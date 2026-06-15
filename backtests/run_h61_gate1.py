#!/repos/quant-zero/.venv/bin/python3
"""
H61 Gate 1 Backtest Runner — QUA-183
Overnight Intraday Reversal (Lou, Polk & Skouras 2019)
IS: 2018-01-01 to 2024-12-31 | WF: 6 windows, 36mo IS / 6mo OOS

Outputs:
  backtests/h61_overnight_intraday_reversal_{date}.json
  backtests/h61_overnight_intraday_reversal_{date}_report.md
  backtests/h61_overnight_intraday_reversal_{date}_verdict.txt
  backtests/h61_overnight_intraday_reversal_{date}_trades.csv

Usage:
  cd /repos/quant-zero
  .venv/bin/python3 backtests/run_h61_gate1.py
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.h61_overnight_intraday_reversal import (
    PARAMETERS,
    WF_WINDOWS,
    IS_START,
    IS_END,
    download_data,
    run_strategy,
    compute_signals,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

OUT_DIR = Path(__file__).parent
TODAY = date.today().isoformat()
SLUG = f"h61_overnight_intraday_reversal_{TODAY}"

GATE1_IS_SHARPE_MIN = 1.0
GATE1_OOS_SHARPE_MIN = 0.7
GATE1_MDD_MAX = -0.20
GATE1_MIN_TRADES = 100
GATE1_WF_WINDOWS_MIN = 3


# ── Statistical Rigor Pipeline ─────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    """Bootstrap Monte Carlo on trade PnL — p5, median, p95 Sharpe."""
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
    """Block bootstrap 95% CI for Sharpe, MDD, win rate."""
    if len(returns) < 4:
        return {
            "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
            "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
        }
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)

    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-10)))
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
    daily_rets: pd.Series,
    observed_sharpe: float,
    n_perms: int = 500,
) -> dict:
    """
    Permutation test: shuffle trade-day assignment. p-value = fraction of
    permuted Sharpes >= observed_sharpe. p <= 0.05 → significant alpha.
    """
    rets_arr = daily_rets.values.copy()
    n_trades = int(np.sum(rets_arr != 0.0))
    if n_trades < 2:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}

    trade_ret_values = rets_arr[rets_arr != 0.0]
    n_days = len(rets_arr)

    permuted_sharpes = []
    for _ in range(n_perms):
        perm = np.zeros(n_days)
        idx = np.random.choice(n_days, size=n_trades, replace=False)
        perm[idx] = np.random.permutation(trade_ret_values)
        std = perm.std()
        if std > 0:
            s = float(perm.mean() / std * np.sqrt(252))
        else:
            s = 0.0
        permuted_sharpes.append(s)

    p_value = float(np.mean(np.array(permuted_sharpes) >= observed_sharpe))
    return {
        "permutation_pvalue": round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    if len(wf_oos_sharpes) == 0:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


def compute_market_impact(ticker_data: pd.DataFrame, shares: int = 200) -> dict:
    """
    SPY is ultra-liquid (ADV >> 50M/day); impact is negligible for retail-size orders.
    Uses most recent 20-day ADV and vol from the provided DataFrame.
    """
    adv = float(ticker_data["Volume"].rolling(20).mean().iloc[-1])
    sigma = float(ticker_data["Close"].pct_change().rolling(20).std().iloc[-1])
    k = 0.1
    impact_pct = k * sigma * np.sqrt(shares / (adv + 1.0))
    impact_bps = impact_pct * 10000
    return {
        "market_impact_bps": round(impact_bps, 4),
        "liquidity_constrained": bool(shares > 0.01 * adv),
        "order_to_adv_ratio": round(shares / (adv + 1.0), 8),
    }


# ── Data Quality Checklist ─────────────────────────────────────────────────────

def data_quality_report(df: pd.DataFrame, start: str, end: str) -> dict:
    """
    Pre-backtest data quality checklist per AGENTS.md engineering director standards.
    Checks: price adjustment, data gaps, volume completeness.
    """
    window = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    na_close = int(window["Close"].isna().sum())
    na_open = int(window["Open"].isna().sum())
    total_bars = len(window)
    coverage_pct = round((total_bars - na_close) / max(total_bars, 1) * 100, 2)
    large_gap_days = int((window["Close"].isna().rolling(5).sum() > 0).sum())
    return {
        "ticker": "SPY",
        "universe_note": "Single ETF, no survivorship bias applicable",
        "price_adjustment": "yfinance auto_adjust=True (split + dividend adjusted)",
        "total_bars": total_bars,
        "na_close_bars": na_close,
        "na_open_bars": na_open,
        "coverage_pct": coverage_pct,
        "large_gap_flag": large_gap_days > 5,
        "earnings_exclusion": "Not applicable — SPY ETF, no single-stock earnings events",
        "delisted_risk": "None — SPY is continuously listed since 1993",
    }


# ── Gate 1 Verdict ─────────────────────────────────────────────────────────────

def gate1_verdict(metrics: dict, wf_windows_passed: int) -> tuple:
    failures = []
    if metrics["is_summary"]["sharpe"] < GATE1_IS_SHARPE_MIN:
        failures.append(
            f"IS Sharpe {metrics['is_summary']['sharpe']:.3f} < {GATE1_IS_SHARPE_MIN} threshold"
        )
    if metrics["oos_avg_sharpe"] < GATE1_OOS_SHARPE_MIN:
        failures.append(
            f"OOS avg Sharpe {metrics['oos_avg_sharpe']:.3f} < {GATE1_OOS_SHARPE_MIN} threshold"
        )
    if metrics["is_summary"]["max_drawdown"] < GATE1_MDD_MAX:
        failures.append(
            f"IS MDD {metrics['is_summary']['max_drawdown']:.1%} > {GATE1_MDD_MAX:.0%} gate"
        )
    if metrics["is_summary"]["trade_count"] < GATE1_MIN_TRADES:
        failures.append(
            f"IS trade count {metrics['is_summary']['trade_count']} < {GATE1_MIN_TRADES} minimum"
        )
    if wf_windows_passed < GATE1_WF_WINDOWS_MIN:
        failures.append(
            f"WF stability {wf_windows_passed}/{len(WF_WINDOWS)} < {GATE1_WF_WINDOWS_MIN} required"
        )
    verdict = "PASS" if not failures else "FAIL"
    return verdict, failures


# ── Report Formatter ───────────────────────────────────────────────────────────

def format_report(
    metrics: dict,
    wf_detail: list,
    verdict: str,
    failures: list,
    rigor: dict,
    dq: dict,
) -> str:
    is_s = metrics["is_summary"]
    lines = [
        "# H61 Gate 1 Backtest Report",
        "",
        "**Strategy:** Overnight Intraday Reversal — SPY",
        f"**Date:** {TODAY}",
        "**Issue:** QUA-183",
        "**Hypothesis:** research/hypotheses/61_overnight_intraday_reversal.md",
        "**Source:** Lou, Polk & Skouras (2019), JFE 134(1)",
        "",
        "---",
        "",
        f"## Gate 1 Verdict: {verdict}",
        "",
    ]
    if failures:
        lines.append("### Failures")
        for f in failures:
            lines.append(f"- {f}")
        lines.append("")
    else:
        lines += ["All Gate 1 criteria passed.", ""]

    lines += [
        "---",
        "",
        "## Key Metrics (SPY)",
        "",
        "| Metric | IS (2018–2024) | OOS (WF avg) | Gate |",
        "|---|---|---|---|",
        f"| Net Sharpe | {is_s['sharpe']:.3f} | {metrics['oos_avg_sharpe']:.3f} | IS > 1.0, OOS > 0.7 |",
        f"| Max Drawdown | {is_s['max_drawdown']:.1%} | — | < 20% |",
        f"| Win Rate | {is_s['win_rate']:.1%} | — | — |",
        f"| Trade Count | {is_s['trade_count']} | — | IS ≥ 100 |",
        f"| Profit Factor | {is_s['profit_factor'] or 'N/A'} | — | — |",
        f"| Avg Net P&L (bps) | {is_s['avg_net_bps']:.2f} | — | > 0 |",
        f"| Total Return | {is_s['total_return_pct']:.2f}% | — | — |",
        "",
        "### Walk-Forward Stability",
        f"- Profitable OOS windows: {metrics['wf_windows_passed']}/{len(WF_WINDOWS)}",
        f"- WF Sharpe std: {rigor['wf_sharpe_std']:.3f}",
        f"- WF Sharpe min: {rigor['wf_sharpe_min']:.3f}",
        f"- Gate (≥ {GATE1_WF_WINDOWS_MIN}/{len(WF_WINDOWS)}): {'PASS' if metrics['wf_windows_passed'] >= GATE1_WF_WINDOWS_MIN else 'FAIL'}",
        "",
        "### Walk-Forward Window Detail",
        "",
        "| Window | IS Sharpe | OOS Sharpe | OOS Trades | OOS Win% |",
        "|---|---|---|---|---|",
    ]
    for w in wf_detail:
        lines.append(
            f"| W{w['window']} IS {w['is_start'][:7]}–{w['is_end'][:7]} → OOS {w['oos_start'][:7]} "
            f"| {w['is_sharpe']:.3f} | {w['oos_sharpe']:.3f} | {w['oos_trades']} | {w['oos_win_rate']:.1%} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Statistical Rigor",
        "",
        f"| Test | Value | Note |",
        f"|---|---|---|",
        f"| MC p5 Sharpe | {rigor['mc_p5_sharpe']:.3f} | Pessimistic bound (flag if < 0.5) |",
        f"| MC Median Sharpe | {rigor['mc_median_sharpe']:.3f} | Bootstrap median |",
        f"| Sharpe 95% CI | [{rigor['sharpe_ci_low']:.3f}, {rigor['sharpe_ci_high']:.3f}] | Block bootstrap |",
        f"| Win Rate 95% CI | [{rigor['win_rate_ci_low']:.1%}, {rigor['win_rate_ci_high']:.1%}] | |",
        f"| Permutation p-value | {rigor['permutation_pvalue']:.4f} | PASS if ≤ 0.05 |",
        f"| Permutation test | {'PASS' if rigor['permutation_test_pass'] else 'FAIL'} | |",
        f"| Market impact (bps) | {rigor['market_impact_bps']:.3f} | SPY 200-share order |",
        f"| Liquidity constrained | {rigor['liquidity_constrained']} | |",
        "",
        "---",
        "",
        "## Data Quality",
        "",
        f"- Universe: {dq['universe_note']}",
        f"- Price adjustment: {dq['price_adjustment']}",
        f"- Total bars (IS window): {dq['total_bars']}",
        f"- Missing Close bars: {dq['na_close_bars']}",
        f"- Coverage: {dq['coverage_pct']}%",
        f"- Large gap flag: {dq['large_gap_flag']}",
        f"- Earnings exclusion: {dq['earnings_exclusion']}",
        "",
        "---",
        "",
        "## Transaction Cost Model (Applied)",
        "",
        "- Asset class: SPY (ultra-liquid ETF, ADV >> 50M shares/day per ED-SLIP-001)",
        "- Fixed cost: $0.005/share per leg",
        "- Slippage: 0.005% per leg (ED-SLIP-001 ultra-liquid tier, NOT standard 0.05%)",
        "- Market impact: 0.1 × σ × sqrt(Q / ADV) per leg",
        "",
        "---",
        "",
        "## Files",
        "",
        f"- Metrics: `backtests/{SLUG}.json`",
        f"- Report: `backtests/{SLUG}_report.md`",
        f"- Verdict: `backtests/{SLUG}_verdict.txt`",
        f"- Trades: `backtests/{SLUG}_trades.csv`",
    ]
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("=== H61 Gate 1 Backtest — QUA-183 ===")
    log.info("IS window: %s to %s", IS_START, IS_END)
    log.info("Parameters: threshold=%.3f%%, trend_ma=%d",
             PARAMETERS["intraday_threshold"] * 100, PARAMETERS["trend_ma_period"])

    # Download once with enough warmup for 200-DMA
    log.info("Downloading SPY data...")
    df = download_data(PARAMETERS["ticker"], IS_START, IS_END, PARAMETERS["trend_ma_period"])
    log.info("Downloaded %d bars (%s to %s)", len(df), df.index[0].date(), df.index[-1].date())

    # Data quality check
    dq = data_quality_report(df, IS_START, IS_END)
    log.info("Data quality: %d bars, %.1f%% coverage", dq["total_bars"], dq["coverage_pct"])
    if dq["large_gap_flag"]:
        log.warning("DATA QUALITY: large gap flag triggered — review before reporting")

    # IS backtest (full 2018–2024)
    log.info("Running IS backtest...")
    is_result = run_strategy(df, PARAMETERS, IS_START, IS_END)
    is_sum = is_result["summary"]
    log.info(
        "IS: Sharpe=%.3f, MDD=%.1f%%, Trades=%d, WinRate=%.1f%%",
        is_sum["sharpe"],
        is_sum["max_drawdown"] * 100,
        is_sum["trade_count"],
        is_sum["win_rate"] * 100,
    )

    # Walk-forward windows
    log.info("Running %d walk-forward windows...", len(WF_WINDOWS))
    wf_detail = []
    oos_sharpes = []
    for w in WF_WINDOWS:
        wf_is = run_strategy(df, PARAMETERS, w["is_start"], w["is_end"])
        wf_oos = run_strategy(df, PARAMETERS, w["oos_start"], w["oos_end"])
        oos_sharpes.append(wf_oos["summary"]["sharpe"])
        wf_detail.append({
            "window": w["window"],
            "is_start": w["is_start"],
            "is_end": w["is_end"],
            "oos_start": w["oos_start"],
            "oos_end": w["oos_end"],
            "is_sharpe": wf_is["summary"]["sharpe"],
            "oos_sharpe": wf_oos["summary"]["sharpe"],
            "oos_trades": wf_oos["summary"]["trade_count"],
            "oos_win_rate": wf_oos["summary"]["win_rate"],
            "oos_max_drawdown": wf_oos["summary"]["max_drawdown"],
        })
        log.info(
            "  W%d: IS Sharpe=%.3f, OOS Sharpe=%.3f (%d trades)",
            w["window"],
            wf_is["summary"]["sharpe"],
            wf_oos["summary"]["sharpe"],
            wf_oos["summary"]["trade_count"],
        )

    wf_windows_passed = sum(1 for s in oos_sharpes if s > 0)
    oos_avg_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0

    metrics = {
        "is_summary": is_sum,
        "oos_avg_sharpe": round(oos_avg_sharpe, 4),
        "wf_windows_passed": wf_windows_passed,
        "wf_detail": wf_detail,
    }

    # Statistical Rigor Pipeline
    log.info("Running statistical rigor pipeline...")
    trade_pnls = np.array([t["net_return_pct"] / 100.0 for t in is_result["trade_log"]])
    daily_rets_arr = is_result["daily_returns"].values

    mc = monte_carlo_sharpe(trade_pnls)
    log.info("  Monte Carlo: p5=%.3f, median=%.3f, p95=%.3f",
             mc["mc_p5_sharpe"], mc["mc_median_sharpe"], mc["mc_p95_sharpe"])
    if mc["mc_p5_sharpe"] < 0.5:
        log.warning("  MC pessimistic bound weak (p5 Sharpe < 0.5)")

    ci = block_bootstrap_ci(daily_rets_arr)
    log.info("  Sharpe 95%% CI: [%.3f, %.3f]", ci["sharpe_ci_low"], ci["sharpe_ci_high"])

    perm = permutation_test_alpha(is_result["daily_returns"], is_sum["sharpe"])
    log.info("  Permutation p-value: %.4f (%s)",
             perm["permutation_pvalue"], "PASS" if perm["permutation_test_pass"] else "FAIL")

    wf_var = walk_forward_variance(oos_sharpes)
    log.info("  WF Sharpe std=%.3f, min=%.3f", wf_var["wf_sharpe_std"], wf_var["wf_sharpe_min"])
    if wf_var["wf_sharpe_min"] < 0:
        log.warning("  WF: at least one losing OOS window (wf_sharpe_min < 0)")

    mi = compute_market_impact(df)
    log.info("  Market impact: %.4f bps (liquidity_constrained=%s)",
             mi["market_impact_bps"], mi["liquidity_constrained"])

    rigor = {**mc, **ci, **perm, **wf_var, **mi}

    # Gate 1 verdict
    verdict, failures = gate1_verdict(metrics, wf_windows_passed)
    log.info("Gate 1 verdict: %s", verdict)
    if failures:
        for f in failures:
            log.warning("  FAIL: %s", f)

    # Build full output JSON
    output = {
        "strategy_name": "H61_OvernightIntradayReversal",
        "date": TODAY,
        "issue": "QUA-183",
        "asset_class": "equities",
        "ticker": PARAMETERS["ticker"],
        "parameters": {k: v for k, v in PARAMETERS.items() if k != "init_cash"},
        "is_start": IS_START,
        "is_end": IS_END,
        "verdict": verdict,
        "gate1_failures": failures,
        "is_sharpe": is_sum["sharpe"],
        "oos_sharpe": round(oos_avg_sharpe, 4),
        "is_max_drawdown": is_sum["max_drawdown"],
        "win_rate": is_sum["win_rate"],
        "profit_factor": is_sum["profit_factor"],
        "trade_count": is_sum["trade_count"],
        "avg_net_bps": is_sum["avg_net_bps"],
        "total_return_pct": is_sum["total_return_pct"],
        "wf_windows_passed": wf_windows_passed,
        "wf_total_windows": len(WF_WINDOWS),
        "wf_detail": wf_detail,
        **rigor,
        "gate1_pass": verdict == "PASS",
        "look_ahead_bias_flag": False,
        "data_quality": dq,
        "slippage_note": "ED-SLIP-001: SPY ultra-liquid 0.005%/leg (not standard 0.05%)",
    }

    # Save JSON
    json_path = OUT_DIR / f"{SLUG}.json"
    json_path.write_text(json.dumps(output, indent=2, default=str))
    log.info("Metrics saved: %s", json_path)

    # Save trade CSV
    trades_df = pd.DataFrame(is_result["trade_log"])
    trades_path = OUT_DIR / f"{SLUG}_trades.csv"
    if not trades_df.empty:
        trades_df.to_csv(trades_path, index=False)
    log.info("Trade log saved: %s (%d trades)", trades_path, len(is_result["trade_log"]))

    # Save report
    report_text = format_report(metrics, wf_detail, verdict, failures, rigor, dq)
    report_path = OUT_DIR / f"{SLUG}_report.md"
    report_path.write_text(report_text)
    log.info("Report saved: %s", report_path)

    # Save verdict
    verdict_lines = [
        f"H61 Gate 1 Verdict: {verdict}",
        f"Date: {TODAY}",
        f"Issue: QUA-183",
        "",
        f"IS Sharpe (SPY, 2018-2024): {is_sum['sharpe']:.4f}",
        f"OOS Avg Sharpe (WF): {oos_avg_sharpe:.4f}",
        f"IS Max Drawdown: {is_sum['max_drawdown']:.4f}",
        f"IS Trade Count: {is_sum['trade_count']}",
        f"WF Stability: {wf_windows_passed}/{len(WF_WINDOWS)} profitable OOS windows",
        f"MC p5 Sharpe: {mc['mc_p5_sharpe']:.4f}",
        f"Permutation p-value: {perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})",
        "",
    ]
    if failures:
        verdict_lines.append("Gate 1 Failures:")
        for f in failures:
            verdict_lines.append(f"  - {f}")
    else:
        verdict_lines.append("All Gate 1 criteria: PASS")

    verdict_path = OUT_DIR / f"{SLUG}_verdict.txt"
    verdict_path.write_text("\n".join(verdict_lines))
    log.info("Verdict saved: %s", verdict_path)

    return verdict, output


if __name__ == "__main__":
    verdict, _ = main()
    sys.exit(0 if verdict == "PASS" else 1)
