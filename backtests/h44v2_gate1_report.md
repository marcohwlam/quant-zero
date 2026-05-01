# H44v2 LQD/IEF Credit Risk Appetite Timer — Gate 1 Report

**Strategy:** H44v2_LQD_IEF_CreditRiskAppetimeTimer_TrailingStop
**Version:** H44v2 (trailing stop-loss redesign — [QUA-343](/QUA/issues/QUA-343))
**Parent escalation:** [QUA-342](/QUA/issues/QUA-342) — CEO ruling: redesign with trailing stop
**Run date:** 2026-05-01
**IS window:** 2007-01-01 → 2021-12-31
**OOS window:** 2022-01-01 → 2025-12-31
**Signal params:** lookback=20d, threshold=0.0%, smoothing=1d, riskoff=cash
**Stop-loss params:** trailing_stop=15%, re-entry margin=3%

## Overall Verdict: FAIL

## H44v2 vs H44 Gate 1 Comparison

| Metric | H44 Result | H44v2 Result | H44v2 Target | Status |
|--------|-----------|-------------|-------------|--------|
| IS Sharpe | 0.6822 | 0.7436 | >1.0 | FAIL |
| IS Max Drawdown | -35.53% | -29.21% | <20% | FAIL |
| OOS Sharpe | 0.7687 | 0.7687 | >0.7 | PASS |
| WF folds passed | 0/4 | 0/4 | ≥3/4 | FAIL |
| MC p5 Sharpe | 1.8274 | 2.1277 | ≥0.5 | PASS |

## Primary Metrics

| Metric | IS | OOS | Threshold | Pass? |
|--------|----|----|-----------|-------|
| Sharpe | 0.7436 | 0.7687 | IS>1.0, OOS>0.7 | IS:FAIL OOS:PASS |
| Max Drawdown | -29.21% | -14.22% | IS<20%, OOS<25% | IS:FAIL OOS:PASS |
| Total Return | 214.39% | 35.85% | — | — |
| Win Rate | 56.58% | 58.49% | >50% | PASS |
| Profit Factor | 2.41 | 1.81 | >1.0 | PASS |
| IS Regime Transitions | 303 | 105 | IS≥100 | PASS |
| Stop-Loss Exits (IS) | 2 | 0 | — | — |
| Trade Count (exits) | 152 | 53 | — | — |
| % Time in SPY | 55.16% | 56.89% | — | — |

## Statistical Validation

| Test | Result | Threshold | Pass? |
|------|--------|-----------|-------|
| DSR z-score | -29.2322 | >0 | FAIL |
| WF folds passed | 0/4 | ≥3 | FAIL |
| WF Sharpe std | 0.4252 | — | — |
| WF Sharpe min | 0.7641 | >0 | PASS |
| MC p5 Sharpe | 2.1277 | ≥0.5 | PASS |
| MC median Sharpe | 4.0991 | — | — |
| Sharpe 95% CI | [0.2733, 1.2427] | — | — |
| Permutation p-value | 0.0500 | ≤0.05 | PASS |
| Signal sensitivity max delta | 18.37% | <30% | PASS |
| Market impact | 0.02 bps | — | — |

## Walk-Forward Detail

| Fold | Train Period | OOS Period | IS Sharpe | OOS Sharpe | Stop Exits OOS | Pass? |
|------|-------------|-----------|-----------|------------|----------------|-------|
| 1 | 2007-01-01→2009-12-31 | 2010-01-01→2012-12-31 | 0.1431 | 0.7641 | 0 | False |
| 2 | 2007-01-01→2012-12-31 | 2013-01-01→2015-12-31 | 0.3869 | 0.9398 | 0 | False |
| 3 | 2007-01-01→2015-12-31 | 2016-01-01→2018-12-31 | N/A | N/A | ? | False |
| 4 | 2007-01-01→2018-12-31 | 2019-01-01→2021-12-31 | 0.5052 | 1.7410 | 0 | False |

## Trailing Stop Sensitivity

| Trailing Stop | IS Sharpe | IS MDD | Stop Exits | Transitions | % in SPY |
|--------------|-----------|--------|-----------|-------------|----------|
| 12% (tight) | 0.7645 | -30.62% | 2 | 309 | 54.77% |
| 15% (base case) | 0.7436 | -29.21% | 2 | 303 | 55.16% |
| 18% (loose) | 0.7115 | -33.30% | 1 | 309 | 55.27% |

## Signal Parameter Sensitivity Sweep

| Lookback | Threshold | Smoothing | IS Sharpe | IS MDD | Stop Exits |
|----------|-----------|-----------|-----------|--------|------------|
| 20d | 0.0000 | 1d | 0.7436 | -29.21% | 2 |
| 16d | 0.0000 | 1d | 0.6761 | -30.98% | 1 |
| 24d | 0.0000 | 1d | 0.6070 | -28.91% | 1 |
| 20d | 0.0005 | 1d | 0.7507 | -29.20% | 2 |
| 20d | -0.0005 | 1d | 0.7002 | -29.18% | 2 |

## GFC 2008-2009 Exit Analysis

- First cash date (GFC window): **2008-07-01**
- Cash days (Sep–Oct 2008): **41**
- Stop-loss exits in GFC period: **2**
- Exit timing: **PASS: before Oct 2008**
- GFC period MDD: **-29.21%**
- GFC period total return: **3.02%**

## 2022 OOS Monthly Regime Analysis (Rate-Shock Year)

- 2022 MDD: **-14.22%** ✅ within threshold
- 2022 Total Return: **-10.48%**
- 2022 Stop-loss exits: **0**
- 2022 % time in SPY: **46.22%**

| Month | Regime | SPY % | Monthly Return |
|-------|--------|-------|----------------|
| 2022-01 | CASH | 30.00% | -3.89% |
| 2022-02 | CASH | 0.00% | 0.00% |
| 2022-03 | CASH | 43.48% | 3.06% |
| 2022-04 | CASH | 50.00% | -3.60% |
| 2022-05 | CASH | 9.52% | 1.99% |
| 2022-06 | SPY | 71.43% | -7.62% |
| 2022-07 | CASH | 35.00% | 4.60% |
| 2022-08 | SPY | 91.30% | -1.09% |
| 2022-09 | CASH | 9.52% | -2.28% |
| 2022-10 | CASH | 19.05% | 1.26% |
| 2022-11 | SPY | 95.24% | 5.67% |
| 2022-12 | SPY | 90.48% | -6.20% |

## Sub-Period Sharpe Decomposition (IS)

| Period | Sharpe | MDD | Win Rate | Transitions | Stop Exits | Total Return |
|--------|--------|-----|----------|-------------|------------|--------------|
| 2007–2012 (GFC + Recovery) | 0.3869 | -29.21% | 50.00% | 119 | 2 | 30.47% |
| 2013–2018 (Bull + Taper) | 0.7127 | -10.07% | 57.38% | 122 | 0 | 34.25% |
| 2019–2021 (Pre/Post COVID) | 1.7410 | -8.69% | 65.62% | 63 | 0 | 71.94% |

## Gate 1 Checklist

- ❌ IS Sharpe > 1.0
- ✅ OOS Sharpe > 0.7
- ❌ IS MDD < 20%
- ✅ OOS MDD < 25%
- ✅ IS Transitions ≥ 100
- ❌ DSR > 0
- ❌ WF folds passed ≥ 3
- ✅ MC p5 Sharpe ≥ 0.5
- ✅ Perm test pass
- ✅ Sensitivity pass
- ✅ Win Rate > 50%
- ✅ GFC exit before Oct 2008

## OOS Data Quality

- Recommendation: **PASS**
- Coverage: **100.0%**
- NaN critical metrics: []

---
*Generated by Engineering Director | [QUA-343](/QUA/issues/QUA-343) | 2026-05-01*