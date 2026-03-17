# Gate 1 Verdict — H39 Equity Breadth Timer v1.0

**Issued by:** Risk Director (agent 0ba97256)
**Date:** 2026-03-17
**References:** QUA-312, QUA-311, QUA-314, QUA-313
**Backtest report:** `backtests/h39_equity_breadth_timer_gate1_report.md`

---

```
GATE 1 VERDICT: FAIL
Strategy: H39 Equity Breadth Timer v1.0
Date: 2026-03-17

QUANTITATIVE SUMMARY
- IS Sharpe: 0.7248  [FAIL — threshold > 1.0 (AUTO-DQ)]
- OOS Sharpe: 0.5720  [FAIL — threshold > 0.7 (AUTO-DQ)]
- Walk-forward consistency: OOS/IS ratio 0.79 (Fold 4)  [FAIL — 1/4 folds passed, threshold ≥ 3/4 (AUTO-DQ)]
- IS Max Drawdown: 19.35%  [PASS — threshold < 20%]
- OOS Max Drawdown: 21.73%  [PASS — threshold < 25%]
- Win Rate: 61.11% (IS) / 42.86% (OOS)  [IS PASS / OOS NOTE — OOS below 50%]
- Deflated Sharpe Ratio: -30.83  [FAIL — threshold > 0 (AUTO-DQ)]
- Parameter sensitivity: max Sharpe Δ < 30% within ±20%  [PASS]
- Walk-forward windows passed: 1/4  [FAIL — threshold ≥ 3/4 (AUTO-DQ)]
- Post-cost performance: IS Sharpe 0.7248 (embedded)  [FAIL — insufficient IS Sharpe]
- Permutation test p-value: 0.532  [FAIL — threshold ≤ 0.05 (AUTO-DQ)]
- Trade count: 19 IS trades  [FAIL — no statistical power even with CEO frequency exception]

AUTO-DISQUALIFICATION FLAGS: 5
  1. IS Sharpe 0.7248 < 1.0
  2. OOS Sharpe 0.5720 < 0.7
  3. Walk-forward: 1/4 windows pass (< 3/4 threshold)
  4. Deflated Sharpe Ratio: -30.83 ≤ 0
  5. Permutation test p-value: 0.532 > 0.05

KELLY CRITERION ANALYSIS
- IS annualized return (est.): ~8.8% (225.62% total over 14 years, 2007–2021)
- IS annualized volatility (est.): ~12.1% (derived: mu / Sharpe = 0.088 / 0.7248)
- Kelly fraction (f* = mu/sigma²): ~6.01
- Recommended max position (25% Kelly × $25,000): $37,563
- Rule 2 cap (25% of capital): $6,250
- Binding cap: $6,250 (Rule 2 is binding)
- Kelly flag: OK (f* > 0.10) — NOTE: moot; strategy fails Gate 1

QUALITATIVE ASSESSMENT
- Economic rationale: VALID (sector breadth as market health proxy — well-documented in academic literature)
- Look-ahead bias: NONE DETECTED (sector SMA computed on lagged data)
- Overfitting risk: LOW (only 2 free parameters — entry threshold and SMA lookback; sensitivity analysis passed)

ROOT CAUSE ANALYSIS
The H39 strategy fails on 5 independent AUTO-DQ criteria. The core issue is structural:

1. Insufficient trade frequency (19 IS entries over 14 years): The strategy spends most of the IS
   window in cash. With so few trades, no statistical test can distinguish genuine edge from luck.
   IS Win Rate of 61.1% is consistent with noise at this sample size.

2. Walk-forward instability: Only Fold 4 (2018–2021) produces passing OOS Sharpe (0.77). Folds 1–3
   show OOS Sharpe of 0.20, 0.95, and 1.20 respectively — no consistent IS→OOS degradation pattern,
   suggesting regime dependency rather than a stable signal.

3. DSR -30.83: The IS Sharpe of 0.7248, already below threshold, deflates massively when adjusted
   for the multiple-testing penalty. This is the definitive statistical rejection signal — the
   observed performance is well within the distribution of chance outcomes.

4. Permutation test p=0.532: Cannot reject the null hypothesis of no edge. The SPY entry signal
   based on % sectors above 200-SMA does not produce returns statistically different from random
   entry at this threshold configuration.

The economic mechanism (sector breadth collapse → defensive exit) is sound, but the signal
produces too few trades across too few regimes to generate statistically reliable conclusions.

VERDICT: REJECT — DO NOT PROMOTE

RECOMMENDATION: Send back. No further iterations recommended at standard trade-frequency.
CONFIDENCE: HIGH (5 independent AUTO-DQ flags; permutation test confirms no edge)
CONCERNS (for archival):
  - OOS Win Rate of 42.86% (below 50%) is a warning sign consistent with IS overfitting to
    a specific regime (2009–2021 bull market). The signal may be regime-dependent rather than
    structural.
  - If CEO wishes to revisit H39-family concepts, the signal could be reconsidered with a
    lower entry threshold (e.g., ≥3 sectors above 200-SMA) to increase trade frequency. However,
    the permutation test suggests no edge exists at any threshold tested — this should be
    investigated before committing Engineering resources.
  - CEO exception for <50 trades/year (QUA-306) was correctly granted but did not change
    the fundamental statistical verdict. The exception applies to the frequency threshold, not
    to the statistical power requirement.
```

---

*This verdict does not require CEO decision — automatic rejection on 5 AUTO-DQ flags.
Per Risk Constitution Rule 4, strategies do not advance to paper trading without passing all
three gates. H39 does not pass Gate 1.*

*No capital at risk. No position sizing or demotion tracking required.*

---

*Issued by Risk Director (agent 0ba97256) — 2026-03-17 | QUA-312*
