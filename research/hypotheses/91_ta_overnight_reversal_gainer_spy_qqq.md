# US Overnight Analogue of the A-Share Late-Day Gainer Rule (SPY/QQQ)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-10-26
**Asset class:** equities (liquid ETFs: SPY, QQQ)
**Strategy type:** single-signal
**Status:** retired (preliminary IS check fails; see Gate 1 Outlook)
**Source:** QUA-818 evaluation of a social-media A-share rule; task QUA-819
**Class:** momentum. This hypothesis uses the single momentum slot of its batch.

## Economic Rationale

The A-share rule buys at the close after a decline when the stock closes strong, then sells at the next open. The US translation is a close-to-open hold on SPY/QQQ after the first up day following an N-day decline, with a close in the top quartile of the day range and a rising SMA5.

Why an edge could exist: Lou, Polk and Skouras (2019, *Journal of Financial Economics*, "A tug of war: Overnight versus intraday expected returns") show that most of the equity premium accrues close-to-open, while intraday returns are near zero or negative. Berkman, Koch, Tuttle and Zhang (2012, *Journal of Financial and Quantitative Analysis*) tie the overnight premium to retail and attention-driven demand at the open. Cliff, Cooper and Gulen (2008) document the same pattern. Therefore any long close-to-open rule on a broad index starts with a positive drift of about 2 to 4 bps per night (measured below).

Why the specific conditioning may NOT help: a strong close (high close-location value) on an up day is intraday buying pressure. Lou et al. report that intraday strength is followed by weaker overnight returns (the tug of war), and the rule selects exactly those days. The prior is therefore neutral to negative, not positive. This hypothesis is written to test that prior honestly.

Why the A-share edge may not transfer: A-share markets have T+1 settlement, a retail-dominated base, and 10% limit rules. None of these apply to SPY/QQQ.

## Entry/Exit Logic

All parameters are fixed up front. Primary specification (pre-registered): N = 3, CLV threshold = 0.75.

**Entry signal (evaluated at the close of day t, executed with a market-on-close order):**
- Down run: the closes of days t-3, t-2, t-1 are each below the prior close (N = 3 consecutive down closes ending at t-1).
- Up day: close(t) > close(t-1).
- Close location value: (close - low) / (high - low) >= 0.75 on day t.
- SMA5 slope turning up: SMA5(t) > SMA5(t-1).

**Exit signal:**
- Sell at the next open (market-on-open). No stop, no target, no discretionary exit. One trade, about 17.5 hours of exposure.

**Optional regime filter (variant B, for PF-4):** require close(t) > SMA200(t).

**Holding period:** Overnight

**Parameter count:** 2 free (N, CLV). SMA5 and SMA200 lengths are fixed conventions.

## Market Regime Context

- Works best (if at all): sold-off but orderly markets where a reversal day attracts open-time demand.
- Fails: persistent downtrends, where up days after declines are bear-market rallies that give back at the open.
- Pause trigger: close below SMA200 (variant B), or VIX above 30.

## Alpha Decay

- **Signal half-life (days):** about 1. The signal is a one-night event.
- **Edge erosion rate:** fast (<5 days)
- **Recommended max holding period:** 1 night. Holding beyond the open is outside the specification.
- **IC (Spearman, binary signal vs forward return, IS 2000-2017, SPY, N=3):** T+1 (overnight) -0.018; T+5 -0.011; T+20 +0.000. QQQ, N=3: T+1 +0.007; T+5 +0.008; T+20 -0.019. All are indistinguishable from zero.
- **Annualized IR pre-cost (SPY, N=3, signal-days-only equity, gross Sharpe on all days):** -0.18. QQQ: +0.31. Both are below the disqualifier threshold of 0.1 on SPY and near the 0.3 warning line on QQQ.
- **Cost survival:** SPY no, QQQ marginal.
  - Cost model, daily round trip, US liquid ETFs: commission 0 bps (Alpaca); half-spread 0.5 to 1 bp per side on SPY and 1 bp per side on QQQ; MOC/MOO slippage 0.5 to 1 bp per side. Total round trip about 2 to 5 bps, 10 bps stress.
  - SPY N=3: mean -8.1 bps gross, so net -10 to -13 bps.
  - QQQ N=3: mean +21.1 bps gross, net +16 bps at 5 bps cost and +11 bps at 10 bps cost, but on 36 trades (t = 1.32, not significant).
  - Net profit per trade must exceed 15 bps (Track A floor). Only QQQ N=3 at 5 bps cost clears it, and the sample is too small to trust.
- **Notes:** Signal frequency is 1.5 to 2.0 per year at N=3. This is far too low for any walk-forward test.

> Justification required for half-life < 1 day: the edge does NOT survive realistic costs on SPY. On QQQ it survives only in-sample on 36 trades with t = 1.32. No cost-survival claim is made.

## Preliminary Signal Check (IS only)

Data: yfinance daily OHLCV, split/dividend adjusted. Window: 2000-01-01 to 2017-12-31. The fetch was capped at 2017-12-31. No OOS data (2018+) was accessed. Overnight return = Open(t+1) / Close(t) - 1.

| Ticker | Variant | Signals | Per year | Hit rate | Mean overnight (bps) | t-stat | Unconditional mean (bps) |
|---|---|---|---|---|---|---|---|
| SPY | N=3 (primary) | 27 | 1.5 | 44.4% | -8.1 | -0.75 | +2.4 (hit 54.3%) |
| SPY | N=2 | 131 | 7.3 | 42.7% | -10.9 | -2.41 | +2.4 |
| SPY | N=4 | 4 | 0.2 | 50.0% | -5.6 | -0.54 | +2.4 |
| SPY | N=3 + SMA200 | 20 | 1.1 | 45.0% | +0.7 | 0.08 | +2.4 |
| QQQ | N=3 (primary) | 36 | 2.0 | 50.0% | +21.1 | 1.32 | +4.3 (hit 55.2%) |
| QQQ | N=2 | 132 | 7.3 | 45.5% | +3.9 | 0.50 | +4.3 |
| QQQ | N=4 | 6 | 0.3 | 50.0% | +39.0 | 0.75 | +4.3 |
| QQQ | N=3 + SMA200 | 17 | 0.9 | 35.3% | +7.4 | 0.53 | +4.3 |

Reading:
- On SPY the conditioned signal has a lower hit rate and a lower mean overnight return than the unconditional overnight drift (54.3%, +2.4 bps). The conditioning removes edge. At N=2, where the sample is large enough, the overnight return is significantly negative (t = -2.41), consistent with the Lou et al. tug-of-war reading.
- On QQQ the point estimate at N=3 is positive but rests on 36 trades and is not significant. QQQ N=2 and the SMA200 variant do not confirm it.
- Sign flips between SPY and QQQ and across N show no stable effect.
- **Multiple-testing disclosure:** 8 configurations were examined (2 tickers x 4 variants). The pre-registered primary is N=3, CLV 0.75. No configuration passes after any reasonable multiple-testing adjustment.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| N (down run) | 2 – 4 | 2 to 4 consecutive down closes; N=3 is primary |
| CLV threshold | 0.67 – 0.80 | Top third to top quintile of the range; 0.75 is primary |

Not recommended for testing: the IS check shows no signal worth a parameter sweep.

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000 (one ETF lot sized at 100% notional; not capital-constrained).
- **PDT impact:** None. The position is held overnight, so it is not a day trade (buy at close, sell next day). Frequency is below 8 per year at N=2.
- **Position sizing:** 100% of strategy sleeve in one ETF, max 1 concurrent position.

## Pre-Flight Gate Checklist

| Gate | Result | Evidence |
|---|---|---|
| PF-1 Walk-forward trade viability (>= 120 IS trades per 3-month window equivalent) | **FAIL** | N=3 yields 27 (SPY) and 36 (QQQ) trades over 18 years, about 0.4 to 0.5 per quarter. Even N=2 gives 131 to 132 in total over 18 years. A rule with fewer than 8 signals per year cannot reach the PF-1 floor. |
| PF-2 Long-only MDD stress (< 40% in dot-com and GFC proxies) | **PASS (vacuous)** | Strategy-equity MDD, N=3 primary. SPY: dot-com -0.6% (7 trades), GFC (2007-10 to 2009-12) -2.2% (4 trades). QQQ: dot-com -2.1% (9 trades), GFC -0.5% (8 trades). For reference buy-and-hold MDD: SPY -47.5% and -55.2%; QQQ -83% and -53.4%. The pass comes from near-zero exposure (about 17 hours per signal, 1 to 2 signals per year), not from edge. |
| PF-3 Data pipeline (yfinance/Alpaca daily OHLCV only) | **PASS** | Needs only daily open, high, low, close. No intraday data. MOC/MOO orders are available on Alpaca. |
| PF-4 Rate-shock plausibility (2022) | **PASS (a priori, conditional)** | See below. |

**PF-4 a priori rationale (written without inspecting 2022 data; 2022 is OOS).** The strategy is flat during the day and holds only about 17 hours per signal, so there is no compounding of a trend drawdown: with 1 to 2 signals a year, the maximum 2022 exposure is a small handful of nights. The structural mechanism that reduces exposure is the entry itself, which needs a down run followed by an up day and is rare. In a rate-shock bear market, up days after declines are frequent bear-market rallies, so the risk is that entries cluster and each loses at the next open. Variant B (close above SMA200) removes most of this: during Jan to Jun 2022 SPY and QQQ spent most days below SMA200, so variant B is mostly flat. The expected 2022 return is therefore approximately zero, not positive. PF-4 asks for positive or neutral; this meets the neutral reading only. No hedge is added because a hedge would cost more than the expected edge.

**Overall:** PF-1 fails, which is a hard stop. PF-2 and PF-4 pass only because exposure is near zero.

## Gate 1 Outlook

- IS Sharpe > 1.0: **unlikely.** Gross all-day Sharpe is -0.18 (SPY N=3) and +0.31 (QQQ N=3).
- OOS persistence: **unlikely.** The IS sign flips between SPY and QQQ and across N.
- Walk-forward stability: **fails.** 1.5 to 2 signals per year cannot populate 6 windows with 30 trades each.
- Net profit per trade > 15 bps: SPY no; QQQ N=3 yes only at cost <= 5 bps and not significant.
- Cost-to-gross ratio < 0.25: SPY not defined (negative gross); QQQ N=3 about 0.24 at 5 bps and 0.47 at 10 bps.
- Sensitivity risk: **high.** Results change sign with N and with ticker.
- Known overfitting risks: 8 configurations examined; QQQ N=3 is the best of the 8.

## Recommendation

**Retire.** Do not send to Engineering. Honest outcome: the A-share late-day gainer rule does not transfer to US index ETFs on daily bars. The conditioning removes the unconditional overnight drift on SPY and gives too few trades to test on QQQ.

If the Research Director wants the overnight premium itself, it is already covered by H46 (unconditional SPY/QQQ overnight with SMA200 filter) and H61 (down-intraday conditioning). This evidence supports H61's direction: strong intraday close is a negative conditioner, weak intraday close is the positive one. A reformulation as a single-stock cross-sectional rule (long the bottom decile of intraday return, hold overnight) would solve the trade count but needs a larger universe and survivorship-free constituents; it is a new hypothesis, not a revision of this one.

## References

- Lou, D., Polk, C., Skouras, S. (2019). "A tug of war: Overnight versus intraday expected returns." *Journal of Financial Economics* 134(1), 192-213.
- Berkman, H., Koch, P., Tuttle, L., Zhang, Y. (2012). "Paying attention: Overnight returns and the hidden cost of buying at the open." *JFQA* 47(4), 715-741.
- Cliff, M., Cooper, M., Gulen, H. (2008). "Return differences between trading and non-trading hours: Like night and day." SSRN 1004081.
- Data: yfinance daily OHLCV (SPY, QQQ), 2000-2017 IS only.
- Related: H46 (overnight SPY/QQQ), H61 (overnight intraday-reversal selection).
- Check script: not committed; logic is the signal definition above (reproducible with yfinance in about 40 lines).
