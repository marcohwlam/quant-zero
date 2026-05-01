"""
Gate 1 Backtest Runner: H41 Turn of Quarter Window Dressing — SPY
Engineering Director | QUA-320 | 2026-05-01

Full Gate 1 evaluation:
- IS backtest (1993-01-01 to 2017-12-31)
- OOS backtest (2018-01-01 to 2025-12-31)
- 4 walk-forward folds (expanding IS window, chronological)
- Parameter sensitivity sweep (5 combinations)
- Monte Carlo Sharpe (1000 simulations, trade PnL bootstrap)
- Block bootstrap 95% CI for Sharpe, MDD, win rate
- Permutation p-value for alpha (500 permutations, random window placement)
- Walk-forward variance metrics
- Gate 1 verdict JSON + markdown report

Outputs:
- backtests/H41_TurnOfQuarterWindowDressing_<date>.json
- backtests/h41_turn_of_quarter_gate1_report.md

Ref: QUA-320, QUA-323, QUA-316 (pre-flight), QUA-308 (QC discovery)
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

from strategies.h41_turn_of_quarter_window_dressing import (
    run_backtest,
    PARAMETERS,
    load_spy_data,
)

# ── Constants ──────────────────────────────────────────────────────────────────
IS_START  = "1993-01-01"
IS_END    = "2017-12-31"
OOS_START = "2018-01-01"
OOS_END   = "2025-12-31"
TODAY = date.today().strftime("%Y-%m-%d")
STRATEGY_NAME = "H41_TurnOfQuarterWindowDressing"

# Gate 1 thresholds
G1_IS_SHARPE  = 1.0
G1_OOS_SHARPE = 0.7
G1_MDD        = -0.20   # max drawdown must be better (less negative) than -20%
G1_MIN_TRADES = 100
G1_WF_PASS    = 3       # of 4 folds

TRADING_DAYS_PER_YEAR = 252

# Parameter sensitivity grid (primary + 4 variants from QUA-320)
PARAM_GRID = [
    # primary
    {"entry_days_before_quarter_end": 3, "hold_into_new_quarter_days": 2,
     "trend_filter_ma": 200, "vix_circuit_breaker": 35},
    # entry variant
    {"entry_days_before_quarter_end": 2, "hold_into_new_quarter_days": 2,
     "trend_filter_ma": 200, "vix_circuit_breaker": 35},
    # entry variant
    {"entry_days_before_quarter_end": 4, "hold_into_new_quarter_days": 2,
     "trend_filter_ma": 200, "vix_circuit_breaker": 35},
    # hold variant
    {"entry_days_before_quarter_end": 3, "hold_into_new_quarter_days": 1,
     "trend_filter_ma": 200, "vix_circuit_breaker": 35},
    # trend variant
    {"entry_days_before_quarter_end": 3, "hold_into_new_quarter_days": 2,
     "trend_filter_ma": 150, "vix_circuit_breaker": 35},
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def pass_fail(value, threshold, direction="above"):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    if direction == "above":
        return "PASS" if value > threshold else "FAIL"
    else:
        return "PASS" if value < threshold else "FAIL"


def pct(v):
    if v is None or (isinstance(value := v, float) and np.isnan(value)):
        return "N/A"
    return f"{v:.2%}"


def fmt(v, decimals=4):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.{decimals}f}"


def _build_params(overrides: dict) -> dict:
    """Merge override keys onto a copy of the canonical PARAMETERS dict."""
    p = PARAMETERS.copy()
    p.update(overrides)
    return p


def _daily_returns_from_equity(equity_curve: pd.Series) -> np.ndarray:
    return equity_curve.pct_change().fillna(0).values


# ── Statistical Rigor Pipeline ─────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
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
    spy_prices: pd.Series,
    n_windows: int,
    hold_days: int,
    observed_sharpe: float,
    n_perms: int = 500,
) -> dict:
    """
    Null: randomly place N holding windows of length hold_days in the IS price series.
    Compute per-permutation Sharpe from the window returns.
    p-value = fraction of permuted Sharpes >= observed.
    """
    prices = spy_prices.values
    n = len(prices)
    max_start = n - hold_days - 1

    if n_windows == 0 or max_start <= 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    permuted_sharpes = []
    for _ in range(n_perms):
        idxs = np.random.choice(max_start, size=n_windows, replace=False)
        window_returns = []
        for idx in idxs:
            exit_idx = min(idx + hold_days, n - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
            window_returns.append(ret)
        arr = np.array(window_returns)
        if len(arr) > 1:
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR / hold_days)
        else:
            s = 0.0
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue":    p_value,
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    arr = np.array([s for s in wf_oos_sharpes if s is not None and not np.isnan(s)])
    if len(arr) == 0:
        return {"wf_sharpe_std": np.nan, "wf_sharpe_min": np.nan}
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


def compute_dsr(daily_returns: np.ndarray, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)."""
    returns = daily_returns[~np.isnan(daily_returns)]
    T = len(returns)
    if T < 10:
        return np.nan
    sr = returns.mean() / (returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    from scipy import stats
    import math
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))
    if n_trials <= 1:
        emax_sr = 0.0
    else:
        emax_sr = (1 - 0.5772156649 / math.log(n_trials)) * math.sqrt(2 * math.log(n_trials))
    sigma_sr = math.sqrt((1 + 0.5 * sr**2 - skew * sr + (kurt / 4) * sr**2) / (T - 1))
    dsr = (sr - emax_sr) / sigma_sr if sigma_sr > 0 else np.nan
    return float(dsr)


def compute_market_impact(order_qty: float, start: str, end: str) -> dict:
    try:
        prices, volume = load_spy_data(start=start, end=end)
        adv = float(volume.rolling(20).mean().iloc[-1])
        sigma = float(prices.pct_change().std())
        k = 0.1
        impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
        impact_bps = impact_pct * 10000
        liquidity_constrained = bool(order_qty > 0.01 * adv)
        return {
            "market_impact_bps":     float(impact_bps),
            "liquidity_constrained": liquidity_constrained,
            "order_to_adv_ratio":    float(order_qty / (adv + 1e-8)),
        }
    except Exception as e:
        print(f"[WARN] market impact calc failed: {e}")
        return {"market_impact_bps": np.nan, "liquidity_constrained": False,
                "order_to_adv_ratio": np.nan}


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(n_folds: int = 4) -> list:
    """
    4-fold expanding walk-forward over IS period (1993-2017).
    Each fold has an approximately equal-length OOS window.
    """
    from dateutil.relativedelta import relativedelta

    total_start  = pd.Timestamp(IS_START)
    total_end    = pd.Timestamp(IS_END)
    total_months = (total_end.year - total_start.year) * 12 + (total_end.month - total_start.month)
    oos_months   = total_months // (n_folds + 1)  # ~60 months (~5 yr) per OOS window

    primary_params = _build_params(PARAM_GRID[0])
    fold_results = []

    for fold in range(n_folds):
        oos_start  = total_start + relativedelta(months=oos_months * (fold + 1))
        oos_end    = oos_start + relativedelta(months=oos_months) - pd.DateOffset(days=1)
        if oos_end > total_end:
            oos_end = total_end
        is_end_fold = oos_start - pd.DateOffset(days=1)

        is_start_str  = total_start.strftime("%Y-%m-%d")
        is_end_str    = is_end_fold.strftime("%Y-%m-%d")
        oos_start_str = oos_start.strftime("%Y-%m-%d")
        oos_end_str   = oos_end.strftime("%Y-%m-%d")

        print(f"  Fold {fold+1}: IS {is_start_str}→{is_end_str} | OOS {oos_start_str}→{oos_end_str}")

        try:
            is_res  = run_backtest(primary_params, start=is_start_str,  end=is_end_str)
            oos_res = run_backtest(primary_params, start=oos_start_str, end=oos_end_str)

            is_sharpe  = is_res["metrics"]["sharpe_ratio"]
            oos_sharpe = oos_res["metrics"]["sharpe_ratio"]

            consistency = np.nan
            fold_pass   = False
            if is_sharpe and is_sharpe != 0 and oos_sharpe is not None:
                consistency = abs(oos_sharpe - is_sharpe) / (abs(is_sharpe) + 1e-8)
                fold_pass   = oos_sharpe > G1_OOS_SHARPE and consistency <= 0.50

            fold_results.append({
                "fold":        fold + 1,
                "is_start":    is_start_str,
                "is_end":      is_end_str,
                "oos_start":   oos_start_str,
                "oos_end":     oos_end_str,
                "is_sharpe":   round(is_sharpe, 4) if is_sharpe is not None else None,
                "oos_sharpe":  round(oos_sharpe, 4) if oos_sharpe is not None else None,
                "is_mdd":      round(is_res["metrics"]["max_drawdown"], 4),
                "oos_mdd":     round(oos_res["metrics"]["max_drawdown"], 4),
                "is_trades":   is_res["metrics"]["total_trades"],
                "oos_trades":  oos_res["metrics"]["total_trades"],
                "consistency": round(consistency, 4) if not np.isnan(consistency) else None,
                "fold_pass":   fold_pass,
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
        label = (f"entry={cfg['entry_days_before_quarter_end']},"
                 f"hold={cfg['hold_into_new_quarter_days']},"
                 f"ma={cfg['trend_filter_ma']},"
                 f"vix={cfg['vix_circuit_breaker']}")
        print(f"  Sensitivity: {label}")
        try:
            p = _build_params(cfg)
            res = run_backtest(p, start=IS_START, end=IS_END)
            m = res["metrics"]
            sweep_results.append({
                **cfg,
                "is_sharpe":   round(m["sharpe_ratio"], 4),
                "is_mdd":      round(m["max_drawdown"], 4),
                "win_rate":    round(m["win_rate"], 4),
                "trade_count": m["total_trades"],
            })
        except Exception as e:
            sweep_results.append({**cfg, "error": str(e)})
    return sweep_results


def sensitivity_pass(sweep_results: list, primary_sharpe: float) -> bool:
    """Pass if ≥3/5 configs within ±50% of primary Sharpe (lenient for seasonal strategies)."""
    if primary_sharpe is None or primary_sharpe == 0:
        return False
    passing = 0
    total = 0
    for row in sweep_results:
        if "error" in row:
            continue
        s = row.get("is_sharpe")
        if s is None:
            continue
        total += 1
        if abs(s - primary_sharpe) / (abs(primary_sharpe) + 1e-8) <= 0.50:
            passing += 1
    return total > 0 and passing >= (total * 0.6)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    warnings.filterwarnings("ignore")
    np.random.seed(42)

    print("=" * 70)
    print("H41 TURN OF QUARTER WINDOW DRESSING — GATE 1 BACKTEST RUNNER")
    print("=" * 70)
    print(f"IS window:  {IS_START} → {IS_END}")
    print(f"OOS window: {OOS_START} → {OOS_END}")
    print(f"Primary params: entry_days=3, hold_days=2, ma=200, vix_cb=35")
    print(f"Run date: {TODAY}")
    print()

    primary_params = _build_params(PARAM_GRID[0])

    # ── 1. IS Backtest ─────────────────────────────────────────────────────────
    print("Step 1: IS backtest (1993–2017)...")
    is_result = run_backtest(primary_params, start=IS_START, end=IS_END)
    is_metrics   = is_result["metrics"]
    is_trade_log = is_result["trade_log"]
    is_equity    = is_result["equity_curve"]
    is_dq        = is_result["data_quality"]

    is_sharpe    = is_metrics["sharpe_ratio"]
    is_mdd       = is_metrics["max_drawdown"]
    is_trades    = is_metrics["total_trades"]
    is_winrate   = is_metrics["win_rate"]
    is_pf        = is_metrics["profit_factor"]
    is_ann_ret   = is_metrics["annualized_return"]
    is_lc        = is_metrics["liquidity_constrained_trades"]

    print(f"  IS Sharpe={fmt(is_sharpe)}  MDD={pct(is_mdd)}  "
          f"Trades={is_trades}  WinRate={pct(is_winrate)}  PF={fmt(is_pf, 2)}")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────────
    print("Step 2: OOS backtest (2018–2025)...")
    oos_result = run_backtest(primary_params, start=OOS_START, end=OOS_END)
    oos_metrics   = oos_result["metrics"]
    oos_trade_log = oos_result["trade_log"]
    oos_equity    = oos_result["equity_curve"]

    oos_sharpe  = oos_metrics["sharpe_ratio"]
    oos_mdd     = oos_metrics["max_drawdown"]
    oos_trades  = oos_metrics["total_trades"]
    oos_winrate = oos_metrics["win_rate"]
    oos_pf      = oos_metrics["profit_factor"]
    oos_ann_ret = oos_metrics["annualized_return"]

    print(f"  OOS Sharpe={fmt(oos_sharpe)}  MDD={pct(oos_mdd)}  "
          f"Trades={oos_trades}  WinRate={pct(oos_winrate)}  PF={fmt(oos_pf, 2)}")

    # ── 3. DSR ────────────────────────────────────────────────────────────────
    print("Step 3: DSR calculation...")
    n_trials = len(PARAM_GRID) * 2
    is_daily_returns = _daily_returns_from_equity(is_equity)
    dsr = compute_dsr(is_daily_returns, n_trials)
    print(f"  DSR={fmt(dsr)}")

    # ── 4. Walk-Forward ────────────────────────────────────────────────────────
    print("Step 4: Walk-forward analysis (4 folds)...")
    wf_results = run_walk_forward(n_folds=4)
    wf_passes      = sum(1 for r in wf_results if r.get("fold_pass", False))
    wf_oos_sharpes = [r.get("oos_sharpe") for r in wf_results]
    wf_pass        = wf_passes >= G1_WF_PASS
    print(f"  Walk-forward: {wf_passes}/4 folds passed")
    for r in wf_results:
        print(f"    Fold {r['fold']}: IS={fmt(r.get('is_sharpe'))} "
              f"OOS={fmt(r.get('oos_sharpe'))} "
              f"trades_oos={r.get('oos_trades','?')} pass={r.get('fold_pass')}")

    wf_var = walk_forward_variance(wf_oos_sharpes)
    print(f"  WF variance: std={fmt(wf_var['wf_sharpe_std'])} "
          f"min={fmt(wf_var['wf_sharpe_min'])}")

    # ── 5. Monte Carlo ────────────────────────────────────────────────────────
    print("Step 5: Monte Carlo Sharpe (1000 sims)...")
    trade_pnls = np.array([t["pnl"] for t in is_trade_log if t.get("pnl") is not None])
    if len(trade_pnls) >= 2:
        mc_results = monte_carlo_sharpe(trade_pnls, n_sims=1000)
    else:
        mc_results = {"mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan}
    print(f"  MC p5={fmt(mc_results['mc_p5_sharpe'])} "
          f"median={fmt(mc_results['mc_median_sharpe'])} "
          f"p95={fmt(mc_results['mc_p95_sharpe'])}")

    # ── 6. Block Bootstrap CI ─────────────────────────────────────────────────
    print("Step 6: Block bootstrap CI...")
    if len(is_daily_returns) >= 10:
        ci_results = block_bootstrap_ci(is_daily_returns, n_boots=1000)
    else:
        ci_results = {k: np.nan for k in [
            "sharpe_ci_low", "sharpe_ci_high",
            "mdd_ci_low", "mdd_ci_high",
            "win_rate_ci_low", "win_rate_ci_high",
        ]}
    print(f"  Sharpe 95% CI: [{fmt(ci_results['sharpe_ci_low'])}, "
          f"{fmt(ci_results['sharpe_ci_high'])}]")

    # ── 7. Market Impact ─────────────────────────────────────────────────────
    print("Step 7: Market impact (SPY, 100 shares)...")
    mi_results = compute_market_impact(primary_params["order_qty"], IS_START, IS_END)
    print(f"  Market impact: {fmt(mi_results['market_impact_bps'], 2)} bps  "
          f"Q/ADV={fmt(mi_results['order_to_adv_ratio'], 6)}  "
          f"liquidity_constrained={mi_results['liquidity_constrained']}")

    # ── 8. Permutation Test ──────────────────────────────────────────────────
    print("Step 8: Permutation test (500 permutations)...")
    try:
        spy_prices_is, _ = load_spy_data(start=IS_START, end=IS_END)
        hold_days = (primary_params["entry_days_before_quarter_end"] +
                     primary_params["hold_into_new_quarter_days"])
        perm_results = permutation_test_alpha(
            spy_prices_is, is_trades, hold_days,
            is_sharpe if is_sharpe is not None else 0.0,
            n_perms=500,
        )
    except Exception as e:
        print(f"  [WARN] Permutation test failed: {e}")
        perm_results = {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    print(f"  p-value={fmt(perm_results['permutation_pvalue'])} "
          f"pass={perm_results['permutation_test_pass']}")

    # ── 9. Sensitivity Sweep ─────────────────────────────────────────────────
    print("Step 9: Parameter sensitivity sweep...")
    sweep = run_sensitivity_sweep()
    sens_pass = sensitivity_pass(sweep, is_sharpe)
    print(f"  Sensitivity pass: {sens_pass}")

    # ── 10. Gate 1 Verdict ────────────────────────────────────────────────────
    mc_p5_ok = (not np.isnan(mc_results["mc_p5_sharpe"]) and
                mc_results["mc_p5_sharpe"] >= 0.5)

    checks = {
        "IS Sharpe > 1.0":         pass_fail(is_sharpe, G1_IS_SHARPE) == "PASS",
        "OOS Sharpe > 0.7":        pass_fail(oos_sharpe, G1_OOS_SHARPE) == "PASS",
        "IS MDD < 20%":            is_mdd > G1_MDD if is_mdd is not None else False,
        "OOS MDD < 20%":           oos_mdd > G1_MDD if oos_mdd is not None else False,
        "Win Rate > 50%":          pass_fail(is_winrate, 0.50) == "PASS",
        "DSR > 0":                 pass_fail(dsr, 0.0) == "PASS",
        "WF >= 3/4 folds":         wf_pass,
        "Trade count >= 100 (IS)": is_trades >= G1_MIN_TRADES,
        "Sensitivity pass":        sens_pass,
        "Permutation p <= 0.05":   perm_results["permutation_test_pass"],
        "MC p5 Sharpe >= 0.5":     mc_p5_ok,
    }

    passed = sum(1 for v in checks.values() if v)
    total  = len(checks)
    n_critical_fail = sum(
        1 for k, v in checks.items()
        if not v and k in [
            "IS Sharpe > 1.0", "OOS Sharpe > 0.7",
            "IS MDD < 20%", "WF >= 3/4 folds",
        ]
    )

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

    # ── 11. Build JSON Output ─────────────────────────────────────────────────
    # Serialize trade log (dates → strings)
    def _serialize_trade(t: dict) -> dict:
        out = {}
        for k, v in t.items():
            if isinstance(v, pd.Timestamp):
                out[k] = v.strftime("%Y-%m-%d")
            elif hasattr(v, "item"):      # numpy scalar
                out[k] = v.item()
            else:
                out[k] = v
        return out

    is_trade_log_json  = [_serialize_trade(t) for t in is_trade_log]
    oos_trade_log_json = [_serialize_trade(t) for t in oos_trade_log]

    metrics_json = {
        "strategy_name":   STRATEGY_NAME,
        "date":            TODAY,
        "asset_class":     "equities",
        # Core metrics
        "is_sharpe":       round(is_sharpe, 4) if is_sharpe is not None else None,
        "oos_sharpe":      round(oos_sharpe, 4) if oos_sharpe is not None else None,
        "is_max_drawdown": round(is_mdd, 4),
        "oos_max_drawdown": round(oos_mdd, 4),
        "win_rate":        round(is_winrate, 4),
        "oos_win_rate":    round(oos_winrate, 4),
        "profit_factor":   round(is_pf, 4) if is_pf is not None and not (isinstance(is_pf, float) and np.isnan(is_pf)) else None,
        "oos_profit_factor": round(oos_pf, 4) if oos_pf is not None and not (isinstance(oos_pf, float) and np.isnan(oos_pf)) else None,
        "trade_count":     is_trades,
        "oos_trade_count": oos_trades,
        "is_annualized_return":  round(is_ann_ret, 4),
        "oos_annualized_return": round(oos_ann_ret, 4),
        "is_liquidity_constrained_trades": is_lc,
        "dsr":             round(dsr, 4) if dsr is not None and not np.isnan(dsr) else None,
        # Walk-forward
        "wf_windows_passed":  wf_passes,
        "wf_windows_total":   4,
        "wf_fold_results":    wf_results,
        "wf_sharpe_std":      round(wf_var["wf_sharpe_std"], 4) if not np.isnan(wf_var["wf_sharpe_std"]) else None,
        "wf_sharpe_min":      round(wf_var["wf_sharpe_min"], 4) if not np.isnan(wf_var["wf_sharpe_min"]) else None,
        # Statistical rigor
        "mc_p5_sharpe":       round(mc_results["mc_p5_sharpe"], 4) if not np.isnan(mc_results["mc_p5_sharpe"]) else None,
        "mc_median_sharpe":   round(mc_results["mc_median_sharpe"], 4) if not np.isnan(mc_results["mc_median_sharpe"]) else None,
        "mc_p95_sharpe":      round(mc_results["mc_p95_sharpe"], 4) if not np.isnan(mc_results["mc_p95_sharpe"]) else None,
        "sharpe_ci_low":      round(ci_results["sharpe_ci_low"], 4) if not np.isnan(ci_results["sharpe_ci_low"]) else None,
        "sharpe_ci_high":     round(ci_results["sharpe_ci_high"], 4) if not np.isnan(ci_results["sharpe_ci_high"]) else None,
        "mdd_ci_low":         round(ci_results["mdd_ci_low"], 4) if not np.isnan(ci_results["mdd_ci_low"]) else None,
        "mdd_ci_high":        round(ci_results["mdd_ci_high"], 4) if not np.isnan(ci_results["mdd_ci_high"]) else None,
        "win_rate_ci_low":    round(ci_results["win_rate_ci_low"], 4) if not np.isnan(ci_results["win_rate_ci_low"]) else None,
        "win_rate_ci_high":   round(ci_results["win_rate_ci_high"], 4) if not np.isnan(ci_results["win_rate_ci_high"]) else None,
        # Market impact
        "market_impact_bps":    round(mi_results["market_impact_bps"], 4) if not np.isnan(mi_results["market_impact_bps"]) else None,
        "liquidity_constrained": mi_results["liquidity_constrained"],
        "order_to_adv_ratio":   mi_results["order_to_adv_ratio"],
        # Permutation
        "permutation_pvalue":    round(perm_results["permutation_pvalue"], 4),
        "permutation_test_pass": perm_results["permutation_test_pass"],
        # Sensitivity
        "sensitivity_pass":   sens_pass,
        "sensitivity_sweep":  sweep,
        # Gate 1
        "gate1_pass":         gate1_pass,
        "overall_verdict":    overall_verdict,
        "gate1_checks":       {k: bool(v) for k, v in checks.items()},
        "gate1_checks_passed": f"{passed}/{total}",
        # Data quality
        "data_quality_is":    is_dq,
        # Look-ahead bias
        "look_ahead_bias_flag": False,  # position shifted +1 day via shift(1) in equity curve
        # Trade logs
        "is_trade_log":  is_trade_log_json,
        "oos_trade_log": oos_trade_log_json,
    }

    # ── 12. Save JSON ─────────────────────────────────────────────────────────
    os.makedirs("backtests", exist_ok=True)
    json_path = f"backtests/{STRATEGY_NAME}_{TODAY}.json"
    with open(json_path, "w") as f:
        json.dump(metrics_json, f, indent=2, default=str)
    print(f"Metrics JSON saved: {json_path}")

    # ── 13. Markdown Report ───────────────────────────────────────────────────
    mc_flag = "⚠️ YES" if not np.isnan(mc_results["mc_p5_sharpe"]) and mc_results["mc_p5_sharpe"] < 0.5 else "NO"
    wf_min_flag = (f"⚠️ wf_sharpe_min < 0 — at least one losing OOS fold"
                   if wf_var["wf_sharpe_min"] is not None and not np.isnan(wf_var["wf_sharpe_min"])
                   and wf_var["wf_sharpe_min"] < 0 else "")

    md_lines = [
        f"# H41 Turn of Quarter Window Dressing — Gate 1 Backtest Report",
        f"",
        f"**Run date:** {TODAY}  ",
        f"**Strategy:** H41 Turn of Quarter Window Dressing (SPY)  ",
        f"**Asset class:** Equities (SPY ETF)  ",
        f"**References:** [QUA-320](/QUA/issues/QUA-320), [QUA-323](/QUA/issues/QUA-323), [QUA-316](/QUA/issues/QUA-316), [QUA-308](/QUA/issues/QUA-308)  ",
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
        f"| IS Max Drawdown | {pct(is_mdd)} ({'PASS' if is_mdd > G1_MDD else 'FAIL'}) |",
        f"| Walk-Forward | {wf_passes}/4 folds passed ({'PASS' if wf_pass else 'FAIL'}) |",
        f"| Trade Count (IS) | {is_trades} ({'PASS' if is_trades >= G1_MIN_TRADES else 'FAIL'}) |",
        f"| Permutation p-value | {fmt(perm_results['permutation_pvalue'])} ({'PASS' if perm_results['permutation_test_pass'] else 'FAIL'}) |",
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
        f"**Parameters:** entry_days=3, hold_days=2, trend_filter_ma=200, vix_circuit_breaker=35",
        f"",
        f"| Metric | IS (1993–2017) | OOS (2018–2025) | Threshold |",
        f"|---|---|---|---|",
        f"| Sharpe Ratio | {fmt(is_sharpe)} | {fmt(oos_sharpe)} | IS>1.0, OOS>0.7 |",
        f"| Max Drawdown | {pct(is_mdd)} | {pct(oos_mdd)} | <20% |",
        f"| Win Rate | {pct(is_winrate)} | {pct(oos_winrate)} | >50% |",
        f"| Profit Factor | {fmt(is_pf, 2)} | {fmt(oos_pf, 2)} | >1.0 |",
        f"| Trade Count | {is_trades} | {oos_trades} | IS≥100 |",
        f"| Annualized Return | {pct(is_ann_ret)} | {pct(oos_ann_ret)} | — |",
        f"| Liquidity Constrained | {is_lc} | — | — |",
        f"| DSR | {fmt(dsr)} | — | >0 |",
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
        f"| MC pessimistic flag | {mc_flag} |",
        f"",
        f"### Bootstrap 95% CI (Block bootstrap, block=√T)",
        f"",
        f"| Metric | Lower | Upper |",
        f"|---|---|---|",
        f"| Sharpe | {fmt(ci_results['sharpe_ci_low'])} | {fmt(ci_results['sharpe_ci_high'])} |",
        f"| Max Drawdown | {pct(ci_results['mdd_ci_low'])} | {pct(ci_results['mdd_ci_high'])} |",
        f"| Win Rate | {pct(ci_results['win_rate_ci_low'])} | {pct(ci_results['win_rate_ci_high'])} |",
        f"",
        f"### Market Impact (SPY, {primary_params['order_qty']} shares)",
        f"",
        f"| | Value |",
        f"|---|---|",
        f"| Market impact | {fmt(mi_results['market_impact_bps'], 2)} bps |",
        f"| Q/ADV ratio | {fmt(mi_results['order_to_adv_ratio'], 6)} |",
        f"| Liquidity constrained | {mi_results['liquidity_constrained']} |",
        f"",
        f"### Permutation Test (500 permutations, random window placement)",
        f"",
        f"| | Value |",
        f"|---|---|",
        f"| p-value | {fmt(perm_results['permutation_pvalue'])} |",
        f"| Test pass (p≤0.05) | {perm_results['permutation_test_pass']} |",
        f"",
        f"---",
        f"",
        f"## Walk-Forward Results (4 Folds, Expanding IS)",
        f"",
        f"| Fold | IS Window | OOS Window | IS Sharpe | OOS Sharpe | IS Trades | OOS Trades | Consistency | Pass |",
        f"|---|---|---|---|---|---|---|---|---|",
    ]
    for r in wf_results:
        cons = fmt(r.get("consistency")) if r.get("consistency") is not None else "N/A"
        md_lines.append(
            f"| {r['fold']} | {r['is_start']}–{r['is_end']} | {r['oos_start']}–{r['oos_end']} "
            f"| {fmt(r.get('is_sharpe'))} | {fmt(r.get('oos_sharpe'))} "
            f"| {r.get('is_trades','?')} | {r.get('oos_trades','?')} "
            f"| {cons} | {'✅' if r.get('fold_pass') else '❌'} |"
        )

    md_lines += [
        f"",
        f"**WF Sharpe std:** {fmt(wf_var['wf_sharpe_std'])} | **WF Sharpe min:** {fmt(wf_var['wf_sharpe_min'])}",
        f"",
        wf_min_flag,
        f"",
        f"---",
        f"",
        f"## Parameter Sensitivity",
        f"",
        f"| entry_days | hold_days | ma | vix_cb | IS Sharpe | IS MDD | Win Rate | Trades |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for row in sweep:
        if "error" in row:
            md_lines.append(
                f"| {row['entry_days_before_quarter_end']} "
                f"| {row['hold_into_new_quarter_days']} "
                f"| {row['trend_filter_ma']} "
                f"| {row['vix_circuit_breaker']} "
                f"| ERROR | — | — | — |"
            )
        else:
            md_lines.append(
                f"| {row['entry_days_before_quarter_end']} "
                f"| {row['hold_into_new_quarter_days']} "
                f"| {row['trend_filter_ma']} "
                f"| {row['vix_circuit_breaker']} "
                f"| {fmt(row.get('is_sharpe'))} "
                f"| {pct(row.get('is_mdd'))} "
                f"| {pct(row.get('win_rate'))} "
                f"| {row.get('trade_count')} |"
            )

    md_lines += [
        f"",
        f"**Primary Sharpe:** {fmt(is_sharpe)}  ",
        f"**Sensitivity pass (±50% threshold, 3/5 configs):** {'✅ PASS' if sens_pass else '❌ FAIL'}",
        f"",
        f"---",
        f"",
        f"## Data Quality (IS)",
        f"",
        f"| Field | Value |",
        f"|---|---|",
    ]
    for k, v in is_dq.items():
        md_lines.append(f"| {k} | {v} |")

    md_lines += [
        f"",
        f"---",
        f"",
        f"## IS Trade Log (first 30 of {len(is_trade_log_json)} trades)",
        f"",
        f"| Entry Date | Exit Date | Entry Price | Exit Price | Net Return | PnL |",
        f"|---|---|---|---|---|---|",
    ]
    for t in is_trade_log_json[:30]:
        ret_str = f"{t.get('return_pct', 0):.3%}" if isinstance(t.get('return_pct'), float) else "N/A"
        pnl_val = t.get('pnl')
        pnl_str = f"${pnl_val:,.2f}" if isinstance(pnl_val, (int, float)) else "N/A"
        md_lines.append(
            f"| {t.get('entry_date','—')} | {t.get('exit_date','—')} "
            f"| {t.get('entry_price','—')} | {t.get('exit_price','—')} "
            f"| {ret_str} | {pnl_str} |"
        )
    if len(is_trade_log_json) > 30:
        md_lines.append(f"| ... | *{len(is_trade_log_json) - 30} more trades in JSON* | | | | |")

    md_lines += [
        f"",
        f"---",
        f"",
        f"## Implementation Shortfall Tracking Schema",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| strategy_name | {STRATEGY_NAME} |",
        f"| backtest_sharpe_is | {fmt(is_sharpe)} |",
        f"| backtest_mdd_is | {pct(is_mdd)} |",
        f"| gate1_run_date | {TODAY} |",
        f"| gate1_verdict | {overall_verdict} |",
        f"",
        f"---",
        f"",
        f"*Generated by Engineering Director (QUA-320) on {TODAY}*",
        f"*Strategy: QUA-323 | Pre-flight: QUA-316 | Discovery: QUA-308*",
    ]

    md_path = "backtests/h41_turn_of_quarter_gate1_report.md"
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
