# Engineering Director — Daily Micro Heartbeat

**Date:** 2026-10-24 (Sat)
**Ticket:** QUA-786 (latest ED Daily Micro; all 137 ED assignments are `blocked`)
**Type:** Daily micro (comment-only by policy, written to file because Paperclip writes are rejected this run, see Blocker 1)

---

## 1. Pipeline health

**Status: STALLED, 121 days dark.**

| Signal | Value |
|---|---|
| Last strategy code | `strategies/h87v2_darvas_box_breakout.py`, 2026-06-25 |
| Last backtest artifact | `backtests/H87v2_DarvasBoxBreakout_2026-06-25.json` |
| Commits, 2026-06 | 170 |
| Commits, 2026-07 through 2026-09 | 0 |
| Commits, 2026-10 | 12, of which 11 are director heartbeat docs |
| Only non-heartbeat commit since July | `36ecf79` MaxDD sign convention, filed 2026-10-02 |
| Working branch (shared checkout) | `chore/QUA-774-risk-director-weekly-heartbeat-2026-10-19` |

Zero Strategy Coder output and zero Backtest Runner output for 121 days. The 24h stall
threshold is exceeded by roughly 121x. This is not a per-ticket stall. The engineering
pipeline has been dark since 2026-06-25.

Delta against the 2026-10-02 heartbeat: control plane is now reachable (Blocker 1 of that
report is resolved), but no engineering throughput resumed in the 22 days since, and a new
adapter-launch fault appeared on 2026-10-23.

## 2. Blockers

### Blocker 1 — Paperclip writes rejected (INFRASTRUCTURE, CEO)

Reads succeed. Writes do not. This run is not task-bound (`PAPERCLIP_TASK_ID` unset), so
every write is refused:

```
POST /api/issues/{id}/comments
  → "Cross-issue writes need a run to attribute them to (Heartbeat run context)."
     code: cross_issue_write_requires_run
```

Retrying with `X-Paperclip-Run-Id: $PAPERCLIP_RUN_ID` returns the same error, so the run id
this process carries is not registered as a heartbeat run. The connections MCP server fails
on the same cause (`422: Connection requests require a task-bound heartbeat run`).

Consequence: this heartbeat cannot post comments, cannot set issue status, and cannot
delegate to Strategy Coder or Backtest Runner. Hence this file.

### Blocker 2 — `workspace_validation_failed`, 76 issues, 2026-09-02 through 2026-10-02

Recovery evidence (QUA-717 and QUA-631, identical across the cluster):

```
reason:                     fallback_agent_home_cwd
executionWorkspaceStrategy: project_primary
resolvedProjectWorkspaceId: 1295742e-63e7-487c-94d3-b4e39601fb52   (correct)
resolvedWorkspaceCwd:       /paperclip/instances/default/workspaces/48b67b44-.../
```

The resolver finds the correct project workspace id, then discards its cwd and falls back to
agent home. Project config is sound: workspace `1295742e` is `isPrimary: true`,
`sourceType: local_path`, `cwd: /home/lamho/Documents/repos/quant-zero`.

The fallback cwd is a container-namespace path (`/paperclip/instances/...`), while the project
cwd is a host path outside `PAPERCLIP_RUNNER_NETWORK_ROOTS`. The runner cannot see
`/home/lamho/Documents/repos/quant-zero`, so `project_primary` resolution degrades to agent
home, which is not a git checkout. Every ED run in that window therefore had no repo.

**Repair:** mount `/home/lamho/Documents/repos/quant-zero` into the runner namespace for this
agent, or repoint workspace `1295742e` at the managed folder already provisioned under
`.../projects/2b92869b-.../a6e8443a-.../quant-zero`. Do not retry the 76 issues first; they
will fail identically.

This blocker is not transient and will recur on the next scheduled heartbeat.

### Blocker 3 — `stranded_assigned_issue` / `acpx_turn_failed`, 60 issues, 2026-10-24

QUA-786 thread records three consecutive `ACP agent reported a terminal access failure` at
14:01, 14:02 and 14:04 UTC on 2026-10-23, then retry budget exhaustion. The adapter could not
acquire a terminal. Independent of Blocker 2.

This run holds a working terminal, so Blocker 3 appears transient.

**Repair order:** fix Blocker 2, then retry one Blocker 3 issue as a canary before bulk retry.

All 137 assignments carry board-owned recovery actions under policy
`board_escalation_no_takeover_v1`. I have no authority to self-unblock any of them.

## 3. Quality flags

**Credential exposed in plaintext, and dead (SECURITY + BLOCKER).** `git remote -v` in the
shared checkout prints a GitHub fine-grained PAT inline in the `origin` URL, stored in
`.git/config`. Every agent with repo access can read it, and it leaks into any transcript that
runs `git remote -v`. It is also no longer valid:

```
git push -u origin chore/QUA-786-ed-daily-micro-2026-10-24
  → remote: Invalid username or token. Password authentication is not supported
    fatal: Authentication failed for 'https://github.com/marcohwlam/quant-zero.git/'
```

The contract fallback (`GH_TOKEN`) is unavailable: it is a project `secret_ref` injected only
on task-bound runs, and this run is not task-bound (Blocker 1). So git workflow contract steps
3, 4, 5 and 6 are all unreachable this run. This commit is local only. No agent can push until
the token is rotated or `GH_TOKEN` injection is fixed.

Rotate the token and move it to a credential helper or `GH_TOKEN` env injection, which the
project `env` block already supports.

**Shared checkout contention.** All agents share one `local_path` workspace, so they serialize
onto one branch and one index. Current state: branch
`chore/QUA-774-risk-director-weekly-heartbeat-2026-10-19`, 5 modified files, 1 deleted
hypothesis (`research/hypotheses/83_usd_regime_em_country_rotation.md`), roughly 20 untracked
June backtest artifacts, 5 stale stashes. This contributes to Blocker 2 fragility and should
be reviewed once the pipeline is live.

**Heartbeat backlog is noise.** 136 of 137 blocked issues are replayed daily and weekly
heartbeat triggers spanning four months. Replaying them has no value; only the forward
schedule matters.

## 4. Decision log

| Decision | Rationale |
|---|---|
| Did not self-unblock any assignment | Recovery actions are board-owned, `no_takeover` policy |
| Did not bulk-retry the 76 workspace issues | Blocker 2 is unrepaired; retries fail identically |
| Wrote this report to file instead of a ticket comment | Blocker 1 rejects all Paperclip writes |
| Did not delegate to Strategy Coder or Backtest Runner | Delegation requires Paperclip task writes, see Blocker 1 |
| Committed locally, did not push or open a PR | Push rejected: `.git/config` PAT is invalid and `GH_TOKEN` is not injected on a non-task-bound run |
| Branched off the dirty shared checkout rather than cleaning it | Other agents' uncommitted work is in that tree; only this file was staged |

## 5. Next actions (CEO decisions required)

1. **Repair the ED workspace mount** or repoint workspace `1295742e`. Blocks everything else.
2. **Register heartbeat runs correctly** so ED runs are task-bound and can write to Paperclip.
3. **Authorize bulk resolution of the 136 stale heartbeat issues as `wont_do`.** Keep only the
   forward schedule.
4. **Rotate the GitHub PAT** and move it out of `.git/config`. It is currently invalid, so no
   agent can push. This blocks every ticket that produces file changes, not just mine.
5. **Canary-retry one `acpx_turn_failed` issue** after action 1 lands, before any bulk retry.

Paperclip tasks for these actions could not be created this run (Blocker 1). They are listed
here for the board to create or for me to create on the first task-bound heartbeat.
