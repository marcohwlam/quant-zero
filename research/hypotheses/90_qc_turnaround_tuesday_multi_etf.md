# Turnaround Tuesday Multi-ETF

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-10-26
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Day-of-week returns are not uniform. Historically, Monday returns are lowest (the "weekend effect", French 1980; Gibbons and Hess 1981) and Tuesday often recovers a weak Monday. Proposed mechanisms: weekend news is released after Friday close and bad news is held until the weekend (Damodaran 1989; Penman 1987), producing Monday selling pressure, which is partially reversed as liquidity providers re-enter on Tuesday. Retail order imbalance at Monday's open (Lakonishok and Maberly 1990) is a second channel. The documented weekend effect has weakened since the 1990s (Schwert 2003 on anomaly disappearance after publication), so this hypothesis is conditional: it only trades Tuesday after an oversold Monday, which targets a short-term reversal rather than a pure calendar effect.

## Entry/Exit Logic

**Entry signal:**
- Monday Close < Friday Close by at least 0.5% (down Monday), AND Monday Close < SMA(5)
- Monday Close > SMA(200) (uptrend only)
- Buy at Monday Close

**Exit signal:**
- Exit at Tuesday Close
- No stop (1-day hold)
- If Monday is a market holiday, use the first trading day after the weekend and the following day

**Holding period:** Overnight (1 trading day)

## Market Regime Context

Works in range-bound or bull markets with moderate vol. Fails when Monday declines are the start of a sell-off (Oct 2008, Mar 2020), where Tuesday continues lower. Pause when VIX > 30.

## Alpha Decay

- **Signal half-life (days):** <1 (1-day horizon by construction; measured by the Monday-to-Tuesday reversal IC, not yet estimated)
- **Edge erosion rate:** fast (<5 days)
- **Recommended max holding period:** 1 day
- **Cost survival:** marginal. ETF round-trip cost ~2 bp; the expected gross edge needs to exceed ~10 bp per trade. With <1 day half-life, explicit justification is required: the edge survives only if average Tuesday return after qualifying Mondays exceeds ~8 bp net. Not yet verified.
- **Notes:** Annualized IR estimate: ~12 trades/year/ETF x 6 ETFs, 15 bp net edge, daily vol ~1.2%: approximately 0.3-0.4 pre-cost. At the warning threshold.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| monday_drop_pct | 0.0 - 1.0 | Oversold threshold |
| sma_short | 3 - 10 | Short-term oversold confirmation |
| trend_filter_sma | 100 - 200 | Uptrend filter |
| vix_cap | 25 - 35 | Crash filter |

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000
- **PDT impact:** None. Entry at Monday Close, exit at Tuesday Close is an overnight hold across sessions, not a same-day round trip.
- **Position sizing:** 15% per ETF, max 6 concurrent positions (all ETFs may qualify on the same Monday)

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** QC community has "Turnaround Tuesday" and "Day of Week Anomaly" examples; exact names and URLs not verified in this file-only run. Engineering must confirm before citing.
- **QC backtest window and IS cherry-pick risk:** Most published versions (e.g., Quantpedia-linked ports) use SPY over 2003-2020 with no trend filter and often report Sharpe of 0.6-1.2 driven by the 2009-2010 and 2020 rebound clusters. Treat with caution.
- **Adaptation to framework and data source:** Daily bars from yfinance; multi-ETF expansion and trend/oversold filters differ from the single-instrument SPY versions.
- **Top-10 clone / crowding confirmation:** Not confirmed; the weekend-effect family is widely known and likely heavily cloned. Crowding risk high.

## Pre-Flight Checklist

### PF-1: Walk-Forward Trade Viability
- 6 ETFs (SPY, QQQ, IWM, DIA, MDY, XLF), ~10-14 qualifying Mondays per ETF per year = ~72 trades/year, ~1,400 over 2000-2019 IS; ÷4 = ~350.
- **[x] PF-1 PASS (estimate; trades are highly correlated across ETFs, effective independent sample is ~12 per year)**

### PF-2: Long-Only MDD Stress Test
- Exposure is ~10% of days and the SMA(200) filter excludes most bear-market days. Estimated MDD 2000-2002: 8-12%; 2008-2009: 8-12%.
- **[x] PF-2 PASS**

### PF-3: Data Pipeline Availability
- Daily Close for ETFs and ^VIX from yfinance. Trading calendar via pandas. No new data needed.
- **[x] PF-3 PASS**

### PF-4: Rate-Shock Regime Plausibility (2022)
- A priori argument: in 2022, SPY was below SMA(200) most of the year, so the trend filter blocks entries. Bear-market rallies in 2022 (Jun, Aug, Nov) began with sharp Monday reversals, but the filter disables the strategy.
- Positive 2022 return is not claimed; expected flat. Without the trend filter, the strategy would buy Monday declines in a persistent downtrend, an expected loss.
- **[!] PF-4 WEAK PASS: capital preservation only; long-biased with no hedge.**

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely (expect 0.4-0.8)
- OOS persistence: unlikely; published anomaly with documented post-1990s decay
- Walk-forward stability: moderate; many trades but correlated
- Sensitivity risk: medium (drop threshold, trend filter)
- Known overfitting risks: day-of-week data mining (Sullivan, Timmermann, White 1999), rebound clustering in 2009 and 2020, cost sensitivity at 1-day horizon

## References

- French, K. (1980). "Stock Returns and the Weekend Effect." *Journal of Financial Economics*.
- Lakonishok, J., Maberly, E. (1990). "The Weekend Effect: Trading Patterns of Individual and Institutional Investors." *Journal of Finance*.
- Schwert, G.W. (2003). "Anomalies and Market Efficiency." *Handbook of the Economics of Finance*.
- Sullivan, R., Timmermann, A., White, H. (1999). "Data-Snooping, Technical Trading Rule Performance, and the Bootstrap." *Journal of Finance*.
- Related: `26_qc_pre_holiday_seasonal`, `rsi2_oversold_spy_mean_reversion`
