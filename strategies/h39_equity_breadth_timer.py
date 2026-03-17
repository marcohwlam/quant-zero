"""
Strategy: H39 Equity Breadth Timer — % Sectors Above 200-SMA as SPY Entry Signal
Author: Strategy Coder Agent
Date: 2026-03-17
Hypothesis: Market breadth (% of 11 S&P 500 GICS sectors above 200-day SMA) predicts
            sustainable equity advances. Go long SPY when >= 7 sectors are above their
            200-SMA; exit to cash when <= 5. Hysteresis band prevents whipsaw.
Asset class: equities (US, SPY ETF)
Parent task: QUA-313
References: Faber (2007); Zaremba et al. (2021) Herding for profits; Zweig (1986);
            Asness, Ilmanen & Maloney (2017) AQR — Market Timing: Sin a Little;
            research/hypotheses/39_equity_breadth_timer.md
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

# ── Logging ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Parameters ───────────────────────────────────────────────────────────────────
PARAMETERS = {
    # Signal thresholds for 11-sector universe (2018+)
    "entry_threshold": 7,       # sectors above 200-SMA required to enter (range: 6–9)
    "exit_threshold": 5,        # sectors above 200-SMA at which to exit (range: 4–6)
    "sma_lookback": 200,        # SMA period per sector in trading days (range: 150–250)
    # Pre-2015: 9 sectors (no XLRE, no XLC)
    "entry_threshold_9": 6,     # proportional: 6/9 ≈ 7/11
    "exit_threshold_9": 4,
    # 2015–2018: 10 sectors (XLRE added, no XLC)
    "entry_threshold_10": 6,    # proportional: 6/10 ≈ 7/11
    "exit_threshold_10": 5,
    # Universe
    "spy_ticker": "SPY",
    # Sector ETFs; XLC available 2018+, XLRE available 2015+
    "sector_tickers": [
        "XLK", "XLF", "XLE", "XLV", "XLI",
        "XLU", "XLRE", "XLY", "XLP", "XLB", "XLC"
    ],
    # Transaction cost model (Engineering Director standard)
    "fixed_cost_per_share": 0.005,   # $0.005/share
    "slippage_pct": 0.0005,          # 0.05%
    "market_impact_k": 0.1,          # Almgren-Chriss coefficient
    "sigma_window": 20,              # rolling vol window for market impact
    "adv_window": 20,                # rolling ADV window
    "order_qty": 100,                # default order size in shares (for impact calc)
    "liquidity_threshold": 0.01,     # Q/ADV ratio above which to flag as constrained
    # Portfolio
    "init_cash": 25000.0,
}

# Sector availability boundaries
_XLRE_LIVE_DATE = pd.Timestamp("2015-10-07")   # XLRE inception
_XLC_LIVE_DATE = pd.Timestamp("2018-06-18")    # XLC inception

# Tickers available before 2015 (9 sectors)
_SECTORS_9 = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLU", "XLY", "XLP", "XLB"]
# Tickers available 2015–2018 (10 sectors, XLRE added)
_SECTORS_10 = _SECTORS_9 + ["XLRE"]
# Full 11-sector universe (2018+)
_SECTORS_11 = _SECTORS_10 + ["XLC"]

# ── Transaction Cost Constants ─────────────────────────────────────────────────
SIGMA_WINDOW = 20
ADV_WINDOW = 20
TRADING_DAYS_PER_YEAR = 252


# ── Data Download & Validation ─────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(start: str, end: str, sma_lookback: int, sector_tickers: list) -> dict:
    """
    Download SPY + all sector ETFs with a warmup window sufficient for SMA lookback.

    Warmup = sma_lookback * 1.5 + 30 calendar days (buffer for non-trading days).
    Validates: column presence, minimum data length, missing-day count.

    Returns dict:
        'spy': pd.DataFrame — SPY OHLCV
        'sectors': dict[str, pd.Series] — {ticker: Close Series} for each sector ETF
        'warnings': list[str] — non-fatal data quality messages
    """
    warmup_td = int(sma_lookback * 1.5) + 30
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_td)).strftime("%Y-%m-%d")

    all_warnings = []

    # Download SPY
    spy_df = _download_single("SPY", warmup_start, end)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing_cols = required - set(spy_df.columns)
    if missing_cols:
        raise ValueError(f"Missing SPY columns: {missing_cols}")
    if len(spy_df) < sma_lookback + 10:
        raise ValueError(f"Insufficient SPY data: {len(spy_df)} bars (need {sma_lookback + 10})")
    spy_na = int(spy_df["Close"].isna().sum())
    if spy_na > 5:
        all_warnings.append(f"SPY: {spy_na} missing trading days")

    # Download sectors
    sector_closes = {}
    for ticker in sector_tickers:
        try:
            df = _download_single(ticker, warmup_start, end)
            if "Close" not in df.columns:
                all_warnings.append(f"{ticker}: missing Close column — skipped")
                continue
            na_count = int(df["Close"].isna().sum())
            if na_count > 5:
                all_warnings.append(f"{ticker}: {na_count} missing trading days")
            sector_closes[ticker] = df["Close"]
        except Exception as exc:
            all_warnings.append(f"{ticker}: download failed — {exc}")

    for w in all_warnings:
        logger.warning(w)

    return {"spy": spy_df, "sectors": sector_closes, "warnings": all_warnings}


# ── Signal Generation ─────────────────────────────────────────────────────────

def compute_sector_breadth(
    sector_closes: dict,
    trading_dates: pd.DatetimeIndex,
    sma_lookback: int,
) -> pd.DataFrame:
    """
    Compute daily breadth_count: number of sectors where close > 200-day SMA.

    Handles dynamic universe — each date uses only sectors available at that date:
    - Before XLRE inception: 9 sectors
    - XLRE inception to XLC inception: 10 sectors
    - After XLC inception: 11 sectors

    Returns DataFrame with columns: [breadth_count, n_sectors, breadth_pct]
    Indexed to trading_dates.
    """
    # Build aligned Close DataFrame for all available sectors
    close_df = pd.DataFrame(
        {t: s for t, s in sector_closes.items()},
        index=trading_dates
    ).ffill()

    # Compute 200-day SMA for each sector
    sma_df = close_df.rolling(window=sma_lookback, min_periods=sma_lookback).mean()

    # Boolean: sector above its SMA
    above_sma = (close_df > sma_df).astype(int)

    # Dynamic universe mask per date
    breadth_records = []
    for date in trading_dates:
        if date < _XLRE_LIVE_DATE:
            universe = [t for t in _SECTORS_9 if t in above_sma.columns]
        elif date < _XLC_LIVE_DATE:
            universe = [t for t in _SECTORS_10 if t in above_sma.columns]
        else:
            universe = [t for t in _SECTORS_11 if t in above_sma.columns]

        row = above_sma.loc[date, universe] if universe else pd.Series(dtype=int)
        n = len(universe)
        count = int(row.sum()) if not row.empty else 0
        breadth_records.append({
            "date": date,
            "breadth_count": count,
            "n_sectors": n,
            "breadth_pct": count / n if n > 0 else np.nan,
        })

    return pd.DataFrame(breadth_records).set_index("date")


def _get_thresholds(date: pd.Timestamp, params: dict) -> tuple:
    """
    Return (entry_threshold, exit_threshold) based on sector universe at given date.
    """
    if date < _XLRE_LIVE_DATE:
        return params["entry_threshold_9"], params["exit_threshold_9"]
    elif date < _XLC_LIVE_DATE:
        return params["entry_threshold_10"], params["exit_threshold_10"]
    else:
        return params["entry_threshold"], params["exit_threshold"]


def generate_weekly_signals(
    breadth_df: pd.DataFrame,
    params: dict,
) -> pd.Series:
    """
    Generate weekly SPY position signal from Friday-close breadth counts.

    Signal logic:
    - Evaluate breadth_count at Friday close
    - Entry: breadth_count >= entry_threshold → signal = 1 (long SPY)
    - Exit: breadth_count <= exit_threshold → signal = 0 (cash)
    - Hysteresis: hold current state when between thresholds
    - Signal changes effective at next Monday open

    Returns pd.Series of signals {0, 1} at daily frequency,
    forward-filled from Friday decision to next Friday.
    Signal is NaN until first Friday with sufficient SMA data.
    """
    # Extract Friday closes (weekday==4)
    fridays = breadth_df[breadth_df.index.dayofweek == 4].copy()
    if fridays.empty:
        raise ValueError("No Friday dates found in breadth data")

    # Determine signal at each Friday using hysteresis
    friday_signals = pd.Series(np.nan, index=fridays.index)
    current_signal = np.nan  # start undecided

    for date, row in fridays.iterrows():
        count = row["breadth_count"]
        n = row["n_sectors"]
        if n == 0 or np.isnan(count):
            continue  # not enough SMA warmup yet

        entry_th, exit_th = _get_thresholds(date, params)

        if np.isnan(current_signal):
            # Initial state: use entry threshold to determine starting position
            if count >= entry_th:
                current_signal = 1
            else:
                current_signal = 0

        if count >= entry_th:
            current_signal = 1
        elif count <= exit_th:
            current_signal = 0
        # else: hysteresis — maintain current_signal

        friday_signals.loc[date] = current_signal

    # Drop NaN (no-data Fridays before SMA warmup)
    friday_signals = friday_signals.dropna()

    # Forward-fill from Friday to next Friday across full daily index
    daily_signal = friday_signals.reindex(breadth_df.index)
    # Signal effective from next TRADING day (shift +1 business day to account for
    # "position change at Monday open after Friday signal")
    daily_signal = daily_signal.shift(1, freq="B")
    daily_signal = daily_signal.reindex(breadth_df.index).ffill()

    return daily_signal.rename("signal")


# ── Transaction Cost Model ──────────────────────────────────────────────────────

def compute_transaction_costs(
    spy_df: pd.DataFrame,
    order_qty: int,
    params: dict,
) -> pd.DataFrame:
    """
    Compute per-share transaction costs for SPY using the Engineering Director model:
      fixed_cost = $0.005/share
      slippage   = 0.05% of price
      market_impact = k × σ × sqrt(Q / ADV)
        where σ = 20-day rolling daily return std
              Q = order_qty (shares)
              ADV = 20-day avg daily volume

    Returns DataFrame with columns: [fixed_cost, slippage_cost, market_impact, total_cost,
                                     liquidity_constrained, sigma, adv, q_over_adv]
    """
    sigma_w = params.get("sigma_window", SIGMA_WINDOW)
    adv_w = params.get("adv_window", ADV_WINDOW)
    k = params.get("market_impact_k", 0.1)
    fixed = params.get("fixed_cost_per_share", 0.005)
    slippage_pct = params.get("slippage_pct", 0.0005)
    liq_threshold = params.get("liquidity_threshold", 0.01)

    close = spy_df["Close"]
    volume = spy_df["Volume"]

    sigma = close.pct_change().rolling(sigma_w).std()          # daily return std
    adv = volume.rolling(adv_w).mean()                         # avg daily volume (shares)

    q_over_adv = order_qty / adv.replace(0, np.nan)            # liquidity ratio

    # Square-root market impact model
    market_impact = k * sigma * np.sqrt(q_over_adv.fillna(0))

    slippage_cost = slippage_pct * close                        # $ per share at market price
    fixed_series = pd.Series(fixed, index=close.index)

    liquidity_constrained = q_over_adv > liq_threshold

    cost_df = pd.DataFrame({
        "fixed_cost": fixed_series,
        "slippage_cost": slippage_cost,
        "market_impact": market_impact,
        "total_cost": fixed_series + slippage_cost + market_impact,
        "liquidity_constrained": liquidity_constrained,
        "sigma": sigma,
        "adv": adv,
        "q_over_adv": q_over_adv,
    })

    # Warn on liquidity-constrained days
    n_constrained = int(liquidity_constrained.sum())
    if n_constrained > 0:
        logger.warning(f"SPY: {n_constrained} days where Q/ADV > {liq_threshold} — liquidity_constrained=True")

    return cost_df


# ── Core Backtest Simulation ───────────────────────────────────────────────────

def simulate_strategy(
    spy_df: pd.DataFrame,
    daily_signal: pd.Series,
    cost_df: pd.DataFrame,
    params: dict,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Simulate SPY long/cash strategy based on daily_signal.

    Position changes at market open (modelled as next-day open price).
    Transaction costs applied on entry and exit using the Engineering Director model.

    Returns DataFrame with columns:
        date, signal, position, spy_close, spy_open, spy_return, strategy_return,
        cumulative_return, trade_id, entry_price, exit_price, pnl,
        transaction_cost, liquidity_constrained
    Indexed by date (trading days within [start, end]).
    """
    # Slice to backtest window only (after warmup)
    mask = (spy_df.index >= start) & (spy_df.index <= end)
    spy_bt = spy_df.loc[mask].copy()
    signal_bt = daily_signal.reindex(spy_bt.index).fillna(0)
    cost_bt = cost_df.reindex(spy_bt.index)

    rows = []
    cash = params["init_cash"]
    shares_held = 0
    in_trade = False
    trade_id = 0
    current_entry_price = np.nan
    current_entry_cost = 0.0
    cumulative_return = 1.0  # multiplicative

    prev_signal = 0  # start in cash

    for i, date in enumerate(spy_bt.index):
        close_px = float(spy_bt["Close"].iloc[i])
        open_px = float(spy_bt["Open"].iloc[i]) if "Open" in spy_bt.columns else close_px
        spy_ret = float(spy_bt["Close"].pct_change().iloc[i]) if i > 0 else 0.0
        sig = int(signal_bt.iloc[i])
        tc_row = cost_bt.iloc[i]
        total_cost = float(tc_row["total_cost"]) if not np.isnan(tc_row["total_cost"]) else 0.0
        liq_constrained = bool(tc_row["liquidity_constrained"])

        entry_price_rec = np.nan
        exit_price_rec = np.nan
        pnl_rec = 0.0
        tc_rec = 0.0

        # Detect signal transition (entry or exit at open)
        signal_changed = (sig != prev_signal)

        if signal_changed:
            if sig == 1 and not in_trade:
                # --- ENTRY ---
                entry_price_rec = open_px
                # Shares = cash / (open_px + total_cost)
                shares_held = int(cash / (open_px + total_cost))
                if shares_held <= 0:
                    shares_held = 0
                    in_trade = False
                else:
                    spend = shares_held * open_px
                    tc_spend = shares_held * total_cost
                    cash -= (spend + tc_spend)
                    current_entry_price = open_px
                    current_entry_cost = total_cost
                    trade_id += 1
                    in_trade = True
                    tc_rec = shares_held * total_cost
                    logger.info(
                        f"ENTRY  {date.date()} | shares={shares_held} "
                        f"@ open={open_px:.2f} | TC={tc_rec:.2f} "
                        f"| liq_constrained={liq_constrained}"
                    )

            elif sig == 0 and in_trade:
                # --- EXIT ---
                exit_price_rec = open_px
                proceeds = shares_held * open_px
                tc_exit = shares_held * total_cost
                pnl_rec = (
                    shares_held * (open_px - current_entry_price)
                    - shares_held * current_entry_cost
                    - tc_exit
                )
                cash += proceeds - tc_exit
                in_trade = False
                tc_rec = tc_exit
                logger.info(
                    f"EXIT   {date.date()} | shares={shares_held} "
                    f"@ open={open_px:.2f} | PnL={pnl_rec:.2f} | TC={tc_rec:.2f}"
                )
                shares_held = 0

        # Portfolio value at close
        portfolio_value = cash + shares_held * close_px

        # Strategy daily return: change in portfolio value
        if i == 0:
            strat_ret = 0.0
        else:
            prev_val = rows[-1]["portfolio_value"] if rows else params["init_cash"]
            strat_ret = (portfolio_value - prev_val) / prev_val if prev_val > 0 else 0.0

        cumulative_return = cumulative_return * (1 + strat_ret)

        rows.append({
            "date": date,
            "signal": sig,
            "position": 1 if in_trade else 0,
            "spy_close": close_px,
            "spy_open": open_px,
            "spy_return": spy_ret,
            "strategy_return": strat_ret,
            "cumulative_return": cumulative_return,
            "trade_id": trade_id if in_trade or signal_changed else 0,
            "entry_price": entry_price_rec,
            "exit_price": exit_price_rec,
            "pnl": pnl_rec,
            "transaction_cost": tc_rec,
            "liquidity_constrained": liq_constrained if signal_changed else False,
            "portfolio_value": portfolio_value,
        })

        prev_signal = sig

    result_df = pd.DataFrame(rows).set_index("date")
    return result_df


# ── Summary Metrics ────────────────────────────────────────────────────────────

def compute_metrics(result_df: pd.DataFrame, params: dict) -> dict:
    """
    Compute summary performance metrics from simulation results.

    Returns dict with: sharpe, max_drawdown, win_rate, total_return,
                       trade_count, avg_hold_days, total_transaction_cost,
                       liquidity_constrained_trades.
    """
    strat_rets = result_df["strategy_return"].fillna(0)

    # Sharpe ratio (annualized, assuming 252 trading days)
    mean_ret = strat_rets.mean()
    std_ret = strat_rets.std()
    sharpe = (mean_ret / std_ret * np.sqrt(TRADING_DAYS_PER_YEAR)) if std_ret > 0 else np.nan

    # Maximum drawdown
    cum_ret = result_df["cumulative_return"]
    rolling_max = cum_ret.cummax()
    drawdown = (cum_ret - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min())

    # Total return
    if len(cum_ret) > 0:
        total_return = float(cum_ret.iloc[-1]) - 1.0
    else:
        total_return = np.nan

    # Win rate: trades with positive PnL
    completed_pnls = result_df[result_df["pnl"] != 0]["pnl"]
    win_rate = float((completed_pnls > 0).sum() / len(completed_pnls)) if len(completed_pnls) > 0 else np.nan
    trade_count = len(result_df[result_df["entry_price"].notna()])

    total_tc = float(result_df["transaction_cost"].sum())
    liq_constrained_count = int(result_df["liquidity_constrained"].sum())

    return {
        "sharpe": round(sharpe, 4) if not np.isnan(sharpe) else None,
        "max_drawdown": round(max_drawdown, 4),
        "win_rate": round(win_rate, 4) if not np.isnan(win_rate) else None,
        "total_return": round(total_return, 4),
        "trade_count": trade_count,
        "total_transaction_cost": round(total_tc, 2),
        "liquidity_constrained_trades": liq_constrained_count,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def run_backtest(
    start_date: str = "2007-01-01",
    end_date: str = "2023-12-31",
    entry_threshold: int = PARAMETERS["entry_threshold"],
    exit_threshold: int = PARAMETERS["exit_threshold"],
    sma_lookback: int = PARAMETERS["sma_lookback"],
    params: dict | None = None,
) -> dict:
    """
    Run the H39 Equity Breadth Timer backtest.

    Downloads SPY + 11 sector ETFs, computes weekly breadth signal, simulates
    long/cash strategy with Engineering Director transaction cost model.

    Args:
        start_date: Backtest start date (YYYY-MM-DD). Default 2007-01-01.
        end_date:   Backtest end date (YYYY-MM-DD). Default 2023-12-31.
        entry_threshold: Sectors above 200-SMA to trigger entry (default 7).
        exit_threshold:  Sectors above 200-SMA to trigger exit (default 5).
        sma_lookback:    SMA period in trading days (default 200).
        params: Optional full parameter dict to override PARAMETERS.

    Returns:
        dict with keys:
            'results': pd.DataFrame — daily simulation results (see simulate_strategy)
            'metrics': dict — summary performance metrics
            'breadth': pd.DataFrame — daily breadth_count and n_sectors
            'data_warnings': list[str] — non-fatal data issues encountered
    """
    t0 = datetime.now()
    if params is None:
        params = PARAMETERS.copy()

    # Apply arg overrides to params
    params["entry_threshold"] = entry_threshold
    params["exit_threshold"] = exit_threshold
    params["sma_lookback"] = sma_lookback

    if entry_threshold <= exit_threshold:
        raise ValueError(
            f"entry_threshold ({entry_threshold}) must be strictly greater than "
            f"exit_threshold ({exit_threshold}) to enforce hysteresis."
        )

    logger.info(
        f"H39 Breadth Timer: start={start_date} end={end_date} "
        f"entry>={entry_threshold} exit<={exit_threshold} sma={sma_lookback}"
    )

    # 1. Download data
    data = download_data(start_date, end_date, sma_lookback, params["sector_tickers"])
    spy_df = data["spy"]
    sector_closes = data["sectors"]

    if not sector_closes:
        raise ValueError("No sector data downloaded. Cannot compute breadth signal.")

    # 2. Compute breadth on full data range (including warmup for SMA)
    all_trading_dates = spy_df.index
    breadth_df = compute_sector_breadth(sector_closes, all_trading_dates, sma_lookback)

    # 3. Generate weekly signals
    daily_signal = generate_weekly_signals(breadth_df, params)

    # 4. Transaction costs on SPY
    cost_df = compute_transaction_costs(spy_df, params["order_qty"], params)

    # 5. Simulate
    result_df = simulate_strategy(spy_df, daily_signal, cost_df, params, start_date, end_date)

    # 6. Metrics
    metrics = compute_metrics(result_df, params)

    elapsed = (datetime.now() - t0).total_seconds()
    logger.info(f"H39 backtest complete in {elapsed:.1f}s | metrics={metrics}")

    # Trim breadth to backtest window for output
    breadth_out = breadth_df.loc[
        (breadth_df.index >= start_date) & (breadth_df.index <= end_date)
    ]

    return {
        "results": result_df,
        "metrics": metrics,
        "breadth": breadth_out,
        "data_warnings": data["warnings"],
    }


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    output = run_backtest(
        start_date="2007-01-01",
        end_date="2023-12-31",
    )
    print("\n=== H39 Equity Breadth Timer — Results ===")
    print(f"Metrics: {output['metrics']}")
    if output["data_warnings"]:
        print(f"Data warnings: {output['data_warnings']}")
    print(output["results"].tail(10))
