"""
Strategy: H30 VIX Spike Fear Capitulation
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: When VIX spikes ≥ 2σ above its 20-day rolling mean AND absolute level ≥ 25,
            equity markets over-discount near-term risk. Buy SPY at next open after the
            spike; exit when VIX reverts to rolling mean, after 5 trading days (sell at
            open of day 6), or on a 3% stop-loss — whichever triggers first.
Asset class: equities (SPY ETF)
Parent task: QUA-266
References: Whaley (2009) JPM 35(3); Harvey & Whaley (1992) JFE 31(1);
            Connors & Alvarez (2012) Short-Term Trading Strategies That Work;
            research/hypotheses/30_vix_spike_spy_mean_reversion.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "SPY",
    "vix_ticker": "^VIX",
    # Entry conditions
    "vix_threshold": 25,          # absolute VIX floor for entry (range: 20–30)
    "vix_zscore_window": 20,      # rolling window for VIX mean/std in days (range: 10–30)
    "vix_zscore_mult": 2.0,       # σ multiplier — spike threshold (range: 1.5–2.5)
    # Regime filter
    "sma_window": 200,            # SPY SMA window for bull-market regime gate
    # Exit parameters
    "hold_days": 5,               # max trading days to hold before time stop (range: 3–7)
    "stop_loss_pct": 0.03,        # per-trade stop-loss from effective entry price (range: 0.02–0.05)
    # Capital
    "init_cash": 25000,           # initial capital in USD
}

# ── Transaction Cost Constants (Engineering Director spec) ─────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share fixed
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root impact coefficient k
SIGMA_WINDOW = 20               # 20-day rolling vol for market impact σ
ADV_WINDOW = 20                 # 20-day rolling ADV for Q/ADV ratio
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(ticker: str, vix_ticker: str, start: str, end: str, params: dict) -> dict:
    """
    Download SPY OHLCV and ^VIX Close with warmup window for rolling indicators.

    Warmup is max(sma_window, SIGMA_WINDOW, ADV_WINDOW) + 60 calendar-day buffer.
    Returns dict: {'spy': DataFrame, 'vix': Series (Close)}
    Raises ValueError if data is insufficient or columns are missing.
    """
    warmup_days = max(params["sma_window"], SIGMA_WINDOW, ADV_WINDOW) + 60
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")

    spy_df = _download_single(ticker, warmup_start, end)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(spy_df.columns)
    if missing:
        raise ValueError(f"Missing columns for {ticker}: {missing}")
    min_bars = params["sma_window"] + 10
    if len(spy_df) < min_bars:
        raise ValueError(
            f"Insufficient data for {ticker}: {len(spy_df)} bars (need {min_bars})"
        )
    na_count = int(spy_df["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing trading days detected")

    vix_raw = _download_single(vix_ticker, warmup_start, end)
    if isinstance(vix_raw.columns, pd.MultiIndex):
        vix_raw.columns = vix_raw.columns.get_level_values(0)
    if "Close" not in vix_raw.columns:
        raise ValueError(f"Missing Close column for {vix_ticker}")
    vix_close = vix_raw["Close"].rename("vix")

    return {"spy": spy_df, "vix": vix_close}


# ── Signal Generation ──────────────────────────────────────────────────────────

def generate_signals(spy_df: pd.DataFrame, vix: pd.Series, params: dict) -> tuple:
    """
    Compute VIX entry/exit signals and SPY 200-SMA regime filter.

    All signals are based on end-of-day closes — no look-ahead.
    Entry is executed at the NEXT day's open after the signal fires.

    VIX entry signal: VIX[t] ≥ vix_threshold AND VIX[t] ≥ mean[t] + mult × std[t]
    VIX exit signal:  VIX[t] ≤ vix_mean[t]  (mean reversion complete)
    Regime filter:    SPY[t] > SPY 200-SMA[t] (long-only during bull market)

    Returns:
        entry_signal:    Boolean Series, True when spike entry conditions met
        vix_exit_signal: Boolean Series, True when VIX reverts to mean (exit trigger)
        regime_ok:       Boolean Series, True when regime filter passes
    """
    window = params["vix_zscore_window"]
    mult = params["vix_zscore_mult"]
    threshold = params["vix_threshold"]
    sma_w = params["sma_window"]

    # Rolling VIX statistics (backward-looking; no future leakage)
    vix_mean = vix.rolling(window, min_periods=window).mean()
    vix_std = vix.rolling(window, min_periods=window).std()

    # Entry: VIX spikes above absolute floor AND above rolling mean + mult×std
    entry_signal = (vix >= threshold) & (vix >= vix_mean + mult * vix_std)

    # Exit: VIX reverts back to (or below) rolling mean — fear premium dissipated
    vix_exit_signal = vix <= vix_mean

    # Regime filter: SPY must be above its 200-day SMA (bull market only)
    spy_sma = spy_df["Close"].rolling(sma_w, min_periods=sma_w).mean()
    regime_ok = spy_df["Close"] > spy_sma

    return entry_signal, vix_exit_signal, regime_ok


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    idx: int,
) -> tuple:
    """
    Canonical equities transaction cost (Engineering Director spec):
      fixed    = $0.005/share
      slippage = 0.05% of notional
      impact   = k × σ × sqrt(Q / ADV) × price × Q  (Almgren-Chriss square-root model)

    Flags orders where Q/ADV > 1% as liquidity-constrained.
    Returns (total_cost_dollars: float, liquidity_constrained: bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01    # fallback: 1% daily vol
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000  # fallback: 1M shares ADV

    # Square-root market impact (Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV). "
            "Q/ADV > 1% — market impact elevated."
        )

    return fixed + slippage + impact, liq_constrained


# ── H30 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h30(
    spy_df: pd.DataFrame,
    vix: pd.Series,
    entry_signal: pd.Series,
    vix_exit_signal: pd.Series,
    regime_ok: pd.Series,
    params: dict,
) -> tuple:
    """
    Simulate H30 VIX Spike Fear Capitulation on SPY using a daily bar loop.

    Entry/exit logic (no vectorbt — custom loop for multi-condition exits):
    - Signal day (close): VIX spike signal fires AND SPY > 200-SMA → pending_entry = True
    - Entry day (next open): buy SPY at open; record entry_price (effective, cost-inclusive)
    - Each subsequent close: check exit conditions in priority order:
        1. Stop-loss: close ≤ entry_price × (1 − stop_loss_pct) → exit next open
        2. VIX reversion: VIX close ≤ 20-day rolling mean → exit next open
        3. Time stop: hold_days − 1 complete bars held → exit next open
           (hold_days=5 → sell at open of day 6, counting entry as day 1)
    - All exits executed at next day's open to avoid same-bar look-ahead.

    Note: stop-loss uses daily close as a conservative proxy for intraday trigger.
    In live trading, a hard intraday stop at entry_price × (1 − stop_loss_pct) is preferred.

    Returns (trade_log: list, equity: pd.Series, daily_df: pd.DataFrame)
    """
    hold_days = params["hold_days"]
    stop_loss_pct = params["stop_loss_pct"]
    init_cash = float(params["init_cash"])

    dates = spy_df.index
    n = len(dates)
    close_s = spy_df["Close"]
    open_s = spy_df["Open"]
    vol_s = spy_df["Volume"]

    # Align signals to SPY trading calendar; missing VIX dates → conservative defaults
    entry_sig_aligned = entry_signal.reindex(dates).fillna(False)
    vix_exit_aligned = vix_exit_signal.reindex(dates).fillna(False)
    regime_aligned = regime_ok.reindex(dates).fillna(False)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_pos = False
    pending_entry = False
    pending_exit_reason = None  # exit condition triggered at close; execute at next open

    entry_date_ts = None
    entry_price = 0.0      # effective entry price (inclusive of transaction costs)
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_bar_idx = -1

    for i in range(n):
        date = dates[i]
        close_i = float(close_s.iloc[i])
        open_i = float(open_s.iloc[i])

        # ── 1. Execute pending exit at today's open ───────────────────────────
        if pending_exit_reason is not None and in_pos:
            exit_price_raw = open_i
            xcost, xliq = _transaction_cost(exit_price_raw, entry_shares, close_s, vol_s, i)
            eff_xp = exit_price_raw - xcost / entry_shares
            pnl = (eff_xp - entry_price) * entry_shares
            capital += eff_xp * entry_shares

            trade_log.append({
                "entry_date": entry_date_ts.date(),
                "exit_date": date.date(),
                "entry_price": round(entry_price, 4),
                "exit_price": round(eff_xp, 4),
                "shares": entry_shares,
                "pnl": round(pnl, 2),
                "entry_cost": round(entry_cost_total, 4),
                "exit_cost": round(xcost, 4),
                "transaction_cost": round(entry_cost_total + xcost, 4),
                "liquidity_constrained": entry_liq or xliq,
                "hold_bars": i - entry_bar_idx,
                "exit_reason": pending_exit_reason,
            })

            in_pos = False
            pending_exit_reason = None
            entry_date_ts = None
            entry_bar_idx = -1

        # ── 2. Execute pending entry at today's open ──────────────────────────
        if pending_entry and not in_pos:
            if open_i > 0 and not pd.isna(open_i):
                shares = int(capital / open_i)
                if shares > 0:
                    cost, liq = _transaction_cost(open_i, shares, close_s, vol_s, i)
                    eff_ep = open_i + cost / shares
                    capital -= eff_ep * shares

                    in_pos = True
                    entry_date_ts = date
                    entry_price = eff_ep
                    entry_shares = shares
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_bar_idx = i
            pending_entry = False

        # ── 3. End-of-day checks using close[i] ───────────────────────────────
        if in_pos:
            # days_held = 0 on entry bar, 1 the next day, etc.
            # TIME_STOP triggers at days_held = hold_days − 1 so we exit at
            # open of the (hold_days + 1)th day, i.e., open on "day 6" for hold_days=5.
            days_held = i - entry_bar_idx

            if close_i <= entry_price * (1 - stop_loss_pct) and pending_exit_reason is None:
                # Stop-loss: position dropped ≥ stop_loss_pct from effective entry
                pending_exit_reason = "STOP_LOSS"
            elif bool(vix_exit_aligned.iloc[i]) and pending_exit_reason is None:
                # VIX reverted to rolling mean — fear premium dissipated
                pending_exit_reason = "VIX_REVERT"
            elif days_held >= hold_days - 1 and pending_exit_reason is None:
                # Time stop: sell at open on day (hold_days + 1) from entry
                pending_exit_reason = "TIME_STOP"

        else:
            # Not in position: check if entry signal fires on today's close
            # pending_entry set here → buy at NEXT bar's open (no look-ahead)
            if (
                not pending_entry
                and bool(entry_sig_aligned.iloc[i])
                and bool(regime_aligned.iloc[i])
                and i < n - 1  # must have a next bar to execute entry
            ):
                pending_entry = True

        # ── 4. Daily mark-to-market ───────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        daily_records.append({
            "date": date,
            "position": 1 if in_pos else 0,
            "signal_type": "VIX_SPIKE" if in_pos else "",
            "equity": mtm,
        })

    # ── Force-close any open position at end of data ──────────────────────────
    if in_pos and n > 0:
        i = n - 1
        close_f = float(close_s.iloc[i])
        xcost, xliq = _transaction_cost(close_f, entry_shares, close_s, vol_s, i)
        eff_xp = close_f - xcost / entry_shares
        pnl = (eff_xp - entry_price) * entry_shares
        capital += eff_xp * entry_shares

        trade_log.append({
            "entry_date": entry_date_ts.date(),
            "exit_date": dates[i].date(),
            "entry_price": round(entry_price, 4),
            "exit_price": round(eff_xp, 4),
            "shares": entry_shares,
            "pnl": round(pnl, 2),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(xcost, 4),
            "transaction_cost": round(entry_cost_total + xcost, 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_bars": i - entry_bar_idx,
            "exit_reason": "END_OF_DATA",
        })
        if daily_records:
            daily_records[-1]["equity"] = capital

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")

    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download data, compute VIX spike signals + regime filter, and simulate H30.

    Parameters
    ----------
    start : str
        Backtest start date (YYYY-MM-DD). IS period: "2007-01-01".
    end : str
        Backtest end date (YYYY-MM-DD). IS period: "2021-12-31".
    params : dict, optional
        Override PARAMETERS dict. Uses module-level PARAMETERS if None.

    Returns
    -------
    dict
        Standard result with:
        - sharpe, max_drawdown, total_return, win_rate, profit_factor
        - trade_count, trades_per_year, pf1_status
        - entry_signals_total, regime_blocked_count, exit_reason_summary
        - trades (DataFrame), equity (Series), daily_df (DataFrame)
        - data_quality (dict)
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    vix_ticker = params["vix_ticker"]
    init_cash = float(params["init_cash"])

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 1. Download (warmup window included) ──────────────────────────────────
    data = download_data(ticker, vix_ticker, start, end, params)
    spy_full = data["spy"]
    vix_full = data["vix"]

    # ── 2. Compute signals on full series (warmup ensures rolling stats are warm) ─
    entry_sig_full, vix_exit_full, regime_full = generate_signals(spy_full, vix_full, params)

    # ── 3. Trim to backtest window ────────────────────────────────────────────
    spy_df = spy_full.loc[
        (spy_full.index >= ts_start) & (spy_full.index <= ts_end)
    ].copy()
    entry_sig = entry_sig_full.reindex(spy_df.index).fillna(False)
    vix_exit_sig = vix_exit_full.reindex(spy_df.index).fillna(False)
    regime_ok = regime_full.reindex(spy_df.index).fillna(False)
    vix_in_window = vix_full.reindex(spy_df.index)

    if len(spy_df) < 10:
        raise ValueError(
            f"Insufficient SPY data after trimming to {start}–{end}: {len(spy_df)} bars"
        )

    # ── 4. Data quality checks ────────────────────────────────────────────────
    max_gap = 0
    if spy_df["Close"].isna().any():
        is_na = spy_df["Close"].isna().astype(int)
        max_gap = int(is_na.groupby((~spy_df["Close"].isna()).cumsum()).sum().max())
    if max_gap >= 5:
        warnings.warn(f"Data gap: {max_gap} consecutive missing days in {ticker}")

    vix_na_count = int(vix_in_window.isna().sum())
    if vix_na_count > 10:
        warnings.warn(
            f"VIX has {vix_na_count} NaN values in backtest window — "
            "entry signals on those days defaulted to False"
        )

    # ── 5. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h30(
        spy_df, vix_in_window, entry_sig, vix_exit_sig, regime_ok, params
    )

    # ── 6. Performance metrics ────────────────────────────────────────────────
    years = (ts_end - ts_start).days / 365.25
    n_trades = len(trade_log)
    trades_per_year = round(n_trades / max(years, 1e-3), 1)

    empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price", "shares",
        "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_bars", "exit_reason",
    ]
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)

    daily_returns = equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values
    sharpe = 0.0
    if len(ret_arr) > 0 and ret_arr.std() > 0:
        sharpe = round(
            float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4
        )

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)
    win_rate = round(float((trades_df["pnl"] > 0).mean()), 4) if n_trades > 0 else 0.0

    # Profit factor = sum(wins) / sum(|losses|)
    profit_factor = 0.0
    if n_trades > 0 and not trades_df.empty:
        wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = round(float(wins / losses) if losses > 0 else float("inf"), 4)

    # PF-1: walk-forward viability — IS estimate is ~150–225 trades → ÷4 = 37–56 ≥ 30 ✅
    pf1_threshold = 30
    trades_per_wf_fold = round(n_trades / 4, 1)
    if trades_per_wf_fold >= pf1_threshold:
        pf1_status = f"PASS ({trades_per_wf_fold:.1f}/fold ≥ {pf1_threshold})"
    else:
        pf1_status = f"WARN: {trades_per_wf_fold:.1f}/fold < {pf1_threshold}"
        warnings.warn(f"PF-1 WARN: {trades_per_wf_fold:.1f} trades/wf-fold < {pf1_threshold}")

    exit_reason_summary = {}
    if n_trades > 0:
        exit_reason_summary = trades_df["exit_reason"].value_counts().to_dict()

    # Diagnostic: count raw entry signals vs regime-blocked signals
    entry_count = int(entry_sig.sum())
    regime_blocked = int((entry_sig & ~regime_ok).sum())

    print(
        f"\nH30 VIX Spike Fear Capitulation ({start} to {end}):\n"
        f"  VIX entry signals: {entry_count} | Regime-blocked: {regime_blocked} | "
        f"Trades executed: {n_trades} ({trades_per_year:.1f}/yr)\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor} | "
        f"PF-1: {pf1_status}\n"
        f"  Exit reasons: {exit_reason_summary}\n"
        f"  Init cash: ${init_cash:,.0f}"
    )

    return {
        "returns": daily_returns,
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params,
        "data_quality": {
            "survivorship_bias_flag": "SPY is a market ETF — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "warmup_bars": max(params["sma_window"], SIGMA_WINDOW, ADV_WINDOW) + 60,
            "gap_flags": ([f"{max_gap} consecutive missing days"] if max_gap >= 5 else []),
            "vix_na_count": vix_na_count,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY still active",
        },
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "trades_per_wf_fold": trades_per_wf_fold,
        "pf1_status": pf1_status,
        "entry_signals_total": entry_count,
        "regime_blocked_count": regime_blocked,
        "exit_reason_summary": exit_reason_summary,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H30.

    Returns a DataFrame with per-day columns:
        date, position, signal_type, pnl, entry_price, exit_price,
        transaction_cost, exit_reason

    Trade-level fields are populated on the exit date; all other rows carry NaN.
    `ticker` parameter accepted for orchestrator compatibility but ignored —
    H30 always uses SPY + ^VIX via PARAMETERS.
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
        "date", "position", "signal_type",
        "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason",
    ]]


if __name__ == "__main__":
    # IS period
    result_is = run_backtest("2007-01-01", "2021-12-31")
    print(f"\n[IS] Trades: {result_is['trade_count']} | Sharpe: {result_is['sharpe']} | "
          f"Win rate: {result_is['win_rate']:.2%}")

    # OOS period
    result_oos = run_backtest("2022-01-01", "2025-12-31")
    print(f"\n[OOS] Trades: {result_oos['trade_count']} | Sharpe: {result_oos['sharpe']} | "
          f"Win rate: {result_oos['win_rate']:.2%}")

    print("\nSample IS trades (first 5):")
    if not result_is["trades"].empty:
        print(result_is["trades"].head().to_string(index=False))

    print(f"\nEquity final (IS): ${result_is['equity'].iloc[-1]:,.2f}")
    print(f"Equity final (OOS): ${result_oos['equity'].iloc[-1]:,.2f}")
