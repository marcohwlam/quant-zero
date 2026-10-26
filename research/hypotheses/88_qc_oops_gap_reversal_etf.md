# Oops! Gap Reversal on Liquid Index ETFs

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-10-26
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Overnight gaps that open beyond the prior day's range are largely driven by thin pre-market liquidity and headline overreaction. Retail and stop-driven order flow pushes the open to an extreme, and liquidity providers fade it as regular-session depth arrives. Larry Williams' "Oops!" pattern formalizes this: a gap below the prior low that then trades back up through the prior low is a failed breakdown (a trapped-seller signal). The mirror case applies to gap-ups. Supporting evidence: Gao, Han, Li, Zhou (2018) on intraday reversal and overnight/intraday return decomposition; Lou, Polk, Skouras (2019) on overnight versus intraday return components. Evidence for this exact daily-bar rule is practitioner-level (Williams, *Long-Term Secrets to Short-Term Trading*), so out-of-sample persistence is unproven.

## Entry/Exit Logic

**Entry signal (long):**
- Open < prior day Low by at least 0.25 x ATR(14)
- Price trades back above prior day Low intraday (daily bar proxy: Close > prior Low, i.e. the day closes back inside the prior range; entry at the prior Low via stop order is not replicable on daily bars, so entry is at the day's Close)
- Prior Close > SMA(200) (long side only trades in uptrends)

**Entry signal (short, optional variant, ETF inverse or flat only):** mirror image; skip in base version (long-only).

**Exit signal:**
- Exit at next day Close, or at first Close above prior day High (whichever comes first)
- Hard stop: Close below the gap-day Low
- Time stop: 3 trading days

**Holding period:** Swing (1-3 days)

## Market Regime Context

Works best in orderly, range-bound or mildly trending markets with moderate VIX (15-30). Fails in crash regimes where gap-downs are followed by continuation (Mar 2020, Oct 2008). Pause when VIX > 35 or SPY < SMA(200) by more than 10%.

## Alpha Decay

- **Signal half-life (days):** ~1-2 (estimate, no decay fit yet)
- **Edge erosion rate:** fast (<5 days)
- **Recommended max holding period:** 3 days (2x half-life)
- **Cost survival:** marginal; ETF spreads of 1 bp and commission-free brokerage make costs small, but average gross edge per trade is likely 20-40 bp
- **Notes:** Vol-scaled IR estimate: ~0.4% edge per trade, ~12 trades/year per ETF, 8 ETFs, annualized vol of the sleeve ~8%; expected IR ~0.4-0.6 pre-cost (above the 0.3 warning level, to be confirmed). Signal crowding is a risk because the pattern is widely published.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| gap_atr_mult | 0.1 - 0.75 | Gap size threshold relative to ATR(14) |
| trend_filter_sma | 100 - 200 | Uptrend filter |
| max_hold_days | 1 - 3 | Decay horizon |
| vix_cap | 30 - 40 | Crash-regime pause |

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000
- **PDT impact:** None. Entry at Close and exit at a later Close are overnight holds, not day trades.
- **Position sizing:** 10% of portfolio per ETF, max 4 concurrent positions

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** No single algorithm. QC community has multiple "Gap Reversal / Gap Fill" implementations and Williams "Oops" ports in the Algorithm Library and forum; URLs not verified in this file-only run and must be confirmed by Engineering before citing.
- **QC backtest window and IS cherry-pick risk:** Community gap strategies typically show 2012-2019 results on SPY with minute data; this window is a low-vol bull market that flatters fade strategies. Discount any reported Sharpe > 1.5.
- **Adaptation to framework and data source:** Rewritten for daily OHLCV (yfinance), entry at Close. Original QC versions use minute bars with intraday stop entry, which this pipeline does not replicate. Expect lower gross edge than QC claims.
- **Top-10 clone / crowding confirmation:** Not confirmed to be outside the top-10 most cloned; gap-fill logic is a common QC tutorial pattern. Crowding risk flagged as moderate-high.

## Pre-Flight Checklist

### PF-1: Walk-Forward Trade Viability
- 8 ETFs (SPY, QQQ, IWM, DIA, XLF, XLK, XLE, XLV), ~12 qualifying events per ETF per year (estimate) = ~96 trades/year, ~1,900 over a 2000-2019 IS window; ÷4 = ~480 per fold.
- **[x] PF-1 PASS (estimate; to be verified by event count on real data)**

### PF-2: Long-Only MDD Stress Test
- SMA(200) filter blocks most 2000-2002 and 2008-2009 entries; 3-day time stop and low gross exposure (max 40%) bound drawdown.
- Estimated worst-case MDD in each period: 15-20% (proxy: SPY SMA(200) filter would have been flat for most of both episodes).
- **[x] PF-2 PASS (conditional on SMA(200) filter being kept in the base spec)**

### PF-3: Data Pipeline Availability
- Requires daily Open, High, Low, Close only. All available from yfinance for 2000+ (sector ETFs from 1999).
- **[x] PF-3 PASS**

### PF-4: Rate-Shock Regime Plausibility (2022)
- A priori argument: 2022 had frequent large overnight gaps driven by CPI and FOMC headlines, followed by intraday reversals (bear market rally dynamics). However, SPY was below SMA(200) for most of 2022, so the trend filter disables the strategy, producing a flat year rather than a positive one.
- Positive return in 2022 is therefore not claimed. The strategy avoids the regime rather than profits from it.
- **[!] PF-4 WEAK PASS: capital preservation only. If the Research Director requires positive 2022 returns, drop the SMA(200) filter and add the short side, which raises overfitting risk.**

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely (expect 0.5-0.9)
- OOS persistence: uncertain; published pattern, likely decayed
- Walk-forward stability: likely moderate; many trades support it
- Sensitivity risk: medium (gap threshold)
- Known overfitting risks: gap and trend-filter thresholds; daily-bar proxy for an intraday pattern; survivorship is low for index ETFs

## References

- Williams, L. (1999). *Long-Term Secrets to Short-Term Trading*. Wiley.
- Lou, D., Polk, C., Skouras, S. (2019). "A Tug of War: Overnight Versus Intraday Expected Returns." *Journal of Financial Economics*.
- Gao, L., Han, Y., Li, S., Zhou, G. (2018). "Market Intraday Momentum." *Journal of Financial Economics*.
- Related: `45_qc_nr7_volatility_compression_breakout`, `46_qc_overnight_return_anomaly`
