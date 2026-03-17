# Gate 1 Verdict: H35 VRP Timer on SPY
**Date:** 2026-03-16
**Overall Verdict:** FAIL
**Recommendation:** Return to Strategy Coder — does not meet Gate 1 criteria

## Summary Metrics

| Metric | IS Value | OOS Value | Threshold | Pass? |
|---|---|---|---|---|
| Sharpe Ratio | 0.5052 | 0.3370 | IS>1.0, OOS>0.7 | IS:✗ OOS:✗ |
| Max Drawdown | -0.2632 | -0.2168 | IS<20%, OOS<25% | IS:✗ OOS:✓ |
| Win Rate | 0.6739 | 0.5833 | >50% | ✓ |
| Profit Factor | 3.1240 | 1.4874 | - | - |
| Trade Count | 46 | 12 | ≥100 | ✗ (CEO QUA-281 exception) |
| DSR | 1.0000 | - | >0 | ✓ |
| Post-cost Sharpe | 0.5052 | 0.3370 | - | - |
| WF Windows Passed | 1/4 | - | ≥3/4 | ✗ |

## Statistical Rigor

| Test | Value | Pass? |
|---|---|---|
| MC p5 Sharpe | 2.4833 | ✓ |
| MC Median Sharpe | 5.5254 | - |
| Bootstrap 95% CI (Sharpe) | [0.085, 0.936] | - |
| Bootstrap 95% CI (MDD) | [-0.418, -0.152] | - |
| Permutation p-value | 0.5660 | ✗ |
| Market Impact (bps) | 0.02 | OK |
| WF Sharpe std | 0.7728 | - |
| WF Sharpe min | -0.4108 ⚠️ Losing OOS window detected | - |
| Sensitivity Pass | False | ✗ |

## OOS Data Quality
- Recommendation: **PASS**
- Critical NaN fields: none
- Advisory NaN fields: none

## Walk-Forward Windows

| Window | OOS Period | Sharpe | Pass? |
|---|---|---|---|
| 1 | 2010-01-01 → 2010-06-30 | -0.3012 | ✗ |
| 2 | 2013-01-01 → 2013-06-30 | 0.3016 | ✗ |
| 3 | 2016-01-01 → 2016-06-30 | -0.4108 | ✗ |
| 4 | 2019-01-01 → 2019-06-30 | 1.5344 | ✓ |

## Failing Criteria
- is_sharpe_gt_1
- oos_sharpe_gt_0_7
- is_mdd_lt_20pct
- wf_windows_passed_3_of_4
- sensitivity_pass
- min_100_trades
- permutation_test_pass

## Research Director Warning
Expected IS Sharpe is 0.8–1.2 (borderline). If IS Sharpe < 0.9, flag for early termination.
IS Sharpe = 0.5052 — BELOW 0.9 THRESHOLD ⚠️

## PF-1 Trade Count Exception
PF-1 EXCEPTION: 46 trades total / 3.1/yr. H35 operates under CEO QUA-281 conditional exception (~8-9 entries/year). Minimum 100 trades threshold NOT MET — flagged for Engineering Director review.

## Files
- IS metrics: `backtests/h35_vrp_spy_is_2026-03-16.json`
- OOS metrics: `backtests/h35_vrp_spy_oos_2026-03-16.json`
- Full metrics: `backtests/H35_VRP_SPY_2026-03-16.json`
- Verdict: `backtests/H35_VRP_SPY_2026-03-16_verdict.txt`
