# Quant Zero — Project Status & Roadmap

**Maintained by:** CEO (heartbeat review)
**Last updated:** 2026-03-16 (CEO heartbeat — H18 + H21 retirement)
**Update cadence:** Every CEO heartbeat

---

## Current Phase

**Phase 1: Backtest Discovery** — In Progress
Target: 3–5 strategies pass Gate 1.
Current pass rate: 2/13 evaluated = 15.4% (H01, H10)

---

## Strategy Pipeline Status

### Gate 1 Results

| Hypothesis | Strategy | Gate 1 Result | Notes |
|---|---|---|---|
| H01 | Bollinger Band Mean Reversion | **PASS** | First passing strategy |
| H07 | Multi-Asset TS Momentum | FAIL | Regime contamination |
| H07b | Multi-Asset TS Momentum (Expanded) | FAIL | Regime contamination |
| H07c | Multi-Asset TS Momentum + Yield Curve | FAIL | Regime contamination |
| H08 | Crypto Momentum (BTC/ETH) | FAIL | Regime contamination |
| H09 | TQQQ Weekly Snapback | FAIL | — |
| H10 | Crypto EQL/EQH Reversal v2 | **PASS** (Pattern-Based Exception) | In paper trading (blocked on config) |
| H11 | CVD Breakout | FAIL | — |
| H12 | SuperTrend ATR Momentum | FAIL | 2026-03-16 verdict |
| H13 | VWAP Anchor Reversion | FAIL | — |
| H14 | OU Mean Reversion Cloud | FAIL → **Retired** | 2026-03-16 |
| H16 | Momentum + Vol Long-Only | FAIL → **Abandoned** | — |
| H17 | Dual Momentum GEM | FAIL | OOS NaN bug; re-run pending |
| H18 | SPY/TLT Rotation v1.2 | FAIL → **Retired** | 2026-03-16 — FINAL H18 iteration; no further variants |
| H19 | VIX Volatility Targeting | FAIL → **Retired** | 2026-03-16 |
| H20 | Sector Momentum Rotation | Pending verdict | Backtest complete; verdict queued (QUA-195) |
| H21 | IBS SPY Mean Reversion | FAIL → **Retired** | 2026-03-16 — edge arbitraged away 2010-2021 |
| H22 | Turn of Month Multi-ETF | Research | Hypothesis only |
| H23 | Credit Spread Equity Timer | Retired standalone | Integrated as H21 overlay |
| H24 | Combined IBS + TOM | Research | Hypothesis only |

### Active Paperclip Tasks (Pipeline)

| Ticket | Status | Assignee | Description |
|---|---|---|---|
| QUA-207 | **Done** | CEO (closed 2026-03-16) | H18 v1.2 RETIRE confirmed |
| QUA-208 | **Done** | Engineering Director | H21 RETIRE confirmed |
| QUA-210 | Done | Backtest Runner | H18 v1.2 IS/OOS run (FAIL) |
| QUA-217 | Done | Backtest Runner | H21 IS/OOS run (FAIL) |
| QUA-161 | Blocked | Engineering Director | H10 paper trading config |
| QUA-68 | In Progress | Portfolio Monitor | Weekly reporting cadence |

---

## Folder Structure

```
quant-zero/
├── agents/              # Agent configurations (CEO, directors, ICs)
├── backtests/           # Backtest output artifacts
├── broker/              # Broker integration (Alpaca, Coinbase)
├── criteria.md          # Gate 1 criteria v1.2 (CEO-locked)
├── docs/
│   ├── PRD.md               # Product requirements
│   ├── architecture.md      # System architecture
│   ├── ceo_operations_manual.md
│   ├── continuous_improvement_framework.md
│   ├── gate1-intake-process.md
│   ├── gate1-verdicts/      # Formal Gate 1 verdict files
│   ├── heartbeats/          # Director heartbeat logs
│   ├── mission_statement.md # Risk Management Constitution
│   ├── monitoring/          # Monitoring runbooks
│   ├── project_status.md    # THIS FILE — project status & roadmap
│   ├── proposals/           # One-off research proposals / exception requests
│   ├── quant_orchestrator.md
│   ├── strategy_knowledge_base.md
│   └── templates/           # Standard templates
├── knowledge_base/      # Strategy knowledge JSON entries
├── orchestrator/        # Orchestrator loop + iteration log
├── research/
│   ├── backtest_results/
│   ├── findings/
│   ├── hypotheses/      # 24 hypotheses (H01–H24)
│   ├── regimes/
│   └── scripts/
├── strategies/          # Production strategy code (H07–H21)
├── tests/               # Unit tests
└── visualization/       # Charts and report generators
```

---

## Current Features

### Research Pipeline
- 24 documented hypotheses across momentum, mean reversion, volatility, rotation, and pattern-based strategies
- Structured hypothesis format with falsifiable rationale, entry/exit logic, parameters
- Alpha Research IC team generating new batches

### Backtesting Infrastructure
- IS/OOS walk-forward backtesting (36-month IS / 6-month OOS, 4+ windows)
- Standardized backtest result schema (JSON) persisted to `/backtests/`
- Transaction cost modeling (commissions + slippage) by asset class
- Regime-slice sub-criterion analysis (Pre-COVID, Stimulus, Rate-shock, Normalization)
- Deflated Sharpe Ratio (DSR) computation
- Parameter sensitivity testing (±20% robustness check)
- Pattern-Based Strategy Exception for sparse binary signals (v1.2)

### Gate 1 System
- Criteria locked at v1.2 with version history
- Overfit Detector agent for automated quantitative checks
- Structured pass/fail verdict format
- CEO final promotion decision workflow

### Agent Organization (Paperclip)
- Research Director + Alpha Research IC team
- Engineering Director + Strategy Coder + Backtest Runner ICs
- Risk Director + Overfit Detector + Portfolio Monitor ICs
- Full task audit trail via run IDs

### Paper Trading (Phase 2 — Partially Active)
- H10 EQL/EQH approved for paper trading (Alpaca paper API)
- Config blocked (QUA-161)

---

## Roadmap

### Near-Term (Next 2–4 Weeks)

| Priority | Item | Owner | Status |
|---|---|---|---|
| P0 | ~~Complete H18 Gate 1 verdict~~ | Engineering + Risk | **Done — RETIRE 2026-03-16** |
| P0 | ~~Complete H21 Gate 1 verdict~~ | Engineering + Risk | **Done — RETIRE 2026-03-16** |
| P0 | H20 Gate 1 verdict | Risk Director | Pending backtest delivery |
| P0 | Unblock H10 paper trading config (QUA-161) | Engineering Director | Blocked |
| P1 | H17 OOS NaN root cause fix + re-run | Engineering Director | Queued |
| P1 | TV Discovery Batch 3 hypotheses (H25+) | Research Director | In research |
| P2 | Turn of Month H22 — move to backtest | Engineering Director | Research only |
| P2 | Weekly portfolio monitoring cadence (QUA-68) | Portfolio Monitor | In progress |

### Medium-Term (1–3 Months)

| Item | Notes |
|---|---|
| Gate 2 criteria definition | For paper-to-live promotion; Risk Director to draft |
| Paper trading validation (30 days per strategy) | Comparing live paper vs. backtest; Phase 2 target |
| Options strategy pipeline | Defined-risk strategies; Phase 2+ |
| Gate 3 live trading infrastructure | CEO approval required before any live orders |
| Execution quality agent | Monitor slippage, fill quality; hire at Gate 3 approach |

### Strategic Goals (Phase 4+)

| Goal | Target | Status |
|---|---|---|
| 3–5 strategies pass Gate 1 | 2/? so far | In progress |
| 30-day paper trading validation | Per strategy | H10 queued |
| First real capital deployment | Phase 3: up to $3,750 | Gate 3 not yet defined |
| Monthly income target (1.5–3.0%) | 60 days post-live | Pre-Gate 3 |
| Portfolio Sharpe > 1.5 | Cross-strategy allocation | Not started |

---

## Open Questions

| # | Question | Owner | Status |
|---|---|---|---|
| OQ-01 | Walk-forward window length (36m/6m vs. shorter) | Risk Director | Open |
| OQ-02 | Deflated Sharpe Ratio mandatory vs. supplemental | Risk + Engineering | Resolved: mandatory at v1.2 |
| OQ-03 | Crypto exchange: Coinbase Advanced vs. Kraken | CEO | Open |
| OQ-04 | PDT constraint: margin vs. cash account for equity strategies | CEO | Open |
| OQ-05 | Execution quality agent: when to hire | Engineering Director | Open (Phase 2 start target) |
| OQ-06 | Gate 2 criteria definition | Risk Director | Not started |
| OQ-07 | Portfolio allocation model (when 3+ strategies pass Gate 1) | Risk Director | Not started |

---

## Improvement Opportunities (Feature Backlog)

**Process:** All new feature/improvement suggestions identified during heartbeat review are created as `[FEATURE]` tickets in Paperclip and assigned to the **board** for review and prioritization before agents begin work. The board decides whether to approve, reject, or defer each suggestion.

| Ticket | Priority | Title | Status |
|---|---|---|---|
| QUA-220 | Medium | Backtest Runner: OOS data quality validation (NaN prevention) | Board review |
| QUA-221 | Medium | Gate 1: structured verdict template enforcement in runner output | Board review |
| QUA-222 | Medium | Research: increase hypothesis generation cadence to 1–2/week | Board review |
| QUA-223 | Medium | Portfolio Monitor: define standard weekly report format + output path | Board review |
| QUA-224 | High | H10 paper trading: unblock QUA-161 escalation path | Board review |

---

*This file is maintained by the CEO during heartbeat reviews. Directors should flag stale or incorrect information via Paperclip comment.*
