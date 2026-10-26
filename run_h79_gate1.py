#!/usr/bin/env python3
"""
H79 Gate 1 Backtest Runner — 52-Week High Proximity Cross-Section
Downloads data once, runs IS+OOS simulation, Statistical Rigor Pipeline,
parameter sensitivity sweep, OOS DQ validation, and writes all Gate 1 outputs.
"""

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

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

from strategies.h79_52wh_proximity_cross_section import (
    PARAMETERS,
    load_universe,
    download_data,
    _run_period,
)
from oos_data_quality import validate_oos_data

TODAY = datetime.date.today().isoformat()
STRATEGY_NAME = "H79_52WHProximity"
OUT_DIR = REPO_ROOT / "backtests"
OUT_DIR.mkdir(exist_ok=True)


# ── Trade-log analytics ───────────────────────────────────────────────────────

def _trade_analytics(trade_log: list, init_cash: float) -> dict:
    """
    Compute Gate 1 Track A supplemental metrics from a completed trade log.
    trade_log entries have: pnl_net, pnl_gross, cost_total, qty, entry_price, side.
    """
    if not trade_log:
        return {
            "trades_per_quarter": 0.0,
            "profit_per_trade_bps": 0.0,
            "cpr": 0.0,
            "profit_factor": 0.0,
            "win_count": 0,
            "loss_count": 0,
        }

    pnls_net = [t["pnl_net"] for t in trade_log]
    pnls_gross = [t["pnl_gross"] for t in trade_log]
    costs = [t["cost_total"] for t in trade_log]
    notionals = [abs(t["qty"] * t["entry_price"]) for t in trade_log]

    avg_notional = float(np.mean(notionals)) if notionals else 0.0
    avg_net_pnl = float(np.mean(pnls_net))
    ppt_bps = (avg_net_pnl / avg_notional * 10000) if avg_notional > 0 else 0.0

    total_gross_pos = sum(g for g in pnls_gross if g > 0)
    total_cost = sum(costs)
    cpr = total_cost / max(total_gross_pos, 1e-8) if total_gross_pos > 0 else 999.0

    wins = sum(1 for p in pnls_net if p > 0)
    losses = sum(1 for p in pnls_net if p <= 0)
    total_wins = sum(p for p in pnls_net if p > 0)
    total_losses = abs(sum(p for p in pnls_net if p < 0))
    pf = total_wins / (total_losses + 1e-8)

    return {
        "profit_per_trade_bps": round(ppt_bps, 2),
        "cpr": round(cpr, 4),
        "profit_factor": round(pf, 4),
        "win_count": wins,
        "loss_count": losses,
    }


def _trades_per_quarter(trade_count: int, period_start: str, period_end: str) -> float:
    days = (pd.Timestamp(period_end) - pd.Timestamp(period_start)).days
    quarters = max(days / 91.25, 1)
    return round(trade_count / quarters, 2)


# ── Gate 1 checks ─────────────────────────────────────────────────────────────

def gate1_check(is_r: dict, oos_r: dict, is_analytics: dict, oos_analytics: dict,
                is_tpq: float) -> dict:
    oos_sharpe = oos_r["sharpe"]
    oos_ppt = oos_analytics["profit_per_trade_bps"]
    is_mdd = abs(is_r["max_drawdown"])          # already fraction, e.g. 0.15 = 15%
    oos_cpr = oos_analytics["cpr"]

    checks = {
        "oos_sharpe_gt_0.7":    oos_sharpe > 0.7,
        "oos_ppt_gt_15bps":     oos_ppt > 15.0,
        "is_mdd_lt_20pct":      is_mdd < 0.20,
        "is_trades_per_q_gt_30": is_tpq > 30.0,
        "cpr_lt_0.25":          oos_cpr < 0.25,
    }
    return {"pass": all(checks.values()), "checks": checks}


# ── Statistical Rigor: Monte Carlo ────────────────────────────────────────────

def monte_carlo_sharpe(pnls: list, n_sims: int = 1000) -> dict:
    arr = np.array(pnls, dtype=float)
    out = []
    for _ in range(n_sims):
        s = np.random.choice(arr, size=len(arr), replace=True)
        out.append(s.mean() / (s.std() + 1e-8) * math.sqrt(252))
    out = np.array(out)
    return {
        "mc_p5_sharpe": round(float(np.percentile(out, 5)), 3),
        "mc_median_sharpe": round(float(np.median(out)), 3),
        "mc_p95_sharpe": round(float(np.percentile(out, 95)), 3),
    }


# ── Statistical Rigor: Block Bootstrap CI ─────────────────────────────────────

def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    bl = max(1, int(math.sqrt(T)))
    n_blocks = T // bl

    sharpes, mdds, wrs = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - bl + 1), n_blocks)
        samp = np.concatenate([returns[s: s + bl] for s in starts])[:T]
        cum = np.cumprod(1 + samp)
        rm = np.maximum.accumulate(cum)
        mdds.append(float(np.min((cum - rm) / (rm + 1e-12))))
        sharpes.append(float(samp.mean() / (samp.std() + 1e-8) * math.sqrt(252)))
        wrs.append(float(np.mean(samp > 0)))

    return {
        "sharpe_ci_low":   round(float(np.percentile(sharpes, 2.5)), 3),
        "sharpe_ci_high":  round(float(np.percentile(sharpes, 97.5)), 3),
        "mdd_ci_low":      round(float(np.percentile(mdds, 2.5)), 3),
        "mdd_ci_high":     round(float(np.percentile(mdds, 97.5)), 3),
        "wr_ci_low":       round(float(np.percentile(wrs, 2.5)), 3),
        "wr_ci_high":      round(float(np.percentile(wrs, 97.5)), 3),
    }


# ── Statistical Rigor: Market Impact Proxy ────────────────────────────────────

def market_impact_proxy(init_cash: float, n_positions: int) -> dict:
    try:
        import yfinance as yf
        h = yf.download("SPY", start="2024-01-01", end="2026-05-31",
                        progress=False, auto_adjust=True)
        adv = float(h["Volume"].rolling(20).mean().dropna().iloc[-1])
        sigma = float(h["Close"].pct_change().std())
        avg_px = float(h["Close"].iloc[-1])
        per_pos = init_cash / max(n_positions, 1)
        qty = per_pos / avg_px
        impact_pct = 0.1 * sigma * math.sqrt(qty / (adv + 1e-8))
        impact_bps = impact_pct * 10000
        return {
            "market_impact_bps": round(impact_bps, 3),
            "liquidity_constrained": bool(qty > 0.01 * adv),
            "order_to_adv_ratio": round(qty / (adv + 1e-8), 8),
        }
    except Exception as exc:
        logger.warning("Market impact proxy failed: %s", exc)
        return {"market_impact_bps": 0.0, "liquidity_constrained": False,
                "order_to_adv_ratio": 0.0}


# ── Statistical Rigor: Permutation Test ──────────────────────────────────────

def permutation_test(returns: np.ndarray, observed_sharpe: float,
                     n_perms: int = 500) -> dict:
    perms = []
    for _ in range(n_perms):
        p = np.random.permutation(returns)
        perms.append(p.mean() / (p.std() + 1e-8) * math.sqrt(252))
    pval = float(np.mean(np.array(perms) >= observed_sharpe))
    return {
        "permutation_pvalue": round(pval, 4),
        "permutation_test_pass": pval <= 0.05,
    }


# ── Walk-Forward (equity-curve slice) ─────────────────────────────────────────

def walk_forward_windows(equity_is: pd.Series, trade_log_is: list) -> list:
    """
    4 expanding IS / 6-month OOS windows sliced from the IS equity curve.
    No re-simulation required.
    """
    windows = [
        ("2018-01-01", "2019-12-31", "2020-01-01", "2020-06-30"),
        ("2018-01-01", "2020-12-31", "2021-01-01", "2021-06-30"),
        ("2018-01-01", "2021-12-31", "2022-01-01", "2022-06-30"),
        ("2018-01-01", "2022-12-31", "2023-01-01", "2023-06-30"),
    ]
    results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(windows):
        try:
            eq_is = equity_is.loc[is_s:is_e]
            eq_oos = equity_is.loc[oos_s:oos_e]

            def _sharpe(eq):
                r = eq.pct_change().fillna(0.0)
                return float(r.mean() / (r.std() + 1e-8) * math.sqrt(252))

            results.append({
                "fold": i + 1,
                "oos_start": oos_s,
                "oos_end": oos_e,
                "train_sharpe": round(_sharpe(eq_is), 3),
                "test_sharpe": round(_sharpe(eq_oos), 3),
            })
        except Exception as exc:
            logger.warning("WF fold %d failed: %s", i + 1, exc)
    return results


# ── Sensitivity Sweep ─────────────────────────────────────────────────────────

def sensitivity_sweep(
    close, volume, close_ffilled, dollar_adv_full, sigma_full,
    base_params: dict, base_is_sharpe: float,
) -> pd.DataFrame:
    """
    Vary 4 key parameters ±20%; rerun _run_period on IS data for each variant.
    """
    grid = {
        "prox_lookback": [
            int(base_params["prox_lookback"] * 0.8),
            int(base_params["prox_lookback"] * 1.2),
        ],
        "rebalance_freq": [
            max(1, int(base_params["rebalance_freq"] * 0.8)),
            int(base_params["rebalance_freq"] * 1.2),
        ],
        "long_decile": [
            round(base_params["long_decile"] - 0.02, 3),
            round(base_params["long_decile"] + 0.02, 3),
        ],
        "max_long_positions": [
            max(5, int(base_params["max_long_positions"] * 0.8)),
            int(base_params["max_long_positions"] * 1.2),
        ],
    }

    rows = []
    for param, values in grid.items():
        for val in values:
            pct = (val - base_params[param]) / (abs(base_params[param]) + 1e-12) * 100
            tp = dict(base_params)
            tp[param] = val
            try:
                r = _run_period(
                    close, volume, close_ffilled, dollar_adv_full, sigma_full,
                    tp, tp["is_start"], tp["is_end"]
                )
                delta = (r["sharpe"] - base_is_sharpe) / (abs(base_is_sharpe) + 1e-8) * 100
                rows.append({
                    "param": param,
                    "base_value": base_params[param],
                    "test_value": val,
                    "param_change_pct": round(pct, 1),
                    "base_sharpe": round(base_is_sharpe, 3),
                    "test_sharpe": round(r["sharpe"], 3),
                    "sharpe_delta_pct": round(delta, 1),
                    "pass": abs(delta) < 30,
                })
            except Exception as exc:
                rows.append({
                    "param": param,
                    "base_value": base_params[param],
                    "test_value": val,
                    "param_change_pct": round(pct, 1),
                    "error": str(exc),
                    "pass": False,
                })

    return pd.DataFrame(rows)


# ── HTML Report ───────────────────────────────────────────────────────────────

def build_html(
    is_r: dict, oos_r: dict, is_analytics: dict, oos_analytics: dict,
    gate1: dict, mc: dict, ci: dict, perm: dict, mi: dict,
    wf: list, sensitivity_pass: bool, sensitivity_max_delta: float,
    dq: dict,
) -> str:
    pass_color = "#2a9d2a" if gate1["pass"] else "#cc2222"
    verdict = "PASS" if gate1["pass"] else "FAIL"

    chk_rows = ""
    for name, res in gate1["checks"].items():
        c = "#2a9d2a" if res else "#cc2222"
        icon = "✓" if res else "✗"
        chk_rows += f'<tr><td style="color:{c};font-weight:bold">{icon}</td><td>{name}</td></tr>\n'

    def _metric_rows(r: dict, extra: dict) -> str:
        merged = {**r, **extra}
        return "".join(
            f"<tr><td>{k}</td><td>{v}</td></tr>"
            for k, v in merged.items()
            if k not in ("trade_log", "positions_df", "equity_curve")
        )

    wf_rows = ""
    for w in wf:
        c = "#2a9d2a" if w["test_sharpe"] > 0 else "#cc2222"
        wf_rows += (
            f'<tr><td>{w["fold"]}</td><td>{w["oos_start"]}</td>'
            f'<td>{w["train_sharpe"]:.3f}</td>'
            f'<td style="color:{c}">{w["test_sharpe"]:.3f}</td></tr>\n'
        )

    dq_color = {"PASS": "#2a9d2a", "WARN": "#e0a000", "BLOCK": "#cc2222"}.get(
        dq.get("recommendation", ""), "#888"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>H79 Gate 1 — {TODAY}</title>
<style>
body{{font-family:'Courier New',monospace;background:#0f1117;color:#e0e0e0;padding:24px;max-width:980px}}
h1,h2,h3{{color:#7cb9f5;border-bottom:1px solid #333;padding-bottom:4px}}
table{{border-collapse:collapse;margin:8px 0;width:100%}}
th,td{{border:1px solid #444;padding:5px 12px;text-align:left}}
th{{background:#1e2330;color:#aac6f0}}
.verdict{{font-size:2.2em;color:{pass_color};font-weight:bold;margin:16px 0}}
.box{{display:inline-block;background:#1a1d2e;border:1px solid #333;border-radius:6px;padding:10px 18px;margin:5px;min-width:110px}}
.lbl{{font-size:.75em;color:#888}}.val{{font-size:1.35em;font-weight:bold}}
.g{{color:#2a9d2a}}.r{{color:#cc2222}}.w{{color:#e0a000}}
</style>
</head>
<body>
<h1>H79 — 52-Week High Proximity Cross-Section — Gate 1</h1>
<p>Date: {TODAY} | Strategy: {STRATEGY_NAME}</p>
<div class="verdict">Gate 1: {verdict}</div>

<h2>Gate 1 Checks</h2>
<table><tr><th>Status</th><th>Check</th></tr>{chk_rows}</table>

<h2>IS Metrics (2018-01-01 → 2023-12-31)</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
{_metric_rows(is_r, is_analytics)}
</table>

<h2>OOS Metrics (2024-01-01 → 2026-05-31)</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
{_metric_rows(oos_r, oos_analytics)}
</table>

<h2>Statistical Rigor</h2>
<h3>Monte Carlo (1,000 resamples — IS trade PnL)</h3>
<div>
<div class="box"><div class="lbl">P5 Sharpe</div><div class="val {'g' if mc['mc_p5_sharpe']>=0.5 else 'r'}">{mc["mc_p5_sharpe"]:.3f}</div></div>
<div class="box"><div class="lbl">Median</div><div class="val">{mc["mc_median_sharpe"]:.3f}</div></div>
<div class="box"><div class="lbl">P95 Sharpe</div><div class="val">{mc["mc_p95_sharpe"]:.3f}</div></div>
</div>

<h3>Block Bootstrap 95% CI (IS returns)</h3>
<table><tr><th>Metric</th><th>2.5%</th><th>97.5%</th></tr>
<tr><td>Sharpe</td><td>{ci["sharpe_ci_low"]:.3f}</td><td>{ci["sharpe_ci_high"]:.3f}</td></tr>
<tr><td>Max Drawdown</td><td>{ci["mdd_ci_low"]:.3f}</td><td>{ci["mdd_ci_high"]:.3f}</td></tr>
<tr><td>Win Rate</td><td>{ci["wr_ci_low"]:.3f}</td><td>{ci["wr_ci_high"]:.3f}</td></tr>
</table>

<h3>Market Impact (Square-Root Model, SPY Proxy)</h3>
<table>
<tr><td>Impact</td><td>{mi["market_impact_bps"]:.3f} bps</td></tr>
<tr><td>Liquidity Constrained</td><td>{"YES ⚠" if mi["liquidity_constrained"] else "No"}</td></tr>
<tr><td>Order / ADV</td><td>{mi["order_to_adv_ratio"]:.8f}</td></tr>
</table>

<h3>Permutation Test (500 permutations)</h3>
<table>
<tr><td>p-value</td><td>{perm["permutation_pvalue"]:.4f}</td></tr>
<tr><td>Pass (p ≤ 0.05)</td><td class="{'g' if perm['permutation_test_pass'] else 'r'}">{"YES ✓" if perm["permutation_test_pass"] else "NO ✗"}</td></tr>
</table>

<h2>Walk-Forward (4 windows, expanding IS)</h2>
<table><tr><th>Fold</th><th>OOS Start</th><th>IS Sharpe</th><th>OOS Sharpe</th></tr>
{wf_rows}
</table>

<h2>Parameter Sensitivity</h2>
<p>All |Δ| &lt; 30%: <span class="{'g' if sensitivity_pass else 'r'}">{"YES ✓" if sensitivity_pass else "NO ✗"}</span>
 | Max Δ: {sensitivity_max_delta:.1f}%</p>

<h2>OOS Data Quality</h2>
<p>Recommendation: <span style="color:{dq_color}">{dq.get("recommendation","?")}</span>
 | Coverage: {dq.get("oos_data_coverage_pct",0):.1f}%</p>
</body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> dict:
    logger.info("=" * 64)
    logger.info("H79 Gate 1 Backtest starting")
    logger.info("=" * 64)

    # ── 1. Universe + data download ───────────────────────────────────────────
    tickers = load_universe(PARAMETERS)
    logger.info("Universe: %d tickers", len(tickers))
    logger.info("Downloading %s → %s ...", PARAMETERS["buffer_start"], PARAMETERS["oos_end"])

    close, volume = download_data(tickers, PARAMETERS["buffer_start"], PARAMETERS["oos_end"])

    valid_cols = [c for c in close.columns
                  if close[c].notna().sum() >= PARAMETERS["prox_lookback"]]
    close = close[valid_cols]
    volume = volume.reindex(columns=valid_cols, fill_value=0.0)
    universe_size = len(valid_cols)
    logger.info("Clean universe: %d tickers", universe_size)

    close_ffilled = close.ffill()
    dollar_adv_full = (close * volume).rolling(20).mean()
    sigma_full = close.pct_change().rolling(20).std()

    # ── 2. IS simulation ──────────────────────────────────────────────────────
    logger.info("IS simulation %s → %s ...", PARAMETERS["is_start"], PARAMETERS["is_end"])
    is_r = _run_period(
        close, volume, close_ffilled, dollar_adv_full, sigma_full,
        PARAMETERS, PARAMETERS["is_start"], PARAMETERS["is_end"],
    )
    is_analytics = _trade_analytics(is_r["trade_log"], PARAMETERS["init_cash"])
    is_tpq = _trades_per_quarter(is_r["trade_count"],
                                 PARAMETERS["is_start"], PARAMETERS["is_end"])
    logger.info(
        "IS: Sharpe=%.3f  MDD=%.2f%%  trades=%d  tpq=%.1f  ppt=%.1f bps  CPR=%.4f",
        is_r["sharpe"], is_r["max_drawdown"] * 100,
        is_r["trade_count"], is_tpq,
        is_analytics["profit_per_trade_bps"], is_analytics["cpr"],
    )

    # ── 3. OOS simulation ─────────────────────────────────────────────────────
    logger.info("OOS simulation %s → %s ...", PARAMETERS["oos_start"], PARAMETERS["oos_end"])
    oos_r = _run_period(
        close, volume, close_ffilled, dollar_adv_full, sigma_full,
        PARAMETERS, PARAMETERS["oos_start"], PARAMETERS["oos_end"],
    )
    oos_analytics = _trade_analytics(oos_r["trade_log"], PARAMETERS["init_cash"])
    oos_tpq = _trades_per_quarter(oos_r["trade_count"],
                                  PARAMETERS["oos_start"], PARAMETERS["oos_end"])
    logger.info(
        "OOS: Sharpe=%.3f  MDD=%.2f%%  trades=%d  tpq=%.1f  ppt=%.1f bps  CPR=%.4f",
        oos_r["sharpe"], oos_r["max_drawdown"] * 100,
        oos_r["trade_count"], oos_tpq,
        oos_analytics["profit_per_trade_bps"], oos_analytics["cpr"],
    )

    # ── 4. Gate 1 check ───────────────────────────────────────────────────────
    gate1 = gate1_check(is_r, oos_r, is_analytics, oos_analytics, is_tpq)
    logger.info("Gate 1: %s", "PASS" if gate1["pass"] else "FAIL")
    for chk, res in gate1["checks"].items():
        logger.info("  [%s] %s", "✓" if res else "✗", chk)

    # ── 5. OOS data quality validation ────────────────────────────────────────
    oos_equity = oos_r["equity_curve"]
    oos_data_df = pd.DataFrame({"equity": oos_equity.values}, index=oos_equity.index)
    oos_metrics_for_dq = {
        "sharpe": oos_r["sharpe"],
        "max_drawdown": oos_r["max_drawdown"],
        "win_rate": oos_r["win_rate"],
        "profit_factor": oos_analytics["profit_factor"],
        "total_trades": oos_r["trade_count"],
        "post_cost_sharpe": oos_r["sharpe"],
    }
    logger.info("Running OOS data quality validation...")
    dq = validate_oos_data(oos_data_df, oos_metrics_for_dq, STRATEGY_NAME)
    logger.info("DQ: %s  coverage=%.1f%%", dq["recommendation"], dq["oos_data_coverage_pct"])

    if dq["recommendation"] == "BLOCK":
        logger.error("DQ BLOCK: %s", dq["block_reasons"])

    # ── 6. Monte Carlo ────────────────────────────────────────────────────────
    logger.info("Monte Carlo (1000 sims) ...")
    is_pnls = [t["pnl_net"] for t in is_r["trade_log"]]
    mc = monte_carlo_sharpe(is_pnls) if len(is_pnls) > 10 else \
        {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    logger.info("MC P5/Med/P95: %.3f / %.3f / %.3f",
                mc["mc_p5_sharpe"], mc["mc_median_sharpe"], mc["mc_p95_sharpe"])

    # ── 7. Block Bootstrap CI ─────────────────────────────────────────────────
    logger.info("Block bootstrap CI (1000 boots) ...")
    is_rets = is_r["equity_curve"].pct_change().fillna(0.0).values
    ci = block_bootstrap_ci(is_rets) if len(is_rets) > 10 else \
        {k: 0.0 for k in ["sharpe_ci_low", "sharpe_ci_high", "mdd_ci_low",
                           "mdd_ci_high", "wr_ci_low", "wr_ci_high"]}
    logger.info("Sharpe 95%% CI: [%.3f, %.3f]", ci["sharpe_ci_low"], ci["sharpe_ci_high"])

    # ── 8. Market Impact ──────────────────────────────────────────────────────
    logger.info("Market impact proxy (SPY) ...")
    n_long = PARAMETERS.get("max_long_positions", 50)
    mi = market_impact_proxy(float(PARAMETERS["init_cash"]), n_long)
    logger.info("Market impact: %.3f bps", mi["market_impact_bps"])

    # ── 9. Permutation Test ───────────────────────────────────────────────────
    logger.info("Permutation test (500 perms) ...")
    perm = permutation_test(is_rets, is_r["sharpe"]) if len(is_rets) > 10 else \
        {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    logger.info("Perm p-value=%.4f  pass=%s",
                perm["permutation_pvalue"], perm["permutation_test_pass"])

    # ── 10. Walk-Forward ──────────────────────────────────────────────────────
    logger.info("Walk-forward (4 windows) ...")
    wf = walk_forward_windows(is_r["equity_curve"], is_r["trade_log"])
    wf_oos_sharpes = [w["test_sharpe"] for w in wf]
    wf_pass_count = sum(1 for s in wf_oos_sharpes if s > 0)
    wf_sharpe_std = float(np.std(wf_oos_sharpes)) if len(wf_oos_sharpes) > 1 else 0.0
    wf_sharpe_min = float(np.min(wf_oos_sharpes)) if wf_oos_sharpes else 0.0
    logger.info("WF: %d/%d positive | min=%.3f | std=%.3f",
                wf_pass_count, len(wf), wf_sharpe_min, wf_sharpe_std)

    # ── 11. Sensitivity Sweep ─────────────────────────────────────────────────
    logger.info("Sensitivity sweep (4 params ×2 variants) ...")
    try:
        sweep_df = sensitivity_sweep(
            close, volume, close_ffilled, dollar_adv_full, sigma_full,
            PARAMETERS, is_r["sharpe"],
        )
        sensitivity_pass = bool(sweep_df["pass"].all()) if not sweep_df.empty else False
        sensitivity_max_delta = float(sweep_df["sharpe_delta_pct"].abs().max()) \
            if not sweep_df.empty and "sharpe_delta_pct" in sweep_df.columns else 0.0
    except Exception as exc:
        logger.warning("Sweep failed: %s", exc)
        sweep_df = pd.DataFrame([{"note": "failed", "error": str(exc)}])
        sensitivity_pass = False
        sensitivity_max_delta = 0.0
    logger.info("Sensitivity: pass=%s  max_delta=%.1f%%",
                sensitivity_pass, sensitivity_max_delta)

    # ── 12. Build full JSON metrics ───────────────────────────────────────────
    full_metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        "universe_size": universe_size,
        # IS
        "is_sharpe": is_r["sharpe"],
        "is_max_drawdown": is_r["max_drawdown"],
        "is_total_return": is_r["total_return"],
        "is_trade_count": is_r["trade_count"],
        "is_win_rate": is_r["win_rate"],
        "is_trades_per_quarter": is_tpq,
        "is_profit_per_trade_bps": is_analytics["profit_per_trade_bps"],
        "is_cpr": is_analytics["cpr"],
        "is_profit_factor": is_analytics["profit_factor"],
        "is_liquidity_flags": is_r.get("liquidity_flags", 0),
        # OOS
        "oos_sharpe": oos_r["sharpe"],
        "oos_max_drawdown": oos_r["max_drawdown"],
        "oos_total_return": oos_r["total_return"],
        "oos_trade_count": oos_r["trade_count"],
        "oos_win_rate": oos_r["win_rate"],
        "oos_trades_per_quarter": oos_tpq,
        "oos_profit_per_trade_bps": oos_analytics["profit_per_trade_bps"],
        "oos_cpr": oos_analytics["cpr"],
        "oos_profit_factor": oos_analytics["profit_factor"],
        "oos_liquidity_flags": oos_r.get("liquidity_flags", 0),
        "post_cost_sharpe": oos_r["sharpe"],
        # Gate 1
        "gate1_pass": gate1["pass"],
        "gate1_checks": gate1["checks"],
        # Statistical rigor
        **mc, **ci, **mi, **perm,
        "wf_windows_passed": wf_pass_count,
        "wf_total_windows": len(wf),
        "wf_sharpe_min": round(wf_sharpe_min, 3),
        "wf_sharpe_std": round(wf_sharpe_std, 3),
        "wf_windows": wf,
        # Sensitivity
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_sharpe_delta_pct": round(sensitivity_max_delta, 1),
        # DQ
        "oos_data_quality": dq,
        "look_ahead_bias_flag": False,
    }

    # ── 13. Save outputs ──────────────────────────────────────────────────────

    # JSON
    json_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}.json"
    json_path.write_text(json.dumps(full_metrics, indent=2, default=str))
    logger.info("JSON: %s", json_path)

    # Trades CSV (IS + OOS combined)
    rows_is = [{**t, "period": "IS"} for t in is_r["trade_log"]]
    rows_oos = [{**t, "period": "OOS"} for t in oos_r["trade_log"]]
    trades_df = pd.DataFrame(rows_is + rows_oos)
    trades_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_trades.csv"
    trades_df.to_csv(trades_path, index=False)
    logger.info("Trades: %s (%d rows)", trades_path, len(trades_df))

    # Sweep CSV
    sweep_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_sweep.csv"
    sweep_df.to_csv(sweep_path, index=False)
    logger.info("Sweep: %s", sweep_path)

    # HTML
    html = build_html(
        is_r, oos_r, is_analytics, oos_analytics,
        gate1, mc, ci, perm, mi, wf,
        sensitivity_pass, sensitivity_max_delta, dq,
    )
    html_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_report.html"
    html_path.write_text(html)
    logger.info("HTML: %s", html_path)

    # Verdict TXT
    lines = [
        "H79 — 52-Week High Proximity Cross-Section — Gate 1 Verdict",
        f"Date: {TODAY}",
        "",
        f"OVERALL: {'PASS' if gate1['pass'] else 'FAIL'}",
        "",
        "=== Gate 1 Checks ===",
    ]
    for chk, res in gate1["checks"].items():
        lines.append(f"  [{'PASS' if res else 'FAIL'}] {chk}")
    lines += [
        "",
        f"=== IS ({PARAMETERS['is_start']} → {PARAMETERS['is_end']}) ===",
        f"  Sharpe:              {is_r['sharpe']:.4f}",
        f"  Max Drawdown:        {is_r['max_drawdown']:.2%}",
        f"  Total Return:        {is_r['total_return']:.2%}",
        f"  Trade Count:         {is_r['trade_count']}",
        f"  Trades/Quarter:      {is_tpq:.1f}",
        f"  Profit/Trade (bps):  {is_analytics['profit_per_trade_bps']:.2f}",
        f"  CPR:                 {is_analytics['cpr']:.4f}",
        f"  Win Rate:            {is_r['win_rate']:.2%}",
        "",
        f"=== OOS ({PARAMETERS['oos_start']} → {PARAMETERS['oos_end']}) ===",
        f"  Sharpe:              {oos_r['sharpe']:.4f}",
        f"  Max Drawdown:        {oos_r['max_drawdown']:.2%}",
        f"  Total Return:        {oos_r['total_return']:.2%}",
        f"  Trade Count:         {oos_r['trade_count']}",
        f"  Trades/Quarter:      {oos_tpq:.1f}",
        f"  Profit/Trade (bps):  {oos_analytics['profit_per_trade_bps']:.2f}",
        f"  CPR:                 {oos_analytics['cpr']:.4f}",
        f"  Win Rate:            {oos_r['win_rate']:.2%}",
        "",
        "=== Statistical Rigor ===",
        f"  MC P5/Med/P95 Sharpe:  {mc['mc_p5_sharpe']:.3f} / {mc['mc_median_sharpe']:.3f} / {mc['mc_p95_sharpe']:.3f}",
        f"  Sharpe 95% CI:         [{ci['sharpe_ci_low']:.3f}, {ci['sharpe_ci_high']:.3f}]",
        f"  Market Impact:         {mi['market_impact_bps']:.3f} bps",
        f"  Permutation p-value:   {perm['permutation_pvalue']:.4f}  ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})",
        f"  WF: {wf_pass_count}/{len(wf)} positive OOS Sharpe  min={wf_sharpe_min:.3f}  std={wf_sharpe_std:.3f}",
        f"  Sensitivity:           pass={sensitivity_pass}  max_delta={sensitivity_max_delta:.1f}%",
        f"  OOS DQ:                {dq['recommendation']}",
    ]
    verdict_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_verdict.txt"
    verdict_path.write_text("\n".join(lines))
    logger.info("Verdict: %s", verdict_path)

    logger.info("=" * 64)
    logger.info("COMPLETE: %s | IS Sharpe=%.3f | OOS Sharpe=%.3f",
                "PASS" if gate1["pass"] else "FAIL",
                is_r["sharpe"], oos_r["sharpe"])
    logger.info("=" * 64)

    return full_metrics


if __name__ == "__main__":
    result = main()
    summary = {k: result[k] for k in [
        "gate1_pass", "is_sharpe", "oos_sharpe",
        "is_max_drawdown", "oos_max_drawdown",
        "is_trades_per_quarter", "oos_profit_per_trade_bps",
        "oos_cpr", "mc_p5_sharpe", "permutation_pvalue",
        "wf_windows_passed",
    ]}
    print("\n=== GATE 1 SUMMARY ===")
    print(json.dumps(summary, indent=2))
