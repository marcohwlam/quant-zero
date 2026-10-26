"""
H87v2 Darvas Box Breakout — Gate 1 Backtest
QUA-423

IS period:     2023-01-01 to 2025-09-30 (composite of 4 WF IS windows)
OOS:           Walk-forward OOS composite (4 × 3-month OOS windows)
Full range:    2023-01-01 to 2025-12-31

H87v2 changes from H87:
  IS period:    2022–2024 → 2023–2025 (remove 2022 bear contamination)
  Walk-forward: 6×(3mo IS/1mo OOS) → 4×(6mo IS/3mo OOS)
  box_n sweep:  [15,20,25] → [20,25,30] (box_n=15 negative IS Sharpe in H87)

Walk-Forward Windows (from QUA-423):
  WF1: IS 2023-01-01–2023-06-30, OOS 2023-07-01–2023-09-30
  WF2: IS 2023-10-01–2024-03-31, OOS 2024-04-01–2024-06-30
  WF3: IS 2024-07-01–2024-12-31, OOS 2025-01-01–2025-03-31
  WF4: IS 2025-04-01–2025-09-30, OOS 2025-10-01–2025-12-31

Parameter Grid (27 combos — 3×3×3):
  box_n:         [20, 25, 30]
  box_width_max: [0.08, 0.10, 0.12]
  vol_ratio_min: [1.20, 1.30, 1.40]

Gate 1 Criteria:
  IS Sharpe > 1.0 (composite over WF IS windows)
  OOS Sharpe > 0.7 (composite over WF OOS windows, trade-weighted)
  IS MDD < 20%
  IS trade count >= 100
  IS win rate > 50%
  IS profit factor > 1.0
  DSR > 0
  WF OOS Sharpe > 0 windows: >= 3/4
  Parameter sensitivity < 100% (H87v2 specific — box_n=15 removed)
  Permutation p < 0.05

Family: H87v2 is iteration 2/2 of the Darvas Box family.
  Retire family if this fails Gate 1. Do not run H87v3.
"""

import sys
import os
import json
import warnings
import math
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date
from itertools import product as iproduct

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

# Add repo root to path so we can import the strategy module
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "strategies"))

import h87v2_darvas_box_breakout as strat

TODAY = date.today().isoformat()
STRATEGY_NAME = "H87v2_DarvasBoxBreakout_RegimeAdjusted"
OUT_DIR = REPO_ROOT / "backtests"
TRADING_DAYS = 252

# Full composite IS and OOS periods
IS_START  = "2023-01-01"
IS_END    = "2025-09-30"   # union of all 4 WF IS windows ends; OOS windows are 10–12/2025

# H87v2 Walk-Forward Windows (4 × 6mo IS / 3mo OOS)
WF_WINDOWS = [
    ("2023-01-01", "2023-06-30", "2023-07-01", "2023-09-30"),  # WF1
    ("2023-10-01", "2024-03-31", "2024-04-01", "2024-06-30"),  # WF2
    ("2024-07-01", "2024-12-31", "2025-01-01", "2025-03-31"),  # WF3
    ("2025-04-01", "2025-09-30", "2025-10-01", "2025-12-31"),  # WF4
]

# Parameter grid: 27 combos (3×3×3) — H87v2 change: box_n=[20,25,30] (was [15,20,25])
SWEEP_BOX_N      = [20, 25, 30]
SWEEP_WIDTH_MAX  = [0.08, 0.10, 0.12]
SWEEP_VOL_RATIO  = [1.20, 1.30, 1.40]

BASE_PARAMS = dict(strat.PARAMETERS)  # default params from strategy module


# ── Metrics ───────────────────────────────────────────────────────────────────────

def compute_metrics(equity: pd.Series, trade_log: pd.DataFrame, label: str) -> dict:
    pv = equity.dropna()
    if len(pv) < 2:
        return {"label": label, "sharpe": 0.0, "mdd": 0.0, "total_return": 0.0,
                "win_rate": 0.0, "profit_factor": 0.0, "trade_count": 0, "_ret": np.array([])}
    ret = pv.pct_change().fillna(0.0).values
    sharpe = float(ret.mean() / (ret.std() + 1e-10) * np.sqrt(TRADING_DAYS))
    cum      = np.cumprod(1 + ret)
    roll_max = np.maximum.accumulate(cum)
    mdd      = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_ret = float(cum[-1] - 1.0)

    if isinstance(trade_log, pd.DataFrame) and not trade_log.empty:
        closed_df = trade_log[trade_log["reason"] != "end_of_period"]
        n_closed = len(closed_df)
        if n_closed > 0:
            pnl_arr = closed_df["pnl"].values
            win_rate = float(np.mean(pnl_arr > 0))
            wins = pnl_arr[pnl_arr > 0].sum()
            losses = abs(pnl_arr[pnl_arr < 0].sum())
            pf = float(wins / max(losses, 1e-8))
            pf = float("inf") if pf > 1e6 else pf
        else:
            win_rate = 0.0
            pf = 0.0
        trade_count = n_closed
    else:
        win_rate = 0.0
        pf = 0.0
        trade_count = 0

    return {
        "label": label,
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4),
        "total_return": round(total_ret, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": pf,
        "trade_count": trade_count,
        "_ret": ret,
    }


# ── Statistical Tests ─────────────────────────────────────────────────────────────

def monte_carlo_sharpe(trade_log: pd.DataFrame, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    if isinstance(trade_log, pd.DataFrame) and not trade_log.empty:
        pnl_arr = trade_log["pnl"].values
    else:
        pnl_arr = np.array([0.0])
    if len(pnl_arr) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    sharpes = []
    for _ in range(n_sims):
        s  = np.random.choice(pnl_arr, size=len(pnl_arr), replace=True)
        sh = s.mean() / (s.std() + 1e-8) * np.sqrt(TRADING_DAYS)
        sharpes.append(sh)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe":    float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    np.random.seed(43)
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks  = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s: s + block_len] for s in starts])[:T]
        if len(sample) < 2:
            continue
        cum      = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        sh  = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS))
        wr  = float(np.mean(sample > 0))
        sharpes.append(sh); mdds.append(mdd); win_rates.append(wr)
    if not sharpes:
        return {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
                "mdd_ci_low": 0.0,    "mdd_ci_high": 0.0,
                "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0}
    return {
        "sharpe_ci_low":    float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high":   float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":       float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":      float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low":  float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def compute_dsr(is_sharpe: float, n_trials: int, T: int) -> float:
    if T <= 0 or n_trials <= 1:
        return float(is_sharpe)
    gamma  = 0.5772
    ln_n   = np.log(max(n_trials, 2))
    exp_max = (
        np.sqrt(2 * ln_n)
        - (np.log(np.log(max(n_trials, 2))) + np.log(4 * np.pi)) / (2 * np.sqrt(2 * ln_n))
        + gamma / np.sqrt(2 * ln_n)
    ) / np.sqrt(T)
    return round(float(is_sharpe - exp_max), 4)


def permutation_test(equity: pd.Series, observed_sharpe: float, n_perms: int = 500) -> dict:
    np.random.seed(44)
    returns = equity.pct_change().fillna(0.0).values
    T = len(returns)
    if T < 20:
        return {"permutation_pvalue": 0.5, "permutation_test_pass": False}
    perm_sharpes = []
    for _ in range(n_perms):
        shuffled = np.random.permutation(returns)
        s = float(shuffled.mean() / (shuffled.std() + 1e-8) * np.sqrt(TRADING_DAYS))
        perm_sharpes.append(s)
    perm_np = np.array(perm_sharpes)
    p_value = float(np.mean(perm_np >= observed_sharpe))
    return {
        "permutation_pvalue":    round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(oos_sharpes: list) -> dict:
    arr = np.array([s for s in oos_sharpes if s is not None])
    if len(arr) == 0:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


# ── Walk-Forward ─────────────────────────────────────────────────────────────────

def run_walk_forward(
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
    spy_close: pd.Series,
    spy_volume: pd.Series,
    params: dict,
) -> list:
    """
    Run 4 walk-forward windows using pre-loaded data and fixed params.
    Each window: IS to find best combo (param sensitivity only) → OOS eval.
    For computational efficiency, uses fixed default params for all windows.
    """
    results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(WF_WINDOWS):
        wf_num = i + 1
        print(f"  WF{wf_num}: IS {is_s}–{is_e} | OOS {oos_s}–{oos_e}")
        try:
            is_res = strat.simulate_strategy(
                close, open_px, high, low, volume, spy_close, spy_volume,
                params, is_s, is_e,
            )
            is_m = compute_metrics(is_res["equity_curve"], is_res["trade_log"], f"WF{wf_num}_IS")

            oos_res = strat.simulate_strategy(
                close, open_px, high, low, volume, spy_close, spy_volume,
                params, oos_s, oos_e,
            )
            oos_m = compute_metrics(oos_res["equity_curve"], oos_res["trade_log"], f"WF{wf_num}_OOS")

            print(f"    IS  Sharpe={is_m['sharpe']:.4f} MDD={is_m['mdd']:.2%} trades={is_m['trade_count']}")
            print(f"    OOS Sharpe={oos_m['sharpe']:.4f} MDD={oos_m['mdd']:.2%} trades={oos_m['trade_count']}")

            results.append({
                "window":      wf_num,
                "is_start":    is_s,   "is_end":   is_e,
                "oos_start":   oos_s,  "oos_end":  oos_e,
                "is_sharpe":   is_m["sharpe"],
                "oos_sharpe":  oos_m["sharpe"],
                "is_mdd":      is_m["mdd"],
                "oos_mdd":     oos_m["mdd"],
                "is_trades":   is_m["trade_count"],
                "oos_trades":  oos_m["trade_count"],
                "is_win_rate": is_m["win_rate"],
                "wf_pass":     oos_m["sharpe"] > 0.0,
            })
        except Exception as e:
            print(f"    WF{wf_num} ERROR: {e}")
            results.append({
                "window": wf_num, "error": str(e), "wf_pass": False,
                "is_sharpe": 0.0, "oos_sharpe": 0.0,
                "is_start": is_s, "is_end": is_e,
                "oos_start": oos_s, "oos_end": oos_e,
                "is_trades": 0, "oos_trades": 0,
            })
    return results


# ── Parameter Sweep ───────────────────────────────────────────────────────────────

def run_sweep(
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
    spy_close: pd.Series,
    spy_volume: pd.Series,
    start: str,
    end: str,
) -> list:
    """
    H87v2 parameter grid: 27 combos (3×3×3).
    box_n [20,25,30] × box_width_max [0.08,0.10,0.12] × vol_ratio_min [1.20,1.30,1.40]
    H87v2 change: box_n=15 removed (produced negative IS Sharpe in H87; inflated sensitivity).
    """
    combos = list(iproduct(SWEEP_BOX_N, SWEEP_WIDTH_MAX, SWEEP_VOL_RATIO))
    print(f"  {len(combos)} sweep combinations (3×3×3: box_n × width_max × vol_ratio)...")
    rows = []
    for i, (bn, wm, vr) in enumerate(combos):
        p = {**BASE_PARAMS, "box_n": bn, "box_width_max": wm, "vol_ratio_min": vr}
        try:
            res = strat.simulate_strategy(
                close, open_px, high, low, volume, spy_close, spy_volume,
                p, start, end,
            )
            rows.append({
                "box_n": bn, "box_width_max": wm, "vol_ratio_min": vr,
                "sharpe":        res["sharpe"],
                "mdd":           res["mdd"],
                "win_rate":      res["win_rate"],
                "profit_factor": res["profit_factor"],
                "trade_count":   res["trades"],
                "ppt_bps":       res["ppt_bps"],
            })
            if (i + 1) % 9 == 0:
                print(f"    {i+1}/{len(combos)} done...")
        except Exception as e:
            rows.append({
                "box_n": bn, "box_width_max": wm, "vol_ratio_min": vr,
                "error": str(e),
            })
    return rows


# ── HTML Report ───────────────────────────────────────────────────────────────────

def build_html_report(
    is_m: dict, checks: list, verdict_label: str,
    mc: dict, bb: dict, perm: dict, dsr_val: float,
    wf_results: list, sweep_rows: list,
    composite_oos_sharpe: float, wf_passed: int,
) -> str:
    vc = "#d4edda" if verdict_label == "PASS" else "#f8d7da"
    check_rows = "".join(
        f"<tr style='background:{'#d4edda' if p else '#f8d7da'}'>"
        f"<td>{g}</td><td>{v}</td><td>{t}</td><td>{'&#10003; PASS' if p else '&#10007; FAIL'}</td></tr>"
        for g, v, t, p in checks
    )
    wf_rows = "".join(
        f"<tr style='background:{'#d4edda' if w.get('wf_pass') else '#f8d7da'}'>"
        f"<td>WF{w['window']}</td>"
        f"<td>{w.get('is_start','')} to {w.get('is_end','')}</td>"
        f"<td>{w.get('is_sharpe', 0):.4f}</td>"
        f"<td>{w.get('oos_start','')} to {w.get('oos_end','')}</td>"
        f"<td>{w.get('oos_sharpe', 0):.4f}</td>"
        f"<td>{w.get('is_trades', 0)}</td><td>{w.get('oos_trades', 0)}</td>"
        f"<td>{'&#10003;' if w.get('wf_pass') else '&#10007;'}</td></tr>"
        for w in wf_results
    )
    sweep_df = pd.DataFrame(sweep_rows)
    sweep_html = (
        sweep_df.to_html(index=False, border=1,
                         float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x))
        if not sweep_df.empty else "<p>N/A</p>"
    )
    pf = is_m.get("profit_factor", 0)
    pf_str = f"{pf:.4f}" if isinstance(pf, (int, float)) and pf != float("inf") else "inf"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>H87v2 Darvas Box Breakout — Gate 1</title>
<style>
body {{ font-family: monospace; max-width: 1400px; margin: 0 auto; padding: 20px; }}
h1 {{ background: #343a40; color: white; padding: 15px; border-radius: 4px; }}
h2 {{ border-bottom: 2px solid #343a40; padding-bottom: 5px; margin-top: 30px; }}
.verdict {{ font-size: 2em; font-weight: bold; padding: 15px; border-radius: 4px;
           background: {vc}; text-align: center; margin: 20px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th {{ background: #343a40; color: white; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border: 1px solid #dee2e6; }}
.section {{ margin: 20px 0; padding: 15px; border: 1px solid #dee2e6; border-radius: 4px; }}
.note {{ background: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>H87v2 Darvas Box Breakout — Regime-Adjusted Gate 1</h1>
<p><strong>Date:</strong> {TODAY} | <strong>Issue:</strong> QUA-423 | <strong>Parent:</strong> QUA-422</p>
<p><strong>Universe:</strong> S&P 500 + S&P 400 (~1,047 PIT tickers, h82v2_universe_2018_jan.csv)</p>
<p><strong>H87v2 changes:</strong> IS 2023+ (2022 bear removed) | WF 4×(6mo IS/3mo OOS) | box_n [20,25,30]</p>
<p><strong>IS period:</strong> {IS_START} to {IS_END} (composite of 4 WF IS windows)</p>
<p><strong>OOS:</strong> Walk-forward composite ({len(WF_WINDOWS)} windows, 3mo OOS each)</p>
<p><strong>Composite OOS Sharpe:</strong> {composite_oos_sharpe:.4f} | <strong>WF OOS positive:</strong> {wf_passed}/{len(WF_WINDOWS)}</p>
<p><strong>Gate 1 criteria:</strong> IS Sharpe &gt; 1.0 | Composite OOS Sharpe &gt; 0.7 | IS MDD &lt; 20% | IS trades &ge; 100 | Win rate &gt; 50% | PF &gt; 1.0 | DSR &gt; 0 | WF OOS &ge; 3/4 | Sensitivity &lt; 100% | Permutation p &lt; 0.05</p>
<p><strong>Cost model:</strong> $0.005/share + 0.05% slip + 0.1&times;&sigma;&times;&radic;(Q/ADV) (ED-SLIP-001)</p>
<div class="note"><strong>Family note:</strong> H87v2 is iteration 2/2 of the Darvas Box family. Retire family if this fails Gate 1.</div>

<div class="verdict">GATE 1: {verdict_label}</div>

<h2>Gate 1 Checklist</h2>
<table>
<tr><th>Gate</th><th>Value</th><th>Threshold</th><th>Result</th></tr>
{check_rows}
</table>

<h2>IS Performance ({IS_START} to {IS_END})</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>IS Value</th></tr>
<tr><td>Sharpe</td><td>{is_m['sharpe']:.4f}</td></tr>
<tr><td>Max Drawdown</td><td>{is_m['mdd']:.2%}</td></tr>
<tr><td>Total Return</td><td>{is_m['total_return']:.2%}</td></tr>
<tr><td>Win Rate</td><td>{is_m['win_rate']:.2%}</td></tr>
<tr><td>Profit Factor</td><td>{pf_str}</td></tr>
<tr><td>Trade Count (closed)</td><td>{is_m['trade_count']}</td></tr>
</table>
</div>

<h2>Statistical Tests</h2>
<div class="section">
<p><strong>Monte Carlo (1000 resamples, PnL bootstrap):</strong> p5={mc['mc_p5_sharpe']:.4f}, median={mc['mc_median_sharpe']:.4f}, p95={mc['mc_p95_sharpe']:.4f}
   {'&#9888; MC p5 &lt; 0.5 — pessimistic bound weak' if mc['mc_p5_sharpe'] < 0.5 else '&#10003;'}</p>
<p><strong>Block Bootstrap CI (95%, daily returns):</strong> Sharpe [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}] | MDD [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]</p>
<p><strong>Permutation test (500 perms, IS equity):</strong> p={perm['permutation_pvalue']:.4f} — {'&#10003; PASS' if perm['permutation_test_pass'] else '&#10007; FAIL (no significant alpha)'}</p>
<p><strong>DSR (deflated Sharpe ratio):</strong> {dsr_val:.4f} — {'&#10003; PASS' if dsr_val > 0 else '&#10007; FAIL'}</p>
</div>

<h2>Walk-Forward Analysis (4 windows — 6mo IS / 3mo OOS)</h2>
<table>
<tr><th>Win</th><th>IS Period</th><th>IS Sharpe</th><th>OOS Period</th><th>OOS Sharpe</th><th>IS Trades</th><th>OOS Trades</th><th>Pass</th></tr>
{wf_rows}
</table>
<p><strong>Composite OOS Sharpe (trade-weighted):</strong> {composite_oos_sharpe:.4f} | Positive OOS windows: {wf_passed}/{len(WF_WINDOWS)}</p>

<h2>Parameter Sweep ({len(sweep_rows)} combinations — 3&times;3&times;3)</h2>
<p>H87v2 grid: box_n [20,25,30] &times; box_width_max [0.08,0.10,0.12] &times; vol_ratio_min [1.20,1.30,1.40]</p>
<p>H87v2 change: box_n=15 removed (produced negative IS Sharpe in H87; inflated sensitivity stat to 290%)</p>
{sweep_html}

<hr>
<p><em>Backtest Runner Agent | QUA-423 | H87v2 Gate 1 | {TODAY}</em></p>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H87v2 Darvas Box Breakout — Gate 1 Backtest")
    print(f"QUA-423 | {TODAY}")
    print(f"IS composite: {IS_START} to {IS_END}")
    print(f"Walk-forward: {len(WF_WINDOWS)} windows (4 × 6mo IS / 3mo OOS)")
    print(f"Parameter grid: {len(list(iproduct(SWEEP_BOX_N, SWEEP_WIDTH_MAX, SWEEP_VOL_RATIO)))} combos")
    print("=" * 70)

    # ── [1] Load Universe Data ──────────────────────────────────────────────────
    print("\n[1/6] Loading universe data (yfinance batch download)...")
    print("  Strategy: h87v2_darvas_box_breakout.py")
    print("  Universe: data/h82v2_universe_2018_jan.csv (S&P 500 + S&P 400 PIT proxy)")
    print("  Data range: 2022-01-01 to 2026-01-15 (buffer for 52wk high + WF4 OOS)")
    close, open_px, high, low, volume, spy_close, spy_volume = strat.load_universe_data(BASE_PARAMS)
    print(f"  Loaded: {len(close.columns)} tickers × {len(close)} days")

    # ── [2] Data Quality Check ──────────────────────────────────────────────────
    print("\n[2/6] Data quality check...")
    tickers = list(close.columns)
    dq = strat._check_data_quality(close, tickers, IS_START, IS_END)
    print(f"  Flagged (>5 missing days in IS): {dq['flagged_count']} / {dq['total_tickers']}")
    if dq["flagged_sample"]:
        print(f"  Sample flagged: {dq['flagged_sample'][:5]}")

    # ── [3] IS Simulation (composite IS period) ─────────────────────────────────
    print(f"\n[3/6] IS Simulation {IS_START} → {IS_END} (default params)...")
    is_res = strat.simulate_strategy(
        close, open_px, high, low, volume, spy_close, spy_volume,
        BASE_PARAMS, IS_START, IS_END,
    )
    is_m = compute_metrics(is_res["equity_curve"], is_res["trade_log"], "IS")
    pf_str = f"{is_m['profit_factor']:.4f}" if isinstance(is_m['profit_factor'], float) else str(is_m['profit_factor'])
    print(f"  Sharpe={is_m['sharpe']:.4f} | MDD={is_m['mdd']:.2%} | "
          f"trades={is_m['trade_count']} | WR={is_m['win_rate']:.2%} | "
          f"PF={pf_str}")

    # ── [4] Statistical Tests ────────────────────────────────────────────────────
    print("\n[4/6] Statistical rigor pipeline...")
    ret_arr_is = is_res["equity_curve"].pct_change().fillna(0.0).values
    mc      = monte_carlo_sharpe(is_res["trade_log"])
    bb      = block_bootstrap_ci(ret_arr_is)
    perm    = permutation_test(is_res["equity_curve"], is_m["sharpe"])
    n_combos = len(list(iproduct(SWEEP_BOX_N, SWEEP_WIDTH_MAX, SWEEP_VOL_RATIO)))
    dsr_val = compute_dsr(is_m["sharpe"], n_combos + len(WF_WINDOWS), len(ret_arr_is))
    print(f"  MC p5={mc['mc_p5_sharpe']:.3f} | BB CI=[{bb['sharpe_ci_low']:.3f},{bb['sharpe_ci_high']:.3f}]")
    print(f"  Perm p={perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'}) | DSR={dsr_val:.4f}")

    # ── [5] Walk-Forward ─────────────────────────────────────────────────────────
    print(f"\n[5/6] Walk-forward ({len(WF_WINDOWS)} windows)...")
    wf_results = run_walk_forward(
        close, open_px, high, low, volume, spy_close, spy_volume, BASE_PARAMS
    )
    oos_sharpes = [w.get("oos_sharpe", 0.0) for w in wf_results]
    oos_trades  = [w.get("oos_trades", 0)   for w in wf_results]
    wf_passed   = sum(1 for w in wf_results if w.get("wf_pass", False))
    wf_var      = walk_forward_variance(oos_sharpes)

    # Composite OOS Sharpe: trade-weighted average across WF OOS windows
    total_oos_trades = sum(oos_trades)
    if total_oos_trades > 0:
        composite_oos_sharpe = float(
            sum(s * t for s, t in zip(oos_sharpes, oos_trades)) / total_oos_trades
        )
    else:
        composite_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0

    print(f"  Composite OOS Sharpe (trade-weighted): {composite_oos_sharpe:.4f}")
    print(f"  WF OOS Sharpe>0: {wf_passed}/{len(WF_WINDOWS)} | std={wf_var['wf_sharpe_std']:.3f} | min={wf_var['wf_sharpe_min']:.3f}")

    # ── [6] Parameter Sweep ──────────────────────────────────────────────────────
    print(f"\n[6/6] Parameter sweep (27 combos — 3×3×3) over IS period...")
    sweep_rows = run_sweep(
        close, open_px, high, low, volume, spy_close, spy_volume,
        IS_START, IS_END,
    )
    valid_sh = [r["sharpe"] for r in sweep_rows if "sharpe" in r and isinstance(r.get("sharpe"), float)]
    if valid_sh:
        sr_range  = max(valid_sh) - min(valid_sh)
        sr_base   = abs(is_m["sharpe"]) if is_m["sharpe"] != 0 else 1.0
        sens_var_pct = sr_range / sr_base
        sens_pass = sens_var_pct < 1.00  # H87v2 threshold: < 100% (vs <50% std)
        print(f"  Sharpe range: {min(valid_sh):.3f}–{max(valid_sh):.3f} | var={sens_var_pct:.1%} | "
              f"{'PASS (< 100%)' if sens_pass else 'FAIL'}")
        print(f"  Note: H87 had 290% sensitivity from box_n=15; H87v2 removes that combo")
    else:
        sens_pass = False
        sens_var_pct = float("nan")

    # ── Gate 1 Checklist ─────────────────────────────────────────────────────────
    pf_val = is_m["profit_factor"]
    pf_str = f"{pf_val:.4f}" if isinstance(pf_val, (int, float)) and pf_val != float("inf") else "inf"

    gate_is_sharpe    = is_m["sharpe"] > 1.0
    gate_oos_sharpe   = composite_oos_sharpe > 0.7
    gate_is_mdd       = is_m["mdd"] > -0.20
    gate_trades       = is_m["trade_count"] >= 100
    gate_win_rate     = is_m["win_rate"] > 0.50
    gate_pf           = (isinstance(pf_val, (int, float)) and pf_val > 1.0) or pf_val == float("inf")
    gate_dsr          = dsr_val > 0.0
    gate_wf           = wf_passed >= 3
    gate_sens         = sens_pass
    gate_perm         = perm["permutation_test_pass"]

    checks = [
        ("IS Sharpe",                   f"{is_m['sharpe']:.4f}",             "> 1.0",     gate_is_sharpe),
        ("Composite OOS Sharpe (WF)",   f"{composite_oos_sharpe:.4f}",       "> 0.7",     gate_oos_sharpe),
        ("IS Max Drawdown",             f"{is_m['mdd']:.2%}",                "< 20%",     gate_is_mdd),
        ("IS Trade Count",              str(is_m["trade_count"]),             ">= 100",    gate_trades),
        ("IS Win Rate",                 f"{is_m['win_rate']:.2%}",           "> 50%",     gate_win_rate),
        ("IS Profit Factor",            pf_str,                               "> 1.0",     gate_pf),
        ("DSR",                         f"{dsr_val:.4f}",                     "> 0",       gate_dsr),
        ("WF OOS Sharpe>0 windows",     f"{wf_passed}/{len(WF_WINDOWS)}",    ">= 3/4",    gate_wf),
        ("Parameter Sensitivity",       f"{sens_var_pct:.1%}" if not (isinstance(sens_var_pct, float) and math.isnan(sens_var_pct)) else "N/A",
                                        "< 100% SR range",                                 gate_sens),
        ("Permutation Test",            f"p={perm['permutation_pvalue']:.4f}", "p < 0.05", gate_perm),
    ]

    n_passed      = sum(1 for *_, p in checks if p)
    verdict_label = "PASS" if all(p for *_, p in checks) else "FAIL"

    print(f"\n{'='*70}")
    print(f"H87v2 — GATE 1 VERDICT: {verdict_label} ({n_passed}/{len(checks)} checks)")
    for g, v, t, p in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {g:<35} {v}  (threshold: {t})")
    print(f"{'='*70}")

    # ── Save Outputs ─────────────────────────────────────────────────────────────
    base = f"H87v2_DarvasBoxBreakout_{TODAY}"

    # Trades CSV
    all_trades = is_res["trade_log"]
    trades_path = OUT_DIR / f"{base}_trades.csv"
    if isinstance(all_trades, pd.DataFrame) and not all_trades.empty:
        all_trades.to_csv(trades_path, index=False)
        print(f"[SAVE] Trades: {trades_path} ({len(all_trades)} rows)")

    # Sweep CSV
    sweep_path = OUT_DIR / f"{base}_sweep.csv"
    if sweep_rows:
        pd.DataFrame(sweep_rows).to_csv(sweep_path, index=False)
        print(f"[SAVE] Sweep: {sweep_path} ({len(sweep_rows)} combos)")

    # HTML Report
    html = build_html_report(
        is_m, checks, verdict_label, mc, bb, perm, dsr_val,
        wf_results, sweep_rows, composite_oos_sharpe, wf_passed,
    )
    html_path = OUT_DIR / f"{base}_report.html"
    html_path.write_text(html)
    print(f"[SAVE] Report: {html_path}")

    # JSON Metrics
    metrics = {
        "strategy_name":              STRATEGY_NAME,
        "date":                       TODAY,
        "issue":                      "QUA-423",
        "parent_issue":               "QUA-422",
        "version":                    "H87v2",
        "asset_class":                "equities",
        "h87v2_changes": {
            "is_period":              "2023-01-01 to 2025-12-31 (removed 2022 bear contamination)",
            "walk_forward":           "4 × (6mo IS / 3mo OOS)",
            "box_n_sweep":            "[20, 25, 30] (removed box_n=15)",
        },
        "is_sharpe":                  is_m["sharpe"],
        "composite_oos_sharpe":       composite_oos_sharpe,
        "is_mdd":                     is_m["mdd"],
        "is_win_rate":                is_m["win_rate"],
        "is_profit_factor":           pf_str,
        "is_trade_count":             is_m["trade_count"],
        "is_total_return":            is_m["total_return"],
        "dsr":                        dsr_val,
        "gate1_pass":                 verdict_label == "PASS",
        "overall_verdict":            verdict_label,
        "n_checks_passed":            n_passed,
        "n_checks_total":             len(checks),
        "mc_p5_sharpe":               mc["mc_p5_sharpe"],
        "mc_median_sharpe":           mc["mc_median_sharpe"],
        "mc_p95_sharpe":              mc["mc_p95_sharpe"],
        "sharpe_ci_low":              bb["sharpe_ci_low"],
        "sharpe_ci_high":             bb["sharpe_ci_high"],
        "mdd_ci_low":                 bb["mdd_ci_low"],
        "mdd_ci_high":                bb["mdd_ci_high"],
        "win_rate_ci_low":            bb["win_rate_ci_low"],
        "win_rate_ci_high":           bb["win_rate_ci_high"],
        "permutation_pvalue":         perm["permutation_pvalue"],
        "permutation_test_pass":      perm["permutation_test_pass"],
        "wf_windows_passed":          wf_passed,
        "wf_sharpe_std":              wf_var["wf_sharpe_std"],
        "wf_sharpe_min":              wf_var["wf_sharpe_min"],
        "sensitivity_pass":           sens_pass,
        "sensitivity_sharpe_var_pct": float(sens_var_pct) if not (isinstance(sens_var_pct, float) and math.isnan(sens_var_pct)) else None,
        "base_params":                BASE_PARAMS,
        "is_period":                  f"{IS_START} to {IS_END}",
        "wf_windows":                 wf_results,
        "checks":                     [
            {"gate": g, "value": v, "threshold": t, "passed": p}
            for g, v, t, p in checks
        ],
        "data_quality":               dq,
        "survivorship_bias_note": (
            "Universe = h82v2_universe_2018_jan.csv (PIT proxy ~2018). "
            "Stocks delisted after 2018 absent from yfinance — bias directionally inflates Sharpe. "
            "Same treatment as H87 / H82v2 (documented per Hard Gate 9 option b)."
        ),
        "look_ahead_bias_flag":       False,
        "look_ahead_note": (
            "CLEAN — box ceiling/floor from prior N days (.shift(1)). "
            "Vol avg from prior 20 days (.shift(1)). "
            "Entry signal at T-close, fill at T+1-open. No same-bar fills."
        ),
    }
    json_path = OUT_DIR / f"{base}.json"
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"[SAVE] Metrics JSON: {json_path}")

    # Verdict TXT
    failed_gates = [(g, v, t) for g, v, t, p in checks if not p]
    wf_lines = []
    for w in wf_results:
        wf_lines.append(
            f"  WF{w['window']} IS {w.get('is_start','')}–{w.get('is_end','')}: "
            f"Sharpe={w.get('is_sharpe',0):.4f} trades={w.get('is_trades',0)} | "
            f"OOS {w.get('oos_start','')}–{w.get('oos_end','')}: "
            f"Sharpe={w.get('oos_sharpe',0):.4f} trades={w.get('oos_trades',0)} | "
            f"{'PASS' if w.get('wf_pass') else 'FAIL'}"
        )

    verdict_lines = [
        f"H87v2 Darvas Box Breakout — Regime-Adjusted Gate 1 Verdict",
        f"{'='*70}",
        f"Date:         {TODAY}",
        f"Strategy:     {STRATEGY_NAME}",
        f"Issue:        QUA-423",
        f"Parent:       QUA-422",
        f"IS composite: {IS_START} to {IS_END}",
        f"Walk-forward: 4 × (6mo IS / 3mo OOS)",
        f"Overall:      {verdict_label} ({n_passed}/{len(checks)} checks passed)",
        f"{'='*70}",
        f"",
        f"=== H87v2 Changes from H87 ===",
        f"IS period:    2022-01-01–2024-12-31 → 2023-01-01–2025-12-31 (remove 2022 bear)",
        f"Walk-forward: 6×(3mo IS/1mo OOS) → 4×(6mo IS/3mo OOS)",
        f"box_n sweep:  [15,20,25] → [20,25,30] (box_n=15 produced neg IS Sharpe in H87)",
        f"",
        f"=== IS Performance ({IS_START} to {IS_END}) ===",
        f"Sharpe:           {is_m['sharpe']:.4f}   [{'PASS' if gate_is_sharpe else 'FAIL'} > 1.0]",
        f"Max Drawdown:     {is_m['mdd']:.2%}  [{'PASS' if gate_is_mdd else 'FAIL'} < 20%]",
        f"Total Return:     {is_m['total_return']:.2%}",
        f"Win Rate:         {is_m['win_rate']:.2%}     [{'PASS' if gate_win_rate else 'FAIL'} > 50%]",
        f"Profit Factor:    {pf_str}    [{'PASS' if gate_pf else 'FAIL'} > 1.0]",
        f"Trade Count:      {is_m['trade_count']}          [{'PASS' if gate_trades else 'FAIL'} >= 100]",
        f"",
        f"=== Walk-Forward OOS Performance ===",
        f"Composite OOS Sharpe (trade-weighted): {composite_oos_sharpe:.4f}  [{'PASS' if gate_oos_sharpe else 'FAIL'} > 0.7]",
    ] + wf_lines + [
        f"  WF OOS Sharpe>0: {wf_passed}/{len(WF_WINDOWS)}  [{'PASS' if gate_wf else 'FAIL'}: >= 3/4]",
        f"  WF std={wf_var['wf_sharpe_std']:.4f} | min={wf_var['wf_sharpe_min']:.4f}",
        f"",
        f"=== Statistical Rigor ===",
        f"MC p5 Sharpe:       {mc['mc_p5_sharpe']:.4f}  {'⚠ weak' if mc['mc_p5_sharpe'] < 0.5 else '✓'}",
        f"MC Median Sharpe:   {mc['mc_median_sharpe']:.4f}",
        f"Sharpe 95% CI:      [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]",
        f"MDD 95% CI:         [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]",
        f"Permutation p:      {perm['permutation_pvalue']:.4f}  [{'PASS' if perm['permutation_test_pass'] else 'FAIL'}: < 0.05]",
        f"DSR:                {dsr_val:.4f}  [{'PASS' if gate_dsr else 'FAIL'}: > 0]",
        f"",
        f"=== Parameter Sweep (27 combos — 3×3×3) ===",
    ]
    if valid_sh:
        verdict_lines += [
            f"  box_n [20,25,30] × box_width_max [0.08,0.10,0.12] × vol_ratio_min [1.20,1.30,1.40]",
            f"  Sharpe range: {min(valid_sh):.4f} – {max(valid_sh):.4f}",
            f"  Sensitivity: {sens_var_pct:.1%}  [{'PASS' if sens_pass else 'FAIL'}: < 100%]",
            f"  (H87 had 290% sensitivity from box_n=15; H87v2 removes that combo)",
        ]
    verdict_lines += [
        f"",
        f"=== Gate 1 Checks ===",
    ] + [
        f"  [{'PASS' if p else 'FAIL'}] {g:<35} {v}  (threshold: {t})"
        for g, v, t, p in checks
    ]

    if verdict_label == "PASS":
        verdict_lines += [
            f"",
            f"=== Recommendation ===",
            f"PASS — advance to paper trading. Notify CEO for approval.",
        ]
    else:
        verdict_lines += [
            f"",
            f"=== Root Cause Analysis ===",
            f"Primary failures ({len(failed_gates)} of {len(checks)} gates):",
        ] + [f"  - {g}: got {v}, need {t}" for g, v, t in failed_gates] + [
            f"",
            f"=== Recommendation ===",
            f"REJECT — do not advance to paper trading.",
            f"NOTE: H87v2 is iteration 2/2. If FAIL, RETIRE Darvas Box family. Do not run H87v3.",
        ]

    verdict_lines += [
        f"",
        f"=== Data Quality ===",
        f"Universe:     h82v2_universe_2018_jan.csv (S&P 500 + S&P 400 PIT proxy ~2018)",
        f"Tickers:      {dq['total_tickers']} loaded | {dq['flagged_count']} flagged (>5 missing days)",
        f"Survivorship: PIT proxy - survivorship bias direction: inflates Sharpe",
        f"Price adj:    yfinance auto_adjust=True",
        f"Look-ahead:   CLEAN (box ceiling from prior N days shifted; entry T+1 open)",
        f"",
        f"=== Files ===",
        f"Report:  backtests/{base}_report.html",
        f"Metrics: backtests/{base}.json",
        f"Verdict: backtests/{base}_verdict.txt",
        f"Trades:  backtests/{base}_trades.csv",
        f"Sweep:   backtests/{base}_sweep.csv",
    ]

    verdict_text = "\n".join(verdict_lines)
    verdict_path = OUT_DIR / f"{base}_verdict.txt"
    verdict_path.write_text(verdict_text)
    print(f"[SAVE] Verdict: {verdict_path}")

    print(f"\n{'='*70}")
    print(f"H87v2 GATE 1 FINAL: {verdict_label} ({n_passed}/{len(checks)} checks)")
    print(f"  IS  Sharpe={is_m['sharpe']:.4f} | Composite OOS Sharpe={composite_oos_sharpe:.4f}")
    print(f"  IS  MDD={is_m['mdd']:.2%} | IS trades={is_m['trade_count']}")
    print(f"  WF={wf_passed}/{len(WF_WINDOWS)} | DSR={dsr_val:.4f} | Perm p={perm['permutation_pvalue']:.4f}")
    print(f"{'='*70}")
    if verdict_label == "FAIL":
        print("NOTE: H87v2 is iteration 2/2. Retire Darvas Box family if FAIL.")

    return metrics


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result.get("gate1_pass") else 1)
