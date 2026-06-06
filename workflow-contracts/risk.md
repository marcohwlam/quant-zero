# Risk Agent Workflow Contract

## MUST be script/Python (repeatable, deterministic)
- Overfitting statistics (DSR, MC bootstrap, permutation tests).
- Gate 1 threshold checks against criteria.md.
- Paper-trading drift and staleness detection.
- Portfolio exposure and drawdown monitoring.

## MAY use LLM (judgment, synthesis)
- Qualitative Gate 1 assessment (economic rationale validity, look-ahead review).
- Writing the dashboard spec (what to show, alert thresholds).
- Deciding when a paper-trading anomaly warrants escalation.

## Rule
If a step runs more than twice, it becomes a script. Agents own their script design.
Pass/fail verdicts cite script output — never an LLM's unaided judgment of the numbers.
