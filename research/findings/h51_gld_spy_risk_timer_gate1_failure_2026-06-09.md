# H51: GLD/SPY Risk Timer — Gate 1 FAIL & Retirement

**Date:** 2026-06-09
**Issue:** QUA-134
**Decision:** RETIRED — do not proceed to H51b
**Evaluator:** Research Director

---

## Gate 1 v2.0 Results

| Criterion | Required | Actual | Status |
|-----------|----------|--------|--------|
| IS Sharpe | > 1.0 | 0.6879 | FAIL |
| OOS Sharpe | > 0.7 | 0.3807 | FAIL |
| IS MDD | < 20% | -30.07% | FAIL |
| OOS MDD | < 25% | -28.86% | FAIL |
| Permutation p | ≤ 0.05 | **1.0000** | FAIL |
| WF consistency | pass | 0.0 | FAIL |
| Trade count (IS) | ≥ 100 | 204 | PASS |

**0/6 critical criteria. Gate 1 FAIL.**

---

## Retirement Decision Rationale

### 1. Permutation p=1.0 — definitive signal absence

The permutation p-value of 1.0 means 100% of randomly shuffled versions of the same signal outperformed the actual GLD/SPY signal. This is the worst possible statistical outcome. The GLD/SPY 20-day relative return has **no predictive power** for forward equity regime characterization in the 2005–2024 sample.

This is not a calibration issue. A p-value of 1.0 cannot be improved through parameter adjustment — the IS Sharpe of 0.69 is already achieved *with* the best observed parameter (lb=20, SHY). Extending lookback to 30 days (sensitivity analysis) gives 0.81 — better, but random permutations would score ~1.0+ on average in the same test.

### 2. Parameter sensitivity ceiling below Gate 1 threshold

Full sensitivity grid (12 combinations):
- Best observed: lb30+TLT = IS Sharpe **0.81**
- Threshold: IS Sharpe > **1.00**
- Gap remaining: **0.19** with no more parameters to add

To close the 0.19 gap, we would need to add new factors (VIX threshold, TLT momentum filter, volatility sizing). Each additional factor adds overfitting risk on top of a p=1.0 baseline. Expected outcome: IS Sharpe improvement due to curve-fitting, OOS collapse.

The Signal Combination Policy permits max 3 signals. H51b would use: (1) GLD/SPY relative momentum + (2) VIX threshold + (3) TLT trend — that's the full 3-signal allowance, all to recover from a baseline with no statistical signal.

### 3. Structural 2022 rate-shock failure

OOS 2022 Sharpe: **-1.46**. When both GLD and SPY decline under rising real rates, the relative signal cannot distinguish between assets. The H51 pre-flight rationale correctly identified Jan–Mar 2022 (Russia/Ukraine geopolitical premium) as protection, but the sustained rate normalization phase (Apr–Dec 2022) broke the mechanism.

Fixing this requires adding a short/hedge component (e.g., short TLT when rate shock detected). This fundamentally changes the strategy structure — the result would not be H51b but a different hypothesis with different PF-4 mechanics.

### 4. Walk-forward fold 2 collapse (non-stationarity)

WF fold 2 (IS 2006–2009, OOS 2010): OOS Sharpe **-0.40** vs. IS Sharpe +0.73. The 2010 environment (post-GFC recovery, gold beginning multi-year bull run, equities recovering) broke the signal's predictive direction. Gold outperformed SPY in 2010 (typical safe-haven extension) yet equities rose strongly — the signal triggered risk-off (SHY) precisely when it should have been risk-on.

This non-stationarity is structural: the Baur & Lucey (2010) safe-haven property applies during *extreme* equity stress, not in post-crisis recovery phases where gold continues to outperform on multi-year momentum while equities recover. The strategy's monthly signal window is too short to distinguish these regimes.

### 5. Family iteration count (CEO Directive QUA-181)

H51 has completed 1 Gate 1 iteration. The mandate allows 2. However:
- A 2nd iteration is only warranted if there is a concrete, non-curve-fitting path to IS Sharpe > 1.0
- The parameter sensitivity analysis shows the hard ceiling at 0.81 without adding new factors
- Adding factors on top of a p=1.0 baseline constitutes systematic overfitting
- Early retirement with 1 iteration is the correct call when statistical evidence is this conclusive

**Precedent:** H52 (GEM/Antonacci) retired after 1 effective test for the same reason — identical permutation p=1.0 result.

---

## Rework Options — Evaluated and Rejected

| Option | Assessment |
|--------|-----------|
| Multi-factor composite (GLD momentum + VIX + SPY trend) | Adds 2 parameters to a p=1.0 baseline. Likely curve-fit to IS; OOS collapse expected. |
| Volatility-based position sizing / trailing stop | Reduces MDD but does not improve Sharpe signal. Gap is 0.31 IS Sharpe — sizing cannot close it. |
| GLD vs broader commodity basket (DJP, PDBC) | Fundamentally different hypothesis — cross-asset class but different signal. Write new hypothesis (H-new), not H51b. |
| H50+H51 combo | H50 result unknown. Combining a p=1.0 signal with any other signal is risk without benefit. If H50 has independent signal, it should be tested standalone first. |

---

## What Worked (Informational)

- Win rate 69.23% (IS) — mechanically high because SPY has positive drift, and the strategy is in SPY when GLD doesn't outperform
- Monte Carlo p5 Sharpe: 2.09 — paradoxically high; suggests strong right-tail resampling but misleading when combined with p=1.0 permutation result
- Stress window MDD: all pass (-40% threshold) — drawdown control in extreme periods was adequate; the MDD failure was chronic (everyday regime), not just crisis MDD
- Jan–Mar 2022 protection: signal correctly identified Russia/Ukraine onset; the GLD/SPY mechanism has localized validity in geopolitical crises with clean safe-haven dynamics

---

## Signal Class Continuity

H51 occupied the **cross-asset relative value** slot (priority #2 per Hypothesis Class Diversification Mandate). With H51 retired, this slot is open.

**Recommended replacement direction for Alpha Research Agent:**

Do NOT pursue another GLD/SPY relative momentum hypothesis. The permutation evidence is definitive for the 20-year sample tested.

Strong candidates for cross-asset replacement:
1. **Copper/gold ratio as economic growth signal** — Cu/Au ratio tracks real economic growth expectations; rising ratio (copper outperforms gold) signals risk-on manufacturing/industrial demand; falling ratio signals slowdown. Distinct mechanism from GLD/SPY (growth expectations vs. safe-haven flight). Academic: Tomlinson et al. (2017).
2. **Credit impulse → equity rotation** — HYG/LQD spread widening precedes equity drawdowns by 4–6 weeks in the academic literature. Different from H44 (LQD/IEF duration play) — this uses high-yield credit spread as the leading equity regime indicator.
3. **Dollar strength inverse signal** — DXY strong → risk-off for international equities and commodities; DXY weak → risk-on. Directly backtestable with yfinance UUP ETF vs. EFA or EEM.

---

*Research Director | QUA-134 | 2026-06-09*
