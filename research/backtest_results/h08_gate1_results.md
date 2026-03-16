# H08 Gate 1 Backtest Results — Crypto Momentum BTC/ETH

**Date:** 2026-03-16
**Strategy File:** `strategies/h08_crypto_momentum.py`
**Asset Class:** Crypto (BTC-USD, ETH-USD)
**Backtest Period:** 2018-01-01 to 2023-12-31
**Capital:** $25,000 (50/50 BTC/ETH split)
**Task:** QUA-119

---

## Overall Gate 1 Verdict: ❌ FAIL

**9 of 12 criteria failed.** H08 Crypto Momentum does not pass Gate 1.

---

## Core Metrics Summary

| Metric | IS (2018–2021) | OOS (2022–2023) | Threshold | Result |
|---|---|---|---|---|
| Sharpe Ratio | **1.3664** | **-0.3429** | >1.0 / >0.7 | IS PASS / OOS ❌ FAIL |
| Max Drawdown | **-35.1%** | **-46.1%** | <20% / <25% | IS ❌ FAIL / OOS ❌ FAIL |
| Win Rate | **55.6%** | 14.3% | >50% | PASS |
| Win/Loss Ratio | **17.78** | — | — | (Strong when wins occur) |
| Profit Factor | **22.23** | — | — | (Driven by 2020–2021 bull) |
| Trade Count | **18** (11 BTC + 7 ETH) | **14** | ≥50 | ❌ FAIL |
| Total Return | **+701.7%** | **-24.9%** | — | — |

### Per-Asset Trade Counts (IS)
- BTC-USD: 11 trades
- ETH-USD: 7 trades
- Combined: 18 trades (EMA crossover generates few signals)

---

## Walk-Forward Analysis (4 Windows × 36m IS / 6m OOS)

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | Pass? |
|---|---|---|---|---|---|
| 1 | 2018-01-01 → 2020-12-31 | 1.393 | 2021-01-01 → 2021-06-30 | 0.439 | ❌ FAIL |
| 2 | 2018-07-01 → 2021-06-30 | 1.585 | 2021-07-01 → 2021-12-31 | 0.458 | ❌ FAIL |
| 3 | 2019-01-01 → 2021-12-31 | 1.670 | 2022-01-01 → 2022-06-30 | -1.528 | ❌ FAIL |
| 4 | 2019-07-01 → 2022-06-30 | 1.276 | 2022-07-01 → 2022-12-31 | -1.050 | ❌ FAIL |

**Windows Passed: 0/4** (threshold: ≥3)
**Consistency Score: -0.28** (threshold: ≥0.70)
**WF Sharpe Std: 0.885** (high variance)
**WF Sharpe Min: -1.528** (⚠️ multiple losing OOS windows)

**Analysis:** IS Sharpe is consistently high (1.28–1.67) but OOS performance collapses in the 2022 bear market. Windows 3 and 4 covering 2022 OOS show Sharpe of -1.53 and -1.05 respectively. This signals severe regime sensitivity — the EMA crossover strategy captured the 2019–2021 bull trend but failed catastrophically in the 2022 crypto bear market.

---

## EMA Sensitivity Scan (16 Combinations — Gate 1 Required)

Full 4×4 EMA parameter grid (IS period 2018-01-01 to 2021-12-31):

| | slow=40 | slow=50 | slow=60 | slow=90 |
|---|---|---|---|---|
| **fast=10** | 1.1714 | 1.1780 | 1.2711 | 1.2609 |
| **fast=15** | 1.1434 | 1.2429 | 1.3434 | 1.0138 |
| **fast=20** | 1.1705 | 1.3289 | **1.3664** | 0.9213 |
| **fast=30** | **1.3887** | 1.2572 | 0.9758 | 0.8606 |

**Sharpe Range:** 0.5281 (from 0.8606 to 1.3887)
**Sharpe Variance:** 44.7% of mean — **❌ FAIL** (threshold: <30%)

**Analysis:** The fast=30 / slow=40 combination (near-overlap) performs highest in IS, while fast=30 / slow=90 performs worst. The wide spread suggests the EMA crossover Sharpe is parameter-dependent and not robust.

---

## Statistical Rigor Pipeline

### Monte Carlo (1,000 resamples of IS trade PnL)
| Percentile | Sharpe |
|---|---|
| p5 (pessimistic) | **6.567** ✅ PASS (≥0.5) |
| Median | 10.008 |
| p95 | 13.856 |

*Note: High MC Sharpe values reflect the outsized win/loss ratio (17.78x) — a few large winning trades dominate the bootstrap. This is misleading given only 18 trades; small-sample bias inflates these values.*

### Block Bootstrap Confidence Intervals (IS, 95%)
| Metric | CI Low | CI High |
|---|---|---|
| Sharpe | 0.433 | 2.275 |
| Max Drawdown | -49.1% | -19.7% |
| Win Rate | 13.6% | 28.7% |

*⚠️ Win Rate CI is 13.6%–28.7% — far below the observed 55.6%, indicating high estimation uncertainty with only 18 trades.*

### Permutation Test for Alpha
- **p-value: 0.222** — ❌ FAIL (threshold: ≤0.05)
- 22.2% of randomly shuffled entry signals produce Sharpe ≥ observed
- **Conclusion:** No statistically significant alpha detected

### Deflated Sharpe Ratio (DSR)
- **DSR: 0.000** — ❌ FAIL (threshold: >0)
- With 23 parameter combinations tested, expected max Sharpe under selection bias ≈ 1.96
- IS Sharpe of 1.37 falls below this threshold — result likely due to overfitting

---

## Market Impact
**N/A** — Crypto exemption. BTC and ETH average daily volume >> $25K order size at all times. No liquidity constraints.

---

## BTC/ETH Correlation Analysis
| Metric | Value |
|---|---|
| Avg 30d Rolling Correlation | **0.825** |
| Max 30d Rolling Correlation | **0.981** |
| High Correlation Flag | ⚠️ **YES** (>0.7) |

**Risk Director Note (QUA-106):** BTC/ETH avg correlation of 0.825 causes near-simultaneous drawdowns on both assets. Combined portfolio MDD of -35.1% IS and -46.1% OOS exceeds Gate 1 thresholds. The 50/50 capital split provides no diversification benefit given near-perfect correlation.

---

## Gate 1 Criteria Checklist

| Criteria | Value | Threshold | Result |
|---|---|---|---|
| IS Sharpe | 1.3664 | >1.0 | ✅ PASS |
| OOS Sharpe | -0.3429 | >0.7 | ❌ FAIL |
| IS Max Drawdown | -35.1% | <20% | ❌ FAIL |
| OOS Max Drawdown | -46.1% | <25% | ❌ FAIL |
| Win Rate | 55.6% | >50% | ✅ PASS |
| Trade Count | 18 | ≥50 | ❌ FAIL |
| WF Windows Passed | 0/4 | ≥3 | ❌ FAIL |
| WF Consistency Score | -0.28 | ≥0.70 | ❌ FAIL |
| EMA Sensitivity | 44.7% variance | <30% | ❌ FAIL |
| DSR | 0.000 | >0 | ❌ FAIL |
| Permutation p-value | 0.222 | ≤0.05 | ❌ FAIL |
| MC p5 Sharpe | 6.567 | ≥0.50 | ✅ PASS |

**Passed: 3/12 | Failed: 9/12**

---

## Root Cause Analysis

### 1. Crypto Volatility → Excessive Drawdowns
BTC daily volatility ~60-80% annualized. With a 15% trailing stop, positions are frequently stopped out during normal intraday/intraweek crypto swings. The IS period (2018–2021) captured the massive 2020–2021 bull run, but the -35.1% IS MDD already violates the 20% threshold before accounting for OOS.

### 2. Too Few Trades (18 in 4 Years)
EMA(20/60) on daily crypto generates only 4–5 crossovers per asset per year. The 50-trade minimum cannot be met without either shorter timeframe data (hourly), a wider universe, or faster EMA parameters.

### 3. OOS Regime Collapse (2022 Bear Market)
The 2022 crypto bear market saw BTC decline ~65% and ETH ~68%. EMA crossover signals during trending-down regimes generate rapid stop-outs. Walk-forward windows 3 and 4 covering H1/H2 2022 show OOS Sharpe of -1.53 and -1.05 — confirming the strategy is a bull-market-only system.

### 4. No Alpha Beyond Selection Bias (DSR=0, p-value=0.22)
With 23 parameter combinations tested and IS Sharpe of 1.37 below the expected max of ~1.96 under selection bias, the apparent IS performance is consistent with parameter mining rather than genuine alpha.

### 5. High BTC/ETH Correlation (0.825)
The 50/50 split provides no risk reduction. Both assets trend together, amplifying drawdowns rather than diversifying.

---

## Contango Note (Live Trading)
This backtest uses spot BTC/ETH prices from Yahoo Finance. Live implementation via BITO (BTC futures ETF) incurs ~10-20%/yr contango roll drag during bull regimes (per Risk Director QUA-106). Spot backtest returns significantly overstate live BITO-based returns. FETH (Fidelity ETH ETF) launched July 2024 — not suitable for IS backtesting.

---

## Look-Ahead Bias Review
- ✅ EMA signals shifted +1 bar (computed at close T, executed at open T+1)
- ✅ No future price data used in signal generation
- ✅ Trailing stop evaluated at close prices (sl_trail=True in vbt)
- ✅ Walk-forward windows are non-overlapping for OOS evaluation

---

## Recommendations for Strategy Coder

If H08 is to be resubmitted for Gate 2, the following structural changes are required:

1. **Increase trade frequency** — Switch to hourly or 4H bars to generate ≥50 trades per year
2. **Redesign for bear regimes** — Add short-side capability or cash-reserve mode when EMA slope is negative
3. **Reduce asset correlation** — Consider BTC + a lower-correlated crypto (e.g., SOL, LINK) or reduce position sizing
4. **Tighter drawdown control** — Reduce trailing stop to 8–10% or add portfolio-level VaR circuit breaker
5. **Widen the parameter grid** — Use 6m rolling optimization windows to adapt to regime changes

---

## Output Files

- `backtests/H08_CryptoMomentum_2026-03-16.json` — Full metrics JSON
- `backtests/H08_CryptoMomentum_2026-03-16_verdict.txt` — Verdict summary
- `backtests/run_h08_gate1.py` — Backtest runner script
- This file: `research/backtest_results/h08_gate1_results.md`

---

*Produced by Backtest Runner Agent (QUA-119) — 2026-03-16*
