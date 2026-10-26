"""
drawdown_convention.py
Canonical max-drawdown sign convention for Quant Zero.

Problem this solves (Engineering Director, QUA-721 daily micro heartbeat 2026-10-02):

The repo carried two incompatible drawdown conventions with no canonical field:

  Group A (signed) — `backtests/run_h72_gate1.py`, `run_h14_gate1.py`, `run_h13_gate1.py`:
      is_mdd = -0.1513;  check is `is_mdd > -0.20`
  Group B (magnitude) — `run_h79_gate1.py`, `run_h83_gate1.py`, `run_h83_elder_gate1.py`:
      is_mdd = abs(-0.1513) = 0.1513;  check is `is_mdd < 0.20`

Each group is internally correct, but:

  1. `agents/overfit-detector/tools/gate1_verdict.py` evaluates
     `bt.is_max_drawdown < IS_DD_MAX` against a POSITIVE threshold (0.20). Feed it a
     signed value and a catastrophic -0.51 drawdown silently returns PASS
     (-0.51 < 0.20). `orchestrator/gate1_reporter.py` happened to guard this with
     `abs()`, but nothing enforced it at the dataclass boundary.
  2. Verdict JSON stored drawdown only as a formatted display string inside the
     `metrics` array. There was no numeric field with a defined sign, so the
     charter constraint `MaxDD < -15%` (`docs/objective-function-charter.md`,
     CEO-locked QUA-154) was not machine-checkable across artifacts.

Convention fixed here
---------------------
* **Signed** (`SIGNED`): drawdown is negative-or-zero, e.g. ``-0.1513``.
  This is the charter-facing form. Charter compares ``signed > -0.15``.
* **Magnitude** (`MAGNITUDE`): drawdown is positive-or-zero, e.g. ``0.1513``.
  This is the Gate 1 threshold form used by `gate1_verdict.py`.

Both helpers are idempotent and accept either input convention, so existing
runners in either group can be routed through them without changes to their own
internal arithmetic.

Usage
-----
    from drawdown_convention import (
        signed_drawdown, drawdown_magnitude, charter_maxdd_compliant,
        charter_compliance_block,
    )

    signed_drawdown(0.1513)            # -> -0.1513
    drawdown_magnitude(-0.1513)        # ->  0.1513
    charter_maxdd_compliant(-0.1513)   # ->  False  (-15.13% is deeper than the -15% floor)
    charter_maxdd_compliant(-0.1100)   # ->  True
"""

from __future__ import annotations

import math
from typing import Any

# ── Charter constants (docs/objective-function-charter.md, CEO-locked QUA-154) ──

CHARTER_MAXDD_FLOOR_SIGNED = -0.15   # MaxDD must be strictly greater than this
CHARTER_NET_SHARPE_MIN = 0.8         # Net Sharpe > 0.8
CHARTER_NET_CAGR_MIN = 0.10          # Net CAGR >= 10%

# Threshold at which the Engineering Director must flag a result as approaching
# the charter floor (AGENTS.md: "Flag any result approaching MaxDD -15%").
CHARTER_MAXDD_WARN_SIGNED = -0.12


class DrawdownConventionError(ValueError):
    """Raised when a drawdown value cannot be interpreted under either convention."""


# ── Normalizers ───────────────────────────────────────────────────────────────

def _coerce(value: Any, field_name: str) -> float:
    """Coerce to a finite float, rejecting NaN/inf which would poison comparisons."""
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise DrawdownConventionError(
            f"{field_name}: {value!r} is not numeric."
        ) from exc
    if not math.isfinite(f):
        raise DrawdownConventionError(
            f"{field_name}: {f} is not finite; drawdown comparisons would be unsound."
        )
    # A drawdown is a fraction of peak equity. |dd| > 1 means total loss plus more,
    # which is only reachable with leverage; > 10 is certainly a unit error (percent
    # passed where a fraction was expected).
    if abs(f) > 10.0:
        raise DrawdownConventionError(
            f"{field_name}: {f} is out of range for a drawdown fraction. "
            f"Pass 0.15 for a 15% drawdown, not 15."
        )
    return f


def signed_drawdown(value: Any, field_name: str = "max_drawdown") -> float:
    """
    Return drawdown in SIGNED convention: negative-or-zero.

    Idempotent — accepts either convention. ``0.0`` stays ``0.0`` (no drawdown).
    """
    return -abs(_coerce(value, field_name))


def drawdown_magnitude(value: Any, field_name: str = "max_drawdown") -> float:
    """
    Return drawdown in MAGNITUDE convention: positive-or-zero.

    Idempotent — accepts either convention. This is the form
    `gate1_verdict.py` compares against `IS_DD_MAX` / `OOS_DD_MAX`.
    """
    return abs(_coerce(value, field_name))


# ── Charter checks ────────────────────────────────────────────────────────────

def charter_maxdd_compliant(value: Any, field_name: str = "max_drawdown") -> bool:
    """
    True when drawdown satisfies the charter constraint ``MaxDD < -15%``.

    The charter phrases the floor as "< -15% from peak", meaning a drawdown
    deeper than -15% is a breach. A -0.10 drawdown is compliant; -0.20 is not.
    Boundary: exactly -0.15 is a breach (constraint is strict).
    """
    return signed_drawdown(value, field_name) > CHARTER_MAXDD_FLOOR_SIGNED


def charter_maxdd_warn(value: Any, field_name: str = "max_drawdown") -> bool:
    """True when drawdown is compliant but within 3pp of the charter floor."""
    signed = signed_drawdown(value, field_name)
    return (
        signed > CHARTER_MAXDD_FLOOR_SIGNED
        and signed <= CHARTER_MAXDD_WARN_SIGNED
    )


def charter_compliance_block(
    *,
    net_sharpe: Any,
    net_cagr: Any,
    max_drawdown: Any,
) -> dict[str, Any]:
    """
    Build the machine-checkable charter compliance block for a verdict JSON.

    All three charter hard constraints must hold simultaneously. Returns a dict
    with the normalized SIGNED drawdown plus per-constraint and overall booleans,
    so downstream consumers never have to re-derive the sign convention.

    `net_cagr` may be None when a runner does not report it; the CAGR constraint
    is then recorded as None (unknown) rather than silently passing, and
    `all_constraints_pass` is False because the charter requires all three.
    """
    signed_dd = signed_drawdown(max_drawdown, "max_drawdown")
    sharpe = _coerce(net_sharpe, "net_sharpe")

    if net_cagr is None:
        cagr: float | None = None
        cagr_pass: bool | None = None
    else:
        cagr = _coerce(net_cagr, "net_cagr")
        cagr_pass = cagr >= CHARTER_NET_CAGR_MIN

    maxdd_pass = signed_dd > CHARTER_MAXDD_FLOOR_SIGNED
    sharpe_pass = sharpe > CHARTER_NET_SHARPE_MIN

    return {
        "convention": "signed",  # drawdown fields below are negative-or-zero
        "net_sharpe": sharpe,
        "net_sharpe_min": CHARTER_NET_SHARPE_MIN,
        "net_sharpe_pass": sharpe_pass,
        "net_cagr": cagr,
        "net_cagr_min": CHARTER_NET_CAGR_MIN,
        "net_cagr_pass": cagr_pass,
        "max_drawdown_signed": signed_dd,
        "max_drawdown_floor_signed": CHARTER_MAXDD_FLOOR_SIGNED,
        "max_drawdown_pass": maxdd_pass,
        "max_drawdown_near_floor": charter_maxdd_warn(signed_dd),
        "all_constraints_pass": bool(maxdd_pass and sharpe_pass and cagr_pass is True),
    }


# ── Smoke tests ───────────────────────────────────────────────────────────────

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

    def test_signed_idempotent():
        assert signed_drawdown(0.1513) == -0.1513
        assert signed_drawdown(-0.1513) == -0.1513
        assert signed_drawdown(signed_drawdown(0.1513)) == -0.1513
        assert signed_drawdown(0.0) == 0.0

    def test_magnitude_idempotent():
        assert drawdown_magnitude(-0.1513) == 0.1513
        assert drawdown_magnitude(0.1513) == 0.1513
        assert drawdown_magnitude(drawdown_magnitude(-0.1513)) == 0.1513

    def test_charter_compliant():
        assert charter_maxdd_compliant(-0.10) is True
        assert charter_maxdd_compliant(0.10) is True    # magnitude input accepted
        assert charter_maxdd_compliant(-0.20) is False
        assert charter_maxdd_compliant(0.20) is False   # magnitude input accepted

    def test_charter_boundary_is_strict():
        # Exactly -15% is a breach: constraint is "< -15%", strict.
        assert charter_maxdd_compliant(-0.15) is False

    def test_warn_band():
        assert charter_maxdd_warn(-0.13) is True    # compliant but near floor
        assert charter_maxdd_warn(-0.05) is False   # comfortably clear
        assert charter_maxdd_warn(-0.20) is False   # already a breach, not a warn

    def test_rejects_nan_and_inf():
        for bad in (float("nan"), float("inf"), float("-inf")):
            try:
                signed_drawdown(bad)
                assert False, f"{bad} should have raised"
            except DrawdownConventionError:
                pass

    def test_rejects_percent_units():
        # 15 instead of 0.15 is the classic unit error; must not pass silently.
        try:
            signed_drawdown(15.0)
            assert False, "15.0 should have raised (percent passed as fraction)"
        except DrawdownConventionError:
            pass

    def test_rejects_non_numeric():
        try:
            signed_drawdown("-12%")
            assert False, "'-12%' should have raised"
        except DrawdownConventionError:
            pass

    def test_compliance_block_pass():
        b = charter_compliance_block(net_sharpe=1.2, net_cagr=0.14, max_drawdown=-0.11)
        assert b["max_drawdown_signed"] == -0.11
        assert b["max_drawdown_pass"] is True
        assert b["net_sharpe_pass"] is True
        assert b["net_cagr_pass"] is True
        assert b["all_constraints_pass"] is True

    def test_compliance_block_normalizes_magnitude_input():
        # A Group B runner passing a positive magnitude must still produce a
        # correct charter verdict.
        b = charter_compliance_block(net_sharpe=1.2, net_cagr=0.14, max_drawdown=0.37)
        assert b["max_drawdown_signed"] == -0.37
        assert b["max_drawdown_pass"] is False
        assert b["all_constraints_pass"] is False

    def test_compliance_block_unknown_cagr_does_not_pass():
        b = charter_compliance_block(net_sharpe=1.2, net_cagr=None, max_drawdown=-0.11)
        assert b["net_cagr"] is None
        assert b["net_cagr_pass"] is None
        assert b["all_constraints_pass"] is False, "unknown CAGR must not count as pass"

    def test_compliance_block_sharpe_boundary_strict():
        b = charter_compliance_block(net_sharpe=0.8, net_cagr=0.14, max_drawdown=-0.11)
        assert b["net_sharpe_pass"] is False, "Sharpe > 0.8 is strict"

    _case("signed_drawdown is idempotent", test_signed_idempotent)
    _case("drawdown_magnitude is idempotent", test_magnitude_idempotent)
    _case("charter compliance accepts both conventions", test_charter_compliant)
    _case("charter floor boundary is strict", test_charter_boundary_is_strict)
    _case("near-floor warn band", test_warn_band)
    _case("rejects NaN/inf", test_rejects_nan_and_inf)
    _case("rejects percent-unit drawdown", test_rejects_percent_units)
    _case("rejects non-numeric", test_rejects_non_numeric)
    _case("compliance block all-pass", test_compliance_block_pass)
    _case("compliance block normalizes magnitude input",
          test_compliance_block_normalizes_magnitude_input)
    _case("unknown CAGR does not count as pass",
          test_compliance_block_unknown_cagr_does_not_pass)
    _case("Sharpe boundary is strict", test_compliance_block_sharpe_boundary_strict)

    print(f"\n{passed}/{total} tests passed")
    return passed == total


if __name__ == "__main__":
    import sys
    print("Running drawdown_convention smoke tests...\n")
    sys.exit(0 if _run_tests() else 1)
