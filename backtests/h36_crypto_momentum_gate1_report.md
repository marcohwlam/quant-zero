# H36 Crypto Cross-Sectional Momentum — Gate 1 Report

**Date:** 2026-03-16
**Strategy:** Cross-sectional weekly ranking of BTC/ETH/SOL/AVAX by 4-week return; long top-1; BTC 200-SMA regime filter.
**Overall Gate 1 Verdict: FAIL**

---

## Core Gate 1 Metrics

| Criterion | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | 1.3762 | > 1.0 | PASS |
| OOS Sharpe | 0.8578 | > 0.7 | PASS |
| IS Max Drawdown | -54.0% | < 20% | FAIL (-54.0% exceeds <20%) |
| OOS Max Drawdown | -59.8% | < 25% | FAIL (-59.8% exceeds <25%) |
| Win Rate (IS) | 48.0% | ≥ 50% or PF ≥ 1.2 | PASS |
| Profit Factor (IS) | 2.6157 | > 1.0 | PASS |
| Trade Count (IS) | 50 | ≥ 100 total | FAIL |
| IS Total Return | 23211.2% | — | — |
| OOS Total Return | 335.2% | — | — |
| Regime On Rate (IS) | 43.6% | > 50% | — |

**CEO Trade Count Exception:** <50/year threshold waived (structural crypto IS window constraint per QUA-291).
**CEO Drawdown Flag:** Estimated 25–40% drawdown. BTC trend filter INSUFFICIENT — DD exceeds Gate 1 <20% criterion.

---

## Per-Asset Breakdown (IS)

| Asset | Trades | Win Rate | Total PnL |
|---|---|---|---|
| AVAX-USD | 14 | 21.4% | $1,311,376 |
| BTC-USD | 13 | 53.8% | $1,194,282 |
| ETH-USD | 12 | 50.0% | $-550,950 |
| SOL-USD | 11 | 72.7% | $3,969,539 |

---

## Walk-Forward Analysis (4 windows, 36m IS / 6m OOS)

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | IS MDD | IS Trades | Status |
|---|---|---|---|---|---|---|---|
| W1 | 2018-01-01 – 2020-12-31 | 1.2777 | 2021-01-01 – 2021-06-30 | 2.2592 | -50.1% | 25 | **PASS** |
| W2 | 2018-07-01 – 2021-06-30 | 1.6214 | 2021-07-01 – 2021-12-31 | 1.939 | -54.0% | 37 | **PASS** |
| W3 | 2019-01-01 – 2021-12-31 | 1.8054 | 2022-01-01 – 2022-06-30 | 0.0 | -54.0% | 47 | **FAIL** |
| W4 | 2019-07-01 – 2022-06-30 | 1.668 | 2022-07-01 – 2022-12-31 | 0.0 | -54.0% | 46 | **FAIL** |

**WF windows passed:** 2/4 | **Consistency score:** 0.741 | **Sharpe std:** 1.0556

---

## Statistical Rigor

| Test | Value | Status |
|---|---|---|
| DSR (n=9 trials) | 0.010178 | PASS |
| MC p5 Sharpe | 0.8129 | PASS |
| MC Median Sharpe | 1.3686 | — |
| Sharpe CI [95%] | [0.6282, 2.0345] | — |
| MDD CI [95%] | [-0.8359, -0.4414] | — |
| Permutation p-value | 0.002 | PASS (≤0.05) |
| WF Sharpe Min | 0.0 | OK |

---

## Sensitivity Analysis

### Ranking Window (5 combinations)
PASS: Sharpe variance 20.5% ≤ 30% across 5 ranking window combinations.

| Config | Sharpe |
|---|---|
| ranking_window_10d | 1.5058 |
| ranking_window_15d | 1.3855 |
| ranking_window_20d | 1.3762 |
| ranking_window_25d | 1.3265 |
| ranking_window_30d | 1.2259 |

### Hard Stop Sensitivity

| Config | Sharpe |
|---|---|
| stop_8pct | 1.4688 |
| stop_10pct | 1.4117 |
| stop_12pct | 1.3762 |
| stop_15pct | 1.3583 |

---

## Data Quality Checklist

- **Survivorship bias:** BTC-USD: trading since 2009. ETH-USD: trading since 2015. SOL-USD: trading since ~2020. AVAX-USD: trading since ~2020. Universe is dynamically restricted to assets with data on each ranking date — 2018-2019 uses only BTC/ETH (2-asset). No survivorship bias: assets are not delisted; all included with actual history (no fictitious backfills).
- **Price adjustments:** yfinance auto_adjust=True for all tickers.
- **Earnings exclusion:** N/A — crypto assets have no earnings events.
- **Delisted tickers:** N/A — BTC, ETH, SOL, AVAX are not subject to exchange delisting. All four remain actively traded through the backtest window.

### Per-Ticker Data Availability (IS Window)

| Ticker | Bars | Missing Days | Data Start | Available at IS Start |
|---|---|---|---|---|
| AVAX-USD | 832 | 49 | 2020-07-13 | False |
| BTC-USD | 1825 | 0 | 2016-09-28 | True |
| ETH-USD | 1825 | 0 | 2017-11-09 | True |
| SOL-USD | 995 | 0 | 2020-04-10 | False |

---

## Risk Flags

- **Look-ahead bias:** None detected. Friday signal shifted 1 bar before use.
- **Market impact:** Crypto — market impact N/A. BTC/ETH/SOL/AVAX ADV >> $25K order size. Cost model: 0.10% taker fee + 0.05% slippage per leg = 0.30% round-trip.
- **Correlation:** BTC/ETH/SOL/AVAX r>0.7 (cross-sectional momentum strategy — not mean-reversion pairs; QUA-281 criterion does not apply).
- **IS window depth:** 2018–2022. 2-asset (BTC/ETH) pre-2020; 4-asset from 2020. CEO exception granted.

---

## Gate 1 Checklist

| Check | Pass? |
|---|---|
| is_sharpe_pass | ✅ PASS |
| oos_sharpe_pass | ✅ PASS |
| is_mdd_pass | ❌ FAIL |
| oos_mdd_pass | ❌ FAIL |
| win_rate_pass | ✅ PASS |
| trade_count_pass | ❌ FAIL |
| wf_windows_pass | ❌ FAIL |
| wf_consistency_pass | ✅ PASS |
| sensitivity_pass | ✅ PASS |
| dsr_pass | ✅ PASS |
| permutation_pass | ✅ PASS |
| mc_p5_pass | ✅ PASS |

---

## Verdict

**Overall Gate 1: FAIL**

Failing criteria: is_mdd_pass, oos_mdd_pass, trade_count_pass, wf_windows_pass

Strategy **does not pass Gate 1**. Return to Research Director for revision.
