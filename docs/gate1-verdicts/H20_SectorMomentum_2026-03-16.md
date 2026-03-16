# GATE 1 VERDICT: FAIL
**Strategy:** H20 SPDR Sector Momentum Weekly Rotation v1.0
**Date:** 2026-03-16
**Submitted by:** Risk Director (QUA-195)
**Backtest source:** QUA-188 (Backtest Runner)
**Overfit Detector input:** QUA-197 (delegated — see overfitting section below)

---

## QUANTITATIVE SUMMARY

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| IS Sharpe (2018–2022) | 0.4558 | > 1.0 | **FAIL** ⚠️ AUTO-DISQUALIFY |
| OOS Sharpe (2023–2025) | 0.1458 | > 0.7 | **FAIL** ⚠️ AUTO-DISQUALIFY |
| Walk-forward consistency (OOS/IS ratio) | 0.32 | ≥ 0.70 (within 30%) | **FAIL** |
| IS Max Drawdown | -23.1% | < 20% | **FAIL** ⚠️ AUTO-DISQUALIFY |
| OOS Max Drawdown | -14.9% | < 25% | PASS |
| Win Rate (IS) | 51.0% | > 50% | PASS (marginal) |
| Deflated Sharpe Ratio | 0.0 | > 0 | **FAIL** ⚠️ AUTO-DISQUALIFY |
| Parameter sensitivity | 129.7% variance | < 30% | **FAIL** |
| Walk-forward windows passed | 1/4 | ≥ 3/4 | **FAIL** |
| Post-cost performance | Sharpe 0.4558 (costs embedded) | Must pass post-cost | **FAIL** (below 1.0) |
| Permutation p-value | 0.000 | ≤ 0.05 | PASS |
| Bootstrap 95% CI (IS Sharpe) | [-0.261, 1.244] | CI should exclude 0 | **FAIL** (CI includes 0) |
| MC p5 Sharpe | -0.345 | > 0 (preferred) | **FAIL** |
| Trade count (IS) | 196 (39.2/yr) | ≥ 30/yr | PASS |

**Criteria passed: 4/14**

### Automatic Disqualification Flags

1. **IS Sharpe = 0.4558 < 1.0** — In-sample Sharpe is less than half the required threshold. AUTO-DISQUALIFY.
2. **OOS Sharpe = 0.1458 < 0.7** — Out-of-sample performance is negligible. Only 0.32× the OOS threshold. AUTO-DISQUALIFY.
3. **IS Max Drawdown = -23.1%** — Exceeds the 20% IS drawdown limit. AUTO-DISQUALIFY.
4. **Deflated Sharpe Ratio = 0.0 ≤ 0** — After applying multiple-comparisons penalty, the strategy retains no statistical edge. AUTO-DISQUALIFY.

Any single auto-disqualification flag = immediate reject. H20 triggers four. The verdict is **REJECT**. No further analysis is required to reach this conclusion.

---

## KELLY CRITERION ANALYSIS

- IS annualized mean return (mu): 30.24% / 5 years = **6.05%**
- IS annualized volatility (sigma = mu / Sharpe): 0.0605 / 0.4558 = **13.27%**
- Kelly fraction (f* = mu / sigma²): 0.0605 / 0.01761 = **3.44**
- 25% Kelly cap: 0.25 × 3.44 × $25,000 = **$21,500**
- Rule 2 cap (25% strategy cap): **$6,250**
- **Binding cap (lesser): $6,250**

> ⚠️ **Note:** The Kelly fraction of 3.44 is mathematically high but reflects extremely noisy estimates. The bootstrap CI for IS Sharpe ranges from −0.261 to 1.244, which means sigma and mu estimates are unreliable. The Monte Carlo p5 Sharpe is −0.345, meaning in the bottom 5% of random simulations, the strategy loses money. In practice, Kelly analysis is **moot** given the multiple auto-disqualification failures. Position sizing is not applicable to a rejected strategy.

---

## WALK-FORWARD ANALYSIS

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | Pass (OOS ≥ 0.7) |
|--------|-----------|-----------|------------|------------|-------------------|
| 1 | 2018–2019 | -0.200 | 2020 | 0.304 | ❌ |
| 2 | 2019–2020 | 0.473 | 2021 | 1.997 | ✅ |
| 3 | 2020–2021 | 1.055 | 2022 | -0.679 | ❌ |
| 4 | 2021–2022 | 1.229 | 2023 | 0.351 | ❌ |

**Windows passed: 1/4** (threshold: ≥ 3/4)

Walk-forward OOS Sharpe: mean = 0.493, std = 0.961, min = −0.679. The very high standard deviation (std nearly 2× the mean) signals severe instability. Window 2's OOS result of 1.997 was entirely driven by the 2021 bull market recovery — the single regime where the strategy works.

---

## REGIME ANALYSIS

| Regime | Sharpe | Pass (≥ 0.8) |
|--------|--------|--------------|
| Pre-COVID 2018–2019 | -0.205 | ❌ |
| COVID crash 2020 | 0.334 | ❌ |
| Recovery 2021 | 2.238 | ✅ |
| Rate shock 2022 | -0.555 | ❌ |
| Normalization 2023 | 0.355 | ❌ |
| Post-norm 2024–25 | 0.050 | ❌ |

**1/6 regimes pass. Zero stress regimes pass.**

Required: ≥ 2 assessable regimes pass, including ≥ 1 stress regime (COVID crash or Rate shock). This strategy performs well **only** during trending bull markets (2021 recovery). It underperforms or loses in volatile, declining, or sideways markets — precisely the conditions where risk-managed strategies must hold up.

---

## OVERFITTING ASSESSMENT

*Pending full Overfit Detector Agent report (QUA-197). Preliminary assessment from available metrics:*

| Signal | Value | Interpretation |
|--------|-------|----------------|
| DSR | 0.0 | Multiple-comparisons penalty completely erases signal |
| Bootstrap 95% CI (IS Sharpe) | [-0.261, 1.244] | CI includes zero — no statistically significant edge |
| MC p5 Sharpe | -0.345 | Negative in bottom 5% of simulations |
| Parameter sensitivity | 129.7% variance across 18 combinations | SEVERE — Sharpe ranges 0.16–0.75 |
| OOS Sharpe degradation | 68% vs IS | Far exceeds 30% allowed degradation |
| WF OOS std | 0.961 | Extremely high vs mean of 0.493 |

**Preliminary overfitting risk: CRITICAL.**

The sensitivity heatmap is particularly damning: lb=10 produces Sharpe 0.75, while lb=20 (the chosen default) produces 0.46 — a 39% difference from a single-parameter change. The strategy appears tuned to the default parameters rather than exhibiting robust momentum effects. The 2021 recovery regime dominance across walk-forward window 2 further suggests the strategy has curve-fitted to a specific bull market environment.

---

## QUALITATIVE ASSESSMENT

- **Economic rationale:** WEAK — Sector momentum is a known phenomenon, but this implementation shows no consistent edge across market regimes. The strategy only profits during momentum-friendly bull markets (2021) while generating losses during stress and mean-reversion periods.
- **Look-ahead bias:** NO EVIDENCE DETECTED — Backtest Runner did not flag look-ahead bias in the signals.
- **XLK concentration risk:** LOW — XLK appears in top-3 in only 35.6% of IS weeks (threshold: 60%). Not a concentration concern.
- **Liquidity:** PASS — No liquidity-constrained flags raised.
- **Trade count:** PASS — 39.2 trades/year meets the ≥ 30/yr requirement.
- **OOS win rate:** 41.9% — Below the 50% threshold, confirming OOS deterioration.

---

## GATE 1 VERDICT

```
GATE 1 VERDICT: FAIL
Strategy: H20 SPDR Sector Momentum Weekly Rotation v1.0
Date: 2026-03-16

QUANTITATIVE SUMMARY
- IS Sharpe: 0.4558  FAIL ⚠️ AUTO-DISQUALIFY
- OOS Sharpe: 0.1458  FAIL ⚠️ AUTO-DISQUALIFY
- Walk-forward consistency: 0.32  FAIL
- IS Max Drawdown: 23.1%  FAIL ⚠️ AUTO-DISQUALIFY
- OOS Max Drawdown: 14.9%  PASS
- Win Rate: 51.0%  PASS (marginal)
- Deflated Sharpe Ratio: 0.0  FAIL ⚠️ AUTO-DISQUALIFY
- Parameter sensitivity: 129.7%  FAIL
- Walk-forward windows passed: 1/4  FAIL
- Post-cost performance: FAIL (Sharpe 0.46, below threshold)

KELLY CRITERION ANALYSIS
- Kelly fraction (f* = mu/sigma^2): 3.44
- Recommended max position (25% Kelly × capital): $21,500
- Binding cap (lesser of Kelly cap vs. Rule 2 cap): $6,250
- Kelly flag: OK (f* > 0.10) — but MOOT given Gate 1 FAIL

QUALITATIVE ASSESSMENT
- Economic rationale: WEAK
- Look-ahead bias: NONE DETECTED
- Overfitting risk: HIGH (CRITICAL preliminary assessment)

RECOMMENDATION: Reject — return to Research Director for fundamental revision
CONFIDENCE: HIGH
CONCERNS:
  1. Four automatic disqualification triggers — IS Sharpe, OOS Sharpe, IS MDD, DSR
  2. Strategy works only in 2021 bull market recovery; fails all other regimes
  3. Severe parameter sensitivity (129.7%) — signals curve-fitting, not genuine alpha
  4. DSR = 0.0 confirms no edge survives multiple-comparisons adjustment
  5. Walk-forward OOS std (0.961) is nearly 2× the mean — highly unstable
  6. OOS win rate 41.9% — below 50%, suggests edge does not generalize
```

---

## RECOMMENDATIONS FOR RESEARCH DIRECTOR

H20 requires fundamental revision before re-submission. Key areas to address:

1. **Core momentum signal is regime-dependent.** The strategy generates alpha only in trending bull markets. Research Director should explore regime-conditional entry — only activate rotation during confirmed uptrends (e.g., SPY above 200-day SMA with positive momentum), and move to cash or defensive sectors during stress regimes.

2. **Parameter instability is critical.** lb=10 produces 0.75 Sharpe vs lb=20 at 0.46. A robust strategy should show <30% variation. Research Director should identify which lookback period is economically motivated, not data-mined.

3. **OOS Sharpe degradation (68%) is severe.** The gap between IS (0.46) and OOS (0.15) is too large. Consider shorter lookback periods, fewer parameters, or regime filters to improve generalization.

4. **Do not re-submit with superficial parameter changes.** The DSR = 0.0 is the most damning signal: after penalizing for multiple comparisons, there is no statistically significant alpha. The strategy needs a structural change, not a parameter sweep.

---

*Verdict issued by Risk Director. CEO approval required before any further action. Research Director should be notified of rejection with this document.*
