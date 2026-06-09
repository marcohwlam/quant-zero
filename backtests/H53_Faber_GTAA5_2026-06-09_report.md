# H53 Faber GTAA-5 — Gate 1 Report

**Date:** 2026-06-09
**Strategy:** Equal-weight (20%) across SPY/EFA/IEF/GSG/VNQ. Hold asset if price > 10-month MA; substitute SHY otherwise. Monthly rebalance.
**IS Period:** 2007-01-01 to 2023-12-31 (GSG-constrained)
**OOS Period:** 2024-01-01 to 2025-12-31
**Overall Gate 1 Verdict: FAIL**
**Borderline note:** IS Sharpe estimated 0.80–1.05 (academic). Published MDD -9.5% well inside <20% gate.

---

## Core Gate 1 Metrics

| Criterion | Value | Threshold | Status |
|---|---|---|---|
| IS Sharpe | 0.5475 | > 1.0 | FAIL |
| OOS Sharpe | 1.1533 | > 0.7 | PASS |
| IS CAGR | 4.3% | — | — |
| IS Max Drawdown | -15.1% | < 20% | PASS (<20%) |
| OOS Max Drawdown | -6.5% | < 25% | PASS (<25%) |
| Win Rate (IS) | 39.3% | ≥ 50% or PF ≥ 1.2 | PASS |
| Profit Factor (IS) | 2.1906 | > 1.0 | PASS |
| Trade Count (IS) | 89 | ≥ 100 | FAIL |
| IS Total Return | 106.0% | — | — |
| OOS Total Return | 17.9% | — | — |
| Avg Assets in SHY (IS) | 1.8/5 | — | — |

---

## Per-Asset Breakdown (IS)

| Asset | Trades | Win Rate | Total PnL | Transitions |
|---|---|---|---|---|
| SPY | 15 | 60.0% | $48,044 | 29 |
| EFA | 17 | 47.1% | $15,266 | 33 |
| IEF | 19 | 36.8% | $11,353 | 37 |
| GSG | 20 | 20.0% | $4,014 | 40 |
| VNQ | 18 | 38.9% | $14,719 | 35 |

---

## Walk-Forward Analysis (4 windows, 48m IS / 12m OOS)

| Window | IS Period | IS Sharpe | OOS Period | OOS Sharpe | IS MDD | IS Trades | Avg SHY | Status |
|---|---|---|---|---|---|---|---|---|
| W1 | 2007-01-01–2010-12-31 | 0.5978 | 2011-01-01–2011-12-31 | -0.0403 | -11.5% | 21 | 1.88 | **FAIL** |
| W2 | 2008-01-01–2011-12-31 | 0.4038 | 2012-01-01–2012-12-31 | -0.057 | -15.1% | 21 | 2.04 | **FAIL** |
| W3 | 2009-01-01–2012-12-31 | 0.5148 | 2013-01-01–2013-12-31 | 0.5942 | -15.8% | 23 | 1.5 | **PASS** |
| W4 | 2010-01-01–2013-12-31 | 0.4728 | 2014-01-01–2014-12-31 | 2.0228 | -15.2% | 26 | 1.4 | **PASS** |

**WF passed:** 2/4 | **Consistency:** 1.306 | **Sharpe std:** 0.8459 | **Sharpe min:** -0.057

---

## Statistical Rigor

| Test | Value | Status |
|---|---|---|
| DSR (n=15 trials) | 0.000000 | FAIL |
| MC p5 Sharpe | 0.1348 | FAIL |
| MC Median Sharpe | 0.5365 | — |
| Sharpe CI [95%] | [0.1433, 0.9384] | — |
| MDD CI [95%] | [-0.3019, -0.1075] | — |
| Permutation p-value | 0.592 | FAIL (>0.05) |

---

## Sensitivity Analysis

### MA Lookback (5 combinations: 8–12 months)
PASS: Sharpe variance 21.7% ≤ 30% across 5 MA lookback combinations.

| Config | IS Sharpe |
|---|---|
| ma_8mo | 0.6243 |
| ma_9mo | 0.6331 |
| ma_10mo | 0.5476 |
| ma_11mo | 0.5084 |
| ma_12mo | 0.564 |

### Commodity ETF Variant (GSG / DJP / PDBC)

| Config | IS Sharpe |
|---|---|
| commodity_GSG | 0.5476 |
| commodity_DJP | 0.571 |
| commodity_PDBC | 0.6494 |

---

## Data Quality Checklist

- **Universe/survivorship bias:** SPY/EFA/IEF/GSG/VNQ/SHY are live ETFs. GSG inception 2006-06-22; first valid MA signal April 2007. Jan-Mar 2007 GSG slice defaults to SHY (conservative). No survivorship bias in ETF universe.
- **Price adjustments:** auto_adjust=True (yfinance). Splits and dividends adjusted.
- **Data gaps:** Checked per ticker; forward-fill NOT applied for gaps >= 5 days.
- **Earnings exclusion:** N/A — ETF strategy (no earnings events).
- **Delisted tickers:** N/A — SPY/EFA/IEF/GSG/VNQ/SHY all active.
- **GSG inception note:** GSG inception 2006-06-22. 10-month MA first computable ~Apr 2007. GSG slice defaults to SHY for Jan-Mar 2007 (3 months, conservative).

---

## Risk Flags

- **Look-ahead bias:** None. MA computed at month-end T using closes through T only. Executed at same T close (Faber 2007 convention).
- **Market impact:** ETF strategy, $100K portfolio / 5 slices = $20K/slice. SPY/EFA/IEF/VNQ/GSG ADV >> $20K. Market impact << 0.1 bps per trade. Canonical model: $0.005/share + 0.05% slippage + k=0.1 sqrt-impact applied in simulation.
- **IS Sharpe borderline:** Estimated 0.80–1.05 (academic). Published MDD -9.5% well inside <20% gate.
- **Commodity concentration:** GSG is energy-heavy. DJP/PDBC provide diversification variants.

---

## Gate 1 Checklist

| Check | Pass? |
|---|---|
| is_sharpe_pass | ❌ FAIL |
| oos_sharpe_pass | ✅ PASS |
| is_mdd_pass | ✅ PASS |
| oos_mdd_pass | ✅ PASS |
| win_rate_pass | ✅ PASS |
| trade_count_pass | ❌ FAIL |
| wf_windows_pass | ❌ FAIL |
| wf_consistency_pass | ✅ PASS |
| sensitivity_pass | ✅ PASS |
| dsr_pass | ❌ FAIL |
| permutation_pass | ❌ FAIL |
| mc_p5_pass | ❌ FAIL |

---

## Verdict

**Overall Gate 1: FAIL**

Failing criteria: is_sharpe_pass, trade_count_pass, wf_windows_pass, dsr_pass, permutation_pass, mc_p5_pass

Strategy **does not pass Gate 1**. Return to Research Director for revision.
