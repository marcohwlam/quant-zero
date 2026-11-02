# Volume Capitulation Reversal on Liquid ETFs

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-11-02
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Price drops on abnormally high volume signal forced or panic selling (margin calls, stop cascades, redemptions). The selling is liquidity-driven rather than information-driven, so a rebound follows as liquidity providers are compensated. Cooper (1999) finds that high-volume losers reverse more strongly than low-volume losers at weekly horizons, and Lee and Swaminathan (2000) show volume conditions the direction and persistence of past returns. Low-volume declines carry more information and tend to continue. Existing firm hypotheses condition on price only (H34 RSI2, H30 VIX spike); volume conditioning is a distinct, untested filter. Evidence on ETFs after 2010 is limited.

## Entry/Exit Logic

**Entry signal (at Close, long-only):**
- Daily return < -1.5 x ATR(14)/Close (a drop larger than 1.5 ATRs)
- Volume > 2.0 x 20-day average volume
- Close > SMA(200) of the same ETF OR SPY Close > SMA(200) (trend gate, test both)
- Universe: SPY, QQQ, IWM, DIA, XLF, XLK, XLE, XLV, XLY, XLP

**Exit signal:**
- Exit at first Close above the prior day Close, or after 5 trading days
- Hard stop: Close below the capitulation-day Low

**Holding period:** Swing (1-5 days)

## Market Regime Context

Works in bull and range markets where selloffs are shocks (Aug 2015, Feb 2018, Dec 2018 intraday, Oct 2023). Fails in crash regimes where capitulation repeats for weeks (Sep-Oct 2008, Mar 2020 first leg). Pause if VIX > 40 or 3 signals fire in 5 days on SPY.

## Alpha Decay

- **Signal half-life (days):** ~2-4 (estimate)
- **Edge erosion rate:** fast to moderate
- **Recommended max holding period:** 5 days (cap at 2x half-life)
- **Cost survival:** yes; ETF spreads ~1 bp, expected gross edge ~40-80 bp per trade in the literature range, less after decay
- **Notes:** Vol-scaled IR estimate ~0.4-0.6 pre-cost on event days (to be confirmed). Signal fires rarely per ETF, so the sleeve holds mostly cash and realized sleeve vol is low; Sharpe may look good on few trades, so PF-1 is the binding risk.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| drop_atr_mult | 1.0 - 2.5 | Size of capitulation |
| vol_mult | 1.5 - 3.0 | Volume spike threshold |
| vol_avg_window | 10 - 30 | Baseline volume |
| max_hold_days | 3 - 7 | Decay horizon |
| trend_gate | none / SPY SMA200 / own SMA200 | Crash filter |

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000
- **PDT impact:** None. Entry at Close, exit at a later Close.
- **Position sizing:** 20% per signal, max 4 concurrent positions.

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** Not verified in this run. QC has "volume spike" and "capitulation" community scripts; Engineering must confirm URL before citing.
- **QC backtest window and IS cherry-pick risk:** Community versions usually test SPY only on 2010-2020, where event count is low (~20) and results are fragile.
- **Adaptation:** Daily OHLCV from yfinance across 10 ETFs to raise event count. Note ETF volume includes creation/redemption noise; use composite volume as reported.
- **Top-10 clone / crowding:** Not a top-cloned pattern to my knowledge; unconfirmed.

## Pre-Flight Checklist

### PF-1: Walk-Forward Trade Viability
- Estimate ~4-6 qualifying events per ETF per year across 10 ETFs = ~50 trades/year (events cluster in selloffs, so effective independent events are fewer); 2000-2019 IS = ~1,000 trades; ÷4 = ~250 per fold.
- Risk: after trend gate, count may fall to 25-35/year (~550 total, ÷4 = ~137), still above 30 per fold, but close to the floor if thresholds are tightened.
- **[x] PF-1 PASS (marginal; verify event count before backtest)**

### PF-2: Long-Only MDD Stress Test
- Trend gate blocks most entries in 2001-2002 and 2008-2009. Without the gate, repeated capitulation entries in Sep-Nov 2008 would be the main loss source, so the gate is mandatory. Per-trade stop at the capitulation low and 5-day time stop limit loss.
- Estimated worst-case MDD: 10-20% (with gate).
- **[x] PF-2 PASS (conditional on gate)**

### PF-3: Data Pipeline Availability
- Needs OHLCV (including Volume) for 10 ETFs; yfinance, 1999+ for sector ETFs, SPY from 1993.
- **[x] PF-3 PASS**

### PF-4: Rate-Shock Regime Plausibility (2022)
- 2022 had multiple high-volume selloff days followed by sharp relief rallies (Jun, Oct, Nov). A SPY-only SMA gate disables most 2022 trades; an own-ETF gate also disables most. Ungated variant would trade but with bear-market continuation risk.
- No positive 2022 return is claimed under the gated base spec.
- **[!] PF-4 WEAK PASS: capital preservation; test the ungated variant separately.**

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely to borderline (0.5-1.0)
- OOS persistence: uncertain; low event count
- Walk-forward stability: uncertain; event clustering around a few crises
- Sensitivity risk: medium-high (two thresholds plus gate)
- Known overfitting risks: threshold selection on few events; clustering inflates apparent trade count; ETF volume is a noisy proxy for forced selling

## References

- Cooper, M. (1999). "Filter Rules Based on Price and Volume in Individual Security Overreaction." *Review of Financial Studies*.
- Lee, C., Swaminathan, B. (2000). "Price Momentum and Trading Volume." *Journal of Finance*.
- Related: `34_rsi2_oversold_spy_mean_reversion`, `30_vix_spike_spy_mean_reversion`, `88_qc_oops_gap_reversal_etf`
