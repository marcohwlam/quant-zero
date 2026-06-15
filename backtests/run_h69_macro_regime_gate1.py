"""
Gate 1 Backtest Runner — H69 Macro-Regime Sector Rotation
Engineering Director (QUA-278)

IS  window: 2004-01-01 to 2018-12-31 (15 years)
OOS window: 2019-01-01 to 2024-12-31 (6 years)
Track A — daily/weekly swing; Track A Gate 1 thresholds (CEO-locked 2026-06-13)

Parameter sweep grid (36 combinations):
  lookback_days:      [10, 20, 60]
  dma_gate:           [True, False]
  regime_c_cash_pct:  [0.0, 0.50, 1.0]
  rebal_day:          ["first", "last"]

Walk-forward (4 expanding windows, OOS within IS period):
  WF1: IS 2004-2009  OOS 2010-2012
  WF2: IS 2004-2011  OOS 2012-2014
  WF3: IS 2004-2013  OOS 2014-2016
  WF4: IS 2004-2015  OOS 2016-2018

Gate 1 pass thresholds (Track A CEO-locked):
  IS Net Sharpe      > 1.0
  OOS Net Sharpe     > 0.7
  IS MaxDD           > -0.20  (MDD < 20%)
  Gate 7 MDD ceiling > -0.30  (hard reject)
  IS CAGR            >= 10%
  IS Trade Count     >= 120
  WF Consistency     >= 3/4 windows
  Permutation p      < 0.05
  CPR                < 0.25
  Net PpT            > 15 bps
  Composite Score    >= 0.60

Outputs:
  backtests/h69_macro_regime_sector_rotation_2026-06-15.json
  backtests/h69_macro_regime_sector_rotation_2026-06-15_report.html
  backtests/h69_macro_regime_sector_rotation_2026-06-15_verdict.txt
  backtests/h69_macro_regime_sector_rotation_2026-06-15_trades.csv
  backtests/h69_macro_regime_sector_rotation_2026-06-15_sweep.csv
"""

import itertools
import json
import logging
import sys
import traceback
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from strategies.h69_macro_regime_sector_rotation import (
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
    REGIME_SECTORS,
    download_data,
    run_backtest,
)

# ── Config ────────────────────────────────────────────────────────────────────
IS_START  = "2004-01-01"
IS_END    = "2018-12-31"
OOS_START = "2019-01-01"
OOS_END   = "2024-12-31"

REPORT_DATE   = "2026-06-15"
STRATEGY_NAME = "h69_macro_regime_sector_rotation"
OUTPUT_DIR    = REPO_ROOT / "backtests"

# Track A Gate 1 thresholds (CEO-locked 2026-06-13, criteria.md v2.7)
GATE_IS_SHARPE  = 1.0
GATE_OOS_SHARPE = 0.7
GATE_IS_MDD     = -0.20
GATE_GATE7_MDD  = -0.30
GATE_IS_CAGR    = 0.10
GATE_MIN_TRADES = 120
GATE_PERM_PVAL  = 0.05
GATE_CPR        = 0.25
GATE_NET_PPT    = 15.0
GATE_CS         = 0.60

SWEEP_GRID = {
    "lookback_days":      [10, 20, 60],
    "dma_gate":           [True, False],
    "regime_c_cash_pct":  [0.0, 0.50, 1.0],
    "rebal_day":          ["first", "last"],
}

WF_WINDOWS = [
    ("2004-01-01", "2009-12-31", "2010-01-01", "2012-12-31"),
    ("2004-01-01", "2011-12-31", "2012-01-01", "2014-12-31"),
    ("2004-01-01", "2013-12-31", "2014-01-01", "2016-12-31"),
    ("2004-01-01", "2015-12-31", "2016-01-01", "2018-12-31"),
]

SUB_PERIODS = {
    "dot_com_recovery": ("2004-01-01", "2006-12-31"),
    "gfc_only":         ("2007-01-01", "2009-12-31"),
    "post_gfc_bull":    ("2010-01-01", "2014-12-31"),
    "rate_hike_cycle":  ("2015-01-01", "2018-12-31"),
    "rate_shock_2022":  ("2022-01-01", "2022-12-31"),
    "oos_full":         ("2019-01-01", "2024-12-31"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sf(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except Exception:
        return None


def backtest_window(start, end, params, label=""):
    try:
        result = run_backtest(start=start, end=end, params=params)
        if label:
            sh  = result.get("sharpe", float("nan")) or 0
            cag = result.get("cagr", 0.0) or 0
            mdd = result.get("max_drawdown", 0.0) or 0
            tc  = result.get("trade_count", 0)
            logger.info("  %s: Sharpe=%.3f CAGR=%.1f%% MDD=%.1f%% trades=%d",
                        label, sh, cag * 100, mdd * 100, tc)
        return result
    except Exception as e:
        logger.error("  %s FAILED: %s", label or f"{start}→{end}", e)
        traceback.print_exc()
        return {"sharpe": np.nan, "cagr": 0.0, "max_drawdown": 0.0,
                "trade_count": 0, "total_return": 0.0, "error": str(e)}


# ── Parameter Sweep ───────────────────────────────────────────────────────────

def run_parameter_sweep() -> pd.DataFrame:
    keys   = list(SWEEP_GRID.keys())
    combos = list(itertools.product(*[SWEEP_GRID[k] for k in keys]))
    logger.info("=== PARAMETER SWEEP: %d combinations ===", len(combos))

    records = []
    for idx, combo in enumerate(combos):
        p = PARAMETERS.copy()
        for k, v in zip(keys, combo):
            p[k] = v
        try:
            r = run_backtest(IS_START, IS_END, p)
            rec = {k: v for k, v in zip(keys, combo)}
            rec["is_sharpe"]        = _sf(r.get("sharpe"))
            rec["is_cagr"]          = _sf(r.get("cagr"))
            rec["is_mdd"]           = _sf(r.get("max_drawdown"))
            rec["is_trades"]        = int(r.get("trade_count", 0))
            rec["is_win_rate"]      = _sf(r.get("win_rate"))
            rec["is_pf"]            = _sf(r.get("profit_factor"))
            rec["is_cpr"]           = _sf(r.get("cpr"))
            rec["is_ppt_bps"]       = _sf(r.get("net_ppt_bps"))
            rec["is_n_transitions"] = int(r.get("n_transitions", 0))
        except Exception as e:
            rec = {k: v for k, v in zip(keys, combo)}
            rec.update({"is_sharpe": None, "is_cagr": 0.0, "is_mdd": 0.0,
                        "is_trades": 0, "is_win_rate": 0.0, "is_pf": 0.0,
                        "is_cpr": 1.0, "is_ppt_bps": 0.0, "is_n_transitions": 0})
            logger.warning("  Sweep combo %d failed: %s", idx, e)
        records.append(rec)

        if (idx + 1) % 9 == 0:
            valid = [r for r in records if r.get("is_sharpe") is not None]
            if valid:
                best = max(valid, key=lambda r: r["is_sharpe"])
                logger.info("  Progress %d/%d — best IS Sharpe: %.3f",
                            idx + 1, len(combos), best["is_sharpe"])

    df    = pd.DataFrame(records)
    valid = df["is_sharpe"].notna().sum()
    logger.info("Sweep complete. Valid: %d/%d", valid, len(combos))
    return df


# ── Walk-Forward ──────────────────────────────────────────────────────────────

def run_walk_forward(params: dict) -> dict:
    logger.info("=== WALK-FORWARD (4 expanding windows) ===")
    wf_results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(WF_WINDOWS):
        is_r  = backtest_window(is_s, is_e, params, f"WF[{i+1}] IS {is_s}→{is_e}")
        oos_r = backtest_window(oos_s, oos_e, params, f"WF[{i+1}] OOS {oos_s}→{oos_e}")
        is_sh  = _sf(is_r.get("sharpe"))
        oos_sh = _sf(oos_r.get("sharpe"))
        wf_results.append({
            "window": i + 1,
            "is_start": is_s, "is_end": is_e,
            "oos_start": oos_s, "oos_end": oos_e,
            "is_sharpe":  is_sh,
            "oos_sharpe": oos_sh,
            "oos_pass":   bool(oos_sh is not None and oos_sh > GATE_OOS_SHARPE),
        })

    oos_sharpes   = [w["oos_sharpe"] for w in wf_results if w["oos_sharpe"] is not None]
    wf_passed     = sum(1 for w in wf_results if w["oos_pass"])
    wf_sharpe_std = float(np.std(oos_sharpes)) if len(oos_sharpes) > 1 else 0.0
    wf_sharpe_min = float(np.min(oos_sharpes)) if oos_sharpes else None

    logger.info("  WF: %d/4 OOS windows passed (Sharpe > %.1f)", wf_passed, GATE_OOS_SHARPE)
    logger.info("  WF OOS Sharpes: %s",
                [f"{s:.3f}" if s is not None else "N/A" for s in oos_sharpes])

    return {
        "windows":        wf_results,
        "windows_passed": wf_passed,
        "wf_sharpe_std":  wf_sharpe_std,
        "wf_sharpe_min":  wf_sharpe_min,
    }


# ── Sub-Period Diagnostics ────────────────────────────────────────────────────

def run_sub_periods(params: dict) -> dict:
    logger.info("=== SUB-PERIOD DIAGNOSTICS ===")
    results = {}
    for name, (s, e) in SUB_PERIODS.items():
        r = backtest_window(s, e, params, f"  sub/{name}")
        results[name] = {
            "start": s, "end": e,
            "sharpe":       _sf(r.get("sharpe")),
            "cagr":         _sf(r.get("cagr")) or 0.0,
            "max_drawdown": _sf(r.get("max_drawdown")) or 0.0,
            "trade_count":  int(r.get("trade_count", 0)),
            "regime_counts": r.get("regime_counts", {}),
        }
    return results


# ── Statistical Rigor ─────────────────────────────────────────────────────────

def monte_carlo_sharpe(rt_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    if len(rt_pnls) < 5:
        return {"mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan}
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(rt_pnls, size=len(rt_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(12)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe":    float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    if T < 10:
        return {"sharpe_ci_low": np.nan, "sharpe_ci_high": np.nan,
                "mdd_ci_low": np.nan, "mdd_ci_high": np.nan}
    block_len = max(1, int(np.sqrt(T)))
    n_blocks  = T // block_len
    sharpes, mdds = [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum    = np.cumprod(1 + sample)
        rmx    = np.maximum.accumulate(cum)
        mdd    = float(np.min((cum - rmx) / (rmx + 1e-8)))
        sh     = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        sharpes.append(sh)
        mdds.append(mdd)
    return {
        "sharpe_ci_low":  float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":     float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":    float(np.percentile(mdds, 97.5)),
    }


def permutation_test(regime_monthly, monthly_sector_returns, observed_sharpe,
                     n_perms=1000):
    if len(regime_monthly) < 6 or monthly_sector_returns.empty:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False,
                "permutation_n": 0, "permutation_note": "insufficient data"}

    regimes = [r["regime"] for r in regime_monthly]
    blocks  = []
    cur, cnt = regimes[0], 1
    for r in regimes[1:]:
        if r == cur:
            cnt += 1
        else:
            blocks.append((cur, cnt))
            cur, cnt = r, 1
    blocks.append((cur, cnt))
    n_blocks = len(blocks)

    regime_to_sectors = {
        "A": ["XLK", "XLY", "XLF"],
        "B": ["XLU", "XLP", "XLV"],
        "C": ["XLE", "XLB"],
        "D": ["XLI", "XLRE", "XLF"],
    }

    def regime_ret(regime, idx):
        secs = [s for s in regime_to_sectors.get(regime, [])
                if s in monthly_sector_returns.columns]
        if not secs or idx >= len(monthly_sector_returns):
            return 0.0
        row  = monthly_sector_returns.iloc[idx]
        rets = [row.get(s, 0.0) for s in secs
                if not pd.isna(row.get(s, float("nan")))]
        return float(np.mean(rets)) if rets else 0.0

    def sharpe_seq(seq):
        arr = np.array([regime_ret(r, i) for i, r in enumerate(seq)])
        return float(arr.mean() / (arr.std() + 1e-10) * np.sqrt(12)) if arr.std() > 1e-10 else 0.0

    perm_sharpes = []
    for _ in range(n_perms):
        perm_blk = list(np.random.permutation(n_blocks))
        perm_seq = []
        for bi in perm_blk:
            lbl, length = blocks[bi]
            perm_seq.extend([lbl] * length)
        perm_seq = perm_seq[:len(regimes)]
        while len(perm_seq) < len(regimes):
            perm_seq.append(blocks[-1][0])
        perm_sharpes.append(sharpe_seq(perm_seq))

    p_value = float(np.mean(np.array(perm_sharpes) >= observed_sharpe))
    logger.info("  Permutation test: p=%.4f (n=%d, n_blocks=%d) — %s",
                p_value, n_perms, n_blocks,
                "PASS" if p_value <= GATE_PERM_PVAL else "FAIL")

    return {
        "permutation_pvalue":    p_value,
        "permutation_test_pass": bool(p_value <= GATE_PERM_PVAL),
        "permutation_n":         n_perms,
        "permutation_n_blocks":  n_blocks,
        "permutation_note": (
            "Block-shuffle of monthly regime sequence. "
            "p < 0.05 = regime signal has genuine sector-return predictive power."
        ),
    }


def compute_dsr(returns_series, n_trials):
    from scipy.stats import norm
    r  = returns_series.dropna().values
    n  = len(r)
    if n < 4 or n_trials <= 0:
        return 0.0
    sr   = r.mean() / (r.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(pd.Series(r).skew())
    kurt = float(pd.Series(r).kurt())
    sr_star = np.sqrt(2) * sr * np.sqrt(np.log(n_trials) / max(np.pi * np.log(n), 1e-8))
    sr_var  = (1 + 0.5 * sr**2 - skew * sr + (kurt / 4) * sr**2) / n
    return round(float(norm.cdf((sr - sr_star) / (np.sqrt(sr_var) + 1e-10))), 6)


def compute_composite_score(oos_sharpe, is_mdd, net_ppt_bps, is_trades):
    ns  = float(np.clip((oos_sharpe - (-0.5)) / (2.0 - (-0.5)), 0.0, 1.0))
    st  = float(np.clip(1.0 - abs(is_mdd) / 0.20, 0.0, 1.0))
    ppt = float(np.clip(net_ppt_bps / 100.0, 0.0, 1.0))
    ta  = float(min(1.0, is_trades / 30))
    return round(0.40 * ns + 0.30 * st + 0.20 * ppt + 0.10 * ta, 4)


def evaluate_gate1(is_m, oos_m, wf, rigor, sweep_df):
    is_sharpe  = _sf(is_m.get("sharpe"))  or 0.0
    oos_sharpe = _sf(oos_m.get("sharpe")) or 0.0
    is_mdd     = _sf(is_m.get("max_drawdown")) or 0.0
    is_cagr    = _sf(is_m.get("cagr")) or 0.0
    is_trades  = int(is_m.get("trade_count", 0))
    cpr        = _sf(is_m.get("cpr"))       or 1.0
    net_ppt    = _sf(is_m.get("net_ppt_bps")) or 0.0
    perm_pass  = bool(rigor.get("permutation_test_pass", False))
    wf_passed  = int(wf.get("windows_passed", 0))

    cs      = compute_composite_score(oos_sharpe, is_mdd, net_ppt, is_trades)
    oos_deg = (is_sharpe - oos_sharpe) / is_sharpe if is_sharpe > 0 else 1.0

    criteria = {
        "IS_Sharpe":       {"value": round(is_sharpe, 4),    "threshold": f"> {GATE_IS_SHARPE}",      "pass": bool(is_sharpe > GATE_IS_SHARPE)},
        "OOS_Sharpe":      {"value": round(oos_sharpe, 4),   "threshold": f"> {GATE_OOS_SHARPE}",     "pass": bool(oos_sharpe > GATE_OOS_SHARPE)},
        "IS_MaxDD":        {"value": round(is_mdd * 100, 2), "threshold": "> -20%",                   "pass": bool(is_mdd > GATE_IS_MDD),        "note": "CS threshold; Gate7 ceiling = -30%"},
        "Gate7_MDD":       {"value": round(is_mdd * 100, 2), "threshold": "> -30% (hard)",            "pass": bool(is_mdd > GATE_GATE7_MDD)},
        "IS_CAGR":         {"value": round(is_cagr * 100, 2),"threshold": f">= {GATE_IS_CAGR*100:.0f}%", "pass": bool(is_cagr >= GATE_IS_CAGR)},
        "IS_TradeCount":   {"value": is_trades,               "threshold": f">= {GATE_MIN_TRADES}",   "pass": bool(is_trades >= GATE_MIN_TRADES)},
        "WF_Consistency":  {"value": f"{wf_passed}/4",        "threshold": ">= 3/4",                  "pass": bool(wf_passed >= 3)},
        "Permutation_p":   {"value": round(float(rigor.get("permutation_pvalue", 1.0)), 4),
                            "threshold": f"< {GATE_PERM_PVAL}", "pass": perm_pass,
                            "note": "Block-shuffle monthly regime sequence"},
        "CPR":             {"value": round(cpr, 4),           "threshold": f"< {GATE_CPR}",           "pass": bool(cpr < GATE_CPR)},
        "Net_PpT_bps":     {"value": round(net_ppt, 2),       "threshold": f"> {GATE_NET_PPT} bps",   "pass": bool(net_ppt > GATE_NET_PPT)},
        "Composite_Score": {"value": round(cs, 4),            "threshold": f">= {GATE_CS}",            "pass": bool(cs >= GATE_CS)},
    }

    all_pass = all(c["pass"] for c in criteria.values())
    return {"criteria": criteria, "verdict": "PASS" if all_pass else "FAIL",
            "composite_score": cs, "oos_degradation": round(float(oos_deg), 4)}


def compute_monthly_sector_returns(close):
    cols = [c for c in close.columns if c in
            ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLRE", "XLC", "XLU", "XLB"]]
    if not cols:
        return pd.DataFrame()
    return close[cols].resample("MS").first().pct_change().iloc[1:]


# ── Report Generators ─────────────────────────────────────────────────────────

def generate_verdict_txt(is_m, oos_m, verdict, sweep_df, wf, rigor, sub):
    cs = verdict.get("composite_score", 0.0)
    lines = [
        "=" * 72,
        "GATE 1 VERDICT — H69 Macro-Regime Sector Rotation (QUA-278)",
        f"Report Date: {REPORT_DATE}  |  Track A (Monthly Rebalancing)",
        "=" * 72,
        "",
        f"OVERALL VERDICT: {verdict['verdict']}",
        f"Composite Score: {cs:.4f}  (threshold >= {GATE_CS})",
        "",
        "── GATE 1 CRITERIA (Track A, CEO-locked 2026-06-13) ─────────────────────",
    ]
    for name, c in verdict["criteria"].items():
        tag  = "PASS" if c["pass"] else "FAIL"
        note = f"  [{c.get('note','')}]" if c.get("note") else ""
        lines.append(f"  [{tag}] {name}: {c['value']} (threshold: {c['threshold']}){note}")

    def pct(x):
        return f"{(x or 0)*100:.2f}%"

    lines += [
        "",
        f"── IS METRICS ({IS_START} to {IS_END}) ─────────────────────────────────",
        f"  Net Sharpe:         {is_m.get('sharpe', 0) or 0:.4f}",
        f"  CAGR:               {pct(is_m.get('cagr'))}",
        f"  Max Drawdown:       {pct(is_m.get('max_drawdown'))}",
        f"  Total Return:       {pct(is_m.get('total_return'))}",
        f"  Win Rate:           {pct(is_m.get('win_rate'))}",
        f"  Profit Factor:      {is_m.get('profit_factor', 0) or 0:.3f}",
        f"  Round-trip Trades:  {is_m.get('trade_count', 0)}",
        f"  Net PpT (bps):      {is_m.get('net_ppt_bps', 0) or 0:.2f}",
        f"  CPR:                {is_m.get('cpr', 1.0) or 1.0:.4f}",
        f"  Regime Transitions: {is_m.get('n_transitions', 0)}",
        f"  Transitions/yr:     {is_m.get('transitions_per_year', 0) or 0:.1f}",
        f"  Avg Hold Days:      {is_m.get('avg_hold_days', 0) or 0:.1f}",
        f"  Regime Counts:      {is_m.get('regime_counts', {})}",
        "",
        f"── OOS METRICS ({OOS_START} to {OOS_END}) ────────────────────────────────",
        f"  Net Sharpe:         {oos_m.get('sharpe', 0) or 0:.4f}",
        f"  CAGR:               {pct(oos_m.get('cagr'))}",
        f"  Max Drawdown:       {pct(oos_m.get('max_drawdown'))}",
        f"  Total Return:       {pct(oos_m.get('total_return'))}",
        f"  Win Rate:           {pct(oos_m.get('win_rate'))}",
        f"  Round-trip Trades:  {oos_m.get('trade_count', 0)}",
        f"  Regime Counts:      {oos_m.get('regime_counts', {})}",
        f"  OOS Degradation:    {verdict['oos_degradation']*100:.1f}% vs IS Sharpe",
        "",
        "── STATISTICAL RIGOR ────────────────────────────────────────────────────",
        f"  MC p5 Sharpe:     {rigor.get('mc_p5_sharpe', float('nan')):.4f}  "
        f"{'[OK]' if (rigor.get('mc_p5_sharpe') or 0) >= 0.5 else '[WEAK]'}",
        f"  MC median Sharpe: {rigor.get('mc_median_sharpe', float('nan')):.4f}",
        f"  Sharpe 95% CI:    [{rigor.get('sharpe_ci_low', float('nan')):.4f}, "
        f"{rigor.get('sharpe_ci_high', float('nan')):.4f}]",
        f"  MDD 95% CI:       [{(rigor.get('mdd_ci_low') or 0)*100:.2f}%, "
        f"{(rigor.get('mdd_ci_high') or 0)*100:.2f}%]",
        f"  Permutation p:    {rigor.get('permutation_pvalue', 1.0):.4f}  "
        f"({'PASS' if rigor.get('permutation_test_pass') else 'FAIL'})",
        f"  Perm n_blocks:    {rigor.get('permutation_n_blocks', 0)}",
        f"  DSR:              {rigor.get('dsr', 0.0):.4f}",
    ]

    if wf:
        lines += ["", "── WALK-FORWARD (4 expanding windows) ───────────────────────────────"]
        for w in wf["windows"]:
            tag    = "PASS" if w["oos_pass"] else "FAIL"
            is_sh  = f"{w['is_sharpe']:.3f}"  if w["is_sharpe"]  is not None else "N/A"
            oos_sh = f"{w['oos_sharpe']:.3f}" if w["oos_sharpe"] is not None else "N/A"
            lines.append(
                f"  Window {w['window']}: IS {w['is_start']}→{w['is_end']} "
                f"OOS {w['oos_start']}→{w['oos_end']} | IS={is_sh} OOS={oos_sh} [{tag}]"
            )
        lines += [
            f"  Windows Passed:  {wf['windows_passed']}/4",
            f"  WF Sharpe Std:   {wf['wf_sharpe_std']:.4f}",
        ]

    if sub:
        lines += ["", "── SUB-PERIOD DIAGNOSTICS ───────────────────────────────────────────"]
        for name, r in sub.items():
            sh = f"{r['sharpe']:.3f}" if r.get("sharpe") is not None else "N/A"
            lines.append(
                f"  {name}: Sharpe={sh} CAGR={(r.get('cagr') or 0)*100:.1f}% "
                f"MDD={(r.get('max_drawdown') or 0)*100:.1f}% "
                f"Trades={r.get('trade_count',0)} Regimes={r.get('regime_counts',{})}"
            )

    if sweep_df is not None and not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        lines += ["", "── PARAMETER SWEEP (36 combinations, IS only) ────────────────────────"]
        if not valid.empty:
            lines += [
                f"  Best IS Sharpe:   {valid['is_sharpe'].max():.4f}",
                f"  Median IS Sharpe: {valid['is_sharpe'].median():.4f}",
                f"  Worst IS Sharpe:  {valid['is_sharpe'].min():.4f}",
                f"  MDD<20% combos:   {(valid['is_mdd'] > -0.20).sum()}/{len(valid)}",
                f"  Sharpe>1.0 combos:{(valid['is_sharpe'] > 1.0).sum()}/{len(valid)}",
            ]

    lines += [
        "",
        "── TRACK A OVERNIGHT/WEEKEND GUARDS (Hard Gate 8) ──────────────────────",
        "  Overnight gaps: N/A — monthly rebalancing; gaps averaged into monthly return.",
        "  Weekend risk:   Sector ETF positions held over weekends (max 33-50% per ETF).",
        "  Earnings policy: N/A — ETF strategy, no single-stock earnings exposure.",
        "  Gap MDD attr:   N/A at monthly bar resolution.",
        "",
        "── SURVIVORSHIP BIAS (Hard Gate 9) ──────────────────────────────────────",
        "  Universe: SPDR sector ETFs + SPY/TLT/SHY — all active, no delisted tickers.",
        "  XLRE pre-2015: weight redistributed to XLI+XLF (documented).",
        "  No survivorship bias concern for this ETF-only universe.",
        "",
        "── COST MODEL ───────────────────────────────────────────────────────────",
        "  Fixed:    $0.005/share | Slip: 0.05% notional | Impact: k=0.1×σ×√(Q/ADV)",
        "  SPY/TLT signal only — not traded; no execution costs on signal assets.",
        "",
        "=" * 72,
    ]
    return "\n".join(lines)


def generate_html_report(is_m, oos_m, verdict, sweep_df, wf, rigor, sub):
    v  = verdict["verdict"]
    vc = "#28a745" if v == "PASS" else "#dc3545"
    pp = rigor.get("permutation_test_pass", False)
    pc = "#28a745" if pp else "#dc3545"
    cs = verdict.get("composite_score", 0.0)
    cc = "#28a745" if cs >= GATE_CS else "#dc3545"

    def fp(x):
        return f"{(x or 0)*100:.2f}%" if x is not None else "N/A"
    def f4(x):
        if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
            return "N/A"
        return f"{x:.4f}"

    crit_rows = ""
    for name, c in verdict["criteria"].items():
        tag   = "PASS" if c["pass"] else "FAIL"
        color = "#28a745" if c["pass"] else "#dc3545"
        note  = c.get("note", "")
        crit_rows += (
            f"<tr><td><strong>{name}</strong></td>"
            f"<td>{c['value']}</td><td>{c['threshold']}</td>"
            f"<td style='color:{color};font-weight:bold'>{tag}</td>"
            f"<td style='font-size:0.85em'>{note}</td></tr>\n"
        )

    wf_rows = ""
    for w in (wf.get("windows") or []):
        color = "#28a745" if w["oos_pass"] else "#dc3545"
        wf_rows += (
            f"<tr><td>{w['window']}</td>"
            f"<td>{w['is_start']}→{w['is_end']}</td>"
            f"<td>{w['oos_start']}→{w['oos_end']}</td>"
            f"<td>{f4(w['is_sharpe'])}</td><td>{f4(w['oos_sharpe'])}</td>"
            f"<td style='color:{color};font-weight:bold'>{'PASS' if w['oos_pass'] else 'FAIL'}</td></tr>\n"
        )

    sweep_tbl = ""
    if sweep_df is not None and not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        for _, row in valid.nlargest(10, "is_sharpe").iterrows():
            sweep_tbl += (
                f"<tr><td>{int(row['lookback_days'])}</td>"
                f"<td>{'ON' if row['dma_gate'] else 'OFF'}</td>"
                f"<td>{row['regime_c_cash_pct']:.0%}</td>"
                f"<td>{row['rebal_day']}</td>"
                f"<td>{f4(row.get('is_sharpe'))}</td>"
                f"<td>{fp(row.get('is_cagr'))}</td>"
                f"<td>{fp(row.get('is_mdd'))}</td>"
                f"<td>{int(row.get('is_trades',0))}</td></tr>\n"
            )

    sub_rows = ""
    for name, r in (sub or {}).items():
        sub_rows += (
            f"<tr><td>{name}</td><td>{r['start']}→{r['end']}</td>"
            f"<td>{f4(r.get('sharpe'))}</td>"
            f"<td>{fp(r.get('cagr'))}</td>"
            f"<td>{fp(r.get('max_drawdown'))}</td>"
            f"<td>{r.get('trade_count',0)}</td>"
            f"<td>{r.get('regime_counts',{})}</td></tr>\n"
        )

    is_rc  = is_m.get("regime_counts",  {})
    oos_rc = oos_m.get("regime_counts", {})

    return f"""<!DOCTYPE html><html>
<head><title>H69 Gate 1 — Macro-Regime Sector Rotation</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1150px;margin:40px auto;color:#333}}
h1{{color:#1a1a2e}}h2{{color:#16213e;border-bottom:2px solid #eee;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;margin:10px 0}}
th,td{{padding:8px 12px;border:1px solid #ddd;text-align:left;font-size:.9em}}
th{{background:#f4f4f4;font-weight:bold}}
.verdict{{font-size:2em;font-weight:bold;color:{vc};margin:20px 0}}
.cs{{font-size:1.3em;font-weight:bold;color:{cc}}}
.mg{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0}}
.mb{{background:#f9f9f9;border:1px solid #ddd;border-radius:6px;padding:12px}}
.mv{{font-size:1.2em;font-weight:bold;color:#1a1a2e}}
.pb{{color:{pc};font-weight:bold;font-size:1.1em}}
.ok{{color:#155724;background:#d4edda;padding:10px;border-radius:4px;margin:10px 0}}
.critical{{color:#721c24;background:#f8d7da;padding:10px;border-radius:4px;margin:10px 0}}
</style></head><body>
<h1>Gate 1 Report — H69 Macro-Regime Sector Rotation (QUA-278)</h1>
<p><strong>Report Date:</strong> {REPORT_DATE} | <strong>Track A</strong> | IS: {IS_START}→{IS_END} | OOS: {OOS_START}→{OOS_END}</p>
<p>SPY+TLT 20-day momentum → 4-regime SPDR sector ETF rotation. Monthly rebalancing.
Signal at last day of month → execution at first day of next month.
Regime C: 200-DMA SPY cash gate (50% → SHY when SPY &lt; 200-DMA).</p>

<div class="verdict">Gate 1 Verdict: {v}</div>
<p>Composite Score (Track A KPI v1.0): <span class="cs">{cs:.4f}</span> (threshold ≥ {GATE_CS})</p>

<div class="{'ok' if pp else 'critical'}">
<strong>PERMUTATION TEST:</strong> <span class="pb">p = {rigor.get('permutation_pvalue',1.0):.4f}</span>
({'PASS — regime signal has genuine predictive power ✓' if pp else 'FAIL — regime ordering not statistically significant'})
Block-shuffle of monthly regime sequence ({rigor.get('permutation_n',0)} shuffles, {rigor.get('permutation_n_blocks',0)} blocks).
</div>

<h2>Gate 1 Criteria</h2>
<table><thead><tr><th>Criterion</th><th>Value</th><th>Threshold</th><th>Status</th><th>Note</th></tr></thead>
<tbody>{crit_rows}</tbody></table>

<h2>IS Performance ({IS_START} to {IS_END})</h2>
<div class="mg">
<div class="mb"><div>Net Sharpe</div><div class="mv">{f4(is_m.get('sharpe'))}</div></div>
<div class="mb"><div>CAGR</div><div class="mv">{fp(is_m.get('cagr'))}</div></div>
<div class="mb"><div>Max Drawdown</div><div class="mv">{fp(is_m.get('max_drawdown'))}</div></div>
<div class="mb"><div>Total Return</div><div class="mv">{fp(is_m.get('total_return'))}</div></div>
<div class="mb"><div>Win Rate</div><div class="mv">{fp(is_m.get('win_rate'))}</div></div>
<div class="mb"><div>Profit Factor</div><div class="mv">{f4(is_m.get('profit_factor'))}</div></div>
<div class="mb"><div>Round-trip Trades</div><div class="mv">{is_m.get('trade_count',0)}</div></div>
<div class="mb"><div>Net PpT (bps)</div><div class="mv">{f4(is_m.get('net_ppt_bps'))}</div></div>
<div class="mb"><div>CPR</div><div class="mv">{f4(is_m.get('cpr'))}</div></div>
</div>

<h2>Regime Distribution</h2>
<table><thead><tr><th>Regime</th><th>Description</th><th>IS Months</th><th>OOS Months</th><th>Sectors</th></tr></thead><tbody>
<tr><td>A</td><td>Growth (EM+ BM-)</td><td>{is_rc.get('A',0)}</td><td>{oos_rc.get('A',0)}</td><td>XLK, XLY, XLF</td></tr>
<tr><td>B</td><td>Defensive (EM- BM+)</td><td>{is_rc.get('B',0)}</td><td>{oos_rc.get('B',0)}</td><td>XLU, XLP, XLV</td></tr>
<tr><td>C</td><td>Stagflation (EM- BM-)</td><td>{is_rc.get('C',0)}</td><td>{oos_rc.get('C',0)}</td><td>XLE, XLB (+200-DMA cash gate)</td></tr>
<tr><td>D</td><td>Recovery (EM+ BM+)</td><td>{is_rc.get('D',0)}</td><td>{oos_rc.get('D',0)}</td><td>XLI, XLRE, XLF</td></tr>
</tbody></table>

<h2>OOS Performance ({OOS_START} to {OOS_END})</h2>
<div class="mg">
<div class="mb"><div>Net Sharpe</div><div class="mv">{f4(oos_m.get('sharpe'))}</div></div>
<div class="mb"><div>CAGR</div><div class="mv">{fp(oos_m.get('cagr'))}</div></div>
<div class="mb"><div>Max Drawdown</div><div class="mv">{fp(oos_m.get('max_drawdown'))}</div></div>
<div class="mb"><div>Total Return</div><div class="mv">{fp(oos_m.get('total_return'))}</div></div>
<div class="mb"><div>Win Rate</div><div class="mv">{fp(oos_m.get('win_rate'))}</div></div>
<div class="mb"><div>Round-trip Trades</div><div class="mv">{oos_m.get('trade_count',0)}</div></div>
<div class="mb"><div>OOS Degradation</div><div class="mv">{verdict['oos_degradation']*100:.1f}%</div></div>
</div>

<h2>Statistical Rigor</h2>
<table><thead><tr><th>Metric</th><th>Value</th><th>Threshold</th><th>Status</th></tr></thead><tbody>
<tr><td>MC p5 Sharpe (1000)</td><td>{f4(rigor.get('mc_p5_sharpe'))}</td><td>≥ 0.5</td><td>{'PASS' if (rigor.get('mc_p5_sharpe') or 0)>=0.5 else 'WARN'}</td></tr>
<tr><td>Bootstrap Sharpe 95% CI</td><td>[{f4(rigor.get('sharpe_ci_low'))}, {f4(rigor.get('sharpe_ci_high'))}]</td><td>—</td><td>—</td></tr>
<tr><td>Bootstrap MDD 95% CI</td><td>[{fp(rigor.get('mdd_ci_low'))}, {fp(rigor.get('mdd_ci_high'))}]</td><td>—</td><td>—</td></tr>
<tr><td><strong>Permutation p (block-shuffle)</strong></td>
<td><strong>{f4(rigor.get('permutation_pvalue'))}</strong></td><td>≤ 0.05</td>
<td style='color:{pc};font-weight:bold'>{'PASS' if pp else 'FAIL'}</td></tr>
<tr><td>DSR (36 trials)</td><td>{f4(rigor.get('dsr'))}</td><td>&gt; 0</td>
<td>{'PASS' if (rigor.get('dsr') or 0)>0 else 'WARN'}</td></tr>
</tbody></table>

<h2>Walk-Forward (4 expanding windows)</h2>
<table><thead><tr><th>#</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>Status</th></tr></thead>
<tbody>{wf_rows}</tbody></table>
<p>Windows passed: <strong>{wf.get('windows_passed',0)}/4</strong> | WF Sharpe std: {wf.get('wf_sharpe_std',0):.4f}</p>

<h2>Sub-Period Diagnostics</h2>
<table><thead><tr><th>Period</th><th>Window</th><th>Sharpe</th><th>CAGR</th><th>MDD</th><th>Trades</th><th>Regime Counts</th></tr></thead>
<tbody>{sub_rows}</tbody></table>

<h2>Parameter Sweep Top 10 (36 combos, IS only)</h2>
<table><thead><tr><th>Lookback</th><th>200-DMA Gate</th><th>C Cash%</th><th>Rebal</th><th>IS Sharpe</th><th>IS CAGR</th><th>IS MDD</th><th>Trades</th></tr></thead>
<tbody>{sweep_tbl}</tbody></table>

<h2>Track A Guards & Data Quality</h2>
<ul>
<li>Overnight/weekend guards (Hard Gate 8): N/A at monthly bar resolution — documented per criteria.md §Swing/Daily-Specific Guards.</li>
<li>Earnings policy: N/A — ETF-only strategy.</li>
<li>Survivorship bias (Hard Gate 9): None — all SPDR ETFs active. XLRE pre-2015: weight redistributed to XLI+XLF.</li>
<li>Look-ahead: signal at last-day-of-month close; execution at next-month first-day close (proxy for open).</li>
<li>Cost model: $0.005/share + 0.05% slip + Almgren-Chriss k=0.1×σ×√(Q/ADV).</li>
</ul>
</body></html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 72)
    logger.info("H69 Macro-Regime Sector Rotation — Gate 1 Backtest (QUA-278)")
    logger.info("=" * 72)

    logger.info("\n=== IS BACKTEST (%s → %s) ===", IS_START, IS_END)
    is_result = backtest_window(IS_START, IS_END, PARAMETERS.copy(), "IS")

    logger.info("\n=== OOS BACKTEST (%s → %s) ===", OOS_START, OOS_END)
    oos_result = backtest_window(OOS_START, OOS_END, PARAMETERS.copy(), "OOS")

    logger.info("\n=== PARAMETER SWEEP ===")
    sweep_df = run_parameter_sweep()

    wf  = run_walk_forward(PARAMETERS.copy())
    sub = run_sub_periods(PARAMETERS.copy())

    # Statistical rigor
    logger.info("\n=== STATISTICAL RIGOR ===")
    rigor   = {}
    rt_df   = is_result.get("round_trips", pd.DataFrame())
    is_eq   = is_result.get("equity", pd.Series(dtype=float))
    rm_list = is_result.get("regime_monthly", [])

    if not rt_df.empty and len(rt_df) >= 5:
        logger.info("  MC bootstrap (1000 sims)...")
        rigor.update(monte_carlo_sharpe(rt_df["net_pnl"].values))

        if not is_eq.empty and len(is_eq) > 10:
            logger.info("  Block bootstrap CI (1000 boots)...")
            rigor.update(block_bootstrap_ci(is_eq.pct_change().fillna(0).values))

        logger.info("  Permutation test (1000 shuffles)...")
        try:
            close_is, _ = download_data(IS_START, IS_END)
            msr = compute_monthly_sector_returns(close_is)
            rigor.update(permutation_test(
                rm_list, msr,
                observed_sharpe=float(is_result.get("sharpe", 0) or 0),
                n_perms=1000,
            ))
        except Exception as e:
            logger.warning("  Permutation test error: %s", e)
            rigor.update({"permutation_pvalue": 1.0, "permutation_test_pass": False,
                          "permutation_n": 0, "permutation_note": f"error: {e}"})

        if not is_eq.empty and len(is_eq) > 5:
            logger.info("  DSR (36 trials)...")
            rigor["dsr"] = compute_dsr(is_eq.pct_change().dropna(), n_trials=36)
    else:
        logger.warning("  Insufficient IS round-trips (%d); skipping rigor.", len(rt_df))
        rigor = {
            "mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan,
            "sharpe_ci_low": np.nan, "sharpe_ci_high": np.nan,
            "mdd_ci_low": np.nan, "mdd_ci_high": np.nan,
            "permutation_pvalue": 1.0, "permutation_test_pass": False, "permutation_n": 0,
            "dsr": 0.0,
        }

    rigor["wf_sharpe_std"] = wf.get("wf_sharpe_std", 0.0)
    rigor["wf_sharpe_min"] = wf.get("wf_sharpe_min")

    verdict = evaluate_gate1(is_result, oos_result, wf, rigor, sweep_df)
    logger.info("\n=== GATE 1 VERDICT: %s  CS=%.4f ===",
                verdict["verdict"], verdict["composite_score"])
    for name, c in verdict["criteria"].items():
        logger.info("  [%s] %s: %s (threshold: %s)",
                    "PASS" if c["pass"] else "FAIL", name, c["value"], c["threshold"])

    # Outputs
    logger.info("\n=== GENERATING REPORTS ===")
    base = f"{STRATEGY_NAME}_{REPORT_DATE}"

    def _sm(m):
        return {k: _sf(v) for k, v in m.items()
                if isinstance(v, (int, float, str, dict, list, bool, type(None)))
                and k not in ("equity", "daily_df", "trades", "round_trips")}

    json_payload = {
        "strategy": "H69_Macro_Regime_Sector_Rotation",
        "version": "1.0", "gate": "Gate 1", "track": "A",
        "report_date": REPORT_DATE,
        "is_window": {"start": IS_START, "end": IS_END},
        "oos_window": {"start": OOS_START, "end": OOS_END},
        "default_params": PARAMETERS,
        "is_metrics": _sm(is_result),
        "oos_metrics": _sm(oos_result),
        "gate1_verdict": verdict,
        "statistical_rigor": {k: _sf(v) for k, v in rigor.items()},
        "walk_forward": {
            "windows": wf["windows"], "windows_passed": wf["windows_passed"],
            "wf_sharpe_std": wf["wf_sharpe_std"], "wf_sharpe_min": wf.get("wf_sharpe_min"),
        },
        "sub_period_diagnostics": sub,
        "parameter_sweep": {
            "total_combinations": len(sweep_df) if sweep_df is not None else 0,
            "best_is_sharpe":   _sf(sweep_df["is_sharpe"].max()) if sweep_df is not None and not sweep_df.empty else None,
            "median_is_sharpe": _sf(sweep_df["is_sharpe"].median()) if sweep_df is not None and not sweep_df.empty else None,
        },
        "paperclip_issue": "QUA-278",
        "hypothesis_ref": "research/hypotheses/69_macro_regime_sector_rotation.md",
        "cost_model": "ED canonical: $0.005/share + 0.05% slip + Almgren-Chriss k=0.1",
    }

    p = OUTPUT_DIR / f"{base}.json"
    with open(p, "w") as f:
        json.dump(json_payload, f, indent=2, default=str)
    logger.info("  JSON: %s", p)

    verdict_txt = generate_verdict_txt(is_result, oos_result, verdict, sweep_df, wf, rigor, sub)
    p = OUTPUT_DIR / f"{base}_verdict.txt"
    with open(p, "w") as f:
        f.write(verdict_txt)
    logger.info("  Verdict: %s", p)

    html = generate_html_report(is_result, oos_result, verdict, sweep_df, wf, rigor, sub)
    p = OUTPUT_DIR / f"{base}_report.html"
    with open(p, "w") as f:
        f.write(html)
    logger.info("  HTML: %s", p)

    trades_df = is_result.get("trades", pd.DataFrame())
    if not trades_df.empty:
        p = OUTPUT_DIR / f"{base}_trades.csv"
        trades_df.to_csv(p, index=False)
        logger.info("  Trades: %s", p)

    if sweep_df is not None and not sweep_df.empty:
        p = OUTPUT_DIR / f"{base}_sweep.csv"
        sweep_df.to_csv(p, index=False)
        logger.info("  Sweep: %s", p)

    logger.info("\n=== SUMMARY ===")
    logger.info("IS  Sharpe=%.4f CAGR=%.1f%% MDD=%.1f%% Trades=%d CPR=%.3f PpT=%.1fbps",
                is_result.get("sharpe", 0) or 0,
                (is_result.get("cagr", 0) or 0) * 100,
                (is_result.get("max_drawdown", 0) or 0) * 100,
                is_result.get("trade_count", 0),
                is_result.get("cpr", 1.0) or 1.0,
                is_result.get("net_ppt_bps", 0) or 0)
    logger.info("OOS Sharpe=%.4f CAGR=%.1f%% MDD=%.1f%%",
                oos_result.get("sharpe", 0) or 0,
                (oos_result.get("cagr", 0) or 0) * 100,
                (oos_result.get("max_drawdown", 0) or 0) * 100)
    logger.info("Permutation p=%.4f  WF: %d/4  CS=%.4f  Verdict: %s",
                rigor.get("permutation_pvalue", 1.0) or 1.0,
                wf["windows_passed"],
                verdict["composite_score"],
                verdict["verdict"])
    logger.info("IS  Regime: %s", is_result.get("regime_counts", {}))
    logger.info("OOS Regime: %s", oos_result.get("regime_counts", {}))

    print("\n" + verdict_txt)
    return json_payload


if __name__ == "__main__":
    result = main()
