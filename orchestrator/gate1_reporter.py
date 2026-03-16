"""
gate1_reporter.py
Gate 1 verdict reporter for the quant orchestrator.

Translates the orchestrator's metrics dict + proposal into a BacktestResult,
calls the Overfit Detector's gate1_verdict engine, and saves the structured
verdict to /backtests/ as both .txt (human-readable) and .json (machine).

Usage (from orchestrator main loop):
    from gate1_reporter import generate_and_save_verdict
    verdict = generate_and_save_verdict(metrics, proposal, wf_windows)
    if verdict["overall_verdict"] in ("PASS", "CONDITIONAL PASS"):
        # escalate to CEO
"""

from __future__ import annotations

import json
import sys
import datetime
from pathlib import Path


# ── Path resolution ───────────────────────────────────────────────────────────

_HERE = Path(__file__).parent
_REPO_ROOT = _HERE.parent
_BACKTESTS_DIR = _REPO_ROOT / "backtests"
_BACKTESTS_TEST_DIR = _REPO_ROOT / "backtests" / "test"  # unit test outputs go here, NOT the root
_OVERFIT_TOOLS = _REPO_ROOT / "agents" / "overfit-detector" / "tools"

# Make overfit-detector tools importable
if str(_OVERFIT_TOOLS) not in sys.path:
    sys.path.insert(0, str(_OVERFIT_TOOLS))

from gate1_verdict import BacktestResult, Gate1Verdict, generate_verdict, format_verdict  # noqa: E402


# ── Public API ────────────────────────────────────────────────────────────────

def generate_and_save_verdict(
    metrics: dict,
    proposal: dict,
    config: dict | None = None,
    output_dir: Path | None = None,
) -> dict:
    """
    Build a Gate 1 verdict from orchestrator metrics and save to /backtests/.

    Args:
        metrics: dict from orchestrator main loop (IS/OOS Sharpe, drawdowns,
                 walk-forward results, transaction cost Sharpe, etc.)
        proposal: strategy proposal dict (strategy_name, hypothesis, parameters)
        config: optional CONFIG dict from orchestrator (for test period dates)
        output_dir: override output directory (default: /backtests/); unit tests
                    should pass _BACKTESTS_TEST_DIR to avoid polluting /backtests/ root.

    Returns:
        dict with keys: overall_verdict, recommendation, confidence, txt_path, json_path
    """
    out_dir = output_dir if output_dir is not None else _BACKTESTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    strategy_name = proposal.get("strategy_name", "unknown")
    date_str = datetime.date.today().isoformat()

    # ── Build walk-forward windows list ──────────────────────────────────────
    # Expects list of (IS_sharpe, OOS_sharpe) tuples
    wf_windows = []
    raw_windows = metrics.get("wf_windows", [])  # list of window dicts
    for w in raw_windows:
        wf_windows.append((w.get("train_sharpe", 0.0), w.get("test_sharpe", 0.0)))

    # ── Determine test period from config or metrics ──────────────────────────
    if config:
        test_start = config.get("in_sample_start", "")
        test_end = config.get("out_of_sample_end", "")
    else:
        test_start = ""
        test_end = ""

    # ── Map metrics → BacktestResult ─────────────────────────────────────────
    bt = BacktestResult(
        strategy_name=strategy_name,
        strategy_version="1.0",
        test_start=test_start,
        test_end=test_end,
        is_sharpe=float(metrics.get("sharpe_in_sample", 0.0)),
        oos_sharpe=float(metrics.get("sharpe_out_of_sample", 0.0)),
        is_max_drawdown=abs(float(metrics.get("max_dd_in_sample", 0.0))),
        oos_max_drawdown=abs(float(metrics.get("max_dd_out_of_sample", 0.0))),
        win_rate=float(metrics.get("win_rate_in_sample", 0.0)),
        trade_count=int(metrics.get("trades_in_sample", 0)),
        dsr_zscore=float(metrics.get("dsr_zscore", 0.0)),
        walk_forward_windows=wf_windows,
        param_sensitivity_passed=bool(metrics.get("param_sensitivity_passed", False)),
        param_sensitivity_max_delta=float(metrics.get("param_sensitivity_max_delta", 0.0)),
        post_cost_sharpe=float(metrics.get("post_cost_sharpe_oos", metrics.get("post_cost_sharpe_is", 0.0))),
        look_ahead_bias=metrics.get("look_ahead_bias", "none"),
        economic_rationale=metrics.get("economic_rationale", "valid"),
        n_trials=int(metrics.get("n_trials", 1)),
    )

    # ── Generate verdict ──────────────────────────────────────────────────────
    verdict: Gate1Verdict = generate_verdict(bt)
    verdict_text = format_verdict(verdict)

    # ── Save outputs ──────────────────────────────────────────────────────────
    base_name = f"{_sanitize(strategy_name)}_{date_str}"
    txt_path = out_dir / f"{base_name}.txt"
    json_path = out_dir / f"{base_name}.json"

    txt_path.write_text(verdict_text)

    # Combine IS + OOS equity curves and trade logs into unified time-series
    equity_curve = metrics.get("equity_curve_is", []) + metrics.get("equity_curve_oos", [])
    trade_log = metrics.get("trade_log_is", []) + metrics.get("trade_log_oos", [])

    verdict_json = {
        "strategy_name": strategy_name,
        "date": date_str,
        "overall_verdict": verdict.overall_verdict,
        "recommendation": verdict.recommendation,
        "confidence": verdict.confidence,
        "disqualify_reason": verdict.disqualify_reason,
        "oos_data_quality": metrics.get("oos_data_quality", None),
        "metrics": [
            {
                "name": m.name,
                "value": m.value,
                "threshold": m.threshold,
                "passed": m.passed,
                "auto_disqualify": m.auto_disqualify,
            }
            for m in verdict.metrics
        ],
        "equity_curve": equity_curve,
        "trade_log": trade_log,
        "txt_path": str(txt_path),
    }
    json_path.write_text(json.dumps(verdict_json, indent=2))

    return {
        "overall_verdict": verdict.overall_verdict,
        "recommendation": verdict.recommendation,
        "confidence": verdict.confidence,
        "txt_path": str(txt_path),
        "json_path": str(json_path),
    }


def _sanitize(name: str) -> str:
    """Convert strategy name to a safe filename component."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:64]


# ── Unit tests ────────────────────────────────────────────────────────────────

def _run_tests():
    """Smoke tests for PASS, FAIL, and CONDITIONAL PASS cases."""
    import traceback

    _pass_metrics = {
        "sharpe_in_sample": 1.5, "sharpe_out_of_sample": 1.1,
        "max_dd_in_sample": 0.12, "max_dd_out_of_sample": 0.15,
        "win_rate_in_sample": 0.55, "trades_in_sample": 200,
        "dsr_zscore": 1.8,
        "wf_windows": [
            {"train_sharpe": 1.4, "test_sharpe": 1.1},
            {"train_sharpe": 1.6, "test_sharpe": 1.2},
            {"train_sharpe": 1.5, "test_sharpe": 1.0},
            {"train_sharpe": 1.3, "test_sharpe": 1.05},
        ],
        "param_sensitivity_passed": True, "param_sensitivity_max_delta": 0.12,
        "post_cost_sharpe_oos": 0.95,
        "n_trials": 5,
    }
    _pass_proposal = {"strategy_name": "TestMomentum"}
    _pass_config = {"in_sample_start": "2018-01-01", "out_of_sample_end": "2023-12-31"}

    _fail_metrics = dict(_pass_metrics)
    _fail_metrics["sharpe_in_sample"] = 0.5  # below Gate 1 threshold

    _cond_metrics = dict(_pass_metrics)
    _cond_metrics["dsr_zscore"] = -0.5  # DSR fails → conditional

    tests = [
        ("PASS case", _pass_metrics, _pass_proposal, _pass_config, "PASS"),
        ("FAIL case", _fail_metrics, {"strategy_name": "FailStrat"}, _pass_config, "FAIL"),
    ]

    passed = 0
    for name, m, p, c, expected in tests:
        try:
            result = generate_and_save_verdict(m, p, c, output_dir=_BACKTESTS_TEST_DIR)
            verdict = result["overall_verdict"]
            if verdict == expected:
                print(f"  [OK]   {name}: {verdict}")
                passed += 1
            else:
                print(f"  [FAIL] {name}: expected {expected}, got {verdict}")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            traceback.print_exc()

    # CONDITIONAL PASS: all quant passes but overfitting risk high (dsr_zscore <= 0)
    try:
        result = generate_and_save_verdict(_cond_metrics, {"strategy_name": "CondStrat"}, _pass_config, output_dir=_BACKTESTS_TEST_DIR)
        verdict = result["overall_verdict"]
        if verdict in ("CONDITIONAL PASS", "FAIL"):
            print(f"  [OK]   CONDITIONAL PASS case: {verdict} (acceptable)")
            passed += 1
        else:
            print(f"  [FAIL] CONDITIONAL PASS case: unexpected {verdict}")
    except Exception as e:
        print(f"  [ERROR] CONDITIONAL PASS case: {e}")

    print(f"\n{passed}/3 tests passed")
    return passed == 3


if __name__ == "__main__":
    print("Running gate1_reporter smoke tests...\n")
    ok = _run_tests()
    sys.exit(0 if ok else 1)
