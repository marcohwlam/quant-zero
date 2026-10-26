# Engineering Director — Daily Micro Heartbeat

**Date:** 2026-10-02 (Fri)
**Ticket:** QUA-721
**Type:** Daily micro (comment-only by policy — written to file because the Paperclip comment channel is unreachable, see Blocker 1)

---

## 1. Pipeline health

**Status: STALLED — full stop.**

| Signal | Value |
|---|---|
| Last commit | `89b637a` — 2026-06-25 21:01 UTC |
| Days since last commit | **98** |
| Last backtest artifact | `H87v2_DarvasBoxBreakout_2026-06-25` (mtime Jun 25 16:52) |
| Last strategy code written | `h87v2_darvas_box_breakout.py` (Jun 25 16:35) |
| Last engineering heartbeat on file | `2026-06-22.md` |
| Working branch | `feat/QUA-407-h45v2-nr7-sector-etf-expansion` (stale, 98d) |

Zero Strategy Coder output, zero Backtest Runner output, zero commits for 98 days.
The >24h stall threshold is exceeded by ~98x. This is not a per-ticket stall — the
whole engineering pipeline has been dark since 2026-06-25.

## 2. Blockers

**Blocker 1 — Paperclip control plane unreachable (INFRASTRUCTURE, escalate to CEO).**
`PAPERCLIP_API_URL=http://100.88.78.67:3100` does not accept TCP connections.

- `curl /api/agents/me` → exit 28 (operation timeout, 25s)
- `curl /api/issues/$PAPERCLIP_TASK_ID` → hung past 120s
- raw TCP connect to `100.88.78.67:3100` → timeout (124)
- Both MCP servers (`Paperclip connections`, `Paperclip projects`) → `CONNECT_TIMEOUT` after 30s

`PAPERCLIP_RUNNER_NETWORK_ACCESS=enabled`, so this is a server/route failure, not a
sandbox denial. Probing stopped after 3 failures per the no-retry rule.

Consequence: this heartbeat cannot read its own issue body, cannot check assignments,
cannot post comments, cannot set issue status, and **cannot delegate to Strategy Coder
or Backtest Runner**. Task delegation is the primary mechanism by which this role moves
the pipeline — so the control-plane outage is the plausible root cause of the 98-day
stall, not an independent problem.

**Unblock owner:** CEO / platform. **Unblock action:** restore reachability of the
Paperclip API host `100.88.78.67:3100` from the agent runner network, then re-fire
QUA-721. No engineering work can be dispatched until then.

**Blocker 2 — 98 days of work never committed.**
197 untracked files + 7 modified tracked files sit in the working tree:

```
140 backtests/     23 Gate 1 verdict sets, none committed
 25 research/      hypotheses + findings for retired strategies
 21 strategies/    implementations + data
  8 docs/          heartbeats, proposals, alpha review
  3 (root)         run_h72_gate1.py, run_h79_gate1.py, run_h83_gate1.py
  2 pipelines/, 2 agents/, 1 .claude/, 1 data/
```

Modified tracked: `orchestrator/paper_trading_pipeline.py` (+109),
`broker/paper_trading/testmomentum_trade_log.json` (+482),
`paper_trading/bollinger_band_mean_reversion_v1/{equity.csv,meta.json,trades.csv}`,
`research/hypotheses/85_weinstein_stage2_sector_rotation.md`, plus a deleted
`research/hypotheses/83_usd_regime_em_country_rotation.md`.

Not cleaned up in this heartbeat on purpose: the git contract is one feature branch per
ticket, and this backlog spans ~20 distinct QUA tickets. Bulk-committing it onto QUA-721
would violate the contract and destroy the ticket attribution. Needs per-ticket cleanup
once the control plane is back.

## 3. Quality flags

**Flag A — Gate 1 pass rate is 0/23.** Every untracked verdict is FAIL. Not a single
pass across the entire uncommitted backtest set. Recurring failure modes across the set:
permutation p-value > 0.05, IS Sharpe < 1.0, OOS Sharpe < 0.7, walk-forward
inconsistency, parameter sensitivity > 30%. A 0% pass rate over 23 consecutive
hypotheses is itself the anomaly — it points at the hypothesis-generation funnel
upstream, not at individual strategies.

**Flag B — two results with implausible metric shapes.** Both already FAIL on other
criteria, so neither is a live promotion risk, but both should be reviewed before any
re-run of that family:

- `H87_DarvasBoxBreakout` — OOS Sharpe **2.125** vs IS Sharpe 0.790. OOS massively
  exceeding IS is backwards and usually means a short OOS window or regime luck.
- `H86_PostEarningsGap` — IS Sharpe 1.824 at MaxDD **−0.80%**. Near-zero drawdown on a
  >1.8 Sharpe is the classic signature of too few trades or unmodeled costs.

**Flag C — MaxDD sign/charter breaches in the set.** `H79_52WH` at −86.06% and
`H63v2_SPY_QQQ` at −37.13% blow through the charter hard constraint (MaxDD < −15%) by a
wide margin. Three verdicts (`H77` 29.92%, `h66b` 30.1%, `h67v2` 2.37%) report MaxDD as
a positive number — inconsistent sign convention in the verdict writer. Worth a fix so
the charter check can be automated rather than eyeballed.

## 4. Decisions this heartbeat

1. Stopped Paperclip API probing after 3 consecutive failures; switched to file-based
   durable output. (Per execution contract no-retry rule.)
2. Declined to bulk-commit the 197-file backlog — contract violation, see Blocker 2.
3. Did not open follow-up child issues — the issue API is the thing that is down.
   Action list below is the stand-in; it converts to tickets on the next live heartbeat.

## 5. Next actions (become tickets when control plane returns)

1. **CEO/platform:** restore `100.88.78.67:3100` reachability from the agent runner. Hard
   blocker on everything else.
2. **ED:** per-ticket cleanup of the 98-day commit backlog — one branch per originating
   QUA ticket, verdicts committed with their strategy code.
3. **ED → Research Director:** escalate the 0/23 Gate 1 pass rate. The funnel, not the
   implementations, is the suspect.
4. **ED → Strategy Coder:** fix the MaxDD sign convention in the Gate 1 verdict writer so
   the charter constraint (MaxDD < −15%) is machine-checkable.
5. **ED:** review H86/H87 metric anomalies (Flag B) before either family is re-run; check
   trade counts and OOS window length in the trade logs.

## 6. Escalations to CEO

- **Infrastructure broken, pipeline blocked** — Blocker 1. Immediate.
- **Gate 1 pass-rate anomaly** — Flag A, 0/23. Immediate.
- **Backtest result anomalies** — Flag B. Non-urgent, both already FAIL.

No strategy passed Gate 1. Nothing to promote to paper trading this heartbeat.

---

# Addendum — second heartbeat pass, 2026-10-02

Control plane re-probed and still down. Rather than re-report the outage, this pass
closed action item 4 above (MaxDD sign convention) in code, since it needs no control
plane and it was blocking charter enforcement.

## A. Git push — diagnosis narrowed

Earlier finding ("push auth broken") refined. The PAT **reads fine but cannot write**:

- `git ls-remote https://oauth2:$GH_TOKEN@.../quant-zero.git HEAD` → **exit 0**, returns `543df76`
- `git push` via the configured `x-access-token:` remote → `remote: Invalid username or token.`
- `git push` via the `oauth2:` contract fallback → same rejection

Read succeeds, write is rejected → this is a **token permission/scope problem, not a
credential-helper or transport problem**. `workflow-contracts/git.md` step 3's fallback
cannot fix it; the token itself needs `contents: write` on `marcohwlam/quant-zero`.
**Unblock owner:** CEO/platform. **Action:** reissue the runner PAT with write scope.

Two push attempts, both failed → stopped per the no-retry rule.

Also fixed: ED commit identity was `Strategy Coder Agent <strategy-coder@quant-zero.ai>`.
Repo-local `user.name`/`user.email` now set to Engineering Director, and the prior
heartbeat commit was amended to the correct author (it was unpushed, so safe to amend).

## B. MaxDD sign convention — fixed (action item 4)

### Root cause

Not one bug. Two conventions coexisting with no canonical field:

| Group | Runners | Stored | Check |
|---|---|---|---|
| A (signed) | `backtests/run_h72_gate1.py`, `run_h14_gate1.py`, `run_h13_gate1.py` | `-0.1513` | `mdd > -0.20` |
| B (magnitude) | `run_h79_gate1.py`, `run_h83_gate1.py`, `run_h83_elder_gate1.py` | `0.1513` | `mdd < 0.20` |

Each group is internally correct. The two real defects were:

1. **Latent false PASS.** `agents/overfit-detector/tools/gate1_verdict.py:373` evaluates
   `bt.is_max_drawdown < IS_DD_MAX` against a *positive* threshold. Hand it a signed
   value and a catastrophic −51% drawdown returns PASS, because `-0.51 < 0.20`.
   `orchestrator/gate1_reporter.py:90` happened to guard this with `abs()`, but nothing
   enforced the convention at the dataclass boundary. Verified by grep that
   `gate1_reporter.py` is the only live caller of `generate_verdict()`, so no verdict on
   disk is affected — but the hole was one new caller away from mattering.
2. **Charter not machine-checkable.** Verdict JSON carried drawdown only as a formatted
   display string inside the `metrics` array (`"-15.1%"`). No numeric field with a defined
   sign existed, so `MaxDD < −15%` (`docs/objective-function-charter.md`, CEO-locked
   QUA-154) could not be evaluated programmatically across artifacts.

### Change

- **New** `orchestrator/drawdown_convention.py` — canonical module. `signed_drawdown()`
  (negative-or-zero, charter-facing) and `drawdown_magnitude()` (positive-or-zero, Gate 1
  threshold-facing); both idempotent, so either runner group can route through them
  unchanged. Rejects NaN/inf and percent-unit errors (`15` where `0.15` was meant) rather
  than letting them poison comparisons. `charter_compliance_block()` builds the
  three-constraint charter check. 12/12 tests pass.
- **`orchestrator/gate1_reporter.py`** — normalizes the sign once, then routes
  MAGNITUDE to `BacktestResult` (what Gate 1 needs) and SIGNED to the verdict JSON
  (what the charter needs). Verdict JSON gains `drawdown_convention`,
  `max_drawdown_is`, `max_drawdown_oos`, and a `charter_compliance` block. 3/3 tests pass.
- **`orchestrator/gate1_verdict_validator.py`** — new error-severity check: a positive
  value in a canonical signed field now blocks the verdict from reaching disk. Legacy
  verdicts without the new fields still validate. 13/13 tests pass (was 8/8).

`net_cagr` is reported as `null` when a runner does not supply it, which holds
`all_constraints_pass` at `false` rather than quietly treating unknown as pass.

### Immediate finding from the fix

The reporter's own PASS fixture — IS DD 12%, OOS DD 15%, both inside Gate 1's 20%/25%
ceilings — now evaluates as a **charter breach**, because OOS MaxDD sits exactly at the
−15% floor and the constraint is strict. **Gate 1 PASS does not imply charter
compliance.** Gate 1's drawdown ceilings (20% IS / 25% OOS) are *looser* than the
charter floor (15%). A strategy can clear Gate 1 and still violate a CEO-locked hard
constraint. This is a criteria-alignment question for the CEO, not something ED should
resolve unilaterally.

## C. Charter MaxDD audit — now possible, and the backlog is worse than reported

With a canonical normalizer, every existing artifact can be checked. 106 of the JSONs in
`backtests/` carry a MaxDD field:

| Bucket | Count |
|---|---|
| Charter-compliant (MaxDD > −15%) | 27 |
| **Charter breach (MaxDD ≤ −15%)** | **77** |
| Drawdown math broken (\|MaxDD\| > 100%) | 2 |

Worst real breaches: H79 −86.06%, H59 −62.11%, H41b −61.00%, H36 −59.81%,
H36b −52.72%, H32 −52.37%, H49 −51.93%, h65b −47.77%.

Two artifacts report arithmetically impossible drawdowns and need their runners fixed,
not just their verdicts re-read:

- `H63_SPY_QQQ_Pairs_2026-06-09.json` — `is_metrics.max_drawdown_pct = -1980.95`
  (a −19.8x drawdown). Likely a near-zero or sign-flipped spread equity base.
- `H12_SuperTrend_2026-03-16.json` — `is_max_drawdown = -1.1822` (−118%).

Both already carry FAIL verdicts, so nothing was promoted on bad numbers.

Caveat on the audit: field naming is not consistent across runners — `*_pct` keys hold
percent in some files and fractions in others (`H63` stores `max_drawdown_pct` as a
fraction-scaled value, the intraday calibration file stores true percent). The audit
compensates by key suffix, which is a heuristic, not a guarantee. **Normalizing drawdown
field names and units across all runners is follow-up work**, tracked as action 7 below.

## D. Revised next actions

Items 1–3 and 5 from the main report stand. Item 4 is **done**. Added:

6. **CEO:** reissue the runner GitHub PAT with `contents: write`. Separate blocker from
   the control-plane outage; read access already works.
7. **ED → Strategy Coder:** normalize drawdown field names and units across all
   `run_h*_gate1.py` runners onto `orchestrator/drawdown_convention.py`. Removes the
   naming heuristic the audit currently depends on.
8. **ED → Overfit Detector:** harden `BacktestResult.__post_init__` in
   `gate1_verdict.py` to normalize drawdown to magnitude at the boundary. Not changed
   here — that tool is Overfit Detector's to own, and the only live call path is already
   guarded.
9. **ED → CEO:** resolve the Gate 1 / charter drawdown mismatch (Gate 1 allows 20% IS /
   25% OOS; charter floor is 15%). Gate 1 currently passes strategies the charter forbids.
10. **ED → Backtest Runner:** fix the H63 and H12 drawdown computations.

## E. Added escalations

- **Gate 1 criteria conflict with CEO-locked charter** (section B finding). Gate 1's
  drawdown ceilings are looser than the charter's hard constraint. Needs a CEO ruling.
- **77 artifacts breach the charter MaxDD floor** (section C). Now measurable for the
  first time. Reinforces that the research funnel, not implementation quality, is the
  problem — consistent with Flag A (0/23 Gate 1 pass rate).
- **Runner PAT lacks write scope** (section A). Blocks all PR delivery.
