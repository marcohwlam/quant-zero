# Research Directory

This is the Research Director's working knowledge base for the Quant Zero alpha research pipeline.

## Structure

| Folder | Purpose |
|--------|---------|
| `hypotheses/` | Strategy ideas and rationale, pre-backtest. One file per strategy. |
| `regimes/` | Market regime classifications, transition signals, and regime history. |
| `findings/` | Research outcomes — passed/failed backtests and why. Links to backtest artifacts. |

## Lifecycle

1. Research Director (or Alpha Research Agent) creates a hypothesis file in `hypotheses/`
2. Strategy is passed to Engineering Director for backtesting
3. Overfit Detector evaluates against Gate 1 criteria
4. Result is documented in `findings/` with pass/fail verdict and rationale
5. Passed strategies advance to paper trading; failed strategies are noted for learning

## File Conventions

- **Hypotheses:** `hypotheses/NN_strategy_name.md` — sequential numbering, snake_case
- **Regimes:** `regimes/YYYY-MM_regime_classification.md` — date-prefixed
- **Findings:** `findings/NN_strategy_name_vN_YYYY-MM.md` — version and date stamped
