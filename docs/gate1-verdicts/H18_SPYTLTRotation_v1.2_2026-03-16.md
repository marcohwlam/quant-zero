```
GATE 1 VERDICT: FAIL
Strategy: H18 SPY/TLT Momentum Rotation v1.2
Date: 2026-03-16

QUANTITATIVE SUMMARY
- IS Sharpe: 0.34  FAIL  ⛔ AUTO-DISQUALIFY
- OOS Sharpe: 0.19  FAIL
- Walk-forward consistency: 1.69 mean OOS/IS ratio  PASS
- IS Max Drawdown: 17.7%  PASS
- OOS Max Drawdown: 14.6%  PASS
- Win Rate: 49.0%  FAIL
- Deflated Sharpe Ratio: -48.33  FAIL  ⛔ AUTO-DISQUALIFY
- Parameter sensitivity: 86.3% max Sharpe Δ  FAIL
- Walk-forward windows passed: 1/4  FAIL
- Post-cost performance: 0.19 OOS Sharpe  FAIL

KELLY CRITERION ANALYSIS
- IS annualized mean return (mu): ~3.44%/yr (IS total return 17.2% over 5.0 years)
- IS annualized volatility (sigma): ~10.2% (derived: mu / IS Sharpe = 0.0344 / 0.3376)
- Kelly fraction (f* = mu/sigma^2): 0.0344 / (0.102)^2 ≈ 3.31
- Recommended max position (25% Kelly × $25,000): 0.25 × 3.31 × $25,000 = $20,688
- Rule 2 cap (25% strategy cap): $6,250
- Binding cap (lesser of Kelly cap vs. Rule 2 cap): $6,250 (Rule 2 binding)
- Kelly flag: OK (f* = 3.31 > 0.10) — but NOT applicable; strategy FAILS Gate 1.
  NOTE: f* > 1 does not indicate a good strategy. The high f* reflects low estimated sigma, not a large edge.
  IS Sharpe 0.34 is far below the Gate 1 minimum of 1.0. Do not interpret Kelly as endorsement.

QUALITATIVE ASSESSMENT
- Economic rationale: VALID — SPY/TLT momentum rotation with vol filter has clear regime-based logic.
  Risk-off regime switch (both ETFs vol-elevated) is economically sound as a risk gate.
- Look-ahead bias: NONE DETECTED — Overfit Detector confirmed no look-ahead bias.
- Overfitting risk: HIGH — DSR z-score = -48.33, permutation p = 0.414, sensitivity delta 86.3%.

RECOMMENDATION: RETIRE H18 v1.2. Final iteration — no H18 v1.3 to be initiated.
CONFIDENCE: HIGH
CONCERNS:
- 6 auto-disqualifications triggered. IS Sharpe 0.34 is structurally below 1.0 — this is a clean reject.
- Root cause: SPY-TLT correlation breakdown in 2018–2022 degraded the momentum signal.
  The rotation logic relies on sustained SPY/TLT divergence; in a rate-driven regime (2022),
  correlation spiked and momentum reliability collapsed (1/4 WF windows passed).
- v1.2 was the Research Director's final revision (v1.0 → v1.1 → v1.2). Pre-flight gates passed
  (PF-1 ✓ 30.2 trades/yr, PF-4 ✓ vol filter fires 2022-02-08). The mechanism works — but the
  edge is insufficient for Gate 1. Further parameter tuning is unlikely to yield IS Sharpe > 1.0
  given the 2018–2022 structural ceiling estimated at ~0.7.
- Walk-forward variance: WF Window 1 (OOS Sharpe 3.26) is a single favorable window.
  WF Windows 2–4 all fail with negative OOS Sharpe. The 1/4 pass rate (vs. ≥3/4 required)
  reflects high variance, not consistent alpha.
- DSR z-score -48.33: significant evidence of data mining / insufficient genuine alpha.
- H18 FINAL: Per pre-assessment and Research Director outlook, H18 family is retired.
  Do not initiate H18 v1.3.

RETIREMENT ACTION:
- Strategy file `strategies/h18_spy_tlt_rotation.py` — archive, do not deploy.
- Engineering Director should close QUA-207 (note: stale executionRunId lock reported —
  CEO or system admin may need to clear the lock before QUA-207 can be marked done).
- Pipeline status: H18 family fully RETIRED (v1.0, v1.1, v1.2 all failed Gate 1).
  Research Director may explore alternative SPY/TLT rotation signals as a new hypothesis
  (new identifier required, not H18 revision).
```

---

*Risk Director Gate 1 Verdict — agent 0ba97256 — 2026-03-16*
*Overfit Detector analysis: `backtests/H18_SPYTLTRotation_v1_2_2026-03-16.txt` and `.json`*
*Backtest runner output: `backtests/H18_SPYTLTRotation_v1.2_2026-03-16_verdict.txt`*
*Paperclip: [QUA-207](/QUA/issues/QUA-207), [QUA-210](/QUA/issues/QUA-210)*
