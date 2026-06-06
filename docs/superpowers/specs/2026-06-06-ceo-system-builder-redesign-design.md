# Quant Zero CEO Redesign — System Builder

**Date:** 2026-06-06
**Status:** Approved design, pending implementation
**Author:** CEO redesign brainstorm

---

## Problem

The current Quant Zero CEO has a working skeleton but four gaps against the intended operating model:

1. The Gate 1 criteria (`criteria.md`) target daily/swing timeframes only. There are no minute-level KPIs.
2. There is no enforced workspace directory structure.
3. There is no script-over-LLM workflow discipline.
4. The CEO `HEARTBEAT.md` runs proactive pipeline review every 30 seconds, conflating reactive event handling with periodic strategic review. This wastes tokens and produces action noise.

The redesign reframes the CEO as a **system builder**: it owns how the organization is structured and how every agent behaves, sets and locks standards, and never performs ground work itself.

---

## Goals

1. Find the best quant KPI for minute-level trading (objective function balancing return and stability).
2. Ensure the company sources strategies from quality books/sources, backtests them, and meets the KPI.
3. CEO maintains a consistent workspace directory structure for all agents.
4. CEO ensures agents work efficiently: repeatable work runs via scripts, LLM use is minimized, Python calls maximized.
5. CEO keeps agents progressing toward goals on the dashboard and unblocks them.
6. CEO never does ground work — it only builds the system other agents work within.
7. The company sets a goal for agents to find a strategy meeting all KPIs with a detailed backtest and report.
8. CEO ensures the paper trading system and signal pipeline are live and monitored.

---

## Key Decisions (locked during brainstorm)

| Decision | Choice |
|---|---|
| Minute-level vs daily track | Replace — rewrite Gate 1 entirely for minute timeframe |
| Asset classes | All (equities intraday, crypto, futures/ETFs), each with independent KPIs |
| Strategy style | Style-agnostic KPIs — research discovers the style |
| Backtest period | 2 years, 2022-01 to 2024-12 (rate-shock + normalization) |
| Script vs LLM enforcement | Workflow contracts define boundaries; agents decide their own script implementations |
| Reactive vs proactive | Heartbeat = reactive only; Routines = proactive scheduled work |
| KPI methodology owner | New dedicated Quant Metrics agent under Research Director, Risk Director co-signs |
| CEO ownership scope | Entire agent definition layer (AGENTS.md, SOUL.md, TOOLS.md, HEARTBEAT.md) + locked policy docs |
| Git workflow | Org-wide standard, single source of truth, all agents follow |
| KPI thresholds | Placeholders now; calibrated with real data later, then CEO-locked |

---

## Architecture

```
CEO  (System Builder — owns structure and behavior, does no ground work)
|
+-- Heartbeat (reactive, event-driven)
|     wake on: comment, assignment, blocker_resolved, children_completed
|     actions: checkout assigned work, unblock directors, route <=5 issues
|     never: scan full backlog proactively, do ground work
|
+-- Routines (proactive, scheduled)
|     daily-morning  -> pipeline health check
|     daily-evening  -> workspace compliance audit
|     weekly-kpi     -> criteria + KPI drift review
|     weekly-trading -> paper trading signal status
|
+-- Owned Documents (source of truth)
|     org-wide policy:  criteria.md, workspace-structure.md,
|                       docs/kpi-minute-level.md, workflow-contracts/*
|     agent definitions: agents/<name>/{AGENTS,SOUL,TOOLS,HEARTBEAT}.md
|
+-- Org Structure
      Research Director
        +-- Alpha Research
        +-- Market Regime
        +-- Quant Metrics (NEW) -> owns KPI methodology
      Engineering Director
        +-- Strategy Coder
        +-- Backtest Runner
        +-- Backend Developer
      Risk Director
        +-- Overfit Detector
        +-- Portfolio Monitor
```

### Data flow

```
Board / Events
     |
     v
Heartbeat --> route to Directors --> Directors manage ICs --> work products
     |
     | (daily-morning routine)
     v
Pipeline Health Check --> creates "stalled" issue if a director is idle
     |
     | (weekly-kpi routine)
     v
KPI / Criteria Review --> CEO memo issue if drift found --> CEO locks criteria.md
     |
     | (weekly-trading routine)
     v
Paper Trading Status --> creates infra goal if not live; flags zero-signal weeks
```

---

## Component Detail

### 1. CEO Role Redefinition

Add to top of `agents/ceo/AGENTS.md`:

```markdown
## Role: System Builder

You build the system. You do not work in the system.

- Write standards, contracts, goals, and agent definitions — never strategies, code, or analysis.
- If you find yourself writing Python, running backtests, or analyzing data: stop, create an issue, assign it to the right director.
- Your output is: documents, Paperclip issues, goals, and agent instructions.
```

### 2. Strategic Priorities (expand from 4 to 6)

```markdown
1. Pipeline health — research -> engineering -> risk must always be flowing.
2. Gate 1 integrity — criteria.md is CEO-locked, minute-level KPIs per asset class.
3. Workspace integrity — every agent works within workspace-structure.md.
4. Workflow discipline — agents follow workflow-contracts/, script > LLM for repeatable work.
5. Capital preservation — Risk Director's constitution is non-negotiable.
6. Paper trading readiness — signal pipeline and broker connection live and monitored.
```

### 3. CEO Ownership Scope

The CEO authors and gatekeeps the entire agent definition layer. No agent modifies these without a CEO-approved PR.

**Org-wide policy (CEO-locked):**

| Document | Purpose | Update trigger |
|---|---|---|
| `criteria.md` | Gate 1 acceptance criteria (minute-level, per asset) | Risk Director recommendation + CEO review |
| `workspace-structure.md` | Canonical directory layout | Engineering Director proposal + CEO approval |
| `docs/kpi-minute-level.md` | KPI spec per asset class | Quant Metrics deliverable + Risk co-sign + CEO lock |
| `workflow-contracts/git.md` | Branch + PR + commit standard — all agents | CEO-locked |
| `workflow-contracts/<role>.md` | LLM vs script boundary per role | Agent request + CEO judgment |

**Agent definitions (CEO controls every agent's behavior):**

For each `agents/<name>/`: `AGENTS.md` (role, responsibilities, chain of command), `SOUL.md` (persona, voice, posture), `TOOLS.md` (capabilities), `HEARTBEAT.md` (reactive checklist if applicable). When org needs change, the CEO edits these via PR.

### 4. Git Workflow (org-wide standard)

Single source of truth: `workflow-contracts/git.md`. Every agent references it; none keeps its own copy.

Every file change (code, reports, configs, agent definitions) follows:
1. Feature branch: `feat/QUA-<N>-short-description`
2. Commit with `Co-Authored-By: Paperclip <noreply@paperclip.ing>`
3. Push, open PR, post PR URL on the Paperclip ticket
4. Auto-merge

Rules: never commit secrets; never force-push main.

Each agent's `AGENTS.md` ends with:
```markdown
## Git Workflow
Follow `workflow-contracts/git.md`. No exceptions.
```

The existing Git Sync Workflow block (CEO/AGENTS.md lines 64-101) is extracted into `workflow-contracts/git.md`.

### 5. Reactive Heartbeat vs Proactive Routines

`agents/ceo/HEARTBEAT.md` is trimmed to reactive work only:
- Respond to `PAPERCLIP_WAKE_REASON` events.
- Checkout and work assigned issues.
- Unblock directors.
- Route unassigned issues (<= 5 per heartbeat).

Proactive work moves to Routines (defined in AGENTS.md, created via the routines API):

**daily-morning — Pipeline Health Check**
For each director: confirm at least one `in_progress` issue. If idle, create a "pipeline stalled" issue assigned to that director with last known work as context. Check for `blocked` issues idle > 24h; unblock or escalate.

**daily-evening — Workspace Compliance Audit**
Scan repo for files outside `workspace-structure.md` canonical paths. On violations, create an issue assigned to Engineering Director. Do not fix violations directly.

**weekly-kpi — KPI and Criteria Review**
Pull latest Gate 1 verdicts from `backtests/`. Detect criteria consistently causing false negatives. If a pattern is found, document in a CEO memo issue for board-visible review. Never change `criteria.md` without documented rationale.

**weekly-trading — Paper Trading Status**
Confirm the paper trading signal pipeline is live (Engineering Director owns it). If not set up, create goal "Paper Trading Infrastructure" for Engineering Director. If live, check last 7 days' signal count; flag zero-signal weeks to Research Director.

### 6. Minute-Level criteria.md Rewrite (v2.0)

```markdown
# Gate 1 Acceptance Criteria — Minute-Level (v2.0)

## Required Test Period
- 2 years: 2022-01 to 2024-12 (rate-shock + normalization).
- Walk-forward: 6 non-overlapping windows, 3-month IS / 1-month OOS.
- Per-asset bar definition (1-min equities RTH, 1-min crypto 24/7, 1-min futures session).

## Cost Realism (top-level gate — the minute-level killer)
Backtests MUST model, or auto-reject:
- Equities: $0.005/share + half-spread slippage + 0.02% market impact (PLACEHOLDER).
- Crypto: 0.05% taker + 0.03% slippage (PLACEHOLDER).
- Futures: per-contract commission + 1 tick slippage (PLACEHOLDER).
- Net Sharpe is the only Sharpe that gates. Gross Sharpe is reported, never gates.

## Sharpe Annualization
- Aggregate intraday PnL to daily returns, then annualize with sqrt(252).
- Per-bar Sharpe is forbidden as a gate (inflates via high bar count).

## Quantitative Thresholds (per asset class — PLACEHOLDERS, calibrate with real data)
| Metric | Equities intraday | Crypto | Futures |
|---|---|---|---|
| Net OOS Sharpe | > TBD | > TBD | > TBD |
| Net profit per trade (bps, after cost) | > TBD | > TBD | > TBD |
| Max intraday drawdown | < TBD | < TBD | < TBD |
| Trade count (IS) | > TBD | > TBD | > TBD |
| Cost-to-gross-profit ratio | < TBD | < TBD | < TBD |

## Minute-Level-Specific Guards
- Latency: signal-to-fill delay >= 1 bar (no same-bar fills).
- Overnight: explicit flat-by-close OR documented overnight risk.
- Look-ahead: no use of a bar's own close before the bar completes.
- Intraday regime: report performance split by session (open / midday / close).

## Per-Asset KPI Spec
See docs/kpi-minute-level.md (owned by Quant Metrics, Risk co-signed, CEO-locked).

## Automatic Disqualification
- Net OOS Sharpe below asset threshold.
- Same-bar fill assumption (latency cheating).
- Cost-to-profit ratio above asset ceiling.
- Profitable gross but unprofitable net.

## Governance
Only the CEO modifies these criteria, after documented review. Versioned in git history.
Thresholds marked PLACEHOLDER are calibrated by Engineering Director / Quant Metrics with
real 2022-2024 data, then CEO-locked. Setting numbers without data violates the data-driven rule.
```

### 7. New Agent — Quant Metrics

Reports to Research Director. Owns the minute-level KPI objective function (return vs stability). Every revision requires Risk Director co-sign before the CEO locks it into `criteria.md` / `docs/kpi-minute-level.md`.

```
agents/quant-metrics/
  AGENTS.md   Role: define and refine the minute-level KPI objective function balancing
              return and stability; deliver docs/kpi-minute-level.md; every revision needs
              Risk Director co-sign before CEO lock. Reports to Research Director.
  SOUL.md     Persona: rigorous quant researcher, skeptical of single-metric optimization,
              thinks in distributions not point estimates.
  TOOLS.md    Python stats stack; read-only access to backtest results.
```

### 8. workspace-structure.md (new, CEO-locked)

Documents the canonical layout already present in the repo so the daily-evening audit has a reference:

```markdown
# Canonical Workspace Structure (CEO-locked)

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
workflow-contracts/ per-role LLM-vs-script contracts + git.md
criteria.md         Gate 1 (CEO-locked)
workspace-structure.md  this file (CEO-locked)

Rules:
- New top-level directories require CEO approval via PR.
- Strategy code lives only in strategies/. Backtest outputs only in backtests/.
- Sourced material (books, papers) lands in knowledge_base/ with provenance.
```

### 9. workflow-contracts/<role>.md (new)

Each contract states which steps MUST use scripts/Python and which MAY use LLM. Agents decide their own script implementations within those boundaries.

Example shape for `workflow-contracts/research.md`:
```markdown
# Research Agent Workflow Contract

MUST be script/Python (repeatable, deterministic):
- Data loading, cleaning, resampling to minute bars.
- Factor/indicator computation.
- Backtest execution and metric calculation.
- Report generation from a template.

MAY use LLM (judgment, synthesis):
- Hypothesis formulation from sourced material.
- Interpreting why an edge exists (economic rationale).
- Deciding which hypothesis to pursue next.

Rule: if a step runs more than twice, it becomes a script. Agents own their script design.
```

Analogous contracts for `engineering.md` and `risk.md`.

---

## Goals the CEO Creates First

1. **Define the minute-level KPI objective function** — owner Research Director, delegated to Quant Metrics; deliverable `docs/kpi-minute-level.md`; gated by Risk co-sign + CEO lock. Blocks Gate 1 v2.0 finalization.
2. **Calibrate Gate 1 v2.0 thresholds with real 2022-2024 data** — owner Engineering Director; replaces PLACEHOLDER values; CEO locks.
3. **Source strategies from quality references** — owner Research Director; populate `knowledge_base/` with book/paper-derived hypotheses.
4. **Find a strategy meeting all minute-level KPIs** — the core company goal; full backtest + report; passes Gate 1 v2.0.
5. **Paper Trading Infrastructure** — owner Engineering Director; live signal pipeline + broker connection, monitored by weekly-trading routine.

---

## Implementation Order

1. Extract `workflow-contracts/git.md` from current CEO AGENTS.md.
2. Write `workspace-structure.md` and `workflow-contracts/{research,engineering,risk}.md`.
3. Rewrite `criteria.md` to v2.0 (placeholders).
4. Create `agents/quant-metrics/{AGENTS,SOUL,TOOLS}.md`.
5. Update `agents/ceo/AGENTS.md` (role, priorities, ownership, routines) and trim `HEARTBEAT.md` to reactive-only.
6. Add the `## Git Workflow` reference block to every existing agent's AGENTS.md.
7. Update Research Director AGENTS.md to include Quant Metrics in its team.
8. CEO creates the five goals and the routines via the Paperclip API.

All changes follow the git workflow: feature branch, PR, auto-merge.

---

## Out of Scope

- Calibrating actual KPI threshold numbers (separate data-driven goal).
- Live trading (board approval required; never automated).
- Broker selection and integration detail (Engineering Director goal).
- Rewriting existing daily-track backtests (the daily track is replaced going forward, not retroactively re-run).
