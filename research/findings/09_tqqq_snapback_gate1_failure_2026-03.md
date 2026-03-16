# H09 TQQQ Weekly Snapback — Gate 1 Failure Analysis & Research Director Decision

**Date:** 2026-03-16
**Tasks:** QUA-134 (Gate 1 backtest), QUA-142 (Research Director review)
**Source report:** `backtests/H09_TQQQSnapback_2026-03-16_verdict.txt`
**Outcome:** FAILED Gate 1 (9 of 13 criteria) — **ABANDONED: entry signal is statistical noise**

---

## Verdict: ABANDON — Entry Signal Has No Predictive Power

H09 fails Gate 1 on 9 criteria. Unlike H07 (where failures were mechanical and addressable), the H09 failure pattern reveals a **fundamental absence of edge**. The verdict is not revisable via parameter redesign.

### Disposition: Abandoned

The core failure is not exit logic or parameter sensitivity — it is the entry signal itself:

- **Permutation p-value = 0.988**: Entries are statistically indistinguishable from random entries. This is the definitive test: no amount of exit optimisation can rescue a strategy where entries carry zero directional information.
- **Negative Sharpe across ALL four tested regimes** (including the "favorable" COVID/stimulus period at only +0.26 — far below the 0.8 sub-period threshold).
- **No robust parameter region**: 84% Sharpe variance across the `entry_decline_pct` sweep; every parameter combination produces negative Sharpe.

---

## Full Gate 1 Scorecard

| Metric | Value | Required | Pass? |
|---|---|---|---|
| IS Sharpe | -0.47 | > 1.0 | FAIL |
| OOS Sharpe | -0.80 | > 0.7 | FAIL |
| IS Max Drawdown | -22.0% | < 20% | FAIL |
| OOS Max Drawdown | -6.7% | < 25% | PASS |
| Win Rate | 56.4% | > 50% | PASS |
| Trade Count | 252 | ≥ 100 | PASS |
| WF Windows Passed | 1/4 | ≥ 3 | FAIL |
| Regime Slice ≥ 0.8 Sharpe | 0/4 | ≥ 2 incl ≥ 1 stress | FAIL |
| Parameter Sensitivity | 84% | ≤ 30% | FAIL |
| Permutation p-value | 0.988 | ≤ 0.05 | FAIL |
| DSR | 0.000 | > 0 | FAIL |
| MC p5 Sharpe | -3.13 | Pessimistic bound | FAIL |
| WF Sharpe Min | -2.27 | — | FLAG |

---

## Root Cause Analysis

### Why the Entry Signal Has No Edge

The weekly drawdown trigger (TQQQ closes ≥N% below 5-day high) does not reliably identify rebalancing overshoot events. The failure modes:

1. **A 5–7% weekly drawdown is equally likely to be the START of a sustained decline as a temporary overshoot.** The regime gate (QQQ > 200-SMA + VIX < 30) filters some bear market drawdowns but not all.

2. **The mathematical setup is structurally negative**: A 1% TP / 2% SL requires > 66% win rate to break even. The strategy achieves 56.4% — a mathematical loss of $0.31 per dollar of gross win. This is not a tuning issue; the TASC article's "1% target" was calibrated to a cherry-picked bull regime.

3. **TASC crowding / survivorship**: The March 2026 TASC publication likely reflects substantial author curve-fitting and timing luck. Research Director explicitly warned of this in the forward review. Confirmed.

### Sub-Period Performance

| Period | Sharpe | Notes |
|---|---|---|
| post_gfc_recovery_2010_2011 | -3.10 | Severe; TQQQ was a new product, high volatility |
| china_selloff_2015_2016 | -0.58 | Drawdowns continued rather than reverting |
| q4_2018_correction | -1.75 | Sharp sell-off; no snapback |
| covid_crash_2020 | +0.42 | Only period with marginal positive performance |
| bear_2022 | -0.95 | Regime gate fires but still 8 trades, all losing |

**The COVID period (2020) is the ONLY positive window, and even then Sharpe = 0.42** — well below the sub-period threshold of 0.8. This confirms the TASC backtest was constructed around 2020–2025 bull market performance.

---

## Why Redesign Is Not Warranted

Engineering Director proposed four options: (1) redesign exit logic, (2) tighten entry criteria, (3) abandon, (4) alternative TQQQ hypothesis. Research Director evaluates each:

| Option | Assessment |
|---|---|
| Redesign exit (higher TP) | Does not fix p=0.988 entry noise. Asymmetric TP/SL improves expectancy math but requires win rate to drop proportionally with wider targets — net effect is regime-dependent, not a structural fix. |
| Tighten entry criteria | Would reduce trade count (already at lower bound with some parameter combos). Adding more filters risks further overfitting to the COVID/stimulus sub-period. |
| **Abandon H09** | **Selected.** Permutation p-value is definitive: entries carry no signal. Investment in further iteration is not justified. |
| Alt TQQQ hypothesis | Open for future consideration (see below). Not H09 — a new hypothesis with entirely different signal architecture. |

---

## Lessons Learned

1. **p-value screening should be a pre-backtest gate.** If a simple permutation test on the entry signal can be run before full backtest investment, it would have identified this failure cheaply.

2. **TASC strategy sourcing requires extra skepticism.** TASC authors have incentive to present strategies with impressive recent backtests. The TV filter's crowding-risk and cherry-picking flags were accurate.

3. **TP/SL ratio must be validated against realistic distribution, not assumed win rate.** The hypothesis assumed 56% win rate based on TASC claims; a preliminary expectancy calculation should have been required before forward.

4. **Regime gate is necessary but not sufficient.** The QQQ 200-SMA + VIX < 30 gate reduced exposure during severe drawdowns but could not rescue a signal with no directional content.

---

## Future TQQQ Consideration (H14+)

The underlying economic mechanism (leveraged ETF volatility-decay overshoot) has solid academic grounding (Cheng & Madhavan 2009, Avellaneda & Zhang 2010). The failure is in the **signal construction** (weekly high drawdown), not the mechanism.

A future hypothesis could explore:
- **VIX term-structure signal**: When VIX futures are in steep contango (tail risk priced in), TQQQ rebalancing drag is mechanically predictable. This is a different, more precise signal than a price drawdown.
- **Implied volatility mean-reversion**: Entry when TQQQ implied vol crosses above realized vol by a threshold, indicating over-pricing of tail risk.
- **Volatility-targeting overlay**: Rather than a binary entry, dynamically size TQQQ exposure based on VIX relative to 252-day mean.

**Priority:** Low. No hypothesis to be generated until H10/H11 Gate 1 results are known and pipeline velocity recovers.

---

## Research Director Sign-Off

**Decision: ABANDON H09**
**Rationale:** Entry signal is statistical noise (p=0.988). No regime-filtered variant can overcome this. Future TQQQ work may be viable with a different signal architecture but requires new hypothesis submission, not a redesign of H09.
**Pipeline status:** H10 backtest in progress (QUA-135); H11 backtest queued (QUA-136). Focus on delivering results from existing queue before commissioning new TQQQ work.

**Date:** 2026-03-16
**Reviewer:** Research Director
