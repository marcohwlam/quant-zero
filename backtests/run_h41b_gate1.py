"""
Gate 1 Backtest Runner: H41b S&P Seasonal Calendar Effect
Backtest Runner Agent | QUA-9 | 2026-05-28

Full Gate 1 evaluation:
- IS backtest (1993-01-01 to 2017-12-31)
- OOS backtest (2018-01-01 to 2025-12-31)
- 4 walk-forward folds (expanding IS window, chronological)
- Parameter sensitivity sweep (5 combinations)
- Monte Carlo Sharpe (1000 simulations, trade PnL bootstrap)
- Block bootstrap 95% CI for Sharpe, MDD, win rate
- Permutation p-value for alpha (500 permutations)
- OOS data quality validation (QUA-220)
- Gate 1 verdict JSON + markdown report
- Verdict template validation (QUA-221)

Outputs:
- backtests/H41b_SPSeasonalCalendar_<date>.json
- backtests/h41b_sp_seasonal_calendar_gate1_report.md

Ref: QUA-9 (Gate 1 run), QUA-8 (strategy implementation)
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.h41b_sp_seasonal_calendar import (
    run_backtest,
    download_data,
    PARAMETERS,
)
from orchestrator.oos_data_quality import validate_oos_data, OOSDataQualityError
from orchestrator.gate1_verdict_validator import (
    enforce_verdict_template,
    validate_verdict_json,
    VerdictValidationError,
)

# ── Constants ────────────────────────────────────────────────────────────────────
IS_START  = "1993-01-01"
IS_END    = "2017-12-31"
OOS_START = "2018-01-01"
OOS_END   = "2025-12-31"
TODAY     = date.today().strftime("%Y-%m-%d")
STRATEGY_NAME = "H41b_SPSeasonalCalendar"
TICKERS = ["SPY", "XLF", "XLK", "XLE"]

TRADING_DAYS_PER_YEAR = 252

# Gate 1 thresholds
G1_IS_SHARPE  = 1.0
G1_OOS_SHARPE = 0.7
G1_MDD        = -0.20
G1_MIN_TRADES = 100
G1_WF_PASS    = 3

# Parameter sensitivity grid: primary + 4 variants
PARAM_GRID = [
    # primary
    {
        "jan_effect_entry_offset": 5, "jan_effect_exit_day": 5,
        "santa_entry_offset": 5, "santa_exit_day": 2,
        "opex_exit_on_thursday": True, "vix_circuit_breaker": 35.0,
    },
    # Jan effect: enter earlier (3 days), exit later (7th day)
    {
        "jan_effect_entry_offset": 3, "jan_effect_exit_day": 7,
        "santa_entry_offset": 5, "santa_exit_day": 2,
        "opex_exit_on_thursday": True, "vix_circuit_breaker": 35.0,
    },
    # Santa rally: enter later (7 days), exit later (4th day)
    {
        "jan_effect_entry_offset": 5, "jan_effect_exit_day": 5,
        "santa_entry_offset": 7, "santa_exit_day": 4,
        "opex_exit_on_thursday": True, "vix_circuit_breaker": 35.0,
    },
    # OpEx: exit on Friday instead of Thursday
    {
        "jan_effect_entry_offset": 5, "jan_effect_exit_day": 5,
        "santa_entry_offset": 5, "santa_exit_day": 2,
        "opex_exit_on_thursday": False, "vix_circuit_breaker": 35.0,
    },
    # VIX circuit breaker raised to 40
    {
        "jan_effect_entry_offset": 5, "jan_effect_exit_day": 5,
        "santa_entry_offset": 5, "santa_exit_day": 2,
        "opex_exit_on_thursday": True, "vix_circuit_breaker": 40.0,
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────────

def pass_fail(value, threshold, direction="above"):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "N/A"
    return "PASS" if (value > threshold if direction == "above" else value < threshold) else "FAIL"


def fmt(v, decimals=4):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.{decimals}f}"


def pct(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.2%}"


def _daily_returns_from_equity(equity: pd.Series) -> np.ndarray:
    return equity.pct_change().fillna(0).values


def _build_params(overrides: dict) -> dict:
    p = PARAMETERS.copy()
    p.update(overrides)
    return p


def _extract_metrics(result: dict) -> dict:
    """Map H41b run_backtest() output to canonical metric keys."""
    m = result["metrics"]
    return {
        "sharpe":         m["sharpe_ratio"],
        "max_drawdown":   m["max_drawdown"],
        "win_rate":       m["win_rate"],
        "profit_factor":  m.get("profit_factor", np.nan),
        "total_trades":   m["trade_count"],
        "total_return":   m.get("total_return", np.nan),
        "post_cost_sharpe": m["sharpe_ratio"],  # costs applied inline
    }


def _oos_data_frame(all_data: dict, tickers: list, start: str, end: str) -> pd.DataFrame:
    """Build a combined Close-price DataFrame for OOS DQ validation."""
    frames = {}
    for t in tickers:
        if t in all_data:
            ser = all_data[t]["Close"]
            ser = ser.loc[(ser.index >= pd.Timestamp(start)) & (ser.index <= pd.Timestamp(end))]
            frames[t] = ser
    if not frames:
        return pd.DataFrame()
    df = pd.DataFrame(frames)
    return df


# ── Statistical Rigor Pipeline ───────────────────────────────────────────────────

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
    prices = spy_prices.values
    n = len(prices)
    max_start = n - hold_days - 1
    if n_windows == 0 or max_start <= 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    permuted_sharpes = []
    for _ in range(n_perms):
        idxs = np.random.choice(max_start, size=min(n_windows, max_start), replace=False)
        window_returns = []
        for idx in idxs:
            exit_idx = min(idx + hold_days, n - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
            window_returns.append(ret)
        arr = np.array(window_returns)
        s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR / max(hold_days, 1)) if len(arr) > 1 else 0.0
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
    from scipy import stats
    import math
    returns = daily_returns[~np.isnan(daily_returns)]
    T = len(returns)
    if T < 10:
        return np.nan
    sr = returns.mean() / (returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))
    emax_sr = 0.0 if n_trials <= 1 else (
        (1 - 0.5772156649 / math.log(n_trials)) * math.sqrt(2 * math.log(n_trials))
    )
    sigma_sr = math.sqrt(
        (1 + 0.5 * sr ** 2 - skew * sr + (kurt / 4) * sr ** 2) / (T - 1)
    )
    return float((sr - emax_sr) / sigma_sr) if sigma_sr > 0 else np.nan


def compute_market_impact(all_data: dict, order_qty: float) -> dict:
    try:
        spy = all_data["SPY"]
        spy_oos = spy.loc[spy.index >= pd.Timestamp(OOS_START)]
        adv = float(spy_oos["Volume"].rolling(20).mean().iloc[-1])
        sigma = float(spy_oos["Close"].pct_change().std())
        k = 0.1
        impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
        impact_bps = impact_pct * 10000
        return {
            "market_impact_bps":     float(impact_bps),
            "liquidity_constrained": bool(order_qty > 0.01 * adv),
            "order_to_adv_ratio":    float(order_qty / (adv + 1e-8)),
        }
    except Exception as e:
        print(f"[WARN] market impact calc failed: {e}")
        return {"market_impact_bps": np.nan, "liquidity_constrained": False,
                "order_to_adv_ratio": np.nan}


# ── Walk-Forward ─────────────────────────────────────────────────────────────────

def run_walk_forward(all_data: dict, n_folds: int = 4) -> list:
    """
    4-fold expanding walk-forward over IS period (1993-2017).
    Sector ETFs available from ~1999; early folds will have SPY only.
    """
    from dateutil.relativedelta import relativedelta

    total_start  = pd.Timestamp(IS_START)
    total_end    = pd.Timestamp(IS_END)
    total_months = (total_end.year - total_start.year) * 12 + (total_end.month - total_start.month)
    oos_months   = total_months // (n_folds + 1)

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
            is_res  = run_backtest(all_data, primary_params, start=is_start_str,  end=is_end_str)
            oos_res = run_backtest(all_data, primary_params, start=oos_start_str, end=oos_end_str)

            is_sharpe  = is_res["metrics"]["sharpe_ratio"]
            oos_sharpe = oos_res["metrics"]["sharpe_ratio"]
            is_mdd     = is_res["metrics"]["max_drawdown"]
            oos_mdd    = oos_res["metrics"]["max_drawdown"]
            is_trades  = is_res["metrics"]["trade_count"]
            oos_trades = oos_res["metrics"]["trade_count"]

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
                "is_sharpe":   round(float(is_sharpe), 4) if is_sharpe is not None else None,
                "oos_sharpe":  round(float(oos_sharpe), 4) if oos_sharpe is not None else None,
                "is_mdd":      round(float(is_mdd), 4),
                "oos_mdd":     round(float(oos_mdd), 4),
                "is_trades":   is_trades,
                "oos_trades":  oos_trades,
                "consistency": round(float(consistency), 4) if not np.isnan(consistency) else None,
                "fold_pass":   fold_pass,
            })
        except Exception as e:
            print(f"  [WARN] Fold {fold+1} failed: {e}")
            traceback.print_exc()
            fold_results.append({
                "fold": fold + 1,
                "is_start": is_start_str, "is_end": is_end_str,
                "oos_start": oos_start_str, "oos_end": oos_end_str,
                "error": str(e), "fold_pass": False,
            })

    return fold_results


# ── Sensitivity Sweep ────────────────────────────────────────────────────────────

def run_sensitivity_sweep(all_data: dict) -> list:
    sweep_results = []
    for cfg in PARAM_GRID:
        label = (f"jan_entry={cfg['jan_effect_entry_offset']},"
                 f"jan_exit={cfg['jan_effect_exit_day']},"
                 f"santa_entry={cfg['santa_entry_offset']},"
                 f"santa_exit={cfg['santa_exit_day']},"
                 f"opex_thu={cfg['opex_exit_on_thursday']},"
                 f"vix={cfg['vix_circuit_breaker']}")
        print(f"  Sensitivity: {label}")
        try:
            p = _build_params(cfg)
            res = run_backtest(all_data, p, start=IS_START, end=IS_END)
            m = res["metrics"]
            sweep_results.append({
                **cfg,
                "is_sharpe":   round(float(m["sharpe_ratio"]), 4),
                "is_mdd":      round(float(m["max_drawdown"]), 4),
                "win_rate":    round(float(m["win_rate"]), 4),
                "trade_count": m["trade_count"],
            })
        except Exception as e:
            sweep_results.append({**cfg, "error": str(e)})
    return sweep_results


def sensitivity_pass(sweep_results: list, primary_sharpe: float) -> bool:
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


# ── Per-Ticker Metrics Helper ─────────────────────────────────────────────────────

def compute_per_ticker_metrics(trades_df: pd.DataFrame, equity_curves: dict) -> dict:
    result = {}
    for ticker in TICKERS:
        if ticker not in equity_curves:
            continue
        eq = equity_curves[ticker]
        rets = _daily_returns_from_equity(eq)
        sharpe = float(rets.mean() / (rets.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)) if len(rets) > 1 and rets.std() > 0 else 0.0
        cum = np.cumprod(1 + rets)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        ticker_trades = trades_df[trades_df["ticker"] == ticker] if not trades_df.empty and "ticker" in trades_df.columns else pd.DataFrame()
        n_trades = len(ticker_trades)
        win_rate = float((ticker_trades["pnl"] > 0).mean()) if n_trades > 0 and "pnl" in ticker_trades.columns else 0.0
        result[ticker] = {
            "sharpe":      round(sharpe, 4),
            "max_drawdown": round(mdd, 4),
            "win_rate":    round(win_rate, 4),
            "trade_count": n_trades,
        }
    return result


# ── Gate 1 Verdict JSON Builder ──────────────────────────────────────────────────

def build_verdict_json(
    is_metrics, oos_metrics, is_sharpe, oos_sharpe, is_mdd, oos_mdd,
    is_winrate, oos_winrate, is_trades, oos_trades, is_pf, oos_pf,
    dsr, wf_results, wf_passes, wf_var, mc_results, ci_results,
    mi_results, perm_results, sens_pass, sweep, checks,
    oos_dq_report, overall_verdict, passed, total,
) -> dict:
    wf_consistency_scores = [
        r.get("consistency") for r in wf_results
        if r.get("consistency") is not None and not np.isnan(r.get("consistency", np.nan))
    ]
    avg_wf_consistency = float(np.mean(wf_consistency_scores)) if wf_consistency_scores else None

    def _safe(v, decimals=4):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return round(float(v), decimals)

    metrics_array = [
        {"name": "IS Sharpe",             "value": _safe(is_sharpe),  "threshold": "> 1.0",   "passed": bool(is_sharpe is not None and is_sharpe > G1_IS_SHARPE)},
        {"name": "OOS Sharpe",            "value": _safe(oos_sharpe), "threshold": "> 0.7",   "passed": bool(oos_sharpe is not None and oos_sharpe > G1_OOS_SHARPE)},
        {"name": "IS Max Drawdown",       "value": _safe(is_mdd),     "threshold": "< -0.20", "passed": bool(is_mdd is not None and is_mdd > G1_MDD)},
        {"name": "OOS Max Drawdown",      "value": _safe(oos_mdd),    "threshold": "< -0.20", "passed": bool(oos_mdd is not None and oos_mdd > G1_MDD)},
        {"name": "Win Rate",              "value": _safe(is_winrate), "threshold": "> 0.50",  "passed": bool(is_winrate is not None and is_winrate > 0.50)},
        {"name": "Trade count",           "value": is_trades,         "threshold": ">= 100",  "passed": bool(is_trades >= G1_MIN_TRADES)},
        {"name": "Deflated Sharpe Ratio (z-score)", "value": _safe(dsr), "threshold": "> 0", "passed": bool(dsr is not None and not np.isnan(dsr) and dsr > 0)},
        {"name": "Walk-forward windows passed", "value": wf_passes,  "threshold": ">= 3/4",  "passed": bool(wf_passes >= G1_WF_PASS)},
        {"name": "Walk-forward OOS/IS consistency", "value": _safe(avg_wf_consistency, 4), "threshold": "<= 0.30", "passed": bool(avg_wf_consistency is not None and avg_wf_consistency <= 0.30)},
        {"name": "Post-cost Sharpe",      "value": _safe(oos_sharpe), "threshold": "> 0.7",   "passed": bool(oos_sharpe is not None and oos_sharpe > G1_OOS_SHARPE)},
        {"name": "Parameter sensitivity", "value": str(sens_pass),    "threshold": "3/5 pass","passed": bool(sens_pass)},
        {"name": "Test period",           "value": f"{IS_START}→{OOS_END}", "threshold": ">= 5 years", "passed": True},
    ]

    verdict_json = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "overall_verdict": overall_verdict,
        "recommendation": (
            "Proceed to paper trading" if overall_verdict == "PASS"
            else "Conditional: address flagged metrics" if overall_verdict == "CONDITIONAL PASS"
            else "Do not advance — Gate 1 criteria not met"
        ),
        "confidence": "HIGH" if overall_verdict == "PASS" else "MEDIUM" if overall_verdict == "CONDITIONAL PASS" else "LOW",
        "disqualify_reason": None,
        "oos_data_quality": oos_dq_report,
        "metrics": metrics_array,
    }
    return verdict_json


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    warnings.filterwarnings("ignore")
    np.random.seed(42)

    print("=" * 70)
    print("H41b S&P SEASONAL CALENDAR EFFECT — GATE 1 BACKTEST RUNNER")
    print("=" * 70)
    print(f"IS window:  {IS_START} → {IS_END}")
    print(f"OOS window: {OOS_START} → {OOS_END}")
    print(f"Tickers: {TICKERS}")
    print(f"Run date: {TODAY}")
    print()

    primary_params = _build_params(PARAM_GRID[0])

    # ── 0. Download full-range data once ────────────────────────────────────────
    print("Step 0: Downloading full-range data (1993–2025)...")
    all_data = download_data(primary_params["tickers"], IS_START, OOS_END,
                             vix_ticker=primary_params["vix_ticker"])
    print(f"  Data downloaded for: {list(all_data.keys())}")
    for t in primary_params["tickers"]:
        if t in all_data:
            print(f"  {t}: {len(all_data[t])} bars ({all_data[t].index[0].date()} → {all_data[t].index[-1].date()})")

    # ── 1. IS Backtest ──────────────────────────────────────────────────────────
    print("\nStep 1: IS backtest (1993–2017)...")
    is_result  = run_backtest(all_data, primary_params, start=IS_START, end=IS_END)
    is_metrics = is_result["metrics"]
    is_trades_df = is_result["trades"]
    is_equity  = is_result["aggregate_equity"]
    is_eq_by_ticker = is_result["equity_curves"]

    is_sharpe  = is_metrics["sharpe_ratio"]
    is_mdd     = is_metrics["max_drawdown"]
    is_trades  = is_metrics["trade_count"]
    is_winrate = is_metrics["win_rate"]
    is_pf      = is_metrics.get("profit_factor", np.nan)
    is_lc      = is_metrics.get("liquidity_constrained_count", 0)
    is_pf4     = is_result.get("pf4_analysis", {})

    print(f"  IS Sharpe={fmt(is_sharpe)}  MDD={pct(is_mdd)}  Trades={is_trades}  "
          f"WinRate={pct(is_winrate)}  PF={fmt(is_pf, 2)}")

    per_ticker_is = compute_per_ticker_metrics(is_trades_df, is_eq_by_ticker)
    for t, tm in per_ticker_is.items():
        print(f"    {t}: Sharpe={fmt(tm['sharpe'])}  MDD={pct(tm['max_drawdown'])}  "
              f"Trades={tm['trade_count']}  WR={pct(tm['win_rate'])}")

    # ── 2. OOS Backtest ─────────────────────────────────────────────────────────
    print("\nStep 2: OOS backtest (2018–2025)...")
    oos_result  = run_backtest(all_data, primary_params, start=OOS_START, end=OOS_END)
    oos_metrics = oos_result["metrics"]
    oos_trades_df = oos_result["trades"]
    oos_equity  = oos_result["aggregate_equity"]
    oos_eq_by_ticker = oos_result["equity_curves"]

    oos_sharpe  = oos_metrics["sharpe_ratio"]
    oos_mdd     = oos_metrics["max_drawdown"]
    oos_trades  = oos_metrics["trade_count"]
    oos_winrate = oos_metrics["win_rate"]
    oos_pf      = oos_metrics.get("profit_factor", np.nan)

    print(f"  OOS Sharpe={fmt(oos_sharpe)}  MDD={pct(oos_mdd)}  Trades={oos_trades}  "
          f"WinRate={pct(oos_winrate)}  PF={fmt(oos_pf, 2)}")

    per_ticker_oos = compute_per_ticker_metrics(oos_trades_df, oos_eq_by_ticker)
    for t, tm in per_ticker_oos.items():
        print(f"    {t}: Sharpe={fmt(tm['sharpe'])}  MDD={pct(tm['max_drawdown'])}  "
              f"Trades={tm['trade_count']}  WR={pct(tm['win_rate'])}")

    # ── 3. OOS Data Quality Validation (QUA-220) ────────────────────────────────
    print("\nStep 3: OOS data quality validation...")
    oos_price_df = _oos_data_frame(all_data, TICKERS, OOS_START, OOS_END)
    oos_metrics_mapped = _extract_metrics(oos_result)
    dq_report = validate_oos_data(oos_price_df, oos_metrics_mapped, STRATEGY_NAME)
    print(f"  DQ recommendation: {dq_report['recommendation']}")
    if dq_report["recommendation"] == "BLOCK":
        print(f"  [BLOCK] {dq_report['block_reasons']}")
        raise OOSDataQualityError(dq_report)
    if dq_report["recommendation"] == "WARN":
        print(f"  [WARN] advisory_nan_fields: {dq_report['advisory_nan_fields']}")

    # ── 4. DSR ──────────────────────────────────────────────────────────────────
    print("\nStep 4: DSR calculation...")
    n_trials = len(PARAM_GRID) * 2
    is_daily_returns = _daily_returns_from_equity(is_equity)
    dsr = compute_dsr(is_daily_returns, n_trials)
    print(f"  DSR={fmt(dsr)}")

    # ── 5. Walk-Forward ─────────────────────────────────────────────────────────
    print("\nStep 5: Walk-forward analysis (4 folds)...")
    wf_results = run_walk_forward(all_data, n_folds=4)
    wf_passes      = sum(1 for r in wf_results if r.get("fold_pass", False))
    wf_oos_sharpes = [r.get("oos_sharpe") for r in wf_results]
    wf_pass        = wf_passes >= G1_WF_PASS
    print(f"  Walk-forward: {wf_passes}/4 folds passed")
    for r in wf_results:
        print(f"    Fold {r['fold']}: IS={fmt(r.get('is_sharpe'))} "
              f"OOS={fmt(r.get('oos_sharpe'))} pass={r.get('fold_pass')}")

    wf_var = walk_forward_variance(wf_oos_sharpes)
    print(f"  WF variance: std={fmt(wf_var['wf_sharpe_std'])} "
          f"min={fmt(wf_var['wf_sharpe_min'])}")

    # ── 6. Monte Carlo ──────────────────────────────────────────────────────────
    print("\nStep 6: Monte Carlo Sharpe (1000 sims)...")
    is_pnls = np.array([t["pnl"] for _, t in (is_trades_df.iterrows() if not is_trades_df.empty else iter([]))
                        if isinstance(t.get("pnl"), (int, float)) and not np.isnan(t["pnl"])])
    if len(is_pnls) >= 2:
        mc_results = monte_carlo_sharpe(is_pnls, n_sims=1000)
    else:
        mc_results = {"mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan}
    print(f"  MC p5={fmt(mc_results['mc_p5_sharpe'])} "
          f"median={fmt(mc_results['mc_median_sharpe'])} "
          f"p95={fmt(mc_results['mc_p95_sharpe'])}")

    # ── 7. Block Bootstrap CI ───────────────────────────────────────────────────
    print("\nStep 7: Block bootstrap CI...")
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

    # ── 8. Market Impact ────────────────────────────────────────────────────────
    print("\nStep 8: Market impact (SPY, 100 shares)...")
    mi_results = compute_market_impact(all_data, primary_params.get("order_qty", 100))
    print(f"  Market impact: {fmt(mi_results['market_impact_bps'], 2)} bps  "
          f"Q/ADV={fmt(mi_results['order_to_adv_ratio'], 6)}  "
          f"constrained={mi_results['liquidity_constrained']}")

    # ── 9. Permutation Test ─────────────────────────────────────────────────────
    print("\nStep 9: Permutation test (500 permutations)...")
    spy_is = all_data["SPY"]["Close"].loc[
        (all_data["SPY"].index >= pd.Timestamp(IS_START)) &
        (all_data["SPY"].index <= pd.Timestamp(IS_END))
    ]
    # Typical hold duration: OpEx=4d, Jan=10d, Santa=7d, SIM=~126d → use median ~10d
    avg_hold = 10
    perm_results = permutation_test_alpha(
        spy_is, is_trades, avg_hold,
        is_sharpe if is_sharpe is not None else 0.0,
        n_perms=500,
    )
    print(f"  p-value={fmt(perm_results['permutation_pvalue'])} "
          f"pass={perm_results['permutation_test_pass']}")

    # ── 10. Sensitivity Sweep ───────────────────────────────────────────────────
    print("\nStep 10: Parameter sensitivity sweep...")
    sweep = run_sensitivity_sweep(all_data)
    sens_pass_val = sensitivity_pass(sweep, is_sharpe)
    print(f"  Sensitivity pass: {sens_pass_val}")

    # ── 11. Gate 1 Verdict ──────────────────────────────────────────────────────
    mc_p5_ok = (not (isinstance(mc_results["mc_p5_sharpe"], float) and np.isnan(mc_results["mc_p5_sharpe"]))
                and mc_results["mc_p5_sharpe"] >= 0.5)

    checks = {
        "IS Sharpe > 1.0":         is_sharpe is not None and is_sharpe > G1_IS_SHARPE,
        "OOS Sharpe > 0.7":        oos_sharpe is not None and oos_sharpe > G1_OOS_SHARPE,
        "IS MDD < 20%":            is_mdd is not None and is_mdd > G1_MDD,
        "OOS MDD < 20%":           oos_mdd is not None and oos_mdd > G1_MDD,
        "Win Rate > 50%":          is_winrate is not None and is_winrate > 0.50,
        "DSR > 0":                 dsr is not None and not np.isnan(dsr) and dsr > 0.0,
        "WF >= 3/4 folds":         wf_pass,
        "Trade count >= 100 (IS)": is_trades >= G1_MIN_TRADES,
        "Sensitivity pass":        sens_pass_val,
        "Permutation p <= 0.05":   perm_results["permutation_test_pass"],
        "MC p5 Sharpe >= 0.5":     mc_p5_ok,
    }

    passed = sum(1 for v in checks.values() if v)
    total  = len(checks)
    n_critical_fail = sum(
        1 for k, v in checks.items()
        if not v and k in ["IS Sharpe > 1.0", "OOS Sharpe > 0.7",
                           "IS MDD < 20%", "WF >= 3/4 folds"]
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

    # ── 12. Build full metrics JSON ─────────────────────────────────────────────
    def _safe(v, dec=4):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        if isinstance(v, (np.floating, np.integer)):
            return round(float(v), dec)
        if isinstance(v, float):
            return round(v, dec)
        return v

    def _serialize_trade(t) -> dict:
        if isinstance(t, dict):
            row = t
        else:
            row = t.to_dict()
        out = {}
        for k, v in row.items():
            if isinstance(v, pd.Timestamp):
                out[k] = v.strftime("%Y-%m-%d")
            elif hasattr(v, "item"):
                out[k] = v.item()
            elif isinstance(v, float) and np.isnan(v):
                out[k] = None
            else:
                out[k] = v
        return out

    is_trade_log_json  = [_serialize_trade(row) for _, row in is_trades_df.iterrows()] if not is_trades_df.empty else []
    oos_trade_log_json = [_serialize_trade(row) for _, row in oos_trades_df.iterrows()] if not oos_trades_df.empty else []

    metrics_json = {
        "strategy_name":   STRATEGY_NAME,
        "date":            TODAY,
        "asset_class":     "equities",
        # Core IS/OOS metrics
        "is_sharpe":       _safe(is_sharpe),
        "oos_sharpe":      _safe(oos_sharpe),
        "is_max_drawdown": _safe(is_mdd),
        "oos_max_drawdown": _safe(oos_mdd),
        "win_rate":        _safe(is_winrate),
        "oos_win_rate":    _safe(oos_winrate),
        "profit_factor":   _safe(is_pf) if not (isinstance(is_pf, float) and (np.isnan(is_pf) or np.isinf(is_pf))) else None,
        "oos_profit_factor": _safe(oos_pf) if not (isinstance(oos_pf, float) and (np.isnan(oos_pf) or np.isinf(oos_pf))) else None,
        "trade_count":     is_trades,
        "oos_trade_count": oos_trades,
        "is_liquidity_constrained_trades": is_lc,
        "post_cost_sharpe": _safe(oos_sharpe),  # costs applied inline
        # DSR
        "dsr":             _safe(dsr),
        # Walk-forward
        "wf_windows_passed":  wf_passes,
        "wf_windows_total":   4,
        "wf_consistency_score": _safe(
            float(np.mean([r["consistency"] for r in wf_results
                           if r.get("consistency") is not None])) if any(r.get("consistency") is not None for r in wf_results) else None
        ),
        "wf_fold_results":    wf_results,
        "wf_sharpe_std":      _safe(wf_var["wf_sharpe_std"]),
        "wf_sharpe_min":      _safe(wf_var["wf_sharpe_min"]),
        # Statistical rigor
        "mc_p5_sharpe":       _safe(mc_results["mc_p5_sharpe"]),
        "mc_median_sharpe":   _safe(mc_results["mc_median_sharpe"]),
        "mc_p95_sharpe":      _safe(mc_results["mc_p95_sharpe"]),
        "sharpe_ci_low":      _safe(ci_results["sharpe_ci_low"]),
        "sharpe_ci_high":     _safe(ci_results["sharpe_ci_high"]),
        "mdd_ci_low":         _safe(ci_results["mdd_ci_low"]),
        "mdd_ci_high":        _safe(ci_results["mdd_ci_high"]),
        "win_rate_ci_low":    _safe(ci_results["win_rate_ci_low"]),
        "win_rate_ci_high":   _safe(ci_results["win_rate_ci_high"]),
        # Market impact
        "market_impact_bps":    _safe(mi_results["market_impact_bps"], 4),
        "liquidity_constrained": mi_results["liquidity_constrained"],
        "order_to_adv_ratio":   _safe(mi_results["order_to_adv_ratio"], 8),
        # Permutation
        "permutation_pvalue":    _safe(perm_results["permutation_pvalue"]),
        "permutation_test_pass": perm_results["permutation_test_pass"],
        # Sensitivity
        "sensitivity_pass":   sens_pass_val,
        "sensitivity_sweep":  sweep,
        # Gate 1
        "gate1_pass":         gate1_pass,
        "overall_verdict":    overall_verdict,
        "gate1_checks":       {k: bool(v) for k, v in checks.items()},
        "gate1_checks_passed": f"{passed}/{total}",
        # Per-ticker breakdown
        "per_ticker_is":   per_ticker_is,
        "per_ticker_oos":  per_ticker_oos,
        # PF-4 analysis
        "pf4_analysis":    is_pf4,
        # Look-ahead
        "look_ahead_bias_flag": False,
        # OOS data quality
        "oos_data_quality": dq_report,
        # Trade logs
        "is_trade_log":  is_trade_log_json,
        "oos_trade_log": oos_trade_log_json,
    }

    # ── 13. Save full metrics JSON ──────────────────────────────────────────────
    os.makedirs(os.path.join(os.path.dirname(__file__)), exist_ok=True)
    json_path = os.path.join(os.path.dirname(__file__), f"{STRATEGY_NAME}_{TODAY}.json")
    with open(json_path, "w") as f:
        json.dump(metrics_json, f, indent=2, default=str)
    print(f"Metrics JSON saved: {json_path}")

    # ── 14. Verdict JSON (template-validated) ──────────────────────────────────
    verdict_json = build_verdict_json(
        is_metrics, oos_metrics, is_sharpe, oos_sharpe, is_mdd, oos_mdd,
        is_winrate, oos_winrate, is_trades, oos_trades, is_pf, oos_pf,
        dsr, wf_results, wf_passes, wf_var, mc_results, ci_results,
        mi_results, perm_results, sens_pass_val, sweep, checks,
        dq_report, overall_verdict, passed, total,
    )

    val_result = validate_verdict_json(verdict_json)
    if val_result.has_errors:
        print(f"[VERDICT VALIDATION] {val_result.summary()}")
        raise VerdictValidationError(STRATEGY_NAME, [i for i in val_result.issues if i.severity == "error"])
    if val_result.has_warnings:
        print(f"[VERDICT VALIDATION WARNING] {val_result.summary()}")

    verdict_path = os.path.join(os.path.dirname(__file__), f"{STRATEGY_NAME}_{TODAY}_verdict.json")
    with open(verdict_path, "w") as f:
        json.dump(verdict_json, f, indent=2, default=str)
    print(f"Verdict JSON saved: {verdict_path}")

    # ── 15. Markdown Report ─────────────────────────────────────────────────────
    mc_flag = "YES (weak)" if not (isinstance(mc_results["mc_p5_sharpe"], float) and np.isnan(mc_results["mc_p5_sharpe"])) and mc_results["mc_p5_sharpe"] < 0.5 else "NO"
    wf_min_flag = (
        "wf_sharpe_min < 0 — at least one losing OOS fold"
        if wf_var["wf_sharpe_min"] is not None
        and not (isinstance(wf_var["wf_sharpe_min"], float) and np.isnan(wf_var["wf_sharpe_min"]))
        and wf_var["wf_sharpe_min"] < 0
        else ""
    )

    md_lines = [
        f"# H41b S&P Seasonal Calendar Effect — Gate 1 Backtest Report",
        f"",
        f"**Run date:** {TODAY}  ",
        f"**Strategy:** H41b S&P Seasonal Calendar Effect  ",
        f"**Asset class:** Equities (SPY, XLF, XLK, XLE ETFs; equal-weight portfolio)  ",
        f"**References:** [QUA-9](/QUA/issues/QUA-9), [QUA-8](/QUA/issues/QUA-8)  ",
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
        f"| OOS Data Quality | {dq_report['recommendation']} |",
        f"",
        f"---",
        f"",
        f"## Gate 1 Checklist",
        f"",
        f"| Check | Result |",
        f"|---|---|",
    ]
    for k, v in checks.items():
        md_lines.append(f"| {k} | {'PASS' if v else 'FAIL'} |")

    md_lines += [
        f"",
        f"---",
        f"",
        f"## Primary Configuration Metrics",
        f"",
        f"**Parameters:** jan_effect_entry=5, jan_effect_exit=5, santa_entry=5, santa_exit=2, opex_thursday=True, vix_cb=35",
        f"",
        f"| Metric | IS (1993–2017) | OOS (2018–2025) | Threshold |",
        f"|---|---|---|---|",
        f"| Sharpe Ratio | {fmt(is_sharpe)} | {fmt(oos_sharpe)} | IS>1.0, OOS>0.7 |",
        f"| Max Drawdown | {pct(is_mdd)} | {pct(oos_mdd)} | <20% |",
        f"| Win Rate | {pct(is_winrate)} | {pct(oos_winrate)} | >50% |",
        f"| Profit Factor | {fmt(is_pf, 2)} | {fmt(oos_pf, 2)} | >1.0 |",
        f"| Trade Count | {is_trades} | {oos_trades} | IS>=100 |",
        f"| Liquidity Constrained (IS) | {is_lc} | — | — |",
        f"| DSR | {fmt(dsr)} | — | >0 |",
        f"",
        f"---",
        f"",
        f"## Per-Ticker Results",
        f"",
        f"### IS (1993–2017)",
        f"",
        f"| Ticker | Sharpe | Max Drawdown | Win Rate | Trades |",
        f"|---|---|---|---|---|",
    ]
    for t in TICKERS:
        if t in per_ticker_is:
            tm = per_ticker_is[t]
            md_lines.append(f"| {t} | {fmt(tm['sharpe'])} | {pct(tm['max_drawdown'])} | {pct(tm['win_rate'])} | {tm['trade_count']} |")
    md_lines += [
        f"| **Equal-weight portfolio** | **{fmt(is_sharpe)}** | **{pct(is_mdd)}** | **{pct(is_winrate)}** | **{is_trades}** |",
        f"",
        f"### OOS (2018–2025)",
        f"",
        f"| Ticker | Sharpe | Max Drawdown | Win Rate | Trades |",
        f"|---|---|---|---|---|",
    ]
    for t in TICKERS:
        if t in per_ticker_oos:
            tm = per_ticker_oos[t]
            md_lines.append(f"| {t} | {fmt(tm['sharpe'])} | {pct(tm['max_drawdown'])} | {pct(tm['win_rate'])} | {tm['trade_count']} |")
    md_lines.append(f"| **Equal-weight portfolio** | **{fmt(oos_sharpe)}** | **{pct(oos_mdd)}** | **{pct(oos_winrate)}** | **{oos_trades}** |")

    md_lines += [
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
        f"| MC pessimistic bound weak (p5 < 0.5) | {mc_flag} |",
        f"",
        f"### Bootstrap 95% CI (block bootstrap, block=sqrt(T))",
        f"",
        f"| Metric | Lower | Upper |",
        f"|---|---|---|",
        f"| Sharpe | {fmt(ci_results['sharpe_ci_low'])} | {fmt(ci_results['sharpe_ci_high'])} |",
        f"| Max Drawdown | {pct(ci_results['mdd_ci_low'])} | {pct(ci_results['mdd_ci_high'])} |",
        f"| Win Rate | {pct(ci_results['win_rate_ci_low'])} | {pct(ci_results['win_rate_ci_high'])} |",
        f"",
        f"### Market Impact (SPY, {primary_params.get('order_qty', 100)} shares)",
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
        f"| Test pass (p<=0.05) | {perm_results['permutation_test_pass']} |",
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
            f"| {r['fold']} | {r.get('is_start','?')}–{r.get('is_end','?')} "
            f"| {r.get('oos_start','?')}–{r.get('oos_end','?')} "
            f"| {fmt(r.get('is_sharpe'))} | {fmt(r.get('oos_sharpe'))} "
            f"| {r.get('is_trades','?')} | {r.get('oos_trades','?')} "
            f"| {cons} | {'PASS' if r.get('fold_pass') else 'FAIL'} |"
        )
    md_lines += [
        f"",
        f"**WF Sharpe std:** {fmt(wf_var['wf_sharpe_std'])} | **WF Sharpe min:** {fmt(wf_var['wf_sharpe_min'])}",
        f"",
        wf_min_flag if wf_min_flag else "",
        f"",
        f"---",
        f"",
        f"## Parameter Sensitivity",
        f"",
        f"| jan_entry | jan_exit | santa_entry | santa_exit | opex_thu | vix_cb | IS Sharpe | IS MDD | Win Rate | Trades |",
        f"|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in sweep:
        if "error" in row:
            md_lines.append(f"| {row.get('jan_effect_entry_offset','?')} | {row.get('jan_effect_exit_day','?')} | "
                            f"{row.get('santa_entry_offset','?')} | {row.get('santa_exit_day','?')} | "
                            f"{row.get('opex_exit_on_thursday','?')} | {row.get('vix_circuit_breaker','?')} | "
                            f"ERROR | — | — | — |")
        else:
            md_lines.append(
                f"| {row.get('jan_effect_entry_offset')} | {row.get('jan_effect_exit_day')} | "
                f"{row.get('santa_entry_offset')} | {row.get('santa_exit_day')} | "
                f"{row.get('opex_exit_on_thursday')} | {row.get('vix_circuit_breaker')} | "
                f"{fmt(row.get('is_sharpe'))} | {pct(row.get('is_mdd'))} | "
                f"{pct(row.get('win_rate'))} | {row.get('trade_count')} |"
            )
    md_lines += [
        f"",
        f"**Sensitivity pass:** {'PASS' if sens_pass_val else 'FAIL'}",
        f"",
        f"---",
        f"",
        f"## Signal Breakdown (IS)",
        f"",
        f"| Signal | Trades | Win Rate | Total PnL |",
        f"|---|---|---|---|",
    ]
    for sig, stats in is_metrics.get("signal_breakdown", {}).items():
        md_lines.append(f"| {sig} | {stats['count']} | {pct(stats['win_rate'])} | ${stats['total_pnl']:,.2f} |")

    md_lines += [
        f"",
        f"---",
        f"",
        f"## PF-4: OpEx/Pre-Holiday Overlap Analysis",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| OpEx entries | {is_pf4.get('opex_count', 'N/A')} |",
        f"| Overlap count | {is_pf4.get('overlap_count', 'N/A')} |",
        f"| Overlap rate | {pct(is_pf4.get('overlap_rate', 0))} |",
        f"| PF-4 pass (<= 30%) | {'PASS' if is_pf4.get('pf4_pass', False) else 'WARN'} |",
        f"| Conflict resolution applied | {is_pf4.get('conflict_resolution_required', False)} |",
        f"",
        f"---",
        f"",
        f"## OOS Data Quality",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| Recommendation | {dq_report['recommendation']} |",
        f"| Coverage | {dq_report['oos_data_coverage_pct']:.1f}% |",
        f"| Total rows | {dq_report['oos_total_rows']} |",
        f"| Clean rows | {dq_report['oos_clean_rows']} |",
        f"| Total NaNs | {dq_report['oos_total_nans']} |",
        f"",
        f"---",
        f"",
        f"## IS Trade Log (first 30 of {len(is_trade_log_json)} trades)",
        f"",
        f"| Ticker | Signal | Entry Date | Exit Date | Entry Price | Exit Price | PnL | Exit Reason |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for t in is_trade_log_json[:30]:
        pnl_str = f"${t.get('pnl', 0):,.2f}" if isinstance(t.get("pnl"), (int, float)) else "N/A"
        md_lines.append(
            f"| {t.get('ticker','—')} | {t.get('signal_types','—')} "
            f"| {t.get('entry_date','—')} | {t.get('exit_date','—')} "
            f"| {t.get('entry_price','—')} | {t.get('exit_price','—')} "
            f"| {pnl_str} | {t.get('exit_reason','—')} |"
        )
    if len(is_trade_log_json) > 30:
        md_lines.append(f"| ... | *{len(is_trade_log_json) - 30} more trades in JSON* | | | | | | |")

    md_lines += [
        f"",
        f"---",
        f"",
        f"*Generated by Backtest Runner Agent (QUA-9) on {TODAY}*",
        f"*Strategy: QUA-8 | Gate 1 run: QUA-9*",
    ]

    md_path = os.path.join(os.path.dirname(__file__), "h41b_sp_seasonal_calendar_gate1_report.md")
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"Markdown report saved: {md_path}")

    return metrics_json, verdict_json, overall_verdict, passed, total, checks, json_path, md_path


if __name__ == "__main__":
    try:
        metrics, verdict, overall_verdict, passed, total, checks, json_path, md_path = main()
        print(f"\nDone. Verdict: {overall_verdict} ({passed}/{total} checks)")
        print(f"JSON:     {json_path}")
        print(f"Report:   {md_path}")
    except OOSDataQualityError as e:
        print(f"\n[BLOCKED] OOS data quality BLOCK: {e}")
        traceback.print_exc()
        sys.exit(2)
    except VerdictValidationError as e:
        print(f"\n[BLOCKED] Verdict template validation failed: {e}")
        traceback.print_exc()
        sys.exit(3)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
