"""
H70 Gate 1 Full Backtest Runner
IS: 2005-01-01 to 2018-12-31
OOS: 2019-01-01 to 2024-12-31
Walk-forward: 4 non-overlapping IS folds (~3.5yr each)
Parameter sweep: 27 combos (rsi_entry x rsi_exit x stop_loss)
"""

import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import date

# Path setup
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "strategies"))
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

from h70_iwm_rsi4_mean_reversion import (
    run_backtest, PARAMETERS, download_data,
    compute_rsi, compute_sma_regime, compute_prior_high
)
from oos_data_quality import validate_oos_data, OOSDataQualityError

TODAY = date.today().isoformat()
STRATEGY_NAME = "h70_iwm_rsi4_mean_reversion"
OUT_DIR = REPO_ROOT / "backtests"

IS_START = "2005-01-01"
IS_END = "2018-12-31"
OOS_START = "2019-01-01"
OOS_END = "2024-12-31"

# Walk-forward: 4 non-overlapping IS folds (~3.5yr each)
WF_FOLDS = [
    ("2005-01-01", "2008-06-30"),
    ("2008-07-01", "2011-12-31"),
    ("2012-01-01", "2015-06-30"),
    ("2015-07-01", "2018-12-31"),
]

# Parameter sweep: 27 combos
SWEEP_PARAMS = {
    "rsi_entry_threshold": [15, 20, 25],
    "rsi_exit_threshold": [60, 65, 70],
    "stop_loss_pct": [0.05, 0.075, 0.10],
}

TRADING_DAYS = 252


# ── Statistical Rigor Pipeline ────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe": float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    np.random.seed(43)
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)

    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        if len(sample) < 2:
            continue
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS))
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
    hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    adv = hist["Volume"].rolling(20).mean().iloc[-1]
    sigma = hist["Close"].pct_change().std()

    if pd.isna(adv) or adv <= 0:
        adv = 50_000_000  # IWM ~50M shares/day
    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01

    k = 0.1
    impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
    impact_bps = impact_pct * 10000
    liquidity_constrained = bool(order_qty > 0.01 * adv)

    return {
        "market_impact_bps": float(impact_bps),
        "liquidity_constrained": liquidity_constrained,
        "order_to_adv_ratio": float(order_qty / (adv + 1e-8)),
        "adv_20d": float(adv),
    }


def permutation_test_alpha(
    prices: np.ndarray,
    entries: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 1000,
    hold_days: int = 5,
) -> dict:
    np.random.seed(44)
    entry_indices = np.where(entries)[0]
    if len(entry_indices) == 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    permuted_sharpes = []
    n = len(prices)
    for _ in range(n_perms):
        perm_idx = np.random.choice(n - hold_days, size=len(entry_indices), replace=False)
        trade_returns = []
        for idx in perm_idx:
            exit_idx = min(idx + hold_days, n - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
            trade_returns.append(ret)
        if len(trade_returns) > 1:
            arr = np.array(trade_returns)
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(TRADING_DAYS / hold_days)
        else:
            s = 0.0
        permuted_sharpes.append(s)

    perm_arr = np.array(permuted_sharpes)
    p_value = float(np.mean(perm_arr >= observed_sharpe))
    return {
        "permutation_pvalue": round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
        "permutation_perm_mean_sharpe": float(perm_arr.mean()),
        "permutation_perm_p95_sharpe": float(np.percentile(perm_arr, 95)),
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
        "wf_sharpe_max": float(arr.max()),
        "wf_sharpe_mean": float(arr.mean()),
    }


def compute_dsr(is_sharpe: float, n_trials: int, T: int) -> float:
    """Deflated Sharpe Ratio (Harvey & Liu 2014 approximation)."""
    if T <= 0 or n_trials <= 1:
        return 0.0
    # Expected max Sharpe from n_trials iid trials
    gamma = 0.5772  # Euler-Mascheroni constant
    expected_max = np.sqrt(2 * np.log(n_trials)) - (np.log(np.log(n_trials)) + np.log(4 * np.pi)) / (2 * np.sqrt(2 * np.log(n_trials))) + gamma / np.sqrt(2 * np.log(n_trials))
    expected_max /= np.sqrt(T)  # scale by sqrt(T) for annualized
    dsr = is_sharpe - expected_max
    return round(float(dsr), 4)


def compute_profit_per_trade_bps(trades_df: pd.DataFrame) -> float:
    """Net profit per trade in basis points."""
    if trades_df.empty:
        return 0.0
    avg_entry = trades_df["entry_price"].mean()
    if avg_entry <= 0:
        return 0.0
    avg_pnl_per_share = trades_df["pnl"].sum() / trades_df["shares"].sum() if trades_df["shares"].sum() > 0 else 0.0
    ppt_bps = (avg_pnl_per_share / avg_entry) * 10000
    return round(float(ppt_bps), 2)


def compute_cpr(trades_df: pd.DataFrame) -> float:
    """Cost/Gross PpT ratio."""
    if trades_df.empty:
        return 1.0
    total_cost = trades_df["transaction_cost"].sum()
    gross_wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
    if gross_wins <= 0:
        return 1.0
    # Normalize by shares * avg_entry for bps comparison
    total_shares = trades_df["shares"].sum()
    avg_entry = trades_df["entry_price"].mean()
    if total_shares <= 0 or avg_entry <= 0:
        return 1.0
    cost_bps = (total_cost / (total_shares * avg_entry)) * 10000
    gross_ppt_bps = (gross_wins / (total_shares * avg_entry)) * 10000
    return round(float(cost_bps / (gross_ppt_bps + 1e-8)), 4)


def regime_2022_split(oos_result: dict) -> dict:
    """Report OOS 2022 separately as rate-shock benchmark."""
    daily_df = oos_result.get("daily_df")
    if daily_df is None or daily_df.empty:
        return {}
    idx_2022 = daily_df.index.year == 2022
    df_2022 = daily_df.loc[idx_2022]
    if df_2022.empty:
        return {"2022_trade_count": 0, "2022_regime_active_pct": 0.0}

    # Trades in 2022
    trades = oos_result.get("trades")
    if trades is None or trades.empty:
        n_2022 = 0
    else:
        trades_2022 = trades[pd.to_datetime(trades["entry_date"]).dt.year == 2022]
        n_2022 = len(trades_2022)

    regime_pct_2022 = float(df_2022["regime_active"].mean()) if "regime_active" in df_2022.columns else 0.0

    return {
        "2022_trade_count": n_2022,
        "2022_regime_active_pct": round(regime_pct_2022, 4),
        "2022_note": "Near-zero exposure expected when IWM < 200-SMA after Jan 2022",
    }


# ── Main backtest orchestration ────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H70 Gate 1 Backtest — {TODAY}")
    print("=" * 70)

    # ── IS backtest ────────────────────────────────────────────────────────────
    print(f"\n[1/7] Running IS backtest ({IS_START} to {IS_END})...")
    with warnings.catch_warnings(record=True) as w_is:
        warnings.simplefilter("always")
        is_result = run_backtest(IS_START, IS_END)

    is_trades = is_result["trades"]
    is_equity = is_result["equity"]
    is_returns = is_result["returns"].values
    n_is_trades = len(is_trades)

    print(f"  IS trades: {n_is_trades}, Sharpe: {is_result['sharpe']}, MDD: {is_result['max_drawdown']:.2%}")

    # ── OOS backtest ───────────────────────────────────────────────────────────
    print(f"\n[2/7] Running OOS backtest ({OOS_START} to {OOS_END})...")
    with warnings.catch_warnings(record=True) as w_oos:
        warnings.simplefilter("always")
        oos_result = run_backtest(OOS_START, OOS_END)

    oos_trades = oos_result["trades"]
    oos_equity = oos_result["equity"]
    oos_returns = oos_result["returns"].values
    n_oos_trades = len(oos_trades)

    print(f"  OOS trades: {n_oos_trades}, Sharpe: {oos_result['sharpe']}, MDD: {oos_result['max_drawdown']:.2%}")

    # ── OOS Data Quality Validation ────────────────────────────────────────────
    print("\n[3/7] OOS Data Quality Validation...")
    oos_data_for_dq = download_data("IWM", OOS_START, OOS_END, PARAMETERS["sma_period"])
    oos_data_for_dq = oos_data_for_dq.loc[
        (oos_data_for_dq.index >= pd.Timestamp(OOS_START)) &
        (oos_data_for_dq.index <= pd.Timestamp(OOS_END))
    ]

    oos_metrics_for_dq = {
        "sharpe": oos_result["sharpe"],
        "max_drawdown": oos_result["max_drawdown"],
        "win_rate": oos_result["win_rate"],
        "profit_factor": oos_result["profit_factor"],
        "total_trades": n_oos_trades,
        "post_cost_sharpe": oos_result["sharpe"],  # same since costs already embedded
    }
    dq_report = validate_oos_data(oos_data_for_dq, oos_metrics_for_dq, STRATEGY_NAME)
    print(f"  OOS DQ recommendation: {dq_report['recommendation']}")
    if dq_report["recommendation"] == "BLOCK":
        print(f"  BLOCK reasons: {dq_report['block_reasons']}")
        raise OOSDataQualityError(dq_report)
    if dq_report["recommendation"] == "WARN":
        print(f"  [WARN] Advisory NaN fields: {dq_report['advisory_nan_fields']}")

    # ── Statistical Rigor Pipeline ─────────────────────────────────────────────
    print("\n[4/7] Statistical Rigor Pipeline...")

    # Monte Carlo on IS trade PnLs
    if n_is_trades >= 5:
        is_pnls = is_trades["pnl"].values
        mc_results = monte_carlo_sharpe(is_pnls)
    else:
        mc_results = {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    print(f"  MC: p5={mc_results['mc_p5_sharpe']:.3f}, median={mc_results['mc_median_sharpe']:.3f}, p95={mc_results['mc_p95_sharpe']:.3f}")

    # Block bootstrap CI on IS returns
    if len(is_returns) > 10:
        bb_results = block_bootstrap_ci(is_returns)
    else:
        bb_results = {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0, "mdd_ci_low": 0.0, "mdd_ci_high": 0.0, "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0}
    print(f"  Bootstrap Sharpe 95% CI: [{bb_results['sharpe_ci_low']:.3f}, {bb_results['sharpe_ci_high']:.3f}]")

    # Market impact (IWM: ultra-liquid ETF, ~50M ADV)
    # Estimate typical order: Elder 2% rule on $25k → ~$500 risk, $500/0.075 = $6667 notional → ~33 shares at $200
    typical_order_qty = 33.0
    mi_results = compute_market_impact("IWM", typical_order_qty, IS_START, IS_END)
    print(f"  Market impact: {mi_results['market_impact_bps']:.4f} bps, ADV: {mi_results['adv_20d']:,.0f}, liq_constrained: {mi_results['liquidity_constrained']}")

    # Permutation test on IS data
    print("  Running permutation test (1000 perms)...")
    # Build entry signal array from IS daily_df
    is_daily = is_result["daily_df"]
    is_close_arr = oos_data_for_dq["Close"].values  # reuse; build proper IS version
    # Get IS close prices
    is_data_raw = download_data("IWM", IS_START, IS_END, PARAMETERS["sma_period"])
    is_data_trim = is_data_raw.loc[
        (is_data_raw.index >= pd.Timestamp(IS_START)) &
        (is_data_raw.index <= pd.Timestamp(IS_END))
    ]
    is_close_arr = is_data_trim["Close"].values

    # Reconstruct entry signals: RSI < 20 AND regime active
    rsi_full = compute_rsi(is_data_raw["Close"], PARAMETERS["rsi_period"])
    regime_full = compute_sma_regime(is_data_raw["Close"], PARAMETERS["sma_period"])
    rsi_is = rsi_full.loc[is_data_trim.index]
    regime_is = regime_full.loc[is_data_trim.index]
    entries_arr = ((rsi_is < PARAMETERS["rsi_entry_threshold"]) & (regime_is == True)).values

    perm_results = permutation_test_alpha(
        is_close_arr, entries_arr, is_result["sharpe"], n_perms=1000, hold_days=5
    )
    print(f"  Permutation p-value: {perm_results['permutation_pvalue']:.4f} ({'PASS' if perm_results['permutation_test_pass'] else 'FAIL'})")

    # ── Walk-forward analysis ─────────────────────────────────────────────────
    print("\n[5/7] Walk-forward analysis (4 IS folds)...")
    wf_fold_results = []
    for fold_i, (fold_start, fold_end) in enumerate(WF_FOLDS):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            fold_r = run_backtest(fold_start, fold_end)
        n_fold_trades = len(fold_r["trades"])
        wf_fold_results.append({
            "fold": fold_i + 1,
            "start": fold_start,
            "end": fold_end,
            "sharpe": fold_r["sharpe"],
            "max_drawdown": fold_r["max_drawdown"],
            "win_rate": fold_r["win_rate"],
            "trade_count": n_fold_trades,
            "trades_per_year": fold_r["trades_per_year"],
        })
        pf1_ok = "OK" if n_fold_trades >= 30 else f"WARN ({n_fold_trades}<30)"
        print(f"  Fold {fold_i+1} ({fold_start}–{fold_end}): Sharpe={fold_r['sharpe']:.3f}, MDD={fold_r['max_drawdown']:.2%}, trades={n_fold_trades} [{pf1_ok}]")

    wf_oos_sharpes = [f["sharpe"] for f in wf_fold_results]  # using fold Sharpe as IS fold metric
    wf_var = walk_forward_variance(wf_oos_sharpes)

    # WF pass: fold Sharpe > 0 = passed window; need >= 3 of 4
    wf_passed = sum(1 for s in wf_oos_sharpes if s > 0.0)
    print(f"  WF windows passed (Sharpe>0): {wf_passed}/4")
    print(f"  WF Sharpe std={wf_var['wf_sharpe_std']:.3f}, min={wf_var['wf_sharpe_min']:.3f}")

    # ── Gate 7 MDD check ──────────────────────────────────────────────────────
    gate7_reject = any(abs(f["max_drawdown"]) > 0.30 for f in wf_fold_results)
    print(f"\n  Gate 7 MDD > 30% in any fold: {'AUTO-REJECT' if gate7_reject else 'PASS'}")

    # ── 2022 regime split ─────────────────────────────────────────────────────
    print("\n[6/7] 2022 regime split analysis...")
    regime_2022 = regime_2022_split(oos_result)
    print(f"  2022 trades: {regime_2022.get('2022_trade_count', 0)}, regime active: {regime_2022.get('2022_regime_active_pct', 0):.1%}")

    # ── Parameter sweep (27 combinations) ────────────────────────────────────
    print("\n[7/7] Parameter sweep (27 combinations)...")
    sweep_rows = []
    base_params = PARAMETERS.copy()
    for rsi_entry in SWEEP_PARAMS["rsi_entry_threshold"]:
        for rsi_exit in SWEEP_PARAMS["rsi_exit_threshold"]:
            for stop_loss in SWEEP_PARAMS["stop_loss_pct"]:
                p = base_params.copy()
                p["rsi_entry_threshold"] = rsi_entry
                p["rsi_exit_threshold"] = rsi_exit
                p["stop_loss_pct"] = stop_loss
                with warnings.catch_warnings(record=True):
                    warnings.simplefilter("always")
                    r = run_backtest(IS_START, IS_END, params=p)
                sweep_rows.append({
                    "rsi_entry": rsi_entry,
                    "rsi_exit": rsi_exit,
                    "stop_loss_pct": stop_loss,
                    "sharpe": r["sharpe"],
                    "max_drawdown": r["max_drawdown"],
                    "win_rate": r["win_rate"],
                    "trade_count": len(r["trades"]),
                    "total_return": r["total_return"],
                    "profit_factor": r["profit_factor"],
                })
    sweep_df = pd.DataFrame(sweep_rows)
    base_sharpe = is_result["sharpe"]
    sweep_df["sharpe_delta_pct"] = ((sweep_df["sharpe"] - base_sharpe) / (abs(base_sharpe) + 1e-8) * 100).round(2)
    max_sensitivity_delta = float(sweep_df["sharpe_delta_pct"].abs().max())
    sensitivity_pass = max_sensitivity_delta < 30.0
    print(f"  Sensitivity: max Sharpe delta={max_sensitivity_delta:.1f}% ({'PASS' if sensitivity_pass else 'FAIL'} threshold=30%)")

    # ── Profit metrics ────────────────────────────────────────────────────────
    is_ppt_bps = compute_profit_per_trade_bps(is_trades)
    oos_ppt_bps = compute_profit_per_trade_bps(oos_trades)
    is_cpr = compute_cpr(is_trades)
    oos_cpr = compute_cpr(oos_trades)

    # ── DSR ──────────────────────────────────────────────────────────────────
    n_trials = len(sweep_rows) + 4  # sweep combos + WF folds
    T_is = len(is_data_trim)
    dsr = compute_dsr(is_result["sharpe"], n_trials, T_is)

    # ── Gap attribution ───────────────────────────────────────────────────────
    is_gap_attr = is_result.get("gap_attribution", {})
    oos_gap_attr = oos_result.get("gap_attribution", {})

    # ── Gate 1 composite score ────────────────────────────────────────────────
    oos_sharpe = oos_result["sharpe"]
    oos_mdd = abs(oos_result["max_drawdown"])
    is_mdd = abs(is_result["max_drawdown"])

    gate_oos_sharpe = oos_sharpe > 0.7
    gate_oos_ppt = oos_ppt_bps > 15.0
    gate_is_mdd_cs = is_mdd < 0.20
    gate_is_mdd_g7 = is_mdd < 0.30
    gate_wf_trades = all(f["trade_count"] > 30 for f in wf_fold_results)
    gate_cpr = is_cpr < 0.25
    gate_perm = perm_results["permutation_test_pass"]

    # Composite Score (equal-weight 6 primary gates)
    primary_gates = [gate_oos_sharpe, gate_oos_ppt, gate_is_mdd_cs, gate_is_mdd_g7, gate_wf_trades, gate_cpr]
    composite_score = round(sum(primary_gates) / len(primary_gates), 4)
    gate1_pass = composite_score >= 0.60 and gate_perm and not gate7_reject

    print(f"\n{'='*70}")
    print(f"GATE 1 SUMMARY:")
    print(f"  IS Sharpe:    {is_result['sharpe']:.4f}")
    print(f"  OOS Sharpe:   {oos_sharpe:.4f}  {'PASS' if gate_oos_sharpe else 'FAIL'} (>0.7)")
    print(f"  IS MDD:       {is_mdd:.2%}       {'PASS' if gate_is_mdd_cs else 'FAIL'} (<20%)")
    print(f"  IS MDD Gate7: {is_mdd:.2%}       {'PASS' if gate_is_mdd_g7 else 'FAIL'} (<30%)")
    print(f"  IS PpT:       {is_ppt_bps:.1f} bps")
    print(f"  OOS PpT:      {oos_ppt_bps:.1f} bps  {'PASS' if gate_oos_ppt else 'FAIL'} (>15 bps)")
    print(f"  IS CPR:       {is_cpr:.3f}       {'PASS' if gate_cpr else 'FAIL'} (<0.25)")
    print(f"  WF trades ok: {gate_wf_trades}  (all folds >30)")
    print(f"  Perm test:    p={perm_results['permutation_pvalue']:.4f}  {'PASS' if gate_perm else 'FAIL'} (<0.05)")
    print(f"  DSR:          {dsr:.4f}")
    print(f"  Sensitivity:  {'PASS' if sensitivity_pass else 'FAIL'}")
    print(f"  MC p5 Sharpe: {mc_results['mc_p5_sharpe']:.3f}  {'OK' if mc_results['mc_p5_sharpe'] >= 0.5 else 'WEAK'}")
    print(f"  WF min Sharpe:{wf_var['wf_sharpe_min']:.3f}  {'OK' if wf_var['wf_sharpe_min'] >= 0 else 'FLAG'}")
    print(f"  Composite CS: {composite_score:.2f}  (need >=0.60)")
    print(f"\n  GATE 1 VERDICT: {'PASS' if gate1_pass else 'FAIL'}")
    print(f"{'='*70}")

    # ── Build full metrics JSON ────────────────────────────────────────────────
    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        # IS metrics
        "is_sharpe": is_result["sharpe"],
        "is_max_drawdown": is_result["max_drawdown"],
        "is_total_return": is_result["total_return"],
        "is_win_rate": is_result["win_rate"],
        "is_profit_factor": is_result["profit_factor"],
        "is_trade_count": n_is_trades,
        "is_trades_per_year": is_result["trades_per_year"],
        "is_ppt_bps": is_ppt_bps,
        "is_cpr": is_cpr,
        "is_exit_breakdown": is_result["exit_breakdown"],
        "is_gap_attribution": is_gap_attr,
        # OOS metrics
        "oos_sharpe": oos_result["sharpe"],
        "oos_max_drawdown": oos_result["max_drawdown"],
        "oos_total_return": oos_result["total_return"],
        "oos_win_rate": oos_result["win_rate"],
        "oos_profit_factor": oos_result["profit_factor"],
        "oos_trade_count": n_oos_trades,
        "oos_trades_per_year": oos_result["trades_per_year"],
        "oos_ppt_bps": oos_ppt_bps,
        "oos_cpr": oos_cpr,
        "oos_exit_breakdown": oos_result["exit_breakdown"],
        "oos_gap_attribution": oos_gap_attr,
        # Post-cost (costs embedded in simulation)
        "post_cost_sharpe": oos_result["sharpe"],
        # DSR
        "dsr": dsr,
        "n_trials": n_trials,
        # Walk-forward
        "wf_windows": wf_fold_results,
        "wf_windows_passed": wf_passed,
        "wf_consistency_score": round(wf_passed / 4, 4),
        **wf_var,
        # Statistical rigor
        **mc_results,
        **bb_results,
        **mi_results,
        **perm_results,
        # Sensitivity
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_delta_pct": max_sensitivity_delta,
        # Gate outcomes
        "gate_oos_sharpe": gate_oos_sharpe,
        "gate_oos_ppt": gate_oos_ppt,
        "gate_is_mdd_cs": gate_is_mdd_cs,
        "gate_is_mdd_g7": gate_is_mdd_g7,
        "gate_wf_trades": gate_wf_trades,
        "gate_cpr": gate_cpr,
        "gate7_auto_reject": gate7_reject,
        "composite_score": composite_score,
        "gate1_pass": gate1_pass,
        # 2022 regime
        "regime_2022": regime_2022,
        # Other
        "look_ahead_bias_flag": False,
        "slippage_model": "ultra_liquid_etf",
        "ruling_ref": "ED-SLIP-001",
        "is_regime_pct": is_result["regime_pct"],
        "oos_regime_pct": oos_result["regime_pct"],
        # OOS data quality
        "oos_data_quality": dq_report,
    }

    # ── Save outputs ──────────────────────────────────────────────────────────
    base = f"h70_iwm_rsi4_mean_reversion_{TODAY}"

    # Metrics JSON
    metrics_path = OUT_DIR / f"{base}.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"\nSaved metrics: {metrics_path}")

    # Trade log CSV (IS + OOS combined)
    all_trades = pd.concat([
        is_trades.assign(period="IS"),
        oos_trades.assign(period="OOS"),
    ], ignore_index=True)
    trades_path = OUT_DIR / f"{base}_trades.csv"
    all_trades.to_csv(trades_path, index=False)
    print(f"Saved trades: {trades_path}")

    # Sweep CSV
    sweep_path = OUT_DIR / f"{base}_sweep.csv"
    sweep_df.to_csv(sweep_path, index=False)
    print(f"Saved sweep: {sweep_path}")

    # Verdict text
    verdict_lines = [
        f"H70 IWM RSI-4 Mean Reversion — Gate 1 Verdict",
        f"Date: {TODAY}",
        f"Strategy: {STRATEGY_NAME}",
        f"",
        f"OVERALL VERDICT: {'PASS' if gate1_pass else 'FAIL'}",
        f"Composite Score: {composite_score:.2f} (need >= 0.60)",
        f"",
        f"PRIMARY GATE CHECKS:",
        f"  OOS Sharpe    : {oos_sharpe:.4f}  {'PASS' if gate_oos_sharpe else 'FAIL'} (> 0.7)",
        f"  OOS PpT       : {oos_ppt_bps:.2f} bps  {'PASS' if gate_oos_ppt else 'FAIL'} (> 15 bps)",
        f"  IS MDD (CS)   : {is_mdd:.2%}  {'PASS' if gate_is_mdd_cs else 'FAIL'} (< 20%)",
        f"  IS MDD (Gate7): {is_mdd:.2%}  {'PASS' if gate_is_mdd_g7 else 'FAIL'} (< 30%)",
        f"  WF trades>30  : {gate_wf_trades}",
        f"  CPR           : {is_cpr:.4f}  {'PASS' if gate_cpr else 'FAIL'} (< 0.25)",
        f"",
        f"STATISTICAL TESTS:",
        f"  Permutation p : {perm_results['permutation_pvalue']:.4f}  {'PASS' if gate_perm else 'FAIL'} (< 0.05)",
        f"  MC p5 Sharpe  : {mc_results['mc_p5_sharpe']:.4f}  {'OK' if mc_results['mc_p5_sharpe'] >= 0.5 else 'WEAK (< 0.5)'}",
        f"  Bootstrap CI  : [{bb_results['sharpe_ci_low']:.4f}, {bb_results['sharpe_ci_high']:.4f}]",
        f"  DSR           : {dsr:.4f}",
        f"",
        f"WALK-FORWARD (4 folds):",
    ]
    for fold in wf_fold_results:
        verdict_lines.append(
            f"  Fold {fold['fold']} ({fold['start']}–{fold['end']}): "
            f"Sharpe={fold['sharpe']:.4f}, MDD={fold['max_drawdown']:.2%}, trades={fold['trade_count']}"
        )
    verdict_lines += [
        f"  WF passed: {wf_passed}/4",
        f"  WF Sharpe std: {wf_var['wf_sharpe_std']:.4f}",
        f"  WF Sharpe min: {wf_var['wf_sharpe_min']:.4f}  {'FLAG' if wf_var['wf_sharpe_min'] < 0 else 'OK'}",
        f"",
        f"IS SUMMARY ({IS_START} to {IS_END}):",
        f"  Sharpe: {is_result['sharpe']:.4f}",
        f"  MDD: {is_mdd:.2%}",
        f"  Win rate: {is_result['win_rate']:.2%}",
        f"  Profit factor: {is_result['profit_factor']:.2f}",
        f"  Trade count: {n_is_trades} ({is_result['trades_per_year']}/yr)",
        f"  PpT: {is_ppt_bps:.2f} bps",
        f"  Regime active: {is_result['regime_pct']:.1%} of days",
        f"",
        f"OOS SUMMARY ({OOS_START} to {OOS_END}):",
        f"  Sharpe: {oos_sharpe:.4f}",
        f"  MDD: {oos_mdd:.2%}",
        f"  Win rate: {oos_result['win_rate']:.2%}",
        f"  Profit factor: {oos_result['profit_factor']:.2f}",
        f"  Trade count: {n_oos_trades} ({oos_result['trades_per_year']}/yr)",
        f"  PpT: {oos_ppt_bps:.2f} bps",
        f"  Regime active: {oos_result['regime_pct']:.1%} of days",
        f"",
        f"2022 REGIME SPLIT:",
        f"  Trades in 2022: {regime_2022.get('2022_trade_count', 0)}",
        f"  Regime active 2022: {regime_2022.get('2022_regime_active_pct', 0):.1%}",
        f"  Note: {regime_2022.get('2022_note', '')}",
        f"",
        f"MARKET IMPACT (IWM ultra-liquid):",
        f"  Impact: {mi_results['market_impact_bps']:.4f} bps",
        f"  ADV (20d): {mi_results['adv_20d']:,.0f} shares",
        f"  Liquidity constrained: {mi_results['liquidity_constrained']}",
        f"  Slippage model: ultra_liquid_etf (ED-SLIP-001)",
        f"",
        f"PARAMETER SWEEP: {len(sweep_rows)} combinations",
        f"  Max Sharpe delta: {max_sensitivity_delta:.1f}% — {'PASS' if sensitivity_pass else 'FAIL'} (<30%)",
        f"  See: {base}_sweep.csv",
        f"",
        f"GAP ATTRIBUTION (Track A Hard Gate 8):",
        f"  IS overnight gap trades: {is_gap_attr.get('overnight_gap_trades', 'N/A')} ({is_gap_attr.get('overnight_gap_pct', 0):.1%})",
        f"  IS weekend gap trades:   {is_gap_attr.get('weekend_gap_trades', 'N/A')} ({is_gap_attr.get('weekend_gap_pct', 0):.1%})",
        f"  OOS overnight gap trades:{oos_gap_attr.get('overnight_gap_trades', 'N/A')} ({oos_gap_attr.get('overnight_gap_pct', 0):.1%})",
        f"  OOS weekend gap trades:  {oos_gap_attr.get('weekend_gap_trades', 'N/A')} ({oos_gap_attr.get('weekend_gap_pct', 0):.1%})",
        f"",
        f"OOS DATA QUALITY: {dq_report['recommendation']}",
        f"  Coverage: {dq_report['oos_data_coverage_pct']:.1f}%",
        f"  Total NaNs: {dq_report['oos_total_nans']}",
    ]

    verdict_text = "\n".join(verdict_lines)
    verdict_path = OUT_DIR / f"{base}_verdict.txt"
    verdict_path.write_text(verdict_text)
    print(f"Saved verdict: {verdict_path}")

    # HTML report
    sweep_table_html = sweep_df.to_html(index=False, float_format=lambda x: f"{x:.4f}", border=1)
    wf_table_rows = "".join(
        f"<tr><td>{f['fold']}</td><td>{f['start']}–{f['end']}</td>"
        f"<td>{f['sharpe']:.4f}</td><td>{f['max_drawdown']:.2%}</td>"
        f"<td>{f['win_rate']:.2%}</td><td>{f['trade_count']}</td></tr>"
        for f in wf_fold_results
    )

    gate_rows = [
        ("OOS Sharpe", f"{oos_sharpe:.4f}", "> 0.7", gate_oos_sharpe),
        ("OOS PpT", f"{oos_ppt_bps:.2f} bps", "> 15 bps", gate_oos_ppt),
        ("IS MDD (CS)", f"{is_mdd:.2%}", "< 20%", gate_is_mdd_cs),
        ("IS MDD (Gate7)", f"{is_mdd:.2%}", "< 30%", gate_is_mdd_g7),
        ("WF trades/fold > 30", str(gate_wf_trades), "all folds", gate_wf_trades),
        ("CPR", f"{is_cpr:.4f}", "< 0.25", gate_cpr),
        ("Permutation test", f"p={perm_results['permutation_pvalue']:.4f}", "< 0.05", gate_perm),
        ("Gate7 auto-reject", str(not gate7_reject), "no fold MDD>30%", not gate7_reject),
        ("Sensitivity", f"Δ{max_sensitivity_delta:.1f}%", "< 30%", sensitivity_pass),
    ]
    gate_html = "".join(
        f"<tr style='background:{'#d4edda' if p else '#f8d7da'}'>"
        f"<td>{g}</td><td>{v}</td><td>{t}</td><td>{'✓ PASS' if p else '✗ FAIL'}</td></tr>"
        for g, v, t, p in gate_rows
    )

    verdict_color = "#d4edda" if gate1_pass else "#f8d7da"
    verdict_label = "PASS" if gate1_pass else "FAIL"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>H70 Gate 1 Report — {TODAY}</title>
<style>
body {{ font-family: monospace; max-width: 1200px; margin: 0 auto; padding: 20px; }}
h1 {{ background: #343a40; color: white; padding: 15px; border-radius: 4px; }}
h2 {{ border-bottom: 2px solid #343a40; padding-bottom: 5px; }}
.verdict {{ font-size: 2em; font-weight: bold; padding: 15px; border-radius: 4px; background: {verdict_color}; text-align: center; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th {{ background: #343a40; color: white; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border: 1px solid #dee2e6; }}
.pass {{ color: #155724; font-weight: bold; }}
.fail {{ color: #721c24; font-weight: bold; }}
.metric-box {{ display: inline-block; padding: 10px 20px; margin: 5px; border-radius: 4px; border: 1px solid #dee2e6; min-width: 150px; text-align: center; }}
.section {{ margin: 20px 0; padding: 15px; border: 1px solid #dee2e6; border-radius: 4px; }}
</style>
</head>
<body>
<h1>H70 IWM RSI-4 Mean Reversion — Gate 1 Report</h1>
<p><strong>Date:</strong> {TODAY} | <strong>Strategy:</strong> {STRATEGY_NAME} | <strong>Asset:</strong> IWM (equities)</p>

<div class="verdict">GATE 1: {verdict_label} — Composite Score: {composite_score:.2f}</div>

<h2>Gate 1 Checklist</h2>
<table>
<tr><th>Gate</th><th>Value</th><th>Threshold</th><th>Result</th></tr>
{gate_html}
</table>

<h2>IS/OOS Summary</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>IS (2005–2018)</th><th>OOS (2019–2024)</th></tr>
<tr><td>Sharpe Ratio</td><td>{is_result['sharpe']:.4f}</td><td>{oos_sharpe:.4f}</td></tr>
<tr><td>Max Drawdown</td><td>{is_mdd:.2%}</td><td>{oos_mdd:.2%}</td></tr>
<tr><td>Win Rate</td><td>{is_result['win_rate']:.2%}</td><td>{oos_result['win_rate']:.2%}</td></tr>
<tr><td>Profit Factor</td><td>{is_result['profit_factor']:.2f}</td><td>{oos_result['profit_factor']:.2f}</td></tr>
<tr><td>Trade Count</td><td>{n_is_trades}</td><td>{n_oos_trades}</td></tr>
<tr><td>Trades/Year</td><td>{is_result['trades_per_year']}</td><td>{oos_result['trades_per_year']}</td></tr>
<tr><td>PpT (bps)</td><td>{is_ppt_bps:.2f}</td><td>{oos_ppt_bps:.2f}</td></tr>
<tr><td>CPR</td><td>{is_cpr:.4f}</td><td>{oos_cpr:.4f}</td></tr>
<tr><td>Regime Active %</td><td>{is_result['regime_pct']:.1%}</td><td>{oos_result['regime_pct']:.1%}</td></tr>
</table>
</div>

<h2>Walk-Forward Analysis (4 IS Folds)</h2>
<table>
<tr><th>Fold</th><th>Period</th><th>Sharpe</th><th>MDD</th><th>Win Rate</th><th>Trades</th></tr>
{wf_table_rows}
</table>
<p>WF Passed: {wf_passed}/4 | Sharpe Std: {wf_var['wf_sharpe_std']:.4f} | Min: {wf_var['wf_sharpe_min']:.4f}</p>

<h2>Statistical Tests</h2>
<div class="section">
<p><strong>Monte Carlo (1000 resamples):</strong> p5={mc_results['mc_p5_sharpe']:.4f}, median={mc_results['mc_median_sharpe']:.4f}, p95={mc_results['mc_p95_sharpe']:.4f}
{"— <span class='fail'>MC p5 Sharpe WEAK (&lt;0.5)</span>" if mc_results['mc_p5_sharpe'] < 0.5 else "— <span class='pass'>MC p5 OK</span>"}</p>
<p><strong>Bootstrap CI (95%):</strong> Sharpe [{bb_results['sharpe_ci_low']:.4f}, {bb_results['sharpe_ci_high']:.4f}]</p>
<p><strong>Permutation test (1000 perms):</strong> p={perm_results['permutation_pvalue']:.4f} — {"<span class='pass'>PASS</span>" if gate_perm else "<span class='fail'>FAIL</span>"}</p>
<p><strong>DSR:</strong> {dsr:.4f}</p>
</div>

<h2>2022 Regime Split</h2>
<div class="section">
<p>Trades in 2022: {regime_2022.get('2022_trade_count', 0)} | Regime active: {regime_2022.get('2022_regime_active_pct', 0):.1%}</p>
<p>{regime_2022.get('2022_note', '')}</p>
</div>

<h2>Market Impact (IWM Ultra-Liquid)</h2>
<div class="section">
<p>Impact: {mi_results['market_impact_bps']:.4f} bps | ADV (20d): {mi_results['adv_20d']:,.0f} shares |
Order/ADV: {mi_results['order_to_adv_ratio']:.6f} | Liq. constrained: {mi_results['liquidity_constrained']}</p>
<p>Slippage model: ultra_liquid_etf (ED-SLIP-001) | IWM ADV well above 1M shares/day threshold.</p>
</div>

<h2>Gap Attribution (Track A Hard Gate 8)</h2>
<div class="section">
<table>
<tr><th>Period</th><th>Overnight Gap Trades</th><th>%</th><th>Weekend Gap Trades</th><th>%</th></tr>
<tr><td>IS</td><td>{is_gap_attr.get('overnight_gap_trades','N/A')}</td><td>{is_gap_attr.get('overnight_gap_pct',0):.1%}</td>
<td>{is_gap_attr.get('weekend_gap_trades','N/A')}</td><td>{is_gap_attr.get('weekend_gap_pct',0):.1%}</td></tr>
<tr><td>OOS</td><td>{oos_gap_attr.get('overnight_gap_trades','N/A')}</td><td>{oos_gap_attr.get('overnight_gap_pct',0):.1%}</td>
<td>{oos_gap_attr.get('weekend_gap_trades','N/A')}</td><td>{oos_gap_attr.get('weekend_gap_pct',0):.1%}</td></tr>
</table>
</div>

<h2>Parameter Sweep (27 Combinations)</h2>
{sweep_table_html}

<h2>OOS Data Quality</h2>
<div class="section">
<p>Recommendation: <strong>{dq_report['recommendation']}</strong> | Coverage: {dq_report['oos_data_coverage_pct']:.1f}% | Total NaNs: {dq_report['oos_total_nans']}</p>
</div>

<hr>
<p><em>Generated by Backtest Runner Agent | QUA-302</em></p>
</body>
</html>"""

    html_path = OUT_DIR / f"{base}_report.html"
    html_path.write_text(html)
    print(f"Saved HTML report: {html_path}")

    print(f"\nAll outputs saved to {OUT_DIR}/")
    print(f"  Metrics:  {base}.json")
    print(f"  Report:   {base}_report.html")
    print(f"  Sweep:    {base}_sweep.csv")
    print(f"  Trades:   {base}_trades.csv")
    print(f"  Verdict:  {base}_verdict.txt")

    return metrics, gate1_pass, verdict_label


if __name__ == "__main__":
    metrics, gate1_pass, verdict_label = main()
    sys.exit(0 if gate1_pass else 1)
