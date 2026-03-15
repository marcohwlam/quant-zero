"""
gate1_verdict.py
Automated Gate 1 Verdict Generator for the Overfit Detector Agent

Orchestrates all Gate 1 checks and generates the structured PASS/FAIL/
CONDITIONAL PASS verdict in the canonical format defined in criteria.md.

Gate 1 criteria are CEO-locked (version 1.0, 2026-03-15).
Any single auto-disqualify trigger = immediate FAIL — analysis stops there.

Usage:
    from gate1_verdict import BacktestResult, generate_verdict, format_verdict

    result = BacktestResult(
        strategy_name="MomentumV1",
        strategy_version="1.0",
        test_start="2018-01-01",
        test_end="2023-12-31",
        is_sharpe=1.52,
        oos_sharpe=1.10,
        is_max_drawdown=0.14,
        oos_max_drawdown=0.18,
        win_rate=0.54,
        trade_count=312,
        dsr_zscore=2.1,
        walk_forward_windows=[(1.5,1.1),(1.4,1.2),(1.6,0.9),(1.3,1.0)],
        param_sensitivity_passed=True,
        param_sensitivity_max_delta=0.18,
        post_cost_sharpe=1.05,
        look_ahead_bias="none",
        economic_rationale="valid",
        n_trials=15,
    )
    verdict = generate_verdict(result)
    print(format_verdict(verdict))
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional, Tuple


# ── Gate 1 thresholds (from criteria.md, CEO-locked v1.0) ──────────────────

IS_SHARPE_MIN        = 1.0
OOS_SHARPE_MIN       = 0.7
IS_DD_MAX            = 0.20   # 20%
OOS_DD_MAX           = 0.25   # 25%
WIN_RATE_MIN         = 0.50   # 50%
DSR_ZSCORE_MIN       = 0.0    # z-score > 0
WF_WINDOWS_MIN       = 3      # pass ≥ 3 of 4 windows
WF_CONSISTENCY_LIMIT = 0.30   # OOS degradation < 30% of IS
PARAM_SENS_LIMIT     = 0.30   # ±20% param → Sharpe Δ < 30%
TRADE_COUNT_MIN      = 50     # > 50 IS trades
TEST_PERIOD_YEARS    = 5.0    # ≥ 5 years
POST_COST_SHARPE_MIN = 0.7    # post-cost OOS Sharpe must pass OOS threshold


# ── Input dataclass ─────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """
    All quantitative and qualitative inputs required for a Gate 1 evaluation.

    Monetary / percentage fields:
      - Sharpe Ratios: annualized, risk-free rate assumed 0%
      - Drawdowns: as fractions (0.15 = 15%)
      - Win rate: as fraction (0.54 = 54%)
      - param_sensitivity_max_delta: worst Sharpe degradation fraction
        observed within ±20% parameter window (0.18 = 18%)

    Walk-forward windows:
      List of (IS_sharpe, OOS_sharpe) tuples, one per non-overlapping window.
      Must contain ≥ 4 windows for a valid Gate 1 test.
    """
    # Identity
    strategy_name: str
    strategy_version: str = "1.0"

    # Test period
    test_start: str = ""   # ISO date string, e.g., "2018-01-01"
    test_end: str = ""     # ISO date string, e.g., "2023-12-31"

    # Core performance
    is_sharpe: float = 0.0
    oos_sharpe: float = 0.0
    is_max_drawdown: float = 0.0   # fraction
    oos_max_drawdown: float = 0.0  # fraction
    win_rate: float = 0.0          # fraction
    trade_count: int = 0

    # Overfitting / robustness
    dsr_zscore: float = 0.0        # z-score from dsr_calculator.compute_dsr()
    walk_forward_windows: List[Tuple[float, float]] = field(default_factory=list)

    # Parameter sensitivity
    param_sensitivity_passed: bool = False
    param_sensitivity_max_delta: float = 0.0  # worst degradation fraction

    # Post-cost performance
    post_cost_sharpe: float = 0.0

    # Qualitative
    look_ahead_bias: str = "none"      # "none" | "warning" | "detected"
    economic_rationale: str = "valid"  # "valid" | "weak" | "missing"

    # Number of strategy variants tested (for DSR context; informational only,
    # dsr_zscore is pre-computed by the caller via dsr_calculator)
    n_trials: int = 1


# ── Output dataclass ────────────────────────────────────────────────────────

@dataclass
class MetricResult:
    """Pass/fail result for a single Gate 1 metric."""
    name: str
    value: str             # formatted display value
    threshold: str         # human-readable threshold
    passed: bool
    auto_disqualify: bool  # True if failing this metric is an immediate FAIL


@dataclass
class Gate1Verdict:
    """
    Structured Gate 1 verdict.

    Fields:
      overall_verdict:       "PASS" | "FAIL" | "CONDITIONAL PASS"
      disqualify_reason:     Set if overall_verdict == "FAIL" due to
                             a single auto-disqualify trigger.
      recommendation:        One of: "Promote to paper trading" |
                             "Send back for additional testing" | "Reject"
      confidence:            "HIGH" | "MEDIUM" | "LOW"
      concerns:              List of concern strings (present even when passing)
      metrics:               Per-metric results for QUANTITATIVE SUMMARY section
      walk_forward_windows:  Per-window breakdown
      wf_windows_passed:     Count of walk-forward windows passed
      wf_oos_is_ratio:       Mean OOS/IS Sharpe ratio across windows
      economic_rationale:    "VALID" | "WEAK" | "MISSING"
      look_ahead_bias:       "NONE DETECTED" | "WARNING" | "DETECTED"
      overfitting_risk:      "LOW" | "MEDIUM" | "HIGH"
    """
    # Identity
    strategy_name: str
    strategy_version: str
    verdict_date: str

    # Overall
    overall_verdict: str
    disqualify_reason: Optional[str]
    recommendation: str
    confidence: str
    concerns: List[str]

    # Quantitative
    metrics: List[MetricResult]
    walk_forward_windows: List[Tuple[float, float]]
    wf_windows_passed: int
    wf_oos_is_ratio: float  # mean OOS/IS ratio

    # Qualitative
    economic_rationale: str   # "VALID" | "WEAK" | "MISSING"
    look_ahead_bias: str      # "NONE DETECTED" | "WARNING" | "DETECTED"
    overfitting_risk: str     # "LOW" | "MEDIUM" | "HIGH"

    # Raw input for reference
    backtest: BacktestResult


# ── Walk-forward helper ─────────────────────────────────────────────────────

def _evaluate_walk_forward(
    windows: List[Tuple[float, float]],
) -> Tuple[int, int, float, List[bool]]:
    """
    Evaluate walk-forward consistency.

    Returns:
        (windows_passed, windows_total, mean_oos_is_ratio, per_window_passed)
    """
    if not windows:
        return 0, 0, 0.0, []

    per_passed: List[bool] = []
    ratios: List[float] = []

    for is_sr, oos_sr in windows:
        if is_sr <= 0:
            per_passed.append(False)
            ratios.append(0.0)
            continue
        degradation = (is_sr - oos_sr) / is_sr
        passed = degradation < WF_CONSISTENCY_LIMIT
        per_passed.append(passed)
        ratios.append(oos_sr / is_sr)

    n_passed = sum(per_passed)
    mean_ratio = sum(ratios) / len(ratios) if ratios else 0.0
    return n_passed, len(windows), mean_ratio, per_passed


# ── Test period helper ──────────────────────────────────────────────────────

def _years_between(start: str, end: str) -> float:
    """Parse ISO date strings and return fractional years between them."""
    try:
        d_start = datetime.strptime(start.strip(), "%Y-%m-%d").date()
        d_end   = datetime.strptime(end.strip(), "%Y-%m-%d").date()
        return (d_end - d_start).days / 365.25
    except (ValueError, AttributeError):
        return 0.0


# ── Overfitting risk assessment ─────────────────────────────────────────────

def _assess_overfitting_risk(bt: BacktestResult, wf_passed: int, wf_total: int) -> str:
    """
    Heuristic overfitting risk score: LOW / MEDIUM / HIGH.

    HIGH indicators:
      - IS Sharpe >> OOS Sharpe (ratio < 0.6)
      - Walk-forward barely passing (3/4)
      - Parameter sensitivity near the limit
      - n_trials high with DSR close to 0

    MEDIUM indicators:
      - OOS/IS ratio 0.6–0.8
      - Walk-forward 3/4
      - Strategy has economic rationale but thin margin
    """
    risk_score = 0

    # IS/OOS degradation
    if bt.is_sharpe > 0:
        oos_is_ratio = bt.oos_sharpe / bt.is_sharpe
        if oos_is_ratio < 0.60:
            risk_score += 3
        elif oos_is_ratio < 0.80:
            risk_score += 2
        elif oos_is_ratio < 0.90:
            risk_score += 1

    # Walk-forward
    if wf_total >= 4 and wf_passed == 3:
        risk_score += 1
    elif wf_total >= 4 and wf_passed < 3:
        risk_score += 3

    # Parameter sensitivity
    if bt.param_sensitivity_max_delta >= 0.25:
        risk_score += 2
    elif bt.param_sensitivity_max_delta >= 0.15:
        risk_score += 1

    # DSR margin
    if 0.0 < bt.dsr_zscore < 1.0:
        risk_score += 2
    elif bt.dsr_zscore < 0:
        risk_score += 4

    # n_trials
    if bt.n_trials >= 50:
        risk_score += 2
    elif bt.n_trials >= 20:
        risk_score += 1

    # Economic rationale
    if bt.economic_rationale == "missing":
        risk_score += 2
    elif bt.economic_rationale == "weak":
        risk_score += 1

    if risk_score <= 2:
        return "LOW"
    elif risk_score <= 5:
        return "MEDIUM"
    else:
        return "HIGH"


# ── Main verdict generation ─────────────────────────────────────────────────

def generate_verdict(bt: BacktestResult) -> Gate1Verdict:
    """
    Run all Gate 1 checks and produce a structured verdict.

    Auto-disqualification logic: the first failing auto-disqualify check
    sets overall_verdict to "FAIL" immediately.  Remaining checks still
    run for informational purposes but do not change the verdict.

    Args:
        bt: BacktestResult with all required inputs.

    Returns:
        Gate1Verdict with per-metric results, qualitative assessment,
        recommendation, and concerns.
    """
    today = date.today().isoformat()
    concerns: List[str] = []
    metrics: List[MetricResult] = []

    # ── Test period ─────────────────────────────────────────────────────────
    test_years = _years_between(bt.test_start, bt.test_end)
    test_period_passed = test_years >= TEST_PERIOD_YEARS
    metrics.append(MetricResult(
        name="Test period",
        value=(
            f"{bt.test_start} – {bt.test_end}, {test_years:.1f} years"
            if bt.test_start and bt.test_end else "Not specified"
        ),
        threshold=f"≥ {TEST_PERIOD_YEARS:.0f} years",
        passed=test_period_passed,
        auto_disqualify=True,
    ))

    # ── IS Sharpe ───────────────────────────────────────────────────────────
    is_sharpe_passed = bt.is_sharpe > IS_SHARPE_MIN
    metrics.append(MetricResult(
        name="IS Sharpe",
        value=f"{bt.is_sharpe:.2f}",
        threshold=f"> {IS_SHARPE_MIN:.1f}",
        passed=is_sharpe_passed,
        auto_disqualify=True,
    ))
    if bt.is_sharpe > IS_SHARPE_MIN and bt.is_sharpe < 1.2:
        concerns.append("IS Sharpe is above threshold but marginal (< 1.2).")

    # ── OOS Sharpe ──────────────────────────────────────────────────────────
    oos_sharpe_passed = bt.oos_sharpe > OOS_SHARPE_MIN
    metrics.append(MetricResult(
        name="OOS Sharpe",
        value=f"{bt.oos_sharpe:.2f}",
        threshold=f"> {OOS_SHARPE_MIN:.1f}",
        passed=oos_sharpe_passed,
        auto_disqualify=True,
    ))
    if bt.oos_sharpe > OOS_SHARPE_MIN and bt.oos_sharpe < 0.85:
        concerns.append("OOS Sharpe is above threshold but marginal (< 0.85).")

    # ── Walk-forward consistency ─────────────────────────────────────────────
    wf_passed_count, wf_total, wf_mean_ratio, wf_per_window = _evaluate_walk_forward(
        bt.walk_forward_windows
    )
    wf_windows_ok = (wf_total >= 4) and (wf_passed_count >= WF_WINDOWS_MIN)
    wf_consistency_ratio = wf_mean_ratio
    # Consistency: mean ratio should be ≥ (1 - WF_CONSISTENCY_LIMIT)
    wf_consistency_ok = wf_mean_ratio >= (1.0 - WF_CONSISTENCY_LIMIT)

    metrics.append(MetricResult(
        name="Walk-forward windows passed",
        value=f"{wf_passed_count}/{wf_total}",
        threshold=f"≥ {WF_WINDOWS_MIN}/4",
        passed=wf_windows_ok,
        auto_disqualify=True,
    ))
    metrics.append(MetricResult(
        name="Walk-forward OOS/IS consistency",
        value=f"{wf_mean_ratio:.2f} mean OOS/IS ratio",
        threshold=f"OOS within {WF_CONSISTENCY_LIMIT:.0%} of IS",
        passed=wf_consistency_ok,
        auto_disqualify=True,
    ))
    if wf_passed_count == WF_WINDOWS_MIN and wf_total == 4:
        concerns.append("Walk-forward barely meets threshold (3/4 windows); one more failure would disqualify.")

    # ── IS Max Drawdown ──────────────────────────────────────────────────────
    is_dd_passed = bt.is_max_drawdown < IS_DD_MAX
    metrics.append(MetricResult(
        name="IS Max Drawdown",
        value=f"{bt.is_max_drawdown:.1%}",
        threshold=f"< {IS_DD_MAX:.0%}",
        passed=is_dd_passed,
        auto_disqualify=True,
    ))
    if bt.is_max_drawdown >= 0.15:
        concerns.append(f"IS drawdown is elevated ({bt.is_max_drawdown:.1%}); strategies near 20% warrant closer review.")

    # ── OOS Max Drawdown ─────────────────────────────────────────────────────
    oos_dd_passed = bt.oos_max_drawdown < OOS_DD_MAX
    metrics.append(MetricResult(
        name="OOS Max Drawdown",
        value=f"{bt.oos_max_drawdown:.1%}",
        threshold=f"< {OOS_DD_MAX:.0%}",
        passed=oos_dd_passed,
        auto_disqualify=False,  # Not in auto-disqualify list in criteria.md
    ))
    if bt.oos_max_drawdown > bt.is_max_drawdown + 0.10:
        concerns.append(
            f"OOS drawdown ({bt.oos_max_drawdown:.1%}) exceeds IS drawdown "
            f"({bt.is_max_drawdown:.1%}) by more than 10pp — requires explanation."
        )

    # ── Win Rate ─────────────────────────────────────────────────────────────
    win_rate_passed = bt.win_rate > WIN_RATE_MIN
    metrics.append(MetricResult(
        name="Win Rate",
        value=f"{bt.win_rate:.1%}",
        threshold=f"> {WIN_RATE_MIN:.0%}",
        passed=win_rate_passed,
        auto_disqualify=False,
    ))

    # ── Trade Count ──────────────────────────────────────────────────────────
    trade_count_passed = bt.trade_count > TRADE_COUNT_MIN
    metrics.append(MetricResult(
        name="Trade count",
        value=str(bt.trade_count),
        threshold=f"> {TRADE_COUNT_MIN}",
        passed=trade_count_passed,
        auto_disqualify=True,
    ))
    if TRADE_COUNT_MIN < bt.trade_count <= 80:
        concerns.append(f"Trade count ({bt.trade_count}) is above threshold but low — statistics may be less reliable.")

    # ── DSR ──────────────────────────────────────────────────────────────────
    dsr_passed = bt.dsr_zscore > DSR_ZSCORE_MIN
    metrics.append(MetricResult(
        name="Deflated Sharpe Ratio (z-score)",
        value=f"{bt.dsr_zscore:.2f}",
        threshold=f"> {DSR_ZSCORE_MIN:.1f}",
        passed=dsr_passed,
        auto_disqualify=True,
    ))
    if dsr_passed and bt.dsr_zscore < 1.0:
        concerns.append(f"DSR z-score is positive but low ({bt.dsr_zscore:.2f}); Sharpe barely survives multiple-comparison correction.")

    # ── Parameter Sensitivity ─────────────────────────────────────────────────
    metrics.append(MetricResult(
        name="Parameter sensitivity",
        value=f"{bt.param_sensitivity_max_delta:.1%} max Sharpe Δ within ±20%",
        threshold=f"< {PARAM_SENS_LIMIT:.0%} Sharpe change",
        passed=bt.param_sensitivity_passed,
        auto_disqualify=True,
    ))
    if bt.param_sensitivity_passed and bt.param_sensitivity_max_delta >= 0.20:
        concerns.append(f"Parameter sensitivity is acceptable but elevated ({bt.param_sensitivity_max_delta:.1%}); near cliff-edge threshold.")

    # ── Post-cost Sharpe ─────────────────────────────────────────────────────
    post_cost_passed = bt.post_cost_sharpe > POST_COST_SHARPE_MIN
    metrics.append(MetricResult(
        name="Post-cost Sharpe",
        value=f"{bt.post_cost_sharpe:.2f}",
        threshold=f"> {POST_COST_SHARPE_MIN:.1f} (after realistic costs)",
        passed=post_cost_passed,
        auto_disqualify=True,
    ))
    if post_cost_passed and bt.post_cost_sharpe < 0.9:
        concerns.append(f"Post-cost Sharpe ({bt.post_cost_sharpe:.2f}) is marginal; cost sensitivity is high.")

    # ── Look-ahead bias ──────────────────────────────────────────────────────
    lab_lower = bt.look_ahead_bias.lower().strip()
    lab_display = {
        "none": "NONE DETECTED",
        "warning": "WARNING",
        "detected": "DETECTED",
    }.get(lab_lower, lab_lower.upper())
    lab_passed = lab_lower == "none"
    if lab_lower == "warning":
        concerns.append("Look-ahead bias: WARNING flag set — manual review required before promotion.")
    elif lab_lower == "detected":
        concerns.append("CRITICAL: Look-ahead bias DETECTED — strategy must be rewritten from scratch.")

    # ── Qualitative: economic rationale ─────────────────────────────────────
    eco_lower = bt.economic_rationale.lower().strip()
    eco_display = {
        "valid": "VALID",
        "weak": "WEAK",
        "missing": "MISSING",
    }.get(eco_lower, eco_lower.upper())
    if eco_lower == "weak":
        concerns.append("Economic rationale is WEAK — data-mining risk elevated; CEO must assess at review.")
    elif eco_lower == "missing":
        concerns.append("Economic rationale is MISSING — this is a qualitative disqualifier per criteria.md.")

    # ── Overfitting risk ─────────────────────────────────────────────────────
    overfitting_risk = _assess_overfitting_risk(bt, wf_passed_count, wf_total)
    if overfitting_risk == "HIGH":
        concerns.append("Overfitting risk assessed as HIGH — mandatory second review before CEO promotion decision.")

    # ── Auto-disqualify check ─────────────────────────────────────────────────
    # Look-ahead bias is always an immediate reject regardless of other metrics
    disqualify_reason: Optional[str] = None
    auto_disq_failed = [m for m in metrics if m.auto_disqualify and not m.passed]

    if lab_lower == "detected":
        disqualify_reason = "Look-ahead bias DETECTED — automatic reject per criteria.md. Strategy must be rewritten."
    elif auto_disq_failed:
        # Report the first failure
        first = auto_disq_failed[0]
        disqualify_reason = (
            f"Auto-disqualify: {first.name} = {first.value} "
            f"(threshold: {first.threshold})"
        )

    # ── Overall verdict ────────────────────────────────────────────────────
    all_metrics_pass = all(m.passed for m in metrics)
    la_ok = lab_lower in ("none", "warning")  # warning → conditional at most

    if disqualify_reason:
        overall_verdict = "FAIL"
        recommendation  = "Reject"
        confidence      = "HIGH"
    elif not all_metrics_pass:
        overall_verdict = "FAIL"
        recommendation  = "Send back for additional testing"
        confidence      = "HIGH"
    elif lab_lower == "warning" or eco_lower in ("weak", "missing") or overfitting_risk == "HIGH":
        overall_verdict = "CONDITIONAL PASS"
        recommendation  = "Send back for additional testing"
        confidence      = "MEDIUM"
    elif concerns:
        overall_verdict = "PASS"
        recommendation  = "Promote to paper trading"
        confidence      = "MEDIUM"
    else:
        overall_verdict = "PASS"
        recommendation  = "Promote to paper trading"
        confidence      = "HIGH"

    return Gate1Verdict(
        strategy_name=bt.strategy_name,
        strategy_version=bt.strategy_version,
        verdict_date=today,
        overall_verdict=overall_verdict,
        disqualify_reason=disqualify_reason,
        recommendation=recommendation,
        confidence=confidence,
        concerns=concerns,
        metrics=metrics,
        walk_forward_windows=bt.walk_forward_windows,
        wf_windows_passed=wf_passed_count,
        wf_oos_is_ratio=wf_mean_ratio,
        economic_rationale=eco_display,
        look_ahead_bias=lab_display,
        overfitting_risk=overfitting_risk,
        backtest=bt,
    )


# ── Verdict formatter ───────────────────────────────────────────────────────

def format_verdict(v: Gate1Verdict) -> str:
    """
    Format a Gate1Verdict as the canonical Gate 1 markdown verdict string
    matching the template in criteria.md.

    Returns a plain-text / markdown string ready to be written to a file
    or posted as a Paperclip comment.
    """
    lines: List[str] = []

    # ── Header ───────────────────────────────────────────────────────────────
    lines.append(f"GATE 1 VERDICT: {v.overall_verdict}")
    lines.append(f"Strategy: {v.strategy_name} v{v.strategy_version}")
    lines.append(f"Date: {v.verdict_date}")
    lines.append("Analyst: Overfit Detector Agent")
    lines.append("")

    # ── Disqualification notice ────────────────────────────────────────────
    if v.disqualify_reason:
        lines.append("⛔ AUTO-DISQUALIFIED")
        lines.append(f"Reason: {v.disqualify_reason}")
        lines.append("")

    # ── Quantitative summary ──────────────────────────────────────────────
    lines.append("QUANTITATIVE SUMMARY")
    for m in v.metrics:
        status = "PASS" if m.passed else "FAIL"
        lines.append(f"- {m.name}: {m.value}  [{status}, threshold {m.threshold}]")

    lines.append("")

    # ── Walk-forward window breakdown ─────────────────────────────────────
    if v.walk_forward_windows:
        lines.append("WALK-FORWARD WINDOW DETAIL")
        for i, (is_sr, oos_sr) in enumerate(v.walk_forward_windows, start=1):
            if is_sr > 0:
                deg = (is_sr - oos_sr) / is_sr
                w_status = "PASS" if deg < WF_CONSISTENCY_LIMIT else "FAIL"
            else:
                w_status = "FAIL"
            lines.append(
                f"  Window {i}: IS={is_sr:.2f}, OOS={oos_sr:.2f}  [{w_status}]"
            )
        lines.append("")

    # ── Qualitative assessment ─────────────────────────────────────────────
    lines.append("QUALITATIVE ASSESSMENT")
    lines.append(f"- Economic rationale: {v.economic_rationale}")
    lines.append(f"- Look-ahead bias: {v.look_ahead_bias}")
    lines.append(f"- Overfitting risk: {v.overfitting_risk}")
    if v.concerns:
        lines.append("- Notes:")
        for c in v.concerns:
            lines.append(f"    * {c}")
    else:
        lines.append("- Notes: No specific concerns.")
    lines.append("")

    # ── Recommendation ────────────────────────────────────────────────────
    lines.append(f"RECOMMENDATION: {v.recommendation}")
    lines.append(f"CONFIDENCE: {v.confidence}")
    if v.concerns:
        lines.append("CONCERNS:")
        for c in v.concerns:
            lines.append(f"  - {c}")
    else:
        lines.append("CONCERNS: None.")

    return "\n".join(lines)


# ── CLI smoke tests (run via: python gate1_verdict.py) ──────────────────────

def _run_tests() -> None:
    """Inline smoke tests for the verdict generator."""
    passed_count = 0
    failed_count = 0

    def check(name: str, condition: bool, msg: str = "") -> None:
        nonlocal passed_count, failed_count
        if condition:
            print(f"  PASS  {name}")
            passed_count += 1
        else:
            print(f"  FAIL  {name}" + (f": {msg}" if msg else ""))
            failed_count += 1

    print("=== Gate 1 Verdict Generator Smoke Tests ===\n")

    # ── Test 1: Solid strategy → PASS ────────────────────────────────────────
    solid = BacktestResult(
        strategy_name="MomentumV1",
        strategy_version="1.0",
        test_start="2018-01-01",
        test_end="2023-12-31",
        is_sharpe=1.55,
        oos_sharpe=1.12,
        is_max_drawdown=0.14,
        oos_max_drawdown=0.17,
        win_rate=0.55,
        trade_count=320,
        dsr_zscore=2.4,
        walk_forward_windows=[(1.6,1.2),(1.5,1.1),(1.4,1.0),(1.3,0.9)],
        param_sensitivity_passed=True,
        param_sensitivity_max_delta=0.12,
        post_cost_sharpe=1.05,
        look_ahead_bias="none",
        economic_rationale="valid",
        n_trials=10,
    )
    v1 = generate_verdict(solid)
    check("T1 solid → PASS", v1.overall_verdict == "PASS", v1.overall_verdict)
    check("T1 recommend promote", "Promote" in v1.recommendation)
    check("T1 no disqualify", v1.disqualify_reason is None)
    print(f"\n--- T1 formatted verdict ---\n{format_verdict(v1)}\n")

    # ── Test 2: Look-ahead bias → FAIL (immediate) ──────────────────────────
    lab_bt = BacktestResult(
        strategy_name="SnoopingV1",
        test_start="2018-01-01",
        test_end="2023-12-31",
        is_sharpe=2.0, oos_sharpe=1.5,
        is_max_drawdown=0.10, oos_max_drawdown=0.12,
        win_rate=0.60, trade_count=400,
        dsr_zscore=3.0,
        walk_forward_windows=[(2.0,1.6),(1.9,1.5),(1.8,1.4),(1.7,1.3)],
        param_sensitivity_passed=True, param_sensitivity_max_delta=0.08,
        post_cost_sharpe=1.4,
        look_ahead_bias="detected",
        economic_rationale="valid",
        n_trials=5,
    )
    v2 = generate_verdict(lab_bt)
    check("T2 look-ahead → FAIL", v2.overall_verdict == "FAIL", v2.overall_verdict)
    check("T2 disqualify reason set", v2.disqualify_reason is not None)
    check("T2 recommend Reject", v2.recommendation == "Reject")
    print(f"\n--- T2 disqualify reason: {v2.disqualify_reason}\n")

    # ── Test 3: Low IS Sharpe → auto-disqualify FAIL ────────────────────────
    low_is = BacktestResult(
        strategy_name="WeakV1",
        test_start="2018-01-01", test_end="2023-12-31",
        is_sharpe=0.85, oos_sharpe=0.72,
        is_max_drawdown=0.15, oos_max_drawdown=0.18,
        win_rate=0.51, trade_count=200,
        dsr_zscore=1.5,
        walk_forward_windows=[(0.9,0.8),(0.8,0.7),(0.85,0.75),(0.9,0.8)],
        param_sensitivity_passed=True, param_sensitivity_max_delta=0.10,
        post_cost_sharpe=0.65,
        look_ahead_bias="none", economic_rationale="valid", n_trials=5,
    )
    v3 = generate_verdict(low_is)
    check("T3 low IS Sharpe → FAIL", v3.overall_verdict == "FAIL", v3.overall_verdict)
    check("T3 disqualify mentions IS Sharpe", "IS Sharpe" in (v3.disqualify_reason or ""))
    print(f"  T3 disqualify: {v3.disqualify_reason}\n")

    # ── Test 4: Qualitative concern → CONDITIONAL PASS ─────────────────────
    cond = BacktestResult(
        strategy_name="GreyAreaV1",
        test_start="2018-01-01", test_end="2023-12-31",
        is_sharpe=1.45, oos_sharpe=1.05,
        is_max_drawdown=0.13, oos_max_drawdown=0.16,
        win_rate=0.53, trade_count=180,
        dsr_zscore=1.8,
        walk_forward_windows=[(1.5,1.1),(1.4,1.0),(1.3,0.9),(1.2,0.85)],
        param_sensitivity_passed=True, param_sensitivity_max_delta=0.14,
        post_cost_sharpe=0.98,
        look_ahead_bias="warning",
        economic_rationale="weak",
        n_trials=8,
    )
    v4 = generate_verdict(cond)
    check("T4 qualitative concern → CONDITIONAL PASS",
          v4.overall_verdict == "CONDITIONAL PASS", v4.overall_verdict)
    check("T4 has concerns", len(v4.concerns) > 0)
    print(f"  T4 verdict={v4.overall_verdict}, concerns={len(v4.concerns)}\n")

    # ── Test 5: Insufficient test period → FAIL ─────────────────────────────
    short_period = BacktestResult(
        strategy_name="ShortV1",
        test_start="2021-01-01", test_end="2023-12-31",
        is_sharpe=1.8, oos_sharpe=1.3,
        is_max_drawdown=0.10, oos_max_drawdown=0.12,
        win_rate=0.58, trade_count=250,
        dsr_zscore=2.1,
        walk_forward_windows=[(1.8,1.4),(1.7,1.3),(1.6,1.2),(1.5,1.1)],
        param_sensitivity_passed=True, param_sensitivity_max_delta=0.08,
        post_cost_sharpe=1.2,
        look_ahead_bias="none", economic_rationale="valid", n_trials=5,
    )
    v5 = generate_verdict(short_period)
    check("T5 short period → FAIL", v5.overall_verdict == "FAIL", v5.overall_verdict)
    check("T5 disqualify mentions period", "period" in (v5.disqualify_reason or "").lower() or
          "Test period" in (v5.disqualify_reason or ""))
    print(f"  T5 disqualify: {v5.disqualify_reason}\n")

    # ── Test 6: DSR ≤ 0 → auto-disqualify ─────────────────────────────────
    neg_dsr = BacktestResult(
        strategy_name="OverfitV1",
        test_start="2018-01-01", test_end="2023-12-31",
        is_sharpe=1.8, oos_sharpe=1.4,
        is_max_drawdown=0.12, oos_max_drawdown=0.15,
        win_rate=0.55, trade_count=300,
        dsr_zscore=-0.5,
        walk_forward_windows=[(1.8,1.5),(1.7,1.4),(1.6,1.3),(1.5,1.2)],
        param_sensitivity_passed=True, param_sensitivity_max_delta=0.10,
        post_cost_sharpe=1.2,
        look_ahead_bias="none", economic_rationale="valid", n_trials=100,
    )
    v6 = generate_verdict(neg_dsr)
    check("T6 negative DSR → FAIL", v6.overall_verdict == "FAIL", v6.overall_verdict)
    check("T6 disqualify mentions DSR", "DSR" in (v6.disqualify_reason or "") or
          "Deflated" in (v6.disqualify_reason or ""))
    print(f"  T6 disqualify: {v6.disqualify_reason}\n")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"{'='*50}")
    print(f"Results: {passed_count} passed, {failed_count} failed")
    if failed_count > 0:
        raise AssertionError(f"{failed_count} test(s) failed")
    print("All tests passed.")


if __name__ == "__main__":
    _run_tests()
