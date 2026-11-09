"""Unit tests for H96 volume capitulation reversal (QUA-913). Synthetic data only, no network."""
import numpy as np
import pandas as pd
import pytest

from strategies import h96_volume_capitulation_reversal_etf as h96


def _frame(n=400, seed=0, drop_at=None, drop=-0.05, vol_spike=4.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    close = 100 * np.cumprod(1 + rng.normal(0.0004, 0.004, n))
    vol = np.full(n, 1e6)
    if drop_at is not None:
        close[drop_at:] *= (1 + drop)
        vol[drop_at] *= vol_spike
    df = pd.DataFrame({"Open": close, "High": close * 1.002, "Low": close * 0.998, "Close": close, "Volume": vol},
                      index=idx)
    if drop_at is not None:
        df.iloc[drop_at, df.columns.get_loc("Low")] = close[drop_at] * 0.995
    return df


def _data(drop_at=300):
    return {"SPY": _frame(drop_at=drop_at), "QQQ": _frame(seed=1, drop_at=drop_at)}


def test_signal_fires_on_drop_with_volume():
    p = {**h96.PARAMETERS, "trend_gate": "none", "vix_pause": None, "spy_pause_signals": 0}
    sig = h96.generate_signals(_data(), p)
    assert sig["SPY"]["gated"].sum() == 1
    assert sig["SPY"].index[sig["SPY"]["gated"]][0] == _data()["SPY"].index[300]


def test_no_signal_without_volume():
    d = {"SPY": _frame(drop_at=300, vol_spike=1.0)}
    p = {**h96.PARAMETERS, "trend_gate": "none", "vix_pause": None, "spy_pause_signals": 0}
    assert h96.generate_signals(d, p)["SPY"]["gated"].sum() == 0


def test_no_lookahead_truncation():
    d = _data()
    p = {**h96.PARAMETERS, "trend_gate": "own_sma", "vix_pause": None}
    full = h96.generate_signals(d, p)["SPY"]["gated"]
    cut = {t: df.iloc[:350] for t, df in d.items()}
    part = h96.generate_signals(cut, p)["SPY"]["gated"]
    assert full.iloc[:350].equals(part)


def test_invalid_gate_raises():
    with pytest.raises(ValueError):
        h96.generate_signals(_data(), {**h96.PARAMETERS, "trend_gate": "bogus"})


def test_missing_spy_raises():
    with pytest.raises(ValueError):
        h96.generate_signals({"QQQ": _frame()}, h96.PARAMETERS)


def test_simulation_accounting_and_exit_rules():
    p = {**h96.PARAMETERS, "trend_gate": "none", "vix_pause": None, "spy_pause_signals": 0}
    d = _data()
    res = h96.run_backtest(d, p, "2010-06-01", "2011-06-30")
    t = res["trades"]
    assert len(t) >= 1
    assert (t["hold_days"] <= p["max_hold_days"]).all()
    assert set(t["reason"]) <= {"stop", "target", "time", "window_end"}
    # equity must equal init cash plus summed net pnl once flat at window end
    assert res["equity"].iloc[-1] == pytest.approx(p["init_cash"] + t["net_pnl"].sum(), rel=1e-9)


def test_costs_reduce_pnl_and_tiering():
    assert h96._slippage("SPY") == 0.00005
    assert h96._slippage("XLE") == 0.0005
    assert h96._impact(0.01, 100, 1e6) == pytest.approx(0.1 * 0.01 * np.sqrt(1e-4))
    assert h96._impact(np.nan, 100, 1e6) == 0.0


def test_max_positions_cap():
    p = {**h96.PARAMETERS, "trend_gate": "none", "vix_pause": None, "spy_pause_signals": 0, "max_positions": 1}
    res = h96.run_backtest(_data(), p, "2010-06-01", "2011-06-30")
    t = res["trades"]
    overlap = [(a.entry_date, a.exit_date) for a in t.itertuples()]
    assert len(overlap) == 1 or all(overlap[i][1] <= overlap[i + 1][0] for i in range(len(overlap) - 1))


def test_validate_ohlcv_rejects_bad_data():
    df = _frame()
    with pytest.raises(ValueError):
        h96.validate_ohlcv(df.drop(columns=["Volume"]))
    bad = df.copy()
    bad.iloc[5, bad.columns.get_loc("Close")] = -1
    with pytest.raises(ValueError):
        h96.validate_ohlcv(bad)


def test_metrics_empty_trades():
    m = h96.compute_metrics(pd.Series([0.0, 0.0, 0.0]), pd.DataFrame())
    assert m["trade_count"] == 0 and m["sharpe"] == 0.0


def test_runner_stats_deterministic():
    import importlib.util
    import pathlib
    path = pathlib.Path(__file__).parent.parent / "backtests" / "run_h96_gate1.py"
    spec = importlib.util.spec_from_file_location("run_h96", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = pd.Series(np.random.default_rng(3).normal(0.0005, 0.01, 800))
    assert mod.monte_carlo_sharpe(r, n=200) == mod.monte_carlo_sharpe(r, n=200)
    ci = mod.bootstrap_sharpe_ci(r, n=200)
    assert ci["lo"] < ci["hi"]
    tr = pd.DataFrame({"ret_net": np.full(30, 0.01)})
    assert mod.permutation_p(tr, n=500) < 0.01
