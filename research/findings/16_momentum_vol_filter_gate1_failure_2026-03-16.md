# H16 Gate 1 Failure Analysis: Momentum + Volatility Effect (Long-Only)

**Date:** 2026-03-16
**Hypothesis file:** `research/hypotheses/16_qc_momentum_reversal_volatility.md`
**Gate 1 ticket:** QUA-165
**Backtest ticket:** QUA-174
**Result:** ❌ GATE 1 FAIL → **ABANDONED**

---

## Gate 1 Metrics

| Metric | Value | Threshold | Pass? |
|--------|-------|-----------|-------|
| IS Sharpe | 0.38 | > 1.0 | ❌ FAIL |
| OOS Sharpe | 0.57 | > 0.7 | ❌ FAIL |
| IS MDD | **-74.2%** | < 20% | ❌ FAIL |
| IS Win Rate | 54.3% | > 50% | ✅ PASS |
| IS Trade Count | 744 | ≥ 100 | ✅ PASS |
| WF Windows | 2/4 | ≥ 3 | ❌ FAIL |
| Permutation p | 1.0 | ≤ 0.05 | ❌ FAIL |
| DSR | 0.0 | > 0 | ❌ FAIL |
| Sensitivity variance | 99.8% | ≤ 30% | ❌ FAIL |
| Regime-slice | 2/9 | ≥ 2 IS incl. stress | ❌ FAIL |
| MC p5 Sharpe | 0.11 | > 0.5 | ❌ FAIL |

**Failed criteria: 9 of 13**

---

## Root Cause Analysis

### 1. Structural: Long-Only + High-Vol Selection = Crash Concentration

The core mechanism of H16 is a two-step sort:
1. Filter to top-20% realized volatility stocks (6-month lookback)
2. Go long the top momentum quintile (Q5) within that group

**The critical error:** High realized volatility stocks are disproportionately exposed to systemic crash events. The vol filter intentionally concentrates the portfolio in the most crash-prone names. In a long-only structure, this creates:

- Amplified drawdowns in every bear/crash regime
- No short leg to offset the crash exposure
- -74.2% IS MDD — driven by 2000-2002 dot-com collapse, 2008-2009 GFC

### 2. Academic Paper Mismatch: Long-Short → Long-Only

Cao & Han (2016) is a **long-short** academic paper. The market-neutral structure is essential to their documented edge:
- Long high-vol/high-momentum stocks (crash-prone)
- Short low-vol/low-momentum stocks (defensive)
- Net exposure: near-zero market beta

The long-only restriction (approved due to $25K capital + PDT constraints) removes the market-neutral protection. The resulting strategy captures the upside of high-vol momentum but fully absorbs the crash downside.

### 3. Permutation p=1.0: No Statistical Alpha

The permutation test (p=1.0) confirms that the strategy's IS performance is **indistinguishable from random chance** over the full IS period. This is not a near-miss — it is a categorical absence of alpha.

### 4. Sensitivity 99.8%: No Robust Parameter Region

Parameter sweep (formation period: 3m/6m/9m × vol filter: 15%/20%/25%) showed 99.8% Sharpe variance. No stable region exists. The strategy is not tunable — even the "best" parameter set has minimal Sharpe and the signal is absent.

---

## Regime Analysis

| Regime | Sharpe | Status |
|--------|--------|--------|
| Dot-com crash (2000-02) | -0.28 | ❌ Severe loss |
| GFC (2007-09) | 0.03 | ❌ Near-zero |
| Recovery (2003-06) | 0.90 | ✅ Pass |
| Bull (2015-19) | 1.02 | ✅ Pass |
| COVID (2020) | 0.44 | ❌ FAIL |

**Pattern:** Strategy only works in calm bull regimes. Fails in every stress or crash regime. This is consistent with the structural analysis — the strategy is a leveraged bull market bet on volatile stocks.

---

## Disposition: ABANDON

**Rationale:**

1. **IS MDD -74.2%** is categorically incompatible with the firm's capital preservation mandate and $25K account size.
2. **Permutation p=1.0** confirms absence of alpha — not a borderline result.
3. **Regime failure** is structural (portfolio construction), not addressable by parameter tuning or regime overlays.

**Why alternatives were rejected:**

- **Long-short variant:** $25K capital + PDT constraints + 2-5% borrow costs on high-vol names → impractical and likely Sharpe-negative post-cost.
- **VIX < 20 regime gate:** Does not address the core problem (high-vol stock selection during stress). Even with VIX gate, remaining trades retain the crash-concentrated portfolio construction.

---

## Lessons for Future Research

### Lesson 1: Long-Only Conversion of Long-Short Academic Papers

Before approving any hypothesis adapted from a long-short academic paper:
- **Require explicit long-only pro-forma:** Estimate IS MDD and Sharpe assuming no short leg
- **Apply crash-concentration pre-screening:** If the universe selector (not the momentum signal) concentrates in crash-prone names, the long-only conversion is structurally flawed

**Checklist addition:** New hypothesis review checklist must include: "Is this adapted from a long-short academic paper? If yes, provide long-only pro-forma MDD estimate."

### Lesson 2: Pre-Flight MDD Proxy for High-Vol Universe Selection

Any strategy that selects stocks by **high realized volatility** (top-N%) for a long-only structure:
- Must provide a pre-flight MDD proxy using the vol-selected universe during IS stress regimes (2000-02, 2008-09)
- If estimated MDD > 40% in any stress regime → **reject at hypothesis stage** without Gate 1 commission

**Rule:** Long-only + top-N% realized vol universe selector → pre-flight stress MDD required. Reject if MDD > 40% in dot-com or GFC.

---

## Re-Activation Conditions

H16 may be reconsidered under the following changed conditions:

| Condition | Change required |
|-----------|----------------|
| Capital tier | ≥ $100K to support margin + borrow costs for long-short implementation |
| Data pipeline | Intraday data enabling stock-level VIX hedge overlay |
| Academic validation | Alternative factor definition (e.g., idiosyncratic vol only, ex-systematic risk) that reduces crash correlation |

**Current status:** ARCHIVED. No re-activation scheduled.

---

## Impact on Research Pipeline

- **Gate 1 pass rate (all-time):** 1/11 = **9.1%** — below 10% alert threshold
- **CEO escalation filed:** [QUA-176](/QUA/issues/QUA-176) (updated with H16 failure)
- **Research buffer:** Empty — QUA-175 (TV Discovery batch 3) must be assigned to Alpha Research Agent immediately
