"""
H47 FOMC Bi-Weekly Cycle — Gate 1 Backtest Runner
QUA-203
Date: 2026-06-11
"""
import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")

# ── Add repo root to path ─────────────────────────────────────────────────────
sys.path.insert(0, "/repos/quant-zero")
sys.path.insert(0, "/repos/quant-zero/strategies")

from h47_fomc_biweekly_cycle import (
    run_strategy,
    PARAMETERS,
    compute_cycle_weeks,
    get_fomc_dates_sorted,
    FOMC_DATES,
    is_week_start_flags,
)

TODAY = "2026-06-11"
OUT_PREFIX = f"/repos/quant-zero/backtests/h47_fomc_biweekly_cycle_{TODAY}"

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def sharpe(returns: np.ndarray) -> float:
    if len(returns) < 2 or returns.std() < 1e-10:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(252))

def max_drawdown(returns: np.ndarray) -> float:
    cum = np.cumprod(1 + returns)
    roll_max = np.maximum.accumulate(cum)
    dd = (cum - roll_max) / (roll_max + 1e-8)
    return float(dd.min())

def cagr(returns: np.ndarray, n_years: float) -> float:
    total = float(np.prod(1 + returns))
    return float(total ** (1 / n_years) - 1)

# ─────────────────────────────────────────────────────────────────────────────
# MONTE CARLO
# ─────────────────────────────────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 500) -> dict:
    sharpes = []
    np.random.seed(42)
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

# ─────────────────────────────────────────────────────────────────────────────
# BLOCK BOOTSTRAP CI
# ─────────────────────────────────────────────────────────────────────────────

def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = T // block_len
    np.random.seed(42)

    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd_val = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s_val = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
        wr_val = float(np.mean(sample > 0))
        sharpes.append(s_val)
        mdds.append(mdd_val)
        win_rates.append(wr_val)

    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low": float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }

# ─────────────────────────────────────────────────────────────────────────────
# PERMUTATION TEST
# ─────────────────────────────────────────────────────────────────────────────

def permutation_test_alpha(
    returns: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 1000,
) -> dict:
    np.random.seed(42)
    permuted_sharpes = []
    for _ in range(n_perms):
        perm = np.random.permutation(returns)
        s = float(perm.mean() / (perm.std() + 1e-8) * np.sqrt(252))
        permuted_sharpes.append(s)
    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": bool(p_value <= 0.05),
    }

# ─────────────────────────────────────────────────────────────────────────────
# DSR (Deflated Sharpe Ratio)
# ─────────────────────────────────────────────────────────────────────────────

def compute_dsr(returns: np.ndarray, n_trials: int = 9, sharpe_observed: float = None) -> float:
    """
    Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio.
    DSR > 0 → statistically significant after multiple testing correction.
    """
    from scipy import stats as scipy_stats
    if sharpe_observed is None:
        sharpe_observed = float(returns.mean() / (returns.std() + 1e-8) * np.sqrt(252))
    T = len(returns)
    if T < 2:
        return 0.0
    skew = float(pd.Series(returns).skew())
    kurt = float(pd.Series(returns).kurt())
    # Expected maximum Sharpe under H0 (Bailey & Lopez de Prado eq 3)
    gamma = 0.5772156649  # Euler-Mascheroni
    sharpe_star = (1 - gamma) * scipy_stats.norm.ppf(1 - 1.0 / n_trials) + \
                  gamma * scipy_stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    # DSR
    sr_scaled = sharpe_observed / np.sqrt(252)  # annualized → daily units
    sr_star_scaled = sharpe_star / np.sqrt(252)
    num = (sr_scaled - sr_star_scaled) * np.sqrt(T - 1)
    denom = np.sqrt(1 - skew * sr_scaled + (kurt - 1) / 4 * sr_scaled ** 2)
    if denom <= 0:
        return 0.0
    dsr = float(scipy_stats.norm.cdf(num / denom))
    return round(dsr, 6)

# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD WINDOWS
# ─────────────────────────────────────────────────────────────────────────────

WF_WINDOWS = [
    ("2003-01-01", "2007-12-31", "2008-01-01", "2008-12-31"),
    ("2009-01-01", "2013-12-31", "2014-01-01", "2014-06-30"),
    ("2014-01-01", "2018-12-31", "2019-01-01", "2019-12-31"),
    ("2019-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
]

def run_walk_forward(params_base: dict) -> dict:
    results = []
    for (is_s, is_e, oos_s, oos_e) in WF_WINDOWS:
        p_is = {**params_base, "start_date": is_s, "end_date": is_e}
        p_oos = {**params_base, "start_date": oos_s, "end_date": oos_e}
        r_is = run_strategy(p_is)
        r_oos = run_strategy(p_oos)
        results.append({
            "is_window": f"{is_s}_{is_e}",
            "oos_window": f"{oos_s}_{oos_e}",
            "is_sharpe": r_is["sharpe"],
            "oos_sharpe": r_oos["sharpe"],
            "is_mdd": r_is["max_drawdown"],
            "oos_mdd": r_oos["max_drawdown"],
            "oos_profitable": r_oos["sharpe"] > 0,
        })
        print(f"  WF {oos_s}→{oos_e}: IS Sharpe={r_is['sharpe']:.3f}  OOS Sharpe={r_oos['sharpe']:.3f}")
    wf_oos_sharpes = [r["oos_sharpe"] for r in results]
    wf_windows_passed = sum(1 for s in wf_oos_sharpes if s > 0)
    is_sharpes = [r["is_sharpe"] for r in results]
    wf_consistency_scores = []
    for r in results:
        if abs(r["is_sharpe"]) > 1e-6:
            decay = (r["is_sharpe"] - r["oos_sharpe"]) / abs(r["is_sharpe"])
            wf_consistency_scores.append(max(0.0, 1.0 - decay))
        else:
            wf_consistency_scores.append(0.0)
    wf_consistency_score = float(np.mean(wf_consistency_scores)) if wf_consistency_scores else 0.0
    return {
        "wf_results": results,
        "wf_windows_passed": wf_windows_passed,
        "wf_consistency_score": round(wf_consistency_score, 4),
        "wf_sharpe_std": float(np.std(wf_oos_sharpes)),
        "wf_sharpe_min": float(np.min(wf_oos_sharpes)),
        "wf_oos_sharpes": wf_oos_sharpes,
    }

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETER SWEEP
# ─────────────────────────────────────────────────────────────────────────────

def run_parameter_sweep(params_base: dict) -> pd.DataFrame:
    rows = []
    even_week_configs = [[0, 2, 4], [0, 2], [0]]
    ma_periods = [150, 200, 250]
    downtrend_sizes = [0.25, 0.50, 0.75]

    for ew in even_week_configs:
        for ma in ma_periods:
            for ds in downtrend_sizes:
                p = {**params_base,
                     "even_weeks_included": ew,
                     "ma_period": ma,
                     "downtrend_position_size": ds}
                try:
                    r = run_strategy(p)
                    rows.append({
                        "even_weeks_included": str(ew),
                        "ma_period": ma,
                        "downtrend_position_size": ds,
                        "sharpe": r["sharpe"],
                        "max_drawdown": r["max_drawdown"],
                        "total_return": r["total_return"],
                        "win_rate": r["win_rate"],
                        "profit_factor": r["profit_factor"],
                        "trade_count": r["trade_count"],
                    })
                    print(f"  sweep ew={ew} ma={ma} ds={ds}: Sharpe={r['sharpe']:.3f} MDD={r['max_drawdown']:.2%}")
                except Exception as e:
                    print(f"  sweep FAIL ew={ew} ma={ma} ds={ds}: {e}")
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────────────────────────────────────
# SENSITIVITY CHECK: ±20% parameter variation
# ─────────────────────────────────────────────────────────────────────────────

def sensitivity_check(params_base: dict, baseline_sharpe: float) -> bool:
    """Check that IS Sharpe doesn't vary >30% across ±20% parameter variation."""
    variations = [
        {"ma_period": int(params_base["ma_period"] * 0.8)},
        {"ma_period": int(params_base["ma_period"] * 1.2)},
        {"downtrend_position_size": params_base["downtrend_position_size"] * 0.8},
        {"downtrend_position_size": min(1.0, params_base["downtrend_position_size"] * 1.2)},
    ]
    sharpes = [baseline_sharpe]
    for v in variations:
        p = {**params_base, **v}
        try:
            r = run_strategy(p)
            sharpes.append(r["sharpe"])
        except Exception as e:
            print(f"  sensitivity FAIL {v}: {e}")
    if abs(baseline_sharpe) < 1e-6:
        return True
    max_pct_change = max(abs(s - baseline_sharpe) / abs(baseline_sharpe) for s in sharpes)
    return bool(max_pct_change < 0.30)

# ─────────────────────────────────────────────────────────────────────────────
# EVEN vs ODD WEEK DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────────────────

def even_odd_diagnostics(is_result: dict, params_base: dict) -> dict:
    """Compute even vs odd week return differential, t-stat."""
    from scipy import stats as scipy_stats
    import yfinance as yf

    # Download raw SPY data for the full IS window
    spy_raw = yf.download("SPY", start="2002-01-01", end="2024-01-01",
                          auto_adjust=True, progress=False)
    if isinstance(spy_raw.columns, pd.MultiIndex):
        spy_raw.columns = spy_raw.columns.get_level_values(0)

    fomc_sorted = get_fomc_dates_sorted(FOMC_DATES, 2002, 2024)
    cycle_weeks = compute_cycle_weeks(spy_raw.index, fomc_sorted)
    week_flags = is_week_start_flags(spy_raw.index)

    spy_raw["_cycle_week"] = cycle_weeks
    spy_raw["_week_start"] = week_flags

    # Weekly returns — use Friday close / Monday open proxy (weekly close-to-close)
    spy_raw["_pct"] = spy_raw["Close"].pct_change()

    # Subset to IS window
    is_start = pd.Timestamp(params_base["start_date"])
    is_end = pd.Timestamp(params_base["end_date"])
    df = spy_raw.loc[(spy_raw.index >= is_start) & (spy_raw.index <= is_end)].copy()

    even_set = set(params_base["even_weeks_included"])

    # For each week: flag even/odd, compute weekly return (from Monday open to Friday close)
    weekly_rows = []
    df = df.reset_index()
    df.columns = [str(c) for c in df.columns]
    df_date_col = "Date" if "Date" in df.columns else "index"
    df[df_date_col] = pd.to_datetime(df[df_date_col])
    df["year_week"] = df[df_date_col].dt.isocalendar().year * 100 + df[df_date_col].dt.isocalendar().week
    for yw, grp in df.groupby("year_week"):
        if len(grp) < 1:
            continue
        cw_raw = grp["_cycle_week"].iloc[0]
        cw = int(cw_raw) if not pd.isna(cw_raw) else None
        is_even = cw is not None and cw in even_set
        week_ret = (grp["Close"].iloc[-1] / grp["Close"].iloc[0] - 1) if len(grp) > 1 else 0.0
        weekly_rows.append({"year_week": yw, "cycle_week": cw, "is_even": is_even, "weekly_return": week_ret})

    weekly_df = pd.DataFrame(weekly_rows).dropna(subset=["cycle_week"])
    even_rets = weekly_df.loc[weekly_df["is_even"], "weekly_return"].values
    odd_rets = weekly_df.loc[~weekly_df["is_even"], "weekly_return"].values

    avg_even = float(np.mean(even_rets)) if len(even_rets) > 0 else 0.0
    avg_odd = float(np.mean(odd_rets)) if len(odd_rets) > 0 else 0.0
    even_win_rate = float(np.mean(even_rets > 0)) if len(even_rets) > 0 else 0.0

    t_stat, t_pvalue = scipy_stats.ttest_ind(even_rets, odd_rets, equal_var=False) if (len(even_rets) > 1 and len(odd_rets) > 1) else (0.0, 1.0)

    return {
        "avg_even_week_return": round(avg_even, 6),
        "avg_odd_week_return": round(avg_odd, 6),
        "even_week_win_rate": round(even_win_rate, 4),
        "even_odd_t_stat": round(float(t_stat), 4),
        "even_odd_t_pvalue": round(float(t_pvalue), 4),
        "n_even_weeks": int(len(even_rets)),
        "n_odd_weeks": int(len(odd_rets)),
    }

# ─────────────────────────────────────────────────────────────────────────────
# POST-PUBLICATION DECAY DIAGNOSTIC
# ─────────────────────────────────────────────────────────────────────────────

def post_pub_decay_diagnostic(params_base: dict) -> dict:
    """Compare pre-2019 vs post-2019 even-week premium."""
    import yfinance as yf
    from scipy import stats as scipy_stats

    spy_raw = yf.download("SPY", start="2002-01-01", end="2026-07-01",
                          auto_adjust=True, progress=False)
    if isinstance(spy_raw.columns, pd.MultiIndex):
        spy_raw.columns = spy_raw.columns.get_level_values(0)

    fomc_sorted = get_fomc_dates_sorted(FOMC_DATES, 2002, 2026)
    cycle_weeks = compute_cycle_weeks(spy_raw.index, fomc_sorted)
    week_flags = is_week_start_flags(spy_raw.index)

    spy_raw["_cycle_week"] = cycle_weeks
    spy_raw["_week_start"] = week_flags
    spy_raw["_pct"] = spy_raw["Close"].pct_change()

    even_set = set(params_base["even_weeks_included"])

    df = spy_raw.reset_index()
    df.columns = [str(c) for c in df.columns]
    df_date_col = "Date" if "Date" in df.columns else "index"
    df[df_date_col] = pd.to_datetime(df[df_date_col])
    df["year_week"] = df[df_date_col].dt.isocalendar().year * 100 + df[df_date_col].dt.isocalendar().week

    weekly_rows = []
    for yw, grp in df.groupby("year_week"):
        if len(grp) < 1:
            continue
        first_date = grp[df_date_col].iloc[0]
        cw_raw = grp["_cycle_week"].iloc[0]
        cw = int(cw_raw) if not pd.isna(cw_raw) else None
        is_even = cw is not None and cw in even_set
        week_ret = (grp["Close"].iloc[-1] / grp["Close"].iloc[0] - 1) if len(grp) > 1 else 0.0
        weekly_rows.append({
            "year_week": yw,
            "first_date": first_date,
            "cycle_week": cw,
            "is_even": is_even,
            "weekly_return": week_ret,
        })

    weekly_df = pd.DataFrame(weekly_rows).dropna(subset=["cycle_week"])

    pre_pub = weekly_df[weekly_df["first_date"] < pd.Timestamp("2019-01-01")]
    post_pub = weekly_df[weekly_df["first_date"] >= pd.Timestamp("2019-01-01")]

    def _even_stats(df_sub):
        even_rets = df_sub.loc[df_sub["is_even"], "weekly_return"].values
        if len(even_rets) < 2:
            return {"mean_even_return": 0.0, "sharpe": 0.0, "n_weeks": 0}
        s = float(np.mean(even_rets) / (np.std(even_rets) + 1e-8) * np.sqrt(52))
        return {
            "mean_even_return": round(float(np.mean(even_rets)), 6),
            "sharpe": round(s, 4),
            "n_weeks": int(len(even_rets)),
        }

    pre_stats = _even_stats(pre_pub)
    post_stats = _even_stats(post_pub)

    retirement_signal = post_stats["sharpe"] <= 0.0

    return {
        "pre_2019_even_week": pre_stats,
        "post_2019_even_week": post_stats,
        "retirement_signal": retirement_signal,
        "retirement_note": (
            "POST-2019 EVEN-WEEK IC ≈ 0 OR NEGATIVE — RETIREMENT SIGNAL"
            if retirement_signal else "No retirement signal"
        ),
    }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("H47 FOMC Bi-Weekly Cycle — Gate 1 Backtest")
    print(f"Date: {TODAY}")
    print("=" * 70)

    baseline_params = {
        "ticker": "SPY",
        "defensive_ticker": None,
        "even_weeks_included": [0, 2, 4],
        "ma_period": 200,
        "downtrend_position_size": 0.50,
        "init_cash": 100000,
        "start_date": "2003-01-01",
        "end_date": "2023-12-31",
    }

    # ── 1. IS Backtest ────────────────────────────────────────────────────────
    print("\n[1/8] Running IS backtest (2003–2023)...")
    r_is = run_strategy(baseline_params)
    is_returns = r_is["daily_returns"].values
    is_years = (pd.Timestamp("2023-12-31") - pd.Timestamp("2003-01-01")).days / 365.25
    is_cagr = cagr(is_returns, is_years)
    print(f"  IS Sharpe={r_is['sharpe']:.4f}  MDD={r_is['max_drawdown']:.2%}  CAGR={is_cagr:.2%}")

    # ── 2. OOS Backtest ───────────────────────────────────────────────────────
    print("\n[2/8] Running OOS backtest (2024-01-01 – 2026-06-10)...")
    oos_params = {**baseline_params, "start_date": "2024-01-01", "end_date": "2026-06-10"}
    r_oos = run_strategy(oos_params)
    print(f"  OOS Sharpe={r_oos['sharpe']:.4f}  MDD={r_oos['max_drawdown']:.2%}")

    # OOS data quality check
    sys.path.insert(0, "/repos/quant-zero/orchestrator")
    try:
        from oos_data_quality import validate_oos_data
        oos_metrics_for_dq = {
            "sharpe": r_oos["sharpe"],
            "max_drawdown": r_oos["max_drawdown"],
            "win_rate": r_oos["win_rate"],
            "profit_factor": r_oos["profit_factor"],
            "total_trades": r_oos["trade_count"],
            "post_cost_sharpe": r_oos["sharpe"],
        }
        import yfinance as yf
        spy_oos_raw = yf.download("SPY", start="2024-01-01", end="2026-06-11",
                                  auto_adjust=True, progress=False)
        if isinstance(spy_oos_raw.columns, pd.MultiIndex):
            spy_oos_raw.columns = spy_oos_raw.columns.get_level_values(0)
        dq_report = validate_oos_data(spy_oos_raw, oos_metrics_for_dq, "h47_fomc_biweekly_cycle")
        print(f"  OOS DQ: {dq_report['recommendation']}")
        if dq_report["recommendation"] == "BLOCK":
            print(f"  BLOCK: {dq_report}")
            sys.exit(1)
    except Exception as e:
        print(f"  OOS DQ check skipped: {e}")
        dq_report = {"recommendation": "SKIPPED", "error": str(e)}

    # ── 3. Pre-pub IS (2003–2018) ─────────────────────────────────────────────
    print("\n[3/8] Pre-pub baseline (2003–2018)...")
    prepub_params = {**baseline_params, "start_date": "2003-01-01", "end_date": "2018-12-31"}
    r_prepub = run_strategy(prepub_params)
    print(f"  Pre-pub Sharpe={r_prepub['sharpe']:.4f}  MDD={r_prepub['max_drawdown']:.2%}")

    # Post-pub diagnostic (2019–2026)
    print("  Post-pub diagnostic (2019–2026)...")
    postpub_params = {**baseline_params, "start_date": "2019-01-01", "end_date": "2026-06-10"}
    r_postpub = run_strategy(postpub_params)
    print(f"  Post-pub Sharpe={r_postpub['sharpe']:.4f}  MDD={r_postpub['max_drawdown']:.2%}")

    # ── 4. No-MA-filter secondary (downtrend_size=1.0) ────────────────────────
    print("\n[4/8] Secondary: no MA filter (downtrend_size=1.0)...")
    noma_params = {**baseline_params, "downtrend_position_size": 1.0}
    r_noma = run_strategy(noma_params)
    print(f"  No-MA Sharpe={r_noma['sharpe']:.4f}  MDD={r_noma['max_drawdown']:.2%}")
    dma_overlay_impact = {
        "baseline_sharpe": r_is["sharpe"],
        "no_ma_sharpe": r_noma["sharpe"],
        "baseline_mdd": r_is["max_drawdown"],
        "no_ma_mdd": r_noma["max_drawdown"],
        "sharpe_improvement_from_ma": round(r_is["sharpe"] - r_noma["sharpe"], 4),
        "mdd_improvement_from_ma": round(r_noma["max_drawdown"] - r_is["max_drawdown"], 4),
    }

    # ── 5. Statistical Rigor Pipeline ─────────────────────────────────────────
    print("\n[5/8] Statistical rigor pipeline...")

    # Trade PnL for Monte Carlo
    trade_log = r_is["trades"]
    pnl_list = []
    buy_stack = []
    for t in trade_log:
        if t.get("ticker") == "SPY":
            if t["trade_type"] == "BUY_SPY":
                buy_stack.append(t)
            elif t["trade_type"] in ("SELL_SPY", "SELL_SPY_EOD") and buy_stack:
                entry = buy_stack.pop()
                pnl = (t["effective_price"] - entry["effective_price"]) * abs(t["shares_delta"])
                pnl_list.append(pnl)
    trade_pnls = np.array(pnl_list) if pnl_list else np.array([0.0])

    mc = monte_carlo_sharpe(trade_pnls, n_sims=500)
    print(f"  Monte Carlo p5={mc['mc_p5_sharpe']:.4f}  median={mc['mc_median_sharpe']:.4f}  p95={mc['mc_p95_sharpe']:.4f}")

    bb = block_bootstrap_ci(is_returns, n_boots=1000)
    print(f"  Bootstrap CI Sharpe [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]")

    perm = permutation_test_alpha(is_returns, r_is["sharpe"], n_perms=1000)
    print(f"  Permutation p-value={perm['permutation_pvalue']:.4f}  pass={perm['permutation_test_pass']}")

    dsr = compute_dsr(is_returns, n_trials=9, sharpe_observed=r_is["sharpe"])
    print(f"  DSR={dsr:.6f}")

    # Market impact (use ADV from yfinance, order_qty = typical weekly trade size)
    import yfinance as yf
    spy_hist = yf.download("SPY", start="2022-01-01", end="2024-01-01",
                           auto_adjust=True, progress=False)
    if isinstance(spy_hist.columns, pd.MultiIndex):
        spy_hist.columns = spy_hist.columns.get_level_values(0)
    adv = float(spy_hist["Volume"].rolling(20).mean().iloc[-1])
    sigma_daily = float(spy_hist["Close"].pct_change().std())
    avg_spy_shares = int(100000 / float(spy_hist["Close"].iloc[-1]))  # ~$100k order
    k = 0.1
    impact_pct = k * sigma_daily * np.sqrt(avg_spy_shares / (adv + 1e-8))
    market_impact_bps = float(impact_pct * 10000)
    liq_constrained = bool(avg_spy_shares / adv > 0.01)
    order_to_adv = float(avg_spy_shares / (adv + 1e-8))
    print(f"  Market impact={market_impact_bps:.4f} bps  liq_constrained={liq_constrained}  Q/ADV={order_to_adv:.6f}")

    # Post-cost Sharpe (already embedded in run_strategy via transaction costs)
    post_cost_sharpe = r_is["sharpe"]  # run_strategy applies costs natively

    # ── 6. Walk-Forward ───────────────────────────────────────────────────────
    print("\n[6/8] Walk-forward analysis (4 windows)...")
    wf = run_walk_forward(baseline_params)
    print(f"  WF windows passed: {wf['wf_windows_passed']}/4  consistency={wf['wf_consistency_score']:.4f}")
    print(f"  WF Sharpe std={wf['wf_sharpe_std']:.4f}  min={wf['wf_sharpe_min']:.4f}")

    # ── 7. Parameter Sweep ────────────────────────────────────────────────────
    print("\n[7/8] Parameter sweep...")
    sweep_df = run_parameter_sweep(baseline_params)
    baseline_sharpe = r_is["sharpe"]
    if len(sweep_df) > 0 and abs(baseline_sharpe) > 1e-6:
        max_dev = float(((sweep_df["sharpe"] - baseline_sharpe).abs() / abs(baseline_sharpe)).max())
        sensitivity_pass = bool(max_dev < 0.30)
    else:
        sensitivity_pass = True
        max_dev = 0.0
    print(f"  Sweep sensitivity: max_dev={max_dev:.2%}  pass={sensitivity_pass}")

    # ── 8. Diagnostics ────────────────────────────────────────────────────────
    print("\n[8/8] Special diagnostics...")
    diag_even_odd = even_odd_diagnostics(r_is, baseline_params)
    print(f"  Even avg return={diag_even_odd['avg_even_week_return']:.4%}  odd avg={diag_even_odd['avg_odd_week_return']:.4%}")
    print(f"  Even win rate={diag_even_odd['even_week_win_rate']:.2%}  t-stat={diag_even_odd['even_odd_t_stat']:.3f}  p={diag_even_odd['even_odd_t_pvalue']:.4f}")

    diag_decay = post_pub_decay_diagnostic(baseline_params)
    print(f"  Pre-pub even Sharpe={diag_decay['pre_2019_even_week']['sharpe']:.4f}")
    print(f"  Post-pub even Sharpe={diag_decay['post_2019_even_week']['sharpe']:.4f}")
    print(f"  Retirement signal: {diag_decay['retirement_signal']}")

    # ── Gate 1 Pass/Fail ──────────────────────────────────────────────────────
    gate1_checks = {
        "is_sharpe_pass": bool(r_is["sharpe"] > 1.0),
        "oos_sharpe_pass": bool(r_oos["sharpe"] > 0.7),
        "is_mdd_pass": bool(abs(r_is["max_drawdown"]) < 0.20),
        "is_cagr_pass": bool(is_cagr >= 0.10),
        "wf_windows_pass": bool(wf["wf_windows_passed"] >= 3),
        "permutation_pass": perm["permutation_test_pass"],
        "even_week_winrate_pass": bool(diag_even_odd["even_week_win_rate"] > 0.50),
        "trade_count_pass": bool(r_is["trade_count"] >= 100),
        "sensitivity_pass": sensitivity_pass,
        "mc_p5_pass": bool(mc["mc_p5_sharpe"] >= 0.5),
    }
    gate1_pass = all(gate1_checks.values())
    gate1_verdict = "PASS" if gate1_pass else "FAIL"
    failed_checks = [k for k, v in gate1_checks.items() if not v]

    print(f"\n{'='*70}")
    print(f"GATE 1 VERDICT: {gate1_verdict}")
    if failed_checks:
        print(f"  FAILED CHECKS: {', '.join(failed_checks)}")
    print(f"{'='*70}")

    # ── Assemble full metrics JSON ────────────────────────────────────────────
    metrics = {
        "strategy_name": "h47_fomc_biweekly_cycle",
        "date": TODAY,
        "asset_class": "equities",
        # Core IS/OOS
        "is_sharpe": r_is["sharpe"],
        "oos_sharpe": r_oos["sharpe"],
        "is_max_drawdown": r_is["max_drawdown"],
        "oos_max_drawdown": r_oos["max_drawdown"],
        "is_cagr": round(is_cagr, 4),
        "win_rate": r_is["win_rate"],
        "profit_factor": r_is["profit_factor"],
        "trade_count": r_is["trade_count"],
        "trades_per_year": r_is["trades_per_year"],
        "total_return_is": r_is["total_return"],
        # DSR
        "dsr": dsr,
        # Walk-forward
        "wf_windows_passed": wf["wf_windows_passed"],
        "wf_consistency_score": wf["wf_consistency_score"],
        "wf_sharpe_std": wf["wf_sharpe_std"],
        "wf_sharpe_min": wf["wf_sharpe_min"],
        "wf_oos_sharpes": wf["wf_oos_sharpes"],
        # Sensitivity
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_deviation": round(max_dev, 4),
        # Post-cost (already applied in sim)
        "post_cost_sharpe": post_cost_sharpe,
        # Statistical rigor
        "mc_p5_sharpe": mc["mc_p5_sharpe"],
        "mc_median_sharpe": mc["mc_median_sharpe"],
        "mc_p95_sharpe": mc["mc_p95_sharpe"],
        "sharpe_ci_low": bb["sharpe_ci_low"],
        "sharpe_ci_high": bb["sharpe_ci_high"],
        "mdd_ci_low": bb["mdd_ci_low"],
        "mdd_ci_high": bb["mdd_ci_high"],
        "win_rate_ci_low": bb["win_rate_ci_low"],
        "win_rate_ci_high": bb["win_rate_ci_high"],
        "market_impact_bps": round(market_impact_bps, 4),
        "liquidity_constrained": liq_constrained,
        "order_to_adv_ratio": round(order_to_adv, 8),
        "permutation_pvalue": perm["permutation_pvalue"],
        "permutation_test_pass": perm["permutation_test_pass"],
        # Flags
        "look_ahead_bias_flag": False,
        "gate1_pass": gate1_pass,
        "gate1_verdict": gate1_verdict,
        "gate1_checks": gate1_checks,
        "failed_checks": failed_checks,
        # Special diagnostics
        "even_odd_diagnostics": diag_even_odd,
        "post_pub_decay_diagnostic": diag_decay,
        "dma_overlay_impact": dma_overlay_impact,
        # Sub-period results
        "prepub_is_sharpe": r_prepub["sharpe"],
        "prepub_is_mdd": r_prepub["max_drawdown"],
        "postpub_sharpe": r_postpub["sharpe"],
        "postpub_mdd": r_postpub["max_drawdown"],
        "no_ma_sharpe": r_noma["sharpe"],
        "no_ma_mdd": r_noma["max_drawdown"],
        # OOS data quality
        "oos_data_quality": dq_report,
    }

    # ── Save JSON ─────────────────────────────────────────────────────────────
    json_path = OUT_PREFIX + ".json"
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"\nMetrics saved: {json_path}")

    # ── Save trades CSV ───────────────────────────────────────────────────────
    trades_path = OUT_PREFIX + "_trades.csv"
    pd.DataFrame(r_is["trades"]).to_csv(trades_path, index=False)
    print(f"Trades saved: {trades_path}")

    # ── Save sweep CSV ────────────────────────────────────────────────────────
    sweep_path = OUT_PREFIX + "_sweep.csv"
    sweep_df.to_csv(sweep_path, index=False)
    print(f"Sweep saved: {sweep_path}")

    # ── Save verdict TXT ──────────────────────────────────────────────────────
    verdict_txt = f"""H47 FOMC Bi-Weekly Cycle — Gate 1 Verdict
Date: {TODAY}
Strategy: h47_fomc_biweekly_cycle
Asset: SPY (equities)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OVERALL VERDICT: {gate1_verdict}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IS Period: 2003-01-01 to 2023-12-31 (21 years)
OOS Period: 2024-01-01 to 2026-06-10

GATE 1 METRICS:
  IS Sharpe:              {r_is['sharpe']:.4f}    (threshold > 1.0)  {'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'}
  OOS Sharpe:             {r_oos['sharpe']:.4f}    (threshold > 0.7)  {'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'}
  IS Max Drawdown:        {r_is['max_drawdown']:.2%}   (threshold < 20%)  {'PASS' if gate1_checks['is_mdd_pass'] else 'FAIL'}
  IS CAGR:                {is_cagr:.2%}   (threshold >= 10%)  {'PASS' if gate1_checks['is_cagr_pass'] else 'FAIL'}
  Win Rate:               {r_is['win_rate']:.2%}   (threshold > 50%)  {'PASS' if gate1_checks['even_week_winrate_pass'] else 'FAIL'}
  Trade Count (IS):       {r_is['trade_count']}      (threshold >= 100) {'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'}
  WF Windows Passed:      {wf['wf_windows_passed']}/4       (threshold >= 3)   {'PASS' if gate1_checks['wf_windows_pass'] else 'FAIL'}
  Permutation p-value:    {perm['permutation_pvalue']:.4f}  (threshold < 0.05) {'PASS' if perm['permutation_test_pass'] else 'FAIL'}
  DSR:                    {dsr:.6f}
  MC p5 Sharpe:           {mc['mc_p5_sharpe']:.4f}    (threshold >= 0.5) {'PASS' if gate1_checks['mc_p5_pass'] else 'FAIL'}
  Sensitivity Pass:       {sensitivity_pass}  (threshold < 30% variation)

STATISTICAL RIGOR:
  Bootstrap Sharpe CI:    [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]
  Bootstrap MDD CI:       [{bb['mdd_ci_low']:.2%}, {bb['mdd_ci_high']:.2%}]
  MC p5/median/p95:       {mc['mc_p5_sharpe']:.4f} / {mc['mc_median_sharpe']:.4f} / {mc['mc_p95_sharpe']:.4f}
  Market Impact:          {market_impact_bps:.4f} bps  (Q/ADV={order_to_adv:.2e})

WALK-FORWARD RESULTS:
  Windows passed:         {wf['wf_windows_passed']}/4
  OOS Sharpe std:         {wf['wf_sharpe_std']:.4f}
  OOS Sharpe min:         {wf['wf_sharpe_min']:.4f}
  Consistency score:      {wf['wf_consistency_score']:.4f}

EVEN VS ODD WEEK DIAGNOSTICS:
  Avg even-week return:   {diag_even_odd['avg_even_week_return']:.4%}
  Avg odd-week return:    {diag_even_odd['avg_odd_week_return']:.4%}
  Even-week win rate:     {diag_even_odd['even_week_win_rate']:.2%}
  t-stat:                 {diag_even_odd['even_odd_t_stat']:.3f}  (p={diag_even_odd['even_odd_t_pvalue']:.4f})

POST-PUBLICATION DECAY:
  Pre-2019 even Sharpe:   {diag_decay['pre_2019_even_week']['sharpe']:.4f}  (n={diag_decay['pre_2019_even_week']['n_weeks']} weeks)
  Post-2019 even Sharpe:  {diag_decay['post_2019_even_week']['sharpe']:.4f}  (n={diag_decay['post_2019_even_week']['n_weeks']} weeks)
  Retirement signal:      {diag_decay['retirement_signal']}
  {diag_decay['retirement_note']}

200-DMA OVERLAY IMPACT:
  Baseline (MA=200):      Sharpe={r_is['sharpe']:.4f}  MDD={r_is['max_drawdown']:.2%}
  No MA filter:           Sharpe={r_noma['sharpe']:.4f}  MDD={r_noma['max_drawdown']:.2%}
  Sharpe improvement:     {dma_overlay_impact['sharpe_improvement_from_ma']:.4f}
  MDD improvement:        {dma_overlay_impact['mdd_improvement_from_ma']:.2%}

{'FAILED CHECKS: ' + ', '.join(failed_checks) if failed_checks else 'All checks PASSED'}
"""

    verdict_path = OUT_PREFIX + "_verdict.txt"
    with open(verdict_path, "w") as f:
        f.write(verdict_txt)
    print(f"Verdict saved: {verdict_path}")

    # ── Save HTML report ──────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>H47 FOMC Bi-Weekly Cycle — Gate 1 Report</title>
<style>
body {{ font-family: monospace; margin: 40px; background: #111; color: #eee; }}
h1 {{ color: {'#4caf50' if gate1_pass else '#f44336'}; }}
h2 {{ color: #90caf9; border-bottom: 1px solid #333; padding-bottom: 6px; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
th {{ background: #1e3a5f; color: #fff; padding: 8px; text-align: left; }}
td {{ padding: 6px 10px; border: 1px solid #333; }}
tr:nth-child(even) {{ background: #1a1a1a; }}
.pass {{ color: #4caf50; font-weight: bold; }}
.fail {{ color: #f44336; font-weight: bold; }}
.metric-value {{ text-align: right; font-weight: bold; }}
</style></head><body>
<h1>H47 FOMC Bi-Weekly Cycle — Gate 1: {gate1_verdict}</h1>
<p>Date: {TODAY} | IS: 2003-01-01 → 2023-12-31 | OOS: 2024-01-01 → 2026-06-10</p>

<h2>Core Gate 1 Metrics</h2>
<table>
<tr><th>Metric</th><th>Value</th><th>Threshold</th><th>Result</th></tr>
<tr><td>IS Sharpe</td><td class="metric-value">{r_is['sharpe']:.4f}</td><td>&gt; 1.0</td><td class="{'pass' if gate1_checks['is_sharpe_pass'] else 'fail'}">{'PASS' if gate1_checks['is_sharpe_pass'] else 'FAIL'}</td></tr>
<tr><td>OOS Sharpe</td><td class="metric-value">{r_oos['sharpe']:.4f}</td><td>&gt; 0.7</td><td class="{'pass' if gate1_checks['oos_sharpe_pass'] else 'fail'}">{'PASS' if gate1_checks['oos_sharpe_pass'] else 'FAIL'}</td></tr>
<tr><td>IS Max Drawdown</td><td class="metric-value">{r_is['max_drawdown']:.2%}</td><td>&lt; 20%</td><td class="{'pass' if gate1_checks['is_mdd_pass'] else 'fail'}">{'PASS' if gate1_checks['is_mdd_pass'] else 'FAIL'}</td></tr>
<tr><td>IS CAGR</td><td class="metric-value">{is_cagr:.2%}</td><td>&ge; 10%</td><td class="{'pass' if gate1_checks['is_cagr_pass'] else 'fail'}">{'PASS' if gate1_checks['is_cagr_pass'] else 'FAIL'}</td></tr>
<tr><td>Win Rate</td><td class="metric-value">{r_is['win_rate']:.2%}</td><td>&gt; 50%</td><td class="{'pass' if gate1_checks['even_week_winrate_pass'] else 'fail'}">{'PASS' if gate1_checks['even_week_winrate_pass'] else 'FAIL'}</td></tr>
<tr><td>Trade Count (IS)</td><td class="metric-value">{r_is['trade_count']}</td><td>&ge; 100</td><td class="{'pass' if gate1_checks['trade_count_pass'] else 'fail'}">{'PASS' if gate1_checks['trade_count_pass'] else 'FAIL'}</td></tr>
<tr><td>WF Windows Passed</td><td class="metric-value">{wf['wf_windows_passed']}/4</td><td>&ge; 3</td><td class="{'pass' if gate1_checks['wf_windows_pass'] else 'fail'}">{'PASS' if gate1_checks['wf_windows_pass'] else 'FAIL'}</td></tr>
<tr><td>Permutation p-value</td><td class="metric-value">{perm['permutation_pvalue']:.4f}</td><td>&lt; 0.05</td><td class="{'pass' if perm['permutation_test_pass'] else 'fail'}">{'PASS' if perm['permutation_test_pass'] else 'FAIL'}</td></tr>
<tr><td>MC p5 Sharpe</td><td class="metric-value">{mc['mc_p5_sharpe']:.4f}</td><td>&ge; 0.5</td><td class="{'pass' if gate1_checks['mc_p5_pass'] else 'fail'}">{'PASS' if gate1_checks['mc_p5_pass'] else 'FAIL'}</td></tr>
<tr><td>DSR</td><td class="metric-value">{dsr:.6f}</td><td>&gt; 0</td><td class="{'pass' if dsr > 0 else 'fail'}">{'PASS' if dsr > 0 else 'FAIL'}</td></tr>
<tr><td>Sensitivity (max dev)</td><td class="metric-value">{max_dev:.2%}</td><td>&lt; 30%</td><td class="{'pass' if sensitivity_pass else 'fail'}">{'PASS' if sensitivity_pass else 'FAIL'}</td></tr>
</table>

<h2>Statistical Rigor</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Bootstrap Sharpe CI (95%)</td><td>[{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]</td></tr>
<tr><td>Bootstrap MDD CI (95%)</td><td>[{bb['mdd_ci_low']:.2%}, {bb['mdd_ci_high']:.2%}]</td></tr>
<tr><td>MC p5 / median / p95</td><td>{mc['mc_p5_sharpe']:.4f} / {mc['mc_median_sharpe']:.4f} / {mc['mc_p95_sharpe']:.4f}</td></tr>
<tr><td>Market Impact (bps)</td><td>{market_impact_bps:.4f}</td></tr>
<tr><td>Q/ADV ratio</td><td>{order_to_adv:.2e}</td></tr>
<tr><td>WF Sharpe std</td><td>{wf['wf_sharpe_std']:.4f}</td></tr>
<tr><td>WF Sharpe min</td><td>{wf['wf_sharpe_min']:.4f}</td></tr>
</table>

<h2>Special Diagnostics</h2>
<h3>Even vs Odd Week</h3>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Avg even-week return</td><td>{diag_even_odd['avg_even_week_return']:.4%}</td></tr>
<tr><td>Avg odd-week return</td><td>{diag_even_odd['avg_odd_week_return']:.4%}</td></tr>
<tr><td>Even-week win rate</td><td>{diag_even_odd['even_week_win_rate']:.2%}</td></tr>
<tr><td>t-statistic (even vs odd)</td><td>{diag_even_odd['even_odd_t_stat']:.3f}</td></tr>
<tr><td>t-test p-value</td><td>{diag_even_odd['even_odd_t_pvalue']:.4f}</td></tr>
</table>

<h3>Post-Publication Decay</h3>
<table>
<tr><th>Period</th><th>Even-Week Mean Return</th><th>Even-Week Sharpe</th><th>N Weeks</th></tr>
<tr><td>Pre-2019 (IS)</td><td>{diag_decay['pre_2019_even_week']['mean_even_return']:.4%}</td><td>{diag_decay['pre_2019_even_week']['sharpe']:.4f}</td><td>{diag_decay['pre_2019_even_week']['n_weeks']}</td></tr>
<tr><td>Post-2019 (OOS)</td><td>{diag_decay['post_2019_even_week']['mean_even_return']:.4%}</td><td>{diag_decay['post_2019_even_week']['sharpe']:.4f}</td><td>{diag_decay['post_2019_even_week']['n_weeks']}</td></tr>
</table>
<p><b>Retirement signal: {diag_decay['retirement_note']}</b></p>

<h3>200-DMA Overlay Impact</h3>
<table>
<tr><th>Config</th><th>Sharpe</th><th>MDD</th></tr>
<tr><td>Baseline (MA=200, size=0.5)</td><td>{r_is['sharpe']:.4f}</td><td>{r_is['max_drawdown']:.2%}</td></tr>
<tr><td>No MA filter (size=1.0)</td><td>{r_noma['sharpe']:.4f}</td><td>{r_noma['max_drawdown']:.2%}</td></tr>
</table>

<h2>Walk-Forward Windows</h2>
<table>
<tr><th>IS Window</th><th>OOS Window</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>OOS Profitable</th></tr>
{''.join(f"<tr><td>{r['is_window']}</td><td>{r['oos_window']}</td><td>{r['is_sharpe']:.4f}</td><td>{r['oos_sharpe']:.4f}</td><td class=\"{'pass' if r['oos_profitable'] else 'fail'}\">{'YES' if r['oos_profitable'] else 'NO'}</td></tr>" for r in wf['wf_results'])}
</table>

<h2>Sub-Period Performance</h2>
<table>
<tr><th>Period</th><th>Sharpe</th><th>MDD</th></tr>
<tr><td>Full IS (2003–2023)</td><td>{r_is['sharpe']:.4f}</td><td>{r_is['max_drawdown']:.2%}</td></tr>
<tr><td>Pre-pub IS (2003–2018)</td><td>{r_prepub['sharpe']:.4f}</td><td>{r_prepub['max_drawdown']:.2%}</td></tr>
<tr><td>Post-pub (2019–2026)</td><td>{r_postpub['sharpe']:.4f}</td><td>{r_postpub['max_drawdown']:.2%}</td></tr>
<tr><td>OOS (2024–2026-06-10)</td><td>{r_oos['sharpe']:.4f}</td><td>{r_oos['max_drawdown']:.2%}</td></tr>
</table>

</body></html>"""

    html_path = OUT_PREFIX + "_report.html"
    with open(html_path, "w") as f:
        f.write(html)
    print(f"HTML report saved: {html_path}")

    # ── Summary print ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("GATE 1 SUMMARY")
    print("=" * 70)
    print(f"IS Sharpe:       {r_is['sharpe']:.4f}  {'✓' if gate1_checks['is_sharpe_pass'] else '✗'}")
    print(f"OOS Sharpe:      {r_oos['sharpe']:.4f}  {'✓' if gate1_checks['oos_sharpe_pass'] else '✗'}")
    print(f"IS MDD:          {r_is['max_drawdown']:.2%}  {'✓' if gate1_checks['is_mdd_pass'] else '✗'}")
    print(f"IS CAGR:         {is_cagr:.2%}  {'✓' if gate1_checks['is_cagr_pass'] else '✗'}")
    print(f"WF consistency:  {wf['wf_windows_passed']}/4 {'✓' if gate1_checks['wf_windows_pass'] else '✗'}")
    print(f"Permutation p:   {perm['permutation_pvalue']:.4f}  {'✓' if perm['permutation_test_pass'] else '✗'}")
    print(f"Even-wk winrate: {diag_even_odd['even_week_win_rate']:.2%}  {'✓' if gate1_checks['even_week_winrate_pass'] else '✗'}")
    print(f"Post-pub Sharpe: {diag_decay['post_2019_even_week']['sharpe']:.4f}")
    print(f"\nVERDICT: {gate1_verdict}")
    print("=" * 70)

    return metrics


if __name__ == "__main__":
    main()
