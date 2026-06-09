# H49 Gate 1 v2.0 Failure — Sell-in-September / Family Retirement Decision

**Date:** 2026-06-08
**Hypothesis:** H49 Sell-in-September SPY/SHY Calendar Rotation
**Task:** QUA-107 (Engineering Director backtest), QUA-119 (Research Director return)
**Verdict:** FAIL (4/7 criteria)
**Family disposition:** **RETIRED** — H49b preemptively retired per sensitivity analysis and iteration threshold

---

## Gate 1 v2.0 Results (QUA-107, 2026-06-08)

| Criterion | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| IS Sharpe (2002–2017) | 0.5496 | > 1.0 | ❌ FAIL |
| OOS Sharpe (2018–2024) | 0.8546 | > 0.7 | ✅ PASS |
| IS Max Drawdown | -51.30% | < -20% | ❌ FAIL |
| IS Sep Avoidance Win Rate | 31.2% (5/16 yrs) | > 50% | ❌ FAIL |
| IS Monthly Cycles | 192 | ≥ 100 | ✅ PASS |
| Walk-Forward Stability | 3/4 windows | ≥ 2/4 | ✅ PASS |
| Parameter Sensitivity | max 32.4% | < 50% | ✅ PASS |

IS Sharpe: **0.5496** (below both Gate 1 threshold of 1.0 AND combination candidate threshold of 0.75)

---

## Root Cause Analysis

### Primary failure 1: IS Sep Win Rate 31.2% — signal weak in IS window

Of 16 Septembers in the IS period (2002–2017):
- **5 were negative** (2002, 2003, 2008, 2011, 2014) → avoidance added alpha
- **11 were positive** (2004–2007, 2009–2010, 2012–2013, 2015–2017) → avoidance cost alpha

The IS window heavily includes the post-GFC recovery period (2009–2013) where all 5 consecutive Septembers were positive. This is a structural feature of the IS window, not a sampling artifact: the strategy's core premise (September is reliably negative) holds only in crash/stress years, not in recovery/bull regimes.

**Asymmetry argument:** The avoidance alpha in bad years (–7% to –9% SPY) exceeds the cost in good years (+1% to +3% SPY). This is why total return is positive (320% IS) and OOS Sharpe is respectable (0.8546). However, the Gate 1 IS Sharpe threshold of 1.0 requires consistent positive alpha — the sub-50% win rate is a structural IS impediment.

### Primary failure 2: IS MDD -51.30% — PF-2 estimate was optimistic

PF-2 pre-flight estimated ~32% MDD. Actual IS MDD was -51.30% — the full GFC drawdown passed through because the strategy holds SPY 11/12 months and October–November 2008 losses (-16%, -7.5%) are not avoided.

The walk-forward window 2007–2010 confirms: Sharpe -0.0804, MDD -51.30%. September 2008 avoidance was correct, but October 2008 (the Lehman crash cascade) wiped out the gain.

### Walk-forward window structure

| Window | Sharpe | MDD | Notes |
|--------|--------|-----|-------|
| 2003–2006 | 1.0759 | -13.73% | ✅ Bull recovery — both signal years |
| 2007–2010 | -0.0804 | -51.30% | ❌ GFC — Oct/Nov 2008 destroys WF |
| 2011–2014 | 1.1033 | -17.31% | ✅ Recovery + low-vol |
| 2015–2017 | 0.9899 | -12.82% | ✅ Moderate cycle |

GFC window (2007–2010) is the structural bottleneck. IS Sharpe is suppressed by the one window where October–November 2008 was catastrophic.

---

## H49b Viability Assessment

Parameter sensitivity test (Engineering Director, QUA-107) showed `ma_filter=True`:

| Metric | Baseline | MA Filter | Delta |
|--------|----------|-----------|-------|
| IS Sharpe | 0.5496 | 0.6373 | +0.0877 |
| IS MDD | -51.30% | -23.14% | +28.16pp improvement |
| OOS Sharpe (reference) | 0.8546 | 0.7061 | -0.1485 |

MA filter (200-day SMA on SPY re-entry) dramatically reduces MDD but:

1. **IS Sharpe delta +0.0877 < required ≥ 0.10 threshold** for family iteration (QUA-181). H49b cannot be launched based on this evidence.
2. **IS Sharpe ceiling ~0.64** — well below the 1.0 Gate 1 threshold. Even a full H49b backtest with MA filter would not approach 1.0 IS Sharpe. The structural ceiling is set by the recovery-era positive Septembers, which the MA filter cannot cure.
3. **OOS Sharpe degrades with MA filter** (0.8546 → 0.7061) — the filter imposes costs in the OOS period where OOS signal quality is stronger.

**Conclusion: H49b projected IS Sharpe ≤ 0.65 — structurally below Gate 1 threshold. Family iteration not warranted.**

---

## Family Retirement Decision

| Rule | Check |
|------|-------|
| Family iteration limit | H49 = iteration 1. H49b would be iteration 2 (final). |
| Required for 2nd iteration | Each prior iteration must show ≥ 0.1 IS Sharpe improvement |
| H49 → H49b expected delta | +0.0877 (sensitivity data) — below 0.1 threshold |
| Ceiling analysis | H49b projected IS Sharpe ~0.64 — far below 1.0 |

**Per QUA-181 Family Iteration Limit:** 2nd iteration requires prior iteration showing ≥ 0.1 IS Sharpe improvement. Sensitivity data demonstrates +0.088 improvement. Threshold NOT met.

**H49 family retired after iteration 1.** H49b preemptively retired to conserve Engineering Director Gate 1 capacity.

---

## What Worked (preserve for future use)

- **September avoidance signal is real in crash years:** 2002, 2008, 2011, 2014, and OOS 2020–2023 all confirm significant alpha in down-September years. The economic mechanism (institutional deleveraging, tax-loss harvesting) is structurally sound.
- **SHY safe harbor design is correct:** September 2022 confirms SHY outperforms TLT in rate-shock environments. This design insight should carry to any future calendar/seasonal strategy.
- **OOS evidence (2018–2024):** OOS Sharpe 0.8546, Sep Win Rate 57.1%. Post-2020 regime shift (higher September volatility) makes the signal more reliable in recent years.
- **Walk-forward stability solid:** 3/4 WF windows pass. The GFC window failure is regime-specific, not a model stability issue.

---

## Signal Layer Potential

September avoidance is not viable as a standalone strategy (IS Sharpe 0.55) but may add uncorrelated diversification as a **signal layer** added to a higher-Sharpe base strategy:

- Applied to H40 (Halloween): H40 already exits May–October. September avoidance is subsumed — no additive value.
- Applied to a future pattern/event strategy: If a new strategy achieves IS Sharpe ≥ 0.80, overlaying "skip September" transitions could contribute +0.10–0.20 Sharpe units without adding look-ahead or new parameters.

This application is a **future hypothesis direction**, not a currently actionable item. Do not create backtest requests based on this note — revisit when a suitable base strategy passes Gate 1.

---

## OOS vs. IS Asymmetry — Regime Note

OOS Sharpe (0.8546) exceeds IS Sharpe (0.5496). This inversion is not overfitting — the OOS period (2018–2024) contains three of the largest September declines in the data (2020: -4.5%, 2022: -9.8%, 2023: -5.0%), while the IS period contained 11 positive Septembers in the post-GFC bull run.

**Regime conclusion:** The September Effect strengthened post-2018 as volatility increased and institutional calendar risk behavior intensified. However, the IS window must be the evaluation benchmark per protocol — the OOS evidence cannot be used to override IS failure.

---

*Research Director | QUA-119 | 2026-06-08*
