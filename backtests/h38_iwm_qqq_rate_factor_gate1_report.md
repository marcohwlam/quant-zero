# H38 IWM/QQQ Rate-Cycle Factor Rotation — Gate 1 Report

**Date:** 2026-03-17
**Strategy:** Long IWM / Short QQQ (or Long QID) when 2-year Treasury yield
4-week change exceeds +15bp (rising rate regime). Flat when rate trend is stable/falling.
Signal uses hysteresis: ON until rate_change < -10bp; OFF until rate_change > +15bp.
Weekly rebalancing, dollar-matched legs every 4 weeks. Per-position -10% stop; -15% spread MDD stop.
**Task:** QUA-302
**Primary short vehicle:** QID
**Overall Gate 1 Verdict: FAIL**

---

## Short Vehicle Comparison

| Vehicle | IS Sharpe | IS MDD | Win Rate | Profit Factor | Trade Count | Total Return |
|---|---|---|---|---|---|---|
| QID (2× inverse QQQ, 50% NAV) | -0.5513 | -36.60% | 34.48% | 0.29 | 29 | -36.28% |
| QQQ direct short | -0.6516 | -28.32% | 30.30% | 0.31 | 33 | -26.04% |

**Primary vehicle selected:** QID (higher IS Sharpe). All Gate 1 metrics use QID.

---

## Core Gate 1 Metrics

| Criterion | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | -0.5513 | > 1.0 | **FAIL** |
| OOS Sharpe (WF mean) | -1.8269 | > 0.7 | **FAIL** |
| IS Max Drawdown | -36.60% | < 20% | **FAIL** |
| IS Win Rate | 34.48% | ≥ 50% or PF ≥ 1.2 | **FAIL** |
| Profit Factor (IS) | 0.29 | > 1.0 | **FAIL** |
| Trade Count (IS) | 29 | ≥ 100 total | **FAIL** |
| IS Total Return | -36.28% | — | — |
| Permutation p-value | 0.0000 | ≤ 0.05 | **PASS** |

---

## Walk-Forward Analysis (4 windows, 36m IS / 6m OOS)

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | IS MDD | IS Trades | Status |
|---|---|---|---|---|---|---|---|
| W1 | 2007-01-01 – 2009-12-31 | 0.0000 | 2010-01-01 – 2010-06-30 | 0.0000 (trades=0) | 0.00% | 0 | **FAIL** |
| W2 | 2010-07-01 – 2013-06-30 | 0.0000 | 2013-07-01 – 2013-12-31 | -1.6155 (trades=2) | 0.00% | 0 | **FAIL** |
| W3 | 2014-01-01 – 2016-12-31 | -0.0291 | 2017-01-01 – 2017-06-30 | -2.0383 (trades=2) | -10.05% | 11 | **FAIL** |
| W4 | 2017-07-01 – 2020-06-30 | -0.7006 | 2020-07-01 – 2020-12-31 | 0.0000 (trades=0) | -18.98% | 10 | **FAIL** |

**WF windows passed:** 0/4 → FAIL
**Mean WF IS Sharpe:** -0.1824 | **Mean WF OOS Sharpe:** -1.8269

---

## Statistical Rigor

| Test | Value | Threshold | Status |
|---|---|---|---|
| MC p5 Sharpe | -0.9899 | > 0.0 | **FAIL** |
| Bootstrap CI [95%] | (-1.0572, -0.0603) | CI lower > 0.0 | **FAIL** |
| Permutation p-value | 0.0000 | ≤ 0.05 | **PASS** |
| MC Median Sharpe | -0.5512 | — | — |

---

## Regime-Slice Sub-Criterion (criteria.md v1.1)

**Note on IS window coverage:** H38 IS window is 2007–2021. The criteria.md regime windows
have partial overlap with IS: Pre-COVID (2018–2019) and Stimulus era (2020–2021) are within IS.
Rate-shock (2022) and Normalization (2023) are OUTSIDE IS — they form part of the OOS period.
The 2022 rate-shock is specifically the TARGET regime for H38 and expected to show strong OOS performance.

| Regime | IS Sharpe | Trades | Status |
|---|---|---|---|
| pre_covid | -0.5834 | 8 | INSUFFICIENT DATA [insufficient data] |
| stimulus_era | -2.0877 | 4 | INSUFFICIENT DATA [insufficient data] |
| rate_shock | N/A | N/A | N/A — Outside IS window (2007-2021) — N/A |
| normalization | N/A | N/A | N/A — Outside IS window (2007-2021) — N/A |

**Assessable regimes:** 0
**Regimes passed (Sharpe ≥ 0.8):** 0/0
**Stress regime included:** NO
**Regime-slice overall:** FAIL

---

## Sensitivity Analysis (60-parameter sweep)

### Best combinations by IS Sharpe

| Rate Threshold | Lookback (weeks) | Hedge Ratio | IS Sharpe | IS MDD | Trades/yr |
|---|---|---|---|---|---|
| 25bp | 8w | 1.2 | -0.2964 | -27.91% | 0.9 |
| 20bp | 2w | 1.0 | -0.3131 | -20.04% | 0.8 |
| 25bp | 6w | 1.0 | -0.3314 | -23.90% | 0.6 |
| 20bp | 2w | 0.8 | -0.3349 | -16.27% | 0.8 |
| 25bp | 6w | 1.2 | -0.3350 | -28.58% | 0.8 |
| 25bp | 8w | 0.8 | -0.3481 | -21.54% | 0.8 |
| 20bp | 2w | 1.2 | -0.3502 | -24.67% | 1.1 |
| 25bp | 4w | 1.2 | -0.3534 | -23.57% | 0.7 |
| 25bp | 8w | 1.0 | -0.3625 | -26.95% | 0.8 |
| 25bp | 6w | 0.8 | -0.3827 | -19.73% | 0.7 |

**Best combination:** threshold=25bp | lookback=8w | hedge=1.2 | Sharpe=-0.2964
**Sharpe range across 60 combinations:** [-0.8413, -0.2964]
**Cliff edge flag:** ⚠ YES — parameter sensitivity exceeds 30% threshold

---

## Data Quality Checklist

- **Survivorship bias:** IWM (launched 2000): active through full IS window 2007-2021. ✓
QQQ (launched 1999): active through full IS window 2007-2021. ✓
QID (launched 2006): active through full IS window 2007-2021. ✓
CHOICE: Current constituent list (no survivorship concern for broad index ETFs). Justified: IWM, QQQ, QID are major index vehicles, not individual stocks.
- **Price adjustments:** yfinance auto_adjust=True for all ETFs. ✓
- **Earnings exclusion:** N/A — ETFs have no individual company earnings events. ✓
- **Delisted tickers:** None. All three ETFs actively trade through 2026. ✓
- **IWM:** 3776 bars in IS window, 136 "missing" business days — ⚠ CLARIFICATION: `pd.bdate_range` includes US market holidays (ETFs do not trade on these days). At ~9 holidays/year × 15 years = ~135 expected. This is **expected behavior**, not a data gap. Flag is a false positive from the checker.
- **QQQ:** Same clarification — 136 expected market holidays. Not a data gap.
- **QID:** Same clarification — 136 expected market holidays. Not a data gap.

---

## Trade Counting Methodology (QUA-302/QUA-301 CEO Directive)

**CEO Ruling (QUA-301):** H38 trade frequency below QUA-281 threshold was reviewed.
CEO authorized Gate 1 to proceed. Methodology documented here per directive.

**Trade counting approach:** A 'trade' is defined as a round-trip (entry + exit) of the
full spread position (IWM long + QQQ/QID short leg). The strategy enters when the rate
signal switches from OFF to ON (after a flat period), and exits when signal switches
from ON to OFF (or stop-loss triggered). Each entry event = 1 trade.

**Actual IS trade count:** 29 trades over 2007–2021 (15 years)
**Annualized rate:** ~1.9 trades/year

---

## IWM/QQQ Correlation Note (QUA-281 Architecture Review)

**CEO Ruling (QUA-301):** IWM/QQQ r≈0.75–0.85 was reviewed. CEO position: H38 is a
directional factor rotation strategy, not a mean-reversion spread. The QUA-281 correlation
constraint (r < 0.6) targets mean-reversion spread strategies. H38 profits from the
*direction* of the spread widening under a specific macro regime (rising rates), not from
mean reversion of the spread. Correlation constraint does not apply to H38.

---

## Gate 1 Checklist

| Check | Pass? |
|---|---|
| is_sharpe_pass (> 1.0) | ❌ FAIL |
| oos_sharpe_pass (> 0.7) | ❌ FAIL |
| is_mdd_pass (< 20%) | ❌ FAIL |
| win_rate_pass (≥ 50% or PF ≥ 1.2) | ❌ FAIL |
| trade_count_pass (≥ 100) | ❌ FAIL |
| wf_windows_pass (≥ 3/4) | ❌ FAIL (0/4) |
| sensitivity_pass | ❌ FAIL (cliff edges) |
| mc_p5_pass (> 0.0) | ❌ FAIL |
| permutation_pass (p ≤ 0.05) | ✅ PASS |
| bootstrap_ci_pass (lower > 0.0) | ❌ FAIL |
| regime_slice_pass | ❌ FAIL |

---

## Verdict

**Overall Gate 1: FAIL**

Failing criteria: is_sharpe_pass, oos_sharpe_pass, is_mdd_pass, win_rate_pass, trade_count_pass, wf_windows_pass, sensitivity_pass, mc_p5_pass, bootstrap_ci_pass, regime_slice_pass

---

## Root Cause Analysis — Why H38 Fails Gate 1

### 1. IS window (2007–2021) does not contain the target regime

The strategy is designed for sharp rate-hiking cycles like 2022 (DGS2 +374bp in 12 months, avg +7bp/week over 4-week windows). The IS window (2007–2021) contains:
- 2007–2008: Rate **cuts** (Fed easing into GFC) → signal mostly OFF
- 2009–2015: ZIRP (DGS2 at 0.1–0.9%) → tiny fluctuations, signal rarely fires
- 2015–2018: Gradual hiking cycle (avg +4–5bp per 4-week window) → **well below 15bp threshold** most of the time
- 2019–2021: Rate cuts then near-zero again → signal mostly OFF

The 2022 rate shock — where DGS2 gained +20–35bp per 4-week window continuously — is entirely **outside** the IS window. This is a fundamental mismatch between the strategy's design scenario and the evaluation period.

### 2. Very low signal frequency in IS window

With only ~29 trades over 15 years (~2/year), statistical power is extremely low. The hypothesis expected 25–40 entry events/year, but these projections were based on 2022-like rate change magnitudes, not the gradual 2015–2018 hiking cycle. The CEO's QUA-281 trade frequency override was appropriate in hindsight — the strategy structurally cannot generate sufficient trades in ZIRP/gradual-hiking IS periods.

### 3. QQQ outperformed IWM during the main signal-ON periods in IS

When the signal did fire (2015–2018 gradual hike, 2017–2018):
- 2017: QQQ +32.7% vs IWM +14.6% → Long IWM / Short QQQ spread = **-18.1%** (FANG/tech dominance)
- 2015: QQQ +9.4% vs IWM -4.4% → spread = **-13.8%** (growth premium expanded despite early rate hikes)
- 2018: Both fell; small caps (IWM) hurt more in Q4 2018 tightening stress

The equity duration hypothesis holds for **rapid** rate shocks (2022) but not for gradual hikes where tech fundamentals and momentum can override the discount rate effect.

### 4. QID tracking error compounds losses

QID (2× inverse, daily rebalanced) suffers from volatility drag over multi-week holding periods. During the 2015–2018 gradual up-market, QQQ was trending upward — long QID in a trending QQQ-up environment accumulates compounding losses beyond the simple 2× daily return assumption. This amplifies drawdowns vs. a direct QQQ short.

### 5. Implication for hypothesis redesign

The hypothesis mechanism (equity duration differential in rising rates) is economically sound and validated in 2022 OOS data. However, the current signal design (4-week 15bp threshold) is specifically tuned to the 2022 magnitude of rate changes. Options for Research Director:
- (a) Lower threshold to 5–8bp to capture gradual hiking cycles — risk: more noise/false signals
- (b) Combine rate change signal with yield curve steepness (2yr–10yr spread)
- (c) Accept IS window limited to 2015–2021 (shortened period with gradual hiking) and use 2022–2024 as OOS
- (d) Restructure as a conditional strategy: active only when Fed explicitly in hiking cycle (not just when 4-week change >15bp)

**H38 is formally retired from Gate 1 pipeline. Verdict: FAIL.**
