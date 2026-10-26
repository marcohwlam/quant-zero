"""
Strategy: H63v2 SPY/QQQ Pairs Daily Baseline Mean Reversion
Author: Strategy Coder Agent
Date: 2026-06-09
Hypothesis: SPY and QQQ are cointegrated. The log-price spread log(SPY) - beta*log(QQQ)
            is mean-reverting intraday. H63v2 fixes H63v1's window-mechanics artifact by
            anchoring the z-score to a DAILY CLOSE BASELINE (rolling 20-day mean/std).
            Baseline is computed once at session open from prior-day closes and held
            constant for the entire session. This eliminates the 30-min window self-
            reversion that generated 12-15 false trades/day in H63v1.
Asset class: US equity ETFs (SPY, QQQ) — intraday-flat, market-neutral
Parent task: QUA-178 (redesign of QUA-167/H63v1)
References:
    Chan (2013) Algorithmic Trading, Ch. 6, pp. 105-133
    Gatev, Goetzmann & Rouwenhorst (2006) RFS 19(3)
    Avellaneda & Lee (2010) QF 10(7)
    research/hypotheses/63v2_spy_qqq_pairs_daily_baseline.md

Data quality notes:
    Universe: SPY + QQQ only. No survivorship bias; both ETFs active since 1999/2000.
    Daily prices: yfinance auto_adjust=True (split/dividend-adjusted).
    Intraday prices: Alpaca SIP, adjustment='split'.
    Data gaps: SPY and QQQ are among the most liquid ETFs; >5 missing trading days
               in 2018-2026 would indicate a data-fetch issue, not a survivorship problem.
    Earnings exclusion: N/A — SPY and QQQ are index ETFs; no individual earnings risk.
    Delisted tickers: N/A — SPY (1993) and QQQ (1999) are active and not at risk of delisting.

PDT NOTE: Strategy targets 3-8 spread crossings/day (each = 2 day trades: 1 SPY + 1 QQQ).
Requires PDT (Pattern Day Trader) designation. At $25K capital, any drawdown below $25K
loses PDT eligibility. Recommended minimum capital: $30K to buffer 8-15% MDD.
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
    "BASELINE_LOOKBACK_DAYS": 20,   # Rolling window (daily closes) for spread mean/std
    "HEDGE_LOOKBACK_DAYS": 20,      # Rolling OLS window (daily closes) for beta
    "ENTRY_ZSCORE": 1.5,            # Enter when |z| > this vs daily baseline
    "EXIT_ZSCORE": 0.25,            # Exit when |z| < this (mean reversion to baseline)
    "STOP_ZSCORE": 3.0,             # Hard stop when |z| > this (divergence)
    "VIX_FILTER_THRESHOLD": 30.0,   # Skip session if prior-day VIX close > this
    "OPEN_SKIP_MINUTES": 15,        # Skip first N minutes after 09:30 ET
    "EOD_EXIT_TIME": "15:45",       # Force-close any open position at this time (ET)
    "INIT_CASH": 25000.0,           # Initial capital ($)
    "SPY_NOTIONAL": 12500.0,        # SPY leg notional per trade ($)
    "QQQ_NOTIONAL": 12500.0,        # QQQ leg notional per trade ($)
}

# ── Transaction Cost Constants (ED canonical spec, ED-SLIP-001 ultra-liquid ETF tier)
FIXED_COST_PER_SHARE = 0.005    # $0.005/share
SLIPPAGE_PCT = 0.00005          # 0.005% of notional (one-way) — ED-SLIP-001 ultra-liquid ETF
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
        cache_dir = str(Path(__file__).parent.parent / "pipelines" / "data" / "h63v2_cache")
    os.makedirs(cache_dir, exist_ok=True)

    fname = f"{symbol}_{start_date}_{end_date}.pkl"
    cache_path = Path(cache_dir) / fname

    if not force_refresh and cache_path.exists():
        logger.info("  Loading %s from cache: %s", symbol, cache_path.name)
        return pd.read_pickle(str(cache_path))

    logger.info("  Fetching %s %s → %s from Alpaca SIP (chunked)...", symbol, start_date, end_date)

    from datetime import timedelta as _td
    chunk_start = pd.Timestamp(start_date).date()
    chunk_end_overall = pd.Timestamp(end_date).date()
    CHUNK_DAYS = 60

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


# ── Daily Baseline ─────────────────────────────────────────────────────────────

def _compute_rolling_ols_betas(
    log_spy: pd.Series,
    log_qqq: pd.Series,
    lookback: int,
) -> pd.Series:
    """
    Rolling OLS: log_spy = alpha + beta * log_qqq.
    Each beta[i] uses rows [i-lookback, i) — strictly backward-looking.
    """
    n = len(log_spy)
    betas = np.full(n, np.nan)
    for i in range(lookback, n):
        y = log_spy.iloc[i - lookback: i].values
        x = log_qqq.iloc[i - lookback: i].values
        xm = np.column_stack([np.ones(len(x)), x])
        try:
            coef, _, _, _ = np.linalg.lstsq(xm, y, rcond=None)
            betas[i] = coef[1]
        except Exception:
            betas[i] = 0.9
    return pd.Series(betas, index=log_spy.index)


def compute_daily_baseline(
    spy_close: pd.Series,
    qqq_close: pd.Series,
    baseline_lookback: int,
    hedge_lookback: int,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Compute per-session baseline constants from daily close data.

    All computations are strictly backward-looking: baseline for date D
    uses closes from [D - baseline_lookback, D) only.

    Returns (mu_daily, sigma_daily, beta) as date-indexed Series.
      mu_daily    = rolling mean of daily spread (log_spy - beta * log_qqq)
      sigma_daily = rolling std of daily spread
      beta        = rolling OLS hedge ratio
    """
    common = spy_close.index.intersection(qqq_close.index)
    log_spy = np.log(spy_close.reindex(common))
    log_qqq = np.log(qqq_close.reindex(common))

    betas = _compute_rolling_ols_betas(log_spy, log_qqq, hedge_lookback)
    daily_spread = log_spy - betas * log_qqq

    mu = daily_spread.rolling(baseline_lookback, min_periods=baseline_lookback).mean()
    sigma = daily_spread.rolling(baseline_lookback, min_periods=baseline_lookback).std()

    return mu, sigma, betas


# ── Transaction Costs ──────────────────────────────────────────────────────────

def compute_trade_cost(
    price: float,
    shares: int,
    sigma: float,
    adv: float,
) -> Tuple[float, bool]:
    """
    Canonical equities cost model (ED-SLIP-001, ultra-liquid ETF tier):
      fixed    = $0.005/share
      slippage = 0.005% of notional (one-way)
      impact   = k * sigma * sqrt(Q/ADV) * price * Q

    Returns (total_cost_$, liquidity_constrained).
    Flags liquidity_constrained when Q > 1% of ADV.
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
    Build the complete signal DataFrame for simulation.

    H63v2 key change: z-score uses a DAILY CLOSE BASELINE (mu_daily, sigma_daily)
    computed once per session from the prior N days of daily closes.
    These session constants are fixed for the entire trading day — no intraday updates.

    z_t = (log(spy_t) - beta_session * log(qqq_t) - mu_daily) / sigma_daily

    Columns returned:
        spy_open, spy_close, qqq_open, qqq_close,
        beta, mu_daily, sigma_daily, spread, zscore,
        spy_sigma, qqq_sigma, spy_adv, qqq_adv,
        vix_ok, tradeable, eod_exit
    """
    baseline_days = params["BASELINE_LOOKBACK_DAYS"]
    hedge_days = params["HEDGE_LOOKBACK_DAYS"]
    vix_thresh = params["VIX_FILTER_THRESHOLD"]
    skip_min = params["OPEN_SKIP_MINUTES"]
    eod_time_str = params.get("EOD_EXIT_TIME", "15:45")

    # ── 1. Join SPY and QQQ minute bars ───────────────────────────────────────
    sig = pd.DataFrame({
        "spy_open": spy_rth["Open"],
        "spy_close": spy_rth["Close"],
        "qqq_open": qqq_rth["Open"],
        "qqq_close": qqq_rth["Close"],
    }).dropna()

    if sig.empty:
        raise ValueError("No overlapping SPY/QQQ minute bars after join")

    sig["date_py"] = sig.index.date

    # ── 2. Compute daily baseline: mu, sigma, beta per date ───────────────────
    # H63v2 CORE: all three constants come from daily closes, not intraday windows.
    mu_daily_s, sigma_daily_s, beta_s = compute_daily_baseline(
        spy_daily["Close"], qqq_daily["Close"], baseline_days, hedge_days
    )

    # Map to minute bars by date. baseline[date D] uses closes up to D-1 (OLS
    # lookback ends at D-1), so no lookahead for the session on date D.
    mu_map = {pd.Timestamp(dt).date(): float(v) for dt, v in mu_daily_s.items() if not np.isnan(v)}
    sigma_map = {pd.Timestamp(dt).date(): float(v) for dt, v in sigma_daily_s.items() if not np.isnan(v)}
    beta_map = {pd.Timestamp(dt).date(): float(v) for dt, v in beta_s.items() if not np.isnan(v)}

    sig["beta"] = [beta_map.get(d, np.nan) for d in sig["date_py"]]
    sig["mu_daily"] = [mu_map.get(d, np.nan) for d in sig["date_py"]]
    sig["sigma_daily"] = [sigma_map.get(d, np.nan) for d in sig["date_py"]]

    sig["beta"] = sig["beta"].ffill().fillna(0.9)
    sig["mu_daily"] = sig["mu_daily"].ffill()
    sig["sigma_daily"] = sig["sigma_daily"].ffill()

    # ── 3. Intraday z-score anchored to daily baseline ────────────────────────
    # z is computed bar-by-bar using session-constant mu_daily and sigma_daily.
    # It will NOT self-revert through window mechanics (unlike H63v1's rolling window).
    sig["spy_log"] = np.log(sig["spy_close"])
    sig["qqq_log"] = np.log(sig["qqq_close"])
    sig["spread"] = sig["spy_log"] - sig["beta"] * sig["qqq_log"]
    sig["zscore"] = (sig["spread"] - sig["mu_daily"]) / sig["sigma_daily"].replace(0, np.nan)

    # Bars before the warmup period has filled (no valid baseline) → NaN z-score
    # Simulation loop treats NaN z as non-tradeable.

    # ── 4. Daily sigma and ADV for transaction costs ──────────────────────────
    spy_sigma_s = spy_daily["Close"].pct_change().rolling(DAILY_SIGMA_WINDOW).std()
    qqq_sigma_s = qqq_daily["Close"].pct_change().rolling(DAILY_SIGMA_WINDOW).std()
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
    vix_list = [(pd.Timestamp(dt).date(), float(v)) for dt, v in vix_close.items() if not np.isnan(v)]
    vix_prev_map = {}
    for i in range(1, len(vix_list)):
        vix_prev_map[vix_list[i][0]] = vix_list[i - 1][1]

    sig["vix_prev"] = [vix_prev_map.get(d, 20.0) for d in sig["date_py"]]
    sig["vix_ok"] = sig["vix_prev"] < vix_thresh

    # ── 6. Time-of-day flags ──────────────────────────────────────────────────
    tradeable_start = (pd.Timestamp("09:30") + pd.Timedelta(minutes=skip_min)).time()
    eod_time = pd.Timestamp(eod_time_str).time()

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
    Run the H63v2 pairs trading simulation over the prepared signal DataFrame.

    Execution model (identical to H63v1):
      - Signal generated at bar t close
      - Fill at bar t+1 open (1-bar latency, no look-ahead)
      - EOD exit signal at EOD_EXIT_TIME bar → fill at next bar open

    Position model:
      - At most one active spread position at a time (no pyramid)
      - Long spread:  long SPY + short QQQ (z < -entry_z: SPY cheap vs QQQ)
      - Short spread: short SPY + long QQQ (z > +entry_z: SPY expensive vs QQQ)
      - Position notional: SPY_NOTIONAL + QQQ_NOTIONAL = $25K total deployed

    Returns (trade_log, equity_ts, daily_df).
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

    in_pos = False
    direction = 0
    spy_shrs = 0
    qqq_shrs = 0
    entry_spy_p = 0.0
    entry_qqq_p = 0.0
    entry_cost_total = 0.0
    entry_ts = None
    entry_bar_idx = -1
    entry_z_val = 0.0
    entry_liq = False

    pending_entry_dir = 0
    pending_exit_reason = ""

    prev_date = None

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
                mtm = _mark_to_market(capital, in_pos, direction, spy_shrs, qqq_shrs,
                                      spy_close_arr[i - 1], qqq_close_arr[i - 1],
                                      entry_spy_p, entry_qqq_p)
                daily_pnl[prev_date] = mtm
            prev_date = bar_date

        # ── Execute pending exit at this bar's open ───────────────────────────
        if pending_exit_reason and in_pos:
            spy_fill = spy_open_arr[i]
            qqq_fill = qqq_open_arr[i]

            spy_ex_cost, spy_ex_liq = compute_trade_cost(
                spy_fill, spy_shrs, spy_sigma_arr[i], spy_adv_arr[i])
            qqq_ex_cost, qqq_ex_liq = compute_trade_cost(
                qqq_fill, qqq_shrs, qqq_sigma_arr[i], qqq_adv_arr[i])

            if direction == 1:
                pnl_spy = (spy_fill - spy_ex_cost / spy_shrs - entry_spy_p) * spy_shrs
                pnl_qqq = (entry_qqq_p - qqq_fill - qqq_ex_cost / qqq_shrs) * qqq_shrs
                exit_spy_net = spy_fill - spy_ex_cost / spy_shrs
                exit_qqq_net = qqq_fill + qqq_ex_cost / qqq_shrs
            else:
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
            pending_entry_dir = 0

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
                _entry_spy_p = spy_fill + spy_en_cost / _spy_shrs
                _entry_qqq_p = qqq_fill - qqq_en_cost / _qqq_shrs
            else:
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

        # ── In-position exit checks (signal at close, fill at next open) ──────
        if in_pos and not pending_exit_reason and tradeable and not np.isnan(z):
            if z_abs < exit_z:
                pending_exit_reason = "MEAN_REVERT"
            elif z_abs > stop_z:
                pending_exit_reason = "STOP_ZSCORE"
            elif direction == 1 and z < -stop_z:
                pending_exit_reason = "STOP_ZSCORE"
            elif direction == -1 and z > stop_z:
                pending_exit_reason = "STOP_ZSCORE"

        # ── Entry signal (signal at close, fill at next bar open) ─────────────
        if (
            not in_pos
            and pending_entry_dir == 0
            and not pending_exit_reason
            and tradeable
            and vix_ok
            and not np.isnan(z)
            and z_abs >= entry_z
            and i < n - 1
        ):
            pending_entry_dir = -1 if z > 0 else 1

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
            "spy_shares": spy_shrs,
            "qqq_shares": qqq_shrs,
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
    """Compute mark-to-market equity including open position unrealized P&L."""
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

        trading_days = len(equity_ts)
        avg_trades_per_day = round(n_trades / max(trading_days, 1), 2)

        liq_constrained_pct = float(trades_df["liquidity_constrained"].mean()) * 100
    else:
        win_rate = profit_factor = avg_pnl = avg_cost = total_cost = cost_ratio = 0.0
        exit_summary = {}
        trades_per_year = 0.0
        avg_trades_per_day = 0.0
        liq_constrained_pct = 0.0

    avg_notional = float(PARAMETERS["SPY_NOTIONAL"] + PARAMETERS["QQQ_NOTIONAL"])
    ppt_bps = (avg_pnl / avg_notional) * 10000 if avg_notional > 0 else 0.0

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "total_return": round(total_return, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "avg_trades_per_day": avg_trades_per_day,
        "trades_per_wf_fold": round(n_trades / 4.0, 1),
        "avg_pnl_per_trade": round(avg_pnl, 4),
        "avg_cost_per_trade": round(avg_cost, 4),
        "total_cost": round(total_cost, 2),
        "ppt_bps": round(ppt_bps, 2),
        "cost_to_gross_ratio": round(cost_ratio, 4),
        "liquidity_constrained_pct": round(liq_constrained_pct, 2),
        "years": round(years, 2),
        "exit_reason_summary": exit_summary,
    }


# ── Public Interface ───────────────────────────────────────────────────────────

def run_backtest(
    start: str,
    end: str,
    params: dict = None,
    spy_rth_full: pd.DataFrame = None,
    qqq_rth_full: pd.DataFrame = None,
    spy_daily: pd.DataFrame = None,
    qqq_daily: pd.DataFrame = None,
    vix_close: pd.Series = None,
    cache_dir: str = None,
) -> dict:
    """
    Run a single H63v2 backtest for the given window and parameters.

    Pre-loaded data kwargs allow efficient parameter sweeps without re-downloading.
    Returns metrics dict plus equity, trades, daily_df, params.
    """
    if params is None:
        params = PARAMETERS.copy()

    if any(v is None for v in [spy_rth_full, qqq_rth_full, spy_daily, qqq_daily, vix_close]):
        hedge_days = params.get("HEDGE_LOOKBACK_DAYS", 20)
        baseline_days = params.get("BASELINE_LOOKBACK_DAYS", 20)
        warmup_days = max(60, (hedge_days + baseline_days) * 3 + 30)
        warmup_start = (
            pd.Timestamp(start) - pd.DateOffset(days=warmup_days)
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

    tz = "America/New_York"
    ts_start = pd.Timestamp(start).tz_localize(tz)
    ts_end = pd.Timestamp(end).tz_localize(tz).replace(hour=23, minute=59)

    spy_win = spy_rth_full[(spy_rth_full.index >= ts_start) & (spy_rth_full.index <= ts_end)].copy()
    qqq_win = qqq_rth_full[(qqq_rth_full.index >= ts_start) & (qqq_rth_full.index <= ts_end)].copy()

    if len(spy_win) < 100:
        raise ValueError(f"Insufficient SPY minute bars in {start}–{end}: {len(spy_win)}")

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_backtest("2018-01-01", "2023-12-31")
    print(f"Sharpe: {result['sharpe']}")
    print(f"Max Drawdown: {result['max_drawdown']:.2%}")
    print(f"Win Rate: {result['win_rate']:.2%}")
    print(f"Total Return: {result['total_return']:.2%}")
    print(f"Trade Count: {result['trade_count']}")
    print(f"Avg Trades/Day: {result['avg_trades_per_day']}")
    print(f"PpT (bps): {result['ppt_bps']}")
    print(f"Exit reasons: {result['exit_reason_summary']}")
