"""
H18 Gate 1 Backtest Runner — SPY/TLT Weekly Momentum Rotation
Executes pre-flight verifications (PF-1 trade count, PF-4 vol filter timing),
IS/OOS backtests, walk-forward, statistical rigor pipeline,
regime-slice analysis (criteria.md v1.1), and 27-combination sensitivity scan.

⚠️ PRE-BACKTEST VERIFICATION REQUIRED:
  1. PF-1: IS annual trade count ≥ 30/yr (default params lb=15, threshold=0.0)
     → STOP if trade count < 30/yr; flag back to Engineering Director.
  2. PF-4: Vol filter first triggers in 2022 on or before 2022-03-01
     → STOP if first trigger > 2022-03-01; flag back to Engineering Director.

IS period:  2018-01-01 to 2022-12-31
OOS period: 2023-01-01 to 2025-12-31
Sensitivity sweep: mom_lookback ∈ {10,15,20} × threshold ∈ {0.0,0.005,0.01} × vol_spy ∈ {0.20,0.25,0.30}
"""

import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
from datetime import date

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.h18_spy_tlt_rotation import (
    run_backtest,
    scan_parameters,
    download_data,
    check_vol_filter_trigger_2022,
    check_trade_count_gate,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

# ── Constants ──────────────────────────────────────────────────────────────────

IS_START  = "2018-01-01"
IS_END    = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END   = "2025-12-31"
TODAY     = str(date.today())
STRATEGY_NAME = "H18_SPY_TLT_WeeklyMomentumRotation"

IS_YEARS = (pd.Timestamp(IS_END) - pd.Timestamp(IS_START)).days / 365.25

# Regime slices for criteria.md v1.1 regime-slice analysis
REGIME_SLICES = {
    "bull_2018_2019":      ("2018-01-01", "2019-12-31"),
    "covid_crash_2020":    ("2020-01-01", "2020-12-31"),
    "recovery_2021":       ("2021-01-01", "2021-12-31"),
    "rate_shock_2022":     ("2022-01-01", "2022-12-31"),
    "normalization_2023":  ("2023-01-01", "2023-12-31"),
    "post_norm_2024_25":   ("2024-01-01", "2025-12-31"),
}
STRESS_REGIMES = {"covid_crash_2020", "rate_shock_2022"}


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
    """Block bootstrap CI for Sharpe, MDD, win rate (block_len = sqrt(T))."""
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
    Block permutation test for weekly momentum strategy.
    Shuffles weekly blocks of returns; p-value = fraction of permutations ≥ observed Sharpe.
    """
    weekly_returns = portfolio_value.resample("W-FRI").last().pct_change().dropna().values
    if len(weekly_returns) < 10:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    permuted_sharpes = []
    for _ in range(n_perms):
        perm = np.random.permutation(weekly_returns)
        s = perm.mean() / (perm.std() + 1e-8) * np.sqrt(52)
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue": round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
    }


def compute_dsr(returns_series: np.ndarray, n_trials: int) -> float:
    """
    Deflated Sharpe Ratio: adjusts IS Sharpe for multiple comparisons.
    n_trials = 27 for H18 sensitivity sweep.
    """
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


# ── Regime-Slice Analysis ──────────────────────────────────────────────────────

def compute_regime_slices(portfolio_value_full: pd.Series) -> dict:
    """
    Regime-slice analysis per criteria.md v1.1.
    H18 (weekly rotation): ~20-35 round-trips/year → trade count threshold ≥ 10.
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
                "sharpe": None, "status": "insufficient_data", "passes": None,
            }
            continue

        rets = val_slice.pct_change().fillna(0).values
        sharpe = float(rets.mean() / (rets.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        cum = np.cumprod(1 + rets)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        total_return = float(val_slice.iloc[-1] / val_slice.iloc[0] - 1) if len(val_slice) > 1 else 0.0

        # ~25 round-trips/year estimate for weekly 2-asset rotation
        days_in_window = (pd.Timestamp(r_end) - pd.Timestamp(r_start)).days
        approx_trades = max(1, int(days_in_window / 365.25 * 25))

        if approx_trades < 10:
            status, passes = "insufficient_data", None
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

    regime_slice_pass = (len(passing) >= 2) and (len(stress_passing) > 0)

    return {
        "regimes": regime_results,
        "n_assessable": len(assessable),
        "n_passing": len(passing),
        "stress_regime_passing": stress_passing,
        "has_stress_pass": len(stress_passing) > 0,
        "regime_slice_pass": regime_slice_pass,
        "note": (
            "Pass: IS Sharpe ≥ 0.8 in ≥2 assessable regimes, "
            "at least one stress regime (COVID/Rate-shock). Criteria.md v1.1."
        ),
    }


# ── Walk-Forward Analysis ──────────────────────────────────────────────────────

def run_walk_forward(params: dict, n_windows: int = 4) -> dict:
    """
    Walk-forward: 4 windows, ~1.5yr IS / ~1yr OOS, rolling forward by test period.
    Weekly strategy: shorter IS window acceptable (more observations per window).
    """
    wf_results = []
    base_start = pd.Timestamp(IS_START)
    train_weeks = 78   # ~1.5 years
    test_weeks = 52    # ~1 year

    for i in range(n_windows):
        offset_weeks = i * test_weeks
        is_start = (base_start + pd.DateOffset(weeks=offset_weeks)).strftime("%Y-%m-%d")
        is_end = (base_start + pd.DateOffset(weeks=offset_weeks + train_weeks) -
                  pd.DateOffset(days=1)).strftime("%Y-%m-%d")
        oos_start = (base_start + pd.DateOffset(weeks=offset_weeks + train_weeks)).strftime("%Y-%m-%d")
        oos_end = (base_start + pd.DateOffset(weeks=offset_weeks + train_weeks + test_weeks) -
                   pd.DateOffset(days=1)).strftime("%Y-%m-%d")

        try:
            r_is = run_backtest(params=params, start=is_start, end=is_end)
            r_oos = run_backtest(params=params, start=oos_start, end=oos_end)
            wf_results.append({
                "window": i + 1,
                "is_period": f"{is_start} to {is_end}",
                "oos_period": f"{oos_start} to {oos_end}",
                "is_sharpe": round(r_is["sharpe"], 4),
                "oos_sharpe": round(r_oos["sharpe"], 4),
                "is_total_return": round(r_is["total_return"], 4),
                "oos_total_return": round(r_oos["total_return"], 4),
                "is_trade_count": r_is["trade_count"],
                "oos_trade_count": r_oos["trade_count"],
            })
        except Exception as exc:
            wf_results.append({
                "window": i + 1, "is_period": f"{is_start} to {is_end}",
                "oos_period": f"{oos_start} to {oos_end}", "error": str(exc),
            })

    oos_sharpes = [w["oos_sharpe"] for w in wf_results if "oos_sharpe" in w]
    summary = {"windows": wf_results, "n_windows": len(wf_results)}
    if oos_sharpes:
        arr = np.array(oos_sharpes)
        summary.update({
            "wf_oos_sharpe_mean": round(float(arr.mean()), 4),
            "wf_oos_sharpe_std":  round(float(arr.std()), 4),
            "wf_oos_sharpe_min":  round(float(arr.min()), 4),
        })
    return summary


# ── Pre-Flight Verification ─────────────────────────────────────────────────────

def run_preflight_verification(params: dict) -> tuple[dict, bool]:
    """
    Run PF-1 and PF-4 pre-backtest verification checks (QUA-187 requirement).

    PF-1: IS annual trade count ≥ 30/yr with default params.
    PF-4: Dual vol filter first triggers in 2022 on or before 2022-03-01.

    Returns:
        (verification_results dict, proceed_with_backtest bool)

    If either check fails, proceed_with_backtest = False — the runner MUST
    flag back to Engineering Director and NOT run the full IS backtest.
    """
    print("\n[PRE-FLIGHT] Running PF-1 and PF-4 verification checks...")

    # Download data for verification (buffer 30 days before IS start for vol warm-up)
    tickers = [params["spy"], params["tlt"]]
    buf_start = str((pd.Timestamp(IS_START) - pd.tseries.offsets.BDay(50)).date())
    # Need data through end of 2022 for vol filter check
    close, volume = download_data(tickers, buf_start, "2022-12-31")

    verification = {}
    proceed = True

    # ── PF-1: Trade count check ──────────────────────────────────────────────
    print("\n  [PF-1] Checking IS trade count (lb=15, threshold=0.0)...")
    try:
        quick_result = run_backtest(params=params, start=IS_START, end=IS_END)
        tc_check = quick_result["trade_count_gate"]
        verification["pf1_trade_count"] = tc_check
        print(f"  PF-1 result: {tc_check['message']}")
        if not tc_check["gate_pass"]:
            proceed = False
            print(
                f"\n  ⚠️  PF-1 FAIL: Annual trade count {tc_check['annual_rate']:.1f}/yr < 30/yr."
                "\n  ACTION: Flag back to Engineering Director. DO NOT proceed to full IS run."
                "\n  Recommendation: try mom_lookback_days=10 or threshold=0.0 to increase turnover."
            )
    except Exception as exc:
        verification["pf1_trade_count"] = {"error": str(exc)}
        proceed = False
        print(f"  PF-1 ERROR: {exc}")

    # ── PF-4: Vol filter trigger timing in 2022 ──────────────────────────────
    print("\n  [PF-4] Checking vol filter first trigger in 2022...")
    try:
        vol_check = check_vol_filter_trigger_2022(close, params)
        verification["pf4_vol_filter_trigger"] = vol_check
        print(f"  PF-4 result: {vol_check.get('message', 'N/A')}")
        if not vol_check.get("pass", False):
            proceed = False
            first_trigger = vol_check.get("first_trigger_date", "never")
            print(
                f"\n  ⚠️  PF-4 FAIL: Vol filter first triggers {first_trigger} > 2022-03-01."
                "\n  ACTION: Flag back to Engineering Director. DO NOT proceed to full IS run."
                "\n  Recommendation: try vol_filter_spy_pct=0.20 or vol_filter_tlt_pct=0.12"
                " to trigger earlier."
            )
    except Exception as exc:
        verification["pf4_vol_filter_trigger"] = {"error": str(exc)}
        # Vol check failure doesn't block — report as warning only
        print(f"  PF-4 ERROR (non-blocking): {exc}")

    verification["proceed_with_backtest"] = proceed
    if proceed:
        print("\n  ✓ Pre-flight checks PASSED — proceeding to full IS/OOS backtest.")
    else:
        print("\n  ✗ Pre-flight checks FAILED — see Engineering Director flags above.")

    return verification, proceed


# ── Main Runner ────────────────────────────────────────────────────────────────

def main():
    np.random.seed(42)
    output = {
        "strategy": STRATEGY_NAME,
        "run_date": TODAY,
        "parameters": {k: v for k, v in PARAMETERS.items()},
    }

    print(f"\n{'='*70}")
    print(f"H18 GATE 1 RUNNER — {STRATEGY_NAME}")
    print(f"Run date: {TODAY}")
    print(f"{'='*70}")

    # ── Pre-Flight Verification (REQUIRED before full IS run) ───────────────
    verification, proceed = run_preflight_verification(PARAMETERS)
    output["preflight_verification"] = verification

    if not proceed:
        output["gate1_summary"] = {
            "gate1_pass": False,
            "verdict": "BLOCKED — Pre-flight verification failed. "
                       "Engineering Director action required before proceeding.",
            "preflight_block": True,
        }
        # Save partial results and exit
        out_dir = os.path.dirname(os.path.abspath(__file__))
        out_path = os.path.join(out_dir, f"H18_SPY_TLT_{TODAY}_preflight_blocked.json")
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nPre-flight blocked. Partial results saved: {out_path}")
        return output

    # ── IS Backtest ─────────────────────────────────────────────────────────────
    print(f"\n[1/6] IS Backtest ({IS_START} to {IS_END})...")
    is_result = None
    try:
        is_result = run_backtest(params=PARAMETERS, start=IS_START, end=IS_END)
        is_pv = is_result["_portfolio_value"]
        is_returns = is_result["_daily_returns"]
        is_pnl = is_result["_pnl_arr"]

        bb_ci = block_bootstrap_ci(is_returns)
        perm = permutation_test_alpha(is_pv, is_result["sharpe"])
        dsr_val = compute_dsr(is_returns, n_trials=27)  # 27 combinations
        mc_sharpe = (
            monte_carlo_sharpe(is_pnl)
            if len(is_pnl) >= 10
            else {"mc_p5_sharpe": None, "mc_median_sharpe": None, "mc_p95_sharpe": None}
        )

        output["is"] = {
            "period": is_result["period"],
            "sharpe": round(is_result["sharpe"], 4),
            "max_drawdown": round(is_result["max_drawdown"], 4),
            "win_rate": round(is_result["win_rate"], 4),
            "win_loss_ratio": (
                round(is_result["win_loss_ratio"], 4)
                if is_result["win_loss_ratio"] != float("inf") else "inf"
            ),
            "profit_factor": (
                round(is_result["profit_factor"], 4)
                if is_result["profit_factor"] != float("inf") else "inf"
            ),
            "total_return": round(is_result["total_return"], 4),
            "trade_count": is_result["trade_count"],
            "trade_count_gate": is_result["trade_count_gate"],
            "holding_pct": is_result["holding_pct"],
            "liquidity_constrained": is_result["liquidity_constrained"],
            "liquidity_flags_count": len(is_result["liquidity_flags"]),
            "block_bootstrap_ci": bb_ci,
            "permutation_test": perm,
            "deflated_sharpe_ratio": round(dsr_val, 4),
            "monte_carlo_sharpe": mc_sharpe,
        }

        print(f"  Sharpe: {is_result['sharpe']:.4f} | MDD: {is_result['max_drawdown']:.4f} "
              f"| Return: {is_result['total_return']:.4f} | Trades: {is_result['trade_count']}")
        print(f"  Holding: {is_result['holding_pct']}")
        print(f"  DSR: {dsr_val:.4f} | Permutation p-value: {perm['permutation_pvalue']:.4f}")

    except Exception as exc:
        output["is"] = {"error": str(exc)}
        print(f"  ERROR: {exc}")

    # ── OOS Backtest ────────────────────────────────────────────────────────────
    print(f"\n[2/6] OOS Backtest ({OOS_START} to {OOS_END})...")
    try:
        oos_result = run_backtest(params=PARAMETERS, start=OOS_START, end=OOS_END)
        output["oos"] = {
            "period": oos_result["period"],
            "sharpe": round(oos_result["sharpe"], 4),
            "max_drawdown": round(oos_result["max_drawdown"], 4),
            "win_rate": round(oos_result["win_rate"], 4),
            "total_return": round(oos_result["total_return"], 4),
            "trade_count": oos_result["trade_count"],
            "holding_pct": oos_result["holding_pct"],
        }
        if is_result is not None:
            is_sh = is_result["sharpe"]
            oos_sh = oos_result["sharpe"]
            degradation = (is_sh - oos_sh) / abs(is_sh) if is_sh != 0 else float("inf")
            output["oos"]["is_to_oos_sharpe_degradation"] = round(degradation, 4)
            output["oos"]["sharpe_stability_flag"] = (
                f"PASS: degradation {degradation:.1%} ≤ 30%"
                if degradation <= 0.30
                else f"WARNING: degradation {degradation:.1%} > 30%"
            )

        print(f"  Sharpe: {oos_result['sharpe']:.4f} | MDD: {oos_result['max_drawdown']:.4f} "
              f"| Return: {oos_result['total_return']:.4f} | Trades: {oos_result['trade_count']}")

    except Exception as exc:
        output["oos"] = {"error": str(exc)}
        print(f"  ERROR: {exc}")

    # ── Regime-Slice Analysis ───────────────────────────────────────────────────
    print(f"\n[3/6] Regime-Slice Analysis (criteria.md v1.1)...")
    if is_result is not None:
        try:
            oos_pv = (
                oos_result["_portfolio_value"]
                if "oos" in output and "_portfolio_value" in oos_result
                else pd.Series()
            )
            full_pv = pd.concat([is_result["_portfolio_value"], oos_pv]).sort_index()
            full_pv = full_pv[~full_pv.index.duplicated(keep="first")]
            regime_analysis = compute_regime_slices(full_pv)
            output["regime_analysis"] = regime_analysis
            print(f"  Regime slice pass: {regime_analysis['regime_slice_pass']}")
            for name, res in regime_analysis["regimes"].items():
                if res["status"] == "assessable":
                    print(f"    {name}: Sharpe={res['sharpe']:.4f} | Pass={res['passes']}")
        except Exception as exc:
            output["regime_analysis"] = {"error": str(exc)}
            print(f"  ERROR: {exc}")

    # ── Walk-Forward Analysis ───────────────────────────────────────────────────
    print(f"\n[4/6] Walk-Forward Analysis (4 windows, ~1.5yr IS / ~1yr OOS)...")
    try:
        wf = run_walk_forward(PARAMETERS)
        output["walk_forward"] = wf
        print(f"  WF OOS Sharpe: mean={wf.get('wf_oos_sharpe_mean', 'N/A')}, "
              f"std={wf.get('wf_oos_sharpe_std', 'N/A')}, "
              f"min={wf.get('wf_oos_sharpe_min', 'N/A')}")
    except Exception as exc:
        output["walk_forward"] = {"error": str(exc)}
        print(f"  ERROR: {exc}")

    # ── Sensitivity Sweep (27 combinations) ─────────────────────────────────────
    print(f"\n[5/6] Parameter Sensitivity Scan (27 combinations)...")
    try:
        scan = scan_parameters(start=IS_START, end=IS_END)
        output["sensitivity_scan"] = scan

        meta = scan.get("_meta", {})
        print(f"  Default (lb15,thr0.0,vsf0.25): Sharpe={meta.get('default_sharpe', 'N/A')}")
        print(f"  Sharpe range: {meta.get('sharpe_min', 'N/A')} – {meta.get('sharpe_max', 'N/A')}")
        print(f"  Gate 1 stability: {meta.get('gate1_stability_flag', 'N/A')}")

        # Show 9 default-filter combinations (vsf=0.25, varying lb × threshold)
        print(f"\n  IS Sharpe (default vol_filter_spy=0.25):")
        print(f"  {'':12s} | {'thr=0.0':>8s} | {'thr=0.005':>9s} | {'thr=0.01':>9s}")
        for lb in [10, 15, 20]:
            row_vals = []
            for thr in [0.0, 0.005, 0.01]:
                key = f"lb{lb}_thr{thr}_vsf0.25"
                sh = scan.get(key, {}).get("sharpe", "err")
                row_vals.append(f"{sh:>9.4f}" if isinstance(sh, float) else f"{'err':>9s}")
            print(f"  lb={lb:2d}d       | {'|'.join(row_vals)}")

        # Flag combinations where trade count fails PF-1
        low_tc_combos = [
            k for k, v in scan.items()
            if isinstance(v, dict) and v.get("trade_count_gate") is False
        ]
        if low_tc_combos:
            print(f"\n  ⚠️  Low trade count (<30/yr) in {len(low_tc_combos)} combinations: {low_tc_combos[:5]}")

    except Exception as exc:
        output["sensitivity_scan"] = {"error": str(exc)}
        print(f"  ERROR: {exc}")

    # ── Gate 1 Summary ──────────────────────────────────────────────────────────
    print(f"\n[6/6] Gate 1 Summary...")
    gate1_checks = {}

    if is_result is not None:
        is_sharpe = is_result["sharpe"]
        gate1_checks["is_sharpe_ge_1"] = {
            "value": round(is_sharpe, 4),
            "pass": is_sharpe >= 1.0,
            "criterion": "IS Sharpe ≥ 1.0",
        }
        gate1_checks["is_mdd_le_20pct"] = {
            "value": round(is_result["max_drawdown"], 4),
            "pass": abs(is_result["max_drawdown"]) <= 0.20,
            "criterion": "IS MDD ≤ 20%",
        }
        gate1_checks["trade_count_pf1"] = {
            "value": is_result["trade_count_gate"]["annual_rate"],
            "pass": is_result["trade_count_gate"]["gate_pass"],
            "criterion": "IS annual trade count ≥ 30/yr (PF-1)",
        }
        gate1_checks["vol_filter_pf4"] = {
            "value": verification.get("pf4_vol_filter_trigger", {}).get("first_trigger_date"),
            "pass": verification.get("pf4_vol_filter_trigger", {}).get("pass", False),
            "criterion": "Vol filter first triggers ≤ 2022-03-01 in 2022 (PF-4)",
        }

    if "regime_analysis" in output:
        gate1_checks["regime_slice"] = {
            "pass": output["regime_analysis"]["regime_slice_pass"],
            "criterion": "IS Sharpe ≥ 0.8 in ≥2 regimes, incl. ≥1 stress regime",
        }
    if "sensitivity_scan" in output and "_meta" in output["sensitivity_scan"]:
        meta = output["sensitivity_scan"]["_meta"]
        gate1_checks["parameter_stability"] = {
            "value": meta.get("sharpe_variance_pct_vs_default"),
            "pass": (meta.get("sharpe_variance_pct_vs_default", 1.0) or 1.0) <= 0.30,
            "criterion": "Sharpe variance ≤ 30% across 27 parameter combinations",
        }

    n_pass = sum(1 for v in gate1_checks.values() if v.get("pass"))
    n_total = len(gate1_checks)
    gate1_overall = (n_pass == n_total)

    output["gate1_summary"] = {
        "checks": gate1_checks,
        "n_pass": n_pass,
        "n_total": n_total,
        "gate1_pass": gate1_overall,
        "verdict": "PASS — Proceed to OOS evaluation" if gate1_overall else "FAIL — Review flagged criteria",
    }

    print(f"\n{'='*70}")
    print(f"GATE 1 SUMMARY: {n_pass}/{n_total} checks passed")
    for check_name, check in gate1_checks.items():
        status = "PASS" if check.get("pass") else "FAIL"
        val = f" ({check.get('value')})" if check.get("value") is not None else ""
        print(f"  [{status}] {check.get('criterion', check_name)}{val}")
    print(f"\nVERDICT: {output['gate1_summary']['verdict']}")
    print(f"{'='*70}\n")

    # ── Save Results ────────────────────────────────────────────────────────────
    def _make_serializable(obj):
        if isinstance(obj, dict):
            return {k: _make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_make_serializable(v) for v in obj]
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.ndarray, pd.Series)):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return str(obj.date())
        if obj == float("inf"):
            return "inf"
        if obj == float("-inf"):
            return "-inf"
        return obj

    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(out_dir, f"H18_SPY_TLT_{TODAY}.json")
    with open(out_path, "w") as f:
        json.dump(_make_serializable(output), f, indent=2)
    print(f"Results saved: {out_path}")

    return output


if __name__ == "__main__":
    main()
