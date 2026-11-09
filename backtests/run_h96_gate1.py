"""
Gate 1 Backtest Runner: H96 Volume Capitulation Reversal on Liquid ETFs (QUA-913, parent QUA-911)
Strategy Coder Agent

Usage:
  python backtests/run_h96_gate1.py --dq-only            # data quality report only, no backtest
  python backtests/run_h96_gate1.py                      # spy_sma, own_sma and none variants
  python backtests/run_h96_gate1.py --variants own_sma

Outputs per variant (variant in spy_sma | own_sma | none | either):
  backtests/h96_<variant>_<date>.json, _report.html, _verdict.txt

IS 2000-2019, OOS 2020-2024. Four walk-forward folds: contiguous 5-year blocks of the IS window
(the rule set has no fitted parameters, so each fold is an independent out-of-time evaluation).
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from strategies.h96_volume_capitulation_reversal_etf import (  # noqa: E402
    PARAMETERS, TRADING_DAYS_PER_YEAR, data_quality_report, download_data, download_vix,
    run_backtest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_START = "1998-06-01"     # warmup for SMA(200)
IS_START, IS_END = "2000-01-01", "2019-12-31"
OOS_START, OOS_END = "2020-01-01", "2024-12-31"
FOLDS = [("2000-01-01", "2004-12-31"), ("2005-01-01", "2009-12-31"),
         ("2010-01-01", "2014-12-31"), ("2015-01-01", "2019-12-31")]
REPORT_DATE = date.today().isoformat()
OUTPUT_DIR = REPO_ROOT / "backtests"

# Gate 1 thresholds (criteria.md Track A and QUA-913 issue)
GATE_IS_SHARPE = 1.0
GATE_OOS_SHARPE = 0.7
GATE_MDD = -0.15
GATE_MIN_TRADES = 100         # issue-level floor; criteria.md Track A floor is 30 per walk-forward window
GATE_FOLD_MIN_TRADES = 30
MDD_WARN = -0.12              # flag when drawdown approaches the -15% limit
N_RESAMPLES = 2000
BLOCK = 21
SEED = 42

SENSITIVITY_GRID = {"drop_atr_mult": [1.0, 1.5, 2.0], "vol_mult": [1.5, 2.0, 3.0]}


# ── Statistics ────────────────────────────────────────────────────────────────

def _sharpe(r: np.ndarray) -> float:
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR)) if sd > 0 else 0.0


def monte_carlo_sharpe(returns: pd.Series, n: int = N_RESAMPLES, seed: int = SEED) -> dict:
    """IID resample of daily returns with replacement; percentiles of the resampled Sharpe."""
    r = returns.dropna().to_numpy()
    if len(r) < 2:
        return {"p5": 0.0, "p50": 0.0, "p95": 0.0}
    rng = np.random.default_rng(seed)
    s = np.array([_sharpe(rng.choice(r, size=len(r), replace=True)) for _ in range(n)])
    return {"p5": float(np.percentile(s, 5)), "p50": float(np.percentile(s, 50)), "p95": float(np.percentile(s, 95))}


def bootstrap_sharpe_ci(returns: pd.Series, n: int = N_RESAMPLES, block: int = BLOCK, seed: int = SEED) -> dict:
    """Moving-block bootstrap (block=21 days) 95% CI of the Sharpe ratio."""
    r = returns.dropna().to_numpy()
    if len(r) < 2 * block:
        return {"lo": 0.0, "hi": 0.0}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(len(r) / block))
    starts_max = len(r) - block
    s = np.empty(n)
    for k in range(n):
        st = rng.integers(0, starts_max + 1, size=n_blocks)
        s[k] = _sharpe(np.concatenate([r[i:i + block] for i in st])[:len(r)])
    return {"lo": float(np.percentile(s, 2.5)), "hi": float(np.percentile(s, 97.5))}


def permutation_p(trades: pd.DataFrame, n: int = N_RESAMPLES, seed: int = SEED) -> float:
    """
    Sign-flip permutation test on net trade returns. H0: trade returns are symmetric around zero.
    p = share of random sign assignments whose mean is >= the observed mean.
    """
    if trades.empty:
        return 1.0
    x = trades["ret_net"].to_numpy()
    obs = x.mean()
    rng = np.random.default_rng(seed)
    flips = rng.choice([-1.0, 1.0], size=(n, len(x)))
    return float(((flips * np.abs(x)).mean(axis=1) >= obs).mean())


# ── Backtest pieces ───────────────────────────────────────────────────────────

def walk_forward(data: dict, params: dict, vix: pd.Series) -> list:
    """Run each fold; report Sharpe, MDD, trades and distinct signal days per fold."""
    out = []
    for a, b in FOLDS:
        res = run_backtest(data, params, a, b, vix)
        m = res["metrics"]
        out.append({"start": a, "end": b, "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"],
                    "trades": m["trade_count"], "distinct_signal_days": res["signal_counts"]["distinct_days"],
                    "years_with_zero_events": res["signal_counts"]["years_with_zero_events"]})
    return out


def sensitivity(data: dict, params: dict, vix: pd.Series) -> dict:
    """IS-only grid over drop_atr_mult and vol_mult. Reports Sharpe range and worst delta to the base case."""
    rows = []
    for d in SENSITIVITY_GRID["drop_atr_mult"]:
        for v in SENSITIVITY_GRID["vol_mult"]:
            p = {**params, "drop_atr_mult": d, "vol_mult": v}
            m = run_backtest(data, p, IS_START, IS_END, vix)["metrics"]
            rows.append({"drop_atr_mult": d, "vol_mult": v, "sharpe": m["sharpe"], "trades": m["trade_count"]})
    base = next(r["sharpe"] for r in rows if r["drop_atr_mult"] == params["drop_atr_mult"]
                and r["vol_mult"] == params["vol_mult"])
    return {"grid": rows, "base_sharpe": base, "max_abs_delta": max(abs(r["sharpe"] - base) for r in rows)}


def evaluate_variant(data: dict, vix: pd.Series, variant: str) -> dict:
    """Full Gate 1 evaluation for one trend-gate variant."""
    params = {**PARAMETERS, "trend_gate": variant}
    is_res = run_backtest(data, params, IS_START, IS_END, vix)
    oos_res = run_backtest(data, params, OOS_START, OOS_END, vix)
    full_r = pd.concat([is_res["returns"], oos_res["returns"]])
    folds = walk_forward(data, params, vix)
    fold_sharpes = [f["sharpe"] for f in folds]
    is_m, oos_m = is_res["metrics"], oos_res["metrics"]

    flags = []
    if is_m["trade_count"] < GATE_MIN_TRADES:
        flags.append(f"IS trade count {is_m['trade_count']} < {GATE_MIN_TRADES} (issue floor)")
    for f in folds:
        if f["trades"] < GATE_FOLD_MIN_TRADES:
            flags.append(f"fold {f['start'][:4]}-{f['end'][:4]} trades {f['trades']} < {GATE_FOLD_MIN_TRADES}")
    for name, m in (("IS", is_m), ("OOS", oos_m)):
        if m["max_drawdown"] <= MDD_WARN:
            flags.append(f"{name} MDD {m['max_drawdown'] * 100:.1f}% approaching -15% limit")
    n_liq = is_res["liquidity_flags"] + oos_res["liquidity_flags"]
    if n_liq:
        flags.append(f"{n_liq} entries with Q/ADV > 1% (liquidity-constrained)")
    zero_years = is_res["signal_counts"]["years_with_zero_events"]
    if zero_years:
        flags.append(f"IS years with zero events: {zero_years}")

    criteria = {
        "IS_Sharpe": (is_m["sharpe"], f"> {GATE_IS_SHARPE}", is_m["sharpe"] > GATE_IS_SHARPE),
        "OOS_Sharpe": (oos_m["sharpe"], f"> {GATE_OOS_SHARPE}", oos_m["sharpe"] > GATE_OOS_SHARPE),
        "IS_MDD": (is_m["max_drawdown"], f"> {GATE_MDD}", is_m["max_drawdown"] > GATE_MDD),
        "OOS_MDD": (oos_m["max_drawdown"], f"> {GATE_MDD}", oos_m["max_drawdown"] > GATE_MDD),
        "IS_TradeCount": (is_m["trade_count"], f">= {GATE_MIN_TRADES}", is_m["trade_count"] >= GATE_MIN_TRADES),
        "Fold_MinTrades": (min(f["trades"] for f in folds), f">= {GATE_FOLD_MIN_TRADES}",
                           min(f["trades"] for f in folds) >= GATE_FOLD_MIN_TRADES),
    }
    crit = {k: {"value": float(v), "threshold": t, "pass": bool(p)} for k, (v, t, p) in criteria.items()}

    all_trades = pd.concat([is_res["trades"], oos_res["trades"]], ignore_index=True)
    return {
        "variant": variant,
        "params": {k: v for k, v in params.items()},
        "is_metrics": is_m, "oos_metrics": oos_m,
        "net_sharpe_full": float(_sharpe(full_r.dropna().to_numpy())),
        "is_signal_counts": is_res["signal_counts"], "oos_signal_counts": oos_res["signal_counts"],
        "walk_forward": {"folds": folds, "sharpe_variance": float(np.var(fold_sharpes, ddof=1)),
                         "sharpe_std": float(np.std(fold_sharpes, ddof=1))},
        "monte_carlo_sharpe": monte_carlo_sharpe(full_r),
        "bootstrap_sharpe_ci95": bootstrap_sharpe_ci(full_r),
        "permutation_p": permutation_p(all_trades),
        "sensitivity": sensitivity(data, params, vix),
        "exit_reasons": all_trades["reason"].value_counts().to_dict() if not all_trades.empty else {},
        "liquidity_flags": n_liq,
        "criteria": crit,
        "verdict": "PASS" if all(c["pass"] for c in crit.values()) else "FAIL",
        "flags": flags,
        "_trades": all_trades,
    }


# ── Reports ───────────────────────────────────────────────────────────────────

def verdict_text(r: dict) -> str:
    """Plain-text verdict."""
    i, o = r["is_metrics"], r["oos_metrics"]
    lines = [f"GATE 1 VERDICT: H96 Volume Capitulation Reversal ({r['variant']} gate)",
             f"Report date: {REPORT_DATE}", f"OVERALL: {r['verdict']}", ""]
    lines += [f"  [{'PASS' if c['pass'] else 'FAIL'}] {k}: {c['value']:.4f} (threshold {c['threshold']})"
              for k, c in r["criteria"].items()]
    lines += ["", f"IS  2000-2019: Sharpe {i['sharpe']:.3f} MDD {i['max_drawdown'] * 100:.2f}% "
              f"win {i['win_rate'] * 100:.1f}% PF {i['profit_factor']:.2f} trades {i['trade_count']}",
              f"OOS 2020-2024: Sharpe {o['sharpe']:.3f} MDD {o['max_drawdown'] * 100:.2f}% "
              f"win {o['win_rate'] * 100:.1f}% PF {o['profit_factor']:.2f} trades {o['trade_count']}",
              f"Net Sharpe (IS+OOS): {r['net_sharpe_full']:.3f}",
              f"MC p5 Sharpe: {r['monte_carlo_sharpe']['p5']:.3f}",
              f"Bootstrap 95% CI: [{r['bootstrap_sharpe_ci95']['lo']:.3f}, {r['bootstrap_sharpe_ci95']['hi']:.3f}]",
              f"Permutation p: {r['permutation_p']:.4f}",
              f"IS events {r['is_signal_counts']['events']}, distinct days {r['is_signal_counts']['distinct_days']}",
              f"WF Sharpe variance: {r['walk_forward']['sharpe_variance']:.4f}", "Per-fold:"]
    lines += [f"  {f['start'][:4]}-{f['end'][:4]}: Sharpe {f['sharpe']:.3f} trades {f['trades']} "
              f"distinct days {f['distinct_signal_days']} MDD {f['max_drawdown'] * 100:.2f}%"
              for f in r["walk_forward"]["folds"]]
    lines += ["", "FLAGS:"] + [f"  - {x}" for x in r["flags"]] if r["flags"] else ["", "FLAGS: none"]
    lines += ["", "Cost model: $0.005/share, slippage 0.005% (SPY/QQQ/IWM) else 0.05%, impact 0.1*sigma*sqrt(Q/ADV)",
              "Data: yfinance auto_adjust=True daily OHLCV"]
    return "\n".join(lines)


def html_report(r: dict) -> str:
    """Minimal HTML report."""
    rows = "".join(f"<tr><td>{k}</td><td>{c['value']:.4f}</td><td>{c['threshold']}</td>"
                   f"<td>{'PASS' if c['pass'] else 'FAIL'}</td></tr>" for k, c in r["criteria"].items())
    fold_rows = "".join(f"<tr><td>{f['start'][:4]}-{f['end'][:4]}</td><td>{f['sharpe']:.3f}</td><td>{f['trades']}</td>"
                        f"<td>{f['distinct_signal_days']}</td><td>{f['max_drawdown'] * 100:.2f}%</td></tr>"
                        for f in r["walk_forward"]["folds"])
    flags = "".join(f"<li>{x}</li>" for x in r["flags"]) or "<li>none</li>"
    pre = verdict_text(r).replace("&", "&amp;").replace("<", "&lt;")
    return (f"<!DOCTYPE html><html><head><title>H96 {r['variant']} Gate 1</title></head><body>"
            f"<h1>H96 Gate 1 ({r['variant']} gate): {r['verdict']}</h1>"
            f"<table border=1><tr><th>Criterion</th><th>Value</th><th>Threshold</th><th>Status</th></tr>{rows}</table>"
            f"<h2>Walk-forward folds</h2><table border=1><tr><th>Fold</th><th>Sharpe</th><th>Trades</th>"
            f"<th>Distinct signal days</th><th>MDD</th></tr>{fold_rows}</table>"
            f"<h2>Flags</h2><ul>{flags}</ul><h2>Verdict text</h2><pre>{pre}</pre></body></html>")


def save(r: dict) -> list:
    """Write json, verdict txt and html for one variant. Returns paths."""
    base = OUTPUT_DIR / f"h96_{r['variant']}_{REPORT_DATE}"
    trades = r.pop("_trades")
    payload = {**r, "is_window": [IS_START, IS_END], "oos_window": [OOS_START, OOS_END],
               "trade_count_total": int(len(trades))}
    paths = [Path(f"{base}.json"), Path(f"{base}_verdict.txt"), Path(f"{base}_report.html")]
    paths[0].write_text(json.dumps(payload, indent=2, default=float))
    paths[1].write_text(verdict_text(r))
    paths[2].write_text(html_report(r))
    if not trades.empty:
        trades.to_csv(f"{base}_trades.csv", index=False)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dq-only", action="store_true", help="print the data quality report and exit")
    ap.add_argument("--variants", nargs="+", default=["spy_sma", "own_sma", "none"])
    args = ap.parse_args()

    data = download_data(PARAMETERS["universe"], DATA_START, "2025-01-01")
    if args.dq_only:
        print(json.dumps(data_quality_report(data), indent=1))
        return
    vix = download_vix(DATA_START, "2025-01-01")
    for v in args.variants:
        logger.info("variant %s", v)
        r = evaluate_variant(data, vix, v)
        print(verdict_text(r))
        logger.info("wrote %s", save(r))


if __name__ == "__main__":
    main()
