# Gate 1 Intake Process — Engineering to Risk Director

**Owner:** Risk Director
**Last updated:** 2026-03-15
**Status:** Active

---

## Purpose

Defines the formal handoff protocol between Engineering Director and Risk Director for Gate 1 reviews. Every backtest must pass Gate 1 before any paper trading promotion is considered. No exceptions.

---

## 1. Submission Requirements

Engineering Director submits a Gate 1 review request via a **Paperclip task** with the following required fields:

### Task Format

```
Title: [Gate 1 Request] <StrategyName> v<version>
Assigned to: Risk Director
Priority: high
Project: Quant Zero
```

### Required Fields in Task Description

```
## Gate 1 Submission — <StrategyName> v<version>

**Submitted by:** Engineering Director
**Date:** YYYY-MM-DD

### Backtest Artifacts
- Backtest JSON path: backtests/<strategy-name>/<version>/results.json
- Narrative report path: backtests/<strategy-name>/<version>/report.md
- Strategy code path: strategies/<strategy-name>/
- Transaction cost model: [confirm method used, e.g. "0.1% round-trip, per trade"]

### Quick Stats
- IS period: YYYY-MM to YYYY-MM
- OOS period: YYYY-MM to YYYY-MM
- IS Sharpe: X.XX
- OOS Sharpe: X.XX
- IS Max Drawdown: XX.X%
- OOS Max Drawdown: XX.X%
- Win Rate: XX.X%
- Walk-forward windows: X/4

### Look-Ahead Bias Certification
[ ] I certify that no future data was used during the backtest period.
[ ] All signals use only data available at time T.
[ ] Feature engineering was applied with proper train/test splits.

### Economic Rationale
[2-3 sentences explaining why this strategy should work in theory]
```

---

## 2. Required Artifacts

Engineering Director **must** attach or link all of the following before the Gate 1 task is considered complete for review:

| Artifact | Path Convention | Required |
|----------|----------------|----------|
| Backtest results (JSON) | `backtests/<name>/<version>/results.json` | ✅ Mandatory |
| Narrative report | `backtests/<name>/<version>/report.md` | ✅ Mandatory |
| Strategy source code | `strategies/<name>/` | ✅ Mandatory |
| Transaction cost modeling confirmation | Inline in task description | ✅ Mandatory |
| Look-ahead bias self-certification | Checklist in task description | ✅ Mandatory |
| Walk-forward window breakdown | Inline in task description or report | ✅ Mandatory |

**Incomplete submissions will be returned immediately** without review. Risk Director will comment on the task noting which artifacts are missing.

---

## 3. SLA

| Milestone | Target |
|-----------|--------|
| Risk Director acknowledges receipt | ≤ 4 hours of submission |
| Overfit Detector analysis complete | ≤ 24 hours of submission |
| Full Gate 1 verdict to CEO | ≤ 2 business days of submission |
| CEO decision on paper promotion | ≤ 2 business days of verdict |

**Clock starts** when all required artifacts are present and look-ahead bias is certified.

---

## 4. Review Workflow

```
Engineering Director
        ↓
  [Gate 1 Request task] → Risk Director (assigned)
        ↓
  Risk Director checksout, verifies artifacts
        ↓
  Delegates overfitting analysis → Overfit Detector Agent (subtask)
        ↓
  Risk Director produces full Gate 1 verdict (pass/fail/conditional)
        ↓
  Escalates to CEO for final promotion decision
        ↓
  CEO approves → Engineering Director notified to schedule paper trading
  CEO denies → Engineering Director notified with reasons for rework
```

---

## 5. Escalation Path — Overfit Detector Unavailable

If Overfit Detector Agent is blocked or unavailable:

1. Risk Director posts a `blocked` comment on the Gate 1 task linking the blocker.
2. Risk Director escalates to CEO with a note that Overfit Detector is unavailable.
3. CEO decides: wait for Overfit Detector recovery, or manually authorize Risk Director to run limited overfitting checks.
4. Manual fallback: Risk Director documents which specific overfitting checks were skipped and why, and downgrades confidence to LOW in the final verdict.
5. Auto-reject if Overfit Detector flags look-ahead bias regardless of availability workaround.

---

## 6. Backtest Directory Conventions

```
backtests/
  <strategy-name>/
    <version>/
      results.json        ← Machine-readable backtest output
      report.md           ← Human-readable narrative analysis
      params.json         ← Parameter set used in backtest
      walk_forward/       ← Per-window results (if applicable)
        window_1.json
        window_2.json
        window_3.json
        window_4.json
```

**Naming conventions:**
- Strategy name: lowercase, hyphenated (e.g., `test-momentum`, `pairs-trading`)
- Version: `v1.0`, `v1.1`, `v2.0` etc. — increment minor for parameter changes, major for model changes

---

## 7. Post-Gate 1 Tracking

Once a strategy passes Gate 1 and CEO approves paper trading:

- Risk Director assigns Portfolio Monitor Agent to track the strategy with:
  - Demotion threshold = 1.5× IS max drawdown
  - Divergence alert = paper Sharpe > 1 std dev below backtest expectation
  - Daily P&L and drawdown reporting to Risk Director
- Strategy is added to the weekly risk summary

---

*This document is maintained by Risk Director. Changes require CEO review.*
