# H07 Gate 1 Backtest Results — Multi-Asset TSMOM

**Date:** 2026-03-16
**Analyst:** Backtest Runner Agent
**Task:** QUA-116
**Parent:** QUA-111
**Strategy file:** `strategies/h07_multi_asset_tsmom.py`
**Metrics JSON:** `backtests/H07_MultiAsset_TSMOM_2026-03-16.json`

---

## Gate 1 Verdict: FAIL

**5 of 12 criteria failed.** Strategy does not advance to Gate 2.

---

## Performance Summary

| Metric | IS (2018–2021) | OOS (2022–2023) | Threshold | Pass? |
|--------|---------------|-----------------|-----------|-------|
| Sharpe Ratio | **1.2547** | **0.4680** | IS > 1.0, OOS > 0.7 | IS ✓ / OOS ✗ |
| Max Drawdown | -12.76% | -5.39% | IS < 20%, OOS < 25% | ✓ / ✓ |
| Win Rate | 66.67% | 50.00% | > 50% | ✓ |
| Win/Loss Ratio | 6.26× | — | ≥ 1.0 | ✓ |
| Trade Count | **9** | 8 | ≥ 50 | ✗ |
| Total Return | +48.8% | +16.2% | — | — |
| Post-Cost Sharpe | 1.2547 | — | (embedded in IS) | — |

---

## Walk-Forward Analysis (4 Windows, 36m IS / 6m OOS)

**Windows Passed: 3/4** (threshold: ≥ 3) ✓
**WF Consistency Score: 0.650** (threshold: ≥ 0.70) ✗

| Window | IS Period | OOS Period | IS Sharpe | OOS Sharpe | IS MDD | OOS MDD | Pass? |
|--------|-----------|------------|-----------|------------|--------|---------|-------|
| 1 | 2018-01-01 – 2020-12-31 | 2021-01-01 – 2021-06-30 | 1.157 | **1.674** | -12.76% | -4.62% | ✓ |
| 2 | 2018-07-01 – 2021-06-30 | 2021-07-01 – 2021-12-31 | 1.084 | **1.300** | -12.92% | -5.54% | ✓ |
| 3 | 2019-01-01 – 2021-12-31 | 2022-01-01 – 2022-06-30 | 1.096 | **0.710** | -10.24% | -8.15% | ✓ |
| 4 | 2019-07-01 – 2022-06-30 | 2022-07-01 – 2022-12-31 | 0.995 | **-0.690** | -8.10% | -8.36% | ✗ |

**Note:** Window 4 fails. H2 2022 (July–December) was the acute 2022 bear market / Fed hiking shock. TSMOM typically suffers when momentum reverses sharply mid-period. Window 4 IS Sharpe also dips below 1.0 (0.995).

---

## Statistical Rigor

### Monte Carlo (1,000 resamples on trade PnL)

| Metric | Value |
|--------|-------|
| MC p5 Sharpe | 6.36 |
| MC Median Sharpe | 12.60 |
| MC p95 Sharpe | 20.53 |

> **Caution:** Only 9 IS trades. Bootstrap on trade-level PnL with very few trades produces unreliable/inflated Sharpe estimates. MC results should not be interpreted at face value. True uncertainty bounds require more trades.

### Block Bootstrap 95% CI (IS daily returns, 1,000 boots)

| Metric | 2.5th pct | 97.5th pct |
|--------|-----------|------------|
| Sharpe | 0.370 | 2.260 |
| Max Drawdown | -19.1% | -4.5% |
| Win Rate (daily) | 49.2% | 53.4% |

CI is wide due to small number of signals. Lower bound Sharpe (0.37) is below the > 1.0 threshold.

### Deflated Sharpe Ratio (DSR)

**DSR ≈ 0.0000** (rounds to zero at 4 decimal places; technically > 0)
With 14 parameter combinations tested, the expected maximum Sharpe (sr\*) ≈ 1.73, which exceeds the observed IS Sharpe of 1.25. The DSR is extremely small, indicating that the observed Sharpe is not clearly above what would be expected by data-mining chance across the parameter grid. This is a weak signal.

### Permutation Test (500 permutations)

**p-value = 0.426 — FAIL** (threshold: ≤ 0.05)
42.6% of random entry permutations achieved a Sharpe ≥ observed IS Sharpe. The strategy's alpha is not statistically distinguishable from noise at the 5% level. Primary contributor: too few trades (9) makes the permutation test underpowered.

### Market Impact (SPY representative)

| Metric | Value |
|--------|-------|
| Market Impact | 0.0141 bps |
| Q/ADV Ratio | 0.000001 |
| Liquidity Constrained | No |

Market impact is negligible for SPY at $25K capital. No liquidity constraints.

---

## Parameter Sensitivity Scan (IS period 2018–2021)

| Parameter | Value | IS Sharpe |
|-----------|-------|-----------|
| lookback_months | 6 | ~varies |
| lookback_months | 9 | ~varies |
| lookback_months | 12 | 1.2547 |
| lookback_months | 18 | ~varies |
| rebalance_frequency | monthly | 1.2547 |
| rebalance_frequency | quarterly | ~varies |
| universe_size | 4 | ~varies |
| universe_size | 6 | 1.2547 |
| intramonth_stop_pct | 0.15 | ~varies |
| intramonth_stop_pct | 0.20 | 1.2547 |
| intramonth_stop_pct | 0.25 | ~varies |

**Sharpe Range: 0.363**
**Variance: 30.9% > 30% — FAIL** (just above threshold)

The sensitivity failure is marginal — 0.9% above the 30% threshold. One combination likely drives the range.

---

## H07-Specific Analysis

### USO/DBC Rolling 12-Month Correlation

**Max Rolling Correlation: 0.9398 — FLAG ✗** (threshold: > 0.7)

USO/DBC correlation peaked at **0.94** — extremely high. DBC holds ~30–40% crude oil, creating structural co-movement with USO. This correlation significantly reduces the diversification benefit of including both in the same universe.

**Research Director recommendation (QUA-111):** Consider replacing USO with **SLV** (silver) or **DBB** (industrial metals) for improved diversification. This could increase the information ratio of the multi-asset portfolio.

### Trade Frequency Issue (Critical)

The strategy generated only **9 trades** across 6 tickers over 4 years (IS period). This is structurally inherent to TSMOM:
- Monthly rebalancing with long hold periods
- Most assets maintain the same momentum direction for extended periods (e.g., QQQ: 1 trade = held long entire IS period)
- `accumulate=False` in vectorbt correctly ignores re-entry signals while in position

The 50-trade minimum threshold is structurally unachievable without:
1. Shortening the lookback period (increases signal noise)
2. Trading a much larger universe (more assets, more trades)
3. Adding intramonth rebalancing triggers (departs from spec)

---

## Failing Criteria Summary

| Criterion | Threshold | Actual | Gap |
|-----------|-----------|--------|-----|
| OOS Sharpe | > 0.70 | 0.468 | -0.232 |
| Trade Count | ≥ 50 | 9 | -41 |
| WF Consistency | ≥ 0.70 | 0.650 | -0.050 |
| Sensitivity | ≤ 30% variance | 30.9% | marginal |
| Permutation p | ≤ 0.05 | 0.426 | underpowered |

---

## Passing Criteria

| Criterion | Threshold | Actual |
|-----------|-----------|--------|
| IS Sharpe | > 1.0 | **1.255** ✓ |
| IS Max Drawdown | < 20% | **-12.8%** ✓ |
| OOS Max Drawdown | < 25% | **-5.4%** ✓ |
| Win Rate | > 50% | **66.7%** ✓ |
| Win/Loss Ratio | ≥ 1.0 | **6.26×** ✓ |
| WF Windows (3/4) | ≥ 3 | **3/4** ✓ |
| DSR | > 0 | **~0** (marginal) ✓ |

---

## Recommendations for Engineering Director

1. **Trade count is the most critical structural issue.** The 50-trade threshold is incompatible with a 6-ETF TSMOM strategy. Either the threshold should be waived/reduced for momentum strategies, or the universe must be expanded (e.g., 20+ assets).

2. **OOS Sharpe of 0.47 is below threshold.** The strategy suffers in H2 2022 (rate hike shock). Consider adding a regime filter (e.g., VIX > 30 → reduce exposure) or a trend confirmation filter.

3. **USO/DBC correlation (0.94) is a structural diversification problem.** Replace USO with SLV or DBB per Research Director guidance.

4. **Permutation test failure is underpowered** (9 trades). Cannot be conclusive. More trades needed before this test is meaningful.

5. **Sensitivity is marginal (30.9%).** A small lookback adjustment could bring this within threshold.

---

## Output Files

- `backtests/H07_MultiAsset_TSMOM_2026-03-16.json` — Full metrics JSON
- `backtests/H07_MultiAsset_TSMOM_2026-03-16_verdict.txt` — Verdict summary
- `research/backtest_results/h07_gate1_results.md` — This report
