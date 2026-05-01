# H41 Turn of Quarter Window Dressing — Gate 1 Backtest Report

**Run date:** 2026-05-01  
**Strategy:** H41 Turn of Quarter Window Dressing (SPY)  
**Asset class:** Equities (SPY ETF)  
**References:** [QUA-320](/QUA/issues/QUA-320), [QUA-323](/QUA/issues/QUA-323), [QUA-316](/QUA/issues/QUA-316), [QUA-308](/QUA/issues/QUA-308)  

---

## Executive Summary

| | |
|---|---|
| **Gate 1 Verdict** | **FAIL** |
| Checks passed | 3/11 |
| IS Sharpe | 0.0832 (FAIL) |
| OOS Sharpe | 0.6172 (FAIL) |
| IS Max Drawdown | -12.04% (PASS) |
| Walk-Forward | 0/4 folds passed (FAIL) |
| Trade Count (IS) | 75 (FAIL) |
| Permutation p-value | 0.7660 (FAIL) |

---

## Gate 1 Checklist

| Check | Result |
|---|---|
| IS Sharpe > 1.0 | ❌ FAIL |
| OOS Sharpe > 0.7 | ❌ FAIL |
| IS MDD < 20% | ✅ PASS |
| OOS MDD < 20% | ✅ PASS |
| Win Rate > 50% | ✅ PASS |
| DSR > 0 | ❌ FAIL |
| WF >= 3/4 folds | ❌ FAIL |
| Trade count >= 100 (IS) | ❌ FAIL |
| Sensitivity pass | ❌ FAIL |
| Permutation p <= 0.05 | ❌ FAIL |
| MC p5 Sharpe >= 0.5 | ❌ FAIL |

---

## Primary Configuration Metrics

**Parameters:** entry_days=3, hold_days=2, trend_filter_ma=200, vix_circuit_breaker=35

| Metric | IS (1993–2017) | OOS (2018–2025) | Threshold |
|---|---|---|---|
| Sharpe Ratio | 0.0832 | 0.6172 | IS>1.0, OOS>0.7 |
| Max Drawdown | -12.04% | -6.78% | <20% |
| Win Rate | 56.00% | 68.00% | >50% |
| Profit Factor | 1.14 | 2.47 | >1.0 |
| Trade Count | 75 | 25 | IS≥100 |
| Annualized Return | 0.27% | 1.87% | — |
| Liquidity Constrained | 0 | — | — |
| DSR | -103.8850 | — | >0 |

---

## Statistical Rigor

### Monte Carlo (1,000 simulations, trade PnL bootstrap)

| | Value |
|---|---|
| MC p5 Sharpe | -1.9960 |
| MC median Sharpe | 0.8005 |
| MC p95 Sharpe | 4.0058 |
| MC pessimistic flag | ⚠️ YES |

### Bootstrap 95% CI (Block bootstrap, block=√T)

| Metric | Lower | Upper |
|---|---|---|
| Sharpe | -0.3019 | 0.5449 |
| Max Drawdown | -31.57% | -7.18% |
| Win Rate | 2.58% | 3.62% |

### Market Impact (SPY, 100 shares)

| | Value |
|---|---|
| Market impact | 0.01 bps |
| Q/ADV ratio | 0.000001 |
| Liquidity constrained | False |

### Permutation Test (500 permutations, random window placement)

| | Value |
|---|---|
| p-value | 0.7660 |
| Test pass (p≤0.05) | False |

---

## Walk-Forward Results (4 Folds, Expanding IS)

| Fold | IS Window | OOS Window | IS Sharpe | OOS Sharpe | IS Trades | OOS Trades | Consistency | Pass |
|---|---|---|---|---|---|---|---|---|
| 1 | 1993-01-01–1997-11-30 | 1997-12-01–2002-10-31 | -0.2708 | 0.2776 | 17 | 10 | 2.0254 | ❌ |
| 2 | 1993-01-01–2002-10-31 | 2002-11-01–2007-09-30 | 0.0118 | 0.6157 | 27 | 17 | 51.1882 | ❌ |
| 3 | 1993-01-01–2007-09-30 | 2007-10-01–2012-08-31 | 0.0993 | 0.2908 | 42 | 14 | 1.9281 | ❌ |
| 4 | 1993-01-01–2012-08-31 | 2012-09-01–2017-07-31 | 0.1503 | -0.2441 | 55 | 19 | 2.6243 | ❌ |

**WF Sharpe std:** 0.3080 | **WF Sharpe min:** -0.2441

⚠️ wf_sharpe_min < 0 — at least one losing OOS fold

---

## Parameter Sensitivity

| entry_days | hold_days | ma | vix_cb | IS Sharpe | IS MDD | Win Rate | Trades |
|---|---|---|---|---|---|---|---|
| 3 | 2 | 200 | 35 | 0.0832 | -12.04% | 56.00% | 75 |
| 2 | 2 | 200 | 35 | 0.1551 | -8.76% | 59.74% | 77 |
| 4 | 2 | 200 | 35 | 0.2804 | -12.93% | 59.46% | 74 |
| 3 | 1 | 200 | 35 | 0.1152 | -9.54% | 58.67% | 75 |
| 3 | 2 | 150 | 35 | 0.1546 | -10.47% | 57.33% | 75 |

**Primary Sharpe:** 0.0832  
**Sensitivity pass (±50% threshold, 3/5 configs):** ❌ FAIL

---

## Data Quality (IS)

| Field | Value |
|---|---|
| survivorship_bias | not_applicable |
| price_adjustments | auto_adjust=True for SPY via yfinance |
| data_gaps | ok: max_consecutive_missing=4 (≤5) |
| earnings_exclusion | not_applicable |
| vix_availability_start | 1993-01-04 |

---

## IS Trade Log (first 30 of 75 trades)

| Entry Date | Exit Date | Entry Price | Exit Price | Net Return | PnL |
|---|---|---|---|---|---|
| 1993-03-29 | 1993-04-05 | 24.92875862121582 | 24.49687385559082 | -1.872% | $-467.97 |
| 1993-06-28 | 1993-07-06 | 25.20982551574707 | 24.61827850341797 | -2.485% | $-621.28 |
| 1993-09-28 | 1993-10-05 | 25.87458610534668 | 25.857070922851562 | -0.206% | $-51.60 |
| 1993-12-29 | 1994-01-05 | 26.52762222290039 | 26.368982315063477 | -0.735% | $-183.87 |
| 1994-09-28 | 1994-10-05 | 26.69721794128418 | 26.07782745361328 | -2.456% | $-614.11 |
| 1994-12-28 | 1995-01-05 | 26.683870315551758 | 26.638622283935547 | -0.307% | $-76.76 |
| 1995-03-29 | 1995-04-05 | 29.348289489746094 | 29.439245223999023 | 0.176% | $43.90 |
| 1995-06-28 | 1995-07-06 | 31.93646812438965 | 32.51297378540039 | 1.673% | $418.22 |
| 1995-09-27 | 1995-10-04 | 34.241249084472656 | 34.259647369384766 | -0.076% | $-18.88 |
| 1995-12-27 | 1996-01-04 | 36.41531753540039 | 36.563438415527344 | 0.279% | $69.76 |
| 1996-03-27 | 1996-04-03 | 38.52959060668945 | 39.013057708740234 | 1.128% | $282.04 |
| 1996-06-26 | 1996-07-03 | 39.72451400756836 | 40.257301330566406 | 1.215% | $303.83 |
| 1996-09-26 | 1996-10-03 | 41.26305389404297 | 41.73281478881836 | 1.014% | $253.40 |
| 1996-12-27 | 1997-01-06 | 45.8465576171875 | 44.977989196777344 | -2.015% | $-503.85 |
| 1997-03-26 | 1997-04-03 | 47.97445297241211 | 45.43450927734375 | -5.413% | $-1,353.15 |
| 1997-06-26 | 1997-07-03 | 53.926918029785156 | 56.05814743041992 | 3.832% | $957.88 |
| 1997-09-26 | 1997-10-03 | 57.73433303833008 | 59.06167984008789 | 2.181% | $545.14 |
| 1997-12-29 | 1998-01-06 | 58.67351531982422 | 59.037845611572266 | 0.504% | $125.89 |
| 1998-03-27 | 1998-04-03 | 67.45685577392578 | 69.28369140625 | 2.592% | $647.99 |
| 1998-06-26 | 1998-07-06 | 70.17931365966797 | 71.60681915283203 | 1.919% | $479.70 |
| 1998-12-29 | 1999-01-06 | 77.2650375366211 | 79.20732879638672 | 2.400% | $599.90 |
| 1999-03-29 | 1999-04-06 | 81.71636962890625 | 82.30048370361328 | 0.602% | $150.55 |
| 1999-06-28 | 1999-07-06 | 83.310546875 | 87.09925842285156 | 4.433% | $1,108.35 |
| 1999-12-29 | 2000-01-05 | 92.23129272460938 | 87.95154571533203 | -4.749% | $-1,187.19 |
| 2000-03-29 | 2000-04-05 | 95.24097442626953 | 93.96160125732422 | -1.453% | $-363.28 |
| 2000-06-28 | 2000-07-06 | 91.89430236816406 | 92.01274108886719 | 0.018% | $4.48 |
| 2002-03-26 | 2002-04-03 | 73.68045043945312 | 72.95183563232422 | -1.102% | $-275.49 |
| 2003-06-26 | 2003-07-03 | 65.0248794555664 | 64.98538970947266 | -0.176% | $-44.02 |
| 2003-09-26 | 2003-10-03 | 66.03429412841797 | 68.30696868896484 | 3.325% | $831.20 |
| 2003-12-29 | 2004-01-06 | 73.78742980957031 | 74.71012115478516 | 1.136% | $284.07 |
| ... | *45 more trades in JSON* | | | | |

---

## Implementation Shortfall Tracking Schema

| Field | Value |
|---|---|
| strategy_name | H41_TurnOfQuarterWindowDressing |
| backtest_sharpe_is | 0.0832 |
| backtest_mdd_is | -12.04% |
| gate1_run_date | 2026-05-01 |
| gate1_verdict | FAIL |

---

*Generated by Engineering Director (QUA-320) on 2026-05-01*
*Strategy: QUA-323 | Pre-flight: QUA-316 | Discovery: QUA-308*