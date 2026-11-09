# H88, H89, H90 QC Drafts Retired (QUA-906)

**Date:** 2026-11-09
**Author:** Alpha Research Agent
**Method:** Event-count and next-day-return check on yfinance daily adjusted bars, 2000-2024, no costs, no tuning. Script: `research/findings/qua906_h88_h89_h90_event_check.py`. This is a pre-flight check, not a Gate 1 backtest.

## H88 Oops Gap Reversal (8 ETFs): retired

- The draft estimated ~12 qualifying events per ETF per year. Real data gives 482 events over 25 years across 8 ETFs, or ~2.4 per ETF per year. The PF-1 estimate was overstated about 5x. In-sample 2000-2019 has 372 events (~93 per fold), which still clears PF-1.
- Next-day Close-to-Close return after signal: mean -3.8 bp, t = -0.69 (pooled). Date-level (events on the same date averaged): t = -0.18 over 251 dates.
- Result: no detectable edge on the daily-bar proxy. The mechanism in the draft requires an intraday stop entry at the prior Low, which daily bars cannot replicate.

## H89 Buyback Blackout Window (SPY): retired

- PF-1 failed as specified (~4 trades per year). The 6-ETF remedy does not add independent samples because the ETFs are highly correlated.
- Direct test of the premise: SPY daily return inside the open window (about Feb 5 to Mar 15, May 5 to Jun 15, Aug 5 to Sep 15, Nov 5 to Dec 15) annualizes to 5.6% (Sharpe 0.30). Outside the window it annualizes to 12.3% (Sharpe 0.62). The sign is opposite to the hypothesis. The SMA(200) filter was not applied in this check, and the window dates are the draft's calendar approximations.
- Result: the calendar effect is not present in 2000-2024 SPY data.

## H90 Turnaround Tuesday Multi-ETF: retired

- Pooled events: 846 (681 in 2000-2019), mean next-day return +17.6 bp, t = 4.57. That t-statistic is inflated because the six ETFs qualify on the same Mondays.
- Distinct signal dates: 298 (~12 per year), matching the draft's own warning. Date-level mean +8.9 bp, t = 1.29.
- The draft's cost-survival rule requires >~8 bp net per trade after ~2 bp round-trip cost. Gross 8.9 bp gives ~7 bp net before slippage, below the stated bar, and t = 1.29 is not significant.
- Result: effective independent sample is too small and the edge does not clear the draft's own cost test.

## Disposition

All three set to `retired`. No Gate 1 backtest requested. A reopen needs a new mechanism or an intraday-resolution test, not a parameter change.
