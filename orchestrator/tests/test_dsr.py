"""
test_dsr.py
Unit tests for compute_dsr() — Deflated Sharpe Ratio calculation.

Run with:
    cd orchestrator
    python -m pytest tests/test_dsr.py -v
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from quant_orchestrator import compute_dsr


def make_returns(n: int = 500, mean: float = 0.001, std: float = 0.01, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mean, std, n))


class TestComputeDsr:
    def test_returns_required_keys(self):
        r = make_returns()
        result = compute_dsr(r, trials_tested=1)
        assert "dsr_zscore" in result
        assert "dsr_probability" in result
        assert "dsr_sr_star" in result
        assert "passed" in result
        assert "n_obs" in result

    def test_positive_edge_passes_single_trial(self):
        """A strong, consistent positive-return series should pass DSR with 1 trial."""
        r = make_returns(n=1000, mean=0.002, std=0.005)
        result = compute_dsr(r, trials_tested=1)
        assert result["passed"] is True
        assert result["dsr_zscore"] > 0

    def test_dsr_decreases_as_trials_increase(self):
        """DSR z-score must decrease monotonically as trials_tested increases."""
        r = make_returns(n=1000, mean=0.001, std=0.01)
        trial_counts = [1, 5, 20, 100]
        scores = [compute_dsr(r, trials_tested=t)["dsr_zscore"] for t in trial_counts]
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1], (
                f"DSR z-score should decrease as trials increase: "
                f"trials={trial_counts[i]} → score={scores[i]:.4f}, "
                f"trials={trial_counts[i+1]} → score={scores[i+1]:.4f}"
            )

    def test_negative_returns_fail(self):
        """Series with negative mean returns should fail DSR."""
        r = make_returns(n=500, mean=-0.001, std=0.01)
        result = compute_dsr(r, trials_tested=1)
        assert result["passed"] is False

    def test_insufficient_observations_returns_inf_fail(self):
        """Series with fewer than 2 observations returns -inf z-score and fails."""
        r = pd.Series([0.01])
        result = compute_dsr(r, trials_tested=1)
        assert result["passed"] is False
        assert result["dsr_zscore"] == float("-inf")

    def test_zero_variance_returns_zero_fail(self):
        """Constant returns (zero variance) should fail gracefully."""
        r = pd.Series([0.001] * 100)
        result = compute_dsr(r, trials_tested=1)
        assert result["passed"] is False

    def test_large_trial_count_significantly_reduces_dsr(self):
        """DSR z-score must be materially lower with many trials than with few."""
        r = make_returns(n=500, mean=0.0005, std=0.01)
        result_few = compute_dsr(r, trials_tested=1)
        result_many = compute_dsr(r, trials_tested=1000)
        assert result_few["dsr_zscore"] > result_many["dsr_zscore"]
        # The reduction should be substantial — SR* grows with log(trials)
        reduction = result_few["dsr_zscore"] - result_many["dsr_zscore"]
        assert reduction > 0.5, (
            f"Expected DSR z-score reduction > 0.5 but got {reduction:.4f}"
        )

    def test_n_obs_matches_series_length(self):
        n = 300
        r = make_returns(n=n)
        result = compute_dsr(r, trials_tested=1)
        assert result["n_obs"] == n
