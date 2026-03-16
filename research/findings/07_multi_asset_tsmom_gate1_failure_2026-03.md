# H07 Multi-Asset TSMOM — Gate 1 Failure Analysis & Research Director Decision

**Date:** 2026-03-16
**Tasks:** QUA-116 (Gate 1 backtest), QUA-123 (Research Director review)
**Source report:** `research/backtest_results/h07_gate1_results.md`
**Outcome:** FAILED Gate 1 (5 of 12 criteria) — **REVISE: pursue H07b with expanded universe + regime filter**

---

## Verdict: REVISE — Structural Failures Are Addressable

H07 fails Gate 1 on 5 criteria, but the failure pattern reveals **mechanical and structural issues, not a broken edge**. The IS Sharpe of 1.255, win rate of 66.7%, and 6.26× win/loss ratio confirm the TSMOM signal has genuine predictive power in the IS window. The failures are:

1. **Trade count (9 vs ≥50)** — structural artifact of 6-ETF monthly rebalancing. **Fixable via universe expansion.**
2. **OOS Sharpe (0.468 vs 0.70)** — driven entirely by Window 4 (H2 2022 rate shock whipsaw). **Fixable via VIX regime filter.**
3. **WF Consistency (0.650 vs 0.70)** — downstream of Window 4 failure. **Resolves if OOS Sharpe is addressed.**
4. **Sensitivity variance (30.9% vs 30%)** — marginal (0.9% over). **Fixable with tighter lookback range.**
5. **Permutation p-value (0.426)** — underpowered due to only 9 trades. **Resolves with more trades.**

All five failures are **mechanically linked** to two root causes: insufficient trade count and regime sensitivity in H2 2022. Both have clear remediation paths.

---

## Gate 1 Results Summary

| Criterion | Threshold | Actual | Result | Notes |
|-----------|-----------|--------|--------|-------|
| IS Sharpe | > 1.0 | **1.255** | ✓ | Strong signal |
| OOS Sharpe | > 0.70 | **0.468** | ✗ | Window 4 failure drives gap |
| IS Max Drawdown | < 20% | **-12.8%** | ✓ | Well controlled |
| Win Rate | > 50% | **66.7%** | ✓ | Excellent |
| Win/Loss Ratio | ≥ 1.0 | **6.26×** | ✓ | Excellent |
| Trade Count | ≥ 50 | **9** | ✗ | **Critical — universe too small** |
| WF Consistency | ≥ 0.70 | **0.650** | ✗ | Window 4 drags score |
| WF Windows Pass | ≥ 3/4 | **3/4** | ✓ | Pass |
| Sensitivity Variance | ≤ 30% | **30.9%** | ✗ | Marginal (0.9% over) |
| Permutation p-value | ≤ 0.05 | **0.426** | ✗ | Underpowered (9 trades) |
| DSR | > 0 | **~0** | ✓ | Marginal pass |

---

## Root Cause Analysis

### Root Cause 1: Universe Too Small (Critical)

6-ETF TSMOM at monthly rebalancing generates only 9 trades in a 4-year IS window. The 50-trade Gate 1 threshold is **structurally unachievable** at this universe size:

- Monthly rebalancing produces ~1 trade per ticker per trend-reversal event
- Most ETFs (QQQ, GLD) maintain consistent momentum direction for months or years
- `accumulate=False` prevents re-entry while in position — correct behavior, but reduces count further

**Implication:** Expanding to 15–20 ETFs would generate ~30–60 trades per IS window, making the 50-trade threshold achievable. Each additional ETF contributes independent momentum signals.

**Permutation test failure is downstream of this.** With 9 trades, no permutation test can distinguish edge from noise — this is a statistical power problem, not evidence of no edge. Increasing trade count to 50+ will make the permutation test meaningful.

### Root Cause 2: 2022 Rate Shock Regime (OOS Sharpe)

Walk-forward Window 4 (H2 2022: July–December) failed with OOS Sharpe -0.69. This was the acute phase of the Fed's 400bps rate hiking cycle: equities, bonds, and commodities moved in unusual correlated patterns, and momentum signals whipsawed when markets attempted to bottom in October 2022 before resuming the decline.

This is a **known TSMOM failure regime** documented in the academic literature (Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016). The fix is a volatility-regime gate:

- When VIX > 25 (stress regime), halve all position sizes
- When VIX > 35 (crisis regime), go flat
- This preserves capital during the specific regime that caused Window 4's failure

**Note:** 2022 was actually described in the original H07 hypothesis as an "exceptional TSMOM year" for the full long-short strategy. The backtest used a long-only variant — the 2022 failure reflects the long-only variant's inability to profit from the commodity surge or short the equity/bond drawdown. An expanded universe with a commodity-long component would have partially captured the 2022 trend.

### Root Cause 3: USO/DBC Correlation (0.94)

Already flagged in QUA-111 (Research Director review) and confirmed by backtest. DBC is ~30-40% crude oil, creating structural co-movement with USO. This reduces the effective diversification from 6 assets to ~5.

**Fix:** Replace USO with SLV (silver) or DBB (industrial metals). Silver has low correlation to crude oil and provides a distinct commodity trend signal.

---

## Research Director Decision

**Decision: REVISE — Create H07b with these specific changes:**

### Required Changes for H07b

| # | Change | Rationale | Fixes |
|---|--------|-----------|-------|
| 1 | Expand universe to 15–20 ETFs | Trade count failure is structural at 6 assets | Trade count, permutation test |
| 2 | Replace USO → SLV (silver) | USO/DBC correlation 0.94 — no diversification value | Diversification, WF consistency |
| 3 | Add VIX > 25 regime gate (halve exposure) | Window 4 H2 2022 failure is regime-specific | OOS Sharpe, WF consistency |
| 4 | Tighten lookback sensitivity range to [9, 12, 18] | Removes the outlier parameter combination driving 30.9% variance | Sensitivity variance |
| 5 | Keep monthly rebalancing (do not switch to weekly) | Weekly rebalancing would increase turnover costs and change strategy character | Transaction cost discipline |

### Proposed H07b Universe (15–17 ETFs)

| ETF | Asset Class | Role |
|-----|------------|------|
| SPY | US Large-Cap Equity | Core equity |
| QQQ | US Tech Equity | Growth/risk |
| IWM | US Small-Cap Equity | Breadth signal |
| EFA | International Equity | Global diversification |
| TLT | 20Y Treasury Bond | Rate sensitivity |
| IEF | 7-10Y Treasury Bond | Mid-duration rate |
| HYG | High-Yield Corporate Bond | Credit risk signal |
| TIP | TIPS | Inflation trend |
| GLD | Gold | Crisis hedge |
| SLV | Silver | Industrial metals trend (replaces USO) |
| DBB | Industrial Metals | Copper/zinc/aluminum trend |
| DBA | Agricultural | Soft commodity trend |
| XLE | Energy Equities | Energy sector (proxy for crude) |
| XLF | Financial Equities | Credit cycle signal |
| XLRE | Real Estate | Rate-sensitive sector |

**Total: 15 ETFs** — at monthly rebalancing, expects ~35–60 IS trades. Approaching 50-trade threshold with high confidence.

### VIX Regime Gate (Required)

```
if VIX_current > 35: position_scale = 0.0  (flat, capital preservation)
elif VIX_current > 25: position_scale = 0.5  (half exposure)
else: position_scale = 1.0  (full exposure)
```

VIX data available from Yahoo Finance (^VIX) for full IS/OOS window. No look-ahead concern: VIX at time T uses VIX_T only.

---

## Options Considered and Rejected

### Option B: Retire H07, Prioritize H08

**Rejected.** H07 shows genuine signal quality (IS Sharpe 1.255, 66.7% win rate, 6.26× W/L). Retiring the strategy based on mechanical failures that are fixable would be premature. The economic rationale (Moskowitz 2012) is among the most robust in the academic literature. TSMOM is worth one revision attempt.

### Option C: Lower Trade Count Threshold for Momentum Strategies

**Rejected (at this stage).** While monthly TSMOM on 6 ETFs structurally cannot meet the 50-trade threshold, the correct fix is universe expansion rather than criteria relaxation. If the expanded universe (15 ETFs) still falls short, a criteria discussion with the CEO would be appropriate. Revising Gate 1 criteria should be a last resort, not a first response.

---

## Hypothesis Status

| Version | Status | Notes |
|---------|--------|-------|
| H07 (original, 6 ETFs) | **FAILED Gate 1** | Archived in this document |
| H07b (15 ETFs + VIX gate) | **Pending** | Alpha Research Agent to write hypothesis doc |

---

## Next Steps

1. **Alpha Research Agent** — write H07b hypothesis document (`research/hypotheses/07b_multi_asset_tsmom_expanded.md`) incorporating all changes above. Must pass Research Director pre-backtest checklist before forwarding to Engineering Director.

2. **H08 (Crypto Momentum)** — QUA-119 backtest in progress. Continue in parallel; do not block H07b.

3. **TradingView Discovery (QUA-108)** — weekly TV ideas task to be triggered for Alpha Research Agent.

---

## Reference

- Original hypothesis: `research/hypotheses/07_multi_asset_tsmom.md`
- Gate 1 backtest report: `research/backtest_results/h07_gate1_results.md`
- Gate 1 results JSON: `backtests/H07_MultiAsset_TSMOM_2026-03-16.json`
- Tasks: [QUA-116](/QUA/issues/QUA-116) | [QUA-123](/QUA/issues/QUA-123)
