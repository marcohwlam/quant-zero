"""
H95 Gate 1 Backtest Runner - Sector ETF Weekly Reversal (long-only, SPY SMA(200) gate)
Parent: QUA-912 (QUA-911)

IS 2000-01-01..2019-12-31, OOS 2020-01-01..2024-12-31, 4 anchored walk-forward folds inside IS.
The strategy has no fitted parameters, so a single continuous simulation is sliced by date.
Runs the base case (2.5 ATR stop) and a no-stop variant; the base case drives the verdict.

Outputs: backtests/h95_<date>.json, h95_<date>_report.html, h95_<date>_verdict.txt
Usage: .venv/bin/python backtests/run_h95_gate1.py [--perms N]
"""

import argparse
import datetime
import html
import json
import sys
import warnings
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents" / "overfit-detector" / "tools"))

from strategies import h95_sector_weekly_reversal as h95  # noqa: E402
from gate1_verdict import BacktestResult, generate_verdict, format_verdict  # noqa: E402
from dsr_calculator import compute_dsr  # noqa: E402

warnings.filterwarnings("ignore")

TODAY = datetime.date.today().isoformat()
IS_START, IS_END = "2000-01-01", "2019-12-31"
OOS_START, OOS_END = "2020-01-01", "2024-12-31"
FOLDS = [("2000-01-01", "2011-12-31", "2012-01-01", "2013-12-31"),
         ("2000-01-01", "2013-12-31", "2014-01-01", "2015-12-31"),
         ("2000-01-01", "2015-12-31", "2016-01-01", "2017-12-31"),
         ("2000-01-01", "2017-12-31", "2018-01-01", "2019-12-31")]
MDD_WARN = -0.15
GATE1_IS_MDD, GATE7_MDD = -0.20, -0.30
SUBPERIODS = {"2000-2002": ("2000-01-01", "2002-12-31"), "2008-2009": ("2008-01-01", "2009-12-31"),
              "2020": ("2020-01-01", "2020-12-31"), "2022": ("2022-01-01", "2022-12-31")}
N_TRIALS = 10  # base + 8 one-at-a-time +/-20% sensitivity variants + no-stop variant


def monte_carlo_sharpe(r: np.ndarray, n: int = 1000, rng=None) -> dict:
    """Bootstrap-resample daily returns i.i.d.; return p5/median/p95 annualized Sharpe."""
    rng = rng or np.random.default_rng(42)
    s = []
    for _ in range(n):
        x = rng.choice(r, size=len(r), replace=True)
        s.append(x.mean() / x.std() * np.sqrt(252) if x.std() > 1e-12 else 0.0)
    return {"mc_p5_sharpe": round(float(np.percentile(s, 5)), 4),
            "mc_median_sharpe": round(float(np.median(s)), 4),
            "mc_p95_sharpe": round(float(np.percentile(s, 95)), 4)}


def block_bootstrap_ci(r: np.ndarray, n: int = 1000, rng=None) -> dict:
    """Block bootstrap (block = sqrt(T)) 95% CI for Sharpe and MDD."""
    rng = rng or np.random.default_rng(43)
    T = len(r)
    bl = max(1, int(np.sqrt(T)))
    sh, dd = [], []
    for _ in range(n):
        starts = rng.integers(0, T - bl + 1, size=T // bl + 1)
        x = np.concatenate([r[s:s + bl] for s in starts])[:T]
        cum = np.cumprod(1 + x)
        dd.append(float(np.min(cum / np.maximum.accumulate(cum) - 1)))
        sh.append(x.mean() / x.std() * np.sqrt(252) if x.std() > 1e-12 else 0.0)
    return {"sharpe_ci_low": round(float(np.percentile(sh, 2.5)), 4),
            "sharpe_ci_high": round(float(np.percentile(sh, 97.5)), 4),
            "mdd_ci_low": round(float(np.percentile(dd, 2.5)), 4),
            "mdd_ci_high": round(float(np.percentile(dd, 97.5)), 4)}


def permutation_test(data: dict, params: dict, observed: float, n_perms: int) -> dict:
    """
    Null: same schedule, gate, sizing, stop and costs, but n_long sectors picked at random each week.
    p = share of null runs with IS Sharpe >= observed (tests the reversal ranking, not the gate).
    """
    null = []
    for k in range(n_perms):
        res = h95.run_backtest(data, params, seed=1000 + k)
        null.append(h95.compute_metrics(res, IS_START, IS_END)["sharpe"])
    null = np.array(null)
    p = float((np.sum(null >= observed) + 1) / (n_perms + 1))
    return {"permutation_pvalue": round(p, 4), "permutation_pass": bool(p <= 0.05), "n_perms": n_perms,
            "null_mean_sharpe": round(float(null.mean()), 4),
            "null_p95_sharpe": round(float(np.percentile(null, 95)), 4)}


def sensitivity(data: dict, params: dict, base_sharpe: float) -> dict:
    """One-at-a-time +/-20% variants of lookback, SMA length and stop multiple; n_long reported separately."""
    variants = {"lookback_days": [4, 6], "trend_sma": [160, 240], "stop_atr_mult": [2.0, 3.0]}
    out, deltas = {}, []
    for k, vals in variants.items():
        for v in vals:
            s = h95.compute_metrics(h95.run_backtest(data, {**params, k: v}), IS_START, IS_END)["sharpe"]
            out[f"{k}={v}"] = s
            if abs(base_sharpe) > 1e-8:
                deltas.append(abs(s - base_sharpe) / abs(base_sharpe))
    for v in (1, 3):
        out[f"n_long={v} (info)"] = h95.compute_metrics(
            h95.run_backtest(data, {**params, "n_long": v}), IS_START, IS_END)["sharpe"]
    mx = float(max(deltas)) if deltas else 1.0
    return {"sharpes": out, "max_delta": round(mx, 4), "passed": bool(mx < 0.30)}


def variant_summary(res: dict) -> dict:
    """IS/OOS/folds/subperiod metrics for one simulation."""
    folds = []
    for tr_s, tr_e, te_s, te_e in FOLDS:
        a, b = h95.compute_metrics(res, tr_s, tr_e), h95.compute_metrics(res, te_s, te_e)
        folds.append({"train": [tr_s, tr_e], "test": [te_s, te_e], "train_sharpe": a["sharpe"],
                      "test_sharpe": b["sharpe"], "train_trades": a["trade_count"], "test_trades": b["trade_count"],
                      "test_mdd": b["max_drawdown"]})
    return {"is": h95.compute_metrics(res, IS_START, IS_END), "oos": h95.compute_metrics(res, OOS_START, OOS_END),
            "folds": folds,
            "subperiods": {k: h95.compute_metrics(res, *v) for k, v in SUBPERIODS.items()}}


def wf_pass(train: float, test: float) -> bool:
    """Window passes when OOS Sharpe degrades < 30% vs IS (or OOS >= IS)."""
    return bool(test >= train or (train > 0 and (train - test) / train < 0.30))


def build_verdict(base: dict, stats: dict, sens: dict, returns_is: np.ndarray) -> tuple:
    """Map results to the overfit-detector BacktestResult and generate the canonical verdict."""
    from scipy.stats import kurtosis, skew
    dsr = compute_dsr(base["is"]["sharpe"], N_TRIALS, len(returns_is), float(skew(returns_is)),
                      float(kurtosis(returns_is)))
    bt = BacktestResult(
        strategy_name="H95_Sector_Weekly_Reversal", test_start=IS_START, test_end=OOS_END,
        is_sharpe=base["is"]["sharpe"], oos_sharpe=base["oos"]["sharpe"],
        is_max_drawdown=abs(base["is"]["max_drawdown"]), oos_max_drawdown=abs(base["oos"]["max_drawdown"]),
        win_rate=base["is"]["win_rate"], trade_count=base["is"]["trade_count"], dsr_zscore=float(dsr.dsr_zscore),
        walk_forward_windows=[(f["train_sharpe"], f["test_sharpe"]) for f in base["folds"]],
        param_sensitivity_passed=sens["passed"], param_sensitivity_max_delta=sens["max_delta"],
        post_cost_sharpe=base["oos"]["sharpe"], look_ahead_bias="none", economic_rationale="valid",
        n_trials=N_TRIALS)
    v = generate_verdict(bt)
    return v, format_verdict(v), dsr


def render_html(summary: dict, verdict_txt: str) -> str:
    """Minimal standalone HTML report."""
    def row(k, v):
        return f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
    parts = [f"<html><head><meta charset='utf-8'><title>H95 Gate 1 {TODAY}</title></head><body>",
             f"<h1>H95 Sector Weekly Reversal - Gate 1 ({TODAY})</h1><pre>{html.escape(verdict_txt)}</pre>"]
    for name in ("base_stop_2.5atr", "no_stop"):
        s = summary["variants"][name]
        parts.append(f"<h2>{name}</h2><table border='1'>")
        parts += [row(f"IS {k}", v) for k, v in s["is"].items()]
        parts += [row(f"OOS {k}", v) for k, v in s["oos"].items()]
        parts.append("</table><h3>Walk-forward folds</h3><table border='1'><tr><th>test</th><th>train Sharpe</th>"
                     "<th>test Sharpe</th><th>train trades</th><th>test trades</th></tr>")
        for f in s["folds"]:
            parts.append(f"<tr><td>{f['test'][0]}..{f['test'][1]}</td><td>{f['train_sharpe']}</td>"
                         f"<td>{f['test_sharpe']}</td><td>{f['train_trades']}</td><td>{f['test_trades']}</td></tr>")
        parts.append("</table>")
    parts.append("<h2>Statistical rigor (base)</h2><table border='1'>")
    parts += [row(k, v) for k, v in summary["stats"].items()]
    parts.append("</table></body></html>")
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--perms", type=int, default=200)
    ap.add_argument("--end", default="2025-01-01")
    args = ap.parse_args()

    params = dict(h95.PARAMETERS)
    data = h95.download_data(params, end=args.end)
    dq = h95.data_quality_report(data, params)

    res_stop = h95.run_backtest(data, params)
    res_nostop = h95.run_backtest(data, {**params, "stop_atr_mult": None})
    variants = {"base_stop_2.5atr": variant_summary(res_stop), "no_stop": variant_summary(res_nostop)}
    base = variants["base_stop_2.5atr"]
    ret_is = res_stop["returns"].loc[IS_START:IS_END].values

    stats = {}
    stats.update(monte_carlo_sharpe(ret_is))
    stats.update(block_bootstrap_ci(ret_is))
    stats.update(permutation_test(data, params, base["is"]["sharpe"], args.perms))
    wf_oos = [f["test_sharpe"] for f in base["folds"]]
    stats["wf_sharpe_std"] = round(float(np.std(wf_oos)), 4)
    stats["wf_sharpe_min"] = round(float(np.min(wf_oos)), 4)
    stats["wf_windows_passed"] = sum(wf_pass(f["train_sharpe"], f["test_sharpe"]) for f in base["folds"])
    sens = sensitivity(data, params, base["is"]["sharpe"])

    verdict, verdict_txt, dsr = build_verdict(base, stats, sens, ret_is)

    mdd_is = base["is"]["max_drawdown"]
    mdd_oos = base["oos"]["max_drawdown"]
    worst_mdd = min(mdd_is, mdd_oos, *[v["max_drawdown"] for v in base["subperiods"].values()])
    flags = {
        "is_mdd_vs_gate1_20pct": "EXCEEDS" if mdd_is < GATE1_IS_MDD else "within",
        "is_mdd_vs_gate7_30pct": "EXCEEDS" if mdd_is < GATE7_MDD else "within",
        "mdd_approaching_15pct": bool(worst_mdd <= MDD_WARN),
        "worst_mdd": worst_mdd,
    }
    summary = {
        "strategy": "H95_Sector_Weekly_Reversal", "date": TODAY, "params": {k: v for k, v in params.items()},
        "periods": {"is": [IS_START, IS_END], "oos": [OOS_START, OOS_END]},
        "variants": variants, "stats": stats, "sensitivity": sens, "dsr": dsr.__dict__,
        "mdd_flags": flags, "data_quality": dq,
        "stop_effect": {"is_sharpe_delta": round(base["is"]["sharpe"] - variants["no_stop"]["is"]["sharpe"], 4),
                        "oos_sharpe_delta": round(base["oos"]["sharpe"] - variants["no_stop"]["oos"]["sharpe"], 4),
                        "is_mdd_delta": round(mdd_is - variants["no_stop"]["is"]["max_drawdown"], 4)},
        "gate1_verdict": verdict.overall_verdict, "trades_sample": res_stop["trades"][:5],
        "liquidity_constrained_trades": sum(t["liquidity_constrained"] for t in res_stop["trades"]),
    }
    out = REPO / "backtests"
    (out / f"h95_{TODAY}.json").write_text(json.dumps(summary, indent=2, default=str))
    extra = (f"\n\nMDD NOTE: IS MDD {mdd_is:.1%} vs Gate 1 limit 20% ({flags['is_mdd_vs_gate1_20pct']}), "
             f"Gate 7 ceiling 30% ({flags['is_mdd_vs_gate7_30pct']}). Worst window MDD {worst_mdd:.1%}"
             f"{' - APPROACHING/EXCEEDING -15%' if flags['mdd_approaching_15pct'] else ''}.\n"
             f"Stop effect (stop minus no-stop): {summary['stop_effect']}\n")
    (out / f"h95_{TODAY}_verdict.txt").write_text(verdict_txt + extra)
    (out / f"h95_{TODAY}_report.html").write_text(render_html(summary, verdict_txt + extra))
    print(json.dumps({k: summary[k] for k in ("gate1_verdict", "mdd_flags", "stop_effect", "stats")}, indent=2))
    for name, v in variants.items():
        print(name, "IS", v["is"], "\n  OOS", v["oos"])
        for f in v["folds"]:
            print("  fold", f["test"], f["train_sharpe"], f["test_sharpe"], f["train_trades"], f["test_trades"])
        print("  sub", {k: (m["sharpe"], m["max_drawdown"]) for k, m in v["subperiods"].items()})
    print("sens", sens)


if __name__ == "__main__":
    main()
