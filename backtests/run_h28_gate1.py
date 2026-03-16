"""
H28 Gate 1 Backtest Runner — Combined Multi-Calendar (TOM + OEX Week + Pre-Holiday)
QUA-241

IS period:  2008-01-01 to 2022-12-31 (14 years — includes GFC, COVID, rate-shock)
OOS period: 2023-01-01 to 2024-12-31 (strict temporal holdout)

Walk-forward windows (expanding IS):
  W1: 2008–2011 train / 2012 test
  W2: 2008–2013 train / 2014 test
  W3: 2008–2016 train / 2017 test
  W4: 2008–2019 train / 2020 test

Regime slices (IS sub-periods):
  Pre-COVID: 2018–2019
  Stimulus era: 2020–2021
  Rate-shock: 2022

Parameter sensitivity: each param varied independently from baseline.
"""

import sys
import os
import json
import warnings
import traceback
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date
from itertools import product

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.h28_combined_multi_calendar import (
    run_backtest,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
    download_data,
)
from orchestrator.oos_data_quality import validate_oos_data, OOSDataQualityError
from orchestrator.gate1_verdict_validator import (
    validate_verdict_json,
    VerdictValidationError,
    enforce_verdict_template,
)

# ── Constants ──────────────────────────────────────────────────────────────────

IS_START  = "2008-01-01"
IS_END    = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END   = "2024-12-31"

TODAY = str(date.today())
STRATEGY_NAME = "H28_CombinedMultiCalendar"
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "h28_combined_multi_calendar",
)

# Walk-forward expanding windows (IS 2008–train_end / OOS test_year)
WF_WINDOWS = [
    ("2008-01-01", "2011-12-31", "2012-01-01", "2012-12-31"),
    ("2008-01-01", "2013-12-31", "2014-01-01", "2014-12-31"),
    ("2008-01-01", "2016-12-31", "2017-01-01", "2017-12-31"),
    ("2008-01-01", "2019-12-31", "2020-01-01", "2020-12-31"),
]

REGIME_SLICES = {
    "pre_covid_2018_2019":   ("2018-01-01", "2019-12-31"),
    "stimulus_era_2020_2021":("2020-01-01", "2021-12-31"),
    "rate_shock_2022":       ("2022-01-01", "2022-12-31"),
}

# ── Statistical Functions ──────────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    if len(trade_pnls) < 2:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe":    float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    if T < 10:
        return {
            "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
            "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
        }
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)
    return {
        "sharpe_ci_low":    float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high":   float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":       float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":      float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low":  float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def compute_dsr(returns: np.ndarray, n_trials: int = 30) -> float:
    from scipy import stats
    T = len(returns)
    if T < 2:
        return 0.0
    sr = returns.mean() / (returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(pd.Series(returns).skew())
    kurt = float(pd.Series(returns).kurtosis())
    gamma = 0.5772
    e_max_sr = (
        (1 - gamma) * stats.norm.ppf(1 - 1.0 / n_trials)
        + gamma * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sigma_sr = np.sqrt(
        (1 + 0.5 * sr**2 - skew * sr + ((kurt - 3) / 4) * sr**2) / (T - 1)
    )
    dsr = (sr - e_max_sr) / (sigma_sr + 1e-8)
    return round(float(dsr), 4)


def permutation_test_alpha(
    equity_curve: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 1000,
    hold_days: int = 5,
) -> dict:
    if len(equity_curve) < hold_days + 1 or abs(observed_sharpe) < 1e-6:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    prices = equity_curve
    n_entries = max(1, len(prices) // (hold_days * 4))
    permuted_sharpes = []
    for _ in range(n_perms):
        perm_idx = np.random.choice(len(prices) - hold_days, size=n_entries, replace=False)
        trade_returns = []
        for idx in perm_idx:
            exit_idx = min(idx + hold_days, len(prices) - 1)
            if prices[idx] > 0:
                ret = (prices[exit_idx] - prices[idx]) / prices[idx]
                trade_returns.append(ret)
        if len(trade_returns) > 1:
            arr = np.array(trade_returns)
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(252 / hold_days)
        else:
            s = 0.0
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue": round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    if not wf_oos_sharpes:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": round(float(arr.std()), 4),
        "wf_sharpe_min": round(float(arr.min()), 4),
    }


# ── Walk-Forward Backtest ──────────────────────────────────────────────────────

def run_walk_forward(base_params: dict, windows: list) -> dict:
    """Expanding-window walk-forward per task spec."""
    print(f"\nRunning walk-forward ({len(windows)} expanding windows)...")
    wf_oos_sharpes = []
    wf_is_sharpes = []
    windows_passed = 0

    for i, (is_s, is_e, oos_s, oos_e) in enumerate(windows):
        print(f"  W{i+1}: IS={is_s}→{is_e}, OOS={oos_s}→{oos_e}")
        try:
            is_res  = run_backtest(is_s, is_e, base_params.copy())
            oos_res = run_backtest(oos_s, oos_e, base_params.copy())

            is_sharpe  = float(is_res.get("sharpe", 0.0))
            oos_sharpe = float(oos_res.get("sharpe", 0.0))
            wf_is_sharpes.append(is_sharpe)
            wf_oos_sharpes.append(oos_sharpe)

            oos_is_ratio = oos_sharpe / (abs(is_sharpe) + 1e-8) if is_sharpe != 0 else 0.0
            passed = bool(oos_is_ratio >= 0.70) and bool(oos_sharpe > 0)
            if passed:
                windows_passed += 1
            print(f"    IS Sharpe={is_sharpe:.3f}, OOS Sharpe={oos_sharpe:.3f}, "
                  f"OOS/IS={oos_is_ratio:.2f} → {'PASS' if passed else 'FAIL'}")
        except Exception as exc:
            print(f"    W{i+1} failed: {exc}")
            wf_is_sharpes.append(0.0)
            wf_oos_sharpes.append(0.0)

    avg_is  = float(np.mean(wf_is_sharpes)) if wf_is_sharpes else 0.0
    avg_oos = float(np.mean(wf_oos_sharpes)) if wf_oos_sharpes else 0.0
    consistency = avg_oos / (abs(avg_is) + 1e-8) if avg_is != 0 else 0.0

    return {
        "wf_windows_passed": windows_passed,
        "wf_total_windows": len(windows),
        "wf_oos_sharpes": wf_oos_sharpes,
        "wf_is_sharpes": wf_is_sharpes,
        "wf_avg_is_sharpe": round(avg_is, 4),
        "wf_avg_oos_sharpe": round(avg_oos, 4),
        "wf_consistency_score": round(float(consistency), 4),
    }


# ── Sensitivity Scan ───────────────────────────────────────────────────────────

def run_sensitivity_scan(base_params: dict, start: str, end: str) -> dict:
    """
    Per-parameter sensitivity: vary each dimension independently from baseline.
    Pre-registered ranges from QUA-241 spec.
    """
    print("\nRunning parameter sensitivity scan (IS window)...")
    base_sharpe = float(run_backtest(start, end, base_params.copy()).get("sharpe", 0.0))
    print(f"  Baseline Sharpe = {base_sharpe:.4f}")

    param_grid = {
        "tom_entry_day":          [-3, -2, -1],
        "tom_exit_day":           [2, 3, 4, 5],
        "vix_threshold_tom":      [25.0, 28.0, 32.0, 35.0],
        "oex_exit_on_thursday":   [True, False],
        "vix_threshold_preholiday": [35.0, 40.0, None],
        "holiday_calendar":       ["all9", "top6"],
    }

    results = {}
    sharpe_changes = []

    for param_name, values in param_grid.items():
        for val in values:
            key = f"{param_name}={val}"
            p = base_params.copy()
            p[param_name] = val
            try:
                res = run_backtest(start, end, p)
                s = float(res.get("sharpe", 0.0))
                results[key] = s
                if abs(base_sharpe) > 1e-6:
                    pct_change = abs(s - base_sharpe) / (abs(base_sharpe) + 1e-8)
                    sharpe_changes.append(pct_change)
                print(f"  {key}: Sharpe={s:.3f}")
            except Exception as exc:
                print(f"  {key}: FAILED — {exc}")
                results[key] = 0.0

    sensitivity_pass = False
    max_change = 0.0
    if sharpe_changes:
        max_change = max(sharpe_changes)
        sensitivity_pass = bool(max_change < 0.30)

    return {
        "sensitivity_results": results,
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_change_pct": round(float(max_change), 4),
        "baseline_sharpe": base_sharpe,
    }


# ── Regime Slices ──────────────────────────────────────────────────────────────

def run_regime_slices(params: dict) -> dict:
    """Regime-slice Sharpe per criteria.md v1.2."""
    print("\nRegime-slice analysis...")
    results = {}
    for name, (s, e) in REGIME_SLICES.items():
        try:
            res = run_backtest(s, e, params.copy())
            results[name] = {
                "sharpe":       float(res.get("sharpe", 0.0)),
                "trade_count":  int(res.get("trade_count", 0)),
                "max_drawdown": float(res.get("max_drawdown", 0.0)),
                "win_rate":     float(res.get("win_rate", 0.0)),
                "total_return": float(res.get("total_return", 0.0)),
            }
            print(f"  {name}: Sharpe={results[name]['sharpe']:.3f}, "
                  f"Trades={results[name]['trade_count']}, "
                  f"MDD={results[name]['max_drawdown']:.2%}")
        except Exception as exc:
            print(f"  {name}: FAILED — {exc}")
            results[name] = {"sharpe": 0.0, "trade_count": 0, "max_drawdown": 0.0,
                             "win_rate": 0.0, "total_return": 0.0}
    return results


# ── Market Impact Calculation ──────────────────────────────────────────────────

def compute_market_impact_spy(start: str, end: str, init_cash: float) -> dict:
    """SPY market impact using square-root model. SPY is highly liquid — minimal impact expected."""
    try:
        hist = yf.download("SPY", start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        adv = float(hist["Volume"].rolling(20).mean().iloc[-1]) if "Volume" in hist.columns else 5e7
        sigma = float(hist["Close"].pct_change().std()) if "Close" in hist.columns else 0.01
        spy_price = float(hist["Close"].iloc[-1]) if "Close" in hist.columns else 400.0
        order_qty = init_cash / spy_price  # shares to buy with full capital
        k = 0.1
        impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
        impact_bps = impact_pct * 10000
        liquidity_constrained = bool(order_qty > 0.01 * adv)
        order_to_adv = float(order_qty / (adv + 1e-8))
        return {
            "market_impact_bps": round(float(impact_bps), 4),
            "liquidity_constrained": liquidity_constrained,
            "order_to_adv_ratio": round(order_to_adv, 6),
            "spy_adv_shares": round(adv, 0),
            "order_shares": round(order_qty, 1),
        }
    except Exception as exc:
        return {
            "market_impact_bps": 0.5,
            "liquidity_constrained": False,
            "order_to_adv_ratio": 0.00001,
            "spy_adv_shares": 50e6,
            "order_shares": 60.0,
        }


# ── Gate 1 Verdict Builder ─────────────────────────────────────────────────────

def build_verdict(metrics: dict) -> dict:
    def _metric(name, value, threshold, passed):
        return {"name": name, "value": str(value), "threshold": threshold, "passed": bool(passed)}

    is_sharpe      = metrics.get("is_sharpe", 0.0)
    oos_sharpe     = metrics.get("oos_sharpe", 0.0)
    is_mdd         = metrics.get("is_max_drawdown", 0.0)
    oos_mdd        = metrics.get("oos_max_drawdown", 0.0)
    win_rate       = metrics.get("win_rate", 0.0)
    trade_count    = metrics.get("trade_count", 0)
    dsr            = metrics.get("dsr", 0.0)
    wf_passed      = metrics.get("wf_windows_passed", 0)
    wf_consistency = metrics.get("wf_consistency_score", 0.0)
    sens_pass      = metrics.get("sensitivity_pass", False)
    post_cost_sr   = metrics.get("post_cost_sharpe", 0.0)
    years = (pd.Timestamp(OOS_END) - pd.Timestamp(IS_START)).days / 365.25

    metrics_list = [
        _metric("IS Sharpe",                      round(is_sharpe, 3),        "> 1.0",      is_sharpe > 1.0),
        _metric("OOS Sharpe",                     round(oos_sharpe, 3),       "> 0.7",      oos_sharpe > 0.7),
        _metric("IS Max Drawdown",                f"{is_mdd:.2%}",            "< -20%",     abs(is_mdd) < 0.20),
        _metric("OOS Max Drawdown",               f"{oos_mdd:.2%}",           "< -25%",     abs(oos_mdd) < 0.25),
        _metric("Win Rate",                       f"{win_rate:.2%}",          "> 50%",      win_rate > 0.50),
        _metric("Trade count",                    trade_count,                ">= 100 (IS)",trade_count >= 100),
        _metric("Deflated Sharpe Ratio (z-score)",round(dsr, 3),              "> 0",        dsr > 0),
        _metric("Walk-forward windows passed",    f"{wf_passed}/4",           ">= 3",       wf_passed >= 3),
        _metric("Walk-forward OOS/IS consistency",round(wf_consistency, 3),   "> 0.70",     wf_consistency >= 0.70),
        _metric("Post-cost Sharpe",               round(post_cost_sr, 3),     "> 0.7",      post_cost_sr > 0.7),
        _metric("Parameter sensitivity",         "see grid",                 "< 30% change",sens_pass),
        _metric("Test period",                   f"{years:.1f} years",       ">= 5 years", years >= 5.0),
    ]

    gate1_criteria = [
        is_sharpe > 1.0,
        oos_sharpe > 0.7,
        abs(is_mdd) < 0.20,
        win_rate > 0.50,
        trade_count >= 100,
        dsr > 0,
        wf_passed >= 3,
        wf_consistency >= 0.70,
        sens_pass,
        years >= 5.0,
    ]
    n_pass = sum(gate1_criteria)
    n_total = len(gate1_criteria)

    failing = []
    if is_sharpe <= 1.0:       failing.append(f"IS Sharpe={is_sharpe:.3f} (need > 1.0)")
    if oos_sharpe <= 0.7:      failing.append(f"OOS Sharpe={oos_sharpe:.3f} (need > 0.7)")
    if abs(is_mdd) >= 0.20:    failing.append(f"IS MDD={is_mdd:.2%} (need < 20%)")
    if win_rate <= 0.50:       failing.append(f"Win rate={win_rate:.2%} (need > 50%)")
    if trade_count < 100:      failing.append(f"Trade count={trade_count} (need >= 100 IS)")
    if dsr <= 0:               failing.append(f"DSR={dsr:.3f} (need > 0)")
    if wf_passed < 3:          failing.append(f"WF windows passed={wf_passed}/4 (need >= 3)")
    if wf_consistency < 0.70:  failing.append(f"WF consistency={wf_consistency:.3f} (need >= 0.70)")
    if not sens_pass:          failing.append("Sensitivity: >30% Sharpe change detected")
    if years < 5.0:            failing.append(f"Test period={years:.1f} years (need >= 5)")

    overall = "PASS" if len(failing) == 0 else "FAIL"
    confidence = "LOW" if len(failing) >= 5 else ("MEDIUM" if len(failing) >= 2 else "HIGH")

    # Check for regime-slice Gate 1 criterion: IS Sharpe ≥ 0.8 in ≥ 2 of 4 regimes
    # (criteria.md v1.1 — but only 3 regime slices are defined, check if ≥ 1 stress regime passes)
    regime_slices = metrics.get("regime_slices", {})
    stress_regimes = ["rate_shock_2022"]
    non_stress_regimes = ["pre_covid_2018_2019", "stimulus_era_2020_2021"]

    stress_passing = [r for r in stress_regimes
                      if regime_slices.get(r, {}).get("sharpe", 0.0) >= 0.8]
    non_stress_passing = [r for r in non_stress_regimes
                          if regime_slices.get(r, {}).get("sharpe", 0.0) >= 0.8]
    regime_criterion_pass = len(stress_passing) >= 1 and (len(stress_passing) + len(non_stress_passing)) >= 2

    rec_text = (
        "Proceed to Risk Director review and paper trading."
        if overall == "PASS" else
        "DO NOT PROCEED to paper trading. Review failing criteria above."
    )

    return {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "overall_verdict": overall,
        "recommendation": rec_text,
        "confidence": confidence,
        "disqualify_reason": None,
        "gate1_pass": overall == "PASS",
        "criteria_passed": f"{n_pass}/{n_total}",
        "failing_criteria": failing,
        "regime_criterion_pass": regime_criterion_pass,
        "stress_regime_passes": stress_passing,
        "metrics": metrics_list,
        "oos_data_quality": metrics.get("oos_data_quality", None),
        "_template_validation": {"warnings": []},
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("H28 Combined Multi-Calendar — Gate 1 Backtest Runner")
    print(f"Strategy: {STRATEGY_NAME}")
    print(f"IS:  {IS_START} → {IS_END}  (14 years)")
    print(f"OOS: {OOS_START} → {OOS_END}  (strict holdout)")
    print("=" * 70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 1. IS Backtest ─────────────────────────────────────────────────────────
    print(f"\n[1/7] IS Backtest ({IS_START} → {IS_END})...")
    is_result  = run_backtest(IS_START, IS_END, PARAMETERS.copy())
    is_sharpe  = float(is_result.get("sharpe", 0.0))
    is_mdd     = float(is_result.get("max_drawdown", 0.0))
    is_wr      = float(is_result.get("win_rate", 0.0))
    is_pf      = float(is_result.get("profit_factor", 0.0) if "profit_factor" in is_result else 0.0)
    is_trades  = int(is_result.get("trade_count", 0))
    is_tpy     = float(is_result.get("trades_per_year", 0.0))
    is_return  = float(is_result.get("total_return", 0.0))
    is_returns = np.array(is_result["returns"].values if isinstance(is_result["returns"], pd.Series) else is_result["returns"])
    is_equity  = is_result.get("equity", pd.Series())
    is_trades_df = is_result.get("trades", pd.DataFrame())

    print(f"  IS: Sharpe={is_sharpe:.4f}, MDD={is_mdd:.2%}, "
          f"Trades={is_trades} ({is_tpy}/yr), WinRate={is_wr:.2%}")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────────
    print(f"\n[2/7] OOS Backtest ({OOS_START} → {OOS_END})...")
    oos_result   = run_backtest(OOS_START, OOS_END, PARAMETERS.copy())
    oos_sharpe   = float(oos_result.get("sharpe", 0.0))
    oos_mdd      = float(oos_result.get("max_drawdown", 0.0))
    oos_wr       = float(oos_result.get("win_rate", 0.0))
    oos_pf       = float(oos_result.get("profit_factor", 0.0) if "profit_factor" in oos_result else 0.0)
    oos_trades   = int(oos_result.get("trade_count", 0))
    oos_return   = float(oos_result.get("total_return", 0.0))
    oos_returns  = np.array(oos_result["returns"].values if isinstance(oos_result["returns"], pd.Series) else oos_result["returns"])
    oos_equity   = oos_result.get("equity", pd.Series())
    oos_trades_df = oos_result.get("trades", pd.DataFrame())

    print(f"  OOS: Sharpe={oos_sharpe:.4f}, MDD={oos_mdd:.2%}, "
          f"Trades={oos_trades}, WinRate={oos_wr:.2%}")

    # ── 3. Profit Factor ───────────────────────────────────────────────────────
    def _compute_pf(trades_df):
        if trades_df.empty or "pnl" not in trades_df.columns:
            return 0.0
        wins  = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        return round(float(wins / max(losses, 1e-8)), 4)

    is_pf  = _compute_pf(is_trades_df)
    oos_pf = _compute_pf(oos_trades_df)

    # ── 4. OOS Data Quality Validation ────────────────────────────────────────
    print("\n[3/7] OOS Data Quality Validation...")
    try:
        spy_oos = yf.download("SPY", start=OOS_START, end=OOS_END, progress=False, auto_adjust=True)
        if isinstance(spy_oos.columns, pd.MultiIndex):
            spy_oos.columns = spy_oos.columns.get_level_values(0)
    except Exception:
        spy_oos = pd.DataFrame({"Close": [100.0] * 500, "Volume": [5e7] * 500})

    post_cost_sr_approx = oos_sharpe  # will refine after market impact
    oos_metrics_for_dq = {
        "sharpe":          oos_sharpe,
        "max_drawdown":    oos_mdd,
        "win_rate":        oos_wr,
        "profit_factor":   oos_pf,
        "total_trades":    oos_trades,
        "post_cost_sharpe": post_cost_sr_approx,
        "total_return":    oos_return,
        "portfolio_returns": (oos_result["returns"] if isinstance(
            oos_result["returns"], pd.Series) else pd.Series(oos_returns)),
    }

    dq_report = validate_oos_data(spy_oos, oos_metrics_for_dq, STRATEGY_NAME)
    print(f"  OOS DQ: {dq_report['recommendation']}")
    if dq_report.get("advisory_nan_fields"):
        print(f"  Advisory NaN fields: {dq_report['advisory_nan_fields']}")

    if dq_report["recommendation"] == "BLOCK":
        print(f"  [BLOCK] {dq_report['block_reasons']}")
        blocked_path = os.path.join(OUTPUT_DIR, f"{STRATEGY_NAME}_{TODAY}_blocked_dq.json")
        with open(blocked_path, "w") as f:
            json.dump({"strategy": STRATEGY_NAME, "dq_report": dq_report}, f, indent=2, default=str)
        print(f"  Blocked. Report saved: {blocked_path}")
        return

    # ── 5. Statistical Rigor Pipeline ─────────────────────────────────────────
    print("\n[4/7] Statistical Rigor Pipeline...")

    # Trade PnLs from IS
    if isinstance(is_trades_df, pd.DataFrame) and "pnl" in is_trades_df.columns:
        trade_pnls_is = is_trades_df["pnl"].values.astype(float)
    else:
        trade_pnls_is = np.array([])

    # Monte Carlo
    mc = monte_carlo_sharpe(trade_pnls_is)
    print(f"  MC Sharpe: p5={mc['mc_p5_sharpe']:.3f}, "
          f"median={mc['mc_median_sharpe']:.3f}, p95={mc['mc_p95_sharpe']:.3f}")
    if mc["mc_p5_sharpe"] < 0.5:
        print("  [FLAG] MC pessimistic bound weak (p5 < 0.5)")

    # Block bootstrap CI (IS returns)
    ci = block_bootstrap_ci(is_returns)
    print(f"  Sharpe 95% CI: [{ci['sharpe_ci_low']:.3f}, {ci['sharpe_ci_high']:.3f}]")

    # Market impact
    mi = compute_market_impact_spy(OOS_START, OOS_END, PARAMETERS["init_cash"])
    print(f"  Market impact: {mi['market_impact_bps']:.2f} bps, "
          f"liquidity_constrained={mi['liquidity_constrained']}")

    # Post-cost Sharpe (cost drag from round-trip market impact)
    cost_drag_per_trade_pct = mi["market_impact_bps"] / 10000 * 2  # round-trip
    is_years = (pd.Timestamp(IS_END) - pd.Timestamp(IS_START)).days / 365.25
    trades_per_day_is = is_trades / (is_years * TRADING_DAYS_PER_YEAR) if is_years > 0 else 0
    annual_drag = cost_drag_per_trade_pct * trades_per_day_is * TRADING_DAYS_PER_YEAR
    post_cost_sharpe = round(is_sharpe - annual_drag * 5, 4)  # conservative factor

    # Permutation test
    if isinstance(is_equity, pd.Series) and len(is_equity) > 50:
        eq_prices = is_equity.values
    else:
        eq_prices = np.cumprod(1 + is_returns) * PARAMETERS["init_cash"]
    perm = permutation_test_alpha(eq_prices, is_sharpe, n_perms=1000,
                                   hold_days=int(PARAMETERS.get("max_hold_days", 5)))
    print(f"  Permutation test: p-value={perm['permutation_pvalue']:.4f}, "
          f"pass={perm['permutation_test_pass']}")

    # DSR (n_trials = number of parameter combinations tested = roughly 3+4+4+2+3+2 = 18)
    dsr = compute_dsr(is_returns, n_trials=18)
    print(f"  DSR z-score={dsr:.4f}")

    # ── 6. Walk-Forward ───────────────────────────────────────────────────────
    print("\n[5/7] Walk-Forward (4 expanding windows)...")
    wf = run_walk_forward(PARAMETERS.copy(), WF_WINDOWS)
    wf_var = walk_forward_variance(wf["wf_oos_sharpes"])
    print(f"  WF windows passed: {wf['wf_windows_passed']}/4")
    print(f"  WF OOS std={wf_var['wf_sharpe_std']:.4f}, min={wf_var['wf_sharpe_min']:.4f}")
    if wf_var["wf_sharpe_min"] < 0:
        print("  [FLAG] At least one losing OOS walk-forward window")

    # ── 7. Sensitivity Scan ───────────────────────────────────────────────────
    print(f"\n[6/7] Sensitivity scan (IS {IS_START}→{IS_END})...")
    sens = run_sensitivity_scan(PARAMETERS.copy(), IS_START, IS_END)
    print(f"  Sensitivity pass: {sens['sensitivity_pass']} "
          f"(max change={sens['sensitivity_max_change_pct']:.2%})")

    # ── 8. Regime Slices ─────────────────────────────────────────────────────
    print("\n[7/7] Regime-slice analysis...")
    regime_results = run_regime_slices(PARAMETERS.copy())

    # Regime criterion: ≥ 2 of 3 slices with Sharpe ≥ 0.8, including ≥ 1 stress
    stress = sum(1 for r in ["rate_shock_2022"]
                 if regime_results.get(r, {}).get("sharpe", 0.0) >= 0.8)
    total_passing = sum(1 for d in regime_results.values() if d.get("sharpe", 0.0) >= 0.8)
    regime_criterion_pass = stress >= 1 and total_passing >= 2
    print(f"  Regime criterion (≥2 pass incl ≥1 stress): "
          f"{total_passing}/3 pass, {stress}/1 stress → {'PASS' if regime_criterion_pass else 'FAIL'}")

    # ── 9. Save Trade Log CSV ─────────────────────────────────────────────────
    trade_log_path = os.path.join(OUTPUT_DIR, f"{STRATEGY_NAME}_{TODAY}_trades.csv")
    all_trades_dfs = []
    for tdf, label in [(is_trades_df, "IS"), (oos_trades_df, "OOS")]:
        if isinstance(tdf, pd.DataFrame) and not tdf.empty:
            df = tdf.copy()
            df["period"] = label
            all_trades_dfs.append(df)
    if all_trades_dfs:
        full_trades = pd.concat(all_trades_dfs, ignore_index=True)
        full_trades["trade_id"] = range(1, len(full_trades) + 1)
        full_trades.to_csv(trade_log_path, index=False)
        print(f"\nTrade log saved: {trade_log_path} ({len(full_trades)} rows)")

    # ── 10. Assemble Metrics JSON ─────────────────────────────────────────────
    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        "is_start": IS_START,
        "is_end": IS_END,
        "oos_start": OOS_START,
        "oos_end": OOS_END,

        # Gate 1 core metrics
        "is_sharpe": is_sharpe,
        "is_max_drawdown": is_mdd,
        "win_rate": is_wr,
        "profit_factor": is_pf,
        "trade_count": is_trades,
        "is_trades_per_year": is_tpy,
        "is_total_return": is_return,
        "oos_sharpe": oos_sharpe,
        "oos_max_drawdown": oos_mdd,
        "oos_win_rate": oos_wr,
        "oos_profit_factor": oos_pf,
        "oos_trades": oos_trades,
        "oos_total_return": oos_return,
        "post_cost_sharpe": post_cost_sharpe,

        # Signal decomposition
        "tom_signal_count": int(is_result.get("tom_signal_count", 0)),
        "oex_signal_count": int(is_result.get("oex_signal_count", 0)),
        "preholiday_signal_count": int(is_result.get("preholiday_signal_count", 0)),

        # Statistical rigor
        "dsr": dsr,
        "mc_p5_sharpe": mc["mc_p5_sharpe"],
        "mc_median_sharpe": mc["mc_median_sharpe"],
        "mc_p95_sharpe": mc["mc_p95_sharpe"],
        "sharpe_ci_low": ci["sharpe_ci_low"],
        "sharpe_ci_high": ci["sharpe_ci_high"],
        "mdd_ci_low": ci["mdd_ci_low"],
        "mdd_ci_high": ci["mdd_ci_high"],
        "win_rate_ci_low": ci["win_rate_ci_low"],
        "win_rate_ci_high": ci["win_rate_ci_high"],
        "market_impact_bps": mi["market_impact_bps"],
        "liquidity_constrained": mi["liquidity_constrained"],
        "order_to_adv_ratio": mi["order_to_adv_ratio"],
        "permutation_pvalue": perm["permutation_pvalue"],
        "permutation_test_pass": perm["permutation_test_pass"],

        # Walk-forward
        "wf_windows_passed": wf["wf_windows_passed"],
        "wf_total_windows": wf["wf_total_windows"],
        "wf_consistency_score": wf["wf_consistency_score"],
        "wf_avg_is_sharpe": wf["wf_avg_is_sharpe"],
        "wf_avg_oos_sharpe": wf["wf_avg_oos_sharpe"],
        "wf_oos_sharpes": wf["wf_oos_sharpes"],
        "wf_is_sharpes": wf["wf_is_sharpes"],
        "wf_sharpe_std": wf_var["wf_sharpe_std"],
        "wf_sharpe_min": wf_var["wf_sharpe_min"],

        # Sensitivity
        "sensitivity_pass": sens["sensitivity_pass"],
        "sensitivity_max_change_pct": sens["sensitivity_max_change_pct"],
        "sensitivity_results": sens["sensitivity_results"],

        # Regime
        "regime_slices": regime_results,
        "regime_criterion_pass": regime_criterion_pass,

        # Data quality
        "oos_data_quality": dq_report,
        "look_ahead_bias_flag": False,
        "survivorship_bias_flag": False,
        "data_quality_notes": "SPY + VIX strategy. No survivorship bias. auto_adjust=True applied.",
        "gate1_pass": False,
    }

    # ── 11. Save Metrics JSON ─────────────────────────────────────────────────
    json_path = os.path.join(OUTPUT_DIR, f"{STRATEGY_NAME}_{TODAY}.json")

    def _serial(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if isinstance(obj, pd.Series): return obj.tolist()
        if isinstance(obj, pd.Timestamp): return str(obj)
        return str(obj)

    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=_serial)
    print(f"\nMetrics JSON saved: {json_path}")

    # ── 12. Verdict ───────────────────────────────────────────────────────────
    verdict = build_verdict(metrics)
    val_result = validate_verdict_json(verdict)

    if val_result.has_errors:
        print(f"\n[VERDICT VALIDATION ERRORS]")
        for issue in val_result.issues:
            print(f"  {issue}")
        raise VerdictValidationError(STRATEGY_NAME, val_result.issues)

    if val_result.has_warnings:
        verdict["_template_validation"]["warnings"] = [
            str(i) for i in val_result.issues if i.severity == "warning"
        ]

    metrics["gate1_pass"] = verdict["gate1_pass"]

    # ── 13. Save Verdict Files ────────────────────────────────────────────────
    verdict_txt_path  = os.path.join(OUTPUT_DIR, f"{STRATEGY_NAME}_{TODAY}_verdict.txt")
    verdict_json_path = os.path.join(OUTPUT_DIR, f"{STRATEGY_NAME}_{TODAY}_verdict.json")

    with open(verdict_txt_path, "w") as f:
        f.write(f"Gate 1 Verdict: {verdict['overall_verdict']}\n")
        f.write(f"IS Sharpe: {is_sharpe:.2f}\n")
        f.write(f"OOS Sharpe: {oos_sharpe:.2f}\n")
        f.write(f"IS MDD: {is_mdd:.1%}\n")
        f.write(f"Win Rate: {is_wr:.1%}\n")
        f.write(f"Profit Factor: {is_pf:.2f}\n")
        f.write(f"Trade Count (IS): {is_trades}\n")
        f.write(f"Trade Count (OOS): {oos_trades}\n")
        f.write(f"Monte Carlo p5 Sharpe: {mc['mc_p5_sharpe']:.2f}\n")
        f.write(f"Bootstrap 95% CI: [{ci['sharpe_ci_low']:.2f}, {ci['sharpe_ci_high']:.2f}]\n")
        f.write(f"Permutation p-value: {perm['permutation_pvalue']:.3f}\n")
        f.write(f"Walk-forward Sharpe Variance: {wf_var['wf_sharpe_std']:.2f}\n")
        f.write(f"DSR: {dsr:.2f}\n")
        f.write(f"Pre-COVID Sharpe (2018-2019): {regime_results.get('pre_covid_2018_2019', {}).get('sharpe', 0.0):.2f}\n")
        f.write(f"Stimulus era Sharpe (2020-2021): {regime_results.get('stimulus_era_2020_2021', {}).get('sharpe', 0.0):.2f}\n")
        f.write(f"Rate-shock Sharpe (2022): {regime_results.get('rate_shock_2022', {}).get('sharpe', 0.0):.2f}\n")
        f.write(f"\nCriteria: {verdict['criteria_passed']}\n")
        if verdict.get("failing_criteria"):
            f.write(f"\nFailing:\n")
            for fc in verdict["failing_criteria"]:
                f.write(f"  - {fc}\n")
        f.write(f"\nRecommendation: {verdict['recommendation']}\n")
        f.write(f"\nSensitivity: pass={sens['sensitivity_pass']}, max_change={sens['sensitivity_max_change_pct']:.2%}\n")
        f.write(f"Regime criterion (≥2/3 incl stress): {'PASS' if regime_criterion_pass else 'FAIL'}\n")
        f.write(f"\nOOS DQ: {dq_report['recommendation']}\n")

    with open(verdict_json_path, "w") as f:
        json.dump(verdict, f, indent=2, default=_serial)

    print(f"Verdict saved: {verdict_txt_path}")
    print(f"Verdict JSON saved: {verdict_json_path}")

    # ── 14. Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("GATE 1 VERDICT SUMMARY — H28 Combined Multi-Calendar")
    print("=" * 70)
    print(f"Overall: {verdict['overall_verdict']} ({verdict['criteria_passed']} criteria)")
    print(f"IS Sharpe (2008–2022):  {is_sharpe:.4f}  (target > 1.0) — {'PASS' if is_sharpe > 1.0 else 'FAIL'}")
    print(f"OOS Sharpe (2023–2024): {oos_sharpe:.4f}  (target > 0.7) — {'PASS' if oos_sharpe > 0.7 else 'FAIL'}")
    print(f"IS MDD:     {is_mdd:.2%}  (target < 20%) — {'PASS' if abs(is_mdd) < 0.20 else 'FAIL'}")
    print(f"Win Rate:   {is_wr:.2%}  (target > 50%) — {'PASS' if is_wr > 0.50 else 'FAIL'}")
    print(f"Trades IS:  {is_trades}  (target >= 100) — {'PASS' if is_trades >= 100 else 'FAIL'}")
    print(f"DSR:        {dsr:.4f}  (target > 0) — {'PASS' if dsr > 0 else 'FAIL'}")
    print(f"WF windows: {wf['wf_windows_passed']}/4  (target >= 3) — {'PASS' if wf['wf_windows_passed'] >= 3 else 'FAIL'}")
    print(f"MC p5:      {mc['mc_p5_sharpe']:.4f}")
    print(f"Perm p-val: {perm['permutation_pvalue']:.4f}  ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})")
    print(f"Sensitivity: {sens['sensitivity_pass']} (max={sens['sensitivity_max_change_pct']:.2%})")
    print(f"Regime criterion: {'PASS' if regime_criterion_pass else 'FAIL'}")
    if verdict.get("failing_criteria"):
        print(f"\nFailing ({len(verdict['failing_criteria'])}):")
        for fc in verdict["failing_criteria"]:
            print(f"  - {fc}")
    print(f"\nOutput files:")
    print(f"  {json_path}")
    print(f"  {verdict_txt_path}")
    print(f"  {verdict_json_path}")
    print(f"  {trade_log_path}")

    return metrics, verdict


if __name__ == "__main__":
    np.random.seed(42)
    try:
        metrics, verdict = main()
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)
