"""
Strategy: H47 FOMC Bi-Weekly Cycle
Author: Strategy Coder Agent
Date: 2026-06-11
Hypothesis: US equity premium is concentrated in even weeks (0, 2, 4) of the 6-week FOMC
            inter-meeting cycle (Cieslak, Morse & Vissing-Jorgensen 2019, JF 74(5)).
            Hold SPY during even weeks; hold cash (or TLT) during odd weeks.
            200-DMA overlay reduces even-week allocation to 50% during downtrends.
Asset class: equities (SPY ETF)
Parent task: QUA-202
References: Cieslak, Morse & Vissing-Jorgensen (2019) JF 74(5);
            research/hypotheses/47_qc_fomc_biweekly_cycle.md

Data quality checklist:
  - auto_adjust=True: YES — yf.download(..., auto_adjust=True)
  - Survivorship bias: NONE — SPY/TLT are market ETFs, always active, no delisting risk
  - Earnings exclusion: N/A — ETF-only strategy; no individual stock earnings events
  - Emergency meetings: INCLUDED — Oct 8 2008 and Mar 3 2020 treated as week 0 (cycle reset)
  - FOMC calendar source: Hardcoded from Federal Reserve public schedule (federalreserve.gov).
    Cross-check at federalreserve.gov/monetarypolicy/fomccalendars.htm before live deployment.
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── FOMC Meeting Dates 2003–2026 ───────────────────────────────────────────────
# Includes emergency meetings (Oct 8 2008, Mar 3 2020) which reset the cycle counter.
# Source: Federal Reserve FOMC meeting calendars (federalreserve.gov)
FOMC_DATES = {
    2003: ["2003-01-29", "2003-03-18", "2003-05-06", "2003-06-25",
           "2003-08-12", "2003-09-16", "2003-10-28", "2003-12-09"],
    2004: ["2004-01-28", "2004-03-16", "2004-05-04", "2004-06-30",
           "2004-08-10", "2004-09-21", "2004-11-10", "2004-12-14"],
    2005: ["2005-02-02", "2005-03-22", "2005-05-03", "2005-06-30",
           "2005-08-09", "2005-09-20", "2005-11-01", "2005-12-13"],
    2006: ["2006-01-31", "2006-03-28", "2006-05-10", "2006-06-29",
           "2006-08-08", "2006-09-20", "2006-10-25", "2006-12-12"],
    2007: ["2007-01-31", "2007-03-21", "2007-05-09", "2007-06-28",
           "2007-08-07", "2007-09-18", "2007-10-31", "2007-12-11"],
    2008: ["2008-01-30", "2008-03-18", "2008-04-30", "2008-06-25",
           "2008-08-05", "2008-09-16", "2008-10-08",  # emergency cut — resets cycle
           "2008-10-29", "2008-12-16"],
    2009: ["2009-01-28", "2009-03-18", "2009-04-29", "2009-06-24",
           "2009-08-12", "2009-09-23", "2009-11-04", "2009-12-16"],
    2010: ["2010-01-27", "2010-03-16", "2010-04-28", "2010-06-23",
           "2010-08-10", "2010-09-21", "2010-11-03", "2010-12-14"],
    2011: ["2011-01-26", "2011-03-15", "2011-04-27", "2011-06-22",
           "2011-08-09", "2011-09-21", "2011-11-02", "2011-12-13"],
    2012: ["2012-01-25", "2012-03-13", "2012-04-25", "2012-06-20",
           "2012-08-01", "2012-09-13", "2012-10-24", "2012-12-12"],
    2013: ["2013-01-30", "2013-03-20", "2013-05-01", "2013-06-19",
           "2013-07-31", "2013-09-18", "2013-10-30", "2013-12-18"],
    2014: ["2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18",
           "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17"],
    2015: ["2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
           "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16"],
    2016: ["2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
           "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14"],
    2017: ["2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
           "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13"],
    2018: ["2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
           "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19"],
    2019: ["2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
           "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11"],
    2020: ["2020-01-29", "2020-03-03",  # emergency COVID cut — resets cycle
           "2020-04-29", "2020-06-10", "2020-07-29",
           "2020-09-16", "2020-11-05", "2020-12-16"],
    2021: ["2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
           "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15"],
    2022: ["2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
           "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14"],
    2023: ["2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
           "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13"],
    2024: ["2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
           "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18"],
    2025: ["2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
           "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10"],
    2026: ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
           "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"],
}

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "SPY",
    "defensive_ticker": None,       # None = cash; "TLT" for bond alternative in odd weeks
    "even_weeks_included": [0, 2, 4],   # full Cieslak spec; sweep: [0,2], [0]
    "ma_period": 200,               # 200-DMA baseline; sweep: 150, 200, 250
    "downtrend_position_size": 0.50,    # SPY fraction during downtrend even weeks
    "init_cash": 100000,
    "start_date": "2003-01-01",
    "end_date": "2023-12-31",       # IS window
    "oos_start_date": "2024-01-01",
    "oos_end_date": "2026-12-31",
}

# ── Transaction Cost Constants (ED-SLIP-001 ultra-liquid tier — SPY) ──────────
# SPY ADV > 50M shares/day → ultra-liquid slippage applies (0.005%, not 0.05%)
FIXED_COST_PER_SHARE = 0.005    # $0.005/share
SLIPPAGE_PCT = 0.00005          # 0.005% per ED-SLIP-001 (ultra-liquid tier)
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root impact coefficient
SIGMA_WINDOW = 20               # rolling vol window for market impact σ
ADV_WINDOW = 20                 # rolling ADV window for Q/ADV ratio
TRADING_DAYS_PER_YEAR = 252


# ── FOMC Calendar Helpers ──────────────────────────────────────────────────────

def get_fomc_dates_sorted(fomc_dict: dict, start_year: int, end_year: int) -> list:
    """Return sorted list of pd.Timestamps for all FOMC dates in [start_year, end_year]."""
    dates = []
    for y in range(start_year, end_year + 1):
        dates.extend(pd.to_datetime(fomc_dict.get(y, [])))
    return sorted(dates)


def compute_cycle_weeks(dates: pd.DatetimeIndex, fomc_dates_sorted: list) -> pd.Series:
    """
    Vectorized computation of FOMC cycle week for every trading day.

    Week 0 = FOMC meeting week (0–4 trading days after the meeting).
    Cycle resets on each FOMC date (including emergency meetings).
    Returns Int64 Series with NA for dates before the first FOMC in the calendar.
    """
    if not fomc_dates_sorted:
        return pd.Series(pd.NA, index=dates, dtype="Int64")

    dates_list = list(dates)
    date_to_pos = {d: i for i, d in enumerate(dates_list)}
    dates_ts = np.array([d.value for d in dates_list], dtype=np.int64)

    # Map each FOMC date to its trading day index (first trading day on or after FOMC date)
    fomc_tdi = []
    for fd in fomc_dates_sorted:
        if fd in date_to_pos:
            fomc_tdi.append(date_to_pos[fd])
        else:
            # FOMC on non-trading day: use next available trading day
            idx = int(np.searchsorted(dates_ts, fd.value, side="left"))
            if idx < len(dates_list):
                warnings.warn(
                    f"FOMC date {fd.date()} not in trading calendar — "
                    f"using {dates_list[idx].date()} as cycle anchor"
                )
                fomc_tdi.append(idx)

    if not fomc_tdi:
        return pd.Series(pd.NA, index=dates, dtype="Int64")

    fomc_tdi_arr = np.array(fomc_tdi, dtype=np.int64)
    all_idx = np.arange(len(dates_list), dtype=np.int64)

    # For each trading day index i, find j = last FOMC trading-day index <= i
    j = np.searchsorted(fomc_tdi_arr, all_idx, side="right") - 1

    valid = j >= 0
    raw = np.full(len(dates_list), -1, dtype=np.int64)
    raw[valid] = (all_idx[valid] - fomc_tdi_arr[j[valid]]) // 5

    out = pd.array(np.where(raw >= 0, raw, pd.NA), dtype="Int64")
    return pd.Series(out, index=dates)


def is_week_start_flags(dates: pd.DatetimeIndex) -> pd.Series:
    """
    True on the first trading day of each ISO calendar week.
    Handles holiday-adjusted Tuesdays (Monday holiday → Tuesday is week start).
    """
    # Year * 100 + ISO week number gives a unique key per calendar week
    week_ids = pd.Series(
        [d.year * 100 + d.isocalendar()[1] for d in dates],
        index=dates,
        dtype="int64",
    )
    is_start = week_ids != week_ids.shift(1)
    is_start.iloc[0] = True
    return is_start


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost_dollars(
    price: float,
    abs_shares: int,
    sigma_val: float,
    adv_val: float,
) -> tuple:
    """
    Compute transaction cost in dollars for SPY order (ED-SLIP-001 ultra-liquid tier).

    Components:
      fixed    = $0.005/share
      slippage = 0.005% of notional  (ultra-liquid tier; SPY ADV > 50M)
      impact   = k × σ × sqrt(Q / ADV) × price × Q  (Almgren-Chriss square-root model)

    Flags orders where Q/ADV > 1% as liquidity-constrained.
    Returns (total_cost_dollars, liquidity_constrained).
    """
    fixed = FIXED_COST_PER_SHARE * abs_shares
    slippage = SLIPPAGE_PCT * price * abs_shares

    sigma = sigma_val if (not np.isnan(sigma_val) and sigma_val > 0) else 0.01
    adv = adv_val if (not np.isnan(adv_val) and adv_val > 0) else 50_000_000  # SPY fallback

    impact = MARKET_IMPACT_K * sigma * np.sqrt(abs_shares / adv) * price * abs_shares
    liq_constrained = bool(abs_shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order: {abs_shares} shares "
            f"({abs_shares / adv:.2%} of ADV). Q/ADV > 1% — market impact elevated."
        )

    return fixed + slippage + impact, liq_constrained


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def _download_data(
    ticker: str,
    def_ticker,
    start: str,
    end: str,
    ma_period: int = 200,
) -> dict:
    """
    Download SPY (and optionally defensive ticker) with warmup for rolling indicators.

    Warmup = ma_period + sigma/adv window + 50-day buffer to ensure fully populated
    rolling stats at the start of the backtest window.

    Returns dict: {"spy": DataFrame, "def": DataFrame or None}
    """
    warmup_cal_days = int((ma_period + max(SIGMA_WINDOW, ADV_WINDOW) + 50) * 1.5)
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_cal_days)).strftime("%Y-%m-%d")

    spy_df = _download_single(ticker, warmup_start, end)
    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(spy_df.columns)
    if missing:
        raise ValueError(f"Missing columns for {ticker}: {missing}")
    if len(spy_df) < ma_period + 10:
        raise ValueError(
            f"Insufficient data for {ticker}: {len(spy_df)} bars (need {ma_period + 10})"
        )
    na_count = int(spy_df["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing trading days detected")

    def_df = None
    if def_ticker:
        def_df = _download_single(def_ticker, warmup_start, end)
        if "Close" not in def_df.columns or "Open" not in def_df.columns:
            raise ValueError(f"Missing Open/Close for defensive ticker {def_ticker}")

    return {"spy": spy_df, "def": def_df}


# ── H47 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h47(
    spy_df: pd.DataFrame,
    def_df,
    fomc_dates_sorted: list,
    params: dict,
) -> tuple:
    """
    Simulate H47 FOMC Bi-Weekly Cycle strategy.

    Rebalances at Monday open (or first trading day of week if Monday is a holiday).
    Holds SPY during even weeks {0,2,4}; holds cash (or defensive ticker) during odd weeks.
    200-DMA overlay reduces even-week SPY allocation to downtrend_position_size when
    prior close is below the 200-DMA.

    Position sizing uses open price on rebalance day; no look-ahead into intraday data.

    Returns:
        trade_log (list of dicts), daily_df (DataFrame indexed by date),
        signal_log (DataFrame with date column).
    """
    even_weeks = set(params["even_weeks_included"])
    downtrend_size = float(params["downtrend_position_size"])
    ma_period = int(params["ma_period"])
    init_cash = float(params["init_cash"])
    def_ticker = params["defensive_ticker"]

    close_s = spy_df["Close"]
    open_s = spy_df["Open"]
    vol_s = spy_df["Volume"]
    dates = spy_df.index
    n = len(dates)

    # Pre-compute 200-DMA trend signal (shift(1): no look-ahead — uses prior close)
    ma200 = close_s.rolling(ma_period, min_periods=ma_period).mean()
    trend_series = (close_s >= ma200).shift(1)  # True = above DMA as of prior close

    # Pre-compute rolling vol and ADV for transaction costs
    rolling_sigma = close_s.pct_change().rolling(SIGMA_WINDOW).std()
    rolling_adv = vol_s.rolling(ADV_WINDOW).mean()

    # Pre-compute cycle weeks — use precomputed column if available (set by run_strategy
    # using warmup-inclusive calendar to correctly anchor cycles at window start)
    if "_cycle_week" in spy_df.columns:
        cycle_week_series = spy_df["_cycle_week"]
    else:
        cycle_week_series = compute_cycle_weeks(dates, fomc_dates_sorted)
    week_start_flags = is_week_start_flags(dates)

    # Defensive ticker price series (if used for odd-week allocation)
    def_open_s = def_df["Open"] if def_df is not None else None
    def_close_s = def_df["Close"] if def_df is not None else None

    trade_log = []
    daily_records = []
    signal_log_records = []

    capital = init_cash
    spy_shares = 0
    def_shares = 0
    current_spy_size = 0.0      # fraction of portfolio in SPY (0, 0.5, or 1.0)
    current_def_size = 0.0      # fraction in defensive ticker

    for i in range(n):
        date = dates[i]
        close_i = float(close_s.iloc[i])
        open_i = float(open_s.iloc[i])

        cw_raw = cycle_week_series.iloc[i]
        cw = None if pd.isna(cw_raw) else int(cw_raw)
        is_even = cw is not None and cw in even_weeks
        trend_raw = trend_series.iloc[i]
        trend = bool(trend_raw) if not pd.isna(trend_raw) else True  # default bullish pre-MA warmup

        sigma_i = float(rolling_sigma.iloc[i]) if not pd.isna(rolling_sigma.iloc[i]) else np.nan
        adv_i = float(rolling_adv.iloc[i]) if not pd.isna(rolling_adv.iloc[i]) else np.nan

        # ── Weekly rebalance at open ──────────────────────────────────────────
        if week_start_flags.iloc[i]:
            # Determine target SPY fraction for this week
            if is_even:
                target_spy = 1.0 if trend else downtrend_size
            else:
                target_spy = 0.0

            # Defensive allocation fills the non-SPY portion when defensive_ticker is set
            target_def = (1.0 - target_spy) if (def_ticker and not is_even) else 0.0

            # Current equity mark at open (use open price for SPY, prior close for def as proxy)
            def_open_i = float(def_open_s.iloc[i]) if def_open_s is not None else 0.0
            spy_mtm_open = spy_shares * open_i
            def_mtm_open = def_shares * def_open_i if def_ticker else 0.0
            total_equity = capital + spy_mtm_open + def_mtm_open

            spy_target_shares = int(total_equity * target_spy / open_i) if open_i > 0 else 0
            def_target_shares = (
                int(total_equity * target_def / def_open_i)
                if (def_ticker and def_open_i > 0 and target_def > 0)
                else 0
            )

            # Execute SPY leg
            spy_delta = spy_target_shares - spy_shares
            if spy_delta != 0:
                cost, liq = _transaction_cost_dollars(open_i, abs(spy_delta), sigma_i, adv_i)
                if spy_delta > 0:
                    eff_price = open_i + cost / spy_delta
                    capital -= eff_price * spy_delta
                    spy_shares += spy_delta
                    trade_type = "BUY_SPY"
                else:
                    eff_price = open_i - cost / abs(spy_delta)
                    capital += eff_price * abs(spy_delta)
                    spy_shares += spy_delta
                    trade_type = "SELL_SPY"
                trade_log.append({
                    "date": date.date(),
                    "trade_type": trade_type,
                    "shares_delta": spy_delta,
                    "shares_held": spy_shares,
                    "ticker": params["ticker"],
                    "open_price": round(open_i, 4),
                    "effective_price": round(eff_price, 4),
                    "transaction_cost": round(cost, 4),
                    "cycle_week": cw,
                    "is_even": is_even,
                    "trend_ok": trend,
                    "target_position_size": target_spy,
                    "liquidity_constrained": liq,
                })
                current_spy_size = target_spy

            # Execute defensive ticker leg
            if def_ticker and def_open_s is not None:
                def_delta = def_target_shares - def_shares
                if def_delta != 0:
                    # Use defensive ticker's own sigma/adv for its cost (TLT is also liquid)
                    def_sigma = (
                        float(def_close_s.pct_change().rolling(SIGMA_WINDOW).std().iloc[i])
                        if def_close_s is not None else np.nan
                    )
                    def_adv = (
                        float(def_df["Volume"].rolling(ADV_WINDOW).mean().iloc[i])
                        if def_df is not None and "Volume" in def_df.columns else np.nan
                    )
                    def_cost, def_liq = _transaction_cost_dollars(
                        def_open_i, abs(def_delta), def_sigma, def_adv
                    )
                    if def_delta > 0:
                        eff_def_price = def_open_i + def_cost / def_delta
                        capital -= eff_def_price * def_delta
                        def_shares += def_delta
                        def_trade_type = "BUY_DEF"
                    else:
                        eff_def_price = def_open_i - def_cost / abs(def_delta)
                        capital += eff_def_price * abs(def_delta)
                        def_shares += def_delta
                        def_trade_type = "SELL_DEF"
                    trade_log.append({
                        "date": date.date(),
                        "trade_type": def_trade_type,
                        "shares_delta": def_delta,
                        "shares_held": def_shares,
                        "ticker": def_ticker,
                        "open_price": round(def_open_i, 4),
                        "effective_price": round(eff_def_price, 4),
                        "transaction_cost": round(def_cost, 4),
                        "cycle_week": cw,
                        "is_even": is_even,
                        "trend_ok": trend,
                        "target_position_size": target_def,
                        "liquidity_constrained": def_liq,
                    })
                current_def_size = target_def

        # ── Daily mark-to-market ──────────────────────────────────────────────
        def_close_i = float(def_close_s.iloc[i]) if def_close_s is not None else 0.0
        equity = capital + spy_shares * close_i + def_shares * def_close_i
        daily_records.append({
            "date": date,
            "equity": equity,
            "spy_position_size": current_spy_size,
            "spy_shares": spy_shares,
            "def_shares": def_shares,
            "cash": capital,
        })

        signal_log_records.append({
            "date": date,
            "cycle_week": cw,
            "is_even": is_even,
            "trend_ok": trend,
            "position_size": current_spy_size,
        })

    # ── Force-close any open positions at end of data ─────────────────────────
    if spy_shares > 0 or def_shares > 0:
        last_i = n - 1
        close_f = float(close_s.iloc[last_i])
        sigma_f = float(rolling_sigma.iloc[last_i]) if not pd.isna(rolling_sigma.iloc[last_i]) else np.nan
        adv_f = float(rolling_adv.iloc[last_i]) if not pd.isna(rolling_adv.iloc[last_i]) else np.nan

        if spy_shares > 0:
            cost, liq = _transaction_cost_dollars(close_f, spy_shares, sigma_f, adv_f)
            eff_price = close_f - cost / spy_shares
            capital += eff_price * spy_shares
            trade_log.append({
                "date": dates[last_i].date(),
                "trade_type": "SELL_SPY_EOD",
                "shares_delta": -spy_shares,
                "shares_held": 0,
                "ticker": params["ticker"],
                "open_price": round(close_f, 4),
                "effective_price": round(eff_price, 4),
                "transaction_cost": round(cost, 4),
                "cycle_week": signal_log_records[-1]["cycle_week"],
                "is_even": signal_log_records[-1]["is_even"],
                "trend_ok": signal_log_records[-1]["trend_ok"],
                "target_position_size": 0.0,
                "liquidity_constrained": liq,
            })
            spy_shares = 0

        if def_shares > 0 and def_close_s is not None:
            def_close_f = float(def_close_s.iloc[last_i])
            def_cost, def_liq = _transaction_cost_dollars(def_close_f, def_shares, np.nan, np.nan)
            eff_def_price = def_close_f - def_cost / def_shares
            capital += eff_def_price * def_shares
            trade_log.append({
                "date": dates[last_i].date(),
                "trade_type": "SELL_DEF_EOD",
                "shares_delta": -def_shares,
                "shares_held": 0,
                "ticker": def_ticker,
                "open_price": round(def_close_f, 4),
                "effective_price": round(eff_def_price, 4),
                "transaction_cost": round(def_cost, 4),
                "cycle_week": signal_log_records[-1]["cycle_week"],
                "is_even": signal_log_records[-1]["is_even"],
                "trend_ok": signal_log_records[-1]["trend_ok"],
                "target_position_size": 0.0,
                "liquidity_constrained": def_liq,
            })
            def_shares = 0

        if daily_records:
            daily_records[-1]["equity"] = capital

    daily_df = pd.DataFrame(daily_records).set_index("date")
    signal_log_df = pd.DataFrame(signal_log_records)  # date as column per task spec

    return trade_log, daily_df, signal_log_df


# ── Main Entry Point ───────────────────────────────────────────────────────────

def run_strategy(params: dict = None) -> dict:
    """
    Download data and run the H47 FOMC Bi-Weekly Cycle strategy.

    Parameters
    ----------
    params : dict, optional
        Override PARAMETERS. Keys: ticker, defensive_ticker, even_weeks_included,
        ma_period, downtrend_position_size, init_cash, start_date, end_date.

    Returns
    -------
    dict with keys:
        equity_curve  : pd.Series indexed by date
        trades        : list of dicts (one entry per rebalance leg)
        daily_returns : pd.Series of daily returns
        signal_log    : pd.DataFrame columns [date, cycle_week, is_even, trend_ok, position_size]
        sharpe, max_drawdown, total_return, win_rate, profit_factor, trade_count,
        trades_per_year, fomc_meetings_in_window, data_quality (dict)
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    def_ticker = params.get("defensive_ticker")
    start = params["start_date"]
    end = params["end_date"]
    ma_period = int(params["ma_period"])
    init_cash = float(params["init_cash"])

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 1. Download data (warmup-inclusive) ───────────────────────────────────
    data = _download_data(ticker, def_ticker, start, end, ma_period)
    spy_full = data["spy"]
    def_full = data["def"]

    # ── 2. Trim to backtest window ────────────────────────────────────────────
    spy_df = spy_full.loc[(spy_full.index >= ts_start) & (spy_full.index <= ts_end)].copy()
    def_df = (
        def_full.loc[(def_full.index >= ts_start) & (def_full.index <= ts_end)].copy()
        if def_full is not None else None
    )

    if len(spy_df) < 10:
        raise ValueError(f"Insufficient SPY data in {start}–{end}: {len(spy_df)} bars")

    # ── 3. Pre-compute rolling indicators on warmup-inclusive series, then trim ─
    # (Rolling calculations run on full data to populate stats at window start)
    close_full = spy_full["Close"]
    ma200_full = close_full.rolling(ma_period, min_periods=ma_period).mean()
    trend_full = (close_full >= ma200_full).shift(1)

    # Trim to backtest window — results are now fully populated from warmup
    spy_df["_ma200"] = ma200_full.reindex(spy_df.index)
    spy_df["_trend_ok"] = trend_full.reindex(spy_df.index)
    spy_df["_sigma"] = close_full.pct_change().rolling(SIGMA_WINDOW).std().reindex(spy_df.index)
    spy_df["_adv"] = spy_full["Volume"].rolling(ADV_WINDOW).mean().reindex(spy_df.index)

    # ── 4. Data quality checks ────────────────────────────────────────────────
    max_gap = 0
    if spy_df["Close"].isna().any():
        is_na = spy_df["Close"].isna().astype(int)
        max_gap = int(is_na.groupby((~spy_df["Close"].isna()).cumsum()).sum().max())
    if max_gap >= 5:
        warnings.warn(f"Data gap: {max_gap} consecutive missing days in {ticker}")

    trend_na_count = int(spy_df["_trend_ok"].isna().sum())
    if trend_na_count > ma_period + 5:
        warnings.warn(
            f"{trend_na_count} NaN values in trend signal — warmup may be insufficient"
        )

    # ── 5. Build FOMC calendar for backtest window ────────────────────────────
    year_start = spy_df.index[0].year
    year_end = spy_df.index[-1].year
    fomc_dates_sorted = get_fomc_dates_sorted(FOMC_DATES, max(2003, year_start - 1), year_end)
    fomc_in_window = [d for d in fomc_dates_sorted if ts_start <= d <= ts_end]

    # Compute cycle weeks on the FULL (warmup-inclusive) calendar so that
    # pre-window FOMC dates anchor the cycle correctly at the backtest start.
    # Without this, FOMC dates before the trimmed window map to index 0 and
    # produce a wrong cycle position in the first few weeks.
    cycle_weeks_full = compute_cycle_weeks(spy_full.index, fomc_dates_sorted)
    spy_df["_cycle_week"] = cycle_weeks_full.reindex(spy_df.index)

    # ── 6. Simulate ───────────────────────────────────────────────────────────
    trade_log, daily_df, signal_log = simulate_h47(spy_df, def_df, fomc_dates_sorted, params)

    equity_curve = daily_df["equity"].rename("equity")

    # ── 7. Performance metrics ────────────────────────────────────────────────
    daily_returns = equity_curve.pct_change().fillna(0.0)
    ret_arr = daily_returns.values

    sharpe = 0.0
    if len(ret_arr) > 0 and ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1.0 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    spy_trades = [t for t in trade_log if t.get("ticker") == ticker]
    # Pair buys with sells to compute trade-level PnL for win rate
    pnl_list = []
    buy_stack = []
    for t in spy_trades:
        if t["trade_type"] in ("BUY_SPY",):
            buy_stack.append(t)
        elif t["trade_type"] in ("SELL_SPY", "SELL_SPY_EOD") and buy_stack:
            entry = buy_stack.pop()
            pnl = (t["effective_price"] - entry["effective_price"]) * abs(t["shares_delta"])
            pnl_list.append(pnl)

    n_paired_trades = len(pnl_list)
    win_rate = round(float(sum(1 for p in pnl_list if p > 0) / n_paired_trades), 4) if n_paired_trades > 0 else 0.0
    wins = sum(p for p in pnl_list if p > 0)
    losses = sum(abs(p) for p in pnl_list if p < 0)
    profit_factor = round(float(wins / losses) if losses > 0 else float("inf"), 4)

    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    trades_per_year = round(len(spy_trades) / years, 1)

    print(
        f"\nH47 FOMC Bi-Weekly Cycle ({start} to {end}):\n"
        f"  FOMC meetings in window: {len(fomc_in_window)} | "
        f"SPY trades (legs): {len(spy_trades)} ({trades_per_year:.1f}/yr)\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor}\n"
        f"  Init cash: ${init_cash:,.0f} | Final equity: ${equity_curve.iloc[-1]:,.2f}"
    )

    return {
        "equity_curve": equity_curve,
        "trades": trade_log,
        "daily_returns": daily_returns,
        "signal_log": signal_log,
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": len(spy_trades),
        "trades_per_year": trades_per_year,
        "fomc_meetings_in_window": len(fomc_in_window),
        "data_quality": {
            "survivorship_bias_flag": "SPY/TLT are market ETFs — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "warmup_bars": ma_period + max(SIGMA_WINDOW, ADV_WINDOW) + 50,
            "gap_flags": ([f"{max_gap} consecutive missing days"] if max_gap >= 5 else []),
            "trend_na_count": trend_na_count,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY still active",
            "fomc_calendar_source": "Hardcoded from Fed FOMC calendar; verify at federalreserve.gov",
            "emergency_meetings_included": "Yes — Oct 8 2008 and Mar 3 2020 included; treat as week 0",
            "slippage_tier": "ED-SLIP-001 ultra-liquid (0.005%) — SPY ADV > 50M shares/day",
        },
    }


if __name__ == "__main__":
    # ── IS period: baseline full Cieslak spec {0,2,4} ────────────────────────
    result_is = run_strategy()
    print(f"\n[IS] Trade count: {result_is['trade_count']} | Sharpe: {result_is['sharpe']}")

    # ── IS: even weeks {0,2} only — sensitivity test ──────────────────────────
    params_narrow = PARAMETERS.copy()
    params_narrow["even_weeks_included"] = [0, 2]
    result_narrow = run_strategy(params_narrow)
    print(f"\n[IS {{0,2}}] Trade count: {result_narrow['trade_count']} | Sharpe: {result_narrow['sharpe']}")

    # ── OOS period ────────────────────────────────────────────────────────────
    params_oos = PARAMETERS.copy()
    params_oos["start_date"] = PARAMETERS["oos_start_date"]
    params_oos["end_date"] = PARAMETERS["oos_end_date"]
    result_oos = run_strategy(params_oos)
    print(f"\n[OOS] Trade count: {result_oos['trade_count']} | Sharpe: {result_oos['sharpe']}")

    print(f"\nSample signal_log (first 10 rows):\n{result_is['signal_log'].head(10).to_string(index=False)}")
    print(f"\nFinal IS equity: ${result_is['equity_curve'].iloc[-1]:,.2f}")
