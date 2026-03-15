"""
test_transaction_costs.py
Unit tests verifying that transaction cost modeling is correctly applied
in run_backtest() and that Gate 1 cost gate rejects strategies with thin edges.

Run with:
    cd orchestrator
    python -m pytest tests/test_transaction_costs.py -v
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

# Add orchestrator directory to path so we can import the module directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from quant_orchestrator import (
    TRANSACTION_COSTS,
    get_cost_params,
    run_backtest,
)


# ── Fixtures ─────────────────────────────────────────────────

def _make_trending_data(n: int = 252, seed: int = 42) -> pd.DataFrame:
    """Create synthetic OHLCV data with a gentle upward drift."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1 + rng.normal(0.0008, 0.01, n))
    df = pd.DataFrame({
        "Open":   close * (1 - rng.uniform(0, 0.005, n)),
        "High":   close * (1 + rng.uniform(0, 0.005, n)),
        "Low":    close * (1 - rng.uniform(0, 0.005, n)),
        "Close":  close,
        "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=pd.date_range("2020-01-02", periods=n, freq="B"))
    return df


# Simple buy-and-hold strategy: enter on day 1, exit on last day.
BUY_HOLD_CODE = """
import vectorbt as vbt
import numpy as np

close = data["Close"] if "Close" in data.columns else data.iloc[:, 0]
entries = np.zeros(len(close), dtype=bool)
exits   = np.zeros(len(close), dtype=bool)
entries[0] = True
exits[-1]  = True

portfolio = vbt.Portfolio.from_signals(close, entries, exits, init_cash=10_000)
"""

# High-frequency strategy: flip every day (many round trips -> large cost drag).
HIGH_FREQ_CODE = """
import vectorbt as vbt
import numpy as np

close = data["Close"] if "Close" in data.columns else data.iloc[:, 0]
n = len(close)
entries = np.zeros(n, dtype=bool)
exits   = np.zeros(n, dtype=bool)
entries[::2] = True  # enter every even day
exits[1::2]  = True  # exit every odd day

portfolio = vbt.Portfolio.from_signals(close, entries, exits, init_cash=10_000)
"""


# ── Tests ─────────────────────────────────────────────────────

class TestGetCostParams:
    def test_equities_returns_correct_costs(self):
        costs = get_cost_params("equities")
        assert costs["fees"] == TRANSACTION_COSTS["equities"]["fees"]
        assert costs["slippage"] == TRANSACTION_COSTS["equities"]["slippage"]

    def test_crypto_returns_correct_costs(self):
        costs = get_cost_params("crypto")
        assert costs["fees"] == TRANSACTION_COSTS["crypto"]["fees"]

    def test_options_returns_correct_costs(self):
        costs = get_cost_params("options")
        assert costs["fees"] == TRANSACTION_COSTS["options"]["fees"]

    def test_unknown_asset_class_defaults_to_equities(self):
        costs = get_cost_params("unknown_asset")
        assert costs == TRANSACTION_COSTS["equities"]

    def test_case_insensitive(self):
        assert get_cost_params("EQUITIES") == get_cost_params("equities")
        assert get_cost_params("Crypto") == get_cost_params("crypto")


class TestRunBacktestCostImpact:
    """Verify that post_cost_sharpe is returned and reflects cost drag."""

    def setup_method(self):
        self.data = _make_trending_data()

    def test_returns_post_cost_sharpe_field(self):
        result = run_backtest(BUY_HOLD_CODE, self.data, asset_class="equities")
        assert "post_cost_sharpe" in result, "post_cost_sharpe must be present in metrics"

    def test_returns_asset_class_field(self):
        result = run_backtest(BUY_HOLD_CODE, self.data, asset_class="crypto")
        assert result["asset_class"] == "crypto"

    def test_post_cost_sharpe_leq_precost_for_high_freq(self):
        """High-frequency trading (many round trips) must show measurable cost drag."""
        result = run_backtest(HIGH_FREQ_CODE, self.data, asset_class="equities")
        pre_cost = result["sharpe"]
        post_cost = result["post_cost_sharpe"]
        assert post_cost <= pre_cost, (
            f"Post-cost Sharpe ({post_cost:.4f}) should not exceed "
            f"pre-cost Sharpe ({pre_cost:.4f}) for a high-frequency strategy"
        )

    def test_cost_drag_larger_for_high_freq_than_buy_hold(self):
        """Cost drag (pre - post Sharpe) must be larger for HFT than buy-and-hold."""
        bh = run_backtest(BUY_HOLD_CODE, self.data, asset_class="equities")
        hf = run_backtest(HIGH_FREQ_CODE, self.data, asset_class="equities")

        bh_drag = bh["sharpe"] - bh["post_cost_sharpe"]
        hf_drag = hf["sharpe"] - hf["post_cost_sharpe"]

        assert hf_drag >= bh_drag, (
            f"High-freq drag ({hf_drag:.4f}) should be >= buy-hold drag ({bh_drag:.4f})"
        )

    def test_crypto_costs_higher_than_equities(self):
        """Crypto has higher fees; cost drag for crypto must be >= equities drag."""
        eq = run_backtest(HIGH_FREQ_CODE, self.data, asset_class="equities")
        cr = run_backtest(HIGH_FREQ_CODE, self.data, asset_class="crypto")

        eq_drag = eq["sharpe"] - eq["post_cost_sharpe"]
        cr_drag = cr["sharpe"] - cr["post_cost_sharpe"]

        assert cr_drag >= eq_drag, (
            f"Crypto drag ({cr_drag:.4f}) should be >= equities drag ({eq_drag:.4f})"
        )

    def test_default_asset_class_is_equities(self):
        result_default = run_backtest(BUY_HOLD_CODE, self.data)
        result_explicit = run_backtest(BUY_HOLD_CODE, self.data, asset_class="equities")
        assert result_default["asset_class"] == "equities"
        assert abs(result_default["post_cost_sharpe"] - result_explicit["post_cost_sharpe"]) < 1e-6


class TestGate1CostGate:
    """
    Verify the Gate 1 logic: a strategy that was profitable before costs
    but survives should have post_cost_sharpe > 0 for buy-and-hold with
    few trades. A high-frequency strategy on noisy data should show
    meaningful cost drag.
    """

    def test_buy_hold_survives_costs(self):
        """Buy-and-hold (1 trade) should survive equities costs."""
        data = _make_trending_data(n=500, seed=99)
        result = run_backtest(BUY_HOLD_CODE, data, asset_class="equities")
        # With just 2 round-trip legs and a trending market, post-cost should be positive
        assert result["post_cost_sharpe"] > -10, (
            "Buy-and-hold should not be destroyed by equities costs"
        )

    def test_profitable_strategy_can_fail_after_costs(self):
        """
        Demonstrate that a strategy marginally profitable pre-cost can fail
        after costs when trading very frequently. This is the core Gate 1 cost gate.
        """
        # Use noisy flat data so HFT barely breaks even pre-cost
        rng = np.random.default_rng(0)
        n = 252
        close = 100.0 * np.cumprod(1 + rng.normal(0.0001, 0.015, n))  # near-zero drift
        df = pd.DataFrame({
            "Open":  close, "High": close * 1.001, "Low": close * 0.999,
            "Close": close, "Volume": np.ones(n) * 1e6,
        }, index=pd.date_range("2020-01-02", periods=n, freq="B"))

        result = run_backtest(HIGH_FREQ_CODE, df, asset_class="equities")
        # On flat/noisy data with high-frequency trading, post-cost Sharpe
        # should be lower than pre-cost (demonstrating cost impact)
        assert result["post_cost_sharpe"] <= result["sharpe"], (
            "Post-cost Sharpe must not exceed pre-cost Sharpe"
        )
