# H94 Stage 2 VCP Stop-Defined: Retired (QUA-831)

**Decision date:** 2026-10-26
**Decision owner:** Research Director
**Status:** Retired at Step 1. No Gate 1 iteration consumed.

## Evidence (research/scripts/h94_step1_precheck.py, IS 2017-06 to 2021-12, H93 PIT universe, 1047 tickers)

- PF-1 failed: 1 realized trade under both the spec (2 contractions, ratio 0.6) and the documented fallback (ratio 0.7). Requirement: at least 120 trades. The hypothesis estimate of 75-150 raw triggers per year was wrong by more than 100x.
- IC failed: S1 (RS126) T+5 +0.0005, T+20 -0.0044; S2 (52-week-high proximity) T+5 -0.0103, T+20 -0.0183; S3 fallback (20d-high breakout with volume) T+5 -0.0070, T+20 -0.0087. All below the 0.02 floor and at or below zero.
- PF-2 passed, but only because the regime gate keeps the proxy mostly in cash.

## Why retire instead of redesign

1. The contraction-chain rule is the binding constraint. Loosening the swing definition beyond the one documented fallback is parameter fitting on a single cycle.
2. The S1/S2 IC result is a hypothesis-level failure, not an S3 implementation problem. Dropping to a 20d-high breakout does not recover it.
3. The usable IS window is one cycle (effective signals from 2018-06). A standard error of about 0.007 on IC cannot separate a real edge from noise at this sample size.

## Lessons

- Trade-count estimates in hypothesis files must be backed by an empirical signal count on the PIT universe before Engineering sees the hypothesis. PF-1 should be measured, not asserted.
- Pattern-recognition setups with chained geometric conditions (VCP) need a precise, codifiable definition at hypothesis time. "Simplified VCP" left the definition to the implementer.
- Track A momentum hypotheses on 2018-2021 inherit the same hostile regime noted in the diversification mandate. Prefer hypotheses that can be tested on a longer window.
