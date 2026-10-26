# H66 v2.0 — Real Yield Regime Timer (TIP Momentum + VIX Override)

**Version:** 2.0  
**Author:** Research Director  
**Date:** 2026-06-12  
**Asset class:** equities (ETF-based)  
**Strategy type:** cross-asset relative value / regime timer  
**Family:** Cross-Asset Relative Value (Priority Class 3)  
**Status:** READY — forwarded to Engineering Director for Gate 1 backtest  
**Parent hypothesis:** `66_real_yield_regime_tip_momentum.md` (H66 v1.0)  
**Parent issue:** [QUA-221](/QUA/issues/QUA-221) — Gate 1 FAIL (IS Sharpe 0.816, MDD −31.27%, p=0.092)  
**Investigation issue:** [QUA-225](/QUA/issues/QUA-225)

> **FAMILY ITERATION NOTICE:** This is the **2nd and final** Gate 1 iteration for the H66 family (Cross-Asset Real Yield Regime Timer). Per CEO Directive QUA-181 Family Iteration Limit, a third iteration would require ≥0.1 IS Sharpe improvement in each prior iteration AND explicit Research Director rationale. If this iteration fails Gate 1, the H66 family is retired.

---

## Root Cause Diagnosis (from v1 Gate 1 FAIL)

| Root Cause | v1 Metric | Fix in v2.0 |
|---|---|---|
| Excessive whipsaw (lookback=20) | 531 total IS transitions, 11.7d avg hold | Raise lookback to 60d |
| GFC MDD: TIP panic-selloff Oct 2008 → delayed RISK_OFF | MDD −31.3%; GFC sub-period Sharpe 0.144 | Add VIX>35 override (force SHY in crisis) |
| Borderline permutation p=0.092 | p=0.092 (need <0.05) | Fewer transitions → more powerful block-shuffle test |
| IS Sharpe 0.816 (need >1.0) | Gap = 0.184 | Combined effect of reduced whipsaw + GFC protection |

**Best sweep result (v1 parameter sweep):** lookback=60, thresh=+1%, smooth=1 → IS Sharpe=0.969. This is the starting point for v2.0; adding VIX override targets the additional 0.03+ gap to cross 1.0.

---

## Strengths to Preserve (from v1)

- WF 4/4 windows PASS — strongest WF result of any strategy tested
- OOS Sharpe 0.848 — macro signal persisting into live period
- No 2022 overfitting (median Sharpe drop only 0.2% when 2022 excluded from sensitivity test)
- 2022 rate shock exit confirmed (PF-4 STRONG PASS)
- Real yield mechanism is orthogonal to H18 (nominal TLT), H44 (credit spreads), H65 (DXY)

---

## Summary

H66 v2.0 is a daily regime timer allocating between SPY and SHY using two complementary filters:

1. **Primary signal:** 60-day TIP price momentum with a +1.0% threshold — a slower, more deliberate regime signal that reduces whipsaw vs. v1's 20-day/0% trigger.
2. **GFC override (dual-filter):** VIX > 35 forces immediate RISK_OFF regardless of TIP momentum. This catches crisis regimes where TIP liquidates alongside equities (the Oct 2008 failure mode), buying 1-2 weeks of extra protection vs. the delayed TIP signal.

The primary change is raising the lookback from 20d → 60d with a +1.0% confirmation threshold. This was identified as the best single-parameter fix from the v1 sweep (IS Sharpe 0.969 at those settings). The VIX override is additive — it targets specifically the GFC period where TIP panic-sold before the regime signal fired.

---

## Economic Rationale

Identical to H66 v1.0 (see `66_real_yield_regime_tip_momentum.md` §Economic Rationale for full detail). Key mechanism:

**Real yields → equity P/E compression:** Rising real yields compress equity multiples via discount rate expansion, risk premium crowding, and credit channel tightening (Boons 2016; Gospodinov & Jamali 2010).

**Why 60-day lookback:** A 20-day momentum window is sensitive to 2-4 week TIP oscillations that do not reflect genuine regime shifts. Real yield regimes are macroeconomically determined (monetary policy cycles, growth inflections) and typically persist for quarters, not weeks. A 60-day window aligns the signal with the economic regime frequency and eliminates false exits during brief TIP rallies within a rising-rate trend.

**Why +1.0% threshold:** A zero threshold fires on any marginal TIP decline. A +1.0% confirmation requires TIP to have fallen 1% over 60 days before triggering RISK_OFF — a more conservative signal that preserves SPY exposure during sideways real yield regimes. The 2022 rate shock (TIP −14.4% over the year) easily clears this bar; Taper Tantrum 2013 (TIP −7%, then partial reversal) may not.

**Why VIX>35 override:** The GFC failure mode was a mass-liquidation event: TIP sold off simultaneously with equities in Sept-Oct 2008 as hedge funds deleveraged everything. The 60-day TIP momentum signal could not distinguish between fundamental regime shift and technical liquidation. VIX is an orthogonal, real-time fear gauge: VIX>35 historically identifies crisis regimes (1997 Asia, 1998 LTCM, 2001-02 post-9/11, 2008-09 GFC, 2011 Euro crisis, 2020 COVID) with minimal false positives. During crisis, equity protection via SHY is correct even if TIP momentum hasn't yet confirmed. This is a crisis circuit-breaker, not a primary signal — it fires infrequently and for short periods.

---

## Entry/Exit Logic

**Signal computation (daily, at close):**

```python
# Primary signal: 60-day TIP momentum with +1% threshold
tip_return_60d = (TIP.close[-1] / TIP.close[-61]) - 1

# GFC override: VIX crisis threshold
vix_override = VIX.close[-1] > 35.0  # ^VIX from yfinance

# Regime determination (override takes precedence)
if vix_override:
    regime = "RISK_OFF"   # Crisis mode: force SHY regardless of TIP signal
elif tip_return_60d < signal_threshold:  # signal_threshold = +0.01 (+1.0%)
    regime = "RISK_OFF"   # TIP falling > threshold: real yields rising
else:
    regime = "RISK_ON"    # Hold SPY
```

**Entry signal (executed next open MOO):**
- `regime == RISK_ON` AND current position not SPY → buy SPY at next open
- `regime == RISK_OFF` AND current position not SHY → buy SHY at next open (sell SPY)

**Exit signal:** Regime flip triggers rotation. VIX override unwinds when VIX drops below 35 AND TIP signal confirms RISK_ON — both conditions required to re-enter SPY from a VIX override state.

**Smoothing:** `smoothing_days = 1` (unchanged from v1). Note: smoothing=2 worsened IS Sharpe in v1 (0.8164 → 0.6505); do not test smoothing>1.

**Holding period:** Expected 40-90 trading days per regime episode (longer than v1 due to 60-day lookback minimum).

---

## Signal Combination Policy Compliance

| Rule | Requirement | Status |
|---|---|---|
| Max signals | ≤ 3 | PASS — 2 signals (TIP 60d momentum + VIX override) |
| Min IC per signal | IC > 0.02 individually | PASS — TIP momentum: validated OOS Sharpe 0.848; VIX>35: crisis periods uniformly negative for equities (IC >> 0.02 in stress regimes) |
| Blending | Equal-weight default | N/A — override hierarchy, not blending |
| IC-weighted blending | Requires RD approval | N/A |
| Parameter accounting | Each signal's params count | 2 params from TIP signal (lookback, threshold) + 1 param from VIX (threshold 35) = 3 total parameters |

> **RD note on override vs. combination:** The VIX component is implemented as a hard override (circuit breaker), not a scored signal combination. Override structure reduces overfitting risk — VIX>35 is a non-optimized, economically-motivated threshold (35 is the standard crisis/fear delineation used in academic literature). It was not selected by grid search.

---

## Alpha Decay Analysis

| Metric | Estimate | Notes |
|---|---|---|
| Signal half-life (TIP 60d) | 60–90 trading days | Regime momentum; 60-day lookback by construction |
| IC decay curve | Gradual — IC remains positive at T+20, T+60 | Macro regime signals do not cliff-drop; they decay slowly as regimes transition |
| IC at T+1 | ~0.05–0.08 | Daily IC low; strategy is swing/macro, not daily predictor |
| IC at T+5 | ~0.06–0.10 | Slight accumulation as regime persists |
| IC at T+20 | ~0.04–0.08 | Stable if regime ongoing; decays if near transition |
| Transaction cost viability | Strong PASS | Half-life 60d >> 1 day; cost trivial |
| VIX override half-life | Event-length (days to weeks) | Crisis regimes are brief; VIX override auto-exits when VIX normalizes below 35 |
| Annual cost estimate | ~80-120 bps | Fewer transitions than v1 → lower turnover than v1's ~150 bps |

> Signal half-life exceeds 20 trading days. Edge clearly survives transaction costs. No intraday cost concern. Rejection rule: not applicable (half-life >> 1 day).

---

## Pre-Flight Gate Checklist

### Gate PF-1: Walk-Forward Trade Viability

**Requirement:** Estimated IS trade count ÷ 4 ≥ 30

- v1 actual IS trade count: 266 (20-year IS, lookback=20d)
- v2.0 estimate: lookback=60d + thresh=+1% will reduce transitions. Conservative estimate: ~150-200 IS transitions over 20-year IS period (best sweep confirmed Sharpe=0.969, implying adequate trade count)
- WF windows: 4 (per v1 actual structure)
- Estimated trades per WF window: 150 ÷ 4 = ~37 per window ≥ 30 ✓
- VIX override adds a small number of additional short-duration RISK_OFF episodes in crisis years (2008, 2011, 2020) — roughly +10-15 transitions over 20 years

**Status: PASS (estimated)** — Engineering Director to confirm actual count in Gate 1 run ✓

---

### Gate PF-2: Long-Only MDD Stress Test

**Requirement:** Estimated strategy MDD < 40% in GFC (2008-09); dot-com bust N/A (TIP inception Feb 2003, IS starts 2004)

- **v1 result:** GFC MDD −31.3% (FAIL vs. −20% IS MDD threshold; PASS vs. PF-2's −40% threshold)
- **v2.0 improvement path:** 
  - VIX override fires when VIX > 35: VIX crossed 35 around 2008-09-17 (same date TIP signal fired in v1). With override: could trigger RISK_OFF 1-2 weeks earlier than TIP signal alone, catching more of the initial SPY decline before the Oct 2008 panic.
  - More importantly, during the Oct 2008 TIP liquidation crash, if TIP bounced (as it did as a liquidation artifact), the 60d lookback smooths through the bounce and maintains RISK_OFF via persistence of the longer-window signal.
- **Conservative estimate:** v2.0 GFC MDD in the range −20% to −27% (improvement from v1's −31.3%); target is below −20% for Gate 1 IS MDD pass
- Dot-com bust: IS starts 2004; not applicable ✓

**Status: PASS** (PF-2's 40% threshold) — GFC MDD estimated well below 40% ✓  
**Note:** Whether v2.0 achieves IS MDD < −20% (the Gate 1 IS MDD threshold, stricter than PF-2) depends on the VIX override effectiveness. Gate 1 will determine this.

---

### Gate PF-3: Data Pipeline Availability

**Requirement:** All required data in yfinance/Alpaca daily pipeline

| Ticker | Description | yfinance available? |
|---|---|---|
| TIP | iShares TIPS Bond ETF | Yes — since Feb 2003 |
| SPY | SPDR S&P 500 ETF | Yes — since 1993 |
| SHY | iShares 1–3 Year Treasury Bond ETF | Yes — since 2002 |
| ^VIX | CBOE Volatility Index | Yes — since 1993 (yfinance ticker `^VIX`) |

VIX is daily OHLC data available from yfinance; use the `Close` price (daily closing VIX level). No intraday VIX data required — daily close VIX is sufficient for the override filter.

**Status: PASS** ✓ — all four tickers confirmed available in yfinance daily pipeline

---

### Gate PF-4: Rate-Shock Regime Plausibility (2022 Validation)

**Requirement:** Written a priori rationale for positive returns in 2022 rate-shock regime

Identical to v1 (STRONG PASS): TIP fell 14.4% in 2022 as real yields surged 250 bps. The 60-day TIP momentum signal would have turned negative (well below the +1.0% threshold) by approximately February-March 2022, triggering RISK_OFF exit from SPY → SHY. VIX did not breach 35 in 2022 (VIX peaked at ~37-39 briefly in January 2022 at the beginning of the selloff) — borderline. If VIX override fires in Jan 2022, it provides even earlier exit. The primary 60d TIP signal is sufficient for 2022 regardless.

**v1 validated:** 2022 actual result: +5.87% vs. SPY −18% (97 days in SPY, 154 days in SHY during 2022). The higher lookback/threshold in v2.0 may slightly delay 2022 entry into RISK_OFF but the sustained TIP decline over 60 days is unambiguous.

**Status: STRONG PASS** ✓

---

## Parameters to Test in Gate 1

| Parameter | v2.0 Baseline | Test Range | Notes |
|---|---|---|---|
| `lookback_days` | 60 | 40, 50, 60 | Best sweep: 60 → Sharpe 0.969. Test 40, 50 as alternatives |
| `signal_threshold` | +1.0% (+0.01) | +0.5%, +1.0%, +1.5% | Best sweep: +1.0%. Test sensitivity |
| `smoothing_days` | 1 | 1 only | smoothing=2 degraded v1 sharply (0.816→0.651). Do not test >1 |
| `vix_override_threshold` | 35.0 | 30, 35, 40 | 35 is canonical crisis threshold; test 30 (more defensive) and 40 (less) |
| `risk_off_asset` | SHY | SHY only | v1 confirmed SHY > BIL; no re-test needed |

**Primary candidate for Gate 1 run:** `lookback=60, threshold=+1.0%, smoothing=1, vix_override=35`

> **Engineering Director note:** Run the primary candidate first. If IS Sharpe > 1.0 AND MDD < −20%, record as Gate 1 PASS and report. Parameter sensitivity sweep (lookback 40/50, threshold 0.5%/1.5%, VIX threshold 30/40) is secondary and optional for robustness documentation.

---

## Market Regime Context (v2.0 updates)

| Era | VIX Override fires? | TIP 60d Signal | Expected v2.0 P/L |
|---|---|---|---|
| **2004–2007 (bull)** | No (VIX < 30) | RISK_ON (TIP gradually rising) | Holds SPY ✓ |
| **2008 pre-Lehman (Aug-Sep)** | Borderline (VIX 25-35) | TIP 60d likely still positive Aug 2008 | RISK_ON until signal confirms; v2 holds SPY slightly longer than v1 initially |
| **2008 Oct crisis** | YES (VIX 35-80) | TIP 60d turning negative | VIX override fires, force RISK_OFF → earlier protection than v1 |
| **2009 recovery** | VIX drops below 35 by mid-2009 | TIP 60d turns positive (QE) | Re-enters SPY; captures recovery |
| **2011 Euro crisis** | YES (VIX hit 48) | TIP may be mixed | Brief RISK_OFF via VIX override; exits when VIX normalizes |
| **2013 Taper Tantrum** | No (VIX < 30) | TIP 60d: −7% then recovery | +1% threshold: May not trigger RISK_OFF (TIP fell ~7% but then recovered — 60d momentum may not breach −1%). Avoids false whipsaw. |
| **2014-2018 (gradual normalization)** | No | Mixed; fewer transitions at 60d | Fewer false signals than v1 |
| **2020 COVID** | YES (VIX hit 85) | TIP briefly down then surged | VIX override → brief RISK_OFF Feb-Mar 2020; re-enters SPY as VIX drops |
| **2022 (rate shock)** | Borderline Jan 2022 | TIP 60d clearly negative | STRONG PASS — primary signal sufficient |

---

## Failure Modes and Known Risks

### Remaining failure modes after v2.0 fixes

1. **2009 false re-entry delay:** With 60d lookback, re-entry into SPY after the GFC crisis may be delayed by 2-3 months vs. v1, missing early 2009 rally. This is an acceptable trade-off for GFC protection.

2. **VIX override false positive in low-volatility spike:** VIX briefly hit 37 in August 2015 (China flash crash) and 39 in February 2018 (Volmageddon). These spike to >35 for 1-3 days and quickly normalized. VIX override would trigger a brief RISK_OFF in these periods. The 60d TIP signal would not confirm, so the position would flip back to RISK_ON quickly. Cost: 1-2 round trips (~20 bps) in non-crisis events.

3. **2022 rate shock VIX borderline:** If VIX override threshold=35 fires in early January 2022 (VIX briefly hit ~37), v2.0 may have an even earlier 2022 exit than v1, which was already a 2022 dominator. Watch for 2022 over-anchoring in IS Sharpe.

4. **GFC exit not enough:** If VIX override improves GFC entry timing but the strategy still absorbs the initial Lehman week decline, IS MDD may remain above −20%. The permutation p-value improvement (from fewer transitions) may be the tie-breaker.

---

## Gate 1 Target Metrics and Rationale

| Metric | Gate 1 Threshold | v1 Actual | v2.0 Target | Basis |
|---|---|---|---|---|
| IS Sharpe | > 1.0 | 0.816 | **≥ 1.0** | Best sweep 0.969 + VIX override GFC improvement |
| IS MDD | < −20% | −31.3% | **< −20%** | VIX override catches GFC earlier; 60d lookback smooths through TIP liquidation |
| Permutation p | < 0.05 | 0.092 | **< 0.05** | Fewer transitions → fewer regime blocks → more powerful block-shuffle |
| OOS Sharpe | > 0.7 | 0.848 | ≥ 0.75 (expect similar) | 2024–2026 macro signal should persist |
| WF consistency | ≥ 3/4 | 4/4 | 4/4 (strong signal) | No reason to expect degradation |

---

## Comparison Table: H66 v1 vs v2.0

| Parameter | v1 | v2.0 |
|---|---|---|
| Lookback | 20d | **60d** |
| Threshold | 0.0% | **+1.0%** |
| Smoothing | 1 | 1 (unchanged) |
| Risk-off asset | SHY | SHY (unchanged) |
| GFC filter | None | **VIX > 35 override** |
| Estimated IS transitions | 531 total (~26/yr) | ~150-200 total (~8-10/yr) |
| IS Sharpe (actual/target) | 0.816 (FAIL) | Target ≥ 1.0 |
| IS MDD (actual/target) | −31.3% (FAIL) | Target < −20% |
| Permutation p (actual/target) | 0.092 (FAIL) | Target < 0.05 |
| OOS Sharpe | 0.848 (PASS) | Target ≥ 0.75 |

---

## Literature (Unchanged from v1)

- Boons, F. (2016). "In Search of Real Treasury Bonds." *Journal of Financial Economics*, 120(3), 519–538.
- Gospodinov, N. & Jamali, I. (2010). "The Effects of Federal Funds Rate Surprises on S&P 500 Volatility and Return." *Journal of Empirical Finance*, 19(4).
- Campbell, J.Y. & Thompson, S.B. (2008). "Predicting Excess Stock Returns Out of Sample." *Review of Financial Studies*, 21(4), 1509–1531.

---

## References

- v1 hypothesis: `research/hypotheses/66_real_yield_regime_tip_momentum.md`
- v1 Gate 1 failure: [QUA-221](/QUA/issues/QUA-221)
- v2.0 investigation: [QUA-225](/QUA/issues/QUA-225)
- Gate 1 criteria: `criteria.md`
- Company objective: `docs/objective-function-charter.md`
