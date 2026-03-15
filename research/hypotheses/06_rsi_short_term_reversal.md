# Hypothesis 06: RSI Short-Term Reversal

**Status:** READY
**Category:** Mean Reversion / Short-Term Reversal
**Source:** Classic technical analysis / Connors & Alvarez RSI(2) research
**Date:** 2026-03-15

---

## Summary

The Relative Strength Index (RSI) at short lookback periods (2-5 days) identifies instruments that are temporarily oversold (RSI < 10-30) or overbought (RSI > 70-90). The strategy fades extreme readings: buying oversold dips and shorting overbought spikes, expecting mean reversion within 1-5 days. A variant popularized by Larry Connors uses RSI(2) on daily data with an entry filter that requires the price to be above its 200-day SMA (to trade only in the dominant trend direction). Distinct from the Bollinger Band strategy (Hypothesis 02) in its use of RSI as the overbought/oversold signal rather than price deviation from a volatility band.

---

## Economic Rationale

Short-term RSI extremes reflect temporary exhaustion of buying or selling pressure. When a stock falls sharply over 2-5 days (RSI drops below 10), short-term sellers have likely already sold and the order imbalance reverses. Buyers who were waiting for a pullback step in, causing a rapid 1-5 day recovery. The mechanism is behavioral: investors overreact to short-term price moves, creating temporary mispricing that quickly resolves.

The RSI(2) variant specifically captures mean reversion at a faster time scale than Bollinger Bands (which use 20-day lookbacks). The very short lookback (2 days) makes it hypersensitive to recent price moves — filtering with a 200d SMA trend filter ensures we only fade pullbacks within an uptrend, not catch falling knives in a bear market.

**Why the edge may persist:**
- Very short-term reversals are too frequent and small for institutional capital to exploit efficiently
- The holding period (1-5 days) is too short for most trend-following systems but well-suited for a nimble systematic approach
- The edge has been documented across multiple asset classes and time periods (equities, ETFs, commodities)

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| Mean-reverting / choppy | Excellent — core regime |
| Trending bull (with 200d SMA filter) | Good — buy pullbacks within uptrend |
| Trending bear | Poor — without short positions, must sit out; short-side RSI > 90 signals in downtrends |
| High volatility | Mixed — more extreme RSI readings = more frequent signals, but also more false starts in volatile conditions |
| Crisis | Dangerous without stop-loss — "the RSI can stay oversold longer than you can stay solvent" |

**When this strategy breaks down:**
- Trending markets without the 200d SMA filter: buying an RSI < 10 in a downtrend catches falling knives
- Earnings/catalyst events: RSI < 10 after an earnings miss is NOT a mean reversion setup — it's a fundamental re-rating
- Illiquid instruments: RSI extremes in illiquid names may not revert; the price move may be due to a single large order with no natural counterparty
- Regime breaks: 2022 rate hike cycle saw extended RSI lows without reversion — trending bear market punished this strategy severely

**Critical filter (non-negotiable):** Only take long entries when the instrument is trading above its 200-day SMA. This is the Connors RSI(2) insight: the same RSI < 10 in an uptrend vs. a downtrend has radically different expected outcomes.

---

## Entry / Exit Logic

**Universe:** Liquid ETFs (SPY, QQQ, IWM, sector ETFs) or S&P 500 large-cap equities above $10/share with > 1M average daily volume

**Signal construction (daily):**
1. Compute RSI over rsi_period days (default: 4 days; shorter = more sensitive)
2. Buy signal: RSI < rsi_oversold_threshold AND close > 200d SMA
3. Short signal (optional): RSI > rsi_overbought_threshold AND close < 200d SMA

**Entry:**
- Long: enter at the close of the day the RSI crosses below rsi_oversold_threshold (or next open)
- Position size: flat 1 position at a time (or scale in if RSI drops further — "cumulative RSI" entry)
- Alternative entry: use a "cumulative RSI" — enter when the sum of last 2 days' RSI readings < 35 (Connors variant)

**Exit (multiple options — choose one for first backtest):**
- Primary: exit when RSI crosses back above rsi_exit_threshold (e.g., 55-65) — "RSI recovery exit"
- Time stop: exit after max_holding_days regardless of RSI (e.g., 5 days)
- Profit target: exit when price returns to the N-day high (e.g., 5-day high)

**Stop-loss:** Hard stop at stop_pct below entry (e.g., 3-5%) — prevents catastrophic losses if the mean reversion fails

**Position sizing:** Fixed fractional (e.g., 10-15% of portfolio per signal). Only 1-3 active positions simultaneously.

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**Asset class:** ETFs primary (SPY, QQQ, IWM, sector ETFs) — less earnings event risk than individual stocks

**PDT Rule Impact (CRITICAL CONSTRAINT FOR THIS STRATEGY):**
- This is a **short-term trading strategy** with 1-5 day holding periods — **PDT is the primary constraint at $25K**
- Holding period < 5 days = round trip within a week = counts toward the 3 round-trip limit
- If signals fire 2-3 times per week per instrument, the 3 round-trip limit will be hit
- **Mitigation strategies:**
  1. Trade only on ETFs (fewer signals than individual stocks) and limit to 2 active positions max
  2. Target holding periods of 5+ days (use the RSI recovery exit rather than time stop)
  3. Only take the highest-conviction signals (RSI < 5 vs. RSI < 20 — be more selective)
  4. Accept that some signals will not be taken due to PDT budget exhaustion

**$25K capital fit:**
- Long-only on 1-3 ETFs is perfectly sized for $25K
- No short positions required for the primary long-only variant
- With $25K and 2 simultaneous positions: $12,500 per position — viable
- Trade frequency constrained by PDT to ~2-3 round trips/week maximum

**Honest assessment:** This strategy's signal frequency may exceed PDT limits at $25K. The backtest should track trade frequency carefully and note how many signals are generated per week. If > 3 trades/week on average, the live implementation will miss signals.

---

## Gate 1 Assessment

| Criterion | Assessment | Notes |
|-----------|------------|-------|
| IS Sharpe > 1.0 | **POSSIBLE** | RSI(2) variants have shown Sharpe 0.9-1.4 in academic studies depending on period and implementation |
| OOS Sharpe > 0.7 | **UNCERTAIN** | Highly dependent on whether the 2018-2023 test period includes mean-reverting regimes |
| IS Max Drawdown < 20% | **LIKELY PASS** | Short holding period limits drawdown; hard stop prevents catastrophic losses |
| Win Rate > 50% | **LIKELY PASS** | Short-term reversal strategies typically achieve 60-70% win rate at cost of small wins |
| Avg Win / Avg Loss > 1.0 | **AT RISK** | Many small wins + fewer larger losses (asymmetric payoff in the wrong direction) — must verify |
| Trade Count > 50 | **PASS** | High signal frequency; easily 50+ trades in IS period |
| PDT Compliance | **AT RISK** | Signal frequency may exceed 3 trades/week at $25K; must be tracked |
| Parameter Sensitivity | **UNKNOWN** | Not characterized in KB (no prior backtest); rsi_period and rsi_oversold_threshold likely sensitive |

**Overall Gate 1 Outlook:** **Uncertain but worth testing** — RSI short-term reversal is a well-documented academic strategy with solid empirical backing, but the specific performance on the 2018-2023 period (which includes two very different regimes: 2020 COVID crash and 2022 bear market) is unknown. PDT compliance is a specific practical concern for live trading. The win rate is likely to be good (60-70%), but the win/loss ratio may be unfavorable (small wins, large stops) — this combination needs to clear the Gate 1 thresholds simultaneously.

---

## Recommended Parameter Ranges for First Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| rsi_period (days) | 4 | [2, 3, 4, 5, 7, 10, 14] | High (expected) |
| rsi_oversold_threshold | 20 | [5, 10, 15, 20, 25, 30] | High (expected) |
| rsi_overbought_threshold | 80 | [70, 75, 80, 85, 90] | Medium |
| rsi_exit_threshold | 55 | [50, 55, 60, 65] | Medium |
| max_holding_days | 5 | [3, 5, 7, 10] | Medium |
| stop_pct | 0.04 | [0.02, 0.03, 0.04, 0.05, 0.07] | Medium |

**Note:** 6 parameters — at the Gate 1 limit of 6 free parameters. Consider fixing rsi_overbought_threshold at 80 (test only long side first) to reduce to 5 free parameters.

**Suggested universe (first backtest):** SPY, QQQ, IWM (3-ETF universe; liquid, low noise, no earnings events).

**200-day SMA filter:** Non-negotiable — must be included in all variants. This is not a free parameter; it is a structural element of the hypothesis.

**Backtest period:** 2018-01-01 to 2023-12-31.

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS.

**PDT tracking:** Backtest engine should record weekly trade count — flag any walk-forward window where average weekly round trips exceed 3.
