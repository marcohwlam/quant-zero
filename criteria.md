# Gate 1 Acceptance Criteria — Minute-Level (v2.0)

**Version:** 2.0
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

The objective function that balances return and stability across these metrics is owned by
the Quant Metrics agent and specified in `docs/kpi-minute-level.md` (Risk co-signed, CEO-locked).

---

## Minute-Level-Specific Guards

- Latency: signal-to-fill delay >= 1 bar (no same-bar fills).
- Overnight: explicit flat-by-close OR documented overnight risk.
- Look-ahead: no use of a bar's own close before the bar completes.
- Intraday regime: report performance split by session (open / midday / close).

---

## Per-Asset KPI Spec

See `docs/kpi-minute-level.md` — owned by Quant Metrics, Risk co-signed, CEO-locked.

---

## Automatic Disqualification (any single flag = reject)

- Net OOS Sharpe below the asset threshold.
- Same-bar fill assumption (latency cheating).
- Cost-to-profit ratio above the asset ceiling.
- Profitable gross but unprofitable net.
- Look-ahead bias detected (rewrite and re-test from scratch).

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
