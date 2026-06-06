# Engineering Agent Workflow Contract

## MUST be script/Python (repeatable, deterministic)
- Strategy code, backtest harness, walk-forward splitting.
- Transaction-cost and slippage modeling.
- Metric computation (net Sharpe, drawdown, trade stats).
- Dashboard generation (`scripts/build_dashboard.py`).
- Data pipeline and broker/paper-trading connectors.

## MAY use LLM (judgment, synthesis)
- Translating a hypothesis spec into a coding approach.
- Debugging interpretation and root-cause reasoning.
- Choosing which infrastructure task to prioritize.

## Rule
If a step runs more than twice, it becomes a script. Agents own their script design.
Backtests and metric calculations are NEVER produced by LLM free-text — only by code.
