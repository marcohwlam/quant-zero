"""
Strategy: H81v2 USD-EM Relative Spread (UURR) Three-State Regime Filter
Author: Strategy Coder Agent
Date: 2026-06-22
Hypothesis: UURR = UUP_63d_return - EEM_63d_return continuous spread drives
            a three-state regime (EM_DOMINANT / NEUTRAL / USD_DOMINANT) plus
            VIX > 30 override. Allocates EEM vs SHY weekly.
Asset class: equities (EM ETF + Treasury ETF rotation)
Parent task: QUA-387
Parent hypothesis: H81v2 (QUA-385 revision of H81 Gate 1 FAIL)
IS window:  2008-01-01 to 2022-12-31 (same as H81 for direct comparison)
OOS window: 2023-01-01 to 2026-06-01

Key improvement vs H81:
  H81 used binary UUP vs 50-day SMA → permutation p=1.0 (no timing alpha)
  H81v2 uses UURR relative spread + neutral zone to reduce churn in
  2013-2021 range-bound period and improve signal informativeness.

References:
  Koijen et al. (2018) JFE — carry and EM equity link (relative return is correct frame)
  Lustig, Roussanov, Verdelhan (2011) RFS — currency return as relative measure
  Menkhoff et al. (2012) JFE — cross-currency momentum
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    "uurr_lookback": 63,          # sweep: [42, 63, 126]
    "uurr_threshold": 0.05,       # sweep: [0.03, 0.05, 0.08] (±5% spread threshold)
    "neutral_eem_weight": 0.40,   # sweep: [0.30, 0.40, 0.50]
    "vix_threshold": 30,          # sweep: [25, 30, 35]
    "init_cash": 25000,
}

TRADING_DAYS_PER_YEAR = 252
MARKET_IMPACT_K = 0.1
SIGMA_WINDOW = 20
ADV_WINDOW = 20

# Slippage tiers per ED spec (ED-SLIP-001 ultra-liquid not applicable here)
SLIPPAGE = {
    "EEM": 0.0005,   # standard: 0.05%
    "SHY": 0.0005,   # standard: 0.05%
}


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_single(tickers: list, start: str, end: str) -> tuple:
    """Download adjusted close + volume. Returns (close_df, volume_df)."""
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        volume = raw["Volume"]
    else:
        t = tickers[0] if len(tickers) == 1 else tickers
        close = raw[["Close"]].rename(columns={"Close": t})
        volume = raw[["Volume"]].rename(columns={"Volume": t})
    return close.copy(), volume.copy()


def _check_gaps(series: pd.Series, label: str, threshold: int = 5) -> None:
    if not series.isna().any():
        return
    groups = series.notna().cumsum()
    max_gap = int(series.isna().astype(int).groupby(groups).sum().max())
    if max_gap >= threshold:
        warnings.warn(
            f"DATA QUALITY: {label} has {max_gap} consecutive missing days "
            f"(>= {threshold} threshold)"
        )


def download_data(params: dict, start: str, end: str) -> dict:
    """
    Download all required instruments with warmup buffer.

    Warmup = max(uurr_lookback) * 2 calendar days to ensure UURR warm at IS start.
    Returns dict: close, volume (EEM/SHY), uup_close, eem_close (for UURR), vix_close.
    """
    lookback = params["uurr_lookback"]
    warmup_cal = (lookback + 30) * 2
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_cal)).strftime("%Y-%m-%d")

    # Position instruments
    close_port, vol_port = _download_single(["EEM", "SHY"], warmup_start, end)
    for t in ["EEM", "SHY"]:
        _check_gaps(close_port[t], t)

    # Signal instruments (not held): UUP and VIX
    close_sig, _ = _download_single(["UUP"], warmup_start, end)
    _check_gaps(close_sig["UUP"], "UUP")

    close_vix, _ = _download_single(["^VIX"], warmup_start, end)
    # ^VIX may come back with column named "^VIX"
    vix_col = close_vix.columns[0]
    _check_gaps(close_vix[vix_col], "^VIX")

    # UUP inception guard (2007-02-20)
    uup_start = close_sig["UUP"].first_valid_index()
    if uup_start is not None and uup_start > pd.Timestamp("2008-01-01"):
        warnings.warn(
            f"UUP data starts {uup_start.date()} — IS start 2008-01-01 requires "
            f"{lookback}-day UURR warmup."
        )

    # EEM close for UURR signal computation (aligned to portfolio calendar)
    eem_for_signal = close_port["EEM"].copy()

    return {
        "close": close_port,
        "volume": vol_port,
        "uup": close_sig["UUP"],
        "eem_signal": eem_for_signal,
        "vix": close_vix[vix_col],
    }


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_uurr_regime(
    uup: pd.Series,
    eem: pd.Series,
    vix: pd.Series,
    params: dict,
) -> pd.DataFrame:
    """
    Compute UURR = UUP_lookback_return - EEM_lookback_return (daily).

    Returns DataFrame with: uurr, regime, vix_extreme
    Regime values: EM_DOMINANT, NEUTRAL, USD_DOMINANT, VIX_OVERRIDE
    No look-ahead: all rolling windows computed on past data only.
    """
    lb = params["uurr_lookback"]
    threshold = params["uurr_threshold"]
    vix_thr = params["vix_threshold"]

    # Align all series to common index (portfolio calendar)
    common_idx = uup.dropna().index.intersection(eem.dropna().index)
    uup_a = uup.reindex(eem.index).ffill(limit=5)
    eem_a = eem.copy()
    vix_a = vix.reindex(eem.index).ffill(limit=5)

    uup_ret = uup_a / uup_a.shift(lb) - 1
    eem_ret = eem_a / eem_a.shift(lb) - 1
    uurr = uup_ret - eem_ret

    vix_extreme = vix_a > vix_thr

    # Three-state classification
    regime = pd.Series("NEUTRAL", index=eem.index, dtype=object)
    regime[uurr > threshold] = "USD_DOMINANT"
    regime[uurr < -threshold] = "EM_DOMINANT"
    # VIX override: EM_DOMINANT or NEUTRAL → VIX_OVERRIDE (treated as USD_DOMINANT for allocation)
    vix_mask = vix_extreme & (regime != "USD_DOMINANT")
    regime[vix_mask] = "VIX_OVERRIDE"

    # Warmup rows → NEUTRAL (conservative, hold SHY partially)
    warmup_mask = uurr.isna()
    regime[warmup_mask] = "NEUTRAL"

    return pd.DataFrame({
        "uurr": uurr,
        "vix": vix_a,
        "vix_extreme": vix_extreme,
        "regime": regime,
    }, index=eem.index)


def regime_to_allocation(regime: str, params: dict) -> dict:
    """Map regime string to {EEM: w, SHY: 1-w} target allocation."""
    neutral_wt = params["neutral_eem_weight"]
    if regime == "EM_DOMINANT":
        eem_w = 1.0
    elif regime == "NEUTRAL":
        eem_w = neutral_wt
    else:  # USD_DOMINANT or VIX_OVERRIDE
        eem_w = 0.0
    return {"EEM": eem_w, "SHY": 1.0 - eem_w}


# ── Transaction Cost ───────────────────────────────────────────────────────────

def compute_transaction_cost(
    ticker: str,
    trade_value: float,
    shares: float,
    sigma: float,
    dollar_adv: float,
) -> tuple:
    """
    Canonical transaction cost per ED spec:
      fixed    = $0.005/share
      slippage = 0.05% of notional (standard tier)
      impact   = k * sigma * sqrt(Q/ADV) * trade_value

    Returns (total_cost_dollars, liquidity_constrained).
    """
    fixed = 0.005 * abs(shares)
    slip_pct = SLIPPAGE.get(ticker, 0.0005)
    slippage = slip_pct * trade_value

    q_over_adv = trade_value / max(dollar_adv, 1.0)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(max(q_over_adv, 0)) * trade_value
    liq_constrained = bool(q_over_adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained: {ticker} trade_value=${trade_value:,.0f} "
            f"is {q_over_adv:.2%} of ADV"
        )

    return fixed + slippage + impact, liq_constrained


# ── Main Simulation Engine ─────────────────────────────────────────────────────

def simulate_h81v2(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    weekly_alloc: pd.Series,
    params: dict,
) -> dict:
    """
    Simulate H81v2 two-asset rotation (EEM / SHY).

    Execution model:
    - Friday close: compute UURR, determine regime, set target allocation.
    - Monday open: rebalance IF target differs from current (change-only).
    - Daily MTM using close prices.
    - Transaction costs applied per rebalance.

    Returns dict with metrics, equity curve, trade log.
    """
    tickers = ["EEM", "SHY"]
    init_cash = float(params["init_cash"])

    sigma_d = {}
    dollar_adv_d = {}
    for t in tickers:
        if t in close.columns:
            daily_ret = close[t].pct_change()
            sigma_d[t] = daily_ret.rolling(SIGMA_WINDOW).std()
            if t in volume.columns:
                dollar_adv_d[t] = (volume[t] * close[t]).rolling(ADV_WINDOW).mean()
            else:
                dollar_adv_d[t] = pd.Series(1e9, index=close.index)

    # Build execution schedule: Friday signal → next trading Monday
    exec_schedule = {}
    for i, fri in enumerate(weekly_alloc.index):
        alloc = weekly_alloc.iloc[i]
        future = close.index[close.index > fri]
        if len(future) == 0:
            continue
        exec_date = future[0]
        exec_schedule[exec_date] = alloc

    shares = {t: 0.0 for t in tickers}
    cash = init_cash
    current_target = {"EEM": 0.0, "SHY": 1.0}  # start defensive in SHY

    equity_curve = pd.Series(dtype=float, index=close.index)
    trade_log = []
    liquidity_flags = []

    def _portfolio_value(date):
        val = cash
        for t in tickers:
            if t in close.columns and shares[t] > 0:
                p = close[t].get(date, np.nan)
                if not np.isnan(p):
                    val += shares[t] * p
        return val

    def _execute_rebalance(date, target_alloc):
        nonlocal cash
        total_val = _portfolio_value(date)
        if total_val <= 0:
            return

        for t in tickers:
            if t not in close.columns:
                continue
            price = close[t].get(date, np.nan)
            if np.isnan(price) or price <= 0:
                continue

            target_val = total_val * target_alloc.get(t, 0.0)
            current_val = shares[t] * price
            delta_val = target_val - current_val

            if abs(delta_val) < 1.0:
                continue

            delta_shares = delta_val / price
            sig = sigma_d[t].get(date, 0.01) if t in sigma_d else 0.01
            if np.isnan(sig) or sig <= 0:
                sig = 0.01
            dadv = dollar_adv_d[t].get(date, 1e9) if t in dollar_adv_d else 1e9
            if np.isnan(dadv) or dadv <= 0:
                dadv = 1e9

            trade_val = abs(delta_val)
            trade_shares = abs(delta_shares)
            cost, liq = compute_transaction_cost(t, trade_val, trade_shares, sig, dadv)

            if liq:
                liquidity_flags.append({
                    "date": str(date.date()), "ticker": t,
                    "trade_value": round(trade_val, 2)
                })

            side = "buy" if delta_shares > 0 else "sell"
            if side == "buy":
                net_cost = trade_val + cost
                if net_cost > cash + 1.0:
                    scale = max(cash - cost, 0) / trade_val if trade_val > 0 else 0
                    delta_shares *= scale
                    trade_val *= scale
                    trade_shares = abs(delta_shares)
                    cost, liq = compute_transaction_cost(t, trade_val, trade_shares, sig, dadv)
                    net_cost = trade_val + cost
                if delta_shares > 0:
                    shares[t] += delta_shares
                    cash -= net_cost
            else:
                proceeds = trade_val - cost
                shares[t] += delta_shares
                cash += proceeds

            trade_log.append({
                "date": str(date.date()),
                "ticker": t,
                "side": side,
                "shares": round(abs(delta_shares), 4),
                "price": round(price, 4),
                "trade_value": round(trade_val, 2),
                "cost": round(cost, 4),
                "liquidity_constrained": liq,
                "target_weight": round(target_alloc.get(t, 0.0), 4),
            })

    for i, date in enumerate(close.index):
        new_alloc = exec_schedule.get(date, None)
        should_rebalance = False

        if new_alloc is not None:
            alloc_d = new_alloc if isinstance(new_alloc, dict) else new_alloc.to_dict()
            # Only rebalance when target actually changes
            for t in tickers:
                if abs(alloc_d.get(t, 0.0) - current_target.get(t, 0.0)) > 1e-6:
                    should_rebalance = True
                    break

        if should_rebalance:
            _execute_rebalance(date, alloc_d)
            current_target = alloc_d.copy()

        equity_curve.iloc[i] = _portfolio_value(date)

    equity_curve = equity_curve.ffill().fillna(init_cash)
    last_val = float(equity_curve.iloc[-1])

    daily_ret = equity_curve.pct_change().fillna(0.0).values
    sharpe = 0.0
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe = round(float(daily_ret.mean() / daily_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + daily_ret) if len(daily_ret) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)
    years = max((close.index[-1] - close.index[0]).days / 365.25, 1e-3)
    cagr = round(float((1 + total_return) ** (1.0 / years) - 1), 4)

    trades_df = pd.DataFrame([t for t in trade_log if "ticker" in t])
    n_trades = len(trades_df)

    # Win rate: fraction of weekly allocation periods with positive return
    exec_dates = sorted(exec_schedule.keys())
    segment_rets = []
    for j in range(len(exec_dates) - 1):
        d0, d1 = exec_dates[j], exec_dates[j + 1]
        v0 = equity_curve.get(d0, np.nan)
        v1 = equity_curve.get(d1, np.nan)
        if not np.isnan(v0) and not np.isnan(v1) and v0 > 0:
            segment_rets.append((v1 - v0) / v0)
    win_rate = round(float(np.mean([r > 0 for r in segment_rets])), 4) if segment_rets else 0.0

    return {
        "sharpe": sharpe,
        "cagr": cagr,
        "max_drawdown": mdd,
        "total_return": total_return,
        "trade_count": n_trades,
        "win_rate": win_rate,
        "equity": equity_curve,
        "trade_log": trade_log,
        "liquidity_flags": liquidity_flags,
        "final_value": round(last_val, 2),
        "years": round(years, 2),
    }


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Full H81v2 backtest: download → signal → weekly schedule → simulate → metrics.

    Parameters
    ----------
    start : str  IS: "2008-01-01"
    end   : str  IS: "2022-12-31"
    params: dict  Overrides PARAMETERS. If None, uses module-level PARAMETERS.

    Returns
    -------
    dict with sharpe, cagr, max_drawdown, total_return, trade_count, win_rate,
         equity, trade_log, regime_counts, params, data_quality, etc.
    """
    if params is None:
        params = PARAMETERS.copy()

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    data = download_data(params, start, end)
    close_full = data["close"]
    volume_full = data["volume"]

    # Compute UURR regime daily (full buffered window, no look-ahead)
    regime_df = compute_uurr_regime(
        data["uup"], data["eem_signal"], data["vix"], params
    )

    # Extract Friday evaluations
    weekly_dates = close_full.index[close_full.index.dayofweek == 4]
    if len(weekly_dates) == 0:
        weekly_dates = close_full.resample("W-FRI").last().index.intersection(close_full.index)

    weekly_regime = regime_df["regime"].reindex(weekly_dates, method="ffill")

    # Build weekly allocation (no confirmation filter for H81v2 — UURR threshold is the filter)
    weekly_alloc = pd.Series(index=weekly_dates, dtype=object)
    for i, fri in enumerate(weekly_dates):
        reg = weekly_regime.iloc[i]
        weekly_alloc.iloc[i] = regime_to_allocation(reg, params)

    # Trim to backtest window
    def _trim(df):
        return df.loc[(df.index >= ts_start) & (df.index <= ts_end)].copy()

    close_sim = _trim(close_full)
    volume_sim = _trim(volume_full)
    weekly_alloc_sim = weekly_alloc[
        (weekly_alloc.index >= ts_start) & (weekly_alloc.index <= ts_end)
    ]

    if len(close_sim) < 10:
        raise ValueError(f"Insufficient data: {len(close_sim)} bars in {start}–{end}")

    result = simulate_h81v2(close_sim, volume_sim, weekly_alloc_sim, params)

    # Regime breakdown (IS period only)
    regime_is = regime_df["regime"][
        (regime_df.index >= ts_start) & (regime_df.index <= ts_end)
    ]
    regime_counts = regime_is.value_counts().to_dict()
    weekly_regime_is = weekly_regime[
        (weekly_regime.index >= ts_start) & (weekly_regime.index <= ts_end)
    ]
    regime_counts_weekly = weekly_regime_is.value_counts().to_dict()

    years = result["years"]
    n_trades = result["trade_count"]
    trades_per_quarter = round(n_trades / max(years * 4, 1), 1)
    pf1_status = (
        f"PASS ({trades_per_quarter:.1f}/quarter >= 30)"
        if trades_per_quarter >= 30
        else f"RISK: {trades_per_quarter:.1f}/quarter < 30 — PF-1 floor not met"
    )

    print(
        f"\nH81v2 UURR Three-State ({start}–{end}) "
        f"[lookback={params['uurr_lookback']}d, threshold={params['uurr_threshold']:.0%}, "
        f"neutral_eem={params['neutral_eem_weight']:.0%}, vix_thr={params['vix_threshold']}]:\n"
        f"  Sharpe: {result['sharpe']} | CAGR: {result['cagr']:.2%} | "
        f"Max DD: {result['max_drawdown']:.2%} | Total Return: {result['total_return']:.2%}\n"
        f"  Trade count: {n_trades} ({trades_per_quarter:.1f}/quarter) | "
        f"Win rate: {result['win_rate']:.2%} | Final: ${result['final_value']:,.2f}\n"
        f"  Weekly regime (IS) — EM_DOMINANT: {regime_counts_weekly.get('EM_DOMINANT',0)} | "
        f"NEUTRAL: {regime_counts_weekly.get('NEUTRAL',0)} | "
        f"USD_DOMINANT: {regime_counts_weekly.get('USD_DOMINANT',0)} | "
        f"VIX_OVERRIDE: {regime_counts_weekly.get('VIX_OVERRIDE',0)}\n"
        f"  PF-1: {pf1_status}"
    )

    return {
        **result,
        "params": params.copy(),
        "pf1_status": pf1_status,
        "regime_counts": regime_counts_weekly,
        "weekly_alloc": weekly_alloc_sim,
        "data_quality": {
            "survivorship_bias": (
                "Fixed 2-ticker portfolio (EEM/SHY) + UUP/VIX signal only. "
                "All ETFs active and liquid. No individual stock survivorship bias."
            ),
            "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
            "data_gaps": "Gaps >=5 consecutive days trigger warning.",
            "uup_inception": (
                f"UUP launched 2007-02-20. IS start 2008-01-01 gives {params['uurr_lookback']}-day "
                "UURR warmup (buffered via pre-start download)."
            ),
            "delisted": "N/A — EEM (2003+), SHY (2002+), UUP (2007+) all active.",
            "earnings_exclusion": "N/A — ETF basket strategy.",
            "signal_lag": (
                "Friday close signal → Monday open execution (T+1). "
                "UURR threshold acts as the hysteresis filter (no separate confirmation filter). "
                "No look-ahead bias: regime computed from rolling past returns only."
            ),
        },
    }


def run_strategy(
    ticker: str = "EEM",
    start: str = "2008-01-01",
    end: str = "2022-12-31",
    params: dict = None,
) -> dict:
    """Orchestrator-compatible entry point. ticker arg ignored (multi-asset)."""
    p = (params or PARAMETERS).copy()
    return run_backtest(start, end, p)


def scan_parameters(
    start: str = "2008-01-01",
    end: str = "2022-12-31",
    base_params: dict = None,
) -> dict:
    """
    Parameter sensitivity sweep per Gate 1 spec.
    Returns dict of {param_label: sharpe} + variance stats per dimension.
    """
    if base_params is None:
        base_params = PARAMETERS.copy()

    sweep = {
        "uurr_lookback": [42, 63, 126],
        "uurr_threshold": [0.03, 0.05, 0.08],
        "neutral_eem_weight": [0.30, 0.40, 0.50],
        "vix_threshold": [25, 30, 35],
    }

    results = {}
    for param_name, values in sweep.items():
        param_results = {}
        for v in values:
            p = {**base_params, param_name: v}
            key = f"{param_name}={v}"
            try:
                r = run_backtest(start, end, p)
                param_results[key] = round(r["sharpe"], 4)
            except Exception as exc:
                param_results[key] = f"error: {exc}"

        results[param_name] = param_results

        sharpe_nums = [x for x in param_results.values() if isinstance(x, float) and not np.isnan(x)]
        if len(sharpe_nums) > 1:
            sr = max(sharpe_nums) - min(sharpe_nums)
            sm = np.mean(sharpe_nums)
            var_pct = sr / abs(sm) if abs(sm) > 0 else float("inf")
            results[f"{param_name}_variance_pct"] = round(var_pct, 4)
            results[f"{param_name}_gate1"] = (
                f"PASS: variance {var_pct:.1%} <= 30%"
                if var_pct <= 0.30
                else f"FAIL: variance {var_pct:.1%} > 30%"
            )

    return results


if __name__ == "__main__":
    print("H81v2 IS baseline (2008-01-01 to 2022-12-31)...")
    is_result = run_backtest("2008-01-01", "2022-12-31")
    if is_result["trade_count"] < 100:
        print("WARNING: IS trade count < 100 — investigate before proceeding.")

    print("\nH81v2 OOS (2023-01-01 to 2026-06-01)...")
    oos_result = run_backtest("2023-01-01", "2026-06-01")

    print("\nH81v2 2022 stress test (Jan-Dec 2022)...")
    stress_2022 = run_backtest("2022-01-01", "2022-12-31")
    print(f"[2022] Sharpe={stress_2022['sharpe']} MDD={stress_2022['max_drawdown']:.2%} "
          f"Regime={stress_2022['regime_counts']}")
