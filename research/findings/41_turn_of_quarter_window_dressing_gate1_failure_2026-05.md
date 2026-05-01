# H41: Turn of Quarter Window Dressing — Gate 1 FAIL & Retirement

**Status:** ARCHIVED (retired after single iteration)
**Date:** 2026-05-01
**Hypothesis file:** `research/hypotheses/41_qc_turn_of_quarter_window_dressing.md`
**Backtest report:** `backtests/h41_turn_of_quarter_gate1_report.md`
**Related tickets:** [QUA-308](/QUA/issues/QUA-308) (QC discovery), [QUA-316](/QUA/issues/QUA-316) (pre-flight review), [QUA-320](/QUA/issues/QUA-320) (Gate 1 backtest), [QUA-334](/QUA/issues/QUA-334) (retirement decision)

---

## 1. Gate 1 Verdict: FAIL

**Checks passed: 3/11**

| Metric | Result | Threshold | Status |
|---|---|---|---|
| IS Sharpe | 0.083 | >1.0 | FAIL |
| OOS Sharpe | 0.617 | >0.7 | FAIL |
| IS MDD | -12.04% | <20% | PASS |
| IS Trade Count | 75 | ≥100 | FAIL |
| WF Folds | 0/4 | ≥3/4 | FAIL |
| Permutation p-value | 0.766 | ≤0.05 | FAIL |
| DSR | -103.9 | >0 | FAIL |
| IS Annualized Return | 0.27% | — | (reference) |
| IS Win Rate | 56% | — | (reference) |
| IS Profit Factor | 1.14 | — | (reference) |

---

## 2. Quantitative Summary

- **IS period:** 1993–2018 (25 years, 4 quarter-end events/year = 99 possible windows)
- **After 200-day SMA filter:** 75 trades executed (24 windows skipped during sustained downtrends)
- **OOS period:** 2019–2024 (~25 OOS trades — too sparse to interpret Sharpe of 0.617 as signal)
- **Walk-forward:** 0 of 4 folds produced positive Sharpe — consistent failure across all sub-periods

---

## 3. Qualitative Assessment

### Economic rationale validity
The window dressing mechanism (Lakonishok et al. 1991) is academically supported and structurally plausible. The effect exists directionally (56% win rate, 1.14 PF), confirming that quarter-end buying pressure does create a mild directional bias. However, the magnitude is insufficient: 0.27% mean return per 5-day window produces near-zero annualized alpha after the trend filter.

### Primary failure mode: Alpha density too low for quarterly frequency
The strategy is active only 20 trading days per year (5 days × 4 quarter-ends). This creates two reinforcing problems:
1. **Trade sparsity:** Even over 25 IS years, only 99 possible events exist — insufficient for Walk-Forward validation at any meaningful sub-period length
2. **Low annualized alpha:** Even if each window earned a consistent +0.5%, 20 active days vs. 252 calendar days means annualized contribution is minimal

### Look-ahead bias check
**Clean.** Calendar-driven entry/exit, no future data in signal construction. Pre-flight gates passed cleanly at submission.

### Overfitting risk
**Low but irrelevant.** Signal is calendar-defined with no parameter search (200-day SMA is standard). The failure is not overfitting — it is genuine alpha insufficiency.

### Statistical significance
**p=0.766** is the most damning single metric. The strategy's IS results are statistically indistinguishable from random. The permutation test shows that 76.6% of random permutations of the same trade sequence produce equal or better Sharpe ratios.

---

## 4. Key Observations

1. **Trade sparsity is structural and unresolvable** for quarterly-window strategies. The 200-day SMA filter is necessary for bear-market protection (PF-2 compliance) yet is the same filter that reduces trade count from 99 to 75. Removing it recovers 24 trades but violates the pre-flight gate. The constraint is binding.

2. **OOS Sharpe (0.617) exceeding IS Sharpe (0.083) is noise, not signal.** With only ~25 OOS trades, the OOS Sharpe has extremely wide confidence intervals. The OOS estimate cannot be interpreted as evidence of out-of-sample persistence.

3. **0/4 WF folds passing is the clearest indicator of structural failure.** Even a marginal strategy would pass 1–2 folds by chance. Zero folds indicates the return profile is unstable across time sub-periods, not just statistically weak in aggregate.

4. **The window dressing effect is real but too small for standalone use.** A 56% win rate and 1.14 PF confirm the directional bias exists. However, as a 5-day event 4× per year, it could theoretically function as a weak overlay component on a more alpha-dense strategy — but it fails the Signal Combination Policy's IC > 0.02 minimum for standalone signal use.

5. **Seasonal anomalies in large-cap US equity ETFs face increasing headwinds** from crowding and front-running. The Turn of Month effect (H22, which uses all 12 month-ends and 4-day windows = 48 events/year) demonstrated that event frequency is the critical enabler for seasonal strategies. H41's 4-event/year calendar cannot achieve the required sample density.

---

## 5. Next Steps

**Verdict: ARCHIVED — no follow-up iterations.**

- H41 family retired after single iteration. No H41b.
- Resources redirected to next pipeline wave:
  - **H43** (Macro Announcement Day Premium — CPI/NFP): event-driven, ~24 events/year, Savor-Wilson (2013) backing
  - **H44** (LQD/IEF Credit Risk Appetite Timer): cross-asset relative value, daily signal, no trade-count constraint
  - **H42** (January Small Cap Effect): if not yet submitted to Engineering Director, check status

**Research lesson:** Quarterly-window seasonal strategies face a structural trade-count ceiling that makes Gate 1 walk-forward validation infeasible at any reasonable parameter budget. Seasonal strategies must have at minimum 8–12 events per year (e.g., monthly = 12/year) to support robust IS/OOS splits. File this as a negative prior on quarterly-frequency strategies.
