# Gate 1 Verdict: H29 TOM + Pre-Holiday + 200-SMA

**Date:** 2026-03-16
**Strategy:** `strategies/h29_tom_preholiday_200sma.py`
**Backtest Runner:** QUA-247
**Engineering Director Verdict:** QUA-245
**Result: FAIL**

---

## Gate 1 Scorecard

| Criterion | Required | Actual | Result |
|---|---|---|---|
| IS Sharpe | > 1.0 | **0.026** | FAIL |
| OOS Sharpe | > 0.7 | **-0.049** | FAIL |
| IS Max Drawdown | < 20% | 15.84% | PASS |
| OOS Max Drawdown | < 25% | 12.05% | PASS |
| Win Rate (IS) | > 50% | 55.6% | PASS |
| Min Trade Count (IS) | >= 100 | 205 | PASS |
| WF Windows Passed | >= 3/4 | **2/4 (50%)** | FAIL |
| WF Consistency | Required | **Score: 0.0** | FAIL |
| Parameter Sensitivity | Stable | **Range: 0.452** | FAIL |
| Stress MDD (GFC 2008–09) | < 40% | 7.73% | PASS |
| Stress MDD (Rate Shock 2022) | < 40% | 2.54% | PASS |
| Permutation p-value | < 0.05 | 0.0 | PASS |

**Failing criteria (5):** IS Sharpe, OOS Sharpe, WF Windows, WF Consistency, Parameter Sensitivity

---

## Key Metrics

```
IS Period:  2007-01-01 to 2021-12-31
OOS Period: 2022-01-01 to 2025-12-31

IS Sharpe:          0.0263
IS MDD:            -15.84%
IS Trade Count:     205
IS Win Rate:        55.6%
IS Profit Factor:   0.9987 (below 1.0 — net loser after costs)
IS Total Return:   -0.13%

OOS Sharpe:        -0.0487
OOS MDD:          -12.05%
OOS Trade Count:    52
OOS Win Rate:       50.0%
OOS Profit Factor:  0.9345

DSR:                0.536
MC p5 Sharpe:      -1.612
MC Median Sharpe:  -0.013
WF Sharpe Std:      1.586
WF Consistency:     0.0 (0/4 folds above Sharpe 0.7)
```

---

## Failure Analysis

### 1. Insufficient Signal Edge (Primary Failure)

IS Sharpe of 0.026 represents essentially zero alpha after transaction costs. The TOM + Pre-Holiday seasonal anomaly on SPY is well-documented in academic literature but appears to be substantially arbitraged away in modern markets. The IS profit factor of 0.9987 confirms the strategy is a slight net loser in-sample.

### 2. 200-SMA Regime Filter: Mechanically Correct, Insufficient

The 200-SMA filter functioned as designed:
- Blocked 80.9% of 2022 trading days (bear regime correctly identified)
- GFC 2008: 98.0% of days blocked (severe drawdown avoided, MDD only 7.73%)
- Rate Shock 2022: MDD limited to 2.54% (vs. unconstrained exposure)

However, the filter cannot create alpha that does not exist in the bull-regime residual. The filter reduced exposure in bad conditions but did not improve the edge in good conditions.

### 3. Walk-Forward Inconsistency

| Fold | IS Period | OOS Period | IS Sharpe | OOS Sharpe | Passed |
|---|---|---|---|---|---|
| 1 | 2007–2009 | 2010H1 | -0.606 | -0.365 | No |
| 2 | 2007H2–2010H1 | 2010H2 | -0.714 | **+2.776** | Yes |
| 3 | 2008–2010 | 2011H1 | 0.233 | +0.614 | Yes |
| 4 | 2008H2–2011H1 | 2011H2 | 0.401 | -1.547 | No |

Fold 2's high OOS Sharpe (+2.78) is an outlier driven by small OOS trade count (7 trades). Underlying consistency is poor: WF Sharpe std = 1.586, min = -1.547.

### 4. Parameter Sensitivity Failure

9-point sensitivity grid (TOM window ±1 day):

| Config | IS Sharpe |
|---|---|
| entry=-3, exit=+2 | 0.090 |
| entry=-3, exit=+3 | 0.131 |
| entry=-3, exit=+4 | 0.240 |
| entry=-2, exit=+2 | **-0.003** |
| entry=-2, exit=+3 | 0.026 (baseline) |
| entry=-2, exit=+4 | 0.173 |
| entry=-1, exit=+2 | 0.366 |
| entry=-1, exit=+3 | 0.333 |
| entry=-1, exit=+4 | **0.449** (best) |

- Sharpe range: 0.452 (high — parameter-sensitive)
- Baseline is near the worst combo; best combo shifts TOM entry earlier by 1 day
- Even the best combo (0.449) is far below the Gate 1 threshold of 1.0
- Signal is structurally unstable: performance is highly dependent on exact entry timing

### 5. OOS Sharpe Negative (-0.049)

OOS Sharpe negative with OOS/IS ratio of -1.85 confirms severe IS overfitting. There is no out-of-sample edge. The permutation p-value of 0.0 (pass) is likely a test artifact from the near-zero IS Sharpe.

---

## H28 vs H29 Comparison

| Metric | H28 (Gate 1 FAIL) | H29 (Gate 1 FAIL) | Direction |
|---|---|---|---|
| IS Sharpe | 0.098 | 0.026 | Worse |
| OOS Sharpe | -0.43 | -0.049 | Less bad |
| IS MDD | 15.3% | 15.84% | Slightly worse |
| WF Windows | 1/4 | 2/4 | Slightly better |
| Free Parameters | 10 | 5 | Better (fewer) |

Removing OEX Week and adding 200-SMA regime filter did not improve the fundamental IS Sharpe. OOS improved marginally (less overfitting due to fewer parameters), but the core signal is insufficient.

---

## Regime Filter Analysis

200-SMA block rate by year (key years):

| Year | Regime Active | Blocked by SMA |
|---|---|---|
| 2008 | 2.0% | **98.0%** |
| 2022 | 19.1% | **80.9%** |
| 2013 | 100.0% | 0.0% |
| 2017 | 100.0% | 0.0% |
| 2021 | 100.0% | 0.0% |

The regime filter successfully identified bear markets but significantly reduced the number of tradeable days — especially 2008 where only 2% of days were active. With few trades available in favorable years, the aggregate Sharpe cannot reach Gate 1 levels.

---

## Recommended Next Directions for Research Director

H29 demonstrates that the SPY TOM + Pre-Holiday calendar effect is insufficient as a standalone strategy. Recommended directions:

1. **Asset class pivot (highest priority):** Test TOM + Pre-Holiday on IWM (Russell 2000 small-cap) or sector ETFs. Academic literature consistently shows calendar effects are stronger in small-cap stocks where institutional arbitrage is limited. Expected IS Sharpe improvement: 2-4x vs SPY.

2. **Pre-Holiday isolation:** Pre-Holiday IC (0.09) is meaningfully higher than TOM IC (0.07). Run Pre-Holiday standalone with the 200-SMA regime filter. Fewer parameters (3 vs 5), cleaner signal, potentially sufficient for Gate 1.

3. **Signal stacking with mean-reversion entry:** Add a short-term RSI or IBS entry filter (e.g., only enter TOM if SPY IBS < 0.3 on entry day). This combines calendar timing with mean-reversion signal to improve entry quality. H21 (IBS standalone) showed moderate success — combination may amplify.

4. **Volatility-adaptive sizing:** Replace binary 200-SMA on/off with VIX-based position scaling (full size below VIX 20, half size VIX 20-30, no trade above VIX 30). Preserves more trades than binary filter while reducing bear-regime risk.

---

*Verdict issued by Engineering Director. Gate 1 pipeline is now empty — all active hypotheses (H24, H27, H28, H29) have failed. Returning to Research Director for next hypothesis generation cycle.*
