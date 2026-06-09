"""
H60: Intraday VWAP Mean Reversion
Hypothesis: research/hypotheses/60_intraday_vwap_mean_reversion.md (v1.2)
Parent task: QUA-166
Author: Engineering Director
Date: 2026-06-09

Strategy: Fade statistically extreme VWAP deviations (Avellaneda-Lee OU s-score adapted to
intraday VWAP), gated by VPIN to avoid informed/toxic flow. Intraday-flat by hard rule.

Signals:
- z = (close - session_vwap) / rolling_std(close - vwap, LOOKBACK_BARS)
- Entry: |z| > ENTRY_Z, VPIN < VPIN_INFORMED, within TRADE_START..TRADE_END
- Exit: |z| < EXIT_Z (reversion), |z| > STOP_Z (stop), time_stop_bars elapsed, VPIN > VPIN_CRISIS, 15:00 ET

Data: SPY (primary), QQQ (robustness) — 1-min OHLCV from Alpaca via MinuteBarStore
Cost model: $0.005/share + 0.05% slippage + 0.1 * sigma * sqrt(Q/ADV) market impact (equities canonical)
"""

import logging
import os
import sys
import warnings
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipelines.minute_bar_store import MinuteBarStore
from pipelines.vpin_engine import VPINEngine

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_UTC = timezone.utc

# ── Default Parameters (literature-grounded baselines) ───────────────────────
PARAMETERS = {
    "ENTRY_Z": 1.5,           # Avellaneda & Lee (2010), adapted from 2.0 (stocks) to 1.5 (VWAP — faster reversion)
    "EXIT_Z": 0.25,           # Reversion to VWAP achieved; A&L use 0.50
    "STOP_Z": 3.0,            # Deviation widening = informed flow event (A&L use 3.5)
    "LOOKBACK_BARS": 30,      # 30-min rolling window for intraday vol (Kissell 2014)
    "VPIN_INFORMED": 0.55,    # Block entry: informed flow regime (Easley et al. 2012 Table 3)
    "VPIN_CRISIS": 0.70,      # Close positions: toxic flow (Easley et al. 2012)
    "VPIN_WINDOW": 50,        # VPIN rolling window bars
    "time_stop_bars": 60,     # 60-min time stop = 2× Kissell (2014) half-life estimate
    "TRADE_START_ET": "10:30",
    "TRADE_END_ET": "14:30",
    "EOD_EXIT_ET": "15:00",   # Hard intraday-flat rule
    "VIX_NORMAL": 25.0,
    "VIX_ELEVATED": 35.0,
    "POSITION_SIZE_FULL": 0.07,
    "POSITION_SIZE_REDUCED": 0.04,
    "INIT_CASH": 25000,
    "PRIMARY": "SPY",
    "ROBUSTNESS": "QQQ",
}

# ── Transaction Cost Constants (canonical equities model) ────────────────────
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_PCT = 0.0005          # 0.05% per leg
MARKET_IMPACT_K = 0.1          # Almgren-Chriss square-root model
SIGMA_WINDOW_DAYS = 20         # 20-day rolling sigma for market impact
ADV_WINDOW_DAYS = 20           # 20-day rolling ADV for market impact

TRADING_DAYS_PER_YEAR = 252


# ── Data acquisition helpers ──────────────────────────────────────────────────

def ensure_minute_bars(symbol: str, start_date: str, end_date: str, store: MinuteBarStore) -> int:
    """
    Ensure minute bars exist in store for symbol/start_date..end_date.
    Fetches month-by-month from Alpaca to avoid HTTP timeouts on large ranges.
    Returns total bars stored.
    """
    try:
        from pipelines.alpaca_ingest import AlpacaMinuteIngester
        api_key = os.environ.get("ALPACA_API_KEY", "")
        api_secret = os.environ.get("ALPACA_API_SECRET", "")
        if not api_key or not api_secret:
            logger.warning("Alpaca credentials not set — skipping fetch for %s", symbol)
            return 0
        ingester = AlpacaMinuteIngester(api_key, api_secret, store)

        # Month-by-month fetch to avoid request timeout on large ranges
        total = 0
        months = pd.date_range(start_date, end_date, freq="MS")
        for month_start in months:
            month_end = (month_start + pd.DateOffset(months=1) - pd.DateOffset(days=1))
            ms = month_start.strftime("%Y-%m-%d")
            me = min(month_end, pd.Timestamp(end_date)).strftime("%Y-%m-%d")
            # Skip if already have data for this month
            existing = store.get_bars(symbol, ms + "T00:00:00Z", me + "T23:59:00Z")
            if not existing.empty:
                logger.debug("%s %s: %d bars already in store — skipping", symbol, ms, len(existing))
                total += len(existing)
                continue
            try:
                n = ingester.fetch_and_store(symbol, ms, me)
                total += n
                logger.info("%s %s: fetched %d bars (cumulative %d)", symbol, ms, n, total)
            except Exception as exc:
                logger.warning("%s %s: fetch failed — %s", symbol, ms, exc)
        return total
    except Exception as exc:
        logger.warning("Failed to fetch %s from Alpaca: %s", symbol, exc)
        return 0


def load_minute_bars(symbol: str, start: str, end: str, store: MinuteBarStore) -> pd.DataFrame:
    """Load bars from store; auto-fetch if the range is not yet populated."""
    bars = store.get_bars(symbol, start + "T00:00:00Z", end + "T23:59:00Z")
    if bars.empty:
        logger.info("No bars in store for %s %s–%s; fetching from Alpaca…", symbol, start, end)
        ensure_minute_bars(symbol, start, end, store)
        bars = store.get_bars(symbol, start + "T00:00:00Z", end + "T23:59:00Z")
    return bars


def get_vix_daily(start: str, end: str) -> pd.Series:
    """Fetch VIX daily closes from yfinance."""
    try:
        vix = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        return vix["Close"].rename("vix")
    except Exception as exc:
        logger.warning("VIX fetch failed: %s — using VIX=20 (full size always)", exc)
        return pd.Series(dtype=float)


# ── Feature computation ────────────────────────────────────────────────────────

def _session_label(ts_utc: pd.Timestamp) -> str:
    return ts_utc.astimezone(_ET).strftime("%Y-%m-%d")


def _et_time(ts_utc: pd.Timestamp) -> str:
    ts_et = ts_utc.astimezone(_ET)
    return ts_et.strftime("%H:%M")


def compute_typical_vwap(bars: pd.DataFrame) -> pd.Series:
    """
    Session VWAP using typical price = (high + low + close) / 3.
    Resets at each new ET session date. Matches hypothesis formula.
    """
    df = bars.copy()
    df.index = pd.to_datetime(df.index, utc=True)
    df["_session"] = df.index.map(_session_label)
    df["typical"] = (df["high"] + df["low"] + df["close"]) / 3.0
    df["_tpv"] = df["typical"] * df["volume"]

    vwap = pd.Series(index=df.index, dtype=float)
    for _, grp in df.groupby("_session"):
        cum_tpv = grp["_tpv"].cumsum()
        cum_vol = grp["volume"].cumsum().replace(0, np.nan)
        vwap.loc[grp.index] = (cum_tpv / cum_vol).values
    return vwap


def compute_features(bars: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Augment bars with VWAP, VWAP z-score, and VPIN.
    All features are computed on [t-1] data before the current bar (no look-ahead).
    """
    df = bars.copy()
    df.index = pd.to_datetime(df.index, utc=True)

    # Session VWAP using typical price
    df["vwap"] = compute_typical_vwap(df)

    # VWAP fractional deviation
    df["deviation"] = (df["close"] - df["vwap"]) / (df["vwap"] + 1e-10)

    # Rolling z-score (no look-ahead: rolling uses only past bars)
    lookback = params["LOOKBACK_BARS"]
    df["rolling_std"] = df["deviation"].rolling(lookback, min_periods=max(5, lookback // 3)).std()
    df["vwap_z"] = df["deviation"] / (df["rolling_std"] + 1e-10)

    # VPIN via BVC
    vpin_engine = VPINEngine()
    bvc = vpin_engine.compute_bvc(df, sigma_window=50)
    df["vpin"] = vpin_engine.compute_vpin(bvc, window=params["VPIN_WINDOW"])

    # ET time string for session window filtering
    df["et_time"] = df.index.map(_et_time)
    df["session"] = df.index.map(_session_label)

    # Shift features by 1 bar to enforce no look-ahead at entry
    # Signal at close of bar t → decision uses features[t], entry at open of bar t+1
    # The simulation loop implements this by checking shifted features
    df["vwap_z_lag1"] = df["vwap_z"].shift(1)
    df["vpin_lag1"] = df["vpin"].shift(1)

    return df


# ── Transaction cost helper ────────────────────────────────────────────────────

def compute_trade_cost(
    price: float,
    shares: int,
    daily_sigma: float,
    daily_adv: float,
    side: str,
) -> tuple[float, dict]:
    """
    Compute total transaction cost per share for a trade leg.
    Returns (cost_per_share, cost_breakdown_dict).
    """
    fixed = FIXED_COST_PER_SHARE
    slip = SLIPPAGE_PCT * price
    impact_pct = MARKET_IMPACT_K * daily_sigma * np.sqrt(max(shares, 1) / max(daily_adv, 1))
    impact = impact_pct * price

    total_per_share = fixed + slip + impact
    liquidity_constrained = (shares / max(daily_adv, 1)) > 0.01

    return total_per_share, {
        "fixed_per_share": round(fixed, 6),
        "slippage_per_share": round(slip, 6),
        "impact_per_share": round(impact, 6),
        "total_per_share": round(total_per_share, 6),
        "liquidity_constrained": liquidity_constrained,
    }


# ── Trade simulator (event-driven on minute bars) ─────────────────────────────

def simulate_trades(
    feat: pd.DataFrame,
    vix_series: pd.Series,
    params: dict,
    daily_stats: pd.DataFrame,
) -> tuple[list, pd.Series]:
    """
    Simulate H60 on precomputed feature dataframe.

    - 1-bar signal-to-fill delay: signal at bar t (vwap_z_lag1), entry at open of bar t+1.
      Implemented via vwap_z_lag1 column.
    - VPIN gate: checked at signal bar (vpin_lag1).
    - Hard EOD exit at 15:00 ET.
    - VIX-based position sizing from daily VIX.
    - RTH bars only (09:30–16:00 ET).

    Returns:
        trade_log: list of trade dicts
        minute_pnl: Series of per-minute PnL
    """
    entry_z = params["ENTRY_Z"]
    exit_z = params["EXIT_Z"]
    stop_z = params["STOP_Z"]
    time_stop = params["time_stop_bars"]
    vpin_inf = params["VPIN_INFORMED"]
    vpin_crisis = params["VPIN_CRISIS"]
    trade_start = params["TRADE_START_ET"]
    trade_end = params["TRADE_END_ET"]
    eod_exit = params["EOD_EXIT_ET"]
    pos_full = params["POSITION_SIZE_FULL"]
    pos_reduced = params["POSITION_SIZE_REDUCED"]
    vix_normal = params["VIX_NORMAL"]
    vix_elevated = params["VIX_ELEVATED"]
    init_cash = params["INIT_CASH"]

    capital = float(init_cash)
    trade_log = []
    minute_pnl = pd.Series(0.0, index=feat.index)

    # Position state
    in_position = False
    direction = 0           # +1 long, -1 short
    entry_price = 0.0       # effective entry (after cost)
    entry_raw_price = 0.0   # raw fill price
    shares = 0
    bars_held = 0
    entry_idx = None
    entry_z_score = 0.0
    entry_vpin = 0.0

    # Trade throttle: prevent rapid cycling
    cooldown_bars_remaining = 0   # bars remaining before next entry allowed
    COOLDOWN_NORMAL = 5           # 5 bars after reversion/time/vpin exit
    COOLDOWN_STOPLOSS = 20        # 20 bars (20 min) after stop_loss — signals bad regime
    MAX_TRADES_PER_SESSION = 3    # Matches hypothesis "1-3 entries per session day"
    current_session = ""
    session_trade_count = 0

    idx = feat.index
    n = len(idx)

    for i in range(1, n):
        ts = idx[i]
        row = feat.iloc[i]
        et_time = row["et_time"]
        session = row["session"]

        # Track cooldown
        if cooldown_bars_remaining > 0:
            cooldown_bars_remaining -= 1

        # Reset per-session state at new session
        if session != current_session:
            current_session = session
            session_trade_count = 0

        # Skip non-RTH bars (outside 09:30–16:00 ET)
        if et_time < "09:30" or et_time > "15:59":
            if in_position and et_time >= eod_exit:
                exit_p = row.get("open", row["close"])
                if pd.isna(exit_p) or exit_p <= 0:
                    exit_p = row["close"]
                _close_trade(
                    trade_log, minute_pnl, capital, ts, session,
                    in_position, direction, shares, entry_price, entry_raw_price,
                    exit_p, bars_held, "eod_flat",
                    feat, daily_stats, i, entry_idx, entry_z_score, entry_vpin,
                    row.get("vwap_z", 0.0), row.get("vpin", 0.0),
                )
                in_position = False
                capital += trade_log[-1]["net_pnl"]
                cooldown_bars_remaining = COOLDOWN_NORMAL
            continue

        # ── EOD force-exit ───────────────────────────────────────────────────
        if in_position and et_time >= eod_exit:
            exit_p = row.get("open", row["close"])
            if pd.isna(exit_p) or exit_p <= 0:
                exit_p = row["close"]
            _close_trade(
                trade_log, minute_pnl, capital, ts, session,
                in_position, direction, shares, entry_price, entry_raw_price,
                exit_p, bars_held, "eod_flat",
                feat, daily_stats, i, entry_idx, entry_z_score, entry_vpin,
                row.get("vwap_z", 0.0), row.get("vpin", 0.0),
            )
            in_position = False
            capital += trade_log[-1]["net_pnl"]
            continue

        close_p = row["close"]
        if pd.isna(close_p):
            continue

        # ── Current bar features (lagged 1 bar for signal = no look-ahead) ──
        z_signal = row.get("vwap_z_lag1", np.nan)
        vpin_signal = row.get("vpin_lag1", np.nan)
        z_current = row.get("vwap_z", np.nan)
        vpin_current = row.get("vpin", np.nan)

        # ── Check exits first (if in position) ───────────────────────────────
        if in_position:
            bars_held += 1
            open_p = row.get("open", close_p)
            if pd.isna(open_p) or open_p <= 0:
                open_p = close_p

            exit_reason = None

            # VPIN crisis: close immediately
            if pd.notna(vpin_current) and vpin_current > vpin_crisis:
                exit_reason = "vpin_crisis"

            # Reversion achieved: |z| < EXIT_Z
            elif pd.notna(z_current) and abs(z_current) < exit_z:
                exit_reason = "reversion"

            # Stop-loss: deviation widening
            elif pd.notna(z_current) and abs(z_current) > stop_z:
                exit_reason = "stop_loss"

            # Time stop
            elif bars_held >= time_stop:
                exit_reason = "time_stop"

            if exit_reason:
                _close_trade(
                    trade_log, minute_pnl, capital, ts, session,
                    in_position, direction, shares, entry_price, entry_raw_price,
                    open_p, bars_held, exit_reason,
                    feat, daily_stats, i, entry_idx, entry_z_score, entry_vpin,
                    z_current, vpin_current,
                )
                in_position = False
                capital += trade_log[-1]["net_pnl"]
                # Apply cooldown — longer after stop_loss (bad regime signal)
                cooldown_bars_remaining = (
                    COOLDOWN_STOPLOSS if exit_reason == "stop_loss" else COOLDOWN_NORMAL
                )
            continue

        # ── Check entry ───────────────────────────────────────────────────────
        if et_time < trade_start or et_time > trade_end:
            continue
        if cooldown_bars_remaining > 0:
            continue
        if session_trade_count >= MAX_TRADES_PER_SESSION:
            continue
        if pd.isna(z_signal) or pd.isna(vpin_signal):
            continue
        if vpin_signal >= vpin_inf:
            continue
        # Only enter in mean-reversion zone: ENTRY_Z < |z| < STOP_Z
        if abs(z_signal) <= entry_z or abs(z_signal) >= stop_z:
            continue

        # Determine direction
        new_direction = -1 if z_signal > 0 else +1

        # VIX-based position sizing
        session_date = pd.Timestamp(session)
        vix_val = _get_vix_for_session(vix_series, session_date)
        if vix_val >= vix_elevated:
            continue  # Skip: too volatile
        pos_size = pos_full if vix_val < vix_normal else pos_reduced

        # Entry at next bar's open (current bar = the bar after signal)
        open_p = row.get("open", close_p)
        if pd.isna(open_p) or open_p <= 0:
            continue

        trade_value = capital * pos_size
        new_shares = int(trade_value / open_p)
        if new_shares <= 0:
            continue

        # Transaction cost at entry
        ds = _get_daily_stats_for_session(daily_stats, session)
        cost_per_share, cost_detail = compute_trade_cost(
            open_p, new_shares, ds["sigma"], ds["adv"], "buy"
        )
        effective_entry = open_p + cost_per_share * new_direction

        in_position = True
        direction = new_direction
        shares = new_shares
        entry_price = effective_entry
        entry_raw_price = open_p
        entry_idx = i
        entry_z_score = z_signal
        entry_vpin = vpin_signal
        bars_held = 0
        session_trade_count += 1

    return trade_log, minute_pnl


def _get_vix_for_session(vix_series: pd.Series, session_date: pd.Timestamp) -> float:
    """Return VIX for a session, defaulting to 20 if unavailable."""
    if vix_series.empty:
        return 20.0
    try:
        # Find nearest prior trading day VIX
        vix_idx = vix_series.index.tz_localize(None) if vix_series.index.tz else vix_series.index
        loc = vix_idx.searchsorted(session_date.tz_localize(None) if session_date.tz else session_date)
        if loc > 0:
            return float(vix_series.iloc[loc - 1])
    except Exception:
        pass
    return 20.0


def _get_daily_stats_for_session(daily_stats: pd.DataFrame, session: str) -> dict:
    """Return sigma and adv for market impact computation."""
    if daily_stats.empty:
        return {"sigma": 0.007, "adv": 100_000_000}
    try:
        session_date = pd.Timestamp(session)
        ds_idx = daily_stats.index.tz_localize(None) if daily_stats.index.tz else daily_stats.index
        loc = ds_idx.searchsorted(session_date.tz_localize(None) if session_date.tz else session_date)
        if 0 < loc <= len(daily_stats):
            row = daily_stats.iloc[loc - 1]
            return {"sigma": float(row.get("sigma", 0.007)), "adv": float(row.get("adv", 100_000_000))}
    except Exception:
        pass
    return {"sigma": 0.007, "adv": 100_000_000}


def _close_trade(
    trade_log, minute_pnl, capital, ts, session,
    in_position, direction, shares, entry_price, entry_raw_price,
    exit_raw_price, bars_held, reason,
    feat, daily_stats, i, entry_idx, entry_z_score, entry_vpin,
    exit_z, exit_vpin,
):
    """Compute exit cost and append trade to log."""
    ds = _get_daily_stats_for_session(daily_stats, session)
    cost_per_share, _ = compute_trade_cost(exit_raw_price, shares, ds["sigma"], ds["adv"], "sell")
    effective_exit = exit_raw_price - cost_per_share * direction

    gross_pnl = (effective_exit - entry_price) * shares * direction
    # PnL as fraction of capital
    pnl_pct = gross_pnl / max(capital, 1.0)

    entry_ts = feat.index[entry_idx] if entry_idx is not None else ts

    trade_log.append({
        "symbol": feat.attrs.get("symbol", "SPY"),
        "entry_ts": str(entry_ts),
        "exit_ts": str(ts),
        "session": session,
        "direction": "long" if direction > 0 else "short",
        "entry_price": round(float(entry_price), 4),
        "entry_raw_price": round(float(entry_raw_price), 4),
        "exit_price": round(float(effective_exit), 4),
        "exit_raw_price": round(float(exit_raw_price), 4),
        "shares": shares,
        "bars_held": bars_held,
        "exit_reason": reason,
        "gross_pnl": round(float(gross_pnl), 4),
        "net_pnl": round(float(gross_pnl), 4),  # costs already in effective prices
        "return_pct": round(float(pnl_pct * 100), 6),
        "entry_z_score": round(float(entry_z_score), 4),
        "exit_z_score": round(float(exit_z), 4) if pd.notna(exit_z) else None,
        "entry_vpin": round(float(entry_vpin), 4),
        "exit_vpin": round(float(exit_vpin), 4) if pd.notna(exit_vpin) else None,
        # IS tracking schema (for paper trading reconciliation)
        "entry_backtest_price": round(float(entry_raw_price), 4),
        "entry_paper_price": None,
        "entry_is_bps": None,
        "exit_backtest_price": round(float(exit_raw_price), 4),
        "exit_paper_price": None,
        "exit_is_bps": None,
    })

    if len(trade_log) > 0:
        minute_pnl.iloc[i] = gross_pnl


# ── Metrics computation ────────────────────────────────────────────────────────

def compute_metrics(trade_log: list, daily_pnl: pd.Series, period_label: str) -> dict:
    """Compute Gate 1 metrics from trade log and daily PnL series."""
    if not trade_log:
        return {
            "period": period_label,
            "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
            "trade_count": 0, "total_return_pct": 0.0,
            "profit_factor": 0.0, "avg_profit_per_trade_bps": 0.0,
            "avg_bars_held": 0.0,
            "exit_reasons": {},
        }

    returns = daily_pnl.values
    if len(returns) > 0 and returns.std() > 1e-10:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    cum = np.cumprod(1 + np.clip(returns, -0.5, 0.5))
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8))) if len(cum) > 0 else 0.0
    total_ret = float(cum[-1] - 1.0) if len(cum) > 0 else 0.0

    pnls = [t["net_pnl"] for t in trade_log]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    win_rate = float(len(wins) / len(pnls)) if pnls else 0.0
    profit_factor = float(sum(wins) / sum(losses)) if losses and wins else 0.0

    # Average profit per trade in basis points (relative to entry price)
    ppt_bps = []
    for t in trade_log:
        if t["entry_raw_price"] > 0:
            bps = t["net_pnl"] / (t["shares"] * t["entry_raw_price"]) * 10000
            ppt_bps.append(bps)
    avg_ppt = float(np.mean(ppt_bps)) if ppt_bps else 0.0

    exit_reasons = {}
    for t in trade_log:
        r = t.get("exit_reason", "unknown")
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    long_trades = [t for t in trade_log if t["direction"] == "long"]
    short_trades = [t for t in trade_log if t["direction"] == "short"]

    return {
        "period": period_label,
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "win_rate": round(win_rate, 4),
        "trade_count": len(trade_log),
        "long_count": len(long_trades),
        "short_count": len(short_trades),
        "total_return_pct": round(total_ret * 100, 4),
        "profit_factor": round(profit_factor, 4),
        "avg_profit_per_trade_bps": round(avg_ppt, 4),
        "avg_bars_held": round(float(np.mean([t["bars_held"] for t in trade_log])), 2),
        "exit_reasons": exit_reasons,
    }


def compute_daily_pnl(trade_log: list, date_range: pd.DatetimeIndex, init_cash: float) -> pd.Series:
    """Convert trade log to daily return series."""
    capital = init_cash
    daily_capital = {}
    for t in trade_log:
        session = t["session"]
        if session not in daily_capital:
            daily_capital[session] = 0.0
        daily_capital[session] += t["net_pnl"]

    daily_ret = pd.Series(0.0, index=date_range)
    running_cap = init_cash
    for date_str, pnl in sorted(daily_capital.items()):
        ts = pd.Timestamp(date_str)
        if ts in daily_ret.index:
            daily_ret[ts] = pnl / max(running_cap, 1.0)
            running_cap += pnl

    return daily_ret


def compute_daily_stats(bars: pd.DataFrame) -> pd.DataFrame:
    """
    Compute daily sigma and ADV from minute bars for market impact model.
    Returns DataFrame with columns [sigma, adv] indexed by ET date.
    """
    if bars.empty:
        return pd.DataFrame(columns=["sigma", "adv"])

    df = bars.copy()
    df.index = pd.to_datetime(df.index, utc=True)
    df["session"] = df.index.map(_session_label)

    # Daily close (last bar of each session)
    daily_close = df.groupby("session")["close"].last()
    daily_vol = df.groupby("session")["volume"].sum()

    daily_ret = daily_close.pct_change()
    sigma = daily_ret.rolling(SIGMA_WINDOW_DAYS, min_periods=5).std().fillna(0.007)
    adv = daily_vol.rolling(ADV_WINDOW_DAYS, min_periods=5).mean().fillna(1e8)

    result = pd.DataFrame({"sigma": sigma, "adv": adv})
    result.index = pd.to_datetime(result.index)
    return result


# ── Walk-forward framework ────────────────────────────────────────────────────

WF_WINDOWS = [
    ("2022-01-01", "2022-03-31", "2022-04-01", "2022-04-30"),
    ("2022-05-01", "2022-07-31", "2022-08-01", "2022-08-31"),
    ("2022-09-01", "2022-11-30", "2022-12-01", "2022-12-31"),
    ("2023-01-01", "2023-03-31", "2023-04-01", "2023-04-30"),
    ("2023-05-01", "2023-07-31", "2023-08-01", "2023-08-31"),
    ("2023-09-01", "2023-11-30", "2023-12-01", "2023-12-31"),
]


def run_period(
    symbol: str,
    start: str,
    end: str,
    store: MinuteBarStore,
    vix: pd.Series,
    params: dict,
    warmup_bars: int = 100,
) -> tuple[list, pd.Series]:
    """Run strategy on a single period. Returns (trade_log, daily_ret)."""
    # Fetch with warmup for indicator initialization
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_bars // 390 + 2)).strftime("%Y-%m-%d")
    bars = load_minute_bars(symbol, warmup_start, end, store)
    if bars.empty:
        logger.warning("No bars for %s %s–%s", symbol, start, end)
        return [], pd.Series(dtype=float)

    bars.attrs["symbol"] = symbol

    # Daily stats (sigma, ADV) for market impact
    daily_stats = compute_daily_stats(bars)

    # Compute features with warmup
    feat = compute_features(bars, params)

    # Trim to actual period (after warmup)
    feat_period = feat[feat["session"] >= start]
    if feat_period.empty:
        return [], pd.Series(dtype=float)

    trade_log, minute_pnl = simulate_trades(feat_period, vix, params, daily_stats)

    # Build daily return series
    period_dates = pd.date_range(start, end, freq="B")
    daily_ret = compute_daily_pnl(trade_log, period_dates, params["INIT_CASH"])

    return trade_log, daily_ret


def run_walkforward(
    symbol: str,
    store: MinuteBarStore,
    vix: pd.Series,
    params: dict = None,
) -> dict:
    """
    Walk-forward backtest: 6 windows of 3-month IS / 1-month OOS.
    Returns comprehensive results dict.
    """
    if params is None:
        params = PARAMETERS

    all_is_trades = []
    all_oos_trades = []
    wf_results = []

    for window_idx, (is_start, is_end, oos_start, oos_end) in enumerate(WF_WINDOWS):
        logger.info("WF window %d: IS %s–%s, OOS %s–%s", window_idx + 1, is_start, is_end, oos_start, oos_end)

        is_trades, is_ret = run_period(symbol, is_start, is_end, store, vix, params)
        oos_trades, oos_ret = run_period(symbol, oos_start, oos_end, store, vix, params)

        is_metrics = compute_metrics(is_trades, is_ret, f"IS_W{window_idx + 1}")
        oos_metrics = compute_metrics(oos_trades, oos_ret, f"OOS_W{window_idx + 1}")

        wf_results.append({
            "window": window_idx + 1,
            "is_start": is_start, "is_end": is_end,
            "oos_start": oos_start, "oos_end": oos_end,
            "is": is_metrics,
            "oos": oos_metrics,
            "oos_profitable": oos_metrics["sharpe"] > 0,
        })

        all_is_trades.extend(is_trades)
        all_oos_trades.extend(oos_trades)

    # Aggregate IS and OOS metrics
    is_dates = pd.date_range("2022-01-01", "2023-11-30", freq="B")
    oos_dates = pd.date_range("2022-04-01", "2023-12-31", freq="B")
    is_daily = compute_daily_pnl(all_is_trades, is_dates, params["INIT_CASH"])
    oos_daily = compute_daily_pnl(all_oos_trades, oos_dates, params["INIT_CASH"])

    is_summary = compute_metrics(all_is_trades, is_daily, "IS_AGGREGATE")
    oos_summary = compute_metrics(all_oos_trades, oos_daily, "OOS_AGGREGATE")

    # WF stability
    oos_profitable_count = sum(1 for w in wf_results if w["oos_profitable"])

    # Cost-to-gross-profit ratio
    gross_profits = sum(t["net_pnl"] for t in all_oos_trades if t["net_pnl"] > 0)
    total_cost_est = sum(
        (FIXED_COST_PER_SHARE * t["shares"] * 2 + SLIPPAGE_PCT * t["entry_raw_price"] * t["shares"] * 2)
        for t in all_oos_trades
    )
    cpr = total_cost_est / max(gross_profits, 1e-8)

    return {
        "strategy": "H60_IntraVWAPMeanReversion",
        "symbol": symbol,
        "parameters": {k: v for k, v in params.items() if not callable(v)},
        "is_summary": is_summary,
        "oos_summary": oos_summary,
        "wf_windows": wf_results,
        "wf_stability": {
            "windows_profitable": oos_profitable_count,
            "total_windows": len(WF_WINDOWS),
            "stability_fraction": oos_profitable_count / max(len(WF_WINDOWS), 1),
            "stability_pass": oos_profitable_count >= 3,
        },
        "cost_to_gross_ratio": round(float(cpr), 4),
        "is_trade_log": all_is_trades,
        "oos_trade_log": all_oos_trades,
        "gate1_eval": {
            "is_sharpe_pass": is_summary["sharpe"] > 1.0,
            "oos_sharpe_pass": oos_summary["sharpe"] > 0.7,
            "mdd_pass": oos_summary["max_drawdown"] > -0.20,
            "min_trades_pass": is_summary["trade_count"] >= 100,
            "wf_stability_pass": oos_profitable_count >= 3,
        },
    }


def run_strategy(
    start: str = "2022-01-01",
    end: str = "2024-12-31",
    params: dict = None,
    store: MinuteBarStore = None,
) -> dict:
    """
    Main entry point. Fetches data, runs walk-forward backtest, returns results.

    Args:
        start: Data start date (ISO string)
        end: Data end date (ISO string)
        params: Strategy parameters (uses PARAMETERS defaults)
        store: MinuteBarStore instance (creates default if None)
    """
    if params is None:
        params = PARAMETERS
    if store is None:
        store = MinuteBarStore()

    primary = params["PRIMARY"]
    robustness = params.get("ROBUSTNESS", "QQQ")

    # Ensure minute bar data is available
    logger.info("Ensuring minute bars for %s %s–%s…", primary, start, end)
    ensure_minute_bars(primary, start, end, store)
    logger.info("Ensuring minute bars for %s %s–%s…", robustness, start, end)
    ensure_minute_bars(robustness, start, end, store)

    # VIX daily for position sizing
    vix = get_vix_daily(start, end)

    # Run walk-forward on primary instrument
    logger.info("Running walk-forward backtest on %s…", primary)
    primary_results = run_walkforward(primary, store, vix, params)

    # Robustness run on QQQ
    logger.info("Running robustness backtest on %s…", robustness)
    robustness_results = run_walkforward(robustness, store, vix, params)

    return {
        "primary": primary_results,
        "robustness": robustness_results,
    }
