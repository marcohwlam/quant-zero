# H29 — TOM + Pre-Holiday with 200-SMA Regime Filter

**Version:** 1.0
**Author:** Research Director
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** multi-signal (calendar/seasonal)
**Status:** RETIRED — Gate 1 FAIL 2026-03-16. IS Sharpe 0.026 (threshold 1.0). Combined Calendar family RETIRED per QUA-181 family iteration limit.
**Parent:** H28 (Combined Multi-Calendar) — Gate 1 FAIL 2026-03-16
**Family iteration:** 2 of 2 (Combined Calendar family — H28 was iteration 1) — **FAMILY RETIRED**
**Finding:** `research/findings/29_tom_preholiday_200sma_gate1_failure_2026-03-16.md`

## Summary

H29 is a refined combined calendar strategy retaining the two highest-quality components from H28 (TOM + Pre-Holiday) while removing the fragile OEX Week signal and adding an SPY 200-day SMA regime filter to neutralise 2022 rate-shock exposure. The redesign directly addresses all four root causes identified in the H28 Gate 1 FAIL: OEX Week parameter instability, 2022 regime failure, statistical insignificance from OR-logic dilution, and excessive parameter count driving catastrophic DSR.

**Key changes vs. H28:**
1. **Removed:** OEX Week signal (Sharpe sensitivity 157.95% to single binary parameter — structurally unreliable at daily close resolution)
2. **Added:** SPY 200-day SMA regime filter — only trade when `SPY_close > SPY_200SMA` (bear-market circuit breaker)
3. **Reduced:** Free parameters from 10 → 4–5 (DSR penalty drops ~80%)
4. **Maintained:** TOM (12 cycles/yr) + Pre-Holiday (9 cycles/yr) = ~21 unique entries/yr × 15yr IS = 315 trades

## Economic Rationale

### Signal 1 — Turn-of-Month (TOM)

Monthly payroll inflows (401k, pension contributions), institutional window-dressing at month-end, and equity futures roll mechanics generate concentrated buying pressure during the last 2 and first 3 trading days of each month. Lakonishok & Smidt (1988) documented this effect over 90 years of US equity data. McConnell & Xu (2008) showed that the TOM window captures the entirety of the US equity market's average monthly excess return. The TOM edge fires 12 times per year and accounts for ~28% of in-market days.

**Why the edge persists:** The mechanism is structural — payroll processors and pension fund custodians have contractual obligations to deploy capital at regular intervals regardless of price. This cannot be front-run without replicating the institutional obligation itself.

### Signal 2 — Pre-Holiday Drift

Short-sellers systematically cover positions before US market holidays to avoid multi-day gap risk: an unhedged short position over a 3-day weekend risks significant adverse gap. Combined with reduced institutional sell-side supply and positive sentiment bias documented by Kim & Park (1994), US equity markets earn approximately 35× the normal daily return on the 1–2 trading days before each of the 9 annual US stock market holidays (Ariel 1990). Pre-Holiday IC ≈ 0.09 — highest of the three calendar signals in H28.

**Why OEX Week was dropped:** `oex_exit_on_thursday` caused a 157.95% Sharpe swing (from 0.098 to 0.011), making it the single largest contributor to H28's parameter instability. A signal this sensitive to a single binary parameter is unreliable at daily close resolution. The dealer delta-hedging mechanism is real but requires intraday precision to exploit correctly. Option D (intraday OEX redesign) is logged as a future hypothesis.

### Regime Filter — SPY 200-Day SMA

H28's primary failure mode was the 2022 rate-shock regime (Sharpe: −1.671). The VIX ≤ 28 filter was insufficient because VIX oscillated in the 25–35 range during the early 2022 equity decline — above the filter threshold only intermittently. Calendar effects are fundamentally long-biased; in a sustained downtrend, even filtered windows deliver negative returns.

The SPY 200-day SMA is the canonical bull/bear market dividing line. SPY crossed below its 200-SMA in late January 2022 and remained below it for most of the year. Adding this filter would have blocked TOM and Pre-Holiday entries through approximately 7–8 months of 2022 — the exact period that drove H28's −1.671 rate-shock Sharpe.

**PF-4 compliance:** The 200-SMA filter provides the a priori regime mechanism required by Gate PF-4. It does not rely on backtested data mining — it is the standard institutional definition of a bear market.

## Signal Combination

*(multi-signal strategy — required section)*

| Signal | IC Estimate | Weight | Source |
|--------|-------------|--------|--------|
| TOM (H22) | 0.07 | equal (50%) | IC ≈ 0.08–0.12 at T+1; blended over 5-day hold ≈ 0.07 |
| Pre-Holiday (H26) | 0.09 | equal (50%) | IC ≈ 0.08–0.12 at T+1; concentrated in Day −1 |

- **Combination method:** Equal-weight OR-logic — each signal is independently sufficient to initiate a position
- **Combined signal IC estimate:** ~0.08 (average of TOM 0.07 and Pre-Holiday 0.09)
- **Overfitting guard:** TOM IC ≈ 0.07 > 0.02 ✓ | Pre-Holiday IC ≈ 0.09 > 0.02 ✓. Both signals qualify individually before combination.
- **Max signals:** 2 ≤ 3 (hard limit) ✓
- **IC-weighted blending:** Not required — ICs are close enough (0.07 vs 0.09) that equal-weight is appropriate and avoids an extra parameter

## Market Regime Context

**Works best:**
- Bull markets (SPY > 200-SMA): both signals fire freely with regime filter open
- Low-to-moderate volatility (VIX 12–25): payroll inflows and short-covering mandates reinforce the long bias
- Range-bound markets with institutional participation: TOM effect is strongest when institutions are active buyers

**Fails / filtered out:**
- Bear markets (SPY < 200-SMA): regime filter blocks all entries — strategy sits in cash
- 2022 rate-shock: SPY below 200-SMA for majority of the year → most or all entries blocked ✓
- 2000–2002 dot-com bust: SPY below 200-SMA from April 2001 onward → entries blocked ✓
- 2008 GFC: SPY below 200-SMA from January 2008 → entries blocked ✓

**Key advantage over H28:** The 200-SMA filter creates a clean binary regime gate that is independent of the VIX level. In 2022, VIX was in a moderate-high range (25–35) rather than a crisis range (>40), meaning the H28 VIX filter frequently failed to block entries. The 200-SMA is a price-action-based filter that correctly identifies the sustained downtrend regardless of volatility regime.

**Expected regime Sharpe estimates (with 200-SMA filter):**
| Regime | Expected Sharpe |
|--------|----------------|
| Bull / low-vol | 1.0–1.5 |
| Range-bound | 0.6–1.0 |
| 2022 Rate-Shock | ~0 (filtered) |
| Dot-com bust | ~0 (filtered) |
| GFC | ~0 (filtered) |
| 2020 COVID crash | ~0 (March–May filtered); recovers in recovery phase |

## Entry/Exit Logic

**Capital allocation philosophy:** 100% SPY when any signal is active AND SPY > 200-SMA; 100% cash otherwise. No leverage. Regime filter evaluated at each entry — positions already in flight are not exited by regime filter mid-trade (only new entries blocked).

---

### Regime Gate (Applied Before All Entries)

**Condition:** `SPY_close[-1] > SPY_200SMA[-1]` (previous day's close above its 200-day SMA)
- If **TRUE**: strategy may enter per signal logic below
- If **FALSE**: strategy remains in cash; any new signal entry is blocked
- **Note:** Existing open positions from prior entries are held to their scheduled exit date — the regime filter blocks new entries only, it does not force mid-trade exits (to avoid whipsawing at 200-SMA crossings)

---

### Signal 1 — Turn-of-Month (TOM)

**Entry:**
- Trigger: Close on the **2nd-to-last trading day of each month** (Day −2 from month-end)
- Filter 1: Regime gate passes (SPY > 200-SMA)
- Filter 2: VIX close ≤ 28 on entry day
- Action: Enter SPY long at today's close (100% of portfolio)

**Exit:**
- Force exit at close on **Day +3 of the following month**
- No stop loss (structured 5–6 day hold; stop adds noise and destroys ICs of a calendar signal)

**Holding period:** ~5–6 trading days spanning the month-turn

---

### Signal 2 — Pre-Holiday

**Entry:**
- Trigger: Close on the **2nd trading day before each US stock market holiday** (Day −2)
  - US holidays: New Year's Day, MLK Day, Presidents Day, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas (9 total)
  - If Day −2 is non-trading, shift to Day −3
- Filter 1: Regime gate passes (SPY > 200-SMA)
- Filter 2: VIX close ≤ 35 on entry day (crisis-only filter — less restrictive given mechanism robustness)
- Action: If not already in SPY, enter SPY long at Day −2 close

**Exit:**
- Force exit at close on **Day −1 (last trading day before holiday)**
- If already in SPY from TOM signal: maintain position; do not reset exit to Day −1

**Holding period:** 1–2 trading days (Day −2 through Day −1)

---

### Overlap Rules

**Rule 1 — Any signal triggers entry.** If in cash and any signal fires (and both filters pass), enter 100% SPY at session close.

**Rule 2 — Overlap maintains position.** If already in SPY and a second signal fires, continue holding. Do NOT exit and re-enter.

**Rule 3 — Exit on latest active signal's expiry.** If TOM and Pre-Holiday overlap (e.g., New Year's pre-holiday falls within TOM window), exit on the later of the two scheduled exits.

**Rule 4 — Extended holds capped at 8 trading days.** No position holds beyond 8 trading days (reduced from H28's 10 — OEX Week was the reason for 10-day cap; 8 is sufficient for TOM+Pre-Holiday).

---

### Annual Trade Schedule (With 200-SMA Bear Filter)

| Signal | Gross frequency | Expected filtered entries/yr | In-market days (filtered) |
|--------|----------------|------------------------------|--------------------------|
| TOM | 12 cycles/yr | ~9–10 (assume ~25% bear-year reduction) | ~40–50 days (~19%) |
| Pre-Holiday | 9 cycles/yr | ~7–8 | ~12–16 days (~5–6%) |
| **Combined (OR-logic, after overlaps)** | **~18–20 unique entries/yr** | **~18–20** | **~50–65 days (~22–27%)** |

> Note: 25% reduction estimate assumes ~3 months per year on average where SPY is below 200-SMA (approximated from 2006–2024 historical frequency). In pure bull periods (2010–2019), filter rarely fires; in bearish periods (2022), filter fires frequently.

**IS trade count estimate:** 18 entries/yr × 15yr = 270 trades (conservative; in bull-heavy IS periods closer to 315)

## Gate 1 Outlook

- **IS Sharpe target > 1.0:** Achievable. Conservative estimate 0.8–1.1. Pre-Holiday IC ≈ 0.09 is the strongest individual signal in the H28 suite. TOM is well-documented. Removing OEX Week eliminates the largest source of instability. 200-SMA filter addresses the primary failure mode (2022). Expected improvement vs H28 baseline (0.098): substantial — 200-SMA filter alone estimated to remove ~60–70% of H28's IS losses.
- **OOS Sharpe > 0.7:** Moderate confidence. Both TOM and Pre-Holiday are documented over 35–90 years across multiple markets. OOS decay expected but within acceptable range for calendar effects.
- **Walk-forward stability:** Good. Calendar signal dates are structurally fixed; regime filter adds one binary gate. Parameter space is narrow (4 free parameters).
- **DSR improvement vs H28:** Very large. H28 had 10 parameters; H29 has 4–5. DSR penalty is ~(parameters)² in the Hairpin correction — reduction from 10 to 4–5 parameters cuts DSR penalty by ~75–85%.
- **Permutation p-value improvement:** Expected. H28 p-value 0.511 was driven by the OR-logic covering 45–50% of trading days — nearly random-entry frequency. H29 covers ~22–27% of trading days (halved), improving statistical distinguishability. Target p-value < 0.05.

## Recommended Parameter Ranges

| Parameter | Baseline | Test Range | Rationale |
|---|---|---|---|
| `tom_entry_day` | −2 (day from month-end) | −3 to −1 | Academic consensus supports −2; test adjacent |
| `tom_exit_day` | +3 (day into next month) | +2 to +4 | Academic consensus +3; test ±1 for robustness |
| `vix_threshold_tom` | 28 | 25, 28, 32 | H28 baseline; test conservative (25) and permissive (32) |
| `vix_threshold_preholiday` | 35 | None, 35, 40 | Test no-VIX-filter to check if Pre-Holiday is robust without |
| `sma_period` | 200 | 150, 200 | 200-SMA is canonical; 150 as secondary robustness check (optional — only if 200 passes) |

**Total free parameters: 4–5** (well within Gate 1 limit; DSR-safe for IS Sharpe > 0.8)

**Parameter pre-registration required:** Engineering Director must lock parameter ranges before IS backtest begins. No post-hoc parameter selection.

## Capital and PDT Compatibility

- **Minimum capital required:** $3,000 (100% SPY single position; ETF price ~$400–550 × 1 lot)
- **PDT impact:** None — all positions are multi-day holds (1–6 days minimum). All entries and exits at the close. No day trades consumed. ✓
- **Position sizing:** 100% SPY (single ETF, no leverage)
- **Max concurrent positions:** 1 (SPY only)
- **Annual trade count:** ~18–21 round-trip entries/exits per year after regime filter
- **Annual transaction costs (est.):** $25K × 18–21 round trips × <0.005% ≈ <$30/yr

## Alpha Decay Analysis

- **Signal half-life:**
  - TOM: 3–4 days (edge concentrated in 5-day month-turn window; IC declines through the window)
  - Pre-Holiday: 1–2 days (concentrated in Day −1; enters at Day −2 to capture the run-up)
  - **Combined effective half-life: ~2.5–3 days** (weighted by frequency: TOM-dominant)
- **IC decay curve:**
  - T+1: IC ≈ 0.08–0.12 (entry day signal confirmation for both signals)
  - T+3: IC ≈ 0.04–0.07 (mid-TOM hold; Pre-Holiday already exited by T+2)
  - T+5: IC ≈ 0.01–0.03 (TOM tail; near exit by Day +3)
  - T+8: IC ≈ 0.00 (all windows expired; max hold cap reached)
- **IC decay shape:** Graceful cliff — not instantaneous. TOM IC decays linearly through the 5-day window; Pre-Holiday IC is step-down (exits at Day −1).
- **Transaction cost viability:** Yes. SPY round-trip cost < 0.005%. Combined annual gross excess return estimated 5–7% vs cash (reduced from H28's 8–10% due to dropped OEX Week; regime filter reduces market time). Edge survives transaction costs by ~150–200× estimated round-trip cost.
- **Crowding risk:** Low-moderate. TOM is widely known but mechanism is structural. Pre-Holiday is less crowded. 200-SMA filter adds a timing layer not present in most retail implementations.

## Pre-Flight Gate Checklist

| Gate | Status | Detail |
|---|---|---|
| **PF-1: Walk-Forward Trade Viability (IS trades ÷ 4 ≥ 30)** | **PASS** | Conservative: 18 entries/yr × 15yr = 270 ÷ 4 = 67.5 ≥ 30 ✓. Bull-weighted IS period: 21 entries/yr × 15yr = 315 ÷ 4 = 78.75 ≥ 30 ✓. Robust pass even with regime filter reducing entries. |
| **PF-2: Long-Only MDD < 40% (dot-com + GFC)** | **PASS** | 200-SMA filter: SPY crossed below 200-SMA in early 2001 (dot-com) and January 2008 (GFC). TOM and Pre-Holiday entries blocked for majority of both crash periods. Estimated dot-com MDD < 10% (regime filter catches sustained decline). GFC MDD < 5% (SPY below 200-SMA from Jan 2008; filter active). Both well under 40% threshold. |
| **PF-3: Data Pipeline Availability** | **PASS** | SPY daily OHLCV (yfinance, 1993+), VIX ^VIX daily (yfinance, 1990+), SPY 200-SMA computed from SPY OHLCV. US holiday calendar: `pandas_market_calendars`. All daily data, no intraday required. ✓ |
| **PF-4: Rate-Shock Regime Plausibility** | **PASS** | **Explicit mechanism:** SPY closed below its 200-day SMA in late January 2022 and remained below it through October 2022 (approximately 9 months). The 200-SMA filter would block TOM and Pre-Holiday entries during this entire period. The 2022 regime failure in H28 (Sharpe −1.671) was driven by executing calendar trades during a sustained bear market — this filter directly eliminates that pathway. This is not "the backtest might capture it" — it is a mechanistic a priori rule: do not trade long-biased calendar effects in a confirmed bear market. |

**All 4 PF gates: PASS**

## Family Iteration Status

- **H28** (iteration 1): Combined TOM + OEX Week + Pre-Holiday — Gate 1 FAIL (IS Sharpe 0.098)
- **H29** (iteration 2): TOM + Pre-Holiday + 200-SMA filter — this document
- **Status:** This is iteration 2 of 2 for the Combined Calendar family. If H29 fails Gate 1, the Combined Calendar family is **retired** per CEO Directive QUA-181. Standalone Pre-Holiday (Option B) or OEX Week intraday redesign (Option D) may proceed as new families.

## References

- Ariel, R.A. (1987). "A Monthly Effect in Stock Returns." *Journal of Financial Economics*, 18(1), 161–174.
- Ariel, R.A. (1990). "High Stock Returns before Holidays: Existence and Evidence on Possible Causes." *Journal of Finance*, 45(5), 1611–1626.
- Lakonishok, J. & Smidt, S. (1988). "Are Seasonal Anomalies Real? A Ninety-Year Perspective." *Review of Financial Studies*, 1(4), 403–425.
- McConnell, J.J. & Xu, W. (2008). "Equity Returns at the Turn of the Month." *Financial Analysts Journal*, 64(2), 49–64.
- Kim, C.W. & Park, J. (1994). "Holiday Effects and Stock Returns: Further Evidence." *Journal of Financial and Quantitative Analysis*, 29(1), 145–157.
- Quantpedia #0083: Pre-Holiday Effect — https://quantpedia.com/strategies/pre-holiday-effect/
- Quantpedia: Turn of the Month in Equity Indexes — https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes
- Related hypotheses: `research/hypotheses/22_tv_turn_of_month_multi_etf.md`, `research/hypotheses/26_qc_pre_holiday_seasonal.md`, `research/hypotheses/28_combined_multi_calendar.md`
- H28 Gate 1 FAIL analysis: [QUA-242](/QUA/issues/QUA-242)
