"""
Strategy: H44 LQD/IEF Credit Risk Appetite Timer — SPY/Cash Rotation
Author: Strategy Coder Agent
Date: 2026-05-01
Hypothesis: LQD/IEF 20-day relative momentum proxies investment-grade credit spreads and
            leads equity market regime. Hold SPY when LQD outperforms IEF (risk-on);
            hold cash when IEF outperforms LQD (credit stress / risk-off).
Asset class: equities (SPY ETF) / cash rotation
Parent task: QUA-339
References: Gilchrist & Zakrajšek (2012) AER 102(4); Fama & French (1989) JFE 25(1);
            Ang & Bekaert (2007) RFS 20(3);
            research/hypotheses/44_lqd_ief_credit_risk_appetite_timer.md
IS window:  2007-01-01 to 2021-12-31
OOS window: 2022-01-01 to 2025-12-31
Data note:  LQD/IEF inception July 2002 — IS start 2007 is safe with full history.
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "spy_ticker": "SPY",
    "lqd_ticker": "LQD",      # iShares iBoxx IG Corp Bond ETF — signal computation only
    "ief_ticker": "IEF",      # iShares 7-10 Year Treasury ETF — signal computation only
    # Signal parameters
    "lookback_days": 20,       # LQD/IEF momentum lookback; range: 10–40
    "signal_threshold": 0.0,   # exit to cash if credit_signal <= threshold; range: 0.0–0.002
    "smoothing_days": 1,       # consecutive days signal <= threshold triggers exit; range: 1–3
    # Risk-off asset during cash regime; options: "cash" (0% return), "SHY", "BIL"
    "riskoff_asset": "cash",
    "init_cash": 25000,
}

# ── Transaction Cost Constants (Engineering Director spec) ─────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share fixed
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
MARKET_IMPACT_K = 0.1           # square-root impact coefficient (Johnson — Algo Trading & DMA)
SIGMA_WINDOW = 20               # 20-day rolling vol for σ
ADV_WINDOW = 20                 # 20-day rolling ADV (shares)
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_ticker(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex if present."""
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
    Download SPY (OHLCV), LQD (Close), IEF (Close), and optional risk-off asset (Close).

    Warmup window: 2x max(lookback, SIGMA_WINDOW, ADV_WINDOW) in calendar days so
    all rolling indicators are warm at the IS/OOS window start date.

    Raises ValueError on missing columns or insufficient data.
    Warns (does not silently forward-fill) on gaps >= 5 consecutive days.
    """
    lookback = params["lookback_days"]
    warmup_days = max(SIGMA_WINDOW, ADV_WINDOW, lookback) + 30
    warmup_cal = warmup_days * 2
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_cal)
    ).strftime("%Y-%m-%d")

    spy_ticker = params["spy_ticker"]
    lqd_ticker = params["lqd_ticker"]
    ief_ticker = params["ief_ticker"]
    riskoff = params["riskoff_asset"].upper()

    spy_df = _download_ticker(spy_ticker, warmup_start, end)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in spy_df.columns:
            raise ValueError(f"Missing column '{col}' for {spy_ticker}")
    min_bars = lookback + SIGMA_WINDOW + 10
    if len(spy_df) < min_bars:
        raise ValueError(f"Insufficient {spy_ticker} data: {len(spy_df)} rows (need >= {min_bars})")
    _check_data_gaps(spy_df["Close"], spy_ticker)

    lqd_df = _download_ticker(lqd_ticker, warmup_start, end)
    if "Close" not in lqd_df.columns:
        raise ValueError(f"Missing 'Close' for {lqd_ticker}")
    _check_data_gaps(lqd_df["Close"], lqd_ticker)
    lqd_close = lqd_df["Close"].rename("lqd")

    ief_df = _download_ticker(ief_ticker, warmup_start, end)
    if "Close" not in ief_df.columns:
        raise ValueError(f"Missing 'Close' for {ief_ticker}")
    _check_data_gaps(ief_df["Close"], ief_ticker)
    ief_close = ief_df["Close"].rename("ief")

    riskoff_close = None
    if riskoff in ("SHY", "BIL"):
        riskoff_df = _download_ticker(riskoff, warmup_start, end)
        if "Close" not in riskoff_df.columns:
            raise ValueError(f"Missing 'Close' for {riskoff}")
        _check_data_gaps(riskoff_df["Close"], riskoff)
        riskoff_close = riskoff_df["Close"].rename(riskoff.lower())

    return {"spy": spy_df, "lqd": lqd_close, "ief": ief_close, "riskoff": riskoff_close}


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_credit_signal(lqd: pd.Series, ief: pd.Series, params: dict) -> pd.Series:
    """
    Compute LQD/IEF credit risk appetite signal.

    credit_signal_t = (LQD_t / LQD_{t-lookback} - 1) - (IEF_t / IEF_{t-lookback} - 1)

    Positive signal (LQD outperforms IEF): credit spreads tightening → risk-on.
    Negative signal (IEF outperforms LQD): credit spreads widening → risk-off.

    Signal at t uses only close data through t (no look-ahead).
    Position change executes at t+1 open — enforced in the simulation loop.

    Returns: pd.Series of float, NaN for the first lookback periods.
    """
    lookback = params["lookback_days"]
    lqd_ret = lqd.pct_change(lookback)
    ief_ret = ief.pct_change(lookback)
    return (lqd_ret - ief_ret).rename("credit_signal")


def apply_smoothing_filter(signal: pd.Series, params: dict) -> pd.Series:
    """
    Apply consecutive-day smoothing to the credit signal (state machine).

    smoothing_days=1 (default): exit to cash on first day credit_signal <= threshold.
    smoothing_days=N: require N consecutive days of signal <= threshold to exit.
    Re-entry into SPY is always immediate (first day signal > threshold).

    State machine rules:
    - State "SPY": transition to "cash" after N consecutive days of signal <= threshold.
    - State "cash": transition to "SPY" immediately when signal > threshold.

    NaN values (warmup period): do not advance the consecutive-days counter; maintain state.

    Returns: pd.Series of bool — True = hold SPY (risk-on), False = hold cash (risk-off).
    """
    threshold = params["signal_threshold"]
    n_days = params["smoothing_days"]

    result = []
    state = True               # start risk-on (hold SPY)
    consecutive_risk_off = 0

    for sig in signal:
        if pd.isna(sig):
            result.append(state)
            continue

        if sig <= threshold:
            consecutive_risk_off += 1
        else:
            consecutive_risk_off = 0

        if state:
            if consecutive_risk_off >= n_days:
                state = False
        else:
            if sig > threshold:
                state = True
                consecutive_risk_off = 0

        result.append(state)

    return pd.Series(result, index=signal.index, dtype=bool, name="hold_spy")


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
      impact   = k * sigma * sqrt(Q / ADV) * price * Q  (square-root market impact)

    sigma: 20-day rolling daily return std (dimensionless).
    ADV: 20-day rolling mean volume in shares.
    Flags Q/ADV > 1% as liquidity-constrained.

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


# ── H44 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h44(
    spy_df: pd.DataFrame,
    hold_spy: pd.Series,
    credit_signal: pd.Series,
    riskoff_close: pd.Series | None,
    params: dict,
    initial_hold_spy: bool = True,
) -> tuple:
    """
    Simulate H44 regime-switching strategy on SPY.

    Execution model (no look-ahead):
    - Signal at T close determines desired regime for T+1 open execution.
    - SPY->cash transition: sell SPY at T+1 open.
    - cash->SPY transition: buy SPY at T+1 open.
    - While in cash: capital earns risk-off asset daily return (0 for 'cash').
    - Transaction costs applied only on SPY entry/exit transitions.
    - initial_hold_spy: desired regime at day 0 open, derived from warmup signal.

    Returns (trade_log: list, equity: pd.Series, daily_df: pd.DataFrame, n_transitions: int).
    """
    init_cash = float(params["init_cash"])
    riskoff_label = params["riskoff_asset"].upper()

    dates = spy_df.index
    n = len(dates)
    close_s = spy_df["Close"]
    open_s = spy_df["Open"]
    vol_s = spy_df["Volume"]

    hold_spy_aligned = hold_spy.reindex(dates, fill_value=True)
    signal_aligned = credit_signal.reindex(dates)

    if riskoff_close is not None:
        riskoff_ret = riskoff_close.reindex(dates).pct_change().fillna(0.0)
    else:
        riskoff_ret = pd.Series(0.0, index=dates)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_spy = False
    spy_shares = 0
    entry_open = 0.0
    entry_cost_total = 0.0
    entry_liq = False
    entry_bar_idx = -1
    entry_date_ts = None
    n_transitions = 0

    for i in range(n):
        date_i = dates[i]
        open_i = float(open_s.iloc[i])
        close_i = float(close_s.iloc[i])
        riskoff_r = float(riskoff_ret.iloc[i])

        # Signal at T-1 close drives T open execution — no look-ahead
        desired_spy = bool(hold_spy_aligned.iloc[i - 1]) if i > 0 else initial_hold_spy

        # ── Transition: cash -> SPY ────────────────────────────────────────────
        if desired_spy and not in_spy:
            if pd.isna(open_i) or open_i <= 0:
                warnings.warn(f"Invalid open at {date_i.date()} (open={open_i}) — skip SPY entry")
            elif capital > 0:
                shares = int(capital / open_i)
                if shares > 0:
                    cost, liq = _transaction_cost(open_i, shares, close_s, vol_s, i)
                    eff_entry = open_i + cost / shares
                    capital -= eff_entry * shares
                    in_spy = True
                    spy_shares = shares
                    entry_open = eff_entry
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_bar_idx = i
                    entry_date_ts = date_i
                    n_transitions += 1

        # ── Transition: SPY -> cash ────────────────────────────────────────────
        elif not desired_spy and in_spy:
            if pd.isna(open_i) or open_i <= 0:
                warnings.warn(f"Invalid open at {date_i.date()} (open={open_i}) — skip SPY exit")
            else:
                xcost, xliq = _transaction_cost(open_i, spy_shares, close_s, vol_s, i)
                eff_exit = open_i - xcost / spy_shares
                trade_pnl = (eff_exit - entry_open) * spy_shares
                capital += eff_exit * spy_shares

                trade_log.append({
                    "entry_date": entry_date_ts.date(),
                    "exit_date": date_i.date(),
                    "entry_price": round(entry_open, 4),
                    "exit_price": round(eff_exit, 4),
                    "shares": spy_shares,
                    "pnl": round(float(trade_pnl), 2),
                    "entry_cost": round(entry_cost_total, 4),
                    "exit_cost": round(float(xcost), 4),
                    "transaction_cost": round(float(entry_cost_total + xcost), 4),
                    "liquidity_constrained": entry_liq or xliq,
                    "hold_days": i - entry_bar_idx,
                    "exit_reason": "SIGNAL_EXIT",
                })

                in_spy = False
                spy_shares = 0
                entry_open = 0.0
                entry_cost_total = 0.0
                entry_liq = False
                entry_bar_idx = -1
                entry_date_ts = None
                n_transitions += 1

        # ── Cash earns risk-off return ─────────────────────────────────────────
        if not in_spy:
            capital *= (1.0 + riskoff_r)

        # ── Daily mark-to-market ──────────────────────────────────────────────
        mtm = capital + spy_shares * close_i if in_spy else capital
        sig_val = signal_aligned.iloc[i]

        daily_records.append({
            "date": date_i,
            "regime": "SPY" if in_spy else riskoff_label,
            "credit_signal": float(sig_val) if not pd.isna(sig_val) else float("nan"),
            "spy_shares": spy_shares if in_spy else 0,
            "equity": mtm,
        })

    # ── Force-close any open SPY position at end of data ─────────────────────
    if in_spy and n > 0:
        close_f = float(close_s.iloc[n - 1])
        xcost, xliq = _transaction_cost(close_f, spy_shares, close_s, vol_s, n - 1)
        eff_exit = close_f - xcost / spy_shares
        trade_pnl = (eff_exit - entry_open) * spy_shares
        capital += eff_exit * spy_shares

        trade_log.append({
            "entry_date": entry_date_ts.date(),
            "exit_date": dates[n - 1].date(),
            "entry_price": round(entry_open, 4),
            "exit_price": round(eff_exit, 4),
            "shares": spy_shares,
            "pnl": round(float(trade_pnl), 2),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(float(xcost), 4),
            "transaction_cost": round(float(entry_cost_total + xcost), 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_days": n - 1 - entry_bar_idx,
            "exit_reason": "END_OF_DATA",
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
    Download data, compute LQD/IEF credit signal, apply smoothing, and simulate H44.

    Parameters
    ----------
    start : str  Backtest start date (YYYY-MM-DD). IS: "2007-01-01".
    end : str    Backtest end date (YYYY-MM-DD). IS: "2021-12-31".
    params : dict  Override PARAMETERS. Uses module-level PARAMETERS if None.

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
    lqd_full = data["lqd"]
    ief_full = data["ief"]
    riskoff_full = data["riskoff"]

    # ── 2. Compute signal on warmup-inclusive series (no look-ahead) ──────────
    credit_sig_full = compute_credit_signal(lqd_full, ief_full, params)
    hold_spy_full = apply_smoothing_filter(credit_sig_full, params)

    # ── 3. Get initial regime state from last warmup day before IS window ─────
    pre_mask = hold_spy_full.index < ts_start
    initial_hold_spy = bool(hold_spy_full.loc[pre_mask].iloc[-1]) if pre_mask.any() else True

    # ── 4. Trim to backtest window ────────────────────────────────────────────
    def _trim(s):
        return s.loc[(s.index >= ts_start) & (s.index <= ts_end)]

    spy_df = _trim(spy_full).copy()
    credit_sig = _trim(credit_sig_full)
    hold_spy = _trim(hold_spy_full)
    riskoff_close = _trim(riskoff_full) if riskoff_full is not None else None

    if len(spy_df) < 10:
        raise ValueError(f"Insufficient data after trimming to {start}–{end}: {len(spy_df)} bars")

    # ── 5. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df, n_transitions = simulate_h44(
        spy_df, hold_spy, credit_sig, riskoff_close, params, initial_hold_spy
    )

    # ── 6. Performance metrics ────────────────────────────────────────────────
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    n_trades = len(trade_log)

    _empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price", "shares",
        "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason",
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

    spy_days = cash_days = 0
    pct_in_spy = 0.0
    riskoff_label = params["riskoff_asset"].upper()
    if not daily_df.empty:
        spy_days = int((daily_df["regime"] == "SPY").sum())
        cash_days = int((daily_df["regime"] != "SPY").sum())
        pct_in_spy = round(spy_days / len(daily_df), 4)

    # PF-1: >= 14 regime transitions per walk-forward fold (4 folds over IS window)
    transitions_per_wf_fold = round(n_transitions / 4, 1)
    pf1_min = 14
    pf1_status = (
        f"PASS ({transitions_per_wf_fold:.1f}/fold >= {pf1_min})"
        if transitions_per_wf_fold >= pf1_min
        else f"WARN: {transitions_per_wf_fold:.1f}/fold < {pf1_min}"
    )

    print(
        f"\nH44 LQD/IEF Credit Risk Appetite Timer ({start}–{end}) "
        f"[lookback={params['lookback_days']}d, thresh={params['signal_threshold']:.4f}, "
        f"smooth={params['smoothing_days']}d, riskoff={riskoff_label}]:\n"
        f"  SPY days: {spy_days} ({pct_in_spy:.1%}) | Cash days: {cash_days} | "
        f"Transitions: {n_transitions} ({transitions_per_year:.1f}/yr)\n"
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
        "params": params,
        "data_quality": {
            "survivorship_bias_flag": "SPY/LQD/IEF are live ETFs — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "spy_ticker": params["spy_ticker"],
            "lqd_ticker": params["lqd_ticker"],
            "ief_ticker": params["ief_ticker"],
            "lqd_inception": "July 2002 — IS window 2007 start is safe",
            "ief_inception": "July 2002 — IS window 2007 start is safe",
            "riskoff_asset": params["riskoff_asset"],
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY/LQD/IEF are still active",
            "forward_fill_policy": "Silent forward-fill NOT applied for gaps >= 5 days",
            "signal_lag": (
                "credit_signal at T uses only LQD/IEF close data through T; "
                "position change executes at T+1 open (no look-ahead bias)"
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
        "transitions_per_wf_fold": transitions_per_wf_fold,
        "pf1_status": pf1_status,
        "spy_days": spy_days,
        "cash_days": cash_days,
        "pct_in_spy": pct_in_spy,
        "avg_hold_days": avg_hold_days,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2007-01-01",
    end: str = "2025-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H44.

    Returns daily DataFrame with columns:
        date, regime, credit_signal, spy_shares, pnl, entry_price, exit_price,
        transaction_cost, exit_reason, equity

    Trade-level fields are populated on the exit date; all other rows carry NaN.
    `ticker` parameter accepted for orchestrator compatibility; H44 uses SPY
    via PARAMETERS["spy_ticker"].
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

    out_cols = ["date", "regime", "credit_signal", "spy_shares",
                "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason", "equity"]
    for col in out_cols:
        if col not in daily.columns:
            daily[col] = float("nan")

    return daily[out_cols]


if __name__ == "__main__":
    # ── IS: baseline (lookback=20d, smoothing=1d, no smoothing) ──────────────
    result_is = run_backtest("2007-01-01", "2021-12-31")
    print(
        f"\n[IS baseline] Transitions: {result_is['n_transitions']} | "
        f"SPY%: {result_is['pct_in_spy']:.1%} | Sharpe: {result_is['sharpe']}"
    )

    # ── IS: smoothing=2 (Engineering Director requested both) ─────────────────
    params_s2 = PARAMETERS.copy()
    params_s2["smoothing_days"] = 2
    result_is_s2 = run_backtest("2007-01-01", "2021-12-31", params_s2)
    print(
        f"[IS smooth=2d] Transitions: {result_is_s2['n_transitions']} | "
        f"SPY%: {result_is_s2['pct_in_spy']:.1%} | Sharpe: {result_is_s2['sharpe']}"
    )

    # ── GFC 2007–2009: verify exit signal fires before worst of Q4 2008 ───────
    result_gfc = run_backtest("2007-01-01", "2009-12-31")
    print(
        f"[GFC 2007–2009] Transitions: {result_gfc['n_transitions']} | "
        f"Max DD: {result_gfc['max_drawdown']:.2%} | "
        f"Total Return: {result_gfc['total_return']:.2%}"
    )
    if not result_gfc["daily_df"].empty:
        gfc_df = result_gfc["daily_df"]
        cash_in_gfc = gfc_df.loc[gfc_df.index >= "2008-09-01", "regime"].eq("CASH").sum()
        print(f"  Cash days Sep 2008 onward: {cash_in_gfc}")

    # ── 2022 rate-shock MDD scenario (Engineering Director key risk) ──────────
    result_2022 = run_backtest("2022-01-01", "2022-12-31")
    print(
        f"[2022 rate-shock] Transitions: {result_2022['n_transitions']} | "
        f"Max DD: {result_2022['max_drawdown']:.2%} | "
        f"Total Return: {result_2022['total_return']:.2%} | "
        f"SPY%: {result_2022['pct_in_spy']:.1%}"
    )

    # ── OOS: 2022–2025 ────────────────────────────────────────────────────────
    result_oos = run_backtest("2022-01-01", "2025-12-31")
    print(
        f"\n[OOS 2022–2025] Transitions: {result_oos['n_transitions']} | "
        f"Sharpe: {result_oos['sharpe']} | Max DD: {result_oos['max_drawdown']:.2%}"
    )

    print(f"\nEquity final (IS baseline): ${result_is['equity'].iloc[-1]:,.2f}")
