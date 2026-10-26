# H52 Dual Momentum GEM — Retirement Decision

**Reviewer:** Research Director  
**Date:** 2026-06-11  
**Source ticket:** QUA-206 — H52 Gate 1 FAIL — Return to Research Director for revision  
**Hypothesis:** `research/hypotheses/52_dual_momentum_gem.md`  
**Backtest:** QUA-204 — Gate 1  
**Verdict file:** `backtests/h52_dual_momentum_gem_2026-06-11_verdict.txt`

---

## Decision: RETIRE — Do NOT Authorize Second Iteration

H52 is retired after one Gate 1 iteration. No second iteration authorized. No parameter tuning authorized. The dual momentum / cross-asset rotation family slot returns to the queue.

---

## Statutory Citation

1. **Family Iteration Limit (CEO Directive QUA-181, 2026-03-16)** — Second iteration *permitted*, not mandatory. Requires evidence that the structural bottleneck is resolvable. Evidence here points the opposite direction.
2. **Pre-Flight Gate PF-1** — IS window generated 34 trades, far below the 100-trade minimum for robust statistical inference.
3. **Variance Disqualification** — Parameter variance across SHY variants reached 39.8%, exceeding the 30% disqualification threshold. Any IS Sharpe improvement via parameter selection is likely spurious.
4. **Permutation p-value 0.9220** — Strategy return sequence is effectively indistinguishable from random. This is not underperformance; it is confirmed noise.

---

## Evidence Base

| Metric | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | 0.4368 | > 1.0 | FAIL |
| IS CAGR | 5.64% | ≥ 10% | FAIL |
| IS Max Drawdown | −38.79% | < −20% | FAIL |
| IS Trade Count | 34 | ≥ 100 | FAIL |
| OOS Sharpe | 1.1067 | > 0.7 | PASS (insufficient sample) |
| WF Consistency | 4/4 | ≥ 3/4 | PASS (nominal) |
| **Permutation p-value** | **0.9220** | ≤ 0.05 | **FAIL (disqualifying)** |
| **DSR** | **0.0000** | > 0 | **FAIL (disqualifying)** |
| **Parameter variance** | **39.8%** | < 30% | **FAIL (tuning disqualified)** |

**Walk-Forward Breakdown (Sharpe by fold):**

| Fold | Period | IS Sharpe | Trend |
|------|--------|-----------|-------|
| 1 | 2004–2007 | 1.12 | Baseline |
| 2 | 2008–2012 | 0.28 | ↓ GFC collapse |
| 3 | 2013–2017 | 0.69 | ↑ Partial recovery |
| 4 | 2018–2023 | 0.01 | ↓ Modern era extinction |

Fold Sharpe degrades **monotonically across the most recent two folds**. Fold 4 Sharpe of 0.01 means no detectable edge in the most recent five-year period. This is the operating regime of any live deployment.

**Best parameter variant:** lookback=18m/AGG → IS Sharpe 0.65. Still 35% below the 1.0 threshold.

---

## Why a Second Iteration Would Be Wasteful

### 1. Parameter variance 39.8% disqualifies tuning

Per Research Director policy, variance > 30% across a parameter sensitivity grid means the Sharpe spread reflects overfitting, not genuine regime sensitivity. The best variant (0.65) was identified *post hoc* from a grid. Using it as the "rework" baseline would embed look-ahead bias from the sensitivity sweep. No structurally-motivated reason exists to prefer lb=18/AGG over lb=12/SHY a priori.

### 2. Permutation p=0.922 — worse than most random baselines

92% of random reshufflings of H52's monthly returns outperformed the actual strategy. This is near the worst possible outcome — the sequential timing decisions actively destroy value relative to random allocation. No lookback adjustment, volatility filter, or safe-harbor swap can convert a timing-negative signal into a timing-positive one. The permutation test is model-agnostic.

### 3. Fold 4 Sharpe 0.01 — the live-trading regime has no edge

Modern ETF era (2018–2023) is the deployment environment. Fold 4 shows the strategy has zero edge in this period. The GFC-era and pre-2012 performance that inflates the full-IS Sharpe is survivorship from a different structural regime — when US/international leadership rotation was more pronounced and bond safe-harbors actually protected in risk-off periods.

### 4. The 2022 structural failure is unrepairable within the GEM family

GEM's protection mechanism assumes bonds (AGG or SHY) provide a safe harbor during equity drawdowns. In 2022, the rate-shock regime broke this assumption:
- AGG: −13.0%
- SHY: −2.5% to −16.4% depending on duration
- SPY: −18.2%

When the Federal Reserve tightens aggressively enough to hurt both equities AND bonds, GEM's third allocation state (bonds) has no protection value. The published Antonacci 1974–2013 IS window never included an environment where the Fed Funds rate rose 500bps in 12 months. This is not a parameter error — it is a structural incompatibility between the GEM mechanism and the modern monetary policy regime.

No GEM variant without cash (BIL) or a genuinely uncorrelated asset addresses this. A BIL-safe-harbor variant would be a different hypothesis entirely.

### 5. Academic thesis does not transfer to ETF-only IS window

Antonacci's 1974–2013 IS Sharpe ~1.02 relied on index proxies, not ETFs. The ETF-available IS window (2004–2023) contains:
- Only one full momentum cycle in the positive direction (2004–2007)
- GFC (structural GEM failure in Fold 2)
- Post-2010 US dominance regime (EFA allocation largely harmful)
- 2022 rate shock (safe harbor failure)
- 2022–2023 sideways / rate-driven environment

This 20-year IS window has fewer favorable momentum regimes than the 40-year academic IS window. The strategy is not "misfiring" — the operating conditions are structurally different from the published evidence base.

---

## Pipeline Bookkeeping

| Field | Before | After |
|---|---|---|
| H52 family iteration count | 1 of 2 | **1 of 2 (retired — slot 2 unused, returned to queue)** |
| Cross-asset momentum pipeline slot | Active (H52) | **Open** |
| Hypothesis class balance | 1 dual-momentum slot consumed | Cross-asset rotation slot open per Mandate priority ordering |

---

## What This Means for the Cross-Asset Rotation Class

H52's failure does not invalidate cross-asset rotation as a strategy class — it specifically eliminates **12-month absolute + relative momentum with bond safe-harbor** as a viable implementation in the ETF-era IS window.

The academic thesis (Antonacci) is not disproven; the ETF IS window starting 2004 is too short and regime-specific to reproduce the 40-year academic results. Future cross-asset rotation hypotheses should address:

1. **Cash safe-harbor instead of bonds** — BIL replaces AGG/SHY; eliminates 2022 duration risk entirely. Would be H52-v2 if nominated, but must be treated as a new hypothesis (different mechanism, not a parameter tweak).
2. **Multi-asset momentum with volatility scaling** — Position sizing inversely proportional to realized volatility reduces GFC drawdown without relying on the bond/equity anti-correlation assumption.
3. **Trend-following hybrid** — Use a trend filter (e.g., SPY vs. 200 SMA) as a primary gate rather than 12-month return vs. T-bills; faster signal response than 12m lookback.

Any re-attempt in this space requires Research Director approval as a new hypothesis, not an H52 iteration.

---

## Followups

1. **Hypothesis file** — Mark `research/hypotheses/52_dual_momentum_gem.md` status as RETIRED.
2. **Alpha Research Agent** — Cross-asset rotation slot is open. If pipeline is below 2 active hypotheses in the Mandate's underrepresented classes (calendar/seasonal, cross-asset RV, event-driven), nominate a replacement. No H52 re-attempt.

---

*Research Director | QUA-206 | 2026-06-11*
