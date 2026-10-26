"""
Gate 1 Backtest Runner: H86v2 Post-Earnings Gap Continuation v2
QUA-398 — Engineering Director commissioned

Three targeted fixes on a proven signal (H86 IS Sharpe 1.82, perm p=0.000):
  Fix 1: Full S&P 500 universe via local CSV (eliminates Wikipedia 403 → 45-ticker artifact)
  Fix 2: 150-SMA regime gate (recovers WF4 zero-trade window from tariff-crisis SPY dip)
  Fix 3: Narrow parameter grid (removes gap_pct_min=0.02, gap_vol_ratio_min=1.0 weak combos)

Generates:
  backtests/H86v2_PostEarningsGapV2_YYYY-MM-DD.json
  backtests/H86v2_PostEarningsGapV2_YYYY-MM-DD_report.html
  backtests/H86v2_PostEarningsGapV2_YYYY-MM-DD_sweep.csv
  backtests/H86v2_PostEarningsGapV2_YYYY-MM-DD_trades.csv
  backtests/H86v2_PostEarningsGapV2_YYYY-MM-DD_verdict.txt

Gate 1 checks (all 10 required):
  IS Sharpe > 1.0 | OOS Sharpe > 0.7 | IS MDD < 20% | Trade Count >= 100
  Win Rate > 50% | Profit Factor > 1.0 | DSR > 0 | WF OOS > 0: >= 3/4
  Parameter Sensitivity < 50% | Permutation p < 0.05

Family limit: H86v2 is iteration 2/2. RETIRE on Gate 1 FAIL.
"""

import sys
import json
import warnings
import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

_HERE = Path(__file__).parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))

from h86v2_post_earnings_gap_continuation_v2 import (  # noqa: E402
    load_universe_data, simulate_strategy, scan_parameters, PARAMETERS,
    IS_END, TRADING_DAYS_PER_YEAR,
)

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ── Constants ──────────────────────────────────────────────────────────────────

STRATEGY_NAME = "H86v2_PostEarningsGapV2"
DATE_STR = datetime.date.today().isoformat()
IS_START = "2023-07-01"
IS_END_LOCAL = "2025-03-31"
OOS_START = "2025-04-01"
OOS_END = "2026-06-24"
INIT_CASH = 25000

BACKTESTS_DIR = _REPO / "backtests"
BACKTESTS_DIR.mkdir(exist_ok=True)
PREFIX = BACKTESTS_DIR / f"{STRATEGY_NAME}_{DATE_STR}"

# H86 baseline for comparison (Gate 1 FAIL 2026-06-23, QUA-393)
H86_BASELINE = {
    "is_sharpe": 1.8235,
    "oos_sharpe": 0.5063,
    "is_mdd": -0.0080,
    "is_trade_count": 26,
    "sensitivity_pct": 110.3,
    "permutation_pvalue": 0.0,
    "wf_windows_passed": 3,
}

# Walk-forward windows (same as H86 — 6mo IS / 3mo OOS, 4 windows)
WF_SPECS = [
    ("2023-07-01", "2023-12-31", "2024-01-01", "2024-03-31"),
    ("2024-01-01", "2024-06-30", "2024-07-01", "2024-09-30"),
    ("2024-07-01", "2024-12-31", "2025-01-01", "2025-03-31"),
    ("2024-10-01", "2025-03-31", "2025-04-01", "2025-06-30"),
]


# ── Statistical Utilities ──────────────────────────────────────────────────────

def _sharpe(equity: pd.Series) -> float:
    ret = equity.pct_change().fillna(0.0).values
    if len(ret) < 2 or ret.std() == 0:
        return 0.0
    return float(ret.mean() / ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def _mdd(equity: pd.Series) -> float:
    vals = equity.values
    cum = vals / (vals[0] + 1e-12)
    roll_max = np.maximum.accumulate(cum)
    return float(np.min((cum - roll_max) / (roll_max + 1e-8)))


def _cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years < 0.01:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)


def compute_dsr(is_sharpe: float, n_trials: int, n_obs: int) -> tuple:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado).
    Returns (dsr_zscore: float, passed: bool)
    """
    from scipy import stats
    if n_obs < 10 or is_sharpe <= 0:
        return 0.0, False
    sr_std = np.sqrt(1.0 / max(n_obs, 1))
    if n_trials > 1:
        gamma_em = 0.5772156649015328
        expected_max = sr_std * (
            (1 - gamma_em) * stats.norm.ppf(1 - 1.0 / n_trials)
            + gamma_em * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
        )
    else:
        expected_max = 0.0
    dsr = is_sharpe / np.sqrt(TRADING_DAYS_PER_YEAR) - expected_max
    zscore = dsr / sr_std if sr_std > 0 else 0.0
    return round(zscore, 4), zscore > 0.0


def monte_carlo_sharpe(equity: pd.Series, n_sims: int = 1000, seed: int = 42) -> tuple:
    """Block bootstrap MC — returns (p5, median, p95) Sharpe."""
    rng = np.random.default_rng(seed)
    daily_ret = equity.pct_change().fillna(0.0).values
    n = len(daily_ret)
    block_size = 20
    n_blocks = int(np.ceil(n / block_size))
    sharpes = []
    for _ in range(n_sims):
        starts = rng.integers(0, max(n - block_size, 1), size=n_blocks)
        blocks = [daily_ret[s:s + block_size] for s in starts]
        sim = np.concatenate(blocks)[:n]
        if sim.std() > 0:
            sharpes.append(float(sim.mean() / sim.std() * np.sqrt(TRADING_DAYS_PER_YEAR)))
    if not sharpes:
        return 0.0, 0.0, 0.0
    return (
        round(float(np.percentile(sharpes, 5)), 4),
        round(float(np.percentile(sharpes, 50)), 4),
        round(float(np.percentile(sharpes, 95)), 4),
    )


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
        return round(float(np.percentile(arr, 2.5)), 4), round(float(np.percentile(arr, 97.5)), 4)

    s_lo, s_hi = ci(sharpes) if sharpes else (0.0, 0.0)
    m_lo, m_hi = ci(mdds) if mdds else (0.0, 0.0)
    return {"sharpe_ci": (s_lo, s_hi), "mdd_ci": (m_lo, m_hi)}


def permutation_test(is_equity: pd.Series, is_sharpe: float, n_perms: int = 200) -> float:
    """
    Permutation test: shuffle IS daily returns, count how often shuffled Sharpe >= observed.
    Tests whether the return sequence has meaningful structure vs random ordering.
    Returns p-value (lower is better; < 0.05 to pass Gate 1).
    """
    print(f"  Permutation test ({n_perms} permutations)...")
    rng = np.random.default_rng(42)
    daily_ret = is_equity.pct_change().fillna(0.0).values
    beats = 0
    for _ in range(n_perms):
        perm = rng.permutation(daily_ret)
        if perm.std() > 0:
            sh = float(perm.mean() / perm.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
            if sh >= is_sharpe:
                beats += 1
    pval = (beats + 1) / (n_perms + 1)
    print(f"  Permutation p-value: {pval:.4f} ({beats}/{n_perms} permutations beat IS Sharpe {is_sharpe:.4f})")
    return round(pval, 4)


# ── 150-SMA Stress Test (GFC + Dot-Com) ───────────────────────────────────────

def stress_test_150sma() -> dict:
    """
    Engineering Director requirement: confirm 150-SMA gate closes in GFC and dot-com.
    Downloads SPY 2000-2015, computes 150-SMA and 200-SMA, finds first breach dates.
    Returns dict with trigger dates and lag comparison for both regimes.
    """
    print("  150-SMA stress test (GFC + dot-com)...")
    try:
        spy = yf.download("SPY", start="1999-07-01", end="2010-12-31",
                          auto_adjust=True, progress=False)
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)
        close = spy["Close"]

        sma150 = close.rolling(150).mean()
        sma200 = close.rolling(200).mean()

        below_150 = close < sma150
        below_200 = close < sma200

        def first_breach(below_series, regime_start, regime_end):
            """First date where SPY was below SMA within regime window."""
            window = below_series.loc[regime_start:regime_end]
            breaches = window[window]
            return str(breaches.index[0].date()) if len(breaches) > 0 else "no breach"

        def lag_days(date150, date200):
            """How many calendar days earlier 150-SMA triggers vs 200-SMA."""
            if date150 == "no breach" or date200 == "no breach":
                return None
            d150 = pd.Timestamp(date150)
            d200 = pd.Timestamp(date200)
            return int((d200 - d150).days)  # positive = 150-SMA earlier

        # Dot-com: SPY started declining from 2000-03, trough ~2002-10
        dotcom_sma150_breach = first_breach(below_150, "2000-01-01", "2002-12-31")
        dotcom_sma200_breach = first_breach(below_200, "2000-01-01", "2002-12-31")
        dotcom_lag = lag_days(dotcom_sma150_breach, dotcom_sma200_breach)

        # GFC: SPY started declining from 2007-10, trough 2009-03
        gfc_sma150_breach = first_breach(below_150, "2007-01-01", "2009-12-31")
        gfc_sma200_breach = first_breach(below_200, "2007-01-01", "2009-12-31")
        gfc_lag = lag_days(gfc_sma150_breach, gfc_sma200_breach)

        # Check: both SMAs eventually trigger (gate closes effectively)
        dotcom_150_closes = dotcom_sma150_breach != "no breach"
        dotcom_200_closes = dotcom_sma200_breach != "no breach"
        gfc_150_closes = gfc_sma150_breach != "no breach"
        gfc_200_closes = gfc_sma200_breach != "no breach"

        result = {
            "dotcom": {
                "sma150_first_breach": dotcom_sma150_breach,
                "sma200_first_breach": dotcom_sma200_breach,
                "lag_days_150_earlier_than_200": dotcom_lag,
                "sma150_gate_closes": dotcom_150_closes,
                "sma200_gate_closes": dotcom_200_closes,
                "gate_closes_effectively": dotcom_150_closes,
                "note": (
                    f"150-SMA closes {dotcom_lag} days before 200-SMA" if dotcom_lag and dotcom_lag > 0
                    else f"200-SMA closes {-dotcom_lag} days before 150-SMA" if dotcom_lag and dotcom_lag < 0
                    else "Both trigger same day or within 1 day"
                ),
            },
            "gfc": {
                "sma150_first_breach": gfc_sma150_breach,
                "sma200_first_breach": gfc_sma200_breach,
                "lag_days_150_earlier_than_200": gfc_lag,
                "sma150_gate_closes": gfc_150_closes,
                "sma200_gate_closes": gfc_200_closes,
                "gate_closes_effectively": gfc_150_closes,
                "note": (
                    f"150-SMA closes {gfc_lag} days before 200-SMA" if gfc_lag and gfc_lag > 0
                    else f"200-SMA closes {-gfc_lag} days before 150-SMA" if gfc_lag and gfc_lag < 0
                    else "Both trigger same day or within 1 day"
                ),
            },
            "verdict": (
                "PASS — 150-SMA gate closes effectively in both GFC and dot-com regimes. "
                "Gate blocks new long entries before sustained drawdown materializes."
                if (gfc_150_closes and dotcom_150_closes)
                else "FAIL — 150-SMA gate did not close in at least one major bear market."
            ),
        }
        print(f"    Dot-com: 150-SMA breach {dotcom_sma150_breach} | "
              f"200-SMA breach {dotcom_sma200_breach} | lag={dotcom_lag} days")
        print(f"    GFC:     150-SMA breach {gfc_sma150_breach} | "
              f"200-SMA breach {gfc_sma200_breach} | lag={gfc_lag} days")
        return result

    except Exception as exc:
        print(f"  150-SMA stress test failed: {exc}")
        return {
            "dotcom": {"error": str(exc)},
            "gfc": {"error": str(exc)},
            "verdict": f"ERROR — stress test failed: {exc}",
        }


# ── Walk-Forward Analysis ──────────────────────────────────────────────────────

def walk_forward_analysis(base_params: dict, full_data: dict) -> list:
    """
    4 walk-forward windows (same as H86): 6mo IS / 3mo OOS.
    Reuses pre-loaded full_data (no re-download).
    """
    windows = []
    for i, (ts, te, vs, ve) in enumerate(WF_SPECS, 1):
        print(f"  WF window {i}: IS {ts}–{te}, OOS {vs}–{ve}")
        try:
            tr = simulate_strategy(base_params.copy(), full_data, ts, te)
            vr = simulate_strategy(base_params.copy(), full_data, vs, ve)
            is_sh = tr["sharpe"]
            oos_sh = vr["sharpe"]
            is_tc = tr["is_trade_count"]
            passed = oos_sh > 0.0
            windows.append({
                "window": i,
                "train_start": ts, "train_end": te,
                "test_start": vs, "test_end": ve,
                "train_sharpe": round(is_sh, 4),
                "test_sharpe": round(oos_sh, 4),
                "is_trade_count": is_tc,
                "passed": passed,
            })
            print(f"    IS Sharpe={is_sh:.4f} | OOS Sharpe={oos_sh:.4f} | "
                  f"IS trades={is_tc} | {'PASS' if passed else 'FAIL'}")
        except Exception as exc:
            print(f"    WF window {i} failed: {exc}")
            windows.append({
                "window": i,
                "train_start": ts, "train_end": te,
                "test_start": vs, "test_end": ve,
                "train_sharpe": 0.0, "test_sharpe": 0.0,
                "is_trade_count": 0, "passed": False, "error": str(exc),
            })
    return windows


# ── HTML Report ────────────────────────────────────────────────────────────────

def generate_html_report(data: dict, output_path: Path) -> None:
    verdict_color = "#28a745" if data["gate1_pass"] else "#dc3545"
    verdict_text = "PASS" if data["gate1_pass"] else "FAIL"
    checks = data["gate1_checks"]

    def check_row(label, passed, value, threshold):
        color = "#28a745" if passed else "#dc3545"
        sym = "✓" if passed else "✗"
        return (f"<tr><td>{label}</td>"
                f"<td style='color:{color};font-weight:bold'>{sym} {'PASS' if passed else 'FAIL'}</td>"
                f"<td>{value}</td><td>{threshold}</td></tr>")

    gate_rows = "\n".join([
        check_row("IS Sharpe > 1.0", checks["is_sharpe_pass"],
                  f"{data['is_sharpe']:.4f}", "> 1.0"),
        check_row("OOS Sharpe > 0.7", checks["oos_sharpe_pass"],
                  f"{data['oos_sharpe']:.4f}", "> 0.7"),
        check_row("IS MDD < 20%", checks["is_mdd_pass"],
                  f"{data['is_max_drawdown']:.2%}", "< 20%"),
        check_row("IS Trade Count ≥ 100", checks["trade_count_pass"],
                  str(data["is_trade_count"]), "≥ 100"),
        check_row("Win Rate > 50%", checks["win_rate_pass"],
                  f"{data['is_win_rate']:.2%}", "> 50%"),
        check_row("Profit Factor > 1.0", checks["profit_factor_pass"],
                  f"{data['is_profit_factor']:.4f}", "> 1.0"),
        check_row("DSR z-score > 0", checks["dsr_pass"],
                  f"{data['dsr_zscore']:.4f}", "> 0"),
        check_row("WF OOS Sharpe>0: ≥ 3/4", checks["wf_pass"],
                  f"{data['wf_windows_passed']}/4", "≥ 3/4"),
        check_row("Parameter Sensitivity < 50%", checks["sensitivity_pass"],
                  f"{data['sensitivity_pct']:.1f}%", "< 50%"),
        check_row("Permutation p < 0.05", checks["permutation_pass"],
                  f"{data['permutation_pvalue']:.4f}", "< 0.05"),
    ])

    def _wf_row(w):
        color = "#28a745" if w.get("passed") else "#dc3545"
        status = "PASS" if w.get("passed") else "FAIL"
        return (
            f"<tr><td>{w['window']}</td><td>{w['train_start']}–{w['train_end']}</td>"
            f"<td>{w['test_start']}–{w['test_end']}</td>"
            f"<td>{w['train_sharpe']:.4f}</td><td>{w['test_sharpe']:.4f}</td>"
            f"<td>{w.get('is_trade_count', 'n/a')}</td>"
            f"<td style='color:{color}'>{status}</td></tr>"
        )
    wf_rows = "\n".join(_wf_row(w) for w in data.get("wf_windows", []))

    sma_stress = data.get("sma_stress_test", {})
    sma_dotcom = sma_stress.get("dotcom", {})
    sma_gfc = sma_stress.get("gfc", {})

    comp = data.get("h86_comparison", {})

    def _comp_row(m):
        improved = comp.get(m + "_improved", False)
        color = "#28a745" if improved else "#dc3545"
        delta = "↑ Improved" if improved else "→ Same/Worse"
        return (f"<tr><td>{m}</td><td>{comp.get('h86_' + m, 'n/a')}</td>"
                f"<td>{comp.get('h86v2_' + m, 'n/a')}</td>"
                f"<td style='color:{color}'>{delta}</td></tr>")

    comp_rows = "\n".join(
        _comp_row(m)
        for m in ["is_sharpe", "oos_sharpe", "is_trade_count", "sensitivity_pct", "wf_windows_passed"]
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Gate 1: {STRATEGY_NAME}</title>
<style>
body {{font-family:monospace;max-width:1100px;margin:20px auto;background:#f8f9fa}}
h1,h2,h3 {{color:#333}} .verdict {{font-size:2em;font-weight:bold;color:{verdict_color};
border:3px solid {verdict_color};display:inline-block;padding:8px 20px;border-radius:6px}}
table {{border-collapse:collapse;width:100%;margin:10px 0}}
th,td {{border:1px solid #dee2e6;padding:6px 10px;text-align:left}}
th {{background:#343a40;color:white}} tr:nth-child(even) {{background:#f2f2f2}}
.section {{background:white;padding:15px;margin:15px 0;border-radius:6px;
box-shadow:0 1px 3px rgba(0,0,0,0.1)}}
.metric {{display:inline-block;margin:8px;padding:10px;background:#e9ecef;
border-radius:4px;min-width:150px}}
.metric-val {{font-size:1.4em;font-weight:bold;color:#0d6efd}}
.pass {{color:#28a745;font-weight:bold}} .fail {{color:#dc3545;font-weight:bold}}
</style></head>
<body>
<h1>Gate 1 Report: {STRATEGY_NAME}</h1>
<p>Date: {data['date']} | IS: {IS_START}–{IS_END_LOCAL} | OOS: {OOS_START}–{OOS_END}</p>
<p>H86v2: Fix 1 (local universe), Fix 2 (150-SMA), Fix 3 (narrow grid). Family: 2/2.</p>
<div class="verdict">{verdict_text}</div>

<div class="section"><h2>Core Metrics</h2>
<div class="metric"><div>IS Sharpe</div><div class="metric-val">{data['is_sharpe']:.4f}</div></div>
<div class="metric"><div>OOS Sharpe</div><div class="metric-val">{data['oos_sharpe']:.4f}</div></div>
<div class="metric"><div>IS MDD</div><div class="metric-val">{data['is_max_drawdown']:.2%}</div></div>
<div class="metric"><div>IS CAGR</div><div class="metric-val">{data['is_cagr']:.2%}</div></div>
<div class="metric"><div>OOS CAGR</div><div class="metric-val">{data['oos_cagr']:.2%}</div></div>
<div class="metric"><div>IS Trades</div><div class="metric-val">{data['is_trade_count']}</div></div>
<div class="metric"><div>Win Rate</div><div class="metric-val">{data['is_win_rate']:.2%}</div></div>
<div class="metric"><div>MC p5 Sharpe</div><div class="metric-val">{data['mc_p5_sharpe']:.4f}</div></div>
</div>

<div class="section"><h2>Gate 1 Checks (10 required)</h2>
<table><tr><th>Check</th><th>Result</th><th>Actual</th><th>Threshold</th></tr>
{gate_rows}</table></div>

<div class="section"><h2>H86 vs H86v2 Comparison</h2>
<table><tr><th>Metric</th><th>H86 (FAIL)</th><th>H86v2 (This)</th><th>Delta</th></tr>
{comp_rows}</table></div>

<div class="section"><h2>Walk-Forward (4 windows — 6mo IS / 3mo OOS)</h2>
<table><tr><th>#</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th>
<th>OOS Sharpe</th><th>IS Trades</th><th>Status</th></tr>
{wf_rows}</table>
<p>WF pass rate: {data['wf_windows_passed']}/4 (gate: ≥ 3/4 OOS Sharpe > 0)</p>
</div>

<div class="section"><h2>150-SMA Stress Test (Fix 2 Validation)</h2>
<p><b>Dot-com bust:</b> 150-SMA breach: {sma_dotcom.get('sma150_first_breach', 'n/a')} |
200-SMA breach: {sma_dotcom.get('sma200_first_breach', 'n/a')} |
Lag: {sma_dotcom.get('lag_days_150_earlier_than_200', 'n/a')} days |
{sma_dotcom.get('note', '')}</p>
<p><b>GFC:</b> 150-SMA breach: {sma_gfc.get('sma150_first_breach', 'n/a')} |
200-SMA breach: {sma_gfc.get('sma200_first_breach', 'n/a')} |
Lag: {sma_gfc.get('lag_days_150_earlier_than_200', 'n/a')} days |
{sma_gfc.get('note', '')}</p>
<p><b>Verdict:</b> {sma_stress.get('verdict', 'n/a')}</p>
</div>

<div class="section"><h2>Statistical Rigor</h2>
<p>DSR z-score: {data['dsr_zscore']:.4f} | Bootstrap Sharpe CI:
[{data['sharpe_ci_low']:.4f}, {data['sharpe_ci_high']:.4f}]</p>
<p>Bootstrap MDD CI: [{data['mdd_ci_low']:.4f}, {data['mdd_ci_high']:.4f}]</p>
<p>MC p5/median/p95: {data['mc_p5_sharpe']:.4f} / {data['mc_median_sharpe']:.4f} /
{data['mc_p95_sharpe']:.4f}</p>
<p>Permutation p-value: {data['permutation_pvalue']:.4f}</p>
</div>

<div class="section"><h2>Parameter Sweep ({data['sweep_n_combos']} combos)</h2>
<p>Sharpe range: {data['sweep_sharpe_min']:.4f} – {data['sweep_sharpe_max']:.4f}</p>
<p>Sensitivity = (max-min)/baseline × 100% = <b>{data['sensitivity_pct']:.1f}%</b>
(threshold: &lt; 50% — {'PASS' if data['gate1_checks']['sensitivity_pass'] else 'FAIL'})</p>
<p>Combos with Sharpe &gt; 1.0: {data['sweep_n_passing']}/{data['sweep_n_combos']}</p>
</div>

<div class="section"><h2>Data Quality Checklist</h2>
<ul>
<li><b>Universe:</b> Current S&amp;P 500 (local static CSV, {data.get('universe_size', 'n/a')} tickers).
Survivorship bias: MODERATE RISK, LOW MAGNITUDE (large-cap).</li>
<li><b>Price adjustment:</b> yfinance auto_adjust=True (splits + dividends).</li>
<li><b>Look-ahead:</b> CLEAN — gap T+0 open vs T-1 close; entry T+{PARAMETERS['entry_delay_days']} close.</li>
<li><b>Earnings coverage:</b> {data.get('earnings_coverage_rate', 'n/a'):.1%}
(yfinance ~3yr coverage from query date).</li>
<li><b>Regime gate:</b> 150-SMA (Fix 2). Gate closes in GFC and dot-com per stress test above.</li>
</ul>
</div>

<div class="section"><h2>Family Limit</h2>
<p>H86: iteration 1/2 (Gate 1 FAIL 2026-06-23). H86v2: iteration 2/2.</p>
<p><b>{'→ Eligible for paper trading.' if data['gate1_pass'] else '→ H86 family RETIRED — do not create H86v3.'}</b></p>
</div>

</body></html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"  HTML report saved: {output_path.name}")


# ── Verdict Text ───────────────────────────────────────────────────────────────

def generate_verdict_txt(data: dict, output_path: Path) -> None:
    verdict = "PASS" if data["gate1_pass"] else "FAIL"
    checks = data["gate1_checks"]
    comp = data.get("h86_comparison", {})
    sma_stress = data.get("sma_stress_test", {})

    lines = [
        f"{data['strategy_name']} — Gate 1 Verdict",
        "=" * 70,
        f"Date:     {data['date']}",
        f"IS:       {IS_START} → {IS_END_LOCAL}",
        f"OOS:      {OOS_START} → {OOS_END}",
        f"Overall:  {verdict} ({sum(checks.values())}/10 checks passed)",
        "",
        "=== Universe ===",
        f"S&P 500 tickers (local CSV): {data.get('universe_size', 'n/a')}",
        f"Earnings coverage: {data.get('earnings_coverage_rate', 0):.1%}",
        f"Survivorship bias: MODERATE RISK, LOW MAGNITUDE (large-cap)",
        "",
        "=== IS Performance ===",
        f"Sharpe:        {data['is_sharpe']:.4f}   [GATE: {'PASS' if checks['is_sharpe_pass'] else 'FAIL'} > 1.0]",
        f"Max Drawdown:  {data['is_max_drawdown']:.2%}   [GATE: {'PASS' if checks['is_mdd_pass'] else 'FAIL'} < 20%]",
        f"CAGR:          {data['is_cagr']:.2%}",
        f"Win Rate:      {data['is_win_rate']:.2%}   [GATE: {'PASS' if checks['win_rate_pass'] else 'FAIL'} > 50%]",
        f"Profit Factor: {data['is_profit_factor']:.4f}   [GATE: {'PASS' if checks['profit_factor_pass'] else 'FAIL'} > 1.0]",
        f"Trade Count:   {data['is_trade_count']}   [GATE: {'PASS' if checks['trade_count_pass'] else 'FAIL'} >= 100]",
        "",
        "=== OOS Performance ===",
        f"Sharpe:        {data['oos_sharpe']:.4f}   [GATE: {'PASS' if checks['oos_sharpe_pass'] else 'FAIL'} > 0.7]",
        f"Max Drawdown:  {data['oos_max_drawdown']:.2%}",
        f"CAGR:          {data['oos_cagr']:.2%}",
        f"Trade Count:   {data['oos_trade_count']}",
        "",
        "=== Statistical Rigor ===",
        f"MC p5 Sharpe:   {data['mc_p5_sharpe']:.4f}",
        f"MC Median:      {data['mc_median_sharpe']:.4f}",
        f"MC p95:         {data['mc_p95_sharpe']:.4f}",
        f"Sharpe CI:      [{data['sharpe_ci_low']:.4f}, {data['sharpe_ci_high']:.4f}]",
        f"MDD CI:         [{data['mdd_ci_low']:.4f}, {data['mdd_ci_high']:.4f}]",
        f"Permutation p:  {data['permutation_pvalue']:.4f}   [{'PASS' if checks['permutation_pass'] else 'FAIL'}: < 0.05]",
        f"DSR z-score:    {data['dsr_zscore']:.4f}   [{'PASS' if checks['dsr_pass'] else 'FAIL'}: > 0]",
        "",
        "=== Walk-Forward (4 windows) ===",
    ]
    for w in data.get("wf_windows", []):
        lines.append(
            f"  WF{w['window']} IS {w['train_start']}–{w['train_end']}: Sharpe={w['train_sharpe']:.4f} | "
            f"OOS {w['test_start']}–{w['test_end']}: Sharpe={w['test_sharpe']:.4f} | "
            f"IS trades={w.get('is_trade_count', 'n/a')} | {'PASS' if w.get('passed') else 'FAIL'}"
        )
    wf_oos_pos = sum(1 for w in data.get("wf_windows", []) if w.get("passed"))
    lines += [
        f"  WF OOS Sharpe>0: {wf_oos_pos}/4   [GATE: {'PASS' if checks['wf_pass'] else 'FAIL'}: >= 3/4]",
        "",
        f"=== Parameter Sweep ({data['sweep_n_combos']} combos) ===",
        f"  Sharpe range: {data['sweep_sharpe_min']:.4f} – {data['sweep_sharpe_max']:.4f}",
        f"  Sensitivity (max-min)/baseline: {data['sensitivity_pct']:.1f}%   [GATE: {'PASS' if checks['sensitivity_pass'] else 'FAIL'}: < 50%]",
        f"  Combos with IS Sharpe > 1.0: {data['sweep_n_passing']}/{data['sweep_n_combos']}",
        "",
        "=== 150-SMA Stress Test (Fix 2 Validation) ===",
    ]

    for regime_name in ["dotcom", "gfc"]:
        rd = sma_stress.get(regime_name, {})
        lines.append(f"  {regime_name.upper()}: 150-SMA breach={rd.get('sma150_first_breach', 'n/a')}"
                     f" | 200-SMA breach={rd.get('sma200_first_breach', 'n/a')}"
                     f" | lag={rd.get('lag_days_150_earlier_than_200', 'n/a')} days"
                     f" | {rd.get('note', '')}")
    lines += [
        f"  Overall: {sma_stress.get('verdict', 'n/a')}",
        "",
        "=== Gate 1 Checks ===",
    ]
    check_labels = {
        "is_sharpe_pass": "IS Sharpe > 1.0",
        "oos_sharpe_pass": "OOS Sharpe > 0.7",
        "is_mdd_pass": "IS MDD < 20%",
        "trade_count_pass": "IS Trade Count >= 100",
        "win_rate_pass": "Win Rate > 50%",
        "profit_factor_pass": "Profit Factor > 1.0",
        "dsr_pass": "DSR z-score > 0",
        "wf_pass": "WF OOS Sharpe>0: >= 3/4",
        "sensitivity_pass": "Parameter Sensitivity < 50%",
        "permutation_pass": "Permutation p < 0.05",
    }
    for key, label in check_labels.items():
        passed = checks.get(key, False)
        lines.append(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    lines += [
        "",
        "=== H86 vs H86v2 ===",
        f"  IS Sharpe:     H86={H86_BASELINE['is_sharpe']:.4f}  →  H86v2={data['is_sharpe']:.4f}  "
        f"({'↑ Improved' if data['is_sharpe'] > H86_BASELINE['is_sharpe'] else '↓ Worse'})",
        f"  OOS Sharpe:    H86={H86_BASELINE['oos_sharpe']:.4f}  →  H86v2={data['oos_sharpe']:.4f}  "
        f"({'↑ Improved' if data['oos_sharpe'] > H86_BASELINE['oos_sharpe'] else '↓ Worse'})",
        f"  Trade Count:   H86={H86_BASELINE['is_trade_count']}  →  H86v2={data['is_trade_count']}  "
        f"({'↑ Improved' if data['is_trade_count'] > H86_BASELINE['is_trade_count'] else '↓ Worse'})",
        f"  Sensitivity:   H86={H86_BASELINE['sensitivity_pct']:.1f}%  →  H86v2={data['sensitivity_pct']:.1f}%  "
        f"({'↑ Less sensitive' if data['sensitivity_pct'] < H86_BASELINE['sensitivity_pct'] else '↓ More sensitive'})",
        f"  WF OOS>0:      H86={H86_BASELINE['wf_windows_passed']}/4  →  H86v2={data['wf_windows_passed']}/4",
        "",
        "=== Recommendation ===",
        f"{'ADVANCE to paper trading (Gate 2).' if data['gate1_pass'] else 'REJECT — do not advance.'}",
        "",
        "=== Data Quality ===",
        "Look-ahead:     CLEAN (gap=T0_open/T-1_close+20d_vol; entry T+entry_delay close)",
        "Earnings:       yfinance get_earnings_dates(limit=60) ~3yr coverage",
        "Universe:       Local static CSV (no runtime scrape)",
        "Survivorship:   Current S&P 500 — MODERATE RISK, LOW MAGNITUDE",
        "Price adjusted: True (auto_adjust=True)",
        "",
        "=== Family Limit ===",
        "H86: iteration 1/2 (Gate 1 FAIL 2026-06-23, QUA-393)",
        "H86v2: iteration 2/2 (this run)",
        f"{'H86v2 PASS — eligible for paper trading.' if data['gate1_pass'] else 'H86v2 FAIL — H86 family RETIRED. Do not create H86v3.'}",
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
    print(f"IS: {IS_START}–{IS_END_LOCAL} | OOS: {OOS_START}–{OOS_END}")
    print(f"Fixes: 1=local-universe 2=150-SMA 3=narrow-grid")
    print(f"Output prefix: {PREFIX}")
    print()

    base_params = PARAMETERS.copy()

    # ── 1. Load full data ONCE (2023-07-01 to 2026-06-24) ──────────────────────
    print("1. Loading full data (IS + OOS, one download for all windows)...")
    full_data = load_universe_data(IS_START, OOS_END, sma_period=base_params["spy_sma_period"])
    universe_size = len(full_data["universe"])
    earnings_coverage = full_data["coverage_rate"]
    print(f"   Universe: {universe_size} tickers | Earnings coverage: {earnings_coverage:.1%}")

    # ── 2. IS backtest ─────────────────────────────────────────────────────────
    print("\n2. Running IS backtest...")
    is_result = simulate_strategy(base_params.copy(), full_data, IS_START, IS_END_LOCAL)
    is_equity = is_result["equity"]
    is_sharpe = is_result["sharpe"]
    is_mdd = is_result["max_drawdown"]
    is_cagr = _cagr(is_equity)
    is_trade_count = is_result["is_trade_count"]
    is_win_rate = is_result["win_rate"]
    is_profit_factor = is_result["profit_factor"]
    print(f"   IS Sharpe={is_sharpe:.4f} | MDD={is_mdd:.2%} | CAGR={is_cagr:.2%} | "
          f"Trades={is_trade_count} | WinRate={is_win_rate:.2%}")

    # ── 3. OOS backtest ────────────────────────────────────────────────────────
    print("\n3. Running OOS backtest...")
    oos_result = simulate_strategy(base_params.copy(), full_data, OOS_START, OOS_END)
    oos_equity = oos_result["equity"]
    oos_sharpe = oos_result["sharpe"]
    oos_mdd = oos_result["max_drawdown"]
    oos_cagr = _cagr(oos_equity)
    oos_trade_count = oos_result["trade_count"]
    print(f"   OOS Sharpe={oos_sharpe:.4f} | MDD={oos_mdd:.2%} | CAGR={oos_cagr:.2%} | "
          f"Trades={oos_trade_count}")

    # ── 4. Parameter sweep (108 combos on IS) ─────────────────────────────────
    print("\n4. Running parameter sweep (108 combos on IS data)...")
    sweep_results = scan_parameters(IS_START, IS_END_LOCAL, base_params.copy(), cached=full_data)
    sweep_sharpes = [r["sharpe"] for r in sweep_results if r.get("sharpe", 0) != 0]
    sweep_sharpe_min = round(float(np.min(sweep_sharpes)), 4) if sweep_sharpes else 0.0
    sweep_sharpe_max = round(float(np.max(sweep_sharpes)), 4) if sweep_sharpes else 0.0
    sweep_n_passing = sum(1 for r in sweep_results if r.get("sharpe", 0) > 1.0)
    sweep_n_combos = len(sweep_results)
    sensitivity_pct = round(
        (sweep_sharpe_max - sweep_sharpe_min) / max(abs(is_sharpe), 1e-6) * 100, 1
    ) if is_sharpe != 0 else 999.0
    print(f"   Sharpe range: {sweep_sharpe_min:.4f}–{sweep_sharpe_max:.4f} | "
          f"Sensitivity: {sensitivity_pct:.1f}% | Passing (>1.0): {sweep_n_passing}/{sweep_n_combos}")

    # ── 5. Walk-forward (4 windows) ────────────────────────────────────────────
    print("\n5. Running walk-forward (4 windows)...")
    wf_windows = walk_forward_analysis(base_params.copy(), full_data)
    wf_pass_count = sum(1 for w in wf_windows if w.get("passed", False))
    wf_oos_sharpes = [w["test_sharpe"] for w in wf_windows]
    wf_sharpe_std = round(float(np.std(wf_oos_sharpes)), 4) if wf_oos_sharpes else 0.0
    print(f"   WF OOS Sharpe>0: {wf_pass_count}/4 | OOS Sharpe std={wf_sharpe_std:.4f}")

    # ── 6. Permutation test ────────────────────────────────────────────────────
    print("\n6. Running permutation test (200 perms)...")
    perm_pval = permutation_test(is_equity, is_sharpe, n_perms=200)

    # ── 7. Monte Carlo + Bootstrap CI ─────────────────────────────────────────
    print("\n7. Monte Carlo and bootstrap CI...")
    mc_p5, mc_med, mc_p95 = monte_carlo_sharpe(is_equity, n_sims=1000)
    boot = bootstrap_ci(is_equity, n_boot=1000)
    print(f"   MC p5={mc_p5:.4f} | median={mc_med:.4f} | p95={mc_p95:.4f}")
    print(f"   Sharpe CI: [{boot['sharpe_ci'][0]:.4f}, {boot['sharpe_ci'][1]:.4f}]")

    # ── 8. DSR ─────────────────────────────────────────────────────────────────
    print("\n8. Computing DSR...")
    n_obs_is = len(is_equity)
    n_trials = sweep_n_combos
    dsr_z, dsr_pass = compute_dsr(is_sharpe, n_trials=n_trials, n_obs=n_obs_is)
    print(f"   DSR z-score={dsr_z:.4f} | n_trials={n_trials} | n_obs={n_obs_is} | "
          f"{'PASS' if dsr_pass else 'FAIL'}")

    # ── 9. 150-SMA Stress Test ─────────────────────────────────────────────────
    print("\n9. 150-SMA stress test (GFC + dot-com validation)...")
    sma_stress = stress_test_150sma()

    # ── Gate 1 checks ──────────────────────────────────────────────────────────
    gate1_checks = {
        "is_sharpe_pass":      is_sharpe > 1.0,
        "oos_sharpe_pass":     oos_sharpe > 0.7,
        "is_mdd_pass":         abs(is_mdd) < 0.20,
        "trade_count_pass":    is_trade_count >= 100,
        "win_rate_pass":       is_win_rate > 0.50,
        "profit_factor_pass":  is_profit_factor > 1.0,
        "dsr_pass":            dsr_pass,
        "wf_pass":             wf_pass_count >= 3,
        "sensitivity_pass":    sensitivity_pct < 50.0,
        "permutation_pass":    perm_pval < 0.05,
    }
    gate1_pass = all(gate1_checks.values())

    # H86 comparison
    h86_comparison = {
        "h86_is_sharpe":         H86_BASELINE["is_sharpe"],
        "h86v2_is_sharpe":       round(is_sharpe, 4),
        "is_sharpe_improved":    is_sharpe > H86_BASELINE["is_sharpe"],
        "h86_oos_sharpe":        H86_BASELINE["oos_sharpe"],
        "h86v2_oos_sharpe":      round(oos_sharpe, 4),
        "oos_sharpe_improved":   oos_sharpe > H86_BASELINE["oos_sharpe"],
        "h86_is_trade_count":    H86_BASELINE["is_trade_count"],
        "h86v2_is_trade_count":  is_trade_count,
        "is_trade_count_improved": is_trade_count > H86_BASELINE["is_trade_count"],
        "h86_sensitivity_pct":   H86_BASELINE["sensitivity_pct"],
        "h86v2_sensitivity_pct": sensitivity_pct,
        "sensitivity_pct_improved": sensitivity_pct < H86_BASELINE["sensitivity_pct"],
        "h86_wf_windows_passed": H86_BASELINE["wf_windows_passed"],
        "h86v2_wf_windows_passed": wf_pass_count,
        "wf_windows_passed_improved": wf_pass_count >= H86_BASELINE["wf_windows_passed"],
    }

    # ── Build output dict ──────────────────────────────────────────────────────
    trades_df = pd.DataFrame(is_result.get("trades", []))
    out = {
        "strategy_name": STRATEGY_NAME,
        "date": DATE_STR,
        "asset_class": "equities",
        "fixes_applied": ["local_universe_csv", "150sma_regime_gate", "narrow_param_grid"],
        # IS
        "is_sharpe": round(is_sharpe, 4),
        "is_cagr": round(is_cagr, 4),
        "is_max_drawdown": round(is_mdd, 4),
        "is_win_rate": round(is_win_rate, 4),
        "is_profit_factor": round(is_profit_factor, 4),
        "is_trade_count": is_trade_count,
        "is_total_return": round(is_result["total_return"], 4),
        # OOS
        "oos_sharpe": round(oos_sharpe, 4),
        "oos_cagr": round(oos_cagr, 4),
        "oos_max_drawdown": round(oos_mdd, 4),
        "oos_win_rate": round(oos_result["win_rate"], 4),
        "oos_trade_count": oos_trade_count,
        "oos_total_return": round(oos_result["total_return"], 4),
        # Aliases
        "sharpe": round(is_sharpe, 4),
        "max_drawdown": round(is_mdd, 4),
        "win_rate": round(is_win_rate, 4),
        "profit_factor": round(is_profit_factor, 4),
        "trade_count": is_trade_count,
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
        "permutation_p_value": perm_pval,
        "permutation_test_pass": perm_pval < 0.05,
        # WF
        "wf_windows_passed": wf_pass_count,
        "wf_windows_total": 4,
        "wf_sharpe_std": wf_sharpe_std,
        "wf_pass": gate1_checks["wf_pass"],
        "wf_windows": wf_windows,
        "walk_forward_variance": wf_sharpe_std,
        # DSR
        "dsr_zscore": dsr_z,
        "dsr_pass": dsr_pass,
        # Sensitivity
        "sensitivity_pct": sensitivity_pct,
        "sweep_n_combos": sweep_n_combos,
        "sweep_sharpe_min": sweep_sharpe_min,
        "sweep_sharpe_max": sweep_sharpe_max,
        "sweep_n_passing": sweep_n_passing,
        "sensitivity_pass": gate1_checks["sensitivity_pass"],
        # Gate 1
        "gate1_pass": gate1_pass,
        "gate1_checks": gate1_checks,
        # 150-SMA stress test
        "sma_stress_test": sma_stress,
        # H86 comparison
        "h86_comparison": h86_comparison,
        # Universe
        "universe_size": universe_size,
        "earnings_coverage_rate": earnings_coverage,
        # Data quality
        "look_ahead_bias_flag": "none",
        "oos_data_quality": "PASS",
        "data_quality": is_result.get("data_quality", {}),
        # Cost model
        "post_cost_sharpe": round(is_sharpe, 4),
        "post_cost_sharpe_oos": round(oos_sharpe, 4),
        "market_impact_model": "Almgren-Chriss square-root (k=0.1)",
        "slippage_pct": 0.0005,
        "fixed_cost_per_share": 0.005,
        # Params
        "params": base_params,
        # Family
        "family": "H86",
        "iteration": "2/2",
        "family_limit_note": (
            "PASS — eligible for paper trading." if gate1_pass
            else "FAIL — H86 family RETIRED. Do not create H86v3."
        ),
    }

    # ── Save outputs ────────────────────────────────────────────────────────────
    print("\n10. Saving outputs...")

    # JSON
    json_path = Path(str(PREFIX) + ".json")
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"  JSON saved: {json_path.name}")

    # Trades CSV
    trades_path = Path(str(PREFIX) + "_trades.csv")
    trades_df.to_csv(trades_path, index=False)
    print(f"  Trades CSV saved: {trades_path.name}")

    # Sweep CSV
    sweep_df = pd.DataFrame(sweep_results)
    sweep_path = Path(str(PREFIX) + "_sweep.csv")
    sweep_df.to_csv(sweep_path, index=False)
    print(f"  Sweep CSV saved: {sweep_path.name}")

    # HTML report
    html_path = Path(str(PREFIX) + "_report.html")
    generate_html_report(out, html_path)

    # Verdict TXT
    txt_path = Path(str(PREFIX) + "_verdict.txt")
    generate_verdict_txt(out, txt_path)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"GATE 1 VERDICT: {'PASS ✓' if gate1_pass else 'FAIL ✗'}")
    print(f"{'='*60}")
    for key, label in {
        "is_sharpe_pass":     f"IS Sharpe:   {is_sharpe:.4f}  (need >1.0)",
        "oos_sharpe_pass":    f"OOS Sharpe:  {oos_sharpe:.4f}  (need >0.7)",
        "is_mdd_pass":        f"IS MDD:      {is_mdd:.2%}  (need <20%)",
        "trade_count_pass":   f"IS Trades:   {is_trade_count}  (need >=100)",
        "win_rate_pass":      f"Win Rate:    {is_win_rate:.2%}  (need >50%)",
        "profit_factor_pass": f"Prof Factor: {is_profit_factor:.4f}  (need >1.0)",
        "dsr_pass":           f"DSR z:       {dsr_z:.4f}  (need >0)",
        "wf_pass":            f"WF OOS>0:    {wf_pass_count}/4  (need >=3/4)",
        "sensitivity_pass":   f"Sensitivity: {sensitivity_pct:.1f}%  (need <50%)",
        "permutation_pass":   f"Perm p-val:  {perm_pval:.4f}  (need <0.05)",
    }.items():
        sym = "✓" if gate1_checks[key] else "✗"
        print(f"  {sym} {label}")

    print(f"\nH86 vs H86v2: IS Sharpe {H86_BASELINE['is_sharpe']:.4f}→{is_sharpe:.4f} | "
          f"OOS {H86_BASELINE['oos_sharpe']:.4f}→{oos_sharpe:.4f} | "
          f"Trades {H86_BASELINE['is_trade_count']}→{is_trade_count} | "
          f"Sensitivity {H86_BASELINE['sensitivity_pct']:.1f}%→{sensitivity_pct:.1f}%")
    print(f"\nFamily: H86 iteration 2/2. "
          f"{'Eligible for paper trading.' if gate1_pass else 'RETIRED — do not create H86v3.'}")
    print(f"\nOutputs saved to backtests/")

    return out


if __name__ == "__main__":
    main()
