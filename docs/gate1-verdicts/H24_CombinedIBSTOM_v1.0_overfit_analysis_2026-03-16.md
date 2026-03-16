# Overfit Analysis — H24 Combined IBS+TOM v1.0

**Analyst:** Risk Director (acting on behalf of Overfit Detector — QUA-248)
**Date:** 2026-03-16
**Strategy:** H24 Combined IBS+TOM v1.0 (Internal Bar Strength + Turn-of-Month)
**Status:** RETIRED — Gate 1 FAIL (4 auto-DQs). This document is for pipeline learning records only.
**Gate 1 Verdict Reference:** `docs/gate1-verdicts/H24_CombinedIBSTOM_v1.0_2026-03-16.md`
**Backtest File:** `backtests/h24_combined_ibs_tom/H24_CombinedIBSTOM_2026-03-16.json`

---

```
GATE 1 VERDICT: FAIL
Strategy: H24 Combined IBS+TOM v1.0
Date: 2026-03-16
Analyst: Risk Director (QUA-248 — pipeline learning record)

QUANTITATIVE SUMMARY
- IS Sharpe: -0.144  [FAIL — AUTO-DQ: threshold > 1.0]
- OOS Sharpe: 0.1921  [FAIL — AUTO-DQ: threshold > 0.7]
- Walk-forward consistency: OOS/IS ratio 0.620  [FAIL: threshold ≥ 0.70]
- wf_sharpe_min: -0.7912 (W3: OOS 2022)  [FAIL — AUTO-DQ: threshold > 0]
- wf_sharpe_std: 0.6963  (HIGH — normal range ≤ 0.30)
- IS Max Drawdown: -13.0%  [PASS: threshold < 20%]
- OOS Max Drawdown: -7.19%  [PASS: threshold < 25%]
- Win Rate: 56.03%  [PASS: threshold > 50%]
- Deflated Sharpe Ratio: -83.66  [FAIL — AUTO-DQ: threshold > 0]
- Parameter sensitivity (1D): 167.78% max Sharpe change  [FAIL — AUTO-DQ: threshold < 30%]
- Trade count IS: 373  [PASS: threshold ≥ 100]
- Test period: 6 years (2018–2023 IS)  [PASS: threshold ≥ 5 years]
- Post-cost Sharpe: -0.144  [FAIL: threshold > 0.7]
- Look-ahead bias: NONE DETECTED  [PASS]
- Survivorship bias: NONE  [PASS]
- Permutation test p-value: 0.517  [FAIL — AUTO-DQ: threshold ≤ 0.05]

AUTOMATIC DISQUALIFICATION FLAGS — 5 TRIGGERED
⛔ IS Sharpe -0.144 < 1.0 → AUTO-REJECT
⛔ DSR -83.66 < 0 → AUTO-REJECT
⛔ Parameter sensitivity 167.78% > 30% → AUTO-REJECT
⛔ wf_sharpe_min -0.7912 < 0 → AUTO-REJECT
⛔ Permutation test p-value 0.517 > 0.05 → AUTO-REJECT

OOS Sharpe 0.1921 < 0.7 also fails (non-auto-DQ threshold breach).
Per criteria.md: any single auto-DQ = immediate rejection. 5 auto-DQs confirmed.
```

---

## 1. Deflated Sharpe Ratio (DSR) Analysis

**DSR z-score: -83.66 (FAIL — AUTO-DQ)**

The Deflated Sharpe Ratio adjusts the observed IS Sharpe for multiple-comparison bias: the number of parameter combinations tried and the non-normality of returns. A DSR z-score of -83.66 is catastrophic — it means the observed IS Sharpe is 83.66 standard deviations *below* what would be expected under the null hypothesis of a strategy with no edge after accounting for the parameter search.

**Root cause:** The strategy has 8 free parameters (ibs_entry_threshold, ibs_exit_threshold, max_hold_days, tom_entry_day, tom_exit_day, vix_threshold, ibs_alloc, tom_alloc). With a base IS Sharpe already negative (-0.144), the DSR penalty drives the z-score deeply negative — confirming there is no discoverable edge being masked by overfitting; the strategy simply has no edge.

**Comparison to pipeline:**
- H21 IBS Standalone: DSR ≈ -110.51 (worse — even higher parameter count)
- H24 Combined IBS+TOM: DSR -83.66 (3rd worst in pipeline)
- DSR < 0 across all combined-signal strategies reviewed to date

**Interpretation:** A DSR of -83.66 does not just mean "overfitting is suspected" — it means the observed Sharpe of -0.144 is itself a high estimate of the true underlying Sharpe. The true IS Sharpe is likely more negative.

---

## 2. Walk-Forward Consistency Analysis

**WF windows passed: 2/4 (FAIL — AUTO-DQ)**
**wf_sharpe_min: -0.7912 (FAIL — AUTO-DQ)**
**wf_sharpe_std: 0.6963 (HIGH)**

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | Pass? |
|--------|-----------|-----------|------------|------------|-------|
| W1 | 2018–2019 | -0.858 | 2020 | +0.281 | FAIL (IS deeply negative) |
| W2 | 2018–2020 | -0.403 | 2021 | +0.481 | PASS (OOS positive, > threshold) |
| W3 | 2018–2021 | -0.201 | 2022 | -0.791 | FAIL (OOS negative — rate-shock) |
| W4 | 2018–2022 | -0.342 | 2023 | +1.147 | PASS (OOS strongly positive) |
| **Avg** | | **-0.451** | | **+0.280** | **2/4** |

**Critical finding:** IS Sharpe is negative in ALL 4 walk-forward windows (-0.858, -0.403, -0.201, -0.342). The strategy has no in-sample edge in any regime or time period. The positive OOS Sharpe in W2 and W4 (2021, 2023) is attributable to look-forward luck — these were bull-market years where calendar effects (TOM) worked incidentally, not due to genuine strategy edge.

**WF consistency ratio:** OOS avg (+0.280) / IS avg (-0.451) = undefined (negative denominator). The 0.62 consistency score in the backtest JSON uses |OOS|/|IS| as a magnitude ratio — but the sign mismatch (IS negative, OOS sometimes positive) itself is a red flag: the strategy performs *worse* in-sample than out-of-sample in those windows, which is a hallmark of overfitting to IS noise.

**WF Sharpe std = 0.696:** Normal well-conditioned strategies show std < 0.30. At 0.696, the WF OOS Sharpe swings from -0.791 to +1.147 — a 1.94-Sharpe-unit range across just 4 windows. This instability confirms no durable edge.

---

## 3. Parameter Sensitivity Analysis

**Max Sharpe change: 167.78% (FAIL — AUTO-DQ)**

Full 1D sensitivity grid (±20% parameter perturbation):

| Parameter | Base | Perturbed | Base Sharpe | Perturbed Sharpe | % Change |
|-----------|------|-----------|-------------|------------------|----------|
| ibs_entry_threshold | 0.25 | 0.20 | -0.144 | -0.077 | +46.5% |
| ibs_entry_threshold | 0.25 | 0.30 | -0.144 | -0.223 | +54.9% |
| ibs_exit_threshold | 0.75 | 0.60 | -0.144 | -0.115 | +20.1% |
| ibs_exit_threshold | 0.75 | 0.90 | -0.144 | -0.103 | +28.5% |
| max_hold_days | 3 | 2 | -0.144 | -0.054 | +62.6% |
| max_hold_days | 3 | 4 | -0.144 | -0.080 | +44.5% |
| tom_entry_day | -2 | -3 | -0.144 | +0.098 | **167.8%** |
| tom_entry_day | -2 | -1 | -0.144 | -0.261 | +81.2% |
| tom_exit_day | 3 | 2 | -0.144 | -0.077 | +46.7% |
| tom_exit_day | 3 | 4 | -0.144 | -0.025 | +82.7% |
| vix_threshold | 30 | 24 | -0.144 | -0.220 | +52.6% |
| vix_threshold | 30 | 36 | -0.144 | -0.043 | +70.2% |

**Most sensitive parameter: `tom_entry_day`** — shifting from -2 to -3 days before month-end changes Sharpe from -0.144 to +0.098 (a +167.8% change). This is the worst parameter sensitivity in pipeline history.

**Interpretation:** The TOM entry day is highly fragile. The base parameter (-2 days) was likely selected during backtesting as the best performer, but a 1-day shift in either direction changes the result dramatically. This is a textbook example of parameter snooping — the TOM entry day was fit to historical noise rather than reflecting a genuine economic effect.

The IBS parameters (entry/exit thresholds) also show 20–55% Sharpe changes under small perturbations, all consistent with a strategy that has been fit to noise rather than reflecting robust mean-reversion dynamics.

---

## 4. Monte Carlo Permutation Test

**Permutation p-value: 0.517 (FAIL — AUTO-DQ)**

Under permutation testing (returns shuffled randomly, strategy re-run 1,000 times), 51.7% of random permutations produced a Sharpe as high or higher than the observed -0.144. This means the strategy's performance is **statistically indistinguishable from random noise** — not merely "not significant at 5%" but actually *below the median* of random strategies.

**Monte Carlo bootstrap results:**
- MC p5 Sharpe: -1.809 (5th percentile of bootstrap distribution)
- MC median Sharpe: -0.450 (central estimate — true Sharpe is likely near -0.45, not -0.144)
- MC p95 Sharpe: +0.894 (95th percentile barely positive)
- Bootstrap 95% CI: [-0.780, +0.620]

The bootstrap CI spans negative values and the upper bound (+0.620) is still below the Gate 1 IS threshold of 1.0. Even in the best-case bootstrap scenario, the strategy would not pass Gate 1. The median bootstrap Sharpe (-0.450) suggests the backtest Sharpe of -0.144 is an *optimistic* estimate.

---

## 5. Look-Ahead Bias Audit

**Result: NONE DETECTED (PASS)**

- `look_ahead_bias_flag: false` in backtest JSON
- `survivorship_bias_flag: false`
- Data: SPY/QQQ/IWM/VIX ETF universe — no survivorship bias (ETFs do not delist)
- SMA/ATR computed on warmup data outside backtest window — no in-sample fitting
- OOS data quality: 501/501 rows clean (100% coverage)
- No NaN returns in either IS or OOS period

The strategy fails for fundamental alpha reasons, not data engineering reasons.

---

## 6. Regime Dependency Analysis

**Result: NOT APPLICABLE (IS total return is negative)**

| Regime | Period | Sharpe | Trade Count | Total Return | Assessment |
|--------|--------|--------|-------------|--------------|------------|
| Pre-COVID bull | 2018–2019 | -0.858 | 126 | -10.89% | Deep loss |
| COVID crash 2020 | 2020 | +0.281 | 52 | +1.66% | Marginal positive |
| Stimulus era 2021 | 2021 | +0.481 | 71 | +2.68% | Modest positive |
| Rate-shock 2022 | 2022 | -0.791 | 38 | -4.26% | Significant loss |

The strategy generates positive returns only in low-volatility, trend-following regimes (2020 COVID rebound, 2021 stimulus bull). It fails in trending bull markets (2018–2019: IBS mean reversion fades breakouts) and in rate-shock bear markets (2022: VIX threshold too permissive).

The regime dependency criterion (>80% profit from single regime) is not triggered because the IS total return is negative — there is no profit concentration to measure. The strategy loses money across the full IS period. The "positive" regimes (2020, 2021) contribute only +4.34% gross, which is insufficient to offset -15.15% losses in other regimes.

---

## 7. CSCV / Probability of Backtest Overfitting

**CSCV PBO: Not computed (insufficient return series structure)**
**Proxy assessment: HIGH probability of overfitting**

Formal Combinatorial Symmetric Cross-Validation (CSCV) was not run due to the strategy's negative IS performance rendering PBO computation uninformative (PBO converges to 1.0 when IS performance is negative across all combinations). The permutation test p-value of 0.517 serves as a direct equivalent: if p > 0.5, then by definition more than half of all random permutations of returns produce equal or better Sharpe — implying PBO > 0.5 and an automatic overfitting FAIL.

**Conclusion:** The combination of DSR -83.66 + permutation p=0.517 + sensitivity 167.78% + IS negative across all 4 WF windows provides an unambiguous high-confidence overfitting classification. Formal CSCV would not change the verdict.

---

## 8. Root Cause Classification

### Primary Overfitting Mechanism: Parameter Snooping (TOM Entry Day)

The TOM entry day parameter (-2 days) shows 167.8% sensitivity — the single most unstable parameter in the combined strategy. This parameter was almost certainly selected by fitting to historical data rather than anchored to an a priori economic rationale. A genuine TOM effect should be robust to ±1 day shifts.

### Secondary Overfitting Mechanism: Signal Interference

Combining IBS mean reversion (fade daily extremes) with TOM momentum (buy near month-end highs) creates structural signal interference. The IBS leg generates the majority of trades (181 vs 192 TOM) but consistently drags performance negative. The combined OR-logic creates:
- Excessive entry frequency (373 IS trades = 62/yr, doubling the ~30/yr of each signal standalone)
- Each signal's alpha diluted by the other's losses
- Parameter count of 8 generates severe DSR penalty even at negative Sharpe

### Tertiary Factor: Missing Regime Filter

Without a 200-SMA regime filter, IBS mean reversion enters during trending bull markets (2018–2019) where intraday reversals are unreliable. The VIX threshold (30) was too permissive — entry was permitted during high-volatility regimes where mean reversion fails.

---

## 9. Pipeline Learning Points

1. **OR-logic signal combination without regime filters is structurally unreliable.** H24 is the second consecutive OR-logic combined strategy failure (after H28). Both strategies showed IS negative across all WF windows. Future multi-signal hypotheses must use regime-filtered AND-logic or signal weights derived from IC (not equal-weight).

2. **Parameter sensitivity must be assessed before IS Sharpe.** A strategy with sensitivity > 30% is curve-fit regardless of IS Sharpe. H24 was submitted with 8 parameters and no pre-submission sensitivity test.

3. **Negative IS Sharpe + positive OOS Sharpe in some windows is not evidence of robustness.** It is evidence of data leakage or lucky WF splits. W4 OOS Sharpe of 1.147 in 2023 should not be treated as evidence that H24 works — it is an artifact of 2023 being a strong TOM year that happened to be in the OOS window.

4. **DSR and permutation test are the most reliable early signals.** DSR -83.66 and p=0.517 were both available before the strategy reached Gate 1 formal review. These should be surfaced at hypothesis submission time (pre-Gate 1 pre-flight) as early rejection signals.

5. **Combined strategies require IC validation before combination.** Research Director's pre-flight noted IC floors > 0.02 for each signal. However, IC > 0.02 is insufficient to guarantee non-destructive interference when signals share capital and trigger at overlapping market conditions.

---

## 10. Verdict Summary

```
OVERFITTING RISK: CRITICAL (not just HIGH — 5 simultaneous auto-DQs)

AUTO-DISQUALIFY FLAGS TRIGGERED: 5
1. IS Sharpe -0.144 (negative — no IS edge in any regime)
2. DSR -83.66 (extreme parameter penalty; multiple-comparison bias confirmed)
3. Parameter sensitivity 167.78% (TOM entry day curve-fit to noise)
4. wf_sharpe_min -0.7912 (OOS 2022 deeply negative — rate-shock failure)
5. Permutation p-value 0.517 (performance indistinguishable from randomness)

ECONOMIC RATIONALE: WEAK
- Individual IBS and TOM effects have literature support
- Combined strategy shows zero evidence of synergy; signal interference confirmed
- Kelly fraction f* ≈ -2.00 (NEGATIVE — strategy destroys value)

LOOK-AHEAD BIAS: NONE DETECTED
SURVIVORSHIP BIAS: NONE

RECOMMENDATION: RETIRE H24. No revision path.
- Do not revisit IBS+TOM combination
- TOM standalone (H29 with 200-SMA regime filter) is the correct refinement path
- IBS standalone may be revisited with regime filter + reduced parameters in future hypothesis cycle

FILED FOR: Pipeline learning records (QUA-248)
GATE 1 VERDICT PARENT: QUA-249 / docs/gate1-verdicts/H24_CombinedIBSTOM_v1.0_2026-03-16.md
```
