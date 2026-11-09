"""Unit tests for the H95 sector weekly reversal strategy (synthetic data, no network)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies import h95_sector_weekly_reversal as h95  # noqa: E402

SECTORS = ["XLB", "XLE", "XLF"]


def _params(**kw):
    p = dict(h95.PARAMETERS)
    p.update({"tickers": SECTORS, "trend_sma": 20, "n_long": 2}, **kw)
    return p


def _data(spy_drift=0.001, n=400, seed=0):
    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(seed)
    cols = {"SPY": 100 * np.cumprod(1 + spy_drift + rng.normal(0, 0.002, n))}
    for tk in SECTORS:
        cols[tk] = 50 * np.cumprod(1 + rng.normal(0, 0.01, n))
    close = pd.DataFrame(cols, index=idx)
    return {"open": close, "high": close * 1.005, "low": close * 0.995, "close": close,
            "volume": pd.DataFrame(5e6, index=idx, columns=close.columns)}


def test_weekly_dates_are_last_trading_day_of_week():
    idx = pd.bdate_range("2024-01-01", "2024-01-31")
    idx = idx.drop(pd.Timestamp("2024-01-19"))  # holiday-style gap on a Friday
    reb = h95.weekly_rebalance_dates(idx)
    assert pd.Timestamp("2024-01-18") in reb and pd.Timestamp("2024-01-19") not in reb
    assert all(d.day_of_week in (3, 4) for d in reb if d < pd.Timestamp("2024-01-29"))


def test_gate_off_means_no_trades():
    d = _data(spy_drift=-0.003)
    res = h95.run_backtest(d, _params())
    assert len(res["trades"]) == 0
    assert res["equity"].iloc[-1] == pytest.approx(h95.PARAMETERS["init_cash"])


def test_trades_open_and_close_on_rebalance_dates():
    d = _data()
    res = h95.run_backtest(d, _params(stop_atr_mult=None))
    reb = {str(x.date()) for x in h95.weekly_rebalance_dates(d["close"].index)}
    assert res["trades"], "expected trades in an up-trending gate"
    assert all(t["entry_date"] in reb for t in res["trades"])
    assert max(len([1 for t in res["trades"] if t["entry_date"] == e]) for e in reb) <= 2


def test_buys_worst_five_day_return():
    d = _data()
    p = _params(stop_atr_mult=None)
    res = h95.run_backtest(d, p)
    first = res["trades"][0]
    dt = pd.Timestamp(first["entry_date"])
    r5 = d["close"][SECTORS].pct_change(5).loc[dt]
    assert first["ticker"] in list(r5.nsmallest(2).index)


def test_stop_exit_fires_on_crash():
    d = _data()
    close = d["close"].copy()
    reb = h95.weekly_rebalance_dates(close.index)
    crash_day = close.index.get_loc(reb[40]) + 2
    close.iloc[crash_day:, :] = close.iloc[crash_day:, :] * 0.8  # all sectors gap down 20%
    d2 = dict(d, close=close, high=close * 1.005, low=close * 0.995)
    res = h95.run_backtest(d2, _params(stop_atr_mult=2.5))
    assert any(t["reason"] == "stop" for t in res["trades"])
    res_ns = h95.run_backtest(d2, _params(stop_atr_mult=None))
    assert not any(t["reason"] == "stop" for t in res_ns["trades"])


def test_no_lookahead_truncation_invariance():
    d = _data()
    p = _params()
    full = h95.run_backtest(d, p)
    # cut at a rebalance date so the truncated final week is a full week
    reb = h95.weekly_rebalance_dates(d["close"].index)
    cut_i = d["close"].index.get_loc(reb[reb > d["close"].index[290]][0]) + 1
    cut = {k: v.iloc[:cut_i] for k, v in d.items()}
    part = h95.run_backtest(cut, p)
    common = part["equity"].index
    # equity up to the cut must not depend on later data
    assert np.allclose(full["equity"].loc[common].values, part["equity"].values)


def test_cost_tiers_and_liquidity_flag():
    c_std, _ = h95.trade_cost(100, 50.0, "XLE", 0.01, 1e7)
    c_ultra, _ = h95.trade_cost(100, 50.0, "SPY", 0.01, 1e7)
    assert c_std > c_ultra
    assert h95.trade_cost(100, 50.0, "XLE", 0.01, 1e7)[1] is False
    assert h95.trade_cost(200000, 50.0, "XLE", 0.01, 1e7)[1] is True
    assert h95.trade_cost(0, 50.0, "XLE", 0.01, 1e7) == (0.0, False)


def test_permutation_seed_is_reproducible():
    d = _data()
    a = h95.run_backtest(d, _params(), seed=1)["equity"]
    b = h95.run_backtest(d, _params(), seed=1)["equity"]
    assert a.equals(b)


def test_validate_rejects_missing_gate():
    d = _data()
    d["close"] = d["close"].drop(columns=["SPY"])
    with pytest.raises(ValueError):
        h95.validate_data(d, _params())
