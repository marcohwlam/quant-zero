# Canonical Workspace Structure (CEO-locked)

This document defines where everything lives in the Quant Zero repository.
The CEO owns it. The daily-evening workspace audit checks files against it.

## Directory layout

```
agents/<name>/      agent definitions and personal memory
backtests/          gate1 verdicts and reports, one dir or file per hypothesis
broker/             broker / paper trading connectors
docs/               company-wide specs and KPI documents
knowledge_base/     sourced strategy material (books, papers, references)
orchestrator/       pipeline glue
research/           research notebooks and hypotheses
strategies/         strategy implementations
tests/              test suite
visualization/      plotting and report rendering
promoted/           registry.json — Gate1-passing strategies (Risk-defined format)
paper_trading/      <strat_id>/{equity.csv, trades.csv, meta.json} (Risk-defined format)
dashboard/          generated static dashboard output (Eng-built, do not hand-edit)
scripts/            shared scripts incl. build_dashboard.py
workflow-contracts/ per-role LLM-vs-script contracts + git.md
criteria.md         Gate 1 acceptance criteria (CEO-locked)
workspace-structure.md  this file (CEO-locked)
```

## Rules

- New top-level directories require CEO approval via PR.
- Strategy code lives only in `strategies/`. Backtest outputs only in `backtests/`.
- Sourced material (books, papers) lands in `knowledge_base/` with provenance.
- `dashboard/` is generated output — never hand-edit; regenerate via `scripts/build_dashboard.py`.
- `promoted/registry.json` and `paper_trading/` formats are defined by the Risk Director.
