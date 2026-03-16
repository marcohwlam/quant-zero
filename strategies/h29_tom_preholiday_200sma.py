"""
Strategy: H29 Combined Calendar: TOM + Pre-Holiday with 200-SMA Regime Filter
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: Two structurally independent calendar effects on SPY — Turn-of-Month (payroll
            flows) and Pre-Holiday (short-covering) — gated by a 200-day SMA regime filter.
            Any signal triggers entry into 100% SPY when SPY > 200-SMA; strategy sits in
            cash during bear regimes (SPY < 200-SMA).
Asset class: equities
Parent task: QUA-246
References: Lakonishok & Smidt (1988); McConnell & Xu (2008); Ariel (1990);
            Kim & Park (1994); H22/H26 hypothesis files; H29 hypothesis file
            research/hypotheses/29_tom_preholiday_200sma.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "SPY",
    "vix_ticker": "^VIX",
    # TOM signal
    "tom_entry_day": -2,              # Days from month-end (range: -3 to -1)
    "tom_exit_day": 3,                # Days into following month (range: +2 to +4)
    "vix_threshold_tom": 28.0,        # VIX filter for TOM (range: 25–32)
    # Pre-Holiday signal
    "vix_threshold_preholiday": 35.0,  # VIX filter for Pre-Holiday (range: None/35/40)
    # Regime filter
    "sma_period": 200,                # SPY SMA lookback period; 200 = canonical bear-market divider
    # Position management
    "max_hold_days": 8,               # Hard cap on trading days in position (range: 7–10)
    "init_cash": 25000,
}

# ── Transaction Cost Constants ─────────────────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share fixed
SLIPPAGE_PCT = 0.0005           # 0.05%
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root impact coefficient k
SIGMA_WINDOW = 20               # 20-day rolling vol for market impact σ
ADV_WINDOW = 20                 # 20-day rolling ADV for market impact Q/ADV ratio
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(ticker: str, vix_ticker: str, start: str, end: str, sma_period: int) -> dict:
    """
    Download SPY and VIX with a warmup window sufficient for the SMA lookback.
    Warmup = max(sma_period + 10, 90) calendar-equivalent days (×1.5 for non-trading days).

    Returns dict with keys: 'spy' (OHLCV DataFrame), 'vix' (Close Series).
    Raises ValueError if data is insufficient or structurally invalid.
    """
    # Warmup must cover at least sma_period trading days (~1.5× calendar days)
    warmup_td = int(sma_period * 1.5) + 30  # extra buffer for weekends/holidays
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_td)).strftime("%Y-%m-%d")

    spy_df = _download_single(ticker, warmup_start, end)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(spy_df.columns)
    if missing:
        raise ValueError(f"Missing columns for {ticker}: {missing}")
    if len(spy_df) < sma_period + 10:
        raise ValueError(f"Insufficient data for {ticker}: {len(spy_df)} bars (need {sma_period + 10})")
    na_count = int(spy_df["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing trading days detected")

    vix_raw = _download_single(vix_ticker, warmup_start, end)
    if "Close" not in vix_raw.columns:
        raise ValueError(f"Missing Close for {vix_ticker}")
    vix = vix_raw["Close"].rename("vix")

    return {"spy": spy_df, "vix": vix}


# ── Calendar Signal Builders ───────────────────────────────────────────────────

def compute_tom_signals(trading_dates: pd.DatetimeIndex, params: dict) -> dict:
    """
    Compute TOM entry → exit date map from the trading calendar.

    entry_day = -2: 2nd-to-last trading day of each month
    exit_day  = +3: 3rd trading day of the following month

    Returns dict: {entry_date (Timestamp): exit_date (Timestamp)}
    """
    entry_day = params["tom_entry_day"]
    exit_day = params["tom_exit_day"]

    df_dates = pd.DataFrame({"date": trading_dates})
    df_dates["ym"] = df_dates["date"].dt.to_period("M")

    months = sorted(df_dates["ym"].unique())
    month_to_days = {
        ym: sorted(df_dates[df_dates["ym"] == ym]["date"].tolist())
        for ym in months
    }

    tom_signals = {}
    for i, ym in enumerate(months):
        month_days = month_to_days[ym]
        n = len(month_days)

        # Negative entry_day: index from end (e.g., -2 → n-2; -1 → n-1 = last day)
        entry_idx = n + entry_day if entry_day < 0 else entry_day - 1
        if not (0 <= entry_idx < n):
            continue
        entry_date = month_days[entry_idx]

        if i + 1 >= len(months):
            continue
        next_days = month_to_days[months[i + 1]]
        # exit_day=3 → index 2 (Day+1=idx0, Day+2=idx1, Day+3=idx2)
        exit_idx = exit_day - 1
        if not (0 <= exit_idx < len(next_days)):
            continue

        tom_signals[entry_date] = next_days[exit_idx]

    return tom_signals


def compute_preholiday_signals(
    trading_dates: pd.DatetimeIndex, year_start: int, year_end: int
) -> dict:
    """
    Compute Pre-Holiday entry → exit date map.

    For each US NYSE holiday in [year_start, year_end]:
    - Exit: Day -1 = last trading day before the holiday
    - Entry: Day -2 = 2nd trading day before the holiday
      (If Day -2 is non-trading, use Day -3 instead)

    VIX filter is applied in simulate_h29, not here.

    Returns dict: {entry_date (Timestamp): exit_date (Timestamp)}
    """
    trading_list = sorted(trading_dates)
    trading_set = set(trading_list)
    # O(1) position lookup: date → index in trading_list
    date_to_idx = {d: i for i, d in enumerate(trading_list)}

    holiday_dates = _get_nyse_holidays(year_start - 1, year_end + 1)

    preholiday_signals = {}
    for holiday_ts in holiday_dates:
        # Day -1: walk backward from holiday to find last trading day before it
        day_minus_1 = None
        t = holiday_ts - pd.Timedelta(days=1)
        for _ in range(7):
            if t in trading_set:
                day_minus_1 = t
                break
            t -= pd.Timedelta(days=1)

        if day_minus_1 is None:
            continue

        idx_m1 = date_to_idx.get(day_minus_1)
        if idx_m1 is None or idx_m1 < 1:
            continue

        # Day -2: one step further back in the trading calendar
        day_minus_2 = trading_list[idx_m1 - 1]
        if day_minus_2 not in trading_set:
            continue

        # Restrict to dates within the backtest range
        if day_minus_2 < trading_list[0] or day_minus_1 > trading_list[-1]:
            continue

        preholiday_signals[day_minus_2] = day_minus_1

    return preholiday_signals


def _get_nyse_holidays(year_start: int, year_end: int) -> list:
    """
    Retrieve NYSE holiday dates between year_start and year_end.
    Prefers pandas_market_calendars; falls back to pandas US Federal holiday rules.
    """
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(
            start_date=f"{year_start}-01-01", end_date=f"{year_end}-12-31"
        )
        # All business days in range
        full_bdays = pd.bdate_range(
            start=f"{year_start}-01-01", end=f"{year_end}-12-31"
        )
        open_days = set(schedule.index.normalize())
        holiday_dates = [pd.Timestamp(d) for d in full_bdays if pd.Timestamp(d) not in open_days]
        return holiday_dates
    except ImportError:
        warnings.warn(
            "pandas_market_calendars not installed — using pandas US Federal holiday fallback."
        )
        return _manual_nyse_holidays(year_start, year_end)


def _manual_nyse_holidays(year_start: int, year_end: int) -> list:
    """
    Generate approximate NYSE holiday dates using pandas US Federal holiday rules.
    Covers the 9 standard NYSE holidays with observance (nearest weekday).
    """
    from pandas.tseries.holiday import (  # noqa: PLC0415
        AbstractHolidayCalendar, Holiday, nearest_workday,
        USMartinLutherKingJr, USPresidentsDay, USMemorialDay, USLaborDay,
        USThanksgivingDay,
    )

    class _NYSEHolidayCalendar(AbstractHolidayCalendar):
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

    cal = _NYSEHolidayCalendar()
    holidays = cal.holidays(start=f"{year_start}-01-01", end=f"{year_end}-12-31")
    return [pd.Timestamp(d) for d in holidays]


# ── Regime Filter ──────────────────────────────────────────────────────────────

def compute_sma_regime(close_series: pd.Series, sma_period: int) -> pd.Series:
    """
    Compute 200-day (or sma_period-day) SMA regime gate.

    Returns boolean Series: True when close[-1] > SMA[-1], i.e. prior-day close
    was above its rolling SMA. This is evaluated as of the entry bar to prevent
    look-ahead — a True on date T means T-1 close was above its SMA.

    Uses .shift(1) so that on any given entry day, we use yesterday's confirmed
    close vs. yesterday's SMA (no same-bar look-ahead).
    """
    sma = close_series.rolling(sma_period).mean()
    # Regime is active when prior-day close exceeds prior-day SMA
    regime_active = (close_series.shift(1) > sma.shift(1))
    return regime_active


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
      impact   = k × σ × sqrt(Q / ADV) × notional  (Almgren-Chriss square-root model)

    Flags orders where Q/ADV > 1% as liquidity-constrained (warns and records flag).
    Returns (total_cost_dollars, liquidity_constrained_bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01   # fallback: 1% daily vol
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000   # fallback: 1M shares ADV

    # Square-root market impact (Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV)"
        )

    return fixed + slippage + impact, liq_constrained


# ── H29 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h29(
    spy_df: pd.DataFrame,
    vix: pd.Series,
    tom_signals: dict,
    preholiday_signals: dict,
    regime: pd.Series,
    params: dict,
) -> tuple:
    """
    Simulate H29 TOM + Pre-Holiday with 200-SMA Regime Filter.

    Entry/exit logic (per hypothesis overlap rules):
    - Regime gate: Entry only allowed when regime=True (SPY > 200-SMA using prior-day values).
                   Existing positions are NOT force-exited when regime flips False mid-trade.
    - Rule 1: Any signal firing today (VIX filter passes + regime gate passes) triggers
              entry if in cash.
    - Rule 2: If already in SPY and a new signal fires, extend the active_exit_dates set
              (maintain position — no unnecessary round-trip).
    - Rule 3: Exit only when date >= max(active_exit_dates.values()).
    - Rule 4: Hard cap — never hold beyond entry_bar + max_hold_days trading days.
    - Rule 5: VIX and regime filters evaluated only at each signal's entry day, not mid-position.

    Returns (trade_log list, equity pd.Series, daily_df pd.DataFrame).
    daily_df columns: date (index), signal_active, position, signal_type,
                      equity, regime_active.
    """
    vix_thresh_tom = params["vix_threshold_tom"]
    vix_thresh_ph = params["vix_threshold_preholiday"]
    max_hold = params["max_hold_days"]
    init_cash = float(params["init_cash"])

    dates = spy_df.index
    n = len(dates)
    close_s = spy_df["Close"]
    vol_s = spy_df["Volume"]
    vix_aligned = vix.reindex(dates)
    regime_aligned = regime.reindex(dates).fillna(False)

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
    active_exit_dates = {}   # {signal_name: exit_date Timestamp}
    active_signal_types = set()
    entry_regime_active = False  # regime state recorded at entry for trade log

    for i in range(n):
        date = dates[i]
        close_i = float(close_s.iloc[i])
        vix_val = vix_aligned.iloc[i]
        vix_i = float(vix_val) if not pd.isna(vix_val) else np.nan
        regime_i = bool(regime_aligned.iloc[i])  # True = SPY > 200-SMA (prior-day basis)

        # ── Determine which signals fire today with passing VIX + regime filters ─
        fired_signals = {}
        if regime_i:  # regime gate: only evaluate calendar signals when SPY > 200-SMA
            if date in tom_signals and not pd.isna(vix_i) and vix_i <= vix_thresh_tom:
                fired_signals["TOM"] = tom_signals[date]
            if date in preholiday_signals and not pd.isna(vix_i) and vix_i <= vix_thresh_ph:
                fired_signals["PRE_HOLIDAY"] = preholiday_signals[date]

        # ── Position management ───────────────────────────────────────────────
        if in_pos:
            # Rule 2: Extend active set with any new signals firing today
            # (regime filter not re-evaluated for in-flight positions)
            for sig_name, sig_exit in fired_signals.items():
                if sig_name not in active_signal_types:
                    active_exit_dates[sig_name] = sig_exit
                    active_signal_types.add(sig_name)

            # Rule 3 + 4: exit on latest active signal, capped at max_hold_days
            latest_exit = max(active_exit_dates.values()) if active_exit_dates else date
            cap_idx = min(entry_bar_idx + max_hold, n - 1)
            effective_exit = min(latest_exit, dates[cap_idx])

            # Exit at close if we've reached or passed the effective exit date
            # Guard: do not exit on the same bar we entered (entry_date_ts < date)
            if date >= effective_exit and date > entry_date_ts:
                xcost, xliq = _transaction_cost(close_i, entry_shares, close_s, vol_s, i)
                eff_xp = close_i - xcost / entry_shares
                pnl = (eff_xp - entry_price_eff) * entry_shares
                capital += eff_xp * entry_shares

                trade_log.append({
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
                    "signal_types": ",".join(sorted(active_signal_types)),
                    "exit_reason": "CAP" if date == dates[cap_idx] else "CALENDAR",
                    "regime_active": entry_regime_active,
                })

                in_pos = False
                active_exit_dates = {}
                active_signal_types = set()
                entry_date_ts = None
                entry_bar_idx = -1
                entry_regime_active = False

        # ── Rule 1: Enter on any qualifying signal if in cash ─────────────────
        if not in_pos and fired_signals and close_i > 0 and not pd.isna(close_i):
            shares = int(capital / close_i)
            if shares > 0:
                cost, liq = _transaction_cost(close_i, shares, close_s, vol_s, i)
                eff_ep = close_i + cost / shares
                capital -= eff_ep * shares

                in_pos = True
                entry_date_ts = date
                entry_price_eff = eff_ep
                entry_shares = shares
                entry_cost_total = cost
                entry_liq = liq
                entry_bar_idx = i
                active_exit_dates = dict(fired_signals)
                active_signal_types = set(fired_signals.keys())
                entry_regime_active = regime_i

        # ── Daily mark-to-market ──────────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        daily_records.append({
            "date": date,
            "signal_active": len(active_exit_dates) > 0,
            "position": 1 if in_pos else 0,
            "signal_type": ",".join(sorted(active_signal_types)) if in_pos else "",
            "equity": mtm,
            "regime_active": regime_i,
        })

    # ── Force close any open position at end of data ──────────────────────────
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
            "entry_price": round(entry_price_eff, 4),
            "exit_price": round(eff_xp, 4),
            "shares": entry_shares,
            "pnl": round(pnl, 2),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(xcost, 4),
            "transaction_cost": round(entry_cost_total + xcost, 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_days": i - entry_bar_idx,
            "signal_types": ",".join(sorted(active_signal_types)),
            "exit_reason": "END_OF_DATA",
            "regime_active": entry_regime_active,
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
    Download data, compute 200-SMA regime, build signal calendars, and simulate
    H29 TOM + Pre-Holiday with 200-SMA Regime Filter.

    Parameters
    ----------
    start : str
        Backtest start date (YYYY-MM-DD). E.g. "2007-01-01" for IS period.
    end : str
        Backtest end date (YYYY-MM-DD). E.g. "2021-12-31" for IS period.
    params : dict, optional
        Override PARAMETERS. Uses module-level PARAMETERS if None.

    Returns
    -------
    dict
        Standardised result with performance metrics, trade log, equity curve,
        daily DataFrame (with regime_active column), and data quality flags.
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    vix_ticker = params["vix_ticker"]
    sma_period = params["sma_period"]
    init_cash = float(params["init_cash"])

    # ── 1. Download (with warmup for SMA + rolling cost model) ────────────────
    data = download_data(ticker, vix_ticker, start, end, sma_period)

    # ── 2. Trim to backtest window ────────────────────────────────────────────
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    spy_full = data["spy"]  # includes warmup; used to compute rolling SMA
    vix_full = data["vix"]

    # Compute regime on full (warmup-inclusive) series so SMA is warmed up at start
    regime_full = compute_sma_regime(spy_full["Close"], sma_period)

    # Now trim to the actual backtest window
    spy_df = spy_full.loc[
        (spy_full.index >= ts_start) & (spy_full.index <= ts_end)
    ].copy()
    vix = vix_full.loc[
        (vix_full.index >= ts_start) & (vix_full.index <= ts_end)
    ]
    regime = regime_full.loc[
        (regime_full.index >= ts_start) & (regime_full.index <= ts_end)
    ]

    if len(spy_df) < 10:
        raise ValueError(
            f"Insufficient SPY data after trimming to {start}–{end}: {len(spy_df)} bars"
        )

    # Validate that SMA warmup was sufficient (should have no NaN at start)
    regime_na = int(regime.isna().sum())
    if regime_na > 0:
        warnings.warn(
            f"Regime series has {regime_na} NaN values at backtest start — "
            f"warmup window may be insufficient for sma_period={sma_period}"
        )

    trading_dates = spy_df.index
    year_start, year_end = trading_dates[0].year, trading_dates[-1].year

    # ── 3. Build signal calendars from the SPY trading date list ─────────────
    tom_signals = compute_tom_signals(trading_dates, params)
    preholiday_signals = compute_preholiday_signals(trading_dates, year_start, year_end)

    # ── 4. Data quality: check consecutive missing days ───────────────────────
    max_gap = 0
    if spy_df["Close"].isna().any():
        is_na = spy_df["Close"].isna().astype(int)
        max_gap = int(is_na.groupby((~spy_df["Close"].isna()).cumsum()).sum().max())
    if max_gap >= 5:
        warnings.warn(f"Data gap: {max_gap} consecutive missing days in {ticker}")

    # VIX gap check
    vix_na = int(vix.isna().sum())
    if vix_na > 10:
        warnings.warn(f"VIX data has {vix_na} missing values — some signal filters may use NaN VIX")

    # ── 5. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h29(
        spy_df, vix, tom_signals, preholiday_signals, regime, params
    )

    # ── 6. Performance metrics ────────────────────────────────────────────────
    n_trades = len(trade_log)
    years = (ts_end - ts_start).days / 365.25
    trades_per_year = round(n_trades / max(years, 1e-3), 1)

    empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "signal_types", "exit_reason",
        "regime_active",
    ]
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)

    daily_returns = equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values
    sharpe = 0.0
    if len(ret_arr) > 0 and ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)
    win_rate = round(float((trades_df["pnl"] > 0).mean()), 4) if n_trades > 0 else 0.0

    # PF-1: minimum trade frequency (30 trades per walk-forward fold)
    pf1_status = "PASS" if trades_per_year >= 30 else f"WARN: {trades_per_year:.1f}/yr < 30"

    # Regime stats: fraction of backtest days where regime was active
    regime_pct = round(float(regime.mean()), 4) if len(regime) > 0 else 0.0

    tom_count = len(tom_signals)
    ph_count = len(preholiday_signals)

    print(
        f"\nH29 TOM + Pre-Holiday + 200-SMA Backtest ({start} to {end}):\n"
        f"  Signal calendar: TOM={tom_count}, Pre-Holiday={ph_count} potential entries\n"
        f"  Regime (SPY > {sma_period}-SMA) active: {regime_pct:.1%} of backtest days\n"
        f"  Trades executed: {n_trades} ({trades_per_year}/yr) — PF-1: {pf1_status}\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Init cash: ${init_cash:,.0f}"
    )

    if trades_per_year < 30:
        warnings.warn(f"PF-1 WARN: {trades_per_year:.1f} trades/yr < 30 threshold")

    return {
        "returns": daily_returns,
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params,
        "data_quality": {
            "survivorship_bias_flag": "SPY is a market ETF — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "warmup_bars": sma_period + 30,
            "gap_flags": ([f"{max_gap} consecutive missing days"] if max_gap >= 5 else []),
            "vix_na_count": vix_na,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY still active",
        },
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "pf1_status": pf1_status,
        "tom_signal_count": tom_count,
        "preholiday_signal_count": ph_count,
        "regime_pct": regime_pct,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H29.

    Returns a DataFrame with per-day columns:
        date, signal_active, position, signal_type,
        pnl, entry_price, exit_price, transaction_cost, regime_active

    Trade-level fields (pnl, entry_price, exit_price, transaction_cost) are populated
    on the exit date of each trade; all other rows carry NaN for those columns.
    `ticker` is ignored — H29 uses SPY via PARAMETERS["ticker"].
    """
    p = (params or PARAMETERS).copy()
    result = run_backtest(start, end, p)

    daily = result["daily_df"].reset_index()
    trades = result["trades"]

    if trades.empty:
        daily["pnl"] = np.nan
        daily["entry_price"] = np.nan
        daily["exit_price"] = np.nan
        daily["transaction_cost"] = np.nan
    else:
        trade_cols = trades[
            ["exit_date", "pnl", "entry_price", "exit_price", "transaction_cost"]
        ].copy()
        trade_cols["exit_date"] = pd.to_datetime(trade_cols["exit_date"])
        daily["date"] = pd.to_datetime(daily["date"])

        daily = daily.merge(
            trade_cols.rename(columns={"exit_date": "date"}),
            on="date",
            how="left",
        )

    return daily[[
        "date", "signal_active", "position", "signal_type",
        "pnl", "entry_price", "exit_price", "transaction_cost", "regime_active",
    ]]


if __name__ == "__main__":
    # IS period: 2007–2021 (quality gate requires this to run clean)
    result = run_backtest("2007-01-01", "2021-12-31")
    print("\nSample trades (first 5):")
    if not result["trades"].empty:
        print(result["trades"].head().to_string(index=False))
    print(f"\nEquity final: ${result['equity'].iloc[-1]:,.2f}")
    print(f"TOM signals: {result['tom_signal_count']} | "
          f"Pre-Holiday signals: {result['preholiday_signal_count']}")
    print(f"Regime active: {result['regime_pct']:.1%} of IS days")
    print(f"Total trade count (IS 2007–2021): {result['trade_count']}")
