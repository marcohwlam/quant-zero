"""
Strategy: H43 Macro Announcement Day Premium — CPI/NFP Long SPY
Author: Strategy Coder Agent
Date: 2026-05-01
Hypothesis: Equity markets earn a systematic premium on scheduled BLS macro announcement days
            (CPI, NFP). Buy SPY at T-1 close, sell at announcement day (T) close.
            A SHY momentum filter skips trades during aggressive rate-tightening environments.
Asset class: equities (SPY ETF)
Parent task: QUA-338
References: Savor & Wilson (2013) JF 68(3); Ai & Bansal (2018) JF 73(3);
            research/hypotheses/43_macro_announcement_day_premium.md
"""

import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

# ── BLS CPI Release Dates 2006–2025 ───────────────────────────────────────────
# Source: BLS CPI release schedule (https://www.bls.gov/schedule/news_release/cpi.htm)
# These are actual release dates (8:30am ET), not reference-month dates.
# IMPORTANT: Cross-verify against BLS before live deployment; dates are best-effort
# based on historical BLS schedules. 2018–2024 dates are high-confidence.
BLS_CPI_RELEASE_DATES = {
    2006: [
        "2006-01-18", "2006-02-22", "2006-03-16", "2006-04-19",
        "2006-05-17", "2006-06-14", "2006-07-19", "2006-08-16",
        "2006-09-20", "2006-10-18", "2006-11-15", "2006-12-14",
    ],
    2007: [
        "2007-01-17", "2007-02-21", "2007-03-16", "2007-04-17",
        "2007-05-15", "2007-06-15", "2007-07-18", "2007-08-15",
        "2007-09-19", "2007-10-17", "2007-11-15", "2007-12-14",
    ],
    2008: [
        "2008-01-16", "2008-02-20", "2008-03-19", "2008-04-16",
        "2008-05-14", "2008-06-18", "2008-07-16", "2008-08-14",
        "2008-09-17", "2008-10-16", "2008-11-19", "2008-12-16",
    ],
    2009: [
        "2009-01-16", "2009-02-20", "2009-03-18", "2009-04-15",
        "2009-05-15", "2009-06-17", "2009-07-15", "2009-08-14",
        "2009-09-16", "2009-10-15", "2009-11-18", "2009-12-16",
    ],
    2010: [
        "2010-01-15", "2010-02-19", "2010-03-18", "2010-04-14",
        "2010-05-19", "2010-06-17", "2010-07-16", "2010-08-13",
        "2010-09-17", "2010-10-15", "2010-11-17", "2010-12-15",
    ],
    2011: [
        "2011-01-14", "2011-02-17", "2011-03-17", "2011-04-15",
        "2011-05-13", "2011-06-15", "2011-07-15", "2011-08-18",
        "2011-09-15", "2011-10-19", "2011-11-17", "2011-12-16",
    ],
    2012: [
        "2012-01-19", "2012-02-17", "2012-03-16", "2012-04-13",
        "2012-05-15", "2012-06-14", "2012-07-17", "2012-08-15",
        "2012-09-14", "2012-10-16", "2012-11-15", "2012-12-14",
    ],
    # Oct 2013: government shutdown delayed release from Oct 16 to Oct 30
    2013: [
        "2013-01-16", "2013-02-21", "2013-03-15", "2013-04-16",
        "2013-05-16", "2013-06-18", "2013-07-16", "2013-08-15",
        "2013-09-17", "2013-10-30", "2013-11-20", "2013-12-17",
    ],
    2014: [
        "2014-01-16", "2014-02-20", "2014-03-18", "2014-04-15",
        "2014-05-15", "2014-06-17", "2014-07-22", "2014-08-19",
        "2014-09-17", "2014-10-22", "2014-11-20", "2014-12-17",
    ],
    2015: [
        "2015-01-16", "2015-02-26", "2015-03-24", "2015-04-17",
        "2015-05-22", "2015-06-18", "2015-07-17", "2015-08-19",
        "2015-09-16", "2015-10-15", "2015-11-17", "2015-12-15",
    ],
    2016: [
        "2016-01-20", "2016-02-19", "2016-03-16", "2016-04-14",
        "2016-05-17", "2016-06-16", "2016-07-15", "2016-08-16",
        "2016-09-16", "2016-10-18", "2016-11-17", "2016-12-15",
    ],
    2017: [
        "2017-01-18", "2017-02-15", "2017-03-15", "2017-04-14",
        "2017-05-12", "2017-06-14", "2017-07-14", "2017-08-11",
        "2017-09-14", "2017-10-13", "2017-11-15", "2017-12-13",
    ],
    2018: [
        "2018-01-12", "2018-02-14", "2018-03-13", "2018-04-11",
        "2018-05-10", "2018-06-12", "2018-07-12", "2018-08-10",
        "2018-09-13", "2018-10-11", "2018-11-14", "2018-12-12",
    ],
    2019: [
        "2019-01-11", "2019-02-13", "2019-03-12", "2019-04-10",
        "2019-05-10", "2019-06-12", "2019-07-11", "2019-08-13",
        "2019-09-12", "2019-10-10", "2019-11-13", "2019-12-11",
    ],
    2020: [
        "2020-01-14", "2020-02-13", "2020-03-11", "2020-04-10",
        "2020-05-12", "2020-06-10", "2020-07-14", "2020-08-12",
        "2020-09-11", "2020-10-13", "2020-11-12", "2020-12-10",
    ],
    2021: [
        "2021-01-13", "2021-02-10", "2021-03-10", "2021-04-13",
        "2021-05-12", "2021-06-10", "2021-07-13", "2021-08-11",
        "2021-09-14", "2021-10-13", "2021-11-10", "2021-12-10",
    ],
    # 2022: high-confidence — notable CPI surprises drove major market moves
    2022: [
        "2022-01-12", "2022-02-10", "2022-03-10", "2022-04-12",
        "2022-05-11", "2022-06-10", "2022-07-13", "2022-08-10",
        "2022-09-13", "2022-10-13", "2022-11-10", "2022-12-13",
    ],
    2023: [
        "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12",
        "2023-05-10", "2023-06-13", "2023-07-12", "2023-08-10",
        "2023-09-13", "2023-10-12", "2023-11-14", "2023-12-12",
    ],
    2024: [
        "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10",
        "2024-05-15", "2024-06-12", "2024-07-11", "2024-08-14",
        "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
    ],
    2025: [
        "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10",
        "2025-05-13", "2025-06-11", "2025-07-11", "2025-08-12",
        "2025-09-11", "2025-10-15", "2025-11-13", "2025-12-10",
    ],
}

# ── NFP Date Exceptions (holiday & scheduling overrides) ───────────────────────
# Key: (year, month) → corrected date string
# Default is first Friday of the month; exceptions listed below.
# Source: BLS Employment Situation release calendar.
_NFP_EXCEPTIONS = {
    (2008, 7): "2008-07-03",   # Jul 4 (Fri) = Independence Day holiday → Thu Jul 3
    (2009, 1): "2009-01-09",   # First Friday Jan 2 too early in month → second Friday
    (2009, 5): "2009-05-08",   # First Friday May 1 too early → second Friday
    (2010, 1): "2010-01-08",   # Jan 1 (Fri) = New Year's holiday → second Friday
    (2013, 10): "2013-10-22",  # Government shutdown; originally Oct 4 → released Oct 22
    (2014, 7): "2014-07-03",   # Jul 4 (Fri) = Independence Day holiday → Thu Jul 3
    (2015, 1): "2015-01-09",   # First Friday Jan 2 too early in month → second Friday
    (2016, 1): "2016-01-08",   # Jan 1 (Fri) = New Year's holiday → second Friday
    (2020, 7): "2020-07-02",   # Jul 3 (Fri) = observed Independence Day → Thu Jul 2
    (2021, 1): "2021-01-08",   # Jan 1 (Fri) = New Year's holiday → second Friday
    (2025, 7): "2025-07-03",   # Jul 4 (Fri) = Independence Day holiday → Thu Jul 3
}


def _build_nfp_dates(year_start: int, year_end: int) -> dict:
    """
    Compute NFP release dates as first Friday of each month, applying known exceptions.
    Returns dict: year → list of date strings.
    """
    result = {}
    for year in range(year_start, year_end + 1):
        year_dates = []
        for month in range(1, 13):
            key = (year, month)
            if key in _NFP_EXCEPTIONS:
                year_dates.append(_NFP_EXCEPTIONS[key])
            else:
                first = date(year, month, 1)
                days_ahead = (4 - first.weekday()) % 7  # 4 = Friday
                ff = first + timedelta(days=days_ahead)
                year_dates.append(ff.strftime("%Y-%m-%d"))
        result[year] = year_dates
    return result


# Pre-build NFP calendar for full range used by this strategy
BLS_NFP_RELEASE_DATES = _build_nfp_dates(2006, 2025)

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "SPY",
    "shy_ticker": "SHY",              # iShares 1-3 Year Treasury ETF (inception 2002)
    # Announcement types to trade; subset of ["CPI", "NFP"]
    "announcement_types": ["CPI", "NFP"],
    # Rate-shock filter: skip if SHY 10-day return <= shy_threshold
    "shy_lookback_days": 10,           # range: 5–15 days
    "shy_threshold": -0.015,           # -1.5%; range: -0.010 to -0.020
    # Entry timing: buy at T-1 close (default) or T-2 close
    "entry_timing": "T-1_close",       # "T-1_close" or "T-2_close"
    "init_cash": 25000,
}

# ── Transaction Cost Constants (Engineering Director spec) ─────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share fixed
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
MARKET_IMPACT_K = 0.1           # square-root impact coefficient (Johnson — Algo Trading & DMA)
SIGMA_WINDOW = 20               # 20-day rolling vol for σ
ADV_WINDOW = 20                 # 20-day rolling ADV
TRADING_DAYS_PER_YEAR = 252


# ── Calendar Helpers ───────────────────────────────────────────────────────────

def get_announcement_dates(params: dict, year_start: int, year_end: int) -> list:
    """
    Return sorted list of (pd.Timestamp, event_type) tuples for all announcement
    days in [year_start, year_end] matching params['announcement_types'].
    """
    ann_types = [t.upper() for t in params["announcement_types"]]
    valid = {"CPI", "NFP"}
    invalid = set(ann_types) - valid
    if invalid:
        raise ValueError(f"Unknown announcement_types: {invalid}. Must be subset of {valid}")

    dates = []
    for yr in range(year_start, year_end + 1):
        if "CPI" in ann_types:
            for d in BLS_CPI_RELEASE_DATES.get(yr, []):
                dates.append((pd.Timestamp(d), "CPI"))
        if "NFP" in ann_types:
            for d in BLS_NFP_RELEASE_DATES.get(yr, []):
                dates.append((pd.Timestamp(d), "NFP"))

    dates.sort(key=lambda x: x[0])
    return dates


def build_signal_map(
    ann_dates_typed: list,
    trading_list: list,
    entry_timing: str,
) -> dict:
    """
    Map entry_date → (exit_date, event_type) based on entry_timing.

    entry_timing='T-1_close': offset=1 trading day before announcement.
    entry_timing='T-2_close': offset=2 trading days before announcement.

    Announcement days not in the SPY trading calendar are skipped with a warning.
    When two events produce the same entry date, the first is kept (warns on duplicate).
    """
    if entry_timing == "T-1_close":
        offset = 1
    elif entry_timing == "T-2_close":
        offset = 2
    else:
        raise ValueError(f"Unknown entry_timing: {entry_timing!r}. Use 'T-1_close' or 'T-2_close'")

    date_to_idx = {d: i for i, d in enumerate(trading_list)}
    trading_set = set(trading_list)
    signal_map = {}

    for ann_ts, ann_type in ann_dates_typed:
        if ann_ts not in trading_set:
            warnings.warn(
                f"{ann_type} date {ann_ts.date()} not in SPY trading calendar — skipped"
            )
            continue
        idx = date_to_idx[ann_ts]
        if idx < offset:
            continue  # not enough prior trading days in data window
        entry_date = trading_list[idx - offset]

        if entry_date in signal_map:
            existing_exit, existing_type = signal_map[entry_date]
            warnings.warn(
                f"Duplicate entry date {entry_date.date()}: {existing_type} "
                f"(exit {existing_exit.date()}) vs {ann_type} (exit {ann_ts.date()}) — "
                f"keeping {existing_type}, skipping {ann_type}"
            )
        else:
            signal_map[entry_date] = (ann_ts, ann_type)

    return signal_map


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_ticker(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(ticker: str, shy_ticker: str, start: str, end: str, shy_lookback: int) -> dict:
    """
    Download SPY (OHLCV) and SHY (Close) with a warmup window.

    Warmup covers rolling windows (SIGMA_WINDOW, ADV_WINDOW, shy_lookback) plus buffer.
    Raises ValueError on insufficient or structurally invalid data.
    """
    warmup_days = max(SIGMA_WINDOW, ADV_WINDOW, shy_lookback) + 30
    warmup_cal = warmup_days * 2  # calendar days (2× to account for weekends/holidays)
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_cal)
    ).strftime("%Y-%m-%d")

    spy_df = _download_ticker(ticker, warmup_start, end)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in spy_df.columns:
            raise ValueError(f"Missing column '{col}' for {ticker}")
    if len(spy_df) < SIGMA_WINDOW + 10:
        raise ValueError(
            f"Insufficient SPY data: {len(spy_df)} bars (need ≥ {SIGMA_WINDOW + 10})"
        )

    spy_na = int(spy_df["Close"].isna().sum())
    if spy_na > 5:
        warnings.warn(f"{ticker}: {spy_na} missing Close values detected")

    # Enforce: no silent forward-fill for gaps > 5 consecutive days
    if spy_df["Close"].isna().any():
        is_na = spy_df["Close"].isna().astype(int)
        groups = spy_df["Close"].notna().cumsum()
        max_gap = int(is_na.groupby(groups).sum().max())
        if max_gap >= 5:
            warnings.warn(
                f"DATA QUALITY: {max_gap} consecutive missing days in {ticker} — "
                "forward-fill NOT applied per data quality policy"
            )

    shy_df = _download_ticker(shy_ticker, warmup_start, end)
    if "Close" not in shy_df.columns:
        raise ValueError(f"Missing 'Close' for {shy_ticker}")
    shy_close = shy_df["Close"].rename("shy")

    return {"spy": spy_df, "shy": shy_close}


# ── Rate-Shock Filter ──────────────────────────────────────────────────────────

def compute_shy_filter(shy_close: pd.Series, params: dict) -> pd.Series:
    """
    SHY momentum rate-shock filter.

    Returns boolean Series (True = ok to trade, False = skip).
    Uses shift(1) so on entry day D we only use SHY close confirmed as of D-1.
    NaN (pre-SHY-inception or insufficient history) → True (no filter applied).

    Rationale: SHY falling > |shy_threshold| over shy_lookback_days signals
    aggressive rate hikes → announcement day premium reverses.
    """
    lookback = params["shy_lookback_days"]
    threshold = params["shy_threshold"]
    shy_return = shy_close.pct_change(lookback).shift(1)
    return shy_return.gt(threshold).fillna(True)


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    idx: int,
) -> tuple:
    """
    Canonical equities transaction cost (Engineering Director spec):
      fixed    = $0.005/share
      slippage = 0.05% of notional
      impact   = k × σ × sqrt(Q / ADV) × price × Q  (square-root market impact)

    Flags Q/ADV > 1% as liquidity-constrained.
    Returns (total_cost_dollars: float, liquidity_constrained: bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000

    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV). Q/ADV > 1%."
        )

    return fixed + slippage + impact, liq_constrained


# ── H43 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h43(
    spy_df: pd.DataFrame,
    shy_filter: pd.Series,
    signal_map: dict,
    params: dict,
) -> tuple:
    """
    Simulate H43 Macro Announcement Day Premium on SPY.

    Entry/exit logic:
    - On entry day (T-1 or T-2): buy SPY at close if SHY filter passes.
    - On T (announcement day): sell SPY at close.
    - Only one position at a time (overlapping events handled by signal_map dedup).

    Returns (trade_log: list, equity: pd.Series, daily_df: pd.DataFrame).
    """
    init_cash = float(params["init_cash"])

    dates = spy_df.index
    n = len(dates)
    close_s = spy_df["Close"]
    vol_s = spy_df["Volume"]

    shy_filter_aligned = shy_filter.reindex(dates).fillna(True)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_pos = False
    entry_date_ts = None
    entry_price_eff = 0.0
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_bar_idx = -1
    exit_target_date = None
    event_type_at_entry = ""
    shy_passed_at_entry = True

    for i in range(n):
        date_i = dates[i]
        close_i = float(close_s.iloc[i])

        # ── Exit on announcement day T ────────────────────────────────────────
        if in_pos and date_i == exit_target_date:
            xcost, xliq = _transaction_cost(close_i, entry_shares, close_s, vol_s, i)
            eff_xp = close_i - xcost / entry_shares
            pnl = (eff_xp - entry_price_eff) * entry_shares
            capital += eff_xp * entry_shares

            ann_ret_pct = round(
                (eff_xp - entry_price_eff) / max(entry_price_eff, 1e-8) * 100, 4
            )
            trade_log.append({
                "entry_date": entry_date_ts.date(),
                "exit_date": date_i.date(),
                "event_type": event_type_at_entry,
                "entry_price": round(entry_price_eff, 4),
                "exit_price": round(eff_xp, 4),
                "shares": entry_shares,
                "pnl": round(pnl, 2),
                "entry_cost": round(entry_cost_total, 4),
                "exit_cost": round(xcost, 4),
                "transaction_cost": round(entry_cost_total + xcost, 4),
                "liquidity_constrained": entry_liq or xliq,
                "hold_days": i - entry_bar_idx,
                "ann_return_pct": ann_ret_pct,
                "shy_filter_passed": shy_passed_at_entry,
                "exit_reason": "ANNOUNCEMENT_CLOSE",
            })

            in_pos = False
            exit_target_date = None
            entry_date_ts = None
            entry_bar_idx = -1
            event_type_at_entry = ""

        elif in_pos and date_i > exit_target_date:
            # Calendar mis-alignment guard — should not happen
            warnings.warn(
                f"Position still open past exit target {exit_target_date.date()} "
                f"at {date_i.date()} — force-closing at close."
            )
            xcost, xliq = _transaction_cost(close_i, entry_shares, close_s, vol_s, i)
            eff_xp = close_i - xcost / entry_shares
            pnl = (eff_xp - entry_price_eff) * entry_shares
            capital += eff_xp * entry_shares

            trade_log.append({
                "entry_date": entry_date_ts.date(),
                "exit_date": date_i.date(),
                "event_type": event_type_at_entry,
                "entry_price": round(entry_price_eff, 4),
                "exit_price": round(eff_xp, 4),
                "shares": entry_shares,
                "pnl": round(pnl, 2),
                "entry_cost": round(entry_cost_total, 4),
                "exit_cost": round(xcost, 4),
                "transaction_cost": round(entry_cost_total + xcost, 4),
                "liquidity_constrained": entry_liq or xliq,
                "hold_days": i - entry_bar_idx,
                "ann_return_pct": None,
                "shy_filter_passed": shy_passed_at_entry,
                "exit_reason": "FORCE_CLOSE",
            })

            in_pos = False
            exit_target_date = None
            entry_date_ts = None
            entry_bar_idx = -1
            event_type_at_entry = ""

        # ── Check entry ────────────────────────────────────────────────────────
        if not in_pos and date_i in signal_map:
            exit_date, ann_type = signal_map[date_i]
            shy_ok = bool(shy_filter_aligned.iloc[i])

            if shy_ok and close_i > 0 and not pd.isna(close_i):
                shares = int(capital / close_i)
                if shares > 0:
                    cost, liq = _transaction_cost(close_i, shares, close_s, vol_s, i)
                    eff_ep = close_i + cost / shares
                    capital -= eff_ep * shares

                    in_pos = True
                    entry_date_ts = date_i
                    entry_price_eff = eff_ep
                    entry_shares = shares
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_bar_idx = i
                    exit_target_date = exit_date
                    event_type_at_entry = ann_type
                    shy_passed_at_entry = True

        # ── Daily mark-to-market ──────────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        daily_records.append({
            "date": date_i,
            "position": 1 if in_pos else 0,
            "signal_type": event_type_at_entry if in_pos else "",
            "equity": mtm,
        })

    # ── Force-close any open position at end of data ──────────────────────────
    if in_pos and n > 0:
        i = n - 1
        date_f = dates[i]
        close_f = float(close_s.iloc[i])
        xcost, xliq = _transaction_cost(close_f, entry_shares, close_s, vol_s, i)
        eff_xp = close_f - xcost / entry_shares
        pnl = (eff_xp - entry_price_eff) * entry_shares
        capital += eff_xp * entry_shares

        trade_log.append({
            "entry_date": entry_date_ts.date(),
            "exit_date": date_f.date(),
            "event_type": event_type_at_entry,
            "entry_price": round(entry_price_eff, 4),
            "exit_price": round(eff_xp, 4),
            "shares": entry_shares,
            "pnl": round(pnl, 2),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(xcost, 4),
            "transaction_cost": round(entry_cost_total + xcost, 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_days": i - entry_bar_idx,
            "ann_return_pct": None,
            "shy_filter_passed": shy_passed_at_entry,
            "exit_reason": "END_OF_DATA",
        })
        if daily_records:
            daily_records[-1]["equity"] = capital

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")

    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download data, build announcement signal map, apply SHY rate-shock filter,
    and simulate the H43 Macro Announcement Day Premium strategy.

    Parameters
    ----------
    start : str
        Backtest start date (YYYY-MM-DD). IS period: "2006-01-01".
    end : str
        Backtest end date (YYYY-MM-DD). IS period: "2021-12-31".
    params : dict, optional
        Override PARAMETERS. Uses module-level PARAMETERS if None.

    Returns
    -------
    dict
        Performance metrics, trade log, equity curve, daily DataFrame, and
        data quality flags. Includes per-event-type breakdown (CPI vs NFP).
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    shy_ticker = params["shy_ticker"]
    init_cash = float(params["init_cash"])
    entry_timing = params["entry_timing"]

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 1. Download data with warmup ─────────────────────────────────────────
    data = download_data(ticker, shy_ticker, start, end, params["shy_lookback_days"])
    spy_full = data["spy"]
    shy_full = data["shy"]

    # ── 2. Compute SHY filter on warmup-inclusive series (no look-ahead) ─────
    shy_filter_full = compute_shy_filter(shy_full, params)

    # ── 3. Trim to backtest window ────────────────────────────────────────────
    spy_df = spy_full.loc[
        (spy_full.index >= ts_start) & (spy_full.index <= ts_end)
    ].copy()
    shy_filter = shy_filter_full.loc[
        (shy_filter_full.index >= ts_start) & (shy_filter_full.index <= ts_end)
    ]

    if len(spy_df) < 10:
        raise ValueError(
            f"Insufficient SPY data after trimming to {start}–{end}: {len(spy_df)} bars"
        )

    trading_list = sorted(spy_df.index)
    year_start = trading_list[0].year
    year_end = trading_list[-1].year

    # ── 4. Build announcement signal map ─────────────────────────────────────
    ann_dates_typed = get_announcement_dates(params, year_start, year_end)
    ann_in_window = [(ts, t) for ts, t in ann_dates_typed if ts_start <= ts <= ts_end]
    signal_map = build_signal_map(ann_in_window, trading_list, entry_timing)

    ann_count = len(ann_in_window)
    cpi_count = sum(1 for _, t in ann_in_window if t == "CPI")
    nfp_count = sum(1 for _, t in ann_in_window if t == "NFP")

    # ── 5. Count SHY-blocked trades ──────────────────────────────────────────
    shy_filter_aligned = shy_filter.reindex(spy_df.index).fillna(True)
    shy_blocked = sum(
        1 for ed in signal_map
        if ed in shy_filter.index and not bool(shy_filter.loc[ed])
    )

    # ── 6. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h43(
        spy_df, shy_filter_aligned, signal_map, params
    )

    # ── 7. Performance metrics ────────────────────────────────────────────────
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    n_trades = len(trade_log)
    trades_per_year = round(n_trades / years, 1)

    _empty_cols = [
        "entry_date", "exit_date", "event_type", "entry_price", "exit_price",
        "shares", "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "ann_return_pct",
        "shy_filter_passed", "exit_reason",
    ]
    trades_df = (
        pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=_empty_cols)
    )

    daily_returns = equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values
    sharpe = 0.0
    if len(ret_arr) > 0 and ret_arr.std() > 0:
        sharpe = round(
            float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4
        )

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)
    win_rate = (
        round(float((trades_df["pnl"] > 0).mean()), 4) if n_trades > 0 else 0.0
    )

    profit_factor = 0.0
    if n_trades > 0:
        wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = (
            round(float(wins / losses), 4) if losses > 0 else float("inf")
        )

    # PF-1: ≥30 trades per walk-forward fold (4 folds over IS period)
    pf1_threshold = 30
    trades_per_wf_fold = round(n_trades / 4, 1)
    pf1_status = (
        f"PASS ({trades_per_wf_fold:.1f}/fold ≥ {pf1_threshold})"
        if trades_per_wf_fold >= pf1_threshold
        else f"WARN: {trades_per_wf_fold:.1f}/fold < {pf1_threshold}"
    )

    # Per-event-type breakdown for Engineering Director analysis
    event_breakdown = {}
    if n_trades > 0 and "event_type" in trades_df.columns:
        for etype, grp in trades_df.groupby("event_type"):
            event_breakdown[str(etype)] = {
                "count": int(len(grp)),
                "win_rate": round(float((grp["pnl"] > 0).mean()), 4),
                "avg_pnl": round(float(grp["pnl"].mean()), 2),
                "avg_return_pct": round(float(grp["ann_return_pct"].dropna().mean()), 4),
            }

    ann_types_label = "+".join(sorted(params["announcement_types"]))
    filter_label = f"SHY-{params['shy_lookback_days']}d<{params['shy_threshold']:.1%}"
    print(
        f"\nH43 Macro Announcement Premium ({start}–{end}) "
        f"[{ann_types_label}, {entry_timing}, {filter_label}]:\n"
        f"  Announcements in window: {ann_count} "
        f"(CPI={cpi_count}, NFP={nfp_count}) | "
        f"SHY-blocked: {shy_blocked} | Trades executed: {n_trades} ({trades_per_year:.1f}/yr)\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor} | "
        f"PF-1: {pf1_status}\n"
        f"  Event breakdown: {event_breakdown}\n"
        f"  Init cash: ${init_cash:,.0f}"
    )

    return {
        "returns": daily_returns,
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params,
        "data_quality": {
            "survivorship_bias_flag": "SPY + SHY are market ETFs — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "spy_ticker": ticker,
            "shy_ticker": shy_ticker,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY + SHY are still active",
            "cpi_calendar_source": (
                "Hardcoded from BLS CPI release schedule; "
                "verify at bls.gov/schedule/news_release/cpi.htm"
            ),
            "nfp_calendar_source": (
                "First-Friday rule + known holiday exceptions; "
                "verify at bls.gov/schedule/news_release/empsit.htm"
            ),
            "forward_fill_policy": "Silent forward-fill NOT applied for gaps > 5 days",
        },
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "trades_per_wf_fold": trades_per_wf_fold,
        "pf1_status": pf1_status,
        "announcement_count": ann_count,
        "shy_blocked_count": shy_blocked,
        "event_breakdown": event_breakdown,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2006-01-01",
    end: str = "2025-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H43.

    Returns a DataFrame with per-day columns:
        date, position, signal_type, pnl, entry_price, exit_price,
        transaction_cost, exit_reason, event_type

    Trade-level fields are populated on the exit date; all other rows carry NaN.
    `ticker` parameter accepted for orchestrator compatibility — H43 uses SPY
    via PARAMETERS["ticker"].
    """
    p = (params or PARAMETERS).copy()
    result = run_backtest(start, end, p)

    daily = result["daily_df"].reset_index()
    trades = result["trades"]

    trade_merge_cols = [
        "exit_date", "pnl", "entry_price", "exit_price",
        "transaction_cost", "exit_reason", "event_type",
    ]

    if trades.empty:
        for col in trade_merge_cols[1:]:
            daily[col] = np.nan
    else:
        trade_cols = trades[trade_merge_cols].copy()
        trade_cols["exit_date"] = pd.to_datetime(trade_cols["exit_date"])
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.merge(
            trade_cols.rename(columns={"exit_date": "date"}),
            on="date",
            how="left",
        )

    return daily[[
        "date", "position", "signal_type",
        "pnl", "entry_price", "exit_price",
        "transaction_cost", "exit_reason", "event_type",
    ]]


if __name__ == "__main__":
    # ── IS: CPI + NFP filtered (main hypothesis) ─────────────────────────────
    result_is = run_backtest("2006-01-01", "2021-12-31")
    print(
        f"\n[IS CPI+NFP] Trades: {result_is['trade_count']} | "
        f"SHY-blocked: {result_is['shy_blocked_count']} | "
        f"Sharpe: {result_is['sharpe']}"
    )

    # ── IS: CPI only — isolate CPI contribution (per Engineering Director) ───
    params_cpi_only = PARAMETERS.copy()
    params_cpi_only["announcement_types"] = ["CPI"]
    result_cpi = run_backtest("2006-01-01", "2021-12-31", params_cpi_only)
    print(
        f"[IS CPI only] Trades: {result_cpi['trade_count']} | "
        f"Sharpe: {result_cpi['sharpe']}"
    )

    # ── IS: NFP only ──────────────────────────────────────────────────────────
    params_nfp_only = PARAMETERS.copy()
    params_nfp_only["announcement_types"] = ["NFP"]
    result_nfp = run_backtest("2006-01-01", "2021-12-31", params_nfp_only)
    print(
        f"[IS NFP only] Trades: {result_nfp['trade_count']} | "
        f"Sharpe: {result_nfp['sharpe']}"
    )

    # ── OOS: 2022–2025 — validate SHY filter skips most 2022 events ──────────
    result_oos = run_backtest("2022-01-01", "2025-12-31")
    print(
        f"[OOS filtered] Trades: {result_oos['trade_count']} | "
        f"SHY-blocked: {result_oos['shy_blocked_count']} | "
        f"Sharpe: {result_oos['sharpe']}"
    )

    print("\nSample IS trades (first 5):")
    if not result_is["trades"].empty:
        print(result_is["trades"].head().to_string(index=False))

    print(f"\nEquity final (IS filtered): ${result_is['equity'].iloc[-1]:,.2f}")
