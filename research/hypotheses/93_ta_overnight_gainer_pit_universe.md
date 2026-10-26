# Overnight Hold on Top-Decile Gainers, Delisting-Inclusive Universe (QUA-823)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-10-26
**Asset class:** equities (single stocks, Jan-2018 S&P 500 constituents including names later delisted)
**Strategy type:** single-signal
**Status:** retired (net edge is negative at 10 and 20 bps round trip; the effect in hypothesis 92 does not reproduce)
**Source:** follow-up to QUA-819 / `92_ta_overnight_gainer_screen_sp500.md`; approved by the requester on QUA-819
**Class:** momentum (cross-sectional gainer continuation overnight)

## Economic Rationale

Hypothesis 92 reported that top-decile close-to-close gainers earned +13.3 bps overnight against +8.1 bps for the average stock, on a 734-name survivor subset. This hypothesis asks whether that gap is real once names that were delisted or acquired in the window are kept in the universe.

The mechanism proposed in the literature is attention-driven retail demand at the open for stocks on gainers lists (Berkman, Koch, Tuttle and Zhang 2012, *JFQA*). The opposing mechanism is short-term reversal concentrated overnight, where liquidity-provision returns accrue to buyers of the day's losers (Jegadeesh 1990; Lehmann 1990; Lou, Polk and Skouras 2019, *JFE*). The result below supports the reversal side.

## Entry/Exit Logic

Pre-registered before the data was fetched. One primary specification, no tuning.

**Universe:** `data/h82v2_universe_2018_jan.csv` (1,047 tickers, Jan 2018 S&P 500 plus the extension used in hypothesis 92), daily bars from Alpaca (SIP, split and dividend adjusted), 2017-06-01 to 2021-12-31. Names with later delisting stay in the sample until their last bar. Daily eligibility filter: prior close > $5, prior 20-day average dollar volume > $5M, volume > 0.

**Entry signal (close of day t, market-on-close):** close-to-close return on day t is in the top decile of that day's eligible universe.

**Exit signal:** sell at the next open (market-on-open). No stop, no target.

**Delisting rule:** if a name has no bar on t+1 (data ends), the overnight return is unobservable. 872 such eligible rows exist, 69 of them in names delisted inside the window. Base case drops them; stress cases assign a -10% and a -30% exit return.

**Holding period:** Overnight

## Market Regime Context

- The gainer-overnight return is weakly negative to flat in both halves of the IS window: -4.4 bps in 2018-2019 and +7.1 bps in 2020-2021. Both are below the average-stock baseline (5.1 and 10.6 bps).
- 2020-2021 is the retail-driven bull market where an attention effect would be strongest. It still does not appear.
- Pause trigger (if ever revisited): none justified, because there is no positive edge to protect.

## Alpha Decay

- **Signal half-life (days):** about 1. The overnight return is the signal.
- **Edge erosion rate:** fast (<5 days)
- **Recommended max holding period:** 1 night.
- **IC:** not estimated separately. The decile table below is the cross-sectional readout; the top-decile gross mean is +1.3 bps (t 0.4).
- **Annualized IR pre-cost:** daily-portfolio gross Sharpe 0.16 (full universe). Below the 0.3 warning level, above the 0.1 disqualifier by a small margin.
- **Cost survival: no.** Cost model as in hypothesis 92: half-spread 2 to 5 bps per side, MOC/MOO slippage 1 to 3 bps per side, commission 0 (Alpaca), so 10 bps base and 20 bps stress round trip. Gross +1.3 bps gives net -8.7 bps at 10 bps and -18.7 bps at 20 bps.

> Half-life below 1 trading day requires explicit cost survival justification. None is available: the gross edge is not distinguishable from zero.

## Preliminary Signal Check (IS only)

Data: Alpaca daily bars via `research/scripts/h93_fetch_alpaca_daily.py`; analysis in `research/scripts/h93_overnight_gainer_check.py`. IS window 2018-01-01 to 2021-12-31 (2017-06 onward used for warm-up only). No data after 2021-12-31 was requested or read. Overnight return = Open(t+1) / Close(t) - 1. Standard errors are clustered by day.

| Universe / treatment | Trades | Median per quarter | Hit | Mean (bps) | SE | t | Baseline (bps) | Excess (bps) | Net @10 | Net @20 | Sharpe | MDD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A. Survivor subset (>= 800 days, replicates hypothesis 92) | 84,226 | 5,286 | 51.8% | +0.7 | 3.7 | 0.2 | 7.9 | -7.2 | -9.3 | -19.3 | 0.07 | -49.8% |
| **B. Full universe, drop unobservable (primary)** | 86,036 | 5,363 | 51.9% | +1.3 | 3.7 | 0.4 | 7.9 | -6.6 | -8.7 | -18.7 | 0.16 | -48.5% |
| C. Full, delisting exit -10% | 86,046 | 5,363 | 51.9% | +1.2 | 3.7 | 0.3 | 7.9 | -6.7 | -8.8 | -18.8 | 0.15 | -48.9% |
| D. Full, delisting exit -30% | 86,046 | 5,363 | 51.9% | +1.0 | 3.7 | 0.3 | 7.7 | -6.7 | -9.0 | -19.0 | 0.12 | -49.7% |
| E. Delisted/short-history names only (diagnostic) | 2,148 | 118 | 53.8% | +15.5 | 8.4 | 1.8 | 10.0 | +5.6 | +5.5 | -4.5 | 1.45 | -37.1% |

Survivorship bias quantified (B minus A): +0.6 bps on the top-decile mean, and 0.0 bps on the baseline (7.9 in both). The bias is small and has the opposite sign from the usual expectation. Sub-group E is too small to carry weight (t 1.8, 118 trades per quarter, 69 unobservable delisting exits).

**Mean overnight return by same-day return decile (bps), survivors, eligible filter, low to high:** 22.1, 13.3, 10.5, 8.8, 7.2, 5.5, 5.2, 3.3, 2.2, 0.7. The relationship is monotonic and negative. Yesterday's losers earn the most overnight; yesterday's gainers earn the least. This is overnight reversal, not gainer continuation.

**Why this disagrees with hypothesis 92 (+13.3 bps, 65,894 trades):** I could not reproduce that figure. Checks run:
- Data source is not the cause. On 9 overlapping names, yfinance and Alpaca overnight means agree within 1.2 bps (for example AAPL 6.3 vs 6.3, GME 44.4 vs 45.6); level differences come only from dividend-adjustment convention.
- The baseline matches (7.9 bps here vs 8.1 bps there), so the price data are consistent.
- Changing the eligibility filter (none, price only, price and dollar volume) moves the top-decile mean between +0.3 and +1.9 bps, never near +13.
- The hypothesis 92 check script was not committed, so the cause of the gap cannot be traced. The likeliest candidates are a ranking or alignment difference in that script. Treat the +13.3 bps figure as unverified and superseded by this result.

Multiple-testing disclosure: one pre-registered primary (B), three treatment variants (A, C, D, E are the same signal under different universe or exit rules), and four diagnostic reproduction runs. No signal parameters were tuned.

Residual survivorship: 71 of the 1,047 requested tickers returned no Alpaca bars (for example SPLS, G1T rejected as an invalid symbol). These are mostly names that were acquired or whose tickers were reused. They are still absent, so a small amount of survivorship bias remains in B. The Jan-2018 constituent list also does not add later index entrants, so late-window eligibility is a stale-universe sample, not a true point-in-time index.

## Parameters to Test

None. The primary has no free parameters beyond the decile cutoff, and the decile table shows no cutoff would rescue the gainer side.

## Capital and PDT Compatibility

- **Minimum capital required:** not applicable, strategy retired.
- **PDT impact:** none, positions are held overnight.
- **Position sizing:** would be equal weight across about 85 signal names per day; at $25K that is below $300 per name, which alone makes it impractical.

## Pre-Flight Gate Checklist

| Gate | Result | Evidence |
|---|---|---|
| PF-1 Trades >= 120 per 3-month window | **PASS** (count only) | Median 5,363 per quarter, but the edge per trade is negative, so the pass is moot. |
| PF-2 Long-only MDD stress < 40% | **FAIL (proxy)** | IS MDD -48.5% including March 2020, above the 40% test and the 30% Track A ceiling. The dot-com and GFC windows cannot be tested on a 2018 universe without survivorship bias. |
| PF-3 Daily OHLCV only | **PASS** | Daily open, high, low, close, volume. Alpaca returns bars for delisted names; 71 tickers have no bars. |
| PF-4 Rate-shock plausibility (2022) | **FAIL (a priori)** | Written without inspecting 2022 data. Gainers in a falling market are high-beta rebounds that tend to fade; the observed IS pattern already shows gainers below baseline, so a rate-shock bear market gives no reason to expect a positive net edge. |

## Gate 1 Outlook

- IS Sharpe > 1.0: **no** (0.16 gross).
- Net profit per trade > 15 bps (Track A floor): **no** (-8.7 bps at 10 bps cost, -18.7 bps at 20 bps).
- Cost-to-gross ratio < 0.25: **no** (gross edge below cost).
- OOS persistence: not tested (no OOS access); nothing to persist.
- Sensitivity risk: low, because the result is flat across universe and delisting treatments.
- Known overfitting risks: none material; the issue is the absence of an effect, not an inflated one.

## Recommendation

**Retire. Do not send to Engineering.**

1. The plain overnight gainer effect does not survive a delisting-inclusive universe. More precisely, it was not present in the Alpaca data on either the survivor subset (+0.7 bps) or the full universe (+1.3 bps), against a 7.9 bps baseline.
2. Survivorship bias in the 92 universe is only about 0.6 bps; it does not explain the 92 result. The 92 figure of +13.3 bps could not be reproduced and should be treated as unverified.
3. Lead for the Research Director, not a hypothesis: the decile table shows the lowest-return decile earning about +22 bps overnight. At 10 bps cost that is roughly +12 bps net, still under the 15 bps floor, with heavy distressed-name tail risk (worst single overnight -91%). It would need its own pre-registered hypothesis with a tail-risk control before any test. I did not mine it further here to avoid unplanned multiple testing.

## References

- Berkman, H., Koch, P., Tuttle, L., Zhang, Y. (2012). "Paying attention: Overnight returns and the hidden cost of buying at the open." *JFQA* 47(4), 715-741.
- Lou, D., Polk, C., Skouras, S. (2019). "A tug of war: Overnight versus intraday expected returns." *JFE* 134(1), 192-213.
- Jegadeesh, N. (1990). "Evidence of predictable behavior of security returns." *Journal of Finance* 45(3), 881-898.
- Lehmann, B. (1990). "Fads, martingales, and market efficiency." *QJE* 105(1), 1-28.
- Data: Alpaca daily bars (SIP, adjustment=all), universe file `data/h82v2_universe_2018_jan.csv` (commit 6b4c7bd), cache `backtests/h93_cache/daily.csv`.
- Related: `92_ta_overnight_gainer_screen_sp500.md`, `91_ta_overnight_reversal_gainer_spy_qqq.md`.
