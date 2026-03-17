"""
Strategy: H41 Turn of Quarter Window Dressing Effect
Author: Strategy Coder Agent
Date: 2026-03-17
Hypothesis: Institutional portfolio managers systematically buy large-cap equities in the
            final 3 trading days of each calendar quarter to window-dress their disclosed
            holdings, creating a systematic positive return anomaly in SPY over the 5
            trading days spanning quarter-end (Lakonishok, Shleifer, Thaler & Vishny 1991).
Asset class: equities (US, SPY ETF)
Parent task: QUA-323
References: Lakonishok et al. (1991) AER; Ng & Wang (2004) JFE;
            research/hypotheses/41_qc_turn_of_quarter_window_dressing.md
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ── Logging ──────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Parameters ───────────────────────────────────────────────────────────────────
# All tunable parameters exposed here for sensitivity scanning.
PARAMETERS = {
    # Quarter-end window definition
    "entry_days_before_quarter_end": 3,   # variants: 2, 4
    "hold_into_new_quarter_days": 2,      # variants: 1, 3
    # Filters (CORE — both required; see hypothesis PF-4)
    "trend_filter_ma": 200,               # SMA lookback days; variants: 150, 100
    "vix_circuit_breaker": 35,            # skip window if VIX > threshold on entry day; variants: 30, 40
    # Transaction cost model (Engineering Director standard — do not modify)
    "fixed_cost_per_share": 0.005,        # $0.005/share fixed
    "slippage_pct": 0.0005,               # 0.05% slippage
    "market_impact_k": 0.1,              # square-root impact coefficient (Johnson 2010)
    "sigma_window": 20,                   # rolling vol window for market impact
    "adv_window": 20,                     # rolling ADV window
    "order_qty": 100,                     # default order size in shares
    "liquidity_threshold": 0.01,          # flag Q/ADV > 1% as liquidity-constrained
    # Portfolio
    "init_cash": 25000.0,
}

# Quarter-end month → new quarter start month
_QUARTER_END_MONTHS = {3: 4, 6: 7, 9: 10, 12: 1}

# Data quality report (updated at runtime)
DATA_QUALITY: dict = {
    "survivorship_bias": "not_applicable",
    "price_adjustments": "auto_adjust=True for SPY via yfinance",
    "data_gaps": "pending",
    "earnings_exclusion": "not_applicable",
    "vix_availability_start": "pending",
}


# ── Helper: single-ticker download ───────────────────────────────────────────────

def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw.empty:
        raise ValueError(f"No data returned for {ticker} [{start} → {end}]")
    return raw


# ── Data loading ──────────────────────────────────────────────────────────────────

def load_spy_data(start: str = "1993-01-01", end: str = "2026-03-01") -> tuple[pd.Series, pd.Series]:
    """
    Download SPY adjusted closing prices and volume.

    SPY inception: 1993-01-29. Dates before inception are silently clipped by yfinance.
    Uses auto_adjust=True for split/dividend adjustment.

    Returns:
        close (pd.Series): adjusted closing prices indexed by date
        volume (pd.Series): daily volume in shares
    """
    logger.info("Downloading SPY from %s to %s", start, end)
    raw = _download("SPY", start=start, end=end)
    close = raw["Close"]
    volume = raw["Volume"] if "Volume" in raw.columns else pd.Series(np.nan, index=raw.index)

    _check_data_gaps(close, label="SPY")
    logger.info("SPY data: %d trading days [%s → %s]", len(close), close.index[0].date(), close.index[-1].date())
    return close, volume


def load_vix_data(start: str = "1993-01-01", end: str = "2026-03-01") -> pd.Series:
    """
    Download ^VIX closing prices. ^VIX is available from approximately 2004-01-02.

    Pre-2004 callers receive NaN for missing dates; callers must handle gracefully
    by skipping the VIX circuit-breaker on days without data.

    Returns:
        pd.Series: VIX closing prices; empty Series if no data in requested range.
    """
    try:
        logger.info("Downloading ^VIX from %s to %s", start, end)
        raw = _download("^VIX", start=start, end=end)
        vix = raw["Close"]
        DATA_QUALITY["vix_availability_start"] = str(vix.index[0].date())
        logger.info("^VIX data: %d days [%s → %s]", len(vix), vix.index[0].date(), vix.index[-1].date())
        return vix
    except ValueError:
        logger.warning("^VIX data unavailable for range [%s → %s]; VIX filter will be skipped", start, end)
        DATA_QUALITY["vix_availability_start"] = "unavailable"
        return pd.Series(dtype=float)


def _check_data_gaps(prices: pd.Series, label: str) -> None:
    """
    Detect consecutive missing weekday gaps > 5 days (holiday/exchange-closure anomalies).
    Weekend/holiday gaps of 1–2 days are expected and ignored.
    Updates DATA_QUALITY dict in-place.
    """
    all_dates = pd.date_range(prices.index.min(), prices.index.max(), freq="B")
    missing = all_dates.difference(prices.index)
    if len(missing) == 0:
        DATA_QUALITY["data_gaps"] = "no_gaps_detected"
        return

    missing_series = pd.Series(missing)
    runs: list[int] = []
    run = 1
    for i in range(1, len(missing_series)):
        if (missing_series.iloc[i] - missing_series.iloc[i - 1]).days == 1:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)

    max_run = max(runs) if runs else 0
    if max_run > 5:
        logger.warning("DATA_QUALITY: %s has consecutive missing weekday run of %d days", label, max_run)
        DATA_QUALITY["data_gaps"] = f"flagged: max_consecutive_missing={max_run}"
    else:
        DATA_QUALITY["data_gaps"] = f"ok: max_consecutive_missing={max_run} (≤5)"


# ── Quarter window identification ─────────────────────────────────────────────────

def _find_quarter_windows(prices: pd.Series, params: dict) -> list[dict]:
    """
    Enumerate entry/exit dates for every quarter-end window in the price series.

    Entry: Nth-to-last trading day of the quarter-end month
           (N = params["entry_days_before_quarter_end"]; default 3).
    Exit:  Mth trading day of the new quarter start month
           (M = params["hold_into_new_quarter_days"]; default 2).

    Quarter-end months → new quarter start months:
        March(3)→April(4), June(6)→July(7), Sep(9)→Oct(10), Dec(12)→Jan(1) of next year.

    Returns:
        Sorted list of dicts: {entry_date, exit_date, quarter_label}
    """
    n_entry = params["entry_days_before_quarter_end"]
    m_exit = params["hold_into_new_quarter_days"]

    windows = []
    years = sorted(prices.index.year.unique())

    for year in years:
        for q_end_month, q_start_month in _QUARTER_END_MONTHS.items():
            # All trading days in the quarter-end month
            month_mask = (prices.index.year == year) & (prices.index.month == q_end_month)
            month_days = prices.index[month_mask]
            if len(month_days) < n_entry:
                logger.debug(
                    "Skipping %d-%02d: only %d trading days (need %d)",
                    year, q_end_month, len(month_days), n_entry,
                )
                continue

            # Nth-to-last trading day of the quarter-end month
            entry_date = month_days[-n_entry]

            # December quarter-end exits into January of the next year
            q_start_year = year + 1 if q_start_month == 1 else year
            start_mask = (prices.index.year == q_start_year) & (prices.index.month == q_start_month)
            start_days = prices.index[start_mask]
            if len(start_days) < m_exit:
                logger.debug(
                    "Skipping %d-Q%d: only %d days in new quarter start month (need %d)",
                    year, {3: 1, 6: 2, 9: 3, 12: 4}[q_end_month], len(start_days), m_exit,
                )
                continue

            # Mth trading day of the new quarter start month (0-indexed: index m_exit-1)
            exit_date = start_days[m_exit - 1]

            quarter_num = {3: 1, 6: 2, 9: 3, 12: 4}[q_end_month]
            windows.append({
                "entry_date": entry_date,
                "exit_date": exit_date,
                "quarter_label": f"{year}-Q{quarter_num}",
            })
            logger.debug("Window %d-Q%d: entry=%s exit=%s", year, quarter_num, entry_date.date(), exit_date.date())

    windows.sort(key=lambda w: w["entry_date"])
    return windows


# ── Signal generation ─────────────────────────────────────────────────────────────

def generate_signals(
    prices: pd.Series,
    vix: pd.Series,
    params: dict = PARAMETERS,
) -> pd.DataFrame:
    """
    Generate daily position signals for the Turn of Quarter window dressing strategy.

    For each quarter-end window:
      1. Trend filter (CORE): skip if SPY < trend_filter_ma-day SMA on entry day.
         If SMA not yet warmed up (early dates), allow the trade.
      2. VIX circuit-breaker: skip if VIX > vix_circuit_breaker on entry day.
         If VIX data unavailable (pre-2004), skip this filter — do not block the trade.
      3. If both filters pass: position=1 from entry_date through exit_date (inclusive).
      4. All other days: position=0 (CASH).

    Signal convention: position[entry_date]=1 with shift(1) in equity curve means
    we earn the entry_date+1 return onward; entry/exit costs are deducted separately.

    Returns:
        pd.DataFrame with columns:
            position (int 0/1): long SPY vs cash
            trend_filter_active (bool): trend filter checked and passed on entry day
            vix_filter_active (bool): VIX filter checked and passed on entry day
            window_skipped_trend (bool): window blocked by trend filter
            window_skipped_vix (bool): window blocked by VIX circuit-breaker
    """
    ma_window = params["trend_filter_ma"]
    vix_threshold = params["vix_circuit_breaker"]

    # Precompute rolling SMA (NaN during warm-up period — allow trade if SMA not ready)
    sma = prices.rolling(ma_window).mean() if ma_window > 0 else pd.Series(np.nan, index=prices.index)

    # Align VIX to price index; NaN for dates with no VIX data (pre-2004 or missing)
    vix_aligned = vix.reindex(prices.index) if not vix.empty else pd.Series(np.nan, index=prices.index)

    signals = pd.DataFrame({
        "position": np.zeros(len(prices), dtype=int),
        "trend_filter_active": False,
        "vix_filter_active": False,
        "window_skipped_trend": False,
        "window_skipped_vix": False,
    }, index=prices.index)

    windows = _find_quarter_windows(prices, params)
    logger.info("Found %d quarter-end windows to evaluate", len(windows))

    skips_trend = 0
    skips_vix = 0
    trades_executed = 0

    for w in windows:
        entry_date = w["entry_date"]
        exit_date = w["exit_date"]
        label = w["quarter_label"]

        if entry_date not in prices.index:
            logger.warning("Entry date %s not in prices index — skipping %s", entry_date.date(), label)
            continue

        entry_price = float(prices.loc[entry_date])

        # ── Trend filter: SPY must be above N-day SMA on entry day ───────────────
        sma_value = float(sma.loc[entry_date])
        if ma_window > 0 and not np.isnan(sma_value):
            if entry_price <= sma_value:
                signals.loc[entry_date, "window_skipped_trend"] = True
                skips_trend += 1
                logger.info(
                    "TREND FILTER blocks %s: SPY(%.2f) ≤ SMA%d(%.2f)",
                    label, entry_price, ma_window, sma_value,
                )
                continue
            signals.loc[entry_date, "trend_filter_active"] = True
        # If SMA not warmed up (NaN), allow the trade without marking trend_filter_active

        # ── VIX circuit-breaker: skip if VIX > threshold on entry day ────────────
        vix_value = float(vix_aligned.loc[entry_date]) if entry_date in vix_aligned.index else np.nan
        if not np.isnan(vix_value):
            if vix_value > vix_threshold:
                signals.loc[entry_date, "window_skipped_vix"] = True
                skips_vix += 1
                logger.info(
                    "VIX CIRCUIT BREAKER blocks %s: VIX(%.1f) > %.1f on %s",
                    label, vix_value, vix_threshold, entry_date.date(),
                )
                continue
            signals.loc[entry_date, "vix_filter_active"] = True
        else:
            # Pre-2004 or VIX data missing: skip VIX filter, proceed with trade
            logger.debug("VIX unavailable on %s — VIX filter skipped for %s", entry_date.date(), label)

        # ── Both filters passed: activate position for this window ────────────────
        window_mask = (prices.index >= entry_date) & (prices.index <= exit_date)
        signals.loc[window_mask, "position"] = 1
        trades_executed += 1
        logger.info("WINDOW ACTIVE %s: in=[%s → %s]", label, entry_date.date(), exit_date.date())

    logger.info(
        "Signal summary: %d windows executed, %d skipped (trend), %d skipped (VIX)",
        trades_executed, skips_trend, skips_vix,
    )
    return signals


# ── Transaction costs ─────────────────────────────────────────────────────────────

def apply_transaction_costs(
    prices: pd.Series,
    signals: pd.DataFrame,
    params: dict,
    volume: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Build trade log with per-trade net returns after transaction costs.

    Cost model per trade leg:
        cost = fixed_cost_per_share + slippage_pct × price + market_impact
        market_impact = k × σ × sqrt(Q / ADV)   [square-root impact model]

    Flags trades as liquidity_constrained when Q / ADV > liquidity_threshold (default 1%).

    Returns:
        pd.DataFrame with one row per completed round-trip trade:
            entry_date, exit_date, entry_price, exit_price, return_pct, pnl,
            liquidity_constrained, entry_cost, exit_cost,
            trend_filter_active, vix_filter_active
    """
    pos = signals["position"].astype(int)

    returns = prices.pct_change()
    sigma = returns.rolling(params["sigma_window"]).std()

    adv = volume.rolling(params["adv_window"]).mean() if volume is not None else pd.Series(np.nan, index=prices.index)

    pos_diff = pos.diff().fillna(pos.astype(float))

    trade_log = []
    entry_date = None
    entry_price = np.nan
    entry_cost = 0.0
    entry_lc = False

    for date in prices.index:
        p = float(prices.loc[date])
        chg = float(pos_diff.loc[date])

        if chg == 1:  # position opens: 0 → 1
            entry_date = date
            entry_price = p
            s = float(sigma.loc[date]) if not np.isnan(sigma.loc[date]) else 0.0
            a = float(adv.loc[date]) if not np.isnan(adv.loc[date]) else 0.0
            Q = params["order_qty"]
            mi = params["market_impact_k"] * s * np.sqrt(Q / a) if a > 0 else 0.0
            entry_lc = (Q / a > params["liquidity_threshold"]) if a > 0 else False
            entry_cost = params["fixed_cost_per_share"] + params["slippage_pct"] * p + mi
            if entry_lc:
                logger.warning("LIQUIDITY_CONSTRAINED ENTRY %s: Q/ADV=%.4f", date.date(), Q / a)

        elif chg == -1 and entry_date is not None:  # position closes: 1 → 0
            exit_price = p
            s = float(sigma.loc[date]) if not np.isnan(sigma.loc[date]) else 0.0
            a = float(adv.loc[date]) if not np.isnan(adv.loc[date]) else 0.0
            Q = params["order_qty"]
            mi = params["market_impact_k"] * s * np.sqrt(Q / a) if a > 0 else 0.0
            exit_lc = (Q / a > params["liquidity_threshold"]) if a > 0 else False
            exit_cost = params["fixed_cost_per_share"] + params["slippage_pct"] * exit_price + mi

            gross_ret = (exit_price - entry_price) / entry_price
            # Cost drag as fraction of entry price (both legs combined)
            total_cost_pct = (entry_cost + exit_cost) / entry_price
            net_ret = gross_ret - total_cost_pct
            pnl = net_ret * params["init_cash"]

            trend_active = bool(signals.loc[entry_date, "trend_filter_active"])
            vix_active = bool(signals.loc[entry_date, "vix_filter_active"])

            trade_log.append({
                "entry_date": entry_date,
                "exit_date": date,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": net_ret,
                "pnl": pnl,
                "trend_filter_active": trend_active,
                "vix_filter_active": vix_active,
                "liquidity_constrained": entry_lc or exit_lc,
                "entry_cost": entry_cost,
                "exit_cost": exit_cost,
            })
            entry_date = None
            entry_price = np.nan

    df = pd.DataFrame(trade_log)
    if not df.empty:
        lc_count = int(df["liquidity_constrained"].sum())
        if lc_count > 0:
            logger.warning("Liquidity-constrained trades: %d (Q/ADV > %.2f)", lc_count, params["liquidity_threshold"])
    return df


# ── Equity curve ──────────────────────────────────────────────────────────────────

def _build_equity_curve(
    prices: pd.Series,
    signals: pd.DataFrame,
    trade_log: pd.DataFrame,
    params: dict,
) -> tuple[pd.Series, pd.Series]:
    """
    Build daily equity curve and net returns from signals and trade costs.

    Method:
    - Apply yesterday's position to today's price return (shift=1 prevents look-ahead).
      Buying at close of entry_date means earnings begin entry_date+1 onward.
    - Deduct per-leg costs on the exact entry/exit dates from the trade log.
    - Cash earns 0% (conservative; real implementation would use T-bills).

    Returns:
        equity_curve (pd.Series): daily portfolio dollar value starting at init_cash
        daily_returns (pd.Series): daily net portfolio returns
    """
    pos = signals["position"].astype(float)
    price_returns = prices.pct_change().fillna(0.0)

    # Entry at close → position applied the next day via shift(1)
    strat_returns = pos.shift(1).fillna(0.0) * price_returns

    # Deduct transaction costs on exact trade dates as fraction of price
    cost_series = pd.Series(0.0, index=prices.index)
    for _, row in trade_log.iterrows():
        if row["entry_date"] in cost_series.index:
            cost_series.loc[row["entry_date"]] -= row["entry_cost"] / row["entry_price"]
        if row["exit_date"] in cost_series.index:
            cost_series.loc[row["exit_date"]] -= row["exit_cost"] / row["exit_price"]

    net_returns = strat_returns + cost_series
    equity_curve = params["init_cash"] * (1 + net_returns).cumprod()
    return equity_curve, net_returns


# ── Metrics ───────────────────────────────────────────────────────────────────────

def _compute_metrics(equity_curve: pd.Series, daily_returns: pd.Series, trade_log: pd.DataFrame) -> dict:
    """Compute standard Gate 1 performance metrics from equity curve and trade log."""
    trading_days = 252

    annualized_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (
        trading_days / max(len(equity_curve), 1)
    ) - 1

    vol = daily_returns.std() * np.sqrt(trading_days)
    sharpe = annualized_return / vol if vol > 0 else 0.0

    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min())

    if trade_log.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": float(sharpe),
            "annualized_return": float(annualized_return),
            "liquidity_constrained_trades": 0,
        }

    winners = trade_log[trade_log["return_pct"] > 0]
    losers = trade_log[trade_log["return_pct"] <= 0]
    win_rate = len(winners) / len(trade_log)

    gross_profit = float(winners["pnl"].sum()) if not winners.empty else 0.0
    gross_loss = float(abs(losers["pnl"].sum())) if not losers.empty else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf

    lc_count = int(trade_log["liquidity_constrained"].sum()) if "liquidity_constrained" in trade_log.columns else 0

    return {
        "total_trades": len(trade_log),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "max_drawdown": max_drawdown,
        "sharpe_ratio": float(sharpe),
        "annualized_return": float(annualized_return),
        "liquidity_constrained_trades": lc_count,
    }


# ── Main backtest entry point ─────────────────────────────────────────────────────

def run_backtest(
    params: dict = PARAMETERS,
    start: str = "1993-01-01",
    end: str = "2025-12-31",
) -> dict:
    """
    Full backtest pipeline: load data → signals → transaction costs → equity curve → metrics.

    Required output function for Gate 1 backtesting.

    Args:
        params: strategy parameters dict (defaults to PARAMETERS)
        start:  data start date string (YYYY-MM-DD)
        end:    data end date string (YYYY-MM-DD)

    Returns:
        dict with keys:
            trade_log (list[dict]): per-trade records with entry_date, exit_date,
                entry_price, exit_price, pnl, trend_filter_active, vix_filter_active,
                liquidity_constrained, return_pct, entry_cost, exit_cost
            equity_curve (pd.Series): daily portfolio value
            metrics (dict): Gate 1 performance metrics
            params (dict): parameters used for this run
            data_quality (dict): gaps, vix_availability_start, adjustments info
    """
    prices, volume = load_spy_data(start=start, end=end)
    vix = load_vix_data(start=start, end=end)

    logger.info("Generating signals [%s → %s]", start, end)
    signals = generate_signals(prices, vix, params)

    logger.info("Computing transaction costs")
    trade_log_df = apply_transaction_costs(prices, signals, params, volume=volume)

    logger.info("Building equity curve")
    equity_curve, daily_returns = _build_equity_curve(prices, signals, trade_log_df, params)

    metrics = _compute_metrics(equity_curve, daily_returns, trade_log_df)
    logger.info("Metrics: %s", metrics)

    # Convert trade log to list of dicts (JSON-serialisable keys)
    trade_log_records = trade_log_df.to_dict("records") if not trade_log_df.empty else []

    return {
        "trade_log": trade_log_records,
        "equity_curve": equity_curve,
        "metrics": metrics,
        "params": params,
        "data_quality": DATA_QUALITY.copy(),
    }


# ── IS / OOS split ────────────────────────────────────────────────────────────────

def run_is_oos(params: dict = PARAMETERS) -> dict:
    """
    Run Gate 1 IS and OOS windows separately and return combined results.

    IS window:  1993-01-01 → 2017-12-31  (25 years; ~200 IS trades)
    OOS window: 2018-01-01 → 2025-12-31  (8 years; ~32 OOS trades)

    Note: SPY data starts 1993-01-29; the first few January 1993 dates are absent.
    The SMA-200 warm-up period means the first ~200 trading days have no trend filter.

    Returns:
        dict with keys "is" and "oos", each containing a run_backtest() result dict.
    """
    logger.info("=== IS run (1993-01-01 → 2017-12-31) ===")
    is_result = run_backtest(params=params, start="1993-01-01", end="2017-12-31")

    logger.info("=== OOS run (2018-01-01 → 2025-12-31) ===")
    oos_result = run_backtest(params=params, start="2018-01-01", end="2025-12-31")

    return {"is": is_result, "oos": oos_result}


# ── CLI entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    result = run_is_oos()

    for window, res in result.items():
        m = res["metrics"]
        tl = res["trade_log"]
        print(f"\n{'='*60}")
        print(f"  {window.upper()} RESULTS")
        print(f"{'='*60}")
        print(f"  Total trades         : {m['total_trades']}")
        print(f"  Win rate             : {m['win_rate']:.1%}")
        print(f"  Profit factor        : {m['profit_factor']:.2f}")
        print(f"  Annualized return    : {m['annualized_return']:.2%}")
        print(f"  Sharpe ratio         : {m['sharpe_ratio']:.3f}")
        print(f"  Max drawdown         : {m['max_drawdown']:.2%}")
        print(f"  Liquidity-constrained: {m['liquidity_constrained_trades']}")
        if tl:
            print(f"  First trade entry    : {tl[0]['entry_date']}")
            print(f"  Last trade exit      : {tl[-1]['exit_date']}")
        print()

    print("Data quality (IS):")
    print(json.dumps(result["is"]["data_quality"], indent=2, default=str))
