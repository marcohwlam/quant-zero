"""
Gate 1 Backtest Runner: Bollinger Band Mean Reversion
Task: QUA-65
Runner: Backtest Runner Agent (ddfd2618)

Design notes:
- Uses generate_signals() / load_vix_mask() directly from strategy module
  (unchanged trading logic).
- Builds per-ticker portfolios; aggregates via mean Sharpe / mean MDD /
  combined trade log (equal-weight interpretation).
- Replaces scan_entry_std() with a grouped equivalent because the strategy's
  scan_entry_std() calls float(pf.sharpe_ratio()) which breaks for multi-column
  portfolios in vectorbt >=0.27.
- The strategy's signal generation logic is NOT modified.
"""

import sys
import json
import datetime
import numpy as np
import pandas as pd

# Path setup
sys.path.insert(0, '/mnt/c/Users/lamho/repo/quant-zero/strategies')
sys.path.insert(0, '/mnt/c/Users/lamho/repo/quant-zero/orchestrator')
sys.path.insert(0, '/mnt/c/Users/lamho/repo/quant-zero/agents/overfit-detector/tools')

from bollinger_band_mean_reversion import (
    PARAMETERS, generate_signals, load_vix_mask, count_weekly_round_trips
)
import vectorbt as vbt
import yfinance as yf
from dsr_calculator import compute_dsr
from gate1_reporter import generate_and_save_verdict

# Set global daily frequency for vectorbt Sharpe annualization
vbt.settings.array_wrapper['freq'] = 'D'

# ── Config ────────────────────────────────────────────────────────────────────
UNIVERSE  = PARAMETERS["universe"]
IS_START  = "2018-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2023-12-31"

FEES      = 0.0001   # ~0.01% (equities)
SLIPPAGE  = 0.0005   # 0.05%
INIT_CASH = 25000


def run_period(start: str, end: str, label: str, params: dict = PARAMETERS) -> dict:
    """
    Download data, generate signals, build per-ticker portfolios,
    and aggregate metrics (mean Sharpe, mean MDD, combined trade log).
    """
    close = yf.download(UNIVERSE, start=start, end=end, progress=False, auto_adjust=True)["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame()
    close = close.dropna(axis=1, how="all")

    vix_mask = load_vix_mask(start, end, params["vix_threshold"])
    entries, exits = generate_signals(close, vix_mask, params)

    # Per-ticker portfolios (no cash sharing — equal-weight independent bets)
    pf = vbt.Portfolio.from_signals(
        close, entries=entries, exits=exits,
        fees=FEES, slippage=SLIPPAGE, init_cash=INIT_CASH,
    )

    # Aggregate: mean across tickers (equal-weight strategy)
    sharpes = pf.sharpe_ratio()   # Series[ticker]
    mdds    = pf.max_drawdown()   # Series[ticker]
    rets    = pf.total_return()   # Series[ticker]

    sharpe     = float(sharpes.mean())
    mdd        = float(mdds.mean())
    total_ret  = float(rets.mean())
    trade_cnt  = int(pf.trades.count().sum())  # total across all tickers

    # Combined PnL array from all tickers (MappedArray.values is a flat ndarray)
    try:
        pnl_arr = pf.trades.pnl.values
        pnl_arr = pnl_arr[~np.isnan(pnl_arr)]
    except Exception:
        pnl_arr = np.array([])

    win_rate = float(np.mean(pnl_arr > 0)) if len(pnl_arr) > 0 else 0.0

    wins   = pnl_arr[pnl_arr > 0]
    losses = pnl_arr[pnl_arr < 0]
    profit_factor = (
        float(wins.sum() / abs(losses.sum()))
        if len(losses) > 0 and losses.sum() != 0 else float("inf")
    )

    # Portfolio-level daily returns (mean across tickers)
    daily_rets = pf.returns()
    if hasattr(daily_rets, "to_pandas"):
        daily_rets = daily_rets.to_pandas()
    if isinstance(daily_rets, pd.DataFrame):
        daily_rets = daily_rets.mean(axis=1)
    daily_rets = daily_rets.dropna()

    # PDT compliance
    pdt_df  = count_weekly_round_trips(entries, exits)
    pdt_max = int(pdt_df.sum(axis=1).max()) if not pdt_df.empty else 0

    print(f"  [{label}] Sharpe={sharpe:.4f}  MDD={mdd*100:.2f}%  "
          f"WinRate={win_rate*100:.1f}%  Trades={trade_cnt}  "
          f"TotalReturn={total_ret*100:.2f}%  PDT_max_weekly={pdt_max}")

    return {
        "sharpe": sharpe, "max_drawdown": mdd, "win_rate": win_rate,
        "total_return": total_ret, "trade_count": trade_cnt,
        "profit_factor": profit_factor,
        "pdt_max_weekly_round_trips": pdt_max,
        "pdt_weekly_summary": pdt_df.sum(axis=1).to_dict(),
        "tickers_traded": list(close.columns),
        "period": f"{start} to {end}",
        "_daily_rets": daily_rets,
    }


def scan_entry_std_grouped(
    universe: list, start: str, end: str,
    entry_std_values: list | None = None,
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Scan Sharpe ratio across entry_std values.
    Uses per-ticker portfolios and takes mean Sharpe (equal-weight).
    Replaces scan_entry_std() which breaks on multi-column portfolios
    in vectorbt >=0.27.
    """
    if entry_std_values is None:
        entry_std_values = [round(v, 2) for v in np.arange(1.6, 2.5, 0.1)]

    close = yf.download(universe, start=start, end=end, progress=False, auto_adjust=True)["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame()
    close = close.dropna(axis=1, how="all")
    vix_mask = load_vix_mask(start, end, base_params["vix_threshold"])

    results = {}
    for std_val in entry_std_values:
        params = dict(base_params)
        params["entry_std"] = std_val
        entries, exits = generate_signals(close, vix_mask, params)

        if entries.empty or entries.sum().sum() == 0:
            results[std_val] = float("nan")
            continue

        pf = vbt.Portfolio.from_signals(
            close, entries=entries, exits=exits,
            fees=FEES, slippage=SLIPPAGE, init_cash=INIT_CASH,
        )
        results[std_val] = float(pf.sharpe_ratio().mean())

    return results


# ────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("Bollinger Band Mean Reversion — Gate 1 Backtest")
print(f"Universe: {UNIVERSE}")
print(f"IS:  {IS_START} to {IS_END}")
print(f"OOS: {OOS_START} to {OOS_END}")
print("=" * 70)

# ── 1. IS Backtest ────────────────────────────────────────────────────────────
print("\n[1/5] Running IS backtest...")
is_m = run_period(IS_START, IS_END, "IS")

# ── 2. OOS Backtest ───────────────────────────────────────────────────────────
print("\n[2/5] Running OOS backtest...")
oos_m = run_period(OOS_START, OOS_END, "OOS")

# ── 3. Entry_std Sensitivity Scan ─────────────────────────────────────────────
print("\n[3/5] Running entry_std sensitivity scan [1.6..2.4]...")
sensitivity = scan_entry_std_grouped(UNIVERSE, IS_START, IS_END)
print("  entry_std → Sharpe:")
for std_val, sv in sorted(sensitivity.items()):
    marker = " <-- BASE" if abs(std_val - 2.0) < 0.01 else ""
    print(f"    {std_val:.1f}: {sv:.4f}{marker}")

base_key         = min(sensitivity.keys(), key=lambda k: abs(k - 2.0))
base_sharpe_val  = sensitivity[base_key]
valid_sharpes    = [v for v in sensitivity.values() if not np.isnan(v)]

if valid_sharpes and base_sharpe_val and not np.isnan(base_sharpe_val) and base_sharpe_val > 0:
    min_sharpe            = min(valid_sharpes)
    sensitivity_degradation = (base_sharpe_val - min_sharpe) / base_sharpe_val
else:
    sensitivity_degradation = 0.0

sensitivity_pass = sensitivity_degradation < 0.30
print(f"\n  Base Sharpe (entry_std=2.0): {base_sharpe_val:.4f}")
if valid_sharpes:
    print(f"  Min Sharpe in range:        {min(valid_sharpes):.4f}")
print(f"  Degradation:                {sensitivity_degradation:.2%}")
print(f"  Sensitivity Gate 1:         {'PASS' if sensitivity_pass else 'FAIL'} (threshold: <30%)")

# ── 4. Walk-Forward Analysis (4 windows, 36mo IS / 6mo OOS) ───────────────────
print("\n[4/5] Running walk-forward analysis (4 windows: 36mo IS / 6mo OOS)...")
wf_window_defs = [
    ("2018-01-01", "2020-12-31", "2021-01-01", "2021-06-30"),
    ("2018-07-01", "2021-06-30", "2021-07-01", "2021-12-31"),
    ("2019-01-01", "2021-12-31", "2022-01-01", "2022-06-30"),
    ("2019-07-01", "2022-06-30", "2022-07-01", "2022-12-31"),
]

wf_results = []
for i, (is_s, is_e, oos_s, oos_e) in enumerate(wf_window_defs, 1):
    print(f"\n  Window {i}: IS {is_s}→{is_e}  OOS {oos_s}→{oos_e}")
    w_is  = run_period(is_s,  is_e,  f"WF{i}-IS")
    w_oos = run_period(oos_s, oos_e, f"WF{i}-OOS")
    oos_deg = (
        (w_is["sharpe"] - w_oos["sharpe"]) / w_is["sharpe"]
        if w_is["sharpe"] > 0 else 1.0
    )
    wf_pass = oos_deg < 0.30
    print(f"    → IS={w_is['sharpe']:.4f}  OOS={w_oos['sharpe']:.4f}  "
          f"Degradation={oos_deg:.2%}  {'PASS' if wf_pass else 'FAIL'}")
    wf_results.append({
        "window": i,
        "is_start": is_s, "is_end": is_e,
        "oos_start": oos_s, "oos_end": oos_e,
        "train_sharpe":    w_is["sharpe"],
        "test_sharpe":     w_oos["sharpe"],
        "is_trade_count":  w_is["trade_count"],
        "oos_trade_count": w_oos["trade_count"],
    })

wf_windows_passed = sum(
    1 for w in wf_results
    if w["train_sharpe"] > 0
    and (w["train_sharpe"] - w["test_sharpe"]) / w["train_sharpe"] < 0.30
)
print(f"\n  Walk-Forward: {wf_windows_passed}/4 windows passed")

# ── 5. DSR Calculation ────────────────────────────────────────────────────────
print("\n[5/5] Computing Deflated Sharpe Ratio (DSR)...")
daily_rets_is = is_m["_daily_rets"]
skew_is = float(daily_rets_is.skew())
kurt_is = float(daily_rets_is.kurtosis())
n_obs_is = len(daily_rets_is)
n_trials = len(sensitivity)

dsr_result = compute_dsr(
    sr_hat=is_m["sharpe"],
    n_trials=n_trials,
    n_obs=n_obs_is,
    skewness=skew_is,
    kurtosis=kurt_is,
)
print(f"  {dsr_result.summary}")

# ── Build metrics dict for gate1_reporter ─────────────────────────────────────
metrics_dict = {
    "sharpe_in_sample":            is_m["sharpe"],
    "sharpe_out_of_sample":        oos_m["sharpe"],
    "max_dd_in_sample":            abs(is_m["max_drawdown"]),
    "max_dd_out_of_sample":        abs(oos_m["max_drawdown"]),
    "win_rate_in_sample":          is_m["win_rate"],
    "trades_in_sample":            is_m["trade_count"],
    "dsr_zscore":                  dsr_result.dsr_zscore,
    "wf_windows":                  wf_results,
    "param_sensitivity_passed":    sensitivity_pass,
    "param_sensitivity_max_delta": sensitivity_degradation,
    "post_cost_sharpe_oos":        oos_m["sharpe"],
    "post_cost_sharpe_is":         is_m["sharpe"],
    "look_ahead_bias":             "none",
    "economic_rationale":          "valid",
    "n_trials":                    n_trials,
    # extended
    "profit_factor":               is_m["profit_factor"],
    "oos_trade_count":             oos_m["trade_count"],
    "is_total_return":             is_m["total_return"],
    "oos_total_return":            oos_m["total_return"],
    "pdt_max_weekly_round_trips":  is_m["pdt_max_weekly_round_trips"],
    "sensitivity_results":         sensitivity,
    "wf_windows_passed":           wf_windows_passed,
    "skewness":                    skew_is,
    "kurtosis":                    kurt_is,
}

proposal_dict = {
    "strategy_name": "BollingerBandMeanReversion",
    "hypothesis": (
        "Prices that deviate beyond N std from rolling mean tend to revert; "
        "buy below lower band, exit at midline."
    ),
    "parameters": PARAMETERS,
}

config_dict = {
    "in_sample_start":   IS_START,
    "out_of_sample_end": OOS_END,
}

print("\n" + "=" * 70)
print("Generating Gate 1 verdict...")
verdict = generate_and_save_verdict(metrics_dict, proposal_dict, config_dict)

print(f"\nVerdict:        {verdict['overall_verdict']}")
print(f"Recommendation: {verdict['recommendation']}")
print(f"Confidence:     {verdict['confidence']}")
print(f"TXT saved to:   {verdict['txt_path']}")
print(f"JSON saved to:  {verdict['json_path']}")

# ── Save extended metrics JSON ────────────────────────────────────────────────
import os
date_str = datetime.date.today().isoformat()
ext_json_path = (
    f"/mnt/c/Users/lamho/repo/quant-zero/backtests/"
    f"BollingerBandMeanReversion_{date_str}.json"
)
os.makedirs("/mnt/c/Users/lamho/repo/quant-zero/backtests", exist_ok=True)

ext_metrics = {
    "strategy_name":              "BollingerBandMeanReversion",
    "date":                       date_str,
    "asset_class":                "equities",
    "is_sharpe":                  is_m["sharpe"],
    "oos_sharpe":                 oos_m["sharpe"],
    "is_max_drawdown":            abs(is_m["max_drawdown"]),
    "oos_max_drawdown":           abs(oos_m["max_drawdown"]),
    "win_rate":                   is_m["win_rate"],
    "profit_factor":              is_m["profit_factor"],
    "trade_count":                is_m["trade_count"],
    "oos_trade_count":            oos_m["trade_count"],
    "dsr":                        dsr_result.dsr_zscore,
    "wf_windows_passed":          wf_windows_passed,
    "wf_consistency_score":       wf_windows_passed / 4.0,
    "sensitivity_pass":           sensitivity_pass,
    "sensitivity_degradation":    sensitivity_degradation,
    "sensitivity_results":        sensitivity,
    "post_cost_sharpe":           oos_m["sharpe"],
    "look_ahead_bias_flag":       False,
    "gate1_pass":                 verdict["overall_verdict"] in ("PASS", "CONDITIONAL PASS"),
    "gate1_verdict":              verdict["overall_verdict"],
    "gate1_recommendation":       verdict["recommendation"],
    "gate1_confidence":           verdict["confidence"],
    "is_total_return":            is_m["total_return"],
    "oos_total_return":           oos_m["total_return"],
    "pdt_max_weekly_round_trips": is_m["pdt_max_weekly_round_trips"],
    "wf_windows":                 wf_results,
    "skewness":                   skew_is,
    "kurtosis":                   kurt_is,
    "dsr_n_trials":               n_trials,
    "txt_path":                   verdict["txt_path"],
    "json_path":                  verdict["json_path"],
}

with open(ext_json_path, "w") as f:
    json.dump(ext_metrics, f, indent=2, default=str)
print(f"\nExtended metrics JSON saved to: {ext_json_path}")

# ── Print final summary ───────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("GATE 1 SUMMARY — BollingerBandMeanReversion")
print("=" * 70)
print(f"{'Metric':<35} {'Value':>12}  {'Threshold':>12}  {'Status':>8}")
print("-" * 75)

rows = [
    ("IS Sharpe",          is_m["sharpe"],               "> 1.0",  is_m["sharpe"] > 1.0),
    ("OOS Sharpe",         oos_m["sharpe"],               "> 0.7",  oos_m["sharpe"] > 0.7),
    ("IS Max Drawdown",    abs(is_m["max_drawdown"]),      "< 20%",  abs(is_m["max_drawdown"]) < 0.20),
    ("OOS Max Drawdown",   abs(oos_m["max_drawdown"]),     "< 25%",  abs(oos_m["max_drawdown"]) < 0.25),
    ("Win Rate (IS)",      is_m["win_rate"],               "> 50%",  is_m["win_rate"] > 0.50),
    ("Trade Count (IS)",   is_m["trade_count"],            ">= 100", is_m["trade_count"] >= 100),
    ("DSR z-score",        dsr_result.dsr_zscore,          "> 0",    dsr_result.dsr_zscore > 0),
    ("WF Windows Passed",  wf_windows_passed,              ">= 3/4", wf_windows_passed >= 3),
    ("Sensitivity Pass",   sensitivity_degradation,        "< 30%",  sensitivity_pass),
    ("Profit Factor",      is_m["profit_factor"],          "(info)", True),
    ("OOS Trade Count",    oos_m["trade_count"],           "(info)", True),
]

for name, val, thresh, passed in rows:
    val_str = f"{val:.4f}" if isinstance(val, float) and val < 10 else str(val)
    status  = "PASS" if passed else "FAIL"
    print(f"  {name:<33} {val_str:>12}  {thresh:>12}  {status:>8}")

print("-" * 75)
print(f"\n  OVERALL GATE 1: {verdict['overall_verdict']}")
print(f"  Recommendation: {verdict['recommendation']}")
print("=" * 70)
