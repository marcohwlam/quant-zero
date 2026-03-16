# GATE 1 VERDICT: FAIL
**Strategy:** H12 SuperTrend ATR Momentum v1.0
**Date:** 2026-03-16
**Submitted by:** Risk Director (QUA-148)
**Backtest source:** QUA-154 (Backtest Runner)
**Overfit Detector input:** Integrated in QUA-154 (DSR, permutation test, MC simulation)

---

## QUANTITATIVE SUMMARY

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| IS Sharpe (2018–2022) | -0.007 | > 1.0 | **FAIL** ⚠️ AUTO-DISQUALIFY |
| OOS Sharpe (2023–2024) | 1.473 | > 0.7 | PASS |
| Walk-forward consistency (OOS/IS ratio) | N/A (IS Sharpe ≤ 0) | OOS within 30% of IS | **FAIL** |
| IS Max Drawdown | -118.2% | < 20% | **FAIL** ⚠️ AUTO-DISQUALIFY |
| OOS Max Drawdown | -36.6% | < 25% | **FAIL** |
| Win Rate | 38.0% | > 50% | **FAIL** |
| Deflated Sharpe Ratio | 0.034 | > 0 | PASS |
| Parameter sensitivity | 10,353% degradation | < 30% | **FAIL** |
| Walk-forward windows passed | 0/4 | ≥ 3 | **FAIL** |
| Post-cost performance | -0.007 (unchanged) | Must pass post-cost | **FAIL** (IS Sharpe negative) |
| Permutation p-value | 0.806 | ≤ 0.05 | **FAIL** |
| MC p5 Sharpe | -4.03 | > 0.5 | **FAIL** |
| Trade count (IS) | 50 | ≥ 30 | PASS |
| Information Coefficient | 0.093 | > 0.02 | PASS |

**Criteria passed: 4/12**

### Automatic Disqualification Flags

1. **IS Sharpe = -0.007 < 0** — Strategy has negative expected return in the in-sample period. This is an immediate automatic disqualification regardless of all other metrics.
2. **IS Max Drawdown = -118.2%** — This exceeds the 20% threshold by 5.9×. A drawdown exceeding 100% implies the strategy is not viable as a standalone implementation.

The verdict is **REJECT** based on these two flags alone. No further analysis is required to reject.

---

## KELLY CRITERION ANALYSIS

- IS annualized mean return (mu): Negative (IS Sharpe = -0.007 with any positive vol → mu < 0)
- Kelly fraction (f* = mu/sigma²): **Negative — strategy has no positive edge**
- Recommended max position: **N/A** — Kelly cap is zero when f* ≤ 0
- Kelly flag: **REJECT — negative expected return. Kelly framework does not apply to strategies with no positive edge.**

*No position sizing analysis is possible or meaningful for a strategy with negative IS Sharpe.*

---

## QUALITATIVE ASSESSMENT

### Economic Rationale
**VALID concept, BROKEN implementation.** The SuperTrend indicator is a legitimate trend-following signal used by practitioners. However, the ATR 2.5×14 base parameter is the **worst-in-grid** — a form of inverted overfitting where the published "default" underperforms all alternatives. This suggests either:
- The parameter was chosen without in-sample validation on US equities, OR
- The backtest is using a parameter calibrated on a different asset class/timeframe

### Look-Ahead Bias
**NONE DETECTED.** The backtest runner certified no look-ahead bias. Regime gate (VIX < 30 + 200-day SMA) correctly uses lagged data. `look_ahead_bias_flag: false`.

### Overfitting Risk
**HIGH (double-edged).** The strategy exhibits both:
1. **Regime gate over-suppression:** The VIX < 30 filter eliminated all entries in 2021 and 2022 (the two most important sub-periods for trend-following validation). The strategy has 0 trades in 2021 and 2022 — the years with highest drawdown in SPY. This is exactly the opposite of what a working trend-following strategy should do.
2. **OOS window too small:** 18 OOS trades (2023–2024) concentrated in a single bull market regime. OOS Sharpe = 1.473 is statistically meaningless with this sample size and regime concentration.
3. **Parameter space non-convexity:** The sensitivity scan reveals isolated positive-Sharpe islands (ATR 2.0×7: IS Sharpe=0.877) but no stable region. The parameter landscape is extremely rough — consistent with noise rather than signal.

### Walk-Forward Analysis
**Critical failure:** All 4 walk-forward OOS windows show Sharpe = 0.0 because the regime gate (VIX < 30 + 200-day SMA) blocked all entries during every 6-month OOS test period. This is a structural paradox: the regime gate is so conservative that it prevents the strategy from trading in any volatile market period — precisely the periods where trend-following should perform.

### Sub-Period Analysis
| Period | IS/OOS | Sharpe | Trades | Assessment |
|--------|--------|--------|--------|------------|
| Pre-COVID bull (2018–2019) | IS | -0.258 | 14 | FAIL — negative in calm bull |
| COVID crash/recovery (2020) | IS | 8.799 | 3 | Spurious — 3 trades, not statistically valid |
| Post-COVID bull (2021) | IS | 0.000 | 0 | Regime gate blocked all entries |
| 2022 rate-shock bear | IS | 0.000 | 0 | **CRITICAL FAIL** — regime gate blocked trend-following in best trend year |
| Post-2022 recovery (2023–2024) | OOS | 1.473 | 18 | Concentrating all signal in bull |

The 2022 failure is **disqualifying on its own merit** — a trend-following strategy that generates zero trades in 2022 has failed its primary use case.

---

## VERDICT

```
GATE 1 VERDICT: FAIL
Strategy: H12 SuperTrend ATR Momentum v1.0
Date: 2026-03-16

RECOMMENDATION: REJECT — Do not promote to paper trading.
CONFIDENCE: HIGH
```

### Concerns

1. **The VIX/SMA regime gate is structurally broken for this strategy.** It prevents entries in the exact market conditions where ATR trend-following should excel (high volatility, trending). If re-submitted, the regime gate logic needs fundamental rethinking — or removal.

2. **The ATR 2.5×14 base parameter is the worst combination tested.** If a version of this strategy is ever re-submitted, the parameter selection methodology must be documented. Cherry-picking inverse (choosing the worst default) is a red flag for an unvetted external signal.

3. **OOS performance is entirely attributable to 18 trades in a single bull market.** This is not a valid out-of-sample test.

4. **Permutation p-value = 0.806** means the strategy's IS performance cannot be statistically distinguished from random. There is no evidence of alpha in the in-sample period.

### Path to Re-submission (if desired)

If Engineering Director wishes to revisit SuperTrend ATR:
- Remove or redesign the VIX regime gate — it is eliminating signal, not protecting capital
- Optimize ATR multiplier/lookback in-sample (currently the published default is worst-in-grid)
- Require IS Sharpe > 1.0 with at least 4 sub-periods showing positive Sharpe
- The 2022 bear must show positive Sharpe with meaningful trade count (≥ 10 trades)

---

*Risk Director verdict | 2026-03-16 | agent 0ba97256 | Source: QUA-148, QUA-154*
