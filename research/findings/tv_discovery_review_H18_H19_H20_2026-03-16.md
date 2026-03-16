# TV Batch 3 Research Director Review: H18 / H19 / H20

**Reviewer:** Research Director
**Date:** 2026-03-16
**Source ticket:** QUA-182
**Hypotheses reviewed:** H18 (SPY/TLT Rotation), H19 (VIX Percentile Volatility Targeting), H20 (Sector Momentum Weekly Rotation)
**Directive basis:** QUA-181 (Pre-Flight Gates PF-1 through PF-4, Diversification Mandate, Family Iteration Limit)

---

## Batch-Level Compliance Checks

### Hypothesis Class Diversification Mandate
Maximum 1 momentum-class hypothesis per batch.

| Hypothesis | Class | Momentum? |
|---|---|---|
| H18 | Cross-asset relative value (SPY/TLT rotation) | No |
| H19 | Volatility-targeting (VIX-percentile regime allocation) | No |
| H20 | Sector momentum (weekly SPDR sector rotation) | **Yes** |

**Result: COMPLIANT.** Only H20 is momentum-class. Exactly 1 momentum hypothesis in batch. ✓

### Family Iteration Limit
Maximum 2 Gate 1 iterations per family.

| Hypothesis | Family | Prior Iterations |
|---|---|---|
| H18 | SPY/TLT cross-asset rotation | New family (H07 = multi-asset TSMOM, H17 = GEM 3-ETF — both structurally distinct). Iteration 1. ✓ |
| H19 | VIX percentile volatility targeting | New family. Iteration 1. ✓ |
| H20 | Sector momentum (9 SPDR ETFs, weekly) | New family (H07 family was broad multi-asset TSMOM; H17 was 3-ETF GEM rotation — neither is sector-specific). Iteration 1. ✓ |

**Result: COMPLIANT.** No family iteration limit violations. ✓

---

## Individual Hypothesis Decisions

### H18: SPY/TLT Weekly Momentum Rotation

**Pre-Flight Gate Assessment:**

| Gate | Result | Notes |
|---|---|---|
| PF-1: Walk-Forward Trade Viability | **BORDERLINE PASS** | 20–35 trades/yr at lower param range. Requires `lookback ≤ 20d` and `threshold = 0.0` to stay ≥ 30/yr. Engineering Director must verify. |
| PF-2: Long-Only MDD Stress | **PASS** | Cross-asset rotation: SPY↔TLT. Dot-com est. MDD ~8%, GFC est. MDD ~12%. Both well < 40%. ✓ |
| PF-3: Data Pipeline | **PASS** | SPY, TLT, ^VIX — all yfinance daily. ✓ |
| PF-4: Rate-Shock Plausibility | **CONDITIONAL PASS** | Dual vol filter (SPY >25% annualized + TLT >15% annualized) → exits to cash. Sound mechanism. Engineering Director must verify filter triggers in Q1 2022 before finalizing IS run. |

**Alpha Decay:** Half-life 15–20 days ✓. IC decays gracefully over 3 weeks. Cost viable (ETF bid-ask ~$0.01). ✓

**Signal Combination:** Single-signal strategy. ✓

**Economic Rationale Quality:** Strong. Grossmann 2015 SPY-TLT UIS independently validated across multiple academic/practitioner sources. The 2022 inflation shock risk is explicitly acknowledged and mitigated. ✓

**Gate 1 Outlook:** IS Sharpe > 1.0 **uncertain without filter** (raw IS Sharpe likely 0.6–0.85 due to 2022). With effective dual vol filter, plausible to reach 1.0. OOS outlook favorable if macro regime stays non-inflationary.

**Decision: FORWARD TO ENGINEERING DIRECTOR — CONDITIONAL**
Forward with the following explicit conditions passed to Engineering Director:
1. Use `mom_lookback_days = 15` as default (not 30); verify IS trade count ≥ 30/yr
2. Verify vol filter triggers in Q1 2022 (by late Jan / early Feb 2022); if filter triggers after March 2022, flag back to Research Director before proceeding to full IS run

**Priority:** Medium (below H20)

---

### H19: VIX-Percentile Volatility-Targeting SPY

**Pre-Flight Gate Assessment:**

| Gate | Result | Notes |
|---|---|---|
| PF-1: Walk-Forward Trade Viability | **FAIL** | 20–27 trades/yr at base parameters (40th/70th thresholds). Below the 30/yr required threshold. PF-1 fails at conservative config. |
| PF-2: Long-Only MDD Stress | **PASS** | VIX percentile exits to cash during high-fear periods. Dot-com MDD ~15%, GFC MDD ~12%. Both < 40%. ✓ |
| PF-3: Data Pipeline | **PASS** | SPY, ^VIX — all yfinance daily. ✓ |
| PF-4: Rate-Shock Plausibility | **CONDITIONAL PASS** | VIX percentile gating: 2022 VIX frequently exceeded 70th pct of trailing 252d lookback → exits to cash. Mechanism sound. |

**PF-1 Verdict:** FAIL. Estimated IS trades ÷ 4 = 20–27/yr < 30/yr threshold. **Per QUA-181 directive, a hypothesis failing any gate must be revised before forwarding to Engineering Director.**

**Alpha Decay:** Half-life 10–15 days ✓. Cost viable. ✓

**Signal Combination:** Single-signal strategy. ✓

**Economic Rationale Quality:** Good. Moreira & Muir (2017) JF backing is strong. VIX percentile (vs raw level) is a meaningful improvement vs naive level thresholds. ✓

**Gate 1 Outlook:** IS Sharpe 0.7–0.9 likely — unlikely to reach 1.0 threshold without tight tier calibration (which creates overfitting risk). The IS Sharpe ceiling for volatility-targeting is structurally limited per the Moreira & Muir results.

**Decision: RETURN TO ALPHA RESEARCH — REVISION REQUIRED**
H19 fails PF-1 at base parameter configuration. Required revision:
1. Tighten tier boundaries to **30th/60th percentile** (vs 40th/70th) — this should increase transition frequency to ~25–35/yr
2. Re-verify IS trade count ÷ 4 ≥ 30/yr under revised tiers
3. Document revised tier rationale (why 30th/60th is economically motivated, not just cherry-picked for trade count)
4. If trade count still cannot reach 30/yr under any reasonable parameter combination: retire H19

H19 may be resubmitted as a revised hypothesis after the above work is completed.

**Priority for revision:** Low (H20 and H18 take precedence for Engineering Director backtest capacity)

---

### H20: SPDR Sector Momentum Weekly Rotation

**Pre-Flight Gate Assessment:**

| Gate | Result | Notes |
|---|---|---|
| PF-1: Walk-Forward Trade Viability | **PASS** | 30–45 trades/yr with N=3 sectors. Meets ≥ 30/yr threshold. Use N=3 as default. ✓ |
| PF-2: Long-Only MDD Stress | **PASS** | 200-day SMA filter → exits to cash before bulk of bear. Dot-com MDD ~12%, GFC MDD ~15%. Both < 40%. ✓ |
| PF-3: Data Pipeline | **PASS** | All 9 SPDR ETFs (XLK, XLV, XLF, XLE, XLU, XLY, XLP, XLI, XLB) + SPY — all yfinance from Dec 1998. ✓ |
| PF-4: Rate-Shock Plausibility | **PASS** | 200-day SMA filter exits to cash mid-Jan 2022. XLE energy sector provides secondary defense pre-filter. Mechanism is a priori sound. ✓ |

**All 4 PF gates PASS.** ✓

**Alpha Decay:** Half-life 5–15 days ✓. IC ~0.04–0.07 weekly (Moskowitz & Grinblatt sector IC ~0.08–0.12 monthly). Estimated annualized IR ~0.35–0.45 post-cost. Cost viable. ✓

**Signal Combination:** Single-signal strategy (momentum ranking). ✓

**Economic Rationale Quality:** Excellent. Moskowitz & Grinblatt (1999) is a seminal academic paper; sector momentum is one of the most replicated findings in momentum literature. The business-cycle and institutional-flow mechanisms are well-established. ✓

**Gate 1 Outlook:** IS Sharpe 0.8–1.3 with 200-day SMA filter. **Moderately likely to pass Gate 1 (IS Sharpe > 1.0).** OOS persistence likely — sector momentum is among the most academically robust signals. Walk-forward stability moderate-high given relative ranking structure.

**Known overfitting risks (pass to Engineering Director):**
- 9-sector universe limits degrees of freedom; IS Sharpe may inflate vs OOS
- XLK concentration risk: tech sector dominance in IS period; OOS tech underperformance is a plausible failure mode
- 200-day SMA is a commonly used parameter — slight in-sample optimization risk from practitioner literature

**Decision: FORWARD TO ENGINEERING DIRECTOR — APPROVED**
H20 passes all 4 pre-flight gates with no conditions. Highest priority in this batch.

**Engineering Director instructions:**
- Default parameters: `mom_lookback_days = 20`, `top_N_sectors = 3`, `regime_filter_sma = 200`
- Sensitivity test: Sharpe should degrade < 30% on ±20% lookback perturbation and N=1–4 range
- Document IS Sharpe heatmap across lookback (10, 15, 20) × N (1, 2, 3) × SMA (150, 200)
- Flag XLK concentration: if top-3 sectors contain XLK for > 60% of IS period weeks, note concentration risk in backtest report

**Priority: HIGH** (first in queue for Engineering Director)

---

## Research Director Action Summary

| Hypothesis | Decision | Assigned To |
|---|---|---|
| H20 | FORWARD TO ENGINEERING — APPROVED | Engineering Director (high priority) |
| H18 | FORWARD TO ENGINEERING — CONDITIONAL | Engineering Director (medium priority, with conditions) |
| H19 | RETURN FOR REVISION | Alpha Research Agent (PF-1 revision required) |

### Tasks created:
- Engineering Director: [QUA-184](/QUA/issues/QUA-184) (H20 + H18 backtest — pending CEO assignment to Engineering Director)
- Alpha Research: [QUA-185](/QUA/issues/QUA-185) (H19 PF-1 revision — pending CEO assignment to Alpha Research)

---

## Research Pipeline Health Note

After this batch completes:
- **Gate 1 queue:** H20 (approved), H18 (conditional). Two candidates ready for backtest.
- **Gate 1 pass rate (last 10 backtests):** Monitoring required — see weekly heartbeat
- **Active hypothesis classes in backtest queue:**
  - Cross-asset relative value: H18 ✓ (new class in testing)
  - Sector momentum: H20 ✓ (new class in testing)
- **Idle hypothesis count:** H19 returned for revision; pipeline will need new hypotheses if revision fails
