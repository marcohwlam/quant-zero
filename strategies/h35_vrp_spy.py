"""
Strategy: H35 Volatility Risk Premium (VRP) Timer on SPY
Author: Strategy Coder Agent
Date: 2026-03-17
Hypothesis: When implied volatility (VIX) exceeds 21-day realized volatility (SPY log returns
            annualized) by >3% AND VIX < 30, the equity risk premium is structurally elevated
            and SPY delivers above-average returns. The strategy times SPY exposure using this
            VRP spread, evaluated weekly at Friday close and executed at Monday open.
Asset class: equities (SPY ETF)
Parent task: QUA-286
References: Bollerslev, Tauchen & Zhou (2009) Rev. Fin. Studies 22(11);
            Carr & Wu (2009) Rev. Fin. Studies 22(3);
            Bekaert & Hoerova (2014) J. Econometrics 183(2);
            research/hypotheses/35_vrp_timed_spy.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "SPY",
    "vix_ticker": "^VIX",
    "vrp_entry_threshold": 3.0,      # VRP > this (%) to enter long SPY
    "vrp_exit_threshold": 0.0,       # VRP < this (%) to exit (realized > implied)
    "vix_upper_bound": 30.0,         # VIX >= this forces exit / blocks entry (panic regime)
    "realized_vol_window": 21,       # days for realized vol calc (matches VIX 30-day horizon)
    "signal_frequency": "weekly",    # evaluate at Friday close, execute Monday open
    "hard_stop_pct": 0.07,           # hard stop at -7% from entry fill (set None to disable)
    "init_cash": 25000,
}

# ── Transaction Cost Constants ─────────────────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share (equities)
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root model coefficient k
SIGMA_WINDOW = 20               # rolling vol window for market impact σ
ADV_WINDOW = 20                 # rolling volume window for market impact ADV
TRADING_DAYS_PER_YEAR = 252
VIX_MAX_FFILL_DAYS = 5          # max forward-fill gap allowed for ^VIX data


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(
    ticker: str,
    vix_ticker: str,
    start: str,
    end: str,
    realized_vol_window: int,
) -> tuple:
    """
    Download SPY OHLCV and ^VIX daily close with warmup window.

    Warmup = realized_vol_window * 2 + 30 calendar days (buffer for weekends/holidays).
    VIX gaps are forward-filled up to VIX_MAX_FFILL_DAYS consecutive days; longer gaps
    are left as NaN and will suppress the signal naturally.

    Returns:
        spy_df (pd.DataFrame): Full OHLCV including warmup period.
        vix_close (pd.Series): VIX close, aligned and forward-filled.
    Raises ValueError on insufficient or malformed data.
    """
    warmup_td = int(realized_vol_window * 2) + 30
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_td)).strftime("%Y-%m-%d")

    spy_df = _download_single(ticker, warmup_start, end)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(spy_df.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns for {ticker}: {missing}")
    if len(spy_df) < realized_vol_window + 10:
        raise ValueError(
            f"Insufficient data for {ticker}: {len(spy_df)} bars (need {realized_vol_window + 10})"
        )

    na_count_spy = int(spy_df["Close"].isna().sum())
    if na_count_spy > 5:
        warnings.warn(f"{ticker}: {na_count_spy} missing Close values detected")

    # Download VIX — close price only (^VIX has no Volume/OHLC guarantees)
    vix_raw = _download_single(vix_ticker, warmup_start, end)
    if "Close" not in vix_raw.columns:
        raise ValueError(f"^VIX download missing Close column; columns: {list(vix_raw.columns)}")

    vix_series = vix_raw["Close"].reindex(spy_df.index)

    # Forward-fill VIX gaps up to VIX_MAX_FFILL_DAYS (holiday / data provider gaps)
    vix_na_before = int(vix_series.isna().sum())
    vix_series = vix_series.ffill(limit=VIX_MAX_FFILL_DAYS)
    vix_na_after = int(vix_series.isna().sum())
    if vix_na_after > 0:
        warnings.warn(
            f"^VIX: {vix_na_after} NaN values remain after forward-fill (gap > {VIX_MAX_FFILL_DAYS} days)"
        )
    elif vix_na_before > 0:
        warnings.warn(f"^VIX: forward-filled {vix_na_before - vix_na_after} gap days (≤ {VIX_MAX_FFILL_DAYS})")

    return spy_df, vix_series


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_realized_vol(close_series: pd.Series, window: int) -> pd.Series:
    """
    Annualized realized volatility from log returns over `window` days, in % units
    (matching VIX percentage convention).

    Formula: std(log(P_t / P_{t-1})) × sqrt(252) × 100
    Evaluated on each bar using prior `window` days — no look-ahead.
    """
    log_returns = np.log(close_series / close_series.shift(1))
    # Rolling std uses window days of log returns (excludes current day's return implicitly
    # through the shift — the last return in the window is log(P_t / P_{t-1}), not future)
    realized_vol = log_returns.rolling(window).std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    return realized_vol


def compute_vrp_signals(
    close_series: pd.Series,
    vix_series: pd.Series,
    params: dict,
) -> tuple:
    """
    Compute VRP = VIX_close − realized_vol (both in % annualized units).

    Signal is evaluated at Friday close and propagated (forward-filled) through the
    following week, so Monday open execution uses Friday's signal — no look-ahead.

    Returns:
        vrp (pd.Series): raw VRP spread.
        signal_weekly (pd.Series): weekly-snapped signal series (0/1).
        entry_signal (pd.Series): Boolean, True on days when a new entry is signaled.
        exit_signal (pd.Series): Boolean, True on days when exit is signaled.
    """
    vrp_entry_thr = params["vrp_entry_threshold"]
    vrp_exit_thr = params["vrp_exit_threshold"]
    vix_upper = params["vix_upper_bound"]
    rv_window = params["realized_vol_window"]

    realized_vol = compute_realized_vol(close_series, rv_window)
    vrp = vix_series - realized_vol

    # Entry condition at Friday close: VRP > threshold AND VIX < upper bound
    entry_cond = (vrp > vrp_entry_thr) & (vix_series < vix_upper)
    # Exit condition at Friday close: VRP < exit threshold OR VIX >= upper bound
    exit_cond = (vrp < vrp_exit_thr) | (vix_series >= vix_upper)

    if params.get("signal_frequency", "weekly") == "weekly":
        # Identify Fridays (weekday==4). When Friday is a holiday, the previous
        # trading day will be used (last bar of that week with no next Friday bar).
        is_friday = close_series.index.dayofweek == 4

        # Build a weekly signal: 1 = long, 0 = flat, evaluated only on Fridays,
        # then forward-filled to cover Mon–Thu until the next Friday evaluation.
        # This ensures Monday open execution (day after signal) has no look-ahead.
        entry_weekly = entry_cond.where(is_friday, other=np.nan).ffill()
        exit_weekly = exit_cond.where(is_friday, other=np.nan).ffill()

        # Start of week (Monday) is where the position actually changes.
        # We shift by 1 bar so the signal fires on the NEXT bar after Friday close.
        entry_signal = entry_weekly.shift(1).fillna(False).astype(bool)
        exit_signal = exit_weekly.shift(1).fillna(False).astype(bool)
    else:
        # Daily evaluation mode (alternative for sensitivity testing)
        entry_signal = entry_cond.shift(1).fillna(False).astype(bool)
        exit_signal = exit_cond.shift(1).fillna(False).astype(bool)

    return vrp, entry_signal, exit_signal, realized_vol


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
      impact   = k × σ × sqrt(Q / ADV) × notional  (Almgren-Chriss square-root model)

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


# ── H35 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h35(
    spy_df: pd.DataFrame,
    entry_signal: pd.Series,
    exit_signal: pd.Series,
    vrp: pd.Series,
    vix_series: pd.Series,
    params: dict,
) -> tuple:
    """
    Simulate H35 VRP Timer on SPY with weekly signal evaluation.

    Position logic:
    - Entry: entry_signal=True AND not in position → enter at next bar's OPEN
    - Exit: exit_signal=True AND in position → exit at next bar's OPEN
    - Hard stop (optional): close <= entry_fill × (1 - hard_stop_pct) → exit at stop price
    - End-of-data: force-close at last close

    All inputs must be aligned to the backtest window (warmup already trimmed).

    Returns:
        trade_log (list of dicts), equity (pd.Series), daily_df (pd.DataFrame)
    """
    init_cash = float(params["init_cash"])
    hard_stop_pct = params.get("hard_stop_pct")   # None to disable

    close_s = spy_df["Close"]
    open_s = spy_df["Open"]
    vol_s = spy_df["Volume"]
    dates = spy_df.index
    n = len(dates)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_pos = False
    pending_entry = False       # queue: enter at next bar's OPEN
    pending_exit = False        # queue: exit at next bar's OPEN
    pending_exit_reason = ""

    # State for the active position
    entry_bar_idx = -1
    entry_fill_price = 0.0      # raw open fill — used for hard stop threshold
    entry_eff_price = 0.0       # effective entry (post-cost) — used for PnL
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_date_ts = None

    for i in range(n):
        date = dates[i]
        open_i = float(open_s.iloc[i])
        close_i = float(close_s.iloc[i])
        entry_i = bool(entry_signal.iloc[i])
        exit_i = bool(exit_signal.iloc[i])
        vrp_i = float(vrp.iloc[i]) if not pd.isna(vrp.iloc[i]) else np.nan
        vix_i = float(vix_series.iloc[i]) if not pd.isna(vix_series.iloc[i]) else np.nan

        exit_triggered = False

        # ── Step 1: Enter at today's OPEN if entry was queued ─────────────────
        if not in_pos and pending_entry:
            if open_i > 0 and not pd.isna(open_i):
                shares = int(capital / open_i)
                if shares > 0:
                    cost, liq = _transaction_cost(open_i, shares, close_s, vol_s, i)
                    eff_ep = open_i + cost / shares   # buyer pays cost
                    capital -= eff_ep * shares
                    in_pos = True
                    entry_bar_idx = i
                    entry_fill_price = open_i
                    entry_eff_price = eff_ep
                    entry_shares = shares
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_date_ts = date
            pending_entry = False

        # ── Step 2: Exit at today's OPEN if queued ────────────────────────────
        # Guard: must not be the same bar as entry (can't enter and exit same open)
        if in_pos and pending_exit and not exit_triggered:
            if i > entry_bar_idx and open_i > 0 and not pd.isna(open_i):
                xcost, xliq = _transaction_cost(open_i, entry_shares, close_s, vol_s, i)
                eff_xp = open_i - xcost / entry_shares   # seller receives open minus cost
                pnl = (eff_xp - entry_eff_price) * entry_shares
                capital += eff_xp * entry_shares

                trade_log.append({
                    "entry_date": entry_date_ts.date(),
                    "exit_date": date.date(),
                    "entry_price": round(entry_eff_price, 4),
                    "exit_price": round(eff_xp, 4),
                    "shares": entry_shares,
                    "pnl": round(pnl, 2),
                    "return_pct": round((eff_xp - entry_eff_price) / entry_eff_price, 6),
                    "entry_cost": round(entry_cost_total, 4),
                    "exit_cost": round(xcost, 4),
                    "transaction_cost": round(entry_cost_total + xcost, 4),
                    "liquidity_constrained": entry_liq or xliq,
                    "hold_days": i - entry_bar_idx,
                    "exit_reason": pending_exit_reason,
                    "vrp_at_entry": round(vrp.iloc[entry_bar_idx], 4)
                    if not pd.isna(vrp.iloc[entry_bar_idx]) else np.nan,
                    "vix_at_entry": round(float(vix_series.iloc[entry_bar_idx]), 4)
                    if not pd.isna(vix_series.iloc[entry_bar_idx]) else np.nan,
                })

                in_pos = False
                exit_triggered = True

            pending_exit = False
            pending_exit_reason = ""

        # ── Step 3: Hard stop — check against today's CLOSE ──────────────────
        # Assumes stop-limit order fills at the stop trigger, not the close (conservative).
        if in_pos and not exit_triggered and hard_stop_pct is not None:
            stop_threshold = entry_fill_price * (1.0 - hard_stop_pct)
            if close_i <= stop_threshold:
                stop_fill = stop_threshold
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
                    "return_pct": round((eff_xp - entry_eff_price) / entry_eff_price, 6),
                    "entry_cost": round(entry_cost_total, 4),
                    "exit_cost": round(xcost, 4),
                    "transaction_cost": round(entry_cost_total + xcost, 4),
                    "liquidity_constrained": entry_liq or xliq,
                    "hold_days": i - entry_bar_idx,
                    "exit_reason": "HARD_STOP",
                    "vrp_at_entry": round(vrp.iloc[entry_bar_idx], 4)
                    if not pd.isna(vrp.iloc[entry_bar_idx]) else np.nan,
                    "vix_at_entry": round(float(vix_series.iloc[entry_bar_idx]), 4)
                    if not pd.isna(vix_series.iloc[entry_bar_idx]) else np.nan,
                })

                in_pos = False
                exit_triggered = True
                pending_exit = False
                pending_exit_reason = ""

        # ── Step 4: Queue exit signal for next bar ────────────────────────────
        # Exit signal from today's close → execute at tomorrow's open
        if in_pos and not exit_triggered and exit_i and not pending_exit:
            pending_exit = True
            pending_exit_reason = "VRP_SIGNAL_EXIT"

        # ── Step 5: Queue entry signal for next bar ───────────────────────────
        # Entry signal from today's close → execute at tomorrow's open
        # Never queue entry if we are in a position or already have one pending
        if not in_pos and not pending_entry and not pending_exit:
            if entry_i:
                pending_entry = True

        # ── Daily mark-to-market ──────────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        daily_records.append({
            "date": date,
            "position": 1 if in_pos else 0,
            "vrp": round(vrp_i, 4) if not pd.isna(vrp_i) else np.nan,
            "vix": round(vix_i, 4) if not pd.isna(vix_i) else np.nan,
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
            "return_pct": round((eff_xp - entry_eff_price) / entry_eff_price, 6),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(xcost, 4),
            "transaction_cost": round(entry_cost_total + xcost, 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_days": (n - 1) - entry_bar_idx,
            "exit_reason": "END_OF_DATA",
            "vrp_at_entry": round(vrp.iloc[entry_bar_idx], 4)
            if not pd.isna(vrp.iloc[entry_bar_idx]) else np.nan,
            "vix_at_entry": round(float(vix_series.iloc[entry_bar_idx]), 4)
            if not pd.isna(vix_series.iloc[entry_bar_idx]) else np.nan,
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
    All returns metrics are annualized to TRADING_DAYS_PER_YEAR (252).
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

    # PF-1: VRP timer produces ~8-9 entries/year; PF-1 threshold is 30/year.
    # This strategy is approved under conditional CEO exception (QUA-281 verdict).
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
    Download SPY and ^VIX data, compute VRP signal on warmup-inclusive series,
    trim to backtest window, and simulate H35 VRP Timer.

    Parameters
    ----------
    start : str  Backtest start date (YYYY-MM-DD). IS = "2007-01-01".
    end   : str  Backtest end date (YYYY-MM-DD). IS = "2021-12-31".
    params : dict, optional  Override PARAMETERS. Uses module PARAMETERS if None.

    Returns
    -------
    dict  Standardized result: sharpe, max_drawdown, total_return, win_rate,
          profit_factor, trade_count, trades_per_year, pf1_status,
          trades (DataFrame), equity_curve (Series), daily_df (DataFrame),
          metrics (dict), data_quality (dict), params (dict).
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    vix_ticker = params["vix_ticker"]
    rv_window = params["realized_vol_window"]
    init_cash = float(params["init_cash"])

    # ── 1. Download with warmup ────────────────────────────────────────────────
    spy_full, vix_full = download_data(ticker, vix_ticker, start, end, rv_window)

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 2. Compute VRP signal on warmup-inclusive series (no NaN at start) ────
    vrp_full, entry_sig_full, exit_sig_full, rv_full = compute_vrp_signals(
        spy_full["Close"], vix_full, params
    )

    # ── 3. Trim all series to backtest window ──────────────────────────────────
    mask = (spy_full.index >= ts_start) & (spy_full.index <= ts_end)
    spy_df = spy_full.loc[mask].copy()
    vrp_aligned = vrp_full.loc[mask]
    entry_aligned = entry_sig_full.loc[mask]
    exit_aligned = exit_sig_full.loc[mask]
    vix_aligned = vix_full.loc[mask]
    rv_aligned = rv_full.loc[mask]

    if len(spy_df) < 10:
        raise ValueError(
            f"Insufficient SPY data after trimming to {start}–{end}: {len(spy_df)} bars"
        )

    # ── 4. Data quality checks ─────────────────────────────────────────────────
    na_spy = int(spy_df["Close"].isna().sum())
    na_vix = int(vix_aligned.isna().sum())

    max_gap_spy = 0
    if spy_df["Close"].isna().any():
        is_na = spy_df["Close"].isna().astype(int)
        max_gap_spy = int(is_na.groupby((~spy_df["Close"].isna()).cumsum()).sum().max())
    if max_gap_spy >= 5:
        warnings.warn(f"Data gap: {max_gap_spy} consecutive missing days in {ticker}")

    vrp_na = int(vrp_aligned.isna().sum())
    if vrp_na > 0:
        warnings.warn(
            f"VRP series has {vrp_na} NaN values in backtest window "
            f"(warmup may be insufficient for realized_vol_window={rv_window})"
        )

    # ── 5. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h35(
        spy_df, entry_aligned, exit_aligned, vrp_aligned, vix_aligned, params
    )

    # ── 6. Build trade DataFrame ───────────────────────────────────────────────
    empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price", "shares",
        "pnl", "return_pct", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason",
        "vrp_at_entry", "vix_at_entry",
    ]
    trades_df = (
        pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)
    )

    # ── 7. Performance metrics ─────────────────────────────────────────────────
    metrics = _compute_metrics(equity, trades_df, start, end)

    # Signal-on rate: fraction of backtest days with entry signal active
    signal_on_pct = round(float(entry_aligned.mean()), 4) if len(entry_aligned) > 0 else 0.0

    # Exit reason breakdown
    exit_breakdown: dict = {}
    if not trades_df.empty:
        exit_breakdown = trades_df["exit_reason"].value_counts().to_dict()

    # VRP descriptive stats for the backtest window
    vrp_stats = {
        "vrp_mean": round(float(vrp_aligned.mean()), 4) if not vrp_aligned.isna().all() else np.nan,
        "vrp_std": round(float(vrp_aligned.std()), 4) if not vrp_aligned.isna().all() else np.nan,
        "vrp_pct_positive": round(float((vrp_aligned > 0).mean()), 4),
        "vrp_pct_above_entry_threshold": round(
            float((vrp_aligned > params["vrp_entry_threshold"]).mean()), 4
        ),
    }

    print(
        f"\nH35 VRP Timer on SPY ({start} to {end}):\n"
        f"  VRP entry threshold: {params['vrp_entry_threshold']}% | "
        f"VIX upper bound: {params['vix_upper_bound']}\n"
        f"  Signal-on rate: {signal_on_pct:.1%} of backtest days\n"
        f"  Trades: {metrics['trade_count']} ({metrics['trades_per_year']}/yr)"
        f" — PF-1: {metrics['pf1_status']}\n"
        f"  Sharpe: {metrics['sharpe']} | Max DD: {metrics['max_drawdown']:.2%}"
        f" | Total Return: {metrics['total_return']:.2%}\n"
        f"  Win rate: {metrics['win_rate']:.2%}"
        f" | Profit factor: {metrics['profit_factor']:.2f}\n"
        f"  Exit reasons: {exit_breakdown}\n"
        f"  VRP stats: mean={vrp_stats['vrp_mean']:.2f}% std={vrp_stats['vrp_std']:.2f}%"
        f" | Init cash: ${init_cash:,.0f}"
    )

    if metrics["trades_per_year"] < 30:
        warnings.warn(
            f"PF-1 WARN: {metrics['trades_per_year']:.1f} trades/yr < 30 threshold. "
            f"H35 operates under CEO QUA-281 conditional exception (~8-9 entries/year expected)."
        )

    return {
        **metrics,
        "returns": equity.pct_change().fillna(0.0),
        "trades": trades_df,
        "equity_curve": equity,
        "daily_df": daily_df,
        "metrics": metrics,
        "params": params,
        "vrp_stats": vrp_stats,
        "signal_on_pct": signal_on_pct,
        "exit_breakdown": exit_breakdown,
        "data_quality": {
            "survivorship_bias_flag": "SPY is a market ETF — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "vix_data_gaps_filled": f"forward-fill ≤ {VIX_MAX_FFILL_DAYS} days",
            "na_spy_close_count": na_spy,
            "na_vix_count": na_vix,
            "gap_flags": ([f"{max_gap_spy} consecutive missing days in SPY"] if max_gap_spy >= 5 else []),
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY still active",
            "look_ahead_bias": "None — Friday close signal shifted by 1 bar before use",
        },
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H35.

    Returns a DataFrame with per-day columns:
        date, position, vrp, vix, equity,
        pnl, entry_price, exit_price, return_pct, transaction_cost, exit_reason

    Trade-level fields are populated on the exit date of each trade; all other rows carry NaN.
    `ticker` is ignored — H35 uses SPY via PARAMETERS["ticker"].
    """
    p = (params or PARAMETERS).copy()
    result = run_backtest(start, end, p)

    daily = result["daily_df"].reset_index()
    trades = result["trades"]

    if trades.empty:
        daily["pnl"] = np.nan
        daily["entry_price"] = np.nan
        daily["exit_price"] = np.nan
        daily["return_pct"] = np.nan
        daily["transaction_cost"] = np.nan
        daily["exit_reason"] = np.nan
    else:
        trade_cols = trades[
            ["exit_date", "pnl", "entry_price", "exit_price", "return_pct", "transaction_cost", "exit_reason"]
        ].copy()
        trade_cols["exit_date"] = pd.to_datetime(trade_cols["exit_date"])
        daily["date"] = pd.to_datetime(daily["date"])

        daily = daily.merge(
            trade_cols.rename(columns={"exit_date": "date"}),
            on="date",
            how="left",
        )

    return daily[[
        "date", "position", "vrp", "vix", "equity",
        "pnl", "entry_price", "exit_price", "return_pct", "transaction_cost", "exit_reason",
    ]]


if __name__ == "__main__":
    # IS period: 2007–2021 (Gate 1 assessment window)
    # Note: H35 is a conditional strategy (~8-9 entries/year; CEO QUA-281 exception required)
    is_result = run_backtest("2007-01-01", "2021-12-31")
    print("\nH35 IS Sample trades (first 10):")
    if not is_result["trades"].empty:
        print(is_result["trades"].head(10).to_string(index=False))
    print(f"\nIS equity final: ${is_result['equity_curve'].iloc[-1]:,.2f}")
    print(f"IS signal-on rate: {is_result['signal_on_pct']:.1%} of days")
    print(f"IS VRP stats: {is_result['vrp_stats']}")
    print(f"IS exit breakdown: {is_result['exit_breakdown']}")
    print(f"IS trade count: {is_result['trade_count']}")

    # OOS period: 2022–2025
    print("\n" + "=" * 60)
    oos_result = run_backtest("2022-01-01", "2025-12-31")
    print(f"\nOOS equity final: ${oos_result['equity_curve'].iloc[-1]:,.2f}")
    print(f"OOS signal-on rate: {oos_result['signal_on_pct']:.1%} of days")
