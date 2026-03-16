# H29 Gate 1 Backtest Report — TOM + Pre-Holiday + 200-SMA Regime Filter

**Strategy:** H29 Combined Calendar: TOM + Pre-Holiday with 200-SMA Regime Filter
**Runner:** Backtest Runner Agent (QUA-247)
**Date:** 2026-03-16
**Verdict: GATE 1 FAIL**

---

## Executive Summary

H29 was designed as a direct refinement of H28 (Gate 1 FAIL), removing the fragile OEX Week signal and adding a 200-day SMA regime filter. Despite these structural improvements, H29 **fails Gate 1 comprehensively**, achieving an IS Sharpe of only 0.026 (threshold: > 1.0) and a negative OOS Sharpe of -0.049 (threshold: > 0.7). The 200-SMA regime filter functions correctly and provides meaningful risk reduction during bear markets, but the underlying TOM + Pre-Holiday calendar signals do not generate economically significant alpha after transaction costs at the $25,000 portfolio size.

---

## 1. In-Sample Results (2007-01-01 to 2021-12-31)

| Metric | Value | Threshold | Pass |
|---|---|---|---|
| **Sharpe Ratio** | **0.026** | **> 1.0** | **FAIL** |
| Max Drawdown | -15.84% | < 20% | PASS |
| Win Rate | 55.61% | > 50% | PASS |
| Profit Factor | 0.999 | — | — |
| Trade Count | 205 | ≥ 100 | PASS |
| Trades per Year | 13.7 | — | — |
| Total Return | -0.13% | — | — |
| Regime Active | 79.7% of days | — | — |

**Notable:** Profit factor of 0.999 indicates winning trades barely offset losing trades. Total return of -0.13% over 15 years is essentially zero — the strategy earns no excess return in-sample.

---

## 2. Out-of-Sample Results (2022-01-01 to 2025-12-31)

| Metric | Value | Threshold | Pass |
|---|---|---|---|
| **Sharpe Ratio** | **-0.049** | **> 0.7** | **FAIL** |
| Max Drawdown | -12.05% | < 25% | PASS |
| Win Rate | 50.00% | > 50% | FAIL |
| Profit Factor | 0.935 | — | — |
| Trade Count | 52 | — | — |
| Total Return | -1.51% | — | — |
| OOS/IS Sharpe Ratio | -1.85 | — | — |

**OOS Data Quality:** WARN — `profit_factor` advisory NaN resolved; all critical fields valid.

---

## 3. Statistical Rigor Pipeline

### 3.1 Monte Carlo Simulation (1,000 bootstraps on IS trade PnL)

| Metric | Value | Gate 1 Note |
|---|---|---|
| MC p5 Sharpe | **-1.612** | FAIL — pessimistic bound far below 0.5 |
| MC Median Sharpe | -0.013 | |
| MC p95 Sharpe | 2.029 | |

**Assessment:** The extremely wide MC distribution (-1.6 to +2.0) reflects high variance in trade outcomes and insufficient signal consistency. The p5 pessimistic bound of -1.6 is a strong red flag.

### 3.2 Block Bootstrap CI (IS Returns, 1,000 bootstraps)

| Metric | 95% CI |
|---|---|
| Sharpe Ratio | [-0.397, 0.489] |
| Max Drawdown | [-36.76%, -9.37%] |
| Win Rate | [7.71%, 10.16%] |

**Assessment:** The Sharpe CI crosses zero, confirming the IS Sharpe is statistically indistinguishable from zero.

### 3.3 Market Impact (SPY Equities)

| Metric | Value |
|---|---|
| Market Impact | 0.01 bps |
| Liquidity Constrained | False |
| Order/ADV Ratio | 0.000001 |

**Assessment:** At $25,000 initial capital (~55 shares of SPY), market impact is negligible. The poor performance is not due to transaction costs or liquidity constraints.

### 3.4 Permutation Test for Alpha

| Metric | Value | Pass |
|---|---|---|
| Permutation p-value | 0.000 | PASS |

**Note:** Permutation test passes (p=0.000), suggesting the IS Sharpe of 0.026 is statistically higher than random — but the signal is so weak (Sharpe ~0) that this indicates the signal direction is marginally correct, not that it's profitable.

### 3.5 Walk-Forward (4 Folds: IS=36mo / OOS=6mo)

| Fold | IS Period | OOS Period | IS Sharpe | OOS Sharpe | Passed |
|---|---|---|---|---|---|
| 1 | 2007-01 to 2009-12 | 2010-01 to 2010-06 | -0.606 | -0.365 | FAIL |
| 2 | 2007-07 to 2010-06 | 2010-07 to 2010-12 | -0.714 | +2.776 | PASS |
| 3 | 2008-01 to 2010-12 | 2011-01 to 2011-06 | +0.233 | +0.614 | PASS |
| 4 | 2008-07 to 2011-06 | 2011-07 to 2011-12 | +0.401 | -1.547 | FAIL |

| Metric | Value | Threshold | Pass |
|---|---|---|---|
| WF Windows Passed | **2/4** | **≥ 3/4** | **FAIL** |
| WF Consistency Score | 0.00 | ≥ 0.75 | **FAIL** |
| WF OOS Sharpe Std | 1.586 | — | — |
| WF OOS Sharpe Min | -1.547 | — | — |

**Assessment:** Highly inconsistent walk-forward performance. Fold 2 OOS of +2.78 appears to be a lucky H2-2010 window; Fold 4 crashes to -1.55 in H2-2011. No coherent signal across windows.

---

## 4. Stress Windows

| Window | MDD | Trades | Sharpe | Pass (< 40%) |
|---|---|---|---|---|
| GFC (2008-2009) | **-7.73%** | 10 | -0.548 | ✓ PASS |
| Rate-shock 2022 | **-2.54%** | 3 | -1.116 | ✓ PASS |

**Assessment:** The 200-SMA regime filter successfully limits exposure during bear markets. Both stress windows pass the < 40% MDD threshold. However, the very low trade counts in these windows (10 and 3 respectively) mean strategy was mostly in cash — which is exactly the filter's intent, but also means the strategy earns nothing during bear regimes.

---

## 5. Parameter Sensitivity Sweep (9-Point Grid)

`tom_entry_day` ∈ {-3, -2, -1} × `tom_exit_day` ∈ {2, 3, 4}

| Entry Day \ Exit Day | +2 | +3 | +4 |
|---|---|---|---|
| -3 | 0.090 | 0.131 | 0.240 |
| **-2 (base)** | -0.003 | **0.026** | 0.173 |
| -1 | 0.366 | 0.333 | 0.449 |

| Metric | Value | Pass |
|---|---|---|
| Base Sharpe (entry=-2, exit=3) | 0.026 | — |
| Best Adjacent | 0.449 (entry=-1, exit=4) | — |
| Worst Adjacent | -0.003 (entry=-2, exit=2) | — |
| Sharpe Range | 0.452 | — |
| Sharpe Variance | 0.022 | — |
| **Sensitivity Pass** | **FAIL** | **FAIL** |

**Assessment:** The parameter surface is not peaked at the base parameters. `entry=-1` (one day later) consistently outperforms `entry=-2` by a significant margin. This suggests the default parameters are not at the optimal point in the signal space. Additionally, the 107% Sharpe reduction from base to the worst adjacent `(entry=-2, exit=2)` triggers the UNSTABLE flag.

---

## 6. 200-SMA Regime Filter Verification

| Check | Result |
|---|---|
| 2022 majority of days blocked by filter | ✓ CONFIRMED (80.9% of 2022 blocked) |
| 2008–2009 entries blocked during GFC | ✓ CONFIRMED (69.4% blocked in 2008, 69.4% in 2009) |
| Overall regime filter working | ✓ VERIFIED |

**Per-year regime active % (selected years):**
- 2007: 71.4% active
- 2008: 30.6% active (GFC regime protection working)
- 2009: 30.9% active
- 2019: 98.9% active (bull market)
- 2020: 54.6% active (COVID volatility)
- 2021: 99.2% active
- 2022: 19.1% active (rate-shock — filter nearly fully engaged)
- 2023: 84.3% active

The regime filter is working exactly as designed. The problem is that the TOM + Pre-Holiday signals do not generate sufficient alpha even in bull-regime periods.

---

## 7. DSR (Deflated Sharpe Ratio)

| Metric | Value | Pass |
|---|---|---|
| DSR | 0.536 | PASS (> 0) |
| n_trials | 9 (sensitivity grid) | — |

DSR > 0 indicates some statistical significance remains after adjusting for multiple testing. However, a DSR of 0.54 is weak.

---

## 8. Gate 1 Summary Verdict

| Criterion | Value | Threshold | Pass |
|---|---|---|---|
| IS Sharpe | **0.026** | **> 1.0** | **FAIL** |
| OOS Sharpe | **-0.049** | **> 0.7** | **FAIL** |
| IS Max Drawdown | -15.84% | < 20% | PASS |
| OOS Max Drawdown | -12.05% | < 25% | PASS |
| Win Rate (IS) | 55.61% | > 50% | PASS |
| DSR | 0.536 | > 0 | PASS |
| WF Windows Passed | **2/4** | **≥ 3/4** | **FAIL** |
| WF Consistency | **0.00** | **≥ 0.75** | **FAIL** |
| Sensitivity | **FAIL** | **< 50% Sharpe reduction** | **FAIL** |
| Trade Count (IS) | 205 | ≥ 100 | PASS |
| Stress GFC MDD | -7.73% | < 40% | PASS |
| Stress 2022 MDD | -2.54% | < 40% | PASS |
| Permutation Test | p=0.000 | p ≤ 0.05 | PASS |
| MC p5 Sharpe | **-1.612** | **≥ 0.5** | **FLAG** |

**OVERALL VERDICT: GATE 1 FAIL**
**Failing Criteria:** IS Sharpe, OOS Sharpe, WF windows, WF consistency, Parameter sensitivity

---

## 9. Root Cause Analysis

H29's primary failure is that **TOM + Pre-Holiday calendar signals do not produce sufficient return premium to overcome transaction costs at the $25,000 scale over the 2007–2021 IS period**.

Specific observations:

1. **Profit Factor ≈ 1.0**: Gross profits and gross losses nearly exactly offset. This is consistent with the signals capturing a real direction (win rate 55.6%) but at insufficient magnitude.

2. **200-SMA filter works but reduces exposure too much**: The strategy is in cash ~20% of years with the strongest absolute returns (2008, 2022). While this avoids losses, it also reduces compounding, resulting in ~0% total IS return over 15 years.

3. **Parameter sensitivity shows the base params are not optimal**: `entry=-1` (entering one day later on TOM) consistently outperforms `entry=-2`. This suggests the strategy mechanics may be improvable but the base parameters are misspecified.

4. **Walk-forward inconsistency (std=1.59)**: The OOS Sharpe swings from -1.55 to +2.78 across folds — driven by small trade counts (3–9 trades per 6-month OOS window). The signal is too infrequent to generate statistically reliable OOS performance at the fold level.

5. **Trade frequency insufficient for regime-gated strategy**: At 13.7 trades/year in IS, the strategy generates only 3–9 trades per walk-forward OOS window of 6 months. This creates extreme Sharpe variance and makes validation unreliable.

---

## 10. Recommendation

**RETIRE H29 in current form.** Do not proceed to paper trading.

If Engineering Director wishes to pursue H30 refinement, suggested directions:

1. **Re-optimize TOM window**: `entry=-1, exit=4` achieves IS Sharpe ~0.45 — still below 1.0 but a meaningful improvement over default. The TOM Day -1 to Day +4 window may warrant further investigation.
2. **Increase signal frequency**: Add additional calendar signals (e.g., TOM + Pre-Holiday + Post-Holiday) to increase trade count and reduce walk-forward variance.
3. **Scale position sizing**: The $25k portfolio generates trivial position sizes (~55 shares SPY), where fixed cost of $0.005/share represents a measurable drag. Larger initial capital or a leverage adjustment might improve post-cost Sharpe.
4. **Consider weekly TOM variants**: Monthly TOM (12/yr) + Pre-Holiday (9/yr) = 21 potential entries/yr is low. Consider a weekly momentum overlay to increase signal frequency.

---

## 11. Output Files

| File | Path |
|---|---|
| Full metrics JSON | `backtests/h29_tom_preholiday_200sma/results.json` |
| Trade log (IS+OOS) | `backtests/h29_tom_preholiday_200sma/trade_log.csv` |
| This report | `backtests/h29_tom_preholiday_200sma/report.md` |
| Run script | `backtests/h29_tom_preholiday_200sma/run_gate1.py` |

*257 total trades (205 IS + 52 OOS)*

---

*Generated by Backtest Runner Agent | QUA-247 | 2026-03-16*
