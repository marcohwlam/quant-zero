"""
Strategy: H34b RSI(2) Oversold SPY Mean Reversion — Raised Threshold (rsi_entry_threshold=20)
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: SPY RSI(2) < 20 in an uptrend (SPY > 200-SMA) marks extreme short-term
            oversold conditions. Raising the threshold from H34's 10 to 20 captures
            the same behavioral mean-reversion mechanism (panic selling after 2-3 down
            days) at a slightly earlier inflection point, tripling trade frequency
            while preserving edge quality. Price mean-reverts to the 5-day SMA within
            3-5 trading days.
Asset class: equities (SPY ETF)
Parent task: QUA-274
Family: RSI(2) Mean Reversion (Iteration 2 of 2 — Final family iteration)
Predecessor: H34 (IS Sharpe 0.35, FAIL — root cause: insufficient trade frequency)
References: Connors & Alvarez (2012) Short-Term Trading Strategies That Work;
            Jegadeesh (1990) J. Finance 45(3); Lehmann (1990) QJE 105(1);
            research/hypotheses/34b_rsi2_oversold_spy_looser_threshold.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "SPY",
    "rsi_period": 2,                  # RSI lookback — fixed by Connors (2012) theory; do NOT tune
    "rsi_entry_threshold": 20,        # H34b: raised from 10 → 20 (test range: 15–25)
    "sma_period": 200,                # Regime gate: SPY > N-day SMA required for entry (test range: 150–250)
    "exit_sma_period": 5,             # Exit when close > N-day SMA (test range: 3–10)
    "time_stop_days": 5,              # Max hold: sell at open of day N+1 (test range: 3–7)
    "stop_loss_pct": 0.04,            # Drawdown stop from raw entry fill (test range: 0.03–0.06)
    "rearm_rsi_level": 50,            # H34b: raised from 40 → 50 — RSI must cross above this after exit
    "init_cash": 25000,
}

# ── Transaction Cost Constants ─────────────────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share (equities)
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
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
    Download SPY OHLCV with a warmup window sufficient for the SMA lookback.
    Warmup = sma_period * 1.5 + 30 calendar days (buffer for weekends/holidays).

    Returns full OHLCV DataFrame including warmup period.
    Raises ValueError if data is insufficient or missing required columns.
    """
    warmup_td = int(sma_period * 1.5) + 30
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_td)).strftime("%Y-%m-%d")

    spy_df = _download_single(ticker, warmup_start, end)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(spy_df.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns for {ticker}: {missing}")
    if len(spy_df) < sma_period + 10:
        raise ValueError(
            f"Insufficient data for {ticker}: {len(spy_df)} bars (need {sma_period + 10})"
        )

    na_count = int(spy_df["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing Close values detected in download range")

    return spy_df


# ── Technical Indicators ───────────────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 2) -> pd.Series:
    """
    Wilder RSI using EWM with com=period-1.

    Connors (2012): RSI(2) is the canonical ultra-short mean-reversion oscillator.
    At RSI(2) < 20, SPY has experienced 2-3 consecutive down days — behavioral
    capitulation signal driven by retail panic and dealer delta-hedging pressure.
    H34b raises the trigger threshold from 10 to 20, catching the same mechanism
    at a slightly earlier inflection point to triple trade frequency.

    Note: add 1e-10 to loss denominator to prevent division by zero on pure-uptrend bars.
    """
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def compute_sma_regime(close_series: pd.Series, sma_period: int) -> pd.Series:
    """
    200-day SMA regime gate.

    Returns True on date T when the prior-day close was above the prior-day SMA.
    Uses .shift(1) so entries on day T are conditioned on day T-1 confirmed close
    — no same-bar look-ahead.
    """
    sma = close_series.rolling(sma_period).mean()
    return close_series.shift(1) > sma.shift(1)


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    fill_price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    idx: int,
) -> tuple:
    """
    Canonical equities transaction cost (Engineering Director spec):
      fixed    = $0.005/share
      slippage = 0.05% of notional
      impact   = k * sigma * sqrt(Q / ADV) * notional  (Almgren-Chriss square-root model)

    Flags orders where Q/ADV > 1% as liquidity-constrained.
    Returns (total_cost_dollars, liquidity_constrained_bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * fill_price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01    # fallback: 1% daily vol
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000  # fallback: 1M shares ADV

    # Square-root market impact (Almgren-Chriss; Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * fill_price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV)"
        )

    return fixed + slippage + impact, liq_constrained


# ── H34b Simulation Engine ─────────────────────────────────────────────────────

def simulate_h34b(
    spy_df: pd.DataFrame,
    rsi_vals: pd.Series,
    sma_regime: pd.Series,
    exit_sma_vals: pd.Series,
    params: dict,
) -> tuple:
    """
    Simulate H34b RSI(2) Oversold SPY Mean Reversion with 200-SMA regime filter.

    Identical logic to H34 with two parameter changes:
    - rsi_entry_threshold: 10 → 20 (catch same edge earlier, 3x trade frequency)
    - rearm_rsi_level: 40 → 50 (slightly more conservative re-arm after exit)

    All inputs must be aligned to the same backtest window (not warmup-inclusive).
    Rolling indicators must be pre-computed on the warmup-inclusive series so that
    values at the start of the backtest window are already warm.

    Entry/exit logic:
    - Entry: RSI(2) < rsi_entry_threshold AND regime active (SPY > 200-SMA, prior-day basis)
             AND re-arm met (RSI rose above rearm_rsi_level after last exit)
             → Enter at OPEN of next bar.
    - Exit 1 (SMA exit): close > exit_sma_period-day SMA → exit at OPEN of next bar.
    - Exit 2 (time stop): hold >= time_stop_days → exit at OPEN of next bar.
    - Exit 3 (stop-loss): close <= entry_fill * (1 - stop_loss_pct) → exit at stop price.

    Exit priority: stop-loss (intraday/close) is evaluated within the day.
    SMA exit and time stop are queued and execute at next bar's open.
    Stop-loss uses entry_fill_price (raw open fill, pre-cost) as the stop baseline.

    Returns:
        trade_log (list of dicts), equity (pd.Series), daily_df (pd.DataFrame)
    """
    rsi_entry_thresh = params["rsi_entry_threshold"]
    time_stop_days = params["time_stop_days"]
    stop_loss_pct = params["stop_loss_pct"]
    rearm_rsi = params["rearm_rsi_level"]
    init_cash = float(params["init_cash"])

    close_s = spy_df["Close"]
    open_s = spy_df["Open"]
    vol_s = spy_df["Volume"]
    dates = spy_df.index
    n = len(dates)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_pos = False
    pending_entry = False       # entry signal: enter at next bar's OPEN
    pending_open_exit = False   # SMA/time-stop exit queued: exit at next bar's OPEN
    pending_exit_reason = ""
    rearm_needed = False        # re-arm gate: must see RSI > rearm_rsi after each exit

    # State for the active position
    entry_bar_idx = -1
    entry_fill_price = 0.0      # raw open fill (used for stop-loss threshold calc)
    entry_eff_price = 0.0       # effective entry price after costs (used for PnL)
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_date_ts = None

    for i in range(n):
        date = dates[i]
        open_i = float(open_s.iloc[i])
        close_i = float(close_s.iloc[i])
        rsi_i_raw = rsi_vals.iloc[i]
        rsi_i = float(rsi_i_raw) if not pd.isna(rsi_i_raw) else np.nan
        regime_i_raw = sma_regime.iloc[i]
        regime_i = bool(regime_i_raw) if not pd.isna(regime_i_raw) else False
        exit_sma_i_raw = exit_sma_vals.iloc[i]
        exit_sma_i = float(exit_sma_i_raw) if not pd.isna(exit_sma_i_raw) else np.nan

        exit_triggered = False

        # ── Step 1: Enter at today's OPEN if entry signal queued ──────────────
        if not in_pos and pending_entry:
            if open_i > 0 and not pd.isna(open_i):
                shares = int(capital / open_i)
                if shares > 0:
                    cost, liq = _transaction_cost(open_i, shares, close_s, vol_s, i)
                    # Add cost to entry price (buyer pays spread + impact)
                    eff_ep = open_i + cost / shares
                    capital -= eff_ep * shares
                    in_pos = True
                    entry_bar_idx = i
                    entry_fill_price = open_i     # raw fill, no costs — stop-loss baseline
                    entry_eff_price = eff_ep
                    entry_shares = shares
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_date_ts = date
            pending_entry = False

        # ── Step 2: Exit at today's OPEN if SMA/time-stop was queued ─────────
        # Must not be on the same bar we entered (entry_bar_idx check)
        if in_pos and pending_open_exit and not exit_triggered:
            if i > entry_bar_idx and open_i > 0 and not pd.isna(open_i):
                xcost, xliq = _transaction_cost(open_i, entry_shares, close_s, vol_s, i)
                # Seller receives open minus transaction costs
                eff_xp = open_i - xcost / entry_shares
                pnl = (eff_xp - entry_eff_price) * entry_shares
                capital += eff_xp * entry_shares

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
                    "hold_days": i - entry_bar_idx,
                    "exit_reason": pending_exit_reason,
                    "regime_active_at_entry": regime_i,
                })

                in_pos = False
                exit_triggered = True
                rearm_needed = True

            pending_open_exit = False
            pending_exit_reason = ""

        # ── Step 3: Check stop-loss against today's CLOSE ────────────────────
        # Uses entry_fill_price (raw open fill) as the stop-loss baseline.
        # Exit at stop_price = entry_fill * (1 - stop_loss_pct) — more realistic
        # than close, since the stop-order would fill at the trigger level.
        if in_pos and not exit_triggered:
            stop_threshold = entry_fill_price * (1.0 - stop_loss_pct)
            if close_i <= stop_threshold:
                stop_fill = stop_threshold   # assume stop fills at trigger, not lower close
                xcost, xliq = _transaction_cost(stop_fill, entry_shares, close_s, vol_s, i)
                eff_xp = stop_fill - xcost / entry_shares
                pnl = (eff_xp - entry_eff_price) * entry_shares
                capital += eff_xp * entry_shares

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
                    "hold_days": i - entry_bar_idx,
                    "exit_reason": "STOP_LOSS",
                    "regime_active_at_entry": regime_i,
                })

                in_pos = False
                exit_triggered = True
                pending_open_exit = False
                pending_exit_reason = ""
                rearm_needed = True

        # ── Step 4: Queue exit condition for next bar ─────────────────────────
        # Time stop takes priority over SMA exit in labeling (SMA may also have fired).
        if in_pos and not exit_triggered:
            hold_days = i - entry_bar_idx  # 0 on entry day, 1 next day, etc.

            # Time stop: hold_days >= time_stop_days → sell at next bar's open
            if hold_days >= time_stop_days:
                if not pending_open_exit:
                    pending_open_exit = True
                    pending_exit_reason = "TIME_STOP"
            # SMA exit: SPY closes above exit_sma → sell at next bar's open
            elif not pd.isna(exit_sma_i) and close_i > exit_sma_i:
                if not pending_open_exit:
                    pending_open_exit = True
                    pending_exit_reason = "SMA_EXIT"

        # ── Step 5: Re-arm check ──────────────────────────────────────────────
        # After closing a position, wait for RSI to bounce above rearm_rsi_level (50)
        # before allowing the next entry. Raised from H34's 40 to prevent chasing
        # consecutive entries in multi-day declines.
        if rearm_needed and not pd.isna(rsi_i) and rsi_i > rearm_rsi:
            rearm_needed = False

        # ── Step 6: Queue entry signal for next bar ───────────────────────────
        # Only valid when: in cash, no pending entry, no pending open exit (avoids
        # entering and immediately exiting on back-to-back bars), re-arm cleared,
        # RSI(2) < threshold (20), and SPY is above its 200-SMA (regime gate).
        if not in_pos and not pending_entry and not pending_open_exit:
            if (not rearm_needed and not pd.isna(rsi_i) and rsi_i < rsi_entry_thresh
                    and regime_i):
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
            "hold_days": (n - 1) - entry_bar_idx,
            "exit_reason": "END_OF_DATA",
            "regime_active_at_entry": bool(sma_regime.iloc[n - 1]) if n > 0 else False,
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
    All metrics are annualised to TRADING_DAYS_PER_YEAR (252).
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
    Download SPY data, compute RSI(2) and SMA indicators on warmup-inclusive
    series, trim to backtest window, and simulate H34b.

    Parameters
    ----------
    start : str  Backtest start date (YYYY-MM-DD). IS = "2007-01-01".
    end   : str  Backtest end date (YYYY-MM-DD). IS = "2021-12-31".
    params : dict, optional  Override PARAMETERS. Uses module PARAMETERS if None.

    Returns
    -------
    dict  Standardised result: sharpe, max_drawdown, total_return, win_rate,
          profit_factor, trade_count, trades_per_year, pf1_status,
          trades (DataFrame), equity (Series), daily_df (DataFrame),
          data_quality (dict), params (dict), regime_pct (float).
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    sma_period = params["sma_period"]
    init_cash = float(params["init_cash"])

    # ── 1. Download with SMA warmup ────────────────────────────────────────────
    spy_full = download_data(ticker, start, end, sma_period)

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 2. Compute indicators on warmup-inclusive series (avoids NaN at start) ─
    rsi_full = compute_rsi(spy_full["Close"], params["rsi_period"])
    regime_full = compute_sma_regime(spy_full["Close"], sma_period)
    exit_sma_full = spy_full["Close"].rolling(params["exit_sma_period"]).mean()

    # ── 3. Trim all series to backtest window ──────────────────────────────────
    mask = (spy_full.index >= ts_start) & (spy_full.index <= ts_end)
    spy_df = spy_full.loc[mask].copy()
    rsi_aligned = rsi_full.loc[mask]
    regime_aligned = regime_full.loc[mask]
    exit_sma_aligned = exit_sma_full.loc[mask]

    if len(spy_df) < 10:
        raise ValueError(
            f"Insufficient SPY data after trimming to {start}–{end}: {len(spy_df)} bars"
        )

    # Warn if SMA warmup left NaN regime values at the start of backtest
    regime_na = int(regime_aligned.isna().sum())
    if regime_na > 0:
        warnings.warn(
            f"Regime series has {regime_na} NaN values at backtest start — "
            f"warmup may be insufficient for sma_period={sma_period}"
        )

    # ── 4. Data quality checks ─────────────────────────────────────────────────
    na_count = int(spy_df["Close"].isna().sum())
    max_gap = 0
    if spy_df["Close"].isna().any():
        is_na = spy_df["Close"].isna().astype(int)
        max_gap = int(is_na.groupby((~spy_df["Close"].isna()).cumsum()).sum().max())
    if max_gap >= 5:
        warnings.warn(f"Data gap: {max_gap} consecutive missing days in {ticker}")

    # ── 5. Pre-flight trade count check (Engineering Note from hypothesis) ─────
    # IS (2007-2021) should produce >= 250 trades; if < 200, alert for threshold review.
    # This check is informational — final validation is done by the Backtest Runner.

    # ── 6. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h34b(
        spy_df, rsi_aligned, regime_aligned, exit_sma_aligned, params
    )

    # ── 7. Build trade DataFrame ───────────────────────────────────────────────
    empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason", "regime_active_at_entry",
    ]
    trades_df = (
        pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)
    )

    # ── 8. Performance metrics ─────────────────────────────────────────────────
    metrics = _compute_metrics(equity, trades_df, start, end)

    # Regime stats: fraction of backtest days where regime was active (SPY > 200-SMA)
    regime_pct = round(float(regime_aligned.mean()), 4) if len(regime_aligned) > 0 else 0.0

    # Exit reason breakdown
    exit_breakdown: dict = {}
    if not trades_df.empty:
        exit_breakdown = trades_df["exit_reason"].value_counts().to_dict()

    # Pre-flight trade count alert (hypothesis spec: >= 250 IS trades required)
    is_window = (start == "2007-01-01" and end == "2021-12-31")
    if is_window and metrics["trade_count"] < 200:
        warnings.warn(
            f"H34b PRE-FLIGHT ALERT: IS trade count {metrics['trade_count']} < 200 — "
            f"hypothesis spec requires >= 250 trades for statistical significance. "
            f"Consider raising rsi_entry_threshold to 25."
        )

    print(
        f"\nH34b RSI(2) Oversold SPY Backtest (threshold={params['rsi_entry_threshold']}) "
        f"({start} to {end}):\n"
        f"  Regime (SPY > {sma_period}-SMA) active: {regime_pct:.1%} of backtest days\n"
        f"  Trades: {metrics['trade_count']} ({metrics['trades_per_year']}/yr)"
        f" — PF-1: {metrics['pf1_status']}\n"
        f"  Sharpe: {metrics['sharpe']} | Max DD: {metrics['max_drawdown']:.2%}"
        f" | Total Return: {metrics['total_return']:.2%}\n"
        f"  Win rate: {metrics['win_rate']:.2%}"
        f" | Profit factor: {metrics['profit_factor']:.2f}\n"
        f"  Exit reasons: {exit_breakdown}\n"
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
            "survivorship_bias_flag": "SPY is a market ETF — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "warmup_bars": sma_period + 30,
            "gap_flags": ([f"{max_gap} consecutive missing days"] if max_gap >= 5 else []),
            "na_close_count": na_count,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY still active",
        },
        "regime_pct": regime_pct,
        "exit_breakdown": exit_breakdown,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H34b.

    Returns a DataFrame with per-day columns:
        date, position, rsi, regime_active, equity,
        pnl, entry_price, exit_price, transaction_cost, exit_reason

    Trade-level fields (pnl, entry_price, exit_price, transaction_cost, exit_reason)
    are populated on the exit date of each trade; all other rows carry NaN.
    `ticker` is ignored — H34b uses SPY via PARAMETERS["ticker"].
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
    # IS period: 2007–2021 (Gate 1 assessment window)
    # Pre-flight check: should produce >= 250 trades (hypothesis requirement)
    is_result = run_backtest("2007-01-01", "2021-12-31")
    print("\nH34b IS Sample trades (first 10):")
    if not is_result["trades"].empty:
        print(is_result["trades"].head(10).to_string(index=False))
    print(f"\nIS equity final: ${is_result['equity'].iloc[-1]:,.2f}")
    print(f"IS regime active: {is_result['regime_pct']:.1%} of days")
    print(f"IS exit breakdown: {is_result['exit_breakdown']}")
    print(f"IS trade count: {is_result['trade_count']} "
          f"({'PASS' if is_result['trade_count'] >= 250 else 'WARN: < 250 — check threshold'})")

    # OOS period: 2022–2025
    print("\n" + "=" * 60)
    oos_result = run_backtest("2022-01-01", "2025-12-31")
    print(f"\nOOS equity final: ${oos_result['equity'].iloc[-1]:,.2f}")
    print(f"OOS regime active: {oos_result['regime_pct']:.1%} of days")
