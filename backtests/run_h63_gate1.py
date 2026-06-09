"""
Gate 1 v2.2 Backtest Runner — H63 SPY/QQQ Intraday Pairs Mean Reversion
Engineering Director (QUA-167)

Outputs:
  backtests/H63_SPY_QQQ_Pairs_2026-06-09.json       — full metrics
  backtests/H63_SPY_QQQ_Pairs_2026-06-09_verdict.txt — Gate 1 verdict
  backtests/H63_SPY_QQQ_Pairs_2026-06-09_report.html — readable report

IS window:  2018-01-01 to 2023-12-31
OOS window: 2024-01-01 to 2026-06-09

Parameter sweep (IS-only):
  ZSCORE_LOOKBACK_MIN: [15, 20, 30, 45]
  ENTRY_ZSCORE:        [1.2, 1.5, 2.0]
  EXIT_ZSCORE:         [0.1, 0.25, 0.5]
  HEDGE_LOOKBACK_DAYS: [10, 20, 30]
  VIX_FILTER_THRESHOLD:[25, 30, 35]

Gate 1 v2.2 pass criteria (from issue QUA-167):
  IS Sharpe    > 1.0
  OOS Sharpe   > 0.7
  IS MDD       < 20%
  OOS degradation (IS→OOS Sharpe drop) < 40%
  IS trade count >= 100
"""

import os
import sys
import json
import logging
import warnings
import itertools
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple

import numpy as np
import pandas as pd

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from strategies.h63_spy_qqq_pairs_mean_reversion import (
    PARAMETERS,
    fetch_minute_data,
    filter_rth,
    compute_daily_beta,
    prepare_signals,
    simulate,
    compute_metrics,
    run_backtest,
    _download_daily,
    _download_vix,
)

# ── Config ─────────────────────────────────────────────────────────────────────

IS_START  = "2018-01-01"
IS_END    = "2023-12-31"
OOS_START = "2024-01-01"
OOS_END   = "2026-06-08"   # Alpaca SIP restricts today; last available trading day

# Warmup for hedging lookback (need prior data for beta)
DATA_START = "2017-07-01"   # 6m before IS to warm up max(30 day) hedge lookback

REPORT_DATE = "2026-06-09"
STRATEGY_NAME = "H63_SPY_QQQ_Pairs"
OUTPUT_DIR = REPO_ROOT / "backtests"

CACHE_DIR = str(REPO_ROOT / "pipelines" / "data" / "h63_cache")

# Gate 1 v2.2 thresholds (from QUA-167 issue description)
GATE_IS_SHARPE     = 1.0
GATE_OOS_SHARPE    = 0.7
GATE_IS_MDD        = -0.20   # negative convention
GATE_OOS_DEGRADE   = 0.40    # max (IS-OOS)/IS
GATE_MIN_TRADES    = 100

# Parameter sweep grid (IS-only)
SWEEP_GRID = {
    "ZSCORE_LOOKBACK_MIN": [15, 20, 30, 45],
    "ENTRY_ZSCORE":        [1.2, 1.5, 2.0],
    "EXIT_ZSCORE":         [0.1, 0.25, 0.5],
    "HEDGE_LOOKBACK_DAYS": [10, 20, 30],
    "VIX_FILTER_THRESHOLD":[25.0, 30.0, 35.0],
}


# ── Data Load ─────────────────────────────────────────────────────────────────

def load_all_data() -> dict:
    """
    Download and cache all required data.
    Returns dict with spy_rth, qqq_rth, spy_daily, qqq_daily, vix_close.
    """
    logger.info("=== DATA DOWNLOAD ===")
    logger.info("Fetching SPY minute bars %s → %s ...", DATA_START, OOS_END)
    spy_raw = fetch_minute_data("SPY", DATA_START, OOS_END, cache_dir=CACHE_DIR)
    logger.info("  SPY: %d bars", len(spy_raw))

    logger.info("Fetching QQQ minute bars %s → %s ...", DATA_START, OOS_END)
    qqq_raw = fetch_minute_data("QQQ", DATA_START, OOS_END, cache_dir=CACHE_DIR)
    logger.info("  QQQ: %d bars", len(qqq_raw))

    spy_rth = filter_rth(spy_raw)
    qqq_rth = filter_rth(qqq_raw)
    logger.info("  SPY RTH: %d bars | QQQ RTH: %d bars", len(spy_rth), len(qqq_rth))

    logger.info("Fetching daily data ...")
    spy_daily = _download_daily("SPY", DATA_START, OOS_END)
    qqq_daily = _download_daily("QQQ", DATA_START, OOS_END)
    vix_close = _download_vix(DATA_START, OOS_END)
    logger.info("  SPY daily: %d rows | QQQ daily: %d rows | VIX: %d rows",
                len(spy_daily), len(qqq_daily), len(vix_close))

    return {
        "spy_rth": spy_rth,
        "qqq_rth": qqq_rth,
        "spy_daily": spy_daily,
        "qqq_daily": qqq_daily,
        "vix_close": vix_close,
    }


# ── Single-window Backtest ─────────────────────────────────────────────────────

def backtest_window(
    start: str,
    end: str,
    params: dict,
    data: dict,
    label: str = "",
) -> dict:
    """Run one backtest and return metrics dict."""
    try:
        result = run_backtest(
            start=start,
            end=end,
            params=params,
            spy_rth_full=data["spy_rth"],
            qqq_rth_full=data["qqq_rth"],
            spy_daily=data["spy_daily"],
            qqq_daily=data["qqq_daily"],
            vix_close=data["vix_close"],
        )
        if label:
            logger.info(
                "  %s: Sharpe=%.3f MDD=%.2f%% trades=%d",
                label, result["sharpe"],
                result["max_drawdown"] * 100,
                result["trade_count"],
            )
        return result
    except Exception as e:
        logger.error("  %s FAILED: %s", label, e)
        traceback.print_exc()
        return {"sharpe": np.nan, "max_drawdown": 0.0, "trade_count": 0, "error": str(e)}


# ── Parameter Sweep ───────────────────────────────────────────────────────────

def run_parameter_sweep(data: dict) -> pd.DataFrame:
    """
    Run the full parameter sweep on IS window only.
    Returns DataFrame with one row per parameter combination.
    """
    keys = list(SWEEP_GRID.keys())
    values = [SWEEP_GRID[k] for k in keys]
    combos = list(itertools.product(*values))
    total = len(combos)
    logger.info("=== PARAMETER SWEEP: %d combinations ===", total)

    records = []
    for idx, combo in enumerate(combos):
        p = PARAMETERS.copy()
        for k, v in zip(keys, combo):
            p[k] = v

        label = f"sweep[{idx+1}/{total}]"
        result = backtest_window(IS_START, IS_END, p, data, label)

        rec = {k: v for k, v in zip(keys, combo)}
        rec["is_sharpe"] = result.get("sharpe", np.nan)
        rec["is_mdd"] = result.get("max_drawdown", 0.0)
        rec["is_trades"] = result.get("trade_count", 0)
        rec["is_win_rate"] = result.get("win_rate", 0.0)
        rec["is_profit_factor"] = result.get("profit_factor", 0.0)
        rec["is_ppt_bps"] = result.get("ppt_bps", 0.0)
        records.append(rec)

        if (idx + 1) % 50 == 0:
            valid = [r for r in records if not np.isnan(r["is_sharpe"])]
            if valid:
                best = max(valid, key=lambda r: r["is_sharpe"])
                logger.info("  Progress %d/%d — best IS Sharpe so far: %.3f", idx+1, total, best["is_sharpe"])

    sweep_df = pd.DataFrame(records)
    logger.info("Sweep complete. Valid combos: %d/%d", sweep_df["is_sharpe"].notna().sum(), total)
    return sweep_df


# ── Gate 1 Verdict ────────────────────────────────────────────────────────────

def evaluate_gate1(is_metrics: dict, oos_metrics: dict) -> dict:
    """
    Evaluate Gate 1 v2.2 criteria.
    Returns verdict dict with pass/fail status for each criterion.
    """
    is_sharpe = is_metrics.get("sharpe", 0.0)
    oos_sharpe = oos_metrics.get("sharpe", 0.0)
    is_mdd = is_metrics.get("max_drawdown", 0.0)
    is_trades = is_metrics.get("trade_count", 0)

    # OOS degradation: (IS - OOS) / IS
    if is_sharpe > 0:
        oos_degrade = (is_sharpe - oos_sharpe) / is_sharpe
    else:
        oos_degrade = 1.0  # fail if IS sharpe <= 0

    criteria = {
        "IS_Sharpe": {
            "value": round(is_sharpe, 4),
            "threshold": f"> {GATE_IS_SHARPE}",
            "pass": bool(is_sharpe > GATE_IS_SHARPE),
        },
        "OOS_Sharpe": {
            "value": round(oos_sharpe, 4),
            "threshold": f"> {GATE_OOS_SHARPE}",
            "pass": bool(oos_sharpe > GATE_OOS_SHARPE),
        },
        "IS_MaxDrawdown": {
            "value": round(is_mdd * 100, 2),
            "threshold": f"> {GATE_IS_MDD * 100:.0f}%",
            "pass": bool(is_mdd > GATE_IS_MDD),
        },
        "OOS_Degradation": {
            "value": round(oos_degrade * 100, 2),
            "threshold": f"< {GATE_OOS_DEGRADE * 100:.0f}%",
            "pass": bool(oos_degrade < GATE_OOS_DEGRADE),
        },
        "IS_TradeCount": {
            "value": is_trades,
            "threshold": f">= {GATE_MIN_TRADES}",
            "pass": bool(is_trades >= GATE_MIN_TRADES),
        },
    }

    all_pass = all(c["pass"] for c in criteria.values())
    return {"criteria": criteria, "verdict": "PASS" if all_pass else "FAIL", "oos_degradation": round(oos_degrade, 4)}


# ── Report Generation ─────────────────────────────────────────────────────────

def generate_json_report(
    is_metrics: dict,
    oos_metrics: dict,
    verdict: dict,
    sweep_df: pd.DataFrame,
    best_params: dict,
    median_is_sharpe: float,
) -> dict:
    """Assemble the JSON report payload."""

    def _safe_metrics(m: dict) -> dict:
        return {
            k: v for k, v in m.items()
            if isinstance(v, (int, float, str, dict, list, bool)) and k not in ("equity", "daily_df", "trades")
        }

    return {
        "strategy": "H63_SPY_QQQ_Intraday_Pairs_Mean_Reversion",
        "version": "1.0",
        "gate": "Gate 1 v2.2",
        "report_date": REPORT_DATE,
        "is_window": {"start": IS_START, "end": IS_END},
        "oos_window": {"start": OOS_START, "end": OOS_END},
        "default_params": PARAMETERS,
        "is_metrics": _safe_metrics(is_metrics),
        "oos_metrics": _safe_metrics(oos_metrics),
        "gate1_verdict": verdict,
        "parameter_sweep": {
            "total_combinations": len(sweep_df),
            "best_is_sharpe": float(sweep_df["is_sharpe"].max()) if not sweep_df.empty else None,
            "median_is_sharpe": round(float(median_is_sharpe), 4),
            "best_params": best_params,
            "sweep_summary": sweep_df.describe().to_dict() if not sweep_df.empty else {},
        },
        "data_quality": {
            "survivorship_bias": "SPY and QQQ are market ETFs — no survivorship bias",
            "price_adjustment": "Alpaca SIP feed with split adjustment; daily data auto_adjust=True",
            "data_gaps": "Alpaca SIP provides complete RTH coverage; gaps flagged by zero-bar sessions",
            "earnings_exclusion": "N/A — ETF strategy, no idiosyncratic earnings risk",
            "delisted_tickers": "N/A — SPY and QQQ still active",
            "universe_bias": "N/A — single pair, not a universe selection strategy",
        },
        "pdt_note": (
            "Strategy requires >3 day trades per 5 rolling days. Requires PDT designation. "
            "At $25K capital, PDT is available IF account maintains >= $25K. "
            "Expected IS MDD of 8-20% could reduce account below $25K PDT threshold. "
            "Recommended minimum capital for live deployment: $30K."
        ),
    }


def generate_verdict_txt(is_metrics: dict, oos_metrics: dict, verdict: dict, sweep_df: pd.DataFrame) -> str:
    lines = [
        "=" * 70,
        f"GATE 1 v2.2 VERDICT — H63 SPY/QQQ Intraday Pairs Mean Reversion",
        f"Report Date: {REPORT_DATE}",
        "=" * 70,
        "",
        f"OVERALL VERDICT: {verdict['verdict']}",
        "",
        "── GATE 1 CRITERIA ──────────────────────────────────────────────────",
    ]
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        lines.append(f"  [{status}] {name}: {c['value']} (threshold: {c['threshold']})")

    lines += [
        "",
        "── IS METRICS (2018-01-01 to 2023-12-31) ───────────────────────────",
        f"  Sharpe:       {is_metrics.get('sharpe', 'N/A'):.4f}",
        f"  Max Drawdown: {is_metrics.get('max_drawdown', 0)*100:.2f}%",
        f"  Total Return: {is_metrics.get('total_return', 0)*100:.2f}%",
        f"  Win Rate:     {is_metrics.get('win_rate', 0)*100:.1f}%",
        f"  Profit Factor:{is_metrics.get('profit_factor', 0):.3f}",
        f"  Trade Count:  {is_metrics.get('trade_count', 0)}",
        f"  Trades/Year:  {is_metrics.get('trades_per_year', 0):.0f}",
        f"  PpT (bps):    {is_metrics.get('ppt_bps', 0):.2f}",
        f"  Cost Ratio:   {is_metrics.get('cost_to_gross_ratio', 0)*100:.1f}%",
        "",
        "── OOS METRICS (2024-01-01 to 2026-06-09) ──────────────────────────",
        f"  Sharpe:       {oos_metrics.get('sharpe', 'N/A'):.4f}",
        f"  Max Drawdown: {oos_metrics.get('max_drawdown', 0)*100:.2f}%",
        f"  Total Return: {oos_metrics.get('total_return', 0)*100:.2f}%",
        f"  Win Rate:     {oos_metrics.get('win_rate', 0)*100:.1f}%",
        f"  Profit Factor:{oos_metrics.get('profit_factor', 0):.3f}",
        f"  Trade Count:  {oos_metrics.get('trade_count', 0)}",
        f"  Trades/Year:  {oos_metrics.get('trades_per_year', 0):.0f}",
        f"  OOS Degradation: {verdict['oos_degradation']*100:.1f}% of IS Sharpe",
        "",
        "── PARAMETER SWEEP SUMMARY (IS-only, 324 combinations) ─────────────",
    ]

    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        if not valid.empty:
            best = valid.loc[valid["is_sharpe"].idxmax()]
            median_sharpe = valid["is_sharpe"].median()
            lines += [
                f"  Best IS Sharpe:   {valid['is_sharpe'].max():.4f}",
                f"  Median IS Sharpe: {median_sharpe:.4f}",
                f"  Worst IS Sharpe:  {valid['is_sharpe'].min():.4f}",
                f"  Best params:      ZSCORE_LOOKBACK={best['ZSCORE_LOOKBACK_MIN']}, "
                f"ENTRY_Z={best['ENTRY_ZSCORE']}, EXIT_Z={best['EXIT_ZSCORE']}, "
                f"HEDGE_DAYS={best['HEDGE_LOOKBACK_DAYS']}, VIX_THRESH={best['VIX_FILTER_THRESHOLD']}",
            ]
        else:
            lines.append("  No valid sweep results")
    else:
        lines.append("  Sweep not run")

    lines += [
        "",
        "── PDT / GATE 8 NOTE ────────────────────────────────────────────────",
        "  Strategy requires >3 day trades per 5 rolling days.",
        "  PDT designation required. At $25K capital, PDT status is held",
        "  IF account maintains >=$ 25K. Expected MDD 8-20% risks PDT loss.",
        "  RECOMMENDATION: Fund at $30K+ for 5K PDT buffer.",
        "  Gate 8 assessed as: CONDITIONAL (PDT-compatible at $25K+ equity)",
        "",
        "── COST MODEL (Engineering Director canonical) ──────────────────────",
        "  Fixed:   $0.005/share",
        "  Slippage: 0.05% of notional",
        "  Market impact: k=0.1 * sigma * sqrt(Q/ADV) (negligible at $12.5K/leg)",
        "",
        "── DATA QUALITY ─────────────────────────────────────────────────────",
        "  Source: Alpaca SIP feed (1-min RTH) + yfinance daily (VIX, beta)",
        "  Split adjustment: Yes (Alpaca split + yfinance auto_adjust)",
        "  Survivorship bias: N/A (SPY/QQQ are market-cap ETFs)",
        "  Earnings events: N/A (ETF strategy)",
        "",
        "=" * 70,
    ]
    return "\n".join(lines)


def generate_html_report(
    is_metrics: dict,
    oos_metrics: dict,
    verdict: dict,
    sweep_df: pd.DataFrame,
) -> str:
    v = verdict["verdict"]
    verdict_color = "#28a745" if v == "PASS" else "#dc3545"

    def fmt_pct(x): return f"{x*100:.2f}%"
    def fmt_n(x): return f"{x:.4f}"

    criteria_rows = ""
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        color = "#28a745" if c["pass"] else "#dc3545"
        criteria_rows += (
            f"<tr><td>{name}</td><td>{c['value']}</td>"
            f"<td>{c['threshold']}</td>"
            f"<td style='color:{color};font-weight:bold'>{status}</td></tr>\n"
        )

    sweep_table = ""
    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        top10 = valid.nlargest(10, "is_sharpe")
        for _, row in top10.iterrows():
            sweep_table += (
                f"<tr><td>{int(row['ZSCORE_LOOKBACK_MIN'])}</td>"
                f"<td>{row['ENTRY_ZSCORE']}</td>"
                f"<td>{row['EXIT_ZSCORE']}</td>"
                f"<td>{int(row['HEDGE_LOOKBACK_DAYS'])}</td>"
                f"<td>{int(row['VIX_FILTER_THRESHOLD'])}</td>"
                f"<td>{row['is_sharpe']:.4f}</td>"
                f"<td>{row['is_mdd']*100:.1f}%</td>"
                f"<td>{row['is_trades']}</td></tr>\n"
            )

    return f"""<!DOCTYPE html>
<html>
<head>
<title>H63 Gate 1 v2.2 Report</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 1000px; margin: 40px auto; color: #333; }}
  h1 {{ color: #1a1a2e; }} h2 {{ color: #16213e; border-bottom: 2px solid #eee; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  th, td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: left; }}
  th {{ background: #f4f4f4; font-weight: bold; }}
  .verdict {{ font-size: 2em; font-weight: bold; color: {verdict_color}; margin: 20px 0; }}
  .metric-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  .metric-box {{ background: #f9f9f9; border: 1px solid #ddd; border-radius: 6px; padding: 15px; }}
  .metric-val {{ font-size: 1.4em; font-weight: bold; color: #1a1a2e; }}
  .warn {{ color: #856404; background: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>Gate 1 v2.2 Report — H63 SPY/QQQ Intraday Pairs Mean Reversion</h1>
<p><strong>Report Date:</strong> {REPORT_DATE} | <strong>IS:</strong> {IS_START} → {IS_END} | <strong>OOS:</strong> {OOS_START} → {OOS_END}</p>

<div class="verdict">Gate 1 Verdict: {v}</div>

<h2>Gate 1 Criteria</h2>
<table><thead><tr><th>Criterion</th><th>Value</th><th>Threshold</th><th>Status</th></tr></thead>
<tbody>{criteria_rows}</tbody></table>

<h2>IS Performance (2018-01-01 to 2023-12-31)</h2>
<div class="metric-grid">
  <div class="metric-box"><div>Sharpe Ratio</div><div class="metric-val">{is_metrics.get('sharpe',0):.4f}</div></div>
  <div class="metric-box"><div>Max Drawdown</div><div class="metric-val">{fmt_pct(is_metrics.get('max_drawdown',0))}</div></div>
  <div class="metric-box"><div>Total Return</div><div class="metric-val">{fmt_pct(is_metrics.get('total_return',0))}</div></div>
  <div class="metric-box"><div>Trade Count ({is_metrics.get('trades_per_year',0):.0f}/yr)</div><div class="metric-val">{is_metrics.get('trade_count',0)}</div></div>
  <div class="metric-box"><div>Win Rate</div><div class="metric-val">{fmt_pct(is_metrics.get('win_rate',0))}</div></div>
  <div class="metric-box"><div>Profit Factor</div><div class="metric-val">{is_metrics.get('profit_factor',0):.3f}</div></div>
  <div class="metric-box"><div>Avg PnL/Trade</div><div class="metric-val">${is_metrics.get('avg_pnl_per_trade',0):.2f}</div></div>
  <div class="metric-box"><div>Net PpT (bps)</div><div class="metric-val">{is_metrics.get('ppt_bps',0):.2f} bps</div></div>
</div>

<h2>OOS Performance (2024-01-01 to 2026-06-09)</h2>
<div class="metric-grid">
  <div class="metric-box"><div>Sharpe Ratio</div><div class="metric-val">{oos_metrics.get('sharpe',0):.4f}</div></div>
  <div class="metric-box"><div>Max Drawdown</div><div class="metric-val">{fmt_pct(oos_metrics.get('max_drawdown',0))}</div></div>
  <div class="metric-box"><div>Total Return</div><div class="metric-val">{fmt_pct(oos_metrics.get('total_return',0))}</div></div>
  <div class="metric-box"><div>Trade Count ({oos_metrics.get('trades_per_year',0):.0f}/yr)</div><div class="metric-val">{oos_metrics.get('trade_count',0)}</div></div>
  <div class="metric-box"><div>Win Rate</div><div class="metric-val">{fmt_pct(oos_metrics.get('win_rate',0))}</div></div>
  <div class="metric-box"><div>OOS Degradation</div><div class="metric-val">{verdict['oos_degradation']*100:.1f}% vs IS</div></div>
</div>

<h2>Parameter Sweep — Top 10 IS Configurations</h2>
<table><thead>
<tr><th>ZScore Win</th><th>Entry Z</th><th>Exit Z</th><th>Hedge Days</th><th>VIX Thresh</th><th>IS Sharpe</th><th>IS MDD</th><th>IS Trades</th></tr>
</thead><tbody>{sweep_table}</tbody></table>

<div class="warn">
<strong>PDT Note (Gate 8):</strong> Strategy trades 3-8 round-trips/day (~6-16 day trades/day), requiring PDT
designation. At $25K, PDT is available but any drawdown below $25K loses eligibility.
Recommended minimum capital: $30K.
</div>

<h2>Transaction Cost Model</h2>
<p>Fixed: $0.005/share | Slippage: 0.05% of notional | Market impact: Almgren-Chriss sqrt-model
(k=0.1 × σ × √(Q/ADV) × notional). At $12.5K/leg, Q/ADV ≈ 0 for SPY/QQQ — market impact negligible.</p>

<h2>Data Quality</h2>
<ul>
  <li><strong>Source:</strong> Alpaca SIP feed (1-min RTH, split-adjusted) + yfinance daily (VIX, beta)</li>
  <li><strong>Survivorship bias:</strong> N/A (SPY/QQQ are broad market ETFs)</li>
  <li><strong>Earnings events:</strong> N/A (ETF strategy, no idiosyncratic earnings)</li>
  <li><strong>Lookahead bias:</strong> None — beta computed using prior-day closes; z-score is rolling backward-window</li>
  <li><strong>Fill model:</strong> 1-bar latency — signal at close → fill at next bar open</li>
</ul>

</body></html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("H63 SPY/QQQ Pairs Mean Reversion — Gate 1 v2.2 Backtest")
    logger.info("=" * 60)

    # ── 1. Load data ─────────────────────────────────────────────────────────
    data = load_all_data()

    # ── 2. Default parameter IS backtest ─────────────────────────────────────
    logger.info("\n=== IS BACKTEST (default params, %s → %s) ===", IS_START, IS_END)
    is_result = backtest_window(IS_START, IS_END, PARAMETERS.copy(), data, "IS")

    logger.info("\n=== OOS BACKTEST (default params, %s → %s) ===", OOS_START, OOS_END)
    oos_result = backtest_window(OOS_START, OOS_END, PARAMETERS.copy(), data, "OOS")

    # ── 3. Gate 1 verdict ────────────────────────────────────────────────────
    verdict = evaluate_gate1(is_result, oos_result)
    logger.info("\n=== GATE 1 VERDICT: %s ===", verdict["verdict"])
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        logger.info("  [%s] %s: %s (threshold: %s)", status, name, c["value"], c["threshold"])

    # ── 4. Parameter sweep (IS only) ─────────────────────────────────────────
    sweep_df = run_parameter_sweep(data)
    best_params = {}
    median_is_sharpe = 0.0
    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        if not valid.empty:
            best_row = valid.loc[valid["is_sharpe"].idxmax()]
            best_params = {k: best_row[k] for k in SWEEP_GRID.keys()}
            median_is_sharpe = float(valid["is_sharpe"].median())
            logger.info("\nSweep results:")
            logger.info("  Best IS Sharpe:   %.4f", valid["is_sharpe"].max())
            logger.info("  Median IS Sharpe: %.4f", median_is_sharpe)
            logger.info("  Worst IS Sharpe:  %.4f", valid["is_sharpe"].min())
            logger.info("  Best params: %s", best_params)
            logger.info("  Robustness: median/best ratio = %.2f%%",
                        median_is_sharpe / valid["is_sharpe"].max() * 100 if valid["is_sharpe"].max() > 0 else 0)

    # ── 5. Generate reports ───────────────────────────────────────────────────
    logger.info("\n=== GENERATING REPORTS ===")
    date_str = REPORT_DATE
    base_name = f"{STRATEGY_NAME}_{date_str}"

    # JSON
    json_report = generate_json_report(is_result, oos_result, verdict, sweep_df, best_params, median_is_sharpe)
    json_path = OUTPUT_DIR / f"{base_name}.json"
    with open(json_path, "w") as f:
        json.dump(json_report, f, indent=2, default=str)
    logger.info("  JSON: %s", json_path)

    # Verdict TXT
    verdict_txt = generate_verdict_txt(is_result, oos_result, verdict, sweep_df)
    verdict_path = OUTPUT_DIR / f"{base_name}_verdict.txt"
    with open(verdict_path, "w") as f:
        f.write(verdict_txt)
    logger.info("  Verdict: %s", verdict_path)

    # HTML
    html_report = generate_html_report(is_result, oos_result, verdict, sweep_df)
    html_path = OUTPUT_DIR / f"{base_name}_report.html"
    with open(html_path, "w") as f:
        f.write(html_report)
    logger.info("  HTML: %s", html_path)

    # Sweep CSV
    if not sweep_df.empty:
        sweep_path = OUTPUT_DIR / f"{base_name}_sweep.csv"
        sweep_df.to_csv(sweep_path, index=False)
        logger.info("  Sweep: %s", sweep_path)

    # Trade log (IS)
    if is_result.get("trades") is not None and not is_result["trades"].empty:
        trades_path = OUTPUT_DIR / f"{base_name}_is_trades.csv"
        is_result["trades"].to_csv(trades_path, index=False)
        logger.info("  IS Trades: %s", trades_path)

    logger.info("\n=== SUMMARY ===")
    logger.info("IS  Sharpe: %.4f  MDD: %.2f%%  Trades: %d",
                is_result["sharpe"], is_result["max_drawdown"]*100, is_result["trade_count"])
    logger.info("OOS Sharpe: %.4f  MDD: %.2f%%  Trades: %d",
                oos_result["sharpe"], oos_result["max_drawdown"]*100, oos_result["trade_count"])
    logger.info("Gate 1 v2.2: %s", verdict["verdict"])

    # Print verdict to stdout
    print("\n" + verdict_txt)

    return {
        "is_result": is_result,
        "oos_result": oos_result,
        "verdict": verdict,
        "sweep_df": sweep_df,
        "json_path": str(json_path),
        "verdict_path": str(verdict_path),
        "html_path": str(html_path),
    }


if __name__ == "__main__":
    result = main()
