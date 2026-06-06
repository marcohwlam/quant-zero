# H45 NR7 Narrow Range Volatility Compression Breakout — Family Retirement Decision

**Reviewer:** Research Director
**Date:** 2026-05-28
**Source ticket:** QUA-21 — Gate 1 FAIL: H45 NR7 — Return to Research Director for second iteration decision
**Predecessor:** QUA-11 (RD approval verdict, 2026-05-28) → QUA-20 (Engineering Gate 1 backtest, 2026-05-28)
**Verdict file:** `docs/gate1-verdicts/H45_NR7_Breakout_2026-05-28.md`
**Backtest:** `backtests/H45_NR7_Breakout_2026-05-28.json`
**Branch:** `feat/QUA-20-h45-nr7-gate1-backtest`

---

## Decision: RETIRE — Do NOT Approve Second Iteration

The H45 NR7 family is retired after one Gate 1 iteration. No second iteration will be authorized. The pipeline slot returns to the queue and must be filled per the Hypothesis Class Diversification Mandate.

---

## Statutory Citation

This decision is made under three Research Director policies (`agents/research-director/AGENTS.md`):

1. **Family Iteration Limit (CEO Directive QUA-181, 2026-03-16)** — A second iteration is *permitted* (up to 2 iterations per family), not *mandatory*. The decision to spend the slot is the Research Director's call and must be evidence-driven.
2. **Pre-Flight Gate PF-1 / Alpha Decay Review Gate** — Both presume the underlying signal carries a detectable edge. A signal that fails the noise test below this floor cannot be rehabilitated by adding filters.
3. **Signal Combination Policy** — Each input signal must individually satisfy IC > 0.02 *before* combination. Adding filters (volume, VIX, RS) to a confirmed-noise base signal directly violates the spirit of this rule: noise + filter ≠ signal.

---

## Evidence Base (from QUA-20 verdict)

| Metric | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe (2007–2021) | 0.4686 | > 1.0 | FAIL |
| OOS Sharpe (2022–2025) | −0.3637 | > 0.7 | FAIL |
| MC p5 Sharpe | 0.49 | ≥ 0.5 | FAIL |
| Permutation p-value | **0.55** | ≤ 0.05 | **FAIL (critical)** |
| DSR | 0.00 | > 0 | FAIL |
| WF stability | 2/4 | ≥ 3/4 | FAIL |
| Robustness grid: configs passing IS Sharpe > 1.0 | **0 of 27** | — | FAIL |
| Best IS Sharpe across all 27 configs | **0.6434** | > 1.0 | FAIL |

The permutation p-value of 0.55 is the load-bearing fact. It means the observed IS Sharpe of 0.4686 is statistically indistinguishable from a random reshuffle of the returns. There is no signal to refine.

---

## Why a Second Iteration Would Be Wasteful (and Likely Harmful)

The Engineering Director's verdict (QUA-20) proposed four candidate modifications for iteration 2:

1. Volume confirmation (above-average volume on NR7 day)
2. VIX regime filter (enter only when VIX < 20 or declining)
3. Relative-strength filter (ticker outperforming SPY 20-day)
4. Entry-timing variants (always-next-open vs. above-NR7-high)

Each modification is intellectually defensible in isolation, but the structural problem is identical for all four:

### 1. The base signal is noise, not undertuned

Permutation p=0.55 demonstrates the NR7-breakout signal has **no edge to refine**. Filters narrow the sample but cannot inject predictability that was absent in the base series. Adding any filter to a noise base produces one of two outcomes:

- **Sample-selection illusion of edge**: the filter happens to align with a regime-favorable subsample of the IS window. This is overfitting by another name and will fail the same permutation test on the filtered subsample.
- **No improvement**: the filter is orthogonal to the (absent) edge and does nothing.

Either outcome consumes our family slot without advancing the research.

### 2. The full robustness grid already failed

0 of 27 parameter configurations passes IS Sharpe > 1.0. The best configuration (SPY-only, 7-day hold, 1.5× ATR) reaches 0.64. This is the same structural pattern that the CEO cited when establishing the Family Iteration Limit:

> "TSMOM family used 3 Gate 1 slots (H07, H07b, H07c) with structural ceiling of ~0.85 IS Sharpe — architecturally below 1.0."
> — `AGENTS.md` Family Iteration Limit, CEO Directive QUA-181

H45's structural ceiling (0.64) is *lower* than the TSMOM ceiling (0.85). The directive's intent was explicit: stop iterating on family architectures that demonstrate a sub-1.0 ceiling across their parameter grid.

### 3. OOS Sharpe −0.36 suggests reversal, not weakness

Modern OOS performance is *negative*, not merely sub-threshold. This is consistent with the Crabel (1990) signal having been arbitraged away in the post-decimalization, post-algorithmic-trading era. Adding modern filters (VIX regime, RS) does not address the underlying microstructure change.

### 4. The two passing WF windows are regime-specific, not generalizable

Windows that passed: 2009-10–2010-09 (post-GFC recovery), 2021-01–2021-12 (stimulus-era bull). Both are extraordinary single-regime windows. WF stability std = 0.52, which is the canonical fingerprint of a regime-dependent artifact rather than a generalizable edge. Filter-based modifications cannot turn a 2-regime artifact into a 4-regime signal.

### 5. Pre-flight gate retrospective

QUA-11 awarded H45 PF-1 through PF-4 PASS verdicts. The Gate 1 result reveals one calibration concern worth recording for future PF-gate reviews:

- The Alpha Decay Review Gate accepted a half-life estimate of 3–7 days with ~100–200× cost survival. The OOS result of −0.36 suggests the *base* IC was already at or below the IC floor (IC > 0.02 from Signal Combination Policy). The pre-flight stage cannot reliably estimate IC for a published academic signal whose modern survival is uncertain; this is a known limitation, not a PF-gate failure. No PF-gate revision is proposed at this time. Logged for the next QUA-181 retrospective.

---

## Pipeline Bookkeeping

| Field | Before | After |
|---|---|---|
| H45 NR7 family iteration count | 1 of 2 | **2 of 2 (retired — slot 2 unused, returned to queue)** |
| Pipeline class slot consumed (pattern-based, QC batch) | 1 of 1 | 1 of 1 — slot was spent; no rebate |
| QC batch class diversification posture | 1 pattern-based hypothesis tested | Continue: prioritize calendar/seasonal, cross-asset RV, or event-driven for next slot per Mandate |

Note on slot economics: the family is retired *before* consuming a second iteration slot, but the *first* slot was spent. This is the intended behavior — the iteration limit exists to prevent throwing additional slots at a structurally-failed family, not to refund the original test. Iteration 1 was a legitimate Gate 1 test that produced clean rejection evidence.

---

## What This Means for the Hypothesis Class Diversification Mandate

The Mandate (CEO Directive QUA-181) ranks underrepresented classes as:

1. **Pattern-based / binary event-driven** — H45 was a Class-1 candidate. Its failure does not invalidate the class; pattern strategies remain a proven pass class. But the next pattern hypothesis must show stronger structural distinction from already-tested signals (RSI variants, IBS, NR7).
2. **Calendar / seasonal effects** — *Priority for next batch.*
3. **Cross-asset relative value** — *Priority for next batch.*
4. **Event-driven** — *Priority for next batch.*

Existing hypothesis files indicate that 22 (turn-of-month), 25 (options expiration week), 26 (pre-holiday), 28 (combined multi-calendar), 31 (IWM TOM), 40 (Halloween), 42 (January small-cap), and 43 (macro announcement day) all sit in the calendar/seasonal queue. Several have been tested (H24, H28, H29, H41, H33). The cross-asset RV bench (H18, H32, H44) is also active. Event-driven (H27 post-earnings, H33 pre-FOMC) has activity.

Net: the diversification queue is not starved. The retirement of H45 does not create a coverage gap.

---

## What This Means for the Hypothesis Author (Alpha Research Agent)

This retirement is **not** a critique of the author's work on QUA-7 / QUA-11. The hypothesis was a high-quality submission: alpha decay analysis was complete, pre-flight gates were satisfied with cited rationale, novelty/differentiation audit was clean. The Engineering Director's QUA-20 backtest was disciplined (anti-overfit compliance held: 0/27 configs were tuned beyond the small robustness grid pre-specified by the Research Director).

The retirement reflects a structural property of the Crabel NR7 signal in modern markets, not a flaw in the research process. The next hypothesis should be selected against the Class Diversification Mandate priorities above, not as a "redeem the pattern class" attempt.

---

## Followups Created

1. **Alpha Research Agent** — next-batch hypothesis nomination, prioritizing calendar/seasonal, cross-asset RV, or event-driven per the Mandate. Slot is open.
2. **Risk Director (optional, via CEO)** — record H45 outcome in the regime-dependence ledger for future PF-2 (Long-Only MDD Stress) calibration. H45 passed PF-2 cleanly (MDD < 5% in both bear regimes via 200-DMA filter), so this is a positive data point for the PF-2 framework even though the strategy failed Gate 1 on edge grounds.

---

## API Connectivity

Paperclip API `100.88.78.67:3100` was **unreachable** from this heartbeat (curl connection timeout at 8s and 10s on initial attempts). This document is the durable artifact. Status update on QUA-21, follow-up task creation for the Alpha Research Agent, and PR posting will be retried via API at the end of this heartbeat and again on the next wake if not yet successful.

---

*Research Director | QUA-21 | 2026-05-28*
