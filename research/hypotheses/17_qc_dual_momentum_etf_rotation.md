# ETF Dual Momentum Rotation (Antonacci GEM)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Gary Antonacci's Global Equities Momentum (GEM) combines two momentum variants to extract a risk-adjusted edge:

1. **Relative momentum** (cross-sectional): compare 12-month total return of US equities (SPY) vs. international equities (EFA) to pick the stronger asset.
2. **Absolute momentum** (time-series, "trend filter"): check whether the winner has a positive return over T-bills (SHY/BIL) over the trailing 12 months. If both are negative → rotate to bonds (AGG) as the safe-harbor asset.

The mechanism: relative momentum captures the persistent performance persistence documented by Jegadeesh & Titman (1993) and extended to asset classes by Asness, Moskowitz & Pedersen (2013). Absolute momentum acts as a recession/bear-market exit rule — it switches the portfolio to bonds when equities are in a cyclical drawdown, dramatically cutting tail risk. The combination yields lower drawdowns than pure cross-sectional momentum while preserving most of the upside.

Academic support: Antonacci (2012, 2014), Asness et al. (2013) "Value and Momentum Everywhere." The strategy has been replicated extensively, including in Allocate Smartly's live tracking database and the Quantpedia library. It is structurally simple, transparent, and not hyperparameter-sensitive.

## Entry/Exit Logic

**Entry signal (evaluated monthly at close on last trading day):**
- Compute 12-month total return for: SPY (US equities), EFA (intl equities), BIL/SHY (T-bills proxy)
- Step 1 — Relative momentum: select the higher-returning asset between SPY and EFA
- Step 2 — Absolute momentum filter: if the winner's 12-month return > BIL return → invest in winner; else → invest in AGG (US aggregate bonds)
- If currently in the correct asset → hold (no change)
- If signal changes → rotate on next-day open (minimize end-of-month execution crowding)

**Exit signal:**
- Monthly signal re-evaluation triggers rotation if current holding no longer matches the signal
- No intra-month exits except for explicit catastrophic stop (e.g., circuit breakers, fund closure)

**Holding period:** Position (weeks+) — average hold ~3–6 months in equity, ~2–3 months in bonds (historically ~70% of time in equity)

## Market Regime Context

**Works best in:** strong trending regimes — sustained bull markets (relative momentum works) or sustained bear markets (absolute momentum rotates to bonds early). Strategy is designed to perform across full market cycles.

**Works poorly in:** choppy, oscillating regimes (false switches between SPY and EFA, or repeated equity↔bond rotations in a sideways market). Whipsaw risk is highest when 12-month return of SPY and EFA are near-equal. Also performs poorly in fast V-shaped crashes that recover within 1 month (e.g., COVID March 2020 — signal may exit near the bottom and re-enter near the top).

**Regime pause rule:** None — strategy is designed to be fully systematic. The absolute momentum filter is itself the regime switch. No secondary filters recommended (adding VIX overlays increases overfitting risk).

## Alpha Decay

- **Signal half-life (days):** ~30 trading days (signal is evaluated monthly; the 12-month lookback means the signal evolves slowly)
- **Edge erosion rate:** slow (>20 days) — the momentum signal at the asset-class level decays over weeks to months, not days
- **Recommended max holding period:** No explicit cap; the signal dictates the hold. Expected average: 3–6 months per leg.
- **Cost survival:** Yes — monthly rebalancing with a 1-position portfolio means at most 1 round-trip trade per month. At SPY full-position (~$25K), commission is <$2 per trade. Annual turnover ~2–4 round trips → annual cost ~$20–50 (<0.2% drag). Edge clearly survives costs.
- **Annualized IR estimate:** Antonacci (2014) documents GEM CAGR ~17% vs. S&P 13% with Sharpe ~0.9 over 1974–2013. Post-2013 live performance is lower (~8–10% CAGR, Sharpe ~0.6–0.7) as both momentum and bond returns have compressed. Post-cost IR at $25K: ~0.6–0.9. Above 0.3 threshold; potentially meets Gate 1 IS Sharpe > 1.0 in extended in-sample windows.
- **IC decay curve (T+N trading days):** T+1: ~0.05, T+5: ~0.05, T+20: ~0.04 — the 12-month signal is slow-moving; IC is relatively stable across short horizons because asset-class momentum persists for months
- **Notes:** Post-2013 performance compression is a key concern. The strategy is widely published and the ETF universe (SPY/EFA/AGG) is extremely liquid and low-cost to execute. Not sensitive to execution timing at this frequency.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| Lookback period (months) | 6–15 | Antonacci uses 12; test 6, 9, 12 |
| Asset universe | SPY/EFA/AGG vs. QQQ/EFA/AGG vs. SPY/EFA/IEF | Different risk profiles; SPY/EFA/AGG is Antonacci canonical |
| Absolute momentum hurdle | T-bill rate vs. 0% | Some variants use 0% return as the hurdle |
| Execution timing | Last day of month vs. first day of next month | Small edge from avoiding month-end flows |
| Bonds asset | AGG vs. IEF vs. SHY | Duration sensitivity test |

## Capital and PDT Compatibility

- **Minimum capital required:** $5,000 (100% in 1 ETF at a time; ETFs are liquid with no lot size constraint)
- **PDT impact:** Minimal — at most 1 trade per month, far below 3 day-trade limit. Fully compatible with $25K / PDT constraints.
- **Position sizing:** 100% of capital in the signal ETF (fully invested, no diversification across positions). This is a concentrated single-holding strategy by design — max concurrent: 1 position.

## QuantConnect Source Caveat

- **Original QC strategy name:** "Dual Momentum Technology ETF" (community forum) and multiple GEM implementations in QC forum/library
- **QC URL:** https://www.quantconnect.com/forum/discussion/10066/dual-momentum-technology-etf/
- **Apparent backtest window:** QC community implementations typically tested 2008–2023; academic backtest covers 1974–2013 using index proxies (pre-ETF period uses index returns, not actual ETF costs)
- **Clone/popularity rank:** The Antonacci GEM concept is among the most widely-known systematic strategies; it is NOT in the top-10 most-cloned QC strategies but is broadly replicated across platforms. Crowding risk at the retail level is moderate — large flows into SPY/EFA/AGG on the same monthly signal day could cause minor execution slippage.
- **Cherry-pick risk:** The published academic backtest uses pre-ETF index data (1974–1995) that cannot be replicated with actual fund costs. The verifiable ETF-era window (2004–present) is shorter. The 1974–2013 Sharpe of ~0.9 is partly a backtest artifact.
- **Novel signal vs. H01–H14:** H07 (Multi-Asset TSMOM) uses a 12-month cross-sectional momentum signal across 8+ asset classes simultaneously, holding a diversified portfolio. H17 is structurally different: binary single-holding rotation across only 3 ETFs with the critical addition of the absolute momentum safety valve (the equity↔bond switch). H07 never moves entirely to bonds; H17 does. This distinct safe-harbor mechanism and concentrated single-holding approach are novel within the H-series.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Likely on long in-sample window (1990–2024 using index proxies); **Uncertain** on ETF-only window (2004–2024) where Sharpe is estimated 0.7–0.9. May fail the 1.0 bar on ETF-only IS.
- **OOS persistence:** Likely — the strategy has been live-tracked since 2012 across multiple platforms with broadly positive results, though with lower returns than the academic backtest.
- **Walk-forward stability:** Likely — the strategy has very few parameters (lookback period, 3 ETFs) and the lookback of 6–15 months all yield similar results. Low sensitivity to parameter changes.
- **Sensitivity risk:** Low — the main parameter (12-month lookback) is robust. The ETF universe choice (SPY vs. QQQ) has moderate impact.
- **Known overfitting risks:** The academic backtest uses pre-ETF data (survivorship risk), and the post-2013 live performance is substantially lower than backtest. The strategy is NOT overfitted in the traditional sense (very few parameters), but the regime risk (momentum compression, low rates suppressing bond returns) is a structural challenge.

## References

- Antonacci, G. (2012). "Risk Premia Harvesting Through Dual Momentum." Portfolio Management Associates.
- Antonacci, G. (2014). *Dual Momentum Investing: An Innovative Strategy for Higher Returns with Lower Risk.* McGraw-Hill.
- Asness, C., Moskowitz, T., & Pedersen, L. (2013). "Value and Momentum Everywhere." *Journal of Finance*, 68(3), 929–985.
- Allocate Smartly live tracking: GEM strategy performance database (post-2012)
- QC community discussion: https://www.quantconnect.com/forum/discussion/10066/dual-momentum-technology-etf/
- Quantified Strategies review: https://www.quantifiedstrategies.com/dual-momentum-trading-strategy/
- "Fragility Case Study: Dual Momentum GEM" — Think New Found (2019): https://blog.thinknewfound.com/2019/01/fragility-case-study-dual-momentum-gem/
- Related in knowledge base: H07 (Multi-Asset TSMOM), H07b (Expanded TSMOM)
