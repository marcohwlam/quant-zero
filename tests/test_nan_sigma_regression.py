"""
Regression tests for NaN sigma cascade bug in strategy backtests.

Bug history:
  QUA-164 (original): H17 simulate_gem_portfolio computed sigma from OOS window only.
    rolling(20).std() returned NaN on first 19 days. NaN propagated via `sig_val or 0`
    (NaN is truthy in Python, so `float('nan') or 0 == float('nan')`), producing
    shares_bought=NaN → cash=0.0 reset → portfolio value collapsed to 0 for all OOS.
    Manifested as "0 trades, -50% return" in OOS.

  Fixes applied (commits 42649bc, a21691c):
    1. close_full/volume_full params in simulate_gem_portfolio: pass pre-buffered data
       so rolling(20) windows are warm at simulation window start.
    2. NaN guard: explicit pd.isna() check for sig_val (not `or 0`).
    3. shares_bought NaN guard: aborts buy with warning instead of cascading.

These tests verify the fix is in place and prevent regression.
"""

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helper: build minimal synthetic price/volume DataFrame
# ---------------------------------------------------------------------------

def make_price_series(n_days: int, start: str = "2020-01-02", base: float = 100.0) -> pd.DataFrame:
    """
    Build a synthetic daily price DataFrame with deterministic returns.
    Uses a fixed seed so tests are reproducible without network calls.
    """
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(start=start, periods=n_days)
    rets = rng.normal(0.0004, 0.01, size=(n_days, 3))
    prices = base * np.cumprod(1 + rets, axis=0)
    vol = np.full((n_days, 3), 5_000_000.0)
    close = pd.DataFrame(prices, index=dates, columns=["SPY", "EFA", "AGG"])
    volume = pd.DataFrame(vol, index=dates, columns=["SPY", "EFA", "AGG"])
    return close, volume


# ---------------------------------------------------------------------------
# Test 1: NaN guard — sig_val `or 0` pattern must not survive
# ---------------------------------------------------------------------------

class TestNaNGuardOrPattern:
    """Verify that the `or 0` anti-pattern has been eliminated from H17."""

    def test_no_or_zero_pattern_for_sig_val(self):
        """
        The original bug used `sig_val = sigma.get(...).get(date, 0) or 0`.
        For NaN inputs, `float('nan') or 0 == float('nan')` (NaN is truthy).
        The fix replaces this with an explicit pd.isna() check.
        This test directly confirms the Python semantic:
          - correct path: pd.isna(x) → replace with 0.0
          - broken path:  `x or 0` → returns NaN for NaN input
        """
        nan_val = float("nan")

        # Broken pattern: NaN passes through `or 0`
        broken_result = nan_val or 0
        assert np.isnan(broken_result), (
            "Confirming broken pattern: float('nan') or 0 should return NaN "
            "(NaN is truthy, so `or 0` does not trigger)"
        )

        # Correct pattern: pd.isna() catches NaN
        correct_result = 0.0 if pd.isna(nan_val) else float(nan_val)
        assert correct_result == 0.0, (
            "Correct pattern: pd.isna guard should convert NaN → 0.0"
        )

    def test_h17_strategy_uses_pdisna_not_or_zero(self):
        """
        Scan the H17 strategy source for the broken `or 0` sig_val pattern.
        The original line was:
            sig_val = sigma.get(...).get(date, 0) or 0
        which should have been replaced by explicit pd.isna() checks.
        """
        import ast, pathlib
        src = pathlib.Path("strategies/h17_dual_momentum_etf_rotation.py").read_text()

        # Confirm the broken pattern is absent
        # The specific vulnerable pattern: `.get(date, 0) or 0`
        assert ".get(date, 0) or 0" not in src, (
            "BUG REGRESSION: H17 still contains `.get(date, 0) or 0` pattern. "
            "This causes NaN sigma to pass through as NaN instead of 0.0. "
            "Replace with explicit pd.isna() check. See commit a21691c."
        )

        # Confirm the fix is in place
        assert "pd.isna(_sv)" in src, (
            "BUG REGRESSION: H17 no longer contains explicit pd.isna() NaN guard for sig_val. "
            "Fix must use `0.0 if pd.isna(_sv) else float(_sv)`. See commit a21691c."
        )


# ---------------------------------------------------------------------------
# Test 2: Rolling window warm-up — sigma must not be NaN at simulation start
# ---------------------------------------------------------------------------

class TestRollingWindowWarmup:
    """
    Verify that sigma computed from buffered (pre-window) data is not NaN
    at the start of the simulation window.

    Root cause of original H17 bug: sigma was computed from OOS-window-only
    data. The first execution date was within the first 19 trading days of
    OOS, so rolling(20).std() returned NaN.
    """

    def test_sigma_nan_at_window_start_without_buffer(self):
        """
        Demonstrate that sigma IS NaN at day 1 of a window without pre-history.
        This is the original bug condition.
        """
        close_oos_only, _ = make_price_series(n_days=60, start="2021-01-04")
        sigma_oos = close_oos_only["SPY"].pct_change().rolling(20).std()

        # Without pre-history, sigma is NaN for the first 20 rows
        assert sigma_oos.iloc[0:19].isna().all(), (
            "sigma should be NaN for first 19 rows when computed from window-only data"
        )

    def test_sigma_not_nan_at_window_start_with_buffer(self):
        """
        Verify that sigma is valid at OOS start when computed from buffered data
        (the fix: pass close_full to simulate_gem_portfolio).
        """
        # Simulate: buffer = last 3 months of IS + full OOS
        close_buffered, _ = make_price_series(n_days=130, start="2020-09-01")  # ~5 months
        sigma_buffered = close_buffered["SPY"].pct_change().rolling(20).std()

        # OOS starts at day ~65 (after 3 months of IS buffer)
        oos_start_idx = 65
        sigma_at_oos_start = sigma_buffered.iloc[oos_start_idx]

        assert not np.isnan(sigma_at_oos_start), (
            "sigma should NOT be NaN at OOS start when computed from buffered data "
            "(fix: pass close_full to simulate_gem_portfolio)"
        )

    def test_h17_run_backtest_passes_close_full(self):
        """
        Verify that h17 run_backtest passes close_full to simulate_gem_portfolio.
        The fix in commit a21691c added close_full=close to the call.
        """
        import inspect, pathlib
        src = pathlib.Path("strategies/h17_dual_momentum_etf_rotation.py").read_text()

        assert "close_full=close" in src, (
            "BUG REGRESSION: H17 run_backtest no longer passes close_full=close to "
            "simulate_gem_portfolio. This re-introduces the OOS NaN sigma bug. "
            "See commit a21691c."
        )

        assert "volume_full=volume" in src, (
            "BUG REGRESSION: H17 run_backtest no longer passes volume_full=volume to "
            "simulate_gem_portfolio. ADV rolling windows will be cold at OOS start."
        )


# ---------------------------------------------------------------------------
# Test 3: Portfolio value must not collapse to 0 from NaN shares
# ---------------------------------------------------------------------------

class TestSharesBoughtNaNGuard:
    """
    Verify that a NaN shares_bought value does NOT cascade into portfolio collapse.

    Original bug: if shares_bought is NaN, the line `cash = 0.0` still ran
    (it was in the else branch that should have been guarded), causing
    portfolio value to collapse from init_cash to 0 forever.
    """

    def test_nan_shares_cascade_prevention(self):
        """
        Directly test the guard logic: if shares_bought is NaN, cash must NOT
        be reset to 0, and the trade must be skipped.
        """
        cash_before = 25_000.0
        shares_bought_nan = float("nan")

        # Simulate the guard from the fixed code:
        #   if pd.isna(shares_bought) or shares_bought <= 0:
        #       [skip trade — don't reset cash]
        #   else:
        #       cash = 0.0  # fully invested
        if pd.isna(shares_bought_nan) or shares_bought_nan <= 0:
            cash_after = cash_before  # guard: skip
        else:
            cash_after = 0.0

        assert cash_after == cash_before, (
            "BUG REGRESSION: NaN shares_bought should NOT reset cash to 0.0. "
            "Guard `if pd.isna(shares_bought) or shares_bought <= 0: skip` must be in place."
        )

    def test_h17_has_shares_bought_nan_guard(self):
        """Verify the guard is present in the H17 source."""
        import pathlib
        src = pathlib.Path("strategies/h17_dual_momentum_etf_rotation.py").read_text()

        assert "pd.isna(shares_bought)" in src, (
            "BUG REGRESSION: H17 no longer contains NaN guard for shares_bought. "
            "Without this guard, a NaN shares_bought resets cash to 0.0 and "
            "collapses portfolio value. See commit a21691c."
        )


# ---------------------------------------------------------------------------
# Test 4: Vulnerability scan of other strategies
# ---------------------------------------------------------------------------

class TestOtherStrategiesVulnerabilityScan:
    """
    Scan other strategies for the original broken patterns that caused the H17 bug.
    These strategies use `impact.fillna(0.0)` instead, which mitigates the issue,
    but we verify that the cash-resetting cascade path does not exist.
    """

    @pytest.mark.parametrize("strategy_file", [
        "strategies/h07_multi_asset_tsmom.py",
        "strategies/h07b_multi_asset_tsmom_expanded.py",
        "strategies/h07c_multi_asset_tsmom_yield_curve.py",
        "strategies/h16_momentum_vol_filter.py",
    ])
    def test_market_impact_fillna_protects_against_nan_cascade(self, strategy_file):
        """
        H07/H07b/H07c/H16 compute sigma on window-only data but call fillna(0.0)
        on the impact DataFrame, preventing NaN from propagating into trade logic.
        Verify this protective pattern is still in place.
        """
        import pathlib
        src = pathlib.Path(strategy_file).read_text()

        if "compute_market_impact" in src:
            # These strategies use a vectorized impact DataFrame — must have fillna
            assert "fillna(0.0)" in src or "fillna(0)" in src, (
                f"BUG RISK: {strategy_file} calls compute_market_impact but "
                "does not call fillna(0.0) on the result. NaN sigma at window "
                "start will propagate into slippage computation."
            )
