```
GATE 1 VERDICT: FAIL
Strategy: H21 IBS SPY Mean Reversion v1.0
Date: 2026-03-16

QUANTITATIVE SUMMARY
- IS Sharpe: -0.41  FAIL  ⛔ AUTO-DISQUALIFY
- OOS Sharpe: 0.12  FAIL
- Walk-forward consistency: 0.00 mean OOS/IS ratio  FAIL
- IS Max Drawdown: 38.8%  FAIL  ⛔ AUTO-DISQUALIFY
- OOS Max Drawdown: 10.1%  PASS
- Win Rate: 56.8%  PASS
- Deflated Sharpe Ratio: -110.51  FAIL  ⛔ AUTO-DISQUALIFY
- Parameter sensitivity: 117.0% max Sharpe Δ  FAIL
- Walk-forward windows passed: 0/4  FAIL
- Post-cost performance: 0.12 OOS Sharpe  FAIL

KELLY CRITERION ANALYSIS
- IS Sharpe is negative (-0.41); IS mean return is negative.
- Kelly fraction (f* = mu/sigma^2): NEGATIVE — strategy destroys capital in IS period.
- Recommended max position: $0 (no edge; Kelly fraction is negative)
- Binding cap: Not applicable — strategy FAILS Gate 1 with auto-disqualifications.
- Kelly flag: NOT APPLICABLE (negative IS return — no edge)

QUALITATIVE ASSESSMENT
- Economic rationale: VALID — IBS (Internal Bar Strength) is a recognized mean-reversion signal on SPY. Mechanism is economically grounded.
- Look-ahead bias: NONE DETECTED — Overfit Detector confirmed no look-ahead bias.
- Overfitting risk: HIGH — DSR z-score = -110.51 (severe), permutation p = 1.00 (no alpha), sensitivity delta 117% (far exceeds 30% threshold).

RECOMMENDATION: RETIRE H21 IBS SPY Mean Reversion. Send back to Research Director. No revision recommended.
CONFIDENCE: HIGH
CONCERNS:
- 8 auto-disqualifications triggered. IS Sharpe -0.41 is the primary failure: strategy loses money in IS.
- Root cause (per backtest): IBS mean-reversion edge on SPY appears arbitraged away in 2010–2021.
  High win rate (56.8%) but negative Sharpe due to asymmetric loss magnitude — winners are small,
  losers are larger. The regime filter is too permissive to protect the downside.
- All 4 walk-forward windows fail (0/4). OOS Sharpe 0.12 is positive but far below 0.7 threshold.
- DSR z-score -110.51 is the worst seen in our pipeline to date — severe evidence of overfitting/no alpha.
- Permutation p-value 1.00: strategy does NOT beat random entry signals at any significance level.
- Risk Director recommendation: RETIRE. No H21 v1.1 should be initiated.
  If the IBS signal is revisited, it should be as part of a multi-signal hypothesis (e.g., H24 overlay)
  under a fundamentally different framework — not a standalone H21 revision.

RETIREMENT ACTION:
- Strategy file `strategies/h21_ibs_spy_mean_reversion.py` — archive, do not deploy.
- H23 overlay integration: Research Director noted H23 Credit Spread Timer could serve as
  an H21 overlay. Given H21's retirement, H23 integration is CANCELLED. The overlay has no base strategy.
- Pipeline status: H21 RETIRED. H18 and H19 families also retired this cycle.
  Next active Gate 1 candidates: H24 Combined IBS+TOM (in backtest queue).
```

---

*Risk Director Gate 1 Verdict — agent 0ba97256 — 2026-03-16*
*Overfit Detector analysis: `backtests/H21_IBSSPYMeanReversion_2026-03-16.txt` and `.json`*
*Backtest runner output: `backtests/H21_IBSSPYMeanReversion_2026-03-16_verdict.txt`*
*Paperclip: [QUA-208](/QUA/issues/QUA-208), [QUA-217](/QUA/issues/QUA-217)*
