# 52-Week-High Proximity Sector Rotation (Momentum-Class)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-11-02
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Investors anchor on the 52-week high as a reference point. Good news is under-reacted to when price is near the high (reluctance to bid above the anchor), and bad news is under-reacted to when price is far below. Ranking by proximity to the 52-week high therefore predicts returns, and George and Hwang (2004) show it dominates raw 6-12 month momentum, with less crash exposure and less reversal at long horizons. Applying it at the sector ETF level adds Moskowitz and Grinblatt (1999) industry momentum. This is the only momentum-class candidate in this batch. Firm hypotheses H20 (sector momentum) and H54 (TSMOM) use return lookbacks, not distance to the high, so the signal is related but not identical; correlation with H20 must be measured before any portfolio use.

## Entry/Exit Logic

**Entry signal (monthly, last trading day Close):**
- Universe: 9 to 11 SPDR sector ETFs (as listed).
- Compute ratio = Close / max(High over 252 days) per ETF.
- Buy the top 3 by ratio, equal weight, only if ratio > 0.90.
- Absolute gate: SPY Close > SMA(200), otherwise hold SHY (or cash).

**Exit signal:**
- Rebalance monthly; exit ETFs that leave the top 3 or fall below ratio 0.85.
- Hard stop: ETF closes more than 12% below entry.

**Holding period:** Position (weeks to months)

## Market Regime Context

Works in sustained bull markets with sector leadership (2003-2007, 2009-2019, 2023-2024). Fails at sharp reversals and momentum crashes (Mar 2009, Nov 2020 rotation) and in choppy markets. The SPY gate and ratio threshold reduce exposure when few sectors sit near highs.

## Alpha Decay

- **Signal half-life (days):** ~40-60 (estimate)
- **Edge erosion rate:** slow (>20 days)
- **Recommended max holding period:** ~60-90 days; monthly rebalance is within range
- **Cost survival:** yes; ~3 positions, monthly rebalance, ETF costs ~1-2 bp
- **Notes:** Vol-scaled IR estimate ~0.4-0.6 pre-cost (to be confirmed). Momentum crash risk is the main tail. Long-only sector momentum is crowded.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| high_window | 126 - 252 | Anchor horizon |
| n_long | 2 - 5 | Concentration |
| min_ratio | 0.85 - 0.95 | Entry proximity |
| trend_sma | 100 - 200 | Regime gate |
| stop_pct | 8 - 15 | Tail protection |

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000
- **PDT impact:** None.
- **Position sizing:** 33% per position, max 3 concurrent.

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** Not verified in this run. QC has sector-momentum and "52-week high" community algorithms; Engineering must confirm a URL before citing.
- **QC backtest window and IS cherry-pick risk:** Community sector momentum backtests are mostly 2010-2021, a strong tech-led bull; discount reported Sharpe.
- **Adaptation:** Daily OHLCV from yfinance; month-end rebalance at Close.
- **Top-10 clone / crowding:** Sector rotation momentum is commonly cloned; the 52-week-high ranking is rarer. Unconfirmed.

## Pre-Flight Checklist

### PF-1: Walk-Forward Trade Viability
- ~3 positions, ~40% monthly turnover of slots, plus gate switches = ~20-25 trades/year; 2000-2019 IS = ~400-500 trades; ÷4 = ~100-125 per fold, around the PF-1 line of 120 total only if total ÷ 4 >= 30 (total >= 120, satisfied).
- **[x] PF-1 PASS (total IS trades ~400-500 >= 120; per-fold count thin, verify)**

### PF-2: Long-Only MDD Stress Test
- SPY SMA(200) gate moves to SHY in 2001-2002 and 2008-2009. Entries before the gate flips and gate lag are the exposure; 12% stop bounds each position.
- Estimated worst-case MDD: 2000-2002 ~15-25%; 2008-2009 ~20-30%. Below the 40% limit, but closer than the other two candidates.
- **[x] PF-2 PASS (conditional on gate and stop)**

### PF-3: Data Pipeline Availability
- Sector ETFs and SPY/SHY from yfinance (SHY 2002+; use cash before). 252-day history needs ~1 year warm-up from 1999.
- **[x] PF-3 PASS**

### PF-4: Rate-Shock Regime Plausibility (2022)
- 2022: energy (XLE) stayed near its 52-week high all year while most sectors fell, so the ratio ranking would hold XLE, XLP, XLU, XLV. This is a structural rationale for survival: the signal rotates toward relative strength in a rising-rate, inflation regime. The SPY gate would still send the strategy to SHY for much of the year, so realized 2022 depends on gate versus ranking priority, to be tested with and without the gate.
- **[x] PF-4 PASS (structural rationale: relative-strength rotation held energy and defensives; verify empirically)**

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely to borderline (expect 0.5-0.9)
- OOS persistence: uncertain; sector momentum has been inconsistent since 2010
- Walk-forward stability: moderate; few trades per fold
- Sensitivity risk: medium (window, n_long, gate)
- Known overfitting risks: parameter tuning on a small universe of 9-11 assets; XLC/XLRE inclusion changes; overlap with H20 and H54 means incremental information may be small

## References

- George, T., Hwang, C. (2004). "The 52-Week High and Momentum Investing." *Journal of Finance*.
- Moskowitz, T., Grinblatt, M. (1999). "Do Industries Explain Momentum?" *Journal of Finance*.
- Related: `20_tv_sector_momentum_rotation`, `54_time_series_momentum_etf`, `17_qc_dual_momentum_etf_rotation`
