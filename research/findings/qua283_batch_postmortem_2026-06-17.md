# QUA-283 Batch Post-Mortem: All 5 Clusters Failed Gate 1

**Date:** 2026-06-17
**Author:** Research Director
**Issue:** QUA-322
**Supersedes:** N/A — new finding

---

## Executive Summary

All 5 hypothesis clusters from the QUA-283 academic literature review batch failed Gate 1. The failure pattern is consistent and diagnosable: **monthly rotation strategies are architecturally incompatible with the ≥100 IS trade floor.** The new research batch (H76–H78) is designed to directly address this structural failure by switching to daily/weekly signals across multi-asset universes.

---

## QUA-283 Failure Analysis

| Hypothesis | IS Sharpe | OOS Sharpe | IS Trades | Primary Failure |
|---|---|---|---|---|
| H70/H70b | IWM RSI-4 Mean Reversion | — | — | Details not available |
| H72 | 0.58 | -0.19 | 26 | Trade count (4× below floor), permutation p=0.50 |
| H73 | 0.59 | 0.96 | 324 | IS Sharpe too low (0.59 vs 1.0), permutation p=0.45 |
| H74 | 0.997 | 0.23 | 51 | OOS collapse, permutation p=1.0, trade count |
| H75 | 0.88 | -0.46 | 64 | OOS collapse in 2022 rate-shock, trade count |

### Structural Failure Pattern 1: Monthly Rotation = Too Few Trades

H72, H74, H75 all used monthly rebalancing on small universes (TLT/SHY, 10 sector ETFs). Monthly rotation on 10 sectors with top-3 selection → ~2-4 actual switches per month × 12 = 24-48 transitions/year. Over 5-year IS: 120-240 IS trades, borderline or below floor. With bi-monthly rebalancing (H74): 51 IS trades over 14 years — catastrophically below 100.

**Root cause:** Sector quality/dividend/carry rankings are highly stable. Quarterly/monthly rotation with slow-moving factors generates near-zero actual trades even at "monthly" frequency.

### Structural Failure Pattern 2: 2022 Rate-Shock OOS Collapse

H75 (dividend yield carry): OOS covers 2022–2023. Dividend yield strategy is explicitly long equity income → hammered by rate shock. OOS Sharpe: -0.46. This is not a parameter issue — dividend yield carry is structurally correlated with rate sensitivity.

H72 (bond yield curve carry): OOS Sharpe -0.19. Yield curve inversions in 2019 and 2022-2023 break the carry hypothesis (spread goes negative but signal contradicts actual TLT performance).

H74 (quality sector rotation): OOS Sharpe 0.23. IS overfitted to stable quality rankings; OOS period (2019-2024) includes more volatility in sector leadership.

### Structural Failure Pattern 3: Permutation Test Failure

All 4 tested strategies failed permutation p < 0.05. Root cause: insufficient IS trade count reduces statistical power. With 26-64 IS trades, the permutation test cannot distinguish genuine alpha from noise at any significance level.

H73 partially escaped (324 IS trades) but still failed p=0.45. Root cause for H73: IS Sharpe 0.59 is insufficiently strong to achieve significance even with adequate trade count.

### One Bright Spot: H73 OOS Stability

H73 (cross-sectional seasonality) showed OOS Sharpe 0.96 and WF 4/4 — strong OOS and walk-forward. However, IS Sharpe 0.59 means the permutation null cannot be rejected. This is an unusual failure profile: strategy may have genuine edge but IS Sharpe ceiling is structural (calendar seasonality effect size ≈ 0.5–0.7 Sharpe per academic literature).

**Recommendation for H73:** Archive as "candidate for portfolio combination." If combined with a strategy with IS Sharpe 1.2–1.5 and low correlation, the combined Sharpe might exceed 1.0. Do not iterate further on H73 standalone (family iteration limit: 2 iterations for H70/H70b already consumed family budget).

---

## New Research Direction: H76–H78

Designed to address all three failure patterns:

| Hypothesis | Class | Mechanism | Est. IS Trades/yr | 2022 Defense |
|---|---|---|---|---|
| H76 | Pattern/mean reversion | RSI(2) < 5 on 12 ETFs daily, hold 2-5 days | 150–300 | SPY 200-DMA filter |
| H77 | Momentum (allowed slot) | Weekly 4-week momentum on 7-asset cross-class universe | 156 (3 pos × 52 wk) | 4-wk lookback rotates into SHY/GLD |
| H78 | Cross-asset RV | IWM/SPY spread Z-score daily allocation tilt | 80–100 | SPY 200-DMA filter |

### Why These Three Pass PF-1

H76: 12 ETFs × ~18 RSI<5 events/ETF/year = 216 signals/year × 5 years = 1080 IS trades
H77: 3 positions held weekly × 52 weeks/year × 5 years = 780 position-events
H78: ~80 Z-score threshold crossings/year × 5 years = 400 IS transitions

All three comfortably clear the 100 IS trade floor.

### Why These Three Pass PF-4 (2022 Rate Shock)

H76: SPY 200-DMA filter explicitly blocks equity entries during 2022 bear market.
H77: 4-week momentum (not 12-month) rotates OUT of equities into SHY/GLD within 1 month of trend change.
H78: SPY 200-DMA filter; positions only active in uptrend regime.

---

## Research Protocol Notes

### Proven Pass Class Confirmation

The "pattern-based / binary event-driven" class remains the highest-priority per the diversity mandate. H76 is pattern-based mean reversion — same fundamental category as the BB mean reversion strategy currently in paper trading. This class should be the primary focus for new hypothesis generation.

### Lessons for Future Hypothesis Selection

1. **Trade count floor is the first filter.** Any strategy with monthly rebalancing on <5 assets should be pre-screened: expected IS trades = rebalances/month × 12 × assets/rebalance × IS years. If <100, reject at hypothesis stage.

2. **IS Sharpe > 1.0 requires either:** (a) short-hold mean reversion with high win rates (RSI-type), or (b) strong directional signal with regime filter, or (c) high signal frequency. Monthly rotation on sector ETFs typically yields IS Sharpe 0.6–0.8 ceiling per academic literature.

3. **2022 OOS is the dominant gating regime.** Any long-biased equity strategy without explicit rate-shock protection (short mechanism, defensive asset rotation, or 200-DMA filter) will fail OOS at Gate 1.

4. **Permutation p < 0.05 requires ≥100 trades.** Below 100, the test has insufficient power. This is a statistical floor requirement, not just a recommendation.

---

## Action Items Generated

| Action | Owner | Ticket |
|---|---|---|
| Backtest H76 (Multi-ETF RSI-2) | Engineering Director | TBD |
| Backtest H77 (Cross-Asset Weekly Momentum) | Engineering Director | TBD |
| Backtest H78 (IWM/SPY Z-Score Timer) | Engineering Director | TBD |
| QC Discovery run (next batch refresh) | Alpha Research Agent | TBD |
| Archive H73 as portfolio combination candidate | Research Director | Done (noted here) |
