"""
Strategy: H38 IWM/QQQ Rate-Cycle Factor Rotation
Author: Strategy Coder Agent (Engineering Director)
Date: 2026-03-17
Hypothesis: Small-cap value stocks (IWM — Russell 2000) and large-cap growth stocks
            (QQQ — NASDAQ-100) represent opposite ends of the equity duration spectrum.
            When the 2-year Treasury yield is in a sustained rising trend (4-week rate
            change > +15bp), go LONG IWM / SHORT QQQ (or LONG QID as margin-free
            alternative). Flat otherwise.

Asset class: US equity ETFs — IWM, QQQ, QID
Parent task: QUA-302
References:
    - Fama, F. & French, K. (1992). "The Cross-Section of Expected Stock Returns." JF 47(2).
    - Asness, C. et al. (2013). "Value and Momentum Everywhere." JF 68(3).
    - Damodaran, A. (2020). "Equity Risk Premiums: Determinants, Estimation and Implications."
    - Binsbergen, J. & Koijen, R. (2017). "The Term Structure of Returns."
    - research/hypotheses/38_smallcap_value_growth_spread.md

Signal: 4-week change in FRED DGS2 (2-year Treasury constant maturity yield)
    - Signal ON  (rising rates): rate_change_4w > +0.15% (15bp)
    - Signal OFF (stable/falling): rate_change_4w <= 0.0%
    - Hysteresis: remains ON until rate_change_4w < -0.10%; remains OFF until > +0.15%

Position when ON:
    - Long  50% NAV in IWM
    - Short 50% NAV in QQQ (direct short) OR Long 50% NAV in QID (2× inverse QQQ)

Position when OFF:
    - Flat/cash (0% exposure)

Rebalancing: Weekly at Friday close; dollar-match IWM/QQQ legs every 4 weeks
Stop-loss: Per-position −10% from entry; full spread stop if MDD > −15%

IS  window: 2007-01-01 to 2021-12-31
OOS window: 4 non-overlapping 36m IS / 6m OOS walk-forward windows

Data quality notes:
    - Survivorship bias: IWM (launched 2000), QQQ (launched 1999), QID (launched 2006)
      all actively traded throughout the full IS window 2007-2021. No delisting risk.
    - Price adjustments: yfinance auto_adjust=True for all ETFs.
    - Earnings exclusion: N/A — ETFs have no earnings events.
    - Data gaps: IWM, QQQ, QID trade on all US market trading days. Gaps only on
      US market holidays — expected behavior, not data gaps.
    - FRED DGS2: free via pandas-datareader. Weekend/holiday forward-fill of up to 5 days.
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

try:
    import pandas_datareader.data as web
    _PDR_AVAILABLE = True
except ImportError:
    _PDR_AVAILABLE = False
    warnings.warn(
        "pandas_datareader not available. FRED DGS2 will be simulated. "
        "Install with: pip install pandas-datareader"
    )


# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    # Signal thresholds (percentage points, not basis points)
    "rate_threshold_on": 0.15,     # 15bp: enter when 4w rate change > +0.15%
    "rate_threshold_exit": -0.10,  # -10bp: exit (hysteresis) when 4w rate change < -0.10%
    "rate_lookback_weeks": 4,      # 4-week (20 trading day) lookback for rate change
    # Allocation
    "long_alloc": 0.50,            # 50% NAV long IWM
    "short_alloc": 0.50,           # 50% NAV short QQQ (or long QID)
    "hedge_ratio": 1.0,            # dollar hedge ratio IWM/QQQ (1.0 = dollar-neutral)
    # Short vehicle
    "short_vehicle": "QID",        # "QQQ" for direct short, "QID" for inverse ETF
    # Stop-loss
    "per_position_stop": 0.10,     # -10% per individual position from entry
    "spread_mdd_stop": 0.15,       # -15% spread drawdown stop (full position exit)
    # Rebalancing
    "rebal_weeks": 4,              # dollar-match rebalancing every N weeks
    # Capital
    "init_cash": 25000,
}

# ── Transaction Cost Constants (canonical equities/ETF model) ──────────────────
# Source: Engineering Director spec — Johnson, Algorithmic Trading & DMA (Book 6)
FIXED_COST_PER_SHARE = 0.005    # $0.005/share per leg
SLIPPAGE_PCT = 0.0005           # 0.05% per leg (one-way)
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root model coefficient
SIGMA_WINDOW = 20               # rolling vol window for σ in market impact
ADV_WINDOW = 20                 # rolling volume window for ADV in market impact
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def download_etf_data(
    start: str,
    end: str,
) -> tuple:
    """
    Download IWM, QQQ, QID daily OHLCV data with warmup period.

    Warmup = 40 trading days (for SIGMA_WINDOW, ADV_WINDOW, and DGS2 lookback).
    yfinance auto_adjust=True: prices adjusted for splits and distributions.

    Returns
    -------
    close_df  (pd.DataFrame): columns = [IWM, QQQ, QID], daily close prices
    open_df   (pd.DataFrame): columns = [IWM, QQQ, QID], daily open prices
    volume_df (pd.DataFrame): columns = [IWM, QQQ, QID], daily volume
    """
    warmup_days = ADV_WINDOW * 2 + 60  # buffer for weekends/holidays
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_days)
    ).strftime("%Y-%m-%d")

    tickers = ["IWM", "QQQ", "QID"]
    raw = yf.download(
        tickers, start=warmup_start, end=end, auto_adjust=True, progress=False
    )

    if isinstance(raw.columns, pd.MultiIndex):
        close_df = raw["Close"][tickers].copy()
        open_df = raw["Open"][tickers].copy()
        volume_df = raw["Volume"][tickers].copy()
    else:
        # Fallback for single-ticker download (shouldn't happen with list)
        close_df = raw[["Close"]].rename(columns={"Close": tickers[0]})
        open_df = raw[["Open"]].rename(columns={"Open": tickers[0]})
        volume_df = raw[["Volume"]].rename(columns={"Volume": tickers[0]})

    return close_df, open_df, volume_df


def download_dgs2(start: str, end: str) -> pd.Series:
    """
    Download FRED DGS2 (2-Year Treasury Constant Maturity Rate) via pandas_datareader.

    DGS2 is a daily series published by FRED. Units: percent (e.g., 2.50 = 2.50%).
    Forward-filled over weekends and US market holidays (limit=5).

    Returns pd.Series with daily index, values = DGS2 rate (percent).
    If pandas_datareader unavailable, returns None (caller handles fallback).
    """
    # Extend start by 2 months to cover the lookback period
    fred_start = (pd.Timestamp(start) - pd.DateOffset(months=3)).strftime("%Y-%m-%d")

    if not _PDR_AVAILABLE:
        warnings.warn("pandas_datareader not available. DGS2 signal will be unavailable.")
        return None

    try:
        raw = web.DataReader("DGS2", "fred", fred_start, end)
        if isinstance(raw, pd.DataFrame):
            raw = raw.iloc[:, 0]
        # DGS2 has NaN on non-business days; forward-fill up to 5 days
        dgs2 = raw.asfreq("B").ffill(limit=5)
        return dgs2.rename("DGS2")
    except Exception as exc:
        warnings.warn(f"FRED DGS2 fetch failed: {exc}. Rate signal unavailable.")
        return None


# ── Data Quality Checklist ─────────────────────────────────────────────────────

def check_data_quality(close_df: pd.DataFrame, start: str, end: str) -> dict:
    """
    Run pre-backtest data quality checks per Engineering Director checklist.

    Documented decisions (H38-specific):
    - Survivorship bias: IWM (launched 2000), QQQ (launched 1999), QID (launched 2006)
      all survive through the full IS window 2007-2021. CHOICE: current constituent list
      (no delisting risk for these broad-market ETFs). Justified: IWM/QQQ/QID are index
      tracking vehicles for major indices — they do not get delisted during bull/bear cycles.
    - Price adjustments: yfinance auto_adjust=True for all ETFs.
    - Earnings exclusion: N/A — ETFs have no individual company earnings events.
    - Delisted tickers: None. All three ETFs actively trade through 2026.
    """
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    report = {
        "survivorship_bias": (
            "IWM (launched 2000): active through full IS window 2007-2021. ✓\n"
            "QQQ (launched 1999): active through full IS window 2007-2021. ✓\n"
            "QID (launched 2006): active through full IS window 2007-2021. ✓\n"
            "CHOICE: Current constituent list (no survivorship concern for broad index ETFs). "
            "Justified: IWM, QQQ, QID are major index vehicles, not individual stocks."
        ),
        "price_adjustments": "yfinance auto_adjust=True for all ETFs. ✓",
        "earnings_exclusion": "N/A — ETFs have no individual company earnings events. ✓",
        "delisted_tickers": "None. All three ETFs actively trade through 2026. ✓",
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
        }

    return report


# ── Signal Generation ──────────────────────────────────────────────────────────

def compute_rate_signal(
    dgs2: pd.Series,
    etf_index: pd.DatetimeIndex,
    params: dict,
) -> pd.Series:
    """
    Compute the weekly rate-regime signal with hysteresis.

    Steps:
    1. Align DGS2 to ETF trading calendar (reindex + ffill).
    2. Compute 4-week rate change = DGS2_today - DGS2_N_trading_days_ago.
    3. Apply hysteresis state machine:
       - ON  when rate_change_4w > threshold_on (+0.15%)
       - EXIT when rate_change_4w < threshold_exit (-0.10%)
       - Hold state between these bands

    The signal is computed on all trading days but only acted upon on Fridays
    (weekly rebalancing). Signal carry-forward is applied for mid-week days.

    Returns pd.Series with index = etf_index, values = {0: flat, 1: active}.
    If DGS2 is unavailable, returns all-zero series (strategy stays flat).

    Feature explanation: rate_change_4w measures the trend in 2yr Treasury yields
    over the past 4 weeks. Positive values indicate a rate-rising regime where
    IWM should outperform QQQ due to equity duration differential. All features
    are lagged by construction (rate change uses PAST data only).
    """
    lookback_days = params["rate_lookback_weeks"] * 5  # approximate trading days per week

    if dgs2 is None or dgs2.empty:
        warnings.warn("DGS2 unavailable — signal set to all-zero (flat).")
        return pd.Series(0, index=etf_index, name="signal")

    # Align DGS2 to ETF trading calendar
    dgs2_aligned = dgs2.reindex(etf_index).ffill(limit=5).fillna(method="bfill")

    # Compute N-day rate change (lagged by 1 day to prevent look-ahead)
    # rate_change_4w[t] = DGS2[t-1] - DGS2[t-1-lookback_days]
    # Using shift(1) ensures we only use information available at close of day t-1
    dgs2_shifted = dgs2_aligned.shift(1)
    rate_change = dgs2_shifted - dgs2_shifted.shift(lookback_days)

    threshold_on = params["rate_threshold_on"]
    threshold_exit = params["rate_threshold_exit"]

    # Hysteresis state machine — vectorized implementation
    # State: 0 = OFF (flat), 1 = ON (long IWM / short QQQ)
    states = pd.Series(0, index=etf_index, name="signal")
    rate_vals = rate_change.values
    state = 0

    for i, rc in enumerate(rate_vals):
        if np.isnan(rc):
            states.iloc[i] = 0
            continue
        if state == 0 and rc > threshold_on:
            state = 1
        elif state == 1 and rc < threshold_exit:
            state = 0
        states.iloc[i] = state

    return states


def get_friday_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return all Fridays (weekday == 4) in the given index."""
    return index[index.dayofweek == 4]


# ── Transaction Costs ──────────────────────────────────────────────────────────

def compute_transaction_cost(
    price: float,
    shares: float,
    sigma: float,
    adv: float,
) -> float:
    """
    Compute total one-way transaction cost per the canonical equities/ETF model.

    cost = fixed_cost + slippage + market_impact
    - fixed_cost   = $0.005/share × |shares|
    - slippage     = 0.05% × price × |shares|
    - market_impact = 0.1 × σ × sqrt(Q / ADV) × price × |shares|
      where Q = |shares|, σ = 20-day rolling daily return σ, ADV = 20-day avg volume

    Source: Johnson — Algorithmic Trading & DMA (Book 6)
    """
    q = abs(shares)
    if q == 0:
        return 0.0, False  # always return tuple

    fixed_cost = FIXED_COST_PER_SHARE * q
    slippage = SLIPPAGE_PCT * price * q

    # Market impact (Almgren-Chriss square-root model)
    if adv > 0 and sigma > 0:
        impact_per_share = MARKET_IMPACT_K * sigma * np.sqrt(q / adv) * price
        market_impact = impact_per_share * q
    else:
        market_impact = 0.0

    liquidity_constrained = (adv > 0) and (q / adv > 0.01)

    return fixed_cost + slippage + market_impact, liquidity_constrained


def compute_tc_simple(price: float, shares: float) -> float:
    """Simplified TC when sigma/ADV unavailable (fixed + slippage only)."""
    q = abs(shares)
    return FIXED_COST_PER_SHARE * q + SLIPPAGE_PCT * price * q


# ── Backtest Engine ────────────────────────────────────────────────────────────

def run_backtest(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    dgs2: pd.Series,
    params: dict,
    start: str,
    end: str,
) -> dict:
    """
    Run H38 IWM/QQQ Rate-Cycle Factor Rotation backtest.

    Execution model:
    - Signal computed at Friday close using DGS2 (lagged 1 day)
    - Trades executed at NEXT Monday open (1-day execution lag)
    - If next Monday is unavailable (holiday), use next available day
    - Stop-loss checked daily at close

    Position sizing:
    - Long leg: long_alloc × NAV → buy floor(dollars / price) shares of IWM
    - Short leg: short_alloc × hedge_ratio × NAV →
        If QQQ direct short: sell floor(dollars / price) shares of QQQ
        If QID: buy floor(dollars / (price × 2)) shares of QID (2× leverage)

    Short vehicle note:
    - QQQ direct short: simulated as negative position, profit = -(QQQ return) × notional
    - QID: long QID, profit = QID return × notional (QID ≈ -2× daily QQQ return)
    - At 50% allocation with QID at 2× leverage: effective QQQ short = 50% × 2× = 100%
      But we allocate 50% NAV × 0.5 shares to get 1× effective — i.e., buy QID at 25% NAV
      Wait: the hypothesis says "long 50% QID ≈ 1× QQQ short at 50% portfolio weight"
      This means: buy QID worth 50% NAV → since QID is 2× inverse, this = 1× QQQ short
      on 50% of portfolio. Correct as stated.

    Returns dict with trade_log, equity_curve, metrics.
    """
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # Slice to backtest window
    idx = close_df.index
    mask = (idx >= ts_start) & (idx <= ts_end)
    dates = idx[mask]

    if len(dates) == 0:
        return {"error": "No data in backtest window"}

    # Precompute rolling sigma and ADV for market impact
    sigma_iwm = close_df["IWM"].pct_change().rolling(SIGMA_WINDOW).std()
    sigma_qqq = close_df["QQQ"].pct_change().rolling(SIGMA_WINDOW).std()
    sigma_qid = close_df["QID"].pct_change().rolling(SIGMA_WINDOW).std()
    adv_iwm = volume_df["IWM"].rolling(ADV_WINDOW).mean()
    adv_qqq = volume_df["QQQ"].rolling(ADV_WINDOW).mean()
    adv_qid = volume_df["QID"].rolling(ADV_WINDOW).mean()

    # Compute rate signal over the full index (with warmup)
    signal_full = compute_rate_signal(dgs2, idx, params)
    signal = signal_full.loc[dates]

    short_vehicle = params["short_vehicle"]  # "QQQ" or "QID"
    init_cash = params["init_cash"]
    long_alloc = params["long_alloc"]
    short_alloc = params["short_alloc"] * params["hedge_ratio"]
    per_pos_stop = params["per_position_stop"]
    spread_mdd_stop = params["spread_mdd_stop"]

    # State variables
    cash = float(init_cash)
    pos_iwm = 0          # shares of IWM (long > 0)
    pos_qqq = 0          # shares of QQQ (short < 0 if direct short, else 0)
    pos_qid = 0          # shares of QID (long > 0 if using QID, else 0)
    entry_price_iwm = 0.0
    entry_price_short = 0.0  # entry price for short leg (QQQ or QID)
    in_position = False
    rebal_week_counter = 0
    peak_spread_value = init_cash  # for spread MDD tracking
    spread_stop_triggered = False

    # Trade log
    trade_log = []
    equity_curve = []
    weekly_signal_log = []

    friday_dates = set(get_friday_dates(dates))
    rebal_weeks = params["rebal_weeks"]

    def get_nav(date):
        """Compute current portfolio NAV."""
        c_iwm = close_df["IWM"].loc[date]
        if short_vehicle == "QQQ":
            c_short = close_df["QQQ"].loc[date]
            return cash + pos_iwm * c_iwm + pos_qqq * c_short
        else:  # QID
            c_short = close_df["QID"].loc[date]
            return cash + pos_iwm * c_iwm + pos_qid * c_short

    def execute_entry(exec_date):
        """Execute entry at open on exec_date."""
        nonlocal cash, pos_iwm, pos_qqq, pos_qid, in_position
        nonlocal entry_price_iwm, entry_price_short, peak_spread_value

        nav = cash  # at entry, in_position is False → cash = full NAV
        long_dollars = long_alloc * nav
        short_dollars = short_alloc * nav

        p_open_iwm = open_df["IWM"].loc[exec_date]
        if pd.isna(p_open_iwm) or p_open_iwm <= 0:
            return None

        # Long IWM
        shares_iwm = int(long_dollars / p_open_iwm)
        if shares_iwm <= 0:
            return None

        # Short vehicle
        if short_vehicle == "QQQ":
            p_open_short = open_df["QQQ"].loc[exec_date]
        else:
            p_open_short = open_df["QID"].loc[exec_date]

        if pd.isna(p_open_short) or p_open_short <= 0:
            return None

        shares_short = int(short_dollars / p_open_short)
        if shares_short <= 0:
            return None

        # Transaction costs — IWM long
        s_iwm = sigma_iwm.loc[exec_date] if exec_date in sigma_iwm.index else 0.0
        a_iwm = adv_iwm.loc[exec_date] if exec_date in adv_iwm.index else 0.0
        if pd.isna(s_iwm): s_iwm = 0.0
        if pd.isna(a_iwm): a_iwm = 0.0

        if s_iwm > 0 and a_iwm > 0:
            tc_iwm, liq_iwm = compute_transaction_cost(p_open_iwm, shares_iwm, s_iwm, a_iwm)
        else:
            tc_iwm = compute_tc_simple(p_open_iwm, shares_iwm)
            liq_iwm = False

        # Transaction costs — short leg
        if short_vehicle == "QQQ":
            s_short = sigma_qqq.loc[exec_date] if exec_date in sigma_qqq.index else 0.0
            a_short = adv_qqq.loc[exec_date] if exec_date in adv_qqq.index else 0.0
        else:
            s_short = sigma_qid.loc[exec_date] if exec_date in sigma_qid.index else 0.0
            a_short = adv_qid.loc[exec_date] if exec_date in adv_qid.index else 0.0

        if pd.isna(s_short): s_short = 0.0
        if pd.isna(a_short): a_short = 0.0

        if s_short > 0 and a_short > 0:
            tc_short, liq_short = compute_transaction_cost(p_open_short, shares_short, s_short, a_short)
        else:
            tc_short = compute_tc_simple(p_open_short, shares_short)
            liq_short = False

        total_cost = tc_iwm + tc_short

        # Execute — clean cash accounting
        # Long IWM: pay cost + TC
        cash -= shares_iwm * p_open_iwm + tc_iwm
        pos_iwm = shares_iwm
        entry_price_iwm = p_open_iwm

        if short_vehicle == "QQQ":
            # Direct short: receive sale proceeds, pay transaction cost
            # Cash receives QQQ sale proceeds; we now owe QQQ shares back
            cash += shares_short * p_open_short - tc_short
            pos_qqq = -shares_short
            entry_price_short = p_open_short
        else:
            # Long QID: pay cost + TC
            cash -= shares_short * p_open_short + tc_short
            pos_qid = shares_short
            entry_price_short = p_open_short

        in_position = True
        peak_spread_value = get_nav(exec_date)

        return {
            "type": "ENTRY",
            "date": str(exec_date.date()),
            "signal_date": None,
            "iwm_shares": shares_iwm,
            "iwm_price": round(p_open_iwm, 4),
            "short_shares": shares_short,
            "short_vehicle": short_vehicle,
            "short_price": round(p_open_short, 4),
            "total_cost_dollars": round(total_cost, 4),
            "liquidity_constrained": liq_iwm or liq_short,
            "nav_at_entry": round(get_nav(exec_date), 2),
        }

    def execute_exit(exec_date, reason: str):
        """Execute full exit at open on exec_date."""
        nonlocal cash, pos_iwm, pos_qqq, pos_qid, in_position
        nonlocal entry_price_iwm, entry_price_short

        if not in_position:
            return None

        p_open_iwm = open_df["IWM"].loc[exec_date]
        if short_vehicle == "QQQ":
            p_open_short = open_df["QQQ"].loc[exec_date]
        else:
            p_open_short = open_df["QID"].loc[exec_date]

        if pd.isna(p_open_iwm): p_open_iwm = close_df["IWM"].loc[exec_date]
        if pd.isna(p_open_short):
            if short_vehicle == "QQQ":
                p_open_short = close_df["QQQ"].loc[exec_date]
            else:
                p_open_short = close_df["QID"].loc[exec_date]

        # TC for exit
        s_iwm = sigma_iwm.loc[exec_date] if exec_date in sigma_iwm.index else 0.0
        a_iwm = adv_iwm.loc[exec_date] if exec_date in adv_iwm.index else 0.0
        if pd.isna(s_iwm): s_iwm = 0.0
        if pd.isna(a_iwm): a_iwm = 0.0

        if s_iwm > 0 and a_iwm > 0:
            tc_iwm, _ = compute_transaction_cost(p_open_iwm, pos_iwm, s_iwm, a_iwm)
        else:
            tc_iwm = compute_tc_simple(p_open_iwm, pos_iwm)

        shares_short = abs(pos_qqq) if short_vehicle == "QQQ" else pos_qid

        if short_vehicle == "QQQ":
            s_short = sigma_qqq.loc[exec_date] if exec_date in sigma_qqq.index else 0.0
            a_short = adv_qqq.loc[exec_date] if exec_date in adv_qqq.index else 0.0
        else:
            s_short = sigma_qid.loc[exec_date] if exec_date in sigma_qid.index else 0.0
            a_short = adv_qid.loc[exec_date] if exec_date in adv_qid.index else 0.0

        if pd.isna(s_short): s_short = 0.0
        if pd.isna(a_short): a_short = 0.0

        if s_short > 0 and a_short > 0:
            tc_short, _ = compute_transaction_cost(p_open_short, shares_short, s_short, a_short)
        else:
            tc_short = compute_tc_simple(p_open_short, shares_short)

        total_cost = tc_iwm + tc_short

        # Compute P&L
        pnl_iwm = pos_iwm * (p_open_iwm - entry_price_iwm) - tc_iwm
        if short_vehicle == "QQQ":
            # Short QQQ P&L: profit when QQQ price drops
            pnl_short = abs(pos_qqq) * (entry_price_short - p_open_short) - tc_short
        else:
            # Long QID P&L
            pnl_short = pos_qid * (p_open_short - entry_price_short) - tc_short

        total_pnl = pnl_iwm + pnl_short

        # Unwind positions
        cash += pos_iwm * p_open_iwm - tc_iwm  # sell IWM
        if short_vehicle == "QQQ":
            cash -= abs(pos_qqq) * p_open_short + tc_short  # cover short
        else:
            cash += pos_qid * p_open_short - tc_short  # sell QID

        nav_at_exit = cash  # fully in cash now

        trade = {
            "type": "EXIT",
            "date": str(exec_date.date()),
            "reason": reason,
            "iwm_shares": pos_iwm,
            "iwm_entry_price": round(entry_price_iwm, 4),
            "iwm_exit_price": round(p_open_iwm, 4),
            "short_shares": shares_short,
            "short_vehicle": short_vehicle,
            "short_entry_price": round(entry_price_short, 4),
            "short_exit_price": round(p_open_short, 4),
            "pnl_iwm": round(pnl_iwm, 4),
            "pnl_short": round(pnl_short, 4),
            "total_pnl": round(total_pnl, 4),
            "total_cost_dollars": round(total_cost, 4),
            "nav_at_exit": round(nav_at_exit, 2),
        }

        pos_iwm = 0
        pos_qqq = 0
        pos_qid = 0
        in_position = False
        entry_price_iwm = 0.0
        entry_price_short = 0.0

        return trade

    def rebalance_legs(rebal_date):
        """Dollar-match the two legs (every rebal_weeks weeks)."""
        nonlocal cash, pos_iwm, pos_qqq, pos_qid, entry_price_iwm, entry_price_short
        if not in_position:
            return

        nav = get_nav(rebal_date)
        target_long = long_alloc * nav
        target_short = short_alloc * nav

        p_iwm = open_df["IWM"].loc[rebal_date]
        if short_vehicle == "QQQ":
            p_short = open_df["QQQ"].loc[rebal_date]
        else:
            p_short = open_df["QID"].loc[rebal_date]

        if pd.isna(p_iwm) or pd.isna(p_short):
            return

        new_shares_iwm = int(target_long / p_iwm)
        new_shares_short = int(target_short / p_short)

        delta_iwm = new_shares_iwm - pos_iwm
        delta_short_raw = new_shares_short
        if short_vehicle == "QQQ":
            delta_short = new_shares_short - abs(pos_qqq)
        else:
            delta_short = new_shares_short - pos_qid

        # Execute rebalancing trades (minimal: only if significant delta)
        if abs(delta_iwm) > 0:
            tc = compute_tc_simple(p_iwm, delta_iwm)
            cash -= delta_iwm * p_iwm + tc
            pos_iwm = new_shares_iwm
            entry_price_iwm = p_iwm  # update entry price to rebal price

        if abs(delta_short) > 0:
            tc = compute_tc_simple(p_short, delta_short)
            if short_vehicle == "QQQ":
                if delta_short > 0:  # increase short
                    cash += delta_short * p_short - tc
                    pos_qqq -= delta_short
                else:  # reduce short
                    cash -= abs(delta_short) * p_short + tc
                    pos_qqq -= delta_short
                entry_price_short = p_short
            else:
                cash -= delta_short * p_short + tc
                pos_qid = new_shares_short
                entry_price_short = p_short

    # ── Main Loop ───────────────────────────────────────────────────────────────
    # Correct execution timing:
    # 1. Start of each day: execute any pending trades at TODAY's open price
    # 2. Check stop-losses using TODAY's close
    # 3. Signal check on Fridays using TODAY's close signal
    # 4. Record equity at TODAY's close
    # This ensures equity recorded on day D reflects the position held AT day D's close.
    pending_entry = False   # True = signal ON set on prev day, enter today's open
    pending_exit = False    # True = exit trigger set on prev day, exit today's open
    pending_exit_reason = "SIGNAL_OFF"
    last_friday_signal = 0
    trade_open = None       # currently open trade record

    for i, date in enumerate(dates):
        is_friday = date in friday_dates

        # ── Step 1: Execute pending trades at TODAY's open ───────────────────────
        if pending_exit and in_position:
            reason = pending_exit_reason
            p_open_iwm_today = open_df["IWM"].loc[date] if date in open_df.index else np.nan
            if not pd.isna(p_open_iwm_today):
                t = execute_exit(date, reason)
                if t is not None:
                    if trade_open is not None:
                        trade_open.update(t)
                        trade_log.append(trade_open)
                    trade_open = None
            pending_exit = False
            spread_stop_triggered = False

        if pending_entry and not in_position:
            p_open_iwm_today = open_df["IWM"].loc[date] if date in open_df.index else np.nan
            if not pd.isna(p_open_iwm_today):
                t = execute_entry(date)
                if t is not None:
                    trade_open = t
            pending_entry = False

        # ── Step 2: Check stop-losses at TODAY's close ───────────────────────────
        if in_position:
            nav = get_nav(date)
            # Update peak NAV for spread MDD tracking
            if nav > peak_spread_value:
                peak_spread_value = nav

            # Spread MDD stop (only trigger if not already pending exit)
            if not pending_exit:
                spread_drawdown = (nav - peak_spread_value) / peak_spread_value
                if spread_drawdown <= -spread_mdd_stop:
                    spread_stop_triggered = True
                    pending_exit = True
                    pending_exit_reason = "SPREAD_MDD_STOP"

            # Per-position IWM stop
            if not pending_exit:
                c_iwm = close_df["IWM"].loc[date]
                if entry_price_iwm > 0 and not pd.isna(c_iwm):
                    if (c_iwm - entry_price_iwm) / entry_price_iwm <= -per_pos_stop:
                        pending_exit = True
                        pending_exit_reason = "IWM_STOP"

            # Per-position short leg stop
            if not pending_exit:
                if short_vehicle == "QQQ":
                    c_short = close_df["QQQ"].loc[date]
                    short_pnl_pct = (entry_price_short - c_short) / entry_price_short if (entry_price_short > 0 and not pd.isna(c_short)) else 0.0
                else:
                    c_short = close_df["QID"].loc[date]
                    short_pnl_pct = (c_short - entry_price_short) / entry_price_short if (entry_price_short > 0 and not pd.isna(c_short)) else 0.0
                if short_pnl_pct <= -per_pos_stop:
                    pending_exit = True
                    pending_exit_reason = "SHORT_LEG_STOP"

        # ── Step 3: Weekly signal check on Fridays ───────────────────────────────
        if is_friday:
            sig = signal.loc[date] if date in signal.index else last_friday_signal
            last_friday_signal = sig

            if sig == 1 and not in_position and not pending_entry:
                pending_entry = True
            elif sig == 0 and in_position and not pending_exit:
                pending_exit = True
                pending_exit_reason = "SIGNAL_OFF"

            # Dollar rebalancing every rebal_weeks weeks
            rebal_week_counter += 1
            if in_position and rebal_week_counter >= rebal_weeks:
                rebal_week_counter = 0
                rebalance_legs(date)

        # ── Step 4: Record equity at TODAY's close ───────────────────────────────
        if in_position:
            nav = get_nav(date)
        else:
            nav = cash
        equity_curve.append({"date": str(date.date()), "nav": round(nav, 2)})

    # Close any open position at end of data
    if in_position and len(dates) > 0:
        t = execute_exit(dates[-1], "END_OF_DATA")
        if t is not None:
            if trade_open is not None:
                trade_open.update(t)
                trade_log.append(trade_open)

    # ── Compute Metrics ─────────────────────────────────────────────────────────
    equity_df = pd.DataFrame(equity_curve).set_index("date")
    equity_df.index = pd.to_datetime(equity_df.index)
    nav_series = equity_df["nav"]

    daily_returns = nav_series.pct_change().dropna()

    if len(daily_returns) > 1:
        sharpe = (
            daily_returns.mean() / daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
            if daily_returns.std() > 0 else 0.0
        )
    else:
        sharpe = 0.0

    # Max drawdown
    roll_max = nav_series.cummax()
    drawdown = (nav_series - roll_max) / roll_max
    max_drawdown = float(drawdown.min())

    # Win rate and profit factor
    completed_trades = [t for t in trade_log if "total_pnl" in t]
    wins = [t for t in completed_trades if t["total_pnl"] > 0]
    losses = [t for t in completed_trades if t["total_pnl"] <= 0]
    win_rate = len(wins) / len(completed_trades) if completed_trades else 0.0
    gross_profit = sum(t["total_pnl"] for t in wins)
    gross_loss = abs(sum(t["total_pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0
    )

    total_return = (nav_series.iloc[-1] - init_cash) / init_cash if len(nav_series) > 0 else 0.0

    metrics = {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "total_return": round(total_return, 4),
        "trade_count": len(completed_trades),
        "final_nav": round(float(nav_series.iloc[-1]) if len(nav_series) > 0 else init_cash, 2),
        "init_cash": init_cash,
    }

    return {
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "metrics": metrics,
        "nav_series": nav_series,
        "daily_returns": daily_returns,
    }


# ── Walk-Forward Analysis ──────────────────────────────────────────────────────

def run_walk_forward(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    dgs2: pd.Series,
    params: dict,
    is_months: int = 36,
    oos_months: int = 6,
    n_windows: int = 4,
    wf_start: str = "2007-01-01",
) -> list:
    """
    Run N-window walk-forward backtest (non-overlapping 36m IS / 6m OOS).

    Each window:
    - IS: is_months months of training
    - OOS: oos_months months of out-of-sample validation
    - Windows are contiguous and non-overlapping

    Returns list of dicts with IS and OOS results per window.
    """
    results = []
    start_dt = pd.Timestamp(wf_start)

    for w in range(n_windows):
        is_start = start_dt + pd.DateOffset(months=w * (is_months + oos_months))
        is_end = is_start + pd.DateOffset(months=is_months) - pd.DateOffset(days=1)
        oos_start = is_end + pd.DateOffset(days=1)
        oos_end = oos_start + pd.DateOffset(months=oos_months) - pd.DateOffset(days=1)

        is_result = run_backtest(
            close_df, open_df, volume_df, dgs2, params,
            start=is_start.strftime("%Y-%m-%d"),
            end=is_end.strftime("%Y-%m-%d"),
        )
        oos_result = run_backtest(
            close_df, open_df, volume_df, dgs2, params,
            start=oos_start.strftime("%Y-%m-%d"),
            end=oos_end.strftime("%Y-%m-%d"),
        )

        results.append({
            "window": w + 1,
            "is_start": is_start.strftime("%Y-%m-%d"),
            "is_end": is_end.strftime("%Y-%m-%d"),
            "oos_start": oos_start.strftime("%Y-%m-%d"),
            "oos_end": oos_end.strftime("%Y-%m-%d"),
            "is": is_result.get("metrics", {}),
            "oos": oos_result.get("metrics", {}),
            "is_trades": is_result.get("trade_log", []),
            "oos_trades": oos_result.get("trade_log", []),
        })

    return results


# ── Monte Carlo and Statistical Tests ─────────────────────────────────────────

def monte_carlo_sharpe(
    daily_returns: pd.Series,
    n_simulations: int = 1000,
    seed: int = 42,
) -> dict:
    """
    Monte Carlo simulation: bootstrap daily returns to estimate Sharpe distribution.

    Method: resample with replacement (daily returns), compute annualized Sharpe
    for each simulation. Report p5, median, p95, and fraction > 0.
    """
    rng = np.random.default_rng(seed)
    n = len(daily_returns)
    if n < 2:
        return {"p5": 0.0, "median": 0.0, "p95": 0.0, "frac_positive": 0.0}

    ret_arr = daily_returns.values
    sharpes = []
    for _ in range(n_simulations):
        sample = rng.choice(ret_arr, size=n, replace=True)
        s = np.mean(sample) / np.std(sample) * np.sqrt(TRADING_DAYS_PER_YEAR) if np.std(sample) > 0 else 0.0
        sharpes.append(s)

    sharpes = np.array(sharpes)
    return {
        "p5": round(float(np.percentile(sharpes, 5)), 4),
        "median": round(float(np.median(sharpes)), 4),
        "p95": round(float(np.percentile(sharpes, 95)), 4),
        "frac_positive": round(float(np.mean(sharpes > 0)), 4),
        "n_simulations": n_simulations,
    }


def bootstrap_ci(
    daily_returns: pd.Series,
    n_bootstrap: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple:
    """
    Bootstrap 95% CI for Sharpe ratio.

    Returns (lower, upper) bounds.
    """
    rng = np.random.default_rng(seed)
    n = len(daily_returns)
    if n < 2:
        return (0.0, 0.0)

    ret_arr = daily_returns.values
    sharpes = []
    for _ in range(n_bootstrap):
        sample = rng.choice(ret_arr, size=n, replace=True)
        s = np.mean(sample) / np.std(sample) * np.sqrt(TRADING_DAYS_PER_YEAR) if np.std(sample) > 0 else 0.0
        sharpes.append(s)

    sharpes = np.array(sharpes)
    alpha = (1 - ci) / 2
    lower = float(np.percentile(sharpes, alpha * 100))
    upper = float(np.percentile(sharpes, (1 - alpha) * 100))
    return (round(lower, 4), round(upper, 4))


def permutation_test(
    daily_returns: pd.Series,
    observed_sharpe: float,
    n_permutations: int = 1000,
    seed: int = 42,
) -> float:
    """
    Permutation test: randomly shuffle daily returns and compute null Sharpe distribution.

    p-value = fraction of permuted Sharpes >= observed_sharpe.
    Low p-value (< 0.05) indicates the observed Sharpe is unlikely to arise by chance.
    """
    rng = np.random.default_rng(seed)
    n = len(daily_returns)
    if n < 2:
        return 1.0

    ret_arr = daily_returns.values
    null_sharpes = []
    for _ in range(n_permutations):
        shuffled = rng.permutation(ret_arr)
        s = np.mean(shuffled) / np.std(shuffled) * np.sqrt(TRADING_DAYS_PER_YEAR) if np.std(shuffled) > 0 else 0.0
        null_sharpes.append(s)

    null_sharpes = np.array(null_sharpes)
    p_value = float(np.mean(null_sharpes >= observed_sharpe))
    return round(p_value, 4)


def compute_regime_slice_sharpes(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    dgs2: pd.Series,
    params: dict,
) -> dict:
    """
    Compute IS Sharpe for each regime sub-window (per criteria.md v1.1).

    Note: H38 IS window is 2007-2021. The criteria.md regime windows (2018-2023)
    have partial overlap:
    - Pre-COVID (2018-2019): within IS → computable
    - Stimulus era (2020-2021): within IS → computable
    - Rate-shock (2022): OUTSIDE IS → N/A (will appear in OOS/WF OOS)
    - Normalization (2023): OUTSIDE IS → N/A

    Assessable regimes: 2 (Pre-COVID, Stimulus era).
    For 2/4 requirement with assessable regimes, need both to pass Sharpe ≥ 0.8.
    Rate-shock is specifically the OOS period where strategy is expected to excel.
    """
    regimes = {
        "pre_covid": ("2018-01-01", "2019-12-31"),
        "stimulus_era": ("2020-01-01", "2021-12-31"),
        "rate_shock": ("2022-01-01", "2022-12-31"),
        "normalization": ("2023-01-01", "2023-12-31"),
    }

    results = {}
    for name, (s, e) in regimes.items():
        # Check if within IS window
        if pd.Timestamp(e) > pd.Timestamp("2021-12-31"):
            results[name] = {"sharpe": None, "note": "Outside IS window (2007-2021) — N/A"}
            continue

        r = run_backtest(close_df, open_df, volume_df, dgs2, params, start=s, end=e)
        m = r.get("metrics", {})
        results[name] = {
            "sharpe": m.get("sharpe", None),
            "trade_count": m.get("trade_count", 0),
            "max_drawdown": m.get("max_drawdown", None),
        }

    return results


# ── Sensitivity Sweep ──────────────────────────────────────────────────────────

def run_sensitivity_sweep(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    dgs2: pd.Series,
    base_params: dict,
    is_start: str = "2007-01-01",
    is_end: str = "2021-12-31",
) -> list:
    """
    Sweep key parameters to test robustness (no cliff edges).

    Tested parameters per hypothesis spec:
    - rate_threshold_on: [0.05, 0.10, 0.15, 0.20, 0.25] (5bp–25bp)
    - rate_lookback_weeks: [2, 4, 6, 8]
    - hedge_ratio: [0.8, 1.0, 1.2]
    """
    sweep_results = []
    thresholds = [0.05, 0.10, 0.15, 0.20, 0.25]
    lookbacks = [2, 4, 6, 8]
    hedge_ratios = [0.8, 1.0, 1.2]

    for thresh in thresholds:
        for lookback in lookbacks:
            for hedge in hedge_ratios:
                p = base_params.copy()
                p["rate_threshold_on"] = thresh
                p["rate_lookback_weeks"] = lookback
                p["hedge_ratio"] = hedge

                r = run_backtest(
                    close_df, open_df, volume_df, dgs2, p,
                    start=is_start, end=is_end
                )
                m = r.get("metrics", {})
                sweep_results.append({
                    "rate_threshold_on": thresh,
                    "rate_lookback_weeks": lookback,
                    "hedge_ratio": hedge,
                    "is_sharpe": m.get("sharpe", 0.0),
                    "is_mdd": m.get("max_drawdown", 0.0),
                    "trade_count": m.get("trade_count", 0),
                    "total_return": m.get("total_return", 0.0),
                })

    return sweep_results


# ── Main Entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    IS_START = "2007-01-01"
    IS_END = "2021-12-31"

    print("H38 IWM/QQQ Rate-Cycle Factor Rotation — Gate 1 Backtest")
    print(f"IS window: {IS_START} to {IS_END}")
    print(f"Parameters: {PARAMETERS}")
    print()

    print("Downloading data...")
    close_df, open_df, volume_df = download_etf_data(IS_START, IS_END)
    dgs2 = download_dgs2(IS_START, IS_END)

    print("Running data quality checks...")
    dq = check_data_quality(close_df, IS_START, IS_END)
    for k, v in dq["tickers"].items():
        print(f"  {k}: {v}")

    print("\nRunning full IS backtest...")
    result = run_backtest(close_df, open_df, volume_df, dgs2, PARAMETERS, IS_START, IS_END)
    m = result["metrics"]
    print(f"  IS Sharpe: {m['sharpe']}")
    print(f"  IS Max Drawdown: {m['max_drawdown']:.2%}")
    print(f"  IS Win Rate: {m['win_rate']:.2%}")
    print(f"  IS Profit Factor: {m['profit_factor']}")
    print(f"  IS Total Return: {m['total_return']:.2%}")
    print(f"  IS Trade Count: {m['trade_count']}")
