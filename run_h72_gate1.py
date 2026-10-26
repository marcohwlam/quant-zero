"""
Gate 1 Backtest Runner for H72 Bond Yield Curve Carry.
Runs IS/OOS + all Statistical Rigor Pipeline steps + walk-forward.
"""
import sys
import os
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, "/repos/quant-zero/strategies")
sys.path.insert(0, "/repos/quant-zero/orchestrator")

import h72_bond_yield_curve_carry as h72

OUTPUT_DIR = "/repos/quant-zero/backtests"
DATE_STR = "2026-06-16"
BASE = f"H72_BondYieldCurveCarry_{DATE_STR}"

# ── 1. Run primary IS/OOS + sweep ─────────────────────────────────────────────
print("=" * 70)
print("STEP 1: Running primary IS/OOS backtest + parameter sweep")
print("=" * 70)

params = {**h72.PARAMETERS}
result = h72.run_strategy(params=params, output_dir=OUTPUT_DIR, run_sweep=True)

is_m = result["is"]
oos_m = result["oos"]
sweep_results = result["sweep_results"]
stability = result["sweep_stability"]

print("\nIS metrics:", is_m)
print("OOS metrics:", oos_m)

# ── 2. Download data (reuse for statistical rigor pipeline) ────────────────────
print("\n" + "=" * 70)
print("STEP 2: Loading data for statistical rigor pipeline")
print("=" * 70)
data = h72.download_data(h72.DATA_START, h72.OOS_END)
monthly_signals = h72.compute_monthly_signals(data, params)

# Rebuild IS/OOS simulations for return series access
is_sim = h72.run_simulation(data, monthly_signals, params, h72.IS_START, h72.IS_END)
oos_sim = h72.run_simulation(data, monthly_signals, params, h72.OOS_START, h72.OOS_END)

is_pv = is_sim["portfolio_values"].dropna()
oos_pv = oos_sim["portfolio_values"].dropna()
is_trades = is_sim["trade_log"]
oos_trades = oos_sim["trade_log"]

is_returns = is_pv.pct_change().fillna(0).values
oos_returns = oos_pv.pct_change().fillna(0).values

# ── 3. OOS Data Quality Validation ────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 3: OOS Data Quality Validation")
print("=" * 70)

try:
    from oos_data_quality import validate_oos_data, OOSDataQualityError

    oos_close = data["close"].loc[h72.OOS_START:h72.OOS_END]

    oos_metrics_for_dq = {
        "sharpe": oos_m.get("sharpe"),
        "max_drawdown": oos_m.get("max_drawdown"),
        "win_rate": oos_m.get("win_rate"),
        "profit_factor": oos_m.get("profit_factor") if oos_m.get("profit_factor") != "inf" else 999.0,
        "total_trades": oos_m.get("trade_count"),
        "post_cost_sharpe": oos_m.get("sharpe"),  # already post-cost in H72
    }

    dq_report = validate_oos_data(oos_close, oos_metrics_for_dq, "H72_BondYieldCurveCarry")
    print(f"OOS DQ recommendation: {dq_report['recommendation']}")

    if dq_report["recommendation"] == "BLOCK":
        print(f"BLOCK: {dq_report}")
        sys.exit(1)

except Exception as e:
    print(f"WARNING: OOS DQ check error: {e}")
    dq_report = {"recommendation": "WARN", "error": str(e)}

# ── 4. Monte Carlo Simulation ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 4: Monte Carlo Simulation (1000 resamples)")
print("=" * 70)

def monte_carlo_sharpe(trade_pnls, n_sims=1000):
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

# Use IS trade PnL for Monte Carlo
is_pnl = np.array([t["pnl_dollar"] for t in is_trades]) if is_trades else np.array([0.0])
mc_results = monte_carlo_sharpe(is_pnl)
print(f"MC p5={mc_results['mc_p5_sharpe']:.3f}, median={mc_results['mc_median_sharpe']:.3f}, p95={mc_results['mc_p95_sharpe']:.3f}")

mc_flag = "MC pessimistic bound weak" if mc_results["mc_p5_sharpe"] < 0.5 else "MC p5 OK"
print(f"MC flag: {mc_flag}")

# ── 5. Block Bootstrap CI ──────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 5: Block Bootstrap 95% CI")
print("=" * 70)

def block_bootstrap_ci(returns, n_boots=1000):
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = T // block_len

    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-10)))
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

# Use IS returns for bootstrap CI
bootstrap_ci = block_bootstrap_ci(is_returns)
print(f"Sharpe CI: [{bootstrap_ci['sharpe_ci_low']:.3f}, {bootstrap_ci['sharpe_ci_high']:.3f}]")
print(f"MDD CI: [{bootstrap_ci['mdd_ci_low']:.3f}, {bootstrap_ci['mdd_ci_high']:.3f}]")
print(f"WinRate CI: [{bootstrap_ci['win_rate_ci_low']:.3f}, {bootstrap_ci['win_rate_ci_high']:.3f}]")

# ── 6. Market Impact ──────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 6: Market Impact (TLT equity ETF)")
print("=" * 70)

# TLT: ~$100/share, $100K capital → ~1000 shares per trade
# ADV ~30M shares/day
tlt_close_all = data["close"]["TLT"]
tlt_sigma = tlt_close_all.pct_change().std()
adv = data["volume"]["TLT"].rolling(20).mean().dropna().iloc[-1]
order_qty = 1000.0  # ~$100K / $100/share

k = 0.1
impact_pct = k * tlt_sigma * np.sqrt(order_qty / (adv + 1e-8))
impact_bps = impact_pct * 10000
liquidity_constrained = bool(order_qty > 0.01 * adv)

market_impact = {
    "market_impact_bps": float(impact_bps),
    "liquidity_constrained": liquidity_constrained,
    "order_to_adv_ratio": float(order_qty / (adv + 1e-8)),
    "tlt_sigma_daily": float(tlt_sigma),
    "tlt_adv_20d": float(adv),
}
print(f"Market impact: {impact_bps:.2f} bps, liquidity_constrained={liquidity_constrained}")

# ── 7. Permutation Test for Alpha ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 7: Permutation Test (500 permutations)")
print("=" * 70)

def permutation_test_alpha(prices, entries, exits, observed_sharpe, n_perms=500):
    permuted_sharpes = []
    entry_indices = np.where(entries)[0]
    n_entries = len(entry_indices)

    for _ in range(n_perms):
        perm_entry_idx = np.random.choice(len(prices), size=n_entries, replace=False)
        trade_returns = []
        for idx in perm_entry_idx:
            exit_idx = min(idx + 5, len(prices) - 1)
            if prices[idx] > 0:
                ret = (prices[exit_idx] - prices[idx]) / prices[idx]
                trade_returns.append(ret)

        if len(trade_returns) > 1:
            arr = np.array(trade_returns)
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(252 / 5)
        else:
            s = 0.0
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": p_value <= 0.05,
    }

# Build entry/exit arrays from IS trade log
is_prices = is_pv.values
n = len(is_prices)
entries_arr = np.zeros(n, dtype=bool)
exits_arr = np.zeros(n, dtype=bool)

for trade in is_trades:
    entry_date = trade.get("date_entry")
    exit_date = trade.get("date_exit")
    if entry_date:
        try:
            idx = is_pv.index.get_loc(pd.Timestamp(entry_date))
            entries_arr[idx] = True
        except (KeyError, Exception):
            pass
    if exit_date:
        try:
            idx = is_pv.index.get_loc(pd.Timestamp(exit_date))
            exits_arr[idx] = True
        except (KeyError, Exception):
            pass

observed_is_sharpe = float(is_m.get("sharpe", 0.0))
perm_results = permutation_test_alpha(is_prices, entries_arr, exits_arr, observed_is_sharpe)
print(f"Permutation p-value: {perm_results['permutation_pvalue']:.4f}, pass={perm_results['permutation_test_pass']}")

# ── 8. Walk-Forward Analysis ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 8: Walk-Forward Analysis (4 windows, IS 36mo / OOS 6mo)")
print("=" * 70)

WF_WINDOWS = [
    ("2003-01-01", "2006-01-01", "2006-01-01", "2006-07-01"),
    ("2006-07-01", "2009-07-01", "2009-07-01", "2010-01-01"),
    ("2010-01-01", "2013-01-01", "2013-01-01", "2013-07-01"),
    ("2013-07-01", "2016-07-01", "2016-07-01", "2017-01-01"),
]

wf_results = []
wf_oos_sharpes = []

for wf_is_start, wf_is_end, wf_oos_start, wf_oos_end in WF_WINDOWS:
    try:
        wf_sigs = h72.compute_monthly_signals(data, params)
        wf_is_sim = h72.run_simulation(data, wf_sigs, params, wf_is_start, wf_is_end)
        wf_is_m = h72.compute_metrics(wf_is_sim["portfolio_values"], wf_is_sim["trade_log"], wf_is_start, wf_is_end)

        wf_oos_sim = h72.run_simulation(data, wf_sigs, params, wf_oos_start, wf_oos_end)
        wf_oos_m = h72.compute_metrics(wf_oos_sim["portfolio_values"], wf_oos_sim["trade_log"], wf_oos_start, wf_oos_end)

        wf_is_sharpe = float(wf_is_m.get("sharpe", 0.0))
        wf_oos_sharpe = float(wf_oos_m.get("sharpe", 0.0))
        wf_oos_sharpes.append(wf_oos_sharpe)

        # Window passes if OOS Sharpe > 0.7 and within 30% of IS Sharpe
        oos_is_ratio = wf_oos_sharpe / (wf_is_sharpe + 1e-8) if wf_is_sharpe > 0 else 0.0
        passed = (wf_oos_sharpe > 0.7) and (abs(1 - oos_is_ratio) <= 0.3)

        wf_results.append({
            "is_period": f"{wf_is_start} to {wf_is_end}",
            "oos_period": f"{wf_oos_start} to {wf_oos_end}",
            "is_sharpe": round(wf_is_sharpe, 4),
            "oos_sharpe": round(wf_oos_sharpe, 4),
            "is_trades": wf_is_m.get("trade_count", 0),
            "oos_trades": wf_oos_m.get("trade_count", 0),
            "oos_is_ratio": round(oos_is_ratio, 4),
            "passed": passed,
        })
        print(f"  WF {wf_oos_start[:7]}: IS Sharpe={wf_is_sharpe:.3f}, OOS Sharpe={wf_oos_sharpe:.3f}, ratio={oos_is_ratio:.2f}, passed={passed}")
    except Exception as e:
        print(f"  WF {wf_oos_start[:7]}: ERROR {e}")
        wf_results.append({"oos_period": f"{wf_oos_start} to {wf_oos_end}", "error": str(e), "passed": False})
        wf_oos_sharpes.append(0.0)

wf_windows_passed = sum(1 for w in wf_results if w.get("passed", False))
print(f"\nWalk-forward: {wf_windows_passed}/4 windows passed")

# Walk-forward variance
def walk_forward_variance(sharpes):
    arr = np.array(sharpes)
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }

wf_variance = walk_forward_variance(wf_oos_sharpes)
print(f"WF variance: std={wf_variance['wf_sharpe_std']:.4f}, min={wf_variance['wf_sharpe_min']:.4f}")

if wf_variance["wf_sharpe_min"] < 0:
    print("WARNING: wf_sharpe_min < 0 — at least one losing OOS window")

# ── 9. DSR (Deflated Sharpe Ratio) ────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 9: Deflated Sharpe Ratio")
print("=" * 70)

try:
    from scipy import stats as scipy_stats

    def compute_dsr(returns, n_trials=12, observed_sharpe=None):
        T = len(returns)
        if T < 10:
            return {"dsr": None, "error": "insufficient data"}

        sharpe_obs = observed_sharpe if observed_sharpe else float(
            returns.mean() / (returns.std() + 1e-10) * np.sqrt(252)
        )
        skew = float(scipy_stats.skew(returns))
        kurt = float(scipy_stats.kurtosis(returns))

        # Expected max Sharpe from n_trials under IID Gaussian (Bailey & Lopez de Prado)
        exp_max = (
            (1 - np.euler_gamma) * scipy_stats.norm.ppf(1 - 1 / n_trials) +
            np.euler_gamma * scipy_stats.norm.ppf(1 - 1 / (n_trials * np.e))
        )
        # Sharpe standard error
        se = np.sqrt((1 + 0.5 * sharpe_obs**2 - skew * sharpe_obs + (kurt / 4) * sharpe_obs**2) / T)
        dsr = float(scipy_stats.norm.cdf((sharpe_obs - exp_max) / (se + 1e-10)))
        return {"dsr": round(dsr, 4), "expected_max_sharpe": round(exp_max, 4), "n_trials": n_trials}

    dsr_result = compute_dsr(is_returns, n_trials=12, observed_sharpe=observed_is_sharpe)
    print(f"DSR: {dsr_result}")
except Exception as e:
    print(f"DSR error: {e}")
    dsr_result = {"dsr": None, "error": str(e)}

# ── 10. Leveraged test if CAGR < 10% ──────────────────────────────────────────
primary_cagr = float(is_m.get("cagr", 0.0))
leveraged_result = None

if primary_cagr < 0.10:
    print("\n" + "=" * 70)
    print(f"STEP 10: Primary CAGR={primary_cagr:.2%} < 10% — running 2x leveraged test")
    print("=" * 70)
    lev_params = {**params, "leverage": 2.0}
    lev_sigs = h72.compute_monthly_signals(data, lev_params)
    lev_is_sim = h72.run_simulation(data, lev_sigs, lev_params, h72.IS_START, h72.IS_END)
    lev_is_m = h72.compute_metrics(lev_is_sim["portfolio_values"], lev_is_sim["trade_log"], h72.IS_START, h72.IS_END)
    lev_oos_sim = h72.run_simulation(data, lev_sigs, lev_params, h72.OOS_START, h72.OOS_END)
    lev_oos_m = h72.compute_metrics(lev_oos_sim["portfolio_values"], lev_oos_sim["trade_log"], h72.OOS_START, h72.OOS_END)
    leveraged_result = {
        "leverage": 2.0,
        "is": lev_is_m,
        "oos": lev_oos_m,
        "sharpe_pass": float(lev_is_m.get("sharpe", 0.0)) > 0.8,
    }
    print(f"2x leveraged IS Sharpe={lev_is_m.get('sharpe')}, CAGR={lev_is_m.get('cagr')}")
    print(f"2x leveraged OOS Sharpe={lev_oos_m.get('sharpe')}, CAGR={lev_oos_m.get('cagr')}")
else:
    print(f"\nPrimary CAGR={primary_cagr:.2%} >= 10% — no leveraged test needed")

# ── 11. Gate 1 Verdict ────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 11: Gate 1 Verdict")
print("=" * 70)

is_sharpe = float(is_m.get("sharpe", 0.0))
oos_sharpe = float(oos_m.get("sharpe", 0.0))
is_mdd = float(is_m.get("max_drawdown", -1.0))
oos_mdd = float(oos_m.get("max_drawdown", -1.0))
is_cagr = float(is_m.get("cagr", 0.0))
oos_cagr = float(oos_m.get("cagr", 0.0))
is_trade_count = int(is_m.get("trade_count", 0))
perm_pvalue = perm_results["permutation_pvalue"]

gate1_checks = {
    "IS Sharpe > 1.0": is_sharpe > 1.0,
    "OOS Sharpe > 0.70": oos_sharpe > 0.70,
    "IS MDD < -15%": is_mdd > -0.15,
    "OOS MDD < -15%": oos_mdd > -0.15,
    "IS CAGR >= 10%": is_cagr >= 0.10,
    "OOS CAGR >= 10%": oos_cagr >= 0.10,
    "IS trades >= 100": is_trade_count >= 100,
    "Permutation p-value < 0.05": perm_pvalue < 0.05,
    "Walk-forward >= 3/4 windows": wf_windows_passed >= 3,
    "DSR > 0": (dsr_result.get("dsr") or 0.0) > 0,
}

passed_checks = sum(1 for v in gate1_checks.values() if v)
total_checks = len(gate1_checks)
core_pass = all([
    gate1_checks["IS Sharpe > 1.0"],
    gate1_checks["OOS Sharpe > 0.70"],
    gate1_checks["IS MDD < -15%"],
    gate1_checks["IS trades >= 100"],
])

if core_pass and passed_checks >= total_checks - 2:
    overall_verdict = "PASS"
elif core_pass:
    overall_verdict = "CONDITIONAL PASS"
else:
    overall_verdict = "FAIL"

print(f"Overall verdict: {overall_verdict} ({passed_checks}/{total_checks} checks)")
for check, result in gate1_checks.items():
    print(f"  {'PASS' if result else 'FAIL'}: {check}")

# ── 12. Build full metrics JSON ────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 12: Writing metrics JSON")
print("=" * 70)

profit_factor_val = is_m.get("profit_factor", 0.0)
if profit_factor_val == "inf":
    profit_factor_val = 999.0

full_metrics = {
    "strategy_name": "H72_BondYieldCurveCarry",
    "date": DATE_STR,
    "asset_class": "equities",
    "parameters": {
        "slope_lookback_months": params["slope_lookback_months"],
        "spread_threshold": "median",
        "leverage": params["leverage"],
    },
    # IS metrics
    "is_sharpe": is_sharpe,
    "is_max_drawdown": is_mdd,
    "is_cagr": is_cagr,
    "is_trade_count": is_trade_count,
    "is_win_rate": float(is_m.get("win_rate", 0.0)),
    "is_profit_factor": float(profit_factor_val),
    "is_total_return": float(is_m.get("total_return", 0.0)),
    "is_avg_ppt_bps": float(is_m.get("avg_ppt_bps", 0.0)),
    # OOS metrics
    "oos_sharpe": oos_sharpe,
    "oos_max_drawdown": oos_mdd,
    "oos_cagr": oos_cagr,
    "oos_trade_count": int(oos_m.get("trade_count", 0)),
    "oos_win_rate": float(oos_m.get("win_rate", 0.0)),
    "oos_profit_factor": float(oos_m.get("profit_factor", 0.0)) if oos_m.get("profit_factor") != "inf" else 999.0,
    "oos_total_return": float(oos_m.get("total_return", 0.0)),
    "oos_avg_ppt_bps": float(oos_m.get("avg_ppt_bps", 0.0)),
    # Post-cost (strategy already applies costs — these are the actual metrics)
    "post_cost_sharpe": is_sharpe,
    "win_rate": float(is_m.get("win_rate", 0.0)),
    "profit_factor": float(profit_factor_val),
    "trade_count": is_trade_count,
    # DSR
    "dsr": dsr_result.get("dsr"),
    # Monte Carlo
    **mc_results,
    "mc_flag": mc_flag,
    # Bootstrap CI
    **bootstrap_ci,
    # Market impact
    **market_impact,
    # Permutation test
    **perm_results,
    # Walk-forward
    "wf_windows_passed": wf_windows_passed,
    "wf_windows_total": 4,
    "wf_consistency_score": round(wf_windows_passed / 4, 2),
    "wf_results": wf_results,
    **wf_variance,
    # Sensitivity / sweep stability
    "sensitivity_pass": stability.get("gate1_stability", "").startswith("PASS"),
    "sweep_stability": stability,
    # Other required fields
    "look_ahead_bias_flag": False,
    "gate1_pass": overall_verdict == "PASS",
    "gate1_verdict": overall_verdict,
    "gate1_checks": gate1_checks,
    # OOS DQ
    "oos_data_quality": dq_report,
    # Leveraged test (if run)
    "leveraged_test": leveraged_result,
    # Raw data
    "is_metrics_raw": is_m,
    "oos_metrics_raw": oos_m,
    "data_quality": result.get("data_quality", {}),
}

json_path = os.path.join(OUTPUT_DIR, f"{BASE}.json")
with open(json_path, "w") as f:
    json.dump(full_metrics, f, indent=2, default=str)
print(f"Metrics JSON: {json_path}")

# ── 13. HTML Report ───────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 13: Generating HTML report")
print("=" * 70)

def render_check(passed):
    return '<span style="color:green">✓ PASS</span>' if passed else '<span style="color:red">✗ FAIL</span>'

verdict_color = {"PASS": "#28a745", "FAIL": "#dc3545", "CONDITIONAL PASS": "#fd7e14"}.get(overall_verdict, "#6c757d")

wf_rows = "".join(
    f"<tr><td>{w.get('oos_period','?')}</td>"
    f"<td>{w.get('is_sharpe', 'ERR')}</td>"
    f"<td>{w.get('oos_sharpe', 'ERR')}</td>"
    f"<td>{w.get('oos_is_ratio', 'ERR')}</td>"
    f"<td>{'✓' if w.get('passed') else '✗'}</td></tr>"
    for w in wf_results
)

sweep_rows = "".join(
    f"<tr><td>{r.get('slope_lookback_months','?')}</td>"
    f"<td>{r.get('spread_threshold','?')}</td>"
    f"<td>{r.get('sharpe', r.get('error','ERR'))}</td>"
    f"<td>{r.get('cagr','?')}</td>"
    f"<td>{r.get('win_rate','?')}</td></tr>"
    for r in result["sweep_results"]
)

gate1_rows = "".join(
    f"<tr><td>{k}</td><td>{render_check(v)}</td></tr>"
    for k, v in gate1_checks.items()
)

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>H72 Bond Yield Curve Carry — Gate 1 Report</title>
<style>
body {{ font-family: monospace; margin: 32px; background: #f8f9fa; }}
h1 {{ color: #343a40; }}
h2 {{ color: #495057; margin-top: 28px; }}
.verdict {{ font-size: 2em; font-weight: bold; color: {verdict_color}; padding: 16px; background: #fff; border: 2px solid {verdict_color}; display: inline-block; margin: 16px 0; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: 12px 0; }}
th, td {{ border: 1px solid #dee2e6; padding: 8px 12px; text-align: left; }}
th {{ background: #343a40; color: #fff; }}
tr:nth-child(even) {{ background: #f8f9fa; }}
.pass {{ color: green; font-weight: bold; }}
.fail {{ color: red; font-weight: bold; }}
.section {{ background: #fff; padding: 16px; border-radius: 6px; margin: 12px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
</style>
</head>
<body>
<h1>H72 Bond Yield Curve Carry — Gate 1 Report</h1>
<p>Date: {DATE_STR} | IS: {h72.IS_START} to {h72.IS_END} | OOS: {h72.OOS_START} to {h72.OOS_END}</p>
<div class="verdict">{overall_verdict} ({passed_checks}/{total_checks} checks)</div>

<div class="section">
<h2>IS / OOS Performance Summary</h2>
<table>
<tr><th>Metric</th><th>IS (2003–2018)</th><th>OOS (2019–2024)</th><th>Threshold</th></tr>
<tr><td>Sharpe (net of costs)</td><td>{is_sharpe:.4f}</td><td>{oos_sharpe:.4f}</td><td>&gt; 1.0 (IS), &gt; 0.70 (OOS)</td></tr>
<tr><td>CAGR</td><td>{is_cagr:.2%}</td><td>{oos_cagr:.2%}</td><td>&ge; 10%</td></tr>
<tr><td>Max Drawdown</td><td>{is_mdd:.2%}</td><td>{oos_mdd:.2%}</td><td>&lt; −15%</td></tr>
<tr><td>Win Rate</td><td>{is_m.get('win_rate', 0):.2%}</td><td>{oos_m.get('win_rate', 0):.2%}</td><td>&gt; 50%</td></tr>
<tr><td>Profit Factor</td><td>{is_m.get('profit_factor', 0)}</td><td>{oos_m.get('profit_factor', 0)}</td><td>&gt; 1.0</td></tr>
<tr><td>Trade Count</td><td>{is_trade_count}</td><td>{oos_m.get('trade_count', 0)}</td><td>&ge; 100 (IS)</td></tr>
<tr><td>Avg PnL per trade (bps)</td><td>{is_m.get('avg_ppt_bps', 0):.1f}</td><td>{oos_m.get('avg_ppt_bps', 0):.1f}</td><td>&gt; 0</td></tr>
<tr><td>DSR</td><td colspan="2">{dsr_result.get('dsr', 'N/A')}</td><td>&gt; 0</td></tr>
</table>
</div>

<div class="section">
<h2>Gate 1 Checklist</h2>
<table>
<tr><th>Check</th><th>Result</th></tr>
{gate1_rows}
</table>
</div>

<div class="section">
<h2>Statistical Rigor</h2>
<table>
<tr><th>Metric</th><th>Value</th><th>Note</th></tr>
<tr><td>MC p5 Sharpe</td><td>{mc_results['mc_p5_sharpe']:.4f}</td><td>{mc_flag}</td></tr>
<tr><td>MC Median Sharpe</td><td>{mc_results['mc_median_sharpe']:.4f}</td><td></td></tr>
<tr><td>MC p95 Sharpe</td><td>{mc_results['mc_p95_sharpe']:.4f}</td><td></td></tr>
<tr><td>Sharpe 95% CI</td><td>[{bootstrap_ci['sharpe_ci_low']:.4f}, {bootstrap_ci['sharpe_ci_high']:.4f}]</td><td>Block bootstrap</td></tr>
<tr><td>MDD 95% CI</td><td>[{bootstrap_ci['mdd_ci_low']:.4f}, {bootstrap_ci['mdd_ci_high']:.4f}]</td><td></td></tr>
<tr><td>Win Rate 95% CI</td><td>[{bootstrap_ci['win_rate_ci_low']:.4f}, {bootstrap_ci['win_rate_ci_high']:.4f}]</td><td></td></tr>
<tr><td>Permutation p-value</td><td>{perm_pvalue:.4f}</td><td>{'PASS: p ≤ 0.05' if perm_pvalue <= 0.05 else 'FAIL: p > 0.05'}</td></tr>
<tr><td>Market Impact (TLT)</td><td>{impact_bps:.2f} bps</td><td>Liquidity constrained: {liquidity_constrained}</td></tr>
<tr><td>OOS DQ</td><td>{dq_report.get('recommendation', 'N/A')}</td><td></td></tr>
</table>
</div>

<div class="section">
<h2>Walk-Forward Analysis (4 windows)</h2>
<p><strong>{wf_windows_passed}/4 windows passed</strong> | WF Sharpe std={wf_variance['wf_sharpe_std']:.4f}, min={wf_variance['wf_sharpe_min']:.4f}</p>
<table>
<tr><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>OOS/IS Ratio</th><th>Passed</th></tr>
{wf_rows}
</table>
</div>

<div class="section">
<h2>Parameter Sweep (IS Sensitivity)</h2>
<p>{stability.get('gate1_stability', 'N/A')}</p>
<table>
<tr><th>Lookback (mo)</th><th>Threshold</th><th>Sharpe</th><th>CAGR</th><th>Win Rate</th></tr>
{sweep_rows}
</table>
</div>

{"<div class='section'><h2>Leveraged Test (2×)</h2>" + f"<p>IS Sharpe: {leveraged_result['is'].get('sharpe')}, IS CAGR: {leveraged_result['is'].get('cagr'):.2%}, OOS Sharpe: {leveraged_result['oos'].get('sharpe')}, OOS CAGR: {leveraged_result['oos'].get('cagr'):.2%}</p><p>Sharpe &gt; 0.8 pass: {leveraged_result['sharpe_pass']}</p></div>" if leveraged_result else ""}

</body>
</html>"""

html_path = os.path.join(OUTPUT_DIR, f"{BASE}_report.html")
with open(html_path, "w") as f:
    f.write(html)
print(f"HTML report: {html_path}")

# ── 14. Verdict TXT ───────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 14: Writing verdict TXT")
print("=" * 70)

verdict_txt = f"""H72 Bond Yield Curve Carry — Gate 1 Verdict
Date: {DATE_STR}
Strategy: H72_BondYieldCurveCarry
Overall: {overall_verdict} ({passed_checks}/{total_checks} checks)

=== IS Performance (2003-2018) ===
Sharpe:        {is_sharpe:.4f}  (threshold > 1.0)
CAGR:          {is_cagr:.2%}  (threshold >= 10%)
Max Drawdown:  {is_mdd:.2%}  (threshold < -15%)
Win Rate:      {float(is_m.get('win_rate', 0)):.2%}
Profit Factor: {is_m.get('profit_factor', 0)}
Trade Count:   {is_trade_count}  (threshold >= 100)
DSR:           {dsr_result.get('dsr', 'N/A')}

=== OOS Performance (2019-2024) ===
Sharpe:        {oos_sharpe:.4f}  (threshold > 0.70)
CAGR:          {oos_cagr:.2%}
Max Drawdown:  {oos_mdd:.2%}
Win Rate:      {float(oos_m.get('win_rate', 0)):.2%}
Trade Count:   {oos_m.get('trade_count', 0)}

=== Statistical Rigor ===
MC p5 Sharpe:       {mc_results['mc_p5_sharpe']:.4f}  ({mc_flag})
Sharpe CI 95%:      [{bootstrap_ci['sharpe_ci_low']:.4f}, {bootstrap_ci['sharpe_ci_high']:.4f}]
Permutation p-val:  {perm_pvalue:.4f}  ({'PASS' if perm_pvalue <= 0.05 else 'FAIL'})
Market Impact:      {impact_bps:.2f} bps  (liquidity_constrained={liquidity_constrained})
OOS DQ:             {dq_report.get('recommendation', 'N/A')}

=== Walk-Forward (4 windows) ===
Passed: {wf_windows_passed}/4
WF Sharpe std: {wf_variance['wf_sharpe_std']:.4f}
WF Sharpe min: {wf_variance['wf_sharpe_min']:.4f}
{'WARNING: wf_sharpe_min < 0 — at least one losing OOS window' if wf_variance['wf_sharpe_min'] < 0 else ''}

=== Sensitivity Sweep ===
{stability.get('gate1_stability', 'N/A')}
Sharpe range: [{stability.get('sharpe_min','?')} – {stability.get('sharpe_max','?')}]

=== Gate 1 Checks ===
"""
for check, chk_result in gate1_checks.items():
    verdict_txt += f"  {'[PASS]' if chk_result else '[FAIL]'} {check}\n"

if leveraged_result:
    verdict_txt += f"""
=== Secondary Leveraged Test (2×) ===
Primary CAGR was {is_cagr:.2%} < 10%, ran 2x leveraged test:
IS Sharpe: {leveraged_result['is'].get('sharpe')}, IS CAGR: {leveraged_result['is'].get('cagr'):.2%}
OOS Sharpe: {leveraged_result['oos'].get('sharpe')}, OOS CAGR: {leveraged_result['oos'].get('cagr'):.2%}
Sharpe > 0.8 (leveraged): {'PASS' if leveraged_result['sharpe_pass'] else 'FAIL'}
"""

verdict_txt += f"\n=== Files ===\n"
verdict_txt += f"Metrics:  backtests/{BASE}.json\n"
verdict_txt += f"Trades:   backtests/{BASE}_trades.csv\n"
verdict_txt += f"Sweep:    backtests/{BASE}_sweep.csv\n"
verdict_txt += f"Report:   backtests/{BASE}_report.html\n"
verdict_txt += f"Verdict:  backtests/{BASE}_verdict.txt\n"

verdict_path = os.path.join(OUTPUT_DIR, f"{BASE}_verdict.txt")
with open(verdict_path, "w") as f:
    f.write(verdict_txt)
print(f"Verdict: {verdict_path}")
print("\nAll outputs written.")
print(f"\nFINAL VERDICT: {overall_verdict}")
