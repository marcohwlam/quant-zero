"""
Strategy: H65b US Dollar Strength Regime v2.0 — VIX Dual-Filter, Asymmetric Exit
Author: Engineering Director (QUA-224)
Date: 2026-06-12
Hypothesis: DX-Y.NYB (US Dollar Index) momentum + VIX level as macro regime signal.
            Enter risk-off ONLY when BOTH conditions met:
              dxy_mom > signal_threshold AND vix_level > vix_threshold
            Exit risk-off ONLY when BOTH conditions clear (asymmetric sticky):
              dxy_mom < signal_threshold AND vix_level < vix_threshold
            Intermediate states: HOLD CURRENT STATE (no partial trigger)

v1.0 failures fixed (QUA-213/QUA-224):
  1. 2014-2015 dollar bull false positive: DXY > 0 but VIX < 20 → stay risk-on (VIX filter)
  2. Q4 2022 whipsaw: DXY turned negative but VIX stayed > 20 → stay risk-off (asymmetric exit)

Asset class: US equity (SPY ETF) / short Treasury ETF (SHY/BIL)
IS window:  2003-01-01 to 2023-12-31 (20yr)
OOS window: 2024-01-01 to 2026-06-12
References: Miranda-Agrippino & Rey (2020), Ang & Bekaert (2004)
            research/hypotheses/65b_dollar_strength_regime_v2.md
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "spy_ticker": "SPY",
    "dxy_ticker": "DX-Y.NYB",    # US Dollar Index cash — signal only, not traded
    "vix_ticker": "^VIX",        # CBOE VIX — second filter, not traded
    # Signal parameters
    "lookback_days": 60,          # DXY momentum lookback; range: 40–80
    "signal_threshold": 0.0,      # DXY mom threshold; range: -0.01 to +0.01
    "vix_threshold": 20.0,        # VIX level threshold; options: 18, 20, 25
    "asymmetric_exit": True,      # Required design — NOT a tunable param
    # Risk-off asset: SHY (primary), BIL
    "riskoff_asset": "SHY",
    "init_cash": 25000,
}

# ── Transaction Cost Constants (Engineering Director spec; ED-SLIP-001) ────────
FIXED_COST_PER_SHARE = 0.005      # $0.005/share fixed
SLIPPAGE_PCT = 0.00005            # 0.005% of notional (ultra-liquid ETF tier ED-SLIP-001)
MARKET_IMPACT_K = 0.1             # Almgren-Chriss square-root coefficient
SIGMA_WINDOW = 20                 # 20-day rolling vol
ADV_WINDOW = 20                   # 20-day rolling ADV
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
    Download SPY (OHLCV), DX-Y.NYB (Close), ^VIX (Close), and risk-off asset (Close).

    v2.0 adds VIX download for dual-filter regime signal.

    Warmup: 2x max(lookback, SIGMA_WINDOW, ADV_WINDOW) in calendar days so
    all rolling indicators are warm at IS/OOS start date.
    """
    lookback = params["lookback_days"]
    warmup_days = max(SIGMA_WINDOW, ADV_WINDOW, lookback) + 30
    warmup_cal = warmup_days * 2
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_cal)
    ).strftime("%Y-%m-%d")

    spy_ticker = params["spy_ticker"]
    dxy_ticker = params["dxy_ticker"]
    vix_ticker = params["vix_ticker"]
    riskoff = params["riskoff_asset"].upper()

    spy_df = _download_ticker(spy_ticker, warmup_start, end)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in spy_df.columns:
            raise ValueError(f"Missing column '{col}' for {spy_ticker}")
    min_bars = lookback + SIGMA_WINDOW + 10
    if len(spy_df) < min_bars:
        raise ValueError(f"Insufficient {spy_ticker} data: {len(spy_df)} rows (need >= {min_bars})")
    _check_data_gaps(spy_df["Close"], spy_ticker)

    dxy_df = _download_ticker(dxy_ticker, warmup_start, end)
    if "Close" not in dxy_df.columns:
        raise ValueError(f"Missing 'Close' for {dxy_ticker}")
    _check_data_gaps(dxy_df["Close"], dxy_ticker)
    dxy_close = dxy_df["Close"].rename("dxy")

    # VIX — available from 1990; ffill(limit=5) into equity calendar
    vix_df = _download_ticker(vix_ticker, warmup_start, end)
    if "Close" not in vix_df.columns:
        raise ValueError(f"Missing 'Close' for {vix_ticker}")
    _check_data_gaps(vix_df["Close"], vix_ticker)
    vix_close = vix_df["Close"].rename("vix")

    riskoff_close = None
    if riskoff in ("SHY", "BIL", "TLT"):
        riskoff_df = _download_ticker(riskoff, warmup_start, end)
        if "Close" not in riskoff_df.columns:
            raise ValueError(f"Missing 'Close' for {riskoff}")
        _check_data_gaps(riskoff_df["Close"], riskoff)
        riskoff_close = riskoff_df["Close"].rename(riskoff.lower())

    return {
        "spy": spy_df,
        "dxy": dxy_close,
        "vix": vix_close,
        "riskoff": riskoff_close,
    }


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_dxy_signal(dxy: pd.Series, params: dict) -> pd.Series:
    """
    Compute DXY momentum signal aligned to SPY equity calendar.

    dxy_signal_t = (DXY_t / DXY_{t-lookback}) - 1

    Positive: dollar rising → potential risk-off (requires VIX confirmation in v2.0).
    DXY is a cash index traded on FX hours; ffill(limit=3) into SPY equity calendar.
    """
    lookback = params["lookback_days"]
    dxy_ff = dxy.ffill(limit=3)
    dxy_mom = dxy_ff.pct_change(lookback)
    return dxy_mom.rename("dxy_signal")


def apply_asymmetric_state_machine(
    dxy_signal: pd.Series,
    vix_series: pd.Series,
    params: dict,
) -> pd.Series:
    """
    v2.0 asymmetric state machine — VIX dual-filter with sticky exit (QUA-224).

    State transitions:
      RISK_ON  → RISK_OFF: dxy_mom > signal_threshold AND vix > vix_threshold
      RISK_OFF → RISK_ON:  dxy_mom < signal_threshold AND vix < vix_threshold
      All other combinations: HOLD CURRENT STATE (no partial trigger)

    Asymmetry critical for Q4 2022: DXY turned negative (would re-enter SPY in v1.0)
    but VIX stayed > 20 through November — asymmetric exit keeps strategy in SHY.

    VIX aligned to DXY signal index via ffill(limit=5) — covers weekends and
    any day VIX is unavailable while DXY has data.

    Returns pd.Series of bool — True = RISK_ON (hold SPY), False = RISK_OFF (hold SHY).
    """
    threshold = params["signal_threshold"]
    vix_threshold = params["vix_threshold"]

    aligned_vix = vix_series.reindex(dxy_signal.index).ffill(limit=5)

    state = True  # start RISK_ON (SPY)
    result = []

    for sig, vix in zip(dxy_signal.values, aligned_vix.values):
        if pd.isna(sig) or pd.isna(vix):
            result.append(state)
            continue

        if state:  # RISK_ON → check entry trigger
            # Both must be met to enter risk-off
            if sig > threshold and vix > vix_threshold:
                state = False
        else:  # RISK_OFF → check exit trigger
            # Both must clear to exit risk-off (asymmetric sticky)
            if sig < threshold and vix < vix_threshold:
                state = True

        result.append(state)

    return pd.Series(result, index=dxy_signal.index, dtype=bool, name="hold_spy")


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    idx: int,
) -> tuple:
    """
    Canonical equities transaction cost (Engineering Director spec, ED-SLIP-001):
      fixed    = $0.005/share
      slippage = 0.005% of notional (ultra-liquid tier: SPY ADV >> 50M shares/day)
      impact   = k × sigma × sqrt(Q / ADV) × price × Q  (Almgren-Chriss sqrt model)

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


# ── H65b Simulation Engine ─────────────────────────────────────────────────────

def simulate_h65b(
    spy_df: pd.DataFrame,
    hold_spy: pd.Series,
    dxy_signal: pd.Series,
    vix_series: pd.Series,
    riskoff_close: pd.Series | None,
    params: dict,
    initial_hold_spy: bool = True,
) -> tuple:
    """
    Simulate H65b DXY+VIX dual-filter regime-switching strategy on SPY.

    Execution model (no look-ahead):
    - Signal at T close determines desired regime for T+1 open execution.
    - SPY→SHY transition: sell SPY at T+1 open.
    - SHY→SPY transition: buy SPY at T+1 open.
    - While in SHY: capital earns SHY daily return.
    - Transaction costs applied on SPY entry/exit transitions only.

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
    signal_aligned = dxy_signal.reindex(dates)
    vix_aligned = vix_series.reindex(dates).ffill(limit=5)

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

        # ── Transition: SHY -> SPY ─────────────────────────────────────────────
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

        # ── Transition: SPY -> SHY ─────────────────────────────────────────────
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
                    "dxy_signal_at_exit": (
                        round(float(signal_aligned.iloc[i - 1]), 6)
                        if i > 0 and not pd.isna(signal_aligned.iloc[i - 1])
                        else float("nan")
                    ),
                    "vix_at_exit": (
                        round(float(vix_aligned.iloc[i - 1]), 2)
                        if i > 0 and not pd.isna(vix_aligned.iloc[i - 1])
                        else float("nan")
                    ),
                })

                in_spy = False
                spy_shares = 0
                entry_open = 0.0
                entry_cost_total = 0.0
                entry_liq = False
                entry_bar_idx = -1
                entry_date_ts = None
                n_transitions += 1

        # ── Risk-off earns SHY/BIL return ─────────────────────────────────────
        if not in_spy:
            capital *= (1.0 + riskoff_r)

        # ── Daily mark-to-market ───────────────────────────────────────────────
        mtm = capital + spy_shares * close_i if in_spy else capital
        sig_val = signal_aligned.iloc[i]
        vix_val = vix_aligned.iloc[i]

        daily_records.append({
            "date": date_i,
            "regime": "SPY" if in_spy else riskoff_label,
            "dxy_signal": float(sig_val) if not pd.isna(sig_val) else float("nan"),
            "vix_level": float(vix_val) if not pd.isna(vix_val) else float("nan"),
            "spy_shares": spy_shares if in_spy else 0,
            "equity": mtm,
        })

    # ── Force-close open SPY position at end of data ──────────────────────────
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
            "dxy_signal_at_exit": float("nan"),
            "vix_at_exit": float("nan"),
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
    Download data, compute DXY momentum + VIX signals, apply asymmetric state machine,
    and simulate H65b.

    Parameters
    ----------
    start : str  Backtest start (YYYY-MM-DD). IS: "2003-01-01".
    end : str    Backtest end (YYYY-MM-DD). IS: "2023-12-31".
    params : dict  Override PARAMETERS; uses module-level PARAMETERS if None.

    Returns
    -------
    dict with performance metrics, trade log, equity curve, daily DataFrame,
    regime statistics, data quality flags.
    """
    if params is None:
        params = PARAMETERS.copy()

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # 1. Download with warmup ──────────────────────────────────────────────────
    data = download_data(params, start, end)
    spy_full = data["spy"]
    dxy_full = data["dxy"]
    vix_full = data["vix"]
    riskoff_full = data["riskoff"]

    # 2. Align DXY to SPY calendar; compute momentum signal ───────────────────
    combined_idx = spy_full.index.union(dxy_full.index)
    dxy_aligned = dxy_full.reindex(combined_idx).ffill(limit=3)
    dxy_on_spy = dxy_aligned.reindex(spy_full.index).ffill(limit=3)

    dxy_sig_full = compute_dxy_signal(dxy_on_spy, params)

    # 3. Align VIX to SPY calendar ─────────────────────────────────────────────
    vix_combined = spy_full.index.union(vix_full.index)
    vix_aligned = vix_full.reindex(vix_combined).ffill(limit=5)
    vix_on_spy = vix_aligned.reindex(spy_full.index).ffill(limit=5)

    # 4. Apply asymmetric state machine ────────────────────────────────────────
    hold_spy_full = apply_asymmetric_state_machine(dxy_sig_full, vix_on_spy, params)

    # 5. Get initial regime state from warmup ──────────────────────────────────
    pre_mask = hold_spy_full.index < ts_start
    initial_hold_spy = bool(hold_spy_full.loc[pre_mask].iloc[-1]) if pre_mask.any() else True

    # 6. Trim to backtest window ───────────────────────────────────────────────
    def _trim(s):
        return s.loc[(s.index >= ts_start) & (s.index <= ts_end)]

    spy_df = _trim(spy_full).copy()
    dxy_sig = _trim(dxy_sig_full)
    vix_sig = _trim(vix_on_spy)
    hold_spy = _trim(hold_spy_full)
    riskoff_close = _trim(riskoff_full) if riskoff_full is not None else None

    if len(spy_df) < 10:
        raise ValueError(f"Insufficient data after trimming to {start}–{end}: {len(spy_df)} bars")

    # 7. Simulate ─────────────────────────────────────────────────────────────
    trade_log, equity, daily_df, n_transitions = simulate_h65b(
        spy_df, hold_spy, dxy_sig, vix_sig, riskoff_close, params, initial_hold_spy
    )

    # 8. Performance metrics ──────────────────────────────────────────────────
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    n_trades = len(trade_log)

    _empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price", "shares",
        "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason",
        "dxy_signal_at_exit", "vix_at_exit",
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
    cagr = round(float((1 + total_return) ** (1.0 / years) - 1), 4) if years > 0 else 0.0

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

    spy_days = riskoff_days = 0
    pct_in_spy = 0.0
    riskoff_label = params["riskoff_asset"].upper()
    if not daily_df.empty:
        spy_days = int((daily_df["regime"] == "SPY").sum())
        riskoff_days = int((daily_df["regime"] != "SPY").sum())
        pct_in_spy = round(spy_days / len(daily_df), 4)

    transitions_per_wf_fold = round(n_transitions / 4, 1)
    pf1_min = 30
    pf1_status = (
        f"PASS ({transitions_per_wf_fold:.1f}/fold >= {pf1_min})"
        if transitions_per_wf_fold >= pf1_min
        else f"WARN: {transitions_per_wf_fold:.1f}/fold < {pf1_min}"
    )

    print(
        f"\nH65b DXY+VIX Regime v2.0 ({start}–{end}) "
        f"[lookback={params['lookback_days']}d, thresh={params['signal_threshold']:.4f}, "
        f"vix_thresh={params['vix_threshold']}, riskoff={riskoff_label}]:\n"
        f"  SPY days: {spy_days} ({pct_in_spy:.1%}) | {riskoff_label} days: {riskoff_days} | "
        f"Transitions: {n_transitions} ({transitions_per_year:.1f}/yr)\n"
        f"  Sharpe: {sharpe} | CAGR: {cagr:.2%} | Max DD: {mdd:.2%} | "
        f"Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor} | "
        f"Avg hold: {avg_hold_days:.1f}d | PF-1: {pf1_status}"
    )

    return {
        "returns": daily_returns,
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params.copy(),
        "data_quality": {
            "survivorship_bias_flag": "SPY/SHY are live ETFs — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "spy_ticker": params["spy_ticker"],
            "dxy_ticker": params["dxy_ticker"],
            "vix_ticker": params["vix_ticker"],
            "dxy_note": (
                "DX-Y.NYB is the ICE US Dollar Index cash level (not a futures contract). "
                "No roll-gap check required. ffill(limit=3) into SPY equity calendar."
            ),
            "vix_note": (
                "^VIX CBOE VIX. Available from 1990. ffill(limit=5) into SPY calendar. "
                "VIX is not traded — signal only. No transaction cost for VIX."
            ),
            "riskoff_asset": params["riskoff_asset"],
            "asymmetric_exit": True,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY/SHY are active ETFs",
            "signal_lag": (
                "dxy_signal + vix_level at T uses only close data through T; "
                "position change executes at T+1 open (no look-ahead bias)"
            ),
        },
        "sharpe": sharpe,
        "cagr": cagr,
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
        "riskoff_days": riskoff_days,
        "pct_in_spy": pct_in_spy,
        "avg_hold_days": avg_hold_days,
        "years": years,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2003-01-01",
    end: str = "2025-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """Orchestrator-compatible entry point for H65b v2.0."""
    p = (params or PARAMETERS).copy()
    result = run_backtest(start, end, p)

    daily = result["daily_df"].reset_index()
    trades = result["trades"]

    trade_merge_cols = ["exit_date", "pnl", "entry_price", "exit_price",
                        "transaction_cost", "exit_reason"]

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

    out_cols = ["date", "regime", "dxy_signal", "vix_level", "spy_shares",
                "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason", "equity"]
    for col in out_cols:
        if col not in daily.columns:
            daily[col] = float("nan")

    return daily[out_cols]


if __name__ == "__main__":
    # Quick smoke test
    result_is = run_backtest("2003-01-01", "2023-12-31")
    print(f"\n[IS 2003-2023] Transitions: {result_is['n_transitions']} | "
          f"SPY%: {result_is['pct_in_spy']:.1%} | Sharpe: {result_is['sharpe']} | "
          f"CAGR: {result_is['cagr']:.2%}")

    result_2022 = run_backtest("2022-01-01", "2022-12-31")
    print(f"[2022 rate-shock] Transitions: {result_2022['n_transitions']} | "
          f"MDD: {result_2022['max_drawdown']:.2%} | "
          f"Total Return: {result_2022['total_return']:.2%} | "
          f"SPY%: {result_2022['pct_in_spy']:.1%}")

    result_2014 = run_backtest("2014-01-01", "2015-12-31")
    print(f"[2014-2015 dollar bull] Transitions: {result_2014['n_transitions']} | "
          f"Sharpe: {result_2014['sharpe']} | SPY%: {result_2014['pct_in_spy']:.1%}")
