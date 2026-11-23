# Sector ETF Weekly Reversal (Long-Only, Trend-Gated)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-11-02
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Short-horizon returns reverse at the industry level because liquidity demand shocks (fund flows, rebalancing, hedging) push a sector away from fair value and liquidity providers earn a premium for absorbing the imbalance. Lo and MacKinlay (1990) and Jegadeesh (1990) document weekly and monthly reversal. Sector ETFs reduce idiosyncratic noise, so the reversal reflects flow pressure rather than firm news. The edge is not arbitraged away at scale because holding losers through a drawdown requires balance sheet and risk tolerance that most funds lack. Evidence at the sector ETF level on post-2010 data is thin, so persistence is unproven.

## Entry/Exit Logic

**Entry signal (weekly, at Friday Close):**
- Universe: 11 SPDR sector ETFs (XLB, XLC*, XLE, XLF, XLI, XLK, XLP, XLRE*, XLU, XLV, XLY). *XLC and XLRE enter when listed.
- Rank sectors by 5-day return; buy the 2 worst.
- Gate: SPY Close > SMA(200), otherwise stay in cash.

**Exit signal:**
- Exit at the next Friday Close and re-rank.
- Hard stop: sector ETF closes more than 2.5 x ATR(14) below entry.

**Holding period:** Swing (5 trading days)

## Market Regime Context

Works in range-bound and mildly trending markets where sector dispersion is high and flows mean-revert. Fails in persistent sector trends (2020 energy collapse, 2022 energy rally) where losers keep losing. The SMA(200) gate pauses trading in bear markets.

## Alpha Decay

- **Signal half-life (days):** ~3-5 (estimate, no decay fit yet)
- **Edge erosion rate:** moderate (5-20 days) at the edge of fast
- **Recommended max holding period:** 5-10 days
- **Cost survival:** likely yes; ETF spreads ~1 bp, weekly turnover of 2 positions, expected gross edge ~15-30 bp per trade vs ~2-4 bp round-trip cost
- **Notes:** Vol-scaled IR estimate ~0.3-0.5 pre-cost (at the 0.3 warning level, to be confirmed). Reversal strength has weakened post-2010 in the equity literature; crowding is moderate.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| lookback_days | 3 - 10 | Reversal horizon |
| n_long | 1 - 3 | Concentration vs diversification |
| trend_sma | 100 - 200 | Regime gate |
| hold_days | 3 - 10 | Decay horizon |
| stop_atr_mult | 2.0 - 3.5 | Tail protection |

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000
- **PDT impact:** None. Weekly holds are not day trades.
- **Position sizing:** 40% of portfolio per position, max 2 concurrent (80% gross).

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** Not verified in this run. QC community has sector-rotation and short-term reversal algorithms; Engineering must confirm a specific URL before citing.
- **QC backtest window and IS cherry-pick risk:** Community versions typically cover 2010-2020, a low-vol bull period; discount any reported Sharpe > 1.5.
- **Adaptation:** Daily OHLCV from yfinance, weekly rebalance at Close.
- **Top-10 clone / crowding:** Not confirmed outside the top-10 most cloned; sector rotation is common, but the reversal variant is rarer than the momentum variant.

## Pre-Flight Checklist

### PF-1: Walk-Forward Trade Viability
- 2 trades/week x ~35 active weeks/year (SMA gate off ~30% of time) = ~70 trades/year; 2000-2019 IS = ~1,400 trades; ÷4 = ~350 per fold.
- **[x] PF-1 PASS (estimate; verify on real data)**

### PF-2: Long-Only MDD Stress Test
- SMA(200) gate on SPY keeps the strategy in cash for most of 2001-2002 and 2008-2009; 2.5 ATR stop and 80% max gross bound residual loss.
- Estimated worst-case MDD: 2000-2002 ~15-20%; 2008-2009 ~15-25% (entries before the gate flips).
- **[x] PF-2 PASS (conditional on gate being kept)**

### PF-3: Data Pipeline Availability
- Nine sector ETFs from 1998-12 via yfinance; XLC (2018) and XLRE (2015) join later. SPY for the gate.
- **[x] PF-3 PASS**

### PF-4: Rate-Shock Regime Plausibility (2022)
- 2022 had large sector dispersion and weekly whipsaws, which favors reversal, but SPY was below SMA(200) most of the year so the gate keeps the strategy mostly flat.
- No positive 2022 return is claimed. Capital preservation only.
- **[!] PF-4 WEAK PASS: flat in 2022 by construction.**

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely (expect 0.4-0.8)
- OOS persistence: uncertain; reversal premium has decayed post-2010
- Walk-forward stability: likely moderate; many trades
- Sensitivity risk: medium (lookback, n_long)
- Known overfitting risks: lookback and hold-day choice; sector composition changes (XLC, XLRE, GICS 2018 reclassification)

## References

- Lo, A., MacKinlay, A.C. (1990). "When Are Contrarian Profits Due to Stock Market Overreaction?" *Review of Financial Studies*.
- Jegadeesh, N. (1990). "Evidence of Predictable Behavior of Security Returns." *Journal of Finance*.
- Moskowitz, T., Grinblatt, M. (1999). "Do Industries Explain Momentum?" *Journal of Finance*.
- Related: `20_tv_sector_momentum_rotation`, `06_rsi_short_term_reversal`, `70_iwm_smallcap_mean_reversion`
