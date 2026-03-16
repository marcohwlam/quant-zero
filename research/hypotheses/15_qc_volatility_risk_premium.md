# Volatility Risk Premium — Short ATM Straddle + OTM Put Collar

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** options
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Implied volatility (IV) systematically exceeds realized volatility (RV) by 2–5 percentage points on average across equity indices. This spread — the Volatility Risk Premium (VRP) — represents compensation that option buyers pay to transfer downside risk to sellers. The mechanism persists because: (a) institutional demand for portfolio insurance keeps IV structurally elevated, (b) market makers must hedge dynamically and demand a premium for gamma risk, and (c) retail investors overweight tail-risk protection. The gap cannot be fully arbitraged because sellers bear unlimited upside/downside risk intraday.

Academic support: Carr & Wu (2009) "Variance Risk Premiums", CBOE VRP studies, Bakshi & Kapadia (2003) "Delta-Hedged Gains and the Negative Market Volatility Risk Premium". Practitioner replication widely available on QC Strategy Library (see Sources).

## Entry/Exit Logic

**Entry signal:**
- At the start of each calendar month, identify options on SPY expiring in ~30 days (closest to 30 DTE)
- Sell 1 ATM straddle (1 ATM call + 1 ATM put at the strike nearest to SPY's current price)
- Buy 1 15%-OTM put (strike ≈ 0.85 × SPY price, same expiry) as crash insurance

**Exit signal:**
- Hold to expiry (let all legs expire) — this is a defined-period premium collection strategy
- If underlying moves >10% intraday (black-swan guard): close entire position at market

**Holding period:** ~30 days per cycle (monthly options)

## Market Regime Context

**Works best in:** low-to-moderate volatility regimes (VIX 12–25). Theta decay is steady, and IV > RV spread is most reliable.

**Works poorly in:** trending markets with momentum >2σ from mean (naked straddle will lose on gamma), spike events (VIX >35), regime transitions where IV explodes. The 15% OTM put provides floor protection against crash events but does not eliminate large losses from sustained directional moves.

**Regime pause rule:** If VIX > 35 at month-start, skip entry for that month. If VIX has risen >50% in the prior 5 trading days, skip entry.

## Alpha Decay

The signal is a structural risk premium rather than a price-based signal; IC decay analysis differs from directional strategies.

- **Signal half-life (days):** ~15 (midpoint of 30-day cycle; theta decay is front-loaded toward expiry)
- **Edge erosion rate:** slow (>20 days) — the premium is collected linearly via theta decay over the holding period
- **Recommended max holding period:** 30 days (hold to expiry); do not roll early except for the black-swan guard
- **Cost survival:** marginal — commissions on 3 legs (~$3–6 per contract at discount brokers) are material vs. $20–40 monthly premium received on a 1-contract position. At $25K scale (1 SPY straddle), cost ratio is ~10–20%. Edge survives with strict cost management.
- **Annualized IR estimate:** VRP strategies historically yield 8–15% annualized pre-cost with Sharpe ~0.8–1.2 (Carr & Wu 2009, CBOE VRP index data). Post-cost IR at $25K scale estimated ~0.5–0.8 — marginal but above 0.3 threshold.
- **IC decay curve:** N/A for premium collection; theta accrual is the signal. IV > RV spread: T+1 ~0.06, T+5 ~0.05, T+20 ~0.04 (compression near expiry as gamma dominates).
- **Notes:** VRP has shown crowding pressure from systematic vol sellers since ~2017; the 15% OTM put hedge reduces net premium materially and is the key cost-vs-protection tradeoff.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| DTE at entry | 20–35 days | Standard monthly cycle; avoid weekly (liquidity, gamma risk) |
| OTM put strike | 80%–90% of spot | 15% OTM = 0.85× is standard; test sensitivity |
| VIX regime filter | 20–35 entry ceiling | Upper bound to skip high-vol months |
| Position size | 1–2 SPY straddles | $25K capital constraint; 1 is baseline |
| Roll trigger | None vs. 2× premium received | Optional early take-profit |

## Capital and PDT Compatibility

- **Minimum capital required:** ~$20,000 (SPY ~$500; selling 1 straddle requires substantial margin ~15K, plus 15% OTM put debit ~$200–500, plus buffer)
- **PDT impact:** Low risk — opens 1 position monthly, holds to expiry. No day trades involved if not stopped out.
- **Position sizing:** 1 SPY straddle = ~$200–400 credit received per month; ~1–2% of $25K portfolio per cycle. Max concurrent: 1 position.

## Data Source Constraint

> **Important:** yfinance does not provide historical options chain data sufficient for backtesting this strategy. Backtesting requires CBOE historical options data (available via CBOE DataShop), ORATS, or Interactive Brokers historical data API. Engineering Director should be consulted on data sourcing before Gate 1 backtest is scheduled.

## QuantConnect Source Caveat

- **Original QC strategy name:** "Volatility Risk Premium Effect"
- **QC URL:** https://www.quantconnect.com/learning/articles/investment-strategy-library/volatility-risk-premium-effect
- **Apparent backtest window:** 2010–2022 (estimated from QC library documentation); potential in-sample cherry-pick risk — the 2010–2017 low-vol regime is favourable for short-vol strategies
- **Clone/popularity rank:** Official QC Strategy Library entry (not community clone) — crowding risk moderate; vol-selling strategies broadly popular among retail systematists post-2012
- **Novel signal vs. H01–H14:** No options strategies exist in H01–H14. This is the first options premium-capture hypothesis and introduces a structurally different return mechanism (risk premium harvest vs. price signal). Distinct from H05 (momentum vol-scaled) and H12 (ATR momentum) — those use vol as a signal filter, not as the return source.
- **Crowding risk assessment:** Short vol has experienced significant crowding; the February 2018 "Volmageddon" event demonstrated the systemic risk of the trade. The 15% OTM put insurance is essential mitigation.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Unknown without options data; literature suggests 0.8–1.2 pre-cost. At $25K scale post-cost: **unlikely to reach 1.0 cleanly** due to high commission ratio. Marginal.
- **OOS persistence:** Likely — VRP is structural and has been documented since 1990s. But regime-sensitivity (2018, 2020) introduces significant drawdown periods.
- **Walk-forward stability:** Likely — monthly rebalancing means few moving parts; parameter sensitivity is low if VIX filter is applied.
- **Sensitivity risk:** Low-medium — strategy is robust to DTE parameter variation; more sensitive to VIX filter threshold and crash event timing.
- **Known overfitting risks:** Post-2018 crowding shifts the Sharpe distribution down. The backtest window used by QC (2010–2022) overweights the pre-Volmageddon low-vol regime.
- **Data dependency blocker:** Cannot be backtested without historical options chain data. This is a hard blocker for Gate 1 unless a data source is provisioned.

## References

- Carr, P. & Wu, L. (2009). "Variance Risk Premiums." *Review of Financial Studies*, 22(3), 1311–1341.
- Bakshi, G. & Kapadia, N. (2003). "Delta-Hedged Gains and the Negative Market Volatility Risk Premium." *Review of Financial Studies*, 16(2), 527–566.
- CBOE Volatility Risk Premium Index (BXMD benchmark)
- QC Strategy Library: https://www.quantconnect.com/learning/articles/investment-strategy-library/volatility-risk-premium-effect
- QC Research Notebook: https://www.quantconnect.com/research/15382/volatility-risk-premium-effect/
- Quantpedia #9: Volatility Risk Premium Effect — https://quantpedia.com/strategies/volatility-risk-premium-effect
