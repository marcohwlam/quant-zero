"""
Strategy: H07 Multi-Asset Time-Series Momentum (TSMOM)
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: 6-ETF universe (SPY, QQQ, TLT, GLD, USO, DBC) with 12-month trailing return
            signal; long if positive, flat otherwise; monthly rebalancing at end-of-month
            close with next-open execution. Long-only variant for $25K account.
Asset class: equities (ETFs)
Parent task: QUA-114
Reference: Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum" — JFE
"""

import warnings
import numpy as np
import pandas as pd
import vectorbt as vbt
import yfinance as yf

# All tunable parameters exposed here for sensitivity scanning
PARAMETERS = {
    "universe": ["SPY", "QQQ", "TLT", "GLD", "USO", "DBC"],
    "lookback_months": 12,             # Trailing return lookback (months)
    "rebalance_frequency": "monthly",  # "monthly" or "quarterly"
    "universe_size": 6,                # Max assets in portfolio at any time (top-N)
    "intramonth_stop_pct": 0.20,       # Per-asset stop-loss threshold from entry price
    "long_only": True,                 # Long-only; flat (cash) for negative signals
    "init_cash": 25000,                # Starting capital ($)
    "order_qty": 100,                  # Order size in shares for market impact calculation
}

TRADING_DAYS_PER_MONTH = 21   # approximate; used for lookback conversion
TRADING_DAYS_PER_YEAR = 252   # approximate; used for rolling volatility and correlation


# ── Data Loading ──────────────────────────────────────────────────────────────

def download_data(
    tickers: list[str], start: str, end: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Download adjusted close prices and volume for tickers via yfinance.

    auto_adjust=True: prices are adjusted for splits and dividends.

    Returns:
        close:  DataFrame of adjusted closing prices, columns = tickers
        volume: DataFrame of daily share volume, columns = tickers
    """
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

    # Handle MultiIndex vs flat column structure across yfinance versions
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        volume = raw["Volume"]
    else:
        # Single-ticker download returns flat columns
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
        volume = raw[["Volume"]].rename(columns={"Volume": tickers[0]})

    # Ensure Series are promoted to DataFrames
    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    if isinstance(volume, pd.Series):
        volume = volume.to_frame(name=tickers[0])

    # Filter to requested tickers (may differ if some have no data)
    available = [t for t in tickers if t in close.columns]
    return close[available].copy(), volume[available].copy()


# ── Data Quality Checklist ────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame) -> dict:
    """
    Run data quality checks per the Engineering Director checklist.

    Data quality notes (documented per spec):
    - Survivorship bias: Fixed universe — all ETFs active since before 2018 backtest start.
      DBC launched Feb 2006; USO launched Apr 2006. No survivorship bias.
    - Price adjustments: yfinance auto_adjust=True handles splits and dividends.
    - Earnings exclusion: N/A — ETFs do not have individual earnings events.
    - Delisted tickers: N/A — major ETFs in this universe have negligible delisting risk.
    - Data gaps: Flagged if any ticker has >5 missing business days in the range.

    Returns dict with per-ticker stats and static notes.
    """
    report = {
        "survivorship_bias": (
            "Fixed universe (SPY, QQQ, TLT, GLD, USO, DBC). All ETFs launched before 2018 "
            "(DBC: Feb 2006, USO: Apr 2006). No survivorship bias for this universe."
        ),
        "price_adjustment": "yfinance auto_adjust=True — adjusted for splits and dividends.",
        "earnings_exclusion": "N/A — ETFs have no individual earnings events.",
        "delisted": "N/A — major ETFs in this universe have negligible delisted risk.",
        "tickers": {},
    }

    flagged = []
    for ticker in close.columns:
        price = close[ticker].dropna()
        if price.empty:
            report["tickers"][ticker] = {"error": "No data returned"}
            flagged.append(ticker)
            continue

        expected = pd.bdate_range(start=price.index.min(), end=price.index.max())
        missing_count = len(expected.difference(price.index))

        report["tickers"][ticker] = {
            "total_days": len(price),
            "missing_business_days": missing_count,
            "gap_flag": missing_count > 5,
            "start": str(price.index.min().date()),
            "end": str(price.index.max().date()),
        }
        if missing_count > 5:
            flagged.append(ticker)

    if flagged:
        warnings.warn(f"Data gap flag (>5 missing business days): {flagged}")

    return report


# ── Momentum Signal ───────────────────────────────────────────────────────────

def compute_momentum_signal(
    close: pd.DataFrame, params: dict
) -> pd.DataFrame:
    """
    Compute 12-month trailing total return signal at monthly (or quarterly) frequency.

    Signal logic (long-only variant):
      R_12m = (P_t / P_{t-lookback}) - 1
      signal = +1.0 if R_12m > 0 (long), 0.0 otherwise (flat / cash)

    Lookback in trading days = lookback_months * 21 (approximate calendar conversion).
    Signal is computed at end-of-rebalancing-period close.
    No look-ahead: R_12m at date T uses only P_t and P_{t-lookback} — no future prices.

    Returns:
        pd.DataFrame at monthly frequency; values 0.0 or 1.0 per ticker.
    """
    lookback_td = params["lookback_months"] * TRADING_DAYS_PER_MONTH

    # 12-month trailing return: R_t = (P_t / P_{t-lookback}) - 1
    trailing_return = close.pct_change(lookback_td)

    # Resample to end of each rebalancing period
    freq = "ME" if params["rebalance_frequency"] == "monthly" else "QE"
    monthly_return = trailing_return.resample(freq).last()

    # Long-only signal: +1 if positive return, 0 otherwise
    signal = (monthly_return > 0).astype(float)

    # Universe size cap: retain only top-N assets by trailing return
    universe_size = params.get("universe_size", len(close.columns))
    if universe_size < len(close.columns):
        # Rank descending; keep top-N AND require a positive signal
        rank = monthly_return.rank(axis=1, ascending=False)
        signal = signal * (rank <= universe_size).astype(float)

    return signal


# ── Entry / Exit Signal Generation ───────────────────────────────────────────

def generate_daily_signals(
    close: pd.DataFrame, params: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Convert monthly TSMOM signals to daily entry/exit signals.

    Execution model:
    - Signal is computed at end-of-month close T (rebalancing date).
    - Execution fires at open of first trading day T+1 (next-open execution).
    - Entry: generated at each rebalancing date for all assets with active signal (+1).
      Firing entries at EVERY rebalancing where signal is active (not just transitions)
      allows re-entry after intramonth stop losses.
      vectorbt ignores entries when already in position (accumulate=False default).
    - Exit: generated at first trading day after rebalancing date where signal turned off.

    No look-ahead: all signals use data available at T, applied from T+1 onward.

    Returns:
        entries: Boolean DataFrame (daily), True on entry bar
        exits:   Boolean DataFrame (daily), True on exit bar
    """
    monthly_signal = compute_momentum_signal(close, params)
    monthly_dates = monthly_signal.index

    entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    exits = pd.DataFrame(False, index=close.index, columns=close.columns)

    for i, rebal_date in enumerate(monthly_dates):
        # Find first trading day strictly after this rebalancing date
        future_dates = close.index[close.index > rebal_date]
        if len(future_dates) == 0:
            continue
        exec_date = future_dates[0]

        current_sig = monthly_signal.loc[rebal_date]
        # Previous signal (default to all-zero if no prior period)
        prev_sig = monthly_signal.iloc[i - 1] if i > 0 else pd.Series(0.0, index=monthly_signal.columns)

        for ticker in close.columns:
            if current_sig[ticker] > 0:
                # Asset is in the long portfolio this month → entry (or re-entry)
                # vectorbt ignores if already holding a position
                entries.at[exec_date, ticker] = True
            elif current_sig[ticker] == 0 and prev_sig[ticker] > 0:
                # Signal turned off → exit position
                exits.at[exec_date, ticker] = True

    return entries, exits


# ── Transaction Cost Model ────────────────────────────────────────────────────

def compute_market_impact(
    close: pd.DataFrame, volume: pd.DataFrame, params: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute square-root market impact per the canonical Engineering Director model.

    Formula: impact = k × σ × sqrt(Q / ADV)
      k   = 0.1 (institutional constant; Johnson, Algorithmic Trading & DMA)
      σ   = 20-day rolling daily return volatility
      Q   = order value in dollars (order_qty × close_price)
      ADV = 20-day rolling average daily dollar volume (volume × close)

    Returns:
        market_impact: DataFrame of impact as fraction of price (shape = close.shape)
        q_over_adv:    DataFrame of Q/ADV ratios for liquidity flagging
    """
    k = 0.1
    order_qty = params.get("order_qty", 100)

    # 20-day rolling return volatility (σ)
    sigma = close.pct_change().rolling(20).std()

    # 20-day rolling average daily dollar volume (ADV in $)
    dollar_volume = volume * close
    adv_dollar = dollar_volume.rolling(20).mean()

    # Q/ADV: order value as fraction of ADV
    order_value = order_qty * close
    q_over_adv = (order_value / adv_dollar.replace(0, np.nan)).fillna(0.0).clip(lower=0)

    # Square-root market impact (fraction of price)
    impact = k * sigma * np.sqrt(q_over_adv)
    return impact.fillna(0.0), q_over_adv


def check_liquidity_constraints(q_over_adv: pd.DataFrame) -> dict:
    """
    Flag dates/tickers where order exceeds 1% of ADV (liquidity-constrained).

    At $25K with ~$4K per ETF position, Q/ADV for liquid ETFs (SPY, QQQ, TLT) will
    effectively be 0. USO/DBC are thinner but still liquid at this capital level.
    """
    constrained = q_over_adv > 0.01
    n_bars = int(constrained.sum().sum())

    if n_bars == 0:
        return {"liquidity_constrained": False, "constrained_bars": 0}

    report: dict = {"liquidity_constrained": True, "constrained_bars": n_bars, "detail": {}}
    for ticker in constrained.columns:
        bad_dates = constrained[ticker][constrained[ticker]].index
        if len(bad_dates) > 0:
            report["detail"][ticker] = [str(d.date()) for d in bad_dates[:5]]
            warnings.warn(
                f"Liquidity constraint: {ticker} Q/ADV > 0.01 on {len(bad_dates)} bars. "
                "Order exceeds 1% of average daily volume."
            )
    return report


# ── Correlation Monitoring ────────────────────────────────────────────────────

def compute_uso_dbc_correlation(close: pd.DataFrame) -> dict:
    """
    Track 12-month rolling USO/DBC daily return correlation.

    Per Research Director review (QUA-111): DBC holds ~30-40% crude oil exposure, creating
    structural correlation with USO. Flag if max rolling correlation exceeds 0.7 over any
    12-month IS window — if flagged, consider replacing USO with SLV or DBB.

    Returns dict with max correlation, flag status, and bar count above threshold.
    """
    if "USO" not in close.columns or "DBC" not in close.columns:
        return {"note": "USO or DBC not in universe — correlation check skipped."}

    returns = close[["USO", "DBC"]].pct_change()
    rolling_corr = returns["USO"].rolling(TRADING_DAYS_PER_YEAR).corr(returns["DBC"])

    valid_corr = rolling_corr.dropna()
    if valid_corr.empty:
        return {"note": "Insufficient data for rolling correlation."}

    max_corr = float(valid_corr.max())
    n_high = int((valid_corr > 0.7).sum())

    result = {
        "uso_dbc_max_rolling_12m_corr": round(max_corr, 4),
        "uso_dbc_bars_above_0_7": n_high,
        "uso_dbc_corr_flag": max_corr > 0.7,
    }

    if max_corr > 0.7:
        warnings.warn(
            f"USO/DBC rolling 12m correlation peaked at {max_corr:.2f} > 0.7. "
            "Per Research Director review QUA-111: consider replacing USO with SLV or DBB "
            "for improved diversification."
        )

    return result


# ── Strategy Runner ───────────────────────────────────────────────────────────

def run_strategy(
    universe: list[str] | None = None,
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = PARAMETERS,
    return_portfolio: bool = False,
) -> dict:
    """
    Run H07 Multi-Asset TSMOM and return a metrics dict.

    Transaction cost model (canonical ETF/equities):
    - Fixed:   $0.005/share → expressed as fraction: fees = 0.005 / close
    - Slippage: 0.05% base + square-root market impact
    - Intramonth stop: sl_stop = intramonth_stop_pct (from entry price; per-asset)

    Returns:
        Metrics dict with Sharpe, MDD, win rate, trade count, USO/DBC correlation,
        data quality report, and liquidity flags.
        If return_portfolio=True, also includes 'portfolio' (vbt.Portfolio object).

    Raises:
        ValueError: if no price data is available or lookback exceeds data history.
    """
    if universe is None:
        universe = params.get("universe", PARAMETERS["universe"])

    # Download price and volume data
    close, volume = download_data(universe, start, end)

    # Data quality checks
    quality_report = check_data_quality(close)

    # Validate usable data
    close = close.dropna(axis=1, how="all")
    if close.empty:
        raise ValueError(f"No price data for {universe} in {start}–{end}.")

    min_required = params["lookback_months"] * TRADING_DAYS_PER_MONTH + 20
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    # Generate entry/exit signals
    entries, exits = generate_daily_signals(close, params)

    # Market impact and liquidity flagging
    market_impact, q_over_adv = compute_market_impact(close, volume, params)
    liquidity_report = check_liquidity_constraints(q_over_adv)

    # USO/DBC correlation check
    corr_report = compute_uso_dbc_correlation(close)

    # Transaction costs (canonical equities model):
    #   fees     = $0.005/share → fraction = 0.005 / price
    #   slippage = 0.05% base + market impact
    fees = 0.005 / close
    slippage = 0.0005 + market_impact

    empty_result = {
        "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0, "win_loss_ratio": 0.0,
        "total_return": 0.0, "trade_count": 0, "period": f"{start} to {end}",
        "tickers_traded": list(close.columns),
        "uso_dbc_correlation": corr_report,
        "data_quality": quality_report,
        "liquidity": liquidity_report,
    }

    if entries.sum().sum() == 0:
        warnings.warn("No entry signals generated — returning empty result.")
        return empty_result

    # Build vectorbt portfolio
    # sl_stop implements per-asset intramonth stop-loss from entry price.
    # accumulate=False (default): duplicate entry signals while in position are ignored,
    # which allows monthly re-entry logic after stop outs without adding to position.
    pf = vbt.Portfolio.from_signals(
        close,
        entries=entries,
        exits=exits,
        sl_stop=params.get("intramonth_stop_pct", 0.20),
        fees=fees,
        slippage=slippage,
        init_cash=params.get("init_cash", 25000),
    )

    # Performance metrics
    sharpe = float(pf.sharpe_ratio())
    mdd = float(pf.max_drawdown())
    total_return = float(pf.total_return())
    trade_count = int(pf.trades.count())

    # Win rate and win/loss ratio (per Risk Director requirements)
    try:
        pnl_raw = pf.trades.pnl.to_pandas()
        pnl_vals = np.array(pnl_raw).flatten()
        pnl_vals = pnl_vals[~np.isnan(pnl_vals)]
        win_rate = float(np.mean(pnl_vals > 0)) if len(pnl_vals) > 0 else 0.0
        wins = pnl_vals[pnl_vals > 0]
        losses = pnl_vals[pnl_vals < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss != 0 else float("inf")
    except Exception:
        win_rate, win_loss_ratio = 0.0, 0.0

    # Risk Director gate warning: win rate < 50% AND win/loss ratio < 1.2
    if win_rate < 0.50 and win_loss_ratio < 1.2:
        warnings.warn(
            f"Win rate {win_rate:.1%} < 50% AND win/loss ratio {win_loss_ratio:.2f} < 1.2. "
            "Strategy may not pass Gate 1. Avg win must be >1.2× avg loss when win rate is low."
        )

    result = {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "win_loss_ratio": win_loss_ratio,
        "total_return": total_return,
        "trade_count": trade_count,
        "period": f"{start} to {end}",
        "tickers_traded": list(close.columns),
        "uso_dbc_correlation": corr_report,
        "data_quality": quality_report,
        "liquidity": liquidity_report,
    }

    if return_portfolio:
        result["portfolio"] = pf

    return result


# ── Parameter Sensitivity Scan ────────────────────────────────────────────────

def scan_parameters(
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Scan Sharpe ratio across the Gate 1 parameter grid from QUA-114.

    Parameter grid (from spec):
    - lookback_months: [6, 9, 12, 18]
    - rebalance_frequency: [monthly, quarterly]
    - universe_size: [4, 6]
    - intramonth_stop_pct: [0.15, 0.20, 0.25]

    Gate 1 disqualification: Sharpe variance > 30% across any parameter dimension.
    """
    results: dict = {}

    # Lookback scan
    for lb in [6, 9, 12, 18]:
        p = {**base_params, "lookback_months": lb}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[f"lookback_{lb}m"] = r["sharpe"]
        except Exception as exc:
            results[f"lookback_{lb}m"] = f"error: {exc}"

    # Rebalance frequency
    for freq in ["monthly", "quarterly"]:
        p = {**base_params, "rebalance_frequency": freq}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[f"rebalance_{freq}"] = r["sharpe"]
        except Exception as exc:
            results[f"rebalance_{freq}"] = f"error: {exc}"

    # Universe size
    for n in [4, 6]:
        p = {**base_params, "universe_size": n}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[f"universe_{n}"] = r["sharpe"]
        except Exception as exc:
            results[f"universe_{n}"] = f"error: {exc}"

    # Intramonth stop
    for stop in [0.15, 0.20, 0.25]:
        p = {**base_params, "intramonth_stop_pct": stop}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[f"stop_{int(stop * 100)}pct"] = r["sharpe"]
        except Exception as exc:
            results[f"stop_{int(stop * 100)}pct"] = f"error: {exc}"

    # Gate 1 variance check across all numeric results
    sharpe_vals = [v for v in results.values() if isinstance(v, float) and not np.isnan(v)]
    if len(sharpe_vals) > 1:
        sharpe_range = max(sharpe_vals) - min(sharpe_vals)
        sharpe_mean = np.mean(sharpe_vals)
        variance_pct = sharpe_range / abs(sharpe_mean) if sharpe_mean != 0 else float("inf")
        results["_sharpe_range"] = round(sharpe_range, 4)
        results["_sharpe_variance_pct"] = round(variance_pct, 4)
        if variance_pct > 0.30:
            results["_gate1_variance_flag"] = (
                f"FAIL: Sharpe variance {variance_pct:.1%} > 30% — automatic disqualification."
            )
        else:
            results["_gate1_variance_flag"] = (
                f"PASS: Sharpe variance {variance_pct:.1%} ≤ 30%."
            )

    return results


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="H07 Multi-Asset Time-Series Momentum (TSMOM) backtest runner."
    )
    parser.add_argument(
        "--plot", action="store_true",
        help="Open an interactive Plotly chart in the default browser after IS backtest.",
    )
    args = parser.parse_args()

    print("Running IS backtest (2018-01-01 to 2021-12-31)...")
    is_result = run_strategy(start="2018-01-01", end="2021-12-31", return_portfolio=args.plot)
    safe_keys = {k: v for k, v in is_result.items() if k not in ("portfolio", "data_quality", "liquidity")}
    print("IS:", safe_keys)

    if args.plot:
        pf = is_result["portfolio"]
        fig = pf.plot()
        fig.show()

    print("\nRunning OOS backtest (2022-01-01 to 2023-12-31)...")
    oos_result = run_strategy(start="2022-01-01", end="2023-12-31")
    safe_oos = {k: v for k, v in oos_result.items() if k not in ("data_quality", "liquidity")}
    print("OOS:", safe_oos)

    print("\nUSO/DBC correlation:")
    print(is_result.get("uso_dbc_correlation", {}))

    print("\nData quality report:")
    for ticker, info in is_result.get("data_quality", {}).get("tickers", {}).items():
        print(f"  {ticker}: {info}")
