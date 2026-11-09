#!/usr/bin/env python3
"""
H97 Gate 1 Backtest Runner (QUA-914, parent QUA-911)
52-Week-High Proximity Sector Rotation (George and Hwang 2004)
IS: 2000-01-01 to 2019-12-31 | OOS: 2020-01-01 to 2024-12-31 | 4 walk-forward folds

The strategy has no fitted parameters, so the 4 walk-forward folds are contiguous 5-year test blocks
over the IS window (2000-04, 2005-09, 2010-14, 2015-19). Each fold reports its own Sharpe, MDD and
trade count; WF variance is the standard deviation of the fold Sharpes.

Outputs:
  backtests/h97_{date}.json
  backtests/h97_{date}_report.html
  backtests/h97_{date}_verdict.txt

Usage:
  cd /repos/quant-zero
  .venv/bin/python3 backtests/run_h97_gate1.py
"""

import html
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.h97_52wk_high_sector_momentum import (  # noqa: E402
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
    compute_metrics,
    data_quality_report,
    download_data,
    run_backtest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

OUT_DIR = Path(__file__).parent
TODAY = date.today().isoformat()
SLUG = f"h97_{TODAY}"

IS_START, IS_END = "2000-01-01", "2019-12-31"
OOS_START, OOS_END = "2020-01-01", "2024-12-31"
WF_FOLDS = [("2000-01-01", "2004-12-31"), ("2005-01-01", "2009-12-31"),
            ("2010-01-01", "2014-12-31"), ("2015-01-01", "2019-12-31")]
STRESS_WINDOWS = {"2000_2002": ("2000-01-01", "2002-12-31"), "2008": ("2008-01-01", "2008-12-31"),
                  "2008_2009": ("2008-01-01", "2009-12-31"), "2022": ("2022-01-01", "2022-12-31")}

GATE1_IS_SHARPE_MIN = 1.0
GATE1_OOS_SHARPE_MIN = 0.7
GATE1_MDD_MAX = -0.20
GATE1_MDD_WARN = -0.15
GATE1_MIN_TRADES = 100
GATE1_MIN_FOLD_TRADES = 30
GATE1_MC_P5_MIN = 0.0
GATE1_PERM_P_MAX = 0.05
N_PERMS = 200
N_BOOTS = 1000
SEED = 97


# ── Statistical rigor ─────────────────────────────────────────────────────────

def monte_carlo_sharpe(trade_rets: np.ndarray, years: float, n_sims: int = N_BOOTS,
                       rng: np.random.Generator = None) -> dict:
    """Bootstrap trade returns with replacement; Sharpe annualised by trades per year (p5, median, p95)."""
    rng = rng or np.random.default_rng(SEED)
    if len(trade_rets) < 2 or years <= 0:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    ann = np.sqrt(len(trade_rets) / years)
    sample = rng.choice(trade_rets, size=(n_sims, len(trade_rets)), replace=True)
    sd = sample.std(axis=1)
    sharpes = np.where(sd > 1e-12, sample.mean(axis=1) / np.where(sd > 1e-12, sd, 1.0) * ann, 0.0)
    return {"mc_p5_sharpe": float(np.percentile(sharpes, 5)), "mc_median_sharpe": float(np.median(sharpes)),
            "mc_p95_sharpe": float(np.percentile(sharpes, 95))}


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = N_BOOTS, rng: np.random.Generator = None) -> dict:
    """Block bootstrap 95% CI for daily-return Sharpe, MDD and positive-day share (block = sqrt(T))."""
    rng = rng or np.random.default_rng(SEED)
    T = len(returns)
    if T < 4:
        return {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0, "mdd_ci_low": 0.0, "mdd_ci_high": 0.0}
    block = max(1, int(np.sqrt(T)))
    n_blocks = int(np.ceil(T / block))
    sharpes, mdds = [], []
    for _ in range(n_boots):
        starts = rng.integers(0, T - block + 1, size=n_blocks)
        s = np.concatenate([returns[a:a + block] for a in starts])[:T]
        cum = np.cumprod(1 + s)
        peak = np.maximum.accumulate(cum)
        mdds.append(float(np.min(cum / peak - 1)))
        sd = s.std()
        sharpes.append(float(s.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR)) if sd > 1e-12 else 0.0)
    return {"sharpe_ci_low": float(np.percentile(sharpes, 2.5)), "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
            "mdd_ci_low": float(np.percentile(mdds, 2.5)), "mdd_ci_high": float(np.percentile(mdds, 97.5))}


def permutation_test(data: Dict[str, pd.DataFrame], observed_sharpe: float, n_perms: int = N_PERMS) -> dict:
    """
    Null: same gate, stop, sizing and qualification rules, but sectors are picked at random from the
    qualifying pool each month. p = share of null IS Sharpes >= observed (tests ranking skill only).
    """
    null = []
    for k in range(n_perms):
        res = run_backtest(data, PARAMETERS, seed=SEED + k)
        null.append(compute_metrics(res, IS_START, IS_END)["sharpe"])
    null_arr = np.array(null)
    p = float((np.sum(null_arr >= observed_sharpe) + 1) / (len(null_arr) + 1))
    return {"permutation_pvalue": round(p, 4), "permutation_test_pass": p <= GATE1_PERM_P_MAX,
            "null_sharpe_mean": float(null_arr.mean()), "null_sharpe_p95": float(np.percentile(null_arr, 95)),
            "n_perms": n_perms}


# ── Gate 1 verdict ────────────────────────────────────────────────────────────

def gate1_verdict(is_m: dict, oos_m: dict, folds: List[dict], rigor: dict) -> tuple:
    """Return (verdict, failures, warnings) against the Gate 1 criteria in criteria.md."""
    fails, warns = [], []
    if is_m["sharpe"] < GATE1_IS_SHARPE_MIN:
        fails.append(f"IS Sharpe {is_m['sharpe']:.3f} < {GATE1_IS_SHARPE_MIN}")
    if oos_m["sharpe"] < GATE1_OOS_SHARPE_MIN:
        fails.append(f"OOS Sharpe {oos_m['sharpe']:.3f} < {GATE1_OOS_SHARPE_MIN}")
    for label, m in (("IS", is_m), ("OOS", oos_m)):
        if m["max_drawdown"] < GATE1_MDD_MAX:
            fails.append(f"{label} MDD {m['max_drawdown']:.1%} worse than {GATE1_MDD_MAX:.0%}")
        elif m["max_drawdown"] <= GATE1_MDD_WARN:
            warns.append(f"{label} MDD {m['max_drawdown']:.1%} is at or beyond the {GATE1_MDD_WARN:.0%} warning line")
    if is_m["trade_count"] < GATE1_MIN_TRADES:
        fails.append(f"IS trade count {is_m['trade_count']} < {GATE1_MIN_TRADES}")
    thin = [f["fold"] for f in folds if f["trade_count"] < GATE1_MIN_FOLD_TRADES]
    if thin:
        fails.append(f"folds {thin} have fewer than {GATE1_MIN_FOLD_TRADES} trades")
    if rigor["mc"]["mc_p5_sharpe"] <= GATE1_MC_P5_MIN:
        fails.append(f"MC p5 Sharpe {rigor['mc']['mc_p5_sharpe']:.3f} <= {GATE1_MC_P5_MIN}")
    if not rigor["perm"]["permutation_test_pass"]:
        fails.append(f"permutation p {rigor['perm']['permutation_pvalue']:.3f} > {GATE1_PERM_P_MAX}")
    return ("PASS" if not fails else "FAIL"), fails, warns


# ── Reports ───────────────────────────────────────────────────────────────────

def verdict_text(report: dict) -> str:
    """Plain-text Gate 1 verdict."""
    is_m, oos_m = report["is"], report["oos"]
    rg = report["rigor"]
    lines = [f"H97 Gate 1 verdict: {report['verdict']}", f"Date: {TODAY}", "",
             f"Net Sharpe (full IS+OOS): {report['full']['sharpe']:.3f}",
             f"IS Sharpe {is_m['sharpe']:.3f} | OOS Sharpe {oos_m['sharpe']:.3f}",
             f"IS MDD {is_m['max_drawdown']:.1%} | OOS MDD {oos_m['max_drawdown']:.1%}",
             f"Win rate IS {is_m['win_rate']:.1%} | OOS {oos_m['win_rate']:.1%}",
             f"Profit factor IS {is_m['profit_factor']:.2f} | OOS {oos_m['profit_factor']:.2f}",
             f"MC p5 Sharpe {rg['mc']['mc_p5_sharpe']:.3f}",
             f"Bootstrap 95% CI Sharpe [{rg['boot']['sharpe_ci_low']:.3f}, {rg['boot']['sharpe_ci_high']:.3f}]",
             f"Permutation p {rg['perm']['permutation_pvalue']:.4f} "
             f"(null mean Sharpe {rg['perm']['null_sharpe_mean']:.3f})",
             f"WF Sharpe std {rg['wf']['wf_sharpe_std']:.3f}, min {rg['wf']['wf_sharpe_min']:.3f}", "",
             "Walk-forward folds:"]
    for f in report["folds"]:
        lines.append(f"  {f['fold']} {f['window']}: Sharpe {f['sharpe']:.3f}, MDD {f['max_drawdown']:.1%}, "
                     f"trades {f['trade_count']}")
    lines += ["", "Stress windows:"]
    for k, m in report["stress"].items():
        lines.append(f"  {k}: MDD {m['max_drawdown']:.1%}, CAGR {m['cagr']:.1%}, trades {m['trade_count']}")
    s = report["stop_effect"]
    lines += ["", f"12% stop effect (IS): with stop Sharpe {s['with_stop']['sharpe']:.3f}, MDD "
              f"{s['with_stop']['max_drawdown']:.1%}; without stop Sharpe {s['no_stop']['sharpe']:.3f}, MDD "
              f"{s['no_stop']['max_drawdown']:.1%}; stop exits {s['with_stop']['stop_exits']}"]
    if report["failures"]:
        lines += ["", "Failures:"] + [f"  - {x}" for x in report["failures"]]
    if report["warnings"]:
        lines += ["", "Warnings:"] + [f"  - {x}" for x in report["warnings"]]
    return "\n".join(lines) + "\n"


def html_report(report: dict) -> str:
    """Minimal standalone HTML report built from the verdict text and fold table."""
    rows = "".join(
        f"<tr><td>{f['fold']}</td><td>{f['window']}</td><td>{f['sharpe']:.3f}</td>"
        f"<td>{f['max_drawdown']:.1%}</td><td>{f['trade_count']}</td></tr>" for f in report["folds"])
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>H97 Gate 1 {TODAY}</title>"
            "<style>body{font-family:sans-serif;max-width:900px;margin:2em auto}"
            "td,th{border:1px solid #ccc;padding:4px 8px}table{border-collapse:collapse}</style></head><body>"
            f"<h1>H97 Gate 1: {report['verdict']}</h1><pre>{html.escape(verdict_text(report))}</pre>"
            "<h2>Walk-forward folds</h2><table><tr><th>Fold</th><th>Window</th><th>Sharpe</th><th>MDD</th>"
            f"<th>Trades</th></tr>{rows}</table></body></html>")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> dict:
    """Run IS/OOS/folds/stress/stop comparison, rigor tests, and write the three output files."""
    log.info("downloading data")
    data = download_data()
    dq = data_quality_report(data)
    log.info("running backtest")
    res = run_backtest(data)
    is_m, oos_m = compute_metrics(res, IS_START, IS_END), compute_metrics(res, OOS_START, OOS_END)
    full = compute_metrics(res, IS_START, OOS_END)
    folds = []
    for i, (a, b) in enumerate(WF_FOLDS, 1):
        m = compute_metrics(res, a, b)
        folds.append({"fold": i, "window": f"{a}..{b}", **m})
    stress = {k: compute_metrics(res, a, b) for k, (a, b) in STRESS_WINDOWS.items()}
    no_stop = run_backtest(data, dict(PARAMETERS, stop_pct=None))
    stop_effect = {"with_stop": is_m, "no_stop": compute_metrics(no_stop, IS_START, IS_END),
                   "oos_with_stop": oos_m, "oos_no_stop": compute_metrics(no_stop, OOS_START, OOS_END)}

    rets_is = res["returns"].loc[IS_START:IS_END].values
    trade_rets = np.array([t["ret"] for t in res["trades"]
                           if not t["refuge"] and IS_START <= t["exit_date"] <= IS_END])
    years = len(rets_is) / TRADING_DAYS_PER_YEAR
    rigor = {
        "mc": monte_carlo_sharpe(trade_rets, years),
        "boot": block_bootstrap_ci(rets_is),
        "perm": permutation_test(data, is_m["sharpe"]),
        "wf": {"wf_sharpe_std": float(np.std([f["sharpe"] for f in folds])),
               "wf_sharpe_min": float(np.min([f["sharpe"] for f in folds]))},
    }
    verdict, failures, warnings = gate1_verdict(is_m, oos_m, folds, rigor)
    report = {"strategy": "H97", "date": TODAY, "parameters": {k: v for k, v in PARAMETERS.items()},
              "verdict": verdict, "failures": failures, "warnings": warnings, "full": full, "is": is_m,
              "oos": oos_m, "folds": folds, "stress": stress, "stop_effect": stop_effect, "rigor": rigor,
              "data_quality": dq, "trades": res["trades"]}
    (OUT_DIR / f"{SLUG}.json").write_text(json.dumps(report, indent=2, default=str))
    (OUT_DIR / f"{SLUG}_verdict.txt").write_text(verdict_text(report))
    (OUT_DIR / f"{SLUG}_report.html").write_text(html_report(report))
    print(verdict_text(report))
    return report


if __name__ == "__main__":
    main()
