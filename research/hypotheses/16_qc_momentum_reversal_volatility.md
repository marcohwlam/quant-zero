# Momentum + Reversal Combined with Volatility Effect (Long-Short Equities)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

The cross-sectional momentum anomaly (Jegadeesh & Titman 1993) is stronger among high-volatility stocks, while low-volatility stocks exhibit mean reversion. The key insight from Cao & Han (2016) is that investor attention and information asymmetry are concentrated in high-volatility names, amplifying both momentum continuation and eventual reversal. By restricting the momentum signal to the top-20% most volatile large-cap stocks, the strategy targets the segment where behavioral biases (underreaction, herding) are most pronounced and where the momentum effect is statistically robust.

The long-short structure harvests the spread between high-vol/high-momentum winners and high-vol/low-momentum losers, with the volatility pre-filter acting as a "relevance screen" that improves signal-to-noise. Academic evidence: Cao & Han (2016) document annualized long-short returns of ~15% (6-month formation, 6-month holding) for large-cap high-volatility quintile sorts. This strategy is documented in the QuantConnect Investment Strategy Library as a direct implementation of their findings.

## Entry/Exit Logic

**Entry signal:**
- Universe: NYSE/NASDAQ/AMEX large-cap stocks (market cap above median), price > $5
- Monthly: compute 6-month realized return and 6-month realized volatility for all universe stocks
- Sort by volatility → keep top 20% (highest realized vol group)
- Within the high-vol group, sort by 6-month return → quintile split
- **Long:** top quintile (Q5, highest 6m return within high-vol group), equal-weighted
- **Short:** bottom quintile (Q1, lowest 6m return within high-vol group), equal-weighted
- Rebalance monthly

**Exit signal:**
- Monthly rebalance closes existing longs/shorts and re-enters based on updated quintile rankings
- No intra-month exits; rely on rebalance cycle for all position management

**Holding period:** Swing — 1 month per cycle (standard momentum holding period)

## Market Regime Context

**Works best in:** trending, moderately volatile markets with cross-sectional dispersion. Works in both bull and bear trends if the high-vol group has clear winners/losers. Best when VIX is 15–30 (enough vol for differentiation, not so much that correlations collapse to 1).

**Works poorly in:** high-correlation panic regimes (VIX >40) where all high-vol stocks move together, eliminating the spread. Also deteriorates in low-dispersion, low-vol regimes (VIX <12) where the high-vol group shrinks or contains noise. The January effect causes short-term reversal in January for prior-year losers — rebalancing in January may underperform.

**Regime pause rule:** Skip rebalancing if realized cross-sectional dispersion (std of monthly returns) is in the bottom 10th percentile over trailing 12 months. Consider a VIX range filter: pause if VIX > 40.

## Alpha Decay

- **Signal half-life (days):** ~15 trading days (within the 21-day monthly holding period; IC peaks in first 2 weeks then decays)
- **Edge erosion rate:** moderate (5–20 days) — momentum in high-vol stocks is shorter-lived than broad market momentum
- **Recommended max holding period:** 21 trading days (1 calendar month); do not extend to 2-month holds
- **Cost survival:** marginal — long-short equity with monthly rebalancing incurs two round-trips per position per year. At $25K, turnover is high relative to capital; short-selling borrow costs add ~1–2% annually on the short leg. Estimated total friction: 2–4% per year. The 6-month IC is ~0.03–0.05 → annualized alpha estimate 8–12% pre-cost. Post-cost survival: **marginal** but possible with tight execution.
- **Annualized IR estimate:** ~0.5–0.8 post-cost at $25K scale. Below 1.0 benchmark but above 0.3 disqualifier.
- **IC decay curve (T+N trading days):** T+1: ~0.04, T+5: ~0.035, T+20: ~0.02 (signal largely expired by month end)
- **Notes:** The high-vol filter creates a selection bias toward smaller, more expensive names to borrow. Practical short availability is a risk at $25K scale. Consider long-only variant with the short replaced by under-weighting.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| Formation period (months) | 3–9 | Jegadeesh & Titman optimal is 6; test 3 and 9 |
| Volatility filter percentile | Top 10%–25% | Top 20% is literature default; test sensitivity |
| Holding period (months) | 1–3 | Standard 1-month; test 2 and 3 |
| Universe size filter | Median cap vs top-quartile | Larger cap = better liquidity but smaller universe |
| Long-only variant | Long Q5 only vs. Long-Short | PDT and borrow-cost alternative |

## Capital and PDT Compatibility

- **Minimum capital required:** ~$15,000 for long-only variant; ~$25,000 minimum for long-short (requires margin account)
- **PDT impact:** Low risk — monthly rebalancing at month-start. One or two position changes per month. No day trades in normal operation. However, if rebalancing is implemented as closing old positions and opening new ones on the same day, that counts as day trades. Execute over 2 days (close T+0, open T+1) to avoid PDT triggers.
- **Position sizing:** Equal-weight across Q5 longs and Q1 shorts. With $25K: at 5 long / 5 short positions → $2,500 per position. Max concurrent: 10 positions (5 long, 5 short).
- **Short selling note:** Requires a margin account with short-selling approved. Not compatible with a cash account.

## QuantConnect Source Caveat

- **Original QC strategy name:** "Momentum and Reversal Combined with Volatility Effect in Stocks"
- **QC URL:** https://www.quantconnect.com/learning/articles/investment-strategy-library/momentum-and-reversal-combined-with-volatility-effect-in-stocks
- **Research notebook:** https://www.quantconnect.com/research/15356/momentum-and-reversal-combined-with-volatility-effect-in-stocks/
- **Apparent backtest window:** 2007–2021 (estimated); covers both bull market and 2008 crisis — more robust than strategies tested only in bull runs
- **Clone/popularity rank:** Official QC Strategy Library (not community clone); moderate public awareness via Quantpedia listing. Not in top-10 most-cloned; crowding risk low.
- **Novel signal vs. H01–H14:** Distinct from H03 (multi-factor long-short) which uses fundamental factors (value, quality). H16 is a purely price-based cross-sectional momentum strategy with a volatility pre-filter — the vol-sort gate is the key differentiator. Distinct from H05 (momentum vol-scaled) which scales a single-name signal by its own vol rather than using vol as a universe filter for a long-short portfolio. Not structurally overlapping with any H01–H14.
- **Cherry-pick risk:** The QC implementation backtested over a period of sustained cross-sectional dispersion. Test with 2020 COVID crash period to verify the drawdown is within tolerance.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Unlikely at $25K net of costs. Literature documents ~0.8–1.2 gross; post borrow/commission friction likely reduces to 0.5–0.8. **Marginal pass; likely fail at tight threshold.**
- **OOS persistence:** Likely — effect documented since 1993 and persists in recent data. Crowding risk is low (strategy is not mass-deployed at retail scale).
- **Walk-forward stability:** Likely — monthly rebalancing with simple quintile sort is not hyperparameter-sensitive.
- **Sensitivity risk:** Low-medium — main sensitivities are formation period (3 vs. 6 vs. 9 months) and volatility filter percentile (15% vs. 20% vs. 25%).
- **Known overfitting risks:** Single parameter set (6m/20%/1m) derived from one academic paper. Cross-validate with at least 2 other formation/holding combinations. The $25K universe will be thin (few high-vol large-caps meet all filters simultaneously), introducing concentration risk.
- **Practical constraint risk:** Short availability and borrow costs are hard to backtest accurately in vectorbt/yfinance. A long-only variant (buy Q5 only) may be more practical for Gate 1 and live trading.

## References

- Jegadeesh, N. & Titman, S. (1993). "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency." *Journal of Finance*, 48(1), 65–91.
- Cao, J. & Han, B. (2016). "Idiosyncratic Risk, Costly Arbitrage, and the Cross-Section of Stock Returns." *Journal of Financial Economics*, 119(3), 519–536.
- QC Learning: https://www.quantconnect.com/learning/articles/investment-strategy-library/momentum-and-reversal-combined-with-volatility-effect-in-stocks
- QC Research: https://www.quantconnect.com/research/15356/momentum-and-reversal-combined-with-volatility-effect-in-stocks/
- Quantpedia: https://quantpedia.com/strategies/momentum-and-reversal-combined-with-volatility-effect-in-stocks
- Related in knowledge base: H03 (multi-factor long-short), H05 (momentum vol-scaled)
