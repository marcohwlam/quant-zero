# TQQQ Trend-Gated Satellite (QQQ 200SMA, weekly RSI, exit-rule variants)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-11-09
**Asset class:** equities
**Strategy type:** single-signal
**Status:** retired (fails PF-2 and PF-4 at intake; filed retroactively for QUA-907)

## Economic Rationale

The scripts `scripts/backtest_tqqq_{weekly_rsi,exit_rules,fixed_yield,bond_rotation}.py` were written as QUA-889 follow-ups on 2026-11-06 and had no hypothesis file. They extend the H09 TQQQ line (`09_tv_tqqq_weekly_snapback.md`, Gate 1 FAIL 2026-03-16). The idea is to hold TQQQ only while QQQ is above its 200-day SMA, and to test what the off-state holds (cash, fixed yield, BIL/SHY/IEF/TLT), plus weekly RSI entry rules and trailing stops. The mechanism is trend persistence of Nasdaq-100 beta with a leverage multiplier; the 3x daily reset adds volatility decay in chop.

## Entry/Exit Logic

**Entry signal:** QQQ close > 200SMA (or weekly RSI > 50 / 55 variants), applied from the next bar.
**Exit signal:** gate off, or trailing stop 25-35% from peak in the exit-rule variants.
**Holding period:** Position (weeks to months)

## Exploratory Results (2010-02 to 2026-11, 10 bps per side, rf=0)

| Variant | Full Sharpe | IS (to 2019) | OOS | Full MDD |
|---|---|---|---|---|
| TQQQ buy and hold | 0.848 | n/a | n/a | -81.7% |
| QQQ 200SMA gate, cash | 0.764 | 0.723 | 0.828 | -56.6% |
| Gate + 6% fixed yield off-state | 0.789 | 0.752 | 0.849 | -55.8% |
| Gate + IEF off-state | 0.762 | 0.740 | 0.806 | -57.8% |
| Weekly RSI>50 in / <45 out | 0.753 | 0.791 | 0.726 | -66.2% |

No variant reaches IS Sharpe 1.0, and none beats buy and hold on Sharpe. The gate cuts MDD but it stays far above 40%.

## Pre-Flight Gate Checklist

- PF-1 Trade viability: marginal. 30 to 46 trades in 16 years gives roughly 8 to 12 IS trades per WF fold, below 30. FAIL.
- PF-2 Long-only MDD stress (synthetic 3x QQQ daily, 0.95% annual expense drag, yfinance QQQ from 1999): FAIL.
  - Ungated: 2000-02 MDD -99.9%, 2008-09 MDD -92.5%.
  - With QQQ 200SMA gate (10 bps cost): 2000-02 MDD -93.0%, 2008-09 MDD -51.7%. Threshold is < 40% in both.
  - Caveat: synthetic 3x ignores financing and tracking error. Direction is not in doubt.
- PF-3 Data: PASS (yfinance daily).
- PF-4 Rate-shock: FAIL. Long-only, no short or hedge. In 2022 the gate variants lost -42% to -44% (CAGR) with MDD -45%; ungated synthetic 3x lost -78%. Bond off-states did not help because bonds fell in 2022. No a priori rationale exists for a positive 2022 return.
- PF-5 Architecture: single alpha plus regime filter, PASS.

## Family Iteration Limit

Family: TQQQ/leveraged-Nasdaq timing. Gate 1 iterations on record: H09 (FAIL, 2026-03-16). H63/H64 are ORB strategies on leveraged ETFs, a different mechanism, so they are not counted. The four 2026-11-06 scripts are exploratory, not Gate 1 runs, so they consume 0 slots. Count: 1 of 2. A Gate 1 submission of this family would be iteration 2 and the last allowed, and it cannot pass PF-2 or PF-4 as designed.

## Alpha Decay

- **Signal half-life (days):** > 20 (trend gate, 200-day lookback)
- **Edge erosion rate:** slow
- **Cost survival:** yes at 10 bps, roughly 3 round trips per year
- **Notes:** Pre-cost IR about 0.76, above the 0.3 warning level. The failure is drawdown, not signal-to-noise.

## Capital and PDT Compatibility

No PDT impact (swing/position). Any account size.

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely (best 0.79)
- Walk-forward stability: unlikely, trade counts too low
- Sensitivity risk: medium
- Known overfitting risks: four scripts and about 25 variants tried on one 16-year window dominated by the 2010-2021 Nasdaq bull market

## Disposition

Retired. QUA-903 already committed the scripts, JSON results and `backtests/tqqq_exploratory_2026-11-06_verdict.txt` (RETIRE) on branch `feat/QUA-903-tqqq-triage`; this file adds the PF-2/PF-4 and family-count record. No Gate 1 submission.

## References

- `research/hypotheses/09_tv_tqqq_weekly_snapback.md`
- `backtests/tqqq_{weekly_rsi,exit_rules,fixed_yield,bond_rotation}_2026-11-06.json`
- `agents/research-director/AGENTS.md` (Pre-Flight Hard Gates, Family Iteration Limit)
