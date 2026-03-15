# Hypothesis 04: Pairs Trading via Cointegration

**Status:** READY
**Category:** Statistical Arbitrage
**Source:** Quantopian Lectures
**Date:** 2026-03-15

---

## Summary

Certain pairs of stocks share a long-run equilibrium relationship (cointegration) — even if each stock trends individually, the spread between them remains mean-reverting. The strategy goes long the underperformer and short the outperformer when the spread's z-score exceeds a threshold, then exits when the spread returns to zero. Fully market-neutral by construction. Works best on fundamentally linked pairs (same sector, competitive peers, holding company / operating subsidiary).

---

## Economic Rationale

Cointegrated pairs often share a common economic driver — similar cost structures, the same end market, or one derives value from the other. When one stock deviates from the pair's historical relationship, it is typically due to transient factors (flow imbalance, index rebalancing, one-off news) rather than a permanent change in relative value. Smart money (arbitrageurs, long-short funds) recognizes this mispricing and trades the spread back to equilibrium.

The edge's source is convergence of economically linked securities. Unlike pure mean reversion (which relies on statistical properties alone), pairs trading has a fundamental anchor — there is a reason the spread should revert.

**Why the edge may erode:** As the strategy became more widely known, spreads narrowed. Modern institutional pairs trading is faster and more capital-intensive than a systematic retail approach can match. The remaining edge is in less-efficient pairs (smaller names, cross-sector cointegration) or in maintaining a large portfolio of pairs to diversify away the risk that any individual pair's cointegration breaks down.

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| Mean-reverting | Excellent — spread mean reversion is the core mechanism |
| Trending (broad market) | Good — market-neutral construction hedges broad beta |
| High volatility / crisis | Mixed — correlations spike to 1.0 in crises, which can temporarily help OR cause simultaneous movement in both legs (no spread reversion) |
| Structural breaks | Dangerous — M&A, bankruptcy, spin-offs, or sector rotations can permanently break cointegration |

**When this strategy breaks down:**
- Cointegration breakdown: pairs that were cointegrated for years can permanently diverge (e.g., a key competitor exits the market)
- Corporate events: mergers cause sudden spread collapse (may be profitable but unpredictable); bankruptcy causes one leg to go to zero
- Short borrowing costs: if the short leg has high borrow cost (hard-to-borrow stocks), the edge is consumed by fees
- Survivorship bias: historical pairs that "worked" are selected after the fact; real-time pair selection is harder

**Regime filter:** Test cointegration using the Engle-Granger or Johansen test on a rolling window. Only maintain the pair if the p-value remains below 0.05. Close the pair if cointegration breaks down.

---

## Entry / Exit Logic

**Universe selection:**
1. Screen for potential pairs: same sector + fundamental linkage (competitive peers, supplier/customer, regional bank peers, etc.)
2. Test each pair for cointegration (Engle-Granger test on residuals of price regression) using lookback_cointegration_days
3. Maintain a portfolio of 10-20 active pairs

**Spread calculation:**
- Fit hedge ratio β via OLS regression: Price_A = α + β × Price_B
- Spread = Price_A - (α + β × Price_B)
- Z-score = (Spread - mean(Spread)) / std(Spread) over lookback window

**Entry:**
- Go long A / short B when z-score < -entry_zscore (pair spread abnormally low: A cheap vs B)
- Go short A / long B when z-score > +entry_zscore (pair spread abnormally high: A expensive vs B)

**Exit:**
- Close position when z-score returns to exit_zscore (near zero = convergence)
- Stop-loss: close if z-score exceeds stop_zscore (indicates cointegration breakdown, not reversion)
- Time stop: close after max_holding_days to avoid capital lockup

**Position sizing:** Hedge-ratio adjusted dollar-neutral (equal notional exposure on each leg).

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**Asset class:** Equities — same sector pairs (e.g., Coke/Pepsi, JPM/BAC, XOM/CVX)

**PDT Rule Impact:**
- Pairs trades are typically held 5-30 days — **PDT is generally manageable** at this time frame
- With 10-20 active pairs, opening/closing several positions per week is possible
- At $25K, keeping 10 active pairs means ~$2,500 per pair ($1,250 per leg), which is viable but thin on liquidity
- 3 round-trips/week across 10 pairs = 0.3 trades/pair/week — very achievable

**$25K capital constraints:**
- 10-20 pairs requires short positions — needs margin account
- At $25K with Reg T (50% margin for shorts): $25K equity supports ~$50K of total exposure (long + short)
- 10 pairs × $2,500/leg × 2 legs = $50K notional — at the absolute edge of margin capacity
- **Practical recommendation:** Start with 5-8 pairs maximum at $25K, with larger position sizes per pair
- Short borrowing fees on small-cap pairs can be material — prioritize large-cap, liquid pairs

**Trade frequency:** Low-medium (average hold 5-30 days, ~5-15 trades/month across portfolio). PDT limit manageable.

---

## Gate 1 Assessment

| Criterion | Assessment | Notes |
|-----------|------------|-------|
| IS Sharpe > 1.0 | **LIKELY PASS** | Historical Sharpe 1.3; stable strategy when pairs remain cointegrated |
| OOS Sharpe > 0.7 | **LIKELY PASS** | Strategy is relatively regime-independent; OOS consistency expected |
| IS Max Drawdown < 20% | **LIKELY PASS** | Historical MDD ~8%; cointegration breakdown stops prevent large drawdowns |
| Win Rate > 50% | **LIKELY PASS** | Mean reversion strategy; win rates typically 55-65% |
| Trade Count > 50 | **LIKELY PASS** | Portfolio of 10 pairs over 5 years easily generates 50+ completed trades |
| Parameter Sensitivity | **LIKELY PASS** | Lookback and zscore thresholds are relatively robust per KB data |
| Survivorship Bias Risk | **FLAG** | Must use point-in-time data for pair selection; cannot select pairs using hindsight |

**Overall Gate 1 Outlook:** **Favorable** — this is one of the stronger candidates alongside Bollinger Band mean reversion. Key risks are (1) survivorship bias in pair selection (must be addressed in backtest methodology) and (2) practical $25K margin constraints for live trading. The low historical MDD is attractive.

---

## Recommended Parameter Ranges for First Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| lookback_cointegration_days | 252 | [126, 189, 252, 378, 504] | Medium |
| entry_zscore | 2.0 | [1.5, 1.75, 2.0, 2.25, 2.5] | High |
| exit_zscore | 0.0 | [-0.5, 0.0, 0.5] | Low |
| stop_zscore | 3.5 | [3.0, 3.5, 4.0] | Medium |
| max_holding_days | 30 | [15, 20, 30, 45, 60] | Low |

**Suggested starting pairs (high liquidity, fundamental linkage):**
- XOM / CVX (oil majors)
- JPM / BAC (large-cap banks)
- KO / PEP (beverage peers)
- GS / MS (investment banks)
- AMZN / MSFT (cloud platform peers — less traditional but worth testing)

**Backtest methodology note:** Pair selection must use only data available at each point in time (no look-ahead in cointegration testing). This is a known source of backtest bias and must be explicitly verified by the Overfit Detector.

**Backtest period:** 2018-01-01 to 2023-12-31.

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS.

**Free parameters:** 5 (within Gate 1 limit of 6).
