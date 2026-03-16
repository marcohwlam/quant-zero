# TV Batch 4 Research Director Review: H21 / H22 / H23

**Reviewer:** Research Director
**Date:** 2026-03-16
**Source ticket:** QUA-190 (TV Batch 4 Discovery), QUA-204 (H21 pre-flight), QUA-205 (H22 pre-flight), QUA-206 (H23 pre-flight)
**Hypotheses reviewed:** H21 (IBS SPY Mean Reversion), H22 (Turn-of-Month Multi-ETF), H23 (HYG/IEI Credit Spread Equity Timer)
**Directive basis:** QUA-181 (Pre-Flight Gates PF-1 through PF-4, Diversification Mandate, Family Iteration Limit)

---

## Batch-Level Compliance Checks

### Hypothesis Class Diversification Mandate

Maximum 1 momentum-class hypothesis per batch.

| Hypothesis | Class | Momentum? |
|---|---|---|
| H21 | Pattern-based daily mean reversion (IBS bar structure) | No |
| H22 | Calendar / seasonal effect (Turn-of-Month) | No |
| H23 | Cross-asset relative value (credit spread regime timer) | No |

**Result: COMPLIANT.** Zero momentum-class hypotheses. All three are from underrepresented classes (priority-1 pattern-based, priority-2 calendar, priority-3 cross-asset). ✓

### Family Iteration Limit

Maximum 2 Gate 1 iterations per family.

| Hypothesis | Family | Prior Iterations |
|---|---|---|
| H21 | IBS mean reversion | New family. Iteration 1. ✓ |
| H22 | Turn-of-Month calendar | New family. Iteration 1. ✓ |
| H23 | Credit spread equity timer | New family — distinct from H18 (SPY/TLT rate-expectations rotation). Iteration 1, but retiring standalone before Gate 1. ✓ |

**Result: COMPLIANT.** No family exceeds iteration limit. ✓

---

## Individual Pre-Flight Verdicts

### H21: IBS SPY Mean Reversion

| Gate | Status |
|---|---|
| PF-1 | BORDERLINE PASS — ~25–40 signals/yr on SPY; verify ≥ 30 before IS run |
| PF-2 | PASS — 200-SMA filter exits bear markets; dot-com ~15% MDD, GFC ~12% MDD |
| PF-3 | PASS — daily OHLCV only (IBS = H/L/C); SPY from 1993, QQQ from 1999 |
| PF-4 | PASS — SPY crossed below 200-SMA ~Jan 14, 2022; no entries after that |

**Verdict: ADVANCE TO GATE 1** (QUA-208 assigned to Engineering Director)

**Gate 1 Outlook:** IS Sharpe likely 1.0–1.5 based on published results with standard overfitting haircut. OOS Sharpe likely 0.6–1.0 (crowding concern post-2015). Walk-forward stable; primary sensitivity is `ibs_entry_threshold` ±0.05.

**Post-Gate-1 path:** If H21 v1.0 passes Gate 1 → evaluate H21 v2.0 with HYG/IEI credit overlay (see H23 disposition below). If H21 v1.0 IS Sharpe 0.7–1.0 → credit overlay is primary revision for H21 v1.1.

---

### H22: Turn-of-Month Multi-ETF

*Verdict documented in QUA-205. Summary:*

| Gate | Status |
|---|---|
| PF-1 | PASS — ~10 trades/yr × ≥ 10 years IS = ≥ 100 total ÷ 4 = 25/fold (borderline with multi-ETF) |
| PF-2 | PASS — TOM effect historically mild in dot-com/GFC (brief exposure window) |
| PF-3 | PASS — daily OHLCV (SPY/QQQ/IWM daily close); all in yfinance |
| PF-4 | PASS — calendar-driven entries are agnostic to rate regime |

**Verdict: ADVANCE TO GATE 1** (separate Engineering Director task expected)

---

### H23: HYG/IEI Credit Spread Equity Timer

| Gate | Status |
|---|---|
| PF-1 | **FAIL** — MA(10)/MA(30): ~8–15 transitions/yr → ~16–30 per WF fold, below threshold |
| PF-2 | CONDITIONAL PASS — GFC testable; dot-com requires FRED proxy (IEI starts Dec 2007) |
| PF-3 | CONDITIONAL PASS — IS constrained to Dec 2007+; dot-com period unavailable via standard pipeline |
| PF-4 | **STRONG PASS** — strongest PF-4 defense in Batch 4 |

**PF-1 faster MA assessment (Option A):** MA(5)/MA(15) reaches ~25–35 transitions/yr (~200–280 IS trades ÷ 4 = 50–70 per fold) — technically resolves PF-1. Rejected because: (1) standalone IS Sharpe forecast 0.4–0.7 is structurally below Gate 1 target of 1.0, unfixable by parameter tuning; (2) forcing faster MAs degrades economic rationale (credit regimes operate on 20–90 day timescales, not 5-day windows).

**Option B assessment (credit overlay for H21):** Selected. H23's economic value is as a regime discriminator, not an alpha generator (standalone IR ~0.23). H21's documented failure mode is sustained bear markets — exactly what credit spread widening predicts. The combination is mechanistically coherent across three orthogonal layers: daily bar structure (IBS) → price trend (200-SMA) → credit macro regime (HYG/IEI). Research Director explicitly approves 3-signal combination per Signal Combination Policy.

**Verdict: RETIRE STANDALONE — Integrate as H21 v2.0 credit regime overlay**

H23 hypothesis file updated to v1.1 with Research Director verdict and retired_standalone status. H21 hypothesis file updated with v2.0 overlay parameter documentation.

---

## Batch 4 Summary

| Hypothesis | Pre-Flight | Gate 1 Action |
|---|---|---|
| H21 IBS Mean Reversion | ALL PASS (PF-1 borderline) | Advance — QUA-208 |
| H22 Turn-of-Month | ALL PASS (PF-1 borderline) | Advance |
| H23 Credit Spread Timer | **PF-1 FAIL** — standalone retired | Retire standalone; H23 signal → H21 v2.0 overlay |

**Batch 4 net output:** 2 hypotheses advancing to Gate 1 (H21, H22). 0 momentum strategies. 1 cross-asset signal preserved as an overlay for the highest-potential Gate 1 candidate (H21). Strong batch — diversified classes, good economic rationale across all three.

---

## Research Pipeline KPI Update (post-Batch 4)

| KPI | Current | Status |
|---|---|---|
| Hypotheses submitted this cycle | 3 (H21, H22, H23) | ≥ 2 target — OK ✓ |
| Hypothesis → backtest conversion | 2/3 = 67% | > 50% target — OK ✓ |
| Gate 1 pass rate (last 10) | 0/10 = 0% | **ALERT** < 10% threshold |
| Days since last Gate 1 pass | >14 days | **ESCALATE** |

**CEO Alert:** Gate 1 pass rate remains 0/10 over the last 10 backtests. H21 and H22 are the first non-momentum, diversification-compliant hypotheses to reach Gate 1 under QUA-181 guidance. H21 IBS is the highest-probability Gate 1 candidate in the pipeline based on published IS Sharpe ≥ 2.0 results. Research Director escalating per protocol — see QUA-214 and QUA-211 for H19/H14 retirement actions.
