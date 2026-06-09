#!/usr/bin/env python3
"""
H60 Gate 1 Backtest Runner — QUA-166
Intraday VWAP Mean Reversion — 2022-01 to 2024-12

Outputs:
  backtests/h60_intraday_vwap_mean_reversion_2026-06-09.json       — full metrics
  backtests/h60_intraday_vwap_mean_reversion_2026-06-09_report.md  — Gate 1 report
  backtests/h60_intraday_vwap_mean_reversion_2026-06-09_verdict.txt

Usage:
  cd /repos/quant-zero
  .venv/bin/python3 backtests/run_h60_gate1.py
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.h60_intraday_vwap_mean_reversion import (
    PARAMETERS,
    run_strategy,
    compute_metrics,
    compute_daily_pnl,
    WF_WINDOWS,
)
from pipelines.minute_bar_store import MinuteBarStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

OUT_DIR = Path(__file__).parent
TODAY = date.today().isoformat()
SLUG = f"h60_intraday_vwap_mean_reversion_{TODAY}"


def gate1_verdict(results: dict) -> tuple[str, list]:
    """Evaluate Gate 1 criteria and return (PASS|FAIL, reasons)."""
    primary = results["primary"]
    gate1 = primary["gate1_eval"]
    wf = primary["wf_stability"]
    oos = primary["oos_summary"]
    is_sum = primary["is_summary"]

    failures = []
    if not gate1["is_sharpe_pass"]:
        failures.append(f"IS Sharpe {is_sum['sharpe']:.3f} < 1.0 threshold")
    if not gate1["oos_sharpe_pass"]:
        failures.append(f"OOS Sharpe {oos['sharpe']:.3f} < 0.7 threshold")
    if not gate1["mdd_pass"]:
        failures.append(f"Max drawdown {oos['max_drawdown']:.1%} > -20% gate")
    if not gate1["min_trades_pass"]:
        failures.append(f"IS trade count {is_sum['trade_count']} < 100 minimum")
    if not gate1["wf_stability_pass"]:
        failures.append(f"WF stability {wf['windows_profitable']}/{wf['total_windows']} < 3/6")

    verdict = "PASS" if not failures else "FAIL"
    return verdict, failures


def format_report(results: dict, verdict: str, failures: list) -> str:
    primary = results["primary"]
    robustness = results["robustness"]
    is_sum = primary["is_summary"]
    oos_sum = primary["oos_summary"]
    wf = primary["wf_stability"]
    wf_windows = primary["wf_windows"]
    params = primary["parameters"]

    lines = [
        f"# H60 Gate 1 Backtest Report",
        f"",
        f"**Strategy:** Intraday VWAP Mean Reversion",
        f"**Date:** {TODAY}",
        f"**Issue:** QUA-166",
        f"**Instrument (primary):** {primary['symbol']}",
        f"**Instrument (robustness):** {robustness['symbol']}",
        f"**Hypothesis:** research/hypotheses/60_intraday_vwap_mean_reversion.md (v1.2)",
        f"",
        f"---",
        f"",
        f"## Gate 1 Verdict: {verdict}",
        "",
    ]

    if failures:
        lines.append("### Failures")
        for f in failures:
            lines.append(f"- {f}")
        lines.append("")
    else:
        lines.append("All Gate 1 criteria passed.")
        lines.append("")

    lines += [
        "---",
        "",
        "## Key Metrics (SPY Primary)",
        "",
        "| Metric | IS (2022–2023) | OOS (WF avg) | Gate |",
        "|---|---|---|---|",
        f"| Net Sharpe (annualized) | {is_sum['sharpe']:.3f} | {oos_sum['sharpe']:.3f} | IS > 1.0, OOS > 0.7 |",
        f"| Max Drawdown | {is_sum['max_drawdown']:.1%} | {oos_sum['max_drawdown']:.1%} | < -20% |",
        f"| Win Rate | {is_sum['win_rate']:.1%} | {oos_sum['win_rate']:.1%} | — |",
        f"| Trade Count | {is_sum['trade_count']} | {oos_sum['trade_count']} | IS ≥ 100 |",
        f"| Profit Factor | {is_sum['profit_factor']:.3f} | {oos_sum['profit_factor']:.3f} | — |",
        f"| Avg P&L / trade (bps) | {is_sum['avg_profit_per_trade_bps']:.2f} | {oos_sum['avg_profit_per_trade_bps']:.2f} | > 0 |",
        f"| Avg bars held | {is_sum['avg_bars_held']:.1f} | {oos_sum['avg_bars_held']:.1f} | — |",
        f"| Total return | {is_sum['total_return_pct']:.2f}% | {oos_sum['total_return_pct']:.2f}% | — |",
        "",
        "### WF Stability",
        f"- Profitable OOS windows: {wf['windows_profitable']}/{wf['total_windows']}",
        f"- Stability fraction: {wf['stability_fraction']:.0%}",
        f"- Gate (≥ 3/6): {'PASS' if wf['stability_pass'] else 'FAIL'}",
        "",
        "### Walk-Forward Window Detail",
        "",
        "| Window | IS Sharpe | OOS Sharpe | OOS Trades | OOS Win% |",
        "|---|---|---|---|---|",
    ]

    for w in wf_windows:
        is_m = w["is"]
        oos_m = w["oos"]
        lines.append(
            f"| W{w['window']} IS {w['is_start'][:7]}–{w['is_end'][:7]} → OOS {w['oos_start'][:7]} "
            f"| {is_m['sharpe']:.3f} | {oos_m['sharpe']:.3f} | {oos_m['trade_count']} | {oos_m['win_rate']:.1%} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Robustness (QQQ)",
        "",
        f"| Metric | IS Sharpe | OOS Sharpe | IS Trades |",
        f"|---|---|---|---|",
        f"| QQQ | {robustness['is_summary']['sharpe']:.3f} | {robustness['oos_summary']['sharpe']:.3f} | {robustness['is_summary']['trade_count']} |",
        "",
        "---",
        "",
        "## Parameters (Baseline — committed before IS optimization)",
        "",
    ]
    for k, v in params.items():
        if isinstance(v, (int, float, str)):
            lines.append(f"- `{k}`: {v}")

    lines += [
        "",
        "---",
        "",
        "## Exit Reason Distribution (OOS)",
        "",
    ]
    for reason, count in oos_sum.get("exit_reasons", {}).items():
        pct = count / max(oos_sum["trade_count"], 1) * 100
        lines.append(f"- {reason}: {count} ({pct:.1f}%)")

    lines += [
        "",
        "---",
        "",
        "## Data Quality Notes",
        "",
        "- **Universe:** SPY (continuous ETF, no survivorship bias)",
        "- **Price adjustments:** Alpaca split-adjusted data (`adjustment=split`)",
        "- **Data source:** Alpaca IEX free feed (1-min OHLCV)",
        "- **VWAP formula:** Typical price = (H+L+C)/3 (per hypothesis)",
        "- **VPIN:** BVC-based rolling window, 50-bar default",
        "- **Signal-to-fill delay:** 1 bar enforced via lagged features",
        "- **Intraday flat:** Hard exit at 15:00 ET enforced",
        "- **PDT:** Intraday round-trips; $25K+ account required (Gate 8 compliant)",
        "- **Earnings exclusion:** Not explicitly excluded; VPIN gate provides primary filter",
        "",
        "---",
        "",
        "## Known Overfitting Risks (from hypothesis)",
        "",
        "1. Kissell (2014) IC estimate may be stale post-2015 HFT proliferation — 2022–2024 backtest is key test",
        "2. VPIN parameter sensitivity (Andersen-Bondarenko 2014 critique) — validate VPIN gate OOS separately",
        "3. Midday window (10:30–14:30) is a priori from Harris (2003), not IS-optimized",
        "4. Short-leg dependency — long-only variant available but Sharpe degrades ~40%",
        "",
        "---",
        "",
        "## Files",
        "",
        f"- Metrics: `backtests/{SLUG}.json`",
        f"- Report: `backtests/{SLUG}_report.md`",
        f"- Verdict: `backtests/{SLUG}_verdict.txt`",
    ]

    return "\n".join(lines)


def main():
    log.info("=== H60 Gate 1 Backtest — QUA-166 ===")
    log.info("Parameters: %s", {k: v for k, v in PARAMETERS.items() if isinstance(v, (int, float, str))})

    store = MinuteBarStore()

    # Run full backtest (data fetch + walk-forward)
    results = run_strategy(
        start="2022-01-01",
        end="2024-12-31",
        params=PARAMETERS,
        store=store,
    )

    # Gate 1 evaluation
    verdict, failures = gate1_verdict(results)
    log.info("Gate 1 verdict: %s", verdict)
    if failures:
        for f in failures:
            log.warning("  FAIL: %s", f)

    # Save JSON metrics (excluding large trade logs for the main file)
    metrics_out = {
        "strategy": "H60_IntraVWAPMeanReversion",
        "date": TODAY,
        "issue": "QUA-166",
        "verdict": verdict,
        "gate1_failures": failures,
        "parameters": {k: v for k, v in PARAMETERS.items() if isinstance(v, (int, float, str))},
        "primary": {
            "symbol": results["primary"]["symbol"],
            "is_summary": results["primary"]["is_summary"],
            "oos_summary": results["primary"]["oos_summary"],
            "wf_stability": results["primary"]["wf_stability"],
            "wf_windows": [
                {k: v for k, v in w.items() if k not in ("is_trade_log", "oos_trade_log")}
                for w in results["primary"]["wf_windows"]
            ],
            "cost_to_gross_ratio": results["primary"]["cost_to_gross_ratio"],
            "gate1_eval": results["primary"]["gate1_eval"],
        },
        "robustness": {
            "symbol": results["robustness"]["symbol"],
            "is_summary": results["robustness"]["is_summary"],
            "oos_summary": results["robustness"]["oos_summary"],
            "wf_stability": results["robustness"]["wf_stability"],
        },
    }

    json_path = OUT_DIR / f"{SLUG}.json"
    json_path.write_text(json.dumps(metrics_out, indent=2, default=str))
    log.info("Metrics saved: %s", json_path)

    # Save trade logs separately
    all_oos_trades = results["primary"]["oos_trade_log"]
    trades_path = OUT_DIR / f"{SLUG}_oos_trades.json"
    trades_path.write_text(json.dumps(all_oos_trades, indent=2, default=str))
    log.info("OOS trade log saved: %s (%d trades)", trades_path, len(all_oos_trades))

    # Save report
    report_text = format_report(results, verdict, failures)
    report_path = OUT_DIR / f"{SLUG}_report.md"
    report_path.write_text(report_text)
    log.info("Report saved: %s", report_path)

    # Save verdict
    verdict_lines = [
        f"H60 Gate 1 Verdict: {verdict}",
        f"Date: {TODAY}",
        f"Issue: QUA-166",
        f"",
        f"IS Sharpe (SPY): {results['primary']['is_summary']['sharpe']:.4f}",
        f"OOS Sharpe (SPY): {results['primary']['oos_summary']['sharpe']:.4f}",
        f"IS Max Drawdown: {results['primary']['is_summary']['max_drawdown']:.4f}",
        f"OOS Max Drawdown: {results['primary']['oos_summary']['max_drawdown']:.4f}",
        f"IS Trade Count: {results['primary']['is_summary']['trade_count']}",
        f"WF Stability: {results['primary']['wf_stability']['windows_profitable']}/{results['primary']['wf_stability']['total_windows']}",
        f"",
    ]
    if failures:
        verdict_lines.append("Gate 1 Failures:")
        for f in failures:
            verdict_lines.append(f"  - {f}")
    else:
        verdict_lines.append("All Gate 1 criteria: PASS")

    verdict_path = OUT_DIR / f"{SLUG}_verdict.txt"
    verdict_path.write_text("\n".join(verdict_lines))
    log.info("Verdict saved: %s", verdict_path)

    return verdict, results


if __name__ == "__main__":
    verdict, _ = main()
    sys.exit(0 if verdict == "PASS" else 1)
