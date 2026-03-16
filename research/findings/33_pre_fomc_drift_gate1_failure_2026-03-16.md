# H33 Pre-FOMC Announcement Drift — Gate 1 FAIL + RETIREMENT

**Date:** 2026-03-16
**Hypothesis:** H33 Pre-FOMC Announcement Drift (SPY Long)
**Backtest task:** QUA-261
**Decision task:** QUA-276
**Decision:** RETIRE — do not rework

---

## Gate 1 Results

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| IS Sharpe (filtered) | 0.41 | > 1.0 | FAIL ❌ |
| IS Sharpe (unfiltered) | 0.41 | > 1.0 | FAIL ❌ |
| OOS Sharpe | 0.02 | > 0.7 | FAIL ❌ |
| IS MDD | -6.61% | < 20% | PASS ✅ |
| Win Rate | 48.74% | > 50% | FAIL ❌ |
| MC p5 Sharpe | -0.09 | ≥ 0.5 | FAIL ❌ |
| Permutation p-value | 0.130 | ≤ 0.05 | FAIL ❌ |

---

## Retirement Decision Rationale

**Decision: RETIRE.** The pre-FOMC drift has been arbitraged away and no viable rework path exists within our current data infrastructure.

### 1. Signal Decay — Fundamental, Not Parametric

The Lucca & Moench (2015) JF paper documented the pre-FOMC drift through 2011. The walk-forward analysis confirms clear temporal decay:

| WF Window | IS Period | IS Sharpe |
|-----------|-----------|-----------|
| 1 | 2007–2009 (GFC) | 1.12 |
| 2 | 2009–2012 | 0.28 |
| 3 | 2012–2015 | 0.04 |
| 4 | 2015–2018 | -0.12 |
| 5 | 2018–2021 | -0.23 |

IS performance is entirely dominated by the GFC period (2007–2010). Post-2012 IS Sharpe averages approximately zero or negative — clear evidence of arbitrage. This is not a parameter issue.

### 2. Statistical Insignificance

Permutation p-value = 0.130. We **cannot reject the null hypothesis of no alpha** at the 5% level. The IS Sharpe of 0.41 is not statistically distinguishable from random chance. Any rework would be curve-fitting a dead signal.

### 3. OOS Confirms Decay

OOS Sharpe = 0.02 over 2022–2025. The effect has zero predictive power in the most recent period. This is the strongest possible evidence of signal decay.

### 4. SHY Filter Provided No Value

The SHY (2-year Treasury) rate-hike filter triggered 0 times in the entire 2007–2021 IS period. The filter was designed to protect against rate-shock environments, but since it never activated in-sample, the filtered and unfiltered versions are identical. The filter design is valid theoretically but irrelevant empirically.

### 5. No Viable Rework Path

The natural rework options each have blocking issues:

| Rework Idea | Blocker |
|-------------|---------|
| Intraday entry (day-of-FOMC drift, first 30 min) | **PF-3 FAIL** — requires intraday data, not in current pipeline |
| Extend hold period (T-2 to T-1 entry) | Departs from the academic mechanism; no IC evidence at T-2 |
| Combine with momentum signal | Would need IC > 0.02 for base signal first — base signal fails at IC ≈ 0 post-2012 |
| Post-FOMC drift (hold for 3–5 days) | Structurally different hypothesis; no published academic backing for consistent direction |

Intraday modifications would be the most theoretically motivated rework (FOMC-day intraday drift is documented), but they fail PF-3 due to no intraday data in our current pipeline.

### 6. Family Iteration Limit Assessment

H33 is the **first iteration** of the FOMC event-driven family. We could launch H33b under the 2-iteration limit. However, with no IC evidence and no viable non-intraday rework, a second iteration would consume a Gate 1 slot without meaningful probability of improvement. This fails the spirit of the Family Iteration Limit directive (QUA-181).

---

## Learnings for Future Research

1. **Published arbitrage risk is real.** Lucca & Moench (2015) is a landmark JF paper — the pre-FOMC drift was known to academic and institutional traders from at least 2015. The decay timeline aligns with wide dissemination. High-quality academic papers with specific tradeable dates are high crowding-risk.

2. **Event-driven strategies with few trades/year require very long IS periods.** At 8 events/year, a 15-year IS window produces only 120 trades — barely adequate for statistical testing. WF windows with 4 trades each produce meaningless Sharpe estimates (OOS Sharpe Std = 1.60).

3. **GFC-period dominance is a red flag.** When walk-forward shows IS Sharpe steadily declining from 1.12 (GFC) to -0.23 (post-2018), the "IS Sharpe" is an artifact of one crisis period, not a robust signal.

4. **Intraday event-driven requires intraday data pipeline investment.** FOMC-day intraday drift may still be alive. File as a data infrastructure requirement: if the team ever acquires intraday data, revisit FOMC-day drift as H33-intraday.

---

## Status

- **H33 hypothesis status:** RETIRED
- **Replacement:** Not required — event-driven slot remains available for alternative event-driven hypothesis
- **Data infrastructure note:** FOMC-day intraday drift filed as deferred candidate pending intraday data pipeline

*Research Director | QUA-276 | 2026-03-16*
