# H47 FOMC Bi-Weekly Cycle — Retirement Finding

**Date:** 2026-06-11
**Verdict:** GATE 1 FAIL → RETIRED
**Backtest:** `backtests/h47_fomc_biweekly_cycle_2026-06-11.json`
**Issue:** QUA-200 (backtest), QUA-210 (retirement assessment)

---

## Failure Summary

7 of 10 Gate 1 checks failed.

| Metric | Result | Threshold | Status |
|--------|--------|-----------|--------|
| IS Sharpe | 0.54 | > 1.0 | FAIL |
| OOS Sharpe | 0.59 | > 0.7 | FAIL |
| IS MDD | -27.87% | < 20% | FAIL |
| IS CAGR | 4.78% | ≥ 10% | FAIL |
| Win Rate | 59.12% | > 50% | PASS |
| Trade Count | 1001 | ≥ 100 | PASS |
| WF Windows | 3/4 | ≥ 3 | PASS |
| Permutation p | 1.00 | < 0.05 | FAIL |
| Sensitivity | False | < 30% var | FAIL |
| MC p5 Sharpe | 0.17 | ≥ 0.5 | FAIL |

---

## Core Signal Analysis

**The Cieslak bi-weekly differential does not exist in the data:**

- Even weeks avg return: 0.194%
- Odd weeks avg return: 0.213%
- t-stat: -0.144 (p = 0.886)

Odd weeks marginally outperformed even weeks — the opposite of the Cieslak hypothesis. No statistical significance. Signal absent.

---

## Post-2019 Anomaly Assessment

Backtest reported: Pre-2019 even-week Sharpe = 0.255 vs Post-2019 even-week Sharpe = 1.503.

**Assessment: NOT recoverable alpha.**

The post-2019 "high Sharpe" is COVID-era market beta (2020-2021 bull market). Any long-equity strategy with >50% market exposure had elevated Sharpe during 2020-2021. The 180-observation sample post-2019 includes the COVID recovery and does not constitute evidence of FOMC cycle alpha. A "post-2019 regime filter" would be pure data mining with no economic basis — it cannot explain WHY the mechanism activated in 2019 rather than it being a spurious segmentation.

**The permutation p-value of 1.00 is determinative.** Zero statistical edge over random over a 21-year IS window.

---

## H47v2 Decision: REJECTED

No revised hypothesis warranted. Reasons:

1. Core signal (even vs odd differential) absent — not a parameter problem
2. Permutation p=1.00 leaves no room for improvement via parameter search
3. Post-2019 "anomaly" is market beta, not FOMC cycle alpha
4. 200-DMA overlay helps (MDD from -45% to -28%) but cannot compensate for absent underlying signal
5. Cieslak effect likely arbitraged away post-2019 publication — the OOS period (2019-2026) is exactly the post-publication window the hypothesis warned about

---

## FOMC Cycle Line of Inquiry: CLOSED

- H33 (Pre-FOMC Day Drift, Lucca-Moench 2015): Retired — low frequency, signal decay post-2012
- H47 (Cieslak Bi-Weekly Cycle, 2019): Retired — signal absent in data, post-publication decay confirmed

Both major academic FOMC timing effects have been tested and failed. No remaining FOMC cycle variants worth pursuing under current evidence base.

---

*Research Director | QUA-210 | 2026-06-11*
