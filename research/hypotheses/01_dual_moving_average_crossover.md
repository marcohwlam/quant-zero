# Hypothesis 01: Dual Moving Average Crossover

**Status:** READY
**Category:** Trend Following
**Source:** Quantopian Lectures
**Date:** 2026-03-15

---

## Summary

A fast simple moving average (SMA) crossing above a slow SMA signals the initiation of a sustained uptrend; the reverse signals a downtrend. The strategy goes long on bullish crossovers and flat (or short) on bearish crossovers. It is one of the oldest and most widely tested systematic strategies — useful as a baseline benchmark.

---

## Economic Rationale

Prices trend because market participants underreact to new information (anchoring bias) and then gradually update their views, creating momentum. Moving averages smooth out noise and filter trend initiation from random fluctuations. The crossover rule is a proxy for detecting when the balance of buying/selling pressure has shifted durably. The edge is behavioral: it exploits the gap between when a trend starts and when the consensus recognizes it.

**Why the edge may be weak:** This is one of the most widely known signals, so it is highly crowded. The raw edge on liquid ETFs (SPY, QQQ alone) is marginal (Sharpe ~0.6 historically). Diversification across a basket of uncorrelated ETFs improves risk-adjusted returns significantly.

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| Trending (bull or bear) | Strong — signal captures trend initiation cleanly |
| Mean-reverting / choppy | Poor — excessive whipsaws, transaction costs erode returns |
| High volatility / crisis | Mixed — fast exits can limit drawdown, but whipsaws spike |

**When this strategy breaks down:**
- Sideways, range-bound markets (2015 chop) generate repeated false signals
- V-shaped reversals (COVID March-April 2020) cause large drawdown before cross fires
- Very long trends with no cross may hold position through intermediate pullbacks

**Regime filter recommended:** Add a simple regime check — only take signals when 200d SMA is upward sloping (for longs) to avoid trending into a declining market.

---

## Entry / Exit Logic

**Entry (Long):**
1. Compute fast SMA (e.g., 10-day) and slow SMA (e.g., 50-day) on adjusted close
2. Enter long when fast SMA crosses above slow SMA (previous bar: fast < slow; current bar: fast > slow)
3. Confirmed entry: only enter if 200d SMA slope is positive (optional regime filter)

**Exit (Long):**
- Primary: exit when fast SMA crosses back below slow SMA (reverse signal)
- Secondary: trailing stop at 2x ATR from entry if cross hasn't fired

**Short (optional):**
- Mirror of long logic; go short when fast SMA crosses below slow SMA
- Note: short side requires margin and PDT discipline — see constraints below

**Position sizing:** Equal-weight across universe. Volatility-adjusted sizing (inverse ATR weighting) preferred to equalize risk per position.

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**Asset class:** Equities / Broad ETFs (SPY, QQQ, IWM, EFA, TLT recommended for diversification)

**PDT Rule Impact:**
- This is a swing/position strategy with average holding periods of weeks to months — **PDT rule is not a primary constraint**
- Crossover signals fire infrequently enough that 3 round-trips/week limit is rarely hit
- Using ETFs avoids single-stock earnings/event risk

**$25K capital constraints:**
- Focus on ETFs: no minimum stock price concerns, high liquidity
- Short side requires margin (Reg T: 50% margin) — shorting ETFs in a $25K account is feasible but reduces buying power
- Recommended: long-only or long/flat variant to avoid margin complexity at $25K
- Max single position 20% of portfolio = $5K per ETF position; 5-position basket is appropriate

**Trade frequency:** Low (1-5 trades/month per instrument). Well within PDT limits.

---

## Gate 1 Assessment

| Criterion | Assessment | Notes |
|-----------|------------|-------|
| IS Sharpe > 1.0 | **AT RISK** | Historical Sharpe ~0.6 on SPY alone; needs diversified basket to reach 1.0 |
| OOS Sharpe > 0.7 | **AT RISK** | If IS barely clears 1.0, OOS degradation likely pushes below 0.7 |
| IS Max Drawdown < 20% | **LIKELY PASS** | Historical MDD ~18%, should be fine with stop |
| Win Rate > 50% | **AT RISK** | Trend-following often has win rate 40-45%, relying on large wins |
| Trade Count > 50 | **LIKELY PASS** | Over 5 years, will generate 50+ signals |
| Parameter Sensitivity | **AT RISK** | Window lengths are known to be sensitive; needs robustness testing |
| PDT Compliance | **PASS** | Swing trade cadence; no PDT issue |

**Overall Gate 1 Outlook:** This strategy is likely to **struggle to pass Gate 1** as a standalone SPY signal. A diversified ETF basket (8-10 instruments) significantly improves the odds. Treat as a **baseline/benchmark** and a starting point for more refined trend-following approaches.

---

## Recommended Parameter Ranges for First Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| fast_window (days) | 10 | [5, 10, 15, 20, 30] | Medium |
| slow_window (days) | 50 | [20, 30, 50, 100, 200] | Medium |
| atr_stop_multiplier | 2.0 | [1.0, 1.5, 2.0, 2.5, 3.0] | Low |
| universe_size | 5 ETFs | [1, 3, 5, 8, 10] | High |
| regime_filter_enabled | True | [True, False] | Medium |

**Suggested universe (first backtest):** SPY, QQQ, IWM, EFA, TLT — diversified across equity style, international, and bonds.

**Backtest period:** 2018-01-01 to 2023-12-31 (includes 2018 vol, COVID crash/recovery, 2022 rate cycle — per Gate 1 requirement).

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS (per Gate 1 requirement).

**Free parameters in first test:** 3 (fast_window, slow_window, atr_stop_multiplier) — well within Gate 1 limit of 6.
