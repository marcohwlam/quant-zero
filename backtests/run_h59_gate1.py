#!/repos/quant-zero/.venv/bin/python3
"""
Gate 1 Backtest Runner: H59 Opening Range Breakout (ORB)
QUA-147 | Backtest Runner Agent | 2026-06-09

IS: 2016-01-01 – 2021-12-31
OOS: 2022-01-01 – 2024-12-31
WF: 12m IS / 3m OOS rolling windows
PDT account: $25,001
"""

import json
import logging
import os
import sys
import warnings
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strategies.h59_opening_range_breakout import (
    PARAMETERS as H59_PARAMS,
    load_intraday_data,
    generate_daily_signals,
    compute_metrics,
    run_walk_forward,
)

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# ── Config ──────────────────────────────────────────────────────────────────────

IS_START  = "2016-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2024-12-31"

TODAY = str(date.today())
DATE_COMPACT = TODAY.replace("-", "")
BACKTESTS_DIR = Path(__file__).parent
OUTPUT_JSON    = BACKTESTS_DIR / f"H59_ORB_{DATE_COMPACT}.json"
OUTPUT_VERDICT = BACKTESTS_DIR / f"H59_ORB_{DATE_COMPACT}_verdict.txt"
OUTPUT_REPORT  = BACKTESTS_DIR / f"H59_ORB_{DATE_COMPACT}_report.html"

CANONICAL = {
    "or_window_min": 15,
    "r_mult": 2.0,
    "stop_buffer": 0.05,
    "exit_time_et": "15:55",
    "long_only": True,
    "min_or_width_pct": 0.0010,
    "account_size": 25001,
    "position_shares": 100,
    "fixed_cost_per_share": 0.005,
    "slippage_pct": 0.0005,
    "market_impact_k": 0.1,
    "sigma_window": 20,
    "adv_window": 20,
    "liquidity_threshold": 0.01,
}

# FOMC statement release dates 2016-2024 (hardcoded Fed calendar)
FOMC_DATES = [
    "2016-01-27","2016-03-16","2016-04-27","2016-06-15","2016-07-27",
    "2016-09-21","2016-11-02","2016-12-14",
    "2017-02-01","2017-03-15","2017-05-03","2017-06-14","2017-07-26",
    "2017-09-20","2017-11-01","2017-12-13",
    "2018-01-31","2018-03-21","2018-05-02","2018-06-13","2018-07-25",
    "2018-09-26","2018-11-08","2018-12-19",
    "2019-01-30","2019-03-20","2019-05-01","2019-06-19","2019-07-31",
    "2019-09-18","2019-10-30","2019-12-11",
    "2020-01-29","2020-03-03","2020-03-15","2020-04-29","2020-06-10",
    "2020-07-29","2020-09-16","2020-11-05","2020-12-16",
    "2021-01-27","2021-03-17","2021-04-28","2021-06-16","2021-07-28",
    "2021-09-22","2021-11-03","2021-12-15",
    "2022-01-26","2022-03-16","2022-05-04","2022-06-15","2022-07-27",
    "2022-09-21","2022-11-02","2022-12-14",
    "2023-02-01","2023-03-22","2023-05-03","2023-06-14","2023-07-26",
    "2023-09-20","2023-11-01","2023-12-13",
    "2024-01-31","2024-03-20","2024-05-01","2024-06-12","2024-07-31",
    "2024-09-18","2024-11-07","2024-12-18",
]


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _daily_returns_from_trades(trades_df: pd.DataFrame, start: str, end: str, account: float) -> np.ndarray:
    """Build daily return series from trade log (no-trade days = 0)."""
    if trades_df.empty:
        bdays = pd.bdate_range(start, end)
        return np.zeros(len(bdays))
    daily_pnl = trades_df.groupby("date")["pnl_net"].sum()
    bdays = pd.bdate_range(start, end)
    all_dates = pd.Index([str(d.date()) for d in bdays])
    return (daily_pnl.reindex(all_dates, fill_value=0.0) / account).values


def _slice_df(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    s = pd.Timestamp(start, tz=ET)
    e = pd.Timestamp(end, tz=ET).replace(hour=23, minute=59)
    return df[(df.index >= s) & (df.index <= e)]


def _risk_series(df: pd.DataFrame, sigma_window: int = 20, adv_window: int = 20):
    daily_close = df.groupby(df.index.normalize())["close"].last()
    daily_volume = df.groupby(df.index.normalize())["volume"].sum()
    daily_sigma = daily_close.pct_change().rolling(sigma_window).std().shift(1)
    daily_adv = daily_volume.rolling(adv_window).mean().shift(1)
    return daily_sigma, daily_adv


# ── Statistical Functions ────────────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, account: float, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    sharpes = []
    n = len(trade_pnls)
    if n < 2:
        return {"p5": 0.0, "p50": 0.0, "p95": 0.0, "n_sims": 0}
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=n, replace=True)
        ret = sample / account
        s = float(ret.mean() / (ret.std() + 1e-8) * np.sqrt(252))
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "p5":  round(float(np.percentile(arr, 5)), 4),
        "p50": round(float(np.median(arr)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
        "n_sims": n_sims,
    }


def permutation_p_value(daily_rets: np.ndarray, n_perm: int = 1000) -> float:
    np.random.seed(42)
    if len(daily_rets) < 2:
        return 1.0
    obs = float(daily_rets.mean() / (daily_rets.std() + 1e-8) * np.sqrt(252))
    perm = [float(np.random.permutation(daily_rets).mean() /
                  (np.random.permutation(daily_rets).std() + 1e-8) * np.sqrt(252))
            for _ in range(n_perm)]
    # recompute cleanly
    perm_sharpes = []
    for _ in range(n_perm):
        s = np.random.permutation(daily_rets)
        perm_sharpes.append(float(s.mean() / (s.std() + 1e-8) * np.sqrt(252)))
    return round(float((np.array(perm_sharpes) >= obs).mean()), 4)


def bootstrap_sharpe_ci(daily_rets: np.ndarray, n_boot: int = 1000) -> dict:
    np.random.seed(42)
    T = len(daily_rets)
    if T < 4:
        return {"lower": 0.0, "upper": 0.0, "ci": 0.95}
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)
    boot = []
    for _ in range(n_boot):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([daily_rets[s:s + block_len] for s in starts])[:T]
        boot.append(float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)))
    arr = np.array(boot)
    return {
        "lower": round(float(np.percentile(arr, 2.5)), 4),
        "upper": round(float(np.percentile(arr, 97.5)), 4),
        "ci": 0.95,
    }


def wf_sharpe_variance(oos_sharpes: list) -> dict:
    arr = np.array(oos_sharpes) if oos_sharpes else np.array([0.0])
    return {
        "std": round(float(arr.std()), 4),
        "min": round(float(arr.min()), 4),
    }


# ── Regime Split (VIX) ───────────────────────────────────────────────────────────

def run_regime_split(all_trades: pd.DataFrame) -> dict:
    if all_trades.empty:
        return {"error": "no_trades"}
    logger.info("Fetching ^VIX daily data for regime split...")
    vix = yf.download("^VIX", start=IS_START, end=OOS_END, auto_adjust=True, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    if vix.empty or "Close" not in vix.columns:
        return {"error": "vix_unavailable"}
    vix_close = vix["Close"].shift(1).dropna()

    def get_prior_vix(date_str):
        ts = pd.Timestamp(date_str)
        candidates = vix_close.index[vix_close.index <= ts]
        if len(candidates) == 0:
            return None
        return float(vix_close.loc[candidates[-1]])

    trades = all_trades.copy()
    trades["prior_vix"] = trades["date"].apply(get_prior_vix)
    trades = trades.dropna(subset=["prior_vix"])

    def regime_stats(df_r, label):
        if df_r.empty:
            return {"label": label, "n_trades": 0, "win_rate": None, "avg_trade_gross_bps": None, "trade_sharpe": None}
        n = len(df_r)
        wins = (df_r["pnl_gross"] > 0).sum()
        notional = df_r["entry_price"] * CANONICAL["position_shares"]
        gross_bps = float((df_r["pnl_gross"] / notional * 10000).mean())
        pnl_arr = df_r["pnl_net"].values
        sharpe = float(pnl_arr.mean() / (pnl_arr.std() + 1e-8) * np.sqrt(252))
        return {
            "label": label,
            "n_trades": int(n),
            "win_rate": round(float(wins / n), 4),
            "avg_trade_gross_bps": round(gross_bps, 2),
            "trade_sharpe": round(sharpe, 4),
        }

    return {
        "high_vol_vix_gte_20": regime_stats(trades[trades["prior_vix"] >= 20], "high_vol"),
        "low_vol_vix_lt_15":   regime_stats(trades[trades["prior_vix"] < 15],  "low_vol"),
        "mid_vol_vix_15_20":   regime_stats(trades[(trades["prior_vix"] >= 15) & (trades["prior_vix"] < 20)], "mid_vol"),
    }


# ── FOMC Exclusion ────────────────────────────────────────────────────────────────

def run_fomc_exclusion(all_trades: pd.DataFrame) -> dict:
    if all_trades.empty:
        return {"error": "no_trades"}
    fomc_set = set(FOMC_DATES)
    is_tr  = all_trades[all_trades["date"] <= IS_END]
    oos_tr = all_trades[all_trades["date"] >  IS_END]
    is_ex  = is_tr[~is_tr["date"].isin(fomc_set)]
    oos_ex = oos_tr[~oos_tr["date"].isin(fomc_set)]

    bm_is  = compute_metrics(is_tr,  IS_START,  IS_END,  CANONICAL["account_size"])
    bm_oos = compute_metrics(oos_tr, OOS_START, OOS_END, CANONICAL["account_size"])
    ex_is  = compute_metrics(is_ex,  IS_START,  IS_END,  CANONICAL["account_size"])
    ex_oos = compute_metrics(oos_ex, OOS_START, OOS_END, CANONICAL["account_size"])

    return {
        "fomc_days_in_sample": len(fomc_set & set(all_trades["date"].unique())),
        "baseline_is_sharpe":  bm_is["sharpe"],
        "baseline_oos_sharpe": bm_oos["sharpe"],
        "ex_fomc_is_sharpe":   ex_is["sharpe"],
        "ex_fomc_oos_sharpe":  ex_oos["sharpe"],
        "is_sharpe_delta":  round(ex_is["sharpe"]  - bm_is["sharpe"],  4),
        "oos_sharpe_delta": round(ex_oos["sharpe"] - bm_oos["sharpe"], 4),
    }


# ── Sensitivity Surface (3×3) ─────────────────────────────────────────────────────

def run_sensitivity_surface(df_full: pd.DataFrame, daily_sigma, daily_adv) -> dict:
    or_windows = [5, 15, 30]
    r_mults    = [1.5, 2.0, 2.5]
    df_oos = _slice_df(df_full, OOS_START, OOS_END)
    surface, overfit_flags = [], []
    for orw in or_windows:
        row = []
        for rm in r_mults:
            p = CANONICAL.copy()
            p["or_window_min"] = orw
            p["r_mult"] = rm
            try:
                tr = generate_daily_signals(df_oos, p, daily_sigma, daily_adv, "SPY")
                m  = compute_metrics(tr, OOS_START, OOS_END, CANONICAL["account_size"])
                s  = m["sharpe"]
                if s > 1.5:
                    overfit_flags.append({"or_window_min": orw, "r_mult": rm, "oos_sharpe": s})
            except Exception as e:
                logger.warning("Sensitivity error (orw=%d rm=%.1f): %s", orw, rm, e)
                s = None
            row.append(round(s, 4) if s is not None else None)
        surface.append(row)
    return {
        "or_window_min_values": or_windows,
        "r_mult_values": r_mults,
        "oos_sharpe_matrix": surface,
        "overfit_outliers": overfit_flags,
        "note": "surface[i][j] = OOS Sharpe for or_windows[i] x r_mults[j]",
    }


# ── Gate 1 Verdict ────────────────────────────────────────────────────────────────

def gate1_verdict(res: dict) -> dict:
    checks = {
        "is_sharpe_gt_1":           res.get("is_sharpe", 0) > 1.0,
        "oos_sharpe_gt_07":         res.get("oos_sharpe", 0) > 0.7,
        "mdd_lt_20pct":             abs(res.get("is_mdd", -1.0)) < 0.20,
        "is_trades_gte_100":        res.get("is_trades", 0) >= 100,
        "wf_pass_rate_gte_50pct":   res.get("wf_pass_rate", 0) >= 0.50,
        "permutation_p_lte_05":     res.get("permutation_p", 1.0) <= 0.05,
        "mc_p5_sharpe_gt_0":        res.get("mc_p5_sharpe", -1.0) > 0.0,
        "wf_trade_count_ok":        res.get("wf_min_trade_count_div4", 0) >= 30,
    }
    n_pass  = sum(checks.values())
    n_total = len(checks)
    all_pass = all(checks.values())
    verdict = "PASS" if all_pass else ("CONDITIONAL PASS" if n_pass >= n_total - 2 else "FAIL")
    return {"passed": all_pass, "verdict": verdict, "checks": checks,
            "pass_count": n_pass, "total_checks": n_total}


# ── HTML Report ────────────────────────────────────────────────────────────────────

def generate_html_report(res: dict, vd: dict) -> str:
    v_color = "#28a745" if vd["verdict"] == "PASS" else ("#ffc107" if "CONDITIONAL" in vd["verdict"] else "#dc3545")

    wf_rows = ""
    for w in res.get("walk_forward_windows", []):
        os_ = w["oos_metrics"]["sharpe"]
        is_ = w["is_metrics"]["sharpe"]
        flag = "&#10003;" if os_ >= 0.5 else "&#10007;"
        wf_rows += f"<tr><td>{w['is_start']}</td><td>{w['is_end']}</td><td>{w['oos_start']}</td><td>{w['oos_end']}</td><td>{is_:.3f}</td><td>{os_:.3f}</td><td>{w['is_metrics']['n_trades']}</td><td>{flag}</td></tr>\n"

    regime_rows = ""
    regime = res.get("regime_split", {})
    for k, rv in regime.items():
        if isinstance(rv, dict) and "n_trades" in rv:
            regime_rows += f"<tr><td>{k}</td><td>{rv.get('n_trades','-')}</td><td>{rv.get('win_rate','-')}</td><td>{rv.get('avg_trade_gross_bps','-')}</td><td>{rv.get('trade_sharpe','-')}</td></tr>\n"

    sens = res.get("sensitivity_surface", {})
    r_mults  = sens.get("r_mult_values", [])
    or_wins  = sens.get("or_window_min_values", [])
    matrix   = sens.get("oos_sharpe_matrix", [])
    sens_hdr = "".join(f"<th>r_mult={rm}</th>" for rm in r_mults)
    sens_rows = ""
    for i, orw in enumerate(or_wins):
        sens_rows += f"<tr><td>OR={orw}m</td>"
        for j in range(len(r_mults)):
            val = matrix[i][j] if i < len(matrix) and j < len(matrix[i]) else "-"
            bg = " style='background:#d4edda'" if val and val > 0.7 else (" style='background:#f8d7da'" if val is not None and val < 0 else "")
            sens_rows += f"<td{bg}>{val}</td>"
        sens_rows += "</tr>\n"

    checks_rows = ""
    for c, p in vd["checks"].items():
        icon = "&#10003;" if p else "&#10007;"
        color = "green" if p else "red"
        val = res.get(c.replace("_gt_", ">").replace("_lte_", "<=").replace("_gte_", ">="), "")
        checks_rows += f"<tr><td>{c}</td><td style='color:{color};font-weight:bold'>{icon}</td></tr>\n"

    fomc = res.get("fomc_exclusion", {})

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<title>H59 ORB Gate 1 — {res.get('date', TODAY)}</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1100px;margin:0 auto;padding:20px}}
h1{{color:#333}}h2{{color:#555;border-bottom:1px solid #ccc;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}
th,td{{border:1px solid #ddd;padding:7px;text-align:left}}th{{background:#f4f4f4}}
.badge{{padding:10px 22px;border-radius:6px;font-size:1.4em;font-weight:bold;color:#fff;background:{v_color};display:inline-block}}
</style></head>
<body>
<h1>H59 Opening Range Breakout &mdash; Gate 1 Report</h1>
<p>Date: {res.get('date', TODAY)} &nbsp;|&nbsp; Ticker: SPY &nbsp;|&nbsp; PDT Account: $25,001</p>
<div class="badge">Gate 1: {vd['verdict']}</div>
<p>{vd['pass_count']}/{vd['total_checks']} criteria passed</p>

<h2>Core IS/OOS Metrics (SPY, Canonical Params)</h2>
<table>
<tr><th>Metric</th><th>IS (2016&ndash;2021)</th><th>OOS (2022&ndash;2024)</th><th>Gate 1 Threshold</th></tr>
<tr><td>Sharpe Ratio</td><td>{res.get('is_sharpe','N/A')}</td><td>{res.get('oos_sharpe','N/A')}</td><td>&gt;1.0 / &gt;0.7</td></tr>
<tr><td>Max Drawdown</td><td>{res.get('is_mdd',0):.2%}</td><td>{res.get('oos_mdd',0):.2%}</td><td>&lt;20% IS</td></tr>
<tr><td>Win Rate</td><td>{res.get('win_rate',0):.2%}</td><td>&mdash;</td><td>&gt;50%</td></tr>
<tr><td>Profit Factor</td><td>{res.get('profit_factor','N/A')}</td><td>&mdash;</td><td>&gt;1.0</td></tr>
<tr><td>Trade Count</td><td>{res.get('is_trades',0)}</td><td>{res.get('oos_trades',0)}</td><td>&ge;100 IS</td></tr>
<tr><td>Avg Gross (bps)</td><td>{res.get('avg_trade_gross_bps','N/A')}</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>Avg Net (bps)</td><td>{res.get('avg_trade_net_bps','N/A')}</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>QQQ OOS Sharpe</td><td colspan="2">{res.get('qqq_oos_sharpe','N/A')}</td><td>Robustness</td></tr>
</table>

<h2>Statistical Rigor</h2>
<table>
<tr><th>Test</th><th>Value</th><th>Threshold</th><th>Result</th></tr>
<tr><td>MC p5 Sharpe</td><td>{res.get('mc_p5_sharpe','N/A')}</td><td>&gt;0.0</td><td>{"&#10003;" if res.get('mc_p5_sharpe',-1)>0 else "&#10007;"}</td></tr>
<tr><td>MC p50 Sharpe</td><td>{res.get('mc_p50_sharpe','N/A')}</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>MC p95 Sharpe</td><td>{res.get('mc_p95_sharpe','N/A')}</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>Permutation p-value</td><td>{res.get('permutation_p','N/A')}</td><td>&le;0.05</td><td>{"&#10003;" if res.get('permutation_p',1)<=0.05 else "&#10007;"}</td></tr>
<tr><td>Bootstrap CI lower</td><td>{res.get('bootstrap_ci',{}).get('lower','N/A')}</td><td>&gt;0</td><td>{"&#10003;" if res.get('bootstrap_ci',{}).get('lower',-1)>0 else "&#10007;"}</td></tr>
<tr><td>Bootstrap CI upper</td><td>{res.get('bootstrap_ci',{}).get('upper','N/A')}</td><td>&mdash;</td><td>&mdash;</td></tr>
<tr><td>WF Sharpe Std</td><td>{res.get('wf_sharpe_std','N/A')}</td><td>lower = more consistent</td><td>&mdash;</td></tr>
<tr><td>WF Sharpe Min</td><td>{res.get('wf_sharpe_min','N/A')}</td><td>&gt;0 preferred</td><td>{"&#10003;" if res.get('wf_sharpe_min',-1)>0 else "&#9888;"}</td></tr>
</table>

<h2>Walk-Forward Stability (12m IS / 3m OOS)</h2>
<p>Pass rate (OOS Sharpe &ge; 0.5): <b>{res.get('wf_pass_rate',0):.1%}</b> &nbsp;|&nbsp;
Windows: {res.get('wf_n_windows',0)} &nbsp;|&nbsp;
Min IS trades / 4: {res.get('wf_min_trade_count_div4','N/A')} (threshold &ge; 30)</p>
<table>
<tr><th>IS Start</th><th>IS End</th><th>OOS Start</th><th>OOS End</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>IS Trades</th><th>Pass (&ge;0.5)</th></tr>
{wf_rows}
</table>

<h2>Regime Split (Prior-Day VIX)</h2>
<table>
<tr><th>Regime</th><th>Trades</th><th>Win Rate</th><th>Avg Gross (bps)</th><th>Trade Sharpe</th></tr>
{regime_rows}
</table>

<h2>FOMC Exclusion Test</h2>
<table>
<tr><th>Metric</th><th>Baseline</th><th>Ex-FOMC</th><th>Delta</th></tr>
<tr><td>IS Sharpe</td><td>{fomc.get('baseline_is_sharpe','N/A')}</td><td>{fomc.get('ex_fomc_is_sharpe','N/A')}</td><td>{fomc.get('is_sharpe_delta','N/A')}</td></tr>
<tr><td>OOS Sharpe</td><td>{fomc.get('baseline_oos_sharpe','N/A')}</td><td>{fomc.get('ex_fomc_oos_sharpe','N/A')}</td><td>{fomc.get('oos_sharpe_delta','N/A')}</td></tr>
</table>

<h2>Sensitivity Surface (3&times;3 OOS Sharpe)</h2>
<p>Rows: or_window_min &isin; {or_wins} | Columns: r_mult &isin; {r_mults}</p>
<table>
<tr><th>OR Window \\ R-mult</th>{sens_hdr}</tr>
{sens_rows}
</table>
{f"<p style='color:orange'>&#9888; Overfit outliers (OOS Sharpe &gt; 1.5): {sens.get('overfit_outliers',[])}</p>" if sens.get('overfit_outliers') else ""}

<h2>Gate 1 Criteria</h2>
<table>
<tr><th>Criterion</th><th>Result</th></tr>
{checks_rows}
</table>

<p style="color:#888;font-size:0.85em">Backtest Runner Agent &bull; QUA-147 &bull; {TODAY} &bull; PDT account $25,001</p>
</body></html>"""


# ── Verdict TXT ────────────────────────────────────────────────────────────────────

def generate_verdict_txt(res: dict, vd: dict) -> str:
    fomc = res.get("fomc_exclusion", {})
    bci  = res.get("bootstrap_ci", {})
    lines = [
        "H59 Opening Range Breakout — Gate 1 Verdict",
        f"Date: {res.get('date', TODAY)}",
        f"Strategy: H59 ORB | Ticker: SPY | PDT Account: $25,001",
        f"IS: {IS_START} -> {IS_END}  |  OOS: {OOS_START} -> {OOS_END}",
        "",
        "IS METRICS:",
        f"  Sharpe:           {res.get('is_sharpe','N/A')}",
        f"  Max Drawdown:     {res.get('is_mdd',0):.2%}",
        f"  Win Rate:         {res.get('win_rate',0):.2%}",
        f"  Profit Factor:    {res.get('profit_factor','N/A')}",
        f"  Trade Count:      {res.get('is_trades',0)}",
        f"  Avg Gross (bps):  {res.get('avg_trade_gross_bps','N/A')}",
        f"  Avg Net (bps):    {res.get('avg_trade_net_bps','N/A')}",
        "",
        "OOS METRICS:",
        f"  Sharpe:           {res.get('oos_sharpe','N/A')}",
        f"  Max Drawdown:     {res.get('oos_mdd',0):.2%}",
        f"  Trade Count:      {res.get('oos_trades',0)}",
        "",
        "STATISTICAL RIGOR:",
        f"  MC p5 Sharpe:     {res.get('mc_p5_sharpe','N/A')}",
        f"  MC p50 Sharpe:    {res.get('mc_p50_sharpe','N/A')}",
        f"  MC p95 Sharpe:    {res.get('mc_p95_sharpe','N/A')}",
        f"  Permutation p:    {res.get('permutation_p','N/A')}",
        f"  Bootstrap 95% CI: [{bci.get('lower','N/A')}, {bci.get('upper','N/A')}]",
        f"  WF Sharpe Std:    {res.get('wf_sharpe_std','N/A')}",
        f"  WF Sharpe Min:    {res.get('wf_sharpe_min','N/A')}",
        "",
        f"WALK-FORWARD: {res.get('wf_n_windows_passed',0)}/{res.get('wf_n_windows',0)} windows passing OOS Sharpe >= 0.5",
        f"WF Pass Rate:       {res.get('wf_pass_rate',0):.1%}",
        f"WF Min Trades / 4:  {res.get('wf_min_trade_count_div4','N/A')} (threshold >= 30)",
        "",
        "QQQ ROBUSTNESS:",
        f"  QQQ OOS Sharpe:   {res.get('qqq_oos_sharpe','N/A')}",
        "",
        "FOMC EXCLUSION:",
        f"  FOMC days in sample: {fomc.get('fomc_days_in_sample','N/A')}",
        f"  Baseline IS Sharpe:  {fomc.get('baseline_is_sharpe','N/A')}",
        f"  Ex-FOMC IS Sharpe:   {fomc.get('ex_fomc_is_sharpe','N/A')}  (delta: {fomc.get('is_sharpe_delta','N/A')})",
        f"  Baseline OOS Sharpe: {fomc.get('baseline_oos_sharpe','N/A')}",
        f"  Ex-FOMC OOS Sharpe:  {fomc.get('ex_fomc_oos_sharpe','N/A')}  (delta: {fomc.get('oos_sharpe_delta','N/A')})",
        "",
        "GATE 1 CRITERIA:",
    ]
    for criterion, passed in vd["checks"].items():
        status = "PASS" if passed else "FAIL"
        lines.append(f"  [{status}] {criterion}")
    lines.extend([
        "",
        f"FINAL VERDICT: {vd['verdict']}",
        f"Passed: {vd['pass_count']}/{vd['total_checks']} criteria",
        "",
        "PDT COMPLIANCE: account_size=$25,001 (PDT-compliant).",
        "DATA: Alpaca 1-min OHLCV, RTH 09:30-16:00 ET, adjustment='all'.",
        "COSTS: $0.005/share fixed + 0.05% slippage + 0.1*sigma*sqrt(Q/ADV) market impact.",
        "SEE: QUA-147 for Engineering Director commentary.",
    ])
    return "\n".join(lines)


# ── Main ────────────────────────────────────────────────────────────────────────────

def run_gate1():
    logger.info("=" * 70)
    logger.info("H59 ORB Gate 1 Backtest  |  IS:%s->%s  OOS:%s->%s", IS_START, IS_END, OOS_START, OOS_END)
    logger.info("=" * 70)

    # 1. Load SPY full-window intraday data
    logger.info("[1/9] Loading SPY 1-min RTH bars %s -> %s ...", IS_START, OOS_END)
    df_spy = load_intraday_data("SPY", IS_START, OOS_END)
    daily_sigma_spy, daily_adv_spy = _risk_series(df_spy)
    logger.info("SPY: %d bars, %d trading days", len(df_spy), df_spy.index.normalize().nunique())

    # 2. IS/OOS canonical backtest
    logger.info("[2/9] IS/OOS backtest (canonical params, SPY)...")
    df_is  = _slice_df(df_spy, IS_START, IS_END)
    df_oos = _slice_df(df_spy, OOS_START, OOS_END)
    is_trades  = generate_daily_signals(df_is,  CANONICAL, daily_sigma_spy, daily_adv_spy, "SPY")
    oos_trades = generate_daily_signals(df_oos, CANONICAL, daily_sigma_spy, daily_adv_spy, "SPY")
    is_m  = compute_metrics(is_trades,  IS_START,  IS_END,  CANONICAL["account_size"])
    oos_m = compute_metrics(oos_trades, OOS_START, OOS_END, CANONICAL["account_size"])
    logger.info("IS  Sharpe=%.4f  MDD=%.2f%%  Trades=%d  WinRate=%.1f%%",
                is_m["sharpe"], is_m["max_drawdown"]*100, is_m["n_trades"], is_m["win_rate"]*100)
    logger.info("OOS Sharpe=%.4f  MDD=%.2f%%  Trades=%d",
                oos_m["sharpe"], oos_m["max_drawdown"]*100, oos_m["n_trades"])

    # 3. Walk-forward
    logger.info("[3/9] Walk-forward (12m IS / 3m OOS)...")
    wf_windows = run_walk_forward(df_spy, CANONICAL, is_months=12, oos_months=3, ticker="SPY")
    wf_oos_sharpes = [w["oos_metrics"]["sharpe"] for w in wf_windows if w["oos_metrics"]["n_trades"] > 0]
    wf_n_pass   = sum(1 for s in wf_oos_sharpes if s >= 0.5)
    wf_pass_rate = wf_n_pass / len(wf_oos_sharpes) if wf_oos_sharpes else 0.0
    wf_mean = np.mean(wf_oos_sharpes) if wf_oos_sharpes else 0.0
    wf_sd   = np.std(wf_oos_sharpes) if len(wf_oos_sharpes) > 1 else 0.0
    wf_outliers = [{"window_idx": i, "oos_sharpe": s}
                   for i, s in enumerate(wf_oos_sharpes) if wf_sd > 0 and s > wf_mean + 2.5 * wf_sd]
    wf_is_counts = [w["is_metrics"]["n_trades"] for w in wf_windows]
    wf_min_tc    = min(wf_is_counts) if wf_is_counts else 0
    wf_min_tc_d4 = wf_min_tc // 4
    wf_var = wf_sharpe_variance(wf_oos_sharpes)
    logger.info("WF: %d windows | pass_rate=%.1f%% | wf_min_trade_div4=%d",
                len(wf_windows), wf_pass_rate * 100, wf_min_tc_d4)

    # 4. Statistical rigor
    logger.info("[4/9] Statistical rigor (MC, permutation, bootstrap)...")
    acct = CANONICAL["account_size"]
    if not is_trades.empty:
        trade_pnls = is_trades["pnl_net"].values
        daily_rets = _daily_returns_from_trades(is_trades, IS_START, IS_END, acct)
        mc     = monte_carlo_sharpe(trade_pnls, acct)
        perm_p = permutation_p_value(daily_rets)
        bs_ci  = bootstrap_sharpe_ci(daily_rets)
    else:
        mc     = {"p5": 0.0, "p50": 0.0, "p95": 0.0, "n_sims": 0}
        perm_p = 1.0
        bs_ci  = {"lower": 0.0, "upper": 0.0, "ci": 0.95}
    logger.info("MC p5=%.4f p50=%.4f | perm_p=%.4f | CI=[%.4f,%.4f]",
                mc["p5"], mc["p50"], perm_p, bs_ci["lower"], bs_ci["upper"])

    # 5. Regime split (VIX)
    logger.info("[5/9] Regime split (prior-day VIX)...")
    all_trades = pd.concat([is_trades, oos_trades], ignore_index=True) if not is_trades.empty else oos_trades.copy()
    regime = run_regime_split(all_trades)

    # 6. FOMC exclusion
    logger.info("[6/9] FOMC exclusion test...")
    fomc = run_fomc_exclusion(all_trades)

    # 7. Sensitivity surface
    logger.info("[7/9] Sensitivity surface (3x3 or_window_min x r_mult)...")
    sensitivity = run_sensitivity_surface(df_spy, daily_sigma_spy, daily_adv_spy)

    # 8. QQQ robustness (OOS only)
    logger.info("[8/9] QQQ robustness (OOS Sharpe)...")
    df_qqq = load_intraday_data("QQQ", OOS_START, OOS_END)
    dsig_qqq, dadv_qqq = _risk_series(df_qqq)
    df_qqq_oos  = _slice_df(df_qqq, OOS_START, OOS_END)
    qqq_trades  = generate_daily_signals(df_qqq_oos, CANONICAL, dsig_qqq, dadv_qqq, "QQQ")
    qqq_oos_m   = compute_metrics(qqq_trades, OOS_START, OOS_END, acct)
    qqq_oos_sharpe = qqq_oos_m["sharpe"]
    logger.info("QQQ OOS Sharpe: %.4f", qqq_oos_sharpe)

    # 9. Assemble & verdict
    logger.info("[9/9] Gate 1 verdict...")
    results = {
        "strategy_name": "H59_ORB",
        "strategy": "H59 Opening Range Breakout",
        "date": TODAY,
        "ticker": "SPY",
        "asset_class": "equities",
        "is_period": f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "pdt_compliance": "account_size=$25,001",
        "params": CANONICAL,
        # Core
        "is_sharpe":  is_m["sharpe"],
        "oos_sharpe": oos_m["sharpe"],
        "is_mdd":  is_m["max_drawdown"],
        "oos_mdd": oos_m["max_drawdown"],
        "is_trades":  is_m["n_trades"],
        "oos_trades": oos_m["n_trades"],
        "win_rate":             is_m["win_rate"],
        "profit_factor":        is_m["profit_factor"],
        "avg_trade_gross_bps":  is_m["avg_trade_gross_bps"],
        "avg_trade_net_bps":    is_m["avg_trade_net_bps"],
        "is_metrics":  is_m,
        "oos_metrics": oos_m,
        # Stats
        "mc_p5_sharpe":  mc["p5"],
        "mc_p50_sharpe": mc["p50"],
        "mc_p95_sharpe": mc["p95"],
        "monte_carlo":   mc,
        "permutation_p": perm_p,
        "bootstrap_ci":  bs_ci,
        "wf_sharpe_std": wf_var["std"],
        "wf_sharpe_min": wf_var["min"],
        # WF
        "wf_n_windows":           len(wf_windows),
        "wf_n_windows_passed":    wf_n_pass,
        "wf_pass_rate":           round(wf_pass_rate, 4),
        "wf_oos_sharpes":         wf_oos_sharpes,
        "wf_outlier_windows":     wf_outliers,
        "wf_min_trade_count_div4": wf_min_tc_d4,
        "walk_forward_windows":   wf_windows,
        # Regime / FOMC / Sensitivity / QQQ
        "regime_split":       regime,
        "fomc_exclusion":     fomc,
        "sensitivity_surface": sensitivity,
        "qqq_oos_sharpe":     qqq_oos_sharpe,
        "qqq_oos_metrics":    qqq_oos_m,
    }

    vd = gate1_verdict(results)
    results["gate1_verdict"] = vd
    results["gate1_pass"] = vd["passed"]

    logger.info("=" * 70)
    logger.info("VERDICT: %s  (%d/%d)", vd["verdict"], vd["pass_count"], vd["total_checks"])
    for c, p in vd["checks"].items():
        logger.info("  [%s] %s", "PASS" if p else "FAIL", c)
    logger.info("=" * 70)

    # Save artifacts
    with open(OUTPUT_JSON, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("JSON:    %s", OUTPUT_JSON)

    verdict_txt = generate_verdict_txt(results, vd)
    with open(OUTPUT_VERDICT, "w") as f:
        f.write(verdict_txt)
    logger.info("Verdict: %s", OUTPUT_VERDICT)

    html = generate_html_report(results, vd)
    with open(OUTPUT_REPORT, "w") as f:
        f.write(html)
    logger.info("Report:  %s", OUTPUT_REPORT)

    return results, vd


if __name__ == "__main__":
    run_gate1()
