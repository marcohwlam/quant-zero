"""
Gate 1 Backtest Runner: H45 NR7 Narrow Range Volatility Compression Breakout
QUA-404 — Strategy Coder Agent

Generates:
  backtests/H45_NR7VolatilityBreakout_YYYY-MM-DD.json
  backtests/H45_NR7VolatilityBreakout_YYYY-MM-DD_report.html
  backtests/H45_NR7VolatilityBreakout_YYYY-MM-DD_sweep.csv
  backtests/H45_NR7VolatilityBreakout_YYYY-MM-DD_trades.csv
  backtests/H45_NR7VolatilityBreakout_YYYY-MM-DD_verdict.txt

Track A Gate 1 checks (criteria.md v2.7 + kpi-daily-weekly.md v1.0):
  Net OOS Sharpe > 0.7            | Net profit per trade > 15 bps
  IS MDD < 20% (Gate 7 < 30%)     | IS trade count/quarter > 30
  CPR < 0.25                       | WF OOS Sharpe > 0: >= 3/4 windows
  Composite Score CS >= 0.60       | Permutation p < 0.05
  DSR z-score > 0

Walk-forward: 4 windows (4-year IS / 6-month OOS per WF_SPECS)
Parameter sweep: trend_ma [150,200,250] x hold_days [3,5,7] x atr_stop_mult [1.5,2.0,2.5,3.0] = 36 combos
"""

import sys
import json
import warnings
import datetime
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))

from h45_nr7_volatility_compression_breakout import (  # noqa: E402
    download_data, compute_indicators, simulate, compute_metrics,
    compute_overnight_gap_stats, PARAMETERS, TRADING_DAYS_PER_YEAR,
)

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ── Constants ──────────────────────────────────────────────────────────────────

STRATEGY_NAME = "H45_NR7VolatilityBreakout"
DATE_STR = datetime.date.today().isoformat()

IS_START = "2005-01-01"
IS_END = "2018-12-31"
OOS_START = "2019-01-01"
OOS_END = "2026-06-24"

BACKTESTS_DIR = _REPO / "backtests"
BACKTESTS_DIR.mkdir(exist_ok=True)
PREFIX = BACKTESTS_DIR / f"{STRATEGY_NAME}_{DATE_STR}"

# Walk-forward: 4-year IS / 6-month OOS (per QUA-404 spec)
WF_SPECS = [
    ("2009-01-01", "2012-12-31", "2013-01-01", "2013-06-30"),
    ("2011-01-01", "2014-12-31", "2015-01-01", "2015-06-30"),
    ("2013-01-01", "2016-12-31", "2017-01-01", "2017-06-30"),
    ("2015-01-01", "2018-12-31", "2019-01-01", "2019-06-30"),
]

# Parameter sweep grid (nr7_lookback fixed at 7 — Crabel canonical)
SWEEP_GRID = {
    "trend_ma": [150, 200, 250],
    "hold_days": [3, 5, 7],
    "atr_stop_mult": [1.5, 2.0, 2.5, 3.0],
}


# ── Statistical Utilities ──────────────────────────────────────────────────────

def _sharpe(equity: pd.Series) -> float:
    ret = equity.pct_change().fillna(0.0).values
    return float(ret.mean() / ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR)) if (len(ret) > 2 and ret.std() > 0) else 0.0


def _mdd(equity: pd.Series) -> float:
    vals = equity.values
    cum = vals / (vals[0] + 1e-12)
    roll_max = np.maximum.accumulate(cum)
    return float(np.min((cum - roll_max) / (roll_max + 1e-8)))


def _cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / max(years, 0.01)) - 1) if years > 0.01 else 0.0


def compute_dsr(is_sharpe: float, n_trials: int, n_obs: int) -> tuple:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado). Returns (z-score, passed)."""
    from scipy import stats
    if n_obs < 10 or is_sharpe <= 0:
        return 0.0, False
    sr_std = np.sqrt(1.0 / max(n_obs, 1))
    gamma_em = 0.5772156649015328
    if n_trials > 1:
        expected_max = sr_std * (
            (1 - gamma_em) * stats.norm.ppf(1 - 1.0 / n_trials)
            + gamma_em * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
        )
    else:
        expected_max = 0.0
    dsr = is_sharpe / np.sqrt(TRADING_DAYS_PER_YEAR) - expected_max
    z = dsr / sr_std if sr_std > 0 else 0.0
    return round(z, 4), z > 0.0


def monte_carlo_sharpe(equity: pd.Series, n_sims: int = 1000, seed: int = 42) -> tuple:
    """Block-bootstrap MC Sharpe. Returns (p5, median, p95)."""
    rng = np.random.default_rng(seed)
    daily_ret = equity.pct_change().fillna(0.0).values
    n = len(daily_ret)
    block = 20
    n_blocks = int(np.ceil(n / block))
    sharpes = []
    for _ in range(n_sims):
        starts = rng.integers(0, max(n - block, 1), size=n_blocks)
        sim = np.concatenate([daily_ret[s:s + block] for s in starts])[:n]
        if sim.std() > 0:
            sharpes.append(float(sim.mean() / sim.std() * np.sqrt(TRADING_DAYS_PER_YEAR)))
    if not sharpes:
        return 0.0, 0.0, 0.0
    return (round(float(np.percentile(sharpes, 5)), 4),
            round(float(np.percentile(sharpes, 50)), 4),
            round(float(np.percentile(sharpes, 95)), 4))


def bootstrap_ci(equity: pd.Series, n_boot: int = 1000, seed: int = 42) -> dict:
    """Bootstrap 95% CI for Sharpe and MDD."""
    rng = np.random.default_rng(seed)
    daily_ret = equity.pct_change().fillna(0.0).values
    n = len(daily_ret)
    sharpes, mdds = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        r = daily_ret[idx]
        if r.std() > 0:
            sharpes.append(float(r.mean() / r.std() * np.sqrt(TRADING_DAYS_PER_YEAR)))
        cum = np.cumprod(1 + r)
        roll_max = np.maximum.accumulate(cum)
        mdds.append(float(np.min((cum - roll_max) / (roll_max + 1e-8))))

    def ci(arr):
        return (round(float(np.percentile(arr, 2.5)), 4),
                round(float(np.percentile(arr, 97.5)), 4))

    s_lo, s_hi = ci(sharpes) if sharpes else (0.0, 0.0)
    m_lo, m_hi = ci(mdds) if mdds else (0.0, 0.0)
    return {"sharpe_ci": (s_lo, s_hi), "mdd_ci": (m_lo, m_hi)}


def permutation_test(is_equity: pd.Series, is_sharpe: float, n_perms: int = 200) -> float:
    """Permutation test on IS daily returns. Returns p-value (lower = better)."""
    print(f"  Permutation test ({n_perms} permutations)...")
    rng = np.random.default_rng(42)
    daily_ret = is_equity.pct_change().fillna(0.0).values
    beats = sum(
        1 for _ in range(n_perms)
        if (lambda p: p.std() > 0 and float(p.mean() / p.std() * np.sqrt(TRADING_DAYS_PER_YEAR)) >= is_sharpe)(
            rng.permutation(daily_ret))
    )
    pval = (beats + 1) / (n_perms + 1)
    print(f"  Permutation p={pval:.4f} ({beats}/{n_perms} beat IS Sharpe {is_sharpe:.4f})")
    return round(pval, 4)


def composite_score(oos_sharpe: float, is_mdd: float, ppt_bps: float,
                    trade_count_per_quarter: float) -> float:
    """
    Track A composite score (kpi-daily-weekly.md v1.0):
    CS = 0.40*NetSharpe_norm + 0.30*Stability_norm + 0.20*PpT_norm + 0.10*TradeAdequacy_norm
    """
    sharpe_norm = np.clip((oos_sharpe - (-0.5)) / (2.0 - (-0.5)), 0.0, 1.0)
    stability_norm = np.clip(1.0 - abs(is_mdd) / 0.20, 0.0, 1.0)
    ppt_norm = np.clip(ppt_bps / 100.0, 0.0, 1.0)
    # TradeAdequacy: min(1.0, count_per_quarter / 30) — gates at 30, full credit at 30
    adequacy_norm = min(1.0, trade_count_per_quarter / 30.0)
    cs = 0.40 * sharpe_norm + 0.30 * stability_norm + 0.20 * ppt_norm + 0.10 * adequacy_norm
    return round(float(cs), 4)


# ── Parameter Sweep ────────────────────────────────────────────────────────────

def run_sweep(indicator_dict: dict, base_params: dict) -> list:
    """36-combo IS parameter sweep. Reuses pre-loaded indicator_dict."""
    keys = list(SWEEP_GRID.keys())
    combos = list(itertools.product(*[SWEEP_GRID[k] for k in keys]))
    results = []
    baseline_sharpe = None

    for i, values in enumerate(combos):
        p = base_params.copy()
        for k, v in zip(keys, values):
            p[k] = v
        try:
            res = simulate(indicator_dict, p, IS_START, IS_END)
            m = compute_metrics(res["equity"], res["trades"], res["total_cost"], p["init_cash"])
            row = {k: v for k, v in zip(keys, values)}
            row.update({
                "sharpe": m["sharpe"],
                "max_drawdown": m["max_drawdown"],
                "win_rate": m["win_rate"],
                "ppt_bps": m["ppt_bps"],
                "cpr": m["cpr"],
                "trade_count": m["trade_count"],
            })
            # Tag baseline
            is_baseline = all(p[k] == base_params[k] for k in keys)
            row["is_baseline"] = is_baseline
            if is_baseline:
                baseline_sharpe = m["sharpe"]
            results.append(row)
            print(f"    [{i + 1:2d}/36] trend_ma={p['trend_ma']} hold={p['hold_days']} "
                  f"atr_mult={p['atr_stop_mult']} → Sharpe={m['sharpe']:.3f} PpT={m['ppt_bps']:.1f}bps")
        except Exception as exc:
            row = {k: v for k, v in zip(keys, values)}
            row.update({"sharpe": 0.0, "error": str(exc)})
            results.append(row)
    return results


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def walk_forward(indicator_dict: dict, base_params: dict) -> list:
    """4-window walk-forward using pre-loaded indicator_dict."""
    windows = []
    for i, (ts, te, vs, ve) in enumerate(WF_SPECS, 1):
        print(f"  WF{i}: IS {ts}–{te}, OOS {vs}–{ve}")
        try:
            ir = simulate(indicator_dict, base_params, ts, te)
            or_ = simulate(indicator_dict, base_params, vs, ve)
            im = compute_metrics(ir["equity"], ir["trades"], ir["total_cost"], base_params["init_cash"])
            om = compute_metrics(or_["equity"], or_["trades"], or_["total_cost"], base_params["init_cash"])
            passed = om["sharpe"] > 0.0
            windows.append({
                "window": i,
                "train_start": ts, "train_end": te,
                "test_start": vs, "test_end": ve,
                "train_sharpe": round(im["sharpe"], 4),
                "test_sharpe": round(om["sharpe"], 4),
                "is_trade_count": im["trade_count"],
                "oos_trade_count": om["trade_count"],
                "passed": passed,
            })
            print(f"    IS Sharpe={im['sharpe']:.4f} trades={im['trade_count']} | "
                  f"OOS Sharpe={om['sharpe']:.4f} → {'PASS' if passed else 'FAIL'}")
        except Exception as exc:
            print(f"    WF{i} ERROR: {exc}")
            windows.append({
                "window": i, "train_start": ts, "train_end": te,
                "test_start": vs, "test_end": ve,
                "train_sharpe": 0.0, "test_sharpe": 0.0,
                "is_trade_count": 0, "oos_trade_count": 0,
                "passed": False, "error": str(exc),
            })
    return windows


# ── HTML Report ────────────────────────────────────────────────────────────────

def _check_row(label, passed, value, threshold):
    c = "#28a745" if passed else "#dc3545"
    s = "✓" if passed else "✗"
    return (f"<tr><td>{label}</td>"
            f"<td style='color:{c};font-weight:bold'>{s} {'PASS' if passed else 'FAIL'}</td>"
            f"<td>{value}</td><td>{threshold}</td></tr>")


def generate_html_report(data: dict, output_path: Path) -> None:
    vc = "#28a745" if data["gate1_pass"] else "#dc3545"
    vt = "PASS" if data["gate1_pass"] else "FAIL"
    checks = data["gate1_checks"]
    cs_val = data["composite_score"]
    gap = data.get("gap_stats", {})

    gate_rows = "\n".join([
        _check_row("Net OOS Sharpe > 0.7", checks["oos_sharpe_pass"],
                   f"{data['oos_sharpe']:.4f}", "> 0.7"),
        _check_row("Net profit/trade > 15 bps", checks["ppt_pass"],
                   f"{data['is_ppt_bps']:.2f} bps", "> 15 bps"),
        _check_row("IS MDD < 20% (CS threshold)", checks["is_mdd_pass"],
                   f"{data['is_max_drawdown']:.2%}", "< 20%"),
        _check_row("IS MDD < 30% (Gate 7 ceiling)", checks["is_mdd_gate7_pass"],
                   f"{data['is_max_drawdown']:.2%}", "< 30%"),
        _check_row("IS trades/quarter > 30", checks["trade_count_pass"],
                   f"{data['is_trades_per_quarter']:.1f}", "> 30"),
        _check_row("CPR < 0.25", checks["cpr_pass"],
                   f"{data['is_cpr']:.4f}", "< 0.25"),
        _check_row("WF OOS Sharpe > 0: ≥ 3/4", checks["wf_pass"],
                   f"{data['wf_windows_passed']}/4", "≥ 3/4"),
        _check_row("Composite Score CS ≥ 0.60", checks["cs_pass"],
                   f"{cs_val:.4f}", "≥ 0.60"),
        _check_row("Permutation p < 0.05", checks["permutation_pass"],
                   f"{data['permutation_pvalue']:.4f}", "< 0.05"),
        _check_row("DSR z-score > 0", checks["dsr_pass"],
                   f"{data['dsr_zscore']:.4f}", "> 0"),
    ])

    def _wf_row(w):
        c = "#28a745" if w.get("passed") else "#dc3545"
        s = "PASS" if w.get("passed") else "FAIL"
        return (
            f"<tr><td>{w['window']}</td><td>{w['train_start']}–{w['train_end']}</td>"
            f"<td>{w['test_start']}–{w['test_end']}</td>"
            f"<td>{w['train_sharpe']:.4f}</td><td>{w.get('is_trade_count', 'n/a')}</td>"
            f"<td>{w['test_sharpe']:.4f}</td>"
            f"<td style='color:{c}'>{s}</td></tr>"
        )
    wf_rows = "\n".join(_wf_row(w) for w in data.get("wf_windows", []))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Gate 1: {STRATEGY_NAME}</title>
<style>
body{{font-family:monospace;max-width:1100px;margin:20px auto;background:#f8f9fa}}
h1,h2{{color:#333}}
.verdict{{font-size:2em;font-weight:bold;color:{vc};border:3px solid {vc};
  display:inline-block;padding:8px 20px;border-radius:6px}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}
th,td{{border:1px solid #dee2e6;padding:6px 10px;text-align:left}}
th{{background:#343a40;color:white}} tr:nth-child(even){{background:#f2f2f2}}
.section{{background:white;padding:15px;margin:15px 0;border-radius:6px;
  box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.metric{{display:inline-block;margin:8px;padding:10px;background:#e9ecef;
  border-radius:4px;min-width:140px}}
.mv{{font-size:1.4em;font-weight:bold;color:#0d6efd}}
.pass{{color:#28a745;font-weight:bold}} .fail{{color:#dc3545;font-weight:bold}}
</style></head>
<body>
<h1>Gate 1 Report: {STRATEGY_NAME}</h1>
<p>Date: {data['date']} | IS: {IS_START}–{IS_END} | OOS: {OOS_START}–{OOS_END}</p>
<p>Universe: SPY, QQQ, IWM | Track A swing/daily | NR7 lookback=7 (Crabel canonical, fixed)</p>
<div class="verdict">{vt}</div>

<div class="section"><h2>Core Metrics</h2>
<div class="metric"><div>IS Sharpe</div><div class="mv">{data['is_sharpe']:.4f}</div></div>
<div class="metric"><div>OOS Sharpe</div><div class="mv">{data['oos_sharpe']:.4f}</div></div>
<div class="metric"><div>IS MDD</div><div class="mv">{data['is_max_drawdown']:.2%}</div></div>
<div class="metric"><div>IS CAGR</div><div class="mv">{data['is_cagr']:.2%}</div></div>
<div class="metric"><div>OOS CAGR</div><div class="mv">{data['oos_cagr']:.2%}</div></div>
<div class="metric"><div>IS Trades</div><div class="mv">{data['is_trade_count']}</div></div>
<div class="metric"><div>IS PpT (bps)</div><div class="mv">{data['is_ppt_bps']:.1f}</div></div>
<div class="metric"><div>IS CPR</div><div class="mv">{data['is_cpr']:.3f}</div></div>
<div class="metric"><div>Win Rate</div><div class="mv">{data['is_win_rate']:.2%}</div></div>
<div class="metric"><div>Composite CS</div><div class="mv">{cs_val:.4f}</div></div>
<div class="metric"><div>MC p5 Sharpe</div><div class="mv">{data['mc_p5_sharpe']:.4f}</div></div>
</div>

<div class="section"><h2>Gate 1 Checks (10 required)</h2>
<table><tr><th>Check</th><th>Result</th><th>Actual</th><th>Threshold</th></tr>
{gate_rows}</table>
<p>Score: {sum(checks.values())}/10 passed</p></div>

<div class="section"><h2>Walk-Forward (4 windows — 4-year IS / 6-month OOS)</h2>
<table><tr><th>#</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th>
<th>IS Trades</th><th>OOS Sharpe</th><th>Status</th></tr>
{wf_rows}</table>
<p>WF pass rate: {data['wf_windows_passed']}/4 (gate: ≥ 3/4 OOS Sharpe &gt; 0) |
WF OOS Sharpe std={data['wf_sharpe_std']:.4f}</p></div>

<div class="section"><h2>Statistical Rigor</h2>
<p>DSR z-score: {data['dsr_zscore']:.4f} | Bootstrap Sharpe CI:
[{data['sharpe_ci_low']:.4f}, {data['sharpe_ci_high']:.4f}]</p>
<p>Bootstrap MDD CI: [{data['mdd_ci_low']:.4f}, {data['mdd_ci_high']:.4f}]</p>
<p>MC p5/median/p95: {data['mc_p5_sharpe']:.4f} / {data['mc_median_sharpe']:.4f} /
{data['mc_p95_sharpe']:.4f}</p>
<p>Permutation p-value: {data['permutation_pvalue']:.4f}</p></div>

<div class="section"><h2>Parameter Sweep ({data['sweep_n_combos']} combos)</h2>
<p>Sharpe range: {data['sweep_sharpe_min']:.4f} – {data['sweep_sharpe_max']:.4f}</p>
<p>Sensitivity = (max-min)/|baseline| × 100 = <b>{data['sensitivity_pct']:.1f}%</b>
(threshold: &lt;50% — {'PASS' if data['sensitivity_pct'] < 50 else 'FAIL'})</p>
<p>Combos with Sharpe &gt; 0.7: {data['sweep_n_passing']}/{data['sweep_n_combos']}</p></div>

<div class="section"><h2>Composite Score (kpi-daily-weekly.md v1.0)</h2>
<p>CS = 0.40 × NetSharpe_norm + 0.30 × Stability_norm + 0.20 × PpT_norm + 0.10 × TradeAdequacy_norm</p>
<p>NetSharpe_norm = {np.clip((data['oos_sharpe'] + 0.5) / 2.5, 0, 1):.4f} |
Stability_norm = {max(0, 1 - abs(data['is_max_drawdown']) / 0.20):.4f} |
PpT_norm = {np.clip(data['is_ppt_bps'] / 100.0, 0, 1):.4f} |
TradeAdequacy_norm = {min(1.0, data['is_trades_per_quarter'] / 30):.4f}</p>
<p>CS = <b>{cs_val:.4f}</b> (threshold: ≥ 0.60 — {'PASS' if checks['cs_pass'] else 'FAIL'})</p></div>

<div class="section"><h2>Track A Hard Gate 8 — Overnight/Weekend Guards</h2>
<table>
<tr><th>Guard</th><th>Value</th></tr>
<tr><td>Overnight gap PnL contribution</td><td>{gap.get('overnight_gap_pnl_contribution_pct', 0):.1f}%</td></tr>
<tr><td>Weekend gap exposure (% avg notional)</td><td>{gap.get('weekend_gap_exposure_pct', 0):.1f}%</td></tr>
<tr><td>Gap MDD attribution</td><td>{gap.get('gap_mdd_attribution_pct', 0):.1f}%</td></tr>
<tr><td>Earnings hold policy</td><td>{gap.get('earnings_policy', 'N/A')}</td></tr>
<tr><td>Survivorship bias</td><td>{gap.get('survivorship_bias', 'N/A')}</td></tr>
</table></div>

<div class="section"><h2>Data Quality Checklist</h2>
<ul>
<li><b>Universe:</b> SPY, QQQ, IWM — current tickers identical to historical; ETFs; no survivorship bias.</li>
<li><b>Price adjustments:</b> yfinance auto_adjust=True (splits + dividends).</li>
<li><b>Earnings exclusion:</b> N/A — ETF universe.</li>
<li><b>Delisted tickers:</b> N/A — SPY/QQQ/IWM continuously listed.</li>
<li><b>Entry execution:</b> Next-day open with breakout confirmation (open &gt; NR7 high). CLEAN — no same-close fill.</li>
<li><b>Look-ahead:</b> CLEAN — all indicators use only prior-close data at signal time.</li>
<li><b>Cost model:</b> ED-SLIP-001 ultra-liquid ETF tier — $0.005/share fixed + 0.005% slippage + Almgren-Chriss impact.</li>
</ul></div>

</body></html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"  HTML report saved: {output_path.name}")


# ── Verdict TXT ────────────────────────────────────────────────────────────────

def generate_verdict_txt(data: dict, output_path: Path) -> None:
    verdict = "PASS" if data["gate1_pass"] else "FAIL"
    checks = data["gate1_checks"]
    cs = data["composite_score"]
    gap = data.get("gap_stats", {})

    lines = [
        f"{data['strategy_name']} — Gate 1 Verdict",
        "=" * 70,
        f"Date:    {data['date']}",
        f"IS:      {IS_START} → {IS_END}",
        f"OOS:     {OOS_START} → {OOS_END}",
        f"Overall: {verdict} ({sum(checks.values())}/10 checks passed)",
        "",
        "=== Universe ===",
        "SPY, QQQ, IWM — ultra-liquid ETFs, ADV > $10B/day (ED-SLIP-001 ultra-liquid tier)",
        "Survivorship bias: NONE — ETFs continuously listed; no delisting risk.",
        "Earnings policy:   N/A — ETFs do not report earnings.",
        "",
        "=== IS Performance ===",
        f"Sharpe:       {data['is_sharpe']:.4f}",
        f"Max Drawdown: {data['is_max_drawdown']:.2%}   [{'PASS' if checks['is_mdd_pass'] else 'FAIL'} CS threshold <20% | {'PASS' if checks['is_mdd_gate7_pass'] else 'FAIL'} Gate 7 <30%]",
        f"CAGR:         {data['is_cagr']:.2%}",
        f"Win Rate:     {data['is_win_rate']:.2%}",
        f"Profit Factor:{data['is_profit_factor']:.4f}",
        f"Trade Count:  {data['is_trade_count']} total | {data['is_trades_per_quarter']:.1f}/quarter   [{'PASS' if checks['trade_count_pass'] else 'FAIL'}: >30/quarter]",
        f"PpT (bps):    {data['is_ppt_bps']:.2f}   [{'PASS' if checks['ppt_pass'] else 'FAIL'}: >15 bps]",
        f"CPR:          {data['is_cpr']:.4f}   [{'PASS' if checks['cpr_pass'] else 'FAIL'}: <0.25]",
        "",
        "=== OOS Performance ===",
        f"Sharpe:       {data['oos_sharpe']:.4f}   [{'PASS' if checks['oos_sharpe_pass'] else 'FAIL'}: >0.7]",
        f"Max Drawdown: {data['oos_max_drawdown']:.2%}",
        f"CAGR:         {data['oos_cagr']:.2%}",
        f"Trade Count:  {data['oos_trade_count']}",
        "",
        "=== Composite Score (kpi-daily-weekly.md v1.0) ===",
        "CS = 0.40*NetSharpe_norm + 0.30*Stability_norm + 0.20*PpT_norm + 0.10*TradeAdequacy_norm",
        f"  NetSharpe_norm:     {np.clip((data['oos_sharpe'] + 0.5) / 2.5, 0, 1):.4f}",
        f"  Stability_norm:     {max(0.0, 1.0 - abs(data['is_max_drawdown']) / 0.20):.4f}",
        f"  PpT_norm:           {np.clip(data['is_ppt_bps'] / 100.0, 0, 1):.4f}",
        f"  TradeAdequacy_norm: {min(1.0, data['is_trades_per_quarter'] / 30):.4f}",
        f"  CS = {cs:.4f}   [{'PASS' if checks['cs_pass'] else 'FAIL'}: >=0.60]",
        "",
        "=== Statistical Rigor ===",
        f"MC p5/median/p95:  {data['mc_p5_sharpe']:.4f} / {data['mc_median_sharpe']:.4f} / {data['mc_p95_sharpe']:.4f}",
        f"Sharpe CI 95%:     [{data['sharpe_ci_low']:.4f}, {data['sharpe_ci_high']:.4f}]",
        f"MDD CI 95%:        [{data['mdd_ci_low']:.4f}, {data['mdd_ci_high']:.4f}]",
        f"Permutation p:     {data['permutation_pvalue']:.4f}   [{'PASS' if checks['permutation_pass'] else 'FAIL'}: <0.05]",
        f"DSR z-score:       {data['dsr_zscore']:.4f}   [{'PASS' if checks['dsr_pass'] else 'FAIL'}: >0]",
        f"WF OOS Sharpe std: {data['wf_sharpe_std']:.4f}",
        "",
        "=== Walk-Forward (4 windows — 4-year IS / 6-month OOS) ===",
    ]
    for w in data.get("wf_windows", []):
        lines.append(
            f"  WF{w['window']} IS {w['train_start']}–{w['train_end']}: "
            f"Sharpe={w['train_sharpe']:.4f} trades={w.get('is_trade_count', 'n/a')} | "
            f"OOS {w['test_start']}–{w['test_end']}: "
            f"Sharpe={w['test_sharpe']:.4f} | {'PASS' if w.get('passed') else 'FAIL'}"
        )
    lines += [
        f"  WF OOS Sharpe>0: {data['wf_windows_passed']}/4   [{'PASS' if checks['wf_pass'] else 'FAIL'}: >=3/4]",
        "",
        f"=== Parameter Sweep ({data['sweep_n_combos']} combos) ===",
        f"  trend_ma: {SWEEP_GRID['trend_ma']}",
        f"  hold_days: {SWEEP_GRID['hold_days']}",
        f"  atr_stop_mult: {SWEEP_GRID['atr_stop_mult']}",
        f"  Sharpe range: {data['sweep_sharpe_min']:.4f} – {data['sweep_sharpe_max']:.4f}",
        f"  Sensitivity: {data['sensitivity_pct']:.1f}%   [{'PASS' if data['sensitivity_pct'] < 50 else 'FAIL'}: <50%]",
        f"  Combos with Sharpe > 0.7: {data['sweep_n_passing']}/{data['sweep_n_combos']}",
        "",
        "=== Track A Hard Gate 8 (Overnight/Weekend Guards) ===",
        f"  Overnight gap PnL contribution: {gap.get('overnight_gap_pnl_contribution_pct', 0):.1f}%",
        f"  Weekend gap exposure:            {gap.get('weekend_gap_exposure_pct', 0):.1f}% of avg position notional",
        f"  Gap MDD attribution:             {gap.get('gap_mdd_attribution_pct', 0):.1f}%",
        f"  Earnings policy:                 {gap.get('earnings_policy', 'N/A')}",
        f"  Survivorship bias:               {gap.get('survivorship_bias', 'N/A')}",
        "",
        "=== Gate 1 Checks ===",
    ]
    check_labels = {
        "oos_sharpe_pass": "Net OOS Sharpe > 0.7",
        "ppt_pass": "Net profit/trade > 15 bps",
        "is_mdd_pass": "IS MDD < 20% (CS threshold)",
        "is_mdd_gate7_pass": "IS MDD < 30% (Gate 7 ceiling)",
        "trade_count_pass": "IS trades/quarter > 30",
        "cpr_pass": "CPR < 0.25",
        "wf_pass": "WF OOS Sharpe > 0: >= 3/4",
        "cs_pass": "Composite Score CS >= 0.60",
        "permutation_pass": "Permutation p < 0.05",
        "dsr_pass": "DSR z-score > 0",
    }
    for key, label in check_labels.items():
        lines.append(f"  [{'PASS' if checks.get(key) else 'FAIL'}] {label}")
    lines += [
        "",
        "=== Recommendation ===",
        "ADVANCE to paper trading (Gate 2)." if data["gate1_pass"] else "REJECT — does not meet Gate 1 criteria.",
        "",
        "=== Data Quality ===",
        "Look-ahead:      CLEAN (signal at close → entry at next open with breakout check)",
        "Same-close fill: NONE (Hard Gate 3 compliant)",
        "Price adjusted:  auto_adjust=True (yfinance)",
        "Cost model:      ED-SLIP-001 ultra-liquid ETF tier",
        "",
        "=== Files ===",
        f"Report:  {PREFIX.name}_report.html",
        f"Metrics: {PREFIX.name}.json",
        f"Verdict: {PREFIX.name}_verdict.txt",
        f"Trades:  {PREFIX.name}_trades.csv",
        f"Sweep:   {PREFIX.name}_sweep.csv",
    ]

    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  Verdict saved: {output_path.name}")


# ── Main Runner ────────────────────────────────────────────────────────────────

def main():
    print(f"=== Gate 1 Backtest: {STRATEGY_NAME} ===")
    print(f"IS: {IS_START}–{IS_END} | OOS: {OOS_START}–{OOS_END}")
    print(f"Output prefix: {PREFIX}\n")

    base_params = PARAMETERS.copy()

    # ── 1. Download data once (full period, single download) ───────────────────
    print("1. Downloading data (full period 2004–2026 for indicator warmup)...")
    tickers = base_params["tickers"]
    raw_data = download_data(tickers, IS_START, OOS_END)
    indicator_dict = {t: compute_indicators(raw_data[t], base_params) for t in tickers}
    print(f"   Data loaded for {tickers}")

    # ── 2. IS backtest ─────────────────────────────────────────────────────────
    print("\n2. Running IS backtest...")
    is_res = simulate(indicator_dict, base_params, IS_START, IS_END)
    is_eq = is_res["equity"]
    is_m = compute_metrics(is_eq, is_res["trades"], is_res["total_cost"], base_params["init_cash"])
    is_cagr = _cagr(is_eq)

    # Trade count per quarter
    is_trading_days = len(is_eq)
    is_quarters = is_trading_days / 63.0
    is_trades_per_quarter = is_m["trade_count"] / max(is_quarters, 1.0)
    print(f"   IS Sharpe={is_m['sharpe']:.4f} | MDD={is_m['max_drawdown']:.2%} | CAGR={is_cagr:.2%} | "
          f"Trades={is_m['trade_count']} ({is_trades_per_quarter:.1f}/qtr) | "
          f"PpT={is_m['ppt_bps']:.1f}bps | CPR={is_m['cpr']:.3f}")

    # ── 3. OOS backtest ────────────────────────────────────────────────────────
    print("\n3. Running OOS backtest...")
    oos_res = simulate(indicator_dict, base_params, OOS_START, OOS_END)
    oos_eq = oos_res["equity"]
    oos_m = compute_metrics(oos_eq, oos_res["trades"], oos_res["total_cost"], base_params["init_cash"])
    oos_cagr = _cagr(oos_eq)
    print(f"   OOS Sharpe={oos_m['sharpe']:.4f} | MDD={oos_m['max_drawdown']:.2%} | "
          f"CAGR={oos_cagr:.2%} | Trades={oos_m['trade_count']}")

    # ── 4. Parameter sweep ─────────────────────────────────────────────────────
    print("\n4. Running parameter sweep (36 combos on IS data)...")
    sweep_results = run_sweep(indicator_dict, base_params)
    sweep_sharpes = [r["sharpe"] for r in sweep_results if r.get("sharpe", 0) != 0 and "error" not in r]
    sw_min = round(float(np.min(sweep_sharpes)), 4) if sweep_sharpes else 0.0
    sw_max = round(float(np.max(sweep_sharpes)), 4) if sweep_sharpes else 0.0
    sw_pass = sum(1 for r in sweep_results if r.get("sharpe", 0) > 0.7)
    sensitivity_pct = round(
        (sw_max - sw_min) / max(abs(is_m["sharpe"]), 1e-6) * 100, 1
    ) if is_m["sharpe"] != 0 else 999.0
    print(f"   Sharpe range: {sw_min:.4f}–{sw_max:.4f} | Sensitivity: {sensitivity_pct:.1f}% | "
          f"Passing (>0.7): {sw_pass}/36")

    # ── 5. Walk-forward ────────────────────────────────────────────────────────
    print("\n5. Walk-forward analysis (4 windows)...")
    wf_windows = walk_forward(indicator_dict, base_params)
    wf_pass_count = sum(1 for w in wf_windows if w.get("passed"))
    wf_oos_sharpes = [w["test_sharpe"] for w in wf_windows]
    wf_sharpe_std = round(float(np.std(wf_oos_sharpes)), 4) if wf_oos_sharpes else 0.0
    print(f"   WF OOS Sharpe>0: {wf_pass_count}/4 | std={wf_sharpe_std:.4f}")

    # ── 6. Permutation test ────────────────────────────────────────────────────
    print("\n6. Permutation test (200 perms)...")
    perm_pval = permutation_test(is_eq, is_m["sharpe"], n_perms=200)

    # ── 7. Monte Carlo + Bootstrap CI ─────────────────────────────────────────
    print("\n7. Monte Carlo + Bootstrap CI...")
    mc_p5, mc_med, mc_p95 = monte_carlo_sharpe(is_eq, n_sims=1000)
    boot = bootstrap_ci(is_eq, n_boot=1000)
    print(f"   MC p5={mc_p5:.4f} | median={mc_med:.4f} | p95={mc_p95:.4f}")
    print(f"   Sharpe CI: [{boot['sharpe_ci'][0]:.4f}, {boot['sharpe_ci'][1]:.4f}]")

    # ── 8. DSR ─────────────────────────────────────────────────────────────────
    print("\n8. DSR...")
    dsr_z, dsr_pass = compute_dsr(is_m["sharpe"], n_trials=len(sweep_results), n_obs=len(is_eq))
    print(f"   DSR z={dsr_z:.4f} | {'PASS' if dsr_pass else 'FAIL'}")

    # ── 9. Overnight gap stats ─────────────────────────────────────────────────
    print("\n9. Overnight gap attribution (Track A Hard Gate 8)...")
    gap_stats = compute_overnight_gap_stats(is_eq, indicator_dict, is_res["trades"])
    print(f"   Gap PnL contribution: {gap_stats['overnight_gap_pnl_contribution_pct']:.1f}% | "
          f"Weekend exposure: {gap_stats['weekend_gap_exposure_pct']:.1f}%")

    # ── Composite score ────────────────────────────────────────────────────────
    cs = composite_score(oos_m["sharpe"], is_m["max_drawdown"],
                         is_m["ppt_bps"], is_trades_per_quarter)

    # ── Gate 1 checks ──────────────────────────────────────────────────────────
    gate1_checks = {
        "oos_sharpe_pass":    oos_m["sharpe"] > 0.7,
        "ppt_pass":           is_m["ppt_bps"] > 15.0,
        "is_mdd_pass":        abs(is_m["max_drawdown"]) < 0.20,
        "is_mdd_gate7_pass":  abs(is_m["max_drawdown"]) < 0.30,
        "trade_count_pass":   is_trades_per_quarter > 30.0,
        "cpr_pass":           is_m["cpr"] < 0.25,
        "wf_pass":            wf_pass_count >= 3,
        "cs_pass":            cs >= 0.60,
        "permutation_pass":   perm_pval < 0.05,
        "dsr_pass":           dsr_pass,
    }
    gate1_pass = all(gate1_checks.values())

    # ── Build output dict ──────────────────────────────────────────────────────
    trades_df = pd.DataFrame(is_res.get("trades", []))
    out = {
        "strategy_name": STRATEGY_NAME,
        "date": DATE_STR,
        "asset_class": "equities_etf",
        "track": "A",
        "universe": ["SPY", "QQQ", "IWM"],
        # IS
        "is_sharpe": is_m["sharpe"],
        "is_cagr": round(is_cagr, 4),
        "is_max_drawdown": is_m["max_drawdown"],
        "is_win_rate": is_m["win_rate"],
        "is_profit_factor": is_m["profit_factor"],
        "is_ppt_bps": is_m["ppt_bps"],
        "is_cpr": is_m["cpr"],
        "is_trade_count": is_m["trade_count"],
        "is_trades_per_quarter": round(is_trades_per_quarter, 2),
        # OOS
        "oos_sharpe": oos_m["sharpe"],
        "oos_cagr": round(oos_cagr, 4),
        "oos_max_drawdown": oos_m["max_drawdown"],
        "oos_win_rate": oos_m["win_rate"],
        "oos_trade_count": oos_m["trade_count"],
        # Aliases for compatibility
        "sharpe": is_m["sharpe"],
        "max_drawdown": is_m["max_drawdown"],
        "win_rate": is_m["win_rate"],
        "trade_count": is_m["trade_count"],
        # Composite score
        "composite_score": cs,
        # MC + Bootstrap
        "mc_p5_sharpe": mc_p5,
        "mc_median_sharpe": mc_med,
        "mc_p95_sharpe": mc_p95,
        "sharpe_ci_low": boot["sharpe_ci"][0],
        "sharpe_ci_high": boot["sharpe_ci"][1],
        "mdd_ci_low": boot["mdd_ci"][0],
        "mdd_ci_high": boot["mdd_ci"][1],
        # Permutation
        "permutation_pvalue": perm_pval,
        "permutation_test_pass": perm_pval < 0.05,
        # WF
        "wf_windows_passed": wf_pass_count,
        "wf_windows_total": 4,
        "wf_sharpe_std": wf_sharpe_std,
        "walk_forward_variance": wf_sharpe_std,
        "wf_windows": wf_windows,
        # DSR
        "dsr_zscore": dsr_z,
        "dsr_pass": dsr_pass,
        # Sensitivity
        "sensitivity_pct": sensitivity_pct,
        "sweep_n_combos": len(sweep_results),
        "sweep_sharpe_min": sw_min,
        "sweep_sharpe_max": sw_max,
        "sweep_n_passing": sw_pass,
        # Gate 1
        "gate1_pass": gate1_pass,
        "gate1_checks": gate1_checks,
        # Overnight guards
        "gap_stats": gap_stats,
        # Cost model
        "cost_model": "ED-SLIP-001 ultra-liquid ETF tier",
        "fixed_cost_per_share": 0.005,
        "slippage_pct": 0.00005,
        "market_impact_model": "Almgren-Chriss k=0.1",
        # Params
        "params": base_params,
    }

    # ── Save outputs ────────────────────────────────────────────────────────────
    print("\n10. Saving outputs...")

    json_path = Path(str(PREFIX) + ".json")
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  JSON saved: {json_path.name}")

    trades_path = Path(str(PREFIX) + "_trades.csv")
    trades_df.to_csv(trades_path, index=False)
    print(f"  Trades CSV saved: {trades_path.name}")

    sweep_df = pd.DataFrame(sweep_results)
    sweep_path = Path(str(PREFIX) + "_sweep.csv")
    sweep_df.to_csv(sweep_path, index=False)
    print(f"  Sweep CSV saved: {sweep_path.name}")

    html_path = Path(str(PREFIX) + "_report.html")
    generate_html_report(out, html_path)

    txt_path = Path(str(PREFIX) + "_verdict.txt")
    generate_verdict_txt(out, txt_path)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"GATE 1 VERDICT: {'PASS ✓' if gate1_pass else 'FAIL ✗'}")
    print(f"{'=' * 60}")
    label_map = {
        "oos_sharpe_pass":   f"OOS Sharpe:      {oos_m['sharpe']:.4f}  (need >0.7)",
        "ppt_pass":          f"PpT (bps):       {is_m['ppt_bps']:.2f}  (need >15)",
        "is_mdd_pass":       f"IS MDD (CS):     {is_m['max_drawdown']:.2%}  (need <20%)",
        "is_mdd_gate7_pass": f"IS MDD (Gate 7): {is_m['max_drawdown']:.2%}  (need <30%)",
        "trade_count_pass":  f"Trades/quarter:  {is_trades_per_quarter:.1f}  (need >30)",
        "cpr_pass":          f"CPR:             {is_m['cpr']:.4f}  (need <0.25)",
        "wf_pass":           f"WF OOS>0:        {wf_pass_count}/4  (need >=3/4)",
        "cs_pass":           f"Composite CS:    {cs:.4f}  (need >=0.60)",
        "permutation_pass":  f"Perm p-value:    {perm_pval:.4f}  (need <0.05)",
        "dsr_pass":          f"DSR z-score:     {dsr_z:.4f}  (need >0)",
    }
    for key, label in label_map.items():
        print(f"  {'✓' if gate1_checks[key] else '✗'} {label}")
    print(f"\nComposite Score: CS = {cs:.4f} ({'PASS' if gate1_checks['cs_pass'] else 'FAIL'})")
    print(f"\nOutputs saved to backtests/")
    return out


if __name__ == "__main__":
    main()
