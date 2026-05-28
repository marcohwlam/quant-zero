# Quant Zero

An AI-managed quantitative trading system where specialized Claude agents handle the full research-to-deployment lifecycle. One human CEO sets direction and approves gate decisions. Agents handle everything in between.

**Status:** Active — 51 hypotheses researched, 39 strategies implemented, 72 backtests run, 1 strategy in paper trading.

---

## Mission

Build a self-improving, AI-managed portfolio that generates consistent monthly income across US equities, options, and crypto — with capital preservation as the primary constraint.

| Target | Value |
|---|---|
| Monthly return | 1.5–3.0% |
| Max drawdown | < 10% |
| Sharpe ratio | > 1.5 |
| Win rate | > 55% |
| Single-trade loss cap | 1% of capital ($250 at $25K) |

---

## How It Works

### Agent Organization

```
                    CEO (human)
                   gate decisions
                   capital allocation
                        │
         ┌──────────────┼──────────────┐
         │              │              │
   Research Dir    Engineering Dir   Risk Dir
         │              │              │
    ┌────┴────┐    ┌────┴────┐    ┌───┴────┐
  Alpha    Market  Strategy  Backtest  Overfit  Portfolio
 Research  Regime   Coder    Runner   Detector  Monitor
```

Three director-level agents coordinate the pipeline. Six IC agents execute the work. All coordination runs through **Paperclip** (control plane). All strategy execution runs in this repository.

### Strategy Lifecycle

```
  PROPOSE          TEST           EVALUATE         LEARN          DEPLOY
     │               │               │               │               │
  Research      Engineering        Risk           Knowledge        CEO
  Director      Director +       Director +       Base           approves
  generates     Backtest         Overfit          updated        paper →
  hypothesis    Runner runs      Detector         iteration      live
  + code spec   IS/OOS +         runs Gate 1      logged
                walk-forward     analysis
```

Every strategy passes through three gates before live capital:

| Gate | Owner | What It Tests |
|---|---|---|
| Gate 1 — Backtest | Risk Director + Overfit Detector | Statistical validity, overfitting, walk-forward consistency |
| Gate 2 — Paper Trading | CEO | Live execution vs. backtest expectations, implementation shortfall |
| Gate 3 — Small Live | CEO | Real capital at minimal size before full allocation |

### Gate 1 Criteria

A strategy must pass all of the following. Any single auto-disqualify = immediate FAIL.

| Test | Threshold | Auto-disqualify? |
|---|---|---|
| IS Sharpe | > 1.0 | No |
| OOS Sharpe | > 0.7 | No |
| IS Max Drawdown | < 20% | No |
| OOS Max Drawdown | < 25% | No |
| Win Rate | > 50% | No |
| Deflated Sharpe Ratio (DSR) | > 0 | Yes |
| Walk-forward windows passed | ≥ 3 of 4 | Yes |
| WF OOS/IS Sharpe consistency | OOS within 30% of IS | Yes |
| Minimum OOS Sharpe per window | > 0 (no window negative) | Yes |
| Parameter sensitivity (1D) | ±20% param change → < 30% Sharpe Δ | Yes |
| Trade count | ≥ 100 trades | Yes |
| Test period | ≥ 5 years | Yes |
| Post-cost performance | Must pass with realistic costs | Yes |
| Look-ahead bias | None detected | Yes |
| PBO (CSCV) | ≤ 0.5 | Yes |
| Permutation test p-value | ≤ 0.05 | Yes |

See [criteria.md](criteria.md) for the full specification.

---

## Feedback Loop

The system is designed to improve with every iteration — not just accumulate backtests.

```
    ┌──────────────────────────────────────────────────────────┐
    │                                                          │
    ▼                                                          │
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐        │   ┌──────────┐
│ PROPOSE │──▶│  TEST   │──▶│EVALUATE │──▶│  LEARN  │────────┘   │  DEPLOY  │
│         │   │         │   │         │   │         │────────────▶│ (gated)  │
└─────────┘   └─────────┘   └─────────┘   └─────────┘            └──────────┘
  Research      Backtest       Risk +        Knowledge             Paper → Live
  Director      Runner         Overfit       Base + 41             with full
  + Alpha       IS/OOS +       Detector      entries, failure      Gate 1/2/3
  Research      walk-fwd                     analysis logged       sign-off
```

**How learning compounds:**

- Every failed strategy is documented in `orchestrator/knowledge_base/` (41 entries) with root cause analysis
- Research Director reads the last N iteration summaries before proposing new hypotheses — no random exploration
- Failed strategy classes are suppressed; research pivots to unexplored edges
- Walk-forward results inform regime dependency analysis on future strategies
- Paper trading shortfall data feeds back into the transaction cost model

**What agents do between heartbeats:**

- Engineering Director: daily pipeline health check (Mon–Fri), weekly metric report (Monday)
- Risk Director: weekly risk summary + tail risk report when VIX > 25
- Research Director: weekly hypothesis pipeline review
- Portfolio Monitor: continuous strategy drawdown tracking vs. backtest expectations

---

## Example Results

### Gate 1 PASS — H10 Crypto EQL/EQH Liquidity Reversal v2

Strategy trades liquidity zone touches (EQL/EQH) in crypto with a reversal bias. Pattern-based binary signal; ~10-14 trades per year.

| Metric | IS | OOS |
|---|---|---|
| Sharpe | 1.20 | 1.44 |
| Max Drawdown | -10.7% | -10.5% |
| Win Rate | 61.4% | 67.3% |
| Walk-forward | 4/4 windows pass | — |
| DSR | 0.0022 (PASS) | — |

Verdict: **PASS WITH APPROVED EXCEPTIONS** — permutation test overridden at n=70 (insufficient power for sparse binary signals; block bootstrap CI fully positive [0.923, 1.666]).

### Gate 1 FAIL — H07 Multi-Asset Time-Series Momentum

Momentum strategy across equities, bonds, and crypto using 12-month lookback.

| Metric | IS | OOS |
|---|---|---|
| Sharpe | 1.25 | 0.47 |
| Max Drawdown | -12.8% | -5.4% |
| Trade Count | 9 (IS) | — |

Verdict: **FAIL** — OOS Sharpe collapses (1.25 → 0.47), insufficient trade count (9 vs ≥ 50 required), poor walk-forward consistency, permutation p = 0.426. Hypothesis: momentum signal is regime-dependent (bull-only), not a persistent edge.

### Gate 1 FAIL — H07b Expanded TSMOM

Iteration on H07 with expanded universe (20 assets). IS Sharpe declined further. Walk-forward showed zero consistency. Logged as: "time-series momentum at 12-month lookback does not generalize across asset classes in mixed-regime periods."

---

## Current Pipeline State

| Stage | Count |
|---|---|
| Hypotheses documented | 51 |
| Strategies implemented | 39 |
| Backtests run | 72 |
| Gate 1 PASS | ~11 |
| Gate 1 FAIL | ~11 |
| Paper trading | 1 (H10 v2) |
| Live trading | 0 |

---

## Repository Structure

```
quant-zero/
├── agents/               # Agent instruction files
│   ├── ceo/              #   AGENTS.md, SOUL.md, HEARTBEAT.md per agent
│   ├── research-director/
│   ├── engineering-director/
│   ├── risk-director/
│   ├── alpha-research/
│   ├── market-regime/
│   ├── strategy-coder/
│   ├── backtest-runner/
│   ├── overfit-detector/
│   └── portfolio-monitor/
├── strategies/           # Executable strategy code (vectorbt)
├── backtests/            # Results: {strategy}_{date}.json + _verdict.txt + _report.html
├── orchestrator/         # Iteration loop, Gate 1 reporter, knowledge base (41 entries)
├── research/
│   ├── hypotheses/       # One .md file per hypothesis (51 total)
│   ├── findings/         # Alpha research outputs
│   └── regimes/          # Historical regime classifications
├── scripts/              # Batch backtest runners
├── broker/               # Broker API configs (secrets via env, never committed)
├── docs/                 # Architecture, mission, templates, heartbeat archives
│   ├── heartbeats/       # Director weekly reports (engineering/, research/, risk/)
│   ├── templates/        # Heartbeat template, report templates
│   └── superpowers/      # Implementation plans and specs
└── criteria.md           # Gate acceptance criteria (CEO-locked)
```

---

## Gate 1 Report Format

Every Gate 1 evaluation produces three artifacts committed to `backtests/`:

```
backtests/{strategy_name}_{date}_report.html   # Full HTML report with charts
backtests/{strategy_name}_{date}.json          # Machine-readable metrics
backtests/{strategy_name}_{date}_verdict.txt   # Structured pass/fail verdict
```

All PRs for Gate 1 strategies include direct links to these files in the PR body and in the Paperclip ticket description.

---

## Risk Constitution (Non-Negotiable)

1. No single trade loses more than 1% of capital ($250 at $25K)
2. No single strategy holds more than 25% of capital
3. Total portfolio exposure never exceeds 80% (20% cash minimum)
4. No strategy goes live without passing all three gates
5. Any strategy that hits 1.5x its backtest max drawdown is automatically demoted to paper
6. No leverage above 2x on any position
7. No new deployment in first or last 30 minutes of US market hours
8. Monthly risk review is mandatory — if CEO skips it, all live strategies pause
9. If total portfolio drawdown exceeds 8%, pause all live trading for 48 hours
10. No agent can execute a live trade — all live order routing requires explicit CEO approval

---

## Setup

```bash
pip install anthropic vectorbt yfinance pandas numpy sqlalchemy scipy statsmodels

export ANTHROPIC_API_KEY="sk-ant-..."
export ALPACA_API_KEY="..."
export ALPACA_API_SECRET="..."

python broker/verify_feeds.py
cd orchestrator && python quant_orchestrator.py
```

---

## Documentation

| Doc | Description |
|---|---|
| [Mission Statement](docs/mission_statement.md) | Strategic goals, risk constitution, capital rules |
| [Architecture](docs/architecture.md) | System design, component diagram, data flows |
| [CEO Operations Manual](docs/ceo_operations_manual.md) | How to operate as CEO |
| [Gate 1 Intake Process](docs/gate1-intake-process.md) | Backtest → paper promotion workflow |
| [Continuous Improvement Framework](docs/continuous_improvement_framework.md) | Feedback loop design |
| [Strategy Knowledge Base](docs/strategy_knowledge_base.md) | Strategy schema and patterns |
| [Quant Orchestrator](docs/quant_orchestrator.md) | Orchestrator design reference |
| [PRD](docs/PRD.md) | Product requirements |
