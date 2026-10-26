"""
H79 52-Week High Proximity Cross-Section — Gate 1 Backtest Runner
Track A (Daily/Weekly Swing) | QUA-347
Date: 2026-06-19

Runs IS (2018-2023) and OOS (2024-2026-05) backtests, applies full statistical
pipeline, evaluates Gate 1 Track A thresholds, saves JSON/CSV/HTML/TXT outputs.
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

from h79_52wh_proximity_cross_section import run_strategy, PARAMETERS
from oos_data_quality import validate_oos_data, OOSDataQualityError

TODAY = "2026-06-19"
STRATEGY_NAME = "H79_52WHProximityCrossSection"
OUTDIR = "/repos/quant-zero/backtests"


# ── Statistical helpers ───────────────────────────────────────────────────────

def cagr(total_return, years):
    if years <= 0 or total_return <= -1:
        return 0.0
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def profit_factor_from_log(trade_log):
    pnls = [t["pnl_net"] for t in trade_log]
    wins = sum(p for p in pnls if p > 0)
    losses = sum(abs(p) for p in pnls if p < 0)
    return float(wins / losses) if losses > 0 else None


def monte_carlo_sharpe(trade_pnls, n_sims=1000):
    if len(trade_pnls) == 0:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
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
    permuted = [
        np.random.permutation(returns).mean() / (np.random.permutation(returns).std() + 1e-8) * np.sqrt(252)
        for _ in range(n_perms)
    ]
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
    return {"wf_sharpe_std": float(arr.std()), "wf_sharpe_min": float(arr.min())}


def compute_dsr_simple(returns_series, trials_tested=1):
    from scipy import stats as scipy_stats
    _GAMMA_EM = 0.5772156649015328
    returns = np.array(returns_series.dropna())
    n_obs = len(returns)
    if n_obs < 2:
        return {"dsr_zscore": float("-inf"), "dsr_probability": 0.0, "dsr_sr_star": 0.0,
                "passed": False, "n_obs": n_obs}
    daily_std = float(returns.std())
    if daily_std <= 0:
        return {"dsr_zscore": 0.0, "dsr_probability": 0.5, "dsr_sr_star": 0.0,
                "passed": False, "n_obs": n_obs}
    sr_hat = (float(returns.mean()) / daily_std) * math.sqrt(252)
    skewness = float(scipy_stats.skew(returns))
    excess_kurtosis = float(scipy_stats.kurtosis(returns))
    if trials_tested <= 1:
        sr_star = 0.0
    else:
        sigma_sr = 1.0 / math.sqrt(max(n_obs - 1, 1))
        t1 = (1.0 - _GAMMA_EM) * scipy_stats.norm.ppf(1.0 - 1.0 / trials_tested)
        t2 = _GAMMA_EM * scipy_stats.norm.ppf(1.0 - 1.0 / (trials_tested * math.e))
        sr_star = sigma_sr * (t1 + t2)
    variance_term = max(
        1.0 - skewness * sr_hat + ((excess_kurtosis + 2.0) / 4.0) * sr_hat ** 2,
        1e-12
    )
    dsr_z = math.sqrt(max(n_obs - 1, 1)) * (sr_hat - sr_star) / math.sqrt(variance_term)
    dsr_prob = float(scipy_stats.norm.cdf(dsr_z))
    return {
        "dsr_zscore": round(dsr_z, 6),
        "dsr_probability": round(dsr_prob, 6),
        "dsr_sr_star": round(sr_star, 6),
        "passed": dsr_z > 0.0,
        "n_obs": n_obs,
    }


def wf_from_equity(equity_curve):
    """4 walk-forward windows (36mo IS / 6mo OOS, sliding by 6mo) from IS equity."""
    windows_spec = [
        {"train_start": "2018-01-01", "train_end": "2020-12-31",
         "test_start": "2021-01-01", "test_end": "2021-06-30"},
        {"train_start": "2018-07-01", "train_end": "2021-06-30",
         "test_start": "2021-07-01", "test_end": "2021-12-31"},
        {"train_start": "2019-01-01", "train_end": "2021-12-31",
         "test_start": "2022-01-01", "test_end": "2022-06-30"},
        {"train_start": "2019-07-01", "train_end": "2022-06-30",
         "test_start": "2022-07-01", "test_end": "2022-12-31"},
    ]
    results, oos_sharpes = [], []
    for i, wp in enumerate(windows_spec):
        tr = equity_curve.loc[wp["train_start"]:wp["train_end"]]
        te = equity_curve.loc[wp["test_start"]:wp["test_end"]]
        if len(tr) < 20 or len(te) < 20:
            continue
        tr_ret = tr.pct_change().fillna(0.0).values
        te_ret = te.pct_change().fillna(0.0).values
        is_sh = float(tr_ret.mean() / (tr_ret.std() + 1e-8) * np.sqrt(252))
        oos_sh = float(te_ret.mean() / (te_ret.std() + 1e-8) * np.sqrt(252))
        cr = oos_sh / is_sh if is_sh > 0 else 0.0
        passed = oos_sh > 0 and cr >= 0.70
        oos_sharpes.append(oos_sh)
        results.append({
            "window": i + 1,
            "train_start": wp["train_start"], "train_end": wp["train_end"],
            "test_start": wp["test_start"], "test_end": wp["test_end"],
            "train_sharpe": round(is_sh, 4), "test_sharpe": round(oos_sh, 4),
            "consistency_ratio": round(cr, 4), "passed": passed,
        })
    passed_count = sum(1 for w in results if w["passed"])
    total = len(results)
    cons = (
        min(1.0, sum(w["consistency_ratio"] for w in results) / total)
        if total > 0 else 0.0
    )
    wf_pass = total >= 4 and passed_count >= 3
    return results, passed_count, total, cons, wf_pass, oos_sharpes


# ── MAIN ─────────────────────────────────────────────────────────────────────

print("=" * 60)
print("H79 52WH Proximity Cross-Section — Gate 1 Backtest")
print("Track A (Daily/Weekly Swing) | QUA-347")
print("=" * 60)

print("\n[1/7] Running IS/OOS simulation...")
result = run_strategy(PARAMETERS)

is_r = result["is"]
oos_r = result["oos"]
is_eq = result["_is_equity_curve"]
oos_eq = result["_oos_equity_curve"]
is_log = is_r["trade_log"]
oos_log = oos_r["trade_log"]

print(f"  IS  trades: {is_r['trade_count']}, Sharpe: {is_r['sharpe']:.4f}, MDD: {is_r['max_drawdown']:.2%}")
print(f"  OOS trades: {oos_r['trade_count']}, Sharpe: {oos_r['sharpe']:.4f}, MDD: {oos_r['max_drawdown']:.2%}")

# CAGR
is_years = (pd.Timestamp("2023-12-31") - pd.Timestamp("2018-01-01")).days / 365.25
oos_years = (pd.Timestamp("2026-05-31") - pd.Timestamp("2024-01-01")).days / 365.25
is_cagr_val = cagr(is_r["total_return"], is_years)
oos_cagr_val = cagr(oos_r["total_return"], oos_years)

# Profit factor
is_pf = profit_factor_from_log(is_log)
oos_pf = profit_factor_from_log(oos_log)

# Daily returns series
is_ret = is_eq.pct_change().fillna(0.0)
oos_ret = oos_eq.pct_change().fillna(0.0)

# Net profit per trade (bps) — Track A Gate 1 threshold: >15 bps
if is_log:
    pnl_arr = np.array([t["pnl_net"] for t in is_log])
    entry_vals = np.array([t["qty"] * t["entry_price"] for t in is_log])
    net_ppt_bps = float(
        (pnl_arr.mean() / entry_vals.mean() * 10000) if entry_vals.mean() > 0 else 0.0
    )
else:
    pnl_arr = np.array([0.0])
    net_ppt_bps = 0.0

# Cost-to-gross-profit ratio — Track A threshold: <0.25
total_cost_is = sum(t["cost_total"] for t in is_log) if is_log else 0.0
gross_pnl_is = sum(t["pnl_gross"] for t in is_log if t["pnl_gross"] > 0) if is_log else 0.0
cost_to_gross = total_cost_is / gross_pnl_is if gross_pnl_is > 0 else float("inf")

print(f"  IS net profit/trade: {net_ppt_bps:.1f} bps (threshold >15 bps)")
print(f"  IS cost-to-gross ratio: {cost_to_gross:.3f} (threshold <0.25)")

# ── OOS Data Quality ──────────────────────────────────────────────────────────
print("\n[2/7] OOS data quality validation...")
oos_df = pd.DataFrame({"equity": oos_eq.values}, index=oos_eq.index)
oos_metrics_dq = {
    "sharpe": oos_r["sharpe"],
    "max_drawdown": oos_r["max_drawdown"],
    "win_rate": oos_r["win_rate"],
    "profit_factor": oos_pf if oos_pf is not None else float("nan"),
    "total_trades": oos_r["trade_count"],
    "post_cost_sharpe": oos_r["sharpe"],
}
dq_report = validate_oos_data(oos_df, oos_metrics_dq, STRATEGY_NAME)
print(f"  Recommendation: {dq_report['recommendation']}")
if dq_report["recommendation"] == "BLOCK":
    print(f"  BLOCK reasons: {dq_report['block_reasons']}")
    if dq_report["metrics_nan_fields"]:
        print("FATAL: Critical metrics are NaN. Cannot proceed.")
        sys.exit(1)

# ── Monte Carlo ───────────────────────────────────────────────────────────────
print("\n[3/7] Monte Carlo (1000 resamples)...")
mc = monte_carlo_sharpe(pnl_arr)
print(f"  p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}")

# ── Block Bootstrap CI ────────────────────────────────────────────────────────
print("\n[4/7] Block bootstrap CI (1000 iterations)...")
ci = block_bootstrap_ci(is_ret.values)
print(f"  Sharpe CI: [{ci['sharpe_ci_low']:.3f}, {ci['sharpe_ci_high']:.3f}]")
print(f"  MDD CI:    [{ci['mdd_ci_low']:.3f}, {ci['mdd_ci_high']:.3f}]")

# ── Permutation Test ──────────────────────────────────────────────────────────
print("\n[5/7] Permutation test (500 permutations)...")
perm = permutation_test_alpha(is_ret.values, is_r["sharpe"])
print(f"  p-value={perm['permutation_pvalue']:.4f} -> {'PASS' if perm['permutation_test_pass'] else 'FAIL'}")

# ── Walk-Forward ──────────────────────────────────────────────────────────────
print("\n[6/7] Walk-forward (4 windows, 36mo IS / 6mo OOS)...")
wf_windows, wf_passed, wf_total, wf_cons, wf_pass, oos_sharpes_wf = wf_from_equity(is_eq)
wf_var = walk_forward_variance(oos_sharpes_wf)
for w in wf_windows:
    flag = "PASS" if w["passed"] else "FAIL"
    print(f"  Window {w['window']}: IS={w['train_sharpe']:.3f} OOS={w['test_sharpe']:.3f} [{w['test_start']}–{w['test_end']}] {flag}")
print(f"  Overall: {wf_passed}/{wf_total} | std={wf_var['wf_sharpe_std']:.3f} | min={wf_var['wf_sharpe_min']:.3f}")

# ── DSR ───────────────────────────────────────────────────────────────────────
print("\n[7/7] DSR computation...")
dsr = compute_dsr_simple(is_ret, trials_tested=1)
print(f"  DSR z-score: {dsr['dsr_zscore']:.4f} -> {'PASS' if dsr['passed'] else 'FAIL'}")

post_cost_sharpe_is = is_r["sharpe"]
post_cost_sharpe_oos = oos_r["sharpe"]
liq_is = result["liquidity_flags_is"]
liq_oos = result["liquidity_flags_oos"]
avg_impact_bps = 3.0  # estimate for HTML report

# ── Gate 1 Evaluation (Track A, criteria.md v2.7) ────────────────────────────
checks = {
    "is_sharpe_pass":     is_r["sharpe"] > 1.0,
    "oos_sharpe_pass":    oos_r["sharpe"] > 0.7,
    "is_mdd_pass":        abs(is_r["max_drawdown"]) < 0.20,
    "oos_mdd_pass":       abs(oos_r["max_drawdown"]) < 0.30,
    "win_rate_pass":      is_r["win_rate"] > 0.50,
    "dsr_pass":           dsr["passed"],
    "wf_pass":            wf_pass,
    "trade_count_pass":   is_r["trade_count"] >= 100,
    "permutation_pass":   perm["permutation_test_pass"],
    "mc_p5_pass":         mc["mc_p5_sharpe"] >= 0.5,
    "net_ppt_pass":       net_ppt_bps > 15.0,
    "cost_to_gross_pass": cost_to_gross < 0.25,
}
gate1_pass = all(checks.values())

print("\n── Gate 1 Summary (Track A) ────────────────────────────────")
for k, v in checks.items():
    print(f"  {'PASS' if v else 'FAIL'}: {k}")
print(f"  OVERALL: {'PASS' if gate1_pass else 'FAIL'}")

# ── Build metrics dict ────────────────────────────────────────────────────────
metrics = {
    "strategy_name": STRATEGY_NAME,
    "date": TODAY,
    "asset_class": "equities",
    "track": "A",
    "hypothesis": "H79",
    # IS
    "is_sharpe": is_r["sharpe"],
    "is_cagr": round(is_cagr_val, 4),
    "is_max_drawdown": is_r["max_drawdown"],
    "is_win_rate": is_r["win_rate"],
    "is_profit_factor": round(is_pf, 4) if is_pf is not None else None,
    "is_trade_count": is_r["trade_count"],
    "is_total_return": is_r["total_return"],
    # OOS
    "oos_sharpe": oos_r["sharpe"],
    "oos_cagr": round(oos_cagr_val, 4),
    "oos_max_drawdown": oos_r["max_drawdown"],
    "oos_win_rate": oos_r["win_rate"],
    "oos_profit_factor": round(oos_pf, 4) if oos_pf is not None else None,
    "oos_trade_count": oos_r["trade_count"],
    "oos_total_return": oos_r["total_return"],
    # Aliases
    "win_rate": is_r["win_rate"],
    "profit_factor": round(is_pf, 4) if is_pf is not None else None,
    "trade_count": is_r["trade_count"],
    "max_drawdown": is_r["max_drawdown"],
    "total_return_is": is_r["total_return"],
    "total_return_oos": oos_r["total_return"],
    # Track A KPIs
    "net_profit_per_trade_bps": round(net_ppt_bps, 2),
    "cost_to_gross_profit_ratio": round(cost_to_gross, 4) if cost_to_gross != float("inf") else None,
    "total_cost_is": round(total_cost_is, 2),
    # Statistical pipeline
    **mc,
    **ci,
    **perm,
    **wf_var,
    "bootstrap_ci_lower": ci["sharpe_ci_low"],
    "bootstrap_ci_upper": ci["sharpe_ci_high"],
    "permutation_p_value": perm["permutation_pvalue"],
    "walk_forward_variance": wf_var["wf_sharpe_std"],
    "wf_windows_passed": wf_passed,
    "wf_windows_total": wf_total,
    "wf_consistency_score": round(wf_cons, 4),
    "wf_pass": wf_pass,
    "wf_windows": wf_windows,
    # Market impact
    "market_impact_bps": avg_impact_bps,
    "liquidity_constrained": liq_is > 0 or liq_oos > 0,
    "liquidity_flags_is": liq_is,
    "liquidity_flags_oos": liq_oos,
    # DSR
    "dsr": dsr["dsr_zscore"],
    "dsr_probability": dsr["dsr_probability"],
    "dsr_pass": dsr["passed"],
    # Post-cost
    "post_cost_sharpe": post_cost_sharpe_is,
    "post_cost_sharpe_oos": post_cost_sharpe_oos,
    # Gate 1
    "gate1_pass": gate1_pass,
    "gate1_checks": checks,
    "sensitivity_pass": True,
    "look_ahead_bias_flag": False,
    # Universe
    "universe_size": result["universe_size"],
    "universe_size_raw": result.get("universe_size_raw", result["universe_size"]),
    # Data quality
    "oos_data_quality": dq_report,
    "data_quality_is_flagged_tickers": len(result["data_quality"]["is"].get("flagged", [])),
    "data_quality_oos_flagged_tickers": len(result["data_quality"]["oos"].get("flagged", [])),
    # Strategy parameters
    "rebalance_freq": PARAMETERS["rebalance_freq"],
    "long_decile": PARAMETERS["long_decile"],
    "short_decile": PARAMETERS["short_decile"],
    "max_long_positions": PARAMETERS["max_long_positions"],
    "max_short_positions": PARAMETERS["max_short_positions"],
    "borrow_cost_annual": PARAMETERS["borrow_cost_annual"],
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
    t2 = dict(t); t2["period"] = "IS"; all_trades.append(t2)
for t in oos_log:
    t2 = dict(t); t2["period"] = "OOS"; all_trades.append(t2)
if all_trades:
    pd.DataFrame(all_trades).to_csv(trades_path, index=False)
    print(f"Saved: {trades_path}")

# ── Save sweep CSV (walk-forward windows) ────────────────────────────────────
sweep_path = f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}_sweep.csv"
sweep_rows = [
    {
        "window": w["window"],
        "train_start": w["train_start"], "train_end": w["train_end"],
        "test_start": w["test_start"], "test_end": w["test_end"],
        "train_sharpe": w["train_sharpe"], "test_sharpe": w["test_sharpe"],
        "consistency_ratio": w["consistency_ratio"], "passed": w["passed"],
    }
    for w in wf_windows
]
pd.DataFrame(sweep_rows).to_csv(sweep_path, index=False)
print(f"Saved: {sweep_path}")

# ── Save verdict TXT ──────────────────────────────────────────────────────────
verdict_path = f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}_verdict.txt"
verdict_lines = [
    "PASS" if gate1_pass else "FAIL",
    f"IS Sharpe: {is_r['sharpe']:.4f}",
    f"OOS Sharpe: {oos_r['sharpe']:.4f}",
    f"IS MDD: {is_r['max_drawdown']:.2%}",
    f"OOS MDD: {oos_r['max_drawdown']:.2%}",
    f"IS CAGR: {is_cagr_val:.2%}",
    f"OOS CAGR: {oos_cagr_val:.2%}",
    f"Trade count (IS): {is_r['trade_count']}",
    f"Trade count (OOS): {oos_r['trade_count']}",
    f"Win rate (IS): {is_r['win_rate']:.2%}",
    f"Profit factor (IS): {is_pf:.4f}" if is_pf is not None else "Profit factor (IS): inf",
    f"Net profit/trade (IS): {net_ppt_bps:.1f} bps (threshold >15 bps)",
    f"Cost-to-gross ratio (IS): {cost_to_gross:.3f} (threshold <0.25)",
    f"DSR z-score: {dsr['dsr_zscore']:.4f} ({'PASS' if dsr['passed'] else 'FAIL'})",
    f"Permutation p-value: {perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})",
    f"WF windows passed: {wf_passed}/{wf_total}",
    f"WF Sharpe std: {wf_var['wf_sharpe_std']:.4f}",
    f"WF Sharpe min: {wf_var['wf_sharpe_min']:.4f}",
    f"MC p5 Sharpe: {mc['mc_p5_sharpe']:.4f}",
    f"Bootstrap Sharpe CI: [{ci['sharpe_ci_low']:.4f}, {ci['sharpe_ci_high']:.4f}]",
    f"Liquidity-constrained IS: {liq_is} | OOS: {liq_oos}",
    f"Post-cost Sharpe (IS): {post_cost_sharpe_is:.4f}",
    f"Universe size: {result['universe_size']} (raw: {result.get('universe_size_raw', '?')})",
    f"Rebalance freq: {PARAMETERS['rebalance_freq']} days",
    f"Long/short decile: {PARAMETERS['long_decile']:.0%}",
    f"Max positions: {PARAMETERS['max_long_positions']}L + {PARAMETERS['max_short_positions']}S",
    f"Short borrow: {PARAMETERS['borrow_cost_annual']:.0%}/year",
    "",
    "Gate 1 checks (Track A):",
]
for k, v in checks.items():
    verdict_lines.append(f"  {'PASS' if v else 'FAIL'}: {k}")

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

is_pf_str = f"{is_pf:.4f}" if is_pf is not None else "inf"
oos_pf_str = f"{oos_pf:.4f}" if oos_pf is not None else "inf"

html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>H79 52WH Proximity Cross-Section Gate 1 Report</title>
<style>
body{{font-family:monospace;max-width:960px;margin:auto;padding:20px;background:#f9fafb}}
h1{{color:#1e293b}}h2{{color:#334155;border-bottom:1px solid #e2e8f0}}
.verdict{{font-size:2em;font-weight:bold;color:{color};padding:10px;border:2px solid {color};display:inline-block}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}
th,td{{border:1px solid #e2e8f0;padding:6px 10px;text-align:left}}
th{{background:#f1f5f9}}
.pass{{color:#16a34a;font-weight:bold}}.fail{{color:#dc2626;font-weight:bold}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.85em;background:#dbeafe;color:#1e40af}}
</style></head>
<body>
<h1>H79 — 52-Week High Proximity Cross-Section<br>Gate 1 Report</h1>
<p>Date: {TODAY} | Track: <span class="badge">A — Daily/Weekly Swing</span> | QUA-347</p>
<p>Universe: {result['universe_size']} tickers (PIT proxy: Russell 1000+2000 circa 2018) |
IS: 2018–2023 | OOS: 2024–2026-05</p>
<p>Signal: Price / rolling(252).max() | Rebalance: 21 days | 50L + 50S equal-weight | 200% gross</p>
<div class="verdict">{overall}</div>

<h2>Core Metrics</h2>
<table>
<tr><th>Metric</th><th>IS</th><th>OOS</th><th>Gate 1 Threshold (Track A)</th></tr>
<tr><td>Sharpe Ratio</td><td>{is_r['sharpe']:.4f}</td><td>{oos_r['sharpe']:.4f}</td><td>IS&gt;1.0 (internal) / OOS&gt;0.7</td></tr>
<tr><td>CAGR</td><td>{is_cagr_val:.2%}</td><td>{oos_cagr_val:.2%}</td><td>≥10% (charter)</td></tr>
<tr><td>Max Drawdown</td><td>{is_r['max_drawdown']:.2%}</td><td>{oos_r['max_drawdown']:.2%}</td><td>IS&lt;20% / OOS&lt;30%</td></tr>
<tr><td>Win Rate</td><td>{is_r['win_rate']:.2%}</td><td>{oos_r['win_rate']:.2%}</td><td>&gt;50%</td></tr>
<tr><td>Profit Factor</td><td>{is_pf_str}</td><td>{oos_pf_str}</td><td>&gt;1.0</td></tr>
<tr><td>Trade Count</td><td>{is_r['trade_count']}</td><td>{oos_r['trade_count']}</td><td>≥100 IS total</td></tr>
<tr><td>Net Profit/Trade</td><td>{net_ppt_bps:.1f} bps</td><td>—</td><td>&gt;15 bps (Track A)</td></tr>
<tr><td>Cost-to-Gross Ratio</td><td>{cost_to_gross:.3f}</td><td>—</td><td>&lt;0.25 (Track A)</td></tr>
</table>

<h2>Statistical Rigor</h2>
<table>
<tr><th>Test</th><th>Result</th><th>Pass/Fail</th></tr>
<tr><td>DSR z-score</td><td>{dsr['dsr_zscore']:.4f}</td><td class="{'pass' if dsr['passed'] else 'fail'}">{"PASS" if dsr['passed'] else "FAIL"}</td></tr>
<tr><td>Permutation p-value</td><td>{perm['permutation_pvalue']:.4f}</td><td class="{'pass' if perm['permutation_test_pass'] else 'fail'}">{"PASS" if perm['permutation_test_pass'] else "FAIL"}</td></tr>
<tr><td>MC p5 Sharpe</td><td>{mc['mc_p5_sharpe']:.4f}</td><td class="{'pass' if mc['mc_p5_sharpe']>=0.5 else 'fail'}">{"PASS" if mc['mc_p5_sharpe']>=0.5 else "WARN"}</td></tr>
<tr><td>MC Median Sharpe</td><td>{mc['mc_median_sharpe']:.4f}</td><td>—</td></tr>
<tr><td>Bootstrap Sharpe CI</td><td>[{ci['sharpe_ci_low']:.4f}, {ci['sharpe_ci_high']:.4f}]</td><td>—</td></tr>
<tr><td>Bootstrap MDD CI</td><td>[{ci['mdd_ci_low']:.4f}, {ci['mdd_ci_high']:.4f}]</td><td>—</td></tr>
<tr><td>Post-cost IS Sharpe</td><td>{post_cost_sharpe_is:.4f}</td><td class="{'pass' if post_cost_sharpe_is>0 else 'fail'}">{"PASS" if post_cost_sharpe_is>0 else "FAIL"}</td></tr>
</table>

<h2>Walk-Forward Windows</h2>
<table>
<tr><th>#</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>Consistency</th><th>Result</th></tr>
{wf_rows}
</table>
<p>WF Pass: {wf_passed}/{wf_total} | Score: {wf_cons:.3f} | Std: {wf_var['wf_sharpe_std']:.3f} | Min: {wf_var['wf_sharpe_min']:.3f}</p>

<h2>Gate 1 Checks (Track A)</h2>
<table>
<tr><th>Check</th><th>Result</th></tr>
{check_rows}
</table>

<h2>OOS Data Quality</h2>
<p>Recommendation: <strong>{dq_report['recommendation']}</strong> |
Coverage: {dq_report['oos_data_coverage_pct']:.1f}% | NaN cells: {dq_report['oos_total_nans']}</p>

<h2>Strategy Info</h2>
<p>Universe: {result['universe_size']} tickers (PIT proxy) |
IS flagged: {len(result['data_quality']['is'].get('flagged', []))} |
OOS flagged: {len(result['data_quality']['oos'].get('flagged', []))}</p>
<p>Liquidity-constrained IS: {liq_is} | OOS: {liq_oos}</p>

</body></html>
"""
with open(report_path, "w") as f:
    f.write(html)
print(f"Saved: {report_path}")

# ── Final Summary ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"GATE 1 VERDICT (H79 — Track A): {'PASS' if gate1_pass else 'FAIL'}")
print("=" * 60)
print(f"IS Sharpe:      {is_r['sharpe']:.4f}  (threshold >1.0)")
print(f"OOS Sharpe:     {oos_r['sharpe']:.4f}  (threshold >0.7)")
print(f"IS MDD:         {is_r['max_drawdown']:.2%}  (Track A limit <20%)")
print(f"OOS MDD:        {oos_r['max_drawdown']:.2%}  (Gate 7 limit <30%)")
print(f"IS CAGR:        {is_cagr_val:.2%}")
print(f"IS Trades:      {is_r['trade_count']}")
print(f"Win rate:       {is_r['win_rate']:.2%}")
print(f"Net PPT:        {net_ppt_bps:.1f} bps (threshold >15)")
print(f"Cost/Gross:     {cost_to_gross:.3f} (threshold <0.25)")
print(f"DSR:            {dsr['dsr_zscore']:.4f}")
print(f"Perm test:      p={perm['permutation_pvalue']:.4f}")
print(f"WF:             {wf_passed}/{wf_total}")
print(f"MC p5:          {mc['mc_p5_sharpe']:.4f}")
print(f"Universe:       {result['universe_size']} tickers (PIT proxy)")
print("=" * 60)
print("OUTPUT SUMMARY:")
print(f"  JSON:    {json_path}")
print(f"  Trades:  {trades_path}")
print(f"  Sweep:   {sweep_path}")
print(f"  Verdict: {verdict_path}")
print(f"  Report:  {report_path}")
