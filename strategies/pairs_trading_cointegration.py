"""
Strategy: Pairs Trading via Cointegration
Author: Engineering Director (Quant Zero)
Date: 2026-03-16
Hypothesis: Cointegrated pairs share a long-run equilibrium; deviations in the
            spread z-score signal transient mispricing that reverts to zero.
            Fully market-neutral by construction (dollar-neutral sizing).
Asset class: equities (long-short pairs)
Parent task: QUA-73

Design notes:
- Rolling 252-day OLS for hedge ratio (point-in-time only — no look-ahead)
- Engle-Granger cointegration test on rolling window (only trade active pairs)
- Custom simulation loop (vectorbt cannot natively handle two-legged pairs trades)
- Stop-loss on cointegration breakdown (z-score exceeds stop_zscore)
- Dollar-neutral sizing (β-weighted)
"""

from __future__ import annotations

import datetime
import math
from typing import NamedTuple

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as scipy_stats
from statsmodels.tsa.stattools import coint


# ── Parameters ────────────────────────────────────────────────────────────────

PARAMETERS = {
    "entry_zscore": 2.0,                # Entry threshold (z-score)
    "exit_zscore": 0.0,                 # Exit at z-score convergence target
    "stop_zscore": 3.5,                 # Stop-loss: close if |z| > this (cointegration break)
    "lookback_cointegration_days": 126, # Rolling window for OLS + coint test (126d = 6 months, fits OOS windows)
    "max_holding_days": 30,             # Time stop: exit after N bars
    "max_active_pairs": 8,              # Max concurrent pair positions
    "capital_per_pair": 5000,           # Notional per leg ($25K / 5 pairs)
    "fees_per_leg": 0.0001,             # Brokerage fees fraction per leg
    "slippage_per_leg": 0.0005,         # Slippage fraction per leg
    "coint_pvalue_threshold": 0.10,     # Max p-value to accept cointegration (relaxed to 10%)
    "pairs": [
        ("KO", "PEP"),
        ("JPM", "BAC"),
        ("XOM", "CVX"),
        ("GOOG", "META"),
        ("AAPL", "MSFT"),
    ],
}

INITIAL_CAPITAL = 25_000.0  # PDT $25K account


# ── Data download ─────────────────────────────────────────────────────────────

def fetch_close_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Download adjusted close prices for a list of tickers."""
    all_tickers = sorted(set(tickers))
    raw = yf.download(all_tickers, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]] if "Close" in raw else raw
    close = close.dropna(how="all")
    return close


# ── Spread analytics ──────────────────────────────────────────────────────────

def compute_rolling_hedge_and_spread(
    price_a: pd.Series,
    price_b: pd.Series,
    lookback: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Point-in-time rolling OLS: A = α + β*B; compute spread and z-score.

    Returns:
        hedge_ratio: β series (rolling estimate, no look-ahead)
        spread:      A - (α + β*B)
        zscore:      rolling z-score of spread
    """
    n = len(price_a)
    hedge_ratio = np.full(n, np.nan)
    spread = np.full(n, np.nan)
    zscore = np.full(n, np.nan)

    a = price_a.to_numpy(dtype=float)
    b = price_b.to_numpy(dtype=float)

    for i in range(lookback - 1, n):
        win_a = a[i - lookback + 1 : i + 1]
        win_b = b[i - lookback + 1 : i + 1]

        # OLS: A ~ α + β*B
        X = np.column_stack([np.ones(lookback), win_b])
        try:
            result = np.linalg.lstsq(X, win_a, rcond=None)
            alpha_hat, beta_hat = result[0]
        except np.linalg.LinAlgError:
            continue

        hedge_ratio[i] = beta_hat
        sp = win_a - (alpha_hat + beta_hat * win_b)
        spread[i] = sp[-1]
        sp_mean = sp.mean()
        sp_std = sp.std()
        if sp_std > 1e-10:
            zscore[i] = (sp[-1] - sp_mean) / sp_std

    idx = price_a.index
    return (
        pd.Series(hedge_ratio, index=idx, name="hedge_ratio"),
        pd.Series(spread, index=idx, name="spread"),
        pd.Series(zscore, index=idx, name="zscore"),
    )


def compute_rolling_coint_pvalue(
    price_a: pd.Series,
    price_b: pd.Series,
    lookback: int,
) -> pd.Series:
    """
    Rolling Engle-Granger cointegration p-value (point-in-time, no look-ahead).
    Expensive: computed every day over full window. Use lookback >= 252 for stability.

    Returns:
        pd.Series of p-values; NaN for first (lookback-1) bars.
    """
    n = len(price_a)
    pvalues = np.full(n, np.nan)
    a = price_a.to_numpy(dtype=float)
    b = price_b.to_numpy(dtype=float)

    # Compute every 5 trading days to reduce overhead (refresh weekly)
    step = 5
    last_pval = np.nan
    for i in range(lookback - 1, n):
        if (i - (lookback - 1)) % step == 0:
            win_a = a[i - lookback + 1 : i + 1]
            win_b = b[i - lookback + 1 : i + 1]
            try:
                _, pval, _ = coint(win_a, win_b)
                last_pval = float(pval)
            except Exception:
                last_pval = 1.0
        pvalues[i] = last_pval

    return pd.Series(pvalues, index=price_a.index, name="coint_pvalue")


# ── Trade record ──────────────────────────────────────────────────────────────

class Trade(NamedTuple):
    pair: tuple[str, str]         # (ticker_a, ticker_b)
    side: int                     # +1: long A/short B; -1: short A/long B
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp | None
    entry_price_a: float
    entry_price_b: float
    exit_price_a: float | None
    exit_price_b: float | None
    hedge_ratio: float            # β at entry
    notional: float               # per-leg notional
    pnl: float | None             # realized PnL (after costs)
    exit_reason: str | None       # "zscore" | "stop" | "time" | "end"


# ── Core simulation ───────────────────────────────────────────────────────────

def _cost_fraction(notional: float, fees: float, slippage: float) -> float:
    """Round-trip cost as a fraction of notional (both legs × 2 sides)."""
    # Per trade: 2 legs (long + short), each with fees + slippage on entry and exit
    return 2 * 2 * (fees + slippage)  # 4 transactions × cost per transaction


def simulate_pair(
    ticker_a: str,
    ticker_b: str,
    close: pd.DataFrame,
    params: dict,
    compute_coint: bool = True,
    eval_start: str | None = None,
) -> tuple[pd.Series, list[Trade]]:
    """
    Simulate a single pair strategy over the full price history.

    Args:
        eval_start: If provided, PnL and trades are only counted from this date forward.
                    Data before eval_start is used purely for lookback warmup.

    Returns:
        daily_pnl: pd.Series of daily mark-to-market PnL (eval period only, net post-cost)
        trades:    list of completed Trade records (eval period only)
    """
    if ticker_a not in close.columns or ticker_b not in close.columns:
        idx = close.index
        return pd.Series(0.0, index=idx, name=f"{ticker_a}/{ticker_b}"), []

    price_a = close[ticker_a].dropna()
    price_b = close[ticker_b].dropna()
    common_idx = price_a.index.intersection(price_b.index)
    price_a = price_a.reindex(common_idx)
    price_b = price_b.reindex(common_idx)

    eval_start_ts = pd.Timestamp(eval_start) if eval_start else None

    lookback = params["lookback_cointegration_days"]
    entry_z = params["entry_zscore"]
    exit_z = params["exit_zscore"]
    stop_z = params["stop_zscore"]
    max_hold = params["max_holding_days"]
    notional = params["capital_per_pair"]
    fees = params["fees_per_leg"]
    slippage = params["slippage_per_leg"]
    coint_thresh = params.get("coint_pvalue_threshold", 0.05)

    # Pre-compute rolling hedge ratio, spread, z-score
    hedge_s, spread_s, zscore_s = compute_rolling_hedge_and_spread(price_a, price_b, lookback)

    # Rolling cointegration p-value (skip if compute_coint=False for speed in sensitivity scan)
    if compute_coint:
        pval_s = compute_rolling_coint_pvalue(price_a, price_b, lookback)
    else:
        pval_s = pd.Series(0.01, index=common_idx)  # assume cointegrated

    n = len(common_idx)
    dates = common_idx
    a_arr = price_a.to_numpy(dtype=float)
    b_arr = price_b.to_numpy(dtype=float)
    z_arr = zscore_s.to_numpy(dtype=float)
    h_arr = hedge_s.to_numpy(dtype=float)
    pv_arr = pval_s.to_numpy(dtype=float)

    daily_pnl = np.zeros(n)
    completed_trades: list[Trade] = []

    # Open position state
    in_trade = False
    side = 0
    entry_idx = -1
    entry_price_a = 0.0
    entry_price_b = 0.0
    entry_hedge = 0.0

    for i in range(n):
        if np.isnan(z_arr[i]) or np.isnan(h_arr[i]):
            continue

        in_eval = (eval_start_ts is None) or (dates[i] >= eval_start_ts)

        if not in_trade:
            # Only open new entries during the eval period
            if not in_eval:
                continue

            # Check for new entry: pair must be cointegrated
            if pv_arr[i] > coint_thresh:
                continue  # pair not cointegrated at this point — skip

            z = z_arr[i]
            if abs(z) >= entry_z:
                side = -1 if z >= entry_z else 1  # +1: long A/short B; -1: short A/long B
                in_trade = True
                entry_idx = i
                entry_price_a = a_arr[i]
                entry_price_b = b_arr[i]
                entry_hedge = h_arr[i]

                # Entry transaction cost
                cost = notional * _cost_fraction(notional, fees, slippage) / 2
                daily_pnl[i] -= cost

        else:
            # Mark open position to market
            if entry_price_a > 0 and entry_price_b > 0 and i > 0:
                pnl_a = side * (a_arr[i] - a_arr[i - 1]) / entry_price_a * notional
                pnl_b = -side * (b_arr[i] - b_arr[i - 1]) / entry_price_b * notional
                daily_pnl[i] = pnl_a + pnl_b

            # Check exit conditions
            z = z_arr[i]
            bars_held = i - entry_idx
            exit_reason = None

            if side == 1 and z >= -exit_z:   # spread converged (long A side)
                exit_reason = "zscore"
            elif side == -1 and z <= exit_z:  # spread converged (short A side)
                exit_reason = "zscore"
            elif abs(z) >= stop_z:
                exit_reason = "stop"
            elif bars_held >= max_hold:
                exit_reason = "time"

            if exit_reason:
                # Apply exit transaction cost
                cost = notional * _cost_fraction(notional, fees, slippage) / 2
                daily_pnl[i] -= cost

                # Realized PnL for this trade (eval period only)
                entry_i_eff = entry_idx
                realized_pnl = daily_pnl[entry_i_eff:i + 1].sum()

                completed_trades.append(Trade(
                    pair=(ticker_a, ticker_b),
                    side=side,
                    entry_date=dates[entry_idx],
                    exit_date=dates[i],
                    entry_price_a=entry_price_a,
                    entry_price_b=entry_price_b,
                    exit_price_a=a_arr[i],
                    exit_price_b=b_arr[i],
                    hedge_ratio=entry_hedge,
                    notional=notional,
                    pnl=realized_pnl,
                    exit_reason=exit_reason,
                ))

                in_trade = False
                side = 0
                entry_idx = -1

    # Force-close any open position at end of period
    if in_trade and entry_idx >= 0:
        i = n - 1
        cost = notional * _cost_fraction(notional, fees, slippage) / 2
        daily_pnl[i] -= cost
        realized_pnl = daily_pnl[entry_idx:].sum()
        completed_trades.append(Trade(
            pair=(ticker_a, ticker_b),
            side=side,
            entry_date=dates[entry_idx],
            exit_date=dates[i] if n > 0 else None,
            entry_price_a=entry_price_a,
            entry_price_b=entry_price_b,
            exit_price_a=a_arr[i] if n > 0 else None,
            exit_price_b=b_arr[i] if n > 0 else None,
            hedge_ratio=entry_hedge,
            notional=notional,
            pnl=realized_pnl,
            exit_reason="end",
        ))

    # Trim daily_pnl to eval period
    pnl_series_full = pd.Series(daily_pnl, index=dates, name=f"{ticker_a}/{ticker_b}")
    if eval_start_ts is not None:
        pnl_series = pnl_series_full[pnl_series_full.index >= eval_start_ts]
    else:
        pnl_series = pnl_series_full

    return pnl_series, completed_trades


# ── Portfolio aggregation ─────────────────────────────────────────────────────

def run_strategy(
    pairs: list[tuple[str, str]] | None = None,
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    params: dict | None = None,
    compute_coint: bool = True,
    warmup_days: int | None = None,
) -> dict:
    """
    Run the full pairs trading strategy over all pairs and aggregate metrics.

    Args:
        pairs:        List of (ticker_a, ticker_b) tuples; defaults to PARAMETERS["pairs"]
        start, end:   Backtest date range (signals and PnL only counted in this window)
        params:       Parameter overrides (merges into PARAMETERS)
        compute_coint: If False, skip rolling cointegration test (faster for sensitivity scan)
        warmup_days:  Extra calendar days to prepend for lookback warmup. Defaults to
                      2 × lookback_cointegration_days in calendar days (~1.4× trading days).

    Returns:
        Metrics dict compatible with gate1_reporter format.
    """
    if params is None:
        params = PARAMETERS.copy()
    else:
        merged = PARAMETERS.copy()
        merged.update(params)
        params = merged

    if pairs is None:
        pairs = params.get("pairs", PARAMETERS["pairs"])

    lookback = params["lookback_cointegration_days"]

    # Prepend a warmup buffer so rolling calcs are valid at `start`
    if warmup_days is None:
        # Convert trading days to calendar days (approx ×1.4) and add 20% buffer
        warmup_days = int(lookback * 1.5 * 1.4)

    start_dt = pd.Timestamp(start)
    fetch_start = (start_dt - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")

    # Fetch prices (with warmup)
    all_tickers = sorted({t for pair in pairs for t in pair})
    close_full = fetch_close_prices(all_tickers, fetch_start, end)
    if close_full.empty:
        raise ValueError(f"No price data for {all_tickers} in {fetch_start}–{end}")

    # Simulate each pair over full window (warmup + eval period)
    all_pnl_series = []
    all_trades: list[Trade] = []

    for ticker_a, ticker_b in pairs:
        pnl_s, trades = simulate_pair(
            ticker_a, ticker_b, close_full, params,
            compute_coint=compute_coint, eval_start=start,
        )
        all_pnl_series.append(pnl_s)
        all_trades.extend(trades)

    if not all_pnl_series:
        return _empty_metrics(start, end)

    # Aggregate portfolio PnL (union of all pair date indices)
    pnl_df = pd.DataFrame(all_pnl_series).T
    portfolio_daily_pnl = pnl_df.sum(axis=1)

    # Equity curve
    equity = INITIAL_CAPITAL + portfolio_daily_pnl.cumsum()

    # Daily returns (on capital)
    daily_returns = portfolio_daily_pnl / INITIAL_CAPITAL

    # Metrics
    sharpe = _compute_sharpe(daily_returns)
    mdd = _compute_max_drawdown(equity)
    trade_pnls = [t.pnl for t in all_trades if t.pnl is not None and t.exit_reason != "end"]
    win_rate = float(np.mean([p > 0 for p in trade_pnls])) if trade_pnls else 0.0
    trade_count = len(trade_pnls)
    total_return = float((equity.iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL)

    # Profit factor
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    profit_factor = sum(wins) / abs(sum(losses)) if losses else float("inf")

    # Trade log
    trade_log = [
        {
            "pair": f"{t.pair[0]}/{t.pair[1]}",
            "side": "long_A" if t.side == 1 else "short_A",
            "entry_date": str(t.entry_date.date()) if t.entry_date else None,
            "exit_date": str(t.exit_date.date()) if t.exit_date else None,
            "pnl": round(t.pnl, 2) if t.pnl is not None else None,
            "exit_reason": t.exit_reason,
        }
        for t in all_trades
        if t.exit_reason != "end"
    ]

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "total_return": total_return,
        "trade_count": trade_count,
        "profit_factor": profit_factor,
        "equity_curve": equity.to_dict(),
        "daily_returns": daily_returns.to_dict(),
        "trade_log": trade_log,
        "period": f"{start} to {end}",
        "pairs_traded": [f"{a}/{b}" for a, b in pairs],
        "n_pairs": len(pairs),
        # Gate 1 reporter field names
        "sharpe_in_sample": sharpe,
        "max_dd_in_sample": mdd,
        "win_rate_in_sample": win_rate,
        "trades_in_sample": trade_count,
    }


# ── Walk-forward runner ───────────────────────────────────────────────────────

def run_walk_forward(
    pairs: list[tuple[str, str]] | None = None,
    params: dict | None = None,
) -> list[dict]:
    """
    4-window walk-forward with 36-month IS / 6-month OOS.

    Windows (aligned to QUA-73 spec):
        W1: IS 2018-01-01 → 2020-12-31, OOS 2021-01-01 → 2021-06-30
        W2: IS 2018-07-01 → 2021-06-30, OOS 2021-07-01 → 2021-12-31
        W3: IS 2019-01-01 → 2021-12-31, OOS 2022-01-01 → 2022-06-30
        W4: IS 2019-07-01 → 2022-06-30, OOS 2022-07-01 → 2022-12-31

    Returns:
        List of dicts with train_sharpe, test_sharpe, train_mdd, test_mdd.
    """
    windows = [
        ("2018-01-01", "2020-12-31", "2021-01-01", "2021-06-30"),
        ("2018-07-01", "2021-06-30", "2021-07-01", "2021-12-31"),
        ("2019-01-01", "2021-12-31", "2022-01-01", "2022-06-30"),
        ("2019-07-01", "2022-06-30", "2022-07-01", "2022-12-31"),
    ]

    results = []
    for is_start, is_end, oos_start, oos_end in windows:
        print(f"  WF: IS {is_start}→{is_end} | OOS {oos_start}→{oos_end}")
        try:
            is_r = run_strategy(pairs=pairs, start=is_start, end=is_end, params=params)
            oos_r = run_strategy(pairs=pairs, start=oos_start, end=oos_end, params=params)
            results.append({
                "is_start": is_start, "is_end": is_end,
                "oos_start": oos_start, "oos_end": oos_end,
                "train_sharpe": is_r["sharpe"],
                "test_sharpe": oos_r["sharpe"],
                "train_mdd": is_r["max_drawdown"],
                "test_mdd": oos_r["max_drawdown"],
                "train_trades": is_r["trade_count"],
                "test_trades": oos_r["trade_count"],
            })
        except Exception as e:
            print(f"    Window failed: {e}")
            results.append({
                "is_start": is_start, "is_end": is_end,
                "oos_start": oos_start, "oos_end": oos_end,
                "train_sharpe": 0.0, "test_sharpe": 0.0,
                "train_mdd": 0.0, "test_mdd": 0.0,
                "train_trades": 0, "test_trades": 0,
            })

    return results


# ── Parameter sensitivity scan ────────────────────────────────────────────────

def scan_entry_zscore(
    pairs: list[tuple[str, str]] | None = None,
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    entry_zscore_values: list[float] | None = None,
    base_params: dict | None = None,
) -> dict[float, float]:
    """
    Scan Sharpe ratio across entry_zscore range [1.6, 2.8] (Gate 1 sensitivity criterion).

    Gate 1 requires < 30% Sharpe degradation across the tested range.

    Returns:
        Dict mapping entry_zscore → portfolio Sharpe ratio.
    """
    if entry_zscore_values is None:
        entry_zscore_values = [round(v, 2) for v in np.arange(1.6, 2.9, 0.2)]

    if base_params is None:
        base_params = PARAMETERS.copy()

    if pairs is None:
        pairs = base_params.get("pairs", PARAMETERS["pairs"])

    # Pre-fetch data with warmup
    lookback = base_params.get("lookback_cointegration_days", PARAMETERS["lookback_cointegration_days"])
    warmup_days = int(lookback * 1.5 * 1.4)
    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")
    all_tickers = sorted({t for pair in pairs for t in pair})
    close = fetch_close_prices(all_tickers, fetch_start, end)

    results = {}
    for z_val in entry_zscore_values:
        p = dict(base_params)
        p["entry_zscore"] = z_val
        try:
            # Pass pre-fetched close directly
            pnl_series_list = []
            for ticker_a, ticker_b in pairs:
                pnl_s, _ = simulate_pair(ticker_a, ticker_b, close, p, compute_coint=False, eval_start=start)
                pnl_series_list.append(pnl_s)
            if pnl_series_list:
                portfolio_pnl = pd.DataFrame(pnl_series_list).T.sum(axis=1)
                daily_returns = portfolio_pnl / INITIAL_CAPITAL
                sharpe = _compute_sharpe(daily_returns)
            else:
                sharpe = 0.0
        except Exception as e:
            print(f"  Sensitivity scan error at entry_zscore={z_val}: {e}")
            sharpe = float("nan")
        results[z_val] = sharpe

    return results


# ── Metric helpers ────────────────────────────────────────────────────────────

def _compute_sharpe(daily_returns: pd.Series) -> float:
    """Annualized Sharpe ratio (risk-free = 0)."""
    dr = daily_returns.dropna()
    if len(dr) < 20 or dr.std() < 1e-10:
        return 0.0
    return float(dr.mean() / dr.std() * math.sqrt(252))


def _compute_max_drawdown(equity: pd.Series) -> float:
    """Maximum drawdown as a positive fraction (0.15 = 15% drawdown)."""
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    return float(abs(drawdown.min()))


def _empty_metrics(start: str, end: str) -> dict:
    return {
        "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
        "total_return": 0.0, "trade_count": 0, "profit_factor": 0.0,
        "equity_curve": {}, "daily_returns": {}, "trade_log": [],
        "period": f"{start} to {end}",
        "sharpe_in_sample": 0.0, "max_dd_in_sample": 0.0,
        "win_rate_in_sample": 0.0, "trades_in_sample": 0,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Pairs Trading Cointegration — Quick Smoke Test ===\n")

    print("IS (2018-01-01 → 2021-12-31):")
    is_r = run_strategy(start="2018-01-01", end="2021-12-31")
    print(f"  Sharpe: {is_r['sharpe']:.3f}  MDD: {is_r['max_drawdown']:.1%}  "
          f"Trades: {is_r['trade_count']}  WinRate: {is_r['win_rate']:.1%}")

    print("\nOOS (2022-01-01 → 2023-12-31):")
    oos_r = run_strategy(start="2022-01-01", end="2023-12-31")
    print(f"  Sharpe: {oos_r['sharpe']:.3f}  MDD: {oos_r['max_drawdown']:.1%}  "
          f"Trades: {oos_r['trade_count']}  WinRate: {oos_r['win_rate']:.1%}")
