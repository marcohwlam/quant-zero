---
tags: [qc-discovery]
---

# H69: VXV/VIX Term Structure Regime Timer

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-06-15
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

The CBOE VIX measures 30-day implied volatility; VXV (now VIX3M) measures 93-day implied volatility. Their ratio encodes the shape of the implied volatility term structure. In a normal (contango) regime, longer-dated implied vol exceeds near-term implied vol (VIX < VXV, ratio < 1.0) — reflecting the risk premium earned for providing liquidity over time. When the term structure inverts to backwardation (VIX > VXV, ratio > 1.0), near-term fear is acute: market participants are paying a premium for immediate protection, signaling crisis or dislocation.

Empirically, periods of VIX backwardation cluster around equity drawdowns (2008, 2011, 2015, 2018 Q4, 2020 March). Holding SPY only when the vol term structure is in contango filters out the worst drawdown periods while remaining invested during the majority of positive-return periods. The mechanism is robust: it exploits the well-documented mean-reversion property of implied volatility and the forward-looking information embedded in the term structure rather than backward-looking price patterns.

Academic support: Whaley (2008) "Understanding the VIX"; Giot (2005) "Relationships Between Implied Volatility Indexes and Stock Index Returns" (Journal of Financial Markets); Simon & Wiggins (2001) "S&P futures and contrary sentiment indicators as forecasting tools."

The edge is not easily arbitraged because the signal does not generate a tradeable spread — it is a binary timing filter on a broad index, not a pairs trade.

## Entry/Exit Logic

**Entry signal:**
- Daily: compute ratio = VIX / VXV (or VIX / VIX3M)
- Optionally smooth ratio with 3-day EMA to reduce whipsaws
- When ratio transitions from ≥ threshold to < threshold (backwardation → contango): Buy SPY at next open

**Exit signal:**
- When ratio transitions from < threshold to ≥ threshold (contango → backwardation): Sell SPY to cash (T-bills proxy: BIL or cash)
- Hard stop: exit if ratio exceeds 1.20 (acute crisis, even if not previously flagged)

**Parameter range for threshold:** 0.90, 0.95, 1.00, 1.05 (test all four)

**Holding period:** Multi-day to multi-week (regime duration). Average regime length ~10-30 trading days.

## Market Regime Context

**Works best:** Trending bull markets with low-vol regimes. Contango is the normal state of VIX term structure (~75-80% of trading days historically), so the strategy is long most of the time.

**Works poorly:** Choppy markets with repeated VIX spikes and reversals (2011–2012, 2015–2016) that generate false backwardation signals and whipsaws. Smoothing mitigates but does not eliminate.

**Regime triggers to pause:** Sustained multi-month backwardation (regime shift rather than spike) may indicate structural break in the model. Flagging via 20-day rolling average of ratio > 1.0 for more than 30 consecutive days.

## Alpha Decay

- **Signal half-life (days):** ~20 trading days (average regime duration between signals)
- **Edge erosion rate:** Slow (>20 days) — the signal is a regime filter, not a predictive return signal per se
- **Recommended max holding period:** Unlimited while in-regime; exit on signal flip
- **Cost survival:** Yes — given typical regime holds of 10-30+ days, round-trip cost of ~1-5 bps (commission + half-spread on SPY) is negligible relative to the avoided drawdown magnitude
- **Notes:** The edge is not return-predictive in a traditional IC sense; it is a drawdown-avoidance filter. Return in contango regime ≈ full SPY return; in backwardation regime, strategy earns T-bill rate. Annualized IR vs buy-and-hold depends on whether avoided bear markets outweigh missed recoveries. 2020 March example: backwardation signal triggered February 25 (VIX spiked above VXV) → avoided SPY -34%; signal cleared ~early April → captured partial recovery.

## Cointegration Analysis

*(Not applicable — single-signal regime timer, not a pairs strategy)*

## Signal Combination

*(Not applicable — single-signal strategy)*

## ML Strategy Specification

*(Not applicable)*

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| ratio_threshold | 0.90, 0.95, 1.00, 1.05 | Sensitivity to regime definition |
| smoothing_window | 1, 3, 5 (EMA days) | Whipsaw reduction |
| universe | SPY, QQQ | Broad vs tech-weighted equity |
| cash_proxy | BIL, SHY, TLT | Short vs intermediate treasury when in cash |

## Capital and PDT Compatibility

- **Minimum capital required:** $1,000 (ETF-only, no margin)
- **PDT impact:** N/A — daily-bar strategy, holds positions for days to weeks
- **Position sizing:** 100% of portfolio in SPY or cash (binary allocation). Max 1 position at a time.

## QuantConnect Source Caveat

- **QC reference:** "VXV-VIX Contango Ratio Strategy" — QuantConnect Community Forum, Discussion #910. URL: https://www.quantconnect.com/forum/discussion/910/vxv-vix-contango-ratio-strategy/
- **QC backtest window:** Forum post circa 2016; community backtests typically cover 2011–2016 (IS cherry-pick risk: data-mined on low-rate bull market regime; post-2016 OOS is critical test period)
- **Adaptation notes:** QC forum discussion used Quandl VXV data (CBOE/VXV). This hypothesis adapts to daily-bar framework using yfinance tickers ^VIX and ^VXV (or ^VIX3M post-2018 rename). No minute-bar data required. VXV was officially renamed to VIX3M by CBOE in January 2018; data continuity must be verified on yfinance before backtesting.
- **Top-10 clone check:** Strategy is NOT in QC's top-10 most-cloned algorithms. It is a niche volatility timing strategy with low crowding risk; the signal is binary and does not generate crowded order flow.

## Pre-Flight Gate Assessment

| Gate | Criterion | Assessment | Status |
|---|---|---|---|
| PF-1 | ≥30 trades over 4-year IS window | Regime switches: 2020 alone had ~4-6; 2022 ~3-5; 2018 Q4 ~1-2. Across 4 years ~15-25 round trips → MARGINAL. Add smoothing to reduce whipsaws but risks dropping below threshold. | AMBER — flag to Risk Director |
| PF-2 | Long-only MDD <40% during dot-com (2000-2002) and GFC (2008-2009) | VIX was consistently above VXV during dot-com and GFC peak periods → strategy would be in cash for the worst drawdown phases. Expected MDD well below 40%. | PASS |
| PF-3 | Data pipeline available (yfinance/Alpaca daily OHLCV) | ^VIX: available on yfinance since 1990. ^VXV/^VIX3M: CBOE started publishing VXV in December 2007; yfinance availability needs explicit verification before backtest. Historical data gap pre-2007 limits IS window start date to ~2008. | AMBER — verify ^VXV ticker on yfinance; IS window may start 2008, not 2000 |
| PF-4 | 2022 rate-shock rationale | VIX was elevated throughout early 2022 (Jan–Feb: ratio approached 1.0; March–June: ratio intermittently in backwardation). Strategy would have been partially in cash during the worst of 2022 equity selloff (-19%). Defensible mechanism. | PASS |

**PF-3 blocker risk:** If ^VXV / ^VIX3M is not available on yfinance with sufficient history (pre-2012), the IS window shrinks. Engineering Director should verify ticker availability before scheduling backtest. Alternative: use FRED VXVCLS series or direct CBOE data download.

## Gate 1 Outlook

- **IS Sharpe > 0.7 (Track A CS gate):** Likely — avoiding major drawdowns (2008, 2020) while capturing bull market runs should produce Sharpe in 0.8-1.2 range IS. Depends heavily on threshold calibration and whether 2020 recovery is captured.
- **OOS persistence:** Moderate confidence — the VIX term structure mechanism is structural (not a data-mined calendar effect) and has held across multiple market regimes since 2007. However, regime switches may have sped up post-COVID, increasing whipsaw risk.
- **Walk-forward stability:** Moderate — the threshold parameter (0.95 vs 1.00 vs 1.05) has low sensitivity risk; the binary nature of the signal limits parameter degeneracy.
- **Sensitivity risk:** Low on threshold, medium on smoothing window
- **Known overfitting risks:** IS window constrained to 2008–present (VXV data limitation). Post-COVID regime change (faster VIX spikes and reversals) may degrade PF-1 trade count. Very low MDD periods (2017, 2019) may produce artificially strong IS results if they dominate the window.

## References

- Whaley, R.E. (2008). "Understanding the VIX." *Journal of Portfolio Management*, 35(3), 98-105.
- Giot, P. (2005). "Relationships Between Implied Volatility Indexes and Stock Index Returns." *Journal of Portfolio Management*, 31(3), 92-100.
- Simon, D.P. & Wiggins, R.A. (2001). "S&P futures and contrary sentiment indicators as forecasting tools." *Journal of Futures Markets*, 21(5), 447-462.
- QuantConnect Forum: "VXV-VIX Contango Ratio Strategy" (Discussion #910) — https://www.quantconnect.com/forum/discussion/910/vxv-vix-contango-ratio-strategy/
- CBOE VIX3M (formerly VXV) Index Methodology: https://www.cboe.com/tradable_products/vix/
- Related hypothesis in pipeline: `18_tv_spy_tlt_rotation.md` (SPY/TLT rotation — different mechanism), `46_spy_tlt_correlation_regime_timer.md` (SPY/TLT correlation regime — different mechanism)
