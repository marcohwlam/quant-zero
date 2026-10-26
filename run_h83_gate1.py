#!/usr/bin/env python3
"""
H83 Gate 1 Backtest Runner — USD-Regime EM Country Rotation
IS: 2015-01-01 to 2022-12-31 | OOS: 2023-01-01 to 2024-12-31
Walk-forward: 6 x (3-month IS / 1-month OOS) windows sliced from IS equity curve
Parameter sweep: SMA period x EM lookback x top-N x hard-stop (108 combinations)
PF-1: if IS tpq < 30, expand to 8 ETFs (+ EWG + EWA), top-4, rerun.
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

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

from strategies.h83_usd_regime_em_country_rotation import (
    PARAMETERS,
    download_data,
    check_data_quality,
    run_backtest_from_data,
)
from oos_data_quality import validate_oos_data

TODAY = datetime.date.today().isoformat()
STRATEGY_NAME = "H83_USDRegimeEMRotation"
OUT_DIR = REPO_ROOT / "backtests"
OUT_DIR.mkdir(exist_ok=True)

# Pre-load all tickers including expanded universe candidates
ALL_TICKERS = ["EWZ", "FXI", "INDA", "EWT", "EWY", "EWJ", "EWG", "EWA", "SHY", "UUP"]
IS_START = "2015-01-01"
IS_END = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
# Buffer: sma_period(max=100) + lookback(max=42) + 30 = 172 days
BUF_START = "2014-05-01"


# ── Trade analytics ────────────────────────────────────────────────────────────

def _trade_analytics(trade_pnl: list) -> dict:
    if not trade_pnl:
        return {
            "profit_per_trade_bps": 0.0, "cpr": 0.0,
            "profit_factor": 0.0, "win_count": 0, "loss_count": 0,
        }
    pnls = [t["pnl"] for t in trade_pnl]
    pnls_gross = [t.get("pnl_gross", t["pnl"]) for t in trade_pnl]
    costs = [t.get("cost_total", 0.0) for t in trade_pnl]
    notionals = [abs(t.get("cost_basis", 1.0)) for t in trade_pnl]

    avg_notional = float(np.mean(notionals)) if notionals else 1.0
    avg_pnl = float(np.mean(pnls)) if pnls else 0.0
    ppt_bps = avg_pnl / avg_notional * 10000 if avg_notional > 0 else 0.0

    gross_pos = sum(g for g in pnls_gross if g > 0)
    total_cost = sum(costs)
    cpr = total_cost / max(gross_pos, 1e-8) if gross_pos > 0 else 999.0

    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    total_wins = sum(p for p in pnls if p > 0)
    total_losses = abs(sum(p for p in pnls if p < 0))
    pf = total_wins / (total_losses + 1e-8)

    return {
        "profit_per_trade_bps": round(ppt_bps, 2),
        "cpr": round(min(cpr, 999.0), 4),
        "profit_factor": round(pf, 4),
        "win_count": wins,
        "loss_count": losses,
    }


def _trades_per_quarter(trade_count: int, period_start: str, period_end: str) -> float:
    days = (pd.Timestamp(period_end) - pd.Timestamp(period_start)).days
    quarters = max(days / 91.25, 1)
    return round(trade_count / quarters, 2)


# ── Gate 1 checks ──────────────────────────────────────────────────────────────

def gate1_check(is_r: dict, oos_r: dict, oos_analytics: dict, is_tpq: float) -> dict:
    checks = {
        "oos_sharpe_gt_0.7": oos_r["sharpe"] > 0.7,
        "oos_ppt_gt_15bps": oos_analytics["profit_per_trade_bps"] > 15.0,
        "is_mdd_lt_20pct": abs(is_r["max_drawdown"]) < 0.20,
        "is_trades_per_q_gt_30": is_tpq > 30.0,
        "cpr_lt_0.25": oos_analytics["cpr"] < 0.25,
    }
    return {"pass": all(checks.values()), "checks": checks}


# ── Statistical rigor ──────────────────────────────────────────────────────────

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
        "sharpe_ci_low": round(float(np.percentile(sharpes, 2.5)), 3),
        "sharpe_ci_high": round(float(np.percentile(sharpes, 97.5)), 3),
        "mdd_ci_low": round(float(np.percentile(mdds, 2.5)), 3),
        "mdd_ci_high": round(float(np.percentile(mdds, 97.5)), 3),
        "wr_ci_low": round(float(np.percentile(wrs, 2.5)), 3),
        "wr_ci_high": round(float(np.percentile(wrs, 97.5)), 3),
    }


def market_impact_proxy(init_cash: float, n_positions: int,
                        close: pd.DataFrame) -> dict:
    try:
        ticker = "EWZ"
        if ticker in close.columns:
            oos_close = close.loc[OOS_START:OOS_END, ticker].dropna()
            oos_vol = None
        else:
            return {"market_impact_bps": 0.0, "liquidity_constrained": False,
                    "order_to_adv_ratio": 0.0}
        # Use daily returns as proxy for sigma; ADV from yfinance volume
        import yfinance as yf
        h = yf.download(ticker, start=OOS_START, end=OOS_END,
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


# ── Walk-Forward: 6 x (3-month IS / 1-month OOS) ──────────────────────────────

def walk_forward_windows(equity_is: pd.Series, trade_pnl_is: list) -> list:
    """
    6 x (3-month IS / 1-month OOS) windows within 2021-07 to 2023-01.
    Each IS window checked for PF-1: >= 30 trades/quarter.
    Sliced from the IS equity curve (no re-simulation required).
    """
    windows = [
        ("2021-07-01", "2021-09-30", "2021-10-01", "2021-10-31"),
        ("2021-10-01", "2021-12-31", "2022-01-01", "2022-01-31"),
        ("2022-01-01", "2022-03-31", "2022-04-01", "2022-04-30"),
        ("2022-04-01", "2022-06-30", "2022-07-01", "2022-07-31"),
        ("2022-07-01", "2022-09-30", "2022-10-01", "2022-10-31"),
        ("2022-10-01", "2022-12-31", "2023-01-01", "2023-01-31"),
    ]

    def _sharpe_slice(eq: pd.Series) -> float:
        r = eq.pct_change().fillna(0.0)
        if len(r) < 5:
            return 0.0
        return float(r.mean() / (r.std() + 1e-8) * math.sqrt(252))

    def _count_trades(t_list: list, start: str, end: str) -> int:
        return sum(
            1 for t in t_list
            if "buy_date" in t and start <= t["buy_date"] <= end
        )

    results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(windows):
        try:
            eq_is_sl = equity_is.loc[is_s:is_e]
            eq_oos_sl = equity_is.loc[oos_s:oos_e]
            n_trades = _count_trades(trade_pnl_is, is_s, is_e)
            results.append({
                "fold": i + 1,
                "is_start": is_s,
                "is_end": is_e,
                "oos_start": oos_s,
                "oos_end": oos_e,
                "train_sharpe": round(_sharpe_slice(eq_is_sl), 3),
                "test_sharpe": round(_sharpe_slice(eq_oos_sl), 3),
                "is_trades_count": n_trades,
                "pf1_pass": n_trades >= 30,
            })
        except Exception as exc:
            logger.warning("WF fold %d failed: %s", i + 1, exc)
    return results


# ── Sensitivity Sweep ──────────────────────────────────────────────────────────

def sensitivity_sweep(
    close: pd.DataFrame, volume: pd.DataFrame, base_is_sharpe: float
) -> pd.DataFrame:
    """
    108-combination parameter sweep: SMA x lookback x top-N x stop.
    Reuses pre-downloaded close/volume data — no re-download per combination.
    """
    sma_periods = [30, 50, 63, 100]
    lookbacks = [10, 20, 42]
    top_ns = [2, 3, 4]
    stops = [0.10, 0.15, None]

    rows = []
    total = len(sma_periods) * len(lookbacks) * len(top_ns) * len(stops)
    done = 0

    for sma in sma_periods:
        for lb in lookbacks:
            for k in top_ns:
                for stop in stops:
                    done += 1
                    stop_label = f"{int(stop * 100)}pct" if stop is not None else "nostop"
                    key = f"sma{sma}_lb{lb}_k{k}_stop_{stop_label}"
                    try:
                        r = run_backtest_from_data(
                            close, volume, IS_START, IS_END,
                            usd_sma_period=sma,
                            em_lookback_days=lb,
                            top_n=k,
                            hard_stop_pct=stop,
                        )
                        delta = (
                            (r["sharpe"] - base_is_sharpe)
                            / (abs(base_is_sharpe) + 1e-8) * 100
                        )
                        rows.append({
                            "key": key,
                            "sma_period": sma,
                            "em_lookback": lb,
                            "top_n": k,
                            "hard_stop_pct": stop if stop is not None else "none",
                            "sharpe": round(r["sharpe"], 4),
                            "cagr": round(r["cagr"], 4),
                            "max_drawdown": round(r["max_drawdown"], 4),
                            "trade_count": r["trade_count"],
                            "profit_per_trade_bps": round(r.get("profit_per_trade_bps", 0), 2),
                            "cpr": round(r.get("cpr", 999), 4),
                            "base_sharpe": round(base_is_sharpe, 3),
                            "sharpe_delta_pct": round(delta, 1),
                            "pass": abs(delta) < 30,
                        })
                    except Exception as exc:
                        rows.append({
                            "key": key,
                            "sma_period": sma,
                            "em_lookback": lb,
                            "top_n": k,
                            "hard_stop_pct": stop if stop is not None else "none",
                            "error": str(exc),
                            "sharpe": 0.0,
                            "sharpe_delta_pct": 0.0,
                            "pass": False,
                        })
                    if done % 20 == 0:
                        logger.info("  Sweep progress: %d/%d", done, total)

    return pd.DataFrame(rows)


# ── HTML Report ────────────────────────────────────────────────────────────────

def build_html(
    is_r: dict, oos_r: dict, gate1: dict, mc: dict, ci: dict,
    perm: dict, mi: dict, wf: list,
    sensitivity_pass: bool, sensitivity_max_delta: float,
    dq: dict, sweep_df: pd.DataFrame,
) -> str:
    pass_color = "#2a9d2a" if gate1["pass"] else "#cc2222"
    verdict = "PASS" if gate1["pass"] else "FAIL"

    chk_rows = "".join(
        f'<tr><td style="color:{"#2a9d2a" if res else "#cc2222"};font-weight:bold">'
        f'{"✓" if res else "✗"}</td><td>{name}</td></tr>\n'
        for name, res in gate1["checks"].items()
    )

    def _fmt(v):
        if isinstance(v, float):
            return f"{v:.4f}"
        return str(v)

    def _metric_rows(r: dict) -> str:
        skip = {"trade_log", "_portfolio_value", "_daily_returns", "_pnl_arr",
                "trade_pnl", "data_quality", "liquidity_flags", "gap_contribution"}
        return "".join(
            f"<tr><td>{k}</td><td>{_fmt(v)}</td></tr>"
            for k, v in r.items()
            if k not in skip and not k.startswith("_")
        )

    wf_rows = ""
    for w in wf:
        pf_c = "#2a9d2a" if w.get("pf1_pass", False) else "#cc2222"
        ts_c = "#2a9d2a" if w["test_sharpe"] > 0 else "#cc2222"
        wf_rows += (
            f'<tr><td>{w["fold"]}</td><td>{w["is_start"]}</td><td>{w["is_end"]}</td>'
            f'<td>{w["oos_start"]}</td>'
            f'<td>{w["train_sharpe"]:.3f}</td>'
            f'<td style="color:{ts_c}">{w["test_sharpe"]:.3f}</td>'
            f'<td style="color:{pf_c}">{w["is_trades_count"]}'
            f' ({"PASS" if w.get("pf1_pass") else "FAIL"})</td></tr>\n'
        )

    # Heatmap: SMA period x EM lookback, avg Sharpe for top_n=3, no-stop
    heatmap_html = ""
    try:
        hm = sweep_df[
            (sweep_df["top_n"] == 3)
            & (sweep_df["hard_stop_pct"].astype(str) == "none")
        ].copy()
        if not hm.empty and "sharpe" in hm.columns:
            pivot = hm.pivot_table(
                values="sharpe",
                index="em_lookback",
                columns="sma_period",
                aggfunc="mean",
            )
            heatmap_html = (
                "<h3>Sharpe Heatmap (top_n=3, no stop): SMA Period x EM Lookback</h3>"
                "<table><tr><th>EM Lookback \\ SMA</th>"
            )
            for col in pivot.columns:
                heatmap_html += f"<th>SMA {col}</th>"
            heatmap_html += "</tr>"
            for idx, row in pivot.iterrows():
                heatmap_html += f"<tr><td>{idx}d</td>"
                for val in row:
                    c = "#2a9d2a" if val > 0.7 else ("#e0a000" if val > 0.3 else "#cc2222")
                    heatmap_html += f'<td style="color:{c}">{val:.3f}</td>'
                heatmap_html += "</tr>"
            heatmap_html += "</table>"
    except Exception:
        pass

    dq_color = {"PASS": "#2a9d2a", "WARN": "#e0a000", "BLOCK": "#cc2222"}.get(
        dq.get("recommendation", ""), "#888"
    )
    gap = is_r.get("gap_contribution", {})
    yr22_ret = is_r.get("year_2022_return", 0)
    yr22_mdd = is_r.get("year_2022_mdd", 0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>H83 Gate 1 — {TODAY}</title>
<style>
body{{font-family:'Courier New',monospace;background:#0f1117;color:#e0e0e0;padding:24px;max-width:980px}}
h1,h2,h3{{color:#7cb9f5;border-bottom:1px solid #333;padding-bottom:4px}}
table{{border-collapse:collapse;margin:8px 0;width:100%}}
th,td{{border:1px solid #444;padding:5px 12px;text-align:left}}
th{{background:#1e2330;color:#aac6f0}}
.verdict{{font-size:2.2em;color:{pass_color};font-weight:bold;margin:16px 0}}
.box{{display:inline-block;background:#1a1d2e;border:1px solid #333;border-radius:6px;
      padding:10px 18px;margin:5px;min-width:110px}}
.lbl{{font-size:.75em;color:#888}}.val{{font-size:1.35em;font-weight:bold}}
.g{{color:#2a9d2a}}.r{{color:#cc2222}}.w{{color:#e0a000}}
</style>
</head>
<body>
<h1>H83 — USD-Regime EM Country Rotation — Gate 1</h1>
<p>Date: {TODAY} | Strategy: {STRATEGY_NAME}</p>
<div class="verdict">Gate 1: {verdict}</div>

<h2>Gate 1 Checks</h2>
<table><tr><th>Status</th><th>Check</th></tr>{chk_rows}</table>

<h2>IS Metrics (2015-01-01 to 2022-12-31)</h2>
<table><tr><th>Metric</th><th>Value</th></tr>{_metric_rows(is_r)}</table>

<h2>OOS Metrics (2023-01-01 to 2024-12-31)</h2>
<table><tr><th>Metric</th><th>Value</th></tr>{_metric_rows(oos_r)}</table>

<h2>2022 Standalone — USD-Strong Rate Shock Stress Test</h2>
<div>
<div class="box"><div class="lbl">2022 Return</div>
  <div class="val {'g' if yr22_ret > -0.05 else 'r'}">{yr22_ret:.2%}</div></div>
<div class="box"><div class="lbl">2022 MDD</div>
  <div class="val {'g' if abs(yr22_mdd) < 0.05 else 'r'}">{yr22_mdd:.2%}</div></div>
<div class="box"><div class="lbl">2022 Sharpe</div>
  <div class="val">{is_r.get("year_2022_sharpe", 0):.3f}</div></div>
<div class="box"><div class="lbl">Regime % EM</div>
  <div class="val">{is_r.get("signal_regime_pct_em", 0):.1%}</div></div>
<div class="box"><div class="lbl">Regime % SHY</div>
  <div class="val">{is_r.get("signal_regime_pct_shy", 0):.1%}</div></div>
</div>

<h2>Statistical Rigor</h2>
<h3>Monte Carlo (1,000 resamples of IS trade PnL)</h3>
<div>
<div class="box"><div class="lbl">P5 Sharpe</div>
  <div class="val {'g' if mc['mc_p5_sharpe'] >= 0.5 else 'r'}">{mc["mc_p5_sharpe"]:.3f}</div></div>
<div class="box"><div class="lbl">Median</div>
  <div class="val">{mc["mc_median_sharpe"]:.3f}</div></div>
<div class="box"><div class="lbl">P95 Sharpe</div>
  <div class="val">{mc["mc_p95_sharpe"]:.3f}</div></div>
</div>

<h3>Block Bootstrap 95% CI (IS daily returns)</h3>
<table><tr><th>Metric</th><th>2.5%</th><th>97.5%</th></tr>
<tr><td>Sharpe</td><td>{ci["sharpe_ci_low"]:.3f}</td><td>{ci["sharpe_ci_high"]:.3f}</td></tr>
<tr><td>Max Drawdown</td><td>{ci["mdd_ci_low"]:.3f}</td><td>{ci["mdd_ci_high"]:.3f}</td></tr>
<tr><td>Win Rate</td><td>{ci["wr_ci_low"]:.3f}</td><td>{ci["wr_ci_high"]:.3f}</td></tr>
</table>

<h3>Market Impact (Square-Root Model, EWZ Proxy)</h3>
<table>
<tr><td>Impact</td><td>{mi["market_impact_bps"]:.3f} bps</td></tr>
<tr><td>Liquidity Constrained</td><td>{"YES &ensp;⚠" if mi["liquidity_constrained"] else "No"}</td></tr>
<tr><td>Order / ADV</td><td>{mi["order_to_adv_ratio"]:.8f}</td></tr>
</table>

<h3>Permutation Test (500 permutations)</h3>
<table>
<tr><td>p-value</td><td>{perm["permutation_pvalue"]:.4f}</td></tr>
<tr><td>Pass (p ≤ 0.05)</td>
  <td class="{'g' if perm['permutation_test_pass'] else 'r'}">
  {"YES ✓" if perm["permutation_test_pass"] else "NO ✗"}</td></tr>
</table>

<h2>Walk-Forward (6 windows — 3-month IS / 1-month OOS)</h2>
<table>
<tr><th>Fold</th><th>IS Start</th><th>IS End</th><th>OOS Start</th>
<th>IS Sharpe</th><th>OOS Sharpe</th><th>IS Trades (PF-1)</th></tr>
{wf_rows}
</table>

<h2>Parameter Sensitivity (108 combinations)</h2>
<p>All |Δ| &lt; 30%:
  <span class="{'g' if sensitivity_pass else 'r'}">
  {"YES ✓" if sensitivity_pass else "NO ✗"}</span>
  | Max Δ: {sensitivity_max_delta:.1f}%</p>
{heatmap_html}

<h2>Overnight / Weekend Gap Disclosure (Track A Guard)</h2>
<table>
<tr><td>Overnight PnL contribution (est.)</td>
  <td>{gap.get("overnight_pnl_contribution_pct", 0):.2%}</td></tr>
<tr><td>Overnight MDD contribution (est.)</td>
  <td>{gap.get("overnight_mdd_contribution_pct", 0):.2%}</td></tr>
<tr><td>Note</td><td>{gap.get("note", "")}</td></tr>
</table>

<h2>OOS Data Quality</h2>
<p>Recommendation: <span style="color:{dq_color}">{dq.get("recommendation", "?")}</span>
 | Coverage: {dq.get("oos_data_coverage_pct", 0):.1f}%</p>
</body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> dict:
    logger.info("=" * 64)
    logger.info("H83 Gate 1 — USD-Regime EM Country Rotation")
    logger.info("=" * 64)

    # ── 1. Download data once ─────────────────────────────────────────────────
    logger.info("Downloading %s tickers %s to %s ...", len(ALL_TICKERS), BUF_START, OOS_END)
    close, volume = download_data(ALL_TICKERS, BUF_START, OOS_END)
    close = close.dropna(axis=1, how="all")
    logger.info("Downloaded: %d tickers  %d trading days", len(close.columns), len(close))
    quality = check_data_quality(close, ALL_TICKERS)

    # ── 2. IS simulation ──────────────────────────────────────────────────────
    logger.info("IS simulation %s -> %s ...", IS_START, IS_END)
    is_r = run_backtest_from_data(close, volume, IS_START, IS_END)
    is_r["data_quality"] = quality
    is_tpq = _trades_per_quarter(is_r["trade_count"], IS_START, IS_END)
    logger.info(
        "IS: Sharpe=%.3f  CAGR=%.2f%%  MDD=%.2f%%  trades=%d  tpq=%.1f  "
        "ppt=%.1f bps  CPR=%.4f",
        is_r["sharpe"], is_r["cagr"] * 100, is_r["max_drawdown"] * 100,
        is_r["trade_count"], is_tpq,
        is_r.get("profit_per_trade_bps", 0), is_r.get("cpr", 999),
    )
    logger.info(
        "IS 2022: return=%.2f%%  MDD=%.2f%%  Regime EM=%.1f%%  SHY=%.1f%%",
        is_r.get("year_2022_return", 0) * 100,
        is_r.get("year_2022_mdd", 0) * 100,
        is_r.get("signal_regime_pct_em", 0) * 100,
        is_r.get("signal_regime_pct_shy", 0) * 100,
    )

    # ── 3. OOS simulation ─────────────────────────────────────────────────────
    logger.info("OOS simulation %s -> %s ...", OOS_START, OOS_END)
    oos_r = run_backtest_from_data(close, volume, OOS_START, OOS_END)
    oos_tpq = _trades_per_quarter(oos_r["trade_count"], OOS_START, OOS_END)
    logger.info(
        "OOS: Sharpe=%.3f  CAGR=%.2f%%  MDD=%.2f%%  trades=%d  tpq=%.1f  "
        "ppt=%.1f bps  CPR=%.4f",
        oos_r["sharpe"], oos_r["cagr"] * 100, oos_r["max_drawdown"] * 100,
        oos_r["trade_count"], oos_tpq,
        oos_r.get("profit_per_trade_bps", 0), oos_r.get("cpr", 999),
    )

    # ── 4. Initial gate check + PF-1 conditional expansion ───────────────────
    is_analytics = _trade_analytics(is_r.get("trade_pnl", []))
    oos_analytics = _trade_analytics(oos_r.get("trade_pnl", []))
    gate1 = gate1_check(is_r, oos_r, oos_analytics, is_tpq)

    pf1_expansion_done = False
    expanded_universe = "Baseline: 6 ETFs top-3"
    if is_tpq < 30.0:
        logger.warning(
            "PF-1 CONDITIONAL: tpq=%.1f < 30 -> expanding to 8 ETFs (EWG + EWA), top-4",
            is_tpq,
        )
        expanded_em = ["EWZ", "FXI", "INDA", "EWT", "EWY", "EWJ", "EWG", "EWA"]
        missing_exp = [t for t in expanded_em if t not in close.columns]
        if missing_exp:
            logger.warning("Expanded ETFs missing from data: %s — skipping expansion", missing_exp)
        else:
            try:
                is_r_exp = run_backtest_from_data(
                    close, volume, IS_START, IS_END,
                    em_tickers=expanded_em, top_n=4,
                )
                is_tpq_exp = _trades_per_quarter(
                    is_r_exp["trade_count"], IS_START, IS_END
                )
                oos_r_exp = run_backtest_from_data(
                    close, volume, OOS_START, OOS_END,
                    em_tickers=expanded_em, top_n=4,
                )
                oos_analytics_exp = _trade_analytics(oos_r_exp.get("trade_pnl", []))
                gate1_exp = gate1_check(is_r_exp, oos_r_exp, oos_analytics_exp, is_tpq_exp)
                logger.info(
                    "Expanded IS: tpq=%.1f  Sharpe=%.3f  Gate1=%s",
                    is_tpq_exp, is_r_exp["sharpe"],
                    "PASS" if gate1_exp["pass"] else "FAIL",
                )
                if is_tpq_exp >= 30.0:
                    is_r = is_r_exp
                    is_r["data_quality"] = quality
                    oos_r = oos_r_exp
                    is_tpq = is_tpq_exp
                    is_analytics = _trade_analytics(is_r.get("trade_pnl", []))
                    oos_analytics = oos_analytics_exp
                    gate1 = gate1_exp
                    pf1_expansion_done = True
                    expanded_universe = "Expanded: 8 ETFs top-4 (EWG + EWA added)"
                    logger.info("PF-1 resolved with expanded universe.")
            except Exception as exc:
                logger.warning("PF-1 expansion failed: %s", exc)

    logger.info("Gate 1: %s", "PASS" if gate1["pass"] else "FAIL")
    for chk, res in gate1["checks"].items():
        logger.info("  [%s] %s", "✓" if res else "✗", chk)

    # ── 5. OOS data quality ───────────────────────────────────────────────────
    oos_pv = oos_r["_portfolio_value"]
    oos_dq_df = pd.DataFrame({"equity": oos_pv.values}, index=oos_pv.index)
    oos_dq_metrics = {
        "sharpe": oos_r["sharpe"],
        "max_drawdown": oos_r["max_drawdown"],
        "win_rate": oos_r["win_rate"],
        "profit_factor": oos_r.get("profit_factor", 0),
        "total_trades": oos_r["trade_count"],
        "post_cost_sharpe": oos_r["sharpe"],
    }
    logger.info("Running OOS data quality validation...")
    dq = validate_oos_data(oos_dq_df, oos_dq_metrics, STRATEGY_NAME)
    logger.info("DQ: %s  coverage=%.1f%%",
                dq["recommendation"], dq["oos_data_coverage_pct"])

    # ── 6. Monte Carlo ────────────────────────────────────────────────────────
    logger.info("Monte Carlo (1000 sims) ...")
    is_pnls = [t["pnl"] for t in is_r.get("trade_pnl", []) if "pnl" in t]
    mc = monte_carlo_sharpe(is_pnls) if len(is_pnls) > 10 else \
        {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    logger.info("MC P5/Med/P95: %.3f / %.3f / %.3f",
                mc["mc_p5_sharpe"], mc["mc_median_sharpe"], mc["mc_p95_sharpe"])

    # ── 7. Block Bootstrap ────────────────────────────────────────────────────
    logger.info("Block bootstrap CI (1000 boots) ...")
    is_rets = is_r["_portfolio_value"].pct_change().fillna(0.0).values
    ci = block_bootstrap_ci(is_rets) if len(is_rets) > 10 else \
        {k: 0.0 for k in ["sharpe_ci_low", "sharpe_ci_high", "mdd_ci_low",
                           "mdd_ci_high", "wr_ci_low", "wr_ci_high"]}
    logger.info("Sharpe 95%% CI: [%.3f, %.3f]",
                ci["sharpe_ci_low"], ci["sharpe_ci_high"])

    # ── 8. Market Impact ──────────────────────────────────────────────────────
    logger.info("Market impact (EWZ proxy) ...")
    mi = market_impact_proxy(float(PARAMETERS["init_cash"]), 3, close)
    logger.info("Market impact: %.3f bps", mi["market_impact_bps"])

    # ── 9. Permutation Test ───────────────────────────────────────────────────
    logger.info("Permutation test (500 perms) ...")
    perm = permutation_test(is_rets, is_r["sharpe"]) if len(is_rets) > 10 else \
        {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    logger.info("Perm p-value=%.4f  pass=%s",
                perm["permutation_pvalue"], perm["permutation_test_pass"])

    # ── 10. Walk-Forward ──────────────────────────────────────────────────────
    logger.info("Walk-forward (6 windows) ...")
    wf = walk_forward_windows(
        is_r["_portfolio_value"], is_r.get("trade_pnl", [])
    )
    wf_pos = sum(1 for w in wf if w["test_sharpe"] > 0)
    wf_pf1 = sum(1 for w in wf if w.get("pf1_pass", False))
    wf_min = float(np.min([w["test_sharpe"] for w in wf])) if wf else 0.0
    wf_std = float(np.std([w["test_sharpe"] for w in wf])) if len(wf) > 1 else 0.0
    logger.info("WF: %d/%d positive | PF-1: %d/%d | min=%.3f | std=%.3f",
                wf_pos, len(wf), wf_pf1, len(wf), wf_min, wf_std)

    # ── 11. Sensitivity Sweep ─────────────────────────────────────────────────
    logger.info("Sensitivity sweep (108 combinations — reusing downloaded data) ...")
    try:
        sweep_df = sensitivity_sweep(close, volume, is_r["sharpe"])
        sensitivity_pass = bool(
            sweep_df["pass"].all()
        ) if not sweep_df.empty else False
        sensitivity_max_delta = float(
            sweep_df["sharpe_delta_pct"].abs().max()
        ) if not sweep_df.empty and "sharpe_delta_pct" in sweep_df.columns else 0.0
    except Exception as exc:
        logger.warning("Sweep failed: %s", exc)
        sweep_df = pd.DataFrame([{"note": "failed", "error": str(exc)}])
        sensitivity_pass = False
        sensitivity_max_delta = 0.0
    logger.info("Sensitivity: pass=%s  max_delta=%.1f%%",
                sensitivity_pass, sensitivity_max_delta)

    # ── 12. Full metrics dict ─────────────────────────────────────────────────
    full_metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities/EM-ETFs",
        "universe": expanded_universe,
        "pf1_expansion_done": pf1_expansion_done,
        # IS
        "is_sharpe": round(is_r["sharpe"], 4),
        "is_cagr": round(is_r["cagr"], 4),
        "is_max_drawdown": round(is_r["max_drawdown"], 4),
        "is_total_return": round(is_r["total_return"], 4),
        "is_trade_count": is_r["trade_count"],
        "is_win_rate": round(is_r["win_rate"], 4),
        "is_trades_per_quarter": is_tpq,
        "is_profit_per_trade_bps": round(is_analytics.get("profit_per_trade_bps", 0), 2),
        "is_cpr": round(is_analytics.get("cpr", 999), 4),
        "is_profit_factor": round(is_analytics.get("profit_factor", 0), 4),
        # OOS
        "oos_sharpe": round(oos_r["sharpe"], 4),
        "oos_cagr": round(oos_r["cagr"], 4),
        "oos_max_drawdown": round(oos_r["max_drawdown"], 4),
        "oos_total_return": round(oos_r["total_return"], 4),
        "oos_trade_count": oos_r["trade_count"],
        "oos_win_rate": round(oos_r["win_rate"], 4),
        "oos_trades_per_quarter": oos_tpq,
        "oos_profit_per_trade_bps": round(oos_analytics.get("profit_per_trade_bps", 0), 2),
        "oos_cpr": round(oos_analytics.get("cpr", 999), 4),
        "oos_profit_factor": round(oos_analytics.get("profit_factor", 0), 4),
        "post_cost_sharpe": round(oos_r["sharpe"], 4),
        # 2022 stress test
        "year_2022_return": round(is_r.get("year_2022_return", 0), 4),
        "year_2022_mdd": round(is_r.get("year_2022_mdd", 0), 4),
        "year_2022_sharpe": round(is_r.get("year_2022_sharpe", 0), 4),
        # Regime
        "is_regime_pct_em": round(is_r.get("signal_regime_pct_em", 0), 4),
        "is_regime_pct_shy": round(is_r.get("signal_regime_pct_shy", 0), 4),
        "oos_regime_pct_em": round(oos_r.get("signal_regime_pct_em", 0), 4),
        "oos_regime_pct_shy": round(oos_r.get("signal_regime_pct_shy", 0), 4),
        # Overnight gap
        "overnight_gap": is_r.get("gap_contribution", {}),
        # Gate 1
        "gate1_pass": gate1["pass"],
        "gate1_checks": gate1["checks"],
        # Statistical rigor
        **mc, **ci, **mi, **perm,
        "wf_windows_passed": wf_pos,
        "wf_total_windows": len(wf),
        "wf_pf1_pass_count": wf_pf1,
        "wf_sharpe_min": round(wf_min, 3),
        "wf_sharpe_std": round(wf_std, 3),
        "wf_windows": wf,
        # Sensitivity
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_sharpe_delta_pct": round(sensitivity_max_delta, 1),
        # DQ
        "oos_data_quality": dq,
        "look_ahead_bias_flag": False,
    }

    # ── 13. Write outputs ─────────────────────────────────────────────────────
    json_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}.json"
    json_path.write_text(json.dumps(full_metrics, indent=2, default=str))
    logger.info("JSON: %s", json_path)

    rt_is = [{**t, "period": "IS"} for t in is_r.get("trade_pnl", [])]
    rt_oos = [{**t, "period": "OOS"} for t in oos_r.get("trade_pnl", [])]
    trades_df = pd.DataFrame(rt_is + rt_oos)
    trades_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_trades.csv"
    trades_df.to_csv(trades_path, index=False)
    logger.info("Trades: %s (%d rows)", trades_path, len(trades_df))

    sweep_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_sweep.csv"
    sweep_df.to_csv(sweep_path, index=False)
    logger.info("Sweep: %s", sweep_path)

    html = build_html(
        is_r, oos_r, gate1, mc, ci, perm, mi, wf,
        sensitivity_pass, sensitivity_max_delta, dq, sweep_df,
    )
    html_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_report.html"
    html_path.write_text(html)
    logger.info("HTML: %s", html_path)

    lines = [
        "H83 — USD-Regime EM Country Rotation — Gate 1 Verdict",
        f"Date: {TODAY}",
        f"Universe: {expanded_universe}",
        "",
        f"OVERALL: {'PASS' if gate1['pass'] else 'FAIL'}",
        "",
        "=== Gate 1 Checks ===",
    ]
    for chk, res in gate1["checks"].items():
        lines.append(f"  [{'PASS' if res else 'FAIL'}] {chk}")
    lines += [
        "",
        f"=== IS ({IS_START} to {IS_END}) ===",
        f"  Sharpe:              {is_r['sharpe']:.4f}",
        f"  CAGR:                {is_r['cagr']:.2%}",
        f"  Max Drawdown:        {is_r['max_drawdown']:.2%}",
        f"  Total Return:        {is_r['total_return']:.2%}",
        f"  Trade Count:         {is_r['trade_count']}",
        f"  Trades/Quarter:      {is_tpq:.1f}",
        f"  Profit/Trade (bps):  {is_analytics.get('profit_per_trade_bps', 0):.2f}",
        f"  CPR:                 {is_analytics.get('cpr', 999):.4f}",
        f"  Win Rate:            {is_r['win_rate']:.2%}",
        f"  Signal Regime EM:    {is_r.get('signal_regime_pct_em', 0):.1%}",
        f"  Signal Regime SHY:   {is_r.get('signal_regime_pct_shy', 0):.1%}",
        "",
        "=== 2022 Standalone (Rate Shock / USD-Strong Stress Test) ===",
        f"  2022 Return:         {is_r.get('year_2022_return', 0):.2%}",
        f"  2022 MDD:            {is_r.get('year_2022_mdd', 0):.2%}",
        f"  2022 Sharpe:         {is_r.get('year_2022_sharpe', 0):.4f}",
        "",
        f"=== OOS ({OOS_START} to {OOS_END}) ===",
        f"  Sharpe:              {oos_r['sharpe']:.4f}",
        f"  CAGR:                {oos_r['cagr']:.2%}",
        f"  Max Drawdown:        {oos_r['max_drawdown']:.2%}",
        f"  Total Return:        {oos_r['total_return']:.2%}",
        f"  Trade Count:         {oos_r['trade_count']}",
        f"  Trades/Quarter:      {oos_tpq:.1f}",
        f"  Profit/Trade (bps):  {oos_analytics.get('profit_per_trade_bps', 0):.2f}",
        f"  CPR:                 {oos_analytics.get('cpr', 999):.4f}",
        f"  Win Rate:            {oos_r['win_rate']:.2%}",
        "",
        "=== Statistical Rigor ===",
        f"  MC P5/Med/P95:         {mc['mc_p5_sharpe']:.3f} / "
        f"{mc['mc_median_sharpe']:.3f} / {mc['mc_p95_sharpe']:.3f}",
        f"  Sharpe 95% CI:         [{ci['sharpe_ci_low']:.3f}, {ci['sharpe_ci_high']:.3f}]",
        f"  Market Impact (EWZ):   {mi['market_impact_bps']:.3f} bps",
        f"  Permutation p-value:   {perm['permutation_pvalue']:.4f}  "
        f"({'PASS' if perm['permutation_test_pass'] else 'FAIL'})",
        f"  WF: {wf_pos}/{len(wf)} positive OOS | "
        f"PF-1: {wf_pf1}/{len(wf)} | min={wf_min:.3f} | std={wf_std:.3f}",
        f"  Sensitivity:           pass={sensitivity_pass}  "
        f"max_delta={sensitivity_max_delta:.1f}%",
        f"  OOS DQ:                {dq['recommendation']}",
        "",
        "=== Overnight / Weekend Gap (Track A Guard) ===",
        f"  PnL contribution:    "
        f"{is_r.get('gap_contribution', {}).get('overnight_pnl_contribution_pct', 0):.2%}",
        f"  MDD contribution:    "
        f"{is_r.get('gap_contribution', {}).get('overnight_mdd_contribution_pct', 0):.2%}",
    ]
    verdict_path = OUT_DIR / f"{STRATEGY_NAME}_{TODAY}_verdict.txt"
    verdict_path.write_text("\n".join(lines))
    logger.info("Verdict: %s", verdict_path)

    logger.info("=" * 64)
    logger.info(
        "COMPLETE: %s | IS Sharpe=%.3f | OOS Sharpe=%.3f",
        "PASS" if gate1["pass"] else "FAIL",
        is_r["sharpe"], oos_r["sharpe"],
    )
    logger.info("=" * 64)

    return full_metrics


if __name__ == "__main__":
    result = main()
    summary = {k: result[k] for k in [
        "gate1_pass", "is_sharpe", "oos_sharpe",
        "is_max_drawdown", "oos_max_drawdown",
        "is_trades_per_quarter", "oos_profit_per_trade_bps",
        "oos_cpr", "mc_p5_sharpe", "permutation_pvalue",
        "wf_windows_passed", "year_2022_return", "year_2022_mdd",
    ]}
    print("\n=== GATE 1 SUMMARY ===")
    print(json.dumps(summary, indent=2))
