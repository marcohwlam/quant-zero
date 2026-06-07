#!/usr/bin/env python3
"""
Gate 1 v2.0 Backtest Runner: H34 RSI(2) Oversold SPY Mean Reversion
QUA-72 | Engineering Director | 2026-06-07

IS window:  2008-01-01 to 2021-12-31
OOS window: 2022-01-01 to 2024-12-31

Criteria: IS Sharpe > 1.0, OOS Sharpe > 0.7, IS MDD < 20%,
          IS Win Rate > 50%, IS Trades >= 100,
          Walk-Forward >= 3/4 windows, Param Sensitivity < 50% Sharpe reduction.
"""

import json
import os
import sys
import warnings
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strategies.h34_rsi2_oversold_spy import PARAMETERS, run_backtest

# ── Windows ────────────────────────────────────────────────────────────────────
IS_START  = "2008-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2024-12-31"

# Four equal sub-windows of IS period (~3.5 years each)
WF_WINDOWS = [
    ("2008-01-01", "2011-06-30"),
    ("2011-07-01", "2014-12-31"),
    ("2015-01-01", "2018-06-30"),
    ("2018-07-01", "2021-12-31"),
]
WF_SHARPE_FLOOR = 0.5   # each sub-window must exceed this to count as pass

# Gate 1 v2.0 thresholds (from QUA-72 spec)
THRESHOLDS = {
    "is_sharpe":              1.0,
    "oos_sharpe":             0.7,
    "is_max_drawdown":       -0.20,   # negative; drawdown expressed as negative fraction
    "is_win_rate":            0.50,
    "is_trade_count":         100,
    "wf_pass_fraction":       0.75,   # >= 3/4 windows
    "param_max_reduction":    0.50,   # < 50% Sharpe reduction
}

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "h34_rsi2_oversold_spy")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _silent_run(start, end, params):
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        return run_backtest(start, end, params)


def _fmt_pct(v):
    return f"{v:.2%}" if isinstance(v, float) else str(v)


def _fmt_sharpe(v):
    return f"{v:.4f}" if isinstance(v, float) else str(v)


# ── Main ───────────────────────────────────────────────────────────────────────

def run_gate1_v2():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    params = PARAMETERS.copy()

    # ── 1. IS Backtest ─────────────────────────────────────────────────────────
    print(f"[1/4] IS backtest {IS_START} → {IS_END} ...")
    is_r = _silent_run(IS_START, IS_END, params)

    # ── 2. OOS Backtest ────────────────────────────────────────────────────────
    print(f"[2/4] OOS backtest {OOS_START} → {OOS_END} ...")
    oos_r = _silent_run(OOS_START, OOS_END, params)

    # ── 3. Walk-Forward Analysis ───────────────────────────────────────────────
    print(f"[3/4] Walk-forward (4 windows) ...")
    wf_results = []
    wf_pass_count = 0

    for wf_start, wf_end in WF_WINDOWS:
        wf_r = _silent_run(wf_start, wf_end, params)
        passed = wf_r["sharpe"] >= WF_SHARPE_FLOOR
        if passed:
            wf_pass_count += 1
        wf_results.append({
            "window":      f"{wf_start} to {wf_end}",
            "sharpe":      wf_r["sharpe"],
            "max_drawdown": wf_r["max_drawdown"],
            "win_rate":    wf_r["win_rate"],
            "trade_count": wf_r["trade_count"],
            "passed":      passed,
        })
        status = "PASS" if passed else "FAIL"
        print(f"  {wf_start}–{wf_end}: Sharpe={wf_r['sharpe']:.3f}  trades={wf_r['trade_count']}  {status}")

    wf_pass_fraction = wf_pass_count / len(WF_WINDOWS)
    wf_stable = wf_pass_fraction >= THRESHOLDS["wf_pass_fraction"]

    # ── 4. Parameter Sensitivity ───────────────────────────────────────────────
    print(f"[4/4] Parameter sensitivity (IS window) ...")
    baseline_sharpe = is_r["sharpe"]

    param_grid = [
        ("rsi_entry_threshold=5",  {"rsi_entry_threshold": 5}),
        ("rsi_entry_threshold=15", {"rsi_entry_threshold": 15}),
        ("sma_period=150",         {"sma_period": 150}),
        ("sma_period=250",         {"sma_period": 250}),
        ("exit_sma_period=3",      {"exit_sma_period": 3}),
        ("exit_sma_period=10",     {"exit_sma_period": 10}),
        ("time_stop_days=3",       {"time_stop_days": 3}),
        ("time_stop_days=7",       {"time_stop_days": 7}),
        ("stop_loss_pct=0.03",     {"stop_loss_pct": 0.03}),
        ("stop_loss_pct=0.06",     {"stop_loss_pct": 0.06}),
    ]

    sensitivity_results = []
    max_reduction = 0.0

    for label, overrides in param_grid:
        p = params.copy()
        p.update(overrides)
        sr = _silent_run(IS_START, IS_END, p)
        # Reduction: positive means worse than baseline
        reduction = (baseline_sharpe - sr["sharpe"]) / max(abs(baseline_sharpe), 1e-8)
        max_reduction = max(max_reduction, reduction)
        sensitivity_results.append({
            "parameter_set":     label,
            "sharpe":            sr["sharpe"],
            "max_drawdown":      sr["max_drawdown"],
            "win_rate":          sr["win_rate"],
            "trade_count":       sr["trade_count"],
            "sharpe_reduction_pct": round(reduction * 100, 1),
        })
        print(f"  {label}: Sharpe={sr['sharpe']:.3f}  reduction={reduction*100:.1f}%")

    sensitivity_stable = max_reduction < THRESHOLDS["param_max_reduction"]

    # ── 5. Criteria Evaluation ─────────────────────────────────────────────────
    criteria = {
        "IS Sharpe (2008-2021)": {
            "value": is_r["sharpe"],
            "threshold": f"> {THRESHOLDS['is_sharpe']}",
            "passed": is_r["sharpe"] > THRESHOLDS["is_sharpe"],
        },
        "OOS Sharpe (2022-2024)": {
            "value": oos_r["sharpe"],
            "threshold": f"> {THRESHOLDS['oos_sharpe']}",
            "passed": oos_r["sharpe"] > THRESHOLDS["oos_sharpe"],
        },
        "IS Max Drawdown": {
            "value": is_r["max_drawdown"],
            "threshold": "> -20.0%",
            "passed": is_r["max_drawdown"] > THRESHOLDS["is_max_drawdown"],
        },
        "IS Win Rate": {
            "value": is_r["win_rate"],
            "threshold": f"> {THRESHOLDS['is_win_rate']:.0%}",
            "passed": is_r["win_rate"] > THRESHOLDS["is_win_rate"],
        },
        "IS Trade Count": {
            "value": is_r["trade_count"],
            "threshold": f">= {THRESHOLDS['is_trade_count']}",
            "passed": is_r["trade_count"] >= THRESHOLDS["is_trade_count"],
        },
        "Walk-Forward Stability": {
            "value": f"{wf_pass_count}/{len(WF_WINDOWS)} windows",
            "threshold": f">= {int(THRESHOLDS['wf_pass_fraction'] * len(WF_WINDOWS))}/{len(WF_WINDOWS)} windows",
            "passed": wf_stable,
        },
        "Parameter Sensitivity": {
            "value": f"max reduction {max_reduction*100:.1f}%",
            "threshold": f"< {THRESHOLDS['param_max_reduction']*100:.0f}% Sharpe reduction",
            "passed": sensitivity_stable,
        },
    }

    n_passed = sum(1 for c in criteria.values() if c["passed"])
    n_total  = len(criteria)
    overall  = "PASS" if all(c["passed"] for c in criteria.values()) else "FAIL"

    # ── 6. Save results.json ───────────────────────────────────────────────────
    results = {
        "strategy":     "H34 RSI(2) Oversold SPY Mean Reversion",
        "run_date":     str(date.today()),
        "gate1_version":"v2.0",
        "task":         "QUA-72",
        "is": {
            "window":         f"{IS_START} to {IS_END}",
            "sharpe":         is_r["sharpe"],
            "max_drawdown":   is_r["max_drawdown"],
            "total_return":   is_r["total_return"],
            "win_rate":       is_r["win_rate"],
            "profit_factor":  is_r["profit_factor"],
            "trade_count":    is_r["trade_count"],
            "trades_per_year":is_r["trades_per_year"],
            "regime_pct":     is_r["regime_pct"],
            "exit_breakdown": is_r["exit_breakdown"],
        },
        "oos": {
            "window":         f"{OOS_START} to {OOS_END}",
            "sharpe":         oos_r["sharpe"],
            "max_drawdown":   oos_r["max_drawdown"],
            "total_return":   oos_r["total_return"],
            "win_rate":       oos_r["win_rate"],
            "profit_factor":  oos_r["profit_factor"],
            "trade_count":    oos_r["trade_count"],
            "trades_per_year":oos_r["trades_per_year"],
            "regime_pct":     oos_r["regime_pct"],
            "exit_breakdown": oos_r["exit_breakdown"],
        },
        "walk_forward": {
            "windows":         wf_results,
            "pass_count":      wf_pass_count,
            "pass_fraction":   round(wf_pass_fraction, 3),
            "stable":          wf_stable,
            "sharpe_floor":    WF_SHARPE_FLOOR,
        },
        "parameter_sensitivity": {
            "baseline_sharpe": baseline_sharpe,
            "results":         sensitivity_results,
            "max_reduction_pct": round(max_reduction * 100, 1),
            "stable":          sensitivity_stable,
        },
        "gate1_v2_criteria": criteria,
        "verdict": {
            "criteria_passed": n_passed,
            "criteria_total":  n_total,
            "overall":         overall,
        },
        "params":        {k: v for k, v in params.items()},
        "data_quality":  is_r["data_quality"],
    }

    rpath = os.path.join(OUTPUT_DIR, "results.json")
    with open(rpath, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults → {rpath}")

    # ── 7. Save trade logs ─────────────────────────────────────────────────────
    if not is_r["trades"].empty:
        is_r["trades"].to_csv(os.path.join(OUTPUT_DIR, "is_trades.csv"), index=False)
    if not oos_r["trades"].empty:
        oos_r["trades"].to_csv(os.path.join(OUTPUT_DIR, "oos_trades.csv"), index=False)

    # ── 8. Write gate1_verdict.md ──────────────────────────────────────────────
    failed_criteria = [k for k, c in criteria.items() if not c["passed"]]
    passed_criteria = [k for k, c in criteria.items() if c["passed"]]

    lines = [
        f"# Gate 1 v2.0 Verdict: H34 RSI(2) Oversold SPY Mean Reversion",
        f"",
        f"**Run date:** {date.today()}  ",
        f"**Task:** QUA-72  ",
        f"**Strategy:** `strategies/h34_rsi2_oversold_spy.py`  ",
        f"**Verdict: {'✅ PASS' if overall == 'PASS' else '❌ FAIL'} ({n_passed}/{n_total} criteria)**",
        f"",
        f"---",
        f"",
        f"## Gate 1 v2.0 Criteria Summary",
        f"",
        f"| Criterion | Value | Threshold | Result |",
        f"|-----------|-------|-----------|--------|",
    ]

    for cname, c in criteria.items():
        val = c["value"]
        if isinstance(val, float):
            if "Drawdown" in cname:
                val_str = f"{val:.2%}"
            elif "Sharpe" in cname:
                val_str = f"{val:.4f}"
            elif "Rate" in cname:
                val_str = f"{val:.2%}"
            else:
                val_str = str(round(val, 4))
        else:
            val_str = str(val)
        result_str = "✅ PASS" if c["passed"] else "❌ FAIL"
        lines.append(f"| {cname} | {val_str} | {c['threshold']} | {result_str} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## In-Sample Performance (2008–2021)",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Sharpe | {is_r['sharpe']:.4f} |",
        f"| Max Drawdown | {is_r['max_drawdown']:.2%} |",
        f"| Total Return | {is_r['total_return']:.2%} |",
        f"| Win Rate | {is_r['win_rate']:.2%} |",
        f"| Profit Factor | {is_r['profit_factor']:.2f} |",
        f"| Trade Count | {is_r['trade_count']} ({is_r['trades_per_year']:.1f}/yr) |",
        f"| Regime Active (SPY > 200-SMA) | {is_r['regime_pct']:.1%} of days |",
        f"| Exit: SMA | {is_r['exit_breakdown'].get('SMA_EXIT', 0)} |",
        f"| Exit: Time Stop | {is_r['exit_breakdown'].get('TIME_STOP', 0)} |",
        f"| Exit: Stop Loss | {is_r['exit_breakdown'].get('STOP_LOSS', 0)} |",
        f"| Exit: End of Data | {is_r['exit_breakdown'].get('END_OF_DATA', 0)} |",
        f"",
        f"## Out-of-Sample Performance (2022–2024)",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Sharpe | {oos_r['sharpe']:.4f} |",
        f"| Max Drawdown | {oos_r['max_drawdown']:.2%} |",
        f"| Total Return | {oos_r['total_return']:.2%} |",
        f"| Win Rate | {oos_r['win_rate']:.2%} |",
        f"| Profit Factor | {oos_r['profit_factor']:.2f} |",
        f"| Trade Count | {oos_r['trade_count']} ({oos_r['trades_per_year']:.1f}/yr) |",
        f"| Regime Active (SPY > 200-SMA) | {oos_r['regime_pct']:.1%} of days |",
        f"",
        f"## Walk-Forward Analysis (4 Sub-Windows)",
        f"",
        f"Sharpe floor per window: {WF_SHARPE_FLOOR}  ",
        f"Result: {wf_pass_count}/{len(WF_WINDOWS)} pass → {'✅ STABLE' if wf_stable else '❌ UNSTABLE'}",
        f"",
        f"| Window | Sharpe | Max DD | Win Rate | Trades | Result |",
        f"|--------|--------|--------|----------|--------|--------|",
    ]

    for wf in wf_results:
        status = "✅ PASS" if wf["passed"] else "❌ FAIL"
        lines.append(
            f"| {wf['window']} | {wf['sharpe']:.4f} | {wf['max_drawdown']:.2%} | "
            f"{wf['win_rate']:.2%} | {wf['trade_count']} | {status} |"
        )

    lines += [
        f"",
        f"## Parameter Sensitivity (IS 2008–2021)",
        f"",
        f"Baseline Sharpe: {baseline_sharpe:.4f}  ",
        f"Max reduction: {max_reduction*100:.1f}% → {'✅ STABLE' if sensitivity_stable else '❌ UNSTABLE'}",
        f"",
        f"| Parameter Set | Sharpe | Max DD | Win Rate | Trades | Sharpe Δ |",
        f"|---------------|--------|--------|----------|--------|----------|",
    ]

    for sr in sensitivity_results:
        lines.append(
            f"| {sr['parameter_set']} | {sr['sharpe']:.4f} | {sr['max_drawdown']:.2%} | "
            f"{sr['win_rate']:.2%} | {sr['trade_count']} | {sr['sharpe_reduction_pct']:+.1f}% |"
        )

    lines += [
        f"",
        f"## Data Quality Checklist",
        f"",
        f"- [x] **Survivorship bias:** {is_r['data_quality']['survivorship_bias_flag']}",
        f"- [x] **Price adjustment:** auto_adjust=True (splits + dividends applied)",
        f"- [x] **Data gaps:** {is_r['data_quality']['gap_flags'] or 'None detected'}",
        f"- [x] **Earnings exclusion:** {is_r['data_quality']['earnings_exclusion']}",
        f"- [x] **Delisted tickers:** {is_r['data_quality']['delisted_tickers']}",
        f"",
        f"## Parameters",
        f"",
        f"| Parameter | Value |",
        f"|-----------|-------|",
        f"| RSI period | {params['rsi_period']} (fixed — Connors 2012) |",
        f"| RSI entry threshold | {params['rsi_entry_threshold']} |",
        f"| SMA regime period | {params['sma_period']}d |",
        f"| Exit SMA period | {params['exit_sma_period']}d |",
        f"| Time stop | {params['time_stop_days']} days |",
        f"| Stop-loss | {params['stop_loss_pct']:.0%} |",
        f"| Re-arm RSI level | {params['rearm_rsi_level']} |",
        f"| Initial capital | ${params['init_cash']:,} |",
        f"",
        f"---",
        f"",
        f"## Narrative",
        f"",
    ]

    if overall == "PASS":
        lines += [
            f"H34 RSI(2) Oversold SPY Mean Reversion **PASSES Gate 1 v2.0** ({n_passed}/{n_total} criteria).",
            f"",
            f"IS Sharpe {is_r['sharpe']:.2f} confirms robust short-term mean-reversion alpha over 2008–2021,",
            f"including the GFC drawdown and COVID crash. The 200-SMA regime filter (active {is_r['regime_pct']:.0%}",
            f"of IS days) successfully screens out sustained bear market conditions.",
            f"Walk-forward stability ({wf_pass_count}/{len(WF_WINDOWS)} sub-windows) confirms the edge is",
            f"not period-specific. OOS Sharpe {oos_r['sharpe']:.2f} demonstrates out-of-sample generalization.",
            f"",
            f"**Recommendation:** Escalate to CEO for paper trading approval.",
        ]
    else:
        lines += [
            f"H34 RSI(2) Oversold SPY Mean Reversion **FAILS Gate 1 v2.0** ({n_passed}/{n_total} criteria).",
            f"",
            f"**Failing criteria ({len(failed_criteria)}):** {', '.join(failed_criteria)}",
            f"",
            f"IS Sharpe {is_r['sharpe']:.4f} is {'above' if is_r['sharpe'] > 1.0 else 'below'} the 1.0 threshold.",
            f"OOS Sharpe {oos_r['sharpe']:.4f} is {'above' if oos_r['sharpe'] > 0.7 else 'below'} the 0.7 threshold.",
            f"IS trade count {is_r['trade_count']} is {'above' if is_r['trade_count'] >= 100 else 'below'} the 100-trade floor.",
            f"",
            f"**Root cause assessment:**",
        ]

        if is_r["sharpe"] < 1.0:
            lines.append(f"- Low IS Sharpe may reflect transaction cost drag relative to short hold periods.")
        if not wf_stable:
            lines.append(f"- Walk-forward instability ({wf_pass_count}/{len(WF_WINDOWS)} windows) indicates")
            lines.append(f"  the alpha is regime-dependent, not persistent across market cycles.")
        if not sensitivity_stable:
            lines.append(f"- Parameter sensitivity ({max_reduction*100:.1f}% max Sharpe reduction) is fragile;")
            lines.append(f"  strategy is over-tuned to baseline parameters.")

        lines += [
            f"",
            f"**Recommendation:** Return to Research Director with metrics for hypothesis refinement.",
            f"Consider relaxing entry threshold, adjusting re-arm condition, or reducing cost assumptions.",
        ]

    lines += [
        f"",
        f"---",
        f"",
        f"*Generated by Engineering Director | QUA-72 | {date.today()}*",
    ]

    vpath = os.path.join(OUTPUT_DIR, "gate1_verdict.md")
    with open(vpath, "w") as f:
        f.write("\n".join(lines))
    print(f"Verdict → {vpath}")

    return results


if __name__ == "__main__":
    results = run_gate1_v2()
    verdict = results["verdict"]
    is_m    = results["is"]
    oos_m   = results["oos"]
    wf      = results["walk_forward"]
    sens    = results["parameter_sensitivity"]

    print(f"\n{'='*60}")
    print(f"GATE 1 v2.0 — H34 RSI(2) Oversold SPY Mean Reversion")
    print(f"{'='*60}")
    print(f"VERDICT: {verdict['overall']}  ({verdict['criteria_passed']}/{verdict['criteria_total']} criteria)")
    print(f"")
    print(f"IS  Sharpe:     {is_m['sharpe']:.4f}  (threshold: > 1.0)")
    print(f"OOS Sharpe:     {oos_m['sharpe']:.4f}  (threshold: > 0.7)")
    print(f"IS  MDD:        {is_m['max_drawdown']:.2%}  (threshold: > -20%)")
    print(f"IS  Win Rate:   {is_m['win_rate']:.2%}  (threshold: > 50%)")
    print(f"IS  Trades:     {is_m['trade_count']}  (threshold: >= 100)")
    print(f"Walk-Forward:   {wf['pass_count']}/{len(WF_WINDOWS)} windows  (threshold: >= 3)")
    print(f"Param Sens:     max {sens['max_reduction_pct']:.1f}% reduction  (threshold: < 50%)")
    print(f"{'='*60}")
    print(f"Output: backtests/h34_rsi2_oversold_spy/")
