# Proposal: Risk Constitution Rules 11 and 12

Author: Risk Director
Ticket: QUA-869 (first proposed in the 2026-06-08 heartbeat; unratified since)
Status: PENDING CEO DECISION

## Decision requested

Approve, amend, or reject each rule below. If approved, the CEO merges the
`docs/mission_statement.md` change in the section "Proposed text". Agents cannot edit
that file (CEO-locked).

## Rule 11: Volatility targeting

Each strategy's capital allocation targets 10% annualized volatility.
Position size = (target_vol / realized_vol) x base_allocation.
A 50% rise in realized vol cuts position size by 33%.
Portfolio Monitor tracks `vol_ratio = realized_vol / backtest_vol` daily and alerts the
Risk Director when it exceeds 1.5x.

Rationale: keeps per-strategy risk contribution stable across regimes; limits drawdown
growth when vol expands. Source: Carver, Systematic Trading, Ch. 9.

Constraint: sizing may only reduce exposure below the caps in Rules 1 to 3. It never
raises exposure above them, and never implies leverage above Rule 6.

## Rule 12: Correlation-based exposure limits

If two active strategies show 30-day rolling return correlation above 0.6, their combined
allocation must not exceed 25% of total capital (one correlated risk unit, extending
Rule 2). Portfolio Monitor computes the correlation matrix daily and alerts the Risk
Director on breach. Source: Carver, Systematic Trading, Ch. 11.

## Current enforcement status

Neither rule is binding. Both are enforced as recommendations, with violations flagged to
the CEO. No violation is currently on record that would change the verdict below.

## Risk Director recommendation

Approve both. Rule 12 is cheap and directly extends Rule 2. For Rule 11, approve with the
cap constraint above so it cannot be read as permission to size up in low-vol regimes.

## Proposed text (append to Risk Management Constitution)

11. Each strategy's capital allocation targets 10% annualized volatility. Position size =
    (target_vol / realized_vol) x base_allocation, capped by Rules 1 to 3 and 6. Alert the
    Risk Director when vol_ratio exceeds 1.5x.
12. If two active strategies have 30-day rolling return correlation above 0.6, their
    combined allocation must not exceed 25% of total capital.

Version history row: `| 2.1 | <date> | Add Rules 11 and 12 | CEO - QUA-869 |`
