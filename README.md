# Quant Zero

**AI-managed quantitative trading system** — research, backtest, and systematically deploy trading strategies across US equities, options, and crypto.

## What This Is

Quant Zero is an agentic pipeline where Claude-powered agents handle the full research-to-deployment lifecycle. A human CEO sets direction and approves gate decisions. Agents handle everything in between.

## Quick Links

| Doc | Description |
|-----|-------------|
| [Mission Statement](docs/mission_statement.md) | Strategic goals and risk constitution |
| [Architecture & Design](docs/architecture.md) | System design, component diagram, data flows |
| [PRD](docs/PRD.md) | Product requirements and acceptance criteria |
| [CEO Operations Manual](docs/ceo_operations_manual.md) | How to operate the system as CEO |
| [Gate 1 Intake Process](docs/gate1-intake-process.md) | Backtest → paper promotion workflow |
| [Quant Orchestrator](docs/quant_orchestrator.md) | Orchestrator design and code reference |
| [Continuous Improvement Framework](docs/continuous_improvement_framework.md) | Feedback loop design |
| [Strategy Knowledge Base](docs/strategy_knowledge_base.md) | Strategy schema and seed patterns |

## Repository Structure

```
quant-zero/
├── agents/               # Agent instruction files (AGENTS.md per agent)
│   ├── ceo/
│   ├── research-director/
│   ├── engineering-director/
│   ├── risk-director/
│   ├── strategy-coder/
│   ├── backtest-runner/
│   ├── alpha-research/
│   ├── market-regime/
│   ├── overfit-detector/
│   └── portfolio-monitor/
├── strategies/           # Executable strategy code (vectorbt)
├── backtests/            # Backtest results (JSON + markdown reports)
├── orchestrator/         # Core iteration loop and Gate 1 reporter
├── broker/               # Broker API configs (no secrets committed)
├── research/             # Hypotheses, findings, scripts
├── docs/                 # All documentation
└── criteria.md           # Gate acceptance criteria
```

## Getting Started

```bash
# Install dependencies
pip install anthropic vectorbt yfinance pandas numpy sqlalchemy

# Set environment variables
export ANTHROPIC_API_KEY="sk-ant-..."
export ALPACA_API_KEY="..."
export ALPACA_API_SECRET="..."

# Verify data feeds
python broker/verify_feeds.py

# Run the orchestrator
cd orchestrator && python quant_orchestrator.py
```

## Gate Criteria (Gate 1 — Backtest)

| Metric | Threshold |
|--------|-----------|
| IS Sharpe | > 1.0 |
| OOS Sharpe | > 0.7 |
| Max Drawdown | < 20% |
| Min Trades | ≥ 100 |

See [criteria.md](criteria.md) for full details.
