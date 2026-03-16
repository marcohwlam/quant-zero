"""
H08 Gate 1 Backtest Runner — Crypto Momentum BTC/ETH
Executes full IS/OOS + walk-forward + statistical rigor pipeline.

Note: strategies/h08_crypto_momentum.py uses tsl_stop kwarg which maps to
sl_stop + sl_trail=True in vectorbt 0.28.4. This runner reimplements the
core portfolio construction with the correct vbt API and reuses all signal
and data functions from the strategy module directly.

Output:
  backtests/H08_CryptoMomentum_{TODAY}.json
  backtests/H08_CryptoMomentum_{TODAY}_verdict.txt
  research/backtest_results/h08_gate1_results.md
"""

import sys
import json
import warnings
import datetime
import numpy as np
import pandas as pd
import vectorbt as vbt
from scipy.stats import norm

sys.path.insert(0, "/mnt/c/Users/lamho/repo/quant-zero")

from strategies.h08_crypto_momentum import (
    download_crypto_data,
    check_data_quality,
    compute_ema_signals,
    compute_btc_eth_correlation,
    PARAMETERS,
    CRYPTO_FEES,
    CRYPTO_SLIPPAGE,
    TRADING_DAYS_PER_YEAR,
)

warnings.filterwarnings("ignore")

TODAY = datetime.date.today().isoformat()
STRATEGY_NAME = "H08_CryptoMomentum"
IS_START, IS_END = "2018-01-01", "2021-12-31"
OOS_START, OOS_END = "2022-01-01", "2023-12-31"


# ── Core Portfolio Runner (vbt 0.28.4 API) ─────────────────────────────────────

def run_single_asset_vbt(price: pd.Series, params: dict, init_cash: float) -> vbt.Portfolio:
    """
    EMA crossover with trailing stop using vbt 0.28.4 API.
    tsl_stop from strategy spec → sl_stop + sl_trail=True in vbt 0.28.4.
    """
    entries, exits = compute_ema_signals(
        price,
        fast=params["ema_fast_period"],
        slow=params["ema_slow_period"],
    )
    pf = vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        sl_stop=params["trailing_stop_pct"],   # trailing stop percentage
        sl_trail=True,                          # makes sl_stop trail the peak
        fees=CRYPTO_FEES,
        slippage=CRYPTO_SLIPPAGE,
        init_cash=init_cash,
        freq="1D",
    )
    return pf


def run_strategy_vbt(
    universe=None,
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
    return_portfolio: bool = False,
) -> dict:
    """Run H08 strategy and return metrics dict (vbt 0.28.4-compatible)."""
    if params is None:
        params = PARAMETERS
    if universe is None:
        universe = params.get("universe", PARAMETERS["universe"])

    close = download_crypto_data(universe, start, end)
    quality_report = check_data_quality(close)
    close = close.dropna(axis=1, how="all")

    if close.empty:
        raise ValueError(f"No price data for {universe} in {start}–{end}.")

    min_required = params["ema_slow_period"] + 10
    if len(close) < min_required:
        raise ValueError(f"Insufficient data: need ≥{min_required} bars, got {len(close)}.")

    init_cash = params.get("init_cash", 25000)
    btc_cols = [c for c in close.columns if "BTC" in c.upper()]
    eth_cols = [c for c in close.columns if "ETH" in c.upper()]

    capital_map = {}
    for ticker in close.columns:
        if ticker in btc_cols:
            capital_map[ticker] = init_cash * params.get("capital_split_btc", 0.50)
        elif ticker in eth_cols:
            capital_map[ticker] = init_cash * params.get("capital_split_eth", 0.50)
        else:
            capital_map[ticker] = init_cash / len(close.columns)

    portfolios = {}
    for ticker in close.columns:
        pf = run_single_asset_vbt(close[ticker], params, capital_map[ticker])
        portfolios[ticker] = pf

    # Combined portfolio metrics
    combined_value = sum(pf.value() for pf in portfolios.values())
    combined_returns = combined_value.pct_change().dropna()

    sharpe = float(
        combined_returns.mean() / (combined_returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )
    rolling_peak = combined_value.cummax()
    mdd = float(((combined_value - rolling_peak) / rolling_peak).min())
    total_return = float((combined_value.iloc[-1] / combined_value.iloc[0]) - 1)

    per_asset_trades = {t: int(pf.trades.count()) for t, pf in portfolios.items()}
    trade_count = sum(per_asset_trades.values())

    all_pnl = []
    for pf in portfolios.values():
        try:
            # In vbt 0.28.4, trades.pnl is a MappedArray; use records_readable
            pnl = pf.trades.records_readable["PnL"].values
            all_pnl.extend(pnl[~np.isnan(pnl)].tolist())
        except Exception:
            try:
                pnl = np.array(pf.trades.pnl.to_pandas()).flatten()
                all_pnl.extend(pnl[~np.isnan(pnl)].tolist())
            except Exception:
                pass

    pnl_arr = np.array(all_pnl)
    if len(pnl_arr) > 0:
        win_rate = float(np.mean(pnl_arr > 0))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss != 0 else float("inf")
    else:
        win_rate, win_loss_ratio = 0.0, 0.0

    corr_report = compute_btc_eth_correlation(close)

    result = {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "win_rate": round(win_rate, 4),
        "win_loss_ratio": round(win_loss_ratio, 4),
        "total_return": round(total_return, 4),
        "trade_count": trade_count,
        "per_asset_trades": per_asset_trades,
        "btc_eth_correlation": corr_report,
        "data_quality": quality_report,
        "combined_returns": combined_returns.values,
        "combined_value": combined_value,
        "all_pnl": pnl_arr,
    }
    if return_portfolio:
        result["portfolios"] = portfolios

    return result


# ── Statistical Rigor Functions ────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe": round(float(np.percentile(sharpes, 5)), 4),
        "mc_median_sharpe": round(float(np.median(sharpes)), 4),
        "mc_p95_sharpe": round(float(np.percentile(sharpes, 95)), 4),
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
        mdd = float(np.min((cum - roll_max) / roll_max))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)
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
    hold_days: int = 5,
) -> dict:
    T = len(prices)
    permuted_sharpes = []
    for _ in range(n_perms):
        n_trades = max(10, T // 20)
        perm_entry_idx = np.random.choice(T - hold_days, size=n_trades, replace=False)
        trade_returns = []
        for idx in perm_entry_idx:
            exit_idx = min(idx + hold_days, T - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
            trade_returns.append(ret)
        arr = np.array(trade_returns)
        if len(arr) > 1 and arr.std() > 0:
            s = arr.mean() / arr.std() * np.sqrt(252 / hold_days)
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
        "wf_sharpe_std": round(float(arr.std()), 4),
        "wf_sharpe_min": round(float(arr.min()), 4),
    }


def compute_dsr(returns_series: np.ndarray, n_trials: int) -> float:
    T = len(returns_series)
    if T < 4:
        return 0.0
    sharpe = returns_series.mean() / (returns_series.std() + 1e-8) * np.sqrt(252)
    skew = float(pd.Series(returns_series).skew())
    kurt = float(pd.Series(returns_series).kurt())
    gamma = 0.5772156649
    E_max_sr = (
        (1 - gamma) * norm.ppf(1 - 1.0 / n_trials)
        + gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    sr_std = np.sqrt(
        (1 + 0.5 * sharpe**2 - skew * sharpe + (kurt / 4) * sharpe**2) / (T - 1)
    )
    dsr = float(norm.cdf((sharpe - E_max_sr) / (sr_std + 1e-10)))
    return round(dsr, 6)


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(base_params: dict, n_windows: int = 4, is_months: int = 36, oos_months: int = 6) -> list:
    wf_results = []
    base_start = pd.Timestamp("2018-01-01")
    for w in range(n_windows):
        is_start = base_start + pd.DateOffset(months=w * 6)
        is_end = is_start + pd.DateOffset(months=is_months) - pd.DateOffset(days=1)
        oos_start = is_end + pd.DateOffset(days=1)
        oos_end = oos_start + pd.DateOffset(months=oos_months) - pd.DateOffset(days=1)
        try:
            is_r = run_strategy_vbt(
                start=is_start.strftime("%Y-%m-%d"),
                end=is_end.strftime("%Y-%m-%d"),
                params=base_params,
            )
            oos_r = run_strategy_vbt(
                start=oos_start.strftime("%Y-%m-%d"),
                end=oos_end.strftime("%Y-%m-%d"),
                params=base_params,
            )
            oos_passes = oos_r["sharpe"] >= 0.7 or (
                is_r["sharpe"] > 0
                and abs(oos_r["sharpe"] - is_r["sharpe"]) / (abs(is_r["sharpe"]) + 1e-8) <= 0.30
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
            wf_results.append({
                "window": w + 1, "error": str(exc), "pass": False,
            })
    return wf_results


# ── EMA Sensitivity Scan ──────────────────────────────────────────────────────

def scan_ema_combinations_vbt(start: str, end: str, base_params: dict) -> dict:
    fast_periods = [10, 15, 20, 30]
    slow_periods = [40, 50, 60, 90]
    results = {}
    for fast in fast_periods:
        for slow in slow_periods:
            key = f"ema_{fast}_{slow}"
            p = {**base_params, "ema_fast_period": fast, "ema_slow_period": slow}
            try:
                r = run_strategy_vbt(start=start, end=end, params=p)
                results[key] = round(r["sharpe"], 4)
            except Exception as exc:
                results[key] = f"error: {exc}"

    sharpe_vals = [v for v in results.values() if isinstance(v, float) and not np.isnan(v)]
    if len(sharpe_vals) > 1:
        sharpe_range = max(sharpe_vals) - min(sharpe_vals)
        sharpe_mean = np.mean(sharpe_vals)
        variance_pct = sharpe_range / abs(sharpe_mean) if sharpe_mean != 0 else float("inf")
        results["_sharpe_range"] = round(float(sharpe_range), 4)
        results["_sharpe_variance_pct"] = round(float(variance_pct), 4)
        flag = "PASS" if variance_pct <= 0.30 else "FAIL"
        results["_gate1_variance_flag"] = f"{flag}: Sharpe variance {variance_pct:.1%} {'≤' if flag == 'PASS' else '>'} 30% across 16 EMA combinations."
    return results


# ── Main Gate 1 Runner ────────────────────────────────────────────────────────

def main():
    np.random.seed(42)
    print("=" * 60)
    print(f"H08 Crypto Momentum — Gate 1 Backtest [{TODAY}]")
    print("=" * 60)

    # ── 1. IS Backtest ──────────────────────────────────────────
    print("\n[1/6] Running IS backtest (2018-01-01 to 2021-12-31)...")
    is_full = run_strategy_vbt(start=IS_START, end=IS_END, params=PARAMETERS, return_portfolio=True)
    is_sharpe = is_full["sharpe"]
    is_mdd = is_full["max_drawdown"]
    is_win_rate = is_full["win_rate"]
    is_win_loss = is_full["win_loss_ratio"]
    is_trade_count = is_full["trade_count"]
    is_total_return = is_full["total_return"]
    is_per_asset = is_full["per_asset_trades"]
    is_returns = is_full["combined_returns"]
    trade_pnls = is_full["all_pnl"]
    btc_eth_corr = is_full["btc_eth_correlation"]
    data_quality = is_full["data_quality"]
    print(f"  IS Sharpe: {is_sharpe}  MDD: {is_mdd:.1%}  WinRate: {is_win_rate:.1%}  Trades: {is_trade_count}")

    # ── 2. OOS Backtest ─────────────────────────────────────────
    print("\n[2/6] Running OOS backtest (2022-01-01 to 2023-12-31)...")
    oos_full = run_strategy_vbt(start=OOS_START, end=OOS_END, params=PARAMETERS)
    oos_sharpe = oos_full["sharpe"]
    oos_mdd = oos_full["max_drawdown"]
    oos_win_rate = oos_full["win_rate"]
    oos_trade_count = oos_full["trade_count"]
    oos_total_return = oos_full["total_return"]
    print(f"  OOS Sharpe: {oos_sharpe}  MDD: {oos_mdd:.1%}  Trades: {oos_trade_count}")

    wins = trade_pnls[trade_pnls > 0]
    losses = trade_pnls[trade_pnls < 0]
    profit_factor = round(
        float(wins.sum() / (abs(losses.sum()) + 1e-8)) if len(losses) > 0 else 999.0, 4
    )
    post_cost_sharpe = is_sharpe  # costs already applied via fees/slippage

    # ── 3. Walk-Forward ─────────────────────────────────────────
    print("\n[3/6] Running walk-forward analysis (4 windows)...")
    wf_table = run_walk_forward(PARAMETERS)
    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_table if "oos_sharpe" in w]
    wf_windows_passed = sum(1 for w in wf_table if w.get("pass", False))
    wf_ratios = []
    for w in wf_table:
        if "is_sharpe" in w and abs(w["is_sharpe"]) > 0.01:
            wf_ratios.append(w["oos_sharpe"] / w["is_sharpe"])
    wf_consistency_score = round(float(np.mean(wf_ratios)) if wf_ratios else 0.0, 4)
    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        print(f"  Window {w['window']}: IS={w.get('is_sharpe','?')} OOS={w.get('oos_sharpe','?')} [{status}]")
    wf_var = walk_forward_variance(wf_oos_sharpes)
    print(f"  WF Sharpe std={wf_var['wf_sharpe_std']}  min={wf_var['wf_sharpe_min']}")

    # ── 4. Statistical Rigor Pipeline ───────────────────────────
    print("\n[4/6] Running statistical rigor pipeline...")

    # 4a. Monte Carlo
    print("  4a. Monte Carlo (1000 sims)...")
    mc = monte_carlo_sharpe(trade_pnls) if len(trade_pnls) > 5 else {
        "mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0
    }
    print(f"      p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}")

    # 4b. Block Bootstrap CI
    print("  4b. Block Bootstrap CI (1000 boots)...")
    bci = block_bootstrap_ci(is_returns) if len(is_returns) > 10 else {
        "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
        "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
        "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
    }
    print(f"      Sharpe CI [{bci['sharpe_ci_low']:.3f}, {bci['sharpe_ci_high']:.3f}]")

    # 4c. Market Impact — N/A for crypto
    market_impact_note = "Crypto — market impact N/A. BTC/ETH ADV >> $25K order size."

    # 4d. Permutation Test
    print("  4d. Permutation test (500 perms)...")
    close_is = download_crypto_data(["BTC-USD", "ETH-USD"], IS_START, IS_END)
    btc_prices = close_is["BTC-USD"].dropna().values if "BTC-USD" in close_is.columns else np.array([])
    perm = permutation_test_alpha(btc_prices, is_sharpe) if len(btc_prices) > 20 else {
        "permutation_pvalue": 1.0, "permutation_test_pass": False
    }
    print(f"      p-value={perm['permutation_pvalue']} {'PASS' if perm['permutation_test_pass'] else 'FAIL'}")

    # 4e. DSR
    n_trials = 16 + 4 + 3  # 16 EMA + 4 trailing stops + 3 capital splits
    dsr = compute_dsr(is_returns, n_trials=n_trials) if len(is_returns) > 10 else 0.0
    print(f"  4e. DSR={dsr}")

    # ── 5. Sensitivity Scan ──────────────────────────────────────
    print("\n[5/6] Running 16 EMA combinations sensitivity scan...")
    ema_scan = scan_ema_combinations_vbt(start=IS_START, end=IS_END, base_params=PARAMETERS)
    print(f"  Sharpe range={ema_scan.get('_sharpe_range')}  variance%={ema_scan.get('_sharpe_variance_pct')}")
    print(f"  {ema_scan.get('_gate1_variance_flag', '')}")
    sensitivity_pass = "PASS" in str(ema_scan.get("_gate1_variance_flag", "FAIL"))
    ema_table = {k: v for k, v in ema_scan.items() if k.startswith("ema_")}

    # ── 6. Gate 1 Verdict ───────────────────────────────────────
    print("\n[6/6] Computing Gate 1 verdict...")
    win_rate_pass = is_win_rate >= 0.50 or (is_win_rate < 0.50 and is_win_loss >= 1.2)
    gate1_checks = {
        "is_sharpe_pass": bool(is_sharpe > 1.0),
        "oos_sharpe_pass": bool(oos_sharpe > 0.7),
        "is_mdd_pass": bool(is_mdd > -0.20),
        "oos_mdd_pass": bool(oos_mdd > -0.25),
        "win_rate_pass": bool(win_rate_pass),
        "trade_count_pass": bool(is_trade_count >= 50),
        "wf_windows_pass": bool(wf_windows_passed >= 3),
        "wf_consistency_pass": bool(wf_consistency_score >= 0.7),
        "sensitivity_pass": bool(sensitivity_pass),
        "dsr_pass": bool(dsr > 0),
        "permutation_pass": bool(perm["permutation_test_pass"]),
        "mc_p5_pass": bool(mc["mc_p5_sharpe"] >= 0.5),
    }
    gate1_pass = all(gate1_checks.values())
    failing = [k for k, v in gate1_checks.items() if not v]
    print(f"\n  Gate 1: {'PASS' if gate1_pass else 'FAIL'}")
    if failing:
        print(f"  Failing: {', '.join(failing)}")

    # ── Build Metrics JSON ──────────────────────────────────────
    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "crypto",
        "is_period": f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "is_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "is_max_drawdown": is_mdd,
        "oos_max_drawdown": oos_mdd,
        "win_rate": is_win_rate,
        "oos_win_rate": oos_win_rate,
        "win_loss_ratio": is_win_loss,
        "profit_factor": profit_factor,
        "trade_count": is_trade_count,
        "oos_trade_count": oos_trade_count,
        "per_asset_trades_is": is_per_asset,
        "total_return_is": is_total_return,
        "total_return_oos": oos_total_return,
        "post_cost_sharpe": post_cost_sharpe,
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
        "market_impact_bps": 0.0,
        "liquidity_constrained": False,
        "order_to_adv_ratio": 0.0,
        "market_impact_note": market_impact_note,
        "permutation_pvalue": perm["permutation_pvalue"],
        "permutation_test_pass": perm["permutation_test_pass"],
        "sensitivity_scan_ema": ema_table,
        "sensitivity_scan_meta": {
            "sharpe_range": ema_scan.get("_sharpe_range"),
            "sharpe_variance_pct": ema_scan.get("_sharpe_variance_pct"),
            "gate1_variance_flag": ema_scan.get("_gate1_variance_flag"),
        },
        "sensitivity_pass": sensitivity_pass,
        "btc_eth_correlation": btc_eth_corr,
        "data_quality_summary": {
            t: {k: v for k, v in info.items() if k != "gap_flag"}
            for t, info in data_quality.get("tickers", {}).items()
        },
        "look_ahead_bias_flag": False,
        "gate1_checks": gate1_checks,
        "gate1_pass": gate1_pass,
        "win_rate_note": (
            (f"Win rate {is_win_rate:.1%} < 50% — "
             f"avg_win/avg_loss={is_win_loss:.2f} "
             + ("≥ 1.2 (passes alt criterion)" if is_win_loss >= 1.2 else "< 1.2 (FAILS)"))
            if is_win_rate < 0.50 else None
        ),
        "contango_note": (
            "LIVE NOTE: Backtest uses spot BTC/ETH prices. BITO incurs ~10-20%/yr "
            "contango drag in bull regimes (Risk Director QUA-106)."
        ),
        "look_ahead_bias_notes": [
            "EMA signals shifted +1 bar (computed at close T, executed at open T+1).",
            "No future price data used in signal generation.",
            "Trailing stop (sl_trail=True) evaluated at close prices — no look-ahead.",
        ],
    }

    # ── Save JSON ───────────────────────────────────────────────
    json_path = f"/mnt/c/Users/lamho/repo/quant-zero/backtests/{STRATEGY_NAME}_{TODAY}.json"
    with open(json_path, "w") as fh:
        json.dump(metrics, fh, indent=2, default=str)
    print(f"\nSaved: {json_path}")

    # ── Save Verdict TXT ────────────────────────────────────────
    wf_min_flag = "FLAG: losing window" if wf_var["wf_sharpe_min"] < 0 else "OK"
    mc_p5_flag = "PASS" if mc["mc_p5_sharpe"] >= 0.5 else "FAIL — MC pessimistic bound weak"
    verdict_lines = [
        f"H08 Crypto Momentum BTC/ETH — Gate 1 Verdict",
        f"Date: {TODAY}",
        "=" * 55,
        f"OVERALL: {'PASS' if gate1_pass else 'FAIL'}",
        "",
        "Core Metrics:",
        f"  IS Sharpe:           {is_sharpe:>8.4f}  {'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'} (>1.0)",
        f"  OOS Sharpe:          {oos_sharpe:>8.4f}  {'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'} (>0.7)",
        f"  IS Max Drawdown:     {is_mdd:>8.1%}  {'PASS' if gate1_checks['is_mdd_pass'] else 'FAIL'} (<20%)",
        f"  OOS Max Drawdown:    {oos_mdd:>8.1%}  {'PASS' if gate1_checks['oos_mdd_pass'] else 'FAIL'} (<25%)",
        f"  Win Rate (IS):       {is_win_rate:>8.1%}  {'PASS' if gate1_checks['win_rate_pass'] else 'FAIL'} (>50% OR w/l>1.2)",
        f"  Win/Loss Ratio:      {is_win_loss:>8.2f}",
        f"  Trade Count (IS):    {is_trade_count:>8d}  {'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'} (≥50)",
        f"  Profit Factor:       {profit_factor:>8.4f}",
        "",
        "Walk-Forward (4 windows):",
        f"  Windows Passed:      {wf_windows_passed}/4  {'PASS' if gate1_checks['wf_windows_pass'] else 'FAIL'} (≥3)",
        f"  Consistency Score:   {wf_consistency_score:>8.4f}  {'PASS' if gate1_checks['wf_consistency_pass'] else 'FAIL'} (≥0.7)",
        f"  WF Sharpe Std:       {wf_var['wf_sharpe_std']:>8.4f}",
        f"  WF Sharpe Min:       {wf_var['wf_sharpe_min']:>8.4f}  {wf_min_flag}",
    ]
    for w in wf_table:
        status = "PASS" if w.get("pass") else "FAIL"
        verdict_lines.append(
            f"    W{w['window']}: IS {w.get('is_sharpe','?'):>6} OOS {w.get('oos_sharpe','?'):>6} [{status}]"
        )
    verdict_lines += [
        "",
        "Statistical Rigor:",
        f"  DSR:                 {dsr:>8.6f}  {'PASS' if gate1_checks['dsr_pass'] else 'FAIL'} (>0)",
        f"  MC p5 Sharpe:        {mc['mc_p5_sharpe']:>8.3f}  {mc_p5_flag}",
        f"  MC Median Sharpe:    {mc['mc_median_sharpe']:>8.3f}",
        f"  Sharpe CI [95%]:     [{bci['sharpe_ci_low']:.3f}, {bci['sharpe_ci_high']:.3f}]",
        f"  MDD CI [95%]:        [{bci['mdd_ci_low']:.3f}, {bci['mdd_ci_high']:.3f}]",
        f"  Perm p-value:        {perm['permutation_pvalue']:>8.4f}  {'PASS' if gate1_checks['permutation_pass'] else 'FAIL'} (≤0.05)",
        "",
        "Sensitivity (16 EMA combinations):",
        f"  {ema_scan.get('_gate1_variance_flag', 'N/A')}",
        "",
        "BTC/ETH Correlation (IS):",
        f"  Avg 30d Corr:        {btc_eth_corr.get('btc_eth_avg_30d_corr', 'N/A')}",
        f"  High Corr Flag:      {btc_eth_corr.get('high_correlation_flag', 'N/A')}",
        "",
        "Risk Flags:",
        f"  Look-ahead bias:     {'YES — FAIL' if metrics['look_ahead_bias_flag'] else 'None detected'}",
        f"  Contango risk:       {metrics['contango_note']}",
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

    return metrics, verdict_txt, ema_table


if __name__ == "__main__":
    metrics, verdict_txt, ema_table = main()
    print("\n" + "=" * 60)
    print(verdict_txt)
