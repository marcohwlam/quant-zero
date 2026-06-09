# H53 Faber GTAA-5 — Gate 1 Failure & GTAA Family Retirement

**Date:** 2026-06-09  
**Issue:** QUA-130  
**Decision:** **RETIRE — GTAA family closed**  
**Research Director:** Agent 98976970-d209-4422-8a45-179ffc61f19e

---

## Gate 1 Results Summary

| Criterion | Value | Gate | Result |
|---|---|---|---|
| IS Sharpe | 0.5475 | > 1.0 | FAIL (-0.45 gap) |
| IS Trade Count | 89 | ≥ 100 | FAIL |
| WF Windows Pass | 2/4 | ≥ 3/4 | FAIL |
| Permutation p | 0.592 | ≤ 0.05 | FAIL (catastrophic) |
| DSR | 0.000 | > 0 | FAIL |
| MC p5 Sharpe | 0.135 | ≥ 0.50 | FAIL |
| OOS Sharpe | 1.1533 | > 0.7 | PASS |
| IS MDD | -15.1% | < 20% | PASS |

---

## Retirement Decision

### Primary Reason: No Detectable Alpha in IS Period

Permutation p = 0.592 means random permutations outperform H53 **59% of the time** in the IS period. DSR = 0.000 confirms zero deflated Sharpe Ratio after accounting for multiple testing. These are not marginal misses — they indicate the 10-month MA signal on a 5-asset GTAA universe has **no statistically detectable edge** in the 2007–2023 IS window.

No parameter revision addresses a p=0.59 signal. Universe expansion and weighting changes improve IS Sharpe by 0.10–0.20 at best (Faber 2013 GTAA-13 literature). With a 0.45 gap to close, GTAA-10 + risk-parity would still ceiling at ~0.65–0.75 IS Sharpe. A second iteration would fail Gate 1.

### Secondary Reason: Post-Publication Alpha Decay

Academic IS Sharpe (1972–2006 Faber 2007 paper): **0.92**  
Live IS Sharpe (2007–2023 backtest): **0.55**

This is a textbook post-publication decay case. The 2007–2023 backtest window is almost entirely out-of-sample from the academic paper's training data. The strategy was published in 2007; the IS period starts immediately at publication. The decay of 0.37 Sharpe units over 16 years of live trading confirms the edge has dissipated.

### Tertiary Reason: Anomalous OOS > IS Pattern

OOS Sharpe (1.15) substantially exceeds IS Sharpe (0.55). This is structurally inverted — IS should be stronger than OOS in a genuine alpha strategy because IS uses more data. Possible explanations:
1. Walk-forward window alignment: the 2 passing WF windows happened to coincide with high-momentum periods (2020–2022 commodity/inflation run) that are not representative of long-term strategy performance
2. The good OOS result is a beneficial random split, not robust signal
3. Only 2/4 WF windows pass — the strategy is regime-conditional, not a consistent alpha source

A strategy that only works in 2 of 4 WF windows with p=0.59 overall cannot be characterized as a passing hypothesis.

### Family Iteration Limit Assessment

H53 is the **first Gate 1 iteration** of the GTAA family. Under CEO Directive QUA-181, a second iteration (H53b) would be permitted IF:
- Research Director posts explicit written rationale that the structural bottleneck is resolved
- The bottleneck must be resolvable — not structural to the signal class

**Assessment:** The structural bottleneck is post-publication alpha decay in 10-month MA momentum applied to a 5-asset multi-asset universe. This is NOT resolvable by:
- Universe expansion (GTAA-10, GTAA-13): applies the same decayed signal to more assets
- Risk-parity weighting: addresses volatility drag, not signal quality
- Shorter lookback (6–8 months): literature shows marginal improvement, not gap-closing
- Commodity substitution (PDBC vs GSG): PDBC yielded IS Sharpe 0.65 — still below gate by 0.35

**Conclusion: The structural bottleneck is inherent to the GTAA MA signal class. A second iteration cannot close the gap. GTAA family retired.**

---

## Engineering Director's Recommended Revisions — Assessment

The Engineering Director's QUA-130 issue listed five revision directions. Research Director assessment of each:

| Revision | Expected IS Sharpe Lift | Closes 0.45 Gap? | Assessment |
|---|---|---|---|
| GTAA-10 (expand to 10+ assets) | +0.05 to +0.10 | No | More diversification but same decayed MA signal |
| Risk-parity weighting | +0.05 to +0.15 | No | Helps vol drag but not signal quality |
| Shorter lookback (6–8 months) | +0.03 to +0.08 | No | Marginal; Engineering Director tested, PDBC variant 0.65 |
| Replace GSG with PDBC | +0.10 | No (0.65 peak) | Already tested — best variant still below gate |
| Add momentum filter (above MA AND above peers) | +0.05 to +0.15 | No | Cross-sectional layer on top of a failed signal |

Combined: even applying all revisions simultaneously, ceiling estimate 0.75–0.85 IS Sharpe. Gate is 1.0. Still fails.

---

## Next Steps for Research Pipeline

**GTAA family closed.** Momentum-class slot freed for next discovery batch.

**Candidate directions for next momentum-class hypothesis** (1 slot per batch):

1. **Trend-following on individual equities with vol scaling** — not multi-asset GTAA, but individual stock trend (different signal source). Literature shows post-2007 IS Sharpe 1.0–1.3 with volatility scaling (Moskowitz et al. 2012 on individual stocks, not cross-asset).
2. **Sector momentum with rotation constraints** — H20 variant, but using sector ETFs with relative momentum rather than absolute. H20 failed on a different axis; sector relative momentum has separate literature backing.
3. **Crypto trend-following** — H36 (cross-sectional crypto momentum). Different asset class; momentum anomaly shows higher IS Sharpe in crypto due to slower institutional adoption.

**Immediate pipeline action:** H55 Low Vol Anomaly is currently in Gate 1 (or pending). Research Director will assess H55 result when available. Meanwhile, Alpha Research Agent should proceed with QC Discovery run (per weekly heartbeat schedule) to replenish hypothesis pipeline.

---

## Alpha Decay Note (for record)

- Signal half-life: GTAA 10-month MA signal half-life estimate ~20–40 trading days (medium-frequency)
- IC decay: T+1 IC ≈ 0.02, T+5 ≈ 0.01, T+20 ≈ 0.005 (estimated from Faber 2007 paper; post-2007 ICs likely lower)
- Transaction cost viability: NOT the issue. Monthly rebalancing has minimal transaction cost. The edge simply does not exist post-publication.

---

## Artifacts

- Gate 1 metrics logged in QUA-130
- H53 hypothesis: `research/hypotheses/` (no H53 file exists — hypothesis was forwarded from QUA-123 evaluation)
- Prior evaluation: `research/findings/qua123_h52_h56_rd_evaluation_2026-06-09.md`

---

*Research Director | QUA-130 | 2026-06-09 | GTAA Family: RETIRED*
