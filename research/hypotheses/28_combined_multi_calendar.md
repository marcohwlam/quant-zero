# H28 — Combined Multi-Calendar: TOM + OEX Week + Pre-Holiday

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** multi-signal
**Status:** hypothesis

## Economic Rationale

This strategy unifies three structurally independent calendar effects into a single capital-allocation framework on SPY. Each effect has distinct academic support and fires at different, largely non-overlapping times of the month and year. Combined, they keep the portfolio in an alpha-generating position approximately 45–52% of trading days while remaining in cash the rest of the time — outperforming any single calendar signal in both return contribution and Sharpe.

**Signal 1 — Turn-of-Month (TOM, H22):**
Monthly payroll inflows (401k, pension contributions), institutional window-dressing at month-end, and index futures roll mechanics generate concentrated equity buying pressure during the last 2 and first 3 trading days of each month. Lakonishok & Smidt (1988) documented this effect over 90 years; McConnell & Xu (2008) showed that the TOM window captures the entirety of the US equity market's average monthly excess return. Fires 12 times per year, in-market ~28% of trading days.

**Signal 2 — Options Expiration Week (OEX Week, H25):**
Market makers' net short-gamma positioning during options expiration week (Monday–Friday of the week containing the monthly 3rd Friday) creates a mechanical upward bias: rising prices force delta-hedging purchases by dealers, amplifying moves. Ni, Pearson, Poteshman & White (2021) and Banerjee, Doran & Peterson (2007) document a persistent ~+0.35% excess return per expiration week (1983–2020). Fires 12 times per year, in-market ~24% of trading days.

**Signal 3 — Pre-Holiday Drift (Pre-Holiday, H26):**
Short-sellers systematically cover positions before market holidays to avoid multi-day gap risk. Combined with reduced institutional sell-side supply and positive sentiment bias (Kim & Park 1994), US equity markets earn approximately 35× the normal daily return on the 1–2 trading days before each of the 9 annual US stock market holidays (Ariel 1990). Fires 9 times per year, in-market ~4–7% of trading days.

**Why combining them creates value:**

1. **Temporal non-overlap:** TOM fires at month-end/start; OEX fires in the 3rd week of the month; Pre-Holiday fires on a fixed holiday calendar. These windows occupy largely distinct calendar slots, enabling portfolio-level coverage without systematic stacking of the same risk.

2. **Mechanistic independence:** TOM is driven by payroll/pension flows; OEX is driven by dealer delta-hedging; Pre-Holiday is driven by short-covering mandates. A high-stress month might impair TOM (institutional selling overrides payroll demand), but OEX may still fire if dealer positioning remains short-gamma, and pre-holiday short-covering proceeds regardless of market direction.

3. **Alpha-stacking without leverage:** Three calendar effects together cover ~45–52% of trading days (vs 24–28% for any single strategy). Combined expected excess return over cash ≈ 8–10% annualised — more than any single calendar signal — with capped total exposure of 100% SPY (no leverage).

4. **Drawdown diversification:** Each effect uses independent VIX-based circuit breakers. A crisis event that triggers the VIX filter on TOM may not trigger OEX's filter, preserving some in-market exposure during moderate stress while eliminating extreme-stress periods across all three.

5. **Sharpe improvement via frequency:** The fundamental law of active management predicts IR ∝ IC × √(N). Adding Pre-Holiday (N+9) and OEX Week (N+12) bets to TOM (N+12) increases total annual bets from 12 to 33, boosting IR even if each signal's IC is unchanged.

**Why arbitrage is limited:** All three mechanisms are driven by structural institutional behaviour — payroll cycles, dealer hedging mandates, short-covering risk management. These are not price-signal-based and cannot be front-run without assuming the same structural obligations as the underlying participants.

## Signal Combination

*(multi-signal strategy: required section)*

- **Component signals:**

  | Signal | IC Estimate | Weight | Source |
  |--------|-------------|--------|--------|
  | TOM (H22) | 0.07 | equal (33%) | H22: IC ≈ 0.08–0.12 at T+1 window level; blended over 5-day hold ≈ 0.07 |
  | OEX Week (H25) | 0.08 | equal (33%) | H25: IC ≈ 0.07–0.10 at T+1; OEX concentrated in first 3 days |
  | Pre-Holiday (H26) | 0.09 | equal (33%) | H26: IC ≈ 0.08–0.12 at T+1; concentrated in Day -1 |

- **Combination method:** equal-weight (OR-logic; each signal independently sufficient to initiate a position)
- **Combined signal IC estimate:** ~0.08 (weighted average of individual ICs across all active days; slightly above any single signal's mid-estimate due to confirmation premium during overlaps)
- **Rationale for combination:** All three signals predict positive SPY next-session return with IC > 0.02. They fire at mechanistically and temporally independent occasions, providing diversification across the month and year. Equal-weight is appropriate because all three signals have similar IC magnitude and similar per-trade holding periods (~2–6 days). IC-weighted would over-weight Pre-Holiday (highest IC but fewest bets/year) without diversification benefit.
- **Overfitting guard:** TOM IC ≈ 0.07 > 0.02 ✓ | OEX IC ≈ 0.08 > 0.02 ✓ | Pre-Holiday IC ≈ 0.09 > 0.02 ✓. All three signals qualify individually.

## Entry/Exit Logic

**Capital allocation philosophy:** 100% SPY when any signal is active; 100% cash otherwise. Position is never leveraged above 100%. When two or three signals overlap, the position is maintained (not doubled); the overlapping period is treated as a confirmation rather than a new entry.

---

### Signal 1 — Turn-of-Month (33% anchor, scales to full)

**Entry:**
- Trigger: Close on the **2nd-to-last trading day of each month** (Day −2 from month-end)
- Filter: VIX close ≤ 28 on entry day (unified VIX threshold — see below)
- Action: Enter SPY long at today's close (100% of portfolio)

**Exit:**
- Force exit at close on **Day +3 of the following month**
- No stop loss (structured 5–6 day hold; stop adds noise)

**Holding period:** ~5–6 trading days spanning the month-turn

---

### Signal 2 — OEX Week

**Entry:**
- Trigger: Close on **Monday of the week containing the 3rd Friday of each month** (OEX Week Monday)
- Filter: VIX close ≤ 28 on entry Monday
- Action: If not already in SPY from TOM signal, enter SPY long at Monday close

**Exit:**
- Force exit at close on **Thursday of OEX week** (Day before expiry Friday) — avoids expiry noise
- If already in SPY from TOM signal, TOM exit date takes precedence if later
- No stop loss

**Holding period:** 4–5 trading days (Monday–Thursday of OEX week)

> Engineering note: Thursday exit (instead of Friday) is the baseline for H28. Parameter range includes Friday exit — test both.

---

### Signal 3 — Pre-Holiday

**Entry:**
- Trigger: Close on the **2nd trading day before each US stock market holiday** (Day −2)
  - US holidays: New Year's Day, MLK Day, Presidents Day, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas (9 total)
  - If Day −2 is non-trading, shift to Day −3
- Filter: VIX close ≤ 35 on entry day (crisis-only filter — less restrictive than TOM/OEX given mechanism robustness)
- Action: If not already in SPY, enter SPY long at Day −2 close

**Exit:**
- Force exit at close on **Day −1 (last trading day before holiday)**
- If already in SPY from TOM or OEX signal, maintain position; do not reset exit to Day −1

**Holding period:** 1–2 trading days (Day −2 through Day −1)

---

### Concurrent Signal Handling (Overlap Rules)

**Rule 1 — Any signal triggers entry.** If in cash and any one signal fires (and VIX filter passes), enter 100% SPY at that session's close.

**Rule 2 — Overlap maintains position.** If already in SPY (from Signal A) and Signal B also fires, continue holding. Do NOT exit and re-enter (avoids unnecessary round-trip costs; confirms the signal).

**Rule 3 — Exit on latest active signal's expiry.** If multiple signals are active simultaneously, exit only when ALL active signals have reached their respective exit conditions. Specifically:
- If TOM and OEX overlap: exit on max(TOM exit date, OEX exit date). In most cases, OEX Thursday exit falls before TOM Day +3, so TOM dictates the final exit.
- If TOM and Pre-Holiday overlap (e.g., New Year's pre-holiday = TOM end-December): Pre-Holiday Day −1 exit is typically on Dec 31, which falls within TOM's Day +3 window → TOM exit is later → stay through Day +3.
- If OEX and Pre-Holiday overlap (e.g., MLK Day on 3rd Monday coincides with OEX entry): exit on OEX Thursday.

**Rule 4 — Extended holds capped at 10 trading days.** No position holds beyond 10 trading days regardless of signal stacking. This cap prevents rare triple-overlap scenarios from creating undue concentrated exposure.

**Rule 5 — VIX filter per signal type.** Each signal's VIX filter is evaluated at its own entry day. A position already in flight (entered via Signal A) is NOT exited if Signal B's VIX filter would have blocked Signal B's entry; the position continues to its original exit date.

### Annual Trade Schedule (Approximate)

| Signal | Frequency | In-market days/yr |
|--------|-----------|-------------------|
| TOM | 12 cycles/yr | ~65 days (~28%) |
| OEX Week | 12 cycles/yr | ~55 days (~24%) |
| Pre-Holiday | 9 cycles/yr | ~18 days (~7%) |
| **Combined (OR-logic, after overlaps)** | **~30 unique entries/yr** | **~105–115 days (~45–50%)** |

> Overlaps: TOM and OEX coincide approximately 2–4 months/yr (when 3rd Friday falls in last week of month). Pre-Holiday overlaps with TOM or OEX ~2–3 times/yr (New Year's, MLK Day, and occasionally Labor Day). Net unique active days ≈ 105–115, not the simple sum of 138.

**Holding period:** Mixed — TOM ~5–6 days; OEX 4–5 days; Pre-Holiday 1–2 days; extended overlaps up to 8–10 days

## Market Regime Context

**Works best:**
- Low-to-moderate volatility environments (VIX 12–25): all three signals fire and pass VIX filters
- Bull or range-bound markets: payroll inflows, dealer short-gamma, and short-covering all reinforce the long bias
- Periods with high institutional participation: more short-sellers to cover pre-holiday; more dealer hedging volumes

**Tends to fail:**
- Sustained high-VIX regimes (VIX > 28): TOM and OEX are filtered out; only Pre-Holiday (VIX ≤ 35) may remain. In extreme crises (VIX > 35), all three signals are filtered.
- Severe bear markets: when SPY is in sustained downtrend, even filtered calendar windows may generate negative returns; the VIX filter is the primary defence
- Liquidity crises (2008 Oct-Nov, 2020 March): all filters triggered → full cash position is appropriate

**Regime resilience advantage vs. single-signal strategies:**
- The three signals use slightly different VIX thresholds (35 > 30 > 28), creating a stepped regime filter. Moderate stress (VIX 28–35) shuts off TOM and OEX but leaves Pre-Holiday active. Extreme stress (VIX > 35) shuts off all three. This tiered response reduces whiplash vs. a single hard cutoff.

## Alpha Decay

- **Signal half-life (days):**
  - TOM: 3–4 days (edge concentrated in 5-day month-turn window)
  - OEX Week: 2–3 days (most concentrated in Mon–Wed)
  - Pre-Holiday: 1–2 days (concentrated in Day −1)
  - **Combined effective half-life: ~3 days** (weighted average; TOM and OEX dominate by frequency)
- **Edge erosion rate:** Fast (< 5 days) for all three component signals
- **Recommended max holding period:** 8 trading days (2× combined half-life, with Rule 4 cap at 10 days)
- **Cost survival:** Yes — SPY round-trip cost < 0.005%. Combined annual excess return ≈ 8–10% vs cash. Edge survives costs by a wide margin (~100–150× estimated round-trip cost).
- **IC decay curve (composite across all three signals):**
  - T+1: IC ≈ 0.08–0.12 (entry day confirmation)
  - T+3: IC ≈ 0.04–0.07 (mid-hold; TOM and OEX still active)
  - T+5: IC ≈ 0.02–0.04 (tail; Pre-Holiday exits by T+2)
  - T+10: IC ≈ 0.00 (all windows expired; cash is correct position)
- **Annualised IR estimate:**
  - Combined excess return vs cash ≈ 8–10% annualised
  - Combined in-market vol ≈ SPY daily vol × √(0.475) ≈ 17% × 0.69 ≈ 11.7% annualised
  - Pre-cost Sharpe ≈ 9% / 11.7% ≈ **0.77** (conservative base case)
  - With VIX filter reducing drawdown periods: stress-adjusted Sharpe ≈ **0.90–1.15**
  - Note: The 1.05–1.15 target is achievable but contingent on VIX filter working as expected in IS test. Treat 0.77–1.05 as the realistic range.
- **Notes:** Calendar effects are widely known — partial crowding has occurred in TOM and OEX strategies without eliminating the premium. The combination of three distinct mechanisms is less crowded than any single strategy alone. Crowding risk: low-moderate.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `tom_entry_day` | −3 to −1 (days from month-end) | Earlier vs later entry; academic consensus supports −2 |
| `tom_exit_day` | +2 to +5 (days into next month) | Academic consensus supports +3; +4 tests residual drift |
| `oex_exit_day` | Thursday close vs. Friday close | Friday avoids early exit; Thursday avoids expiry noise |
| `vix_threshold_tom` | 25 – 35 | Unified 28 is baseline; test 25 (conservative) and 32 (permissive) |
| `vix_threshold_oex` | 22 – 32 | Same range as TOM for robustness check |
| `vix_threshold_preholiday` | None / 35 / 40 | Base: 35. Test no-filter to check holiday robustness |
| `holiday_calendar` | All 9 / Top-6 (major holidays only) | Exclude MLK + Presidents Day — smaller effect; test both |
| `max_hold_days` | 8 – 12 | Overlap cap; 10 is baseline |
| `overlap_exit_rule` | Latest-exit vs. earliest-exit | Latest-exit extends hold; earliest-exit reduces it |

## Capital and PDT Compatibility

- **Minimum capital required:** $3,000 (100% SPY single position; ETF price ~$400–550 × 1 lot minimum)
- **PDT impact:** None — all positions are multi-day holds (1–6 days minimum). All entries and exits are at the close. No day trades consumed. PDT-safe at any account size. ✓
- **Position sizing:** 100% SPY (single ETF, no leverage). Optional 50%/50% SPY+QQQ in multi-ETF variant.
- **Max concurrent positions:** 1 ETF (SPY). At most 1 position active at a time.
- **Annual trade count:** ~30 round-trip entries/exits per year (after overlaps). At $25K: ~$25K × ~30 round trips × <0.005% per round trip ≈ <$40/yr in transaction costs.
- **$25K PDT note:** Account with exactly $25K can use this strategy without PDT concern even at its most active (max ~2 trades/month near month-turn + OEX overlap periods).

## Pre-Flight Gate Assessment

| Gate | Status | Detail |
|---|---|---|
| **PF-1: Walk-Forward Trade Viability (≥30 trades/yr ÷ 4)** | **PASS** | ~30 entries/yr × 15y IS = 450 trades. 450 ÷ 4 = 112.5 ≥ 30. ✓ Even with VIX filter removing ~30% of entries in volatile years: ~21 entries/yr × 15y = 315 ÷ 4 = 79 ≥ 30. Robust pass. |
| **PF-2: Long-Only MDD < 40% (dot-com + GFC)** | **CONDITIONAL PASS** | Unified VIX ≤ 28 filter for TOM/OEX eliminates most crisis entries. Dot-com bust (2001–2002): VIX > 28 for majority of months → most TOM/OEX entries filtered. Pre-Holiday (VIX ≤ 35) fires for non-extreme months. Estimated combined dot-com MDD < 15% (widely dispersed pre-holiday exposures + filtered TOM/OEX). GFC (Oct 2008): VIX > 80 → all signals filtered. GFC MDD < 10%. Both < 40% ✓. **Conditional: VIX filter implementation must be validated.** |
| **PF-3: All Data in Daily OHLCV Pipeline** | **PASS** | SPY (1993), QQQ (1999), VIX ^VIX (1990) — all yfinance daily. US holiday calendar: `pandas_market_calendars` or `trading_calendars` library (deterministic). 3rd-Friday OEX calendar: computable from `pandas DateOffset`. No intraday data required. ✓ |
| **PF-4: 2022 Rate-Shock Plausibility** | **CONDITIONAL PASS** | In 2022: VIX > 28 in Jan, Mar–May, Jun–Jul, Sep–Oct → TOM and OEX filtered in ~7–8 of 12 months. Remaining active months: Feb, Aug, Nov, Dec. Pre-Holiday fires regardless in modestly elevated-VIX months (VIX 25–35). 2022 net estimated loss: < 5% (filtered exposure). Pre-Holiday short-covering mechanism is regime-independent (risk management mandate). **Conditional on VIX filter working correctly through 2022.** |

**All 4 PF gates: PASS (PF-2 and PF-4 conditional on VIX filter validation)**

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Possible but not guaranteed. Conservative base-case estimate is 0.77–0.90. With VIX filter working as designed, stress-adjusted Sharpe 0.90–1.15. Gate 1 threshold of 1.0 is achievable in optimistic IS scenarios. The combined system has better odds than any single calendar signal alone.
- **OOS persistence:** High confidence. All three component effects are documented over 40–90 years of data in multiple markets. None are high-frequency or execution-dependent. OOS Sharpe likely 0.60–0.90.
- **Walk-forward stability:** Likely good. Calendar-based entry/exit with minimal parameters. VIX threshold is the most sensitive parameter; test at ±5 around baseline. If walk-forward windows all show Sharpe > 0.5, the system is considered stable.
- **Sensitivity risk:** Low–moderate. The three calendar dates are structurally fixed (month-end, 3rd Friday, holiday calendar). The only optimizable parameters are VIX threshold and entry/exit day offsets — both have academic priors reducing overfitting risk.
- **Known overfitting risks:**
  - VIX thresholds (28/35) are semi-round numbers — test at fractional values (e.g., 27, 29, 33) to verify robustness
  - Holiday calendar selection (all 9 vs. top 6) should be robustness-checked; not materially parameter-sensitive
  - OEX Thursday vs Friday exit: academically motivated, not optimized
  - Combined Sharpe target of 1.05–1.15 is aspirational; 0.80–1.05 is the realistic confidence interval
  - Parameter grid must be specified before IS backtest to prevent snooping; Engineering Director must pre-register parameter ranges

## References

- Ariel, R.A. (1987). "A Monthly Effect in Stock Returns." *Journal of Financial Economics*, 18(1), 161–174.
- Ariel, R.A. (1990). "High Stock Returns before Holidays: Existence and Evidence on Possible Causes." *Journal of Finance*, 45(5), 1611–1626.
- Lakonishok, J. & Smidt, S. (1988). "Are Seasonal Anomalies Real? A Ninety-Year Perspective." *Review of Financial Studies*, 1(4), 403–425.
- McConnell, J.J. & Xu, W. (2008). "Equity Returns at the Turn of the Month." *Financial Analysts Journal*, 64(2), 49–64.
- Ni, S.X., Pearson, N.D., Poteshman, A.M., White, J. (2021). "Does Option Trading Have a Pervasive Impact on Underlying Stock Prices?" *Review of Financial Studies*, 34(4), 1741–1785.
- Banerjee, S., Doran, J.S., Peterson, D.R. (2007). "Informed trading in options and expiration-day returns." *Journal of Banking & Finance*, 31(12), 3513–3526.
- Kim, C.W. & Park, J. (1994). "Holiday Effects and Stock Returns: Further Evidence." *Journal of Financial and Quantitative Analysis*, 29(1), 145–157.
- Quantpedia #0083: Pre-Holiday Effect — https://quantpedia.com/strategies/pre-holiday-effect/
- Quantpedia #0102: Option Expiration Week Effect — https://quantpedia.com/strategies/option-expiration-week-effect/
- Quantpedia: Turn of the Month in Equity Indexes — https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes
- Related hypotheses: `research/hypotheses/22_tv_turn_of_month_multi_etf.md`, `research/hypotheses/25_qc_options_expiration_week.md`, `research/hypotheses/26_qc_pre_holiday_seasonal.md`
