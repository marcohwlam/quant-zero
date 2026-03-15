# Hypothesis 03: Multi-Factor Long-Short Equity

**Status:** READY
**Category:** Factor / Statistical Arbitrage
**Source:** Quantopian Contest (archetype strategy)
**Date:** 2026-03-15

---

## Summary

Combines multiple orthogonal alpha factors (value, momentum, quality) into a composite ranking of stocks. Buys the top decile (highest-scoring stocks) and shorts the bottom decile (lowest-scoring stocks) with sector-neutral, dollar-neutral construction. Hedges broad market risk and isolates stock-specific alpha. Was the dominant strategy in the Quantopian contest era (2010-2018) but has seen alpha decay due to factor crowding.

---

## Economic Rationale

**Value factor:** Cheap stocks (low P/E, P/B, P/S) outperform expensive stocks over long horizons because markets persistently overreact to growth expectations, creating mean reversion in valuation multiples (behavioral overreaction).

**Momentum factor:** Recent winners tend to continue outperforming due to underreaction — investors anchored to prior prices don't fully adjust to new information, creating persistent price momentum.

**Quality factor:** High-quality firms (high ROE, low leverage, stable earnings) outperform because their superior fundamentals are systematically undervalued by markets pricing in mean reversion that doesn't materialize.

**Combining factors:** The three factors are partially uncorrelated. Value and momentum are often negatively correlated (cheap stocks are often recently beaten down; winners are often expensive). The composite factor diversifies across these drivers, providing more stable alpha than any single factor.

**Long-short construction:** By going long top decile and short bottom decile, the strategy hedges market beta and sector exposures, theoretically isolating pure stock-selection alpha.

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| All regimes (by design) | Strategy is designed to be market-neutral — hedged beta |
| Factor-crowded / low-dispersion | Poor — if everyone uses the same factors, spreads narrow |
| Crisis / deleveraging | Dangerous — forced selling causes correlated unwinds; long-short books can lose simultaneously |
| Post-crisis recovery | Mixed — value factor may lag if "value traps" persist |

**When this strategy breaks down:**
- Factor crowding events: 2018-2019 momentum crash, 2020 COVID rotation caused large factor drawdowns
- Short squeezes: bottom-decile shorts (often recent losers / low-quality stocks) can spike violently on news
- Deleveraging: in a crisis, the long leg falls (investors sell quality) while the short leg rises (short squeezes)

**Critical caveat for Gate 1:** Historical Sharpe 1.8 was recorded on 2010-2018 data. Performance degraded substantially post-2018 due to factor crowding. Gate 1 requires 2018-2023 data — the backtest may fail to replicate historical performance given the post-2018 decay. This must be disclosed and verified.

---

## Entry / Exit Logic

**Universe:** S&P 500 (or Russell 1000) constituents — liquid, large-cap for borrowability on short side

**Factor computation (weekly/monthly):**
1. **Value score:** rank stocks by P/E, P/B, EV/EBITDA (lower multiple = higher score). Normalize to z-score.
2. **Momentum score:** rank by 12-month price return (excluding most recent month). Normalize to z-score.
3. **Quality score:** rank by ROE, debt-to-equity, earnings stability. Normalize to z-score.
4. **Composite score:** weighted average (default: 1/3 each). Normalize final composite to z-score.

**Entry:**
- Long top decile (composite z-score highest 10% of universe)
- Short bottom decile (composite z-score lowest 10% of universe)
- Rebalance on monthly schedule (day 1 of each month, or 21-day rolling)
- Sector-neutral: match sector weights in long and short legs

**Exit:**
- Position exits when stock falls out of its decile at rebalance
- Hard stop: exit individual position if it moves > 5% against expectation in a single day (idiosyncratic news)

**Sizing:** Equal-weight within each leg. Dollar-neutral (equal $ long and $ short). Max single position 2% of portfolio.

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**Asset class:** S&P 500 equities

**PDT Rule Impact:**
- Monthly rebalance means most trades happen once a month — **PDT is generally not a constraint** at this frequency
- However, if the strategy trades weekly, and multiple positions are adjusted each week, PDT can become a binding constraint at $25K
- With 50 positions per leg (100 total) and monthly rebalance, turnover is 20-30 trades/month — well within PDT limits spread over a month

**$25K capital constraints (SIGNIFICANT CONCERNS):**
- Long-short with 100 positions requires $250 per position on $25K — **impractical at this scale**
- Short-selling requires borrowing (Reg T margin) — needs a margin account
- At $25K, a viable scaled version: 10-15 long positions, 10-15 short positions, larger weights per position
- Preferred: **long-only factor portfolio** as the $25K-compatible version (sacrifices market neutrality)
- True long-short at $25K is structurally difficult: borrow fees, margin calls, and position minimums create friction

**Recommendation for $25K:** Test the full long-short model in backtest for Gate 1 qualification, but note that live trading at $25K would use a long-only factor portfolio (top quintile only) as the implementable version.

**Trade frequency:** Low-medium (monthly rebalance, ~20-30 trades/month). PDT not a concern at monthly cadence.

---

## Gate 1 Assessment

| Criterion | Assessment | Notes |
|-----------|------------|-------|
| IS Sharpe > 1.0 | **AT RISK (post-2018)** | Historical 1.8 was on 2010-2018 data; must test 2018-2023 which is in-scope for Gate 1 |
| OOS Sharpe > 0.7 | **AT RISK** | Factor decay post-2018 may cause both IS and OOS to underperform history |
| IS Max Drawdown < 20% | **LIKELY PASS** | Historical MDD ~10%; factor crowding events may push this higher in 2018-2023 |
| Win Rate > 50% | **UNCERTAIN** | Factor strategies don't naturally map to win-rate; depends on rebalance cadence |
| Trade Count > 50 | **PASS** | 100+ positions rebalancing monthly generates thousands of trades in 5 years |
| Parameter Sensitivity | **LIKELY PASS** | Factor weights are relatively low-sensitivity (diversified drivers) |
| $25K Implementation | **CONCERN** | Full long-short is impractical at $25K; must note this caveat |

**Overall Gate 1 Outlook:** **Uncertain** — the strategy has the best historical pedigree but the highest uncertainty around post-2018 performance decay. Gate 1 testing on 2018-2023 will be the real test of whether this strategy retains viability. The $25K implementation concern is a practical blocker for live trading even if Gate 1 is passed.

---

## Recommended Parameter Ranges for First Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| value_weight | 0.33 | [0.0, 0.25, 0.33, 0.50, 1.0] | Low |
| momentum_weight | 0.33 | [0.0, 0.25, 0.33, 0.50, 1.0] | Low |
| quality_weight | 0.33 | [0.0, 0.25, 0.33, 0.50, 1.0] | Low |
| rebalance_freq (days) | 21 | [5, 10, 21, 42, 63] | Medium |
| long_short_percentile | 10 | [5, 10, 15, 20] | Medium |

**Constraint:** value + momentum + quality weights must sum to 1.0.

**Data requirement:** Fundamental data (P/E, P/B, ROE, debt-to-equity, earnings) required in addition to price data. Engineering Director must confirm data availability before backtest begins.

**Backtest period:** 2018-01-01 to 2023-12-31 (covers the factor decay period — critical for honest assessment).

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS.

**Free parameters:** 5 (within Gate 1 limit of 6, but note factor weights are constrained to sum to 1).
