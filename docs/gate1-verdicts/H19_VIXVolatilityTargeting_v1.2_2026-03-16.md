# GATE 1 VERDICT: FAIL
**Strategy:** H19 VIX-Percentile Volatility-Targeting SPY v1.2
**Date:** 2026-03-16
**Submitted by:** Risk Director
**Backtest source:** QUA-202 (Backtest Runner) / `backtests/H19_VIXVolatilityTargeting_v1.2_2026-03-16.json`

---

## QUANTITATIVE SUMMARY

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| IS Sharpe (2018–2022) | 1.3148 | > 1.0 | **PASS** |
| OOS Sharpe (2023–2024) | 6.7222 | > 0.70 | **PASS** |
| Walk-forward consistency (OOS/IS) | 5.11× | ≤ 1/0.70 ≈ within 30% | — (OOS > IS, see WF note) |
| IS Max Drawdown | -12.1% | < 20% | **PASS** |
| OOS Max Drawdown | -1.2% | < 25% | **PASS** |
| Win Rate (IS) | 56.8% | > 50% | **PASS** |
| Deflated Sharpe Ratio | ~0.0 (near-zero) | > 0 | **PASS** (marginal) |
| Parameter sensitivity | PASS (Sharpe range 1.31–1.90 across tier grid) | < 30% | **PASS** |
| Walk-forward windows passed | 2/4 | ≥ 3/4 | **❌ FAIL** |
| Post-cost Sharpe | 1.2185 | > 1.0 | **PASS** |
| Trade count (IS, pre-conditions) | 26.2/yr (131 total) | ≥ 30/yr (PF-1) | **❌ FAIL** |
| Permutation p-value | 0.132 | ≤ 0.05 | **❌ FAIL** |
| MC p5 Sharpe (bootstrap) | -1.62 | > 0 | **❌ FAIL** |
| 95% CI IS Sharpe | [-0.59, 0.99] (includes 0) | CI should exclude 0 | **❌ FAIL** |

**Auto-disqualification flags:** None individually, but 3 compounding failures (WF windows, PF-1 trade count, permutation test) constitute clear Gate 1 FAIL.

---

## KELLY CRITERION ANALYSIS

> **Note:** Kelly analysis is academic — strategy has failed Gate 1 and is not eligible for promotion. Included per protocol.

- IS annualized return: ~3.5% (18.78% total / 5.4 years)
- IS annualized vol (derived from Sharpe 1.3148): ~2.7%
- Kelly fraction (f* = mu/sigma²): ~48 (high due to low vol, low absolute return)
- **Interpretation:** As with H14, the pathological Kelly fraction reflects ultra-low vol relative to modest absolute return. Not binding — strategy is REJECTED.

---

## QUALITATIVE ASSESSMENT

**Economic rationale:** VALID — VIX percentile regime-based equity exposure reduction is well-grounded. The strategy correctly exits SPY ahead of 2022 rate shock (PF-4 first cash trigger: 2022-01-21, within 10 days of Fed pivot announcement).

**Look-ahead bias:** NONE DETECTED — VIX percentile computed on rolling 252-day lookback with 1-bar lag confirmed by Engineering Director.

**Overfitting risk:** HIGH — Key concerns:

1. **Walk-forward catastrophic failure in H2 2022:** Window 3 OOS Sharpe = -14.39, Window 4 OOS Sharpe = -3.85. This is not statistical noise — it is a systematic failure of the VIX regime filter in the 2022 H2 period when VIX was elevated but equities continued to decline despite "risk-off" VIX signals.

2. **OOS 2023–2024 Sharpe of 6.72 is suspicious:** 20 trades producing OOS Sharpe of 6.72 over 2 years is a red flag — this is likely a regime artifact (2023–2024 was unusually low-vol) rather than edge. With only 20 OOS trades, the OOS result cannot be statistically distinguished from luck.

3. **MC p5 Sharpe = -1.62 and 95% CI includes 0:** Monte Carlo simulation shows that ~5% of random draws produce Sharpe ≤ -1.62. The CI [-0.59, 0.99] does not exclude zero — we cannot reject the null hypothesis that the strategy has zero alpha.

4. **Permutation test p = 0.132:** At 5% threshold, this fails. Even at 15% threshold this would barely pass. The signal is not statistically distinguishable from data-mining on the IS window.

**Primary failure modes:**
- **2022 rate-shock H2 regime (structural):** VIX was elevated in H2 2022, but equities continued to fall. The VIX-based cash exit logic generates FALSE positives (or misses the actual bottom), producing extreme negative OOS Sharpe in WF windows 3 and 4.
- **Low trade count (PF-1):** 26.2/yr at default params is below the 30/yr threshold required for statistical reliability.
- **Insufficient statistical evidence of edge:** Permutation test and bootstrap CI both confirm the null cannot be rejected.

---

## WALK-FORWARD DEEP DIVE

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | Pass |
|--------|-----------|-----------|------------|------------|------|
| 1 | 2018-01-01→2020-12-31 | 2.03 | 2021-01-01→2021-06-30 | 5.74 | ✅ |
| 2 | 2018-07-01→2021-06-30 | 2.90 | 2021-07-01→2021-12-31 | 1.43 | ✅ |
| 3 | 2019-01-01→2021-12-31 | 3.02 | 2022-01-01→2022-06-30 | **-14.39** | ❌ |
| 4 | 2019-07-01→2022-06-30 | 2.18 | 2022-07-01→2022-12-31 | **-3.85** | ❌ |

**Observation:** Windows 1 and 2 cover favorable low-vol bull regimes (2021). Windows 3 and 4 cover the 2022 rate shock — the strategy's known failure mode. The catastrophic WF Window 3 OOS (-14.39 Sharpe) is the single most disqualifying data point.

---

## DISPOSITION

**RECOMMENDATION: RETIRE — do not revise further.**

**Rationale:** H19 has undergone two iterations (v1.0 → v1.2 with 30th/60th percentile thresholds). The core failure persists:

1. VIX-percentile regime filter is accurate in 2021 (low-vol bull) but **fails catastrophically in 2022** when VIX stays elevated through a prolonged bear market. The regime signal generates false re-entry signals.

2. The trade count problem (26.2/yr vs. 30/yr threshold) is a fundamental characteristic of a once-or-twice-monthly allocation decision — not a parameter tuning issue.

3. Statistical tests (permutation p = 0.132, MC p5 = -1.62, CI includes 0) consistently confirm insufficient alpha.

**A v1.3 revision is not recommended** — the core mechanism (VIX percentile as SPY allocation timer) has no statistically significant edge at the daily IS period tested. Further parameter iterations risk data-mining.

**Alternative:** If CEO/Research Director believes the VIX regime timing concept has merit, consider reframing as a **risk overlay** on a portfolio of strategies (reduce all allocations when VIX > Xth percentile) rather than a standalone SPY timing strategy. This would bypass the trade count problem and test the signal in a different context.

**CONFIDENCE: HIGH**

---

*Risk Director — 2026-03-16*
*QUA-202 backtest | `backtests/H19_VIXVolatilityTargeting_v1.2_2026-03-16.json`*
*H19 v1.0: Gate 1 FAIL (QUA-200). H19 v1.2: Gate 1 FAIL (this verdict).*
