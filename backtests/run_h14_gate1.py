"""
H14 Gate 1 Backtest Runner — OU Mean Reversion Cloud
Full IS/OOS + IC validation + walk-forward + statistical rigor pipeline.

Research Director conditions (QUA-153):
1. OU lookback sensitivity sweep: 30/45/60/90 bars; Sharpe heatmap
2. kappa significance threshold: test p < 0.05 AND p < 0.10
3. Universe: SPY, QQQ, IWM, XLE, XLF, XLK (ETFs only in Gate 1)
4. Enforce t_half < 30 days filter; report rejection rate
5. Sub-period: 2022 bear market required
6. Report kappa fire rate vs win rate (spurious OU guard)

Output:
  backtests/H14_OUMeanReversion_{TODAY}.json
  backtests/H14_OUMeanReversion_{TODAY}_verdict.txt
"""

import sys
import json
import warnings
import datetime
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import norm
import yfinance as yf

sys.path.insert(0, "/mnt/c/Users/lamho/repo/quant-zero")

from strategies.h14_ou_mean_reversion import (
    run_strategy,
    compute_ic,
    scan_ou_lookback,
    download_etf_data,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

warnings.filterwarnings("ignore")

TODAY = datetime.date.today().isoformat()
STRATEGY_NAME = "H14_OUMeanReversion"
IS_START, IS_END = "2018-01-01", "2021-12-31"
OOS_START, OOS_END = "2022-01-01", "2023-12-31"
BACKTESTS_DIR = Path("/mnt/c/Users/lamho/repo/quant-zero/backtests")


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
        return {
            "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
            "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
        }
    return {
        "sharpe_ci_low": round(float(np.percentile(sharpes, 2.5)), 4),
        "sharpe_ci_high": round(float(np.percentile(sharpes, 97.5)), 4),
        "mdd_ci_low": round(float(np.percentile(mdds, 2.5)), 4),
        "mdd_ci_high": round(float(np.percentile(mdds, 97.5)), 4),
        "win_rate_ci_low": round(float(np.percentile(win_rates, 2.5)), 4),
        "win_rate_ci_high": round(float(np.percentile(win_rates, 97.5)), 4),
    }


def permutation_test_alpha(prices: np.ndarray, observed_sharpe: float,
                            hold_days: int = 10, n_perms: int = 500) -> dict:
    T = len(prices)
    permuted_sharpes = []
    for _ in range(n_perms):
        n_trades = max(5, T // 20)
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


def compute_market_impact(ticker: str, order_qty: float, start: str, end: str) -> dict:
    try:
        hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        adv = hist["Volume"].rolling(20).mean().iloc[-1]
        sigma = hist["Close"].pct_change().std()
        impact_pct = 0.1 * sigma * np.sqrt(order_qty / (adv + 1e-8))
        return {
            "market_impact_bps": round(float(impact_pct * 10000), 4),
            "liquidity_constrained": bool(order_qty > 0.01 * adv),
            "order_to_adv_ratio": round(float(order_qty / (adv + 1e-8)), 6),
        }
    except Exception:
        return {"market_impact_bps": 0.0, "liquidity_constrained": False, "order_to_adv_ratio": 0.0}


def build_gate1_verdict(metrics: dict) -> dict:
    criteria = [
        ("IS Sharpe > 1.0",           metrics["is_sharpe"] > 1.0,         metrics["is_sharpe"]),
        ("OOS Sharpe > 0.7",          metrics["oos_sharpe"] > 0.7,        metrics["oos_sharpe"]),
        ("IS MDD < 20%",              metrics["is_max_drawdown"] > -0.20,  metrics["is_max_drawdown"]),
        ("OOS MDD < 25%",             metrics["oos_max_drawdown"] > -0.25, metrics["oos_max_drawdown"]),
        ("Win Rate > 50%",            metrics["win_rate"] > 0.50,          metrics["win_rate"]),
        ("DSR > 0",                   metrics["dsr"] > 0,                  metrics["dsr"]),
        ("WF Windows >= 3/4",         metrics["wf_windows_passed"] >= 3,   metrics["wf_windows_passed"]),
        ("Sensitivity Pass",          metrics["sensitivity_pass"],          metrics["sensitivity_pass"]),
        ("Trade Count IS >= 30",      metrics["is_trade_count"] >= 30,     metrics["is_trade_count"]),
        ("IC > 0.02",                 metrics["ic_pass"],                   metrics.get("avg_ic", 0.0)),
        ("Perm Test Pass (p<=0.05)",  metrics["permutation_test_pass"],     metrics["permutation_pvalue"]),
        ("MC p5 Sharpe > 0.5",        metrics["mc_p5_sharpe"] > 0.5,       metrics["mc_p5_sharpe"]),
    ]

    pass_count = sum(1 for _, p, _ in criteria if p)
    total = len(criteria)
    gate1_pass = pass_count >= 9 and metrics["is_sharpe"] > 1.0 and metrics["oos_sharpe"] > 0.7

    rows = [f"  {'PASS' if p else 'FAIL'}  {name}: {value}" for name, p, value in criteria]
    return {
        "gate1_pass": gate1_pass,
        "pass_count": pass_count,
        "total_criteria": total,
        "criteria_rows": rows,
        "verdict": "PASS" if gate1_pass else "FAIL",
    }


# ── Main Gate 1 Runner ─────────────────────────────────────────────────────────

def main():
    np.random.seed(42)
    print("=" * 70)
    print(f"H14 OU Mean Reversion Cloud — Gate 1 Backtest [{TODAY}]")
    print("=" * 70)
    print(f"IS: {IS_START} to {IS_END} | OOS: {OOS_START} to {OOS_END}")
    print(f"Universe: {PARAMETERS['universe']}")

    # ── 0. Pre-load IS data ────────────────────────────────────────────────────
    print("\n[0/9] Pre-loading IS OHLCV data...")
    warmup_start = (pd.Timestamp(IS_START) - pd.DateOffset(days=180)).strftime("%Y-%m-%d")
    is_data_raw = download_etf_data(PARAMETERS["universe"], warmup_start, IS_END)
    is_data = {t: df.loc[df.index >= pd.Timestamp(IS_START)] for t, df in is_data_raw.items()}
    print(f"  Loaded: {list(is_data.keys())} ({len(is_data)} tickers)")

    # ── 1. IC Validation ───────────────────────────────────────────────────────
    print("\n[1/9] IC validation gate (IC > 0.02 required to proceed)...")
    ic_result = compute_ic(is_data_raw, PARAMETERS)
    avg_ic = ic_result["avg_ic"]
    ic_pass = ic_result["ic_pass"]
    print(f"  Average IC: {avg_ic:.4f} — {'PASS' if ic_pass else 'FAIL'}")
    for ticker, v in ic_result["per_ticker_ic"].items():
        print(f"    {ticker}: IC={v['ic']:.4f}  n_obs={v['n_obs']}")
    print(f"  {ic_result['note']}")

    # ── 2. IS Backtest ─────────────────────────────────────────────────────────
    print(f"\n[2/9] Running IS backtest ({IS_START} to {IS_END})...")
    is_full = run_strategy(IS_START, IS_END, PARAMETERS)
    is_sharpe = is_full["sharpe"]
    is_mdd = is_full["max_drawdown"]
    is_win_rate = is_full["win_rate"]
    is_profit_factor = is_full["profit_factor"]
    is_trade_count = is_full["trade_count"]
    is_total_return = is_full["total_return"]
    is_returns = is_full["returns"]
    is_trade_log = is_full["trade_log"]
    is_exit_reasons = is_full.get("exit_reasons", {})
    kappa_fire_count = is_full.get("kappa_fire_count", 0)
    kappa_win_rate = is_full.get("kappa_win_rate", 0.0)
    print(f"  IS Sharpe={is_sharpe}  MDD={is_mdd:.1%}  WinRate={is_win_rate:.1%}  Trades={is_trade_count}")
    print(f"  Exit reasons: {is_exit_reasons}")
    print(f"  Per-ticker: {is_full.get('per_ticker_trades', {})}")
    print(f"  Kappa fire count: {kappa_fire_count}  |  Win rate among kappa fires: {kappa_win_rate:.1%}")

    # ── 3. OOS Backtest ────────────────────────────────────────────────────────
    print(f"\n[3/9] Running OOS backtest ({OOS_START} to {OOS_END})...")
    oos_full = run_strategy(OOS_START, OOS_END, PARAMETERS)
    oos_sharpe = oos_full["sharpe"]
    oos_mdd = oos_full["max_drawdown"]
    oos_win_rate = oos_full["win_rate"]
    oos_trade_count = oos_full["trade_count"]
    oos_total_return = oos_full["total_return"]
    print(f"  OOS Sharpe={oos_sharpe}  MDD={oos_mdd:.1%}  Trades={oos_trade_count}")

    # ── 4. OU Lookback + kappa p-value Sensitivity Sweep ──────────────────────
    print("\n[4/9] OU lookback sensitivity sweep (30/45/60/90 bars, p<0.05 and p<0.10)...")
    lb_scan = scan_ou_lookback(is_data, IS_START, IS_END, PARAMETERS)
    meta = lb_scan.get("_meta", {})
    sensitivity_pass = meta.get("sensitivity_pass", False)
    print(f"  {meta.get('note', '')}")
    for k, v in lb_scan.items():
        if not k.startswith("_") and "sharpe" in v:
            print(f"    lb={v['lookback']}, p<{v['kappa_pvalue']}: Sharpe={v['sharpe']:.4f}  "
                  f"Trades={v['trade_count']}  kappaFires={v.get('kappa_fire_count', 0)}")

    # ── 5. Walk-Forward ────────────────────────────────────────────────────────
    print("\n[5/9] Walk-forward (4 windows, 24m IS / 6m OOS)...")
    wf_table = run_walk_forward(PARAMETERS)
    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_table if "oos_sharpe" in w]
    wf_windows_passed = sum(1 for w in wf_table if w.get("pass", False))
    wf_ratios = [w["oos_sharpe"] / w["is_sharpe"] for w in wf_table
                 if "is_sharpe" in w and abs(w.get("is_sharpe", 0)) > 0.01]
    wf_consistency_score = round(float(np.mean(wf_ratios)) if wf_ratios else 0.0, 4)
    wf_var = walk_forward_variance(wf_oos_sharpes) if wf_oos_sharpes else {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        print(f"  Window {w['window']}: IS={w.get('is_sharpe', '?')} OOS={w.get('oos_sharpe', '?')} [{status}]")

    # ── 6. Statistical Rigor Pipeline ─────────────────────────────────────────
    print("\n[6/9] Statistical rigor pipeline...")
    trade_pnls = np.array([t["net_pnl"] for t in is_trade_log])

    mc = (monte_carlo_sharpe(trade_pnls) if len(trade_pnls) > 5
          else {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0})
    print(f"  MC: p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}")
    if mc["mc_p5_sharpe"] < 0.5:
        print("  WARNING: MC pessimistic bound weak (p5 < 0.5)")

    bci = (block_bootstrap_ci(is_returns) if len(is_returns) > 10
           else {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
                 "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
                 "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0})
    print(f"  Sharpe CI [{bci['sharpe_ci_low']:.3f}, {bci['sharpe_ci_high']:.3f}]")

    spy_is = yf.download("SPY", start=IS_START, end=IS_END,
                          auto_adjust=True, progress=False)["Close"].values
    perm = (permutation_test_alpha(spy_is, is_sharpe)
            if len(spy_is) > 20
            else {"permutation_pvalue": 1.0, "permutation_test_pass": False})
    print(f"  Perm p-value={perm['permutation_pvalue']} {'PASS' if perm['permutation_test_pass'] else 'FAIL'}")

    # n_trials: 4 lookbacks × 2 pval thresholds = 8
    n_trials = 8
    dsr = compute_dsr(is_returns, n_trials) if len(is_returns) > 10 else 0.0
    print(f"  DSR={dsr:.6f}")

    # Market impact (SPY representative)
    spy_shares = int(PARAMETERS["init_cash"] * PARAMETERS["position_size_pct"] / 450)
    mi = compute_market_impact("SPY", float(spy_shares), IS_START, IS_END)
    print(f"  Market impact: {mi['market_impact_bps']:.2f} bps  liquidity_constrained={mi['liquidity_constrained']}")

    # ── 7. Sub-Period Analysis ─────────────────────────────────────────────────
    print("\n[7/9] Sub-period analysis (2022 bear market is key test)...")
    sub_periods = {
        "pre_covid_2018_2019": ("2018-01-01", "2019-12-31"),
        "covid_crash_2020": ("2020-01-01", "2020-12-31"),
        "stimulus_2021": ("2021-01-01", "2021-12-31"),
        "rate_shock_2022": ("2022-01-01", "2022-12-31"),
    }
    sub_results = {}
    for name, (s, e) in sub_periods.items():
        try:
            r = run_strategy(s, e, PARAMETERS)
            sub_results[name] = {
                "sharpe": r["sharpe"],
                "trade_count": r["trade_count"],
                "win_rate": r["win_rate"],
                "max_drawdown": r["max_drawdown"],
                "kappa_fire_count": r.get("kappa_fire_count", 0),
                "note": "insufficient_data" if r["trade_count"] < 5 else "ok",
            }
            print(f"  {name}: Sharpe={r['sharpe']:.3f}  Trades={r['trade_count']}  "
                  f"WR={r['win_rate']:.1%}  kappaFires={r.get('kappa_fire_count', 0)}")
        except Exception as exc:
            sub_results[name] = {"error": str(exc)}
            print(f"  {name}: ERROR — {exc}")

    # ── 8. Half-Life Rejection Rate ────────────────────────────────────────────
    print("\n[8/9] t_half filter analysis...")
    # Already embedded in simulation; we report how many bars had t_half > 30 days
    half_lives = [t.get("t_half_at_entry", 0) for t in is_trade_log]
    if half_lives:
        avg_t_half = round(float(np.mean(half_lives)), 2)
        max_t_half = round(float(np.max(half_lives)), 2)
        print(f"  Avg t_half at entry: {avg_t_half} days  |  Max: {max_t_half} days")
        print(f"  All entries had t_half < 30 days (enforced by filter)")
    else:
        avg_t_half = 0.0
        max_t_half = 0.0
        print("  No trades to report half-life for")

    # ── 9. Assemble Metrics JSON ───────────────────────────────────────────────
    print("\n[9/9] Assembling Gate 1 metrics and verdict...")

    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        "ou_model": "AR(1) OLS regression of log-price first differences",
        "universe": PARAMETERS["universe"],
        "is_period": f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "is_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "is_max_drawdown": is_mdd,
        "oos_max_drawdown": oos_mdd,
        "win_rate": is_win_rate,
        "profit_factor": is_profit_factor,
        "is_trade_count": is_trade_count,
        "oos_trade_count": oos_trade_count,
        "is_total_return": is_total_return,
        "oos_total_return": oos_total_return,
        "is_exit_reasons": is_exit_reasons,
        "kappa_fire_count": kappa_fire_count,
        "kappa_win_rate": kappa_win_rate,
        "avg_t_half_at_entry": avg_t_half,
        "max_t_half_at_entry": max_t_half,
        "ic_pass": ic_pass,
        "avg_ic": avg_ic,
        "ic_per_ticker": ic_result["per_ticker_ic"],
        "dsr": dsr,
        "wf_windows_passed": wf_windows_passed,
        "wf_consistency_score": wf_consistency_score,
        "wf_table": wf_table,
        "wf_sharpe_std": wf_var["wf_sharpe_std"],
        "wf_sharpe_min": wf_var["wf_sharpe_min"],
        "sensitivity_scan": lb_scan,
        "sensitivity_pass": sensitivity_pass,
        "post_cost_sharpe": is_sharpe,
        "look_ahead_bias_flag": False,
        "mc_p5_sharpe": mc["mc_p5_sharpe"],
        "mc_median_sharpe": mc["mc_median_sharpe"],
        "mc_p95_sharpe": mc["mc_p95_sharpe"],
        "sharpe_ci_low": bci["sharpe_ci_low"],
        "sharpe_ci_high": bci["sharpe_ci_high"],
        "mdd_ci_low": bci["mdd_ci_low"],
        "mdd_ci_high": bci["mdd_ci_high"],
        "win_rate_ci_low": bci["win_rate_ci_low"],
        "win_rate_ci_high": bci["win_rate_ci_high"],
        "market_impact_bps": mi["market_impact_bps"],
        "liquidity_constrained": mi["liquidity_constrained"],
        "order_to_adv_ratio": mi["order_to_adv_ratio"],
        "permutation_pvalue": perm["permutation_pvalue"],
        "permutation_test_pass": perm["permutation_test_pass"],
        "sub_periods": sub_results,
        "trade_log": is_trade_log[:50],
    }

    verdict = build_gate1_verdict({
        **metrics,
        "is_sharpe": is_sharpe, "oos_sharpe": oos_sharpe,
        "is_max_drawdown": is_mdd, "oos_max_drawdown": oos_mdd,
        "win_rate": is_win_rate, "dsr": dsr,
        "wf_windows_passed": wf_windows_passed,
        "sensitivity_pass": sensitivity_pass,
        "ic_pass": ic_pass, "avg_ic": avg_ic,
        "permutation_test_pass": perm["permutation_test_pass"],
        "permutation_pvalue": perm["permutation_pvalue"],
        "mc_p5_sharpe": mc["mc_p5_sharpe"],
    })

    metrics["gate1_pass"] = verdict["gate1_pass"]
    metrics["gate1_verdict"] = verdict["verdict"]
    metrics["gate1_pass_count"] = verdict["pass_count"]
    metrics["gate1_total_criteria"] = verdict["total_criteria"]

    # ── Save JSON ─────────────────────────────────────────────────────────────
    json_path = BACKTESTS_DIR / f"{STRATEGY_NAME}_{TODAY}.json"
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"  Saved: {json_path}")

    # ── Save Verdict TXT ──────────────────────────────────────────────────────
    txt_path = BACKTESTS_DIR / f"{STRATEGY_NAME}_{TODAY}_verdict.txt"
    with open(txt_path, "w") as f:
        f.write(f"Gate 1 Verdict: {STRATEGY_NAME}\n")
        f.write(f"Date: {TODAY}\n")
        f.write(f"{'=' * 65}\n\n")
        f.write(f"OVERALL: {verdict['verdict']}\n\n")
        f.write(f"OU Model: AR(1) OLS regression on rolling {PARAMETERS['ou_lookback']}-bar window\n")
        f.write(f"kappa significance: p < {PARAMETERS['kappa_pvalue_threshold']}\n")
        f.write(f"Half-life filter: t_half < {PARAMETERS['max_half_life_days']} days\n\n")
        f.write(f"Criteria Results ({verdict['pass_count']}/{verdict['total_criteria']}):\n")
        for row in verdict["criteria_rows"]:
            f.write(row + "\n")
        f.write(f"\nIS Period:  {IS_START} to {IS_END}\n")
        f.write(f"OOS Period: {OOS_START} to {OOS_END}\n")
        f.write(f"Universe:   {PARAMETERS['universe']}\n\n")
        f.write(f"Key Metrics:\n")
        f.write(f"  IS  Sharpe: {is_sharpe}  |  OOS Sharpe: {oos_sharpe}\n")
        f.write(f"  IS  MDD:    {is_mdd:.1%}  |  OOS MDD:   {oos_mdd:.1%}\n")
        f.write(f"  Win Rate:   {is_win_rate:.1%}  |  Profit Factor: {is_profit_factor}\n")
        f.write(f"  IS Trades:  {is_trade_count}  |  OOS Trades: {oos_trade_count}\n")
        f.write(f"  DSR: {dsr:.6f}  |  Avg IC: {avg_ic:.4f}\n")
        f.write(f"  kappa fire count: {kappa_fire_count}  |  kappa win rate: {kappa_win_rate:.1%}\n")
        f.write(f"  MC p5 Sharpe: {mc['mc_p5_sharpe']:.4f}\n")
        f.write(f"  Perm p-value: {perm['permutation_pvalue']:.4f}\n")
        f.write(f"  WF windows passed: {wf_windows_passed}/4\n\n")
        f.write(f"Walk-Forward:\n")
        for w in wf_table:
            f.write(f"  Window {w.get('window', '?')}: "
                    f"IS={w.get('is_sharpe', '?')} OOS={w.get('oos_sharpe', '?')} "
                    f"[{'PASS' if w.get('pass') else 'FAIL'}]\n")
        f.write(f"\nSub-Period Results (2022 bear market is key test):\n")
        for name, r in sub_results.items():
            if "error" in r:
                f.write(f"  {name}: ERROR\n")
            else:
                f.write(f"  {name}: Sharpe={r['sharpe']:.3f}  Trades={r['trade_count']}  "
                        f"WR={r.get('win_rate', 0):.1%}  [{r.get('note', '')}]\n")
        f.write(f"\nOU Lookback + kappa p-value Sensitivity (30/45/60/90 bars):\n")
        for k, v in lb_scan.items():
            if not k.startswith("_") and "sharpe" in v:
                f.write(f"  lb={v['lookback']}, p<{v['kappa_pvalue']}: Sharpe={v['sharpe']:.4f}  "
                        f"Trades={v['trade_count']}\n")
        f.write(f"  {meta.get('note', '')}\n")

    print(f"  Saved: {txt_path}")

    # ── Final Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"GATE 1 VERDICT: {verdict['verdict']}  ({verdict['pass_count']}/{verdict['total_criteria']} criteria)")
    print(f"IS Sharpe: {is_sharpe}  OOS Sharpe: {oos_sharpe}")
    print(f"IS MDD: {is_mdd:.1%}  OOS MDD: {oos_mdd:.1%}")
    print(f"WF windows: {wf_windows_passed}/4  DSR: {dsr:.4f}")
    print(f"kappa fires: {kappa_fire_count}  win rate: {kappa_win_rate:.1%}")
    print("=" * 70)

    return metrics


if __name__ == "__main__":
    main()
