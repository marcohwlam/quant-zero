# TOOLS.md — Quant Metrics Tools

## Available

- Python statistical stack (numpy, pandas, scipy, statsmodels).
- Read-only access to `backtests/` verdicts and reports.
- Read-only access to `paper_trading/` results for live-vs-backtest comparison.
- File read/write in `docs/` for `kpi-minute-level.md`.
- Web search for methodology references (DSR, PBO, deflated metrics literature).

## Constraints

- Read-only on strategy code and backtest outputs — you measure, you do not author strategies.
- You do not run live trades or modify broker connectors.
- You do not lock `criteria.md`; you propose and the CEO locks.
