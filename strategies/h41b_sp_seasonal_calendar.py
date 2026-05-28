"""
Strategy: H41b S&P Seasonal Calendar Effect
Author: Strategy Coder Agent
Date: 2026-05-28
Hypothesis: Four structurally independent seasonal anomalies — January Effect,
            Sell in May, Santa Claus Rally, and OpEx Week Drift — generate
            positive edge on SPY and sector ETFs (XLF, XLK, XLE) when traded
            with appropriate calendar-based entry/exit rules.
Asset class: equities (ETFs: SPY, XLF, XLK, XLE)
Parent task: QUA-8
References: Haugen & Jorion (1996) — January Effect; Bouman & Jacobsen (2002) — Sell in May;
            Yale Hirsch — Santa Claus Rally; McConnell & Xu (2008) — OpEx Week;
            research/hypotheses/h41b_sp_seasonal_calendar.md

PF-4 STATUS: OpEx–PreHoliday co-occurrence analysis computed inline in
             compute_opex_preholiday_overlap(). See comments at that function.
             If overlap > 30%, `prefer_opex_over_preholiday` param (default True)
             resolves the conflict.

Data Quality Checklist:
  - Survivorship bias: Not applicable. SPY, XLF, XLK, XLE are all current,
    long-lived ETFs; no point-in-time selection issue.
  - Split/dividend adjustment: auto_adjust=True in all yfinance downloads.
  - Gap check: Tickers with >5 missing trading days are flagged at runtime
    via _check_data_gaps(). Warning logged and recorded in DATA_QUALITY dict.
  - Earnings exclusion: Not applicable. Strategy is calendar-signal based;
    earnings dates are irrelevant.
  - Delisted tickers: Not applicable. All four ETFs remain active.
"""

import logging
import warnings
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ── Logging ──────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Parameters ───────────────────────────────────────────────────────────────────
PARAMETERS = {
    # Tickers
    "tickers": ["SPY", "XLF", "XLK", "XLE"],

    # January Effect: enter last N trading days of December; exit M-th trading day of January
    "jan_effect_entry_offset": 5,   # last 5 trading days of December (range: 3–7)
    "jan_effect_exit_day": 5,       # exit on 5th trading day of January (range: 3–7)

    # Sell in May: short the "summer" gap; be long Nov 1 → May 1
    # Entry: first trading day of November; exit: first trading day of May
    "sell_may_entry_month": 11,     # November
    "sell_may_exit_month": 5,       # May

    # Santa Claus Rally: enter N trading days before Dec 31; exit on M-th trading day of January
    "santa_entry_offset": 5,        # 5 trading days before Dec 31 (range: 3–7)
    "santa_exit_day": 2,            # exit on 2nd trading day of January (range: 1–4)

    # OpEx Week Drift: enter Monday of 3rd-Friday week; exit Thursday
    "opex_exit_on_thursday": True,  # True=Thursday exit; False=Friday

    # VIX circuit breaker (applied per-ticker)
    "vix_circuit_breaker": 35.0,    # exit any open position if VIX closes above this (range: 30–45)
    "vix_ticker": "^VIX",

    # Conflict resolution: OpEx vs Pre-Holiday overlap (PF-4)
    "prefer_opex_over_preholiday": True,  # if True and OpEx overlaps a pre-holiday day, keep OpEx

    # Transaction cost model (Engineering Director standard)
    "fixed_cost_per_share": 0.005,   # $0.005/share fixed
    "slippage_pct": 0.0005,          # 0.05% slippage
    "market_impact_k": 0.1,          # Almgren-Chriss square-root model k (Johnson 2010)
    "sigma_window": 20,              # rolling vol window for market impact σ
    "adv_window": 20,                # rolling ADV window
    "order_qty": 100,                # default order size in shares
    "liquidity_threshold": 0.01,     # Q/ADV flag threshold (>1% of ADV = liquidity-constrained)

    # Portfolio
    "init_cash": 25000.0,
}

# ── Data Quality dict (updated at runtime) ───────────────────────────────────────
DATA_QUALITY: dict = {
    "survivorship_bias": "not_applicable — SPY/XLF/XLK/XLE are active ETFs with no point-in-time issue",
    "price_adjustments": "auto_adjust=True via yfinance for all tickers",
    "data_gaps": {},       # populated per ticker in _check_data_gaps()
    "earnings_exclusion": "not_applicable — calendar-signal strategy",
    "delisted_tickers": "not_applicable — all four ETFs remain active",
}

# ── Trading day constants ─────────────────────────────────────────────────────────
TRADING_DAYS_PER_YEAR = 252


# ── Data download ─────────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw.empty:
        raise ValueError(f"No data returned for {ticker} [{start} → {end}]")
    return raw


def _check_data_gaps(prices: pd.Series, ticker: str) -> None:
    """
    Flag tickers with >5 consecutive missing business days.
    Updates global DATA_QUALITY["data_gaps"][ticker] with result.
    """
    all_bdays = pd.bdate_range(prices.index.min(), prices.index.max())
    missing = all_bdays.difference(prices.index)
    if len(missing) == 0:
        DATA_QUALITY["data_gaps"][ticker] = "ok: no_gaps"
        return

    missing_s = pd.Series(missing)
    runs: list[int] = []
    run = 1
    for i in range(1, len(missing_s)):
        if (missing_s.iloc[i] - missing_s.iloc[i - 1]).days == 1:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)
    max_run = max(runs)

    if max_run > 5:
        msg = f"WARNING: {ticker} has consecutive missing-weekday run of {max_run}"
        logger.warning(msg)
        DATA_QUALITY["data_gaps"][ticker] = f"flagged: max_consecutive_missing={max_run}"
    else:
        DATA_QUALITY["data_gaps"][ticker] = f"ok: max_consecutive_missing={max_run}"


def download_data(
    tickers: list[str],
    start: str,
    end: str,
    vix_ticker: str = "^VIX",
) -> dict[str, pd.DataFrame]:
    """
    Download OHLCV for each ticker plus VIX Close. Includes 90-day warmup period
    before `start` so rolling cost computations (sigma, ADV) are warm from day one.

    Returns:
        dict keyed by ticker (e.g. "SPY") → OHLCV DataFrame, plus "VIX" → Close Series.
    Raises ValueError if any required column is missing or data is insufficient.
    """
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=90)).strftime("%Y-%m-%d")

    result: dict = {}
    for ticker in tickers:
        logger.info("Downloading %s [%s → %s]", ticker, warmup_start, end)
        df = _download_single(ticker, warmup_start, end)
        required_cols = {"Open", "High", "Low", "Close", "Volume"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns for {ticker}: {missing}")
        if len(df) < 50:
            raise ValueError(f"Insufficient data for {ticker}: {len(df)} bars")
        _check_data_gaps(df["Close"], ticker)
        result[ticker] = df

    logger.info("Downloading VIX [%s → %s]", warmup_start, end)
    vix_raw = _download_single(vix_ticker, warmup_start, end)
    if "Close" not in vix_raw.columns:
        raise ValueError(f"Missing Close for {vix_ticker}")
    result["VIX"] = vix_raw[["Close"]].rename(columns={"Close": "vix"})

    return result


# ── Calendar helpers ──────────────────────────────────────────────────────────────

def _get_nyse_holidays(year_start: int, year_end: int) -> list:
    """
    Retrieve NYSE holiday dates for PF-4 pre-holiday overlap calculation.
    Prefers pandas_market_calendars; falls back to pandas Federal holiday rules.
    """
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(
            start_date=f"{year_start}-01-01", end_date=f"{year_end}-12-31"
        )
        full_bdays = pd.bdate_range(f"{year_start}-01-01", f"{year_end}-12-31")
        open_days = set(schedule.index.normalize())
        return [pd.Timestamp(d) for d in full_bdays if pd.Timestamp(d) not in open_days]
    except ImportError:
        warnings.warn("pandas_market_calendars not installed — using pandas Federal holiday fallback.")
        return _manual_nyse_holidays(year_start, year_end)


def _manual_nyse_holidays(year_start: int, year_end: int) -> list:
    from pandas.tseries.holiday import (  # noqa: PLC0415
        AbstractHolidayCalendar, Holiday, nearest_workday,
        USMartinLutherKingJr, USPresidentsDay, USMemorialDay,
        USLaborDay, USThanksgivingDay,
    )

    class _NYSECal(AbstractHolidayCalendar):
        rules = [
            Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
            USMartinLutherKingJr,
            USPresidentsDay,
            USMemorialDay,
            Holiday("Juneteenth", month=6, day=19, observance=nearest_workday),
            Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
            USLaborDay,
            USThanksgivingDay,
            Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
        ]

    cal = _NYSECal()
    holidays = cal.holidays(start=f"{year_start}-01-01", end=f"{year_end}-12-31")
    return [pd.Timestamp(d) for d in holidays]


# ── PF-4: OpEx ↔ Pre-Holiday Overlap Analysis ────────────────────────────────────

def compute_opex_preholiday_overlap(
    trading_dates: pd.DatetimeIndex,
    params: dict,
) -> dict:
    """
    PF-4 gate: Compute the fraction of OpEx-week Monday entries that fall within
    5 trading days of a US market holiday.

    Method:
    1. Identify all OpEx-Monday entry dates from the trading calendar.
    2. Identify all pre-holiday windows (5 trading days before each NYSE holiday).
    3. Compute overlap count / total OpEx entries.

    Returns:
        dict with keys: opex_count, overlap_count, overlap_rate,
                        pf4_pass (bool: overlap_rate <= 0.30),
                        conflict_resolution_required (bool),
                        sample_conflicts (list of date strings).
    """
    year_start = trading_dates[0].year
    year_end = trading_dates[-1].year
    trading_list = sorted(trading_dates)
    trading_set = set(trading_list)

    # Compute OpEx entry dates (Mondays of 3rd-Friday weeks)
    opex_entries: list = []
    for m_start in sorted({pd.Timestamp(d.year, d.month, 1) for d in trading_list}):
        year, month = m_start.year, m_start.month
        first_day = pd.Timestamp(year, month, 1)
        days_to_friday = (4 - first_day.weekday()) % 7
        first_friday = first_day + pd.Timedelta(days=days_to_friday)
        third_friday = first_friday + pd.Timedelta(weeks=2)
        opex_monday = third_friday - pd.Timedelta(days=third_friday.weekday())
        # snap forward if holiday
        t = opex_monday
        for _ in range(7):
            if t in trading_set:
                opex_entries.append(t)
                break
            t += pd.Timedelta(days=1)

    # Build pre-holiday 5-day windows: collect all trading days within 5 days before each holiday
    holidays = _get_nyse_holidays(year_start - 1, year_end + 1)
    preholiday_window: set = set()
    for holiday_ts in holidays:
        # find the last 5 trading days before the holiday
        candidates = [d for d in trading_list if d < holiday_ts]
        for pre_day in candidates[-5:]:
            preholiday_window.add(pre_day)

    overlap_dates = [d for d in opex_entries if d in preholiday_window]
    opex_count = len(opex_entries)
    overlap_count = len(overlap_dates)
    overlap_rate = overlap_count / opex_count if opex_count > 0 else 0.0

    pf4_pass = overlap_rate <= 0.30
    conflict_resolution_required = not pf4_pass

    logger.info(
        "PF-4 OpEx/PreHoliday overlap: %d/%d OpEx entries overlap (%.1f%%) — %s",
        overlap_count, opex_count, overlap_rate * 100,
        "PASS" if pf4_pass else "WARN: >30% overlap — conflict-resolution param applied",
    )

    return {
        "opex_count": opex_count,
        "overlap_count": overlap_count,
        "overlap_rate": round(overlap_rate, 4),
        "pf4_pass": pf4_pass,
        "conflict_resolution_required": conflict_resolution_required,
        "sample_conflicts": [str(d.date()) for d in overlap_dates[:10]],
    }


# ── Signal calendar builders ──────────────────────────────────────────────────────

def _build_jan_effect_signals(
    trading_dates: pd.DatetimeIndex, params: dict
) -> dict:
    """
    January Effect: enter on N-th-to-last trading day of December,
    exit on M-th trading day of January.

    Returns dict: {entry_date → exit_date}.
    """
    entry_offset = params["jan_effect_entry_offset"]
    exit_day = params["jan_effect_exit_day"]

    trading_list = sorted(trading_dates)
    df_dates = pd.DataFrame({"date": trading_list})
    df_dates["ym"] = df_dates["date"].dt.to_period("M")

    month_map: dict = {
        ym: sorted(df_dates[df_dates["ym"] == ym]["date"].tolist())
        for ym in df_dates["ym"].unique()
    }

    signals: dict = {}
    for ym, days in month_map.items():
        if ym.month != 12:
            continue
        n = len(days)
        # last entry_offset trading days: index n-entry_offset
        entry_idx = n - entry_offset
        if not (0 <= entry_idx < n):
            continue
        entry_date = days[entry_idx]

        # Exit: M-th trading day of the following January
        jan_period = ym + 1
        jan_days = month_map.get(jan_period, [])
        exit_idx = exit_day - 1   # 5th day → index 4
        if not (0 <= exit_idx < len(jan_days)):
            continue
        exit_date = jan_days[exit_idx]

        signals[entry_date] = exit_date

    return signals


def _build_sell_in_may_signals(
    trading_dates: pd.DatetimeIndex, params: dict
) -> dict:
    """
    Sell in May (long Nov→May): enter on first trading day of November,
    exit on first trading day of May.

    Returns dict: {entry_date → exit_date}.
    """
    entry_month = params["sell_may_entry_month"]   # November = 11
    exit_month = params["sell_may_exit_month"]     # May = 5

    trading_list = sorted(trading_dates)
    df_dates = pd.DataFrame({"date": trading_list})
    df_dates["ym"] = df_dates["date"].dt.to_period("M")

    month_map: dict = {
        ym: sorted(df_dates[df_dates["ym"] == ym]["date"].tolist())
        for ym in df_dates["ym"].unique()
    }

    signals: dict = {}
    for ym, days in month_map.items():
        if ym.month != entry_month:
            continue
        if not days:
            continue
        entry_date = days[0]   # first trading day of November

        # Exit on first trading day of following May (6 months later)
        may_period = ym + 6
        may_days = month_map.get(may_period, [])
        if not may_days:
            continue
        exit_date = may_days[0]

        signals[entry_date] = exit_date

    return signals


def _build_santa_claus_signals(
    trading_dates: pd.DatetimeIndex, params: dict
) -> dict:
    """
    Santa Claus Rally: enter N trading days before Dec 31 (inclusive),
    exit on M-th trading day of January.

    Returns dict: {entry_date → exit_date}.
    """
    entry_offset = params["santa_entry_offset"]
    exit_day = params["santa_exit_day"]

    trading_list = sorted(trading_dates)
    df_dates = pd.DataFrame({"date": trading_list})
    df_dates["ym"] = df_dates["date"].dt.to_period("M")

    month_map: dict = {
        ym: sorted(df_dates[df_dates["ym"] == ym]["date"].tolist())
        for ym in df_dates["ym"].unique()
    }

    signals: dict = {}
    for ym, days in month_map.items():
        if ym.month != 12:
            continue
        n = len(days)
        # 5 trading days before Dec 31 = the (n - entry_offset)-th trading day of December
        entry_idx = n - entry_offset
        if not (0 <= entry_idx < n):
            continue
        entry_date = days[entry_idx]

        jan_period = ym + 1
        jan_days = month_map.get(jan_period, [])
        exit_idx = exit_day - 1
        if not (0 <= exit_idx < len(jan_days)):
            continue
        exit_date = jan_days[exit_idx]

        signals[entry_date] = exit_date

    return signals


def _build_opex_signals(
    trading_dates: pd.DatetimeIndex,
    params: dict,
    preholiday_window: Optional[set] = None,
) -> dict:
    """
    OpEx Week Drift: enter Monday of the week containing the 3rd Friday of each month,
    exit Thursday of that week (or Friday if opex_exit_on_thursday=False).

    If preholiday_window is provided and prefer_opex_over_preholiday=False, skip
    OpEx entries that overlap with a pre-holiday window (PF-4 conflict resolution).

    Returns dict: {entry_date → exit_date}.
    """
    exit_on_thursday = params["opex_exit_on_thursday"]
    prefer_opex = params["prefer_opex_over_preholiday"]

    trading_list = sorted(trading_dates)
    trading_set = set(trading_list)

    def snap_forward(ts):
        t = pd.Timestamp(ts)
        for _ in range(7):
            if t in trading_set:
                return t
            t += pd.Timedelta(days=1)
        return None

    def snap_backward(ts):
        t = pd.Timestamp(ts)
        for _ in range(7):
            if t in trading_set:
                return t
            t -= pd.Timedelta(days=1)
        return None

    signals: dict = {}
    for m_start in sorted({pd.Timestamp(d.year, d.month, 1) for d in trading_list}):
        year, month = m_start.year, m_start.month
        first_day = pd.Timestamp(year, month, 1)
        days_to_friday = (4 - first_day.weekday()) % 7
        first_friday = first_day + pd.Timedelta(days=days_to_friday)
        third_friday = first_friday + pd.Timedelta(weeks=2)
        opex_monday = third_friday - pd.Timedelta(days=third_friday.weekday())

        exit_raw = (
            opex_monday + pd.Timedelta(days=3)   # Thursday
            if exit_on_thursday
            else opex_monday + pd.Timedelta(days=4)   # Friday
        )

        entry_date = snap_forward(opex_monday)
        exit_date = snap_backward(exit_raw)

        if entry_date is None or exit_date is None:
            continue
        if entry_date >= exit_date:
            continue

        # PF-4 conflict resolution: skip this OpEx entry if it overlaps a pre-holiday window
        # and caller explicitly prefers pre-holiday over opex
        if preholiday_window is not None and not prefer_opex:
            if entry_date in preholiday_window:
                logger.debug(
                    "OpEx entry %s skipped: overlaps pre-holiday window (prefer_opex=False)",
                    entry_date.date(),
                )
                continue

        signals[entry_date] = exit_date

    return signals


# ── Signal generation ─────────────────────────────────────────────────────────────

def generate_signals(
    data: dict[str, pd.DataFrame],
    params: dict = PARAMETERS,
) -> dict[str, dict]:
    """
    Generate per-ticker entry/exit signal maps for all four seasonal effects.

    Uses the trading calendar from the first available ticker's index.

    Returns:
        Nested dict: {ticker: {signal_name: {entry_date: exit_date, ...}, ...}}
        Signal names: "jan_effect", "sell_in_may", "santa_claus", "opex_week"

    Also runs PF-4 overlap analysis and logs results.
    """
    tickers = params["tickers"]
    # Use the first main ticker's trading calendar as the canonical date index
    first_ticker = tickers[0]
    trading_dates: pd.DatetimeIndex = data[first_ticker].index

    # PF-4: compute overlap between OpEx and pre-holiday windows before building signal maps
    pf4 = compute_opex_preholiday_overlap(trading_dates, params)
    logger.info("PF-4 result: %s", pf4)

    # Build pre-holiday window set for OpEx conflict resolution
    year_start = trading_dates[0].year
    year_end = trading_dates[-1].year
    holidays = _get_nyse_holidays(year_start - 1, year_end + 1)
    trading_list = sorted(trading_dates)
    preholiday_window: set = set()
    for hts in holidays:
        candidates = [d for d in trading_list if d < hts]
        for pre_day in candidates[-5:]:
            preholiday_window.add(pre_day)

    jan_signals = _build_jan_effect_signals(trading_dates, params)
    sim_signals = _build_sell_in_may_signals(trading_dates, params)
    santa_signals = _build_santa_claus_signals(trading_dates, params)
    opex_signals = _build_opex_signals(trading_dates, params, preholiday_window=preholiday_window)

    logger.info(
        "Signal calendars: January Effect=%d, Sell-in-May=%d, "
        "Santa Claus=%d, OpEx Week=%d",
        len(jan_signals), len(sim_signals), len(santa_signals), len(opex_signals),
    )

    # All tickers share the same calendar; signal entry/exit dates are identical
    result: dict = {}
    for ticker in tickers:
        result[ticker] = {
            "jan_effect": jan_signals,
            "sell_in_may": sim_signals,
            "santa_claus": santa_signals,
            "opex_week": opex_signals,
        }

    return result


# ── Transaction cost model ────────────────────────────────────────────────────────

def _transaction_cost(
    price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    bar_idx: int,
    params: dict,
) -> tuple[float, bool]:
    """
    Canonical equities transaction cost (Engineering Director spec):
      fixed    = $0.005/share
      slippage = 0.05% of notional
      impact   = k × σ × sqrt(Q / ADV) × price × shares  (Almgren-Chriss sqrt model)

    Flags orders where Q/ADV > 1% as liquidity-constrained.
    Returns (total_cost_dollars, liquidity_constrained_bool).
    """
    fixed = params["fixed_cost_per_share"] * shares
    slippage = params["slippage_pct"] * price * shares

    sigma_s = close_series.pct_change().rolling(params["sigma_window"]).std()
    sigma = sigma_s.iloc[bar_idx] if bar_idx < len(sigma_s) else np.nan
    adv_s = vol_series.rolling(params["adv_window"]).mean()
    adv = adv_s.iloc[bar_idx] if bar_idx < len(adv_s) else np.nan

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000

    impact = params["market_impact_k"] * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > params["liquidity_threshold"])

    if liq_constrained:
        logger.warning(
            "LIQUIDITY_CONSTRAINED: %d shares = %.2f%% of ADV at bar %d",
            shares, shares / adv * 100, bar_idx,
        )

    return fixed + slippage + impact, liq_constrained


# ── Per-ticker simulation ─────────────────────────────────────────────────────────

def _simulate_ticker(
    ticker: str,
    ohlcv: pd.DataFrame,
    vix: pd.Series,
    ticker_signals: dict,
    params: dict,
) -> tuple[list, pd.Series]:
    """
    Simulate all four seasonal signals for a single ticker using an OR-logic
    overlap approach: any signal entry triggers a position if in cash; exits
    happen when the latest active signal expires or VIX circuit breaker fires.

    Args:
        ticker_signals: dict {signal_name: {entry_date: exit_date}}

    Returns:
        (trade_log list, equity pd.Series)
    """
    vix_cb = params["vix_circuit_breaker"]
    init_cash = float(params["init_cash"])
    close_s = ohlcv["Close"]
    vol_s = ohlcv["Volume"]
    vix_aligned = vix.reindex(ohlcv.index, fill_value=np.nan)

    # Flatten signal map: {entry_date: (exit_date, signal_name)}
    all_entries: dict = {}
    for sig_name, sig_map in ticker_signals.items():
        for entry_date, exit_date in sig_map.items():
            if entry_date not in all_entries:
                all_entries[entry_date] = []
            all_entries[entry_date].append((exit_date, sig_name))

    dates = ohlcv.index
    n = len(dates)

    trade_log: list = []
    equity_vals: list = []

    capital = init_cash
    in_pos = False
    entry_date_ts = None
    entry_price_eff = 0.0
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_bar_idx = -1
    active_exits: dict = {}     # {signal_name: exit_date}
    active_signal_names: set = set()

    for i, date in enumerate(dates):
        close_i = float(close_s.iloc[i])
        vix_i = float(vix_aligned.iloc[i]) if not pd.isna(vix_aligned.iloc[i]) else np.nan

        # ── VIX circuit breaker ───────────────────────────────────────────────
        if in_pos and not pd.isna(vix_i) and vix_i > vix_cb:
            xcost, xliq = _transaction_cost(close_i, entry_shares, close_s, vol_s, i, params)
            eff_xp = close_i - xcost / max(entry_shares, 1)
            pnl = (eff_xp - entry_price_eff) * entry_shares
            capital += eff_xp * entry_shares

            trade_log.append({
                "ticker": ticker,
                "entry_date": entry_date_ts.date(),
                "exit_date": date.date(),
                "entry_price": round(entry_price_eff, 4),
                "exit_price": round(eff_xp, 4),
                "shares": entry_shares,
                "pnl": round(pnl, 2),
                "entry_cost": round(entry_cost_total, 4),
                "exit_cost": round(xcost, 4),
                "transaction_cost": round(entry_cost_total + xcost, 4),
                "liquidity_constrained": entry_liq or xliq,
                "hold_days": i - entry_bar_idx,
                "signal_types": ",".join(sorted(active_signal_names)),
                "exit_reason": "VIX_CIRCUIT_BREAKER",
            })
            in_pos = False
            active_exits = {}
            active_signal_names = set()
            entry_date_ts = None

        # ── New signals firing today ──────────────────────────────────────────
        todays_signals = all_entries.get(date, [])
        if in_pos:
            # Extend active set with new signals
            for exit_date, sig_name in todays_signals:
                if sig_name not in active_signal_names:
                    active_exits[sig_name] = exit_date
                    active_signal_names.add(sig_name)

        # ── Exit check ───────────────────────────────────────────────────────
        if in_pos and active_exits:
            latest_exit = max(active_exits.values())
            if date >= latest_exit and date > entry_date_ts:
                xcost, xliq = _transaction_cost(close_i, entry_shares, close_s, vol_s, i, params)
                eff_xp = close_i - xcost / max(entry_shares, 1)
                pnl = (eff_xp - entry_price_eff) * entry_shares
                capital += eff_xp * entry_shares

                trade_log.append({
                    "ticker": ticker,
                    "entry_date": entry_date_ts.date(),
                    "exit_date": date.date(),
                    "entry_price": round(entry_price_eff, 4),
                    "exit_price": round(eff_xp, 4),
                    "shares": entry_shares,
                    "pnl": round(pnl, 2),
                    "entry_cost": round(entry_cost_total, 4),
                    "exit_cost": round(xcost, 4),
                    "transaction_cost": round(entry_cost_total + xcost, 4),
                    "liquidity_constrained": entry_liq or xliq,
                    "hold_days": i - entry_bar_idx,
                    "signal_types": ",".join(sorted(active_signal_names)),
                    "exit_reason": "CALENDAR",
                })
                in_pos = False
                active_exits = {}
                active_signal_names = set()
                entry_date_ts = None

        # ── Enter if signal fires and we're flat ──────────────────────────────
        if not in_pos and todays_signals and close_i > 0 and not pd.isna(close_i):
            shares = int(capital / close_i)
            if shares > 0:
                cost, liq = _transaction_cost(close_i, shares, close_s, vol_s, i, params)
                eff_ep = close_i + cost / shares
                capital -= eff_ep * shares

                in_pos = True
                entry_date_ts = date
                entry_price_eff = eff_ep
                entry_shares = shares
                entry_cost_total = cost
                entry_liq = liq
                entry_bar_idx = i
                for exit_date, sig_name in todays_signals:
                    active_exits[sig_name] = exit_date
                    active_signal_names.add(sig_name)

        # ── Daily mark-to-market ──────────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        equity_vals.append(mtm)

    # Force-close open position at end of data
    if in_pos and n > 0:
        i = n - 1
        close_f = float(close_s.iloc[i])
        date_f = dates[i]
        xcost, xliq = _transaction_cost(close_f, entry_shares, close_s, vol_s, i, params)
        eff_xp = close_f - xcost / max(entry_shares, 1)
        pnl = (eff_xp - entry_price_eff) * entry_shares
        capital += eff_xp * entry_shares

        trade_log.append({
            "ticker": ticker,
            "entry_date": entry_date_ts.date(),
            "exit_date": date_f.date(),
            "entry_price": round(entry_price_eff, 4),
            "exit_price": round(eff_xp, 4),
            "shares": entry_shares,
            "pnl": round(pnl, 2),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(xcost, 4),
            "transaction_cost": round(entry_cost_total + xcost, 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_days": i - entry_bar_idx,
            "signal_types": ",".join(sorted(active_signal_names)),
            "exit_reason": "END_OF_DATA",
        })
        if equity_vals:
            equity_vals[-1] = capital

    equity = pd.Series(equity_vals, index=dates, name=ticker)
    return trade_log, equity


# ── Main backtest entry point ─────────────────────────────────────────────────────

def run_backtest(
    data: dict[str, pd.DataFrame],
    params: dict = PARAMETERS,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """
    Simulate all four seasonal signals across all tickers in params["tickers"].
    Combines results into aggregate metrics (equal-weight across tickers).

    Args:
        data: output of download_data() — includes per-ticker OHLCV and "VIX"
        params: strategy parameters dict
        start: restrict backtest to this start date (ISO string); if None, uses full data
        end: restrict backtest to this end date (ISO string); if None, uses full data

    Returns:
        dict with keys: trades (DataFrame), equity_curves (dict ticker→Series),
                        aggregate_equity (Series), metrics (dict), data_quality (dict),
                        pf4_analysis (dict), params (dict).
    """
    tickers = params["tickers"]
    vix_series = data["VIX"]["vix"]

    # Generate signal calendars (includes PF-4 analysis)
    signals_by_ticker = generate_signals(data, params)

    all_trades: list = []
    equity_curves: dict = {}

    for ticker in tickers:
        ohlcv = data[ticker].copy()
        if start:
            ohlcv = ohlcv.loc[ohlcv.index >= pd.Timestamp(start)]
        if end:
            ohlcv = ohlcv.loc[ohlcv.index <= pd.Timestamp(end)]

        if len(ohlcv) < 10:
            logger.warning("Insufficient data for %s after date filtering — skipping", ticker)
            continue

        # Trim signal maps to the backtest window
        ticker_signals: dict = {}
        for sig_name, sig_map in signals_by_ticker[ticker].items():
            ts_start = ohlcv.index[0]
            ts_end = ohlcv.index[-1]
            ticker_signals[sig_name] = {
                k: v for k, v in sig_map.items()
                if k >= ts_start and k <= ts_end
            }

        vix_trimmed = vix_series.reindex(ohlcv.index)
        trade_log, equity = _simulate_ticker(
            ticker, ohlcv, vix_trimmed, ticker_signals, params
        )

        all_trades.extend(trade_log)
        equity_curves[ticker] = equity

    # ── Aggregate equity: equal-weight average across tickers ────────────────
    if equity_curves:
        eq_df = pd.DataFrame(equity_curves)
        eq_df = eq_df.ffill()
        agg_equity = eq_df.mean(axis=1)
        agg_equity.name = "aggregate"
    else:
        agg_equity = pd.Series(dtype=float)

    # ── Compute metrics ───────────────────────────────────────────────────────
    trades_df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    daily_returns = agg_equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values
    sharpe = 0.0
    if len(ret_arr) > 1 and ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    n_trades = len(trades_df)
    win_rate = 0.0
    profit_factor = 0.0
    if n_trades > 0 and "pnl" in trades_df.columns:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        winners_pnl = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losers_pnl = abs(trades_df.loc[trades_df["pnl"] <= 0, "pnl"].sum())
        profit_factor = round(winners_pnl / losers_pnl, 4) if losers_pnl > 0 else float("inf")

    has_lc_col = n_trades > 0 and "liquidity_constrained" in trades_df.columns
    lc_count = int(trades_df["liquidity_constrained"].sum()) if has_lc_col else 0
    if lc_count > 0:
        logger.warning(
            "Liquidity-constrained trades: %d (Q/ADV > %.1f%%)",
            lc_count, params["liquidity_threshold"] * 100,
        )

    # Per-signal breakdown
    signal_breakdown: dict = {}
    if n_trades > 0 and "signal_types" in trades_df.columns:
        for sig_name in ["jan_effect", "sell_in_may", "santa_claus", "opex_week"]:
            mask = trades_df["signal_types"].str.contains(sig_name, na=False)
            sig_trades = trades_df[mask]
            if not sig_trades.empty:
                signal_breakdown[sig_name] = {
                    "count": len(sig_trades),
                    "win_rate": round(float((sig_trades["pnl"] > 0).mean()), 4),
                    "total_pnl": round(float(sig_trades["pnl"].sum()), 2),
                }

    pf4_analysis = compute_opex_preholiday_overlap(
        data[tickers[0]].index if tickers else pd.DatetimeIndex([]), params
    )

    metrics = {
        "sharpe_ratio": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "liquidity_constrained_count": lc_count,
        "signal_breakdown": signal_breakdown,
    }

    logger.info("H41b results: %s", {k: v for k, v in metrics.items() if k != "signal_breakdown"})

    return {
        "trades": trades_df,
        "equity_curves": equity_curves,
        "aggregate_equity": agg_equity,
        "metrics": metrics,
        "data_quality": DATA_QUALITY.copy(),
        "pf4_analysis": pf4_analysis,
        "params": params,
    }


# ── Orchestrator-compatible entry point ──────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
) -> dict:
    """
    Orchestrator-compatible entry point. Downloads data and runs the full backtest.

    `ticker` is accepted for interface compatibility but the strategy always
    runs on all tickers in params["tickers"]. If `ticker` is not in the list,
    it is prepended.

    Returns the full run_backtest() result dict plus a "summary" key with
    scalar metrics for the orchestrator's metrics store.
    """
    p = (params or PARAMETERS).copy()
    if ticker not in p["tickers"]:
        p["tickers"] = [ticker] + p["tickers"]

    data = download_data(p["tickers"], start, end, vix_ticker=p["vix_ticker"])

    # Trim OHLCV to the requested backtest window (warmup retained in data for rolling calcs)
    result = run_backtest(data, p, start=start, end=end)

    m = result["metrics"]
    result["summary"] = {
        "sharpe": m["sharpe_ratio"],
        "max_drawdown": m["max_drawdown"],
        "total_return": m["total_return"],
        "win_rate": m["win_rate"],
        "trade_count": m["trade_count"],
    }
    return result


# ── CLI entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    result = run_strategy(start="2018-01-01", end="2023-12-31")
    m = result["metrics"]
    pf4 = result["pf4_analysis"]

    print("\n" + "=" * 60)
    print("  H41b S&P Seasonal Calendar Effect")
    print("=" * 60)
    print(f"  Sharpe ratio     : {m['sharpe_ratio']:.4f}")
    print(f"  Max drawdown     : {m['max_drawdown']:.2%}")
    print(f"  Total return     : {m['total_return']:.2%}")
    print(f"  Win rate         : {m['win_rate']:.2%}")
    print(f"  Profit factor    : {m['profit_factor']:.2f}")
    print(f"  Total trades     : {m['trade_count']}")
    print(f"  Liq-constrained  : {m['liquidity_constrained_count']}")
    print()
    print(f"  PF-4 OpEx/PreHoliday overlap: {pf4['overlap_rate']:.1%} — {'PASS' if pf4['pf4_pass'] else 'WARN'}")
    if pf4["sample_conflicts"]:
        print(f"  Sample conflicts : {', '.join(pf4['sample_conflicts'][:5])}")
    print()
    print("  Signal breakdown:")
    for sig, stats in m.get("signal_breakdown", {}).items():
        print(f"    {sig:20s}: {stats['count']} trades, WR={stats['win_rate']:.1%}, PnL=${stats['total_pnl']:,.2f}")
    print()
    print("Data quality:")
    print(json.dumps(result["data_quality"], indent=2, default=str))
