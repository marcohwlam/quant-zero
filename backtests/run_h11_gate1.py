"""
H11 Gate 1 Backtest Runner — CVD-Confirmed Breakout
Full IS/OOS + sequential IC validation + walk-forward + statistical rigor.

Research Director conditions (QUA-130):
1. Sequential signal validation: price breakout IC alone first, then CVD proxy alone
2. CVD threshold sensitivity sweep (0.5-2.0)
3. Universe: SPY/QQQ/IWM + top-50 S&P500 by ADV (using 15 liquid proxies)
4. Asset: equity ETFs + large-cap stocks

Output:
  backtests/H11_CVDBreakout_{TODAY}.json
  backtests/H11_CVDBreakout_{TODAY}_verdict.txt
"""

import sys
import json
import warnings
import datetime
import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, "/mnt/c/Users/lamho/repo/quant-zero")

from strategies.h11_cvd_breakout import (
    run_strategy,
    validate_sequential_ic,
    scan_cvd_threshold,
    download_equity_data,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

warnings.filterwarnings("ignore")

TODAY = datetime.date.today().isoformat()
STRATEGY_NAME = "H11_CVDBreakout"
IS_START, IS_END = "2018-01-01", "2021-12-31"
OOS_START, OOS_END = "2022-01-01", "2023-12-31"


# ── Statistical Rigor Functions ────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe": round(float(np.percentile(arr, 5)), 4),
        "mc_median_sharpe": round(float(np.median(arr)), 4),
        "mc_p95_sharpe": round(float(np.percentile(arr, 95)), 4),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        if len(sample) < 2 or sample.std() == 0:
            continue
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)
    if not sharpes:
        return {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
                "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
                "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0}
    return {
        "sharpe_ci_low": round(float(np.percentile(sharpes, 2.5)), 4),
        "sharpe_ci_high": round(float(np.percentile(sharpes, 97.5)), 4),
        "mdd_ci_low": round(float(np.percentile(mdds, 2.5)), 4),
        "mdd_ci_high": round(float(np.percentile(mdds, 97.5)), 4),
        "win_rate_ci_low": round(float(np.percentile(win_rates, 2.5)), 4),
        "win_rate_ci_high": round(float(np.percentile(win_rates, 97.5)), 4),
    }


def permutation_test_alpha(prices: np.ndarray, observed_sharpe: float,
                            hold_days: int = 5, n_perms: int = 500) -> dict:
    T = len(prices)
    permuted_sharpes = []
    for _ in range(n_perms):
        n_trades = max(10, T // 15)
        valid = np.arange(max(1, T - hold_days))
        if len(valid) == 0:
            break
        idx = np.random.choice(valid, size=min(n_trades, len(valid)), replace=False)
        rets = [(prices[min(j + hold_days, T - 1)] - prices[j]) / (prices[j] + 1e-8) for j in idx]
        arr = np.array(rets)
        if len(arr) > 1 and arr.std() > 0:
            s = arr.mean() / arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR / hold_days)
        else:
            s = 0.0
        permuted_sharpes.append(s)
    if not permuted_sharpes:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    arr = np.array(permuted_sharpes)
    p = round(float(np.mean(arr >= observed_sharpe)), 4)
    return {"permutation_pvalue": p, "permutation_test_pass": bool(p <= 0.05)}


def compute_dsr(returns: np.ndarray, n_trials: int) -> float:
    T = len(returns)
    if T < 4:
        return 0.0
    sharpe = returns.mean() / (returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(pd.Series(returns).skew())
    kurt = float(pd.Series(returns).kurt())
    gamma = 0.5772156649
    E_max_sr = (
        (1 - gamma) * norm.ppf(1 - 1.0 / n_trials)
        + gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sr_std = np.sqrt(
        (1 + 0.5 * sharpe ** 2 - skew * sharpe + (kurt / 4) * sharpe ** 2) / (T - 1)
    )
    return round(float(norm.cdf((sharpe - E_max_sr) / (sr_std + 1e-10))), 6)


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": round(float(arr.std()), 4),
        "wf_sharpe_min": round(float(arr.min()), 4),
    }


def run_walk_forward(base_params: dict, n_windows: int = 4,
                     is_months: int = 24, oos_months: int = 6) -> list:
    wf_results = []
    base_start = pd.Timestamp(IS_START)
    for w in range(n_windows):
        is_start = base_start + pd.DateOffset(months=w * oos_months)
        is_end = is_start + pd.DateOffset(months=is_months) - pd.DateOffset(days=1)
        oos_start = is_end + pd.DateOffset(days=1)
        oos_end = oos_start + pd.DateOffset(months=oos_months) - pd.DateOffset(days=1)
        try:
            is_r = run_strategy(is_start.strftime("%Y-%m-%d"), is_end.strftime("%Y-%m-%d"), base_params)
            oos_r = run_strategy(oos_start.strftime("%Y-%m-%d"), oos_end.strftime("%Y-%m-%d"), base_params)
            oos_passes = (
                oos_r["sharpe"] >= 0.7
                or (is_r["sharpe"] > 0
                    and abs(oos_r["sharpe"] - is_r["sharpe"]) / (abs(is_r["sharpe"]) + 1e-8) <= 0.30)
            )
            wf_results.append({
                "window": w + 1,
                "is_start": is_start.strftime("%Y-%m-%d"),
                "is_end": is_end.strftime("%Y-%m-%d"),
                "oos_start": oos_start.strftime("%Y-%m-%d"),
                "oos_end": oos_end.strftime("%Y-%m-%d"),
                "is_sharpe": is_r["sharpe"],
                "oos_sharpe": oos_r["sharpe"],
                "is_mdd": is_r["max_drawdown"],
                "oos_mdd": oos_r["max_drawdown"],
                "is_trade_count": is_r["trade_count"],
                "oos_trade_count": oos_r["trade_count"],
                "pass": bool(oos_passes),
            })
        except Exception as exc:
            wf_results.append({"window": w + 1, "error": str(exc), "pass": False})
    return wf_results


# ── Main Gate 1 Runner ────────────────────────────────────────────────────────

def main():
    np.random.seed(42)
    print("=" * 65)
    print(f"H11 CVD-Confirmed Breakout — Gate 1 Backtest [{TODAY}]")
    print("=" * 65)
    print(f"IS: {IS_START} to {IS_END} | OOS: {OOS_START} to {OOS_END}")
    print(f"Universe: {PARAMETERS['universe'][:6]}... ({len(PARAMETERS['universe'])} tickers)")

    # ── 0. Pre-load IS data (reuse for IC validation + main backtest) ─────────
    print("\n[0/8] Pre-loading IS data...")
    warmup_start = (pd.Timestamp(IS_START) - pd.DateOffset(days=60)).strftime("%Y-%m-%d")
    is_ohlcv_full = download_equity_data(PARAMETERS["universe"], warmup_start, IS_END)
    is_ohlcv = {t: df.loc[df.index >= pd.Timestamp(IS_START)] for t, df in is_ohlcv_full.items()}
    print(f"  Loaded {len(is_ohlcv)} tickers")

    # ── 1. Sequential IC Validation (Research Director QUA-130) ──────────────
    print("\n[1/8] Sequential IC validation...")
    ic_validation = validate_sequential_ic(is_ohlcv, PARAMETERS)
    print(f"  Price breakout IC: {ic_validation['avg_price_breakout_ic']:.4f} {'PASS' if ic_validation['price_ic_pass'] else 'FAIL'}")
    print(f"  CVD proxy IC:      {ic_validation['avg_cvd_proxy_ic']:.4f} {'PASS' if ic_validation['cvd_ic_pass'] else 'FAIL'}")
    print(f"  Combined IC:       {ic_validation['avg_combined_ic']:.4f}")
    print(f"  Decision: {ic_validation['decision']}")
    print(f"  Note: {ic_validation['note']}")

    # If CVD IC fails, downgrade to price_only
    if ic_validation["decision"] == "PRICE_ONLY":
        print("\n  DOWNGRADING to price breakout only — CVD IC < 0.02")
        active_signal = "price_only"
    elif ic_validation["decision"] == "REJECT_BOTH":
        print("\n  REJECTING — both signals below IC floor")
        active_signal = "combined"
    else:
        active_signal = "combined"

    print(f"  Active signal for Gate 1: {active_signal}")

    # ── 2. IS Backtest ────────────────────────────────────────────────────────
    print(f"\n[2/8] Running IS backtest ({IS_START} to {IS_END})...")
    is_full = run_strategy(IS_START, IS_END, PARAMETERS, signal_override=active_signal)
    is_sharpe = is_full["sharpe"]
    is_mdd = is_full["max_drawdown"]
    is_win_rate = is_full["win_rate"]
    is_win_loss = is_full["win_loss_ratio"]
    is_profit_factor = is_full["profit_factor"]
    is_trade_count = is_full["trade_count"]
    is_total_return = is_full["total_return"]
    is_returns = is_full["returns"]
    is_trade_log = is_full["trade_log"]
    is_exit_reasons = is_full.get("exit_reasons", {})
    trade_pnls = np.array([t["net_pnl"] for t in is_trade_log])
    print(f"  IS Sharpe={is_sharpe}  MDD={is_mdd:.1%}  WinRate={is_win_rate:.1%}  Trades={is_trade_count}")
    print(f"  Exit reasons: {is_exit_reasons}")
    print(f"  Per-ticker: {is_full.get('per_ticker_trades', {})}")

    # ── 3. OOS Backtest ───────────────────────────────────────────────────────
    print(f"\n[3/8] Running OOS backtest ({OOS_START} to {OOS_END})...")
    oos_full = run_strategy(OOS_START, OOS_END, PARAMETERS, signal_override=active_signal)
    oos_sharpe = oos_full["sharpe"]
    oos_mdd = oos_full["max_drawdown"]
    oos_win_rate = oos_full["win_rate"]
    oos_trade_count = oos_full["trade_count"]
    oos_total_return = oos_full["total_return"]
    print(f"  OOS Sharpe={oos_sharpe}  MDD={oos_mdd:.1%}  Trades={oos_trade_count}")

    # ── 4. CVD Threshold Sensitivity Sweep ────────────────────────────────────
    print("\n[4/8] CVD threshold sensitivity sweep (0.5-2.0)...")
    cvd_scan = scan_cvd_threshold(is_ohlcv, IS_START, IS_END, PARAMETERS)
    cvd_meta = cvd_scan.get("_meta", {})
    sensitivity_pass = "PASS" in str(cvd_meta.get("gate1_robustness", "FAIL"))
    print(f"  Sharpe variance: {cvd_meta.get('sharpe_variance_pct', 'N/A')} -> {'PASS' if sensitivity_pass else 'FAIL'}")
    for k, v in cvd_scan.items():
        if not k.startswith("_") and isinstance(v, dict) and "sharpe" in v:
            print(f"    {k}: Sharpe={v['sharpe']:.4f}  Trades={v['trade_count']}")

    # ── 5. Walk-Forward ───────────────────────────────────────────────────────
    print("\n[5/8] Walk-forward (4 windows, 24m IS / 6m OOS)...")
    wf_table = run_walk_forward(PARAMETERS)
    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_table if "oos_sharpe" in w]
    wf_windows_passed = sum(1 for w in wf_table if w.get("pass", False))
    wf_ratios = [w["oos_sharpe"] / w["is_sharpe"] for w in wf_table
                 if "is_sharpe" in w and abs(w.get("is_sharpe", 0)) > 0.01]
    wf_consistency_score = round(float(np.mean(wf_ratios)) if wf_ratios else 0.0, 4)
    wf_var = walk_forward_variance(wf_oos_sharpes) if wf_oos_sharpes else {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        print(f"  Window {w['window']}: IS={w.get('is_sharpe','?')} OOS={w.get('oos_sharpe','?')} [{status}]")

    # ── 6. Statistical Rigor ──────────────────────────────────────────────────
    print("\n[6/8] Statistical rigor pipeline...")
    mc = monte_carlo_sharpe(trade_pnls) if len(trade_pnls) > 5 else {
        "mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0
    }
    print(f"  MC: p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}")

    bci = block_bootstrap_ci(is_returns) if len(is_returns) > 10 else {
        "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
        "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
        "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
    }
    print(f"  Sharpe CI [{bci['sharpe_ci_low']:.3f}, {bci['sharpe_ci_high']:.3f}]")

    import yfinance as yf
    spy_is = yf.download("SPY", start=IS_START, end=IS_END, auto_adjust=True, progress=False)["Close"].values
    perm = (permutation_test_alpha(spy_is, is_sharpe)
            if len(spy_is) > 20
            else {"permutation_pvalue": 1.0, "permutation_test_pass": False})
    print(f"  Perm p-value={perm['permutation_pvalue']} {'PASS' if perm['permutation_test_pass'] else 'FAIL'}")

    # n_trials: 6 CVD thresholds × 3 signals (price/cvd/combined) = 18
    n_trials = 18
    dsr = compute_dsr(is_returns, n_trials) if len(is_returns) > 10 else 0.0
    print(f"  DSR={dsr:.6f}")

    # ── 7. Sub-Period Analysis ────────────────────────────────────────────────
    print("\n[7/8] Sub-period analysis...")
    sub_periods = {
        "pre_covid_2018_2019": ("2018-01-01", "2019-12-31"),
        "stimulus_2020_2021": ("2020-01-01", "2021-12-31"),
        "rate_shock_2022": ("2022-01-01", "2022-12-31"),
        "normalization_2023": ("2023-01-01", "2023-12-31"),
    }
    sub_results = {}
    for name, (s, e) in sub_periods.items():
        try:
            r = run_strategy(s, e, PARAMETERS, signal_override=active_signal)
            sub_results[name] = {
                "sharpe": r["sharpe"],
                "max_drawdown": r["max_drawdown"],
                "trade_count": r["trade_count"],
                "win_rate": r["win_rate"],
            }
            print(f"  {name}: Sharpe={r['sharpe']}  MDD={r['max_drawdown']:.1%}  Trades={r['trade_count']}")
        except Exception as exc:
            sub_results[name] = {"error": str(exc)}
            print(f"  {name}: ERROR — {exc}")

    # ── 8. Gate 1 Verdict ────────────────────────────────────────────────────
    print("\n[8/8] Gate 1 verdict...")
    win_rate_pass = is_win_rate >= 0.50 or (is_win_rate < 0.50 and is_win_loss >= 1.2)
    gate1_checks = {
        "is_sharpe_pass": bool(is_sharpe > 1.0),
        "oos_sharpe_pass": bool(oos_sharpe > 0.7),
        "is_mdd_pass": bool(is_mdd > -0.20),
        "oos_mdd_pass": bool(oos_mdd > -0.25),
        "win_rate_pass": bool(win_rate_pass),
        "trade_count_pass": bool(is_trade_count >= 100),
        "wf_windows_pass": bool(wf_windows_passed >= 3),
        "wf_consistency_pass": bool(wf_consistency_score >= 0.7),
        "sensitivity_pass": bool(sensitivity_pass),
        "price_ic_pass": bool(ic_validation["price_ic_pass"]),
        "cvd_ic_pass": bool(ic_validation["cvd_ic_pass"]),
        "dsr_pass": bool(dsr > 0),
        "permutation_pass": bool(perm["permutation_test_pass"]),
        "mc_p5_pass": bool(mc["mc_p5_sharpe"] >= 0.5),
    }
    gate1_pass = all(gate1_checks.values())
    failing = [k for k, v in gate1_checks.items() if not v]

    print(f"\n  OVERALL: {'PASS' if gate1_pass else 'FAIL'}")
    if failing:
        print(f"  Failing: {', '.join(failing)}")

    # ── Build JSON ────────────────────────────────────────────────────────────
    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        "universe": PARAMETERS["universe"],
        "active_signal": active_signal,
        "is_period": f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "is_sharpe": is_sharpe, "oos_sharpe": oos_sharpe,
        "is_max_drawdown": is_mdd, "oos_max_drawdown": oos_mdd,
        "win_rate": is_win_rate, "oos_win_rate": oos_win_rate,
        "win_loss_ratio": is_win_loss, "profit_factor": is_profit_factor,
        "trade_count": is_trade_count, "oos_trade_count": oos_trade_count,
        "total_return_is": is_total_return, "total_return_oos": oos_total_return,
        "post_cost_sharpe": is_sharpe,
        "dsr": dsr,
        "mc_p5_sharpe": mc["mc_p5_sharpe"], "mc_median_sharpe": mc["mc_median_sharpe"], "mc_p95_sharpe": mc["mc_p95_sharpe"],
        "sharpe_ci_low": bci["sharpe_ci_low"], "sharpe_ci_high": bci["sharpe_ci_high"],
        "mdd_ci_low": bci["mdd_ci_low"], "mdd_ci_high": bci["mdd_ci_high"],
        "permutation_pvalue": perm["permutation_pvalue"], "permutation_test_pass": perm["permutation_test_pass"],
        "wf_windows_passed": wf_windows_passed, "wf_consistency_score": wf_consistency_score,
        "wf_table": wf_table, "wf_oos_sharpes": [round(s, 4) for s in wf_oos_sharpes],
        "wf_sharpe_std": wf_var["wf_sharpe_std"], "wf_sharpe_min": wf_var["wf_sharpe_min"],
        "ic_validation": {k: v for k, v in ic_validation.items() if k != "per_ticker"},
        "cvd_sensitivity_scan": {k: v for k, v in cvd_scan.items() if not k.startswith("_")},
        "cvd_sensitivity_meta": cvd_meta,
        "sub_period_results": sub_results,
        "is_exit_reasons": is_exit_reasons,
        "per_ticker_trades_is": is_full.get("per_ticker_trades", {}),
        "liquidity_flags_is": is_full.get("liquidity_flags", 0),
        "trade_log_sample": is_trade_log[:20],
        "trade_log_count": len(is_trade_log),
        "gate1_checks": gate1_checks, "gate1_pass": gate1_pass, "failing_criteria": failing,
        "look_ahead_bias_flag": False,
        "look_ahead_bias_notes": [
            "Price breakout: close[T] > rolling_max(close[T-N:T-1]) — no look-ahead.",
            "CVD proxy: computed from same-bar OHLCV at close T — no future data.",
            "Both signals at close T → entry at open T+1 (shifted 1 bar).",
        ],
        "survivorship_bias_flag": True,
        "survivorship_bias_note": (
            "Universe uses current tickers — survivorship bias present. "
            "Likely inflates IS performance vs. live trading."
        ),
    }

    json_path = f"/mnt/c/Users/lamho/repo/quant-zero/backtests/{STRATEGY_NAME}_{TODAY}.json"
    with open(json_path, "w") as fh:
        json.dump(metrics, fh, indent=2, default=str)
    print(f"\nSaved: {json_path}")

    # ── Verdict TXT ───────────────────────────────────────────────────────────
    verdict_lines = [
        f"H11 CVD-Confirmed Breakout — Gate 1 Verdict",
        f"Date: {TODAY}",
        f"IS: {IS_START} to {IS_END}  |  OOS: {OOS_START} to {OOS_END}",
        f"Active signal: {active_signal}",
        "=" * 60,
        f"OVERALL: {'PASS' if gate1_pass else 'FAIL'}",
        "",
        "Core Metrics:",
        f"  IS Sharpe:           {is_sharpe:>8.4f}  {'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'} (>1.0)",
        f"  OOS Sharpe:          {oos_sharpe:>8.4f}  {'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'} (>0.7)",
        f"  IS Max Drawdown:     {is_mdd:>8.1%}  {'PASS' if gate1_checks['is_mdd_pass'] else 'FAIL'} (<20%)",
        f"  OOS Max Drawdown:    {oos_mdd:>8.1%}  {'PASS' if gate1_checks['oos_mdd_pass'] else 'FAIL'} (<25%)",
        f"  Win Rate (IS):       {is_win_rate:>8.1%}  {'PASS' if gate1_checks['win_rate_pass'] else 'FAIL'} (>50%)",
        f"  Win/Loss Ratio:      {is_win_loss:>8.2f}",
        f"  Profit Factor:       {is_profit_factor:>8.4f}",
        f"  Trade Count (IS):    {is_trade_count:>8d}  {'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'} (>=100)",
        "",
        "Sequential IC Validation (Research Director QUA-130):",
        f"  Price Breakout IC:   {ic_validation['avg_price_breakout_ic']:>8.4f}  {'PASS' if gate1_checks['price_ic_pass'] else 'FAIL'} (>0.02)",
        f"  CVD Proxy IC:        {ic_validation['avg_cvd_proxy_ic']:>8.4f}  {'PASS' if gate1_checks['cvd_ic_pass'] else 'FAIL'} (>0.02)",
        f"  Combined IC:         {ic_validation['avg_combined_ic']:>8.4f}",
        f"  Decision: {ic_validation['decision']}",
        "",
        "Walk-Forward (4 windows):",
        f"  Windows Passed:      {wf_windows_passed}/4  {'PASS' if gate1_checks['wf_windows_pass'] else 'FAIL'}",
        f"  Consistency Score:   {wf_consistency_score:>8.4f}  {'PASS' if gate1_checks['wf_consistency_pass'] else 'FAIL'}",
    ]
    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        verdict_lines.append(f"    W{w['window']}: IS {w.get('is_sharpe','?'):>6} OOS {w.get('oos_sharpe','?'):>6} [{status}]")
    verdict_lines += [
        "",
        "Sub-Period Performance:",
    ]
    for name, v in sub_results.items():
        if "sharpe" in v:
            verdict_lines.append(f"  {name}: Sharpe={v['sharpe']:.4f}  MDD={v['max_drawdown']:.1%}  Trades={v['trade_count']}")
    verdict_lines += [
        "",
        "CVD Threshold Sensitivity:",
        f"  Variance: {cvd_meta.get('sharpe_variance_pct', 'N/A')} {'PASS' if sensitivity_pass else 'FAIL'}",
    ]
    for k, v in cvd_scan.items():
        if not k.startswith("_") and isinstance(v, dict) and "sharpe" in v:
            verdict_lines.append(f"    {k}: Sharpe={v['sharpe']:.4f}  Trades={v['trade_count']}")
    verdict_lines += [
        "",
        "Statistical Rigor:",
        f"  DSR:                 {dsr:>12.6f}  {'PASS' if gate1_checks['dsr_pass'] else 'FAIL'}",
        f"  MC p5 Sharpe:        {mc['mc_p5_sharpe']:>12.3f}  {'PASS' if gate1_checks['mc_p5_pass'] else 'FAIL'}",
        f"  Sharpe CI [95%]:     [{bci['sharpe_ci_low']:.3f}, {bci['sharpe_ci_high']:.3f}]",
        f"  Perm p-value:        {perm['permutation_pvalue']:>12.4f}  {'PASS' if gate1_checks['permutation_pass'] else 'FAIL'}",
        "",
        "Risk Flags:",
        f"  Survivorship bias:   PRESENT — current ticker universe inflates IS performance",
        f"  Earnings exclusion:  NOT applied — earnings events included in backtest",
        f"  Look-ahead bias:     None detected (signals computed at close, entry at open T+1)",
        "",
        "FAILING CRITERIA:" if failing else "All criteria passed.",
    ]
    if failing:
        for f_name in failing:
            verdict_lines.append(f"  x {f_name}")

    verdict_txt = "\n".join(verdict_lines)
    verdict_path = f"/mnt/c/Users/lamho/repo/quant-zero/backtests/{STRATEGY_NAME}_{TODAY}_verdict.txt"
    with open(verdict_path, "w") as fh:
        fh.write(verdict_txt)
    print(f"Saved: {verdict_path}")
    print("\n" + "=" * 65)
    print(verdict_txt)

    return metrics, verdict_txt


if __name__ == "__main__":
    metrics, verdict_txt = main()
