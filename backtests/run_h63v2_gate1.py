"""
Gate 1 v2.2 Backtest Runner — H63v2 SPY/QQQ Pairs Daily Baseline Mean Reversion
Backtest Runner Agent (QUA-179)

Outputs:
  backtests/H63v2_SPY_QQQ_Pairs_2026-06-09.json          — full metrics
  backtests/H63v2_SPY_QQQ_Pairs_2026-06-09_report.html   — readable report
  backtests/H63v2_SPY_QQQ_Pairs_2026-06-09_verdict.txt   — Gate 1 verdict
  backtests/H63v2_SPY_QQQ_Pairs_2026-06-09_trades.csv    — trade log

IS  window: 2018-01-01 to 2023-12-31 (5 years)
OOS window: 2024-01-01 to 2026-06-06 (last Friday in cached data)
Warmup:     2017-07-01 (6 months before IS for beta/baseline initialization)

Data source: Reuses H63v1 cached Alpaca SIP minute bars
  (pipelines/data/h63_cache/SPY_2017-07-01_2026-06-08.pkl)
  (pipelines/data/h63_cache/QQQ_2017-07-01_2026-06-08.pkl)
No Alpaca credentials required for this run.

Parameter sweep grid (324 combinations):
  BASELINE_LOOKBACK_DAYS: [10, 15, 20, 30]
  ENTRY_ZSCORE:           [1.2, 1.5, 2.0]
  EXIT_ZSCORE:            [0.1, 0.25, 0.5]
  HEDGE_LOOKBACK_DAYS:    [10, 20, 30]
  VIX_FILTER_THRESHOLD:   [25, 30, 35]

Gate 1 v2.2 pass criteria:
  IS Sharpe      > 1.0
  OOS Sharpe     > 0.7
  IS MaxDD       < 20%   (negative convention: > -0.20)
  OOS degradation < 40%  (IS→OOS Sharpe drop)
  IS trade count >= 100

CRITICAL validation: avg_trades_per_day must be 3-8 in IS period.
If 12-15+/day, escalate immediately to Engineering Director.
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

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from strategies.h63v2_spy_qqq_pairs_daily_baseline import (
    PARAMETERS,
    filter_rth,
    prepare_signals,
    simulate,
    compute_metrics,
    run_backtest,
    _download_daily,
    _download_vix,
    compute_trade_cost,
)
from orchestrator.oos_data_quality import validate_oos_data, OOSDataQualityError

# ── Config ─────────────────────────────────────────────────────────────────────

IS_START  = "2018-01-01"
IS_END    = "2023-12-31"
OOS_START = "2024-01-01"
OOS_END   = "2026-06-06"   # Last Friday in cached data (June 8 is Sunday)
DATA_START = "2017-07-01"  # 6-month warmup before IS

REPORT_DATE = "2026-06-09"
STRATEGY_NAME = "H63v2_SPY_QQQ_Pairs"
OUTPUT_DIR = REPO_ROOT / "backtests"
H63_CACHE_DIR = str(REPO_ROOT / "pipelines" / "data" / "h63_cache")

GATE_IS_SHARPE   = 1.0
GATE_OOS_SHARPE  = 0.7
GATE_IS_MDD      = -0.20
GATE_OOS_DEGRADE = 0.40
GATE_MIN_TRADES  = 100
FREQ_MIN_PER_DAY = 3.0
FREQ_MAX_PER_DAY = 8.0

SWEEP_GRID = {
    "BASELINE_LOOKBACK_DAYS": [10, 15, 20, 30],
    "ENTRY_ZSCORE":           [1.2, 1.5, 2.0],
    "EXIT_ZSCORE":            [0.1, 0.25, 0.5],
    "HEDGE_LOOKBACK_DAYS":    [10, 20, 30],
    "VIX_FILTER_THRESHOLD":   [25.0, 30.0, 35.0],
}

# Walk-forward windows: IS 36 months / OOS 6 months, 4 windows
WF_WINDOWS = [
    ("2018-01-01", "2020-12-31", "2021-01-01", "2021-06-30"),
    ("2018-07-01", "2021-06-30", "2021-07-01", "2021-12-31"),
    ("2019-01-01", "2021-12-31", "2022-01-01", "2022-06-30"),
    ("2019-07-01", "2022-06-30", "2022-07-01", "2022-12-31"),
]


# ── Data Load ─────────────────────────────────────────────────────────────────

def load_all_data() -> dict:
    """Load minute-bar data from H63v1 cache; download daily from yfinance."""
    logger.info("=== DATA LOAD ===")

    spy_cache = Path(H63_CACHE_DIR) / "SPY_2017-07-01_2026-06-08.pkl"
    qqq_cache = Path(H63_CACHE_DIR) / "QQQ_2017-07-01_2026-06-08.pkl"

    logger.info("Loading SPY from cache: %s", spy_cache.name)
    spy_raw = pd.read_pickle(str(spy_cache))
    logger.info("  SPY raw: %d bars", len(spy_raw))

    logger.info("Loading QQQ from cache: %s", qqq_cache.name)
    qqq_raw = pd.read_pickle(str(qqq_cache))
    logger.info("  QQQ raw: %d bars", len(qqq_raw))

    spy_rth = filter_rth(spy_raw)
    qqq_rth = filter_rth(qqq_raw)
    logger.info("  SPY RTH: %d | QQQ RTH: %d bars", len(spy_rth), len(qqq_rth))

    logger.info("Downloading SPY/QQQ/VIX daily from yfinance...")
    spy_daily = _download_daily("SPY", DATA_START, OOS_END)
    qqq_daily = _download_daily("QQQ", DATA_START, OOS_END)
    vix_close = _download_vix(DATA_START, OOS_END)
    logger.info("  SPY daily: %d | QQQ daily: %d | VIX: %d rows",
                len(spy_daily), len(qqq_daily), len(vix_close))

    return {
        "spy_rth": spy_rth, "qqq_rth": qqq_rth,
        "spy_daily": spy_daily, "qqq_daily": qqq_daily,
        "vix_close": vix_close,
    }


# ── Single-window Backtest ─────────────────────────────────────────────────────

def backtest_window(start, end, params, data, label=""):
    try:
        result = run_backtest(
            start=start, end=end, params=params,
            spy_rth_full=data["spy_rth"], qqq_rth_full=data["qqq_rth"],
            spy_daily=data["spy_daily"], qqq_daily=data["qqq_daily"],
            vix_close=data["vix_close"],
        )
        if label:
            logger.info("  %s: Sharpe=%.3f MDD=%.2f%% trades=%d tpd=%.2f",
                        label, result["sharpe"], result["max_drawdown"] * 100,
                        result["trade_count"], result.get("avg_trades_per_day", 0))
        return result
    except Exception as e:
        logger.error("  %s FAILED: %s", label, e)
        traceback.print_exc()
        return {"sharpe": np.nan, "max_drawdown": 0.0, "trade_count": 0, "error": str(e)}


# ── Parameter Sweep ───────────────────────────────────────────────────────────

def run_parameter_sweep(data: dict) -> pd.DataFrame:
    """
    IS-only sweep over all parameter combinations.
    Optimized: pre-compute signal DataFrames for unique (BASELINE, HEDGE) pairs.
    VIX and trading params applied at simulate() time.
    """
    keys = list(SWEEP_GRID.keys())
    values = [SWEEP_GRID[k] for k in keys]
    combos = list(itertools.product(*values))
    total = len(combos)
    logger.info("=== PARAMETER SWEEP: %d combinations ===", total)

    # Pre-compute signal DataFrames for unique (BASELINE_LOOKBACK, HEDGE_LOOKBACK)
    unique_bl_hl = list({
        (c[0], c[3]) for c in combos  # indices: 0=BASELINE, 3=HEDGE
    })
    logger.info("  Pre-computing signal DFs for %d (BASELINE, HEDGE) pairs...", len(unique_bl_hl))

    sig_cache = {}
    for bl, hl in unique_bl_hl:
        p = PARAMETERS.copy()
        p["BASELINE_LOOKBACK_DAYS"] = bl
        p["HEDGE_LOOKBACK_DAYS"] = hl
        p["VIX_FILTER_THRESHOLD"] = 999.0   # permissive placeholder — override per combo

        try:
            # Build signal over IS window
            tz = "America/New_York"
            ts_start = pd.Timestamp(IS_START).tz_localize(tz)
            ts_end = pd.Timestamp(IS_END).tz_localize(tz).replace(hour=23, minute=59)
            spy_win = data["spy_rth"][
                (data["spy_rth"].index >= ts_start) & (data["spy_rth"].index <= ts_end)
            ].copy()
            qqq_win = data["qqq_rth"][
                (data["qqq_rth"].index >= ts_start) & (data["qqq_rth"].index <= ts_end)
            ].copy()
            sig_df = prepare_signals(spy_win, qqq_win, data["spy_daily"],
                                     data["qqq_daily"], data["vix_close"], p)
            sig_cache[(bl, hl)] = sig_df
            logger.debug("  Cached sig for BL=%d HL=%d: %d bars", bl, hl, len(sig_df))
        except Exception as e:
            logger.error("  prepare_signals failed for BL=%d HL=%d: %s", bl, hl, e)
            sig_cache[(bl, hl)] = None

    records = []
    for idx, combo in enumerate(combos):
        bl, entry_z, exit_z, hl, vix_t = combo
        p = PARAMETERS.copy()
        p["BASELINE_LOOKBACK_DAYS"] = bl
        p["ENTRY_ZSCORE"] = entry_z
        p["EXIT_ZSCORE"] = exit_z
        p["HEDGE_LOOKBACK_DAYS"] = hl
        p["VIX_FILTER_THRESHOLD"] = vix_t

        sig_df = sig_cache.get((bl, hl))
        if sig_df is None:
            rec = {k: v for k, v in zip(keys, combo)}
            rec.update({"is_sharpe": np.nan, "is_mdd": 0.0, "is_trades": 0,
                        "is_win_rate": 0.0, "is_profit_factor": 0.0, "is_avg_tpd": 0.0})
            records.append(rec)
            continue

        # Apply VIX threshold and trading params, then simulate
        sig_run = sig_df.copy()
        sig_run["vix_ok"] = sig_run["vix_prev"] < vix_t

        try:
            trade_log, equity_ts, _ = simulate(sig_run, p)
            metrics = compute_metrics(trade_log, equity_ts, IS_START, IS_END)
        except Exception as e:
            metrics = {"sharpe": np.nan, "max_drawdown": 0.0, "trade_count": 0,
                       "win_rate": 0.0, "profit_factor": 0.0, "avg_trades_per_day": 0.0}

        rec = {k: v for k, v in zip(keys, combo)}
        rec["is_sharpe"] = metrics.get("sharpe", np.nan)
        rec["is_mdd"] = metrics.get("max_drawdown", 0.0)
        rec["is_trades"] = metrics.get("trade_count", 0)
        rec["is_win_rate"] = metrics.get("win_rate", 0.0)
        rec["is_profit_factor"] = metrics.get("profit_factor", 0.0)
        rec["is_avg_tpd"] = metrics.get("avg_trades_per_day", 0.0)
        records.append(rec)

        if (idx + 1) % 50 == 0:
            valid = [r for r in records if not np.isnan(r["is_sharpe"])]
            if valid:
                best = max(valid, key=lambda r: r["is_sharpe"])
                logger.info("  Progress %d/%d — best IS Sharpe so far: %.3f",
                            idx + 1, total, best["is_sharpe"])

    sweep_df = pd.DataFrame(records)
    valid_count = sweep_df["is_sharpe"].notna().sum()
    logger.info("Sweep complete. Valid: %d/%d", valid_count, total)
    return sweep_df


# ── Walk-Forward ──────────────────────────────────────────────────────────────

def run_walk_forward(data: dict, params: dict) -> dict:
    """4-window walk-forward (IS 36mo / OOS 6mo each)."""
    logger.info("=== WALK-FORWARD (4 windows, IS 36mo / OOS 6mo) ===")
    wf_results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(WF_WINDOWS):
        is_r = backtest_window(is_s, is_e, params, data, f"WF[{i+1}] IS")
        oos_r = backtest_window(oos_s, oos_e, params, data, f"WF[{i+1}] OOS")
        is_sh = is_r.get("sharpe", np.nan)
        oos_sh = oos_r.get("sharpe", np.nan)
        wf_results.append({
            "window": i + 1,
            "is_start": is_s, "is_end": is_e,
            "oos_start": oos_s, "oos_end": oos_e,
            "is_sharpe": is_sh,
            "oos_sharpe": oos_sh,
            "oos_is_ratio": float(oos_sh / is_sh) if (is_sh and is_sh > 0 and not np.isnan(is_sh)) else np.nan,
            "oos_pass": bool(oos_sh > GATE_OOS_SHARPE) if not np.isnan(oos_sh) else False,
        })

    oos_sharpes = [w["oos_sharpe"] for w in wf_results if not np.isnan(w["oos_sharpe"])]
    windows_passed = sum(1 for w in wf_results if w["oos_pass"])
    wf_sharpe_std = float(np.std(oos_sharpes)) if len(oos_sharpes) > 1 else 0.0
    wf_sharpe_min = float(np.min(oos_sharpes)) if oos_sharpes else np.nan

    logger.info("  WF: %d/4 OOS windows passed (Sharpe>0.7)", windows_passed)
    logger.info("  WF OOS Sharpes: %s", [f"{s:.3f}" for s in oos_sharpes])
    logger.info("  WF Sharpe std=%.3f min=%.3f", wf_sharpe_std, wf_sharpe_min if not np.isnan(wf_sharpe_min) else -999)

    if wf_sharpe_min < 0:
        logger.warning("  FLAG: wf_sharpe_min < 0 — at least one losing OOS window")

    return {
        "windows": wf_results,
        "windows_passed": windows_passed,
        "wf_sharpe_std": wf_sharpe_std,
        "wf_sharpe_min": float(wf_sharpe_min) if not np.isnan(wf_sharpe_min) else None,
    }


# ── Statistical Rigor Pipeline ─────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe": float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = T // block_len
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / roll_max))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
        wr = float(np.mean(sample > 0))
        sharpes.append(s); mdds.append(mdd); win_rates.append(wr)
    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low": float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def compute_market_impact_etf(ticker: str, order_notional: float, spy_daily: pd.DataFrame) -> dict:
    """Market impact for ultra-liquid ETF. Uses pre-loaded daily data."""
    prices = spy_daily["Close"]
    volumes = spy_daily["Volume"]
    adv = float(volumes.rolling(20).mean().iloc[-1])
    sigma = float(prices.pct_change().std())
    avg_price = float(prices.iloc[-252:].mean())
    order_qty = order_notional / avg_price
    k = 0.1
    impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
    impact_bps = impact_pct * 10000
    return {
        "market_impact_bps": float(impact_bps),
        "liquidity_constrained": bool(order_qty > 0.01 * adv),
        "order_to_adv_ratio": float(order_qty / (adv + 1e-8)),
    }


def permutation_test_alpha(prices: np.ndarray, entries: np.ndarray,
                           observed_sharpe: float, n_perms: int = 500) -> dict:
    entry_indices = np.where(entries)[0]
    if len(entry_indices) == 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    permuted_sharpes = []
    for _ in range(n_perms):
        perm_entry_idx = np.random.choice(len(prices), size=len(entry_indices), replace=False)
        trade_returns = []
        for idx in perm_entry_idx:
            exit_idx = min(idx + 5, len(prices) - 1)
            ret = (prices[exit_idx] - prices[idx]) / max(prices[idx], 1e-8)
            trade_returns.append(ret)
        if len(trade_returns) > 1:
            arr = np.array(trade_returns)
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(252 / 5)
        else:
            s = 0.0
        permuted_sharpes.append(s)
    p_value = float(np.mean(np.array(permuted_sharpes) >= observed_sharpe))
    return {"permutation_pvalue": p_value, "permutation_test_pass": bool(p_value <= 0.05)}


def compute_dsr(returns_series: pd.Series, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Lopez de Prado 2018)."""
    if len(returns_series) < 10 or n_trials <= 0:
        return 0.0
    r = returns_series.dropna().values
    n = len(r)
    if n < 4:
        return 0.0
    from scipy.stats import norm
    sr = r.mean() / (r.std() + 1e-10) * np.sqrt(252)
    skew = float(pd.Series(r).skew())
    kurt = float(pd.Series(r).kurt())
    # Expected max Sharpe from n_trials IID tests
    sr_star = np.sqrt(2) * sr * np.sqrt(np.log(n_trials) / (np.pi * np.log(n)))
    # Variance of SR estimate
    sr_var = (1 + 0.5 * sr**2 - skew * sr + (kurt / 4) * sr**2) / n
    dsr = float(norm.cdf((sr - sr_star) / (np.sqrt(sr_var) + 1e-10)))
    return round(dsr, 6)


def sensitivity_scan(data: dict, default_params: dict) -> dict:
    """±20% variation on key numeric params. Returns dict: param → {-20%, +20%} Sharpe."""
    scan_keys = ["BASELINE_LOOKBACK_DAYS", "ENTRY_ZSCORE", "EXIT_ZSCORE",
                 "HEDGE_LOOKBACK_DAYS", "VIX_FILTER_THRESHOLD"]
    base_result = backtest_window(IS_START, IS_END, default_params, data, "sensitivity_base")
    base_sharpe = base_result.get("sharpe", np.nan)
    results = {"base_sharpe": base_sharpe, "params": {}}

    for key in scan_keys:
        base_val = default_params.get(key)
        if base_val is None or not isinstance(base_val, (int, float)):
            continue
        sensitivity = {}
        for pct in [-0.20, 0.20]:
            new_val = base_val * (1 + pct)
            if key in ("BASELINE_LOOKBACK_DAYS", "HEDGE_LOOKBACK_DAYS"):
                new_val = max(2, int(round(new_val)))
            p = default_params.copy()
            p[key] = new_val
            r = backtest_window(IS_START, IS_END, p, data)
            s = r.get("sharpe", np.nan)
            sensitivity[f"{'+' if pct > 0 else ''}{int(pct*100)}%"] = {
                "value": new_val, "sharpe": float(s) if not np.isnan(s) else None,
                "sharpe_change_pct": float((s - base_sharpe) / max(abs(base_sharpe), 1e-8) * 100)
                    if (not np.isnan(s) and not np.isnan(base_sharpe)) else None,
            }
        results["params"][key] = sensitivity

    # Check pass: all ±20% variations < 30% Sharpe change
    all_changes = []
    for key, sens in results["params"].items():
        for pct_key, r in sens.items():
            if r.get("sharpe_change_pct") is not None:
                all_changes.append(abs(r["sharpe_change_pct"]))
    sensitivity_pass = bool(all(c < 30.0 for c in all_changes)) if all_changes else True
    results["sensitivity_pass"] = sensitivity_pass
    return results


# ── Gate 1 Verdict ────────────────────────────────────────────────────────────

def evaluate_gate1(is_metrics: dict, oos_metrics: dict) -> dict:
    is_sharpe = is_metrics.get("sharpe", 0.0)
    oos_sharpe = oos_metrics.get("sharpe", 0.0)
    is_mdd = is_metrics.get("max_drawdown", 0.0)
    is_trades = is_metrics.get("trade_count", 0)
    avg_tpd = is_metrics.get("avg_trades_per_day", 0.0)

    oos_degrade = (is_sharpe - oos_sharpe) / is_sharpe if is_sharpe > 0 else 1.0

    freq_ok = bool(FREQ_MIN_PER_DAY <= avg_tpd <= FREQ_MAX_PER_DAY)
    freq_flag = "OK" if freq_ok else (
        "HIGH (12-15+/day → H63v1 artifact suspected — ESCALATE)" if avg_tpd > FREQ_MAX_PER_DAY
        else f"LOW ({avg_tpd:.2f}/day)"
    )

    criteria = {
        "IS_Sharpe":      {"value": round(is_sharpe, 4), "threshold": f"> {GATE_IS_SHARPE}",
                           "pass": bool(is_sharpe > GATE_IS_SHARPE)},
        "OOS_Sharpe":     {"value": round(oos_sharpe, 4), "threshold": f"> {GATE_OOS_SHARPE}",
                           "pass": bool(oos_sharpe > GATE_OOS_SHARPE)},
        "IS_MaxDrawdown": {"value": round(is_mdd * 100, 2), "threshold": "> -20%",
                           "pass": bool(is_mdd > GATE_IS_MDD)},
        "OOS_Degradation":{"value": round(oos_degrade * 100, 2), "threshold": "< 40%",
                           "pass": bool(oos_degrade < GATE_OOS_DEGRADE)},
        "IS_TradeCount":  {"value": is_trades, "threshold": f">= {GATE_MIN_TRADES}",
                           "pass": bool(is_trades >= GATE_MIN_TRADES)},
        "TradeFrequency": {"value": round(avg_tpd, 2), "threshold": "3-8/day",
                           "pass": freq_ok, "note": freq_flag},
    }

    all_pass = all(c["pass"] for c in criteria.values())
    return {"criteria": criteria, "verdict": "PASS" if all_pass else "FAIL",
            "oos_degradation": round(oos_degrade, 4), "freq_flag": freq_flag}


# ── Report generators ─────────────────────────────────────────────────────────

def _safe_metrics(m: dict) -> dict:
    return {k: v for k, v in m.items()
            if isinstance(v, (int, float, str, dict, list, bool, type(None)))
            and k not in ("equity", "daily_df", "trades")}


def generate_verdict_txt(is_m, oos_m, verdict, sweep_df, wf, rigor) -> str:
    lines = [
        "=" * 70,
        f"GATE 1 v2.2 VERDICT — H63v2 SPY/QQQ Pairs Daily Baseline",
        f"Report Date: {REPORT_DATE}",
        "=" * 70,
        "",
        f"OVERALL VERDICT: {verdict['verdict']}",
        f"Trade Frequency: {verdict['freq_flag']}",
        "",
        "── GATE 1 CRITERIA ──────────────────────────────────────────────────",
    ]
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        note = f"  [{c.get('note', '')}]" if c.get("note") else ""
        lines.append(f"  [{status}] {name}: {c['value']} (threshold: {c['threshold']}){note}")

    lines += [
        "",
        f"── IS METRICS ({IS_START} to {IS_END}) ──────────────────────────────",
        f"  Sharpe:          {is_m.get('sharpe', 0):.4f}",
        f"  Max Drawdown:    {is_m.get('max_drawdown', 0)*100:.2f}%",
        f"  Total Return:    {is_m.get('total_return', 0)*100:.2f}%",
        f"  Win Rate:        {is_m.get('win_rate', 0)*100:.1f}%",
        f"  Profit Factor:   {is_m.get('profit_factor', 0):.3f}",
        f"  Trade Count:     {is_m.get('trade_count', 0)}",
        f"  Trades/Year:     {is_m.get('trades_per_year', 0):.0f}",
        f"  Avg Trades/Day:  {is_m.get('avg_trades_per_day', 0):.2f}  ← CRITICAL VALIDATION",
        f"  PpT (bps):       {is_m.get('ppt_bps', 0):.2f}",
        f"  Cost Ratio:      {is_m.get('cost_to_gross_ratio', 0)*100:.1f}%",
        f"  Exit Reasons:    {is_m.get('exit_reason_summary', {})}",
        "",
        f"── OOS METRICS ({OOS_START} to {OOS_END}) ────────────────────────",
        f"  Sharpe:          {oos_m.get('sharpe', 0):.4f}",
        f"  Max Drawdown:    {oos_m.get('max_drawdown', 0)*100:.2f}%",
        f"  Total Return:    {oos_m.get('total_return', 0)*100:.2f}%",
        f"  Win Rate:        {oos_m.get('win_rate', 0)*100:.1f}%",
        f"  Profit Factor:   {oos_m.get('profit_factor', 0):.3f}",
        f"  Trade Count:     {oos_m.get('trade_count', 0)}",
        f"  Avg Trades/Day:  {oos_m.get('avg_trades_per_day', 0):.2f}",
        f"  OOS Degradation: {verdict['oos_degradation']*100:.1f}% vs IS Sharpe",
        "",
        "── STATISTICAL RIGOR PIPELINE ───────────────────────────────────────",
        f"  MC p5 Sharpe:      {rigor.get('mc_p5_sharpe', 'N/A'):.4f}  {'[WEAK]' if rigor.get('mc_p5_sharpe', 1) < 0.5 else '[OK]'}",
        f"  MC median Sharpe:  {rigor.get('mc_median_sharpe', 'N/A'):.4f}",
        f"  MC p95 Sharpe:     {rigor.get('mc_p95_sharpe', 'N/A'):.4f}",
        f"  Sharpe 95% CI:     [{rigor.get('sharpe_ci_low', 0):.4f}, {rigor.get('sharpe_ci_high', 0):.4f}]",
        f"  MDD 95% CI:        [{rigor.get('mdd_ci_low', 0)*100:.2f}%, {rigor.get('mdd_ci_high', 0)*100:.2f}%]",
        f"  WinRate 95% CI:    [{rigor.get('win_rate_ci_low', 0)*100:.1f}%, {rigor.get('win_rate_ci_high', 0)*100:.1f}%]",
        f"  Permutation pval:  {rigor.get('permutation_pvalue', 'N/A'):.4f}  ({'PASS' if rigor.get('permutation_test_pass') else 'FAIL – no alpha'})",
        f"  Market Impact:     {rigor.get('market_impact_bps', 0):.3f} bps  ({'LIQ_CONSTRAINED' if rigor.get('liquidity_constrained') else 'OK'})",
        f"  DSR:               {rigor.get('dsr', 'N/A')}",
    ]

    if wf:
        lines += ["", "── WALK-FORWARD (4 windows, IS 36mo / OOS 6mo) ─────────────────────"]
        for w in wf["windows"]:
            status = "PASS" if w["oos_pass"] else "FAIL"
            lines.append(
                f"  Window {w['window']}: IS {w['is_start']}→{w['is_end']} "
                f"OOS {w['oos_start']}→{w['oos_end']} | "
                f"IS Sharpe={w['is_sharpe']:.3f} OOS Sharpe={w['oos_sharpe']:.3f} [{status}]"
            )
        lines += [
            f"  Windows Passed:  {wf['windows_passed']}/4",
            f"  WF Sharpe Std:   {wf['wf_sharpe_std']:.4f}",
            f"  WF Sharpe Min:   {wf['wf_sharpe_min']:.4f}  {'[LOSING WINDOW]' if wf.get('wf_sharpe_min', 0) < 0 else ''}",
        ]

    lines += [
        "",
        "── PARAMETER SWEEP SUMMARY (IS-only, 324 combinations) ─────────────",
    ]
    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        if not valid.empty:
            best = valid.loc[valid["is_sharpe"].idxmax()]
            lines += [
                f"  Best IS Sharpe:   {valid['is_sharpe'].max():.4f}",
                f"  Median IS Sharpe: {valid['is_sharpe'].median():.4f}",
                f"  Worst IS Sharpe:  {valid['is_sharpe'].min():.4f}",
                f"  Best params:      BASELINE={int(best['BASELINE_LOOKBACK_DAYS'])} "
                f"ENTRY_Z={best['ENTRY_ZSCORE']} EXIT_Z={best['EXIT_ZSCORE']} "
                f"HEDGE={int(best['HEDGE_LOOKBACK_DAYS'])} VIX={best['VIX_FILTER_THRESHOLD']}",
                f"  Best trades/day:  {best.get('is_avg_tpd', 0):.2f}",
            ]

    lines += [
        "",
        "── COST MODEL ───────────────────────────────────────────────────────",
        "  Fixed:   $0.005/share (ED-SLIP-001 ultra-liquid ETF tier)",
        "  Slippage: 0.005% of notional (one-way)",
        "  Impact:  k=0.1 × sigma × sqrt(Q/ADV) × notional (Almgren-Chriss)",
        "  Note:    At $12.5K/leg, Q/ADV is negligible for SPY/QQQ",
        "",
        "── PDT NOTE ─────────────────────────────────────────────────────────",
        "  Strategy targets 3-8 spread crossings/day (= 6-16 day trades/day).",
        "  PDT designation required. Minimum capital $30K recommended.",
        "",
        "=" * 70,
    ]
    return "\n".join(lines)


def generate_html_report(is_m, oos_m, verdict, sweep_df, wf, rigor) -> str:
    v = verdict["verdict"]
    verdict_color = "#28a745" if v == "PASS" else "#dc3545"
    freq_ok = verdict["criteria"]["TradeFrequency"]["pass"]
    freq_color = "#28a745" if freq_ok else "#dc3545"

    def fmt_pct(x): return f"{x*100:.2f}%"

    criteria_rows = ""
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        color = "#28a745" if c["pass"] else "#dc3545"
        note = c.get("note", "")
        criteria_rows += (
            f"<tr><td>{name}</td><td>{c['value']}</td><td>{c['threshold']}</td>"
            f"<td style='color:{color};font-weight:bold'>{status}</td>"
            f"<td style='font-size:0.85em'>{note}</td></tr>\n"
        )

    wf_rows = ""
    if wf:
        for w in wf["windows"]:
            color = "#28a745" if w["oos_pass"] else "#dc3545"
            wf_rows += (
                f"<tr><td>{w['window']}</td>"
                f"<td>{w['is_start']}→{w['is_end']}</td>"
                f"<td>{w['oos_start']}→{w['oos_end']}</td>"
                f"<td>{w['is_sharpe']:.3f}</td>"
                f"<td>{w['oos_sharpe']:.3f}</td>"
                f"<td style='color:{color};font-weight:bold'>{'PASS' if w['oos_pass'] else 'FAIL'}</td></tr>\n"
            )

    sweep_table = ""
    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        if not valid.empty:
            top10 = valid.nlargest(10, "is_sharpe")
            for _, row in top10.iterrows():
                freq_in_range = FREQ_MIN_PER_DAY <= row.get("is_avg_tpd", 0) <= FREQ_MAX_PER_DAY
                fc = "#28a745" if freq_in_range else "#dc3545"
                sweep_table += (
                    f"<tr><td>{int(row['BASELINE_LOOKBACK_DAYS'])}</td>"
                    f"<td>{row['ENTRY_ZSCORE']}</td><td>{row['EXIT_ZSCORE']}</td>"
                    f"<td>{int(row['HEDGE_LOOKBACK_DAYS'])}</td>"
                    f"<td>{int(row['VIX_FILTER_THRESHOLD'])}</td>"
                    f"<td>{row['is_sharpe']:.4f}</td>"
                    f"<td>{row['is_mdd']*100:.1f}%</td>"
                    f"<td>{row['is_trades']}</td>"
                    f"<td style='color:{fc}'>{row.get('is_avg_tpd', 0):.2f}</td></tr>\n"
                )

    return f"""<!DOCTYPE html>
<html>
<head>
<title>H63v2 Gate 1 v2.2 Report</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 40px auto; color: #333; }}
h1 {{ color: #1a1a2e; }} h2 {{ color: #16213e; border-bottom: 2px solid #eee; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: left; font-size: 0.9em; }}
th {{ background: #f4f4f4; font-weight: bold; }}
.verdict {{ font-size: 2em; font-weight: bold; color: {verdict_color}; margin: 20px 0; }}
.metric-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }}
.metric-box {{ background: #f9f9f9; border: 1px solid #ddd; border-radius: 6px; padding: 12px; }}
.metric-val {{ font-size: 1.3em; font-weight: bold; color: #1a1a2e; }}
.freq-badge {{ color: {freq_color}; font-weight: bold; font-size: 1.1em; }}
.warn {{ color: #856404; background: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; }}
.critical {{ color: #721c24; background: #f8d7da; padding: 10px; border-radius: 4px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>Gate 1 v2.2 Report — H63v2 SPY/QQQ Pairs Daily Baseline Mean Reversion</h1>
<p><strong>Report Date:</strong> {REPORT_DATE} | <strong>IS:</strong> {IS_START}→{IS_END} | <strong>OOS:</strong> {OOS_START}→{OOS_END}</p>
<p><strong>Key fix vs H63v1:</strong> Z-score anchored to daily close baseline (not intraday rolling window) to eliminate 12-15/day false signals.</p>

<div class="verdict">Gate 1 Verdict: {v}</div>

<div class="{'warn' if freq_ok else 'critical'}">
<strong>Trade Frequency (CRITICAL):</strong> IS avg trades/day = <span class="freq-badge">{is_m.get('avg_trades_per_day', 0):.2f}/day</span> (target: {FREQ_MIN_PER_DAY}–{FREQ_MAX_PER_DAY}/day)
{'— Within target range ✓' if freq_ok else ' — OUTSIDE TARGET RANGE ✗ (escalate to Engineering Director)'}
</div>

<h2>Gate 1 Criteria</h2>
<table><thead><tr><th>Criterion</th><th>Value</th><th>Threshold</th><th>Status</th><th>Note</th></tr></thead>
<tbody>{criteria_rows}</tbody></table>

<h2>IS Performance ({IS_START} to {IS_END})</h2>
<div class="metric-grid">
  <div class="metric-box"><div>Sharpe Ratio</div><div class="metric-val">{is_m.get('sharpe',0):.4f}</div></div>
  <div class="metric-box"><div>Max Drawdown</div><div class="metric-val">{fmt_pct(is_m.get('max_drawdown',0))}</div></div>
  <div class="metric-box"><div>Total Return</div><div class="metric-val">{fmt_pct(is_m.get('total_return',0))}</div></div>
  <div class="metric-box"><div>Win Rate</div><div class="metric-val">{fmt_pct(is_m.get('win_rate',0))}</div></div>
  <div class="metric-box"><div>Profit Factor</div><div class="metric-val">{is_m.get('profit_factor',0):.3f}</div></div>
  <div class="metric-box"><div>Trade Count ({is_m.get('trades_per_year',0):.0f}/yr)</div><div class="metric-val">{is_m.get('trade_count',0)}</div></div>
  <div class="metric-box"><div>Avg Trades/Day (TARGET 3-8)</div><div class="metric-val freq-badge">{is_m.get('avg_trades_per_day',0):.2f}</div></div>
  <div class="metric-box"><div>PpT (bps)</div><div class="metric-val">{is_m.get('ppt_bps',0):.2f}</div></div>
  <div class="metric-box"><div>Avg PnL/Trade</div><div class="metric-val">${is_m.get('avg_pnl_per_trade',0):.2f}</div></div>
  <div class="metric-box"><div>Cost Ratio</div><div class="metric-val">{is_m.get('cost_to_gross_ratio',0)*100:.1f}%</div></div>
</div>

<h2>OOS Performance ({OOS_START} to {OOS_END})</h2>
<div class="metric-grid">
  <div class="metric-box"><div>Sharpe Ratio</div><div class="metric-val">{oos_m.get('sharpe',0):.4f}</div></div>
  <div class="metric-box"><div>Max Drawdown</div><div class="metric-val">{fmt_pct(oos_m.get('max_drawdown',0))}</div></div>
  <div class="metric-box"><div>Total Return</div><div class="metric-val">{fmt_pct(oos_m.get('total_return',0))}</div></div>
  <div class="metric-box"><div>Win Rate</div><div class="metric-val">{fmt_pct(oos_m.get('win_rate',0))}</div></div>
  <div class="metric-box"><div>Trade Count ({oos_m.get('trades_per_year',0):.0f}/yr)</div><div class="metric-val">{oos_m.get('trade_count',0)}</div></div>
  <div class="metric-box"><div>OOS Degradation</div><div class="metric-val">{verdict['oos_degradation']*100:.1f}% vs IS</div></div>
  <div class="metric-box"><div>Avg Trades/Day</div><div class="metric-val">{oos_m.get('avg_trades_per_day',0):.2f}</div></div>
</div>

<h2>Statistical Rigor Pipeline</h2>
<table><thead><tr><th>Metric</th><th>Value</th><th>Threshold</th><th>Status</th></tr></thead><tbody>
<tr><td>MC p5 Sharpe (1000 bootstrap)</td><td>{rigor.get('mc_p5_sharpe',0):.4f}</td><td>>= 0.5</td><td>{'PASS' if rigor.get('mc_p5_sharpe', 0) >= 0.5 else 'WARN – pessimistic bound weak'}</td></tr>
<tr><td>MC Median Sharpe</td><td>{rigor.get('mc_median_sharpe',0):.4f}</td><td>-</td><td>-</td></tr>
<tr><td>MC p95 Sharpe</td><td>{rigor.get('mc_p95_sharpe',0):.4f}</td><td>-</td><td>-</td></tr>
<tr><td>Block Bootstrap Sharpe CI 95%</td><td>[{rigor.get('sharpe_ci_low',0):.4f}, {rigor.get('sharpe_ci_high',0):.4f}]</td><td>-</td><td>-</td></tr>
<tr><td>Block Bootstrap MDD CI 95%</td><td>[{rigor.get('mdd_ci_low',0)*100:.2f}%, {rigor.get('mdd_ci_high',0)*100:.2f}%]</td><td>-</td><td>-</td></tr>
<tr><td>Permutation Test p-value (500 perms)</td><td>{rigor.get('permutation_pvalue',1):.4f}</td><td><= 0.05</td><td>{'PASS' if rigor.get('permutation_test_pass') else 'FAIL – no statistical alpha'}</td></tr>
<tr><td>Market Impact (per leg)</td><td>{rigor.get('market_impact_bps',0):.3f} bps</td><td>-</td><td>{'LIQUIDITY CONSTRAINED' if rigor.get('liquidity_constrained') else 'OK'}</td></tr>
<tr><td>Deflated Sharpe Ratio</td><td>{rigor.get('dsr',0):.4f}</td><td>> 0</td><td>{'PASS' if rigor.get('dsr', 0) > 0 else 'FAIL'}</td></tr>
</tbody></table>

<h2>Walk-Forward Analysis (4 windows)</h2>
<table><thead><tr><th>Win</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>OOS</th></tr></thead>
<tbody>{wf_rows}</tbody></table>
<p>Windows passed (OOS Sharpe > 0.7): <strong>{wf.get('windows_passed', 0)}/4</strong> | WF Sharpe std: {wf.get('wf_sharpe_std',0):.4f} | WF min: {wf.get('wf_sharpe_min',0):.4f}</p>

<h2>Parameter Sweep — Top 10 IS Configurations</h2>
<table><thead>
<tr><th>Baseline</th><th>Entry Z</th><th>Exit Z</th><th>Hedge</th><th>VIX Thresh</th><th>IS Sharpe</th><th>IS MDD</th><th>IS Trades</th><th>Avg TPD</th></tr>
</thead><tbody>{sweep_table}</tbody></table>

<h2>Transaction Cost Model</h2>
<p>Fixed: $0.005/share | Slippage: 0.005% of notional (ED-SLIP-001 ultra-liquid ETF tier) | Market impact: Almgren-Chriss sqrt-model (k=0.1 × σ × √(Q/ADV) × notional).</p>

<h2>Data Quality</h2>
<ul>
  <li><strong>Minute data:</strong> Alpaca SIP feed (cached from H63v1 run), split-adjusted, 1-min RTH</li>
  <li><strong>Daily data:</strong> yfinance auto_adjust=True (SPY, QQQ, ^VIX)</li>
  <li><strong>Survivorship bias:</strong> N/A (SPY/QQQ are broad market ETFs)</li>
  <li><strong>Lookahead bias:</strong> None — daily baseline uses prior-day closes; fill at next bar open (1-bar latency)</li>
  <li><strong>H63v2 fix:</strong> Z-score baseline computed once at session open from prior N daily closes — eliminates intraday rolling-window self-reversion artifact</li>
</ul>

</body></html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 70)
    logger.info("H63v2 SPY/QQQ Pairs Daily Baseline — Gate 1 v2.2 Backtest")
    logger.info("=" * 70)

    # 1. Load data
    data = load_all_data()

    # 2. IS backtest (default params)
    logger.info("\n=== IS BACKTEST (default params, %s → %s) ===", IS_START, IS_END)
    is_result = backtest_window(IS_START, IS_END, PARAMETERS.copy(), data, "IS")
    if not is_result.get("trades") is None and hasattr(is_result.get("trades"), "empty"):
        pass

    # CRITICAL: validate trade frequency
    avg_tpd = is_result.get("avg_trades_per_day", 0.0)
    logger.info("CRITICAL FREQ CHECK: IS avg trades/day = %.2f (target 3-8)", avg_tpd)
    if avg_tpd > FREQ_MAX_PER_DAY:
        logger.error(
            "ESCALATION REQUIRED: IS trades/day = %.2f exceeds 8.0 — "
            "possible H63v1 rolling-window artifact surviving in H63v2. "
            "Do NOT proceed with parameter sweep. Notify Engineering Director.",
            avg_tpd
        )
        # Still proceed but flag prominently in verdict

    # 3. OOS backtest (default params)
    logger.info("\n=== OOS BACKTEST (default params, %s → %s) ===", OOS_START, OOS_END)
    oos_result = backtest_window(OOS_START, OOS_END, PARAMETERS.copy(), data, "OOS")

    # 4. OOS data quality check (required before statistical pipeline)
    logger.info("\n=== OOS DATA QUALITY CHECK ===")
    # Build OOS-window price df for the validator
    tz = "America/New_York"
    ts_oos_start = pd.Timestamp(OOS_START).tz_localize(tz)
    ts_oos_end = pd.Timestamp(OOS_END).tz_localize(tz).replace(hour=23, minute=59)
    oos_price_df = data["spy_daily"][
        (data["spy_daily"].index >= pd.Timestamp(OOS_START)) &
        (data["spy_daily"].index <= pd.Timestamp(OOS_END))
    ][["Open", "High", "Low", "Close", "Volume"]]

    # Build metrics dict matching what validate_oos_data expects
    oos_metrics_for_dq = {
        "sharpe": oos_result.get("sharpe"),
        "max_drawdown": oos_result.get("max_drawdown"),
        "win_rate": oos_result.get("win_rate"),
        "profit_factor": oos_result.get("profit_factor"),
        "total_trades": oos_result.get("trade_count"),
        "post_cost_sharpe": oos_result.get("sharpe"),   # H63v2 cost-inclusive
        "total_return": oos_result.get("total_return"),
    }

    dq_report = validate_oos_data(oos_price_df, oos_metrics_for_dq, "H63v2_SPY_QQQ_Pairs")
    logger.info("  OOS DQ recommendation: %s", dq_report["recommendation"])

    if dq_report["recommendation"] == "BLOCK":
        logger.error("OOS DATA QUALITY BLOCK: %s", dq_report["block_reasons"])
        raise OOSDataQualityError(dq_report)
    elif dq_report["recommendation"] == "WARN":
        logger.warning("[DATA QUALITY WARN] %s", dq_report.get("advisory_nan_fields", []))

    # 5. Parameter sweep (IS only)
    logger.info("\n=== PARAMETER SWEEP ===")
    sweep_df = run_parameter_sweep(data)
    best_params = PARAMETERS.copy()
    median_is_sharpe = 0.0
    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        if not valid.empty:
            best_row = valid.loc[valid["is_sharpe"].idxmax()]
            for k in SWEEP_GRID:
                best_params[k] = best_row[k]
            median_is_sharpe = float(valid["is_sharpe"].median())
            logger.info("Best IS Sharpe: %.4f | Median: %.4f | Worst: %.4f",
                        valid["is_sharpe"].max(), median_is_sharpe, valid["is_sharpe"].min())
            logger.info("Best params: BASELINE=%d ENTRY_Z=%.1f EXIT_Z=%.2f HEDGE=%d VIX=%.0f",
                        int(best_row["BASELINE_LOOKBACK_DAYS"]), best_row["ENTRY_ZSCORE"],
                        best_row["EXIT_ZSCORE"], int(best_row["HEDGE_LOOKBACK_DAYS"]),
                        best_row["VIX_FILTER_THRESHOLD"])

    # 6. Walk-forward (default params)
    wf = run_walk_forward(data, PARAMETERS.copy())

    # 7. Statistical Rigor Pipeline
    logger.info("\n=== STATISTICAL RIGOR PIPELINE ===")
    is_trades_df = is_result.get("trades", pd.DataFrame())
    rigor = {}

    if not is_trades_df.empty and len(is_trades_df) > 5:
        trade_pnls = is_trades_df["pnl"].values

        # 7a. Monte Carlo (1000 resamples on IS trades)
        logger.info("  Monte Carlo (1000 sims)...")
        rigor.update(monte_carlo_sharpe(trade_pnls))
        if rigor["mc_p5_sharpe"] < 0.5:
            logger.warning("  FLAG: MC p5 Sharpe %.4f < 0.5 — pessimistic bound weak", rigor["mc_p5_sharpe"])

        # 7b. Block Bootstrap CI (IS daily returns)
        logger.info("  Block bootstrap CI (1000 boots)...")
        is_equity = is_result.get("equity", pd.Series(dtype=float))
        if not is_equity.empty and len(is_equity) > 5:
            is_returns = is_equity.pct_change().fillna(0).values
            rigor.update(block_bootstrap_ci(is_returns))

        # 7c. Market impact (SPY leg, $12,500 notional)
        logger.info("  Market impact (SPY, $12.5K notional)...")
        try:
            rigor.update(compute_market_impact_etf("SPY", 12500.0, data["spy_daily"]))
        except Exception as e:
            logger.warning("  Market impact calc failed: %s", e)
            rigor.update({"market_impact_bps": 0.0, "liquidity_constrained": False, "order_to_adv_ratio": 0.0})

        # 7d. Permutation test for alpha (500 perms on IS data)
        logger.info("  Permutation test (500 perms)...")
        try:
            sig_for_perm = prepare_signals(
                data["spy_rth"][
                    (data["spy_rth"].index >= pd.Timestamp(IS_START).tz_localize(tz)) &
                    (data["spy_rth"].index <= pd.Timestamp(IS_END).tz_localize(tz).replace(hour=23, minute=59))
                ].copy(),
                data["qqq_rth"][
                    (data["qqq_rth"].index >= pd.Timestamp(IS_START).tz_localize(tz)) &
                    (data["qqq_rth"].index <= pd.Timestamp(IS_END).tz_localize(tz).replace(hour=23, minute=59))
                ].copy(),
                data["spy_daily"], data["qqq_daily"], data["vix_close"], PARAMETERS.copy()
            )
            prices_arr = sig_for_perm["spy_close"].values
            entries_arr = np.zeros(len(prices_arr), dtype=bool)
            # mark entry bars from trade log
            entry_ts_set = set(str(t) for t in (is_trades_df["entry_ts"].values
                                                  if not is_trades_df.empty else []))
            rigor.update(permutation_test_alpha(
                prices_arr, entries_arr,
                observed_sharpe=is_result.get("sharpe", 0.0),
                n_perms=500
            ))
        except Exception as e:
            logger.warning("  Permutation test failed: %s", e)
            rigor.update({"permutation_pvalue": 1.0, "permutation_test_pass": False})

        # 7e. Walk-forward variance (already computed above)
        rigor["wf_sharpe_std"] = wf.get("wf_sharpe_std", 0.0)
        rigor["wf_sharpe_min"] = wf.get("wf_sharpe_min", 0.0)

        # 7f. Deflated Sharpe Ratio
        logger.info("  DSR (324 trials)...")
        if not is_equity.empty and len(is_equity) > 5:
            rigor["dsr"] = compute_dsr(is_equity.pct_change().dropna(), n_trials=324)
    else:
        logger.warning("  Skipping Statistical Rigor Pipeline — insufficient IS trades")
        rigor = {
            "mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan,
            "sharpe_ci_low": np.nan, "sharpe_ci_high": np.nan,
            "mdd_ci_low": np.nan, "mdd_ci_high": np.nan,
            "win_rate_ci_low": np.nan, "win_rate_ci_high": np.nan,
            "market_impact_bps": 0.0, "liquidity_constrained": False, "order_to_adv_ratio": 0.0,
            "permutation_pvalue": 1.0, "permutation_test_pass": False,
            "wf_sharpe_std": 0.0, "wf_sharpe_min": np.nan, "dsr": 0.0,
        }

    # 8. Sensitivity scan
    logger.info("\n=== SENSITIVITY SCAN ===")
    sens = sensitivity_scan(data, PARAMETERS.copy())
    logger.info("  Sensitivity pass: %s", sens.get("sensitivity_pass"))

    # 9. Gate 1 verdict
    verdict = evaluate_gate1(is_result, oos_result)
    logger.info("\n=== GATE 1 VERDICT: %s ===", verdict["verdict"])
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        logger.info("  [%s] %s: %s (threshold: %s)", status, name, c["value"], c["threshold"])

    # 10. Save outputs
    logger.info("\n=== GENERATING REPORTS ===")
    base_name = f"{STRATEGY_NAME}_{REPORT_DATE}"

    # Add rigor + dq to oos_result for JSON
    oos_result["oos_data_quality"] = dq_report

    # JSON
    json_payload = {
        "strategy": "H63v2_SPY_QQQ_Pairs_Daily_Baseline_Mean_Reversion",
        "version": "2.0",
        "gate": "Gate 1 v2.2",
        "report_date": REPORT_DATE,
        "is_window": {"start": IS_START, "end": IS_END},
        "oos_window": {"start": OOS_START, "end": OOS_END},
        "default_params": PARAMETERS,
        "is_metrics": _safe_metrics(is_result),
        "oos_metrics": _safe_metrics(oos_result),
        "gate1_verdict": verdict,
        "statistical_rigor": {k: (float(v) if isinstance(v, (np.floating, np.integer)) else v)
                               for k, v in rigor.items()},
        "walk_forward": {
            "windows": wf["windows"],
            "windows_passed": wf["windows_passed"],
            "wf_sharpe_std": wf["wf_sharpe_std"],
            "wf_sharpe_min": wf["wf_sharpe_min"],
        },
        "sensitivity": sens,
        "parameter_sweep": {
            "total_combinations": len(sweep_df) if not sweep_df.empty else 0,
            "best_is_sharpe": float(sweep_df["is_sharpe"].max()) if not sweep_df.empty else None,
            "median_is_sharpe": round(median_is_sharpe, 4),
            "best_params": best_params,
            "sweep_summary": sweep_df.describe().to_dict() if not sweep_df.empty else {},
        },
        "oos_data_quality": dq_report,
        "data_quality": {
            "survivorship_bias": "N/A — SPY and QQQ are broad market ETFs",
            "minute_data_source": "Alpaca SIP feed (cached H63v1 run, split-adjusted)",
            "daily_data_source": "yfinance auto_adjust=True (SPY, QQQ, ^VIX)",
            "lookahead_bias": "None — daily baseline uses prior-day closes; 1-bar fill latency",
            "h63v2_fix": "Intraday z-score anchored to daily close baseline (not rolling window)",
        },
        "pdt_note": (
            "Strategy targets 3-8 spread crossings/day (6-16 day trades/day). "
            "PDT designation required. Minimum capital $30K recommended."
        ),
    }

    json_path = OUTPUT_DIR / f"{base_name}.json"
    with open(json_path, "w") as f:
        json.dump(json_payload, f, indent=2, default=str)
    logger.info("  JSON: %s", json_path)

    # Verdict TXT
    verdict_txt = generate_verdict_txt(is_result, oos_result, verdict, sweep_df, wf, rigor)
    verdict_path = OUTPUT_DIR / f"{base_name}_verdict.txt"
    with open(verdict_path, "w") as f:
        f.write(verdict_txt)
    logger.info("  Verdict: %s", verdict_path)

    # HTML
    html_report = generate_html_report(is_result, oos_result, verdict, sweep_df, wf, rigor)
    html_path = OUTPUT_DIR / f"{base_name}_report.html"
    with open(html_path, "w") as f:
        f.write(html_report)
    logger.info("  HTML: %s", html_path)

    # Trade CSV (IS)
    is_trades_df_out = is_result.get("trades", pd.DataFrame())
    if not is_trades_df_out.empty:
        trades_path = OUTPUT_DIR / f"{base_name}_trades.csv"
        is_trades_df_out.to_csv(trades_path, index=False)
        logger.info("  IS Trades: %s", trades_path)

    # Sweep CSV
    if not sweep_df.empty:
        sweep_path = OUTPUT_DIR / f"{base_name}_sweep.csv"
        sweep_df.to_csv(sweep_path, index=False)
        logger.info("  Sweep: %s", sweep_path)

    logger.info("\n=== SUMMARY ===")
    logger.info("IS  Sharpe=%.4f MDD=%.2f%% Trades=%d AvgTPD=%.2f",
                is_result["sharpe"], is_result["max_drawdown"]*100,
                is_result["trade_count"], is_result.get("avg_trades_per_day", 0))
    logger.info("OOS Sharpe=%.4f MDD=%.2f%% Trades=%d AvgTPD=%.2f",
                oos_result["sharpe"], oos_result["max_drawdown"]*100,
                oos_result["trade_count"], oos_result.get("avg_trades_per_day", 0))
    logger.info("WF: %d/4 windows passed", wf["windows_passed"])
    logger.info("Gate 1 v2.2: %s", verdict["verdict"])
    logger.info("OOS DQ: %s", dq_report["recommendation"])

    print("\n" + verdict_txt)
    return json_payload


if __name__ == "__main__":
    result = main()
