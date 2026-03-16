"""
Strategy: H31 IWM Small-Cap Turn-of-Month
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: Small-cap equities (IWM) exhibit a 2–3× stronger Turn-of-Month effect than
            large-cap indices. Buy IWM at the close of the last trading day of each month,
            hold through the close of the 3rd trading day of the new month. Only trade when
            IWM > 200-day SMA (bull-market regime gate).
Asset class: equities (IWM ETF)
Parent task: QUA-268
References: Ogden (1990) JF 45(4); Jacobs & Levy (1988) FAJ 44(6); Ariel (1987) JFE 18(1);
            research/hypotheses/31_iwm_smallcap_turn_of_month.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "IWM",
    # Calendar parameters
    "hold_days": 3,           # trading days to hold after last-day-of-month close (range: 2–4)
    # Regime filter
    "sma_window": 200,        # IWM SMA window for bull-market regime gate (range: 150–250)
    # Emergency stop
    "stop_loss_pct": 0.05,    # emergency exit if IWM drops > 5% from entry close (range: 3–7%)
    # Capital
    "init_cash": 25000,       # initial capital in USD
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


def download_data(ticker: str, start: str, end: str, params: dict) -> pd.DataFrame:
    """
    Download IWM OHLCV with warmup window for SMA and rolling transaction cost stats.

    Warmup = max(sma_window, SIGMA_WINDOW, ADV_WINDOW) + 60 calendar-day buffer.
    Returns DataFrame with OHLCV columns.
    Raises ValueError if data is insufficient or columns are missing.
    """
    warmup_days = max(params["sma_window"], SIGMA_WINDOW, ADV_WINDOW) + 60
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")

    df = _download_single(ticker, warmup_start, end)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns for {ticker}: {missing}")
    min_bars = params["sma_window"] + 10
    if len(df) < min_bars:
        raise ValueError(
            f"Insufficient data for {ticker}: {len(df)} bars (need {min_bars})"
        )
    na_count = int(df["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing trading days detected")

    return df


# ── Turn-of-Month Calendar ─────────────────────────────────────────────────────

def build_tom_schedule(trading_index: pd.DatetimeIndex, hold_days: int) -> dict:
    """
    Compute TOM entry/exit bar indices for all months in the data.

    Entry: last trading day of each calendar month (bar index → the close price)
    Exit:  hold_days trading bars after entry (the Nth trading day of the new month)

    The academic TOM window (Ogden 1990, Jacobs & Levy 1988) is:
        Enter close of day -1, hold through close of day +hold_days

    Returns dict: {entry_bar_idx (int): exit_bar_idx (int)}
    """
    if len(trading_index) == 0:
        return {}

    dates = list(trading_index)
    n = len(dates)

    # Find last trading day of each month by grouping by (year, month)
    month_key = [(d.year, d.month) for d in dates]
    entry_indices = {}
    for bar_idx, mk in enumerate(month_key):
        # Overwrite — final iteration per month gives the last bar
        entry_indices[mk] = bar_idx

    schedule = {}
    for mk, entry_idx in entry_indices.items():
        exit_idx = entry_idx + hold_days
        if exit_idx >= n:
            continue  # not enough data for exit; skip last partial month

        # Sanity: exit must be in the next calendar month (not same month)
        entry_date = dates[entry_idx]
        exit_date = dates[exit_idx]
        if (exit_date.year, exit_date.month) == (entry_date.year, entry_date.month):
            warnings.warn(
                f"TOM: exit bar {exit_idx} ({exit_date.date()}) is still in same month "
                f"as entry {entry_date.date()} — month has > {hold_days} trailing days. "
                "Skipping this entry."
            )
            continue

        schedule[entry_idx] = exit_idx

    return schedule


# ── Signal Generation ──────────────────────────────────────────────────────────

def compute_regime(df: pd.DataFrame, sma_window: int) -> pd.Series:
    """
    Compute IWM 200-day SMA regime filter.

    Returns Boolean Series: True when IWM > SMA (bull regime — trade allowed).
    Only defined once SMA has enough history (min_periods = sma_window).
    """
    sma = df["Close"].rolling(sma_window, min_periods=sma_window).mean()
    return df["Close"] > sma


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


# ── H31 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h31(
    iwm_df: pd.DataFrame,
    regime: pd.Series,
    tom_schedule: dict,
    params: dict,
) -> tuple:
    """
    Simulate H31 IWM Turn-of-Month using a daily bar loop.

    Entry/exit logic:
    - Entry: buy IWM at CLOSE of last trading day of month (if IWM > 200-SMA).
      Close-at-close entry captures the academic TOM premium (Ogden 1990 documents
      close-to-close returns for the TOM window).
    - Normal exit: sell IWM at CLOSE of the (hold_days)th trading day of new month.
    - Emergency stop: if any close between entry and exit drops > stop_loss_pct from
      entry close → sell at NEXT DAY'S OPEN (daily close approximation of intraday stop).
    - Only one position at a time.

    Returns (trade_log: list, equity: pd.Series, daily_df: pd.DataFrame)
    """
    stop_loss_pct = params["stop_loss_pct"]
    init_cash = float(params["init_cash"])

    dates = iwm_df.index
    n = len(dates)
    close_s = iwm_df["Close"]
    open_s = iwm_df["Open"]
    vol_s = iwm_df["Volume"]

    # Align regime to data index
    regime_aligned = regime.reindex(dates).fillna(False)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_pos = False
    pending_stop_exit = False   # stop triggered at close; execute at next open

    entry_date_ts = None
    entry_price = 0.0      # effective entry price (inclusive of transaction costs)
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_bar_idx = -1
    exit_bar_idx = -1

    # Pre-compute set of entry bars for O(1) lookup
    entry_bar_set = set(tom_schedule.keys())

    for i in range(n):
        date = dates[i]
        close_i = float(close_s.iloc[i])
        open_i = float(open_s.iloc[i])

        # ── 1. Execute pending stop-loss exit at today's open ─────────────────
        if pending_stop_exit and in_pos:
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
                "exit_reason": "STOP_LOSS",
            })

            in_pos = False
            pending_stop_exit = False
            entry_date_ts = None
            entry_bar_idx = -1
            exit_bar_idx = -1

        # ── 2. Normal exit at CLOSE on exit_bar ───────────────────────────────
        elif in_pos and i == exit_bar_idx:
            xcost, xliq = _transaction_cost(close_i, entry_shares, close_s, vol_s, i)
            eff_xp = close_i - xcost / entry_shares
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
                "exit_reason": "TOM_CLOSE",
            })

            in_pos = False
            entry_date_ts = None
            entry_bar_idx = -1
            exit_bar_idx = -1

        # ── 3. Check emergency stop for open positions ────────────────────────
        if in_pos and not pending_stop_exit and i != exit_bar_idx:
            if close_i <= entry_price * (1 - stop_loss_pct):
                # Stop hit on close; execute at next bar's open
                pending_stop_exit = True

        # ── 4. Entry at CLOSE on last-day-of-month ────────────────────────────
        # Only enter if: entry bar, not already in position, regime filter passes
        if not in_pos and not pending_stop_exit and i in entry_bar_set:
            if bool(regime_aligned.iloc[i]) and close_i > 0 and not pd.isna(close_i):
                shares = int(capital / close_i)
                if shares > 0:
                    cost, liq = _transaction_cost(close_i, shares, close_s, vol_s, i)
                    eff_ep = close_i + cost / shares
                    capital -= eff_ep * shares

                    in_pos = True
                    entry_date_ts = date
                    entry_price = eff_ep
                    entry_shares = shares
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_bar_idx = i
                    exit_bar_idx = tom_schedule[i]

        # ── 5. Daily mark-to-market ───────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        daily_records.append({
            "date": date,
            "position": 1 if in_pos else 0,
            "signal_type": "TOM" if in_pos else "",
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
    Download IWM data, build TOM calendar, apply regime filter, and simulate H31.

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
        - tom_months_in_window, regime_blocked_count, exit_reason_summary
        - trades (DataFrame), equity (Series), daily_df (DataFrame)
        - data_quality (dict)
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]
    hold_days = params["hold_days"]
    init_cash = float(params["init_cash"])

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 1. Download (warmup window included) ──────────────────────────────────
    iwm_full = download_data(ticker, start, end, params)

    # ── 2. Compute regime on full series (warmup ensures SMA is warm) ─────────
    regime_full = compute_regime(iwm_full, params["sma_window"])

    # ── 3. Trim to backtest window ────────────────────────────────────────────
    iwm_df = iwm_full.loc[
        (iwm_full.index >= ts_start) & (iwm_full.index <= ts_end)
    ].copy()
    regime = regime_full.reindex(iwm_df.index).fillna(False)

    if len(iwm_df) < 10:
        raise ValueError(
            f"Insufficient IWM data after trimming to {start}–{end}: {len(iwm_df)} bars"
        )

    # ── 4. Data quality checks ────────────────────────────────────────────────
    max_gap = 0
    if iwm_df["Close"].isna().any():
        is_na = iwm_df["Close"].isna().astype(int)
        max_gap = int(is_na.groupby((~iwm_df["Close"].isna()).cumsum()).sum().max())
    if max_gap >= 5:
        warnings.warn(f"Data gap: {max_gap} consecutive missing days in {ticker}")

    # ── 5. Build TOM schedule on trimmed window ────────────────────────────────
    tom_schedule = build_tom_schedule(iwm_df.index, hold_days)

    # Diagnostic: count regime-blocked TOM entries
    regime_blocked = 0
    for entry_idx in tom_schedule:
        if not bool(regime.iloc[entry_idx]):
            regime_blocked += 1

    tom_month_count = len(tom_schedule)

    # ── 6. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h31(iwm_df, regime, tom_schedule, params)

    # ── 7. Performance metrics ────────────────────────────────────────────────
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

    # PF-1: ~8–10 active trades/yr × 15 yr = 120–150 total → ÷4 = 30–37 ≥ 30 ✅ (borderline)
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

    print(
        f"\nH31 IWM Small-Cap Turn-of-Month ({start} to {end}):\n"
        f"  TOM months in window: {tom_month_count} | Regime-blocked: {regime_blocked} | "
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
            "survivorship_bias_flag": "IWM is a market ETF — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "warmup_bars": max(params["sma_window"], SIGMA_WINDOW, ADV_WINDOW) + 60,
            "gap_flags": ([f"{max_gap} consecutive missing days"] if max_gap >= 5 else []),
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — IWM still active",
            "tom_calendar": f"Last trading day of month (pandas groupby year-month); "
                            f"exit {hold_days} bars later",
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
        "tom_months_in_window": tom_month_count,
        "regime_blocked_count": regime_blocked,
        "exit_reason_summary": exit_reason_summary,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "IWM",
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H31.

    Returns a DataFrame with per-day columns:
        date, position, signal_type, pnl, entry_price, exit_price,
        transaction_cost, exit_reason

    Trade-level fields populated on the exit date; all other rows carry NaN.
    `ticker` parameter accepted for orchestrator compatibility but ignored —
    H31 always uses IWM via PARAMETERS.
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
