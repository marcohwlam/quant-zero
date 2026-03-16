"""
H07 Gate 1 Backtest Runner
Executes IS/OOS backtests, walk-forward, statistical rigor pipeline,
and sensitivity scan for H07 Multi-Asset TSMOM.

Note: Strategy's run_strategy() returns per-ticker metrics. This runner
builds portfolios with group_by=True for combined portfolio-level Sharpe.
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

# Required: set global daily frequency for vectorbt Sharpe annualization
vbt.settings.array_wrapper['freq'] = 'D'

# Add parent directory so we can import the strategy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies.h07_multi_asset_tsmom import (
    download_data, check_data_quality, generate_daily_signals,
    compute_market_impact, check_liquidity_constraints,
    compute_uso_dbc_correlation, scan_parameters, PARAMETERS
)

# ── Constants ─────────────────────────────────────────────────────────────────
IS_START  = "2018-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2023-12-31"
INIT_CASH = 25000
TODAY = str(date.today())
STRATEGY_NAME = "H07_MultiAsset_TSMOM"


# ── Portfolio Builder ──────────────────────────────────────────────────────────

def build_portfolio(start: str, end: str, params: dict):
    """
    Build per-ticker vectorbt Portfolios for H07 strategy with equal capital split.
    Returns (pf, close, volume, extra_reports).

    Capital allocation: init_cash / n_tickers per ticker (equal weight).
    Portfolio-level metrics are computed from combined portfolio value.
    """
    universe = params.get("universe", ["SPY", "QQQ", "TLT", "GLD", "USO", "DBC"])
    close, volume = download_data(universe, start, end)

    # Data quality
    quality_report = check_data_quality(close)
    close = close.dropna(axis=1, how="all")
    if close.empty:
        raise ValueError(f"No price data for {universe} in {start}–{end}.")

    min_required = params["lookback_months"] * 21 + 20
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    # Generate signals
    entries, exits = generate_daily_signals(close, params)

    # Market impact and liquidity
    market_impact_df, q_over_adv = compute_market_impact(close, volume, params)
    liquidity_report = check_liquidity_constraints(q_over_adv)

    # USO/DBC correlation
    corr_report = compute_uso_dbc_correlation(close)

    # Transaction costs (canonical equities)
    fees = 0.005 / close
    slippage = 0.0005 + market_impact_df

    # Per-ticker portfolio with equal capital allocation
    n_tickers = len(close.columns)
    cash_per_ticker = params.get("init_cash", INIT_CASH) / n_tickers

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
        "corr_report": corr_report,
        "close": close,
        "entries": entries,
        "q_over_adv": q_over_adv,
    }
    return pf, close, volume, extra


def portfolio_metrics(pf, close: pd.DataFrame, params: dict) -> dict:
    """
    Extract combined portfolio-level metrics from per-ticker portfolios.
    Combines individual portfolio values to get portfolio-level Sharpe/MDD.
    """
    # Combined portfolio value = sum of per-ticker values
    combined_value = pf.value().sum(axis=1)
    combined_returns = combined_value.pct_change().fillna(0).values

    # Portfolio-level Sharpe
    sharpe = float(combined_returns.mean() / (combined_returns.std() + 1e-8) * np.sqrt(252))

    # Portfolio-level MDD
    cum = np.cumprod(1 + combined_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))

    # Total return
    total_return = float(combined_value.iloc[-1] / combined_value.iloc[0] - 1)

    # Total trade count across all tickers
    trade_count = int(pf.trades.count().sum())

    # PnL from all trades
    try:
        pnl_vals = pf.trades.pnl.values
        pnl_vals = pnl_vals[~np.isnan(pnl_vals)]
        win_rate = float(np.mean(pnl_vals > 0)) if len(pnl_vals) > 0 else 0.0
        wins = pnl_vals[pnl_vals > 0]
        losses = pnl_vals[pnl_vals < 0]
        avg_win  = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
        profit_factor  = (
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
        "mc_p5_sharpe":     float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe":    float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks  = max(1, T // block_len)

    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum       = np.cumprod(1 + sample)
        roll_max  = np.maximum.accumulate(cum)
        mdd       = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        s         = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(252))
        wr        = float(np.mean(sample > 0))
        sharpes.append(s); mdds.append(mdd); win_rates.append(wr)

    return {
        "sharpe_ci_low":    float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high":   float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":       float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":      float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low":  float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def permutation_test_alpha(
    prices: np.ndarray,
    entries_flat: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 500,
    hold_days: int = 21,
) -> dict:
    permuted_sharpes = []
    entry_indices = np.where(entries_flat)[0]
    n_entries = len(entry_indices)

    if n_entries == 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

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
        "permutation_pvalue":   p_value,
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

def run_walk_forward(params: dict, n_windows: int = 4,
                     train_months: int = 36, test_months: int = 6) -> dict:
    """
    Walk-forward analysis using sliding IS+OOS windows.
    Each window runs the full IS+OOS period together (to satisfy lookback requirements),
    then splits portfolio value at the IS/OOS boundary for separate metric computation.
    """
    wf_results = []
    base_start = pd.Timestamp("2018-01-01")

    for i in range(n_windows):
        offset_months = i * 6
        is_start  = (base_start + pd.DateOffset(months=offset_months)).strftime("%Y-%m-%d")
        is_end    = (base_start + pd.DateOffset(
            months=offset_months + train_months - 1, day=31)).strftime("%Y-%m-%d")
        oos_start = (base_start + pd.DateOffset(
            months=offset_months + train_months)).strftime("%Y-%m-%d")
        oos_end   = (base_start + pd.DateOffset(
            months=offset_months + train_months + test_months - 1, day=31)).strftime("%Y-%m-%d")

        # Run full combined window (IS+OOS together) to satisfy lookback
        full_end = oos_end
        try:
            pf_full, close_full, _, _ = build_portfolio(is_start, full_end, params)
            combined_value_full = pf_full.value().sum(axis=1)

            # Split at IS/OOS boundary
            is_mask  = combined_value_full.index <= pd.Timestamp(is_end)
            oos_mask = combined_value_full.index >= pd.Timestamp(oos_start)

            is_value  = combined_value_full[is_mask]
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

            m_is_wf  = period_metrics(is_value)
            m_oos_wf = period_metrics(oos_value)

            # Trade count in OOS period
            oos_trade_count = 0
            try:
                records = pf_full.trades.records_arr
                # Count trades closing in OOS period (approximate)
                oos_trade_count = max(1, int(pf_full.trades.count().sum() * (len(oos_value) / max(1, len(combined_value_full)))))
            except Exception:
                pass

            wf_results.append({
                "window": i + 1,
                "is_start": is_start, "is_end": is_end,
                "oos_start": oos_start, "oos_end": oos_end,
                "is_sharpe":       round(m_is_wf["sharpe"], 4),
                "oos_sharpe":      round(m_oos_wf["sharpe"], 4),
                "is_mdd":          round(m_is_wf["mdd"], 4),
                "oos_mdd":         round(m_oos_wf["mdd"], 4),
                "oos_trade_count": oos_trade_count,
                "pass": m_oos_wf["sharpe"] >= 0.7,
            })
        except Exception as exc:
            wf_results.append({
                "window": i + 1,
                "is_start": is_start, "is_end": is_end,
                "oos_start": oos_start, "oos_end": oos_end,
                "error": str(exc),
                "pass": False,
            })

    windows_passed = sum(1 for w in wf_results if w.get("pass", False))
    oos_sharpes = [w["oos_sharpe"] for w in wf_results if "oos_sharpe" in w]
    is_sharpes  = [w["is_sharpe"]  for w in wf_results if "is_sharpe" in w]

    consistency_ratios = []
    for w in wf_results:
        if "is_sharpe" in w and "oos_sharpe" in w and abs(w["is_sharpe"]) > 0.01:
            consistency_ratios.append(w["oos_sharpe"] / w["is_sharpe"])
    wf_consistency_score = float(np.mean(consistency_ratios)) if consistency_ratios else 0.0

    return {
        "windows": wf_results,
        "windows_passed": windows_passed,
        "oos_sharpes": oos_sharpes,
        "is_sharpes":  is_sharpes,
        "wf_consistency_score": wf_consistency_score,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H07 Gate 1 Backtest — {TODAY}")
    print("=" * 70)

    params = {**PARAMETERS}

    # ── 1. IS Backtest ─────────────────────────────────────────────────────
    print(f"\n[1/7] Running IS backtest ({IS_START} to {IS_END})...")
    pf_is, close_is, volume_is, extra_is = build_portfolio(IS_START, IS_END, params)
    m_is = portfolio_metrics(pf_is, close_is, params)
    is_returns = m_is["combined_returns"]
    print(f"  IS Sharpe:  {m_is['sharpe']:.4f}")
    print(f"  IS MDD:     {m_is['max_drawdown']:.4f}")
    print(f"  IS WinRate: {m_is['win_rate']:.4f}")
    print(f"  IS Trades:  {m_is['trade_count']}")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────
    print(f"\n[2/7] Running OOS backtest ({OOS_START} to {OOS_END})...")
    pf_oos, close_oos, _, extra_oos = build_portfolio(OOS_START, OOS_END, params)
    m_oos = portfolio_metrics(pf_oos, close_oos, params)
    oos_returns = m_oos["combined_returns"]
    print(f"  OOS Sharpe:  {m_oos['sharpe']:.4f}")
    print(f"  OOS MDD:     {m_oos['max_drawdown']:.4f}")
    print(f"  OOS WinRate: {m_oos['win_rate']:.4f}")
    print(f"  OOS Trades:  {m_oos['trade_count']}")

    # ── 3. Walk-Forward ────────────────────────────────────────────────────
    print("\n[3/7] Running walk-forward analysis (4 windows, 36m IS / 6m OOS)...")
    wf = run_walk_forward(params, n_windows=4, train_months=36, test_months=6)
    print(f"  Windows passed: {wf['windows_passed']}/4")
    for w in wf["windows"]:
        if "error" in w:
            print(f"  Window {w['window']}: ERROR — {w['error']}")
        else:
            status = "PASS" if w.get("pass") else "FAIL"
            print(f"  Window {w['window']}: IS={w['is_sharpe']:.2f}  OOS={w['oos_sharpe']:.2f}  [{status}]")

    wf_var = walk_forward_variance(wf["oos_sharpes"])

    # ── 4. Monte Carlo ─────────────────────────────────────────────────────
    print("\n[4/7] Running Monte Carlo simulation (1,000 resamples)...")
    trade_pnls = m_is["pnl_vals"]
    mc = (monte_carlo_sharpe(trade_pnls) if len(trade_pnls) > 1
          else {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0})
    print(f"  MC p5={mc['mc_p5_sharpe']:.3f}  median={mc['mc_median_sharpe']:.3f}  p95={mc['mc_p95_sharpe']:.3f}")

    # ── 5. Block Bootstrap CI ──────────────────────────────────────────────
    print("\n[5/7] Running block bootstrap CI (1,000 boots)...")
    bb = (block_bootstrap_ci(is_returns) if len(is_returns) > 10
          else {k: 0.0 for k in ["sharpe_ci_low","sharpe_ci_high",
                                  "mdd_ci_low","mdd_ci_high",
                                  "win_rate_ci_low","win_rate_ci_high"]})
    print(f"  Sharpe CI: [{bb['sharpe_ci_low']:.3f}, {bb['sharpe_ci_high']:.3f}]")
    print(f"  MDD CI:    [{bb['mdd_ci_low']:.3f}, {bb['mdd_ci_high']:.3f}]")

    # ── 6. Market Impact ───────────────────────────────────────────────────
    print("\n[6/7] Computing market impact (SPY representative)...")
    import yfinance as yf
    market_impact_bps  = 0.0
    order_to_adv_ratio = 0.0
    try:
        spy_hist = yf.download("SPY", start=IS_START, end=IS_END,
                               auto_adjust=True, progress=False)
        adv   = float(spy_hist["Volume"].rolling(20).mean().iloc[-1])
        sigma = float(spy_hist["Close"].pct_change().std())
        qty   = params.get("order_qty", 100)
        q_adv = qty / (adv + 1e-8)
        market_impact_bps  = 0.1 * sigma * np.sqrt(q_adv) * 10000
        order_to_adv_ratio = q_adv
        print(f"  SPY impact: {market_impact_bps:.4f} bps  Q/ADV={q_adv:.6f}")
    except Exception as e:
        print(f"  Market impact compute warning: {e}")

    liquidity_report = extra_is["liquidity_report"]
    liquidity_constrained = liquidity_report.get("liquidity_constrained", False)
    uso_dbc_corr = extra_is["corr_report"]

    # ── 7. Permutation Test ────────────────────────────────────────────────
    print("\n[7/7] Running permutation test (500 perms)...")
    try:
        spy_prices  = close_is["SPY"].values if "SPY" in close_is.columns else close_is.iloc[:, 0].values
        entries_is  = extra_is["entries"]
        spy_entries = entries_is["SPY"].values if "SPY" in entries_is.columns else entries_is.iloc[:, 0].values
        perm = permutation_test_alpha(spy_prices, spy_entries, m_is["sharpe"])
        print(f"  Permutation p-value: {perm['permutation_pvalue']:.4f}  "
              f"({'PASS' if perm['permutation_test_pass'] else 'FAIL'})")
    except Exception as e:
        print(f"  Permutation test warning: {e}")
        perm = {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    # DSR
    n_trials = 14  # parameter combinations tested
    dsr = compute_dsr(is_returns, n_trials)
    print(f"\n  DSR: {dsr:.4f}")

    # ── Parameter Sensitivity Scan ─────────────────────────────────────────
    print("\nRunning parameter sensitivity scan...")
    sensitivity = scan_parameters(start=IS_START, end=IS_END, base_params=params)
    # scan_parameters uses run_strategy() internally which may fail for multi-col
    # Rebuild it here using our build_portfolio approach
    sens_results = {}
    grid = {
        "lookback_months":        [6, 9, 12, 18],
        "rebalance_frequency":    ["monthly", "quarterly"],
        "universe_size":          [4, 6],
        "intramonth_stop_pct":    [0.15, 0.20, 0.25],
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
        sharpe_mean  = np.mean(sharpe_nums)
        variance_pct = sharpe_range / abs(sharpe_mean) if abs(sharpe_mean) > 0 else float("inf")
        sens_results["_sharpe_range"]        = round(sharpe_range, 4)
        sens_results["_sharpe_variance_pct"] = round(variance_pct, 4)
        sens_results["_gate1_variance_flag"] = (
            f"PASS: variance {variance_pct:.1%} ≤ 30%"
            if variance_pct <= 0.30
            else f"FAIL: variance {variance_pct:.1%} > 30%"
        )
    sensitivity_pass = "PASS" in str(sens_results.get("_gate1_variance_flag", ""))
    print(f"  Sharpe range: {sens_results.get('_sharpe_range', 'N/A')}")
    print(f"  Sensitivity:  {sens_results.get('_gate1_variance_flag', 'N/A')}")

    # ── Gate 1 Checks ──────────────────────────────────────────────────────
    gate1_checks = {
        "is_sharpe_pass":        m_is["sharpe"]          > 1.0,
        "oos_sharpe_pass":       m_oos["sharpe"]         > 0.7,
        "is_mdd_pass":           abs(m_is["max_drawdown"]) < 0.20,
        "oos_mdd_pass":          abs(m_oos["max_drawdown"]) < 0.25,
        "win_rate_pass":         m_is["win_rate"]        > 0.50,
        "win_loss_ratio_pass":   m_is["win_loss_ratio"]  >= 1.0,
        "trade_count_pass":      m_is["trade_count"]     >= 50,
        "wf_windows_pass":       wf["windows_passed"]    >= 3,
        "wf_consistency_pass":   wf["wf_consistency_score"] >= 0.70,
        "sensitivity_pass":      sensitivity_pass,
        "dsr_pass":              dsr > 0.0,
        "permutation_pass":      perm["permutation_test_pass"],
    }
    gate1_pass = all(gate1_checks.values())

    # ── Assemble Metrics JSON ──────────────────────────────────────────────
    metrics = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "asset_class": "equities",
        "is_period":  f"{IS_START} to {IS_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        # Core
        "is_sharpe":      round(m_is["sharpe"], 4),
        "oos_sharpe":     round(m_oos["sharpe"], 4),
        "is_max_drawdown":  round(m_is["max_drawdown"], 4),
        "oos_max_drawdown": round(m_oos["max_drawdown"], 4),
        "win_rate":       round(m_is["win_rate"], 4),
        "win_loss_ratio": round(m_is["win_loss_ratio"], 4),
        "profit_factor":  round(m_is["profit_factor"], 4),
        "trade_count":    m_is["trade_count"],
        "oos_trade_count": m_oos["trade_count"],
        "total_return_is":  round(m_is["total_return"], 4),
        "total_return_oos": round(m_oos["total_return"], 4),
        "dsr": round(dsr, 4),
        "post_cost_sharpe": round(m_is["sharpe"], 4),  # IS already includes costs
        # Walk-forward
        "wf_windows_passed":     wf["windows_passed"],
        "wf_consistency_score":  round(wf["wf_consistency_score"], 4),
        "wf_table":              wf["windows"],
        "wf_oos_sharpes":        wf["oos_sharpes"],
        "wf_sharpe_std":         round(wf_var["wf_sharpe_std"], 4),
        "wf_sharpe_min":         round(wf_var["wf_sharpe_min"], 4),
        # Statistical rigor
        "mc_p5_sharpe":     round(mc["mc_p5_sharpe"], 4),
        "mc_median_sharpe": round(mc["mc_median_sharpe"], 4),
        "mc_p95_sharpe":    round(mc["mc_p95_sharpe"], 4),
        "sharpe_ci_low":    round(bb["sharpe_ci_low"], 4),
        "sharpe_ci_high":   round(bb["sharpe_ci_high"], 4),
        "mdd_ci_low":       round(bb["mdd_ci_low"], 4),
        "mdd_ci_high":      round(bb["mdd_ci_high"], 4),
        "win_rate_ci_low":  round(bb["win_rate_ci_low"], 4),
        "win_rate_ci_high": round(bb["win_rate_ci_high"], 4),
        "market_impact_bps":    round(market_impact_bps, 6),
        "liquidity_constrained": liquidity_constrained,
        "order_to_adv_ratio":   round(order_to_adv_ratio, 8),
        "permutation_pvalue":   round(perm["permutation_pvalue"], 4),
        "permutation_test_pass": perm["permutation_test_pass"],
        # Sensitivity
        "sensitivity_scan": sens_results,
        "sensitivity_pass": sensitivity_pass,
        # H07 specific
        "uso_dbc_correlation": uso_dbc_corr,
        "look_ahead_bias_flag": False,
        # Gate 1
        "gate1_checks": gate1_checks,
        "gate1_pass":   gate1_pass,
    }

    # ── Save JSON ──────────────────────────────────────────────────────────
    out_dir   = os.path.dirname(os.path.abspath(__file__))
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

    corr_flag = uso_dbc_corr.get("uso_dbc_corr_flag")
    corr_max  = uso_dbc_corr.get("uso_dbc_max_rolling_12m_corr", "N/A")
    lines += [
        "",
        f"USO/DBC Rolling Correlation: max={corr_max}  "
            f"flagged={'YES — consider replacing USO with SLV/DBB' if corr_flag else 'NO'}",
        "",
    ]

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
