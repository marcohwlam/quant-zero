# H37 G10 Currency Carry — Gate 1 Report

**Date:** 2026-03-17
**Strategy:** Monthly carry + momentum long-short FX ETF strategy. Long top-2 high-yield currency ETFs (by 3-month central bank rate differential vs. USD), short bottom-2 low-yield. Momentum confirmation: long ETF only if > 60-day SMA, short ETF only if < 60-day SMA. VIX > 35 emergency exit. -8% hard stop per position.
**Task:** QUA-298
**Overall Gate 1 Verdict: FAIL**

---

## Core Gate 1 Metrics

| Criterion | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | -0.2254 | > 1.0 | **FAIL** |
| OOS Sharpe (WF mean) | 0.2798 | > 0.7 | **FAIL** |
| IS Max Drawdown | -25.66% | < 20% | **FAIL** |
| IS Win Rate | 39.76% | ≥ 50% or PF ≥ 1.2 | **FAIL** |
| Profit Factor (IS) | 0.82 | > 1.0 | **FAIL** |
| Trade Count (IS) | 254 (16.9/yr) | ≥ 100 total | **PASS** |
| IS Total Return | -17.36% | — | — |
| Permutation p-value | 1.0 | ≤ 0.05 | **FAIL** |

---

## Walk-Forward Analysis (4 windows, 36m IS / 6m OOS)

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | IS MDD | IS Trades | Status |
|---|---|---|---|---|---|---|---|
| W1 | 2007-01-01 – 2009-12-31 | -0.1121 | 2010-01-01 – 2010-06-30 | -1.1781 | -14.25% | 105 | **FAIL** |
| W2 | 2010-07-01 – 2013-06-30 | -0.1616 | 2013-07-01 – 2013-12-31 | 1.7358 | -12.98% | 42 | FAIL (IS) |
| W3 | 2014-01-01 – 2016-12-31 | -0.0140 | 2017-01-01 – 2017-06-30 | -0.2253 | -9.77% | 23 | **FAIL** |
| W4 | 2017-07-01 – 2020-06-30 | -0.9001 | 2020-07-01 – 2020-12-31 | 0.7867 | -12.52% | 43 | **FAIL** |

**WF windows passed (both IS and OOS):** 0/4
**Mean WF IS Sharpe:** -0.30 | **Mean WF OOS Sharpe:** 0.28
**Note:** W2 OOS and W4 OOS show positive OOS performance despite negative IS — inconsistent with learning hypothesis. Not evidence of a stable signal.

---

## Statistical Rigor

| Test | Value | Threshold | Status |
|---|---|---|---|
| MC p5 Sharpe | -0.6587 | > 0.0 | **FAIL** |
| Bootstrap CI [95%] | (-0.7288, 0.2845) | CI lower > 0.0 | **FAIL** |
| Permutation p-value | 1.0 | ≤ 0.05 | **FAIL** |
| MC Median Sharpe | — | — | — |

**Statistical interpretation:** The permutation p-value of 1.0 indicates the backtest results are statistically indistinguishable from random returns. There is no detectable alpha signal in the 2007–2021 IS period for this strategy parameterization.

---

## Per-Asset Breakdown (IS)

| Asset | Currency | Direction | Trades | Win Rate | Total PnL |
|---|---|---|---|---|---|
| FXA | AUD | Long | 92 | 41.30% | -$238 |
| FXB | GBP | Long/Short | 43 | 44.19% | +$176 |
| FXF | CHF | Short | 73 | 38.36% | -$4,292 |
| FXY | JPY | Short | 46 | 34.78% | +$15 |
| FXC | CAD | Long | — | — | — |
| FXE | EUR | Short | — | — | — |

**Note:** FXC (CAD) and FXE (EUR) had insufficient carry signal confirmation to appear in top-2/bottom-2 ranking consistently. FXF (CHF short) was the largest drag: Swiss Franc appreciated in 2011 and 2015 risk-off episodes, triggering large losses on short CHF positions.

---

## Exit Reason Breakdown

| Exit Type | Count | % of Total |
|---|---|---|
| VIX_EXIT | 164 | 64.6% |
| REBALANCE | 88 | 34.6% |
| HARD_STOP | 1 | 0.4% |
| END_OF_DATA | 1 | 0.4% |

**Critical finding:** 64.6% of all exits are VIX-triggered emergency exits. This indicates severe strategy whipsaw during high-volatility regimes:
- 2008-2009 GFC: VIX remained above 35 for extended periods; strategy repeatedly entered and exited monthly
- 2011 Euro crisis, 2020 COVID: similar whipsaw patterns
- Each VIX exit + re-entry cycle incurs full round-trip transaction costs

---

## Sensitivity Analysis (27-parameter sweep)

### Summary: No parameter combination passes Gate 1

| n_legs | SMA Window | VIX Exit | IS Sharpe | IS MDD | Trades/yr |
|---|---|---|---|---|---|
| 1 | 40d | 28 | -0.3166 | -29.29% | 19.5 |
| 1 | 40d | 35 | -0.0873 | -23.54% | 9.7 |
| 1 | 40d | 40 | -0.0467 | -23.01% | 6.7 |
| 1 | 60d | 28 | -0.1753 | -22.97% | 19.1 |
| 1 | 60d | 35 | +0.0304 | -20.03% | 9.3 |
| 1 | 60d | 40 | +0.0643 | -19.61% | 6.3 |
| 1 | 80d | 28 | -0.0705 | -18.35% | 19.1 |
| **1** | **80d** | **40** | **+0.1905** | **-15.23%** | **5.7** |
| 2 | 60d | 35 | -0.2254 | -25.66% | 16.9 |
| 2 | 80d | 40 | +0.0021 | -25.39% | 11.5 |
| 3 | 80d | 40 | +0.2011 | -18.01% | 18.1 |

**Best combination:** n_legs=1, sma=80d, vix_exit=40 → IS Sharpe = +0.19, MDD = -15.23%
Even the best parameter set achieves Sharpe = 0.19 vs. Gate 1 threshold of 1.0. The gap is ~0.8 Sharpe units.

**Sharpe variance across 27 combinations:** range -0.56 to +0.20 (all below Gate 1 threshold).

---

## Data Quality Checklist

- **Survivorship bias:** FXA (AUD), FXC (CAD), FXE (EUR), FXF (CHF), FXY (JPY) all actively traded 2007–2021. FXB (GBP) available throughout the IS window; dynamically excluded when price data unavailable. No delisted ETFs in the IS window. **Risk: FX ETF universe represents current constituents, not a complete G10 universe. AUD, CAD, EUR, CHF, JPY, GBP ETF selection does not include NZD (FXN), NOK, SEK — partial G10 coverage only.**
- **Price adjustments:** yfinance `auto_adjust=True` for all ETFs.
- **Data gaps:** All tickers show 135-136 "missing" business days due to ETF non-trading on US market holidays — this is expected behavior, not data gaps. No anomalous gaps detected.
- **Earnings exclusion:** N/A — FX ETFs have no earnings events.
- **Delisted tickers:** None in IS window.
- **FRED rate data:** INTDSR series (3-month interbank rates) downloaded via pandas-datareader. All 6 currency rates + FEDFUNDS confirmed available. Forward-filled to daily frequency.

---

## Root Cause Analysis — Why H37 Fails Gate 1

### 1. Severe carry crashes in IS window
The 2007–2021 IS window contains two major carry crashes:
- **2008 GFC:** AUD/CAD carry unwind. FXA fell ~-30%, FXC fell ~-20% from peak. JPY (FXY) rose +30% as flight-to-safety. Both long and short legs lose simultaneously.
- **2020 COVID:** Another brief but sharp carry unwind. FXA, FXC fell sharply.

### 2. VIX exit whipsaw (64.6% of trades)
The VIX > 35 exit triggers during crises and forces the strategy out. When the strategy re-enters the next monthly rebalance, it incurs round-trip costs. With monthly rebalancing, the strategy churns in and out during extended high-VIX periods, accumulating transaction costs without capturing recovery.

### 3. Near-zero rate environment (2010–2021) compresses carry differentials
From 2009 to 2021, major central banks converged to near-zero rates (Fed: 0–2.5%, BoC: 0.25–1.75%, ECB: 0–0.5%, BoJ: 0%). The interest rate differentials that drive carry returns were historically compressed, reducing signal quality. The academic evidence (Lustig & Verdelhan 2007, Menkhoff 2012) is primarily documented in higher-rate environments pre-2008.

### 4. Post-2015 carry evidence gap (per QUA-281 pre-screen)
The hypothesis noted that post-2015 carry evidence needed confirmation. This backtest empirically confirms the concern: carry did not perform well in the 2015–2021 period within the IS window.

### 5. Short CHF drag
FXF (CHF) was the largest drag asset. The Swiss National Bank's safe-haven policy (CHF floor removal in January 2015, -0.75% deposit rate) caused CHF to appreciate unexpectedly, generating losses on short CHF positions.

---

## Gate 1 Checklist

| Check | Pass? |
|---|---|
| is_sharpe_pass (> 1.0) | ❌ FAIL |
| oos_sharpe_pass (> 0.7) | ❌ FAIL |
| is_mdd_pass (< 20%) | ❌ FAIL |
| win_rate_pass (≥ 50% or PF ≥ 1.2) | ❌ FAIL |
| trade_count_pass (≥ 100) | ✅ PASS |
| wf_windows_pass (≥ 3/4) | ❌ FAIL (0/4) |
| sensitivity_pass | ❌ FAIL (best Sharpe = 0.19) |
| mc_p5_pass (> 0.0) | ❌ FAIL |
| permutation_pass (p ≤ 0.05) | ❌ FAIL (p = 1.0) |
| bootstrap_ci_pass (lower > 0.0) | ❌ FAIL |

---

## Verdict

**Overall Gate 1: FAIL**

Failing criteria: is_sharpe_pass, oos_sharpe_pass, is_mdd_pass, win_rate_pass, wf_windows_pass, sensitivity_pass, mc_p5_pass, permutation_pass, bootstrap_ci_pass

**Strategy does not pass Gate 1.** The 2007–2021 IS window contains two major carry crashes (GFC 2008, COVID 2020) that dominate strategy returns. The strategy earns negative risk-adjusted returns (-0.23 Sharpe) with high MDD (-25.66%) and statistically insignificant results (permutation p = 1.0). No parameter combination tested achieves Gate 1 Sharpe threshold of 1.0 — the best observed is 0.19.

**Recommendation to Research Director:** Consider (a) shorter IS window excluding post-2008 near-zero rate era, (b) long-only variant during risk-on regime only, (c) alternative FX risk premium with better post-2015 documentation, or (d) different asset class for next hypothesis. H37 is formally retired.
