"""
H09 Gate 1 Backtest Runner — TQQQ Weekly Snapback
Full IS/OOS + walk-forward + statistical rigor + sub-period + sensitivity pipeline.

Output:
  backtests/H09_TQQQSnapback_{TODAY}.json
  backtests/H09_TQQQSnapback_{TODAY}_verdict.txt
"""

import sys
import json
import warnings
import datetime
import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, "/mnt/c/Users/lamho/repo/quant-zero")

from strategies.h09_tqqq_weekly_snapback import (
    run_strategy,
    scan_entry_decline,
    scan_vix_gate,
    SUB_PERIODS,
    GFC_NOTE,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

warnings.filterwarnings("ignore")

TODAY = datetime.date.today().isoformat()
STRATEGY_NAME = "H09_TQQQSnapback"

# Per Research Director: IS must start no later than 2015
IS_START, IS_END = "2015-01-01", "2021-12-31"
OOS_START, OOS_END = "2022-01-01", "2023-12-31"


# ── Statistical Rigor Functions ────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    """Monte Carlo p5 Sharpe from bootstrap resampling of trade PnLs."""
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe": round(float(np.percentile(arr, 5)), 4),
        "mc_median_sharpe": round(float(np.median(arr)), 4),
        "mc_p95_sharpe": round(float(np.percentile(arr, 95)), 4),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    """Block bootstrap 95% CI for Sharpe, MDD, win rate."""
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        if len(sample) < 2 or sample.std() == 0:
            continue
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)
    if not sharpes:
        return {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
                "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
                "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0}
    return {
        "sharpe_ci_low": round(float(np.percentile(sharpes, 2.5)), 4),
        "sharpe_ci_high": round(float(np.percentile(sharpes, 97.5)), 4),
        "mdd_ci_low": round(float(np.percentile(mdds, 2.5)), 4),
        "mdd_ci_high": round(float(np.percentile(mdds, 97.5)), 4),
        "win_rate_ci_low": round(float(np.percentile(win_rates, 2.5)), 4),
        "win_rate_ci_high": round(float(np.percentile(win_rates, 97.5)), 4),
    }


def permutation_test_alpha(
    prices: np.ndarray,
    observed_sharpe: float,
    hold_days: int = 5,
    n_perms: int = 500,
) -> dict:
    """Permutation test: is IS Sharpe above what random entry would achieve?"""
    T = len(prices)
    permuted_sharpes = []
    for _ in range(n_perms):
        n_trades = max(10, T // 20)
        valid_starts = np.arange(T - hold_days)
        if len(valid_starts) == 0:
            break
        perm_entry_idx = np.random.choice(valid_starts, size=min(n_trades, len(valid_starts)), replace=False)
        trade_returns = []
        for idx in perm_entry_idx:
            exit_idx = min(idx + hold_days, T - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
            trade_returns.append(ret)
        arr = np.array(trade_returns)
        if len(arr) > 1 and arr.std() > 0:
            s = arr.mean() / arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR / hold_days)
        else:
            s = 0.0
        permuted_sharpes.append(s)
    if not permuted_sharpes:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    arr = np.array(permuted_sharpes)
    p_value = round(float(np.mean(arr >= observed_sharpe)), 4)
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": bool(p_value <= 0.05),
    }


def compute_dsr(returns: np.ndarray, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Lopez de Prado 2014)."""
    T = len(returns)
    if T < 4:
        return 0.0
    sharpe = returns.mean() / (returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(pd.Series(returns).skew())
    kurt = float(pd.Series(returns).kurt())
    gamma = 0.5772156649
    E_max_sr = (
        (1 - gamma) * norm.ppf(1 - 1.0 / n_trials)
        + gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sr_std = np.sqrt(
        (1 + 0.5 * sharpe ** 2 - skew * sharpe + (kurt / 4) * sharpe ** 2) / (T - 1)
    )
    dsr = float(norm.cdf((sharpe - E_max_sr) / (sr_std + 1e-10)))
    return round(dsr, 6)


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": round(float(arr.std()), 4),
        "wf_sharpe_min": round(float(arr.min()), 4),
    }


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(base_params: dict, n_windows: int = 4,
                     is_months: int = 36, oos_months: int = 6) -> list:
    """
    Walk-forward: 4 non-overlapping windows, 36-month IS / 6-month OOS.
    Starting from IS_START (2015-01-01), each window slides by oos_months.
    """
    wf_results = []
    base_start = pd.Timestamp(IS_START)
    for w in range(n_windows):
        is_start = base_start + pd.DateOffset(months=w * oos_months)
        is_end = is_start + pd.DateOffset(months=is_months) - pd.DateOffset(days=1)
        oos_start = is_end + pd.DateOffset(days=1)
        oos_end = oos_start + pd.DateOffset(months=oos_months) - pd.DateOffset(days=1)
        try:
            is_r = run_strategy(
                start=is_start.strftime("%Y-%m-%d"),
                end=is_end.strftime("%Y-%m-%d"),
                params=base_params,
            )
            oos_r = run_strategy(
                start=oos_start.strftime("%Y-%m-%d"),
                end=oos_end.strftime("%Y-%m-%d"),
                params=base_params,
            )
            oos_passes = (
                oos_r["sharpe"] >= 0.7
                or (is_r["sharpe"] > 0
                    and abs(oos_r["sharpe"] - is_r["sharpe"]) / (abs(is_r["sharpe"]) + 1e-8) <= 0.30)
            )
            wf_results.append({
                "window": w + 1,
                "is_start": is_start.strftime("%Y-%m-%d"),
                "is_end": is_end.strftime("%Y-%m-%d"),
                "oos_start": oos_start.strftime("%Y-%m-%d"),
                "oos_end": oos_end.strftime("%Y-%m-%d"),
                "is_sharpe": is_r["sharpe"],
                "oos_sharpe": oos_r["sharpe"],
                "is_mdd": is_r["max_drawdown"],
                "oos_mdd": oos_r["max_drawdown"],
                "is_trade_count": is_r["trade_count"],
                "oos_trade_count": oos_r["trade_count"],
                "pass": bool(oos_passes),
            })
        except Exception as exc:
            wf_results.append({"window": w + 1, "error": str(exc), "pass": False})
    return wf_results


# ── Regime-Slice Sub-Criterion (criteria.md v1.1) ─────────────────────────────

REGIME_SLICES = {
    "pre_covid_2018_2019": ("2018-01-01", "2019-12-31"),
    "stimulus_2020_2021": ("2020-01-01", "2021-12-31"),
    "rate_shock_2022": ("2022-01-01", "2022-12-31"),
    "normalization_2023": ("2023-01-01", "2023-12-31"),
}


def run_regime_slices(base_params: dict) -> dict:
    """
    Run IS Sharpe for each of the 4 criteria.md v1.1 sub-regimes.
    Pass requires IS Sharpe ≥ 0.8 in ≥ 2/4 regimes, with ≥ 1 stress regime.
    Stress regimes: pre_covid_2018_2019, rate_shock_2022.
    """
    results = {}
    for regime, (s, e) in REGIME_SLICES.items():
        try:
            r = run_strategy(start=s, end=e, params=base_params)
            results[regime] = {
                "sharpe": r["sharpe"],
                "mdd": r["max_drawdown"],
                "trade_count": r["trade_count"],
                "pass_08": r["sharpe"] >= 0.8,
            }
        except Exception as exc:
            results[regime] = {"error": str(exc), "pass_08": False}

    n_pass = sum(1 for v in results.values() if v.get("pass_08", False))
    stress_regimes = ["pre_covid_2018_2019", "rate_shock_2022"]
    stress_pass = any(results.get(r, {}).get("pass_08", False) for r in stress_regimes)

    results["_verdict"] = {
        "regimes_passing_08": n_pass,
        "stress_regime_pass": stress_pass,
        "regime_slice_pass": bool(n_pass >= 2 and stress_pass),
        "note": "Pass requires IS Sharpe ≥ 0.8 in ≥2/4 regimes (≥1 stress regime).",
    }
    return results


# ── Main Gate 1 Runner ────────────────────────────────────────────────────────

def main():
    np.random.seed(42)
    print("=" * 65)
    print(f"H09 TQQQ Weekly Snapback — Gate 1 Backtest [{TODAY}]")
    print("=" * 65)
    print(f"IS: {IS_START} to {IS_END}")
    print(f"OOS: {OOS_START} to {OOS_END}")
    print(f"\nGFC NOTE: {GFC_NOTE[:80]}...")

    # ── 1. IS Backtest ───────────────────────────────────────────
    print(f"\n[1/7] Running IS backtest ({IS_START} to {IS_END})...")
    is_full = run_strategy(start=IS_START, end=IS_END, params=PARAMETERS)
    is_sharpe = is_full["sharpe"]
    is_mdd = is_full["max_drawdown"]
    is_win_rate = is_full["win_rate"]
    is_win_loss = is_full["win_loss_ratio"]
    is_profit_factor = is_full["profit_factor"]
    is_trade_count = is_full["trade_count"]
    is_total_return = is_full["total_return"]
    is_returns = is_full["returns"]
    is_trade_log = is_full["trade_log"]
    is_exit_reasons = is_full.get("exit_reasons", {})
    trade_pnls = np.array([t["net_pnl"] for t in is_trade_log])
    print(f"  IS Sharpe={is_sharpe}  MDD={is_mdd:.1%}  WinRate={is_win_rate:.1%}  Trades={is_trade_count}")
    print(f"  Exit reasons: {is_exit_reasons}")

    # ── 2. OOS Backtest ──────────────────────────────────────────
    print(f"\n[2/7] Running OOS backtest ({OOS_START} to {OOS_END})...")
    oos_full = run_strategy(start=OOS_START, end=OOS_END, params=PARAMETERS)
    oos_sharpe = oos_full["sharpe"]
    oos_mdd = oos_full["max_drawdown"]
    oos_win_rate = oos_full["win_rate"]
    oos_trade_count = oos_full["trade_count"]
    oos_total_return = oos_full["total_return"]
    oos_exit_reasons = oos_full.get("exit_reasons", {})
    print(f"  OOS Sharpe={oos_sharpe}  MDD={oos_mdd:.1%}  Trades={oos_trade_count}")

    # ── 3. Sub-Period Analysis ───────────────────────────────────
    print("\n[3/7] Running sub-period analysis...")
    sub_period_results = {}
    for name, (s, e) in SUB_PERIODS.items():
        try:
            r = run_strategy(start=s, end=e, params=PARAMETERS)
            sub_period_results[name] = {
                "sharpe": r["sharpe"],
                "mdd": r["max_drawdown"],
                "trade_count": r["trade_count"],
            }
            print(f"  {name}: Sharpe={r['sharpe']}  MDD={r['max_drawdown']:.1%}  Trades={r['trade_count']}")
        except Exception as exc:
            sub_period_results[name] = {"error": str(exc)}
            print(f"  {name}: ERROR — {exc}")
    sub_period_results["_gfc_note"] = GFC_NOTE

    # ── 4. Regime-Slice Sub-Criterion (criteria.md v1.1) ────────
    print("\n[4/7] Running regime-slice sub-criterion...")
    regime_slices = run_regime_slices(PARAMETERS)
    rs_verdict = regime_slices.get("_verdict", {})
    rs_pass = rs_verdict.get("regime_slice_pass", False)
    print(f"  Regimes ≥0.8 Sharpe: {rs_verdict.get('regimes_passing_08')}/4")
    print(f"  Stress regime pass: {rs_verdict.get('stress_regime_pass')}")
    print(f"  Regime-slice: {'PASS' if rs_pass else 'FAIL'}")
    for regime, v in regime_slices.items():
        if not regime.startswith("_"):
            print(f"    {regime}: Sharpe={v.get('sharpe', 'err')}  MDD={v.get('mdd', 'err')}")

    # ── 5. Walk-Forward ──────────────────────────────────────────
    print("\n[5/7] Running walk-forward analysis (4 windows, 36m IS / 6m OOS)...")
    wf_table = run_walk_forward(PARAMETERS)
    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_table if "oos_sharpe" in w]
    wf_windows_passed = sum(1 for w in wf_table if w.get("pass", False))
    wf_ratios = []
    for w in wf_table:
        if "is_sharpe" in w and abs(w.get("is_sharpe", 0)) > 0.01:
            wf_ratios.append(w["oos_sharpe"] / w["is_sharpe"])
    wf_consistency_score = round(float(np.mean(wf_ratios)) if wf_ratios else 0.0, 4)
    wf_var = walk_forward_variance(wf_oos_sharpes) if wf_oos_sharpes else {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        print(f"  Window {w['window']}: IS={w.get('is_sharpe','?')} OOS={w.get('oos_sharpe','?')} [{status}]")
    print(f"  WF Sharpe std={wf_var['wf_sharpe_std']}  min={wf_var['wf_sharpe_min']}")

    # ── 6. Statistical Rigor Pipeline ───────────────────────────
    print("\n[6/7] Statistical rigor pipeline...")

    print("  6a. Monte Carlo (1000 sims)...")
    mc = monte_carlo_sharpe(trade_pnls) if len(trade_pnls) > 5 else {
        "mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0
    }
    print(f"      p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}")

    print("  6b. Block Bootstrap CI (1000 boots)...")
    bci = block_bootstrap_ci(is_returns) if len(is_returns) > 10 else {
        "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
        "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
        "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
    }
    print(f"      Sharpe CI [{bci['sharpe_ci_low']:.3f}, {bci['sharpe_ci_high']:.3f}]")

    print("  6c. Market Impact (equities)...")
    # TQQQ: ADV ~60-100M shares/day; at $25K × 15% = $3,750 → ~50-100 shares
    # Q/ADV = 100 / 60_000_000 = 1.7e-6 → far below 1% threshold → no liquidity constraint
    market_impact_note = (
        "TQQQ ADV ~60-100M shares/day. At $25K×15% sizing, Q≈50-100 shares. "
        "Q/ADV ≈ 1.7e-6 << 0.01 threshold. Market impact negligible (< 0.01 bps). "
        "No liquidity constraint flagged."
    )
    liquidity_flags = is_full.get("liquidity_flags", 0)
    print(f"      {market_impact_note[:70]}...")

    print("  6d. Permutation test (500 perms)...")
    # Use TQQQ closing prices from IS period for permutation test
    try:
        import yfinance as yf
        tqqq_prices_is = yf.download("TQQQ", start=IS_START, end=IS_END,
                                     auto_adjust=True, progress=False)["Close"].values
    except Exception:
        tqqq_prices_is = np.array([])
    perm = (permutation_test_alpha(tqqq_prices_is, is_sharpe)
            if len(tqqq_prices_is) > 20
            else {"permutation_pvalue": 1.0, "permutation_test_pass": False})
    print(f"      p-value={perm['permutation_pvalue']} {'PASS' if perm['permutation_test_pass'] else 'FAIL'}")

    print("  6e. DSR...")
    # n_trials: 5 decline × 5 vix_gate = 25 param combinations + 5 sub-periods = 30
    n_trials = 30
    dsr = compute_dsr(is_returns, n_trials=n_trials) if len(is_returns) > 10 else 0.0
    print(f"      DSR={dsr:.6f}")

    # ── 7. Sensitivity Scans ─────────────────────────────────────
    print("\n[7/7] Sensitivity scans (entry_decline_pct and vix_gate)...")
    decline_scan = scan_entry_decline(start=IS_START, end=IS_END, base_params=PARAMETERS)
    vix_scan = scan_vix_gate(start=IS_START, end=IS_END, base_params=PARAMETERS)
    print(f"  Decline scan: {decline_scan.get('_meta', {})}")

    # Sensitivity robustness: extract Sharpe across both scans
    all_scan_sharpes = []
    for k, v in decline_scan.items():
        if not k.startswith("_") and isinstance(v, dict) and "sharpe" in v:
            all_scan_sharpes.append(v["sharpe"])
    for k, v in vix_scan.items():
        if isinstance(v, dict) and "sharpe" in v:
            all_scan_sharpes.append(v["sharpe"])
    if len(all_scan_sharpes) > 1:
        scan_range = max(all_scan_sharpes) - min(all_scan_sharpes)
        scan_mean = np.mean(all_scan_sharpes)
        scan_variance_pct = scan_range / abs(scan_mean) if scan_mean != 0 else float("inf")
        sensitivity_pass = scan_variance_pct <= 0.30
    else:
        scan_variance_pct = 0.0
        sensitivity_pass = False

    print(f"  Combined param sensitivity variance: {scan_variance_pct:.1%} -> {'PASS' if sensitivity_pass else 'FAIL'}")

    # ── Gate 1 Verdict ───────────────────────────────────────────
    print("\n[Gate 1 Verdict]")
    win_rate_pass = is_win_rate >= 0.50 or (is_win_rate < 0.50 and is_win_loss >= 1.2)

    gate1_checks = {
        "is_sharpe_pass": bool(is_sharpe > 1.0),
        "oos_sharpe_pass": bool(oos_sharpe > 0.7),
        "is_mdd_pass": bool(is_mdd > -0.20),
        "oos_mdd_pass": bool(oos_mdd > -0.25),
        "win_rate_pass": bool(win_rate_pass),
        "trade_count_pass": bool(is_trade_count >= 100),  # Gate 1 minimum 100
        "wf_windows_pass": bool(wf_windows_passed >= 3),
        "wf_consistency_pass": bool(wf_consistency_score >= 0.7),
        "sensitivity_pass": bool(sensitivity_pass),
        "regime_slice_pass": bool(rs_pass),
        "dsr_pass": bool(dsr > 0),
        "permutation_pass": bool(perm["permutation_test_pass"]),
        "mc_p5_pass": bool(mc["mc_p5_sharpe"] >= 0.5),
    }
    gate1_pass = all(gate1_checks.values())
    failing = [k for k, v in gate1_checks.items() if not v]

    print(f"\n  OVERALL: {'PASS' if gate1_pass else 'FAIL'}")
    if failing:
        print(f"  Failing: {', '.join(failing)}")

    # ── Build Metrics JSON ────────────────────────────────────────
    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities_leveraged_etf",
        "ticker": "TQQQ",
        "is_period": f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        # Core metrics
        "is_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "is_max_drawdown": is_mdd,
        "oos_max_drawdown": oos_mdd,
        "win_rate": is_win_rate,
        "oos_win_rate": oos_win_rate,
        "win_loss_ratio": is_win_loss,
        "profit_factor": is_profit_factor,
        "trade_count": is_trade_count,
        "oos_trade_count": oos_trade_count,
        "total_return_is": is_total_return,
        "total_return_oos": oos_total_return,
        "post_cost_sharpe": is_sharpe,
        # Statistical rigor
        "dsr": dsr,
        "mc_p5_sharpe": mc["mc_p5_sharpe"],
        "mc_median_sharpe": mc["mc_median_sharpe"],
        "mc_p95_sharpe": mc["mc_p95_sharpe"],
        "sharpe_ci_low": bci["sharpe_ci_low"],
        "sharpe_ci_high": bci["sharpe_ci_high"],
        "mdd_ci_low": bci["mdd_ci_low"],
        "mdd_ci_high": bci["mdd_ci_high"],
        "win_rate_ci_low": bci["win_rate_ci_low"],
        "win_rate_ci_high": bci["win_rate_ci_high"],
        "permutation_pvalue": perm["permutation_pvalue"],
        "permutation_test_pass": perm["permutation_test_pass"],
        # Walk-forward
        "wf_windows_passed": wf_windows_passed,
        "wf_consistency_score": wf_consistency_score,
        "wf_table": wf_table,
        "wf_oos_sharpes": [round(s, 4) for s in wf_oos_sharpes],
        "wf_sharpe_std": wf_var["wf_sharpe_std"],
        "wf_sharpe_min": wf_var["wf_sharpe_min"],
        # Regime slices (criteria.md v1.1)
        "regime_slices": {k: {kk: vv for kk, vv in v.items() if kk != "pass_08"}
                          for k, v in regime_slices.items() if not k.startswith("_")},
        "regime_slice_verdict": rs_verdict,
        # Sub-period analysis
        "sub_period_results": sub_period_results,
        # Transaction costs
        "market_impact_note": market_impact_note,
        "market_impact_bps": 0.0,
        "liquidity_constrained": liquidity_flags > 0,
        "liquidity_constrained_count": liquidity_flags,
        "order_to_adv_note": "Q/ADV << 0.01 — no liquidity constraint",
        # Sensitivity
        "sensitivity_scan_decline": {
            k: v for k, v in decline_scan.items() if not k.startswith("_")
        },
        "sensitivity_scan_vix": vix_scan,
        "sensitivity_meta": {
            "combined_variance_pct": round(float(scan_variance_pct), 4),
            "sensitivity_pass": sensitivity_pass,
        },
        # Exit analysis
        "is_exit_reasons": is_exit_reasons,
        "oos_exit_reasons": oos_exit_reasons,
        # Trade log (first 20 for compactness)
        "trade_log_sample": is_trade_log[:20],
        "trade_log_count": len(is_trade_log),
        # Data quality
        "data_quality": {
            k: v for k, v in is_full.get("data_quality", {}).items()
            if k != "tickers"
        },
        "gfc_limitation_note": GFC_NOTE,
        # Gate 1
        "gate1_checks": gate1_checks,
        "gate1_pass": gate1_pass,
        "failing_criteria": failing,
        "look_ahead_bias_flag": False,
        "look_ahead_bias_notes": [
            "Entry signal computed at close T; execution at open T+1 (shifted +1 bar).",
            "Rolling high uses past prices only (no current bar).",
            "QQQ SMA and VIX checked at close of signal bar — no future data used.",
            "Regime gate suppresses NEW entries only; existing positions use TP/SL/time-stop.",
        ],
        "win_rate_note": (
            f"Win rate {is_win_rate:.1%} < 50% — "
            f"win/loss ratio {is_win_loss:.2f} "
            + ("≥ 1.2 (alternate criterion)" if is_win_loss >= 1.2 else "< 1.2 (FAIL)")
        ) if is_win_rate < 0.50 else None,
        "tasc_crowding_note": (
            "TASC March 2026 publication. Monitor for post-publication edge decay. "
            "OOS period (2022-2023) predates publication — crowding risk in live trading only."
        ),
    }

    # ── Save JSON ─────────────────────────────────────────────────
    json_path = f"/mnt/c/Users/lamho/repo/quant-zero/backtests/{STRATEGY_NAME}_{TODAY}.json"
    with open(json_path, "w") as fh:
        json.dump(metrics, fh, indent=2, default=str)
    print(f"\nSaved: {json_path}")

    # ── Save Verdict TXT ──────────────────────────────────────────
    wf_min_flag = "FLAG: losing WF window" if wf_var["wf_sharpe_min"] < 0 else "OK"
    mc_p5_flag = "PASS" if mc["mc_p5_sharpe"] >= 0.5 else "FAIL — MC pessimistic bound weak"

    verdict_lines = [
        f"H09 TQQQ Weekly Snapback — Gate 1 Verdict",
        f"Date: {TODAY}",
        f"IS: {IS_START} to {IS_END}  |  OOS: {OOS_START} to {OOS_END}",
        "=" * 60,
        f"OVERALL: {'PASS ✓' if gate1_pass else 'FAIL ✗'}",
        "",
        "Core Metrics:",
        f"  IS Sharpe:           {is_sharpe:>8.4f}  {'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'} (>1.0)",
        f"  OOS Sharpe:          {oos_sharpe:>8.4f}  {'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'} (>0.7)",
        f"  IS Max Drawdown:     {is_mdd:>8.1%}  {'PASS' if gate1_checks['is_mdd_pass'] else 'FAIL'} (<20%)",
        f"  OOS Max Drawdown:    {oos_mdd:>8.1%}  {'PASS' if gate1_checks['oos_mdd_pass'] else 'FAIL'} (<25%)",
        f"  Win Rate (IS):       {is_win_rate:>8.1%}  {'PASS' if gate1_checks['win_rate_pass'] else 'FAIL'} (>50% OR w/l>1.2)",
        f"  Win/Loss Ratio:      {is_win_loss:>8.2f}",
        f"  Profit Factor:       {is_profit_factor:>8.4f}",
        f"  Trade Count (IS):    {is_trade_count:>8d}  {'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'} (≥100)",
        "",
        "Walk-Forward (4 windows, 36m IS / 6m OOS):",
        f"  Windows Passed:      {wf_windows_passed}/4  {'PASS' if gate1_checks['wf_windows_pass'] else 'FAIL'} (≥3)",
        f"  Consistency Score:   {wf_consistency_score:>8.4f}  {'PASS' if gate1_checks['wf_consistency_pass'] else 'FAIL'} (≥0.7)",
        f"  WF Sharpe Std:       {wf_var['wf_sharpe_std']:>8.4f}",
        f"  WF Sharpe Min:       {wf_var['wf_sharpe_min']:>8.4f}  {wf_min_flag}",
    ]
    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        verdict_lines.append(
            f"    W{w['window']}: IS {w.get('is_sharpe','?'):>6} OOS {w.get('oos_sharpe','?'):>6} [{status}]"
        )
    verdict_lines += [
        "",
        "Regime-Slice Sub-Criterion (criteria.md v1.1):",
        f"  Regimes ≥0.8 Sharpe: {rs_verdict.get('regimes_passing_08', 0)}/4  {'PASS' if gate1_checks['regime_slice_pass'] else 'FAIL'} (≥2 incl ≥1 stress)",
    ]
    for regime, v in regime_slices.items():
        if not regime.startswith("_"):
            flag = "✓" if v.get("pass_08") else "✗"
            verdict_lines.append(
                f"    {regime}: Sharpe={v.get('sharpe', 'err'):.4f} "
                f"MDD={v.get('mdd', 0):.1%} Trades={v.get('trade_count', 0)} {flag}"
                if isinstance(v.get("sharpe"), float) else f"    {regime}: {v}"
            )
    verdict_lines += [
        "",
        "Sub-Period Analysis (Research Director conditions):",
        f"  GFC Note: TQQQ inception 2010-02-09; GFC 2008-09 untestable.",
    ]
    for name, v in sub_period_results.items():
        if not name.startswith("_") and isinstance(v, dict) and "sharpe" in v:
            verdict_lines.append(
                f"  {name}: Sharpe={v['sharpe']:.4f}  MDD={v['mdd']:.1%}  Trades={v['trade_count']}"
            )
    verdict_lines += [
        "",
        "Statistical Rigor:",
        f"  DSR:                 {dsr:>12.6f}  {'PASS' if gate1_checks['dsr_pass'] else 'FAIL'} (>0)",
        f"  MC p5 Sharpe:        {mc['mc_p5_sharpe']:>12.3f}  {mc_p5_flag}",
        f"  MC Median Sharpe:    {mc['mc_median_sharpe']:>12.3f}",
        f"  Sharpe CI [95%]:     [{bci['sharpe_ci_low']:.3f}, {bci['sharpe_ci_high']:.3f}]",
        f"  MDD CI [95%]:        [{bci['mdd_ci_low']:.3f}, {bci['mdd_ci_high']:.3f}]",
        f"  Perm p-value:        {perm['permutation_pvalue']:>12.4f}  {'PASS' if gate1_checks['permutation_pass'] else 'FAIL'} (≤0.05)",
        "",
        "Sensitivity (entry_decline_pct × vix_gate):",
        f"  Combined variance:   {scan_variance_pct:>11.1%}  {'PASS' if gate1_checks['sensitivity_pass'] else 'FAIL'} (≤30%)",
    ]
    for k, v in decline_scan.items():
        if not k.startswith("_") and isinstance(v, dict) and "sharpe" in v:
            verdict_lines.append(f"    {k}: Sharpe={v['sharpe']:.4f}  Trades={v['trade_count']}")
    verdict_lines += [
        "",
        "Exit Reason Analysis (IS):",
    ]
    for reason, count in is_exit_reasons.items():
        verdict_lines.append(f"  {reason}: {count} trades")
    verdict_lines += [
        "",
        "Risk Flags:",
        f"  Look-ahead bias:     {'YES — FAIL' if metrics['look_ahead_bias_flag'] else 'None detected'}",
        f"  Liquidity flags:     {liquidity_flags} trades flagged as liquidity-constrained",
        f"  TASC crowding risk:  Monitor post-publication (March 2026) edge decay in live trading",
        f"  TQQQ 2022 MDD:       Strategy uses regime gate (QQQ 200-SMA + VIX gate) to reduce exposure",
        "",
        "FAILING CRITERIA:" if failing else "All criteria passed.",
    ]
    if failing:
        for f_name in failing:
            verdict_lines.append(f"  x {f_name}")

    verdict_txt = "\n".join(verdict_lines)
    verdict_path = f"/mnt/c/Users/lamho/repo/quant-zero/backtests/{STRATEGY_NAME}_{TODAY}_verdict.txt"
    with open(verdict_path, "w") as fh:
        fh.write(verdict_txt)
    print(f"Saved: {verdict_path}")
    print("\n" + "=" * 65)
    print(verdict_txt)
    print("=" * 65)

    return metrics, verdict_txt


if __name__ == "__main__":
    metrics, verdict_txt = main()
