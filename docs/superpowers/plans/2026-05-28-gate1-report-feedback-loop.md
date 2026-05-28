# Gate 1 Report Feedback Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After Gate 1 verdict is produced, the Overfit Detector automatically generates an enhanced interactive HTML report (equity curve + full Gate 1 metrics), commits it to git, and posts a structured summary to the Paperclip issue.

**Architecture:** `visualization/report.py` gains a `--verdict` flag that adds three new Gate 1 sections (walk-forward windows chart, regime-slice chart, Gate 1 checklist table) and injects a verdict banner into the HTML output. `gate1_reporter.py` is extended to write `regime_slice` into the verdict JSON. The Overfit Detector AGENTS.md gains a Reporting section as its final step.

**Tech Stack:** Python 3.10+, Plotly (already installed), argparse, pathlib, json; existing `gate1_verdict.py` / `gate1_reporter.py` engine.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `visualization/report.py` | Modify | Add `--verdict` arg, verdict banner, WF chart, regime chart, Gate 1 checklist table |
| `orchestrator/gate1_reporter.py` | Modify | Write `regime_slice` field into verdict JSON output |
| `agents/overfit-detector/AGENTS.md` | Modify | Add Reporting section as final step after Gate 1 |
| `tests/test_report_gate1.py` | Create | Tests for new report.py functionality |

---

## Task 1: Extend verdict JSON with `regime_slice` field

**Files:**
- Modify: `orchestrator/gate1_reporter.py` (around line 86 where `verdict_json` dict is built)

- [ ] **Step 1: Locate the verdict_json dict construction in gate1_reporter.py**

Open `orchestrator/gate1_reporter.py`. Find the block that builds `verdict_json` (around line 86). It currently ends with `"txt_path": str(txt_path)`. The `regime_slice` field must be added here.

- [ ] **Step 2: Add `regime_slice` extraction from metrics**

In `generate_and_save_verdict()`, before the `verdict_json = {...}` block, extract `regime_slice` from the incoming `metrics` dict:

```python
# Extract regime-slice Sharpe values if provided by the orchestrator
regime_slice = metrics.get("regime_slice", {})
# Normalise: ensure keys are the canonical regime names
_REGIME_KEYS = [
    "pre_covid_2018_2019",
    "stimulus_2020_2021",
    "rate_shock_2022",
    "normalization_2023",
]
regime_slice = {k: float(regime_slice[k]) for k in _REGIME_KEYS if k in regime_slice}
```

Add this block immediately before line `verdict_json = {`.

- [ ] **Step 3: Add `regime_slice` to the verdict_json dict**

Inside the `verdict_json = { ... }` block, add the field after `"trade_log": trade_log,`:

```python
"regime_slice": regime_slice,
```

- [ ] **Step 4: Run the existing smoke tests to confirm nothing broke**

```bash
cd /home/lamho/Documents/repos/quant-zero
python orchestrator/gate1_reporter.py
```

Expected output:
```
Running gate1_reporter smoke tests...

  [OK]   PASS case: PASS
  [OK]   FAIL case: FAIL
  [OK]   CONDITIONAL PASS case: CONDITIONAL PASS (acceptable)

3/3 tests passed
```

- [ ] **Step 5: Confirm regime_slice appears in a test verdict JSON**

```bash
cat backtests/test/TestMomentum_*.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('regime_slice:', d.get('regime_slice', 'MISSING'))"
```

Expected: `regime_slice: {}` (empty because the PASS test metrics don't include regime data — this is correct; the field exists but is empty when not provided by the orchestrator).

- [ ] **Step 6: Commit**

```bash
git add orchestrator/gate1_reporter.py
git commit -m "feat: add regime_slice field to Gate 1 verdict JSON output"
```

---

## Task 2: Write failing tests for new report.py functionality

**Files:**
- Create: `tests/test_report_gate1.py`

- [ ] **Step 1: Create the test file**

Create `tests/test_report_gate1.py` with the following content:

```python
"""
Tests for Gate 1 enhanced reporting in visualization/report.py.
Run with: python tests/test_report_gate1.py
"""
import json
import sys
import tempfile
from pathlib import Path

# Make visualization importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from visualization.report import load_verdict, build_report, _build_verdict_banner


# ── Fixtures ──────────────────────────────────────────────────────────────────

MINIMAL_BACKTEST = {
    "strategy_name": "TestStrategy",
    "date": "2026-01-01",
    "is_sharpe": 1.35,
    "oos_sharpe": 0.91,
    "is_max_drawdown": -0.12,
    "oos_max_drawdown": -0.18,
    "win_rate": 0.55,
    "profit_factor": 1.4,
    "trade_count": 120,
    "oos_trade_count": 45,
    "wf_table": [
        {"window": 1, "is_sharpe": 1.3, "oos_sharpe": 0.95, "pass": True},
        {"window": 2, "is_sharpe": 1.4, "oos_sharpe": 0.88, "pass": True},
        {"window": 3, "is_sharpe": 1.2, "oos_sharpe": 0.90, "pass": True},
        {"window": 4, "is_sharpe": 1.5, "oos_sharpe": 0.92, "pass": True},
    ],
    "equity_curve": [],
    "trade_log": [],
}

MINIMAL_VERDICT = {
    "strategy_name": "TestStrategy",
    "date": "2026-01-01",
    "overall_verdict": "PASS",
    "recommendation": "Promote to paper trading",
    "confidence": "HIGH",
    "disqualify_reason": None,
    "regime_slice": {
        "pre_covid_2018_2019": 0.92,
        "stimulus_2020_2021": 1.34,
        "rate_shock_2022": 0.81,
        "normalization_2023": 0.75,
    },
    "metrics": [
        {"name": "IS Sharpe", "value": 1.35, "threshold": 1.0, "passed": True, "auto_disqualify": False},
        {"name": "OOS Sharpe", "value": 0.91, "threshold": 0.7, "passed": True, "auto_disqualify": False},
        {"name": "Deflated Sharpe Ratio", "value": 0.42, "threshold": 0.0, "passed": True, "auto_disqualify": True},
        {"name": "IS Max Drawdown", "value": -0.12, "threshold": -0.20, "passed": True, "auto_disqualify": False},
        {"name": "Walk-forward windows passed", "value": 4, "threshold": 3, "passed": True, "auto_disqualify": True},
        {"name": "Win Rate", "value": 0.55, "threshold": 0.50, "passed": True, "auto_disqualify": False},
        {"name": "Parameter Sensitivity", "value": "PASS", "threshold": None, "passed": True, "auto_disqualify": True},
    ],
    "auto_disqualifiers": [],
    "failing_criteria": [],
}

FAIL_VERDICT = dict(MINIMAL_VERDICT, overall_verdict="FAIL", disqualify_reason="IS Sharpe below 1.0")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_load_verdict_returns_none_for_none_path():
    result = load_verdict(None)
    assert result is None, f"Expected None, got {result}"
    print("  [OK] load_verdict(None) returns None")


def test_load_verdict_returns_none_for_missing_file():
    result = load_verdict(Path("/tmp/does_not_exist_abc123.json"))
    assert result is None, f"Expected None for missing file, got {result}"
    print("  [OK] load_verdict(missing path) returns None")


def test_load_verdict_loads_valid_json():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(MINIMAL_VERDICT, f)
        tmp = Path(f.name)
    result = load_verdict(tmp)
    assert result is not None
    assert result["overall_verdict"] == "PASS"
    tmp.unlink()
    print("  [OK] load_verdict loads valid JSON correctly")


def test_build_verdict_banner_pass():
    html = _build_verdict_banner(MINIMAL_VERDICT)
    assert "PASS" in html
    assert "TestStrategy" in html
    assert "#2E7D32" in html or "green" in html.lower() or "E8F5E9" in html
    print("  [OK] PASS verdict banner contains correct content and green color")


def test_build_verdict_banner_fail():
    html = _build_verdict_banner(FAIL_VERDICT)
    assert "FAIL" in html
    assert "#C62828" in html or "red" in html.lower() or "FFEBEE" in html
    print("  [OK] FAIL verdict banner contains red color")


def test_build_report_without_verdict_returns_5_row_figure():
    fig, banner = build_report(MINIMAL_BACKTEST, verdict_data=None)
    # 5 rows: equity, drawdown, rolling sharpe, trade scatter, metrics table
    assert len(fig.data) >= 1, "Figure should have at least one trace"
    assert banner == "", f"Banner should be empty string without verdict, got: {banner!r}"
    print("  [OK] build_report without verdict returns figure with empty banner")


def test_build_report_with_verdict_returns_banner_html():
    fig, banner = build_report(MINIMAL_BACKTEST, verdict_data=MINIMAL_VERDICT)
    assert "PASS" in banner, f"Banner HTML should contain PASS, got: {banner[:200]}"
    assert len(fig.data) > 5, f"Figure with verdict should have more traces, got {len(fig.data)}"
    print("  [OK] build_report with verdict returns non-empty banner and enriched figure")


def test_build_report_with_verdict_figure_contains_wf_traces():
    fig, _ = build_report(MINIMAL_BACKTEST, verdict_data=MINIMAL_VERDICT)
    trace_names = [t.name for t in fig.data if hasattr(t, "name")]
    assert any("IS Sharpe" in (n or "") for n in trace_names) or any("Walk" in (n or "") for n in trace_names), (
        f"Expected walk-forward traces, got: {trace_names}"
    )
    print("  [OK] figure with verdict contains walk-forward chart traces")


def test_build_report_wf_chart_uses_wf_table_from_backtest():
    fig, _ = build_report(MINIMAL_BACKTEST, verdict_data=MINIMAL_VERDICT)
    # The WF chart should have 4 data points (one per window)
    wf_traces = [t for t in fig.data if hasattr(t, "name") and t.name and "IS Sharpe" in t.name]
    if wf_traces:
        assert len(wf_traces[0].x) == 4, f"Expected 4 WF windows, got {len(wf_traces[0].x)}"
    print("  [OK] walk-forward chart has correct number of windows (4)")


def test_build_report_regime_chart_uses_verdict_regime_slice():
    fig, _ = build_report(MINIMAL_BACKTEST, verdict_data=MINIMAL_VERDICT)
    regime_traces = [t for t in fig.data if hasattr(t, "name") and t.name and "Regime" in t.name]
    assert len(regime_traces) > 0, f"Expected regime chart traces, got: {[t.name for t in fig.data]}"
    print("  [OK] regime-slice chart trace present in figure")


def test_build_report_with_empty_regime_slice_skips_regime_chart_gracefully():
    verdict_no_regime = dict(MINIMAL_VERDICT, regime_slice={})
    fig, banner = build_report(MINIMAL_BACKTEST, verdict_data=verdict_no_regime)
    assert "PASS" in banner
    # Should not raise; regime chart may show "no data" annotation
    print("  [OK] empty regime_slice does not crash report generation")


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_load_verdict_returns_none_for_none_path,
        test_load_verdict_returns_none_for_missing_file,
        test_load_verdict_loads_valid_json,
        test_build_verdict_banner_pass,
        test_build_verdict_banner_fail,
        test_build_report_without_verdict_returns_5_row_figure,
        test_build_report_with_verdict_returns_banner_html,
        test_build_report_with_verdict_figure_contains_wf_traces,
        test_build_report_wf_table_uses_wf_table_from_backtest,
        test_build_report_regime_chart_uses_verdict_regime_slice,
        test_build_report_with_empty_regime_slice_skips_regime_chart_gracefully,
    ]
    # Rename for clarity
    tests[8] = test_build_report_wf_chart_uses_wf_table_from_backtest

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(0 if failed == 0 else 1)
```

- [ ] **Step 2: Run tests to confirm they fail (functions not yet implemented)**

```bash
cd /home/lamho/Documents/repos/quant-zero
python tests/test_report_gate1.py
```

Expected: `ImportError` or `AttributeError` on `load_verdict` / `_build_verdict_banner` — these do not exist yet. That confirms the tests are real.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_report_gate1.py
git commit -m "test: add failing tests for Gate 1 enhanced report"
```

---

## Task 3: Add `--verdict` CLI arg and `load_verdict()` to report.py

**Files:**
- Modify: `visualization/report.py`

- [ ] **Step 1: Add `load_verdict()` function after `load_backtest_json()`**

In `visualization/report.py`, after the `load_backtest_json()` function (around line 55), add:

```python
def load_verdict(path) -> dict | None:
    """
    Load a verdict JSON file. Returns None if path is None or file not found.
    Never raises — missing verdict degrades gracefully to base report.
    """
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        print(f"WARNING: verdict file not found: {p}. Gate 1 sections will be skipped.", file=sys.stderr)
        return None
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            print(f"WARNING: verdict file is not a JSON object: {p}. Skipping.", file=sys.stderr)
            return None
        return data
    except json.JSONDecodeError as e:
        print(f"WARNING: verdict file is not valid JSON: {p}: {e}. Skipping.", file=sys.stderr)
        return None
```

- [ ] **Step 2: Add `--verdict` to `_parse_args()`**

Find `_parse_args()` (around line 265). After the `--output` argument block, add:

```python
parser.add_argument(
    "--verdict",
    metavar="PATH",
    default=None,
    help=(
        "Path to the Gate 1 verdict JSON file (e.g. backtests/<strategy>_<date>_verdict.json). "
        "When provided, adds verdict banner, walk-forward chart, regime-slice chart, "
        "and Gate 1 checklist table to the report."
    ),
)
```

- [ ] **Step 3: Wire `--verdict` into `main()`**

Find `main()` (around line 280). After `data = load_backtest_json(input_path)`, add:

```python
verdict_data = load_verdict(args.verdict) if args.verdict else None
if verdict_data:
    print(f"Verdict: {verdict_data.get('overall_verdict', 'UNKNOWN')} ({args.verdict})")
```

Then update the `build_report` call (currently `fig = build_report(data)`) to:

```python
fig, banner_html = build_report(data, verdict_data=verdict_data)
```

And update the HTML write block. Replace `pio.write_html(...)` with:

```python
if banner_html:
    # Custom HTML wrapper: banner + Plotly figure
    figure_div = pio.to_html(
        fig,
        include_plotlyjs=True,
        full_html=False,
        auto_open=False,
    )
    full_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{data.get('strategy_name', 'Backtest')} — Gate 1 Report</title>
  <style>
    body {{ margin: 0; padding: 16px; font-family: Arial, sans-serif; background: #fafafa; }}
    .report-container {{ max-width: 1400px; margin: 0 auto; }}
  </style>
</head>
<body>
  <div class="report-container">
    {banner_html}
    {figure_div}
  </div>
</body>
</html>"""
    output_path.write_text(full_html)
else:
    pio.write_html(
        fig,
        file=str(output_path),
        include_plotlyjs=True,
        full_html=True,
        auto_open=False,
    )
```

- [ ] **Step 4: Update `build_report()` signature**

Change the signature from:
```python
def build_report(data: dict) -> go.Figure:
```
to:
```python
def build_report(data: dict, verdict_data: dict | None = None) -> tuple[go.Figure, str]:
```

And change the return statement at the end from `return fig` to `return fig, ""`. (The banner will be returned in later tasks.)

- [ ] **Step 5: Run tests — load_verdict tests should now pass**

```bash
cd /home/lamho/Documents/repos/quant-zero
python tests/test_report_gate1.py
```

Expected: first 3 tests pass (`load_verdict` tests), remaining tests fail or error on `_build_verdict_banner` / new `build_report` signature. That's correct progress.

- [ ] **Step 6: Commit**

```bash
git add visualization/report.py
git commit -m "feat: add --verdict CLI arg and load_verdict() to report.py"
```

---

## Task 4: Add verdict banner

**Files:**
- Modify: `visualization/report.py`

- [ ] **Step 1: Add `_build_verdict_banner()` function**

Add this function after `load_verdict()` (before `_normalise_metrics()`):

```python
def _build_verdict_banner(verdict_data: dict) -> str:
    """
    Build an HTML div verdict banner for the top of the report.
    Returns an HTML string.
    """
    verdict = verdict_data.get("overall_verdict", "UNKNOWN")
    strategy = verdict_data.get("strategy_name", "")
    date = verdict_data.get("date", "")
    disqualify = verdict_data.get("disqualify_reason") or ""

    color_map = {
        "PASS": ("#E8F5E9", "#2E7D32", "#1B5E20", "✅"),
        "CONDITIONAL PASS": ("#FFF8E1", "#F9A825", "#E65100", "⚠️"),
        "FAIL": ("#FFEBEE", "#FFCDD2", "#C62828", "❌"),
    }
    bg, border_bg, fg, icon = color_map.get(verdict, ("#F5F5F5", "#E0E0E0", "#424242", "ℹ️"))

    # Extract headline metrics from the metrics list
    metrics_by_name = {m["name"]: m for m in verdict_data.get("metrics", [])}

    def _metric_val(name: str) -> str:
        m = metrics_by_name.get(name, {})
        v = m.get("value")
        if v is None:
            return "N/A"
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v)

    oos_sharpe = _metric_val("OOS Sharpe")
    dsr = _metric_val("Deflated Sharpe Ratio")
    wf_windows = _metric_val("Walk-forward windows passed")

    disqualify_html = (
        f'<p style="margin:8px 0 0 0; color:#C62828; font-size:13px;"><strong>Auto-disqualifier:</strong> {disqualify}</p>'
        if disqualify
        else ""
    )

    return f"""<div style="background:{bg}; border-left: 6px solid {fg}; border-radius: 4px; padding: 16px 24px; margin: 0 0 20px 0;">
  <h2 style="color:{fg}; margin:0 0 6px 0; font-size:20px; font-family: Arial, sans-serif;">{icon}&nbsp; Gate 1 Verdict: <strong>{verdict}</strong></h2>
  <p style="margin:0; color:#333; font-size:14px; font-family: Arial, sans-serif;">
    <strong>Strategy:</strong> {strategy} &nbsp;|&nbsp;
    <strong>Date:</strong> {date} &nbsp;|&nbsp;
    <strong>OOS Sharpe:</strong> {oos_sharpe} &nbsp;|&nbsp;
    <strong>DSR:</strong> {dsr} &nbsp;|&nbsp;
    <strong>WF Windows:</strong> {wf_windows}
  </p>
  {disqualify_html}
</div>"""
```

- [ ] **Step 2: Wire `_build_verdict_banner()` into `build_report()`**

In `build_report()`, just before `return fig, ""`, change to:

```python
banner_html = _build_verdict_banner(verdict_data) if verdict_data else ""
return fig, banner_html
```

- [ ] **Step 3: Run tests — banner tests should now pass**

```bash
cd /home/lamho/Documents/repos/quant-zero
python tests/test_report_gate1.py
```

Expected: tests 1–5 pass (load_verdict + banner tests). Tests 6+ still fail on `build_report` return type / new chart sections.

- [ ] **Step 4: Commit**

```bash
git add visualization/report.py
git commit -m "feat: add Gate 1 verdict banner to report"
```

---

## Task 5: Add walk-forward windows chart

**Files:**
- Modify: `visualization/report.py`

- [ ] **Step 1: Add `_build_wf_traces()` function**

Add after `_build_metrics_table()` (before `# ── Main report builder`):

```python
def _build_wf_traces(backtest_data: dict) -> list[go.Bar]:
    """
    Build grouped bar traces for walk-forward IS vs OOS Sharpe per window.
    Colors each OOS bar green (pass) or red (fail).
    Returns empty list if no wf_table data.
    """
    wf_table = backtest_data.get("wf_table", [])
    if not wf_table:
        return []

    window_labels = [f"W{w.get('window', i + 1)}" for i, w in enumerate(wf_table)]
    is_sharpes = [w.get("is_sharpe", 0.0) for w in wf_table]
    oos_sharpes = [w.get("oos_sharpe", 0.0) for w in wf_table]
    oos_colors = ["#2E7D32" if w.get("pass", False) else "#C62828" for w in wf_table]

    return [
        go.Bar(
            name="IS Sharpe",
            x=window_labels,
            y=is_sharpes,
            marker_color="#1565C0",
            opacity=0.7,
            hovertemplate="<b>%{x}</b><br>IS Sharpe: %{y:.3f}<extra></extra>",
        ),
        go.Bar(
            name="OOS Sharpe",
            x=window_labels,
            y=oos_sharpes,
            marker_color=oos_colors,
            hovertemplate="<b>%{x}</b><br>OOS Sharpe: %{y:.3f}<extra>%{marker.color}</extra>",
        ),
    ]
```

- [ ] **Step 2: Update `build_report()` to conditionally add row 6 (WF chart)**

Inside `build_report()`, find the `make_subplots(rows=5, ...)` call. Replace the entire `make_subplots` block with a conditional version:

```python
has_verdict = verdict_data is not None
n_rows = 8 if has_verdict else 5

if has_verdict:
    row_heights = [0.20, 0.11, 0.11, 0.13, 0.17, 0.11, 0.11, 0.06]
    subplot_titles = (
        "Equity Curve",
        "Drawdown (%)",
        "Rolling 30-Day Sharpe (Annualised)",
        "Trade PnL Scatter",
        "Performance Metrics",
        "Walk-Forward Windows (IS vs OOS Sharpe)",
        "Regime-Slice Sharpe",
        "Gate 1 Checklist",
    )
    specs = [
        [{"type": "scatter"}],
        [{"type": "scatter"}],
        [{"type": "scatter"}],
        [{"type": "scatter"}],
        [{"type": "table"}],
        [{"type": "bar"}],
        [{"type": "bar"}],
        [{"type": "table"}],
    ]
else:
    row_heights = [0.28, 0.16, 0.16, 0.18, 0.22]
    subplot_titles = (
        "Equity Curve",
        "Drawdown (%)",
        "Rolling 30-Day Sharpe (Annualised)",
        "Trade PnL Scatter",
        "Performance Metrics",
    )
    specs = [
        [{"type": "scatter"}],
        [{"type": "scatter"}],
        [{"type": "scatter"}],
        [{"type": "scatter"}],
        [{"type": "table"}],
    ]

fig = make_subplots(
    rows=n_rows,
    cols=1,
    row_heights=row_heights,
    vertical_spacing=0.04,
    subplot_titles=subplot_titles,
    specs=specs,
)
```

- [ ] **Step 3: Add WF chart traces to row 6 in `build_report()`**

After the `# ── Row 5: Metrics table` block (after `fig.add_trace(_build_metrics_table(metrics), row=5, col=1)`), add:

```python
# ── Row 6: Walk-forward windows (only when verdict is provided) ───────────
if has_verdict:
    wf_traces = _build_wf_traces(data)
    if wf_traces:
        for trace in wf_traces:
            fig.add_trace(trace, row=6, col=1)
        # OOS Sharpe threshold reference line
        fig.add_hline(
            y=0.7,
            line_dash="dot",
            line_color="rgba(0,0,0,0.4)",
            annotation_text="OOS threshold (0.7)",
            annotation_position="right",
            row=6, col=1,
        )
    else:
        fig.add_annotation(
            text="No walk-forward data available (wf_table missing from backtest JSON)",
            xref="x6 domain", yref="y6 domain", x=0.5, y=0.5,
            showarrow=False, row=6, col=1,
        )
    fig.update_layout(barmode="group")
```

- [ ] **Step 4: Run tests — WF chart tests should now pass**

```bash
cd /home/lamho/Documents/repos/quant-zero
python tests/test_report_gate1.py
```

Expected: tests 1–8 pass (including `test_build_report_with_verdict_figure_contains_wf_traces` and `test_build_report_wf_chart_uses_wf_table_from_backtest`).

- [ ] **Step 5: Commit**

```bash
git add visualization/report.py
git commit -m "feat: add walk-forward windows chart to Gate 1 report"
```

---

## Task 6: Add regime-slice chart

**Files:**
- Modify: `visualization/report.py`

- [ ] **Step 1: Add `_build_regime_traces()` function**

Add immediately after `_build_wf_traces()`:

```python
_REGIME_DISPLAY_NAMES = {
    "pre_covid_2018_2019": "Pre-COVID (2018–19)",
    "stimulus_2020_2021": "Stimulus Era (2020–21)",
    "rate_shock_2022": "Rate Shock (2022)",
    "normalization_2023": "Normalization (2023)",
}

def _build_regime_traces(verdict_data: dict) -> list[go.Bar]:
    """
    Build horizontal bar trace for regime-slice Sharpe per regime.
    Returns empty list if regime_slice is missing or empty.
    """
    regime_slice = verdict_data.get("regime_slice", {})
    if not regime_slice:
        return []

    _THRESHOLD = 0.8
    labels = [_REGIME_DISPLAY_NAMES.get(k, k) for k in regime_slice]
    values = list(regime_slice.values())
    colors = ["#2E7D32" if v >= _THRESHOLD else "#C62828" for v in values]

    return [
        go.Bar(
            name="Regime Sharpe",
            x=values,
            y=labels,
            orientation="h",
            marker_color=colors,
            hovertemplate="<b>%{y}</b><br>Sharpe: %{x:.3f}<extra></extra>",
        )
    ]
```

- [ ] **Step 2: Add regime chart traces to row 7 in `build_report()`**

After the row 6 WF chart block, add:

```python
# ── Row 7: Regime-slice (only when verdict is provided) ───────────────────
if has_verdict:
    regime_traces = _build_regime_traces(verdict_data)
    if regime_traces:
        for trace in regime_traces:
            fig.add_trace(trace, row=7, col=1)
        fig.add_vline(
            x=0.8,
            line_dash="dot",
            line_color="rgba(0,0,0,0.4)",
            annotation_text="Min threshold (0.8)",
            annotation_position="top right",
            row=7, col=1,
        )
    else:
        fig.add_annotation(
            text="No regime-slice data available (regime_slice missing from verdict JSON)",
            xref="x7 domain", yref="y7 domain", x=0.5, y=0.5,
            showarrow=False, row=7, col=1,
        )
```

- [ ] **Step 3: Run tests — regime chart tests should now pass**

```bash
cd /home/lamho/Documents/repos/quant-zero
python tests/test_report_gate1.py
```

Expected: tests 1–10 pass (including `test_build_report_regime_chart_uses_verdict_regime_slice` and `test_build_report_with_empty_regime_slice_skips_regime_chart_gracefully`).

- [ ] **Step 4: Commit**

```bash
git add visualization/report.py
git commit -m "feat: add regime-slice chart to Gate 1 report"
```

---

## Task 7: Add Gate 1 checklist table

**Files:**
- Modify: `visualization/report.py`

- [ ] **Step 1: Add `_build_gate1_checklist()` function**

Add after `_build_regime_traces()`:

```python
def _build_gate1_checklist(verdict_data: dict) -> go.Table:
    """
    Build a full Gate 1 checklist Plotly Table from verdict metrics.
    Auto-disqualifiers are highlighted red. Passing rows are green.
    """
    metrics = verdict_data.get("metrics", [])

    if not metrics:
        return go.Table(
            header=dict(values=["<b>No Gate 1 metrics in verdict JSON</b>"], fill_color="#F5F5F5"),
            cells=dict(values=[["Check that gate1_reporter.py produces a metrics array"]]),
        )

    def _fmt(v) -> str:
        if v is None:
            return "N/A"
        if isinstance(v, float):
            return f"{v:.4f}"
        if isinstance(v, bool):
            return "Yes" if v else "No"
        return str(v)

    def _fmt_threshold(m: dict) -> str:
        t = m.get("threshold")
        if t is None:
            return "—"
        if isinstance(t, float):
            return f"{t:.4f}"
        return str(t)

    names = [m["name"] for m in metrics]
    values_col = [_fmt(m.get("value")) for m in metrics]
    thresholds_col = [_fmt_threshold(m) for m in metrics]
    result_col = ["✅ PASS" if m.get("passed") else "❌ FAIL" for m in metrics]
    auto_col = ["⚠️ Auto-DQ" if m.get("auto_disqualify") and not m.get("passed") else "" for m in metrics]

    # Row colors: auto-DQ fail = deep red, regular fail = light red, pass = light green
    row_colors = []
    for m in metrics:
        if m.get("auto_disqualify") and not m.get("passed"):
            row_colors.append("#FFCDD2")  # deep red: auto-disqualifier triggered
        elif not m.get("passed"):
            row_colors.append("#FFEBEE")  # light red: failed but not auto-DQ
        else:
            row_colors.append("#F1F8E9")  # light green: passed

    return go.Table(
        header=dict(
            values=["<b>Criterion</b>", "<b>Value</b>", "<b>Threshold</b>", "<b>Result</b>", "<b>Notes</b>"],
            fill_color="#1565C0",
            font=dict(color="white", size=11),
            align="left",
            height=26,
        ),
        cells=dict(
            values=[names, values_col, thresholds_col, result_col, auto_col],
            fill_color=[row_colors, row_colors, row_colors, row_colors, row_colors],
            align=["left", "right", "right", "left", "left"],
            font=dict(size=10),
            height=22,
        ),
    )
```

- [ ] **Step 2: Add Gate 1 checklist table to row 8 in `build_report()`**

After the row 7 regime chart block, add:

```python
# ── Row 8: Gate 1 checklist table (only when verdict is provided) ─────────
if has_verdict:
    fig.add_trace(_build_gate1_checklist(verdict_data), row=8, col=1)
```

- [ ] **Step 3: Update figure height for the 8-row layout**

Find `fig.update_layout(height=1400, ...)`. Change to a conditional:

```python
fig.update_layout(
    title=dict(
        text=f"<b>{strategy_name}</b>{title_verdict}<br><sup>{report_date}</sup>",
        font=dict(size=18),
        x=0.5,
        xanchor="center",
    ),
    height=2000 if has_verdict else 1400,
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    plot_bgcolor="white",
    paper_bgcolor="white",
    hovermode="x unified",
    font=dict(family="Arial, sans-serif", size=11),
    margin=dict(l=60, r=40, t=100, b=40),
)
```

Also update the axis-styling loop. The current loop runs `for i in range(1, 5)`. Change to:

```python
scatter_rows = 4  # rows 1–4 always have scatter x-axes
for i in range(1, scatter_rows + 1):
    fig.update_xaxes(
        showgrid=True, gridcolor="#EEEEEE", gridwidth=1,
        zeroline=False, row=i, col=1,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor="#EEEEEE", gridwidth=1,
        zeroline=False, row=i, col=1,
    )

# Row 6: WF bar chart axes (if verdict present)
if has_verdict:
    fig.update_xaxes(showgrid=True, gridcolor="#EEEEEE", row=6, col=1)
    fig.update_yaxes(showgrid=True, gridcolor="#EEEEEE", row=6, col=1, title_text="Sharpe")
    fig.update_xaxes(showgrid=True, gridcolor="#EEEEEE", row=7, col=1, title_text="Sharpe")
    fig.update_yaxes(showgrid=True, gridcolor="#EEEEEE", row=7, col=1)
```

- [ ] **Step 4: Run the full test suite — all tests should now pass**

```bash
cd /home/lamho/Documents/repos/quant-zero
python tests/test_report_gate1.py
```

Expected output:
```
  [OK] load_verdict(None) returns None
  [OK] load_verdict(missing path) returns None
  [OK] load_verdict loads valid JSON correctly
  [OK] PASS verdict banner contains correct content and green color
  [OK] FAIL verdict banner contains red color
  [OK] build_report without verdict returns figure with empty banner
  [OK] build_report with verdict returns non-empty banner and enriched figure
  [OK] figure with verdict contains walk-forward chart traces
  [OK] walk-forward chart has correct number of windows (4)
  [OK] regime-slice chart trace present in figure
  [OK] empty regime_slice does not crash report generation

11/11 tests passed
```

- [ ] **Step 5: Manual smoke test — generate a real report**

```bash
cd /home/lamho/Documents/repos/quant-zero
# Use an existing backtest JSON (adjust filename if needed)
BACKTEST=$(ls backtests/*.json | grep -v verdict | grep -v test | head -1)
echo "Using: $BACKTEST"
python visualization/report.py --backtest "$BACKTEST"
```

Open the generated HTML in a browser and verify the base report works (no verdict flags).

- [ ] **Step 6: Commit**

```bash
git add visualization/report.py
git commit -m "feat: add Gate 1 checklist table to enhanced report"
```

---

## Task 8: Update Overfit Detector AGENTS.md with Reporting section

**Files:**
- Modify: `agents/overfit-detector/AGENTS.md`

- [ ] **Step 1: Add Reporting section before the Git Sync Workflow section**

Open `agents/overfit-detector/AGENTS.md`. Find the line `## Git Sync Workflow`. Insert the following block immediately before it:

```markdown
## Reporting (Final Step After Gate 1)

After saving the verdict JSON to `/backtests/{strategy_name}_{date}_verdict.json`, generate and publish the Gate 1 report. This step is mandatory for every verdict — PASS, FAIL, and CONDITIONAL PASS.

### 1. Generate the HTML report

```bash
cd /repos/quant-zero
python visualization/report.py \
  --backtest backtests/{strategy_name}_{date}.json \
  --verdict backtests/{strategy_name}_{date}_verdict.json
```

Output: `backtests/{strategy_name}_{date}_report.html`

If `--backtest` file is missing (verdict-only run), log a warning and skip. Do not block.

### 2. Commit the report to git

```bash
git checkout -b feat/QUA-{N}-gate1-report
git add backtests/{strategy_name}_{date}_report.html
git commit -m "feat(QUA-{N}): Gate 1 report for {strategy_name}

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
git push -u origin feat/QUA-{N}-gate1-report
```

### 3. Post Paperclip comment on the issue

Use the `paperclip` skill to post a comment on the issue QUA-{N}. Format the comment as follows — populate all values from the verdict JSON:

```markdown
## Gate 1 Report: {strategy_name}

**Verdict:** [✅ PASS / ❌ FAIL / ⚠️ CONDITIONAL PASS]

| Criterion | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| IS Sharpe | {is_sharpe} | > 1.0 | [✅ PASS / ❌ FAIL] |
| OOS Sharpe | {oos_sharpe} | > 0.7 | [✅ PASS / ❌ FAIL] |
| Deflated Sharpe Ratio | {dsr} | > 0 | [✅ PASS / ❌ FAIL] |
| Walk-forward Windows | {wf_windows}/4 | ≥ 3 | [✅ PASS / ❌ FAIL] |
| IS Max Drawdown | {is_mdd}% | < 20% | [✅ PASS / ❌ FAIL] |
| OOS Max Drawdown | {oos_mdd}% | < 25% | [✅ PASS / ❌ FAIL] |
| Win Rate | {win_rate}% | > 50% | [✅ PASS / ❌ FAIL] |
| Parameter Sensitivity | — | stable ±20% | [✅ PASS / ❌ FAIL] |
| Regime-Slice | {regime_pass}/4 regimes ≥ 0.8 | ≥ 2 incl. stress | [✅ PASS / ❌ FAIL] |
| Post-Cost Sharpe | {post_cost_sharpe} | > 0.7 | [✅ PASS / ❌ FAIL] |

**Auto-disqualifiers triggered:** [None / list reason]
**Report:** `backtests/{strategy_name}_{date}_report.html`
**Branch:** `feat/QUA-{N}-gate1-report`

Open the HTML report locally: `file:///repos/quant-zero/backtests/{strategy_name}_{date}_report.html`
```

### Error handling

- If `visualization/report.py` fails: log the error as a Paperclip comment, skip the HTML commit, post the metrics table comment anyway.
- If `git push` fails: include the report path in the Paperclip comment; note that the file is available locally at the path shown.
- If the Paperclip API call fails: write the comment content to `docs/heartbeats/risk/{date}-gate1-{strategy_name}.md` as fallback.

```

- [ ] **Step 2: Verify the section was inserted correctly**

```bash
grep -n "Reporting (Final Step" agents/overfit-detector/AGENTS.md
```

Expected: line number output confirming the section exists before `## Git Sync Workflow`.

- [ ] **Step 3: Commit**

```bash
git add agents/overfit-detector/AGENTS.md
git commit -m "feat: add Gate 1 reporting step to Overfit Detector AGENTS.md"
```

---

## Task 9: End-to-end smoke test

- [ ] **Step 1: Run full test suite one final time**

```bash
cd /home/lamho/Documents/repos/quant-zero
python tests/test_report_gate1.py
```

Expected: `11/11 tests passed`

- [ ] **Step 2: Generate a report with a real verdict JSON if one exists**

```bash
cd /home/lamho/Documents/repos/quant-zero
BACKTEST=$(ls backtests/*.json | grep -v verdict | grep -v test | head -1)
VERDICT="${BACKTEST/_\.json/_verdict.json}"
# Try to find a matching verdict
VERDICT=$(echo "$BACKTEST" | sed 's/\.json$/_verdict.json/')
if [ -f "$VERDICT" ]; then
  python visualization/report.py --backtest "$BACKTEST" --verdict "$VERDICT"
  echo "Report generated. Open in browser:"
  echo "  file://$(realpath ${BACKTEST%.json}_report.html)"
else
  echo "No matching verdict JSON found for $BACKTEST — skipping end-to-end test"
  echo "Run gate1_reporter.py first to generate a verdict, then retry"
fi
```

- [ ] **Step 3: Final commit — bump version comment in report.py**

At the top of `visualization/report.py`, update the docstring to note the `--verdict` flag:

Change:
```python
    python visualization/report.py --backtest backtests/<strategy>_<date>.json
```
to:
```python
    python visualization/report.py --backtest backtests/<strategy>_<date>.json
    python visualization/report.py --backtest backtests/<strategy>_<date>.json --verdict backtests/<strategy>_<date>_verdict.json
```

And update the "Charts produced" list to add:
```python
    Gate 1 sections (when --verdict provided):
    6. Walk-forward windows — grouped bar: IS vs OOS Sharpe per window, colored pass/fail
    7. Regime-slice         — horizontal bar: Sharpe per market regime vs 0.8 threshold
    8. Gate 1 checklist     — full criterion table with pass/fail and auto-DQ highlights
    Verdict banner          — top-of-page HTML summary with headline metrics
```

```bash
git add visualization/report.py
git commit -m "docs: update report.py docstring with --verdict usage and new chart list"
```
