# Overnight Hold on Top-Decile Daily Gainers, Delisting-Aware Universe (QUA-823)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-10-26
**Asset class:** equities (single stocks, Jan 2018 S&P 500 constituent list)
**Strategy type:** single-signal
**Status:** retired (primary specification fails the net edge floor and the MDD ceiling; one exploratory variant is flagged for the Research Director, see Recommendation)
**Source:** QUA-823, follow-up to QUA-819 v2 (`92_ta_overnight_gainer_screen_sp500.md`)
**Class:** momentum. This hypothesis uses the single momentum slot of its batch.

## Economic Rationale

Plain version of the A-share rule with the weak conditions removed. In QUA-819 v2, the "down run" and "SMA5 turning up" conditions added only about +2 bps over simply buying the top-decile gainers, so this hypothesis keeps only the gainer rank.

Why an edge could exist:
- Lou, Polk and Skouras (2019, *Journal of Financial Economics*, "A tug of war: Overnight versus intraday expected returns") show that overnight returns carry most of the equity premium and that overnight return patterns persist across stocks.
- Berkman, Koch, Tuttle and Zhang (2012, *JFQA*) link overnight returns to attention-driven demand at the open, which is strongest for stocks on gainers lists.
- Barber and Odean (2008, *Review of Financial Studies*) show that individual investors are net buyers of attention-grabbing stocks, including large one-day winners.

Why it may not survive: the effect is small relative to realistic round-trip costs, was concentrated in 2020 retail-driven markets, and may be reduced by exclusion of delisted names.

## Entry/Exit Logic

All parameters fixed up front. Primary specification (pre-registered): top decile.

**Universe:** names in the Jan 2018 constituent list (`data/h82v2_universe_2018_jan.csv`, committed in 6b4c7bd, not on main), filtered daily by prior close > $5 and 20-day average dollar volume > $5M.

**Entry signal (at the close of day t, market-on-close order):**
- Close-to-close return on day t ranks in the top decile of the eligible universe that day.

**Exit signal:** sell at the next open (market-on-open). No stop, no target.

**Sizing:** equal weight across that day's signals, 100% of the sleeve.

**Recommended regime filter (variant B, a priori from hypothesis 91):** no entries when the equal-weight universe index closes below its 200-day moving average.

**Holding period:** Overnight

**Parameter count:** 1 (rank cutoff).

## Market Regime Context

- Works best (if at all): strong retail-driven bull markets. Excess return over the universe mean, by year, 2018 to 2021: +1.3, +0.3, +16.2, +3.6 bps per trade-day.
- Fails: persistent downtrends and low-attention regimes (2018 to 2019 excess is close to zero).
- Pause trigger: equal-weight universe index below its SMA200.

## Alpha Decay

- **Signal half-life (days):** about 1.
- **Edge erosion rate:** fast (<5 days)
- **Recommended max holding period:** 1 night.
- **IC / forward excess:** the signal is a rank cutoff; the measured quantity is the excess overnight return of the top decile over the eligible-universe mean: +5.4 bps per day (t = 3.13 on the daily difference series, 1,008 days). This t-stat ignores serial dependence and the strong 2020 concentration, so it overstates confidence.
- **Annualized IR pre-cost:** about 1.2 gross (see table, net Sharpe at 10 bps is 0.46).
- **Cost survival: no (primary).**
  - Cost model, daily round trip, US stocks with ADV above $5M: half-spread 2 to 5 bps per side, MOC/MOO slippage 1 to 3 bps per side, commission 0 (Alpaca). Round trip about 6 to 16 bps. Base 10 bps, stress 20 bps. For ADV above $200M, 6 bps is plausible.
  - Primary: gross +13.5 bps per trade, net +3.5 bps at 10 bps and -6.5 bps at 20 bps.
  - Track A floor is 15 bps net profit per trade: fails.

> Half-life below 1 trading day requires explicit cost survival justification: the primary specification does not survive realistic costs at the Track A floor. No cost-survival claim is made for it.

## Preliminary Signal Check (IS only)

Data: yfinance daily OHLCV, split/dividend adjusted. IS window 2018-01-01 to 2021-12-31. Fetched through 2021-12-31 only, no OOS (2022+) data accessed. Overnight return = Open(t+1) / Close(t) - 1. Daily portfolio: equal weight across that day's signals, flat on days without signals; cost charged per invested day.

**Data coverage (the point of this ticket):** 1,005 names requested, 747 returned data (745 on first pass plus 2 on retry), 258 returned nothing (25.7%). No history filter was applied beyond 60 days, so names that were delisted inside the window or listed late are included for the days they existed. Names that yfinance does not serve at all (mostly acquired or delisted) remain missing. The data is therefore improved over QUA-819 v2 (734 names) but not delisting-complete. No alternate data credentials (Alpaca, Polygon, Tiingo) are available in this environment.

| Variant | Trades | Median per quarter | Mean overnight (bps) | Excess vs universe (bps, t) | Net per trade at 10 bps | Net Sharpe at 10 / 20 bps | IS MDD at 10 bps |
|---|---|---|---|---|---|---|---|
| **Top 10% (primary)** | 66,461 | 4,158 | +13.5 | +5.4 (3.13) | +3.5 | 0.46 / -0.83 | -46% |
| Top 5% | 33,482 | 2,094 | +17.3 | +9.2 (3.59) | +7.3 | 0.83 / -0.30 | -41% |
| Top 20% | 132,418 | 8,284 | +11.4 | +3.2 (2.79) | +1.4 | 0.20 / -1.24 | -48% |
| Top 10%, ADV > $50M | 38,238 | 2,366 | +14.4 | +6.3 (2.82) | +4.4 | 0.54 / -0.67 | -50% |
| Top 10%, ADV > $200M | 15,159 | 890 | +19.2 | +11.9 (3.23) | +9.2 | 0.99 / 0.01 | -44% |
| Top 10%, ADV $5M to $50M | 28,223 | 1,758 | +12.3 | +4.7 (2.44) | +2.3 | 0.37 / -0.90 | -41% |
| Top 10% and return > 3% | 29,964 | 1,654 | +22.3 | +9.9 (3.61) | +12.3 | 0.92 / -0.24 | -35% |
| Top 10% and return > 5% | 12,720 | 604 | +30.4 | +16.1 (3.12) | +20.4 | 1.09 / 0.29 | -44% |
| Top 10%, regime filter (variant B) | 54,402 | 4,158 | +12.7 | +4.0 (2.40) | +2.7 | 0.45 / -1.22 | -18% |
| Control: bottom 10% (losers) | 65,453 | 4,095 | +9.5 | +1.4 (0.82) | -0.5 | -0.05 / -1.23 | -46% |

Mean overnight by year 2018, 2019, 2020, 2021 (bps, primary): 6, 7, 27, 15. Top 10% and return > 5%: -13, 19, 41, 42.

Reading:
- The gainer effect is positive but small: +5 bps excess over the universe, with 2020 supplying most of it. Excess in 2018 and 2019 is near zero.
- Larger and more liquid gainers show more edge (ADV > $200M: +11.9 bps excess), and bigger one-day moves show more (return > 5%: +16.1 bps excess). The larger move filter fails in 2018 (-13 bps).
- Losers earn +9.5 bps overnight against +8.1 bps for the universe, so most of the level is generic overnight drift in a bull sample, not a gainer-specific effect.
- **Multiple-testing disclosure:** 10 configurations were examined. The primary is pre-registered as top 10%. All other rows are post-hoc exploration, and the best-looking rows (return > 5%, ADV > $200M) are the most exposed to selection.
- **Survivorship bound:** the 258 missing names are 25.7% of the universe. If their overnight returns on gainer days averaged m bps, the blended gross would be 0.743 x 13.5 + 0.257 x m. For the blended net edge to reach the Track A floor of 15 bps at 10 bps cost, m must be at least about 58 bps. That is implausible, so the failure of the primary spec against the 15 bps floor is robust to the missing data. The sign and size of the +5.4 bps excess are not robust and could move either way.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| Rank cutoff | top 5% to top 20% | primary top 10% |
| Minimum one-day return | 0% to 5% | exploratory only, post-hoc |
| Minimum ADV | $5M to $200M | exploratory only, cost tier |

## Capital and PDT Compatibility

- **Minimum capital required:** $25,000. About 66 names per day in the primary specification; a 20-name cap per day is required at this size.
- **PDT impact:** none. Positions are held overnight, so they are not day trades.
- **Position sizing:** equal weight, 100% of the sleeve on signal days, max 20 names per day (cap not applied in the IS check).

## Pre-Flight Gate Checklist

| Gate | Result | Evidence |
|---|---|---|
| PF-1 Walk-forward trade viability (>= 120 IS trades per 3-month window) | **PASS** | Primary 4,158 trades per quarter; return > 5% variant 604. |
| PF-2 Long-only MDD stress (< 40%) | **FAIL (unfiltered), PASS (variant B, IS proxy)** | Dot-com and GFC cannot be run point-in-time with a 2018 constituent list. IS proxy: primary MDD -46% at 10 bps (fails 40%); variant B MDD -18%. The Track A charter ceiling of 30% is met only by variant B. The IS period includes March 2020. |
| PF-3 Data pipeline (yfinance/Alpaca daily OHLCV only) | **PASS with caveat** | Daily OHLCV only. yfinance does not serve 25.7% of the requested names, so a delisting-complete test needs another data source. |
| PF-4 Rate-shock plausibility (2022) | **PASS only for variant B (a priori, untested)** | Written without inspecting 2022 data. In a rate-shock bear market, top gainers are high-beta rallies that tend to reverse, and retail demand fades. The unfiltered rule has no structural exit. Variant B is flat when the equal-weight universe is below its SMA200, which covers most of Jan to Jun 2022. Expected 2022 result with the filter: about zero, not positive. |

**Overall:** the primary specification fails PF-2 and the net edge floor. Variant B passes PF-1 to PF-4 on paper but its net edge per trade is +2.7 bps at 10 bps cost.

## Gate 1 Outlook

- IS Sharpe > 1.0: **unlikely.** Net Sharpe 0.46 (primary) and 0.45 (variant B) at 10 bps.
- Net profit per trade > 15 bps: **fails** for the primary (+3.5) and variant B (+2.7).
- Cost-to-gross ratio < 0.25: **fails** (10 / 13.5 = 0.74).
- OOS persistence: **unlikely.** Excess return is concentrated in 2020.
- MDD: -46% (primary) and -18% (variant B) against a 30% ceiling.
- Sensitivity risk: **high.** Edge depends on liquidity tier, move size, and year.
- Known overfitting risks: 10 configurations; 25.7% of the universe is missing; one dominant year.

## Recommendation

**Retire the primary specification.** Do not send to Engineering.

Flag for the Research Director: the exploratory row "top 10% and return > 5%" shows +20.4 bps net per trade at 10 bps cost (604 trades per quarter), and "ADV > $200M" shows +9.2 bps net with lower realistic costs. Both are post-hoc, both lose or earn about nothing in 2018, and both are untested on delisted names. If the Director wants to pursue them, the next step is a new hypothesis that pre-registers the larger-move and liquidity filters, uses a delisting-complete data source (Alpaca historical assets including inactive symbols, Norgate, or CRSP), and only then touches OOS data. I do not recommend spending the OOS window on this before the data gap is closed.

## References

- Lou, D., Polk, C., Skouras, S. (2019). "A tug of war: Overnight versus intraday expected returns." *Journal of Financial Economics* 134(1), 192-213.
- Berkman, H., Koch, P., Tuttle, L., Zhang, Y. (2012). "Paying attention: Overnight returns and the hidden cost of buying at the open." *JFQA* 47(4), 715-741.
- Barber, B., Odean, T. (2008). "All that glitters: The effect of attention and news on the buying behavior of individual and institutional investors." *Review of Financial Studies* 21(2), 785-818.
- Data: yfinance daily OHLCV, 747 of 1,005 Jan-2018 universe names, IS 2018-2021 only.
- Related: `91_ta_overnight_reversal_gainer_spy_qqq.md`, `92_ta_overnight_gainer_screen_sp500.md`, H46, H61.
- Check script: not committed; logic is the signal definition above.
