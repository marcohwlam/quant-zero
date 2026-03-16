"""
gate1_verdict_validator.py
Structured Gate 1 verdict template enforcement.

Validates that a verdict JSON dict produced by gate1_reporter.py contains all
required fields before it is written to disk and sent to Risk Director review.
Prevents silently incomplete verdicts from reaching downstream reviewers.

Motivation: verdicts were previously written manually by Overfit Detector with
no automated field-presence check, allowing required sections to be omitted
without detection (source: CEO heartbeat QUA-219, Engineering Director QUA-221).

Usage
-----
    from gate1_verdict_validator import validate_verdict_json, VerdictValidationError

    issues = validate_verdict_json(verdict_json)
    if issues:
        raise VerdictValidationError(verdict_json.get("strategy_name", "?"), issues)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Required top-level fields in every verdict JSON ──────────────────────────

_REQUIRED_TOP_LEVEL_FIELDS: list[str] = [
    "strategy_name",
    "date",
    "overall_verdict",
    "recommendation",
    "confidence",
    "metrics",
]

# `disqualify_reason` is allowed to be None/null — not required to be non-null.
# `oos_data_quality` is optional (added by QUA-220 pipeline).

# ── overall_verdict must be one of these values ───────────────────────────────

_VALID_VERDICTS = {"PASS", "FAIL", "CONDITIONAL PASS"}

# ── Required metric names that must appear in the `metrics` array ─────────────
# Derived from gate1_verdict.py generate_verdict() and criteria.md v1.2.

_REQUIRED_METRIC_NAMES: list[str] = [
    "IS Sharpe",
    "OOS Sharpe",
    "IS Max Drawdown",
    "OOS Max Drawdown",
    "Win Rate",
    "Trade count",                         # exact name from gate1_verdict.py
    "Deflated Sharpe Ratio (z-score)",     # exact name from gate1_verdict.py
    "Walk-forward windows passed",
    "Walk-forward OOS/IS consistency",
    "Post-cost Sharpe",
    "Parameter sensitivity",
    "Test period",
]

# ── Required sub-fields on each metric entry ──────────────────────────────────

_REQUIRED_METRIC_SUBFIELDS: list[str] = ["name", "value", "threshold", "passed"]


# ── Public types ─────────────────────────────────────────────────────────────

@dataclass
class VerdictValidationIssue:
    """A single validation finding on a verdict JSON."""
    field: str          # dot-path to the offending field, e.g. "metrics[IS Sharpe]"
    severity: str       # "error" (required) or "warning" (advisory)
    message: str        # human-readable description

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.field}: {self.message}"


@dataclass
class VerdictValidationResult:
    """Aggregated validation result for one verdict JSON."""
    strategy_name: str
    issues: list[VerdictValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    def summary(self) -> str:
        if not self.issues:
            return f"[{self.strategy_name}] Verdict template VALID — no issues."
        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity == "warning"]
        lines = [f"[{self.strategy_name}] Verdict template validation: "
                 f"{len(errors)} error(s), {len(warnings)} warning(s)"]
        for issue in self.issues:
            lines.append(f"  {issue}")
        return "\n".join(lines)


class VerdictValidationError(Exception):
    """Raised when a verdict JSON fails required-field validation."""

    def __init__(self, strategy_name: str, issues: list[VerdictValidationIssue]) -> None:
        self.strategy_name = strategy_name
        self.issues = issues
        errors = [str(i) for i in issues if i.severity == "error"]
        super().__init__(
            f"Gate 1 verdict template validation FAILED for '{strategy_name}': "
            f"{len(errors)} error(s):\n" + "\n".join(errors)
        )


# ── Public API ────────────────────────────────────────────────────────────────

def validate_verdict_json(verdict_json: dict[str, Any]) -> VerdictValidationResult:
    """
    Validate a Gate 1 verdict JSON dict for template compliance.

    Checks:
      1. All required top-level fields are present and non-null.
      2. `overall_verdict` is one of the allowed values.
      3. All required metric names appear in the `metrics` array.
      4. Each metric entry has all required sub-fields (name, value, threshold, passed).
      5. The `metrics` array is non-empty.

    Args:
        verdict_json: The verdict dict as produced by gate1_reporter.py.

    Returns:
        VerdictValidationResult with any issues found. Check `.has_errors` to
        determine if saving should be blocked.
    """
    strategy_name = verdict_json.get("strategy_name", "<unknown>")
    result = VerdictValidationResult(strategy_name=strategy_name)

    # ── 1. Required top-level fields ──────────────────────────────────────
    for fname in _REQUIRED_TOP_LEVEL_FIELDS:
        val = verdict_json.get(fname)
        if val is None:
            result.issues.append(VerdictValidationIssue(
                field=fname,
                severity="error",
                message=f"Required field is missing or null.",
            ))

    # ── 2. overall_verdict value check ────────────────────────────────────
    ov = verdict_json.get("overall_verdict")
    if ov is not None and ov not in _VALID_VERDICTS:
        result.issues.append(VerdictValidationIssue(
            field="overall_verdict",
            severity="error",
            message=(
                f"Value '{ov}' is not a valid verdict. "
                f"Must be one of: {sorted(_VALID_VERDICTS)}"
            ),
        ))

    # ── 3. Metrics array non-empty ────────────────────────────────────────
    metrics_list = verdict_json.get("metrics")
    if not isinstance(metrics_list, list) or len(metrics_list) == 0:
        result.issues.append(VerdictValidationIssue(
            field="metrics",
            severity="error",
            message="'metrics' must be a non-empty list.",
        ))
        # Cannot continue with metric checks
        return result

    # ── 4. Required metric sub-field check ────────────────────────────────
    for idx, metric_entry in enumerate(metrics_list):
        if not isinstance(metric_entry, dict):
            result.issues.append(VerdictValidationIssue(
                field=f"metrics[{idx}]",
                severity="error",
                message="Metric entry must be a dict.",
            ))
            continue
        for subfield in _REQUIRED_METRIC_SUBFIELDS:
            if subfield not in metric_entry:
                result.issues.append(VerdictValidationIssue(
                    field=f"metrics[{idx}].{subfield}",
                    severity="error",
                    message=f"Required sub-field '{subfield}' missing from metric entry.",
                ))

    # ── 5. Required metric names present ──────────────────────────────────
    present_metric_names = {
        m.get("name") for m in metrics_list if isinstance(m, dict) and "name" in m
    }
    for required_name in _REQUIRED_METRIC_NAMES:
        if required_name not in present_metric_names:
            result.issues.append(VerdictValidationIssue(
                field=f"metrics[{required_name!r}]",
                severity="error",
                message=(
                    f"Required metric '{required_name}' not found in metrics array. "
                    f"Present metrics: {sorted(present_metric_names)}"
                ),
            ))

    # ── 6. Advisory: oos_data_quality missing ─────────────────────────────
    if "oos_data_quality" not in verdict_json or verdict_json["oos_data_quality"] is None:
        result.issues.append(VerdictValidationIssue(
            field="oos_data_quality",
            severity="warning",
            message=(
                "oos_data_quality report is absent. "
                "OOS NaN validation (QUA-220) may not have run."
            ),
        ))

    return result


def enforce_verdict_template(verdict_json: dict[str, Any]) -> VerdictValidationResult:
    """
    Validate and raise VerdictValidationError if any errors are found.

    This is the strict enforcement entry point. Call before writing verdict to disk.

    Args:
        verdict_json: The verdict dict to validate.

    Returns:
        VerdictValidationResult (only returns if no errors).

    Raises:
        VerdictValidationError: if any error-severity issues are found.
    """
    result = validate_verdict_json(verdict_json)
    if result.has_errors:
        raise VerdictValidationError(result.strategy_name, result.issues)
    return result


# ── Smoke tests ───────────────────────────────────────────────────────────────

def _make_valid_verdict(strategy_name: str = "TestStrategy") -> dict[str, Any]:
    """Build a minimal valid verdict dict for testing."""
    metrics = [
        {"name": n, "value": "1.2", "threshold": "> 1.0", "passed": True}
        for n in _REQUIRED_METRIC_NAMES
    ]
    return {
        "strategy_name": strategy_name,
        "date": "2026-03-16",
        "overall_verdict": "PASS",
        "recommendation": "Proceed to paper trading.",
        "confidence": "HIGH",
        "disqualify_reason": None,
        "oos_data_quality": {"recommendation": "PASS"},
        "metrics": metrics,
    }


def _run_tests() -> bool:
    import traceback

    passed = 0
    total = 0

    def _case(name: str, fn) -> None:
        nonlocal passed, total
        total += 1
        try:
            fn()
            print(f"  [OK]  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
        except Exception:
            print(f"  [ERROR] {name}")
            traceback.print_exc()

    # Valid verdict → no errors
    def test_valid():
        v = _make_valid_verdict()
        r = validate_verdict_json(v)
        assert not r.has_errors, r.summary()

    # Missing top-level field → error
    def test_missing_top_level():
        v = _make_valid_verdict()
        del v["overall_verdict"]
        r = validate_verdict_json(v)
        assert r.has_errors
        fields = [i.field for i in r.issues if i.severity == "error"]
        assert "overall_verdict" in fields, fields

    # Invalid overall_verdict value → error
    def test_bad_verdict_value():
        v = _make_valid_verdict()
        v["overall_verdict"] = "MAYBE"
        r = validate_verdict_json(v)
        assert r.has_errors
        assert any(i.field == "overall_verdict" for i in r.issues if i.severity == "error")

    # Missing required metric → error
    def test_missing_metric():
        v = _make_valid_verdict()
        v["metrics"] = [m for m in v["metrics"] if m["name"] != "IS Sharpe"]
        r = validate_verdict_json(v)
        assert r.has_errors, r.summary()
        assert r.has_errors
        assert any("IS Sharpe" in i.field for i in r.issues)

    # Metric missing subfield → error
    def test_metric_missing_subfield():
        v = _make_valid_verdict()
        # Remove "passed" from first metric
        v["metrics"][0] = {k: val for k, val in v["metrics"][0].items() if k != "passed"}
        r = validate_verdict_json(v)
        assert r.has_errors
        assert any(".passed" in i.field for i in r.issues)

    # Empty metrics list → error
    def test_empty_metrics():
        v = _make_valid_verdict()
        v["metrics"] = []
        r = validate_verdict_json(v)
        assert r.has_errors
        assert any(i.field == "metrics" for i in r.issues)

    # Missing oos_data_quality → warning only (not error)
    def test_missing_dq_warning():
        v = _make_valid_verdict()
        del v["oos_data_quality"]
        r = validate_verdict_json(v)
        assert not r.has_errors, r.summary()
        assert r.has_warnings
        assert any(i.field == "oos_data_quality" for i in r.issues if i.severity == "warning")

    # enforce_verdict_template raises on error
    def test_enforce_raises():
        v = _make_valid_verdict()
        del v["strategy_name"]
        try:
            enforce_verdict_template(v)
            assert False, "Should have raised VerdictValidationError"
        except VerdictValidationError:
            pass

    _case("valid verdict → no errors", test_valid)
    _case("missing top-level field → error", test_missing_top_level)
    _case("invalid overall_verdict value → error", test_bad_verdict_value)
    _case("missing required metric → error", test_missing_metric)
    _case("metric missing subfield → error", test_metric_missing_subfield)
    _case("empty metrics list → error", test_empty_metrics)
    _case("missing oos_data_quality → warning only", test_missing_dq_warning)
    _case("enforce_verdict_template raises on error", test_enforce_raises)

    print(f"\n{passed}/{total} tests passed")
    return passed == total


if __name__ == "__main__":
    print("Running gate1_verdict_validator smoke tests...\n")
    import sys
    ok = _run_tests()
    sys.exit(0 if ok else 1)
