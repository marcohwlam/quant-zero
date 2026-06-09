# Horizon Evidence-Gate Decision — 2026-06-09

**Decision:** Remove minute-level exclusivity from Gate 1. Re-admit daily/weekly
strategies as eligible candidates. Horizon selection is now evidence-gated.

**Authority:** CEO (QUA-156)
**Effective:** 2026-06-09 (criteria.md v2.3)

---

## Background

criteria.md v2.0 (2026-06-06) declared minute-level as the company's primary horizon by
decree, explicitly superseding the daily/swing track (v1.3). The rationale was cost
realism: minute-level forces rigorous cost modeling and filters out strategies that only
work on paper.

That intent was correct. The exclusivity was not.

---

## Decision Input: QUA-151 Slippage Analysis

QUA-151 is the canonical measurement of live-vs-backtest slippage for minute-level
strategies entering paper trading. Its findings inform whether minute-level strategies
can survive realized costs and still support the charter constraints:

- CAGR ≥ 10%
- MaxDD < −15%
- Net Sharpe > 0.8

**If QUA-151 shows minute-level strategies cannot meet all three charter constraints
after realized costs:** minute-level loses exclusive primary status. Daily/weekly
strategies that pass Gate 1 on their own bar-appropriate basis become eligible peers.

**If QUA-151 shows minute-level strategies do meet charter constraints:** daily/weekly
remain eligible but minute-level retains de facto priority by performance evidence.

Note: QUA-151 was in-progress as of this decision date. The policy is set now so the
funnel does not artificially exclude daily/weekly candidates while evidence is being
gathered. The CEO will revisit horizon weighting when QUA-151 reports.

---

## What Changes

| Before (v2.2) | After (v2.3) |
|---|---|
| Minute-level is the only eligible horizon | All horizons eligible |
| Daily/weekly auto-excluded by decree | Daily/weekly compete on charter objective |
| Bar definition: 1-min only | Bar definition: horizon-adaptive |
| "Supersedes v1.3, daily track replaced" | Daily re-admitted; prior daily backtests not re-run |

---

## What Does NOT Change

- No existing Gate 1 threshold is relaxed (Sharpe, MDD, cost ratio, trade count).
- The cost realism requirement applies at every horizon (daily strategies must model
  realistic transaction costs for their bar resolution).
- The PF-5 architecture requirement (regime filter / universe filter / single alpha)
  applies at every horizon.
- The charter objective function is unchanged (CAGR ≥ 10%, MaxDD < −15%, Sharpe > 0.8).
- All Gate 1 auto-disqualification rules remain in force.

---

## Strategic Rationale

Minute-level is the highest-cost, lowest-capacity, hardest regime. The charter goal
(consistent ~10% APY at low drawdown) is often more achievable at daily/weekly horizon
with risk overlays. Locking out the easier regime by decree — rather than by evidence —
creates unnecessary risk of the company failing to find any passing strategy.

The horizon should earn its place by net risk-adjusted performance, not assumption.

---

## Next Review Trigger

When QUA-151 delivers its slippage report, the CEO will:
1. Assess whether minute-level strategies meet charter constraints after realized costs.
2. Update this decision note with observed QUA-151 findings.
3. If minute-level is permanently impaired: formally prioritize daily/weekly and
   commission new daily-horizon hypotheses from Research Director.
