"""
Strategy: H33 Pre-FOMC Announcement Drift
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: ~80% of the equity risk premium accrues in the 24 hours before each scheduled
            FOMC announcement. Buy SPY at T-1 close, sell at T close (FOMC announcement day).
            A SHY momentum filter skips meetings in aggressive rate-hike environments.
Asset class: equities (SPY ETF)
Parent task: QUA-260
References: Lucca & Moench (2015) JF 70(1); Cieslak, Morse & Vissing-Jorgensen (2019) JF 74(5);
            research/hypotheses/33_pre_fomc_announcement_drift.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── FOMC Announcement Dates 2007–2025 ──────────────────────────────────────────
# Statement release dates (the T in T-1 → T logic).  Scheduled meetings only;
# emergency interim actions (e.g. Mar 2020 conference calls) are excluded because
# the pre-FOMC drift requires the meeting to be known in advance.
# Source: Federal Reserve FOMC meeting calendars (federalreserve.gov)
# NOTE: Cross-check against the official Fed calendar before live deployment.
FOMC_ANNOUNCEMENT_DATES = {
    2007: [
        "2007-01-31", "2007-03-21", "2007-05-09", "2007-06-28",
        "2007-08-07", "2007-09-18", "2007-10-31", "2007-12-11",
    ],
    2008: [
        "2008-01-30", "2008-03-18", "2008-04-30", "2008-06-25",
        "2008-08-05", "2008-09-16", "2008-10-29", "2008-12-16",
    ],
    2009: [
        "2009-01-28", "2009-03-18", "2009-04-29", "2009-06-24",
        "2009-08-12", "2009-09-23", "2009-11-04", "2009-12-16",
    ],
    2010: [
        "2010-01-27", "2010-03-16", "2010-04-28", "2010-06-23",
        "2010-08-10", "2010-09-21", "2010-11-03", "2010-12-14",
    ],
    2011: [
        "2011-01-26", "2011-03-15", "2011-04-27", "2011-06-22",
        "2011-08-09", "2011-09-21", "2011-11-02", "2011-12-13",
    ],
    2012: [
        "2012-01-25", "2012-03-13", "2012-04-25", "2012-06-20",
        "2012-08-01", "2012-09-13", "2012-10-24", "2012-12-12",
    ],
    2013: [
        "2013-01-30", "2013-03-20", "2013-05-01", "2013-06-19",
        "2013-07-31", "2013-09-18", "2013-10-30", "2013-12-18",
    ],
    2014: [
        "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18",
        "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
    ],
    2015: [
        "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
        "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
    ],
    2016: [
        "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
        "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
    ],
    2017: [
        "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
        "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    ],
    2018: [
        "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
        "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    ],
    2019: [
        "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
        "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    ],
    # 2020: emergency Mar 3 / Mar 15 calls excluded; 7 regular scheduled meetings
    2020: [
        "2020-01-29", "2020-04-29", "2020-06-10", "2020-07-29",
        "2020-09-16", "2020-11-05", "2020-12-16",
    ],
    2021: [
        "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
        "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    ],
    2022: [
        "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
        "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    ],
    2023: [
        "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
        "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    ],
    2024: [
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
        "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    ],
    2025: [
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    ],
}

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "SPY",
    "shy_ticker": "SHY",        # iShares 1-3 Year Treasury ETF (SHY inception 2002)
    # Rate-hike filter: skip trade if SHY 10-day return < shy_filter_threshold
    "shy_lookback": 10,          # range: 5–15 days
    "shy_filter_threshold": -0.015,  # -1.5%; range: -0.010 to -0.020
    "apply_shy_filter": True,    # set False for unfiltered baseline (PF-1 check)
    # Emergency overnight stop: if SPY gaps down > this % at T open, exit at open
    "overnight_stop_pct": 0.02,  # 2%; range: 0.015–0.030
    # Position sizing: 100% of available capital into SPY (binary in/out)
    "init_cash": 25000,
}

# ── Transaction Cost Constants (Engineering Director spec) ─────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share fixed
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root impact coefficient k
SIGMA_WINDOW = 20               # 20-day rolling vol for market impact σ
ADV_WINDOW = 20                 # 20-day rolling ADV for Q/ADV ratio
TRADING_DAYS_PER_YEAR = 252


# ── FOMC Calendar Helpers ──────────────────────────────────────────────────────

def get_fomc_dates(year_start: int, year_end: int) -> list:
    """
    Return sorted list of pd.Timestamps for all FOMC announcement dates
    in [year_start, year_end] inclusive.
    """
    result = []
    for yr in range(year_start, year_end + 1):
        for d in FOMC_ANNOUNCEMENT_DATES.get(yr, []):
            result.append(pd.Timestamp(d))
    return sorted(result)


def build_fomc_signal_map(fomc_dates: list, trading_list: list) -> dict:
    """
    Build signal dict mapping T-1 → T for each FOMC announcement date T.

    T-1 is the immediately preceding trading day in the SPY data.
    FOMC dates that fall outside the trading calendar (holidays, etc.) are skipped
    with a warning — in practice the Fed always meets on trading days.

    Returns dict: {t_minus_1_date (Timestamp): t_date (Timestamp)}
    """
    date_to_idx = {d: i for i, d in enumerate(trading_list)}
    trading_set = set(trading_list)
    signal_map = {}

    for fomc_ts in fomc_dates:
        if fomc_ts not in trading_set:
            # Rare: FOMC date is a non-trading day — skip
            warnings.warn(
                f"FOMC date {fomc_ts.date()} not found in SPY trading calendar — skipped"
            )
            continue
        idx = date_to_idx[fomc_ts]
        if idx < 1:
            continue  # no prior trading day in our data window
        t_minus_1 = trading_list[idx - 1]
        signal_map[t_minus_1] = fomc_ts

    return signal_map


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(ticker: str, shy_ticker: str, start: str, end: str) -> dict:
    """
    Download SPY (OHLCV) and SHY (Close) with a warmup window for rolling
    indicators (SIGMA_WINDOW + ADV_WINDOW + shy_lookback).

    Returns dict: {'spy': DataFrame, 'shy': Series (Close)}
    Raises ValueError if data is insufficient or structurally invalid.
    """
    # Warmup: max of rolling windows + buffer (×1.5 for non-trading days)
    warmup_days = max(SIGMA_WINDOW, ADV_WINDOW) + 30  # ~50 calendar days
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")

    spy_df = _download_single(ticker, warmup_start, end)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(spy_df.columns)
    if missing:
        raise ValueError(f"Missing columns for {ticker}: {missing}")
    if len(spy_df) < SIGMA_WINDOW + 10:
        raise ValueError(
            f"Insufficient data for {ticker}: {len(spy_df)} bars (need {SIGMA_WINDOW + 10})"
        )
    na_count = int(spy_df["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing trading days detected")

    shy_raw = _download_single(shy_ticker, warmup_start, end)
    if "Close" not in shy_raw.columns:
        raise ValueError(f"Missing Close for {shy_ticker}")
    shy_close = shy_raw["Close"].rename("shy")

    return {"spy": spy_df, "shy": shy_close}


# ── Rate-Hike Filter (SHY Momentum) ───────────────────────────────────────────

def compute_shy_filter(shy_close: pd.Series, params: dict) -> pd.Series:
    """
    Compute the rate-hike filter from SHY 10-day (shy_lookback) return.

    Returns boolean Series indexed by date:
        True  → filter PASSES (ok to trade) — SHY return > shy_filter_threshold
        False → filter BLOCKS trade — aggressive rate-hike environment

    Uses shift(1) to ensure no look-ahead: on day D we use SHY known as of close D-1.
    For dates before SHY inception (2002) or with insufficient history, returns True
    (no filter applied per hypothesis — only SPY data required pre-2002).
    """
    lookback = params["shy_lookback"]
    threshold = params["shy_filter_threshold"]

    # shy_return[t] = (SHY[t-1] - SHY[t-1-lookback]) / SHY[t-1-lookback]
    # shift(1) so that on entry day D we use yesterday's confirmed close
    shy_return = shy_close.pct_change(lookback).shift(1)

    # Filter passes when return > threshold (SHY hasn't fallen sharply)
    # NaN (insufficient history or pre-SHY-inception) → treat as passing (no filter)
    filter_pass = shy_return.gt(threshold).fillna(True)
    return filter_pass


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
      impact   = k × σ × sqrt(Q / ADV) × price × Q  (Almgren-Chriss square-root model)

    Flags orders where Q/ADV > 1% as liquidity-constrained.
    Returns (total_cost_dollars: float, liquidity_constrained: bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01    # fallback: 1% daily vol
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000  # fallback: 1M shares ADV

    # Square-root market impact (Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV). "
            "Q/ADV > 1% — market impact elevated."
        )

    return fixed + slippage + impact, liq_constrained


# ── H33 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h33(
    spy_df: pd.DataFrame,
    shy_filter: pd.Series,
    fomc_signal_map: dict,
    params: dict,
) -> tuple:
    """
    Simulate H33 Pre-FOMC Announcement Drift on SPY.

    Entry/exit logic:
    - On T-1 (day before FOMC announcement): buy SPY at T-1 close if SHY filter passes
      (or if apply_shy_filter=False).
    - On T (FOMC announcement day):
        * Emergency stop: if SPY open < T-1 close × (1 − overnight_stop_pct), sell at T open.
        * Normal exit: sell at T close.
    - Only one position at a time (FOMC meetings never overlap by construction).

    Returns (trade_log: list, equity: pd.Series, daily_df: pd.DataFrame).
    """
    apply_filter = params["apply_shy_filter"]
    stop_pct = params["overnight_stop_pct"]
    init_cash = float(params["init_cash"])

    dates = spy_df.index
    n = len(dates)
    close_s = spy_df["Close"]
    open_s = spy_df["Open"]
    vol_s = spy_df["Volume"]

    # Align SHY filter to SPY trading calendar; missing days → True (pass)
    shy_filter_aligned = shy_filter.reindex(dates).fillna(True)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_pos = False
    entry_date_ts = None
    entry_close = 0.0       # T-1 close price (raw, before cost adjustment)
    entry_price_eff = 0.0   # effective entry price after transaction costs
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_bar_idx = -1
    exit_target_date = None  # the T (FOMC announcement day) for current position
    shy_passed_at_entry = True

    for i in range(n):
        date = dates[i]
        close_i = float(close_s.iloc[i])
        open_i = float(open_s.iloc[i])

        if in_pos:
            # ── Check for exit on announcement day T ─────────────────────────
            if date == exit_target_date:
                # Emergency overnight stop: if open gaps down > stop_pct from entry close
                overnight_drop = (open_i - entry_close) / max(entry_close, 1e-8)
                if overnight_drop < -stop_pct:
                    # Exit at T open (emergency stop)
                    exit_price_raw = open_i
                    exit_reason = "OVERNIGHT_STOP"
                else:
                    # Normal exit at T close
                    exit_price_raw = close_i
                    exit_reason = "FOMC_CLOSE"

                xcost, xliq = _transaction_cost(
                    exit_price_raw, entry_shares, close_s, vol_s, i
                )
                eff_xp = exit_price_raw - xcost / entry_shares
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
                    "exit_reason": exit_reason,
                    "overnight_return_pct": round(overnight_drop * 100, 4),
                    "shy_filter_passed": shy_passed_at_entry,
                })

                in_pos = False
                entry_date_ts = None
                exit_target_date = None
                entry_bar_idx = -1

            # ── Unexpected case: still in position past exit target ───────────
            elif date > exit_target_date:
                # Should not happen if FOMC calendar is correct; force-exit at close
                warnings.warn(
                    f"Position still open past exit target {exit_target_date.date()} "
                    f"at {date.date()} — force-closing at close."
                )
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
                    "exit_reason": "FORCE_CLOSE",
                    "overnight_return_pct": None,
                    "shy_filter_passed": shy_passed_at_entry,
                })
                in_pos = False
                entry_date_ts = None
                exit_target_date = None
                entry_bar_idx = -1

        # ── Check entry: is today T-1 for a FOMC meeting? ────────────────────
        if not in_pos and date in fomc_signal_map:
            fomc_t_date = fomc_signal_map[date]  # T = FOMC announcement day

            # Apply SHY rate-hike filter (if enabled)
            shy_ok = bool(shy_filter_aligned.iloc[i]) if apply_filter else True

            if shy_ok and close_i > 0 and not pd.isna(close_i):
                shares = int(capital / close_i)
                if shares > 0:
                    cost, liq = _transaction_cost(close_i, shares, close_s, vol_s, i)
                    eff_ep = close_i + cost / shares
                    capital -= eff_ep * shares

                    in_pos = True
                    entry_date_ts = date
                    entry_close = close_i          # raw close for overnight stop calculation
                    entry_price_eff = eff_ep
                    entry_shares = shares
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_bar_idx = i
                    exit_target_date = fomc_t_date
                    shy_passed_at_entry = shy_ok

        # ── Daily mark-to-market ──────────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        daily_records.append({
            "date": date,
            "position": 1 if in_pos else 0,
            "signal_type": "PRE_FOMC" if in_pos else "",
            "equity": mtm,
        })

    # ── Force-close any open position at end of data ─────────────────────────
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
            "exit_reason": "END_OF_DATA",
            "overnight_return_pct": None,
            "shy_filter_passed": shy_passed_at_entry,
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
    Download data, build FOMC signal map, apply SHY rate-hike filter, and
    simulate the H33 Pre-FOMC Announcement Drift strategy.

    Parameters
    ----------
    start : str
        Backtest start date (YYYY-MM-DD).  IS period: "2007-01-01".
    end : str
        Backtest end date (YYYY-MM-DD).  IS period: "2021-12-31".
    params : dict, optional
        Override PARAMETERS dict.  Uses module-level PARAMETERS if None.

    Returns
    -------
    dict
        Standard result with performance metrics, trade log, equity curve,
        daily DataFrame, and data quality flags.  Includes:
        - sharpe, max_drawdown, total_return, win_rate, profit_factor
        - trade_count, trades_per_year, pf1_status
        - fomc_meetings_in_window, shy_filtered_count
        - trades (DataFrame), equity (Series), daily_df (DataFrame)
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    shy_ticker = params["shy_ticker"]
    init_cash = float(params["init_cash"])
    apply_filter = params["apply_shy_filter"]

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 1. Download (warmup window included) ─────────────────────────────────
    data = download_data(ticker, shy_ticker, start, end)

    spy_full = data["spy"]
    shy_full = data["shy"]

    # ── 2. Compute SHY filter on full (warmup-inclusive) series ──────────────
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

    # ── 4. Data quality: check for consecutive missing days ───────────────────
    max_gap = 0
    if spy_df["Close"].isna().any():
        is_na = spy_df["Close"].isna().astype(int)
        max_gap = int(is_na.groupby((~spy_df["Close"].isna()).cumsum()).sum().max())
    if max_gap >= 5:
        warnings.warn(f"Data gap: {max_gap} consecutive missing days in {ticker}")

    shy_na_count = int(shy_filter.isna().sum())
    if shy_na_count > 10:
        warnings.warn(
            f"SHY filter has {shy_na_count} NaN values — some filter decisions used fallback"
        )

    trading_list = sorted(spy_df.index)
    year_start = trading_list[0].year
    year_end = trading_list[-1].year

    # ── 5. Build FOMC signal map: T-1 → T for all meetings in window ─────────
    fomc_dates = get_fomc_dates(year_start, year_end)
    # Keep only dates within the backtest window
    fomc_dates_in_window = [
        d for d in fomc_dates if ts_start <= d <= ts_end
    ]
    fomc_signal_map = build_fomc_signal_map(fomc_dates_in_window, trading_list)

    fomc_meeting_count = len(fomc_dates_in_window)

    # ── 6. Count how many trades SHY filter would block ──────────────────────
    shy_filter_aligned = shy_filter.reindex(spy_df.index).fillna(True)
    shy_blocked_count = 0
    if apply_filter:
        for entry_date in fomc_signal_map:
            if entry_date in shy_filter.index and not shy_filter.loc[entry_date]:
                shy_blocked_count += 1

    # ── 7. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h33(
        spy_df, shy_filter_aligned, fomc_signal_map, params
    )

    # ── 8. Performance metrics ────────────────────────────────────────────────
    years = (ts_end - ts_start).days / 365.25
    n_trades = len(trade_log)
    trades_per_year = round(n_trades / max(years, 1e-3), 1)

    empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price", "shares",
        "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason",
        "overnight_return_pct", "shy_filter_passed",
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

    # Profit factor = sum(wins) / sum(|losses|)
    profit_factor = 0.0
    if n_trades > 0 and not trades_df.empty:
        wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = round(float(wins / losses) if losses > 0 else float("inf"), 4)

    # PF-1: walk-forward viability — need >= 30 trades per fold (4 folds over IS)
    # Unfiltered (apply_shy_filter=False): ~120 IS trades → 30/fold ✅
    # Filtered (apply_shy_filter=True): ~90 IS trades → 22.5/fold ⚠️
    pf1_threshold = 30
    trades_per_wf_fold = round(n_trades / 4, 1)
    if trades_per_wf_fold >= pf1_threshold:
        pf1_status = f"PASS ({trades_per_wf_fold:.1f}/fold ≥ {pf1_threshold})"
    else:
        pf1_status = f"WARN: {trades_per_wf_fold:.1f}/fold < {pf1_threshold}"
        warnings.warn(f"PF-1 WARN: {trades_per_wf_fold:.1f} trades/wf-fold < {pf1_threshold}")

    # Exit reason summary
    exit_reason_summary = {}
    if n_trades > 0:
        exit_reason_summary = trades_df["exit_reason"].value_counts().to_dict()

    filter_label = "filtered" if apply_filter else "unfiltered"
    print(
        f"\nH33 Pre-FOMC Drift Backtest ({start} to {end}) [{filter_label}]:\n"
        f"  FOMC meetings in window: {fomc_meeting_count} | "
        f"SHY-blocked: {shy_blocked_count} | Trades executed: {n_trades} "
        f"({trades_per_year:.1f}/yr)\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor} | "
        f"PF-1: {pf1_status}\n"
        f"  Exit reasons: {exit_reason_summary}\n"
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
            "warmup_bars": max(SIGMA_WINDOW, ADV_WINDOW) + 30,
            "gap_flags": ([f"{max_gap} consecutive missing days"] if max_gap >= 5 else []),
            "shy_na_count": shy_na_count,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY + SHY still active",
            "fomc_calendar_source": "Hardcoded from Fed FOMC calendar; verify at federalreserve.gov",
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
        "fomc_meetings_in_window": fomc_meeting_count,
        "shy_filtered_count": shy_blocked_count,
        "exit_reason_summary": exit_reason_summary,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H33.

    Returns a DataFrame with per-day columns:
        date, position, signal_type, pnl, entry_price, exit_price,
        transaction_cost, exit_reason

    Trade-level fields are populated on the exit date; all other rows carry NaN.
    `ticker` parameter is accepted for orchestrator compatibility but ignored —
    H33 uses SPY via PARAMETERS["ticker"].
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
        daily["exit_reason"] = np.nan
    else:
        trade_cols = trades[
            ["exit_date", "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason"]
        ].copy()
        trade_cols["exit_date"] = pd.to_datetime(trade_cols["exit_date"])
        daily["date"] = pd.to_datetime(daily["date"])

        daily = daily.merge(
            trade_cols.rename(columns={"exit_date": "date"}),
            on="date",
            how="left",
        )

    return daily[[
        "date", "position", "signal_type",
        "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason",
    ]]


if __name__ == "__main__":
    # ── IS period: unfiltered baseline (apply_shy_filter=False) — PF-1 check ─
    params_unfiltered = PARAMETERS.copy()
    params_unfiltered["apply_shy_filter"] = False
    result_is_unfiltered = run_backtest("2007-01-01", "2021-12-31", params_unfiltered)
    print(f"\n[IS Unfiltered] Trade count: {result_is_unfiltered['trade_count']} | "
          f"Sharpe: {result_is_unfiltered['sharpe']}")

    # ── IS period: filtered (apply_shy_filter=True) — main hypothesis ────────
    params_filtered = PARAMETERS.copy()
    params_filtered["apply_shy_filter"] = True
    result_is_filtered = run_backtest("2007-01-01", "2021-12-31", params_filtered)
    print(f"\n[IS Filtered] Trade count: {result_is_filtered['trade_count']} | "
          f"SHY-blocked: {result_is_filtered['shy_filtered_count']} | "
          f"Sharpe: {result_is_filtered['sharpe']}")

    # ── OOS period: filtered ──────────────────────────────────────────────────
    result_oos = run_backtest("2022-01-01", "2025-12-31", params_filtered)
    print(f"\n[OOS Filtered] Trade count: {result_oos['trade_count']} | "
          f"SHY-blocked: {result_oos['shy_filtered_count']} | "
          f"Sharpe: {result_oos['sharpe']}")

    print("\nSample IS filtered trades (first 5):")
    if not result_is_filtered["trades"].empty:
        print(result_is_filtered["trades"].head().to_string(index=False))

    print(f"\nEquity final (IS filtered): ${result_is_filtered['equity'].iloc[-1]:,.2f}")
