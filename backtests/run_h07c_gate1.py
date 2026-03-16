"""
H07c Gate 1 Backtest Runner — Multi-Asset TSMOM Yield Curve Regime Filter
Executes IS/OOS backtests, walk-forward, statistical rigor pipeline,
regime-slice analysis, and parameter sensitivity scan.

IS period:  2018-01-01 to 2021-12-31
OOS period: 2022-01-01 to 2023-12-31

Regime slices (QUA-169 spec):
  Pre-COVID:      2018-01-01 to 2019-12-31
  Stimulus:       2020-01-01 to 2021-12-31
  Rate Shock:     2022-01-01 to 2022-12-31
  Normalization:  2023-01-01 to 2023-12-31
"""

import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
from datetime import date

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.h07c_multi_asset_tsmom_yield_curve import (
    run_backtest,
    scan_parameters,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

# ── Constants ──────────────────────────────────────────────────────────────────

IS_START  = "2018-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2023-12-31"
TODAY     = str(date.today())
STRATEGY_NAME = "H07c_MultiAsset_TSMOM_YieldCurve"

REGIME_SLICES = {
    "pre_covid_2018_2019":   ("2018-01-01", "2019-12-31"),
    "stimulus_2020_2021":    ("2020-01-01", "2021-12-31"),
    "rate_shock_2022":       ("2022-01-01", "2022-12-31"),
    "normalization_2023":    ("2023-01-01", "2023-12-31"),
}
STRESS_REGIMES = {"rate_shock_2022"}


# ── Statistical Functions ──────────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe":    float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)

    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)

    return {
        "sharpe_ci_low":    float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high":   float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":       float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":      float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low":  float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def permutation_test_alpha(
    returns: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 500,
) -> dict:
    if len(returns) < 10:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    permuted_sharpes = []
    for _ in range(n_perms):
        perm = np.random.permutation(returns)
        s = perm.mean() / (perm.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": p_value <= 0.05,
    }


def compute_dsr(returns_series: np.ndarray, n_trials: int) -> float:
    from scipy.stats import norm
    T = len(returns_series)
    if T < 2:
        return 0.0
    sr_obs = returns_series.mean() / (returns_series.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    sr_star = (
        (1 - np.euler_gamma) * norm.ppf(1 - 1.0 / n_trials)
        + np.euler_gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    skew = float(pd.Series(returns_series).skew())
    kurt = float(pd.Series(returns_series).kurtosis())
    var_sr = (1 + (0.5 * sr_obs**2) - (skew * sr_obs) + ((kurt / 4) * sr_obs**2)) / (T - 1)
    dsr = norm.cdf((sr_obs - sr_star) / (np.sqrt(max(var_sr, 1e-12)) + 1e-8))
    return float(dsr)


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array([s for s in wf_oos_sharpes if s is not None and not np.isnan(s)])
    if len(arr) == 0:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


# ── Regime-Slice Analysis ──────────────────────────────────────────────────────

def compute_regime_slices(params: dict) -> dict:
    """
    Run backtest for each regime slice and compute per-slice Sharpe.
    Criteria: IS Sharpe >= 0.8 in >= 2 regimes, at least 1 stress regime.
    """
    regime_results = {}

    for regime_name, (r_start, r_end) in REGIME_SLICES.items():
        try:
            r = run_backtest(params=params, start=r_start, end=r_end)
            passes = r["sharpe"] >= 0.8
            regime_results[regime_name] = {
                "sharpe": round(r["sharpe"], 4),
                "mdd": round(r["max_drawdown"], 4),
                "total_return": round(r["total_return"], 4),
                "trade_count": r["trade_count"],
                "yc_blocked": r.get("filter_stats", {}).get("yc_blocked_count", 0),
                "status": "assessable",
                "passes": passes,
            }
        except Exception as exc:
            regime_results[regime_name] = {
                "status": "error",
                "error": str(exc),
                "passes": False,
            }

    assessable = {k: v for k, v in regime_results.items() if v.get("status") == "assessable"}
    passing = {k: v for k, v in assessable.items() if v.get("passes")}
    stress_passing = [k for k in passing if k in STRESS_REGIMES]
    n_passing = len(passing)
    has_stress_pass = len(stress_passing) > 0

    regime_slice_pass = (n_passing >= 2) and has_stress_pass

    return {
        "regimes": regime_results,
        "n_assessable": len(assessable),
        "n_passing": n_passing,
        "stress_regime_passing": stress_passing,
        "has_stress_pass": has_stress_pass,
        "regime_slice_pass": regime_slice_pass,
        "note": "Pass: IS Sharpe >= 0.8 in >= 2 regimes, at least 1 stress (rate_shock_2022). QUA-169.",
    }


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(
    params: dict,
    n_windows: int = 4,
    train_months: int = 36,
    test_months: int = 6,
) -> dict:
    """
    Walk-forward: 4 windows, 36m IS / 6m OOS.
    Start: 2016-01-01 (provides 2-year buffer before 2018 IS start for yield curve data).
    """
    wf_results = []
    base_start = pd.Timestamp("2016-01-01")

    for i in range(n_windows):
        offset_months = i * test_months
        is_start = (base_start + pd.DateOffset(months=offset_months)).strftime("%Y-%m-%d")
        is_end = (
            base_start + pd.DateOffset(months=offset_months + train_months - 1, day=31)
        ).strftime("%Y-%m-%d")
        oos_start = (
            base_start + pd.DateOffset(months=offset_months + train_months)
        ).strftime("%Y-%m-%d")
        oos_end = (
            base_start + pd.DateOffset(months=offset_months + train_months + test_months - 1, day=31)
        ).strftime("%Y-%m-%d")

        try:
            r_is = run_backtest(params=params, start=is_start, end=is_end)
            r_oos = run_backtest(params=params, start=oos_start, end=oos_end)
            wf_results.append({
                "window":       i + 1,
                "is_start":     is_start,
                "is_end":       is_end,
                "oos_start":    oos_start,
                "oos_end":      oos_end,
                "is_sharpe":    round(r_is["sharpe"], 4),
                "oos_sharpe":   round(r_oos["sharpe"], 4),
                "is_mdd":       round(r_is["max_drawdown"], 4),
                "oos_mdd":      round(r_oos["max_drawdown"], 4),
                "oos_trades":   r_oos["trade_count"],
                "pass":         r_oos["sharpe"] >= 0.7,
            })
        except Exception as exc:
            wf_results.append({
                "window":    i + 1,
                "is_start":  is_start,
                "is_end":    is_end,
                "oos_start": oos_start,
                "oos_end":   oos_end,
                "error":     str(exc),
                "pass":      False,
            })

    windows_passed = sum(1 for w in wf_results if w.get("pass", False))
    oos_sharpes = [w["oos_sharpe"] for w in wf_results if "oos_sharpe" in w]
    is_sharpes = [w["is_sharpe"] for w in wf_results if "is_sharpe" in w]

    consistency_ratios = []
    for w in wf_results:
        if "is_sharpe" in w and "oos_sharpe" in w and abs(w["is_sharpe"]) > 0.01:
            consistency_ratios.append(w["oos_sharpe"] / w["is_sharpe"])
    wf_consistency_score = float(np.mean(consistency_ratios)) if consistency_ratios else 0.0

    return {
        "windows":              wf_results,
        "windows_passed":       windows_passed,
        "oos_sharpes":          oos_sharpes,
        "is_sharpes":           is_sharpes,
        "wf_consistency_score": wf_consistency_score,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H07c Gate 1 Backtest — {TODAY}")
    print("Strategy: Multi-Asset TSMOM Yield Curve Regime Filter + Dynamic Lookback")
    print(f"IS:  {IS_START} to {IS_END}")
    print(f"OOS: {OOS_START} to {OOS_END}")
    print("=" * 70)

    params = {**PARAMETERS}

    # ── 1. IS Backtest ─────────────────────────────────────────────────────
    print(f"\n[1/8] Running IS backtest ({IS_START} to {IS_END})...")
    is_result = run_backtest(params=params, start=IS_START, end=IS_END)
    is_returns = is_result["_combined_returns"]
    is_pnl = is_result["_pnl_vals"]
    print(f"  IS Sharpe:        {is_result['sharpe']:.4f}")
    print(f"  IS MDD:           {is_result['max_drawdown']:.4f}")
    print(f"  IS Win Rate:      {is_result['win_rate']:.4f}")
    print(f"  IS Profit Factor: {is_result['profit_factor']:.4f}")
    print(f"  IS Total Return:  {is_result['total_return']:.4f}")
    print(f"  IS Trade Count:   {is_result['trade_count']}")
    print(f"  YC filter stats:  {is_result.get('filter_stats', {})}")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────
    print(f"\n[2/8] Running OOS backtest ({OOS_START} to {OOS_END})...")
    oos_result = run_backtest(params=params, start=OOS_START, end=OOS_END)
    oos_returns = oos_result["_combined_returns"]
    print(f"  OOS Sharpe:       {oos_result['sharpe']:.4f}")
    print(f"  OOS MDD:          {oos_result['max_drawdown']:.4f}")
    print(f"  OOS Win Rate:     {oos_result['win_rate']:.4f}")
    print(f"  OOS Total Return: {oos_result['total_return']:.4f}")
    print(f"  OOS Trade Count:  {oos_result['trade_count']}")
    print(f"  YC filter stats:  {oos_result.get('filter_stats', {})}")

    # ── 3. Regime-Slice Analysis ───────────────────────────────────────────
    print("\n[3/8] Running regime-slice analysis (4 slices: pre-COVID/stimulus/rate-shock/normalization)...")
    regime_analysis = compute_regime_slices(params)
    for rn, rv in regime_analysis.get("regimes", {}).items():
        sharpe_str = f"{rv['sharpe']:.4f}" if "sharpe" in rv else "N/A"
        pass_str = "PASS" if rv.get("passes") else "FAIL"
        yc_blocked = rv.get("yc_blocked", 0)
        print(f"  {rn}: Sharpe={sharpe_str} [{pass_str}] YC-blocked={yc_blocked}")
    print(
        f"  Regime-slice overall: {regime_analysis.get('n_passing', 0)} passing "
        f"— {'PASS' if regime_analysis.get('regime_slice_pass') else 'FAIL'}"
    )

    # ── 4. Walk-Forward ────────────────────────────────────────────────────
    print("\n[4/8] Running walk-forward analysis (4 windows, 36m IS / 6m OOS)...")
    wf = run_walk_forward(params, n_windows=4, train_months=36, test_months=6)
    print(f"  Windows passed: {wf['windows_passed']}/4")
    for w in wf["windows"]:
        if "error" in w:
            print(f"  Window {w['window']}: ERROR — {w['error']}")
        else:
            status = "PASS" if w.get("pass") else "FAIL"
            print(f"  Window {w['window']}: IS={w['is_sharpe']:.2f}  OOS={w['oos_sharpe']:.2f}  [{status}]")
    wf_var = walk_forward_variance(wf["oos_sharpes"])

    # ── 5. Monte Carlo ─────────────────────────────────────────────────────
    print("\n[5/8] Running Monte Carlo simulation (1,000 resamples)...")
    mc = (
        monte_carlo_sharpe(is_pnl)
        if len(is_pnl) > 1
        else {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    )
    print(f"  MC p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}")
    if mc["mc_p5_sharpe"] < 0.5:
        print("  WARNING: MC pessimistic bound weak (p5 Sharpe < 0.5)")

    # ── 6. Block Bootstrap CI ──────────────────────────────────────────────
    print("\n[6/8] Running block bootstrap CI (1,000 boots)...")
    bb = (
        block_bootstrap_ci(is_returns)
        if len(is_returns) > 10
        else {k: 0.0 for k in ["sharpe_ci_low", "sharpe_ci_high", "mdd_ci_low",
                                "mdd_ci_high", "win_rate_ci_low", "win_rate_ci_high"]}
    )
    print(f"  Sharpe CI: [{bb['sharpe_ci_low']:.3f}, {bb['sharpe_ci_high']:.3f}]")
    print(f"  MDD CI:    [{bb['mdd_ci_low']:.3f}, {bb['mdd_ci_high']:.3f}]")
    print(f"  Win Rate CI: [{bb['win_rate_ci_low']:.3f}, {bb['win_rate_ci_high']:.3f}]")

    # ── 7. Permutation Test + DSR ──────────────────────────────────────────
    print("\n[7/8] Running permutation test and DSR computation...")
    perm = permutation_test_alpha(is_returns, is_result["sharpe"])
    print(f"  Permutation p-value: {perm['permutation_pvalue']:.4f}  "
          f"({'PASS' if perm['permutation_test_pass'] else 'FAIL'})")
    # n_trials: 4 parameters × 3 values each = 12 combinations in scan
    n_trials = 12
    dsr = compute_dsr(is_returns, n_trials)
    print(f"  DSR: {dsr:.4f}")

    # ── 8. Parameter Sensitivity Scan ─────────────────────────────────────
    print("\n[8/8] Running parameter sensitivity scan (H07c grid)...")
    sens_results = scan_parameters(start=IS_START, end=IS_END, base_params=params)
    print(f"  Sharpe range: {sens_results.get('_sharpe_range', 'N/A')}")
    print(f"  Sensitivity:  {sens_results.get('_gate1_variance_flag', 'N/A')}")
    for k, v in sens_results.items():
        if not k.startswith("_"):
            print(f"  {k}: {v}")
    sensitivity_pass = "PASS" in str(sens_results.get("_gate1_variance_flag", ""))

    # ── Gate 1 Evaluation ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("GATE 1 EVALUATION")
    print("=" * 70)

    regime_slice_pass = regime_analysis.get("regime_slice_pass", False)

    gate1_checks = {
        "is_sharpe_pass":       is_result["sharpe"] > 1.0,
        "oos_sharpe_pass":      oos_result["sharpe"] > 0.7,
        "is_mdd_pass":          abs(is_result["max_drawdown"]) < 0.20,
        "oos_mdd_pass":         abs(oos_result["max_drawdown"]) < 0.25,
        "win_rate_pass":        is_result["win_rate"] > 0.50,
        "trade_count_pass":     is_result["trade_count"] >= 100,
        "wf_windows_pass":      wf["windows_passed"] >= 3,
        "wf_consistency_pass":  wf["wf_consistency_score"] >= 0.70,
        "sensitivity_pass":     sensitivity_pass,
        "dsr_pass":             dsr > 0.0,
        "permutation_pass":     perm["permutation_test_pass"],
        "regime_slice_pass":    regime_slice_pass,
    }
    gate1_pass = all(gate1_checks.values())

    for criterion, passed in gate1_checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {criterion}")

    print(f"\n{'GATE 1: PASS' if gate1_pass else 'GATE 1: FAIL'}")
    print("=" * 70)

    # ── Assemble Output JSON ───────────────────────────────────────────────
    is_filter_stats = is_result.get("filter_stats", {})
    oos_filter_stats = oos_result.get("filter_stats", {})

    output = {
        "strategy":         STRATEGY_NAME,
        "date":             TODAY,
        "asset_class":      "equities",
        "is_period":        f"{IS_START} to {IS_END}",
        "oos_period":       f"{OOS_START} to {OOS_END}",
        "is_sharpe":        round(is_result["sharpe"], 4),
        "oos_sharpe":       round(oos_result["sharpe"], 4),
        "is_max_drawdown":  round(is_result["max_drawdown"], 4),
        "oos_max_drawdown": round(oos_result["max_drawdown"], 4),
        "is_win_rate":      round(is_result["win_rate"], 4),
        "oos_win_rate":     round(oos_result["win_rate"], 4),
        "is_profit_factor": round(is_result["profit_factor"], 4),
        "is_total_return":  round(is_result["total_return"], 4),
        "oos_total_return": round(oos_result["total_return"], 4),
        "is_trade_count":   is_result["trade_count"],
        "oos_trade_count":  oos_result["trade_count"],
        # Yield curve filter metrics (new for H07c — QUA-169 requirement)
        "is_yc_blocked_count":    is_filter_stats.get("yc_blocked_count", 0),
        "is_vix_crisis_blocked":  is_filter_stats.get("vix_crisis_blocked_count", 0),
        "is_raw_entry_opportunities": is_filter_stats.get("raw_entry_opportunities", 0),
        "is_yc_block_rate":       is_filter_stats.get("yc_block_rate", 0),
        "oos_yc_blocked_count":   oos_filter_stats.get("yc_blocked_count", 0),
        "oos_yc_block_rate":      oos_filter_stats.get("yc_block_rate", 0),
        "duration_sensitive_tickers": is_filter_stats.get("duration_sensitive_tickers_in_universe", []),
        # Regime data
        "is_yc_regime_stats":   is_result.get("yc_regime_stats", {}),
        "oos_yc_regime_stats":  oos_result.get("yc_regime_stats", {}),
        "is_vix_regime_stats":  is_result.get("vix_regime_stats", {}),
        "oos_vix_regime_stats": oos_result.get("vix_regime_stats", {}),
        # Walk-forward
        "wf_windows_passed":    wf["windows_passed"],
        "wf_consistency_score": round(wf["wf_consistency_score"], 4),
        "wf_oos_sharpes":       wf["oos_sharpes"],
        "wf_details":           wf["windows"],
        "wf_sharpe_std":        round(wf_var["wf_sharpe_std"], 4),
        "wf_sharpe_min":        round(wf_var["wf_sharpe_min"], 4),
        # Monte Carlo
        "mc_p5_sharpe":         round(mc["mc_p5_sharpe"], 4),
        "mc_median_sharpe":     round(mc["mc_median_sharpe"], 4),
        "mc_p95_sharpe":        round(mc["mc_p95_sharpe"], 4),
        # Bootstrap CI
        "sharpe_ci_low":        round(bb["sharpe_ci_low"], 4),
        "sharpe_ci_high":       round(bb["sharpe_ci_high"], 4),
        "mdd_ci_low":           round(bb["mdd_ci_low"], 4),
        "mdd_ci_high":          round(bb["mdd_ci_high"], 4),
        "win_rate_ci_low":      round(bb["win_rate_ci_low"], 4),
        "win_rate_ci_high":     round(bb["win_rate_ci_high"], 4),
        # Permutation + DSR
        "permutation_pvalue":    round(perm["permutation_pvalue"], 6),
        "permutation_test_pass": perm["permutation_test_pass"],
        "dsr":                   round(dsr, 4),
        "n_trials":              n_trials,
        # Sensitivity
        "sensitivity":           {k: v for k, v in sens_results.items()},
        # Regime slices
        "regime_slices":         regime_analysis.get("regimes", {}),
        "regime_slice_pass":     regime_analysis.get("regime_slice_pass", False),
        "n_regime_slices_passing": regime_analysis.get("n_passing", 0),
        "stress_regimes_passing": regime_analysis.get("stress_regime_passing", []),
        # Liquidity
        "market_impact_bps":      0.0,  # negligible for $25K position in mega-cap ETFs
        "liquidity_constrained":  is_result.get("liquidity", {}).get("liquidity_constrained", False),
        "order_to_adv_ratio":     0.0,
        # Data quality
        "data_quality":           is_result.get("data_quality", {}),
        "yield_curve_quality":    is_result.get("yield_curve_quality", {}),
        # Gate 1
        "gate1_checks":           gate1_checks,
        "gate1_pass":             gate1_pass,
    }

    # ── Write Output Files ─────────────────────────────────────────────────
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path    = os.path.join(out_dir, f"{STRATEGY_NAME}_{TODAY}.json")
    verdict_path = os.path.join(out_dir, f"{STRATEGY_NAME}_{TODAY}_verdict.txt")

    with open(json_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    failing_criteria = [k for k, v in gate1_checks.items() if not v]
    verdict_lines = [
        f"H07c Gate 1 Verdict — {TODAY}",
        f"Strategy: {STRATEGY_NAME}",
        f"IS period:  {IS_START} to {IS_END}",
        f"OOS period: {OOS_START} to {OOS_END}",
        "",
        f"IS Sharpe:         {output['is_sharpe']} ({'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'} > 1.0)",
        f"OOS Sharpe:        {output['oos_sharpe']} ({'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'} > 0.7)",
        f"IS MDD:            {output['is_max_drawdown']} ({'PASS' if gate1_checks['is_mdd_pass'] else 'FAIL'} < 0.20)",
        f"OOS MDD:           {output['oos_max_drawdown']} ({'PASS' if gate1_checks['oos_mdd_pass'] else 'FAIL'} < 0.25)",
        f"IS Win Rate:       {output['is_win_rate']} ({'PASS' if gate1_checks['win_rate_pass'] else 'FAIL'} > 0.50)",
        f"IS Trade Count:    {output['is_trade_count']} ({'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'} >= 100)",
        f"WF Windows Passed: {output['wf_windows_passed']}/4 ({'PASS' if gate1_checks['wf_windows_pass'] else 'FAIL'} >= 3)",
        f"WF Consistency:    {output['wf_consistency_score']} ({'PASS' if gate1_checks['wf_consistency_pass'] else 'FAIL'} >= 0.70)",
        f"Sensitivity:       {sens_results.get('_gate1_variance_flag', 'N/A')}",
        f"DSR:               {output['dsr']} ({'PASS' if gate1_checks['dsr_pass'] else 'FAIL'} > 0)",
        f"Permutation p:     {output['permutation_pvalue']} ({'PASS' if gate1_checks['permutation_pass'] else 'FAIL'} <= 0.05)",
        f"Regime-slice:      ({'PASS' if gate1_checks['regime_slice_pass'] else 'FAIL'})",
        "",
        "H07c-Specific Metrics:",
        f"  IS YC-blocked entries:  {output['is_yc_blocked_count']} of {output['is_raw_entry_opportunities']} ({output['is_yc_block_rate']:.1%})",
        f"  OOS YC-blocked entries: {output['oos_yc_blocked_count']} of {oos_filter_stats.get('raw_entry_opportunities', 0)} ({output['oos_yc_block_rate']:.1%})",
        f"  IS VIX-crisis-blocked:  {output['is_vix_crisis_blocked']}",
        f"  Duration-sensitive ETFs: {output['duration_sensitive_tickers']}",
        "",
        "Statistical Rigor:",
        f"  MC p5 Sharpe:       {output['mc_p5_sharpe']}",
        f"  MC Median Sharpe:   {output['mc_median_sharpe']}",
        f"  Sharpe 95% CI:      [{output['sharpe_ci_low']}, {output['sharpe_ci_high']}]",
        f"  WF Sharpe Std:      {output['wf_sharpe_std']}",
        f"  WF Sharpe Min:      {output['wf_sharpe_min']}",
        "",
        "Regime Slices:",
    ]

    for rn, rv in regime_analysis.get("regimes", {}).items():
        sharpe_str = f"{rv.get('sharpe', 'N/A')}"
        pass_str = "PASS" if rv.get("passes") else "FAIL"
        verdict_lines.append(f"  {rn}: Sharpe={sharpe_str} [{pass_str}]")

    if failing_criteria:
        verdict_lines += ["", "FAILING CRITERIA:"]
        for fc in failing_criteria:
            verdict_lines.append(f"  - {fc}")

    verdict_lines += ["", f"GATE 1: {'PASS' if gate1_pass else 'FAIL'}"]

    with open(verdict_path, "w") as f:
        f.write("\n".join(verdict_lines))

    print(f"\nOutput files:")
    print(f"  {json_path}")
    print(f"  {verdict_path}")

    return output


if __name__ == "__main__":
    main()
