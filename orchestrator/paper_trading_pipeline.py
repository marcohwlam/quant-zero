"""
paper_trading_pipeline.py
Unified paper trading signal pipeline for Quant Zero.

Runs all registered paper-trading strategies, executes signals via Alpaca paper broker,
and writes standardized outputs to paper_trading/<strat_id>/.

Output per strategy:
    paper_trading/<strat_id>/equity.csv    — daily equity snapshots (date, portfolio_value)
    paper_trading/<strat_id>/trades.csv    — full trade log in CSV format
    paper_trading/<strat_id>/meta.json     — metadata, signals, last_updated, health

Usage:
    python orchestrator/paper_trading_pipeline.py
    python orchestrator/paper_trading_pipeline.py --dry-run
    python orchestrator/paper_trading_pipeline.py --health-check

Health flags:
    STALE   — last_updated > STALE_HOURS_THRESHOLD business hours ago
    ERROR   — strategy runner threw an exception
    OK      — updated within threshold

Engineering Director standard (AGENTS.md):
    - IS tracking: append entry_is_bps to each trade
    - Mean IS > 5 bps for 2 consecutive weeks → cost-model-revision
    - All output under paper_trading/<strat_id>/ for CEO weekly-trading routine

Scheduled daily at market close via Paperclip routine (see broker/strategy_registry.json).
"""

import os
import sys
import csv
import json
import logging
import argparse
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

PAPER_TRADING_DIR = REPO_ROOT / "paper_trading"
# Prefer promoted/registry.json (canonical) over legacy broker/strategy_registry.json
PROMOTED_REGISTRY_PATH = REPO_ROOT / "promoted" / "registry.json"
REGISTRY_PATH = PROMOTED_REGISTRY_PATH if PROMOTED_REGISTRY_PATH.exists() else REPO_ROOT / "broker" / "strategy_registry.json"

# Flag as stale if not updated in this many hours.
# 80h covers Fri→Mon with market-holiday buffer.
STALE_HOURS_THRESHOLD = 80


# ── Output Writers ─────────────────────────────────────────────────────────────

def _strat_dir(strat_id: str) -> Path:
    d = PAPER_TRADING_DIR / strat_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_prev_meta(strat_id: str) -> dict:
    """Load existing meta.json for a strategy; returns {} on missing or parse error."""
    path = PAPER_TRADING_DIR / strat_id / "meta.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def compute_strategy_equity(
    capital_allocated: float,
    assets: list,
    all_positions: list,
    prev_meta: dict,
) -> dict:
    """
    Compute per-strategy equity from open Alpaca positions.

    strategy_equity = capital_allocated + unrealized_pnl + cumulative_realized_pnl

    unrealized_pnl:          sum of Alpaca unrealized_pl for this strategy's assets.
    cumulative_realized_pnl: carried forward from prev_meta; incremented when a
                             previously open position is no longer present (position
                             closed → P&L became realized cash in the account).

    Position closed detection: compares open_positions_detail stored in prev_meta
    against current positions. When a symbol disappears, its last known unrealized_pl
    is added to cumulative_realized_pnl. Daily cadence means the approximation error
    equals intraday PnL movement from last snapshot to fill time.

    Returns dict with strategy_equity, unrealized_pnl, cumulative_realized_pnl,
    and open_positions_detail (stored in meta.json for next-run detection).
    """
    alpaca_assets = {a.replace("-", "") for a in (assets or [])}
    strat_positions = [p for p in all_positions if p.get("symbol") in alpaca_assets]

    unrealized_pnl = sum(float(p.get("unrealized_pl", 0)) for p in strat_positions)

    # Carry forward cumulative realized PnL and detect newly closed positions
    prev_cum_realized = float(prev_meta.get("cumulative_realized_pnl", 0) or 0)
    prev_detail = {
        d["symbol"]: float(d.get("unrealized_pl", 0))
        for d in (prev_meta.get("open_positions_detail", []) or [])
    }
    current_symbols = {p["symbol"] for p in strat_positions}
    # Positions present last run but absent now were closed; add their last unrealized_pl
    newly_realized = sum(pnl for sym, pnl in prev_detail.items() if sym not in current_symbols)
    cumulative_realized_pnl = round(prev_cum_realized + newly_realized, 4)

    return {
        "strategy_equity": round(capital_allocated + unrealized_pnl + cumulative_realized_pnl, 4),
        "unrealized_pnl": round(unrealized_pnl, 4),
        "cumulative_realized_pnl": cumulative_realized_pnl,
        "open_positions_detail": [
            {"symbol": p["symbol"], "unrealized_pl": float(p.get("unrealized_pl", 0))}
            for p in strat_positions
        ],
    }


def append_equity_row(strat_id: str, portfolio_value: float) -> None:
    """Upsert today's equity snapshot into equity.csv (one row per date)."""
    path = _strat_dir(strat_id) / "equity.csv"
    today_str = date.today().isoformat()

    rows: list[dict] = []
    if path.exists():
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))

    # Replace today's row if present, else append
    rows = [r for r in rows if r.get("date") != today_str]
    rows.append({"date": today_str, "portfolio_value": round(portfolio_value, 4)})

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "portfolio_value"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_trades_csv(strat_id: str, trade_log: list) -> None:
    """Overwrite trades.csv with the full trade log."""
    if not trade_log:
        return
    path = _strat_dir(strat_id) / "trades.csv"
    # Collect all keys preserving order
    seen, cols = set(), []
    for rec in trade_log:
        for k in rec:
            if k not in seen:
                cols.append(k)
                seen.add(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(trade_log)


def write_meta_json(strat_id: str, meta: dict) -> None:
    """Write meta.json for a strategy."""
    path = _strat_dir(strat_id) / "meta.json"
    with open(path, "w") as f:
        json.dump(meta, f, indent=2, default=str)


# ── Health Check ───────────────────────────────────────────────────────────────

def check_health(strat_id: str) -> dict:
    """
    Return health dict for one strategy based on meta.json.

    Returns:
        {"strat_id": ..., "status": "OK"|"STALE"|"MISSING"|"ERROR", "detail": ...}
    """
    meta_path = PAPER_TRADING_DIR / strat_id / "meta.json"
    if not meta_path.exists():
        return {"strat_id": strat_id, "status": "MISSING", "detail": "meta.json not found"}

    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except Exception as exc:
        return {"strat_id": strat_id, "status": "ERROR", "detail": f"meta.json parse error: {exc}"}

    # Accept both "last_updated" (pipeline format) and "last_update" (runner format)
    last_updated_str = meta.get("last_updated") or meta.get("last_update")
    if not last_updated_str:
        return {"strat_id": strat_id, "status": "STALE", "detail": "last_updated missing"}

    try:
        last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
        # Normalize both to naive UTC for comparison
        if last_updated.tzinfo is not None:
            from datetime import timezone
            last_updated = last_updated.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return {"strat_id": strat_id, "status": "STALE", "detail": f"unparseable timestamp: {last_updated_str}"}

    age_hours = (datetime.utcnow() - last_updated).total_seconds() / 3600
    if age_hours > STALE_HOURS_THRESHOLD:
        return {
            "strat_id": strat_id,
            "status": "STALE",
            "detail": f"last_updated {age_hours:.1f}h ago (threshold {STALE_HOURS_THRESHOLD}h)",
            "last_updated": last_updated_str,
        }

    return {
        "strat_id": strat_id,
        "status": "OK",
        "detail": f"updated {age_hours:.1f}h ago",
        "last_updated": last_updated_str,
        "signals": meta.get("signals"),
        "portfolio_value": meta.get("portfolio_value"),
    }


def run_health_check() -> dict:
    """Check health of all registered strategies."""
    registry = _load_registry()
    strategies = registry.get("strategies", [])
    results = {}

    for strat in strategies:
        if strat.get("status") != "paper":
            continue
        strat_id = _strat_id(strat)
        results[strat_id] = check_health(strat_id)

    overall = "OK"
    for r in results.values():
        if r["status"] in ("ERROR", "MISSING", "STALE"):
            overall = r["status"]
            break

    return {"overall": overall, "strategies": results, "checked_at": datetime.now().isoformat()}


# ── Registry ───────────────────────────────────────────────────────────────────

def _load_registry() -> dict:
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def _strat_id(strat: dict) -> str:
    """Return canonical strat_id: use explicit field if present, else derive from name."""
    if "strat_id" in strat:
        return strat["strat_id"]
    return strat["name"].lower().replace(" ", "_").replace("/", "_")


# ── Strategy Runners ───────────────────────────────────────────────────────────

def run_h10(client, dry_run: bool) -> dict:
    """Run H10 Crypto EQL Reversal paper runner and return summary."""
    from broker.paper_trading.h10_paper_runner import (
        get_current_signal, execute_signals, append_trade_log,
        load_trade_log, compute_shortfall_report, STRATEGY_NAME,
    )
    signals = get_current_signal()
    if dry_run:
        exec_log = [
            {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": t,
                "signal": signals.get(t, {}).get("signal", 0),
                "signal_type": signals.get(t, {}).get("signal_type", "flat"),
                "action": "dry_run",
                "dry_run": True,
            }
            for t in ["BTC-USD", "ETH-USD"]
        ]
    else:
        exec_log = execute_signals(client, signals, dry_run=False)
        append_trade_log(exec_log)

    trade_log = load_trade_log()
    is_report = compute_shortfall_report(trade_log)

    return {
        "strategy": STRATEGY_NAME,
        "signals": {k: v for k, v in signals.items() if k not in ("timestamp",)},
        "execution": exec_log,
        "trade_log": trade_log,
        "is_report": is_report,
    }


def run_testmomentum(client, dry_run: bool) -> dict:
    """Run TestMomentum paper runner and return summary."""
    from strategies.test_momentum import get_live_signals, PARAMETERS
    from broker.paper_trading.testmomentum_paper_runner import (
        execute_signals, append_trade_log, load_trade_log,
        compute_shortfall_report, STRATEGY_NAME,
    )

    signals = get_live_signals(params=PARAMETERS)
    if dry_run:
        universe = PARAMETERS["universe"]
        exec_log = [
            {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker": t,
                "signal": 1 if t in signals.get("buy", []) else 0,
                "action": "dry_run",
                "dry_run": True,
            }
            for t in universe
        ]
    else:
        exec_log = execute_signals(client, signals, dry_run=False)
        append_trade_log(exec_log)

    trade_log = load_trade_log()
    is_report = compute_shortfall_report(trade_log)

    return {
        "strategy": STRATEGY_NAME,
        "signals": signals,
        "execution": exec_log,
        "trade_log": trade_log,
        "is_report": is_report,
    }


STRATEGY_RUNNERS = {
    # Canonical strat_ids from promoted/registry.json
    "h10_crypto_eql_reversal_v2": run_h10,
    "bollinger_band_mean_reversion_v1": run_testmomentum,
    # Legacy names from broker/strategy_registry.json (fallback)
    "h10_cryptoeqlreversal_v2": run_h10,
    "testmomentum": run_testmomentum,
}


# ── Main Pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(dry_run: bool = False) -> dict:
    from broker.alpaca_client import AlpacaClient

    logger.info("=" * 60)
    logger.info(f"Paper Trading Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE PAPER'}")
    logger.info("=" * 60)

    # Connect once; all runners share the client
    client = AlpacaClient()
    account = client.get_account()
    total_portfolio_value = float(account.get("portfolio_value", 0))
    logger.info(f"Alpaca connected — portfolio=${total_portfolio_value:,.2f} status={account.get('status')}")

    # Fetch positions once; shared across all strategies for per-strategy equity calc
    try:
        all_positions = client.get_positions()
    except Exception as exc:
        logger.warning(f"Could not fetch positions for equity tracking: {exc}. Per-strategy equity will use capital_allocated only.")
        all_positions = []

    registry = _load_registry()
    results = {}

    for strat in registry.get("strategies", []):
        if strat.get("status") != "paper":
            logger.info(f"Skipping {strat['name']} (status={strat.get('status')})")
            continue

        strat_id = _strat_id(strat)
        runner_fn = STRATEGY_RUNNERS.get(strat_id)

        if runner_fn is None:
            logger.warning(f"No runner registered for strat_id={strat_id}. Skipping.")
            results[strat_id] = {"status": "ERROR", "detail": "no runner registered"}
            continue

        logger.info(f"--- Running {strat['name']} ({strat_id}) ---")
        try:
            # Load previous meta for realized PnL carry-forward before runner modifies it
            prev_meta = _load_prev_meta(strat_id)

            result = runner_fn(client, dry_run=dry_run)

            # Compute per-strategy equity from positions (not total Alpaca account value)
            capital_allocated = float(strat.get("capital_allocated", 0))
            equity_data = compute_strategy_equity(
                capital_allocated=capital_allocated,
                assets=strat.get("assets", []),
                all_positions=all_positions,
                prev_meta=prev_meta,
            )
            strategy_equity = equity_data["strategy_equity"]
            logger.info(
                f"  {strat_id} equity=${strategy_equity:.2f} "
                f"(unrealized_pnl={equity_data['unrealized_pnl']:.2f}, "
                f"realized_pnl={equity_data['cumulative_realized_pnl']:.2f})"
            )

            # Write standardized outputs
            append_equity_row(strat_id, strategy_equity)
            write_trades_csv(strat_id, result.get("trade_log", []))

            meta = {
                "strat_id": strat_id,
                "strategy_name": strat["name"],
                "last_updated": datetime.now().isoformat(),
                "run_date": date.today().isoformat(),
                "dry_run": dry_run,
                "portfolio_value": strategy_equity,
                "strategy_equity": strategy_equity,
                "capital_allocated": capital_allocated,
                "unrealized_pnl": equity_data["unrealized_pnl"],
                "cumulative_realized_pnl": equity_data["cumulative_realized_pnl"],
                "open_positions_detail": equity_data["open_positions_detail"],
                "signals": result.get("signals"),
                "is_report": result.get("is_report"),
                "registry": {
                    "asset_class": strat.get("asset_class"),
                    "capital_allocated": capital_allocated,
                    "gate1_approved": strat.get("gate1_approved"),
                    "start_date": strat.get("start_date"),
                },
            }
            write_meta_json(strat_id, meta)

            results[strat_id] = {"status": "OK", "strategy_equity": strategy_equity, "signals": result.get("signals"), "is_report": result.get("is_report")}
            logger.info(f"  {strat_id} → OK")

        except Exception as exc:
            logger.error(f"  {strat_id} FAILED: {exc}", exc_info=True)
            meta = {
                "strat_id": strat_id,
                "strategy_name": strat["name"],
                "last_updated": datetime.now().isoformat(),
                "run_date": date.today().isoformat(),
                "error": str(exc),
                "status": "ERROR",
            }
            write_meta_json(strat_id, meta)
            results[strat_id] = {"status": "ERROR", "detail": str(exc)}

    summary = {
        "pipeline_run": datetime.now().isoformat(),
        "dry_run": dry_run,
        "total_portfolio_value": total_portfolio_value,
        "strategies": results,
    }

    logger.info("=" * 60)
    logger.info("Pipeline complete.")
    for sid, r in results.items():
        logger.info(f"  {sid}: {r['status']}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Quant Zero Paper Trading Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Signal eval only; no orders submitted")
    parser.add_argument("--health-check", action="store_true", help="Print health status and exit")
    args = parser.parse_args()

    if args.health_check:
        health = run_health_check()
        print(json.dumps(health, indent=2))
        return health

    summary = run_pipeline(dry_run=args.dry_run)
    print("\nPipeline summary:")
    print(f"  total_portfolio_value : ${summary['total_portfolio_value']:,.2f}")
    for sid, r in summary["strategies"].items():
        eq = r.get("strategy_equity")
        eq_str = f"  equity=${eq:,.2f}" if eq is not None else ""
        print(f"  {sid:40s}  {r['status']}{eq_str}")
    return summary


if __name__ == "__main__":
    main()
