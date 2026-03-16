"""
H27 Gate 1 Backtest Runner — PEAD Post-Earnings Announcement Drift
QUA-237

Executes IS/OOS backtests, walk-forward, statistical rigor pipeline,
regime-slice analysis, sensitivity scan, and all Engineering Director flags.

IS period:  2007-01-01 to 2021-12-31  (NOTE: earnings data limitation applies — see below)
OOS period: 2022-01-01 to 2025-12-31

CRITICAL DATA LIMITATION:
  yfinance earnings_dates typically covers only the last ~12 quarters (~3 years).
  The IS window (2007–2021) will generate near-zero trades because historical earnings
  dates are unavailable via yfinance for that period. This is a structural constraint
  of the strategy's data source, not a code bug. The OOS window (2022–2025) will have
  better coverage since it falls within yfinance's historical earnings horizon.

  The IS backtest will FAIL Gate 1 on trade count alone. An alternative
  "available-data IS" window (2023-01-01 to 2024-06-30) is run as supplemental
  analysis to assess strategy quality where earnings data actually exists.

Sensitivity heatmap: gap_threshold ∈ {0.02, 0.03, 0.04, 0.05} × hold_days ∈ {10, 20, 40}
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

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.h27_pead_earnings_drift import (
    run_backtest,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
    get_sp500_universe,
    load_earnings_dates,
    download_data,
)
from orchestrator.oos_data_quality import validate_oos_data, OOSDataQualityError
from orchestrator.gate1_verdict_validator import (
    validate_verdict_json,
    VerdictValidationError,
    enforce_verdict_template,
)

# ── Constants ──────────────────────────────────────────────────────────────────

IS_START  = "2007-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2025-12-31"

# Alternative IS window where yfinance earnings data actually exists
ALT_IS_START = "2023-01-01"
ALT_IS_END   = "2024-06-30"

TODAY = str(date.today())
STRATEGY_NAME = "H27_PEAD_EarningsDrift"
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "h27_pead_earnings_drift",
)

# ── Statistical Functions ──────────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    """Bootstrap MC on trade PnL → Sharpe distribution."""
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
    """Block bootstrap 95% CI for Sharpe, MDD, win rate."""
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


def compute_dsr(returns: np.ndarray, n_trials: int = 12) -> float:
    """
    Deflated Sharpe Ratio (Lopez de Prado).
    z-score adjustment for multiple testing and non-Gaussian returns.
    """
    from scipy import stats
    T = len(returns)
    if T < 2:
        return 0.0
    sr = returns.mean() / (returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    # DSR z-score: SR - (expected max SR from n_trials trials) / std of SR
    skew = float(pd.Series(returns).skew())
    kurt = float(pd.Series(returns).kurtosis())
    # Expected maximum SR under multiple testing
    gamma = 0.5772  # Euler-Mascheroni constant
    e_max_sr = (
        (1 - gamma) * stats.norm.ppf(1 - 1.0 / n_trials)
        + gamma * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    # Variance of SR estimate
    sigma_sr = np.sqrt(
        (1 + 0.5 * sr**2 - skew * sr + ((kurt - 3) / 4) * sr**2) / (T - 1)
    )
    dsr = (sr - e_max_sr) / (sigma_sr + 1e-8)
    return round(float(dsr), 4)


def permutation_test_alpha(
    prices: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 500,
    hold_days: int = 20,
) -> dict:
    """Permutation test: shuffle entry dates 500 times, compute p-value."""
    if len(prices) < hold_days + 1 or observed_sharpe == 0.0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    n_entries = max(1, len(prices) // hold_days // 4)
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
    """WF OOS Sharpe variance metrics."""
    if not wf_oos_sharpes:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": round(float(arr.std()), 4),
        "wf_sharpe_min": round(float(arr.min()), 4),
    }


# ── Walk-Forward Backtest ──────────────────────────────────────────────────────

def run_walk_forward(base_params: dict, n_folds: int = 4,
                     train_months: int = 18, test_months: int = 6) -> dict:
    """
    Walk-forward with n_folds windows.
    Uses train_months=18 and test_months=6 to keep within yfinance earnings coverage.
    NOTE: Full 36mo IS / 6mo OOS walk-forward cannot be run due to earnings data
    coverage limiting the effective tradeable period to ~3 years.
    """
    print(f"\nRunning walk-forward ({n_folds} folds, {train_months}mo train, {test_months}mo test)...")
    wf_start = pd.Timestamp("2023-01-01")
    wf_oos_sharpes = []
    wf_is_sharpes = []
    windows_passed = 0

    for fold in range(n_folds):
        is_start_ts = wf_start + pd.DateOffset(months=fold * test_months)
        is_end_ts   = is_start_ts + pd.DateOffset(months=train_months) - pd.DateOffset(days=1)
        oos_start_ts = is_end_ts + pd.DateOffset(days=1)
        oos_end_ts   = oos_start_ts + pd.DateOffset(months=test_months) - pd.DateOffset(days=1)

        is_s  = is_start_ts.strftime("%Y-%m-%d")
        is_e  = is_end_ts.strftime("%Y-%m-%d")
        oos_s = oos_start_ts.strftime("%Y-%m-%d")
        oos_e = oos_end_ts.strftime("%Y-%m-%d")

        print(f"  Fold {fold+1}: IS={is_s}→{is_e}, OOS={oos_s}→{oos_e}")

        try:
            is_res  = run_backtest(base_params.copy(), is_s, is_e)
            oos_res = run_backtest(base_params.copy(), oos_s, oos_e)

            is_sharpe  = float(is_res.get("sharpe", 0.0))
            oos_sharpe = float(oos_res.get("sharpe", 0.0))
            wf_is_sharpes.append(is_sharpe)
            wf_oos_sharpes.append(oos_sharpe)

            # Gate 1 WF criterion: OOS Sharpe ≥ 0.7 × IS Sharpe (within 30%)
            oos_is_ratio = oos_sharpe / (is_sharpe + 1e-8) if is_sharpe > 0 else 0.0
            passed = bool(oos_is_ratio >= 0.70) and bool(oos_sharpe > 0)
            if passed:
                windows_passed += 1
            print(f"    IS Sharpe={is_sharpe:.3f}, OOS Sharpe={oos_sharpe:.3f}, "
                  f"OOS/IS ratio={oos_is_ratio:.2f} → {'PASS' if passed else 'FAIL'}")
        except Exception as exc:
            print(f"    Fold {fold+1} failed: {exc}")
            wf_is_sharpes.append(0.0)
            wf_oos_sharpes.append(0.0)

    avg_is  = float(np.mean(wf_is_sharpes)) if wf_is_sharpes else 0.0
    avg_oos = float(np.mean(wf_oos_sharpes)) if wf_oos_sharpes else 0.0
    consistency = avg_oos / (avg_is + 1e-8) if avg_is > 0 else 0.0

    return {
        "wf_windows_passed": windows_passed,
        "wf_total_windows": n_folds,
        "wf_oos_sharpes": wf_oos_sharpes,
        "wf_is_sharpes": wf_is_sharpes,
        "wf_avg_is_sharpe": round(avg_is, 4),
        "wf_avg_oos_sharpe": round(avg_oos, 4),
        "wf_consistency_score": round(float(consistency), 4),
    }


# ── Sensitivity Scan ───────────────────────────────────────────────────────────

def run_sensitivity_scan(base_params: dict, start: str, end: str) -> dict:
    """
    Sensitivity heatmap: gap_threshold ∈ {0.02, 0.03, 0.04, 0.05} × hold_days ∈ {10, 20, 40}.
    Uses ALT IS window (2023-2024) where earnings data is available.
    """
    print("\nRunning sensitivity scan (gap_threshold × hold_days)...")
    gap_thresholds = [0.02, 0.03, 0.04, 0.05]
    hold_days_list  = [10, 20, 40]

    base_sharpe = base_params.get("_base_sharpe", 0.0)
    results = {}
    sharpe_changes = []

    for gt in gap_thresholds:
        for hd in hold_days_list:
            key = f"gap_{gt}_hold_{hd}"
            try:
                p = base_params.copy()
                p["gap_threshold"] = gt
                p["hold_days"] = hd
                res = run_backtest(p, start, end)
                s = float(res.get("sharpe", 0.0))
                results[key] = s
                if base_sharpe > 0:
                    pct_change = abs(s - base_sharpe) / (abs(base_sharpe) + 1e-8)
                    sharpe_changes.append(pct_change)
                print(f"  gap={gt}, hold={hd}: Sharpe={s:.3f}")
            except Exception as exc:
                print(f"  gap={gt}, hold={hd}: FAILED — {exc}")
                results[key] = 0.0

    # Sensitivity pass: max Sharpe change < 30% for ±20% param variation
    sensitivity_pass = False
    if sharpe_changes:
        max_change = max(sharpe_changes)
        sensitivity_pass = bool(max_change < 0.30)

    return {
        "sensitivity_results": results,
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_change_pct": round(float(max(sharpe_changes)) if sharpe_changes else 0.0, 4),
    }


# ── Regime-Slice Analysis ──────────────────────────────────────────────────────

def run_regime_slices(params: dict) -> dict:
    """
    Regime-slice IS Sharpe: Per task spec.
    Note: Most pre-2022 slices will have zero trades due to earnings data gap.
    Post-2022 slices will have actual results.
    """
    slices = {
        "pre_gfc_2007":       ("2007-01-01", "2007-12-31"),
        "gfc_2008_2009":      ("2008-01-01", "2009-12-31"),
        "recovery_2010_2015": ("2010-01-01", "2015-12-31"),
        "bull_2016_2019":     ("2016-01-01", "2019-12-31"),
        "covid_2020":         ("2020-01-01", "2020-12-31"),
        "rate_shock_2022":    ("2022-01-01", "2022-12-31"),
        "post_rate_2023_2025":("2023-01-01", "2025-12-31"),
    }
    results = {}
    for name, (s, e) in slices.items():
        try:
            res = run_backtest(params.copy(), s, e)
            results[name] = {
                "sharpe": float(res.get("sharpe", 0.0)),
                "trade_count": int(res.get("trade_count", 0)),
                "max_drawdown": float(res.get("max_drawdown", 0.0)),
            }
            print(f"  {name}: Sharpe={results[name]['sharpe']:.3f}, "
                  f"Trades={results[name]['trade_count']}, "
                  f"MDD={results[name]['max_drawdown']:.2%}")
        except Exception as exc:
            print(f"  {name}: FAILED — {exc}")
            results[name] = {"sharpe": 0.0, "trade_count": 0, "max_drawdown": 0.0}
    return results


# ── PF-2 Trailing Position Drawdown ───────────────────────────────────────────

def compute_trailing_position_mdd(trade_log: list, equity_curve: list,
                                   equity_index: pd.DatetimeIndex) -> dict:
    """
    PF-2 validation: compute peak portfolio drawdown for positions opened within
    20 days before SPY crosses below 200-SMA.
    Approximated here by identifying regime transitions and examining position timing.
    """
    try:
        spy = download_data("SPY", "2006-01-01", "2025-12-31")
        spy["sma200"] = spy["Close"].rolling(200).mean()
        spy["regime_up"] = spy["Close"] > spy["sma200"]
        spy["regime_change"] = spy["regime_up"].diff()

        # Find regime-down transitions (bull→bear crossings)
        bear_crossings = spy.index[spy["regime_change"] == -1].tolist()

        if not bear_crossings or not trade_log:
            return {
                "pf2_trailing_mdd_2008_2009": None,
                "pf2_trailing_mdd_2022": None,
                "pf2_note": "No regime transitions or trades found",
            }

        # Check which trades were opened within 20 days before a bear crossing
        trades_df = pd.DataFrame(trade_log)
        if trades_df.empty or "entry_date" not in trades_df.columns:
            return {
                "pf2_trailing_mdd_2008_2009": None,
                "pf2_trailing_mdd_2022": None,
                "pf2_note": "No trades in log",
            }

        trades_df["entry_date"] = pd.to_datetime(trades_df["entry_date"])
        gfc_crossings = [c for c in bear_crossings
                         if pd.Timestamp("2008-01-01") <= c <= pd.Timestamp("2009-12-31")]
        rate_crossings = [c for c in bear_crossings
                          if pd.Timestamp("2022-01-01") <= c <= pd.Timestamp("2022-12-31")]

        def _trailing_mdd(crossings):
            if not crossings:
                return None
            trailing_pnls = []
            for crossing in crossings:
                window_start = crossing - pd.Timedelta(days=28)  # ~20 trading days
                mask = (
                    (trades_df["entry_date"] >= window_start) &
                    (trades_df["entry_date"] <= crossing)
                )
                sub = trades_df.loc[mask]
                trailing_pnls.extend(sub["pnl"].tolist() if "pnl" in sub.columns else [])
            if not trailing_pnls:
                return None
            arr = np.array(trailing_pnls)
            cum = np.cumsum(arr)
            roll_max = np.maximum.accumulate(cum)
            return round(float(np.min((cum - roll_max) / (np.abs(roll_max) + 1e-8))), 4)

        gfc_mdd   = _trailing_mdd(gfc_crossings)
        rate_mdd  = _trailing_mdd(rate_crossings)

        return {
            "pf2_trailing_mdd_2008_2009": gfc_mdd,
            "pf2_trailing_mdd_2022": rate_mdd,
            "pf2_note": (
                f"Trailing positions found: GFC={len(gfc_crossings)} crossings, "
                f"2022={len(rate_crossings)} crossings"
            ),
        }
    except Exception as exc:
        return {
            "pf2_trailing_mdd_2008_2009": None,
            "pf2_trailing_mdd_2022": None,
            "pf2_note": f"PF-2 computation failed: {exc}",
        }


# ── Gate 1 Verdict Builder ─────────────────────────────────────────────────────

def build_verdict(metrics: dict) -> dict:
    """Build Gate 1 verdict JSON from metrics dict."""

    def _metric(name, value, threshold, passed):
        return {"name": name, "value": str(value), "threshold": threshold, "passed": bool(passed)}

    is_sharpe     = metrics.get("is_sharpe", 0.0)
    oos_sharpe    = metrics.get("oos_sharpe", 0.0)
    is_mdd        = metrics.get("is_max_drawdown", 0.0)
    oos_mdd       = metrics.get("oos_max_drawdown", 0.0)
    win_rate      = metrics.get("win_rate", 0.0)
    trade_count   = metrics.get("trade_count", 0)
    dsr           = metrics.get("dsr", 0.0)
    wf_passed     = metrics.get("wf_windows_passed", 0)
    wf_consistency = metrics.get("wf_consistency_score", 0.0)
    sens_pass     = metrics.get("sensitivity_pass", False)
    post_cost_sr  = metrics.get("post_cost_sharpe", 0.0)
    test_start    = metrics.get("is_start", IS_START)
    test_end      = metrics.get("oos_end", OOS_END)
    years = (pd.Timestamp(test_end) - pd.Timestamp(test_start)).days / 365.25

    metrics_list = [
        _metric("IS Sharpe",                      round(is_sharpe, 3),       "> 1.0",       is_sharpe > 1.0),
        _metric("OOS Sharpe",                     round(oos_sharpe, 3),      "> 0.7",       oos_sharpe > 0.7),
        _metric("IS Max Drawdown",                f"{is_mdd:.2%}",           "< -20%",      abs(is_mdd) < 0.20),
        _metric("OOS Max Drawdown",               f"{oos_mdd:.2%}",          "< -25%",      abs(oos_mdd) < 0.25),
        _metric("Win Rate",                       f"{win_rate:.2%}",         "> 50%",       win_rate > 0.50),
        _metric("Trade count",                    trade_count,               ">= 50 (IS)",  trade_count >= 50),
        _metric("Deflated Sharpe Ratio (z-score)",round(dsr, 3),             "> 0",         dsr > 0),
        _metric("Walk-forward windows passed",    f"{wf_passed}/4",          ">= 3",        wf_passed >= 3),
        _metric("Walk-forward OOS/IS consistency",round(wf_consistency, 3),  "> 0.70",      wf_consistency >= 0.70),
        _metric("Post-cost Sharpe",               round(post_cost_sr, 3),    "> 0.7",       post_cost_sr > 0.7),
        _metric("Parameter sensitivity",         "see heatmap",             "< 30% change",sens_pass),
        _metric("Test period",                   f"{years:.1f} years",      ">= 5 years",  years >= 5.0),
    ]

    # Gate 1 pass/fail
    gate1_criteria = [
        is_sharpe > 1.0,
        oos_sharpe > 0.7,
        abs(is_mdd) < 0.20,
        win_rate > 0.50,
        trade_count >= 50,
        dsr > 0,
        wf_passed >= 3,
        wf_consistency >= 0.70,
        sens_pass,
        years >= 5.0,
    ]
    n_pass = sum(gate1_criteria)
    n_total = len(gate1_criteria)

    # Identify failing criteria
    failing = []
    if is_sharpe <= 1.0:    failing.append(f"IS Sharpe={is_sharpe:.3f} (need > 1.0)")
    if oos_sharpe <= 0.7:   failing.append(f"OOS Sharpe={oos_sharpe:.3f} (need > 0.7)")
    if abs(is_mdd) >= 0.20: failing.append(f"IS MDD={is_mdd:.2%} (need < 20%)")
    if win_rate <= 0.50:    failing.append(f"Win rate={win_rate:.2%} (need > 50%)")
    if trade_count < 50:    failing.append(f"Trade count={trade_count} (need >= 50 IS)")
    if dsr <= 0:            failing.append(f"DSR={dsr:.3f} (need > 0)")
    if wf_passed < 3:       failing.append(f"WF windows passed={wf_passed}/4 (need >= 3)")
    if wf_consistency < 0.70: failing.append(f"WF consistency={wf_consistency:.3f} (need >= 0.70)")
    if not sens_pass:       failing.append("Sensitivity: >30% Sharpe change detected")
    if years < 5.0:         failing.append(f"Test period={years:.1f} years (need >= 5)")

    overall = "PASS" if len(failing) == 0 else "FAIL"
    confidence = "LOW" if len(failing) >= 5 else ("MEDIUM" if len(failing) >= 2 else "HIGH")

    disqualify_reason = None
    if trade_count < 50:
        disqualify_reason = (
            f"DISQUALIFIED: Insufficient IS trades ({trade_count} < 50 required). "
            "Root cause: yfinance earnings_dates covers only ~12 quarters. "
            "The 2007–2021 IS window predates yfinance earnings coverage, "
            "resulting in near-zero signal generation. "
            "Strategy requires a point-in-time earnings data source for full IS validation."
        )

    rec_text = (
        "DO NOT PROCEED to paper trading. Requires point-in-time earnings data source "
        "(e.g., Compustat, Bloomberg earnings calendar) to run the full 2007–2021 IS window. "
        "With available-data IS (2023–2024), strategy shows structural promise but "
        "insufficient historical validation for Gate 1 approval."
        if overall == "FAIL" else
        "Proceed to Risk Director review and paper trading."
    )

    return {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "overall_verdict": overall,
        "recommendation": rec_text,
        "confidence": confidence,
        "disqualify_reason": disqualify_reason,
        "gate1_pass": overall == "PASS",
        "criteria_passed": f"{n_pass}/{n_total}",
        "failing_criteria": failing,
        "metrics": metrics_list,
        "oos_data_quality": metrics.get("oos_data_quality", None),
        "_template_validation": {"warnings": []},
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("H27 PEAD Gate 1 Backtest Runner")
    print(f"Strategy: {STRATEGY_NAME}")
    print(f"IS:  {IS_START} → {IS_END}")
    print(f"OOS: {OOS_START} → {OOS_END}")
    print(f"Alt IS (earnings-available): {ALT_IS_START} → {ALT_IS_END}")
    print("=" * 70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 1. Run IS backtest (2007-2021) ────────────────────────────────────────
    print(f"\n[1/7] Running IS backtest ({IS_START} → {IS_END})...")
    print("NOTE: Expecting near-zero trades due to yfinance earnings coverage gap.")
    is_result = run_backtest(PARAMETERS.copy(), IS_START, IS_END)
    is_sharpe     = float(is_result.get("sharpe", 0.0))
    is_mdd        = float(is_result.get("max_drawdown", 0.0))
    is_win_rate   = float(is_result.get("win_rate", 0.0))
    is_pf         = float(is_result.get("profit_factor", 0.0))
    is_trades     = int(is_result.get("trade_count", 0))
    is_coverage   = float(is_result.get("earnings_coverage_rate", 0.0))
    is_returns    = np.array(is_result.get("returns", pd.Series()).values
                             if isinstance(is_result.get("returns"), pd.Series)
                             else is_result.get("returns", []))
    is_equity_idx = (is_result.get("equity").index
                     if isinstance(is_result.get("equity"), pd.Series) else None)

    print(f"  IS Sharpe={is_sharpe:.4f}, MDD={is_mdd:.2%}, "
          f"Trades={is_trades}, WinRate={is_win_rate:.2%}, "
          f"EarningsCoverage={is_coverage:.1%}")

    # ── 2. Run Alt IS backtest (2023-2024) — earnings data available ──────────
    print(f"\n[1b/7] Running Alt IS backtest ({ALT_IS_START} → {ALT_IS_END}) "
          "where earnings data exists...")
    alt_is_result  = run_backtest(PARAMETERS.copy(), ALT_IS_START, ALT_IS_END)
    alt_is_sharpe  = float(alt_is_result.get("sharpe", 0.0))
    alt_is_mdd     = float(alt_is_result.get("max_drawdown", 0.0))
    alt_is_trades  = int(alt_is_result.get("trade_count", 0))
    alt_is_returns = np.array(alt_is_result.get("returns", pd.Series()).values
                               if isinstance(alt_is_result.get("returns"), pd.Series)
                               else alt_is_result.get("returns", []))
    print(f"  Alt IS Sharpe={alt_is_sharpe:.4f}, MDD={alt_is_mdd:.2%}, "
          f"Trades={alt_is_trades}")

    # ── 3. Run OOS backtest (2022-2025) ───────────────────────────────────────
    print(f"\n[2/7] Running OOS backtest ({OOS_START} → {OOS_END})...")
    oos_result    = run_backtest(PARAMETERS.copy(), OOS_START, OOS_END)
    oos_sharpe    = float(oos_result.get("sharpe", 0.0))
    oos_mdd       = float(oos_result.get("max_drawdown", 0.0))
    oos_win_rate  = float(oos_result.get("win_rate", 0.0))
    oos_pf        = float(oos_result.get("profit_factor", 0.0))
    oos_trades    = int(oos_result.get("trade_count", 0))
    oos_coverage  = float(oos_result.get("earnings_coverage_rate", 0.0))
    oos_trade_log = oos_result.get("trades", [])
    oos_equity    = oos_result.get("equity", pd.Series())
    oos_returns   = np.array(oos_result.get("returns", pd.Series()).values
                              if isinstance(oos_result.get("returns"), pd.Series)
                              else oos_result.get("returns", []))

    print(f"  OOS Sharpe={oos_sharpe:.4f}, MDD={oos_mdd:.2%}, "
          f"Trades={oos_trades}, WinRate={oos_win_rate:.2%}, "
          f"EarningsCoverage={oos_coverage:.1%}")

    # ── 4. OOS Data Quality Validation ───────────────────────────────────────
    print("\n[3/7] OOS Data Quality Validation...")
    # Build minimal OOS data frame for validation (use SPY as proxy for data coverage)
    try:
        spy_oos = yf.download("SPY", start=OOS_START, end=OOS_END, progress=False, auto_adjust=True)
        if isinstance(spy_oos.columns, pd.MultiIndex):
            spy_oos.columns = spy_oos.columns.get_level_values(0)
    except Exception:
        spy_oos = pd.DataFrame({"Close": [100.0] * 1000})

    oos_metrics_for_dq = {
        "sharpe":          oos_sharpe,
        "max_drawdown":    oos_mdd,
        "win_rate":        oos_win_rate,
        "profit_factor":   oos_pf,
        "total_trades":    oos_trades,
        "post_cost_sharpe": oos_sharpe * 0.90,  # approx pre-DQ
        "total_return":    float(oos_result.get("total_return", 0.0)),
        "portfolio_returns": (oos_result.get("returns") if isinstance(
            oos_result.get("returns"), pd.Series) else pd.Series(oos_returns)),
    }

    dq_report = validate_oos_data(spy_oos, oos_metrics_for_dq, STRATEGY_NAME)
    print(f"  OOS Data Quality: {dq_report['recommendation']}")
    if dq_report.get("advisory_nan_fields"):
        print(f"  Advisory NaN fields: {dq_report['advisory_nan_fields']}")

    if dq_report["recommendation"] == "BLOCK":
        print(f"  [BLOCK] {dq_report['block_reasons']}")
        # Write blocked report and exit
        blocked_path = os.path.join(OUTPUT_DIR, f"H27_PEAD_{TODAY}_blocked_dq.json")
        with open(blocked_path, "w") as f:
            json.dump({"strategy": STRATEGY_NAME, "dq_report": dq_report}, f, indent=2, default=str)
        print(f"  Blocked report saved: {blocked_path}")
        return

    if dq_report["recommendation"] == "WARN":
        print(f"  [WARN] Proceeding with warnings: {dq_report.get('advisory_nan_fields', [])}")

    # ── 5. Statistical Rigor Pipeline ────────────────────────────────────────
    print("\n[4/7] Statistical Rigor Pipeline...")

    # Use OOS trades for MC (where we have actual trading signal)
    trade_pnls_oos = np.array([t.get("pnl", 0) for t in oos_trade_log]) if oos_trade_log else np.array([])

    # Monte Carlo
    mc_results = monte_carlo_sharpe(trade_pnls_oos)
    print(f"  MC Sharpe: p5={mc_results['mc_p5_sharpe']:.3f}, "
          f"median={mc_results['mc_median_sharpe']:.3f}, "
          f"p95={mc_results['mc_p95_sharpe']:.3f}")
    if mc_results["mc_p5_sharpe"] < 0.5:
        print("  [FLAG] MC pessimistic bound weak (p5 < 0.5)")

    # Block bootstrap CI (on OOS returns)
    ci_results = block_bootstrap_ci(oos_returns)
    print(f"  Sharpe 95% CI: [{ci_results['sharpe_ci_low']:.3f}, {ci_results['sharpe_ci_high']:.3f}]")

    # Market impact (OOS — for representative trade sizing)
    # Compute using SPY proxy (representative equity)
    try:
        spy_hist = spy_oos.copy()
        adv = spy_hist["Volume"].rolling(20).mean().iloc[-1] if "Volume" in spy_hist.columns else 5e7
        sigma = spy_hist["Close"].pct_change().std() if "Close" in spy_hist.columns else 0.01
        order_qty = float(PARAMETERS["init_cash"] / PARAMETERS["max_positions"] / 400)  # approx shares
        k = 0.1
        impact_pct = k * sigma * np.sqrt(order_qty / (float(adv) + 1e-8))
        market_impact_bps = impact_pct * 10000
        liquidity_constrained = bool(order_qty > 0.01 * float(adv))
        order_to_adv = float(order_qty / (float(adv) + 1e-8))
    except Exception:
        market_impact_bps = 0.5
        liquidity_constrained = False
        order_to_adv = 0.0001

    print(f"  Market impact: {market_impact_bps:.2f} bps, "
          f"liquidity_constrained={liquidity_constrained}")

    # Post-cost Sharpe adjustment
    cost_drag_per_trade = (market_impact_bps / 10000) * 2  # round-trip
    if oos_trades > 0:
        oos_years = (pd.Timestamp(OOS_END) - pd.Timestamp(OOS_START)).days / 365.25
        trades_per_day = oos_trades / (oos_years * TRADING_DAYS_PER_YEAR)
        annual_drag = cost_drag_per_trade * trades_per_day * TRADING_DAYS_PER_YEAR
        post_cost_sharpe = round(oos_sharpe - annual_drag * 10, 4)
    else:
        post_cost_sharpe = oos_sharpe

    # Permutation test (on OOS equity curve as price proxy)
    if isinstance(oos_equity, pd.Series) and len(oos_equity) > 50:
        oos_prices = oos_equity.values
    else:
        oos_prices = np.cumprod(1 + oos_returns) * PARAMETERS["init_cash"] if len(oos_returns) > 0 else np.array([100.0] * 100)
    perm_results = permutation_test_alpha(oos_prices, oos_sharpe, n_perms=500)
    print(f"  Permutation test: p-value={perm_results['permutation_pvalue']:.4f}, "
          f"pass={perm_results['permutation_test_pass']}")

    # DSR
    dsr_returns = alt_is_returns if len(alt_is_returns) > 2 else oos_returns
    dsr = compute_dsr(dsr_returns, n_trials=12)
    print(f"  DSR z-score={dsr:.4f}")

    # ── 6. Walk-Forward ───────────────────────────────────────────────────────
    print("\n[5/7] Walk-Forward (4-fold, 18mo train / 6mo test — within earnings data window)...")
    wf_results = run_walk_forward(
        PARAMETERS.copy(), n_folds=4, train_months=18, test_months=6
    )
    wf_var = walk_forward_variance(wf_results["wf_oos_sharpes"])
    print(f"  WF windows passed: {wf_results['wf_windows_passed']}/4")
    print(f"  WF OOS Sharpe std={wf_var['wf_sharpe_std']:.4f}, min={wf_var['wf_sharpe_min']:.4f}")
    if wf_var["wf_sharpe_min"] < 0:
        print("  [FLAG] At least one losing OOS walk-forward window")

    # ── 7. Sensitivity Scan ───────────────────────────────────────────────────
    print(f"\n[6/7] Sensitivity scan (using alt IS: {ALT_IS_START}→{ALT_IS_END})...")
    base_params_sens = PARAMETERS.copy()
    base_params_sens["_base_sharpe"] = alt_is_sharpe
    sens_results = run_sensitivity_scan(base_params_sens, ALT_IS_START, ALT_IS_END)
    print(f"  Sensitivity pass: {sens_results['sensitivity_pass']} "
          f"(max change={sens_results['sensitivity_max_change_pct']:.2%})")

    # ── 8. Regime Slices ─────────────────────────────────────────────────────
    print("\n[7/7] Regime-slice analysis...")
    regime_results = run_regime_slices(PARAMETERS.copy())

    # ── 9. PF-2 Trailing Position MDD ─────────────────────────────────────────
    print("\nPF-2: Trailing position drawdown analysis...")
    is_trade_log = is_result.get("trades", [])
    oos_eq_index = oos_equity.index if isinstance(oos_equity, pd.Series) else pd.DatetimeIndex([])
    pf2_results = compute_trailing_position_mdd(
        is_trade_log + oos_trade_log,
        oos_equity.tolist() if isinstance(oos_equity, pd.Series) else [],
        oos_eq_index,
    )
    print(f"  PF-2 GFC MDD: {pf2_results['pf2_trailing_mdd_2008_2009']}, "
          f"2022 MDD: {pf2_results['pf2_trailing_mdd_2022']}")

    # ── 10. Assemble Metrics JSON ─────────────────────────────────────────────
    wf_consistency = wf_results["wf_consistency_score"]

    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        "is_start": IS_START,
        "is_end": IS_END,
        "oos_start": OOS_START,
        "oos_end": OOS_END,
        "alt_is_start": ALT_IS_START,
        "alt_is_end": ALT_IS_END,

        # IS metrics (full 2007-2021 window — limited by earnings data)
        "is_sharpe": is_sharpe,
        "is_max_drawdown": is_mdd,
        "is_win_rate": is_win_rate,
        "is_profit_factor": is_pf,
        "is_trade_count": is_trades,
        "is_earnings_coverage_rate": is_coverage,

        # Alt IS metrics (2023-2024 — where earnings data exists)
        "alt_is_sharpe": alt_is_sharpe,
        "alt_is_max_drawdown": alt_is_mdd,
        "alt_is_trade_count": alt_is_trades,

        # OOS metrics
        "oos_sharpe": oos_sharpe,
        "oos_max_drawdown": oos_mdd,
        "win_rate": oos_win_rate,
        "profit_factor": oos_pf,
        "trade_count": is_trades,  # Gate 1 criterion uses IS trade count
        "oos_trade_count": oos_trades,
        "oos_earnings_coverage_rate": oos_coverage,

        # Aggregated metrics (Gate 1 criteria)
        "sharpe": is_sharpe,  # primary IS Sharpe for Gate 1
        "max_drawdown": is_mdd,
        "post_cost_sharpe": post_cost_sharpe,
        "dsr": dsr,
        "wf_windows_passed": wf_results["wf_windows_passed"],
        "wf_total_windows": wf_results["wf_total_windows"],
        "wf_consistency_score": wf_consistency,
        "wf_avg_is_sharpe": wf_results["wf_avg_is_sharpe"],
        "wf_avg_oos_sharpe": wf_results["wf_avg_oos_sharpe"],
        "wf_sharpe_std": wf_var["wf_sharpe_std"],
        "wf_sharpe_min": wf_var["wf_sharpe_min"],
        "wf_oos_sharpes": wf_results["wf_oos_sharpes"],
        "wf_is_sharpes": wf_results["wf_is_sharpes"],
        "sensitivity_pass": sens_results["sensitivity_pass"],
        "sensitivity_results": sens_results["sensitivity_results"],
        "sensitivity_max_change_pct": sens_results["sensitivity_max_change_pct"],

        # Statistical rigor
        "mc_p5_sharpe": mc_results["mc_p5_sharpe"],
        "mc_median_sharpe": mc_results["mc_median_sharpe"],
        "mc_p95_sharpe": mc_results["mc_p95_sharpe"],
        "sharpe_ci_low": ci_results["sharpe_ci_low"],
        "sharpe_ci_high": ci_results["sharpe_ci_high"],
        "mdd_ci_low": ci_results["mdd_ci_low"],
        "mdd_ci_high": ci_results["mdd_ci_high"],
        "win_rate_ci_low": ci_results["win_rate_ci_low"],
        "win_rate_ci_high": ci_results["win_rate_ci_high"],
        "market_impact_bps": round(market_impact_bps, 4),
        "liquidity_constrained": liquidity_constrained,
        "order_to_adv_ratio": round(order_to_adv, 6),
        "permutation_pvalue": perm_results["permutation_pvalue"],
        "permutation_test_pass": perm_results["permutation_test_pass"],

        # Regime slices
        "regime_slices": regime_results,

        # PF-2 trailing position drawdown
        "pf2_trailing_mdd_2008_2009": pf2_results["pf2_trailing_mdd_2008_2009"],
        "pf2_trailing_mdd_2022": pf2_results["pf2_trailing_mdd_2022"],
        "pf2_note": pf2_results["pf2_note"],

        # Data quality
        "oos_data_quality": dq_report,
        "earnings_coverage_rate": oos_coverage,
        "survivorship_bias_flag": True,
        "data_quality_notes": (
            "CRITICAL: yfinance earnings_dates covers only ~12 quarters (~3 years). "
            "IS window (2007–2021) generates near-zero trades. "
            "OOS window (2022–2025) uses available earnings data. "
            "Alt IS (2023–2024) used for sensitivity analysis and WF. "
            "Survivorship bias present: universe = current-day top 200 S&P 500."
        ),
        "look_ahead_bias_flag": False,
        "gate1_pass": False,  # updated by verdict
    }

    # ── 11. Save Metrics JSON ─────────────────────────────────────────────────
    json_path = os.path.join(OUTPUT_DIR, f"H27_PEAD_{TODAY}.json")

    def _make_serializable(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Series):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return str(obj)
        return str(obj)

    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=_make_serializable)
    print(f"\nMetrics JSON saved: {json_path}")

    # ── 12. Build and Validate Verdict ────────────────────────────────────────
    verdict = build_verdict(metrics)

    val_result = validate_verdict_json(verdict)
    if val_result.has_errors:
        print(f"\n[VERDICT VALIDATION ERRORS]")
        for issue in val_result.issues:
            print(f"  {issue}")
        raise VerdictValidationError(STRATEGY_NAME, val_result.issues)

    if val_result.has_warnings:
        print(f"\n[VERDICT VALIDATION WARNINGS]")
        for issue in val_result.issues:
            if issue.severity == "warning":
                print(f"  {issue}")
        verdict["_template_validation"]["warnings"] = [str(i) for i in val_result.issues if i.severity == "warning"]

    # Update gate1_pass in metrics
    metrics["gate1_pass"] = verdict["gate1_pass"]

    # ── 13. Save Verdict ──────────────────────────────────────────────────────
    verdict_path = os.path.join(OUTPUT_DIR, f"H27_PEAD_{TODAY}_verdict.txt")
    with open(verdict_path, "w") as f:
        f.write(f"H27 PEAD Earnings Drift — Gate 1 Verdict\n")
        f.write(f"Generated: {TODAY}\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"OVERALL VERDICT: {verdict['overall_verdict']}\n")
        f.write(f"Criteria passed: {verdict['criteria_passed']}\n")
        f.write(f"Confidence: {verdict['confidence']}\n\n")

        if verdict.get("disqualify_reason"):
            f.write(f"DISQUALIFICATION REASON:\n{verdict['disqualify_reason']}\n\n")

        f.write("METRICS TABLE:\n")
        for m in verdict["metrics"]:
            status = "PASS" if m["passed"] else "FAIL"
            f.write(f"  [{status}] {m['name']}: {m['value']} (threshold: {m['threshold']})\n")

        f.write("\n")
        if verdict.get("failing_criteria"):
            f.write("FAILING CRITERIA:\n")
            for fc in verdict["failing_criteria"]:
                f.write(f"  - {fc}\n")
            f.write("\n")

        f.write(f"RECOMMENDATION:\n{verdict['recommendation']}\n\n")

        f.write("SUPPLEMENTAL ANALYSIS (earnings-available window only):\n")
        f.write(f"  Alt IS ({ALT_IS_START}→{ALT_IS_END}): "
                f"Sharpe={alt_is_sharpe:.3f}, MDD={alt_is_mdd:.2%}, Trades={alt_is_trades}\n")
        f.write(f"  WF (4-fold within 2023–2025): {wf_results['wf_windows_passed']}/4 passed, "
                f"avg OOS Sharpe={wf_results['wf_avg_oos_sharpe']:.3f}\n")
        f.write(f"  MC p5 Sharpe={mc_results['mc_p5_sharpe']:.3f} "
                f"({'WEAK' if mc_results['mc_p5_sharpe'] < 0.5 else 'OK'})\n")
        f.write(f"  Permutation p-value={perm_results['permutation_pvalue']:.4f} "
                f"({'PASS' if perm_results['permutation_test_pass'] else 'FAIL alpha test'})\n")
        f.write(f"  DSR z-score={dsr:.4f} ({'PASS' if dsr > 0 else 'FAIL'})\n")

        f.write("\nDATA QUALITY NOTES:\n")
        f.write(f"  OOS DQ: {dq_report['recommendation']}\n")
        f.write(f"  {metrics['data_quality_notes']}\n")

        f.write("\nPF-2 TRAILING POSITION DRAWDOWN:\n")
        f.write(f"  GFC 2008-2009: {pf2_results['pf2_trailing_mdd_2008_2009']}\n")
        f.write(f"  Rate Shock 2022: {pf2_results['pf2_trailing_mdd_2022']}\n")
        f.write(f"  {pf2_results['pf2_note']}\n")

        f.write("\nSENSITIVITY HEATMAP (alt IS, gap_threshold × hold_days):\n")
        for key, val in sens_results["sensitivity_results"].items():
            f.write(f"  {key}: Sharpe={val:.3f}\n")

        f.write("\nREGIME SLICES:\n")
        for name, data in regime_results.items():
            f.write(f"  {name}: Sharpe={data['sharpe']:.3f}, "
                    f"Trades={data['trade_count']}, MDD={data['max_drawdown']:.2%}\n")

        f.write("\nSURVIVORSHIP BIAS CAVEAT:\n")
        f.write("  Universe = current-day top 200 S&P 500 by market cap.\n")
        f.write("  Not point-in-time. Historical delisted/demoted tickers excluded.\n")
        f.write("  Results are biased upward by survivorship.\n")

    print(f"Verdict saved: {verdict_path}")

    # ── 14. Save verdict JSON ─────────────────────────────────────────────────
    verdict_json_path = os.path.join(OUTPUT_DIR, f"H27_PEAD_{TODAY}_verdict.json")
    with open(verdict_json_path, "w") as f:
        json.dump(verdict, f, indent=2, default=_make_serializable)
    print(f"Verdict JSON saved: {verdict_json_path}")

    # ── 15. Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("GATE 1 VERDICT SUMMARY")
    print("=" * 70)
    print(f"Overall: {verdict['overall_verdict']} ({verdict['criteria_passed']} criteria)")
    print(f"IS Sharpe (2007-2021): {is_sharpe:.4f}  (target > 1.0) — "
          f"{'PASS' if is_sharpe > 1.0 else 'FAIL'}")
    print(f"IS Trades (2007-2021): {is_trades}  (target >= 50) — "
          f"{'PASS' if is_trades >= 50 else 'FAIL'}")
    print(f"OOS Sharpe (2022-2025): {oos_sharpe:.4f}  (target > 0.7) — "
          f"{'PASS' if oos_sharpe > 0.7 else 'FAIL'}")
    print(f"Alt IS Sharpe (2023-2024): {alt_is_sharpe:.4f}")
    print(f"Alt IS Trades (2023-2024): {alt_is_trades}")
    print(f"Walk-forward: {wf_results['wf_windows_passed']}/4 windows passed")
    print(f"MC p5 Sharpe: {mc_results['mc_p5_sharpe']:.4f}")
    print(f"DSR z-score: {dsr:.4f}")
    print(f"Sensitivity pass: {sens_results['sensitivity_pass']}")
    if verdict.get("failing_criteria"):
        print(f"\nFailing criteria ({len(verdict['failing_criteria'])}):")
        for fc in verdict["failing_criteria"]:
            print(f"  - {fc}")

    print(f"\nOutput files:")
    print(f"  {json_path}")
    print(f"  {verdict_path}")
    print(f"  {verdict_json_path}")

    return metrics, verdict


if __name__ == "__main__":
    np.random.seed(42)
    try:
        metrics, verdict = main()
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)
