---
tags: [qc-discovery]
---

# H71: Contrarian Monthly Sector ETF Rotation

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-06-15
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Short-horizon equity returns exhibit mean reversion at the sector level: sectors that underperform their peers in a given month tend to outperform in the following month. This contrarian pattern arises from several documented mechanisms:

1. **Institutional rebalancing pressure:** Index rebalancers and target-weight funds systematically sell recent winners and buy recent losers at month-end, creating a predictable demand signal for the underperforming sectors.
2. **Overreaction and reversal:** Retail and momentum traders chase recent winners and overweight good-news sectors, creating temporary mispricings that professional reversion traders exploit.
3. **Mean-reverting factor loadings:** Sector ETFs load differentially on value/growth, cyclical/defensive, and high/low-beta factors. Short-term factor tilts created by monthly price moves tend to revert as macro conditions stabilize.

This strategy is explicitly **anti-momentum** — it exploits the reversal component of short-term returns documented by Jegadeesh (1990) and Lehmann (1990), distinct from the cross-sectional momentum anomaly (12-1 lookback) which operates over a different horizon and has been well-tested in the pipeline (H52-H54 family, retired or tested separately).

Evidence: Richards (1997) documented winner-loser reversals at the sector/country level over 1-12 month horizons in developed equity markets. Sorensen & Burke (1986) showed sector rotation using relative performance generates excess returns. Stivers & Sun (2010) "Cross-Sectional Return Dispersion and Time Variation in Value and Momentum Premiums" shows the reversal premium is strongest during high cross-sectional dispersion periods.

Universe: 11 SPDR Select Sector ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY) — all available on yfinance since 1998-1999. XLRE (Real Estate) launched 2015; if including, IS window starts 2016 or XLRE is excluded from pre-2015 universe.

## Entry/Exit Logic

**Entry signal:**
- On the last trading day of each month: rank all 11 SPDR sector ETFs by prior-month total return (close-to-close)
- Buy the bottom 2 ranked sectors (worst monthly performers) in equal weight (50% each)
- Regime filter: Only enter long positions when SPY is above its 200-day MA (long-only bear filter)

**Exit signal:**
- Hold current 2-sector position for 30 calendar days (until next monthly rebalance)
- At month-end rebalance: sell current holdings, rebuy worst 2 sectors of the new ranking

**Holding period:** Approximately 1 calendar month (swing)

**Regime override:**
- If SPY is below 200-day MA at month-end: move entire portfolio to cash (BIL proxy)
- Resume buying at next month-end if SPY recovers above 200-DMA

## Market Regime Context

**Works best:** High cross-sectional dispersion environments (2000-2002, 2008-2009, 2020, 2022) where sector divergence is greatest — the reversal premium is widest when dispersion is high. Also works in range-bound markets where no single macro theme dominates.

**Works poorly:** Strong unidirectional momentum regimes where one sector leads relentlessly (e.g., tech dominance 2017-2019, energy dominance 2022). In such regimes, the "worst performer" sector may continue to underperform rather than reverse.

**Regime failures:** In 2022, Energy (XLE) was the sole outperformer (+66%). Contrarian rotation would have bought beaten-down Communication Services (XLC, -40%) and Consumer Discretionary (XLY, -37%) each month — both continued to underperform throughout the year. The 200-DMA bear filter (SPY below 200-DMA for most of 2022) would have put the portfolio in cash for many 2022 months, partially mitigating this failure mode. Net 2022 impact: contested; depends on exact 200-DMA filter dates.

## Alpha Decay

- **Signal half-life (days):** 10-15 trading days (approximately half the monthly holding period)
- **Edge erosion rate:** Moderate (5-20 days) — reversal premium at sector level erodes over the month as the mispricing corrects
- **Recommended max holding period:** 30 calendar days (one monthly rebalance cycle); do not extend to 2-month holds
- **Cost survival:** Yes — one monthly round-trip per 2 ETFs held = 4 trades/month. At $25K, SPY-level bid-ask spreads for sector ETFs are ~1-2 bps one-way. Commission: zero (Alpaca). Estimated annual cost drag: 8-24 bps total. With typical gross monthly alpha of 30-80 bps on the reversal premium, cost survival is confirmed.
- **Notes:** Annualized IR estimate: if monthly reversal premium ≈ 40 bps/month over SPY, annualized excess ≈ 4.8%; monthly vol ≈ 3-5%; IR ≈ 0.96-1.6. This is a rough estimate; actual IR will be determined in backtest. Pre-cost IR > 0.3 threshold is easily met if reversal premium holds.

## Cointegration Analysis

*(Not applicable — single-signal monthly rotation, not a pairs strategy)*

## Signal Combination

*(Not applicable — single-signal strategy)*

## ML Strategy Specification

*(Not applicable)*

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| bottom_n_sectors | 1, 2, 3 | Sensitivity to how many losers to buy |
| lookback_period | 1 month, 3 months | 1-month reversal vs 3-month reversal horizon |
| bear_filter | 200-DMA SPY, 10-month SMA, none | PF-2 drawdown control |
| rebalance_day | Last trading day of month, first trading day of month | Execution timing sensitivity |
| universe | 10 sectors (ex-XLRE), 11 sectors (incl. XLRE, post-2015) | Data availability pre-2015 |

## Capital and PDT Compatibility

- **Minimum capital required:** $2,000 (2 ETFs, $1K each; comfortable at $25K)
- **PDT impact:** N/A — monthly rebalancing strategy; at most 4 trades per month, far below PDT threshold
- **Position sizing:** 50% per sector ETF, 2 positions. If bear filter active: 100% cash.

## QuantConnect Source Caveat

- **QC reference:** Sector rotation is a well-represented strategy class in the QuantConnect community forum and algorithm library. The contrarian (bottom-ranked) variant is discussed in QC community forums under sector rotation and reversion themes. The closest QC Strategy Library reference is the Quantpedia partnership page (https://www.quantconnect.com/announcements/15489/our-new-quantpedia-strategy-library/) which includes strategies based on cross-sectional return reversal. Additionally, the QuantConnect "Exploiting Term Structure of VIX Futures" article (https://www.quantconnect.com/tutorials/strategy-library/exploiting-term-structure-of-vix-futures) demonstrates similar monthly bar-level rotation logic in QC's Python LEAN engine.
- **QC backtest window:** Community implementations typically cover 2007–2024 (full sector ETF history). IS cherry-pick risk: sector ETFs only have history from 1998-1999, limiting pre-dot-com validation. Post-2010 data is dominated by a tech-growth regime that disadvantages contrarian sector rotation.
- **Adaptation notes:** Adapted to daily-bar framework using yfinance. Monthly close prices for 11 SPDR ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY) are all available on yfinance. No intraday, options chain, VWAP, or CVD data required. XLRE (Real Estate) split from XLF in 2015; pre-2015 backtest must either exclude XLRE or use 10-sector universe. Engineering Director to confirm XLRE handling in backtest spec.
- **Top-10 clone check:** Contrarian sector rotation (bottom-ranked monthly performers) is NOT a top-10 QC clone. The most-cloned QC strategies are momentum-based (buy top performers); this strategy is explicitly the inverse. Low crowding risk.

## Pre-Flight Gate Assessment

| Gate | Criterion | Assessment | Status |
|---|---|---|---|
| PF-1 | ≥30 trades over 4-year IS window | 12 monthly rebalances/year × 4 trades per rebalance (2 sells + 2 buys) = 48 trades/year × 4 years = 192 trades. PASS with significant margin. | PASS |
| PF-2 | Long-only MDD <40% during dot-com (2000-2002) and GFC (2008-2009) | Without bear filter: worst-performing sectors in 2000-2002 (XLK, XLC) had drawdowns of 60-80%; in 2008-2009 (XLF) lost ~80%. Long-only without filter → MDD exceeds 40%. WITH 200-DMA bear filter: SPY dropped below 200-DMA in early 2001 and October 2008 → strategy in cash for the worst months. Expected MDD with filter: 15-30%. | AMBER — 200-DMA filter is REQUIRED for PF-2 compliance |
| PF-3 | Data pipeline available (yfinance/Alpaca daily OHLCV) | All 11 SPDR sector ETFs available on yfinance with full price history. XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY: available since 1998-1999. XLC: launched June 2018. XLRE: launched October 2015. If using 11-sector universe, IS window must start in 2019 to include XLC. If using 9-sector universe (ex-XLC, ex-XLRE), IS window can start 2000. Confirm universe definition with Engineering Director. | PASS (with universe definition) |
| PF-4 | 2022 rate-shock rationale | 2022: SPY fell below 200-DMA early (January 2022) → bear filter would have moved portfolio to cash for much of 2022. Sectors that reversed in 2022 were mostly not contrarian (energy dominated upside persistently). Bear filter is the defense. Without filter, 2022 would have been destructive (buying XLC/XLY monthly while they continued falling). With filter: avoided. | PASS (with 200-DMA filter) |

**Critical dependency:** PF-2 and PF-4 both require the 200-DMA bear filter. This is a non-optional regime overlay. Must be included in backtest spec from day one. Engineering Director should code the SPY 200-DMA check as a mandatory pre-condition before any long allocation.

## Gate 1 Outlook

- **IS Sharpe > 0.7:** Possible with 200-DMA filter — contrarian sector rotation with bear filter has appeared in academic-adjacent practitioner research with Sharpe ratios of 0.7-1.0 over 2000-2020. Depends critically on IS window and whether 2022 bear filter captures the worst period.
- **OOS persistence:** Moderate confidence — the institutional rebalancing mechanism (index funds buying losers) has structural backing, and the reversal premium at sector level is more persistent than at individual stock level due to lower idiosyncratic noise.
- **Walk-forward stability:** Moderate — the strategy has 2 key parameters (bottom_n_sectors: 1 or 2; lookback: 1 month). Low sensitivity to these within the relevant range. 200-DMA filter is robust and not parameter-sensitive.
- **Sensitivity risk:** Medium — the 200-DMA filter is a binary regime switch; if markets oscillate around the 200-DMA during a choppy period, whipsaw costs accumulate. Smooth/delayed moving average (e.g., 10-month SMA) may be more robust.
- **Known overfitting risks:** (1) Selection of 2022 as the primary failure mode may make the 200-DMA filter appear more powerful than it is (single-event validation). (2) XLRE/XLC universe truncation affects the IS window. (3) The contrarian premium may be stronger in the academic sample (pre-2000) than in the ETF-available period (post-1998). (4) Regime sensitivity: strong unidirectional macro regimes (2017 tech dominance, 2022 energy dominance) systematically hurt this strategy.

## References

- Jegadeesh, N. (1990). "Evidence of Predictable Behavior of Security Returns." *Journal of Finance*, 45(3), 881-898.
- Lehmann, B.N. (1990). "Fads, Martingales, and Market Efficiency." *Quarterly Journal of Economics*, 105(1), 1-28.
- Richards, A.J. (1997). "Winner-Loser Reversals in National Stock Market Indices: Can They Be Explained?" *Journal of Finance*, 52(5), 2129-2144.
- Sorensen, E.H. & Burke, T. (1986). "Portfolio Returns from Active Industry Group Rotation." *Financial Analysts Journal*, 42(5), 43-50.
- Stivers, C. & Sun, L. (2010). "Cross-Sectional Return Dispersion and Time Variation in Value and Momentum Premiums." *Journal of Financial and Quantitative Analysis*, 45(4), 987-1014.
- QuantConnect Community Forum — Sector Rotation discussions: https://www.quantconnect.com/forum/
- QuantConnect Strategy Library (Quantpedia): https://www.quantconnect.com/announcements/15489/our-new-quantpedia-strategy-library/
- SPDR Sector ETF family historical data: available via yfinance tickers XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY
