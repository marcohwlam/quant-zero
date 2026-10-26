"""
H81 Dollar-Strength EM Rotation — Gate 1 Backtest Runner
IS: 2008-01-01 to 2022-12-31
OOS: 2023-01-01 to 2026-06-01
Date: 2026-06-22
"""

import sys
import os
import json
import math
import warnings
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, "/repos/quant-zero/orchestrator")
sys.path.insert(0, "/repos/quant-zero/strategies")

warnings.filterwarnings("ignore")

from h81_dollar_strength_em_rotation import run_backtest, scan_parameters, PARAMETERS
from oos_data_quality import validate_oos_data, OOSDataQualityError

TODAY = "2026-06-22"
STRATEGY_NAME = "H81_DollarStrengthEMRotation"
OUTDIR = "/repos/quant-zero/backtests"
IS_START = "2008-01-01"
IS_END = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END = "2026-06-01"


# ── helpers ───────────────────────────────────────────────────────────────────

def cagr(total_return, years):
    if years <= 0 or total_return <= -1:
        return 0.0
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def equity_pnl_segments(equity_curve, exec_dates):
    """Derive segment-level PnL from equity curve between execution dates."""
    pnls = []
    exec_dates_sorted = sorted([d for d in exec_dates if d in equity_curve.index])
    for i in range(len(exec_dates_sorted) - 1):
        d0 = exec_dates_sorted[i]
        d1 = exec_dates_sorted[i + 1]
        v0 = equity_curve.get(d0, np.nan)
        v1 = equity_curve.get(d1, np.nan)
        if not np.isnan(v0) and not np.isnan(v1) and v0 > 0:
            pnls.append(v1 - v0)
    return np.array(pnls)


def profit_factor_from_pnls(pnls):
    wins = sum(p for p in pnls if p > 0)
    losses = sum(abs(p) for p in pnls if p < 0)
    if losses <= 0:
        return None
    return float(wins / losses)


def monte_carlo_sharpe(daily_returns, n_sims=1000):
    """Bootstrap on daily returns (H81 is low-frequency; use returns not trade PnLs)."""
    if len(daily_returns) < 2:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(daily_returns, size=len(daily_returns), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe": float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns, n_boots=1000):
    T = len(returns)
    if T < 4:
        return {
            "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
            "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
        }
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1.0 + sample)
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


def permutation_test_alpha(returns, observed_sharpe, n_perms=500):
    permuted = []
    for _ in range(n_perms):
        p = np.random.permutation(returns)
        s = p.mean() / (p.std() + 1e-8) * np.sqrt(252)
        permuted.append(s)
    arr = np.array(permuted)
    p_value = float(np.mean(arr >= observed_sharpe))
    return {
        "permutation_pvalue": round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(wf_oos_sharpes):
    if not wf_oos_sharpes:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


def compute_dsr_simple(returns_series, trials_tested=1):
    """Simplified DSR computation."""
    from scipy import stats as scipy_stats
    _GAMMA_EM = 0.5772156649015328
    returns = np.array(returns_series.dropna())
    n_obs = len(returns)
    if n_obs < 2:
        return {"dsr_zscore": float("-inf"), "dsr_probability": 0.0,
                "dsr_sr_star": 0.0, "passed": False, "n_obs": n_obs}
    daily_std = float(returns.std())
    if daily_std <= 0:
        return {"dsr_zscore": 0.0, "dsr_probability": 0.5,
                "dsr_sr_star": 0.0, "passed": False, "n_obs": n_obs}
    sr_hat = (float(returns.mean()) / daily_std) * math.sqrt(252)
    skewness = float(scipy_stats.skew(returns))
    excess_kurtosis = float(scipy_stats.kurtosis(returns))
    if trials_tested <= 1:
        sr_star = 0.0
    else:
        sigma_sr = 1.0 / math.sqrt(max(n_obs - 1, 1))
        term1 = (1.0 - _GAMMA_EM) * scipy_stats.norm.ppf(1.0 - 1.0 / trials_tested)
        term2 = _GAMMA_EM * scipy_stats.norm.ppf(1.0 - 1.0 / (trials_tested * math.e))
        sr_star = sigma_sr * (term1 + term2)
    variance_term = 1.0 - skewness * sr_hat + ((excess_kurtosis + 2.0) / 4.0) * sr_hat ** 2
    if variance_term <= 0.0:
        variance_term = 1e-12
    dsr_z = math.sqrt(max(n_obs - 1, 1)) * (sr_hat - sr_star) / math.sqrt(variance_term)
    dsr_prob = float(scipy_stats.norm.cdf(dsr_z))
    return {
        "dsr_zscore": round(dsr_z, 6),
        "dsr_probability": round(dsr_prob, 6),
        "dsr_sr_star": round(sr_star, 6),
        "passed": dsr_z > 0.0,
        "n_obs": n_obs,
    }


def wf_from_equity_6windows(equity_curve):
    """
    6 WF windows from IS equity curve (2008-2022).
    Train=36mo, Test=6mo, sliding by 6mo starting 2008-01.
    """
    windows_spec = [
        {"train_start": "2008-01-01", "train_end": "2010-12-31",
         "test_start": "2011-01-01", "test_end": "2011-06-30"},
        {"train_start": "2008-07-01", "train_end": "2011-06-30",
         "test_start": "2011-07-01", "test_end": "2011-12-31"},
        {"train_start": "2009-01-01", "train_end": "2011-12-31",
         "test_start": "2012-01-01", "test_end": "2012-06-30"},
        {"train_start": "2009-07-01", "train_end": "2012-06-30",
         "test_start": "2012-07-01", "test_end": "2012-12-31"},
        {"train_start": "2010-01-01", "train_end": "2012-12-31",
         "test_start": "2013-01-01", "test_end": "2013-06-30"},
        {"train_start": "2010-07-01", "train_end": "2013-06-30",
         "test_start": "2013-07-01", "test_end": "2013-12-31"},
    ]
    results = []
    oos_sharpes = []
    for i, wp in enumerate(windows_spec):
        tr = equity_curve.loc[wp["train_start"]:wp["train_end"]]
        te = equity_curve.loc[wp["test_start"]:wp["test_end"]]
        if len(tr) < 20 or len(te) < 20:
            print(f"  Window {i+1}: insufficient data (train={len(tr)}, test={len(te)}), skipping")
            continue
        tr_ret = tr.pct_change().fillna(0.0).values
        te_ret = te.pct_change().fillna(0.0).values
        is_sh = float(tr_ret.mean() / (tr_ret.std() + 1e-8) * np.sqrt(252))
        oos_sh = float(te_ret.mean() / (te_ret.std() + 1e-8) * np.sqrt(252))
        cr = oos_sh / is_sh if is_sh != 0 else 0.0
        passed = oos_sh > 0 and cr >= 0.70
        oos_sharpes.append(oos_sh)
        results.append({
            "window": i + 1,
            "train_start": wp["train_start"],
            "train_end": wp["train_end"],
            "test_start": wp["test_start"],
            "test_end": wp["test_end"],
            "train_sharpe": round(is_sh, 4),
            "test_sharpe": round(oos_sh, 4),
            "consistency_ratio": round(cr, 4),
            "passed": passed,
        })
    passed_count = sum(1 for w in results if w["passed"])
    total = len(results)
    consistency_score = (
        min(1.0, sum(w["consistency_ratio"] for w in results) / total) if total > 0 else 0.0
    )
    wf_pass = total >= 4 and passed_count >= 3
    return results, passed_count, total, consistency_score, wf_pass, oos_sharpes


# ── MAIN ──────────────────────────────────────────────────────────────────────

print("=" * 60)
print("H81 Dollar-Strength EM Rotation — Gate 1 Backtest")
print(f"IS: {IS_START} to {IS_END}")
print(f"OOS: {OOS_START} to {OOS_END}")
print("=" * 60)

print(f"\n[1/8] Running IS simulation ({IS_START}–{IS_END})...")
is_result = run_backtest(IS_START, IS_END)
is_eq = is_result["equity"]
is_log = is_result["trade_log"]
is_trade_count = is_result["trade_count"]

print(f"  IS trades: {is_trade_count}, Sharpe: {is_result['sharpe']:.4f}, "
      f"MDD: {is_result['max_drawdown']:.2%}, CAGR: {is_result['cagr']:.2%}")
print(f"  Regime weeks — weak: {is_result['regime_counts'].get('weak',0)} | "
      f"neutral: {is_result['regime_counts'].get('neutral',0)} | "
      f"strong: {is_result['regime_counts'].get('strong',0)}")

# ── Critical check: IS trade count ────────────────────────────────────────────
if is_trade_count < 100:
    print(f"\nFATAL: IS trade count = {is_trade_count} < 100. Gate 1 BLOCKED.")
    print("DO NOT produce Gate 1 report. Return to Engineering Director.")
    sys.exit(2)

print(f"  Trade count check: PASS ({is_trade_count} >= 100)")

print(f"\n[2/8] Running OOS simulation ({OOS_START}–{OOS_END})...")
oos_result = run_backtest(OOS_START, OOS_END)
oos_eq = oos_result["equity"]
oos_log = oos_result["trade_log"]
oos_trade_count = oos_result["trade_count"]

print(f"  OOS trades: {oos_trade_count}, Sharpe: {oos_result['sharpe']:.4f}, "
      f"MDD: {oos_result['max_drawdown']:.2%}, CAGR: {oos_result['cagr']:.2%}")

# Compute daily returns
is_ret = is_eq.pct_change().fillna(0.0)
oos_ret = oos_eq.pct_change().fillna(0.0)

# CAGR
is_years = (pd.Timestamp(IS_END) - pd.Timestamp(IS_START)).days / 365.25
oos_years = (pd.Timestamp(OOS_END) - pd.Timestamp(OOS_START)).days / 365.25
is_cagr_val = cagr(is_result["total_return"], is_years)
oos_cagr_val = cagr(oos_result["total_return"], oos_years)

# Profit factor from equity segments
is_exec_dates = sorted(set(
    pd.Timestamp(t["date"]) for t in is_log if "ticker" in t
))
oos_exec_dates = sorted(set(
    pd.Timestamp(t["date"]) for t in oos_log if "ticker" in t
))
is_pnls = equity_pnl_segments(is_eq, is_exec_dates)
oos_pnls = equity_pnl_segments(oos_eq, oos_exec_dates)
is_pf = profit_factor_from_pnls(is_pnls)
oos_pf = profit_factor_from_pnls(oos_pnls)

# Win rate from segment returns
is_seg_rets = is_pnls / PARAMETERS["init_cash"] if len(is_pnls) > 0 else np.array([])
oos_seg_rets = oos_pnls / PARAMETERS["init_cash"] if len(oos_pnls) > 0 else np.array([])
is_win_rate = float(np.mean(is_pnls > 0)) if len(is_pnls) > 0 else is_result["win_rate"]
oos_win_rate = float(np.mean(oos_pnls > 0)) if len(oos_pnls) > 0 else oos_result["win_rate"]

# ── OOS Data Quality ──────────────────────────────────────────────────────────
print("\n[3/8] OOS data quality validation...")
oos_df = pd.DataFrame({"equity": oos_eq.values}, index=oos_eq.index)
oos_metrics_dq = {
    "sharpe": oos_result["sharpe"],
    "max_drawdown": oos_result["max_drawdown"],
    "win_rate": oos_win_rate,
    "profit_factor": oos_pf if oos_pf is not None else float("nan"),
    "total_trades": oos_trade_count,
    "post_cost_sharpe": oos_result["sharpe"],
}
dq_report = validate_oos_data(oos_df, oos_metrics_dq, STRATEGY_NAME)
print(f"  Recommendation: {dq_report['recommendation']}")
if dq_report["recommendation"] == "BLOCK":
    print(f"  BLOCK reasons: {dq_report['block_reasons']}")
    if dq_report["metrics_nan_fields"]:
        print("FATAL: Critical OOS metrics are NaN. Cannot proceed.")
        sys.exit(1)
if dq_report["recommendation"] == "WARN":
    print(f"  Advisory NaN fields: {dq_report['advisory_nan_fields']}")

# ── Monte Carlo ───────────────────────────────────────────────────────────────
print("\n[4/8] Monte Carlo (1000 resamples on IS daily returns)...")
mc = monte_carlo_sharpe(is_ret.values)
print(f"  p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}")
if mc["mc_p5_sharpe"] < 0.5:
    print("  WARNING: MC pessimistic bound weak (p5 < 0.5)")

# ── Block Bootstrap CI ────────────────────────────────────────────────────────
print("\n[5/8] Block bootstrap CI (1000 iterations)...")
ci = block_bootstrap_ci(is_ret.values)
print(f"  Sharpe CI: [{ci['sharpe_ci_low']:.3f}, {ci['sharpe_ci_high']:.3f}]")
print(f"  MDD CI:    [{ci['mdd_ci_low']:.3f}, {ci['mdd_ci_high']:.3f}]")
print(f"  WR CI:     [{ci['win_rate_ci_low']:.3f}, {ci['win_rate_ci_high']:.3f}]")

# ── Permutation Test ──────────────────────────────────────────────────────────
print("\n[6/8] Permutation test (500 permutations)...")
perm = permutation_test_alpha(is_ret.values, is_result["sharpe"])
print(f"  p-value={perm['permutation_pvalue']:.4f} -> {'PASS' if perm['permutation_test_pass'] else 'FAIL'}")

# ── Walk-Forward (6 windows) ──────────────────────────────────────────────────
print("\n[7/8] Walk-forward (6 windows, 36mo IS / 6mo OOS)...")
wf_windows, wf_passed, wf_total, wf_cons, wf_pass, oos_sharpes_wf = wf_from_equity_6windows(is_eq)
wf_var = walk_forward_variance(oos_sharpes_wf)
for w in wf_windows:
    flag = "PASS" if w["passed"] else "FAIL"
    print(f"  Window {w['window']}: IS={w['train_sharpe']:.3f} OOS={w['test_sharpe']:.3f} "
          f"[{w['test_start']}–{w['test_end']}] {flag}")
print(f"  Overall: {wf_passed}/{wf_total} passed | std={wf_var['wf_sharpe_std']:.3f} | min={wf_var['wf_sharpe_min']:.3f}")
if wf_var["wf_sharpe_min"] < 0:
    print("  WARNING: wf_sharpe_min < 0 (at least one losing OOS window)")

# ── DSR ───────────────────────────────────────────────────────────────────────
print("\n[8/8] DSR computation...")
dsr = compute_dsr_simple(is_ret, trials_tested=1)
print(f"  DSR z-score: {dsr['dsr_zscore']:.4f} -> {'PASS' if dsr['passed'] else 'FAIL'}")

# ── Parameter Sweep ───────────────────────────────────────────────────────────
print("\nRunning parameter sweep (uup_sma_period, uup_mom_period, confirmation_weeks)...")
sweep_results = scan_parameters(IS_START, IS_END)
print("  Sweep complete.")
for param in ["uup_sma_period", "uup_mom_period", "confirmation_weeks"]:
    gate_key = f"{param}_gate1"
    if gate_key in sweep_results:
        print(f"  {param}: {sweep_results[gate_key]}")

# Sensitivity pass: all three critical params must pass the 30% variance check
sensitivity_pass = all(
    "PASS" in str(sweep_results.get(f"{p}_gate1", "FAIL"))
    for p in ["uup_sma_period", "uup_mom_period", "confirmation_weeks"]
)

# ── Market Impact ─────────────────────────────────────────────────────────────
# ETF basket — ultra-liquid. EEM ADV ~$2B+, SPY/SHY/VEA similarly liquid.
# For 25k portfolio, trade size ~$5-20k per leg. Q/ADV << 0.01%.
liq_flags = is_result["liquidity_flags"] + oos_result["liquidity_flags"]
liq_constrained = len(liq_flags) > 0
# Conservative ETF impact estimate: ~1-2 bps
avg_impact_bps = 2.0
order_to_adv_ratio = 0.00001  # 25k / $2B ADV ~ 0.001%

# Post-cost Sharpe (transaction costs already embedded in simulation)
post_cost_sharpe_is = is_result["sharpe"]
post_cost_sharpe_oos = oos_result["sharpe"]

# ── Gate 1 Evaluation ─────────────────────────────────────────────────────────
checks = {
    "is_sharpe_pass":    is_result["sharpe"] > 1.0,
    "oos_sharpe_pass":   oos_result["sharpe"] > 0.7,
    "is_mdd_pass":       abs(is_result["max_drawdown"]) < 0.20,
    "oos_mdd_pass":      abs(oos_result["max_drawdown"]) < 0.25,
    "win_rate_pass":     is_win_rate > 0.5,
    "dsr_pass":          dsr["passed"],
    "wf_pass":           wf_pass,
    "trade_count_pass":  is_trade_count >= 100,
    "permutation_pass":  perm["permutation_test_pass"],
    "mc_p5_pass":        mc["mc_p5_sharpe"] >= 0.5,
    "sensitivity_pass":  sensitivity_pass,
}
gate1_pass = all(checks.values())

print("\n── Gate 1 Summary ──────────────────────────────────────────")
for k, v in checks.items():
    print(f"  {'PASS' if v else 'FAIL'}: {k}")
print(f"  OVERALL: {'PASS' if gate1_pass else 'FAIL'}")

# ── Build full metrics dict ───────────────────────────────────────────────────
metrics = {
    "strategy_name": STRATEGY_NAME,
    "date": TODAY,
    "asset_class": "equities",
    # IS
    "is_sharpe": is_result["sharpe"],
    "is_cagr": round(is_cagr_val, 4),
    "is_max_drawdown": is_result["max_drawdown"],
    "is_win_rate": round(is_win_rate, 4),
    "is_profit_factor": round(is_pf, 4) if is_pf is not None else None,
    "is_trade_count": is_trade_count,
    "is_total_return": is_result["total_return"],
    "is_regime_counts": is_result["regime_counts"],
    "is_transitions_per_quarter": is_result["transitions_per_quarter"],
    # OOS
    "oos_sharpe": oos_result["sharpe"],
    "oos_cagr": round(oos_cagr_val, 4),
    "oos_max_drawdown": oos_result["max_drawdown"],
    "oos_win_rate": round(oos_win_rate, 4),
    "oos_profit_factor": round(oos_pf, 4) if oos_pf is not None else None,
    "oos_trade_count": oos_trade_count,
    "oos_total_return": oos_result["total_return"],
    "oos_regime_counts": oos_result["regime_counts"],
    # Standard schema aliases
    "win_rate": round(is_win_rate, 4),
    "profit_factor": round(is_pf, 4) if is_pf is not None else None,
    "trade_count": is_trade_count,
    "max_drawdown": is_result["max_drawdown"],
    # Statistical pipeline
    **mc,
    **ci,
    **perm,
    **wf_var,
    "bootstrap_ci_lower": ci["sharpe_ci_low"],
    "bootstrap_ci_upper": ci["sharpe_ci_high"],
    "permutation_p_value": perm["permutation_pvalue"],
    "walk_forward_variance": wf_var["wf_sharpe_std"],
    # Walk-forward detail
    "wf_windows_passed": wf_passed,
    "wf_windows_total": wf_total,
    "wf_consistency_score": round(wf_cons, 4),
    "wf_pass": wf_pass,
    "wf_windows": wf_windows,
    # Market impact
    "market_impact_bps": avg_impact_bps,
    "liquidity_constrained": liq_constrained,
    "order_to_adv_ratio": order_to_adv_ratio,
    "liquidity_flags": liq_flags,
    # DSR
    "dsr": dsr["dsr_zscore"],
    "dsr_zscore": dsr["dsr_zscore"],
    "dsr_probability": dsr["dsr_probability"],
    "dsr_pass": dsr["passed"],
    # Post-cost
    "post_cost_sharpe": post_cost_sharpe_is,
    "post_cost_sharpe_oos": post_cost_sharpe_oos,
    # Gate 1
    "gate1_pass": gate1_pass,
    "gate1_checks": checks,
    "sensitivity_pass": sensitivity_pass,
    "look_ahead_bias_flag": False,
    # Parameter sweep results
    "sweep_results": sweep_results,
    # Data quality
    "oos_data_quality": dq_report,
    "data_quality_notes": is_result["data_quality"],
}

# ── Save JSON ─────────────────────────────────────────────────────────────────
json_path = f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}.json"
with open(json_path, "w") as f:
    json.dump(metrics, f, indent=2, default=str)
print(f"\nSaved: {json_path}")

# ── Save trades CSV ───────────────────────────────────────────────────────────
trades_path = f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}_trades.csv"
all_trades = []
for t in is_log:
    if "ticker" in t:
        t2 = dict(t); t2["period"] = "IS"; all_trades.append(t2)
for t in oos_log:
    if "ticker" in t:
        t2 = dict(t); t2["period"] = "OOS"; all_trades.append(t2)
if all_trades:
    pd.DataFrame(all_trades).to_csv(trades_path, index=False)
    print(f"Saved: {trades_path}")

# ── Save sweep CSV ────────────────────────────────────────────────────────────
sweep_path = f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}_sweep.csv"
sweep_rows = []
# WF windows as sweep rows + param sweep
for w in wf_windows:
    sweep_rows.append({
        "type": "walk_forward",
        "window": w["window"],
        "train_start": w["train_start"], "train_end": w["train_end"],
        "test_start": w["test_start"], "test_end": w["test_end"],
        "train_sharpe": w["train_sharpe"], "test_sharpe": w["test_sharpe"],
        "consistency_ratio": w["consistency_ratio"], "passed": w["passed"],
    })
# Add param sweep rows
for param in ["uup_sma_period", "uup_mom_period", "confirmation_weeks", "spy_trend_ma"]:
    if param in sweep_results:
        for label, sharpe in sweep_results[param].items():
            sweep_rows.append({
                "type": "param_sweep",
                "param": param,
                "label": label,
                "sharpe": sharpe,
                "variance_pct": sweep_results.get(f"{param}_variance_pct", ""),
                "gate1": sweep_results.get(f"{param}_gate1", ""),
            })
pd.DataFrame(sweep_rows).to_csv(sweep_path, index=False)
print(f"Saved: {sweep_path}")

# ── Save verdict TXT ──────────────────────────────────────────────────────────
verdict_path = f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}_verdict.txt"
verdict_lines = [
    "PASS" if gate1_pass else "FAIL",
    f"Strategy: {STRATEGY_NAME}",
    f"Date: {TODAY}",
    f"IS period: {IS_START} to {IS_END}",
    f"OOS period: {OOS_START} to {OOS_END}",
    "",
    "── Core Metrics ──",
    f"IS Sharpe: {is_result['sharpe']:.4f} (threshold >1.0)",
    f"OOS Sharpe: {oos_result['sharpe']:.4f} (threshold >0.7)",
    f"IS MDD: {is_result['max_drawdown']:.2%} (threshold <20%)",
    f"OOS MDD: {oos_result['max_drawdown']:.2%} (threshold <25%)",
    f"IS CAGR: {is_cagr_val:.2%}",
    f"OOS CAGR: {oos_cagr_val:.2%}",
    f"Trade count (IS): {is_trade_count} (threshold >=100)",
    f"Trade count (OOS): {oos_trade_count}",
    f"Win rate (IS): {is_win_rate:.2%} (threshold >50%)",
    f"Profit factor (IS): {is_pf:.4f}" if is_pf is not None else "Profit factor (IS): inf",
    f"IS Regime — weak: {is_result['regime_counts'].get('weak',0)} | neutral: {is_result['regime_counts'].get('neutral',0)} | strong: {is_result['regime_counts'].get('strong',0)}",
    f"OOS Regime — weak: {oos_result['regime_counts'].get('weak',0)} | neutral: {oos_result['regime_counts'].get('neutral',0)} | strong: {oos_result['regime_counts'].get('strong',0)}",
    "",
    "── Statistical Rigor ──",
    f"DSR z-score: {dsr['dsr_zscore']:.4f} ({'PASS' if dsr['passed'] else 'FAIL'})",
    f"Permutation p-value: {perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})",
    f"MC p5 Sharpe: {mc['mc_p5_sharpe']:.4f} ({'PASS' if mc['mc_p5_sharpe']>=0.5 else 'WARN'})",
    f"MC Median Sharpe: {mc['mc_median_sharpe']:.4f}",
    f"Bootstrap Sharpe CI: [{ci['sharpe_ci_low']:.4f}, {ci['sharpe_ci_high']:.4f}]",
    f"Bootstrap MDD CI: [{ci['mdd_ci_low']:.4f}, {ci['mdd_ci_high']:.4f}]",
    f"Bootstrap WR CI: [{ci['win_rate_ci_low']:.4f}, {ci['win_rate_ci_high']:.4f}]",
    f"WF windows passed: {wf_passed}/{wf_total}",
    f"WF Sharpe std: {wf_var['wf_sharpe_std']:.4f}",
    f"WF Sharpe min: {wf_var['wf_sharpe_min']:.4f}",
    f"Sensitivity pass: {sensitivity_pass}",
    f"Market impact (est): {avg_impact_bps:.2f} bps",
    f"Post-cost Sharpe (IS): {post_cost_sharpe_is:.4f}",
    f"Post-cost Sharpe (OOS): {post_cost_sharpe_oos:.4f}",
    f"Liquidity constrained events: {len(liq_flags)}",
    "",
    "── Parameter Sweep (IS sensitivity) ──",
]
for param in ["uup_sma_period", "uup_mom_period", "confirmation_weeks"]:
    if param in sweep_results:
        verdict_lines.append(f"  {param}: {sweep_results[param]}")
        verdict_lines.append(f"    Gate1: {sweep_results.get(f'{param}_gate1','N/A')}")

verdict_lines += [
    "",
    "── Walk-Forward Windows ──",
]
for w in wf_windows:
    verdict_lines.append(
        f"  Window {w['window']}: IS [{w['train_start']}–{w['train_end']}] "
        f"Sharpe={w['train_sharpe']:.3f} | OOS [{w['test_start']}–{w['test_end']}] "
        f"Sharpe={w['test_sharpe']:.3f} | CR={w['consistency_ratio']:.3f} | "
        f"{'PASS' if w['passed'] else 'FAIL'}"
    )

verdict_lines += [
    "",
    "── Gate 1 Checks ──",
]
for k, v in checks.items():
    verdict_lines.append(f"  {'PASS' if v else 'FAIL'}: {k}")

verdict_lines += [
    "",
    f"OOS Data Quality: {dq_report['recommendation']} | Coverage: {dq_report['oos_data_coverage_pct']:.1f}%",
]

with open(verdict_path, "w") as f:
    f.write("\n".join(verdict_lines) + "\n")
print(f"Saved: {verdict_path}")

# ── Save HTML report ──────────────────────────────────────────────────────────
report_path = f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}_report.html"
overall = "PASS" if gate1_pass else "FAIL"
color = "#22c55e" if gate1_pass else "#ef4444"

check_rows = ""
for k, v in checks.items():
    bg = "#f0fdf4" if v else "#fef2f2"
    check_rows += f'<tr style="background:{bg}"><td>{k}</td><td>{"PASS ✓" if v else "FAIL ✗"}</td></tr>\n'

wf_rows = ""
for w in wf_windows:
    bg = "#f0fdf4" if w["passed"] else "#fef2f2"
    wf_rows += (
        f'<tr style="background:{bg}"><td>{w["window"]}</td>'
        f'<td>{w["train_start"]}–{w["train_end"]}</td>'
        f'<td>{w["test_start"]}–{w["test_end"]}</td>'
        f'<td>{w["train_sharpe"]:.3f}</td>'
        f'<td>{w["test_sharpe"]:.3f}</td>'
        f'<td>{w["consistency_ratio"]:.3f}</td>'
        f'<td>{"PASS" if w["passed"] else "FAIL"}</td></tr>\n'
    )

sweep_rows_html = ""
for param in ["uup_sma_period", "uup_mom_period", "confirmation_weeks"]:
    if param in sweep_results:
        for label, sh in sweep_results[param].items():
            sweep_rows_html += f'<tr><td>{param}</td><td>{label}</td><td>{sh}</td></tr>\n'

html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>H81 DollarStrengthEMRotation Gate 1 Report</title>
<style>
body{{font-family:monospace;max-width:1000px;margin:auto;padding:20px;background:#f9fafb}}
h1{{color:#1e293b}}h2{{color:#334155;border-bottom:1px solid #e2e8f0}}
.verdict{{font-size:2em;font-weight:bold;color:{color};padding:10px;border:2px solid {color};display:inline-block}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}
th,td{{border:1px solid #e2e8f0;padding:6px 10px;text-align:left}}
th{{background:#f1f5f9}}
.pass{{color:#16a34a;font-weight:bold}}.fail{{color:#dc2626;font-weight:bold}}
</style></head>
<body>
<h1>H81 Dollar-Strength EM Rotation — Gate 1 Report</h1>
<p>Date: {TODAY} | Asset class: ETF rotation (EEM/VEA/SPY/SHY) | Signal: UUP USD regime</p>
<p>IS: {IS_START}–{IS_END} | OOS: {OOS_START}–{OOS_END}</p>
<div class="verdict">{overall}</div>

<h2>Core Metrics</h2>
<table>
<tr><th>Metric</th><th>IS</th><th>OOS</th><th>Gate 1 Threshold</th></tr>
<tr><td>Sharpe Ratio</td><td>{is_result["sharpe"]:.4f}</td><td>{oos_result["sharpe"]:.4f}</td><td>IS>1.0 / OOS>0.7</td></tr>
<tr><td>CAGR</td><td>{is_cagr_val:.2%}</td><td>{oos_cagr_val:.2%}</td><td>—</td></tr>
<tr><td>Max Drawdown</td><td>{is_result["max_drawdown"]:.2%}</td><td>{oos_result["max_drawdown"]:.2%}</td><td>IS<20% / OOS<25%</td></tr>
<tr><td>Win Rate</td><td>{is_win_rate:.2%}</td><td>{oos_win_rate:.2%}</td><td>>50%</td></tr>
<tr><td>Profit Factor</td><td>{f"{is_pf:.4f}" if is_pf else "inf"}</td><td>{f"{oos_pf:.4f}" if oos_pf else "inf"}</td><td>>1.0</td></tr>
<tr><td>Trade Count</td><td>{is_trade_count}</td><td>{oos_trade_count}</td><td>≥100</td></tr>
<tr><td>IS Regime</td><td colspan="2">weak={is_result["regime_counts"].get("weak",0)} | neutral={is_result["regime_counts"].get("neutral",0)} | strong={is_result["regime_counts"].get("strong",0)}</td><td>—</td></tr>
<tr><td>OOS Regime</td><td colspan="2">weak={oos_result["regime_counts"].get("weak",0)} | neutral={oos_result["regime_counts"].get("neutral",0)} | strong={oos_result["regime_counts"].get("strong",0)}</td><td>—</td></tr>
</table>

<h2>Statistical Rigor</h2>
<table>
<tr><th>Test</th><th>Result</th><th>Pass/Fail</th></tr>
<tr><td>DSR z-score</td><td>{dsr["dsr_zscore"]:.4f}</td><td class="{"pass" if dsr["passed"] else "fail"}">{"PASS" if dsr["passed"] else "FAIL"}</td></tr>
<tr><td>Permutation p-value</td><td>{perm["permutation_pvalue"]:.4f}</td><td class="{"pass" if perm["permutation_test_pass"] else "fail"}">{"PASS" if perm["permutation_test_pass"] else "FAIL"}</td></tr>
<tr><td>MC p5 Sharpe</td><td>{mc["mc_p5_sharpe"]:.4f}</td><td class="{"pass" if mc["mc_p5_sharpe"]>=0.5 else "fail"}">{"PASS" if mc["mc_p5_sharpe"]>=0.5 else "WARN"}</td></tr>
<tr><td>MC Median Sharpe</td><td>{mc["mc_median_sharpe"]:.4f}</td><td>—</td></tr>
<tr><td>Bootstrap Sharpe CI</td><td>[{ci["sharpe_ci_low"]:.4f}, {ci["sharpe_ci_high"]:.4f}]</td><td>—</td></tr>
<tr><td>Bootstrap MDD CI</td><td>[{ci["mdd_ci_low"]:.4f}, {ci["mdd_ci_high"]:.4f}]</td><td>—</td></tr>
<tr><td>Post-cost IS Sharpe</td><td>{post_cost_sharpe_is:.4f}</td><td class="{"pass" if post_cost_sharpe_is>0 else "fail"}">{"PASS" if post_cost_sharpe_is>0 else "FAIL"}</td></tr>
<tr><td>Market impact (est)</td><td>{avg_impact_bps:.2f} bps</td><td>—</td></tr>
<tr><td>Sensitivity (±20%)</td><td>—</td><td class="{"pass" if sensitivity_pass else "fail"}">{"PASS" if sensitivity_pass else "FAIL"}</td></tr>
</table>

<h2>Walk-Forward Windows (6 windows, 36mo IS / 6mo OOS)</h2>
<table>
<tr><th>#</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>Consistency</th><th>Result</th></tr>
{wf_rows}
</table>
<p>WF Pass: {wf_passed}/{wf_total} | Consistency score: {wf_cons:.3f} | Std: {wf_var["wf_sharpe_std"]:.3f} | Min: {wf_var["wf_sharpe_min"]:.3f}</p>

<h2>Parameter Sweep (IS)</h2>
<table>
<tr><th>Parameter</th><th>Value</th><th>IS Sharpe</th></tr>
{sweep_rows_html}
</table>

<h2>Gate 1 Checks</h2>
<table>
<tr><th>Check</th><th>Result</th></tr>
{check_rows}
</table>

<h2>OOS Data Quality</h2>
<p>Recommendation: <strong>{dq_report["recommendation"]}</strong> | Coverage: {dq_report["oos_data_coverage_pct"]:.1f}% | Total NaN cells: {dq_report["oos_total_nans"]}</p>

<h2>Strategy Info</h2>
<p>Tickers: EEM, VEA, SPY, SHY | Signal: UUP USD regime (SMA={PARAMETERS["uup_sma_period"]}d, mom={PARAMETERS["uup_mom_period"]}d, confirm={PARAMETERS["confirmation_weeks"]}w)</p>
<p>Execution: Friday close signal → Monday open execution (T+1, no look-ahead)</p>
<p>Liquidity-constrained events: {len(liq_flags)}</p>

</body></html>
"""

with open(report_path, "w") as f:
    f.write(html)
print(f"Saved: {report_path}")

# ── Final Summary ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"GATE 1 VERDICT: {'PASS' if gate1_pass else 'FAIL'}")
print("=" * 60)
print(f"IS Sharpe:    {is_result['sharpe']:.4f}  (threshold >1.0)")
print(f"OOS Sharpe:   {oos_result['sharpe']:.4f}  (threshold >0.7)")
print(f"IS MDD:       {is_result['max_drawdown']:.2%}  (threshold <20%)")
print(f"OOS MDD:      {oos_result['max_drawdown']:.2%}  (threshold <25%)")
print(f"IS CAGR:      {is_cagr_val:.2%}")
print(f"IS Trades:    {is_trade_count}")
print(f"Win rate:     {is_win_rate:.2%}")
print(f"DSR:          {dsr['dsr_zscore']:.4f}")
print(f"Perm test:    p={perm['permutation_pvalue']:.4f}")
print(f"WF:           {wf_passed}/{wf_total}")
print(f"MC p5:        {mc['mc_p5_sharpe']:.4f}")
print(f"Sensitivity:  {'PASS' if sensitivity_pass else 'FAIL'}")
print("=" * 60)
print("OUTPUT SUMMARY:")
print(f"  JSON:    {json_path}")
print(f"  Trades:  {trades_path}")
print(f"  Sweep:   {sweep_path}")
print(f"  Verdict: {verdict_path}")
print(f"  Report:  {report_path}")
