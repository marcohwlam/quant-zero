"""
Strategy: H63 SPY/QQQ Intraday Cointegrated Spread Mean Reversion
Author: Strategy Coder Agent (Engineering Director QUA-167)
Date: 2026-06-09
Hypothesis: SPY and QQQ are cointegrated. The log-price spread log(SPY) - beta*log(QQQ)
            is mean-reverting intraday at the 30-min horizon. Enter when the rolling
            z-score exceeds ±ENTRY_ZSCORE (signal bar close → fill next bar open).
            Exit at ±EXIT_ZSCORE or hard stop ±STOP_ZSCORE, EOD exit at 15:45 ET.
            Skip sessions with prior-day VIX > VIX_FILTER_THRESHOLD.
Asset class: US equity ETFs (SPY, QQQ) — intraday-flat, market-neutral
Parent task: QUA-167
References:
    Chan (2013) Algorithmic Trading, Ch. 6, pp. 105-133
    Gatev, Goetzmann & Rouwenhorst (2006) RFS 19(3)
    Avellaneda & Lee (2010) QF 10(7)
    research/hypotheses/63_spy_qqq_intraday_pairs_mean_reversion.md
    knowledge_base/mkb007_intraday_etf_pairs_cointegration.md

PDT NOTE: Strategy trades 3-8 spread crossings/day (each = 2 day trades: 1 SPY + 1 QQQ).
Requires PDT (Pattern Day Trader) designation. At $25K, PDT is available but any drawdown
below $25K loses PDT eligibility. Recommended minimum capital: $30K to buffer 8-15% MDD.
"""

import os
import sys
import time
import logging
import warnings
import numpy as np
import pandas as pd
import requests
from pathlib import Path
from typing import Optional, Tuple, List, Dict

logger = logging.getLogger(__name__)

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ZSCORE_LOOKBACK_MIN": 30,       # Rolling window in minutes for intraday z-score
    "ENTRY_ZSCORE": 1.5,             # Enter when |z| > this
    "EXIT_ZSCORE": 0.25,             # Exit when |z| < this (mean reversion)
    "STOP_ZSCORE": 3.0,              # Hard stop when |z| > this (divergence)
    "HEDGE_LOOKBACK_DAYS": 20,       # Days for daily rolling OLS beta
    "VIX_FILTER_THRESHOLD": 30.0,    # Skip session if prior-day VIX > this
    "OPEN_SKIP_MINUTES": 15,         # Skip first N minutes after 09:30 ET
    "INIT_CASH": 25000.0,            # Initial capital ($)
    "SPY_NOTIONAL": 12500.0,         # SPY leg notional per trade ($)
    "QQQ_NOTIONAL": 12500.0,         # QQQ leg notional per trade ($)
}

# ── Transaction Cost Constants (Engineering Director canonical spec) ───────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share
SLIPPAGE_PCT = 0.0005           # 0.05% of notional (one-way)
MARKET_IMPACT_K = 0.1           # Almgren-Chriss sqrt-impact coefficient k
DAILY_SIGMA_WINDOW = 20         # days for rolling σ in market impact
DAILY_ADV_WINDOW = 20           # days for rolling ADV in market impact
TRADING_DAYS_PER_YEAR = 252

# ── Alpaca Data Fetch ──────────────────────────────────────────────────────────

def _fetch_alpaca_minute_bars(
    symbol: str,
    start_iso: str,
    end_iso: str,
    api_key: str,
    api_secret: str,
    feed: str = "sip",
) -> pd.DataFrame:
    """
    Fetch 1-min OHLCV bars from Alpaca for symbol over [start_iso, end_iso].
    Handles pagination with exponential backoff. Returns DataFrame with UTC DatetimeIndex.
    """
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }
    params: Dict = {
        "timeframe": "1Min",
        "start": start_iso,
        "end": end_iso,
        "adjustment": "split",
        "limit": 10000,
        "feed": feed,
    }

    all_bars: List[dict] = []
    page = 0
    backoff = 1.0

    while True:
        for attempt in range(4):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=30)
                if resp.status_code == 200:
                    break
                if resp.status_code in (429, 503) and attempt < 3:
                    logger.warning("HTTP %s — retry %d in %.1fs", resp.status_code, attempt + 1, backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                resp.raise_for_status()
            except requests.exceptions.Timeout:
                if attempt < 3:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                raise

        data = resp.json()
        raw = data.get("bars") or []
        if raw:
            all_bars.extend(raw)
            page += 1
            if page % 5 == 0:
                logger.info("  %s: %d bars (page %d)...", symbol, len(all_bars), page)
        else:
            # No bars but may have next page token — extremely rare; break
            pass

        token = data.get("next_page_token")
        if not token:
            break
        params["page_token"] = token

    if not all_bars:
        return pd.DataFrame()

    df = pd.DataFrame(all_bars)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.set_index("t")
    df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    df = df[["Open", "High", "Low", "Close", "Volume"]].sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def fetch_minute_data(
    symbol: str,
    start_date: str,
    end_date: str,
    cache_dir: Optional[str] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch or load from cache 1-min bars for symbol over [start_date, end_date].
    Requests are chunked into ~2-month windows to avoid Alpaca API range limits.
    Returns DataFrame with UTC DatetimeIndex.
    """
    api_key = os.environ.get("ALPACA_API_KEY", "")
    api_secret = os.environ.get("ALPACA_API_SECRET", "")
    if not api_key or not api_secret:
        raise EnvironmentError("ALPACA_API_KEY and ALPACA_API_SECRET must be set")

    if cache_dir is None:
        cache_dir = str(Path(__file__).parent.parent / "pipelines" / "data" / "h63_cache")
    os.makedirs(cache_dir, exist_ok=True)

    fname = f"{symbol}_{start_date}_{end_date}.pkl"
    cache_path = Path(cache_dir) / fname

    if not force_refresh and cache_path.exists():
        logger.info("  Loading %s from cache: %s", symbol, cache_path.name)
        return pd.read_pickle(str(cache_path))

    logger.info("  Fetching %s %s → %s from Alpaca SIP (chunked)...", symbol, start_date, end_date)

    # Chunk into ~2-month windows to avoid API range limits
    from datetime import date as _date, timedelta as _td
    chunk_start = pd.Timestamp(start_date).date()
    chunk_end_overall = pd.Timestamp(end_date).date()
    CHUNK_DAYS = 60  # ~2 months per request

    all_chunks: List[pd.DataFrame] = []
    while chunk_start <= chunk_end_overall:
        chunk_end = min(chunk_start + _td(days=CHUNK_DAYS), chunk_end_overall)
        start_iso = f"{chunk_start.strftime('%Y-%m-%d')}T09:00:00Z"
        end_iso = f"{chunk_end.strftime('%Y-%m-%d')}T23:59:00Z"
        logger.debug("  %s chunk %s → %s", symbol, chunk_start, chunk_end)
        chunk_df = _fetch_alpaca_minute_bars(symbol, start_iso, end_iso, api_key, api_secret)
        if not chunk_df.empty:
            all_chunks.append(chunk_df)
        chunk_start = chunk_end + _td(days=1)

    if not all_chunks:
        raise ValueError(f"No minute bars returned for {symbol} {start_date}–{end_date}")

    df = pd.concat(all_chunks).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.to_pickle(str(cache_path))
    logger.info("  Cached %s: %d bars", symbol, len(df))
    return df


def filter_rth(df: pd.DataFrame, tz: str = "America/New_York") -> pd.DataFrame:
    """
    Keep only bars in RTH (09:30–15:59 ET). Returns df with ET DatetimeIndex.
    Input must have UTC DatetimeIndex.
    """
    df_et = df.copy()
    if df_et.index.tz is None:
        df_et.index = df_et.index.tz_localize("UTC")
    df_et.index = df_et.index.tz_convert(tz)
    open_t = pd.Timestamp("09:30").time()
    close_t = pd.Timestamp("15:59").time()
    mask = (df_et.index.time >= open_t) & (df_et.index.time <= close_t)
    return df_et[mask]


# ── Daily Beta ─────────────────────────────────────────────────────────────────

def compute_daily_beta(
    spy_close: pd.Series,
    qqq_close: pd.Series,
    lookback_days: int,
) -> pd.Series:
    """
    Rolling OLS beta: log(SPY) = alpha + beta * log(QQQ).
    beta[i] uses rows [i-lookback_days, i) — strictly backward-looking.
    Returns Series indexed by date (same index as spy_close after alignment).
    """
    common = spy_close.index.intersection(qqq_close.index)
    spy_log = np.log(spy_close.reindex(common))
    qqq_log = np.log(qqq_close.reindex(common))

    n = len(common)
    betas = np.full(n, np.nan)

    for i in range(lookback_days, n):
        y = spy_log.iloc[i - lookback_days: i].values
        x = qqq_log.iloc[i - lookback_days: i].values
        xm = np.column_stack([np.ones(len(x)), x])
        try:
            coef, _, _, _ = np.linalg.lstsq(xm, y, rcond=None)
            betas[i] = coef[1]
        except Exception:
            betas[i] = 0.9

    return pd.Series(betas, index=common)


# ── Transaction Costs ──────────────────────────────────────────────────────────

def compute_trade_cost(
    price: float,
    shares: int,
    sigma: float,
    adv: float,
) -> Tuple[float, bool]:
    """
    Canonical equities cost model (Engineering Director spec):
      fixed    = $0.005/share
      slippage = 0.05% of notional (one-way)
      impact   = k * sigma * sqrt(Q/ADV) * price * Q

    Returns (total_cost_$, liquidity_constrained).
    """
    if shares <= 0 or price <= 0:
        return 0.0, False
    sigma = sigma if (sigma and np.isfinite(sigma) and sigma > 0) else 0.01
    adv = adv if (adv and np.isfinite(adv) and adv > 0) else 1_000_000.0

    notional = price * shares
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * notional
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * notional
    liq_constrained = bool(shares / adv > 0.01)
    return fixed + slippage + impact, liq_constrained


# ── Signal Preparation ─────────────────────────────────────────────────────────

def prepare_signals(
    spy_rth: pd.DataFrame,
    qqq_rth: pd.DataFrame,
    spy_daily: pd.DataFrame,
    qqq_daily: pd.DataFrame,
    vix_close: pd.Series,
    params: dict,
) -> pd.DataFrame:
    """
    Build the complete signal DataFrame needed for simulation.

    Columns returned:
        spy_open, spy_close, qqq_open, qqq_close,
        beta, spread, zscore,
        spy_sigma, qqq_sigma, spy_adv, qqq_adv,
        vix_ok, tradeable, eod_exit

    Index: DatetimeIndex (ET timezone)
    """
    zscore_win = params["ZSCORE_LOOKBACK_MIN"]
    hedge_days = params["HEDGE_LOOKBACK_DAYS"]
    vix_thresh = params["VIX_FILTER_THRESHOLD"]
    skip_min = params["OPEN_SKIP_MINUTES"]

    # ── 1. Join SPY and QQQ minute bars ───────────────────────────────────────
    sig = pd.DataFrame({
        "spy_open": spy_rth["Open"],
        "spy_close": spy_rth["Close"],
        "qqq_open": qqq_rth["Open"],
        "qqq_close": qqq_rth["Close"],
    }).dropna()

    if sig.empty:
        raise ValueError("No overlapping SPY/QQQ minute bars after join")

    # Use Python date objects to avoid timezone mismatch with yfinance daily data
    sig["date_py"] = sig.index.date   # array of datetime.date objects

    # ── 2. Daily beta → map to minute bars ────────────────────────────────────
    daily_beta = compute_daily_beta(spy_daily["Close"], qqq_daily["Close"], hedge_days)
    # daily_beta[date] uses closes up to date-1 (backward-looking, no lookahead)
    # Build date-keyed dict using Python date objects
    beta_map = {pd.Timestamp(dt).date(): float(v) for dt, v in daily_beta.items() if not np.isnan(v)}
    sig["beta"] = [beta_map.get(d, np.nan) for d in sig["date_py"]]
    sig["beta"] = sig["beta"].ffill().fillna(0.9)

    # ── 3. Spread and z-score ─────────────────────────────────────────────────
    sig["spy_log"] = np.log(sig["spy_close"])
    sig["qqq_log"] = np.log(sig["qqq_close"])
    sig["spread"] = sig["spy_log"] - sig["beta"] * sig["qqq_log"]

    # Session-reset z-score: rolling window resets at each session open.
    # Prevents cross-session spread shifts (overnight gaps) from generating false signals.
    # Each day's z-score uses only same-day bars — standard intraday pairs practice.
    # groupby date_py then apply rolling within each day (vectorized via transform).
    def _session_zscore(x: pd.Series) -> pd.Series:
        mu = x.rolling(zscore_win, min_periods=zscore_win).mean()
        sigma = x.rolling(zscore_win, min_periods=zscore_win).std()
        z = (x - mu) / sigma.replace(0, np.nan)
        return z

    sig["zscore"] = sig.groupby("date_py")["spread"].transform(_session_zscore)

    # ── 4. Daily sigma and ADV for transaction costs ──────────────────────────
    spy_close_daily = spy_daily["Close"]
    qqq_close_daily = qqq_daily["Close"]
    spy_sigma_s = spy_close_daily.pct_change().rolling(DAILY_SIGMA_WINDOW).std()
    qqq_sigma_s = qqq_close_daily.pct_change().rolling(DAILY_SIGMA_WINDOW).std()
    spy_adv_s = spy_daily["Volume"].rolling(DAILY_ADV_WINDOW).mean()
    qqq_adv_s = qqq_daily["Volume"].rolling(DAILY_ADV_WINDOW).mean()

    spy_sigma_map = {pd.Timestamp(dt).date(): float(v) for dt, v in spy_sigma_s.items() if not np.isnan(v)}
    qqq_sigma_map = {pd.Timestamp(dt).date(): float(v) for dt, v in qqq_sigma_s.items() if not np.isnan(v)}
    spy_adv_map = {pd.Timestamp(dt).date(): float(v) for dt, v in spy_adv_s.items() if not np.isnan(v)}
    qqq_adv_map = {pd.Timestamp(dt).date(): float(v) for dt, v in qqq_adv_s.items() if not np.isnan(v)}

    sig["spy_sigma"] = [spy_sigma_map.get(d, 0.01) for d in sig["date_py"]]
    sig["qqq_sigma"] = [qqq_sigma_map.get(d, 0.01) for d in sig["date_py"]]
    sig["spy_adv"] = [spy_adv_map.get(d, 1e8) for d in sig["date_py"]]
    sig["qqq_adv"] = [qqq_adv_map.get(d, 1e8) for d in sig["date_py"]]

    # ── 5. VIX filter: prior-day VIX close ────────────────────────────────────
    # Build date-keyed dict with prior-day VIX (shift by 1 calendar slot)
    vix_list = [(pd.Timestamp(dt).date(), float(v)) for dt, v in vix_close.items() if not np.isnan(v)]
    vix_prev_map = {}
    for i in range(1, len(vix_list)):
        # vix_list[i][0] is today's date; vix_list[i-1][1] is prior day's VIX close
        vix_prev_map[vix_list[i][0]] = vix_list[i - 1][1]

    sig["vix_prev"] = [vix_prev_map.get(d, 20.0) for d in sig["date_py"]]
    sig["vix_ok"] = sig["vix_prev"] < vix_thresh

    # ── 6. Time-of-day flags ──────────────────────────────────────────────────
    tradeable_start = (pd.Timestamp("09:30") + pd.Timedelta(minutes=skip_min)).time()
    eod_time = pd.Timestamp("15:45").time()

    t_arr = sig.index.time
    sig["tradeable"] = [(tradeable_start <= t < eod_time) for t in t_arr]
    sig["eod_exit"] = [t == eod_time for t in t_arr]

    return sig


# ── Core Simulation ────────────────────────────────────────────────────────────

def simulate(
    sig: pd.DataFrame,
    params: dict,
) -> Tuple[List[dict], pd.Series, pd.DataFrame]:
    """
    Run the H63 pairs trading simulation over the prepared signal DataFrame.

    Execution model:
      - Signal generated at bar t close
      - Fill at bar t+1 open (1-bar latency, no look-ahead)
      - EOD exit signal at 15:45 bar → fill at 15:46 bar open (or same session close if last bar)

    Position model:
      - At most one active spread position at a time
      - Long spread: long SPY + short QQQ (z < -entry_z: SPY cheap vs QQQ)
      - Short spread: short SPY + long QQQ (z > +entry_z: SPY expensive vs QQQ)
      - Position notional: SPY_NOTIONAL + QQQ_NOTIONAL = $25K total deployed

    Returns trade_log, equity_ts (daily), daily_df
    """
    entry_z = params["ENTRY_ZSCORE"]
    exit_z = params["EXIT_ZSCORE"]
    stop_z = params["STOP_ZSCORE"]
    init_cash = float(params["INIT_CASH"])
    spy_notional = float(params["SPY_NOTIONAL"])
    qqq_notional = float(params["QQQ_NOTIONAL"])

    n = len(sig)
    if n < 2:
        return [], pd.Series(dtype=float), pd.DataFrame()

    trade_log: List[dict] = []
    daily_pnl: Dict[pd.Timestamp, float] = {}

    capital = init_cash

    # Position state
    in_pos = False
    direction = 0           # +1 = long spread, -1 = short spread
    spy_shrs = 0
    qqq_shrs = 0
    entry_spy_p = 0.0       # effective entry price (cost-inclusive)
    entry_qqq_p = 0.0
    entry_cost_total = 0.0
    entry_ts = None
    entry_bar_idx = -1
    entry_z_val = 0.0
    entry_liq = False

    # Pending signals: set at bar t, execute at bar t+1
    pending_entry_dir = 0   # 0 = none
    pending_exit_reason = ""

    prev_date = None
    day_start_capital = init_cash

    # Precompute arrays for fast access
    spy_open_arr = sig["spy_open"].values
    spy_close_arr = sig["spy_close"].values
    qqq_open_arr = sig["qqq_open"].values
    qqq_close_arr = sig["qqq_close"].values
    zscore_arr = sig["zscore"].values
    tradeable_arr = sig["tradeable"].values
    eod_exit_arr = sig["eod_exit"].values
    vix_ok_arr = sig["vix_ok"].values
    spy_sigma_arr = sig["spy_sigma"].values
    qqq_sigma_arr = sig["qqq_sigma"].values
    spy_adv_arr = sig["spy_adv"].values
    qqq_adv_arr = sig["qqq_adv"].values
    timestamps = sig.index

    for i in range(n):
        ts = timestamps[i]
        bar_date = ts.normalize()
        z = zscore_arr[i]
        z_abs = abs(z) if not np.isnan(z) else 0.0
        tradeable = bool(tradeable_arr[i])
        eod = bool(eod_exit_arr[i])
        vix_ok = bool(vix_ok_arr[i])

        # ── Day boundary ──────────────────────────────────────────────────────
        if prev_date != bar_date:
            if prev_date is not None:
                # Record previous day's end capital
                mtm = _mark_to_market(capital, in_pos, direction, spy_shrs, qqq_shrs,
                                      spy_close_arr[i - 1], qqq_close_arr[i - 1],
                                      entry_spy_p, entry_qqq_p)
                daily_pnl[prev_date] = mtm
            prev_date = bar_date
            day_start_capital = capital

        # ── Execute pending exit at this bar's open ───────────────────────────
        if pending_exit_reason and in_pos:
            spy_fill = spy_open_arr[i]
            qqq_fill = qqq_open_arr[i]

            spy_ex_cost, spy_ex_liq = compute_trade_cost(
                spy_fill, spy_shrs, spy_sigma_arr[i], spy_adv_arr[i])
            qqq_ex_cost, qqq_ex_liq = compute_trade_cost(
                qqq_fill, qqq_shrs, qqq_sigma_arr[i], qqq_adv_arr[i])

            if direction == 1:
                # Long spread: sell SPY (long), buy QQQ (cover short)
                pnl_spy = (spy_fill - spy_ex_cost / spy_shrs - entry_spy_p) * spy_shrs
                pnl_qqq = (entry_qqq_p - qqq_fill - qqq_ex_cost / qqq_shrs) * qqq_shrs
                exit_spy_net = spy_fill - spy_ex_cost / spy_shrs
                exit_qqq_net = qqq_fill + qqq_ex_cost / qqq_shrs
            else:
                # Short spread: buy SPY (cover short), sell QQQ (long)
                pnl_spy = (entry_spy_p - spy_fill - spy_ex_cost / spy_shrs) * spy_shrs
                pnl_qqq = (qqq_fill - qqq_ex_cost / qqq_shrs - entry_qqq_p) * qqq_shrs
                exit_spy_net = spy_fill + spy_ex_cost / spy_shrs
                exit_qqq_net = qqq_fill - qqq_ex_cost / qqq_shrs

            pnl_net = pnl_spy + pnl_qqq
            capital += pnl_net

            trade_log.append({
                "entry_ts": entry_ts,
                "exit_ts": ts,
                "entry_date": entry_ts.date() if entry_ts else ts.date(),
                "exit_date": ts.date(),
                "direction": "LONG_SPREAD" if direction == 1 else "SHORT_SPREAD",
                "spy_shares": spy_shrs,
                "qqq_shares": qqq_shrs,
                "entry_spy_price": round(entry_spy_p, 4),
                "entry_qqq_price": round(entry_qqq_p, 4),
                "exit_spy_price": round(exit_spy_net, 4),
                "exit_qqq_price": round(exit_qqq_net, 4),
                "pnl": round(pnl_net, 4),
                "entry_cost": round(entry_cost_total, 4),
                "exit_cost": round(spy_ex_cost + qqq_ex_cost, 4),
                "total_cost": round(entry_cost_total + spy_ex_cost + qqq_ex_cost, 4),
                "liquidity_constrained": entry_liq or spy_ex_liq or qqq_ex_liq,
                "entry_zscore": round(entry_z_val, 4),
                "exit_zscore": round(float(z), 4),
                "exit_reason": pending_exit_reason,
                "hold_bars": i - entry_bar_idx,
            })

            in_pos = False
            direction = 0
            spy_shrs = 0
            qqq_shrs = 0
            entry_ts = None
            entry_bar_idx = -1
            pending_exit_reason = ""
            pending_entry_dir = 0  # don't immediately re-enter after exit on same bar

        # ── Execute pending entry at this bar's open ───────────────────────────
        elif pending_entry_dir != 0 and not in_pos:
            spy_fill = spy_open_arr[i]
            qqq_fill = qqq_open_arr[i]

            _spy_shrs = max(1, int(spy_notional / spy_fill))
            _qqq_shrs = max(1, int(qqq_notional / qqq_fill))

            spy_en_cost, spy_en_liq = compute_trade_cost(
                spy_fill, _spy_shrs, spy_sigma_arr[i], spy_adv_arr[i])
            qqq_en_cost, qqq_en_liq = compute_trade_cost(
                qqq_fill, _qqq_shrs, qqq_sigma_arr[i], qqq_adv_arr[i])

            if pending_entry_dir == 1:
                # Long spread: buy SPY, short QQQ
                # Effective entry: cost absorbed into per-share price
                _entry_spy_p = spy_fill + spy_en_cost / _spy_shrs
                _entry_qqq_p = qqq_fill - qqq_en_cost / _qqq_shrs
            else:
                # Short spread: short SPY, buy QQQ
                _entry_spy_p = spy_fill - spy_en_cost / _spy_shrs
                _entry_qqq_p = qqq_fill + qqq_en_cost / _qqq_shrs

            in_pos = True
            direction = pending_entry_dir
            spy_shrs = _spy_shrs
            qqq_shrs = _qqq_shrs
            entry_spy_p = _entry_spy_p
            entry_qqq_p = _entry_qqq_p
            entry_cost_total = spy_en_cost + qqq_en_cost
            entry_ts = ts
            entry_bar_idx = i
            entry_z_val = z
            entry_liq = spy_en_liq or qqq_en_liq
            pending_entry_dir = 0

        # ── EOD hard exit signal ──────────────────────────────────────────────
        if eod and in_pos and not pending_exit_reason:
            pending_exit_reason = "EOD_EXIT"

        # ── In-position exit checks (checked at close, fill at next open) ─────
        if in_pos and not pending_exit_reason and tradeable and not np.isnan(z):
            if z_abs < exit_z:
                pending_exit_reason = "MEAN_REVERT"
            elif z_abs > stop_z:
                pending_exit_reason = "STOP_ZSCORE"
            # Wrong-direction divergence (entered long but spread now very negative → also stop)
            elif direction == 1 and z < -stop_z:
                pending_exit_reason = "STOP_ZSCORE"
            elif direction == -1 and z > stop_z:
                pending_exit_reason = "STOP_ZSCORE"

        # ── Entry signal (at close; fill at next bar open) ────────────────────
        if (
            not in_pos
            and pending_entry_dir == 0
            and not pending_exit_reason
            and tradeable
            and vix_ok
            and not np.isnan(z)
            and z_abs >= entry_z
            and i < n - 1   # need next bar for fill
        ):
            pending_entry_dir = -1 if z > 0 else 1
            # z > +entry_z → spread wide (SPY expensive) → short spread
            # z < -entry_z → spread narrow (SPY cheap) → long spread

    # ── Force-close open position at end of data ──────────────────────────────
    if in_pos and n > 0:
        last_i = n - 1
        spy_fill = spy_close_arr[last_i]
        qqq_fill = qqq_close_arr[last_i]
        ts = timestamps[last_i]

        spy_ex_cost, _ = compute_trade_cost(spy_fill, spy_shrs, 0.01, 1e8)
        qqq_ex_cost, _ = compute_trade_cost(qqq_fill, qqq_shrs, 0.01, 1e8)

        if direction == 1:
            pnl_net = (
                (spy_fill - spy_ex_cost / spy_shrs - entry_spy_p) * spy_shrs +
                (entry_qqq_p - qqq_fill - qqq_ex_cost / qqq_shrs) * qqq_shrs
            )
        else:
            pnl_net = (
                (entry_spy_p - spy_fill - spy_ex_cost / spy_shrs) * spy_shrs +
                (qqq_fill - qqq_ex_cost / qqq_shrs - entry_qqq_p) * qqq_shrs
            )
        capital += pnl_net
        trade_log.append({
            "entry_ts": entry_ts,
            "exit_ts": ts,
            "entry_date": entry_ts.date() if entry_ts else ts.date(),
            "exit_date": ts.date(),
            "direction": "LONG_SPREAD" if direction == 1 else "SHORT_SPREAD",
            "spy_shares": spy_shrs, "qqq_shares": qqq_shrs,
            "entry_spy_price": round(entry_spy_p, 4),
            "entry_qqq_price": round(entry_qqq_p, 4),
            "exit_spy_price": round(spy_fill, 4),
            "exit_qqq_price": round(qqq_fill, 4),
            "pnl": round(pnl_net, 4),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(spy_ex_cost + qqq_ex_cost, 4),
            "total_cost": round(entry_cost_total + spy_ex_cost + qqq_ex_cost, 4),
            "liquidity_constrained": entry_liq,
            "entry_zscore": round(entry_z_val, 4),
            "exit_zscore": round(float(zscore_arr[last_i]) if not np.isnan(zscore_arr[last_i]) else 0.0, 4),
            "exit_reason": "END_OF_DATA",
            "hold_bars": last_i - entry_bar_idx,
        })

    # ── Final day record ──────────────────────────────────────────────────────
    if prev_date is not None:
        daily_pnl[prev_date] = capital

    if not daily_pnl:
        return trade_log, pd.Series(dtype=float), pd.DataFrame()

    equity_ts = pd.Series(daily_pnl).sort_index()
    daily_df = pd.DataFrame({"equity": equity_ts})
    return trade_log, equity_ts, daily_df


def _mark_to_market(
    capital: float, in_pos: bool, direction: int,
    spy_shrs: int, qqq_shrs: int,
    spy_close: float, qqq_close: float,
    entry_spy_p: float, entry_qqq_p: float,
) -> float:
    """Compute mark-to-market equity including open position."""
    if not in_pos:
        return capital
    if direction == 1:
        unrealized = (spy_close - entry_spy_p) * spy_shrs + (entry_qqq_p - qqq_close) * qqq_shrs
    else:
        unrealized = (entry_spy_p - spy_close) * spy_shrs + (qqq_close - entry_qqq_p) * qqq_shrs
    return capital + unrealized


# ── Performance Metrics ────────────────────────────────────────────────────────

def compute_metrics(
    trade_log: list,
    equity_ts: pd.Series,
    start: str,
    end: str,
) -> dict:
    """Compute standard Gate 1 v2.2 performance metrics from trades and equity curve."""
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    n_trades = len(trade_log)

    if not equity_ts.empty and len(equity_ts) > 1:
        daily_returns = equity_ts.pct_change().fillna(0.0)
        ret_arr = daily_returns.values
        mu = ret_arr.mean()
        sigma = ret_arr.std()
        sharpe = float(mu / sigma * np.sqrt(TRADING_DAYS_PER_YEAR)) if sigma > 1e-10 else 0.0
        cum = np.cumprod(1 + ret_arr)
        roll_max = np.maximum.accumulate(np.maximum(cum, 1e-10))
        drawdowns = (cum - roll_max) / roll_max
        mdd = float(np.min(drawdowns))
        total_return = float(cum[-1] - 1.0)
    else:
        daily_returns = pd.Series(dtype=float)
        sharpe = 0.0
        mdd = 0.0
        total_return = 0.0

    if n_trades > 0:
        trades_df = pd.DataFrame(trade_log)
        win_rate = float((trades_df["pnl"] > 0).mean())
        wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = float(wins / losses) if losses > 0 else float("inf")
        avg_pnl = float(trades_df["pnl"].mean())
        avg_cost = float(trades_df["total_cost"].mean())
        total_cost = float(trades_df["total_cost"].sum())
        gross_pnl = trades_df["pnl"].sum() + trades_df["total_cost"].sum()
        cost_ratio = total_cost / abs(gross_pnl) if abs(gross_pnl) > 1e-6 else 0.0
        exit_summary = trades_df["exit_reason"].value_counts().to_dict()
        trades_per_year = round(n_trades / max(years, 1e-3), 1)
    else:
        win_rate = profit_factor = avg_pnl = avg_cost = total_cost = cost_ratio = 0.0
        exit_summary = {}
        trades_per_year = 0.0

    # PpT in basis points (net PnL per trade / avg notional)
    avg_notional = (PARAMETERS["SPY_NOTIONAL"] + PARAMETERS["QQQ_NOTIONAL"])
    ppt_bps = (avg_pnl / avg_notional) * 10000 if avg_notional > 0 else 0.0

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "total_return": round(total_return, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "trades_per_wf_fold": round(n_trades / 4.0, 1),
        "avg_pnl_per_trade": round(avg_pnl, 4),
        "avg_cost_per_trade": round(avg_cost, 4),
        "total_cost": round(total_cost, 2),
        "ppt_bps": round(ppt_bps, 2),
        "cost_to_gross_ratio": round(cost_ratio, 4),
        "years": round(years, 2),
        "exit_reason_summary": exit_summary,
    }


# ── Public Interface ───────────────────────────────────────────────────────────

def run_backtest(
    start: str,
    end: str,
    params: dict = None,
    # Pre-loaded data (avoids re-downloading across multiple sweep runs)
    spy_rth_full: pd.DataFrame = None,
    qqq_rth_full: pd.DataFrame = None,
    spy_daily: pd.DataFrame = None,
    qqq_daily: pd.DataFrame = None,
    vix_close: pd.Series = None,
    cache_dir: str = None,
) -> dict:
    """
    Run a single H63 backtest for the given window and parameters.

    Pre-loaded data kwargs allow efficient parameter sweeps without re-downloading.
    Returns metrics dict with equity, trades, daily_df.
    """
    if params is None:
        params = PARAMETERS.copy()

    if any(v is None for v in [spy_rth_full, qqq_rth_full, spy_daily, qqq_daily, vix_close]):
        # Load data with warmup
        hedge_days = params.get("HEDGE_LOOKBACK_DAYS", 20)
        warmup_start = (
            pd.Timestamp(start) - pd.DateOffset(days=max(60, hedge_days * 3 + 30))
        ).strftime("%Y-%m-%d")

        if spy_rth_full is None or qqq_rth_full is None:
            spy_raw = fetch_minute_data("SPY", warmup_start, end, cache_dir=cache_dir)
            qqq_raw = fetch_minute_data("QQQ", warmup_start, end, cache_dir=cache_dir)
            spy_rth_full = filter_rth(spy_raw)
            qqq_rth_full = filter_rth(qqq_raw)

        if spy_daily is None or qqq_daily is None:
            spy_daily = _download_daily("SPY", warmup_start, end)
            qqq_daily = _download_daily("QQQ", warmup_start, end)

        if vix_close is None:
            vix_close = _download_vix(warmup_start, end)

    # Trim minute bars to [start, end]
    tz = "America/New_York"
    ts_start = pd.Timestamp(start).tz_localize(tz)
    ts_end = pd.Timestamp(end).tz_localize(tz).replace(hour=23, minute=59)

    spy_win = spy_rth_full[(spy_rth_full.index >= ts_start) & (spy_rth_full.index <= ts_end)].copy()
    qqq_win = qqq_rth_full[(qqq_rth_full.index >= ts_start) & (qqq_rth_full.index <= ts_end)].copy()

    if len(spy_win) < 100:
        raise ValueError(f"Insufficient SPY minute bars in {start}–{end}: {len(spy_win)}")

    # Prepare signals and run simulation
    sig_df = prepare_signals(spy_win, qqq_win, spy_daily, qqq_daily, vix_close, params)
    trade_log, equity_ts, daily_df = simulate(sig_df, params)

    metrics = compute_metrics(trade_log, equity_ts, start, end)
    metrics.update({
        "equity": equity_ts,
        "daily_df": daily_df,
        "trades": pd.DataFrame(trade_log) if trade_log else pd.DataFrame(),
        "params": params,
    })

    return metrics


# ── Data Download Helpers ──────────────────────────────────────────────────────

def _download_daily(ticker: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        raise ValueError(f"No daily data for {ticker} {start}–{end}")
    return df


def _download_vix(start: str, end: str) -> pd.Series:
    import yfinance as yf
    df = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        raise ValueError(f"No VIX data for {start}–{end}")
    return df["Close"]
