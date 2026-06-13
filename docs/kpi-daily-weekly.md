# Daily/Weekly (Track A) KPI Objective Function — v1.0

**Status:** CEO-LOCKED — 2026-06-13 ([QUA-238](/QUA/issues/QUA-238))
**Version:** 1.0
**Author:** Engineering Director (QUA-236)
**Date:** 2026-06-13
**Referenced by:** `criteria.md` §Per-Asset KPI Spec (Track A)
**Governance:** This document becomes the authoritative objective function for Track A Gate 1 upon CEO lock. No modifications without CEO-approved PR and Risk Director co-sign.

---

## Purpose

This document defines the objective function that balances **return** and **stability** for
Track A (daily/weekly swing-to-position) strategy evaluation — US equities only at this revision.

At daily/weekly resolution, the dominant failure mode is **unfiltered drawdown in adverse
regimes**. Three consecutive failures (H49/H50/H51: monthly-rotation strategies, MDD −30% to
−51%) confirmed this empirically. A strategy that participates fully in bear markets regardless
of signal quality is structurally incompatible with the company charter (MaxDD < −15%,
QUA-154). This shifts the objective function relative to Track B: **drawdown control is
primary; cost drag is secondary** because per-trade costs are already a small fraction of
multi-day gross moves (CPR < 0.25 hard gate pre-screens the cost dimension).

Track A strategies source from the J Law lineage (`docs/knowledge/trading-methodology-jlaw-lineage.md`):
O'Neil CAN SLIM, Minervini SEPA/VCP/Trend Template, Weinstein Stage 2 analysis, Darvas boxes.
These archetypes share: multi-week holding periods (5–30 trading days), built-in regime filters,
equity universe scanning, and hard stop discipline. The objective function is calibrated to
admit well-designed implementations of these archetypes while rejecting under-filtered or
over-fitted variants.

---

## Core Objective Function

The objective is to maximize a composite score (CS) that rewards net risk-adjusted return,
controls multi-day drawdown, penalizes cost drag, and ensures statistical adequacy:

```
CS = 0.40 × NetSharpe_norm
   + 0.30 × Stability_norm
   + 0.20 × ProfitPerTrade_norm
   + 0.10 × TradeAdequacy_norm
```

### Component Definitions

| Component | Weight | Formula | Rationale |
|---|---|---|---|
| `NetSharpe_norm` | 40% | Normalized Net OOS Sharpe (post-cost, annualized via daily equity curve → sqrt(252)) | Primary return-quality signal. Net-only; gross Sharpe is diagnostic, never gates. |
| `Stability_norm` | 30% | `max(0, 1 − ‖MDD_IS‖ / MDD_ceiling)` — inverted drawdown score | **Elevated from 20% (Track B).** At swing horizon, the dominant failure mode is runaway drawdown in bear markets, not cost drag. H49/H50/H51 case study. |
| `ProfitPerTrade_norm` | 20% | Normalized net profit per trade in bps after all costs | **Reduced from 30% (Track B).** CPR < 0.25 hard gate pre-screens cost efficiency. Swing trades capture multi-day directional moves; above the floor, PpT is less discriminating. |
| `TradeAdequacy_norm` | 10% | `min(1.0, TradeCount_IS / min_trades_floor)` — capped at 1.0 | Ensures statistical power. At daily frequency, statistical adequacy is more demanding per trade. |

### Weight Justification

**Why MDD/Stability at 30% (not 20% as in Track B):**
- Track B dominant failure mode: cost destruction — PpT at 30% weight directly combats it.
- Track A dominant failure mode: bear-market drawdown — MDD at 30% weight directly combats it.
- With CPR < 0.25 as a hard gate, cost coverage is already binary-screened. Elevating PpT
  to 30% at swing scale would over-reward a dimension that is less discriminating (clearing
  15 bps net PpT over a multi-day hold is structurally easier than clearing 5 bps over
  hundreds of intraday trades). Re-weighting toward MDD closes the H49/H50/H51 failure mode.

**Why PpT at 20% (not 30% as in Track B):**
- At minute scale, costs are ~30–40% of gross PpT (CPR 0.30–0.40 is common); PpT is highly
  discriminating. At swing scale, costs are ≤ 25% of gross PpT by hard gate. Margins above
  the 15 bps floor are large; gradation in PpT adds less signal than gradation in MDD control.
- PpT still gates: strategies at 15 bps net are barely above cost noise (25 bps gross, or
  a 0.25% directional move over the full hold). The CS weight rewards meaningful improvement
  above that floor.

**Normalization:** Each component is min-max normalized to [0, 1] against the Track A
calibration range. Calibration values populated 2026-06-13 (QUA-236) — see
§Composite Score Normalization Reference and `docs/gate1-threshold-calibration-swing-2026-06-13.md`.

**Pass threshold:** CS ≥ 0.60 is the Gate 1 composite pass bar (same as Track B; consistent
with the calibration protocol target of admitting viable strategies from the 60th percentile
of the expected distribution).

---

## Hard Gates (any single flag = reject regardless of CS)

These operate before the composite score is computed:

1. **Net OOS Sharpe < 0.7** — composite score irrelevant if net edge is below floor.
2. **CPR ≥ 0.25** — strategy is economically non-viable at swing scale (costs > 25% of gross
   profit from winning trades). At multi-day holding periods, this signals inadequate
   directional capture, not just cost drag.
3. **Same-close execution assumption** — filling at the closing price of the day on which the
   signal was generated constitutes look-ahead. Swing signals (CAN SLIM breakout, VCP pivot,
   Stage 2 breakout) are generated using the day's closing price; the fill must occur on the
   **next trading day** (market open, or a pre-specified stop-buy limit). Automatic disqualification.
4. **Look-ahead bias detected** — any use of future data in signal construction: rewrite and
   re-test from scratch. This includes using the breakout day's high/low to set a stop that
   could not have been placed before the bar completed.
5. **Gross-profitable but net-negative** — no exceptions; cost model is non-negotiable.
6. **IS trade count ≤ 30 per 3-month window** — statistical adequacy is binary. Fewer than
   30 trades in an IS window produces Sharpe estimates with too-wide confidence intervals to
   be actionable. Note: PF-1 pre-flight requires IS trades ≥ 120 per window; PF-1 is the
   binding operational gate. The 30-trade floor defines the statistical concept.
7. **MDD > 30% peak-to-trough in any IS window (Gate 7 ceiling)** — a strategy scoring 0.0
   on MDD can still pass CS ≥ 0.60 via NetSharpe + PpT alone. Gate 7 prevents structurally
   unsafe strategies from reaching paper trading. Ceiling = 2× the MDD CS threshold (20%).
   Any single IS window exceeding 30% MDD is a charter violation regardless of aggregate CS.
8. **Overnight/weekend guards not documented → AUTO-DEFER** — Track A strategies hold multi-day
   by design. The following disclosures are required (criteria.md §Swing/Daily-Specific Guards);
   missing any one = return to Strategy Coder for documentation:
   - Overnight gap contribution to total PnL and MDD reported.
   - Weekend gap exposure quantified as % of position notional.
   - Earnings hold policy declared (if holding through earnings: position ≤ 5% of account).
   - Gap MDD attribution reported (gap events vs. intraday/session moves).
9. **Survivorship-biased universe → AUTO-DEFER** — if the backtest universe uses current S&P
   500 / Russell 2000 constituents without historical delistings, return to Strategy Coder.
   Strategies that never held stocks that were eventually delisted have artificially suppressed
   drawdowns. Either (a) use a point-in-time universe, or (b) explicitly document the choice
   and its bias direction with a sensitivity estimate.

---

## Track A KPI Specification — US Equities Swing/Daily

**Session:** Daily bars (EOD), US equities only. RTH reference: NYSE/NASDAQ regular hours.
**Execution timing:** Signal generated at EOD close → fill at next-day open (or pre-set stop-buy
limit). No same-close fills on breakout signals.
**Cost model:** $0.005/share each side + 0.05% one-way slippage + `0.1 × σ × sqrt(Q/ADV)`
Almgren-Chriss market impact. Same model as Track B; per-trade cost is lower fraction of gross
at daily scale. Full derivation: `docs/gate1-threshold-calibration-swing-2026-06-13.md` §3.
**MDD scope:** Peak-to-trough drawdown of the strategy equity curve over the full IS period
(3-month window). NOT per-session; multi-day position carries overnight/weekend exposure.
**Universe eligibility:** J Law lineage strategies target US equities with adequate liquidity.
Minimum thresholds: ADV ≥ 200K shares/day, market cap ≥ $500M (or explicit justification for
smaller-cap mandate). Liquidity flag applies: Q/ADV > 1% must be flagged.

| KPI | Symbol | Gate Role | Threshold | Rationale |
|---|---|---|---|---|
| Net OOS Sharpe (6-window aggregate) | `NetSharpe_sw` | Hard gate + CS component | > **0.7** | HLZ deflated SR floor + 6 OOS windows (126 trading days); SE ≈ 1.41; P40 of viable swing strategy distribution. Full derivation: calibration doc §4.1. |
| Net profit per trade (bps after cost) | `PpT_sw` | Hard gate + CS component | > **15 bps** | 3× intraday floor. RT cost ≈ 10 bps; 15 bps net → gross PpT > 25 bps (0.25% directional move minimum). Strategies below this are indistinguishable from execution noise over multi-day holds. Full derivation: calibration doc §4.2. |
| MDD (peak-to-trough, IS period) | `MDD_sw` | Hard gate (Gate 7) + CS component | CS threshold: < **20%** of account equity. Gate 7 hard ceiling: < **30%**. | Charter-calibrated: portfolio MaxDD < −15% (QUA-154); filtered swing strategy should stay within 20% in worst-case 3-month window (2022 Q2 benchmark: SPY −17%, filtered strategy materially better). Full derivation: calibration doc §4.3. |
| IS trade count (per 3-month window) | `TC_sw` | Hard gate | > **30** | Statistical minimum for daily-bar Sharpe estimation; de Prado (2018) 30-observation floor for t-stat > 2 at SR=0.5. PF-1 operational floor (≥ 120/window) supersedes this in practice. Full derivation: calibration doc §4.4. |
| Cost-to-gross-profit ratio | `CPR_sw` | Hard gate | < **0.25** | More strict than intraday (0.40); swing trades capture multi-day directional moves, so costs must be a smaller fraction. CPR < 0.25 → gross winners > 40 bps average; consistent with PpT floor (self-consistent: 15 bps / (15/0.75) bps gross = 0.25). Full derivation: calibration doc §4.5. |

**Secondary diagnostics (non-gating, report only):**
- Regime split: performance in 2022 (rate-shock/bear) vs. 2023-2024 (bull). Strategies relying
  entirely on bull-market returns without drawdown control in 2022 are discouraged from
  promotion even if aggregate OOS Sharpe passes.
- Hold period distribution: mean, P25, P75 of holding periods in trading days. Documents whether
  the strategy is genuinely swing-to-position (5–30 days) or degenerating to near-intraday
  (< 2 days average hold).
- Overnight gap contribution: % of total PnL and % of total MDD attributable to gap events.
  Required by Hard Gate 8 disclosures; duplicated here for structured reporting.
- Sector concentration: is more than 50% of IS trades concentrated in one GICS sector?
  Document if yes — not a reject, but a risk flag for portfolio construction.
- Consecutive loss analysis: maximum consecutive losing trades and peak drawdown per losing streak.
- Win rate: expected > 40% for momentum strategies (right-tail gains offset left-tail losses).

**J Law lineage archetype applicability:**

| Archetype | Expected IS Sharpe range | Expected PpT range | Notes |
|---|---|---|---|
| Weinstein Stage 2 breakout (filters Stage 3/4/1) | 0.7–1.3 | 20–80 bps | Regime filter naturally avoids bear markets; CPR should be 0.05–0.15. |
| Minervini SEPA + VCP | 0.8–1.5 | 30–120 bps | Hard stop discipline limits drawdown; typical hold 5–20 days. |
| O'Neil CAN SLIM | 0.7–1.2 | 20–80 bps | Earnings exposure policy required; universe = leading stocks at ATH-near. |
| Darvas Box breakout | 0.6–1.0 | 15–60 bps | Lowest trade count; box formation requires patience. |

Strategies that fall below the lower bound of the expected range for their archetype warrant
additional review — the signal may be degraded by over-parameterization.

---

## Metric Rationale vs. Alternatives Considered

| Metric | Chosen | Alternative Considered | Why Chosen |
|---|---|---|---|
| **Net OOS Sharpe** | Yes | Gross OOS Sharpe | Gross ignores cost. Even at daily scale, a strategy with gross Sharpe 2.0 can be net 0.5 if CPR is high. Gross is reported but never gates. |
| **Profit per trade (bps)** | Yes | Profit factor (gross profit / gross loss) | PpT is cost-anchored; profit factor is not. PpT answers "does each trade cover costs with meaningful margin?" — essential even at swing scale. |
| **Peak-to-trough IS period MDD** | Yes | Per-session MDD | Per-session MDD is nonsensical for multi-week holds. IS period MDD captures the cumulative drawdown over the full holding-period window, including overnight/weekend gaps. |
| **IS trade count floor** | Yes | OOS trade count | IS trade count is observable before the split; governs whether IS statistics are trustworthy. OOS trade count is a secondary diagnostic. |
| **Cost-to-gross-profit ratio** | Yes | Net margin % | Cost ratio is strategy-agnostic and isolates whether gross moves are sufficiently above cost noise. Net margin % depends on position sizing and compresses the cost signal. |
| **MDD/Stability at 30% CS weight** | Yes | PpT at 30% (Track B weighting) | Track A dominant failure mode is drawdown, not cost. Re-weighting toward MDD closes the most common Track A failure mode (H49/H50/H51). PpT is pre-screened by CPR hard gate. |
| **CS pass threshold ≥ 0.60** | Yes | ≥ 0.70 | Consistent with Track B. 0.60 represents the 60th percentile of the expected viable strategy distribution at the normalization calibration points. Raising to 0.70 would reject genuinely viable strategies with moderate (but acceptable) MDD profiles. |

---

## Calibration Protocol

All threshold values were calibrated against 2022–2024 daily-bar empirical data per QUA-236
(2026-06-13), using the same methodology as QUA-150 (Track B calibration):

1. **Engineering Director** ran a calibration sweep using RSI(2) as a weak baseline on a
   5-stock proxy universe (SPY, QQQ, IWM, AAPL, MSFT), same as QUA-150. Full derivation:
   `docs/gate1-threshold-calibration-swing-2026-06-13.md`.
2. Key finding: daily bars are the *native* data frequency for Track A, requiring no adjustment
   factors (unlike QUA-150's minute-level calibration, which required daily-to-minute scaling).
3. **Thresholds set at 40th percentile** of the expected viable strategy distribution (gate
   rejects bottom 40% of well-designed strategies; same protocol as Track B).
4. **J Law lineage archetypes** inform the expected performance range (§Track A KPI Specification
   above); thresholds calibrated to admit the lower bound of credible Minervini/Weinstein
   implementations.
5. **Risk Director co-sign:** required before final CEO lock.
6. **CEO locks** composite score and weights into this document on PR merge; simultaneously
   resolves the "pending delivery" note in `criteria.md` §Per-Asset KPI Spec.

**Re-calibration triggers:** (a) First 5 Track A strategies reviewed under these thresholds;
(b) annual re-lock per governance calendar; (c) major market regime change (new rate cycle,
systematic Vol regime shift); (d) Track A thresholds show persistent Pass/Fail asymmetry
(all pass or all fail → thresholds are miscalibrated).

---

## Composite Score Normalization Reference

Calibrated 2026-06-13 (QUA-236). Min = floor (score → 0.0); Max = excellent (score → 1.0, capped).
MDD: Min is the CS threshold value (score = 0.0 at CS threshold; Gate 7 ceiling strategies
are rejected before CS computation).

| KPI | Min (0.0 score) | Max (1.0 score) | Note |
|---|---|---|---|
| `NetSharpe_sw` | −0.5 | 2.0 | Same range as Track B equities. |
| `PpT_sw` (bps) | 0.0 | 100.0 | 100 bps net ≈ 1% per trade average; represents excellent swing edge (10× the gate floor). |
| `MDD_sw` (%) | −20% (CS threshold) | 0.0% | 0% drawdown = perfect stability. Scores 0 at CS threshold; Gate 7 ceiling (30%) = hard reject. |
| `TradeCount_IS` | 30 (floor) | 200 | 200 trades/3-month window ≈ 15 trades/week on a 20-50 stock universe; excellent activity. |

**Normalization formula for each component:**

```
NetSharpe_norm   = clip((NetSharpe_OOS − (−0.5)) / (2.0 − (−0.5)), 0, 1)
PpT_norm         = clip(PpT_bps / 100.0, 0, 1)
Stability_norm   = clip(1 − |MDD_IS| / 0.20, 0, 1)
TradeAdequacy_norm = min(1.0, TradeCount_IS / 30)
```

**Example computations:**

| Strategy | NetSharpe | PpT | MDD_IS | IS Trades | CS |
|---|---|---|---|---|---|
| Excellent VCP | 1.4 | 60 bps | −8% | 120 | 0.40×0.76 + 0.30×0.60 + 0.20×0.60 + 0.10×1.0 = 0.304 + 0.180 + 0.120 + 0.100 = **0.70** |
| Borderline CAN SLIM | 0.75 | 18 bps | −18% | 35 | 0.40×0.50 + 0.30×0.10 + 0.20×0.18 + 0.10×1.0 = 0.200 + 0.030 + 0.036 + 0.100 = **0.37** (FAIL) |
| Good Weinstein | 1.0 | 35 bps | −12% | 80 | 0.40×0.60 + 0.30×0.40 + 0.20×0.35 + 0.10×1.0 = 0.240 + 0.120 + 0.070 + 0.100 = **0.53** (FAIL — just below 0.60) |
| Strong Weinstein | 1.1 | 40 bps | −10% | 90 | 0.40×0.64 + 0.30×0.50 + 0.20×0.40 + 0.10×1.0 = 0.256 + 0.150 + 0.080 + 0.100 = **0.59** (just below) |
| Solid Minervini | 1.2 | 50 bps | −10% | 100 | 0.40×0.68 + 0.30×0.50 + 0.20×0.50 + 0.10×1.0 = 0.272 + 0.150 + 0.100 + 0.100 = **0.62** (PASS) |

*Observation: strategies with > 10% IS MDD need either strong NetSharpe (> 1.0) or very high
PpT (> 40 bps) to clear CS ≥ 0.60. This reflects the deliberate elevation of MDD weight.*

---

## Risk Director Co-Sign (v1.0 review)

**Verdict: UNCONDITIONAL CO-SIGN**
**Risk Director:** Risk Director Agent (QUA-237)
**Date:** 2026-06-13

### Five Key Decisions — Sign-Off

**1. Composite score weights (40/30/20/10)**
APPROVED. Weight inversion vs Track B (40/20/30/10 → 40/30/20/10) is empirically justified.
H49/H50/H51 confirmed bear-market drawdown as the dominant Track A failure mode, not cost drag.
CPR < 0.25 hard gate pre-screens cost efficiency; elevating PpT to 30% at swing scale would
over-reward a dimension already binary-screened. MDD at 30% directly closes the failure mode.

**2. MDD CS threshold 20% / Gate 7 ceiling 30%**
APPROVED. Consistent with CEO-locked `criteria.md` v2.6 (QUA-234). Charter constraint
(MaxDD < −15%) is portfolio-level; per-strategy 20% gate provides adequate margin:
Risk Constitution Rule 2 caps each strategy at 25% capital → max portfolio MDD contribution
from a single strategy at peak = 0.20 × 0.25 = 5.0% of portfolio equity. Multi-strategy
correlation effects are handled by Portfolio Monitor. Gate 7 ceiling at 30% (2× CS threshold)
correctly prevents CS gaming via offsetting NetSharpe/PpT when MDD is structurally unsafe.

**3. Same-close fill prohibition (Hard Gate 3)**
APPROVED. Structurally identical to Track B's same-bar fill prohibition. Swing signals
(CAN SLIM breakout, VCP pivot, Stage 2 breakout) are generated using the day's closing price;
same-close fill requires knowing the close before it completes — classic look-ahead. Next-day
open or pre-set stop-buy limit is the correct Track A latency gate. Auto-disqualification is
the right severity (mirrors criteria.md §Automatic Disqualification).

**4. Survivorship bias auto-defer (Hard Gate 9)**
APPROVED as auto-defer (not hard reject). Bias is fixable via (a) point-in-time universe
or (b) documented sensitivity estimate with quantitative bias direction assessment. Hard reject
would be disproportionate for a correctable data quality issue with a known bias direction
(suppresses drawdown, inflates Sharpe). Reviewer note: "sensitivity estimate" in option (b)
must be quantitative — a qualitative directional statement alone is insufficient to satisfy
this gate.

**5. CS pass threshold = 0.60**
APPROVED. Consistent with Track B calibration protocol (admit 60th percentile of viable
strategies). Normalization examples verified: all five worked examples compute correctly.
Threshold is correctly tight — "Good Weinstein" at CS 0.53 and "Strong Weinstein" at CS 0.59
both fail, reflecting the deliberate MDD weight elevation. Raising to 0.70 would reject
strategies with acceptable (10%–15%) MDD profiles that compensate with strong NetSharpe.

### Normalization Verification

All five worked examples in §Composite Score Normalization Reference verified independently:
- Excellent VCP: 0.304 + 0.180 + 0.120 + 0.100 = **0.704** ✓
- Borderline CAN SLIM: 0.200 + 0.030 + 0.036 + 0.100 = **0.366** ✓
- Good Weinstein: 0.240 + 0.120 + 0.070 + 0.100 = **0.530** ✓
- Strong Weinstein: 0.256 + 0.150 + 0.080 + 0.100 = **0.586** ✓
- Solid Minervini: 0.272 + 0.150 + 0.100 + 0.100 = **0.622** ✓

### Minor Clarifications (non-blocking)

1. TradeAdequacy normalization table lists Max = 200 trades, but the operative formula
   `min(1.0, TradeCount_IS / 30)` scores 1.0 at any count ≥ 30. The table max is
   informational; the formula is correct and the document's "statistical adequacy is binary"
   framing accurately describes the intent.

2. Gate 9 auto-defer option (b) requires a *quantitative* sensitivity estimate
   (e.g., "survivorship bias inflates IS Sharpe by +0.1 to +0.3 based on X% delisting
   rate"). Qualitative directional statements do not satisfy this gate.

### Charter Alignment Assessment

Track A KPI objective function is consistent with `docs/objective-function-charter.md`
(QUA-154). MDD weight elevation and Gate 7 ceiling directly operationalize the MaxDD < −15%
portfolio constraint at strategy level. CS pass threshold and normalization calibration target
strategies that can plausibly contribute to the portfolio Sharpe > 0.8 objective.

**Escalation to CEO for final lock is authorized.**

---

## CEO Lock

**Locked by:** CEO — 2026-06-13 ([QUA-238](/QUA/issues/QUA-238))

Governance chain verified:
- Authored by Engineering Director (QUA-236)
- Risk Director co-sign: UNCONDITIONAL (QUA-237)
- CEO lock: complete

`docs/kpi-daily-weekly.md` v1.0 is hereby the authoritative Track A composite objective function. The composite score formula, weights (40/30/20/10), hard gates (1–9), normalization reference, and CS pass threshold (≥ 0.60) are binding immediately for all Track A Gate 1 submissions. No modification without CEO-approved PR and Risk Director co-sign.

---

## Version History

| Version | Date | Change | Author |
|---|---|---|---|
| 1.0 | 2026-06-13 | Initial document — Track A composite objective function, hard gates, per-archetype KPI spec, normalization reference, metric rationale. Thresholds sourced from `docs/gate1-threshold-calibration-swing-2026-06-13.md` (CEO-locked 2026-06-13, QUA-234). Risk Director co-sign: QUA-237 (UNCONDITIONAL). CEO-locked: QUA-238. | Engineering Director — QUA-236; CEO — QUA-238 |
