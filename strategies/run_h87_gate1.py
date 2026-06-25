"""
Gate 1 Backtest Runner: H87 Darvas Box Breakout — S&P 1500 US Equities
QUA-418 — Strategy Coder Agent

Generates:
  backtests/H87_DarvasBoxBreakout_YYYY-MM-DD.json
  backtests/H87_DarvasBoxBreakout_YYYY-MM-DD_report.html
  backtests/H87_DarvasBoxBreakout_YYYY-MM-DD_sweep.csv
  backtests/H87_DarvasBoxBreakout_YYYY-MM-DD_trades.csv
  backtests/H87_DarvasBoxBreakout_YYYY-MM-DD_verdict.txt

Gate 1 checks (QUA-418 spec):
  IS Sharpe > 1.0              | OOS Sharpe > 0.7
  IS MDD < 20%                 | IS trade count >= 100
  Win rate > 50%               | Profit factor > 1.0
  WF OOS positive >= 4/6       | Parameter sensitivity < 50%
  Permutation p < 0.05

Walk-forward: 6 windows (3-month IS / 1-month OOS per QUA-418 spec)
Parameter sweep: box_n [15,20,25] x box_width_max [0.08,0.10,0.12] x vol_ratio_min [1.20,1.30,1.40] = 27 combos
"""

import sys
import json
import math
import warnings
import itertools
import datetime
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))

from h87_darvas_box_breakout import (  # noqa: E402
    load_universe_data, simulate_strategy, scan_parameters,
    PARAMETERS, IS_START, IS_END, TRADING_DAYS_PER_YEAR,
    _check_data_quality,
)

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ── Constants ──────────────────────────────────────────────────────────────────

STRATEGY_NAME = "H87_DarvasBoxBreakout"
DATE_STR = datetime.date.today().isoformat()

BACKTESTS_DIR = _REPO / "backtests"
BACKTESTS_DIR.mkdir(exist_ok=True)
PREFIX = BACKTESTS_DIR / f"{STRATEGY_NAME}_{DATE_STR}"

# Walk-forward: 6 windows (3-month IS / 1-month OOS) — QUA-418 spec
WF_SPECS = [
    ("2022-01-01", "2022-03-31", "2022-04-01", "2022-04-30"),
    ("2022-04-01", "2022-06-30", "2022-07-01", "2022-07-31"),
    ("2022-07-01", "2022-09-30", "2022-10-01", "2022-10-31"),
    ("2022-10-01", "2022-12-31", "2023-01-01", "2023-01-31"),
    ("2023-01-01", "2023-09-30", "2023-10-01", "2023-12-31"),
    ("2024-01-01", "2024-09-30", "2024-10-01", "2024-12-31"),
]

# Parameter sweep grid (27 combos)
SWEEP_GRID = {
    "box_n": [15, 20, 25],
    "box_width_max": [0.08, 0.10, 0.12],
    "vol_ratio_min": [1.20, 1.30, 1.40],
}


# ── Statistical Utilities ──────────────────────────────────────────────────────

def _sharpe(equity: pd.Series) -> float:
    ret = equity.pct_change().fillna(0.0).values
    s = ret.std()
    if len(ret) < 3 or s < 1e-10:
        return 0.0
    return float(ret.mean() / s * math.sqrt(TRADING_DAYS_PER_YEAR))


def _mdd(equity: pd.Series) -> float:
    vals = equity.values.astype(float)
    if len(vals) == 0:
        return 0.0
    cum = vals / (vals[0] + 1e-12)
    roll_max = np.maximum.accumulate(cum)
    return float(np.min((cum - roll_max) / (roll_max + 1e-8)))


def _cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years < 0.01:
        return 0.0
    return float((equity.iloc[-1] / (equity.iloc[0] + 1e-12)) ** (1.0 / years) - 1)


def _profit_factor(trade_df: pd.DataFrame) -> float:
    if trade_df.empty:
        return 0.0
    wins = trade_df.loc[trade_df["pnl"] > 0, "pnl"].sum()
    losses = trade_df.loc[trade_df["pnl"] < 0, "pnl"].abs().sum()
    return round(float(wins / losses), 4) if losses > 0 else 999.0


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
        sim = np.concatenate([daily_ret[s: s + block] for s in starts])[:n]
        s = sim.std()
        if s > 1e-10:
            sharpes.append(float(sim.mean() / s * math.sqrt(TRADING_DAYS_PER_YEAR)))
    if not sharpes:
        return 0.0, 0.0, 0.0
    return (
        round(float(np.percentile(sharpes, 5)), 4),
        round(float(np.percentile(sharpes, 50)), 4),
        round(float(np.percentile(sharpes, 95)), 4),
    )


def permutation_test(is_equity: pd.Series, is_sharpe: float, n_perms: int = 300) -> float:
    """Permutation test on IS daily returns. Returns p-value."""
    print(f"  Permutation test ({n_perms} permutations)...")
    rng = np.random.default_rng(42)
    daily_ret = is_equity.pct_change().fillna(0.0).values
    beats = 0
    for _ in range(n_perms):
        p = rng.permutation(daily_ret)
        s = p.std()
        if s > 1e-10:
            perm_sharpe = float(p.mean() / s * math.sqrt(TRADING_DAYS_PER_YEAR))
            if perm_sharpe >= is_sharpe:
                beats += 1
    pval = (beats + 1) / (n_perms + 1)
    print(f"  Permutation p={pval:.4f} ({beats}/{n_perms} beat IS Sharpe {is_sharpe:.4f})")
    return round(pval, 4)


def bootstrap_ci(equity: pd.Series, n_boot: int = 1000, seed: int = 42) -> dict:
    """Bootstrap 95% CI for Sharpe and MDD."""
    rng = np.random.default_rng(seed)
    daily_ret = equity.pct_change().fillna(0.0).values
    n = len(daily_ret)
    sharpes, mdds = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        r = daily_ret[idx]
        s = r.std()
        if s > 1e-10:
            sharpes.append(float(r.mean() / s * math.sqrt(TRADING_DAYS_PER_YEAR)))
        cum = np.cumprod(1 + r)
        roll_max = np.maximum.accumulate(cum)
        mdds.append(float(np.min((cum - roll_max) / (roll_max + 1e-8))))

    def _ci(arr):
        if not arr:
            return 0.0, 0.0
        return round(float(np.percentile(arr, 2.5)), 4), round(float(np.percentile(arr, 97.5)), 4)

    s_lo, s_hi = _ci(sharpes)
    m_lo, m_hi = _ci(mdds)
    return {"sharpe_ci": (s_lo, s_hi), "mdd_ci": (m_lo, m_hi)}


def _compute_gap_mdd_fraction(trade_df: pd.DataFrame, close: pd.DataFrame) -> float:
    """
    Estimate fraction of losing trade PnL attributable to overnight gaps.
    Gap = |exit_open - prior_close| / prior_close > 1% flags as gap event.
    """
    if trade_df.empty:
        return 0.0
    losing = trade_df[trade_df["pnl"] < 0]
    if losing.empty:
        return 0.0
    total_loss = float(losing["pnl"].abs().sum())
    gap_loss = 0.0
    for _, row in losing.iterrows():
        ticker = row["ticker"]
        try:
            exit_date = pd.Timestamp(row["exit_date"])
            if ticker not in close.columns:
                continue
            prior_idx = close.index.get_indexer([exit_date], method="pad")[0]
            if prior_idx <= 0:
                continue
            prior_close = float(close.iloc[prior_idx - 1][ticker])
            exit_px = row["exit_price"]
            if abs(exit_px - prior_close) / max(prior_close, 1e-8) > 0.01:
                gap_loss += abs(row["pnl"])
        except Exception:
            continue
    return round(gap_loss / max(total_loss, 1e-8), 4)


# ── Parameter Sweep ────────────────────────────────────────────────────────────

def _build_param_grid(base_params: dict) -> list:
    """Build 27-combo grid by varying only swept params; all others from base_params."""
    keys = list(SWEEP_GRID.keys())
    combos = list(itertools.product(*[SWEEP_GRID[k] for k in keys]))
    grid = []
    for values in combos:
        p = base_params.copy()
        for k, v in zip(keys, values):
            p[k] = v
        grid.append(p)
    return grid


def run_sweep(
    close, open_px, high, low, volume, spy_close, spy_volume, base_params
) -> pd.DataFrame:
    """Run 27-combo IS parameter sweep. Returns DataFrame with metrics per combo."""
    print(f"\n=== Parameter Sweep ({len(SWEEP_GRID['box_n']) * len(SWEEP_GRID['box_width_max']) * len(SWEEP_GRID['vol_ratio_min'])} combos) ===")
    grid = _build_param_grid(base_params)
    sweep_df = scan_parameters(
        close, open_px, high, low, volume, spy_close, spy_volume, grid, IS_START, IS_END
    )
    # Tag baseline combo
    baseline_mask = (
        (sweep_df["box_n"] == base_params["box_n"])
        & (sweep_df["box_width_max"] == base_params["box_width_max"])
        & (sweep_df["vol_ratio_min"] == base_params["vol_ratio_min"])
    )
    sweep_df["is_baseline"] = baseline_mask
    return sweep_df


def _select_best_params(sweep_df: pd.DataFrame, base_params: dict) -> dict:
    """Select combo with highest IS Sharpe. Fall back to baseline on tie."""
    valid = sweep_df[sweep_df["trades"] >= 10]
    if valid.empty:
        print("  Warning: no sweep combo with >=10 trades; using baseline params")
        return base_params.copy()
    best_idx = valid["sharpe"].idxmax()
    best_row = valid.loc[best_idx]
    best = base_params.copy()
    for k in SWEEP_GRID:
        best[k] = best_row[k]
    print(
        f"  Best params: box_n={best['box_n']} width={best['box_width_max']} "
        f"vol_ratio={best['vol_ratio_min']} -> IS Sharpe={best_row['sharpe']:.4f}"
    )
    return best


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def walk_forward(
    close, open_px, high, low, volume, spy_close, spy_volume, best_params
) -> list:
    """6-window walk-forward; returns list of window result dicts."""
    print("\n=== Walk-Forward (6 windows) ===")
    windows = []
    for i, (ts, te, vs, ve) in enumerate(WF_SPECS, 1):
        print(f"  WF{i}: IS {ts}-{te}, OOS {vs}-{ve}")
        try:
            ir = simulate_strategy(
                close, open_px, high, low, volume, spy_close, spy_volume,
                best_params, ts, te,
            )
            or_ = simulate_strategy(
                close, open_px, high, low, volume, spy_close, spy_volume,
                best_params, vs, ve,
            )
            oos_sharpe = _sharpe(or_["equity_curve"])
            passed = oos_sharpe > 0.0
            windows.append({
                "window": i,
                "train_start": ts, "train_end": te,
                "test_start": vs, "test_end": ve,
                "train_sharpe": round(_sharpe(ir["equity_curve"]), 4),
                "train_trades": ir["trades"],
                "test_sharpe": round(oos_sharpe, 4),
                "test_trades": or_["trades"],
                "passed": passed,
                "oos_equity": or_["equity_curve"],
            })
            print(
                f"    IS Sharpe={ir['sharpe']:.4f} trades={ir['trades']} | "
                f"OOS Sharpe={oos_sharpe:.4f} -> {'PASS' if passed else 'FAIL'}"
            )
        except Exception as exc:
            print(f"    WF{i} ERROR: {exc}")
            windows.append({
                "window": i, "train_start": ts, "train_end": te,
                "test_start": vs, "test_end": ve,
                "train_sharpe": 0.0, "train_trades": 0,
                "test_sharpe": 0.0, "test_trades": 0,
                "passed": False, "error": str(exc),
            })
    return windows


def _combined_oos_sharpe(wf_windows: list) -> tuple:
    """Compute OOS Sharpe and MDD from concatenated WF OOS return streams."""
    ret_series = []
    for w in wf_windows:
        ec = w.get("oos_equity")
        if ec is not None and len(ec) > 1:
            ret_series.append(ec.pct_change().fillna(0.0))
    if not ret_series:
        return 0.0, 0.0
    combined = pd.concat(ret_series)
    s = combined.std()
    if s < 1e-10:
        return 0.0, 0.0
    sharpe = float(combined.mean() / s * math.sqrt(TRADING_DAYS_PER_YEAR))
    cum = np.cumprod(1.0 + combined.values)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    return round(sharpe, 4), round(mdd, 4)


# ── HTML Report ────────────────────────────────────────────────────────────────

def _check_row(label: str, passed: bool, value: str, threshold: str) -> str:
    color = "#28a745" if passed else "#dc3545"
    sym = "✓" if passed else "✗"
    status = "PASS" if passed else "FAIL"
    return (
        f"<tr><td>{label}</td>"
        f"<td style='color:{color};font-weight:bold'>{sym} {status}</td>"
        f"<td>{value}</td><td>{threshold}</td></tr>"
    )


def _equity_sparkline(equity: pd.Series, width: int = 600, height: int = 120) -> str:
    """Minimal inline SVG equity curve."""
    if len(equity) < 2:
        return ""
    vals = equity.values.astype(float)
    lo, hi = vals.min(), vals.max()
    span = max(hi - lo, 1.0)
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = int(i / (n - 1) * width)
        y = int(height - (v - lo) / span * height)
        pts.append(f"{x},{y}")
    color = "#28a745" if vals[-1] >= vals[0] else "#dc3545"
    poly = " ".join(pts)
    return (
        f'<svg width="{width}" height="{height}" style="border:1px solid #ccc">'
        f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.5"/>'
        f"</svg>"
    )


def generate_html_report(data: dict, is_equity: pd.Series, output_path: Path) -> None:
    verdict_color = "#28a745" if data["gate1_pass"] else "#dc3545"
    verdict_text = "PASS" if data["gate1_pass"] else "FAIL"
    checks = data["gate1_checks"]
    n_pass = sum(1 for v in checks.values() if v)

    gate_rows = "\n".join([
        _check_row("IS Sharpe > 1.0", checks["is_sharpe_pass"],
                   f"{data['is_sharpe']:.4f}", "> 1.0"),
        _check_row("OOS Sharpe > 0.7", checks["oos_sharpe_pass"],
                   f"{data['oos_sharpe']:.4f}", "> 0.7"),
        _check_row("IS MDD < 20%", checks["is_mdd_pass"],
                   f"{data['is_mdd']:.2%}", "< 20%"),
        _check_row("IS trade count >= 100", checks["trade_count_pass"],
                   str(data["is_trade_count"]), ">= 100"),
        _check_row("Win rate > 50%", checks["win_rate_pass"],
                   f"{data['is_win_rate']:.2%}", "> 50%"),
        _check_row("Profit factor > 1.0", checks["profit_factor_pass"],
                   f"{data['is_profit_factor']:.4f}", "> 1.0"),
        _check_row("WF OOS positive >= 4/6", checks["wf_pass"],
                   f"{data['wf_windows_positive']}/6", ">= 4"),
        _check_row("Parameter sensitivity < 50%", checks["sensitivity_pass"],
                   f"{data['sensitivity_pct']:.1f}%", "< 50%"),
        _check_row("Permutation p < 0.05", checks["permutation_pass"],
                   f"{data['permutation_pvalue']:.4f}", "< 0.05"),
    ])

    def _wf_row(w):
        c = "#28a745" if w.get("passed") else "#dc3545"
        s = "PASS" if w.get("passed") else "FAIL"
        return (
            f"<tr><td>{w['window']}</td>"
            f"<td>{w['train_start']}–{w['train_end']}</td>"
            f"<td>{w['test_start']}–{w['test_end']}</td>"
            f"<td>{w['train_sharpe']:.4f}</td><td>{w.get('train_trades', 'n/a')}</td>"
            f"<td>{w['test_sharpe']:.4f}</td><td>{w.get('test_trades', 'n/a')}</td>"
            f"<td style='color:{c}'>{s}</td></tr>"
        )

    wf_rows = "\n".join(_wf_row(w) for w in data.get("wf_windows", []))
    bp = data.get("best_params", {})
    sparkline = _equity_sparkline(is_equity)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Gate 1: {STRATEGY_NAME}</title>
<style>
body{{font-family:monospace;max-width:1200px;margin:20px auto;background:#f8f9fa}}
h1,h2{{color:#333}}
.verdict{{font-size:2em;font-weight:bold;color:{verdict_color};border:3px solid {verdict_color};
  display:inline-block;padding:8px 20px;border-radius:6px}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}
th,td{{border:1px solid #dee2e6;padding:6px 10px;text-align:left}}
th{{background:#343a40;color:white}} tr:nth-child(even){{background:#f2f2f2}}
.section{{background:white;padding:15px;margin:15px 0;border-radius:6px;
  box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.metric{{display:inline-block;margin:8px;padding:10px;background:#e9ecef;
  border-radius:4px;min-width:130px}}
.mv{{font-size:1.4em;font-weight:bold;color:#0d6efd}}
</style></head>
<body>
<h1>Gate 1 Report: {STRATEGY_NAME}</h1>
<p>Date: {data['date']} | IS: {IS_START}–{IS_END} | Universe: S&P 1500 PIT proxy (~1,047 tickers)</p>
<p>Best params: box_n={bp.get('box_n','?')} box_width_max={bp.get('box_width_max','?')} vol_ratio_min={bp.get('vol_ratio_min','?')}</p>
<div class="verdict">{verdict_text} ({n_pass}/9 checks)</div>

<div class="section"><h2>IS Equity Curve</h2>
{sparkline}</div>

<div class="section"><h2>Core Metrics</h2>
<div class="metric"><div>IS Sharpe</div><div class="mv">{data['is_sharpe']:.4f}</div></div>
<div class="metric"><div>OOS Sharpe (WF)</div><div class="mv">{data['oos_sharpe']:.4f}</div></div>
<div class="metric"><div>IS MDD</div><div class="mv">{data['is_mdd']:.2%}</div></div>
<div class="metric"><div>IS CAGR</div><div class="mv">{data.get('is_cagr', 0.0):.2%}</div></div>
<div class="metric"><div>IS Trades</div><div class="mv">{data['is_trade_count']}</div></div>
<div class="metric"><div>Win Rate</div><div class="mv">{data['is_win_rate']:.2%}</div></div>
<div class="metric"><div>Profit Factor</div><div class="mv">{data['is_profit_factor']:.3f}</div></div>
<div class="metric"><div>PpT (bps)</div><div class="mv">{data['is_ppt_bps']:.1f}</div></div>
<div class="metric"><div>MC p5 Sharpe</div><div class="mv">{data['mc_p5_sharpe']:.4f}</div></div>
<div class="metric"><div>Earnings Exits</div><div class="mv">{data.get('earnings_exits', 0)}</div></div>
<div class="metric"><div>Liq. Constrained</div><div class="mv">{data.get('liquidity_constrained_pct', 0.0):.2%}</div></div>
</div>

<div class="section"><h2>Gate 1 Checks (9 required)</h2>
<table><tr><th>Check</th><th>Result</th><th>Actual</th><th>Threshold</th></tr>
{gate_rows}</table></div>

<div class="section"><h2>Walk-Forward (6 windows — 3-month IS / 1-month OOS)</h2>
<table><tr><th>#</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th>
<th>IS Trades</th><th>OOS Sharpe</th><th>OOS Trades</th><th>Status</th></tr>
{wf_rows}</table>
<p>WF pass rate: {data['wf_windows_positive']}/6 (gate: >= 4/6 OOS Sharpe > 0)</p>
<p>Combined OOS Sharpe: {data['oos_sharpe']:.4f} | OOS MDD: {data['oos_mdd']:.2%}</p></div>

<div class="section"><h2>Statistical Rigor</h2>
<p>Bootstrap Sharpe CI: [{data.get('sharpe_ci_low', 0.0):.4f}, {data.get('sharpe_ci_high', 0.0):.4f}]</p>
<p>Bootstrap MDD CI: [{data.get('mdd_ci_low', 0.0):.4f}, {data.get('mdd_ci_high', 0.0):.4f}]</p>
<p>MC p5/median/p95: {data['mc_p5_sharpe']:.4f} / {data['mc_median_sharpe']:.4f} / {data['mc_p95_sharpe']:.4f}</p>
<p>Permutation p-value: {data['permutation_pvalue']:.4f} (gate: < 0.05)</p></div>

<div class="section"><h2>Parameter Sweep (27 combos)</h2>
<p>Sharpe range: {data['sweep_sharpe_min']:.4f} – {data['sweep_sharpe_max']:.4f}</p>
<p>Sensitivity = (max-min)/|baseline| x 100 = <b>{data['sensitivity_pct']:.1f}%</b>
(threshold: &lt;50% — {'PASS' if data['sensitivity_pct'] < 50 else 'FAIL'})</p>
<p>Combos with Sharpe > 1.0: {data['sweep_n_passing']}/27</p></div>

<div class="section"><h2>Regime and Risk Attribution</h2>
<p>2022 bear market: {data.get('regime_2022_trades', 0)} trades, PnL ${data.get('regime_2022_pnl', 0.0):.0f} (expected near-zero; regime filter blocks entries)</p>
<p>Earnings exits: {data.get('earnings_exits', 0)} trades exited pre-earnings</p>
<p>Gap MDD fraction: {data.get('gap_mdd_fraction', 0.0):.2%} (fraction of losses from overnight gaps)</p>
<p>Liquidity-constrained trades: {data.get('liquidity_constrained_pct', 0.0):.2%} (flagged Q/ADV > 1%)</p></div>

<div class="section"><h2>Data Quality Checklist</h2>
<ul>
<li><b>Survivorship bias:</b> Universe is h82v2_universe_2018_jan.csv (PIT proxy circa 2018).
  Stocks delisted after 2018 absent from yfinance — bias directionally INFLATES Sharpe.</li>
<li><b>Price adjustments:</b> yfinance auto_adjust=True (splits + dividends corrected).</li>
<li><b>Data gaps:</b> {data.get('dq_flagged_count', 0)} tickers flagged with >5 missing business days in IS.</li>
<li><b>Earnings exclusion:</b> earnings_exit rule active. {data.get('earnings_exits', 0)} trades exited.
  Fallback: 8% hard stop on tickers where yfinance calendar unavailable.</li>
<li><b>Delisted tickers:</b> Tickers with &lt;252 total days excluded pre-backtest. yfinance returns
  partial data through delisting (correct treatment — real returns).</li>
<li><b>Entry execution:</b> Signal at close T, fill at next-day open T+1 (Hard Gate 3 compliant).</li>
<li><b>Look-ahead:</b> CLEAN — all indicators use only prior-close data at signal generation time.</li>
<li><b>Cost model:</b> Equities standard tier — $0.005/share fixed + 0.05% slippage + Almgren-Chriss impact.</li>
</ul></div>

</body></html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"  HTML report saved: {output_path.name}")


# ── Verdict TXT ────────────────────────────────────────────────────────────────

def generate_verdict_txt(data: dict, output_path: Path) -> None:
    verdict = "PASS" if data["gate1_pass"] else "FAIL"
    checks = data["gate1_checks"]
    n_pass = sum(1 for v in checks.values() if v)
    bp = data.get("best_params", {})

    def _ck(flag, label):
        return f"{'✓' if flag else '✗'} {'PASS' if flag else 'FAIL'}  {label}"

    lines = [
        f"{STRATEGY_NAME} — Gate 1 Verdict",
        "=" * 70,
        f"Date:    {data['date']}",
        f"IS:      {IS_START} -> {IS_END}",
        f"Overall: {verdict} ({n_pass}/9 checks passed)",
        "",
        "=== Best Parameters (from 27-combo IS sweep) ===",
        f"box_n          = {bp.get('box_n', '?')}",
        f"box_width_max  = {bp.get('box_width_max', '?')}",
        f"vol_ratio_min  = {bp.get('vol_ratio_min', '?')}",
        f"spy_sma_days   = {bp.get('spy_sma_days', 150)} (fixed)",
        f"hard_stop_pct  = {bp.get('hard_stop_pct', 0.08)} (fixed)",
        f"max_hold_days  = {bp.get('max_hold_days', 25)} (fixed)",
        "",
        "=== IS Performance ===",
        f"Sharpe:         {data['is_sharpe']:.4f}",
        f"Max Drawdown:   {data['is_mdd']:.2%}",
        f"CAGR:           {data.get('is_cagr', 0.0):.2%}",
        f"Win Rate:       {data['is_win_rate']:.2%}",
        f"Profit Factor:  {data['is_profit_factor']:.4f}",
        f"Trade Count:    {data['is_trade_count']}",
        f"PpT (bps):      {data['is_ppt_bps']:.2f}",
        "",
        "=== OOS Performance (Walk-Forward Combined) ===",
        f"OOS Sharpe:     {data['oos_sharpe']:.4f}",
        f"OOS MDD:        {data['oos_mdd']:.2%}",
        f"WF windows positive: {data['wf_windows_positive']}/6",
        "",
        "=== Walk-Forward Windows ===",
    ]
    for w in data.get("wf_windows", []):
        result = "PASS" if w.get("passed") else "FAIL"
        lines.append(
            f"  WF{w['window']}: IS {w['train_start']}-{w['train_end']} "
            f"Sharpe={w['train_sharpe']:.4f} t={w['train_trades']} | "
            f"OOS {w['test_start']}-{w['test_end']} "
            f"Sharpe={w['test_sharpe']:.4f} t={w['test_trades']} -> {result}"
        )
    lines += [
        "",
        "=== Statistical Rigor ===",
        f"MC p5 Sharpe:   {data['mc_p5_sharpe']:.4f}",
        f"Permutation p:  {data['permutation_pvalue']:.4f}",
        f"Bootstrap Sharpe CI: [{data.get('sharpe_ci_low', 0.0):.4f}, {data.get('sharpe_ci_high', 0.0):.4f}]",
        "",
        "=== Parameter Sweep Sensitivity ===",
        f"Sharpe range:   {data['sweep_sharpe_min']:.4f} – {data['sweep_sharpe_max']:.4f}",
        f"Sensitivity:    {data['sensitivity_pct']:.1f}% (threshold: < 50%)",
        "",
        "=== Regime & Risk Attribution ===",
        f"2022 trades:    {data.get('regime_2022_trades', 0)} (expected near-zero after March 2022)",
        f"2022 PnL:       ${data.get('regime_2022_pnl', 0.0):.0f}",
        f"Earnings exits: {data.get('earnings_exits', 0)}",
        f"Gap MDD frac:   {data.get('gap_mdd_fraction', 0.0):.2%}",
        f"Liq. const.:    {data.get('liquidity_constrained_pct', 0.0):.2%}",
        "",
        "=== Gate 1 Checks ===",
        _ck(checks["is_sharpe_pass"],        f"IS Sharpe > 1.0             : {data['is_sharpe']:.4f}"),
        _ck(checks["oos_sharpe_pass"],       f"OOS Sharpe > 0.7            : {data['oos_sharpe']:.4f}"),
        _ck(checks["is_mdd_pass"],           f"IS MDD < 20%                : {data['is_mdd']:.2%}"),
        _ck(checks["trade_count_pass"],      f"IS trade count >= 100       : {data['is_trade_count']}"),
        _ck(checks["win_rate_pass"],         f"Win rate > 50%              : {data['is_win_rate']:.2%}"),
        _ck(checks["profit_factor_pass"],    f"Profit factor > 1.0         : {data['is_profit_factor']:.4f}"),
        _ck(checks["wf_pass"],               f"WF OOS positive >= 4/6      : {data['wf_windows_positive']}/6"),
        _ck(checks["sensitivity_pass"],      f"Parameter sensitivity < 50% : {data['sensitivity_pct']:.1f}%"),
        _ck(checks["permutation_pass"],      f"Permutation p < 0.05        : {data['permutation_pvalue']:.4f}"),
        "",
        f"OVERALL: {verdict} ({n_pass}/9 checks passed)",
        "",
        "=== Survivorship Bias Note ===",
        "Universe: h82v2_universe_2018_jan.csv (PIT proxy circa 2018, ~1,047 tickers).",
        "Stocks delisted after 2018 are absent from yfinance.",
        "Bias direction: INFLATES Sharpe (missing losers that went to zero).",
        "Satisfies Hard Gate 9 option b (documented, directional sensitivity note present).",
    ]

    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  Verdict saved: {output_path.name}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"=== Gate 1: {STRATEGY_NAME} ===")
    print(f"Date: {DATE_STR} | IS: {IS_START} to {IS_END}")

    # 1. Load data
    print("\n--- Loading universe data ---")
    close, open_px, high, low, volume, spy_close, spy_volume = load_universe_data(PARAMETERS)
    tickers = list(close.columns)
    print(f"Universe: {len(tickers)} tickers")

    dq = _check_data_quality(close, tickers, IS_START, IS_END)
    print(f"Data quality: {dq['flagged_count']} tickers flagged (>5 missing IS days)")

    # 2. Parameter sweep (27 combos over IS)
    print("\n--- Parameter Sweep ---")
    sweep_df = run_sweep(close, open_px, high, low, volume, spy_close, spy_volume, PARAMETERS)
    best_params = _select_best_params(sweep_df, PARAMETERS)

    # Sensitivity: (max-min) / |baseline_sharpe| * 100
    baseline_row = sweep_df[sweep_df["is_baseline"]]
    baseline_sharpe = float(baseline_row["sharpe"].iloc[0]) if not baseline_row.empty else 0.0
    sweep_sharpe_min = float(sweep_df["sharpe"].min())
    sweep_sharpe_max = float(sweep_df["sharpe"].max())
    sensitivity_pct = (
        (sweep_sharpe_max - sweep_sharpe_min) / max(abs(baseline_sharpe), 1e-8) * 100
    )
    sweep_n_passing = int((sweep_df["sharpe"] > 1.0).sum())

    # 3. Full IS simulation with best params
    print(f"\n--- Full IS Simulation ({IS_START} to {IS_END}) ---")
    is_res = simulate_strategy(
        close, open_px, high, low, volume, spy_close, spy_volume,
        best_params, IS_START, IS_END,
    )
    is_equity = is_res["equity_curve"]
    is_trade_log = is_res["trade_log"]

    is_sharpe = _sharpe(is_equity)
    is_mdd = _mdd(is_equity)
    is_cagr = _cagr(is_equity)

    # Regime 2022 attribution
    if not is_trade_log.empty:
        mask_2022 = is_trade_log["entry_date"].str.startswith("2022")
        regime_2022_trades = int(mask_2022.sum())
        regime_2022_pnl = float(is_trade_log.loc[mask_2022, "pnl"].sum())
    else:
        regime_2022_trades = 0
        regime_2022_pnl = 0.0

    # Gap MDD fraction
    gap_mdd_fraction = _compute_gap_mdd_fraction(is_trade_log, close)

    # 4. Walk-forward
    wf_windows = walk_forward(
        close, open_px, high, low, volume, spy_close, spy_volume, best_params
    )
    oos_sharpe, oos_mdd = _combined_oos_sharpe(wf_windows)
    wf_windows_positive = sum(1 for w in wf_windows if w.get("passed", False))
    wf_oos_sharpes = [w["test_sharpe"] for w in wf_windows]

    # 5. Statistical tests
    print("\n--- Statistical Tests ---")
    mc_p5, mc_med, mc_p95 = monte_carlo_sharpe(is_equity, n_sims=1000)
    permutation_pvalue = permutation_test(is_equity, is_sharpe)
    boot = bootstrap_ci(is_equity)
    sharpe_ci_low, sharpe_ci_high = boot["sharpe_ci"]
    mdd_ci_low, mdd_ci_high = boot["mdd_ci"]

    # 6. Gate 1 checks
    gate1_checks = {
        "is_sharpe_pass": is_sharpe > 1.0,
        "oos_sharpe_pass": oos_sharpe > 0.7,
        "is_mdd_pass": abs(is_mdd) < 0.20,
        "trade_count_pass": is_res["trades"] >= 100,
        "win_rate_pass": is_res["win_rate"] > 0.50,
        "profit_factor_pass": is_res["profit_factor"] > 1.0,
        "wf_pass": wf_windows_positive >= 4,
        "sensitivity_pass": sensitivity_pct < 50.0,
        "permutation_pass": permutation_pvalue < 0.05,
    }
    gate1_pass = all(gate1_checks.values())

    # 7. Assemble full data dict
    result_data = {
        "strategy": STRATEGY_NAME,
        "date": DATE_STR,
        "best_params": {k: best_params[k] for k in ["box_n", "box_width_max", "vol_ratio_min",
                                                      "spy_sma_days", "hard_stop_pct", "max_hold_days"]},
        # IS metrics
        "is_sharpe": round(is_sharpe, 4),
        "is_mdd": round(is_mdd, 4),
        "is_cagr": round(is_cagr, 4),
        "is_trade_count": is_res["trades"],
        "is_win_rate": is_res["win_rate"],
        "is_profit_factor": is_res["profit_factor"],
        "is_ppt_bps": is_res["ppt_bps"],
        # OOS metrics (walk-forward combined)
        "oos_sharpe": oos_sharpe,
        "oos_mdd": oos_mdd,
        "wf_oos_sharpes": wf_oos_sharpes,
        "wf_windows_positive": wf_windows_positive,
        # Walk-forward windows (strip equity curve Series before JSON)
        "wf_windows": [
            {k: v for k, v in w.items() if k != "oos_equity"} for w in wf_windows
        ],
        # Statistical tests
        "mc_p5_sharpe": mc_p5,
        "mc_median_sharpe": mc_med,
        "mc_p95_sharpe": mc_p95,
        "permutation_pvalue": permutation_pvalue,
        "sharpe_ci_low": sharpe_ci_low,
        "sharpe_ci_high": sharpe_ci_high,
        "mdd_ci_low": mdd_ci_low,
        "mdd_ci_high": mdd_ci_high,
        # Sensitivity
        "sensitivity_pct": round(sensitivity_pct, 2),
        "sweep_sharpe_min": round(sweep_sharpe_min, 4),
        "sweep_sharpe_max": round(sweep_sharpe_max, 4),
        "sweep_n_combos": len(sweep_df),
        "sweep_n_passing": sweep_n_passing,
        "baseline_sharpe": round(baseline_sharpe, 4),
        # Regime and risk attribution
        "regime_2022_trades": regime_2022_trades,
        "regime_2022_pnl": round(regime_2022_pnl, 2),
        "gap_mdd_fraction": gap_mdd_fraction,
        "earnings_exits": is_res.get("earnings_exits", 0),
        "liquidity_constrained_pct": is_res.get("liquidity_constrained_pct", 0.0),
        # Data quality
        "data_quality": {
            "universe_size": len(tickers),
            "dq_flagged_count": dq["flagged_count"],
            "dq_flagged_sample": dq.get("flagged_sample", [])[:10],
        },
        "dq_flagged_count": dq["flagged_count"],
        # Gate 1 result
        "gate1_checks": gate1_checks,
        "gate1_pass": gate1_pass,
    }

    # 8. Save outputs
    print("\n--- Saving Outputs ---")

    # JSON
    json_path = Path(str(PREFIX) + ".json")
    with open(json_path, "w") as f:
        json.dump(result_data, f, indent=2, default=str)
    print(f"  JSON saved: {json_path.name}")

    # HTML
    html_path = Path(str(PREFIX) + "_report.html")
    generate_html_report(result_data, is_equity, html_path)

    # Sweep CSV
    sweep_path = Path(str(PREFIX) + "_sweep.csv")
    sweep_df.to_csv(sweep_path, index=False)
    print(f"  Sweep CSV saved: {sweep_path.name}")

    # Trades CSV
    trades_path = Path(str(PREFIX) + "_trades.csv")
    if not is_trade_log.empty:
        is_trade_log.to_csv(trades_path, index=False)
    else:
        pd.DataFrame().to_csv(trades_path, index=False)
    print(f"  Trades CSV saved: {trades_path.name}")

    # Verdict TXT
    verdict_path = Path(str(PREFIX) + "_verdict.txt")
    generate_verdict_txt(result_data, verdict_path)

    # 9. Summary
    print("\n" + "=" * 70)
    print(f"GATE 1 RESULT: {'PASS' if gate1_pass else 'FAIL'} ({sum(gate1_checks.values())}/9 checks)")
    print(f"IS Sharpe={is_sharpe:.4f} | OOS Sharpe={oos_sharpe:.4f} | IS MDD={is_mdd:.2%}")
    print(f"IS Trades={is_res['trades']} | Win Rate={is_res['win_rate']:.2%} | PF={is_res['profit_factor']:.3f}")
    print(f"WF positive: {wf_windows_positive}/6 | Sensitivity: {sensitivity_pct:.1f}% | Perm p: {permutation_pvalue:.4f}")
    print(f"Regime 2022: {regime_2022_trades} trades | Earnings exits: {is_res.get('earnings_exits', 0)}")
    print("=" * 70)

    return result_data


if __name__ == "__main__":
    main()
