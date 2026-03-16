"""
visualization/report.py
=======================
Generate a self-contained interactive HTML backtest report from a Gate 1 JSON file.

Usage:
    python visualization/report.py --backtest backtests/<strategy>_<date>.json
    python visualization/report.py --backtest backtests/<strategy>_<date>.json --output /tmp/my_report.html
    python visualization/report.py --help

Output:
    <source_json_basename>_report.html in the same directory as the input JSON
    (override with --output)

Charts produced (Plotly, single self-contained HTML):
    1. Equity curve      — portfolio value over time; IS/OOS periods shaded
    2. Drawdown          — percentage drawdown from peak over time
    3. Rolling 30d Sharpe — annualised rolling Sharpe ratio
    4. Trade PnL scatter  — each closed trade (x=exit date, y=PnL $), coloured by direction
    5. Metrics table      — IS Sharpe, OOS Sharpe, MDD, win rate, profit factor, # trades

Requires: plotly (pip install plotly)
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np


# ── Plotly is an optional dependency not in the base orchestrator requirements ──

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.io as pio
except ImportError as exc:
    print(
        "ERROR: plotly is required for report generation.\n"
        "Install it with:  pip install plotly\n"
        f"Original error: {exc}",
        file=sys.stderr,
    )
    sys.exit(1)


# ── JSON loading ──────────────────────────────────────────────────────────────

def load_backtest_json(path: Path) -> dict:
    """Load and validate a backtest JSON file. Raises ValueError on schema issues."""
    if not path.exists():
        raise FileNotFoundError(f"Backtest file not found: {path}")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")
    return data


# ── Schema normalisation ──────────────────────────────────────────────────────

def _normalise_metrics(data: dict) -> dict:
    """
    Return a flat metrics dict regardless of whether the JSON uses the
    flat orchestrator format or the gate1_reporter verdict format.
    """
    metrics: dict = {}

    # Flat orchestrator format (BollingerBand etc.)
    metrics["is_sharpe"] = data.get("is_sharpe") or data.get("sharpe_in_sample")
    metrics["oos_sharpe"] = data.get("oos_sharpe") or data.get("sharpe_out_of_sample")
    metrics["is_mdd"] = data.get("is_max_drawdown") or data.get("max_dd_in_sample")
    metrics["oos_mdd"] = data.get("oos_max_drawdown") or data.get("max_dd_out_of_sample")
    metrics["win_rate"] = data.get("win_rate") or data.get("win_rate_in_sample")
    metrics["profit_factor"] = data.get("profit_factor")
    metrics["trade_count"] = data.get("trade_count") or data.get("trades_in_sample")
    metrics["oos_trade_count"] = data.get("oos_trade_count")
    metrics["gate1_verdict"] = data.get("gate1_verdict") or data.get("overall_verdict")
    metrics["strategy_name"] = data.get("strategy_name", "Unknown Strategy")
    metrics["date"] = data.get("date", "")

    # gate1_reporter verdict format (metrics[] array)
    for m in data.get("metrics", []):
        name = m.get("name", "")
        val = m.get("value")
        if name == "IS Sharpe" and metrics["is_sharpe"] is None:
            metrics["is_sharpe"] = val
        elif name == "OOS Sharpe" and metrics["oos_sharpe"] is None:
            metrics["oos_sharpe"] = val
        elif name == "IS Max Drawdown" and metrics["is_mdd"] is None:
            metrics["is_mdd"] = val
        elif name == "Win Rate" and metrics["win_rate"] is None:
            metrics["win_rate"] = val
        elif name == "Trade Count" and metrics["trade_count"] is None:
            metrics["trade_count"] = val

    return metrics


def _parse_equity_curve(data: dict) -> pd.DataFrame:
    """Return a DataFrame with columns: date, portfolio_value, drawdown_pct."""
    records = data.get("equity_curve", [])
    if not records:
        return pd.DataFrame(columns=["date", "portfolio_value", "drawdown_pct"])
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["portfolio_value"] = pd.to_numeric(df["portfolio_value"], errors="coerce")
    df["drawdown_pct"] = pd.to_numeric(df["drawdown_pct"], errors="coerce")
    return df


def _parse_trade_log(data: dict) -> pd.DataFrame:
    """Return a DataFrame with one row per closed trade."""
    records = data.get("trade_log", [])
    if not records:
        return pd.DataFrame(columns=["trade_id", "entry_date", "exit_date",
                                     "entry_price", "exit_price", "shares",
                                     "direction", "pnl", "pnl_pct"])
    df = pd.DataFrame(records)
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    df["pnl_pct"] = pd.to_numeric(df["pnl_pct"], errors="coerce")
    return df


def _get_is_oos_boundary(data: dict) -> tuple[str | None, str | None]:
    """
    Return (is_end_date_str, oos_start_date_str) derived from wf_windows.
    Returns (None, None) if not determinable.
    """
    wf = data.get("wf_windows", [])
    if not wf:
        return None, None
    # IS region = from start of data to end of first walk-forward IS window
    # OOS region = from start of first OOS window to end of last OOS window
    first = wf[0]
    is_end = first.get("is_end")
    oos_start = first.get("oos_start")
    return is_end, oos_start


# ── Rolling Sharpe helper ─────────────────────────────────────────────────────

def _rolling_sharpe(portfolio_value: pd.Series, window: int = 30) -> pd.Series:
    """
    Compute annualised rolling Sharpe from a portfolio value series.
    window: number of trading days (default 30).
    Returns a Series aligned to the input index.
    """
    returns = portfolio_value.pct_change()
    # Annualisation: sqrt(252) for daily
    roll_mean = returns.rolling(window).mean()
    roll_std = returns.rolling(window).std()
    sharpe = (roll_mean / (roll_std + 1e-12)) * np.sqrt(252)
    return sharpe


# ── Chart builders ────────────────────────────────────────────────────────────

_IS_FILL_COLOR = "rgba(144, 202, 249, 0.15)"   # light blue — in-sample
_OOS_FILL_COLOR = "rgba(255, 183, 77, 0.15)"   # light amber — out-of-sample


def _add_period_shading(fig: go.Figure, is_end: str | None, oos_start: str | None,
                        x_min: str, x_max: str, rows: list[int]) -> None:
    """
    Add IS/OOS background shading as vrect shapes. Applied to all listed subplot rows.
    """
    if not is_end or not oos_start:
        return
    for row in rows:
        # In-sample shading
        fig.add_vrect(
            x0=x_min, x1=is_end,
            fillcolor=_IS_FILL_COLOR, line_width=0,
            layer="below", row=row, col=1,
            annotation_text="IS" if row == rows[0] else None,
            annotation_position="top left",
        )
        # Out-of-sample shading
        fig.add_vrect(
            x0=oos_start, x1=x_max,
            fillcolor=_OOS_FILL_COLOR, line_width=0,
            layer="below", row=row, col=1,
            annotation_text="OOS" if row == rows[0] else None,
            annotation_position="top left",
        )


def _build_equity_curve_trace(ec_df: pd.DataFrame) -> go.Scatter:
    return go.Scatter(
        x=ec_df["date"],
        y=ec_df["portfolio_value"],
        mode="lines",
        name="Portfolio Value",
        line=dict(color="#1565C0", width=1.5),
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Value: $%{y:,.0f}<extra></extra>",
    )


def _build_drawdown_trace(ec_df: pd.DataFrame) -> go.Scatter:
    return go.Scatter(
        x=ec_df["date"],
        y=ec_df["drawdown_pct"],
        mode="lines",
        name="Drawdown %",
        fill="tozeroy",
        fillcolor="rgba(211, 47, 47, 0.25)",
        line=dict(color="#C62828", width=1),
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Drawdown: %{y:.2f}%<extra></extra>",
    )


def _build_rolling_sharpe_trace(ec_df: pd.DataFrame) -> go.Scatter:
    sharpe_series = _rolling_sharpe(ec_df.set_index("date")["portfolio_value"])
    return go.Scatter(
        x=sharpe_series.index,
        y=sharpe_series.values,
        mode="lines",
        name="30d Rolling Sharpe",
        line=dict(color="#6A1B9A", width=1.2),
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Sharpe: %{y:.2f}<extra></extra>",
    )


def _build_zero_line(x_min: str, x_max: str) -> go.Scatter:
    """Horizontal zero reference line for rolling Sharpe chart."""
    return go.Scatter(
        x=[x_min, x_max],
        y=[0, 0],
        mode="lines",
        name="Zero",
        line=dict(color="rgba(0,0,0,0.3)", width=1, dash="dot"),
        showlegend=False,
    )


def _build_trade_scatter(tl_df: pd.DataFrame) -> list[go.Scatter]:
    """Return two Scatter traces: one for long trades, one for short."""
    traces = []
    for direction, color, symbol in [
        ("long", "#2E7D32", "circle"),
        ("short", "#C62828", "triangle-down"),
    ]:
        subset = tl_df[tl_df["direction"] == direction] if "direction" in tl_df.columns else pd.DataFrame()
        if subset.empty:
            continue
        traces.append(
            go.Scatter(
                x=subset["exit_date"],
                y=subset["pnl"],
                mode="markers",
                name=f"{direction.title()} trades",
                marker=dict(
                    symbol=symbol,
                    color=color,
                    size=7,
                    opacity=0.8,
                    line=dict(width=0.5, color="white"),
                ),
                hovertemplate=(
                    "<b>%{x|%Y-%m-%d}</b><br>"
                    "PnL: $%{y:,.2f}<br>"
                    f"Direction: {direction}<extra></extra>"
                ),
            )
        )
    if not traces:
        # Fallback — all trades as neutral colour
        if not tl_df.empty:
            traces.append(
                go.Scatter(
                    x=tl_df["exit_date"],
                    y=tl_df["pnl"],
                    mode="markers",
                    name="Trades",
                    marker=dict(color="#546E7A", size=7, opacity=0.8),
                    hovertemplate="<b>%{x|%Y-%m-%d}</b><br>PnL: $%{y:,.2f}<extra></extra>",
                )
            )
    return traces


def _build_metrics_table(metrics: dict) -> go.Table:
    """Build a formatted metrics summary table."""

    def _fmt_pct(v):
        return f"{v * 100:.2f}%" if v is not None else "N/A"

    def _fmt_float(v, decimals=3):
        return f"{v:.{decimals}f}" if v is not None else "N/A"

    def _fmt_int(v):
        return str(int(v)) if v is not None else "N/A"

    rows = [
        ("IS Sharpe", _fmt_float(metrics.get("is_sharpe"))),
        ("OOS Sharpe", _fmt_float(metrics.get("oos_sharpe"))),
        ("IS Max Drawdown", _fmt_pct(metrics.get("is_mdd"))),
        ("OOS Max Drawdown", _fmt_pct(metrics.get("oos_mdd"))),
        ("Win Rate", _fmt_pct(metrics.get("win_rate"))),
        ("Profit Factor", _fmt_float(metrics.get("profit_factor"))),
        ("IS Trade Count", _fmt_int(metrics.get("trade_count"))),
        ("OOS Trade Count", _fmt_int(metrics.get("oos_trade_count"))),
        ("Gate 1 Verdict", str(metrics.get("gate1_verdict") or "N/A")),
    ]

    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]

    # Colour verdict cell red/green
    cell_fill_colors = []
    for label, val in rows:
        if label == "Gate 1 Verdict":
            if "PASS" in str(val).upper():
                cell_fill_colors.append("#E8F5E9")
            elif "FAIL" in str(val).upper():
                cell_fill_colors.append("#FFEBEE")
            else:
                cell_fill_colors.append("white")
        else:
            cell_fill_colors.append("white")

    return go.Table(
        header=dict(
            values=["<b>Metric</b>", "<b>Value</b>"],
            fill_color="#1565C0",
            font=dict(color="white", size=12),
            align="left",
            height=28,
        ),
        cells=dict(
            values=[labels, values],
            fill_color=[["#F5F5F5"] * len(rows), cell_fill_colors],
            align=["left", "right"],
            font=dict(size=11),
            height=24,
        ),
    )


# ── Main report builder ───────────────────────────────────────────────────────

def build_report(data: dict) -> go.Figure:
    """
    Build the full multi-panel Plotly figure from backtest JSON data.
    """
    metrics = _normalise_metrics(data)
    ec_df = _parse_equity_curve(data)
    tl_df = _parse_trade_log(data)
    is_end, oos_start = _get_is_oos_boundary(data)

    has_equity = not ec_df.empty
    has_trades = not tl_df.empty

    x_min = str(ec_df["date"].min())[:10] if has_equity else "2018-01-01"
    x_max = str(ec_df["date"].max())[:10] if has_equity else "2024-01-01"

    strategy_name = metrics.get("strategy_name", "Strategy")
    report_date = metrics.get("date", "")
    verdict = metrics.get("gate1_verdict") or ""
    title_verdict = f" — {verdict}" if verdict else ""

    # Layout: 5 rows, varying row heights
    fig = make_subplots(
        rows=5,
        cols=1,
        row_heights=[0.28, 0.16, 0.16, 0.18, 0.22],
        vertical_spacing=0.05,
        subplot_titles=(
            "Equity Curve",
            "Drawdown (%)",
            "Rolling 30-Day Sharpe (Annualised)",
            "Trade PnL Scatter",
            "Performance Metrics",
        ),
        specs=[
            [{"type": "scatter"}],
            [{"type": "scatter"}],
            [{"type": "scatter"}],
            [{"type": "scatter"}],
            [{"type": "table"}],
        ],
    )

    # ── Row 1: Equity curve ───────────────────────────────────────────────────
    if has_equity:
        fig.add_trace(_build_equity_curve_trace(ec_df), row=1, col=1)
    else:
        fig.add_annotation(
            text="No equity curve data available",
            xref="x domain", yref="y domain", x=0.5, y=0.5,
            showarrow=False, row=1, col=1,
        )

    # ── Row 2: Drawdown ───────────────────────────────────────────────────────
    if has_equity:
        fig.add_trace(_build_drawdown_trace(ec_df), row=2, col=1)

    # ── Row 3: Rolling Sharpe ─────────────────────────────────────────────────
    if has_equity and len(ec_df) >= 30:
        fig.add_trace(_build_rolling_sharpe_trace(ec_df), row=3, col=1)
        fig.add_trace(_build_zero_line(x_min, x_max), row=3, col=1)
    else:
        fig.add_annotation(
            text="Insufficient data for 30-day rolling Sharpe",
            xref="x3 domain", yref="y3 domain", x=0.5, y=0.5,
            showarrow=False, row=3, col=1,
        )

    # ── Row 4: Trade PnL scatter ──────────────────────────────────────────────
    if has_trades:
        for trace in _build_trade_scatter(tl_df):
            fig.add_trace(trace, row=4, col=1)
    else:
        fig.add_annotation(
            text="No trade log data available",
            xref="x4 domain", yref="y4 domain", x=0.5, y=0.5,
            showarrow=False, row=4, col=1,
        )

    # ── Row 5: Metrics table ──────────────────────────────────────────────────
    fig.add_trace(_build_metrics_table(metrics), row=5, col=1)

    # ── IS/OOS period shading (rows 1–4) ──────────────────────────────────────
    if has_equity:
        _add_period_shading(fig, is_end, oos_start, x_min, x_max, rows=[1, 2, 3, 4])

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text=f"<b>{strategy_name}</b>{title_verdict}<br><sup>{report_date}</sup>",
            font=dict(size=18),
            x=0.5,
            xanchor="center",
        ),
        height=1400,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
        font=dict(family="Arial, sans-serif", size=11),
        margin=dict(l=60, r=40, t=100, b=40),
    )

    # Axis styling — light gridlines
    for i in range(1, 5):
        fig.update_xaxes(
            showgrid=True, gridcolor="#EEEEEE", gridwidth=1,
            zeroline=False, row=i, col=1,
        )
        fig.update_yaxes(
            showgrid=True, gridcolor="#EEEEEE", gridwidth=1,
            zeroline=False, row=i, col=1,
        )

    # Y-axis labels
    fig.update_yaxes(title_text="Portfolio Value ($)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)
    fig.update_yaxes(title_text="Sharpe", row=3, col=1)
    fig.update_yaxes(title_text="PnL ($)", row=4, col=1)

    return fig


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a self-contained interactive HTML backtest report from a Gate 1 JSON file.\n\n"
            "Example:\n"
            "  python visualization/report.py --backtest backtests/BollingerBand_2026-03-15.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--backtest",
        required=True,
        metavar="PATH",
        help="Path to the backtest JSON file (e.g. backtests/<strategy>_<date>.json)",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help=(
            "Path for the HTML output file. "
            "Defaults to <source_json_basename>_report.html in the same directory as the input."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    input_path = Path(args.backtest).resolve()

    # Determine output path
    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = input_path.parent / (input_path.stem + "_report.html")

    print(f"Loading: {input_path}")
    data = load_backtest_json(input_path)

    strategy_name = data.get("strategy_name", "Unknown Strategy")
    print(f"Strategy: {strategy_name}")

    # Warn if equity_curve / trade_log are empty (old migrated files)
    ec_len = len(data.get("equity_curve", []))
    tl_len = len(data.get("trade_log", []))
    if ec_len == 0:
        print(
            "WARNING: equity_curve is empty. "
            "Re-run the backtest with QUA-109 schema support to populate time-series data."
        )
    if tl_len == 0:
        print(
            "WARNING: trade_log is empty. "
            "Charts relying on per-trade data will be blank."
        )

    print("Building report…")
    fig = build_report(data)

    # Write self-contained HTML (no CDN, all JS bundled inline)
    pio.write_html(
        fig,
        file=str(output_path),
        include_plotlyjs=True,
        full_html=True,
        auto_open=False,
    )

    print(f"Report written: {output_path}")
    print(f"Open in browser: file://{output_path}")


if __name__ == "__main__":
    main()
