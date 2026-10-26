"""Daily H10 paper-trading consistency alarm (QUA-826).

Checks, per QUA-808 CEO decision (Option 1, clock reset 2026-10-26):
  1. EQUITY_WITHOUT_ACTIVITY: equity changed day over day with zero positions and zero trades.
  2. SIGNAL_GAP: gap between consecutive signal-evaluation days exceeds 3 trading days
     (or the last evaluation is more than 3 trading days before the as-of date).
  3. Progress toward the Gate 2 evidence target: 90 evaluated days AND 8 trades (whichever is later).

Exit code 0 = clean, 1 = at least one alarm (caller posts to the Risk Director).
"""
import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

STRAT_DIR = Path(__file__).resolve().parents[1] / "paper_trading" / "h10_crypto_eql_reversal_v2"
WINDOW_START = date(2026, 10, 26)
TARGET_DAYS = 90
TARGET_TRADES = 8
MAX_GAP_TRADING_DAYS = 3
EQUITY_TOL = 0.01  # dollars


def _d(s):
    return datetime.fromisoformat(s.strip()).date()


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def trading_days_between(a, b):
    """Weekdays strictly after a, up to and including b."""
    if b <= a:
        return 0
    return int(np.busday_count(a + timedelta(days=1), b + timedelta(days=1)))


def live_rows(trades, start):
    return [r for r in trades if r.get("dry_run", "").strip().lower() != "true" and _d(r["date"]) >= start]


def is_fill(r):
    return r.get("action", "flat") not in ("", "flat") and bool(r.get("fill_qty", "").strip())


def evaluate(equity, trades, as_of, start=WINDOW_START):
    alarms = []
    rows = live_rows(trades, start)
    eval_days = sorted({_d(r["date"]) for r in rows})
    n_trades = sum(1 for r in rows if is_fill(r))

    # 1. Equity change with no positions and no trades. Compare consecutive equity rows
    # inside the window plus the last row before it, so a jump on day one is caught.
    eq = sorted(((_d(r["date"]), float(r["portfolio_value"])) for r in equity))
    prior = [e for e in eq if e[0] < start][-1:]
    inwin = [e for e in eq if e[0] >= start]
    fill_days = {_d(r["date"]) for r in rows if is_fill(r)}
    open_pos_days = {_d(r["date"]) for r in rows if r.get("has_position", "").strip().lower() == "true"}
    seq = prior + inwin
    for (_, prev), (day, cur) in zip(seq, seq[1:]):
        if abs(cur - prev) > EQUITY_TOL and day not in fill_days and day not in open_pos_days:
            alarms.append({
                "code": "EQUITY_WITHOUT_ACTIVITY",
                "detail": f"{day}: equity {prev:,.2f} -> {cur:,.2f} with zero positions and zero trades",
            })

    # 2. Signal-evaluation gaps (outage detection).
    anchor = [start - timedelta(days=1)] if not eval_days else []
    pts = (anchor + eval_days) if anchor else eval_days
    for a, b in zip(pts, pts[1:]):
        gap = trading_days_between(a, b) - 1  # missed trading days between evaluations
        if gap > MAX_GAP_TRADING_DAYS:
            alarms.append({"code": "SIGNAL_GAP", "detail": f"no evaluation between {a} and {b} ({gap} trading days)"})
    last = eval_days[-1] if eval_days else None
    ref = last or (start - timedelta(days=1))
    tail = trading_days_between(ref, as_of) - (0 if as_of.weekday() >= 5 else 1)
    if tail > MAX_GAP_TRADING_DAYS:
        alarms.append({"code": "SIGNAL_GAP", "detail": f"last evaluation {last}, {tail} trading days stale as of {as_of}"})

    progress = {
        "evaluated_days": len(eval_days),
        "trades": n_trades,
        "target": f"{TARGET_DAYS} days AND {TARGET_TRADES} trades (whichever later)",
        "met": len(eval_days) >= TARGET_DAYS and n_trades >= TARGET_TRADES,
    }
    return {"as_of": str(as_of), "alarms": alarms, "progress": progress}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, default=STRAT_DIR)
    p.add_argument("--as-of", type=_d, default=date.today())
    a = p.parse_args(argv)
    res = evaluate(read_csv(a.dir / "equity.csv"), read_csv(a.dir / "trades.csv"), a.as_of)
    print(json.dumps(res, indent=2))
    return 1 if res["alarms"] else 0


if __name__ == "__main__":
    sys.exit(main())
