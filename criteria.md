# Gate 1 Acceptance Criteria — Backtest Qualification

**Version:** 1.0
**Locked by:** CEO
**Date:** 2026-03-15
**Status:** LOCKED — only the CEO may modify these criteria after lock.

---

## Purpose

Gate 1 is the first quality checkpoint in the strategy promotion pipeline. A strategy must pass Gate 1 before it is eligible for paper trading. These criteria exist to ensure that only strategies with genuine, robust edges advance — not statistical artifacts or curve-fitted noise.

The Overfit Detector agent is responsible for evaluating strategies against these criteria and producing a pass/fail recommendation. The CEO makes the final promotion decision at Gate 1 review.

---

## Required Test Period

| Parameter | Requirement | Rationale |
|-----------|-------------|-----------|
| Minimum backtest length | **5 years** (2018–2023) | Must include crypto winter (2018), COVID crash and recovery (2020), 2022 rate hike cycle. Shorter periods miss the full regime cycle. |
| Walk-forward periods | **Minimum 4 non-overlapping windows** | One or two windows is insufficient for statistical confidence. |
| Walk-forward split | **36-month in-sample / 6-month out-of-sample** | Standard split balancing training data vs. validation signal. |

---

## Quantitative Thresholds

### Returns and Risk-Adjusted Performance

| Metric | Minimum (Pass) | Target | Notes |
|--------|---------------|--------|-------|
| In-Sample (IS) Sharpe Ratio | **> 1.0** | > 1.5 | Annualized, risk-free rate assumed 0% for simplicity |
| Out-of-Sample (OOS) Sharpe Ratio | **> 0.7** | > 1.0 | OOS is the real test; IS Sharpe alone means nothing |
| Walk-forward consistency | **OOS Sharpe within 30% of IS Sharpe** | Within 20% | If OOS degrades sharply vs IS, the strategy is overfit |
| Deflated Sharpe Ratio (DSR) | **> 0** | > 0.5 | Adjusts for multiple comparisons / number of variants tested. DSR ≤ 0 means the Sharpe is likely due to luck. |

### Drawdown

| Metric | Maximum (Pass) | Notes |
|--------|---------------|-------|
| In-Sample Max Drawdown | **< 20%** | Absolute floor. Strategies near 20% are flagged for closer review. |
| Out-of-Sample Max Drawdown | **< 25%** | OOS drawdown is allowed slightly more slack due to smaller sample; however, if OOS drawdown exceeds IS drawdown by more than 10 percentage points, require explanation. |

### Win Rate and Trade Quality

| Metric | Minimum (Pass) | Notes |
|--------|---------------|-------|
| Win rate | **> 50%** | Baseline edge requirement. Win rate alone is insufficient — must be combined with favorable risk/reward. |
| Average win / average loss ratio | **> 1.0** | A 50% win rate with 1:1 reward-risk breaks even. Prefer win rate > 50% OR reward/risk > 1.2. |
| Minimum trade count (IS period) | **> 50 trades** | Fewer than 50 trades yields unreliable statistics. For low-frequency strategies, require minimum 30 trades in each walk-forward OOS window. |

### Parameter Robustness

| Metric | Requirement | Notes |
|--------|-------------|-------|
| Parameter sensitivity | **No cliff edges** | A ±20% change in any parameter must cause < 30% change in Sharpe Ratio. If one parameter controls the entire edge, the strategy is overfit to that value. |
| Parameter count | **≤ 6 free parameters** | More parameters = more degrees of freedom = higher overfitting risk. Strategies with > 6 parameters require explicit CEO approval. |
| Robustness score | **Pass in ≥ 3 of 4 walk-forward windows** | A strategy that passes only in one or two windows is likely a regime bet, not a universal edge. |

---

## Qualitative Requirements

These cannot be automated — the CEO and Overfit Detector must assess them at Gate 1 review:

1. **Economic rationale:** The strategy must have a plausible explanation for *why* the edge exists. "The backtest is good" is not a rationale. Example of acceptable rationale: "Momentum persists due to behavioral underreaction to news." Data mining without a hypothesis is rejected.

2. **No look-ahead bias:** The strategy code must be reviewed to confirm no future data is used in signal generation. The Overfit Detector must explicitly certify this.

3. **Realistic transaction costs:** Backtests must include commissions and slippage estimates:
   - Equities/ETFs: $0.005/share + 0.05% slippage assumption
   - Options: $0.65/contract + 0.10% slippage
   - Crypto: 0.10% taker fee + 0.05% slippage
   If the strategy fails after costs, it does not pass.

4. **No overfitting flags:** The Overfit Detector must produce an explicit overfitting risk assessment. Strategies rated "high overfitting risk" require a second review before CEO considers promotion.

---

## Asset-Class Constraints

### Equities and ETFs
- Minimum stock price: $10
- Minimum average daily volume: 500,000 shares
- No earnings-week entries (earnings are binary risk; exclude ±5 days around earnings)
- PDT compliance: strategy must be implementable with ≤ 3 round trips per week (swing trades preferred)

### Options
- Defined-risk strategies only (no naked options)
- Minimum 30 DTE on entry
- Close rule must be specified (e.g., 50% profit or 21 DTE)
- Backtest must model theta decay explicitly, not just entry/exit prices

### Crypto
- BTC and ETH only for systematic strategies (altcoins lack sufficient history)
- Maximum 2x leverage
- Crypto winter (2018) must be included in test period — any strategy that didn't survive 2018 does not pass

---

## Automatic Disqualification (Any Single Flag = Reject)

- IS Sharpe < 1.0
- OOS Sharpe < 0.7
- DSR ≤ 0
- Max drawdown exceeds IS threshold (> 20%)
- Look-ahead bias detected (automatic reject — strategy must be rewritten and re-tested from scratch)
- Fewer than 50 trades in IS period
- Strategy fails after realistic transaction costs
- Strategy passes in fewer than 3 of 4 walk-forward windows

---

## Pass/Fail Verdict Format

The Overfit Detector must produce a verdict in this format:

```
GATE 1 VERDICT: [PASS / FAIL / CONDITIONAL PASS]
Strategy: [name and version]
Date: [date]

QUANTITATIVE SUMMARY
- IS Sharpe: [X.XX]  [PASS/FAIL, threshold 1.0]
- OOS Sharpe: [X.XX]  [PASS/FAIL, threshold 0.7]
- Walk-forward consistency: [X.XX ratio]  [PASS/FAIL, threshold < 30% degradation]
- IS Max Drawdown: [XX.X%]  [PASS/FAIL, threshold 20%]
- OOS Max Drawdown: [XX.X%]  [PASS/FAIL, threshold 25%]
- Win Rate: [XX.X%]  [PASS/FAIL, threshold 50%]
- Deflated Sharpe Ratio: [X.XX]  [PASS/FAIL, threshold 0]
- Parameter sensitivity: [PASS/FAIL]
- Walk-forward windows passed: [X/4]  [PASS/FAIL, threshold 3/4]
- Post-cost performance: [PASS/FAIL]

QUALITATIVE ASSESSMENT
- Economic rationale: [VALID / WEAK / MISSING]
- Look-ahead bias: [NONE DETECTED / WARNING / DETECTED]
- Overfitting risk: [LOW / MEDIUM / HIGH]

RECOMMENDATION: [Promote to paper trading / Send back for additional testing / Reject]
CONFIDENCE: [HIGH / MEDIUM / LOW]
CONCERNS: [list any specific concerns, even if passing]
```

A "CONDITIONAL PASS" is permitted only when a strategy passes all quantitative thresholds but has a qualitative concern. The CEO must explicitly acknowledge the concern before promotion.

---

## Governance

- These criteria were set by the CEO on 2026-03-15.
- Only the CEO can modify these criteria, and only after a formal review with documented rationale.
- Any change to criteria must be versioned (increment version number, preserve prior version in git history).
- Relaxing criteria requires higher justification than tightening them.
- If no strategies pass for 20+ consecutive iterations, the CEO will review whether criteria are too strict — but will not relax them without data showing the criteria are generating false negatives.

---

*This document is the binding reference for all Gate 1 decisions. Agents may reference it; only the CEO may change it.*
