"""
walk_forward_evaluator.py
Walk-Forward Consistency Evaluator for Gate 1 Overfitting Detection

Evaluates whether a strategy's walk-forward results are consistent:
  - OOS Sharpe must be within 30% of IS Sharpe for each window
  - At least 3 of 4 windows must pass that consistency check

Usage:
    from walk_forward_evaluator import evaluate_walk_forward, WalkForwardVerdict

    windows = [
        (1.5, 1.1),   # (IS_sharpe, OOS_sharpe) for window 1
        (1.4, 1.2),   # window 2
        (1.6, 1.0),   # window 3
        (1.3, 0.9),   # window 4
    ]
    verdict = evaluate_walk_forward(windows)
    print(verdict.overall_passed)
    print(verdict.summary)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple


# ── Thresholds (from criteria.md, CEO-locked) ──────────────────────────────

MIN_WINDOWS_TO_PASS = 3          # must pass at least this many windows
OOS_IS_CONSISTENCY_LIMIT = 0.30  # OOS must be within 30% of IS Sharpe
MIN_WINDOW_COUNT = 4             # require at least 4 windows for a valid test


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class WindowResult:
    """Result for a single walk-forward window."""
    window_index: int           # 1-based index
    is_sharpe: float
    oos_sharpe: float
    oos_is_ratio: float         # OOS / IS; >1 means OOS exceeded IS (good)
    oos_degradation_pct: float  # (IS - OOS) / IS; positive = degraded
    passed: bool                # True if |oos_degradation_pct| < OOS_IS_CONSISTENCY_LIMIT

    @property
    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"  Window {self.window_index}: {status}  "
            f"IS={self.is_sharpe:.3f}, OOS={self.oos_sharpe:.3f}, "
            f"ratio={self.oos_is_ratio:.3f}, "
            f"degradation={self.oos_degradation_pct:.1%}"
        )


@dataclass
class WalkForwardVerdict:
    """Overall walk-forward consistency verdict."""
    overall_passed: bool
    windows_passed: int
    windows_total: int
    windows_required: int
    per_window: List[WindowResult] = field(default_factory=list)
    oos_sharpe_mean: float = 0.0
    oos_sharpe_std: float = 0.0
    oos_is_ratio_mean: float = 0.0
    insufficient_windows: bool = False   # True if fewer than MIN_WINDOW_COUNT provided

    @property
    def summary(self) -> str:
        if self.insufficient_windows:
            return (
                f"Walk-Forward: FAIL  "
                f"(insufficient windows: {self.windows_total} < {MIN_WINDOW_COUNT} required)"
            )

        status = "PASS" if self.overall_passed else "FAIL"
        lines = [
            f"Walk-Forward Consistency: {status}  "
            f"({self.windows_passed}/{self.windows_total} windows passed, "
            f"need {self.windows_required})"
        ]
        for w in self.per_window:
            lines.append(w.summary)
        lines.append(
            f"  OOS Sharpe — mean={self.oos_sharpe_mean:.3f}, "
            f"std={self.oos_sharpe_std:.3f}"
        )
        lines.append(f"  Mean OOS/IS ratio: {self.oos_is_ratio_mean:.3f}")
        return "\n".join(lines)


# ── Core logic ─────────────────────────────────────────────────────────────

def _evaluate_window(index: int, is_sharpe: float, oos_sharpe: float) -> WindowResult:
    """
    Evaluate a single walk-forward window.

    A window passes if the OOS Sharpe degradation relative to IS Sharpe
    is strictly below OOS_IS_CONSISTENCY_LIMIT (30%).

    Edge cases:
    - IS Sharpe <= 0: window automatically fails (strategy unprofitable in-sample)
    - OOS > IS: degradation is negative (improvement); window passes
    """
    if is_sharpe <= 0:
        return WindowResult(
            window_index=index,
            is_sharpe=is_sharpe,
            oos_sharpe=oos_sharpe,
            oos_is_ratio=float("nan"),
            oos_degradation_pct=float("inf"),
            passed=False,
        )

    ratio = oos_sharpe / is_sharpe
    degradation = (is_sharpe - oos_sharpe) / is_sharpe  # positive = worse
    passed = degradation < OOS_IS_CONSISTENCY_LIMIT

    return WindowResult(
        window_index=index,
        is_sharpe=is_sharpe,
        oos_sharpe=oos_sharpe,
        oos_is_ratio=ratio,
        oos_degradation_pct=degradation,
        passed=passed,
    )


def _sample_std(values: List[float]) -> float:
    """Sample standard deviation (ddof=1). Returns 0.0 for fewer than 2 values."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(variance)


def evaluate_walk_forward(
    windows: List[Tuple[float, float]],
    min_windows_to_pass: int = MIN_WINDOWS_TO_PASS,
) -> WalkForwardVerdict:
    """
    Evaluate walk-forward consistency for a strategy.

    Args:
        windows:              List of (IS_sharpe, OOS_sharpe) tuples, one per
                              walk-forward window. Must contain at least 4 windows
                              for a valid Gate 1 evaluation.
        min_windows_to_pass:  Minimum number of windows that must individually pass
                              the OOS/IS consistency check. Default is 3 (of 4).

    Returns:
        WalkForwardVerdict with per-window breakdown, OOS statistics, and
        overall PASS/FAIL.

    Raises:
        ValueError: If windows list is empty.

    Example:
        windows = [
            (1.5, 1.1),
            (1.4, 1.2),
            (1.6, 0.9),
            (1.3, 1.0),
        ]
        verdict = evaluate_walk_forward(windows)
        assert verdict.overall_passed
    """
    if not windows:
        raise ValueError("windows list must be non-empty")

    window_results: List[WindowResult] = []
    for i, (is_sr, oos_sr) in enumerate(windows, start=1):
        window_results.append(_evaluate_window(i, is_sr, oos_sr))

    n = len(windows)
    insufficient = n < MIN_WINDOW_COUNT
    passed_count = sum(1 for w in window_results if w.passed)

    oos_values = [w.oos_sharpe for w in window_results]
    oos_mean = sum(oos_values) / n
    oos_std = _sample_std(oos_values)

    valid_ratios = [w.oos_is_ratio for w in window_results if not math.isnan(w.oos_is_ratio)]
    ratio_mean = sum(valid_ratios) / len(valid_ratios) if valid_ratios else float("nan")

    # Auto-fail on insufficient windows or not enough passing windows
    overall_passed = (not insufficient) and (passed_count >= min_windows_to_pass)

    return WalkForwardVerdict(
        overall_passed=overall_passed,
        windows_passed=passed_count,
        windows_total=n,
        windows_required=min_windows_to_pass,
        per_window=window_results,
        oos_sharpe_mean=oos_mean,
        oos_sharpe_std=oos_std,
        oos_is_ratio_mean=ratio_mean,
        insufficient_windows=insufficient,
    )


# ── CLI smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Example 1: 3 of 4 windows pass → PASS
    windows1 = [
        (1.5, 1.1),  # ratio=0.73, degradation=27% → PASS (< 30%)
        (1.4, 1.2),  # ratio=0.86, degradation=14% → PASS
        (1.6, 0.9),  # ratio=0.56, degradation=44% → FAIL
        (1.3, 1.0),  # ratio=0.77, degradation=23% → PASS
    ]
    v1 = evaluate_walk_forward(windows1)
    print(v1.summary)
    print()
    assert v1.overall_passed, "Expected PASS — 3/4 windows pass"
    assert v1.windows_passed == 3

    # Example 2: only 2 of 4 pass → FAIL
    windows2 = [
        (1.5, 1.1),  # PASS
        (1.4, 0.7),  # degradation=50% → FAIL
        (1.6, 0.8),  # degradation=50% → FAIL
        (1.3, 1.0),  # PASS
    ]
    v2 = evaluate_walk_forward(windows2)
    print(v2.summary)
    print()
    assert not v2.overall_passed, "Expected FAIL — only 2/4 windows pass"
    assert v2.windows_passed == 2

    # Example 3: only 3 windows provided → FAIL (insufficient)
    windows3 = [
        (1.5, 1.2),
        (1.4, 1.1),
        (1.6, 1.3),
    ]
    v3 = evaluate_walk_forward(windows3)
    print(v3.summary)
    print()
    assert not v3.overall_passed, "Expected FAIL — insufficient windows"
    assert v3.insufficient_windows

    # Example 4: negative IS Sharpe → window auto-fails
    windows4 = [
        (-0.5, 0.3),  # IS <= 0 → FAIL
        (1.4, 1.2),   # PASS
        (1.6, 1.3),   # PASS
        (1.3, 1.0),   # PASS
    ]
    v4 = evaluate_walk_forward(windows4)
    print(v4.summary)
    print()
    assert v4.overall_passed, "Expected PASS — 3/4 pass despite bad first window"
    assert not v4.per_window[0].passed

    print("All assertions passed.")
