# Gate 1 Acceptance Criteria — Backtest Qualification

**Version:** 1.3
**Locked by:** CEO
**Date:** 2026-03-16
**Change log:** v1.1 — Added Regime-Slice Sub-Criterion per QUA-133 analysis (Risk Director). Addresses regime-contamination pattern observed in H07 and H08 Gate 1 failures.
v1.2 — Added Pattern-Based Strategy Exception per QUA-152 review.
v1.3 — Added REGIME_CASH Walk-Forward Exemption per QUA-294/QUA-295 (H36b Gate 1 review).
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

### Regime-Slice Sub-Criterion (IS Window)

To prevent aggregate IS Sharpe from being inflated by a single extraordinary regime, strategies must pass a per-regime validation within the IS window.

**Regime windows (aligned with IS period 2018–2023):**

| Regime | Date Range | Character |
|--------|-----------|----------|
| Pre-COVID | 2018–2019 | Normal bull market, low realized vol |
| Stimulus era | 2020–2021 | COVID crash recovery + historic stimulus rally |
| Rate-shock | 2022 | Aggressive Fed tightening, multi-asset drawdown |
| Normalization | 2023 | Post-tightening stabilization |

**Requirement:**
- Achieve IS Sharpe ≥ 0.8 in **at least 2 of 4 sub-regimes**
- At least one passing regime must be a **stress regime** (Stimulus era OR Rate-shock)

**Assessability guard:**
If a strategy has fewer than 10 trades in a sub-regime window, that sub-regime is marked "insufficient data" and excluded from the 2/4 count. If fewer than 2 sub-regimes are assessable, the strategy must achieve higher trade frequency before Gate 1 consideration.

**This sub-criterion is additive to — not a replacement for — the aggregate IS Sharpe > 1.0 threshold.**
A strategy passing 2/4 sub-regimes while failing aggregate IS Sharpe > 1.0 is automatically rejected.

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

### Walk-Forward REGIME_CASH Exemption

A walk-forward OOS window that produces **zero trades** because a regime filter (e.g., 200-SMA, VIX threshold, volatility filter) correctly placed the strategy in **CASH** during a known drawdown period (bear market, crash) is **exempt from the "strategy passes in ≥ 3 of 4 walk-forward windows" requirement** under the following conditions:

1. The regime filter's cash signal is confirmed to cover the OOS window dates (e.g., BTC 200-SMA regime cash from 2022–2023).
2. The drawdown avoided by the regime filter is documented and exceeds **30%** in the underlying asset during the OOS window.
3. The Engineering Director explicitly flags the windows as REGIME_CASH in the verdict file and calculates WF windows excluding exempt windows.
4. At least **2 non-exempt** walk-forward windows pass (i.e., regime-cash exemption cannot waive the requirement for all 4 windows).

**Rationale:** A strategy that correctly avoids a catastrophic drawdown through regime detection is functioning as designed. Penalizing zero-trade windows in these periods creates a perverse incentive to disable effective regime filters.

**Governance:** REGIME_CASH exemption must be explicitly requested in the verdict file and confirmed by the Risk Director. CEO acknowledgment required on first application per asset class.

**Asset class precedent:**
- Crypto (BTC 200-SMA): CEO-ratified 2026-03-16 (QUA-294). 2022–2023 crypto bear market qualifies as a REGIME_CASH exemption period when the BTC 200-SMA filter places the strategy in cash.

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

## Pattern-Based Strategy Exception

Applies to strategies that use **binary, sparse, event-driven signals** (e.g., support/resistance zone patterns, candlestick patterns, breakout flags) where the signal fires ≤ 20 times/year per asset. Standard continuous-factor IC is not applicable to these strategies.

**Eligibility:** A strategy qualifies as Pattern-Based if:
- Signal fires ≤ 20 times/year per asset on average
- Signal is binary (0 = no trade, 1 = enter)
- No continuous factor ranking or scoring is used

**IC substitute (approved for Pattern-Based strategies only):**

| Standard criterion | Substitute for pattern-based | Threshold |
|---|---|---|
| Spearman IC > 0.02 | Zone-touch directional accuracy (hit rate at T+5) | ≥ 55%, binomial p-value < 0.15, n ≥ 50 |

**MC p5 and Permutation override (when trade count < 100):**

Both MC p5 Sharpe and permutation p-value criteria are overridden when **all three** of the following conditions hold:
1. IS trade count < 100
2. Block bootstrap CI on daily returns is **fully positive** (lower bound > 0)
3. DSR > 0 (Deflated Sharpe Ratio confirms edge is not due to luck from multiple comparisons)

When these conditions hold, the block bootstrap CI on daily returns is the authoritative statistical test. The rationale: at n < 100, permutation tests and Monte Carlo bootstraps of sparse event PnLs produce unstable distributions that generate false negatives even for genuine signals.

**Governance:** Pattern-Based Exception may only be applied with:
1. Engineering Director explicit sign-off in the verdict file
2. Research Director confirmation in a QUA issue comment
3. CEO ratification in version history (this section)

Both standard verdict format fields (MC p5, Permutation p-value) must still be reported — they are marked EXCEPTION rather than PASS/FAIL.

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
- Fails regime-slice sub-criterion: fewer than 2 of 4 assessable sub-regimes achieve IS Sharpe ≥ 0.8, OR no stress regime (Stimulus era / Rate-shock) is among the passing regimes

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
- Regime-slice (Pre-COVID 2018–2019 IS Sharpe): [X.XX or N/A]  [PASS/FAIL/N/A]
- Regime-slice (Stimulus era 2020–2021 IS Sharpe): [X.XX or N/A]  [PASS/FAIL/N/A]
- Regime-slice (Rate-shock 2022 IS Sharpe): [X.XX or N/A]  [PASS/FAIL/N/A]
- Regime-slice (Normalization 2023 IS Sharpe): [X.XX or N/A]  [PASS/FAIL/N/A]
- Regime-slice overall: [X of 4 assessable regimes passed, stress regime included Y/N]  [PASS/FAIL]

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

### Version History

| Version | Date | Change | Rationale |
|---------|------|--------|-----------|
| 1.0 | 2026-03-15 | Initial criteria locked | Baseline Gate 1 standards |
| 1.1 | 2026-03-16 | Added Regime-Slice Sub-Criterion | H07 and H08 failures revealed regime-contamination pattern: aggregate IS Sharpe inflated by single extreme regime. New sub-criterion requires IS Sharpe ≥ 0.8 in ≥ 2 of 4 sub-regimes, with at least one stress regime passing. Proposed by Risk Director (QUA-133), approved by CEO (QUA-127). |
| 1.2 | 2026-03-16 | Added Pattern-Based Strategy Exception | H10 EQL/EQH v2 review (QUA-152) revealed IC > 0.02 threshold is methodologically incompatible with binary sparse pattern signals (signal flat on ~99% of days forces IC → 0 regardless of actual predictive power). Research Director approved IC substitute (zone-touch directional accuracy ≥ 55%, n ≥ 50) and MC/permutation override for IS trade count < 100 backed by fully positive block bootstrap CI and DSR > 0. Engineering Director proposed formalizing for reuse (QUA-159). CEO ratified 2026-03-16. |
| 1.3 | 2026-03-16 | Added REGIME_CASH Walk-Forward Exemption | H36b Gate 1 review (QUA-295) identified a gap: WF windows where the strategy is correctly in CASH during a bear market (regime filter functioning as designed) produced zero OOS trades, causing a WF FAIL despite the filter doing its job. Risk Director and Engineering Director recommended formalizing an exemption. CEO ratified 2026-03-16 (QUA-294). Requires: drawdown avoided ≥ 30%, Engineering Director flags windows, Risk Director confirms, ≥ 2 non-exempt windows still pass. First precedent: Crypto (BTC 200-SMA) 2022–2023 bear market. |

---

*This document is the binding reference for all Gate 1 decisions. Agents may reference it; only the CEO may change it.*
