"""
Strategy: H65 US Dollar Strength Regime — SPY/SHY Binary Allocation Timer
Author: Engineering Director (QUA-213)
Date: 2026-06-11
Hypothesis: DX-Y.NYB (US Dollar Index) 20-day momentum as macro regime signal.
            Rising dollar (dxy_mom > threshold) → global financial conditions
            tightening → hold SHY (risk-off).
            Flat/falling dollar (dxy_mom <= threshold) → accommodative conditions
            → hold SPY (risk-on).
            Signal evaluated daily; transitions executed at next day open (T+1 MOO).
Asset class: US equity (SPY ETF) / short Treasury ETF (SHY)
Parent task: QUA-213
References: Miranda-Agrippino & Rey (2020 RoES); Rey (2013 Jackson Hole);
            Avdjiev, Du, Koch & Shin (2019 IMF Econ Rev);
            research/hypotheses/65_dollar_strength_regime.md
IS window:  2003-01-01 to 2023-12-31 (20yr)
OOS window: 2024-01-01 to 2026-06-10
Data note:  DX-Y.NYB available from 1972; SPY from 1993; SHY from 2002.
            IS start 2003 is safe with full warmup for all series.
Replaces:   H58 (Cu/Au Ratio Regime — retired 2026-06-11, QUA-207)

Signal direction: OPPOSITE to H58.
  H58 Cu/Au > 0 → risk-on (copper > gold = industrial demand > safe-haven).
  H65 DXY mom > 0 → risk-OFF (rising dollar = global financial tightening).
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "spy_ticker": "SPY",
    "dxy_ticker": "DX-Y.NYB",    # US Dollar Index cash — signal only, not traded
    # Signal parameters
    "lookback_days": 20,          # DXY momentum lookback; range: 10–60
    "signal_threshold": 0.0,      # exit to SHY if dxy_mom > threshold; range: -0.01–0.02
    "smoothing_days": 1,          # consecutive days signal > threshold before exit; range: 1–3
    # Risk-off asset: SHY (primary), BIL, TLT (avoid TLT in rate-shock regimes)
    "riskoff_asset": "SHY",
    "init_cash": 25000,
}

# ── Transaction Cost Constants (Engineering Director spec; ED-SLIP-001) ────────
# SPY is ultra-liquid (ADV >> 50M shares/day) — use ED-SLIP-001 tier
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
    Download SPY (OHLCV), DX-Y.NYB (Close), and risk-off asset (Close).

    Warmup: 2x max(lookback, SIGMA_WINDOW, ADV_WINDOW) in calendar days so
    all rolling indicators are warm at IS/OOS start date.

    Raises ValueError on missing columns or insufficient data.
    Warns (does not silently forward-fill) on gaps >= 5 consecutive days.

    Note: DX-Y.NYB is a cash index computed daily on FX trading days.
    DXY values are ffill'd into SPY equity calendar (limit=3) for holidays/weekends.
    No roll-gap check needed (cash index, not futures front-month continuous).
    """
    lookback = params["lookback_days"]
    warmup_days = max(SIGMA_WINDOW, ADV_WINDOW, lookback) + 30
    warmup_cal = warmup_days * 2
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_cal)
    ).strftime("%Y-%m-%d")

    spy_ticker = params["spy_ticker"]
    dxy_ticker = params["dxy_ticker"]
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
        "riskoff": riskoff_close,
    }


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_dxy_signal(dxy: pd.Series, params: dict) -> pd.Series:
    """
    Compute DXY momentum regime signal.

    dxy_signal_t = (DXY_t / DXY_{t-lookback}) - 1

    Positive: dollar rising → global financial conditions tightening → RISK-OFF.
    Negative/flat: dollar flat/falling → accommodative conditions → RISK-ON.

    Note: signal direction is OPPOSITE to H58's Cu/Au signal.
      H58: signal > threshold → risk-on (hold SPY).
      H65: signal > threshold → risk-off (hold SHY).

    Signal at T uses only DX-Y.NYB close data through T (no look-ahead).
    Position change executes at T+1 open — enforced in simulation loop.

    DXY is a cash index traded on FX market hours; forward-fill into SPY
    equity calendar covers weekends and US holidays (limit=3 days).

    Returns pd.Series of float, NaN for the first lookback periods.
    """
    lookback = params["lookback_days"]

    # Align DXY to SPY trading calendar via ffill
    # DXY trades FX hours; may have data on days SPY closes (and vice versa)
    dxy_ff = dxy.ffill(limit=3)
    dxy_mom = dxy_ff.pct_change(lookback)
    return dxy_mom.rename("dxy_signal")


def apply_smoothing_filter(signal: pd.Series, params: dict) -> pd.Series:
    """
    Apply consecutive-day smoothing to the DXY momentum signal (state machine).

    smoothing_days=1 (default): exit to SHY on first day dxy_signal > threshold.
    smoothing_days=N: require N consecutive days of signal > threshold before exit.
    Re-entry into SPY is always immediate (first day signal <= threshold).

    State machine:
    - "SPY": transitions to "SHY" after N consecutive days of signal > threshold.
    - "SHY": transitions to "SPY" immediately when signal <= threshold.

    NaN (warmup): do not advance consecutive-day counter; maintain current state.

    Note: INVERTED relative to H58. H58 exits when signal <= threshold.
          H65 exits when signal > threshold (rising dollar = risk-off).

    Returns pd.Series of bool — True = hold SPY (risk-on), False = hold SHY (risk-off).
    """
    threshold = params["signal_threshold"]
    n_days = params["smoothing_days"]

    result = []
    state = True               # start risk-on (SPY)
    consecutive_risk_off = 0

    for sig in signal:
        if pd.isna(sig):
            result.append(state)
            continue

        # Dollar rising = potential risk-off signal
        if sig > threshold:
            consecutive_risk_off += 1
        else:
            consecutive_risk_off = 0

        if state:  # currently in SPY
            if consecutive_risk_off >= n_days:
                state = False  # exit to SHY
        else:  # currently in SHY
            if sig <= threshold:
                state = True   # return to SPY immediately
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


# ── H65 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h65(
    spy_df: pd.DataFrame,
    hold_spy: pd.Series,
    dxy_signal: pd.Series,
    riskoff_close: pd.Series | None,
    params: dict,
    initial_hold_spy: bool = True,
) -> tuple:
    """
    Simulate H65 DXY regime-switching strategy on SPY.

    Execution model (no look-ahead):
    - Signal at T close determines desired regime for T+1 open execution.
    - SPY→SHY transition: sell SPY at T+1 open.
    - SHY→SPY transition: buy SPY at T+1 open.
    - While in SHY: capital earns SHY daily return.
    - Transaction costs applied on SPY entry/exit transitions only.
    - initial_hold_spy: regime state at day 0 open, derived from warmup signal.

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
                })

                in_spy = False
                spy_shares = 0
                entry_open = 0.0
                entry_cost_total = 0.0
                entry_liq = False
                entry_bar_idx = -1
                entry_date_ts = None
                n_transitions += 1

        # ── Risk-off earns SHY return ──────────────────────────────────────────
        if not in_spy:
            capital *= (1.0 + riskoff_r)

        # ── Daily mark-to-market ───────────────────────────────────────────────
        mtm = capital + spy_shares * close_i if in_spy else capital
        sig_val = signal_aligned.iloc[i]

        daily_records.append({
            "date": date_i,
            "regime": "SPY" if in_spy else riskoff_label,
            "dxy_signal": float(sig_val) if not pd.isna(sig_val) else float("nan"),
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
    Download data, compute DXY momentum signal, apply smoothing, and simulate H65.

    Parameters
    ----------
    start : str  Backtest start (YYYY-MM-DD). IS: "2003-01-01".
    end : str    Backtest end (YYYY-MM-DD). IS: "2023-12-31".
    params : dict  Override PARAMETERS; uses module-level PARAMETERS if None.

    Returns
    -------
    dict with performance metrics, trade log, equity curve, daily DataFrame,
    regime statistics, data quality flags, and GFC exit diagnostic.
    """
    if params is None:
        params = PARAMETERS.copy()

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # 1. Download with warmup ──────────────────────────────────────────────────
    data = download_data(params, start, end)
    spy_full = data["spy"]
    dxy_full = data["dxy"]
    riskoff_full = data["riskoff"]

    # 2. Compute signal on warmup-inclusive series (no look-ahead) ─────────────
    # Align DXY to SPY trading calendar via outer join, then ffill
    combined_idx = spy_full.index.union(dxy_full.index)
    dxy_aligned = dxy_full.reindex(combined_idx).ffill(limit=3)
    # Restrict to SPY trading days
    dxy_on_spy = dxy_aligned.reindex(spy_full.index).ffill(limit=3)

    dxy_sig_full = compute_dxy_signal(dxy_on_spy, params)
    hold_spy_full = apply_smoothing_filter(dxy_sig_full, params)

    # 3. Get initial regime state from last warmup day before IS window ─────────
    pre_mask = hold_spy_full.index < ts_start
    initial_hold_spy = bool(hold_spy_full.loc[pre_mask].iloc[-1]) if pre_mask.any() else True

    # 4. Trim to backtest window ───────────────────────────────────────────────
    def _trim(s):
        return s.loc[(s.index >= ts_start) & (s.index <= ts_end)]

    spy_df = _trim(spy_full).copy()
    dxy_sig = _trim(dxy_sig_full)
    hold_spy = _trim(hold_spy_full)
    riskoff_close = _trim(riskoff_full) if riskoff_full is not None else None

    if len(spy_df) < 10:
        raise ValueError(f"Insufficient data after trimming to {start}–{end}: {len(spy_df)} bars")

    # 5. Simulate ─────────────────────────────────────────────────────────────
    trade_log, equity, daily_df, n_transitions = simulate_h65(
        spy_df, hold_spy, dxy_sig, riskoff_close, params, initial_hold_spy
    )

    # 6. Performance metrics ──────────────────────────────────────────────────
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    n_trades = len(trade_log)

    _empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price", "shares",
        "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_days", "exit_reason", "dxy_signal_at_exit",
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

    # 7. GFC exit timing diagnostic (Sept 2008 exit date/price) ──────────────
    gfc_diagnostic = {}
    if not trades_df.empty:
        trades_df_dated = trades_df.copy()
        trades_df_dated["exit_date_ts"] = pd.to_datetime(trades_df_dated["exit_date"])
        gfc_exits = trades_df_dated[
            (trades_df_dated["exit_date_ts"] >= pd.Timestamp("2008-08-01")) &
            (trades_df_dated["exit_date_ts"] <= pd.Timestamp("2008-12-31")) &
            (trades_df_dated["exit_reason"] == "SIGNAL_EXIT")
        ]
        if not gfc_exits.empty:
            first_gfc_exit = gfc_exits.iloc[0]
            gfc_diagnostic = {
                "gfc_first_exit_date": str(first_gfc_exit["exit_date"]),
                "gfc_first_exit_price": float(first_gfc_exit["exit_price"]),
                "gfc_n_exits_aug_dec_2008": len(gfc_exits),
                "note": "Strategy exits SPY to SHY — validates PF-2 gate (GFC protection)",
            }
        else:
            if not daily_df.empty:
                aug_2008 = daily_df.loc[
                    (daily_df.index >= pd.Timestamp("2008-08-01")) &
                    (daily_df.index <= pd.Timestamp("2008-09-15"))
                ]
                in_shy_aug = int((aug_2008["regime"] != "SPY").sum()) if not aug_2008.empty else 0
                gfc_diagnostic = {
                    "gfc_first_exit_date": None,
                    "note": f"No exit signal fired Aug–Dec 2008. Days in SHY Aug 1–Sep 15: {in_shy_aug}",
                }
    else:
        gfc_diagnostic = {"note": "No trades — cannot compute GFC exit diagnostic"}

    print(
        f"\nH65 DXY Regime Timer ({start}–{end}) "
        f"[lookback={params['lookback_days']}d, thresh={params['signal_threshold']:.4f}, "
        f"smooth={params['smoothing_days']}d, riskoff={riskoff_label}]:\n"
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
        "gfc_diagnostic": gfc_diagnostic,
        "data_quality": {
            "survivorship_bias_flag": "SPY/SHY are live ETFs — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "spy_ticker": params["spy_ticker"],
            "dxy_ticker": params["dxy_ticker"],
            "dxy_note": (
                "DX-Y.NYB is the ICE US Dollar Index cash level (not a futures contract). "
                "No roll-gap check required. ffill(limit=3) into SPY equity calendar."
            ),
            "riskoff_asset": params["riskoff_asset"],
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — SPY/SHY are active ETFs; DX-Y.NYB is a cash index",
            "forward_fill_policy": (
                "DX-Y.NYB forward-filled into SPY calendar (limit=3 days, covers weekend/holiday gaps). "
                "Silent forward-fill NOT applied for equity data gaps >= 5 days."
            ),
            "signal_lag": (
                "dxy_signal at T uses only DX-Y.NYB close data through T; "
                "position change executes at T+1 open (no look-ahead bias)"
            ),
            "survivorship_bias": "SPY and SHY are broad-market/treasury ETFs — no survivorship bias",
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
    """
    Orchestrator-compatible entry point for H65.

    Returns daily DataFrame with columns:
        date, regime, dxy_signal, spy_shares, pnl, entry_price, exit_price,
        transaction_cost, exit_reason, equity
    """
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

    out_cols = ["date", "regime", "dxy_signal", "spy_shares",
                "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason", "equity"]
    for col in out_cols:
        if col not in daily.columns:
            daily[col] = float("nan")

    return daily[out_cols]


if __name__ == "__main__":
    # ── IS baseline (lookback=20d, smoothing=1d, SHY) ─────────────────────────
    result_is = run_backtest("2003-01-01", "2023-12-31")
    print(
        f"\n[IS baseline lookback=20 2003–2023] Transitions: {result_is['n_transitions']} | "
        f"SPY%: {result_is['pct_in_spy']:.1%} | Sharpe: {result_is['sharpe']} | "
        f"CAGR: {result_is['cagr']:.2%}"
    )
    print(f"  GFC diagnostic: {result_is['gfc_diagnostic']}")

    # ── IS primary variant (lookback=60d) ─────────────────────────────────────
    params_60 = PARAMETERS.copy()
    params_60["lookback_days"] = 60
    result_is_60 = run_backtest("2003-01-01", "2023-12-31", params_60)
    print(
        f"[IS primary lookback=60 2003–2023] Transitions: {result_is_60['n_transitions']} | "
        f"Sharpe: {result_is_60['sharpe']} | CAGR: {result_is_60['cagr']:.2%}"
    )

    # ── 2014–2015 dollar bull diagnostic ──────────────────────────────────────
    result_2014_15 = run_backtest("2014-01-01", "2015-12-31")
    print(
        f"[2014–2015 dollar bull] Transitions: {result_2014_15['n_transitions']} | "
        f"Sharpe: {result_2014_15['sharpe']} | MDD: {result_2014_15['max_drawdown']:.2%}"
    )

    # ── GFC stress test ────────────────────────────────────────────────────────
    result_gfc = run_backtest("2007-01-01", "2009-12-31")
    print(
        f"[GFC 2007–2009] Transitions: {result_gfc['n_transitions']} | "
        f"Max DD: {result_gfc['max_drawdown']:.2%} | "
        f"Total Return: {result_gfc['total_return']:.2%}"
    )
    print(f"  GFC exit: {result_gfc['gfc_diagnostic']}")

    # ── 2022 rate-shock ────────────────────────────────────────────────────────
    result_2022 = run_backtest("2022-01-01", "2022-12-31")
    print(
        f"[2022 rate-shock] Transitions: {result_2022['n_transitions']} | "
        f"Max DD: {result_2022['max_drawdown']:.2%} | "
        f"Total Return: {result_2022['total_return']:.2%} | "
        f"SPY%: {result_2022['pct_in_spy']:.1%}"
    )

    # ── OOS: 2024–2026 ────────────────────────────────────────────────────────
    result_oos = run_backtest("2024-01-01", "2026-06-10")
    print(
        f"\n[OOS 2024–2026] Transitions: {result_oos['n_transitions']} | "
        f"Sharpe: {result_oos['sharpe']} | Max DD: {result_oos['max_drawdown']:.2%}"
    )

    print(f"\nEquity final (IS baseline): ${result_is['equity'].iloc[-1]:,.2f}")
