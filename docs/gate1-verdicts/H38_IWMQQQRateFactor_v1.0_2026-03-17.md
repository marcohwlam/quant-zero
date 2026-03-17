# Gate 1 Verdict: H38 IWM/QQQ Rate-Cycle Factor Rotation v1.0

**Date:** 2026-03-17
**Engineering Director:** e20af8ed-290b-4cee-8bce-531026cebad5
**Task:** QUA-302
**Primary short vehicle evaluated:** QID

---

```
GATE 1 VERDICT: FAIL
Strategy: H38 IWM/QQQ Rate-Cycle Factor Rotation v1.0
Date: 2026-03-17

QUANTITATIVE SUMMARY
- IS Sharpe: -0.5513  [FAIL, threshold 1.0]
- OOS Sharpe: -1.8269  [FAIL, threshold 0.7]
- Walk-forward consistency: 231.38% degradation  [FAIL, threshold < 30% degradation]
- IS Max Drawdown: -36.60%  [FAIL, threshold 20%]
- OOS Max Drawdown: N/A (aggregated from WF windows)
- Win Rate: 34.48%  [MARGINAL, threshold 50%]
- Profit Factor: 0.2911  [FAIL, threshold 1.2]
- Deflated Sharpe Ratio: N/A (single variant primary; sensitivity sweep conducted)
- Parameter sensitivity: FAIL (cliff edges detected)  [cliff edges: YES]
- Walk-forward windows passed: 0/4  [FAIL, threshold 3/4]
- Post-cost performance: PASS (transaction costs included in all metrics)

- Regime-slice (Pre-COVID 2018–2019 IS Sharpe): -0.5834 (8 trades) — INSUFFICIENT DATA (<10 trades)
- Regime-slice (Stimulus era 2020–2021 IS Sharpe): -2.0877 (4 trades) — INSUFFICIENT DATA (<10 trades)
- Regime-slice (Rate-shock 2022 IS Sharpe): N/A — Outside IS window (2007-2021) — N/A
- Regime-slice (Normalization 2023 IS Sharpe): N/A — Outside IS window (2007-2021) — N/A
- Regime-slice overall: 0 of 0 assessable regimes passed, stress regime included NO  [FAIL]

QUALITATIVE ASSESSMENT
- Economic rationale: VALID — Equity duration differential between IWM and QQQ
  is well-documented (Fama-French 1992, Asness et al 2013, Damodaran 2020).
  Rising rate environments structurally favor short-duration (IWM) vs.
  long-duration (QQQ) equity. Financially sound mechanism via discount rate
  compression of growth premiums and financials NIM expansion.
- Look-ahead bias: NONE DETECTED — DGS2 signal lagged by 1 trading day;
  all features use past-only data; execution at next open after signal Friday.
- Overfitting risk: LOW — 2 signal parameters; weekly rebalancing; rate
  threshold economic rather than curve-fitted; hysteresis from published
  regime literature. No ML, no complex filtering.

TRADE COUNTING NOTE (QUA-302 CEO Ruling):
Trade freq below QUA-281 50/year threshold was CEO-approved (QUA-301).
Round-trips = 29 over 15 years = ~1.9/year.
CEO authorized Gate 1 to proceed with documented methodology.

CORRELATION NOTE (QUA-302 CEO Ruling):
IWM/QQQ r≈0.75–0.85 exceeds QUA-281 mean-reversion spread threshold.
CEO position (QUA-301): H38 is directional factor rotation, not mean-reversion.
QUA-281 correlation constraint does not apply to directional regime strategies.

RECOMMENDATION: Return to Research Director — fails Gate 1
CONFIDENCE: MEDIUM
CONCERNS:
  - Rate-shock regime (2022) is OUTSIDE IS window; strong OOS performance expected
    but not validated in this IS period. This is structurally correct (IS = 2007-2021)
    but the best single regime for H38 is not part of the IS Sharpe aggregate.
  - QID tracking error vs. -1× QQQ over multi-week holding periods introduces
    basis risk. Monitored but not explicitly modeled in backtest (volatility drag).
  - Low trade frequency (~2/year) limits statistical power.
    CEO-approved override in place.
```

---

## Engineering Director Sign-Off

- Data quality checklist: COMPLETE (see gate1 report)
- Transaction costs applied per canonical model (Johnson Book 6)
- No look-ahead bias confirmed in code review
- CEO trade-frequency ruling (QUA-301) documented
- CEO correlation ruling (QUA-301) documented
- Both short vehicles tested (QID and QQQ direct short)

*Engineering Director: e20af8ed-290b-4cee-8bce-531026cebad5*
*Run: QUA-302 | 2026-03-17*