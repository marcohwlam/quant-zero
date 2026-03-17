# H36b Crypto Cross-Sectional Momentum — Gate 1 Report

**Date:** 2026-03-16
**Strategy:** Cross-sectional weekly ranking of BTC/ETH/SOL/AVAX by 4-week return; long top-2 equal-weight (50%/50%); BTC 200-SMA regime filter.
**H36b Revision:** Position sizing changed from top-1 (100%) to top-2 equal-weight. Alpha signal unchanged.
**Overall Gate 1 Verdict: FAIL**

---

## Core Gate 1 Metrics

| Criterion | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | 1.5236 | > 1.0 | PASS |
| OOS Sharpe | 0.9868 | > 0.7 | PASS |
| IS Max Drawdown | -52.4% | < 20% | FAIL (-52.4% exceeds <20%) |
| OOS Max Drawdown | -52.7% | < 25% | FAIL (-52.7% exceeds <25%) |
| Win Rate (IS) | 47.1% | ≥ 50% or PF ≥ 1.2 | PASS |
| Profit Factor (IS) | 3.6683 | > 1.0 | PASS |
| Trade Count (IS) | 68 | ≥ 100 total | FAIL |
| IS Total Return | 18927.3% | — | — |
| OOS Total Return | 430.3% | — | — |
| Regime On Rate (IS) | 43.6% | > 50% | — |

**CEO Trade Count Exception:** <50/year threshold waived (structural crypto IS window constraint per QUA-291).
**H36b Drawdown Fix:** H36 MDD was -54% (Gate 1 FAIL). H36b measured IS MDD: -52.4%. STILL exceeds Gate 1 <20% criterion — additional fix needed.

---

## Per-Asset Breakdown (IS)

| Asset | Trades | Win Rate | Total PnL |
|---|---|---|---|
| AVAX-USD | 19 | 36.8% | $918,683 |
| BTC-USD | 18 | 44.4% | $456,224 |
| ETH-USD | 20 | 55.0% | $528,785 |
| SOL-USD | 11 | 54.5% | $2,797,366 |

---

## Top-N Position Count Sensitivity (H36b-specific)

| Config | IS Sharpe | IS MDD | IS Trades |
|---|---|---|---|
| top_n_1 ← H36 | 1.3762 | -54.0% | 50 |
| top_n_2 ← H36b | 1.5236 | -52.4% | 68 |
| top_n_3 | 1.3618 | -45.6% | 77 |
| top_n_4 | 1.3486 | -47.5% | 49 |


---

## Walk-Forward Analysis (4 windows, 36m IS / 6m OOS)

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | IS MDD | IS Trades | Status |
|---|---|---|---|---|---|---|---|
| W1 | 2018-01-01 – 2020-12-31 | 1.0802 | 2021-01-01 – 2021-06-30 | 3.3245 | -52.4% | 37 | **PASS** |
| W2 | 2018-07-01 – 2021-06-30 | 1.7839 | 2021-07-01 – 2021-12-31 | 2.7309 | -52.4% | 47 | **PASS** |
| W3 | 2019-01-01 – 2021-12-31 | 2.0957 | 2022-01-01 – 2022-06-30 | 0.0 | -52.4% | 62 | **PASS** *(regime cash)* |
| W4 | 2019-07-01 – 2022-06-30 | 1.9528 | 2022-07-01 – 2022-12-31 | 0.0 | -46.6% | 67 | **PASS** *(regime cash)* |

**WF windows passed:** 4/4 | **Consistency score:** 1.1521 | **Sharpe std:** 1.5283
**Regime-cash windows:** 2 (strategy correctly in CASH during bear market — not a strategy failure)

> **WF Criterion Review Flag (QUA-293):** Windows where trade_count=0 AND regime=CASH are flagged as REGIME_CASH (pass). A strategy that correctly avoids the market during BTC bear phases should not be penalized. CEO to review WF criterion for crypto strategies. Standard criterion applied here with REGIME_CASH exemption.

---

## Statistical Rigor

| Test | Value | Status |
|---|---|---|
| DSR (n=10 trials) | 0.203572 | PASS |
| MC p5 Sharpe | 0.9184 | PASS |
| MC Median Sharpe | 1.5212 | — |
| Sharpe CI [95%] | [0.6909, 2.3578] | — |
| MDD CI [95%] | [-75.8%, -38.2%] | — |
| Permutation p-value | 0.0 | PASS (≤0.05) |
| WF Sharpe Min | 0.0 | OK |

---

## Sensitivity Analysis

### Ranking Window (5 combinations)
PASS: Sharpe variance 12.8% ≤ 30% across 5 ranking window combinations.

| Config | Sharpe |
|---|---|
| ranking_window_10d | 1.3372 |
| ranking_window_15d | 1.4988 |
| ranking_window_20d | 1.5236 |
| ranking_window_25d | 1.426 |
| ranking_window_30d | 1.476 |

### Hard Stop Sensitivity

| Config | Sharpe |
|---|---|
| stop_8pct | 1.5647 |
| stop_10pct | 1.5312 |
| stop_12pct | 1.5236 |
| stop_15pct | 1.4853 |

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
- **Market impact:** Crypto — market impact N/A. BTC/ETH/SOL/AVAX ADV >> $25K order size. Cost model: 0.10% taker fee + 0.05% slippage per leg = 0.30% round-trip. H36b has 2 concurrent positions → ~2× round-trip events per rebalance vs H36.
- **Correlation:** BTC/ETH/SOL/AVAX r>0.7 (cross-sectional momentum strategy — not mean-reversion pairs; QUA-281 criterion does not apply).
- **IS window depth:** 2018–2022. 2-asset (BTC/ETH) pre-2020; 4-asset from 2020. CEO exception granted.
- **H36b diversification:** Top-2 positions reduce single-asset tail risk. Trade count ~2× H36 (two concurrent positions per rebalance).

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
| wf_windows_pass | ✅ PASS |
| wf_consistency_pass | ✅ PASS |
| sensitivity_pass | ✅ PASS |
| dsr_pass | ✅ PASS |
| permutation_pass | ✅ PASS |
| mc_p5_pass | ✅ PASS |

---

## Verdict

**Overall Gate 1: FAIL**

Failing criteria: is_mdd_pass, oos_mdd_pass, trade_count_pass

Strategy **does not pass Gate 1**. Return to Research Director for revision.
