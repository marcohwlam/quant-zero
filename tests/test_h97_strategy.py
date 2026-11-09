"""Unit tests for the H97 52-week-high sector momentum strategy (synthetic data, no network)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies import h97_52wk_high_sector_momentum as h97  # noqa: E402

SECTORS = ["XLB", "XLE", "XLF", "XLK"]


def _params(**kw):
    p = dict(h97.PARAMETERS)
    p.update({"tickers": SECTORS, "trend_sma": 20, "high_window": 60}, **kw)
    return p


def _data(spy_drift=0.001, n=500, seed=0, drifts=None):
    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(seed)
    cols = {"SPY": 100 * np.cumprod(1 + spy_drift + rng.normal(0, 0.002, n)),
            "SHY": 80 * np.cumprod(1 + 0.0001 + rng.normal(0, 0.0005, n))}
    drifts = drifts or {}
    for tk in SECTORS:
        cols[tk] = 50 * np.cumprod(1 + drifts.get(tk, 0.0008) + rng.normal(0, 0.008, n))
    close = pd.DataFrame(cols, index=idx)
    return {"open": close, "high": close * 1.003, "low": close * 0.997, "close": close,
            "volume": pd.DataFrame(5e6, index=idx, columns=close.columns)}


def test_monthly_dates_are_last_trading_day_of_month():
    idx = pd.bdate_range("2024-01-01", "2024-04-30").drop(pd.Timestamp("2024-03-29"))
    reb = h97.monthly_rebalance_dates(idx)
    assert list(reb.strftime("%Y-%m-%d")) == ["2024-01-31", "2024-02-29", "2024-03-28", "2024-04-30"]


def test_trade_cost_ultra_liquid_cheaper_and_flags_liquidity():
    c_spy, _ = h97.trade_cost(100, 100.0, "SPY", 0.01, 1e8)
    c_xl, _ = h97.trade_cost(100, 100.0, "XLK", 0.01, 1e8)
    assert c_spy < c_xl
    _, liq = h97.trade_cost(20000, 100.0, "XLK", 0.01, 1e6)
    assert liq is True


def test_select_targets_threshold_and_retention():
    p = _params()
    r = pd.Series({"XLB": 0.99, "XLE": 0.95, "XLF": 0.88, "XLK": 0.70})
    assert h97.select_targets(r, set(), p) == ["XLB", "XLE"]
    r2 = pd.Series({"XLB": 0.99, "XLE": 0.95, "XLF": 0.88, "XLK": 0.70})
    assert "XLF" in h97.select_targets(r2, {"XLF"}, p)      # held, ratio >= 0.85 stays
    r3 = pd.Series({"XLB": 0.99, "XLE": 0.95, "XLF": 0.84, "XLK": 0.70})
    assert "XLF" not in h97.select_targets(r3, {"XLF"}, p)  # held, ratio < 0.85 exits


def test_gate_off_holds_only_refuge():
    res = h97.run_backtest(_data(spy_drift=-0.003), _params())
    assert all(t["refuge"] for t in res["trades"])  # SHY is bought and held, never closed
    assert res["equity"].iloc[-1] > h97.PARAMETERS["init_cash"]


def test_entries_only_on_rebalance_dates_and_max_positions():
    d = _data()
    res = h97.run_backtest(d, _params(stop_pct=None))
    reb = {str(x.date()) for x in h97.monthly_rebalance_dates(d["close"].index)}
    sector = [t for t in res["trades"] if not t["refuge"]]
    assert sector and all(t["entry_date"] in reb for t in sector)
    assert max(sum(1 for t in sector if t["entry_date"] == e) for e in reb) <= 3


def test_stop_exits_below_threshold():
    d = _data(drifts={"XLB": 0.003, "XLE": 0.003, "XLF": 0.003, "XLK": 0.003}, seed=3)
    crash = d["close"].index[300]
    for tk in SECTORS:
        d["close"].loc[crash:, tk] *= 0.7
    d["high"] = d["close"] * 1.003
    res = h97.run_backtest(d, _params())
    stops = [t for t in res["trades"] if t["reason"] == "stop"]
    assert stops and all(t["exit_px"] < t["entry_px"] * 0.88 for t in stops)


def test_null_mode_reproducible_and_metrics_exclude_refuge():
    d = _data()
    a = h97.run_backtest(d, _params(), seed=5)
    b = h97.run_backtest(d, _params(), seed=5)
    assert a["equity"].equals(b["equity"])
    m = h97.compute_metrics(a, "2020-01-01", "2030-01-01")
    assert m["trade_count"] == sum(1 for t in a["trades"] if not t["refuge"])


def test_validate_data_rejects_missing_gate():
    d = _data()
    d["close"] = d["close"].drop(columns=["SPY"])
    with pytest.raises(ValueError):
        h97.validate_data(d, _params())
