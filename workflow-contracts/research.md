# Research Agent Workflow Contract

Defines which steps MUST run as scripts/Python and which MAY use LLM judgment.
Agents own their own script implementations within these boundaries.

## MUST be script/Python (repeatable, deterministic)
- Data loading, cleaning, resampling to minute bars.
- Factor / indicator computation.
- Statistical tests (cointegration, half-life, IC, Hurst).
- Backtest execution and metric calculation.
- Report generation from a template.

## MAY use LLM (judgment, synthesis)
- Hypothesis formulation from sourced material.
- Interpreting why an edge exists (economic rationale).
- Deciding which hypothesis to pursue next.

## Rule
If a step runs more than twice, it becomes a script. Agents own their script design.
