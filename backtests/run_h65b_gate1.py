"""
Gate 1 Backtest Runner — H65b US Dollar Strength Regime v2.0 (VIX Dual-Filter)
Engineering Director (QUA-224)

v2.0 design: Asymmetric state machine with VIX dual-filter.
  Enter risk-off: DXY_mom > threshold AND VIX > vix_threshold
  Exit risk-off:  DXY_mom < threshold AND VIX < vix_threshold (BOTH must clear)
  Intermediate: HOLD CURRENT STATE (sticky)

v1.0 failed: IS Sharpe=0.676, 2022 Sharpe=-1.876, WF=1/4 (QUA-213)
v2.0 targets: IS Sharpe > 1.0, 2022 Sharpe > 0.0, WF >= 3/4

Outputs:
  backtests/h65b_dollar_strength_regime_v2_2026-06-12.json
  backtests/h65b_dollar_strength_regime_v2_2026-06-12_report.html
  backtests/h65b_dollar_strength_regime_v2_2026-06-12_verdict.txt
  backtests/h65b_dollar_strength_regime_v2_2026-06-12_trades.csv
  backtests/h65b_dollar_strength_regime_v2_2026-06-12_sweep.csv

IS  window: 2003-01-01 to 2023-12-31 (20 years)
OOS window: 2024-01-01 to 2026-06-12

QUA-224 variants tested:
  Variant 1 (baseline): lookback=60, vix_thresh=20, thresh=0.0, SHY
  Variant 2 (tight VIX): lookback=60, vix_thresh=18, thresh=0.0, SHY
  Variant 3 (wide VIX):  lookback=60, vix_thresh=25, thresh=0.0, SHY

Parameter sweep grid:
  lookback_days:    [40, 60, 80]
  signal_threshold: [-0.005, 0.0, 0.005]
  vix_threshold:    [18, 20, 25]
  riskoff_asset:    ["SHY", "BIL"]

Critical QUA-224 requirements:
  1. Report IS trade count FIRST; flag to Research Director if < 120
  2. Report 2022 sub-period Sharpe (must be > 0.0; v1.0 was -1.876)
  3. Walk-forward consistency >= 3/4 windows
  4. Permutation p-value < 0.05
  5. Sub-period diagnostics: pre-GFC, GFC, 2014-2015 dollar bull, 2022 rate-shock, AI bull 2023
"""

import json
import logging
import sys
import traceback
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from strategies.h65b_dollar_strength_regime_v2 import (
    PARAMETERS,
    TRADING_DAYS_PER_YEAR,
    download_data,
    compute_dxy_signal,
    apply_asymmetric_state_machine,
    simulate_h65b,
    run_backtest,
)

# ── Config ─────────────────────────────────────────────────────────────────────
IS_START  = "2003-01-01"
IS_END    = "2023-12-31"
OOS_START = "2024-01-01"
OOS_END   = "2026-06-12"

REPORT_DATE = "2026-06-12"
STRATEGY_NAME = "h65b_dollar_strength_regime_v2"
OUTPUT_DIR = REPO_ROOT / "backtests"

GATE_IS_SHARPE  = 1.0
GATE_OOS_SHARPE = 0.7
GATE_IS_MDD     = -0.20
GATE_IS_CAGR    = 0.10
GATE_MIN_TRADES = 100
GATE_PERM_PVAL  = 0.05
QUA224_MIN_TRADES_FLAG = 120   # flag to Research Director if IS trades < 120

# QUA-224 required variants
VARIANT_BASELINE = {"lookback_days": 60, "vix_threshold": 20.0, "signal_threshold": 0.0, "riskoff_asset": "SHY"}
VARIANT_TIGHT_VIX = {"lookback_days": 60, "vix_threshold": 18.0, "signal_threshold": 0.0, "riskoff_asset": "SHY"}
VARIANT_WIDE_VIX  = {"lookback_days": 60, "vix_threshold": 25.0, "signal_threshold": 0.0, "riskoff_asset": "SHY"}

SWEEP_GRID = {
    "lookback_days":    [40, 60, 80],
    "signal_threshold": [-0.005, 0.0, 0.005],
    "vix_threshold":    [18.0, 20.0, 25.0],
    "riskoff_asset":    ["SHY", "BIL"],
}

# Expanding-window walk-forward
WF_WINDOWS = [
    ("2003-01-01", "2010-12-31", "2011-01-01", "2015-12-31"),  # WF1: post-GFC, no GFC in OOS
    ("2003-01-01", "2013-12-31", "2014-01-01", "2017-12-31"),  # WF2: dollar bull OOS
    ("2003-01-01", "2016-12-31", "2017-01-01", "2020-12-31"),  # WF3: late bull OOS
    ("2003-01-01", "2018-12-31", "2019-01-01", "2023-12-31"),  # WF4: COVID+2022 OOS
]

# Sub-period diagnostics (QUA-224 requirements)
SUB_PERIODS = {
    "pre_gfc_only":           ("2003-01-01", "2007-12-31"),
    "gfc_only":               ("2007-01-01", "2009-12-31"),
    "dollar_bull_2014_15":    ("2014-01-01", "2015-12-31"),  # v1.0 false positive — expect fix
    "rate_shock_2022":        ("2022-01-01", "2022-12-31"),  # v1.0 Sharpe=-1.876 — critical fix
    "ai_bull_2023":           ("2023-01-01", "2023-12-31"),
    "post_gfc_2010_2019":     ("2010-01-01", "2019-12-31"),
}

DOTCOM_PERIOD = ("2000-01-01", "2002-12-31")


# ── Single-window Backtest ─────────────────────────────────────────────────────

def backtest_window(start, end, params, label=""):
    try:
        result = run_backtest(start=start, end=end, params=params)
        if label:
            logger.info("  %s: Sharpe=%.3f CAGR=%.1f%% MDD=%.1f%% trades=%d",
                        label, result["sharpe"], result["cagr"] * 100,
                        result["max_drawdown"] * 100, result["trade_count"])
        return result
    except Exception as e:
        logger.error("  %s FAILED: %s", label or f"{start}→{end}", e)
        traceback.print_exc()
        return {
            "sharpe": np.nan, "cagr": 0.0, "max_drawdown": 0.0,
            "trade_count": 0, "total_return": 0.0, "error": str(e),
        }


# ── Variant Comparison ────────────────────────────────────────────────────────

def run_variant_comparison() -> dict:
    """
    QUA-224: Test three VIX threshold variants on IS period.
    """
    logger.info("=== VARIANT COMPARISON (QUA-224) ===")

    params_base = PARAMETERS.copy(); params_base.update(VARIANT_BASELINE)
    params_tight = PARAMETERS.copy(); params_tight.update(VARIANT_TIGHT_VIX)
    params_wide = PARAMETERS.copy(); params_wide.update(VARIANT_WIDE_VIX)

    r_base  = backtest_window(IS_START, IS_END, params_base,  "Variant-1 vix_thresh=20")
    r_tight = backtest_window(IS_START, IS_END, params_tight, "Variant-2 vix_thresh=18")
    r_wide  = backtest_window(IS_START, IS_END, params_wide,  "Variant-3 vix_thresh=25")

    sh_base  = r_base.get("sharpe", np.nan)
    sh_tight = r_tight.get("sharpe", np.nan)
    sh_wide  = r_wide.get("sharpe", np.nan)

    logger.info("  Variant-1 (vix_thresh=20): IS Sharpe=%.4f MDD=%.2f%% Trades=%d",
                sh_base  if not np.isnan(sh_base)  else 0.0,
                r_base.get("max_drawdown", 0) * 100, r_base.get("trade_count", 0))
    logger.info("  Variant-2 (vix_thresh=18): IS Sharpe=%.4f MDD=%.2f%% Trades=%d",
                sh_tight if not np.isnan(sh_tight) else 0.0,
                r_tight.get("max_drawdown", 0) * 100, r_tight.get("trade_count", 0))
    logger.info("  Variant-3 (vix_thresh=25): IS Sharpe=%.4f MDD=%.2f%% Trades=%d",
                sh_wide  if not np.isnan(sh_wide)  else 0.0,
                r_wide.get("max_drawdown", 0) * 100, r_wide.get("trade_count", 0))

    # Select variant with highest IS Sharpe for Gate 1 submission
    candidates = [
        ("baseline_vix20", params_base, sh_base, r_base),
        ("tight_vix18",    params_tight, sh_tight, r_tight),
        ("wide_vix25",     params_wide, sh_wide, r_wide),
    ]
    valid = [(name, p, sh, r) for name, p, sh, r in candidates if not np.isnan(sh)]
    if valid:
        best = max(valid, key=lambda x: x[2])
        selected_name, selected_params, selected_sharpe, _ = best
    else:
        selected_name = "baseline_vix20"
        selected_params = params_base

    logger.info("  Selected: %s (IS Sharpe=%.4f)", selected_name,
                selected_sharpe if valid else 0.0)

    def _v(r, sh):
        return {
            "is_sharpe": float(sh) if not np.isnan(sh) else None,
            "is_cagr": float(r.get("cagr", 0.0)),
            "is_mdd": float(r.get("max_drawdown", 0.0)),
            "is_trades": int(r.get("trade_count", 0)),
            "n_transitions": int(r.get("n_transitions", 0)),
            "pct_in_spy": float(r.get("pct_in_spy", 0.0)),
        }

    return {
        "variant_1_baseline": {"params": VARIANT_BASELINE, **_v(r_base, sh_base)},
        "variant_2_tight_vix": {"params": VARIANT_TIGHT_VIX, **_v(r_tight, sh_tight)},
        "variant_3_wide_vix": {"params": VARIANT_WIDE_VIX, **_v(r_wide, sh_wide)},
        "selected_variant": selected_name,
        "selected_params": selected_params,
        "note": (
            "QUA-224 v2.0 tests three VIX threshold variants. "
            "Asymmetric exit is required design — not varied. "
            "Selected variant used for full Gate 1 analysis."
        ),
    }


# ── Parameter Sweep ───────────────────────────────────────────────────────────

def run_parameter_sweep(selected_params: dict) -> pd.DataFrame:
    """IS-only sweep over parameter combinations."""
    import itertools
    keys = list(SWEEP_GRID.keys())
    values = [SWEEP_GRID[k] for k in keys]
    combos = list(itertools.product(*values))
    logger.info("=== PARAMETER SWEEP: %d combinations ===", len(combos))

    records = []
    for idx, combo in enumerate(combos):
        p = PARAMETERS.copy()
        for k, v in zip(keys, combo):
            p[k] = v

        try:
            result = run_backtest(IS_START, IS_END, p)
            rec = {k: v for k, v in zip(keys, combo)}
            rec["is_sharpe"] = result["sharpe"]
            rec["is_cagr"] = result["cagr"]
            rec["is_mdd"] = result["max_drawdown"]
            rec["is_trades"] = result["trade_count"]
            rec["is_win_rate"] = result["win_rate"]
            rec["is_profit_factor"] = result["profit_factor"]
            rec["is_pct_in_spy"] = result["pct_in_spy"]
            rec["is_transitions"] = result["n_transitions"]
        except Exception as e:
            rec = {k: v for k, v in zip(keys, combo)}
            rec.update({
                "is_sharpe": np.nan, "is_cagr": 0.0, "is_mdd": 0.0,
                "is_trades": 0, "is_win_rate": 0.0, "is_profit_factor": 0.0,
                "is_pct_in_spy": 0.0, "is_transitions": 0,
            })
        records.append(rec)

        if (idx + 1) % 15 == 0:
            valid = [r for r in records if not np.isnan(r.get("is_sharpe", float("nan")))]
            if valid:
                best = max(valid, key=lambda r: r["is_sharpe"])
                logger.info("  Progress %d/%d — best IS Sharpe: %.3f",
                            idx + 1, len(combos), best["is_sharpe"])

    sweep_df = pd.DataFrame(records)
    valid_count = sweep_df["is_sharpe"].notna().sum()
    logger.info("Sweep complete. Valid: %d/%d", valid_count, len(combos))
    return sweep_df


# ── Walk-Forward ──────────────────────────────────────────────────────────────

def run_walk_forward(params: dict) -> dict:
    """4-window expanding walk-forward."""
    logger.info("=== WALK-FORWARD (4 expanding windows) ===")
    wf_results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(WF_WINDOWS):
        is_r  = backtest_window(is_s, is_e, params, f"WF[{i+1}] IS {is_s}→{is_e}")
        oos_r = backtest_window(oos_s, oos_e, params, f"WF[{i+1}] OOS {oos_s}→{oos_e}")
        is_sh  = is_r.get("sharpe", np.nan)
        oos_sh = oos_r.get("sharpe", np.nan)
        wf_results.append({
            "window": i + 1,
            "is_start": is_s, "is_end": is_e,
            "oos_start": oos_s, "oos_end": oos_e,
            "is_sharpe":  float(is_sh)  if not np.isnan(is_sh)  else None,
            "oos_sharpe": float(oos_sh) if not np.isnan(oos_sh) else None,
            "oos_pass": bool(oos_sh > GATE_OOS_SHARPE) if not np.isnan(oos_sh) else False,
        })

    oos_sharpes = [w["oos_sharpe"] for w in wf_results
                   if w["oos_sharpe"] is not None and not np.isnan(w["oos_sharpe"])]
    windows_passed = sum(1 for w in wf_results if w["oos_pass"])
    wf_sharpe_std = float(np.std(oos_sharpes)) if len(oos_sharpes) > 1 else 0.0
    wf_sharpe_min = float(np.min(oos_sharpes)) if oos_sharpes else None

    logger.info("  WF: %d/4 OOS windows passed (Sharpe > %.1f)", windows_passed, GATE_OOS_SHARPE)
    logger.info("  WF OOS Sharpes: %s",
                [f"{s:.3f}" if s is not None else "N/A" for s in oos_sharpes])

    non_gfc_sharpes = []
    for w in wf_results:
        if w["oos_start"] in ("2011-01-01", "2014-01-01"):
            if w["oos_sharpe"] is not None:
                non_gfc_sharpes.append(w["oos_sharpe"])
    gfc_dependency_flag = (
        bool(all(s < 0.5 for s in non_gfc_sharpes))
        if non_gfc_sharpes
        else None
    )
    if gfc_dependency_flag:
        logger.warning(
            "  GFC-DEPENDENCY FLAG: non-GFC OOS folds show Sharpe < 0.5 — "
            "strategy may be GFC-dependent."
        )

    return {
        "windows": wf_results,
        "windows_passed": windows_passed,
        "wf_sharpe_std": wf_sharpe_std,
        "wf_sharpe_min": wf_sharpe_min,
        "gfc_dependency_flag": gfc_dependency_flag,
    }


# ── Statistical Rigor Pipeline ─────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    sharpes = []
    for _ in range(n_sims):
        sample = np.random.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
        sharpes.append(s)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe": float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = T // block_len
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, T - block_len + 1, size=n_blocks)
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


def permutation_test_regime_signal(
    daily_df: pd.DataFrame,
    spy_returns: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 1000,
) -> dict:
    """
    Regime-signal permutation test (block shuffle of allocation vector).
    Null: dual-filter signal (DXY+VIX) has no predictive power for SPY returns.
    """
    if len(spy_returns) == 0 or daily_df.empty:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False,
                "permutation_n": 0, "permutation_note": "insufficient data"}

    regimes = daily_df["regime"].values
    spy_ret_aligned = spy_returns[:len(regimes)]

    blocks = []
    if len(regimes) == 0:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False,
                "permutation_n": 0, "permutation_note": "no regime data"}

    current = regimes[0]
    count = 1
    for r in regimes[1:]:
        if r == current:
            count += 1
        else:
            blocks.append((current, count))
            current = r
            count = 1
    blocks.append((current, count))
    n_blocks = len(blocks)

    permuted_sharpes = []
    for _ in range(n_perms):
        perm_blocks = list(np.random.permutation(n_blocks))
        perm_regimes = []
        for bi in perm_blocks:
            label, length = blocks[bi]
            perm_regimes.extend([label] * length)
        perm_regimes = perm_regimes[:len(regimes)]
        while len(perm_regimes) < len(regimes):
            perm_regimes.append(blocks[-1][0])

        perm_hold = np.array([1.0 if r == "SPY" else 0.0 for r in perm_regimes])
        perm_strategy_ret = perm_hold * spy_ret_aligned
        if perm_strategy_ret.std() > 0:
            s = float(perm_strategy_ret.mean() / perm_strategy_ret.std()
                      * np.sqrt(TRADING_DAYS_PER_YEAR))
        else:
            s = 0.0
        permuted_sharpes.append(s)

    p_value = float(np.mean(np.array(permuted_sharpes) >= observed_sharpe))
    logger.info("  Permutation test: p=%.4f (n_perms=%d, n_blocks=%d) — %s",
                p_value, n_perms, n_blocks,
                "PASS" if p_value <= GATE_PERM_PVAL else "FAIL")

    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": bool(p_value <= GATE_PERM_PVAL),
        "permutation_n": n_perms,
        "permutation_n_blocks": n_blocks,
        "permutation_pvalue_note": (
            "Block-shuffle permutation of regime allocation vector. "
            "p < 0.05 confirms DXY+VIX dual-filter has genuine predictive power."
        ),
    }


def compute_market_impact_spy(spy_daily: pd.DataFrame, order_notional: float = 25000.0) -> dict:
    prices = spy_daily["Close"]
    volumes = spy_daily["Volume"]
    adv = float(volumes.rolling(20).mean().iloc[-1])
    sigma = float(prices.pct_change().rolling(20).std().iloc[-1])
    avg_price = float(prices.iloc[-252:].mean())
    order_qty = order_notional / avg_price
    k = 0.1
    impact_pct = k * sigma * np.sqrt(order_qty / (adv + 1e-8))
    impact_bps = impact_pct * 10000
    return {
        "market_impact_bps": float(impact_bps),
        "liquidity_constrained": bool(order_qty > 0.01 * adv),
        "order_to_adv_ratio": float(order_qty / (adv + 1e-8)),
        "adv_shares": float(adv),
        "sigma_daily": float(sigma),
    }


def compute_dsr(returns_series: pd.Series, n_trials: int) -> float:
    """Deflated Sharpe Ratio (Lopez de Prado 2018)."""
    if len(returns_series) < 10 or n_trials <= 0:
        return 0.0
    r = returns_series.dropna().values
    n = len(r)
    if n < 4:
        return 0.0
    from scipy.stats import norm
    sr = r.mean() / (r.std() + 1e-10) * np.sqrt(TRADING_DAYS_PER_YEAR)
    skew = float(pd.Series(r).skew())
    kurt = float(pd.Series(r).kurt())
    sr_star = np.sqrt(2) * sr * np.sqrt(np.log(n_trials) / (np.pi * np.log(n)))
    sr_var = (1 + 0.5 * sr**2 - skew * sr + (kurt / 4) * sr**2) / n
    dsr = float(norm.cdf((sr - sr_star) / (np.sqrt(sr_var) + 1e-10)))
    return round(dsr, 6)


# ── Sub-period Diagnostics ────────────────────────────────────────────────────

def run_sub_period_diagnostics(params: dict) -> dict:
    """
    Run sub-period backtests per QUA-224 requirements.
    Critical: 2022 rate-shock Sharpe must be > 0.0 (v1.0 was -1.876).
    """
    logger.info("=== SUB-PERIOD DIAGNOSTICS ===")
    results = {}
    for name, (s, e) in SUB_PERIODS.items():
        r = backtest_window(s, e, params, f"  sub/{name}")
        results[name] = {
            "start": s, "end": e,
            "sharpe": float(r["sharpe"]) if not np.isnan(r["sharpe"]) else None,
            "cagr": float(r["cagr"]),
            "max_drawdown": float(r["max_drawdown"]),
            "trade_count": int(r["trade_count"]),
            "pct_in_spy": float(r.get("pct_in_spy", 0.0)),
            "transitions_per_year": float(r.get("transitions_per_year", 0.0)),
            "total_return": float(r["total_return"]),
        }
        if name == "rate_shock_2022":
            sh = results[name]["sharpe"]
            if sh is not None and sh > 0.0:
                logger.info("  *** 2022 sub-period FIXED: Sharpe=%.3f (v1.0 was -1.876) ***", sh)
            elif sh is not None:
                logger.warning("  *** 2022 sub-period STILL NEGATIVE: Sharpe=%.3f ***", sh)

    # 2000-2002 dot-com pre-IS diagnostic (SHY started 2002-07-30 — use BIL)
    logger.info("  Dot-com sub-period 2000-2002 (pre-IS diagnostic, BIL as risk-off)...")
    params_dotcom = params.copy()
    params_dotcom["riskoff_asset"] = "BIL"
    r_dotcom = backtest_window(DOTCOM_PERIOD[0], DOTCOM_PERIOD[1], params_dotcom,
                               "  sub/dotcom_2000_02_BIL")
    results["dotcom_2000_2002"] = {
        "start": DOTCOM_PERIOD[0], "end": DOTCOM_PERIOD[1],
        "sharpe": float(r_dotcom["sharpe"]) if not np.isnan(r_dotcom["sharpe"]) else None,
        "cagr": float(r_dotcom["cagr"]),
        "max_drawdown": float(r_dotcom["max_drawdown"]),
        "trade_count": int(r_dotcom["trade_count"]),
        "pct_in_spy": float(r_dotcom.get("pct_in_spy", 0.0)),
        "transitions_per_year": float(r_dotcom.get("transitions_per_year", 0.0)),
        "total_return": float(r_dotcom["total_return"]),
        "risk_off_asset": "BIL",
        "note": (
            "Pre-IS period. SHY started 2002-07-30; BIL used as risk-off substitute. "
            "QUA-224 requires explicit MDD reporting for this period."
        ),
    }
    logger.info("  Dot-com 2000-2002: MDD=%.2f%% Sharpe=%.3f",
                r_dotcom.get("max_drawdown", 0) * 100,
                r_dotcom.get("sharpe", float("nan")))

    return results


# ── Gate 1 Verdict ────────────────────────────────────────────────────────────

def evaluate_gate1(is_metrics: dict, oos_metrics: dict, wf: dict, rigor: dict,
                   variant_info: dict, sub: dict) -> dict:
    is_sharpe  = is_metrics.get("sharpe", 0.0) or 0.0
    oos_sharpe = oos_metrics.get("sharpe", 0.0) or 0.0
    is_mdd     = is_metrics.get("max_drawdown", 0.0) or 0.0
    is_cagr    = is_metrics.get("cagr", 0.0) or 0.0
    is_trades  = is_metrics.get("trade_count", 0)
    perm_pass  = rigor.get("permutation_test_pass", False)
    wf_passed  = wf.get("windows_passed", 0)

    oos_degrade = ((is_sharpe - oos_sharpe) / is_sharpe
                   if is_sharpe > 0 else 1.0)

    # QUA-224 critical: 2022 sub-period Sharpe must be > 0.0
    sharpe_2022 = sub.get("rate_shock_2022", {}).get("sharpe")
    sharpe_2022_pass = bool(sharpe_2022 is not None and sharpe_2022 > 0.0)

    criteria = {
        "IS_Sharpe":          {"value": round(float(is_sharpe), 4),
                               "threshold": f"> {GATE_IS_SHARPE}",
                               "pass": bool(is_sharpe > GATE_IS_SHARPE)},
        "OOS_Sharpe":         {"value": round(float(oos_sharpe), 4),
                               "threshold": f"> {GATE_OOS_SHARPE}",
                               "pass": bool(oos_sharpe > GATE_OOS_SHARPE)},
        "IS_MaxDrawdown":     {"value": round(is_mdd * 100, 2),
                               "threshold": "> -20%",
                               "pass": bool(is_mdd > GATE_IS_MDD)},
        "IS_CAGR":            {"value": round(is_cagr * 100, 2),
                               "threshold": f">= {GATE_IS_CAGR*100:.0f}%",
                               "pass": bool(is_cagr >= GATE_IS_CAGR)},
        "IS_TradeCount":      {"value": is_trades,
                               "threshold": f">= {GATE_MIN_TRADES}",
                               "pass": bool(is_trades >= GATE_MIN_TRADES)},
        "WF_Consistency":     {"value": f"{wf_passed}/4",
                               "threshold": ">= 3/4 windows",
                               "pass": bool(wf_passed >= 3)},
        "Permutation_pvalue": {"value": round(float(rigor.get("permutation_pvalue", 1.0)), 4),
                               "threshold": f"< {GATE_PERM_PVAL}",
                               "pass": bool(perm_pass),
                               "note": "CRITICAL"},
        "Sharpe_2022":        {"value": round(float(sharpe_2022), 4) if sharpe_2022 is not None else "N/A",
                               "threshold": "> 0.0 (v1.0 was -1.876)",
                               "pass": sharpe_2022_pass,
                               "note": "QUA-224 critical fix target"},
    }

    all_pass = all(c["pass"] for c in criteria.values())

    # Trade count flag per QUA-224
    trade_count_flag = None
    if is_trades < QUA224_MIN_TRADES_FLAG:
        trade_count_flag = (
            f"IS trade count {is_trades} < {QUA224_MIN_TRADES_FLAG}. "
            "QUA-224 requires flagging to Research Director. "
            "VIX filter may have reduced trades below viable threshold."
        )

    return {
        "criteria": criteria,
        "verdict": "PASS" if all_pass else "FAIL",
        "oos_degradation": round(float(oos_degrade), 4),
        "selected_variant": variant_info.get("selected_variant", "unknown"),
        "sharpe_2022": sharpe_2022,
        "sharpe_2022_fixed": sharpe_2022_pass,
        "trade_count_flag": trade_count_flag,
    }


# ── Report Generators ─────────────────────────────────────────────────────────

def generate_verdict_txt(is_m, oos_m, verdict, sweep_df, wf, rigor, sub,
                         variant_info) -> str:
    sv = variant_info.get("selected_variant", "unknown")
    v1 = variant_info.get("variant_1_baseline", {})
    v2 = variant_info.get("variant_2_tight_vix", {})
    v3 = variant_info.get("variant_3_wide_vix", {})

    lines = [
        "=" * 72,
        "GATE 1 VERDICT — H65b Dollar Strength Regime v2.0 (VIX Dual-Filter)",
        f"Report Date: {REPORT_DATE}",
        "=" * 72,
        "",
        f"OVERALL VERDICT: {verdict['verdict']}",
        f"Selected variant: {sv}",
        "",
        "── QUA-224 VARIANT COMPARISON ───────────────────────────────────────────",
        f"  Variant-1 (vix_thresh=20): IS Sharpe={v1.get('is_sharpe', 'N/A')} "
        f"MDD={v1.get('is_mdd', 0)*100:.2f}% Trades={v1.get('is_trades', 0)}",
        f"  Variant-2 (vix_thresh=18): IS Sharpe={v2.get('is_sharpe', 'N/A')} "
        f"MDD={v2.get('is_mdd', 0)*100:.2f}% Trades={v2.get('is_trades', 0)}",
        f"  Variant-3 (vix_thresh=25): IS Sharpe={v3.get('is_sharpe', 'N/A')} "
        f"MDD={v3.get('is_mdd', 0)*100:.2f}% Trades={v3.get('is_trades', 0)}",
        f"  Selected for Gate 1: {sv}",
        "",
        "── CRITICAL: 2022 RATE-SHOCK SUB-PERIOD (v1.0 was -1.876) ──────────────",
    ]

    sharpe_2022 = verdict.get("sharpe_2022")
    sharpe_2022_fixed = verdict.get("sharpe_2022_fixed", False)
    if sharpe_2022 is not None:
        fix_label = "FIXED ✓" if sharpe_2022_fixed else "STILL NEGATIVE ✗"
        lines.append(f"  2022 Sharpe: {sharpe_2022:.4f} ({fix_label})")
    else:
        lines.append("  2022 Sharpe: N/A")

    if verdict.get("trade_count_flag"):
        lines += [
            "",
            f"  ⚠ TRADE COUNT FLAG: {verdict['trade_count_flag']}",
        ]

    lines += [
        "",
        "── GATE 1 CRITERIA ──────────────────────────────────────────────────────",
    ]
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        note = f"  [{c.get('note', '')}]" if c.get("note") else ""
        lines.append(
            f"  [{status}] {name}: {c['value']} (threshold: {c['threshold']}){note}"
        )

    lines += [
        "",
        f"── IS METRICS ({IS_START} to {IS_END}) ─────────────────────────────────",
        f"  Sharpe:           {is_m.get('sharpe', 0):.4f}",
        f"  CAGR:             {is_m.get('cagr', 0)*100:.2f}%",
        f"  Max Drawdown:     {is_m.get('max_drawdown', 0)*100:.2f}%",
        f"  Total Return:     {is_m.get('total_return', 0)*100:.2f}%",
        f"  Win Rate:         {is_m.get('win_rate', 0)*100:.1f}%",
        f"  Profit Factor:    {is_m.get('profit_factor', 0):.3f}",
        f"  Trade Count:      {is_m.get('trade_count', 0)}",
        f"  Transitions/yr:   {is_m.get('transitions_per_year', 0):.1f}",
        f"  Avg Hold Days:    {is_m.get('avg_hold_days', 0):.1f}",
        f"  % Time in SPY:    {is_m.get('pct_in_spy', 0)*100:.1f}%",
        "",
        f"── OOS METRICS ({OOS_START} to {OOS_END}) ────────────────────────────────",
        f"  Sharpe:           {oos_m.get('sharpe', 0):.4f}",
        f"  CAGR:             {oos_m.get('cagr', 0)*100:.2f}%",
        f"  Max Drawdown:     {oos_m.get('max_drawdown', 0)*100:.2f}%",
        f"  Total Return:     {oos_m.get('total_return', 0)*100:.2f}%",
        f"  Win Rate:         {oos_m.get('win_rate', 0)*100:.1f}%",
        f"  Trade Count:      {oos_m.get('trade_count', 0)}",
        f"  OOS Degradation:  {verdict['oos_degradation']*100:.1f}% vs IS Sharpe",
        "",
        "── STATISTICAL RIGOR ────────────────────────────────────────────────────",
        f"  MC p5 Sharpe:     {rigor.get('mc_p5_sharpe', float('nan')):.4f}  "
        f"{'[OK]' if rigor.get('mc_p5_sharpe', 0) >= 0.5 else '[WEAK]'}",
        f"  MC median Sharpe: {rigor.get('mc_median_sharpe', float('nan')):.4f}",
        f"  Sharpe 95% CI:    [{rigor.get('sharpe_ci_low', 0):.4f}, "
        f"{rigor.get('sharpe_ci_high', 0):.4f}]",
        f"  MDD 95% CI:       [{rigor.get('mdd_ci_low', 0)*100:.2f}%, "
        f"{rigor.get('mdd_ci_high', 0)*100:.2f}%]",
        f"  Permutation p:    {rigor.get('permutation_pvalue', 1):.4f}  "
        f"({'PASS ✓' if rigor.get('permutation_test_pass') else 'FAIL ✗'}) [CRITICAL]",
        f"  Perm n_blocks:    {rigor.get('permutation_n_blocks', 0)}",
        f"  Market Impact:    {rigor.get('market_impact_bps', 0):.3f} bps  "
        f"({'LIQ_CONSTRAINED' if rigor.get('liquidity_constrained') else 'OK'})",
        f"  DSR:              {rigor.get('dsr', 0):.4f}  "
        f"({'PASS' if rigor.get('dsr', 0) > 0 else 'FAIL'})",
    ]

    if wf:
        lines += [
            "",
            "── WALK-FORWARD (4 expanding windows) ───────────────────────────────",
        ]
        for w in wf["windows"]:
            status = "PASS" if w["oos_pass"] else "FAIL"
            is_sh  = f"{w['is_sharpe']:.3f}"  if w["is_sharpe"]  is not None else "N/A"
            oos_sh = f"{w['oos_sharpe']:.3f}" if w["oos_sharpe"] is not None else "N/A"
            lines.append(
                f"  Window {w['window']}: IS {w['is_start']}→{w['is_end']} "
                f"OOS {w['oos_start']}→{w['oos_end']} | "
                f"IS Sharpe={is_sh} OOS Sharpe={oos_sh} [{status}]"
            )
        wf_min_str = f"{wf['wf_sharpe_min']:.4f}" if wf.get("wf_sharpe_min") is not None else "N/A"
        lines += [
            f"  Windows Passed:    {wf['windows_passed']}/4",
            f"  WF Sharpe Std:     {wf['wf_sharpe_std']:.4f}",
            f"  WF Sharpe Min:     {wf_min_str}"
            f"  {'[GFC-DEPENDENT RISK]' if wf.get('gfc_dependency_flag') else ''}",
        ]

    if sub:
        lines += ["", "── SUB-PERIOD DIAGNOSTICS (QUA-224 required) ───────────────────────────"]
        for name, r in sub.items():
            if name == "smoothing_comparison":
                continue
            sharpe_str = f"{r['sharpe']:.3f}" if r.get("sharpe") is not None else "N/A"
            note_str = f" [{r['note'][:80]}...]" if r.get("note") else ""
            crit_note = " *** CRITICAL FIX TARGET ***" if name == "rate_shock_2022" else ""
            lines.append(
                f"  {name}: Sharpe={sharpe_str} "
                f"CAGR={r.get('cagr',0)*100:.1f}% "
                f"MDD={r.get('max_drawdown',0)*100:.1f}% "
                f"Trades={r.get('trade_count',0)}{crit_note}{note_str}"
            )

    lines += [
        "",
        "── PARAMETER SWEEP SUMMARY (IS-only) ───────────────────────────────────",
    ]
    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        if not valid.empty:
            best = valid.loc[valid["is_sharpe"].idxmax()]
            lines += [
                f"  Best IS Sharpe:    {valid['is_sharpe'].max():.4f}",
                f"  Median IS Sharpe:  {valid['is_sharpe'].median():.4f}",
                f"  Worst IS Sharpe:   {valid['is_sharpe'].min():.4f}",
                f"  Best params:       lookback={int(best['lookback_days'])} "
                f"thresh={best['signal_threshold']:.4f} "
                f"vix_thresh={best['vix_threshold']:.0f} "
                f"riskoff={best['riskoff_asset']}",
            ]

    lines += [
        "",
        "── COST MODEL ───────────────────────────────────────────────────────────",
        "  Fixed:    $0.005/share",
        "  Slippage: 0.005% of notional (ED-SLIP-001 ultra-liquid tier: SPY ADV > 50M/day)",
        "  Impact:   k=0.1 × sigma × sqrt(Q/ADV) × notional (Almgren-Chriss)",
        "  Signal:   DX-Y.NYB and ^VIX — not traded. No FX/vol transaction costs.",
        "",
        "── DATA QUALITY ─────────────────────────────────────────────────────────",
        "  Price adjustment: yfinance auto_adjust=True",
        "  DX-Y.NYB: ICE US Dollar Index cash level (not futures); no roll-gap check",
        "  ^VIX: CBOE VIX, available from 1990; ffill(limit=5) into equity calendar",
        "  Survivorship bias: N/A — SPY/SHY are active broad-market ETFs",
        "  Lookahead bias: signal at T computed from T close; execution at T+1 open",
        "",
        "── HYPOTHESIS SOURCE ────────────────────────────────────────────────────",
        "  H65b v2.0: research/hypotheses/65b_dollar_strength_regime_v2.md",
        "  Supersedes H65 v1.0 (Gate 1 FAIL, QUA-213). v2.0 task: QUA-224.",
        "  References: Miranda-Agrippino & Rey (2020), Ang & Bekaert (2004).",
        "",
        "=" * 72,
    ]
    return "\n".join(lines)


def generate_html_report(is_m, oos_m, verdict, sweep_df, wf, rigor, sub,
                         variant_info) -> str:
    v = verdict["verdict"]
    verdict_color = "#28a745" if v == "PASS" else "#dc3545"
    perm_pass = rigor.get("permutation_test_pass", False)
    perm_color = "#28a745" if perm_pass else "#dc3545"
    gfc_dep = wf.get("gfc_dependency_flag", False)
    sv = variant_info.get("selected_variant", "unknown")
    v1 = variant_info.get("variant_1_baseline", {})
    v2 = variant_info.get("variant_2_tight_vix", {})
    v3 = variant_info.get("variant_3_wide_vix", {})

    sharpe_2022 = verdict.get("sharpe_2022")
    sharpe_2022_fixed = verdict.get("sharpe_2022_fixed", False)
    sharpe_2022_color = "#28a745" if sharpe_2022_fixed else "#dc3545"
    sharpe_2022_str = f"{sharpe_2022:.4f}" if sharpe_2022 is not None else "N/A"
    sharpe_2022_label = "FIXED ✓" if sharpe_2022_fixed else "STILL NEGATIVE ✗"

    def fmt_pct(x):
        return f"{x * 100:.2f}%" if x is not None else "N/A"
    def fmt_4(x):
        return f"{x:.4f}" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "N/A"

    criteria_rows = ""
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        color = "#28a745" if c["pass"] else "#dc3545"
        note = c.get("note", "")
        criteria_rows += (
            f"<tr><td><strong>{name}</strong></td>"
            f"<td>{c['value']}</td><td>{c['threshold']}</td>"
            f"<td style='color:{color};font-weight:bold'>{status}</td>"
            f"<td style='font-size:0.85em'>{note}</td></tr>\n"
        )

    wf_rows = ""
    if wf:
        for w in wf["windows"]:
            color = "#28a745" if w["oos_pass"] else "#dc3545"
            is_sh  = fmt_4(w["is_sharpe"])
            oos_sh = fmt_4(w["oos_sharpe"])
            wf_rows += (
                f"<tr><td>{w['window']}</td>"
                f"<td>{w['is_start']}→{w['is_end']}</td>"
                f"<td>{w['oos_start']}→{w['oos_end']}</td>"
                f"<td>{is_sh}</td><td>{oos_sh}</td>"
                f"<td style='color:{color};font-weight:bold'>"
                f"{'PASS' if w['oos_pass'] else 'FAIL'}</td></tr>\n"
            )

    sweep_table = ""
    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        if not valid.empty:
            top10 = valid.nlargest(10, "is_sharpe")
            for _, row in top10.iterrows():
                sweep_table += (
                    f"<tr><td>{int(row['lookback_days'])}</td>"
                    f"<td>{row['signal_threshold']:.4f}</td>"
                    f"<td>{row['vix_threshold']:.0f}</td>"
                    f"<td>{row['riskoff_asset']}</td>"
                    f"<td>{row['is_sharpe']:.4f}</td>"
                    f"<td>{row['is_cagr']*100:.1f}%</td>"
                    f"<td>{row['is_mdd']*100:.1f}%</td>"
                    f"<td>{int(row['is_trades'])}</td></tr>\n"
                )

    sub_rows = ""
    if sub:
        for name, r in sub.items():
            sharpe_str = fmt_4(r.get("sharpe"))
            note_str = r.get("note", "")[:100] + "..." if r.get("note") else ""
            row_style = " style='background:#fff3cd'" if name == "rate_shock_2022" else ""
            sub_rows += (
                f"<tr{row_style}><td>{name}</td><td>{r.get('start','')}→{r.get('end','')}</td>"
                f"<td>{sharpe_str}</td>"
                f"<td>{r.get('cagr',0)*100:.1f}%</td>"
                f"<td>{r.get('max_drawdown',0)*100:.1f}%</td>"
                f"<td>{r.get('trade_count',0)}</td>"
                f"<td>{r.get('pct_in_spy',0)*100:.1f}%</td>"
                f"<td style='font-size:0.8em'>{note_str}</td></tr>\n"
            )

    trade_flag_html = ""
    if verdict.get("trade_count_flag"):
        trade_flag_html = f'<div class="warn"><strong>⚠ Trade Count Flag:</strong> {verdict["trade_count_flag"]}</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<title>H65b Gate 1 Report — Dollar Strength Regime v2.0 (VIX Dual-Filter)</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 40px auto; color: #333; }}
h1 {{ color: #1a1a2e; }} h2 {{ color: #16213e; border-bottom: 2px solid #eee; padding-bottom: 4px; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: left; font-size: 0.9em; }}
th {{ background: #f4f4f4; font-weight: bold; }}
.verdict {{ font-size: 2em; font-weight: bold; color: {verdict_color}; margin: 20px 0; }}
.metric-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }}
.metric-box {{ background: #f9f9f9; border: 1px solid #ddd; border-radius: 6px; padding: 12px; }}
.metric-val {{ font-size: 1.2em; font-weight: bold; color: #1a1a2e; }}
.perm-badge {{ color: {perm_color}; font-weight: bold; font-size: 1.1em; }}
.warn {{ color: #856404; background: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; }}
.critical {{ color: #721c24; background: #f8d7da; padding: 10px; border-radius: 4px; margin: 10px 0; }}
.ok {{ color: #155724; background: #d4edda; padding: 10px; border-radius: 4px; margin: 10px 0; }}
.info {{ color: #0c5460; background: #d1ecf1; padding: 10px; border-radius: 4px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>Gate 1 Report — H65b Dollar Strength Regime v2.0 (VIX Dual-Filter, Asymmetric Exit)</h1>
<p><strong>Report Date:</strong> {REPORT_DATE} | <strong>IS:</strong> {IS_START}→{IS_END} | <strong>OOS:</strong> {OOS_START}→{OOS_END}</p>
<p>v2.0 design: Asymmetric state machine — enter risk-off when DXY_mom &gt; threshold AND VIX &gt; vix_threshold;
exit risk-off ONLY when both clear (sticky). Fixes Q4 2022 whipsaw (v1.0 Sharpe=-1.876) and 2014-2015 false positive.</p>
<p>Supersedes H65 v1.0 (IS Sharpe=0.676, FAIL, QUA-213). Task: QUA-224.</p>

<div class="verdict">Gate 1 Verdict: {v}</div>
{trade_flag_html}

<div class="{'ok' if sharpe_2022_fixed else 'critical'}">
<strong>CRITICAL FIX CHECK — 2022 Rate-Shock Sub-Period:</strong>
<span style='color:{sharpe_2022_color};font-weight:bold'>Sharpe = {sharpe_2022_str} ({sharpe_2022_label})</span>
v1.0 was −1.876. v2.0 target: &gt; 0.0.
VIX filter + asymmetric exit should keep strategy in SHY through Q4 2022 DXY reversal.
</div>

<div class="info">
<strong>QUA-224 VARIANT COMPARISON (required):</strong><br>
Variant-1 (vix_thresh=20): IS Sharpe={v1.get('is_sharpe', 'N/A')} | MDD={v1.get('is_mdd', 0)*100:.2f}% | Trades={v1.get('is_trades', 0)}<br>
Variant-2 (vix_thresh=18): IS Sharpe={v2.get('is_sharpe', 'N/A')} | MDD={v2.get('is_mdd', 0)*100:.2f}% | Trades={v2.get('is_trades', 0)}<br>
Variant-3 (vix_thresh=25): IS Sharpe={v3.get('is_sharpe', 'N/A')} | MDD={v3.get('is_mdd', 0)*100:.2f}% | Trades={v3.get('is_trades', 0)}<br>
<strong>Selected for Gate 1: {sv}</strong>
</div>

{'<div class="critical"><strong>GFC-DEPENDENCY FLAG:</strong> Non-GFC walk-forward folds show Sharpe &lt; 0.5.</div>' if gfc_dep else ''}

<div class="{'ok' if perm_pass else 'critical'}">
<strong>PERMUTATION TEST (CRITICAL):</strong>
<span class="perm-badge">p = {rigor.get('permutation_pvalue', 1.0):.4f}</span>
({'PASS — DXY+VIX dual-filter has genuine predictive power ✓' if perm_pass else 'FAIL — no statistical alpha.'})
Block-shuffle permutation ({rigor.get('permutation_n', 0)} shuffles, {rigor.get('permutation_n_blocks', 0)} regime blocks).
</div>

<h2>Gate 1 Criteria</h2>
<table><thead><tr><th>Criterion</th><th>Value</th><th>Threshold</th><th>Status</th><th>Note</th></tr></thead>
<tbody>{criteria_rows}</tbody></table>

<h2>IS Performance ({IS_START} to {IS_END}) — Selected Variant: {sv}</h2>
<div class="metric-grid">
  <div class="metric-box"><div>Sharpe Ratio</div><div class="metric-val">{fmt_4(is_m.get('sharpe'))}</div></div>
  <div class="metric-box"><div>CAGR</div><div class="metric-val">{fmt_pct(is_m.get('cagr'))}</div></div>
  <div class="metric-box"><div>Max Drawdown</div><div class="metric-val">{fmt_pct(is_m.get('max_drawdown'))}</div></div>
  <div class="metric-box"><div>Total Return</div><div class="metric-val">{fmt_pct(is_m.get('total_return'))}</div></div>
  <div class="metric-box"><div>Win Rate</div><div class="metric-val">{fmt_pct(is_m.get('win_rate'))}</div></div>
  <div class="metric-box"><div>Profit Factor</div><div class="metric-val">{fmt_4(is_m.get('profit_factor'))}</div></div>
  <div class="metric-box"><div>Trade Count</div><div class="metric-val">{is_m.get('trade_count', 0)}</div></div>
  <div class="metric-box"><div>Transitions/yr</div><div class="metric-val">{is_m.get('transitions_per_year', 0):.1f}</div></div>
  <div class="metric-box"><div>% Time in SPY</div><div class="metric-val">{is_m.get('pct_in_spy', 0)*100:.1f}%</div></div>
</div>

<h2>OOS Performance ({OOS_START} to {OOS_END})</h2>
<div class="metric-grid">
  <div class="metric-box"><div>Sharpe Ratio</div><div class="metric-val">{fmt_4(oos_m.get('sharpe'))}</div></div>
  <div class="metric-box"><div>CAGR</div><div class="metric-val">{fmt_pct(oos_m.get('cagr'))}</div></div>
  <div class="metric-box"><div>Max Drawdown</div><div class="metric-val">{fmt_pct(oos_m.get('max_drawdown'))}</div></div>
  <div class="metric-box"><div>Win Rate</div><div class="metric-val">{fmt_pct(oos_m.get('win_rate'))}</div></div>
  <div class="metric-box"><div>Trade Count</div><div class="metric-val">{oos_m.get('trade_count', 0)}</div></div>
  <div class="metric-box"><div>OOS Degradation</div><div class="metric-val">{verdict['oos_degradation']*100:.1f}%</div></div>
</div>

<h2>Statistical Rigor Pipeline</h2>
<table><thead><tr><th>Metric</th><th>Value</th><th>Threshold</th><th>Status</th></tr></thead><tbody>
<tr><td>MC p5 Sharpe (1000 bootstrap)</td><td>{fmt_4(rigor.get('mc_p5_sharpe'))}</td><td>&ge; 0.5</td><td>{'PASS' if (rigor.get('mc_p5_sharpe') or 0) >= 0.5 else 'WARN'}</td></tr>
<tr><td>MC Median Sharpe</td><td>{fmt_4(rigor.get('mc_median_sharpe'))}</td><td>-</td><td>-</td></tr>
<tr><td>Block Bootstrap Sharpe 95% CI</td><td>[{fmt_4(rigor.get('sharpe_ci_low'))}, {fmt_4(rigor.get('sharpe_ci_high'))}]</td><td>-</td><td>-</td></tr>
<tr><td>Block Bootstrap MDD 95% CI</td><td>[{fmt_pct(rigor.get('mdd_ci_low'))}, {fmt_pct(rigor.get('mdd_ci_high'))}]</td><td>-</td><td>-</td></tr>
<tr><td><strong>Permutation test p-value</strong></td>
    <td><strong>{fmt_4(rigor.get('permutation_pvalue'))}</strong></td>
    <td>&le; 0.05</td>
    <td style='color:{perm_color};font-weight:bold'>{'PASS' if perm_pass else 'FAIL — CRITICAL'}</td></tr>
<tr><td>Market Impact (SPY, $25K notional)</td><td>{fmt_4(rigor.get('market_impact_bps'))} bps</td><td>-</td>
    <td>{'LIQUIDITY CONSTRAINED' if rigor.get('liquidity_constrained') else 'OK'}</td></tr>
<tr><td>Deflated Sharpe Ratio</td><td>{fmt_4(rigor.get('dsr'))}</td><td>&gt; 0</td>
    <td>{'PASS' if (rigor.get('dsr') or 0) > 0 else 'FAIL'}</td></tr>
</tbody></table>

<h2>Walk-Forward Analysis (4 expanding windows)</h2>
<table><thead><tr><th>#</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>OOS Pass</th></tr></thead>
<tbody>{wf_rows}</tbody></table>
<p>Windows passed: <strong>{wf.get('windows_passed', 0)}/4</strong> | WF Sharpe std: {wf.get('wf_sharpe_std', 0):.4f}</p>

<h2>Sub-Period Diagnostics (QUA-224 required)</h2>
<p><em>2022 rate-shock row highlighted — critical fix target for v2.0.</em></p>
<table><thead><tr><th>Period</th><th>Window</th><th>Sharpe</th><th>CAGR</th><th>MDD</th><th>Trades</th><th>% SPY</th><th>Note</th></tr></thead>
<tbody>{sub_rows}</tbody></table>

<h2>Parameter Sweep — Top 10 IS Configurations</h2>
<table><thead><tr><th>Lookback</th><th>Threshold</th><th>VIX Thresh</th><th>Risk-off</th><th>IS Sharpe</th><th>IS CAGR</th><th>IS MDD</th><th>IS Trades</th></tr></thead>
<tbody>{sweep_table}</tbody></table>

<h2>v2.0 Design Notes</h2>
<ul>
  <li><strong>Asymmetric exit:</strong> Both DXY_mom &lt; threshold AND VIX &lt; vix_threshold required to exit risk-off. Prevents Q4 2022 premature re-entry.</li>
  <li><strong>2014-2015 fix:</strong> VIX filter prevents risk-off entry when DXY strong but VIX calm (VIX was mostly 10-15 in 2014-2015).</li>
  <li><strong>asymmetric_exit=True is NOT a free parameter</strong> — it is required design. Do not test symmetric version.</li>
  <li><strong>Sticky-state benefit:</strong> Fewer transitions vs symmetric version; lower transaction cost drag.</li>
</ul>

<h2>Transaction Cost Model (ED-SLIP-001)</h2>
<ul>
  <li>Fixed: $0.005/share | Slippage: 0.005% of notional (ultra-liquid: SPY ADV &gt; 50M shares/day)</li>
  <li>Market impact: Almgren-Chriss k=0.1 × σ × √(Q/ADV) × notional</li>
  <li>Signal assets DX-Y.NYB and ^VIX: not traded. No FX or vol transaction costs.</li>
</ul>

</body></html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 72)
    logger.info("H65b Dollar Strength Regime v2.0 (VIX Dual-Filter) — Gate 1 Backtest")
    logger.info("QUA-224: Asymmetric state machine — fixes Q4 2022 whipsaw and 2014-2015 FP")
    logger.info("=" * 72)

    # 0. Variant comparison (QUA-224 requirement)
    logger.info("\n=== QUA-224 VARIANT COMPARISON ===")
    variant_info = run_variant_comparison()
    selected_params = variant_info["selected_params"]
    logger.info("Selected variant: %s", variant_info["selected_variant"])

    # 1. IS backtest (selected variant)
    logger.info("\n=== IS BACKTEST (%s → %s) ===", IS_START, IS_END)
    is_result = backtest_window(IS_START, IS_END, selected_params.copy(), "IS")

    # QUA-224: Report IS trade count FIRST; flag if < 120
    is_trade_count = is_result.get("trade_count", 0)
    logger.info("\n=== IS TRADE COUNT: %d ===", is_trade_count)
    if is_trade_count < QUA224_MIN_TRADES_FLAG:
        logger.warning(
            "  *** QUA-224 FLAG: IS trade count %d < %d threshold. "
            "VIX filter may have reduced trades below viable threshold. "
            "Flag to Research Director before proceeding. ***",
            is_trade_count, QUA224_MIN_TRADES_FLAG
        )
    else:
        logger.info("  IS trade count OK: %d >= %d", is_trade_count, QUA224_MIN_TRADES_FLAG)

    # 2. OOS backtest
    logger.info("\n=== OOS BACKTEST (%s → %s) ===", OOS_START, OOS_END)
    oos_result = backtest_window(OOS_START, OOS_END, selected_params.copy(), "OOS")

    # 3. Parameter sweep
    logger.info("\n=== PARAMETER SWEEP ===")
    sweep_df = run_parameter_sweep(selected_params)
    best_params = selected_params.copy()
    median_is_sharpe = 0.0
    if not sweep_df.empty:
        valid = sweep_df.dropna(subset=["is_sharpe"])
        if not valid.empty:
            best_row = valid.loc[valid["is_sharpe"].idxmax()]
            for k in SWEEP_GRID:
                best_params[k] = best_row[k]
            median_is_sharpe = float(valid["is_sharpe"].median())
            logger.info("Best IS Sharpe: %.4f | Median: %.4f | Worst: %.4f",
                        valid["is_sharpe"].max(), median_is_sharpe, valid["is_sharpe"].min())

    # 4. Walk-forward
    wf = run_walk_forward(selected_params.copy())

    # 5. Sub-period diagnostics (includes critical 2022 sub-period)
    sub = run_sub_period_diagnostics(selected_params.copy())

    # 6. Statistical rigor pipeline
    logger.info("\n=== STATISTICAL RIGOR PIPELINE ===")
    is_trades_df = is_result.get("trades", pd.DataFrame())
    is_daily_df = is_result.get("daily_df", pd.DataFrame())
    is_equity = is_result.get("equity", pd.Series(dtype=float))
    rigor = {}

    if not is_trades_df.empty and len(is_trades_df) >= 10:
        trade_pnls = is_trades_df["pnl"].values

        logger.info("  Monte Carlo (1000 sims)...")
        rigor.update(monte_carlo_sharpe(trade_pnls))

        logger.info("  Block bootstrap CI (1000 boots)...")
        if not is_equity.empty and len(is_equity) > 5:
            is_returns = is_equity.pct_change().fillna(0).values
            rigor.update(block_bootstrap_ci(is_returns))

        logger.info("  Permutation test (1000 block-shuffles)...")
        if not is_equity.empty and not is_daily_df.empty:
            spy_returns = is_equity.pct_change().fillna(0).values
            rigor.update(permutation_test_regime_signal(
                is_daily_df, spy_returns,
                observed_sharpe=is_result.get("sharpe", 0.0),
                n_perms=1000,
            ))
        else:
            rigor.update({"permutation_pvalue": 1.0, "permutation_test_pass": False,
                          "permutation_n": 0, "permutation_note": "no data"})

        logger.info("  Market impact (SPY, $25K)...")
        try:
            import yfinance as yf
            spy_daily = yf.download("SPY", start="2023-01-01", end="2026-06-12",
                                     auto_adjust=True, progress=False)
            if isinstance(spy_daily.columns, pd.MultiIndex):
                spy_daily.columns = spy_daily.columns.get_level_values(0)
            rigor.update(compute_market_impact_spy(spy_daily, 25000.0))
        except Exception as e:
            logger.warning("  Market impact calc failed: %s", e)
            rigor.update({"market_impact_bps": 0.0, "liquidity_constrained": False,
                          "order_to_adv_ratio": 0.0})

        logger.info("  DSR (%d sweep trials)...", len(sweep_df))
        if not is_equity.empty and len(is_equity) > 5:
            rigor["dsr"] = compute_dsr(is_equity.pct_change().dropna(), n_trials=len(sweep_df))

        rigor["wf_sharpe_std"] = wf.get("wf_sharpe_std", 0.0)
        rigor["wf_sharpe_min"] = wf.get("wf_sharpe_min") or 0.0

    else:
        logger.warning("  Skipping Statistical Rigor Pipeline — insufficient IS trades (%d)",
                       len(is_trades_df))
        rigor = {
            "mc_p5_sharpe": np.nan, "mc_median_sharpe": np.nan, "mc_p95_sharpe": np.nan,
            "sharpe_ci_low": np.nan, "sharpe_ci_high": np.nan,
            "mdd_ci_low": np.nan, "mdd_ci_high": np.nan,
            "win_rate_ci_low": np.nan, "win_rate_ci_high": np.nan,
            "permutation_pvalue": 1.0, "permutation_test_pass": False, "permutation_n": 0,
            "market_impact_bps": 0.0, "liquidity_constrained": False, "order_to_adv_ratio": 0.0,
            "dsr": 0.0, "wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0,
        }

    # 7. Gate 1 verdict
    verdict = evaluate_gate1(is_result, oos_result, wf, rigor, variant_info, sub)
    logger.info("\n=== GATE 1 VERDICT: %s ===", verdict["verdict"])
    for name, c in verdict["criteria"].items():
        status = "PASS" if c["pass"] else "FAIL"
        logger.info("  [%s] %s: %s (threshold: %s)", status, name, c["value"], c["threshold"])

    if verdict.get("trade_count_flag"):
        logger.warning("  TRADE COUNT FLAG: %s", verdict["trade_count_flag"])

    # 8. Save outputs
    logger.info("\n=== GENERATING REPORTS ===")
    base_name = f"{STRATEGY_NAME}_{REPORT_DATE}"

    def _safe(v):
        if isinstance(v, (np.floating, np.integer)):
            return float(v) if not np.isnan(v) else None
        if isinstance(v, float) and np.isnan(v):
            return None
        return v

    def _safe_metrics(m: dict) -> dict:
        return {
            k: _safe(v)
            for k, v in m.items()
            if isinstance(v, (int, float, str, dict, list, bool, type(None)))
            and k not in ("equity", "daily_df", "trades", "returns")
        }

    rigor_safe = {k: _safe(v) for k, v in rigor.items()}
    dotcom_diag = sub.get("dotcom_2000_2002", {})

    json_payload = {
        "strategy": "H65b_Dollar_Strength_Regime_v2",
        "version": "2.0",
        "gate": "Gate 1",
        "report_date": REPORT_DATE,
        "is_window": {"start": IS_START, "end": IS_END},
        "oos_window": {"start": OOS_START, "end": OOS_END},
        "qua224_variant_comparison": variant_info,
        "selected_params": selected_params,
        "is_metrics": _safe_metrics(is_result),
        "oos_metrics": _safe_metrics(oos_result),
        "gate1_verdict": verdict,
        "statistical_rigor": rigor_safe,
        "walk_forward": {
            "windows": wf["windows"],
            "windows_passed": wf["windows_passed"],
            "wf_sharpe_std": wf["wf_sharpe_std"],
            "wf_sharpe_min": wf.get("wf_sharpe_min"),
            "gfc_dependency_flag": wf.get("gfc_dependency_flag"),
        },
        "sub_period_diagnostics": sub,
        "parameter_sweep": {
            "total_combinations": len(sweep_df),
            "best_is_sharpe": _safe(sweep_df["is_sharpe"].max()) if not sweep_df.empty else None,
            "median_is_sharpe": _safe(median_is_sharpe),
            "best_params": best_params,
        },
        "dotcom_2000_2002_diagnostic": {
            "mdd": dotcom_diag.get("max_drawdown"),
            "sharpe": dotcom_diag.get("sharpe"),
            "note": dotcom_diag.get("note", ""),
        },
        "data_quality": {
            "survivorship_bias": "N/A — SPY/SHY are active ETFs",
            "price_adjusted": True,
            "dxy_note": "DX-Y.NYB ICE US Dollar Index cash level; ffill(limit=3) into SPY calendar",
            "vix_note": "^VIX CBOE VIX; ffill(limit=5) into SPY calendar",
            "lookahead_bias": "None — signal at T from T close; T+1 open execution",
            "asymmetric_exit": True,
        },
        "v1_comparison": {
            "v1_is_sharpe": 0.676,
            "v1_2022_sharpe": -1.876,
            "v1_wf_consistency": "1/4",
            "v2_fixes": [
                "VIX > vix_threshold co-condition prevents 2014-2015 false positive",
                "Asymmetric exit prevents Q4 2022 premature re-entry (sticky risk-off until VIX clears)",
            ],
        },
        "hypothesis_ref": "research/hypotheses/65b_dollar_strength_regime_v2.md",
        "academic_refs": [
            "Miranda-Agrippino & Rey (2020) RoES — dollar as global financial cycle factor",
            "Ang & Bekaert (2004) NBER — stock return predictability and VIX regimes",
        ],
    }

    json_path = OUTPUT_DIR / f"{base_name}.json"
    with open(json_path, "w") as f:
        json.dump(json_payload, f, indent=2, default=str)
    logger.info("  JSON: %s", json_path)

    verdict_txt = generate_verdict_txt(
        is_result, oos_result, verdict, sweep_df, wf, rigor, sub, variant_info
    )
    verdict_path = OUTPUT_DIR / f"{base_name}_verdict.txt"
    with open(verdict_path, "w") as f:
        f.write(verdict_txt)
    logger.info("  Verdict: %s", verdict_path)

    html_report = generate_html_report(
        is_result, oos_result, verdict, sweep_df, wf, rigor, sub, variant_info
    )
    html_path = OUTPUT_DIR / f"{base_name}_report.html"
    with open(html_path, "w") as f:
        f.write(html_report)
    logger.info("  HTML: %s", html_path)

    is_trades_df_out = is_result.get("trades", pd.DataFrame())
    if not is_trades_df_out.empty:
        trades_path = OUTPUT_DIR / f"{base_name}_trades.csv"
        is_trades_df_out.to_csv(trades_path, index=False)
        logger.info("  IS Trades: %s", trades_path)

    if not sweep_df.empty:
        sweep_path = OUTPUT_DIR / f"{base_name}_sweep.csv"
        sweep_df.to_csv(sweep_path, index=False)
        logger.info("  Sweep: %s", sweep_path)

    logger.info("\n=== SUMMARY ===")
    logger.info("Selected variant: %s", variant_info["selected_variant"])
    logger.info("IS  Sharpe=%.4f CAGR=%.1f%% MDD=%.1f%% Trades=%d",
                is_result.get("sharpe", 0), is_result.get("cagr", 0) * 100,
                is_result.get("max_drawdown", 0) * 100, is_result.get("trade_count", 0))
    logger.info("OOS Sharpe=%.4f CAGR=%.1f%% MDD=%.1f%% Trades=%d",
                oos_result.get("sharpe", 0), oos_result.get("cagr", 0) * 100,
                oos_result.get("max_drawdown", 0) * 100, oos_result.get("trade_count", 0))
    logger.info("2022 sub-period Sharpe: %.4f (%s)",
                verdict.get("sharpe_2022") or 0.0,
                "FIXED ✓" if verdict.get("sharpe_2022_fixed") else "STILL NEGATIVE ✗")
    logger.info("Permutation p=%.4f (%s)",
                rigor.get("permutation_pvalue", 1.0),
                "PASS" if rigor.get("permutation_test_pass") else "FAIL")
    logger.info("WF: %d/4 windows passed | GFC-dep: %s",
                wf["windows_passed"], wf.get("gfc_dependency_flag"))
    logger.info("Gate 1: %s", verdict["verdict"])

    print("\n" + verdict_txt)
    return json_payload


if __name__ == "__main__":
    result = main()
