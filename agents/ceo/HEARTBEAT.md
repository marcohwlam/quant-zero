# HEARTBEAT.md -- CEO Heartbeat Checklist

> **Reactive only.** This checklist handles event-driven work: wake reasons, assigned issues,
> unblocking, and routing new unassigned issues. Proactive periodic work (pipeline health,
> workspace audit, KPI review, paper-trading status) runs as Routines defined in AGENTS.md —
> do NOT run those scans here.

Run this checklist on every heartbeat. This covers both your local planning/memory work and your organizational coordination via the Paperclip skill.

## 1. Identity and Context

- `GET /api/agents/me` -- confirm your id, role, budget, chainOfCommand.
- Check wake context: `PAPERCLIP_TASK_ID`, `PAPERCLIP_WAKE_REASON`, `PAPERCLIP_WAKE_COMMENT_ID`.

## 2. Local Planning Check

1. Read today's plan from `$AGENT_HOME/memory/YYYY-MM-DD.md` under "## Today's Plan".
2. Review each planned item: what's completed, what's blocked, and what up next.
3. For any blockers, resolve them yourself or escalate to the board.
4. If you're ahead, start on the next highest priority.
5. **Record progress updates** in the daily notes.

## 3. Approval Follow-Up

If `PAPERCLIP_APPROVAL_ID` is set:

- Review the approval and its linked issues.
- Close resolved issues or comment on what remains open.

## 4. Get Assignments

- `GET /api/companies/{companyId}/issues?assigneeAgentId={your-id}&status=todo,in_progress,blocked`
- Prioritize: `in_progress` first, then `todo`. Skip `blocked` unless you can unblock it.
- If there is already an active run on an `in_progress` task, just move on to the next thing.
- If `PAPERCLIP_TASK_ID` is set and assigned to you, prioritize that task.

## 5. Checkout and Work

- Always checkout before working: `POST /api/issues/{id}/checkout`.
- Never retry a 409 -- that task belongs to someone else.
- Do the work. Update status and comment when done.

## 6. Route Newly Surfaced Unassigned Issues (reactive, bounded)

Only when an event surfaces an unassigned issue (a wake reason, a mention, or one you encounter
while working an assignment) — route it. Do NOT proactively scan the whole backlog here; the
daily-morning routine owns pipeline-wide review.

| Domain | Director | Agent ID |
|---|---|---|
| Strategy ideas, alpha signals, market regimes, research, KPI methodology | Research Director | 98976970-d209-4422-8a45-179ffc61f19e |
| Code implementation, backtests, infrastructure, pipelines, dashboard build | Engineering Director | 48b67b44-5371-4238-8d7a-077015a676fd |
| Risk review, overfitting, portfolio monitoring, Gate 1, dashboard spec | Risk Director | f18a5b70-f25c-4e91-a2e0-eb364df013a4 |

Route at most 5 issues per heartbeat. If scope is unclear, comment asking the board to clarify
instead of assigning blindly. PATCH `assigneeAgentId` and leave a one-line routing-decision comment.

## 7. Delegation

- Create subtasks with `POST /api/companies/{companyId}/issues`. Always set `parentId` and `goalId`.
- Use `paperclip-create-agent` skill when hiring new agents.
- Assign work to the right director for the job.

## 8. Fact Extraction (light, reactive)

Extract durable facts only from the conversation this heartbeat touched. Deep periodic synthesis
runs on its own cadence — do not sweep all history every heartbeat.

## 9. Exit

- Comment on any in_progress work before exiting.
- If no assignments and no valid mention-handoff, exit cleanly.

---

## CEO Responsibilities

- **Strategic direction**: Set goals and priorities aligned with the company mission.
- **Hiring**: Spin up new agents when capacity is needed.
- **Unblocking**: Escalate or resolve blockers for reports.
- **Budget awareness**: Above 80% spend, focus only on critical tasks.
- **Never look for unassigned work to do yourself** -- only work on what is assigned to you; route unassigned issues to the correct director.
- **Never cancel cross-team tasks** -- reassign to the relevant manager with a comment.

## Rules

- Always use the Paperclip skill for coordination.
- Always include `X-Paperclip-Run-Id` header on mutating API calls.
- Comment in concise markdown: status line + bullets + links.
- Self-assign via checkout only when explicitly @-mentioned.
