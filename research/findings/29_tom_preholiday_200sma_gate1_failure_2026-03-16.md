# H29 Gate 1 FAIL — TOM + Pre-Holiday + 200-SMA Regime Filter

**Date:** 2026-03-16
**Ticket:** QUA-247 (Backtest Runner) / QUA-245 (Gate 1 parent)
**Verdict:** GATE 1 FAIL — RETIRE
**Family retirement:** Combined Calendar family (H28 iteration 1, H29 iteration 2) — **RETIRED per CEO Directive QUA-181 Family Iteration Limit**

---

## Metrics

| Metric | Value | Threshold | Pass |
|--------|-------|-----------|------|
| IS Sharpe | **0.026** | > 1.0 | ❌ FAIL |
| OOS Sharpe | **-0.049** | > 0.7 | ❌ FAIL |
| IS MDD | -15.84% | < 20% | ✅ PASS |
| IS Win Rate | 55.61% | > 50% | ✅ PASS |
| IS Trade Count | 205 | ≥ 100 | ✅ PASS |
| WF Windows | **2/4** | ≥ 3/4 | ❌ FAIL |
| Permutation p | 0.000 | ≤ 0.05 | ✅ PASS (signal direction marginal) |
| DSR | 0.536 | > 0 | ✅ PASS |
| Sensitivity | **FAIL** | < 50% reduction | ❌ FAIL |
| MC p5 Sharpe | -1.612 | ≥ 0.5 | 🚩 FAIL |

**Failing criteria:** IS Sharpe, OOS Sharpe, WF windows, WF consistency, parameter sensitivity.

---

## Root Cause

**Primary failure: TOM + Pre-Holiday signals do not generate economically significant alpha at $25K scale over the 2007–2021 IS period.**

1. **Profit factor ≈ 1.0** — gross wins and losses nearly exactly offset. Win rate 55.6% captures real direction, but return per trade is insufficient. Total IS return over 15 years: -0.13%.

2. **200-SMA filter works correctly but reduces compounding** — strategy was in cash for 80.9% of 2022 and 69.4% of 2008–2009. Bear market protection is effective, but the strategy earns zero alpha even in bull regimes.

3. **Signal too infrequent** — 13.7 trades/year in IS generates only 3–9 trades per 6-month walk-forward OOS window. Extreme Sharpe variance (std=1.59) across WF folds; impossible to validate reliably.

4. **Base parameters not optimal** — sensitivity sweep shows `entry=-1` consistently outperforms `entry=-2`. The default parameters are not at the optimal point, contributing to the sensitivity fail.

---

## Family Analysis: Combined Calendar Retired

| Version | IS Sharpe | Primary Failure | Disposition |
|---------|-----------|-----------------|-------------|
| H28 (TOM + Pre-Holiday + OEX Week) | N/A | OEX Week instability (157.95% sensitivity) | FAIL — iteration 1 |
| H29 (TOM + Pre-Holiday + 200-SMA) | 0.026 | Insufficient alpha — profit factor ≈ 1.0 | FAIL — iteration 2 |

**Structural bottleneck:** TOM and Pre-Holiday signals generate real return direction (win rate > 50%) but insufficient magnitude at the $25K SPY ETF daily close granularity. The academic edge (Ariel 1990, Lakonishok & Smidt 1988) requires intraday precision to capture in a consistent manner. Daily close entries blend signal with non-signal hours, degrading edge.

Per CEO Directive QUA-181: **Combined Calendar family is RETIRED. No H30 iteration within this family.**

---

## Pipeline Lessons

1. **Calendar-effect magnitude at daily close granularity is insufficient for Sharpe > 1.0** — TOM and Pre-Holiday effects are intraday phenomena being captured at daily close. Future calendar-effect strategies should either: (a) use open/close vs close/close analysis to isolate the return window, or (b) require intraday data capability.

2. **Signal frequency minimum for WF reliability** — strategies with < 20 trades/year in IS require at least 20-year IS windows or WF folds sized to ≥ 15 trades. H29's 13.7 trades/year with 6-month WF folds produced only 3–9 trades per fold — statistically inadequate.

3. **200-SMA regime filter is additive for risk management but cannot create alpha** — the filter correctly blocked the 2022 rate shock and 2008 GFC. The problem is the underlying signal, not the regime filter. The filter design is reusable in future hypotheses.

---

## Forward Guidance

**Do NOT commission H30 Combined Calendar** — family iteration limit reached per QUA-181.

Standalone H25 (OEX Week): Not recommended for Gate 1 — standalone Sharpe estimate 0.42–0.75 (below threshold). OEX Week instability confirmed across H28 failure analysis. Recommend **SUSPEND** pending intraday data infrastructure.

Standalone H26 (Pre-Holiday): Not recommended for Gate 1 — standalone Sharpe estimate ~0.40 (below threshold). Archive as potential component signal for future multi-signal framework when intraday data is available.

**New hypothesis direction required.** See Hypothesis Class Diversification Mandate (QUA-181) priority order.

---

*Research Director | QUA-247 | 2026-03-16*
