# H14: OU Mean Reversion Cloud — Gate 1 Failure Analysis

**Date:** 2026-03-16
**Hypothesis:** `research/hypotheses/14_tv_ou_mean_reversion_cloud.md`
**Verdict file:** `backtests/H14_OUMeanReversion_2026-03-16.json`
**Paperclip:** QUA-162 (backtest), QUA-171 (execution)

---

## Gate 1 Results

| Metric | Value | Threshold | Pass/Fail |
|--------|-------|-----------|-----------|
| IS Sharpe | 0.903 | > 1.0 | **FAIL** |
| OOS Sharpe | -0.009 | > 0.7 | **FAIL** |
| IS MDD | 1.57% | < 20% | PASS |
| OOS MDD | 0.59% | < 25% | PASS |
| IS Win Rate | 56.9% | > 50% | PASS |
| IS Trade Count | 160 | ≥ 100 | PASS |
| WF Windows | 3/4 | ≥ 3 | PASS |
| IC (avg) | 0.111 | > 0.02 | PASS |
| DSR | 7.3e-5 | > 0 | **FAIL** (borderline) |
| Sensitivity | ~72% deviation | < 30% | **FAIL** |
| Permutation p | 0.544 | ≤ 0.05 | **FAIL** |

**GATE 1: FAIL** — 4 criteria failed, including critical IS Sharpe and catastrophic OOS collapse.

---

## Root Cause Analysis

### 1. Severe OOS Degradation (IS 0.903 → OOS -0.009)

The near-zero OOS Sharpe (-0.009) despite an IS Sharpe of 0.903 is the definitive indicator of **overfitting to the IS regime**. The OU model parameters (mean-reversion speed, Ornstein-Uhlenbeck band thresholds) were optimized for the 2018–2021 low-volatility/trending equity regime. In the 2022–2023 OOS period:
- Elevated rates destroyed the correlation structure the OU model relied on
- OOU cloud parameters (kappa, theta, sigma) calibrated on IS data became stale
- OOS returns were flat despite 84 OOS trades

### 2. Permutation p = 0.544 (No Statistical Alpha)

The permutation test confirms: the observed IS performance is indistinguishable from random shuffling of returns. The IC of 0.111 appears promising in isolation, but when tested against permuted data, the signal strength is not reproducible. This suggests the IC metric is capturing in-sample noise, not a genuine predictive relationship.

### 3. Parameter Sensitivity: 72% Deviation

The Ornstein-Uhlenbeck parameters are highly sensitive. A ±20% perturbation of the entry threshold produces 72% Sharpe degradation (threshold: < 30%). This confirms the IS performance is parameter-dependent and unlikely to generalize.

### 4. DSR Near Zero

Despite reasonable WF (3/4) and IC metrics, the Deflated Sharpe Ratio approaches zero — after adjusting for the number of trials in the OU parameter search, the effective alpha is negligible.

---

## Decision: RETIRE H14 OU Mean Reversion Cloud

**Research Director decision: H14 is retired.** The OOS collapse is a disqualifying red flag independent of the IS Sharpe shortfall.

**Re-activation conditions:**
- True intraday OU calibration with rolling parameter updates (not static IS calibration)
- Alternative asset class (FX pairs, futures spreads) where OU dynamics are more stable
- Dynamic re-calibration: OU parameters must be re-estimated at each trading decision, not fitted once to IS data

---

## Lessons

1. **Static OU calibration is regime-fragile**: OU parameters estimated on 2018–2021 data fail in 2022 rate shock because the covariance structure breaks. Future OU-based strategies must use rolling parameter estimation (re-estimate daily or weekly).
2. **High IC + low DSR = multiple testing artifact**: IC of 0.111 looks convincing but DSR of ~0 indicates it was selected from a parameter search — not a genuinely robust signal.
3. **WF 3/4 pass can coexist with OOS collapse**: Walk-forward validates IS sub-window stability, but does not guarantee OOS regime generalization. The WF test and the OOS test are complementary, not redundant.

---

*Research Director — 2026-03-16 | QUA-104 (heartbeat)*
