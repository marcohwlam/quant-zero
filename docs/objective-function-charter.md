# Quant Zero Objective Function Charter

**Version:** 1.0  
**Status:** CEO-LOCKED  
**Locked by:** CEO (QUA-154, 2026-06-09)  
**Supersedes:** Any prior framing of the company objective as "beat the S&P 500" on absolute return.

---

## Purpose

This charter locks the company's top-level objective function and establishes the risk-adjusted
framing that governs all agent behavior, strategy research, backtesting, and capital allocation
decisions.

All agents must optimize for this objective. Any directive, document, or behavior that conflicts
with this charter is superseded by it.

---

## The Objective Function

**Primary objective:** maximize net Sharpe ratio.

**Hard constraints (all three must hold simultaneously):**

| Constraint | Threshold | Rationale |
|---|---|---|
| Net CAGR | ≥ 10% annualized | Minimum acceptable absolute return; approximately matches long-run SPX |
| Maximum Drawdown | < −15% from peak | Capital preservation floor; positions portfolio to survive and recover |
| Net Sharpe | > 0.8 annualized | Minimum risk-adjusted quality; well above SPX baseline of ~0.5 |

**All metrics are measured NET** of realistic transaction costs, fees, and slippage per the
canonical cost model in `agents/engineering-director/AGENTS.md` and `criteria.md`.

---

## The Risk-Adjusted Framing (Explicit)

The win condition is **beating SPX on risk-adjusted terms**, NOT on absolute return.

| Benchmark | Approximate Sharpe | Approximate MaxDD |
|---|---|---|
| S&P 500 (SPX) | ~0.5 annualized | ~−50% (2000–2002, 2008–2009) |
| Quant Zero target | > 0.8 annualized | < −15% |

Why this matters:

- SPX long-run CAGR ≈ 10%. Matching or modestly beating SPX return is *not* the goal if it
  requires accepting SPX-level drawdowns (−50%). A $25K account cannot survive a −50% drawdown
  in context.
- The achievable, valuable win is: **similar or better return with dramatically less drawdown and
  more consistency** — a genuine risk-adjusted improvement, not a raw return race.
- Optimizing for absolute return without a drawdown constraint naturally produces strategies that
  are long-biased in bull markets and catastrophic in bear markets. This charter explicitly rejects
  that failure mode.

**Any agent that optimizes for raw return without respecting the MaxDD < −15% and Sharpe > 0.8
constraints is acting against the company objective.** These constraints are not secondary;
they are co-equal with the return target.

---

## Relationship to Existing Documents

This charter is the **top-level statement**. Other documents operationalize it at finer resolution:

| Document | Scope | Relationship |
|---|---|---|
| `docs/objective-function-charter.md` (this file) | Company-level objective | Top-level authority |
| `docs/kpi-minute-level.md` | Per-asset-class KPI operationalization for Gate 1 | Implements this charter at minute-level; per-asset Sharpe floors (0.7–0.8) and intraday MDD ceilings are the Gate 1 operationalization of the charter constraints |
| `criteria.md` | Gate 1 acceptance criteria | Enforces this charter at strategy-evaluation checkpoints |
| `docs/mission_statement.md` | Risk Management Constitution | Capital-level rules (1% trade limit, 8% portfolio halt, etc.) that sit beneath this charter's portfolio-level constraints |

**No conflict rule:** If `docs/kpi-minute-level.md` or `criteria.md` appears to permit a strategy
that would violate the charter constraints (CAGR < 10%, MaxDD < −15%, or Sharpe < 0.8 at
portfolio level), the charter governs. Per-asset intraday MDD thresholds in the KPI doc measure
*strategy-level* drawdown; the charter's −15% MaxDD applies to the *portfolio* as a whole.

---

## Interpretation Guidance for Directors

### Research Director

When evaluating or proposing strategy hypotheses:
- Prioritize hypotheses with credible Sharpe > 0.8 thesis, not hypotheses chasing absolute return.
- Reject hypotheses with no drawdown control mechanism — a regime filter or exit discipline is
  mandatory (PF-5 in `criteria.md` encodes this).
- "Beats SPX return" is insufficient justification. "Achieves comparable return with Sharpe > 0.8
  and MaxDD < 15%" is the target framing.

### Engineering Director

When implementing and backtesting strategies:
- Report Net Sharpe as the primary metric in all Gate 1 outputs. Gross Sharpe is diagnostic only.
- Flag any backtest result where net CAGR ≥ 10% is achieved at the cost of MaxDD approaching
  −15%; this is a charter warning even if it passes Gate 1 thresholds.
- The cost model in `criteria.md` and `agents/engineering-director/AGENTS.md` must be applied in
  all backtests — net metrics are what the charter measures.

### Risk Director

When reviewing strategies and portfolio:
- Gate 1 recommendation must include a charter-alignment assessment: does this strategy, if
  promoted, contribute toward the portfolio Sharpe > 0.8 / MaxDD < −15% targets?
- Portfolio-level risk monitoring must track whether the live portfolio remains within charter bounds.
- A portfolio breaching MaxDD −15% is a charter violation requiring immediate CEO escalation,
  regardless of whether individual strategy demotion thresholds have been hit.

---

## Governance

- This charter is CEO-locked. No agent modifies it without a CEO-approved PR.
- Any strategy promotion, capital allocation change, or research direction that would cause the
  portfolio to structurally violate the charter must be escalated to the CEO before execution.
- Revisions require documented rationale, version increment, and CEO lock.

### Version History

| Version | Date | Change | Author |
|---|---|---|---|
| 1.0 | 2026-06-09 | Initial lock — max Sharpe s.t. CAGR≥10% / MaxDD<−15% / Sharpe>0.8; risk-adjusted framing explicit; supersedes "beat SPX return" objective | CEO — QUA-154 |
