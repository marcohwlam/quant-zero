# Gate 1 Acceptance Criteria — Minute-Level (v2.1)

**Version:** 2.1
**Locked by:** CEO
**Status:** LOCKED — only the CEO may modify these criteria after lock.
**Supersedes:** v1.3 (daily/swing). The daily track is replaced going forward;
prior daily-track backtests are not retroactively re-run.

---

## Purpose

Gate 1 is the first quality checkpoint in the minute-level strategy promotion pipeline.
A strategy must pass Gate 1 before it is eligible for paper trading. At minute resolution,
the dominant failure mode is transaction cost, not curve-fitting — the criteria reflect that.

---

## Required Test Period

| Parameter | Requirement | Rationale |
|-----------|-------------|-----------|
| Backtest window | 2 years: 2022-01 to 2024-12 | Covers rate-shock (2022) and normalization (2023-2024). |
| Walk-forward windows | 6 non-overlapping | 3-month in-sample / 1-month out-of-sample each. |
| Bar definition | Per asset class | 1-min equities RTH; 1-min crypto 24/7; 1-min futures session. |

---

## Cost Realism (top-level gate — the minute-level killer)

Backtests MUST model the following, or the strategy is auto-rejected:

| Asset | Cost model (PLACEHOLDER — calibrate with real data) |
|-------|------------------------------------------------------|
| Equities | $0.005/share + half-spread slippage + 0.02% market impact |
| Crypto | 0.05% taker + 0.03% slippage |
| Futures | per-contract commission + 1 tick slippage |

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

PLACEHOLDERS — calibrated by Engineering Director / Quant Metrics with real 2022-2024 data,
then CEO-locked. Setting numbers without data violates the data-driven rule.

| Metric | Equities intraday | Crypto | Futures |
|---|---|---|---|
| Net OOS Sharpe | > TBD | > TBD | > TBD |
| Net profit per trade (bps, after cost) | > TBD | > TBD | > TBD |
| Max intraday drawdown | < TBD | < TBD | < TBD |
| Trade count (IS) | > TBD | > TBD | > TBD |
| Cost-to-gross-profit ratio | < TBD | < TBD | < TBD |

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
