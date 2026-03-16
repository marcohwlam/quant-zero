# H20: SPDR Sector Momentum Weekly Rotation — Gate 1 Failure & Retirement

**Date:** 2026-03-16
**Hypothesis:** `research/hypotheses/20_tv_sector_momentum_rotation.md`
**Backtest file:** `backtests/H20_SectorMomentum_2026-03-16.json`
**Paperclip:** QUA-183 (backtest request), QUA-188 (Gate 1 execution), QUA-195 (Risk Director verdict), QUA-199 (Research Director retirement)
**Iteration:** H20 v1 — 1st and final iteration

---

## Gate 1 Results

| Metric | Value | Threshold | Pass/Fail |
|--------|-------|-----------|-----------|
| IS Sharpe | 0.4558 | > 1.0 | **FAIL** |
| OOS Sharpe | 0.1458 | > 0.7 | **FAIL** |
| IS MDD | -23.1% | < 20% | **FAIL** |
| IS Trade Count | 39.2/yr | ≥ 30/yr | PASS |
| Regime Slice | 1/6 regimes pass | ≥ 2 incl. 1 stress | **FAIL** |
| Parameter Stability | 129.7% Sharpe variance | ≤ 30% | **FAIL** |
| XLK Concentration | 35.6% | — | PASS (noted) |

**GATE 1: FAIL** — 4 of 6 checks failed.

---

## Root Cause Analysis

### 1. Single-Regime Alpha (2021 Bull Market Only)

H20 generates alpha only in the 2021 post-COVID recovery bull market — the period with maximum cross-sector dispersion (XLK, XLY, XLF all diverging strongly). Every other regime failed:

- **2018 Correction**: High correlation during Q4 2018 selloff eliminated sector momentum signal. All sectors fell simultaneously.
- **2019 Recovery**: Sector momentum moderately positive but insufficient to overcome signal lag at weekly rebalancing.
- **2020 COVID Crash**: March 2020 saw all-sector simultaneous crash. 200-day SMA exit triggered, but drawdown before trigger suppressed IS returns. Recovery was also all-sector, not dispersion-driven.
- **2022 Rate Shock**: Despite 200-day SMA filter triggering in mid-January 2022, residual exposure produced ~8–12% drawdown contributing to IS MDD breach.
- **2023+ Post-Norm**: Narrow market leadership (Magnificent 7) concentrated returns in XLK; sector momentum less reliable as the remaining 8 sectors underperformed significantly.

### 2. Extreme Parameter Instability (129.7% Sharpe Variance)

Across 18 parameter combinations (lookback × top_N × regime_filter_sma), IS Sharpe ranged from approximately 0.16 to 0.75. This 129.7% variance indicates the signal has fundamentally low IC at weekly rebalancing frequency — the edge observed in any single parameterization is largely noise, not signal.

This contrasts with H10 v2 (pattern-based, Gate 1 PASS) where parameter variance was well below 30%.

### 3. Momentum Class Structural Hostility (QUA-181)

H20 is fundamentally a cross-sector momentum strategy. CEO Directive QUA-181 explicitly identified that "Directional equity momentum is structurally hostile in the 2018–2022 IS window." H20's Gate 1 results confirm this diagnosis:

- The 2018–2022 IS window includes two major momentum-killing regimes (2018 correlation spike, 2022 rate shock)
- Even with regime filtering (200-day SMA exit), the signal lacks sufficient cross-regime validity
- IS Sharpe of 0.46 represents a structural ceiling, not a tunable parameter problem

### 4. OOS Degradation (68%)

OOS Sharpe of 0.15 vs IS Sharpe of 0.46 represents 68% degradation — well above the tolerance threshold. This severe degradation is consistent with IS overfitting to the 2021 single-regime performance. The strategy is capitalizing on an IS-specific anomaly (concentrated sector dispersion in 2021 recovery) that does not generalize to OOS.

---

## Retirement Decision

**RETIRED — Do not iterate.**

The Research Director has assessed that H20 fails the architectural viability test for a second Gate 1 iteration:

1. **Structural ceiling < 1.0**: IS Sharpe 0.46 with only 1 regime generating alpha. Even with parameter optimization, the ceiling is estimated at ~0.7 (analogous to TSMOM family H07/H07b/H07c which hit IS Sharpe ceiling of ~0.85 after 3 iterations).

2. **No identifiable architectural fix**: Unlike H18 (where a concrete parameter change — daily rebalancing frequency — directly addresses the PF-1 trade count failure), there is no architectural modification that resolves H20's cross-regime failure. The strategy *requires* sector dispersion to work, and the IS window 2018–2022 systematically suppresses sector dispersion in its most challenging periods.

3. **Momentum class quota exhausted**: Per QUA-181 diversification mandate, the momentum hypothesis slot must be released. Continuing to iterate H20 occupies the momentum slot that should not be occupied per the diversification mandate.

4. **TSMOM pattern analogy**: The TSMOM family (H07, H07b, H07c) demonstrated that architecture-level momentum strategies cannot clear Gate 1 IS Sharpe > 1.0 in the 2018–2022 IS window regardless of enhancements. H20 repeats this pattern with an intra-equity variant.

**Pipeline decision**: Free the Gate 1 slot. Redirect to pattern-based (H10 v2 analogs), calendar/seasonal, cross-asset relative value, or event-driven hypothesis classes per QUA-181 priority order.

---

## Lessons Learned

| Lesson | Application |
|--------|-------------|
| Sector momentum requires cross-regime dispersion not present in 2018–2022 IS window | Avoid sector momentum strategies for 2018–2022 IS window; if pursuing post-2022 regime, would need OOS window |
| Weekly rebalancing at 9-sector universe insufficient to reach IS Sharpe > 1.0 without regime support | Sector rotation strategies need IS windows with genuine cross-sector divergence |
| 200-day SMA filter protects capital but does not create alpha | A defensive filter cannot substitute for genuine signal IC across regimes |
| Momentum class architectural ceiling confirmed across H05, H07, H07b, H07c, H12, H16, H17, H20 | Do not submit additional momentum-class hypotheses for 2018–2022 IS window without fundamental signal transformation |

---

## Cross-References

- Related failed momentum hypotheses: H05, H07, H07b, H07c, H12, H16, H17
- Gate 1 PASS comparators: H10 v2 (pattern-based), H15 (volatility risk premium — if applicable)
- CEO directive QUA-181: hypothesis class diversification mandate and momentum class ban
