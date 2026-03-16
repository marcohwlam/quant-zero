"""
param_sensitivity.py
Parameter Sensitivity Checker for Gate 1 Overfitting Detection

Evaluates whether a strategy has cliff-edge parameter sensitivity:
  - A ±20% change in any parameter causing ≥30% Sharpe degradation = FAIL

Usage:
    from param_sensitivity import check_sensitivity, SensitivityVerdict

    sweep = {
        "fast_window": [(8, 1.1), (9, 1.3), (10, 1.5), (11, 1.35), (12, 1.2)],
        "slow_window": [(18, 1.2), (20, 1.4), (22, 1.5), (24, 1.45), (26, 1.3)],
    }
    verdict = check_sensitivity(sweep, base_values={"fast_window": 10, "slow_window": 22})
    print(verdict.overall_passed)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── Thresholds (from criteria.md, CEO-locked) ──────────────────────────────

PARAM_CHANGE_THRESHOLD = 0.20   # ±20% of base value defines the sensitivity window
SHARPE_DEGRADATION_LIMIT = 0.30  # ≥30% Sharpe drop = cliff edge = FAIL


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class PointDetail:
    """Result for a single sweep point."""
    param_value: float
    sharpe: float
    pct_change_from_base: float   # relative to base param value
    sharpe_degradation_pct: float # (base_sharpe - sharpe) / base_sharpe; positive = worse
    within_window: bool           # True if |pct_change_from_base| <= PARAM_CHANGE_THRESHOLD
    is_cliff_edge: bool           # True if within_window AND sharpe_degradation_pct >= limit


@dataclass
class ParamSensitivityResult:
    """Sensitivity result for a single parameter."""
    param_name: str
    base_value: float
    base_sharpe: float
    passed: bool                          # True if no cliff edge within ±20% window
    max_degradation_pct: float            # worst Sharpe drop within window (may be negative = improvement)
    cliff_edge_values: List[float]        # param values that triggered cliff-edge failures
    details: List[PointDetail] = field(default_factory=list)

    @property
    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"{self.param_name}: {status}  "
            f"base={self.base_value}, base_sharpe={self.base_sharpe:.3f}, "
            f"max_degradation={self.max_degradation_pct:.1%}"
        )


@dataclass
class SensitivityVerdict:
    """Overall parameter sensitivity verdict across all parameters."""
    overall_passed: bool
    per_param: List[ParamSensitivityResult]
    worst_degradation_pct: float          # highest degradation across all params
    cliff_edge_params: List[str]          # names of params that failed

    @property
    def summary(self) -> str:
        status = "PASS" if self.overall_passed else "FAIL"
        lines = [f"Parameter Sensitivity: {status}"]
        for r in self.per_param:
            lines.append(f"  {r.summary}")
        if self.cliff_edge_params:
            lines.append(f"  Cliff-edge parameters: {', '.join(self.cliff_edge_params)}")
        lines.append(f"  Worst degradation within ±20% window: {self.worst_degradation_pct:.1%}")
        return "\n".join(lines)


# ── Core logic ─────────────────────────────────────────────────────────────

def _find_base_sharpe(
    sweep_points: List[Tuple[float, float]],
    base_value: float,
) -> float:
    """
    Find the Sharpe at the base parameter value.

    Looks for an exact match first; if not found, interpolates between the
    two nearest sweep points. Extrapolation is not performed — if base_value
    is outside the sweep range, the nearest endpoint is used.
    """
    if not sweep_points:
        raise ValueError("sweep_points must be non-empty")

    sorted_points = sorted(sweep_points, key=lambda t: t[0])

    # Exact match
    for v, s in sorted_points:
        if abs(v - base_value) < 1e-12:
            return s

    # Interpolation between neighbours
    values = [v for v, _ in sorted_points]
    sharpes = [s for _, s in sorted_points]

    if base_value <= values[0]:
        return sharpes[0]
    if base_value >= values[-1]:
        return sharpes[-1]

    for i in range(len(values) - 1):
        v_lo, v_hi = values[i], values[i + 1]
        if v_lo <= base_value <= v_hi:
            t = (base_value - v_lo) / (v_hi - v_lo)
            return sharpes[i] + t * (sharpes[i + 1] - sharpes[i])

    # Fallback (should not reach here)
    return sharpes[0]


def _infer_base_value(sweep_points: List[Tuple[float, float]]) -> float:
    """
    Infer the base parameter value as the median sweep point by index.

    When no explicit base is provided we assume the strategy was optimised on
    the middle of the sweep range, which is a common convention.
    """
    sorted_vals = sorted(v for v, _ in sweep_points)
    mid_idx = len(sorted_vals) // 2
    return sorted_vals[mid_idx]


def check_param_sensitivity(
    param_name: str,
    sweep_points: List[Tuple[float, float]],
    base_value: Optional[float] = None,
) -> ParamSensitivityResult:
    """
    Evaluate cliff-edge sensitivity for a single parameter.

    Args:
        param_name:    Human-readable parameter name.
        sweep_points:  List of (param_value, sharpe_ratio) tuples from the sweep.
                       At least 3 points recommended; duplicate param_values are
                       averaged.
        base_value:    The parameter value actually used in the strategy. If None,
                       inferred as the median sweep value by index.

    Returns:
        ParamSensitivityResult with per-point breakdown and overall pass/fail.

    Raises:
        ValueError: If sweep_points is empty or all Sharpe values are zero/negative.
    """
    if not sweep_points:
        raise ValueError(f"sweep_points is empty for parameter '{param_name}'")

    # Deduplicate by averaging Sharpe for identical param values
    aggregated: Dict[float, List[float]] = {}
    for v, s in sweep_points:
        aggregated.setdefault(v, []).append(s)
    deduped = [(v, sum(ss) / len(ss)) for v, ss in aggregated.items()]

    if base_value is None:
        base_value = _infer_base_value(deduped)

    base_sharpe = _find_base_sharpe(deduped, base_value)

    if base_sharpe <= 0:
        # Cannot compute meaningful degradation when base Sharpe is non-positive.
        # Strategy should have already failed OOS Sharpe > 0.7 check; flag here too.
        return ParamSensitivityResult(
            param_name=param_name,
            base_value=base_value,
            base_sharpe=base_sharpe,
            passed=False,
            max_degradation_pct=float("inf"),
            cliff_edge_values=[base_value],
            details=[],
        )

    details: List[PointDetail] = []
    cliff_edge_values: List[float] = []
    max_degradation = float("-inf")

    for v, s in sorted(deduped, key=lambda t: t[0]):
        pct_change = (v - base_value) / base_value if base_value != 0 else 0.0
        degradation = (base_sharpe - s) / base_sharpe
        within_window = abs(pct_change) <= PARAM_CHANGE_THRESHOLD
        is_cliff = within_window and degradation >= SHARPE_DEGRADATION_LIMIT

        if within_window:
            max_degradation = max(max_degradation, degradation)
        if is_cliff:
            cliff_edge_values.append(v)

        details.append(PointDetail(
            param_value=v,
            sharpe=s,
            pct_change_from_base=pct_change,
            sharpe_degradation_pct=degradation,
            within_window=within_window,
            is_cliff_edge=is_cliff,
        ))

    # If all points are outside the window, max_degradation stays -inf — no data to fail on
    if max_degradation == float("-inf"):
        max_degradation = 0.0

    passed = len(cliff_edge_values) == 0

    return ParamSensitivityResult(
        param_name=param_name,
        base_value=base_value,
        base_sharpe=base_sharpe,
        passed=passed,
        max_degradation_pct=max_degradation,
        cliff_edge_values=cliff_edge_values,
        details=details,
    )


def check_sensitivity(
    sweep: Dict[str, List[Tuple[float, float]]],
    base_values: Optional[Dict[str, float]] = None,
) -> SensitivityVerdict:
    """
    Evaluate parameter sensitivity for all parameters in a strategy sweep.

    Args:
        sweep:        Dict mapping parameter name → list of (param_value, sharpe_ratio).
                      Must contain at least one parameter.
        base_values:  Optional dict mapping parameter name → base value used in strategy.
                      For any parameter not present, the base is inferred as the
                      median sweep value.

    Returns:
        SensitivityVerdict with overall PASS/FAIL and per-parameter breakdown.

    Example:
        sweep = {
            "fast_window": [(8, 1.1), (9, 1.3), (10, 1.5), (11, 1.35), (12, 1.2)],
            "slow_window": [(18, 1.2), (20, 1.4), (22, 1.5), (24, 1.45), (26, 1.3)],
        }
        verdict = check_sensitivity(sweep, base_values={"fast_window": 10, "slow_window": 22})
    """
    if not sweep:
        raise ValueError("sweep dict must contain at least one parameter")

    base_values = base_values or {}
    results: List[ParamSensitivityResult] = []

    for param_name, points in sweep.items():
        base = base_values.get(param_name)
        result = check_param_sensitivity(param_name, points, base_value=base)
        results.append(result)

    cliff_params = [r.param_name for r in results if not r.passed]
    overall_passed = len(cliff_params) == 0

    worst_degradation = max(
        (r.max_degradation_pct for r in results if r.max_degradation_pct != float("inf")),
        default=0.0,
    )

    return SensitivityVerdict(
        overall_passed=overall_passed,
        per_param=results,
        worst_degradation_pct=worst_degradation,
        cliff_edge_params=cliff_params,
    )


# ── CLI smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Example: strategy with fast_window=10, slow_window=22
    # fast_window shows a cliff edge (Sharpe collapses at 8, within ±20% of 10)
    # slow_window is robust

    sweep = {
        "fast_window": [
            (7,  0.3),   # -30% from base=10  → outside window
            (8,  0.6),   # -20% from base=10  → within window, degradation = (1.5-0.6)/1.5 = 60% → CLIFF
            (9,  1.3),   # -10% from base=10  → within window, degradation = 13% → OK
            (10, 1.5),   # base
            (11, 1.35),  # +10% → within window, degradation = 10% → OK
            (12, 1.2),   # +20% → within window, degradation = 20% → OK
            (13, 1.0),   # +30% → outside window
        ],
        "slow_window": [
            (18, 1.2),   # -18% from base=22  → within window, degradation = 20% → OK
            (20, 1.4),   # -9%  → within window, degradation = 7%  → OK
            (22, 1.5),   # base
            (24, 1.45),  # +9%  → within window, degradation = 3%  → OK
            (26, 1.3),   # +18% → within window, degradation = 13% → OK
            (28, 1.1),   # +27% → outside window
        ],
    }

    verdict = check_sensitivity(sweep, base_values={"fast_window": 10, "slow_window": 22})
    print(verdict.summary)
    print()
    print(f"Overall passed: {verdict.overall_passed}")
    print(f"Cliff-edge params: {verdict.cliff_edge_params}")
    print(f"Worst degradation: {verdict.worst_degradation_pct:.1%}")

    assert not verdict.overall_passed, "Expected FAIL due to fast_window cliff edge"
    assert "fast_window" in verdict.cliff_edge_params
    assert "slow_window" not in verdict.cliff_edge_params

    # Example 2: all params robust
    sweep2 = {
        "rsi_period": [
            (11, 1.35),
            (12, 1.42),
            (14, 1.50),
            (16, 1.45),
            (17, 1.38),
        ],
    }
    verdict2 = check_sensitivity(sweep2, base_values={"rsi_period": 14})
    assert verdict2.overall_passed, "Expected PASS"
    print("\nAll assertions passed.")
