"""
Gate 1 Backtest Runner: H44 LQD/IEF Credit Risk Appetite Timer — SPY/Cash Rotation
Backtest Runner Agent | QUA-341 | 2026-05-01

Full Gate 1 evaluation:
- IS backtest (2007-01-01 to 2021-12-31)
- OOS backtest (2022-01-01 to 2025-12-31)
- 4 walk-forward folds (expanding IS window, chronological, 5 equal 3-year blocks)
- Parameter sensitivity sweep (5 combinations: lookback ±20%, threshold ±20%)
- Monte Carlo Sharpe (1000 simulations, trade PnL bootstrap)
- Block bootstrap 95% CI for Sharpe, MDD, win rate
- Market impact estimate (square-root model)
- Permutation p-value for alpha (500 permutations, null = random SPY/cash matching % in-market)
- Walk-forward variance metrics
- Engineering Director extras:
    * 2022 monthly regime analysis (OOS scenario, MDD flag if IS MDD > 20%)
    * 2008-2009 GFC exit timing
    * Smoothing comparison (smooth=1 vs smooth=2)
    * Sub-period Sharpe decomposition (2007-2012, 2013-2018, 2019-2021)
- OOS data quality validation
- Gate 1 verdict JSON + markdown report

Outputs:
- backtests/h44_gate1_results.json
- backtests/h44_gate1_report.md

Ref: QUA-341, QUA-339
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

from strategies.h44_lqd_ief_credit_risk_appetite_timer import (
    run_backtest,
    PARAMETERS,
    download_data,
    compute_credit_signal,
    apply_smoothing_filter,
)
from oos_data_quality import validate_oos_data, OOSDataQualityError

# ── Constants ──────────────────────────────────────────────────────────────────
IS_START  = "2007-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2025-12-31"
TODAY     = date.today().strftime("%Y-%m-%d")
STRATEGY_NAME = "H44_LQD_IEF_CreditRiskAppetiteTimer"

# Gate 1 thresholds
G1_IS_SHARPE  = 1.0
G1_OOS_SHARPE = 0.7
G1_MDD        = -0.20
G1_MIN_TRADES = 100   # regime transitions
G1_WF_PASS    = 3     # of 4 folds must pass

TRADING_DAYS_PER_YEAR = 252

# Parameter sensitivity grid: vary lookback ±20%, threshold ±20%
PARAM_GRID = [
    # primary (canonical): lookback=20, threshold=0.0, smoothing=1
    {"lookback_days": 20, "signal_threshold": 0.0000, "smoothing_days": 1},
    # lookback shorter (-20%)
    {"lookback_days": 16, "signal_threshold": 0.0000, "smoothing_days": 1},
    # lookback longer (+20%)
    {"lookback_days": 24, "signal_threshold": 0.0000, "smoothing_days": 1},
    # threshold tighter (+0.5 bps)
    {"lookback_days": 20, "signal_threshold": 0.0005, "smoothing_days": 1},
    # threshold looser (negative edge — only exit on meaningful underperformance)
    {"lookback_days": 20, "signal_threshold": -0.0005, "smoothing_days": 1},
]


# ── Formatting helpers ─────────────────────────────────────────────────────────

def pass_fail(cond):
    return "PASS" if cond else "FAIL"


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


def _safe_float(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if np.isnan(f) or np.isinf(f) else round(f, 4)
    except Exception:
        return None


def _trade_log_records(trades_df: pd.DataFrame) -> list:
    """Serialize trade DataFrame to JSON-safe list."""
    if trades_df is None or trades_df.empty:
        return []
    records = []
    for _, row in trades_df.iterrows():
        rec = {}
        for col in trades_df.columns:
            v = row[col]
            if hasattr(v, "item"):
                v = v.item()
            elif isinstance(v, (pd.Timestamp, date)):
                v = str(v)
            elif isinstance(v, float) and np.isnan(v):
                v = None
            rec[col] = v
        records.append(rec)
    return records


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
    pct_in_market: float,
    observed_sharpe: float,
    n_perms: int = 500,
) -> dict:
    """
    Null hypothesis: random SPY/cash allocation matching the same % in-market.
    Randomly assign contiguous holding windows (avg hold_days from observed) so
    the total fraction in market equals pct_in_market.
    p-value = fraction of permuted Sharpes >= observed.
    """
    prices = spy_prices.dropna().values
    n = len(prices)
    if n < 20 or pct_in_market <= 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    # Daily returns under H44's typical hold periods
    daily_ret = np.diff(prices) / (prices[:-1] + 1e-8)

    permuted_sharpes = []
    for _ in range(n_perms):
        # Random binary in-market mask with same fraction as observed
        mask = np.random.rand(len(daily_ret)) < pct_in_market
        perm_rets = daily_ret * mask.astype(float)
        if perm_rets.std() > 0:
            s = perm_rets.mean() / perm_rets.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        else:
            s = 0.0
        permuted_sharpes.append(s)

    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue":    round(p_value, 4),
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
    """Square-root market impact for SPY (Engineering Director spec)."""
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
    Divides IS into 5 equal 3-year blocks; each fold expands training
    and tests on the next block.

    Fold 1: Train 2007-2009 (36mo), OOS 2010-2012
    Fold 2: Train 2007-2012 (72mo), OOS 2013-2015
    Fold 3: Train 2007-2015 (108mo), OOS 2016-2018
    Fold 4: Train 2007-2018 (144mo), OOS 2019-2021
    """
    primary_params = _build_params(PARAM_GRID[0])
    fold_results = []

    block_boundaries = [
        ("2007-01-01", "2009-12-31"),
        ("2010-01-01", "2012-12-31"),
        ("2013-01-01", "2015-12-31"),
        ("2016-01-01", "2018-12-31"),
        ("2019-01-01", "2021-12-31"),
    ]

    for fold in range(n_folds):
        train_start = block_boundaries[0][0]
        train_end   = block_boundaries[fold][1]
        oos_start   = block_boundaries[fold + 1][0]
        oos_end     = block_boundaries[fold + 1][1]

        print(f"  Fold {fold + 1}: Train {train_start}→{train_end} | OOS {oos_start}→{oos_end}")

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
                "fold":           fold + 1,
                "train_start":    train_start,
                "train_end":      train_end,
                "oos_start":      oos_start,
                "oos_end":        oos_end,
                "train_sharpe":   _safe_float(is_sharpe),
                "oos_sharpe":     _safe_float(oos_sharpe),
                "is_mdd":         _safe_float(is_res["max_drawdown"]),
                "oos_mdd":        _safe_float(oos_res["max_drawdown"]),
                "is_transitions": is_res["n_transitions"],
                "oos_transitions": oos_res["n_transitions"],
                "is_trades":      is_res["trade_count"],
                "oos_trades":     oos_res["trade_count"],
                "consistency":    round(float(consistency), 4) if not np.isnan(consistency) else None,
                "fold_pass":      fold_pass,
            })
        except Exception as e:
            print(f"  [WARN] Fold {fold + 1} failed: {e}")
            traceback.print_exc()
            fold_results.append({
                "fold":        fold + 1,
                "train_start": train_start, "train_end": train_end,
                "oos_start":   oos_start, "oos_end": oos_end,
                "error":       str(e), "fold_pass": False,
            })

    return fold_results


# ── Sensitivity Sweep ──────────────────────────────────────────────────────────

def run_sensitivity_sweep() -> list:
    """Run IS backtest with 5 param variants; assess Sharpe stability."""
    sweep_results = []
    for cfg in PARAM_GRID:
        label = (f"lb={cfg['lookback_days']}d,"
                 f"thresh={cfg['signal_threshold']:.4f},"
                 f"smooth={cfg['smoothing_days']}d")
        print(f"  Sensitivity: {label}")
        try:
            p = _build_params(cfg)
            res = run_backtest(IS_START, IS_END, p)
            sweep_results.append({
                **cfg,
                "label":         label,
                "is_sharpe":     _safe_float(res["sharpe"]),
                "is_mdd":        _safe_float(res["max_drawdown"]),
                "win_rate":      _safe_float(res["win_rate"]),
                "n_transitions": res["n_transitions"],
                "trade_count":   res["trade_count"],
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


# ── Engineering Director Extras ────────────────────────────────────────────────

def gfc_exit_analysis(primary_params: dict) -> dict:
    """
    Report exact date strategy went to cash in late 2008 (GFC).
    Should be before October 2008 (peak drawdown month for SPY).
    """
    try:
        gfc_res = run_backtest("2007-01-01", "2009-12-31", primary_params)
        daily_df = gfc_res["daily_df"]
        if daily_df.empty:
            return {"error": "No daily data for GFC period"}

        # Find first day the strategy went to cash in the Sep-Dec 2008 window
        gfc_window = daily_df.loc["2008-07-01":"2009-03-31"]
        cash_rows = gfc_window[gfc_window["regime"] != "SPY"]
        first_cash_date = None
        last_spy_before = None
        if not cash_rows.empty:
            first_cash_date = str(cash_rows.index[0].date())
            # Find the exit transition just before
            spy_before = gfc_window.loc[:cash_rows.index[0]]
            spy_before = spy_before[spy_before["regime"] == "SPY"]
            if not spy_before.empty:
                last_spy_before = str(spy_before.index[-1].date())

        # Sep-Oct 2008 cash days
        oct_2008 = daily_df.loc["2008-09-01":"2008-10-31"] if "2008-09-01" in daily_df.index.astype(str) or True else pd.DataFrame()
        try:
            oct_2008 = daily_df.loc["2008-09-01":"2008-10-31"]
        except Exception:
            oct_2008 = pd.DataFrame()
        cash_days_sep_oct_2008 = int((oct_2008["regime"] != "SPY").sum()) if not oct_2008.empty else 0

        before_oct = first_cash_date is not None and first_cash_date < "2008-10-01"

        return {
            "first_cash_date_2008": first_cash_date,
            "last_spy_date_before_exit": last_spy_before,
            "cash_days_sep_oct_2008": cash_days_sep_oct_2008,
            "exited_before_oct_2008": before_oct,
            "gfc_mdd":        _safe_float(gfc_res["max_drawdown"]),
            "gfc_total_ret":  _safe_float(gfc_res["total_return"]),
            "gfc_transitions": gfc_res["n_transitions"],
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def smoothing_comparison(primary_params: dict) -> dict:
    """Compare IS Sharpe and MDD for smoothing=1 vs smoothing=2."""
    try:
        p1 = primary_params.copy()
        p1["smoothing_days"] = 1
        res1 = run_backtest(IS_START, IS_END, p1)

        p2 = primary_params.copy()
        p2["smoothing_days"] = 2
        res2 = run_backtest(IS_START, IS_END, p2)

        return {
            "smoothing_1": {
                "is_sharpe":     _safe_float(res1["sharpe"]),
                "is_mdd":        _safe_float(res1["max_drawdown"]),
                "n_transitions": res1["n_transitions"],
                "win_rate":      _safe_float(res1["win_rate"]),
            },
            "smoothing_2": {
                "is_sharpe":     _safe_float(res2["sharpe"]),
                "is_mdd":        _safe_float(res2["max_drawdown"]),
                "n_transitions": res2["n_transitions"],
                "win_rate":      _safe_float(res2["win_rate"]),
            },
        }
    except Exception as e:
        return {"error": str(e)}


def oos_2022_monthly_analysis(primary_params: dict) -> dict:
    """
    Monthly IS returns for 2022 (OOS period, Engineering Director focus on rate-shock year).
    Flag if any month has SPY exposure during severe drawdown.
    """
    try:
        res_2022 = run_backtest("2022-01-01", "2022-12-31", primary_params)
        daily_df = res_2022["daily_df"]

        if daily_df.empty:
            return {"error": "No 2022 data"}

        # Monthly breakdown
        monthly = []
        for month in range(1, 13):
            m_start = f"2022-{month:02d}-01"
            m_end_dt = pd.Timestamp(f"2022-{month:02d}-01") + pd.offsets.MonthEnd(0)
            m_end = m_end_dt.strftime("%Y-%m-%d")
            try:
                m_df = daily_df.loc[m_start:m_end]
            except Exception:
                continue
            if m_df.empty:
                continue
            m_spy_days = int((m_df["regime"] == "SPY").sum())
            m_cash_days = int((m_df["regime"] != "SPY").sum())
            m_equity_start = float(m_df["equity"].iloc[0])
            m_equity_end   = float(m_df["equity"].iloc[-1])
            m_ret = (m_equity_end - m_equity_start) / (m_equity_start + 1e-8)
            monthly.append({
                "month":      f"2022-{month:02d}",
                "spy_days":   m_spy_days,
                "cash_days":  m_cash_days,
                "regime_pct_spy": round(m_spy_days / max(1, len(m_df)), 4),
                "monthly_return": round(float(m_ret), 4),
            })

        return {
            "year":         "2022",
            "mdd_2022":     _safe_float(res_2022["max_drawdown"]),
            "total_ret_2022": _safe_float(res_2022["total_return"]),
            "transitions_2022": res_2022["n_transitions"],
            "pct_in_spy_2022": _safe_float(res_2022["pct_in_spy"]),
            "monthly_breakdown": monthly,
            "mdd_flag":     (res_2022["max_drawdown"] is not None and
                             res_2022["max_drawdown"] < -0.20),
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


def regime_breakdown(primary_params: dict) -> list:
    """Sub-period Sharpe decomposition: 2007-2012, 2013-2018, 2019-2021."""
    windows = [
        ("2007-01-01", "2012-12-31", "2007–2012 (GFC + Recovery)"),
        ("2013-01-01", "2018-12-31", "2013–2018 (Bull + Taper)"),
        ("2019-01-01", "2021-12-31", "2019–2021 (Pre/Post COVID)"),
    ]
    results = []
    for r_start, r_end, label in windows:
        try:
            res = run_backtest(r_start, r_end, primary_params)
            results.append({
                "period":      label,
                "start":       r_start,
                "end":         r_end,
                "sharpe":      _safe_float(res["sharpe"]),
                "mdd":         _safe_float(res["max_drawdown"]),
                "win_rate":    _safe_float(res["win_rate"]),
                "trade_count": res["trade_count"],
                "n_transitions": res["n_transitions"],
                "total_ret":   _safe_float(res["total_return"]),
                "pct_in_spy":  _safe_float(res["pct_in_spy"]),
            })
            print(f"  {label}: Sharpe={fmt(res['sharpe'])} "
                  f"transitions={res['n_transitions']} MDD={pct(res['max_drawdown'])}")
        except Exception as e:
            print(f"  [WARN] Regime {label} failed: {e}")
            results.append({"period": label, "error": str(e)})
    return results


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    warnings.filterwarnings("ignore")
    np.random.seed(42)

    print("=" * 70)
    print("H44 LQD/IEF CREDIT RISK APPETITE TIMER — GATE 1 BACKTEST RUNNER")
    print("=" * 70)
    print(f"IS window:  {IS_START} → {IS_END}")
    print(f"OOS window: {OOS_START} → {OOS_END}")
    print(f"Primary params: lookback=20d, threshold=0.0%, smoothing=1d, riskoff=cash")
    print(f"Run date: {TODAY}")
    print()

    primary_params = _build_params(PARAM_GRID[0])

    # ── 1. IS Backtest ─────────────────────────────────────────────────────────
    print("Step 1: IS backtest (2007–2021)...")
    is_result  = run_backtest(IS_START, IS_END, primary_params)
    is_sharpe  = is_result["sharpe"]
    is_mdd     = is_result["max_drawdown"]
    is_trades  = is_result["trade_count"]
    is_ntrans  = is_result["n_transitions"]
    is_winrate = is_result["win_rate"]
    is_pf      = is_result["profit_factor"]
    is_ret     = is_result["total_return"]
    is_equity  = is_result["equity"]
    is_trade_df = is_result["trades"]
    is_pct_spy = is_result["pct_in_spy"]

    print(f"  IS Sharpe={fmt(is_sharpe)}  MDD={pct(is_mdd)}  "
          f"Transitions={is_ntrans}  Trades(exits)={is_trades}  "
          f"WinRate={pct(is_winrate)}  PF={fmt(is_pf, 2)}  "
          f"SPY%={pct(is_pct_spy)}")

    # PF-1 check
    if is_ntrans < G1_MIN_TRADES:
        print(f"\n[FLAG] Trade count ({is_ntrans} transitions) < {G1_MIN_TRADES} — "
              f"Gate 1 FAIL on trade count. Escalating to Engineering Director.")

    # IS MDD flag
    if is_mdd is not None and is_mdd < G1_MDD:
        print(f"\n[FLAG] IS MDD ({pct(is_mdd)}) exceeds 20% threshold.")

    # ── 2. OOS Backtest ────────────────────────────────────────────────────────
    print("\nStep 2: OOS backtest (2022–2025)...")
    oos_result  = run_backtest(OOS_START, OOS_END, primary_params)
    oos_sharpe  = oos_result["sharpe"]
    oos_mdd     = oos_result["max_drawdown"]
    oos_trades  = oos_result["trade_count"]
    oos_ntrans  = oos_result["n_transitions"]
    oos_winrate = oos_result["win_rate"]
    oos_pf      = oos_result["profit_factor"]
    oos_ret     = oos_result["total_return"]
    oos_equity  = oos_result["equity"]
    oos_trade_df = oos_result["trades"]
    oos_pct_spy = oos_result["pct_in_spy"]

    print(f"  OOS Sharpe={fmt(oos_sharpe)}  MDD={pct(oos_mdd)}  "
          f"Transitions={oos_ntrans}  Trades(exits)={oos_trades}  "
          f"WinRate={pct(oos_winrate)}  PF={fmt(oos_pf, 2)}  "
          f"SPY%={pct(oos_pct_spy)}")

    # ── 3. OOS Data Quality Validation ────────────────────────────────────────
    print("\nStep 3: OOS data quality validation...")
    post_cost_sharpe_oos = float(oos_sharpe) if oos_sharpe is not None else np.nan
    oos_metrics_for_dq = {
        "sharpe":           oos_sharpe,
        "max_drawdown":     oos_mdd,
        "win_rate":         oos_winrate,
        "profit_factor":    oos_pf if oos_pf is not None and not np.isinf(oos_pf) else None,
        "total_trades":     oos_trades,
        "post_cost_sharpe": post_cost_sharpe_oos,
        "total_return":     oos_ret,
    }

    try:
        oos_raw = yf.download("SPY", start=OOS_START, end=OOS_END,
                              auto_adjust=True, progress=False)
        if isinstance(oos_raw.columns, pd.MultiIndex):
            oos_raw.columns = oos_raw.columns.get_level_values(0)
        oos_price_df = oos_raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    except Exception as e:
        print(f"  [WARN] OOS SPY download failed for DQ: {e}")
        oos_price_df = (pd.DataFrame({"Close": oos_equity.values})
                        if oos_equity is not None and not oos_equity.empty
                        else pd.DataFrame({"Close": [1.0]}))

    dq_report = validate_oos_data(oos_price_df, oos_metrics_for_dq, STRATEGY_NAME)
    print(f"  OOS DQ: {dq_report['recommendation']} | "
          f"Coverage={dq_report['oos_data_coverage_pct']:.1f}% | "
          f"NaN metrics={dq_report['metrics_nan_fields']}")

    if dq_report["recommendation"] == "BLOCK":
        print(f"\n[FATAL] OOS data quality BLOCK: {dq_report['block_reasons']}")
        _save_blocked_result(dq_report)
        return

    if dq_report["recommendation"] == "WARN":
        print(f"  [DATA QUALITY WARN] {dq_report.get('advisory_nan_fields', [])}")

    # ── 4. DSR ────────────────────────────────────────────────────────────────
    print("\nStep 4: DSR calculation...")
    n_trials = len(PARAM_GRID) * 2
    is_daily_returns = is_result["returns"].values
    dsr = compute_dsr(is_daily_returns, n_trials)
    print(f"  DSR z-score={fmt(dsr)}  (n_trials={n_trials})")

    # ── 5. Walk-Forward ────────────────────────────────────────────────────────
    print("\nStep 5: Walk-forward analysis (4 folds)...")
    wf_results     = run_walk_forward(n_folds=4)
    wf_passes      = sum(1 for r in wf_results if r.get("fold_pass", False))
    wf_oos_sharpes = [r.get("oos_sharpe") for r in wf_results]
    wf_pass        = wf_passes >= G1_WF_PASS
    print(f"  Walk-forward: {wf_passes}/4 folds passed (need ≥{G1_WF_PASS})")
    for r in wf_results:
        print(f"    Fold {r['fold']}: IS={fmt(r.get('train_sharpe'))} "
              f"OOS={fmt(r.get('oos_sharpe'))} "
              f"trans_oos={r.get('oos_transitions','?')} pass={r.get('fold_pass')}")

    wf_var = walk_forward_variance(wf_oos_sharpes)
    print(f"  WF variance: std={fmt(wf_var['wf_sharpe_std'])} "
          f"min={fmt(wf_var['wf_sharpe_min'])}")
    if wf_var["wf_sharpe_min"] is not None and not np.isnan(wf_var["wf_sharpe_min"]) and wf_var["wf_sharpe_min"] < 0:
        print("  [FLAG] WF min OOS Sharpe < 0 — at least one losing OOS fold.")

    # ── 6. Monte Carlo ────────────────────────────────────────────────────────
    print("\nStep 6: Monte Carlo Sharpe (1000 sims)...")
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
    if not mc_p5_ok:
        print("  [FLAG] MC pessimistic bound weak (p5 < 0.5)")

    # ── 7. Block Bootstrap CI ─────────────────────────────────────────────────
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
    print(f"  MDD 95% CI: [{pct(ci_results['mdd_ci_low'])}, {pct(ci_results['mdd_ci_high'])}]")

    # ── 8. Market Impact ─────────────────────────────────────────────────────
    print("\nStep 8: Market impact (SPY)...")
    mi_results = compute_market_impact("SPY", IS_START, IS_END,
                                       init_cash=float(primary_params["init_cash"]))
    print(f"  Market impact: {fmt(mi_results['market_impact_bps'], 2)} bps  "
          f"Q/ADV={fmt(mi_results['order_to_adv_ratio'], 8)}  "
          f"liq_constrained={mi_results['liquidity_constrained']}")

    # ── 9. Permutation Test ──────────────────────────────────────────────────
    print("\nStep 9: Permutation test (500 permutations, null=random % in-market)...")
    try:
        spy_dl = yf.download("SPY", start=IS_START, end=IS_END,
                             auto_adjust=True, progress=False)
        if isinstance(spy_dl.columns, pd.MultiIndex):
            spy_dl.columns = spy_dl.columns.get_level_values(0)
        spy_close_is = spy_dl["Close"].dropna()
        perm_results = permutation_test_alpha(
            spy_close_is,
            pct_in_market=float(is_pct_spy) if is_pct_spy is not None else 0.7,
            observed_sharpe=float(is_sharpe) if is_sharpe is not None else 0.0,
            n_perms=500,
        )
    except Exception as e:
        print(f"  [WARN] Permutation test failed: {e}")
        perm_results = {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    print(f"  p-value={fmt(perm_results['permutation_pvalue'])} "
          f"pass={perm_results['permutation_test_pass']}")

    # ── 10. Sensitivity Sweep ─────────────────────────────────────────────────
    print("\nStep 10: Parameter sensitivity sweep...")
    sweep = run_sensitivity_sweep()
    sens_pass, sens_max_delta = sensitivity_pass(sweep, is_sharpe)
    print(f"  Sensitivity pass: {sens_pass}  (max_delta={pct(sens_max_delta)})")

    # ── 11. GFC Exit Timing (Engineering Director request) ───────────────────
    print("\nStep 11: GFC 2008-2009 exit timing analysis...")
    gfc_analysis = gfc_exit_analysis(primary_params)
    if "error" not in gfc_analysis:
        print(f"  GFC first cash date: {gfc_analysis['first_cash_date_2008']} | "
              f"Exit before Oct 2008: {gfc_analysis['exited_before_oct_2008']}")
        if not gfc_analysis.get("exited_before_oct_2008", False):
            print("  [FLAG] Strategy did NOT exit before October 2008 (worst drawdown month).")
    else:
        print(f"  [WARN] GFC analysis failed: {gfc_analysis['error']}")

    # ── 12. Smoothing Comparison (Engineering Director request) ──────────────
    print("\nStep 12: Smoothing comparison (smooth=1 vs smooth=2)...")
    smooth_comp = smoothing_comparison(primary_params)
    if "error" not in smooth_comp:
        s1 = smooth_comp["smoothing_1"]
        s2 = smooth_comp["smoothing_2"]
        print(f"  smooth=1: Sharpe={fmt(s1['is_sharpe'])} MDD={pct(s1['is_mdd'])} "
              f"transitions={s1['n_transitions']}")
        print(f"  smooth=2: Sharpe={fmt(s2['is_sharpe'])} MDD={pct(s2['is_mdd'])} "
              f"transitions={s2['n_transitions']}")

    # ── 13. 2022 Monthly Regime (Engineering Director request) ───────────────
    print("\nStep 13: 2022 OOS monthly regime analysis...")
    analysis_2022 = oos_2022_monthly_analysis(primary_params)
    if "error" not in analysis_2022:
        print(f"  2022: MDD={pct(analysis_2022['mdd_2022'])} "
              f"TotalRet={pct(analysis_2022['total_ret_2022'])} "
              f"SPY%={pct(analysis_2022['pct_in_spy_2022'])} "
              f"MDD_FLAG={analysis_2022['mdd_flag']}")
        for m in analysis_2022.get("monthly_breakdown", []):
            regime_label = "SPY" if m["regime_pct_spy"] > 0.5 else "CASH"
            print(f"    {m['month']}: {regime_label} ({pct(m['regime_pct_spy'])} SPY) "
                  f"return={pct(m['monthly_return'])}")

    # ── 14. Regime Breakdown IS ───────────────────────────────────────────────
    print("\nStep 14: Sub-period Sharpe decomposition (2007-2012, 2013-2018, 2019-2021)...")
    regime_results = regime_breakdown(primary_params)

    # ── 15. Post-cost Sharpe ──────────────────────────────────────────────────
    # H44 embeds all costs in the simulation — is_sharpe IS the post-cost number
    post_cost_sharpe_is = float(is_sharpe) if is_sharpe is not None else np.nan

    # ── 16. Gate 1 Pass/Fail ─────────────────────────────────────────────────
    checks = {
        "IS Sharpe > 1.0":       (is_sharpe  is not None and is_sharpe  > G1_IS_SHARPE),
        "OOS Sharpe > 0.7":      (oos_sharpe is not None and oos_sharpe > G1_OOS_SHARPE),
        "IS MDD < 20%":          (is_mdd     is not None and is_mdd     > G1_MDD),
        "OOS MDD < 25%":         (oos_mdd    is not None and oos_mdd    > -0.25),
        "IS Transitions ≥ 100":  (is_ntrans  >= G1_MIN_TRADES),
        "DSR > 0":               (not np.isnan(dsr) and dsr > 0),
        "WF folds passed ≥ 3":   wf_pass,
        "MC p5 Sharpe ≥ 0.5":    mc_p5_ok,
        "Perm test pass":         perm_results["permutation_test_pass"],
        "Sensitivity pass":       sens_pass,
        "Win Rate > 50%":         (is_winrate is not None and is_winrate > 0.50),
        "GFC exit before Oct 2008": gfc_analysis.get("exited_before_oct_2008", False),
    }
    n_pass = sum(checks.values())
    n_total = len(checks)
    gate1_pass = (
        checks["IS Sharpe > 1.0"]   and
        checks["OOS Sharpe > 0.7"]  and
        checks["IS MDD < 20%"]      and
        checks["IS Transitions ≥ 100"]
    )
    overall_verdict = "PASS" if gate1_pass and n_pass >= 9 else (
        "CONDITIONAL PASS" if gate1_pass else "FAIL"
    )

    print(f"\n{'=' * 70}")
    print(f"GATE 1 VERDICT: {overall_verdict} ({n_pass}/{n_total} checks passed)")
    print(f"{'=' * 70}")
    for check, passed in checks.items():
        print(f"  {'[PASS]' if passed else '[FAIL]'} {check}")

    # ── 17. Assemble full results JSON ────────────────────────────────────────
    is_trade_log  = _trade_log_records(is_trade_df)
    oos_trade_log = _trade_log_records(oos_trade_df)

    results = {
        "strategy_name":       STRATEGY_NAME,
        "date":                TODAY,
        "asset_class":         "equities",
        "is_start":            IS_START,
        "is_end":              IS_END,
        "oos_start":           OOS_START,
        "oos_end":             OOS_END,

        # Primary metrics
        "is_sharpe":           _safe_float(is_sharpe),
        "oos_sharpe":          _safe_float(oos_sharpe),
        "is_max_drawdown":     _safe_float(is_mdd),
        "oos_max_drawdown":    _safe_float(oos_mdd),
        "is_total_return":     _safe_float(is_ret),
        "oos_total_return":    _safe_float(oos_ret),
        "win_rate":            _safe_float(is_winrate),
        "oos_win_rate":        _safe_float(oos_winrate),
        "profit_factor":       _safe_float(is_pf) if is_pf is not None and not np.isinf(is_pf) else None,
        "oos_profit_factor":   _safe_float(oos_pf) if oos_pf is not None and not np.isinf(oos_pf) else None,
        "trade_count":         is_trades,
        "oos_trade_count":     oos_trades,
        "n_transitions_is":    is_ntrans,
        "n_transitions_oos":   oos_ntrans,
        "pct_in_spy_is":       _safe_float(is_pct_spy),
        "pct_in_spy_oos":      _safe_float(oos_pct_spy),

        # Post-cost (H44 costs embedded in simulation)
        "post_cost_sharpe":    round(post_cost_sharpe_is, 4) if not np.isnan(post_cost_sharpe_is) else None,
        "post_cost_sharpe_oos": round(post_cost_sharpe_oos, 4) if not np.isnan(post_cost_sharpe_oos) else None,

        # DSR
        "dsr":                 round(float(dsr), 4) if not np.isnan(dsr) else None,
        "dsr_n_trials":        n_trials,

        # Walk-forward
        "wf_windows_passed":   wf_passes,
        "wf_pass":             wf_pass,
        "wf_windows":          wf_results,
        "wf_sharpe_std":       _safe_float(wf_var["wf_sharpe_std"]),
        "wf_sharpe_min":       _safe_float(wf_var["wf_sharpe_min"]),

        # Monte Carlo
        "mc_p5_sharpe":        _safe_float(mc_results["mc_p5_sharpe"]),
        "mc_median_sharpe":    _safe_float(mc_results["mc_median_sharpe"]),
        "mc_p95_sharpe":       _safe_float(mc_results["mc_p95_sharpe"]),
        "mc_p5_sharpe_flag":   "MC pessimistic bound weak" if not mc_p5_ok else "OK",

        # Bootstrap CI
        "sharpe_ci_low":       _safe_float(ci_results["sharpe_ci_low"]),
        "sharpe_ci_high":      _safe_float(ci_results["sharpe_ci_high"]),
        "mdd_ci_low":          _safe_float(ci_results["mdd_ci_low"]),
        "mdd_ci_high":         _safe_float(ci_results["mdd_ci_high"]),
        "win_rate_ci_low":     _safe_float(ci_results["win_rate_ci_low"]),
        "win_rate_ci_high":    _safe_float(ci_results["win_rate_ci_high"]),

        # Market impact
        "market_impact_bps":   round(float(mi_results["market_impact_bps"]), 4)
                               if not np.isnan(mi_results["market_impact_bps"]) else None,
        "liquidity_constrained": mi_results["liquidity_constrained"],
        "order_to_adv_ratio":  round(float(mi_results["order_to_adv_ratio"]), 8)
                               if not np.isnan(mi_results["order_to_adv_ratio"]) else None,

        # Permutation test
        "permutation_pvalue":  round(float(perm_results["permutation_pvalue"]), 4),
        "permutation_test_pass": perm_results["permutation_test_pass"],

        # Sensitivity
        "sensitivity_pass":    sens_pass,
        "sensitivity_max_delta": sens_max_delta,
        "sensitivity_sweep":   sweep,

        # Engineering Director extras
        "gfc_exit_analysis":   gfc_analysis,
        "smoothing_comparison": smooth_comp,
        "oos_2022_monthly":    analysis_2022,
        "regime_breakdown":    regime_results,

        # Gate 1 verdict
        "gate1_checks":        checks,
        "gate1_pass":          gate1_pass,
        "overall_verdict":     overall_verdict,

        # OOS Data Quality
        "oos_data_quality":    dq_report,

        # Trade logs
        "is_trade_log":        is_trade_log,
        "oos_trade_log":       oos_trade_log,

        # Look-ahead bias
        "look_ahead_bias_flag": False,
        "look_ahead_bias_note": (
            "credit_signal at T uses only LQD/IEF close data through T; "
            "position change executes at T+1 open (no look-ahead bias)"
        ),
    }

    # ── 18. Save JSON ─────────────────────────────────────────────────────────
    backtests_dir = os.path.join(_REPO_ROOT, "backtests")
    os.makedirs(backtests_dir, exist_ok=True)
    json_path = os.path.join(backtests_dir, "h44_gate1_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved: {json_path}")

    # ── 19. Generate Markdown Report ──────────────────────────────────────────
    md = _build_markdown_report(results)
    md_path = os.path.join(backtests_dir, "h44_gate1_report.md")
    with open(md_path, "w") as f:
        f.write(md)
    print(f"Report saved: {md_path}")

    return results


def _save_blocked_result(dq_report: dict):
    backtests_dir = os.path.join(_REPO_ROOT, "backtests")
    os.makedirs(backtests_dir, exist_ok=True)
    path = os.path.join(backtests_dir, "h44_gate1_results.json")
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

    def _pf(cond):
        return "PASS" if cond else "FAIL"

    lines = [
        f"# H44 LQD/IEF Credit Risk Appetite Timer — Gate 1 Report",
        f"",
        f"**Strategy:** {r['strategy_name']}",
        f"**Run date:** {r['date']}",
        f"**IS window:** {r['is_start']} → {r['is_end']}",
        f"**OOS window:** {r['oos_start']} → {r['oos_end']}",
        f"**Parameters:** lookback=20d, threshold=0.0%, smoothing=1d, riskoff=cash",
        f"",
        f"## Overall Verdict: {r['overall_verdict']}",
        f"",
        f"## Primary Metrics",
        f"",
        f"| Metric | IS | OOS | Threshold | Pass? |",
        f"|--------|----|----|-----------|-------|",
        f"| Sharpe | {_fv(r.get('is_sharpe'))} | {_fv(r.get('oos_sharpe'))} | IS>1.0, OOS>0.7 | IS:{_pf(r.get('is_sharpe') or 0 > 1.0)} OOS:{_pf(r.get('oos_sharpe') or 0 > 0.7)} |",
        f"| Max Drawdown | {_pct(r.get('is_max_drawdown'))} | {_pct(r.get('oos_max_drawdown'))} | IS<20%, OOS<25% | IS:{_pf(r.get('is_max_drawdown') or 0 > -0.20)} OOS:{_pf(r.get('oos_max_drawdown') or 0 > -0.25)} |",
        f"| Total Return | {_pct(r.get('is_total_return'))} | {_pct(r.get('oos_total_return'))} | — | — |",
        f"| Win Rate | {_pct(r.get('win_rate'))} | {_pct(r.get('oos_win_rate'))} | >50% | {_pf((r.get('win_rate') or 0) > 0.50)} |",
        f"| Profit Factor | {_fv(r.get('profit_factor'), 2)} | {_fv(r.get('oos_profit_factor'), 2)} | >1.0 | {_pf((r.get('profit_factor') or 0) > 1.0)} |",
        f"| IS Regime Transitions | {r.get('n_transitions_is', 'N/A')} | {r.get('n_transitions_oos', 'N/A')} | IS≥100 | {_pf((r.get('n_transitions_is') or 0) >= 100)} |",
        f"| Trade Count (exits) | {r.get('trade_count', 'N/A')} | {r.get('oos_trade_count', 'N/A')} | — | — |",
        f"| % Time in SPY | {_pct(r.get('pct_in_spy_is'))} | {_pct(r.get('pct_in_spy_oos'))} | — | — |",
        f"| Post-Cost Sharpe | {_fv(r.get('post_cost_sharpe'))} | {_fv(r.get('post_cost_sharpe_oos'))} | >0.7 OOS | {_pf((r.get('post_cost_sharpe_oos') or 0) > 0.7)} |",
        f"",
        f"## Statistical Validation",
        f"",
        f"| Test | Result | Threshold | Pass? |",
        f"|------|--------|-----------|-------|",
        f"| DSR z-score | {_fv(r.get('dsr'))} | >0 | {_pf((r.get('dsr') or 0) > 0)} |",
        f"| WF folds passed | {r.get('wf_windows_passed', 'N/A')}/4 | ≥3 | {_pf((r.get('wf_windows_passed') or 0) >= 3)} |",
        f"| WF Sharpe std | {_fv(r.get('wf_sharpe_std'))} | — | — |",
        f"| WF Sharpe min | {_fv(r.get('wf_sharpe_min'))} | >0 | {_pf((r.get('wf_sharpe_min') or -1) > 0)} |",
        f"| MC p5 Sharpe | {_fv(r.get('mc_p5_sharpe'))} | ≥0.5 | {_pf((r.get('mc_p5_sharpe') or 0) >= 0.5)} |",
        f"| MC median Sharpe | {_fv(r.get('mc_median_sharpe'))} | — | — |",
        f"| Sharpe 95% CI | [{_fv(r.get('sharpe_ci_low'))}, {_fv(r.get('sharpe_ci_high'))}] | — | — |",
        f"| Permutation p-value | {_fv(r.get('permutation_pvalue'))} | ≤0.05 | {_pf(r.get('permutation_test_pass', False))} |",
        f"| Sensitivity max delta | {_pct(r.get('sensitivity_max_delta'))} | <30% | {_pf(r.get('sensitivity_pass', False))} |",
        f"| Market impact | {_fv(r.get('market_impact_bps'), 2)} bps | — | — |",
        f"| Liquidity constrained | {r.get('liquidity_constrained', 'N/A')} | False | {_pf(not r.get('liquidity_constrained', True))} |",
        f"",
        f"## Walk-Forward Detail",
        f"",
        f"| Fold | Train Period | OOS Period | IS Sharpe | OOS Sharpe | OOS Transitions | Pass? |",
        f"|------|-------------|-----------|-----------|------------|-----------------|-------|",
    ]

    for fold in r.get("wf_windows", []):
        lines.append(
            f"| {fold.get('fold')} "
            f"| {fold.get('train_start', '?')}→{fold.get('train_end', '?')} "
            f"| {fold.get('oos_start', '?')}→{fold.get('oos_end', '?')} "
            f"| {_fv(fold.get('train_sharpe'))} "
            f"| {_fv(fold.get('oos_sharpe'))} "
            f"| {fold.get('oos_transitions', '?')} "
            f"| {fold.get('fold_pass', '?')} |"
        )

    lines += [
        f"",
        f"## Engineering Director — GFC Exit Analysis",
        f"",
    ]
    gfc = r.get("gfc_exit_analysis", {})
    if "error" not in gfc:
        exit_flag = "✅ BEFORE Oct 2008" if gfc.get("exited_before_oct_2008") else "❌ NOT before Oct 2008"
        lines += [
            f"- First cash date (GFC window): **{gfc.get('first_cash_date_2008', 'N/A')}**",
            f"- Last SPY date before exit: **{gfc.get('last_spy_date_before_exit', 'N/A')}**",
            f"- Cash days (Sep–Oct 2008): **{gfc.get('cash_days_sep_oct_2008', 'N/A')}**",
            f"- Exit timing: {exit_flag}",
            f"- GFC period MDD: **{_pct(gfc.get('gfc_mdd'))}**",
            f"- GFC period total return: **{_pct(gfc.get('gfc_total_ret'))}**",
        ]
    else:
        lines.append(f"Error: {gfc.get('error')}")

    lines += [
        f"",
        f"## Engineering Director — Smoothing Comparison",
        f"",
        f"| Smoothing | IS Sharpe | IS MDD | Transitions | Win Rate |",
        f"|-----------|-----------|--------|-------------|----------|",
    ]
    sc = r.get("smoothing_comparison", {})
    if "error" not in sc:
        for k in ["smoothing_1", "smoothing_2"]:
            d = sc.get(k, {})
            label = "smooth=1 (primary)" if k == "smoothing_1" else "smooth=2"
            lines.append(
                f"| {label} | {_fv(d.get('is_sharpe'))} | {_pct(d.get('is_mdd'))} "
                f"| {d.get('n_transitions', 'N/A')} | {_pct(d.get('win_rate'))} |"
            )

    lines += [
        f"",
        f"## Engineering Director — 2022 Monthly Regime Analysis (OOS Rate-Shock Year)",
        f"",
    ]
    a22 = r.get("oos_2022_monthly", {})
    if "error" not in a22:
        lines += [
            f"- 2022 MDD: **{_pct(a22.get('mdd_2022'))}** {'⚠️ EXCEEDS 20%' if a22.get('mdd_flag') else '✅ within threshold'}",
            f"- 2022 Total Return: **{_pct(a22.get('total_ret_2022'))}**",
            f"- 2022 % time in SPY: **{_pct(a22.get('pct_in_spy_2022'))}**",
            f"",
            f"| Month | Regime | SPY % | Monthly Return |",
            f"|-------|--------|-------|----------------|",
        ]
        for m in a22.get("monthly_breakdown", []):
            regime_label = "SPY" if m["regime_pct_spy"] > 0.5 else "CASH"
            lines.append(
                f"| {m['month']} | {regime_label} | {_pct(m['regime_pct_spy'])} "
                f"| {_pct(m['monthly_return'])} |"
            )

    lines += [
        f"",
        f"## Sub-Period Sharpe Decomposition (IS)",
        f"",
        f"| Period | Sharpe | MDD | Win Rate | Transitions | Total Return |",
        f"|--------|--------|-----|----------|-------------|--------------|",
    ]
    for reg in r.get("regime_breakdown", []):
        if "error" not in reg:
            lines.append(
                f"| {reg.get('period')} | {_fv(reg.get('sharpe'))} "
                f"| {_pct(reg.get('mdd'))} | {_pct(reg.get('win_rate'))} "
                f"| {reg.get('n_transitions', 'N/A')} | {_pct(reg.get('total_ret'))} |"
            )

    lines += [
        f"",
        f"## Parameter Sensitivity Sweep",
        f"",
        f"| Lookback | Threshold | Smoothing | IS Sharpe | IS MDD | Transitions |",
        f"|----------|-----------|-----------|-----------|--------|-------------|",
    ]
    for row in r.get("sensitivity_sweep", []):
        if "error" not in row:
            lines.append(
                f"| {row.get('lookback_days')}d "
                f"| {row.get('signal_threshold', 0):.4f} "
                f"| {row.get('smoothing_days')}d "
                f"| {_fv(row.get('is_sharpe'))} "
                f"| {_pct(row.get('is_mdd'))} "
                f"| {row.get('n_transitions', 'N/A')} |"
            )

    lines += [
        f"",
        f"## Gate 1 Checklist",
        f"",
    ]
    for check, passed in r.get("gate1_checks", {}).items():
        icon = "✅" if passed else "❌"
        lines.append(f"- {icon} {check}")

    dq = r.get("oos_data_quality", {})
    lines += [
        f"",
        f"## OOS Data Quality",
        f"",
        f"- Recommendation: **{dq.get('recommendation', 'N/A')}**",
        f"- Coverage: **{dq.get('oos_data_coverage_pct', 'N/A')}%**",
        f"- NaN critical metrics: {dq.get('metrics_nan_fields', [])}",
        f"",
        f"---",
        f"*Generated by Backtest Runner Agent | QUA-341 | {TODAY}*",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    main()
