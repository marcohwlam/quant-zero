"""
Strategy: H76 Multi-ETF RSI-2 Daily Mean Reversion Portfolio
Author: Engineering Director (QUA-323)
Date: 2026-06-17
Hypothesis: 12-ETF daily RSI(2) < 5 signals extreme oversold across diversified
            sector ETFs. SPY 200-DMA portfolio-level regime filter blocks entries
            in sustained downtrends. Equal-weight 25% per position, max 4 concurrent.
            High signal frequency (~1000 IS trades) addresses QUA-283 trade-count failure.
Asset class: equities (ETF basket — 12 instruments)
Parent task: QUA-323
References: Connors & Alvarez (2009) "Short Term Trading Strategies That Work";
            Weinstein (1988) §3 (200-DMA trend filter);
            research/hypotheses/h76_multi_etf_rsi2_daily_mean_reversion.md
Slippage: SPY/QQQ/IWM 0.005% ultra-liquid (ED-SLIP-001);
          all other ETFs 0.05% standard canonical
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

TICKERS = ["SPY", "QQQ", "IWM", "XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB"]

ULTRA_LIQUID = {"SPY", "QQQ", "IWM"}

SLIPPAGE_BY_TICKER = {t: 0.00005 if t in ULTRA_LIQUID else 0.0005 for t in TICKERS}

FIXED_COST_PER_SHARE = 0.005
MARKET_IMPACT_K = 0.1
SIGMA_WINDOW = 20
ADV_WINDOW = 20
TRADING_DAYS_PER_YEAR = 252

PARAMETERS = {
    "tickers": TICKERS,
    "rsi_period": 2,
    "rsi_entry_threshold": 5,     # RSI(2) < 5 → buy next open
    "rsi_exit_threshold": 65,     # Exit when RSI(2) > 65
    "spy_dma_period": 200,        # Portfolio-level SPY regime gate
    "stop_loss_pct": 0.05,        # 5% hard stop per position
    "max_hold_days": 5,           # 5-bar max hold
    "max_positions": 4,           # Max concurrent positions
    "position_weight": 0.25,      # Equal-weight 25% of equity per position
    "init_cash": 100_000,         # Larger capital to handle 12-ETF basket
}


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data_multi(
    tickers: list,
    start: str,
    end: str,
    dma_period: int,
) -> dict:
    """
    Download OHLCV for all tickers with warmup window for DMA.
    Returns dict[ticker -> DataFrame].
    Raises ValueError on missing columns or insufficient data.
    """
    warmup_td = int(dma_period * 1.5) + 30
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_td)).strftime("%Y-%m-%d")

    result = {}
    for t in tickers:
        raw = yf.download(t, start=warmup_start, end=end, auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        required = {"Open", "High", "Low", "Close", "Volume"}
        missing = required - set(raw.columns)
        if missing:
            raise ValueError(f"Missing OHLCV columns for {t}: {missing}")
        if len(raw) < dma_period + 10:
            raise ValueError(f"Insufficient data for {t}: {len(raw)} bars")
        na_count = int(raw["Close"].isna().sum())
        if na_count > 5:
            warnings.warn(f"{t}: {na_count} missing Close values")
        result[t] = raw
    return result


# ── Technical Indicators ───────────────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 2) -> pd.Series:
    """Wilder RSI via EWM com=period-1. Prevents div-by-zero with 1e-10 offset."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    return 100 - (100 / (1 + gain / (loss + 1e-10)))


def compute_spy_regime(spy_close: pd.Series, dma_period: int) -> pd.Series:
    """
    Portfolio-level SPY regime: prior-day close > prior-day 200-DMA.
    No look-ahead: both close and DMA are shifted by 1.
    """
    dma = spy_close.rolling(dma_period).mean()
    return spy_close.shift(1) > dma.shift(1)


def compute_indicators_multi(
    dfs: dict,
    dma_period: int,
    rsi_period: int,
) -> tuple:
    """
    Compute per-ticker RSI and portfolio-level SPY regime gate.
    Returns (rsi_dict, spy_regime_series).
    rsi_dict[ticker] = pd.Series of RSI values.
    spy_regime_series = pd.Series (True = regime active, entries allowed).
    """
    rsi_dict = {}
    for t, df in dfs.items():
        rsi_dict[t] = compute_rsi(df["Close"], rsi_period)

    spy_regime = compute_spy_regime(dfs["SPY"]["Close"], dma_period)
    return rsi_dict, spy_regime


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    ticker: str,
    fill_price: float,
    shares: int,
    df: pd.DataFrame,
    idx: int,
) -> tuple:
    """
    Transaction cost: fixed + slippage + Almgren-Chriss market impact.
    SPY/QQQ/IWM: 0.005% slippage (ED-SLIP-001 ultra-liquid).
    All others: 0.05% standard canonical.
    Returns (total_cost_dollars, liquidity_constrained_bool).
    """
    slippage_pct = SLIPPAGE_BY_TICKER[ticker]
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = slippage_pct * fill_price * shares

    close_s = df["Close"]
    vol_s = df["Volume"]
    sigma = close_s.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_s.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 50_000_000 if ticker in ULTRA_LIQUID else 500_000

    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * fill_price * shares
    liq_constrained = bool(shares / adv > 0.01)
    if liq_constrained:
        warnings.warn(f"Liquidity-constrained: {ticker} {shares} shares idx={idx}")

    return fixed + slippage + impact, liq_constrained


# ── Position Sizing ────────────────────────────────────────────────────────────

def _equal_weight_shares(
    open_price: float,
    account_equity: float,
    position_weight: float,
) -> int:
    """Equal-weight sizing: 25% of equity per position, at current open price."""
    if open_price <= 0 or account_equity <= 0:
        return 0
    target_notional = account_equity * position_weight
    return max(0, int(target_notional / open_price))


# ── Gap Attribution Helper ─────────────────────────────────────────────────────

def _gap_flags(entry_ts: pd.Timestamp, exit_ts: pd.Timestamp, hold_days: int) -> tuple:
    o_gap = bool(hold_days >= 1)
    day_range = pd.date_range(entry_ts, exit_ts, freq="D")
    w_gap = bool(any(d.dayofweek >= 5 for d in day_range))
    return o_gap, w_gap


# ── H76 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h76(
    all_dfs: dict,
    rsi_dict: dict,
    spy_regime: pd.Series,
    common_dates: pd.DatetimeIndex,
    params: dict,
) -> tuple:
    """
    Simulate H76 RSI-2 multi-ETF mean reversion (12 ETFs, 4 max concurrent positions).

    Entry (evaluated at EOD close, executed at T+1 open):
        RSI(2) < rsi_entry_threshold AND SPY 200-DMA regime active
        AND n_open_positions < max_positions
        → buy at next open (equal-weight 25% of equity)

    Exit priority (first trigger wins per instrument):
        1. Pending open exit (RSI > 65 OR max_hold reached) → T+1 open
        2. Hard stop (close ≤ entry_raw × (1 - stop_loss_pct)) → at stop price same bar

    Returns (trade_log, equity, daily_df).
    """
    tickers = params["tickers"]
    rsi_entry_thresh = params["rsi_entry_threshold"]
    rsi_exit_thresh  = params["rsi_exit_threshold"]
    stop_loss_pct    = params["stop_loss_pct"]
    max_hold_days    = params["max_hold_days"]
    max_positions    = params["max_positions"]
    position_weight  = params["position_weight"]
    capital          = float(params["init_cash"])

    in_pos         = {t: False for t in tickers}
    pending_entry  = {t: False for t in tickers}
    pending_exit   = {t: False for t in tickers}
    exit_reason_q  = {t: ""   for t in tickers}
    bar_entry_idx  = {t: -1   for t in tickers}
    fill_price_raw = {t: 0.0  for t in tickers}
    fill_price_eff = {t: 0.0  for t in tickers}
    pos_shares     = {t: 0    for t in tickers}
    pos_cost       = {t: 0.0  for t in tickers}
    pos_liq        = {t: False for t in tickers}
    entry_date_ts  = {t: None for t in tickers}
    entry_regime_f = {t: False for t in tickers}

    trade_log = []
    daily_records = []
    n = len(common_dates)

    def _safe_val(df, col, date):
        try:
            v = df.loc[date, col]
            return float(v) if not pd.isna(v) else None
        except (KeyError, TypeError):
            return None

    def _safe_ind(series, date):
        try:
            v = series.loc[date]
            return None if pd.isna(v) else v
        except (KeyError, TypeError):
            return None

    for i, date in enumerate(common_dates):

        # ── Step A: Process pending open exits ────────────────────────────────
        for t in tickers:
            if not in_pos[t] or not pending_exit[t]:
                continue
            if i <= bar_entry_idx[t]:
                continue
            open_i = _safe_val(all_dfs[t], "Open", date)
            if open_i is None or open_i <= 0:
                continue

            xcost, xliq = _transaction_cost(t, open_i, pos_shares[t], all_dfs[t], i)
            eff_xp = open_i - xcost / pos_shares[t]
            pnl = (eff_xp - fill_price_eff[t]) * pos_shares[t]
            capital += eff_xp * pos_shares[t]

            hold = i - bar_entry_idx[t]
            og, wg = _gap_flags(entry_date_ts[t], date, hold)
            trade_log.append({
                "ticker": t,
                "entry_date": entry_date_ts[t].date(),
                "exit_date": date.date(),
                "entry_price": round(fill_price_eff[t], 4),
                "exit_price": round(eff_xp, 4),
                "shares": pos_shares[t],
                "pnl": round(pnl, 2),
                "entry_cost": round(pos_cost[t], 4),
                "exit_cost": round(xcost, 4),
                "transaction_cost": round(pos_cost[t] + xcost, 4),
                "liquidity_constrained": pos_liq[t] or xliq,
                "hold_days": hold,
                "exit_reason": exit_reason_q[t],
                "regime_active_at_entry": entry_regime_f[t],
                "overnight_gap": og,
                "weekend_gap": wg,
            })
            in_pos[t] = False
            pending_exit[t] = False
            exit_reason_q[t] = ""

        # ── Step B: Compute current portfolio state ───────────────────────────
        n_open = sum(1 for t in tickers if in_pos[t])
        cur_notional = 0.0
        for t in tickers:
            if in_pos[t]:
                open_i = _safe_val(all_dfs[t], "Open", date)
                if open_i and open_i > 0:
                    cur_notional += pos_shares[t] * open_i
        account_equity = capital + cur_notional

        # ── Step C: Process pending entries ───────────────────────────────────
        for t in tickers:
            if in_pos[t] or not pending_entry[t]:
                pending_entry[t] = False
                continue
            if n_open >= max_positions:
                pending_entry[t] = False
                continue
            open_i = _safe_val(all_dfs[t], "Open", date)
            if open_i is None or open_i <= 0:
                pending_entry[t] = False
                continue

            shares = _equal_weight_shares(open_i, account_equity, position_weight)
            if shares <= 0:
                pending_entry[t] = False
                continue

            cost, liq = _transaction_cost(t, open_i, shares, all_dfs[t], i)
            eff_ep = open_i + cost / shares
            capital -= eff_ep * shares

            in_pos[t]         = True
            bar_entry_idx[t]  = i
            fill_price_raw[t] = open_i
            fill_price_eff[t] = eff_ep
            pos_shares[t]     = shares
            pos_cost[t]       = cost
            pos_liq[t]        = liq
            entry_date_ts[t]  = date
            entry_regime_f[t] = bool(_safe_ind(spy_regime, date))

            cur_notional += shares * open_i
            n_open += 1
            account_equity = capital + cur_notional
            pending_entry[t] = False

        # ── Step D: Stop-loss check (using close) ─────────────────────────────
        for t in tickers:
            if not in_pos[t]:
                continue
            close_i = _safe_val(all_dfs[t], "Close", date)
            if close_i is None:
                continue
            stop_threshold = fill_price_raw[t] * (1.0 - stop_loss_pct)
            if close_i <= stop_threshold:
                stop_fill = stop_threshold
                xcost, xliq = _transaction_cost(t, stop_fill, pos_shares[t], all_dfs[t], i)
                eff_xp = stop_fill - xcost / pos_shares[t]
                pnl = (eff_xp - fill_price_eff[t]) * pos_shares[t]
                capital += eff_xp * pos_shares[t]

                hold = i - bar_entry_idx[t]
                og, wg = _gap_flags(entry_date_ts[t], date, hold)
                trade_log.append({
                    "ticker": t,
                    "entry_date": entry_date_ts[t].date(),
                    "exit_date": date.date(),
                    "entry_price": round(fill_price_eff[t], 4),
                    "exit_price": round(eff_xp, 4),
                    "shares": pos_shares[t],
                    "pnl": round(pnl, 2),
                    "entry_cost": round(pos_cost[t], 4),
                    "exit_cost": round(xcost, 4),
                    "transaction_cost": round(pos_cost[t] + xcost, 4),
                    "liquidity_constrained": pos_liq[t] or xliq,
                    "hold_days": hold,
                    "exit_reason": "STOP_LOSS",
                    "regime_active_at_entry": entry_regime_f[t],
                    "overnight_gap": og,
                    "weekend_gap": wg,
                })
                in_pos[t] = False
                pending_exit[t] = False
                exit_reason_q[t] = ""
                n_open = max(0, n_open - 1)

        # ── Step E: Queue exit conditions for next bar ────────────────────────
        for t in tickers:
            if not in_pos[t] or pending_exit[t]:
                continue
            rsi_i  = _safe_ind(rsi_dict[t], date)
            hold   = i - bar_entry_idx[t]
            if rsi_i is not None and rsi_i > rsi_exit_thresh:
                pending_exit[t] = True
                exit_reason_q[t] = "RSI_EXIT"
            elif hold >= max_hold_days:
                pending_exit[t] = True
                exit_reason_q[t] = "MAX_HOLD"

        # ── Step F: Queue entry signals for next bar ──────────────────────────
        regime_active = bool(_safe_ind(spy_regime, date))
        if regime_active:
            for t in tickers:
                if in_pos[t] or pending_entry[t]:
                    continue
                rsi_i = _safe_ind(rsi_dict[t], date)
                if rsi_i is not None and rsi_i < rsi_entry_thresh:
                    pending_entry[t] = True

        # ── Step G: Mark-to-market ────────────────────────────────────────────
        portfolio_notional = 0.0
        for t in tickers:
            if in_pos[t]:
                close_i = _safe_val(all_dfs[t], "Close", date)
                if close_i and close_i > 0:
                    portfolio_notional += pos_shares[t] * close_i
        mtm_equity = capital + portfolio_notional
        n_open_g = sum(1 for t in tickers if in_pos[t])

        daily_records.append({
            "date": date,
            "equity": mtm_equity,
            "n_positions": n_open_g,
            "portfolio_notional": portfolio_notional,
            "spy_regime_active": regime_active,
        })

    # ── Force-close all open positions at end ─────────────────────────────────
    if n > 0:
        date_f = common_dates[-1]
        for t in tickers:
            if in_pos[t]:
                close_f = _safe_val(all_dfs[t], "Close", date_f)
                if close_f and close_f > 0:
                    xcost, xliq = _transaction_cost(t, close_f, pos_shares[t], all_dfs[t], n - 1)
                    eff_xp = close_f - xcost / pos_shares[t]
                    pnl = (eff_xp - fill_price_eff[t]) * pos_shares[t]
                    capital += eff_xp * pos_shares[t]
                    hold = (n - 1) - bar_entry_idx[t]
                    og, wg = _gap_flags(entry_date_ts[t], date_f, hold)
                    trade_log.append({
                        "ticker": t,
                        "entry_date": entry_date_ts[t].date(),
                        "exit_date": date_f.date(),
                        "entry_price": round(fill_price_eff[t], 4),
                        "exit_price": round(eff_xp, 4),
                        "shares": pos_shares[t],
                        "pnl": round(pnl, 2),
                        "entry_cost": round(pos_cost[t], 4),
                        "exit_cost": round(xcost, 4),
                        "transaction_cost": round(pos_cost[t] + xcost, 4),
                        "liquidity_constrained": pos_liq[t] or xliq,
                        "hold_days": hold,
                        "exit_reason": "END_OF_DATA",
                        "regime_active_at_entry": entry_regime_f[t],
                        "overnight_gap": og,
                        "weekend_gap": wg,
                    })

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")
    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df


# ── Performance Metrics ────────────────────────────────────────────────────────

def _compute_metrics(equity: pd.Series, trades_df: pd.DataFrame, start: str, end: str) -> dict:
    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)
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

    win_rate = profit_factor = 0.0
    if n_trades > 0:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        gross_wins   = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        gross_losses = abs(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum())
        profit_factor = round(float(gross_wins / max(gross_losses, 1e-8)), 4)

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
    }


def _per_instrument_stats(trades_df: pd.DataFrame, years: float) -> dict:
    if trades_df.empty:
        return {}
    stats = {}
    for t in trades_df["ticker"].unique():
        sub = trades_df[trades_df["ticker"] == t]
        n = len(sub)
        if n == 0:
            continue
        avg_entry = sub["entry_price"].mean()
        total_shares = sub["shares"].sum()
        avg_pnl_per_share = sub["pnl"].sum() / total_shares if total_shares > 0 else 0.0
        ppt_bps = (avg_pnl_per_share / avg_entry * 10000) if avg_entry > 0 else 0.0
        win_rate = float((sub["pnl"] > 0).mean())
        pnls = sub["pnl"].values
        avg_hold = max(sub["hold_days"].mean(), 1)
        sharpe_proxy = float(pnls.mean() / (pnls.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR / avg_hold))
        stats[t] = {
            "trade_count": n,
            "trades_per_year": round(n / max(years, 1e-3), 1),
            "win_rate": round(win_rate, 4),
            "ppt_bps": round(ppt_bps, 2),
            "sharpe_proxy": round(sharpe_proxy, 4),
            "total_pnl": round(float(sub["pnl"].sum()), 2),
        }
    return stats


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download 12 ETFs, compute RSI(2) and SPY 200-DMA regime, simulate H76.

    Parameters
    ----------
    start : str  Backtest start (YYYY-MM-DD). IS = "2005-01-01".
    end   : str  Backtest end (YYYY-MM-DD). IS = "2018-12-31".
    params : dict, optional  Override PARAMETERS.

    Returns
    -------
    dict  Standard result with sharpe, max_drawdown, win_rate, profit_factor,
          trade_count, trades_per_year, trades DataFrame, equity Series, daily_df,
          per_instrument_stats, exit_breakdown, gap_attribution, concurrent_analysis.
    """
    if params is None:
        params = PARAMETERS.copy()
    if "tickers" not in params:
        params["tickers"] = TICKERS

    tickers     = params["tickers"]
    dma_period  = params["spy_dma_period"]
    rsi_period  = params["rsi_period"]
    init_cash   = float(params["init_cash"])

    # 1. Download with warmup (SPY always included for regime)
    tickers_to_download = list(set(tickers) | {"SPY"})
    all_dfs_full = download_data_multi(tickers_to_download, start, end, dma_period)

    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)

    # 2. Compute indicators on warmup-inclusive series
    rsi_dict_full, spy_regime_full = compute_indicators_multi(all_dfs_full, dma_period, rsi_period)

    # 3. Find common dates across all tickers in backtest window
    date_sets = [
        set(df.loc[(df.index >= ts_start) & (df.index <= ts_end)].index)
        for t, df in all_dfs_full.items() if t in tickers
    ]
    common_set   = date_sets[0].intersection(*date_sets[1:])
    common_dates = pd.DatetimeIndex(sorted(common_set))

    if len(common_dates) < 10:
        raise ValueError(f"Insufficient common dates in {start}–{end}: {len(common_dates)}")

    # 4. Trim DataFrames, RSI, and regime to common_dates
    all_dfs = {t: all_dfs_full[t].loc[common_dates] for t in tickers_to_download}
    rsi_dict = {t: rsi_dict_full[t].loc[common_dates] for t in tickers_to_download}
    spy_regime = spy_regime_full.loc[common_dates]

    # Filter to strategy tickers for simulation
    sim_dfs  = {t: all_dfs[t] for t in tickers}
    sim_rsis = {t: rsi_dict[t] for t in tickers}

    # 5. Simulate
    trade_log, equity, daily_df = simulate_h76(sim_dfs, sim_rsis, spy_regime, common_dates, params)

    # 6. Build trade DataFrame
    empty_cols = [
        "ticker", "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason",
        "regime_active_at_entry", "overnight_gap", "weekend_gap",
    ]
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)

    # 7. Metrics
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    metrics = _compute_metrics(equity, trades_df, start, end)

    # 8. Per-instrument stats
    per_inst = _per_instrument_stats(trades_df, years)

    # 9. Exit breakdown
    exit_breakdown = {}
    if not trades_df.empty:
        exit_breakdown = trades_df["exit_reason"].value_counts().to_dict()

    # 10. Gap attribution
    gap_attribution = {}
    if not trades_df.empty:
        n_t = len(trades_df)
        gap_attribution = {
            "overnight_gap_trades": int(trades_df["overnight_gap"].sum()),
            "weekend_gap_trades": int(trades_df["weekend_gap"].sum()),
            "total_trades": n_t,
            "overnight_gap_pct": round(float(trades_df["overnight_gap"].mean()), 4),
            "weekend_gap_pct": round(float(trades_df["weekend_gap"].mean()), 4),
            "overnight_gap_pnl": round(float(trades_df.loc[trades_df["overnight_gap"], "pnl"].sum()), 2),
            "weekend_gap_pnl": round(float(trades_df.loc[trades_df["weekend_gap"], "pnl"].sum()), 2),
        }

    # 11. Concurrent position analysis
    concurrent_analysis = {}
    if not daily_df.empty and "n_positions" in daily_df.columns:
        n_pos = daily_df["n_positions"]
        concurrent_analysis = {
            "pct_time_2plus_positions": round(float((n_pos >= 2).mean()), 4),
            "pct_time_4plus_positions": round(float((n_pos >= 4).mean()), 4),
            "avg_n_positions_when_invested": round(float(n_pos[n_pos > 0].mean()), 4) if (n_pos > 0).any() else 0.0,
            "max_simultaneous_positions": int(n_pos.max()) if not n_pos.empty else 0,
            "pct_time_in_market": round(float((n_pos > 0).mean()), 4),
        }

    # 12. Regime stats
    spy_regime_pct = round(float(spy_regime.mean()), 4)

    print(
        f"\nH76 Multi-ETF RSI-2 Backtest ({start} to {end}):\n"
        f"  Universe: {tickers}\n"
        f"  RSI({params['rsi_period']}) < {params['rsi_entry_threshold']} | SPY {dma_period}-DMA regime: {spy_regime_pct:.1%} active\n"
        f"  Max positions: {params['max_positions']} | Weight: {params['position_weight']:.0%} | Stop: {params['stop_loss_pct']:.0%}\n"
        f"  Total trades: {metrics['trade_count']} ({metrics['trades_per_year']}/yr)\n"
        f"  Sharpe: {metrics['sharpe']} | MDD: {metrics['max_drawdown']:.2%} | Return: {metrics['total_return']:.2%}\n"
        f"  Win rate: {metrics['win_rate']:.2%} | Profit factor: {metrics['profit_factor']:.2f}\n"
        f"  Exit breakdown: {exit_breakdown}"
    )

    return {
        **metrics,
        "returns": equity.pct_change().fillna(0.0),
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params,
        "per_instrument_stats": per_inst,
        "exit_breakdown": exit_breakdown,
        "gap_attribution": gap_attribution,
        "concurrent_analysis": concurrent_analysis,
        "spy_regime_pct": spy_regime_pct,
        "data_quality": {
            "survivorship_bias_flag": "ETF basket — no survivorship bias; ETFs track broad indices",
            "price_adjusted": True,
            "auto_adjust": True,
            "tickers": tickers,
            "common_dates_count": len(common_dates),
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — all 12 ETFs currently active",
        },
        "metadata": {
            "hypothesis": "H76",
            "slippage_model": "SPY/QQQ/IWM 0.005% ultra-liquid (ED-SLIP-001); others 0.05% standard",
            "ruling_ref": "ED-SLIP-001",
        },
    }


if __name__ == "__main__":
    is_result = run_backtest("2005-01-01", "2018-12-31")
    print(f"\nIS equity final: ${is_result['equity'].iloc[-1]:,.2f}")
    print(f"IS per-instrument: {is_result['per_instrument_stats']}")
    oos_result = run_backtest("2019-01-01", "2024-12-31")
    print(f"\nOOS equity final: ${oos_result['equity'].iloc[-1]:,.2f}")
