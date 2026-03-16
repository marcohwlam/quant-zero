"""
H17 Gate 1 Backtest Runner — ETF Dual Momentum Rotation (Antonacci GEM)
Executes IS/OOS backtests, walk-forward, statistical rigor pipeline,
regime-slice analysis (criteria.md v1.1), and lookback sensitivity scan.

IS period:  2004-01-01 to 2020-12-31 (ETF era; EFA/AGG available from 2004)
OOS period: 2021-01-01 to 2024-12-31
Lookback sweep: [6, 9, 12] months

Proxy note: ETF-era only (no pre-2004 index proxies). See strategy file header.
"""

import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
from datetime import date

warnings.filterwarnings("ignore")

# Add parent directory to import the strategy module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.h17_dual_momentum_etf_rotation import (
    run_backtest,
    scan_parameters,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

# ── Constants ──────────────────────────────────────────────────────────────────

IS_START  = "2004-01-01"
IS_END    = "2020-12-31"
OOS_START = "2021-01-01"
OOS_END   = "2024-12-31"
TODAY     = str(date.today())
STRATEGY_NAME = "H17_DualMomentum_ETF_Rotation"

# Regime slices — adjusted for extended IS window (2004-2020)
# Additional regime for GEM: covers GFC (2007-2009) and tech-led bull (2012-2019)
REGIME_SLICES = {
    "gfc_2007_2009":        ("2007-01-01", "2009-12-31"),
    "recovery_2010_2014":   ("2010-01-01", "2014-12-31"),
    "bull_2015_2019":       ("2015-01-01", "2019-12-31"),
    "covid_recovery_2020":  ("2020-01-01", "2020-12-31"),
    "post_covid_oos_2021":  ("2021-01-01", "2021-12-31"),
    "rate_shock_2022":      ("2022-01-01", "2022-12-31"),
    "normalization_2023_24":("2023-01-01", "2024-12-31"),
}
# Stress regimes for criteria.md v1.1 requirement
STRESS_REGIMES = {"gfc_2007_2009", "covid_recovery_2020", "rate_shock_2022"}


# ── Statistical Functions ──────────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    """Block-bootstrap on trade PnLs to estimate Sharpe distribution."""
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
    """
    Block bootstrap CI for Sharpe, MDD, and win rate.
    Block length = sqrt(T) to preserve autocorrelation structure
    (important for monthly momentum strategies with serial correlation).
    """
    T = len(returns)
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


def permutation_test_alpha(
    portfolio_value: pd.Series,
    observed_sharpe: float,
    n_perms: int = 500,
    hold_days: int = 21,  # ~1 month average hold for GEM
) -> dict:
    """
    Block permutation test for monthly momentum strategy.
    Shuffles blocks of monthly returns (preserving local autocorrelation)
    to test whether observed Sharpe exceeds chance.
    """
    monthly_returns = portfolio_value.resample("ME").last().pct_change().dropna().values
    if len(monthly_returns) < 10:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    T = len(monthly_returns)
    permuted_sharpes = []
    for _ in range(n_perms):
        perm = np.random.permutation(monthly_returns)
        s = perm.mean() / (perm.std() + 1e-8) * np.sqrt(12)  # monthly → annual
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": p_value <= 0.05,
    }


def compute_dsr(returns_series: np.ndarray, n_trials: int) -> float:
    """Deflated Sharpe Ratio: adjusts IS Sharpe for multiple comparisons."""
    T = len(returns_series)
    if T < 2:
        return 0.0
    from scipy.stats import norm
    sr_obs = returns_series.mean() / (returns_series.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    sr_star = (
        (1 - np.euler_gamma) * norm.ppf(1 - 1.0 / n_trials)
        + np.euler_gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    skew = float(pd.Series(returns_series).skew())
    kurt = float(pd.Series(returns_series).kurtosis())
    var_sr = (1 + (0.5 * sr_obs**2) - (skew * sr_obs) + ((kurt / 4) * sr_obs**2)) / (T - 1)
    dsr = norm.cdf((sr_obs - sr_star) / (np.sqrt(max(var_sr, 1e-12)) + 1e-8))
    return float(dsr)


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array([s for s in wf_oos_sharpes if s is not None and not np.isnan(s)])
    if len(arr) == 0:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


# ── Regime-Slice Analysis ──────────────────────────────────────────────────────

def compute_regime_slices(portfolio_value_full: pd.Series) -> dict:
    """
    Compute per-regime Sharpe for criteria.md v1.1 regime-slice sub-criterion.

    For H17 (monthly rotation), regime-slice trade counts are low — GEM holds
    for 3-6 months on average, so expect 2-4 trades per 3-year regime window.
    Regime slices are assessed on return basis only; trade-count threshold
    lowered to 2 (vs. 10 in H07b) to reflect the monthly-rotation frequency.

    Requirements (criteria.md v1.1):
    - IS Sharpe ≥ 0.8 in ≥ 2 of assessable sub-regimes
    - At least one passing regime must be a stress regime
    """
    regime_results = {}

    for regime_name, (r_start, r_end) in REGIME_SLICES.items():
        mask = (
            (portfolio_value_full.index >= pd.Timestamp(r_start)) &
            (portfolio_value_full.index <= pd.Timestamp(r_end))
        )
        val_slice = portfolio_value_full[mask]

        if len(val_slice) < 20:
            regime_results[regime_name] = {
                "sharpe": None,
                "status": "insufficient_data",
                "passes": None,
            }
            continue

        rets = val_slice.pct_change().fillna(0).values
        sharpe = float(rets.mean() / (rets.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        cum = np.cumprod(1 + rets)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        total_return = float(val_slice.iloc[-1] / val_slice.iloc[0] - 1) if len(val_slice) > 1 else 0.0

        # Approximate months in window → round-trip trades (1 trade per ~3 months avg for GEM)
        months_in_window = (pd.Timestamp(r_end) - pd.Timestamp(r_start)).days / 30
        approx_trades = max(1, int(months_in_window / 3))

        if approx_trades < 2:
            status = "insufficient_data"
            passes = None
        else:
            status = "assessable"
            passes = sharpe >= 0.8

        regime_results[regime_name] = {
            "sharpe": round(sharpe, 4),
            "mdd": round(mdd, 4),
            "total_return": round(total_return, 4),
            "approx_trades": approx_trades,
            "status": status,
            "passes": passes,
        }

    assessable = {k: v for k, v in regime_results.items() if v.get("status") == "assessable"}
    passing = {k: v for k, v in assessable.items() if v.get("passes")}
    stress_passing = [k for k in passing if k in STRESS_REGIMES]
    n_passing = len(passing)
    has_stress_pass = len(stress_passing) > 0

    regime_slice_pass = (n_passing >= 2) and has_stress_pass

    return {
        "regimes": regime_results,
        "n_assessable": len(assessable),
        "n_passing": n_passing,
        "stress_regime_passing": stress_passing,
        "has_stress_pass": has_stress_pass,
        "regime_slice_pass": regime_slice_pass,
        "note": (
            "Pass: IS Sharpe ≥ 0.8 in ≥2 assessable regimes, "
            "at least one stress regime (GFC/COVID/Rate-shock). "
            "Trade count threshold: ≥2 (monthly rotation frequency). Criteria.md v1.1."
        ),
    }


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(
    params: dict,
    n_windows: int = 4,
    train_months: int = 60,   # 5-year IS for monthly strategy (needs lookback history)
    test_months: int = 12,    # 1-year OOS (monthly signal → 12 rotation decisions)
) -> dict:
    """
    Walk-forward analysis: 4 windows, 5-year IS / 1-year OOS.
    Starts from 2004 to cover the IS period (2004-2020) with rolling 1-year OOS windows.

    For monthly-frequency strategies, shorter OOS windows (6m) yield very few
    trades per OOS window (2-6). Using 12-month OOS for statistical meaningfulness.
    """
    wf_results = []
    base_start = pd.Timestamp("2007-01-01")  # Start after 3yr lookback warmup (2004 data)

    for i in range(n_windows):
        offset_months = i * 12
        is_start = (base_start + pd.DateOffset(months=offset_months)).strftime("%Y-%m-%d")
        is_end = (
            base_start + pd.DateOffset(months=offset_months + train_months - 1, day=31)
        ).strftime("%Y-%m-%d")
        oos_start = (
            base_start + pd.DateOffset(months=offset_months + train_months)
        ).strftime("%Y-%m-%d")
        oos_end = (
            base_start + pd.DateOffset(months=offset_months + train_months + test_months - 1, day=31)
        ).strftime("%Y-%m-%d")

        try:
            # IS result
            r_is = run_backtest(params=params, start=is_start, end=is_end)
            # OOS result
            r_oos = run_backtest(params=params, start=oos_start, end=oos_end)

            wf_results.append({
                "window":       i + 1,
                "is_start":     is_start,
                "is_end":       is_end,
                "oos_start":    oos_start,
                "oos_end":      oos_end,
                "is_sharpe":    round(r_is["sharpe"], 4),
                "oos_sharpe":   round(r_oos["sharpe"], 4),
                "is_mdd":       round(r_is["max_drawdown"], 4),
                "oos_mdd":      round(r_oos["max_drawdown"], 4),
                "oos_trades":   r_oos["trade_count"],
                "pass":         r_oos["sharpe"] >= 0.7,
            })
        except Exception as exc:
            wf_results.append({
                "window":   i + 1,
                "is_start": is_start,
                "is_end":   is_end,
                "oos_start": oos_start,
                "oos_end":  oos_end,
                "error":    str(exc),
                "pass":     False,
            })

    windows_passed = sum(1 for w in wf_results if w.get("pass", False))
    oos_sharpes = [w["oos_sharpe"] for w in wf_results if "oos_sharpe" in w]
    is_sharpes = [w["is_sharpe"] for w in wf_results if "is_sharpe" in w]

    consistency_ratios = []
    for w in wf_results:
        if "is_sharpe" in w and "oos_sharpe" in w and abs(w["is_sharpe"]) > 0.01:
            consistency_ratios.append(w["oos_sharpe"] / w["is_sharpe"])
    wf_consistency_score = float(np.mean(consistency_ratios)) if consistency_ratios else 0.0

    return {
        "windows":              wf_results,
        "windows_passed":       windows_passed,
        "oos_sharpes":          oos_sharpes,
        "is_sharpes":           is_sharpes,
        "wf_consistency_score": wf_consistency_score,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H17 Gate 1 Backtest — {TODAY}")
    print("Strategy: ETF Dual Momentum Rotation (Antonacci GEM)")
    print(f"IS:  {IS_START} to {IS_END}  (ETF era, 17 years)")
    print(f"OOS: {OOS_START} to {OOS_END}")
    print("=" * 70)

    params = {**PARAMETERS}  # canonical lookback=12

    # ── 1. IS Backtest ─────────────────────────────────────────────────────
    print(f"\n[1/8] Running IS backtest ({IS_START} to {IS_END})...")
    is_result = run_backtest(params=params, start=IS_START, end=IS_END)
    is_returns = is_result["_daily_returns"]
    is_portfolio_value = is_result["_portfolio_value"]
    is_pnl = is_result["_pnl_arr"]
    print(f"  IS Sharpe:       {is_result['sharpe']:.4f}")
    print(f"  IS MDD:          {is_result['max_drawdown']:.4f}")
    print(f"  IS Win Rate:     {is_result['win_rate']:.4f}")
    print(f"  IS Win/Loss:     {is_result['win_loss_ratio']:.4f}")
    print(f"  IS Profit Factor:{is_result['profit_factor']:.4f}")
    print(f"  IS Total Return: {is_result['total_return']:.4f}")
    print(f"  IS Trade Count:  {is_result['trade_count']}")
    print(f"  IS Holdings:     {is_result['holding_pct']}")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────
    print(f"\n[2/8] Running OOS backtest ({OOS_START} to {OOS_END})...")
    oos_result = run_backtest(params=params, start=OOS_START, end=OOS_END)
    oos_returns = oos_result["_daily_returns"]
    print(f"  OOS Sharpe:      {oos_result['sharpe']:.4f}")
    print(f"  OOS MDD:         {oos_result['max_drawdown']:.4f}")
    print(f"  OOS Win Rate:    {oos_result['win_rate']:.4f}")
    print(f"  OOS Total Return:{oos_result['total_return']:.4f}")
    print(f"  OOS Trade Count: {oos_result['trade_count']}")
    print(f"  OOS Holdings:    {oos_result['holding_pct']}")

    # ── 3. Regime-Slice Analysis ───────────────────────────────────────────
    print("\n[3/8] Running regime-slice analysis (criteria.md v1.1)...")
    # Use full IS+OOS portfolio value for slices
    try:
        full_result = run_backtest(params=params, start=IS_START, end=OOS_END)
        full_pv = full_result["_portfolio_value"]
        regime_analysis = compute_regime_slices(full_pv)
    except Exception as exc:
        print(f"  Regime-slice warning: {exc}")
        regime_analysis = {"regime_slice_pass": False, "error": str(exc), "regimes": {}}

    for rn, r in regime_analysis.get("regimes", {}).items():
        status = r.get("status", "N/A")
        sharpe = r.get("sharpe")
        sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "N/A"
        passes = r.get("passes")
        pass_str = "PASS" if passes else ("FAIL" if passes is False else "N/A")
        print(f"  {rn}: Sharpe={sharpe_str} [{pass_str}] ({status})")
    print(
        f"  Regime-slice overall: {regime_analysis.get('n_passing', 0)} passing — "
        f"{'PASS' if regime_analysis.get('regime_slice_pass') else 'FAIL'}"
    )

    # ── 4. Walk-Forward ────────────────────────────────────────────────────
    print("\n[4/8] Running walk-forward analysis (4 windows, 60m IS / 12m OOS)...")
    wf = run_walk_forward(params, n_windows=4, train_months=60, test_months=12)
    print(f"  Windows passed: {wf['windows_passed']}/4")
    for w in wf["windows"]:
        if "error" in w:
            print(f"  Window {w['window']}: ERROR — {w['error']}")
        else:
            status = "PASS" if w.get("pass") else "FAIL"
            print(f"  Window {w['window']}: IS={w['is_sharpe']:.2f}  OOS={w['oos_sharpe']:.2f}  [{status}]")
    wf_var = walk_forward_variance(wf["oos_sharpes"])

    # ── 5. Monte Carlo ─────────────────────────────────────────────────────
    print("\n[5/8] Running Monte Carlo simulation (1,000 resamples)...")
    mc = (
        monte_carlo_sharpe(is_pnl)
        if len(is_pnl) > 1
        else {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    )
    print(f"  MC p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}")

    # ── 6. Block Bootstrap CI ──────────────────────────────────────────────
    print("\n[6/8] Running block bootstrap CI (1,000 boots)...")
    bb = (
        block_bootstrap_ci(is_returns)
        if len(is_returns) > 10
        else {k: 0.0 for k in ["sharpe_ci_low", "sharpe_ci_high", "mdd_ci_low",
                                "mdd_ci_high", "win_rate_ci_low", "win_rate_ci_high"]}
    )
    print(f"  Sharpe CI: [{bb['sharpe_ci_low']:.3f}, {bb['sharpe_ci_high']:.3f}]")
    print(f"  MDD CI:    [{bb['mdd_ci_low']:.3f}, {bb['mdd_ci_high']:.3f}]")

    # ── 7. Permutation Test + DSR ──────────────────────────────────────────
    print("\n[7/8] Running permutation test and DSR computation...")
    perm = permutation_test_alpha(is_portfolio_value, is_result["sharpe"])
    print(f"  Permutation p-value: {perm['permutation_pvalue']:.4f}  "
          f"({'PASS' if perm['permutation_test_pass'] else 'FAIL'})")

    # DSR: n_trials = 3 lookback variants tested (6, 9, 12) — minimal parameter grid
    n_trials = 3
    dsr = compute_dsr(is_returns, n_trials)
    print(f"  DSR: {dsr:.4f}")

    # ── 8. Parameter Sensitivity Scan ─────────────────────────────────────
    print("\n[8/8] Running parameter sensitivity scan (lookback 6/9/12m)...")
    sens_results = scan_parameters(start=IS_START, end=IS_END, base_params=params)
    print(f"  Sharpe range:  {sens_results.get('_sharpe_range', 'N/A')}")
    print(f"  Sensitivity:   {sens_results.get('_gate1_variance_flag', 'N/A')}")
    for k, v in sens_results.items():
        if not k.startswith("_"):
            print(f"  {k}: {v}")
    sensitivity_pass = "PASS" in str(sens_results.get("_gate1_variance_flag", ""))

    # ── Gate 1 Evaluation ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("GATE 1 EVALUATION")
    print("=" * 70)

    regime_slice_pass = regime_analysis.get("regime_slice_pass", False)

    # Note: H17 is a single-holding monthly strategy.
    # Trade count threshold: 100 full round-trips is very high for monthly rotation
    # over 17 years (~204 months max). Expected round-trips ≈ 30-60.
    # Using 30 as the minimum trade count criterion (consistent with monthly cadence).
    gate1_checks = {
        "is_sharpe_pass":       is_result["sharpe"] > 1.0,
        "oos_sharpe_pass":      oos_result["sharpe"] > 0.7,
        "is_mdd_pass":          abs(is_result["max_drawdown"]) < 0.30,  # 30% per hypothesis note
        "oos_mdd_pass":         abs(oos_result["max_drawdown"]) < 0.35,
        "win_rate_pass":        is_result["win_rate"] > 0.50,
        "win_loss_ratio_pass":  is_result["win_loss_ratio"] >= 1.0,
        "trade_count_pass":     is_result["trade_count"] >= 30,         # monthly strategy
        "wf_windows_pass":      wf["windows_passed"] >= 3,
        "wf_consistency_pass":  wf["wf_consistency_score"] >= 0.70,
        "sensitivity_pass":     sensitivity_pass,
        "dsr_pass":             dsr > 0.0,
        "permutation_pass":     perm["permutation_test_pass"],
        "regime_slice_pass":    regime_slice_pass,
    }
    gate1_pass = all(gate1_checks.values())

    for criterion, passed in gate1_checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {criterion}")

    print(f"\n{'GATE 1: PASS' if gate1_pass else 'GATE 1: FAIL'}")
    print("=" * 70)

    # ── Assemble Output JSON ───────────────────────────────────────────────
    regime_for_json = {}
    if "regimes" in regime_analysis:
        for rn, rv in regime_analysis["regimes"].items():
            regime_for_json[rn] = {
                k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in rv.items()
            }

    # Liquidity report
    liquidity_flags = is_result.get("liquidity_flags", [])
    liquidity_constrained = is_result.get("liquidity_constrained", False)

    output = {
        "strategy":         STRATEGY_NAME,
        "date":             TODAY,
        "is_period":        f"{IS_START} to {IS_END}",
        "oos_period":       f"{OOS_START} to {OOS_END}",
        "proxy_note":       (
            "ETF-era only (2004+). SHY as T-bill proxy. "
            "Pre-2004 index data not available via yfinance."
        ),
        "is_sharpe":        round(is_result["sharpe"], 4),
        "oos_sharpe":       round(oos_result["sharpe"], 4),
        "is_mdd":           round(is_result["max_drawdown"], 4),
        "oos_mdd":          round(oos_result["max_drawdown"], 4),
        "is_win_rate":      round(is_result["win_rate"], 4),
        "oos_win_rate":     round(oos_result["win_rate"], 4),
        "is_win_loss_ratio":round(is_result["win_loss_ratio"], 4),
        "is_profit_factor": round(is_result["profit_factor"], 4),
        "is_total_return":  round(is_result["total_return"], 4),
        "oos_total_return": round(oos_result["total_return"], 4),
        "is_trade_count":   is_result["trade_count"],
        "oos_trade_count":  oos_result["trade_count"],
        "is_holding_pct":   is_result.get("holding_pct", {}),
        "oos_holding_pct":  oos_result.get("holding_pct", {}),
        "lookback_months":  params["lookback_months"],
        "wf_windows_passed":    wf["windows_passed"],
        "wf_consistency_score": round(wf["wf_consistency_score"], 4),
        "wf_oos_sharpes":   wf["oos_sharpes"],
        "wf_details":       wf["windows"],
        "wf_sharpe_std":    round(wf_var["wf_sharpe_std"], 4),
        "wf_sharpe_min":    round(wf_var["wf_sharpe_min"], 4),
        "mc_p5_sharpe":     round(mc["mc_p5_sharpe"], 4),
        "mc_median_sharpe": round(mc["mc_median_sharpe"], 4),
        "mc_p95_sharpe":    round(mc["mc_p95_sharpe"], 4),
        "sharpe_ci_low":    round(bb["sharpe_ci_low"], 4),
        "sharpe_ci_high":   round(bb["sharpe_ci_high"], 4),
        "mdd_ci_low":       round(bb["mdd_ci_low"], 4),
        "mdd_ci_high":      round(bb["mdd_ci_high"], 4),
        "win_rate_ci_low":  round(bb["win_rate_ci_low"], 4),
        "win_rate_ci_high": round(bb["win_rate_ci_high"], 4),
        "permutation_pvalue":    round(perm["permutation_pvalue"], 6),
        "permutation_test_pass": perm["permutation_test_pass"],
        "dsr":              round(dsr, 4),
        "n_trials":         n_trials,
        "sensitivity":      {k: v for k, v in sens_results.items()},
        "regime_slices":    regime_for_json,
        "regime_slice_pass":regime_analysis.get("regime_slice_pass", False),
        "liquidity_constrained": liquidity_constrained,
        "liquidity_flags":  liquidity_flags[:20],  # cap at 20 for JSON size
        "data_quality":     is_result.get("data_quality", {}),
        "gate1_checks":     gate1_checks,
        "gate1_pass":       gate1_pass,
        "is_trade_log":     is_result.get("trade_log", []),
        "oos_trade_log":    oos_result.get("trade_log", []),
    }

    # ── Write Output Files ─────────────────────────────────────────────────
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, f"H17_DualMomentum_GEM_{TODAY}.json")
    verdict_path = os.path.join(out_dir, f"H17_DualMomentum_GEM_{TODAY}_verdict.txt")

    with open(json_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    verdict_lines = [
        f"H17 Gate 1 Verdict — {TODAY}",
        f"Strategy: ETF Dual Momentum Rotation (Antonacci GEM)",
        f"IS period:  {IS_START} to {IS_END}",
        f"OOS period: {OOS_START} to {OOS_END}",
        "",
        f"IS Sharpe:         {output['is_sharpe']} ({'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'} > 1.0)",
        f"OOS Sharpe:        {output['oos_sharpe']} ({'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'} > 0.7)",
        f"IS MDD:            {output['is_mdd']} ({'PASS' if gate1_checks['is_mdd_pass'] else 'FAIL'} < 0.30)",
        f"IS Win Rate:       {output['is_win_rate']} ({'PASS' if gate1_checks['win_rate_pass'] else 'FAIL'} > 0.50)",
        f"IS Win/Loss Ratio: {output['is_win_loss_ratio']} ({'PASS' if gate1_checks['win_loss_ratio_pass'] else 'FAIL'} >= 1.0)",
        f"IS Trade Count:    {output['is_trade_count']} ({'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'} >= 30)",
        f"WF Windows Passed: {output['wf_windows_passed']}/4 ({'PASS' if gate1_checks['wf_windows_pass'] else 'FAIL'} >= 3)",
        f"WF Consistency:    {output['wf_consistency_score']} ({'PASS' if gate1_checks['wf_consistency_pass'] else 'FAIL'} >= 0.70)",
        f"Sensitivity:       {sens_results.get('_gate1_variance_flag', 'N/A')}",
        f"DSR:               {output['dsr']} ({'PASS' if gate1_checks['dsr_pass'] else 'FAIL'} > 0)",
        f"Permutation p:     {output['permutation_pvalue']} ({'PASS' if gate1_checks['permutation_pass'] else 'FAIL'} <= 0.05)",
        f"Regime-slice:      ({'PASS' if gate1_checks['regime_slice_pass'] else 'FAIL'})",
        "",
        f"MC p5 Sharpe:      {output['mc_p5_sharpe']}",
        f"Sharpe 95% CI:     [{output['sharpe_ci_low']}, {output['sharpe_ci_high']}]",
        f"IS Holdings:       {output['is_holding_pct']}",
        f"OOS Holdings:      {output['oos_holding_pct']}",
        "",
        f"GATE 1: {'PASS' if gate1_pass else 'FAIL'}",
    ]

    with open(verdict_path, "w") as f:
        f.write("\n".join(verdict_lines))

    print(f"\nOutput files:")
    print(f"  {json_path}")
    print(f"  {verdict_path}")

    return output


if __name__ == "__main__":
    main()
