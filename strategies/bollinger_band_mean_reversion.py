"""
Strategy: Bollinger Band Mean Reversion
Author: Engineering Director (Quant Zero)
Date: 2026-03-16
Hypothesis: Prices that deviate beyond N standard deviations from a rolling mean
            tend to revert toward it; buying below the lower Bollinger Band and
            exiting at the midline captures this edge on liquid ETFs.
Asset class: equities (ETFs, long-only)
Parent task: QUA-53
"""

import vectorbt as vbt
import pandas as pd
import numpy as np
import yfinance as yf

# ── All tunable parameters exposed here for sensitivity scanning ──────────────
PARAMETERS = {
    "lookback_period": 20,       # Bollinger Band rolling window (trading days)
    "entry_std": 2.0,            # Std deviations below mean to trigger long entry
    "exit_std": 0.0,             # Std deviations from mean to exit (0.0 = midline)
    "max_holding_days": 10,      # Time stop: exit after N days if midline not reached
    "stop_loss_std": 3.0,        # Hard stop: exit if price crosses this many std BELOW mean
    "vix_threshold": 30.0,       # Suspend all new longs when VIX closes above this level
    "universe": ["SPY", "QQQ", "XLV", "XLF", "XLE", "IWM"],
}


# ── Signal Generation ─────────────────────────────────────────────────────────

def compute_bollinger_bands(
    close: pd.Series, lookback: int, entry_std: float, exit_std: float, stop_loss_std: float
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Compute rolling mean, entry band, exit band, and stop-loss band.

    Returns:
        mid:        Rolling SMA (midline / exit target)
        lower:      Lower entry band (mean - entry_std * std)
        exit_band:  Exit target band (mean - exit_std * std; typically = mid when exit_std=0)
        stop_band:  Stop-loss band (mean - stop_loss_std * std)
    """
    mid = close.rolling(lookback).mean()
    std = close.rolling(lookback).std()
    lower = mid - entry_std * std
    exit_band = mid - exit_std * std       # 0.0 → exit at midline
    stop_band = mid - stop_loss_std * std  # Stop-loss below mean
    return mid, lower, exit_band, stop_band


def generate_signals(
    close: pd.DataFrame,
    vix_mask: pd.Series,
    params: dict = PARAMETERS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generate entry and exit signals for a multi-ticker DataFrame.

    Args:
        close:    DataFrame of closing prices, columns = tickers
        vix_mask: Boolean Series indexed by date; True means VIX > threshold (no new longs)
        params:   Strategy parameters dict

    Returns:
        entries: Boolean DataFrame, True on long entry bar
        exits:   Boolean DataFrame, True on exit bar
    """
    lookback = params["lookback_period"]
    entry_std = params["entry_std"]
    exit_std = params["exit_std"]
    stop_loss_std = params["stop_loss_std"]
    max_holding = params["max_holding_days"]

    entries_list = {}
    exits_list = {}

    for ticker in close.columns:
        price = close[ticker].dropna()

        mid, lower, exit_band, stop_band = compute_bollinger_bands(
            price, lookback, entry_std, exit_std, stop_loss_std
        )

        # Entry: close crosses below lower band (previous bar above, current bar below/at)
        raw_entry = (price.shift(1) >= lower.shift(1)) & (price <= lower)

        # Suppress entries when VIX regime filter is active
        vix_aligned = vix_mask.reindex(price.index, fill_value=False)
        raw_entry = raw_entry & ~vix_aligned

        # Exit conditions (any of the three):
        # 1. Price returns to exit band (midline by default)
        exit_midline = price >= exit_band

        # 2. Hard stop-loss: price drops to stop_loss_std below mean
        exit_stop = price <= stop_band

        # 3. Time stop: hold for max_holding_days, then exit (handled via accumulate logic below)
        #    We implement the time stop by generating an exit max_holding bars after each entry.
        raw_exit = exit_midline | exit_stop

        # Apply time stop: ensure we exit within max_holding_days of any entry
        # Build expanded exit mask that fires max_holding bars after any entry signal
        entry_arr = raw_entry.to_numpy(dtype=bool)
        exit_arr = raw_exit.to_numpy(dtype=bool)
        n = len(entry_arr)
        time_stop_arr = np.zeros(n, dtype=bool)

        in_trade = False
        entry_bar = -1
        for i in range(n):
            if not in_trade and entry_arr[i]:
                in_trade = True
                entry_bar = i
            if in_trade:
                bars_held = i - entry_bar
                if exit_arr[i] or bars_held >= max_holding:
                    time_stop_arr[i] = True
                    in_trade = False
                    entry_bar = -1

        final_exit = pd.Series(
            exit_arr | time_stop_arr, index=price.index, name=ticker
        )
        final_entry = pd.Series(entry_arr, index=price.index, name=ticker)

        entries_list[ticker] = final_entry
        exits_list[ticker] = final_exit

    entries = pd.DataFrame(entries_list)
    exits = pd.DataFrame(exits_list)
    return entries, exits


# ── VIX Loader ────────────────────────────────────────────────────────────────

def load_vix_mask(start: str, end: str, threshold: float) -> pd.Series:
    """
    Download VIX daily close and return a boolean mask where VIX > threshold.

    Returns:
        pd.Series (DatetimeIndex), True on dates where VIX exceeds the threshold.
    """
    vix = yf.download("^VIX", start=start, end=end, progress=False)
    if vix.empty:
        return pd.Series(dtype=bool)
    vix_close = vix["Close"].squeeze()
    return vix_close > threshold


# ── PDT Compliance Helper ─────────────────────────────────────────────────────

def count_weekly_round_trips(entries: pd.DataFrame, exits: pd.DataFrame) -> pd.DataFrame:
    """
    Count completed round-trip trades (entry + exit pair) per week per ticker.

    Args:
        entries: Boolean DataFrame of entry signals
        exits:   Boolean DataFrame of exit signals

    Returns:
        DataFrame indexed by ISO week start date, columns = tickers, values = round-trip count.
    """
    weekly_trips = {}
    for ticker in entries.columns:
        e = entries[ticker]
        x = exits[ticker]

        # Walk through signals to pair entries with their exits
        in_trade = False
        trips = {}
        entry_week = None
        for date in e.index:
            if not in_trade and e.get(date, False):
                in_trade = True
                entry_week = date
            elif in_trade and x.get(date, False):
                # Count the round-trip in the week the TRADE CLOSED
                week_start = date - pd.offsets.Week(weekday=0)
                trips[week_start] = trips.get(week_start, 0) + 1
                in_trade = False

        weekly_trips[ticker] = pd.Series(trips)

    result = pd.DataFrame(weekly_trips).fillna(0).astype(int)
    result.index.name = "week_start"
    return result


# ── Parameter Sensitivity Scan ────────────────────────────────────────────────

def scan_entry_std(
    universe: list[str],
    start: str,
    end: str,
    entry_std_values: list[float] | None = None,
    base_params: dict = PARAMETERS,
) -> dict[float, float]:
    """
    Scan Sharpe ratio across a range of entry_std values (Gate 1 sensitivity criterion).

    Gate 1 requires < 30% Sharpe degradation for entry_std in [1.6, 2.4].

    Args:
        universe:         List of ticker symbols
        start, end:       Date range strings
        entry_std_values: List of entry_std values to test (default: [1.6..2.4] step 0.1)
        base_params:      Base parameter dict (entry_std will be overridden)

    Returns:
        Dict mapping entry_std → portfolio Sharpe ratio
    """
    if entry_std_values is None:
        entry_std_values = [round(v, 2) for v in np.arange(1.6, 2.5, 0.1)]

    results = {}
    close = yf.download(universe, start=start, end=end, progress=False)["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame()

    vix_mask = load_vix_mask(start, end, base_params["vix_threshold"])

    for std_val in entry_std_values:
        params = dict(base_params)
        params["entry_std"] = std_val
        entries, exits = generate_signals(close, vix_mask, params)

        if entries.empty or entries.sum().sum() == 0:
            results[std_val] = float("nan")
            continue

        pf = vbt.Portfolio.from_signals(
            close,
            entries=entries,
            exits=exits,
            fees=0.0001,     # ~0.01% fees (ETF, low brokerage)
            slippage=0.0005, # 0.05% slippage
        )
        results[std_val] = float(pf.sharpe_ratio())

    return results


# ── Main Strategy Runner ──────────────────────────────────────────────────────

def run_strategy(
    universe: list[str] | None = None,
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    params: dict = PARAMETERS,
) -> dict:
    """
    Download data, run the Bollinger Band Mean Reversion strategy, and return metrics.

    Args:
        universe: List of ticker symbols (defaults to PARAMETERS["universe"])
        start:    Start date for the backtest period
        end:      End date for the backtest period
        params:   Strategy parameter overrides

    Returns:
        Metrics dict compatible with the orchestrator's Gate 1 reporter.
    """
    if universe is None:
        universe = params.get("universe", PARAMETERS["universe"])

    # Download price data
    close = yf.download(universe, start=start, end=end, progress=False)["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame()

    # Drop any all-NaN columns (tickers with no data in range)
    close = close.dropna(axis=1, how="all")
    if close.empty:
        raise ValueError(f"No price data returned for {universe} in {start}–{end}")

    # Build VIX regime mask
    vix_mask = load_vix_mask(start, end, params["vix_threshold"])

    # Generate signals
    entries, exits = generate_signals(close, vix_mask, params)

    if entries.sum().sum() == 0:
        return {
            "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
            "total_return": 0.0, "trade_count": 0,
            "pdt_weekly_round_trips": {},
        }

    # Build portfolio (equal-weight, long-only)
    pf = vbt.Portfolio.from_signals(
        close,
        entries=entries,
        exits=exits,
        fees=0.0001,     # ~0.01% fees
        slippage=0.0005, # 0.05% slippage
        init_cash=25000, # $25K starting capital
    )

    # Aggregate portfolio-level metrics
    sharpe = float(pf.sharpe_ratio())
    mdd = float(pf.max_drawdown())
    total_return = float(pf.total_return())
    trade_count = int(pf.trades.count())

    # Win rate: pct of trades with positive PnL
    trades_pnl = pf.trades.pnl.to_pandas() if hasattr(pf.trades.pnl, "to_pandas") else pf.trades.pnl
    if hasattr(trades_pnl, "values"):
        pnl_arr = trades_pnl.values.flatten()
    else:
        pnl_arr = np.array(trades_pnl)
    win_rate = float(np.mean(pnl_arr > 0)) if len(pnl_arr) > 0 else 0.0

    # PDT compliance: weekly round-trip counts
    pdt_df = count_weekly_round_trips(entries, exits)
    pdt_max_weekly = int(pdt_df.sum(axis=1).max()) if not pdt_df.empty else 0

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "total_return": total_return,
        "trade_count": trade_count,
        "pdt_max_weekly_round_trips": pdt_max_weekly,
        "pdt_weekly_summary": pdt_df.sum(axis=1).to_dict(),
        "tickers_traded": list(close.columns),
        "period": f"{start} to {end}",
    }


# ── Quick smoke test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running IS backtest (2018–2021)...")
    is_result = run_strategy(start="2018-01-01", end="2021-12-31")
    print("IS:", is_result)

    print("\nRunning OOS backtest (2022–2023)...")
    oos_result = run_strategy(start="2022-01-01", end="2023-12-31")
    print("OOS:", oos_result)

    print("\nRunning entry_std sensitivity scan...")
    sensitivity = scan_entry_std(
        universe=PARAMETERS["universe"],
        start="2018-01-01",
        end="2021-12-31",
    )
    print("Sensitivity (entry_std → Sharpe):", sensitivity)
