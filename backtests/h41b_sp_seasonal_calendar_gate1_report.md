# H41b S&P Seasonal Calendar Effect — Gate 1 Backtest Report

**Run date:** 2026-05-28  
**Strategy:** H41b S&P Seasonal Calendar Effect  
**Asset class:** Equities (SPY, XLF, XLK, XLE ETFs; equal-weight portfolio)  
**References:** [QUA-9](/QUA/issues/QUA-9), [QUA-8](/QUA/issues/QUA-8)  

---

## Executive Summary

| | |
|---|---|
| **Gate 1 Verdict** | **FAIL** |
| Checks passed | 4/11 |
| IS Sharpe | 0.4323 (FAIL) |
| OOS Sharpe | 0.0651 (FAIL) |
| IS Max Drawdown | -46.39% (FAIL) |
| Walk-Forward | 0/4 folds passed (FAIL) |
| Trade Count (IS) | 655 (PASS) |
| Permutation p-value | 0.9040 (FAIL) |
| OOS Data Quality | PASS |

---

## Gate 1 Checklist

| Check | Result |
|---|---|
| IS Sharpe > 1.0 | FAIL |
| OOS Sharpe > 0.7 | FAIL |
| IS MDD < 20% | FAIL |
| OOS MDD < 20% | FAIL |
| Win Rate > 50% | PASS |
| DSR > 0 | FAIL |
| WF >= 3/4 folds | FAIL |
| Trade count >= 100 (IS) | PASS |
| Sensitivity pass | PASS |
| Permutation p <= 0.05 | FAIL |
| MC p5 Sharpe >= 0.5 | PASS |

---

## Primary Configuration Metrics

**Parameters:** jan_effect_entry=5, jan_effect_exit=5, santa_entry=5, santa_exit=2, opex_thursday=True, vix_cb=35

| Metric | IS (1993–2017) | OOS (2018–2025) | Threshold |
|---|---|---|---|
| Sharpe Ratio | 0.4323 | 0.0651 | IS>1.0, OOS>0.7 |
| Max Drawdown | -46.39% | -23.71% | <20% |
| Win Rate | 56.49% | 52.24% | >50% |
| Profit Factor | 1.92 | 1.01 | >1.0 |
| Trade Count | 655 | 312 | IS>=100 |
| Liquidity Constrained (IS) | 15 | — | — |
| DSR | -18.4938 | — | >0 |

---

## Per-Ticker Results

### IS (1993–2017)

| Ticker | Sharpe | Max Drawdown | Win Rate | Trades |
|---|---|---|---|---|
| SPY | 0.6858 | -26.78% | 60.80% | 199 |
| XLF | 0.3651 | -30.14% | 53.95% | 152 |
| XLK | 0.1693 | -61.00% | 53.95% | 152 |
| XLE | 0.5291 | -29.79% | 55.92% | 152 |
| **Equal-weight portfolio** | **0.4323** | **-46.39%** | **56.49%** | **655** |

### OOS (2018–2025)

| Ticker | Sharpe | Max Drawdown | Win Rate | Trades |
|---|---|---|---|---|
| SPY | 0.1428 | -22.87% | 51.28% | 78 |
| XLF | 0.0344 | -36.96% | 51.28% | 78 |
| XLK | 0.2072 | -29.02% | 56.41% | 78 |
| XLE | -0.0958 | -43.36% | 50.00% | 78 |
| **Equal-weight portfolio** | **0.0651** | **-23.71%** | **52.24%** | **312** |

---

## Statistical Rigor

### Monte Carlo (1,000 simulations, trade PnL bootstrap)

| | Value |
|---|---|
| MC p5 Sharpe | 1.7987 |
| MC median Sharpe | 2.6155 |
| MC p95 Sharpe | 3.4533 |
| MC pessimistic bound weak (p5 < 0.5) | NO |

### Bootstrap 95% CI (block bootstrap, block=sqrt(T))

| Metric | Lower | Upper |
|---|---|---|
| Sharpe | 0.0617 | 0.8555 |
| Max Drawdown | -63.38% | -17.78% |
| Win Rate | 23.06% | 31.09% |

### Market Impact (SPY, 100 shares)

| | Value |
|---|---|
| Market impact | 0.01 bps |
| Q/ADV ratio | 0.000001 |
| Liquidity constrained | False |

### Permutation Test (500 permutations)

| | Value |
|---|---|
| p-value | 0.9040 |
| Test pass (p<=0.05) | False |

---

## Walk-Forward Results (4 Folds, Expanding IS)

| Fold | IS Window | OOS Window | IS Sharpe | OOS Sharpe | IS Trades | OOS Trades | Consistency | Pass |
|---|---|---|---|---|---|---|---|---|
| 1 | 1993-01-01–1997-11-30 | 1997-12-01–2002-10-31 | 1.1390 | -0.0397 | 39 | 136 | 1.0349 | FAIL |
| 2 | 1993-01-01–2002-10-31 | 2002-11-01–2007-09-30 | 0.1438 | 0.7310 | 175 | 136 | 4.0834 | FAIL |
| 3 | 1993-01-01–2007-09-30 | 2007-10-01–2012-08-31 | 0.2950 | 0.6834 | 311 | 192 | 1.3166 | FAIL |
| 4 | 1993-01-01–2012-08-31 | 2012-09-01–2017-07-31 | 0.4001 | 0.6491 | 503 | 136 | 0.6223 | FAIL |

**WF Sharpe std:** 0.3164 | **WF Sharpe min:** -0.0397

wf_sharpe_min < 0 — at least one losing OOS fold

---

## Parameter Sensitivity

| jan_entry | jan_exit | santa_entry | santa_exit | opex_thu | vix_cb | IS Sharpe | IS MDD | Win Rate | Trades |
|---|---|---|---|---|---|---|---|---|---|
| 5 | 5 | 5 | 2 | True | 35.0 | 0.4323 | -46.39% | 56.49% | 655 |
| 3 | 7 | 5 | 2 | True | 35.0 | 0.4384 | -46.14% | 56.64% | 655 |
| 5 | 5 | 7 | 4 | True | 35.0 | 0.4360 | -45.15% | 56.30% | 659 |
| 5 | 5 | 5 | 2 | False | 35.0 | 0.4293 | -47.06% | 55.57% | 655 |
| 5 | 5 | 5 | 2 | True | 40.0 | 0.4799 | -50.79% | 57.42% | 620 |

**Sensitivity pass:** PASS

---

## Signal Breakdown (IS)

| Signal | Trades | Win Rate | Total PnL |
|---|---|---|---|
| jan_effect | 85 | 77.65% | $234,247.27 |
| sell_in_may | 82 | 76.83% | $236,140.13 |
| santa_claus | 85 | 77.65% | $234,247.27 |
| opex_week | 634 | 55.68% | $217,712.75 |

---

## PF-4: OpEx/Pre-Holiday Overlap Analysis

| Field | Value |
|---|---|
| OpEx entries | 395 |
| Overlap count | 65 |
| Overlap rate | 16.46% |
| PF-4 pass (<= 30%) | PASS |
| Conflict resolution applied | False |

---

## OOS Data Quality

| Field | Value |
|---|---|
| Recommendation | PASS |
| Coverage | 100.0% |
| Total rows | 2010 |
| Clean rows | 2010 |
| Total NaNs | 0 |

---

## IS Trade Log (first 30 of 655 trades)

| Ticker | Signal | Entry Date | Exit Date | Entry Price | Exit Price | PnL | Exit Reason |
|---|---|---|---|---|---|---|---|
| SPY | opex_week | 1993-02-16 | 1993-02-18 | 23.9352 | 23.8654 | $-72.98 | CALENDAR |
| SPY | opex_week | 1993-03-15 | 1993-03-18 | 24.9511 | 24.913 | $-38.06 | CALENDAR |
| SPY | opex_week | 1993-04-12 | 1993-04-15 | 24.8441 | 24.8234 | $-20.78 | CALENDAR |
| SPY | opex_week | 1993-05-17 | 1993-05-20 | 24.4292 | 24.944 | $524.10 | CALENDAR |
| SPY | opex_week | 1993-06-14 | 1993-06-17 | 24.9134 | 24.9618 | $49.39 | CALENDAR |
| SPY | opex_week | 1993-07-12 | 1993-07-15 | 25.037 | 24.9652 | $-72.96 | CALENDAR |
| SPY | opex_week | 1993-08-16 | 1993-08-19 | 25.2802 | 25.4699 | $190.49 | CALENDAR |
| SPY | opex_week | 1993-09-13 | 1993-09-16 | 25.8722 | 25.6957 | $-174.40 | CALENDAR |
| SPY | opex_week | 1993-10-11 | 1993-10-14 | 25.8758 | 26.2057 | $323.64 | CALENDAR |
| SPY | jan_effect,opex_week,santa_claus,sell_in_may | 1993-11-01 | 1994-05-02 | 26.3311 | 25.7223 | $-594.71 | CALENDAR |
| SPY | opex_week | 1994-05-16 | 1994-05-19 | 25.2809 | 25.926 | $641.28 | CALENDAR |
| SPY | opex_week | 1994-06-13 | 1994-06-16 | 26.2119 | 26.325 | $111.17 | CALENDAR |
| SPY | opex_week | 1994-07-11 | 1994-07-14 | 25.573 | 25.8924 | $323.20 | CALENDAR |
| SPY | opex_week | 1994-08-15 | 1994-08-18 | 26.4654 | 26.5081 | $42.34 | CALENDAR |
| SPY | opex_week | 1994-09-12 | 1994-09-15 | 26.7782 | 27.1854 | $399.14 | CALENDAR |
| SPY | opex_week | 1994-10-17 | 1994-10-20 | 26.9952 | 26.8393 | $-153.78 | CALENDAR |
| SPY | jan_effect,opex_week,santa_claus,sell_in_may | 1994-11-01 | 1995-05-01 | 26.9952 | 29.9371 | $2,885.94 | CALENDAR |
| SPY | opex_week | 1995-05-15 | 1995-05-18 | 30.8797 | 30.2914 | $-559.43 | CALENDAR |
| SPY | opex_week | 1995-06-12 | 1995-06-15 | 31.0896 | 31.4913 | $372.42 | CALENDAR |
| SPY | opex_week | 1995-07-17 | 1995-07-20 | 33.0298 | 32.463 | $-500.51 | CALENDAR |
| SPY | opex_week | 1995-08-14 | 1995-08-17 | 32.9105 | 32.8385 | $-62.74 | CALENDAR |
| SPY | opex_week | 1995-09-11 | 1995-09-14 | 33.8166 | 34.3935 | $488.03 | CALENDAR |
| SPY | opex_week | 1995-10-16 | 1995-10-19 | 34.3745 | 34.8253 | $381.85 | CALENDAR |
| SPY | jan_effect,opex_week,santa_claus,sell_in_may | 1995-11-01 | 1996-05-01 | 34.6324 | 38.969 | $3,690.41 | CALENDAR |
| SPY | opex_week | 1996-05-13 | 1996-05-16 | 39.5129 | 39.7404 | $191.08 | CALENDAR |
| SPY | opex_week | 1996-06-17 | 1996-06-20 | 39.829 | 39.6012 | $-190.85 | CALENDAR |
| SPY | opex_week | 1996-07-15 | 1996-07-18 | 37.5063 | 38.5213 | $898.28 | CALENDAR |
| SPY | opex_week | 1996-08-12 | 1996-08-15 | 39.928 | 39.6239 | $-259.41 | CALENDAR |
| SPY | opex_week | 1996-09-16 | 1996-09-19 | 41.1906 | 41.1 | $-74.37 | CALENDAR |
| SPY | opex_week | 1996-10-14 | 1996-10-17 | 42.361 | 42.5701 | $166.44 | CALENDAR |
| ... | *625 more trades in JSON* | | | | | | |

---

*Generated by Backtest Runner Agent (QUA-9) on 2026-05-28*
*Strategy: QUA-8 | Gate 1 run: QUA-9*