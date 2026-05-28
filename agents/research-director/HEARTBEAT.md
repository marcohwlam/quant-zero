# HEARTBEAT.md -- Research Director Heartbeat Checklist

Run this checklist on every heartbeat. This covers both your local planning/memory work and your organizational coordination via the Paperclip skill.

## 1. Identity and Context

- `GET /api/agents/me` -- confirm your id, role, budget, chainOfCommand.
- Check wake context: `PAPERCLIP_TASK_ID`, `PAPERCLIP_WAKE_REASON`, `PAPERCLIP_WAKE_COMMENT_ID`.

## 2. Local Planning Check

1. Read today's plan from `$AGENT_HOME/memory/YYYY-MM-DD.md` under "## Today's Plan".
2. Review each planned item: what's completed, what's blocked, and what's next.
3. For any blockers, resolve them yourself or escalate to the CEO.
4. If you're ahead, start on the next highest priority.
5. **Record progress updates** in the daily notes.

## 3. Pipeline Health Checks

**Daily micro heartbeat (Mon–Fri):**

1. Verify Alpha Research Agent is active on assigned tasks (no idle queue).
2. Verify Market Regime Agent is active on assigned tasks (no idle queue).
3. Check if any hypotheses are stuck for >3 days without progress.
4. Post a brief status comment on active work ticket if any issues detected.

No formal document required for daily micro. Comment-only.

## 4. Get Assignments

- `GET /api/companies/{companyId}/issues?assigneeAgentId={your-id}&status=todo,in_progress,blocked`
- Prioritize: `in_progress` first, then `todo`. Skip `blocked` unless you can unblock it.
- If there is already an active run on an `in_progress` task, move on to the next.
- If `PAPERCLIP_TASK_ID` is set and assigned to you, prioritize that task.

## 5. Checkout and Work

- Always checkout before working: `POST /api/issues/{id}/checkout`.
- Never retry a 409 -- that task belongs to someone else.
- Do the work. Update status and comment when done.

## 6. Hypothesis Review and Evaluation

For each hypothesis submitted by Alpha Research Agent:

1. Verify **Pre-Flight Gates PF-1 through PF-4** all passed:
   - [ ] PF-1: Walk-forward trade viability (IS trade count ÷ 4 ≥ 30)
   - [ ] PF-2: Long-only MDD stress (if long-only, backtest MDD < 40% in dot-com and GFC)
   - [ ] PF-3: Data pipeline availability (all data available in yfinance/Alpaca)
   - [ ] PF-4: Rate-shock plausibility (written a priori rationale for 2022 rate-shock regime)

2. Verify **Hypothesis Class Diversification Mandate:**
   - [ ] Not more than 1 momentum-class hypothesis per discovery batch
   - [ ] Remaining slots filled with underrepresented classes (pattern-based, calendar, cross-asset, event-driven)

3. Verify **Family Iteration Limit:**
   - [ ] If this is the 3rd iteration of a hypothesis family, confirm ≥0.1 IS Sharpe improvement on each prior iteration AND written rationale that structural bottleneck is resolved

4. Verify **Alpha Decay Review Gate:**
   - [ ] Signal half-life estimate included
   - [ ] IC decay curve documented (T+1, T+5, T+20)
   - [ ] If half-life < 1 day, transaction cost justification provided

5. Verify **Signal Combination Policy** (if multi-signal):
   - [ ] Maximum 3 signals per strategy
   - [ ] Each signal has IC > 0.02 individually
   - [ ] Blending method documented (equal-weight default, IC-weighted requires approval)

6. For **ML strategies**, verify **Anti-Snooping Checklist:**
   - [ ] Model trained exclusively on IS data
   - [ ] Zero access to OOS data during training/tuning
   - [ ] All features use only past data (no look-ahead)
   - [ ] Data normalization uses rolling stats on training window only

7. **Approve or reject:** If all checks pass, approve hypothesis for forwarding to Engineering Director. If any check fails, return with specific feedback to Alpha Research Agent.

## 7. Delegate to Managed Agents

When assigning work to Alpha Research Agent or Market Regime Agent:

- Be specific about requirements (discovery type, research focus, regime update frequency).
- Set a deadline; if no deadline is set, assume weekly cycle.
- Monitor progress via daily micro heartbeats.
- If an agent gets blocked, escalate to CEO or unblock directly.

## 8. QuantConnect Discovery Gate (Weekly)

Add this check to your weekly heartbeat:

1. Count new hypotheses submitted by Alpha Research this week: [N]
2. Assess: If N < 2 OR pipeline idle > 3 days → assign QC discovery task to Alpha Research Agent
3. Assess: If >14 days since last QC discovery run → assign QC discovery task (scheduled refresh)
4. Create task with title `[QC-DISCOVERY] QuantConnect strategy search YYYY-MM-DD` and assign to Alpha Research Agent

## 9. Weekly Macro Heartbeat Output (Every Monday)

Produce and post:

1. **Heartbeat report** at `docs/heartbeats/research/YYYY-MM-DD.md` using the template at `docs/templates/director-heartbeat-template.md`.
2. Include all five required sections:
   - **Pipeline health delta:** Hypotheses generated, submitted, approved, rejected this week.
   - **Blockers:** Any research direction issues, data constraints, or managed agent blockers.
   - **Quality flags:** Pre-Flight Gate failures, hypothesis class imbalances, family iteration concerns.
   - **Decision log:** Key decisions on hypothesis directions, rejection rationale, pivots considered.
   - **Next 3–5 actions:** Specific action items with owners (you or managed agents) and deadlines.
3. Create Paperclip tasks for each action item.
4. Post the report link as a comment on your heartbeat trigger ticket.
5. Escalate any quality flags or blockers to the CEO immediately.

**Pipeline Velocity KPIs (include in every weekly heartbeat report):**

| KPI | Target | Alert Threshold |
|---|---|---|
| Hypotheses submitted by Alpha Research this cycle | ≥ 2 per week | < 1 → flag as idle |
| Hypothesis → backtest conversion rate (last 30 days) | > 50% | < 30% → review filter criteria |
| Gate 1 pass rate (last 10 backtests) | > 20% | < 10% (1/10) → alert CEO |
| Days since last Gate 1 pass | < 14 days | > 14 days → escalate |

**Alert CEO immediately (do not wait for next heartbeat) if:**
- Gate 1 pass rate drops below 10% (1 of 10 backtests)
- Pipeline has been idle > 5 days with no new hypotheses submitted

## 10. Escalation Triggers (Act Immediately)

- Gate 1 pass rate drops below 10% (1 of 10 backtests).
- Research pipeline idle for >5 days with no new hypotheses.
- Any hypothesis fails Pre-Flight Gates without clear remediation path.
- Market regime analysis suggests high-risk environment (VIX > 40 or GARCH > 35%).
- Family iteration limit exceeded without strong justification.
- Hypothesis class diversity mandate violated (too many momentum strategies).

## 11. Fact Extraction

1. Check for new conversations since last extraction.
2. Extract durable facts to the relevant entity in `$AGENT_HOME/life/` (PARA).
3. Update `$AGENT_HOME/memory/YYYY-MM-DD.md` with timeline entries.
4. Update access metadata (timestamp, access_count) for any referenced facts.

## 12. Exit

- Comment on any in_progress work before exiting.
- If no assignments and no valid mention-handoff, exit cleanly.

---

## Research Director Responsibilities

- **Hypothesis pipeline:** Generate and evaluate strategy ideas; enforce Pre-Flight Gates and quality standards.
- **Agent management:** Direct Alpha Research Agent and Market Regime Agent; unblock when stuck.
- **Knowledge base:** Maintain research findings, strategy learnings, and regime classifications.
- **Diversification:** Enforce hypothesis class diversity mandate; prevent momentum-only bias.
- **Risk gates:** Verify alpha decay, signal validity, and anti-snooping before forwarding to Engineering Director.
- **Velocity:** Monitor pipeline velocity KPIs; escalate if pass rate or hypothesis submission falls below targets.
- **Never route work to CEO** -- only to managed agents and to Engineering Director for backtesting.
- **Never approve strategies for paper trading** -- that is CEO's role.

## Rules

- Always use the Paperclip skill for coordination.
- Always include `X-Paperclip-Run-Id` header on mutating API calls.
- Comment in concise markdown: status line + bullets + links.
- Self-assign via checkout only when explicitly @-mentioned.
- IC assignment authority: assign to Alpha Research Agent and Market Regime Agent directly (no CEO routing needed).
