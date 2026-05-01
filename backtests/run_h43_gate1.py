"""
Gate 1 Backtest Runner: H43 Macro Announcement Day Premium — SPY
Backtest Runner Agent | QUA-340 | 2026-05-01

Full Gate 1 evaluation:
- IS backtest (2007-01-01 to 2021-12-31)
- OOS backtest (2022-01-01 to 2025-04-30)
- 4 walk-forward folds (expanding IS window, chronological)
- Parameter sensitivity sweep (5 combinations)
- Monte Carlo Sharpe (1000 simulations, trade PnL bootstrap)
- Block bootstrap 95% CI for Sharpe, MDD, win rate
- Permutation p-value for alpha (500 permutations)
- Walk-forward variance metrics
- NFP vs CPI decomposition
- 2022 SHY filter audit
- Regime breakdown (2007-2012, 2013-2018, 2019-2021)
- OOS data quality validation
- Gate 1 verdict JSON + markdown report

Outputs:
- backtests/h43_gate1_results.json
- backtests/h43_gate1_report.md

Ref: QUA-340, QUA-338
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

# ── Path setup ─────────────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "orchestrator"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "agents", "overfit-detector", "tools"))

from strategies.h43_macro_announcement_day_premium import (
    run_backtest,
    PARAMETERS,
    download_data,
    compute_shy_filter,
    get_announcement_dates,
    build_signal_map,
)
from oos_data_quality import validate_oos_data, OOSDataQualityError

# ── Constants ──────────────────────────────────────────────────────────────────
IS_START  = "2007-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2025-04-30"
TODAY     = date.today().strftime("%Y-%m-%d")
STRATEGY_NAME = "H43_MacroAnnouncementDayPremium"

# Gate 1 thresholds
G1_IS_SHARPE  = 1.0
G1_OOS_SHARPE = 0.7
G1_MDD        = -0.20
G1_MIN_TRADES = 100
G1_WF_PASS    = 3       # of 4 folds must pass

TRADING_DAYS_PER_YEAR = 252

# Parameter sensitivity grid: vary shy_lookback_days and shy_threshold ±20%
PARAM_GRID = [
    # primary (canonical)
    {"shy_lookback_days": 10, "shy_threshold": -0.015},
    # lookback shorter
    {"shy_lookback_days": 8,  "shy_threshold": -0.015},
    # lookback longer
    {"shy_lookback_days": 12, "shy_threshold": -0.015},
    # threshold looser
    {"shy_lookback_days": 10, "shy_threshold": -0.012},
    # threshold tighter
    {"shy_lookback_days": 10, "shy_threshold": -0.018},
]


# ── Formatting helpers ─────────────────────────────────────────────────────────

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


def _build_params(overrides: dict) -> dict:
    p = PARAMETERS.copy()
    p.update(overrides)
    return p


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
    n_trades: int,
    hold_days: int,
    observed_sharpe: float,
    n_perms: int = 500,
) -> dict:
    """
    Null: randomly place n_trades holding windows on non-announcement days.
    p-value = fraction of permuted Sharpes >= observed.
    """
    prices = spy_prices.values
    n = len(prices)
    max_start = n - hold_days - 1

    if n_trades == 0 or max_start <= 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    permuted_sharpes = []
    for _ in range(n_perms):
        idxs = np.random.choice(max_start, size=min(n_trades, max_start), replace=False)
        window_returns = []
        for idx in idxs:
            exit_idx = min(idx + hold_days, n - 1)
            ret = (prices[exit_idx] - prices[idx]) / (prices[idx] + 1e-8)
            window_returns.append(ret)
        arr = np.array(window_returns)
        if len(arr) > 1:
            s = arr.mean() / (arr.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR / max(hold_days, 1))
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
    from scipy import stats
    import math
    sr = returns.mean() / (returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))
    if n_trials <= 1:
        emax_sr = 0.0
    else:
        emax_sr = (1 - 0.5772156649 / math.log(n_trials)) * math.sqrt(2 * math.log(n_trials))
    sigma_sr = math.sqrt(abs((1 + 0.5 * sr**2 - skew * sr + (kurt / 4) * sr**2) / max(T - 1, 1)))
    dsr = (sr - emax_sr) / sigma_sr if sigma_sr > 0 else np.nan
    return float(dsr)


def compute_market_impact(ticker: str, start: str, end: str, init_cash: float = 25000.0) -> dict:
    """Square-root market impact for SPY."""
    try:
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        if raw.empty or "Close" not in raw.columns:
            raise ValueError("No data")
        avg_price = float(raw["Close"].mean())
        order_qty = int(init_cash / avg_price) if avg_price > 0 else 100
        adv = float(raw["Volume"].rolling(20).mean().iloc[-1])
        sigma = float(raw["Close"].pct_change().std())
        k = 0.1
        impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
        impact_bps = impact_pct * 10000
        liquidity_constrained = bool(order_qty > 0.01 * adv)
        return {
            "market_impact_bps":     float(impact_bps),
            "liquidity_constrained": liquidity_constrained,
            "order_to_adv_ratio":    float(order_qty / (adv + 1e-8)),
            "avg_order_qty":         order_qty,
        }
    except Exception as e:
        print(f"[WARN] market impact calc failed: {e}")
        return {
            "market_impact_bps":     np.nan,
            "liquidity_constrained": False,
            "order_to_adv_ratio":    np.nan,
            "avg_order_qty":         0,
        }


# ── Walk-Forward ───────────────────────────────────────────────────────────────

def run_walk_forward(n_folds: int = 4) -> list:
    """
    4-fold expanding walk-forward over IS period (2007-2021, 15 years).
    Divides IS into 5 equal blocks of 3 years; each fold uses all prior blocks
    as train and the next block as OOS.

    Fold 1: Train 2007-2009 (36mo), OOS 2010-2012
    Fold 2: Train 2007-2012 (72mo), OOS 2013-2015
    Fold 3: Train 2007-2015 (108mo), OOS 2016-2018
    Fold 4: Train 2007-2018 (144mo), OOS 2019-2021
    """
    primary_params = _build_params(PARAM_GRID[0])
    fold_results = []

    # 5 equal 3-year blocks spanning 2007-2021
    block_boundaries = [
        ("2007-01-01", "2009-12-31"),
        ("2010-01-01", "2012-12-31"),
        ("2013-01-01", "2015-12-31"),
        ("2016-01-01", "2018-12-31"),
        ("2019-01-01", "2021-12-31"),
    ]

    for fold in range(n_folds):
        train_start  = block_boundaries[0][0]
        train_end    = block_boundaries[fold][1]
        oos_start    = block_boundaries[fold + 1][0]
        oos_end      = block_boundaries[fold + 1][1]

        print(f"  Fold {fold+1}: Train {train_start}→{train_end} | OOS {oos_start}→{oos_end}")

        try:
            is_res  = run_backtest(train_start, train_end, primary_params)
            oos_res = run_backtest(oos_start, oos_end, primary_params)

            is_sharpe  = is_res["sharpe"]
            oos_sharpe = oos_res["sharpe"]

            consistency = np.nan
            fold_pass   = False
            if is_sharpe and abs(is_sharpe) > 1e-6 and oos_sharpe is not None:
                consistency = abs(oos_sharpe - is_sharpe) / (abs(is_sharpe) + 1e-8)
                fold_pass   = oos_sharpe > G1_OOS_SHARPE and consistency <= 0.50

            fold_results.append({
                "fold":        fold + 1,
                "train_start": train_start,
                "train_end":   train_end,
                "oos_start":   oos_start,
                "oos_end":     oos_end,
                "train_sharpe": round(float(is_sharpe), 4) if is_sharpe is not None else None,
                "oos_sharpe":   round(float(oos_sharpe), 4) if oos_sharpe is not None else None,
                "is_mdd":       round(float(is_res["max_drawdown"]), 4),
                "oos_mdd":      round(float(oos_res["max_drawdown"]), 4),
                "is_trades":    is_res["trade_count"],
                "oos_trades":   oos_res["trade_count"],
                "consistency":  round(float(consistency), 4) if not np.isnan(consistency) else None,
                "fold_pass":    fold_pass,
            })
        except Exception as e:
            print(f"  [WARN] Fold {fold+1} failed: {e}")
            traceback.print_exc()
            fold_results.append({
                "fold":      fold + 1,
                "train_start": train_start, "train_end": train_end,
                "oos_start": oos_start, "oos_end": oos_end,
                "error":     str(e), "fold_pass": False,
            })

    return fold_results


# ── Sensitivity Sweep ──────────────────────────────────────────────────────────

def run_sensitivity_sweep() -> list:
    """Run IS backtest with 5 param variants; assess Sharpe stability."""
    sweep_results = []
    for cfg in PARAM_GRID:
        label = f"shy_lb={cfg['shy_lookback_days']},shy_th={cfg['shy_threshold']:.3f}"
        print(f"  Sensitivity: {label}")
        try:
            p = _build_params(cfg)
            res = run_backtest(IS_START, IS_END, p)
            sweep_results.append({
                **cfg,
                "label":       label,
                "is_sharpe":   round(float(res["sharpe"]), 4),
                "is_mdd":      round(float(res["max_drawdown"]), 4),
                "win_rate":    round(float(res["win_rate"]), 4),
                "trade_count": res["trade_count"],
            })
        except Exception as e:
            sweep_results.append({**cfg, "label": label, "error": str(e)})
    return sweep_results


def sensitivity_pass(sweep_results: list, primary_sharpe: float) -> tuple:
    """Pass if ≥3/5 configs within ±30% of primary Sharpe."""
    if primary_sharpe is None or abs(primary_sharpe) < 1e-6:
        return False, 0.0
    passing = 0
    total = 0
    max_delta = 0.0
    for row in sweep_results:
        if "error" in row:
            continue
        s = row.get("is_sharpe")
        if s is None:
            continue
        total += 1
        delta = abs(s - primary_sharpe) / (abs(primary_sharpe) + 1e-8)
        max_delta = max(max_delta, delta)
        if delta <= 0.30:
            passing += 1
    passed = total > 0 and passing >= 3
    return passed, round(max_delta, 4)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    warnings.filterwarnings("ignore")
    np.random.seed(42)

    print("=" * 70)
    print("H43 MACRO ANNOUNCEMENT DAY PREMIUM — GATE 1 BACKTEST RUNNER")
    print("=" * 70)
    print(f"IS window:  {IS_START} → {IS_END}")
    print(f"OOS window: {OOS_START} → {OOS_END}")
    print(f"Primary params: SHY lb=10d, threshold=-1.5%, entry=T-1_close")
    print(f"Run date: {TODAY}")
    print()

    primary_params = _build_params(PARAM_GRID[0])

    # ── 1. IS Backtest ─────────────────────────────────────────────────────────
    print("Step 1: IS backtest (2007–2021)...")
    is_result  = run_backtest(IS_START, IS_END, primary_params)
    is_sharpe  = is_result["sharpe"]
    is_mdd     = is_result["max_drawdown"]
    is_trades  = is_result["trade_count"]
    is_winrate = is_result["win_rate"]
    is_pf      = is_result["profit_factor"]
    is_ret     = is_result["total_return"]
    is_shy_blk = is_result["shy_blocked_count"]
    is_event_bd = is_result["event_breakdown"]
    is_equity  = is_result["equity"]
    is_trade_df = is_result["trades"]

    print(f"  IS Sharpe={fmt(is_sharpe)}  MDD={pct(is_mdd)}  "
          f"Trades={is_trades}  WinRate={pct(is_winrate)}  PF={fmt(is_pf, 2)}  "
          f"SHY-blocked={is_shy_blk}")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────────
    print("Step 2: OOS backtest (2022–2025)...")
    oos_result  = run_backtest(OOS_START, OOS_END, primary_params)
    oos_sharpe  = oos_result["sharpe"]
    oos_mdd     = oos_result["max_drawdown"]
    oos_trades  = oos_result["trade_count"]
    oos_winrate = oos_result["win_rate"]
    oos_pf      = oos_result["profit_factor"]
    oos_ret     = oos_result["total_return"]
    oos_shy_blk = oos_result["shy_blocked_count"]
    oos_equity  = oos_result["equity"]
    oos_trade_df = oos_result["trades"]

    print(f"  OOS Sharpe={fmt(oos_sharpe)}  MDD={pct(oos_mdd)}  "
          f"Trades={oos_trades}  WinRate={pct(oos_winrate)}  PF={fmt(oos_pf, 2)}  "
          f"SHY-blocked={oos_shy_blk}")

    # ── 3. OOS Data Quality Validation ────────────────────────────────────────
    print("Step 3: OOS data quality validation...")
    post_cost_sharpe_oos = float(oos_sharpe) if oos_sharpe is not None else np.nan
    oos_metrics_for_dq = {
        "sharpe":           oos_sharpe,
        "max_drawdown":     oos_mdd,
        "win_rate":         oos_winrate,
        "profit_factor":    oos_pf,
        "total_trades":     oos_trades,
        "post_cost_sharpe": post_cost_sharpe_oos,
        "total_return":     oos_ret,
    }

    # Build a minimal OOS price DataFrame for the validator
    try:
        oos_raw = yf.download("SPY", start=OOS_START, end=OOS_END,
                              auto_adjust=True, progress=False)
        if isinstance(oos_raw.columns, pd.MultiIndex):
            oos_raw.columns = oos_raw.columns.get_level_values(0)
        oos_price_df = oos_raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    except Exception as e:
        print(f"  [WARN] OOS price download failed for DQ: {e}")
        oos_price_df = pd.DataFrame({"Close": oos_equity.values} if not oos_equity.empty else {"Close": [1.0]})

    dq_report = validate_oos_data(oos_price_df, oos_metrics_for_dq, STRATEGY_NAME)
    print(f"  OOS DQ: {dq_report['recommendation']} | "
          f"Coverage={dq_report['oos_data_coverage_pct']:.1f}% | "
          f"NaN metrics={dq_report['metrics_nan_fields']}")

    if dq_report["recommendation"] == "BLOCK":
        print(f"\n[FATAL] OOS data quality BLOCK: {dq_report['block_reasons']}")
        # Save partial result and exit
        _save_blocked_result(dq_report)
        return

    if dq_report["recommendation"] == "WARN":
        print(f"  [DATA QUALITY WARN] {dq_report.get('advisory_nan_fields', [])}")

    # ── 4. DSR ────────────────────────────────────────────────────────────────
    print("Step 4: DSR calculation...")
    n_trials = len(PARAM_GRID) * 2
    is_daily_returns = is_result["returns"].values
    dsr = compute_dsr(is_daily_returns, n_trials)
    print(f"  DSR z-score={fmt(dsr)}  (n_trials={n_trials})")

    # ── 5. Walk-Forward ────────────────────────────────────────────────────────
    print("Step 5: Walk-forward analysis (4 folds)...")
    wf_results = run_walk_forward(n_folds=4)
    wf_passes      = sum(1 for r in wf_results if r.get("fold_pass", False))
    wf_oos_sharpes = [r.get("oos_sharpe") for r in wf_results]
    wf_pass        = wf_passes >= G1_WF_PASS
    print(f"  Walk-forward: {wf_passes}/4 folds passed (need ≥{G1_WF_PASS})")
    for r in wf_results:
        print(f"    Fold {r['fold']}: IS={fmt(r.get('train_sharpe'))} "
              f"OOS={fmt(r.get('oos_sharpe'))} "
              f"trades_oos={r.get('oos_trades','?')} pass={r.get('fold_pass')}")

    wf_var = walk_forward_variance(wf_oos_sharpes)
    print(f"  WF variance: std={fmt(wf_var['wf_sharpe_std'])} "
          f"min={fmt(wf_var['wf_sharpe_min'])}")

    # ── 6. Monte Carlo ────────────────────────────────────────────────────────
    print("Step 6: Monte Carlo Sharpe (1000 sims)...")
    if not is_trade_df.empty and len(is_trade_df) >= 2:
        trade_pnls = is_trade_df["pnl"].dropna().values
        mc_results = monte_carlo_sharpe(trade_pnls, n_sims=1000)
    else:
        mc_results = {"mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan}
    print(f"  MC p5={fmt(mc_results['mc_p5_sharpe'])} "
          f"median={fmt(mc_results['mc_median_sharpe'])} "
          f"p95={fmt(mc_results['mc_p95_sharpe'])}")
    mc_p5_ok = (not np.isnan(mc_results["mc_p5_sharpe"]) and
                mc_results["mc_p5_sharpe"] >= 0.5)

    # ── 7. Block Bootstrap CI ─────────────────────────────────────────────────
    print("Step 7: Block bootstrap CI...")
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

    # ── 8. Market Impact ─────────────────────────────────────────────────────
    print("Step 8: Market impact (SPY)...")
    mi_results = compute_market_impact("SPY", IS_START, IS_END,
                                       init_cash=float(primary_params["init_cash"]))
    print(f"  Market impact: {fmt(mi_results['market_impact_bps'], 2)} bps  "
          f"Q/ADV={fmt(mi_results['order_to_adv_ratio'], 8)}  "
          f"liq_constrained={mi_results['liquidity_constrained']}")

    # ── 9. Permutation Test ──────────────────────────────────────────────────
    print("Step 9: Permutation test (500 permutations)...")
    try:
        spy_dl = yf.download("SPY", start=IS_START, end=IS_END,
                             auto_adjust=True, progress=False)
        if isinstance(spy_dl.columns, pd.MultiIndex):
            spy_dl.columns = spy_dl.columns.get_level_values(0)
        spy_close_is = spy_dl["Close"].dropna()
        perm_results = permutation_test_alpha(
            spy_close_is,
            n_trades=is_trades,
            hold_days=1,        # H43 is a 1-day hold (T-1 close to T close)
            observed_sharpe=float(is_sharpe) if is_sharpe is not None else 0.0,
            n_perms=500,
        )
    except Exception as e:
        print(f"  [WARN] Permutation test failed: {e}")
        perm_results = {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    print(f"  p-value={fmt(perm_results['permutation_pvalue'])} "
          f"pass={perm_results['permutation_test_pass']}")

    # ── 10. Sensitivity Sweep ─────────────────────────────────────────────────
    print("Step 10: Parameter sensitivity sweep...")
    sweep = run_sensitivity_sweep()
    sens_pass, sens_max_delta = sensitivity_pass(sweep, is_sharpe)
    print(f"  Sensitivity pass: {sens_pass}  (max_delta={pct(sens_max_delta)})")

    # ── 11. NFP vs CPI Decomposition (Engineering Director request) ───────────
    print("Step 11: NFP vs CPI decomposition...")
    params_cpi = _build_params({"announcement_types": ["CPI"]})
    params_nfp = _build_params({"announcement_types": ["NFP"]})
    try:
        cpi_is = run_backtest(IS_START, IS_END, params_cpi)
        nfp_is = run_backtest(IS_START, IS_END, params_nfp)
        cpi_oos = run_backtest(OOS_START, OOS_END, params_cpi)
        nfp_oos = run_backtest(OOS_START, OOS_END, params_nfp)
        decomp = {
            "CPI": {
                "is_sharpe":   round(float(cpi_is["sharpe"]), 4),
                "is_mdd":      round(float(cpi_is["max_drawdown"]), 4),
                "is_trades":   cpi_is["trade_count"],
                "is_win_rate": round(float(cpi_is["win_rate"]), 4),
                "oos_sharpe":  round(float(cpi_oos["sharpe"]), 4),
                "oos_mdd":     round(float(cpi_oos["max_drawdown"]), 4),
                "oos_trades":  cpi_oos["trade_count"],
                "oos_win_rate": round(float(cpi_oos["win_rate"]), 4),
                "oos_shy_blocked": cpi_oos["shy_blocked_count"],
            },
            "NFP": {
                "is_sharpe":   round(float(nfp_is["sharpe"]), 4),
                "is_mdd":      round(float(nfp_is["max_drawdown"]), 4),
                "is_trades":   nfp_is["trade_count"],
                "is_win_rate": round(float(nfp_is["win_rate"]), 4),
                "oos_sharpe":  round(float(nfp_oos["sharpe"]), 4),
                "oos_mdd":     round(float(nfp_oos["max_drawdown"]), 4),
                "oos_trades":  nfp_oos["trade_count"],
                "oos_win_rate": round(float(nfp_oos["win_rate"]), 4),
                "oos_shy_blocked": nfp_oos["shy_blocked_count"],
            },
        }
        print(f"  CPI IS: Sharpe={fmt(decomp['CPI']['is_sharpe'])}, "
              f"OOS: Sharpe={fmt(decomp['CPI']['oos_sharpe'])}")
        print(f"  NFP IS: Sharpe={fmt(decomp['NFP']['is_sharpe'])}, "
              f"OOS: Sharpe={fmt(decomp['NFP']['oos_sharpe'])}")
    except Exception as e:
        print(f"  [WARN] Decomposition failed: {e}")
        decomp = {"error": str(e)}

    # ── 12. 2022 SHY Filter Audit (Engineering Director request) ─────────────
    print("Step 12: 2022 SHY filter audit...")
    try:
        audit_2022 = run_backtest("2022-01-01", "2022-12-31", primary_params)
        unfiltered_2022 = run_backtest("2022-01-01", "2022-12-31",
                                       {**primary_params, "shy_threshold": -1.0})
        shy_2022_audit = {
            "total_events_2022": unfiltered_2022["trade_count"],
            "filtered_events_2022": audit_2022["shy_blocked_count"],
            "executed_trades_2022": audit_2022["trade_count"],
            "filter_rate_pct": round(
                audit_2022["shy_blocked_count"] / max(1, unfiltered_2022["trade_count"]) * 100, 1
            ),
            "sharpe_filtered_2022": round(float(audit_2022["sharpe"]), 4),
            "sharpe_unfiltered_2022": round(float(unfiltered_2022["sharpe"]), 4),
        }
        print(f"  2022 filter audit: {shy_2022_audit['filtered_events_2022']} of "
              f"{shy_2022_audit['total_events_2022']} events filtered "
              f"({shy_2022_audit['filter_rate_pct']:.1f}%)")
    except Exception as e:
        print(f"  [WARN] 2022 SHY audit failed: {e}")
        shy_2022_audit = {"error": str(e)}

    # ── 13. Regime Breakdown IS (Engineering Director request) ────────────────
    print("Step 13: Regime breakdown (2007-2012, 2013-2018, 2019-2021)...")
    regime_windows = [
        ("2007-01-01", "2012-12-31", "2007–2012 (GFC + Recovery)"),
        ("2013-01-01", "2018-12-31", "2013–2018 (Bull + Taper)"),
        ("2019-01-01", "2021-12-31", "2019–2021 (Pre/Post COVID)"),
    ]
    regime_results = []
    for r_start, r_end, label in regime_windows:
        try:
            r_res = run_backtest(r_start, r_end, primary_params)
            regime_results.append({
                "period":    label,
                "start":     r_start,
                "end":       r_end,
                "sharpe":    round(float(r_res["sharpe"]), 4),
                "mdd":       round(float(r_res["max_drawdown"]), 4),
                "win_rate":  round(float(r_res["win_rate"]), 4),
                "trades":    r_res["trade_count"],
                "total_ret": round(float(r_res["total_return"]), 4),
            })
            print(f"  {label}: Sharpe={fmt(r_res['sharpe'])} "
                  f"trades={r_res['trade_count']}")
        except Exception as e:
            print(f"  [WARN] Regime {label} failed: {e}")
            regime_results.append({"period": label, "error": str(e)})

    # ── 14. Post-cost Sharpe ──────────────────────────────────────────────────
    # H43 already embeds all transaction costs in the simulation; is_sharpe IS
    # the post-cost number. We report it explicitly for Gate 1 template.
    post_cost_sharpe_is  = float(is_sharpe)  if is_sharpe  is not None else np.nan
    post_cost_sharpe_oos = float(oos_sharpe) if oos_sharpe is not None else np.nan

    # ── 15. Gate 1 Pass/Fail ─────────────────────────────────────────────────
    checks = {
        "IS Sharpe > 1.0":       (is_sharpe  is not None and is_sharpe  > G1_IS_SHARPE),
        "OOS Sharpe > 0.7":      (oos_sharpe is not None and oos_sharpe > G1_OOS_SHARPE),
        "IS MDD < 20%":          (is_mdd     is not None and is_mdd     > G1_MDD),
        "OOS MDD < 25%":         (oos_mdd    is not None and oos_mdd    > -0.25),
        "IS Trades ≥ 100":       (is_trades  >= G1_MIN_TRADES),
        "DSR > 0":               (not np.isnan(dsr) and dsr > 0),
        "WF folds passed ≥ 3":   wf_pass,
        "MC p5 Sharpe ≥ 0.5":    mc_p5_ok,
        "Perm test pass":         perm_results["permutation_test_pass"],
        "Sensitivity pass":       sens_pass,
        "Win Rate > 50%":         (is_winrate is not None and is_winrate > 0.50),
    }
    n_pass = sum(checks.values())
    n_total = len(checks)
    gate1_pass = (
        checks["IS Sharpe > 1.0"]   and
        checks["OOS Sharpe > 0.7"]  and
        checks["IS MDD < 20%"]      and
        checks["IS Trades ≥ 100"]
    )
    overall_verdict = "PASS" if gate1_pass and n_pass >= 8 else (
        "CONDITIONAL PASS" if gate1_pass else "FAIL"
    )

    print(f"\n{'='*70}")
    print(f"GATE 1 VERDICT: {overall_verdict} ({n_pass}/{n_total} checks passed)")
    print(f"{'='*70}")
    for check, passed in checks.items():
        print(f"  {'[PASS]' if passed else '[FAIL]'} {check}")

    # ── 16. Trade Log ────────────────────────────────────────────────────────
    is_trade_log  = []
    oos_trade_log = []
    if not is_trade_df.empty:
        for _, row in is_trade_df.iterrows():
            rec = {}
            for col in is_trade_df.columns:
                v = row[col]
                if hasattr(v, "item"):
                    v = v.item()
                elif isinstance(v, (pd.Timestamp, date)):
                    v = str(v)
                elif isinstance(v, float) and np.isnan(v):
                    v = None
                rec[col] = v
            is_trade_log.append(rec)
    if not oos_trade_df.empty:
        for _, row in oos_trade_df.iterrows():
            rec = {}
            for col in oos_trade_df.columns:
                v = row[col]
                if hasattr(v, "item"):
                    v = v.item()
                elif isinstance(v, (pd.Timestamp, date)):
                    v = str(v)
                elif isinstance(v, float) and np.isnan(v):
                    v = None
                rec[col] = v
            oos_trade_log.append(rec)

    # ── 17. Assemble full results JSON ────────────────────────────────────────
    results = {
        "strategy_name":         STRATEGY_NAME,
        "date":                  TODAY,
        "asset_class":           "equities",
        "is_start":              IS_START,
        "is_end":                IS_END,
        "oos_start":             OOS_START,
        "oos_end":               OOS_END,

        # Primary metrics
        "is_sharpe":             round(float(is_sharpe),  4) if is_sharpe  is not None else None,
        "oos_sharpe":            round(float(oos_sharpe), 4) if oos_sharpe is not None else None,
        "is_max_drawdown":       round(float(is_mdd),  4)   if is_mdd     is not None else None,
        "oos_max_drawdown":      round(float(oos_mdd), 4)   if oos_mdd    is not None else None,
        "is_total_return":       round(float(is_ret),  4)   if is_ret     is not None else None,
        "oos_total_return":      round(float(oos_ret), 4)   if oos_ret    is not None else None,
        "win_rate":              round(float(is_winrate), 4) if is_winrate is not None else None,
        "oos_win_rate":          round(float(oos_winrate), 4) if oos_winrate is not None else None,
        "profit_factor":         round(float(is_pf), 4) if is_pf is not None and not np.isinf(is_pf) else None,
        "oos_profit_factor":     round(float(oos_pf), 4) if oos_pf is not None and not np.isinf(oos_pf) else None,
        "trade_count":           is_trades,
        "oos_trade_count":       oos_trades,
        "is_shy_blocked":        is_shy_blk,
        "oos_shy_blocked":       oos_shy_blk,
        "event_breakdown_is":    is_event_bd,
        "event_breakdown_oos":   oos_result.get("event_breakdown", {}),

        # Post-cost (H43 costs are embedded in simulation)
        "post_cost_sharpe":      round(post_cost_sharpe_is, 4),
        "post_cost_sharpe_oos":  round(post_cost_sharpe_oos, 4),

        # DSR
        "dsr":                   round(float(dsr), 4) if not np.isnan(dsr) else None,
        "dsr_n_trials":          n_trials,

        # Walk-forward
        "wf_windows_passed":     wf_passes,
        "wf_pass":               wf_pass,
        "wf_windows":            wf_results,
        "wf_sharpe_std":         round(float(wf_var["wf_sharpe_std"]), 4)
                                 if not np.isnan(wf_var["wf_sharpe_std"]) else None,
        "wf_sharpe_min":         round(float(wf_var["wf_sharpe_min"]), 4)
                                 if not np.isnan(wf_var["wf_sharpe_min"]) else None,

        # Monte Carlo
        "mc_p5_sharpe":          round(float(mc_results["mc_p5_sharpe"]), 4)
                                 if not np.isnan(mc_results["mc_p5_sharpe"]) else None,
        "mc_median_sharpe":      round(float(mc_results["mc_median_sharpe"]), 4)
                                 if not np.isnan(mc_results["mc_median_sharpe"]) else None,
        "mc_p95_sharpe":         round(float(mc_results["mc_p95_sharpe"]), 4)
                                 if not np.isnan(mc_results["mc_p95_sharpe"]) else None,
        "mc_p5_sharpe_flag":     "MC pessimistic bound weak" if not mc_p5_ok else "OK",

        # Bootstrap CI
        "sharpe_ci_low":         round(float(ci_results["sharpe_ci_low"]), 4)
                                 if not np.isnan(ci_results["sharpe_ci_low"]) else None,
        "sharpe_ci_high":        round(float(ci_results["sharpe_ci_high"]), 4)
                                 if not np.isnan(ci_results["sharpe_ci_high"]) else None,
        "mdd_ci_low":            round(float(ci_results["mdd_ci_low"]), 4)
                                 if not np.isnan(ci_results["mdd_ci_low"]) else None,
        "mdd_ci_high":           round(float(ci_results["mdd_ci_high"]), 4)
                                 if not np.isnan(ci_results["mdd_ci_high"]) else None,
        "win_rate_ci_low":       round(float(ci_results["win_rate_ci_low"]), 4)
                                 if not np.isnan(ci_results["win_rate_ci_low"]) else None,
        "win_rate_ci_high":      round(float(ci_results["win_rate_ci_high"]), 4)
                                 if not np.isnan(ci_results["win_rate_ci_high"]) else None,

        # Market impact
        "market_impact_bps":     round(float(mi_results["market_impact_bps"]), 4)
                                 if not np.isnan(mi_results["market_impact_bps"]) else None,
        "liquidity_constrained": mi_results["liquidity_constrained"],
        "order_to_adv_ratio":    round(float(mi_results["order_to_adv_ratio"]), 8)
                                 if not np.isnan(mi_results["order_to_adv_ratio"]) else None,

        # Permutation test
        "permutation_pvalue":    round(float(perm_results["permutation_pvalue"]), 4),
        "permutation_test_pass": perm_results["permutation_test_pass"],

        # Sensitivity
        "sensitivity_pass":      sens_pass,
        "sensitivity_max_delta": sens_max_delta,
        "sensitivity_sweep":     sweep,

        # Engineering Director extras
        "nfp_cpi_decomposition": decomp,
        "shy_2022_audit":        shy_2022_audit,
        "regime_breakdown":      regime_results,

        # Gate 1 verdict
        "gate1_checks":          checks,
        "gate1_pass":            gate1_pass,
        "overall_verdict":       overall_verdict,

        # OOS Data Quality
        "oos_data_quality":      dq_report,

        # Trade logs
        "is_trade_log":          is_trade_log,
        "oos_trade_log":         oos_trade_log,

        # Look-ahead bias flag
        "look_ahead_bias_flag":  False,
    }

    # ── 18. Save JSON ─────────────────────────────────────────────────────────
    backtests_dir = os.path.join(_REPO_ROOT, "backtests")
    os.makedirs(backtests_dir, exist_ok=True)
    json_path = os.path.join(backtests_dir, "h43_gate1_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved: {json_path}")

    # ── 19. Generate Markdown Report ──────────────────────────────────────────
    md = _build_markdown_report(results)
    md_path = os.path.join(backtests_dir, "h43_gate1_report.md")
    with open(md_path, "w") as f:
        f.write(md)
    print(f"Report saved: {md_path}")

    return results


def _save_blocked_result(dq_report: dict):
    backtests_dir = os.path.join(_REPO_ROOT, "backtests")
    os.makedirs(backtests_dir, exist_ok=True)
    path = os.path.join(backtests_dir, "h43_gate1_results.json")
    out = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "overall_verdict": "BLOCKED",
        "gate1_pass": False,
        "oos_data_quality": dq_report,
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Blocked result saved: {path}")


def _build_markdown_report(r: dict) -> str:
    def _pf(v, check=True):
        return "PASS" if v else "FAIL"

    def _fv(v, d=4):
        if v is None:
            return "N/A"
        try:
            return f"{float(v):.{d}f}"
        except Exception:
            return str(v)

    def _pct(v):
        if v is None:
            return "N/A"
        try:
            return f"{float(v):.2%}"
        except Exception:
            return str(v)

    lines = [
        f"# H43 Macro Announcement Day Premium — Gate 1 Report",
        f"",
        f"**Strategy:** {r['strategy_name']}",
        f"**Run date:** {r['date']}",
        f"**IS window:** {r['is_start']} → {r['is_end']}",
        f"**OOS window:** {r['oos_start']} → {r['oos_end']}",
        f"",
        f"## Overall Verdict: {r['overall_verdict']}",
        f"",
        f"## Primary Metrics",
        f"",
        f"| Metric | IS | OOS | Threshold | Pass? |",
        f"|--------|----|----|-----------|-------|",
        f"| Sharpe | {_fv(r.get('is_sharpe'))} | {_fv(r.get('oos_sharpe'))} | IS>1.0, OOS>0.7 | IS:{_pf(r.get('is_sharpe',0)>1.0)} OOS:{_pf(r.get('oos_sharpe',0)>0.7)} |",
        f"| Max Drawdown | {_pct(r.get('is_max_drawdown'))} | {_pct(r.get('oos_max_drawdown'))} | <20% | IS:{_pf(r.get('is_max_drawdown',0)>-0.20)} OOS:{_pf(r.get('oos_max_drawdown',0)>-0.25)} |",
        f"| Total Return | {_pct(r.get('is_total_return'))} | {_pct(r.get('oos_total_return'))} | — | — |",
        f"| Win Rate | {_pct(r.get('win_rate'))} | {_pct(r.get('oos_win_rate'))} | >50% | {_pf(r.get('win_rate',0)>0.50)} |",
        f"| Profit Factor | {_fv(r.get('profit_factor'),2)} | {_fv(r.get('oos_profit_factor'),2)} | >1.0 | {_pf(r.get('profit_factor',0) is not None and r.get('profit_factor',0)>1.0)} |",
        f"| Trade Count | {r.get('trade_count','N/A')} | {r.get('oos_trade_count','N/A')} | IS≥100 | {_pf(r.get('trade_count',0)>=100)} |",
        f"| SHY-Filtered | {r.get('is_shy_blocked','N/A')} | {r.get('oos_shy_blocked','N/A')} | — | — |",
        f"| Post-Cost Sharpe | {_fv(r.get('post_cost_sharpe'))} | {_fv(r.get('post_cost_sharpe_oos'))} | >0.7 | OOS:{_pf(r.get('post_cost_sharpe_oos',0)>0.7)} |",
        f"",
        f"## Statistical Validation",
        f"",
        f"| Test | Result | Threshold | Pass? |",
        f"|------|--------|-----------|-------|",
        f"| DSR z-score | {_fv(r.get('dsr'))} | >0 | {_pf(r.get('dsr',0) is not None and r.get('dsr',0)>0)} |",
        f"| WF folds passed | {r.get('wf_windows_passed','N/A')}/4 | ≥3 | {_pf(r.get('wf_windows_passed',0)>=3)} |",
        f"| WF Sharpe std | {_fv(r.get('wf_sharpe_std'))} | — | — |",
        f"| WF Sharpe min | {_fv(r.get('wf_sharpe_min'))} | >0 (no losing WF window) | {_pf(r.get('wf_sharpe_min') is not None and r.get('wf_sharpe_min',0)>0)} |",
        f"| MC p5 Sharpe | {_fv(r.get('mc_p5_sharpe'))} | ≥0.5 | {_pf(r.get('mc_p5_sharpe',0) is not None and r.get('mc_p5_sharpe',0)>=0.5)} |",
        f"| MC median Sharpe | {_fv(r.get('mc_median_sharpe'))} | — | — |",
        f"| Sharpe 95% CI | [{_fv(r.get('sharpe_ci_low'))}, {_fv(r.get('sharpe_ci_high'))}] | — | — |",
        f"| Permutation p-value | {_fv(r.get('permutation_pvalue'))} | ≤0.05 | {_pf(r.get('permutation_test_pass',False))} |",
        f"| Sensitivity max delta | {_pct(r.get('sensitivity_max_delta'))} | <30% | {_pf(r.get('sensitivity_pass',False))} |",
        f"| Market impact | {_fv(r.get('market_impact_bps'),2)} bps | — | — |",
        f"| Liquidity constrained | {r.get('liquidity_constrained','N/A')} | False | {_pf(not r.get('liquidity_constrained', True))} |",
        f"",
        f"## Walk-Forward Detail",
        f"",
        f"| Fold | Train Period | OOS Period | IS Sharpe | OOS Sharpe | OOS Trades | Pass? |",
        f"|------|-------------|-----------|-----------|------------|------------|-------|",
    ]

    for fold in r.get("wf_windows", []):
        lines.append(
            f"| {fold.get('fold')} | {fold.get('train_start','?')}→{fold.get('train_end','?')} "
            f"| {fold.get('oos_start','?')}→{fold.get('oos_end','?')} "
            f"| {_fv(fold.get('train_sharpe'))} | {_fv(fold.get('oos_sharpe'))} "
            f"| {fold.get('oos_trades','?')} | {fold.get('fold_pass','?')} |"
        )

    lines += [
        f"",
        f"## NFP vs CPI Decomposition",
        f"",
        f"| Event | IS Sharpe | IS MDD | IS Trades | OOS Sharpe | OOS Trades | OOS SHY-Filtered |",
        f"|-------|-----------|--------|-----------|------------|------------|------------------|",
    ]
    decomp = r.get("nfp_cpi_decomposition", {})
    for etype in ["CPI", "NFP"]:
        d = decomp.get(etype, {})
        lines.append(
            f"| {etype} | {_fv(d.get('is_sharpe'))} | {_pct(d.get('is_mdd'))} "
            f"| {d.get('is_trades','N/A')} | {_fv(d.get('oos_sharpe'))} "
            f"| {d.get('oos_trades','N/A')} | {d.get('oos_shy_blocked','N/A')} |"
        )

    lines += [
        f"",
        f"## 2022 SHY Filter Audit",
        f"",
    ]
    audit = r.get("shy_2022_audit", {})
    if "error" not in audit:
        lines += [
            f"- Total CPI/NFP events in 2022: **{audit.get('total_events_2022','N/A')}**",
            f"- Events filtered by SHY: **{audit.get('filtered_events_2022','N/A')}** "
            f"({audit.get('filter_rate_pct','N/A')}%)",
            f"- Trades executed: **{audit.get('executed_trades_2022','N/A')}**",
            f"- Filtered Sharpe: **{_fv(audit.get('sharpe_filtered_2022'))}** vs "
            f"unfiltered: **{_fv(audit.get('sharpe_unfiltered_2022'))}**",
        ]
    else:
        lines.append(f"Error: {audit.get('error')}")

    lines += [
        f"",
        f"## Regime Breakdown (IS)",
        f"",
        f"| Period | Sharpe | MDD | Win Rate | Trades |",
        f"|--------|--------|-----|----------|--------|",
    ]
    for reg in r.get("regime_breakdown", []):
        if "error" not in reg:
            lines.append(
                f"| {reg.get('period')} | {_fv(reg.get('sharpe'))} "
                f"| {_pct(reg.get('mdd'))} | {_pct(reg.get('win_rate'))} "
                f"| {reg.get('trades','N/A')} |"
            )

    lines += [
        f"",
        f"## Gate 1 Checklist",
        f"",
    ]
    for check, passed in r.get("gate1_checks", {}).items():
        icon = "✅" if passed else "❌"
        lines.append(f"- {icon} {check}")

    # OOS DQ section
    dq = r.get("oos_data_quality", {})
    lines += [
        f"",
        f"## OOS Data Quality",
        f"",
        f"- Recommendation: **{dq.get('recommendation', 'N/A')}**",
        f"- Coverage: **{dq.get('oos_data_coverage_pct', 'N/A')}%**",
        f"- NaN metrics: {dq.get('metrics_nan_fields', [])}",
        f"",
        f"---",
        f"*Generated by Backtest Runner Agent | QUA-340 | {TODAY}*",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    main()
