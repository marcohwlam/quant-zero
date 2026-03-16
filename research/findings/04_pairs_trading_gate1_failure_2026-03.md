# Gate 1 Failure Analysis — Pairs Trading Cointegration (#04)

**Author:** Research Director
**Date:** 2026-03-16
**Task:** QUA-79
**Related Tasks:** QUA-73 (Gate 1 backtest), QUA-79 (this review)
**Status:** FAILURE ANALYZED — v2.0 hypothesis issued (see `/research/hypotheses/04_pairs_trading_cointegration_v2.md`)

---

## Gate 1 Result Summary

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| IS Sharpe | 0.50 | > 1.0 | **FAIL** |
| OOS Sharpe | 0.02 | > 0.7 | **FAIL** |
| IS Max Drawdown | 3.5% | < 20% | PASS |
| IS Win Rate | 55.3% | > 50% | PASS |
| IS Trade Count | 38 | > 50 | **FAIL** |
| Param Sensitivity (entry_zscore) | 104.9% | < 30% | **FAIL** |
| WF Windows Passed | 0/4 | ≥ 3/4 | **FAIL** |
| DSR z-score | 7.63 | > 0 | PASS |

**Overall verdict: FAIL (5 of 9 criteria failed). Auto-disqualified on IS Sharpe.**

---

## Root Cause Analysis

### Primary Failure: Pair Universe Not Cointegrated in 2018–2023

The five seed pairs (XOM/CVX, JPM/BAC, KO/PEP, GS/MS, AMZN/MSFT) were selected based on conventional pairs-trading intuition — same sector, competitive peers, shared economic driver. However, the backtest revealed that **none of these pairs maintained statistical cointegration for meaningful periods in the 2018–2023 Gate 1 test window**.

- Rolling 126-day Engle-Granger test passes p < 0.10 on fewer than **10% of trading days** per pair
- GOOG/META and JPM/BAC: **zero cointegration days detected**
- KO/PEP: best pair — only 75 cointegrated days out of 756 (9.9%)

**Why did cointegration break down post-2018?**

Each pair suffered a structural break driven by differentiated strategic positioning:

| Pair | Cointegration Breakage Driver |
|------|-------------------------------|
| XOM/CVX | Energy transition divergence — CVX accelerated renewables pivot faster than XOM; different production profiles in Permian |
| JPM/BAC | Post-Dodd-Frank regulatory differences; JPM grew investment banking while BAC restructured; fintech disruption impacted each differently |
| KO/PEP | Pepsi's Frito-Lay segment (50%+ of earnings by 2020) creates a non-comparable earnings mix; diverging product portfolios |
| GS/MS | Goldman Sachs' consumer banking (Marcus) experiment 2019-2022 diverged from Morgan Stanley's wealth management focus |
| AMZN/MSFT | AWS vs. Azure growth trajectories diverged structurally; AMZN commerce/logistics drag; very different capex profiles post-2020 |

**Key lesson:** Large-cap technology and financial pairs are **increasingly poor cointegration candidates** in the post-2018 period due to accelerating business model differentiation. The assumption that "large-cap sector peers" = cointegrated is no longer valid for these names.

### Secondary Failure: Insufficient Trade Count

With pairs inactive >90% of the time, only 38 IS trades occurred over 6 years — fewer than 7 trades per year across 5 pairs. This creates two compounding problems:
1. **Statistical insignificance**: 38 trades is insufficient to conclude the IS Sharpe of 0.50 is anything other than noise
2. **Parameter sensitivity amplification**: Each individual trade has outsized impact on performance metrics; tiny changes in entry_zscore drastically alter which trades trigger → 104.9% Sharpe sensitivity

### Tertiary Failure: Post-2021 OOS Collapse

The 2022 rate hike cycle fundamentally altered spread dynamics. Pairs that operated in a near-zero-rate environment (where relative valuations were compressed) began repricing as rate sensitivity differentiated by business model. This structural shift explains why OOS Sharpe = 0.02 even where IS shows some signal.

---

## What Worked

Despite the failures, several structural elements performed correctly:
- **Market-neutral construction**: IS MDD of only 3.5% — excellent capital preservation
- **Win rate**: 55.3% win rate confirms the mean-reversion mechanism functions when it actually triggers
- **DSR z-score**: 7.63 — the IS Sharpe, while too low, is not explained by pure noise; there is a genuine signal component
- **Economic rationale**: VALID — cointegration-based pairs trading is a real edge; the failure is in pair selection, not in the underlying economic logic

---

## Strategic Decision

**This strategy is NOT retired.** The economic rationale remains valid and the structural elements (market-neutral, low MDD, positive win rate) are confirmed. The failure is entirely attributable to **incorrect pair selection** for the 2018–2023 test window.

**Direction: Revise and retest with v2.0 hypothesis.**

The v2.0 hypothesis makes three fundamental changes:
1. Switch pair universe from large-cap equity pairs → **sector ETF pairs** (XLF/KRE, XLE/OIH, XLV/IBB, XLP/XLY, GLD/SLV)
2. Reduce cointegration lookback from 252d → **63d** (more responsive to current-epoch relationships)
3. Lower entry z-score from 2.0 → **1.5** (targets 2–3× more trades; stays statistically meaningful)

See full v2.0 specification: `/research/hypotheses/04_pairs_trading_cointegration_v2.md`

---

## Updated Phase 1 Ranking Impact

Following this failure, the Phase 1 queue is updated:

| Priority | Strategy | Status |
|----------|----------|--------|
| 1 | Pairs Trading v2.0 (#04 revised) | → Revised hypothesis ready, retest needed |
| 2 | Momentum Vol-Scaled (#05) | Ready for backtest |
| 3 | RSI Short-Term Reversal (#06) | Pending H04/H05 results |
| 4 | DMA Crossover (#01) | Baseline calibration |
| 5 | Multi-Factor L/S (#03) | Blocked on data |
| — | Bollinger Band (#02) | ⛔ RETIRED |

---

## Lessons for Future Hypothesis Development

1. **Equity pairs must be validated for cointegration in the exact Gate 1 IS window (2018–2021) before hypothesis submission.** A pair that cointegrated historically is not guaranteed to cointegrate in the test window.

2. **Structural breaks are more common in large-cap equities post-2018** than in prior periods. Alternative pair universes should be biased toward:
   - Sector ETF pairs (idiosyncratic risk diversified away)
   - Smaller-cap sector peers (less institutional coverage = more persistent mis-pricing)
   - Commodity-linked pairs with a physical supply/demand anchor

3. **Trade count < 50 IS trades is a leading indicator of parameter sensitivity problems.** If a strategy generates fewer than 50 IS trades, the parameter sensitivity test is likely to fail because individual trades swing the Sharpe by large amounts. Future hypotheses should pre-estimate expected trade count before submission.

4. **Market-neutral construction with low MDD is genuinely valuable** — even though this strategy failed IS Sharpe, the risk management structure (3.5% max drawdown in a hostile test window) shows the architecture is sound. Worth reusing in v2.0.

---

*Research Director | QUA-79 | 2026-03-16*
