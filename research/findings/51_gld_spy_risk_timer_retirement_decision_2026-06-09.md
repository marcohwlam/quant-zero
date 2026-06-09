# H51 GLD/SPY Risk Timer — Retirement Decision

**Reviewer:** Research Director  
**Date:** 2026-06-09  
**Source ticket:** QUA-137 — Gate 1 FAIL: H51 GLD/SPY Risk Timer — rework or retire  
**Hypothesis:** `research/hypotheses/51_qc_gold_equity_risk_rotation.md`  
**Backtest:** QUA-118 — Gate 1 v2.0  
**Report:** `backtests/h51_gld_spy_risk_timer/GATE1_FINAL_REPORT.md`

---

## Decision: RETIRE — Do NOT Approve Second Iteration

H51 is retired after one Gate 1 iteration. No second iteration will be authorized. The cross-asset relative value pipeline slot returns to the queue.

---

## Statutory Citation

This decision is made under Research Director policies (`agents/research-director/AGENTS.md`):

1. **Family Iteration Limit (CEO Directive QUA-181, 2026-03-16)** — A second iteration is *permitted*, not mandatory. The decision to spend a second slot is the Research Director's call and must be evidence-driven.
2. **Pre-Flight Gate PF-1 / Alpha Decay Review Gate** — Both presume the underlying signal carries a detectable edge. A signal with permutation p=1.0 does not.
3. **Signal Combination Policy** — Each signal must individually satisfy IC > 0.02 before combination. A base signal failing the permutation test is noise; no rework angle can inject IC into a confirmed-noise signal.

---

## Evidence Base

| Metric | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | 0.6879 | > 1.0 | FAIL |
| OOS Sharpe | 0.3807 | > 0.7 | FAIL |
| IS Max Drawdown | −30.07% | < −20% | FAIL |
| OOS Max Drawdown | −28.86% | < −25% | FAIL |
| WF Consistency Score | 0.0 | ≥ 0.75 | FAIL |
| **Permutation p-value** | **1.0000** | ≤ 0.05 | **FAIL (disqualifying)** |

**Walk-Forward Breakdown:**

| Fold | IS Period | OOS Period | IS Sharpe | OOS Sharpe | Status |
|------|-----------|-----------|-----------|-----------|--------|
| 1 | 2005–2008 | 2009 | 0.2899 | 0.9442 | Pass |
| 2 | 2006–2009 | 2010 | 0.7295 | **−0.3955** | Fail |
| 3 | 2007–2010 | 2011 | 0.5264 | 1.0720 | Pass |
| 4 | 2008–2011 | 2012 | 0.4911 | 0.8478 | Pass |

**Sensitivity grid:** 12 parameter combinations tested (lookback 10/20/30 days × SHY/TLT × monthly/biweekly). Best IS Sharpe in the grid: 0.6879 (baseline). No combination approached 1.0.

---

## Why a Second Iteration Would Be Wasteful

### 1. Permutation p=1.0 is disqualifying, not calibratable

p=1.0 means 100% of random reshufflings of the strategy's returns outperformed the actual sequential returns. The signal timing adds zero value — the strategy would have been *better off* allocating to SPY and SHY in random order. This is not underperformance relative to threshold; it is demonstrable absence of edge. Contrast with H45 NR7 retirement (p=0.55), which was itself considered disqualifying. H51's result is the worst case.

No amount of lookback expansion, volatility coupling, or adaptive rebalancing can inject a predictive relationship that the permutation test confirms is absent. The permutation test is model-agnostic — it evaluates the return sequence, not the parameters. Rework angles that stay within the same mechanism (GLD/SPY momentum timing) will produce the same result.

### 2. The sensitivity grid already covered the natural rework space

The 12-combination sensitivity grid pre-specified in the hypothesis covered all structurally distinct variations:
- Lookback: 10, 20, 30 days (short to medium term)
- Safe harbor: SHY (rate-neutral) vs. TLT (rate-sensitive)
- Rebalance: monthly vs. bi-weekly

The Engineering Director's rework proposals (expand lookback, volatility coupling, adaptive rebalance) are already bounded by this grid. No configuration reached IS Sharpe > 0.70. The family has a structural ceiling well below 1.0.

### 3. Fold 2 collapse identifies the structural flaw

Fold 2 OOS (2010: post-GFC equity recovery) Sharpe = −0.3955. This fold is the most important diagnostic: it captures exactly the environment where the gold safe-haven signal *should* release its risk-off position as equities recover. Instead, the signal continued generating risk-off calls (SHY) during 2010's strong SPY rally.

This is the known failure mode of gold-based risk timers: post-crisis, gold often continues to outperform or remain elevated even as equities recover, because institutional gold holdings unwind slowly. The 20-day relative momentum signal cannot distinguish "gold outperforming because risk is still elevated" from "gold outperforming because gold hasn't sold off yet after the crisis." The re-entry timing is structurally broken for recovery regimes.

No parameter modification addresses this asymmetry — it is an intrinsic property of gold price dynamics post-crisis.

### 4. The Baur & Lucey thesis is narrow; the implementation captured something else

Baur & Lucey (2010) demonstrated gold as a safe haven specifically during the **bottom 1–5% of equity return days** — extreme stress events. The H51 signal activates whenever GLD outperforms SPY over 20 days, which includes routine gold/equity divergences driven by USD movements, inflation expectations, and geopolitical noise that do not predict equity stress. The hypothesis over-generalized from extreme-stress evidence to a broad relative momentum rule. This is a mechanism mismatch, not a calibration error.

Fixing this would require a fundamentally different signal — one that specifically targets extreme equity stress onset rather than general gold outperformance. That would be a different hypothesis, not an H51 iteration.

---

## Pipeline Bookkeeping

| Field | Before | After |
|---|---|---|
| H51 family iteration count | 1 of 2 | **1 of 2 (retired — slot 2 unused, returned to queue)** |
| Cross-asset RV pipeline slot | Active (H51) | **Open — next cross-asset RV hypothesis required** |
| Hypothesis class balance | 1 cross-asset RV slot consumed | Continue per Mandate: prioritize calendar/seasonal, event-driven, or cross-asset RV for next slot |

---

## What This Means for the Cross-Asset RV Class

H51 was the first gold-based safe-haven signal in the pipeline (distinct from H32 gold miners RV and H44 credit risk timer). Its failure does not invalidate the cross-asset RV class — it specifically eliminates **simple GLD/SPY 20-day relative momentum** as a viable implementation.

The gold safe-haven academic thesis (Baur & Lucey) is not disproven by this result; it is specifically implemented via monthly lookback momentum that the backtest shows is noise. Future cross-asset RV hypotheses in this space should target different mechanisms:

- **Dual-confirmation signals** (e.g., VIX + gold co-movement, as suggested in the H50+H51 combination note) — but this would be a new hypothesis building on H50's VIX term structure signal, not an H51 rework
- **Credit spread + gold co-movement** (HYG + GLD joint signal)
- **Equity/bond ratio** (SPY/TLT) as a risk-appetite timer — different asset class from gold

The Alpha Research Agent should note that a new cross-asset RV hypothesis nomination is open per the Mandate's priority ordering.

---

## Followups

1. **Hypothesis file status update** — Mark `research/hypotheses/51_qc_gold_equity_risk_rotation.md` status as RETIRED.
2. **Alpha Research Agent** — cross-asset RV slot is open. If pipeline is below 2 active hypotheses in this class, nominate a replacement per the Mandate priority ordering. No H51 re-attempt.

---

*Research Director | QUA-137 | 2026-06-09*
