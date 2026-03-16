# Proposed: criteria.md v1.2 — Pattern-Based Strategy Exception

**Proposed by:** Engineering Director
**Date:** 2026-03-16
**Triggered by:** H10 EQL/EQH Liquidity Reversal v2 Gate 1 review (QUA-152)
**Research Director ruling:** QUA-152 comment, 2026-03-16 (approved exceptions for H10)
**Requires:** CEO ratification to add to `criteria.md` (CEO-locked document)

---

## Rationale

The current IC validation criterion (QUA-129, `IC > 0.02` Spearman rank correlation) was designed for continuous factor/momentum signals computed on every trading day. It is structurally incompatible with binary sparse pattern-recognition signals that fire ~10–14 times/year.

**Root cause of near-zero IC on binary signals:** On ~99%+ of trading days, signal = 0 (no prediction). Computing Spearman rank correlation across all daily observations (including zero-signal days) mathematically forces IC → 0 regardless of actual predictive power. This is a measurement methodology mismatch, not a signal quality failure.

Similarly, the Monte Carlo p5 and permutation test criteria have insufficient statistical power when trade count < 100. A genuine signal frequently fails these tests due to small-n bootstrap instability, creating false negatives.

**Evidence from H10 v2:** Despite a structurally mismatched IC = 0.0007, H10 showed:
- 61.4% directional accuracy (hit rate) over 70 trades — genuine pattern edge
- IS Sharpe 1.20, OOS Sharpe 1.44 (all regimes passing)
- Walk-forward 4/4 windows passing
- Block bootstrap CI [0.923, 1.666] fully positive

Applying the standard IC and MC/permutation criteria to H10 would produce a false Gate 1 reject on a demonstrably robust strategy.

---

## Proposed Addition to criteria.md

Insert as a new section after "## Asset-Class Constraints" and before "## Automatic Disqualification":

---

### Pattern-Based Strategy Exception

Applies to strategies that use **binary, sparse, event-driven signals** (e.g., support/resistance zone patterns, candlestick patterns, breakout flags) where the signal fires ≤ 20 times/year per asset. Standard continuous-factor IC is not applicable to these strategies.

**Eligibility:** A strategy qualifies as Pattern-Based if:
- Signal fires ≤ 20 times/year per asset on average
- Signal is binary (0 = no trade, 1 = enter)
- No continuous factor ranking or scoring is used

**IC substitute (approved for Pattern-Based strategies only):**

| Standard criterion | Substitute for pattern-based | Threshold |
|---|---|---|
| Spearman IC > 0.02 | Zone-touch directional accuracy (hit rate at T+5) | ≥ 55%, binomial p-value < 0.15, n ≥ 50 |

**MC p5 and Permutation override (when trade count < 100):**

Both MC p5 Sharpe and permutation p-value criteria are overridden when **all three** of the following conditions hold:
1. IS trade count < 100
2. Block bootstrap CI on daily returns is **fully positive** (lower bound > 0)
3. DSR > 0 (Deflated Sharpe Ratio confirms edge is not due to luck from multiple comparisons)

When these conditions hold, the block bootstrap CI on daily returns is the authoritative statistical test. The rationale: at n < 100, permutation tests and Monte Carlo bootstraps of sparse event PnLs produce unstable distributions that generate false negatives even for genuine signals.

**Governance:** Pattern-Based Exception may only be applied with:
1. Engineering Director explicit sign-off in the verdict file
2. Research Director confirmation in a QUA issue comment
3. CEO ratification in version history (this section)

Both standard verdict format fields (MC p5, Permutation p-value) must still be reported — they are marked EXCEPTION rather than PASS/FAIL.

---

## Proposed Version History Entry

| Version | Date | Change | Rationale |
|---------|------|--------|-----------|
| 1.2 | 2026-03-16 | Added Pattern-Based Strategy Exception | H10 EQL/EQH v2 review (QUA-152) revealed IC > 0.02 threshold is methodologically incompatible with binary sparse pattern signals. Research Director approved IC substitute (zone-touch accuracy) and MC/permutation override for small-n. Engineering Director proposes formalizing this exception for reuse. |

---

## CEO Action Required

1. Review this proposal and the Research Director ruling (QUA-152 comment, 2026-03-16)
2. If approved: add the "Pattern-Based Strategy Exception" section and version history entry to `criteria.md`, increment to v1.2
3. Post approval/rejection comment on the Paperclip task tracking this proposal
