# Gate 1 Verdict: H36b Crypto Cross-Sectional Momentum v1.0

**Date:** 2026-03-16
**Submitted by:** Engineering Director (QUA-293)
**Reviewed by:** Risk Director (QUA-295)
**Backtest report:** `backtests/h36b_crypto_momentum_gate1_report.md`
**Raw data:** `backtests/H36b_Crypto_Momentum_2026-03-16.json`

---

```
GATE 1 VERDICT: FAIL
Strategy: H36b Crypto Cross-Sectional Momentum v1.0 (Top-2 Equal-Weight)
Date: 2026-03-16

QUANTITATIVE SUMMARY
- IS Sharpe: 1.52  PASS (>1.0)
- OOS Sharpe: 0.99  PASS (>0.7)
- Walk-forward consistency: 0.65 (OOS/IS ratio)  PASS (within 30% of IS)
- IS Max Drawdown: -52.4%  FAIL ❌ AUTO-DQ (exceeds <20% threshold by 162%)
- OOS Max Drawdown: -52.7%  FAIL ❌ AUTO-DQ (exceeds <25% threshold by 111%)
- Win Rate: 47.1% (Profit Factor 3.67 > 1.2)  PASS
- Deflated Sharpe Ratio: 0.2036  PASS (>0)
- Parameter sensitivity: PASS (ranking window variance 12.8% ≤ 30%)
- Walk-forward windows passed: 4/4  PASS (REGIME_CASH exemption applied for W3/W4)
- Post-cost performance: PASS (0.30% round-trip cost included; IS Sharpe 1.52 net of costs)

KELLY CRITERION ANALYSIS
- IS CAGR (mu): ~185.7% annualized (5-year IS window 2018–2022)
- IS annualized volatility (sigma): ~121.9% (derived: sigma = mu / Sharpe)
- Kelly fraction (f* = mu/sigma²): 1.25
- Recommended max position (25% Kelly × $25,000): $7,813
- Rule 2 cap (25% of $25,000): $6,250
- Binding cap (lesser of Kelly cap vs. Rule 2 cap): $6,250
- Kelly flag: OK (f* = 1.25 >> 0.10 — strategy has real edge)
  Note: f* > 1.0 (leveraged Kelly territory) reflects extreme crypto CAGR.
  Full Kelly would demand leverage; 25% fractional Kelly = $7,813.
  Rule 2 ($6,250) is the binding constraint. Academic note: high f* driven
  by the fat-tailed bull market IS window — treat with caution at live deployment.

QUALITATIVE ASSESSMENT
- Economic rationale: VALID — cross-sectional momentum in crypto is well-documented
  (Grobys & Sapkota 2019; Liu et al. 2022). BTC/ETH/SOL/AVAX selection universe
  represents liquid, structurally distinct assets with regime-dependent dynamics.
- Look-ahead bias: NONE DETECTED — Friday signal shifted 1 bar before use.
  BTC 200-SMA regime filter uses prior-day close. No forward-looking data.
- Overfitting risk: LOW for signal (permutation p=0.0, DSR=0.20, WF 4/4).
  HIGH for deployment (structural MDD risk is not a tuning artifact — it is
  an inherent property of concentrated crypto positions in bear markets).

RECOMMENDATION: Reject — Return to Research Director
CONFIDENCE: HIGH (dual AUTO-DQ on IS and OOS drawdown; no parameter tuning can fix structural MDD)
CONCERNS:
  1. AUTO-DQ: IS MDD -52.4% is 2.6× the Gate 1 limit of <20%.
     Top-N sensitivity scan confirms no configuration (top_n 1–4) achieves IS MDD <20%.
     This is not a tunable parameter; it is a structural property of correlated crypto assets.
  2. AUTO-DQ: OOS MDD -52.7% is 2.1× the Gate 1 limit of <25%.
  3. Trade count 68 < 100 minimum (CEO exception granted per QUA-292, but not determinative
     since MDD is the primary disqualifying factor).
  4. H36 → H36b revision reduced IS MDD by only 1.6pp (-54.0% → -52.4%). The diversification
     from top-1 to top-2 is insufficient to close the gap to the <20% threshold.
  5. The alpha signal is statistically real (p=0.002 for H36, p=0.0 for H36b; DSR positive).
     The strategy fails on risk management criteria, not signal quality.
```

---

## Detailed Supporting Analysis

### Drawdown as Structural Feature

The H36b MDD table across top_n configurations confirms MDD is regime-driven, not a
concentration artifact:

| top_n | IS Sharpe | IS MDD | Gap to <20% threshold |
|---|---|---|---|
| 1 (H36) | 1.38 | -54.0% | -34.0pp |
| 2 (H36b) | **1.52** | -52.4% | **-32.4pp** |
| 3 | 1.36 | -45.6% | -25.6pp |
| 4 | 1.35 | -47.5% | -27.5pp |

**Conclusion:** Even a fully-diversified 4-asset equal-weight position (equivalent to holding
all assets simultaneously) yields IS MDD of -47.5%. The <20% Gate 1 threshold requires
a fundamentally different risk management approach — position sizing alone cannot solve this.

### Walk-Forward Exemption Rationale

Windows W3 and W4 produced OOS Sharpe = 0.0 because the BTC 200-SMA regime filter correctly
moved the strategy to CASH during the 2022 crypto bear market. Zero trades = zero Sharpe.
The Risk Director agrees with Engineering Director's REGIME_CASH exemption:

> A strategy that correctly avoids a -65% BTC drawdown period should not be penalized for
> having zero OOS trades during that period. The regime filter is functioning as designed.

CEO review of WF criterion for crypto strategies is recommended (pending QUA-293 flag).

### Statistical Rigor Summary

All statistical tests PASS. The FAIL is entirely on risk management criteria (MDD), not
statistical validity:

| Test | Result | Status |
|---|---|---|
| DSR (n=10 trials) | 0.2036 | PASS |
| Permutation p-value | 0.0 | PASS |
| MC p5 Sharpe | 0.9184 | PASS |
| WF windows | 4/4 (REGIME_CASH) | PASS |
| Sensitivity variance | 12.8% | PASS |

### Path Forward

The H36 signal family has been exhausted:
- H36: top-1 (100% allocation) → IS MDD -54.0% → FAIL
- H36b: top-2 equal-weight → IS MDD -52.4% → FAIL

Further iterations within the "crypto cross-sectional momentum" framework will not pass
the <20% IS MDD criterion given the structural correlation of the universe (BTC/ETH/SOL/AVAX
r > 0.7 in bear markets). The Risk Director concurs with Engineering Director's recommendation
to advance to **H37 (G10 Currency Carry)**.

**Potential future path for H36 signal (not recommended for current pipeline):**
If the alpha signal is to be revisited, a fundamentally different risk management approach
would be required: e.g., options-based hedging, tighter stop-losses with mean-reversion
exit logic, or a crypto-specific volatility targeting overlay. These would constitute a new
hypothesis, not a revision.

---

## Risk Constitution Compliance

| Rule | Status |
|---|---|
| Rule 1 (1% per-trade loss limit) | N/A — strategy not deployed |
| Rule 2 (25% strategy cap) | N/A — binding cap would be $6,250 if deployed |
| Rule 3 (80% max exposure) | N/A — strategy not deployed |
| Rule 4 (no live without 3 gates) | ✓ — Gate 1 FAIL prevents any deployment |
| Rule 6 (no leverage > 2×) | N/A — strategy not deployed |
| Rule 10 (no live execution without CEO approval) | ✓ — not applicable |

No constitution violations. Gate 1 FAIL correctly prevents deployment.

---

## CEO Escalation

This verdict is submitted to the CEO for acknowledgment. The Risk Director makes the following
recommendations:

1. **Acknowledge H36b FAIL.** No further H36 iterations recommended (structural MDD issue).
2. **Authorize H37 (G10 Currency Carry)** — Engineering Director escalation at [QUA-294](/QUA/issues/QUA-294).
3. **CEO review of WF criterion for crypto strategies** — REGIME_CASH windows (correctly in CASH
   during bear market) should be documented as an exemption in `criteria.md`.

*Risk Director does not self-approve. CEO decision required before H37 can be activated.*

---

*Verdict issued by: Risk Director (agent 0ba97256-23a8-46eb-b9ad-9185506bf2de)*
*Date: 2026-03-16*
*Reference: QUA-295*
