# H55 Low Volatility Anomaly — Gate 1 Failure & Retirement

**Date:** 2026-06-09
**Research Director Decision:** RETIRE — do not submit for second Gate 1
**Source issue:** QUA-126 (backtest), QUA-131 (RD review)

---

## Gate 1 Results Summary

| Metric | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | 0.9039 | > 1.0 | FAIL |
| OOS Sharpe | 0.4868 | > 0.7 | FAIL |
| IS MDD | -20.86% | < 20% | FAIL |
| IS Trades | 383 | ≥ 100 | PASS |
| WF Consistency | 6/6 | ≥ 3/4 | PASS |
| Permutation p | 0.866 | ≤ 0.05 | FAIL |
| MC p5 Sharpe | 0.077 | > 0 | PASS |
| Bootstrap CI lower | 0.0128 | > 0 | PASS |

USMV parallel: IS Sharpe 0.944, OOS Sharpe 0.409.

---

## Failure Analysis

### 1. Permutation Test — Critical Failure (p = 0.866)

The permutation p-value of 0.866 is the decisive finding. This means 86.6% of randomly-shuffled return sequences performed as well as or better than the actual strategy. The signal pattern is statistically indistinguishable from noise.

This contradicts the WF 6/6 result on first read. The resolution: WF windows use a Sharpe floor of 0.3, which is achievable by strategies with low signal-to-noise. A strategy can post positive sub-0.5 Sharpe across all windows while the permutation test correctly identifies that its return sequencing is not systematic.

**The permutation failure alone is sufficient to retire H55.**

### 2. OOS Structural Failure — Rate Sensitivity (2022)

OOS Sharpe 0.487 is 31% below the 0.7 threshold — not a marginal gap. SPLV lost -12% in 2022 vs. SPY -20%, but monthly rotation still accumulated losses through the full drawdown. USMV OOS Sharpe 0.409 confirms this is not a SPLV-specific artifact.

Root cause: SPLV and USMV are dominated by utilities, consumer staples, and REITs — sectors with bond-like duration. In rate-shock regimes, these sectors reprice alongside long Treasuries. The bear gate (SHY trigger) fires only when SPY 12m absolute return goes negative, but SPLV can post large losses before SPY turns negative. In 2022, SPY turned negative quickly but the bulk of SPLV losses were accumulated before the gate fired.

**This is structural, not tunable.** No bear gate parameter adjustment can alter SPLV/USMV's sector composition.

### 3. PF-4 Retrospective Failure

H55 was forwarded to Gate 1 with a PF-4 "conditional pass" — the rationale was SPLV outperformed SPY (-12% vs -20%) in 2022. That framing was incorrect for our purposes: what matters is absolute return meeting Gate 1 Sharpe thresholds, not relative outperformance vs. benchmark. The OOS Sharpe of 0.487 in a rate-shock regime confirms the PF-4 conditional pass was too permissive.

**Lesson:** For future long-only equity factor ETFs with strong sector bias, PF-4 should require the strategy to post positive absolute returns (not merely outperform SPY) in 2022.

---

## Why Retirement (Not Refinement)

The Family Iteration Limit (max 2 Gate 1 iterations) permits one more iteration. However:

1. **No refinable parameter fixes the structural issue.** Bear gate ≤ -5% SPY threshold, variable lookback, or tighter stop-loss — none of these change SPLV's rate duration.
2. **A fundamentally different low-vol construct** (e.g., intraday volatility scoring, options-implied vol, or fundamental quality screens) would constitute a new hypothesis, not H55 refinement.
3. **Permutation test failure** indicates even the pattern captured in IS may not be systematic. Iterating further risks mining noise.

Spending a Gate 1 slot on a structural non-fix is wasteful given the pipeline.

---

## Validity of the Underlying Academic Signal

The WF 6/6 result and Bootstrap CI [0.013, 1.292] confirm the low-volatility anomaly IS real over the 1990–2021 IS window. The Blitz & van Vliet (2007) and Baker et al. (2011) papers are not invalidated.

The problem is **implementation** at monthly ETF rotation frequency with SPLV/USMV, given:
- Rate sensitivity of the ETF's sector composition
- Monthly rebalancing lag
- The 2022 rate-shock OOS period

---

## Future Exploration Paths (NOT commissioned — for reference)

If the pipeline is idle or the CEO requests low-vol exploration:

1. **Rate-hedged low-vol factor:** Long SPLV + short TLT (duration hedge). Requires short-selling capability — check broker constraints.
2. **Min-vol with quality filter:** Combine low-vol with profitability screen to avoid "cheap" rate-sensitive sectors. This is a multi-signal approach (2 signals: vol rank + ROE threshold).
3. **Sector-neutral min-vol:** Build low-vol proxy sector by sector to eliminate sector bias. Requires daily constituent data — likely PF-3 fail with current pipeline.

None of these paths are commissioned. Research Director recommends only reopening low-vol exploration if the pipeline has no higher-priority non-momentum hypotheses.

---

## H-Series Status

| Iteration | ID | IS Sharpe | Gate 1 |
|---|---|---|---|
| 1 | H55 | 0.904 | FAIL — RETIRED |

Family retired after iteration 1. Academic edge validated but ETF implementation structurally rate-sensitive. Do not forward further H55 variants.

---

*Research Director | QUA-131 | 2026-06-09*
