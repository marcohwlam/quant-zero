"""
Strategy: H70b Multi-ETF Small-Cap RSI-4 Mean Reversion Basket
Author: Strategy Coder Agent (via Engineering Director — QUA-306)
Date: 2026-06-16
Hypothesis: IWM + IJH + VB + IJR RSI-4 < 25 in Stage 2 uptrend fires extreme short-term
            oversold signals across correlated but independently-gated small/mid-cap ETFs.
            Basket expands H70's signal count from ~4.6/yr to ~26/yr (4 ETFs × 6.5/yr),
            fixing the WF trade-count failure while preserving the confirmed edge.
Asset class: equities (ETF basket — 4 instruments)
Parent tasks: QUA-305, QUA-306
References: Connors & Alvarez (2009, 2012); Weinstein (1988) §3; Elder (1993) §7.3;
            research/hypotheses/70b_multi_etf_smallcap_rsi4_mean_reversion.md
Slippage: IWM 0.005% ultra-liquid (ED-SLIP-001); IJH/VB/IJR 0.05% standard canonical
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

TICKERS = ["IWM", "IJH", "VB", "IJR"]

# Per-ticker slippage: IWM ultra-liquid (ED-SLIP-001), others standard
SLIPPAGE_BY_TICKER = {
    "IWM": 0.00005,   # 0.005% one-way
    "IJH": 0.0005,    # 0.05% one-way
    "VB":  0.0005,    # 0.05% one-way
    "IJR": 0.0005,    # 0.05% one-way
}

FIXED_COST_PER_SHARE = 0.005    # $0.005/share each side
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root model k
SIGMA_WINDOW = 20
ADV_WINDOW = 20
TRADING_DAYS_PER_YEAR = 252

PARAMETERS = {
    "tickers": ["IWM", "IJH", "VB", "IJR"],
    "rsi_period": 4,
    "rsi_entry_threshold": 25,          # RSI-4 < 25; sweep-validated in QUA-300
    "sma_period": 200,                  # Weinstein Stage 2 gate (per instrument)
    "rsi_exit_threshold": 65,           # Exit when RSI-4 > 65
    "high_exit_lookback": 5,            # Exit when close > max(close[-5..-1])
    "stop_loss_pct": 0.075,             # 7.5% hard stop
    "max_hold_days": 15,
    "position_risk_pct": 0.02,          # Elder 2% rule
    "max_notional_pct_per_instrument": 0.30,  # 30% per ETF cap
    "portfolio_notional_cap": 0.80,           # 80% total portfolio cap
    "init_cash": 25000,
}


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data_multi(
    tickers: list,
    start: str,
    end: str,
    sma_period: int,
) -> dict:
    """
    Download OHLCV for all tickers with warmup window for SMA.
    Returns dict[ticker -> DataFrame].
    Raises ValueError if any ticker is missing required columns or insufficient data.
    """
    warmup_td = int(sma_period * 1.5) + 30
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
        if len(raw) < sma_period + 10:
            raise ValueError(f"Insufficient data for {t}: {len(raw)} bars")
        na_count = int(raw["Close"].isna().sum())
        if na_count > 5:
            warnings.warn(f"{t}: {na_count} missing Close values in download range")
        result[t] = raw
    return result


# ── Technical Indicators ───────────────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 4) -> pd.Series:
    """Wilder RSI via EWM com=period-1. Prevents div-by-zero with 1e-10 offset."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    return 100 - (100 / (1 + gain / (loss + 1e-10)))


def compute_sma_regime(close_series: pd.Series, sma_period: int) -> pd.Series:
    """Weinstein Stage 2: prior-day close > prior-day SMA. No look-ahead bias."""
    sma = close_series.rolling(sma_period).mean()
    return close_series.shift(1) > sma.shift(1)


def compute_prior_high(close_series: pd.Series, lookback: int = 5) -> pd.Series:
    """Max close over prior N bars (strictly prior — no same-bar look-ahead)."""
    return close_series.shift(1).rolling(lookback).max()


def compute_indicators_multi(
    dfs: dict,
    sma_period: int,
    rsi_period: int,
    high_lookback: int,
) -> dict:
    """
    For each ticker, compute RSI, regime gate, and prior-high on the warmup-inclusive series.
    Returns dict[ticker -> {"rsi": pd.Series, "regime": pd.Series, "prior_high": pd.Series}].
    """
    indicators = {}
    for t, df in dfs.items():
        close = df["Close"]
        indicators[t] = {
            "rsi": compute_rsi(close, rsi_period),
            "regime": compute_sma_regime(close, sma_period),
            "prior_high": compute_prior_high(close, high_lookback),
        }
    return indicators


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    ticker: str,
    fill_price: float,
    shares: int,
    df: pd.DataFrame,
    idx: int,
) -> tuple:
    """
    Per-ticker transaction cost model.
    IWM: 0.005% slippage (ED-SLIP-001 ultra-liquid).
    IJH/VB/IJR: 0.05% slippage (canonical standard).
    + fixed $0.005/share + Almgren-Chriss market impact.
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
        adv = 500_000 if ticker != "IWM" else 50_000_000

    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * fill_price * shares
    liq_constrained = bool(shares / adv > 0.01)
    if liq_constrained:
        warnings.warn(f"Liquidity-constrained: {ticker} {shares} shares ({shares/adv:.2%} ADV) idx={idx}")

    return fixed + slippage + impact, liq_constrained


# ── Position Sizing ────────────────────────────────────────────────────────────

def _elder_position_size(
    entry_fill: float,
    account_equity: float,
    stop_loss_pct: float,
    position_risk_pct: float,
    max_notional_pct: float,
) -> int:
    """
    Elder 2% Rule: risk max 2% of equity per trade.
    Capped at max_notional_pct (30%) concentration limit per instrument.
    """
    if entry_fill <= 0 or account_equity <= 0:
        return 0
    risk_per_share = entry_fill * stop_loss_pct
    max_risk = account_equity * position_risk_pct
    shares = int(max_risk / risk_per_share) if risk_per_share > 0 else 0
    max_notional_shares = int(account_equity * max_notional_pct / entry_fill)
    return max(0, min(shares, max_notional_shares))


# ── Gap Attribution Helper ─────────────────────────────────────────────────────

def _gap_flags(entry_ts: pd.Timestamp, exit_ts: pd.Timestamp, hold_days: int) -> tuple:
    o_gap = bool(hold_days >= 1)
    day_range = pd.date_range(entry_ts, exit_ts, freq="D")
    w_gap = bool(any(d.dayofweek >= 5 for d in day_range))
    return o_gap, w_gap


# ── H70b Multi-ETF Simulation Engine ──────────────────────────────────────────

def simulate_h70b(
    all_dfs: dict,
    all_indicators: dict,
    common_dates: pd.DatetimeIndex,
    params: dict,
) -> tuple:
    """
    Simulate H70b RSI-4 multi-ETF mean reversion basket.

    All inputs must be aligned to common_dates (backtest window, indicators already warm).
    Entry/exit logic is per-instrument independent; portfolio notional cap enforced globally.

    Entry (per instrument, evaluated at EOD, executed at T+1 open):
        RSI-4 < rsi_entry_threshold AND close > 200-SMA (per instrument)
        → Skip if portfolio_notional + new_pos > 80% × equity

    Exit priority (first trigger wins per instrument):
        1. Pending open exit (RSI > 65 or 5-day high) → T+1 open
        2. Hard stop (close ≤ entry × 0.925) → at stop price
        3. Max hold (15 bars) → T+1 open

    Returns (trade_log, equity, daily_df).
    """
    tickers = params["tickers"]
    rsi_entry_thresh = params["rsi_entry_threshold"]
    rsi_exit_thresh = params["rsi_exit_threshold"]
    stop_loss_pct = params["stop_loss_pct"]
    max_hold_days = params["max_hold_days"]
    position_risk_pct = params["position_risk_pct"]
    max_notional_pct = params["max_notional_pct_per_instrument"]
    portfolio_cap = params["portfolio_notional_cap"]
    capital = float(params["init_cash"])

    # ── Per-instrument state ──────────────────────────────────────────────────
    in_pos          = {t: False   for t in tickers}
    pending_entry   = {t: False   for t in tickers}
    pending_exit    = {t: False   for t in tickers}
    exit_reason_q   = {t: ""      for t in tickers}
    bar_entry_idx   = {t: -1      for t in tickers}
    fill_price_raw  = {t: 0.0     for t in tickers}  # raw open fill (stop baseline)
    fill_price_eff  = {t: 0.0     for t in tickers}  # fill + costs (PnL baseline)
    pos_shares      = {t: 0       for t in tickers}
    pos_cost        = {t: 0.0     for t in tickers}
    pos_liq         = {t: False   for t in tickers}
    entry_date_ts   = {t: None    for t in tickers}
    entry_regime_f  = {t: False   for t in tickers}

    trade_log = []
    daily_records = []
    n = len(common_dates)

    def _safe_val(df: pd.DataFrame, col: str, date: pd.Timestamp):
        try:
            v = df.loc[date, col]
            return float(v) if not pd.isna(v) else None
        except (KeyError, TypeError):
            return None

    def _safe_ind(ind_series: pd.Series, date: pd.Timestamp):
        try:
            v = ind_series.loc[date]
            return None if pd.isna(v) else v
        except (KeyError, TypeError):
            return None

    for i, date in enumerate(common_dates):

        # ── Step A: Process pending open exits (free capital before entries) ──
        for t in tickers:
            if not in_pos[t] or not pending_exit[t]:
                continue
            if i <= bar_entry_idx[t]:
                # Can't exit on same bar as entry
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

        # ── Step B: Portfolio notional at this bar (close approximation) ──────
        # Use current open prices as proxy for entry-time notional
        cur_notional = 0.0
        for t in tickers:
            if in_pos[t]:
                open_i = _safe_val(all_dfs[t], "Open", date)
                if open_i and open_i > 0:
                    cur_notional += pos_shares[t] * open_i
        account_equity = capital + cur_notional

        # ── Step C: Process pending entries (portfolio cap check) ─────────────
        for t in tickers:
            if in_pos[t] or not pending_entry[t]:
                pending_entry[t] = False
                continue
            open_i = _safe_val(all_dfs[t], "Open", date)
            if open_i is None or open_i <= 0:
                pending_entry[t] = False
                continue

            shares = _elder_position_size(
                open_i, account_equity, stop_loss_pct, position_risk_pct, max_notional_pct
            )
            if shares <= 0:
                pending_entry[t] = False
                continue

            new_notional = shares * open_i
            if cur_notional + new_notional > portfolio_cap * account_equity:
                # Portfolio cap breached — skip this trade
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
            entry_regime_f[t] = bool(_safe_ind(all_indicators[t]["regime"], date))

            cur_notional += new_notional
            account_equity = capital + cur_notional
            pending_entry[t] = False

        # ── Step D: Stop-loss check (close vs stop threshold) ─────────────────
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

        # ── Step E: Queue exit conditions for next bar ────────────────────────
        for t in tickers:
            if not in_pos[t] or pending_exit[t]:
                continue
            rsi_i = _safe_ind(all_indicators[t]["rsi"], date)
            close_i = _safe_val(all_dfs[t], "Close", date)
            ph_i = _safe_ind(all_indicators[t]["prior_high"], date)
            hold = i - bar_entry_idx[t]

            if rsi_i is not None and rsi_i > rsi_exit_thresh:
                pending_exit[t] = True
                exit_reason_q[t] = "RSI_EXIT"
            elif ph_i is not None and close_i is not None and close_i > ph_i:
                pending_exit[t] = True
                exit_reason_q[t] = "HIGH_EXIT"
            elif hold >= max_hold_days:
                pending_exit[t] = True
                exit_reason_q[t] = "MAX_HOLD"

        # ── Step F: Queue entry signals for next bar ──────────────────────────
        for t in tickers:
            if in_pos[t] or pending_entry[t]:
                continue
            rsi_i = _safe_ind(all_indicators[t]["rsi"], date)
            regime_i = _safe_ind(all_indicators[t]["regime"], date)
            if rsi_i is not None and regime_i and rsi_i < rsi_entry_thresh:
                pending_entry[t] = True

        # ── Step G: Mark-to-market portfolio ──────────────────────────────────
        portfolio_notional = 0.0
        for t in tickers:
            if in_pos[t]:
                close_i = _safe_val(all_dfs[t], "Close", date)
                if close_i and close_i > 0:
                    portfolio_notional += pos_shares[t] * close_i
        mtm_equity = capital + portfolio_notional
        n_open = sum(1 for t in tickers if in_pos[t])

        rsi_vals_cur = {
            t: _safe_ind(all_indicators[t]["rsi"], date)
            for t in tickers
        }
        daily_records.append({
            "date": date,
            "equity": mtm_equity,
            "n_positions": n_open,
            "portfolio_notional": portfolio_notional,
            "cap_active": (portfolio_notional > portfolio_cap * mtm_equity * 0.5),
            **{f"rsi_{t.lower()}": rsi_vals_cur[t] for t in tickers},
        })

    # ── Force-close all open positions at end of data ─────────────────────────
    if common_dates is not None and n > 0:
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

    win_rate, profit_factor = 0.0, 0.0
    if n_trades > 0:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        gross_wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
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
    """Per-ticker disaggregation: trade count, Sharpe proxy, PpT, win rate."""
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
        # Simple Sharpe proxy from trade PnLs
        pnls = sub["pnl"].values
        sharpe_proxy = float(pnls.mean() / (pnls.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR / (max(sub["hold_days"].mean(), 1))))
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
    Download all 4 ETFs, compute indicators on warmup-inclusive series, trim to backtest
    window (common dates), and simulate H70b multi-ETF basket.

    Parameters
    ----------
    start : str  Backtest start (YYYY-MM-DD). IS = "2005-01-01".
    end   : str  Backtest end (YYYY-MM-DD). IS = "2018-12-31".
    params : dict, optional  Override PARAMETERS. Uses module PARAMETERS if None.

    Returns
    -------
    dict  Standardized result with sharpe, max_drawdown, win_rate, profit_factor,
          trade_count, trades_per_year, trades DataFrame, equity Series, daily_df,
          per_instrument_stats, regime_pct_by_ticker, gap_attribution, exit_breakdown.
    """
    if params is None:
        params = PARAMETERS.copy()
    if "tickers" not in params:
        params["tickers"] = TICKERS

    tickers = params["tickers"]
    sma_period = params["sma_period"]
    rsi_period = params["rsi_period"]
    high_lookback = params["high_exit_lookback"]
    init_cash = float(params["init_cash"])

    # 1. Download with warmup
    all_dfs_full = download_data_multi(tickers, start, end, sma_period)

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # 2. Compute indicators on warmup-inclusive series
    all_indicators_full = compute_indicators_multi(all_dfs_full, sma_period, rsi_period, high_lookback)

    # 3. Find common dates in backtest window (intersection across all tickers)
    date_sets = [
        set(df.loc[(df.index >= ts_start) & (df.index <= ts_end)].index)
        for df in all_dfs_full.values()
    ]
    common_set = date_sets[0].intersection(*date_sets[1:])
    common_dates = pd.DatetimeIndex(sorted(common_set))

    if len(common_dates) < 10:
        raise ValueError(f"Insufficient common dates in {start}–{end}: {len(common_dates)}")

    # 4. Trim DataFrames and indicators to common_dates
    all_dfs = {t: all_dfs_full[t].loc[common_dates] for t in tickers}
    all_indicators = {}
    for t in tickers:
        all_indicators[t] = {
            k: all_indicators_full[t][k].loc[common_dates]
            for k in ("rsi", "regime", "prior_high")
        }

    # 5. Simulate
    trade_log, equity, daily_df = simulate_h70b(all_dfs, all_indicators, common_dates, params)

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

    # 9. Regime stats per ticker
    regime_pct_by_ticker = {}
    for t in tickers:
        reg = all_indicators[t]["regime"]
        regime_pct_by_ticker[t] = round(float(reg.mean()), 4)

    # 10. Exit breakdown
    exit_breakdown = {}
    if not trades_df.empty:
        exit_breakdown = trades_df["exit_reason"].value_counts().to_dict()

    # 11. Gap attribution
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

    # 12. Concurrent position analysis
    concurrent_analysis = {}
    if not daily_df.empty and "n_positions" in daily_df.columns:
        n_pos = daily_df["n_positions"]
        n_notional = daily_df.get("portfolio_notional", pd.Series(dtype=float))
        concurrent_analysis = {
            "pct_time_2plus_positions": round(float((n_pos >= 2).mean()), 4),
            "pct_time_3plus_positions": round(float((n_pos >= 3).mean()), 4),
            "avg_n_positions_when_invested": round(float(n_pos[n_pos > 0].mean()), 4) if (n_pos > 0).any() else 0.0,
            "max_simultaneous_positions": int(n_pos.max()) if not n_pos.empty else 0,
        }
        if not n_notional.empty:
            eq = daily_df["equity"]
            notional_pct = n_notional / (eq + 1e-8)
            concurrent_analysis["avg_portfolio_notional_pct"] = round(float(notional_pct.mean()), 4)
            concurrent_analysis["avg_notional_when_cap_active"] = round(
                float(notional_pct[notional_pct > params["portfolio_notional_cap"] * 0.75].mean()), 4
            ) if (notional_pct > params["portfolio_notional_cap"] * 0.75).any() else 0.0

    print(
        f"\nH70b Multi-ETF RSI-4 Basket Backtest ({start} to {end}):\n"
        f"  Tickers: {tickers}\n"
        f"  RSI-4 < {params['rsi_entry_threshold']} | Portfolio cap: {params['portfolio_notional_cap']:.0%} | Per-instr cap: {params['max_notional_pct_per_instrument']:.0%}\n"
        f"  Total trades: {metrics['trade_count']} ({metrics['trades_per_year']}/yr)\n"
        f"  Sharpe: {metrics['sharpe']} | MDD: {metrics['max_drawdown']:.2%} | Return: {metrics['total_return']:.2%}\n"
        f"  Win rate: {metrics['win_rate']:.2%} | Profit factor: {metrics['profit_factor']:.2f}\n"
        f"  Per-instrument: {per_inst}"
    )

    return {
        **metrics,
        "returns": equity.pct_change().fillna(0.0),
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params,
        "per_instrument_stats": per_inst,
        "regime_pct_by_ticker": regime_pct_by_ticker,
        "exit_breakdown": exit_breakdown,
        "gap_attribution": gap_attribution,
        "concurrent_analysis": concurrent_analysis,
        "data_quality": {
            "survivorship_bias_flag": "ETF basket — no survivorship bias; ETFs track broad indices",
            "price_adjusted": True,
            "auto_adjust": True,
            "tickers": tickers,
            "common_dates_count": len(common_dates),
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — all 4 ETFs currently active",
        },
        "metadata": {
            "hypothesis": "H70b",
            "slippage_model": "mixed: IWM ultra-liquid ED-SLIP-001 + canonical standard for IJH/VB/IJR",
            "ruling_ref": "ED-SLIP-001",
        },
    }


if __name__ == "__main__":
    is_result = run_backtest("2005-01-01", "2018-12-31")
    print(f"\nIS equity final: ${is_result['equity'].iloc[-1]:,.2f}")
    print(f"IS per-instrument: {is_result['per_instrument_stats']}")
    print(f"IS concurrent analysis: {is_result['concurrent_analysis']}")
    oos_result = run_backtest("2019-01-01", "2024-12-31")
    print(f"\nOOS equity final: ${oos_result['equity'].iloc[-1]:,.2f}")
    print(f"OOS per-instrument: {oos_result['per_instrument_stats']}")
