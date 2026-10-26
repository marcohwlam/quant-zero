"""
Strategy: H72 Bond Yield Curve Carry (Duration Timing via Yield Curve Slope)
Author: Strategy Coder Agent
Date: 2026-06-16
Hypothesis: Monthly duration switch between TLT (20+ yr) and SHY (1-3 yr) based on
            10Y-2Y Treasury spread vs its trailing 12-month median. LONG_DURATION (TLT)
            when spread > trailing median; SHORT_DURATION (SHY) otherwise.
Asset class: US Treasury ETFs (TLT + SHY)
Parent task: QUA-309 / QUA-310

IS window:  2003-01-01 to 2018-12-31 (15 years, ~180 monthly signals)
OOS window: 2019-01-01 to 2024-12-31 (5 years, ~60 monthly signals)

Data: TLT + SHY daily OHLCV (yfinance auto_adjust=True)
      ^TNX (CBOE 10-Year Treasury Note Yield, % points)
      ^IRX (13-week T-Bill rate, % points) — used as 2Y yield proxy per QUA-310 spec.
      Rationale: signal depends on spread DIRECTION not absolute level; 2Y vs 3M is
      second-order. ^IRX tracks Fed policy rate closely and is available from 2002.
Capital: $100,000 starting capital. Leverage param for secondary tests (default 1.0×).

Transaction cost model (canonical AGENTS.md — standard ETF tier):
  TLT (ADV ~30M shares/day): $0.005/share + 0.05% slippage + market impact
  SHY (ADV ~15M shares/day): $0.005/share + 0.05% slippage + market impact
  Market impact: 0.1 × σ × sqrt(Q / ADV) — Almgren-Chriss square-root model
  Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True in trade log
  Note: At $100K capital, TLT ~$95/share → ~1,050 shares. TLT ADV ~30M → Q/ADV ≈ 0.0035%.
        Well below 1% threshold — no liquidity constraint expected at this capital level.

Alpha mechanism: Bond carry premium — yield curve slope predicts duration returns.
  Structural self-hedge: curve inversion (which destroys TLT) IS the exit signal.
References:
  Koijen et al. (2018): "Carry" — JFE 127(2), 197-225
  Cochrane & Piazzesi (2005): "Bond Risk Premia" — AER 95(1), 138-160
  Ilmanen (2011): Expected Returns ch. 9 (Government Bond Carry)
  Ilmanen (2016): Factor Investing — duration timing Sharpe 0.8-1.2 (1964-2016)
"""

import argparse
import json
import os
import warnings
from itertools import product

import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ───────────────────────────────────────────────────────────────────

PARAMETERS = {
    "slope_lookback_months": 12,   # trailing months for median spread computation
    "spread_threshold": None,       # None → rolling median; float → fixed % threshold
    "leverage": 1.0,                # 1.0 = unleveraged primary; 1.5/2.0 for secondary
    "init_capital": 100_000.0,
}

SWEEP_VALUES = {
    # 4 × 3 = 12 combinations
    "slope_lookback_months": [6, 12, 18, 24],
    "spread_threshold": [None, 0.0, -0.25],  # None=rolling median, 0.0=zero-crossing, -0.25=-25bps
}

IS_START = "2003-01-01"
IS_END = "2018-12-31"
OOS_START = "2019-01-01"
OOS_END = "2024-12-31"
DATA_START = "2002-07-01"   # TLT/SHY inception; warmup period for spread median
TRADING_DAYS_PER_YEAR = 252

YIELD_DATA_NOTE = (
    "10Y yield: ^TNX (CBOE 10-Year Treasury Note Yield, yfinance). "
    "2Y yield proxy: ^IRX (13-week T-Bill rate, yfinance). "
    "^IRX used as 2Y proxy per QUA-310 spec — signal is spread direction, not absolute level."
)


# ── Data Loading ─────────────────────────────────────────────────────────────────

def download_data(start: str = DATA_START, end: str = OOS_END) -> dict:
    """
    Download TLT/SHY ETF prices and ^TNX/^IRX yield data from yfinance.

    Returns dict with:
      close, open_, volume: DataFrames[TLT, SHY] (split+dividend adjusted)
      yield_10y: Series (^TNX in % points, reindexed to ETF trading days)
      yield_2y:  Series (^IRX in % points, reindexed to ETF trading days)
    """
    print(f"H72: downloading TLT/SHY from {start} to {end}...")
    etf_raw = yf.download(
        ["TLT", "SHY"],
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
    )

    if not isinstance(etf_raw.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex columns from yfinance multi-ticker download.")

    close = etf_raw["Close"][["TLT", "SHY"]].copy()
    open_ = etf_raw["Open"][["TLT", "SHY"]].copy()
    volume = etf_raw["Volume"][["TLT", "SHY"]].copy()
    close = close.dropna(how="all")
    open_ = open_.reindex(close.index)
    volume = volume.reindex(close.index)

    print(f"H72: downloading ^TNX / ^IRX from {start} to {end}...")
    yield_raw = yf.download(
        ["^TNX", "^IRX"],
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
    )

    if isinstance(yield_raw.columns, pd.MultiIndex):
        tnx = yield_raw["Close"]["^TNX"].copy()
        irx = yield_raw["Close"]["^IRX"].copy()
    else:
        raise ValueError("Expected MultiIndex columns for yield data download.")

    # Align yield data to ETF trading day calendar; ffill gaps up to 5 business days
    tnx = tnx.reindex(close.index).ffill(limit=5)
    irx = irx.reindex(close.index).ffill(limit=5)

    return {
        "close": close,
        "open_": open_,
        "volume": volume,
        "yield_10y": tnx,
        "yield_2y": irx,
    }


def check_data_quality(data: dict) -> dict:
    """
    Pre-backtest data quality validation per H72 Data Quality Checklist.
    Flags gaps > 5 consecutive missing trading days for ETF prices or yields.
    """
    close = data["close"]
    report = {
        "survivorship_bias": (
            "Fixed 2-ETF universe: TLT (inception Jul 2002) + SHY (inception Jul 2002). "
            "Both active major ETFs, no delisting risk. No survivorship bias."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "yield_data_source": YIELD_DATA_NOTE,
        "earnings_exclusion": "N/A — bond ETFs have no earnings events.",
        "tickers": {},
        "yield_gaps": {},
        "flagged": [],
    }

    def _gap_check(series, label):
        clean = series.dropna()
        if len(clean) == 0:
            return {"error": "No data"}, True
        trimmed = series.loc[clean.index[0]:]
        max_gap = consec = 0
        for v in trimmed.isna():
            consec = (consec + 1) if v else 0
            max_gap = max(max_gap, consec)
        gap_flag = max_gap > 5
        if gap_flag:
            warnings.warn(f"Data gap flag: {label} has {max_gap} consecutive missing days (>5 threshold).")
        return {
            "total_obs": int(len(clean)),
            "max_consecutive_missing": max_gap,
            "gap_flag": gap_flag,
            "start": str(clean.index.min().date()),
            "end": str(clean.index.max().date()),
        }, gap_flag

    for ticker in ["TLT", "SHY"]:
        info, flagged = _gap_check(close[ticker], ticker)
        report["tickers"][ticker] = info
        if flagged:
            report["flagged"].append(ticker)

    for label, series in [("^TNX_10y", data["yield_10y"]), ("^IRX_2y_proxy", data["yield_2y"])]:
        info, flagged = _gap_check(series, label)
        report["yield_gaps"][label] = info
        if flagged:
            report["flagged"].append(label)

    return report


# ── Monthly Signal Computation ────────────────────────────────────────────────────

def get_last_trading_days(close: pd.DataFrame) -> pd.DatetimeIndex:
    """
    Return last trading day of each calendar month present in close.index.
    Uses resample('ME') to group by calendar month, then takes the last available date.
    """
    helper = pd.Series(close.index, index=close.index)
    last_days = helper.resample("ME").last().dropna()
    return pd.DatetimeIndex(last_days.values)


def compute_monthly_signals(data: dict, params: dict) -> pd.DataFrame:
    """
    Compute 10Y-2Y spread and duration signal at last trading day of each month.

    Signal rules (computed at month-end with no look-ahead):
      spread_t = yield_10y_t - yield_2y_t  (in percentage points)
      threshold = rolling N-month median of spread  (if spread_threshold is None)
               = fixed float value                  (if spread_threshold is a float)
      LONG_DURATION (TLT) if spread_t > threshold
      SHORT_DURATION (SHY) otherwise

    Returns DataFrame indexed by actual last-trading-day Timestamps:
      spread, spread_median, threshold_used, target_position ("TLT"|"SHY")
    """
    close = data["close"]
    yield_10y = data["yield_10y"]
    yield_2y = data["yield_2y"]
    lookback = params["slope_lookback_months"]
    threshold_param = params.get("spread_threshold")  # None or float

    ltd = get_last_trading_days(close)

    # Sample yields at each month-end trading day
    tnx_m = yield_10y.reindex(ltd)
    irx_m = yield_2y.reindex(ltd)
    spread = (tnx_m - irx_m).copy()
    spread.index = ltd

    # Forward-fill isolated NaN months (holiday gaps already handled in download_data)
    spread = spread.ffill(limit=2)

    # Trailing median — rolling over monthly observations (min 3 months required)
    spread_median = spread.rolling(lookback, min_periods=3).median()

    # Threshold: rolling median or fixed value
    if threshold_param is None:
        threshold_series = spread_median
    else:
        threshold_series = pd.Series(float(threshold_param), index=spread.index)

    # Position: TLT if spread strictly above threshold, else SHY
    target = pd.Series(index=spread.index, dtype=object)
    valid = spread.notna() & threshold_series.notna()
    target[valid] = np.where(spread[valid] > threshold_series[valid], "TLT", "SHY")

    return pd.DataFrame({
        "spread": spread,
        "spread_median": spread_median,
        "threshold_used": threshold_series,
        "target_position": target,
    })


# ── Transaction Cost Model ────────────────────────────────────────────────────────

def compute_buy_shares(
    asset: str, cash: float, price: float, sigma: float, adv_shares: float
) -> tuple:
    """
    Deploy `cash` into `asset` at `price` with standard ETF transaction cost model.

    Returns: (shares, cash_spent, liquidity_constrained, cost_breakdown)
    """
    if price <= 0 or cash <= 0:
        return 0.0, 0.0, False, {}

    slippage = 0.0005   # 0.05% standard ETF tier
    adv_safe = max(adv_shares, 1.0) if not (np.isnan(adv_shares) if isinstance(adv_shares, float) else False) else 1.0
    sigma_safe = sigma if not np.isnan(sigma) else 0.0

    est_shares = cash / (price * (1 + slippage) + 0.005)
    q_over_adv = est_shares / adv_safe
    impact = 0.1 * sigma_safe * np.sqrt(max(q_over_adv, 0.0))
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
        "market_impact_pct": round(impact, 6),
        "total_cost_pct": round(total_pct, 6),
        "commission_per_share": 0.005,
        "q_over_adv": round(q_over_adv, 6),
    }


def compute_sell_proceeds(
    asset: str, shares: float, price: float, sigma: float, adv_shares: float
) -> tuple:
    """
    Sell `shares` of `asset` at `price` with standard ETF transaction cost model.

    Returns: (net_proceeds, liquidity_constrained, cost_breakdown)
    """
    if shares <= 0 or price <= 0:
        return 0.0, False, {}

    slippage = 0.0005
    adv_safe = max(adv_shares, 1.0) if not np.isnan(adv_shares) else 1.0
    sigma_safe = sigma if not np.isnan(sigma) else 0.0
    q_over_adv = shares / adv_safe
    impact = 0.1 * sigma_safe * np.sqrt(max(q_over_adv, 0.0))
    total_pct = slippage + impact

    commission = shares * 0.005
    net_proceeds = max(shares * price * (1 - total_pct) - commission, 0.0)

    liquidity_constrained = q_over_adv > 0.01
    if liquidity_constrained:
        warnings.warn(
            f"LIQUIDITY-CONSTRAINED SELL: {asset} Q/ADV={q_over_adv:.4f} > 1% — "
            f"shares={shares:.0f}, ADV={adv_shares:.0f}"
        )

    return net_proceeds, liquidity_constrained, {
        "slippage_pct": slippage,
        "market_impact_pct": round(impact, 6),
        "total_cost_pct": round(total_pct, 6),
        "commission": round(commission, 2),
        "q_over_adv": round(q_over_adv, 6),
    }


# ── Portfolio Simulation ─────────────────────────────────────────────────────────

def run_simulation(
    data: dict,
    monthly_signals: pd.DataFrame,
    params: dict,
    start: str,
    end: str,
) -> dict:
    """
    Event-driven monthly duration-timing backtest for H72.

    Execution model:
    - Initial position: last monthly signal at or before `start`
    - Initial entry: open of first trading day in window
    - Monthly rebalance: signal at close of last trading day of month t
    - Switch execution: open of next trading day after month-end
    - Always fully invested: TLT or SHY (no uninvested cash once entered)
    - Leverage > 1.0: deploy leverage × cash (cash goes negative = borrowed; no margin cost modeled)

    Returns dict with portfolio_values (pd.Series daily), trade_log (list of dicts).
    """
    close = data["close"]
    open_ = data["open_"]
    volume = data["volume"]
    leverage = params.get("leverage", 1.0)
    init_capital = params["init_capital"]

    window = close.loc[start:end].index
    if len(window) < 5:
        raise ValueError(f"Insufficient data for period {start}:{end}")

    # Initial position from last signal before (or at) window start
    prior = monthly_signals[
        monthly_signals.index <= pd.Timestamp(start)
    ]["target_position"].dropna()
    if len(prior) > 0:
        initial_target = prior.iloc[-1]
    else:
        in_win = monthly_signals.loc[start:end]["target_position"].dropna()
        initial_target = in_win.iloc[0] if len(in_win) > 0 else "TLT"

    # Month-end dates within window (set for O(1) lookup)
    sig_in_window = monthly_signals.loc[start:end]
    month_end_set = set(sig_in_window.dropna(subset=["target_position"]).index)

    # Precomputed 20-day rolling vol and ADV
    tlt_sigma = close["TLT"].pct_change().rolling(20).std()
    shy_sigma = close["SHY"].pct_change().rolling(20).std()
    tlt_adv = volume["TLT"].rolling(20).mean()
    shy_adv = volume["SHY"].rolling(20).mean()

    # Simulation state
    cash = float(init_capital)
    position = None      # "TLT" | "SHY" | None
    shares = 0.0
    entry_price = None
    entry_date_str = None
    entry_idx = None

    # First action: buy initial_target at open of day 0
    pending_target = initial_target

    portfolio_values = pd.Series(index=window, dtype=float)
    trade_log = []

    def _get(series, t, fallback=np.nan):
        v = series.get(t, fallback)
        return fallback if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)

    for i, t in enumerate(window):
        tlt_open = _get(open_["TLT"], t)
        shy_open = _get(open_["SHY"], t)
        tlt_close = _get(close["TLT"], t)
        shy_close = _get(close["SHY"], t)

        # ── Execute pending switch / initial entry at today's open ────────────
        if pending_target is not None:
            target_asset = pending_target
            pending_target = None
            exec_open = tlt_open if target_asset == "TLT" else shy_open
            if np.isnan(exec_open):
                exec_open = tlt_close if target_asset == "TLT" else shy_close

            # Sell current holding first (if any)
            if position is not None and shares > 0:
                sell_px = tlt_open if position == "TLT" else shy_open
                if np.isnan(sell_px):
                    sell_px = tlt_close if position == "TLT" else shy_close
                sig = _get(tlt_sigma, t, 0.0) if position == "TLT" else _get(shy_sigma, t, 0.0)
                adv = _get(tlt_adv, t, 1e6) if position == "TLT" else _get(shy_adv, t, 1e6)

                proceeds, liq_sell, sell_costs = compute_sell_proceeds(
                    position, shares, sell_px, sig, adv
                )
                cash += proceeds

                hold_days = i - (entry_idx or 0)
                entry_val = shares * (entry_price or sell_px)
                pnl_dollar = proceeds - entry_val
                pnl_pct = pnl_dollar / entry_val if entry_val > 0 else 0.0
                trade_log.append({
                    "date_entry": entry_date_str,
                    "date_exit": str(t.date()),
                    "asset": position,
                    "entry_price": round(entry_price, 4) if entry_price else None,
                    "exit_price": round(sell_px, 4),
                    "pnl_pct": round(pnl_pct, 6),
                    "pnl_dollar": round(pnl_dollar, 2),
                    "hold_days": hold_days,
                    "exit_reason": "monthly_rebalance" if i > 0 else "initial_entry_replace",
                    "liquidity_constrained": liq_sell,
                    "cost_breakdown": sell_costs,
                })
                position = None
                shares = 0.0
                entry_price = None
                entry_date_str = None
                entry_idx = None

            # Buy target
            if not np.isnan(exec_open) and exec_open > 0:
                sig = _get(tlt_sigma, t, 0.0) if target_asset == "TLT" else _get(shy_sigma, t, 0.0)
                adv = _get(tlt_adv, t, 1e6) if target_asset == "TLT" else _get(shy_adv, t, 1e6)
                deploy = cash * leverage
                sh, spent, liq_buy, buy_costs = compute_buy_shares(
                    target_asset, deploy, exec_open, sig, adv
                )
                if sh > 0:
                    cash -= spent   # may go negative if leverage > 1 (borrowed capital)
                    shares = sh
                    position = target_asset
                    entry_price = exec_open
                    entry_date_str = str(t.date())
                    entry_idx = i

        # ── Mark to market at close ───────────────────────────────────────────
        if position == "TLT":
            mark = tlt_close if not np.isnan(tlt_close) else tlt_open
        elif position == "SHY":
            mark = shy_close if not np.isnan(shy_close) else shy_open
        else:
            mark = 0.0

        nav = cash + shares * (mark or 0.0)
        portfolio_values.iloc[i] = nav

        # ── Check month-end signal at close (queues next-day execution) ───────
        if t in month_end_set:
            new_target = monthly_signals.loc[t, "target_position"]
            if pd.notna(new_target) and new_target != position:
                pending_target = new_target

    # Force-close final position at window end (mark-to-market, no trade cost)
    if position is not None and shares > 0:
        last_t = window[-1]
        last_px = _get(close[position], last_t)
        if last_px > 0:
            hold_days = len(window) - 1 - (entry_idx or 0)
            entry_val = shares * (entry_price or last_px)
            pnl_dollar = shares * last_px - entry_val
            pnl_pct = pnl_dollar / entry_val if entry_val > 0 else 0.0
            trade_log.append({
                "date_entry": entry_date_str,
                "date_exit": str(last_t.date()),
                "asset": position,
                "entry_price": round(entry_price, 4) if entry_price else None,
                "exit_price": round(last_px, 4),
                "pnl_pct": round(pnl_pct, 6),
                "pnl_dollar": round(pnl_dollar, 2),
                "hold_days": hold_days,
                "exit_reason": "window_end",
                "liquidity_constrained": False,
                "cost_breakdown": {},
            })

    portfolio_values = portfolio_values.ffill().fillna(init_capital)
    return {"portfolio_values": portfolio_values, "trade_log": trade_log}


# ── Performance Metrics ───────────────────────────────────────────────────────────

def compute_metrics(
    portfolio_values: pd.Series, trade_log: list, start: str, end: str
) -> dict:
    """
    Compute IS/OOS performance metrics: Sharpe, CAGR, MDD, win rate, profit factor.
    Risk-free rate = 0 (bond ETF already earns Treasury yield; no risk-free deduction).
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

    # Closed trades only (exclude open window_end entry which has no exit cost)
    closed = [t for t in trade_log if t.get("exit_reason") != "window_end"]
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
        win_rate = profit_factor = avg_ppt_bps = 0.0

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


# ── Parameter Sweep ───────────────────────────────────────────────────────────────

def scan_parameters(data: dict) -> list:
    """
    Run IS backtest for all SWEEP_VALUES combinations (4 lookbacks × 3 thresholds = 12 total).

    Returns list of dicts with params + IS metrics.
    """
    results = []
    keys = list(SWEEP_VALUES.keys())
    vals = list(SWEEP_VALUES.values())

    for combo in product(*vals):
        p = {**PARAMETERS, **dict(zip(keys, combo))}
        try:
            signals = compute_monthly_signals(data, p)
            sim = run_simulation(data, signals, p, IS_START, IS_END)
            m = compute_metrics(sim["portfolio_values"], sim["trade_log"], IS_START, IS_END)
            thr_label = "median" if p["spread_threshold"] is None else str(p["spread_threshold"])
            results.append({
                "slope_lookback_months": p["slope_lookback_months"],
                "spread_threshold": thr_label,
                **{k: v for k, v in m.items() if k not in ("period", "years")},
            })
        except Exception as exc:
            thr_label = "median" if p.get("spread_threshold") is None else str(p.get("spread_threshold"))
            results.append({
                "slope_lookback_months": p["slope_lookback_months"],
                "spread_threshold": thr_label,
                "error": str(exc),
            })

    return results


def sweep_stability_summary(sweep_results: list) -> dict:
    """Compute Sharpe range across sweep and Gate 1 stability check (< 30% variation)."""
    sharpes = [
        r["sharpe"] for r in sweep_results
        if "sharpe" in r and isinstance(r["sharpe"], (int, float))
    ]
    if not sharpes:
        return {"error": "No valid sweep results"}

    primary = next(
        (r["sharpe"] for r in sweep_results
         if r.get("slope_lookback_months") == PARAMETERS["slope_lookback_months"]
         and r.get("spread_threshold") == "median"),   # primary uses rolling median
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


# ── Main Entry Point ──────────────────────────────────────────────────────────────

def run_strategy(
    params: dict = PARAMETERS,
    output_dir: str = None,
    run_sweep: bool = True,
) -> dict:
    """
    Full IS+OOS backtest for H72 Bond Yield Curve Carry.

    Downloads data once, runs IS and OOS, optionally runs 12-combination param sweep,
    writes trade log CSV and metrics JSON to output_dir (if provided).

    Returns dict with IS metrics, OOS metrics, sweep results, data quality report.
    """
    print(f"H72: downloading data {DATA_START} → {OOS_END}...")
    data = download_data(DATA_START, OOS_END)

    quality = check_data_quality(data)
    if quality["flagged"]:
        warnings.warn(f"Data quality flags: {quality['flagged']}")

    print(
        f"H72: computing monthly signals "
        f"(lookback={params['slope_lookback_months']}m, "
        f"threshold={'median' if params['spread_threshold'] is None else params['spread_threshold']})..."
    )
    monthly_signals = compute_monthly_signals(data, params)

    print(f"H72: running IS backtest {IS_START} → {IS_END}...")
    is_sim = run_simulation(data, monthly_signals, params, IS_START, IS_END)
    is_metrics = compute_metrics(is_sim["portfolio_values"], is_sim["trade_log"], IS_START, IS_END)

    print(f"H72: running OOS backtest {OOS_START} → {OOS_END}...")
    oos_sim = run_simulation(data, monthly_signals, params, OOS_START, OOS_END)
    oos_metrics = compute_metrics(oos_sim["portfolio_values"], oos_sim["trade_log"], OOS_START, OOS_END)

    sweep_results = []
    stability = {}
    if run_sweep:
        print("H72: running 12-combination parameter sweep on IS...")
        sweep_results = scan_parameters(data)
        stability = sweep_stability_summary(sweep_results)
        print(f"H72: sweep complete — {stability.get('gate1_stability', 'N/A')}")

    # Print summary table
    print("\n" + "=" * 70)
    print(f"{'H72 Bond Yield Curve Carry — Performance Summary':^70}")
    print("=" * 70)
    print(f"{'Metric':<25} {'IS (2003-2018)':>20} {'OOS (2019-2024)':>20}")
    print("-" * 70)
    for key in ("sharpe", "cagr", "max_drawdown", "win_rate", "trade_count", "avg_ppt_bps"):
        print(f"{key:<25} {str(is_metrics.get(key, 'N/A')):>20} {str(oos_metrics.get(key, 'N/A')):>20}")
    print("=" * 70)
    if stability:
        print(f"Sweep stability: {stability.get('gate1_stability', 'N/A')}")
    print()

    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    all_trades = is_sim["trade_log"] + oos_sim["trade_log"]

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        base = f"H72_BondYieldCurveCarry_{today_str}"

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
            print(f"Trade log: {csv_path} ({len(trade_df)} trades)")
        else:
            print("No trades generated.")

        # Sweep CSV
        if sweep_results:
            sweep_df = pd.DataFrame(sweep_results)
            sweep_path = os.path.join(output_dir, f"{base}_sweep.csv")
            sweep_df.to_csv(sweep_path, index=False)
            print(f"Sweep CSV: {sweep_path}")

        # Metrics JSON
        thr_label = "median" if params["spread_threshold"] is None else params["spread_threshold"]
        json_output = {
            "strategy": "H72_BondYieldCurveCarry",
            "date": today_str,
            "parameters": {
                "slope_lookback_months": params["slope_lookback_months"],
                "spread_threshold": thr_label,
                "leverage": params["leverage"],
            },
            "initial_capital": params["init_capital"],
            "yield_data_note": YIELD_DATA_NOTE,
            "cost_model": {
                "tlt_slippage": "0.05% (standard ETF tier)",
                "shy_slippage": "0.05% (standard ETF tier)",
                "fixed_commission": "$0.005/share",
                "market_impact": "0.1 × σ × sqrt(Q/ADV) — Almgren-Chriss",
                "liquidity_flag_threshold": "Q/ADV > 0.01",
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
        print(f"Metrics JSON: {json_path}")

    return {
        "is": is_metrics,
        "oos": oos_metrics,
        "sweep_stability": stability,
        "sweep_results": sweep_results,
        "data_quality": quality,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="H72 Bond Yield Curve Carry — duration timing via 10Y-2Y spread."
    )
    parser.add_argument(
        "--lookback", type=int, default=PARAMETERS["slope_lookback_months"],
        choices=SWEEP_VALUES["slope_lookback_months"],
        help="Trailing months for spread median (default: 12)",
    )
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="Fixed spread threshold in %% points (default: None = rolling median)",
    )
    parser.add_argument(
        "--leverage", type=float, default=PARAMETERS["leverage"],
        help="Position leverage multiplier (default: 1.0; margin cost not modeled)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Directory for trade CSV, sweep CSV, and JSON metrics output",
    )
    parser.add_argument(
        "--no-sweep", action="store_true",
        help="Skip 12-combination parameter sweep (faster run)",
    )
    args = parser.parse_args()

    run_params = {
        **PARAMETERS,
        "slope_lookback_months": args.lookback,
        "spread_threshold": args.threshold,
        "leverage": args.leverage,
    }

    run_strategy(
        params=run_params,
        output_dir=args.output_dir,
        run_sweep=not args.no_sweep,
    )
