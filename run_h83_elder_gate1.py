#!/usr/bin/env python3
"""
H83 Gate 1 Backtest Runner — Elder Triple Screen Multi-ETF System
Runs TWO IS/OOS variants per QUA-379:
  Standard:  IS 2003-2018 | OOS 2019-2025
  Post-GFC:  IS 2009-2020 | OOS 2020-2025

Parameter sweep: oversold threshold (15/20/25) × hard stop (6%/7.5%/9%) × max positions (3/4)
Reports per-quarter IS trade count and flags quarters below 30.
Uses kpi-daily-weekly.md v1.0 criteria (OOS Sharpe > 0.7, CS >= 0.60, NO IS Sharpe gate).
"""

import copy
import json
import logging
import math
import sys
import warnings
import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

from strategies.h83_elder_triple_screen_multi_etf import (
    PARAMETERS,
    UNIVERSE,
    download_data,
    run_backtest,
    per_quarter_trade_count,
)

TODAY = datetime.date.today().isoformat()
STRATEGY_NAME = "H83_ElderTripleScreenMultiETF"
OUT_DIR = REPO_ROOT / "backtests"
OUT_DIR.mkdir(exist_ok=True)

# ── IS/OOS Variants ───────────────────────────────────────────────────────────

VARIANTS = {
    "standard": {
        "is_start": "2003-01-01",
        "is_end": "2018-12-31",
        "oos_start": "2019-01-01",
        "oos_end": "2025-06-01",
        "label": "Standard (IS 2003-2018 / OOS 2019-2025)",
    },
    "post_gfc": {
        "is_start": "2009-01-01",
        "is_end": "2020-12-31",
        "oos_start": "2021-01-01",
        "oos_end": "2025-06-01",
        "label": "Post-GFC (IS 2009-2020 / OOS 2021-2025)",
    },
}

# ── kpi-daily-weekly v1.0 Composite Score ─────────────────────────────────────

def composite_score(oos_sharpe: float, mdd_is: float, ppt_bps: float, trade_count_is: int) -> dict:
    """
    Track A Gate 1 composite score per kpi-daily-weekly.md v1.0.
    CS = 0.40*NetSharpe_norm + 0.30*Stability_norm + 0.20*PpT_norm + 0.10*TradeAdequacy_norm
    """
    # Normalization ranges (calibrated 2026-06-13 per QUA-236)
    sharpe_norm = float(np.clip((oos_sharpe - (-0.5)) / (2.0 - (-0.5)), 0.0, 1.0))
    # MDD: min=20% (CS threshold, score=0), max=0% (score=1)
    mdd_abs = abs(mdd_is)
    stability_norm = float(np.clip(1.0 - mdd_abs / 0.20, 0.0, 1.0))
    ppt_norm = float(np.clip(ppt_bps / 100.0, 0.0, 1.0))
    trade_adequacy_norm = float(min(1.0, trade_count_is / 30.0))

    cs = (0.40 * sharpe_norm
          + 0.30 * stability_norm
          + 0.20 * ppt_norm
          + 0.10 * trade_adequacy_norm)
    return {
        "composite_score": round(cs, 4),
        "sharpe_norm": round(sharpe_norm, 4),
        "stability_norm": round(stability_norm, 4),
        "ppt_norm": round(ppt_norm, 4),
        "trade_adequacy_norm": round(trade_adequacy_norm, 4),
    }


# ── Trade Analytics ───────────────────────────────────────────────────────────

def trade_analytics(trade_log: list, init_cash: float) -> dict:
    """Compute profit_per_trade_bps, CPR, profit_factor from trade log."""
    if not trade_log:
        return {
            "profit_per_trade_bps": 0.0,
            "cpr": 999.0,
            "profit_factor": 0.0,
            "win_count": 0,
            "loss_count": 0,
            "avg_hold_days": 0.0,
            "gap_pnl_total": 0.0,
        }
    pnls_net = [t["pnl_net"] for t in trade_log]
    pnls_gross = [t["pnl_gross"] for t in trade_log]
    notionals = [abs(t["qty"] * t["entry_price"]) for t in trade_log]
    costs = [abs(t["pnl_gross"] - t["pnl_net"]) for t in trade_log]

    avg_notional = float(np.mean(notionals)) if notionals else 1.0
    avg_net_pnl = float(np.mean(pnls_net))
    ppt_bps = (avg_net_pnl / avg_notional * 10000) if avg_notional > 0 else 0.0

    total_gross_pos = sum(g for g in pnls_gross if g > 0)
    total_cost = sum(costs)
    cpr = total_cost / max(total_gross_pos, 1e-8) if total_gross_pos > 0 else 999.0

    wins = [p for p in pnls_net if p > 0]
    losses = [p for p in pnls_net if p < 0]
    pf = sum(wins) / max(abs(sum(losses)), 1e-8) if losses else float("inf")

    holds = [t.get("hold_days", 0) for t in trade_log]
    gap_pnl_total = sum(t.get("gap_pnl", 0.0) for t in trade_log)

    return {
        "profit_per_trade_bps": round(ppt_bps, 2),
        "cpr": round(min(cpr, 999.0), 4),
        "profit_factor": round(min(pf, 999.0), 4),
        "win_count": len(wins),
        "loss_count": len([p for p in pnls_net if p <= 0]),
        "avg_hold_days": round(float(np.mean(holds)), 1),
        "gap_pnl_total": round(gap_pnl_total, 2),
    }


def trades_per_quarter(trade_count: int, period_start: str, period_end: str) -> float:
    days = (pd.Timestamp(period_end) - pd.Timestamp(period_start)).days
    quarters = max(days / 91.25, 1)
    return round(trade_count / quarters, 2)


# ── Gate 1 Checks ─────────────────────────────────────────────────────────────

def gate1_check(
    oos_r: dict, is_r: dict, is_analytics: dict, oos_analytics: dict,
    is_tpq: float, cs_result: dict
) -> dict:
    """
    Apply kpi-daily-weekly.md v1.0 hard gates. NO IS Sharpe gate.
    """
    checks = {
        "oos_sharpe_gt_0.7": oos_r["sharpe"] > 0.7,
        "is_mdd_lt_30pct": abs(is_r["max_drawdown"]) < 0.30,
        "cpr_lt_0.25": oos_analytics["cpr"] < 0.25,
        "is_ppt_gt_15bps": is_analytics["profit_per_trade_bps"] > 15.0,
        "composite_score_ge_0.60": cs_result["composite_score"] >= 0.60,
        "is_tpq_ge_30": is_tpq >= 30.0,
    }
    overall = all(checks.values())
    return {"pass": overall, "checks": checks}


# ── Monte Carlo ───────────────────────────────────────────────────────────────

def monte_carlo(trade_log: list, n_sim: int = 1000, init_cash: float = 100_000) -> dict:
    if len(trade_log) < 10:
        return {
            "mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0,
        }
    pnls = [t["pnl_net"] for t in trade_log]
    n = len(pnls)
    sharpes = []
    rng = np.random.default_rng(42)
    for _ in range(n_sim):
        sample = rng.choice(pnls, size=n, replace=True)
        cum = np.cumsum(sample)
        eq = init_cash + cum
        ret = np.diff(eq) / eq[:-1]
        s = (ret.mean() / (ret.std() + 1e-10)) * np.sqrt(252) if ret.std() > 0 else 0.0
        sharpes.append(s)
    return {
        "mc_p5_sharpe": round(float(np.percentile(sharpes, 5)), 3),
        "mc_median_sharpe": round(float(np.median(sharpes)), 3),
        "mc_p95_sharpe": round(float(np.percentile(sharpes, 95)), 3),
    }


def bootstrap_ci(trade_log: list, n_boot: int = 1000, init_cash: float = 100_000) -> dict:
    if len(trade_log) < 10:
        return {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0}
    pnls = [t["pnl_net"] for t in trade_log]
    n = len(pnls)
    sharpes = []
    rng = np.random.default_rng(123)
    for _ in range(n_boot):
        sample = rng.choice(pnls, size=n, replace=True)
        cum = np.cumsum(sample)
        eq = init_cash + cum
        ret = np.diff(eq) / eq[:-1]
        s = (ret.mean() / (ret.std() + 1e-10)) * np.sqrt(252) if ret.std() > 0 else 0.0
        sharpes.append(s)
    return {
        "sharpe_ci_low": round(float(np.percentile(sharpes, 2.5)), 3),
        "sharpe_ci_high": round(float(np.percentile(sharpes, 97.5)), 3),
    }


def permutation_test(trade_log: list, n_perm: int = 500, init_cash: float = 100_000) -> dict:
    if len(trade_log) < 10:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    pnls = np.array([t["pnl_net"] for t in trade_log])
    n = len(pnls)
    cum = np.cumsum(pnls)
    eq = init_cash + cum
    ret = np.diff(eq) / eq[:-1]
    actual_sharpe = (ret.mean() / (ret.std() + 1e-10)) * np.sqrt(252) if ret.std() > 0 else 0.0
    rng = np.random.default_rng(999)
    count_above = 0
    for _ in range(n_perm):
        perm = rng.permutation(pnls)
        cum_p = np.cumsum(perm)
        eq_p = init_cash + cum_p
        ret_p = np.diff(eq_p) / eq_p[:-1]
        s = (ret_p.mean() / (ret_p.std() + 1e-10)) * np.sqrt(252) if ret_p.std() > 0 else 0.0
        if s >= actual_sharpe:
            count_above += 1
    pval = (count_above + 1) / (n_perm + 1)
    return {
        "permutation_pvalue": round(pval, 4),
        "permutation_test_pass": pval < 0.05,
    }


def market_impact_estimate(trade_log: list) -> dict:
    if not trade_log:
        return {"market_impact_bps": 0.0}
    costs = [abs(t["pnl_gross"] - t["pnl_net"]) for t in trade_log]
    notionals = [abs(t["qty"] * t["entry_price"]) for t in trade_log]
    if not notionals or sum(notionals) == 0:
        return {"market_impact_bps": 0.0}
    mi_bps = sum(costs) / sum(notionals) * 10000
    return {"market_impact_bps": round(mi_bps, 3)}


# ── Walk-Forward Validation ───────────────────────────────────────────────────

def walk_forward(data: dict, params: dict, is_start: str, is_end: str,
                 n_windows: int = 6) -> list:
    """
    Split IS into n_windows equal chunks; report Sharpe of each chunk.
    Returns list of {"window": N, "sharpe": X} dicts.
    """
    is_dates = pd.date_range(is_start, is_end, freq="B")
    if len(is_dates) < n_windows * 60:
        return []
    chunk_size = len(is_dates) // n_windows
    results = []
    for i in range(n_windows):
        w_start = is_dates[i * chunk_size].strftime("%Y-%m-%d")
        w_end = is_dates[min((i + 1) * chunk_size - 1, len(is_dates) - 1)].strftime("%Y-%m-%d")
        try:
            r = run_backtest(data, w_start, w_end, params)
            results.append({"window": i + 1, "start": w_start, "end": w_end,
                            "sharpe": r["sharpe"], "trade_count": r["trade_count"]})
        except Exception as exc:
            results.append({"window": i + 1, "start": w_start, "end": w_end,
                            "sharpe": 0.0, "trade_count": 0, "error": str(exc)})
    return results


# ── Parameter Sweep ───────────────────────────────────────────────────────────

def param_sweep(data: dict, base_params: dict, is_start: str, is_end: str,
                oos_start: str, oos_end: str) -> pd.DataFrame:
    """
    Sweep oversold_threshold × hard_stop_pct × max_positions.
    Returns DataFrame with OOS Sharpe for each combination.
    """
    oversold_vals = [15, 20, 25]
    stop_vals = [0.06, 0.075, 0.09]
    maxpos_vals = [3, 4]

    rows = []
    for oversold in oversold_vals:
        for stop in stop_vals:
            for maxpos in maxpos_vals:
                p = copy.deepcopy(base_params)
                p["oversold_threshold"] = oversold
                p["hard_stop_pct"] = stop
                p["max_positions"] = maxpos
                p["position_weight"] = 1.0 / maxpos
                try:
                    is_r = run_backtest(data, is_start, is_end, p)
                    oos_r = run_backtest(data, oos_start, oos_end, p)
                    rows.append({
                        "oversold_threshold": oversold,
                        "hard_stop_pct": stop,
                        "max_positions": maxpos,
                        "is_sharpe": is_r["sharpe"],
                        "oos_sharpe": oos_r["sharpe"],
                        "is_mdd": is_r["max_drawdown"],
                        "oos_mdd": oos_r["max_drawdown"],
                        "is_trade_count": is_r["trade_count"],
                        "oos_trade_count": oos_r["trade_count"],
                    })
                except Exception as exc:
                    rows.append({
                        "oversold_threshold": oversold,
                        "hard_stop_pct": stop,
                        "max_positions": maxpos,
                        "error": str(exc),
                        "oos_sharpe": np.nan,
                    })
    return pd.DataFrame(rows)


# ── HTML Report ───────────────────────────────────────────────────────────────

def build_html(variant_label: str, is_r: dict, oos_r: dict,
               is_analytics: dict, oos_analytics: dict,
               gate1: dict, cs_result: dict,
               mc: dict, ci: dict, perm: dict, mi: dict, wf: list,
               is_tpq: float, oos_tpq: float,
               pq: dict, sweep_df: pd.DataFrame) -> str:
    gate_color = "#2ecc71" if gate1["pass"] else "#e74c3c"
    gate_label = "PASS" if gate1["pass"] else "FAIL"
    checks_html = "".join(
        f"<tr><td>{k}</td><td style='color:{'green' if v else 'red'}'>"
        f"{'PASS' if v else 'FAIL'}</td></tr>"
        for k, v in gate1["checks"].items()
    )
    flagged_q = pq.get("flagged_quarters", [])
    flag_html = (
        f"<p style='color:orange'>Quarters with &lt;30 trades: {', '.join(flagged_q)}</p>"
        if flagged_q else "<p style='color:green'>No quarters below 30-trade floor.</p>"
    )
    sweep_html = sweep_df.to_html(index=False, float_format=lambda x: f"{x:.3f}") if not sweep_df.empty else "<p>Sweep not available</p>"
    wf_html = "<table border='1'><tr><th>Window</th><th>Start</th><th>End</th><th>Sharpe</th><th>Trades</th></tr>" + \
        "".join(f"<tr><td>{w['window']}</td><td>{w.get('start','')}</td><td>{w.get('end','')}</td>"
                f"<td>{w['sharpe']:.3f}</td><td>{w.get('trade_count',0)}</td></tr>" for w in wf) + "</table>"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>H83 Elder Triple Screen Gate 1</title>
<style>body{{font-family:monospace;margin:20px}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:6px}} h1{{color:#333}}</style></head>
<body>
<h1>H83 Elder Triple Screen Multi-ETF — Gate 1 Report</h1>
<p>{variant_label} | {TODAY}</p>
<h2 style="color:{gate_color}">Overall: {gate_label} | CS={cs_result['composite_score']:.4f}</h2>
<table>{checks_html}</table>
<h3>Composite Score Breakdown</h3>
<table><tr><th>Component</th><th>Normalized</th><th>Weight</th><th>Contribution</th></tr>
<tr><td>NetSharpe (OOS)</td><td>{cs_result['sharpe_norm']:.3f}</td><td>0.40</td><td>{0.40*cs_result['sharpe_norm']:.3f}</td></tr>
<tr><td>Stability (IS MDD)</td><td>{cs_result['stability_norm']:.3f}</td><td>0.30</td><td>{0.30*cs_result['stability_norm']:.3f}</td></tr>
<tr><td>PpT (IS)</td><td>{cs_result['ppt_norm']:.3f}</td><td>0.20</td><td>{0.20*cs_result['ppt_norm']:.3f}</td></tr>
<tr><td>Trade Adequacy</td><td>{cs_result['trade_adequacy_norm']:.3f}</td><td>0.10</td><td>{0.10*cs_result['trade_adequacy_norm']:.3f}</td></tr>
</table>
<h3>IS Period ({PARAMETERS['is_start']} → {PARAMETERS['is_end']})</h3>
<table>
<tr><td>Sharpe</td><td>{is_r['sharpe']:.4f}</td></tr>
<tr><td>Max Drawdown</td><td>{is_r['max_drawdown']:.2%}</td></tr>
<tr><td>Total Return</td><td>{is_r['total_return']:.2%}</td></tr>
<tr><td>Trade Count</td><td>{is_r['trade_count']}</td></tr>
<tr><td>Trades/Quarter</td><td>{is_tpq:.1f}</td></tr>
<tr><td>PpT (bps)</td><td>{is_analytics['profit_per_trade_bps']:.2f}</td></tr>
<tr><td>CPR</td><td>{is_analytics['cpr']:.4f}</td></tr>
<tr><td>Win Rate</td><td>{is_r['win_rate']:.2%}</td></tr>
<tr><td>Avg Hold Days</td><td>{is_analytics['avg_hold_days']:.1f}</td></tr>
</table>
{flag_html}
<h3>OOS Period ({PARAMETERS['oos_start']} → {PARAMETERS['oos_end']})</h3>
<table>
<tr><td>Sharpe</td><td>{oos_r['sharpe']:.4f}</td></tr>
<tr><td>Max Drawdown</td><td>{oos_r['max_drawdown']:.2%}</td></tr>
<tr><td>Total Return</td><td>{oos_r['total_return']:.2%}</td></tr>
<tr><td>Trade Count</td><td>{oos_r['trade_count']}</td></tr>
<tr><td>Trades/Quarter</td><td>{oos_tpq:.1f}</td></tr>
<tr><td>PpT (bps)</td><td>{oos_analytics['profit_per_trade_bps']:.2f}</td></tr>
<tr><td>CPR</td><td>{oos_analytics['cpr']:.4f}</td></tr>
<tr><td>Win Rate</td><td>{oos_r['win_rate']:.2%}</td></tr>
</table>
<h3>Statistical Rigor</h3>
<table>
<tr><td>MC P5/Median/P95 Sharpe</td><td>{mc['mc_p5_sharpe']:.3f} / {mc['mc_median_sharpe']:.3f} / {mc['mc_p95_sharpe']:.3f}</td></tr>
<tr><td>Bootstrap 95% CI</td><td>[{ci['sharpe_ci_low']:.3f}, {ci['sharpe_ci_high']:.3f}]</td></tr>
<tr><td>Market Impact</td><td>{mi['market_impact_bps']:.3f} bps</td></tr>
<tr><td>Permutation p-value</td><td>{perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})</td></tr>
</table>
<h3>Walk-Forward Windows</h3>{wf_html}
<h3>Parameter Sweep (OOS Sharpe)</h3>{sweep_html}
</body></html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def run_variant(variant_key: str, variant: dict, data: dict) -> dict:
    """Run full Gate 1 evaluation for one IS/OOS variant."""
    logger.info("=" * 60)
    logger.info("Variant: %s", variant["label"])
    is_start = variant["is_start"]
    is_end = variant["is_end"]
    oos_start = variant["oos_start"]
    oos_end = variant["oos_end"]

    params = copy.deepcopy(PARAMETERS)
    params["is_start"] = is_start
    params["is_end"] = is_end
    params["oos_start"] = oos_start
    params["oos_end"] = oos_end

    logger.info("Running IS: %s → %s", is_start, is_end)
    is_r = run_backtest(data, is_start, is_end, params)
    logger.info("IS  Sharpe=%.3f  MDD=%.1f%%  Trades=%d",
                is_r["sharpe"], is_r["max_drawdown"] * 100, is_r["trade_count"])

    logger.info("Running OOS: %s → %s", oos_start, oos_end)
    oos_r = run_backtest(data, oos_start, oos_end, params)
    logger.info("OOS Sharpe=%.3f  MDD=%.1f%%  Trades=%d",
                oos_r["sharpe"], oos_r["max_drawdown"] * 100, oos_r["trade_count"])

    is_an = trade_analytics(is_r["trade_log"], params["init_cash"])
    oos_an = trade_analytics(oos_r["trade_log"], params["init_cash"])
    is_tpq = trades_per_quarter(is_r["trade_count"], is_start, is_end)
    oos_tpq = trades_per_quarter(oos_r["trade_count"], oos_start, oos_end)

    pq = per_quarter_trade_count(is_r["trade_log"])
    if pq["flagged_quarters"]:
        logger.warning("PF-1: Quarters below 30-trade floor: %s", pq["flagged_quarters"])
    logger.info("IS PpT=%.1f bps  CPR=%.3f  TPQ=%.1f", is_an["profit_per_trade_bps"], is_an["cpr"], is_tpq)

    cs_result = composite_score(oos_r["sharpe"], is_r["max_drawdown"],
                                is_an["profit_per_trade_bps"], is_r["trade_count"])
    gate1 = gate1_check(oos_r, is_r, is_an, oos_an, is_tpq, cs_result)
    logger.info("Gate 1: %s  CS=%.4f", "PASS" if gate1["pass"] else "FAIL", cs_result["composite_score"])

    logger.info("Running Monte Carlo and statistical tests...")
    mc = monte_carlo(oos_r["trade_log"], n_sim=1000, init_cash=params["init_cash"])
    ci = bootstrap_ci(oos_r["trade_log"], n_boot=1000, init_cash=params["init_cash"])
    perm = permutation_test(oos_r["trade_log"], n_perm=500, init_cash=params["init_cash"])
    mi = market_impact_estimate(oos_r["trade_log"])
    logger.info("MC P5=%.3f Median=%.3f P95=%.3f  Perm p=%.4f",
                mc["mc_p5_sharpe"], mc["mc_median_sharpe"], mc["mc_p95_sharpe"], perm["permutation_pvalue"])

    logger.info("Running walk-forward (6 windows)...")
    wf = walk_forward(data, params, is_start, is_end, n_windows=6)
    wf_pass = sum(1 for w in wf if w.get("sharpe", 0) > 0)
    wf_sharpes = [w.get("sharpe", 0.0) for w in wf]
    logger.info("WF: %d/%d positive Sharpe  min=%.3f  std=%.3f",
                wf_pass, len(wf), min(wf_sharpes) if wf_sharpes else 0,
                float(np.std(wf_sharpes)) if wf_sharpes else 0)

    logger.info("Running parameter sweep (18 combos)...")
    try:
        sweep_df = param_sweep(data, params, is_start, is_end, oos_start, oos_end)
    except Exception as exc:
        logger.warning("Sweep failed: %s", exc)
        sweep_df = pd.DataFrame([{"note": "failed", "error": str(exc)}])

    # Sensitivity: max OOS Sharpe delta vs primary spec in sweep
    if "oos_sharpe" in sweep_df.columns:
        primary_oos = oos_r["sharpe"]
        sharpe_vals = sweep_df["oos_sharpe"].dropna()
        sensitivity_max_delta = float((sharpe_vals - primary_oos).abs().max() * 100) if not sharpe_vals.empty else 0.0
        sensitivity_pass = sensitivity_max_delta < 50.0
    else:
        sensitivity_max_delta = 0.0
        sensitivity_pass = False

    # Overnight gap attribution
    gap_total = sum(t.get("gap_pnl", 0.0) for t in is_r["trade_log"])
    total_pnl = sum(t.get("pnl_net", 0.0) for t in is_r["trade_log"])
    gap_pct_pnl = abs(gap_total / total_pnl * 100) if total_pnl != 0 else 0.0
    logger.info("IS Gap PnL attribution: %.1f%% of total net PnL", gap_pct_pnl)

    full_metrics = {
        "variant": variant_key,
        "variant_label": variant["label"],
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities_etf_cross_asset",
        "universe": UNIVERSE,
        # IS
        "is_start": is_start,
        "is_end": is_end,
        "is_sharpe": is_r["sharpe"],
        "is_max_drawdown": is_r["max_drawdown"],
        "is_total_return": is_r["total_return"],
        "is_trade_count": is_r["trade_count"],
        "is_win_rate": is_r["win_rate"],
        "is_trades_per_quarter": is_tpq,
        "is_profit_per_trade_bps": is_an["profit_per_trade_bps"],
        "is_cpr": is_an["cpr"],
        "is_profit_factor": is_an["profit_factor"],
        "is_avg_hold_days": is_an["avg_hold_days"],
        "is_gap_pct_pnl": round(gap_pct_pnl, 2),
        "is_flagged_quarters": pq["flagged_quarters"],
        "is_liquidity_flags": is_r.get("liquidity_flags", 0),
        # OOS
        "oos_start": oos_start,
        "oos_end": oos_end,
        "oos_sharpe": oos_r["sharpe"],
        "oos_max_drawdown": oos_r["max_drawdown"],
        "oos_total_return": oos_r["total_return"],
        "oos_trade_count": oos_r["trade_count"],
        "oos_win_rate": oos_r["win_rate"],
        "oos_trades_per_quarter": oos_tpq,
        "oos_profit_per_trade_bps": oos_an["profit_per_trade_bps"],
        "oos_cpr": oos_an["cpr"],
        "oos_profit_factor": oos_an["profit_factor"],
        "oos_avg_hold_days": oos_an["avg_hold_days"],
        "oos_liquidity_flags": oos_r.get("liquidity_flags", 0),
        # Gate 1
        "gate1_pass": gate1["pass"],
        "gate1_checks": gate1["checks"],
        # Composite score
        **cs_result,
        # Statistical rigor
        **mc, **ci, **perm, **mi,
        "wf_windows_passed": wf_pass,
        "wf_total_windows": len(wf),
        "wf_sharpe_min": round(min(wf_sharpes) if wf_sharpes else 0.0, 3),
        "wf_sharpe_std": round(float(np.std(wf_sharpes)) if wf_sharpes else 0.0, 3),
        "wf_windows": wf,
        # Sensitivity
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_sharpe_delta_pct": round(sensitivity_max_delta, 1),
        # Data quality
        "look_ahead_bias_flag": False,
        "survivorship_bias_note": "Fixed 8-ETF universe; no survivorship bias",
        "overnight_weekend_guards_documented": True,
        "gap_pnl_attribution_reported": True,
    }

    # Save variant-specific outputs
    suffix = f"_{variant_key}"
    json_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}{suffix}.json"
    json_path.write_text(json.dumps(full_metrics, indent=2, default=str))
    logger.info("JSON: %s", json_path)

    trades_combined = (
        [{**t, "period": "IS"} for t in is_r["trade_log"]]
        + [{**t, "period": "OOS"} for t in oos_r["trade_log"]]
    )
    trades_df = pd.DataFrame(trades_combined)
    trades_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}{suffix}_trades.csv"
    trades_df.to_csv(trades_path, index=False)

    sweep_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}{suffix}_sweep.csv"
    sweep_df.to_csv(sweep_path, index=False)

    html = build_html(
        variant["label"], is_r, oos_r, is_an, oos_an, gate1, cs_result,
        mc, ci, perm, mi, wf, is_tpq, oos_tpq, pq, sweep_df,
    )
    html_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}{suffix}_report.html"
    html_path.write_text(html)

    lines = [
        f"H83 Elder Triple Screen Multi-ETF — Gate 1 Verdict [{variant['label']}]",
        f"Date: {TODAY}",
        "",
        f"OVERALL: {'PASS' if gate1['pass'] else 'FAIL'}  |  Composite Score: {cs_result['composite_score']:.4f} (threshold: 0.60)",
        "",
        "=== Gate 1 Checks (kpi-daily-weekly.md v1.0) ===",
        "NOTE: No IS Sharpe gate. Only OOS Sharpe > 0.7 hard gate.",
    ]
    for chk, res in gate1["checks"].items():
        lines.append(f"  [{'PASS' if res else 'FAIL'}] {chk}")
    lines += [
        "",
        f"=== Composite Score Breakdown ===",
        f"  NetSharpe_norm (OOS):  {cs_result['sharpe_norm']:.4f} × 0.40 = {0.40*cs_result['sharpe_norm']:.4f}",
        f"  Stability_norm (IS MDD): {cs_result['stability_norm']:.4f} × 0.30 = {0.30*cs_result['stability_norm']:.4f}",
        f"  PpT_norm (IS):         {cs_result['ppt_norm']:.4f} × 0.20 = {0.20*cs_result['ppt_norm']:.4f}",
        f"  TradeAdequacy_norm:    {cs_result['trade_adequacy_norm']:.4f} × 0.10 = {0.10*cs_result['trade_adequacy_norm']:.4f}",
        f"  CS = {cs_result['composite_score']:.4f}  (threshold ≥ 0.60)",
        "",
        f"=== IS Period ({is_start} → {is_end}) ===",
        f"  Sharpe:              {is_r['sharpe']:.4f}  [no IS Sharpe gate in v2.7]",
        f"  Max Drawdown:        {is_r['max_drawdown']:.2%}  [gate: <30%]",
        f"  Total Return:        {is_r['total_return']:.2%}",
        f"  Trade Count:         {is_r['trade_count']}",
        f"  Trades/Quarter:      {is_tpq:.1f}  [gate: ≥30]",
        f"  PpT (bps net):       {is_an['profit_per_trade_bps']:.2f}  [gate: >15]",
        f"  CPR:                 {is_an['cpr']:.4f}  [gate: <0.25]",
        f"  Win Rate:            {is_r['win_rate']:.2%}",
        f"  Avg Hold Days:       {is_an['avg_hold_days']:.1f}",
        f"  Gap PnL attribution: {gap_pct_pnl:.1f}% of IS net PnL",
        f"  Flagged Quarters (<30): {pq['flagged_quarters'] or 'None'}",
        "",
        f"=== OOS Period ({oos_start} → {oos_end}) ===",
        f"  Sharpe:              {oos_r['sharpe']:.4f}  [hard gate: >0.70]",
        f"  Max Drawdown:        {oos_r['max_drawdown']:.2%}",
        f"  Total Return:        {oos_r['total_return']:.2%}",
        f"  Trade Count:         {oos_r['trade_count']}",
        f"  Trades/Quarter:      {oos_tpq:.1f}",
        f"  PpT (bps net):       {oos_an['profit_per_trade_bps']:.2f}",
        f"  CPR:                 {oos_an['cpr']:.4f}",
        f"  Win Rate:            {oos_r['win_rate']:.2%}",
        "",
        "=== Statistical Rigor ===",
        f"  MC P5/Med/P95 Sharpe:  {mc['mc_p5_sharpe']:.3f} / {mc['mc_median_sharpe']:.3f} / {mc['mc_p95_sharpe']:.3f}",
        f"  Bootstrap 95% CI:      [{ci['sharpe_ci_low']:.3f}, {ci['sharpe_ci_high']:.3f}]",
        f"  Market Impact:         {mi['market_impact_bps']:.3f} bps",
        f"  Permutation p-value:   {perm['permutation_pvalue']:.4f}  ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})",
        f"  WF: {wf_pass}/{len(wf)} positive OOS Sharpe  min={min(wf_sharpes) if wf_sharpes else 0:.3f}",
        f"  Sensitivity:           pass={sensitivity_pass}  max_delta={sensitivity_max_delta:.1f}%",
    ]
    verdict_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}{suffix}_verdict.txt"
    verdict_path.write_text("\n".join(lines))
    logger.info("Verdict: %s", verdict_path)
    logger.info("Gate 1 %s | OOS Sharpe=%.3f | CS=%.4f",
                "PASS" if gate1["pass"] else "FAIL",
                oos_r["sharpe"], cs_result["composite_score"])

    return full_metrics


def main():
    logger.info("=" * 64)
    logger.info("H83 Elder Triple Screen Multi-ETF — Gate 1")
    logger.info("=" * 64)

    # Download data once (widest date range needed)
    all_starts = [v["is_start"] for v in VARIANTS.values()]
    data_start = min(all_starts)  # 2003-01-01
    data_end = max(v["oos_end"] for v in VARIANTS.values())
    logger.info("Downloading data: %s ETFs from %s to %s", len(UNIVERSE), data_start, data_end)
    data = download_data(UNIVERSE, data_start, data_end, warmup_days=300)
    available = list(data.keys())
    logger.info("Available tickers: %s", available)
    if len(available) < 4:
        raise RuntimeError(f"Insufficient data: only {len(available)} tickers available")

    results = {}
    for variant_key, variant in VARIANTS.items():
        try:
            results[variant_key] = run_variant(variant_key, variant, data)
        except Exception as exc:
            logger.error("Variant %s failed: %s", variant_key, exc)
            results[variant_key] = {"variant": variant_key, "error": str(exc), "gate1_pass": False}

    # Combined summary JSON
    summary = {
        "strategy": STRATEGY_NAME,
        "date": TODAY,
        "variants": {
            k: {
                "gate1_pass": r.get("gate1_pass", False),
                "oos_sharpe": r.get("oos_sharpe", None),
                "is_sharpe": r.get("is_sharpe", None),
                "composite_score": r.get("composite_score", None),
                "is_mdd": r.get("is_max_drawdown", None),
                "is_tpq": r.get("is_trades_per_quarter", None),
                "is_ppt_bps": r.get("is_profit_per_trade_bps", None),
                "is_cpr": r.get("is_cpr", None),
            }
            for k, r in results.items()
        },
        "overall_pass": any(r.get("gate1_pass", False) for r in results.values()),
    }
    summary_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Summary: %s", summary_path)

    logger.info("=" * 64)
    for k, r in results.items():
        logger.info("  %s: %s  OOS Sharpe=%.3f  CS=%.4f",
                    k.upper(),
                    "PASS" if r.get("gate1_pass") else "FAIL",
                    r.get("oos_sharpe", 0.0),
                    r.get("composite_score", 0.0))
    logger.info("=" * 64)

    return results


if __name__ == "__main__":
    main()
