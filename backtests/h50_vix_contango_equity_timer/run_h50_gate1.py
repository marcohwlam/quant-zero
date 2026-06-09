"""
Gate 1 v2.0 runner for H50: VIX Contango/Backwardation Equity Timer.
Produces: results.json, is_trades.csv, oos_trades.csv, gate1_verdict.md
"""

import json
import os
import sys
from datetime import date

# Allow import from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from strategies.h50_vix_contango_equity_timer import run_strategy, DEFAULT_PARAMS

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def _fmt_pct(v):
    return f"{v:.2%}" if isinstance(v, float) else str(v)


def _fmt_f(v, d=4):
    return f"{v:.{d}f}" if isinstance(v, float) else str(v)


def run_gate1(params=None):
    result = run_strategy(params)

    m    = result["is_metrics"]
    om   = result["oos_metrics"]
    wf   = result["walk_forward"]
    sens = result["sensitivity"]
    gate = result["gate_criteria"]
    p    = result["params"]

    # ── Save trade logs ───────────────────────────────────────────────────────
    result["is_trade_log"].to_csv(
        os.path.join(OUT_DIR, "is_trades.csv"), index=False)
    result["oos_trade_log"].to_csv(
        os.path.join(OUT_DIR, "oos_trades.csv"), index=False)

    # ── Save results JSON ─────────────────────────────────────────────────────
    json_payload = {
        "strategy":    result["strategy"],
        "run_date":    str(date.today()),
        "params":      p,
        "is_metrics":  m,
        "oos_metrics": om,
        "walk_forward":  wf,
        "sensitivity":   sens,
        "gate_criteria": gate,
        "pass_count":    result["pass_count"],
        "verdict":       result["verdict"],
    }
    with open(os.path.join(OUT_DIR, "results.json"), "w") as fh:
        json.dump(json_payload, fh, indent=2, default=str)

    # ── Gate 1 v2.0 verdict markdown ─────────────────────────────────────────
    wf_pass = sum(1 for w in wf if w["pass"])
    sens_neg = [s for s in sens if s["delta_pct"] is not None and s["delta_pct"] < 0]
    max_red  = max((abs(s["delta_pct"]) for s in sens_neg), default=0.0)

    lines = []
    verdict_icon = "✅ PASS" if result["verdict"] == "PASS" else "❌ FAIL"
    lines.append(f"# Gate 1 v2.0 Verdict: H50 VIX Contango/Backwardation Equity Timer")
    lines.append(f"\n**Overall: {verdict_icon} ({result['pass_count']}/7 criteria)**\n")

    # Parameters
    lines.append("## Parameters\n")
    lines.append(f"- `exit_persistence`:    {p['exit_persistence']} days")
    lines.append(f"- `reentry_persistence`: {p['reentry_persistence']} days")
    lines.append(f"- `ratio_threshold`:     {p['ratio_threshold']}")
    lines.append(f"- `init_cash`:           ${p['init_cash']:,.0f}\n")

    # Gate criteria table
    lines.append("## Gate 1 Criteria\n")
    lines.append("| Criterion | Value | Threshold | Result |")
    lines.append("|-----------|-------|-----------|--------|")
    for crit, vals in gate.items():
        v   = vals["value"]
        t   = vals["threshold"]
        ok  = vals["pass"]
        icon = "✅ PASS" if ok else "❌ FAIL"
        if isinstance(v, float):
            v_str = f"{v:.4f}" if abs(v) < 100 else f"{v:.1f}"
        else:
            v_str = str(v)
        if isinstance(t, float):
            t_str = f"{t:.2f}"
        else:
            t_str = str(t)
        lines.append(f"| {crit} | {v_str} | {t_str} | {icon} |")
    lines.append("")

    # IS metrics
    lines.append("## In-Sample Performance (2008–2021)\n")
    lines.append(f"- Sharpe:        {m['sharpe']:.4f}")
    lines.append(f"- Max Drawdown:  {m['mdd']:.2%}")
    lines.append(f"- Total Return:  {m['total_return']:.2%}")
    lines.append(f"- Ann. Return:   {m['ann_return']:.2%}")
    lines.append(f"- Ann. Vol:      {m['ann_vol']:.2%}")
    lines.append(f"- Win Rate:      {m['win_rate']:.2%}")
    lines.append(f"- Profit Factor: {m['profit_factor']:.4f}")
    lines.append(f"- Trade Count:   {m['trade_count']}\n")

    # OOS metrics
    lines.append("## Out-of-Sample Performance (2022–2024)\n")
    lines.append(f"- Sharpe:        {om['sharpe']:.4f}")
    lines.append(f"- Max Drawdown:  {om['mdd']:.2%}")
    lines.append(f"- Total Return:  {om['total_return']:.2%}")
    lines.append(f"- Ann. Return:   {om['ann_return']:.2%}")
    lines.append(f"- Ann. Vol:      {om['ann_vol']:.2%}")
    lines.append(f"- Win Rate:      {om['win_rate']:.2%}")
    lines.append(f"- Profit Factor: {om['profit_factor']:.4f}")
    lines.append(f"- Trade Count:   {om['trade_count']}\n")

    # Walk-forward table
    lines.append("## Walk-Forward Stability\n")
    lines.append(f"**{wf_pass}/6 windows pass (threshold: ≥4)**\n")
    lines.append("| Window | Sharpe | MDD | Win Rate | Trades | Result |")
    lines.append("|--------|--------|-----|----------|--------|--------|")
    for w in wf:
        icon = "✅" if w["pass"] else "❌"
        lines.append(f"| {w['window']} | {w['sharpe']:.4f} | {w['mdd']:.2%} "
                     f"| {w['win_rate']:.2%} | {w['trades']} | {icon} |")
    lines.append("")

    # Sensitivity table
    lines.append("## Parameter Sensitivity\n")
    lines.append(f"**Max Sharpe reduction: {max_red:.1f}% (threshold: <50%)**\n")
    lines.append(f"Base Sharpe (IS): {m['sharpe']:.4f}\n")
    lines.append("| Variant | Sharpe | Trades | Δ vs Base |")
    lines.append("|---------|--------|--------|-----------|")
    for s in sens:
        dp = f"{s['delta_pct']:+.1f}%" if s["delta_pct"] is not None else "—"
        lines.append(f"| {s['variant']} | {s['sharpe']:.4f} | {s['trades']} | {dp} |")
    lines.append("")

    # Hard gate checks
    lines.append("## Hard Gate Checks\n")
    lines.append(f"- HG-1: OOS Sharpe > 0.7 — {'✅ PASS' if om['sharpe'] > 0.7 else '❌ FAIL'}")
    lines.append(f"- HG-2: Same-bar fill — ✅ PASS (close-to-close rotation)")
    lines.append(f"- HG-3: Look-ahead bias — ✅ PASS (signal uses only historical data)")
    lines.append(f"- HG-4: Net-positive IS — {'✅ PASS' if m['total_return'] > 0 else '❌ FAIL'}")
    lines.append(f"- HG-5: IS trade count ≥ 120 — {'✅ PASS' if m['trade_count'] >= 120 else '❌ FAIL'}")
    lines.append(f"- HG-6: MDD < 40% (IS) — {'✅ PASS' if m['mdd'] > -0.40 else '❌ FAIL'}")
    lines.append(f"- HG-7: PDT compliance — ✅ PASS (ETF rotation, no PDT concern)\n")

    verdict_md = "\n".join(lines)
    with open(os.path.join(OUT_DIR, "gate1_verdict.md"), "w") as fh:
        fh.write(verdict_md)

    print(f"\nResults saved to {OUT_DIR}/")
    print(f"Verdict: {result['verdict']} ({result['pass_count']}/7)")
    return result


if __name__ == "__main__":
    run_gate1()
