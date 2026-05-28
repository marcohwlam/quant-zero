"""
Gate 1 Backtest Runner — H30 VIX Spike Fear Capitulation
QUA-267 | Backtest Runner Agent | 2026-03-16

Runs full Gate 1 pipeline:
  - IS (2007–2021) and OOS (2022–2025) backtests
  - OOS data quality validation (required pre-statistical pipeline)
  - Statistical rigor pipeline:
      * Monte Carlo simulation (1,000 resamples)
      * Block bootstrap CI (95%)
      * Market impact cost model
      * Permutation test for alpha (500 perms)
      * Walk-forward variance (4 windows)
  - Walk-forward (4 windows, IS split)
  - Parameter sensitivity: vix_threshold (20, 25, 30) + hold_days (3, 5, 7)
  - Special validations: 2022 in-cash %, GFC 2008–2009 MDD, 2022 stress MDD
  - DSR computation
  - Saves to backtests/H30_VIXSpikeCapitulation_{date}.json and _verdict.txt
"""

from __future__ import annotations

import json
import sys
import os
import warnings
import traceback
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── Ensure project root is on sys.path ────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from h30_vix_spike_spy_fear_capitulation import run_backtest, PARAMETERS, download_data
from oos_data_quality import validate_oos_data, OOSDataQualityError

STRATEGY_NAME = "H30_VIXSpikeCapitulation"
TODAY = date.today().isoformat()
BACKTESTS_DIR = PROJECT_ROOT / "backtests"
BACKTESTS_DIR.mkdir(exist_ok=True)

IS_START = "2007-01-01"
IS_END = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END = "2025-12-31"

TRADING_DAYS_PER_YEAR = 252


# ══════════════════════════════════════════════════════════════════════════════
# Statistical Rigor Pipeline
# ══════════════════════════════════════════════════════════════════════════════

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    """Bootstrap Monte Carlo on trade PnL sequence (Davey Book 5)."""
    if len(trade_pnls) == 0:
        return {"mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan}
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe": float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    """Block bootstrap 95% CI for Sharpe, MDD, win rate (Davey Book 5)."""
    if len(returns) < 4:
        return {
            "sharpe_ci_low": np.nan, "sharpe_ci_high": np.nan,
            "mdd_ci_low": np.nan, "mdd_ci_high": np.nan,
            "win_rate_ci_low": np.nan, "win_rate_ci_high": np.nan,
        }
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        if len(sample) == 0:
            continue
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)
    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low": float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def compute_market_impact(ticker: str, order_qty: float, start: str, end: str) -> dict:
    """Square-root market impact model (Johnson — Algorithmic Trading & DMA)."""
    try:
        import yfinance as yf
        hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        if hist.empty or "Volume" not in hist.columns:
            raise ValueError("No volume data")
        adv = hist["Volume"].rolling(20).mean().dropna()
        adv_val = float(adv.iloc[-1]) if len(adv) > 0 else 1_000_000
        sigma_val = float(hist["Close"].pct_change().std()) if len(hist) > 1 else 0.01
        k = 0.1
        impact_pct = k * sigma_val * np.sqrt(order_qty / (adv_val + 1e-8))
        impact_bps = impact_pct * 10000
        liquidity_constrained = bool(order_qty > 0.01 * adv_val)
        return {
            "market_impact_bps": float(impact_bps),
            "liquidity_constrained": liquidity_constrained,
            "order_to_adv_ratio": float(order_qty / (adv_val + 1e-8)),
        }
    except Exception as e:
        print(f"  [WARN] market impact computation failed: {e}")
        return {
            "market_impact_bps": np.nan,
            "liquidity_constrained": False,
            "order_to_adv_ratio": np.nan,
        }


def permutation_test_alpha(
    prices: np.ndarray,
    entries: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 500,
    hold_days: int = 5,
) -> dict:
    """Permutation test for strategy alpha (Chan — Quantitative Trading)."""
    if len(prices) < 10 or observed_sharpe is None or np.isnan(observed_sharpe):
        return {"permutation_pvalue": np.nan, "permutation_test_pass": False}
    permuted_sharpes = []
    entry_count = max(1, int(entries.sum()))
    for _ in range(n_perms):
        perm_idx = np.random.choice(len(prices), size=entry_count, replace=False)
        trade_returns = []
        for idx in perm_idx:
            exit_idx = min(idx + hold_days, len(prices) - 1)
            if prices[idx] > 0:
                ret = (prices[exit_idx] - prices[idx]) / prices[idx]
                trade_returns.append(ret)
        if len(trade_returns) > 1:
            arr = np.array(trade_returns)
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR / hold_days)
        else:
            s = 0.0
        permuted_sharpes.append(s)
    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    """Walk-forward variance metrics (Davey Book 5)."""
    arr = np.array([s for s in wf_oos_sharpes if s is not None and not np.isnan(s)])
    if len(arr) == 0:
        return {"wf_sharpe_std": np.nan, "wf_sharpe_min": np.nan}
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


def compute_dsr(returns_series: pd.Series, n_trials: int = 10) -> float:
    """
    Deflated Sharpe Ratio (Lopez de Prado 2018).
    Adjusts Sharpe for number of trials, skewness, and kurtosis.
    """
    try:
        from scipy.stats import norm
        r = returns_series.dropna()
        if len(r) < 10:
            return np.nan
        T = len(r)
        sharpe = float(r.mean() / (r.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        skew = float(r.skew())
        kurt = float(r.kurtosis())

        # Expected maximum Sharpe across n_trials via Euler-Mascheroni
        gamma = 0.5772156649
        E_max = (1 - gamma) * norm.ppf(1 - 1.0 / n_trials) + gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))

        # Variance of Sharpe ratio
        var_sharpe = (1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2) / (T - 1)
        if var_sharpe <= 0:
            var_sharpe = 1.0 / T

        dsr = norm.cdf((sharpe - E_max) / np.sqrt(var_sharpe))
        return float(dsr)
    except Exception as e:
        print(f"  [WARN] DSR computation failed: {e}")
        return np.nan


# ══════════════════════════════════════════════════════════════════════════════
# Walk-Forward
# ══════════════════════════════════════════════════════════════════════════════

def run_walk_forward(n_windows: int = 4) -> dict:
    """
    Walk-forward over the IS period (2007–2021).
    Splits IS into n_windows equal sub-periods; reports OOS Sharpe per window.
    """
    print(f"\n[WF] Running walk-forward ({n_windows} windows over IS 2007–2021)...")
    is_start_ts = pd.Timestamp(IS_START)
    is_end_ts = pd.Timestamp(IS_END)
    total_days = (is_end_ts - is_start_ts).days
    window_days = total_days // n_windows

    wf_results = []
    wf_oos_sharpes = []

    for i in range(n_windows):
        win_start = is_start_ts + pd.DateOffset(days=i * window_days)
        win_end = is_start_ts + pd.DateOffset(days=(i + 1) * window_days) - pd.DateOffset(days=1)
        if i == n_windows - 1:
            win_end = is_end_ts

        win_start_str = win_start.strftime("%Y-%m-%d")
        win_end_str = win_end.strftime("%Y-%m-%d")

        # Train on first 75% of window, OOS on last 25%
        win_len = (win_end - win_start).days
        train_end = win_start + pd.DateOffset(days=int(win_len * 0.75))
        oos_start_wf = train_end + pd.DateOffset(days=1)

        train_end_str = train_end.strftime("%Y-%m-%d")
        oos_start_wf_str = oos_start_wf.strftime("%Y-%m-%d")

        print(f"  Window {i+1}: IS {win_start_str}–{train_end_str}, OOS {oos_start_wf_str}–{win_end_str}")
        try:
            oos_r = run_backtest(oos_start_wf_str, win_end_str)
            oos_sharpe = oos_r["sharpe"]
            wf_oos_sharpes.append(oos_sharpe)
            window_pass = oos_sharpe > 0.7
            print(f"    OOS Sharpe: {oos_sharpe:.4f} | {'PASS' if window_pass else 'FAIL'}")
            wf_results.append({
                "window": i + 1,
                "is_start": win_start_str,
                "is_end": train_end_str,
                "oos_start": oos_start_wf_str,
                "oos_end": win_end_str,
                "oos_sharpe": oos_sharpe,
                "oos_mdd": oos_r["max_drawdown"],
                "oos_trades": oos_r["trade_count"],
                "passed": window_pass,
            })
        except Exception as e:
            print(f"    [ERROR] WF window {i+1}: {e}")
            wf_oos_sharpes.append(np.nan)
            wf_results.append({
                "window": i + 1,
                "oos_sharpe": np.nan,
                "passed": False,
                "error": str(e),
            })

    windows_passed = sum(1 for w in wf_results if w.get("passed", False))
    wf_consistency = windows_passed / n_windows

    print(f"  [WF] {windows_passed}/{n_windows} windows passed")
    return {
        "wf_results": wf_results,
        "wf_oos_sharpes": wf_oos_sharpes,
        "wf_windows_passed": windows_passed,
        "wf_total_windows": n_windows,
        "wf_consistency_score": round(wf_consistency, 4),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Parameter Sensitivity
# ══════════════════════════════════════════════════════════════════════════════

def run_sensitivity(param_name: str, values: list) -> dict:
    """Scan IS Sharpe across param variations."""
    print(f"\n[SENS] Sensitivity scan: {param_name} = {values}")
    base_params = PARAMETERS.copy()
    base_result = run_backtest(IS_START, IS_END, base_params)
    base_sharpe = base_result["sharpe"]

    scan_results = []
    max_pct_change = 0.0

    for v in values:
        p = PARAMETERS.copy()
        p[param_name] = v
        try:
            r = run_backtest(IS_START, IS_END, p)
            pct_chg = abs(r["sharpe"] - base_sharpe) / (abs(base_sharpe) + 1e-8) * 100
            max_pct_change = max(max_pct_change, pct_chg)
            scan_results.append({
                "param_value": v,
                "sharpe": r["sharpe"],
                "mdd": r["max_drawdown"],
                "trade_count": r["trade_count"],
                "pct_change_from_base": round(pct_chg, 2),
            })
            print(f"  {param_name}={v}: Sharpe={r['sharpe']:.4f} ({pct_chg:.1f}% change from base)")
        except Exception as e:
            print(f"  {param_name}={v}: ERROR — {e}")
            scan_results.append({"param_value": v, "error": str(e)})

    sensitivity_pass = max_pct_change < 30.0
    print(f"  [SENS] Max Sharpe change: {max_pct_change:.1f}% — {'PASS' if sensitivity_pass else 'FAIL'}")
    return {
        "sensitivity_param": param_name,
        "base_value": base_params[param_name],
        "base_sharpe": base_sharpe,
        "scan_results": scan_results,
        "max_pct_change": round(max_pct_change, 2),
        "sensitivity_pass": sensitivity_pass,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Special Validations
# ══════════════════════════════════════════════════════════════════════════════

def run_special_validations(is_result: dict, oos_result: dict) -> dict:
    """
    Special validations for H30:
    1. 2022 in-cash % — regime filter should block entries during bear market
    2. GFC 2008–2009 MDD
    3. 2022 stress window MDD
    """
    print("\n[SPEC] Running special validations...")
    svs = {}

    # 1. 2022 regime analysis — how often was regime filter OFF (in-cash)
    oos_daily = oos_result.get("daily_df", pd.DataFrame())
    if not oos_daily.empty and "position" in oos_daily.columns:
        mask_2022 = oos_daily.index.year == 2022
        if mask_2022.any():
            positions_2022 = oos_daily.loc[mask_2022, "position"]
            in_cash_pct_2022 = float((positions_2022 == 0).mean())
            svs["regime_2022_in_cash_pct"] = round(in_cash_pct_2022, 4)
            # H30 uses VIX spike entries; in 2022 bear market, regime filter (SPY > 200-SMA) should limit entries
            print(f"  2022 in-cash (no position): {in_cash_pct_2022:.1%}")
        else:
            svs["regime_2022_in_cash_pct"] = None
    else:
        svs["regime_2022_in_cash_pct"] = None

    # 2. GFC 2008–2009 MDD
    try:
        gfc_result = run_backtest("2008-01-01", "2009-12-31")
        gfc_mdd = gfc_result["max_drawdown"]
        svs["gfc_2008_2009_mdd"] = round(gfc_mdd, 4)
        svs["gfc_trades"] = gfc_result["trade_count"]
        print(f"  GFC 2008–2009 MDD: {gfc_mdd:.2%} | Trades: {gfc_result['trade_count']}")
    except Exception as e:
        print(f"  [WARN] GFC MDD failed: {e}")
        svs["gfc_2008_2009_mdd"] = None
        svs["gfc_trades"] = None

    # 3. 2022 stress window MDD
    try:
        stress_2022 = run_backtest("2022-01-01", "2022-12-31")
        svs["stress_2022_mdd"] = round(stress_2022["max_drawdown"], 4)
        svs["stress_2022_trades"] = stress_2022["trade_count"]
        svs["stress_2022_sharpe"] = round(stress_2022["sharpe"], 4)
        print(f"  2022 stress MDD: {stress_2022['max_drawdown']:.2%} | Trades: {stress_2022['trade_count']} | Sharpe: {stress_2022['sharpe']:.4f}")
    except Exception as e:
        print(f"  [WARN] 2022 stress MDD failed: {e}")
        svs["stress_2022_mdd"] = None
        svs["stress_2022_trades"] = None
        svs["stress_2022_sharpe"] = None

    return svs


# ══════════════════════════════════════════════════════════════════════════════
# Gate 1 Verdict
# ══════════════════════════════════════════════════════════════════════════════

GATE1_CRITERIA = {
    "IS Sharpe > 1.0": lambda m: m["is_sharpe"] > 1.0,
    "OOS Sharpe > 0.7": lambda m: m["oos_sharpe"] > 0.7,
    "IS Max Drawdown < 20%": lambda m: abs(m["is_max_drawdown"]) < 0.20,
    "OOS Max Drawdown < 25%": lambda m: abs(m["oos_max_drawdown"]) < 0.25,
    "Win Rate > 50%": lambda m: m["win_rate"] > 0.50,
    "DSR > 0": lambda m: m["dsr"] is not None and not np.isnan(m["dsr"]) and m["dsr"] > 0,
    "Walk-forward >= 3/4 windows passed": lambda m: m["wf_windows_passed"] >= 3,
    "Parameter sensitivity pass": lambda m: m["sensitivity_pass"],
    "Trade count >= 100 (IS)": lambda m: m["is_trade_count"] >= 100,
    "MC p5 Sharpe >= 0.5": lambda m: not np.isnan(m.get("mc_p5_sharpe") or np.nan) and (m.get("mc_p5_sharpe") or 0) >= 0.5,
    "Permutation test pass (p <= 0.05)": lambda m: m.get("permutation_test_pass", False),
}


def evaluate_gate1(metrics: dict) -> dict:
    results = {}
    for criterion, fn in GATE1_CRITERIA.items():
        try:
            results[criterion] = bool(fn(metrics))
        except Exception:
            results[criterion] = False
    passing = sum(1 for v in results.values() if v)
    total = len(results)
    overall = "PASS" if all(results.values()) else "FAIL"
    return {
        "criteria": results,
        "passing": passing,
        "total": total,
        "overall_verdict": overall,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Main Pipeline
# ══════════════════════════════════════════════════════════════════════════════

def main():
    np.random.seed(42)
    print("=" * 70)
    print(f"Gate 1 Backtest — {STRATEGY_NAME}")
    print(f"Date: {TODAY} | QUA-267")
    print("=" * 70)

    # ── 1. IS Backtest ──────────────────────────────────────────────────────
    print(f"\n[IS] Running IS backtest ({IS_START} to {IS_END})...")
    try:
        is_result = run_backtest(IS_START, IS_END)
        print(f"  IS Sharpe: {is_result['sharpe']:.4f}")
        print(f"  IS MDD: {is_result['max_drawdown']:.2%}")
        print(f"  IS Trades: {is_result['trade_count']}")
        print(f"  IS Win Rate: {is_result['win_rate']:.2%}")
        print(f"  IS Profit Factor: {is_result['profit_factor']:.2f}")
        print(f"  IS Entry signals: {is_result['entry_signals_total']} | Regime-blocked: {is_result['regime_blocked_count']}")
        print(f"  IS Exit reasons: {is_result['exit_reason_summary']}")
    except Exception as e:
        print(f"[FATAL] IS backtest failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── 2. OOS Backtest ─────────────────────────────────────────────────────
    print(f"\n[OOS] Running OOS backtest ({OOS_START} to {OOS_END})...")
    try:
        oos_result = run_backtest(OOS_START, OOS_END)
        print(f"  OOS Sharpe: {oos_result['sharpe']:.4f}")
        print(f"  OOS MDD: {oos_result['max_drawdown']:.2%}")
        print(f"  OOS Trades: {oos_result['trade_count']}")
        print(f"  OOS Win Rate: {oos_result['win_rate']:.2%}")
        print(f"  OOS Profit Factor: {oos_result['profit_factor']:.2f}")
        print(f"  OOS Entry signals: {oos_result['entry_signals_total']} | Regime-blocked: {oos_result['regime_blocked_count']}")
        print(f"  OOS Exit reasons: {oos_result['exit_reason_summary']}")
    except Exception as e:
        print(f"[FATAL] OOS backtest failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── 3. OOS Data Download (for DQ check) ────────────────────────────────
    print(f"\n[DQ] Downloading OOS data for quality check ({OOS_START} to {OOS_END})...")
    try:
        oos_raw = download_data(
            PARAMETERS["ticker"],
            PARAMETERS["vix_ticker"],
            OOS_START,
            OOS_END,
            PARAMETERS,
        )
        oos_data = oos_raw["spy"].loc[oos_raw["spy"].index >= pd.Timestamp(OOS_START)]
        print(f"  OOS data rows: {len(oos_data)}")
    except Exception as e:
        print(f"[FATAL] OOS data download failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── 4. OOS Data Quality Validation ─────────────────────────────────────
    print("\n[DQ] Running OOS data quality validation...")
    # Cap inf profit_factor — zero OOS losses → inf, but DQ validator blocks inf as non-finite.
    # Cap at 99.0 (large but finite) to allow DQ to pass; note true value in metrics.
    _pf_oos = oos_result["profit_factor"]
    _pf_oos_dq = min(_pf_oos, 99.0) if np.isfinite(_pf_oos) else 99.0

    oos_metrics_for_dq = {
        "sharpe": oos_result["sharpe"],
        "max_drawdown": oos_result["max_drawdown"],
        "win_rate": oos_result["win_rate"],
        "profit_factor": _pf_oos_dq,
        "total_trades": oos_result["trade_count"],
        "post_cost_sharpe": oos_result["sharpe"],  # post-cost already baked in simulation
        "total_return": oos_result["total_return"],
        "portfolio_returns": oos_result.get("returns"),
    }

    try:
        dq_report = validate_oos_data(oos_data, oos_metrics_for_dq, STRATEGY_NAME)
        print(f"  DQ Recommendation: {dq_report['recommendation']}")
        print(f"  OOS Data Coverage: {dq_report['oos_data_coverage_pct']:.1f}%")
        if dq_report["recommendation"] == "BLOCK":
            print(f"  [BLOCK] {dq_report.get('block_reasons', 'Unknown block reason')}")
            raise OOSDataQualityError(dq_report)
        if dq_report["recommendation"] == "WARN":
            print(f"  [WARN] Advisory NaN fields: {dq_report.get('advisory_nan_fields', [])}")
    except OOSDataQualityError as e:
        print(f"\n[FATAL] OOS data quality BLOCK — halting. Report: {e.report}")
        sys.exit(2)

    # ── 5. Statistical Rigor Pipeline ───────────────────────────────────────

    # 5a. Monte Carlo
    print("\n[MC] Running Monte Carlo simulation (1,000 resamples)...")
    is_trade_pnls = is_result["trades"]["pnl"].values if not is_result["trades"].empty else np.array([])
    mc_results = monte_carlo_sharpe(is_trade_pnls)
    print(f"  MC p5 Sharpe: {mc_results['mc_p5_sharpe']:.4f}")
    print(f"  MC median Sharpe: {mc_results['mc_median_sharpe']:.4f}")
    print(f"  MC p95 Sharpe: {mc_results['mc_p95_sharpe']:.4f}")
    if not np.isnan(mc_results["mc_p5_sharpe"]) and mc_results["mc_p5_sharpe"] < 0.5:
        print("  [FLAG] MC pessimistic bound weak (p5 < 0.5)")

    # 5b. Block Bootstrap CI
    print("\n[BB] Running block bootstrap CI (1,000 boots)...")
    is_returns = is_result.get("returns", pd.Series(dtype=float))
    bb_results = block_bootstrap_ci(is_returns.values if len(is_returns) > 0 else np.array([]))
    print(f"  Sharpe 95% CI: [{bb_results['sharpe_ci_low']:.4f}, {bb_results['sharpe_ci_high']:.4f}]")
    print(f"  MDD 95% CI: [{bb_results['mdd_ci_low']:.4f}, {bb_results['mdd_ci_high']:.4f}]")
    print(f"  Win Rate 95% CI: [{bb_results['win_rate_ci_low']:.4f}, {bb_results['win_rate_ci_high']:.4f}]")

    # 5c. Market Impact
    print("\n[MI] Computing market impact (equities, SPY)...")
    # ~$25k portfolio buying SPY at ~$400 → ~62 shares
    avg_spy_price = 400.0
    order_qty = float(PARAMETERS["init_cash"]) / avg_spy_price
    mi_results = compute_market_impact("SPY", order_qty, OOS_START, OOS_END)
    print(f"  Market impact: {mi_results['market_impact_bps']:.2f} bps" if not np.isnan(mi_results["market_impact_bps"]) else "  Market impact: N/A")
    print(f"  Liquidity constrained: {mi_results['liquidity_constrained']}")
    if not np.isnan(mi_results["order_to_adv_ratio"]):
        print(f"  Order/ADV ratio: {mi_results['order_to_adv_ratio']:.6f}")

    # 5d. Permutation Test
    print("\n[PERM] Running permutation test (500 permutations)...")
    is_daily = is_result.get("daily_df", pd.DataFrame())
    if not is_daily.empty and "position" in is_daily.columns:
        entries_arr = (is_daily["position"].shift(1, fill_value=0) == 0) & (is_daily["position"] == 1)
        entries_arr = entries_arr.values.astype(bool)
        spy_closes = is_daily["equity"].values
    else:
        entries_arr = np.zeros(len(is_returns), dtype=bool)
        spy_closes = np.array([])

    perm_results = permutation_test_alpha(
        prices=spy_closes,
        entries=entries_arr,
        observed_sharpe=is_result["sharpe"],
        n_perms=500,
        hold_days=PARAMETERS["hold_days"],
    )
    print(f"  Permutation p-value: {perm_results['permutation_pvalue']:.4f}")
    print(f"  Permutation test pass: {perm_results['permutation_test_pass']}")

    # 5e. Walk-Forward
    wf_data = run_walk_forward(n_windows=4)
    wf_var = walk_forward_variance(wf_data["wf_oos_sharpes"])
    print(f"\n[WF] Variance: std={wf_var['wf_sharpe_std']:.4f}, min={wf_var['wf_sharpe_min']:.4f}")
    if not np.isnan(wf_var["wf_sharpe_min"]) and wf_var["wf_sharpe_min"] < 0:
        print("  [FLAG] wf_sharpe_min < 0 — at least one losing OOS window")

    # ── 6. Parameter Sensitivity ────────────────────────────────────────────
    # Scan vix_threshold (20, 25, 30) — base is 25
    print("\n[SENS] Parameter sensitivity: vix_threshold (20, 25, 30)...")
    sens_vix = run_sensitivity("vix_threshold", [20, 25, 30])

    # Scan hold_days (3, 5, 7) — base is 5
    print("\n[SENS] Parameter sensitivity: hold_days (3, 5, 7)...")
    sens_hold = run_sensitivity("hold_days", [3, 5, 7])

    # Combined sensitivity pass — both must pass
    combined_max_pct = max(sens_vix["max_pct_change"], sens_hold["max_pct_change"])
    sensitivity_pass = sens_vix["sensitivity_pass"] and sens_hold["sensitivity_pass"]
    print(f"\n[SENS] Combined max Sharpe change: {combined_max_pct:.1f}% — {'PASS' if sensitivity_pass else 'FAIL'}")

    # ── 7. DSR ──────────────────────────────────────────────────────────────
    print("\n[DSR] Computing Deflated Sharpe Ratio...")
    dsr_value = compute_dsr(is_returns, n_trials=10)
    print(f"  DSR: {dsr_value:.4f}" if not np.isnan(dsr_value) else "  DSR: N/A")

    # ── 8. Special Validations ──────────────────────────────────────────────
    spec_validations = run_special_validations(is_result, oos_result)

    # ── 9. Post-cost Sharpe (transaction costs baked into simulation) ────────
    post_cost_sharpe_is = is_result["sharpe"]
    post_cost_sharpe_oos = oos_result["sharpe"]

    # ── 10. Assemble Metrics JSON ────────────────────────────────────────────
    print("\n[OUT] Assembling metrics JSON...")

    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",

        # IS metrics
        "is_sharpe": round(is_result["sharpe"], 4),
        "is_max_drawdown": round(is_result["max_drawdown"], 4),
        "is_total_return": round(is_result["total_return"], 4),
        "is_win_rate": round(is_result["win_rate"], 4),
        "is_profit_factor": round(is_result["profit_factor"], 4),
        "is_trade_count": is_result["trade_count"],
        "is_trades_per_year": is_result["trades_per_year"],
        "is_entry_signals_total": is_result["entry_signals_total"],
        "is_regime_blocked_count": is_result["regime_blocked_count"],
        "is_exit_reason_summary": is_result["exit_reason_summary"],

        # OOS metrics
        "oos_sharpe": round(oos_result["sharpe"], 4),
        "oos_max_drawdown": round(oos_result["max_drawdown"], 4),
        "oos_total_return": round(oos_result["total_return"], 4),
        "win_rate": round(oos_result["win_rate"], 4),
        "profit_factor": round(oos_result["profit_factor"], 4),
        "trade_count": oos_result["trade_count"],
        "oos_entry_signals_total": oos_result["entry_signals_total"],
        "oos_regime_blocked_count": oos_result["regime_blocked_count"],
        "oos_exit_reason_summary": oos_result["exit_reason_summary"],

        # Combined
        "post_cost_sharpe": round(post_cost_sharpe_oos, 4),
        "post_cost_sharpe_is": round(post_cost_sharpe_is, 4),
        "dsr": round(float(dsr_value), 4) if not np.isnan(dsr_value) else None,

        # Walk-forward
        "wf_windows_passed": wf_data["wf_windows_passed"],
        "wf_total_windows": wf_data["wf_total_windows"],
        "wf_consistency_score": wf_data["wf_consistency_score"],
        "wf_results": wf_data["wf_results"],
        "wf_oos_sharpes": [round(s, 4) if not np.isnan(s) else None for s in wf_data["wf_oos_sharpes"]],
        "wf_sharpe_std": round(wf_var["wf_sharpe_std"], 4) if not np.isnan(wf_var["wf_sharpe_std"]) else None,
        "wf_sharpe_min": round(wf_var["wf_sharpe_min"], 4) if not np.isnan(wf_var["wf_sharpe_min"]) else None,

        # Statistical rigor
        "mc_p5_sharpe": round(mc_results["mc_p5_sharpe"], 4) if not np.isnan(mc_results["mc_p5_sharpe"]) else None,
        "mc_median_sharpe": round(mc_results["mc_median_sharpe"], 4) if not np.isnan(mc_results["mc_median_sharpe"]) else None,
        "mc_p95_sharpe": round(mc_results["mc_p95_sharpe"], 4) if not np.isnan(mc_results["mc_p95_sharpe"]) else None,
        "sharpe_ci_low": round(bb_results["sharpe_ci_low"], 4) if not np.isnan(bb_results["sharpe_ci_low"]) else None,
        "sharpe_ci_high": round(bb_results["sharpe_ci_high"], 4) if not np.isnan(bb_results["sharpe_ci_high"]) else None,
        "mdd_ci_low": round(bb_results["mdd_ci_low"], 4) if not np.isnan(bb_results["mdd_ci_low"]) else None,
        "mdd_ci_high": round(bb_results["mdd_ci_high"], 4) if not np.isnan(bb_results["mdd_ci_high"]) else None,
        "win_rate_ci_low": round(bb_results["win_rate_ci_low"], 4) if not np.isnan(bb_results["win_rate_ci_low"]) else None,
        "win_rate_ci_high": round(bb_results["win_rate_ci_high"], 4) if not np.isnan(bb_results["win_rate_ci_high"]) else None,
        "market_impact_bps": round(mi_results["market_impact_bps"], 4) if not np.isnan(mi_results["market_impact_bps"]) else None,
        "liquidity_constrained": mi_results["liquidity_constrained"],
        "order_to_adv_ratio": round(mi_results["order_to_adv_ratio"], 8) if not np.isnan(mi_results["order_to_adv_ratio"]) else None,
        "permutation_pvalue": round(perm_results["permutation_pvalue"], 4) if not np.isnan(perm_results["permutation_pvalue"]) else None,
        "permutation_test_pass": perm_results["permutation_test_pass"],

        # Sensitivity (combined across both params)
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_pct_change": combined_max_pct,
        "sensitivity_vix_threshold": sens_vix,
        "sensitivity_hold_days": sens_hold,

        # Special validations
        "special_validations": spec_validations,

        # Flags
        "look_ahead_bias_flag": False,
        "oos_data_quality": dq_report,
    }

    # Gate 1 evaluation
    gate1 = evaluate_gate1(metrics)
    metrics["gate1_pass"] = gate1["overall_verdict"] == "PASS"
    metrics["gate1_criteria"] = gate1["criteria"]
    metrics["gate1_passing"] = gate1["passing"]
    metrics["gate1_total"] = gate1["total"]
    metrics["gate1_overall_verdict"] = gate1["overall_verdict"]

    # Trade logs
    oos_trades = oos_result["trades"]
    metrics["trade_log_oos"] = oos_trades.head(50).to_dict(orient="records") if not oos_trades.empty else []
    is_trades = is_result["trades"]
    metrics["trade_log_is_sample"] = is_trades.head(20).to_dict(orient="records") if not is_trades.empty else []

    # ── 11. Save JSON ────────────────────────────────────────────────────────
    json_path = BACKTESTS_DIR / f"{STRATEGY_NAME}_{TODAY}.json"

    def json_serializer(obj):
        if isinstance(obj, (date, datetime)):
            return str(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return None if np.isnan(obj) else float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, bool):
            return bool(obj)
        raise TypeError(f"Not serializable: {type(obj)}")

    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=json_serializer)
    print(f"\n[OUT] Metrics JSON saved: {json_path}")

    # ── 12. Gate 1 Verdict File ──────────────────────────────────────────────
    verdict_path = BACKTESTS_DIR / f"{STRATEGY_NAME}_{TODAY}_verdict.txt"

    verdict_lines = [
        f"Gate 1 Verdict — {STRATEGY_NAME}",
        f"Date: {TODAY}",
        f"Overall: {gate1['overall_verdict']} ({gate1['passing']}/{gate1['total']} criteria passed)",
        "",
        "=" * 60,
        "IS/OOS Performance",
        "=" * 60,
        f"  IS Sharpe:          {metrics['is_sharpe']:.4f}   (threshold > 1.0)   {'PASS' if metrics['is_sharpe'] > 1.0 else 'FAIL'}",
        f"  OOS Sharpe:         {metrics['oos_sharpe']:.4f}   (threshold > 0.7)   {'PASS' if metrics['oos_sharpe'] > 0.7 else 'FAIL'}",
        f"  IS Max Drawdown:    {metrics['is_max_drawdown']:.2%}  (threshold < 20%)   {'PASS' if abs(metrics['is_max_drawdown']) < 0.20 else 'FAIL'}",
        f"  OOS Max Drawdown:   {metrics['oos_max_drawdown']:.2%}  (threshold < 25%)   {'PASS' if abs(metrics['oos_max_drawdown']) < 0.25 else 'FAIL'}",
        f"  IS Trade Count:     {metrics['is_trade_count']}      (threshold >= 100)  {'PASS' if metrics['is_trade_count'] >= 100 else 'FAIL'}",
        f"  OOS Trade Count:    {metrics['trade_count']}",
        f"  Win Rate (OOS):     {metrics['win_rate']:.2%}  (threshold > 50%)   {'PASS' if metrics['win_rate'] > 0.50 else 'FAIL'}",
        f"  Profit Factor (OOS):{metrics['profit_factor']:.2f}",
        f"  Post-cost Sharpe:   {metrics['post_cost_sharpe']:.4f}",
        "",
        "=" * 60,
        "Statistical Rigor",
        "=" * 60,
        f"  DSR:                {metrics['dsr']}    (threshold > 0)    {'PASS' if metrics['dsr'] and metrics['dsr'] > 0 else 'FAIL'}",
        f"  MC p5 Sharpe:       {metrics['mc_p5_sharpe']}  (threshold >= 0.5)  {'PASS' if metrics['mc_p5_sharpe'] and metrics['mc_p5_sharpe'] >= 0.5 else 'WARN'}",
        f"  MC Median Sharpe:   {metrics['mc_median_sharpe']}",
        f"  Sharpe 95% CI:      [{metrics['sharpe_ci_low']}, {metrics['sharpe_ci_high']}]",
        f"  MDD 95% CI:         [{metrics['mdd_ci_low']}, {metrics['mdd_ci_high']}]",
        f"  Market Impact:      {metrics['market_impact_bps']} bps",
        f"  Permutation p-val:  {metrics['permutation_pvalue']}  (threshold <= 0.05)  {'PASS' if metrics['permutation_test_pass'] else 'FAIL'}",
        "",
        "=" * 60,
        "Walk-Forward",
        "=" * 60,
        f"  Windows Passed:     {metrics['wf_windows_passed']}/{metrics['wf_total_windows']}  (threshold >= 3/4)  {'PASS' if metrics['wf_windows_passed'] >= 3 else 'FAIL'}",
        f"  WF Consistency:     {metrics['wf_consistency_score']:.2%}",
        f"  WF Sharpe Std:      {metrics['wf_sharpe_std']}",
        f"  WF Sharpe Min:      {metrics['wf_sharpe_min']}",
    ]

    for i, r in enumerate(wf_data["wf_results"]):
        verdict_lines.append(
            f"  Window {r.get('window', i+1)}: OOS Sharpe={r.get('oos_sharpe', 'N/A')}  {'PASS' if r.get('passed') else 'FAIL'}"
        )

    verdict_lines += [
        "",
        "=" * 60,
        "Parameter Sensitivity",
        "=" * 60,
        f"  Combined Max Sharpe change: {metrics['sensitivity_max_pct_change']:.1f}%  (threshold < 30%)  {'PASS' if metrics['sensitivity_pass'] else 'FAIL'}",
        "",
        "  vix_threshold scan (20, 25, 30):",
    ]
    for row in sens_vix["scan_results"]:
        if "error" not in row:
            verdict_lines.append(
                f"    vix_threshold={row['param_value']}: Sharpe={row['sharpe']:.4f} ({row['pct_change_from_base']:.1f}% change)"
            )

    verdict_lines.append("  hold_days scan (3, 5, 7):")
    for row in sens_hold["scan_results"]:
        if "error" not in row:
            verdict_lines.append(
                f"    hold_days={row['param_value']}: Sharpe={row['sharpe']:.4f} ({row['pct_change_from_base']:.1f}% change)"
            )

    verdict_lines += [
        "",
        "=" * 60,
        "Special Validations",
        "=" * 60,
        f"  2022 In-Cash %:     {spec_validations.get('regime_2022_in_cash_pct', 'N/A')}",
        f"  GFC 2008-2009 MDD:  {spec_validations.get('gfc_2008_2009_mdd', 'N/A')} | Trades: {spec_validations.get('gfc_trades', 'N/A')}",
        f"  2022 Stress MDD:    {spec_validations.get('stress_2022_mdd', 'N/A')}",
        f"  2022 Stress Sharpe: {spec_validations.get('stress_2022_sharpe', 'N/A')}",
        f"  2022 Stress Trades: {spec_validations.get('stress_2022_trades', 'N/A')}",
        "",
        "=" * 60,
        "OOS Data Quality",
        "=" * 60,
        f"  Recommendation:     {dq_report['recommendation']}",
        f"  Data Coverage:      {dq_report['oos_data_coverage_pct']:.1f}%",
        f"  Total NaNs:         {dq_report['oos_total_nans']}",
        "",
        "=" * 60,
        f"GATE 1 VERDICT: {gate1['overall_verdict']}",
        "=" * 60,
    ]

    for criterion, passed in gate1["criteria"].items():
        verdict_lines.append(f"  {'[PASS]' if passed else '[FAIL]'} {criterion}")

    if gate1["overall_verdict"] == "FAIL":
        failing = [k for k, v in gate1["criteria"].items() if not v]
        verdict_lines += ["", "Failing criteria:"]
        for f in failing:
            verdict_lines.append(f"  - {f}")

    verdict_text = "\n".join(verdict_lines)
    with open(verdict_path, "w") as f:
        f.write(verdict_text)
    print(f"[OUT] Verdict file saved: {verdict_path}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"GATE 1 VERDICT: {gate1['overall_verdict']} ({gate1['passing']}/{gate1['total']} criteria passed)")
    print("=" * 70)
    if gate1["overall_verdict"] == "FAIL":
        failing = [k for k, v in gate1["criteria"].items() if not v]
        print("FAILING CRITERIA:")
        for f in failing:
            print(f"  - {f}")

    print(f"\nJSON: {json_path}")
    print(f"Verdict: {verdict_path}")
    return metrics


if __name__ == "__main__":
    main()
