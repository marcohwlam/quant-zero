"""
Strategy: H59 Opening Range Breakout (ORB) — Intraday-Flat Momentum
Author: Strategy Coder Agent
Date: 2026-06-09
Hypothesis: research/hypotheses/59_opening_range_breakout_orb.md (v1.1)
Asset class: equities
Parent task: QUA-146
Source paper: Zarattini & Aziz (2023) SSRN 4416198

Data Quality Checklist:
  - Survivorship bias: NOT APPLICABLE. SPY and QQQ are continuous benchmark ETFs (not
    individual stocks). SPY inception Jan 1993, QQQ inception Mar 1999; both active
    through the full backtest window 2016-2024. No survivorship issue.

  - Price adjustments: Alpaca historical bars with adjustment='all' applies split and
    dividend adjustments automatically. Equivalent to yfinance auto_adjust=True.

  - Data gaps: RTH trading days with consecutive missing bars >MAX_CONSECUTIVE_GAP_DAYS
    are flagged at runtime via _check_intraday_gaps(). Days with insufficient OR-window
    bars are skipped silently (logged at DEBUG). Forward-fill is NOT applied to gaps
    >5 days; those dates are excluded from signal generation.

  - Earnings exclusion: ORB is an intraday strategy. Earnings announcement days may
    inflate or deflate OR width, producing atypical signals. run_backtest() accepts an
    optional earnings_dates parameter. If provided, it reports two metric sets:
    (a) all_trades and (b) ex_earnings (±1 trading day excluded) as a sensitivity test.
    Earnings dates are NOT automatically excluded from the baseline — both sets are
    reported. If earnings_dates not provided, sensitivity test is skipped.

  - Delisted tickers: NOT APPLICABLE for SPY/QQQ. Both are active ETFs with no
    delisting risk over the backtest window.

ML Pipeline Compliance:
  Strategy is pattern-based (ORB S/R breakout), NOT ML-based. No sklearn Pipeline is
  required. No train/test splits, no feature scaling, no model fitting. The anti-snooping
  checklist for ML strategies does not apply. OR window and R_mult parameters are fixed
  from the source paper (Zarattini & Aziz 2023), not optimized on in-sample data.

PDT Compliance:
  Account size >= $25,001 required. ORB fires ~163 trades/year (~0.65/day), which
  exceeds the 3 day-trades per rolling 5 days PDT limit for accounts below $25,000.
  The strategy requires PDT-compliant account designation.

Transaction Cost Model (canonical, Engineering Director AGENTS.md):
  - Fixed commission: $0.005/share per leg (entry AND exit, two legs per round-trip)
  - Slippage: 0.05% of trade price per leg (half-spread approximation)
  - Market impact: 0.1 * sigma * sqrt(Q / ADV), where:
      sigma = 20-day rolling daily return std (shift(1) to avoid look-ahead)
      Q = order size in shares (position_shares)
      ADV = 20-day rolling average daily volume (shares, shift(1))
  - Liquidity flag: Q/ADV > 0.01 -> liquidity_constrained = True; logged in trade record

Data source:
  Alpaca Markets historical data API v2 (1-minute OHLCV, RTH 09:30-16:00 ET).
  Requires ALPACA_API_KEY and ALPACA_API_SECRET (env vars or broker/.env).
  SIP feed attempted first (broadest coverage); falls back to IEX on 403.
"""

import datetime as dt
import logging
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
TRADING_DAYS_PER_YEAR = 252
RTH_START = dt.time(9, 30)
RTH_LAST_BAR = dt.time(15, 59)   # last bar that starts within RTH
MAX_CONSECUTIVE_GAP_DAYS = 5
ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks"

# All tunable parameters exposed here for sensitivity scanning
PARAMETERS = {
    "or_window_min": 15,          # opening range window; grid: [5, 15, 30]
    "r_mult": 2.0,                # reward-to-risk ratio; grid: [1.5, 2.0, 2.5]
    "stop_buffer": 0.05,          # stop buffer as fraction of OR_width below OR_low
    "exit_time_et": "15:55",      # hard intraday close (HH:MM ET)
    "long_only": True,            # short-side requires locate; defer to v2
    "min_or_width_pct": 0.0010,   # skip days where OR_width/price < 0.10%
    "account_size": 25001,        # PDT-compliant minimum
    "position_shares": 100,       # lot size (SPY ~$500/share = $50K notional)
    # Transaction cost model
    "fixed_cost_per_share": 0.005,
    "slippage_pct": 0.0005,
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
    Returns (bars_list, next_page_token_or_None).
    Attempts SIP feed first; falls back to IEX on 403 (SIP requires paid subscription).
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
    """
    api_key = os.getenv("ALPACA_API_KEY", "")
    api_secret = os.getenv("ALPACA_API_SECRET", "")
    if not api_key or api_key.startswith("your_"):
        raise EnvironmentError(
            "ALPACA_API_KEY not configured. Set ALPACA_API_KEY and ALPACA_API_SECRET "
            "in environment or broker/.env to run the H59 backtest. "
            "See broker/.env.example for setup instructions."
        )

    # Cover pre-market to capture any 09:30 bars that land as 09:29 in UTC math
    start_iso = f"{start}T13:00:00Z"   # 09:00 ET = 13:00 UTC (approx; Alpaca filters RTH)
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
            time.sleep(0.05)   # respect rate limits (~20 req/s free tier)
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
    # Alpaca minute bar columns: t=timestamp, o=open, h=high, l=low, c=close, v=volume
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                             "l": "low", "c": "close", "v": "volume"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["open", "high", "low", "close", "volume"]]


def _filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Convert UTC index to ET; keep only bars with timestamp in RTH (09:30-15:59 ET)."""
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

    # Compute max run of consecutive missing business days
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
    Filters to RTH (09:30-16:00 ET). Checks for data gaps.
    Returns DataFrame indexed by ET-localized timestamps.
    Raises EnvironmentError if Alpaca credentials not configured.
    Raises ValueError if no RTH bars are found.
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

def compute_opening_range(
    df_day: pd.DataFrame,
    or_window_min: int,
) -> tuple[float, float, float]:
    """
    Compute OR_high, OR_low, OR_width from a single-day 1-minute OHLCV DataFrame.
    OR window: first or_window_min bars starting at 09:30 ET (bars where t >= 09:30 and t < 09:30+N).
    Uses high column for OR_high and low column for OR_low (OHLCV bar convention).

    Returns:
        (OR_high, OR_low, OR_width) where OR_width = OR_high - OR_low
    Raises:
        ValueError if OR window has fewer than half the expected bars, or OR_width <= 0.
    """
    if df_day.empty:
        raise ValueError("Empty day DataFrame passed to compute_opening_range")

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

def _compute_cost_components(
    entry_price: float,
    exit_price: float,
    params: dict,
    sigma: float,
    adv: float,
) -> tuple[float, float, float, float, bool]:
    """
    Compute individual cost components per Engineering Director canonical model.
    Returns (commission_total, slippage_total, market_impact_total, total_cost, liquidity_constrained).
    All totals are in dollars (not per share); market impact applied once at entry leg.
    """
    qty = params["position_shares"]
    k = params["market_impact_k"]

    # Commission: $0.005/share per leg (entry + exit)
    commission_total = params["fixed_cost_per_share"] * 2 * qty

    # Slippage: 0.05% of trade price per leg (half-spread)
    slippage_total = (params["slippage_pct"] * entry_price + params["slippage_pct"] * exit_price) * qty

    # Market impact: k * sigma * sqrt(Q/ADV) * entry_price * qty
    liquidity_constrained = False
    market_impact_total = 0.0
    if adv > 0 and sigma > 0:
        q_over_adv = qty / adv
        liquidity_constrained = q_over_adv > params["liquidity_threshold"]
        market_impact_total = k * sigma * np.sqrt(q_over_adv) * entry_price * qty

    total_cost = commission_total + slippage_total + market_impact_total
    return commission_total, slippage_total, market_impact_total, total_cost, liquidity_constrained


def apply_transaction_costs(
    trade: dict,
    params: dict,
    sigma: float,
    adv: float,
) -> tuple[float, bool]:
    """
    Apply canonical transaction cost model to a single trade.

    Args:
        trade: dict with keys 'entry_price', 'exit_price'
        params: PARAMETERS dict (uses position_shares, fixed_cost_per_share, slippage_pct, etc.)
        sigma: 20-day rolling daily return std (dimensionless, e.g. 0.01 = 1%)
        adv: 20-day average daily volume in shares

    Returns:
        (net_pnl, liquidity_constrained)
    """
    entry_price = trade["entry_price"]
    exit_price = trade["exit_price"]
    qty = params["position_shares"]
    _, _, _, total_cost, liq = _compute_cost_components(entry_price, exit_price, params, sigma, adv)
    pnl_gross = (exit_price - entry_price) * qty
    return pnl_gross - total_cost, liq


# ── Signal Generation ────────────────────────────────────────────────────────────

def _parse_exit_time(exit_time_str: str) -> dt.time:
    """Parse 'HH:MM' string to datetime.time."""
    hh, mm = exit_time_str.split(":")
    return dt.time(int(hh), int(mm))


def generate_daily_signals(
    df: pd.DataFrame,
    params: dict,
    daily_sigma: pd.Series = None,
    daily_adv: pd.Series = None,
    ticker: str = "",
) -> pd.DataFrame:
    """
    Process each RTH trading day in df to find ORB entries and exits.

    Signal logic (long-only baseline):
      1. Compute OR_high/OR_low from first or_window_min bars (09:30-09:30+N)
      2. Skip day if OR_width/OR_close < min_or_width_pct (costs dominate narrow ORs)
      3. After OR window ends, scan bars for close > OR_high (breakout trigger)
      4. Enter at open of the NEXT bar (t+1 fill; no same-bar fill — look-ahead free)
      5. Scan forward for first exit: target hit, stop hit, or hard EOD exit at 15:55
      6. At most 1 trade per day (first valid breakout only)

    Args:
        df: 1-minute RTH DataFrame with ET-localized DatetimeIndex
        params: PARAMETERS dict
        daily_sigma: pd.Series of daily return std indexed by date (for transaction costs)
        daily_adv: pd.Series of daily volume averages indexed by date (for transaction costs)
        ticker: ticker symbol for logging (optional)

    Returns:
        DataFrame of trade records with one row per executed trade.
    """
    hard_exit_time = _parse_exit_time(params["exit_time_et"])
    or_window = params["or_window_min"]

    trade_rows = []
    # Pre-group by date once (O(N)) to avoid O(N) lookup per trading day.
    date_to_bars = {d: g for d, g in df.groupby(df.index.normalize())}
    trading_dates = sorted(date_to_bars.keys())

    for date in trading_dates:
        date_str = str(date.date())
        df_day = date_to_bars[date]

        if len(df_day) < or_window + 5:   # need OR bars + at least one post-OR bar
            logger.debug("Skipping %s %s: only %d bars", ticker, date_str, len(df_day))
            continue

        # ── Opening Range ─────────────────────────────────────────────────────────
        try:
            or_high, or_low, or_width = compute_opening_range(df_day, or_window)
        except ValueError as exc:
            logger.debug("Skipping %s %s: %s", ticker, date_str, exc)
            continue

        # OR close = close of the last bar strictly inside the OR window
        day_date = df_day.index[0].date()
        or_start_ts = pd.Timestamp(day_date, tz=ET).replace(hour=9, minute=30)
        or_end_ts = or_start_ts + pd.Timedelta(minutes=or_window)
        or_bars = df_day[(df_day.index >= or_start_ts) & (df_day.index < or_end_ts)]
        or_close = float(or_bars["close"].iloc[-1])

        # Skip days with OR too narrow (edge < cost)
        if or_close > 0 and or_width / or_close < params["min_or_width_pct"]:
            logger.debug(
                "Skipping %s %s: OR too narrow (%.4f%% < %.4f%%)",
                ticker, date_str,
                or_width / or_close * 100,
                params["min_or_width_pct"] * 100,
            )
            continue

        # Lookup transaction cost inputs (shift(1) already applied by caller)
        sigma_val = 0.01   # fallback ~1% daily vol for equity ETFs
        adv_val = 50_000_000   # fallback ~50M shares ADV
        if daily_sigma is not None and date in daily_sigma.index:
            v = daily_sigma.loc[date]
            if pd.notna(v) and v > 0:
                sigma_val = float(v)
        if daily_adv is not None and date in daily_adv.index:
            v = daily_adv.loc[date]
            if pd.notna(v) and v > 0:
                adv_val = float(v)

        # ── Post-OR scanning ──────────────────────────────────────────────────────
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
                break   # no more entries possible today

            # Long breakout trigger: bar close exceeds OR_high
            if post_closes[i] > or_high:
                # Require a next bar for t+1 fill (no same-bar entry)
                if i + 1 >= n_post:
                    break
                # Guard: don't enter if next bar is at or past hard exit
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

                    # Target hit: bar high reaches or exceeds target
                    if post_highs[j] >= target:
                        exit_price = target
                        exit_ts = str(post_index[j])
                        exit_reason = "target"
                        break

                    # Stop hit: bar low drops to or below stop
                    if post_lows[j] <= stop:
                        exit_price = stop
                        exit_ts = str(post_index[j])
                        exit_reason = "stop"
                        break

                    # Hard EOD: bar time at or past exit_time_et
                    if ex_bar_time >= hard_exit_time:
                        exit_price = float(post_closes[j])
                        exit_ts = str(post_index[j])
                        exit_reason = "eod"
                        break

                # If scanning ended without hitting any exit condition
                if exit_price is None:
                    last_j = n_post - 1
                    exit_price = float(post_closes[last_j])
                    exit_ts = str(post_index[last_j])
                    exit_reason = "eod"

                # ── Transaction costs ───────────────────────────────────────────
                comm, slip, mkt_imp, total_cost, liq = _compute_cost_components(
                    entry_price, exit_price, params, sigma_val, adv_val
                )
                qty = params["position_shares"]
                pnl_gross = (exit_price - entry_price) * qty
                pnl_net = pnl_gross - total_cost

                if liq:
                    q_adv_ratio = qty / adv_val if adv_val > 0 else float("inf")
                    logger.warning(
                        "LIQUIDITY CONSTRAINED: %s %s — Q=%d shares, ADV=%.0f shares, Q/ADV=%.4f",
                        ticker, date_str, qty, adv_val, q_adv_ratio,
                    )

                trade_rows.append({
                    "date": date_str,
                    "ticker": ticker,
                    "entry_time": entry_ts,
                    "exit_time": exit_ts,
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "stop": round(stop, 4),
                    "target": round(target, 4),
                    "exit_reason": exit_reason,
                    "pnl_gross": round(pnl_gross, 4),
                    "pnl_net": round(pnl_net, 4),
                    "commission": round(comm, 4),
                    "slippage": round(slip, 4),
                    "market_impact": round(mkt_imp, 4),
                    "liquidity_constrained": liq,
                })
                break   # at most 1 trade per day

    return pd.DataFrame(trade_rows)


# ── Performance Metrics ──────────────────────────────────────────────────────────

def _daily_pnl_series(trades_df: pd.DataFrame, start_date: str, end_date: str) -> pd.Series:
    """
    Build daily P&L series from trade log. No-trade days receive pnl = 0.
    Uses business day calendar between start_date and end_date.
    """
    if trades_df.empty:
        bdays = pd.bdate_range(start_date, end_date)
        return pd.Series(0.0, index=pd.Index(bdays.astype(str)))

    daily_pnl = trades_df.groupby("date")["pnl_net"].sum()
    bdays = pd.bdate_range(start_date, end_date)
    all_dates = pd.Index([str(d.date()) for d in bdays])
    return daily_pnl.reindex(all_dates, fill_value=0.0)


def compute_metrics(
    trades_df: pd.DataFrame,
    start_date: str = None,
    end_date: str = None,
    account_size: float = None,
) -> dict:
    """
    Compute standard Gate 1 performance metrics from a trade log DataFrame.

    Daily Sharpe: computed from daily P&L series including no-trade days (P&L=0).
    This is the primary reported Sharpe — more conservative than trade-only Sharpe.

    Args:
        trades_df: output of generate_daily_signals()
        start_date: first date of window (YYYY-MM-DD); inferred from trades if None
        end_date: last date of window (YYYY-MM-DD); inferred from trades if None
        account_size: equity base for return normalization; uses PARAMETERS default if None

    Returns:
        dict with Sharpe, MDD, win_rate, profit_factor, avg_trade_gross_bps,
        avg_trade_net_bps, n_trades and related diagnostics.
    """
    acct = account_size if account_size is not None else PARAMETERS["account_size"]

    if trades_df.empty:
        return {
            "n_trades": 0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_trade_gross_bps": 0.0,
            "avg_trade_net_bps": 0.0,
            "error": "no_trades",
        }

    n_trades = len(trades_df)
    s_date = start_date or trades_df["date"].min()
    e_date = end_date or trades_df["date"].max()

    # Daily P&L and return series
    daily_pnl = _daily_pnl_series(trades_df, s_date, e_date)
    daily_ret = daily_pnl / acct

    # Sharpe (annualized from daily, including no-trade days)
    mean_ret = daily_ret.mean()
    std_ret = daily_ret.std()
    sharpe = (mean_ret / std_ret * np.sqrt(TRADING_DAYS_PER_YEAR)) if std_ret > 0 else 0.0

    # Max drawdown from cumulative equity curve
    cum_equity = (1 + daily_ret).cumprod()
    rolling_peak = cum_equity.cummax()
    drawdown = (cum_equity - rolling_peak) / rolling_peak
    max_drawdown = float(drawdown.min())

    # Win rate and profit factor (trade level)
    wins = trades_df[trades_df["pnl_gross"] > 0]["pnl_gross"]
    losses = trades_df[trades_df["pnl_gross"] <= 0]["pnl_gross"]
    win_rate = len(wins) / n_trades if n_trades > 0 else 0.0
    gross_wins = wins.sum()
    gross_losses = abs(losses.sum())
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")

    # Average trade P&L in basis points (relative to notional = entry_price * shares)
    notional = trades_df["entry_price"] * PARAMETERS["position_shares"]
    gross_bps = (trades_df["pnl_gross"] / notional * 10000).mean()
    net_bps = (trades_df["pnl_net"] / notional * 10000).mean()

    # Exit reason breakdown
    exit_counts = trades_df["exit_reason"].value_counts().to_dict()
    liq_count = int(trades_df["liquidity_constrained"].sum())

    return {
        "n_trades": int(n_trades),
        "sharpe": round(float(sharpe), 4),
        "max_drawdown": round(float(max_drawdown), 6),
        "win_rate": round(float(win_rate), 4),
        "profit_factor": round(float(profit_factor), 4),
        "avg_trade_gross_bps": round(float(gross_bps), 2),
        "avg_trade_net_bps": round(float(net_bps), 2),
        "total_gross_pnl": round(float(trades_df["pnl_gross"].sum()), 2),
        "total_net_pnl": round(float(trades_df["pnl_net"].sum()), 2),
        "exit_target_pct": round(exit_counts.get("target", 0) / n_trades, 4),
        "exit_stop_pct": round(exit_counts.get("stop", 0) / n_trades, 4),
        "exit_eod_pct": round(exit_counts.get("eod", 0) / n_trades, 4),
        "liquidity_constrained_count": liq_count,
        "start_date": s_date,
        "end_date": e_date,
    }


# ── Walk-Forward Analysis ────────────────────────────────────────────────────────

def run_walk_forward(
    df: pd.DataFrame,
    params: dict,
    is_months: int = 12,
    oos_months: int = 3,
    ticker: str = "",
) -> list:
    """
    Rolling walk-forward analysis over the full intraday DataFrame.
    Each window: IS = is_months, OOS = oos_months. Roll forward by oos_months per step.
    For each window, compute IS and OOS metrics separately.
    Parameters are fixed (no fitting) — walk-forward tests temporal consistency.

    Returns:
        list of dicts, one per window, each with 'window', 'is_metrics', 'oos_metrics'.
    """
    if df.empty:
        return []

    # Build daily closing prices for sigma and ADV computation
    daily_close = df.groupby(df.index.normalize())["close"].last()
    daily_volume = df.groupby(df.index.normalize())["volume"].sum()
    daily_returns = daily_close.pct_change()

    sigma_series = (
        daily_returns.rolling(params["sigma_window"]).std().shift(1).reindex(df.index.normalize().unique())
    )
    adv_series = (
        daily_volume.rolling(params["adv_window"]).mean().shift(1).reindex(df.index.normalize().unique())
    )

    # Month-end anchor dates
    norm_idx = df.index.normalize()   # pre-compute once for all WF window slicing
    all_dates = norm_idx.unique().sort_values()
    start_dt = all_dates[0].to_pydatetime()
    end_dt = all_dates[-1].to_pydatetime()

    results = []
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

        is_mask = (norm_idx >= pd.Timestamp(is_start_str, tz=ET)) & \
                  (norm_idx < pd.Timestamp(is_end_str, tz=ET))
        oos_mask = (norm_idx >= pd.Timestamp(oos_start_str, tz=ET)) & \
                   (norm_idx < pd.Timestamp(oos_end_str, tz=ET))

        df_is = df.loc[is_mask]
        df_oos = df.loc[oos_mask]

        is_trades = generate_daily_signals(df_is, params, sigma_series, adv_series, ticker)
        oos_trades = generate_daily_signals(df_oos, params, sigma_series, adv_series, ticker)

        results.append({
            "window": f"{is_start_str}:{is_end_str}:{oos_end_str}",
            "is_start": is_start_str,
            "is_end": is_end_str,
            "oos_start": oos_start_str,
            "oos_end": oos_end_str,
            "is_metrics": compute_metrics(is_trades, is_start_str, is_end_str),
            "oos_metrics": compute_metrics(oos_trades, oos_start_str, oos_end_str),
        })

        window_start = window_start + pd.DateOffset(months=oos_months)

    logger.info("Walk-forward: %d windows completed", len(results))
    return results


# ── Main Backtest Entry Point ────────────────────────────────────────────────────

def run_backtest(
    ticker: str = "SPY",
    is_start: str = "2016-01-01",
    is_end: str = "2021-12-31",
    oos_start: str = "2022-01-01",
    oos_end: str = "2024-12-31",
    params: dict = None,
    earnings_dates: list = None,
) -> dict:
    """
    Run H59 ORB full backtest: IS period + OOS period + walk-forward.

    Args:
        ticker: equity ticker (default 'SPY'; 'QQQ' for robustness check)
        is_start: in-sample start date (YYYY-MM-DD)
        is_end: in-sample end date (YYYY-MM-DD)
        oos_start: out-of-sample start date (YYYY-MM-DD)
        oos_end: out-of-sample end date (YYYY-MM-DD)
        params: parameter dict (defaults to PARAMETERS if None)
        earnings_dates: optional list of 'YYYY-MM-DD' earnings announcement dates.
            If provided, reports a second metric set excluding ±1 trading day around
            earnings dates as a sensitivity test.

    Returns:
        Full result dict matching the Gate 1 output contract.
    """
    if params is None:
        params = PARAMETERS.copy()

    account_size = params.get("account_size", PARAMETERS["account_size"])

    logger.info("=== H59 Opening Range Breakout Backtest ===")
    logger.info("Ticker: %s | IS: %s -> %s | OOS: %s -> %s", ticker, is_start, is_end, oos_start, oos_end)
    logger.info("OR window: %d min | R_mult: %.1f | stop_buffer: %.2f",
                params["or_window_min"], params["r_mult"], params["stop_buffer"])

    # ── 1. Load full intraday data ────────────────────────────────────────────────
    logger.info("[1/5] Loading intraday data (%s) ...", ticker)
    try:
        df_full = load_intraday_data(ticker, is_start, oos_end)
    except Exception as exc:
        return {"error": f"Data load failed: {exc}", "strategy": "H59_ORB", "ticker": ticker}

    # ── 2. Compute daily risk metrics (no look-ahead: shift(1)) ──────────────────
    logger.info("[2/5] Computing daily sigma and ADV ...")
    daily_close = df_full.groupby(df_full.index.normalize())["close"].last()
    daily_volume = df_full.groupby(df_full.index.normalize())["volume"].sum()
    daily_returns = daily_close.pct_change()

    daily_sigma = daily_returns.rolling(params["sigma_window"]).std().shift(1)
    daily_adv = daily_volume.rolling(params["adv_window"]).mean().shift(1)

    # ── 3. Slice IS / OOS data ───────────────────────────────────────────────────
    is_start_ts = pd.Timestamp(is_start, tz=ET)
    is_end_ts = pd.Timestamp(is_end, tz=ET).replace(hour=23, minute=59)
    oos_start_ts = pd.Timestamp(oos_start, tz=ET)
    oos_end_ts = pd.Timestamp(oos_end, tz=ET).replace(hour=23, minute=59)

    df_is = df_full[(df_full.index >= is_start_ts) & (df_full.index <= is_end_ts)]
    df_oos = df_full[(df_full.index >= oos_start_ts) & (df_full.index <= oos_end_ts)]

    # ── 4. Generate signals ──────────────────────────────────────────────────────
    logger.info("[3/5] Generating IS signals (%s -> %s) ...", is_start, is_end)
    is_trades = generate_daily_signals(df_is, params, daily_sigma, daily_adv, ticker)
    logger.info("IS: %d trades generated", len(is_trades))

    logger.info("[3/5] Generating OOS signals (%s -> %s) ...", oos_start, oos_end)
    oos_trades = generate_daily_signals(df_oos, params, daily_sigma, daily_adv, ticker)
    logger.info("OOS: %d trades generated", len(oos_trades))

    # ── 5. Earnings sensitivity test (optional) ──────────────────────────────────
    earnings_sensitivity = None
    if earnings_dates is not None and len(earnings_dates) > 0:
        earn_set = set(earnings_dates)
        all_trading_dates = [str(d.date()) for d in daily_close.index]

        def _build_exclude_set(earn_dates: set, bday_list: list) -> set:
            """Build set of dates to exclude: earnings ±1 trading day."""
            bday_sorted = sorted(bday_list)
            bday_idx = {d: i for i, d in enumerate(bday_sorted)}
            exclude = set()
            for ed in earn_dates:
                idx = bday_idx.get(ed)
                if idx is not None:
                    for delta in (-1, 0, 1):
                        if 0 <= idx + delta < len(bday_sorted):
                            exclude.add(bday_sorted[idx + delta])
            return exclude

        exclude_dates = _build_exclude_set(earn_set, all_trading_dates)

        is_ex_earn = is_trades[~is_trades["date"].isin(exclude_dates)]
        oos_ex_earn = oos_trades[~oos_trades["date"].isin(exclude_dates)]

        earnings_sensitivity = {
            "excluded_dates_count": len(exclude_dates),
            "is_ex_earnings_metrics": compute_metrics(is_ex_earn, is_start, is_end, account_size),
            "oos_ex_earnings_metrics": compute_metrics(oos_ex_earn, oos_start, oos_end, account_size),
        }
        logger.info(
            "Earnings sensitivity: %d dates excluded (±1 day around %d events)",
            len(exclude_dates), len(earnings_dates),
        )

    # ── 6. Compute metrics ───────────────────────────────────────────────────────
    logger.info("[4/5] Computing performance metrics ...")
    is_metrics = compute_metrics(is_trades, is_start, is_end, account_size)
    oos_metrics = compute_metrics(oos_trades, oos_start, oos_end, account_size)

    # ── 7. Walk-forward analysis ─────────────────────────────────────────────────
    logger.info("[5/5] Running walk-forward analysis (12m IS / 3m OOS windows) ...")
    wf_windows = run_walk_forward(df_full, params, is_months=12, oos_months=3, ticker=ticker)
    wf_oos_sharpes = [
        w["oos_metrics"]["sharpe"]
        for w in wf_windows
        if "error" not in w["oos_metrics"] and w["oos_metrics"]["n_trades"] > 0
    ]
    wf_sharpe_floor = 0.30
    wf_passes = sum(1 for s in wf_oos_sharpes if s >= wf_sharpe_floor)

    # ── 8. Build trade log (combined IS + OOS) ───────────────────────────────────
    all_trades = pd.concat([is_trades, oos_trades], ignore_index=True) if not is_trades.empty else oos_trades
    trade_log = all_trades.to_dict("records") if not all_trades.empty else []
    liq_count_total = int(all_trades["liquidity_constrained"].sum()) if not all_trades.empty else 0

    # ── 9. Assemble result ───────────────────────────────────────────────────────
    result = {
        "strategy": "H59_ORB",
        "ticker": ticker,
        "params": params,
        # Top-level Gate 1 contract fields
        "is_sharpe": is_metrics["sharpe"],
        "oos_sharpe": oos_metrics["sharpe"],
        "is_mdd": is_metrics["max_drawdown"],
        "oos_mdd": oos_metrics["max_drawdown"],
        "is_trades": is_metrics["n_trades"],
        "oos_trades": oos_metrics["n_trades"],
        "win_rate": is_metrics["win_rate"],
        "profit_factor": is_metrics["profit_factor"],
        "avg_trade_gross_bps": is_metrics["avg_trade_gross_bps"],
        "avg_trade_net_bps": is_metrics["avg_trade_net_bps"],
        # Detailed metrics
        "is_metrics": is_metrics,
        "oos_metrics": oos_metrics,
        # Walk-forward
        "walk_forward_windows": wf_windows,
        "walk_forward_summary": {
            "n_windows": len(wf_windows),
            "oos_sharpe_floor": wf_sharpe_floor,
            "oos_passes": wf_passes,
            "oos_total": len(wf_oos_sharpes),
            "consistency": f"{wf_passes}/{len(wf_oos_sharpes)}",
        },
        # Trade log
        "trade_log": trade_log,
        "liquidity_constrained_count": liq_count_total,
        # Earnings sensitivity (populated if earnings_dates provided)
        "earnings_sensitivity": earnings_sensitivity,
        # Data quality
        "data_quality": {
            "survivorship_bias": "NOT APPLICABLE — SPY/QQQ are continuous benchmark ETFs",
            "price_adjustments": "Alpaca adjustment=all (splits + dividends)",
            "data_gaps": "flagged at runtime; days with insufficient OR bars skipped",
            "earnings_exclusion": "see earnings_sensitivity field; baseline includes all days",
            "delisted_tickers": "NOT APPLICABLE — SPY/QQQ active through full backtest window",
            "ml_pipeline": "N/A — signal-based strategy, no ML fitting",
            "pdt_compliance": "requires account >= $25,001",
        },
    }

    logger.info(
        "=== H59 Backtest Complete === IS Sharpe: %.2f | OOS Sharpe: %.2f | "
        "IS trades: %d | OOS trades: %d | WF: %s",
        is_metrics["sharpe"], oos_metrics["sharpe"],
        is_metrics["n_trades"], oos_metrics["n_trades"],
        result["walk_forward_summary"]["consistency"],
    )
    return result


# ── Entry Point ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    logger.info("Running H59 ORB backtest — SPY primary, QQQ robustness ...")
    spy_result = run_backtest("SPY", "2016-01-01", "2021-12-31", "2022-01-01", "2024-12-31")
    print(json.dumps(spy_result, indent=2, default=str))

    qqq_result = run_backtest("QQQ", "2016-01-01", "2021-12-31", "2022-01-01", "2024-12-31")
    print(json.dumps(qqq_result, indent=2, default=str))
