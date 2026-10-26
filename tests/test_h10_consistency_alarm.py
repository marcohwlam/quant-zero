from datetime import date

from scripts.h10_consistency_alarm import evaluate

S = date(2026, 10, 26)


def tr(d, fill=False, pos="False"):
    return {"date": f"{d} 16:00:00", "dry_run": "False", "has_position": pos,
            "action": "buy" if fill else "flat", "fill_qty": "1" if fill else ""}


def codes(res):
    return [a["code"] for a in res["alarms"]]


def test_clean_flat_days():
    eq = [{"date": "2026-10-26", "portfolio_value": "5000"}, {"date": "2026-10-27", "portfolio_value": "5000"}]
    res = evaluate(eq, [tr("2026-10-26"), tr("2026-10-27")], date(2026, 10, 27))
    assert res["alarms"] == [] and res["progress"]["evaluated_days"] == 2


def test_equity_change_without_activity():
    eq = [{"date": "2026-06-14", "portfolio_value": "5000"}, {"date": "2026-10-26", "portfolio_value": "99922.85"}]
    assert "EQUITY_WITHOUT_ACTIVITY" in codes(evaluate(eq, [tr("2026-10-26")], S))


def test_equity_change_with_trade_ok():
    eq = [{"date": "2026-10-26", "portfolio_value": "5000"}, {"date": "2026-10-27", "portfolio_value": "5100"}]
    res = evaluate(eq, [tr("2026-10-26"), tr("2026-10-27", fill=True)], date(2026, 10, 27))
    assert res["alarms"] == [] and res["progress"]["trades"] == 1


def test_signal_gap_between_evaluations():
    res = evaluate([], [tr("2026-10-26"), tr("2026-11-09")], date(2026, 11, 9))
    assert "SIGNAL_GAP" in codes(res)


def test_stale_tail():
    assert "SIGNAL_GAP" in codes(evaluate([], [tr("2026-10-26")], date(2026, 11, 6)))


def test_dry_run_and_pre_window_ignored():
    rows = [dict(tr("2026-10-26"), dry_run="True"), tr("2026-03-16")]
    assert evaluate([], rows, S)["progress"]["evaluated_days"] == 0
