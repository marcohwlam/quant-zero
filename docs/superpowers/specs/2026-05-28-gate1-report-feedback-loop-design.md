# Gate 1 Report Feedback Loop Design

**Date:** 2026-05-28
**Status:** Approved
**Scope:** Enhanced strategy backtest reporting with full Gate 1 quantitative metrics, wired into the Overfit Detector agent workflow with git commit and Paperclip comment output.

---

## Problem Statement

`visualization/report.py` already generates a basic Plotly HTML report (equity curve, drawdown, rolling Sharpe, trade scatter, metrics table), but:

1. The report is not automatically triggered after Gate 1 verdicts.
2. The report does not include Gate 1-specific metrics: walk-forward windows, DSR, regime-slice, parameter sensitivity, or the verdict banner.
3. The output is not committed to git or surfaced in Paperclip where the board can see it.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Gate 1 Pipeline                          │
│                                                             │
│  Backtest Runner                                            │
│  ├── runs backtest → metrics JSON + trades CSV              │
│  └── calls gate1_reporter.py → verdict JSON/TXT             │
│                        │                                    │
│                        ▼                                    │
│  Overfit Detector  (owns Gate 1 + Report)                   │
│  ├── DSR, walk-forward, param sensitivity, regime-slice     │
│  ├── produces: verdict JSON                                 │
│  └── calls report generator (final step)                   │
│                        │                                    │
│           ┌────────────┴────────────┐                       │
│           ▼                         ▼                       │
│  Enhanced report.py          git commit                     │
│  reads:                      feat/QUA-N-gate1-report        │
│  - backtest JSON             └── backtests/                 │
│  - verdict JSON                  └── HXX_report.html        │
│  - trades CSV                                               │
│  produces: HTML                     │                       │
│                                     ▼                       │
│                            Paperclip comment                │
│                            on issue: summary +              │
│                            file path + verdict              │
└─────────────────────────────────────────────────────────────┘
```

**Data flow:**

```
backtest JSON ──┐
trades CSV     ─┼──► enhanced report.py ──► HXX_report.html ──► git commit
verdict JSON ──┘                                                      │
                                                                       ▼
                                              Paperclip issue comment (markdown)
```

---

## Component 1: Enhanced `visualization/report.py`

### Existing sections (kept as-is)

- Equity curve (portfolio value, IS/OOS periods shaded)
- Drawdown percentage over time
- Rolling 30-day Sharpe ratio
- Trade PnL scatter (exit date vs PnL, colored by direction)
- Metrics summary table

### New sections (Gate 1 specific)

**Gate 1 Verdict Banner** (top of report)
- Strategy name, date, overall verdict (PASS / FAIL / CONDITIONAL)
- Key headline metrics: OOS Sharpe, DSR, WF windows passed
- Color coded: green = PASS, red = FAIL, amber = CONDITIONAL

**Walk-Forward Windows Chart**
- Grouped bar chart: IS Sharpe vs OOS Sharpe per window
- Each bar group colored: green = window passed, red = failed
- Horizontal reference line at OOS Sharpe threshold (0.7)
- Data source: `wf_table[]` array in backtest JSON

**Regime-Slice Results Chart**
- Horizontal bar chart: Sharpe per regime (Pre-COVID, Stimulus, Rate-shock, Normalization)
- Vertical reference line at threshold (0.8)
- Bars colored: green = pass, red = fail
- Data source: `regime_slice` field in verdict JSON

**Gate 1 Full Checklist Table**
- Every Gate 1 criterion: metric | value | threshold | PASS/FAIL
- Includes: IS Sharpe, OOS Sharpe, DSR, WF consistency ratio, IS Max DD, OOS Max DD, Win Rate, WF windows passed, parameter sensitivity, post-cost performance, regime-slice
- Auto-disqualifiers highlighted with red background
- Data source: verdict JSON

### CLI interface changes

```bash
# Existing (backward compatible)
python visualization/report.py --backtest backtests/<strategy>_<date>.json

# New: with Gate 1 sections
python visualization/report.py \
  --backtest backtests/<strategy>_<date>.json \
  --verdict backtests/<strategy>_<date>_verdict.json
```

- `--verdict` is optional. Without it, report renders existing sections only.
- Output filename: `<strategy>_<date>_report.html` (same as before)

### Verdict JSON requirements

The verdict JSON must contain `regime_slice` data for the regime-slice chart. If the current `gate1_reporter.py` does not write this field, the Overfit Detector must write it when generating the verdict. Fields required:

```json
{
  "verdict": "PASS",
  "metrics": {
    "is_sharpe": 1.25,
    "oos_sharpe": 0.89,
    "dsr": 0.42,
    "wf_windows_passed": 3,
    "wf_consistency_ratio": 0.71,
    "is_max_drawdown": -0.14,
    "oos_max_drawdown": -0.18,
    "win_rate": 0.56,
    "profit_factor": 1.4,
    "post_cost_sharpe": 1.19,
    "param_sensitivity": "PASS"
  },
  "regime_slice": {
    "pre_covid_2018_2019": 0.92,
    "stimulus_2020_2021": 1.34,
    "rate_shock_2022": 0.81,
    "normalization_2023": 0.75
  },
  "auto_disqualifiers": [],
  "failing_criteria": []
}
```

---

## Component 2: Overfit Detector AGENTS.md Update

Add a **Reporting** section as the final step after Gate 1 verdict is produced:

```markdown
## Reporting (Final Step After Gate 1)

After saving the verdict JSON, generate and publish the Gate 1 report:

1. Generate HTML report:
   python visualization/report.py \
     --backtest backtests/<strategy>_<date>.json \
     --verdict backtests/<strategy>_<date>_verdict.json

2. Commit to git on a feature branch:
   git checkout -b feat/QUA-<N>-gate1-report
   git add backtests/<strategy>_<date>_report.html
   git commit -m "feat(QUA-<N>): Gate 1 report for <strategy>

   Co-Authored-By: Paperclip <noreply@paperclip.ing>"
   git push -u origin feat/QUA-<N>-gate1-report

3. Post comment on the Paperclip issue (QUA-<N>):
   Use the Paperclip skill to post the comment below.
```

### Paperclip comment format

```markdown
## Gate 1 Report: <StrategyName>

**Verdict:** ✅ PASS / ❌ FAIL / ⚠️ CONDITIONAL PASS

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| IS Sharpe | X.XX | > 1.0 | ✅ PASS |
| OOS Sharpe | X.XX | > 0.7 | ✅ PASS |
| DSR | X.XX | > 0 | ✅ PASS |
| WF Windows | X/4 | ≥ 3 | ✅ PASS |
| IS Max Drawdown | XX.X% | < 20% | ✅ PASS |
| OOS Max Drawdown | XX.X% | < 25% | ✅ PASS |
| Win Rate | XX.X% | > 50% | ✅ PASS |
| Param Sensitivity | — | stable | ✅ PASS |
| Regime-Slice | X/4 regimes | ≥ 2 incl. stress | ✅ PASS |

**Auto-disqualifiers triggered:** None / [list if any]

**Report file:** `backtests/<strategy>_<date>_report.html`
**Branch:** `feat/QUA-<N>-gate1-report`

Open the HTML file locally to view interactive charts.
```

---

## Implementation Scope

### Files to modify

| File | Change |
|------|--------|
| `visualization/report.py` | Add `--verdict` arg; add 3 new chart sections; add verdict banner |
| `agents/overfit-detector/AGENTS.md` | Add Reporting section as final step |

### Files to verify (may need update)

| File | Check |
|------|-------|
| `orchestrator/gate1_reporter.py` | Confirm it writes `regime_slice` to verdict JSON; add if missing |

### Files not touched

- `agents/backtest-runner/AGENTS.md` — no change; backtest runner still hands off to overfit detector as before
- `criteria.md` — locked by CEO, no change
- All other agent AGENTS.md files

---

## Error Handling

- If `--verdict` file not found: log warning, skip Gate 1 sections, render base report only.
- If `regime_slice` missing from verdict JSON: skip regime chart, log warning in report HTML.
- If git push fails: log error to Paperclip comment, attach report path for manual commit.
- If Paperclip API call fails: write comment content to `docs/heartbeats/risk/<date>-gate1-<strategy>.md` as fallback.

---

## Success Criteria

1. `python visualization/report.py --backtest X.json --verdict X_verdict.json` produces a self-contained HTML with all existing + new Gate 1 sections.
2. Overfit Detector, after producing a verdict, autonomously commits the HTML and posts a Paperclip comment with the metrics table and verdict.
3. The Paperclip issue has a comment visible to the board within one agent heartbeat cycle of Gate 1 completion.
4. Backward compatibility: `--verdict` omitted still produces the original report without errors.
