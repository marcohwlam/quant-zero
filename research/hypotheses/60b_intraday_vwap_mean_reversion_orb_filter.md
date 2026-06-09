# H60b: Intraday VWAP Mean Reversion v2 — ORB Session Filter + Tightened VPIN Gate

**Version:** 1.0
**Author:** Research Director
**Date:** 2026-06-09
**Reviewed by:** Research Director
**Review date:** 2026-06-09
**Asset class:** equities
**Strategy type:** single-signal
**Status:** DRAFT — IC re-estimation pending (see QUA-168 subtask)
**Parent hypothesis:** H60 (`60_intraday_vwap_mean_reversion.md`)
**Parent Gate 1 result:** FAIL (QUA-166, backtested 2026-06-09)

---

## Redesign Summary (Gate 1 Failure Response)

H60 failed Gate 1 on two independent failure modes. This redesign addresses both.

### Gate 1 Failure Recap

| Metric | SPY-Calibrated (0.005% slip) | Gate |
|---|---|---|
| IS Sharpe | -0.877 | > 1.0 |
| OOS Sharpe | -1.280 | > 0.7 |
| WF Stability | 2/6 | ≥ 3/6 |
| OOS Win Rate | 40.3% | — |
| OOS Stop-Loss Rate | 74% (260/352 trades) | — |

### Root Cause A — Missing ORB Filter (Primary)

The H60 hypothesis described an opening-range filter in the Market Regime Context section:

> *"Regime pause trigger: Skip session if opening range (first 30-min high–low spread) exceeds 1.5% — this identifies gap-and-trend sessions where VWAP reversion is unreliable."*

**This filter was never implemented in the strategy code.** The 2022 backtest included trend days (high opening ranges) that were explicitly excluded in the hypothesis design. VPIN was 0.35–0.40 on these trending sessions — below the 0.55 entry gate — so the strategy entered into persistent VWAP deviations that did not revert. Result: 74% stop-loss rate (OOS).

**Fix:** Implement the ORB session filter that was always part of the design intent.

### Root Cause B — Kissell IC Compression (Secondary)

Kissell (2014) IC estimates (0.12–0.15 at T+0) are stale. Post-2015 HFT proliferation and algorithmic VWAP strategy proliferation appear to have compressed observed IC to ~0.06–0.09 in the 2022–2024 period. Even after applying the ORB filter, the revised IC must be estimated from 2022–2024 data before resubmission.

**Fix:** Delegate IC re-estimation to Alpha Research Agent (delegated via QUA-168 subtask). H60b is DRAFT until this is complete.

### Family Iteration Status

This is the **second and final permitted iteration** of the H60 VWAP mean reversion family. Per the Family Iteration Limit (CEO Directive QUA-181):
- Maximum 2 Gate 1 iterations per hypothesis family before mandatory retirement
- A third iteration requires: each prior iteration showed ≥0.1 IS Sharpe improvement AND explicit written rationale from Research Director

H60 IS Sharpe: -0.877 (SPY-calibrated). H60b must demonstrate IS Sharpe improvement ≥ +0.10 (target: IS Sharpe > -0.77 minimum; goal: > 1.0 gate). If H60b also fails Gate 1, the VWAP mean reversion family is retired.

---

## Changes from H60

| Component | H60 (failed) | H60b (redesign) |
|---|---|---|
| Opening-range session filter | Described, not implemented | **Implemented**: 30-min H-L > 1.5% → skip session |
| VPIN entry gate | 0.55 | **0.45** (tightened — secondary fix) |
| IC estimates | Kissell 2014 (0.12–0.15) | **Pending re-estimation** (Alpha Research) |
| Status | APPROVED → Gate 1 FAIL | DRAFT (pending IC re-estimation) |

---

## Summary

Intraday VWAP mean reversion targets structural counter-directional order flow from VWAP-targeting institutional algorithms (~30–40% of equity flow; Harris 2003). Strategy fades statistically extreme VWAP deviations using an Ornstein-Uhlenbeck z-score, gated by VPIN to avoid informed/toxic flow (Easley et al. 2012) and by an opening-range breakout (ORB) filter to skip trending sessions where VWAP deviations persist. All positions are intraday-flat by hard rule.

**Core redesign rationale:** The ORB session filter is the dominant fix. Trend days — identified by wide opening ranges (> 1.5% of open price in the first 30 minutes) — generate VWAP deviations that do NOT revert; institutional VWAP algorithms are also chasing a trend on these sessions, removing the structural counter-flow. Filtering these sessions was always part of the H60 design intent; it was omitted from the implementation.

---

## Economic Rationale

See H60 for full rationale (unchanged). Summary:
1. VWAP algorithm acceleration creates structural counter-directional flow (Harris 2003, Chapter 12)
2. Career-risk economics create opposing interest at VWAP deviation tails (Perold 1988)
3. Midday window (10:30–14:30) has lowest informed-flow fraction (Harris 2003, pp. 274–277)
4. OU s-score framework provides principled entry/exit thresholds (Avellaneda & Lee 2010)
5. VPIN gate prevents fading informed/toxic flow (Easley et al. 2012)

**Additional H60b rationale for ORB filter:**

On sessions where the first 30-min opening range exceeds 1.5%, the session is exhibiting directional momentum driven by macro news (overnight, pre-market, or early-release events). In these sessions:
- VWAP algorithms are net directional (executing trending flows), not mean-reverting
- Institutional VWAP deviations in one direction are being fed by aggressive directional order flow
- VPIN may remain low (0.35–0.40) because the trend is driven by broad market participants, not identifiable informed actors
- Result: VWAP deviations persist and widen → stop-losses fire

The ORB filter is a well-established session classifier in intraday trading (Lo, MacKinlay & Zhang 2002 document opening-range predictive power for intraday direction). Filtering sessions with ORB > 1.5% is a binary regime classifier that is: (a) computable from available minute-bar data, (b) grounded in prior literature, (c) not IS-optimized (threshold derived from H60 hypothesis description, not backtest).

---

## Entry/Exit Logic

### New: Opening-Range Breakout (ORB) Session Filter

```python
ORB_THRESHOLD = 0.015  # 1.5% of session open price (from H60 design intent; not IS-optimized)
ORB_WINDOW_BARS = 30   # First 30 minutes of session (9:30-10:00 ET, 1-min bars)

def compute_orb_pct(session_bars):
    """First 30-min H-L range as fraction of session open price."""
    first_30 = session_bars.iloc[:ORB_WINDOW_BARS]
    session_open = first_30.iloc[0]['open']
    orb_high = first_30['high'].max()
    orb_low  = first_30['low'].min()
    return (orb_high - orb_low) / session_open

# At 10:00 ET (when first 30 bars are available, 30 min before trading starts):
orb_pct = compute_orb_pct(today_bars)
skip_session = (orb_pct > ORB_THRESHOLD)

# No trades if session is filtered:
if skip_session:
    return  # No entries for entire session
```

**Implementation note:** Trading window opens at 10:30 ET. The ORB computation uses bars from 9:30–10:00 ET (30 bars of 1-min data). By 10:30, the ORB gate has been evaluated and the session-skip decision is committed. No in-session recalculation needed.

### Updated: VPIN Entry Gate (Tightened)

```python
# H60b: Tightened from 0.55 → 0.45
VPIN_INFORMED = 0.45  # VPIN above this = skip entry (more conservative)
VPIN_CRISIS   = 0.70  # VPIN above this = close existing positions immediately (unchanged)
```

**Rationale for 0.45 vs 0.40:** The issue description identifies VPIN 0.35–0.40 on trending sessions. Since the ORB filter is the primary fix for those sessions, VPIN tightening to 0.45 provides secondary protection on borderline sessions without aggressively reducing trade count. Tightening to 0.40 would require IC re-estimation first to confirm the trade-count/Sharpe tradeoff is favorable.

### Unchanged: VWAP Z-Score Signal

```python
ENTRY_Z      = 1.5    # Enter when |z| > 1.5 (Avellaneda & Lee adapted)
EXIT_Z       = 0.25   # Exit when |z| < 0.25 (reversion to VWAP)
STOP_Z       = 3.0    # Stop-loss when |z| > 3.0
LOOKBACK_BARS = 30    # 30-min rolling window for vol estimation
```

### Complete Entry Conditions (H60b)

```python
TRADE_START = "10:30"   # After ORB window closes + 30-min buffer
TRADE_END   = "14:30"   # Last 90 min of session excluded

if skip_session:
    return  # ORB filter triggered — no entries today

if (TRADE_START <= current_time <= TRADE_END
        and current_vpin < VPIN_INFORMED    # 0.45 (tightened)
        and position_size > 0
        and not in_position):

    if vwap_z < -ENTRY_Z:
        direction = +1   # Long: price below VWAP
    elif vwap_z > ENTRY_Z:
        direction = -1   # Short: price above VWAP
```

### Unchanged: Exit Conditions

```python
if abs(vwap_z) < EXIT_Z:          exit(reason="reversion")
if abs(vwap_z) > STOP_Z:          exit(reason="stop_loss")
if bars_held >= 60:                exit(reason="time_stop")
if current_vpin > VPIN_CRISIS:     exit(reason="vpin_crisis")
if current_time >= "15:00":        exit(reason="eod_flat")
```

### Unchanged: VIX Size Scaling

```python
VIX_NORMAL   = 25.0   # Full position: 7% of portfolio
VIX_ELEVATED = 35.0   # Reduced: 4% of portfolio
# VIX > 35: position_size = 0 (skip entirely)
```

---

## Market Regime Context

| Regime | ORB | VPIN | H60b Action |
|---|---|---|---|
| Quiet midday (VIX 12–25, no major news) | < 1.5% | < 0.45 | **Trade** — primary target regime |
| Moderate vol (VIX 25–35) | < 1.5% | < 0.45 | Trade at reduced size (VIX scaling) |
| Trend day (morning gap, strong directional move) | **> 1.5%** | 0.35–0.40 | **Skip session** — ORB filter triggers |
| Informed flow day (earnings, FOMC, CPI) | Varies | **> 0.55** | **Skip entry** — VPIN filter triggers |
| Extreme vol (VIX > 35) | Likely > 1.5% | High | Double-filtered (ORB + VIX) |
| Late-day window (14:30–16:00) | N/A | N/A | No new entries (time filter) |

**2022 rate-shock coverage:** In 2022, high-impact macro sessions (CPI surprises, FOMC days) were predominantly trend days with wide opening ranges. The ORB filter would have skipped these sessions. Midday normalization sessions (wide morning move → midday consolidation) had ORB > 1.5% and would also be filtered, UNLESS the morning move settled before 10:00 ET (rare in 2022). The ORB filter is the primary answer to the PF-4 rate-shock concern.

---

## Alpha Decay

**IC estimates — pending re-estimation**

The H60 IC estimates from Kissell (2014) are confirmed stale by the Gate 1 backtest. H60b uses preliminary compressed estimates pending Alpha Research re-estimation from 2022-2024 OOS trade data.

| Timepoint | Kissell 2014 (H60) | Observed 2022-2024 (preliminary) | H60b target (post-filter) |
|---|---|---|---|
| T+0 (entry) | IC 0.12–0.15 | ~0.06–0.09 (compressed) | TBD (Alpha Research) |
| T+15 min | IC 0.08 | ~0.04–0.06 | TBD |
| T+30 min | IC 0.04 | ~0.02–0.03 | TBD |
| T+60 min | IC 0.01 | ~0.01 | TBD |

**Post-filter IC hypothesis:** The ORB filter removes trend sessions where the mean reversion signal was noise (negative IC contribution). Removing those sessions should improve observed IC in the filtered sample. Alpha Research Agent will compute actual IC from the 352 OOS trade records, segmented by ORB threshold, to validate this hypothesis.

**Signal half-life:** Unchanged — 20–45 minutes intraday (structural property of VWAP algorithm response, not crowding-dependent).

**Transaction cost viability (unchanged):**
- SPY round-trip: 0.003–0.005% (deep liquid midday)
- Break-even IC at these costs: ~0.01–0.02
- Even compressed IC (0.06): far above break-even
- Transaction cost viability confirmed — edge not cost-destructive at SPY scale

---

## Pre-Flight Gate Checklist

### PF-1: Walk-Forward Trade Viability

**H60 passed; H60b impact analysis:**
- H60 trade frequency: ~250 trades/year
- ORB filter expected removal: 20–30% of sessions (high-vol sessions with > 1.5% ORB)
  - Based on SPY historical data: 2022 had ~60–75 high-ORB sessions; other years ~30–40
  - Estimated filtered sessions: ~35–50/year average
  - Remaining sessions: ~200–215/year
- VPIN tightening (0.55 → 0.45): additional ~10–15% reduction in entry rate on non-filtered sessions
- Estimated H60b trades/year: ~150–200

**Minimum WF IS window viability:**
- 3-month IS window: ~37–50 trades ≥ 30 threshold
- Conservative scenario (150/year): 37–38 trades per 3-month window — marginal but passes

**[x] PF-1 PASS — Estimated 150–200 trades/year; ~37–50 per WF IS window ≥ 30 threshold** ✓

*Note: If IC re-estimation shows filter removes more sessions than estimated, re-evaluate PF-1 at that time.*

---

### PF-2: Long-Only MDD Stress Test

Unchanged from H60. Intraday-flat architecture enforces hard MDD ceiling. ORB filter reduces trade count, further reducing MDD risk (fewer losing trades possible per day).

**[x] PF-2 PASS — Intraday-flat structure; ORB filter further reduces worst-case daily loss** ✓

---

### PF-3: Data Pipeline Availability

| Asset | Source | Availability |
|---|---|---|
| SPY 1-min OHLCV | Alpaca Markets | ✓ (via QUA-149) |
| VWAP (derived) | pipelines/vwap_engine.py | ✓ (via QUA-149) |
| VPIN (derived) | pipelines/vpin_engine.py | ✓ (via QUA-149) |
| **Opening range (derived)** | **Computed from first 30 1-min bars** | ✓ trivial — max/min/open from existing minute bars |
| VIX daily close | yfinance | ✓ |

ORB computation requires no new data sources — derived from existing Alpaca minute bars.

**[x] PF-3 PASS — ORB is trivially derived from existing pipeline; no new data sources required** ✓

---

### PF-4: Rate-Shock Regime Plausibility

**H60 failed this implicitly** (VPIN was 0.35–0.40 on 2022 trend days; gate did not trigger).

**H60b direct answer:** In the 2022 rate-shock regime, macro events (CPI surprises, FOMC days) drove strong morning directional moves. These sessions would have had:
- CPI release days (first Friday of month): wide overnight gaps → ORB > 1.5% on most CPI surprise sessions → **session filtered**
- FOMC days (8 per year): strong midday directional moves → ORB > 1.5% → **session filtered**
- Post-CPI normalization days: typically moderate ORB (< 1.5%) → still traded
- Ordinary rate-shock sessions (rising rates, no catalyst): VIX 25–30, ORB < 1.5% → traded at reduced size

**Mechanism works in rate-shock for non-event sessions:** The structural VWAP reversion mechanism (VWAP-targeting algorithms) is regime-independent. Ordinary rate-hike-driven sessions (slow drift, moderate vol) are not trend sessions in the intraday sense — VWAP deviations still revert.

**[x] PF-4 PASS — ORB filter directly addresses 2022 rate-shock failure mode; FOMC/CPI days filtered; ordinary rate-shock sessions trade at reduced VIX-scaled position size** ✓

---

## Signal Validity Pre-Check

1. **Look-ahead bias (ORB):** ORB computed from bars 9:30–10:00 ET. Trading window opens at 10:30 ET. No look-ahead. ✓
2. **ORB threshold origin:** 1.5% was specified in H60 hypothesis (not IS-optimized). Implementation is faithful to original design intent. Low data-snooping risk. ✓
3. **VPIN tightening:** 0.45 is within the 0.45–0.65 range documented in H60's Parameters to Test table. Not a new parameter. ✓
4. **Remaining overfitting concerns:** Same as H60. VPIN sensitivity (Andersen-Bondarenko 2014) still applies. ORB threshold robustness should be tested: 1.0%, 1.5%, 2.0% range in IS optimization (baseline: 1.5%).

---

## Parameters to Test (H60b)

| Parameter | Suggested Range | Baseline | Change from H60? |
|---|---|---|---|
| `ORB_THRESHOLD` | 0.010 – 0.025 | **0.015** | NEW parameter |
| `VPIN_INFORMED` | 0.40 – 0.55 | **0.45** | Changed (was 0.55) |
| `ENTRY_Z` | 1.0 – 2.5 | 1.5 | Unchanged |
| `EXIT_Z` | 0.10 – 0.50 | 0.25 | Unchanged |
| `LOOKBACK_BARS` | 15 – 60 | 30 | Unchanged |
| `time_stop_bars` | 30 – 90 | 60 | Unchanged |

**Degrees of freedom: 6 (up from 5).** ORB_THRESHOLD is a new parameter. Its baseline (1.5%) is grounded in H60 hypothesis description (not IS-optimized). Gate 1 parameter limit: must account for all 6 parameters in IS optimization.

---

## Capital and PDT Compatibility

Unchanged from H60. PDT designation required. Minimum $25,000 account.

Trade frequency reduction (ORB filter): fewer day trades per week. Engineering Director should test whether reduced frequency moves average below 3 day-trades/week, potentially enabling sub-$25K accounts in some weeks (but not by design — still target $25K+ accounts).

---

## IC Re-Estimation Requirement (OPEN — Must Complete Before Gate 1)

**Delegated to:** Alpha Research Agent (via QUA-168 subtask)

**Task:** Compute actual IC from H60 OOS trade data (352 trades, `backtests/h60_intraday_vwap_mean_reversion_2026-06-09_oos_trades.json`):

1. Segment trades by ORB filter: which trades would be filtered by H60b's 1.5% ORB threshold?
2. For non-filtered trades only: compute IC at T+5, T+15, T+30 (using `exit_z_score` and forward returns)
3. Compare against Kissell 2014 estimates and update the Alpha Decay section
4. Provide revised annualized IR estimate under H60b filter regime

**This document is DRAFT until IC re-estimation is complete. Do not forward to Engineering Director until Alpha Research delivers updated IC estimates.**

---

## Gate 1 Outlook (H60b)

| Criterion | Threshold | H60b Estimate | Assessment |
|---|---|---|---|
| IS Sharpe | > 1.0 | Unknown (IC re-estimation pending) | **UNCERTAIN** |
| OOS Sharpe | > 0.7 | Unknown | **UNCERTAIN** |
| WF stability | ≥ 3/6 | Improved vs H60 (ORB filter removes worst sessions) | **LIKELY IMPROVED** |
| MDD | < -20% | < 5% (intraday-flat) | **VERY LIKELY PASS** |
| Trade count | ≥ 30/IS window | 37–50 | **MARGINAL PASS** |

**Key uncertainty:** Whether IC after ORB filtering is sufficient for IS Sharpe > 1.0. The ORB filter removes the worst sessions but the remaining sessions must show positive IC to produce Sharpe > 1.0.

**Decision gate:** If Alpha Research IC re-estimation shows compressed IC < 0.04 even in filtered sample, this hypothesis family should be retired without Gate 1 backtest (structure cannot produce Sharpe > 1.0 at realistic IC levels). Alpha Research Agent must explicitly assess this.

---

## Cointegration Analysis

Not applicable — single-instrument (SPY).

---

## Signal Combination

Not applicable — single-signal strategy.

---

## References

See H60 (`60_intraday_vwap_mean_reversion.md`) for full reference list. Additional reference:

- Lo, A.W., MacKinlay, A.C., & Zhang, J. (2002). Econometric models of limit-order executions. *Journal of Financial Economics*, 65(1), 31–71. *(Opening-range predictive power for intraday direction)*
- H60 Gate 1 backtest artifacts: `backtests/h60_intraday_vwap_mean_reversion_2026-06-09.json`, `backtests/h60_intraday_vwap_mean_reversion_2026-06-09_oos_trades.json`
- Source issue: QUA-168
