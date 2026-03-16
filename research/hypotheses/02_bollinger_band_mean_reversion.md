# Hypothesis 02: Bollinger Band Mean Reversion

**Status:** FAILED
**Category:** Mean Reversion
**Source:** Quantopian Lectures
**Date:** 2026-03-15

---

## Summary

When prices deviate significantly from their recent moving average (beyond 2 standard deviations, as measured by Bollinger Bands), they tend to revert toward the mean. The strategy buys extreme lows (below the lower band) and shorts extreme highs (above the upper band), exiting at the midpoint. Works best on liquid instruments in range-bound regimes where no fundamental catalyst has caused the deviation.

---

## Economic Rationale

Mean reversion exists because short-term price extremes are often caused by temporary imbalances in liquidity (large block orders, forced selling/buying) rather than fundamental value changes. Market makers and arbitrageurs step in to provide liquidity at extreme prices, pushing prices back toward fair value. The Bollinger Band framework quantifies "extreme" in a statistically principled way (standard deviations from a rolling mean), making it more robust than fixed-threshold rules.

The edge is strongest when:
1. The deviation is not driven by fundamental news (earnings, macro events)
2. The instrument has high liquidity and active market making
3. The universe is diversified (portfolio of 20+ names diversifies away idiosyncratic blow-up risk)

**Why the edge persists:** While well-known, mean reversion at the portfolio level is harder to arbitrage than it appears — you need enough capital to take many simultaneous positions, tolerate short-term mark-to-market losses, and manage the occasional "deviation that doesn't revert" (trend continuation).

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| Mean-reverting / choppy | Excellent — core regime for this strategy |
| Trending (mild) | Degraded — longs into downtrends keep deepening |
| Trending (strong) | Poor — price can stay outside bands for extended periods; catastrophic longs |
| High volatility / crisis | Dangerous — band widening generates fewer signals, but those that fire may be regime breaks |

**When this strategy breaks down:**
- Sustained trends: price stays below lower band for weeks/months (e.g., 2022 bear market)
- Earnings surprises: fundamental re-rating makes mean reversion invalid
- Sector rotation events: the "mean" itself is shifting

**Regime filter recommendation:** Only activate this strategy when the broad market regime is "mean-reverting" (e.g., VIX between 15-25, 200d SMA relatively flat). Reduce or suspend positions when VIX > 30 or when the instrument is in a confirmed downtrend.

---

## Entry / Exit Logic

**Entry (Long):**
1. Compute rolling mean (SMA) and Bollinger Bands: mean ± (entry_std × rolling_std) over lookback_period days
2. Buy when close crosses below the lower band (mean - entry_std × std)
3. Filter: skip if the move is earnings-related (no entry within ±5 days of earnings date)
4. Filter: skip if market regime is "trending" per regime overlay

**Entry (Short — optional, for accounts with margin):**
- Mirror: sell short when close crosses above the upper band (mean + entry_std × std)

**Exit:**
- Primary: exit when price returns to the midline (middle band / SMA)
- Time stop: exit after max_holding_days if midline not reached (prevents capital lockup)
- Stop loss: exit immediately if price crosses 3× std from mean (indicates trend continuation, not reversion)

**Position sizing:** Size inversely proportional to distance from band — larger when the deviation is greater (but cap at a maximum per-position limit to avoid over-concentration in runaway trends).

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**Asset class:** Liquid large-cap equities or sector ETFs

**PDT Rule Impact:**
- Mean reversion signals can fire frequently on individual stocks — **PDT is a meaningful constraint** at $25K
- Holding period averages 3-8 days; if multiple simultaneous positions are opened and closed, the 3 round-trip/week limit can be approached
- **Mitigation:** Use ETFs as the primary universe (less frequent signals per instrument), or target a holding period of 5+ days to stay well inside PDT limits
- Alternative: trade only 1-2 positions simultaneously at $25K to stay comfortably within PDT bounds

**$25K capital constraints:**
- A portfolio of 20+ stocks is impractical at $25K — minimum ~$1,250 per position
- Focus on 5-10 liquid ETFs for diversification without over-concentration
- No short positions recommended for PDT/margin simplicity unless account is margin-enabled
- $25K account: recommend long-only on ETFs (SPY, QQQ, sector ETFs like XLV, XLF, XLE)

**Trade frequency:** Medium (depends on universe size). On ETF universe, likely 2-5 active positions at any time.

---

## Gate 1 Assessment

| Criterion | Assessment | Notes |
|-----------|------------|-------|
| IS Sharpe > 1.0 | **LIKELY PASS** | Historical Sharpe 1.1 on liquid equity basket; ETF basket should hold |
| OOS Sharpe > 0.7 | **POSSIBLE PASS** | Key risk: regime mismatch in OOS period (e.g., if OOS period is a trend) |
| IS Max Drawdown < 20% | **LIKELY PASS** | Historical MDD ~14% with stops |
| Win Rate > 50% | **LIKELY PASS** | Mean reversion strategies typically have 55-65% win rate |
| Trade Count > 50 | **LIKELY PASS** | Liquid ETF basket over 5 years will generate 50+ signals |
| Parameter Sensitivity | **AT RISK** | entry_std is marked "high sensitivity" in KB — cliff-edge risk around 2.0 |
| PDT Compliance | **CONDITIONAL** | Manageable with ETF universe and 5+ day holding period target |

**Overall Gate 1 Outlook:** This is the **strongest of the 6 seed strategies** for passing Gate 1, based on historical performance data. Key risk is entry_std parameter sensitivity — backtest must show performance is robust to ±20% change in this parameter. Regime filtering is critical to avoid trending-market losses.

---

## Recommended Parameter Ranges for First Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| lookback_period (days) | 20 | [10, 15, 20, 30, 50] | Medium |
| entry_std | 2.0 | [1.5, 1.75, 2.0, 2.25, 2.5, 3.0] | High |
| exit_std (from mean) | 0.0 | [-0.5, 0.0, 0.5] | Low |
| max_holding_days | 10 | [5, 8, 10, 15, 20] | Medium |
| universe | 5 ETFs | Sector ETFs basket | — |

**Suggested universe (first backtest):** SPY, QQQ, XLV, XLF, XLE, IWM (diversified sector exposure).

**Backtest period:** 2018-01-01 to 2023-12-31.

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS.

**Critical test:** Confirm entry_std robustness — the Gate 1 requirement is < 30% Sharpe degradation for ±20% parameter change. With entry_std = 2.0, the ±20% range is [1.6, 2.4]. Must confirm Sharpe stays above threshold across this range.

**Free parameters in first test:** 4 (lookback, entry_std, exit_std, max_holding_days) — within Gate 1 limit of 6.
