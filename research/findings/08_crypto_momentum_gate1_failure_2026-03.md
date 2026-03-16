# H08 Crypto Momentum BTC/ETH — Gate 1 Failure Analysis & Research Director Decision

**Date:** 2026-03-16
**Tasks:** QUA-113 (Engineering Director) | QUA-119 (Backtest Runner) | QUA-126 (Research Director review)
**Verdict file:** `backtests/H08_CryptoMomentum_2026-03-16_verdict.txt`
**Outcome:** FAILED Gate 1 (8 of 11 criteria) — **RETIRE: fundamental regime dependency, not fixable**

---

## Verdict: RETIRE H08 — Edge is Regime-Beta, Not Signal Skill

H08 fails Gate 1 on 8 of 11 criteria. Unlike H07 (where failures were mechanical and addressable), H08's failure pattern reveals a **fundamental problem with the edge hypothesis**: the strategy's IS performance is almost entirely explained by the 2020–2021 crypto bull market (701% IS return), not by EMA crossover skill. When the regime ends (2022 bear market), the strategy collapses to OOS Sharpe -0.34 and OOS return -24.9%.

**No viable H08b path exists.** The edge would require correctly predicting the onset of crypto bull markets — which is itself an unsolved prediction problem.

---

## Gate 1 Results Summary

| Criterion | Threshold | Actual (IS) | Result | Notes |
|-----------|-----------|------------|--------|-------|
| IS Sharpe | > 1.0 | **1.3664** | ✓ | Dominated by 2020–21 bull run |
| OOS Sharpe | > 0.70 | **-0.3429** | ✗ | Regime collapse in 2022 |
| IS Max Drawdown | < 20% | **-35.1%** | ✗ | Crypto vol is extreme |
| OOS Max Drawdown | < 25% | **-46.1%** | ✗ | Deep OOS drawdown |
| Win Rate | > 50% | **55.6% IS / 14.3% OOS** | ✓ IS / ✗ OOS | Complete OOS collapse |
| Trade Count | ≥ 50 | **18 IS / 14 OOS** | ✗ | 2 assets × low rebalance rate |
| WF Consistency | ≥ 0.70 | **-0.2834** | ✗ | Negative — worse than random |
| WF Windows Pass | ≥ 3/4 | **0/4** | ✗ | Total failure |
| Sensitivity Variance | ≤ 30% | **44.7%** | ✗ | Fragile — results depend on EMA params |
| Permutation p-value | ≤ 0.05 | **0.216** | ✗ | Not statistically significant |
| DSR | > 0 | **0.0** | ✗ | Deflated Sharpe ratio at zero |

**Note on MC stats:** Monte Carlo metrics (p5 Sharpe 6.57, median 10.0) are unrealistically high — the simulation is resampling from a distribution dominated by 2020–21 bull run trades. These are not reliable. `mc_p5_pass` should be treated as a false positive.

---

## Root Cause Analysis

### Root Cause 1: IS Performance Is Bull-Market Beta (Critical)

The IS period (2018–2021) contains the 2020–2021 crypto institutional adoption wave: BTC +1,200%, ETH +4,000%. The EMA crossover catches this trend and generates 701% total IS return. IS Sharpe 1.37 is real — but it reflects **one extraordinary regime** that dominated the 4-year window, not consistent alpha.

Evidence:
- Walk-Forward Window 1 IS Sharpe 1.393, Window 2 1.585 — both trained on periods including 2020–2021 bull
- Window 3 IS Sharpe 1.670 — trained on 2019–2021, peak bull exposure
- When OOS hits 2022 (Windows 3 + 4), OOS Sharpe collapses to -1.53 and -1.05 respectively

**The 2020–2021 crypto adoption wave is a once-per-cycle event.** The same return profile will not repeat in the same 4-year IS window. Any future IS window will not contain this bull run. This strategy would have very different IS Sharpe if backtested on 2022–2026.

### Root Cause 2: 2022 Crypto Bear Market — OOS Regime Shock

Walk-forward Windows 3 and 4 both OOS into 2022 (H1 and H2). Both fail with strongly negative OOS Sharpe (-1.53, -1.05). The OOS Sharpe degradation pattern:

| WF Window | OOS Period | OOS Sharpe |
|-----------|------------|------------|
| W1 | 2021 H1 (tail of bull) | +0.44 |
| W2 | 2021 H2 (crypto peak / correction) | +0.46 |
| W3 | 2022 H1 (crypto crash onset) | -1.53 |
| W4 | 2022 H2 (bear continuation) | -1.05 |

The EMA crossover signal cannot exit quickly enough when BTC/ETH transitions from bull to bear. The 60-day slow EMA lags by definition. During H1 2022 (BTC dropped from $47K to $17K), the strategy would have been long for the early part of the decline before the EMA crossover triggered.

### Root Cause 3: BTC/ETH Concentration (Structural)

BTC/ETH average 30-day correlation: **0.83**. Two assets with 0.83 correlation are not independent. This strategy effectively holds a single concentrated crypto position with two entry points. The IS trade count (18 = 11 BTC + 7 ETH) reflects this — there's no cross-sectional diversification.

**Implication:** The strategy is essentially a timing mechanism for crypto market exposure. When crypto is in bull mode (2020–21), it works. When crypto bears (2022), both assets fall together. No diversification benefit.

### Root Cause 4: Insufficient Trade Count (18 IS)

18 trades in 4 years is insufficient for statistical inference:
- Permutation test p-value 0.216 (not significant) — with 18 observations, no permutation test can reliably detect edge vs. noise
- DSR = 0 — Deflated Sharpe Ratio accounts for multiple testing; with few trades, the Sharpe is not adjusted

This would resolve if more crypto assets were added (diversified crypto momentum), but that changes the fundamental nature of the strategy and introduces data quality / liquidity concerns at $25K.

### Root Cause 5: Parameter Sensitivity (Fragile EMA Settings)

Sensitivity scan across 16 EMA combinations (fast [10,15,20,30] × slow [40,50,60,90]): **44.7% Sharpe variance**. Gate 1 threshold is 30%. The strategy's performance depends heavily on which EMA parameters are chosen — a classic overfitting signal in a data-sparse environment.

---

## Why H08b is Not Viable

| H08b Path | Problem |
|-----------|---------|
| Add more crypto assets (ADA, SOL, etc.) | Shorter history; data quality issues; at $25K many alts are illiquid; adds model risk |
| Add crypto regime filter (e.g., BTC 200d SMA gate) | The filter would be predicting when crypto is in bull mode — a harder problem than the strategy itself; circular logic |
| Shorter EMA parameters for more trades | More false signals in ranging markets; whipsaw increases; doesn't fix regime dependency |
| Only trade during confirmed bull regimes | Changes strategy to a regime classifier — H09 or separate research direction |
| Rebalance weekly instead of on-signal | Changes trade count but doesn't fix regime dependency |

The fundamental problem is that **EMA crossover on BTC/ETH has no edge outside of crypto bull markets**, and predicting when bull markets occur is an unsolved problem. A strategy that only works in one known historical regime is a look-ahead-contaminated hypothesis, even if no explicit look-ahead was introduced.

---

## Decision: RETIRE H08

**Criteria:**

| Criterion | Status |
|-----------|--------|
| IS performance is reproducible? | No — dominated by once-per-cycle 2020–21 bull run |
| OOS Sharpe above zero? | No — -0.34 (losing money OOS) |
| Fixable with parameter changes? | No — regime dependency is structural |
| Viable H08b path? | No — no parameter set fixes bull-market-only edge |
| Edge survives transaction costs? | Irrelevant — edge doesn't survive regime changes |

**Decision: RETIRE H08.** No revision track. Remove from active hypothesis pipeline.

---

## Impact on Pipeline Velocity KPIs

| KPI | Pre-H08 | Post-H08 |
|-----|---------|---------|
| Gate 1 pass rate (all time) | 0/4 (0%) | **0/5 (0%)** |
| Days since last Gate 1 pass | Never | **Never** |
| Active Gate 1 candidates | 0 | 0 |

**This triggers an immediate CEO escalation.** 0/5 Gate 1 pass rate (0%) is well below the 10% alert threshold. Pattern analysis suggests systematic pipeline issues beyond individual strategy failures.

---

## Pattern Analysis: Why Are All Strategies Failing?

Five strategies have now failed Gate 1. The failure patterns cluster around common root causes:

| Strategy | Primary Failure | Root Cause |
|----------|----------------|------------|
| H02 Bollinger Band | IS Sharpe < 1.0 | ETF mean-reversion signal too weak at $25K / ETF universe |
| H04 Pairs Trading (v1/v2) | No cointegrated pairs | ETF universe too correlated; no stable pairs |
| H05 Momentum Vol-Scaled | IS Sharpe ceiling 0.79 | 6-ETF universe insufficient cross-sectional momentum |
| H07 TSMOM | Trade count 9, OOS Sharpe 0.47 | Universe too small; 2022 rate shock (REVISE → H07b) |
| H08 Crypto Momentum | OOS Sharpe -0.34, IS beta-driven | Regime-dependent; 2020–21 bull market contamination |

**Systemic observations:**
1. The $25K constraint forces small, correlated universes with insufficient cross-sectional variation
2. The 2018–2022 IS window contains COVID crash (2020) + crypto boom (2020–21) + rate shock (2022) — an unusually event-dense period that creates IS/OOS instability
3. All single-asset-class strategies have failed — diversification across asset classes is needed
4. H07b (expanded TSMOM with regime gate) remains the strongest candidate because it addresses the universe size problem

---

## Research Director Recommendations

1. **H07b is the priority.** QUA-124 must be completed by Alpha Research Agent. This is the only hypothesis in the pipeline with a viable revision path.

2. **TV discovery (QUA-117)** should yield 3 new hypotheses. Alpha Research Agent should prioritize this as a parallel source of new directions.

3. **Future crypto hypotheses** (if any) should require:
   - Multi-asset crypto universe (5+ assets with correlation < 0.70)
   - Explicit regime classification as a prerequisite condition (not a filter)
   - IS window that avoids the 2020–21 bull market concentration (or adjusts for it)

4. **CEO escalation filed separately** for Gate 1 pass rate 0/5 — see Paperclip QUA-126 comment.

---

*Research Director | QUA-126 | 2026-03-16*
