#!/usr/bin/env python3
"""
Build script for Quant Zero Dashboard.
Reads canonical data formats and produces dashboard output files.

Spec: docs/dashboard-spec.md §5

Usage:
    python3 scripts/build_dashboard.py
    python3 scripts/build_dashboard.py --output-dir docs/dashboard
"""

import argparse
import csv
import json
import math
import os
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    warnings.warn("pandas/numpy not available — Sharpe computation disabled", stacklevel=2)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Staleness thresholds per spec §3
STALENESS_HOURS = {
    "crypto": 2,
    "equities": 26,
    "futures": 4,
}


# ── Staleness ──────────────────────────────────────────────────────────────────

def is_stale(meta: dict, asset_class: str, now_utc: datetime) -> bool:
    """Return True when meta.last_update is older than the asset-class threshold."""
    last_update_str = meta.get("last_update", "")
    if not last_update_str:
        return True
    try:
        last_update = datetime.fromisoformat(last_update_str.replace("Z", "+00:00"))
        threshold = timedelta(hours=STALENESS_HOURS.get(asset_class, 26))
        return (now_utc - last_update) > threshold
    except (ValueError, TypeError):
        return True


# ── Sharpe ────────────────────────────────────────────────────────────────────

def rolling_sharpe(equity_csv_path: str, window_days: int = None):
    """Compute annualised Sharpe from equity CSV daily_pnl column. Spec §5."""
    if not HAS_PANDAS:
        return None
    path = Path(equity_csv_path)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        df = df.sort_values("date")
        returns = df["daily_pnl"] / df["portfolio_value"].shift(1)
        if window_days:
            returns = returns.tail(window_days)
        clean = returns.dropna()
        if len(clean) < 20:
            return None
        std = clean.std()
        if std == 0 or math.isnan(std):
            return None
        return float(clean.mean() / std * math.sqrt(252))
    except Exception:
        return None


# ── Demotion threshold validation ──────────────────────────────────────────────

def validate_demotion_threshold(entry: dict) -> bool:
    """
    Validate demotion_drawdown_threshold == 1.5 × gate1.is_max_drawdown ± 0.001.
    Log warning on mismatch — drift may be intentional CEO override (spec §5).
    """
    ddt = entry.get("demotion_drawdown_threshold", 0)
    is_mdd = entry.get("gate1", {}).get("is_max_drawdown", 0)
    expected = 1.5 * is_mdd
    if abs(ddt - expected) >= 0.001:
        print(
            f"WARNING [{entry.get('strat_id')}]: demotion_drawdown_threshold "
            f"{ddt:.4f} != 1.5 × is_max_drawdown {expected:.4f} "
            f"(diff={abs(ddt - expected):.4f}) — possible CEO override.",
            file=sys.stderr,
        )
        return False
    return True


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_equity_csv(strat_id: str) -> list:
    path = REPO_ROOT / "paper_trading" / strat_id / "equity.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_trades_csv(strat_id: str) -> list:
    path = REPO_ROOT / "paper_trading" / strat_id / "trades.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_meta_json(strat_id: str) -> dict:
    path = REPO_ROOT / "paper_trading" / strat_id / "meta.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


# ── Portfolio drawdown ─────────────────────────────────────────────────────────

def compute_portfolio_drawdown(active_equity: dict) -> float:
    """
    Portfolio drawdown from combined equity curves of active strategies.
    active_equity: {strat_id: [equity_csv_rows]}
    """
    date_values: dict = {}
    for rows in active_equity.values():
        for row in rows:
            date = row.get("date", "")
            try:
                val = float(row.get("portfolio_value", 0) or 0)
            except (ValueError, TypeError):
                val = 0.0
            date_values[date] = date_values.get(date, 0.0) + val

    if not date_values:
        return 0.0

    values = [date_values[d] for d in sorted(date_values)]
    peak = max(values)
    current = values[-1]
    if peak <= 0:
        return 0.0
    return max(0.0, (1.0 - current / peak) * 100.0)


# ── Leaderboard builder ───────────────────────────────────────────────────────

def derive_alert_state(meta: dict, strat: dict, stale: bool) -> str:
    """Returns 'OK', 'WARNING', or 'CRITICAL'."""
    current_dd = float(meta.get("current_drawdown_pct", 0) or 0)
    demotion_pct = float(strat.get("demotion_drawdown_threshold", 1)) * 100
    warning_pct = float(strat.get("warning_drawdown_threshold", 1)) * 100

    if current_dd >= demotion_pct:
        return "CRITICAL"
    if current_dd >= warning_pct or stale:
        return "WARNING"
    return "OK"


def build_leaderboard_row(strat: dict, meta: dict, paper_sharpe, stale: bool) -> dict:
    gate1 = strat.get("gate1", {})
    current_dd = float(meta.get("current_drawdown_pct", 0) or 0)
    demotion_pct = strat.get("demotion_drawdown_threshold", 0) * 100
    warning_pct = strat.get("warning_drawdown_threshold", 0) * 100

    alert = derive_alert_state(meta, strat, stale)

    # Paper vs backtest divergence check (spec §2.4)
    oos_sharpe = gate1.get("oos_sharpe")
    if paper_sharpe is not None and oos_sharpe and paper_sharpe < 0.7 * oos_sharpe:
        if alert == "OK":
            alert = "WARNING"

    return {
        "strat_id": strat["strat_id"],
        "name": strat.get("name", ""),
        "status": strat.get("status", ""),
        "asset_class": strat.get("asset_class", ""),
        "capital_allocated": strat.get("capital_allocated", 0),
        "is_sharpe": gate1.get("is_sharpe"),
        "oos_sharpe": gate1.get("oos_sharpe"),
        "paper_sharpe": paper_sharpe,
        "backtest_mdd_pct": round(gate1.get("is_max_drawdown", 0) * 100, 2),
        "current_drawdown_pct": current_dd,
        "demotion_threshold_pct": round(demotion_pct, 2),
        "warning_threshold_pct": round(warning_pct, 2),
        "alert": alert,
        "last_update": meta.get("last_update"),
        "is_stale": stale,
        "paper_start_date": strat.get("paper_start_date"),
    }


# ── Alerts builder ─────────────────────────────────────────────────────────────

def build_alerts(strategies: list, metas: dict, stales: dict, portfolio_dd: float) -> list:
    alerts = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # Portfolio-level
    if portfolio_dd >= 8.0:
        alerts.append({
            "type": "portfolio_halt",
            "severity": "CRITICAL",
            "strat_id": None,
            "message": f"Portfolio drawdown {portfolio_dd:.2f}% ≥ 8% HALT threshold. All live strategies pause per Rule 9.",
            "timestamp": now_iso,
        })
    elif portfolio_dd >= 6.0:
        alerts.append({
            "type": "portfolio_warn",
            "severity": "WARNING",
            "strat_id": None,
            "message": f"Portfolio drawdown {portfolio_dd:.2f}% ≥ 6% WARN threshold.",
            "timestamp": now_iso,
        })

    # Per-strategy
    for strat in strategies:
        if strat.get("status") not in ("paper", "live"):
            continue
        strat_id = strat["strat_id"]
        meta = metas.get(strat_id, {})
        stale = stales.get(strat_id, False)
        current_dd = float(meta.get("current_drawdown_pct", 0) or 0)
        demotion_pct = strat.get("demotion_drawdown_threshold", 1) * 100
        warning_pct = strat.get("warning_drawdown_threshold", 1) * 100

        if stale:
            alerts.append({
                "type": "strategy_stale",
                "severity": "WARNING",
                "strat_id": strat_id,
                "message": f"Strategy data stale. Last update: {meta.get('last_update', 'unknown')}",
                "timestamp": now_iso,
            })
        if current_dd >= demotion_pct:
            alerts.append({
                "type": "demotion_threshold_hit",
                "severity": "CRITICAL",
                "strat_id": strat_id,
                "message": f"Current drawdown {current_dd:.2f}% ≥ demotion threshold {demotion_pct:.2f}%. Risk Director alerted.",
                "timestamp": now_iso,
            })
        elif current_dd >= warning_pct:
            alerts.append({
                "type": "approaching_demotion",
                "severity": "WARNING",
                "strat_id": strat_id,
                "message": f"Current drawdown {current_dd:.2f}% ≥ warning threshold {warning_pct:.2f}%.",
                "timestamp": now_iso,
            })

    return alerts


# ── Equity chart data ──────────────────────────────────────────────────────────

def build_equity_data(strat_id: str, rows: list) -> dict:
    def _f(row, col):
        try:
            return float(row.get(col) or 0)
        except (ValueError, TypeError):
            return 0.0

    return {
        "strat_id": strat_id,
        "dates": [r.get("date", "") for r in rows],
        "portfolio_values": [_f(r, "portfolio_value") for r in rows],
        "cumulative_return_pct": [_f(r, "cumulative_return_pct") for r in rows],
        "drawdown_pct": [_f(r, "drawdown_pct") for r in rows],
        "daily_pnl": [_f(r, "daily_pnl") for r in rows],
    }


# ── HTML renderer ─────────────────────────────────────────────────────────────

def render_html(portfolio: dict, leaderboard: list, alerts: list) -> str:
    state_color = {
        "OK": "#28a745",
        "WARN": "#ffc107",
        "HALT": "#dc3545",
    }.get(portfolio.get("alert_state", "OK"), "#6c757d")

    lb_rows_html = ""
    for row in leaderboard:
        alert = row.get("alert", "OK")
        row_bg = {
            "CRITICAL": ' style="background:#f8d7da"',
            "WARNING": ' style="background:#fff3cd"',
        }.get(alert, "")
        stale_badge = ' <span style="color:#999;font-size:.8em">[STALE]</span>' if row.get("is_stale") else ""
        ps = row.get("paper_sharpe")
        paper_sharpe_str = f"{ps:.2f}" if ps is not None else "—"
        is_sharpe = row.get("is_sharpe")
        is_sharpe_str = f"{is_sharpe:.2f}" if is_sharpe is not None else "—"
        oos_sharpe = row.get("oos_sharpe")
        oos_sharpe_str = f"{oos_sharpe:.2f}" if oos_sharpe is not None else "—"
        lb_rows_html += f"""
      <tr{row_bg}>
        <td>{row["strat_id"]}{stale_badge}</td>
        <td>{row.get("name","")}</td>
        <td><span class="badge-{row.get("status","")}">{row.get("status","")}</span></td>
        <td>{row.get("asset_class","")}</td>
        <td>${row.get("capital_allocated",0):,.0f}</td>
        <td>{is_sharpe_str}</td>
        <td>{oos_sharpe_str}</td>
        <td>{paper_sharpe_str}</td>
        <td>{row.get("backtest_mdd_pct",0):.1f}%</td>
        <td>{row.get("current_drawdown_pct",0):.2f}%</td>
        <td>{row.get("demotion_threshold_pct",0):.1f}%</td>
        <td class="alert-{alert}">{alert}</td>
        <td style="font-size:.8em">{row.get("last_update","—")}</td>
      </tr>"""

    alert_rows_html = ""
    for a in alerts:
        sev = a.get("severity", "INFO")
        sev_color = {"CRITICAL": "#dc3545", "WARNING": "#856404", "INFO": "#0c5460"}.get(sev, "#6c757d")
        alert_rows_html += f"""
      <tr>
        <td style="color:{sev_color};font-weight:700">{sev}</td>
        <td>{a.get("strat_id") or "Portfolio"}</td>
        <td>{a.get("message","")}</td>
        <td style="font-size:.8em">{a.get("timestamp","")}</td>
      </tr>"""
    if not alert_rows_html:
        alert_rows_html = '<tr><td colspan="4" style="text-align:center;color:#28a745;padding:12px">✓ No active alerts</td></tr>'

    total = portfolio.get("total_capital", 0)
    deployed = portfolio.get("deployed_capital", 0)
    cash = portfolio.get("cash_buffer", 0)
    dep_pct = portfolio.get("deployed_pct", 0)
    cash_pct = portfolio.get("cash_pct", 0)
    port_dd = portfolio.get("portfolio_drawdown_pct", 0)
    dd_color = "#dc3545" if port_dd >= 8 else "#ffc107" if port_dd >= 6 else "#28a745"
    as_of = portfolio.get("as_of_utc", "")
    active_count = portfolio.get("active_strategy_count", 0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quant Zero Dashboard</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f0f2f5;color:#1a1a2e}}
.topbar{{background:#1a1a2e;color:#fff;padding:12px 28px;display:flex;justify-content:space-between;align-items:center}}
.topbar h1{{font-size:1.3em;font-weight:700;letter-spacing:.5px}}
.as-of{{font-size:.8em;color:#aaa}}
.container{{max-width:1500px;margin:0 auto;padding:18px 24px}}
.summary{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:18px}}
.card{{background:#fff;border-radius:8px;padding:14px 16px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.card .lbl{{font-size:.7em;color:#6c757d;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}}
.card .val{{font-size:1.35em;font-weight:700}}
.section{{background:#fff;border-radius:8px;padding:18px 20px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.section h2{{font-size:1em;color:#495057;border-bottom:1px solid #dee2e6;padding-bottom:8px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:.86em}}
th{{background:#f8f9fa;padding:8px 10px;text-align:left;font-weight:600;border-bottom:2px solid #dee2e6;white-space:nowrap}}
td{{padding:7px 10px;border-bottom:1px solid #f0f0f0}}
tr:hover td{{background:#fafafa}}
.badge-paper{{background:#cce5ff;color:#004085;padding:2px 8px;border-radius:10px;font-size:.8em;font-weight:600}}
.badge-live{{background:#d4edda;color:#155724;padding:2px 8px;border-radius:10px;font-size:.8em;font-weight:600}}
.badge-retired{{background:#e2e3e5;color:#383d41;padding:2px 8px;border-radius:10px;font-size:.8em;font-weight:600}}
.alert-OK{{color:#28a745;font-weight:700}}
.alert-WARNING{{color:#856404;font-weight:700}}
.alert-CRITICAL{{color:#721c24;font-weight:700}}
</style>
</head>
<body>
<div class="topbar">
  <h1>⚡ Quant Zero Dashboard</h1>
  <span class="as-of">As of {as_of}</span>
</div>
<div class="container">
  <div class="summary">
    <div class="card"><div class="lbl">Total Capital</div><div class="val">${total:,.0f}</div></div>
    <div class="card"><div class="lbl">Deployed</div><div class="val">${deployed:,.0f} <small style="font-size:.55em;color:#6c757d">({dep_pct:.0f}%)</small></div></div>
    <div class="card"><div class="lbl">Cash Buffer</div><div class="val">${cash:,.0f} <small style="font-size:.55em;color:#6c757d">({cash_pct:.0f}%)</small></div></div>
    <div class="card"><div class="lbl">Portfolio Drawdown</div><div class="val" style="color:{dd_color}">{port_dd:.2f}%</div></div>
    <div class="card"><div class="lbl">Alert State</div><div class="val" style="color:{state_color}">{portfolio.get("alert_state","OK")}</div></div>
    <div class="card"><div class="lbl">Active Strategies</div><div class="val">{active_count}</div></div>
  </div>

  <div class="section">
    <h2>Strategy Leaderboard</h2>
    <table>
      <thead>
        <tr>
          <th>Strategy ID</th><th>Name</th><th>Status</th><th>Asset Class</th>
          <th>Capital</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>Paper Sharpe</th>
          <th>Backtest MDD</th><th>Current DD</th><th>Demotion Threshold</th>
          <th>Alert</th><th>Last Update</th>
        </tr>
      </thead>
      <tbody>{lb_rows_html}
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>Active Alerts</h2>
    <table>
      <thead><tr><th>Severity</th><th>Strategy</th><th>Message</th><th>Timestamp</th></tr></thead>
      <tbody>{alert_rows_html}
      </tbody>
    </table>
  </div>
</div>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main(output_dir: str = "docs/dashboard") -> int:
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()

    out = REPO_ROOT / output_dir
    data = out / "data"
    equity_out = data / "equity"
    out.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    equity_out.mkdir(parents=True, exist_ok=True)

    print(f"build_dashboard.py — {now_iso}")

    # Load registry
    registry_path = REPO_ROOT / "promoted" / "registry.json"
    if not registry_path.exists():
        print(f"ERROR: promoted/registry.json not found", file=sys.stderr)
        return 1

    with open(registry_path) as f:
        registry = json.load(f)

    strategies = registry.get("strategies", [])
    portfolio_cfg = registry.get("portfolio", {})

    # Validate demotion thresholds
    for s in strategies:
        validate_demotion_threshold(s)

    active_strategies = [s for s in strategies if s.get("status") in ("paper", "live")]

    # Per-strategy data collection
    all_equity: dict = {}
    metas: dict = {}
    stales: dict = {}
    leaderboard: list = []
    all_trades: list = []

    for strat in strategies:
        sid = strat["strat_id"]
        asset_class = strat.get("asset_class", "equities")

        equity_rows = load_equity_csv(sid)
        meta = load_meta_json(sid)
        trades = load_trades_csv(sid)

        all_equity[sid] = equity_rows
        metas[sid] = meta

        stale = is_stale(meta, asset_class, now_utc)
        stales[sid] = stale

        # Equity chart JSON (active strategies only)
        if strat.get("status") in ("paper", "live"):
            eq_data = build_equity_data(sid, equity_rows)
            with open(equity_out / f"{sid}.json", "w") as f:
                json.dump(eq_data, f, indent=2)
            print(f"  equity/{sid}.json")

        # Compute Sharpe from equity CSV
        eq_path = str(REPO_ROOT / "paper_trading" / sid / "equity.csv")
        paper_sharpe = rolling_sharpe(eq_path)

        # Accumulate trade feed
        for t in trades:
            all_trades.append({**t, "strategy": sid})

        # Leaderboard row
        lb_row = build_leaderboard_row(strat, meta, paper_sharpe, stale)
        leaderboard.append(lb_row)

    # Sort leaderboard: active before retired; within active: CRITICAL→WARNING→OK, then paper Sharpe DESC
    _severity = {"CRITICAL": 0, "WARNING": 1, "OK": 2}
    _status = {"paper": 0, "live": 0, "retired": 1}

    leaderboard.sort(key=lambda r: (
        _status.get(r.get("status", "retired"), 1),
        _severity.get(r.get("alert", "OK"), 2),
        -(r.get("paper_sharpe") or 0),
    ))

    # Portfolio summary
    total_capital = portfolio_cfg.get("total_capital", 0)
    deployed = sum(s.get("capital_allocated", 0) for s in active_strategies)
    cash = total_capital - deployed
    dep_pct = round(deployed / total_capital * 100, 1) if total_capital else 0
    cash_pct = round(cash / total_capital * 100, 1) if total_capital else 0

    active_equity = {sid: all_equity[sid] for sid in (s["strat_id"] for s in active_strategies)}
    portfolio_dd = compute_portfolio_drawdown(active_equity)

    dd_warn_pct = portfolio_cfg.get("portfolio_drawdown_warn", 0.06) * 100
    dd_pause_pct = portfolio_cfg.get("portfolio_drawdown_pause", 0.08) * 100
    if portfolio_dd >= dd_pause_pct:
        port_alert = "HALT"
    elif portfolio_dd >= dd_warn_pct:
        port_alert = "WARN"
    else:
        port_alert = "OK"

    last_updates = [
        metas.get(s["strat_id"], {}).get("last_update", "")
        for s in active_strategies
        if metas.get(s["strat_id"], {}).get("last_update")
    ]
    as_of = max(last_updates) if last_updates else now_iso

    portfolio = {
        "schema_version": "1.0",
        "total_capital": total_capital,
        "deployed_capital": deployed,
        "cash_buffer": cash,
        "deployed_pct": dep_pct,
        "cash_pct": cash_pct,
        "portfolio_drawdown_pct": round(portfolio_dd, 3),
        "alert_state": port_alert,
        "as_of_utc": as_of,
        "active_strategy_count": len(active_strategies),
    }

    # Build alerts
    alerts = build_alerts(strategies, metas, stales, portfolio_dd)

    # Trade feed: last 50 sorted DESC by timestamp
    trade_feed = sorted(all_trades, key=lambda t: t.get("timestamp", ""), reverse=True)[:50]

    # Write output files
    with open(data / "portfolio.json", "w") as f:
        json.dump(portfolio, f, indent=2)
    print("  data/portfolio.json")

    with open(data / "leaderboard.json", "w") as f:
        json.dump(leaderboard, f, indent=2)
    print("  data/leaderboard.json")

    with open(data / "alerts.json", "w") as f:
        json.dump(alerts, f, indent=2)
    print("  data/alerts.json")

    html = render_html(portfolio, leaderboard, alerts)
    with open(out / "index.html", "w") as f:
        f.write(html)
    print("  index.html")

    print(
        f"\nDone. Capital: ${total_capital:,.0f} | Deployed: ${deployed:,.0f} ({dep_pct:.0f}%) "
        f"| Portfolio DD: {portfolio_dd:.2f}% | Alert: {port_alert}"
    )
    if alerts:
        print(f"Active alerts: {len(alerts)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Quant Zero dashboard from canonical data files")
    parser.add_argument(
        "--output-dir",
        default="docs/dashboard",
        help="Output directory relative to repo root (default: docs/dashboard)",
    )
    args = parser.parse_args()
    sys.exit(main(args.output_dir))
