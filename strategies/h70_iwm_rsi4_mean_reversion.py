"""
Strategy: H70 IWM Small-Cap Mean Reversion via RSI-4 with Weinstein Stage 2 Filter
Author: Strategy Coder Agent
Date: 2026-06-15
Hypothesis: IWM RSI-4 < 20 in Stage 2 uptrend marks extreme short-term oversold conditions
            in small-cap universe. AP rebalancing, ETF discount-to-NAV forces, and
            institutional cross-asset rebalancing drive mean reversion within 4-8 trading days.
Asset class: equities (IWM ETF)
Parent task: QUA-301
References: Connors & Alvarez (2009, 2012); Weinstein (1988) §3; Elder (1993) §7.3;
            Israel & Moskowitz (2013); research/hypotheses/70_iwm_smallcap_mean_reversion.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "IWM",
    "rsi_period": 4,              # Wilder RSI (EWM com=3) — Connors & Alvarez (2009) canonical
    "rsi_entry_threshold": 20,    # Enter when RSI-4 < 20 (test range: 15–25)
    "sma_period": 200,            # Regime gate: IWM > 200-day SMA = Weinstein Stage 2
    "rsi_exit_threshold": 65,     # Exit when RSI-4 > 65 at EOD (test range: 60–70)
    "high_exit_lookback": 5,      # Exit when close > max(close[-5..-1]) (test range: 3–7)
    "stop_loss_pct": 0.075,       # 7.5% hard stop — O'Neil/Minervini standard (test: 5%–10%)
    "max_hold_days": 15,          # Max hold bars; exit at T+1 open on day 15 (test: 10/15/20)
    "position_risk_pct": 0.02,    # Elder 2% rule: max 2% account equity at risk per trade
    "max_notional_pct": 0.40,     # Concentration cap: max 40% of account per position
    "init_cash": 25000,
}

# ── Transaction Cost Constants — ED-SLIP-001 Ultra-Liquid ETF Tier ─────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share (equities)
SLIPPAGE_PCT = 0.00005          # 0.005% of notional (IWM ultra-liquid tier; ED-SLIP-001)
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root model coefficient k
SIGMA_WINDOW = 20               # rolling vol window for market impact σ
ADV_WINDOW = 20                 # rolling volume window for market impact ADV
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(ticker: str, start: str, end: str, sma_period: int) -> pd.DataFrame:
    """
    Download IWM OHLCV with warmup window sufficient for the SMA lookback.
    Warmup = sma_period * 1.5 + 30 calendar days (buffer for weekends/holidays).

    Returns full OHLCV DataFrame including warmup period.
    Raises ValueError if data is insufficient or missing required columns.
    """
    warmup_td = int(sma_period * 1.5) + 30
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_td)).strftime("%Y-%m-%d")

    df = _download_single(ticker, warmup_start, end)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns for {ticker}: {missing}")
    if len(df) < sma_period + 10:
        raise ValueError(
            f"Insufficient data for {ticker}: {len(df)} bars (need {sma_period + 10})"
        )

    na_count = int(df["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing Close values detected in download range")

    return df


# ── Technical Indicators ───────────────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 4) -> pd.Series:
    """
    Wilder RSI using EWM with com=period-1 (alpha=1/period).

    RSI-4 on IWM < 20: requires 4 bars of net down momentum — more stringent than RSI-2
    on SPY, capturing genuinely extreme small-cap oversold events. Add 1e-10 to loss
    denominator to prevent division by zero on pure-uptrend bars.
    """
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def compute_sma_regime(close_series: pd.Series, sma_period: int) -> pd.Series:
    """
    Weinstein Stage 2 regime gate: IWM > 200-day SMA.

    Uses prior-day close vs prior-day SMA (.shift(1)) — no same-bar look-ahead.
    Returns True when day T-1 close was above day T-1 SMA.
    """
    sma = close_series.rolling(sma_period).mean()
    return close_series.shift(1) > sma.shift(1)


def compute_prior_high(close_series: pd.Series, lookback: int = 5) -> pd.Series:
    """
    Prior N-day high: max(close[-N..-1]) — strictly prior bars, no same-bar look-ahead.

    close.shift(1).rolling(lookback).max() at bar i = max(close[i-N..i-1]).
    """
    return close_series.shift(1).rolling(lookback).max()


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    fill_price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    idx: int,
) -> tuple:
    """
    ED-SLIP-001 ultra-liquid ETF transaction cost model:
      fixed    = $0.005/share
      slippage = 0.005% of notional (ultra-liquid tier; IWM named in ED-SLIP-001)
      impact   = k * sigma * sqrt(Q / ADV) * notional  (Almgren-Chriss square-root model)

    Flags orders where Q/ADV > 1% as liquidity-constrained.
    Returns (total_cost_dollars, liquidity_constrained_bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * fill_price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01       # fallback: 1% daily vol
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000    # fallback: 1M shares ADV

    # Square-root market impact (Almgren-Chriss; Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * fill_price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV) — ED-SLIP-001"
        )

    return fixed + slippage + impact, liq_constrained


# ── Position Sizing ────────────────────────────────────────────────────────────

def _elder_position_size(entry_fill: float, account_equity: float, params: dict) -> int:
    """
    Elder 2% Rule (Elder §7.3): risk max 2% of account equity per trade.

    risk_per_share = entry_fill × stop_loss_pct  (7.5% = $15/share at IWM ~$200)
    max_risk_dollars = account_equity × position_risk_pct  (2%)
    shares = int(max_risk_dollars / risk_per_share)

    Capped at max_notional_pct (40%) concentration limit per position.
    Returns 0 if entry_fill <= 0.
    """
    if entry_fill <= 0:
        return 0
    risk_per_share = entry_fill * params["stop_loss_pct"]
    max_risk = account_equity * params["position_risk_pct"]
    shares = int(max_risk / risk_per_share) if risk_per_share > 0 else 0
    max_notional_shares = int(account_equity * params["max_notional_pct"] / entry_fill)
    return max(0, min(shares, max_notional_shares))


# ── H70 Simulation Engine ──────────────────────────────────────────────────────

def _gap_flags(entry_date_ts: pd.Timestamp, exit_date_ts: pd.Timestamp, hold_days: int) -> tuple:
    """Compute overnight_gap and weekend_gap flags for a completed trade."""
    o_gap = bool(hold_days >= 1)
    day_range = pd.date_range(entry_date_ts, exit_date_ts, freq='D')
    w_gap = bool(any(d.dayofweek >= 5 for d in day_range))
    return o_gap, w_gap


def simulate_h70(
    iwm_df: pd.DataFrame,
    rsi_vals: pd.Series,
    sma_regime: pd.Series,
    prior_high_vals: pd.Series,
    params: dict,
) -> tuple:
    """
    Simulate H70 RSI-4 IWM mean reversion with Weinstein Stage 2 filter.

    All inputs must be aligned to the backtest window (trim after pre-computing indicators
    on the warmup-inclusive series, so values at backtest start are already warm).

    Entry/exit logic:
    - Entry: RSI-4 < rsi_entry_threshold AND regime active (IWM > 200-SMA, prior-day basis)
             → Enter at OPEN of next bar. Position sized via Elder 2% rule.
    - Exit 1 (RSI): RSI-4 > rsi_exit_threshold at EOD → exit at OPEN of next bar.
    - Exit 2 (5-day high): close > max(close[-5..-1]) at EOD → exit at OPEN of next bar.
    - Exit 3 (max hold): hold >= max_hold_days bars → exit at OPEN of next bar.
    - Exit 4 (stop-loss): close <= entry_fill × (1 - stop_loss_pct) → exit at stop price.

    EOD exit priority (for labeling when multiple fire simultaneously): RSI > HIGH > MAX_HOLD.
    Stop-loss is intraday/close and takes priority over any queued EOD exit.
    No re-arm gate (RSI-4 on IWM fires less frequently than RSI-2 on SPY; each signal independent).

    Gap tracking (Track A Hard Gate 8):
        overnight_gap = True if position held ≥1 overnight (hold_days ≥ 1)
        weekend_gap   = True if any Sat/Sun in calendar range entry→exit

    Returns:
        trade_log (list of dicts), equity (pd.Series), daily_df (pd.DataFrame)
    """
    rsi_entry_thresh = params["rsi_entry_threshold"]
    rsi_exit_thresh = params["rsi_exit_threshold"]
    stop_loss_pct = params["stop_loss_pct"]
    max_hold_days = params["max_hold_days"]
    init_cash = float(params["init_cash"])

    close_s = iwm_df["Close"]
    open_s = iwm_df["Open"]
    vol_s = iwm_df["Volume"]
    dates = iwm_df.index
    n = len(dates)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_pos = False
    pending_entry = False
    pending_open_exit = False
    pending_exit_reason = ""

    # Active position state
    entry_bar_idx = -1
    entry_fill_price = 0.0       # raw open fill — stop-loss threshold baseline
    entry_eff_price = 0.0        # fill + costs — PnL baseline
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_date_ts = None
    entry_regime = False

    for i in range(n):
        date = dates[i]
        open_i = float(open_s.iloc[i])
        close_i = float(close_s.iloc[i])

        rsi_raw = rsi_vals.iloc[i]
        rsi_i = float(rsi_raw) if not pd.isna(rsi_raw) else np.nan

        regime_raw = sma_regime.iloc[i]
        regime_i = bool(regime_raw) if not pd.isna(regime_raw) else False

        prior_high_raw = prior_high_vals.iloc[i]
        prior_high_i = float(prior_high_raw) if not pd.isna(prior_high_raw) else np.nan

        exit_triggered = False

        # ── Step 1: Enter at today's OPEN if entry signal queued ──────────────
        if not in_pos and pending_entry:
            if open_i > 0 and not pd.isna(open_i):
                shares = _elder_position_size(open_i, capital, params)
                if shares > 0:
                    cost, liq = _transaction_cost(open_i, shares, close_s, vol_s, i)
                    eff_ep = open_i + cost / shares
                    capital -= eff_ep * shares
                    in_pos = True
                    entry_bar_idx = i
                    entry_fill_price = open_i    # raw fill; stop-loss baseline (pre-cost)
                    entry_eff_price = eff_ep
                    entry_shares = shares
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_date_ts = date
                    entry_regime = regime_i
            pending_entry = False

        # ── Step 2: Exit at today's OPEN if RSI/high/max-hold was queued ─────
        # Must not be on the same bar we entered (entry_bar_idx check).
        if in_pos and pending_open_exit and not exit_triggered:
            if i > entry_bar_idx and open_i > 0 and not pd.isna(open_i):
                xcost, xliq = _transaction_cost(open_i, entry_shares, close_s, vol_s, i)
                eff_xp = open_i - xcost / entry_shares
                pnl = (eff_xp - entry_eff_price) * entry_shares
                capital += eff_xp * entry_shares

                hold_days = i - entry_bar_idx
                o_gap, w_gap = _gap_flags(entry_date_ts, date, hold_days)

                trade_log.append({
                    "entry_date": entry_date_ts.date(),
                    "exit_date": date.date(),
                    "entry_price": round(entry_eff_price, 4),
                    "exit_price": round(eff_xp, 4),
                    "shares": entry_shares,
                    "pnl": round(pnl, 2),
                    "entry_cost": round(entry_cost_total, 4),
                    "exit_cost": round(xcost, 4),
                    "transaction_cost": round(entry_cost_total + xcost, 4),
                    "liquidity_constrained": entry_liq or xliq,
                    "hold_days": hold_days,
                    "exit_reason": pending_exit_reason,
                    "regime_active_at_entry": entry_regime,
                    "overnight_gap": o_gap,
                    "weekend_gap": w_gap,
                })

                in_pos = False
                exit_triggered = True

            pending_open_exit = False
            pending_exit_reason = ""

        # ── Step 3: Check stop-loss against today's CLOSE ────────────────────
        # Uses entry_fill_price (raw open fill, pre-cost) as the stop baseline.
        # Stop assumed to fill at trigger level (not lower close) — standard assumption.
        if in_pos and not exit_triggered:
            stop_threshold = entry_fill_price * (1.0 - stop_loss_pct)
            if close_i <= stop_threshold:
                stop_fill = stop_threshold
                xcost, xliq = _transaction_cost(stop_fill, entry_shares, close_s, vol_s, i)
                eff_xp = stop_fill - xcost / entry_shares
                pnl = (eff_xp - entry_eff_price) * entry_shares
                capital += eff_xp * entry_shares

                hold_days = i - entry_bar_idx
                o_gap, w_gap = _gap_flags(entry_date_ts, date, hold_days)

                trade_log.append({
                    "entry_date": entry_date_ts.date(),
                    "exit_date": date.date(),
                    "entry_price": round(entry_eff_price, 4),
                    "exit_price": round(eff_xp, 4),
                    "shares": entry_shares,
                    "pnl": round(pnl, 2),
                    "entry_cost": round(entry_cost_total, 4),
                    "exit_cost": round(xcost, 4),
                    "transaction_cost": round(entry_cost_total + xcost, 4),
                    "liquidity_constrained": entry_liq or xliq,
                    "hold_days": hold_days,
                    "exit_reason": "STOP_LOSS",
                    "regime_active_at_entry": entry_regime,
                    "overnight_gap": o_gap,
                    "weekend_gap": w_gap,
                })

                in_pos = False
                exit_triggered = True
                pending_open_exit = False
                pending_exit_reason = ""

        # ── Step 4: Queue exit condition for next bar (EOD evaluation) ────────
        # Priority: RSI_EXIT > HIGH_EXIT > MAX_HOLD (first match wins for labeling).
        # Not set if already queued (pending_open_exit guards against overwrite).
        if in_pos and not exit_triggered and not pending_open_exit:
            hold_days = i - entry_bar_idx

            if not pd.isna(rsi_i) and rsi_i > rsi_exit_thresh:
                pending_open_exit = True
                pending_exit_reason = "RSI_EXIT"
            elif not pd.isna(prior_high_i) and close_i > prior_high_i:
                pending_open_exit = True
                pending_exit_reason = "HIGH_EXIT"
            elif hold_days >= max_hold_days:
                pending_open_exit = True
                pending_exit_reason = "MAX_HOLD"

        # ── Step 5: Queue entry signal for next bar ───────────────────────────
        # Valid only when: in cash, no pending entry, RSI-4 < threshold, regime open.
        # No re-arm gate — RSI-4 on IWM fires infrequently; each signal independent.
        if not in_pos and not pending_entry:
            if not pd.isna(rsi_i) and rsi_i < rsi_entry_thresh and regime_i:
                pending_entry = True

        # ── Daily mark-to-market ──────────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        daily_records.append({
            "date": date,
            "position": 1 if in_pos else 0,
            "rsi": round(rsi_i, 2) if not pd.isna(rsi_i) else np.nan,
            "regime_active": regime_i,
            "equity": mtm,
        })

    # ── Force-close any open position at end of data ──────────────────────────
    if in_pos and n > 0:
        i = n - 1
        date_f = dates[i]
        close_f = float(close_s.iloc[i])
        xcost, xliq = _transaction_cost(close_f, entry_shares, close_s, vol_s, i)
        eff_xp = close_f - xcost / entry_shares
        pnl = (eff_xp - entry_eff_price) * entry_shares
        capital += eff_xp * entry_shares

        hold_days = (n - 1) - entry_bar_idx
        o_gap, w_gap = _gap_flags(entry_date_ts, date_f, hold_days)

        trade_log.append({
            "entry_date": entry_date_ts.date(),
            "exit_date": date_f.date(),
            "entry_price": round(entry_eff_price, 4),
            "exit_price": round(eff_xp, 4),
            "shares": entry_shares,
            "pnl": round(pnl, 2),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(xcost, 4),
            "transaction_cost": round(entry_cost_total + xcost, 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_days": hold_days,
            "exit_reason": "END_OF_DATA",
            "regime_active_at_entry": entry_regime,
            "overnight_gap": o_gap,
            "weekend_gap": w_gap,
        })
        if daily_records:
            daily_records[-1]["equity"] = capital

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")

    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df


# ── Performance Metrics ────────────────────────────────────────────────────────

def _compute_metrics(equity: pd.Series, trades_df: pd.DataFrame, start: str, end: str) -> dict:
    """
    Compute standard Gate 1 performance metrics from equity curve and trade log.
    All metrics annualized to TRADING_DAYS_PER_YEAR (252).
    """
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)
    years = max((ts_end - ts_start).days / 365.25, 1e-3)

    n_trades = len(trades_df)
    trades_per_year = round(n_trades / years, 1)

    daily_returns = equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values

    sharpe = 0.0
    if len(ret_arr) > 0 and ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    win_rate = 0.0
    profit_factor = 0.0
    if n_trades > 0:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        gross_wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        gross_losses = abs(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum())
        profit_factor = round(float(gross_wins / max(gross_losses, 1e-8)), 4)

    pf1_status = "PASS" if trades_per_year >= 30 else f"WARN: {trades_per_year:.1f}/yr < 30"

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "pf1_status": pf1_status,
    }


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download IWM data, compute indicators on warmup-inclusive series, trim to
    backtest window, and simulate H70.

    Parameters
    ----------
    start : str  Backtest start (YYYY-MM-DD). IS = "2005-01-01".
    end   : str  Backtest end (YYYY-MM-DD). IS = "2018-12-31".
    params : dict, optional  Override PARAMETERS. Uses module PARAMETERS if None.

    Returns
    -------
    dict  Standardized result: sharpe, max_drawdown, total_return, win_rate,
          profit_factor, trade_count, trades_per_year, pf1_status, returns,
          trades (DataFrame), equity (Series), daily_df (DataFrame),
          data_quality (dict), regime_pct (float), exit_breakdown (dict),
          gap_attribution (dict), metadata (dict), params (dict).
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    sma_period = params["sma_period"]
    high_lookback = params["high_exit_lookback"]
    init_cash = float(params["init_cash"])

    # 1. Download with SMA warmup
    df_full = download_data(ticker, start, end, sma_period)

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # 2. Compute indicators on warmup-inclusive series (avoids NaN at backtest start)
    rsi_full = compute_rsi(df_full["Close"], params["rsi_period"])
    regime_full = compute_sma_regime(df_full["Close"], sma_period)
    prior_high_full = compute_prior_high(df_full["Close"], high_lookback)

    # 3. Trim all series to backtest window
    mask = (df_full.index >= ts_start) & (df_full.index <= ts_end)
    iwm_df = df_full.loc[mask].copy()
    rsi_aligned = rsi_full.loc[mask]
    regime_aligned = regime_full.loc[mask]
    prior_high_aligned = prior_high_full.loc[mask]

    if len(iwm_df) < 10:
        raise ValueError(
            f"Insufficient IWM data after trimming to {start}–{end}: {len(iwm_df)} bars"
        )

    regime_na = int(regime_aligned.isna().sum())
    if regime_na > 0:
        warnings.warn(
            f"Regime series has {regime_na} NaN values at backtest start — "
            f"warmup may be insufficient for sma_period={sma_period}"
        )

    # 4. Data quality checks
    na_count = int(iwm_df["Close"].isna().sum())
    max_gap = 0
    if iwm_df["Close"].isna().any():
        is_na = iwm_df["Close"].isna().astype(int)
        max_gap = int(is_na.groupby((~iwm_df["Close"].isna()).cumsum()).sum().max())
    if max_gap >= 5:
        warnings.warn(f"Data gap: {max_gap} consecutive missing days in {ticker}")

    # 5. Simulate
    trade_log, equity, daily_df = simulate_h70(
        iwm_df, rsi_aligned, regime_aligned, prior_high_aligned, params
    )

    # 6. Build trade DataFrame
    empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason", "regime_active_at_entry",
        "overnight_gap", "weekend_gap",
    ]
    trades_df = (
        pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)
    )

    # 7. Performance metrics
    metrics = _compute_metrics(equity, trades_df, start, end)

    # Regime stats
    regime_pct = round(float(regime_aligned.mean()), 4) if len(regime_aligned) > 0 else 0.0

    # Exit reason breakdown
    exit_breakdown: dict = {}
    if not trades_df.empty:
        exit_breakdown = trades_df["exit_reason"].value_counts().to_dict()

    # Gap attribution for Track A Hard Gate 8
    gap_attribution: dict = {}
    if not trades_df.empty:
        n_total = len(trades_df)
        n_overnight = int(trades_df["overnight_gap"].sum())
        n_weekend = int(trades_df["weekend_gap"].sum())
        overnight_pnl = float(trades_df.loc[trades_df["overnight_gap"], "pnl"].sum())
        weekend_pnl = float(trades_df.loc[trades_df["weekend_gap"], "pnl"].sum())
        gap_attribution = {
            "overnight_gap_trades": n_overnight,
            "weekend_gap_trades": n_weekend,
            "total_trades": n_total,
            "overnight_gap_pct": round(n_overnight / max(n_total, 1), 4),
            "weekend_gap_pct": round(n_weekend / max(n_total, 1), 4),
            "overnight_gap_pnl": round(overnight_pnl, 2),
            "weekend_gap_pnl": round(weekend_pnl, 2),
        }

    print(
        f"\nH70 IWM RSI-4 Mean Reversion Backtest ({start} to {end}):\n"
        f"  Regime (IWM > {sma_period}-SMA) active: {regime_pct:.1%} of backtest days\n"
        f"  Trades: {metrics['trade_count']} ({metrics['trades_per_year']}/yr)"
        f" — PF-1: {metrics['pf1_status']}\n"
        f"  Sharpe: {metrics['sharpe']} | Max DD: {metrics['max_drawdown']:.2%}"
        f" | Total Return: {metrics['total_return']:.2%}\n"
        f"  Win rate: {metrics['win_rate']:.2%}"
        f" | Profit factor: {metrics['profit_factor']:.2f}\n"
        f"  Exit reasons: {exit_breakdown}\n"
        f"  Gap attribution: {gap_attribution}\n"
        f"  Init cash: ${init_cash:,.0f}"
    )

    if metrics["trades_per_year"] < 30:
        warnings.warn(f"PF-1 WARN: {metrics['trades_per_year']:.1f} trades/yr < 30 threshold")

    return {
        **metrics,
        "returns": equity.pct_change().fillna(0.0),
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params,
        "data_quality": {
            "survivorship_bias_flag": "IWM is a Russell 2000 ETF — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "warmup_bars": sma_period + 30,
            "gap_flags": ([f"{max_gap} consecutive missing days"] if max_gap >= 5 else []),
            "na_close_count": na_count,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — IWM still active",
        },
        "regime_pct": regime_pct,
        "exit_breakdown": exit_breakdown,
        "gap_attribution": gap_attribution,
        "metadata": {
            "slippage_model": "ultra_liquid_etf",
            "ruling_ref": "ED-SLIP-001",
            "hypothesis": "H70",
            "ticker": ticker,
        },
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "IWM",
    start: str = "2005-01-01",
    end: str = "2018-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H70.

    Returns a DataFrame with per-day columns:
        date, position, rsi, regime_active, equity,
        pnl, entry_price, exit_price, transaction_cost, exit_reason

    Trade-level fields (pnl, entry_price, exit_price, transaction_cost, exit_reason)
    are populated on the exit date of each trade; all other rows carry NaN.
    `ticker` is ignored — H70 uses IWM via PARAMETERS["ticker"].
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
        "date", "position", "rsi", "regime_active", "equity",
        "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason",
    ]]


if __name__ == "__main__":
    # IS period: 2005-2018 (Gate 1 assessment window per hypothesis)
    is_result = run_backtest("2005-01-01", "2018-12-31")
    print("\nIS Sample trades (first 10):")
    if not is_result["trades"].empty:
        print(is_result["trades"].head(10).to_string(index=False))
    print(f"\nIS equity final: ${is_result['equity'].iloc[-1]:,.2f}")
    print(f"IS regime active: {is_result['regime_pct']:.1%} of days")
    print(f"IS exit breakdown: {is_result['exit_breakdown']}")
    print(f"IS gap attribution: {is_result['gap_attribution']}")

    # OOS period: 2019-2024
    print("\n" + "=" * 60)
    oos_result = run_backtest("2019-01-01", "2024-12-31")
    print(f"\nOOS equity final: ${oos_result['equity'].iloc[-1]:,.2f}")
    print(f"OOS regime active: {oos_result['regime_pct']:.1%} of days")
    print(f"OOS exit breakdown: {oos_result['exit_breakdown']}")
    print(f"OOS gap attribution: {oos_result['gap_attribution']}")
