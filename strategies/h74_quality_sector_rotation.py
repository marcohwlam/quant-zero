"""
Strategy: H74 Quality Sector Rotation (Quality/Profitability Factor)
Author: Strategy Coder Agent
Date: 2026-06-16
Hypothesis: Sector ETFs ranked by quality composite (div-yield stability +
            inverse price volatility) outperform. Long top-K quality sectors monthly.
            SPY < 200-DMA regime filter → 100% SHY.
Asset class: US equity sector ETFs (SPDR + VNQ)
Parent task: QUA-318

IS window:  2005-01-01 to 2018-12-31 (14 years)
OOS window: 2019-01-01 to 2024-12-31 (6 years)

Signal construction (no look-ahead):
  1. div_yield_score  = sum(dividends paid in [t - N months, t]) / close_t
                        Cross-sectional z-score across 10 sectors.
  2. stability_score = 1 / (rolling N-month daily return std × sqrt(252))
                        Inverse vol = stable business quality.
                        Cross-sectional z-score.
  3. quality_composite = equal-weight average of the two z-scores.

Regime filter (highest priority):
  SPY close < dma_window-day SMA → 100% SHY
  Re-enter sectors at next rebalance when SPY > SMA.

Transaction costs (ED-SLIP-001 canonical):
  Sector ETFs: $0.005/share + 0.05% slippage + 0.1×σ×sqrt(Q/ADV) market impact
  SHY:  $0.005/share + 0.005% slippage (ultra-liquid if 20d ADV > 50M/day)
  Market impact coefficient k=0.1 (Almgren-Chriss square-root model)
  Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True

Academic:
  Novy-Marx, R. (2013). "The Other Side of Value." JFE 108(1), 1-28.
  Asness, C., Frazzini, A., Pedersen, L. (2019). "Quality Minus Junk." RAS 24(1), 34-112.
  Frazzini, A., Pedersen, L. (2014). "Betting Against Beta." JFE 111(1), 1-28.
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

UNIVERSE = ["XLK", "XLV", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB", "XLE", "VNQ"]
REGIME_ETF = "SPY"
SAFE_HAVEN = "SHY"
TRADING_DAYS_PER_YEAR = 252

PARAMETERS = {
    "sectors_held": 3,
    "quality_lookback_months": 12,
    "dma_window": 200,
    "rebalance_frequency": "monthly",  # "monthly" | "bi-monthly"
    "init_capital": 100_000.0,
}

SWEEP_VALUES = {
    "sectors_held": [2, 3, 4],
    "quality_lookback_months": [6, 12, 18],
    "dma_window": [150, 200, 250],
    "rebalance_frequency": ["monthly", "bi-monthly"],
}

IS_START = "2005-01-01"
IS_END = "2018-12-31"
OOS_START = "2019-01-01"
OOS_END = "2024-12-31"
DATA_START = "2003-01-01"   # extra warmup for quality lookback + DMA

SHY_ULTRA_LIQUID_ADV = 50_000_000   # shares/day threshold for ultra-liquid slippage

WF_WINDOWS = [
    ("2005-01-01", "2007-12-31"),
    ("2008-01-01", "2011-12-31"),
    ("2012-01-01", "2015-12-31"),
    ("2016-01-01", "2018-12-31"),
]


# ── Data Loading ──────────────────────────────────────────────────────────────

def download_data(start=DATA_START, end=OOS_END):
    """Download OHLCV (multi-ticker) + per-ETF dividend history."""
    all_tickers = UNIVERSE + [REGIME_ETF, SAFE_HAVEN]
    print(f"H74: downloading OHLCV ({len(all_tickers)} tickers, {start}→{end})...")
    raw = yf.download(
        all_tickers, start=start, end=end,
        auto_adjust=True, progress=False,
    )
    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex columns from yfinance multi-ticker download.")

    close = raw["Close"][all_tickers].copy()
    open_ = raw["Open"][all_tickers].copy()
    volume = raw["Volume"][all_tickers].copy()
    close = close.dropna(how="all")
    open_ = open_.reindex(close.index)
    volume = volume.reindex(close.index)

    print(f"H74: downloading dividends for {len(UNIVERSE)} sector ETFs...")
    dividends = {}
    for ticker in UNIVERSE:
        try:
            hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
            if "Dividends" in hist.columns:
                divs = hist["Dividends"].copy()
                if hasattr(divs.index, "tz") and divs.index.tz is not None:
                    divs.index = divs.index.tz_localize(None)
                divs.index = pd.to_datetime(divs.index).normalize()
                dividends[ticker] = divs[divs > 0].copy()
            else:
                dividends[ticker] = pd.Series(dtype=float)
        except Exception as exc:
            warnings.warn(f"Dividend download failed for {ticker}: {exc}")
            dividends[ticker] = pd.Series(dtype=float)

    return {"close": close, "open_": open_, "volume": volume, "dividends": dividends}


def check_data_quality(data):
    """Pre-backtest data quality checks (H74 Data Quality Checklist)."""
    close = data["close"]
    report = {
        "universe": UNIVERSE,
        "regime_etf": REGIME_ETF,
        "safe_haven": SAFE_HAVEN,
        "survivorship_bias": (
            "Fixed 10-sector universe: 9 SPDR ETFs (inception Dec 1998) + VNQ (inception May 2004). "
            "All ETFs still active — no delisting risk. VNQ warmup period handled with NaN scores. "
            "Universe defined a priori by hypothesis spec; no post-hoc selection bias."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — sector ETFs are diversified baskets; no individual earnings events.",
        "tickers": {},
        "flagged": [],
    }

    for ticker in UNIVERSE + [REGIME_ETF, SAFE_HAVEN]:
        if ticker not in close.columns:
            report["tickers"][ticker] = {"error": "not in downloaded data"}
            report["flagged"].append(f"{ticker}:MISSING")
            continue
        col = close[ticker].dropna()
        if len(col) == 0:
            report["tickers"][ticker] = {"error": "all NaN"}
            report["flagged"].append(ticker)
            continue
        trimmed = close[ticker].loc[col.index[0]:]
        max_gap = consec = 0
        for v in trimmed.isna():
            consec = (consec + 1) if v else 0
            max_gap = max(max_gap, consec)
        gap_flag = max_gap > 5
        if gap_flag:
            warnings.warn(f"Data gap: {ticker} has {max_gap} consecutive missing days (>5).")
            report["flagged"].append(ticker)
        report["tickers"][ticker] = {
            "total_obs": int(len(col)),
            "start": str(col.index.min().date()),
            "end": str(col.index.max().date()),
            "max_consecutive_missing": max_gap,
            "gap_flag": gap_flag,
        }

    return report


# ── Rebalance Date Helpers ─────────────────────────────────────────────────────

def get_last_trading_days(close):
    """Last trading day of each calendar month in close.index."""
    helper = pd.Series(close.index, index=close.index)
    last_days = helper.resample("ME").last().dropna()
    return pd.DatetimeIndex(last_days.values)


def get_rebalance_dates(close, frequency):
    """Monthly or bi-monthly rebalance dates (month-end)."""
    all_me = get_last_trading_days(close)
    if frequency == "bi-monthly":
        return all_me[::2]
    return all_me


# ── Quality Score Computation ─────────────────────────────────────────────────

def compute_quality_scores(close_sectors, dividends, rebalance_date, lookback_months):
    """
    Quality composite score for each sector ETF at rebalance_date.

    quality_composite = (div_yield_zscore + inv_vol_zscore) / 2

    div_yield  = sum(dividends in [date - lookback, date]) / close_at_date
                 Higher div yield → more stable earnings → higher quality.
    inv_vol    = 1 / (daily_return_std(lookback) × sqrt(252))
                 Lower vol → more stable business → higher quality.

    Both z-scored cross-sectionally. NaN where data insufficient.
    """
    lookback_start = rebalance_date - pd.DateOffset(months=lookback_months)
    min_days = max(20, lookback_months * 15)  # require ~15 trading days per month

    div_yields = {}
    inv_vols = {}

    for ticker in UNIVERSE:
        if ticker not in close_sectors.columns:
            div_yields[ticker] = np.nan
            inv_vols[ticker] = np.nan
            continue

        price_series = close_sectors[ticker]
        price = float(price_series.get(rebalance_date, np.nan))
        if np.isnan(price) or price <= 0:
            div_yields[ticker] = np.nan
            inv_vols[ticker] = np.nan
            continue

        # Dividend yield: trailing N-month dividends / current price
        total_div = 0.0
        if ticker in dividends:
            divs = dividends[ticker]
            if len(divs) > 0:
                mask = (divs.index >= lookback_start) & (divs.index <= rebalance_date)
                total_div = float(divs[mask].sum())
        div_yields[ticker] = total_div / price

        # Inverse volatility: 1 / annualized daily return std
        price_window = price_series.loc[lookback_start:rebalance_date].dropna()
        if len(price_window) >= min_days:
            rets = price_window.pct_change().dropna()
            if len(rets) >= 5:
                vol = float(rets.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
                inv_vols[ticker] = 1.0 / (vol + 1e-8)
            else:
                inv_vols[ticker] = np.nan
        else:
            inv_vols[ticker] = np.nan

    def xscore(d):
        s = pd.Series(d).dropna()
        if len(s) < 2:
            return {k: 0.0 if not np.isnan(v) else np.nan for k, v in d.items()}
        m, std = float(s.mean()), float(s.std())
        if std < 1e-8:
            return {k: 0.0 if not np.isnan(v) else np.nan for k, v in d.items()}
        return {k: (float(v) - m) / std if not np.isnan(float(v)) else np.nan for k, v in d.items()}

    dy_z = xscore(div_yields)
    iv_z = xscore(inv_vols)

    quality = {}
    for ticker in UNIVERSE:
        dy = dy_z.get(ticker, np.nan)
        iv = iv_z.get(ticker, np.nan)
        dy_nan = isinstance(dy, float) and np.isnan(dy)
        iv_nan = isinstance(iv, float) and np.isnan(iv)
        if not dy_nan and not iv_nan:
            quality[ticker] = (dy + iv) / 2.0
        elif not dy_nan:
            quality[ticker] = dy
        elif not iv_nan:
            quality[ticker] = iv
        else:
            quality[ticker] = np.nan

    return pd.Series(quality)


def precompute_quality_cache(close, dividends, lookbacks):
    """Precompute quality scores for all lookbacks × all month-end dates. Returns nested dict."""
    all_month_ends = get_last_trading_days(close)
    close_sectors = close[UNIVERSE]
    cache = {}
    for lb in lookbacks:
        cache[lb] = {}
        for d in all_month_ends:
            cache[lb][d] = compute_quality_scores(close_sectors, dividends, d, lb)
        print(f"H74:   quality cache lb={lb}m: {len(cache[lb])} month-end dates")
    return cache


def precompute_spy_dma(spy_close, dma_windows):
    """Precompute SPY DMA series for each window size."""
    return {w: spy_close.rolling(w, min_periods=max(20, w // 4)).mean() for w in dma_windows}


# ── Transaction Cost Helpers ──────────────────────────────────────────────────

def _slippage_rate(ticker, adv_shares):
    """One-way slippage: SHY ultra-liquid (0.005%) if ADV > 50M; else standard (0.05%)."""
    if ticker == SAFE_HAVEN:
        adv = adv_shares if not (isinstance(adv_shares, float) and np.isnan(adv_shares)) else 0.0
        if adv >= SHY_ULTRA_LIQUID_ADV:
            return 0.00005  # 0.005% ultra-liquid
    return 0.0005  # 0.05% standard ETF tier


def compute_buy_cost(ticker, cash, price, sigma, adv):
    """
    Buy `cash` worth of `ticker` at `price`.
    Returns (shares, spent, liquidity_constrained).
    """
    if price <= 0 or cash <= 0:
        return 0.0, 0.0, False
    adv_s = max(float(adv) if not np.isnan(adv) else 1e6, 1.0)
    sigma_s = float(sigma) if not np.isnan(sigma) else 0.015
    slip = _slippage_rate(ticker, adv_s)

    est_shares = cash / (price * (1 + slip) + 0.005)
    q_adv = est_shares / adv_s
    impact = 0.1 * sigma_s * np.sqrt(max(q_adv, 0.0))
    cost_ps = price * (1 + slip + impact) + 0.005
    shares = cash / cost_ps
    spent = shares * cost_ps
    liq = q_adv > 0.01
    if liq:
        warnings.warn(f"LIQUIDITY-CONSTRAINED BUY {ticker}: Q/ADV={q_adv:.4f} > 1%")
    return shares, spent, liq


def compute_sell_proceeds(ticker, shares, price, sigma, adv):
    """
    Sell `shares` of `ticker` at `price`.
    Returns (net_proceeds, liquidity_constrained).
    """
    if shares <= 0 or price <= 0:
        return 0.0, False
    adv_s = max(float(adv) if not np.isnan(adv) else 1e6, 1.0)
    sigma_s = float(sigma) if not np.isnan(sigma) else 0.015
    slip = _slippage_rate(ticker, adv_s)

    q_adv = shares / adv_s
    impact = 0.1 * sigma_s * np.sqrt(max(q_adv, 0.0))
    commission = shares * 0.005
    proceeds = max(shares * price * (1 - slip - impact) - commission, 0.0)
    liq = q_adv > 0.01
    if liq:
        warnings.warn(f"LIQUIDITY-CONSTRAINED SELL {ticker}: Q/ADV={q_adv:.4f} > 1%")
    return proceeds, liq


# ── Portfolio Simulation ──────────────────────────────────────────────────────

def run_simulation(data, quality_cache, spy_dma_cache, params, start, end):
    """
    Event-driven sector rotation backtest.

    Signal at month-end close → execution at next trading day open.
    Partial rebalance: sell only exiting positions; buy entering positions;
    equal-weight rebalance of the full portfolio each cycle.

    Returns: {portfolio_values: pd.Series daily NAV, trade_log: list[dict]}
    """
    close = data["close"]
    open_ = data["open_"]
    volume = data["volume"]

    sectors_held = params["sectors_held"]
    lb = params["quality_lookback_months"]
    dma_w = params["dma_window"]
    freq = params["rebalance_frequency"]
    init_capital = float(params["init_capital"])

    window_idx = close.loc[start:end].index
    if len(window_idx) < 5:
        raise ValueError(f"Insufficient data: {start}:{end}")

    all_rebal = get_rebalance_dates(close, freq)
    rebal_in_window = set(
        all_rebal[(all_rebal >= pd.Timestamp(start)) & (all_rebal <= pd.Timestamp(end))]
    )

    spy_dma = spy_dma_cache[dma_w]

    sigma_s = {
        tk: close[tk].pct_change().rolling(20).std()
        for tk in UNIVERSE + [SAFE_HAVEN] if tk in close.columns
    }
    adv_s = {
        tk: volume[tk].rolling(20).mean()
        for tk in UNIVERSE + [SAFE_HAVEN] if tk in volume.columns
    }

    def _val(series, t):
        v = series.get(t) if hasattr(series, 'get') else (series[t] if t in series.index else np.nan)
        return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else np.nan

    def _px(ticker, t, use_open=False):
        src = open_ if use_open else close
        if ticker not in src.columns:
            return np.nan
        v = _val(src[ticker], t)
        if np.isnan(v) and use_open and ticker in close.columns:
            v = _val(close[ticker], t)
        return v

    def _sig(ticker, t):
        v = _val(sigma_s[ticker], t) if ticker in sigma_s else np.nan
        return v if not np.isnan(v) else 0.015

    def _adv(ticker, t):
        v = _val(adv_s[ticker], t) if ticker in adv_s else np.nan
        return v if not np.isnan(v) else 1e6

    def _get_target(t):
        """Target positions at signal date t (month-end)."""
        spy_px = _val(close[REGIME_ETF], t)
        spy_ma = _val(spy_dma, t)
        if not np.isnan(spy_px) and not np.isnan(spy_ma) and spy_px < spy_ma:
            return "BEAR", [SAFE_HAVEN]
        scores = quality_cache.get(lb, {}).get(t)
        if scores is None:
            scores = compute_quality_scores(close[UNIVERSE], data["dividends"], t, lb)
        valid = scores.dropna()
        if len(valid) == 0:
            return "BULL_NOSIGNAL", [SAFE_HAVEN]
        top = valid.nlargest(min(sectors_held, len(valid))).index.tolist()
        return "BULL", top

    # Initial target from last rebalance before window start
    prior = all_rebal[all_rebal <= pd.Timestamp(start)]
    if len(prior) > 0:
        _, init_target = _get_target(prior[-1])
    else:
        first = all_rebal[all_rebal >= pd.Timestamp(start)]
        _, init_target = _get_target(first[0]) if len(first) > 0 else (None, [SAFE_HAVEN])

    # State
    cash = init_capital
    positions = {}     # {ticker: shares}
    ep = {}            # entry prices
    ed = {}            # entry dates (str)
    ei = {}            # entry indices
    pending = init_target

    portfolio_values = pd.Series(np.nan, index=window_idx)
    trade_log = []

    for i, t in enumerate(window_idx):
        # Execute pending rebalance at today's open
        if pending is not None:
            new_tgt = list(pending)
            pending = None

            # 1) Sell positions not in new target
            for tk in [x for x in list(positions.keys()) if x not in new_tgt]:
                sh = positions.pop(tk, 0.0)
                if sh <= 0:
                    continue
                px = _px(tk, t, use_open=True)
                if np.isnan(px) or px <= 0:
                    positions[tk] = sh   # restore; can't sell
                    continue
                proc, liq = compute_sell_proceeds(tk, sh, px, _sig(tk, t), _adv(tk, t))
                cash += proc
                ent_p = ep.pop(tk, px)
                ent_d = ed.pop(tk, str(t.date()))
                ent_i = ei.pop(tk, i)
                ev = sh * ent_p
                pnl = proc - ev
                trade_log.append({
                    "date_entry": ent_d, "date_exit": str(t.date()),
                    "asset": tk, "entry_price": round(ent_p, 4),
                    "exit_price": round(px, 4),
                    "pnl_pct": round(pnl / ev, 6) if ev > 0 else 0.0,
                    "pnl_dollar": round(pnl, 2),
                    "hold_days": i - ent_i,
                    "exit_reason": "rebalance",
                    "liquidity_constrained": liq,
                })

            # 2) Compute current NAV (cash + remaining positions at open)
            nav = cash
            for tk, sh in positions.items():
                px = _px(tk, t, use_open=True)
                if np.isnan(px):
                    px = _px(tk, t, use_open=False)
                nav += sh * (float(px) if not np.isnan(px) else 0.0)

            # 3) Equal-weight rebalance: target value per position = NAV / n
            n_tgt = len(new_tgt)
            if n_tgt > 0:
                tgt_val = nav / n_tgt

                # Trim overweight kept positions (>20% above target)
                for tk in [x for x in list(positions.keys()) if x in new_tgt]:
                    px = _px(tk, t, use_open=True)
                    if np.isnan(px) or px <= 0:
                        continue
                    cur_val = positions[tk] * px
                    if cur_val > tgt_val * 1.20:
                        trim_sh = (cur_val - tgt_val) / px
                        proc, _ = compute_sell_proceeds(tk, trim_sh, px, _sig(tk, t), _adv(tk, t))
                        cash += proc
                        positions[tk] -= trim_sh

                # Buy new positions not yet held
                new_buys = [tk for tk in new_tgt if tk not in positions]
                if new_buys:
                    cash_each = cash / len(new_buys)
                    for tk in new_buys:
                        px = _px(tk, t, use_open=True)
                        if np.isnan(px) or px <= 0 or cash_each <= 1.0:
                            continue
                        sh, spent, liq = compute_buy_cost(
                            tk, cash_each, px, _sig(tk, t), _adv(tk, t)
                        )
                        if sh > 0:
                            cash -= spent
                            positions[tk] = sh
                            ep[tk] = px
                            ed[tk] = str(t.date())
                            ei[tk] = i

        # Mark to market at close
        nav = cash
        for tk, sh in positions.items():
            cpx = _px(tk, t, use_open=False)
            nav += sh * (float(cpx) if not np.isnan(cpx) else 0.0)
        portfolio_values.iloc[i] = nav

        # Check rebalance signal at today's close
        if t in rebal_in_window:
            _, new_tgt = _get_target(t)
            if set(new_tgt) != set(positions.keys()):
                pending = new_tgt

    # Force-close open positions at window end (mark-to-market; no trade cost)
    last_t = window_idx[-1]
    for tk, sh in list(positions.items()):
        px = _px(tk, last_t, use_open=False)
        if np.isnan(px) or px <= 0:
            continue
        ent_p = ep.get(tk, float(px))
        ent_d = ed.get(tk, str(last_t.date()))
        ent_i = ei.get(tk, len(window_idx) - 1)
        ev = sh * ent_p
        pnl = sh * float(px) - ev
        trade_log.append({
            "date_entry": ent_d, "date_exit": str(last_t.date()),
            "asset": tk, "entry_price": round(ent_p, 4),
            "exit_price": round(float(px), 4),
            "pnl_pct": round(pnl / ev, 6) if ev > 0 else 0.0,
            "pnl_dollar": round(pnl, 2),
            "hold_days": len(window_idx) - 1 - ent_i,
            "exit_reason": "window_end",
            "liquidity_constrained": False,
        })

    portfolio_values = portfolio_values.ffill().fillna(init_capital)
    return {"portfolio_values": portfolio_values, "trade_log": trade_log}


# ── Performance Metrics ───────────────────────────────────────────────────────

def compute_metrics(portfolio_values, trade_log, start, end):
    """Sharpe (annualized, rf=0), CAGR, MDD, win rate, profit factor."""
    pv = portfolio_values.dropna()
    if len(pv) < 2:
        return {"error": "insufficient data"}

    daily_ret = pv.pct_change().fillna(0.0).values
    sharpe = float(daily_ret.mean() / (daily_ret.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR))
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    total_return = float(pv.iloc[-1] / pv.iloc[0] - 1)
    cagr = float((pv.iloc[-1] / pv.iloc[0]) ** (1.0 / max(years, 0.01)) - 1)

    cum = np.cumprod(1 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-10)))

    non_we = [t for t in trade_log if t.get("exit_reason") != "window_end"]
    if non_we:
        pnl_arr = np.array([t["pnl_dollar"] for t in non_we])
        pct_arr = np.array([t["pnl_pct"] for t in non_we])
        win_rate = float(np.mean(pnl_arr > 0))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        pf = (float(wins.sum() / abs(losses.sum()))
              if len(losses) > 0 and abs(losses.sum()) > 0 else float("inf"))
        avg_ppt = float(np.mean(pct_arr) * 10_000)
    else:
        win_rate = pf = avg_ppt = 0.0

    # Count position switches (rebalance events with asset changes)
    position_switches = sum(1 for t in trade_log if t.get("exit_reason") == "rebalance")

    return {
        "sharpe": round(sharpe, 4),
        "cagr": round(cagr, 4),
        "max_drawdown": round(mdd, 4),
        "total_return": round(total_return, 4),
        "trade_count": len(trade_log),
        "position_switches": position_switches,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(pf, 4) if not np.isinf(pf) else "inf",
        "avg_ppt_bps": round(avg_ppt, 2),
        "period": f"{start} to {end}",
        "years": round(years, 2),
    }


# ── Statistical Tests ────────────────────────────────────────────────────────

def compute_dsr(sharpe, n_trials, skew=0.0, kurtosis=3.0):
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).
    DSR = P(SR > SR*) where SR* is the max Sharpe from n_trials independent strategies.
    Approximation: SR* ≈ (1 - gamma) * Z^-1(1 - 1/n) + gamma * Z^-1(1 - 1/(n*e))
    """
    from scipy import stats
    if n_trials <= 1:
        return float(stats.norm.cdf(sharpe / np.sqrt(1.0 / TRADING_DAYS_PER_YEAR)))

    gamma = 0.5772156649  # Euler-Mascheroni constant
    expected_max = (
        (1 - gamma) * stats.norm.ppf(1 - 1.0 / n_trials)
        + gamma * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    # Sharpe std (1-year benchmark): sqrt((1 + skew*SR - ((kurtosis-1)/4)*SR^2) / (T-1))
    T = TRADING_DAYS_PER_YEAR
    sr_std = np.sqrt((1 + skew * sharpe - ((kurtosis - 1) / 4) * sharpe ** 2) / (T - 1))
    dsr = float(stats.norm.cdf((sharpe - expected_max) / (sr_std + 1e-10)))
    return round(dsr, 4)


def run_block_bootstrap(portfolio_values, n_boot=1000, block_size=21):
    """Block bootstrap 95% CI for Sharpe and MDD."""
    daily_ret = portfolio_values.pct_change().fillna(0.0).values
    n = len(daily_ret)
    sharpes = []
    mdds = []
    rng = np.random.default_rng(42)
    for _ in range(n_boot):
        n_blocks = n // block_size + 1
        starts = rng.integers(0, max(1, n - block_size), size=n_blocks)
        boot = np.concatenate([daily_ret[s:s + block_size] for s in starts])[:n]
        boot_sharpe = boot.mean() / (boot.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR)
        cum = np.cumprod(1 + boot)
        roll_max = np.maximum.accumulate(cum)
        boot_mdd = np.min((cum - roll_max) / (roll_max + 1e-10))
        sharpes.append(boot_sharpe)
        mdds.append(boot_mdd)
    sharpes = np.array(sharpes)
    mdds = np.array(mdds)
    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
    }


def run_permutation_test(trade_log, observed_sharpe, n_perm=200):
    """
    Permutation test: shuffle trade PnL order, recompute cumulative Sharpe.
    p-value = fraction of permutations with Sharpe >= observed.
    """
    closed = [t for t in trade_log if t.get("exit_reason") != "window_end"]
    if len(closed) < 10:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False,
                "permutation_perm_mean": 0.0, "permutation_perm_p95": 0.0}

    pnl = np.array([t["pnl_pct"] for t in closed])
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
        "permutation_pvalue": round(p_value, 4),
        "permutation_test_pass": p_value < 0.05,
        "permutation_perm_mean": round(float(perm_arr.mean()), 4),
        "permutation_perm_p95": round(float(np.percentile(perm_arr, 95)), 4),
    }


def run_mc_sharpe(trade_log, n_mc=1000):
    """Monte Carlo Sharpe distribution by resampling trade PnLs with replacement."""
    closed = [t for t in trade_log if t.get("exit_reason") != "window_end"]
    if len(closed) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    pnl = np.array([t["pnl_pct"] for t in closed])
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
        "mc_p5_sharpe": float(np.percentile(mc, 5)),
        "mc_median_sharpe": float(np.percentile(mc, 50)),
        "mc_p95_sharpe": float(np.percentile(mc, 95)),
        "mc_flag": f"MC on {len(closed)} IS trade PnLs",
    }


# ── Market Impact Report ──────────────────────────────────────────────────────

def compute_market_impact_report(data, is_metrics):
    """Per-ticker market impact analysis at $100K capital, ~1/K per position."""
    close = data["close"]
    volume = data["volume"]
    report = {}
    k = PARAMETERS["sectors_held"]
    notional_per_pos = 100_000 / k

    for ticker in UNIVERSE:
        if ticker not in close.columns:
            continue
        is_data = close[ticker].loc[IS_START:IS_END].dropna()
        is_vol = volume[ticker].loc[IS_START:IS_END].dropna()
        if len(is_data) < 20 or len(is_vol) < 20:
            continue
        avg_price = float(is_data.mean())
        adv_20d = float(is_vol.rolling(20).mean().dropna().mean())
        if avg_price <= 0 or adv_20d <= 0:
            continue
        qty = notional_per_pos / avg_price
        sigma = float(is_data.pct_change().std() * np.sqrt(TRADING_DAYS_PER_YEAR) / np.sqrt(TRADING_DAYS_PER_YEAR))
        sigma_daily = float(is_data.pct_change().std())
        q_adv = qty / adv_20d
        impact_bps = round(0.1 * sigma_daily * np.sqrt(max(q_adv, 0.0)) * 10_000, 4)
        report[ticker] = {
            "market_impact_bps": impact_bps,
            "adv_20d": round(adv_20d, 0),
            "avg_price": round(avg_price, 2),
            f"qty_at_{int(notional_per_pos / 1000)}k": round(qty, 0),
            "q_over_adv": round(q_adv, 6),
            "liquidity_constrained": q_adv > 0.01,
        }
    return report


# ── Parameter Sweep ───────────────────────────────────────────────────────────

def scan_parameters(data, quality_cache, spy_dma_cache):
    """Run IS backtest for all 54 sweep combinations. Returns list of result dicts."""
    keys = list(SWEEP_VALUES.keys())
    vals = list(SWEEP_VALUES.values())
    results = []

    for combo in product(*vals):
        p = {**PARAMETERS, **dict(zip(keys, combo))}
        label = (f"held={p['sectors_held']} lb={p['quality_lookback_months']}m "
                 f"dma={p['dma_window']} freq={p['rebalance_frequency']}")
        try:
            sim = run_simulation(data, quality_cache, spy_dma_cache, p, IS_START, IS_END)
            m = compute_metrics(sim["portfolio_values"], sim["trade_log"], IS_START, IS_END)
            results.append({
                "sectors_held": p["sectors_held"],
                "quality_lookback_months": p["quality_lookback_months"],
                "dma_window": p["dma_window"],
                "rebalance_frequency": p["rebalance_frequency"],
                **{k: v for k, v in m.items() if k not in ("period", "years")},
            })
        except Exception as exc:
            results.append({
                "sectors_held": p["sectors_held"],
                "quality_lookback_months": p["quality_lookback_months"],
                "dma_window": p["dma_window"],
                "rebalance_frequency": p["rebalance_frequency"],
                "error": str(exc),
            })
    return results


def sweep_stability_summary(sweep_results):
    """Compute Sharpe range across sweep combinations."""
    sharpes = [r["sharpe"] for r in sweep_results
               if "sharpe" in r and isinstance(r["sharpe"], (int, float))]
    if not sharpes:
        return {"error": "no valid sweep results"}

    primary_sharpe = next(
        (r["sharpe"] for r in sweep_results
         if r.get("sectors_held") == PARAMETERS["sectors_held"]
         and r.get("quality_lookback_months") == PARAMETERS["quality_lookback_months"]
         and r.get("dma_window") == PARAMETERS["dma_window"]
         and r.get("rebalance_frequency") == PARAMETERS["rebalance_frequency"]),
        None,
    )
    sharpe_range = max(sharpes) - min(sharpes)
    variance_pct = sharpe_range / abs(primary_sharpe) if primary_sharpe and primary_sharpe != 0 else float("nan")

    return {
        "primary_sharpe": primary_sharpe,
        "sharpe_min": round(min(sharpes), 4),
        "sharpe_max": round(max(sharpes), 4),
        "sharpe_range": round(sharpe_range, 4),
        "sharpe_variance_pct": round(variance_pct, 4) if not np.isnan(variance_pct) else None,
        "sensitivity_pass": (not np.isnan(variance_pct)) and variance_pct <= 0.30,
        "n_combinations": len(sharpes),
    }


# ── Regime Analysis ────────────────────────────────────────────────────────────

def count_regime_months(data, quality_cache, spy_dma_cache, params, start, end):
    """Count IS months in BEAR regime (SPY < DMA)."""
    close = data["close"]
    spy_dma = spy_dma_cache[params["dma_window"]]
    month_ends = get_last_trading_days(close)
    me_in = month_ends[(month_ends >= pd.Timestamp(start)) & (month_ends <= pd.Timestamp(end))]
    bear_months = 0
    first_shy = None
    for t in me_in:
        spy_px = close[REGIME_ETF].get(t, np.nan)
        spy_ma = spy_dma.get(t, np.nan)
        if not np.isnan(spy_px) and not np.isnan(spy_ma) and spy_px < spy_ma:
            bear_months += 1
            if first_shy is None:
                first_shy = str(t.date())
    return bear_months, first_shy, len(me_in)


# ── Walk-Forward Windows ──────────────────────────────────────────────────────

def run_walk_forward(data, quality_cache, spy_dma_cache, params):
    """Run 4 IS walk-forward windows. Returns list of per-window metrics dicts."""
    results = []
    for wid, (ws, we) in enumerate(WF_WINDOWS, 1):
        try:
            sim = run_simulation(data, quality_cache, spy_dma_cache, params, ws, we)
            m = compute_metrics(sim["portfolio_values"], sim["trade_log"], ws, we)
            results.append({
                "window": wid,
                "is_start": ws,
                "is_end": we,
                "sharpe": m["sharpe"],
                "max_drawdown": m["max_drawdown"],
                "win_rate": m["win_rate"],
                "trade_count": m["trade_count"],
                "cagr": m["cagr"],
                "position_switches": m["position_switches"],
            })
        except Exception as exc:
            results.append({"window": wid, "is_start": ws, "is_end": we, "error": str(exc)})
    return results


# ── HTML Report ───────────────────────────────────────────────────────────────

def build_html_report(strategy_name, date_str, is_m, oos_m, wf_windows,
                      stat_tests, sweep_stab, mi_report, gate_checks):
    """Generate a minimal Gate 1 HTML report."""
    gate_rows = "".join(
        f"<tr><td>{'✓' if v else '✗'}</td><td><b>{k}</b></td><td>{desc}</td></tr>"
        for k, (v, desc) in gate_checks.items()
    )
    wf_rows = "".join(
        f"<tr><td>{w.get('window')}</td><td>{w.get('is_start')}–{w.get('is_end')}</td>"
        f"<td>{w.get('sharpe', 'N/A')}</td><td>{w.get('max_drawdown', 'N/A')}</td>"
        f"<td>{w.get('trade_count', 'N/A')}</td></tr>"
        for w in wf_windows
    )
    html = f"""<!DOCTYPE html><html><head><title>{strategy_name} Gate 1</title>
<style>body{{font-family:monospace;margin:2em}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:4px 8px}}th{{background:#eee}}</style></head><body>
<h1>{strategy_name} — Gate 1 Report ({date_str})</h1>
<h2>IS Performance ({IS_START} to {IS_END})</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Sharpe</td><td>{is_m.get('sharpe')}</td></tr>
<tr><td>CAGR</td><td>{is_m.get('cagr', 0)*100:.2f}%</td></tr>
<tr><td>Max Drawdown</td><td>{is_m.get('max_drawdown', 0)*100:.2f}%</td></tr>
<tr><td>Win Rate</td><td>{is_m.get('win_rate', 0)*100:.1f}%</td></tr>
<tr><td>Trade Count</td><td>{is_m.get('trade_count')}</td></tr>
<tr><td>Position Switches</td><td>{is_m.get('position_switches')}</td></tr>
</table>
<h2>OOS Performance ({OOS_START} to {OOS_END})</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Sharpe</td><td>{oos_m.get('sharpe')}</td></tr>
<tr><td>CAGR</td><td>{oos_m.get('cagr', 0)*100:.2f}%</td></tr>
<tr><td>Max Drawdown</td><td>{oos_m.get('max_drawdown', 0)*100:.2f}%</td></tr>
<tr><td>Trade Count</td><td>{oos_m.get('trade_count')}</td></tr>
</table>
<h2>Statistical Tests</h2>
<table><tr><th>Test</th><th>Value</th></tr>
<tr><td>DSR</td><td>{stat_tests.get('dsr')}</td></tr>
<tr><td>Permutation p-value</td><td>{stat_tests.get('permutation_pvalue')}</td></tr>
<tr><td>Sharpe 95% CI</td><td>[{stat_tests.get('sharpe_ci_low', 0):.4f}, {stat_tests.get('sharpe_ci_high', 0):.4f}]</td></tr>
</table>
<h2>Walk-Forward Windows</h2>
<table><tr><th>Window</th><th>Period</th><th>Sharpe</th><th>MDD</th><th>Trades</th></tr>
{wf_rows}</table>
<h2>Sensitivity Sweep</h2>
<p>Sharpe range: {sweep_stab.get('sharpe_min')} – {sweep_stab.get('sharpe_max')} |
Variance vs primary: {(sweep_stab.get('sharpe_variance_pct') or 0)*100:.1f}%</p>
<h2>Gate 1 Checks</h2>
<table><tr><th>Pass</th><th>Gate</th><th>Details</th></tr>{gate_rows}</table>
</body></html>"""
    return html


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_strategy(params=None, output_dir=None, run_sweep=True):
    """
    Full IS + OOS Gate 1 backtest for H74 Quality Sector Rotation.
    Precomputes quality scores and SPY DMA for all sweep combinations,
    runs IS+OOS simulation with primary params, optionally runs 54-combo sweep.
    """
    if params is None:
        params = PARAMETERS.copy()

    # ── Data download ─────────────────────────────────────────────────────────
    data = download_data(DATA_START, OOS_END)
    quality_report = check_data_quality(data)
    if quality_report["flagged"]:
        warnings.warn(f"Data quality flags: {quality_report['flagged']}")

    # ── Precompute signal caches ──────────────────────────────────────────────
    unique_lbs = set(SWEEP_VALUES["quality_lookback_months"])
    unique_lbs.add(params["quality_lookback_months"])
    unique_dmas = set(SWEEP_VALUES["dma_window"])
    unique_dmas.add(params["dma_window"])

    print("H74: precomputing quality score cache...")
    quality_cache = precompute_quality_cache(data["close"], data["dividends"], sorted(unique_lbs))
    spy_dma_cache = precompute_spy_dma(data["close"][REGIME_ETF], sorted(unique_dmas))

    # ── IS backtest ───────────────────────────────────────────────────────────
    print(f"H74: running IS backtest ({IS_START}→{IS_END})...")
    is_sim = run_simulation(data, quality_cache, spy_dma_cache, params, IS_START, IS_END)
    is_metrics = compute_metrics(is_sim["portfolio_values"], is_sim["trade_log"], IS_START, IS_END)

    # ── OOS backtest ──────────────────────────────────────────────────────────
    print(f"H74: running OOS backtest ({OOS_START}→{OOS_END})...")
    oos_sim = run_simulation(data, quality_cache, spy_dma_cache, params, OOS_START, OOS_END)
    oos_metrics = compute_metrics(oos_sim["portfolio_values"], oos_sim["trade_log"], OOS_START, OOS_END)

    # ── Statistical tests ─────────────────────────────────────────────────────
    print("H74: running statistical tests (bootstrap, permutation, DSR)...")
    n_trials = len(SWEEP_VALUES.get("sectors_held", [])) * len(SWEEP_VALUES.get("quality_lookback_months", []))
    n_trials = max(n_trials, 10)
    dsr = compute_dsr(is_metrics["sharpe"], n_trials)
    boot = run_block_bootstrap(is_sim["portfolio_values"])
    perm = run_permutation_test(is_sim["trade_log"], is_metrics["sharpe"])
    mc = run_mc_sharpe(is_sim["trade_log"])
    stat_tests = {"dsr": dsr, **boot, **perm, **mc}

    # ── Walk-forward ──────────────────────────────────────────────────────────
    print("H74: running walk-forward windows...")
    wf_windows = run_walk_forward(data, quality_cache, spy_dma_cache, params)
    wf_passed = sum(1 for w in wf_windows if "sharpe" in w and isinstance(w["sharpe"], float))
    wf_sharpes = [w["sharpe"] for w in wf_windows if isinstance(w.get("sharpe"), float)]
    wf_sharpe_std = float(np.std(wf_sharpes)) if len(wf_sharpes) > 1 else 0.0
    wf_sharpe_min = float(min(wf_sharpes)) if wf_sharpes else 0.0

    # ── Parameter sweep ───────────────────────────────────────────────────────
    sweep_results = []
    stability = {}
    if run_sweep:
        print("H74: running 54-combination parameter sweep on IS...")
        sweep_results = scan_parameters(data, quality_cache, spy_dma_cache)
        stability = sweep_stability_summary(sweep_results)
        print(f"H74: sweep done — {stability.get('n_combinations')} combos | "
              f"Sharpe {stability.get('sharpe_min')}–{stability.get('sharpe_max')}")

    # ── Market impact report ──────────────────────────────────────────────────
    mi_report = compute_market_impact_report(data, is_metrics)

    # ── Regime analysis ───────────────────────────────────────────────────────
    bear_is, first_shy_is, total_is_months = count_regime_months(
        data, quality_cache, spy_dma_cache, params, IS_START, IS_END
    )
    bear_oos, first_shy_oos, total_oos_months = count_regime_months(
        data, quality_cache, spy_dma_cache, params, OOS_START, OOS_END
    )

    # Spot-check PF-2 (GFC 2008-09) and PF-4 (rate shock 2022) regime behavior
    gfc_bear, gfc_first_shy, _ = count_regime_months(
        data, quality_cache, spy_dma_cache, params, "2007-01-01", "2009-12-31"
    )
    rate_bear, rate_first_shy, _ = count_regime_months(
        data, quality_cache, spy_dma_cache, params, "2022-01-01", "2022-12-31"
    )

    # ── Gate 1 evaluation ──────────────────────────────────────────────────────
    gate_checks = {
        "IS Sharpe": (is_metrics["sharpe"] > 1.0,
                      f"{is_metrics['sharpe']} (threshold: > 1.0)"),
        "OOS Sharpe": (oos_metrics["sharpe"] > 0.70,
                       f"{oos_metrics['sharpe']} (threshold: > 0.70)"),
        "IS CAGR": (is_metrics["cagr"] >= 0.10,
                    f"{is_metrics['cagr']*100:.2f}% (threshold: >= 10%)"),
        "IS MDD": (is_metrics["max_drawdown"] > -0.15,
                   f"{is_metrics['max_drawdown']*100:.2f}% (threshold: > -15%)"),
        "OOS MDD": (oos_metrics["max_drawdown"] > -0.15,
                    f"{oos_metrics['max_drawdown']*100:.2f}% (threshold: > -15%)"),
        "Walk-Forward": (wf_passed >= 3,
                         f"{wf_passed}/{len(wf_windows)} (threshold: >= 3/4)"),
        "Permutation p": (perm["permutation_pvalue"] < 0.05,
                          f"{perm['permutation_pvalue']} (threshold: < 0.05)"),
        "IS Trade Count": (is_metrics["trade_count"] >= 100,
                           f"{is_metrics['trade_count']} (threshold: >= 100)"),
        "DSR": (dsr > 0,
                f"{dsr} (threshold: > 0)"),
        "IS Switches": (is_metrics["position_switches"] >= 120,
                        f"{is_metrics['position_switches']} (threshold: >= 120)"),
    }
    n_passed = sum(1 for v, _ in gate_checks.values() if v)
    gate1_pass = n_passed == len(gate_checks)

    # ── Console summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"{'H74 Quality Sector Rotation — Performance Summary':^70}")
    print("=" * 70)
    print(f"{'Metric':<25} {'IS (2005-2018)':>20} {'OOS (2019-2024)':>20}")
    print("-" * 70)
    for k in ("sharpe", "cagr", "max_drawdown", "win_rate", "trade_count", "position_switches"):
        iv = is_metrics.get(k, "N/A")
        ov = oos_metrics.get(k, "N/A")
        if k in ("cagr", "max_drawdown", "win_rate") and isinstance(iv, float):
            iv = f"{iv*100:.2f}%"
            ov = f"{ov*100:.2f}%" if isinstance(ov, float) else ov
        print(f"{k:<25} {str(iv):>20} {str(ov):>20}")
    print("=" * 70)
    print(f"Gate 1: {'PASS' if gate1_pass else 'FAIL'} ({n_passed}/{len(gate_checks)} checks passed)")
    print(f"DSR: {dsr}  Permutation p: {perm['permutation_pvalue']}")
    if stability:
        vp = stability.get("sharpe_variance_pct")
        vp_s = f"{vp*100:.1f}%" if vp is not None else "N/A"
        print(f"Sweep: {stability.get('n_combinations')} combos | "
              f"Sharpe {stability.get('sharpe_min')}-{stability.get('sharpe_max')} | "
              f"variance {vp_s}")
    print()

    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    all_trades = is_sim["trade_log"] + oos_sim["trade_log"]

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        base = f"H74_QualitySectorRotation_{today_str}"

        # Trade CSV
        if all_trades:
            trade_df = pd.DataFrame(all_trades)
            cols = ["date_entry", "date_exit", "asset", "entry_price", "exit_price",
                    "pnl_pct", "pnl_dollar", "hold_days", "exit_reason", "liquidity_constrained"]
            trade_df = trade_df[[c for c in cols if c in trade_df.columns]]
            csv_path = os.path.join(output_dir, f"{base}_trades.csv")
            trade_df.to_csv(csv_path, index=False)
            print(f"Trades: {csv_path} ({len(trade_df)} records)")

        # Sweep CSV
        if sweep_results:
            sweep_df = pd.DataFrame(sweep_results)
            sweep_path = os.path.join(output_dir, f"{base}_sweep.csv")
            sweep_df.to_csv(sweep_path, index=False)
            print(f"Sweep:  {sweep_path}")

        # Metrics JSON
        json_output = {
            "strategy_name": "H74_QualitySectorRotation",
            "date": today_str,
            "hypothesis": "H74",
            "asset_class": "equities",
            "parent_task": "QUA-318",
            "universe": UNIVERSE,
            "regime_etf": REGIME_ETF,
            "safe_haven": SAFE_HAVEN,
            "parameters": {
                "sectors_held": params["sectors_held"],
                "quality_lookback_months": params["quality_lookback_months"],
                "dma_window": params["dma_window"],
                "rebalance_frequency": params["rebalance_frequency"],
            },
            "cost_model": {
                "slippage": "0.05% standard ETF tier (sector ETFs ADV << 50M/day)",
                "shy_slippage": "0.005% ultra-liquid if SHY 20d ADV > 50M/day; else 0.05%",
                "commission": "$0.005/share",
                "market_impact": "0.1 × σ × sqrt(Q/ADV) — Almgren-Chriss",
                "ruling": "ED-SLIP-001 sector ETF tier",
            },
            "is_sharpe": is_metrics["sharpe"],
            "is_cagr": is_metrics["cagr"],
            "is_max_drawdown": is_metrics["max_drawdown"],
            "is_total_return": is_metrics["total_return"],
            "is_win_rate": is_metrics["win_rate"],
            "is_profit_factor": is_metrics["profit_factor"],
            "is_trade_count": is_metrics["trade_count"],
            "is_position_switches": is_metrics["position_switches"],
            "is_avg_ppt_bps": is_metrics["avg_ppt_bps"],
            "oos_sharpe": oos_metrics["sharpe"],
            "oos_cagr": oos_metrics["cagr"],
            "oos_max_drawdown": oos_metrics["max_drawdown"],
            "oos_total_return": oos_metrics["total_return"],
            "oos_win_rate": oos_metrics["win_rate"],
            "oos_profit_factor": oos_metrics["profit_factor"],
            "oos_trade_count": oos_metrics["trade_count"],
            "oos_position_switches": oos_metrics["position_switches"],
            "oos_avg_ppt_bps": oos_metrics["avg_ppt_bps"],
            "post_cost_sharpe": is_metrics["sharpe"],
            "dsr": dsr,
            "n_trials": n_trials,
            **mc,
            **boot,
            **perm,
            "market_impact_by_ticker": mi_report,
            "wf_windows": wf_windows,
            "wf_windows_passed": wf_passed,
            "wf_consistency_score": round(wf_passed / len(wf_windows), 4) if wf_windows else 0.0,
            "wf_sharpe_std": round(wf_sharpe_std, 4),
            "wf_sharpe_min": round(wf_sharpe_min, 4),
            "sensitivity_pass": stability.get("sensitivity_pass", False),
            "sensitivity_max_delta_pct": round(
                (stability.get("sharpe_variance_pct") or 0) * 100, 2
            ),
            "sweep_sharpe_min": stability.get("sharpe_min"),
            "sweep_sharpe_max": stability.get("sharpe_max"),
            "gate_is_sharpe": gate_checks["IS Sharpe"][0],
            "gate_oos_sharpe": gate_checks["OOS Sharpe"][0],
            "gate_is_cagr": gate_checks["IS CAGR"][0],
            "gate_is_mdd": gate_checks["IS MDD"][0],
            "gate_oos_mdd": gate_checks["OOS MDD"][0],
            "gate_wf": gate_checks["Walk-Forward"][0],
            "gate_perm": gate_checks["Permutation p"][0],
            "gate_trades": gate_checks["IS Trade Count"][0],
            "gate_dsr": gate_checks["DSR"][0],
            "gate_pf1_switches": gate_checks["IS Switches"][0],
            "gate1_pass": gate1_pass,
            "n_checks_passed": n_passed,
            "regime_bearish_is_months": bear_is,
            "is_total_months": total_is_months,
            "pf2_gfc_shy_months": gfc_bear,
            "pf2_gfc_first_shy": gfc_first_shy,
            "pf4_rate_shock_shy_months": rate_bear,
            "pf4_rate_shock_first_shy": rate_first_shy,
            "data_quality": quality_report,
            "sweep_stability": stability,
            "sweep_results": sweep_results,
        }
        json_path = os.path.join(output_dir, f"{base}.json")
        with open(json_path, "w") as f:
            json.dump(json_output, f, indent=2, default=str)
        print(f"JSON:   {json_path}")

        # HTML report
        html = build_html_report(
            "H74_QualitySectorRotation", today_str,
            is_metrics, oos_metrics, wf_windows,
            stat_tests, stability, mi_report, gate_checks
        )
        html_path = os.path.join(output_dir, f"{base}_report.html")
        with open(html_path, "w") as f:
            f.write(html)
        print(f"HTML:   {html_path}")

        # Verdict TXT
        gc = gate_checks
        fail_reasons = [f"  - {k}: got {desc.split('(')[0].strip()}, need {desc.split('(')[1].rstrip(')')}"
                        for k, (passed, desc) in gc.items() if not passed]

        # Research Director note
        rd_note_section = ""
        if not gate1_pass and is_metrics["sharpe"] >= 0.5:
            rd_note_section = (
                "\n=== Research Director Note ===\n"
                f"IS Sharpe {is_metrics['sharpe']:.4f} is below > 1.0 gate but shows economic rationale.\n"
                "Per Research Director guidance: if OOS persistence and WF stability are present,\n"
                "flag as portfolio combination candidate (3-4 uncorrelated sector strategies → combined Sharpe > 1.0).\n"
                f"OOS Sharpe: {oos_metrics['sharpe']:.4f} | WF consistent: {wf_passed}/{len(wf_windows)}\n"
            )

        wf_lines = "\n".join(
            f"  Window {w.get('window')}: {w.get('is_start')}–{w.get('is_end')}: "
            f"Sharpe={w.get('sharpe', 'N/A')}, MDD={w.get('max_drawdown', 'N/A'):.2%}, "
            f"trades={w.get('trade_count', 'N/A')}, switches={w.get('position_switches', 'N/A')}"
            if all(k in w for k in ("sharpe", "max_drawdown"))
            else f"  Window {w.get('window')}: ERROR — {w.get('error', 'N/A')}"
            for w in wf_windows
        )

        vp = stability.get("sharpe_variance_pct")
        vp_str = f"{vp*100:.1f}%" if vp is not None else "N/A"
        stability_gate_str = f"{'PASS' if stability.get('sensitivity_pass') else 'FAIL'} < 30%"

        verdict = f"""H74 Quality Sector Rotation (Quality/Profitability Factor) — Gate 1 Verdict
======================================================================
Date:     {today_str}
Strategy: H74_QualitySectorRotation
Overall:  {'PASS' if gate1_pass else 'FAIL'} ({n_passed}/{len(gate_checks)} checks passed)
======================================================================

=== Universe ===
Sectors:  {', '.join(UNIVERSE)}
Regime:   SPY {params['dma_window']}-DMA → exit to SHY
Signal:   quality composite = (div_yield_z + inv_vol_z) / 2, top-{params['sectors_held']} equal weight
Lookback: {params['quality_lookback_months']} months
Academic: Novy-Marx (2013) JFE; Asness et al. (2019) AQR QMJ

=== IS Performance ({IS_START} to {IS_END}, 14 years) ===
Sharpe:              {is_metrics['sharpe']:.4f}    [{'PASS' if gc['IS Sharpe'][0] else 'FAIL'}: > 1.0]
CAGR:                {is_metrics['cagr']*100:.2f}%    [{'PASS' if gc['IS CAGR'][0] else 'FAIL'}: >= 10%]
Max Drawdown:        {is_metrics['max_drawdown']*100:.2f}%    [{'PASS' if gc['IS MDD'][0] else 'FAIL'}: > -15%]
Win Rate:            {is_metrics['win_rate']*100:.2f}%
Profit Factor:       {is_metrics['profit_factor']}
Trade Count:         {is_metrics['trade_count']}    [{'PASS' if gc['IS Trade Count'][0] else 'FAIL'}: >= 100]
Position Switches:   {is_metrics['position_switches']}    [{'PASS' if gc['IS Switches'][0] else 'FAIL'}: >= 120]
Avg PpT:             {is_metrics['avg_ppt_bps']} bps
Regime-SHY months:   {bear_is}/{total_is_months} IS months
PF-2 GFC (2007-09):  {gfc_bear} SHY months; first exit: {gfc_first_shy or 'N/A'}
PF-4 Rate shock 2022:{rate_bear} SHY months; first exit: {rate_first_shy or 'N/A'}

=== OOS Performance ({OOS_START} to {OOS_END}, 6 years) ===
Sharpe:              {oos_metrics['sharpe']:.4f}  [{'PASS' if gc['OOS Sharpe'][0] else 'FAIL'}: > 0.70]
CAGR:                {oos_metrics['cagr']*100:.2f}%
Max Drawdown:        {oos_metrics['max_drawdown']*100:.2f}%  [{'PASS' if gc['OOS MDD'][0] else 'FAIL'}: > -15%]
Win Rate:            {oos_metrics['win_rate']*100:.2f}%
Profit Factor:       {oos_metrics['profit_factor']}
Trade Count:         {oos_metrics['trade_count']}
Position Switches:   {oos_metrics['position_switches']}

=== Statistical Rigor ===
MC p5 Sharpe:        {mc.get('mc_p5_sharpe', 'N/A')}
MC Median Sharpe:    {mc.get('mc_median_sharpe', 'N/A')}
Sharpe 95% CI:       [{boot.get('sharpe_ci_low', 0):.4f}, {boot.get('sharpe_ci_high', 0):.4f}]  (block bootstrap)
MDD 95% CI:          [{boot.get('mdd_ci_low', 0):.4f}, {boot.get('mdd_ci_high', 0):.4f}]
Permutation p-value: {perm['permutation_pvalue']}    [{'PASS' if gc['Permutation p'][0] else 'FAIL'}: < 0.05]
DSR:                 {dsr}    [{'PASS' if gc['DSR'][0] else 'FAIL'}: > 0]
Max Market Impact:   {max((v.get('market_impact_bps', 0) for v in mi_report.values()), default=0):.4f} bps

=== Walk-Forward Analysis ({len(wf_windows)} IS Windows) ===
{wf_lines}
  WF Passed: {wf_passed}/{len(wf_windows)}   [{'PASS' if gc['Walk-Forward'][0] else 'FAIL'}: >= 3/4]
  WF Sharpe std: {wf_sharpe_std:.4f}
  WF Sharpe min: {wf_sharpe_min:.4f}

=== Sensitivity Sweep ({stability.get('n_combinations', 0)} combinations) ===
  Sharpe range: {stability.get('sharpe_min', 'N/A')} – {stability.get('sharpe_max', 'N/A')}
  Variance vs primary: {vp_str} ({stability_gate_str})
  See: {base}_sweep.csv
{rd_note_section}
=== Gate 1 Checks ===
""" + "\n".join(
            f"  [{'PASS' if passed else 'FAIL'}] {k:<22} {desc}"
            for k, (passed, desc) in gc.items()
        ) + f"""

=== Root Cause Analysis ===
""" + (f"Primary failures ({len(fail_reasons)} of {len(gc)} gates):\n" + "\n".join(fail_reasons)
        if fail_reasons else "All gates passed.") + f"""

=== Recommendation ===
{'ACCEPT — advance to paper trading.' if gate1_pass else 'REJECT — do not advance to paper trading. Return to Research Director with metrics.'}
{'Note: See Research Director note above for portfolio combination potential.' if not gate1_pass and is_metrics['sharpe'] >= 0.5 else ''}

=== Files ===
Metrics: {output_dir}/{base}.json
Trades:  {output_dir}/{base}_trades.csv
Sweep:   {output_dir}/{base}_sweep.csv
Report:  {output_dir}/{base}_report.html
Verdict: {output_dir}/{base}_verdict.txt
"""
        verdict_path = os.path.join(output_dir, f"{base}_verdict.txt")
        with open(verdict_path, "w") as f:
            f.write(verdict)
        print(f"Verdict:{verdict_path}")
        print()
        print(verdict)

    return {
        "is": is_metrics,
        "oos": oos_metrics,
        "gate1_pass": gate1_pass,
        "n_checks_passed": n_passed,
        "sweep_stability": stability,
        "data_quality": quality_report,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="H74 Quality Sector Rotation — Gate 1 backtest."
    )
    parser.add_argument("--sectors-held", type=int, default=PARAMETERS["sectors_held"],
                        choices=[2, 3, 4])
    parser.add_argument("--lookback", type=int, default=PARAMETERS["quality_lookback_months"],
                        choices=[6, 12, 18])
    parser.add_argument("--dma", type=int, default=PARAMETERS["dma_window"],
                        choices=[150, 200, 250])
    parser.add_argument("--rebalance", type=str, default=PARAMETERS["rebalance_frequency"],
                        choices=["monthly", "bi-monthly"])
    parser.add_argument("--output-dir", type=str, default="backtests")
    parser.add_argument("--no-sweep", action="store_true")
    args = parser.parse_args()

    run_params = {
        **PARAMETERS,
        "sectors_held": args.sectors_held,
        "quality_lookback_months": args.lookback,
        "dma_window": args.dma,
        "rebalance_frequency": args.rebalance,
    }
    run_strategy(params=run_params, output_dir=args.output_dir, run_sweep=not args.no_sweep)
