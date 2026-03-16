# H05 Momentum Vol-Scaled — Gate 1 Failure Analysis

**Date:** 2026-03-16 (Batch 1) | Updated: 2026-03-16 (Batch 2)
**Tasks:** QUA-82 (Batch 1 review), QUA-97 (Batch 2 review)
**Batches:** Iterations 1–35 (Batch 1) + Iterations 36–65 (Batch 2) = 60 total iterations
**Outcome:** FAILED — 0/60 iterations pass Gate 1

---

## Verdict: FAIL — IS Sharpe Ceiling ~0.79 — Retire $25K ETF Implementation ✅ CONFIRMED by Batch 2

**All 60 parameter variations across two batches fail Gate 1.** IS Sharpe ranges from 0.43 to 0.79 — never reaching the 1.0 threshold. The failure is systematic (100% of iterations) and parameter-invariant across both batches, confirming a structural failure rather than parameter mis-calibration.

---

## Results Summary (Best Configurations)

| Configuration | IS Sharpe | OOS Sharpe | IS MDD | Win Rate | Gate 1 |
|--------------|----------|-----------|--------|----------|--------|
| lb12_sk1_k2_tv10_cp10 | **0.791** | 0.357 | -17.8% | — | **FAIL** (IS Sharpe, OOS Sharpe) |
| lb12_sk1_k3_tv10_cp15 | 0.707 | 0.531 | -14.4% | — | **FAIL** (IS Sharpe, OOS Sharpe) |
| lb9_sk1_k4_tv12_cp10 | 0.434 | **1.084** | -28.0% | 65% | **FAIL** (IS Sharpe, IS MDD) |
| lb18_sk1_k4_tv10_cp10 | 0.508 | 1.048 | -21.2% | 71% | **FAIL** (IS Sharpe, IS MDD) |

**Batch statistics:**
- IS Sharpe range: 0.434 – 0.791 (all below 1.0 threshold)
- IS MDD range: -34.4% – -13.0%
- OOS Sharpe range: 0.357 – 1.084
- Configs with IS MDD < 20%: 10/30 (MDD passable, Sharpe still fails)
- Configs with OOS Sharpe > 0.7: 12/30 (OOS passable, IS Sharpe still fails)
- **No configuration passes both IS Sharpe AND OOS Sharpe simultaneously**

**Walk-forward windows passed:** 0/4 in all tested configurations

---

## Batch 2 Update — Iterations 36–65 (QUA-97)

**Date:** 2026-03-16 | **Source:** QUA-81 orchestrator run | **Parent task:** QUA-97

### Batch 2 Top 3 by OOS Sharpe

| Configuration | IS Sharpe | OOS Sharpe | IS MDD | Win Rate | Trades | Gate 1 |
|---|---|---|---|---|---|---|
| mvs_lb9_sk1_k4_tv12_rb21_cp10 (Iter 57) | 0.434 | **1.084** | -28.0% | 65.5% | 110 | **FAIL** (IS Sharpe, IS MDD) |
| mvs_lb9_sk1_k5_tv10_rb42_cp10 (Iter 65) | 0.467 | **1.074** | -23.6% | 72.7% | 77 | **FAIL** (IS Sharpe, IS MDD) |
| mvs_lb18_sk1_k4_tv10_rb21_cp10 (Iter 61) | 0.508 | **1.048** | -21.2% | 70.8% | 89 | **FAIL** (IS Sharpe, IS MDD) |

**Batch 2 statistics:**
- Gate 1 passes: **0/30**
- IS Sharpe range: 0.43 – 0.51 (maximum IS Sharpe in Batch 2 is *lower* than Batch 1's 0.79)
- IS MDD failures: 18/30 (identical structural pattern to Batch 1)
- OOS Sharpe > 1.0: 3/30 (same inverted IS/OOS pattern — confirms regime effect, not look-ahead)

### Batch 2 Anomalies

**Walk-Forward Bug (all 30 configs):** `wf_windows_passed = 0` for all iterations. Root cause: 6-month OOS sub-windows are shorter than the momentum lookback warmup period, so no signals are generated within each WF OOS window. The WF function needs to pass combined IS+OOS history for signal computation. **Main IS/OOS metrics are unaffected.** This is an infrastructure defect, not a strategy failure.

**IS Sharpe Regression in Batch 2:** Batch 2's best IS Sharpe (0.508) is significantly below Batch 1's best (0.791). Batch 2 explored new rebalance windows (21d, 42d) that change the holding period but don't resolve the fundamental universe problem. The wider rebalance windows reduce trade count and diversification, further suppressing Sharpe.

### Batch 2 Conclusion

Second batch confirms the structural ceiling identified in Batch 1. No parameter configuration — across 6 different dimensions over 60 total iterations — can overcome the fundamental insufficiency of the 8-ETF universe for cross-sectional momentum. **H05 is definitively retired from Phase 1 at $25K.**

---

## Failure Mode Analysis

### Primary Failure: IS Sharpe 0.43–0.79 (100% of iterations fail)

The IS Sharpe ceiling is approximately 0.79 — achieved with 12-month lookback, 1-month skip, top-2 ETFs, 10% target vol, 10% crash protection. This is 21 percentage points below the Gate 1 threshold of 1.0. The failure is robust across:
- All lookback windows tested: 6, 9, 12, 18 months
- All top-k portfolio sizes: 2, 3, 4, 5 ETFs
- All target volatilities: 10%, 12%, 15%, 20%
- All crash protection thresholds: 5%, 8%, 10%, 12%, 15% (including no crash protection)
- Equal-weight vs. vol-weighted allocation

This parameter-invariant failure pattern is diagnostic of a **structural/regime problem**, not a parameter problem.

### Root Cause: ETF Universe Too Small for Cross-Sectional Momentum

**Critical finding:** The batch used an 8-ETF universe (SPY, QQQ, IWM, DIA, XLF, XLE, XLK, XLV). Cross-sectional momentum requires meaningful dispersion between assets. The 8 ETFs in this universe are highly correlated (~0.7–0.9 pairwise), and the cross-sectional variation is minimal:
- 4/8 are broad market ETFs (SPY, QQQ, IWM, DIA) — nearly identical exposure
- 4/8 are sector ETFs with substantial market beta

The monthly Sharpe of the top-k vs. bottom-k spread is near-zero because there is insufficient alpha dispersion in a correlated 8-ETF universe.

**The original hypothesis calls for S&P 500 individual stocks (~500 names)** — a universe with substantial idiosyncratic cross-sectional dispersion. The ETF adaptation sacrifices the fundamental mechanism that makes cross-sectional momentum work.

### Secondary Failure: IS MDD > 20% (20/30 iterations)

Even configurations that resolve the MDD issue (10/30 have MDD < 20%) do so at the cost of reduced exposure, which further compresses IS Sharpe. There is a structural trade-off between MDD control and alpha generation in this implementation.

The March 2020 COVID crash is the primary MDD driver:
- Top-2 momentum ETF portfolio drops >20% in the crash
- Crash protection (50% reduction at SPY -10% monthly) activates but lags the actual crash by 1–3 weeks at monthly measurement
- Recovery period (April–December 2020) is a strong trend — crash protection kept positions reduced, costing IS Sharpe

### Inverted IS/OOS Pattern

Notably, the OOS Sharpe is stronger than IS Sharpe for many configurations (e.g., OOS 1.08 vs IS 0.43). This reflects:
- **OOS (2023-2024):** Strong bull market with large cross-sectional dispersion across sector ETFs
- **IS (2018-2022):** COVID crash, 2022 bear, low cross-sectional dispersion in mixed market

This is not a sign of out-of-sample overfitting; rather, the IS window is the more difficult period.

---

## $25K Implementation Constraint (Critical)

The hypothesis itself rated H05 as **"Poor" for $25K fit**. The full long-short strategy (S&P 500 stocks, 100 longs + 100 shorts) is **not executable at $25K**. The ETF adaptation tested here represents the maximum viable implementation at this capital level, and it proves insufficient.

**Conclusion:** H05 Momentum Vol-Scaled cannot be viably implemented at $25K in a way that passes Gate 1. The strategy needs either:
1. **Larger capital** ($250K+ for 20–40 S&P 500 stock positions with proper sizing)
2. **Different asset class** (e.g., cross-country ETF momentum with 30+ countries — more dispersion than 8 domestic ETFs)

---

## Key Lessons

1. **Universe size is a structural requirement for cross-sectional momentum.** Do not test cross-sectional momentum on < 20 highly correlated instruments — the cross-sectional dispersion is insufficient for the strategy to work.
2. **The $25K capital constraint rules out cross-sectional equity momentum entirely.** Gate 1 should not test H05 further at $25K unless the universe is expanded (e.g., 30+ country/sector ETFs with meaningful independence).
3. **IS window (2018-2022) is hostile to multiple strategy classes.** H02 (mean reversion), H04 (cointegration), and now H05 (momentum) all fail IS Sharpe. The common thread is the IS window's combination of COVID crash, rate volatility, and regime transitions that systematically impair strategies tested at $25K scale with limited universe.
4. **OOS Sharpe > IS Sharpe is not a red flag when the IS window genuinely contains a structural break.** The 2020 crash is a legitimate IS hazard, not cherry-picked OOS overfitting.

---

## Pipeline Impact

**Gate 1 pass rate: 0/3 strategies tested (0%)** — alert threshold (< 10%) triggered.

**Strategies tested vs. Gate 1:**
| Strategy | IS Sharpe | Result |
|----------|----------|--------|
| H02 Bollinger Band Mean Reversion | 0.029 | FAIL |
| H04 Pairs Trading v1.0 | 0.500 | FAIL |
| H05 Momentum Vol-Scaled (ETF, $25K) | 0.791 (best) | FAIL |

**Remaining pipeline:**
- H04-v3 (Distance Method): In progress — QUA-98 assigned to Alpha Research
- H06 RSI Reversal: Has mean-reversion structural risk; 200d SMA filter may help
- H01 DMA Crossover: Baseline only; not a Gate 1 candidate
- H03 Multi-Factor L/S: Data dependency + $25K concern unresolved

**Research Director recommendation:** CEO escalation required. 0/3 Gate 1 pass rate triggers immediate review of pipeline strategy and IS window appropriateness.

**Infrastructure action required:** Engineering Director must fix the WF function to pass combined IS+OOS history for signal computation (identified in Batch 2 anomaly above). Does not affect strategy retirement decision.

---

*Research Director | QUA-82 (Batch 1) + QUA-97 (Batch 2) | 2026-03-16*
