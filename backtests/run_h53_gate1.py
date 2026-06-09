"""
H53 Gate 1 Backtest Runner — Faber GTAA-5 (5-Asset 10-Month MA Tactical Allocation)
Executes full IS/OOS + walk-forward + statistical rigor pipeline.

IS period:  2007-01-01 to 2023-12-31  (GSG inception June 2006; 10-month MA warm by Apr 2007)
OOS period: 2024-01-01 to 2025-12-31

Gate 1 targets (QUA-125):
  IS Sharpe > 1.0  (borderline: estimate 0.80-1.05)
  OOS Sharpe > 0.7
  IS MDD < 20%  (published -9.5% — strong safety margin)
  IS Trades >= 100
  Walk-forward consistency >= 3/4 windows
  Permutation p <= 0.05

Output:
  backtests/H53_Faber_GTAA5_{TODAY}.json
  backtests/H53_Faber_GTAA5_{TODAY}_report.md
  backtests/H53_Faber_GTAA5_{TODAY}_verdict.txt
"""

import sys
import json
import warnings
import datetime
import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, "/repos/quant-zero")

from strategies.h53_faber_gtaa5 import (
    run_backtest,
    download_data,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

warnings.filterwarnings("ignore")

TODAY = datetime.date.today().isoformat()
STRATEGY_NAME = "H53_Faber_GTAA5"

IS_START, IS_END = "2007-01-01", "2023-12-31"
OOS_START, OOS_END = "2024-01-01", "2025-12-31"

BACKTEST_DIR = "/repos/quant-zero/backtests"


# ── Statistical Rigor Functions ────────────────────────────────────────────────

def monte_carlo_sharpe(daily_returns: np.ndarray, n_sims: int = 1000) -> dict:
    """Bootstrap Sharpe distribution; return p5/median/p95."""
    sharpes = []
    T = len(daily_returns)
    for _ in range(n_sims):
        sample = np.random.choice(daily_returns, size=T, replace=True)
        std = sample.std()
        s = (sample.mean() / (std + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR)
             if std > 1e-10 else 0.0)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe": round(float(np.percentile(sharpes, 5)), 4),
        "mc_median_sharpe": round(float(np.median(sharpes)), 4),
        "mc_p95_sharpe": round(float(np.percentile(sharpes, 95)), 4),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    """Block bootstrap CI for Sharpe/MDD/win-rate. Block = sqrt(T)."""
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = T // block_len
    sharpes, mdds, win_rates = [], [], []

    for _ in range(n_boots):
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        std = sample.std()
        s = (float(sample.mean() / (std + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR))
             if std > 1e-10 else 0.0)
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(float(np.mean(sample > 0)))

    return {
        "sharpe_ci_low": round(float(np.percentile(sharpes, 2.5)), 4),
        "sharpe_ci_high": round(float(np.percentile(sharpes, 97.5)), 4),
        "mdd_ci_low": round(float(np.percentile(mdds, 2.5)), 4),
        "mdd_ci_high": round(float(np.percentile(mdds, 97.5)), 4),
        "win_rate_ci_low": round(float(np.percentile(win_rates, 2.5)), 4),
        "win_rate_ci_high": round(float(np.percentile(win_rates, 97.5)), 4),
    }


def permutation_test_alpha(
    prices: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 500,
    hold_days: int = 21,  # monthly strategy → ~21 trading days/month
) -> dict:
    """
    Permutation test: compare observed Sharpe to random-entry distribution.
    p-value = fraction of random strategies with Sharpe >= observed.
    """
    T = len(prices)
    permuted_sharpes = []

    for _ in range(n_perms):
        n_trades = max(10, T // hold_days)
        valid_starts = T - hold_days
        if valid_starts <= 0:
            permuted_sharpes.append(0.0)
            continue
        entry_idxs = np.random.choice(valid_starts, size=min(n_trades, valid_starts), replace=False)
        trade_rets = []
        for idx in entry_idxs:
            exit_idx = min(idx + hold_days, T - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
            trade_rets.append(ret)
        arr = np.array(trade_rets)
        if len(arr) > 1 and arr.std() > 1e-10:
            s = arr.mean() / arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR / hold_days)
        else:
            s = 0.0
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = round(float(np.mean(permuted_sharpes >= observed_sharpe)), 4)
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": bool(p_value <= 0.05),
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": round(float(arr.std()), 4) if len(arr) > 1 else 0.0,
        "wf_sharpe_min": round(float(arr.min()), 4) if len(arr) > 0 else 0.0,
    }


def compute_dsr(returns_series: np.ndarray, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014)."""
    T = len(returns_series)
    if T < 4:
        return 0.0
    std = returns_series.std()
    sharpe = returns_series.mean() / (std + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(pd.Series(returns_series).skew())
    kurt = float(pd.Series(returns_series).kurt())
    gamma = 0.5772156649
    E_max_sr = (
        (1 - gamma) * norm.ppf(1 - 1.0 / n_trials)
        + gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sr_std = np.sqrt(
        (1 + 0.5 * sharpe ** 2 - skew * sharpe + (kurt / 4) * sharpe ** 2) / (T - 1)
    )
    dsr = float(norm.cdf((sharpe - E_max_sr) / (sr_std + 1e-10)))
    return round(dsr, 6)


# ── Walk-Forward Analysis ──────────────────────────────────────────────────────

def run_walk_forward(
    base_params: dict,
    n_windows: int = 4,
    is_months: int = 48,   # 4-year IS windows
    oos_months: int = 12,  # 1-year OOS windows
) -> list:
    """
    Walk-forward: 4 non-overlapping IS/OOS windows across IS period 2007-2023.
    Windows: 4yr IS / 1yr OOS. Starts 2007-01-01.
    Expected windows:
      W1: IS 2007-2010 / OOS 2011
      W2: IS 2008-2011 / OOS 2012
      W3: IS 2009-2012 / OOS 2013
      W4: IS 2010-2013 / OOS 2014
    """
    wf_results = []
    base_start = pd.Timestamp("2007-01-01")

    for w in range(n_windows):
        is_start = base_start + pd.DateOffset(months=w * oos_months)
        is_end = is_start + pd.DateOffset(months=is_months) - pd.DateOffset(days=1)
        oos_start = is_end + pd.DateOffset(days=1)
        oos_end = oos_start + pd.DateOffset(months=oos_months) - pd.DateOffset(days=1)

        try:
            is_r = run_backtest(
                start=is_start.strftime("%Y-%m-%d"),
                end=is_end.strftime("%Y-%m-%d"),
                params=base_params,
            )
            oos_r = run_backtest(
                start=oos_start.strftime("%Y-%m-%d"),
                end=oos_end.strftime("%Y-%m-%d"),
                params=base_params,
            )
            # Pass: OOS Sharpe >= 0.7 OR OOS Sharpe within 30% degradation of IS
            oos_passes = bool(
                oos_r["sharpe"] >= 0.7
                or (
                    is_r["sharpe"] > 0
                    and abs(oos_r["sharpe"] - is_r["sharpe"]) / (abs(is_r["sharpe"]) + 1e-8) <= 0.30
                )
            )
            wf_results.append({
                "window": w + 1,
                "is_start": is_start.strftime("%Y-%m-%d"),
                "is_end": is_end.strftime("%Y-%m-%d"),
                "oos_start": oos_start.strftime("%Y-%m-%d"),
                "oos_end": oos_end.strftime("%Y-%m-%d"),
                "is_sharpe": round(is_r["sharpe"], 4),
                "oos_sharpe": round(oos_r["sharpe"], 4),
                "is_mdd": round(is_r["max_drawdown"], 4),
                "oos_mdd": round(oos_r["max_drawdown"], 4),
                "is_trade_count": is_r["trade_count"],
                "oos_trade_count": oos_r["trade_count"],
                "is_avg_shy": is_r["avg_n_shy"],
                "oos_avg_shy": oos_r["avg_n_shy"],
                "pass": oos_passes,
            })
        except Exception as exc:
            wf_results.append({
                "window": w + 1,
                "error": str(exc),
                "pass": False,
            })

    return wf_results


# ── Sensitivity Scans ──────────────────────────────────────────────────────────

def scan_ma_lookback(start: str, end: str, base_params: dict) -> dict:
    """Scan MA lookback: 8, 9, 10, 11, 12 months."""
    results = {}
    for ma in [8, 9, 10, 11, 12]:
        key = f"ma_{ma}mo"
        p = {**base_params, "ma_months": ma}
        try:
            r = run_backtest(start=start, end=end, params=p)
            results[key] = round(r["sharpe"], 4)
        except Exception as exc:
            results[key] = f"error: {exc}"

    sharpe_vals = [v for v in results.values() if isinstance(v, float) and not np.isnan(v)]
    if len(sharpe_vals) > 1:
        sharpe_range = max(sharpe_vals) - min(sharpe_vals)
        sharpe_mean = np.mean(sharpe_vals)
        variance_pct = sharpe_range / abs(sharpe_mean) if abs(sharpe_mean) > 1e-8 else float("inf")
        results["_sharpe_range"] = round(float(sharpe_range), 4)
        results["_sharpe_variance_pct"] = round(float(variance_pct), 4)
        flag = "PASS" if variance_pct <= 0.30 else "FAIL"
        results["_gate1_variance_flag"] = (
            f"{flag}: Sharpe variance {variance_pct:.1%} "
            f"{'≤' if flag == 'PASS' else '>'} 30% across 5 MA lookback combinations."
        )
    return results


def scan_commodity_variants(start: str, end: str, base_params: dict) -> dict:
    """Scan commodity ETF variants: GSG, DJP, PDBC."""
    results = {}
    for cmdty in ["GSG", "DJP", "PDBC"]:
        key = f"commodity_{cmdty}"
        p = {**base_params, "commodity_ticker": cmdty}
        p["assets"] = ["SPY", "EFA", "IEF", cmdty, "VNQ"]
        try:
            r = run_backtest(start=start, end=end, params=p)
            results[key] = round(r["sharpe"], 4)
        except Exception as exc:
            results[key] = f"error: {exc}"
    return results


# ── Main Gate 1 Runner ────────────────────────────────────────────────────────

def main():
    np.random.seed(42)
    print("=" * 70)
    print(f"H53 Faber GTAA-5 — Gate 1 Backtest [{TODAY}]")
    print(f"IS: {IS_START} to {IS_END}  |  OOS: {OOS_START} to {OOS_END}")
    print("Expected IS Sharpe: 0.80–1.05 (borderline). Published MDD: -9.5%.")
    print("=" * 70)

    # ── 1. IS Backtest ────────────────────────────────────────────────────────
    print(f"\n[1/6] IS backtest ({IS_START} → {IS_END})...")
    is_result = run_backtest(start=IS_START, end=IS_END, params=PARAMETERS)
    is_sharpe = is_result["sharpe"]
    is_mdd = is_result["max_drawdown"]
    is_win_rate = is_result["win_rate"]
    is_trade_count = is_result["trade_count"]
    is_total_return = is_result["total_return"]
    is_cagr = is_result["cagr"]
    is_profit_factor = is_result["profit_factor"]
    is_returns = is_result["returns"].values
    is_asset_breakdown = is_result["asset_breakdown"]
    is_avg_shy = is_result["avg_n_shy"]
    data_quality = is_result["data_quality"]
    trades_df = is_result["trades"]

    print(
        f"  IS Sharpe: {is_sharpe}  MDD: {is_mdd:.1%}  "
        f"CAGR: {is_cagr:.1%}  WinRate: {is_win_rate:.1%}  "
        f"Trades: {is_trade_count}  PF: {is_profit_factor}"
    )
    print(f"  Avg assets in SHY: {is_avg_shy:.1f}/5")

    # ── 2. OOS Backtest ───────────────────────────────────────────────────────
    print(f"\n[2/6] OOS backtest ({OOS_START} → {OOS_END})...")
    oos_result = run_backtest(start=OOS_START, end=OOS_END, params=PARAMETERS)
    oos_sharpe = oos_result["sharpe"]
    oos_mdd = oos_result["max_drawdown"]
    oos_win_rate = oos_result["win_rate"]
    oos_trade_count = oos_result["trade_count"]
    oos_total_return = oos_result["total_return"]
    oos_avg_shy = oos_result["avg_n_shy"]

    print(
        f"  OOS Sharpe: {oos_sharpe}  MDD: {oos_mdd:.1%}  "
        f"Trades: {oos_trade_count}  WinRate: {oos_win_rate:.1%}"
    )

    # ── 3. Walk-Forward ───────────────────────────────────────────────────────
    print("\n[3/6] Walk-forward (4 windows, 48m IS / 12m OOS)...")
    wf_table = run_walk_forward(PARAMETERS, n_windows=4, is_months=48, oos_months=12)
    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_table if "oos_sharpe" in w]
    wf_windows_passed = sum(1 for w in wf_table if w.get("pass", False))
    wf_ratios = []
    for w in wf_table:
        if "is_sharpe" in w and abs(w["is_sharpe"]) > 0.01:
            wf_ratios.append(w["oos_sharpe"] / w["is_sharpe"])
    wf_consistency_score = round(float(np.mean(wf_ratios)) if wf_ratios else 0.0, 4)
    wf_var = walk_forward_variance(wf_oos_sharpes)

    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        err = w.get("error", "")
        if err:
            print(f"  W{w['window']}: ERROR: {err}")
        else:
            print(
                f"  W{w['window']}: IS={w.get('is_sharpe','?')} "
                f"OOS={w.get('oos_sharpe','?')} "
                f"IS_MDD={w.get('is_mdd','?'):.1%} [{status}]"
            )
    print(
        f"  WF passed: {wf_windows_passed}/4 | "
        f"Consistency: {wf_consistency_score} | "
        f"Sharpe std: {wf_var['wf_sharpe_std']}"
    )

    # ── 4. Statistical Rigor ──────────────────────────────────────────────────
    print("\n[4/6] Statistical rigor pipeline...")

    print("  4a. Monte Carlo Sharpe (1000 sims)...")
    mc = (monte_carlo_sharpe(is_returns) if len(is_returns) > 10
          else {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0})
    print(
        f"      p5={mc['mc_p5_sharpe']:.3f}  "
        f"median={mc['mc_median_sharpe']:.3f}  "
        f"p95={mc['mc_p95_sharpe']:.3f}"
    )

    print("  4b. Block Bootstrap CI (1000 boots)...")
    bci = (block_bootstrap_ci(is_returns) if len(is_returns) > 20
           else {k: 0.0 for k in [
               "sharpe_ci_low", "sharpe_ci_high",
               "mdd_ci_low", "mdd_ci_high",
               "win_rate_ci_low", "win_rate_ci_high",
           ]})
    print(f"      Sharpe CI [{bci['sharpe_ci_low']:.3f}, {bci['sharpe_ci_high']:.3f}]")

    print("  4c. Market impact (equity ETFs, canonical model)...")
    # Average market impact estimate — SPY/EFA/IEF/VNQ all very liquid
    # $100K / 5 assets = $20K/slice. SPY ~$500/share → ~40 shares → negligible impact.
    market_impact_note = (
        "ETF strategy, $100K portfolio / 5 slices = $20K/slice. "
        "SPY/EFA/IEF/VNQ/GSG ADV >> $20K. Market impact << 0.1 bps per trade. "
        "Canonical model: $0.005/share + 0.05% slippage + k=0.1 sqrt-impact applied in simulation."
    )

    print("  4d. Permutation test (500 perms, SPY proxy, 21-day hold)...")
    try:
        spy_data = download_data(PARAMETERS, IS_START, IS_END)
        spy_prices = spy_data["SPY"]["Close"].loc[IS_START:IS_END].dropna().values
        perm = permutation_test_alpha(spy_prices, is_sharpe, n_perms=500, hold_days=21)
    except Exception as e:
        print(f"      Permutation test error: {e}")
        perm = {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    print(
        f"      p-value={perm['permutation_pvalue']} "
        f"{'PASS' if perm['permutation_test_pass'] else 'FAIL'}"
    )

    # DSR: n_trials = 5 MA lookbacks × 3 commodity variants = 15 combinations
    n_trials = 15
    dsr = compute_dsr(is_returns, n_trials=n_trials) if len(is_returns) > 10 else 0.0
    print(f"  4e. DSR (n={n_trials} trials): {dsr:.6f}")

    # ── 5. Sensitivity Scans ──────────────────────────────────────────────────
    print("\n[5/6] Sensitivity scans...")

    print("  5a. MA lookback scan [8, 9, 10, 11, 12] months...")
    ma_scan = scan_ma_lookback(IS_START, IS_END, PARAMETERS)
    print(f"      {ma_scan.get('_gate1_variance_flag', 'N/A')}")
    sensitivity_pass = "PASS" in str(ma_scan.get("_gate1_variance_flag", "FAIL"))
    ma_table = {k: v for k, v in ma_scan.items() if k.startswith("ma_")}

    print("  5b. Commodity variant scan [GSG, DJP, PDBC]...")
    cmdty_scan = scan_commodity_variants(IS_START, IS_END, PARAMETERS)
    print(f"      {cmdty_scan}")

    # ── 6. Gate 1 Verdict ─────────────────────────────────────────────────────
    print("\n[6/6] Gate 1 verdict...")

    gate1_checks = {
        "is_sharpe_pass": bool(is_sharpe > 1.0),
        "oos_sharpe_pass": bool(oos_sharpe > 0.7),
        "is_mdd_pass": bool(is_mdd > -0.20),
        "oos_mdd_pass": bool(oos_mdd > -0.25),
        "win_rate_pass": bool(is_win_rate >= 0.50 or is_profit_factor >= 1.2),
        "trade_count_pass": bool(is_trade_count >= 100),
        "wf_windows_pass": bool(wf_windows_passed >= 3),
        "wf_consistency_pass": bool(wf_consistency_score >= 0.7),
        "sensitivity_pass": bool(sensitivity_pass),
        "dsr_pass": bool(dsr > 0),
        "permutation_pass": bool(perm["permutation_test_pass"]),
        "mc_p5_pass": bool(mc["mc_p5_sharpe"] >= 0.5),
    }

    gate1_pass = all(gate1_checks.values())
    failing = [k for k, v in gate1_checks.items() if not v]

    print(f"\n  Gate 1: {'PASS ✓' if gate1_pass else 'FAIL ✗'}")
    if failing:
        print(f"  Failing: {', '.join(failing)}")
    else:
        print("  All Gate 1 criteria passed.")

    # ── Build JSON Metrics ─────────────────────────────────────────────────────
    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "hypothesis": "H53",
        "asset_class": "multi-asset ETF",
        "assets": PARAMETERS["assets"],
        "ma_months": PARAMETERS["ma_months"],
        "safe_harbor": PARAMETERS["safe_harbor"],
        "commodity_ticker": PARAMETERS.get("commodity_ticker", "GSG"),
        "is_period": f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "is_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "is_max_drawdown": is_mdd,
        "oos_max_drawdown": oos_mdd,
        "is_win_rate": is_win_rate,
        "oos_win_rate": oos_win_rate,
        "is_profit_factor": is_profit_factor,
        "is_cagr": is_cagr,
        "is_total_return": is_total_return,
        "oos_total_return": oos_total_return,
        "trade_count_is": is_trade_count,
        "trade_count_oos": oos_trade_count,
        "is_avg_shy_assets": is_avg_shy,
        "oos_avg_shy_assets": oos_avg_shy,
        "asset_breakdown_is": is_asset_breakdown,
        "dsr": dsr,
        "wf_windows_passed": wf_windows_passed,
        "wf_consistency_score": wf_consistency_score,
        "wf_table": wf_table,
        "wf_oos_sharpes": [round(s, 4) for s in wf_oos_sharpes],
        "wf_sharpe_std": wf_var["wf_sharpe_std"],
        "wf_sharpe_min": wf_var["wf_sharpe_min"],
        "mc_p5_sharpe": mc["mc_p5_sharpe"],
        "mc_median_sharpe": mc["mc_median_sharpe"],
        "mc_p95_sharpe": mc["mc_p95_sharpe"],
        "sharpe_ci_low": bci["sharpe_ci_low"],
        "sharpe_ci_high": bci["sharpe_ci_high"],
        "mdd_ci_low": bci["mdd_ci_low"],
        "mdd_ci_high": bci["mdd_ci_high"],
        "win_rate_ci_low": bci["win_rate_ci_low"],
        "win_rate_ci_high": bci["win_rate_ci_high"],
        "market_impact_note": market_impact_note,
        "permutation_pvalue": perm["permutation_pvalue"],
        "permutation_test_pass": perm["permutation_test_pass"],
        "sensitivity_scan_ma_lookback": ma_table,
        "sensitivity_scan_commodity": cmdty_scan,
        "sensitivity_scan_meta": {
            "sharpe_range": ma_scan.get("_sharpe_range"),
            "sharpe_variance_pct": ma_scan.get("_sharpe_variance_pct"),
            "gate1_variance_flag": ma_scan.get("_gate1_variance_flag"),
        },
        "sensitivity_pass": sensitivity_pass,
        "data_quality_summary": {
            "survivorship_bias": data_quality["survivorship_bias_flag"],
            "price_adjustments": "auto_adjust=True (splits/dividends).",
            "earnings_exclusion": data_quality["earnings_exclusion"],
            "delisted_tickers": data_quality["delisted_tickers"],
            "gsg_inception_note": data_quality["gsg_inception_note"],
            "signal_lag": data_quality["signal_lag"],
        },
        "look_ahead_bias_flag": False,
        "look_ahead_bias_notes": [
            "Monthly close MA computed using only historical closes through signal date T.",
            "Signal at month-end T uses close through T; executed at same T close (Faber convention).",
            "No future data used in warmup period calculations.",
            "GSG MA defaults to SHY for first 3 months (Jan-Mar 2007) — conservative.",
        ],
        "gate1_checks": gate1_checks,
        "gate1_pass": gate1_pass,
        "failing_criteria": failing,
        "borderline_note": (
            "IS Sharpe borderline (estimated 0.80-1.05). "
            "Published MDD -9.5% provides strong Gate 1 safety margin on drawdown criterion. "
            "Low MDD partially compensates for borderline Sharpe in paper-trading risk assessment."
        ),
    }

    # ── Save JSON ──────────────────────────────────────────────────────────────
    json_path = f"{BACKTEST_DIR}/{STRATEGY_NAME}_{TODAY}.json"
    with open(json_path, "w") as fh:
        json.dump(metrics, fh, indent=2, default=str)
    print(f"\nSaved JSON: {json_path}")

    # ── Build Markdown Report ──────────────────────────────────────────────────
    verdict_str = "PASS" if gate1_pass else "FAIL"
    mdd_flag = "PASS (<20%)" if is_mdd > -0.20 else f"FAIL ({is_mdd:.1%})"
    oos_mdd_flag = "PASS (<25%)" if oos_mdd > -0.25 else f"FAIL ({oos_mdd:.1%})"
    mc_p5_flag = "PASS" if mc["mc_p5_sharpe"] >= 0.5 else "FAIL"

    asset_rows = ""
    for tkr, info in is_asset_breakdown.items():
        asset_rows += (
            f"| {tkr} | {info['trade_count']} | {info['win_rate']:.1%} "
            f"| ${info['total_pnl']:,.0f} | {info['n_transitions']} |\n"
        )

    wf_rows = ""
    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        if "error" in w:
            wf_rows += f"| W{w['window']} | ERROR | — | — | — | — | — | — | **{status}** |\n"
        else:
            wf_rows += (
                f"| W{w['window']} | {w.get('is_start','?')}–{w.get('is_end','?')} "
                f"| {w.get('is_sharpe','?')} "
                f"| {w.get('oos_start','?')}–{w.get('oos_end','?')} "
                f"| {w.get('oos_sharpe','?')} "
                f"| {w.get('is_mdd', 0.0):.1%} "
                f"| {w.get('is_trade_count','?')} "
                f"| {w.get('is_avg_shy','?')} "
                f"| **{status}** |\n"
            )

    report_md = f"""# H53 Faber GTAA-5 — Gate 1 Report

**Date:** {TODAY}
**Strategy:** Equal-weight (20%) across SPY/EFA/IEF/GSG/VNQ. Hold asset if price > {PARAMETERS['ma_months']}-month MA; substitute SHY otherwise. Monthly rebalance.
**IS Period:** {IS_START} to {IS_END} (GSG-constrained)
**OOS Period:** {OOS_START} to {OOS_END}
**Overall Gate 1 Verdict: {verdict_str}**
**Borderline note:** IS Sharpe estimated 0.80–1.05 (academic). Published MDD -9.5% well inside <20% gate.

---

## Core Gate 1 Metrics

| Criterion | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | {is_sharpe} | > 1.0 | {'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'} |
| OOS Sharpe | {oos_sharpe} | > 0.7 | {'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'} |
| IS CAGR | {is_cagr:.1%} | — | — |
| IS Max Drawdown | {is_mdd:.1%} | < 20% | {mdd_flag} |
| OOS Max Drawdown | {oos_mdd:.1%} | < 25% | {oos_mdd_flag} |
| Win Rate (IS) | {is_win_rate:.1%} | ≥ 50% or PF ≥ 1.2 | {'PASS' if gate1_checks['win_rate_pass'] else 'FAIL'} |
| Profit Factor (IS) | {is_profit_factor} | > 1.0 | {'PASS' if is_profit_factor > 1.0 else 'FAIL'} |
| Trade Count (IS) | {is_trade_count} | ≥ 100 | {'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'} |
| IS Total Return | {is_total_return:.1%} | — | — |
| OOS Total Return | {oos_total_return:.1%} | — | — |
| Avg Assets in SHY (IS) | {is_avg_shy:.1f}/5 | — | — |

---

## Per-Asset Breakdown (IS)

| Asset | Trades | Win Rate | Total PnL | Transitions |
|---|---|---|---|---|
{asset_rows}
---

## Walk-Forward Analysis (4 windows, 48m IS / 12m OOS)

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | IS MDD | IS Trades | Avg SHY | Status |
|---|---|---|---|---|---|---|---|---|
{wf_rows}
**WF passed:** {wf_windows_passed}/4 | **Consistency:** {wf_consistency_score} | **Sharpe std:** {wf_var['wf_sharpe_std']} | **Sharpe min:** {wf_var['wf_sharpe_min']}

---

## Statistical Rigor

| Test | Value | Status |
|---|---|---|
| DSR (n={n_trials} trials) | {dsr:.6f} | {'PASS' if gate1_checks['dsr_pass'] else 'FAIL'} |
| MC p5 Sharpe | {mc['mc_p5_sharpe']} | {mc_p5_flag} |
| MC Median Sharpe | {mc['mc_median_sharpe']} | — |
| Sharpe CI [95%] | [{bci['sharpe_ci_low']}, {bci['sharpe_ci_high']}] | — |
| MDD CI [95%] | [{bci['mdd_ci_low']}, {bci['mdd_ci_high']}] | — |
| Permutation p-value | {perm['permutation_pvalue']} | {'PASS (≤0.05)' if gate1_checks['permutation_pass'] else 'FAIL (>0.05)'} |

---

## Sensitivity Analysis

### MA Lookback (5 combinations: 8–12 months)
{ma_scan.get('_gate1_variance_flag', 'N/A')}

| Config | IS Sharpe |
|---|---|
"""

    for k, v in ma_table.items():
        report_md += f"| {k} | {v} |\n"

    report_md += f"""
### Commodity ETF Variant (GSG / DJP / PDBC)

| Config | IS Sharpe |
|---|---|
"""
    for k, v in cmdty_scan.items():
        report_md += f"| {k} | {v} |\n"

    report_md += f"""
---

## Data Quality Checklist

- **Universe/survivorship bias:** {data_quality['survivorship_bias_flag']}
- **Price adjustments:** auto_adjust=True (yfinance). Splits and dividends adjusted.
- **Data gaps:** Checked per ticker; forward-fill NOT applied for gaps >= 5 days.
- **Earnings exclusion:** N/A — ETF strategy (no earnings events).
- **Delisted tickers:** N/A — SPY/EFA/IEF/GSG/VNQ/SHY all active.
- **GSG inception note:** {data_quality['gsg_inception_note']}

---

## Risk Flags

- **Look-ahead bias:** None. MA computed at month-end T using closes through T only. Executed at same T close (Faber 2007 convention).
- **Market impact:** {market_impact_note}
- **IS Sharpe borderline:** Estimated 0.80–1.05 (academic). Published MDD -9.5% well inside <20% gate.
- **Commodity concentration:** GSG is energy-heavy. DJP/PDBC provide diversification variants.

---

## Gate 1 Checklist

| Check | Pass? |
|---|---|
"""

    for check, passed in gate1_checks.items():
        report_md += f"| {check} | {'✅ PASS' if passed else '❌ FAIL'} |\n"

    report_md += f"""
---

## Verdict

**Overall Gate 1: {verdict_str}**

"""
    if gate1_pass:
        report_md += (
            "All Gate 1 criteria passed. "
            "Strategy eligible for paper trading pending CEO approval.\n"
        )
    else:
        report_md += f"Failing criteria: {', '.join(failing)}\n\n"
        report_md += "Strategy **does not pass Gate 1**. Return to Research Director for revision.\n"

    report_path = f"{BACKTEST_DIR}/{STRATEGY_NAME}_{TODAY}_report.md"
    with open(report_path, "w") as fh:
        fh.write(report_md)
    print(f"Saved report: {report_path}")

    # ── Verdict file ───────────────────────────────────────────────────────────
    verdict_path = f"{BACKTEST_DIR}/{STRATEGY_NAME}_{TODAY}_verdict.txt"
    with open(verdict_path, "w") as fh:
        fh.write(f"Gate 1 Verdict: {verdict_str}\n")
        fh.write(f"IS Sharpe: {is_sharpe}\n")
        fh.write(f"OOS Sharpe: {oos_sharpe}\n")
        fh.write(f"IS MDD: {is_mdd:.4f}\n")
        fh.write(f"IS Trades: {is_trade_count}\n")
        fh.write(f"WF Windows Passed: {wf_windows_passed}/4\n")
        fh.write(f"Permutation p: {perm['permutation_pvalue']}\n")
        if failing:
            fh.write(f"Failing: {', '.join(failing)}\n")
    print(f"Saved verdict: {verdict_path}")

    return metrics, gate1_pass, failing


if __name__ == "__main__":
    metrics, gate1_pass, failing = main()
    print("\n" + "=" * 70)
    print(f"H53 Gate 1 Final Verdict: {'PASS' if gate1_pass else 'FAIL'}")
    if failing:
        print(f"Failing: {', '.join(failing)}")
    print(f"IS Sharpe:  {metrics['is_sharpe']}")
    print(f"OOS Sharpe: {metrics['oos_sharpe']}")
    print(f"IS MDD:     {metrics['is_max_drawdown']:.1%}")
    print(f"IS Trades:  {metrics['trade_count_is']}")
    print(f"IS CAGR:    {metrics['is_cagr']:.1%}")
