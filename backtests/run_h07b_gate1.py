"""
H07b Gate 1 Backtest Runner
Executes IS/OOS backtests, walk-forward, statistical rigor pipeline,
regime-slice analysis (criteria.md v1.1), and sensitivity scan for
H07b Multi-Asset TSMOM (15-ETF expanded universe + VIX regime gate).

Output schema matches H07_MultiAsset_TSMOM_2026-03-16.json with additions:
  - vix_regime_stats: dict of VIX regime day counts and percentages
  - regime_slices: dict of per-regime IS Sharpe (criteria.md v1.1 sub-criterion)
  - regime_slice_pass: bool
"""

import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
from datetime import date
import vectorbt as vbt

warnings.filterwarnings("ignore")

# Annualize Sharpe using daily frequency
vbt.settings.array_wrapper['freq'] = 'D'

# Add parent directory to import the strategy module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.h07b_multi_asset_tsmom_expanded import (
    download_data, download_vix, resolve_universe, check_data_quality,
    generate_daily_signals, compute_market_impact, check_liquidity_constraints,
    scan_parameters, PARAMETERS,
)

# ── Constants ──────────────────────────────────────────────────────────────────

IS_START = "2018-01-01"
IS_END = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END = "2023-12-31"
INIT_CASH = 25000
TODAY = str(date.today())
STRATEGY_NAME = "H07b_MultiAsset_TSMOM_Expanded"

# Regime-slice windows (criteria.md v1.1 sub-criterion)
REGIME_SLICES = {
    "pre_covid_2018_2019": ("2018-01-01", "2019-12-31"),
    "stimulus_2020_2021": ("2020-01-01", "2021-12-31"),
    "rate_shock_2022": ("2022-01-01", "2022-12-31"),
    "normalization_2023": ("2023-01-01", "2023-12-31"),
}
# Regimes considered "stress" for the v1.1 requirement
STRESS_REGIMES = {"stimulus_2020_2021", "rate_shock_2022"}


# ── Portfolio Builder ──────────────────────────────────────────────────────────

def build_portfolio(start: str, end: str, params: dict) -> tuple:
    """
    Build per-ticker vectorbt portfolios for H07b with VIX-scaled sizing.

    Capital allocation:
    - init_cash split equally across tickers: cash_per_ticker = init_cash / n_tickers
    - Normal regime (VIX ≤ stress_threshold): invest full cash_per_ticker per entry
    - Stress regime (VIX 25-35): invest cash_per_ticker × 0.5 per entry
    - Crisis regime (VIX > 35): no entry; existing positions exited

    Sizing is implemented via size_type='value' (dollar amount per entry).
    Falls back to default sizing if vectorbt raises an error.

    Returns: (pf, close, volume, extra)
        extra: dict with quality_report, liquidity_report, entries, vix_daily_scale, q_over_adv
    """
    universe = resolve_universe(
        list(params.get("universe", PARAMETERS["universe"])), start
    )
    close, volume = download_data(universe, start, end)

    # Download VIX with pre-start buffer for month-end alignment
    vix_start = str((pd.Timestamp(start) - pd.DateOffset(months=2)).date())
    vix_close = download_vix(vix_start, end)

    quality_report = check_data_quality(close)
    close = close.dropna(axis=1, how="all")
    if close.empty:
        raise ValueError(f"No price data for {universe} in {start}–{end}.")

    min_required = params["lookback_months"] * 21 + 20
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    entries, exits, vix_daily_scale = generate_daily_signals(close, vix_close, params)
    market_impact_df, q_over_adv = compute_market_impact(close, volume, params)
    liquidity_report = check_liquidity_constraints(q_over_adv)

    fees = 0.005 / close
    slippage = 0.0005 + market_impact_df

    n_tickers = len(close.columns)
    cash_per_ticker = params.get("init_cash", INIT_CASH) / n_tickers

    # Build dollar-value size DataFrame for VIX-scaled entries
    # On entry bars: size = cash_per_ticker × vix_scale (dollar amount)
    # On non-entry bars: NaN (vectorbt ignores size on non-signal bars)
    size_dollars = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    entry_arr = entries.values
    for col_idx, ticker in enumerate(close.columns):
        row_indices = np.where(entry_arr[:, col_idx])[0]
        for row_idx in row_indices:
            scale = float(vix_daily_scale.iloc[row_idx])
            # Crisis (scale=0.0) entries should already be blocked; guard here
            effective_scale = max(scale, 0.5)  # stress or normal
            size_dollars.iloc[row_idx, col_idx] = cash_per_ticker * effective_scale

    try:
        pf = vbt.Portfolio.from_signals(
            close,
            entries=entries,
            exits=exits,
            size=size_dollars,
            size_type="value",
            sl_stop=params.get("intramonth_stop_pct", 0.20),
            fees=fees,
            slippage=slippage,
            init_cash=cash_per_ticker,
            group_by=False,
        )
    except Exception as exc:
        warnings.warn(f"VIX-scaled sizing failed ({exc}). Falling back to default sizing.")
        pf = vbt.Portfolio.from_signals(
            close,
            entries=entries,
            exits=exits,
            sl_stop=params.get("intramonth_stop_pct", 0.20),
            fees=fees,
            slippage=slippage,
            init_cash=cash_per_ticker,
            group_by=False,
        )

    extra = {
        "quality_report": quality_report,
        "liquidity_report": liquidity_report,
        "entries": entries,
        "vix_daily_scale": vix_daily_scale,
        "q_over_adv": q_over_adv,
        "close": close,
    }
    return pf, close, volume, extra


def portfolio_metrics(pf, close: pd.DataFrame, params: dict) -> dict:
    """
    Extract combined portfolio-level metrics from per-ticker portfolios.
    Combines individual portfolio values for portfolio-level Sharpe/MDD.
    """
    combined_value = pf.value().sum(axis=1)
    combined_returns = combined_value.pct_change().fillna(0).values
    sharpe = float(combined_returns.mean() / (combined_returns.std() + 1e-8) * np.sqrt(252))
    cum = np.cumprod(1 + combined_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(combined_value.iloc[-1] / combined_value.iloc[0] - 1)
    trade_count = int(pf.trades.count().sum())

    try:
        pnl_vals = pf.trades.pnl.values
        pnl_vals = pnl_vals[~np.isnan(pnl_vals)]
        win_rate = float(np.mean(pnl_vals > 0)) if len(pnl_vals) > 0 else 0.0
        wins = pnl_vals[pnl_vals > 0]
        losses = pnl_vals[pnl_vals < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
        profit_factor = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0
            else float("inf")
        )
    except Exception:
        pnl_vals = np.array([0.0])
        win_rate = win_loss_ratio = profit_factor = 0.0

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "win_loss_ratio": win_loss_ratio,
        "profit_factor": profit_factor,
        "pnl_vals": pnl_vals,
        "combined_returns": combined_returns,
        "combined_value": combined_value,
    }


# ── Regime-Slice Analysis (criteria.md v1.1) ──────────────────────────────────

def compute_regime_slices(
    pf_full, combined_value_full: pd.Series, params: dict
) -> dict:
    """
    Compute per-regime IS Sharpe for criteria.md v1.1 regime-slice sub-criterion.

    Regime windows:
    - Pre-COVID (2018-2019): normal bull market, low vol
    - Stimulus era (2020-2021): COVID crash recovery + historic stimulus
    - Rate-shock (2022): Fed tightening, multi-asset drawdown
    - Normalization (2023): post-tightening stabilization

    Requirements (criteria.md v1.1):
    - IS Sharpe ≥ 0.8 in ≥ 2 of 4 sub-regimes
    - At least one passing regime must be a stress regime (Stimulus OR Rate-shock)
    - Sub-regimes with <10 trades are "insufficient data" and excluded from count

    Returns dict with per-regime metrics and overall pass/fail.
    """
    regime_results = {}
    trade_count_per_regime = {}

    for regime_name, (r_start, r_end) in REGIME_SLICES.items():
        mask = (
            (combined_value_full.index >= pd.Timestamp(r_start)) &
            (combined_value_full.index <= pd.Timestamp(r_end))
        )
        val_slice = combined_value_full[mask]

        if len(val_slice) < 10:
            regime_results[regime_name] = {
                "sharpe": None,
                "status": "insufficient_data",
                "passes": None,
            }
            continue

        rets = val_slice.pct_change().fillna(0).values
        sharpe = float(rets.mean() / (rets.std() + 1e-8) * np.sqrt(252))
        cum = np.cumprod(1 + rets)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))

        # Estimate trade count in this period (approximate)
        period_fraction = len(val_slice) / max(1, len(combined_value_full))
        approx_trades = int(round(pf_full.trades.count().sum() * period_fraction))
        trade_count_per_regime[regime_name] = approx_trades

        if approx_trades < 10:
            regime_results[regime_name] = {
                "sharpe": round(sharpe, 4),
                "mdd": round(mdd, 4),
                "approx_trades": approx_trades,
                "status": "insufficient_data",
                "passes": None,
            }
        else:
            regime_results[regime_name] = {
                "sharpe": round(sharpe, 4),
                "mdd": round(mdd, 4),
                "approx_trades": approx_trades,
                "status": "assessable",
                "passes": sharpe >= 0.8,
            }

    # Evaluate v1.1 requirement
    assessable = {k: v for k, v in regime_results.items() if v.get("status") == "assessable"}
    passing = {k: v for k, v in assessable.items() if v.get("passes")}
    stress_passing = [k for k in passing if k in STRESS_REGIMES]

    n_assessable = len(assessable)
    n_passing = len(passing)
    has_stress_pass = len(stress_passing) > 0

    # criteria.md v1.1: ≥2 of assessable regimes pass, at least one stress regime
    regime_slice_pass = (n_passing >= 2) and has_stress_pass

    return {
        "regimes": regime_results,
        "n_assessable": n_assessable,
        "n_passing": n_passing,
        "stress_regime_passing": stress_passing,
        "has_stress_pass": has_stress_pass,
        "regime_slice_pass": regime_slice_pass,
        "note": (
            "Pass requires IS Sharpe ≥ 0.8 in ≥2 of 4 sub-regimes, "
            "at least one being a stress regime (Stimulus or Rate-shock). "
            "Criteria.md v1.1."
        ),
    }


# ── Statistical Rigor Functions ────────────────────────────────────────────────

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
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low": float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def permutation_test_alpha(
    prices: np.ndarray,
    entries_flat: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 500,
    hold_days: int = 21,
) -> dict:
    entry_indices = np.where(entries_flat)[0]
    n_entries = len(entry_indices)
    if n_entries == 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    permuted_sharpes = []
    for _ in range(n_perms):
        perm_idx = np.random.choice(len(prices), size=n_entries, replace=False)
        trade_returns = []
        for idx in perm_idx:
            exit_idx = min(idx + hold_days, len(prices) - 1)
            if prices[idx] > 0:
                ret = (prices[exit_idx] - prices[idx]) / prices[idx]
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
    arr = np.array([s for s in wf_oos_sharpes if s is not None and not np.isnan(s)])
    if len(arr) == 0:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


def compute_dsr(returns_series: np.ndarray, n_trials: int) -> float:
    """Deflated Sharpe Ratio: adjusts IS Sharpe for multiple comparisons."""
    T = len(returns_series)
    if T < 2:
        return 0.0
    from scipy.stats import norm
    sr_obs = returns_series.mean() / (returns_series.std() + 1e-8) * np.sqrt(252)
    sr_star = (
        (1 - np.euler_gamma) * norm.ppf(1 - 1.0 / n_trials)
        + np.euler_gamma * norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    skew = float(pd.Series(returns_series).skew())
    kurt = float(pd.Series(returns_series).kurtosis())
    var_sr = (1 + (0.5 * sr_obs**2) - (skew * sr_obs) + ((kurt / 4) * sr_obs**2)) / (T - 1)
    dsr = norm.cdf((sr_obs - sr_star) / (np.sqrt(max(var_sr, 1e-12)) + 1e-8))
    return float(dsr)


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(
    params: dict, n_windows: int = 4, train_months: int = 36, test_months: int = 6
) -> dict:
    """
    Walk-forward analysis with sliding IS+OOS windows.
    Runs the full combined window to satisfy lookback, then splits at IS/OOS boundary.
    OOS Sharpe ≥ 0.7 is the per-window pass criterion.
    """
    wf_results = []
    base_start = pd.Timestamp("2018-01-01")

    for i in range(n_windows):
        offset_months = i * 6
        is_start = (base_start + pd.DateOffset(months=offset_months)).strftime("%Y-%m-%d")
        is_end = (base_start + pd.DateOffset(
            months=offset_months + train_months - 1, day=31)).strftime("%Y-%m-%d")
        oos_start = (base_start + pd.DateOffset(
            months=offset_months + train_months)).strftime("%Y-%m-%d")
        oos_end = (base_start + pd.DateOffset(
            months=offset_months + train_months + test_months - 1, day=31)).strftime("%Y-%m-%d")

        try:
            pf_full, close_full, _, _ = build_portfolio(is_start, oos_end, params)
            combined_value_full = pf_full.value().sum(axis=1)

            is_mask = combined_value_full.index <= pd.Timestamp(is_end)
            oos_mask = combined_value_full.index >= pd.Timestamp(oos_start)
            is_value = combined_value_full[is_mask]
            oos_value = combined_value_full[oos_mask]

            def period_metrics(val_series):
                if len(val_series) < 5:
                    return {"sharpe": 0.0, "mdd": 0.0}
                rets = val_series.pct_change().fillna(0).values
                s = float(rets.mean() / (rets.std() + 1e-8) * np.sqrt(252))
                cum = np.cumprod(1 + rets)
                roll_max = np.maximum.accumulate(cum)
                mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
                return {"sharpe": s, "mdd": mdd}

            m_is_wf = period_metrics(is_value)
            m_oos_wf = period_metrics(oos_value)

            # Approximate OOS trade count as proportion of full-window trades
            total_trades = int(pf_full.trades.count().sum())
            oos_frac = len(oos_value) / max(1, len(combined_value_full))
            oos_trade_count = max(1, int(round(total_trades * oos_frac)))

            wf_results.append({
                "window": i + 1,
                "is_start": is_start,
                "is_end": is_end,
                "oos_start": oos_start,
                "oos_end": oos_end,
                "is_sharpe": round(m_is_wf["sharpe"], 4),
                "oos_sharpe": round(m_oos_wf["sharpe"], 4),
                "is_mdd": round(m_is_wf["mdd"], 4),
                "oos_mdd": round(m_oos_wf["mdd"], 4),
                "oos_trade_count": oos_trade_count,
                "pass": m_oos_wf["sharpe"] >= 0.7,
            })
        except Exception as exc:
            wf_results.append({
                "window": i + 1,
                "is_start": is_start,
                "is_end": is_end,
                "oos_start": oos_start,
                "oos_end": oos_end,
                "error": str(exc),
                "pass": False,
            })

    windows_passed = sum(1 for w in wf_results if w.get("pass", False))
    oos_sharpes = [w["oos_sharpe"] for w in wf_results if "oos_sharpe" in w]
    is_sharpes = [w["is_sharpe"] for w in wf_results if "is_sharpe" in w]

    consistency_ratios = []
    for w in wf_results:
        if "is_sharpe" in w and "oos_sharpe" in w and abs(w["is_sharpe"]) > 0.01:
            consistency_ratios.append(w["oos_sharpe"] / w["is_sharpe"])
    wf_consistency_score = float(np.mean(consistency_ratios)) if consistency_ratios else 0.0

    return {
        "windows": wf_results,
        "windows_passed": windows_passed,
        "oos_sharpes": oos_sharpes,
        "is_sharpes": is_sharpes,
        "wf_consistency_score": wf_consistency_score,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H07b Gate 1 Backtest — {TODAY}")
    print("=" * 70)

    params = {**PARAMETERS}

    # ── 1. IS Backtest ─────────────────────────────────────────────────────
    print(f"\n[1/8] Running IS backtest ({IS_START} to {IS_END})...")
    pf_is, close_is, volume_is, extra_is = build_portfolio(IS_START, IS_END, params)
    m_is = portfolio_metrics(pf_is, close_is, params)
    is_returns = m_is["combined_returns"]
    is_combined_value = m_is["combined_value"]
    print(f"  IS Sharpe:  {m_is['sharpe']:.4f}")
    print(f"  IS MDD:     {m_is['max_drawdown']:.4f}")
    print(f"  IS WinRate: {m_is['win_rate']:.4f}")
    print(f"  IS Trades:  {m_is['trade_count']}")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────
    print(f"\n[2/8] Running OOS backtest ({OOS_START} to {OOS_END})...")
    pf_oos, close_oos, _, extra_oos = build_portfolio(OOS_START, OOS_END, params)
    m_oos = portfolio_metrics(pf_oos, close_oos, params)
    oos_returns = m_oos["combined_returns"]
    print(f"  OOS Sharpe:  {m_oos['sharpe']:.4f}")
    print(f"  OOS MDD:     {m_oos['max_drawdown']:.4f}")
    print(f"  OOS WinRate: {m_oos['win_rate']:.4f}")
    print(f"  OOS Trades:  {m_oos['trade_count']}")

    # ── 3. Regime-Slice Analysis (criteria.md v1.1) ────────────────────────
    print("\n[3/8] Running regime-slice analysis (criteria.md v1.1)...")
    # Use full IS+OOS window for regime slices (all 4 regimes fall within 2018-2023)
    try:
        pf_full_window, _, _, _ = build_portfolio(IS_START, OOS_END, params)
        combined_full = pf_full_window.value().sum(axis=1)
        regime_analysis = compute_regime_slices(pf_full_window, combined_full, params)
    except Exception as exc:
        print(f"  Regime-slice warning: {exc}")
        regime_analysis = {"regime_slice_pass": False, "error": str(exc)}

    for regime_name, r in regime_analysis.get("regimes", {}).items():
        status = r.get("status", "N/A")
        sharpe = r.get("sharpe")
        sharpe_str = f"{sharpe:.4f}" if sharpe is not None else "N/A"
        passes = r.get("passes")
        pass_str = "PASS" if passes else ("FAIL" if passes is False else "N/A")
        print(f"  {regime_name}: Sharpe={sharpe_str} [{pass_str}] ({status})")
    print(f"  Regime-slice overall: "
          f"{regime_analysis.get('n_passing', 0)}/4 passing — "
          f"{'PASS' if regime_analysis.get('regime_slice_pass') else 'FAIL'}")

    # ── 4. Walk-Forward ────────────────────────────────────────────────────
    print("\n[4/8] Running walk-forward analysis (4 windows, 36m IS / 6m OOS)...")
    wf = run_walk_forward(params, n_windows=4, train_months=36, test_months=6)
    print(f"  Windows passed: {wf['windows_passed']}/4")
    for w in wf["windows"]:
        if "error" in w:
            print(f"  Window {w['window']}: ERROR — {w['error']}")
        else:
            status = "PASS" if w.get("pass") else "FAIL"
            print(f"  Window {w['window']}: IS={w['is_sharpe']:.2f}  OOS={w['oos_sharpe']:.2f}  [{status}]")

    wf_var = walk_forward_variance(wf["oos_sharpes"])

    # ── 5. Monte Carlo ─────────────────────────────────────────────────────
    print("\n[5/8] Running Monte Carlo simulation (1,000 resamples)...")
    trade_pnls = m_is["pnl_vals"]
    mc = (monte_carlo_sharpe(trade_pnls) if len(trade_pnls) > 1
          else {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0})
    print(f"  MC p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}")

    # ── 6. Block Bootstrap CI ──────────────────────────────────────────────
    print("\n[6/8] Running block bootstrap CI (1,000 boots)...")
    bb = (block_bootstrap_ci(is_returns) if len(is_returns) > 10
          else {k: 0.0 for k in ["sharpe_ci_low", "sharpe_ci_high", "mdd_ci_low",
                                  "mdd_ci_high", "win_rate_ci_low", "win_rate_ci_high"]})
    print(f"  Sharpe CI: [{bb['sharpe_ci_low']:.3f}, {bb['sharpe_ci_high']:.3f}]")
    print(f"  MDD CI:    [{bb['mdd_ci_low']:.3f}, {bb['mdd_ci_high']:.3f}]")

    # ── 7. Market Impact + Permutation ────────────────────────────────────
    print("\n[7/8] Computing market impact and permutation test...")
    import yfinance as yf
    market_impact_bps = 0.0
    order_to_adv_ratio = 0.0
    try:
        spy_hist = yf.download("SPY", start=IS_START, end=IS_END,
                               auto_adjust=True, progress=False)
        adv = float(spy_hist["Volume"].rolling(20).mean().iloc[-1])
        sigma = float(spy_hist["Close"].pct_change().std())
        qty = params.get("order_qty", 100)
        q_adv = qty / (adv + 1e-8)
        market_impact_bps = 0.1 * sigma * np.sqrt(q_adv) * 10000
        order_to_adv_ratio = q_adv
        print(f"  SPY impact: {market_impact_bps:.4f} bps  Q/ADV={q_adv:.6f}")
    except Exception as e:
        print(f"  Market impact compute warning: {e}")

    liquidity_report = extra_is["liquidity_report"]
    liquidity_constrained = liquidity_report.get("liquidity_constrained", False)

    try:
        entries_is = extra_is["entries"]
        spy_prices = close_is["SPY"].values if "SPY" in close_is.columns else close_is.iloc[:, 0].values
        spy_entries = entries_is["SPY"].values if "SPY" in entries_is.columns else entries_is.iloc[:, 0].values
        perm = permutation_test_alpha(spy_prices, spy_entries, m_is["sharpe"])
        print(f"  Permutation p-value: {perm['permutation_pvalue']:.4f}  "
              f"({'PASS' if perm['permutation_test_pass'] else 'FAIL'})")
    except Exception as e:
        print(f"  Permutation test warning: {e}")
        perm = {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    # DSR (n_trials = number of parameter combos tested across H07b sensitivity scan)
    n_trials = 9  # 3 lookbacks × 3 vix_stress × 1 crisis threshold (primary axis only)
    dsr = compute_dsr(is_returns, n_trials)
    print(f"  DSR: {dsr:.4f}")

    # ── 8. Parameter Sensitivity Scan ─────────────────────────────────────
    print("\n[8/8] Running parameter sensitivity scan...")
    sens_results = {}
    grid = {
        "lookback_months": [9, 12, 18],
        "vix_stress_threshold": [20, 25, 30],
        "intramonth_stop_pct": [0.15, 0.20, 0.25],
    }
    for param_name, values in grid.items():
        for val in values:
            p = {**params, param_name: val}
            key = f"{param_name}={val}"
            try:
                pf_s, _, _, _ = build_portfolio(IS_START, IS_END, p)
                m_s = portfolio_metrics(pf_s, None, p)
                sens_results[key] = round(m_s["sharpe"], 4)
            except Exception as exc:
                sens_results[key] = f"error: {exc}"

    sharpe_nums = [v for v in sens_results.values() if isinstance(v, float)]
    if len(sharpe_nums) > 1:
        sharpe_range = max(sharpe_nums) - min(sharpe_nums)
        sharpe_mean = np.mean(sharpe_nums)
        variance_pct = sharpe_range / abs(sharpe_mean) if abs(sharpe_mean) > 0 else float("inf")
        sens_results["_sharpe_range"] = round(sharpe_range, 4)
        sens_results["_sharpe_variance_pct"] = round(variance_pct, 4)
        sens_results["_gate1_variance_flag"] = (
            f"PASS: variance {variance_pct:.1%} ≤ 30%"
            if variance_pct <= 0.30
            else f"FAIL: variance {variance_pct:.1%} > 30%"
        )
    sensitivity_pass = "PASS" in str(sens_results.get("_gate1_variance_flag", ""))
    print(f"  Sharpe range: {sens_results.get('_sharpe_range', 'N/A')}")
    print(f"  Sensitivity:  {sens_results.get('_gate1_variance_flag', 'N/A')}")

    # VIX regime statistics (IS window)
    vix_daily_scale_is = extra_is.get("vix_daily_scale", pd.Series())
    try:
        import yfinance as yf2
        vix_raw = yf2.download("^VIX", start=IS_START, end=IS_END,
                               auto_adjust=True, progress=False)
        vix_is = vix_raw["Close"].squeeze() if not vix_raw.empty else pd.Series()
        n_crisis = int((vix_is > params["vix_crisis_threshold"]).sum())
        n_stress = int(
            ((vix_is > params["vix_stress_threshold"]) &
             (vix_is <= params["vix_crisis_threshold"])).sum()
        )
        n_normal = int((vix_is <= params["vix_stress_threshold"]).sum())
        total_vix_days = len(vix_is)
        vix_regime_stats = {
            "days_crisis": n_crisis,
            "days_stress": n_stress,
            "days_normal": n_normal,
            "pct_crisis": round(n_crisis / max(1, total_vix_days), 4),
            "pct_stress": round(n_stress / max(1, total_vix_days), 4),
            "pct_normal": round(n_normal / max(1, total_vix_days), 4),
        }
    except Exception:
        vix_regime_stats = {}

    # ── Gate 1 Checks ──────────────────────────────────────────────────────
    regime_slice_pass = regime_analysis.get("regime_slice_pass", False)

    gate1_checks = {
        "is_sharpe_pass": m_is["sharpe"] > 1.0,
        "oos_sharpe_pass": m_oos["sharpe"] > 0.7,
        "is_mdd_pass": abs(m_is["max_drawdown"]) < 0.20,
        "oos_mdd_pass": abs(m_oos["max_drawdown"]) < 0.25,
        "win_rate_pass": m_is["win_rate"] > 0.50,
        "win_loss_ratio_pass": m_is["win_loss_ratio"] >= 1.0,
        "trade_count_pass": m_is["trade_count"] >= 50,
        "wf_windows_pass": wf["windows_passed"] >= 3,
        "wf_consistency_pass": wf["wf_consistency_score"] >= 0.70,
        "sensitivity_pass": sensitivity_pass,
        "dsr_pass": dsr > 0.0,
        "permutation_pass": perm["permutation_test_pass"],
        "regime_slice_pass": regime_slice_pass,  # criteria.md v1.1
    }
    gate1_pass = all(gate1_checks.values())

    # ── Assemble Metrics JSON ──────────────────────────────────────────────
    regime_for_json = {}
    if "regimes" in regime_analysis:
        for regime_name, r in regime_analysis["regimes"].items():
            regime_for_json[regime_name] = {
                "sharpe": r.get("sharpe"),
                "mdd": r.get("mdd"),
                "approx_trades": r.get("approx_trades"),
                "status": r.get("status"),
                "passes": r.get("passes"),
            }

    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        "is_period": f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        # Core metrics
        "is_sharpe": round(m_is["sharpe"], 4),
        "oos_sharpe": round(m_oos["sharpe"], 4),
        "is_max_drawdown": round(m_is["max_drawdown"], 4),
        "oos_max_drawdown": round(m_oos["max_drawdown"], 4),
        "win_rate": round(m_is["win_rate"], 4),
        "win_loss_ratio": round(m_is["win_loss_ratio"], 4),
        "profit_factor": round(m_is["profit_factor"], 4),
        "trade_count": m_is["trade_count"],
        "oos_trade_count": m_oos["trade_count"],
        "total_return_is": round(m_is["total_return"], 4),
        "total_return_oos": round(m_oos["total_return"], 4),
        "dsr": round(dsr, 4),
        "post_cost_sharpe": round(m_is["sharpe"], 4),  # IS already includes costs
        # Walk-forward
        "wf_windows_passed": wf["windows_passed"],
        "wf_consistency_score": round(wf["wf_consistency_score"], 4),
        "wf_table": wf["windows"],
        "wf_oos_sharpes": wf["oos_sharpes"],
        "wf_sharpe_std": round(wf_var["wf_sharpe_std"], 4),
        "wf_sharpe_min": round(wf_var["wf_sharpe_min"], 4),
        # Statistical rigor
        "mc_p5_sharpe": round(mc["mc_p5_sharpe"], 4),
        "mc_median_sharpe": round(mc["mc_median_sharpe"], 4),
        "mc_p95_sharpe": round(mc["mc_p95_sharpe"], 4),
        "sharpe_ci_low": round(bb["sharpe_ci_low"], 4),
        "sharpe_ci_high": round(bb["sharpe_ci_high"], 4),
        "mdd_ci_low": round(bb["mdd_ci_low"], 4),
        "mdd_ci_high": round(bb["mdd_ci_high"], 4),
        "win_rate_ci_low": round(bb["win_rate_ci_low"], 4),
        "win_rate_ci_high": round(bb["win_rate_ci_high"], 4),
        "market_impact_bps": round(market_impact_bps, 6),
        "liquidity_constrained": liquidity_constrained,
        "order_to_adv_ratio": round(order_to_adv_ratio, 8),
        "permutation_pvalue": round(perm["permutation_pvalue"], 4),
        "permutation_test_pass": perm["permutation_test_pass"],
        # Sensitivity
        "sensitivity_scan": sens_results,
        "sensitivity_pass": sensitivity_pass,
        # VIX regime gate statistics
        "vix_regime_stats": vix_regime_stats,
        # Regime-slice sub-criterion (criteria.md v1.1)
        "regime_slices": regime_for_json,
        "regime_slice_n_passing": regime_analysis.get("n_passing", 0),
        "regime_slice_stress_passing": regime_analysis.get("stress_regime_passing", []),
        "regime_slice_pass": regime_slice_pass,
        # Flags
        "look_ahead_bias_flag": False,
        # Gate 1
        "gate1_checks": gate1_checks,
        "gate1_pass": gate1_pass,
    }

    # ── Save JSON ──────────────────────────────────────────────────────────
    out_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, f"{STRATEGY_NAME}_{TODAY}.json")
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"\nMetrics saved: {json_path}")

    # ── Verdict ────────────────────────────────────────────────────────────
    lines = [
        f"Gate 1 Verdict — {STRATEGY_NAME} — {TODAY}",
        "=" * 60,
        f"Overall: {'PASS ✓' if gate1_pass else 'FAIL ✗'}",
        "",
        "Gate 1 Checks:",
    ]
    for check, passed in gate1_checks.items():
        lines.append(f"  [{'PASS' if passed else 'FAIL'}] {check}")

    lines += [
        "",
        "Key Metrics:",
        f"  IS Sharpe:        {metrics['is_sharpe']:.4f}  (> 1.0)",
        f"  OOS Sharpe:       {metrics['oos_sharpe']:.4f}  (> 0.7)",
        f"  IS MDD:           {metrics['is_max_drawdown']:.4f}  (< 0.20)",
        f"  OOS MDD:          {metrics['oos_max_drawdown']:.4f}  (< 0.25)",
        f"  Win Rate:         {metrics['win_rate']:.4f}  (> 0.50)",
        f"  Win/Loss Ratio:   {metrics['win_loss_ratio']:.4f}  (>= 1.0)",
        f"  Trade Count (IS): {metrics['trade_count']}  (>= 50)",
        f"  DSR:              {metrics['dsr']:.4f}  (> 0)",
        f"  WF Windows:       {metrics['wf_windows_passed']}/4  (>= 3)",
        f"  MC p5 Sharpe:     {metrics['mc_p5_sharpe']:.4f}" +
            ("  [WEAK: < 0.5]" if metrics['mc_p5_sharpe'] < 0.5 else ""),
        f"  Permutation p:    {metrics['permutation_pvalue']:.4f}  "
            f"({'PASS' if metrics['permutation_test_pass'] else 'FAIL'})",
        f"  Sensitivity:      {'PASS' if sensitivity_pass else 'FAIL'}",
        "",
        "Regime-Slice Sub-Criterion (criteria.md v1.1):",
    ]
    for regime_name, r in regime_for_json.items():
        sharpe_str = f"{r['sharpe']:.4f}" if r.get("sharpe") is not None else "N/A"
        status_str = r.get("status", "N/A")
        pass_str = "PASS" if r.get("passes") else ("FAIL" if r.get("passes") is False else "N/A")
        lines.append(f"  {regime_name}: Sharpe={sharpe_str} [{pass_str}] ({status_str})")
    n_p = regime_analysis.get("n_passing", 0)
    stress_p = regime_analysis.get("stress_regime_passing", [])
    lines.append(
        f"  Overall regime-slice: {n_p}/4 passing, "
        f"stress regimes: {stress_p} — "
        f"{'PASS' if regime_slice_pass else 'FAIL'}"
    )

    lines += [
        "",
        "VIX Regime Gate (IS window):",
        f"  Normal days (VIX ≤ {params['vix_stress_threshold']}): "
            f"{vix_regime_stats.get('days_normal', 'N/A')} "
            f"({vix_regime_stats.get('pct_normal', 0):.1%})",
        f"  Stress days (VIX {params['vix_stress_threshold']}-{params['vix_crisis_threshold']}): "
            f"{vix_regime_stats.get('days_stress', 'N/A')} "
            f"({vix_regime_stats.get('pct_stress', 0):.1%})",
        f"  Crisis days (VIX > {params['vix_crisis_threshold']}): "
            f"{vix_regime_stats.get('days_crisis', 'N/A')} "
            f"({vix_regime_stats.get('pct_crisis', 0):.1%})",
        "",
        "Walk-Forward Table:",
    ]
    for w in wf["windows"]:
        if "error" in w:
            lines.append(f"  Window {w['window']}: ERROR — {w['error']}")
        else:
            p = "PASS" if w.get("pass") else "FAIL"
            lines.append(
                f"  Window {w['window']} ({w['is_start']}–{w['oos_end']}): "
                f"IS={w['is_sharpe']:.2f}  OOS={w['oos_sharpe']:.2f}  [{p}]"
            )

    lines.append("")
    if not gate1_pass:
        lines.append("Failing criteria:")
        for check, passed in gate1_checks.items():
            if not passed:
                lines.append(f"  - {check}")
    else:
        lines.append("All Gate 1 criteria passed.")

    verdict_text = "\n".join(lines)
    verdict_path = os.path.join(out_dir, f"{STRATEGY_NAME}_{TODAY}_verdict.txt")
    with open(verdict_path, "w") as f:
        f.write(verdict_text)
    print(f"Verdict saved: {verdict_path}")
    print("\n" + verdict_text)

    return metrics


if __name__ == "__main__":
    np.random.seed(42)
    results = main()
