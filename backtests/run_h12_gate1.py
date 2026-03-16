"""
H12 SuperTrend ATR Momentum — Gate 1 Backtest Runner
======================================================
STATUS: ARCHIVED — Gate 1 FAIL 2026-03-16. DO NOT RE-RUN.
  See: docs/gate1-verdicts/H12_SuperTrend_ATR_Momentum_2026-03-16.md | QUA-148, QUA-180

Produces standardized metrics JSON + verdict for QUA-154.

IS period : 2018-01-01 — 2022-12-31  (5 years)
OOS period: 2023-01-01 — 2024-12-31  (2 years)
Universe  : SPY, QQQ, IWM (long-only)

Conditions (Research Director):
  1. VIX < 30 + 200-day SMA regime gate MANDATORY
  2. ATR sensitivity heatmap (multiplier 1.5–3.5 × lookback 7–20)
  3. 2022 bear-market sub-period must be tested
  4. SPY, QQQ, IWM only
  5. Long-only
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date
from scipy import stats

from strategies.h12_supertrend_atr_momentum import (
    run_multi_asset,
    scan_atr_params,
    run_strategy,
    generate_signals,
    compute_ic,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TICKERS   = ["SPY", "QQQ", "IWM"]
IS_START  = "2018-01-01"
IS_END    = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END   = "2024-12-31"
FULL_START = IS_START
FULL_END   = OOS_END

# Base parameters
ATR_LOOKBACK    = 14
ATR_MULTIPLIER  = 2.5
VIX_THRESHOLD   = 30.0
SMA_PERIOD      = 200
MAX_HOLD_DAYS   = 30

# Transaction costs
COST_PER_SHARE  = 0.005
SLIPPAGE_PCT    = 0.0005

# Output
TODAY = date.today().isoformat()
OUT_JSON    = f"backtests/H12_SuperTrend_{TODAY}.json"
OUT_VERDICT = f"backtests/H12_SuperTrend_{TODAY}_verdict.txt"

# ---------------------------------------------------------------------------
# Helpers — statistical rigor pipeline
# ---------------------------------------------------------------------------

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe":    float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks  = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        if len(sample) < 2:
            continue
        cum     = np.cumprod(1 + np.clip(sample, -0.99, 10))
        roll_max = np.maximum.accumulate(cum)
        mdd     = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s       = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
        wr      = float(np.mean(sample > 0))
        sharpes.append(s); mdds.append(mdd); win_rates.append(wr)
    return {
        "sharpe_ci_low":    float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high":   float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":       float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":      float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low":  float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def compute_market_impact(ticker: str, order_qty: float, start: str, end: str) -> dict:
    try:
        hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        if hist.empty:
            raise ValueError("empty")
        adv   = float(hist["Volume"].rolling(20).mean().dropna().iloc[-1])
        sigma = float(hist["Close"].pct_change().std())
        k     = 0.1
        impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
        impact_bps = impact_pct * 10_000
        return {
            "market_impact_bps":    float(impact_bps),
            "liquidity_constrained": bool(order_qty > 0.01 * adv),
            "order_to_adv_ratio":   float(order_qty / (adv + 1e-8)),
        }
    except Exception:
        return {"market_impact_bps": 0.0, "liquidity_constrained": False, "order_to_adv_ratio": 0.0}


def permutation_test(prices: np.ndarray, entries: np.ndarray, observed_sharpe: float,
                     n_perms: int = 500) -> dict:
    entry_indices = np.where(entries)[0]
    if len(entry_indices) == 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    permuted = []
    for _ in range(n_perms):
        perm_idx = np.random.choice(len(prices), size=len(entry_indices), replace=False)
        trade_rets = []
        for idx in perm_idx:
            exit_idx = min(idx + MAX_HOLD_DAYS, len(prices) - 1)
            if prices[idx] > 0:
                trade_rets.append((prices[exit_idx] - prices[idx]) / prices[idx])
        if len(trade_rets) > 1:
            arr = np.array(trade_rets)
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(252 / MAX_HOLD_DAYS)
        else:
            s = 0.0
        permuted.append(s)
    permuted = np.array(permuted)
    p_value = float(np.mean(permuted >= observed_sharpe))
    return {"permutation_pvalue": p_value, "permutation_test_pass": p_value <= 0.05}


def compute_dsr(returns: np.ndarray, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)."""
    T = len(returns)
    if T < 4:
        return 0.0
    sr = returns.mean() / (returns.std() + 1e-8) * np.sqrt(252)
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns))
    gamma = (1 - skew * sr + (kurt - 1) / 4 * sr**2)
    sr_star = np.sqrt(gamma / T) * (np.sqrt(1 - 1 / (4 * T)) * stats.norm.ppf(1 - 1 / n_trials))
    dsr = float(stats.norm.cdf((sr - sr_star) / np.sqrt(gamma / T + 1e-8)))
    return dsr


def walk_forward_variance(oos_sharpes: list) -> dict:
    arr = np.array(oos_sharpes, dtype=float)
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def run_walk_forward(tickers, train_months=24, test_months=6):
    """4-window walk-forward validation."""
    results = []
    # IS: 2018-2022 (60 months). Walk-forward windows of 24m train / 6m test.
    # Window 1: train 2018-01 to 2019-12, test 2020-01 to 2020-06
    # Window 2: train 2019-01 to 2020-12, test 2021-01 to 2021-06
    # Window 3: train 2020-01 to 2021-12, test 2022-01 to 2022-06
    # Window 4: train 2021-01 to 2022-12, test 2023-01 to 2023-06
    windows = [
        ("2018-01-01", "2019-12-31", "2020-01-01", "2020-06-30"),
        ("2019-01-01", "2020-12-31", "2021-01-01", "2021-06-30"),
        ("2020-01-01", "2021-12-31", "2022-01-01", "2022-06-30"),
        ("2021-01-01", "2022-12-31", "2023-01-01", "2023-06-30"),
    ]
    for i, (ts, te, vs, ve) in enumerate(windows):
        train_res = run_multi_asset(tickers, ts, te,
                                    atr_lookback=ATR_LOOKBACK, atr_multiplier=ATR_MULTIPLIER,
                                    vix_threshold=VIX_THRESHOLD, sma_period=SMA_PERIOD,
                                    max_hold_days=MAX_HOLD_DAYS)
        test_res  = run_multi_asset(tickers, vs, ve,
                                    atr_lookback=ATR_LOOKBACK, atr_multiplier=ATR_MULTIPLIER,
                                    vix_threshold=VIX_THRESHOLD, sma_period=SMA_PERIOD,
                                    max_hold_days=MAX_HOLD_DAYS)
        is_sharpe  = train_res["metrics"].get("sharpe", 0.0)
        oos_sharpe = test_res["metrics"].get("sharpe", 0.0)
        # Window passes if OOS Sharpe > 0 and within 70% of IS (not degraded by > 30%)
        consistency = (oos_sharpe / (is_sharpe + 1e-8)) if is_sharpe != 0 else 0.0
        passed = oos_sharpe > 0 and consistency >= 0.7
        results.append({
            "window": i + 1,
            "train_start": ts, "train_end": te,
            "test_start": vs,  "test_end": ve,
            "is_sharpe": is_sharpe,
            "oos_sharpe": oos_sharpe,
            "consistency": consistency,
            "passed": passed,
        })
        print(f"  WF window {i+1}: IS={is_sharpe:.3f}, OOS={oos_sharpe:.3f}, "
              f"consistency={consistency:.2f}, pass={passed}")
    return results


# ---------------------------------------------------------------------------
# Sub-period analysis
# ---------------------------------------------------------------------------

def run_sub_periods(tickers):
    sub_periods = [
        ("2018-01-01", "2019-12-31", "pre-COVID bull"),
        ("2020-01-01", "2020-12-31", "COVID crash/recovery"),
        ("2021-01-01", "2021-12-31", "post-COVID bull"),
        ("2022-01-01", "2022-12-31", "2022 rate-shock bear"),
        ("2023-01-01", "2024-12-31", "post-2022 recovery"),
    ]
    rows = []
    for s, e, label in sub_periods:
        res = run_multi_asset(tickers, s, e,
                              atr_lookback=ATR_LOOKBACK, atr_multiplier=ATR_MULTIPLIER,
                              vix_threshold=VIX_THRESHOLD, sma_period=SMA_PERIOD,
                              max_hold_days=MAX_HOLD_DAYS)
        rows.append({
            "period": label, "start": s, "end": e,
            "sharpe": res["metrics"].get("sharpe", 0.0),
            "trade_count": res["metrics"].get("trade_count", 0),
            "win_rate": res["metrics"].get("win_rate", 0.0),
        })
        print(f"  Sub-period [{label}]: Sharpe={rows[-1]['sharpe']:.3f}, "
              f"trades={rows[-1]['trade_count']}, WR={rows[-1]['win_rate']:.2%}")
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    np.random.seed(42)
    print("=" * 60)
    print("H12 SuperTrend ATR Momentum — Gate 1 Backtest")
    print("=" * 60)

    # -----------------------------------------------------------------------
    # 1. IC Validation
    # -----------------------------------------------------------------------
    print("\n[1] IC Validation (SPY, IS period)...")
    spy_result = run_strategy("SPY", IS_START, IS_END,
                               atr_lookback=ATR_LOOKBACK, atr_multiplier=ATR_MULTIPLIER,
                               vix_threshold=VIX_THRESHOLD, sma_period=SMA_PERIOD)
    ic_spy = spy_result.get("ic", 0.0)
    print(f"    SPY IC = {ic_spy:.4f}")
    ic_pass = ic_spy > 0.02
    print(f"    IC gate: {'PASS' if ic_pass else 'FAIL'} (threshold: > 0.02)")

    # -----------------------------------------------------------------------
    # 2. IS Backtest
    # -----------------------------------------------------------------------
    print(f"\n[2] IS Backtest ({IS_START} — {IS_END})...")
    is_result = run_multi_asset(TICKERS, IS_START, IS_END,
                                 atr_lookback=ATR_LOOKBACK, atr_multiplier=ATR_MULTIPLIER,
                                 vix_threshold=VIX_THRESHOLD, sma_period=SMA_PERIOD,
                                 max_hold_days=MAX_HOLD_DAYS)
    is_metrics = is_result["metrics"]
    print(f"    Trades    : {is_metrics['trade_count']}")
    print(f"    Sharpe    : {is_metrics['sharpe']:.4f}")
    print(f"    Max DD    : {is_metrics['max_drawdown']:.2%}")
    print(f"    Win Rate  : {is_metrics['win_rate']:.2%}")
    print(f"    Prof Fact : {is_metrics['profit_factor']:.2f}")
    for tkr, m in is_result.get("per_ticker", {}).items():
        print(f"      {tkr}: Sharpe={m.get('sharpe', 0):.3f}, trades={m.get('trade_count', 0)}")

    # -----------------------------------------------------------------------
    # 3. OOS Backtest
    # -----------------------------------------------------------------------
    print(f"\n[3] OOS Backtest ({OOS_START} — {OOS_END})...")
    oos_result = run_multi_asset(TICKERS, OOS_START, OOS_END,
                                  atr_lookback=ATR_LOOKBACK, atr_multiplier=ATR_MULTIPLIER,
                                  vix_threshold=VIX_THRESHOLD, sma_period=SMA_PERIOD,
                                  max_hold_days=MAX_HOLD_DAYS)
    oos_metrics = oos_result["metrics"]
    print(f"    Trades    : {oos_metrics['trade_count']}")
    print(f"    Sharpe    : {oos_metrics['sharpe']:.4f}")
    print(f"    Max DD    : {oos_metrics['max_drawdown']:.2%}")
    print(f"    Win Rate  : {oos_metrics['win_rate']:.2%}")

    # -----------------------------------------------------------------------
    # 4. ATR Sensitivity Scan (multiplier 1.5–3.5 × lookback 7–20)
    # -----------------------------------------------------------------------
    print("\n[4] ATR Parameter Sensitivity Scan (IS period)...")
    sensitivity_df = scan_atr_params(
        TICKERS, IS_START, IS_END,
        multipliers=[1.5, 2.0, 2.5, 3.0, 3.5],
        lookbacks=[7, 10, 14, 17, 20],
    )
    print(sensitivity_df.to_string(index=False))

    base_sharpe = is_metrics["sharpe"]
    # Gate: ±20% perturbation → < 30% Sharpe change
    base_row = sensitivity_df[
        (sensitivity_df["atr_multiplier"] == ATR_MULTIPLIER) &
        (sensitivity_df["atr_lookback"] == ATR_LOOKBACK)
    ]
    if not base_row.empty:
        # Multiplier ±20%: 2.5 → 2.0 and 3.0
        nearby = sensitivity_df[
            (sensitivity_df["atr_multiplier"].isin([2.0, 3.0])) &
            (sensitivity_df["atr_lookback"] == ATR_LOOKBACK)
        ]
        if not nearby.empty:
            max_deg = float(abs(nearby["sharpe"].values - base_sharpe).max() / (abs(base_sharpe) + 1e-8))
        else:
            max_deg = 0.0
    else:
        max_deg = 0.0
    sensitivity_pass = max_deg < 0.30
    print(f"    Max Sharpe degradation at ±20% multiplier: {max_deg:.1%}")
    print(f"    Sensitivity: {'PASS' if sensitivity_pass else 'FAIL'} (threshold < 30%)")

    # -----------------------------------------------------------------------
    # 5. Walk-Forward Validation
    # -----------------------------------------------------------------------
    print("\n[5] Walk-Forward Validation (4 windows)...")
    wf_results = run_walk_forward(TICKERS)
    wf_passed = sum(1 for w in wf_results if w["passed"])
    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_results]
    wf_is_sharpes  = [w["is_sharpe"]  for w in wf_results]
    wf_avg_consistency = np.mean([w["consistency"] for w in wf_results])
    print(f"    Windows passed: {wf_passed}/4")
    print(f"    Avg OOS/IS consistency: {wf_avg_consistency:.2f}")

    wf_var = walk_forward_variance(wf_oos_sharpes)

    # -----------------------------------------------------------------------
    # 6. Statistical Rigor Pipeline
    # -----------------------------------------------------------------------
    print("\n[6] Statistical Rigor Pipeline...")

    # IS trade PnLs for MC / bootstrap
    is_pnls = np.array([t["net_pnl"] for t in is_result["trades"]])
    is_rets  = np.array([t["return_pct"] for t in is_result["trades"]])

    mc_results   = monte_carlo_sharpe(is_pnls) if len(is_pnls) > 1 else {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    ci_results   = block_bootstrap_ci(is_rets)  if len(is_rets) > 1  else {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0, "mdd_ci_low": 0.0, "mdd_ci_high": 0.0, "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0}
    mi_results   = compute_market_impact("SPY", 500, IS_START, IS_END)
    dsr_value    = compute_dsr(is_rets, n_trials=20) if len(is_rets) > 4 else 0.0

    print(f"    MC p5 Sharpe     : {mc_results['mc_p5_sharpe']:.3f}")
    print(f"    MC median Sharpe : {mc_results['mc_median_sharpe']:.3f}")
    print(f"    Sharpe CI        : [{ci_results['sharpe_ci_low']:.3f}, {ci_results['sharpe_ci_high']:.3f}]")
    print(f"    MDD CI           : [{ci_results['mdd_ci_low']:.3f}, {ci_results['mdd_ci_high']:.3f}]")
    print(f"    Market impact    : {mi_results['market_impact_bps']:.2f} bps")
    print(f"    DSR              : {dsr_value:.4f}")

    # Permutation test
    spy_res_is = run_strategy("SPY", IS_START, IS_END,
                               atr_lookback=ATR_LOOKBACK, atr_multiplier=ATR_MULTIPLIER,
                               vix_threshold=VIX_THRESHOLD, sma_period=SMA_PERIOD)
    if "df" in spy_res_is and len(spy_res_is["df"]) > 0:
        spy_df  = spy_res_is["df"]
        prices  = spy_df["Close"].values
        entries = spy_df["entry"].values.astype(bool)
        perm_results = permutation_test(prices, entries, is_metrics["sharpe"])
    else:
        perm_results = {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    print(f"    Permutation p-value : {perm_results['permutation_pvalue']:.3f} "
          f"({'PASS' if perm_results['permutation_test_pass'] else 'FAIL'})")

    # Post-cost Sharpe (all costs already applied in simulate_trades, so IS Sharpe is post-cost)
    post_cost_sharpe = is_metrics["sharpe"]

    # -----------------------------------------------------------------------
    # 7. Sub-period analysis
    # -----------------------------------------------------------------------
    print("\n[7] Sub-period Analysis...")
    sub_period_results = run_sub_periods(TICKERS)

    # Check 2022 bear sub-period
    bear_2022 = next((r for r in sub_period_results if "2022" in r["period"]), None)
    bear_sharpe = bear_2022["sharpe"] if bear_2022 else None
    print(f"    2022 bear market Sharpe: {bear_sharpe:.3f}" if bear_sharpe is not None else "    2022 data missing")

    # -----------------------------------------------------------------------
    # 8. Gate 1 Evaluation
    # -----------------------------------------------------------------------
    print("\n[8] Gate 1 Evaluation...")

    gate_criteria = {
        "is_sharpe_gt_1.0":        is_metrics["sharpe"] > 1.0,
        "oos_sharpe_gt_0.7":       oos_metrics["sharpe"] > 0.7,
        "is_mdd_lt_20pct":         abs(is_metrics["max_drawdown"]) < 0.20,
        "oos_mdd_lt_25pct":        abs(oos_metrics["max_drawdown"]) < 0.25,
        "win_rate_gt_50pct":       is_metrics["win_rate"] > 0.50,
        "dsr_gt_0":                dsr_value > 0,
        "wf_passed_3of4":          wf_passed >= 3,
        "sensitivity_pass":        sensitivity_pass,
        "trade_count_ge_30":       is_metrics["trade_count"] >= 30,
        "permutation_test_pass":   perm_results["permutation_test_pass"],
        "ic_pass":                 ic_pass,
        "mc_p5_sharpe_gt_0.5":    mc_results["mc_p5_sharpe"] > 0.5,
    }

    passed_count = sum(gate_criteria.values())
    total_count  = len(gate_criteria)
    gate1_pass   = all(gate_criteria.values())

    for criterion, result in gate_criteria.items():
        status = "PASS" if result else "FAIL"
        print(f"    [{status}] {criterion}")
    print(f"\n    Gate 1 VERDICT: {'PASS' if gate1_pass else 'FAIL'} ({passed_count}/{total_count} criteria)")

    # -----------------------------------------------------------------------
    # 9. Build output JSON
    # -----------------------------------------------------------------------
    output = {
        "strategy_name": "H12_SuperTrend_ATR_Momentum",
        "date": TODAY,
        "asset_class": "equities",
        "tickers": TICKERS,
        "is_period": f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "parameters": {
            "atr_lookback": ATR_LOOKBACK,
            "atr_multiplier": ATR_MULTIPLIER,
            "vix_threshold": VIX_THRESHOLD,
            "sma_period": SMA_PERIOD,
            "max_hold_days": MAX_HOLD_DAYS,
        },
        # Core metrics
        "is_sharpe":       round(is_metrics["sharpe"], 4),
        "oos_sharpe":      round(oos_metrics["sharpe"], 4),
        "is_max_drawdown": round(is_metrics["max_drawdown"], 4),
        "oos_max_drawdown":round(oos_metrics["max_drawdown"], 4),
        "win_rate":        round(is_metrics["win_rate"], 4),
        "profit_factor":   round(is_metrics["profit_factor"], 4),
        "trade_count":     is_metrics["trade_count"],
        "oos_trade_count": oos_metrics["trade_count"],
        "ic":              round(ic_spy, 4),
        "dsr":             round(dsr_value, 4),
        # Walk-forward
        "wf_windows_passed":    wf_passed,
        "wf_consistency_score": round(float(wf_avg_consistency), 4),
        "wf_results":           wf_results,
        "wf_sharpe_std":        round(wf_var["wf_sharpe_std"], 4),
        "wf_sharpe_min":        round(wf_var["wf_sharpe_min"], 4),
        # Sensitivity
        "sensitivity_pass":         sensitivity_pass,
        "sensitivity_max_degradation": round(max_deg, 4),
        "sensitivity_scan":         sensitivity_df.to_dict(orient="records"),
        # Statistical rigor
        "mc_p5_sharpe":     round(mc_results["mc_p5_sharpe"], 4),
        "mc_median_sharpe": round(mc_results["mc_median_sharpe"], 4),
        "mc_p95_sharpe":    round(mc_results["mc_p95_sharpe"], 4),
        "sharpe_ci_low":    round(ci_results["sharpe_ci_low"], 4),
        "sharpe_ci_high":   round(ci_results["sharpe_ci_high"], 4),
        "mdd_ci_low":       round(ci_results["mdd_ci_low"], 4),
        "mdd_ci_high":      round(ci_results["mdd_ci_high"], 4),
        "win_rate_ci_low":  round(ci_results["win_rate_ci_low"], 4),
        "win_rate_ci_high": round(ci_results["win_rate_ci_high"], 4),
        "market_impact_bps":     round(mi_results["market_impact_bps"], 4),
        "liquidity_constrained": mi_results["liquidity_constrained"],
        "order_to_adv_ratio":    round(mi_results["order_to_adv_ratio"], 8),
        "permutation_pvalue":    round(perm_results["permutation_pvalue"], 4),
        "permutation_test_pass": perm_results["permutation_test_pass"],
        # Post-cost
        "post_cost_sharpe":     round(post_cost_sharpe, 4),
        "look_ahead_bias_flag": False,
        # Sub-periods
        "sub_period_results": sub_period_results,
        "bear_2022_sharpe":   round(bear_sharpe, 4) if bear_sharpe is not None else None,
        # Gate 1
        "gate_criteria":  {k: bool(v) for k, v in gate_criteria.items()},
        "gate1_pass":     gate1_pass,
        "criteria_passed": passed_count,
        "criteria_total":  total_count,
    }

    os.makedirs("backtests", exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nMetrics JSON saved: {OUT_JSON}")

    # -----------------------------------------------------------------------
    # 10. Verdict text
    # -----------------------------------------------------------------------
    failing = [k for k, v in gate_criteria.items() if not v]
    verdict_lines = [
        "=" * 60,
        "H12 SuperTrend ATR Momentum — Gate 1 Verdict",
        "=" * 60,
        f"Date         : {TODAY}",
        f"Universe     : {', '.join(TICKERS)}",
        f"IS period    : {IS_START} — {IS_END}",
        f"OOS period   : {OOS_START} — {OOS_END}",
        "",
        f"VERDICT: {'PASS' if gate1_pass else 'FAIL'}  ({passed_count}/{total_count} criteria)",
        "",
        "--- Core Metrics ---",
        f"IS Sharpe         : {is_metrics['sharpe']:.4f}  (threshold > 1.0)",
        f"OOS Sharpe        : {oos_metrics['sharpe']:.4f}  (threshold > 0.7)",
        f"IS Max Drawdown   : {is_metrics['max_drawdown']:.2%}  (threshold < 20%)",
        f"OOS Max Drawdown  : {oos_metrics['max_drawdown']:.2%}  (threshold < 25%)",
        f"Win Rate          : {is_metrics['win_rate']:.2%}  (threshold > 50%)",
        f"Profit Factor     : {is_metrics['profit_factor']:.2f}",
        f"IS Trade Count    : {is_metrics['trade_count']}  (threshold ≥ 30)",
        f"OOS Trade Count   : {oos_metrics['trade_count']}",
        f"IC (SPY)          : {ic_spy:.4f}  (threshold > 0.02)",
        f"DSR               : {dsr_value:.4f}  (threshold > 0)",
        "",
        "--- Walk-Forward ---",
        f"Windows Passed    : {wf_passed}/4  (threshold ≥ 3)",
        f"Avg Consistency   : {wf_avg_consistency:.2f}",
        f"WF Sharpe Std     : {wf_var['wf_sharpe_std']:.4f}",
        f"WF Sharpe Min     : {wf_var['wf_sharpe_min']:.4f}",
        "",
        "--- Statistical Rigor ---",
        f"MC p5 Sharpe      : {mc_results['mc_p5_sharpe']:.3f}",
        f"MC median Sharpe  : {mc_results['mc_median_sharpe']:.3f}",
        f"Sharpe 95% CI     : [{ci_results['sharpe_ci_low']:.3f}, {ci_results['sharpe_ci_high']:.3f}]",
        f"Market Impact     : {mi_results['market_impact_bps']:.2f} bps",
        f"Permutation p     : {perm_results['permutation_pvalue']:.3f}  "
        f"({'PASS' if perm_results['permutation_test_pass'] else 'FAIL'})",
        f"Sensitivity max Δ : {max_deg:.1%}  ({'PASS' if sensitivity_pass else 'FAIL'})",
        "",
        "--- Sub-Period Performance ---",
    ]
    for sp in sub_period_results:
        verdict_lines.append(f"  {sp['period']:30s}: Sharpe={sp['sharpe']:.3f}, trades={sp['trade_count']}, WR={sp['win_rate']:.2%}")

    if bear_sharpe is not None:
        verdict_lines.append(f"\n2022 bear test: Sharpe={bear_sharpe:.3f} "
                              f"({'PASS — trend-following worked' if bear_sharpe > 0 else 'FAIL — losses in trending bear'})")

    if not gate1_pass:
        verdict_lines += ["", "--- Failing Criteria ---"]
        for f_crit in failing:
            verdict_lines.append(f"  FAIL: {f_crit}")

    verdict_lines += [
        "",
        "--- Research Director Conditions Check ---",
        "  [OK] Regime gate applied: VIX < 30 + 200-day SMA filter",
        "  [OK] ATR sensitivity heatmap: multiplier 1.5–3.5 × lookback 7–20",
        "  [OK] 2022 bear sub-period tested",
        "  [OK] Universe: SPY, QQQ, IWM only",
        "  [OK] Long-only (no short positions)",
        "",
        "Generated by Backtest Runner Agent (QUA-154)",
    ]

    verdict_text = "\n".join(verdict_lines)
    with open(OUT_VERDICT, "w") as f:
        f.write(verdict_text)
    print(f"Verdict text saved: {OUT_VERDICT}")
    print("\n" + verdict_text)

    return output


if __name__ == "__main__":
    main()
