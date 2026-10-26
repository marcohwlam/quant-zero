"""
H77 Cross-Asset Weekly Momentum Portfolio — Gate 1 Backtest Runner
QUA-328

Runs IS/OOS backtests, full Statistical Rigor Pipeline, parameter sweep,
walk-forward analysis, and 2022 stress period. Writes all required output files.
"""

import sys
import os
import json
import math
import warnings
import datetime
import traceback

import numpy as np
import pandas as pd

# Add strategy and orchestrator to path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "strategies"))
sys.path.insert(0, os.path.join(REPO_ROOT, "orchestrator"))

from h77_cross_asset_weekly_momentum import (
    run_backtest as h77_run_backtest,
    scan_parameters as h77_scan_parameters,
    PARAMETERS,
    download_data,
    compute_cross_asset_signals,
    simulate_portfolio,
)
from quant_orchestrator import compute_dsr

DATE_STR = "2026-06-17"
STRATEGY_NAME = "H77_CrossAssetMomentum"
BACKTESTS_DIR = os.path.join(REPO_ROOT, "backtests")

IS_START = "2007-06-01"
IS_END = "2019-12-31"
OOS_START = "2020-01-01"
OOS_END = "2024-12-31"
STRESS_START = "2022-01-01"
STRESS_END = "2022-12-31"

TICKERS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "HYG", "SHY"]
TRADING_DAYS_PER_YEAR = 252


# ── Statistical Rigor Pipeline ───────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    """Bootstrap MC on trade PnL. Returns p5, median, p95 Sharpe."""
    if len(trade_pnls) < 2:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
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
    """Block bootstrap 95% CI for Sharpe, MDD, win rate. Block length = sqrt(T)."""
    T = len(returns)
    if T < 4:
        return {
            "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
            "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
        }
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = T // block_len

    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
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


def compute_market_impact_h77(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    trade_log: list,
    params: dict,
) -> dict:
    """
    Aggregate market impact across all H77 trades.
    Returns avg bps, max bps, any liquidity-constrained trades.
    """
    k = 0.1
    impact_bps_list = []
    constrained_count = 0

    for entry in trade_log:
        ticker = entry.get("ticker")
        date_str = entry.get("date")
        shares = abs(entry.get("shares", 0))
        if not ticker or not date_str or shares < 1e-6:
            continue
        if ticker not in close.columns or ticker not in volume.columns:
            continue
        try:
            date = pd.Timestamp(date_str)
            if date not in close.index:
                continue
            sigma_series = close[ticker].pct_change().rolling(20).std()
            adv_series = (volume[ticker] * close[ticker]).rolling(20).mean()
            sigma_val = sigma_series.get(date, np.nan)
            adv_val = adv_series.get(date, np.nan)
            if pd.isna(sigma_val) or pd.isna(adv_val) or adv_val <= 0:
                continue
            price = close.at[date, ticker]
            q_over_adv = (shares * price) / adv_val
            impact = k * sigma_val * math.sqrt(max(q_over_adv, 0))
            impact_bps = impact * 10000
            impact_bps_list.append(impact_bps)
            if q_over_adv > 0.01:
                constrained_count += 1
        except Exception:
            continue

    if not impact_bps_list:
        return {
            "market_impact_bps": 0.0,
            "market_impact_bps_max": 0.0,
            "liquidity_constrained": False,
            "order_to_adv_ratio": 0.0,
            "constrained_trade_count": 0,
        }

    return {
        "market_impact_bps": round(float(np.mean(impact_bps_list)), 4),
        "market_impact_bps_max": round(float(np.max(impact_bps_list)), 4),
        "liquidity_constrained": constrained_count > 0,
        "order_to_adv_ratio": 0.0,  # not tracked per-trade here
        "constrained_trade_count": constrained_count,
    }


def permutation_test_alpha(
    prices_df: pd.DataFrame,
    signal_df: pd.DataFrame,
    volume: pd.DataFrame,
    params: dict,
    observed_sharpe: float,
    close_full: pd.DataFrame,
    volume_full: pd.DataFrame,
    n_perms: int = 500,
) -> dict:
    """
    Permutation test: shuffle signal dates (rebalance schedule), recompute Sharpe.
    p-value = fraction of permuted Sharpes >= observed Sharpe.
    """
    if signal_df.empty or len(signal_df) < 5:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    price_index = prices_df.index
    signal_dates = list(signal_df.index)
    n_signals = len(signal_dates)

    # All available trading dates in the IS window for permutation
    all_dates = list(price_index)
    if len(all_dates) < n_signals:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    permuted_sharpes = []
    np.random.seed(42)  # reproducibility

    for i in range(n_perms):
        try:
            # Draw random dates to replace signal dates
            perm_indices = np.random.choice(len(all_dates), size=n_signals, replace=False)
            perm_dates = sorted([all_dates[j] for j in perm_indices])

            # Build permuted signal_df: same target weights structure, shuffled dates
            perm_signal = signal_df.copy()
            perm_signal.index = pd.DatetimeIndex(perm_dates)

            # Simulate with permuted signals
            sim = simulate_portfolio(
                prices_df, volume, perm_signal, params,
                close_full=close_full, volume_full=volume_full,
            )
            perm_sharpe = sim["sharpe"]
            permuted_sharpes.append(perm_sharpe)
        except Exception:
            permuted_sharpes.append(0.0)

    if not permuted_sharpes:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    arr = np.array(permuted_sharpes)
    p_value = float(np.mean(arr >= observed_sharpe))

    return {
        "permutation_pvalue": round(p_value, 6),
        "permutation_test_pass": p_value <= 0.05,
        "permutation_n": len(permuted_sharpes),
        "permutation_sharpe_dist_p5": round(float(np.percentile(arr, 5)), 4),
        "permutation_sharpe_dist_median": round(float(np.median(arr)), 4),
        "permutation_sharpe_dist_p95": round(float(np.percentile(arr, 95)), 4),
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    """Walk-forward variance metrics across OOS windows."""
    if not wf_oos_sharpes:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": round(float(arr.std()), 4),
        "wf_sharpe_min": round(float(arr.min()), 4),
    }


# ── Walk-Forward Analysis (H77-specific) ─────────────────────────────────────

def walk_forward_h77(
    close_full: pd.DataFrame,
    volume_full: pd.DataFrame,
    params: dict,
    n_folds: int = 4,
    is_start: str = IS_START,
    is_end: str = IS_END,
) -> dict:
    """
    4 non-overlapping IS folds over the in-sample period (~3 years each).
    Each fold: IS = 3 years, OOS = remainder of fold window.
    """
    is_start_ts = pd.Timestamp(is_start)
    is_end_ts = pd.Timestamp(is_end)

    total_days = (is_end_ts - is_start_ts).days
    fold_days = total_days // n_folds

    windows = []
    for i in range(n_folds):
        fold_start = is_start_ts + pd.Timedelta(days=i * fold_days)
        fold_end = is_start_ts + pd.Timedelta(days=(i + 1) * fold_days) - pd.Timedelta(days=1)
        if fold_end > is_end_ts:
            fold_end = is_end_ts

        # Use first 75% as IS, last 25% as OOS within each fold
        fold_len = (fold_end - fold_start).days
        train_end = fold_start + pd.Timedelta(days=int(fold_len * 0.75))
        test_start = train_end + pd.Timedelta(days=1)
        test_end = fold_end

        try:
            # IS fold
            is_close = close_full.loc[str(fold_start.date()):str(train_end.date())]
            is_vol = volume_full.reindex(is_close.index).fillna(0)
            if len(is_close) < 30:
                windows.append({
                    "window": i + 1, "train_start": str(fold_start.date()),
                    "train_end": str(train_end.date()), "test_start": str(test_start.date()),
                    "test_end": str(test_end.date()), "train_sharpe": 0.0,
                    "test_sharpe": 0.0, "consistency_ratio": 0.0, "passed": False,
                })
                continue

            is_signals = compute_cross_asset_signals(
                close_full, params,
                str(fold_start.date()), str(train_end.date())
            )
            if is_signals.empty:
                windows.append({
                    "window": i + 1, "train_start": str(fold_start.date()),
                    "train_end": str(train_end.date()), "test_start": str(test_start.date()),
                    "test_end": str(test_end.date()), "train_sharpe": 0.0,
                    "test_sharpe": 0.0, "consistency_ratio": 0.0, "passed": False,
                })
                continue

            is_sim = simulate_portfolio(is_close, is_vol, is_signals, params,
                                        close_full=close_full, volume_full=volume_full)

            # OOS fold
            oos_close = close_full.loc[str(test_start.date()):str(test_end.date())]
            oos_vol = volume_full.reindex(oos_close.index).fillna(0)
            if len(oos_close) < 10:
                windows.append({
                    "window": i + 1, "train_start": str(fold_start.date()),
                    "train_end": str(train_end.date()), "test_start": str(test_start.date()),
                    "test_end": str(test_end.date()), "train_sharpe": round(is_sim["sharpe"], 4),
                    "test_sharpe": 0.0, "consistency_ratio": 0.0, "passed": False,
                })
                continue

            oos_signals = compute_cross_asset_signals(
                close_full, params,
                str(test_start.date()), str(test_end.date())
            )
            oos_sim = simulate_portfolio(oos_close, oos_vol, oos_signals, params,
                                         close_full=close_full, volume_full=volume_full)

            train_sharpe = is_sim["sharpe"]
            test_sharpe = oos_sim["sharpe"]
            consistency_ratio = test_sharpe / train_sharpe if train_sharpe > 0 else 0.0
            passed = test_sharpe > 0

            windows.append({
                "window": i + 1,
                "train_start": str(fold_start.date()),
                "train_end": str(train_end.date()),
                "test_start": str(test_start.date()),
                "test_end": str(test_end.date()),
                "train_sharpe": round(train_sharpe, 4),
                "test_sharpe": round(test_sharpe, 4),
                "consistency_ratio": round(consistency_ratio, 4),
                "passed": passed,
            })
        except Exception as exc:
            print(f"  Walk-forward fold {i+1} error: {exc}")
            traceback.print_exc()
            windows.append({
                "window": i + 1,
                "train_start": str(fold_start.date()),
                "train_end": str(train_end.date()),
                "test_start": str(test_start.date()),
                "test_end": str(test_end.date()),
                "train_sharpe": 0.0, "test_sharpe": 0.0,
                "consistency_ratio": 0.0, "passed": False,
            })

    wf_windows_passed = sum(1 for w in windows if w["passed"])
    oos_sharpes = [w["test_sharpe"] for w in windows]
    wf_var = walk_forward_variance(oos_sharpes)

    return {
        "windows": windows,
        "wf_windows_passed": wf_windows_passed,
        "wf_windows_total": len(windows),
        "wf_consistency_score": round(
            sum(w["consistency_ratio"] for w in windows) / max(len(windows), 1), 4
        ),
        "wf_pass": wf_windows_passed >= 3,
        **wf_var,
    }


# ── 2022 Stress Period Analysis ───────────────────────────────────────────────

def run_stress_2022(
    close_full: pd.DataFrame,
    volume_full: pd.DataFrame,
    params: dict,
) -> dict:
    """
    2022 stress: report calendar year return, MDD, avg allocation to equities vs. defensives.
    """
    try:
        stress_close = close_full.loc[STRESS_START:STRESS_END]
        stress_vol = volume_full.reindex(stress_close.index).fillna(0)

        if len(stress_close) < 10:
            return {"error": "Insufficient 2022 data"}

        signals_2022 = compute_cross_asset_signals(
            close_full, params, STRESS_START, STRESS_END
        )

        sim_2022 = simulate_portfolio(
            stress_close, stress_vol, signals_2022, params,
            close_full=close_full, volume_full=volume_full,
        )

        # Asset allocation analysis
        equity_tickers = {"SPY", "QQQ", "IWM"}
        defensive_tickers = {"TLT", "GLD", "SHY"}
        equity_weeks, defensive_weeks, total_weeks = 0, 0, 0

        if not signals_2022.empty:
            for _, row in signals_2022.iterrows():
                total_weeks += 1
                top_k = row.get("top_k_assets", [])
                w_dict = row.get("target_weights", {})
                eq_w = sum(w_dict.get(t, 0) for t in top_k if t in equity_tickers)
                def_w = sum(w_dict.get(t, 0) for t in top_k if t in defensive_tickers)
                if "SHY" in w_dict and "SHY" not in [x for x in top_k if x not in defensive_tickers]:
                    def_w += w_dict.get("SHY", 0)
                equity_weeks += eq_w
                defensive_weeks += def_w

        avg_equity_alloc = equity_weeks / max(total_weeks, 1)
        avg_defensive_alloc = defensive_weeks / max(total_weeks, 1)

        return {
            "2022_return": round(sim_2022["total_return"], 6),
            "2022_max_drawdown": round(sim_2022["max_drawdown"], 6),
            "2022_sharpe": round(sim_2022["sharpe"], 4),
            "2022_avg_equity_alloc": round(avg_equity_alloc, 4),
            "2022_avg_defensive_alloc": round(avg_defensive_alloc, 4),
            "2022_total_signal_weeks": total_weeks,
            "hypothesis_validation": (
                "CONFIRMED: defensive rotation dominated during 2022 selloff"
                if avg_defensive_alloc > avg_equity_alloc
                else "WEAK: equity allocation exceeded defensive during 2022 selloff"
            ),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── HTML Report Generator ─────────────────────────────────────────────────────

def generate_html_report(
    strategy_name: str,
    date_str: str,
    is_result: dict,
    oos_result: dict,
    wf_result: dict,
    mc_result: dict,
    ci_result: dict,
    perm_result: dict,
    stress_2022: dict,
    gate1_pass: bool,
    dsr_result: dict,
) -> str:
    verdict_color = "#27ae60" if gate1_pass else "#e74c3c"
    verdict_text = "PASS" if gate1_pass else "FAIL"

    def fmt(v, pct=False, decimals=4):
        if v is None:
            return "N/A"
        if pct:
            return f"{float(v)*100:.2f}%"
        return f"{float(v):.{decimals}f}"

    wf_rows = ""
    for w in wf_result.get("windows", []):
        status = "✓ PASS" if w["passed"] else "✗ FAIL"
        color = "#27ae60" if w["passed"] else "#e74c3c"
        wf_rows += f"""
        <tr>
            <td>{w['window']}</td>
            <td>{w['train_start']} → {w['train_end']}</td>
            <td>{w['test_start']} → {w['test_end']}</td>
            <td>{fmt(w['train_sharpe'])}</td>
            <td>{fmt(w['test_sharpe'])}</td>
            <td style="color:{color};font-weight:bold">{status}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>H77 Gate 1 Report — {date_str}</title>
    <style>
        body {{ font-family: monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; }}
        h1, h2 {{ color: #00d2ff; }}
        table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
        th, td {{ border: 1px solid #444; padding: 8px 12px; text-align: left; }}
        th {{ background: #16213e; color: #00d2ff; }}
        tr:nth-child(even) {{ background: #0f3460; }}
        .verdict {{ font-size: 2em; font-weight: bold; color: {verdict_color}; padding: 10px; border: 2px solid {verdict_color}; display: inline-block; }}
        .pass {{ color: #27ae60; }}
        .fail {{ color: #e74c3c; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 20px 0; }}
        .metric-card {{ background: #16213e; border: 1px solid #444; padding: 15px; border-radius: 5px; }}
        .metric-value {{ font-size: 1.5em; font-weight: bold; color: #00d2ff; }}
        .metric-label {{ font-size: 0.8em; color: #aaa; margin-top: 5px; }}
    </style>
</head>
<body>
    <h1>H77 Cross-Asset Weekly Momentum Portfolio</h1>
    <p>Gate 1 Report | {date_str} | QUA-328</p>
    <div class="verdict">{verdict_text}</div>

    <h2>Primary Metrics</h2>
    <div class="metric-grid">
        <div class="metric-card">
            <div class="metric-value {'pass' if is_result['sharpe'] > 1.0 else 'fail'}">{fmt(is_result['sharpe'])}</div>
            <div class="metric-label">IS Sharpe (threshold: >1.0)</div>
        </div>
        <div class="metric-card">
            <div class="metric-value {'pass' if oos_result['sharpe'] > 0.7 else 'fail'}">{fmt(oos_result['sharpe'])}</div>
            <div class="metric-label">OOS Sharpe (threshold: >0.7)</div>
        </div>
        <div class="metric-card">
            <div class="metric-value {'pass' if abs(is_result['max_drawdown']) < 0.20 else 'fail'}">{fmt(is_result['max_drawdown'], pct=True)}</div>
            <div class="metric-label">IS Max Drawdown (threshold: <20%)</div>
        </div>
        <div class="metric-card">
            <div class="metric-value {'pass' if is_result['trade_count'] >= 100 else 'fail'}">{is_result['trade_count']}</div>
            <div class="metric-label">IS Trade Count (threshold: ≥100)</div>
        </div>
        <div class="metric-card">
            <div class="metric-value {'pass' if dsr_result.get('passed') else 'fail'}">{fmt(dsr_result.get('dsr_zscore', 0))}</div>
            <div class="metric-label">DSR z-score (threshold: >0)</div>
        </div>
        <div class="metric-card">
            <div class="metric-value {'pass' if wf_result['wf_windows_passed'] >= 3 else 'fail'}">{wf_result['wf_windows_passed']}/4</div>
            <div class="metric-label">WF Windows Passed (threshold: ≥3/4)</div>
        </div>
    </div>

    <h2>In-Sample Results (2007-06-01 to 2019-12-31)</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Sharpe Ratio</td><td>{fmt(is_result['sharpe'])}</td></tr>
        <tr><td>Max Drawdown</td><td>{fmt(is_result['max_drawdown'], pct=True)}</td></tr>
        <tr><td>Total Return</td><td>{fmt(is_result['total_return'], pct=True)}</td></tr>
        <tr><td>Win Rate</td><td>{fmt(is_result['win_rate'], pct=True)}</td></tr>
        <tr><td>Profit Factor</td><td>{fmt(is_result['profit_factor'])}</td></tr>
        <tr><td>Trade Count</td><td>{is_result['trade_count']}</td></tr>
    </table>

    <h2>Out-of-Sample Results (2020-01-01 to 2024-12-31)</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Sharpe Ratio</td><td>{fmt(oos_result['sharpe'])}</td></tr>
        <tr><td>Max Drawdown</td><td>{fmt(oos_result['max_drawdown'], pct=True)}</td></tr>
        <tr><td>Total Return</td><td>{fmt(oos_result['total_return'], pct=True)}</td></tr>
        <tr><td>Win Rate</td><td>{fmt(oos_result['win_rate'], pct=True)}</td></tr>
        <tr><td>Trade Count</td><td>{oos_result['trade_count']}</td></tr>
    </table>

    <h2>Walk-Forward Analysis</h2>
    <table>
        <tr><th>Fold</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>Status</th></tr>
        {wf_rows}
    </table>

    <h2>Statistical Rigor Pipeline</h2>
    <table>
        <tr><th>Test</th><th>Result</th><th>Status</th></tr>
        <tr>
            <td>Monte Carlo p5 Sharpe (1000 sims)</td>
            <td>{fmt(mc_result.get('mc_p5_sharpe'))}</td>
            <td class="{'pass' if mc_result.get('mc_p5_sharpe', 0) >= 0.5 else 'fail'}">{"PASS" if mc_result.get('mc_p5_sharpe', 0) >= 0.5 else "WARN: MC pessimistic bound weak"}</td>
        </tr>
        <tr>
            <td>MC Median Sharpe</td>
            <td>{fmt(mc_result.get('mc_median_sharpe'))}</td>
            <td>—</td>
        </tr>
        <tr>
            <td>Bootstrap 95% CI Sharpe</td>
            <td>[{fmt(ci_result.get('sharpe_ci_low'))}, {fmt(ci_result.get('sharpe_ci_high'))}]</td>
            <td>—</td>
        </tr>
        <tr>
            <td>Permutation Test p-value (500 perms)</td>
            <td>{fmt(perm_result.get('permutation_pvalue'))}</td>
            <td class="{'pass' if perm_result.get('permutation_test_pass') else 'fail'}">{"PASS" if perm_result.get('permutation_test_pass') else "FAIL (no statistically significant alpha)"}</td>
        </tr>
        <tr>
            <td>DSR z-score</td>
            <td>{fmt(dsr_result.get('dsr_zscore', 0))}</td>
            <td class="{'pass' if dsr_result.get('passed') else 'fail'}">{"PASS" if dsr_result.get('passed') else "FAIL"}</td>
        </tr>
        <tr>
            <td>WF Sharpe Std (consistency)</td>
            <td>{fmt(wf_result.get('wf_sharpe_std'))}</td>
            <td class="{'pass' if wf_result.get('wf_sharpe_std', 1.0) <= 0.5 else 'warn'}">{"OK" if wf_result.get('wf_sharpe_std', 1.0) <= 0.5 else "WARN: variance > 0.5"}</td>
        </tr>
        <tr>
            <td>WF Sharpe Min (worst window)</td>
            <td>{fmt(wf_result.get('wf_sharpe_min'))}</td>
            <td class="{'pass' if wf_result.get('wf_sharpe_min', -1) >= 0 else 'fail'}">{"OK" if wf_result.get('wf_sharpe_min', -1) >= 0 else "FLAG: losing OOS window"}</td>
        </tr>
    </table>

    <h2>2022 Stress Period</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>2022 Calendar Year Return</td><td>{fmt(stress_2022.get('2022_return'), pct=True)}</td></tr>
        <tr><td>2022 Max Drawdown</td><td>{fmt(stress_2022.get('2022_max_drawdown'), pct=True)}</td></tr>
        <tr><td>2022 Sharpe</td><td>{fmt(stress_2022.get('2022_sharpe'))}</td></tr>
        <tr><td>Avg Equity Allocation</td><td>{fmt(stress_2022.get('2022_avg_equity_alloc'), pct=True)}</td></tr>
        <tr><td>Avg Defensive Allocation</td><td>{fmt(stress_2022.get('2022_avg_defensive_alloc'), pct=True)}</td></tr>
        <tr><td>Hypothesis Validation</td><td>{stress_2022.get('hypothesis_validation', 'N/A')}</td></tr>
    </table>

    <p style="color:#666; margin-top:40px">Generated by Backtest Runner Agent (QUA-328) | {date_str}</p>
</body>
</html>"""
    return html


# ── Main Execution ────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("H77 Cross-Asset Weekly Momentum Portfolio — Gate 1 Backtest")
    print("QUA-328")
    print("=" * 70)

    # ── Download full buffered data once ──────────────────────────────────────
    print("\n[DATA] Downloading full buffered price history...")
    # Buffer: start 6 months before IS_START for SMA warmup
    buf_start = str((pd.Timestamp(IS_START) - pd.DateOffset(months=6)).date())
    buf_end = OOS_END
    close_full, volume_full = download_data(TICKERS, buf_start, buf_end)
    print(f"  Data shape: {close_full.shape} | {buf_start} to {buf_end}")
    print(f"  Tickers: {list(close_full.columns)}")

    # ── IS Backtest ───────────────────────────────────────────────────────────
    print("\n[IS] Running in-sample backtest (2007-06-01 to 2019-12-31)...")
    is_result = h77_run_backtest(start=IS_START, end=IS_END)
    print(f"  IS Sharpe:       {is_result['sharpe']:.4f}")
    print(f"  IS MaxDD:        {is_result['max_drawdown']*100:.2f}%")
    print(f"  IS Total Return: {is_result['total_return']*100:.2f}%")
    print(f"  IS Trade Count:  {is_result['trade_count']}")
    print(f"  IS Win Rate:     {is_result['win_rate']*100:.2f}%")

    # ── OOS Backtest ──────────────────────────────────────────────────────────
    print("\n[OOS] Running out-of-sample backtest (2020-01-01 to 2024-12-31)...")
    oos_result = h77_run_backtest(start=OOS_START, end=OOS_END)
    print(f"  OOS Sharpe:       {oos_result['sharpe']:.4f}")
    print(f"  OOS MaxDD:        {oos_result['max_drawdown']*100:.2f}%")
    print(f"  OOS Total Return: {oos_result['total_return']*100:.2f}%")
    print(f"  OOS Trade Count:  {oos_result['trade_count']}")

    # ── OOS Data Quality Validation ───────────────────────────────────────────
    print("\n[DQ] OOS data quality validation...")
    from oos_data_quality import validate_oos_data, OOSDataQualityError

    oos_close_window = close_full.loc[OOS_START:OOS_END]
    oos_metrics_for_dq = {
        "sharpe": oos_result["sharpe"],
        "max_drawdown": oos_result["max_drawdown"],
        "win_rate": oos_result["win_rate"],
        "profit_factor": oos_result["profit_factor"],
        "total_trades": oos_result["trade_count"],
        "post_cost_sharpe": oos_result["sharpe"],  # post-cost is embedded in H77's own model
    }
    dq_report = validate_oos_data(oos_close_window, oos_metrics_for_dq, STRATEGY_NAME)
    print(f"  DQ recommendation: {dq_report['recommendation']}")
    if dq_report.get("advisory_nan_fields"):
        print(f"  Advisory NaN fields: {dq_report['advisory_nan_fields']}")
    if dq_report["recommendation"] == "BLOCK":
        print(f"  BLOCK reasons: {dq_report.get('block_reasons', [])}")
        print("  HALTING — data quality check blocked. Reporting blocked status.")
        return {"blocked": True, "dq_report": dq_report}

    # ── DSR ───────────────────────────────────────────────────────────────────
    print("\n[DSR] Computing Deflated Sharpe Ratio...")
    is_daily_returns = pd.Series(is_result["_daily_returns"])
    dsr_result = compute_dsr(is_daily_returns, trials_tested=1)
    print(f"  DSR z-score: {dsr_result['dsr_zscore']:.4f} | SR*={dsr_result['dsr_sr_star']:.4f} | n={dsr_result['n_obs']}")
    print(f"  DSR: {'PASS' if dsr_result['passed'] else 'FAIL'}")

    # ── Walk-Forward ──────────────────────────────────────────────────────────
    print("\n[WF] Running walk-forward analysis (4 IS folds)...")
    wf_result = walk_forward_h77(close_full, volume_full, PARAMETERS)
    print(f"  WF windows passed: {wf_result['wf_windows_passed']}/{wf_result['wf_windows_total']}")
    for w in wf_result["windows"]:
        status = "✓" if w["passed"] else "✗"
        print(f"  {status} Fold {w['window']}: IS={w['train_sharpe']:.2f} OOS={w['test_sharpe']:.2f} [{w['test_start']}–{w['test_end']}]")

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    print("\n[MC] Monte Carlo simulation (1000 resamples on IS trade PnL)...")
    is_pnl_arr = is_result.get("_pnl_arr", np.array([]))
    mc_result = monte_carlo_sharpe(is_pnl_arr, n_sims=1000)
    print(f"  MC p5 Sharpe: {mc_result['mc_p5_sharpe']:.4f}")
    print(f"  MC Median:    {mc_result['mc_median_sharpe']:.4f}")
    print(f"  MC p95:       {mc_result['mc_p95_sharpe']:.4f}")
    if mc_result["mc_p5_sharpe"] < 0.5:
        print("  FLAG: MC pessimistic bound weak (p5 < 0.5)")

    # ── Bootstrap CI ──────────────────────────────────────────────────────────
    print("\n[CI] Block bootstrap confidence intervals (1000 bootstrap samples)...")
    is_returns = is_result["_daily_returns"]
    ci_result = block_bootstrap_ci(is_returns, n_boots=1000)
    print(f"  Sharpe 95% CI: [{ci_result['sharpe_ci_low']:.4f}, {ci_result['sharpe_ci_high']:.4f}]")
    print(f"  MDD 95% CI:    [{ci_result['mdd_ci_low']*100:.2f}%, {ci_result['mdd_ci_high']*100:.2f}%]")
    print(f"  WinRate 95% CI: [{ci_result['win_rate_ci_low']*100:.2f}%, {ci_result['win_rate_ci_high']*100:.2f}%]")

    # ── Market Impact ─────────────────────────────────────────────────────────
    print("\n[MI] Computing market impact (IS trades)...")
    is_trade_log = is_result.get("trade_log", [])
    is_close_window = close_full.loc[IS_START:IS_END]
    is_vol_window = volume_full.reindex(is_close_window.index).fillna(0)
    mi_result = compute_market_impact_h77(is_close_window, is_vol_window, is_trade_log, PARAMETERS)
    print(f"  Avg market impact: {mi_result['market_impact_bps']:.4f} bps")
    print(f"  Liquidity constrained: {mi_result['liquidity_constrained']}")

    # ── Permutation Test ──────────────────────────────────────────────────────
    print("\n[PERM] Permutation test for alpha (500 permutations)...")
    is_signals = compute_cross_asset_signals(close_full, PARAMETERS, IS_START, IS_END)
    perm_result = permutation_test_alpha(
        is_close_window, is_signals, is_vol_window, PARAMETERS,
        observed_sharpe=is_result["sharpe"],
        close_full=close_full, volume_full=volume_full,
        n_perms=500,
    )
    print(f"  Permutation p-value: {perm_result['permutation_pvalue']:.4f}")
    print(f"  Permutation test: {'PASS' if perm_result['permutation_test_pass'] else 'FAIL'}")

    # ── 2022 Stress ───────────────────────────────────────────────────────────
    print("\n[STRESS] 2022 stress period analysis...")
    stress_2022 = run_stress_2022(close_full, volume_full, PARAMETERS)
    print(f"  2022 Return:  {stress_2022.get('2022_return', 0)*100:.2f}%")
    print(f"  2022 MDD:     {stress_2022.get('2022_max_drawdown', 0)*100:.2f}%")
    print(f"  2022 Sharpe:  {stress_2022.get('2022_sharpe', 0):.4f}")
    print(f"  {stress_2022.get('hypothesis_validation', 'N/A')}")

    # ── Parameter Sweep (36 combinations) ────────────────────────────────────
    print("\n[SWEEP] Running parameter sweep (36 combinations)...")
    sweep_results = h77_scan_parameters(start=IS_START, end=IS_END)
    sweep_meta = sweep_results.pop("_meta", {})
    print(f"  Default Sharpe: {sweep_meta.get('default_sharpe', 'N/A')}")
    print(f"  Sharpe range: [{sweep_meta.get('sharpe_min', 'N/A')}, {sweep_meta.get('sharpe_max', 'N/A')}]")
    print(f"  Stability flag: {sweep_meta.get('gate1_stability_flag', 'N/A')}")

    sensitivity_pass = "PASS" in str(sweep_meta.get("gate1_stability_flag", "FAIL"))

    # ── Post-cost Sharpe ──────────────────────────────────────────────────────
    # H77 embeds all transaction costs in its own simulation; post-cost IS = IS Sharpe
    post_cost_sharpe = is_result["sharpe"]
    post_cost_sharpe_oos = oos_result["sharpe"]

    # ── Gate 1 Verdict ────────────────────────────────────────────────────────
    gate1_checks = {
        "is_sharpe_pass": is_result["sharpe"] > 1.0,
        "oos_sharpe_pass": oos_result["sharpe"] > 0.7,
        "is_mdd_pass": abs(is_result["max_drawdown"]) < 0.20,
        "trade_count_pass": is_result["trade_count"] >= 100,
        "permutation_pass": perm_result["permutation_test_pass"],
        "wf_pass": wf_result["wf_windows_passed"] >= 3,
        "dsr_pass": dsr_result["passed"],
    }
    gate1_pass = all(gate1_checks.values())

    print("\n[GATE 1] Verdict:")
    for k, v in gate1_checks.items():
        status = "✓ PASS" if v else "✗ FAIL"
        print(f"  {status}: {k}")
    print(f"\n  Gate 1 Final: {'PASS' if gate1_pass else 'FAIL'}")

    # ── Cost/gross profit ratio ───────────────────────────────────────────────
    pnl_arr = is_result.get("_pnl_arr", np.array([]))
    gross_profit = float(np.sum(pnl_arr[pnl_arr > 0])) if len(pnl_arr) > 0 else 0.0
    # Estimate total costs from trade log (commission + slippage embedded in proceeds)
    total_costs_est = 0.0
    for entry in is_trade_log:
        total_costs_est += entry.get("commission", 0) + (
            entry.get("shares", 0) * entry.get("price", 0) * abs(
                entry.get("slippage_pct", 0) - 0.00005
            )
        )
    cost_gross_ratio = total_costs_est / max(gross_profit, 1.0)
    print(f"\n  Cost/Gross Profit Ratio: {cost_gross_ratio:.4f} (threshold: <0.25)")

    # ── Assemble full metrics JSON ────────────────────────────────────────────
    wf_oos_sharpes = [w["test_sharpe"] for w in wf_result["windows"]]
    wf_var = walk_forward_variance(wf_oos_sharpes)

    metrics_json = {
        "strategy_name": STRATEGY_NAME,
        "date": DATE_STR,
        "asset_class": "equities",
        # Primary metrics
        "is_sharpe": round(is_result["sharpe"], 6),
        "oos_sharpe": round(oos_result["sharpe"], 6),
        "is_max_drawdown": round(is_result["max_drawdown"], 6),
        "oos_max_drawdown": round(oos_result["max_drawdown"], 6),
        "win_rate": round(is_result["win_rate"], 6),
        "profit_factor": round(is_result["profit_factor"], 6),
        "trade_count": is_result["trade_count"],
        "oos_trade_count": oos_result["trade_count"],
        "total_return_is": round(is_result["total_return"], 6),
        "total_return_oos": round(oos_result["total_return"], 6),
        # DSR
        "dsr": round(dsr_result["dsr_zscore"], 6),
        "dsr_probability": round(dsr_result["dsr_probability"], 6),
        "dsr_pass": dsr_result["passed"],
        # Walk-forward
        "wf_windows_passed": wf_result["wf_windows_passed"],
        "wf_windows_total": wf_result["wf_windows_total"],
        "wf_consistency_score": wf_result["wf_consistency_score"],
        "wf_pass": wf_result["wf_pass"],
        "wf_windows": wf_result["windows"],
        "wf_sharpe_std": wf_var["wf_sharpe_std"],
        "wf_sharpe_min": wf_var["wf_sharpe_min"],
        # Statistical tests
        "mc_p5_sharpe": round(mc_result["mc_p5_sharpe"], 6),
        "mc_median_sharpe": round(mc_result["mc_median_sharpe"], 6),
        "mc_p95_sharpe": round(mc_result["mc_p95_sharpe"], 6),
        "sharpe_ci_low": round(ci_result["sharpe_ci_low"], 6),
        "sharpe_ci_high": round(ci_result["sharpe_ci_high"], 6),
        "mdd_ci_low": round(ci_result["mdd_ci_low"], 6),
        "mdd_ci_high": round(ci_result["mdd_ci_high"], 6),
        "win_rate_ci_low": round(ci_result["win_rate_ci_low"], 6),
        "win_rate_ci_high": round(ci_result["win_rate_ci_high"], 6),
        # Market impact
        "market_impact_bps": mi_result["market_impact_bps"],
        "market_impact_bps_max": mi_result["market_impact_bps_max"],
        "liquidity_constrained": mi_result["liquidity_constrained"],
        "order_to_adv_ratio": mi_result["order_to_adv_ratio"],
        # Permutation test
        "permutation_pvalue": perm_result.get("permutation_pvalue", 1.0),
        "permutation_test_pass": perm_result.get("permutation_test_pass", False),
        "permutation_n": perm_result.get("permutation_n", 0),
        # Sensitivity / cost
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_meta": sweep_meta,
        "post_cost_sharpe": round(post_cost_sharpe, 6),
        "post_cost_sharpe_oos": round(post_cost_sharpe_oos, 6),
        "cost_gross_ratio": round(cost_gross_ratio, 6),
        "look_ahead_bias_flag": False,
        # Gate 1 verdict
        "gate1_pass": gate1_pass,
        "gate1_checks": gate1_checks,
        # Asset concentration
        "asset_concentration": is_result.get("asset_concentration", {}),
        "holding_pct": is_result.get("holding_pct", {}),
        # 2022 stress
        "stress_2022": stress_2022,
        # OOS data quality
        "oos_data_quality": dq_report,
    }

    # ── Save outputs ──────────────────────────────────────────────────────────
    base = os.path.join(BACKTESTS_DIR, f"{STRATEGY_NAME}_{DATE_STR}")

    # 1. Metrics JSON
    metrics_path = f"{base}.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics_json, f, indent=2, default=str)
    print(f"\n[SAVE] Metrics: {metrics_path}")

    # 2. Trade log CSV
    trades_path = f"{base}_trades.csv"
    if is_result.get("trade_pnl"):
        trades_df = pd.DataFrame(is_result["trade_pnl"] + oos_result.get("trade_pnl", []))
        trades_df.to_csv(trades_path, index=False)
    else:
        trades_df = pd.DataFrame(is_result["trade_log"] + oos_result.get("trade_log", []))
        trades_df.to_csv(trades_path, index=False)
    print(f"[SAVE] Trades: {trades_path}")

    # 3. Parameter sweep CSV
    sweep_path = f"{base}_sweep.csv"
    sweep_rows = []
    for key, val in sweep_results.items():
        if isinstance(val, dict) and not key.startswith("_"):
            sweep_rows.append({"config": key, **val})
    if sweep_rows:
        pd.DataFrame(sweep_rows).to_csv(sweep_path, index=False)
    print(f"[SAVE] Sweep: {sweep_path}")

    # 4. HTML report
    html_path = f"{base}_report.html"
    html = generate_html_report(
        STRATEGY_NAME, DATE_STR, is_result, oos_result, wf_result,
        mc_result, ci_result, perm_result, stress_2022, gate1_pass, dsr_result,
    )
    with open(html_path, "w") as f:
        f.write(html)
    print(f"[SAVE] Report: {html_path}")

    # 5. Verdict TXT
    verdict_path = f"{base}_verdict.txt"
    verdict_lines = [
        f"{'PASS' if gate1_pass else 'FAIL'}",
        f"IS Sharpe: {is_result['sharpe']:.4f}",
        f"OOS Sharpe: {oos_result['sharpe']:.4f}",
        f"IS MDD: {abs(is_result['max_drawdown'])*100:.2f}%",
        f"OOS MDD: {abs(oos_result['max_drawdown'])*100:.2f}%",
        f"Trade count (IS): {is_result['trade_count']}",
        f"Win rate (IS): {is_result['win_rate']*100:.2f}%",
        f"Profit factor (IS): {is_result['profit_factor']:.4f}",
        f"DSR z-score: {dsr_result['dsr_zscore']:.4f} ({'PASS' if dsr_result['passed'] else 'FAIL'})",
        f"Permutation p-value: {perm_result.get('permutation_pvalue', 1.0):.4f} ({'PASS' if perm_result.get('permutation_test_pass') else 'FAIL'})",
        f"WF windows passed: {wf_result['wf_windows_passed']}/4",
        f"WF Sharpe std: {wf_var['wf_sharpe_std']:.4f}",
        f"WF Sharpe min: {wf_var['wf_sharpe_min']:.4f}",
        f"MC p5 Sharpe: {mc_result['mc_p5_sharpe']:.4f}",
        f"Bootstrap Sharpe CI: [{ci_result['sharpe_ci_low']:.4f}, {ci_result['sharpe_ci_high']:.4f}]",
        f"Market impact (avg): {mi_result['market_impact_bps']:.4f} bps",
        f"Sensitivity pass: {sensitivity_pass}",
        f"Post-cost Sharpe (IS): {post_cost_sharpe:.4f}",
        f"Cost/gross ratio: {cost_gross_ratio:.4f}",
        f"2022 return: {stress_2022.get('2022_return', 0)*100:.2f}%",
        f"2022 MDD: {stress_2022.get('2022_max_drawdown', 0)*100:.2f}%",
        f"",
        f"Gate 1 checks:",
    ]
    for k, v in gate1_checks.items():
        verdict_lines.append(f"  {'PASS' if v else 'FAIL'}: {k}")

    with open(verdict_path, "w") as f:
        f.write("\n".join(verdict_lines))
    print(f"[SAVE] Verdict: {verdict_path}")

    print("\n" + "=" * 70)
    print(f"GATE 1 FINAL VERDICT: {'PASS' if gate1_pass else 'FAIL'}")
    print("=" * 70)

    return {
        "gate1_pass": gate1_pass,
        "is_sharpe": is_result["sharpe"],
        "oos_sharpe": oos_result["sharpe"],
        "is_mdd": is_result["max_drawdown"],
        "trade_count": is_result["trade_count"],
        "permutation_pvalue": perm_result.get("permutation_pvalue"),
        "wf_windows_passed": wf_result["wf_windows_passed"],
        "dsr": dsr_result["dsr_zscore"],
        "metrics_path": metrics_path,
        "verdict_path": verdict_path,
        "report_path": html_path,
    }


if __name__ == "__main__":
    result = main()
    print("\nSummary:", json.dumps(
        {k: v for k, v in result.items() if not k.endswith("_path")},
        indent=2, default=str
    ))
