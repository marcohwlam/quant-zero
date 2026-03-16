# Architecture & Design Document — Quant Zero

**Version:** 1.0
**Date:** 2026-03-15
**Owner:** Engineering Director
**Status:** Active

---

## 1. System Overview

Quant Zero is a multi-agent AI pipeline that converts strategy hypotheses into vetted, systematically-deployed trading strategies. The system is organized around a CEO (human) who makes gate decisions, three Director-level agents (Research, Engineering, Risk), and a set of IC agents under each Director.

All agent coordination uses **Paperclip** as the control plane. All strategy execution and data processing runs in the `/mnt/c/Users/lamho/repo/quant-zero` local workspace.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           QUANT ZERO SYSTEM                                  │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                         HUMAN LAYER                                      │ │
│  │                                                                           │ │
│  │                    ┌──────────────────┐                                  │ │
│  │                    │    CEO (Human)    │                                  │ │
│  │                    │  gate decisions  │                                  │ │
│  │                    │  capital alloc.  │                                  │ │
│  │                    │  research direct │                                  │ │
│  │                    └────────┬─────────┘                                  │ │
│  └──────────────────────────── │ ─────────────────────────────────────────┘ │
│                                │ Paperclip tasks                             │
│  ┌──────────────────────────── │ ─────────────────────────────────────────┐ │
│  │                    DIRECTOR LAYER                                         │ │
│  │                             │                                             │ │
│  │     ┌───────────────────────┼────────────────────┐                       │ │
│  │     │                       │                    │                       │ │
│  │     ▼                       ▼                    ▼                       │ │
│  │ ┌───────────┐        ┌─────────────┐      ┌───────────┐                 │ │
│  │ │ Research  │        │ Engineering │      │   Risk    │                 │ │
│  │ │ Director  │        │  Director   │      │ Director  │                 │ │
│  │ │           │        │             │      │           │                 │ │
│  │ │ Hypotheses│──────▶ │ Code + Test │─────▶│ Gate 1    │                 │ │
│  │ │ Regime    │        │ Backtests   │      │ Overfit   │                 │ │
│  │ └─────┬─────┘        └──────┬──────┘      └─────┬─────┘                 │ │
│  │       │                     │                   │                        │ │
│  └───────│─────────────────────│───────────────────│────────────────────┘  │ │
│          │                     │                   │                        │ │
│  ┌───────│─────────────────────│───────────────────│────────────────────┐  │ │
│  │       ▼        IC LAYER     ▼                   ▼                    │  │ │
│  │  ┌──────────┐         ┌──────────┐        ┌──────────┐              │  │ │
│  │  │  Alpha   │         │ Strategy │        │  Overfit │              │  │ │
│  │  │ Research │         │  Coder   │        │ Detector │              │  │ │
│  │  └──────────┘         └──────────┘        └──────────┘              │  │ │
│  │  ┌──────────┐         ┌──────────┐        ┌──────────┐              │  │ │
│  │  │  Market  │         │ Backtest │        │Portfolio │              │  │ │
│  │  │  Regime  │         │  Runner  │        │ Monitor  │              │  │ │
│  │  └──────────┘         └──────────┘        └──────────┘              │  │ │
│  └────────────────────────────────────────────────────────────────────┘  │ │
│                                                                            │ │
└────────────────────────────────────────────────────────────────────────────┘ │
                                                                                │
```

---

## 3. Strategy Lifecycle

```
   Research                Engineering                   Risk              CEO
      │                        │                           │                │
      │  hypothesis doc        │                           │                │
      │ ──────────────────────▶│                           │                │
      │                        │                           │                │
      │                   Strategy Coder                   │                │
      │                   implements code                  │                │
      │                        │                           │                │
      │                   Backtest Runner                  │                │
      │                   runs IS + OOS                    │                │
      │                        │                           │                │
      │                        │  Gate 1 pass?             │                │
      │                        │ ──────────────────────────▶                │
      │                        │                           │                │
      │                        │                     Overfit Detector       │
      │                        │                     runs analysis          │
      │                        │                           │                │
      │                        │                           │ verdict        │
      │                        │                           │ ───────────────▶
      │                        │                           │                │
      │                        │                           │          approve/reject
      │                        │                           │                │
      │  (if rejected)         │                           │                │
      │ ◀──────────────────────│                           │                │
      │                        │                           │                │
      │                        │  (if approved)            │                │
      │                        │ ◀─────────────────────────│────────────────│
      │                        │  deploy to paper          │                │
      │                        │                           │                │
      │                        │                    Portfolio Monitor       │
      │                        │                    tracks paper perf.      │
```

---

## 4. Component Map

### 4.1 Repository Layout

```
quant-zero/
│
├── agents/                         # Agent AGENTS.md instruction files
│   ├── ceo/AGENTS.md
│   ├── research-director/AGENTS.md
│   ├── engineering-director/AGENTS.md
│   ├── risk-director/AGENTS.md
│   ├── strategy-coder/AGENTS.md
│   ├── backtest-runner/AGENTS.md
│   ├── alpha-research/AGENTS.md
│   ├── market-regime/AGENTS.md
│   ├── overfit-detector/AGENTS.md
│   └── portfolio-monitor/AGENTS.md
│
├── strategies/                     # Executable strategy modules
│   ├── bollinger_band_mean_reversion.py
│   ├── pairs_trading_cointegration.py
│   └── test_momentum.py
│
├── backtests/                      # Standardized backtest outputs
│   ├── <strategy-name>/
│   │   └── <version>/
│   │       ├── results.json        # Machine-readable metrics
│   │       ├── report.md           # Human-readable narrative
│   │       ├── params.json         # Parameter set
│   │       └── walk_forward/       # Per-window results
│
├── orchestrator/                   # Core execution engine
│   ├── quant_orchestrator.py       # Main propose→backtest→evaluate loop
│   ├── gate1_reporter.py           # Gate 1 metrics extraction
│   ├── iteration_log.db            # SQLite: all iteration history
│   ├── knowledge_base/             # Learnings per iteration (JSON/MD)
│   └── requirements.txt
│
├── broker/                         # Broker API integrations
│   ├── README.md                   # Setup guide
│   ├── strategy_registry.json      # Active strategy configurations
│   └── verify_feeds.py             # Data feed health check
│
├── research/                       # Research Director outputs
│   ├── hypotheses/                 # Strategy hypothesis documents
│   └── findings/                   # Pre-screening results, CSVs
│
└── docs/                           # All system documentation
    ├── PRD.md                      # Product requirements
    ├── architecture.md             # This document
    ├── mission_statement.md
    ├── ceo_operations_manual.md
    ├── gate1-intake-process.md
    ├── quant_orchestrator.md
    ├── continuous_improvement_framework.md
    ├── strategy_knowledge_base.md
    ├── heartbeats/                 # Director heartbeat reports
    │   ├── engineering/
    │   ├── research/
    │   └── risk/
    ├── monitoring/                 # Strategy runbooks
    └── templates/
        └── director-heartbeat-template.md
```

### 4.2 Agent Roster

| Agent | Reports To | Manages | Primary Input | Primary Output |
|-------|-----------|---------|--------------|----------------|
| CEO | — | Research Dir, Engineering Dir, Risk Dir | Gate packages, agent reports | Gate decisions, capital allocation |
| Research Director | CEO | Alpha Research, Market Regime | CEO directives | Strategy hypotheses |
| Engineering Director | CEO | Strategy Coder, Backtest Runner | Hypotheses from Research | Backtest metrics, Gate 1 submissions |
| Risk Director | CEO | Overfit Detector, Portfolio Monitor | Gate 1 packages | Pass/fail verdicts, monitoring alerts |
| Alpha Research | Research Dir | — | Knowledge base, market data | Strategy hypotheses |
| Market Regime | Research Dir | — | Price data, VIX, breadth | Regime classification |
| Strategy Coder | Engineering Dir | — | Hypothesis + params | Executable Python/vectorbt code |
| Backtest Runner | Engineering Dir | — | Strategy code | Standardized metrics reports |
| Overfit Detector | Risk Dir | — | Backtest results, walk-forward data | Overfitting risk score, pass/fail |
| Portfolio Monitor | Risk Dir | — | Paper/live performance data | Alerts, demotion recommendations |

---

## 5. Iteration Loop (Orchestrator Detail)

```
┌──────────────────────────────────────────────────────────────────────┐
│                      ITERATION LOOP (per cycle)                       │
│                                                                        │
│  ┌─────────────────────┐                                              │
│  │  1. LOAD CONTEXT    │                                              │
│  │  - knowledge_base/  │                                              │
│  │  - last N iters     │                                              │
│  │    from SQLite      │                                              │
│  └──────────┬──────────┘                                              │
│             │                                                          │
│             ▼                                                          │
│  ┌─────────────────────┐                                              │
│  │  2. PROPOSE         │                                              │
│  │  Claude generates:  │                                              │
│  │  - hypothesis       │                                              │
│  │  - parameters       │                                              │
│  │  - vectorbt code    │                                              │
│  └──────────┬──────────┘                                              │
│             │                                                          │
│             ▼                                                          │
│  ┌─────────────────────┐                                              │
│  │  3. BACKTEST        │                                              │
│  │  exec() strategy    │                                              │
│  │  code on:           │                                              │
│  │  - IS data window   │                                              │
│  │  - OOS data window  │                                              │
│  │  Extract: Sharpe,   │                                              │
│  │  MDD, trades, etc.  │                                              │
│  └──────────┬──────────┘                                              │
│             │                                                          │
│             ▼                                                          │
│  ┌─────────────────────┐                                              │
│  │  4. EVALUATE        │                                              │
│  │  Claude assesses:   │                                              │
│  │  - passed/failed    │                                              │
│  │  - overfit risk     │                                              │
│  │  - next direction   │                                              │
│  └──────────┬──────────┘                                              │
│             │                                                          │
│             ▼                                                          │
│  ┌─────────────────────┐                                              │
│  │  5. LOG & LEARN     │                                              │
│  │  - Write SQLite row │                                              │
│  │  - Save KB JSON     │                                              │
│  │  - Flag if Gate 1   │                                              │
│  │    criteria met     │                                              │
│  └──────────┬──────────┘                                              │
│             │                                                          │
│             └───────────────────────────────┐                         │
│                                             ▼                         │
│                              ┌──────────────────────┐                │
│                              │  Gate 1 met? → HALT  │                │
│                              │  submit to Risk Dir   │                │
│                              │                       │                │
│                              │  Not met? → next iter │                │
│                              └──────────────────────┘                │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 6. Data Flow

### 6.1 Market Data

```
yfinance (OHLCV)
    │
    ├──▶ IS window  (2018-01-01 to 2022-12-31)
    │        │
    │        └──▶ Strategy code → vectorbt Portfolio → IS metrics
    │
    └──▶ OOS window (2023-01-01 to 2024-12-31)
             │
             └──▶ Strategy code → vectorbt Portfolio → OOS metrics
```

### 6.2 Gate 1 Package Flow

```
Backtest Runner
    │
    ├── backtests/<name>/<version>/results.json   (machine-readable)
    ├── backtests/<name>/<version>/report.md      (human-readable)
    └── backtests/<name>/<version>/params.json
    │
    ▼
Engineering Director
    │  creates Paperclip Gate 1 task
    ▼
Risk Director
    │  delegates to Overfit Detector
    ▼
CEO receives verdict: pass / fail / conditional
```

---

## 7. Broker Integration Architecture

```
┌────────────────────────────────────────────────────┐
│                  BROKER LAYER                       │
│                                                     │
│   ┌─────────────────┐    ┌──────────────────────┐  │
│   │ Alpaca           │    │ Crypto Exchange       │  │
│   │ (Equities/Opts)  │    │ (Coinbase/Kraken)     │  │
│   │                  │    │                       │  │
│   │ Phase 2: Paper   │    │ Phase 2: Testnet      │  │
│   │ Phase 3: Live    │    │ Phase 3: Live         │  │
│   └────────┬─────────┘    └──────────┬────────────┘  │
│            │                         │               │
└────────────│─────────────────────────│───────────────┘
             │                         │
             ▼                         ▼
         Auth: env vars only (ALPACA_API_KEY, COINBASE_API_KEY, etc.)
         No secrets committed. broker/.env in .gitignore.
```

**Phases:**
- **Phase 0–1:** Brokers not connected; yfinance data only
- **Phase 2:** Alpaca paper + exchange testnet; Portfolio Monitor activated
- **Phase 3+:** Live accounts; CEO must explicitly approve order routing

---

## 8. Paperclip Coordination

All inter-agent coordination happens via Paperclip tasks (not direct calls):

```
Typical task flow:

Research Director
  └── creates task "Implement H04 Pairs Trading" → assigns to Strategy Coder
                                                          │
                                                          ▼
                                                    Strategy Coder checks out,
                                                    writes code in /strategies/,
                                                    comments with file path,
                                                    marks done
                                                          │
Engineering Director (via heartbeat)                      │
  └── sees subtask done, creates "Run backtest for H04" → Backtest Runner
                                                          │
                                                          ▼
                                                    Backtest Runner runs,
                                                    writes to /backtests/,
                                                    comments with results,
                                                    marks done
                                                          │
Engineering Director
  └── evaluates Gate 1, creates Gate 1 task → Risk Director
                                                          │
                                                          ▼
                                                    Risk Director runs
                                                    Overfit Detector, posts
                                                    verdict, escalates to CEO
```

---

## 9. Security Model

| Control | Implementation |
|---------|----------------|
| API key storage | Environment variables only; never committed |
| Git secret prevention | `.env`, `*.key`, `credentials.*` in `.gitignore` |
| Agent permissions | No agent can execute live trades without CEO gate decision |
| Paperclip audit trail | `X-Paperclip-Run-Id` on all mutating API calls |
| Strategy code isolation | `exec()` in sandboxed local namespace; no filesystem writes from strategy code |

---

## 10. Observability

| Layer | Mechanism |
|-------|-----------|
| Iteration history | SQLite: `orchestrator/iteration_log.db` |
| Strategy learnings | JSON files: `orchestrator/knowledge_base/` |
| Backtest artifacts | Versioned dirs: `backtests/<name>/<version>/` |
| Agent coordination | Paperclip task comments and run audit trail |
| Paper/live positions | Portfolio Monitor Agent → daily reports |
| Director heartbeats | `docs/heartbeats/<director>/YYYY-MM-DD.md` (weekly) |

---

## 11. Current Strategy Inventory

| Strategy | File | Status | Gate 1 Result |
|----------|------|--------|---------------|
| Bollinger Band Mean Reversion | `strategies/bollinger_band_mean_reversion.py` | Backtested | See `backtests/BollingerBandMeanReversion_2026-03-15.*` |
| Pairs Trading (Cointegration) | `strategies/pairs_trading_cointegration.py` | Backtested | See `backtests/PairsTradingCointegration_2026-03-15.*` |
| Test Momentum v1.0 | `strategies/test_momentum.py` | Paper trading | Deployed 2026-03-15 |

---

## 12. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backtesting engine | vectorbt | Fast, pandas-native, vectorized; industry standard for Python quant |
| Coordination layer | Paperclip | Agent-native task management with run audit trail |
| Iteration persistence | SQLite | Zero infrastructure, single-file, queryable |
| Parameter limit | 6 max | Reduces overfitting by construction |
| OOS period | 2 years (2023–2024) | Sufficient to cover at least one full market cycle |
| Broker | Alpaca (equities) + Coinbase/Kraken (crypto) | Free paper trading; retail-accessible APIs |
| Agent runtime | Claude claude-sonnet-4-6 via Paperclip | Consistent model version across all agents |

---

*This document is maintained by Engineering Director. Architecture changes require CEO awareness.*
