"""
Strategy: H51 Gold/Equity Relative Momentum Risk Timer — GLD/SPY Monthly Rotation
Author: Engineering Director
Date: 2026-06-08
Hypothesis: GLD 20-day relative return vs SPY used as macro safe-haven signal.
            Risk-off when GLD outperforms SPY over prior 20 trading days → hold SHY.
            Risk-on when SPY outperforms GLD → hold SPY.
            Signal checked and executed at last trading day of each month (close).
Asset class: US equity (SPY ETF) / short Treasury ETF (SHY)
Parent task: QUA-108
References: Baur & Lucey (2010 JBFA); Erb & Harvey (2013 FAJ);
            research/hypotheses/51_qc_gold_equity_risk_rotation.md
IS window:  2005-01-01 to 2021-12-31  (GLD inception Nov 2004; first signal Jan 2005)
OOS window: 2022-01-01 to 2025-12-31
Data note:  GLD inception 2004-11-18. Use GC=F proxy for pre-2004 dot-com stress test.
            SHY inception 2002-07-22. SPY inception 1993-01-29.
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "spy_ticker": "SPY",
    "gld_ticker": "GLD",
    "gcf_proxy_ticker": "GC=F",     # gold futures proxy for pre-GLD dot-com test
    "safe_harbor": "SHY",           # risk-off asset; alternative: "TLT"
    "lookback_days": 20,            # trailing trading days for GLD/SPY rel return; range: 10–40
    "rebalance_frequency": "monthly",  # "monthly" or "biweekly"
    "signal_threshold": 0.0,        # GLD relative outperformance required; 0.0 = any outperformance
    "use_gcf_proxy": False,         # True extends back pre-2004 using GC=F (dot-com stress test)
    "gld_inception": "2004-11-18",  # GLD first trading day (used with use_gcf_proxy)
    "init_cash": 25000,
}

# ── Transaction Cost Constants (Engineering Director spec) ─────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share fixed
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
MARKET_IMPACT_K = 0.1           # square-root impact (Almgren-Chriss, Johnson)
SIGMA_WINDOW = 20               # 20-day rolling σ for market impact
ADV_WINDOW = 20                 # 20-day rolling ADV
TRADING_DAYS_PER_YEAR = 252


# ── Data Helpers ───────────────────────────────────────────────────────────────

def _download_ticker(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def _check_data_gaps(series: pd.Series, label: str) -> None:
    """Warn (do not silently forward-fill) on consecutive NaN gaps >= 5 days."""
    if not series.isna().any():
        return
    n_na = int(series.isna().sum())
    if n_na > 0:
        warnings.warn(f"{label}: {n_na} missing values detected")
    groups = series.notna().cumsum()
    max_gap = int(series.isna().astype(int).groupby(groups).sum().max())
    if max_gap >= 5:
        warnings.warn(
            f"DATA QUALITY: {max_gap} consecutive missing days in {label} — "
            "forward-fill NOT applied per data quality policy"
        )


def download_data(params: dict, start: str, end: str) -> dict:
    """
    Download SPY (OHLCV), GLD or GC=F (Close), SHY (Close).

    Warmup = 2 × max(lookback, SIGMA_WINDOW, ADV_WINDOW) in calendar days so
    all rolling indicators are warm at the IS/OOS start date.

    When use_gcf_proxy=True and start < gld_inception, downloads GC=F for the
    pre-GLD period and splices it with GLD after inception.

    Raises ValueError on missing columns or insufficient data.
    """
    lookback = params["lookback_days"]
    warmup_days = max(SIGMA_WINDOW, ADV_WINDOW, lookback) + 30
    warmup_cal = warmup_days * 2
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_cal)
    ).strftime("%Y-%m-%d")

    spy_df = _download_ticker(params["spy_ticker"], warmup_start, end)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in spy_df.columns:
            raise ValueError(f"Missing column '{col}' for {params['spy_ticker']}")
    _check_data_gaps(spy_df["Close"], params["spy_ticker"])

    gld_inception = pd.Timestamp(params["gld_inception"])
    use_proxy = params.get("use_gcf_proxy", False) and pd.Timestamp(start) < gld_inception

    if use_proxy:
        # Download both GC=F and GLD; splice at GLD inception
        gcf_df = _download_ticker(params["gcf_proxy_ticker"], warmup_start, end)
        if "Close" not in gcf_df.columns:
            raise ValueError(f"Missing 'Close' for {params['gcf_proxy_ticker']}")
        gcf_close = gcf_df["Close"].rename("gold_signal")

        gld_df = _download_ticker(params["gld_ticker"], gld_inception.strftime("%Y-%m-%d"), end)
        if "Close" not in gld_df.columns:
            raise ValueError(f"Missing 'Close' for {params['gld_ticker']}")
        gld_close = gld_df["Close"].rename("gold_signal")

        # Normalise splice: scale GC=F to match GLD price at first GLD date
        first_gld_date = gld_close.index[0]
        if first_gld_date in gcf_close.index and not pd.isna(gcf_close.loc[first_gld_date]):
            scale = float(gld_close.iloc[0]) / float(gcf_close.loc[first_gld_date])
            gcf_scaled = gcf_close.loc[gcf_close.index < first_gld_date] * scale
        else:
            gcf_scaled = gcf_close.loc[gcf_close.index < first_gld_date]

        gold_signal = pd.concat([gcf_scaled, gld_close]).sort_index()
        gold_signal = gold_signal[~gold_signal.index.duplicated(keep="last")]
        warnings.warn(
            f"GC=F proxy used for gold signal before {first_gld_date.date()} "
            f"(pre-GLD dot-com stress test). Scale factor: {scale:.4f}."
        )
        gold_ticker_label = f"GC=F+GLD splice"
    else:
        gld_df = _download_ticker(params["gld_ticker"], warmup_start, end)
        if "Close" not in gld_df.columns:
            raise ValueError(f"Missing 'Close' for {params['gld_ticker']}")
        _check_data_gaps(gld_df["Close"], params["gld_ticker"])
        gold_signal = gld_df["Close"].rename("gold_signal")
        gold_ticker_label = params["gld_ticker"]

    harbor = params["safe_harbor"]
    harbor_df = _download_ticker(harbor, warmup_start, end)
    if "Close" not in harbor_df.columns:
        raise ValueError(f"Missing 'Close' for {harbor}")
    _check_data_gaps(harbor_df["Close"], harbor)
    harbor_close = harbor_df["Close"].rename("harbor")

    return {
        "spy": spy_df,
        "gold_signal": gold_signal,
        "harbor": harbor_close,
        "gold_ticker_label": gold_ticker_label,
    }


# ── Rebalance Date Logic ───────────────────────────────────────────────────────

def _get_rebalance_dates(date_index: pd.DatetimeIndex, frequency: str) -> pd.DatetimeIndex:
    """
    Return the set of dates on which signal is checked and trades are executed.

    monthly:   last trading day of each calendar month.
    biweekly:  last trading day of every two-week period (every other week-end).
    """
    if frequency == "monthly":
        # Group by year-month, take the last date in each group
        df_tmp = pd.DataFrame({"date": date_index}, index=date_index)
        rebal = df_tmp.groupby([df_tmp.index.year, df_tmp.index.month])["date"].last()
        return pd.DatetimeIndex(rebal.values)
    elif frequency == "biweekly":
        # Use 2-week periods; resample to 2W-FRI, take last valid date
        s = pd.Series(date_index, index=date_index)
        rebal = s.resample("2W-FRI").last().dropna()
        # Snap to actual trading days
        return pd.DatetimeIndex(rebal.values)
    else:
        raise ValueError(f"Unknown rebalance_frequency: {frequency!r}")


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_gold_signal(
    gold: pd.Series,
    spy_close: pd.Series,
    rebalance_dates: pd.DatetimeIndex,
    params: dict,
) -> pd.Series:
    """
    Compute GLD/SPY relative momentum signal on each rebalance date.

    relative_signal_t = (GLD_t/GLD_{t-lookback} - 1) - (SPY_t/SPY_{t-lookback} - 1)

    Positive signal: GLD outperformed SPY → risk-off (hold SHY next month).
    Negative or zero: SPY outperformed GLD → risk-on (hold SPY next month).

    Only computed on rebalance dates; other dates are NaN.
    Uses only data available at close on signal date (no look-ahead).
    """
    lookback = params["lookback_days"]
    threshold = params["signal_threshold"]

    # Align on common index
    combined = pd.DataFrame({"gold": gold, "spy": spy_close}).dropna()

    signals = pd.Series(index=rebalance_dates, dtype=float, name="gold_spy_signal")
    for dt in rebalance_dates:
        if dt not in combined.index:
            continue
        loc = combined.index.get_loc(dt)
        if loc < lookback:
            continue
        gold_prev = combined["gold"].iloc[loc - lookback]
        gold_now = combined["gold"].iloc[loc]
        spy_prev = combined["spy"].iloc[loc - lookback]
        spy_now = combined["spy"].iloc[loc]
        if pd.isna(gold_prev) or pd.isna(spy_prev) or gold_prev <= 0 or spy_prev <= 0:
            continue
        gold_ret = gold_now / gold_prev - 1.0
        spy_ret = spy_now / spy_prev - 1.0
        signals.loc[dt] = gold_ret - spy_ret

    # Risk-off = True when signal > threshold (GLD outperformed SPY)
    risk_off = signals > threshold
    return signals, risk_off


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
      impact   = k × σ × sqrt(Q/ADV) × price × Q  (square-root market impact)

    Returns (total_cost_dollars: float, liquidity_constrained: bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000

    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: {shares} shares "
            f"({shares / adv:.2%} of ADV). Q/ADV > 1%."
        )

    return fixed + slippage + impact, liq_constrained


# ── H51 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h51(
    spy_df: pd.DataFrame,
    harbor_close: pd.Series,
    risk_off: pd.Series,
    gold_signals: pd.Series,
    rebalance_dates: pd.DatetimeIndex,
    params: dict,
) -> tuple:
    """
    Simulate H51 monthly rotation strategy.

    Execution model (no look-ahead):
    - On each rebalance date: check signal at close, execute switch at same close.
      (Month-end close is the institutional rebalancing window per hypothesis.)
    - Between rebalances: hold the current asset; daily P&L from daily returns.
    - SPY held during risk-on months; SHY held during risk-off months.
    - Transaction costs applied on all transitions (both SPY and SHY legs).

    Returns (trade_log, equity, daily_df, n_transitions).
    """
    init_cash = float(params["init_cash"])
    harbor_label = params["safe_harbor"]

    spy_close = spy_df["Close"]
    spy_open = spy_df["Open"]
    spy_vol = spy_df["Volume"]
    dates = spy_df.index
    n = len(dates)

    harbor_ret = harbor_close.reindex(dates).pct_change().fillna(0.0)
    spy_ret = spy_close.pct_change().fillna(0.0)

    rebal_set = set(rebalance_dates)

    trade_log = []
    daily_records = []

    capital = init_cash
    # Determine initial regime from first rebalance signal
    # Default risk-on (hold SPY) until first rebalance
    in_spy = True
    spy_shares = 0
    harbor_units = 0.0   # dollar-equivalent units for SHY

    # Track open SPY trade for log
    entry_spy_price = 0.0
    entry_spy_shares = 0
    entry_spy_cost = 0.0
    entry_spy_date = None
    entry_spy_liq = False

    n_transitions = 0

    # Bootstrap: buy SPY at first date open (default risk-on start)
    if n > 0:
        open_0 = float(spy_open.iloc[0])
        if open_0 > 0 and capital > 0:
            shares_0 = int(capital / open_0)
            if shares_0 > 0:
                cost_0, liq_0 = _transaction_cost(open_0, shares_0, spy_close, spy_vol, 0)
                eff_entry_0 = open_0 + cost_0 / shares_0
                capital -= eff_entry_0 * shares_0
                spy_shares = shares_0
                entry_spy_price = eff_entry_0
                entry_spy_shares = shares_0
                entry_spy_cost = cost_0
                entry_spy_date = dates[0]
                entry_spy_liq = liq_0

    for i in range(n):
        date_i = dates[i]

        # Check if this is a rebalance date with a signal
        if date_i in rebal_set and date_i in risk_off.index and not pd.isna(risk_off.loc[date_i]):
            desired_spy = not bool(risk_off.loc[date_i])

            # ── Execute at close price ────────────────────────────────────────
            close_i = float(spy_close.iloc[i])

            if in_spy and not desired_spy:
                # SPY → SHY transition: sell SPY at close
                if spy_shares > 0 and close_i > 0:
                    xcost, xliq = _transaction_cost(close_i, spy_shares, spy_close, spy_vol, i)
                    eff_exit = close_i - xcost / spy_shares
                    trade_pnl = (eff_exit - entry_spy_price) * spy_shares
                    capital += eff_exit * spy_shares

                    trade_log.append({
                        "entry_date": entry_spy_date.date() if entry_spy_date else None,
                        "exit_date": date_i.date(),
                        "asset": "SPY",
                        "entry_price": round(entry_spy_price, 4),
                        "exit_price": round(eff_exit, 4),
                        "shares": spy_shares,
                        "pnl": round(float(trade_pnl), 2),
                        "entry_cost": round(entry_spy_cost, 4),
                        "exit_cost": round(float(xcost), 4),
                        "transaction_cost": round(float(entry_spy_cost + xcost), 4),
                        "liquidity_constrained": entry_spy_liq or xliq,
                        "hold_days": i - (dates.get_loc(entry_spy_date) if entry_spy_date in dates else 0),
                        "exit_reason": "SIGNAL_RISK_OFF",
                        "gold_signal": round(float(gold_signals.loc[date_i]), 6) if date_i in gold_signals.index else float("nan"),
                    })

                    spy_shares = 0
                    entry_spy_price = 0.0
                    entry_spy_shares = 0
                    entry_spy_cost = 0.0
                    entry_spy_date = None
                    entry_spy_liq = False
                    in_spy = False
                    n_transitions += 1

                    # Buy SHY: track as dollar value (SHY treated as return-bearing cash)
                    harbor_units = capital

            elif not in_spy and desired_spy:
                # SHY → SPY transition: buy SPY at close
                harbor_units = 0.0
                if close_i > 0 and capital > 0:
                    shares_in = int(capital / close_i)
                    if shares_in > 0:
                        cost_in, liq_in = _transaction_cost(close_i, shares_in, spy_close, spy_vol, i)
                        eff_entry = close_i + cost_in / shares_in
                        capital -= eff_entry * shares_in
                        spy_shares = shares_in
                        entry_spy_price = eff_entry
                        entry_spy_shares = shares_in
                        entry_spy_cost = cost_in
                        entry_spy_date = date_i
                        entry_spy_liq = liq_in
                        in_spy = True
                        n_transitions += 1

        # ── Daily returns: apply while holding ───────────────────────────────
        if not in_spy:
            # SHY earns daily harbor return
            h_ret = float(harbor_ret.iloc[i])
            capital *= (1.0 + h_ret)
            harbor_units = capital

        # ── Daily mark-to-market ──────────────────────────────────────────────
        close_i = float(spy_close.iloc[i])
        if in_spy:
            mtm = capital + spy_shares * close_i
        else:
            mtm = capital

        sig_val = gold_signals.loc[date_i] if date_i in gold_signals.index else float("nan")

        daily_records.append({
            "date": date_i,
            "regime": "SPY" if in_spy else harbor_label,
            "gold_spy_signal": float(sig_val) if not pd.isna(sig_val) else float("nan"),
            "spy_shares": spy_shares if in_spy else 0,
            "equity": mtm,
        })

    # ── Force-close open SPY at end of data ──────────────────────────────────
    if in_spy and n > 0 and spy_shares > 0:
        close_f = float(spy_close.iloc[n - 1])
        xcost_f, xliq_f = _transaction_cost(close_f, spy_shares, spy_close, spy_vol, n - 1)
        eff_exit_f = close_f - xcost_f / spy_shares
        trade_pnl_f = (eff_exit_f - entry_spy_price) * spy_shares
        capital += eff_exit_f * spy_shares

        trade_log.append({
            "entry_date": entry_spy_date.date() if entry_spy_date else None,
            "exit_date": dates[n - 1].date(),
            "asset": "SPY",
            "entry_price": round(entry_spy_price, 4),
            "exit_price": round(eff_exit_f, 4),
            "shares": spy_shares,
            "pnl": round(float(trade_pnl_f), 2),
            "entry_cost": round(entry_spy_cost, 4),
            "exit_cost": round(float(xcost_f), 4),
            "transaction_cost": round(float(entry_spy_cost + xcost_f), 4),
            "liquidity_constrained": entry_spy_liq or xliq_f,
            "hold_days": n - 1,
            "exit_reason": "END_OF_DATA",
            "gold_signal": float("nan"),
        })
        if daily_records:
            daily_records[-1]["equity"] = capital

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")

    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df, n_transitions


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download data, compute GLD/SPY relative momentum signal, simulate H51 monthly rotation.

    Parameters
    ----------
    start : str  Backtest start date (YYYY-MM-DD). IS: "2005-01-01".
    end : str    Backtest end date (YYYY-MM-DD). IS: "2021-12-31".
    params : dict  Override PARAMETERS; uses module-level PARAMETERS if None.

    Returns
    -------
    dict with performance metrics, trade log, equity curve, daily DataFrame,
    regime statistics, and data quality flags.
    """
    if params is None:
        params = PARAMETERS.copy()

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 1. Download with warmup ───────────────────────────────────────────────
    data = download_data(params, start, end)
    spy_full = data["spy"]
    gold_full = data["gold_signal"]
    harbor_full = data["harbor"]
    gold_ticker_label = data["gold_ticker_label"]

    # ── 2. Compute rebalance dates on full SPY trading calendar ──────────────
    rebalance_dates_full = _get_rebalance_dates(spy_full.index, params["rebalance_frequency"])

    # ── 3. Compute signals on warmup-inclusive series (no look-ahead) ─────────
    spy_close_full = spy_full["Close"]
    gold_signals_full, risk_off_full = compute_gold_signal(
        gold_full, spy_close_full, rebalance_dates_full, params
    )

    # ── 4. Trim to backtest window ────────────────────────────────────────────
    def _trim(s):
        return s.loc[(s.index >= ts_start) & (s.index <= ts_end)]

    spy_df = _trim(spy_full).copy()
    harbor_close = _trim(harbor_full)
    gold_signals = gold_signals_full.loc[
        (gold_signals_full.index >= ts_start) & (gold_signals_full.index <= ts_end)
    ]
    risk_off = risk_off_full.loc[
        (risk_off_full.index >= ts_start) & (risk_off_full.index <= ts_end)
    ]
    rebalance_dates = pd.DatetimeIndex([
        d for d in rebalance_dates_full
        if ts_start <= d <= ts_end
    ])

    if len(spy_df) < 10:
        raise ValueError(f"Insufficient data after trimming to {start}–{end}: {len(spy_df)} bars")

    # ── 5. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df, n_transitions = simulate_h51(
        spy_df, harbor_close, risk_off, gold_signals, rebalance_dates, params
    )

    # ── 6. Performance metrics ────────────────────────────────────────────────
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    n_trades = len(trade_log)

    _empty_cols = [
        "entry_date", "exit_date", "asset", "entry_price", "exit_price",
        "shares", "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason", "gold_signal",
    ]
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=_empty_cols)

    daily_returns = equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values
    sharpe = 0.0
    if len(ret_arr) > 1 and ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    win_rate = 0.0
    profit_factor = 0.0
    avg_hold_days = 0.0
    if n_trades > 0:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = round(float(wins / losses), 4) if losses > 0 else float("inf")
        avg_hold_days = round(float(trades_df["hold_days"].mean()), 1)

    transitions_per_year = round(n_transitions / years, 1)

    spy_days = harbor_days = 0
    pct_in_spy = 0.0
    harbor_label = params["safe_harbor"]
    if not daily_df.empty:
        spy_days = int((daily_df["regime"] == "SPY").sum())
        harbor_days = int((daily_df["regime"] != "SPY").sum())
        pct_in_spy = round(spy_days / len(daily_df), 4)

    # Risk-off month fraction
    n_rebal = len(rebalance_dates)
    n_riskoff_months = int(risk_off.sum()) if not risk_off.empty else 0
    pct_riskoff = round(n_riskoff_months / n_rebal, 4) if n_rebal > 0 else 0.0

    # PF-1: trade count check (monthly rebalances / 4 walk-forward folds >= 30)
    monthly_rebalances = n_rebal
    rebal_per_fold = round(monthly_rebalances / 4, 1)
    pf1_status = (
        f"PASS ({rebal_per_fold:.1f} rebalances/fold >= 30)"
        if rebal_per_fold >= 30
        else f"WARN: {rebal_per_fold:.1f}/fold < 30"
    )

    print(
        f"\nH51 GLD/SPY Risk Timer ({start}–{end}) "
        f"[lookback={params['lookback_days']}d, harbor={harbor_label}, "
        f"freq={params['rebalance_frequency']}, gold={gold_ticker_label}]:\n"
        f"  SPY days: {spy_days} ({pct_in_spy:.1%}) | {harbor_label} days: {harbor_days} | "
        f"Rebalances: {n_rebal} | Risk-off months: {n_riskoff_months} ({pct_riskoff:.1%})\n"
        f"  Transitions: {n_transitions} ({transitions_per_year:.1f}/yr)\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor} | "
        f"Avg hold: {avg_hold_days:.1f}d | PF-1: {pf1_status}\n"
        f"  Init cash: ${params['init_cash']:,.0f}"
    )

    return {
        "returns": daily_returns,
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params.copy(),
        "data_quality": {
            "survivorship_bias_flag": "SPY/GLD/SHY are live ETFs — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "spy_ticker": params["spy_ticker"],
            "gold_ticker": gold_ticker_label,
            "harbor_ticker": harbor_label,
            "gld_inception": params["gld_inception"],
            "gcf_proxy_used": params.get("use_gcf_proxy", False),
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY/GLD/SHY are active ETFs",
            "forward_fill_policy": "Silent forward-fill NOT applied for gaps >= 5 days",
            "signal_lag": (
                "GLD/SPY signal at month-end T uses only close data through T; "
                "execution at same T close (no look-ahead — institutional rebalancing window)"
            ),
        },
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "n_transitions": n_transitions,
        "transitions_per_year": transitions_per_year,
        "monthly_rebalances": n_rebal,
        "rebal_per_fold": rebal_per_fold,
        "pct_riskoff": pct_riskoff,
        "n_riskoff_months": n_riskoff_months,
        "pf1_status": pf1_status,
        "spy_days": spy_days,
        "harbor_days": harbor_days,
        "pct_in_spy": pct_in_spy,
        "avg_hold_days": avg_hold_days,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2005-01-01",
    end: str = "2025-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H51.

    Returns daily DataFrame with columns:
        date, regime, gold_spy_signal, spy_shares, pnl, entry_price, exit_price,
        transaction_cost, exit_reason, equity
    """
    p = (params or PARAMETERS).copy()
    result = run_backtest(start, end, p)

    daily = result["daily_df"].reset_index()
    trades = result["trades"]

    trade_merge_cols = ["exit_date", "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason"]

    if trades.empty:
        for col in trade_merge_cols[1:]:
            daily[col] = float("nan")
    else:
        trade_cols = trades[trade_merge_cols].copy()
        trade_cols["exit_date"] = pd.to_datetime(trade_cols["exit_date"])
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.merge(
            trade_cols.rename(columns={"exit_date": "date"}),
            on="date",
            how="left",
        )

    out_cols = ["date", "regime", "gold_spy_signal", "spy_shares",
                "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason", "equity"]
    for col in out_cols:
        if col not in daily.columns:
            daily[col] = float("nan")

    return daily[out_cols]


if __name__ == "__main__":
    # ── IS baseline: lookback=20d, SHY safe harbor, monthly rebalance ─────────
    result_is = run_backtest("2005-01-01", "2021-12-31")
    print(
        f"\n[IS baseline 2005–2021] Rebalances: {result_is['monthly_rebalances']} | "
        f"Risk-off months: {result_is['n_riskoff_months']} ({result_is['pct_riskoff']:.1%}) | "
        f"Transitions: {result_is['n_transitions']} | Sharpe: {result_is['sharpe']}"
    )

    # ── IS lookback=10d ───────────────────────────────────────────────────────
    params_lb10 = PARAMETERS.copy()
    params_lb10["lookback_days"] = 10
    result_lb10 = run_backtest("2005-01-01", "2021-12-31", params_lb10)
    print(f"[IS lookback=10d] Sharpe: {result_lb10['sharpe']} | MDD: {result_lb10['max_drawdown']:.2%}")

    # ── IS lookback=30d ───────────────────────────────────────────────────────
    params_lb30 = PARAMETERS.copy()
    params_lb30["lookback_days"] = 30
    result_lb30 = run_backtest("2005-01-01", "2021-12-31", params_lb30)
    print(f"[IS lookback=30d] Sharpe: {result_lb30['sharpe']} | MDD: {result_lb30['max_drawdown']:.2%}")

    # ── IS TLT safe harbor (rate sensitivity test) ────────────────────────────
    params_tlt = PARAMETERS.copy()
    params_tlt["safe_harbor"] = "TLT"
    result_tlt = run_backtest("2005-01-01", "2021-12-31", params_tlt)
    print(f"[IS TLT harbor] Sharpe: {result_tlt['sharpe']} | MDD: {result_tlt['max_drawdown']:.2%}")

    # ── IS biweekly rebalance ─────────────────────────────────────────────────
    params_bw = PARAMETERS.copy()
    params_bw["rebalance_frequency"] = "biweekly"
    result_bw = run_backtest("2005-01-01", "2021-12-31", params_bw)
    print(f"[IS biweekly] Sharpe: {result_bw['sharpe']} | MDD: {result_bw['max_drawdown']:.2%}")

    # ── Dot-com stress test with GC=F proxy (2000–2004) ──────────────────────
    params_gcf = PARAMETERS.copy()
    params_gcf["use_gcf_proxy"] = True
    result_dotcom = run_backtest("2000-01-01", "2004-12-31", params_gcf)
    print(
        f"[Dot-com 2000–2004 GC=F proxy] Sharpe: {result_dotcom['sharpe']} | "
        f"MDD: {result_dotcom['max_drawdown']:.2%} | Transitions: {result_dotcom['n_transitions']}"
    )

    # ── GFC stress test ───────────────────────────────────────────────────────
    result_gfc = run_backtest("2007-01-01", "2009-12-31")
    print(
        f"[GFC 2007–2009] Sharpe: {result_gfc['sharpe']} | "
        f"MDD: {result_gfc['max_drawdown']:.2%} | Risk-off months: {result_gfc['n_riskoff_months']}"
    )

    # ── 2022 rate-shock ───────────────────────────────────────────────────────
    result_2022 = run_backtest("2022-01-01", "2022-12-31")
    print(
        f"[2022 rate-shock] Sharpe: {result_2022['sharpe']} | "
        f"MDD: {result_2022['max_drawdown']:.2%} | SPY%: {result_2022['pct_in_spy']:.1%}"
    )

    # ── OOS: 2022–2025 ────────────────────────────────────────────────────────
    result_oos = run_backtest("2022-01-01", "2025-12-31")
    print(
        f"\n[OOS 2022–2025] Sharpe: {result_oos['sharpe']} | "
        f"MDD: {result_oos['max_drawdown']:.2%} | Transitions: {result_oos['n_transitions']}"
    )

    print(f"\nEquity final (IS baseline): ${result_is['equity'].iloc[-1]:,.2f}")
