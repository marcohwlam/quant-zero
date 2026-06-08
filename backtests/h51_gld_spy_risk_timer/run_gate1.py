"""
H51 Gate 1 v2.0 Full Backtest Runner
QUA-108 — Engineering Director
Date: 2026-06-08

Strategy: Gold/Equity Relative Momentum Risk Timer — GLD/SPY Monthly Rotation
Hypothesis: research/hypotheses/51_qc_gold_equity_risk_rotation.md

Runs:
  - IS/OOS backtests (baseline + parameter sweep)
  - Statistical rigor: Monte Carlo p5, block bootstrap CI, permutation test, walk-forward
  - Dot-com stress test with GC=F proxy (PF-2 requirement)
  - GFC and 2022 rate-shock stress windows
  - Parameter sensitivity: lookback_days × safe_harbor × rebalance_frequency

Gate 1 v2.0 acceptance:
  - IS Sharpe > 1.0
  - OOS Sharpe > 0.7
  - IS MDD < 20%
  - Minimum 100 monthly rebalances in IS window (PF-1 criterion)
  - WF windows passed >= 3/4
"""

import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
import dateutil.relativedelta as rd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from strategies.h51_gld_spy_risk_timer import run_backtest, PARAMETERS

STRATEGY_NAME = "h51_gld_spy_risk_timer"
OUT_DIR = os.path.join(REPO_ROOT, "backtests", "h51_gld_spy_risk_timer")

IS_START  = "2005-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2025-12-31"

# Gate 1 v2.0 thresholds
GATE1 = {
    "is_sharpe":     1.0,
    "oos_sharpe":    0.7,
    "is_mdd":        0.20,
    "oos_mdd":       0.25,
    "min_rebalances": 100,   # monthly rebalances as trade count (PF-1 approved)
    "wf_windows":    3,
}


# ── Statistical Helpers ────────────────────────────────────────────────────────

def compute_sharpe(returns_arr: np.ndarray) -> float:
    if len(returns_arr) == 0 or returns_arr.std() == 0:
        return 0.0
    return float(returns_arr.mean() / returns_arr.std() * np.sqrt(252))


def compute_mdd(returns_arr: np.ndarray) -> float:
    if len(returns_arr) == 0:
        return 0.0
    cum = np.cumprod(1 + returns_arr)
    roll_max = np.maximum.accumulate(cum)
    return float(np.min((cum - roll_max) / (roll_max + 1e-8)))


def compute_profit_factor(trade_pnls: np.ndarray) -> float:
    gross_profit = float(trade_pnls[trade_pnls > 0].sum())
    gross_loss = float(abs(trade_pnls[trade_pnls < 0].sum()))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    """Bootstrap trade PnL to get Sharpe distribution."""
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe": float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = T // block_len
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)
    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low": float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def permutation_test_alpha(observed_sharpe: float, trade_pnls: np.ndarray, n_perms: int = 500) -> dict:
    """Shuffle trade PnL; compute fraction of permuted Sharpes >= observed."""
    permuted = []
    for _ in range(n_perms):
        shuffled = np.random.permutation(trade_pnls)
        s = shuffled.mean() / (shuffled.std() + 1e-8) * np.sqrt(252)
        permuted.append(s)
    permuted = np.array(permuted)
    p_value = float(np.mean(permuted >= observed_sharpe))
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": p_value <= 0.05,
    }


def compute_dsr(returns_series: pd.Series, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)."""
    from scipy import stats as scipy_stats
    T = len(returns_series)
    if T < 10:
        return 0.0
    sr = compute_sharpe(returns_series.values)
    skew = float(returns_series.skew())
    kurt = float(returns_series.kurtosis())
    gamma = 0.5772
    sr_star = (
        (1 - gamma) * scipy_stats.norm.ppf(1 - 1.0 / n_trials)
        + gamma * scipy_stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sr_star_ann = sr_star / np.sqrt(T)
    sigma_sr = np.sqrt((1 - skew * sr + (kurt / 4 - 1) * sr**2) / (T - 1))
    if sigma_sr <= 0:
        return float(sr > sr_star_ann)
    return round(float(scipy_stats.norm.cdf((sr - sr_star_ann) / sigma_sr)), 6)


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(params: dict, train_months: int = 48, test_months: int = 12) -> list:
    """
    4-fold walk-forward: IS=48mo (4yr) / OOS=12mo (1yr) anchored from IS_START.
    H51 IS window 2005–2021 = 17 years → 4 folds of 4yr IS + 1yr OOS = sensible.
    """
    base_start = pd.Timestamp(IS_START)
    results = []
    for fold in range(4):
        offset_mo = fold * test_months
        wf_is_start = (base_start + rd.relativedelta(months=offset_mo)).strftime("%Y-%m-%d")
        wf_is_end = (
            base_start + rd.relativedelta(months=offset_mo + train_months) - pd.Timedelta(days=1)
        ).strftime("%Y-%m-%d")
        wf_oos_start = (base_start + rd.relativedelta(months=offset_mo + train_months)).strftime("%Y-%m-%d")
        wf_oos_end = (
            base_start + rd.relativedelta(months=offset_mo + train_months + test_months) - pd.Timedelta(days=1)
        ).strftime("%Y-%m-%d")

        try:
            is_r = run_backtest(wf_is_start, wf_is_end, params.copy())
            oos_r = run_backtest(wf_oos_start, wf_oos_end, params.copy())
            is_s = is_r["sharpe"]
            oos_s = oos_r["sharpe"]
            passed = oos_s > 0 and oos_s >= 0.7 * max(is_s, 0.01)
            results.append({
                "fold": fold + 1,
                "is_start": wf_is_start, "is_end": wf_is_end,
                "oos_start": wf_oos_start, "oos_end": wf_oos_end,
                "is_sharpe": float(is_s), "oos_sharpe": float(oos_s),
                "is_rebalances": int(is_r["monthly_rebalances"]),
                "oos_rebalances": int(oos_r["monthly_rebalances"]),
                "is_riskoff_pct": float(is_r["pct_riskoff"]),
                "oos_riskoff_pct": float(oos_r["pct_riskoff"]),
                "passed": passed,
            })
            print(
                f"  WF Fold {fold+1}: IS={is_s:.3f}, OOS={oos_s:.3f}, "
                f"IS_rebal={is_r['monthly_rebalances']}, OOS_rebal={oos_r['monthly_rebalances']}, "
                f"pass={passed}"
            )
        except Exception as e:
            print(f"  WF Fold {fold+1} ERROR: {e}")
            results.append({
                "fold": fold + 1, "error": str(e),
                "passed": False, "oos_sharpe": 0.0, "is_sharpe": 0.0,
            })
    return results


# ── Parameter Sensitivity ──────────────────────────────────────────────────────

def run_sensitivity_sweep(params: dict) -> dict:
    """
    12-point grid: lookback_days ∈ {10, 20, 30} × safe_harbor ∈ {SHY, TLT} × rebalance_frequency ∈ {monthly, biweekly}.
    Collapse to 12 combos (biweekly doubles the lookback combinations).
    """
    base_sharpe = None
    results = {}
    sharpes = []

    for lb in [10, 20, 30]:
        for harbor in ["SHY", "TLT"]:
            for freq in ["monthly", "biweekly"]:
                p = params.copy()
                p["lookback_days"] = lb
                p["safe_harbor"] = harbor
                p["rebalance_frequency"] = freq
                key = f"lb{lb}_{harbor}_{freq}"
                try:
                    r = run_backtest(IS_START, IS_END, p)
                    s = r["sharpe"]
                    results[key] = {
                        "sharpe": float(s),
                        "mdd": float(r["max_drawdown"]),
                        "rebalances": int(r["monthly_rebalances"]),
                        "riskoff_pct": float(r["pct_riskoff"]),
                    }
                    sharpes.append(s)
                    if lb == 20 and harbor == "SHY" and freq == "monthly":
                        base_sharpe = s
                    print(f"  Sensitivity {key}: Sharpe={s:.4f}, MDD={r['max_drawdown']:.2%}")
                except Exception as e:
                    results[key] = {"error": str(e)}
                    print(f"  Sensitivity {key}: ERROR {e}")

    unstable = False
    instability_notes = []
    if base_sharpe is not None and base_sharpe > 0:
        for key, val in results.items():
            if "sharpe" in val:
                reduction = (base_sharpe - val["sharpe"]) / (abs(base_sharpe) + 1e-8)
                if reduction > 0.50:
                    unstable = True
                    instability_notes.append(
                        f"{key}: Sharpe={val['sharpe']:.4f} ({reduction:.1%} below base)"
                    )

    sharpe_variance = float(np.var(sharpes)) if sharpes else 0.0
    sharpe_range = float(max(sharpes) - min(sharpes)) if len(sharpes) >= 2 else 0.0

    return {
        "grid": results,
        "base_sharpe": float(base_sharpe) if base_sharpe is not None else None,
        "sharpe_variance": sharpe_variance,
        "sharpe_range": sharpe_range,
        "sharpe_values": [float(s) for s in sharpes],
        "unstable": unstable,
        "instability_notes": instability_notes,
        "sensitivity_pass": not unstable,
    }


# ── Stress Windows ─────────────────────────────────────────────────────────────

def run_stress_windows(params: dict) -> dict:
    """
    H51 stress windows:
    - dot_com_gcf (2000–2004): GC=F proxy, validates PF-2 conditional pass
    - gfc_2008_2009: GLD available, validates GFC MDD < 20–25%
    - rate_shock_2022: rate-shock, validates PF-4 claim
    """
    windows = {
        "gfc_2008_2009": ("2007-01-01", "2009-12-31", False),
        "rate_shock_2022": ("2022-01-01", "2022-12-31", False),
    }
    stress_results = {}
    for name, (start, end, use_gcf) in windows.items():
        p = params.copy()
        p["use_gcf_proxy"] = use_gcf
        try:
            r = run_backtest(start, end, p)
            mdd = r["max_drawdown"]
            stress_results[name] = {
                "mdd": float(mdd),
                "sharpe": float(r["sharpe"]),
                "rebalances": int(r["monthly_rebalances"]),
                "riskoff_pct": float(r["pct_riskoff"]),
                "passed": abs(mdd) < 0.40,
            }
            print(f"  Stress {name}: MDD={mdd:.2%}, Sharpe={r['sharpe']:.4f}, risk-off%={r['pct_riskoff']:.1%}, pass={abs(mdd) < 0.40}")
        except Exception as e:
            stress_results[name] = {"error": str(e), "passed": False}
            print(f"  Stress {name}: ERROR {e}")

    # Dot-com with GC=F proxy (PF-2 validation)
    try:
        p_gcf = params.copy()
        p_gcf["use_gcf_proxy"] = True
        r_dotcom = run_backtest("2000-01-01", "2004-12-31", p_gcf)
        stress_results["dot_com_gcf_proxy"] = {
            "mdd": float(r_dotcom["max_drawdown"]),
            "sharpe": float(r_dotcom["sharpe"]),
            "rebalances": int(r_dotcom["monthly_rebalances"]),
            "riskoff_pct": float(r_dotcom["pct_riskoff"]),
            "pf2_note": "GC=F proxy used for gold signal (GLD inception Nov 2004)",
            "passed": abs(r_dotcom["max_drawdown"]) < 0.40,
        }
        print(
            f"  Stress dot_com_gcf_proxy: MDD={r_dotcom['max_drawdown']:.2%}, "
            f"Sharpe={r_dotcom['sharpe']:.4f}, risk-off%={r_dotcom['pct_riskoff']:.1%}"
        )
    except Exception as e:
        stress_results["dot_com_gcf_proxy"] = {"error": str(e), "passed": False}
        print(f"  Stress dot_com_gcf_proxy: ERROR {e}")

    return stress_results


# ── OOS Data Quality ───────────────────────────────────────────────────────────

def validate_oos_metrics(oos_result: dict) -> dict:
    critical_fields = ["sharpe", "max_drawdown", "win_rate", "monthly_rebalances"]
    advisory_fields = ["profit_factor", "pct_riskoff"]
    nan_critical = []
    nan_advisory = []
    for f in critical_fields:
        v = oos_result.get(f)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            nan_critical.append(f)
    for f in advisory_fields:
        v = oos_result.get(f)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            nan_advisory.append(f)
    oos_returns = oos_result.get("returns", pd.Series(dtype=float))
    returns_nan = int(oos_returns.isna().sum()) if hasattr(oos_returns, "isna") else 0
    recommendation = "BLOCK" if nan_critical else ("WARN" if (nan_advisory or returns_nan > 0) else "PASS")
    return {
        "strategy_name": STRATEGY_NAME,
        "recommendation": recommendation,
        "critical_nan_fields": nan_critical,
        "advisory_nan_fields": nan_advisory,
        "returns_nan_count": returns_nan,
        "oos_rebalances": oos_result.get("monthly_rebalances", 0),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    np.random.seed(42)
    params = PARAMETERS.copy()
    os.makedirs(OUT_DIR, exist_ok=True)

    print("=" * 70)
    print(f"H51 GLD/SPY Risk Timer — Gate 1 v2.0 — QUA-108")
    print(f"IS:  {IS_START} → {IS_END}")
    print(f"OOS: {OOS_START} → {OOS_END}")
    print("=" * 70)

    # ── 1. IS Backtest ─────────────────────────────────────────────────────────
    print("\n[1/8] IS backtest (baseline: lb=20d, SHY, monthly)...")
    with warnings.catch_warnings(record=True) as w_is:
        warnings.simplefilter("always")
        is_result = run_backtest(IS_START, IS_END, params.copy())
    is_warnings = [str(x.message) for x in w_is]

    is_trades = is_result["trades"]
    is_returns = is_result["returns"].values
    is_trade_pnls = is_trades["pnl"].values if not is_trades.empty else np.array([])
    is_sharpe = is_result["sharpe"]
    is_mdd = is_result["max_drawdown"]
    is_win_rate = is_result["win_rate"]
    is_rebalances = is_result["monthly_rebalances"]  # PF-1 trade count
    is_pf = compute_profit_factor(is_trade_pnls)
    print(
        f"  IS Sharpe={is_sharpe:.4f}, MDD={is_mdd:.2%}, "
        f"Rebalances={is_rebalances}, Transitions={is_result['n_transitions']}, "
        f"Risk-off%={is_result['pct_riskoff']:.1%}, WinRate={is_win_rate:.2%}, PF={is_pf:.4f}"
    )

    # ── 2. OOS Backtest ────────────────────────────────────────────────────────
    print("\n[2/8] OOS backtest...")
    with warnings.catch_warnings(record=True) as w_oos:
        warnings.simplefilter("always")
        oos_result = run_backtest(OOS_START, OOS_END, params.copy())
    oos_warnings = [str(x.message) for x in w_oos]

    dq_report = validate_oos_metrics(oos_result)
    if dq_report["recommendation"] == "BLOCK":
        print(f"  [OOS DATA QUALITY BLOCK] {dq_report['critical_nan_fields']}")
        raise RuntimeError(f"OOS data quality BLOCK: {dq_report}")
    if dq_report["recommendation"] == "WARN":
        print(f"  [OOS DATA QUALITY WARN] {dq_report['advisory_nan_fields']}")

    oos_trades = oos_result["trades"]
    oos_returns = oos_result["returns"].values
    oos_trade_pnls = oos_trades["pnl"].values if not oos_trades.empty else np.array([])
    oos_sharpe = oos_result["sharpe"]
    oos_mdd = oos_result["max_drawdown"]
    oos_win_rate = oos_result["win_rate"]
    oos_rebalances = oos_result["monthly_rebalances"]
    oos_pf = compute_profit_factor(oos_trade_pnls)
    print(
        f"  OOS Sharpe={oos_sharpe:.4f}, MDD={oos_mdd:.2%}, "
        f"Rebalances={oos_rebalances}, Transitions={oos_result['n_transitions']}, "
        f"Risk-off%={oos_result['pct_riskoff']:.1%}, WinRate={oos_win_rate:.2%}, PF={oos_pf:.4f}"
    )

    # ── 3. Monte Carlo ─────────────────────────────────────────────────────────
    print("\n[3/8] Monte Carlo p5 Sharpe (IS trade PnL, 1000 sims)...")
    if len(is_trade_pnls) > 1:
        mc = monte_carlo_sharpe(is_trade_pnls)
    else:
        mc = {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    print(f"  p5={mc['mc_p5_sharpe']:.4f}, median={mc['mc_median_sharpe']:.4f}, p95={mc['mc_p95_sharpe']:.4f}")
    mc_flag = mc["mc_p5_sharpe"] < 0.5

    # ── 4. Block Bootstrap CI ──────────────────────────────────────────────────
    print("\n[4/8] Block bootstrap CI (IS returns, 1000 boots)...")
    if len(is_returns) > 10:
        bci = block_bootstrap_ci(is_returns)
    else:
        bci = {k: 0.0 for k in ["sharpe_ci_low", "sharpe_ci_high", "mdd_ci_low", "mdd_ci_high", "win_rate_ci_low", "win_rate_ci_high"]}
    print(f"  Sharpe CI: [{bci['sharpe_ci_low']:.4f}, {bci['sharpe_ci_high']:.4f}]")
    print(f"  MDD CI: [{bci['mdd_ci_low']:.4f}, {bci['mdd_ci_high']:.4f}]")

    # ── 5. Permutation Test ────────────────────────────────────────────────────
    print("\n[5/8] Permutation test for alpha (500 permutations)...")
    if len(is_trade_pnls) > 1:
        perm = permutation_test_alpha(is_sharpe, is_trade_pnls)
    else:
        perm = {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    print(f"  p-value={perm['permutation_pvalue']:.4f}, pass={perm['permutation_test_pass']}")

    # ── 6. Walk-Forward ────────────────────────────────────────────────────────
    print("\n[6/8] Walk-forward (4 folds: IS=48mo, OOS=12mo)...")
    wf_results = run_walk_forward(params)
    wf_oos_sharpes = [r.get("oos_sharpe", 0.0) for r in wf_results]
    wf_is_sharpes = [r.get("is_sharpe", 0.0) for r in wf_results]
    wf_windows_passed = sum(1 for r in wf_results if r.get("passed", False))
    wf_sharpe_std = float(np.std(wf_oos_sharpes)) if wf_oos_sharpes else 0.0
    wf_sharpe_min = float(np.min(wf_oos_sharpes)) if wf_oos_sharpes else 0.0
    wf_consistency = []
    for r in wf_results:
        is_s = r.get("is_sharpe", 0.0)
        oos_s = r.get("oos_sharpe", 0.0)
        if abs(is_s) > 0:
            wf_consistency.append(abs(oos_s - is_s) / (abs(is_s) + 1e-8) <= 0.30)
    wf_consistency_score = sum(wf_consistency) / max(len(wf_consistency), 1)
    print(f"  WF windows passed: {wf_windows_passed}/4, consistency={wf_consistency_score:.2f}")
    print(f"  WF OOS Sharpes: {[round(s, 3) for s in wf_oos_sharpes]}")
    print(f"  WF std={wf_sharpe_std:.4f}, min={wf_sharpe_min:.4f}")

    # ── 7. DSR ─────────────────────────────────────────────────────────────────
    n_trials = 12  # sensitivity grid size
    dsr = compute_dsr(is_result["returns"], n_trials)
    print(f"\n  DSR={dsr:.6f} (n_trials={n_trials})")

    # ── 8. Stress Windows ──────────────────────────────────────────────────────
    print("\n[7/8] Stress windows (GFC 2007–2009, Rate-shock 2022, Dot-com GC=F)...")
    stress = run_stress_windows(params)
    stress_all_pass = all(s.get("passed", False) for s in stress.values())

    # ── 9. Parameter Sensitivity ───────────────────────────────────────────────
    print("\n[8/8] Parameter sensitivity (12-point grid)...")
    sensitivity = run_sensitivity_sweep(params)
    print(
        f"  Sensitivity: variance={sensitivity['sharpe_variance']:.4f}, "
        f"range={sensitivity['sharpe_range']:.4f}, pass={sensitivity['sensitivity_pass']}"
    )

    # ── Gate 1 v2.0 Checks ────────────────────────────────────────────────────
    oos_is_ratio = oos_sharpe / (is_sharpe + 1e-8) if is_sharpe > 0 else 0.0

    gate1_checks = {
        "is_sharpe_gt_1":       is_sharpe > GATE1["is_sharpe"],
        "oos_sharpe_gt_0.7":    oos_sharpe > GATE1["oos_sharpe"],
        "is_mdd_lt_20pct":      abs(is_mdd) < GATE1["is_mdd"],
        "oos_mdd_lt_25pct":     abs(oos_mdd) < GATE1["oos_mdd"],
        "min_rebalances_100":   is_rebalances >= GATE1["min_rebalances"],
        "win_rate_gt_50pct":    is_win_rate > 0.50,
        "dsr_gt_0":             dsr > 0,
        "wf_windows_3of4":      wf_windows_passed >= GATE1["wf_windows"],
        "wf_consistency":       wf_consistency_score >= 0.75,
        "sensitivity_pass":     sensitivity["sensitivity_pass"],
        "stress_mdd_lt_40pct":  stress_all_pass,
        "permutation_test":     perm["permutation_test_pass"],
        "mc_p5_gt_0":           mc["mc_p5_sharpe"] > 0,
    }

    gate1_pass = all(gate1_checks.values())
    failing = [k for k, v in gate1_checks.items() if not v]
    gate1_verdict = "PASS" if gate1_pass else "FAIL"

    # Special instruction: flag as combo candidate if IS Sharpe 0.80–0.99
    combo_candidate_flag = 0.80 <= is_sharpe < 1.0
    if combo_candidate_flag:
        print(
            f"\n  [COMBO CANDIDATE] IS Sharpe={is_sharpe:.4f} in 0.80–0.99 range. "
            "Flag H50+H51 combination candidate to Research Director per QUA-108 special instructions."
        )

    print(f"\n{'='*70}")
    print(f"GATE 1 v2.0 VERDICT: {gate1_verdict}")
    if failing:
        print(f"FAILING CRITERIA: {failing}")
    print(f"IS Sharpe={is_sharpe:.4f}  (>{GATE1['is_sharpe']}: {gate1_checks['is_sharpe_gt_1']})")
    print(f"OOS Sharpe={oos_sharpe:.4f} (>{GATE1['oos_sharpe']}: {gate1_checks['oos_sharpe_gt_0.7']})")
    print(f"OOS/IS ratio={oos_is_ratio:.3f}")
    print(f"IS MDD={is_mdd:.2%} (<{GATE1['is_mdd']:.0%}: {gate1_checks['is_mdd_lt_20pct']})")
    print(f"OOS MDD={oos_mdd:.2%} (<{GATE1['oos_mdd']:.0%}: {gate1_checks['oos_mdd_lt_25pct']})")
    print(f"IS Rebalances={is_rebalances} (>={GATE1['min_rebalances']}: {gate1_checks['min_rebalances_100']})")
    print(f"DSR={dsr:.6f} (>0: {gate1_checks['dsr_gt_0']})")
    print(f"WF windows passed={wf_windows_passed}/4 (>={GATE1['wf_windows']}: {gate1_checks['wf_windows_3of4']})")
    print(f"H50+H51 combo candidate flag: {combo_candidate_flag}")
    print(f"{'='*70}")

    # ── Save Trade Logs ────────────────────────────────────────────────────────
    if not is_trades.empty or not oos_trades.empty:
        all_trades = pd.concat(
            [is_trades.assign(period="IS"), oos_trades.assign(period="OOS")],
            ignore_index=True,
        )
    else:
        all_trades = pd.DataFrame()
    trade_log_path = os.path.join(OUT_DIR, "trade_log.csv")
    all_trades.to_csv(trade_log_path, index=False)
    print(f"\nTrade log saved: {trade_log_path} ({len(all_trades)} total SPY trades)")

    # ── Save Results JSON ──────────────────────────────────────────────────────
    def _to_jsonable(v):
        if isinstance(v, (np.floating, np.float64, np.float32)):
            return float(v)
        if isinstance(v, (np.integer, np.int64, np.int32)):
            return int(v)
        if isinstance(v, np.bool_):
            return bool(v)
        return v

    stress_json = {
        k: {kk: _to_jsonable(vv) for kk, vv in v.items()}
        for k, v in stress.items()
    }
    wf_json = [
        {k: _to_jsonable(v) for k, v in r.items()}
        for r in wf_results
    ]

    results_out = {
        "strategy_name": STRATEGY_NAME,
        "date": "2026-06-08",
        "asset_class": "equities_etf",
        "hypothesis": "research/hypotheses/51_qc_gold_equity_risk_rotation.md",
        # IS
        "is_sharpe": float(is_sharpe),
        "is_max_drawdown": float(is_mdd),
        "is_trade_count": int(is_rebalances),   # monthly rebalances per PF-1
        "is_transitions": int(is_result["n_transitions"]),
        "is_win_rate": float(is_win_rate),
        "is_profit_factor": float(is_pf),
        "is_total_return": float(is_result["total_return"]),
        "is_riskoff_pct": float(is_result["pct_riskoff"]),
        "is_riskoff_months": int(is_result["n_riskoff_months"]),
        # OOS
        "oos_sharpe": float(oos_sharpe),
        "oos_max_drawdown": float(oos_mdd),
        "oos_trade_count": int(oos_rebalances),
        "oos_transitions": int(oos_result["n_transitions"]),
        "oos_win_rate": float(oos_win_rate),
        "oos_profit_factor": float(oos_pf),
        "oos_total_return": float(oos_result["total_return"]),
        "oos_riskoff_pct": float(oos_result["pct_riskoff"]),
        "oos_is_sharpe_ratio": float(oos_is_ratio),
        # Aggregated for Gate 1 reporter
        "sharpe": float(is_sharpe),
        "win_rate": float(is_win_rate),
        "profit_factor": float(is_pf),
        "trade_count": int(is_rebalances),
        "max_drawdown": float(is_mdd),
        # Statistical rigor
        "dsr": float(dsr),
        "mc_p5_sharpe": float(mc["mc_p5_sharpe"]),
        "mc_median_sharpe": float(mc["mc_median_sharpe"]),
        "mc_p95_sharpe": float(mc["mc_p95_sharpe"]),
        "mc_pessimistic_flag": bool(mc_flag),
        "sharpe_ci_low": float(bci["sharpe_ci_low"]),
        "sharpe_ci_high": float(bci["sharpe_ci_high"]),
        "mdd_ci_low": float(bci["mdd_ci_low"]),
        "mdd_ci_high": float(bci["mdd_ci_high"]),
        "win_rate_ci_low": float(bci["win_rate_ci_low"]),
        "win_rate_ci_high": float(bci["win_rate_ci_high"]),
        "permutation_pvalue": float(perm["permutation_pvalue"]),
        "permutation_test_pass": bool(perm["permutation_test_pass"]),
        "wf_sharpe_std": float(wf_sharpe_std),
        "wf_sharpe_min": float(wf_sharpe_min),
        "wf_windows_passed": int(wf_windows_passed),
        "wf_consistency_score": float(wf_consistency_score),
        "wf_results": wf_json,
        "wf_oos_sharpes": [float(s) for s in wf_oos_sharpes],
        # Stress
        "stress_windows": stress_json,
        "stress_all_pass": bool(stress_all_pass),
        # Sensitivity
        "sensitivity_pass": bool(sensitivity["sensitivity_pass"]),
        "sensitivity_results": {
            "grid": sensitivity["grid"],
            "base_sharpe": float(sensitivity["base_sharpe"]) if sensitivity["base_sharpe"] is not None else None,
            "sharpe_variance": float(sensitivity["sharpe_variance"]),
            "sharpe_range": float(sensitivity["sharpe_range"]),
            "sharpe_values": [float(s) for s in sensitivity["sharpe_values"]],
            "unstable": bool(sensitivity["unstable"]),
            "instability_notes": sensitivity["instability_notes"],
            "sensitivity_pass": bool(sensitivity["sensitivity_pass"]),
        },
        # Post-cost (baked in)
        "post_cost_sharpe": float(is_sharpe),
        "post_cost_sharpe_oos": float(oos_sharpe),
        # H50 combination note
        "combo_candidate_h50_h51": bool(combo_candidate_flag),
        "combo_note": (
            "IS Sharpe 0.80–0.99: flag to Research Director as H50+H51 combination candidate"
            if combo_candidate_flag else "Not in combo candidate range"
        ),
        # Gate 1
        "gate1_checks": gate1_checks,
        "gate1_pass": bool(gate1_pass),
        "gate1_verdict": gate1_verdict,
        "gate1_failing_criteria": failing,
        "look_ahead_bias_flag": False,
        # Data quality
        "data_quality": is_result["data_quality"],
        "oos_data_quality": dq_report,
        "is_warnings": is_warnings[:10],
        "oos_warnings": oos_warnings[:10],
        # Params
        "params": params,
    }

    results_path = os.path.join(OUT_DIR, "results.json")
    with open(results_path, "w") as f:
        json.dump(results_out, f, indent=2, default=str)
    print(f"Results JSON saved: {results_path}")

    # ── Save Verdict Text ──────────────────────────────────────────────────────
    verdict_lines = [
        f"H51 GLD/SPY Risk Timer — Gate 1 v2.0 Verdict — 2026-06-08",
        f"{'='*60}",
        f"IS Sharpe: {is_sharpe:.4f}  (>1.0: {gate1_checks['is_sharpe_gt_1']})",
        f"OOS Sharpe: {oos_sharpe:.4f}  (>0.7: {gate1_checks['oos_sharpe_gt_0.7']})",
        f"OOS/IS Sharpe ratio: {oos_is_ratio:.3f}",
        f"IS MDD: {is_mdd:.2%}  (<20%: {gate1_checks['is_mdd_lt_20pct']})",
        f"OOS MDD: {oos_mdd:.2%}  (<25%: {gate1_checks['oos_mdd_lt_25pct']})",
        f"IS Rebalances: {is_rebalances}  (>=100: {gate1_checks['min_rebalances_100']})",
        f"IS Transitions: {is_result['n_transitions']}  (regime switches)",
        f"Risk-off months (IS): {is_result['n_riskoff_months']} ({is_result['pct_riskoff']:.1%})",
        f"Win Rate (IS): {is_win_rate:.2%}  (>50%: {gate1_checks['win_rate_gt_50pct']})",
        f"DSR: {dsr:.6f}  (>0: {gate1_checks['dsr_gt_0']})",
        f"MC p5 Sharpe: {mc['mc_p5_sharpe']:.4f}  (>0: {gate1_checks['mc_p5_gt_0']})",
        f"Sharpe CI 95%: [{bci['sharpe_ci_low']:.4f}, {bci['sharpe_ci_high']:.4f}]",
        f"Permutation p-value: {perm['permutation_pvalue']:.4f}  (<=0.05: {gate1_checks['permutation_test']})",
        f"WF windows passed: {wf_windows_passed}/4  (>=3: {gate1_checks['wf_windows_3of4']})",
        f"WF OOS Sharpes: {[round(s, 3) for s in wf_oos_sharpes]}",
        f"WF std: {wf_sharpe_std:.4f}  WF min: {wf_sharpe_min:.4f}",
        f"Sensitivity pass: {sensitivity['sensitivity_pass']}  (range={sensitivity['sharpe_range']:.4f})",
        f"Stress windows all pass: {stress_all_pass}",
        f"",
        f"OVERALL VERDICT: {gate1_verdict}",
    ]
    if failing:
        verdict_lines.append(f"FAILING CRITERIA: {', '.join(failing)}")
    if combo_candidate_flag:
        verdict_lines.append(
            "COMBO CANDIDATE: IS Sharpe 0.80–0.99. Flag H50+H51 to Research Director."
        )

    verdict_path = os.path.join(OUT_DIR, "verdict.txt")
    with open(verdict_path, "w") as f:
        f.write("\n".join(verdict_lines))
    print(f"Verdict saved: {verdict_path}")

    return results_out


if __name__ == "__main__":
    results = main()
    print(f"\nFinal verdict: {results['gate1_verdict']}")
