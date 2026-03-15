# Hypotheses

Pre-backtest strategy ideas and rationale. Each file represents one strategy candidate.

## Naming Convention

`NN_strategy_name.md` — two-digit sequential number, snake_case strategy name.

## Required Sections per Hypothesis File

1. **Summary** — one-paragraph description
2. **Economic Rationale** — why should this edge exist?
3. **Market Regime Context** — when does this work / fail?
4. **Entry/Exit Logic** — clear enough to codify
5. **Asset Class & PDT/Capital Constraints** — fit for a $25K account
6. **Gate 1 Assessment** — which thresholds are likely to pass/miss?
7. **Recommended Parameter Ranges** — starting point for first backtest

## Status Labels

- `DRAFT` — under development, not ready for backtesting
- `READY` — hypothesis is complete; ready to pass to Engineering Director
- `IN_BACKTEST` — Engineering Director is running the backtest
- `FINDINGS_AVAILABLE` — see findings/ for result
