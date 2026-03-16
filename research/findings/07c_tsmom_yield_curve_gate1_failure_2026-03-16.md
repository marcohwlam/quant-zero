# H07c: Multi-Asset TSMOM Yield-Curve-Aware — Gate 1 Failure Analysis

**Date:** 2026-03-16
**Hypothesis:** `research/hypotheses/07c_multi_asset_tsmom_yield_curve.md`
**Verdict file:** `backtests/H07c_MultiAsset_TSMOM_YieldCurve_2026-03-16_verdict.txt`
**Paperclip:** QUA-169 (backtest execution), QUA-166 (revision proposal), QUA-167 (coordination)
**Iteration:** H07 v3 — 4th TSMOM variant evaluated

---

## Gate 1 Results

| Metric | Value | Threshold | Pass/Fail |
|--------|-------|-----------|-----------|
| IS Sharpe | 0.848 | > 1.0 | **FAIL** |
| OOS Sharpe | 0.753 | > 0.7 | **PASS** |
| IS MDD | 5.84% | < 20% | PASS |
| OOS MDD | 4.5% | < 25% | PASS |
| IS Win Rate | 61.4% | > 50% | PASS |
| IS Trade Count | 88 | ≥ 100 | **FAIL** |
| WF Windows Passed | 0/4 | ≥ 3 | **FAIL** |
| Permutation p | 0.97 | ≤ 0.05 | **FAIL** |
| Parameter Sensitivity | 26.3% | < 30% | PASS |
| Regime-slice (2/4 N/A) | Incomplete | 3/4 regimes | **FAIL** |

**GATE 1: FAIL** — 6 criteria failed.

---

## Root Cause Analysis

### 1. Yield Curve Filter Created Regime Blindness

The yield curve threshold filter (`TNX - IRX < yield_curve_threshold`) blocked:
- 7.6% of IS entries (28/370)
- 17.9% of OOS entries (19/106)

During the 2022 rate shock regime, the inverted yield curve blocked virtually all entries — resulting in `N/A` for the regime-slice sub-criterion in both `rate_shock_2022` and `normalization_2023`. This paradox means the filter designed to protect the strategy from rate-shock regime actually prevented sufficient trading to demonstrate statistical significance in those regimes.

### 2. WF Structural Incompatibility (0/4 windows)

The walk-forward windows (12m lookback, 6m OOS) were architecturally incompatible with the 15-ETF universe and yield curve parameter — insufficient trades in any single 6-month OOS window to achieve significance. H07b and H07c both suffer from this: TSMOM with monthly rebalancing simply doesn't generate enough trades at the window granularity required for walk-forward validation.

### 3. IS Sharpe Shortfall: Structural, Not Incidental

IS Sharpe trajectory across H07 family:
- H07 (original 7-ETF): IS Sharpe ~0.7
- H07b (15-ETF + VIX gate): IS Sharpe ~0.8
- H07c (15-ETF + VIX + yield curve): IS Sharpe 0.848

Improvement at each iteration is real (+0.1/iteration) but the delta is diminishing. Extrapolating, H07d would be unlikely to reach 1.0 without a fundamentally different signal. The 2022 rate shock is the structural IS-window killer — TSMOM reversal in 2022 cannot be filtered away at monthly rebalancing frequency.

### 4. Permutation Test: No Statistical Alpha (p=0.97)

Permutation p = 0.97 indicates the observed IS Sharpe of 0.85 is consistent with random chance. Despite reasonable realized metrics, the statistical test rejects the hypothesis that IS performance is above chance.

---

## Regime Slice Analysis

| Regime | Period | Sharpe | Pass |
|--------|--------|--------|------|
| pre_covid_2018_2019 | 2018–2019 | 1.257 | ✅ |
| stimulus_2020_2021 | 2020–2021 | 0.885 | ✅ |
| rate_shock_2022 | 2022 | N/A (blocked) | ❌ |
| normalization_2023 | 2023 | N/A (blocked) | ❌ |

The yield curve filter intended to skip the 2022 regime instead made the strategy unable to generate statistical evidence in that regime. A filter that creates unmeasured exposure is worse than one that trades through drawdown — at least the latter generates measurable IS data.

---

## Decision: RETIRE H07 TSMOM Family

**Research Director decision: The H07 Multi-Asset TSMOM family is permanently retired from Phase 1 Gate 1 evaluation.**

Rationale:
- 4 iterations evaluated (H07, H07b, H07c, and the original H07 baseline)
- IS Sharpe ceiling appears to be ~0.85 at monthly rebalancing with this universe
- Each refinement adds marginal lift but no iteration can overcome the structural 2022 rate shock period
- WF structural incompatibility is unfixable without moving to weekly rebalancing (which increases transaction costs)
- Permutation test confirms no statistical alpha exists in the IS window

**Re-activation conditions:**
- Capital ≥ $100K (allows weekly rebalancing with lower position-size impact)
- IS window revised to exclude 2022 or add explicit hold-out treatment for rate-shock regime
- Alternative universe construction (international TSMOM, sector TSMOM) with >30 assets

---

## Lessons for Research Pipeline

1. **Monthly-rebalancing TSMOM is IS-window-fragile at $25K**: The 2022 rate shock is a non-diversifiable risk in the 2018–2023 IS window. Strategies with monthly rebalancing lack the reactivity to exit before the reversal propagates. Prefer daily-bar strategies or regime-conditional monthly strategies.

2. **Yield curve filters that blank entire regimes are architectural failures**: A filter that produces N/A in a regime sub-criterion is effectively hiding risk, not managing it. Future hypotheses with regime filters must guarantee sufficient trade count in ALL required IS regime slices.

3. **WF validation requires trade count floor per window**: Before commissioning backtest, Alpha Research should verify that IS trade count ÷ 4 ≥ 30 trades per WF window. H07c had 88 total IS trades — ~22/window, below the significance threshold.

---

## H07 Family Gate 1 Summary

| Version | IS Sharpe | Result | Primary Failure |
|---------|-----------|--------|-----------------|
| H07 (7-ETF) | ~0.70 | FAIL | IS Sharpe < 1.0 |
| H07b (15-ETF + VIX gate) | ~0.80 | FAIL | IS Sharpe < 1.0, WF 0/4 |
| H07c (+ yield curve filter) | 0.848 | FAIL | IS Sharpe < 1.0, WF 0/4, permutation p=0.97 |

**All three failed the same structural bottleneck: IS window 2022 rate shock + insufficient trade count for WF.**

---

*Research Director — 2026-03-16 | QUA-104 (heartbeat) / QUA-169 (backtest)*
