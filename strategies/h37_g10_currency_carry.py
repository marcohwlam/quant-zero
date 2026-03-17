"""
Strategy: H37 G10 Currency Carry (Long/Short)
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: Currencies of high-yield G10 nations outperform low-yield nations after adjusting
            for momentum confirmation. Long top-2 carry ETFs (yield > USD), short bottom-2
            carry ETFs (yield < USD), subject to a 60-day SMA momentum filter. Monthly rebal.
            VIX > 35 triggers emergency exit. -8% hard stop per position.

Asset class: FX ETFs (equity-like instruments tracking currency exposure)
Parent task: QUA-293
References:
    - Lustig, Roussanov & Verdelhan (2011) "Common Risk Factors in Currency Markets" RFS 24(11)
    - Menkhoff, Sarno, Schmeling & Schrimpf (2012) "Carry Trades and Global Foreign Exchange
      Volatility" JF 67(2)
    - Asness, Moskowitz & Pedersen (2013) "Value and Momentum Everywhere" JFE
    - research/hypotheses/37_g10_currency_carry.md

Universe: FXA (AUD), FXB (GBP), FXC (CAD), FXE (EUR), FXF (CHF), FXY (JPY)

FRED Rate Series:
    USD baseline : FEDFUNDS (effective federal funds rate)
    FXA (AUD)    : INTDSRAUM193N
    FXB (GBP)    : INTDSRGBM193N
    FXC (CAD)    : INTDSRCAM193N
    FXE (EUR)    : INTDSREUM193N
    FXF (CHF)    : INTDSRCHM193N
    FXY (JPY)    : INTDSRJPM193N

Data quality notes (FX-specific):
    - Survivorship bias: FXA, FXC, FXE, FXF, FXY remain actively traded through 2007-2021 IS.
      FXB (GBP ETF) was liquidated around 2019; data unavailable after that date. The strategy
      dynamically drops FXB from the ranking universe for periods where data is unavailable.
      No other ETFs in the universe are delisted within the IS window (2007-2021).
    - Price adjustments: yfinance auto_adjust=True for all ETFs.
    - Earnings exclusion: N/A — FX ETFs have no earnings events.
    - Data gaps: checked per ticker; flag if > 5 missing business days.

IS  window : 2007-01-01 to 2021-12-31
OOS window : 4 non-overlapping 36m IS / 6m OOS walk-forward windows
"""

import warnings
import itertools
import numpy as np
import pandas as pd
import yfinance as yf

# Attempt to import pandas_datareader for FRED rates
try:
    import pandas_datareader.data as web
    _PDR_AVAILABLE = True
except ImportError:
    _PDR_AVAILABLE = False
    warnings.warn(
        "pandas_datareader not available. All FRED rates will default to 0.0. "
        "Install with: pip install pandas-datareader"
    )

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "universe": ["FXA", "FXB", "FXC", "FXE", "FXF", "FXY"],
    "n_legs": 2,                  # top-N long candidates, bottom-N short candidates
    "sma_window": 60,             # 60-day (12-week) SMA momentum filter
    "vix_exit_threshold": 35,     # VIX > this triggers emergency exit at next open
    "hard_stop_pct": 0.08,        # -8% per position from entry price
    "long_book_pct": 0.50,        # 50% of NAV for long book
    "short_book_pct": 0.50,       # 50% of NAV for short book
    "init_cash": 25000,
}

# ── FRED Series Map ────────────────────────────────────────────────────────────
FRED_SERIES = {
    "USD": "FEDFUNDS",
    "FXA": "INTDSRAUM193N",
    "FXB": "INTDSRGBM193N",
    "FXC": "INTDSRCAM193N",
    "FXE": "INTDSREUM193N",
    "FXF": "INTDSRCHM193N",
    "FXY": "INTDSRJPM193N",
}

# ── Transaction Cost Constants (canonical equities/ETF model) ──────────────────
# Source: Engineering Director spec — Johnson, Algorithmic Trading & DMA (Book 6)
FIXED_COST_PER_SHARE = 0.005     # $0.005/share per leg
SLIPPAGE_PCT = 0.0005            # 0.05% per leg
MARKET_IMPACT_K = 0.1            # Almgren-Chriss square-root model coefficient
SIGMA_WINDOW = 20                # rolling vol window for σ in market impact
ADV_WINDOW = 20                  # rolling volume window for ADV in market impact
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data(
    universe: list,
    start: str,
    end: str,
    sma_window: int,
) -> tuple:
    """
    Download OHLCV for FX ETFs and ^VIX with warmup period for SMA computation.

    Warmup = sma_window × 2 + 60 calendar days (buffer for weekends/holidays).
    yfinance auto_adjust=True: prices adjusted for splits and distributions.

    Parameters
    ----------
    universe : list   FX ETF tickers (e.g. ["FXA","FXB","FXC","FXE","FXF","FXY"])
    start    : str    Backtest start date (YYYY-MM-DD)
    end      : str    Backtest end date (YYYY-MM-DD)
    sma_window : int  SMA window (determines warmup length)

    Returns
    -------
    close_df  (pd.DataFrame): Daily close prices (full warmup-inclusive series)
    open_df   (pd.DataFrame): Daily open prices (full warmup-inclusive series)
    volume_df (pd.DataFrame): Daily volume (full warmup-inclusive series)
    vix_series (pd.Series):   VIX close, aligned to close_df index, forward-filled
    """
    warmup_days = sma_window * 2 + 60
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_days)
    ).strftime("%Y-%m-%d")

    # Download FX ETFs
    all_tickers = sorted(set(universe))
    raw = yf.download(
        all_tickers, start=warmup_start, end=end, auto_adjust=True, progress=False
    )

    if isinstance(raw.columns, pd.MultiIndex):
        close_df = raw["Close"].copy()
        open_df = raw["Open"].copy()
        volume_df = raw["Volume"].copy()
    else:
        # Single-ticker fallback
        ticker = all_tickers[0]
        close_df = raw[["Close"]].rename(columns={"Close": ticker})
        open_df = raw[["Open"]].rename(columns={"Open": ticker})
        volume_df = raw[["Volume"]].rename(columns={"Volume": ticker})

    # Download ^VIX separately — close only
    vix_raw = yf.download("^VIX", start=warmup_start, end=end, auto_adjust=True, progress=False)
    if isinstance(vix_raw.columns, pd.MultiIndex):
        vix_raw.columns = vix_raw.columns.get_level_values(0)
    if "Close" not in vix_raw.columns:
        warnings.warn("^VIX download missing Close column; VIX exit filter disabled.")
        vix_series = pd.Series(np.nan, index=close_df.index)
    else:
        vix_series = vix_raw["Close"].reindex(close_df.index).ffill(limit=5)

    return close_df, open_df, volume_df, vix_series


def download_fred_rates(
    universe: list,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Download 3-month central bank rates from FRED via pandas_datareader.

    Returns a DataFrame with tickers + "USD" as columns, monthly frequency,
    representing the central bank policy rate (%) for each currency.

    Fallback: if pandas_datareader is unavailable, or a specific series fails,
    the rate for that ticker is set to 0.0 (logged as a warning).
    This means carry differentials for failed series will be 0.0 (neutral).

    Parameters
    ----------
    universe : list  FX ETF tickers (e.g. ["FXA","FXB","FXC","FXE","FXF","FXY"])
    start    : str   Start date (YYYY-MM-DD) — fetch with 3-month buffer
    end      : str   End date (YYYY-MM-DD)

    Returns
    -------
    pd.DataFrame  Columns = universe tickers + "USD", index = date (monthly),
                  values = central bank rate (%).
    """
    # Extend start by 6 months to ensure coverage at signal start
    fred_start = (pd.Timestamp(start) - pd.DateOffset(months=6)).strftime("%Y-%m-%d")

    rate_dict = {}
    tickers_to_fetch = universe + ["USD"]

    for ticker in tickers_to_fetch:
        series_id = FRED_SERIES.get(ticker)
        if series_id is None:
            warnings.warn(f"No FRED series defined for {ticker}; using 0.0")
            rate_dict[ticker] = None
            continue

        if not _PDR_AVAILABLE:
            rate_dict[ticker] = None
            continue

        try:
            raw = web.DataReader(series_id, "fred", fred_start, end)
            # FRED returns a DataFrame with the series_id as column; rename to ticker
            if isinstance(raw, pd.DataFrame):
                raw = raw.iloc[:, 0]
            rate_dict[ticker] = raw.rename(ticker)
        except Exception as exc:
            warnings.warn(
                f"FRED fetch failed for {ticker} (series={series_id}): {exc}. "
                f"Using 0.0 for this rate."
            )
            rate_dict[ticker] = None

    # Build combined DataFrame; backfill NaN rate series with 0.0
    frames = []
    for ticker in tickers_to_fetch:
        s = rate_dict.get(ticker)
        if s is None or (isinstance(s, pd.Series) and s.empty):
            # Fallback: 0.0 constant (no carry differential contribution)
            idx = pd.date_range(fred_start, end, freq="MS")
            frames.append(pd.Series(0.0, index=idx, name=ticker))
        else:
            frames.append(s.rename(ticker))

    rate_df = pd.concat(frames, axis=1)
    # Resample to month-end and forward-fill gaps (FRED data is sparse/monthly)
    rate_df = rate_df.resample("ME").last().ffill().fillna(0.0)

    return rate_df


# ── Data Quality Checklist ─────────────────────────────────────────────────────

def check_data_quality(close_df: pd.DataFrame, start: str, end: str) -> dict:
    """
    Run pre-backtest data quality checks per Engineering Director checklist.

    Documented decisions (FX-specific):
    - Survivorship bias: FXA (AUD ETF), FXC (CAD), FXE (EUR), FXF (CHF), FXY (JPY) remain
      actively traded through the full IS window 2007-2021. FXB (GBP ETF, ticker: FXB)
      was liquidated around 2019. If FXB data is unavailable after that date, the strategy
      dynamically excludes it from the ranking universe — no fictitious price backfills.
      Flag this explicitly in the report.
    - Price adjustments: yfinance auto_adjust=True.
    - Earnings exclusion: N/A — FX ETFs have no earnings events.
    - Data gaps: checked per ticker; flag if > 5 missing business days in window.
    """
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    report = {
        "survivorship_bias": (
            "FXA (AUD): active through full IS window. "
            "FXC (CAD): active through full IS window. "
            "FXE (EUR): active through full IS window. "
            "FXF (CHF): active through full IS window. "
            "FXY (JPY): active through full IS window. "
            "FXB (GBP): ETF was LIQUIDATED ~2019. Data may be unavailable after that date. "
            "FXB is dynamically excluded from the ranking universe when data is missing — "
            "no fictitious price backfills are used. This creates a 5-ETF universe for "
            "the post-2019 portion of the IS window. Flag: SURVIVORSHIP_RISK_FXB."
        ),
        "price_adjustments": "yfinance auto_adjust=True for all ETFs.",
        "earnings_exclusion": "N/A — FX ETFs have no earnings events.",
        "delisted_tickers": (
            "FXB (GBP ETF) potentially delisted ~2019. All other ETFs remain active. "
            "Dynamic exclusion implemented in signal computation."
        ),
        "tickers": {},
    }

    for ticker in close_df.columns:
        price = close_df[ticker]
        price_full = price.dropna()

        if price_full.empty:
            report["tickers"][ticker] = {"error": "No data returned by yfinance"}
            continue

        price_window = price.loc[ts_start:ts_end].dropna()
        if price_window.empty:
            report["tickers"][ticker] = {
                "note": f"No data in backtest window {start}–{end}",
                "data_start": str(price_full.index.min().date()),
                "data_end": str(price_full.index.max().date()),
                "fxb_delisted": ticker == "FXB",
            }
            continue

        expected_bdays = pd.bdate_range(
            start=price_window.index.min(), end=price_window.index.max()
        )
        missing_count = len(expected_bdays.difference(price_window.index))

        report["tickers"][ticker] = {
            "bars_in_window": len(price_window),
            "missing_business_days": missing_count,
            "gap_flag": missing_count > 5,
            "data_start": str(price_full.index.min().date()),
            "data_end": str(price_full.index.max().date()),
            "available_at_is_start": bool(price_full.index.min() <= ts_start),
            "fxb_delisted": ticker == "FXB" and price_full.index.max() < pd.Timestamp("2021-01-01"),
        }

        if missing_count > 5:
            warnings.warn(
                f"Data gap: {ticker} has {missing_count} missing business days "
                f"in window {start}–{end}"
            )

        if ticker == "FXB" and price_full.index.max() < pd.Timestamp("2021-01-01"):
            warnings.warn(
                f"FXB (GBP ETF): data ends {price_full.index.max().date()}. "
                f"ETF was liquidated ~2019. FXB will be excluded from ranking after "
                f"its last available data date."
            )

    return report


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_carry_momentum_signal(
    close_df: pd.DataFrame,
    rate_df: pd.DataFrame,
    params: dict,
) -> dict:
    """
    Compute monthly carry + momentum signal for G10 currency carry strategy.

    Signal evaluation at month-end close (signal_date), execution at next trading
    day OPEN (no look-ahead bias). Signals are dict keyed by signal_date.

    Algorithm (per month-end):
    1. Get FRED rate differential for each available ETF = rate_etf - rate_USD.
    2. Rank all available ETFs by differential, descending.
    3. Top-n_legs = long candidates; bottom-n_legs = short candidates.
    4. Momentum filter:
       - Long candidate: include only if ETF close > 60-day SMA (confirmed uptrend).
       - Short candidate: include only if ETF close < 60-day SMA (confirmed downtrend).
       - If not confirmed: skip that leg (go flat on that slot).
    5. Result: {'long': [confirmed longs], 'short': [confirmed shorts]}

    FXB dynamic exclusion: if FXB has NaN close on the signal date, it is excluded
    from the ranking for that month — no imputation, no backfill.

    Parameters
    ----------
    close_df  : pd.DataFrame  Warmup-inclusive daily close prices
    rate_df   : pd.DataFrame  Monthly FRED rates (columns = universe + "USD")
    params    : dict          Strategy parameters (n_legs, sma_window, universe)

    Returns
    -------
    dict  {pd.Timestamp(month_end_date): {'long': [tickers], 'short': [tickers]}}
          Only month-end dates are keys; caller must forward-fill to daily execution dates.
    """
    n_legs = int(params.get("n_legs", 2))
    sma_window = int(params.get("sma_window", 60))
    universe = list(params.get("universe", []))

    # Compute 60-day SMA on warmup-inclusive series (no NaN at backtest window start)
    sma_df = close_df[universe].rolling(sma_window).mean()

    # Identify month-end trading days within close_df
    month_end_dates = close_df.resample("ME").last().index
    # Only keep months that are actual trading days
    actual_month_ends = [d for d in month_end_dates if d in close_df.index]

    signals = {}

    for me_date in actual_month_ends:
        # Get USD rate at or before this month-end
        rate_slice = rate_df.loc[:me_date]
        if rate_slice.empty:
            continue

        latest_rates = rate_slice.iloc[-1]
        usd_rate = latest_rates.get("USD", 0.0)
        if pd.isna(usd_rate):
            usd_rate = 0.0

        # Compute carry differential for each available ETF
        differentials = {}
        for ticker in universe:
            # Skip if no close data on this date (e.g. FXB after delisting)
            if ticker not in close_df.columns:
                continue
            close_val = close_df[ticker].loc[me_date] if me_date in close_df.index else np.nan
            if pd.isna(close_val):
                continue  # Dynamically exclude (FXB delisting handling)

            etf_rate = latest_rates.get(ticker, 0.0)
            if pd.isna(etf_rate):
                etf_rate = 0.0

            differentials[ticker] = etf_rate - usd_rate

        if len(differentials) < 2:
            signals[me_date] = {"long": [], "short": []}
            continue

        # Rank by differential descending
        sorted_tickers = sorted(differentials, key=lambda t: differentials[t], reverse=True)
        n_avail = len(sorted_tickers)
        actual_legs = min(n_legs, n_avail // 2)  # Ensure we have enough for both sides

        if actual_legs < 1:
            signals[me_date] = {"long": [], "short": []}
            continue

        long_candidates = sorted_tickers[:actual_legs]
        short_candidates = sorted_tickers[n_avail - actual_legs:]

        # Momentum filter — confirm each leg
        confirmed_long = []
        for ticker in long_candidates:
            if ticker not in sma_df.columns:
                continue
            sma_val = sma_df[ticker].loc[me_date] if me_date in sma_df.index else np.nan
            close_val = close_df[ticker].loc[me_date] if me_date in close_df.index else np.nan
            if pd.notna(sma_val) and pd.notna(close_val) and close_val > sma_val:
                confirmed_long.append(ticker)
            # If not confirmed: skip leg (go flat on that slot)

        confirmed_short = []
        for ticker in short_candidates:
            if ticker not in sma_df.columns:
                continue
            sma_val = sma_df[ticker].loc[me_date] if me_date in sma_df.index else np.nan
            close_val = close_df[ticker].loc[me_date] if me_date in close_df.index else np.nan
            if pd.notna(sma_val) and pd.notna(close_val) and close_val < sma_val:
                confirmed_short.append(ticker)
            # If not confirmed: skip leg (go flat on that slot)

        signals[me_date] = {"long": confirmed_long, "short": confirmed_short}

    return signals


def _signals_to_daily(
    monthly_signals: dict,
    trading_index: pd.DatetimeIndex,
) -> pd.Series:
    """
    Convert monthly signal dict to a daily Series aligned to trading_index.

    Each month-end signal is forward-filled to the next month-end (execution on
    next trading day after signal date). The signal is SHIFTED +1 bar to ensure
    execution at next trading day OPEN (no look-ahead).

    Returns
    -------
    pd.Series  Index = trading_index; values = signal dicts {'long': [...], 'short': [...]}
               None for dates before first signal.
    """
    # Place signals at month-end dates; forward-fill through the month
    signal_series = pd.Series(index=trading_index, dtype=object)

    for date, sig in monthly_signals.items():
        # Find the exact trading day for this date (or nearest)
        if date in signal_series.index:
            signal_series.loc[date] = sig

    # Forward-fill: carry signal from month-end through subsequent trading days
    # (ffill on object dtype requires explicit fill)
    filled = [None] * len(signal_series)
    last_val = None
    for i, (idx, val) in enumerate(signal_series.items()):
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            last_val = val
        filled[i] = last_val
    signal_ffill = pd.Series(filled, index=trading_index)

    # Shift +1 bar: month-end signal → next trading day execution (no look-ahead)
    signal_shifted = signal_ffill.shift(1)

    return signal_shifted


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _compute_etf_tc(
    price: float,
    shares: float,
    volume_df: pd.DataFrame,
    close_df: pd.DataFrame,
    i: int,
    etf: str,
    direction: str,
) -> tuple:
    """
    Canonical equities/ETF transaction cost model (Engineering Director spec).

    Components:
    - Fixed cost  : $0.005/share per leg
    - Slippage    : 0.05% of notional per leg
    - Market impact: 0.1 × σ × sqrt(Q / ADV)
      where σ = 20-day rolling daily return std (annualized to daily → keep raw)
            Q = shares traded
            ADV = 20-day avg daily volume
    - Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True

    Effective price convention:
    - Long buy  : eff_entry = price × (1 + slippage_pct) + fixed_cost/shares + market_impact/shares
    - Short sell: eff_entry = price × (1 - slippage_pct) - fixed_cost/shares - market_impact/shares
    - Close (sell/cover): reverse of above

    Parameters
    ----------
    price      : float  Raw execution price
    shares     : float  Number of shares (positive)
    volume_df  : pd.DataFrame  Daily volumes (columns = tickers)
    close_df   : pd.DataFrame  Daily closes (columns = tickers)
    i          : int    Current bar index
    etf        : str    Ticker symbol
    direction  : str    "long_open" | "long_close" | "short_open" | "short_close"

    Returns
    -------
    eff_price            : float  Cost-adjusted execution price
    total_cost           : float  Total dollar cost (all components, positive)
    liquidity_constrained: bool   True if Q/ADV > 0.01
    """
    # ── Market impact: σ and ADV ───────────────────────────────────────────────
    sigma = 0.0
    adv = 1e6  # default high ADV (no impact) if data unavailable

    if etf in close_df.columns and i >= SIGMA_WINDOW:
        close_slice = close_df[etf].iloc[max(0, i - SIGMA_WINDOW):i]
        rets = close_slice.pct_change().dropna()
        if len(rets) >= 5:
            sigma = float(rets.std())

    if etf in volume_df.columns and i >= ADV_WINDOW:
        vol_slice = volume_df[etf].iloc[max(0, i - ADV_WINDOW):i].dropna()
        if len(vol_slice) >= 5:
            adv = float(vol_slice.mean())
            if adv < 1:
                adv = 1.0  # guard against zero

    liquidity_constrained = bool(shares / adv > 0.01)
    market_impact_per_share = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) if adv > 0 else 0.0

    fixed_per_share = FIXED_COST_PER_SHARE
    slippage_per_share = SLIPPAGE_PCT * price
    total_cost_per_share = fixed_per_share + slippage_per_share + market_impact_per_share
    total_cost = total_cost_per_share * shares

    if direction == "long_open":
        # Buy: pay higher price
        eff_price = price * (1 + SLIPPAGE_PCT) + fixed_per_share + market_impact_per_share
    elif direction == "long_close":
        # Sell to close long: receive lower price
        eff_price = price * (1 - SLIPPAGE_PCT) - fixed_per_share - market_impact_per_share
    elif direction == "short_open":
        # Short sell: receive lower price (cost reduces proceeds)
        eff_price = price * (1 - SLIPPAGE_PCT) - fixed_per_share - market_impact_per_share
    elif direction == "short_close":
        # Cover short: pay higher price
        eff_price = price * (1 + SLIPPAGE_PCT) + fixed_per_share + market_impact_per_share
    else:
        raise ValueError(f"Unknown direction: {direction}")

    return eff_price, total_cost, liquidity_constrained


# ── Simulation Engine ──────────────────────────────────────────────────────────

def simulate_h37(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    vix_series: pd.Series,
    monthly_signal: dict,
    params: dict,
) -> tuple:
    """
    Simulate H37 G10 Currency Carry with monthly rebalancing.

    Execution rules:
    - Monthly rebalance: signal set at month-end close → execute at next trading day OPEN.
    - VIX emergency exit: if today's VIX close > threshold → set pending_vix_exit flag;
      execute full exit at next open.
    - Hard stop: check long positions at close (close ≤ entry × 0.92 → exit at that close).
      Check short positions at close (close ≥ entry × 1.08 → exit at that close).
      Execute at the stop threshold price (conservative — assumes fill at stop, not worse).
    - End of data: force-close all positions at last close.

    Position sizing:
    - Long book  = long_book_pct  × NAV, equally divided among confirmed long legs.
    - Short book = short_book_pct × NAV, equally divided among confirmed short legs.
    - Integer shares: floor(allocation / price).
    - Residual cash (from rounding and unconfirmed legs) held as cash.

    NAV tracking:
    - NAV = init_cash + realized_pnl + unrealized_pnl
    - Long PnL  = shares × (eff_exit - eff_entry)
    - Short PnL = shares × (eff_entry - eff_exit)   [profit when price falls]

    Parameters
    ----------
    close_df       : pd.DataFrame  Daily closes (backtest window, trimmed)
    open_df        : pd.DataFrame  Daily opens (backtest window, trimmed)
    volume_df      : pd.DataFrame  Daily volumes (backtest window, trimmed)
    vix_series     : pd.Series     VIX daily close, aligned to close_df index
    monthly_signal : dict          {month_end_date: {'long': [...], 'short': [...]}}
    params         : dict          Strategy parameters

    Returns
    -------
    trade_log  : list of dicts  (see Trade log fields in module docstring)
    equity     : pd.Series      Daily NAV
    daily_df   : pd.DataFrame   Date-indexed; columns: position, equity, long_pos, short_pos
    """
    n_legs = int(params.get("n_legs", 2))
    vix_threshold = float(params.get("vix_exit_threshold", 35))
    hard_stop_pct = float(params.get("hard_stop_pct", 0.08))
    long_book_pct = float(params.get("long_book_pct", 0.50))
    short_book_pct = float(params.get("short_book_pct", 0.50))
    init_cash = float(params["init_cash"])

    # Build daily signal series from monthly signal dict
    daily_signal = _signals_to_daily(monthly_signal, close_df.index)

    dates = close_df.index
    n = len(dates)

    trade_log = []
    daily_records = []

    # Cash tracking: realized_pnl accumulates; unrealized computed daily
    cash = init_cash
    realized_pnl = 0.0

    # Positions:
    #   longs  = {ticker: {shares, entry_fill, entry_eff, entry_cost, entry_date, entry_bar}}
    #   shorts = {ticker: {shares, entry_fill, entry_eff, entry_cost, entry_date, entry_bar}}
    longs: dict = {}
    shorts: dict = {}

    # VIX exit flag: set when VIX close > threshold; execute at next open
    pending_vix_exit = False

    # Track current target signal for rebalance detection
    current_target = {"long": [], "short": []}

    for i in range(n):
        date = dates[i]

        # ── Get today's signal ─────────────────────────────────────────────────
        raw_signal = daily_signal.iloc[i]
        if raw_signal is None or (isinstance(raw_signal, float) and np.isnan(raw_signal)):
            desired_long = []
            desired_short = []
        else:
            desired_long = list(raw_signal.get("long", []))
            desired_short = list(raw_signal.get("short", []))

        # ── VIX emergency exit (execute at today's OPEN) ───────────────────────
        if pending_vix_exit:
            # Exit all positions at today's open
            for ticker in sorted(list(longs.keys())):
                pos = longs[ticker]
                if ticker in open_df.columns and i > pos["entry_bar"]:
                    open_price = float(open_df[ticker].iloc[i])
                    if open_price > 0 and not pd.isna(open_price):
                        eff_xp, xcost, xliq = _compute_etf_tc(
                            open_price, pos["shares"], volume_df, close_df, i, ticker, "long_close"
                        )
                        pnl = pos["shares"] * (eff_xp - pos["entry_eff"])
                        cash += eff_xp * pos["shares"]
                        realized_pnl += pnl
                        trade_log.append(_make_trade_record(
                            pos, date, open_price, eff_xp, xcost, pnl, i, "VIX_EXIT", xliq
                        ))
            longs.clear()

            for ticker in sorted(list(shorts.keys())):
                pos = shorts[ticker]
                if ticker in open_df.columns and i > pos["entry_bar"]:
                    open_price = float(open_df[ticker].iloc[i])
                    if open_price > 0 and not pd.isna(open_price):
                        eff_xp, xcost, xliq = _compute_etf_tc(
                            open_price, pos["shares"], volume_df, close_df, i, ticker, "short_close"
                        )
                        pnl = pos["shares"] * (pos["entry_eff"] - eff_xp)
                        cash -= eff_xp * pos["shares"]             # pay cover cost (proceeds already in cash)
                        realized_pnl += pnl
                        trade_log.append(_make_trade_record(
                            pos, date, open_price, eff_xp, xcost, pnl, i, "VIX_EXIT", xliq,
                            direction="short"
                        ))
            shorts.clear()

            pending_vix_exit = False
            desired_long = []
            desired_short = []
            current_target = {"long": [], "short": []}

        # ── Monthly rebalance: compute NAV, exit stale, enter new ─────────────
        desired_long_set = frozenset(desired_long)
        desired_short_set = frozenset(desired_short)
        current_long_set = frozenset(longs.keys())
        current_short_set = frozenset(shorts.keys())

        needs_rebalance = (
            desired_long_set != current_long_set or
            desired_short_set != current_short_set
        )

        if needs_rebalance:
            # ── Exit stale longs at today's OPEN ──────────────────────────────
            to_exit_long = current_long_set - desired_long_set
            for ticker in sorted(to_exit_long):
                pos = longs[ticker]
                if ticker in open_df.columns and i > pos["entry_bar"]:
                    open_price = float(open_df[ticker].iloc[i])
                    if open_price > 0 and not pd.isna(open_price):
                        eff_xp, xcost, xliq = _compute_etf_tc(
                            open_price, pos["shares"], volume_df, close_df, i, ticker, "long_close"
                        )
                        pnl = pos["shares"] * (eff_xp - pos["entry_eff"])
                        cash += eff_xp * pos["shares"]
                        realized_pnl += pnl
                        trade_log.append(_make_trade_record(
                            pos, date, open_price, eff_xp, xcost, pnl, i, "REBALANCE", xliq
                        ))
                        del longs[ticker]

            # ── Exit stale shorts at today's OPEN ─────────────────────────────
            to_exit_short = current_short_set - desired_short_set
            for ticker in sorted(to_exit_short):
                pos = shorts[ticker]
                if ticker in open_df.columns and i > pos["entry_bar"]:
                    open_price = float(open_df[ticker].iloc[i])
                    if open_price > 0 and not pd.isna(open_price):
                        eff_xp, xcost, xliq = _compute_etf_tc(
                            open_price, pos["shares"], volume_df, close_df, i, ticker, "short_close"
                        )
                        pnl = pos["shares"] * (pos["entry_eff"] - eff_xp)
                        cash -= eff_xp * pos["shares"]             # pay cover cost (proceeds already in cash)
                        realized_pnl += pnl
                        trade_log.append(_make_trade_record(
                            pos, date, open_price, eff_xp, xcost, pnl, i, "REBALANCE", xliq,
                            direction="short"
                        ))
                        del shorts[ticker]

            # ── Compute current NAV for position sizing ────────────────────────
            nav = _compute_nav(cash, longs, shorts, close_df, open_df, i)

            # ── Enter new longs at today's OPEN ───────────────────────────────
            to_enter_long = desired_long_set - frozenset(longs.keys())
            if to_enter_long and len(desired_long) > 0:
                per_leg_alloc = nav * long_book_pct / len(desired_long)
                for ticker in sorted(to_enter_long):
                    if ticker in open_df.columns and cash > 0:
                        open_price = float(open_df[ticker].iloc[i])
                        if open_price > 0 and not pd.isna(open_price):
                            alloc = min(per_leg_alloc, cash)
                            shares = int(alloc / open_price)  # integer shares (floor)
                            if shares < 1:
                                continue
                            eff_ep, ecost, eliq = _compute_etf_tc(
                                open_price, shares, volume_df, close_df, i, ticker, "long_open"
                            )
                            cash -= eff_ep * shares
                            longs[ticker] = {
                                "ticker": ticker,
                                "shares": shares,
                                "entry_fill": open_price,
                                "entry_eff": eff_ep,
                                "entry_cost": ecost,
                                "entry_date": date,
                                "entry_bar": i,
                                "direction": "long",
                                "liquidity_constrained": eliq,
                            }

            # ── Enter new shorts at today's OPEN ──────────────────────────────
            to_enter_short = desired_short_set - frozenset(shorts.keys())
            if to_enter_short and len(desired_short) > 0:
                per_leg_alloc = nav * short_book_pct / len(desired_short)
                for ticker in sorted(to_enter_short):
                    if ticker in open_df.columns and cash > 0:
                        open_price = float(open_df[ticker].iloc[i])
                        if open_price > 0 and not pd.isna(open_price):
                            alloc = min(per_leg_alloc, cash)
                            shares = int(alloc / open_price)  # integer shares (floor)
                            if shares < 1:
                                continue
                            eff_ep, ecost, eliq = _compute_etf_tc(
                                open_price, shares, volume_df, close_df, i, ticker, "short_open"
                            )
                            # Short sell: receive proceeds (eff_ep already cost-adjusted)
                            cash += eff_ep * shares
                            shorts[ticker] = {
                                "ticker": ticker,
                                "shares": shares,
                                "entry_fill": open_price,
                                "entry_eff": eff_ep,
                                "entry_cost": ecost,
                                "entry_date": date,
                                "entry_bar": i,
                                "direction": "short",
                                "liquidity_constrained": eliq,
                            }

            current_target = {"long": list(desired_long_set), "short": list(desired_short_set)}

        # ── Hard stop check at today's CLOSE ──────────────────────────────────
        # Long stops: exit if close ≤ entry × (1 - hard_stop_pct)
        for ticker in sorted(list(longs.keys())):
            pos = longs[ticker]
            if ticker in close_df.columns:
                close_i = float(close_df[ticker].iloc[i])
                stop_threshold = pos["entry_fill"] * (1.0 - hard_stop_pct)
                if not pd.isna(close_i) and close_i <= stop_threshold:
                    stop_fill = stop_threshold  # conservative: fill at stop price
                    eff_xp, xcost, xliq = _compute_etf_tc(
                        stop_fill, pos["shares"], volume_df, close_df, i, ticker, "long_close"
                    )
                    pnl = pos["shares"] * (eff_xp - pos["entry_eff"])
                    cash += eff_xp * pos["shares"]
                    realized_pnl += pnl
                    trade_log.append(_make_trade_record(
                        pos, date, stop_fill, eff_xp, xcost, pnl, i, "HARD_STOP", xliq
                    ))
                    del longs[ticker]

        # Short stops: exit if close ≥ entry × (1 + hard_stop_pct)
        for ticker in sorted(list(shorts.keys())):
            pos = shorts[ticker]
            if ticker in close_df.columns:
                close_i = float(close_df[ticker].iloc[i])
                stop_threshold = pos["entry_fill"] * (1.0 + hard_stop_pct)
                if not pd.isna(close_i) and close_i >= stop_threshold:
                    stop_fill = stop_threshold  # conservative: fill at stop price
                    eff_xp, xcost, xliq = _compute_etf_tc(
                        stop_fill, pos["shares"], volume_df, close_df, i, ticker, "short_close"
                    )
                    pnl = pos["shares"] * (pos["entry_eff"] - eff_xp)
                    cash -= eff_xp * pos["shares"]             # pay cover cost (proceeds already in cash)
                    realized_pnl += pnl
                    trade_log.append(_make_trade_record(
                        pos, date, stop_fill, eff_xp, xcost, pnl, i, "HARD_STOP", xliq,
                        direction="short"
                    ))
                    del shorts[ticker]

        # ── VIX close check: set pending_vix_exit for next open ───────────────
        vix_today = vix_series.iloc[i] if i < len(vix_series) else np.nan
        if not pd.isna(vix_today) and float(vix_today) > vix_threshold:
            if longs or shorts:  # only flag if we have positions
                pending_vix_exit = True

        # ── Daily mark-to-market NAV ───────────────────────────────────────────
        nav_today = _compute_nav(cash, longs, shorts, close_df, close_df, i)

        long_pos_str = ",".join(sorted(longs.keys())) if longs else ""
        short_pos_str = ",".join(sorted(shorts.keys())) if shorts else ""
        pos_str = f"L:{long_pos_str}|S:{short_pos_str}" if (longs or shorts) else "FLAT"

        daily_records.append({
            "date": date,
            "position": pos_str,
            "equity": nav_today,
            "long_pos": long_pos_str,
            "short_pos": short_pos_str,
            "vix": float(vix_today) if not pd.isna(vix_today) else np.nan,
        })

    # ── Force-close all open positions at end of data ─────────────────────────
    if (longs or shorts) and n > 0:
        i = n - 1
        date_f = dates[i]

        for ticker in sorted(list(longs.keys())):
            pos = longs[ticker]
            if ticker in close_df.columns:
                close_f = float(close_df[ticker].iloc[i])
                if not pd.isna(close_f) and close_f > 0:
                    eff_xp, xcost, xliq = _compute_etf_tc(
                        close_f, pos["shares"], volume_df, close_df, i, ticker, "long_close"
                    )
                    pnl = pos["shares"] * (eff_xp - pos["entry_eff"])
                    cash += eff_xp * pos["shares"]
                    realized_pnl += pnl
                    trade_log.append(_make_trade_record(
                        pos, date_f, close_f, eff_xp, xcost, pnl, i, "END_OF_DATA", xliq
                    ))

        for ticker in sorted(list(shorts.keys())):
            pos = shorts[ticker]
            if ticker in close_df.columns:
                close_f = float(close_df[ticker].iloc[i])
                if not pd.isna(close_f) and close_f > 0:
                    eff_xp, xcost, xliq = _compute_etf_tc(
                        close_f, pos["shares"], volume_df, close_df, i, ticker, "short_close"
                    )
                    pnl = pos["shares"] * (pos["entry_eff"] - eff_xp)
                    cash -= eff_xp * pos["shares"]             # pay cover cost (proceeds already in cash)
                    realized_pnl += pnl
                    trade_log.append(_make_trade_record(
                        pos, date_f, close_f, eff_xp, xcost, pnl, i, "END_OF_DATA", xliq,
                        direction="short"
                    ))

        if daily_records:
            daily_records[-1]["equity"] = cash  # final equity = cash (all positions closed)

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")

    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df


def _compute_nav(
    cash: float,
    longs: dict,
    shorts: dict,
    close_df: pd.DataFrame,
    price_df: pd.DataFrame,
    i: int,
) -> float:
    """
    Compute current NAV = cash + unrealized long MTM - unrealized short MTM.

    Long MTM  : mark positions at current price (gain if price rises)
    Short MTM : mark positions at current price (gain if price falls;
                short PnL = entry_eff - current_price per share)
    """
    nav = cash

    for ticker, pos in longs.items():
        if ticker in close_df.columns:
            price_i = float(close_df[ticker].iloc[i])
            if not pd.isna(price_i):
                nav += pos["shares"] * price_i
            else:
                nav += pos["shares"] * pos["entry_fill"]  # fallback to entry price

    for ticker, pos in shorts.items():
        if ticker in close_df.columns:
            price_i = float(close_df[ticker].iloc[i])
            if not pd.isna(price_i):
                # Short liability: proceeds (entry_eff × shares) already in cash;
                # deduct current liability = shares × current_price
                nav -= pos["shares"] * price_i
            # If NaN: no adjustment (assume unrealized PnL = 0)

    return nav


def _make_trade_record(
    pos: dict,
    exit_date,
    exit_price: float,
    exit_eff: float,
    exit_cost: float,
    pnl: float,
    exit_bar: int,
    exit_reason: str,
    liquidity_constrained: bool,
    direction: str = "long",
) -> dict:
    """Build a standardized trade log record."""
    entry_eff = pos["entry_eff"]
    entry_fill = pos["entry_fill"]
    shares = pos["shares"]
    hold_days = exit_bar - pos["entry_bar"]

    if direction == "long":
        return_pct = (exit_eff - entry_eff) / (entry_eff + 1e-10)
    else:
        return_pct = (entry_eff - exit_eff) / (entry_eff + 1e-10)

    return {
        "entry_date": pos["entry_date"].date() if hasattr(pos["entry_date"], "date") else pos["entry_date"],
        "exit_date": exit_date.date() if hasattr(exit_date, "date") else exit_date,
        "asset": pos.get("ticker", ""),  # filled by caller context if needed
        "direction": direction,
        "entry_price": round(float(entry_fill), 6),
        "entry_eff": round(float(entry_eff), 6),
        "exit_price": round(float(exit_price), 6),
        "exit_eff": round(float(exit_eff), 6),
        "shares": float(shares),
        "pnl": round(float(pnl), 2),
        "return_pct": round(float(return_pct), 6),
        "entry_cost": round(float(pos["entry_cost"]), 4),
        "exit_cost": round(float(exit_cost), 4),
        "transaction_cost": round(float(pos["entry_cost"] + exit_cost), 4),
        "liquidity_constrained": bool(liquidity_constrained or pos.get("liquidity_constrained", False)),
        "hold_days": int(hold_days),
        "exit_reason": exit_reason,
    }


# ── Performance Metrics ────────────────────────────────────────────────────────

def _compute_metrics(
    equity: pd.Series,
    trades_df: pd.DataFrame,
    start: str,
    end: str,
) -> dict:
    """
    Compute standard Gate 1 performance metrics from equity curve and trade log.

    Metrics:
    - Sharpe = mean(daily_return) / std(daily_return) × sqrt(252)
    - MDD    = min((cum - roll_max) / roll_max)
    - Win rate     = fraction of trades with pnl > 0
    - Profit factor = sum(winning pnl) / sum(|losing pnl|)
    """
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)
    years = max((ts_end - ts_start).days / 365.25, 1e-3)

    n_trades = len(trades_df)
    trades_per_year = round(n_trades / years, 1)

    daily_returns = equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values

    sharpe = 0.0
    if len(ret_arr) > 1 and ret_arr.std() > 1e-10:
        sharpe = round(
            float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4
        )

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    win_rate = 0.0
    profit_factor = 0.0
    if n_trades > 0 and "pnl" in trades_df.columns:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        gross_wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        gross_losses = abs(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum())
        profit_factor = round(float(gross_wins / max(gross_losses, 1e-8)), 4)

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
    }


# ── Walk-Forward Engine ────────────────────────────────────────────────────────

def run_walk_forward(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    vix_series: pd.Series,
    rate_df: pd.DataFrame,
    params: dict,
) -> list:
    """
    Run 4-window walk-forward validation.

    Windows (36m IS / 6m OOS):
      W1: IS 2007-01-01 to 2009-12-31 | OOS 2010-01-01 to 2010-06-30
      W2: IS 2010-07-01 to 2013-06-30 | OOS 2013-07-01 to 2013-12-31
      W3: IS 2014-01-01 to 2016-12-31 | OOS 2017-01-01 to 2017-06-30
      W4: IS 2017-07-01 to 2020-06-30 | OOS 2020-07-01 to 2020-12-31

    Each window:
    1. Fit signal on IS data (signal computed on full warmup series; IS-trimmed).
    2. Evaluate on OOS data using IS-derived signal continuation (same rate_df).
    3. Report IS and OOS metrics.

    Returns
    -------
    list of dicts, one per window:
        {window, is_start, is_end, oos_start, oos_end,
         is_sharpe, oos_sharpe, is_mdd, oos_mdd,
         is_trade_count, oos_trade_count, is_metrics, oos_metrics}
    """
    windows = [
        {"window": "W1", "is_start": "2007-01-01", "is_end": "2009-12-31",
         "oos_start": "2010-01-01", "oos_end": "2010-06-30"},
        {"window": "W2", "is_start": "2010-07-01", "is_end": "2013-06-30",
         "oos_start": "2013-07-01", "oos_end": "2013-12-31"},
        {"window": "W3", "is_start": "2014-01-01", "is_end": "2016-12-31",
         "oos_start": "2017-01-01", "oos_end": "2017-06-30"},
        {"window": "W4", "is_start": "2017-07-01", "is_end": "2020-06-30",
         "oos_start": "2020-07-01", "oos_end": "2020-12-31"},
    ]

    results = []

    for w in windows:
        print(
            f"  Walk-forward {w['window']}: IS {w['is_start']}–{w['is_end']} | "
            f"OOS {w['oos_start']}–{w['oos_end']}"
        )

        try:
            # Signal is computed on full (warmup-inclusive) close_df
            # Then trimmed separately for IS and OOS windows
            monthly_signal_full = compute_carry_momentum_signal(close_df, rate_df, params)

            def _run_window(wstart, wend):
                ts_s = pd.Timestamp(wstart)
                ts_e = pd.Timestamp(wend)
                mask = (close_df.index >= ts_s) & (close_df.index <= ts_e)
                c = close_df.loc[mask].copy()
                o = open_df.loc[mask].copy()
                v = volume_df.loc[mask].copy()
                vix = vix_series.loc[mask]
                if len(c) < 10:
                    return None
                # Subset monthly_signal to this window
                win_signal = {
                    d: s for d, s in monthly_signal_full.items()
                    if ts_s <= d <= ts_e
                }
                tlog, eq, ddf = simulate_h37(c, o, v, vix, win_signal, params)
                empty_cols = [
                    "entry_date", "exit_date", "asset", "direction", "entry_price",
                    "entry_eff", "exit_price", "exit_eff", "shares", "pnl", "return_pct",
                    "entry_cost", "exit_cost", "transaction_cost", "liquidity_constrained",
                    "hold_days", "exit_reason",
                ]
                td = pd.DataFrame(tlog) if tlog else pd.DataFrame(columns=empty_cols)
                m = _compute_metrics(eq, td, wstart, wend)
                return m

            is_m = _run_window(w["is_start"], w["is_end"])
            oos_m = _run_window(w["oos_start"], w["oos_end"])

            results.append({
                "window": w["window"],
                "is_start": w["is_start"],
                "is_end": w["is_end"],
                "oos_start": w["oos_start"],
                "oos_end": w["oos_end"],
                "is_sharpe": is_m["sharpe"] if is_m else np.nan,
                "oos_sharpe": oos_m["sharpe"] if oos_m else np.nan,
                "is_mdd": is_m["max_drawdown"] if is_m else np.nan,
                "oos_mdd": oos_m["max_drawdown"] if oos_m else np.nan,
                "is_trade_count": is_m["trade_count"] if is_m else 0,
                "oos_trade_count": oos_m["trade_count"] if oos_m else 0,
                "is_metrics": is_m,
                "oos_metrics": oos_m,
            })

            print(
                f"    IS  Sharpe: {results[-1]['is_sharpe']:.4f} | "
                f"MDD: {results[-1]['is_mdd']:.2%} | "
                f"Trades: {results[-1]['is_trade_count']}"
            )
            print(
                f"    OOS Sharpe: {results[-1]['oos_sharpe']:.4f} | "
                f"MDD: {results[-1]['oos_mdd']:.2%} | "
                f"Trades: {results[-1]['oos_trade_count']}"
            )

        except Exception as exc:
            warnings.warn(f"Walk-forward {w['window']} failed: {exc}")
            results.append({
                "window": w["window"],
                **{k: np.nan for k in [
                    "is_sharpe", "oos_sharpe", "is_mdd", "oos_mdd"
                ]},
                "is_trade_count": 0,
                "oos_trade_count": 0,
                "is_metrics": None,
                "oos_metrics": None,
                "error": str(exc),
            })

    return results


# ── Sensitivity Sweep ──────────────────────────────────────────────────────────

def _run_sensitivity_sweep(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    vix_series: pd.Series,
    rate_df: pd.DataFrame,
    params: dict,
    start: str,
    end: str,
) -> list:
    """
    Sensitivity sweep over key parameters:
        n_legs    : [1, 2, 3]
        sma_window: [40, 60, 80]
        vix_exit  : [28, 35, 40]

    Total combinations: 3 × 3 × 3 = 27.
    Each combination runs a full backtest on the IS window.

    Returns list of dicts with parameter values + IS metrics.
    """
    sweep_results = []
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)
    mask = (close_df.index >= ts_start) & (close_df.index <= ts_end)
    c_trim = close_df.loc[mask].copy()
    o_trim = open_df.loc[mask].copy()
    v_trim = volume_df.loc[mask].copy()
    vix_trim = vix_series.loc[mask]

    for n_legs, sma_win, vix_thr in itertools.product([1, 2, 3], [40, 60, 80], [28, 35, 40]):
        sweep_params = params.copy()
        sweep_params["n_legs"] = n_legs
        sweep_params["sma_window"] = sma_win
        sweep_params["vix_exit_threshold"] = vix_thr

        try:
            # Recompute SMA-dependent signal with new sma_window
            msig = compute_carry_momentum_signal(close_df, rate_df, sweep_params)
            # Filter to IS window
            msig_is = {d: s for d, s in msig.items() if ts_start <= d <= ts_end}

            tlog, eq, _ = simulate_h37(c_trim, o_trim, v_trim, vix_trim, msig_is, sweep_params)
            empty_cols = ["pnl"]
            td = pd.DataFrame(tlog) if tlog else pd.DataFrame(columns=empty_cols)
            m = _compute_metrics(eq, td, start, end)

            sweep_results.append({
                "n_legs": n_legs,
                "sma_window": sma_win,
                "vix_exit": vix_thr,
                **{f"is_{k}": v for k, v in m.items()},
            })
        except Exception as exc:
            sweep_results.append({
                "n_legs": n_legs,
                "sma_window": sma_win,
                "vix_exit": vix_thr,
                "error": str(exc),
            })

    return sweep_results


# ── Monte Carlo / Bootstrap / Permutation ─────────────────────────────────────

def _monte_carlo_sharpe(
    equity: pd.Series,
    n_simulations: int = 1000,
    p_level: float = 0.05,
    seed: int = 42,
) -> float:
    """
    Monte Carlo Sharpe: resample daily returns with replacement (block-bootstrap
    approximation). Report the p_level (5th percentile) Sharpe.
    """
    rng = np.random.default_rng(seed)
    daily_returns = equity.pct_change().dropna().values
    if len(daily_returns) < 10:
        return np.nan

    sharpes = []
    n = len(daily_returns)
    for _ in range(n_simulations):
        sample = rng.choice(daily_returns, size=n, replace=True)
        std_ = sample.std()
        if std_ > 1e-10:
            sharpes.append(float(sample.mean() / std_ * np.sqrt(TRADING_DAYS_PER_YEAR)))

    if not sharpes:
        return np.nan
    return round(float(np.percentile(sharpes, int(p_level * 100))), 4)


def _bootstrap_sharpe_ci(
    equity: pd.Series,
    n_boot: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple:
    """
    Bootstrap 95% confidence interval for Sharpe ratio.
    Returns (lower, upper) bounds.
    """
    rng = np.random.default_rng(seed)
    daily_returns = equity.pct_change().dropna().values
    if len(daily_returns) < 10:
        return (np.nan, np.nan)

    sharpes = []
    n = len(daily_returns)
    for _ in range(n_boot):
        sample = rng.choice(daily_returns, size=n, replace=True)
        std_ = sample.std()
        if std_ > 1e-10:
            sharpes.append(float(sample.mean() / std_ * np.sqrt(TRADING_DAYS_PER_YEAR)))

    if len(sharpes) < 10:
        return (np.nan, np.nan)

    alpha = (1 - ci) / 2
    lower = round(float(np.percentile(sharpes, alpha * 100)), 4)
    upper = round(float(np.percentile(sharpes, (1 - alpha) * 100)), 4)
    return (lower, upper)


def _permutation_test(
    equity: pd.Series,
    n_perm: int = 500,
    seed: int = 42,
) -> float:
    """
    Permutation test: under H0 (no skill), daily returns are i.i.d.
    Permute returns, compute Sharpe for each permutation.
    p-value = fraction of permuted Sharpes >= observed Sharpe.
    """
    rng = np.random.default_rng(seed)
    daily_returns = equity.pct_change().dropna().values
    if len(daily_returns) < 10:
        return np.nan

    std_ = daily_returns.std()
    if std_ < 1e-10:
        return np.nan
    observed_sharpe = float(daily_returns.mean() / std_ * np.sqrt(TRADING_DAYS_PER_YEAR))

    count_exceed = 0
    n = len(daily_returns)
    for _ in range(n_perm):
        perm = rng.permutation(daily_returns)
        s_ = perm.std()
        if s_ > 1e-10:
            perm_sharpe = float(perm.mean() / s_ * np.sqrt(TRADING_DAYS_PER_YEAR))
            if perm_sharpe >= observed_sharpe:
                count_exceed += 1

    return round(float(count_exceed / n_perm), 4)


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(
    start: str = "2007-01-01",
    end: str = "2021-12-31",
    params: dict = None,
) -> dict:
    """
    Orchestrate H37 G10 Currency Carry full IS backtest.

    Steps:
    1. Download FX ETF OHLCV + ^VIX with warmup (yfinance).
    2. Download FRED central bank rates (pandas_datareader; fallback to 0.0).
    3. Data quality checks.
    4. Compute carry + momentum signal on full (warmup-inclusive) series.
    5. Trim to backtest window; simulate.
    6. Compute IS metrics.
    7. Run 4-window walk-forward validation.
    8. Sensitivity sweep (n_legs × sma_window × vix_exit).
    9. Monte Carlo, bootstrap CI, permutation test.
    10. Return unified result dict.

    Parameters
    ----------
    start  : str   IS start date (default "2007-01-01")
    end    : str   IS end date (default "2021-12-31")
    params : dict  Override PARAMETERS (optional)

    Returns
    -------
    dict  Keys: is_sharpe, oos_sharpe, is_mdd, win_rate, profit_factor,
               trade_count, trades_per_year, walk_forward_results, sensitivity,
               mc_p5_sharpe, bootstrap_ci, permutation_pvalue, + all _compute_metrics
               keys, trades (DataFrame), equity_curve (Series), daily_df (DataFrame),
               data_quality (dict), params (dict)
    """
    if params is None:
        params = PARAMETERS.copy()

    universe = list(params["universe"])
    sma_window = int(params.get("sma_window", 60))
    init_cash = float(params["init_cash"])

    print(f"\nH37 G10 Currency Carry — run_backtest({start} to {end})")
    print(f"  Universe: {universe}")
    print(f"  n_legs={params['n_legs']}, sma={sma_window}, vix_exit={params['vix_exit_threshold']}")

    # ── 1. Download price data ────────────────────────────────────────────────
    print("  [1/9] Downloading price data...")
    close_full, open_full, volume_full, vix_full = download_data(
        universe, start, end, sma_window
    )

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 2. Download FRED rates ─────────────────────────────────────────────────
    print("  [2/9] Downloading FRED rates...")
    rate_df = download_fred_rates(universe, start, end)

    # ── 3. Data quality checks ────────────────────────────────────────────────
    print("  [3/9] Checking data quality...")
    data_quality = check_data_quality(close_full, start, end)

    # ── 4. Compute signal on warmup-inclusive series ──────────────────────────
    print("  [4/9] Computing carry + momentum signal...")
    monthly_signal_full = compute_carry_momentum_signal(close_full, rate_df, params)

    # ── 5. Trim to backtest window ────────────────────────────────────────────
    mask = (close_full.index >= ts_start) & (close_full.index <= ts_end)
    close_df = close_full.loc[mask].copy()
    open_df = open_full.loc[mask].copy()
    volume_df = volume_full.loc[mask].copy()
    vix_series = vix_full.loc[mask]

    # Subset monthly signal to IS window
    monthly_signal_is = {
        d: s for d, s in monthly_signal_full.items()
        if ts_start <= d <= ts_end
    }

    if len(close_df) < 10:
        raise ValueError(
            f"Insufficient data after trimming to {start}–{end}: {len(close_df)} bars"
        )

    # ── 6. Simulate ───────────────────────────────────────────────────────────
    print("  [5/9] Running IS simulation...")
    trade_log, equity, daily_df = simulate_h37(
        close_df, open_df, volume_df, vix_series, monthly_signal_is, params
    )

    # ── 7. Build trade DataFrame ──────────────────────────────────────────────
    empty_cols = [
        "entry_date", "exit_date", "asset", "direction", "entry_price", "entry_eff",
        "exit_price", "exit_eff", "shares", "pnl", "return_pct", "entry_cost",
        "exit_cost", "transaction_cost", "liquidity_constrained", "hold_days", "exit_reason",
    ]
    # Inject asset (ticker) into trade records — fix: _make_trade_record uses pos dict
    # Re-label trades from trade_log (ticker captured in outer loop scope)
    trades_df = (
        pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)
    )
    # Ensure all required columns exist
    for col in empty_cols:
        if col not in trades_df.columns:
            trades_df[col] = np.nan

    # ── 8. IS Metrics ─────────────────────────────────────────────────────────
    metrics = _compute_metrics(equity, trades_df, start, end)

    # ── 9. Walk-forward validation ────────────────────────────────────────────
    print("  [6/9] Running walk-forward validation...")
    wf_results = run_walk_forward(close_full, open_full, volume_full, vix_full, rate_df, params)

    oos_sharpes = [
        w["oos_sharpe"] for w in wf_results
        if not np.isnan(w.get("oos_sharpe", np.nan))
    ]
    oos_sharpe_mean = round(float(np.mean(oos_sharpes)), 4) if oos_sharpes else np.nan

    # ── 10. Sensitivity sweep ─────────────────────────────────────────────────
    print("  [7/9] Running sensitivity sweep (27 combinations)...")
    sensitivity = _run_sensitivity_sweep(
        close_full, open_full, volume_full, vix_full, rate_df, params, start, end
    )

    # ── 11. Monte Carlo + bootstrap CI + permutation test ─────────────────────
    print("  [8/9] Running Monte Carlo / bootstrap / permutation tests...")
    mc_p5_sharpe = _monte_carlo_sharpe(equity)
    bootstrap_ci = _bootstrap_sharpe_ci(equity)
    permutation_pvalue = _permutation_test(equity)

    # ── 12. Print summary ─────────────────────────────────────────────────────
    exit_breakdown = {}
    asset_breakdown = {}
    if not trades_df.empty:
        if "exit_reason" in trades_df.columns:
            exit_breakdown = trades_df["exit_reason"].value_counts().to_dict()
        if "asset" in trades_df.columns:
            for asset_name, grp in trades_df.groupby("asset"):
                asset_breakdown[asset_name] = {
                    "trade_count": len(grp),
                    "total_pnl": round(float(grp["pnl"].sum()), 2),
                    "win_rate": round(float((grp["pnl"] > 0).mean()), 4),
                }

    if not trades_df.empty and "direction" in trades_df.columns:
        long_trades = int((trades_df["direction"] == "long").sum())
        short_trades = int((trades_df["direction"] == "short").sum())
    else:
        long_trades = 0
        short_trades = 0

    print(
        f"\nH37 G10 Currency Carry [{start} to {end}]:\n"
        f"  Universe: {universe}\n"
        f"  n_legs: {params['n_legs']} | SMA: {sma_window}d | "
        f"VIX exit: {params['vix_exit_threshold']} | Hard stop: {params['hard_stop_pct']:.0%}\n"
        f"  Monthly signals: {len(monthly_signal_is)} | IS bars: {len(close_df)}\n"
        f"  Trades: {metrics['trade_count']} ({metrics['trades_per_year']}/yr) "
        f"[L:{long_trades} S:{short_trades}]\n"
        f"  IS  Sharpe: {metrics['sharpe']} | Max DD: {metrics['max_drawdown']:.2%} "
        f"| Total Return: {metrics['total_return']:.2%}\n"
        f"  OOS Sharpe (WF mean): {oos_sharpe_mean}\n"
        f"  Win rate: {metrics['win_rate']:.2%} | Profit factor: {metrics['profit_factor']:.2f}\n"
        f"  MC p5 Sharpe: {mc_p5_sharpe} | Bootstrap CI: {bootstrap_ci} "
        f"| Perm p-val: {permutation_pvalue}\n"
        f"  Exit reasons: {exit_breakdown}\n"
        f"  Init cash: ${init_cash:,.0f}"
    )
    print("  [9/9] Done.")

    return {
        # Top-level Gate 1 metrics
        "is_sharpe": metrics["sharpe"],
        "oos_sharpe": oos_sharpe_mean,
        "is_mdd": metrics["max_drawdown"],
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "trade_count": metrics["trade_count"],
        "trades_per_year": metrics["trades_per_year"],
        # Walk-forward
        "walk_forward_results": wf_results,
        # Sensitivity
        "sensitivity": sensitivity,
        # Statistical tests
        "mc_p5_sharpe": mc_p5_sharpe,
        "bootstrap_ci": bootstrap_ci,
        "permutation_pvalue": permutation_pvalue,
        # Full metrics dict
        **metrics,
        # Data objects
        "returns": equity.pct_change().fillna(0.0),
        "trades": trades_df,
        "equity_curve": equity,
        "daily_df": daily_df,
        "metrics": metrics,
        "params": params,
        "data_quality": data_quality,
        "asset_breakdown": asset_breakdown,
        "exit_breakdown": exit_breakdown,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    universe: list = None,
    start: str = "2007-01-01",
    end: str = "2021-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H37 G10 Currency Carry.

    Returns a DataFrame with per-day columns:
        date, position, equity, pnl, asset, direction, entry_price, exit_price,
        return_pct, transaction_cost, exit_reason

    Trade-level fields are populated on exit date; other rows carry NaN.
    The `position` column uses the format "L:<longs>|S:<shorts>" or "FLAT".
    """
    p = (params or PARAMETERS).copy()
    if universe is not None:
        p["universe"] = universe

    result = run_backtest(start, end, p)

    daily = result["daily_df"].reset_index()
    trades = result["trades"]

    trade_cols = [
        "exit_date", "asset", "direction", "pnl", "entry_price", "exit_price",
        "return_pct", "transaction_cost", "exit_reason",
    ]

    if trades.empty or not all(c in trades.columns for c in trade_cols):
        for col in ["pnl", "asset", "direction", "entry_price", "exit_price",
                    "return_pct", "transaction_cost", "exit_reason"]:
            daily[col] = np.nan
    else:
        tc = trades[trade_cols].copy()
        tc["exit_date"] = pd.to_datetime(tc["exit_date"])
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.merge(
            tc.rename(columns={"exit_date": "date"}),
            on="date",
            how="left",
        )

    output_cols = [
        "date", "position", "equity",
        "pnl", "asset", "direction", "entry_price", "exit_price",
        "return_pct", "transaction_cost", "exit_reason",
    ]
    for col in output_cols:
        if col not in daily.columns:
            daily[col] = np.nan

    return daily[output_cols]


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("H37 G10 Currency Carry — IS Backtest (2007-01-01 to 2021-12-31)")
    print("=" * 70)

    is_result = run_backtest(
        start="2007-01-01",
        end="2021-12-31",
        params=PARAMETERS.copy(),
    )

    print(f"\n{'=' * 70}")
    print("GATE 1 SUMMARY")
    print(f"{'=' * 70}")
    print(f"  IS Sharpe       : {is_result['is_sharpe']}")
    print(f"  IS Max Drawdown : {is_result['is_mdd']:.2%}")
    print(f"  IS Total Return : {is_result['total_return']:.2%}")
    print(f"  Win Rate        : {is_result['win_rate']:.2%}")
    print(f"  Profit Factor   : {is_result['profit_factor']:.2f}")
    print(f"  Trade Count     : {is_result['trade_count']}")
    print(f"  Trades/Year     : {is_result['trades_per_year']}")
    print(f"  OOS Sharpe (WF) : {is_result['oos_sharpe']}")
    print(f"  MC p5 Sharpe    : {is_result['mc_p5_sharpe']}")
    print(f"  Bootstrap 95% CI: {is_result['bootstrap_ci']}")
    print(f"  Permutation pval: {is_result['permutation_pvalue']}")
    print()

    equity_curve = is_result["equity_curve"]
    if not equity_curve.empty:
        print(f"  Final NAV       : ${equity_curve.iloc[-1]:,.2f}")
        print(f"  Starting NAV    : ${PARAMETERS['init_cash']:,.2f}")

    print()
    trades = is_result["trades"]
    if not trades.empty:
        print("Sample trades (first 10):")
        display_cols = [
            c for c in [
                "entry_date", "exit_date", "asset", "direction",
                "entry_price", "exit_price", "shares", "pnl",
                "return_pct", "exit_reason"
            ] if c in trades.columns
        ]
        print(trades[display_cols].head(10).to_string(index=False))

    print()
    print("Walk-forward results:")
    for w in is_result["walk_forward_results"]:
        print(
            f"  {w['window']}: IS Sharpe={w.get('is_sharpe', np.nan):.4f}, "
            f"OOS Sharpe={w.get('oos_sharpe', np.nan):.4f}, "
            f"IS MDD={w.get('is_mdd', np.nan):.2%}, "
            f"IS Trades={w.get('is_trade_count', 0)}"
        )

    print()
    print("Data quality report:")
    dq = is_result["data_quality"]
    print(f"  Survivorship: {dq.get('survivorship_bias', 'N/A')[:100]}...")
    for ticker, info in dq.get("tickers", {}).items():
        if "error" in info:
            print(f"  {ticker}: ERROR — {info['error']}")
        elif "note" in info:
            print(f"  {ticker}: NOTE — {info['note']}")
        else:
            print(
                f"  {ticker}: {info.get('bars_in_window', '?')} bars, "
                f"{info.get('missing_business_days', '?')} missing bdays, "
                f"gap_flag={info.get('gap_flag', False)}"
            )
