# Gate 1 Acceptance Criteria (v2.4)

**Version:** 2.4
**Locked by:** CEO
**Status:** CEO-LOCKED
**Supersedes:** v1.3 (daily/swing) for quantitative thresholds. Daily/weekly horizon
re-admitted as eligible candidates (v2.3); prior daily-track backtests not retroactively re-run.

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
- No horizon is auto-excluded. All compete on the same charter objective function
  and the same calibrated Gate 1 thresholds (QUA-150, 2026-06-09).
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

## Quantitative Thresholds (per asset class)

Calibrated from 2022-2024 empirical data (QUA-150, 2026-06-09). See
`docs/gate1-threshold-calibration-2026-06-09.md` for full derivation.
CEO-locked on PR merge. Setting numbers without data violates the data-driven rule.

| Metric | Equities intraday | Crypto (BTC/ETH) | Futures (ES/MES) |
|---|---|---|---|
| Net OOS Sharpe (6-window aggregate) | > **0.7** | > **0.8** | > **0.7** |
| Net profit per trade (bps after cost) | > **5 bps** | > **8 bps** | > **0.5 ticks** |
| Max intraday/session MDD (CS threshold) | < **1.5%** acct equity | < **3.0%** acct equity | < **2.0%** acct equity |
| IS trade count (per 3-month window) | > **300** | > **200** | > **150** |
| Cost-to-gross-profit ratio | < **0.40** | < **0.35** | < **0.35** |

**Gate 7 hard ceiling (2× CS threshold):**

| Asset | MDD hard gate ceiling |
|---|---|
| Equities intraday | < **3.0%** of account equity (per session) |
| Crypto | < **6.0%** of account equity (per 24h) |
| Futures | < **4.0%** of account equity (per session) |

The objective function that balances return and stability across these metrics is defined in
`docs/kpi-minute-level.md` **v0.3 (CEO-locked 2026-06-07, QUA-68)**. That document is authoritative
for the composite score formula, hard gate definitions, and per-asset KPI specifications.

---

## Minute-Level-Specific Guards

- Latency: signal-to-fill delay >= 1 bar (no same-bar fills).
- Overnight: explicit flat-by-close OR documented overnight risk.
- Look-ahead: no use of a bar's own close before the bar completes.
- Intraday regime: report performance split by session (open / midday / close).

---

## Per-Asset KPI Spec

See `docs/kpi-minute-level.md` v0.3 — CEO-locked 2026-06-07 ([QUA-68](/QUA/issues/QUA-68)).  
Hard gates 1–8 (including Gate 8 PDT compliance for equities intraday) are defined there.

---

## Automatic Disqualification (any single flag = reject)

Full hard gate list is in `docs/kpi-minute-level.md` §Hard Gates (Gates 1–8). Summary:

- Net OOS Sharpe below the asset threshold.
- Same-bar fill assumption (latency cheating).
- Cost-to-profit ratio above the asset ceiling.
- Profitable gross but unprofitable net.
- Look-ahead bias detected (rewrite and re-test from scratch).
- IS trade count below asset-class floor (statistical adequacy).
- Max intraday/session MDD exceeds absolute ceiling (2× CS threshold).
- **PDT-incompatible design (US equities intraday, margin accounts)** — requires >3 day trades per 5 rolling days. *(Gate 8, CEO ruling F3, 2026-06-07)*

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
