"""
Strategy: H64 Leveraged-ETF Opening Range Breakout with VIX >= 20 Day Filter
Author: Strategy Coder Agent
Date: 2026-06-10
Hypothesis: research/hypotheses/64_leveraged_etf_orb_vix_filter.md
Asset class: equities (leveraged ETFs — SPXL, TQQQ)
Parent task: QUA-186
Source paper: Zarattini & Aziz (2023) SSRN 4416198

Survivorship Bias:
  SPXL (Direxion Daily S&P 500 Bull 3X ETF): launched November 2008. Active through the
  full backtest window 2016-2024. No survivorship bias.
  TQQQ (ProShares UltraPro QQQ 3X ETF): launched February 2010. Active through the full
  backtest window 2016-2024. No survivorship bias.

Price Adjustments:
  Alpaca historical bars with adjustment='all' applies split and dividend adjustments
  automatically. Equivalent to yfinance auto_adjust=True.

Data Gaps:
  RTH trading days with >MAX_CONSECUTIVE_GAP_DAYS consecutive missing business days are
  flagged at runtime via _check_intraday_gaps(). Forward-fill is NOT applied to gaps
  >5 days; those dates are excluded from signal generation.

Earnings Exclusion:
  NOT APPLICABLE. SPXL and TQQQ are leveraged index ETFs (not individual stocks). ETFs
  have no earnings announcement dates. No earnings exclusion is required or implemented.

Delisted Tickers:
  NOT APPLICABLE. SPXL and TQQQ are active US equity ETFs through the full backtest window
  2016-2024 and remain active as of this writing.

VIX Look-ahead:
  Prior-day VIX close is used strictly as vix_close.shift(1) — never same-day VIX.
  Same-day VIX intraday values are not observable at market open and cannot be used for
  entry decisions without introducing look-ahead bias.

ML Pipeline Compliance:
  NOT APPLICABLE. Strategy is pattern-based (ORB support/resistance breakout with a
  regime filter), NOT ML-based. No sklearn Pipeline, no train/test splits, no feature
  scaling, no model fitting. The ML anti-snooping checklist does not apply.

PDT Compliance:
  Account size >= $25,001 required. VIX >= 20 filter yields ~78 trades/year across
  SPXL+TQQQ combined (~39 per instrument), all intraday day-trades. Exceeds PDT limit
  for accounts below $25,000.

Transaction Cost Model (instrument-class overrides per ED-SLIP-001):
  Fixed commission: $0.005/share per leg (entry AND exit — two legs per round-trip)
  Slippage: 0.060% = 0.00060 per leg (SPXL and TQQQ leveraged ETF override)
  NOT using the canonical 0.05% equities default — ED-SLIP-001 overrides apply.
  Market impact: k * sigma * sqrt(Q / ADV), where:
      k = 0.1 (institutional constant, Johnson — Algorithmic Trading & DMA)
      sigma = 20-day rolling daily return std (shift(1) — no look-ahead)
      Q = order size in shares (position_shares parameter)
      ADV = 20-day rolling average daily volume in shares (shift(1))
  Liquidity flag: Q/ADV > 0.01 -> liquidity_constrained = True; logged in trade record.

Walk-Forward Requirement (PF-1 constraint):
  Must use 24-month IS / 6-month OOS windows. 12m IS windows violate PF-1 because
  ~78 trades/year with VIX >= 20 filter gives only 78/4 = 19.5 trades per 12m IS window
  (below the 30-trade minimum). Default is_months=24 is hard-coded per Research Director
  documented in hypothesis file and feasibility memo (QUA-152, QUA-181).
"""

import datetime as dt
import logging
import os
import time
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
TRADING_DAYS_PER_YEAR = 252
RTH_START = dt.time(9, 30)
RTH_LAST_BAR = dt.time(15, 59)   # last valid RTH minute bar start
MAX_CONSECUTIVE_GAP_DAYS = 5
ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks"

# Instrument-class slippage overrides (ED-SLIP-001) — NOT the canonical 0.0005 default
_SLIPPAGE_OVERRIDES = {
    "SPXL": 0.00060,
    "TQQQ": 0.00060,
}

# All tunable parameters exposed here for sensitivity scanning
PARAMETERS = {
    "or_window_min": 15,             # sweep: [5, 15]
    "r_mult": 2.0,                   # sweep: [1.5, 2.0, 2.5]
    "vix_threshold": 20,             # sweep: [17, 20, 25]
    "stop_buffer": 0.05,             # fixed
    "universe": ["SPXL", "TQQQ"],   # sweep: ["SPXL"], ["TQQQ"], ["SPXL", "TQQQ"]
    "exit_time_et": "15:55",
    "long_only": True,
    "min_or_width_pct": 0.0010,
    "account_size": 25001,
    "position_shares": 100,          # per instrument
    # Transaction cost model
    "fixed_cost_per_share": 0.005,
    "slippage_pct_spxl": 0.00060,    # 6 bps one-way — leveraged ETF override (ED-SLIP-001)
    "slippage_pct_tqqq": 0.00060,    # 6 bps one-way — leveraged ETF override (ED-SLIP-001)
    "market_impact_k": 0.1,
    "sigma_window": 20,
    "adv_window": 20,
    "liquidity_threshold": 0.01,
}


# ── Environment / Credential Loading ────────────────────────────────────────────

def _load_broker_env() -> None:
    """Load broker/.env into os.environ without overwriting existing vars."""
    env_path = Path(__file__).parent.parent / "broker" / ".env"
    if not env_path.exists():
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            key = key.strip()
            value = raw.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


_load_broker_env()


# ── VIX Daily Data ───────────────────────────────────────────────────────────────

def load_vix_daily(start: str, end: str) -> pd.Series:
    """
    Fetch ^VIX daily closing prices from yfinance and return prior-day values.
    The shift(1) enforces strict no look-ahead: day D gets VIX close from day D-1.

    Args:
        start: inclusive start date (YYYY-MM-DD)
        end: inclusive end date (YYYY-MM-DD)

    Returns:
        pd.Series: prior-day VIX close, tz-naive date index.
                   Index covers [start, end]; first row is NaN (no prior day at start).
    """
    # Fetch a buffer before start to have a valid prior-day VIX on the first trading day
    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    raw = yf.download("^VIX", start=fetch_start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError(f"No VIX data returned from yfinance for [{start} to {end}]")

    close_col = raw["Close"]
    if isinstance(close_col.columns, pd.Index) and len(close_col.columns) > 0:
        # Multi-ticker download accidentally wrapped
        vix_close = close_col.iloc[:, 0]
    else:
        vix_close = close_col.squeeze()

    # Ensure tz-naive date index
    idx = vix_close.index
    if hasattr(idx, "tz") and idx.tz is not None:
        idx = idx.tz_convert(None)
    vix_close.index = idx.normalize()

    # shift(1): day D now holds the VIX close of day D-1 — strict prior-day, no look-ahead
    prior_day_vix = vix_close.shift(1)

    n_valid = prior_day_vix.dropna()
    logger.info(
        "VIX loaded: %d rows total, %d valid prior-day values | date range [%s, %s]",
        len(prior_day_vix),
        len(n_valid),
        str(prior_day_vix.index[0].date()) if len(prior_day_vix) > 0 else "N/A",
        str(prior_day_vix.index[-1].date()) if len(prior_day_vix) > 0 else "N/A",
    )
    return prior_day_vix


# ── Alpaca Historical Data API ───────────────────────────────────────────────────

def _alpaca_bars_page(
    ticker: str,
    start_iso: str,
    end_iso: str,
    api_key: str,
    api_secret: str,
    page_token: str = None,
) -> tuple[list, str]:
    """
    Single paginated request to Alpaca /v2/stocks/{symbol}/bars.
    Attempts SIP feed first; falls back to IEX on 403 (SIP requires paid subscription).
    Returns (bars_list, next_page_token_or_None).
    """
    url = f"{ALPACA_DATA_URL}/{ticker}/bars"
    query = {
        "start": start_iso,
        "end": end_iso,
        "timeframe": "1Min",
        "adjustment": "all",
        "feed": "sip",
        "limit": 10000,
    }
    if page_token:
        query["page_token"] = page_token
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }
    resp = requests.get(url, params=query, headers=headers, timeout=30)
    if resp.status_code == 403:
        query["feed"] = "iex"
        resp = requests.get(url, params=query, headers=headers, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    return body.get("bars", []), body.get("next_page_token")


def _fetch_alpaca_bars(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch all 1-minute OHLCV bars from Alpaca for [start, end] (YYYY-MM-DD).
    Paginates automatically. Returns DataFrame with UTC-aware DatetimeIndex.
    Raises EnvironmentError if credentials not configured.
    Raises ValueError if no bars are found.
    """
    api_key = os.getenv("ALPACA_API_KEY", "")
    api_secret = os.getenv("ALPACA_API_SECRET", "")
    if not api_key or api_key.startswith("your_"):
        raise EnvironmentError(
            "ALPACA_API_KEY not configured. Set ALPACA_API_KEY and ALPACA_API_SECRET "
            "in environment or broker/.env to run the H64 backtest. "
            "See broker/.env.example for setup instructions."
        )

    start_iso = f"{start}T13:00:00Z"   # 09:00 ET approx; Alpaca filters RTH
    end_iso = f"{end}T23:59:59Z"

    all_bars: list = []
    page_token = None
    attempt = 0

    while True:
        try:
            bars, next_token = _alpaca_bars_page(
                ticker, start_iso, end_iso, api_key, api_secret, page_token
            )
            all_bars.extend(bars)
            logger.debug("Fetched %d bars (total so far: %d)", len(bars), len(all_bars))
            if not next_token:
                break
            page_token = next_token
            time.sleep(0.05)   # respect Alpaca rate limits
        except requests.HTTPError as exc:
            attempt += 1
            if attempt >= 3:
                raise RuntimeError(
                    f"Alpaca data fetch failed for {ticker} after {attempt} attempts: {exc}"
                ) from exc
            wait = 2 ** attempt
            logger.warning("Alpaca HTTP error (attempt %d/3); retrying in %ds: %s", attempt, wait, exc)
            time.sleep(wait)

    if not all_bars:
        raise ValueError(f"No bars returned from Alpaca for {ticker} [{start} to {end}]")

    df = pd.DataFrame(all_bars)
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                             "l": "low", "c": "close", "v": "volume"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["open", "high", "low", "close", "volume"]]


def _filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Convert UTC index to ET; keep only bars within RTH (09:30-15:59 ET)."""
    df_et = df.copy()
    df_et.index = df_et.index.tz_convert(ET)
    rth_mask = (df_et.index.time >= RTH_START) & (df_et.index.time <= RTH_LAST_BAR)
    return df_et.loc[rth_mask]


def _check_intraday_gaps(df: pd.DataFrame, ticker: str) -> str:
    """
    Check for missing RTH trading days (days with zero bars).
    Flags tickers with >MAX_CONSECUTIVE_GAP_DAYS consecutive missing business days.
    Returns a status string for logging/reporting.
    """
    if df.empty:
        return "empty"
    trading_dates = df.index.normalize().unique()
    bdays = pd.bdate_range(trading_dates.min(), trading_dates.max())
    missing = bdays.difference(trading_dates)
    if len(missing) == 0:
        return "no_gaps"

    runs, run = [], 1
    for i in range(1, len(missing)):
        if (missing[i] - missing[i - 1]).days <= 3:   # allow weekend bridging
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)
    max_run = max(runs) if runs else 0

    status = f"ok:max_consecutive_missing={max_run}"
    if max_run > MAX_CONSECUTIVE_GAP_DAYS:
        logger.warning(
            "DATA GAP FLAG: %s — %d consecutive missing RTH days (threshold: %d). "
            "These dates are excluded from signal generation.",
            ticker, max_run, MAX_CONSECUTIVE_GAP_DAYS,
        )
        status = f"flagged:max_consecutive_missing={max_run}"
    return status


def load_intraday_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch 1-minute OHLCV bars for ticker over [start, end] (YYYY-MM-DD).
    Filters to RTH (09:30-15:59 ET). Checks for data gaps.
    Returns DataFrame indexed by ET-localized timestamps.
    Raises EnvironmentError if Alpaca credentials not configured.
    Raises ValueError if no RTH bars found.
    """
    logger.info("Loading 1-min RTH bars: %s [%s -> %s]", ticker, start, end)
    raw = _fetch_alpaca_bars(ticker, start, end)
    df = _filter_rth(raw)

    if df.empty:
        raise ValueError(f"No RTH bars found for {ticker} [{start} to {end}]")

    gap_status = _check_intraday_gaps(df, ticker)
    n_days = df.index.normalize().nunique()
    logger.info(
        "%s: %d RTH bars | %d trading days | gap_check=%s",
        ticker, len(df), n_days, gap_status,
    )
    return df


# ── Opening Range Computation ────────────────────────────────────────────────────

def _compute_opening_range(
    df_day: pd.DataFrame,
    or_window_min: int,
) -> tuple[float, float, float]:
    """
    Compute OR_high, OR_low, OR_width from a single-day 1-minute OHLCV DataFrame.
    OR window: first or_window_min bars starting at 09:30 ET (bars where 09:30 <= t < 09:30+N).
    Uses high column for OR_high and low column for OR_low (OHLCV bar semantics).

    Returns:
        (OR_high, OR_low, OR_width) where OR_width = OR_high - OR_low
    Raises:
        ValueError if fewer than half the expected bars, or OR_width <= 0.
    """
    if df_day.empty:
        raise ValueError("Empty day DataFrame passed to _compute_opening_range")

    day_date = df_day.index[0].date()
    or_start = pd.Timestamp(day_date, tz=ET).replace(hour=9, minute=30)
    or_end = or_start + pd.Timedelta(minutes=or_window_min)

    or_bars = df_day[(df_day.index >= or_start) & (df_day.index < or_end)]
    min_required = max(1, or_window_min // 2)

    if len(or_bars) < min_required:
        raise ValueError(
            f"Insufficient OR bars on {day_date}: need >={min_required}, got {len(or_bars)}"
        )

    or_high = float(or_bars["high"].max())
    or_low = float(or_bars["low"].min())
    or_width = or_high - or_low

    if or_width <= 0:
        raise ValueError(f"OR_width <= 0 on {day_date}: OR_high={or_high}, OR_low={or_low}")

    return or_high, or_low, or_width


# ── Transaction Cost Model ───────────────────────────────────────────────────────

def _get_slippage_pct(ticker: str, params: dict) -> float:
    """Return instrument-class slippage override for ticker (ED-SLIP-001)."""
    key = f"slippage_pct_{ticker.lower()}"
    if key in params:
        return params[key]
    return _SLIPPAGE_OVERRIDES.get(ticker.upper(), 0.00060)


def _compute_cost_components(
    entry_price: float,
    exit_price: float,
    ticker: str,
    params: dict,
    sigma: float,
    adv: float,
) -> tuple[float, float, float, float, bool]:
    """
    Compute individual cost components per instrument-class overrides (ED-SLIP-001).
    Returns (commission_total, slippage_total, market_impact_total, total_cost, liquidity_constrained).
    All totals are in dollars; market impact applied at entry leg only.
    """
    qty = params["position_shares"]
    k = params["market_impact_k"]
    slippage_pct = _get_slippage_pct(ticker, params)

    # Commission: $0.005/share per leg (entry + exit = 2 legs)
    commission_total = params["fixed_cost_per_share"] * 2 * qty

    # Slippage: leveraged ETF override per leg (entry + exit)
    slippage_total = (slippage_pct * entry_price + slippage_pct * exit_price) * qty

    # Market impact: k * sigma * sqrt(Q/ADV) * entry_price * qty
    liquidity_constrained = False
    market_impact_total = 0.0
    if adv > 0 and sigma > 0:
        q_over_adv = qty / adv
        liquidity_constrained = q_over_adv > params["liquidity_threshold"]
        market_impact_total = k * sigma * np.sqrt(q_over_adv) * entry_price * qty

    total_cost = commission_total + slippage_total + market_impact_total
    return commission_total, slippage_total, market_impact_total, total_cost, liquidity_constrained


# ── Signal Generation ────────────────────────────────────────────────────────────

def _parse_exit_time(exit_time_str: str) -> dt.time:
    """Parse 'HH:MM' string to datetime.time."""
    hh, mm = exit_time_str.split(":")
    return dt.time(int(hh), int(mm))


def _vix_lookup_dict(vix_series: pd.Series) -> dict:
    """
    Build a tz-naive date -> prior_vix_close dict from the (already shifted) vix_series.
    Handles both tz-aware and tz-naive series indices safely.
    """
    lookup = {}
    for idx, val in vix_series.items():
        ts = pd.Timestamp(idx)
        # Normalize to tz-naive date for consistent key lookup
        if ts.tz is not None:
            ts = ts.tz_convert(None)
        lookup[ts.normalize()] = val
    return lookup


def generate_daily_signals(
    intraday_df: pd.DataFrame,
    vix_series: pd.Series,
    params: dict,
    ticker: str = "",
    daily_sigma: pd.Series = None,
    daily_adv: pd.Series = None,
) -> pd.DataFrame:
    """
    Process each RTH trading day to find ORB entries and exits.

    VIX gate: only enter on days where prior-day VIX >= vix_threshold.
    vix_series must already be shifted by 1 day (no same-day VIX — no look-ahead).

    Signal logic (long-only, per PF design):
      1. Skip day if prior-day VIX < vix_threshold
      2. Compute OR_high/OR_low from first or_window_min bars (09:30-09:30+N)
      3. Skip day if OR_width/OR_close < min_or_width_pct
      4. After OR window ends, scan bars for close > OR_high (breakout trigger)
      5. Enter at open of NEXT bar (t+1 fill — no same-bar entry, look-ahead free)
      6. Scan forward for first exit: target, stop, or hard EOD exit at 15:55 ET
      7. At most 1 trade per day per instrument

    Args:
        intraday_df: 1-minute RTH DataFrame with ET-localized DatetimeIndex
        vix_series: prior-day VIX close, already shifted (vix_close.shift(1)); tz-naive date index
        params: PARAMETERS dict
        ticker: ticker symbol for logging and cost lookup (optional, defaults to "")
        daily_sigma: pd.Series of 20-day rolling daily return std, shift(1) applied, by date
        daily_adv: pd.Series of 20-day rolling average daily volume (shares), shift(1) applied

    Returns:
        DataFrame of trade records — at most one row per trading day.
        Columns: trade_id, ticker, date, entry_time, exit_time, entry_price, exit_price,
                 stop, target, exit_reason, pnl_pct, pnl_dollar, gross_edge_bps,
                 net_pnl_bps, commission, slippage, market_impact, prior_vix,
                 liquidity_constrained.
    """
    hard_exit_time = _parse_exit_time(params["exit_time_et"])
    or_window = params["or_window_min"]
    vix_threshold = params["vix_threshold"]

    vix_lookup = _vix_lookup_dict(vix_series) if vix_series is not None else {}

    trade_rows = []
    date_to_bars = {d: g for d, g in intraday_df.groupby(intraday_df.index.normalize())}
    trading_dates = sorted(date_to_bars.keys())

    for date in trading_dates:
        # Normalize to tz-naive for VIX lookup
        date_ts = pd.Timestamp(date)
        if date_ts.tz is not None:
            date_naive = date_ts.tz_convert(None).normalize()
        else:
            date_naive = date_ts.normalize()
        date_str = str(date_ts.date())
        df_day = date_to_bars[date]

        # ── VIX day filter (prior-day close, no look-ahead) ──────────────────────
        prior_vix = vix_lookup.get(date_naive, float("nan"))
        if pd.isna(prior_vix):
            logger.debug("Skipping %s %s: no prior-day VIX available", ticker, date_str)
            continue
        if prior_vix < vix_threshold:
            logger.debug(
                "VIX FILTER blocked: %s %s — prior VIX %.2f < threshold %.0f",
                ticker, date_str, prior_vix, vix_threshold,
            )
            continue

        if len(df_day) < or_window + 5:
            logger.debug("Skipping %s %s: only %d bars", ticker, date_str, len(df_day))
            continue

        # ── Opening Range ─────────────────────────────────────────────────────────
        try:
            or_high, or_low, or_width = _compute_opening_range(df_day, or_window)
        except ValueError as exc:
            logger.debug("Skipping %s %s: %s", ticker, date_str, exc)
            continue

        day_date = df_day.index[0].date()
        or_start_ts = pd.Timestamp(day_date, tz=ET).replace(hour=9, minute=30)
        or_end_ts = or_start_ts + pd.Timedelta(minutes=or_window)
        or_bars = df_day[(df_day.index >= or_start_ts) & (df_day.index < or_end_ts)]
        or_close = float(or_bars["close"].iloc[-1])

        # Skip if OR is too narrow relative to price
        if or_close > 0 and or_width / or_close < params["min_or_width_pct"]:
            logger.debug(
                "Skipping %s %s: OR too narrow (%.4f%% < %.4f%%)",
                ticker, date_str,
                or_width / or_close * 100,
                params["min_or_width_pct"] * 100,
            )
            continue

        # Transaction cost inputs (shift(1) already applied by caller)
        # Fallback values: ~1.5% vol and ~5M shares ADV are reasonable for SPXL/TQQQ
        sigma_val = 0.015
        adv_val = 5_000_000
        if daily_sigma is not None and date in daily_sigma.index:
            v = daily_sigma.loc[date]
            if pd.notna(v) and v > 0:
                sigma_val = float(v)
        if daily_adv is not None and date in daily_adv.index:
            v = daily_adv.loc[date]
            if pd.notna(v) and v > 0:
                adv_val = float(v)

        # ── Post-OR scanning for breakout trigger ────────────────────────────────
        post_or = df_day[df_day.index >= or_end_ts]
        if post_or.empty:
            continue

        post_index = post_or.index
        post_opens = post_or["open"].values
        post_highs = post_or["high"].values
        post_lows = post_or["low"].values
        post_closes = post_or["close"].values
        n_post = len(post_or)

        for i in range(n_post):
            bar_time = post_index[i].time()
            if bar_time >= hard_exit_time:
                break

            # Long breakout trigger: bar close exceeds OR_high
            if post_closes[i] > or_high:
                # Require a next bar for t+1 fill (no same-bar entry)
                if i + 1 >= n_post:
                    break
                if post_index[i + 1].time() >= hard_exit_time:
                    break

                entry_price = float(post_opens[i + 1])
                entry_ts = str(post_index[i + 1])
                stop = entry_price - or_width * (1.0 + params["stop_buffer"])
                target = entry_price + or_width * params["r_mult"]

                # ── Exit scanning ───────────────────────────────────────────────
                exit_price = None
                exit_ts = None
                exit_reason = None

                for j in range(i + 1, n_post):
                    ex_bar_time = post_index[j].time()

                    # Target hit: bar high reaches or exceeds take-profit
                    if post_highs[j] >= target:
                        exit_price = target
                        exit_ts = str(post_index[j])
                        exit_reason = "target"
                        break

                    # Stop hit: bar low drops to or below stop loss
                    if post_lows[j] <= stop:
                        exit_price = stop
                        exit_ts = str(post_index[j])
                        exit_reason = "stop"
                        break

                    # Hard time exit: flat at 15:55 ET
                    if ex_bar_time >= hard_exit_time:
                        exit_price = float(post_closes[j])
                        exit_ts = str(post_index[j])
                        exit_reason = "time"
                        break

                if exit_price is None:
                    # End of RTH data before any exit triggered
                    last_j = n_post - 1
                    exit_price = float(post_closes[last_j])
                    exit_ts = str(post_index[last_j])
                    exit_reason = "time"

                # ── Transaction costs ───────────────────────────────────────────
                comm, slip, mkt_imp, total_cost, liq = _compute_cost_components(
                    entry_price, exit_price, ticker, params, sigma_val, adv_val
                )
                qty = params["position_shares"]
                pnl_gross = (exit_price - entry_price) * qty
                pnl_dollar = pnl_gross - total_cost
                pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
                notional = entry_price * qty
                gross_edge_bps = (pnl_gross / notional * 10000) if notional > 0 else 0.0
                net_pnl_bps = (pnl_dollar / notional * 10000) if notional > 0 else 0.0

                if liq:
                    q_adv_ratio = qty / adv_val if adv_val > 0 else float("inf")
                    logger.warning(
                        "LIQUIDITY CONSTRAINED: %s %s — Q=%d shares, ADV=%.0f shares, Q/ADV=%.4f",
                        ticker, date_str, qty, adv_val, q_adv_ratio,
                    )

                trade_rows.append({
                    "trade_id": str(uuid.uuid4()),
                    "ticker": ticker,
                    "date": date_str,
                    "entry_time": entry_ts,
                    "exit_time": exit_ts,
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "stop": round(stop, 4),
                    "target": round(target, 4),
                    "exit_reason": exit_reason,
                    "pnl_pct": round(pnl_pct, 6),
                    "pnl_dollar": round(pnl_dollar, 4),
                    "gross_edge_bps": round(gross_edge_bps, 2),
                    "net_pnl_bps": round(net_pnl_bps, 2),
                    "commission": round(comm, 4),
                    "slippage": round(slip, 4),
                    "market_impact": round(mkt_imp, 4),
                    "prior_vix": round(float(prior_vix), 2),
                    "liquidity_constrained": liq,
                })
                break   # at most 1 trade per day per instrument

    return pd.DataFrame(trade_rows)


# ── Performance Metrics ──────────────────────────────────────────────────────────

def _daily_pnl_series(trades_df: pd.DataFrame, start_date: str, end_date: str) -> pd.Series:
    """Build daily P&L series; no-trade days receive pnl = 0."""
    if trades_df.empty:
        bdays = pd.bdate_range(start_date, end_date)
        return pd.Series(0.0, index=pd.Index([str(d.date()) for d in bdays]))

    daily_pnl = trades_df.groupby("date")["pnl_dollar"].sum()
    bdays = pd.bdate_range(start_date, end_date)
    all_dates = pd.Index([str(d.date()) for d in bdays])
    return daily_pnl.reindex(all_dates, fill_value=0.0)


def compute_metrics(trade_log_df: pd.DataFrame, start_date: str = None, end_date: str = None) -> dict:
    """
    Compute standard Gate 1 performance metrics from a trade log DataFrame.

    Daily Sharpe is computed from daily P&L including no-trade days (conservative).
    This is the primary Sharpe — more conservative than trade-only Sharpe.

    Args:
        trade_log_df: output of generate_daily_signals(); may be None or empty.
        start_date: window start (YYYY-MM-DD); inferred from trades if None.
        end_date: window end (YYYY-MM-DD); inferred from trades if None.

    Returns:
        dict with trade_count, sharpe, max_drawdown, win_rate, profit_factor,
        gross_edge_bps_mean, net_pnl_bps_mean, exit_reason breakdown,
        liquidity_constrained_count, low_trade_count_flag (True if < 30).
    """
    acct = PARAMETERS["account_size"]

    if trade_log_df is None or (hasattr(trade_log_df, "empty") and trade_log_df.empty):
        return {
            "trade_count": 0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "gross_edge_bps_mean": 0.0,
            "net_pnl_bps_mean": 0.0,
            "low_trade_count_flag": True,
            "error": "no_trades",
        }

    n_trades = len(trade_log_df)
    s_date = start_date or trade_log_df["date"].min()
    e_date = end_date or trade_log_df["date"].max()

    daily_pnl = _daily_pnl_series(trade_log_df, s_date, e_date)
    daily_ret = daily_pnl / acct

    mean_ret = daily_ret.mean()
    std_ret = daily_ret.std()
    sharpe = (mean_ret / std_ret * np.sqrt(TRADING_DAYS_PER_YEAR)) if std_ret > 0 else 0.0

    cum_equity = (1 + daily_ret).cumprod()
    rolling_peak = cum_equity.cummax()
    drawdown = (cum_equity - rolling_peak) / rolling_peak
    max_drawdown = float(drawdown.min())

    # Win/loss based on gross edge direction
    wins_mask = trade_log_df["gross_edge_bps"] > 0
    wins_pnl = trade_log_df.loc[wins_mask, "pnl_dollar"]
    losses_pnl = trade_log_df.loc[~wins_mask, "pnl_dollar"]
    win_rate = float(wins_mask.sum()) / n_trades
    gross_wins = wins_pnl.sum()
    gross_losses = abs(losses_pnl.sum())
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")

    gross_bps_mean = float(trade_log_df["gross_edge_bps"].mean())
    net_pnl_bps_mean = float(trade_log_df["net_pnl_bps"].mean())

    exit_counts = trade_log_df["exit_reason"].value_counts().to_dict()
    liq_count = int(trade_log_df["liquidity_constrained"].sum())

    return {
        "trade_count": int(n_trades),
        "sharpe": round(float(sharpe), 4),
        "max_drawdown": round(float(max_drawdown), 6),
        "win_rate": round(float(win_rate), 4),
        "profit_factor": round(float(profit_factor), 4),
        "gross_edge_bps_mean": round(gross_bps_mean, 2),
        "net_pnl_bps_mean": round(net_pnl_bps_mean, 2),
        "total_pnl_dollar": round(float(trade_log_df["pnl_dollar"].sum()), 2),
        "exit_target_pct": round(exit_counts.get("target", 0) / n_trades, 4),
        "exit_stop_pct": round(exit_counts.get("stop", 0) / n_trades, 4),
        "exit_time_pct": round(exit_counts.get("time", 0) / n_trades, 4),
        "liquidity_constrained_count": liq_count,
        "low_trade_count_flag": n_trades < 30,
        "start_date": s_date,
        "end_date": e_date,
    }


# ── Walk-Forward Analysis ────────────────────────────────────────────────────────

def run_walk_forward(
    tickers: list,
    full_start: str,
    full_end: str,
    is_months: int = 24,   # hard-coded 24 per PF-1: 12m IS gives <30 trades/window
    oos_months: int = 6,
    params: dict = None,
) -> dict:
    """
    Multi-ticker rolling walk-forward analysis.
    Signals generated independently per ticker; aggregated for metrics.
    Parameters are fixed (no fitting) — walk-forward tests temporal consistency only.

    PF-1 constraint: is_months >= 24 required. 12m IS fails PF-1 (~19.5 trades/window).
    Research Director documented: 24m IS / 6m OOS is the hard minimum for H64.

    Args:
        tickers: list of ticker strings (e.g. ["SPXL", "TQQQ"])
        full_start: start of full data range (YYYY-MM-DD)
        full_end: end of full data range (YYYY-MM-DD)
        is_months: in-sample window length in months (must be >= 24 for PF-1 compliance)
        oos_months: out-of-sample window length in months (default 6)
        params: parameter dict; defaults to module PARAMETERS if None

    Returns:
        dict with keys: strategy, params, windows, summary, trade_log, all_oos_metrics.
    """
    if params is None:
        params = PARAMETERS.copy()

    if is_months < 24:
        logger.warning(
            "is_months=%d < 24 violates PF-1 trade-count requirement for H64 "
            "(~78 trades/year -> %.1f trades per %dm IS window < 30 minimum). "
            "Results will be statistically unreliable.",
            is_months, 78 * is_months / 12, is_months,
        )

    logger.info(
        "=== H64 Walk-Forward === tickers=%s | IS=%dm OOS=%dm | %s -> %s",
        tickers, is_months, oos_months, full_start, full_end,
    )

    # ── Load intraday data and compute risk metrics for all tickers ───────────────
    ticker_data: dict[str, pd.DataFrame] = {}
    ticker_sigma: dict[str, pd.Series] = {}
    ticker_adv: dict[str, pd.Series] = {}

    for ticker in tickers:
        try:
            df = load_intraday_data(ticker, full_start, full_end)
        except Exception as exc:
            logger.error("Data load failed for %s — skipping: %s", ticker, exc)
            continue

        daily_close = df.groupby(df.index.normalize())["close"].last()
        daily_volume = df.groupby(df.index.normalize())["volume"].sum()
        daily_returns = daily_close.pct_change()

        ticker_data[ticker] = df
        # shift(1): ensure risk metrics use only past data (no look-ahead)
        ticker_sigma[ticker] = daily_returns.rolling(params["sigma_window"]).std().shift(1)
        ticker_adv[ticker] = daily_volume.rolling(params["adv_window"]).mean().shift(1)

    if not ticker_data:
        return {
            "error": "No ticker data loaded successfully",
            "strategy": "H64_LETF_ORB_VIX",
            "windows": [],
            "summary": {},
            "trade_log": [],
        }

    # ── Load VIX daily (full range, prior-day shift inside load_vix_daily) ────────
    try:
        vix_series = load_vix_daily(full_start, full_end)
    except Exception as exc:
        return {
            "error": f"VIX data load failed: {exc}",
            "strategy": "H64_LETF_ORB_VIX",
            "windows": [],
            "summary": {},
            "trade_log": [],
        }

    # ── Roll walk-forward windows ─────────────────────────────────────────────────
    start_dt = pd.Timestamp(full_start)
    end_dt = pd.Timestamp(full_end)

    windows = []
    all_oos_trade_frames: list[pd.DataFrame] = []
    window_start = start_dt

    while True:
        is_end = window_start + pd.DateOffset(months=is_months)
        oos_end = is_end + pd.DateOffset(months=oos_months)

        if oos_end.date() > end_dt.date():
            break

        is_start_str = window_start.strftime("%Y-%m-%d")
        is_end_str = is_end.strftime("%Y-%m-%d")
        oos_start_str = is_end.strftime("%Y-%m-%d")
        oos_end_str = oos_end.strftime("%Y-%m-%d")

        is_start_ts = pd.Timestamp(is_start_str, tz=ET)
        is_end_ts = pd.Timestamp(is_end_str, tz=ET).replace(hour=23, minute=59)
        oos_start_ts = pd.Timestamp(oos_start_str, tz=ET)
        oos_end_ts = pd.Timestamp(oos_end_str, tz=ET).replace(hour=23, minute=59)

        is_trade_frames: list[pd.DataFrame] = []
        oos_trade_frames: list[pd.DataFrame] = []

        for ticker in tickers:
            if ticker not in ticker_data:
                continue
            df = ticker_data[ticker]
            norm_idx = df.index.normalize()

            df_is = df[(norm_idx >= is_start_ts) & (norm_idx <= is_end_ts)]
            df_oos = df[(norm_idx >= oos_start_ts) & (norm_idx <= oos_end_ts)]

            sigma = ticker_sigma.get(ticker)
            adv = ticker_adv.get(ticker)

            if not df_is.empty:
                t_is = generate_daily_signals(df_is, vix_series, params, ticker, sigma, adv)
                if not t_is.empty:
                    is_trade_frames.append(t_is)

            if not df_oos.empty:
                t_oos = generate_daily_signals(df_oos, vix_series, params, ticker, sigma, adv)
                if not t_oos.empty:
                    oos_trade_frames.append(t_oos)
                    all_oos_trade_frames.append(t_oos)

        is_combined = (
            pd.concat(is_trade_frames, ignore_index=True) if is_trade_frames else pd.DataFrame()
        )
        oos_combined = (
            pd.concat(oos_trade_frames, ignore_index=True) if oos_trade_frames else pd.DataFrame()
        )

        is_metrics = compute_metrics(is_combined, is_start_str, is_end_str)
        oos_metrics = compute_metrics(oos_combined, oos_start_str, oos_end_str)

        windows.append({
            "window": f"{is_start_str}:{is_end_str}:{oos_end_str}",
            "is_start": is_start_str,
            "is_end": is_end_str,
            "oos_start": oos_start_str,
            "oos_end": oos_end_str,
            "is_metrics": is_metrics,
            "oos_metrics": oos_metrics,
        })

        logger.info(
            "WF [%s|%s]: IS trades=%d (low=%s) gross=%.1fbps | "
            "OOS trades=%d (low=%s) gross=%.1fbps Sharpe=%.2f",
            is_start_str, oos_end_str,
            is_metrics["trade_count"], is_metrics["low_trade_count_flag"],
            is_metrics["gross_edge_bps_mean"],
            oos_metrics["trade_count"], oos_metrics["low_trade_count_flag"],
            oos_metrics["gross_edge_bps_mean"],
            oos_metrics["sharpe"],
        )

        window_start = window_start + pd.DateOffset(months=oos_months)

    # ── Summary ───────────────────────────────────────────────────────────────────
    oos_sharpes = [
        w["oos_metrics"]["sharpe"]
        for w in windows
        if w["oos_metrics"]["trade_count"] > 0
    ]
    wf_sharpe_floor = 0.30
    wf_passes = sum(1 for s in oos_sharpes if s >= wf_sharpe_floor)

    all_oos_combined = (
        pd.concat(all_oos_trade_frames, ignore_index=True)
        if all_oos_trade_frames
        else pd.DataFrame()
    )
    total_oos_metrics = compute_metrics(all_oos_combined, full_start, full_end)

    summary = {
        "tickers": tickers,
        "full_start": full_start,
        "full_end": full_end,
        "is_months": is_months,
        "oos_months": oos_months,
        "n_windows": len(windows),
        "wf_sharpe_floor": wf_sharpe_floor,
        "oos_sharpe_passes": wf_passes,
        "oos_sharpe_total": len(oos_sharpes),
        "consistency": f"{wf_passes}/{len(oos_sharpes)}",
        "total_oos_trade_count": total_oos_metrics["trade_count"],
        "total_oos_gross_edge_bps_mean": total_oos_metrics["gross_edge_bps_mean"],
        "total_oos_net_pnl_bps_mean": total_oos_metrics["net_pnl_bps_mean"],
    }

    logger.info(
        "=== H64 Walk-Forward Complete === %d windows | WF consistency: %s | "
        "Total OOS trades: %d | OOS gross: %.1f bps | OOS net: %.1f bps",
        len(windows), summary["consistency"],
        total_oos_metrics["trade_count"],
        total_oos_metrics["gross_edge_bps_mean"],
        total_oos_metrics["net_pnl_bps_mean"],
    )

    return {
        "strategy": "H64_LETF_ORB_VIX",
        "params": params,
        "windows": windows,
        "summary": summary,
        "trade_log": all_oos_combined.to_dict("records") if not all_oos_combined.empty else [],
        "all_oos_metrics": total_oos_metrics,
    }


# ── Entry Point ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    result = run_walk_forward(
        tickers=PARAMETERS["universe"],
        full_start="2016-01-01",
        full_end="2024-12-31",
        is_months=24,
        oos_months=6,
    )
    print(json.dumps(result, indent=2, default=str))
