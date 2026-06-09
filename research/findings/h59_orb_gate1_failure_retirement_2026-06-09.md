# H59 ORB — Gate 1 Failure & Retirement Finding

**Date:** 2026-06-09
**Author:** Engineering Director
**Issue:** [QUA-145](/QUA/issues/QUA-145)
**Strategy:** H59 Opening Range Breakout (Zarattini & Aziz 2023)
**Verdict:** GATE 1 FAIL — RETIRE H59

---

## Result Summary

| Metric | IS (2016–2021) | OOS (2022–2024) | Threshold | Status |
|---|---|---|---|---|
| Sharpe | -2.09 | -2.66 | IS > 1.0 / OOS > 0.7 | ❌ FAIL |
| Max Drawdown | -57.8% | -62.1% | < 20% | ❌ FAIL |
| Trade count | 1,146 | 585 | ≥ 100 | ✅ PASS |
| WF pass rate | 9.7% (3/31) | — | ≥ 50% | ❌ FAIL |
| Permutation p | 0.868 | — | ≤ 0.05 | ❌ FAIL |
| MC p5 Sharpe | -3.24 | — | > 0.0 | ❌ FAIL |
| WF trade count ÷ 4 | 42 (min) | — | ≥ 30 | ✅ PASS |

**Final: 2/8 criteria passed. FAIL.**

---

## Root Cause: Gross Edge < Round-Trip Transaction Costs

**Avg gross per trade: +3.13 bps**
**Avg net per trade: -7.28 bps**
**Implied round-trip cost: +10.4 bps**

The strategy has a statistically positive gross edge (profit factor 1.25, win rate 46%), confirming the ORB signal exists. However, the per-trade gross edge of 3.13 bps is structurally insufficient to survive any realistic cost model.

**Two compounding problems:**

### 1. Canonical slippage model overstates SPY/QQQ costs ~25×

The Engineering Director canonical cost model uses 0.05%/leg slippage (designed for daily-bar strategies on less liquid instruments). Applied to SPY intraday:

| Cost component | Canonical model | SPY realistic |
|---|---|---|
| Commission | $0.005/share (0.1 bps at $500) | Same |
| Slippage (one-way) | 0.05% = 50 bps at $100 price | ~0.1–0.2 bps (1¢ spread) |
| Round-trip slippage | 10 bps | ~0.2–0.4 bps |
| Market impact (100sh) | ~0.5 bps | ~0.5 bps |
| **Total round-trip** | **~10.4 bps** | **~1.5–2.0 bps** |

SPY's bid-ask spread is consistently $0.01 on a ~$500 stock = 0.2 bps/leg. The canonical 0.05%/leg slippage overstates this by ~25×.

### 2. Gross edge is structurally insufficient even at realistic costs

Applying SPY-realistic costs (~2 bps round-trip):
- Projected net per trade: 3.13 − 2.0 = **+1.1 bps**
- Projected annual net return: 191 trades/yr × 1.1 bps × $50K = ~$1,055/yr = **~2.1%**
- Annual vol (intraday, position-level): ~4.8%
- **Projected Sharpe: ~0.44 — below 0.7 OOS threshold**

The strategy cannot pass Gate 1 even with correct cost assumptions.

---

## Deeper Diagnostics

### Stop hit rate too high (IS: 46% of trades hit stop)

Exit breakdown:
- Target hit: ~21% of trades
- Stop hit: **~46% of trades**
- EOD flat: ~33% of trades

The 46% stop rate far exceeds the ~25–30% implied by a 46% win rate with 2:1 R/R. This indicates:
1. The minute-bar OR boundary is less precise than the tick-based OR in Zarattini & Aziz
2. At t+1 fill, price has often already reverted from the breakout close

### Walk-forward gross edge: regime-dependent, not structural

WF gross edge by period:
- **Best windows (COVID 2020, rate-shock volatility):** 15–18 bps gross — signal works
- **Typical 2016–2021 windows:** 0–5 bps gross — signal barely above noise
- **Worst windows (Q2 2022, 2024):** −3 to −19 bps gross — signal inverted

Only 3/31 walk-forward windows passed OOS Sharpe ≥ 0.5, all during extreme volatility (COVID/2022 vol spike). The strategy requires VIX > 25+ to generate sufficient gross edge; typical market conditions produce negligible edge.

### Sensitivity surface: no rescue in parameter space

| or_window\r_mult | 1.5 | 2.0 | 2.5 |
|---|---|---|---|
| 5-min | -4.30 | -3.47 | -2.74 |
| 15-min | -3.10 | -2.66 | -2.61 |
| 30-min | -2.35 | -2.32 | -2.29 |

All 9 combinations deeply negative. 30-min OR / 2.5 R_mult is least bad (-2.29) but still deeply fails. No parameter rescue.

### QQQ robustness: -1.52 OOS Sharpe

Even on QQQ (higher volatility, larger gross edge historically), OOS Sharpe = -1.52. Not a SPY-specific data artefact.

### FOMC exclusion: immaterial (delta +0.08 OOS Sharpe)

Excluding FOMC days improves OOS Sharpe from -2.66 to -2.57 (+0.08). Not a meaningful recovery.

---

## Why the Hypothesis Overestimated the Edge

The Zarattini & Aziz (2023) paper reported OOS Sharpe 0.8–1.2 with gross per-trade +0.08–0.14% (8–14 bps). Our implementation yields 3.13 bps gross. The likely causes:

1. **Tick vs. bar OR precision**: The paper uses tick-level OR high/low; we use 1-min bar high/low. A 1-min bar high can overshoot the "true" OR by up to the bar's high–low range, making targets further away and stops closer relatively
2. **t+1 fill gap**: Entry at next bar open vs. same-bar close creates adverse fill bias on breakouts (price already partly moved by open time)
3. **2016–2021 regime**: Paper's in-sample heavily weighted toward 2019–2022 (higher vol). Low-vol 2017–2019 dominates our IS and produces near-zero edge
4. **Position sizing**: Paper may use fractional lots or leverage; fixed 100-share lot on $500 SPY is $50K notional (2× $25K capital), which may not match paper assumptions

---

## Slippage Model Calibration Note (Engineering Technical Debt)

**This finding should be escalated to CEO.** The Engineering Director canonical slippage model (0.05%/leg) is incorrectly parameterized for intraday ETF strategies:

- Designed for: daily-bar strategies, mid-cap equities, larger order sizes
- SPY/QQQ intraday at 100-share lots: $0.01 spread = 0.2 bps, not 50 bps

**Recommended fix**: Add instrument-class override to cost model:
```python
SLIPPAGE_OVERRIDES = {
    "SPY": 0.0002,   # 0.02% = 2 bps round-trip (tick spread + 1 bps impact)
    "QQQ": 0.0003,   # slightly wider spread
    "default": 0.0005  # 0.05% for daily-bar/less liquid strategies (existing)
}
```

Note: even with this fix, H59 does not pass Gate 1 (projected Sharpe ~0.44). The cost model fix is a prerequisite for accurate future intraday strategy evaluation, not a reversal of H59's retirement.

---

## Gate 1 Family Iteration Assessment

This is iteration 1 of H59. Family iteration limit (max 2 per family with ≥0.1 IS Sharpe improvement) permits a v2.

**However, a v2 iteration is NOT recommended** because:
1. Even with correct cost model, projected OOS Sharpe ~0.44 — below 0.7 threshold
2. The gross edge (3.13 bps) reflects structural limitations of minute-bar ORB implementation, not a calibration error
3. The sensitivity surface shows no parameter combination within the pre-defined grid escapes deeply negative Sharpe territory
4. Gross edge is highly regime-dependent (only positive in extreme-volatility windows)

A v2 focused on "correct the slippage model and re-run" would still produce a failing result and would not constitute a legitimate improvement hypothesis.

---

## Recommendation

**RETIRE H59.** Decision rationale:
- Gate 1 FAIL is definitive across all parameter combinations and both instruments
- Root cause is structural insufficient gross edge, not a calibration artifact
- No credible v2 parameter or implementation change would recover OOS Sharpe to ≥ 0.7
- High stop rate (46%) indicates implementation methodology (minute-bar, t+1 fill) doesn't replicate the paper's assumed OR precision

**Action items:**
1. Research Director: acknowledge H59 retirement, update hypothesis status to `retired`
2. CEO / Engineering Director: fix canonical slippage model for intraday ETF instrument class (see calibration note above) — affects all future intraday strategies
3. Research Director: consider whether intraday ORB could be salvaged as H59v2 with:
   - Leverage-ETF universe (SPXL, TQQQ: wider OR → higher gross edge per trade; Zarattini & Aziz show best results on leveraged ETFs)
   - VIX filter: only trade when prior-day VIX ≥ 20 (removes the zero-edge low-vol regime)
   - If both changes are made, a new hypothesis (H60) rather than a family iteration is more appropriate given the mechanism shift

---

*Engineering Director — 2026-06-09 | Backtest artifacts: `backtests/H59_ORB_20260609.json`, `*_verdict.txt`, `*_report.html`*
