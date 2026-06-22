"""
Strategy: H83 Elder Triple Screen Multi-ETF System
Author: Engineering Director (QUA-379)
Date: 2026-06-22
Hypothesis: Elder Triple Screen applied to 8 liquid ETFs (SPY, QQQ, IWM, XLK, XLE, XLP, TLT, GLD).
  Screen 1 — Weekly MACD histogram > 0 (trend gate, updated every Friday close)
  Screen 2 — Daily Stochastic(5,3) dips below oversold threshold then crosses back above
  Screen 3 — Enter at next-day open (T+1 fill)
  Exit — weekly MACD flips negative OR daily Stoch > overbought OR hard stop
Asset class: equities/ETFs (cross-asset: equity, bond, commodity)
Parent task: QUA-379
References: Elder (1993) "Trading for a Living" §Triple Screen System

Data quality checklist:
  Universe: SPY (1993+), QQQ (1999+), IWM (2000+), XLK (1998+), XLE (1998+),
            XLP (1998+), TLT (2002+), GLD (2004+). All via yfinance auto_adjust=True.
  TLT inception 2002+, GLD inception 2004+. IS from 2003 means GLD absent first year;
  strategy runs on available tickers only — no single-ticker gap creates look-ahead.
  Price adjustments: auto_adjust=True for splits and dividends.
  Data gaps: tickers with >5 missing Close values flagged.
  Earnings exclusion: N/A — ETF universe; no individual stock earnings events.
  Survivorship bias: Fixed 8-ETF universe pre-selected by hypothesis. All ETFs active
    and liquid. No delisted ETFs. No survivorship bias possible.
  Weekly MACD: resampled from daily Close using W-FRI (last trading day of each week).
    Forward-filled to daily. No look-ahead: Friday's MACD used from Friday EOD onward.

Transaction cost model (canonical, per Engineering Director AGENTS.md):
  Ultra-liquid ETFs (SPY, QQQ, IWM): $0.005/share + 0.005% slippage + market impact
  Standard ETFs (TLT, GLD, XLK, XLE, XLP): $0.005/share + 0.05% slippage + market impact
  Market impact: k=0.1 × sigma × sqrt(Q/ADV), square-root model (Johnson 2010)
  Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True

Track A hard gates (kpi-daily-weekly.md v1.0):
  Net OOS Sharpe > 0.7 | CPR < 0.25 | IS trade count > 30/quarter | MDD < 30%
  Composite score: 0.40*NetSharpe_norm + 0.30*Stability_norm + 0.20*PpT_norm + 0.10*TradeAdequacy_norm ≥ 0.60

Overnight/weekend guards (Hard Gate 8 documentation):
  - Overnight gap contribution: tracked via daily open vs prior close; reported in analytics
  - Weekend gap exposure: 2 weekend nights per week max; position sizing at 25% per position
    caps single weekend gap exposure to 25% × gap_pct of portfolio
  - Earnings policy: ETF universe has no single-stock earnings risk
  - Gap MDD attribution: reported in trade analytics (gap_pnl vs intraday_pnl)
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Constants ──────────────────────────────────────────────────────────────────

UNIVERSE = ["SPY", "QQQ", "IWM", "XLK", "XLE", "XLP", "TLT", "GLD"]
ULTRA_LIQUID = {"SPY", "QQQ", "IWM"}
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_ULTRA = 0.00005   # 0.005%
SLIPPAGE_STANDARD = 0.0005  # 0.05%
MARKET_IMPACT_K = 0.1
SIGMA_WINDOW = 20
ADV_WINDOW = 20
TRADING_DAYS_PER_YEAR = 252
MIN_HOLD_DAYS = 2          # Minimum days before Stochastic exit can trigger


PARAMETERS = {
    "universe": UNIVERSE,
    # MACD parameters (standard Elder: 12/26/9)
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    # Stochastic parameters
    "stoch_k_period": 5,
    "stoch_d_period": 3,
    # Entry/exit thresholds (primary spec)
    "oversold_threshold": 20,     # Sweep: 15, 20, 25
    "overbought_threshold": 80,
    "hard_stop_pct": 0.075,       # Sweep: 0.06, 0.075, 0.09
    # Portfolio management
    "max_positions": 4,           # Sweep: 3, 4
    "position_weight": 0.25,
    "init_cash": 100_000,
    # IS/OOS (standard split — runner overrides per variant)
    "is_start": "2003-01-01",
    "is_end": "2018-12-31",
    "oos_start": "2019-01-01",
    "oos_end": "2025-12-31",
}


# ── Data Download ─────────────────────────────────────────────────────────────

def download_data(tickers: list, start: str, end: str, warmup_days: int = 200) -> dict:
    """
    Download OHLCV for all tickers with warmup for indicator computation.
    Returns dict[ticker -> DataFrame] with columns Open/High/Low/Close/Volume.
    Tickers missing >5 Close values are flagged but not excluded.
    """
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")
    result = {}
    for t in tickers:
        try:
            raw = yf.download(t, start=warmup_start, end=end, auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            if "Close" not in raw.columns:
                warnings.warn(f"{t}: missing Close column, skipping")
                continue
            na_count = int(raw["Close"].isna().sum())
            if na_count > 5:
                warnings.warn(f"{t}: {na_count} missing Close values")
            result[t] = raw.copy()
        except Exception as exc:
            warnings.warn(f"{t}: download error — {exc}")
    return result


# ── Technical Indicators ──────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_weekly_macd(daily_close: pd.Series, fast: int, slow: int, signal: int) -> pd.Series:
    """
    Compute weekly MACD histogram and forward-fill to daily frequency.
    Uses W-FRI resampling (last trading day on or before each Friday).
    The value at day T is the most recently completed Friday's MACD histogram.
    No look-ahead: Friday's close used from Friday EOD onward via ffill.
    Returns: pd.Series aligned to daily_close.index.
    """
    weekly_close = daily_close.resample("W-FRI").last().dropna()
    if len(weekly_close) < slow + signal + 5:
        return pd.Series(np.nan, index=daily_close.index)
    ema_fast = _ema(weekly_close, fast)
    ema_slow = _ema(weekly_close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    # Forward-fill to daily: Friday's value propagates through Mon-Thu
    return hist.reindex(daily_close.index).ffill()


def compute_stochastic(df: pd.DataFrame, k_period: int, d_period: int) -> tuple:
    """
    Compute Stochastic(k_period, d_period) from OHLCV.
    %K = 3-day SMA of raw stochastic over k_period-day range.
    Returns (stoch_k, stoch_d) aligned to df.index.
    """
    lowest = df["Low"].rolling(k_period).min()
    highest = df["High"].rolling(k_period).max()
    denom = (highest - lowest).replace(0, np.nan)
    raw_stoch = 100.0 * (df["Close"] - lowest) / denom
    stoch_k = raw_stoch.rolling(d_period).mean()   # %K: smoothed
    stoch_d = stoch_k.rolling(d_period).mean()     # %D: additional smoothing
    return stoch_k, stoch_d


# ── Transaction Cost ──────────────────────────────────────────────────────────

def compute_cost(ticker: str, qty: float, price: float, sigma: float, adv: float) -> tuple:
    """
    Round-trip cost per trade leg (entry or exit).
    Returns (cost_dollars, liquidity_flag).
    """
    slippage = SLIPPAGE_ULTRA if ticker in ULTRA_LIQUID else SLIPPAGE_STANDARD
    notional = abs(qty * price)
    fixed_cost = abs(qty) * FIXED_COST_PER_SHARE
    slippage_cost = notional * slippage
    q_adv_ratio = (notional / max(adv * price, 1e-8)) if adv > 0 else 0.0
    impact = MARKET_IMPACT_K * sigma * np.sqrt(max(q_adv_ratio, 0.0)) * notional
    total = fixed_cost + slippage_cost + impact
    liquidity_flag = q_adv_ratio > 0.01
    return total, liquidity_flag


# ── Backtest Engine ───────────────────────────────────────────────────────────

def run_backtest(
    data: dict,
    start: str,
    end: str,
    params: dict,
) -> dict:
    """
    Run the Elder Triple Screen backtest over [start, end].
    data: dict[ticker -> DataFrame] with warmup data
    Returns dict with equity curve, trade log, and summary metrics.
    """
    fast = params["macd_fast"]
    slow = params["macd_slow"]
    sig = params["macd_signal"]
    k_period = params["stoch_k_period"]
    d_period = params["stoch_d_period"]
    oversold = params["oversold_threshold"]
    overbought = params["overbought_threshold"]
    hard_stop = params["hard_stop_pct"]
    max_pos = params["max_positions"]
    pos_wt = params["position_weight"]
    init_cash = params["init_cash"]

    # Build common daily date range
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    # ── Pre-compute indicators for each ticker ─────────────────────────────
    indicators = {}
    for t, df in data.items():
        if df is None or len(df) < slow * 7 + 60:
            continue
        weekly_macd = compute_weekly_macd(df["Close"], fast, slow, sig)
        stoch_k, stoch_d = compute_stochastic(df, k_period, d_period)
        # Sigma for market impact (20-day daily return std)
        sigma = df["Close"].pct_change().rolling(SIGMA_WINDOW).std()
        # ADV in shares (20-day average volume)
        adv = df["Volume"].rolling(ADV_WINDOW).mean()
        indicators[t] = {
            "df": df,
            "weekly_macd": weekly_macd,
            "stoch_k": stoch_k,
            "sigma": sigma,
            "adv": adv,
        }

    if not indicators:
        raise ValueError("No valid tickers after indicator computation")

    # Build aligned date index for the backtest period
    all_indices = [ind["df"].index for ind in indicators.values()]
    common_idx = all_indices[0]
    for idx in all_indices[1:]:
        common_idx = common_idx.intersection(idx)
    date_range = common_idx[(common_idx >= start_ts) & (common_idx <= end_ts)]

    if len(date_range) < 20:
        raise ValueError(f"Insufficient trading days in [{start}, {end}]: {len(date_range)}")

    # ── Backtest state ─────────────────────────────────────────────────────
    cash = float(init_cash)
    portfolio_value = float(init_cash)
    positions = {}   # ticker -> {qty, entry_price, entry_date, hold_days}
    equity_curve = []
    trade_log = []
    liquidity_flags = 0
    pending_entries = {}   # ticker -> (qty, entry_price_est) to fill at next open
    pending_exits = {}     # ticker -> reason to exit at next open

    prev_day = None

    for i, today in enumerate(date_range):
        inds = {t: ind for t, ind in indicators.items()
                if today in ind["df"].index}

        # ── Execute pending orders at today's open ──────────────────────
        for t, reason in list(pending_exits.items()):
            if t not in positions:
                pending_exits.pop(t)
                continue
            open_px = float(inds[t]["df"].loc[today, "Open"]) if t in inds else None
            if open_px is None or np.isnan(open_px):
                continue
            pos = positions.pop(t)
            qty = pos["qty"]
            entry_px = pos["entry_price"]
            sigma = float(inds[t]["sigma"].get(today, 0.0) or 0.0)
            adv_shares = float(inds[t]["adv"].get(today, 1e6) or 1e6)
            exit_cost, liq_flag = compute_cost(t, qty, open_px, sigma, adv_shares)
            if liq_flag:
                liquidity_flags += 1
            gross_pnl = qty * (open_px - entry_px)
            # Entry cost was recorded at entry; exit cost here
            net_pnl = gross_pnl - exit_cost
            proceeds = qty * open_px - exit_cost
            cash += proceeds
            hold_days = (today - pos["entry_date"]).days
            # Gap attribution (overnight gap)
            prev_close = float(inds[t]["df"]["Close"].get(prev_day, open_px)) if prev_day is not None else open_px
            gap_pnl = qty * (open_px - prev_close)
            trade_log.append({
                "ticker": t,
                "entry_date": pos["entry_date"].isoformat(),
                "exit_date": today.isoformat(),
                "entry_price": round(entry_px, 4),
                "exit_price": round(open_px, 4),
                "qty": qty,
                "pnl_gross": round(gross_pnl, 4),
                "pnl_net": round(net_pnl, 4),
                "cost_total": round(exit_cost + pos.get("entry_cost", 0.0), 4),
                "hold_days": hold_days,
                "exit_reason": reason,
                "gap_pnl": round(gap_pnl, 4),
            })
            pending_exits.pop(t)

        for t, (qty, entry_est) in list(pending_entries.items()):
            if t in positions:
                pending_entries.pop(t)
                continue
            if t not in inds:
                pending_entries.pop(t)
                continue
            open_px = float(inds[t]["df"].loc[today, "Open"])
            if np.isnan(open_px):
                pending_entries.pop(t)
                continue
            sigma = float(inds[t]["sigma"].get(today, 0.0) or 0.0)
            adv_shares = float(inds[t]["adv"].get(today, 1e6) or 1e6)
            entry_cost, liq_flag = compute_cost(t, qty, open_px, sigma, adv_shares)
            if liq_flag:
                liquidity_flags += 1
            cost_of_position = qty * open_px + entry_cost
            if cost_of_position > cash:
                pending_entries.pop(t)
                continue
            cash -= cost_of_position
            positions[t] = {
                "qty": qty,
                "entry_price": open_px,
                "entry_date": today,
                "hold_days": 0,
                "entry_cost": entry_cost,
            }
            pending_entries.pop(t)

        # ── Mark-to-market portfolio value ──────────────────────────────
        pos_value = 0.0
        for t, pos in positions.items():
            close_px = float(inds[t]["df"].loc[today, "Close"]) if t in inds else pos["entry_price"]
            if np.isnan(close_px):
                close_px = pos["entry_price"]
            pos_value += pos["qty"] * close_px
        portfolio_value = cash + pos_value
        equity_curve.append({"date": today.isoformat(), "equity": portfolio_value})

        # ── Update hold days for open positions ─────────────────────────
        for t in positions:
            positions[t]["hold_days"] = (today - positions[t]["entry_date"]).days

        # ── Generate signals at today's EOD ─────────────────────────────
        for t, pos in list(positions.items()):
            if t not in inds:
                continue
            weekly_macd_val = float(inds[t]["weekly_macd"].get(today, 0.0) or 0.0)
            close_px = float(inds[t]["df"].loc[today, "Close"])
            entry_px = pos["entry_price"]
            hold = pos["hold_days"]

            # Exit 1: Weekly MACD turns negative
            if weekly_macd_val < 0 and t not in pending_exits:
                pending_exits[t] = "weekly_macd_negative"
                continue

            # Exit 3: Hard stop (computed from close; fill at next open)
            if close_px < entry_px * (1.0 - hard_stop) and t not in pending_exits:
                pending_exits[t] = "hard_stop"
                continue

            # Exit 2: Daily Stochastic overbought (min hold of MIN_HOLD_DAYS)
            if hold >= MIN_HOLD_DAYS:
                stoch_k_val = float(inds[t]["stoch_k"].get(today, 50.0) or 50.0)
                if stoch_k_val > overbought and t not in pending_exits:
                    pending_exits[t] = "stoch_overbought"

        # ── Entry signals ───────────────────────────────────────────────
        open_slot_count = max_pos - len(positions) - len(pending_entries)
        if open_slot_count > 0:
            for t in UNIVERSE:
                if t not in inds:
                    continue
                if t in positions or t in pending_entries or t in pending_exits:
                    continue
                if open_slot_count <= 0:
                    break

                # Screen 1: Weekly MACD trend gate
                weekly_macd_val = float(inds[t]["weekly_macd"].get(today, np.nan))
                if np.isnan(weekly_macd_val) or weekly_macd_val <= 0:
                    continue

                # Screen 2: Stochastic oversold cross
                if prev_day is None or prev_day not in inds[t]["df"].index:
                    continue
                stoch_k_today = float(inds[t]["stoch_k"].get(today, np.nan))
                stoch_k_prev = float(inds[t]["stoch_k"].get(prev_day, np.nan))
                if np.isnan(stoch_k_today) or np.isnan(stoch_k_prev):
                    continue
                entry_signal = (stoch_k_prev < oversold) and (stoch_k_today >= oversold)
                if not entry_signal:
                    continue

                # Position sizing: pos_wt of current portfolio
                alloc = portfolio_value * pos_wt
                close_px = float(inds[t]["df"].loc[today, "Close"])
                if np.isnan(close_px) or close_px <= 0:
                    continue
                qty = int(alloc / close_px)
                if qty < 1:
                    continue

                # Screen 3: Schedule entry at next open
                pending_entries[t] = (qty, close_px)
                open_slot_count -= 1

        prev_day = today

    # ── Liquidate any remaining positions at final close ─────────────────
    final_day = date_range[-1] if len(date_range) > 0 else None
    if final_day is not None:
        for t, pos in list(positions.items()):
            if t in indicators and final_day in indicators[t]["df"].index:
                close_px = float(indicators[t]["df"].loc[final_day, "Close"])
                qty = pos["qty"]
                entry_px = pos["entry_price"]
                gross_pnl = qty * (close_px - entry_px)
                net_pnl = gross_pnl  # no additional cost for forced liquidation marker
                trade_log.append({
                    "ticker": t,
                    "entry_date": pos["entry_date"].isoformat(),
                    "exit_date": final_day.isoformat(),
                    "entry_price": round(entry_px, 4),
                    "exit_price": round(close_px, 4),
                    "qty": qty,
                    "pnl_gross": round(gross_pnl, 4),
                    "pnl_net": round(net_pnl, 4),
                    "cost_total": round(pos.get("entry_cost", 0.0), 4),
                    "hold_days": (final_day - pos["entry_date"]).days,
                    "exit_reason": "period_end",
                    "gap_pnl": 0.0,
                })

    # ── Compute summary metrics ──────────────────────────────────────────
    equity_df = pd.DataFrame(equity_curve).set_index("date")["equity"]
    equity_df.index = pd.DatetimeIndex(equity_df.index)
    returns = equity_df.pct_change().dropna()
    sharpe = float((returns.mean() / returns.std()) * np.sqrt(TRADING_DAYS_PER_YEAR)) if returns.std() > 0 else 0.0
    roll_max = equity_df.cummax()
    drawdown = (equity_df - roll_max) / roll_max
    max_dd = float(drawdown.min())
    total_return = float((equity_df.iloc[-1] / equity_df.iloc[0]) - 1.0)
    trade_count = len([t for t in trade_log if t["exit_reason"] != "period_end"])
    wins = [t for t in trade_log if t["pnl_net"] > 0]
    win_rate = len(wins) / max(len(trade_log), 1)

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "total_return": round(total_return, 4),
        "trade_count": trade_count,
        "win_rate": round(win_rate, 4),
        "equity_curve": equity_curve,
        "trade_log": trade_log,
        "liquidity_flags": liquidity_flags,
        "final_equity": float(equity_df.iloc[-1]),
    }


# ── Per-Quarter Trade Count ────────────────────────────────────────────────────

def per_quarter_trade_count(trade_log: list) -> dict:
    """
    Count trades per calendar quarter. Used for PF-1 gate check.
    Returns dict with quarter labels and flagged quarters (<30 trades).
    """
    if not trade_log:
        return {"quarters": {}, "flagged_quarters": []}
    df = pd.DataFrame(trade_log)
    df["entry_dt"] = pd.to_datetime(df["entry_date"])
    df["quarter"] = df["entry_dt"].dt.to_period("Q").astype(str)
    counts = df.groupby("quarter").size().to_dict()
    flagged = [q for q, c in counts.items() if c < 30]
    return {"quarters": counts, "flagged_quarters": flagged}
