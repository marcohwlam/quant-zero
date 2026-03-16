# Product Requirements Document — Quant Zero

**Version:** 1.0
**Date:** 2026-03-15
**Owner:** Engineering Director
**Status:** Active

---

## 1. Overview

Quant Zero is an AI-managed quantitative trading system. It uses a team of Claude-powered agents to research, code, backtest, and deploy systematic trading strategies across US equities, options, and crypto — with a human CEO making every gate decision on capital deployment.

The system is designed so that one person can operate a full quantitative trading operation without writing code or performing manual analysis.

---

## 2. Problem Statement

Retail quantitative trading faces three hard problems:

1. **Research bandwidth** — Identifying systematic edges requires reading academic papers, testing hypotheses, and iterating quickly. This is full-time work.
2. **Execution discipline** — The gap between backtest and live performance is often caused by human discretionary override (second-guessing signals, missing entries, sizing emotionally).
3. **Overfitting** — Most retail quant strategies that "work" in backtest fail live because they were curve-fit to historical noise.

Quant Zero solves all three by: delegating research and coding to AI agents, enforcing mechanical execution via broker API, and using a multi-gate validation pipeline with dedicated overfitting detection before any capital is deployed.

---

## 3. Goals

### Primary Goals

| Goal | Metric | Target |
|------|--------|--------|
| Generate consistent income | Monthly return | 1.5–3.0% |
| Preserve capital | Max portfolio drawdown | < 10% |
| Risk-adjusted returns | Sharpe ratio | > 1.5 |
| Systematic edge | Win rate | > 55% |

### Secondary Goals

- Operate without the CEO writing code
- Maintain full reproducibility of all backtests
- Produce a portfolio of uncorrelated strategies (cross-strategy correlation < 0.4)
- Time to first live dollar ≤ 90 days from system launch

### Non-Goals

- High-frequency trading (target hold period: hours to days)
- Directional options speculation (defined-risk strategies only)
- Altcoin trading (BTC and ETH only)
- Fully autonomous live trading (CEO approves all capital deployment)

---

## 4. Users

| User | Role | How they interact |
|------|------|-------------------|
| CEO (human) | Sole decision-maker for capital | Reviews gate packages, approves/rejects promotions, sets research direction |
| Engineering Director (agent) | Technical pipeline owner | Translates hypotheses to code, runs backtests, evaluates Gate 1 |
| Research Director (agent) | Strategy ideation | Generates hypotheses, monitors market regime |
| Risk Director (agent) | Risk gating and monitoring | Runs overfitting checks, monitors paper/live positions |

---

## 5. System Requirements

### 5.1 Strategy Pipeline

| Requirement | Detail |
|-------------|--------|
| SR-01 | Every strategy must have a written, falsifiable hypothesis |
| SR-02 | All backtests must run on in-sample (IS) AND out-of-sample (OOS) windows |
| SR-03 | Strategy code must be parameterized and version-controlled in `/strategies/` |
| SR-04 | Maximum 6 parameters per strategy (prevents overfitting by construction) |
| SR-05 | Backtests must model transaction costs (minimum: 0.1% round-trip) |
| SR-06 | All backtest results persisted to `/backtests/` in standardized JSON format |

### 5.2 Gate 1 Acceptance Criteria

A strategy must pass **all four** criteria to advance from backtest to paper trading:

| Metric | Minimum Threshold | Rationale |
|--------|-------------------|-----------|
| IS Sharpe ratio | > 1.0 | Baseline in-sample edge required |
| OOS Sharpe ratio | > 0.7 | Proves edge survives unseen data |
| Max drawdown | < 20% | Capital preservation constraint |
| Minimum trades | ≥ 100 | Statistical significance of results |

### 5.3 Risk Management (Non-Negotiable)

| Rule | Limit |
|------|-------|
| Max loss per trade | 1% of total capital |
| Max capital per strategy | 25% |
| Max total portfolio exposure | 80% (20% always in cash) |
| Max leverage | 2× on any position |
| PDT compliance | Max 3 day trades / 5 days in margin accounts |
| Emergency circuit breaker | Pause all live trading if portfolio drawdown exceeds 8% |

### 5.4 Data Requirements

| Asset Class | Data Source | Frequency | Notes |
|-------------|-------------|-----------|-------|
| US Equities / ETFs | yfinance | Daily OHLCV | Free; adequate for backtesting |
| Options | Alpaca API | Daily | Phase 2+ (paper trading onward) |
| Crypto (BTC/ETH) | Exchange API | Daily/hourly | Coinbase Advanced or Kraken |

---

## 6. Functional Requirements

### 6.1 Orchestrator

- FR-01: The orchestrator runs a propose → backtest → evaluate → learn loop
- FR-02: Each iteration is logged to SQLite (`orchestrator/iteration_log.db`) with full metrics
- FR-03: Learnings are saved to the knowledge base (`orchestrator/knowledge_base/`) for future iterations
- FR-04: The orchestrator halts at gate decisions and waits for CEO input — it does not auto-promote

### 6.2 Agent Pipeline

- FR-05: Research Director generates strategy hypotheses as structured documents in `research/hypotheses/`
- FR-06: Engineering Director delegates coding to Strategy Coder and backtesting to Backtest Runner via Paperclip tasks
- FR-07: Backtest Runner produces standardized reports with: IS Sharpe, OOS Sharpe, MDD, win rate, profit factor, trade log
- FR-08: Risk Director runs Overfit Detector on all Gate 1 candidates before submitting verdict to CEO
- FR-09: All agent coordination uses Paperclip (task assignment, status updates, comment threads)

### 6.3 Broker Integration

- FR-10: Paper trading via Alpaca paper API (`https://paper-api.alpaca.markets`)
- FR-11: Crypto paper trading via exchange sandbox (Coinbase or Kraken testnet)
- FR-12: API keys never committed to git; injected via environment variables only
- FR-13: Live order routing is disabled until Gate 3 approval by CEO

---

## 7. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Backtest reproducibility | Given same parameters, results must be bit-identical |
| Code quality | All strategy code must pass linting before backtesting |
| Audit trail | Every Paperclip action linked to a run ID for traceability |
| Documentation | All passing strategies have a narrative report alongside metrics |
| Security | No secrets in git; `.env` in `.gitignore` |

---

## 8. Phased Rollout

| Phase | Capital | Milestone |
|-------|---------|-----------|
| Phase 0: Foundation | $0 | Infrastructure setup, first 5 iterations |
| Phase 1: Backtest Discovery | $0 | 3–5 strategies pass Gate 1 |
| Phase 2: Paper Validation | $0 (simulated) | 30 days paper per strategy; compare to backtest |
| Phase 3: Small Live | Up to $3,750 (15%) | First real capital, 5% per strategy max |
| Phase 4: Scale | Up to $20,000 (80%) | Full allocation on proven strategies |
| Phase 5: Compound | Reinvestment | Portfolio self-sustaining; monthly income target hit |

---

## 9. Open Questions / Decisions Pending

| # | Question | Owner | Status |
|---|----------|-------|--------|
| OQ-01 | Walk-forward window length (36-month train / 6-month test vs. shorter) | Risk Director | Open |
| OQ-02 | Whether to add Deflated Sharpe Ratio as mandatory Gate 1 metric | Risk Director + Engineering Director | Open |
| OQ-03 | Crypto exchange selection: Coinbase Advanced vs. Kraken | CEO | Open |
| OQ-04 | PDT constraint: margin account vs. cash account for equity strategies | CEO | Open |
| OQ-05 | When to hire Execution Quality Agent (Phase 2 start or Gate 3 approach) | Engineering Director | Open |

---

*This document is maintained by Engineering Director. Changes to Gate criteria require CEO sign-off.*
