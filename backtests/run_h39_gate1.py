"""
Gate 1 Backtest Runner: H39 Equity Breadth Timer
Backtest Runner Agent | QUA-314 | 2026-03-17

Runs full Gate 1 evaluation per criteria.md v1.3:
- IS backtest (2007-01-01 to 2021-12-31)
- OOS backtest (2022-01-01 to 2025-12-31)
- 4 walk-forward folds (70/30 IS/OOS split, chronological)
- Parameter sensitivity sweep (5 combinations)
- Monte Carlo Sharpe (1000 simulations, trade PnL bootstrap)
- Block bootstrap 95% CI for Sharpe, MDD, win rate
- Market impact estimation (SPY, square-root model)
- Permutation p-value for alpha (500 permutations)
- Walk-forward variance metrics
- OOS data quality validation
- Gate 1 verdict JSON + markdown report

Outputs:
- backtests/H39_EquityBreadthTimer_<date>.json
- backtests/h39_equity_breadth_timer_gate1_report.md
"""

import sys
import os
import json
import warnings
import traceback
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.h39_equity_breadth_timer import (
    run_backtest,
    PARAMETERS,
    download_data,
    compute_sector_breadth,
    generate_weekly_signals,
    compute_transaction_costs,
    simulate_strategy,
    compute_metrics,
)

# ── Constants ──────────────────────────────────────────────────────────────────
IS_START = "2007-01-01"
IS_END   = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2025-12-31"
TODAY = date.today().strftime("%Y-%m-%d")
STRATEGY_NAME = "H39_EquityBreadthTimer"

# Primary configuration
PRIMARY_ENTRY = 7
PRIMARY_EXIT  = 5
PRIMARY_SMA   = 200

# Parameter sensitivity grid
PARAM_GRID = [
    {"entry_threshold": 7, "exit_threshold": 5, "sma_lookback": 200},  # primary
    {"entry_threshold": 6, "exit_threshold": 4, "sma_lookback": 200},
    {"entry_threshold": 8, "exit_threshold": 6, "sma_lookback": 200},
    {"entry_threshold": 7, "exit_threshold": 5, "sma_lookback": 150},
    {"entry_threshold": 7, "exit_threshold": 5, "sma_lookback": 250},
]

# Gate 1 thresholds
G1_IS_SHARPE   = 1.0
G1_OOS_SHARPE  = 0.7
G1_IS_MDD      = -0.20  # less than 20% drawdown
G1_OOS_MDD     = -0.25
G1_WIN_RATE    = 0.50
G1_DSR         = 0.0
G1_WF_PASS     = 3       # of 4 folds
G1_MIN_TRADES  = 50      # CEO exception granted for breadth timer (low-frequency)

TRADING_DAYS_PER_YEAR = 252


# ── Helpers ────────────────────────────────────────────────────────────────────

def pass_fail(value, threshold, direction="above"):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    if direction == "above":
        return "PASS" if value > threshold else "FAIL"
    else:
        return "PASS" if value < threshold else "FAIL"


def pct(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.2%}"


def fmt(v, decimals=4):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.{decimals}f}"


def compute_profit_factor(result_df: pd.DataFrame) -> float:
    pnls = result_df[result_df["pnl"] != 0]["pnl"]
    if len(pnls) == 0:
        return np.nan
    gross_profit = pnls[pnls > 0].sum()
    gross_loss   = abs(pnls[pnls < 0].sum())
    if gross_loss == 0:
        return float("inf")
    return float(gross_profit / gross_loss)


# ── Statistical Rigor Pipeline ─────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(252)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe":    float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
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
        s = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
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


def compute_market_impact(ticker: str, order_qty: float, start: str, end: str) -> dict:
    import yfinance as yf
    try:
        hist = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        adv = hist["Volume"].rolling(20).mean().iloc[-1]
        sigma = hist["Close"].pct_change().std()
        k = 0.1
        impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
        impact_bps = impact_pct * 10000
        liquidity_constrained = bool(order_qty > 0.01 * adv)
        return {
            "market_impact_bps":   float(impact_bps),
            "liquidity_constrained": liquidity_constrained,
            "order_to_adv_ratio":  float(order_qty / (adv + 1e-8)),
        }
    except Exception as e:
        print(f"[WARN] market impact calc failed: {e}")
        return {"market_impact_bps": np.nan, "liquidity_constrained": False, "order_to_adv_ratio": np.nan}


def permutation_test_alpha(
    result_df: pd.DataFrame,
    observed_sharpe: float,
    n_perms: int = 500,
) -> dict:
    """
    Permute entry signals by randomly reassigning entry dates.
    Sharpe computed from daily strategy returns of permuted runs.
    """
    prices = result_df["spy_close"].values
    entry_dates = result_df[result_df["entry_price"].notna()].index
    n_entries = len(entry_dates)
    n = len(prices)

    if n_entries == 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    # Use trade-level PnL from permuted 5-day holding periods
    permuted_sharpes = []
    for _ in range(n_perms):
        perm_idx = np.random.choice(n - 5, size=n_entries, replace=False)
        trade_returns = []
        for idx in perm_idx:
            exit_idx = min(idx + 5, n - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
            trade_returns.append(ret)
        arr = np.array(trade_returns)
        if len(arr) > 1:
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(252 / 5)
        else:
            s = 0.0
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue":     p_value,
        "permutation_test_pass":  p_value <= 0.05,
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array([s for s in wf_oos_sharpes if s is not None and not np.isnan(s)])
    if len(arr) == 0:
        return {"wf_sharpe_std": np.nan, "wf_sharpe_min": np.nan}
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


def compute_dsr(returns_series: pd.Series, n_trials: int) -> float:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).
    DSR = SR * sqrt(T) * [1 - gamma3*SR + (gamma4-1)/4 * SR^2]^0.5
    approximated here as adjusting for multiple testing bias.
    """
    returns = returns_series.dropna().values
    T = len(returns)
    if T < 10:
        return np.nan
    sr = returns.mean() / (returns.std() + 1e-8) * np.sqrt(252)
    # Skewness and kurtosis
    from scipy import stats
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))  # excess kurtosis = kurt-3
    # Expected max SR under IID assumptions for n_trials strategies
    import math
    if n_trials <= 1:
        emax_sr = 0.0
    else:
        emax_sr = (1 - 0.5772156649 / math.log(n_trials)) * math.sqrt(2 * math.log(n_trials))
    # Psi (variance of SR estimator)
    sigma_sr = math.sqrt((1 + 0.5 * sr**2 - skew * sr + (kurt / 4) * sr**2) / (T - 1))
    dsr = (sr - emax_sr) / sigma_sr if sigma_sr > 0 else np.nan
    return float(dsr)


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(n_folds: int = 4) -> list:
    """
    4-fold chronological walk-forward over IS period (2007-2021).
    Uses expanding IS window approach.
    Each fold: fixed ~3.5-yr OOS window.
    """
    from dateutil.relativedelta import relativedelta

    total_start = pd.Timestamp(IS_START)
    total_end   = pd.Timestamp(IS_END)
    total_months = (total_end.year - total_start.year) * 12 + (total_end.month - total_start.month)

    fold_results = []
    oos_months = total_months // (n_folds + 1)   # ~28-30 months OOS each

    for fold in range(n_folds):
        # OOS window slides forward
        oos_start = total_start + relativedelta(months=oos_months * (fold + 1))
        oos_end   = oos_start + relativedelta(months=oos_months) - pd.DateOffset(days=1)
        if oos_end > total_end:
            oos_end = total_end

        # IS: from total_start to just before oos_start
        is_end_fold = oos_start - pd.DateOffset(days=1)

        is_start_str = total_start.strftime("%Y-%m-%d")
        is_end_str   = is_end_fold.strftime("%Y-%m-%d")
        oos_start_str = oos_start.strftime("%Y-%m-%d")
        oos_end_str   = oos_end.strftime("%Y-%m-%d")

        print(f"  Fold {fold+1}: IS {is_start_str}→{is_end_str} | OOS {oos_start_str}→{oos_end_str}")

        try:
            is_res  = run_backtest(is_start_str,   is_end_str,   PRIMARY_ENTRY, PRIMARY_EXIT, PRIMARY_SMA)
            oos_res = run_backtest(oos_start_str, oos_end_str, PRIMARY_ENTRY, PRIMARY_EXIT, PRIMARY_SMA)

            is_sharpe  = is_res["metrics"]["sharpe"]
            oos_sharpe = oos_res["metrics"]["sharpe"]

            # OOS/IS consistency: OOS within 30% of IS
            if is_sharpe and is_sharpe != 0 and oos_sharpe is not None:
                consistency = abs(oos_sharpe - is_sharpe) / abs(is_sharpe)
                fold_pass = (
                    oos_sharpe is not None and
                    oos_sharpe > G1_OOS_SHARPE and
                    consistency <= 0.30
                )
            else:
                consistency = np.nan
                fold_pass = False

            fold_results.append({
                "fold": fold + 1,
                "is_start":  is_start_str,
                "is_end":    is_end_str,
                "oos_start": oos_start_str,
                "oos_end":   oos_end_str,
                "is_sharpe":   is_sharpe,
                "oos_sharpe":  oos_sharpe,
                "is_mdd":    is_res["metrics"]["max_drawdown"],
                "oos_mdd":   oos_res["metrics"]["max_drawdown"],
                "consistency": round(consistency, 4) if not np.isnan(consistency) else None,
                "fold_pass": fold_pass,
            })
        except Exception as e:
            print(f"  [WARN] Fold {fold+1} failed: {e}")
            fold_results.append({
                "fold": fold + 1,
                "is_start": is_start_str, "is_end": is_end_str,
                "oos_start": oos_start_str, "oos_end": oos_end_str,
                "error": str(e), "fold_pass": False,
            })

    return fold_results


# ── Sensitivity Sweep ──────────────────────────────────────────────────────────

def run_sensitivity_sweep() -> list:
    sweep_results = []
    for cfg in PARAM_GRID:
        label = f"entry={cfg['entry_threshold']},exit={cfg['exit_threshold']},sma={cfg['sma_lookback']}"
        print(f"  Sensitivity: {label}")
        try:
            res = run_backtest(IS_START, IS_END,
                               cfg["entry_threshold"],
                               cfg["exit_threshold"],
                               cfg["sma_lookback"])
            sweep_results.append({
                "entry_threshold": cfg["entry_threshold"],
                "exit_threshold":  cfg["exit_threshold"],
                "sma_lookback":    cfg["sma_lookback"],
                "is_sharpe":       res["metrics"]["sharpe"],
                "is_mdd":          res["metrics"]["max_drawdown"],
                "win_rate":        res["metrics"]["win_rate"],
                "trade_count":     res["metrics"]["trade_count"],
            })
        except Exception as e:
            sweep_results.append({
                "entry_threshold": cfg["entry_threshold"],
                "exit_threshold":  cfg["exit_threshold"],
                "sma_lookback":    cfg["sma_lookback"],
                "error": str(e),
            })
    return sweep_results


def sensitivity_pass(sweep_results: list, primary_sharpe: float) -> bool:
    """Pass if no config deviates > 30% from primary Sharpe."""
    if primary_sharpe is None or primary_sharpe == 0:
        return False
    for row in sweep_results:
        if "error" in row:
            continue
        s = row.get("is_sharpe")
        if s is None:
            continue
        if abs(s - primary_sharpe) / abs(primary_sharpe) > 0.30:
            return False
    return True


# ── OOS Data Quality ──────────────────────────────────────────────────────────

def validate_oos_data_inline(oos_result_df: pd.DataFrame, oos_metrics: dict) -> dict:
    """Inline OOS data quality check (mirrors oos_data_quality.py logic)."""
    critical_fields = ["sharpe", "max_drawdown", "win_rate"]
    advisory_fields = ["total_transaction_cost"]

    nan_critical = [f for f in critical_fields
                    if oos_metrics.get(f) is None or
                    (isinstance(oos_metrics.get(f), float) and np.isnan(oos_metrics[f]))]
    nan_advisory = [f for f in advisory_fields
                    if oos_metrics.get(f) is None or
                    (isinstance(oos_metrics.get(f), float) and np.isnan(oos_metrics[f]))]

    # Row coverage
    total_rows = len(oos_result_df)
    non_nan_rows = int(oos_result_df["strategy_return"].notna().sum())
    coverage = non_nan_rows / total_rows if total_rows > 0 else 0.0

    if nan_critical or coverage < 0.90:
        recommendation = "BLOCK"
    elif coverage < 0.95 or nan_advisory:
        recommendation = "WARN"
    else:
        recommendation = "PASS"

    return {
        "recommendation": recommendation,
        "nan_critical_fields": nan_critical,
        "advisory_nan_fields": nan_advisory,
        "row_coverage_pct": round(coverage * 100, 2),
        "total_rows": total_rows,
        "non_nan_rows": non_nan_rows,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    warnings.filterwarnings("ignore")
    np.random.seed(42)

    print("=" * 70)
    print("H39 EQUITY BREADTH TIMER — GATE 1 BACKTEST RUNNER")
    print("=" * 70)
    print(f"IS window:  {IS_START} → {IS_END}")
    print(f"OOS window: {OOS_START} → {OOS_END}")
    print(f"Primary params: entry>={PRIMARY_ENTRY} exit<={PRIMARY_EXIT} sma={PRIMARY_SMA}")
    print(f"Run date: {TODAY}")
    print()

    # ── 1. IS Backtest ─────────────────────────────────────────────────────────
    print("Step 1: IS backtest...")
    is_output = run_backtest(IS_START, IS_END, PRIMARY_ENTRY, PRIMARY_EXIT, PRIMARY_SMA)
    is_result_df = is_output["results"]
    is_metrics   = is_output["metrics"]
    data_warnings = is_output["data_warnings"]

    is_sharpe  = is_metrics["sharpe"]
    is_mdd     = is_metrics["max_drawdown"]
    is_trades  = is_metrics["trade_count"]
    is_winrate = is_metrics["win_rate"]
    is_pf      = compute_profit_factor(is_result_df)
    print(f"  IS Sharpe={is_sharpe}  MDD={pct(is_mdd)}  Trades={is_trades}  WinRate={pct(is_winrate)}")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────────
    print("Step 2: OOS backtest...")
    oos_output = run_backtest(OOS_START, OOS_END, PRIMARY_ENTRY, PRIMARY_EXIT, PRIMARY_SMA)
    oos_result_df = oos_output["results"]
    oos_metrics   = oos_output["metrics"]

    oos_sharpe  = oos_metrics["sharpe"]
    oos_mdd     = oos_metrics["max_drawdown"]
    oos_trades  = oos_metrics["trade_count"]
    oos_winrate = oos_metrics["win_rate"]
    oos_pf      = compute_profit_factor(oos_result_df)
    print(f"  OOS Sharpe={oos_sharpe}  MDD={pct(oos_mdd)}  Trades={oos_trades}  WinRate={pct(oos_winrate)}")

    # ── 3. OOS Data Quality Validation ────────────────────────────────────────
    print("Step 3: OOS data quality validation...")
    dq_report = validate_oos_data_inline(oos_result_df, oos_metrics)
    print(f"  DQ recommendation: {dq_report['recommendation']}")
    if dq_report["recommendation"] == "BLOCK":
        print(f"  [BLOCK] OOS data quality check failed: {dq_report}")
        # Still proceed but flag in verdict
        print("  [WARNING] Proceeding with BLOCK-level DQ — metrics may be unreliable")
    elif dq_report["recommendation"] == "WARN":
        print(f"  [WARN] {dq_report['advisory_nan_fields']}")

    # ── 4. Post-cost Sharpe ────────────────────────────────────────────────────
    # IS returns already incorporate transaction costs from simulation
    post_cost_sharpe = is_sharpe  # costs embedded in strategy_return

    # ── 5. DSR ────────────────────────────────────────────────────────────────
    print("Step 4: DSR calculation...")
    n_trials = len(PARAM_GRID) * 2  # sensitivity configs + IS/OOS splits
    dsr = compute_dsr(is_result_df["strategy_return"], n_trials)
    print(f"  DSR={fmt(dsr)}")

    # ── 6. Walk-Forward ────────────────────────────────────────────────────────
    print("Step 5: Walk-forward analysis (4 folds)...")
    wf_results = run_walk_forward(n_folds=4)
    wf_passes = sum(1 for r in wf_results if r.get("fold_pass", False))
    wf_oos_sharpes = [r.get("oos_sharpe") for r in wf_results]
    wf_pass = wf_passes >= G1_WF_PASS
    print(f"  Walk-forward: {wf_passes}/4 folds passed")
    for r in wf_results:
        print(f"    Fold {r['fold']}: IS={fmt(r.get('is_sharpe'))} OOS={fmt(r.get('oos_sharpe'))} "
              f"pass={r.get('fold_pass')}")

    # ── 7. Walk-Forward Variance ───────────────────────────────────────────────
    wf_var = walk_forward_variance(wf_oos_sharpes)
    print(f"  WF variance: std={fmt(wf_var['wf_sharpe_std'])} min={fmt(wf_var['wf_sharpe_min'])}")

    # ── 8. Monte Carlo ────────────────────────────────────────────────────────
    print("Step 6: Monte Carlo Sharpe (1000 sims)...")
    trade_pnls = is_result_df[is_result_df["pnl"] != 0]["pnl"].values
    if len(trade_pnls) >= 2:
        mc_results = monte_carlo_sharpe(trade_pnls, n_sims=1000)
    else:
        mc_results = {"mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan}
    print(f"  MC p5={fmt(mc_results['mc_p5_sharpe'])} median={fmt(mc_results['mc_median_sharpe'])} "
          f"p95={fmt(mc_results['mc_p95_sharpe'])}")

    # ── 9. Block Bootstrap CI ─────────────────────────────────────────────────
    print("Step 7: Block bootstrap CI...")
    is_returns = is_result_df["strategy_return"].fillna(0).values
    if len(is_returns) >= 10:
        ci_results = block_bootstrap_ci(is_returns, n_boots=1000)
    else:
        ci_results = {
            "sharpe_ci_low": np.nan, "sharpe_ci_high": np.nan,
            "mdd_ci_low": np.nan, "mdd_ci_high": np.nan,
            "win_rate_ci_low": np.nan, "win_rate_ci_high": np.nan,
        }
    print(f"  Sharpe 95% CI: [{fmt(ci_results['sharpe_ci_low'])}, {fmt(ci_results['sharpe_ci_high'])}]")

    # ── 10. Market Impact ─────────────────────────────────────────────────────
    print("Step 8: Market impact (SPY, 100 shares)...")
    mi_results = compute_market_impact("SPY", PARAMETERS["order_qty"], IS_START, IS_END)
    print(f"  Market impact: {fmt(mi_results['market_impact_bps'], 2)} bps  "
          f"Q/ADV={fmt(mi_results['order_to_adv_ratio'], 6)}  "
          f"liquidity_constrained={mi_results['liquidity_constrained']}")

    # ── 11. Permutation Test ──────────────────────────────────────────────────
    print("Step 9: Permutation test (500 permutations)...")
    if is_sharpe is not None and not np.isnan(is_sharpe):
        perm_results = permutation_test_alpha(is_result_df, is_sharpe, n_perms=500)
    else:
        perm_results = {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    print(f"  p-value={fmt(perm_results['permutation_pvalue'])} pass={perm_results['permutation_test_pass']}")

    # ── 12. Sensitivity Sweep ─────────────────────────────────────────────────
    print("Step 10: Parameter sensitivity sweep...")
    sweep = run_sensitivity_sweep()
    sens_pass = sensitivity_pass(sweep, is_sharpe)
    print(f"  Sensitivity pass: {sens_pass}")

    # ── 13. Gate 1 Verdict ────────────────────────────────────────────────────
    checks = {
        "IS Sharpe > 1.0":        pass_fail(is_sharpe, G1_IS_SHARPE) == "PASS",
        "OOS Sharpe > 0.7":       pass_fail(oos_sharpe, G1_OOS_SHARPE) == "PASS",
        "IS MDD < 20%":           pass_fail(is_mdd, G1_IS_MDD, "above") == "PASS",  # mdd is negative
        "OOS MDD < 25%":          pass_fail(oos_mdd, G1_OOS_MDD, "above") == "PASS",
        "Win Rate > 50%":         pass_fail(is_winrate, G1_WIN_RATE) == "PASS",
        "DSR > 0":                pass_fail(dsr, G1_DSR) == "PASS",
        "WF >= 3/4 folds":        wf_pass,
        "Trade count >= 50 (IS)": is_trades >= G1_MIN_TRADES,
        "Sensitivity pass":       sens_pass,
        "Permutation p <= 0.05":  perm_results["permutation_test_pass"],
        "MC p5 Sharpe >= 0.5":    mc_results["mc_p5_sharpe"] >= 0.5 if not np.isnan(mc_results["mc_p5_sharpe"]) else False,
        "DQ not BLOCK":           dq_report["recommendation"] != "BLOCK",
    }

    passed = sum(1 for v in checks.values() if v)
    total  = len(checks)
    n_critical_fail = sum(1 for k, v in checks.items()
                          if not v and k in [
                              "IS Sharpe > 1.0", "OOS Sharpe > 0.7",
                              "IS MDD < 20%", "WF >= 3/4 folds"
                          ])

    if n_critical_fail == 0 and passed >= total - 2:
        overall_verdict = "PASS"
    elif n_critical_fail == 0 and passed >= total - 4:
        overall_verdict = "CONDITIONAL PASS"
    else:
        overall_verdict = "FAIL"

    gate1_pass = overall_verdict in ("PASS", "CONDITIONAL PASS")

    print()
    print("=" * 70)
    print(f"GATE 1 VERDICT: {overall_verdict}  ({passed}/{total} checks passed)")
    print("=" * 70)
    for k, v in checks.items():
        print(f"  {'✓' if v else '✗'}  {k}")
    print()

    # ── 14. Build JSON Metrics ─────────────────────────────────────────────────
    # Trade log
    trade_log = []
    entries = is_result_df[is_result_df["entry_price"].notna()]
    exits   = is_result_df[is_result_df["exit_price"].notna()]
    for _, row in entries.iterrows():
        tid = int(row["trade_id"])
        exit_rows = exits[exits["trade_id"] == tid]
        exit_date = exit_rows.index[0].strftime("%Y-%m-%d") if len(exit_rows) > 0 else None
        exit_price = float(exit_rows["exit_price"].iloc[0]) if len(exit_rows) > 0 else None
        pnl = float(exit_rows["pnl"].iloc[0]) if len(exit_rows) > 0 else None
        trade_log.append({
            "trade_id":    tid,
            "entry_date":  row.name.strftime("%Y-%m-%d"),
            "entry_price": round(float(row["entry_price"]), 4),
            "exit_date":   exit_date,
            "exit_price":  round(exit_price, 4) if exit_price else None,
            "pnl":         round(pnl, 2) if pnl else None,
        })

    metrics_json = {
        "strategy_name":  STRATEGY_NAME,
        "date":           TODAY,
        "asset_class":    "equities",
        # Core metrics
        "is_sharpe":       is_sharpe,
        "oos_sharpe":      oos_sharpe,
        "is_max_drawdown": is_mdd,
        "oos_max_drawdown": oos_mdd,
        "win_rate":        is_winrate,
        "oos_win_rate":    oos_winrate,
        "profit_factor":   round(is_pf, 4) if not np.isnan(is_pf) and is_pf != float("inf") else None,
        "oos_profit_factor": round(oos_pf, 4) if not np.isnan(oos_pf) and oos_pf != float("inf") else None,
        "trade_count":     is_trades,
        "oos_trade_count": oos_trades,
        "is_total_return": is_metrics["total_return"],
        "oos_total_return": oos_metrics["total_return"],
        "dsr":             round(dsr, 4) if not np.isnan(dsr) else None,
        # Walk-forward
        "wf_windows_passed":    wf_passes,
        "wf_windows_total":     4,
        "wf_consistency_score": round(sum(r.get("consistency", 0) or 0 for r in wf_results) / len(wf_results), 4),
        "wf_fold_results":      wf_results,
        "wf_sharpe_std":        wf_var["wf_sharpe_std"],
        "wf_sharpe_min":        wf_var["wf_sharpe_min"],
        # Statistical rigor
        "mc_p5_sharpe":         mc_results["mc_p5_sharpe"],
        "mc_median_sharpe":     mc_results["mc_median_sharpe"],
        "mc_p95_sharpe":        mc_results["mc_p95_sharpe"],
        "sharpe_ci_low":        ci_results["sharpe_ci_low"],
        "sharpe_ci_high":       ci_results["sharpe_ci_high"],
        "mdd_ci_low":           ci_results["mdd_ci_low"],
        "mdd_ci_high":          ci_results["mdd_ci_high"],
        "win_rate_ci_low":      ci_results["win_rate_ci_low"],
        "win_rate_ci_high":     ci_results["win_rate_ci_high"],
        # Market impact
        "market_impact_bps":    mi_results["market_impact_bps"],
        "liquidity_constrained": mi_results["liquidity_constrained"],
        "order_to_adv_ratio":   mi_results["order_to_adv_ratio"],
        # Post-cost
        "post_cost_sharpe":     post_cost_sharpe,
        # Permutation
        "permutation_pvalue":   perm_results["permutation_pvalue"],
        "permutation_test_pass": perm_results["permutation_test_pass"],
        # Sensitivity
        "sensitivity_pass":     sens_pass,
        "sensitivity_sweep":    sweep,
        # OOS quality
        "oos_data_quality":     dq_report,
        # Gate 1
        "gate1_pass":           gate1_pass,
        "overall_verdict":      overall_verdict,
        "gate1_checks":         checks,
        "gate1_checks_passed":  f"{passed}/{total}",
        # Look-ahead bias
        "look_ahead_bias_flag": False,  # signal shifted +1 business day, verified in strategy code
        # Trade log
        "trade_log":            trade_log,
        # Data quality
        "data_warnings":        data_warnings,
    }

    # ── 15. Save JSON ─────────────────────────────────────────────────────────
    os.makedirs("backtests", exist_ok=True)
    json_path = f"backtests/{STRATEGY_NAME}_{TODAY}.json"
    with open(json_path, "w") as f:
        json.dump(metrics_json, f, indent=2, default=str)
    print(f"Metrics JSON saved: {json_path}")

    # ── 16. Build Markdown Report ─────────────────────────────────────────────
    md_lines = [
        f"# H39 Equity Breadth Timer — Gate 1 Backtest Report",
        f"",
        f"**Run date:** {TODAY}  ",
        f"**Strategy:** H39 Equity Breadth Timer — % Sectors Above 200-SMA as SPY Entry Signal  ",
        f"**Asset class:** Equities (SPY)  ",
        f"**References:** QUA-314, QUA-313, QUA-311  ",
        f"",
        f"---",
        f"",
        f"## Executive Summary",
        f"",
        f"| | |",
        f"|---|---|",
        f"| **Gate 1 Verdict** | **{overall_verdict}** |",
        f"| Checks passed | {passed}/{total} |",
        f"| IS Sharpe | {fmt(is_sharpe)} ({pass_fail(is_sharpe, G1_IS_SHARPE)}) |",
        f"| OOS Sharpe | {fmt(oos_sharpe)} ({pass_fail(oos_sharpe, G1_OOS_SHARPE)}) |",
        f"| IS Max Drawdown | {pct(is_mdd)} ({pass_fail(is_mdd, G1_IS_MDD, 'above')}) |",
        f"| Walk-Forward | {wf_passes}/4 folds passed ({pass_fail(wf_passes, G1_WF_PASS)}) |",
        f"| DSR | {fmt(dsr)} ({pass_fail(dsr, G1_DSR)}) |",
        f"",
        f"---",
        f"",
        f"## Gate 1 Checklist",
        f"",
        f"| Check | Result |",
        f"|---|---|",
    ]
    for k, v in checks.items():
        md_lines.append(f"| {k} | {'✅ PASS' if v else '❌ FAIL'} |")

    md_lines += [
        f"",
        f"---",
        f"",
        f"## Primary Configuration Metrics",
        f"",
        f"**Parameters:** entry_threshold={PRIMARY_ENTRY}, exit_threshold={PRIMARY_EXIT}, sma_lookback={PRIMARY_SMA}",
        f"",
        f"| Metric | IS (2007–2021) | OOS (2022–2025) | Threshold |",
        f"|---|---|---|---|",
        f"| Sharpe Ratio | {fmt(is_sharpe)} | {fmt(oos_sharpe)} | IS>1.0, OOS>0.7 |",
        f"| Max Drawdown | {pct(is_mdd)} | {pct(oos_mdd)} | IS<20%, OOS<25% |",
        f"| Win Rate | {pct(is_winrate)} | {pct(oos_winrate)} | >50% |",
        f"| Profit Factor | {fmt(is_pf, 2)} | {fmt(oos_pf, 2)} | >1.0 |",
        f"| Trade Count | {is_trades} | {oos_trades} | ≥50 (CEO exception) |",
        f"| Total Return | {pct(is_metrics['total_return'])} | {pct(oos_metrics['total_return'])} | — |",
        f"| Total TC | ${is_metrics['total_transaction_cost']:.2f} | ${oos_metrics['total_transaction_cost']:.2f} | — |",
        f"| Post-cost Sharpe | {fmt(post_cost_sharpe)} | — | embedded |",
        f"",
        f"---",
        f"",
        f"## Statistical Rigor",
        f"",
        f"### Monte Carlo (1,000 simulations, trade PnL bootstrap)",
        f"",
        f"| | Value |",
        f"|---|---|",
        f"| MC p5 Sharpe | {fmt(mc_results['mc_p5_sharpe'])} |",
        f"| MC median Sharpe | {fmt(mc_results['mc_median_sharpe'])} |",
        f"| MC p95 Sharpe | {fmt(mc_results['mc_p95_sharpe'])} |",
        f"| MC pessimistic flag | {'⚠️ YES' if mc_results['mc_p5_sharpe'] < 0.5 else 'NO'} |",
        f"",
        f"### Bootstrap 95% CI (Block bootstrap, block=√T)",
        f"",
        f"| Metric | Lower | Upper |",
        f"|---|---|---|",
        f"| Sharpe | {fmt(ci_results['sharpe_ci_low'])} | {fmt(ci_results['sharpe_ci_high'])} |",
        f"| Max Drawdown | {pct(ci_results['mdd_ci_low'])} | {pct(ci_results['mdd_ci_high'])} |",
        f"| Win Rate | {pct(ci_results['win_rate_ci_low'])} | {pct(ci_results['win_rate_ci_high'])} |",
        f"",
        f"### Market Impact (SPY, {PARAMETERS['order_qty']} shares)",
        f"",
        f"| | Value |",
        f"|---|---|",
        f"| Market impact | {fmt(mi_results['market_impact_bps'], 2)} bps |",
        f"| Q/ADV ratio | {fmt(mi_results['order_to_adv_ratio'], 6)} |",
        f"| Liquidity constrained | {mi_results['liquidity_constrained']} |",
        f"",
        f"### Permutation Test (500 permutations)",
        f"",
        f"| | Value |",
        f"|---|---|",
        f"| p-value | {fmt(perm_results['permutation_pvalue'])} |",
        f"| Test pass (p≤0.05) | {perm_results['permutation_test_pass']} |",
        f"",
        f"---",
        f"",
        f"## Walk-Forward Results",
        f"",
        f"| Fold | IS Window | OOS Window | IS Sharpe | OOS Sharpe | Consistency | Pass |",
        f"|---|---|---|---|---|---|---|",
    ]
    for r in wf_results:
        cons = fmt(r.get("consistency")) if r.get("consistency") is not None else "N/A"
        md_lines.append(
            f"| {r['fold']} | {r['is_start']}–{r['is_end']} | {r['oos_start']}–{r['oos_end']} "
            f"| {fmt(r.get('is_sharpe'))} | {fmt(r.get('oos_sharpe'))} | {cons} | {'✅' if r.get('fold_pass') else '❌'} |"
        )

    md_lines += [
        f"",
        f"**WF Sharpe std:** {fmt(wf_var['wf_sharpe_std'])} | **WF Sharpe min:** {fmt(wf_var['wf_sharpe_min'])}",
        f"",
        f"{'⚠️ wf_sharpe_min < 0 — at least one losing OOS window' if wf_var['wf_sharpe_min'] is not None and wf_var['wf_sharpe_min'] < 0 else ''}",
        f"",
        f"---",
        f"",
        f"## Parameter Sensitivity",
        f"",
        f"| entry | exit | sma | IS Sharpe | IS MDD | Win Rate | Trades |",
        f"|---|---|---|---|---|---|---|",
    ]
    for row in sweep:
        if "error" in row:
            md_lines.append(f"| {row['entry_threshold']} | {row['exit_threshold']} | {row['sma_lookback']} | ERROR | — | — | — |")
        else:
            md_lines.append(
                f"| {row['entry_threshold']} | {row['exit_threshold']} | {row['sma_lookback']} "
                f"| {fmt(row.get('is_sharpe'))} | {pct(row.get('is_mdd'))} "
                f"| {pct(row.get('win_rate'))} | {row.get('trade_count')} |"
            )

    primary_sharpe_str = fmt(is_sharpe)
    md_lines += [
        f"",
        f"**Primary Sharpe:** {primary_sharpe_str}  ",
        f"**Sensitivity pass (±30% threshold):** {'✅ PASS' if sens_pass else '❌ FAIL'}",
        f"",
        f"---",
        f"",
        f"## OOS Data Quality",
        f"",
        f"| | |",
        f"|---|---|",
        f"| Recommendation | **{dq_report['recommendation']}** |",
        f"| Row coverage | {dq_report['row_coverage_pct']}% |",
        f"| NaN critical fields | {dq_report['nan_critical_fields'] or 'None'} |",
        f"| Advisory NaN fields | {dq_report['advisory_nan_fields'] or 'None'} |",
        f"",
        f"---",
        f"",
        f"## Trade Log (IS, up to 30 trades shown)",
        f"",
        f"| Trade | Entry Date | Entry Price | Exit Date | Exit Price | PnL |",
        f"|---|---|---|---|---|---|",
    ]
    for t in trade_log[:30]:
        md_lines.append(
            f"| {t['trade_id']} | {t['entry_date']} | {t['entry_price']} "
            f"| {t['exit_date'] or '—'} | {t['exit_price'] or '—'} "
            f"| ${t['pnl']:,.2f} |" if t['pnl'] is not None
            else f"| {t['trade_id']} | {t['entry_date']} | {t['entry_price']} | — | — | — |"
        )

    if len(trade_log) > 30:
        md_lines.append(f"| ... | *{len(trade_log) - 30} more trades in JSON* | | | | |")

    md_lines += [
        f"",
        f"---",
        f"",
        f"## Data Warnings",
        f"",
    ]
    if data_warnings:
        for w in data_warnings:
            md_lines.append(f"- {w}")
    else:
        md_lines.append("No data warnings.")

    md_lines += [
        f"",
        f"---",
        f"",
        f"## IS Shortfall Tracking Schema",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| strategy_name | {STRATEGY_NAME} |",
        f"| entry_backtest_price | {fmt(trade_log[0]['entry_price'] if trade_log else None)} |",
        f"| backtest_sharpe_is | {fmt(is_sharpe)} |",
        f"| backtest_mdd_is | {pct(is_mdd)} |",
        f"| gate1_run_date | {TODAY} |",
        f"| gate1_verdict | {overall_verdict} |",
        f"",
        f"---",
        f"",
        f"*Generated by Backtest Runner Agent (QUA-314) on {TODAY}*",
    ]

    md_path = "backtests/h39_equity_breadth_timer_gate1_report.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"Markdown report saved: {md_path}")

    return metrics_json, overall_verdict, passed, total, checks


if __name__ == "__main__":
    try:
        metrics, verdict, passed, total, checks = main()
        print(f"\nDone. Verdict: {verdict} ({passed}/{total} checks)")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
