# H19 VIX-Percentile Volatility-Targeting SPY v1.2 — Gate 1 Verdict

**Date:** 2026-03-16
**Ticket:** QUA-200 (verdict), QUA-202 (backtest run)
**Strategy file:** `strategies/h19_vix_volatility_targeting.py`
**Iteration:** 1 of 2 allowed Gate 1 iterations
**Verdict: FAIL — 3 auto-disqualifications**

---

## Gate 1 Results Summary

| Criterion | Value | Result |
|---|---|---|
| IS Sharpe > 1.0 | 1.3148 | ✅ PASS |
| OOS Sharpe > 0.7 | 6.7222 (20 trades) | ✅ PASS* |
| IS Max Drawdown < 20% | -12.10% | ✅ PASS |
| OOS Max Drawdown < 25% | -1.20% | ✅ PASS |
| Win Rate > 50% | 56.76% | ✅ PASS |
| IS Trades ≥ 100 | 111 | ✅ PASS |
| **WF windows passed ≥ 3/4** | **2/4** | **❌ FAIL** |
| **Permutation test (p < 0.05)** | **p=0.132** | **❌ FAIL** |
| **PF-1 trade count ≥ 30/yr** | **26.2/yr** | **❌ FAIL** |

*OOS Sharpe of 6.72 is based on only 20 trades — statistically unreliable. Sharpe 95% CI: [-0.59, 0.99] brackets zero.

**Gate 1 PASS: False**

---

## Disqualification Analysis

### DQ-1: Walk-Forward Failure (2/4 windows)

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | Result |
|---|---|---|---|---|---|
| 1 | 2018-01-01–2020-12-31 | 2.03 | 2021-01-01–2021-06-30 | 5.74 | PASS |
| 2 | 2018-07-01–2021-06-30 | 2.90 | 2021-07-01–2021-12-31 | 1.43 | PASS |
| 3 | 2019-01-01–2021-12-31 | 3.02 | **2022-01-01–2022-06-30** | **-14.39** | **FAIL** |
| 4 | 2019-07-01–2022-06-30 | 2.18 | **2022-07-01–2022-12-31** | **-3.85** | **FAIL** |

**Root cause:** The strategy catastrophically fails in the 2022 bear market — precisely the high-VIX regime it was designed to navigate. VIX percentile thresholds calibrated on 2018–2021 data did not adapt to sustained rate-shock conditions, where VIX stayed elevated for months rather than spiking briefly.

WF Sharpe std = 7.52; WF min = -14.39. This is a structural regime failure, not a parameter tuning problem.

### DQ-2: Permutation Test Failure (p=0.132)

No statistical evidence that H19 alpha exceeds what chance would produce (threshold: p < 0.05). Combined with DSR = 0.00, the strategy's apparent IS performance cannot be distinguished from luck.

### DQ-3: PF-1 Trade Count Failure (26.2/yr)

Actual IS trade count = 131 trades over 5 years = 26.2/yr. Minimum required = 30/yr. Mitigation B (VIX 10-day MA crossover) added additional trades but was insufficient to clear the threshold consistently in low-VIX years.

---

## Statistical Rigor (Full)

| Metric | Value |
|---|---|
| Monte Carlo p5 Sharpe | -1.62 |
| Monte Carlo median Sharpe | 1.22 |
| Monte Carlo p95 Sharpe | 3.01 |
| Sharpe 95% CI | [-0.59, 0.99] |
| MDD 95% CI | [-71.2%, -4.6%] |
| Permutation p-value | 0.132 |
| DSR | 0.000 |
| Post-cost Sharpe | 1.22 |

---

## Sensitivity Heatmap (IS Sharpe)

|  | tier2=0.55 | tier2=0.60 | tier2=0.65 |
|---|---|---|---|
| **tier1=0.25** | 1.6532 (108 tr) | 1.3920 (130 tr) | 1.9017 (136 tr) |
| **tier1=0.30** | 1.5485 (89 tr) | 1.3148 (111 tr) | 1.7096 (118 tr) |
| **tier1=0.35** | 1.6103 (74 tr) | 1.3113 (98 tr) | 1.6963 (106 tr) |

**Observation:** IS Sharpe is robust across the 3×3 grid (all > 1.0). However, parameter combos with tier2=0.65 show higher Sharpe AND higher trade counts — possibly worth targeting in a revision. The WF catastrophe likely persists regardless of parameter combo because it is regime-driven.

---

## Engineering Director Assessment

**Is this a fixable problem?** Partially uncertain.

The WF 2022 collapse is the most damning finding and suggests a structural limitation: VIX percentile thresholds optimized on low-interest-rate 2018–2021 data fail under 2022-style sustained inflation/rate-shock. A revision would need to:
1. Incorporate **rate regime awareness** (e.g., Fed Funds rate level or trend) so VIX thresholds adapt when the volatility regime shifts structurally
2. Or add **minimum hold period / VIX persistence filter** to avoid whipsawing into cash during sustained high-VIX regimes
3. Or replace pure percentile with **conditional percentile** (conditioned on rate/macro regime)

**Trade count fix:** tier2=0.65 combos show 118–136 trades over IS period = 23.6–27.2/yr — still below 30/yr threshold. This is a signal frequency issue tied to strategy architecture.

**Auto-retire threshold check:** IS Sharpe = 1.31 > 0.70 → **No auto-retire**. H19 family at 1/2 iterations. One revision allowed.

**Recommendation:** Return to Research Director. If revision addresses regime adaptation specifically (not just parameter tuning), a 2nd iteration is warranted. If Research Director assesses that regime adaptation is out of scope or adds too much complexity, retiring H19 is the correct call.

---

## Pre-Flight Status

| Check | Result |
|---|---|
| PF-1 (IS trade count ≥ 30/yr) | FAIL (26.2/yr) |
| PF-4 (first 2022 cash trigger ≤ 2022-01-31) | PASS (2022-01-21) |
| PDT compliance | PASS (max 3 trades in 5d) |
| Data quality | SPY/VIX 2011 days, 74 missing business days (survivorship bias noted for SPY) |

---

## Backtest Artifacts

- Raw results: `backtests/H19_VIXVolatilityTargeting_v1.2_2026-03-16.json`
- Verdict text: `backtests/H19_VIXVolatilityTargeting_v1.2_2026-03-16_verdict.txt`
- Strategy code: `strategies/h19_vix_volatility_targeting.py`

*Engineering Director | 2026-03-16*
