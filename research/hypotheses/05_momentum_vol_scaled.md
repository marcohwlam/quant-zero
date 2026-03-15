# Hypothesis 05: Momentum — Volatility Scaled

**Status:** READY
**Category:** Momentum
**Source:** Quantopian Lectures / Jegadeesh & Titman (1993)
**Date:** 2026-03-15

---

## Summary

Cross-sectional momentum — buying recent winners and selling recent losers — generates persistent alpha. This implementation enhances raw momentum by (1) skipping the most recent month to avoid the short-term reversal effect, and (2) scaling position sizes by inverse realized volatility to equalize risk contribution across positions. Also includes a crash protection mechanism that reduces exposure when the broad market suffers a sharp monthly decline. Historically the strongest individual momentum strategy in academic literature.

---

## Economic Rationale

Momentum persists because of behavioral underreaction: investors and analysts update their views on stocks too slowly in response to earnings surprises and fundamental news. Initial reactions are muted; the full price adjustment plays out over the following 3-12 months. This creates a predictable pattern where recent winners (positive earnings surprises, improving fundamentals) continue to outperform.

**Three-factor decomposition of the edge:**
1. **Underreaction to news:** Investors anchor to prior prices and underweight new information (Barberis et al., Hong & Stein)
2. **Institutional herding:** Fund managers who performed well attract capital inflows, which they reinvest in existing winners (creating continuation)
3. **Trend-following feedback:** The momentum signal's broad use means trend followers reinforce the signal (though this also creates crash risk)

**The skip-recent-month improvement:** The 1-month reversal effect (Jegadeesh 1990) means the very most recent month's return is negatively autocorrelated (short-term mean reversion). Skipping it removes noise and improves signal quality.

**Volatility scaling:** Risk parity logic — equal risk per position, not equal dollar per position. High-volatility stocks get smaller allocations; low-volatility stocks get larger ones. This improves Sharpe significantly (~0.3 Sharpe improvement in backtests per KB data).

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| Trending bull | Excellent — momentum thrives; winners keep winning |
| Trending bear | Dangerous — crash protection helps, but momentum portfolios can suffer large drawdowns during reversals |
| Mean-reverting / choppy | Poor — no persistent winners/losers; signal degrades to noise |
| Crisis / reversal | Very dangerous — momentum crashes are well-documented (March 2009, March 2020) |

**When this strategy breaks down (critical risk):**
- **Momentum crashes:** Documented phenomenon — when cheap/beaten-down stocks reverse violently, the short leg (momentum losers) spikes, creating catastrophic losses. Examples: 2009 recovery, March 2020 recovery, September 2020 rotation.
- **Crowded trade risk:** Momentum is the most widely researched and used factor. When crowded funds unwind simultaneously, momentum loses money fast.
- **High-volatility regimes:** Volatility scaling increases turnover because position weights change frequently, adding transaction costs.

**Note on the 2018-2023 Gate 1 period:** This period includes the COVID crash (March 2020) and subsequent violent recovery — a classic momentum crash scenario. The crash protection mechanism will be critical during this period. Honest backtesting must include this stress event.

---

## Entry / Exit Logic

**Universe:** S&P 500 constituents (liquid large-cap equities with strong data history)

**Signal construction (monthly):**
1. Compute each stock's total return over the past momentum_lookback_months, excluding the most recent skip_recent_months
2. Rank all stocks by this return
3. Long top quintile (20% highest momentum), short bottom quintile (20% lowest momentum)
4. Rebalance monthly (every rebalance_frequency_days trading days)

**Position sizing:**
1. Estimate each stock's realized volatility (e.g., 21-day rolling std of daily returns, annualized)
2. Allocate inversely proportional to volatility: weight_i = (1/vol_i) / Σ(1/vol_j)
3. Scale total portfolio exposure to target target_volatility (e.g., 10% annualized)
4. Cap any single position at 5% of portfolio

**Crash protection:**
1. Compute the broad market (SPY) 1-month return
2. If SPY 1-month return < crash_protection_threshold (e.g., -10%), reduce all positions by 50%
3. Restore full positions when SPY rebounds above the threshold

**Exit:** Position exits at monthly rebalance when a stock falls out of the top/bottom quintile.

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**Asset class:** S&P 500 equities

**PDT Rule Impact:**
- Monthly rebalance cadence: positions are held for ~21 trading days on average — **PDT is not a significant constraint**
- Quintile rotation at $25K: ~20 long + 20 short positions = 40 total positions, $625 per position
- At $25K, 40 positions is not feasible due to minimum trade sizes and commission drag

**$25K capital constraints (SIGNIFICANT CONCERNS):**
- Full quintile portfolio (100 longs, 100 shorts) is completely impractical at $25K
- Even a scaled version (20 longs, 20 shorts) requires short selling and produces very small position sizes
- **Practical adaptation for $25K:**
  - Long-only version: buy top decile only (10-15 stocks) — sacrifices the short leg's alpha contribution
  - Or: use momentum-ranked ETFs (e.g., MTUM ETF as a proxy) for simplified exposure
- Short-selling at $25K faces the same margin constraints as multi-factor L/S (see Hypothesis 03)
- Historical MDD of 25% is at the Gate 1 limit for IS — the short leg helps in the full long-short version; long-only will have higher drawdowns

**Trade frequency:** Low-medium (monthly rebalance, 20-40 trades/month for full portfolio). PDT manageable.

---

## Gate 1 Assessment

| Criterion | Assessment | Notes |
|-----------|------------|-------|
| IS Sharpe > 1.0 | **LIKELY PASS** | Historical 1.4 on 2000-2020; the 2018-2023 period requires retesting given crowding |
| OOS Sharpe > 0.7 | **UNCERTAIN** | Momentum crashes in 2020 and rotation risk; crash protection must work |
| IS Max Drawdown < 20% | **AT RISK** | Historical MDD 25% — exceeds Gate 1 threshold of 20% without crash protection |
| Win Rate > 50% | **UNCERTAIN** | Cross-sectional momentum win rate depends on definition; typically ~55% |
| Trade Count > 50 | **PASS** | Monthly rebalance of 40-200 positions generates thousands of trades |
| Parameter Sensitivity | **LIKELY PASS** | Lookback window medium-sensitivity; crash protection threshold low-sensitivity |
| $25K Implementation | **CONCERN** | Full long-short impractical; long-only version sacrifices significant alpha |

**Overall Gate 1 Outlook:** **Conditional** — the key risk is the historical 25% MDD which already exceeds the Gate 1 IS threshold of 20%. The crash protection mechanism (which reduced the MDD in the historical record) is critical and must function correctly in the backtest. This strategy is worth testing but requires the crash protection module to work properly. Without it, it will fail Gate 1 on drawdown.

---

## Recommended Parameter Ranges for First Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| momentum_lookback_months | 12 | [3, 6, 9, 12, 18] | Medium |
| skip_recent_months | 1 | [0, 1, 2, 3] | Low |
| target_volatility | 0.10 | [0.05, 0.08, 0.10, 0.15, 0.20] | Medium |
| rebalance_frequency_days | 21 | [10, 15, 21, 42, 63] | Medium |
| crash_protection_threshold | -0.10 | [-0.05, -0.08, -0.10, -0.12, -0.15] | Low |

**Critical test:** Confirm that IS MDD < 20% is achievable with crash protection. If not, this strategy requires modification before Gate 1 submission.

**Backtest period:** 2018-01-01 to 2023-12-31 (must include the 2020 COVID crash/recovery — the most relevant momentum stress test).

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS.

**Free parameters:** 5 (within Gate 1 limit of 6).
