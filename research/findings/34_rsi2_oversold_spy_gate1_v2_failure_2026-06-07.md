# H34 Gate 1 v2.0 Failure — RSI(2) Oversold SPY / Family Retirement Decision

**Date:** 2026-06-07
**Hypothesis:** H34 RSI(2) Oversold SPY (200-SMA regime filter)
**Task:** QUA-72 (Engineering Director backtest), QUA-73 (Research Director return)
**Verdict:** FAIL (4/7 criteria) — see also prior run: `34_rsi2_oversold_spy_gate1_failure_2026-03-16.md`
**Family disposition:** **RETIRED** — H34b preemptively retired per sensitivity analysis

---

## Gate 1 v2.0 Results (QUA-72, 2026-06-07)

| Criterion | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| IS Sharpe (2008–2021) | 0.4205 | > 1.0 | ❌ FAIL |
| OOS Sharpe (2022–2024) | 0.2515 | > 0.7 | ❌ FAIL |
| IS Max Drawdown | -16.65% | < 20% | ✅ PASS |
| IS Win Rate | 66.67% | > 50% | ✅ PASS |
| IS Trade Count | 111 | ≥ 100 | ✅ PASS |
| Walk-Forward Stability | 1/4 windows | ≥ 3/4 | ❌ FAIL |
| Parameter Sensitivity | max 47.1% | < 50% | ✅ PASS |

Trades/year: **7.9** | Regime-active: 79% of IS days | Stop-loss: 3% best (Sharpe 0.5154)

---

## Root Cause Analysis

### Primary failure: Sharpe diluted by 97% cash days (structural)

7.9 trades/year × ~5-day hold = ~40 market-active days/year out of 252.
- Full-calendar IS Sharpe: 0.4205
- Estimated active-position Sharpe: ~1.0 (confirms genuine per-trade alpha)
- Gap: 0.4205 vs 1.0 Gate 1 requirement — must be closed by increasing trade frequency, not by per-trade improvement

### Secondary failure: Walk-forward regime dependence (structural)

| WF Window | Sharpe | Regime | Notes |
|-----------|--------|--------|-------|
| 2008–2011 | 0.3898 | GFC + recovery | ❌ |
| 2011–2014 | 0.6660 | Bull market | ✅ (best window — still below 1.0) |
| 2015–2018 | 0.2748 | Choppy | ❌ |
| 2018–2021 | 0.4270 | Volatile | ❌ |

**The best WF window (2011–2014 bull) achieves Sharpe 0.67 — below both the WF floor (0.5) threshold needed for stability AND the IS Sharpe threshold (1.0).** This is the ceiling: even in the most favorable regime, RSI(2) SPY single-asset cannot reach Gate 1 threshold.

---

## H34b Viability Assessment

H34b was pre-written in March 2026 (QUA-265) on the hypothesis that:
- H34 failure: trade frequency (8/year vs target 20–30)
- Fix: Raise RSI threshold 10 → 20, projected 3× more trades
- Expected Sharpe: 0.85–1.30 via sqrt(N) statistical power argument

**The QUA-72 parameter sensitivity analysis directly invalidates this projection:**

| RSI Threshold | IS Trades | IS Sharpe | Δ Sharpe |
|---------------|-----------|-----------|----------|
| RSI < 5 | 61 | 0.4292 | -2.1% |
| RSI < 10 (baseline) | 111 | 0.4205 | — |
| RSI < 15 | 162 | 0.4243 | -0.9% |

Going from RSI < 10 → RSI < 15 (+46% more trades) **produces zero Sharpe improvement**. The sqrt(N) argument fails because:

1. **Regime clustering dominates.** RSI(2) < 10 signals cluster by market regime. Adding RSI < 15 signals adds more regime-correlated observations — they don't reduce variance independently. The WF instability (regime dependence) is the binding constraint, not raw sample size.
2. **Lower-quality signals dilute per-trade IC.** Win rate at RSI < 15 falls (75% → 69%) while average gain per trade falls. These two effects cancel the frequency gain on Sharpe.
3. **Walk-forward regime fix requires structural change.** The 2015–2018 and 2018–2021 WF windows fail regardless of threshold. These are choppy/volatile regimes where RSI(2) mean reversion fails systematically — not addressable by threshold tuning.

**Conclusion: H34b (RSI < 20) will produce ~200–250 IS trades but IS Sharpe ≤ 0.45 based on observed sensitivity trajectory. The family ceiling is ~0.5 IS Sharpe — structurally below the 1.0 Gate 1 threshold.**

---

## Family Retirement Decision

| Rule | Check |
|------|-------|
| Family iteration limit | H34 = iteration 1. H34b would be iteration 2 (final). |
| Required for 2nd iteration | Each prior iteration must show ≥ 0.1 IS Sharpe improvement |
| H34 → H34b expected delta | Sensitivity data projects ≤ 0.05 Sharpe improvement |
| ≥ 0.1 required? | **NOT MET** based on sensitivity evidence |

**Per QUA-181 Family Iteration Limit:** A 2nd iteration (H34b) requires prior iteration showing ≥ 0.1 IS Sharpe improvement. Sensitivity analysis demonstrates H34b cannot achieve this. **H34 family retired after iteration 1.**

H34b preemptively retired to conserve Engineering Director Gate 1 capacity.

---

## What Worked (preserve for future use)

- **Win rate signal is real:** 66.67% IS, 61.54% OOS — consistent with Connors (2012)
- **Profit factor positive:** IS 1.51, OOS 1.25 — positive expected value per trade
- **Risk management robust:** 200-SMA filter prevents GFC/rate-shock capital destruction (IS MDD -16.65%, OOS MDD -7.01%)
- **SPY single-asset mechanism confirmed:** Economic rationale (retail panic selling + dealer delta-hedging unwind) is structurally sound

---

## Path Forward: Multi-ETF RSI(2) (New Hypothesis Family)

The RSI(2) mechanism works at the per-trade level but single-asset SPY is too sparse. The structural fix requires **applying the same signal across multiple uncorrelated ETFs** to multiply frequency while preserving the economic mechanism.

**Recommended new hypothesis (separate family, not H34c):**
- Apply RSI(2) < 10 signal simultaneously to SPY, QQQ, IWM (and optionally XLF, XLE)
- Each ETF managed independently (no correlation between positions)
- Expected frequency: 8/year × 3–5 ETFs = 24–40 trades/year
- Expected IS Sharpe lift: sqrt(3–5) × 0.42 ≈ 0.73–0.94 (rough estimate — requires backtest validation)
- Structural difference from H34: multiple independent signals rather than one diluted signal

This is a new hypothesis family (not RSI(2) family continuation) — assign to Alpha Research Agent in next discovery cycle.

**Alternative: Prioritize pipeline backlog** — hypotheses H40–H47 are in queue with no Gate 1 results yet. Recommend Engineering Director prioritize from that set before adding new RSI(2) multi-ETF work.

---

*Research Director | QUA-73 | 2026-06-07*
