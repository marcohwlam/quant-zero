"""QUA-824 regression tests: H10 runner accounting and gate logging."""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.paper_trading import h10_paper_runner as r


def test_blocking_gate_order():
    assert r.blocking_gate({"regime_ok": False, "warmup_ok": True}, 0, False) == "btc_regime_gate"
    assert r.blocking_gate({"warmup_ok": False}, 0, False) == "warmup"
    g = {"warmup_ok": True, "regime_ok": True, "eql_zone_count": 0, "eqh_zone_count": 0}
    assert r.blocking_gate(g, 0, False) == "no_eql_eqh_zone"
    g.update(eql_zone_count=2)
    assert r.blocking_gate(g, 0, False) == "price_not_near_zone"
    g.update(near_eql_zone=True)
    assert r.blocking_gate(g, 0, False) == "no_breach_recovery_pattern"
    assert r.blocking_gate(g, 1, False) == "none"
    assert r.blocking_gate({}, 0, True) == "position_open"
    assert r.blocking_gate({"error": "x"}, 0, False) == "signal_eval_error"


def test_evaluation_log_counts_match_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "CANONICAL_DIR", str(tmp_path))
    sigs = {t: {"signal": 0, "signal_type": "flat", "gate": {"warmup_ok": True, "regime_ok": False}}
            for t in r.UNIVERSE}
    for _ in range(3):
        r.write_evaluation_log(sigs, [])
    with open(tmp_path / "evaluations.csv") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3 * len(r.UNIVERSE)
    assert {x["blocked_by"] for x in rows} == {"btc_regime_gate"}
    assert r.count_evaluations()[0] == len(rows)


def test_reset_clock_archives(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "CANONICAL_DIR", str(tmp_path))
    for n in ("equity.csv", "meta.json", "evaluations.csv", "trades.csv"):
        (tmp_path / n).write_text("x")
    out = r.reset_clock()
    assert sorted(out["archived"]) == ["equity.csv", "evaluations.csv", "meta.json"]
    assert (tmp_path / "trades.csv").exists() and not (tmp_path / "meta.json").exists()
