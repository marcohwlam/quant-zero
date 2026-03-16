"""
Strategy: H07c Multi-Asset Time-Series Momentum — Yield Curve Regime Filter + Dynamic Lookback
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: 15-ETF universe with dual regime system: VIX gate (from H07b) + yield curve filter
            that exits duration-sensitive ETFs when 2Y-10Y spread inverts, combined with
            dynamic lookback (12m normal / 6m elevated-VIX) to reduce stale-signal whipsaw.
Asset class: equities (ETFs)
Parent task: QUA-168
References:
  - Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum" — JFE 104(2)
  - Barroso & Santa-Clara (2015) "Momentum Has Its Moments" — JFE 116(1)
  - Daniel & Moskowitz (2016) "Momentum Crashes" — JFE 122(2)
  - Harvey (1988) "The Real Term Structure and Consumption Growth" — JFE 22(2)
  - Estrella & Mishkin (1998) "Predicting U.S. Recessions" — RES 80(1)

Changes from H07b:
  - Yield curve filter: exit TLT/IEF/HYG/TIP/XLF/XLRE when ^TNX - ^IRX < yield_curve_threshold
  - Dynamic lookback: 12-month if VIX <= dynamic_lookback_vix_threshold, 6-month otherwise
  - Two new parameters: yield_curve_threshold, dynamic_lookback_vix_threshold
  - generate_daily_signals returns filter_stats dict (YC-blocked vs VIX-blocked counts)
"""

import warnings
import numpy as np
import pandas as pd
import vectorbt as vbt
import yfinance as yf

# All tunable parameters exposed here for sensitivity scanning
PARAMETERS = {
    "universe": [
        "SPY", "QQQ", "IWM", "EFA",       # equities: large, tech, small, intl
        "TLT", "IEF", "HYG", "TIP",        # bonds: long-dur, mid-dur, credit, TIPS
        "GLD", "SLV", "DBB", "DBA",        # commodities: gold, silver, metals, ag
        "XLE", "XLF", "XLRE",              # sectors: energy, financials, real estate
    ],
    "lookback_months_normal": 12,           # lookback when VIX <= dynamic_lookback_vix_threshold
    "lookback_months_stress": 6,            # lookback when VIX > dynamic_lookback_vix_threshold
    "vix_stress_threshold": 25,             # VIX > this → half exposure; scan: [20, 25, 30]
    "vix_crisis_threshold": 35,             # VIX > this → flat; fixed at 35
    "yield_curve_threshold": 0.0,           # YC spread < this → exit duration ETFs; scan: [-0.25, 0.0, +0.25]
    "dynamic_lookback_vix_threshold": 20,   # VIX switch for lookback; scan: [15, 20, 25]
    "intramonth_stop_pct": 0.20,            # per-asset stop-loss from entry price; scan: [0.15, 0.20, 0.25]
    "long_only": True,                      # long-only; flat for negative signals
    "init_cash": 25000,                     # starting capital ($)
    "order_qty": 100,                       # order size in shares (for market impact calc)
}

TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_YEAR = 252

# XLRE launched October 2015. If it has insufficient history before IS start,
# substitute IYR (iShares US Real Estate, since June 2000). Approved by Research Director.
XLRE_MIN_DAYS_BEFORE_IS = 400
XLRE_SUBSTITUTE = "IYR"

# Duration-sensitive ETFs: exit when yield curve is inverted.
# Defined by economic characteristics (rate duration / credit spread sensitivity),
# NOT selected by return screening. IYR is included to handle the XLRE → IYR substitution.
# Economic rationale per hypothesis 07c: these ETFs face ongoing headwinds when the
# Fed is in an aggressive hiking cycle (inverted curve = markets pricing future cuts after hikes).
DURATION_SENSITIVE_ETFS = frozenset(["TLT", "IEF", "HYG", "TIP", "XLF", "XLRE", "IYR"])


# ── Data Loading ───────────────────────────────────────────────────────────────

def download_data(
    tickers: list, start: str, end: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Download adjusted close prices and volume via yfinance.
    auto_adjust=True: adjusted for splits and dividends.

    Returns:
        close:  DataFrame, adjusted closing prices
        volume: DataFrame, daily share volume
    """
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        volume = raw["Volume"]
    else:
        # Single-ticker flat columns
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
        volume = raw[["Volume"]].rename(columns={"Volume": tickers[0]})

    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    if isinstance(volume, pd.Series):
        volume = volume.to_frame(name=tickers[0])

    available = [t for t in tickers if t in close.columns]
    return close[available].copy(), volume[available].copy()


def download_vix(start: str, end: str) -> pd.Series:
    """
    Download VIX daily close from Yahoo Finance (ticker: ^VIX).

    No look-ahead: caller uses VIX at date T for positions starting at T+1.
    Downloads from slightly before start to ensure month-end VIX is available.

    Returns pd.Series named 'VIX'.
    Raises ValueError if data is empty.
    """
    raw = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError("VIX download returned empty. Check Yahoo Finance connection.")

    if isinstance(raw.columns, pd.MultiIndex):
        vix = raw["Close"].squeeze()
    else:
        vix = raw["Close"]

    if isinstance(vix, pd.DataFrame):
        vix = vix.iloc[:, 0]

    return vix.rename("VIX")


def download_yield_curve(start: str, end: str) -> pd.DataFrame:
    """
    Download 10-Year (^TNX) and short-term (^IRX) Treasury yields from Yahoo Finance.
    Compute YC_spread = TNX - IRX as a proxy for the yield curve spread.

    Note: ^IRX is the 13-week T-Bill rate used here as the short-end proxy per task spec.
    The FRED alternative T10Y2Y (10-Year minus 2-Year) is a closer match to the academic
    definition of yield curve inversion but requires an additional API key. Yahoo ^TNX - ^IRX
    is sufficient for the mechanistic regime filter described in hypothesis 07c.

    Returns:
        DataFrame with columns ['TNX', 'IRX', 'YC_spread'], daily frequency.
        Gaps are forward-filled (yields don't trade on weekends/holidays).
    Raises:
        ValueError: if either yield series is completely empty.
    """
    def _extract_close(raw: pd.DataFrame, ticker: str) -> pd.Series:
        if raw.empty:
            raise ValueError(
                f"Yield download for {ticker} returned empty. Check Yahoo Finance connection."
            )
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"].squeeze()
        else:
            close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close

    tnx_raw = yf.download("^TNX", start=start, end=end, auto_adjust=True, progress=False)
    irx_raw = yf.download("^IRX", start=start, end=end, auto_adjust=True, progress=False)

    tnx = _extract_close(tnx_raw, "^TNX").rename("TNX")
    irx = _extract_close(irx_raw, "^IRX").rename("IRX")

    yc_df = pd.DataFrame({"TNX": tnx, "IRX": irx}).sort_index()
    yc_df["YC_spread"] = yc_df["TNX"] - yc_df["IRX"]

    # Forward-fill to handle non-trading days (yield data has sparse holidays)
    yc_df = yc_df.ffill()

    return yc_df


def resolve_universe(tickers: list, is_start: str = "2018-01-01") -> list:
    """
    Resolve ETF universe: substitute XLRE with IYR if XLRE lacks sufficient history.

    Survivorship bias note:
    - All ETFs except XLRE/IYR have data back to at least 2007 (DBB, DBA, HYG, SLV).
    - No ETF was selected based on forward-looking backtest performance.
    - XLRE (Oct 2015): has ~2+ years before 2018 IS start. IYR (Jun 2000): full IS coverage.
    - Universe represents 5 asset classes × 3 instruments: structured diversification,
      not return-chasing.

    Returns the final universe list (XLRE or IYR, all others unchanged).
    """
    if "XLRE" not in tickers:
        return tickers

    try:
        is_ts = pd.Timestamp(is_start)
        check_start = str((is_ts - pd.DateOffset(years=3)).date())
        xlre_raw, _ = download_data(["XLRE"], check_start, is_start)
        xlre_days = len(xlre_raw["XLRE"].dropna())
        if xlre_days >= XLRE_MIN_DAYS_BEFORE_IS:
            return tickers
    except Exception:
        pass  # Fall through to substitution

    warnings.warn(
        f"XLRE has <{XLRE_MIN_DAYS_BEFORE_IS} trading days before IS start {is_start}. "
        f"Substituting XLRE with {XLRE_SUBSTITUTE} (iShares US Real Estate, since 2000). "
        "This substitution is pre-approved per hypothesis file 07c_multi_asset_tsmom_yield_curve.md."
        f" Note: {XLRE_SUBSTITUTE} inherits duration-sensitive classification."
    )
    return [XLRE_SUBSTITUTE if t == "XLRE" else t for t in tickers]


# ── Data Quality ───────────────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame) -> dict:
    """
    Data quality report per Engineering Director checklist.

    Notes:
    - Survivorship bias: Fixed universe; no ETF selected on forward performance.
      DBB/DBA/HYG/SLV launched 2006-2007 — present for full 2018-2023 IS window.
    - Price adjustments: yfinance auto_adjust=True (splits + dividends).
    - Earnings exclusion: N/A — ETFs have no individual earnings events.
    - Delisted: N/A — all are major ETFs with negligible delisting risk.
    - Data gaps: flagged if any ticker has >5 missing business days.
    """
    report = {
        "survivorship_bias": (
            "15-ETF fixed universe. All ETFs present since at least 2007 (DBB, DBA, HYG, SLV). "
            "No ETF selected on forward performance. XLRE (2015) → IYR (2000) if data insufficient."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — ETFs have no individual earnings events.",
        "delisted": "N/A — all are major actively-traded ETFs.",
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
        missing = len(expected.difference(price.index))
        report["tickers"][ticker] = {
            "total_days": len(price),
            "missing_business_days": missing,
            "gap_flag": missing > 5,
            "start": str(price.index.min().date()),
            "end": str(price.index.max().date()),
        }
        if missing > 5:
            flagged.append(ticker)

    if flagged:
        warnings.warn(f"Data gap flag (>5 missing business days): {flagged}")

    return report


def check_yield_curve_data(yc_df: pd.DataFrame) -> dict:
    """
    Validate yield curve data quality.

    Per Engineering Director requirement: confirm ^TNX and ^IRX data availability
    back to at least 2016 (2 years before the 2018-01-01 IS start). This ensures
    that the 12-month lookback period at the IS start has yield curve data available.

    Returns:
        dict with availability confirmation and any warnings.
    """
    required_start = pd.Timestamp("2016-01-01")
    report = {
        "required_start": str(required_start.date()),
        "purpose": "Confirm yield curve data covers 2-year lookback buffer before IS start (2018-01-01)",
        "series": {},
    }

    all_ok = True
    for col in ["TNX", "IRX", "YC_spread"]:
        if col not in yc_df.columns:
            report["series"][col] = {"error": f"Column {col} not found in yield curve data"}
            all_ok = False
            continue

        series = yc_df[col].dropna()
        if series.empty:
            report["series"][col] = {"error": "Empty series — check Yahoo Finance download"}
            all_ok = False
            continue

        data_start = series.index.min()
        data_ok = data_start <= required_start
        report["series"][col] = {
            "start": str(data_start.date()),
            "end": str(series.index.max().date()),
            "total_days": len(series),
            "available_from_2016": data_ok,
        }

        if not data_ok:
            all_ok = False
            warnings.warn(
                f"Yield curve {col}: data starts {data_start.date()}, "
                f"which is after required start 2016-01-01. "
                "Early IS period may have missing yield curve regime data."
            )

    report["all_series_available_from_2016"] = all_ok
    return report


# ── VIX Regime Gate ────────────────────────────────────────────────────────────

def compute_vix_regime(
    vix_close: pd.Series,
    rebal_dates: pd.DatetimeIndex,
    daily_index: pd.DatetimeIndex,
    stress_threshold: float,
    crisis_threshold: float,
) -> tuple[pd.Series, pd.Series]:
    """
    Compute VIX-based position scale at monthly and intramonth frequency.

    Monthly gate (strictly no look-ahead):
        VIX_T = closing VIX value at end-of-month T.
        Applied to M+1 positions (first trading day after T).
        VIX_T > crisis_threshold:  scale = 0.0 (flat, capital preservation)
        VIX_T > stress_threshold:  scale = 0.5 (half exposure, stress regime)
        VIX_T ≤ stress_threshold:  scale = 1.0 (full exposure, normal)

    Intramonth override:
        If VIX.close[T] > crisis_threshold, force-exit all positions at T+1 open.
        Accepts 1-day execution lag (documented in hypothesis per Research Director).

    References:
        Barroso & Santa-Clara (2015): volatility-scaling avoids high-VIX whipsaw periods.
        Daniel & Moskowitz (2016): VIX > 25 documented as momentum performance degradation period.

    Returns:
        monthly_scale:    pd.Series indexed by rebal_dates, values in {0.0, 0.5, 1.0}
        daily_crisis_exit: pd.Series (bool), True on days to force-exit all positions
    """
    monthly_scale = {}
    for rd in rebal_dates:
        past_vix = vix_close.loc[:rd]
        if past_vix.empty:
            monthly_scale[rd] = 1.0
            continue
        vix_val = float(past_vix.iloc[-1])
        if vix_val > crisis_threshold:
            monthly_scale[rd] = 0.0
        elif vix_val > stress_threshold:
            monthly_scale[rd] = 0.5
        else:
            monthly_scale[rd] = 1.0

    monthly_scale_series = pd.Series(monthly_scale, name="vix_scale")

    # Intramonth: T+1 is a force-exit day if VIX[T] > crisis_threshold
    vix_on_daily = vix_close.reindex(daily_index, method="ffill")
    daily_crisis_exit = pd.Series(False, index=daily_index)
    for i in range(1, len(daily_index)):
        if vix_on_daily.iloc[i - 1] > crisis_threshold:
            daily_crisis_exit.iloc[i] = True

    return monthly_scale_series, daily_crisis_exit


# ── Yield Curve Regime ─────────────────────────────────────────────────────────

def compute_yield_curve_regime(
    yc_spread: pd.Series,
    rebal_dates: pd.DatetimeIndex,
    yc_threshold: float,
) -> pd.Series:
    """
    Compute yield curve regime at each month-end rebalancing date.

    No look-ahead: uses only YC spread data at or before each rebalancing date.
    Inverted curve (spread < yc_threshold) triggers blocking of duration-sensitive ETFs
    at the subsequent month's rebalancing.

    Args:
        yc_spread:    Daily series of (^TNX - ^IRX) yield spread
        rebal_dates:  Month-end dates to evaluate
        yc_threshold: Threshold for declaring inversion (default 0.0 = standard inversion)

    Returns:
        pd.Series (bool) indexed by rebal_dates, True = inverted curve
    """
    yc_inverted = {}
    for rd in rebal_dates:
        past_yc = yc_spread.loc[:rd]
        if past_yc.empty:
            yc_inverted[rd] = False
            continue
        yc_val = float(past_yc.dropna().iloc[-1]) if past_yc.dropna().shape[0] > 0 else 0.0
        yc_inverted[rd] = yc_val < yc_threshold

    return pd.Series(yc_inverted, name="yc_inverted")


# ── Signal Generation ──────────────────────────────────────────────────────────

def generate_daily_signals(
    close: pd.DataFrame,
    vix_close: pd.Series,
    yc_spread: pd.Series,
    params: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, dict]:
    """
    Generate daily entry/exit signals with yield curve regime filter and dynamic lookback.

    Changes from H07b:
    - Dynamic lookback: 12m normal (VIX <= threshold) / 6m stress (VIX > threshold)
    - Yield curve filter: DURATION_SENSITIVE_ETFS blocked when YC_spread < yield_curve_threshold

    Signal logic at each month-end rebalancing date T (no look-ahead):
      Step 1: VIX_T → vix_scale ∈ {0.0, 0.5, 1.0} and dynamic lookback ∈ {6, 12} months
      Step 2: YC_spread_T → yc_inverted (bool)
      Step 3: R_Nm(i, T) = (P(i,T) / P(i, T - lookback×21)) − 1 per ETF
      Step 4: signal_raw(i,T) = +1 if R_Nm > 0 else 0
      Step 5: Apply filters:
              - VIX crisis (vix_scale=0): exit all positions; block all entries
              - YC inverted AND i ∈ DURATION_SENSITIVE_ETFS: signal = 0 (exit if was long)
              - Otherwise: entry on +1 signal; exit on 0 signal

    Logging:
      - Counts raw entry opportunities, YC-blocked entries, VIX-crisis-blocked entries
      - Warns if YC filter blocks >30% of raw entry opportunities

    Returns:
        entries:          Boolean DataFrame (daily)
        exits:            Boolean DataFrame (daily)
        vix_daily_scale:  pd.Series (float, daily), values in {0.0, 0.5, 1.0}
        filter_stats:     dict with blocking counts for logging
    """
    # Identify month-end rebalancing dates from price series
    monthly_dates = close.resample("ME").last().index

    # Precompute VIX and yield curve regimes at each rebalancing date
    monthly_vix_scale, daily_crisis_exit = compute_vix_regime(
        vix_close,
        monthly_dates,
        close.index,
        params["vix_stress_threshold"],
        params["vix_crisis_threshold"],
    )
    yc_inverted_series = compute_yield_curve_regime(
        yc_spread,
        monthly_dates,
        params["yield_curve_threshold"],
    )

    # Resolve duration-sensitive tickers (handles XLRE → IYR substitution)
    duration_sensitive = DURATION_SENSITIVE_ETFS & set(close.columns)

    # Precompute momentum signal for each month using dynamic lookback
    # Dynamic lookback rule: 12m if VIX ≤ dynamic_lookback_vix_threshold, 6m otherwise
    # No look-ahead: lookback decision and signal both use data at or before month-end T
    monthly_signals = {}
    for rd in monthly_dates:
        past_vix = vix_close.loc[:rd]
        vix_val = float(past_vix.dropna().iloc[-1]) if not past_vix.dropna().empty else 20.0

        if vix_val <= params["dynamic_lookback_vix_threshold"]:
            lb_months = params["lookback_months_normal"]
        else:
            lb_months = params["lookback_months_stress"]

        lookback_td = lb_months * TRADING_DAYS_PER_MONTH

        # Use only prices up to and including this month-end date
        past_close = close.loc[:rd]
        if len(past_close) <= lookback_td:
            # Not enough history for this lookback window: default to flat
            monthly_signals[rd] = pd.Series(0.0, index=close.columns)
            continue

        price_now = past_close.iloc[-1]
        price_lb = past_close.iloc[-1 - lookback_td]
        # Avoid division by zero; NaN → False (flat signal)
        ret = (price_now / price_lb.replace(0, np.nan)) - 1
        monthly_signals[rd] = (ret > 0).fillna(False).astype(float)

    # Build daily entry/exit DataFrames
    entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    exits = pd.DataFrame(False, index=close.index, columns=close.columns)
    vix_daily_scale = pd.Series(1.0, index=close.index, name="vix_daily_scale")

    # Logging counters (per hypothesis: track YC filter impact)
    raw_entry_count = 0      # all (month, ticker) pairs with raw momentum signal = 1
    yc_blocked_count = 0     # subset blocked by yield curve filter
    vix_blocked_count = 0    # subset blocked by VIX crisis gate (vix_scale = 0)

    for i, rebal_date in enumerate(monthly_dates):
        future_dates = close.index[close.index > rebal_date]
        if len(future_dates) == 0:
            continue
        exec_date = future_dates[0]  # first trading day of next month

        current_sig = monthly_signals[rebal_date]
        prev_sig = (
            monthly_signals[monthly_dates[i - 1]]
            if i > 0
            else pd.Series(0.0, index=close.columns)
        )
        vix_scale = float(monthly_vix_scale.get(rebal_date, 1.0))
        yc_inv = bool(yc_inverted_series.get(rebal_date, False))

        # Propagate monthly VIX scale to all daily bars until the next rebalancing
        next_rebal_dates = [r for r in monthly_dates if r > rebal_date]
        if next_rebal_dates:
            period_end = close.index[close.index <= next_rebal_dates[0]]
            period_end = period_end[period_end >= exec_date]
        else:
            period_end = close.index[close.index >= exec_date]
        if len(period_end) > 0:
            vix_daily_scale.loc[period_end] = vix_scale

        for ticker in close.columns:
            raw_signal = float(current_sig[ticker])

            if vix_scale == 0.0:
                # VIX crisis: exit all existing positions; block all new entries
                if prev_sig[ticker] > 0:
                    exits.at[exec_date, ticker] = True
                if raw_signal > 0:
                    # Count as VIX-blocked (would have been an entry otherwise)
                    raw_entry_count += 1
                    vix_blocked_count += 1

            elif raw_signal > 0:
                raw_entry_count += 1

                if yc_inv and ticker in duration_sensitive:
                    # Yield curve inverted: force duration-sensitive ETF to flat
                    yc_blocked_count += 1
                    if prev_sig[ticker] > 0:
                        # Was long last month → exit now
                        exits.at[exec_date, ticker] = True
                    # No new entry: signal forced to 0 by yield curve filter
                else:
                    # Normal entry: momentum signal active, no regime block
                    entries.at[exec_date, ticker] = True

            elif raw_signal == 0 and prev_sig[ticker] > 0:
                # Signal turned off this month: exit (standard TSMOM exit)
                exits.at[exec_date, ticker] = True

    # Intramonth crisis override: force-exit all on T+1 when VIX[T] > crisis_threshold
    crisis_exit_dates = daily_crisis_exit.index[daily_crisis_exit]
    if len(crisis_exit_dates) > 0:
        exits.loc[crisis_exit_dates, :] = True

    # Yield curve filter warning (Engineering Director requirement: flag if >30% blocked)
    yc_block_rate = yc_blocked_count / max(1, raw_entry_count)
    if yc_block_rate > 0.30:
        warnings.warn(
            f"Yield curve filter blocked {yc_block_rate:.1%} of expected entry opportunities "
            f"({yc_blocked_count}/{raw_entry_count}). Exceeds the 30% Engineering Director "
            "threshold. Consider reviewing yield_curve_threshold parameter."
        )

    filter_stats = {
        "raw_entry_opportunities": raw_entry_count,
        "yc_blocked_count": yc_blocked_count,
        "vix_crisis_blocked_count": vix_blocked_count,
        "yc_block_rate": round(yc_block_rate, 4),
        "yc_threshold_exceeded_30pct": yc_block_rate > 0.30,
        "duration_sensitive_tickers_in_universe": sorted(duration_sensitive),
    }

    print(
        f"  [H07c filter stats] {raw_entry_count} raw signals | "
        f"{yc_blocked_count} YC-blocked ({yc_block_rate:.1%}) | "
        f"{vix_blocked_count} VIX-crisis-blocked"
    )

    return entries, exits, vix_daily_scale, filter_stats


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def compute_market_impact(
    close: pd.DataFrame, volume: pd.DataFrame, params: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Square-root market impact (canonical Engineering Director model).

    Formula: impact = k × σ × sqrt(Q / ADV)
      k   = 0.1 (Johnson, Algorithmic Trading & DMA)
      σ   = 20-day rolling daily return volatility
      Q   = order dollar value (order_qty × close)
      ADV = 20-day average dollar volume (volume × close)

    Returns:
        market_impact: impact fraction (same shape as close)
        q_over_adv:    Q/ADV ratios for liquidity flagging
    """
    k = 0.1
    order_qty = params.get("order_qty", 100)
    sigma = close.pct_change().rolling(20).std()
    dollar_volume = volume * close
    adv_dollar = dollar_volume.rolling(20).mean()
    order_value = order_qty * close
    q_over_adv = (order_value / adv_dollar.replace(0, np.nan)).fillna(0.0).clip(lower=0)
    impact = k * sigma * np.sqrt(q_over_adv)
    return impact.fillna(0.0), q_over_adv


def check_liquidity_constraints(q_over_adv: pd.DataFrame) -> dict:
    """
    Flag dates/tickers where order quantity exceeds 1% of average daily volume.

    At $25K with ~$1,667 per ETF position, Q/ADV for liquid ETFs will be
    effectively 0. During inverted yield curve periods (6 active ETFs) positions
    may grow to ~$2,778 — still well within liquidity bounds for these ETFs.
    """
    constrained = q_over_adv > 0.01
    n_bars = int(constrained.sum().sum())
    if n_bars == 0:
        return {"liquidity_constrained": False, "constrained_bars": 0}

    report = {"liquidity_constrained": True, "constrained_bars": n_bars, "detail": {}}
    for ticker in constrained.columns:
        bad_dates = constrained[ticker][constrained[ticker]].index
        if len(bad_dates) > 0:
            report["detail"][ticker] = [str(d.date()) for d in bad_dates[:5]]
            warnings.warn(
                f"Liquidity constraint: {ticker} Q/ADV > 0.01 on {len(bad_dates)} bars. "
                "Order exceeds 1% of average daily volume."
            )
    return report


# ── Strategy Runner ────────────────────────────────────────────────────────────

def run_backtest(
    params: dict = PARAMETERS,
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    return_portfolio: bool = False,
) -> dict:
    """
    Run H07c Multi-Asset TSMOM (yield curve filter + dynamic lookback) and return metrics dict.

    Regime system:
    1. Yield curve filter (primary, new in H07c):
       - YC_spread(T) = ^TNX - ^IRX at month-end T
       - If YC_spread < yield_curve_threshold AND ETF is duration-sensitive → flat for M+1
    2. VIX regime gate (from H07b, unchanged):
       - VIX > crisis_threshold at month-end T → flat for M+1 (all ETFs)
       - VIX > stress_threshold at month-end T → 50% scale for M+1
       - Intramonth: VIX > crisis_threshold on any day → force-exit next day
    3. Dynamic lookback (new in H07c):
       - VIX ≤ dynamic_lookback_vix_threshold → 12-month lookback (normal)
       - VIX > dynamic_lookback_vix_threshold → 6-month lookback (stress)

    Position sizing (unchanged from H07b):
    - Equal capital split per ticker: cash_per_ticker = init_cash / n_tickers
    - Normal (scale=1.0): invest full cash_per_ticker per entry
    - Stress (scale=0.5): invest cash_per_ticker × 0.5 per entry
    - Crisis (scale=0.0): no entries; existing positions exited

    Transaction costs:
    - Fixed: $0.005/share → fraction = 0.005 / close
    - Slippage: 0.05% base + square-root market impact
    - Intramonth stop: sl_stop = intramonth_stop_pct (from entry price, per-asset)

    Returns:
        dict with sharpe, max_drawdown, win_rate, win_loss_ratio, profit_factor,
        total_return, trade_count, tickers_traded, data_quality, yield_curve_quality,
        liquidity, vix_regime_stats, yc_regime_stats, filter_stats, and optionally 'portfolio'.

    Raises:
        ValueError: if no price data available or insufficient history.
    """
    # 1. Resolve universe (XLRE → IYR substitution if needed)
    universe = resolve_universe(list(params.get("universe", PARAMETERS["universe"])), start)

    # 2. Download price, volume, VIX, and yield curve data
    close, volume = download_data(universe, start, end)

    # Download VIX and yield curve with 2-year pre-start buffer for lookback coverage
    # 2-year buffer ensures 12-month lookback has data available at IS start (2018-01-01)
    pre_start = str((pd.Timestamp(start) - pd.DateOffset(years=2)).date())
    vix_close = download_vix(pre_start, end)
    yc_df = download_yield_curve(pre_start, end)

    # 3. Data quality checks
    quality_report = check_data_quality(close)
    yc_quality_report = check_yield_curve_data(yc_df)

    close = close.dropna(axis=1, how="all")
    if close.empty:
        raise ValueError(f"No price data for {universe} in {start}–{end}.")

    # Use normal lookback for minimum history requirement (12 months is the longer one)
    min_required = params["lookback_months_normal"] * TRADING_DAYS_PER_MONTH + 20
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    yc_spread = yc_df["YC_spread"]

    # 4. Generate signals (with yield curve filter and dynamic lookback)
    entries, exits, vix_daily_scale, filter_stats = generate_daily_signals(
        close, vix_close, yc_spread, params
    )

    # 5. Market impact and transaction costs
    market_impact, q_over_adv = compute_market_impact(close, volume, params)
    liquidity_report = check_liquidity_constraints(q_over_adv)
    fees = 0.005 / close
    slippage = 0.0005 + market_impact

    # VIX regime statistics for reporting
    vix_window = vix_close.reindex(close.index, method="ffill")
    n_crisis = int((vix_window > params["vix_crisis_threshold"]).sum())
    n_stress = int(
        ((vix_window > params["vix_stress_threshold"]) &
         (vix_window <= params["vix_crisis_threshold"])).sum()
    )
    n_normal = int((vix_window <= params["vix_stress_threshold"]).sum())
    vix_regime_stats = {
        "days_crisis": n_crisis,
        "days_stress": n_stress,
        "days_normal": n_normal,
        "pct_crisis": round(n_crisis / max(1, len(vix_window)), 4),
        "pct_stress": round(n_stress / max(1, len(vix_window)), 4),
        "pct_normal": round(n_normal / max(1, len(vix_window)), 4),
    }

    # Yield curve regime statistics for reporting
    yc_window = yc_spread.reindex(close.index, method="ffill")
    n_yc_inverted = int((yc_window < params["yield_curve_threshold"]).sum())
    n_yc_normal = int((yc_window >= params["yield_curve_threshold"]).sum())
    yc_regime_stats = {
        "days_inverted": n_yc_inverted,
        "days_normal": n_yc_normal,
        "pct_inverted": round(n_yc_inverted / max(1, len(yc_window)), 4),
        "pct_normal": round(n_yc_normal / max(1, len(yc_window)), 4),
        "yc_threshold": params["yield_curve_threshold"],
    }

    empty_result = {
        "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0, "win_loss_ratio": 0.0,
        "profit_factor": 0.0, "total_return": 0.0, "trade_count": 0,
        "period": f"{start} to {end}", "tickers_traded": list(close.columns),
        "data_quality": quality_report, "yield_curve_quality": yc_quality_report,
        "liquidity": liquidity_report, "vix_regime_stats": vix_regime_stats,
        "yc_regime_stats": yc_regime_stats, "filter_stats": filter_stats,
    }

    if entries.sum().sum() == 0:
        warnings.warn("No entry signals generated — returning empty result.")
        return empty_result

    # 6. Build portfolio (equal capital split per ticker, VIX-scaled sizing)
    n_tickers = len(close.columns)
    cash_per_ticker = params.get("init_cash", 25000) / n_tickers

    # Build size DataFrame: on entry bars, size = cash_per_ticker × vix_scale (dollars)
    size_dollars = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    entry_mask = entries.values
    for col_idx in range(len(close.columns)):
        for row_idx in np.where(entry_mask[:, col_idx])[0]:
            scale = float(vix_daily_scale.iloc[row_idx])
            size_dollars.iloc[row_idx, col_idx] = cash_per_ticker * max(scale, 0.5)

    try:
        pf = vbt.Portfolio.from_signals(
            close,
            entries=entries,
            exits=exits,
            size=size_dollars,
            size_type="value",
            sl_stop=params.get("intramonth_stop_pct", 0.20),
            fees=fees,
            slippage=slippage,
            init_cash=cash_per_ticker,
            group_by=False,
        )
    except Exception as exc:
        # Fallback: if VIX-scaled sizing fails, use default sizing
        warnings.warn(f"VIX-scaled sizing failed ({exc}), falling back to default sizing.")
        pf = vbt.Portfolio.from_signals(
            close,
            entries=entries,
            exits=exits,
            sl_stop=params.get("intramonth_stop_pct", 0.20),
            fees=fees,
            slippage=slippage,
            init_cash=cash_per_ticker,
            group_by=False,
        )

    # 7. Portfolio-level metrics
    combined_value = pf.value().sum(axis=1)
    combined_returns = combined_value.pct_change().fillna(0).values
    sharpe = float(combined_returns.mean() / (combined_returns.std() + 1e-8) * np.sqrt(252))
    cum = np.cumprod(1 + combined_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(combined_value.iloc[-1] / combined_value.iloc[0] - 1)
    trade_count = int(pf.trades.count().sum())

    try:
        pnl_vals = pf.trades.pnl.values
        pnl_vals = pnl_vals[~np.isnan(pnl_vals)]
        win_rate = float(np.mean(pnl_vals > 0)) if len(pnl_vals) > 0 else 0.0
        wins = pnl_vals[pnl_vals > 0]
        losses = pnl_vals[pnl_vals < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
        profit_factor = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0
            else float("inf")
        )
    except Exception:
        pnl_vals = np.array([])
        win_rate = win_loss_ratio = profit_factor = 0.0

    if win_rate < 0.50 and win_loss_ratio < 1.2:
        warnings.warn(
            f"Win rate {win_rate:.1%} < 50% AND win/loss ratio {win_loss_ratio:.2f} < 1.2. "
            "Strategy may not pass Gate 1 thresholds."
        )

    result = {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "win_loss_ratio": win_loss_ratio,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "trade_count": trade_count,
        "period": f"{start} to {end}",
        "tickers_traded": list(close.columns),
        "data_quality": quality_report,
        "yield_curve_quality": yc_quality_report,
        "liquidity": liquidity_report,
        "vix_regime_stats": vix_regime_stats,
        "yc_regime_stats": yc_regime_stats,
        "filter_stats": filter_stats,
        "_combined_returns": combined_returns,
        "_pnl_vals": pnl_vals,
    }

    if return_portfolio:
        result["portfolio"] = pf

    return result


# ── Parameter Sensitivity Scan ─────────────────────────────────────────────────

def scan_parameters(
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Scan Sharpe across the H07c Gate 1 parameter grid.

    Parameter grid (per hypothesis 07c):
    - yield_curve_threshold:       [-0.25, 0.0, +0.25]   (new H07c parameter)
    - dynamic_lookback_vix_threshold: [15, 20, 25]         (new H07c parameter)
    - vix_stress_threshold:        [20, 25, 30]            (inherited from H07b)
    - intramonth_stop_pct:         [0.15, 0.20, 0.25]      (inherited from H07b)

    Gate 1 disqualification: Sharpe variance > 30% across any parameter dimension.
    """
    results: dict = {}

    grid = {
        "yield_curve_threshold": [-0.25, 0.0, 0.25],
        "dynamic_lookback_vix_threshold": [15, 20, 25],
        "vix_stress_threshold": [20, 25, 30],
        "intramonth_stop_pct": [0.15, 0.20, 0.25],
    }

    for param_name, values in grid.items():
        for val in values:
            p = {**base_params, param_name: val}
            key = f"{param_name}={val}"
            try:
                r = run_backtest(params=p, start=start, end=end)
                results[key] = round(r["sharpe"], 4)
            except Exception as exc:
                results[key] = f"error: {exc}"

    sharpe_nums = [v for v in results.values() if isinstance(v, float) and not np.isnan(v)]
    if len(sharpe_nums) > 1:
        sharpe_range = max(sharpe_nums) - min(sharpe_nums)
        sharpe_mean = np.mean(sharpe_nums)
        variance_pct = sharpe_range / abs(sharpe_mean) if abs(sharpe_mean) > 0 else float("inf")
        results["_sharpe_range"] = round(sharpe_range, 4)
        results["_sharpe_variance_pct"] = round(variance_pct, 4)
        results["_gate1_variance_flag"] = (
            f"PASS: variance {variance_pct:.1%} ≤ 30%"
            if variance_pct <= 0.30
            else f"FAIL: variance {variance_pct:.1%} > 30%"
        )

    return results


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="H07c Multi-Asset TSMOM (yield curve filter + dynamic lookback) backtest runner."
    )
    parser.add_argument("--plot", action="store_true",
                        help="Show interactive Plotly chart after IS backtest.")
    args = parser.parse_args()

    EXCLUDE_KEYS = ("portfolio", "data_quality", "yield_curve_quality", "liquidity",
                    "_combined_returns", "_pnl_vals")

    print("H07c: Running IS backtest (2018-01-01 to 2021-12-31)...")
    is_result = run_backtest(start="2018-01-01", end="2021-12-31", return_portfolio=args.plot)
    safe_is = {k: v for k, v in is_result.items() if k not in EXCLUDE_KEYS}
    print("IS:", safe_is)

    print("\nYield curve quality (IS):")
    print(is_result.get("yield_curve_quality", {}))

    print("\nYield curve regime stats (IS):")
    print(is_result.get("yc_regime_stats", {}))

    print("\nVIX regime stats (IS):")
    print(is_result.get("vix_regime_stats", {}))

    print("\nFilter stats (IS):")
    print(is_result.get("filter_stats", {}))

    if args.plot:
        pf = is_result["portfolio"]
        fig = pf.plot()
        fig.show()

    print("\nH07c: Running OOS backtest (2022-01-01 to 2023-12-31)...")
    oos_result = run_backtest(start="2022-01-01", end="2023-12-31")
    safe_oos = {k: v for k, v in oos_result.items() if k not in EXCLUDE_KEYS}
    print("OOS:", safe_oos)

    print("\nFilter stats (OOS):")
    print(oos_result.get("filter_stats", {}))
