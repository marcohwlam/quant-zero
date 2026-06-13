# Gate 1 Acceptance Criteria (v2.6)

**Version:** 2.6
**Locked by:** CEO — 2026-06-13 ([QUA-234](/QUA/issues/QUA-234); Risk Director co-sign: [QUA-233](/QUA/issues/QUA-233))
**Status:** CEO-LOCKED
**Supersedes:** v2.4 (CEO-locked) for Track A swing/daily thresholds. Track B intraday thresholds unchanged.

---

## Horizon Selection Policy

Horizon (minute-level, daily, weekly) is **evidence-gated, not fixed by decree.**

- All horizons are eligible candidates for the strategy pipeline.
- A strategy's horizon is accepted if it meets the charter objective (CAGR ≥ 10%,
  MaxDD < −15%, net Sharpe > 0.8) after realistic costs at Gate 1.
- Minute-level held primary status by decree since v2.0. That exclusivity is removed.
  Minute-level loses exclusive primary status if realized live-vs-backtest slippage
  (measured by QUA-151) prevents minute-level strategies from meeting the charter
  constraints — in that case, daily/weekly strategies compete on equal footing.
- No horizon is auto-excluded. All compete on the same charter objective function.
  Track B (intraday) thresholds calibrated QUA-150 (2026-06-09). Track A (daily/weekly swing)
  thresholds calibrated QUA-232 (2026-06-13). See §Quantitative Thresholds for both sets.
- Decision authority: CEO, informed by QUA-151 slippage findings. See
  `docs/horizon-evidence-gate-decision-2026-06-09.md` for the rationale.

**Constraint:** this policy widens the eligible horizon set. It does not relax any
existing Gate 1 threshold, cost model, or architectural pre-flight requirement.

---

## Purpose

Gate 1 is the first quality checkpoint in the strategy promotion pipeline.
A strategy must pass Gate 1 before it is eligible for paper trading. For minute-level
submissions, the dominant failure mode is transaction cost, not curve-fitting — the
criteria reflect that. Daily/weekly submissions face the same output thresholds on a
bar-appropriate basis.

These criteria operationalize the company objective function defined in
`docs/objective-function-charter.md` (CEO-locked, QUA-154). The charter's portfolio-level
hard constraints (Net CAGR ≥ 10%, MaxDD < −15%, Net Sharpe > 0.8) govern all agent behavior;
the per-asset thresholds below are the strategy-level operationalization of those constraints.

---

## Required Test Period

| Parameter | Requirement | Rationale |
|-----------|-------------|-----------|
| Backtest window | 2 years: 2022-01 to 2024-12 | Covers rate-shock (2022) and normalization (2023-2024). |
| Walk-forward windows | 6 non-overlapping | 3-month in-sample / 1-month out-of-sample each. |
| Bar definition | Per asset class and horizon | Minute-level: 1-min equities RTH; 1-min crypto 24/7; 1-min futures session. Daily: EOD bars. Weekly: weekly close bars. |

---

## Cost Realism (top-level gate — the minute-level killer)

Backtests MUST model the following, or the strategy is auto-rejected:

| Asset | Cost model | Approx round-trip cost |
|-------|------------|------------------------|
| Equities | $0.005/share each side + 0.05% one-way slippage + `0.1×σ×sqrt(Q/ADV)` market impact (Almgren-Chriss, k=0.1) | ~10 bps (SPY/QQQ scale) |
| Crypto | 0.10% taker fee + 0.05% one-way slippage | ~30 bps |
| Futures | $2.10/contract/side (ES) or $0.37/contract/side (MES) + 1 tick slippage ($12.50/ES tick; $0.625/MES tick) | ~$29/contract (ES); ~$1.50 (MES) |

Cost model source: Engineering Director AGENTS.md canonical table (exchange fee schedules
+ Johnson *Algorithmic Trading & DMA* Table 3.2). Calibrated 2026-06-09 (QUA-150).

Net Sharpe is the only Sharpe that gates. Gross Sharpe is reported, never gates.

---

## Sharpe Annualization

- Aggregate intraday PnL to daily returns, then annualize with sqrt(252).
- Per-bar Sharpe is forbidden as a gate (it inflates with bar count).

---

## Strategy Architecture (pre-flight, PF-5)

The output thresholds below (Sharpe, MDD, cost) measure what happened. This section mandates
**what must be true before the backtest runs** — the construction discipline that prevents
structural failures from reaching output review.

Every Gate 1 submission must declare three layers per **PF-5** in
`docs/gate1-intake-process.md §0`:

| Layer | Requirement | Reference |
|-------|-------------|-----------|
| **Regime / risk filter** | Explicit stand-aside rule, OR documented justification for unconditional trading. Missing (a) without justification = auto-defer. | `research/filters/vpin_vix_regime_filter_spec.md` ([QUA-127](/QUA/issues/QUA-127)) |
| **Universe / liquidity filter** | Eligibility rules: spread, ADV, and cap/notional thresholds. | [QUA-128](/QUA/issues/QUA-128) |
| **Single alpha signal** | One directional signal, Harvey-Liu-Zhu deflated t > 3.0. No stacking. | [QUA-129](/QUA/issues/QUA-129) |

**Why this gates MDD, not just Sharpe:** strategies that lack a regime filter can participate
fully in bear markets regardless of signal quality — H49/H50/H51 all failed this way
(long-hold monthly rotation, MDD −30% to −51%, blew the −20% gate). The architecture
declaration catches that failure mode at intake, before compute is spent.

This section is additive — it does not relax any output threshold.

---

## Quantitative Thresholds (per asset class and horizon)

### Track B — Intraday (Minute-Level)

Calibrated from 2022-2024 empirical data (QUA-150, 2026-06-09). See
`docs/gate1-threshold-calibration-2026-06-09.md` for full derivation.
CEO-locked.

| Metric | Equities intraday | Crypto (BTC/ETH) | Futures (ES/MES) |
|---|---|---|---|
| Net OOS Sharpe (6-window aggregate) | > **0.7** | > **0.8** | > **0.7** |
| Net profit per trade (bps after cost) | > **5 bps** | > **8 bps** | > **0.5 ticks** |
| Max intraday/session MDD (CS threshold) | < **1.5%** acct equity | < **3.0%** acct equity | < **2.0%** acct equity |
| IS trade count (per 3-month window) | > **300** | > **200** | > **150** |
| Cost-to-gross-profit ratio | < **0.40** | < **0.35** | < **0.35** |

**Gate 7 hard ceiling (2× CS threshold) — Track B:**

| Asset | MDD hard gate ceiling |
|---|---|
| Equities intraday | < **3.0%** of account equity (per session) |
| Crypto | < **6.0%** of account equity (per 24h) |
| Futures | < **4.0%** of account equity (per session) |

The objective function for Track B is defined in `docs/kpi-minute-level.md` **v0.3
(CEO-locked 2026-06-07, QUA-68)**. That document is authoritative for the composite score
formula, hard gate definitions, and per-asset KPI specifications.

---

### Track A — Swing/Daily (US Equities Only)

Calibrated from 2022-2024 daily-bar empirical data (QUA-232, 2026-06-13). See
`docs/gate1-threshold-calibration-swing-2026-06-13.md` for full derivation.
**CEO-LOCKED 2026-06-13** — Risk Director co-signed [QUA-233](/QUA/issues/QUA-233); CEO locked [QUA-234](/QUA/issues/QUA-234). Binding immediately.

Track A strategies use the same cost model as Track B (see §Cost Realism). MDD scope differs:
Track A measures peak-to-trough equity drawdown over the IS period (multi-day basis), not per session.

| Metric | Equities swing/daily |
|---|---|
| Net OOS Sharpe (6-window aggregate) | > **0.7** |
| Net profit per trade (bps after cost) | > **15 bps** |
| MDD (peak-to-trough, IS period, CS threshold) | < **20%** acct equity |
| IS trade count (per 3-month window) | > **30** |
| Cost-to-gross-profit ratio | < **0.25** |

**Gate 7 hard ceiling (2× CS threshold) — Track A:**

| Asset/Horizon | MDD hard gate ceiling |
|---|---|
| Equities swing/daily | < **30%** of account equity (IS period) |

**Track A KPI document:** `docs/kpi-daily-weekly.md` — pending delivery. Until that document
is CEO-locked, the composite score formula is not binding; only the hard gate thresholds
above apply to Track A submissions.

**Full-backtest MDD disclosure (narrative, not auto-reject gate):** The 20% IS-period CS threshold
applies per 3-month walk-forward window. In addition, the hypothesis narrative submission must
report full-backtest MDD across the 2022–2024 window. This is a portfolio-level charter constraint
(MaxDD < −15%), not a per-strategy auto-reject at Gate 1 — but reviewers require visibility.

**Track A overnight/weekend guards** (replaces flat-by-close; see §Swing/Daily-Specific Guards below).

---

## Minute-Level-Specific Guards (Track B)

- Latency: signal-to-fill delay >= 1 bar (no same-bar fills).
- Overnight: explicit flat-by-close OR documented overnight risk.
- Look-ahead: no use of a bar's own close before the bar completes.
- Intraday regime: report performance split by session (open / midday / close).

---

## Swing/Daily-Specific Guards (Track A)

Track A strategies hold overnight and over weekends by design. These guards replace the
Track B flat-by-close requirement. Failure to document = auto-defer (same as missing regime
filter under PF-5).

- **Overnight gap documentation:** Report average overnight gap contribution to total PnL and MDD.
- **Weekend risk disclosure:** Quantify weekend gap exposure as % of position notional and
  expected MDD contribution.
- **Earnings gap policy:** Document whether strategy holds through earnings. If yes, max
  position size per earnings-holding position ≤ 5% of account equity.
- **Gap MDD attribution:** Report fraction of max drawdown attributable to gap events
  (overnight/weekend) vs. intraday/session moves.
- **Look-ahead:** no use of bar's own close before bar completes (same as Track B).

---

## Per-Asset KPI Spec

**Track B:** See `docs/kpi-minute-level.md` v0.3 — CEO-locked 2026-06-07 ([QUA-68](/QUA/issues/QUA-68)).  
Hard gates 1–8 (including Gate 8 PDT compliance for equities intraday) are defined there.

**Track A:** See `docs/kpi-daily-weekly.md` — pending delivery by Quant Metrics Agent.
Until CEO-locked, only the hard gate thresholds in §Track A above apply to swing submissions.

---

## Automatic Disqualification (any single flag = reject)

Full Track B hard gate list is in `docs/kpi-minute-level.md` §Hard Gates (Gates 1–8). Summary (applies to both tracks unless noted):

- Net OOS Sharpe below the horizon/asset threshold (Track A: < 0.7; Track B: per asset class above).
- Same-bar fill assumption (latency cheating).
- Cost-to-profit ratio above the asset/horizon ceiling.
- Profitable gross but unprofitable net.
- Look-ahead bias detected (rewrite and re-test from scratch).
- IS trade count below floor (Track A: < 30; Track B: per asset class above).
- MDD exceeds absolute ceiling (Track A: > 30% IS period; Track B: > 2× CS per session).
- **PDT-incompatible design (US equities intraday, margin accounts)** — requires >3 day trades per 5 rolling days. *(Gate 8, CEO ruling F3, 2026-06-07)* Track B only; Track A swing strategies are PDT-exempt by holding-period design.
- **Track A overnight guards not documented** — auto-defer if overnight gap, weekend risk, earnings policy, or gap MDD attribution is missing.

---

## Governance

- Only the CEO modifies these criteria, after a documented review with rationale.
- Any change is versioned (increment version, preserve prior version in git history).
- PLACEHOLDER thresholds are filled only with data-backed calibration, then CEO-locked.
- Relaxing criteria requires higher justification than tightening.

### Version History

| Version | Date | Change | Rationale |
|---------|------|--------|-----------|
| 1.0–1.3 | 2026-03 | Daily/swing criteria | Preserved in git history. |
| 2.0 | 2026-06-06 | Rewrite for minute-level, all assets | Company pivot to minute-level trading; cost realism promoted to top-level gate; thresholds deferred to data calibration. |
| 2.0.1 | 2026-06-07 | Reference `docs/kpi-minute-level.md` v0.3 (CEO-locked). Added Gate 8 (PDT) to auto-disqualification summary. KPI doc is the authoritative objective function. | CEO — [QUA-68](/QUA/issues/QUA-68) |
| 2.1 | 2026-06-09 | Add "Strategy Architecture" section encoding the three-layer construction discipline (regime filter / universe filter / single alpha) as a binding pre-flight requirement (PF-5). Add PF-5 auto-defer rule to `docs/gate1-intake-process.md`. Output thresholds unchanged. Motivation: H49/H50/H51 monthly-rotation dead-end — all failed MDD gate due to absent regime filter; structural failure now caught at intake not output. | CEO — [QUA-144](/QUA/issues/QUA-144) |
| 2.2 | 2026-06-09 | Replace all TBD/PLACEHOLDER thresholds with data-backed calibrated values for all three asset classes (equities intraday, crypto, futures). Replace PLACEHOLDER cost model with AGENTS.md canonical (exchange fee schedules + Almgren-Chriss impact). Full derivation in `docs/gate1-threshold-calibration-2026-06-09.md`. | Engineering Director — [QUA-150](/QUA/issues/QUA-150) |
| 2.3 | 2026-06-09 | Horizon is evidence-gated, not fixed by decree. Remove minute-level exclusivity. Re-admit daily/weekly as eligible candidates on equal footing. Add Horizon Selection Policy section. Bar definition made horizon-adaptive. All thresholds unchanged. Decision rationale: `docs/horizon-evidence-gate-decision-2026-06-09.md`. Triggered by QUA-151 slippage findings. | CEO — [QUA-156](/QUA/issues/QUA-156) |
| 2.4 | 2026-06-09 | Add explicit reference to `docs/objective-function-charter.md` (QUA-154) in §Purpose. Criteria already aligned; change is documentary — makes the charter → criteria chain of authority explicit. | CEO — [QUA-154](/QUA/issues/QUA-154) |
| 2.5 | 2026-06-09 | §Dual-Track Applicability: Gate 1 governs both Track A (daily/weekly) and Track B (minute-level). Track A thresholds marked PENDING calibration. | CEO — [QUA-230](/QUA/issues/QUA-230) |
| 2.6 | 2026-06-13 | Add calibrated Track A swing/daily equities thresholds. Separate quantitative threshold table into Track A and Track B sections. Add §Swing/Daily-Specific Guards. Add overnight guards to auto-disqualification. Cost model unchanged. Full calibration derivation: `docs/gate1-threshold-calibration-swing-2026-06-13.md`. Risk Director co-sign: [QUA-233](/QUA/issues/QUA-233). | CEO — [QUA-234](/QUA/issues/QUA-234) (Research Director calibration: [QUA-232](/QUA/issues/QUA-232)) |
