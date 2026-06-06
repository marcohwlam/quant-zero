# CEO System-Builder Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconfigure the Quant Zero CEO into a system builder that owns org structure, agent behavior, and locked standards while never doing ground work, and stand up minute-level Gate 1 criteria, a dedicated KPI agent, and a split-owned dashboard.

**Architecture:** Pure markdown/config authoring in the `quant-zero` repo plus a final runtime step where the CEO creates goals and routines through the Paperclip API. Git workflow is DRY'd into a single canonical contract referenced by every agent. No application code, no tests — verification is `grep`/`git` based.

**Tech Stack:** Markdown agent definitions, Paperclip REST API (curl), git feature-branch workflow.

**Working branch:** All work happens on `docs/ceo-system-builder-redesign-spec` (already checked out) or a fresh `feat/QUA-ceo-redesign` branch. Confirm before starting:

```bash
cd /home/lamho/Documents/repos/quant-zero && git branch --show-current
```

**Spec reference:** `docs/superpowers/specs/2026-06-06-ceo-system-builder-redesign-design.md`

**Scope note:** This plan configures the CEO operating system. It does NOT implement downstream deliverables that other agents own as goals: the dashboard generator code (`scripts/build_dashboard.py`), KPI threshold calibration, or actual strategy research. Those are created as Paperclip goals in Task 11.

---

### Task 1: Create the canonical git workflow contract

**Files:**
- Create: `workflow-contracts/git.md`

- [ ] **Step 1: Create the directory and file**

Create `workflow-contracts/git.md` with this exact content:

```markdown
# Git Workflow Contract (CEO-locked)

The single source of truth for git workflow across ALL Quant Zero agents.
No agent keeps its own copy. Every agent's AGENTS.md references this file.

## When to use

After completing any ticket that produces file changes (code, reports, configs,
heartbeats, knowledge base updates, agent definitions).

## Steps

1. Create a feature branch named after the ticket:
   ```bash
   git checkout -b feat/QUA-<N>-short-description
   ```

2. Stage and commit all changed files:
   ```bash
   git add <changed files>
   git commit -m "feat(QUA-<N>): <short description>

   Co-Authored-By: Paperclip <noreply@paperclip.ing>"
   ```

3. Push the branch to origin:
   ```bash
   git push -u origin feat/QUA-<N>-short-description
   ```

4. Create a PR using the GitHub CLI:
   ```bash
   gh pr create --title "feat(QUA-<N>): <short description>" --body "Closes QUA-<N>"
   ```

5. Post the PR URL as a comment on the Paperclip ticket and notify your manager.

6. Auto-merge the PR immediately after creation:
   ```bash
   gh pr merge --merge --auto
   ```

## Rules

- Never commit `.env` files, secrets, or credentials.
- Never force-push to `main`.
- Always include `Co-Authored-By: Paperclip <noreply@paperclip.ing>` in every commit.
- One feature branch per ticket. Do not commit unrelated work onto another ticket's branch.
```

- [ ] **Step 2: Verify the file exists**

Run: `cat /home/lamho/Documents/repos/quant-zero/workflow-contracts/git.md | head -5`
Expected: prints the `# Git Workflow Contract (CEO-locked)` header.

- [ ] **Step 3: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add workflow-contracts/git.md
git commit -m "feat: add canonical git workflow contract

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 2: Replace per-agent git blocks with a reference

Every agent currently duplicates a ~40-line "Git Sync Workflow" section. Replace each with a one-line reference to `workflow-contracts/git.md`.

**Files (Modify — the trailing `## Git Sync Workflow` section in each):**
- `agents/alpha-research/AGENTS.md`
- `agents/backend-developer/AGENTS.md`
- `agents/backtest-runner/AGENTS.md`
- `agents/engineering-director/AGENTS.md`
- `agents/market-regime/AGENTS.md`
- `agents/overfit-detector/AGENTS.md`
- `agents/portfolio-monitor/AGENTS.md`
- `agents/research-director/AGENTS.md`
- `agents/risk-director/AGENTS.md`
- `agents/strategy-coder/AGENTS.md`

(The CEO is handled in Task 9. Do not touch `agents/ceo/` here.)

- [ ] **Step 1: Confirm which agents have a git block**

Run:
```bash
cd /home/lamho/Documents/repos/quant-zero
grep -rl "## Git Sync Workflow" agents/ | grep -v agents/ceo
```
Expected: the 10 files listed above (some agents may lack the block — only edit those that have it).

- [ ] **Step 2: For each file, delete from the `## Git Sync Workflow` heading to end of file and replace with the reference block**

The git section is always the last section in each file. For each file, remove everything from the line `## Git Sync Workflow` through the end of the file, and append:

```markdown
## Git Workflow

Follow `workflow-contracts/git.md`. No exceptions.
```

Use this command per file (example for alpha-research), repeating for all 10:

```bash
cd /home/lamho/Documents/repos/quant-zero
f=agents/alpha-research/AGENTS.md
# Cut everything from the Git Sync Workflow heading onward
sed -i '/^## Git Sync Workflow$/,$d' "$f"
# Append the reference block
printf '## Git Workflow\n\nFollow `workflow-contracts/git.md`. No exceptions.\n' >> "$f"
```

Repeat with `f=` set to each of the 10 paths.

- [ ] **Step 3: Verify no duplicated git blocks remain (outside the contract)**

Run:
```bash
cd /home/lamho/Documents/repos/quant-zero
grep -rl "## Git Sync Workflow" agents/ ; echo "exit: $?"
grep -rc "Follow \`workflow-contracts/git.md\`" agents/ | grep -v ":0"
```
Expected: first grep prints nothing (no old blocks left); second prints the 10 files each with count 1.

- [ ] **Step 4: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add agents/
git commit -m "refactor: DRY agent git workflow into single contract reference

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 3: Create the canonical workspace structure document

**Files:**
- Create: `workspace-structure.md`

- [ ] **Step 1: Create the file**

Create `workspace-structure.md` with this exact content:

```markdown
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
```

- [ ] **Step 2: Verify**

Run: `head -3 /home/lamho/Documents/repos/quant-zero/workspace-structure.md`
Expected: prints the `# Canonical Workspace Structure (CEO-locked)` header.

- [ ] **Step 3: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add workspace-structure.md
git commit -m "feat: add CEO-locked workspace structure standard

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 4: Create per-role workflow contracts (script vs LLM)

**Files:**
- Create: `workflow-contracts/research.md`
- Create: `workflow-contracts/engineering.md`
- Create: `workflow-contracts/risk.md`

- [ ] **Step 1: Create `workflow-contracts/research.md`**

```markdown
# Research Agent Workflow Contract

Defines which steps MUST run as scripts/Python and which MAY use LLM judgment.
Agents own their own script implementations within these boundaries.

## MUST be script/Python (repeatable, deterministic)
- Data loading, cleaning, resampling to minute bars.
- Factor / indicator computation.
- Statistical tests (cointegration, half-life, IC, Hurst).
- Backtest execution and metric calculation.
- Report generation from a template.

## MAY use LLM (judgment, synthesis)
- Hypothesis formulation from sourced material.
- Interpreting why an edge exists (economic rationale).
- Deciding which hypothesis to pursue next.

## Rule
If a step runs more than twice, it becomes a script. Agents own their script design.
```

- [ ] **Step 2: Create `workflow-contracts/engineering.md`**

```markdown
# Engineering Agent Workflow Contract

## MUST be script/Python (repeatable, deterministic)
- Strategy code, backtest harness, walk-forward splitting.
- Transaction-cost and slippage modeling.
- Metric computation (net Sharpe, drawdown, trade stats).
- Dashboard generation (`scripts/build_dashboard.py`).
- Data pipeline and broker/paper-trading connectors.

## MAY use LLM (judgment, synthesis)
- Translating a hypothesis spec into a coding approach.
- Debugging interpretation and root-cause reasoning.
- Choosing which infrastructure task to prioritize.

## Rule
If a step runs more than twice, it becomes a script. Agents own their script design.
Backtests and metric calculations are NEVER produced by LLM free-text — only by code.
```

- [ ] **Step 3: Create `workflow-contracts/risk.md`**

```markdown
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
```

- [ ] **Step 4: Verify all three exist**

Run: `ls /home/lamho/Documents/repos/quant-zero/workflow-contracts/`
Expected: `engineering.md  git.md  research.md  risk.md`

- [ ] **Step 5: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add workflow-contracts/research.md workflow-contracts/engineering.md workflow-contracts/risk.md
git commit -m "feat: add per-role script-vs-LLM workflow contracts

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 5: Rewrite criteria.md for minute-level (v2.0)

**Files:**
- Modify (full replace): `criteria.md`

This replaces the entire daily/swing criteria with minute-level v2.0. Preserve the prior version in git history (the commit itself preserves it).

- [ ] **Step 1: Replace the entire contents of `criteria.md`**

```markdown
# Gate 1 Acceptance Criteria — Minute-Level (v2.0)

**Version:** 2.0
**Locked by:** CEO
**Status:** LOCKED — only the CEO may modify these criteria after lock.
**Supersedes:** v1.3 (daily/swing). The daily track is replaced going forward;
prior daily-track backtests are not retroactively re-run.

---

## Purpose

Gate 1 is the first quality checkpoint in the minute-level strategy promotion pipeline.
A strategy must pass Gate 1 before it is eligible for paper trading. At minute resolution,
the dominant failure mode is transaction cost, not curve-fitting — the criteria reflect that.

---

## Required Test Period

| Parameter | Requirement | Rationale |
|-----------|-------------|-----------|
| Backtest window | 2 years: 2022-01 to 2024-12 | Covers rate-shock (2022) and normalization (2023-2024). |
| Walk-forward windows | 6 non-overlapping | 3-month in-sample / 1-month out-of-sample each. |
| Bar definition | Per asset class | 1-min equities RTH; 1-min crypto 24/7; 1-min futures session. |

---

## Cost Realism (top-level gate — the minute-level killer)

Backtests MUST model the following, or the strategy is auto-rejected:

| Asset | Cost model (PLACEHOLDER — calibrate with real data) |
|-------|------------------------------------------------------|
| Equities | $0.005/share + half-spread slippage + 0.02% market impact |
| Crypto | 0.05% taker + 0.03% slippage |
| Futures | per-contract commission + 1 tick slippage |

Net Sharpe is the only Sharpe that gates. Gross Sharpe is reported, never gates.

---

## Sharpe Annualization

- Aggregate intraday PnL to daily returns, then annualize with sqrt(252).
- Per-bar Sharpe is forbidden as a gate (it inflates with bar count).

---

## Quantitative Thresholds (per asset class)

PLACEHOLDERS — calibrated by Engineering Director / Quant Metrics with real 2022-2024 data,
then CEO-locked. Setting numbers without data violates the data-driven rule.

| Metric | Equities intraday | Crypto | Futures |
|---|---|---|---|
| Net OOS Sharpe | > TBD | > TBD | > TBD |
| Net profit per trade (bps, after cost) | > TBD | > TBD | > TBD |
| Max intraday drawdown | < TBD | < TBD | < TBD |
| Trade count (IS) | > TBD | > TBD | > TBD |
| Cost-to-gross-profit ratio | < TBD | < TBD | < TBD |

The objective function that balances return and stability across these metrics is owned by
the Quant Metrics agent and specified in `docs/kpi-minute-level.md` (Risk co-signed, CEO-locked).

---

## Minute-Level-Specific Guards

- Latency: signal-to-fill delay >= 1 bar (no same-bar fills).
- Overnight: explicit flat-by-close OR documented overnight risk.
- Look-ahead: no use of a bar's own close before the bar completes.
- Intraday regime: report performance split by session (open / midday / close).

---

## Per-Asset KPI Spec

See `docs/kpi-minute-level.md` — owned by Quant Metrics, Risk co-signed, CEO-locked.

---

## Automatic Disqualification (any single flag = reject)

- Net OOS Sharpe below the asset threshold.
- Same-bar fill assumption (latency cheating).
- Cost-to-profit ratio above the asset ceiling.
- Profitable gross but unprofitable net.
- Look-ahead bias detected (rewrite and re-test from scratch).

---

## Governance

- Only the CEO modifies these criteria, after a documented review with rationale.
- Any change is versioned (increment version, preserve prior version in git history).
- PLACEHOLDER thresholds are filled only with data-backed calibration, then CEO-locked.
- Relaxing criteria requires higher justification than tightening.

### Version History

| Version | Date | Change | Rationale |
|---------|------|--------|-----------|
| 1.0–1.3 | 2026-03 | Daily/swing criteria | Preserved in git history. |
| 2.0 | 2026-06-06 | Rewrite for minute-level, all assets | Company pivot to minute-level trading; cost realism promoted to top-level gate; thresholds deferred to data calibration. |
```

- [ ] **Step 2: Verify**

Run: `head -3 /home/lamho/Documents/repos/quant-zero/criteria.md`
Expected: `# Gate 1 Acceptance Criteria — Minute-Level (v2.0)`

- [ ] **Step 3: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add criteria.md
git commit -m "feat: rewrite Gate 1 criteria for minute-level (v2.0)

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 6: Create the Quant Metrics agent

**Files:**
- Create: `agents/quant-metrics/AGENTS.md`
- Create: `agents/quant-metrics/SOUL.md`
- Create: `agents/quant-metrics/TOOLS.md`

- [ ] **Step 1: Create `agents/quant-metrics/AGENTS.md`**

```markdown
# Quant Metrics Agent

You are the Quant Metrics Agent at Quant Zero. You report to the Research Director.
You own the minute-level KPI methodology — the objective function that balances return
and stability for strategy evaluation.

## Chain of Command

- **Reports to:** Research Director
- **Manages:** None
- **Mandatory co-signer:** Risk Director (every KPI revision requires Risk sign-off before CEO lock)

## Mission

Define and refine the minute-level KPI objective function. Produce and maintain
`docs/kpi-minute-level.md`. Your output determines how every strategy is judged for
return vs stability, so methodological rigor is the whole job.

## Responsibilities

- Research and define the objective function balancing return and stability for minute-level strategies, per asset class.
- Deliver and maintain `docs/kpi-minute-level.md`.
- Propose calibrated values for the PLACEHOLDER thresholds in `criteria.md`, backed by real 2022-2024 data.
- Every revision: obtain Risk Director co-sign, then submit to CEO to lock.
- Think in distributions, not point estimates. Reject single-metric optimization.

## Deliverable: docs/kpi-minute-level.md

Must specify, per asset class (equities intraday, crypto, futures):
- The return measure (net of modeled costs).
- The stability measure (drawdown, consistency across walk-forward windows, regime spread).
- How the two combine into a single ranking objective.
- The rationale for the chosen weighting, with sensitivity analysis.

## Governance

- You propose; you do not lock. The CEO locks `criteria.md` and `docs/kpi-minute-level.md`.
- No revision advances without Risk Director co-sign recorded in the QUA ticket.

## Workflow Contract

Follow `workflow-contracts/research.md`. Metric computation and calibration are scripts;
methodology rationale is your LLM judgment.

## Paperclip Workflow

You operate in heartbeat mode. Each heartbeat:
1. Check your Paperclip assignments.
2. Checkout the highest-priority task.
3. Read directives from the Research Director.
4. Run calibration scripts / update methodology.
5. Update `docs/kpi-minute-level.md`, request Risk co-sign, then notify CEO for lock.
6. Update task status with a clear comment before exiting.

## References

- `$AGENT_HOME/HEARTBEAT.md` — execution checklist
- `$AGENT_HOME/SOUL.md` — values and operating principles
- `criteria.md` — Gate 1 criteria (the thresholds you calibrate)
- `docs/kpi-minute-level.md` — your primary deliverable
- `workflow-contracts/research.md` — script vs LLM boundary

## Git Workflow

Follow `workflow-contracts/git.md`. No exceptions.
```

- [ ] **Step 2: Create `agents/quant-metrics/SOUL.md`**

```markdown
# SOUL.md — Quant Metrics Persona

You are a rigorous quant researcher.

## Operating Principles

- Think in distributions, not point estimates. A single Sharpe number hides the tails.
- Distrust single-metric optimization. Any metric you can name can be gamed; design against it.
- Stability and return are a trade-off, not a ranking. State the trade-off explicitly.
- Every threshold must be earned from data. "It feels right" is not a calibration.
- Sensitivity first. If a small change in weighting flips the ranking, the objective is fragile.
- Show your work. Methodology that cannot be reproduced from a script is not methodology.

## Voice

- Precise and quantitative. Lead with the number and the uncertainty around it.
- Name assumptions out loud. Flag where a choice is judgment, not evidence.
- Short. A KPI definition is a contract, not an essay.
```

- [ ] **Step 3: Create `agents/quant-metrics/TOOLS.md`**

```markdown
# TOOLS.md — Quant Metrics Tools

## Available

- Python statistical stack (numpy, pandas, scipy, statsmodels).
- Read-only access to `backtests/` verdicts and reports.
- Read-only access to `paper_trading/` results for live-vs-backtest comparison.
- File read/write in `docs/` for `kpi-minute-level.md`.
- Web search for methodology references (DSR, PBO, deflated metrics literature).

## Constraints

- Read-only on strategy code and backtest outputs — you measure, you do not author strategies.
- You do not run live trades or modify broker connectors.
- You do not lock `criteria.md`; you propose and the CEO locks.
```

- [ ] **Step 4: Verify**

Run: `ls /home/lamho/Documents/repos/quant-zero/agents/quant-metrics/`
Expected: `AGENTS.md  SOUL.md  TOOLS.md`

- [ ] **Step 5: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add agents/quant-metrics/
git commit -m "feat: add Quant Metrics agent (KPI methodology owner)

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 7: Add Quant Metrics to the Research Director's team

**Files:**
- Modify: `agents/research-director/AGENTS.md:3` and `:9-12`

- [ ] **Step 1: Update the opening line (line 3)**

Replace:
```
You are the Research Director at Quant Zero, a quantitative trading firm. You report to the CEO and manage two agents: the Alpha Research Agent and the Market Regime Agent.
```
With:
```
You are the Research Director at Quant Zero, a quantitative trading firm. You report to the CEO and manage three agents: the Alpha Research Agent, the Market Regime Agent, and the Quant Metrics Agent.
```

- [ ] **Step 2: Update the Chain of Command block**

Replace:
```
- **Reports to:** CEO
- **Manages:** Alpha Research Agent, Market Regime Agent
```
With:
```
- **Reports to:** CEO
- **Manages:** Alpha Research Agent, Market Regime Agent, Quant Metrics Agent
```

- [ ] **Step 3: Add a Quant Metrics responsibility bullet**

After the existing "Maintain and extend the knowledge base with research findings" bullet, add:
```
- Direct the Quant Metrics Agent to define and refine the minute-level KPI objective function; ensure every KPI revision is Risk-co-signed before CEO lock
```

- [ ] **Step 4: Verify**

Run: `grep -n "Quant Metrics" /home/lamho/Documents/repos/quant-zero/agents/research-director/AGENTS.md`
Expected: at least 3 matches (opening line, chain of command, responsibility bullet).

- [ ] **Step 5: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add agents/research-director/AGENTS.md
git commit -m "feat: add Quant Metrics to Research Director's team

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 8: Rewrite the CEO AGENTS.md (role, priorities, ownership, routines)

**Files:**
- Modify: `agents/ceo/AGENTS.md`

- [ ] **Step 1: Insert the Role section at the very top (after line 1 `You are the CEO of Quant Zero.` block, before `## Org Structure`)**

Add immediately after the mission paragraph:
```markdown
## Role: System Builder

You build the system. You do not work in the system.

- Write standards, contracts, goals, and agent definitions — never strategies, code, or analysis.
- If you find yourself writing Python, running backtests, or analyzing data: stop, create an issue, assign it to the right director.
- Your output is: documents, Paperclip issues, goals, and agent instructions.
```

- [ ] **Step 2: Add the Quant Metrics row to the Org Structure director/IC mapping**

In the Org Structure section, after the directors table, add:
```markdown
Each director manages a team of IC agents. The Research Director's team now includes the
**Quant Metrics Agent**, which owns the minute-level KPI methodology (`docs/kpi-minute-level.md`),
co-signed by the Risk Director before the CEO locks it.
```

- [ ] **Step 3: Replace the Strategic Priorities section (lines ~21-26) with the expanded six**

```markdown
## Strategic Priorities

1. Pipeline health — research -> engineering -> risk must always be flowing. No stage idle.
2. Gate 1 integrity — criteria.md is CEO-locked, minute-level KPIs per asset class. Never relax under pressure.
3. Workspace integrity — every agent works within workspace-structure.md.
4. Workflow discipline — agents follow workflow-contracts/, script > LLM for repeatable work.
5. Capital preservation — the Risk Director's constitution is non-negotiable.
6. Paper trading readiness — signal pipeline and broker connection live and monitored.
```

- [ ] **Step 4: Add the Owned Documents section (after Strategic Priorities)**

```markdown
## Owned Documents

You author and gatekeep the entire agent definition layer. No agent modifies these without a CEO-approved PR.

### Org-wide policy (CEO-locked)
| Document | Purpose | Update trigger |
|---|---|---|
| `criteria.md` | Gate 1 acceptance criteria (minute-level, per asset) | Risk Director recommendation + CEO review |
| `workspace-structure.md` | Canonical directory layout | Engineering Director proposal + CEO approval |
| `docs/kpi-minute-level.md` | KPI spec per asset class | Quant Metrics deliverable + Risk co-sign + CEO lock |
| `workflow-contracts/git.md` | Branch + PR + commit standard — ALL agents | CEO-locked |
| `workflow-contracts/<role>.md` | LLM vs script boundary per role | Agent request + CEO judgment |

### Agent definitions (you own every agent's behavior)
For each `agents/<name>/`: `AGENTS.md` (role, responsibilities, chain of command),
`SOUL.md` (persona, voice), `TOOLS.md` (capabilities), `HEARTBEAT.md` (reactive checklist).
When org needs change — new role, behavior fix, capability grant — you edit these via PR.

Note: the Quant Zero Dashboard is NOT a CEO-owned document. The Risk Director owns its spec
and data format; the Engineering Director owns the build. You only set the goal that it exists.
```

- [ ] **Step 5: Add the Routines section (after Owned Documents)**

```markdown
## Routines (proactive, scheduled — separate from reactive heartbeat)

Reactive work runs in HEARTBEAT.md (event-driven). Proactive work runs as routines you own.
Create and manage only your own routines via the routines API.

### daily-morning — Pipeline Health Check
For each director (Research, Engineering, Risk): confirm at least one `in_progress` issue.
If idle, create a "pipeline stalled" issue assigned to that director with last known work as context.
Check for `blocked` issues idle > 24h; unblock or escalate.

### daily-evening — Workspace Compliance Audit
Scan the repo for files outside `workspace-structure.md` canonical paths.
On violations, create an issue assigned to the Engineering Director. Do not fix violations yourself.

### weekly-kpi — KPI and Criteria Review
Pull latest Gate 1 verdicts from `backtests/`. Detect criteria consistently causing false negatives.
If a pattern is found, document it in a CEO memo issue for board-visible review.
Never change `criteria.md` without documented rationale.

### weekly-trading — Paper Trading Status
Confirm the paper-trading signal pipeline is live (Engineering Director owns it). If not set up,
create the "Paper Trading Infrastructure" goal for Engineering. If live, check the last 7 days'
signal count and the dashboard staleness flags; flag zero-signal weeks to Research Director and
open an issue to Engineering if the pipeline is broken.

Note: the `daily-dashboard` routine (run the dashboard generator) is owned and created by the
Engineering Director, not the CEO.
```

- [ ] **Step 6: Replace the trailing `## Git Sync Workflow` section (lines 64-101) with the reference**

Remove everything from `## Git Sync Workflow` to end of file and replace with:
```markdown
## Git Workflow

Follow `workflow-contracts/git.md`. No exceptions.
```

```bash
cd /home/lamho/Documents/repos/quant-zero
f=agents/ceo/AGENTS.md
sed -i '/^## Git Sync Workflow$/,$d' "$f"
printf '## Git Workflow\n\nFollow `workflow-contracts/git.md`. No exceptions.\n' >> "$f"
```

- [ ] **Step 7: Verify**

Run:
```bash
cd /home/lamho/Documents/repos/quant-zero
grep -c "Role: System Builder" agents/ceo/AGENTS.md
grep -c "## Routines" agents/ceo/AGENTS.md
grep -c "## Owned Documents" agents/ceo/AGENTS.md
grep -c "## Git Sync Workflow" agents/ceo/AGENTS.md   # expect 0
```
Expected: 1, 1, 1, 0.

- [ ] **Step 8: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add agents/ceo/AGENTS.md
git commit -m "feat: CEO as system builder — role, priorities, ownership, routines

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 9: Trim CEO HEARTBEAT.md to reactive-only

**Files:**
- Modify: `agents/ceo/HEARTBEAT.md`

The proactive work (Section 6 backlog scanning beyond routing, fact-extraction cadence) moves to routines. Keep the heartbeat focused on reacting to events and working assigned issues.

- [ ] **Step 1: Add a mode banner at the top (after line 1 heading)**

Insert after the `# HEARTBEAT.md -- CEO Heartbeat Checklist` line:
```markdown
> **Reactive only.** This checklist handles event-driven work: wake reasons, assigned issues,
> unblocking, and routing new unassigned issues. Proactive periodic work (pipeline health,
> workspace audit, KPI review, paper-trading status) runs as Routines defined in AGENTS.md —
> do NOT run those scans here.
```

- [ ] **Step 2: Replace Section 6 "Review Unassigned Issues" with a bounded routing-only version**

Replace the entire `## 6. Review Unassigned Issues` section with:
```markdown
## 6. Route Newly Surfaced Unassigned Issues (reactive, bounded)

Only when an event surfaces an unassigned issue (a wake reason, a mention, or one you encounter
while working an assignment) — route it. Do NOT proactively scan the whole backlog here; the
daily-morning routine owns pipeline-wide review.

| Domain | Director | Agent ID |
|---|---|---|
| Strategy ideas, alpha signals, market regimes, research, KPI methodology | Research Director | 3e005203-1704-46ed-a469-8f2c4c4b6f58 |
| Code implementation, backtests, infrastructure, pipelines, dashboard build | Engineering Director | e20af8ed-290b-4cee-8bce-531026cebad5 |
| Risk review, overfitting, portfolio monitoring, Gate 1, dashboard spec | Risk Director | 0ba97256-23a8-46eb-b9ad-9185506bf2de |

Route at most 5 issues per heartbeat. If scope is unclear, comment asking the board to clarify
instead of assigning blindly. PATCH `assigneeAgentId` and leave a one-line routing-decision comment.
```

- [ ] **Step 3: Replace Section 8 "Fact Extraction" with a pointer to the routine cadence**

Replace the `## 8. Fact Extraction` section body with:
```markdown
## 8. Fact Extraction (light, reactive)

Extract durable facts only from the conversation this heartbeat touched. Deep periodic synthesis
runs on its own cadence — do not sweep all history every heartbeat.
```

- [ ] **Step 4: Verify**

Run:
```bash
cd /home/lamho/Documents/repos/quant-zero
grep -c "Reactive only" agents/ceo/HEARTBEAT.md
grep -c "daily-morning routine owns" agents/ceo/HEARTBEAT.md
```
Expected: 1 and 1.

- [ ] **Step 5: Commit**

```bash
cd /home/lamho/Documents/repos/quant-zero
git add agents/ceo/HEARTBEAT.md
git commit -m "refactor: trim CEO heartbeat to reactive-only, move proactive work to routines

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
```

---

### Task 10: Open PR and merge the repo changes

- [ ] **Step 1: Push the branch**

```bash
cd /home/lamho/Documents/repos/quant-zero
git push -u origin $(git branch --show-current)
```

- [ ] **Step 2: Open the PR**

```bash
cd /home/lamho/Documents/repos/quant-zero
gh pr create --title "feat: CEO system-builder redesign + minute-level Gate 1 + Quant Metrics" \
  --body "Implements docs/superpowers/specs/2026-06-06-ceo-system-builder-redesign-design.md

- Canonical git workflow contract; all agents reference it (DRY)
- workspace-structure.md and per-role script-vs-LLM contracts
- criteria.md rewritten for minute-level (v2.0, thresholds as placeholders)
- New Quant Metrics agent under Research Director
- CEO as system builder: role, six priorities, owned documents, routines
- CEO heartbeat trimmed to reactive-only"
```

- [ ] **Step 3: Auto-merge**

```bash
cd /home/lamho/Documents/repos/quant-zero
gh pr merge --merge --auto
```

Expected: PR queued for auto-merge.

---

### Task 11: CEO creates goals and routines via the Paperclip API (runtime)

This task runs as the CEO agent (or you, acting with the CEO's credentials) against the live Paperclip server. It is not a repo change. Resolve `companyId` and your `agentId` first.

- [ ] **Step 1: Resolve identity**

```bash
curl -s "$PAPERCLIP_API_URL/api/agents/me" -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('agentId', d.get('id')); print('companyId', d.get('companyId'))"
```
Record `companyId` and your CEO `agentId` for the calls below.

- [ ] **Step 2: Create the five+1 goals**

For each goal, create an issue. Example for goal 1 (repeat the pattern, changing title/description/assignee). Director IDs: Research `3e005203-1704-46ed-a469-8f2c4c4b6f58`, Engineering `e20af8ed-290b-4cee-8bce-531026cebad5`, Risk `0ba97256-23a8-46eb-b9ad-9185506bf2de`.

```bash
CID=<companyId>
RID=3e005203-1704-46ed-a469-8f2c4c4b6f58   # Research Director
EID=e20af8ed-290b-4cee-8bce-531026cebad5   # Engineering Director
KID=0ba97256-23a8-46eb-b9ad-9185506bf2de   # Risk Director

# Goal 1 — Define the minute-level KPI objective function (Research -> Quant Metrics)
curl -s -X POST "$PAPERCLIP_API_URL/api/companies/$CID/issues" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "X-Paperclip-Run-Id: $PAPERCLIP_RUN_ID" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"Define the minute-level KPI objective function\",\"priority\":\"high\",\"assigneeAgentId\":\"$RID\",\"description\":\"Deliver docs/kpi-minute-level.md balancing return and stability per asset class. Delegated to Quant Metrics. Requires Risk Director co-sign before CEO lock. Blocks Gate 1 v2.0 finalization.\"}"
```

Repeat for:
- Goal 2 — "Calibrate Gate 1 v2.0 thresholds with real 2022-2024 data" → `$EID`.
- Goal 3 — "Source minute-level strategies from quality references" → `$RID`.
- Goal 4 — "Find a strategy meeting all minute-level KPIs (full backtest + report)" → `$RID` (core company goal).
- Goal 5 — "Paper Trading Infrastructure (live signal pipeline + broker)" → `$EID`.
- Goal 6 — "Quant Zero Dashboard (Risk specs format + alerts; Eng builds generator/serving)" → `$KID` for the spec, with an Engineering subtask for the build.

- [ ] **Step 3: Create the CEO routines**

Read `skills/paperclip/references/routines.md` first for the exact routine payload schema, then create the four CEO routines (`daily-morning`, `daily-evening`, `weekly-kpi`, `weekly-trading`) with `schedule` (cron) triggers assigned to the CEO. The Engineering Director separately creates its own `daily-dashboard` routine.

- [ ] **Step 4: Verify goals exist**

```bash
curl -s "$PAPERCLIP_API_URL/api/companies/$CID/issues?q=minute-level" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" | python3 -m json.tool | grep -i title
```
Expected: the newly created goal titles appear.

---

## Self-Review

**Spec coverage:**
- Role redefinition → Task 8 Step 1. ✓
- Reactive/proactive split → Task 8 Step 5 (routines), Task 9 (heartbeat trim). ✓
- CEO ownership of agent definitions + locked docs → Task 8 Step 4. ✓
- Git workflow as org-wide standard → Task 1 (contract), Task 2 + Task 8 Step 6 (references). ✓
- Minute-level criteria.md → Task 5. ✓
- Quant Metrics agent under Research Director → Task 6, Task 7. ✓
- workspace-structure.md → Task 3. ✓
- workflow-contracts (script vs LLM) → Task 4. ✓
- Dashboard (Risk specs, Eng builds, CEO not owner) → Task 8 Step 4 note + Task 11 Goal 6. ✓
- Five+1 goals → Task 11 Step 2. ✓
- Routines created → Task 11 Step 3. ✓

**Placeholder scan:** criteria.md threshold TBDs are intentional, data-calibration deferrals documented as such (not plan placeholders). API `companyId`/`agentId` are resolved at runtime in Task 11 Step 1 (cannot be hard-coded). No disallowed placeholders.

**Type/name consistency:** `workflow-contracts/git.md` reference text identical across Tasks 1, 2, 6, 8. Director IDs identical in Tasks 9 and 11. Data formats (`promoted/registry.json`, `paper_trading/<strat>/...`) consistent between workspace-structure.md (Task 3) and spec.

---

## Out of Scope (downstream goals, not this plan)

- `scripts/build_dashboard.py` implementation (Engineering Director, Goal 6).
- Filling criteria.md threshold numbers (Engineering + Quant Metrics, Goal 2).
- Actual strategy research and backtests (Goal 4).
- Broker integration detail (Goal 5).
