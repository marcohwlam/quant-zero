"""
Strategy: H78 IWM/SPY Size Spread Z-Score Daily Timer
Author: Strategy Coder Agent
Date: 2026-06-17
Hypothesis: When the IWM/SPY price ratio 60-day rolling z-score drops below -1.0
            (small-caps underperformed large-caps by >1σ over 60 days), tilt allocation
            toward IWM (60% IWM / 40% SPY), betting on size-premium mean reversion.
            When z > +1.0: SPY-Heavy (40% IWM / 60% SPY). Neutral zone: 50/50.
            SPY 200-DMA regime filter: 100% SHY in bear markets.
            Min 3-day hold per state to prevent whipsaw.

Asset class: US equity ETFs (SPY, IWM), cash (SHY)
Parent task: QUA-325

IS window:  2005-01-01 to 2020-12-31 (16 years; warmup from 2001-01)
OOS window: 2021-01-01 to 2024-12-31 (4 years)

Transaction costs (per AGENTS.md canonical model + ED-SLIP-001 ruling):
  SPY (ultra-liquid, ADV >> 50M/day): $0.005/share + 0.005% slippage + 0.1×σ×sqrt(Q/ADV)
  IWM (ultra-liquid, ADV >> 50M/day): $0.005/share + 0.005% slippage + 0.1×σ×sqrt(Q/ADV)
  SHY (standard, ADV < 50M/day):      $0.005/share + 0.05%  slippage + 0.1×σ×sqrt(Q/ADV)

References:
  Fama-French (1992): size premium in US equities
  Lo & MacKinlay (1990): short-horizon cross-sectional mean reversion, JFE 18(1)
  Faber (2007): 200-DMA trend filter (SSRN 962461)
  ED-SLIP-001: docs/rulings/slippage-spy-large-cap-etf-2026-06-09.md
"""

import argparse
import json
import os
import warnings
from itertools import product

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Universe & Config ─────────────────────────────────────────────────────────

EQUITY_TICKERS = ["SPY", "IWM"]
SAFE_HAVEN     = "SHY"
ALL_TICKERS    = EQUITY_TICKERS + [SAFE_HAVEN]
TRADING_DAYS_PER_YEAR = 252
ULTRA_LIQUID_ADV_THRESHOLD = 50_000_000  # shares/day — ED-SLIP-001

PARAMETERS = {
    "z_lookback":    60,     # Z-score rolling window (calendar trading days)
    "z_threshold":   1.0,    # |Z| boundary between Neutral and Heavy states
    "iwm_heavy_pct": 0.60,   # IWM weight in IWM-Heavy; SPY-Heavy uses 1 - this
    "min_hold_days": 3,      # minimum days in current state before rebalancing
    "dma_window":    200,    # SPY DMA regime filter (days)
    "init_capital":  100_000.0,
}

SWEEP_VALUES = {
    "z_lookback":    [30, 45, 60, 90],
    "z_threshold":   [0.75, 1.0, 1.25, 1.5],
    "iwm_heavy_pct": [0.55, 0.60, 0.65, 0.70],
    "min_hold_days": [2, 3, 5],
    "dma_window":    [150, 200],
}

# Aggressive tilt test per hypothesis § "Additional test"
TILT_TEST_CONFIGS = [
    {"label": "primary_60_40",    "iwm_heavy_pct": 0.60},
    {"label": "aggressive_70_30", "iwm_heavy_pct": 0.70},
    {"label": "aggressive_80_20", "iwm_heavy_pct": 0.80},
]

IS_START   = "2005-01-01"
IS_END     = "2020-12-31"
OOS_START  = "2021-01-01"
OOS_END    = "2024-12-31"
DATA_START = "2001-01-01"   # needs 200d DMA + 60d Z-score warmup before 2005

# Walk-forward: expanding IS windows, 2yr OOS slices within IS period
WF_WINDOWS = [
    ("2005-01-01", "2009-12-31", "2010-01-01", "2011-12-31"),
    ("2005-01-01", "2012-12-31", "2013-01-01", "2014-12-31"),
    ("2005-01-01", "2015-12-31", "2016-01-01", "2017-12-31"),
    ("2005-01-01", "2018-12-31", "2019-01-01", IS_END),
]


# ── Data Loading ──────────────────────────────────────────────────────────────

def download_data(start=DATA_START, end=OOS_END):
    """Download SPY, IWM, SHY daily OHLCV. auto_adjust=True (splits + dividends)."""
    print(f"H78: downloading {ALL_TICKERS} ({start} → {end})...")
    raw = yf.download(ALL_TICKERS, start=start, end=end, auto_adjust=True, progress=False)
    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex columns from yfinance multi-ticker download.")

    close  = raw["Close"][ALL_TICKERS].copy()
    open_  = raw["Open"][ALL_TICKERS].copy()
    volume = raw["Volume"][ALL_TICKERS].copy()

    close  = close.dropna(how="all")
    open_  = open_.reindex(close.index)
    volume = volume.reindex(close.index)
    return {"close": close, "open": open_, "volume": volume}


def check_data_quality(data):
    """Pre-backtest data quality checklist (Engineering Director standard)."""
    close = data["close"]
    report = {
        "survivorship_bias": (
            "Fixed 3-ticker universe: SPY (1993+), IWM (2000-05), SHY (2002-07). "
            "All active ETFs through OOS end 2024. No survivorship bias."
        ),
        "price_adjustment": "yfinance auto_adjust=True — split- and dividend-adjusted.",
        "earnings_exclusion": "N/A — ETF baskets, no single-stock earnings events.",
        "delisted_tickers": "N/A — SPY, IWM, SHY all active through 2024.",
        "tickers": {},
        "flagged": [],
    }
    for ticker in ALL_TICKERS:
        if ticker not in close.columns:
            report["tickers"][ticker] = {"error": "Not in downloaded data"}
            report["flagged"].append(ticker)
            continue
        series = close[ticker]
        clean = series.dropna()
        if len(clean) == 0:
            report["tickers"][ticker] = {"error": "No data"}
            report["flagged"].append(ticker)
            continue
        series_trimmed = series.loc[clean.index[0]:]
        nan_mask = series_trimmed.isna()
        max_consec = consec = 0
        for v in nan_mask:
            consec = (consec + 1) if v else 0
            max_consec = max(max_consec, consec)
        gap_flag = max_consec > 5
        report["tickers"][ticker] = {
            "total_trading_days": int(len(clean)),
            "max_consecutive_missing": max_consec,
            "gap_flag": gap_flag,
            "start": str(clean.index.min().date()),
            "end":   str(clean.index.max().date()),
        }
        if gap_flag:
            report["flagged"].append(ticker)
            warnings.warn(f"Data gap: {ticker} has {max_consec} consecutive missing days (>5).")
    return report


# ── Signal Precomputation ─────────────────────────────────────────────────────

def build_precomputed(data, params):
    """
    Compute all rolling signals — strictly backward-looking, no look-ahead.

    Z-score: (IWM/SPY_today - 60d_mean) / 60d_std.
    Regime: SPY_close > SPY_200d_SMA.
    Sigma: 20d rolling daily return std (market impact formula denominator).
    ADV: 20d rolling avg daily volume (market impact formula denominator).
    """
    close  = data["close"]
    volume = data["volume"]
    z_lb   = params["z_lookback"]
    t_win  = params["dma_window"]

    spy_c = close["SPY"]
    iwm_c = close["IWM"]

    ratio      = iwm_c / spy_c
    ratio_mean = ratio.rolling(z_lb).mean()
    ratio_std  = ratio.rolling(z_lb).std()
    z_score    = (ratio - ratio_mean) / ratio_std

    spy_dma   = spy_c.rolling(t_win).mean()
    spy_above = spy_c > spy_dma

    spy_sigma = spy_c.pct_change().rolling(20).std()
    iwm_sigma = iwm_c.pct_change().rolling(20).std()
    shy_sigma = close["SHY"].pct_change().rolling(20).std()

    spy_adv = volume["SPY"].rolling(20).mean()
    iwm_adv = volume["IWM"].rolling(20).mean()
    shy_adv = volume["SHY"].rolling(20).mean()

    return {
        "z_score":   z_score,
        "spy_above": spy_above,
        "spy_sigma": spy_sigma,
        "iwm_sigma": iwm_sigma,
        "shy_sigma": shy_sigma,
        "spy_adv":   spy_adv,
        "iwm_adv":   iwm_adv,
        "shy_adv":   shy_adv,
    }


def get_signal_state(z_val, spy_above_val, z_thr):
    """Map Z-score + DMA regime flag → portfolio allocation state."""
    if not bool(spy_above_val):
        return "shy"
    if not np.isnan(float(z_val if z_val is not None else np.nan)):
        if z_val < -z_thr:
            return "iwm_heavy"
        if z_val > +z_thr:
            return "spy_heavy"
    return "neutral"


def get_target_weights(state, iwm_heavy_pct):
    """
    Return (spy_w, iwm_w, shy_w) for state.

    iwm_heavy:  (1-iwm_heavy_pct) SPY + iwm_heavy_pct IWM  → 40% SPY / 60% IWM
    neutral:    50% SPY + 50% IWM
    spy_heavy:  iwm_heavy_pct SPY + (1-iwm_heavy_pct) IWM  → 60% SPY / 40% IWM
    shy:        100% SHY
    """
    if state == "shy":
        return (0.0, 0.0, 1.0)
    if state == "iwm_heavy":
        return (1.0 - iwm_heavy_pct, iwm_heavy_pct, 0.0)
    if state == "spy_heavy":
        return (iwm_heavy_pct, 1.0 - iwm_heavy_pct, 0.0)
    return (0.5, 0.5, 0.0)  # neutral


# ── Transaction Cost Model ────────────────────────────────────────────────────

def get_slippage_pct(ticker, adv_shares):
    """
    Per ED-SLIP-001: SPY and IWM are both ultra-liquid (ADV >> 50M/day).
    SHY typical ADV ~20M shares/day → standard 0.05% tier.
    """
    if ticker in ("SPY", "IWM"):
        return 0.00005   # 0.005% — ED-SLIP-001 ultra-liquid ruling
    return 0.0005        # 0.05% — canonical standard tier (SHY)


def compute_nav(holdings, prices):
    """Portfolio NAV = sum(shares × price) + cash."""
    def _p(k):
        v = prices.get(k, 0.0)
        return float(v) if v is not None and not np.isnan(float(v if v is not None else np.nan)) else 0.0
    return (holdings["spy"] * _p("SPY") +
            holdings["iwm"] * _p("IWM") +
            holdings["shy"] * _p("SHY") +
            holdings["cash"])


def execute_rebalance(target_state, iwm_heavy_pct, holdings, prices_open, precomp, t):
    """
    Incremental rebalance to target_state at open prices — only trade the weight delta.
    Sells execute first (free up cash), then buys.

    holdings: {"spy": shares, "iwm": shares, "shy": shares, "cash": $}
    prices_open: {"SPY": $, "IWM": $, "SHY": $}
    Returns (updated_holdings, cost_info).
    """
    def _safe(v, default=0.0):
        try:
            f = float(v)
            return f if not np.isnan(f) else default
        except Exception:
            return default

    spy_p = _safe(prices_open.get("SPY"), 0.0)
    iwm_p = _safe(prices_open.get("IWM"), 0.0)
    shy_p = _safe(prices_open.get("SHY"), 0.0)

    spy_val   = holdings["spy"] * spy_p
    iwm_val   = holdings["iwm"] * iwm_p
    shy_val   = holdings["shy"] * shy_p
    total_nav = spy_val + iwm_val + shy_val + holdings["cash"]

    if total_nav <= 0:
        return holdings.copy(), {"total_cost": 0.0, "cost_bps": 0.0, "nav_before": 0.0}

    spy_w, iwm_w, shy_w = get_target_weights(target_state, iwm_heavy_pct)

    target_vals  = {"spy": total_nav * spy_w, "iwm": total_nav * iwm_w, "shy": total_nav * shy_w}
    current_vals = {"spy": spy_val, "iwm": iwm_val, "shy": shy_val}
    prices       = {"spy": spy_p, "iwm": iwm_p, "shy": shy_p}
    ticker_map   = {"spy": "SPY", "iwm": "IWM", "shy": "SHY"}

    def _precomp_val(series, default):
        try:
            v = series.get(t, default)
            return float(v) if v is not None and not np.isnan(float(v)) else default
        except Exception:
            return default

    sigmas = {
        "spy": _precomp_val(precomp["spy_sigma"], 0.0),
        "iwm": _precomp_val(precomp["iwm_sigma"], 0.0),
        "shy": _precomp_val(precomp["shy_sigma"], 0.0),
    }
    advs = {
        "spy": _precomp_val(precomp["spy_adv"], 1e8),
        "iwm": _precomp_val(precomp["iwm_adv"], 5e7),
        "shy": _precomp_val(precomp["shy_adv"], 2e7),
    }

    new_h = holdings.copy()
    total_cost   = 0.0
    cost_details = {}

    # Two-pass: sells first to free cash, then buys
    for pass_type in ("sell", "buy"):
        for key in ("spy", "iwm", "shy"):
            delta = target_vals[key] - current_vals[key]
            price = prices[key]

            if pass_type == "sell" and delta >= 0:
                continue
            if pass_type == "buy" and delta <= 0:
                continue
            if abs(delta) < 0.01 or price <= 0:
                continue

            ticker = ticker_map[key]
            sigma  = sigmas[key]
            adv    = advs[key]
            shares = abs(delta) / price
            adv_safe = max(adv, 1.0)
            q_adv    = shares / adv_safe
            slippage = get_slippage_pct(ticker, adv)
            impact   = 0.1 * sigma * np.sqrt(max(q_adv, 0.0))
            cost_pct = slippage + impact
            commission = shares * 0.005
            trade_cost = abs(delta) * cost_pct + commission
            total_cost += trade_cost

            liq = q_adv > 0.01
            if liq:
                warnings.warn(f"LIQUIDITY-CONSTRAINED: {ticker} Q/ADV={q_adv:.5f}")

            if delta < 0:  # SELL
                new_h[key]     = max(0.0, new_h[key] - shares)
                new_h["cash"] += (abs(delta) - trade_cost)
            else:  # BUY
                new_h[key]     = new_h[key] + shares
                new_h["cash"] -= (abs(delta) + trade_cost)

            cost_details[ticker] = {
                "notional":   round(abs(delta), 2),
                "shares":     round(shares, 4),
                "slippage_pct": slippage,
                "impact_pct": round(impact, 7),
                "commission": round(commission, 4),
                "trade_cost": round(trade_cost, 4),
                "liq_constrained": liq,
                "adv_tier": "ultra_liquid" if slippage < 0.0001 else "standard",
                "ruling":    "ED-SLIP-001" if slippage < 0.0001 else "canonical",
            }

    cost_bps = total_cost / total_nav * 10_000 if total_nav > 0 else 0.0
    return new_h, {
        "total_cost": round(total_cost, 4),
        "cost_bps":   round(cost_bps, 4),
        "nav_before": round(total_nav, 4),
        "detail":     cost_details,
    }


# ── Portfolio Simulation ──────────────────────────────────────────────────────

def run_simulation(data, precomp, params, start, end):
    """
    Event-driven portfolio simulation for H78.

    Execution model:
    - Signal computed at close of day t (all data strictly backward-looking)
    - Rebalance executes at open of day t+1 (no look-ahead)
    - Portfolio is always fully invested in SPY/IWM/SHY mix or 100% SHY
    - Min hold: min_hold_days must pass in current state before switching

    Trade log: each state period (entry → exit) = one "trade" record.
    pnl_pct per trade = portfolio return over the state hold period.
    """
    close  = data["close"]
    open_  = data["open"]

    z_score   = precomp["z_score"]
    spy_above = precomp["spy_above"]

    z_thr         = params["z_threshold"]
    iwm_heavy_pct = params["iwm_heavy_pct"]
    min_hold      = params["min_hold_days"]
    init_cap      = params["init_capital"]

    window = close.loc[start:end].index
    if len(window) < 10:
        raise ValueError(f"Insufficient data for period {start}:{end}")

    holdings = {"spy": 0.0, "iwm": 0.0, "shy": 0.0, "cash": float(init_cap)}
    current_state = None   # None = awaiting initial allocation
    days_in_state = 0
    pending_state = None   # queued rebalance (executes at next open)

    portfolio_values = pd.Series(index=window, dtype=float)
    trade_log = []
    current_trade = None

    def _px(ticker, px_type, ts):
        src = close if px_type == "close" else open_
        try:
            v = src[ticker].get(ts, np.nan) if ticker in src.columns else np.nan
            return float(v) if v is not None and not pd.isna(v) else np.nan
        except Exception:
            return np.nan

    for i, t in enumerate(window):
        spy_o = _px("SPY", "open", t)
        iwm_o = _px("IWM", "open", t)
        shy_o = _px("SHY", "open", t)
        spy_c = _px("SPY", "close", t)
        iwm_c = _px("IWM", "close", t)
        shy_c = _px("SHY", "close", t)

        prices_open  = {"SPY": spy_o, "IWM": iwm_o, "SHY": shy_o}
        prices_close = {"SPY": spy_c, "IWM": iwm_c, "SHY": shy_c}

        # ── 1. Execute pending rebalance at open ─────────────────────────────
        if pending_state is not None and i > 0:
            nav_before_rebalance = compute_nav(holdings, prices_open)

            # Close previous trade (at pre-rebalance NAV)
            if current_trade is not None:
                hold_i = current_trade.pop("_entry_i")
                current_trade["date_exit"]   = str(t.date())
                current_trade["nav_exit"]    = round(nav_before_rebalance, 4)
                current_trade["hold_days"]   = i - hold_i
                nav_entry = current_trade["nav_entry"]
                pnl_dollar = nav_before_rebalance - nav_entry
                current_trade["pnl_dollar"]  = round(pnl_dollar, 4)
                current_trade["pnl_pct"] = (
                    round(pnl_dollar / nav_entry, 6) if nav_entry > 0 else 0.0
                )
                current_trade["exit_reason"] = "state_change"
                trade_log.append(current_trade)

            holdings, cost_info = execute_rebalance(
                pending_state, iwm_heavy_pct, holdings, prices_open, precomp, t
            )
            nav_after_rebalance = compute_nav(holdings, prices_open)

            # Open new trade (at post-rebalance NAV — costs already deducted)
            current_trade = {
                "date_entry":  str(t.date()),
                "_entry_i":    i,
                "state":       pending_state,
                "nav_entry":   round(nav_after_rebalance, 4),
                "spy_w":       get_target_weights(pending_state, iwm_heavy_pct)[0],
                "iwm_w":       get_target_weights(pending_state, iwm_heavy_pct)[1],
                "shy_w":       get_target_weights(pending_state, iwm_heavy_pct)[2],
                "cost_bps":    cost_info["cost_bps"],
                "date_exit":   None,
                "nav_exit":    None,
                "hold_days":   None,
                "pnl_dollar":  None,
                "pnl_pct":     None,
                "exit_reason": None,
            }

            current_state = pending_state
            days_in_state = 0
            pending_state = None

        # ── 2. Mark-to-market at close ───────────────────────────────────────
        nav = compute_nav(holdings, prices_close)
        if nav <= 0 or np.isnan(nav):
            nav = compute_nav(holdings, prices_open)
        portfolio_values.iloc[i] = max(nav, 0.0)

        # ── 3. Compute signal at close (backward-looking) ─────────────────────
        z_raw = z_score.get(t, np.nan)
        ab_raw = spy_above.get(t, True)
        z_val  = float(z_raw)  if z_raw  is not None and not pd.isna(z_raw)  else np.nan
        ab_val = bool(ab_raw)  if ab_raw is not None else True
        z_valid = not np.isnan(z_val)

        if z_valid:
            desired_state = get_signal_state(z_val, ab_val, z_thr)
        else:
            desired_state = "neutral"  # insufficient warmup data

        # ── 4. Handle initial allocation (no min-hold required) ──────────────
        if current_state is None:
            if z_valid:
                pending_state = desired_state
                current_state = "__pending__"
            continue

        # ── 5. Check state-change eligibility (min-hold enforced) ────────────
        days_in_state += 1

        if pending_state is None and desired_state != current_state:
            if days_in_state >= min_hold:
                pending_state = desired_state

    # ── Close final open trade at period end ─────────────────────────────────
    if current_trade is not None:
        pv_final = portfolio_values.dropna()
        final_nav = float(pv_final.iloc[-1]) if len(pv_final) > 0 else holdings["cash"]
        hold_i = current_trade.pop("_entry_i", 0)
        current_trade["date_exit"]   = str(window[-1].date())
        current_trade["nav_exit"]    = round(final_nav, 4)
        current_trade["hold_days"]   = len(window) - hold_i
        nav_entry = current_trade["nav_entry"]
        pnl_dollar = final_nav - nav_entry
        current_trade["pnl_dollar"]  = round(pnl_dollar, 4)
        current_trade["pnl_pct"] = (
            round(pnl_dollar / nav_entry, 6) if nav_entry > 0 else 0.0
        )
        current_trade["exit_reason"] = "period_end"
        trade_log.append(current_trade)

    portfolio_values = portfolio_values.ffill().fillna(init_cap)
    return {"portfolio_values": portfolio_values, "trade_log": trade_log}


# ── Performance Metrics ───────────────────────────────────────────────────────

def compute_metrics(portfolio_values, trade_log, start, end):
    """Standard performance metrics for H78 allocation strategy."""
    pv = portfolio_values.dropna()
    if len(pv) < 2:
        return {"error": "Insufficient data"}

    daily_ret  = pv.pct_change().fillna(0.0).values
    sharpe = float(
        daily_ret.mean() / (daily_ret.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )

    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    cagr  = float((pv.iloc[-1] / pv.iloc[0]) ** (1.0 / max(years, 0.01)) - 1)
    total_return = float(pv.iloc[-1] / pv.iloc[0] - 1)

    cum = np.cumprod(1 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-10)))

    completed = [t for t in trade_log if t.get("exit_reason") == "state_change"]
    position_switches = len(completed)
    all_trades = trade_log  # each state-period is a "trade"
    trade_count = len(all_trades)

    if all_trades:
        pnl_arr = np.array([t["pnl_pct"] for t in all_trades if t.get("pnl_pct") is not None])
        win_rate = float(np.mean(pnl_arr > 0)) if len(pnl_arr) > 0 else 0.0
        wins   = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        profit_factor = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0
            else float("inf")
        )
        avg_ppt_bps = float(np.mean(pnl_arr) * 10_000) if len(pnl_arr) > 0 else 0.0
        avg_cost_bps = float(np.mean([t.get("cost_bps", 0.0) for t in all_trades]))
    else:
        win_rate = profit_factor = avg_ppt_bps = avg_cost_bps = 0.0

    return {
        "sharpe":            round(sharpe, 4),
        "cagr":              round(cagr, 4),
        "max_drawdown":      round(mdd, 4),
        "total_return":      round(total_return, 4),
        "trade_count":       trade_count,
        "position_switches": position_switches,
        "win_rate":          round(win_rate, 4),
        "profit_factor":     round(profit_factor, 4) if not np.isinf(profit_factor) else "inf",
        "avg_ppt_bps":       round(avg_ppt_bps, 2),
        "avg_cost_bps":      round(avg_cost_bps, 4),
        "period":            f"{start} to {end}",
        "years":             round(years, 2),
    }


# ── Statistical Tests ─────────────────────────────────────────────────────────

def compute_dsr(sharpe, n_trials):
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)."""
    try:
        from scipy import stats
    except ImportError:
        return 0.0
    if n_trials <= 1:
        return float(stats.norm.cdf(sharpe / np.sqrt(1.0 / TRADING_DAYS_PER_YEAR)))
    gamma = 0.5772156649
    e_max = (
        (1 - gamma) * stats.norm.ppf(1 - 1.0 / n_trials)
        + gamma    * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    T = TRADING_DAYS_PER_YEAR
    sr_std = np.sqrt(max((1 + 0 * sharpe - ((3 - 1) / 4) * sharpe ** 2) / (T - 1), 1e-10))
    return round(float(stats.norm.cdf((sharpe - e_max) / sr_std)), 4)


def run_block_bootstrap(portfolio_values, n_boot=1000, block_size=21):
    """Block bootstrap 95% CI for Sharpe and MDD (block_size=21 ≈ 1 month)."""
    daily_ret = portfolio_values.pct_change().fillna(0.0).values
    n = len(daily_ret)
    rng = np.random.default_rng(42)
    sharpes, mdds = [], []
    for _ in range(n_boot):
        n_blocks = n // block_size + 1
        starts = rng.integers(0, max(1, n - block_size), size=n_blocks)
        boot = np.concatenate([daily_ret[s:s + block_size] for s in starts])[:n]
        boot_sharpe = boot.mean() / (boot.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR)
        cum = np.cumprod(1 + boot)
        roll_max = np.maximum.accumulate(cum)
        sharpes.append(boot_sharpe)
        mdds.append(np.min((cum - roll_max) / (roll_max + 1e-10)))
    sharpes, mdds = np.array(sharpes), np.array(mdds)
    return {
        "sharpe_ci_low":  round(float(np.percentile(sharpes, 2.5)),  4),
        "sharpe_ci_high": round(float(np.percentile(sharpes, 97.5)), 4),
        "mdd_ci_low":     round(float(np.percentile(mdds, 2.5)),     4),
        "mdd_ci_high":    round(float(np.percentile(mdds, 97.5)),    4),
    }


def run_permutation_test(trade_log, observed_sharpe, n_perm=500):
    """
    Permutation test: shuffle trade pnl_pct order, recompute Sharpe.
    p-value = fraction of permutations with Sharpe ≥ observed.
    """
    closed = [t for t in trade_log if t.get("exit_reason") == "state_change"]
    if len(closed) < 10:
        return {
            "permutation_pvalue": 1.0,
            "permutation_test_pass": False,
            "permutation_perm_mean": 0.0,
            "permutation_perm_p95": 0.0,
        }
    pnl = np.array([t["pnl_pct"] for t in closed if t.get("pnl_pct") is not None])
    rng = np.random.default_rng(42)
    perm_sharpes = []
    for _ in range(n_perm):
        shuffled = rng.permutation(pnl)
        cum = np.cumprod(1 + shuffled)
        daily = np.diff(cum) / cum[:-1] if len(cum) > 1 else shuffled
        perm_sharpes.append(
            float(daily.mean() / (daily.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR))
        )
    perm_arr = np.array(perm_sharpes)
    p_value = float(np.mean(perm_arr >= observed_sharpe))
    return {
        "permutation_pvalue":      round(p_value, 4),
        "permutation_test_pass":   p_value < 0.05,
        "permutation_perm_mean":   round(float(perm_arr.mean()), 4),
        "permutation_perm_p95":    round(float(np.percentile(perm_arr, 95)), 4),
    }


def run_mc_sharpe(trade_log, n_mc=1000):
    """Monte Carlo Sharpe distribution via bootstrap resampling of trade PnLs."""
    closed = [t for t in trade_log if t.get("exit_reason") == "state_change"]
    if len(closed) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    pnl = np.array([t["pnl_pct"] for t in closed if t.get("pnl_pct") is not None])
    rng = np.random.default_rng(42)
    mc_sharpes = []
    for _ in range(n_mc):
        sample = rng.choice(pnl, size=len(pnl), replace=True)
        cum = np.cumprod(1 + sample)
        daily = np.diff(cum) / cum[:-1] if len(cum) > 1 else sample
        mc_sharpes.append(
            float(daily.mean() / (daily.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR))
        )
    mc = np.array(mc_sharpes)
    return {
        "mc_p5_sharpe":     round(float(np.percentile(mc, 5)),  4),
        "mc_median_sharpe": round(float(np.percentile(mc, 50)), 4),
        "mc_p95_sharpe":    round(float(np.percentile(mc, 95)), 4),
        "mc_flag":          f"MC resampling on {len(closed)} IS closed state periods",
    }


# ── Walk-Forward Analysis ─────────────────────────────────────────────────────

def run_walk_forward(data, params):
    """
    Expanding IS / fixed OOS walk-forward over 4 windows within the IS period.
    A window PASSES if OOS Sharpe > 0.70.
    """
    results = []
    for is_s, is_e, oos_s, oos_e in WF_WINDOWS:
        try:
            # Reuse precomputed signals with IS params
            precomp = build_precomputed(data, params)
            is_sim  = run_simulation(data, precomp, params, is_s, is_e)
            oos_sim = run_simulation(data, precomp, params, oos_s, oos_e)
            is_m    = compute_metrics(is_sim["portfolio_values"], is_sim["trade_log"], is_s, is_e)
            oos_m   = compute_metrics(oos_sim["portfolio_values"], oos_sim["trade_log"], oos_s, oos_e)
            oos_s_val = oos_m["sharpe"]
            passed    = isinstance(oos_s_val, float) and oos_s_val > 0.70
            results.append({
                "is_period":    f"{is_s} to {is_e}",
                "oos_period":   f"{oos_s} to {oos_e}",
                "is_sharpe":    is_m["sharpe"],
                "oos_sharpe":   oos_s_val,
                "is_mdd":       is_m["max_drawdown"],
                "oos_mdd":      oos_m["max_drawdown"],
                "is_trades":    is_m["trade_count"],
                "oos_trades":   oos_m["trade_count"],
                "pass":         passed,
            })
        except Exception as exc:
            results.append({
                "is_period":  f"{is_s} to {is_e}",
                "oos_period": f"{oos_s} to {oos_e}",
                "error":      str(exc),
                "pass":       False,
            })
    return results


# ── Parameter Sweep ───────────────────────────────────────────────────────────

def scan_parameters(data):
    """
    IS-only sweep over all combinations of SWEEP_VALUES.
    Total: 4 × 4 × 4 × 3 × 2 = 384 combinations.
    """
    keys   = list(SWEEP_VALUES.keys())
    vals   = list(SWEEP_VALUES.values())
    results = []
    for combo in product(*vals):
        p = {**PARAMETERS, **dict(zip(keys, combo))}
        try:
            precomp = build_precomputed(data, p)
            sim     = run_simulation(data, precomp, p, IS_START, IS_END)
            m       = compute_metrics(sim["portfolio_values"], sim["trade_log"], IS_START, IS_END)
            results.append({
                "z_lookback":    p["z_lookback"],
                "z_threshold":   p["z_threshold"],
                "iwm_heavy_pct": p["iwm_heavy_pct"],
                "min_hold_days": p["min_hold_days"],
                "dma_window":    p["dma_window"],
                **{k: v for k, v in m.items() if k not in ("period", "years")},
            })
        except Exception as exc:
            results.append({
                "z_lookback":    p["z_lookback"],
                "z_threshold":   p["z_threshold"],
                "iwm_heavy_pct": p["iwm_heavy_pct"],
                "min_hold_days": p["min_hold_days"],
                "dma_window":    p["dma_window"],
                "error":         str(exc),
            })
    return results


def sweep_stability_summary(sweep_results):
    """Compute Sharpe range across sweep; flag if variance > 30% of primary."""
    sharpes = [
        r["sharpe"] for r in sweep_results
        if "sharpe" in r and isinstance(r["sharpe"], (int, float))
    ]
    if not sharpes:
        return {"error": "No valid sweep results"}
    primary = next(
        (r["sharpe"] for r in sweep_results
         if r.get("z_lookback")    == PARAMETERS["z_lookback"]
         and r.get("z_threshold")   == PARAMETERS["z_threshold"]
         and r.get("iwm_heavy_pct") == PARAMETERS["iwm_heavy_pct"]
         and r.get("min_hold_days") == PARAMETERS["min_hold_days"]
         and r.get("dma_window")    == PARAMETERS["dma_window"]),
        None,
    )
    sharpe_range = max(sharpes) - min(sharpes)
    variance_pct = sharpe_range / abs(primary) if primary and primary != 0 else float("nan")
    return {
        "primary_sharpe":    primary,
        "sharpe_min":        round(min(sharpes), 4),
        "sharpe_max":        round(max(sharpes), 4),
        "sharpe_range":      round(sharpe_range, 4),
        "sharpe_variance_pct": round(variance_pct, 4) if not np.isnan(variance_pct) else None,
        "sensitivity_pass":  (not np.isnan(variance_pct)) and variance_pct <= 0.30,
        "n_combinations":    len(sharpes),
    }


# ── Tilt Test ─────────────────────────────────────────────────────────────────

def run_tilt_test(data, base_params):
    """
    Run IS+OOS with primary (60/40), aggressive (70/30), and ultra (80/20) tilts.
    Reports Sharpe vs MDD tradeoff for each tilt config.
    """
    results = []
    for cfg in TILT_TEST_CONFIGS:
        p = {**base_params, "iwm_heavy_pct": cfg["iwm_heavy_pct"]}
        try:
            precomp = build_precomputed(data, p)
            is_sim  = run_simulation(data, precomp, p, IS_START, IS_END)
            oos_sim = run_simulation(data, precomp, p, OOS_START, OOS_END)
            is_m    = compute_metrics(is_sim["portfolio_values"], is_sim["trade_log"], IS_START, IS_END)
            oos_m   = compute_metrics(oos_sim["portfolio_values"], oos_sim["trade_log"], OOS_START, OOS_END)
            results.append({
                "label":            cfg["label"],
                "iwm_heavy_pct":    cfg["iwm_heavy_pct"],
                "spy_heavy_pct":    round(1.0 - cfg["iwm_heavy_pct"], 2),
                "is_sharpe":        is_m["sharpe"],
                "is_cagr_pct":      round(is_m["cagr"] * 100, 2),
                "is_mdd_pct":       round(is_m["max_drawdown"] * 100, 2),
                "is_trades":        is_m["trade_count"],
                "oos_sharpe":       oos_m["sharpe"],
                "oos_cagr_pct":     round(oos_m["cagr"] * 100, 2),
                "oos_mdd_pct":      round(oos_m["max_drawdown"] * 100, 2),
            })
        except Exception as exc:
            results.append({"label": cfg["label"], "error": str(exc)})
    return results


# ── Market Impact Report ──────────────────────────────────────────────────────

def compute_market_impact_report(data, params):
    """Per-ETF market impact at $100K, given IS avg price and 20d ADV."""
    close  = data["close"]
    volume = data["volume"]
    report = {}

    spy_w, iwm_w, shy_w = get_target_weights("iwm_heavy", params["iwm_heavy_pct"])
    alloc = {"SPY": spy_w, "IWM": iwm_w, "SHY": shy_w}

    for ticker in ALL_TICKERS:
        if ticker not in close.columns:
            continue
        is_c   = close[ticker].loc[IS_START:IS_END].dropna()
        is_vol = volume[ticker].loc[IS_START:IS_END].dropna()
        if len(is_c) < 20 or len(is_vol) < 20:
            continue
        avg_px  = float(is_c.mean())
        adv_20d = float(is_vol.rolling(20).mean().dropna().mean())
        if avg_px <= 0 or adv_20d <= 0:
            continue
        notional = 100_000 * alloc.get(ticker, 0.10)
        qty = notional / avg_px
        sigma_daily = float(is_c.pct_change().std())
        q_adv = qty / adv_20d
        impact_bps = round(0.1 * sigma_daily * np.sqrt(max(q_adv, 0.0)) * 10_000, 4)
        slippage = get_slippage_pct(ticker, adv_20d)
        report[ticker] = {
            "notional":        round(notional, 2),
            "avg_price":       round(avg_px, 2),
            "qty":             round(qty, 1),
            "adv_20d":         round(adv_20d, 0),
            "q_over_adv":      round(q_adv, 7),
            "impact_bps":      impact_bps,
            "slippage_pct":    slippage,
            "adv_tier":        "ultra_liquid" if slippage < 0.0001 else "standard",
            "liq_constrained": q_adv > 0.01,
        }
    return report


# ── HTML Report ───────────────────────────────────────────────────────────────

def generate_html_report(
    is_metrics, oos_metrics, stat_tests, wf_windows,
    sweep_stab, gate_checks, tilt_test, n_passed, gate1_pass,
):
    """Generate self-contained HTML Gate 1 report."""
    gate_rows = "".join(
        f"<tr><td>{'✅' if v else '❌'}</td><td>{k}</td><td>{d}</td></tr>"
        for k, (v, d) in gate_checks.items()
    )
    wf_rows = "".join(
        f"<tr><td>{i+1}</td><td>{w.get('is_period','')}</td>"
        f"<td>IS: {w.get('is_sharpe','N/A')}</td>"
        f"<td>OOS: {w.get('oos_sharpe','N/A')}</td>"
        f"<td>{'✅ PASS' if w.get('pass') else '❌ FAIL'}</td></tr>"
        for i, w in enumerate(wf_windows)
    )
    tilt_rows = "".join(
        f"<tr><td>{r.get('label')}</td><td>{r.get('iwm_heavy_pct','-'):.0%} / {r.get('spy_heavy_pct','-'):.0%}</td>"
        f"<td>{r.get('is_sharpe','N/A')}</td><td>{r.get('is_cagr_pct','N/A')}%</td>"
        f"<td>{r.get('is_mdd_pct','N/A')}%</td>"
        f"<td>{r.get('oos_sharpe','N/A')}</td><td>{r.get('oos_mdd_pct','N/A')}%</td></tr>"
        for r in tilt_test if "error" not in r
    )
    result_label = "✅ PASS" if gate1_pass else "❌ FAIL"
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>H78 IWM/SPY Size Spread Z-Score Timer — Gate 1</title>
<style>
body{{font-family:monospace;margin:30px;background:#f9f9f9}}
h1{{color:#2c3e50}}h2{{color:#34495e;border-bottom:1px solid #ccc}}
table{{border-collapse:collapse;width:100%;margin-bottom:20px}}
th{{background:#2c3e50;color:white;padding:6px 10px;text-align:left}}
td{{padding:5px 10px;border:1px solid #ddd}}
tr:nth-child(even){{background:#f2f2f2}}
.pass{{color:green;font-weight:bold}}.fail{{color:red;font-weight:bold}}
.verdict{{font-size:1.4em;font-weight:bold;padding:10px;border-radius:4px;
          background:{'#d4edda' if gate1_pass else '#f8d7da'};
          color:{'#155724' if gate1_pass else '#721c24'}}}
</style></head><body>
<h1>H78 IWM/SPY Size Spread Z-Score Daily Timer — Gate 1 Report</h1>
<div class="verdict">Overall: {result_label} ({n_passed}/{len(gate_checks)} checks passed)</div>
<h2>Strategy</h2>
<p>Universe: SPY, IWM (equity positions), SHY (cash). Signal: 60-day rolling Z-score of IWM/SPY ratio.
States: IWM-Heavy (60% IWM/40% SPY) when Z&lt;-1.0; Neutral (50/50); SPY-Heavy (40/60) when Z&gt;+1.0.
Regime filter: 100% SHY when SPY &lt; 200-DMA. Min hold: 3 days.</p>
<h2>IS Performance ({IS_START} to {IS_END}, {is_metrics.get('years','?')} years)</h2>
<table>
<tr><th>Metric</th><th>IS</th><th>OOS ({OOS_START}–{OOS_END})</th></tr>
<tr><td>Sharpe</td><td>{is_metrics.get('sharpe')}</td><td>{oos_metrics.get('sharpe')}</td></tr>
<tr><td>CAGR</td><td>{is_metrics.get('cagr',0)*100:.2f}%</td><td>{oos_metrics.get('cagr',0)*100:.2f}%</td></tr>
<tr><td>Max Drawdown</td><td>{is_metrics.get('max_drawdown',0)*100:.2f}%</td><td>{oos_metrics.get('max_drawdown',0)*100:.2f}%</td></tr>
<tr><td>Win Rate</td><td>{is_metrics.get('win_rate',0)*100:.1f}%</td><td>{oos_metrics.get('win_rate',0)*100:.1f}%</td></tr>
<tr><td>Profit Factor</td><td>{is_metrics.get('profit_factor')}</td><td>{oos_metrics.get('profit_factor')}</td></tr>
<tr><td>Trade Count (state periods)</td><td>{is_metrics.get('trade_count')}</td><td>{oos_metrics.get('trade_count')}</td></tr>
<tr><td>Position Switches</td><td>{is_metrics.get('position_switches')}</td><td>{oos_metrics.get('position_switches')}</td></tr>
<tr><td>Avg PpT (bps)</td><td>{is_metrics.get('avg_ppt_bps')}</td><td>{oos_metrics.get('avg_ppt_bps')}</td></tr>
<tr><td>Avg Cost (bps/rebalance)</td><td>{is_metrics.get('avg_cost_bps')}</td><td>{oos_metrics.get('avg_cost_bps')}</td></tr>
</table>
<h2>Statistical Rigor</h2>
<table>
<tr><td>MC p5 Sharpe</td><td>{stat_tests.get('mc_p5_sharpe')}</td></tr>
<tr><td>MC Median Sharpe</td><td>{stat_tests.get('mc_median_sharpe')}</td></tr>
<tr><td>Sharpe 95% CI</td><td>[{stat_tests.get('sharpe_ci_low',0):.4f}, {stat_tests.get('sharpe_ci_high',0):.4f}]</td></tr>
<tr><td>MDD 95% CI</td><td>[{stat_tests.get('mdd_ci_low',0)*100:.2f}%, {stat_tests.get('mdd_ci_high',0)*100:.2f}%]</td></tr>
<tr><td>Permutation p-value</td><td>{stat_tests.get('permutation_pvalue')}</td></tr>
<tr><td>DSR</td><td>{stat_tests.get('dsr')}</td></tr>
</table>
<h2>Walk-Forward (4 expanding IS windows, 2yr OOS each)</h2>
<table><tr><th>#</th><th>IS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>Result</th></tr>
{wf_rows}</table>
<h2>Tilt Test: Sharpe vs MDD Tradeoff</h2>
<table><tr><th>Config</th><th>IWM/SPY Split</th><th>IS Sharpe</th><th>IS CAGR</th><th>IS MDD</th><th>OOS Sharpe</th><th>OOS MDD</th></tr>
{tilt_rows}</table>
<h2>Sensitivity Sweep ({sweep_stab.get('n_combinations',0)} combos)</h2>
<p>Sharpe range: {sweep_stab.get('sharpe_min')} – {sweep_stab.get('sharpe_max')} |
Variance vs primary: {(sweep_stab.get('sharpe_variance_pct') or 0)*100:.1f}% |
{'✅ PASS: ≤30%' if sweep_stab.get('sensitivity_pass') else '❌ FAIL: >30%'}</p>
<h2>Gate 1 Checks</h2>
<table><tr><th>Pass</th><th>Gate</th><th>Details</th></tr>{gate_rows}</table>
</body></html>"""
    return html


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_strategy(params=None, output_dir=None, run_sweep=True):
    """
    Full IS+OOS Gate 1 backtest for H78 IWM/SPY Size Spread Z-Score Timer.

    Downloads data once, runs IS+OOS simulation with primary params,
    runs tilt test (60/40, 70/30, 80/20), optional 384-combo sweep,
    runs statistical tests (DSR, block bootstrap, permutation, MC),
    writes trade log CSV, sweep CSV, metrics JSON, verdict TXT, HTML report.
    """
    if params is None:
        params = PARAMETERS.copy()

    # ── Data ─────────────────────────────────────────────────────────────────
    data = download_data(DATA_START, OOS_END)
    quality = check_data_quality(data)
    if quality["flagged"]:
        warnings.warn(f"Data quality flags: {quality['flagged']}")

    # ── Primary IS backtest ──────────────────────────────────────────────────
    print(f"H78: building precomputed signals (z_lb={params['z_lookback']}, "
          f"threshold={params['z_threshold']}, dma={params['dma_window']})...")
    precomp = build_precomputed(data, params)

    print(f"H78: running IS backtest ({IS_START} → {IS_END})...")
    is_sim  = run_simulation(data, precomp, params, IS_START, IS_END)
    is_metrics = compute_metrics(is_sim["portfolio_values"], is_sim["trade_log"], IS_START, IS_END)

    # ── Primary OOS backtest ─────────────────────────────────────────────────
    print(f"H78: running OOS backtest ({OOS_START} → {OOS_END})...")
    oos_sim = run_simulation(data, precomp, params, OOS_START, OOS_END)
    oos_metrics = compute_metrics(oos_sim["portfolio_values"], oos_sim["trade_log"], OOS_START, OOS_END)

    # ── Statistical tests ────────────────────────────────────────────────────
    print("H78: running statistical tests (DSR, bootstrap, permutation, MC)...")
    n_trials = sum(len(v) for v in SWEEP_VALUES.values())  # ~ number of param variations
    dsr  = compute_dsr(is_metrics["sharpe"], n_trials)
    boot = run_block_bootstrap(is_sim["portfolio_values"])
    perm = run_permutation_test(is_sim["trade_log"], is_metrics["sharpe"])
    mc   = run_mc_sharpe(is_sim["trade_log"])
    stat_tests = {"dsr": dsr, **boot, **perm, **mc}

    # ── Walk-forward ─────────────────────────────────────────────────────────
    print("H78: running walk-forward (4 expanding windows)...")
    wf_windows  = run_walk_forward(data, params)
    wf_passed   = sum(1 for w in wf_windows if w.get("pass"))
    wf_sharpes  = [w["oos_sharpe"] for w in wf_windows if isinstance(w.get("oos_sharpe"), float)]
    wf_sharpe_std = float(np.std(wf_sharpes)) if len(wf_sharpes) > 1 else 0.0
    wf_sharpe_min = float(min(wf_sharpes)) if wf_sharpes else 0.0

    # ── Tilt test ─────────────────────────────────────────────────────────────
    print("H78: running tilt test (60/40, 70/30, 80/20)...")
    tilt_test = run_tilt_test(data, params)

    # ── Parameter sweep ───────────────────────────────────────────────────────
    sweep_results = []
    stability = {}
    if run_sweep:
        print("H78: running 384-combination parameter sweep on IS (this may take a few minutes)...")
        sweep_results = scan_parameters(data)
        stability = sweep_stability_summary(sweep_results)
        vp = stability.get("sharpe_variance_pct")
        print(f"H78: sweep done — {stability.get('n_combinations')} combos | "
              f"Sharpe {stability.get('sharpe_min')}–{stability.get('sharpe_max')} | "
              f"variance {f'{vp*100:.1f}%' if vp else 'N/A'}")

    # ── Market impact ─────────────────────────────────────────────────────────
    mi_report = compute_market_impact_report(data, params)

    # ── Gate 1 evaluation ─────────────────────────────────────────────────────
    gate_checks = {
        "IS Sharpe > 1.0": (
            is_metrics["sharpe"] > 1.0,
            f"{is_metrics['sharpe']} (threshold: > 1.0)"
        ),
        "OOS Sharpe > 0.70": (
            oos_metrics["sharpe"] > 0.70,
            f"{oos_metrics['sharpe']} (threshold: > 0.70)"
        ),
        "IS CAGR >= 10%": (
            is_metrics["cagr"] >= 0.10,
            f"{is_metrics['cagr']*100:.2f}% (threshold: >= 10%)"
        ),
        "IS MDD > -20%": (
            is_metrics["max_drawdown"] > -0.20,
            f"{is_metrics['max_drawdown']*100:.2f}% (threshold: > -20%)"
        ),
        "OOS MDD > -20%": (
            oos_metrics["max_drawdown"] > -0.20,
            f"{oos_metrics['max_drawdown']*100:.2f}% (threshold: > -20%)"
        ),
        "IS Trade Count >= 100": (
            is_metrics["trade_count"] >= 100,
            f"{is_metrics['trade_count']} state periods (threshold: >= 100)"
        ),
        "Walk-Forward >= 3/4": (
            wf_passed >= 3,
            f"{wf_passed}/{len(wf_windows)} windows pass OOS Sharpe > 0.70"
        ),
        "Permutation p < 0.05": (
            perm["permutation_pvalue"] < 0.05,
            f"p = {perm['permutation_pvalue']} (threshold: < 0.05)"
        ),
        "DSR > 0": (
            dsr > 0,
            f"DSR = {dsr} (threshold: > 0)"
        ),
        "IS Switches >= 60": (
            is_metrics["position_switches"] >= 60,
            f"{is_metrics['position_switches']} switches (threshold: >= 60)"
        ),
    }
    n_passed    = sum(1 for v, _ in gate_checks.values() if v)
    gate1_pass  = n_passed == len(gate_checks)

    # ── Console summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"{'H78 IWM/SPY Size Spread Z-Score Timer — Summary':^70}")
    print("=" * 70)
    print(f"{'Metric':<25} {'IS (2005-2020)':>20} {'OOS (2021-2024)':>20}")
    print("-" * 70)
    for key in ("sharpe", "cagr", "max_drawdown", "win_rate", "trade_count", "position_switches", "avg_ppt_bps"):
        iv = is_metrics.get(key, "N/A")
        ov = oos_metrics.get(key, "N/A")
        if key in ("cagr", "max_drawdown", "win_rate") and isinstance(iv, float):
            iv = f"{iv*100:.2f}%"
            ov = f"{ov*100:.2f}%" if isinstance(ov, float) else ov
        print(f"{key:<25} {str(iv):>20} {str(ov):>20}")
    print("=" * 70)
    print(f"Gate 1: {'PASS' if gate1_pass else 'FAIL'} ({n_passed}/{len(gate_checks)} checks)")
    print(f"DSR: {dsr} | Permutation p: {perm['permutation_pvalue']} | MC p5: {mc.get('mc_p5_sharpe','N/A')}")
    print(f"WF: {wf_passed}/4 pass | WF Sharpe std: {wf_sharpe_std:.4f} | WF min: {wf_sharpe_min:.4f}")
    if stability:
        vp = stability.get("sharpe_variance_pct")
        print(f"Sweep: {stability.get('n_combinations')} combos | "
              f"Sharpe {stability.get('sharpe_min')}–{stability.get('sharpe_max')} | "
              f"variance {f'{vp*100:.1f}%' if vp else 'N/A'}")
    print("\nTilt Test:")
    for r in tilt_test:
        if "error" not in r:
            print(f"  {r['label']:<25} IS Sharpe={r['is_sharpe']}  IS MDD={r['is_mdd_pct']}%  "
                  f"OOS Sharpe={r['oos_sharpe']}")
    print()

    # ── Output files ──────────────────────────────────────────────────────────
    today_str  = pd.Timestamp.now().strftime("%Y-%m-%d")
    all_trades = is_sim["trade_log"] + oos_sim["trade_log"]

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        base = f"H78_IWMSPYSizeSpreadZScoreTimer_{today_str}"

        # Trade log CSV
        if all_trades:
            trade_df = pd.DataFrame(all_trades)
            cols = [
                "date_entry", "date_exit", "state", "spy_w", "iwm_w", "shy_w",
                "nav_entry", "nav_exit", "pnl_pct", "pnl_dollar",
                "hold_days", "exit_reason", "cost_bps",
            ]
            trade_df = trade_df[[c for c in cols if c in trade_df.columns]]
            csv_path = os.path.join(output_dir, f"{base}_trades.csv")
            trade_df.to_csv(csv_path, index=False)
            print(f"Trades:  {csv_path} ({len(trade_df)} records)")

        # Sweep CSV
        if sweep_results:
            sweep_df   = pd.DataFrame(sweep_results)
            sweep_path = os.path.join(output_dir, f"{base}_sweep.csv")
            sweep_df.to_csv(sweep_path, index=False)
            print(f"Sweep:   {sweep_path}")

        # Metrics JSON
        json_output = {
            "strategy_name": "H78_IWMSPYSizeSpreadZScoreTimer",
            "date":          today_str,
            "hypothesis":    "H78",
            "asset_class":   "equities_etf",
            "parent_task":   "QUA-325",
            "universe":      ALL_TICKERS,
            "parameters": {k: v for k, v in params.items() if k != "init_capital"},
            "initial_capital": params["init_capital"],
            "cost_model": {
                "spy_slippage": "0.005% ultra-liquid (ED-SLIP-001; SPY ADV >> 50M/day)",
                "iwm_slippage": "0.005% ultra-liquid (ED-SLIP-001; IWM ADV >> 50M/day)",
                "shy_slippage": "0.05% standard (SHY ADV ~20M/day < 50M threshold)",
                "commission":   "$0.005/share",
                "market_impact": "0.1 × σ × sqrt(Q/ADV) — Almgren-Chriss square-root model",
                "ruling":       "ED-SLIP-001",
            },
            "is_period":  {"start": IS_START, "end": IS_END},
            "oos_period": {"start": OOS_START, "end": OOS_END},
            "is_metrics":  is_metrics,
            "oos_metrics": oos_metrics,
            "stat_tests":  stat_tests,
            "walk_forward": {
                "windows":      wf_windows,
                "passed":       wf_passed,
                "total":        len(wf_windows),
                "sharpe_std":   round(wf_sharpe_std, 4),
                "sharpe_min":   round(wf_sharpe_min, 4),
            },
            "tilt_test":       tilt_test,
            "sweep_stability": stability,
            "market_impact":   mi_report,
            "data_quality":    quality,
            "gate1_checks":    {k: {"pass": v, "detail": d} for k, (v, d) in gate_checks.items()},
            "gate1_pass":      gate1_pass,
            "gate1_n_passed":  n_passed,
            "gate1_n_total":   len(gate_checks),
        }
        json_path = os.path.join(output_dir, f"{base}.json")
        with open(json_path, "w") as f:
            json.dump(json_output, f, indent=2, default=str)
        print(f"Metrics: {json_path}")

        # HTML report
        html = generate_html_report(
            is_metrics, oos_metrics, stat_tests, wf_windows,
            stability, gate_checks, tilt_test, n_passed, gate1_pass,
        )
        html_path = os.path.join(output_dir, f"{base}_report.html")
        with open(html_path, "w") as f:
            f.write(html)
        print(f"Report:  {html_path}")

        # Verdict TXT
        verdict_lines = [
            f"H78 IWM/SPY Size Spread Z-Score Timer — Gate 1 Verdict",
            "=" * 60,
            f"Date:     {today_str}",
            f"Strategy: H78_IWMSPYSizeSpreadZScoreTimer",
            f"Overall:  {'PASS' if gate1_pass else 'FAIL'} ({n_passed}/{len(gate_checks)} checks passed)",
            "=" * 60,
            "",
            f"=== Universe ===",
            f"Instruments:   SPY (large-cap), IWM (small-cap), SHY (cash)",
            f"Signal:        60d rolling Z-score of IWM/SPY price ratio",
            f"States:        IWM-Heavy (60/40) | Neutral (50/50) | SPY-Heavy (40/60) | SHY (100%)",
            f"Regime filter: SPY 200-DMA → 100% SHY in downtrend",
            f"Min hold:      3 trading days per state",
            "",
            f"=== IS Performance ({IS_START} to {IS_END}, {is_metrics.get('years','?')} years) ===",
            f"Sharpe:              {is_metrics.get('sharpe')}    [{'PASS' if gate_checks['IS Sharpe > 1.0'][0] else 'FAIL'}: > 1.0]",
            f"CAGR:                {is_metrics.get('cagr',0)*100:.2f}%    [{'PASS' if gate_checks['IS CAGR >= 10%'][0] else 'FAIL'}: >= 10%]",
            f"Max Drawdown:        {is_metrics.get('max_drawdown',0)*100:.2f}%    [{'PASS' if gate_checks['IS MDD > -20%'][0] else 'FAIL'}: > -20%]",
            f"Win Rate:            {is_metrics.get('win_rate',0)*100:.1f}%",
            f"Profit Factor:       {is_metrics.get('profit_factor')}",
            f"Trade Count:         {is_metrics.get('trade_count')}    [{'PASS' if gate_checks['IS Trade Count >= 100'][0] else 'FAIL'}: >= 100]",
            f"Position Switches:   {is_metrics.get('position_switches')}    [{'PASS' if gate_checks['IS Switches >= 60'][0] else 'FAIL'}: >= 60]",
            f"Avg PpT:             {is_metrics.get('avg_ppt_bps')} bps",
            f"Avg Rebalance Cost:  {is_metrics.get('avg_cost_bps')} bps",
            "",
            f"=== OOS Performance ({OOS_START} to {OOS_END}, {oos_metrics.get('years','?')} years) ===",
            f"Sharpe:              {oos_metrics.get('sharpe')}  [{'PASS' if gate_checks['OOS Sharpe > 0.70'][0] else 'FAIL'}: > 0.70]",
            f"CAGR:                {oos_metrics.get('cagr',0)*100:.2f}%",
            f"Max Drawdown:        {oos_metrics.get('max_drawdown',0)*100:.2f}%  [{'PASS' if gate_checks['OOS MDD > -20%'][0] else 'FAIL'}: > -20%]",
            f"Win Rate:            {oos_metrics.get('win_rate',0)*100:.1f}%",
            f"Trade Count:         {oos_metrics.get('trade_count')}",
            "",
            f"=== Statistical Rigor ===",
            f"MC p5 Sharpe:        {mc.get('mc_p5_sharpe','N/A')}",
            f"MC Median Sharpe:    {mc.get('mc_median_sharpe','N/A')}",
            f"Sharpe 95% CI:       [{boot.get('sharpe_ci_low',0):.4f}, {boot.get('sharpe_ci_high',0):.4f}]  (block bootstrap)",
            f"MDD 95% CI:          [{boot.get('mdd_ci_low',0)*100:.2f}%, {boot.get('mdd_ci_high',0)*100:.2f}%]",
            f"Permutation p-value: {perm.get('permutation_pvalue','N/A')}    [{'PASS' if gate_checks['Permutation p < 0.05'][0] else 'FAIL'}: < 0.05]",
            f"DSR:                 {dsr}    [{'PASS' if gate_checks['DSR > 0'][0] else 'FAIL'}: > 0]",
            "",
            f"=== Walk-Forward (4 windows, expanding IS / 2yr OOS) ===",
            f"Passed: {wf_passed}/4    [{'PASS' if gate_checks['Walk-Forward >= 3/4'][0] else 'FAIL'}: >= 3/4]",
            f"WF OOS Sharpe std: {wf_sharpe_std:.4f}",
            f"WF OOS Sharpe min: {wf_sharpe_min:.4f}",
        ]
        for i, w in enumerate(wf_windows):
            verdict_lines.append(
                f"Window {i+1}: IS {w.get('is_period','')} | OOS {w.get('oos_period','')}"
            )
            verdict_lines.append(
                f"  IS Sharpe: {w.get('is_sharpe','N/A')}, OOS Sharpe: {w.get('oos_sharpe','N/A')}"
                f", {'PASS' if w.get('pass') else 'FAIL'}"
            )
        verdict_lines += [
            "",
            f"=== Tilt Test (Sharpe vs MDD Tradeoff) ===",
        ]
        for r in tilt_test:
            if "error" not in r:
                verdict_lines.append(
                    f"{r['label']:<25} IS Sharpe={r['is_sharpe']}  IS MDD={r['is_mdd_pct']}%  "
                    f"OOS Sharpe={r['oos_sharpe']}  OOS MDD={r['oos_mdd_pct']}%"
                )
        if stability:
            vp = stability.get("sharpe_variance_pct")
            verdict_lines += [
                "",
                f"=== Sweep Stability ({stability.get('n_combinations')} combos) ===",
                f"Sharpe range:   {stability.get('sharpe_min')} – {stability.get('sharpe_max')}",
                f"Variance:       {f'{vp*100:.1f}%' if vp else 'N/A'}  "
                f"[{'PASS' if stability.get('sensitivity_pass') else 'FAIL'}: <= 30%]",
            ]

        verdict_lines += [
            "",
            f"=== Market Impact ===",
        ]
        for ticker, mi in mi_report.items():
            verdict_lines.append(
                f"{ticker}: {mi.get('impact_bps')} bps (Q/ADV: {mi.get('q_over_adv'):.6f})  "
                f"ADV tier: {mi.get('adv_tier')}"
            )

        verdict_path = os.path.join(output_dir, f"{base}_verdict.txt")
        with open(verdict_path, "w") as f:
            f.write("\n".join(verdict_lines))
        print(f"Verdict: {verdict_path}")

    return {
        "is":              is_metrics,
        "oos":             oos_metrics,
        "stat_tests":      stat_tests,
        "walk_forward":    wf_windows,
        "tilt_test":       tilt_test,
        "sweep_stability": stability,
        "data_quality":    quality,
        "gate1_pass":      gate1_pass,
        "gate1_n_passed":  n_passed,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="H78 IWM/SPY Size Spread Z-Score Daily Timer — Gate 1 Backtest"
    )
    parser.add_argument("--z-lookback", type=int, default=PARAMETERS["z_lookback"],
                        help="Z-score rolling window in trading days (default: 60)")
    parser.add_argument("--z-threshold", type=float, default=PARAMETERS["z_threshold"],
                        help="Z-score magnitude to change state (default: 1.0)")
    parser.add_argument("--iwm-heavy-pct", type=float, default=PARAMETERS["iwm_heavy_pct"],
                        help="IWM weight in IWM-Heavy state (default: 0.60)")
    parser.add_argument("--min-hold", type=int, default=PARAMETERS["min_hold_days"],
                        help="Min days in state before rebalance (default: 3)")
    parser.add_argument("--dma-window", type=int, default=PARAMETERS["dma_window"],
                        help="SPY DMA regime filter window (default: 200)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory for CSV/JSON/HTML/TXT files")
    parser.add_argument("--no-sweep", action="store_true",
                        help="Skip the 384-combo parameter sweep (faster)")
    args = parser.parse_args()

    p = {
        **PARAMETERS,
        "z_lookback":    args.z_lookback,
        "z_threshold":   args.z_threshold,
        "iwm_heavy_pct": args.iwm_heavy_pct,
        "min_hold_days": args.min_hold,
        "dma_window":    args.dma_window,
    }
    run_strategy(params=p, output_dir=args.output_dir, run_sweep=not args.no_sweep)
