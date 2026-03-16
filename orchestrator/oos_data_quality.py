"""
oos_data_quality.py
OOS (out-of-sample) data quality validation for the backtest pipeline.

Detects and flags NaN / missing-value contamination in OOS price data and
post-backtest metrics before those metrics are committed to Gate 1 verdicts.
Root-cause motivation: H17 failure traced to silent NaN contamination that
skewed OOS Sharpe and other aggregate stats (source: CEO heartbeat QUA-219).

Usage
-----
    from oos_data_quality import validate_oos_data, OOSDataQualityError

    report = validate_oos_data(oos_data, oos_metrics, strategy_name="H21_IBS")
    if report["recommendation"] == "BLOCK":
        raise OOSDataQualityError(report)

    # Safe to proceed — attach report to metrics for downstream logging
    metrics["oos_data_quality"] = report
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


# ── Tuning knobs ─────────────────────────────────────────────────────────────

# Minimum fraction of fully-clean rows required for PASS (otherwise WARN/BLOCK)
_MIN_CLEAN_ROW_COVERAGE = 0.95

# Fraction below which we treat coverage as critically low (BLOCK)
_CRITICAL_CLEAN_ROW_COVERAGE = 0.90

# OOS metrics that must not be NaN/None — any violation triggers BLOCK
_CRITICAL_METRIC_FIELDS = [
    "sharpe",
    "max_drawdown",
    "win_rate",
    "profit_factor",
    "total_trades",
    "post_cost_sharpe",
]

# OOS metrics that are advisory — NaN triggers WARN, not BLOCK
_ADVISORY_METRIC_FIELDS = [
    "total_return",
]


# ── Public API ────────────────────────────────────────────────────────────────

class OOSDataQualityError(Exception):
    """Raised when OOS data quality is BLOCK-level and reporting must halt."""

    def __init__(self, report: dict) -> None:
        self.report = report
        nan_fields = report.get("metrics_nan_fields", [])
        coverage = report.get("oos_data_coverage_pct", 0.0)
        super().__init__(
            f"OOS data quality BLOCK: coverage={coverage:.1f}%, "
            f"NaN metric fields={nan_fields}"
        )


def validate_oos_data(
    oos_data: pd.DataFrame,
    oos_metrics: dict[str, Any],
    strategy_name: str = "unknown",
) -> dict[str, Any]:
    """
    Validate OOS price data and backtest metrics for NaN contamination.

    Runs two complementary checks:
      1. Input data check — scans the OOS OHLCV DataFrame for NaN values
         before any strategy logic touches it. Gaps here can silently corrupt
         rolling-window features and portfolio returns.
      2. Output metrics check — scans the dict returned by run_backtest() for
         NaN / None in key performance fields. This catches cases where
         vectorbt returns NaN due to insufficient trades or degenerate series.

    Args:
        oos_data:     OOS price DataFrame (rows = trading days, cols = OHLCV or
                      multi-ticker equivalent). Passed in before run_backtest().
        oos_metrics:  Dict returned by run_backtest() for the OOS window.
        strategy_name: Used for logging only.

    Returns:
        A dict report with the following keys:

        strategy_name          str   — echo of the input name
        oos_total_rows         int   — number of rows in oos_data
        oos_clean_rows         int   — rows with zero NaN in any column
        oos_data_coverage_pct  float — clean_rows / total_rows × 100
        oos_nan_per_column     dict  — {col_name: nan_count} for every column
        oos_total_nans         int   — sum of all NaN cells
        metrics_nan_fields     list  — critical metric fields that are NaN/None
        advisory_nan_fields    list  — advisory metric fields that are NaN/None
        has_critical_nan       bool  — True if any BLOCK condition is met
        recommendation         str   — "PASS", "WARN", or "BLOCK"
        block_reasons          list  — human-readable reasons when BLOCK

    Raises:
        TypeError: if oos_data is not a pandas DataFrame.
    """
    if not isinstance(oos_data, pd.DataFrame):
        raise TypeError(f"oos_data must be a pd.DataFrame, got {type(oos_data)}")

    # ── 1. Input data NaN audit ───────────────────────────────────────────────
    total_rows = len(oos_data)
    nan_per_col: dict[str, int] = {
        str(col): int(count)
        for col, count in oos_data.isnull().sum().items()
    }
    total_nans = sum(nan_per_col.values())
    clean_rows = int((~oos_data.isnull().any(axis=1)).sum())
    data_coverage_pct = (clean_rows / max(1, total_rows)) * 100.0

    # ── 2. Output metrics NaN audit ───────────────────────────────────────────
    # Only flag fields that ARE present but contain NaN/None.
    # Absent fields are not flagged — the strategy may not emit every metric.
    metrics_nan_fields = [
        field
        for field in _CRITICAL_METRIC_FIELDS
        if field in oos_metrics and _is_nan_or_none(oos_metrics[field])
    ]
    advisory_nan_fields = [
        field
        for field in _ADVISORY_METRIC_FIELDS
        if field in oos_metrics and _is_nan_or_none(oos_metrics[field])
    ]

    # Also scan portfolio_returns series for NaN contamination
    portfolio_returns = oos_metrics.get("portfolio_returns")
    returns_nan_count = 0
    returns_nan_pct = 0.0
    if isinstance(portfolio_returns, pd.Series) and len(portfolio_returns) > 0:
        returns_nan_count = int(portfolio_returns.isnull().sum())
        returns_nan_pct = (returns_nan_count / len(portfolio_returns)) * 100.0
        if returns_nan_count > 0:
            # Treat returns NaN as an advisory issue (dropna is applied upstream,
            # but we surface the count so the caller can make an informed decision)
            advisory_nan_fields.append(f"portfolio_returns ({returns_nan_count} NaN)")

    # ── 3. Block conditions ───────────────────────────────────────────────────
    block_reasons: list[str] = []

    if metrics_nan_fields:
        block_reasons.append(
            f"Critical OOS metric fields are NaN/None: {metrics_nan_fields}"
        )

    if data_coverage_pct < _CRITICAL_CLEAN_ROW_COVERAGE * 100:
        block_reasons.append(
            f"OOS data coverage critically low: {data_coverage_pct:.1f}% "
            f"(threshold {_CRITICAL_CLEAN_ROW_COVERAGE * 100:.0f}%)"
        )

    has_critical_nan = bool(block_reasons)

    # ── 4. Recommendation ─────────────────────────────────────────────────────
    if has_critical_nan:
        recommendation = "BLOCK"
    elif (
        data_coverage_pct < _MIN_CLEAN_ROW_COVERAGE * 100
        or advisory_nan_fields
        or total_nans > 0
    ):
        recommendation = "WARN"
    else:
        recommendation = "PASS"

    return {
        "strategy_name": strategy_name,
        "oos_total_rows": total_rows,
        "oos_clean_rows": clean_rows,
        "oos_data_coverage_pct": round(data_coverage_pct, 2),
        "oos_nan_per_column": nan_per_col,
        "oos_total_nans": total_nans,
        "metrics_nan_fields": metrics_nan_fields,
        "advisory_nan_fields": advisory_nan_fields,
        "returns_nan_count": returns_nan_count,
        "returns_nan_pct": round(returns_nan_pct, 2),
        "has_critical_nan": has_critical_nan,
        "recommendation": recommendation,
        "block_reasons": block_reasons,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_nan_or_none(value: Any) -> bool:
    """Return True if value is None, NaN, or non-finite."""
    if value is None:
        return True
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return True
    if isinstance(value, (np.floating, np.integer)):
        return bool(np.isnan(value)) or bool(np.isinf(value))
    return False


# ── Smoke tests ───────────────────────────────────────────────────────────────

def _run_tests() -> bool:
    """Basic smoke tests — callable from __main__."""
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

    # Clean data + clean metrics → PASS
    def test_clean():
        data = pd.DataFrame({
            "Open": [100.0, 101.0, 102.0],
            "Close": [101.0, 102.0, 103.0],
        })
        metrics = {
            "sharpe": 1.2, "max_drawdown": -0.10, "win_rate": 0.55,
            "profit_factor": 1.4, "total_trades": 50, "post_cost_sharpe": 1.0,
        }
        r = validate_oos_data(data, metrics, "TestClean")
        assert r["recommendation"] == "PASS", r["recommendation"]
        assert r["has_critical_nan"] is False

    # NaN in critical metric → BLOCK
    def test_nan_metric():
        data = pd.DataFrame({"Close": [100.0, 101.0]})
        metrics = {
            "sharpe": float("nan"), "max_drawdown": -0.10, "win_rate": 0.55,
            "profit_factor": 1.4, "total_trades": 50, "post_cost_sharpe": 1.0,
        }
        r = validate_oos_data(data, metrics, "TestNaNSharpe")
        assert r["recommendation"] == "BLOCK", r["recommendation"]
        assert "sharpe" in r["metrics_nan_fields"]

    # Low data coverage → BLOCK
    def test_low_coverage():
        # 10 rows, 9 NaN → coverage 10%
        data = pd.DataFrame({"Close": [float("nan")] * 9 + [100.0]})
        metrics = {
            "sharpe": 1.0, "max_drawdown": -0.10, "win_rate": 0.55,
            "profit_factor": 1.4, "total_trades": 50, "post_cost_sharpe": 1.0,
        }
        r = validate_oos_data(data, metrics, "TestLowCoverage")
        assert r["recommendation"] == "BLOCK", r["recommendation"]
        assert r["has_critical_nan"] is True

    # Some NaN in data but metrics clean → WARN
    def test_warn():
        # 100 rows, 3 NaN cells → coverage 97% (between 90–95 threshold)
        closes = [100.0 + i for i in range(100)]
        closes[5] = float("nan")
        closes[20] = float("nan")
        closes[50] = float("nan")
        data = pd.DataFrame({"Close": closes})
        metrics = {
            "sharpe": 1.0, "max_drawdown": -0.10, "win_rate": 0.55,
            "profit_factor": 1.4, "total_trades": 50, "post_cost_sharpe": 1.0,
        }
        r = validate_oos_data(data, metrics, "TestWarn")
        assert r["recommendation"] in ("WARN", "PASS"), r["recommendation"]

    # None metric → BLOCK
    def test_none_metric():
        data = pd.DataFrame({"Close": [100.0, 101.0]})
        metrics = {
            "sharpe": 1.0, "max_drawdown": None, "win_rate": 0.55,
            "profit_factor": 1.4, "total_trades": 50, "post_cost_sharpe": 1.0,
        }
        r = validate_oos_data(data, metrics, "TestNoneMetric")
        assert r["recommendation"] == "BLOCK", r["recommendation"]
        assert "max_drawdown" in r["metrics_nan_fields"]

    _case("clean data + metrics → PASS", test_clean)
    _case("NaN sharpe → BLOCK", test_nan_metric)
    _case("low data coverage → BLOCK", test_low_coverage)
    _case("sparse NaN in data → WARN/PASS", test_warn)
    _case("None metric → BLOCK", test_none_metric)

    print(f"\n{passed}/{total} tests passed")
    return passed == total


if __name__ == "__main__":
    print("Running oos_data_quality smoke tests...\n")
    import sys
    ok = _run_tests()
    sys.exit(0 if ok else 1)
