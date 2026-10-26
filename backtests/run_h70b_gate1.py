"""
H70b Gate 1 Full Backtest Runner — Multi-ETF Small-Cap RSI-4 Mean Reversion Basket
IS:  2005-01-01 to 2018-12-31 (14 years)
OOS: 2019-01-01 to 2024-12-31 (6 years)
Walk-forward: 4 non-overlapping IS folds (~3.5yr each)
Parameter sweep: 9 combos (rsi_entry × portfolio_notional_cap)
Parent: QUA-306 | Family: H70 Small-Cap Mean Reversion (iteration 2/2, final allowed)
Composite Score formula: hypothesis file H70b §Gate 1 Assessment
"""

import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import date

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "strategies"))
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

from h70b_multi_etf_rsi4_mean_reversion import (
    run_backtest, PARAMETERS, TICKERS,
    download_data_multi, compute_indicators_multi,
)
from oos_data_quality import validate_oos_data, OOSDataQualityError

TODAY = date.today().isoformat()
STRATEGY_NAME = "H70b_SPY_QQQ_Multi_ETF_RSI4_Basket"
OUT_DIR = REPO_ROOT / "backtests"

IS_START  = "2005-01-01"
IS_END    = "2018-12-31"
OOS_START = "2019-01-01"
OOS_END   = "2024-12-31"

# Walk-forward: 4 non-overlapping IS folds (~3.5yr each)
WF_FOLDS = [
    ("2005-01-01", "2008-06-30"),
    ("2008-07-01", "2011-12-31"),
    ("2012-01-01", "2015-06-30"),
    ("2015-07-01", "2018-12-31"),
]

# Sweep: 9 combos — entry threshold × portfolio notional cap
SWEEP_RSI_ENTRIES = [20, 25, 30]
SWEEP_PORT_CAPS   = [0.60, 0.80, 1.00]

TRADING_DAYS = 252


# ── Statistical Rigor Pipeline ─────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe": float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    np.random.seed(43)
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)

    sharpes, mdds = [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s: s + block_len] for s in starts])[:T]
        if len(sample) < 2:
            continue
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS))
        sharpes.append(s)
        mdds.append(mdd)

    return {
        "sharpe_ci_low":  float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":     float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":    float(np.percentile(mdds, 97.5)),
    }


def permutation_test_multi(
    ticker_prices: dict,
    ticker_entry_counts: dict,
    observed_sharpe: float,
    n_perms: int = 1000,
    hold_days: int = 5,
) -> dict:
    """
    Multi-instrument permutation test.
    For each permutation, randomly draw the same number of entry points per ticker,
    compute aggregate trade return Sharpe, and compare to observed.
    """
    np.random.seed(44)
    permuted_sharpes = []

    for _ in range(n_perms):
        all_rets = []
        for t, prices in ticker_prices.items():
            n = len(prices)
            n_entries = ticker_entry_counts.get(t, 0)
            if n_entries == 0 or n < hold_days + 1:
                continue
            max_start = max(1, n - hold_days)
            perm_idx = np.random.choice(max_start, size=n_entries, replace=False)
            for idx in perm_idx:
                exit_idx = min(idx + hold_days, n - 1)
                ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
                all_rets.append(ret)

        if len(all_rets) > 1:
            arr = np.array(all_rets)
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(TRADING_DAYS / hold_days)
        else:
            s = 0.0
        permuted_sharpes.append(s)

    perm_arr = np.array(permuted_sharpes)
    p_value = float(np.mean(perm_arr >= observed_sharpe))
    return {
        "permutation_pvalue": round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
        "permutation_perm_mean_sharpe": float(perm_arr.mean()),
        "permutation_perm_p95_sharpe": float(np.percentile(perm_arr, 95)),
    }


def walk_forward_variance(wf_sharpes: list) -> dict:
    arr = np.array(wf_sharpes)
    return {
        "wf_sharpe_std":  float(arr.std()),
        "wf_sharpe_min":  float(arr.min()),
        "wf_sharpe_max":  float(arr.max()),
        "wf_sharpe_mean": float(arr.mean()),
    }


def compute_dsr(is_sharpe: float, n_trials: int, T: int) -> float:
    """Deflated Sharpe Ratio (Harvey & Liu 2014 approximation)."""
    if T <= 0 or n_trials <= 1:
        return 0.0
    gamma = 0.5772
    ln_n = np.log(n_trials)
    expected_max = (
        np.sqrt(2 * ln_n)
        - (np.log(np.log(n_trials)) + np.log(4 * np.pi)) / (2 * np.sqrt(2 * ln_n))
        + gamma / np.sqrt(2 * ln_n)
    ) / np.sqrt(T)
    return round(float(is_sharpe - expected_max), 4)


def compute_profit_per_trade_bps(trades_df: pd.DataFrame) -> float:
    if trades_df.empty:
        return 0.0
    total_shares = trades_df["shares"].sum()
    if total_shares <= 0:
        return 0.0
    avg_entry = trades_df["entry_price"].mean()
    if avg_entry <= 0:
        return 0.0
    avg_pnl_per_share = trades_df["pnl"].sum() / total_shares
    return round(float(avg_pnl_per_share / avg_entry * 10000), 2)


def compute_cpr(trades_df: pd.DataFrame) -> float:
    """Cost-to-gross-PpT ratio."""
    if trades_df.empty:
        return 1.0
    total_shares = trades_df["shares"].sum()
    avg_entry = trades_df["entry_price"].mean()
    if total_shares <= 0 or avg_entry <= 0:
        return 1.0
    cost_bps = (trades_df["transaction_cost"].sum() / (total_shares * avg_entry)) * 10000
    gross_wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
    gross_ppt_bps = (gross_wins / (total_shares * avg_entry)) * 10000
    return round(float(cost_bps / (gross_ppt_bps + 1e-8)), 4)


def compute_composite_score(
    oos_sharpe: float,
    is_mdd_abs: float,
    ppt_bps: float,
    is_trade_count: int,
    n_folds: int = 4,
) -> float:
    """
    H70b composite score from hypothesis file §Gate 1 Assessment.
    CS = 0.40 × NetSharpe_norm + 0.30 × Stability_norm + 0.20 × PpT_norm + 0.10 × TradeAdequacy_norm
    """
    trade_per_fold = is_trade_count / n_folds
    net_sharpe_norm    = np.clip((oos_sharpe - (-0.5)) / 2.5, 0, 1)
    stability_norm     = np.clip(1 - is_mdd_abs / 0.20, 0, 1)
    ppt_norm           = np.clip(ppt_bps / 100.0, 0, 1)
    trade_adequacy_norm = min(1.0, trade_per_fold / 30.0)
    cs = 0.40 * net_sharpe_norm + 0.30 * stability_norm + 0.20 * ppt_norm + 0.10 * trade_adequacy_norm
    return round(float(cs), 4)


def regime_2022_split(oos_result: dict) -> dict:
    """Report OOS 2022 separately as rate-shock benchmark."""
    daily_df = oos_result.get("daily_df")
    if daily_df is None or daily_df.empty:
        return {}
    idx_2022 = daily_df.index.year == 2022
    df_2022 = daily_df.loc[idx_2022]
    if df_2022.empty:
        return {"2022_trade_count": 0, "2022_regime_active_pct": 0.0}

    trades = oos_result.get("trades")
    if trades is None or trades.empty:
        n_2022 = 0
    else:
        n_2022 = len(trades[pd.to_datetime(trades["entry_date"]).dt.year == 2022])

    regime_pct = oos_result.get("regime_pct_by_ticker", {})
    return {
        "2022_trade_count": n_2022,
        "2022_note": "All four small/mid-cap ETFs expected below 200-SMA by Feb 2022 (rate-shock gate)",
        "2022_n_position_mean": round(float(df_2022["n_positions"].mean()), 4) if "n_positions" in df_2022 else 0.0,
    }


def compute_market_impact_all(tickers: list, is_start: str, is_end: str) -> dict:
    """Market impact estimate per ticker at typical Elder 2% sizing on $25K account."""
    results = {}
    typical_shares = {"IWM": 33, "IJH": 70, "VB": 30, "IJR": 60}
    for t in tickers:
        try:
            hist = yf.download(t, start=is_start, end=is_end, progress=False, auto_adjust=True)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            adv = hist["Volume"].rolling(20).mean().iloc[-1]
            sigma = hist["Close"].pct_change().std()
            adv = float(adv) if not pd.isna(adv) and adv > 0 else 500_000
            sigma = float(sigma) if not pd.isna(sigma) and sigma > 0 else 0.01
            qty = typical_shares.get(t, 50)
            impact_bps = 0.1 * sigma * np.sqrt(qty / adv) * 10000
            results[t] = {
                "market_impact_bps": float(impact_bps),
                "order_qty": qty,
                "adv_20d": float(adv),
                "liquidity_constrained": bool(qty > 0.01 * adv),
            }
        except Exception as e:
            results[t] = {"market_impact_bps": 0.0, "error": str(e)}
    return results


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H70b Gate 1 Backtest — {TODAY}")
    print(f"Universe: IWM + IJH + VB + IJR (Multi-ETF RSI-4 Mean Reversion Basket)")
    print(f"Family: H70 Small-Cap Mean Reversion — iteration 2/2 (FINAL ALLOWED)")
    print("=" * 70)

    # ── [1/8] IS Backtest ─────────────────────────────────────────────────────
    print(f"\n[1/8] IS backtest ({IS_START} to {IS_END})...")
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        is_result = run_backtest(IS_START, IS_END)

    is_trades = is_result["trades"]
    is_equity = is_result["equity"]
    is_returns = is_result["returns"].values
    n_is = len(is_trades)
    is_years = 14.0

    print(f"  IS trades: {n_is} | Sharpe: {is_result['sharpe']} | MDD: {is_result['max_drawdown']:.2%}")
    print(f"  Per-instrument: {is_result['per_instrument_stats']}")
    print(f"  Concurrent: {is_result['concurrent_analysis']}")

    # ── [2/8] OOS Backtest ────────────────────────────────────────────────────
    print(f"\n[2/8] OOS backtest ({OOS_START} to {OOS_END})...")
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        oos_result = run_backtest(OOS_START, OOS_END)

    oos_trades = oos_result["trades"]
    oos_equity = oos_result["equity"]
    oos_returns = oos_result["returns"].values
    n_oos = len(oos_trades)

    print(f"  OOS trades: {n_oos} | Sharpe: {oos_result['sharpe']} | MDD: {oos_result['max_drawdown']:.2%}")

    # ── [3/8] OOS Data Quality ────────────────────────────────────────────────
    print("\n[3/8] OOS Data Quality Validation (IWM reference)...")
    oos_dfs = download_data_multi(["IWM"], OOS_START, OOS_END, PARAMETERS["sma_period"])
    iwm_oos_df = oos_dfs["IWM"].loc[
        (oos_dfs["IWM"].index >= pd.Timestamp(OOS_START)) &
        (oos_dfs["IWM"].index <= pd.Timestamp(OOS_END))
    ]
    oos_dq_metrics = {
        "sharpe": oos_result["sharpe"],
        "max_drawdown": oos_result["max_drawdown"],
        "win_rate": oos_result["win_rate"],
        "profit_factor": oos_result["profit_factor"],
        "total_trades": n_oos,
        "post_cost_sharpe": oos_result["sharpe"],
    }
    dq_report = validate_oos_data(iwm_oos_df, oos_dq_metrics, STRATEGY_NAME)
    print(f"  DQ recommendation: {dq_report['recommendation']}")
    if dq_report["recommendation"] == "BLOCK":
        print(f"  BLOCK reasons: {dq_report['block_reasons']}")
        raise OOSDataQualityError(dq_report)

    # ── [4/8] Statistical Rigor Pipeline ─────────────────────────────────────
    print("\n[4/8] Statistical rigor pipeline...")

    # Monte Carlo on IS trade PnLs
    if n_is >= 5:
        mc_results = monte_carlo_sharpe(is_trades["pnl"].values)
    else:
        mc_results = {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    print(f"  MC: p5={mc_results['mc_p5_sharpe']:.3f}, median={mc_results['mc_median_sharpe']:.3f}, p95={mc_results['mc_p95_sharpe']:.3f}")

    # Block bootstrap CI on IS portfolio returns
    if len(is_returns) > 10:
        bb_results = block_bootstrap_ci(is_returns)
    else:
        bb_results = {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0, "mdd_ci_low": 0.0, "mdd_ci_high": 0.0}
    print(f"  Bootstrap Sharpe 95% CI: [{bb_results['sharpe_ci_low']:.3f}, {bb_results['sharpe_ci_high']:.3f}]")

    # Market impact per ticker
    print("  Computing market impact per ticker...")
    mi_results = compute_market_impact_all(TICKERS, IS_START, IS_END)
    for t, mi in mi_results.items():
        print(f"    {t}: {mi.get('market_impact_bps', 0.0):.4f} bps (ADV={mi.get('adv_20d', 0):,.0f}, liq_constrained={mi.get('liquidity_constrained', False)})")

    # Permutation test on IS data (multi-instrument entry-based)
    print("  Running permutation test (1000 perms, multi-instrument)...")
    # Build IS price arrays and entry counts per ticker
    is_dfs_full = download_data_multi(TICKERS, IS_START, IS_END, PARAMETERS["sma_period"])
    is_inds_full = compute_indicators_multi(
        is_dfs_full, PARAMETERS["sma_period"], PARAMETERS["rsi_period"], PARAMETERS["high_exit_lookback"]
    )
    ticker_price_arrays = {}
    ticker_entry_counts = {}
    for t in TICKERS:
        df_t = is_dfs_full[t]
        df_t_trim = df_t.loc[(df_t.index >= pd.Timestamp(IS_START)) & (df_t.index <= pd.Timestamp(IS_END))]
        ticker_price_arrays[t] = df_t_trim["Close"].values
        # Entry signal: RSI < 25 AND regime active (from IS trade log)
        t_trades = is_trades[is_trades["ticker"] == t] if not is_trades.empty and "ticker" in is_trades.columns else pd.DataFrame()
        ticker_entry_counts[t] = len(t_trades)

    perm_results = permutation_test_multi(
        ticker_price_arrays, ticker_entry_counts, is_result["sharpe"], n_perms=1000, hold_days=5
    )
    print(f"  Permutation p-value: {perm_results['permutation_pvalue']:.4f} ({'PASS' if perm_results['permutation_test_pass'] else 'FAIL'})")

    # ── [5/8] Walk-Forward Analysis (4 IS folds) ──────────────────────────────
    print("\n[5/8] Walk-forward analysis (4 IS folds)...")
    wf_fold_results = []
    for fold_i, (fold_start, fold_end) in enumerate(WF_FOLDS):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            fold_r = run_backtest(fold_start, fold_end)
        n_fold = len(fold_r["trades"])
        # Per-ticker trade counts in this fold
        per_ticker_fold = {}
        if not fold_r["trades"].empty and "ticker" in fold_r["trades"].columns:
            per_ticker_fold = fold_r["trades"]["ticker"].value_counts().to_dict()
        wf_fold_results.append({
            "fold": fold_i + 1,
            "start": fold_start,
            "end": fold_end,
            "sharpe": fold_r["sharpe"],
            "max_drawdown": fold_r["max_drawdown"],
            "win_rate": fold_r["win_rate"],
            "trade_count": n_fold,
            "trades_per_year": fold_r["trades_per_year"],
            "per_ticker_trades": per_ticker_fold,
        })
        pf1_ok = "OK" if n_fold > 30 else f"WARN ({n_fold}<=30)"
        print(f"  Fold {fold_i+1} ({fold_start}–{fold_end}): Sharpe={fold_r['sharpe']:.3f}, MDD={fold_r['max_drawdown']:.2%}, trades={n_fold} [{pf1_ok}]")
        print(f"    Per-ticker: {per_ticker_fold}")

    wf_sharpes = [f["sharpe"] for f in wf_fold_results]
    wf_var = walk_forward_variance(wf_sharpes)
    wf_passed = sum(1 for s in wf_sharpes if s > 0.0)
    print(f"  WF passed (Sharpe>0): {wf_passed}/4 | std={wf_var['wf_sharpe_std']:.3f} | min={wf_var['wf_sharpe_min']:.3f}")

    # Gate 7: per-fold MDD > 30% → auto-reject
    gate7_reject = any(abs(f["max_drawdown"]) > 0.30 for f in wf_fold_results)
    print(f"  Gate 7 (any fold MDD>30%): {'AUTO-REJECT' if gate7_reject else 'PASS'}")

    # WF trades/fold check: all folds must have > 30 trades
    gate_wf_trades = all(f["trade_count"] > 30 for f in wf_fold_results)
    print(f"  WF trades/fold >30 (all folds): {'PASS' if gate_wf_trades else 'FAIL'}")

    # ── [6/8] 2022 Regime Split ───────────────────────────────────────────────
    print("\n[6/8] 2022 regime split...")
    r2022 = regime_2022_split(oos_result)
    print(f"  2022 trades: {r2022.get('2022_trade_count', 0)} | {r2022.get('2022_note', '')}")

    # ── [7/8] Parameter Sweep (9 combos) ─────────────────────────────────────
    print("\n[7/8] Parameter sweep (9 combos: 3 RSI entry × 3 portfolio caps)...")
    sweep_rows = []
    base_params = PARAMETERS.copy()
    for rsi_entry in SWEEP_RSI_ENTRIES:
        for port_cap in SWEEP_PORT_CAPS:
            p = base_params.copy()
            p["rsi_entry_threshold"] = rsi_entry
            p["portfolio_notional_cap"] = port_cap
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                r = run_backtest(IS_START, IS_END, params=p)
            n_sweep = len(r["trades"])
            sweep_rows.append({
                "rsi_entry": rsi_entry,
                "portfolio_notional_cap": port_cap,
                "sharpe": r["sharpe"],
                "max_drawdown": r["max_drawdown"],
                "win_rate": r["win_rate"],
                "trade_count": n_sweep,
                "total_return": r["total_return"],
                "profit_factor": r["profit_factor"],
            })
            print(f"  RSI<{rsi_entry} | cap={port_cap:.0%}: Sharpe={r['sharpe']:.3f}, MDD={r['max_drawdown']:.2%}, trades={n_sweep}")

    sweep_df = pd.DataFrame(sweep_rows)
    base_sharpe = is_result["sharpe"]
    sweep_df["sharpe_delta_pct"] = ((sweep_df["sharpe"] - base_sharpe) / (abs(base_sharpe) + 1e-8) * 100).round(2)
    max_sensitivity_delta = float(sweep_df["sharpe_delta_pct"].abs().max())
    sensitivity_pass = max_sensitivity_delta < 30.0
    print(f"  Max Sharpe sensitivity: {max_sensitivity_delta:.1f}% ({'PASS' if sensitivity_pass else 'FAIL'} <30%)")

    # ── [8/8] Profit Metrics + Gate 1 Verdict ────────────────────────────────
    print("\n[8/8] Gate 1 verdict...")

    is_ppt_bps  = compute_profit_per_trade_bps(is_trades)
    oos_ppt_bps = compute_profit_per_trade_bps(oos_trades)
    is_cpr      = compute_cpr(is_trades)
    oos_cpr     = compute_cpr(oos_trades)

    # DSR
    n_trials = len(sweep_rows) + 4
    T_is = len(is_equity)
    dsr = compute_dsr(is_result["sharpe"], n_trials, T_is)

    # Gate checks
    oos_sharpe = oos_result["sharpe"]
    is_mdd_abs = abs(is_result["max_drawdown"])
    oos_mdd_abs = abs(oos_result["max_drawdown"])

    gate_oos_sharpe = oos_sharpe > 0.70
    gate_oos_ppt    = oos_ppt_bps > 15.0
    gate_is_mdd_cs  = is_mdd_abs < 0.20
    gate_is_mdd_g7  = is_mdd_abs < 0.30
    gate_cpr        = is_cpr < 0.25
    gate_perm       = perm_results["permutation_test_pass"]

    # H70b composite score (hypothesis formula)
    composite_score = compute_composite_score(oos_sharpe, is_mdd_abs, oos_ppt_bps, n_is)
    gate1_pass = (
        composite_score >= 0.60
        and gate_perm
        and not gate7_reject
        and gate_wf_trades
    )
    verdict_label = "PASS" if gate1_pass else "FAIL"

    print(f"\n{'='*70}")
    print("GATE 1 SUMMARY — H70b Multi-ETF RSI-4 Basket:")
    print(f"  IS Sharpe:       {is_result['sharpe']:.4f}")
    print(f"  OOS Sharpe:      {oos_sharpe:.4f}  {'PASS' if gate_oos_sharpe else 'FAIL'} (>0.70)")
    print(f"  IS MDD (CS):     {is_mdd_abs:.2%}     {'PASS' if gate_is_mdd_cs else 'FAIL'} (<20%)")
    print(f"  IS MDD (Gate 7): {is_mdd_abs:.2%}     {'PASS' if gate_is_mdd_g7 else 'FAIL'} (<30%)")
    print(f"  IS PpT:          {is_ppt_bps:.1f} bps")
    print(f"  OOS PpT:         {oos_ppt_bps:.1f} bps  {'PASS' if gate_oos_ppt else 'FAIL'} (>15 bps)")
    print(f"  IS CPR:          {is_cpr:.3f}     {'PASS' if gate_cpr else 'FAIL'} (<0.25)")
    print(f"  WF trades>30:    {gate_wf_trades} (all folds)")
    print(f"  Perm test:       p={perm_results['permutation_pvalue']:.4f}  {'PASS' if gate_perm else 'FAIL'} (<0.05)")
    print(f"  Gate7 reject:    {gate7_reject}")
    print(f"  DSR:             {dsr:.4f}")
    print(f"  Sensitivity:     {max_sensitivity_delta:.1f}%  {'PASS' if sensitivity_pass else 'FAIL'}")
    print(f"  MC p5 Sharpe:    {mc_results['mc_p5_sharpe']:.3f}  {'OK' if mc_results['mc_p5_sharpe'] >= 0.5 else 'WEAK'}")
    print(f"  WF min Sharpe:   {wf_var['wf_sharpe_min']:.3f}  {'OK' if wf_var['wf_sharpe_min'] >= 0 else 'FLAG'}")
    print(f"  Composite CS:    {composite_score:.4f}  (need >=0.60)")
    print(f"\n  GATE 1 VERDICT: {verdict_label}")
    print(f"{'='*70}")

    # ── Build metrics JSON ────────────────────────────────────────────────────
    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        "hypothesis": "H70b",
        "universe": TICKERS,
        "family": "H70 Small-Cap Mean Reversion — iteration 2/2 (final allowed)",
        # IS
        "is_sharpe": is_result["sharpe"],
        "is_max_drawdown": is_result["max_drawdown"],
        "is_total_return": is_result["total_return"],
        "is_win_rate": is_result["win_rate"],
        "is_profit_factor": is_result["profit_factor"],
        "is_trade_count": n_is,
        "is_trades_per_year": is_result["trades_per_year"],
        "is_ppt_bps": is_ppt_bps,
        "is_cpr": is_cpr,
        "is_exit_breakdown": is_result["exit_breakdown"],
        "is_gap_attribution": is_result.get("gap_attribution", {}),
        "is_per_instrument_stats": is_result["per_instrument_stats"],
        "is_concurrent_analysis": is_result["concurrent_analysis"],
        "is_regime_pct_by_ticker": is_result["regime_pct_by_ticker"],
        # OOS
        "oos_sharpe": oos_result["sharpe"],
        "oos_max_drawdown": oos_result["max_drawdown"],
        "oos_total_return": oos_result["total_return"],
        "oos_win_rate": oos_result["win_rate"],
        "oos_profit_factor": oos_result["profit_factor"],
        "oos_trade_count": n_oos,
        "oos_trades_per_year": oos_result["trades_per_year"],
        "oos_ppt_bps": oos_ppt_bps,
        "oos_cpr": oos_cpr,
        "oos_exit_breakdown": oos_result["exit_breakdown"],
        "oos_gap_attribution": oos_result.get("gap_attribution", {}),
        "oos_per_instrument_stats": oos_result["per_instrument_stats"],
        "oos_concurrent_analysis": oos_result["concurrent_analysis"],
        "oos_regime_pct_by_ticker": oos_result["regime_pct_by_ticker"],
        # Post-cost
        "post_cost_sharpe": oos_result["sharpe"],
        # DSR
        "dsr": dsr,
        "n_trials": n_trials,
        # Walk-forward
        "wf_windows": wf_fold_results,
        "wf_windows_passed": wf_passed,
        "wf_consistency_score": round(wf_passed / 4, 4),
        **wf_var,
        # Statistical rigor
        **mc_results,
        **bb_results,
        **perm_results,
        # Market impact
        "market_impact_by_ticker": mi_results,
        # Sensitivity
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_delta_pct": max_sensitivity_delta,
        # Gate outcomes
        "gate_oos_sharpe": gate_oos_sharpe,
        "gate_oos_ppt": gate_oos_ppt,
        "gate_is_mdd_cs": gate_is_mdd_cs,
        "gate_is_mdd_g7": gate_is_mdd_g7,
        "gate_wf_trades": gate_wf_trades,
        "gate_cpr": gate_cpr,
        "gate7_auto_reject": gate7_reject,
        "composite_score": composite_score,
        "gate1_pass": gate1_pass,
        # 2022 regime
        "regime_2022": r2022,
        # OOS data quality
        "oos_data_quality": dq_report,
        # Model
        "look_ahead_bias_flag": False,
        "slippage_model": "mixed: IWM 0.005% ultra-liquid (ED-SLIP-001); IJH/VB/IJR 0.05% standard",
    }

    # ── Save outputs ──────────────────────────────────────────────────────────
    base = f"H70b_Multi_ETF_RSI4_Basket_{TODAY}"

    metrics_path = OUT_DIR / f"{base}.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"\nSaved metrics: {metrics_path}")

    all_trades = pd.concat([
        is_trades.assign(period="IS"),
        oos_trades.assign(period="OOS"),
    ], ignore_index=True)
    trades_path = OUT_DIR / f"{base}_trades.csv"
    all_trades.to_csv(trades_path, index=False)
    print(f"Saved trades: {trades_path}")

    sweep_path = OUT_DIR / f"{base}_sweep.csv"
    sweep_df.to_csv(sweep_path, index=False)
    print(f"Saved sweep: {sweep_path}")

    # Verdict text
    verdict_lines = [
        f"H70b Multi-ETF Small-Cap RSI-4 Mean Reversion Basket — Gate 1 Verdict",
        f"Date: {TODAY}",
        f"Universe: IWM + IJH + VB + IJR",
        f"Family: H70 Small-Cap Mean Reversion — iteration 2/2 (FINAL ALLOWED)",
        f"",
        f"OVERALL VERDICT: {verdict_label}",
        f"Composite Score: {composite_score:.4f} (need >= 0.60)",
        f"",
        f"PRIMARY GATE CHECKS:",
        f"  OOS Sharpe     : {oos_sharpe:.4f}  {'PASS' if gate_oos_sharpe else 'FAIL'} (> 0.70)",
        f"  OOS PpT        : {oos_ppt_bps:.2f} bps  {'PASS' if gate_oos_ppt else 'FAIL'} (> 15 bps)",
        f"  IS MDD (CS)    : {is_mdd_abs:.2%}  {'PASS' if gate_is_mdd_cs else 'FAIL'} (< 20%)",
        f"  IS MDD (Gate 7): {is_mdd_abs:.2%}  {'PASS' if gate_is_mdd_g7 else 'FAIL'} (< 30%)",
        f"  WF trades/fold : {'PASS' if gate_wf_trades else 'FAIL'} (all folds > 30)",
        f"  CPR            : {is_cpr:.4f}  {'PASS' if gate_cpr else 'FAIL'} (< 0.25)",
        f"",
        f"STATISTICAL TESTS:",
        f"  Permutation p  : {perm_results['permutation_pvalue']:.4f}  {'PASS' if gate_perm else 'FAIL'} (< 0.05)",
        f"  MC p5 Sharpe   : {mc_results['mc_p5_sharpe']:.4f}  {'OK' if mc_results['mc_p5_sharpe'] >= 0.5 else 'WEAK (< 0.5)'}",
        f"  Bootstrap CI   : [{bb_results['sharpe_ci_low']:.4f}, {bb_results['sharpe_ci_high']:.4f}]",
        f"  DSR            : {dsr:.4f}",
        f"",
        f"WALK-FORWARD (4 IS folds):",
    ]
    for fold in wf_fold_results:
        verdict_lines.append(
            f"  Fold {fold['fold']} ({fold['start']}–{fold['end']}): "
            f"Sharpe={fold['sharpe']:.4f}, MDD={fold['max_drawdown']:.2%}, trades={fold['trade_count']}"
            f"  per-ticker={fold['per_ticker_trades']}"
        )
    verdict_lines += [
        f"  WF passed: {wf_passed}/4",
        f"  WF Sharpe std: {wf_var['wf_sharpe_std']:.4f}",
        f"  WF Sharpe min: {wf_var['wf_sharpe_min']:.4f}  {'FLAG' if wf_var['wf_sharpe_min'] < 0 else 'OK'}",
        f"  Gate 7 (any fold MDD>30%): {'AUTO-REJECT' if gate7_reject else 'PASS'}",
        f"",
        f"PER-INSTRUMENT DISAGGREGATION (IS):",
    ]
    for t, st in is_result["per_instrument_stats"].items():
        verdict_lines.append(
            f"  {t}: trades={st['trade_count']}, PpT={st['ppt_bps']:.1f} bps, "
            f"WR={st['win_rate']:.1%}, Sharpe~={st['sharpe_proxy']:.3f}"
        )
    verdict_lines += [
        f"",
        f"IS SUMMARY ({IS_START} to {IS_END}):",
        f"  Sharpe: {is_result['sharpe']:.4f}",
        f"  MDD: {is_mdd_abs:.2%}",
        f"  Win rate: {is_result['win_rate']:.2%}",
        f"  Profit factor: {is_result['profit_factor']:.2f}",
        f"  Trade count: {n_is} ({is_result['trades_per_year']}/yr)",
        f"  PpT: {is_ppt_bps:.2f} bps",
        f"  Exit breakdown: {is_result['exit_breakdown']}",
        f"  Concurrent: {is_result['concurrent_analysis']}",
        f"",
        f"OOS SUMMARY ({OOS_START} to {OOS_END}):",
        f"  Sharpe: {oos_sharpe:.4f}",
        f"  MDD: {oos_mdd_abs:.2%}",
        f"  Win rate: {oos_result['win_rate']:.2%}",
        f"  Profit factor: {oos_result['profit_factor']:.2f}",
        f"  Trade count: {n_oos} ({oos_result['trades_per_year']}/yr)",
        f"  PpT: {oos_ppt_bps:.2f} bps",
        f"  2022 regime: {r2022}",
        f"",
        f"PARAMETER SWEEP (9 combinations):",
        f"  Max Sharpe sensitivity: {max_sensitivity_delta:.1f}% — {'PASS' if sensitivity_pass else 'FAIL'} (<30%)",
        f"  See: {base}_sweep.csv",
        f"",
        f"SLIPPAGE MODEL:",
        f"  IWM: 0.005% one-way (ultra-liquid, ED-SLIP-001)",
        f"  IJH, VB, IJR: 0.05% one-way (canonical standard)",
        f"  Commission: $0.005/share each side (all instruments)",
        f"",
        f"GAP ATTRIBUTION (Hard Gate 8):",
        f"  IS overnight: {is_result.get('gap_attribution', {}).get('overnight_gap_trades', 'N/A')} trades ({is_result.get('gap_attribution', {}).get('overnight_gap_pct', 0):.1%})",
        f"  IS weekend:   {is_result.get('gap_attribution', {}).get('weekend_gap_trades', 'N/A')} trades ({is_result.get('gap_attribution', {}).get('weekend_gap_pct', 0):.1%})",
        f"",
        f"OOS DATA QUALITY: {dq_report['recommendation']}",
    ]

    verdict_text = "\n".join(verdict_lines)
    verdict_path = OUT_DIR / f"{base}_verdict.txt"
    verdict_path.write_text(verdict_text)
    print(f"Saved verdict: {verdict_path}")

    # HTML report
    wf_rows_html = "".join(
        f"<tr><td>{f['fold']}</td><td>{f['start']}–{f['end']}</td>"
        f"<td>{f['sharpe']:.4f}</td><td>{f['max_drawdown']:.2%}</td>"
        f"<td>{f['win_rate']:.2%}</td><td>{f['trade_count']}</td>"
        f"<td style='font-size:0.85em'>{f['per_ticker_trades']}</td></tr>"
        for f in wf_fold_results
    )
    instr_rows_html = "".join(
        f"<tr><td>{t}</td><td>{st['trade_count']}</td><td>{st['ppt_bps']:.1f}</td>"
        f"<td>{st['win_rate']:.1%}</td><td>{st['sharpe_proxy']:.3f}</td><td>${st['total_pnl']:,.2f}</td></tr>"
        for t, st in is_result["per_instrument_stats"].items()
    )
    gate_rows_html = "".join(
        f"<tr style='background:{'#d4edda' if p else '#f8d7da'}'>"
        f"<td>{g}</td><td>{v}</td><td>{t}</td><td>{'✓ PASS' if p else '✗ FAIL'}</td></tr>"
        for g, v, t, p in [
            ("OOS Sharpe",      f"{oos_sharpe:.4f}",                    "> 0.70",     gate_oos_sharpe),
            ("OOS PpT",         f"{oos_ppt_bps:.2f} bps",              "> 15 bps",   gate_oos_ppt),
            ("IS MDD (CS)",     f"{is_mdd_abs:.2%}",                   "< 20%",      gate_is_mdd_cs),
            ("IS MDD (Gate 7)", f"{is_mdd_abs:.2%}",                   "< 30%",      gate_is_mdd_g7),
            ("WF trades/fold",  str(gate_wf_trades),                    "all > 30",   gate_wf_trades),
            ("CPR",             f"{is_cpr:.4f}",                       "< 0.25",     gate_cpr),
            ("Perm test",       f"p={perm_results['permutation_pvalue']:.4f}", "< 0.05", gate_perm),
            ("Gate7 no-reject", str(not gate7_reject),                 "no fold>30%", not gate7_reject),
            ("Sensitivity",     f"Δ{max_sensitivity_delta:.1f}%",      "< 30%",      sensitivity_pass),
        ]
    )
    sweep_html = sweep_df.to_html(index=False, float_format=lambda x: f"{x:.4f}", border=1)
    verdict_color = "#d4edda" if gate1_pass else "#f8d7da"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>H70b Gate 1 Report — {TODAY}</title>
<style>
body {{ font-family: monospace; max-width: 1200px; margin: 0 auto; padding: 20px; }}
h1 {{ background: #343a40; color: white; padding: 15px; border-radius: 4px; }}
h2 {{ border-bottom: 2px solid #343a40; padding-bottom: 5px; margin-top: 30px; }}
.verdict {{ font-size: 2em; font-weight: bold; padding: 15px; border-radius: 4px; background: {verdict_color}; text-align: center; margin: 20px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th {{ background: #343a40; color: white; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border: 1px solid #dee2e6; }}
.section {{ margin: 20px 0; padding: 15px; border: 1px solid #dee2e6; border-radius: 4px; }}
.pass {{ color: #155724; font-weight: bold; }}
.fail {{ color: #721c24; font-weight: bold; }}
</style>
</head>
<body>
<h1>H70b Multi-ETF RSI-4 Basket — Gate 1 Report</h1>
<p><strong>Date:</strong> {TODAY} | <strong>Universe:</strong> IWM + IJH + VB + IJR | <strong>Family:</strong> H70 iteration 2/2 (FINAL ALLOWED)</p>
<p><strong>Slippage:</strong> IWM 0.005% (ED-SLIP-001 ultra-liquid) | IJH/VB/IJR 0.05% (canonical standard)</p>

<div class="verdict">GATE 1: {verdict_label} — Composite Score: {composite_score:.4f} (≥ 0.60)</div>

<h2>Gate 1 Checklist</h2>
<table><tr><th>Gate</th><th>Value</th><th>Threshold</th><th>Result</th></tr>{gate_rows_html}</table>

<h2>IS/OOS Summary</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>IS (2005–2018)</th><th>OOS (2019–2024)</th></tr>
<tr><td>Sharpe</td><td>{is_result['sharpe']:.4f}</td><td>{oos_sharpe:.4f}</td></tr>
<tr><td>Max Drawdown</td><td>{is_mdd_abs:.2%}</td><td>{oos_mdd_abs:.2%}</td></tr>
<tr><td>Win Rate</td><td>{is_result['win_rate']:.2%}</td><td>{oos_result['win_rate']:.2%}</td></tr>
<tr><td>Profit Factor</td><td>{is_result['profit_factor']:.2f}</td><td>{oos_result['profit_factor']:.2f}</td></tr>
<tr><td>Trade Count</td><td>{n_is}</td><td>{n_oos}</td></tr>
<tr><td>Trades/Year</td><td>{is_result['trades_per_year']}</td><td>{oos_result['trades_per_year']}</td></tr>
<tr><td>PpT (bps)</td><td>{is_ppt_bps:.2f}</td><td>{oos_ppt_bps:.2f}</td></tr>
<tr><td>CPR</td><td>{is_cpr:.4f}</td><td>{oos_cpr:.4f}</td></tr>
</table>
</div>

<h2>Per-Instrument Disaggregation (IS)</h2>
<table>
<tr><th>Ticker</th><th>Trades</th><th>PpT (bps)</th><th>Win Rate</th><th>Sharpe~</th><th>Total PnL</th></tr>
{instr_rows_html}
</table>

<h2>Walk-Forward Analysis (4 IS Folds)</h2>
<table>
<tr><th>Fold</th><th>Period</th><th>Sharpe</th><th>MDD</th><th>Win Rate</th><th>Trades</th><th>Per-Ticker</th></tr>
{wf_rows_html}
</table>
<p>WF passed: {wf_passed}/4 | Sharpe std: {wf_var['wf_sharpe_std']:.4f} | Min: {wf_var['wf_sharpe_min']:.4f} | Gate 7: {'AUTO-REJECT' if gate7_reject else 'PASS'}</p>

<h2>Concurrent Position Analysis</h2>
<div class="section">
<p>{is_result['concurrent_analysis']}</p>
</div>

<h2>Statistical Tests</h2>
<div class="section">
<p><strong>Monte Carlo (1000 resamples):</strong> p5={mc_results['mc_p5_sharpe']:.4f}, median={mc_results['mc_median_sharpe']:.4f}, p95={mc_results['mc_p95_sharpe']:.4f}</p>
<p><strong>Block Bootstrap CI (95%):</strong> Sharpe [{bb_results['sharpe_ci_low']:.4f}, {bb_results['sharpe_ci_high']:.4f}]</p>
<p><strong>Permutation test (multi-instrument, 1000 perms):</strong> p={perm_results['permutation_pvalue']:.4f} — {"<span class='pass'>PASS</span>" if gate_perm else "<span class='fail'>FAIL</span>"}</p>
<p><strong>DSR:</strong> {dsr:.4f} | <strong>Sensitivity:</strong> Δ{max_sensitivity_delta:.1f}%</p>
</div>

<h2>2022 Rate-Shock Regime Split</h2>
<div class="section">
<p>2022 trades: {r2022.get('2022_trade_count', 0)} | {r2022.get('2022_note', '')}</p>
</div>

<h2>Gap Attribution (Hard Gate 8)</h2>
<div class="section">
<table>
<tr><th>Period</th><th>Overnight Gap Trades</th><th>%</th><th>Weekend Gap Trades</th><th>%</th></tr>
<tr><td>IS</td>
<td>{is_result.get('gap_attribution', {}).get('overnight_gap_trades','N/A')}</td>
<td>{is_result.get('gap_attribution', {}).get('overnight_gap_pct',0):.1%}</td>
<td>{is_result.get('gap_attribution', {}).get('weekend_gap_trades','N/A')}</td>
<td>{is_result.get('gap_attribution', {}).get('weekend_gap_pct',0):.1%}</td></tr>
<tr><td>OOS</td>
<td>{oos_result.get('gap_attribution', {}).get('overnight_gap_trades','N/A')}</td>
<td>{oos_result.get('gap_attribution', {}).get('overnight_gap_pct',0):.1%}</td>
<td>{oos_result.get('gap_attribution', {}).get('weekend_gap_trades','N/A')}</td>
<td>{oos_result.get('gap_attribution', {}).get('weekend_gap_pct',0):.1%}</td></tr>
</table>
</div>

<h2>Parameter Sweep (9 Combinations)</h2>
{sweep_html}

<h2>Market Impact by Ticker</h2>
<div class="section">
{"".join(f"<p>{t}: {mi.get('market_impact_bps',0.0):.4f} bps | ADV={mi.get('adv_20d',0):,.0f} shares | liq_constrained={mi.get('liquidity_constrained',False)}</p>" for t, mi in mi_results.items())}
</div>

<hr>
<p><em>Generated by Engineering Director (QUA-306) | H70b Gate 1 | {TODAY}</em></p>
</body>
</html>"""

    html_path = OUT_DIR / f"{base}_report.html"
    html_path.write_text(html)
    print(f"Saved HTML: {html_path}")

    print(f"\nAll outputs → {OUT_DIR}/")
    print(f"  Metrics: {base}.json")
    print(f"  Report:  {base}_report.html")
    print(f"  Sweep:   {base}_sweep.csv")
    print(f"  Trades:  {base}_trades.csv")
    print(f"  Verdict: {base}_verdict.txt")

    return metrics, gate1_pass, verdict_label


if __name__ == "__main__":
    metrics, gate1_pass, verdict_label = main()
    sys.exit(0 if gate1_pass else 1)
