# Overnight Hold on First-Up-Day Top-Decile Gainers, S&P 500 Constituents (QUA-819 v2)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-10-26
**Asset class:** equities (single stocks, 2018-01 S&P 500 constituents)
**Strategy type:** single-signal
**Status:** retired (preliminary IS check fails PF-1 on the primary spec and the net-edge floor; see Gate 1 Outlook)
**Source:** QUA-819 v2, closer translation of the social-media A-share rule (top-gainers list, first red day, MA5 turning up, buy at 14:30, sell next morning)
**Class:** momentum. This hypothesis uses the single momentum slot of its batch.
**Supersedes scope of:** `91_ta_overnight_reversal_gainer_spy_qqq.md` (index-ETF version, retired on PF-1 by construction because one instrument cannot produce enough signals).

## Economic Rationale

The A-share rule is a cross-sectional screen: from the daily gainers list, pick stocks that are up for the first time after a decline and whose short moving average is turning up, buy near the close and sell the next morning. The US translation keeps the cross-section.

Why an edge could exist:
- Lou, Polk and Skouras (2019, *Journal of Financial Economics*, "A tug of war: Overnight versus intraday expected returns") show that most of the equity premium accrues close-to-open, and that overnight and intraday return components have persistent but opposite cross-sectional patterns.
- Berkman, Koch, Tuttle and Zhang (2012, *JFQA*) link the overnight premium to attention-driven retail demand at the open, which is strongest for stocks on gainers lists.
- Short-term reversal literature (Jegadeesh 1990; Lehmann 1990) says a stock that fell for several days and then bounces is a liquidity-provision signal, so a bounce day with a strong close is consistent with buying-pressure continuation into the open.

Why it may not survive: the first-day-up bounce after a decline is the most crowded retail pattern, spreads on the mid-cap tail erase a few basis points of edge, and the evidence below shows the signal adds only a small increment over simply holding top-decile gainers overnight.

## Entry/Exit Logic

All parameters are fixed up front. Primary specification (pre-registered): N = 3, CLV >= 0.75, top decile.

**Universe (point-in-time):** stocks in `data/h82v2_universe_2018_jan.csv` (Jan 2018 constituents), filtered each day by the prior day's close > $5 and 20-day average dollar volume > $5M.

**Entry signal (evaluated at the close of day t, market-on-close order):**
- Gainer rank: close-to-close return on day t is in the top decile of the eligible universe that day.
- Down run: the closes of days t-3, t-2, t-1 are each below the prior close (N = 3).
- Up day: close(t) > close(t-1).
- Close location value: (close - low) / (high - low) >= 0.75.
- SMA5 slope turning up: SMA5(t) > SMA5(t-1).

**Exit signal:** sell at the next open (market-on-open). No stop, no target, no discretionary exit.

**Sizing:** equal weight across that day's signals, 100% of the sleeve, no leverage.

**Holding period:** Overnight

**Translation notes:** the 10-minute-chart MA5 is replaced by the daily SMA5 (PF-3, daily OHLCV only). The 14:30 entry is replaced by the close. The "sell at a morning high" exit is replaced by the open, because a morning-high exit is not codifiable from daily bars.

## Market Regime Context

- Works best (if at all): orderly, rising markets in which retail demand for gainers is strong. In-sample, the signal earned about -1 bp per trade in 2018-2019 and about +28 bps per trade in 2020-2021.
- Fails: bear-market rallies, where an up day after a decline is followed by a gap down.
- Pause trigger: SPY close below its SMA200.

## Alpha Decay

- **Signal half-life (days):** about 1. The overnight return is the signal.
- **Edge erosion rate:** fast (<5 days)
- **Recommended max holding period:** 1 night.
- **IC (daily cross-sectional Spearman of the signal flag vs the overnight return, IS 2018-2021, N=3):** T+1 -0.003. Forward return from the close, signal names vs eligible-universe average: T+5 +73 vs +38 bps; T+20 +200 vs +147 bps. The T+1 IC is indistinguishable from zero. The longer-horizon excess is small and not significant.
- **Annualized IR pre-cost:** gross all-day Sharpe 0.42 (N=3); 1.03 (N=2); 1.10 (N=4).
- **Cost survival: no (primary), marginal (N=4).**
  - Cost model, daily round trip, US large and mid caps with ADV > $5M: half-spread 2 to 5 bps per side, MOC/MOO slippage 1 to 3 bps per side, commission 0 (Alpaca). Round trip about 6 to 16 bps. Base case 10 bps, stress case 20 bps.
  - N=3: gross +15.2 bps per trade, so net +10.2 at 5 bps, +5.2 at 10 bps, -4.8 at 20 bps.
  - The Track A floor is 15 bps net profit per trade, so N=3 fails at every realistic cost level.
- **Increment over baseline:** the average eligible stock earned +8.1 bps overnight over the same window, so about half of the gross figure is baseline drift, not signal. Excess +7.1 bps per trade with a standard error of about 4.7 bps (t about 1.5, not significant).

> Half-life below 1 trading day requires explicit cost survival justification: the edge does not survive costs on the primary spec. No cost-survival claim is made.

## Preliminary Signal Check (IS only)

Data: yfinance daily OHLCV, split/dividend adjusted. IS window: 2018-01-01 to 2021-12-31 (the Jan 2018 constituent snapshot is point-in-time only from 2018). Data was fetched through 2021-12-31 only. No OOS data (2022+) was accessed. Overnight return = Open(t+1) / Close(t) - 1.

| Variant | Trades | Median trades per quarter | Hit rate | Mean overnight (bps) | t-stat | Gross all-day Sharpe | IS MDD |
|---|---|---|---|---|---|---|---|
| **N=3, top decile (primary)** | 1,486 | 88 | 53.2% | +15.2 | 3.25 | 0.42 | -36.8% |
| N=2, top decile | 5,043 | 315 | 53.1% | +11.8 | 5.14 | 1.03 | -23.6% |
| N=4, top decile | 247 | 15 | 57.1% | +36.8 | 3.12 | 1.10 | -10.5% |
| N=3, all gainers (no top-decile rank) | 3,672 | 220 | 55.5% | +11.1 | 4.57 | 0.71 | -21.1% |
| No decline condition, top decile | 34,072 | 2,215 | 54.7% | +13.4 | 10.39 | 1.55 | -28.7% |
| Control: top-decile gainers only | 65,894 | 4,126 | 55.2% | +13.3 | 13.26 | 1.74 | -32.0% |
| Control: eligible universe, all days | n/a | n/a | 56.0% | +8.1 | n/a | n/a | n/a |

Sub-period stability, mean overnight per trade (bps), 2018-2019 vs 2020-2021: N=3 primary -1.4 vs +27.9; N=2 +1.4 vs +21.2; N=4 +23.8 vs +48.3; control top-decile gainers +6.2 vs +20.2.

Reading:
- The decline condition and the SMA5 turn add almost nothing over the plain top-decile gainer control (+15.2 vs +13.3 bps for N=3, +11.8 vs +13.3 for N=2). The screen is mostly the gainer-list effect plus the universe-wide overnight drift.
- The edge is concentrated in 2020-2021 (retail-driven bull market). The primary spec is roughly zero in 2018-2019.
- N=4 looks best per trade but has only 15 trades per quarter and 247 trades in total; it is the best of the variants examined, so it is the most exposed to selection.
- Unlike the SPY/QQQ result in hypothesis 91, strong-close single stocks do not show a negative overnight return in this window.
- **Multiple-testing disclosure:** 7 configurations were examined. The pre-registered primary is N=3, CLV 0.75, top decile.
- **Survivorship caveat (material):** the 1,005-name Jan-2018 universe was reduced to the 734 names with at least 800 trading days of data in 2017-06 to 2021-12. This keeps names that survived to 2021 and drops names that were delisted or acquired in the window. That inflates every mean above, including the +8.1 bps baseline. Treat absolute levels as upper bounds. Relative comparisons against the same-universe control are less affected.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| N (down run) | 2 – 4 | N=3 primary |
| CLV threshold | 0.67 – 0.80 | 0.75 primary |
| Gainer rank cutoff | top 5% – top 15% | top decile primary |

Not recommended for testing: the control comparison shows the extra conditions add little.

## Capital and PDT Compatibility

- **Minimum capital required:** $25,000 recommended. 88 trades per quarter across about 574 signal days out of 1,000 means several names per day, and equal-weight sizing needs at least 10 to 20 positions to avoid concentration.
- **PDT impact:** none. Positions are held overnight (buy at close, sell next open), so no round trip occurs on the same trading day.
- **Position sizing:** equal weight, 100% of the sleeve on signal days, max 20 names per day (cap not applied in the IS check).

## Pre-Flight Gate Checklist

| Gate | Result | Evidence |
|---|---|---|
| PF-1 Walk-forward trade viability (>= 120 IS trades per 3-month window) | **FAIL (primary), PASS (N=2)** | N=3 median 88 trades per quarter. N=2 has 315 and passes, but its net edge per trade is +1.8 bps at 10 bps cost. |
| PF-2 Long-only MDD stress (< 40% in dot-com and GFC proxies) | **NOT TESTABLE as written; IS proxy marginal** | The 2018 point-in-time universe cannot be applied to 2000-2002 or 2008-2009 without survivorship bias. Proxy 1: IS MDD of -36.8% (N=3), which includes March 2020, is below 40% but above the Track A charter MDD ceiling of 30%. Proxy 2: exposure is overnight only (about 17 hours per signal), so the strategy does not hold through multi-day drawdowns; buy-and-hold SPY/QQQ MDD in dot-com and GFC was -47% to -83% and the SPY/QQQ version of this rule (hypothesis 91) had under 6% MDD. Judged marginal, not a clean pass. |
| PF-3 Data pipeline (yfinance/Alpaca daily OHLCV only) | **PASS** | Needs only daily OHLC and volume. Delisted tickers have partial yfinance coverage (see survivorship caveat). |
| PF-4 Rate-shock plausibility (2022) | **PASS only with a regime filter (a priori, untested)** | See below. |

**PF-4 a priori rationale (written without inspecting 2022 data).** In a rate-shock bear market, a first up day after three down days is the textbook bear-market rally, and top-decile gainers on such days are high-beta names that gap down the next morning when the rally fails. The unfiltered rule therefore has a plausible negative expectancy in 2022. The structural mitigant is a regime filter: no entries when SPY closes below its SMA200. SPY was below SMA200 for most of Jan to Jun 2022, so the filtered rule is mostly flat, and exposure when it does trade is limited to one night. Expected 2022 outcome with the filter: close to zero, not positive. Without the filter: negative. The filter is part of the recommended specification, but it is an a priori choice and has not been tested.

**Overall:** PF-1 fails on the primary spec. PF-2 is not cleanly testable. PF-3 passes. PF-4 passes only with an untested filter.

## Gate 1 Outlook

- IS Sharpe > 1.0: **unlikely** for the primary spec (gross 0.42 before costs). N=2 shows 1.03 gross but net of 10 bps costs the per-trade edge is +1.8 bps.
- Net profit per trade > 15 bps: **fails.** N=3 is +5.2 bps at 10 bps cost. N=4 passes (+26.8 bps) on 247 trades only.
- Cost-to-gross ratio < 0.25: **fails** for N=3 (10 / 15.2 = 0.66) and N=2.
- OOS persistence: **unlikely.** The edge sits in 2020-2021 and is about zero in 2018-2019.
- Walk-forward stability: **mixed.** N=3 fails the 120 trades floor; N=4 has about 15 trades per quarter.
- MDD: -36.8% IS (N=3) exceeds the Track A 30% ceiling.
- Sensitivity risk: **high.** Results change strongly with N.
- Known overfitting risks: 7 configurations examined; survivorship in the 734-name subset; one dominant sub-period.

## Recommendation

**Retire.** Do not send to Engineering. The closer single-stock translation fixes the trade-count problem of the ETF version (hypothesis 91) but not the economics: the conditions beyond "top-decile gainer" add about +2 bps over a plain gainer control, the net edge per trade is +5 bps at realistic costs against a 15 bps floor, and the result rests on a survivor-biased 2020-2021 bull market.

What remains of value: the plain top-decile gainers control earns about +13 bps overnight against +8 bps for the average stock. If the Research Director wants to pursue it, the right test is a separate hypothesis on the overnight gainer effect using a delisting-inclusive point-in-time universe (CRSP-quality or iShares annual snapshots), with the 10 to 20 bps cost model above. That is a new hypothesis, not a revision of this one.

## References

- Lou, D., Polk, C., Skouras, S. (2019). "A tug of war: Overnight versus intraday expected returns." *Journal of Financial Economics* 134(1), 192-213.
- Berkman, H., Koch, P., Tuttle, L., Zhang, Y. (2012). "Paying attention: Overnight returns and the hidden cost of buying at the open." *JFQA* 47(4), 715-741.
- Jegadeesh, N. (1990). "Evidence of predictable behavior of security returns." *Journal of Finance* 45(3), 881-898.
- Lehmann, B. (1990). "Fads, martingales, and market efficiency." *Quarterly Journal of Economics* 105(1), 1-28.
- Data: yfinance daily OHLCV, 734 of 1,005 Jan-2018 universe names, IS 2018-2021 only. Universe file: `data/h82v2_universe_2018_jan.csv` (committed in 6b4c7bd, not present on main).
- Related: `91_ta_overnight_reversal_gainer_spy_qqq.md`, H46, H61, H82v2.
- Check script: not committed; logic is the signal definition above.
