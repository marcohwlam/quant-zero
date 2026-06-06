# Knowledge Base — Minute-Level Strategy Hypotheses

Strategies sourced from quality references that require minute-level OHLCV or tick data.
These are **not** ready for the current daily-OHLCV backtesting pipeline (PF-3 fail by construction).
They are preserved here as research assets for when intraday data infrastructure is built.

## Naming Convention

`mkbNNN_strategy_slug.md` — three-digit sequential number, snake_case slug.

## Status Labels

- `KNOWLEDGE_BASE` — documented from source; not yet pipeline-ready
- `INFRA_READY` — minute-level data pipeline exists; can graduate to research/hypotheses/
- `RETIRED` — edge documented as decayed or not replicable

## Required Sections

1. **Provenance** — author, title, year, page/section
2. **Summary** — one paragraph
3. **Edge & Mechanism** — why this works at minute-bar level
4. **Entry/Exit Logic** — codifiable pseudocode
5. **Alpha Decay Analysis** — half-life, IC decay, transaction cost viability
6. **Failure Modes & Overfitting Risks**
7. **Infrastructure Requirements** — data sources not in current pipeline
8. **Pipeline Graduation Path** — what needs to be built before backtesting

---

*Research Director | QUA-49 | 2026-06-06*
