"""
Strategy: H44v2 LQD/IEF Credit Risk Appetite Timer — SPY/Cash with Trailing Stop-Loss
Author: Engineering Director (QUA-343)
Date: 2026-05-01
Parent: QUA-343 (H44v2 redesign from QUA-342 CEO ruling)
Signal mechanism: Unchanged from H44. LQD/IEF 20-day relative momentum proxies
                  investment-grade credit spreads and leads equity market regime.
Stop-loss overlay (new in v2):
  - Trailing stop: trailing_stop_pct (default 15%) from HWM per equity holding period.
  - Stop trigger: close_t <= hwm * (1 - trailing_stop_pct) → exit at next open.
  - Re-entry after stop: BOTH (a) LQD/IEF signal risk-on AND
    (b) open >= stop_trigger_price * (1 + reentry_margin). Prevents whipsaw.
IS window:  2007-01-01 to 2021-12-31
OOS window: 2022-01-01 to 2025-12-31
"""

import warnings

import numpy as np
import pandas as pd

from strategies.h44_lqd_ief_credit_risk_appetite_timer import (
    PARAMETERS as _H44_PARAMETERS,
    FIXED_COST_PER_SHARE,
    SLIPPAGE_PCT,
    MARKET_IMPACT_K,
    SIGMA_WINDOW,
    ADV_WINDOW,
    TRADING_DAYS_PER_YEAR,
    download_data,
    compute_credit_signal,
    apply_smoothing_filter,
    _transaction_cost,
)

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = _H44_PARAMETERS.copy()
PARAMETERS.update({
    "trailing_stop_pct": 0.15,  # 15% trailing stop from HWM (v2 base case)
    "reentry_margin": 0.03,     # SPY must be 3% above stop trigger price to re-enter
})


# ── H44v2 Simulation Engine ────────────────────────────────────────────────────

def simulate_h44v2(
    spy_df: pd.DataFrame,
    hold_spy: pd.Series,
    credit_signal: pd.Series,
    riskoff_close: pd.Series | None,
    params: dict,
    initial_hold_spy: bool = True,
) -> tuple:
    """
    Simulate H44v2 regime-switching strategy with trailing stop-loss overlay.

    Execution model (no look-ahead):
    - Signal at T close determines desired regime for T+1 open execution.
    - Trailing stop checked at each day's close; exit fires at next open.
    - HWM resets to entry price on each new SPY position entry.
    - After a stop exit, re-entry requires BOTH: signal risk-on AND
      open >= stop_trigger_price * (1 + reentry_margin). Prevents whipsaw.
    - Signal exit (SPY → cash) clears stop cooldown state.

    Returns (trade_log, equity, daily_df, n_transitions, n_stop_exits).
    """
    trailing_stop_pct = float(params.get("trailing_stop_pct", 0.15))
    reentry_margin = float(params.get("reentry_margin", 0.03))
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

    # Trailing stop state
    hwm = 0.0
    stop_exit_pending = False
    stop_trigger_price_recorded = 0.0  # hwm * (1 - trailing_stop_pct) when stop triggered
    in_stop_cooldown = False
    n_stop_exits = 0

    for i in range(n):
        date_i = dates[i]
        open_i = float(open_s.iloc[i])
        close_i = float(close_s.iloc[i])
        riskoff_r = float(riskoff_ret.iloc[i])

        # Signal at T-1 close drives T open execution — no look-ahead
        desired_spy = bool(hold_spy_aligned.iloc[i - 1]) if i > 0 else initial_hold_spy

        # ── Priority 1: Trailing stop exit at open ─────────────────────────────
        if in_spy and stop_exit_pending:
            if pd.isna(open_i) or open_i <= 0:
                warnings.warn(
                    f"Invalid open at {date_i.date()} during trailing stop exit — deferring"
                )
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
                    "exit_reason": "TRAILING_STOP",
                    "hwm_at_stop": round(hwm, 4),
                    "stop_trigger_price": round(stop_trigger_price_recorded, 4),
                })

                in_spy = False
                spy_shares = 0
                entry_open = 0.0
                entry_cost_total = 0.0
                entry_liq = False
                entry_bar_idx = -1
                entry_date_ts = None
                stop_exit_pending = False
                in_stop_cooldown = True
                n_stop_exits += 1
                n_transitions += 1
                hwm = 0.0

        # ── Cash → SPY (signal-driven, with cooldown check) ────────────────────
        elif not in_spy and desired_spy:
            can_enter = True
            if in_stop_cooldown:
                reentry_threshold = stop_trigger_price_recorded * (1.0 + reentry_margin)
                if open_i >= reentry_threshold:
                    in_stop_cooldown = False   # cooldown resolved
                else:
                    can_enter = False          # still cooling down

            if can_enter:
                if pd.isna(open_i) or open_i <= 0:
                    warnings.warn(
                        f"Invalid open at {date_i.date()} (open={open_i}) — skip SPY entry"
                    )
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
                        hwm = open_i            # reset HWM to entry price
                        n_transitions += 1

        # ── SPY → cash (signal exit) ───────────────────────────────────────────
        elif in_spy and not desired_spy:
            if pd.isna(open_i) or open_i <= 0:
                warnings.warn(
                    f"Invalid open at {date_i.date()} (open={open_i}) — skip SPY exit"
                )
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
                    "hwm_at_stop": round(hwm, 4),
                    "stop_trigger_price": round(hwm * (1 - trailing_stop_pct), 4),
                })

                in_spy = False
                spy_shares = 0
                entry_open = 0.0
                entry_cost_total = 0.0
                entry_liq = False
                entry_bar_idx = -1
                entry_date_ts = None
                hwm = 0.0
                stop_exit_pending = False
                # Signal exit (risk-off) clears stop cooldown — regime has changed
                in_stop_cooldown = False
                n_transitions += 1

        # ── Cash earns risk-off return ─────────────────────────────────────────
        if not in_spy:
            capital *= (1.0 + riskoff_r)

        # ── Update HWM and check trailing stop at close ────────────────────────
        if in_spy and not stop_exit_pending:
            hwm = max(hwm, close_i)
            trailing_stop_price = hwm * (1.0 - trailing_stop_pct)
            if close_i <= trailing_stop_price:
                stop_exit_pending = True
                stop_trigger_price_recorded = trailing_stop_price

        # ── Daily mark-to-market ───────────────────────────────────────────────
        mtm = capital + spy_shares * close_i if in_spy else capital
        sig_val = signal_aligned.iloc[i]

        daily_records.append({
            "date": date_i,
            "regime": "SPY" if in_spy else riskoff_label,
            "credit_signal": float(sig_val) if not pd.isna(sig_val) else float("nan"),
            "spy_shares": spy_shares if in_spy else 0,
            "equity": mtm,
            "hwm": round(hwm, 4) if in_spy else 0.0,
            "stop_pending": stop_exit_pending,
            "in_stop_cooldown": in_stop_cooldown,
        })

    # ── Force-close any open SPY position at end of data ──────────────────────
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
            "hwm_at_stop": round(hwm, 4),
            "stop_trigger_price": round(hwm * (1 - trailing_stop_pct), 4),
        })
        if daily_records:
            daily_records[-1]["equity"] = capital

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")

    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df, n_transitions, n_stop_exits


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download data, compute LQD/IEF credit signal, simulate H44v2 with trailing stop.

    Parameters
    ----------
    start : str  Backtest start date (YYYY-MM-DD). IS: "2007-01-01".
    end : str    Backtest end date (YYYY-MM-DD). IS: "2021-12-31".
    params : dict  Override PARAMETERS. Uses module-level PARAMETERS if None.

    Returns
    -------
    dict with performance metrics, trade log, equity curve, daily DataFrame,
    regime statistics, stop-loss statistics, and data quality flags.
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

    # ── 5. Simulate with trailing stop ───────────────────────────────────────
    trade_log, equity, daily_df, n_transitions, n_stop_exits = simulate_h44v2(
        spy_df, hold_spy, credit_sig, riskoff_close, params, initial_hold_spy
    )

    # ── 6. Performance metrics ────────────────────────────────────────────────
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    n_trades = len(trade_log)

    _empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price", "shares",
        "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason",
        "hwm_at_stop", "stop_trigger_price",
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
    stop_exit_pct = round(n_stop_exits / max(n_trades, 1), 4)

    spy_days = cash_days = 0
    pct_in_spy = 0.0
    riskoff_label = params["riskoff_asset"].upper()
    if not daily_df.empty:
        spy_days = int((daily_df["regime"] == "SPY").sum())
        cash_days = int((daily_df["regime"] != "SPY").sum())
        pct_in_spy = round(spy_days / len(daily_df), 4)

    transitions_per_wf_fold = round(n_transitions / 4, 1)
    pf1_min = 14
    pf1_status = (
        f"PASS ({transitions_per_wf_fold:.1f}/fold >= {pf1_min})"
        if transitions_per_wf_fold >= pf1_min
        else f"WARN: {transitions_per_wf_fold:.1f}/fold < {pf1_min}"
    )

    trailing_stop_pct = params.get("trailing_stop_pct", 0.15)
    reentry_margin = params.get("reentry_margin", 0.03)

    print(
        f"\nH44v2 LQD/IEF Credit Risk Appetite Timer ({start}–{end}) "
        f"[lookback={params['lookback_days']}d, thresh={params['signal_threshold']:.4f}, "
        f"stop={trailing_stop_pct:.0%}, re-entry+{reentry_margin:.0%}]:\n"
        f"  SPY days: {spy_days} ({pct_in_spy:.1%}) | Cash days: {cash_days} | "
        f"Transitions: {n_transitions} ({transitions_per_year:.1f}/yr)\n"
        f"  Stop exits: {n_stop_exits}/{n_trades} ({stop_exit_pct:.1%} of trades)\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor} | "
        f"Avg hold: {avg_hold_days:.1f}d | PF-1: {pf1_status}"
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
            "trailing_stop_pct": trailing_stop_pct,
            "reentry_margin": reentry_margin,
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
        "n_stop_exits": n_stop_exits,
        "stop_exit_pct": stop_exit_pct,
        "transitions_per_year": transitions_per_year,
        "transitions_per_wf_fold": transitions_per_wf_fold,
        "pf1_status": pf1_status,
        "spy_days": spy_days,
        "cash_days": cash_days,
        "pct_in_spy": pct_in_spy,
        "avg_hold_days": avg_hold_days,
        "trailing_stop_pct": trailing_stop_pct,
        "reentry_margin": reentry_margin,
    }


if __name__ == "__main__":
    result_is = run_backtest("2007-01-01", "2021-12-31")
    print(
        f"\n[IS baseline 15% stop] Transitions: {result_is['n_transitions']} | "
        f"Stop exits: {result_is['n_stop_exits']} | "
        f"SPY%: {result_is['pct_in_spy']:.1%} | "
        f"Sharpe: {result_is['sharpe']} | MDD: {result_is['max_drawdown']:.2%}"
    )

    result_oos = run_backtest("2022-01-01", "2025-12-31")
    print(
        f"[OOS 2022–2025 15% stop] Sharpe: {result_oos['sharpe']} | "
        f"MDD: {result_oos['max_drawdown']:.2%} | Stop exits: {result_oos['n_stop_exits']}"
    )
