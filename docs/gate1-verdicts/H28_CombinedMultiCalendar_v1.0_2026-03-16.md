```
GATE 1 VERDICT: FAIL
Strategy: H28 Combined Multi-Calendar v1.0 (TOM + OEX Week + Pre-Holiday)
Date: 2026-03-16

QUANTITATIVE SUMMARY
- IS Sharpe: 0.098  [FAIL — AUTO-DQ: threshold > 1.0]
- OOS Sharpe: 0.141  [FAIL: threshold > 0.7]
- Walk-forward consistency: OOS/IS ratio 3.02  [PASS: threshold > 0.70]
  ⚠️ NOTE: Ratio > 1.0 because IS Sharpe is near-zero. Numerically PASS but
  economically suspicious — OOS outperforming a near-zero IS is not a signal of
  genuine skill; it reflects regime luck in the short OOS window.
- IS Max Drawdown: -23.69%  [FAIL: threshold < 20%]
- OOS Max Drawdown: -9.17%  [PASS: threshold < 25%]
- Win Rate: 55.86%  [PASS: threshold > 50%]
- Deflated Sharpe Ratio: -102.64  [FAIL — AUTO-DQ: threshold > 0]
- Parameter sensitivity: 157.95% max Sharpe change  [FAIL — AUTO-DQ: threshold < 30%]
- Walk-forward windows passed: 3/4  [PASS: threshold ≥ 3/4]
- Post-cost Sharpe: 0.097  [FAIL: threshold > 0.7]
- Test period: 17 years (2008–2022 IS)  [PASS: threshold ≥ 5 years]
- Trade count IS: 367  [PASS: threshold ≥ 100]

AUTOMATIC DISQUALIFICATION FLAGS — TRIGGERED (3)
⛔ IS Sharpe 0.098 < 1.0 → AUTO-REJECT
⛔ DSR -102.64 < 0 → AUTO-REJECT
⛔ Parameter sensitivity 157.95% > 30% → AUTO-REJECT

Per criteria.md: any single auto-DQ flag = immediate rejection. 3 auto-DQs confirmed.

STATISTICAL RIGOR
- Monte Carlo p5 Sharpe: -1.11 (worst 5th pct is deeply negative)
- Bootstrap 95% CI: [-0.26, 0.70] (spans negative; true Sharpe likely near zero)
- Permutation p-value: 0.511 (>> 0.05 threshold — NO statistical edge detected)
- Walk-forward Sharpe variance: 0.45 (high variance across windows)

REGIME ANALYSIS — FAIL
- Pre-COVID (2018–2019): 0.36
- Stimulus era (2020–2021): -0.00
- Rate-shock (2022): -1.67 (CATASTROPHIC — strategy collapsed in rising rate regime)
- Regime criterion (≥2/3 regimes PASS): FAIL (0/3 regimes meet acceptable performance)

KELLY CRITERION ANALYSIS
- Note: With IS Sharpe 0.098 and permutation p-value 0.511, this strategy has no
  statistically demonstrated edge. Kelly analysis is moot — the Sharpe estimate is
  indistinguishable from noise.
- Estimated (illustrative only): If sigma ≈ 15%/yr, mu ≈ 1.47%/yr
  → f* = 0.0147 / 0.0225 ≈ 0.65 (theoretical)
  → 25% Kelly = 0.163 × $25,000 = $4,075 (theoretical)
- Kelly flag: LOW EDGE (f* estimate irrelevant — no statistical edge confirmed)
- MOOT: Strategy rejected on auto-DQ grounds before Kelly criterion applies.

QUALITATIVE ASSESSMENT
- Economic rationale: VALID (calendar anomalies are documented in literature)
  but implementation is too aggressive — three signals combined OR-logic
  creates excessive exposure with insufficient alpha per unit of risk
- Look-ahead bias: NONE DETECTED (data pipeline clean, OOS quality 100%)
- Overfitting risk: HIGH
  - DSR z = -102.64 is among the worst in pipeline history (comparable to H21)
  - Permutation p = 0.511 confirms performance is indistinguishable from random
  - OEX Week parameter (`oex_exit_on_thursday`) causes 158% Sharpe swing —
    the strategy's sign depends on a single binary flag (unreliable)
  - Rate-shock 2022 Sharpe of -1.67 indicates regime fragility, not calendar edge

ROOT CAUSE OF FAILURE
The combined OR-logic calendar system generates too many trades (367 IS) with
insufficient per-trade edge. Key weaknesses:
1. OEX Week signal is highly unstable (158% sensitivity to one parameter)
2. Combined OR-logic inflates trade count without improving risk-adjusted return
3. Strategy fully exposed during high-vol regimes (rate-shock 2022: -1.67 Sharpe)
4. No regime filter — enters calendar trades regardless of macro environment

RECOMMENDATION: FAIL — DO NOT PROMOTE TO PAPER TRADING
CONFIDENCE: HIGH (3 auto-disqualifications, permutation p=0.511)

CONCERNS (for CEO awareness even on FAIL):
- Win rate 55.86% suggests a real but weak calendar edge exists in the underlying
  signals. The failure is in implementation (signal combination, position sizing,
  no regime filter), not in the underlying calendar anomaly thesis.
- H29 (TOM + Pre-Holiday + 200-SMA regime filter) has already been commissioned
  to address the regime fragility root cause. This is the correct refinement path.
- H24 Combined IBS+TOM remains in the Gate 1 pipeline — may test whether TOM
  signal is stronger when combined with mean-reversion (IBS) rather than other
  calendar signals.

PIPELINE IMPACT: H28 is RETIRED (no v1.1 — fundamental signal stability issue).
Engineering pipeline has already advanced to H29 per QUA-242 refinement task.
```

---

**Verdict file:** `docs/gate1-verdicts/H28_CombinedMultiCalendar_v1.0_2026-03-16.md`
**Backtest artifacts:** `backtests/h28_combined_multi_calendar/`
**Issued by:** Risk Director (agent 0ba97256)
**Date:** 2026-03-16
