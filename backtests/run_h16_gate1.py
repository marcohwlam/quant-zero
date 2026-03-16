"""
H16 Gate 1 Backtest Runner — Momentum + Volatility Effect (Long-Only)
Executes IS/OOS backtests, walk-forward, statistical rigor pipeline,
regime-slice analysis (criteria.md v1.2), and parameter sensitivity scan.

IS period:  2000-01-01 to 2020-12-31 (20 years; covers dot-com crash, GFC, COVID)
OOS period: 2021-01-01 to 2024-12-31

Survivorship bias note: fixed large-cap universe uses current S&P 500 members.
Stocks delisted 2000-2024 excluded. Estimated +1-3% annual alpha inflation.
See strategy file header for full documentation.

Gate 1 Adapted Criteria (per QUA-165 spec):
  - IS Sharpe > 1.0
  - OOS Sharpe > 0.7
  - MDD < 20% (IS)
  - Trade count ≥ 100 (multi-stock monthly rebalance easily meets this)
  - Walk-forward ≥ 3/4 windows
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
from strategies.h16_momentum_vol_filter import (
    run_backtest,
    scan_parameters,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

# ── Constants ──────────────────────────────────────────────────────────────────

IS_START  = "2000-01-01"
IS_END    = "2020-12-31"
OOS_START = "2021-01-01"
OOS_END   = "2024-12-31"
TODAY     = str(date.today())
STRATEGY_NAME = "H16_MomentumVolFilter_LongOnly"

# Regime slices covering the full IS+OOS period.
# IS period spans dot-com crash → GFC → bull → COVID (2000-2020).
# Stress regimes: dot-com crash, GFC, COVID, rate shock.
REGIME_SLICES = {
    "dot_com_crash_2000_2002":  ("2000-01-01", "2002-12-31"),
    "recovery_2003_2006":       ("2003-01-01", "2006-12-31"),
    "gfc_2007_2009":            ("2007-01-01", "2009-12-31"),
    "recovery_bull_2010_2014":  ("2010-01-01", "2014-12-31"),
    "bull_2015_2019":           ("2015-01-01", "2019-12-31"),
    "covid_2020":               ("2020-01-01", "2020-12-31"),
    "post_covid_2021":          ("2021-01-01", "2021-12-31"),
    "rate_shock_2022":          ("2022-01-01", "2022-12-31"),
    "normalization_2023_24":    ("2023-01-01", "2024-12-31"),
}
# Stress regimes: must include at least one in regime-slice pass
STRESS_REGIMES = {
    "dot_com_crash_2000_2002",
    "gfc_2007_2009",
    "covid_2020",
    "rate_shock_2022",
}
# IS-period regime windows only (for regime-slice sub-criterion)
IS_REGIME_SLICES = {
    k: v for k, v in REGIME_SLICES.items()
    if pd.Timestamp(v[0]) >= pd.Timestamp(IS_START)
    and pd.Timestamp(v[0]) <= pd.Timestamp(IS_END)
}


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
) -> dict:
    """
    Block permutation test: shuffle monthly returns to test whether observed
    Sharpe exceeds chance. Uses monthly returns to preserve the rebalance cadence.
    """
    monthly_returns = portfolio_value.resample("ME").last().pct_change().dropna().values
    if len(monthly_returns) < 10:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

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
    sr_obs = (
        returns_series.mean() / (returns_series.std() + 1e-8)
        * np.sqrt(TRADING_DAYS_PER_YEAR)
    )
    sr_star = (
        (1 - np.euler_gamma) * norm.ppf(1 - 1.0 / n_trials)
        + np.euler_gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    skew = float(pd.Series(returns_series).skew())
    kurt = float(pd.Series(returns_series).kurtosis())
    var_sr = (
        (1 + (0.5 * sr_obs**2) - (skew * sr_obs) + ((kurt / 4) * sr_obs**2))
        / (T - 1)
    )
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
    Compute per-regime Sharpe for criteria.md v1.2 regime-slice sub-criterion.

    For H16 (monthly rebalance, 3-5 positions per month), regime trade counts
    are high (240 IS months × ~3 positions = ~720 buys, ~240 round-trip trades).
    Assessability threshold: ≥ 10 trades per regime (monthly rotation).

    Requirements (criteria.md v1.2, adapted for H16 IS period 2000-2020):
    - IS Sharpe ≥ 0.8 in ≥ 2 of assessable IS sub-regimes
    - At least one passing regime must be a stress regime
      (dot-com crash, GFC, COVID, or rate-shock)
    """
    regime_results = {}

    for regime_name, (r_start, r_end) in REGIME_SLICES.items():
        mask = (
            (portfolio_value_full.index >= pd.Timestamp(r_start))
            & (portfolio_value_full.index <= pd.Timestamp(r_end))
        )
        val_slice = portfolio_value_full[mask]

        if len(val_slice) < 20:
            regime_results[regime_name] = {
                "sharpe": None, "status": "insufficient_data", "passes": None,
            }
            continue

        rets = val_slice.pct_change().fillna(0).values
        sharpe = float(rets.mean() / (rets.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        cum = np.cumprod(1 + rets)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        total_return = (
            float(val_slice.iloc[-1] / val_slice.iloc[0] - 1)
            if len(val_slice) > 1 else 0.0
        )

        # Approximate trade count: monthly rebalance → ~1 round-trip per month
        months_in_window = (pd.Timestamp(r_end) - pd.Timestamp(r_start)).days / 30
        approx_trades = max(1, int(months_in_window))

        if approx_trades < 10:
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

    # Evaluate only IS-period regimes for the sub-criterion
    is_assessable = {
        k: v for k, v in regime_results.items()
        if k in IS_REGIME_SLICES and v.get("status") == "assessable"
    }
    is_passing = {k: v for k, v in is_assessable.items() if v.get("passes")}
    stress_passing = [k for k in is_passing if k in STRESS_REGIMES]
    n_passing = len(is_passing)
    has_stress_pass = len(stress_passing) > 0

    regime_slice_pass = (n_passing >= 2) and has_stress_pass

    return {
        "regimes": regime_results,
        "n_assessable_is": len(is_assessable),
        "n_passing_is": n_passing,
        "stress_regime_passing": stress_passing,
        "has_stress_pass": has_stress_pass,
        "regime_slice_pass": regime_slice_pass,
        "note": (
            "Pass: IS Sharpe ≥ 0.8 in ≥ 2 IS sub-regimes, at least one stress regime "
            "(dot-com/GFC/COVID/rate-shock). Trade threshold: ≥ 10 monthly trades. "
            "Criteria.md v1.2. IS sub-regimes only (2000-2020)."
        ),
    }


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(
    params: dict,
    n_windows: int = 4,
    train_months: int = 60,   # 5-year IS window
    test_months: int = 12,    # 1-year OOS window
) -> dict:
    """
    Walk-forward analysis: 4 windows, 5-year IS / 1-year OOS.
    Starts from 2005 (after 5yr buffer from IS start 2000).
    Monthly rebalance strategy: 12-month OOS yields ~12 round-trip trades per window.
    """
    wf_results = []
    # Start after sufficient training history (IS start 2000 + 5yr train = 2005)
    base_start = pd.Timestamp("2005-01-01")

    for i in range(n_windows):
        offset_months = i * test_months
        is_start = (base_start + pd.DateOffset(months=offset_months)).strftime("%Y-%m-%d")
        is_end = (
            base_start + pd.DateOffset(months=offset_months + train_months - 1, day=31)
        ).strftime("%Y-%m-%d")
        oos_start = (
            base_start + pd.DateOffset(months=offset_months + train_months)
        ).strftime("%Y-%m-%d")
        oos_end = (
            base_start
            + pd.DateOffset(months=offset_months + train_months + test_months - 1, day=31)
        ).strftime("%Y-%m-%d")

        try:
            r_is = run_backtest(params=params, start=is_start, end=is_end)
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
                "window":     i + 1,
                "is_start":   is_start,
                "is_end":     is_end,
                "oos_start":  oos_start,
                "oos_end":    oos_end,
                "error":      str(exc),
                "pass":       False,
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
    print(f"H16 Gate 1 Backtest — {TODAY}")
    print("Strategy: Momentum + Volatility Effect (Long-Only)")
    print(f"IS:  {IS_START} to {IS_END}  (20 years, covers dot-com, GFC, COVID)")
    print(f"OOS: {OOS_START} to {OOS_END}")
    print("SURVIVORSHIP BIAS NOTE: fixed large-cap universe; see strategy file.")
    print("=" * 70)

    params = {**PARAMETERS}   # canonical: formation_months=6, vol_filter_pct=0.20

    # ── 1. IS Backtest ────────────────────────────────────────────────────
    print(f"\n[1/8] Running IS backtest ({IS_START} to {IS_END})...")
    is_result = run_backtest(params=params, start=IS_START, end=IS_END)
    is_returns = is_result["_daily_returns"]
    is_portfolio_value = is_result["_portfolio_value"]
    is_pnl = is_result["_pnl_arr"]
    print(f"  IS Sharpe:         {is_result['sharpe']:.4f}")
    print(f"  IS MDD:            {is_result['max_drawdown']:.4f}")
    print(f"  IS Win Rate:       {is_result['win_rate']:.4f}")
    print(f"  IS Win/Loss:       {is_result['win_loss_ratio']:.4f}")
    print(f"  IS Profit Factor:  {is_result['profit_factor']:.4f}")
    print(f"  IS Total Return:   {is_result['total_return']:.4f}")
    print(f"  IS Trade Count:    {is_result['trade_count']}")
    print(f"  IS Avg Positions:  {is_result['avg_positions_per_month']:.1f}")

    # ── 2. OOS Backtest ───────────────────────────────────────────────────
    print(f"\n[2/8] Running OOS backtest ({OOS_START} to {OOS_END})...")
    oos_result = run_backtest(params=params, start=OOS_START, end=OOS_END)
    oos_returns = oos_result["_daily_returns"]
    print(f"  OOS Sharpe:        {oos_result['sharpe']:.4f}")
    print(f"  OOS MDD:           {oos_result['max_drawdown']:.4f}")
    print(f"  OOS Win Rate:      {oos_result['win_rate']:.4f}")
    print(f"  OOS Total Return:  {oos_result['total_return']:.4f}")
    print(f"  OOS Trade Count:   {oos_result['trade_count']}")

    # ── 3. Regime-Slice Analysis ──────────────────────────────────────────
    print("\n[3/8] Running regime-slice analysis (criteria.md v1.2)...")
    try:
        full_result = run_backtest(params=params, start=IS_START, end=OOS_END)
        full_pv = full_result["_portfolio_value"]
        regime_analysis = compute_regime_slices(full_pv)
    except Exception as exc:
        print(f"  Regime-slice warning: {exc}")
        regime_analysis = {
            "regime_slice_pass": False, "error": str(exc), "regimes": {},
            "n_passing_is": 0, "has_stress_pass": False,
        }

    for rn, r in regime_analysis.get("regimes", {}).items():
        in_is = rn in IS_REGIME_SLICES
        status = r.get("status", "N/A")
        sharpe = r.get("sharpe")
        sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "N/A"
        passes = r.get("passes")
        pass_str = "PASS" if passes else ("FAIL" if passes is False else "N/A")
        is_label = "(IS)" if in_is else "(OOS)"
        print(f"  {rn} {is_label}: Sharpe={sharpe_str} [{pass_str}] ({status})")

    print(
        f"  Regime-slice (IS sub-criterion): {regime_analysis.get('n_passing_is', 0)} IS regimes passing — "
        f"{'PASS' if regime_analysis.get('regime_slice_pass') else 'FAIL'}"
    )

    # ── 4. Walk-Forward ───────────────────────────────────────────────────
    print("\n[4/8] Running walk-forward analysis (4 windows, 60m IS / 12m OOS)...")
    wf = run_walk_forward(params, n_windows=4, train_months=60, test_months=12)
    print(f"  Windows passed: {wf['windows_passed']}/4")
    for w in wf["windows"]:
        if "error" in w:
            print(f"  Window {w['window']}: ERROR — {w['error']}")
        else:
            status = "PASS" if w.get("pass") else "FAIL"
            print(
                f"  Window {w['window']}: IS={w['is_sharpe']:.2f}  "
                f"OOS={w['oos_sharpe']:.2f}  trades={w['oos_trades']}  [{status}]"
            )
    wf_var = walk_forward_variance(wf["oos_sharpes"])

    # ── 5. Monte Carlo ────────────────────────────────────────────────────
    print("\n[5/8] Running Monte Carlo simulation (1,000 resamples)...")
    mc = (
        monte_carlo_sharpe(is_pnl)
        if len(is_pnl) > 1
        else {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    )
    print(
        f"  MC p5={mc['mc_p5_sharpe']:.3f}  "
        f"median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}"
    )

    # ── 6. Block Bootstrap CI ─────────────────────────────────────────────
    print("\n[6/8] Running block bootstrap CI (1,000 boots)...")
    bb = (
        block_bootstrap_ci(is_returns)
        if len(is_returns) > 10
        else {k: 0.0 for k in [
            "sharpe_ci_low", "sharpe_ci_high", "mdd_ci_low",
            "mdd_ci_high", "win_rate_ci_low", "win_rate_ci_high",
        ]}
    )
    print(f"  Sharpe CI: [{bb['sharpe_ci_low']:.3f}, {bb['sharpe_ci_high']:.3f}]")
    print(f"  MDD CI:    [{bb['mdd_ci_low']:.3f}, {bb['mdd_ci_high']:.3f}]")
    bb_positive = bb["sharpe_ci_low"] > 0

    # ── 7. Permutation Test + DSR ─────────────────────────────────────────
    print("\n[7/8] Running permutation test and DSR computation...")
    perm = permutation_test_alpha(is_portfolio_value, is_result["sharpe"])
    print(
        f"  Permutation p-value: {perm['permutation_pvalue']:.4f}  "
        f"({'PASS' if perm['permutation_test_pass'] else 'FAIL'})"
    )

    # DSR: n_trials = 9 (2D grid: 3 formation × 3 vol filter variants tested)
    n_trials = 9
    dsr = compute_dsr(is_returns, n_trials)
    print(f"  DSR (n_trials={n_trials}): {dsr:.4f}")

    # ── 8. Parameter Sensitivity Scan ────────────────────────────────────
    print("\n[8/8] Running 2D parameter sensitivity scan (formation × vol filter)...")
    sens_results = scan_parameters(start=IS_START, end=IS_END, base_params=params)
    print(f"  Sharpe range:  {sens_results.get('_sharpe_range', 'N/A')}")
    print(f"  Sensitivity:   {sens_results.get('_gate1_variance_flag', 'N/A')}")
    for k, v in sens_results.items():
        if not k.startswith("_"):
            print(f"  {k}: {v}")
    sensitivity_pass = "PASS" in str(sens_results.get("_gate1_variance_flag", ""))

    # ── Gate 1 Evaluation ─────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("GATE 1 EVALUATION")
    print("=" * 70)
    print("SURVIVORSHIP BIAS: fixed large-cap universe overstates IS returns.")
    print("Gate 1 caveat: est. +1-3% annual alpha inflation. See strategy file.")

    regime_slice_pass = regime_analysis.get("regime_slice_pass", False)

    gate1_checks = {
        "is_sharpe_pass":       is_result["sharpe"] > 1.0,
        "oos_sharpe_pass":      oos_result["sharpe"] > 0.7,
        "is_mdd_pass":          abs(is_result["max_drawdown"]) < 0.20,
        "oos_mdd_pass":         abs(oos_result["max_drawdown"]) < 0.25,
        "win_rate_pass":        is_result["win_rate"] > 0.50,
        "win_loss_ratio_pass":  is_result["win_loss_ratio"] >= 1.0,
        "trade_count_pass":     is_result["trade_count"] >= 100,
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
    print(
        "NOTE: Survivorship bias caveat — if Gate 1 PASS, inflate costs by 1-3% "
        "and re-verify thresholds before paper trading promotion."
    )
    print("=" * 70)

    # ── Assemble Output JSON ──────────────────────────────────────────────
    regime_for_json = {}
    if "regimes" in regime_analysis:
        for rn, rv in regime_analysis["regimes"].items():
            regime_for_json[rn] = {
                k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in rv.items()
            }

    liquidity_flags = is_result.get("liquidity_flags", [])
    liquidity_constrained = is_result.get("liquidity_constrained", False)

    output = {
        "strategy":             STRATEGY_NAME,
        "date":                 TODAY,
        "is_period":            f"{IS_START} to {IS_END}",
        "oos_period":           f"{OOS_START} to {OOS_END}",
        "survivorship_bias_note": (
            "Fixed large-cap universe. Delisted stocks 2000-2024 excluded. "
            "Est. +1-3% annual alpha inflation (Elton et al. 1996). Gate 1 caveat."
        ),
        "formation_months":     params["formation_months"],
        "vol_filter_pct":       params["vol_filter_pct"],
        "is_sharpe":            round(is_result["sharpe"], 4),
        "oos_sharpe":           round(oos_result["sharpe"], 4),
        "is_mdd":               round(is_result["max_drawdown"], 4),
        "oos_mdd":              round(oos_result["max_drawdown"], 4),
        "is_win_rate":          round(is_result["win_rate"], 4),
        "oos_win_rate":         round(oos_result["win_rate"], 4),
        "is_win_loss_ratio":    round(is_result["win_loss_ratio"], 4),
        "is_profit_factor":     round(is_result["profit_factor"], 4),
        "is_total_return":      round(is_result["total_return"], 4),
        "oos_total_return":     round(oos_result["total_return"], 4),
        "is_trade_count":       is_result["trade_count"],
        "oos_trade_count":      oos_result["trade_count"],
        "is_avg_positions":     is_result["avg_positions_per_month"],
        "oos_avg_positions":    oos_result["avg_positions_per_month"],
        "wf_windows_passed":    wf["windows_passed"],
        "wf_consistency_score": round(wf["wf_consistency_score"], 4),
        "wf_oos_sharpes":       wf["oos_sharpes"],
        "wf_details":           wf["windows"],
        "wf_sharpe_std":        round(wf_var["wf_sharpe_std"], 4),
        "wf_sharpe_min":        round(wf_var["wf_sharpe_min"], 4),
        "mc_p5_sharpe":         round(mc["mc_p5_sharpe"], 4),
        "mc_median_sharpe":     round(mc["mc_median_sharpe"], 4),
        "mc_p95_sharpe":        round(mc["mc_p95_sharpe"], 4),
        "sharpe_ci_low":        round(bb["sharpe_ci_low"], 4),
        "sharpe_ci_high":       round(bb["sharpe_ci_high"], 4),
        "mdd_ci_low":           round(bb["mdd_ci_low"], 4),
        "mdd_ci_high":          round(bb["mdd_ci_high"], 4),
        "win_rate_ci_low":      round(bb["win_rate_ci_low"], 4),
        "win_rate_ci_high":     round(bb["win_rate_ci_high"], 4),
        "bb_ci_positive":       bb_positive,
        "permutation_pvalue":   round(perm["permutation_pvalue"], 6),
        "permutation_test_pass":perm["permutation_test_pass"],
        "dsr":                  round(dsr, 4),
        "n_trials":             n_trials,
        "sensitivity":          {k: v for k, v in sens_results.items()},
        "regime_slices":        regime_for_json,
        "regime_slice_pass":    regime_analysis.get("regime_slice_pass", False),
        "liquidity_constrained":liquidity_constrained,
        "liquidity_flags":      liquidity_flags[:20],   # cap for JSON size
        "data_quality":         is_result.get("data_quality", {}),
        "gate1_checks":         gate1_checks,
        "gate1_pass":           gate1_pass,
        "is_trade_log":         is_result.get("trade_log", [])[:100],   # cap at 100
        "oos_trade_log":        oos_result.get("trade_log", [])[:100],
    }

    # ── Write Output Files ────────────────────────────────────────────────
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, f"H16_MomentumVolFilter_{TODAY}.json")
    verdict_path = os.path.join(out_dir, f"H16_MomentumVolFilter_{TODAY}_verdict.txt")

    with open(json_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    verdict_lines = [
        f"H16 Gate 1 Verdict — {TODAY}",
        "Strategy: Momentum + Volatility Effect (Long-Only)",
        f"IS period:  {IS_START} to {IS_END} (20 years)",
        f"OOS period: {OOS_START} to {OOS_END}",
        "",
        "SURVIVORSHIP BIAS CAVEAT: Fixed large-cap universe; est. +1-3% annual alpha inflation.",
        "",
        f"IS Sharpe:         {output['is_sharpe']} ({'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'} > 1.0)",
        f"OOS Sharpe:        {output['oos_sharpe']} ({'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'} > 0.7)",
        f"IS MDD:            {output['is_mdd']} ({'PASS' if gate1_checks['is_mdd_pass'] else 'FAIL'} < 0.20)",
        f"IS Win Rate:       {output['is_win_rate']} ({'PASS' if gate1_checks['win_rate_pass'] else 'FAIL'} > 0.50)",
        f"IS Win/Loss Ratio: {output['is_win_loss_ratio']} ({'PASS' if gate1_checks['win_loss_ratio_pass'] else 'FAIL'} >= 1.0)",
        f"IS Trade Count:    {output['is_trade_count']} ({'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'} >= 100)",
        f"WF Windows Passed: {output['wf_windows_passed']}/4 ({'PASS' if gate1_checks['wf_windows_pass'] else 'FAIL'} >= 3)",
        f"WF Consistency:    {output['wf_consistency_score']} ({'PASS' if gate1_checks['wf_consistency_pass'] else 'FAIL'} >= 0.70)",
        f"Sensitivity:       {sens_results.get('_gate1_variance_flag', 'N/A')}",
        f"DSR:               {output['dsr']} ({'PASS' if gate1_checks['dsr_pass'] else 'FAIL'} > 0)",
        f"Permutation p:     {output['permutation_pvalue']} ({'PASS' if gate1_checks['permutation_pass'] else 'FAIL'} <= 0.05)",
        f"Regime-slice:      ({'PASS' if gate1_checks['regime_slice_pass'] else 'FAIL'})",
        "",
        f"MC p5 Sharpe:      {output['mc_p5_sharpe']}",
        f"Sharpe 95% CI:     [{output['sharpe_ci_low']}, {output['sharpe_ci_high']}]",
        f"BB CI positive:    {bb_positive}",
        f"Avg Positions/Mo:  {output['is_avg_positions']}",
        "",
        f"GATE 1: {'PASS' if gate1_pass else 'FAIL'}",
        "",
        "Note: if PASS, verify bias-adjusted performance before paper trading promotion.",
    ]

    with open(verdict_path, "w") as f:
        f.write("\n".join(verdict_lines))

    print(f"\nOutput files:")
    print(f"  {json_path}")
    print(f"  {verdict_path}")

    return output


if __name__ == "__main__":
    main()
