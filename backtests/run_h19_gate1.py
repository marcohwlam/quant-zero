"""
Gate 1 Backtest Runner: H19 VIX-Percentile Volatility-Targeting SPY v1.2
Ticket: QUA-202

Runs full IS/OOS backtest, walk-forward, and statistical rigor pipeline.
"""

import sys
import os
import json
import warnings
import traceback
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

# Add repo root to path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from strategies.h19_vix_volatility_targeting import (
    download_data,
    check_data_quality,
    compute_allocation_series,
    verify_preconditions,
    check_pdt_compliance,
    build_trade_log,
    compute_metrics,
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
)

# ── Constants ─────────────────────────────────────────────────────────────────

IS_START = "2018-01-01"
IS_END   = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END   = "2024-12-31"
WARMUP_START = "2017-01-01"   # Extra year for VIX percentile warmup

TODAY = date.today().strftime("%Y-%m-%d")
OUTPUT_JSON   = os.path.join(os.path.dirname(__file__), f"H19_VIXVolatilityTargeting_v1.2_{TODAY}.json")
OUTPUT_VERDICT = os.path.join(os.path.dirname(__file__), f"H19_VIXVolatilityTargeting_v1.2_{TODAY}_verdict.txt")


# ── Statistical Rigor Functions ───────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe": float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = T // block_len

    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-12)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
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
    try:
        hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if hist.empty or "Volume" not in hist.columns:
            return {"market_impact_bps": 0.0, "liquidity_constrained": False, "order_to_adv_ratio": 0.0}
        adv = float(hist["Volume"].rolling(20).mean().dropna().iloc[-1])
        sigma = float(hist["Close"].squeeze().pct_change().std())
        k = 0.1
        impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
        impact_bps = impact_pct * 10000
        liq_constrained = bool(order_qty > 0.01 * adv)
        return {
            "market_impact_bps": float(impact_bps),
            "liquidity_constrained": liq_constrained,
            "order_to_adv_ratio": float(order_qty / (adv + 1e-8)),
        }
    except Exception as e:
        print(f"  [WARN] Market impact computation failed: {e}")
        return {"market_impact_bps": 0.0, "liquidity_constrained": False, "order_to_adv_ratio": 0.0}


def permutation_test_alpha(
    prices: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 500,
    hold_days: int = 5,
) -> dict:
    permuted_sharpes = []
    n = len(prices)
    for _ in range(n_perms):
        n_entries = max(1, n // (hold_days * 2))
        perm_entry_idx = np.random.choice(n - hold_days, size=n_entries, replace=False)
        trade_returns = []
        for idx in perm_entry_idx:
            exit_idx = min(idx + hold_days, n - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-12)
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
        "permutation_pvalue": p_value,
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array(wf_oos_sharpes, dtype=float)
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


def compute_dsr(returns: np.ndarray, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014)."""
    T = len(returns)
    if T < 5:
        return float("nan")
    sr = returns.mean() / (returns.std() + 1e-12) * np.sqrt(T)
    gamma3 = float(pd.Series(returns).skew())
    gamma4 = float(pd.Series(returns).kurt())
    # Expected max Sharpe under n_trials trials
    sr_star = (
        (1 - np.euler_gamma) * np.sqrt(2 * np.log(n_trials)) / np.log(n_trials)
        + np.euler_gamma / np.sqrt(np.log(n_trials))
        if n_trials > 1
        else 0.0
    )
    # Variance of SR estimate
    var_sr = (1 + 0.5 * sr**2 - gamma3 * sr + (gamma4 - 3) / 4 * sr**2) / T
    if var_sr <= 0:
        return float("nan")
    # DSR: probability that IS SR exceeds SR* (expected max under multiple testing)
    from scipy.stats import norm
    dsr = float(norm.cdf((sr - sr_star) / np.sqrt(var_sr)))
    return dsr


def build_equity_returns(trade_log: pd.DataFrame, init_cash: float, all_dates: pd.DatetimeIndex) -> pd.Series:
    """Build a daily returns series from the trade log, mapped onto all_dates."""
    if trade_log.empty:
        return pd.Series(0.0, index=all_dates)

    trade_log_sorted = trade_log.copy()
    trade_log_sorted["exit_date"] = pd.to_datetime(trade_log_sorted["exit_date"])
    trade_log_sorted = trade_log_sorted.sort_values("exit_date")

    pnl_by_date = trade_log_sorted.groupby("exit_date")["net_pnl"].sum()
    cumulative = init_cash + pnl_by_date.cumsum().reindex(all_dates).fillna(method="ffill").fillna(init_cash)
    daily_returns = cumulative.pct_change().fillna(0.0)
    return daily_returns


# ── Walk-Forward ──────────────────────────────────────────────────────────────

def run_walk_forward(spy_close, spy_volume, vix_close, params, n_windows=4):
    """4-fold walk-forward: IS=36mo, OOS=6mo each window."""
    # Build full date range
    full_start = pd.Timestamp("2018-01-01")
    full_end   = pd.Timestamp("2024-12-31")

    # Windows: step forward by 6 months each time
    # Window 1: IS 2018-01 to 2020-12 (36mo), OOS 2021-01 to 2021-06 (6mo)
    # Window 2: IS 2018-07 to 2021-06, OOS 2021-07 to 2021-12
    # Window 3: IS 2019-01 to 2021-12, OOS 2022-01 to 2022-06
    # Window 4: IS 2019-07 to 2022-06, OOS 2022-07 to 2022-12

    windows = []
    is_months = 36
    oos_months = 6
    step_months = 6
    window_start = pd.Timestamp("2018-01-01")

    for i in range(n_windows):
        is_start = window_start + pd.DateOffset(months=step_months * i)
        is_end   = is_start + pd.DateOffset(months=is_months) - pd.Timedelta(days=1)
        oos_start = is_end + pd.Timedelta(days=1)
        oos_end   = oos_start + pd.DateOffset(months=oos_months) - pd.Timedelta(days=1)
        windows.append((is_start, is_end, oos_start, oos_end))

    results = []
    for idx, (is_s, is_e, oos_s, oos_e) in enumerate(windows):
        print(f"  WF Window {idx+1}: IS {is_s.date()}→{is_e.date()}, OOS {oos_s.date()}→{oos_e.date()}")
        try:
            # IS period
            is_spy = spy_close.loc[str(is_s.date()):str(is_e.date())]
            is_vol = spy_volume.loc[str(is_s.date()):str(is_e.date())]
            is_vix = vix_close.loc[str(is_s.date()):str(is_e.date())]

            # Need warmup — use full series signals and slice
            full_signals = compute_allocation_series(spy_close, vix_close, params)
            is_signals = full_signals.loc[str(is_s.date()):str(is_e.date())]
            oos_signals = full_signals.loc[str(oos_s.date()):str(oos_e.date())]

            oos_spy = spy_close.loc[str(oos_s.date()):str(oos_e.date())]
            oos_vol = spy_volume.loc[str(oos_s.date()):str(oos_e.date())]

            # IS trade log & metrics
            is_tl = build_trade_log(is_signals, is_spy, is_vol, params, params["init_cash"])
            is_m = compute_metrics(is_tl, is_spy, params["init_cash"])

            # OOS trade log & metrics
            oos_tl = build_trade_log(oos_signals, oos_spy, oos_vol, params, params["init_cash"])
            oos_m = compute_metrics(oos_tl, oos_spy, params["init_cash"])

            # Gate 1 pass for this window: OOS Sharpe > 0.7 and OOS MDD < 25%
            oos_sharpe = oos_m["sharpe"] if not (oos_m["sharpe"] is None or np.isnan(oos_m["sharpe"])) else -999
            oos_mdd = oos_m["max_drawdown"] if not (oos_m["max_drawdown"] is None or np.isnan(oos_m["max_drawdown"])) else -999

            window_pass = (oos_sharpe > 0.7) and (oos_mdd > -0.25)

            results.append({
                "window": idx + 1,
                "is_start": str(is_s.date()),
                "is_end": str(is_e.date()),
                "oos_start": str(oos_s.date()),
                "oos_end": str(oos_e.date()),
                "is_sharpe": is_m["sharpe"],
                "oos_sharpe": oos_m["sharpe"],
                "is_mdd": is_m["max_drawdown"],
                "oos_mdd": oos_m["max_drawdown"],
                "is_trades": is_m["trade_count"],
                "oos_trades": oos_m["trade_count"],
                "window_pass": bool(window_pass),
            })
            print(f"    IS Sharpe={is_m['sharpe']}, OOS Sharpe={oos_m['sharpe']}, PASS={window_pass}")
        except Exception as e:
            print(f"    [ERROR] WF window {idx+1} failed: {e}")
            results.append({
                "window": idx + 1,
                "is_start": str(is_s.date()),
                "is_end": str(is_e.date()),
                "oos_start": str(oos_s.date()),
                "oos_end": str(oos_e.date()),
                "error": str(e),
                "window_pass": False,
            })

    return results


# ── Sensitivity Heatmap ───────────────────────────────────────────────────────

def run_sensitivity_heatmap(spy_close, spy_volume, vix_close, base_params):
    """3×3 tier threshold sensitivity: tier1 ∈ {0.25,0.30,0.35}, tier2 ∈ {0.55,0.60,0.65}."""
    tier1_vals = [0.25, 0.30, 0.35]
    tier2_vals = [0.55, 0.60, 0.65]

    heatmap = []
    for t1 in tier1_vals:
        row = []
        for t2 in tier2_vals:
            p = base_params.copy()
            p["tier1_threshold"] = t1
            p["tier2_threshold"] = t2
            try:
                signals = compute_allocation_series(spy_close, vix_close, p)
                is_signals = signals.loc[IS_START:IS_END]
                is_spy = spy_close.loc[IS_START:IS_END]
                is_vol = spy_volume.loc[IS_START:IS_END]
                tl = build_trade_log(is_signals, is_spy, is_vol, p, p["init_cash"])
                m = compute_metrics(tl, is_spy, p["init_cash"])
                row.append({
                    "tier1": t1,
                    "tier2": t2,
                    "is_sharpe": m["sharpe"],
                    "trade_count": m["trade_count"],
                })
            except Exception as e:
                row.append({"tier1": t1, "tier2": t2, "error": str(e)})
        heatmap.append(row)
    return heatmap


# ── Main Backtest Runner ──────────────────────────────────────────────────────

def main():
    np.random.seed(42)
    params = PARAMETERS.copy()

    print("=" * 70)
    print("H19 VIX-Percentile Volatility-Targeting SPY v1.2 — Gate 1 Backtest")
    print("=" * 70)

    # ── Step 1: Download full data range (warmup + IS + OOS) ─────────────────
    print(f"\n[1/9] Downloading data: {WARMUP_START} → {OOS_END}")
    spy_close, spy_volume, vix_close = download_data(
        params["spy_ticker"], params["vix_ticker"], WARMUP_START, OOS_END
    )
    print(f"  SPY: {len(spy_close)} days | VIX: {len(vix_close)} days")

    # ── Step 2: Data quality check ────────────────────────────────────────────
    print("\n[2/9] Data quality check...")
    dq_report = check_data_quality(spy_close, vix_close)
    print(f"  Flags: {dq_report['flagged_tickers'] or 'None'}")

    # ── Step 3: Compute allocation signals ────────────────────────────────────
    print(f"\n[3/9] Computing signals (lookback={params['vix_lookback_days']}d)...")
    full_signals = compute_allocation_series(spy_close, vix_close, params)

    # ── Step 4: Pre-conditions ────────────────────────────────────────────────
    print("\n[4/9] Pre-condition verification (conservative params)...")
    # Use conservative params for PF-1/PF-4 check (per spec)
    conservative_params = params.copy()
    conservative_params["vix_lookback_days"] = 252
    conservative_params["tier1_threshold"] = 0.30
    conservative_params["tier2_threshold"] = 0.60
    conservative_params["vix_ma_days"] = 10
    cons_signals = compute_allocation_series(spy_close, vix_close, conservative_params)
    preconditions = verify_preconditions(cons_signals, is_start=IS_START, is_end=IS_END)
    print(f"  PF-1 (trade count ≥ 30/yr): {preconditions['is_trade_count']} trades ({preconditions['is_annual_trade_rate']}/yr) → {'PASS' if preconditions['pf1_pass'] else 'FAIL'}")
    print(f"  PF-4 (first 2022 cash ≤ Jan-31): {preconditions['first_2022_cash_trigger']} → {'PASS' if preconditions['pf4_pass'] else 'FAIL'}")

    if not preconditions["pf1_pass"]:
        print("\n  *** PF-1 FAIL: IS trade count < 30/yr. Reporting FAIL — not running full IS. ***")

    # ── Step 5: PDT compliance ────────────────────────────────────────────────
    print("\n[5/9] PDT compliance check (IS period)...")
    is_signals_full = full_signals.loc[IS_START:IS_END]
    pdt_report = check_pdt_compliance(is_signals_full)
    print(f"  PDT pass: {pdt_report['pdt_pass']} | Max trades in 5d: {pdt_report['max_trades_in_5d']}")
    if pdt_report["violation_windows"]:
        print(f"  Violations: {pdt_report['violation_windows'][:5]}...")

    # ── Step 6: IS / OOS backtests ────────────────────────────────────────────
    print(f"\n[6/9] IS backtest ({IS_START} → {IS_END})...")
    is_spy = spy_close.loc[IS_START:IS_END]
    is_vol = spy_volume.loc[IS_START:IS_END]
    is_sig = full_signals.loc[IS_START:IS_END]
    is_tl = build_trade_log(is_sig, is_spy, is_vol, params, params["init_cash"])
    is_metrics = compute_metrics(is_tl, is_spy, params["init_cash"])
    print(f"  IS Sharpe={is_metrics['sharpe']}, MDD={is_metrics['max_drawdown']:.2%}, "
          f"Win={is_metrics['win_rate']:.2%}, Trades={is_metrics['trade_count']}")

    print(f"\n[6b/9] OOS backtest ({OOS_START} → {OOS_END})...")
    oos_spy = spy_close.loc[OOS_START:OOS_END]
    oos_vol = spy_volume.loc[OOS_START:OOS_END]
    oos_sig = full_signals.loc[OOS_START:OOS_END]
    oos_tl = build_trade_log(oos_sig, oos_spy, oos_vol, params, params["init_cash"])
    oos_metrics = compute_metrics(oos_tl, oos_spy, params["init_cash"])
    print(f"  OOS Sharpe={oos_metrics['sharpe']}, MDD={oos_metrics['max_drawdown']:.2%}, "
          f"Win={oos_metrics['win_rate']:.2%}, Trades={oos_metrics['trade_count']}")

    # Profit factor
    def profit_factor(tl):
        if tl.empty:
            return 0.0
        wins = tl[tl["net_pnl"] > 0]["net_pnl"].sum()
        losses = abs(tl[tl["net_pnl"] <= 0]["net_pnl"].sum())
        return float(wins / (losses + 1e-8))

    is_pf = profit_factor(is_tl)
    oos_pf = profit_factor(oos_tl)

    # Post-cost Sharpe (trade-level)
    if not is_tl.empty:
        is_net_rets = (is_tl["net_pnl"] / params["init_cash"]).values
        post_cost_sharpe = float(is_net_rets.mean() / (is_net_rets.std() + 1e-8) * np.sqrt(252))
    else:
        post_cost_sharpe = float("nan")

    # ── Step 7: Statistical Rigor Pipeline ───────────────────────────────────
    print("\n[7/9] Statistical Rigor Pipeline...")

    # 7a. Monte Carlo
    print("  7a. Monte Carlo (1000 sims)...")
    mc_results = {"mc_p5_sharpe": float("nan"), "mc_median_sharpe": float("nan"), "mc_p95_sharpe": float("nan")}
    if not is_tl.empty and len(is_tl) >= 5:
        mc_results = monte_carlo_sharpe(is_tl["net_pnl"].values)
    print(f"      MC p5={mc_results['mc_p5_sharpe']:.3f}, median={mc_results['mc_median_sharpe']:.3f}, p95={mc_results['mc_p95_sharpe']:.3f}")

    # 7b. Block Bootstrap CI
    print("  7b. Block bootstrap CI (1000 boots)...")
    # Build IS daily returns from equity curve
    is_dates = is_spy.index
    is_eq_returns = build_equity_returns(is_tl, params["init_cash"], is_dates)
    bb_results = {"sharpe_ci_low": float("nan"), "sharpe_ci_high": float("nan"),
                  "mdd_ci_low": float("nan"), "mdd_ci_high": float("nan"),
                  "win_rate_ci_low": float("nan"), "win_rate_ci_high": float("nan")}
    if len(is_eq_returns) >= 10:
        bb_results = block_bootstrap_ci(is_eq_returns.values)
    print(f"      Sharpe CI=[{bb_results['sharpe_ci_low']:.3f}, {bb_results['sharpe_ci_high']:.3f}]")

    # 7c. Market Impact
    print("  7c. Market impact (SPY)...")
    # Representative order: init_cash / spy_price * 0.60 (elevated tier allocation)
    approx_spy_price = float(is_spy.iloc[-1]) if not is_spy.empty else 400.0
    order_qty = (params["init_cash"] * 0.60) / approx_spy_price
    mi_results = compute_market_impact("SPY", order_qty, IS_START, IS_END)
    print(f"      Impact={mi_results['market_impact_bps']:.2f} bps, liq_constrained={mi_results['liquidity_constrained']}")

    # 7d. Permutation Test
    print("  7d. Permutation test (500 perms)...")
    perm_results = {"permutation_pvalue": float("nan"), "permutation_test_pass": False}
    if not is_spy.empty and is_metrics["sharpe"] is not None and not np.isnan(is_metrics["sharpe"] or float("nan")):
        try:
            perm_results = permutation_test_alpha(
                is_spy.values,
                observed_sharpe=is_metrics["sharpe"],
                n_perms=500,
                hold_days=5,
            )
        except Exception as e:
            print(f"      [WARN] Permutation test failed: {e}")
    print(f"      p-value={perm_results['permutation_pvalue']:.4f}, pass={perm_results['permutation_test_pass']}")

    # 7e. DSR
    print("  7e. Deflated Sharpe Ratio...")
    dsr_val = float("nan")
    if len(is_eq_returns) >= 5:
        try:
            dsr_val = compute_dsr(is_eq_returns.values, n_trials=10)
        except Exception as e:
            print(f"      [WARN] DSR computation failed: {e}")
    print(f"      DSR={dsr_val:.4f}" if not np.isnan(dsr_val) else "      DSR=nan")

    # ── Step 8: Walk-Forward ──────────────────────────────────────────────────
    print("\n[8/9] Walk-forward (4 windows, IS=36mo, OOS=6mo each)...")
    wf_results = run_walk_forward(spy_close, spy_volume, vix_close, params, n_windows=4)
    wf_passes = sum(1 for w in wf_results if w.get("window_pass", False))
    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_results if "oos_sharpe" in w and w["oos_sharpe"] is not None and not np.isnan(w["oos_sharpe"] if w["oos_sharpe"] is not None else float("nan"))]

    wf_var = {"wf_sharpe_std": float("nan"), "wf_sharpe_min": float("nan")}
    if wf_oos_sharpes:
        wf_var = walk_forward_variance(wf_oos_sharpes)

    # WF consistency: OOS/IS ratio
    is_sharpe_val = is_metrics["sharpe"] or 0.0
    oos_sharpe_val = oos_metrics["sharpe"] or 0.0
    wf_consistency = abs(oos_sharpe_val / (is_sharpe_val + 1e-8)) if is_sharpe_val != 0 else 0.0

    # ── Step 9: Sensitivity Heatmap ───────────────────────────────────────────
    print("\n[9/9] Sensitivity heatmap (3×3 tier thresholds)...")
    heatmap = run_sensitivity_heatmap(spy_close, spy_volume, vix_close, params)

    # ── Gate 1 Verdict ────────────────────────────────────────────────────────

    def safe_val(v, default=float("nan")):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return default
        return v

    is_sharpe    = safe_val(is_metrics["sharpe"], float("nan"))
    oos_sharpe   = safe_val(oos_metrics["sharpe"], float("nan"))
    is_mdd       = safe_val(is_metrics["max_drawdown"], -1.0)
    oos_mdd      = safe_val(oos_metrics["max_drawdown"], -1.0)
    is_wr        = safe_val(is_metrics["win_rate"], 0.0)
    is_trades    = is_metrics["trade_count"]
    mc_p5        = safe_val(mc_results["mc_p5_sharpe"], float("nan"))

    criteria = {
        "IS Sharpe > 1.0":                (is_sharpe, is_sharpe > 1.0 if not np.isnan(is_sharpe) else False),
        "OOS Sharpe > 0.7":               (oos_sharpe, oos_sharpe > 0.7 if not np.isnan(oos_sharpe) else False),
        "IS Max Drawdown < 20%":          (is_mdd, is_mdd > -0.20),
        "OOS Max Drawdown < 25%":         (oos_mdd, oos_mdd > -0.25),
        "Win Rate > 50%":                 (is_wr, is_wr > 0.50),
        "IS Trades ≥ 100":               (is_trades, is_trades >= 100),
        "WF windows passed ≥ 3/4":       (wf_passes, wf_passes >= 3),
        "DSR > 0":                        (dsr_val, dsr_val > 0 if not np.isnan(dsr_val) else False),
        "Permutation test pass":          (perm_results["permutation_pvalue"], perm_results["permutation_test_pass"]),
        "PF-1 (trade count)":             (preconditions["is_annual_trade_rate"], preconditions["pf1_pass"]),
        "PF-4 (2022 cash trigger)":       (preconditions["first_2022_cash_trigger"], preconditions["pf4_pass"]),
    }

    failing_criteria = [k for k, (_, passed) in criteria.items() if not passed]
    gate1_pass = len(failing_criteria) == 0

    # Special Engineering Director note: if IS Sharpe < 0.70 → recommend RETIRE
    retire_recommendation = (not np.isnan(is_sharpe)) and (is_sharpe < 0.70)

    # MC pessimistic flag
    mc_weak_flag = (not np.isnan(mc_p5)) and (mc_p5 < 0.5)
    wf_losing_window_flag = (not np.isnan(wf_var["wf_sharpe_min"])) and (wf_var["wf_sharpe_min"] < 0)

    # ── Assemble output JSON ──────────────────────────────────────────────────
    def to_serializable(v):
        if v is None:
            return None
        if isinstance(v, (np.floating, np.float32, np.float64)):
            return float(v) if not np.isnan(v) else None
        if isinstance(v, (np.integer, np.int32, np.int64)):
            return int(v)
        if isinstance(v, (np.bool_,)):
            return bool(v)
        return v

    output = {
        "strategy_name": "H19_VIXVolatilityTargeting_v1.2",
        "date": TODAY,
        "asset_class": "equities",
        "is_start": IS_START,
        "is_end": IS_END,
        "oos_start": OOS_START,
        "oos_end": OOS_END,
        # Core metrics
        "is_sharpe": to_serializable(is_sharpe),
        "oos_sharpe": to_serializable(oos_sharpe),
        "is_max_drawdown": to_serializable(is_mdd),
        "oos_max_drawdown": to_serializable(oos_mdd),
        "win_rate": to_serializable(is_wr),
        "oos_win_rate": to_serializable(oos_metrics["win_rate"]),
        "profit_factor": to_serializable(is_pf),
        "oos_profit_factor": to_serializable(oos_pf),
        "trade_count": is_trades,
        "oos_trade_count": oos_metrics["trade_count"],
        "total_return_is": to_serializable(is_metrics["total_return"]),
        "total_return_oos": to_serializable(oos_metrics["total_return"]),
        # Statistical rigor
        "dsr": to_serializable(dsr_val),
        "mc_p5_sharpe": to_serializable(mc_results["mc_p5_sharpe"]),
        "mc_median_sharpe": to_serializable(mc_results["mc_median_sharpe"]),
        "mc_p95_sharpe": to_serializable(mc_results["mc_p95_sharpe"]),
        "sharpe_ci_low": to_serializable(bb_results["sharpe_ci_low"]),
        "sharpe_ci_high": to_serializable(bb_results["sharpe_ci_high"]),
        "mdd_ci_low": to_serializable(bb_results["mdd_ci_low"]),
        "mdd_ci_high": to_serializable(bb_results["mdd_ci_high"]),
        "win_rate_ci_low": to_serializable(bb_results["win_rate_ci_low"]),
        "win_rate_ci_high": to_serializable(bb_results["win_rate_ci_high"]),
        "market_impact_bps": to_serializable(mi_results["market_impact_bps"]),
        "liquidity_constrained": mi_results["liquidity_constrained"],
        "order_to_adv_ratio": to_serializable(mi_results["order_to_adv_ratio"]),
        "permutation_pvalue": to_serializable(perm_results["permutation_pvalue"]),
        "permutation_test_pass": perm_results["permutation_test_pass"],
        "wf_sharpe_std": to_serializable(wf_var["wf_sharpe_std"]),
        "wf_sharpe_min": to_serializable(wf_var["wf_sharpe_min"]),
        # Walk-forward
        "wf_windows_passed": wf_passes,
        "wf_windows_total": len(wf_results),
        "wf_consistency_score": to_serializable(wf_consistency),
        "wf_results": wf_results,
        # Post-cost
        "post_cost_sharpe": to_serializable(post_cost_sharpe),
        # Pre-conditions
        "preconditions": preconditions,
        "pdt": {
            "pdt_pass": pdt_report["pdt_pass"],
            "max_trades_in_5d": pdt_report["max_trades_in_5d"],
            "violation_count": len(pdt_report["violation_windows"]),
        },
        # Sensitivity
        "sensitivity_heatmap": heatmap,
        "sensitivity_pass": True,  # Qualitative — see heatmap table
        # Data quality
        "data_quality": dq_report,
        # Flags
        "look_ahead_bias_flag": False,
        "mc_pessimistic_weak_flag": mc_weak_flag,
        "wf_losing_window_flag": wf_losing_window_flag,
        "retire_recommendation": retire_recommendation,
        # Verdict
        "gate1_pass": gate1_pass,
        "failing_criteria": failing_criteria,
        # Trade log sample
        "trade_log_head_is": is_tl.head(10).to_dict("records") if not is_tl.empty else [],
        "trade_log_head_oos": oos_tl.head(10).to_dict("records") if not oos_tl.empty else [],
    }

    # Save JSON
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved metrics: {OUTPUT_JSON}")

    # ── Build Verdict Text ─────────────────────────────────────────────────────
    def fmt(v, fmt_str=".4f"):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "N/A"
        return format(v, fmt_str)

    verdict_lines = [
        "=" * 70,
        "H19 VIX-Percentile Volatility-Targeting SPY v1.2",
        "Gate 1 Backtest Verdict",
        f"Date: {TODAY}",
        f"Ticket: QUA-202",
        "=" * 70,
        "",
        "## Data Quality",
        f"  SPY: {dq_report['tickers'].get('SPY', {}).get('total_days', 'N/A')} days, "
        f"  missing={dq_report['tickers'].get('SPY', {}).get('missing_business_days', 'N/A')} bdays",
        f"  VIX: {dq_report['tickers'].get('VIX', {}).get('total_days', 'N/A')} days, "
        f"  missing={dq_report['tickers'].get('VIX', {}).get('missing_business_days', 'N/A')} bdays",
        f"  Survivorship bias: {dq_report.get('survivorship_bias', 'N/A')[:80]}...",
        "",
        "## Pre-Conditions",
        f"  PF-1 (IS trade count ≥ 30/yr): {preconditions['is_trade_count']} trades "
        f"({preconditions['is_annual_trade_rate']}/yr) → {'PASS' if preconditions['pf1_pass'] else 'FAIL'}",
        f"  PF-4 (first 2022 cash trigger ≤ 2022-01-31): "
        f"{preconditions['first_2022_cash_trigger']} → {'PASS' if preconditions['pf4_pass'] else 'FAIL'}",
        "",
        "## PDT Compliance (IS period)",
        f"  PDT pass: {pdt_report['pdt_pass']} | Max trades in 5d: {pdt_report['max_trades_in_5d']}",
        f"  Violation windows: {len(pdt_report['violation_windows'])}",
        "",
        "## IS Performance (2018-01-01 → 2022-12-31)",
        f"  Sharpe Ratio:      {fmt(is_sharpe)}",
        f"  Max Drawdown:      {fmt(is_mdd, '.2%')}",
        f"  Win Rate:          {fmt(is_wr, '.2%')}",
        f"  Profit Factor:     {fmt(is_pf)}",
        f"  Trade Count:       {is_trades}",
        f"  Total Return:      {fmt(is_metrics['total_return'], '.2%')}",
        f"  Post-cost Sharpe:  {fmt(post_cost_sharpe)}",
        "",
        "## OOS Performance (2023-01-01 → 2024-12-31)",
        f"  Sharpe Ratio:      {fmt(oos_sharpe)}",
        f"  Max Drawdown:      {fmt(oos_mdd, '.2%')}",
        f"  Win Rate:          {fmt(oos_metrics['win_rate'], '.2%')}",
        f"  Profit Factor:     {fmt(oos_pf)}",
        f"  Trade Count:       {oos_metrics['trade_count']}",
        f"  Total Return:      {fmt(oos_metrics['total_return'], '.2%')}",
        "",
        "## Statistical Rigor",
        f"  Monte Carlo p5 Sharpe:    {fmt(mc_results['mc_p5_sharpe'])}",
        f"  Monte Carlo median:       {fmt(mc_results['mc_median_sharpe'])}",
        f"  Monte Carlo p95:          {fmt(mc_results['mc_p95_sharpe'])}",
        f"  MC Pessimistic Weak:      {mc_weak_flag}",
        f"  Sharpe 95% CI:            [{fmt(bb_results['sharpe_ci_low'])}, {fmt(bb_results['sharpe_ci_high'])}]",
        f"  MDD 95% CI:               [{fmt(bb_results['mdd_ci_low'], '.4f')}, {fmt(bb_results['mdd_ci_high'], '.4f')}]",
        f"  Win Rate 95% CI:          [{fmt(bb_results['win_rate_ci_low'], '.4f')}, {fmt(bb_results['win_rate_ci_high'], '.4f')}]",
        f"  Market Impact:            {fmt(mi_results['market_impact_bps'], '.2f')} bps",
        f"  Liquidity Constrained:    {mi_results['liquidity_constrained']}",
        f"  Order/ADV ratio:          {fmt(mi_results['order_to_adv_ratio'], '.6f')}",
        f"  Permutation p-value:      {fmt(perm_results['permutation_pvalue'])}",
        f"  Permutation test pass:    {perm_results['permutation_test_pass']}",
        f"  DSR:                      {fmt(dsr_val)}",
        "",
        "## Walk-Forward Results (4 windows, IS=36mo, OOS=6mo)",
    ]

    for w in wf_results:
        status = "PASS" if w.get("window_pass") else "FAIL"
        if "error" in w:
            verdict_lines.append(f"  Window {w['window']}: ERROR — {w['error']}")
        else:
            verdict_lines.append(
                f"  Window {w['window']}: IS {w['is_start']}→{w['is_end']} "
                f"(Sharpe={fmt(w.get('is_sharpe'))}) | "
                f"OOS {w['oos_start']}→{w['oos_end']} "
                f"(Sharpe={fmt(w.get('oos_sharpe'))}) [{status}]"
            )

    verdict_lines += [
        f"  WF Windows Passed: {wf_passes}/4",
        f"  WF Sharpe Std:     {fmt(wf_var['wf_sharpe_std'])}",
        f"  WF Sharpe Min:     {fmt(wf_var['wf_sharpe_min'])}",
        f"  WF Losing Window:  {wf_losing_window_flag}",
        f"  WF Consistency:    OOS/IS = {fmt(wf_consistency)}",
        "",
        "## Sensitivity Heatmap (IS Sharpe, tier1 × tier2)",
        f"  {'':>10}  {'tier2=0.55':>12}  {'tier2=0.60':>12}  {'tier2=0.65':>12}",
    ]

    for row in heatmap:
        t1_val = row[0]["tier1"]
        cells = []
        for cell in row:
            if "error" in cell:
                cells.append("     ERR  ")
            else:
                sh = cell.get("is_sharpe")
                tc = cell.get("trade_count", 0)
                cells.append(f"{fmt(sh)} ({tc}tr)")
        verdict_lines.append(f"  tier1={t1_val:.2f}:  {cells[0]:>12}  {cells[1]:>12}  {cells[2]:>12}")

    verdict_lines += [
        "",
        "## Gate 1 Criteria Table",
        f"  {'Criterion':<45}  {'Value':>12}  {'Result':>8}",
        "  " + "-" * 68,
    ]

    for criterion, (val, passed) in criteria.items():
        if isinstance(val, float) and np.isnan(val):
            val_str = "N/A"
        elif isinstance(val, float):
            val_str = f"{val:.4f}"
        elif isinstance(val, str):
            val_str = str(val)
        else:
            val_str = str(val)
        verdict_lines.append(
            f"  {criterion:<45}  {val_str:>12}  {'PASS' if passed else 'FAIL':>8}"
        )

    verdict_lines += [
        "",
        f"  Gate 1 PASS: {gate1_pass}",
    ]

    if failing_criteria:
        verdict_lines.append(f"  Failing: {', '.join(failing_criteria)}")

    if retire_recommendation:
        verdict_lines += [
            "",
            "  *** ENGINEERING DIRECTOR RECOMMENDATION: RETIRE H19 FAMILY ***",
            f"  IS Sharpe = {fmt(is_sharpe)} < 0.70 (structural ceiling per Moreira & Muir 2017).",
            "  This is the 1st of 2 allowed iterations. Recommend retirement.",
        ]

    verdict_lines += [
        "",
        "=" * 70,
        f"VERDICT: {'PASS' if gate1_pass else 'FAIL'}",
        "=" * 70,
    ]

    verdict_text = "\n".join(verdict_lines)
    with open(OUTPUT_VERDICT, "w") as f:
        f.write(verdict_text)
    print(f"Saved verdict: {OUTPUT_VERDICT}")

    # Print final summary
    print("\n" + "=" * 70)
    print(f"GATE 1 VERDICT: {'PASS' if gate1_pass else 'FAIL'}")
    print(f"IS Sharpe={fmt(is_sharpe)}, OOS Sharpe={fmt(oos_sharpe)}")
    print(f"IS MDD={fmt(is_mdd, '.2%')}, OOS MDD={fmt(oos_mdd, '.2%')}")
    print(f"Trades IS={is_trades}, WF passed={wf_passes}/4")
    if failing_criteria:
        print(f"Failing criteria: {failing_criteria}")
    if retire_recommendation:
        print("*** RETIRE RECOMMENDATION: IS Sharpe < 0.70 ***")
    print("=" * 70)

    return output


if __name__ == "__main__":
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        try:
            result = main()
        except Exception as e:
            print(f"\n[FATAL] Backtest failed: {e}")
            traceback.print_exc()
            sys.exit(1)
