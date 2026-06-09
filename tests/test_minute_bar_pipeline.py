"""
Integration tests for the minute-bar pipeline.

Requires ALPACA_API_KEY / ALPACA_API_SECRET env vars.
Tests skip gracefully when credentials are absent.
"""

import os
import pytest
import pandas as pd

from pipelines.minute_bar_store import MinuteBarStore
from pipelines.alpaca_ingest import AlpacaMinuteIngester
from pipelines.vwap_engine import VWAPEngine
from pipelines.vpin_engine import VPINEngine

ALPACA_KEY = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET = os.environ.get("ALPACA_API_SECRET")
HAS_CREDS = bool(ALPACA_KEY and ALPACA_SECRET)

requires_creds = pytest.mark.skipif(not HAS_CREDS, reason="ALPACA_API_KEY not set")

# Known trading dates for SPY
_DATE_1 = "2024-01-02"
_DATE_2 = "2024-01-03"

# UTC session boundaries for 09:30 ET on each date
# 2024-01-02 is EST (UTC-5), so 09:30 ET = 14:30 UTC
# 2024-01-03 is EST (UTC-5), so 09:30 ET = 14:30 UTC
_SESSION_OPEN_D1 = f"{_DATE_1}T14:30:00Z"
_SESSION_OPEN_D2 = f"{_DATE_2}T14:30:00Z"
_SESSION_END_D1 = f"{_DATE_1}T21:00:00Z"  # 16:00 ET = 21:00 UTC


def _build_store_with_data(tmp_path):
    """Shared fixture: ingest SPY for _DATE_1 and _DATE_2 into a temp DB."""
    db_file = str(tmp_path / "test_bars.db")
    store = MinuteBarStore(db_path=db_file)
    ingester = AlpacaMinuteIngester(api_key=ALPACA_KEY, api_secret=ALPACA_SECRET, store=store)
    ingester.fetch_and_store("SPY", f"{_DATE_1}T00:00:00Z", f"{_DATE_2}T23:59:00Z")
    return store


@requires_creds
def test_vwap_intraday_2024_01_02(tmp_path):
    """VWAP at 11:00 ET (16:00 UTC) on 2024-01-02 should be between SPY open and close."""
    store = _build_store_with_data(tmp_path)

    # 11:00 ET = 16:00 UTC on 2024-01-02 (EST)
    target_ts = f"{_DATE_1}T16:00:00Z"

    engine = VWAPEngine()
    vwap = engine.get_vwap("SPY", target_ts, store)

    # Load that session's bars for sanity-check bounds
    bars = store.get_bars("SPY", _SESSION_OPEN_D1, _SESSION_END_D1)
    assert not bars.empty, "No bars loaded for SPY 2024-01-02 session"

    session_low = bars["low"].min()
    session_high = bars["high"].max()

    # VWAP must be within session's low-high range
    assert session_low <= vwap <= session_high, (
        f"VWAP {vwap:.4f} outside session range [{session_low:.4f}, {session_high:.4f}]"
    )

    # Check vwap_dev_sigma is finite and within [-5, 5]
    augmented = engine.compute_vwap_deviation(bars)
    mid_idx = len(augmented) // 2
    sigma_vals = augmented["vwap_dev_sigma"].iloc[mid_idx:]  # skip warmup
    finite_vals = sigma_vals.dropna()
    assert len(finite_vals) > 0, "All vwap_dev_sigma values are NaN"
    assert finite_vals.between(-5, 5).all(), (
        f"vwap_dev_sigma out of [-5, 5]: {finite_vals[~finite_vals.between(-5, 5)].tolist()}"
    )


@requires_creds
def test_vpin_intraday_2024_01_02(tmp_path):
    """VPIN at 15:30 ET (20:30 UTC) on 2024-01-02 should be in [0, 1] with valid regime."""
    store = _build_store_with_data(tmp_path)

    # 15:30 ET = 20:30 UTC (EST)
    target_ts = f"{_DATE_1}T20:30:00Z"

    engine = VPINEngine()
    vpin = engine.get_vpin("SPY", target_ts, window=50, store=store)

    assert 0.0 <= vpin <= 1.0, f"VPIN {vpin} outside [0, 1]"

    regime = engine.classify_regime(vpin)
    valid_regimes = {"crisis", "directional", "mixed", "mean_reversion"}
    assert regime in valid_regimes, f"Unexpected regime: {regime}"


@requires_creds
def test_vwap_session_reset(tmp_path):
    """VWAP must reset at 09:30 ET on 2024-01-03 (should differ from end-of-day VWAP on 2024-01-02)."""
    store = _build_store_with_data(tmp_path)

    engine = VWAPEngine()

    # End of session on day 1: 16:00 ET = 21:00 UTC
    vwap_end_d1 = engine.get_vwap("SPY", _SESSION_END_D1, store)

    # First bar of session on day 2: 09:31 ET = 14:31 UTC
    vwap_open_d2 = engine.get_vwap("SPY", f"{_DATE_2}T14:31:00Z", store)

    # VWAP at day-2 open should be close to day-2's first bar close, not day-1's session VWAP
    # They must differ — a reset occurred
    assert vwap_end_d1 != vwap_open_d2, (
        f"VWAP did not reset between sessions: end_d1={vwap_end_d1:.4f}, open_d2={vwap_open_d2:.4f}"
    )

    # Verify day-2 open VWAP equals the first bar close (single-bar VWAP = close)
    bars_d2 = store.get_bars("SPY", _SESSION_OPEN_D2, f"{_DATE_2}T14:31:00Z")
    assert not bars_d2.empty, "No bars for 2024-01-03 session open"
    first_bar_close = bars_d2["close"].iloc[-1]
    # Single-bar VWAP = close * vol / vol = close; allow tiny float tolerance
    assert abs(vwap_open_d2 - first_bar_close) < 0.01, (
        f"Day-2 first-bar VWAP {vwap_open_d2:.4f} far from first bar close {first_bar_close:.4f}"
    )
