"""QUA-855: mixed-base equity curves must not create phantom portfolio drawdown."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_dashboard as bd


def rows(*pairs):
    return [{"date": d, "portfolio_value": v} for d, v in pairs]


def test_mixed_base_sparse_dates_no_phantom_dd():
    eq = {
        "a": rows(("2026-06-08", 5000), ("2026-06-09", 5000), ("2026-10-26", 5000)),
        "b": rows(("2026-06-08", 100187.6), ("2026-10-26", 99922.85)),
    }
    dd = bd.compute_portfolio_drawdown(eq, {"a": 5000, "b": 5000})
    assert dd < 1.0


def test_real_drawdown_detected():
    eq = {"a": rows(("2026-01-01", 5000), ("2026-01-02", 4500))}
    assert abs(bd.compute_portfolio_drawdown(eq, {"a": 5000}) - 10.0) < 1e-9


def test_divergence_guard():
    assert bd.portfolio_dd_divergence(95.25, [0.3, 0.0])
    assert bd.portfolio_dd_divergence(3.0, [2.5]) is None


def test_last_updated_key_both_accepted():
    assert bd._meta_last_update({"last_updated": "x"}) == "x"
    assert bd._meta_last_update({"last_update": "y"}) == "y"
    assert not bd.is_stale({"last_updated": "2999-01-01T00:00:00+00:00"}, "equities",
                           bd.datetime.now(bd.timezone.utc))


def test_build_alerts_dq_replaces_halt():
    out = bd.build_alerts([], {}, {}, 95.25, "dq")
    assert [a["type"] for a in out] == ["data_quality"]
