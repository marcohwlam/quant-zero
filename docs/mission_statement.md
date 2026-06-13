# Mission Statement

**Version:** 2.0  
**Status:** CEO-LOCKED  
**Locked by:** CEO (QUA-230, 2026-06-13)  
**Supersedes:** v1.x (minute-level-flavored, ad-hoc capital numbers)

---

## Objective

Build a portfolio of low-correlation, systematically-validated strategies that deliver consistent
risk-adjusted returns — beating SPX on risk-adjusted terms at Net CAGR >= 10%, Sharpe > 0.8,
MaxDD < -15% — across whatever horizon the evidence supports.

This objective is verbatim from `docs/objective-function-charter.md` (CEO-locked, QUA-154), the
single source of truth for the objective function. All quantitative thresholds, Gate 1 criteria,
and cost model requirements live in `criteria.md` and the charter. They are not restated here.

---

## Core Principles

**Capital preservation first.** A drawdown requires outsized returns to recover. The system is
built to be paranoid about risk before it is ambitious about returns.

**Compound systematically, not speculatively.** The goal is repeatable, evidence-backed edges
that compound over months and years — not a single large trade.

**Horizon follows evidence, not decree.** Horizons (intraday, daily, weekly) are eligible
candidates if they survive Gate 1 under realistic costs. Evidence determines the active horizon;
no horizon is permanently excluded or permanently primary. See `criteria.md` §Horizon Selection
Policy and `docs/horizon-evidence-gate-decision-2026-06-09.md`.

**Multi-strategy diversification is structural.** Low-correlation strategies across horizons and
asset classes reduce drawdown and smooth returns. The portfolio is the product; a single strategy
is not.

**Earn the right to scale.** Paper trading precedes live capital. Live trading at small size
precedes full allocation. The system cannot skip gates.

---

## Strategy Tracks

Two tracks feed one portfolio sleeve. Both are judged by the same charter objective
(QUA-154) and the same Gate 1 (`criteria.md`), with horizon-appropriate threshold sets.

### Track A — Daily/Weekly Momentum

**Status:** Near-term primary path to first Gate-1-passing strategy.

**Horizon:** Daily/weekly bars. Holding period: days to months.

**Playbook:** `docs/knowledge/trading-methodology-jlaw-lineage.md` (J Law lineage — O'Neil,
Minervini, Weinstein, Darvas, Elder). The lineage is Track A's *tool*, not the company's
mission.

**Built-in components:**

| Component | Implementation |
|---|---|
| Universe finder | CAN SLIM criteria + Minervini Trend Template |
| Regime filter | O'Neil M-filter (market direction) + Weinstein Stage analysis |
| Risk framework | 7–8% hard stops per position; Elder 2%/6% rules |

**Why primary now:** Track A ships with finder, regime filter, and risk discipline already
documented. Lower turnover means transaction cost drag is not the dominant failure mode at
this horizon — unlike minute-level where cost realism is the #1 killer.

**Gate 1 note:** Requires a daily/weekly-specific threshold set (swing MDD ceiling, trade-count
floor, holding-period guards). The minute-level thresholds in `criteria.md` v2.2 are inapplicable
at multi-day holding periods. Swing threshold set commissioned as a follow-up (QUA-230 §4).

---

### Track B — Minute-Level Intraday

**Status:** Active in parallel. Evidence-gated on QUA-151 slippage findings.

**Horizon:** Minute-level bars. Holding period: intraday, flat by close.

**Architecture:** Three-layer construction discipline from QUA-127/128/129:
regime/risk filter + universe/liquidity filter + single alpha signal (Harvey-Liu-Zhu deflated
t > 3.0).

**Cost realism:** This is the cost-realism track. Dominant failure mode is transaction cost
drag, not curve-fitting. Strategies must survive the full cost model in `criteria.md`
§Cost Realism before retaining any status.

**Evidence gate:** Track B retains parallel status until QUA-151 (live slippage measurement)
produces findings. If realized live slippage prevents minute-level strategies from meeting
the charter constraints, Track A becomes the primary path by evidence rather than decree.
If minute-level strategies survive QUA-151, Track B competes on equal footing.

---

## Sequencing Note

Track A is the near-term primary path. This is a sequencing decision based on two facts:
(1) Track A's playbook is documented end-to-end and ready to operationalize; (2) Track B's
cost drag at minute-level is unresolved pending QUA-151. This is NOT a permanent ranking.
Both tracks remain active. The charter objective governs; whichever track produces a
Gate-1-passing strategy advances.

---

## Risk Management Constitution

These rules cannot be overridden by any agent. Only the CEO can modify them, and only
after a formal review.

1. No single trade can lose more than 1% of total capital.
2. No single strategy can hold more than 25% of total capital.
3. Total portfolio exposure never exceeds 80%. 20% stays in cash or stablecoins.
4. No strategy goes live without passing all three gates (backtest → paper → small live).
5. Any strategy that hits 1.5x its backtest max drawdown is automatically demoted to paper.
6. No leverage above 2x on any position, any asset class.
7. No new strategy deployment during the first or last 30 minutes of US market hours
   (highest volatility, worst fills).
8. Monthly risk review is mandatory. If the CEO skips it, all live strategies pause until
   the review is completed.
9. If total portfolio drawdown exceeds 8%, pause all live trading for 48 hours and conduct
   a full review before resuming.
10. No agent can execute a live trade. All live order routing requires explicit CEO approval
    or a pre-approved automated rule that the CEO has reviewed and signed off on.

---

## Governance

- CEO-locked. No agent modifies this document without a CEO-approved PR.
- Horizon-specific thresholds belong in `criteria.md`, not here.
- The objective function belongs in `docs/objective-function-charter.md`, not here.
- Future mission adjustments are rare and require documented rationale. Strategy and horizon
  changes belong in the strategy/horizon layers — not in this document.

### Version History

| Version | Date | Change | Author |
|---|---|---|---|
| 1.x | 2026-03 to 2026-06 | Minute-level-flavored mission; ad-hoc capital targets | Various |
| 2.0 | 2026-06-13 | Rewrite: horizon-agnostic mission; objective verbatim from QUA-154; two strategy tracks (Track A daily/weekly primary, Track B minute-level evidence-gated on QUA-151); Risk Management Constitution preserved; stale roadmap and ad-hoc numbers removed | CEO — QUA-230 |
