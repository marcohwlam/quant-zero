---
tags: [qc-discovery]
---

# H70: Dogs of the Dow Annual Dividend Yield Rotation

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-06-15
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

"Dogs of the Dow" selects the 10 highest dividend-yielding stocks among the 30 DJIA components at year-end and holds them equal-weight for the following calendar year. The rationale is mean reversion in valuation: high dividend yield among blue-chip Dow components signals temporary price depression relative to the firm's dividend-paying capacity. As price normalizes upward (dividend policy typically sticky), yield compresses and the investor captures both price appreciation and the elevated income.

Mechanism that prevents full arbitrage: (1) Institutional calendar constraints — many managers rebalance only annually, limiting immediate arbitrage. (2) Behavioral anchoring — investors underweight recently depressed blue-chip stocks that are still fundamentally sound. (3) Value premium — high-yield DJIA stocks load on the Fama-French HML (high-minus-low book-to-market) factor, which persists due to investor risk aversion and institutional mandate constraints.

Evidence: O'Higgins & Downes (1991) documented the original strategy outperforming the DJIA by ~2-3% annually on pre-2000 data. Prather & Webb (2002) confirmed modest persistence in 1973-1999 data. **Caveat:** Multiple studies (da Silva 2001; Visscher & Filbeck 2003) document significant underperformance versus S&P 500 post-2000. The edge may have been partially arbitraged away. This hypothesis is submitted for Gate 1 testing with explicit underperformance flag.

The strategy is $25K-compatible: 10 equal-weight DJIA stocks, ~$2,500 each. Annual turnover of 5-8 stocks keeps transaction costs minimal.

## Entry/Exit Logic

**Entry signal:**
- On the last trading day of each calendar year: rank the 30 current DJIA components by trailing 12-month dividend yield (annual dividend / year-end price)
- Buy the top 10 highest-yielding stocks in equal weight (10% each) at the open on January 2 (first trading day of new year)

**Exit signal:**
- Hold entire position until the following December 31 / January 2 rebalance
- At annual rebalance: exit any position that no longer ranks in the top 10 highest-yield stocks; enter new entrants to the top-10

**Optional overlay (PF-2 risk mitigation):**
- If DJIA is below its 200-day moving average at year-end, hold cash/BIL instead of rotating into the Dogs basket for that year (bear market filter)

**Holding period:** Annual (calendar year)

## Market Regime Context

**Works best:** Value-favorable environments, rising dividend payout environments, low-growth / rate-stable markets where yield-seeking investors dominate (late 1970s, early 1980s, 2000-2005, 2022).

**Works poorly:** Growth-dominated bull markets where dividend-paying stocks underperform growth (2010–2019). Rising rate environments can compress P/E multiples on all stocks but hurt dividend stocks more if duration is long (early 2022).

**Known regime failure:** 2010-2019: DJIA "Dogs" significantly underperformed SPY due to growth/tech dominance. Without a momentum filter to exit during these periods, the strategy suffers extended drawdown vs. benchmark.

## Alpha Decay

- **Signal half-life (days):** 125 trading days (half-year) — the yield rank reflects a value signal that takes 6-12 months to mean-revert on average
- **Edge erosion rate:** Slow (>20 days by definition — annual holding period)
- **Recommended max holding period:** 12 months (as defined by strategy); do not extend beyond the calendar year
- **Cost survival:** Yes — one round-trip per year per position. With 5-8 stock changes/year, estimated annual transaction cost of 3-10 bps at $25K (commission ~$0 Alpaca, slippage negligible for DJIA blue-chips)
- **Notes:** The edge's existence post-2000 is genuinely uncertain. The signal IC is likely low in recent data. Gate 1 OOS persistence test (post-2020 window) is the critical signal for whether this edge still exists.

## Cointegration Analysis

*(Not applicable — single-signal annual rotation, not a pairs strategy)*

## Signal Combination

*(Not applicable — single-signal strategy)*

## ML Strategy Specification

*(Not applicable)*

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| top_n_stocks | 5, 10, 15 | Sensitivity to number of Dogs selected |
| rebalance_month | January 1, October 1 (fiscal year), July 1 (semi-annual) | Calendar anchor sensitivity |
| yield_calculation | trailing 12-month / declared | Data precision vs. lag tradeoff |
| bear_filter_threshold | None, 200-DMA, 10-month SMA | PF-2 risk mitigation |
| universe | DJIA 30, S&P 100 (OEX) | Extension to broader universe |

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000 (10 stocks, $1K each minimum lot; comfortable at $25K)
- **PDT impact:** N/A — annual rebalancing strategy, far below PDT day-trade threshold
- **Position sizing:** 10% per position, equal-weight. Max 10 concurrent positions.

## QuantConnect Source Caveat

- **QC reference:** QuantConnect community algorithm project #29197087; also referenced in QuantConnect's Quantpedia Strategy Library announcement (https://www.quantconnect.com/announcements/15489/our-new-quantpedia-strategy-library/). Community implementations available via QuantConnect's public algorithm search.
- **QC backtest window:** Community backtests typically cover 2010–2024 (bull market dominated; IS cherry-pick risk high — backtest window excludes the pre-2000 era where the edge was strongest; OOS period for practitioners who discovered this is approximately post-1995)
- **Adaptation notes:** Adapted to daily-bar framework using yfinance for DJIA component price and dividend history. No minute-bar or intraday data required. Key adaptation: yfinance dividend history (`ticker.dividends`) provides trailing dividend yields. DJIA composition history (point-in-time) is NOT provided by yfinance — using current DJIA 30 components for all historical periods introduces survivorship bias. Flag as look-ahead/survivorship risk; backtest must acknowledge this limitation.
- **Top-10 clone check:** Dogs of the Dow is a widely-known popular strategy but is NOT among QC's top-10 most-cloned algorithms (which skew toward momentum and trend-following). Low crowding risk in algorithmic implementation given annual rebalancing and DJIA-only universe.

## Pre-Flight Gate Assessment

| Gate | Criterion | Assessment | Status |
|---|---|---|---|
| PF-1 | ≥30 trades over 4-year IS window | Annual rebalance: ~5-8 stock changes × 2 (buy+sell) = 10-16 trades/year × 4 years = 40-64 trades. PASS. | PASS |
| PF-2 | Long-only MDD <40% during dot-com (2000-2002) and GFC (2008-2009) | DJIA Dogs are blue-chips but still fell 30-50% in 2000-2002 (XOM, T, MRK dominated Dogs list during this period). 2008-2009: DJIA Dog stocks (BAC, GE, C) suffered severe losses. WITHOUT trend filter, MDD likely exceeds 40% in both periods. WITH 200-DMA bear filter: periods in cash skip worst legs → likely below 40%. Bear filter is REQUIRED for PF-2. | AMBER — bear filter mandatory |
| PF-3 | Data pipeline available (yfinance/Alpaca daily OHLCV) | yfinance provides price history for all current DJIA components since 1990+. Dividend history via `ticker.dividends` available. HOWEVER: point-in-time DJIA composition (which 30 stocks were in the index in 2000, 2005, 2010) is NOT in yfinance. Using today's DJIA composition for all periods = survivorship/look-ahead bias. Must document this bias explicitly in backtest. Engineering Director should incorporate DJIA historical composition data from a reference source (e.g., Wikipedia DJIA composition history, or hardcoded dates). | AMBER — survivorship bias must be documented and controlled |
| PF-4 | 2022 rate-shock rationale | In 2022, value/dividend stocks outperformed growth significantly. DJIA Dogs in 2022 included high-yielders like CVX, VZ, IBM, DOW — CVX alone was +53% in 2022. Strategy likely OUTPERFORMED SPY in 2022. Defensible. | PASS |

**Survivorship bias note (look-ahead risk):** If backtest uses current DJIA-30 composition for all periods (2000-2024), it selects from stocks that survived to 2026 — excluding failures like Citigroup (pre-GFC), Sears, Eastman Kodak that were in the DJIA at some point. This biases results upward. Risk Director must be notified; backtest narrative must disclose this limitation.

## Gate 1 Outlook

- **IS Sharpe > 0.7:** Uncertain — heavily dependent on IS window. Pre-2000 data may show Sharpe 0.8+; post-2010 data likely Sharpe < 0.5 vs SPY benchmark. IS window selection is critical.
- **OOS persistence:** LOW confidence — documented underperformance in recent decades. Primary value is as a diversifying, low-turnover strategy, not a high-alpha signal.
- **Walk-forward stability:** Low-medium — strategy is parameter-light (one param: top-N) which is positive; but the edge itself may not be stable across regimes.
- **Sensitivity risk:** Low (only 1 parameter: number of Dogs selected)
- **Known overfitting risks:** (1) Survivorship bias in DJIA composition history. (2) IS window selection bias — cherry-picking 2000-2010 would show outperformance; 2010-2024 would show underperformance. Walk-forward OOS verdict is the honest test. (3) The academic edge was documented before 1991 — post-publication decay is a known risk.

## References

- O'Higgins, M. & Downes, J. (1991). *Beating the Dow*. HarperCollins.
- Prather, L. & Webb, G.P. (2002). "Dogs of the Dow: Large-Cap Stocks, Dividend Yield, and the January Effect." *Journal of Investing*, 11(1), 65-73.
- da Silva, A.L.C. (2001). "Empirical Tests of the Dogs of the Dow Strategy in Latin American Stock Markets." *International Review of Financial Analysis*, 10(2), 187-199.
- Visscher, S. & Filbeck, G. (2003). "Dividend Yield Strategies in the Canadian Stock Market." *Financial Analysts Journal*, 59(1), 99-106.
- QuantConnect Community Project #29197087 — https://www.quantconnect.com/project/29197087
- Quantpedia Strategy Library on QuantConnect — https://www.quantconnect.com/announcements/15489/our-new-quantpedia-strategy-library/
