"""
Strategy: H69 SPY/TLT Bond-Equity Ratio Mean Reversion
Author: Strategy Coder Agent
Date: 2026-06-15
Hypothesis: When the SPY/TLT price ratio z-score diverges beyond ±1.0 sigma, institutional
            TDF rebalancing flows create predictable mean-reversion pressure. Long SPY when
            z < -entry_threshold AND SPY above 200-DMA. Long TLT when z > +entry_threshold
            AND TLT above 200-DMA. Cash otherwise. Exit on z-revert, 200-DMA breach, or
            time stop.
Asset class: multi-asset (US large-cap equity + US long-term treasuries)
Parent task: QUA-289

IS window:  2004-01-01 to 2020-12-31 (warmup from 2002-07-01, TLT inception)
OOS window: 2021-01-01 to 2024-12-31

Data: SPY + TLT daily OHLCV, yfinance auto_adjust=True
Capital: $100,000 starting capital. No leverage. No shorting. One position at a time.

Transaction cost model (per ED-SLIP-001 ruling and canonical AGENTS.md):
  SPY (ultra-liquid, ADV > 50M): $0.005/share + 0.005% slippage + market impact
  TLT (standard, ADV ~15-30M):  $0.005/share + 0.05%  slippage + market impact
  Market impact: 0.1 × σ × sqrt(Q / ADV) — Almgren-Chriss square-root model
  Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True in trade log

Alpha mechanism: TDF rebalancing flows are mandated, non-discretionary, and cannot be
                 arbitraged away. Signal orthogonal to momentum (per PF-1 assessment).
References:
  Faber (2007): 200-DMA trend filter — SSRN 962461
  Cici et al. (2017): TDF rebalancing flows — Review of Finance 22(3)
  ED-SLIP-001 ruling: docs/rulings/slippage-spy-large-cap-etf-2026-06-09.md
"""

import argparse
import json
import os
import warnings
from itertools import product

import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ──────────────────────────────────────────────────────────────────

PARAMETERS = {
    "z_lookback": 252,       # rolling window for z-score (trading days)
    "entry_threshold": 1.0,  # z-score magnitude to enter a position
    "exit_threshold": 0.25,  # z-score magnitude to exit (revert-to-mean)
    "time_stop_days": 20,    # max trading days per position (hard cap)
    "trend_window": 200,     # Faber (2007) 200-DMA regime gate — do not sweep
    "init_capital": 100_000.0,
}

SWEEP_VALUES = {
    "z_lookback": [126, 252, 504],
    "entry_threshold": [0.75, 1.0, 1.5],
    "exit_threshold": [0.0, 0.25, 0.5],
    "time_stop_days": [15, 20, 30],
}

IS_START = "2004-01-01"
IS_END = "2020-12-31"
OOS_START = "2021-01-01"
OOS_END = "2024-12-31"
# TLT inception July 2002; download from here to cover warmup for IS 2004
DATA_START = "2002-07-01"
TRADING_DAYS_PER_YEAR = 252
# ED-SLIP-001 threshold
ULTRA_LIQUID_ADV_THRESHOLD = 50_000_000  # 50M shares/day


# ── Data Loading ─────────────────────────────────────────────────────────────────

def download_data(start: str = DATA_START, end: str = OOS_END) -> dict:
    """
    Download daily OHLCV for SPY and TLT via yfinance.
    auto_adjust=True: split- and dividend-adjusted prices.

    Returns dict with keys 'open', 'close', 'volume' — each a DataFrame[SPY, TLT].
    """
    raw = yf.download(
        ["SPY", "TLT"],
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
    )

    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex columns from yfinance multi-ticker download.")

    close = raw["Close"][["SPY", "TLT"]].copy()
    open_ = raw["Open"][["SPY", "TLT"]].copy()
    volume = raw["Volume"][["SPY", "TLT"]].copy()

    # Drop rows where both tickers are NaN (non-trading days)
    close = close.dropna(how="all")
    open_ = open_.reindex(close.index)
    volume = volume.reindex(close.index)

    return {"close": close, "open": open_, "volume": volume}


def check_data_quality(data: dict) -> dict:
    """
    Validate data per Engineering Director pre-backtest checklist.
    Flags any gap > 5 consecutive missing trading days.
    """
    close = data["close"]
    report = {
        "survivorship_bias": (
            "Fixed 2-ticker universe (SPY, TLT). SPY inception 1993; TLT inception July 2002. "
            "Both active major ETFs with no delisting risk. No survivorship bias."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — ETFs, no earnings events.",
        "tickers": {},
        "flagged": [],
    }
    for ticker in ["SPY", "TLT"]:
        if ticker not in close.columns:
            report["tickers"][ticker] = {"error": "Not in downloaded data"}
            report["flagged"].append(ticker)
            continue
        series = close[ticker]
        # Check consecutive NaN gaps only after first valid data point.
        # NaN before inception (e.g., TLT rows before 2002-07-26) are pre-inception
        # padding, not real gaps — skip them by trimming leading NaN.
        clean = series.dropna()
        series_trimmed = series.loc[clean.index[0]:]  # start at first valid row
        nan_mask = series_trimmed.isna()
        max_consec_gap = 0
        consec = 0
        for v in nan_mask:
            consec = (consec + 1) if v else 0
            max_consec_gap = max(max_consec_gap, consec)
        gap_flag = max_consec_gap > 5
        report["tickers"][ticker] = {
            "total_trading_days": int(len(clean)),
            "max_consecutive_missing": max_consec_gap,
            "gap_flag": gap_flag,
            "start": str(clean.index.min().date()),
            "end": str(clean.index.max().date()),
        }
        if gap_flag:
            report["flagged"].append(ticker)
            warnings.warn(
                f"Data gap flag: {ticker} has {max_consec_gap} consecutive missing days (>5 threshold)."
            )
    return report


# ── Precomputed Series ───────────────────────────────────────────────────────────

def build_precomputed(data: dict, params: dict) -> dict:
    """
    Compute all rolling signals on the full dataset.
    All windows are strictly backward-looking — no look-ahead bias.

    Returns dict with:
      z_score, spy_above_200, tlt_above_200, spy_sigma, tlt_sigma, spy_adv, tlt_adv
    """
    close = data["close"]
    volume = data["volume"]
    spy_c = close["SPY"]
    tlt_c = close["TLT"]
    z_lb = params["z_lookback"]
    t_win = params["trend_window"]

    ratio = spy_c / tlt_c
    ratio_mean = ratio.rolling(z_lb).mean()
    ratio_std = ratio.rolling(z_lb).std()
    z_score = (ratio - ratio_mean) / ratio_std

    spy_dma = spy_c.rolling(t_win).mean()
    tlt_dma = tlt_c.rolling(t_win).mean()
    spy_above_200 = spy_c > spy_dma
    tlt_above_200 = tlt_c > tlt_dma

    # 20-day rolling daily return std (not annualized — used raw for impact formula)
    spy_sigma = spy_c.pct_change().rolling(20).std()
    tlt_sigma = tlt_c.pct_change().rolling(20).std()

    # 20-day rolling avg daily share volume (for ADV)
    spy_adv = volume["SPY"].rolling(20).mean()
    tlt_adv = volume["TLT"].rolling(20).mean()

    return {
        "z_score": z_score,
        "spy_above_200": spy_above_200,
        "tlt_above_200": tlt_above_200,
        "spy_sigma": spy_sigma,
        "tlt_sigma": tlt_sigma,
        "spy_adv": spy_adv,
        "tlt_adv": tlt_adv,
    }


# ── Transaction Cost Model ───────────────────────────────────────────────────────

def get_slippage_pct(symbol: str, adv_shares: float) -> float:
    """
    Per ED-SLIP-001: ultra-liquid ETF tier when ADV > 50M shares/day.
    SPY typically qualifies; TLT (ADV ~15-30M) uses canonical 0.05%.
    """
    if not np.isnan(adv_shares) and adv_shares > ULTRA_LIQUID_ADV_THRESHOLD:
        return 0.00005  # 0.005% — ED-SLIP-001 ultra-liquid ruling
    return 0.0005   # 0.05% — canonical equities/ETF


def compute_buy_shares(
    asset: str, cash: float, price: float, sigma: float, adv_shares: float
) -> tuple:
    """
    Compute shares to buy and total cash spent deploying `cash` into `asset`.

    Returns:
        (shares, cash_spent, liquidity_constrained, cost_breakdown)
    """
    if price <= 0 or cash <= 0:
        return 0.0, 0.0, False, {}

    slippage = get_slippage_pct(asset, adv_shares)
    adv_safe = max(adv_shares, 1.0) if not np.isnan(adv_shares) else 1.0
    # Estimate shares with approximation first, then refine
    est_shares = cash / (price * (1 + slippage) + 0.005)
    q_over_adv = est_shares / adv_safe
    impact = 0.1 * (sigma if not np.isnan(sigma) else 0.0) * np.sqrt(max(q_over_adv, 0.0))
    total_pct = slippage + impact

    cost_per_share = price * (1 + total_pct) + 0.005
    shares = cash / cost_per_share
    cash_spent = shares * cost_per_share

    liquidity_constrained = q_over_adv > 0.01
    if liquidity_constrained:
        warnings.warn(
            f"LIQUIDITY-CONSTRAINED BUY: {asset} Q/ADV={q_over_adv:.4f} > 1% — "
            f"shares={shares:.0f}, ADV={adv_shares:.0f}"
        )

    return shares, cash_spent, liquidity_constrained, {
        "slippage_pct": slippage,
        "market_impact_pct": impact,
        "total_cost_pct": total_pct,
        "commission_per_share": 0.005,
        "adv_tier": "ultra_liquid" if slippage < 0.0001 else "standard",
        "ruling_ref": "ED-SLIP-001" if slippage < 0.0001 else "canonical",
    }


def compute_sell_proceeds(
    asset: str, shares: float, price: float, sigma: float, adv_shares: float
) -> tuple:
    """
    Compute net proceeds from selling `shares` of `asset`.

    Returns:
        (net_proceeds, liquidity_constrained, cost_breakdown)
    """
    if shares <= 0 or price <= 0:
        return 0.0, False, {}

    slippage = get_slippage_pct(asset, adv_shares)
    adv_safe = max(adv_shares, 1.0) if not np.isnan(adv_shares) else 1.0
    q_over_adv = shares / adv_safe
    impact = 0.1 * (sigma if not np.isnan(sigma) else 0.0) * np.sqrt(max(q_over_adv, 0.0))
    total_pct = slippage + impact

    commission = shares * 0.005
    net_proceeds = shares * price * (1 - total_pct) - commission

    liquidity_constrained = q_over_adv > 0.01
    if liquidity_constrained:
        warnings.warn(
            f"LIQUIDITY-CONSTRAINED SELL: {asset} Q/ADV={q_over_adv:.4f} > 1% — "
            f"shares={shares:.0f}, ADV={adv_shares:.0f}"
        )

    return max(net_proceeds, 0.0), liquidity_constrained, {
        "slippage_pct": slippage,
        "market_impact_pct": impact,
        "total_cost_pct": total_pct,
        "commission": commission,
        "adv_tier": "ultra_liquid" if slippage < 0.0001 else "standard",
        "ruling_ref": "ED-SLIP-001" if slippage < 0.0001 else "canonical",
    }


# ── Portfolio Simulation ─────────────────────────────────────────────────────────

def run_simulation(
    data: dict,
    precomp: dict,
    params: dict,
    start: str,
    end: str,
) -> dict:
    """
    Event-driven backtest for H69 SPY/TLT ratio mean reversion.

    Execution model:
    - Signal computed at close of day t (using only data available at t)
    - Entry/exit executes at open of day t+1 (next-day fill, no look-ahead)
    - One position at a time: SPY, TLT, or cash
    - SPY long takes precedence over TLT if both signals fire simultaneously

    Position exit (first to trigger):
    - Z-score revert: z >= -exit_threshold (for SPY long) or z <= +exit_threshold (for TLT long)
    - 200-DMA mid-position breach: asset close < its 200-DMA
    - Time stop: trading days held >= time_stop_days

    Returns dict with portfolio_values (pd.Series), trade_log (list of dicts), metrics.
    """
    entry_thr = params["entry_threshold"]
    exit_thr = params["exit_threshold"]
    time_stop = params["time_stop_days"]
    init_capital = params["init_capital"]

    close = data["close"]
    open_ = data["open"]

    z_score = precomp["z_score"]
    spy_above = precomp["spy_above_200"]
    tlt_above = precomp["tlt_above_200"]
    spy_sigma = precomp["spy_sigma"]
    tlt_sigma = precomp["tlt_sigma"]
    spy_adv = precomp["spy_adv"]
    tlt_adv = precomp["tlt_adv"]

    # Simulation window (IS or OOS)
    window = close.loc[start:end].index
    if len(window) < 10:
        raise ValueError(f"Insufficient data for period {start}:{end}")

    # State
    cash = float(init_capital)
    position = None   # None | 'SPY' | 'TLT'
    shares = 0.0
    entry_date_str = None
    entry_price = None
    entry_idx = None      # index (integer) in `window` of the day we bought

    # Pending actions (set at close of day t, executed at open of day t+1)
    pending_exit = False
    pending_exit_reason = None
    pending_entry = None  # 'SPY' | 'TLT' | None

    portfolio_values = pd.Series(index=window, dtype=float)
    trade_log = []

    for i, t in enumerate(window):
        spy_open_t = open_["SPY"].get(t, np.nan)
        tlt_open_t = open_["TLT"].get(t, np.nan)
        spy_close_t = close["SPY"].get(t, np.nan)
        tlt_close_t = close["TLT"].get(t, np.nan)

        # ── Execute pending actions at today's open ──────────────────────────
        if pending_exit and i > 0:
            asset = position
            exit_open = spy_open_t if asset == "SPY" else tlt_open_t
            if pd.isna(exit_open) or exit_open <= 0:
                exit_open = spy_close_t if asset == "SPY" else tlt_close_t

            sigma_val = float(spy_sigma.get(t, 0.0) or 0.0)
            adv_val = float(spy_adv.get(t, 1e6) or 1e6) if asset == "SPY" else float(tlt_adv.get(t, 1e6) or 1e6)
            if asset == "TLT":
                sigma_val = float(tlt_sigma.get(t, 0.0) or 0.0)

            proceeds, liq_flag, cost_info = compute_sell_proceeds(
                asset, shares, exit_open, sigma_val, adv_val
            )
            cash += proceeds

            # Trading days held = i - entry_idx (entry_idx is when we bought at open)
            hold_td = i - entry_idx

            entry_value = shares * entry_price
            pnl_dollar = proceeds - entry_value
            pnl_pct = pnl_dollar / entry_value if entry_value > 0 else 0.0

            trade_log.append({
                "date_entry": entry_date_str,
                "date_exit": str(t.date()),
                "asset": asset,
                "entry_price": round(entry_price, 4),
                "exit_price": round(exit_open, 4),
                "pnl_pct": round(pnl_pct, 6),
                "pnl_dollar": round(pnl_dollar, 2),
                "hold_days": hold_td,
                "exit_reason": pending_exit_reason,
                "liquidity_constrained": liq_flag,
                "cost_breakdown": cost_info,
            })

            position = None
            shares = 0.0
            entry_date_str = None
            entry_price = None
            entry_idx = None
            pending_exit = False
            pending_exit_reason = None

        if pending_entry is not None and position is None and i > 0:
            asset = pending_entry
            buy_open = spy_open_t if asset == "SPY" else tlt_open_t
            if pd.isna(buy_open) or buy_open <= 0:
                buy_open = spy_close_t if asset == "SPY" else tlt_close_t

            sigma_val = float(spy_sigma.get(t, 0.0) or 0.0)
            adv_val = float(spy_adv.get(t, 1e6) or 1e6)
            if asset == "TLT":
                sigma_val = float(tlt_sigma.get(t, 0.0) or 0.0)
                adv_val = float(tlt_adv.get(t, 1e6) or 1e6)

            sh, spent, liq_flag, cost_info = compute_buy_shares(
                asset, cash, buy_open, sigma_val, adv_val
            )
            if sh > 0:
                cash -= spent
                cash = max(cash, 0.0)
                shares = sh
                position = asset
                entry_date_str = str(t.date())
                entry_price = buy_open
                entry_idx = i

            pending_entry = None

        # ── Mark to market at close ──────────────────────────────────────────
        spy_mark = spy_close_t if not pd.isna(spy_close_t) else (spy_open_t or 0.0)
        tlt_mark = tlt_close_t if not pd.isna(tlt_close_t) else (tlt_open_t or 0.0)

        if position == "SPY":
            nav = cash + shares * spy_mark
        elif position == "TLT":
            nav = cash + shares * tlt_mark
        else:
            nav = cash
        portfolio_values.iloc[i] = nav

        # ── Check exit conditions at close (for tomorrow's open execution) ───
        # All checks use precomputed series — no look-ahead, no loop recompute
        if position is not None:
            z_t = z_score.get(t, np.nan)
            should_exit = False
            reason = None

            # Z-score revert exit
            if position == "SPY" and not pd.isna(z_t) and z_t >= -exit_thr:
                should_exit = True
                reason = "zscore_revert"
            elif position == "TLT" and not pd.isna(z_t) and z_t <= exit_thr:
                should_exit = True
                reason = "zscore_revert"

            # 200-DMA breach mid-position (use precomputed boolean series)
            if not should_exit and position == "SPY":
                above = spy_above.get(t)
                if above is not None and not bool(above):
                    should_exit = True
                    reason = "200dma_breach"
            if not should_exit and position == "TLT":
                above = tlt_above.get(t)
                if above is not None and not bool(above):
                    should_exit = True
                    reason = "200dma_breach"

            # Time stop
            if not should_exit and entry_idx is not None and (i - entry_idx) >= time_stop:
                should_exit = True
                reason = "time_stop"

            if should_exit and not pending_exit:
                pending_exit = True
                pending_exit_reason = reason

        # ── Check entry conditions at close (if not in position after exit) ──
        # Entry eligible if: no position now AND no pending entry yet
        # Also eligible if pending_exit is True (will be flat at next open)
        can_enter = (position is None and not pending_exit) or (pending_exit and position is not None)

        if can_enter and pending_entry is None:
            z_t = z_score.get(t, np.nan)
            if not pd.isna(z_t):
                spy_ab = bool(spy_above.get(t, False))
                tlt_ab = bool(tlt_above.get(t, False))
                long_spy = (z_t < -entry_thr) and spy_ab
                long_tlt = (z_t > entry_thr) and tlt_ab
                if long_spy:
                    pending_entry = "SPY"
                elif long_tlt:
                    pending_entry = "TLT"

    portfolio_values = portfolio_values.ffill().fillna(init_capital)
    return {"portfolio_values": portfolio_values, "trade_log": trade_log}


# ── Performance Metrics ───────────────────────────────────────────────────────────

def compute_metrics(portfolio_values: pd.Series, trade_log: list, start: str, end: str) -> dict:
    """
    Compute IS/OOS performance metrics from simulation output.

    Metrics:
      - Sharpe (annualized, risk-free = 0)
      - CAGR
      - Max Drawdown
      - Trade Count
      - Win Rate
      - Profit Factor
      - Avg PpT (bps)
    """
    pv = portfolio_values.dropna()
    if len(pv) < 2:
        return {"error": "Insufficient portfolio values for metrics"}

    daily_ret = pv.pct_change().fillna(0.0).values
    sharpe = float(
        daily_ret.mean() / (daily_ret.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )

    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    total_return = float(pv.iloc[-1] / pv.iloc[0] - 1)
    cagr = float((pv.iloc[-1] / pv.iloc[0]) ** (1.0 / max(years, 0.01)) - 1)

    cum = np.cumprod(1 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-10)))

    if trade_log:
        pnl_arr = np.array([t["pnl_dollar"] for t in trade_log])
        pnl_pct_arr = np.array([t["pnl_pct"] for t in trade_log])
        win_rate = float(np.mean(pnl_arr > 0))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        profit_factor = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0
            else float("inf")
        )
        avg_ppt_bps = float(np.mean(pnl_pct_arr) * 10_000)
    else:
        win_rate = 0.0
        profit_factor = 0.0
        avg_ppt_bps = 0.0

    return {
        "sharpe": round(sharpe, 4),
        "cagr": round(cagr, 4),
        "max_drawdown": round(mdd, 4),
        "total_return": round(total_return, 4),
        "trade_count": len(trade_log),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if not np.isinf(profit_factor) else "inf",
        "avg_ppt_bps": round(avg_ppt_bps, 2),
        "period": f"{start} to {end}",
        "years": round(years, 2),
    }


# ── Parameter Sweep ──────────────────────────────────────────────────────────────

def scan_parameters(data: dict, close_full: pd.DataFrame = None) -> list:
    """
    Run IS backtest for all parameter combinations from SWEEP_VALUES.
    Total: 3 × 3 × 3 × 3 = 81 combinations.

    Uses precomputed signals where possible; recomputes z-score per z_lookback.

    Returns list of dicts with params + IS metrics.
    """
    results = []
    keys = list(SWEEP_VALUES.keys())
    vals = list(SWEEP_VALUES.values())

    for combo in product(*vals):
        p = {**PARAMETERS, **dict(zip(keys, combo))}
        try:
            precomp = build_precomputed(data, p)
            sim = run_simulation(data, precomp, p, IS_START, IS_END)
            m = compute_metrics(sim["portfolio_values"], sim["trade_log"], IS_START, IS_END)
            results.append({
                "z_lookback": p["z_lookback"],
                "entry_threshold": p["entry_threshold"],
                "exit_threshold": p["exit_threshold"],
                "time_stop_days": p["time_stop_days"],
                **{k: v for k, v in m.items() if k not in ("period", "years")},
            })
        except Exception as exc:
            results.append({
                "z_lookback": p["z_lookback"],
                "entry_threshold": p["entry_threshold"],
                "exit_threshold": p["exit_threshold"],
                "time_stop_days": p["time_stop_days"],
                "error": str(exc),
            })

    return results


def sweep_stability_summary(sweep_results: list) -> dict:
    """Compute Sharpe range and Gate 1 stability check (< 30% variation)."""
    sharpes = [r["sharpe"] for r in sweep_results if "sharpe" in r and isinstance(r["sharpe"], (int, float))]
    if not sharpes:
        return {"error": "No valid sweep results"}

    primary = next(
        (r["sharpe"] for r in sweep_results
         if r.get("z_lookback") == PARAMETERS["z_lookback"]
         and r.get("entry_threshold") == PARAMETERS["entry_threshold"]
         and r.get("exit_threshold") == PARAMETERS["exit_threshold"]
         and r.get("time_stop_days") == PARAMETERS["time_stop_days"]),
        None
    )

    sharpe_range = max(sharpes) - min(sharpes)
    variance_pct = sharpe_range / abs(primary) if primary and primary != 0 else float("nan")

    return {
        "primary_sharpe": primary,
        "sharpe_min": round(min(sharpes), 4),
        "sharpe_max": round(max(sharpes), 4),
        "sharpe_range": round(sharpe_range, 4),
        "sharpe_variance_pct": round(variance_pct, 4) if not np.isnan(variance_pct) else None,
        "gate1_stability": (
            f"PASS: variance {variance_pct:.1%} ≤ 30%"
            if not np.isnan(variance_pct) and variance_pct <= 0.30
            else f"FAIL: variance {variance_pct:.1%} > 30% — flag to Engineering Director"
        ),
        "n_combinations": len(sharpes),
    }


# ── Main Entry Point ─────────────────────────────────────────────────────────────

def run_strategy(params: dict = PARAMETERS, output_dir: str = None, run_sweep: bool = True) -> dict:
    """
    Full IS+OOS backtest for H69 SPY/TLT ratio mean reversion.

    Downloads data once, runs IS and OOS periods, optionally runs param sweep,
    writes trade log CSV and JSON metrics file to output_dir.

    Returns dict with IS metrics, OOS metrics, and sweep results.
    """
    print("H69: downloading SPY/TLT data from", DATA_START, "to", OOS_END, "...")
    data = download_data(DATA_START, OOS_END)

    quality = check_data_quality(data)
    if quality["flagged"]:
        warnings.warn(f"Data quality flag: {quality['flagged']}")

    # Precompute signals on full dataset (IS + OOS) for primary params
    print(f"H69: computing signals (z_lookback={params['z_lookback']}, "
          f"entry={params['entry_threshold']}, exit={params['exit_threshold']}, "
          f"time_stop={params['time_stop_days']})...")
    precomp = build_precomputed(data, params)

    # IS simulation
    print(f"H69: running IS backtest {IS_START} → {IS_END}...")
    is_sim = run_simulation(data, precomp, params, IS_START, IS_END)
    is_metrics = compute_metrics(is_sim["portfolio_values"], is_sim["trade_log"], IS_START, IS_END)

    # OOS simulation
    print(f"H69: running OOS backtest {OOS_START} → {OOS_END}...")
    oos_sim = run_simulation(data, precomp, params, OOS_START, OOS_END)
    oos_metrics = compute_metrics(oos_sim["portfolio_values"], oos_sim["trade_log"], OOS_START, OOS_END)

    # Parameter sweep (IS only)
    sweep_results = []
    stability = {}
    if run_sweep:
        print("H69: running 81-combination parameter sweep on IS...")
        sweep_results = scan_parameters(data)
        stability = sweep_stability_summary(sweep_results)
        print(f"H69: sweep complete — stability: {stability.get('gate1_stability', 'N/A')}")

    # Stdout summary
    print("\n" + "=" * 70)
    print(f"{'H69 SPY/TLT Ratio Mean Reversion — Performance Summary':^70}")
    print("=" * 70)
    print(f"{'Metric':<25} {'IS (2004-2020)':>20} {'OOS (2021-2024)':>20}")
    print("-" * 70)
    for key in ("sharpe", "cagr", "max_drawdown", "win_rate", "trade_count", "avg_ppt_bps"):
        is_v = is_metrics.get(key, "N/A")
        oos_v = oos_metrics.get(key, "N/A")
        print(f"{key:<25} {str(is_v):>20} {str(oos_v):>20}")
    print("=" * 70)
    if stability:
        print(f"Sweep stability: {stability.get('gate1_stability', 'N/A')}")
    print()

    # Write output files
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    all_trades = is_sim["trade_log"] + oos_sim["trade_log"]

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        base = f"H69_SPYTLTRatioMeanReversion_{today_str}"

        # Trade log CSV
        if all_trades:
            trade_df = pd.DataFrame(all_trades)
            csv_cols = [
                "date_entry", "date_exit", "asset", "entry_price", "exit_price",
                "pnl_pct", "pnl_dollar", "hold_days", "exit_reason", "liquidity_constrained",
            ]
            trade_df = trade_df[[c for c in csv_cols if c in trade_df.columns]]
            csv_path = os.path.join(output_dir, f"{base}_trades.csv")
            trade_df.to_csv(csv_path, index=False)
            print(f"Trade log written: {csv_path} ({len(trade_df)} trades)")
        else:
            print("No trades generated for trade log.")

        # JSON metrics
        json_output = {
            "strategy": "H69_SPYTLTRatioMeanReversion",
            "date": today_str,
            "parameters": {k: v for k, v in params.items() if k != "init_capital"},
            "initial_capital": params["init_capital"],
            "cost_model": {
                "spy_slippage": "0.005% (ED-SLIP-001 ultra-liquid ruling)",
                "tlt_slippage": "0.05% (canonical standard ETF)",
                "fixed_commission": "$0.005/share",
                "market_impact": "0.1 × σ × sqrt(Q/ADV)",
                "ruling_ref": "ED-SLIP-001",
            },
            "is": is_metrics,
            "oos": oos_metrics,
            "data_quality": quality,
            "sweep_stability": stability,
            "sweep_results": sweep_results,
        }
        json_path = os.path.join(output_dir, f"{base}.json")
        with open(json_path, "w") as f:
            json.dump(json_output, f, indent=2, default=str)
        print(f"Metrics JSON written: {json_path}")

    return {
        "is": is_metrics,
        "oos": oos_metrics,
        "sweep_stability": stability,
        "sweep_results": sweep_results,
        "data_quality": quality,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="H69 SPY/TLT Bond-Equity Ratio Mean Reversion backtest."
    )
    parser.add_argument(
        "--z-lookback", type=int, default=PARAMETERS["z_lookback"],
        choices=SWEEP_VALUES["z_lookback"],
        help="Rolling z-score lookback in trading days (default: 252)"
    )
    parser.add_argument(
        "--entry-threshold", type=float, default=PARAMETERS["entry_threshold"],
        help="Z-score magnitude to enter position (default: 1.0)"
    )
    parser.add_argument(
        "--exit-threshold", type=float, default=PARAMETERS["exit_threshold"],
        help="Z-score magnitude to exit position (default: 0.25)"
    )
    parser.add_argument(
        "--time-stop", type=int, default=PARAMETERS["time_stop_days"],
        help="Max trading days per position (default: 20)"
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Directory for trade log CSV and JSON metrics output"
    )
    parser.add_argument(
        "--no-sweep", action="store_true",
        help="Skip the 81-combination parameter sweep (faster)"
    )
    args = parser.parse_args()

    params = {
        **PARAMETERS,
        "z_lookback": args.z_lookback,
        "entry_threshold": args.entry_threshold,
        "exit_threshold": args.exit_threshold,
        "time_stop_days": args.time_stop,
    }

    run_strategy(params=params, output_dir=args.output_dir, run_sweep=not args.no_sweep)
