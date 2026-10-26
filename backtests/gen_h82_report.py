"""Generate H82 HTML report from saved JSON metrics."""
import json, sys

TODAY = "2026-06-17"
STRATEGY_NAME = "H82_MinerviniVCPBreakout"
OUTDIR = "/repos/quant-zero/backtests"

with open(f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}.json") as f:
    m = json.load(f)

gate1_pass = m["gate1_pass"]
checks = m["gate1_checks"]
overall = "PASS" if gate1_pass else "FAIL"
color = "#22c55e" if gate1_pass else "#ef4444"

is_pf = m.get("is_profit_factor")
oos_pf = m.get("oos_profit_factor")
is_pf_str = f"{is_pf:.4f}" if is_pf is not None else "inf"
oos_pf_str = f"{oos_pf:.4f}" if oos_pf is not None else "inf"

check_rows = ""
for k, v in checks.items():
    bg = "#f0fdf4" if v else "#fef2f2"
    check_rows += f'<tr style="background:{bg}"><td>{k}</td><td>{"PASS ✓" if v else "FAIL ✗"}</td></tr>\n'

wf_rows = ""
for w in m.get("wf_windows", []):
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

dsr_pass = m.get("dsr_pass", False)
perm_pass = m.get("permutation_test_pass", False)
mc_p5 = m.get("mc_p5_sharpe", 0.0)
mc_pass = mc_p5 >= 0.5
post_cost = m.get("post_cost_sharpe", 0.0)
post_cost_pass = post_cost > 0

html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>H82 MinerviniVCPBreakout Gate 1 Report</title>
<style>
body{{font-family:monospace;max-width:900px;margin:auto;padding:20px;background:#f9fafb}}
h1{{color:#1e293b}}h2{{color:#334155;border-bottom:1px solid #e2e8f0}}
.verdict{{font-size:2em;font-weight:bold;color:{color};padding:10px;border:2px solid {color};display:inline-block}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}
th,td{{border:1px solid #e2e8f0;padding:6px 10px;text-align:left}}
th{{background:#f1f5f9}}
.pass{{color:#16a34a;font-weight:bold}}.fail{{color:#dc2626;font-weight:bold}}
</style></head>
<body>
<h1>H82 Minervini VCP Breakout — Gate 1 Report</h1>
<p>Date: {TODAY} | Universe: {m.get("universe_size","?")} tickers | IS: 2018-2023 | OOS: 2024-2025</p>
<div class="verdict">{overall}</div>

<h2>Core Metrics</h2>
<table>
<tr><th>Metric</th><th>IS</th><th>OOS</th><th>Gate 1 Threshold</th></tr>
<tr><td>Sharpe Ratio</td><td>{m["is_sharpe"]:.4f}</td><td>{m["oos_sharpe"]:.4f}</td><td>IS&gt;1.0 / OOS&gt;0.7</td></tr>
<tr><td>CAGR</td><td>{m["is_cagr"]:.2%}</td><td>{m["oos_cagr"]:.2%}</td><td>IS≥10%</td></tr>
<tr><td>Max Drawdown</td><td>{m["is_max_drawdown"]:.2%}</td><td>{m["oos_max_drawdown"]:.2%}</td><td>IS&lt;15% (hard) / OOS&lt;25%</td></tr>
<tr><td>Win Rate</td><td>{m["is_win_rate"]:.2%}</td><td>{m["oos_win_rate"]:.2%}</td><td>&gt;50%</td></tr>
<tr><td>Profit Factor</td><td>{is_pf_str}</td><td>{oos_pf_str}</td><td>&gt;1.0</td></tr>
<tr><td>Trade Count</td><td>{m["is_trade_count"]}</td><td>{m["oos_trade_count"]}</td><td>≥100</td></tr>
</table>

<h2>Statistical Rigor</h2>
<table>
<tr><th>Test</th><th>Result</th><th>Pass/Fail</th></tr>
<tr><td>DSR z-score</td><td>{m["dsr"]:.4f}</td><td class="{"pass" if dsr_pass else "fail"}">{"PASS" if dsr_pass else "FAIL"}</td></tr>
<tr><td>Permutation p-value</td><td>{m["permutation_p_value"]:.4f}</td><td class="{"pass" if perm_pass else "fail"}">{"PASS" if perm_pass else "FAIL"}</td></tr>
<tr><td>MC p5 Sharpe</td><td>{mc_p5:.4f}</td><td class="{"pass" if mc_pass else "fail"}">{"PASS" if mc_pass else "FAIL"}</td></tr>
<tr><td>MC Median Sharpe</td><td>{m.get("mc_median_sharpe", 0):.4f}</td><td>—</td></tr>
<tr><td>Bootstrap Sharpe CI</td><td>[{m["bootstrap_ci_lower"]:.4f}, {m["bootstrap_ci_upper"]:.4f}]</td><td>—</td></tr>
<tr><td>Bootstrap MDD CI</td><td>[{m["mdd_ci_low"]:.4f}, {m["mdd_ci_high"]:.4f}]</td><td>—</td></tr>
<tr><td>Post-cost IS Sharpe</td><td>{post_cost:.4f}</td><td class="{"pass" if post_cost_pass else "fail"}">{"PASS" if post_cost_pass else "FAIL"}</td></tr>
<tr><td>Market impact (est)</td><td>{m.get("market_impact_bps", 3.0):.2f} bps</td><td>—</td></tr>
</table>

<h2>Walk-Forward Windows</h2>
<table>
<tr><th>#</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>Consistency</th><th>Result</th></tr>
{wf_rows}
</table>
<p>WF Pass: {m["wf_windows_passed"]}/{m["wf_windows_total"]} | Consistency: {m["wf_consistency_score"]:.3f} | Std: {m["walk_forward_variance"]:.3f} | Min: {m["wf_sharpe_min"]:.3f}</p>

<h2>Gate 1 Checks</h2>
<table>
<tr><th>Check</th><th>Result</th></tr>
{check_rows}
</table>

<h2>OOS Data Quality</h2>
<p>Recommendation: <strong>{m.get("oos_data_quality", {}).get("recommendation", "N/A")}</strong> | Coverage: {m.get("oos_data_quality", {}).get("oos_data_coverage_pct", 100):.1f}%</p>

<h2>Strategy Info</h2>
<p>Universe: {m.get("universe_size","?")} tickers | VCP signal days: {m.get("vcp_signal_days","?")} | Total signals: {m.get("total_vcp_signals","?")}</p>
<p>Liquidity-constrained trades IS: {m.get("liquidity_flags_is",0)} | OOS: {m.get("liquidity_flags_oos",0)}</p>

<h2>VCP Parameters (Post-Fix)</h2>
<table>
<tr><th>Parameter</th><th>Value</th><th>Note</th></tr>
<tr><td>vcp_contraction_ratio</td><td>0.99</td><td>Loosened from 0.75 (QUA-336)</td></tr>
<tr><td>vcp_volume_dryup_ratio</td><td>0.95</td><td>Loosened from 0.60 (QUA-336)</td></tr>
<tr><td>breakout_volume_ratio</td><td>1.05</td><td>Loosened from 1.40 (QUA-336)</td></tr>
<tr><td>min_swing_pct</td><td>0.03</td><td>Loosened from 0.04 (QUA-336)</td></tr>
</table>

</body></html>
"""

report_path = f"{OUTDIR}/{STRATEGY_NAME}_{TODAY}_report.html"
with open(report_path, "w") as f:
    f.write(html)
print(f"Saved: {report_path}")
