"""
TestMomentum v1.0 — Paper Trading Runner
Portfolio Monitor | Date: 2026-05-01

Deploys TestMomentum signals to Alpaca paper trading account (equities).
Runs daily at market close to rebalance top-momentum ETF positions.

CEO approved: QUA-45 (Gate 1 pass, 2026-03-15)
Paper trading start: 2026-03-16 | Capital allocated: $5,000
IS Sharpe: 1.50 | OOS Sharpe: 1.10 | IS Max DD: 12.0% | Win Rate: 55%

Demotion trigger: 18% drawdown from peak | Warning: 12% drawdown

Usage:
    # One-shot signal evaluation and order execution:
    python broker/paper_trading/testmomentum_paper_runner.py

    # Dry-run (print signals, no orders):
    python broker/paper_trading/testmomentum_paper_runner.py --dry-run

    # Shortfall report only:
    python broker/paper_trading/testmomentum_paper_runner.py --shortfall-report

Required env vars:
    ALPACA_API_KEY
    ALPACA_API_SECRET
    ALPACA_BASE_URL (defaults to paper endpoint)

Risk constraints (per Risk Constitution):
    - Max single-strategy exposure: 25% of total portfolio ($5,000 / $25,000)
    - Top_n=2 ETF positions, ~$2,500 notional each
    - Long-only; stop-loss signal-driven (no manual overrides)
    - Market orders with time_in_force=day (equities)
"""

import os
import sys
import json
import logging
import argparse
import warnings
from datetime import date, datetime

import numpy as np

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from broker.alpaca_client import AlpacaClient
from strategies.test_momentum import get_live_signals, PARAMETERS

# ── Constants ──────────────────────────────────────────────────────────────────

STRATEGY_NAME   = "TestMomentum"
UNIVERSE        = PARAMETERS["universe"]
CAPITAL         = 5_000.0           # allocated capital in USD
TOP_N           = PARAMETERS["top_n"]
TRADE_LOG_PATH  = "broker/paper_trading/testmomentum_trade_log.json"

# Canonical data paths (spec §4.2)
STRAT_ID         = "bollinger_band_mean_reversion_v1"
CANONICAL_DIR    = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "paper_trading", STRAT_ID,
)
INITIAL_CAPITAL  = 5000.0
PAPER_START_DATE = "2026-03-16"
RUNNER_VERSION   = "1.1.0"
DEMOTION_THRESHOLD_PCT = 18.00   # 1.5 × 12%
WARNING_THRESHOLD_PCT  = 12.00

IS_THRESHOLD_BPS = 10.0
IS_WARN_BPS      = 5.0


# ── Position Sizing ────────────────────────────────────────────────────────────

def compute_target_notional(ticker: str, in_buy_list: bool) -> float:
    """
    Equal-weight across top_n holdings within strategy capital allocation.
    Each position targets CAPITAL / TOP_N dollars.
    """
    if not in_buy_list:
        return 0.0
    return round(CAPITAL / TOP_N, 2)


# ── Execution ─────────────────────────────────────────────────────────────────

def execute_signals(
    client: AlpacaClient,
    signals: dict,
    dry_run: bool = False,
) -> list:
    """
    Rebalance positions based on momentum signals.

    For each ticker in universe:
    - If in buy list and no current position → open long (notional order)
    - If not in buy list and has position → close position
    - If already at target state → hold / skip

    Returns list of execution records for trade log.
    """
    buy_tickers  = set(signals.get("buy", []))
    execution_log = []

    for ticker in UNIVERSE:
        in_buy = ticker in buy_tickers
        target_notional = compute_target_notional(ticker, in_buy)

        current_position = client.get_position(ticker)
        has_position = current_position is not None and float(current_position.get("qty", 0)) != 0

        entry_record = {
            "date":             datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker":           ticker,
            "signal":           1 if in_buy else 0,
            "signal_type":      "momentum_long" if in_buy else "flat",
            "momentum_score":   signals.get("momentum_scores", {}).get(ticker),
            "target_notional":  target_notional,
            "has_position":     has_position,
            "action":           None,
            "order_id":         None,
            "fill_qty":         None,
            "fill_price":       None,
            "entry_paper_price": None,
            "dry_run":          dry_run,
        }

        if in_buy and not has_position:
            entry_record["action"] = "buy"
            logger.info(f"Signal: LONG {ticker} (notional=${target_notional:.0f})")

            if not dry_run:
                try:
                    order = client.submit_order(
                        symbol=ticker,
                        notional=target_notional,
                        side="buy",
                        order_type="market",
                        time_in_force="day",
                        client_order_id=f"tm_{ticker}_{date.today().strftime('%Y%m%d')}",
                    )
                    filled = client.wait_for_fill(order["id"])
                    fill_price = float(filled.get("filled_avg_price") or 0)
                    fill_qty   = float(filled.get("filled_qty") or 0)

                    entry_record["order_id"]         = order["id"]
                    entry_record["fill_qty"]         = fill_qty
                    entry_record["fill_price"]       = fill_price
                    entry_record["entry_paper_price"] = fill_price
                    logger.info(f"  FILLED: {fill_qty:.4f} {ticker} @ ${fill_price:.2f}")
                except Exception as exc:
                    logger.error(f"  ORDER FAILED for {ticker}: {exc}")
                    entry_record["error"] = str(exc)

        elif not in_buy and has_position:
            entry_record["action"] = "close"
            logger.info(f"Signal: CLOSE {ticker} (not in top-{TOP_N})")

            if not dry_run:
                try:
                    result = client.close_position(ticker)
                    logger.info(f"  Position closed for {ticker}")
                    entry_record["order_id"] = result.get("id")
                except Exception as exc:
                    logger.error(f"  CLOSE FAILED for {ticker}: {exc}")
                    entry_record["error"] = str(exc)

        else:
            entry_record["action"] = "hold" if has_position else "flat"
            logger.info(f"No action: {ticker} in_buy={in_buy} has_position={has_position}")

        execution_log.append(entry_record)

    return execution_log


# ── Trade Log ─────────────────────────────────────────────────────────────────

def load_trade_log() -> list:
    if not os.path.exists(TRADE_LOG_PATH):
        return []
    with open(TRADE_LOG_PATH, "r") as f:
        return json.load(f)


def append_trade_log(new_entries: list):
    log = load_trade_log()
    log.extend(new_entries)
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2, default=str)
    logger.info(f"Trade log updated: {len(log)} total entries → {TRADE_LOG_PATH}")


# ── Canonical file writers (spec §4.2) ────────────────────────────────────────

EQUITY_COLUMNS = [
    "date", "portfolio_value", "cash", "invested", "daily_pnl",
    "cumulative_pnl", "cumulative_return_pct", "drawdown_pct",
    "peak_value", "trade_count_today", "signal_count_today",
]

TRADES_COLUMNS = [
    "timestamp", "ticker", "action", "qty", "price", "notional",
    "commission", "slippage_est", "signal", "order_id", "dry_run",
    "pnl_realized", "position_after",
]


def _ensure_canonical_headers():
    import csv as _csv
    os.makedirs(CANONICAL_DIR, exist_ok=True)
    eq_path = os.path.join(CANONICAL_DIR, "equity.csv")
    if not os.path.exists(eq_path):
        with open(eq_path, "w", newline="") as f:
            _csv.writer(f).writerow(EQUITY_COLUMNS)
    tr_path = os.path.join(CANONICAL_DIR, "trades.csv")
    if not os.path.exists(tr_path):
        with open(tr_path, "w", newline="") as f:
            _csv.writer(f).writerow(TRADES_COLUMNS)


def write_canonical_equity(account_value: float, signal_count: int, trade_count: int = 0):
    """Append one equity row for today. Dedup on date — latest wins (spec §4.2.1)."""
    import csv as _csv
    _ensure_canonical_headers()
    eq_path = os.path.join(CANONICAL_DIR, "equity.csv")
    today = date.today().strftime("%Y-%m-%d")

    rows = []
    try:
        with open(eq_path, newline="") as f:
            rows = list(_csv.DictReader(f))
    except FileNotFoundError:
        pass

    if rows:
        prev = rows[-1]
        prev_value = float(prev.get("portfolio_value", INITIAL_CAPITAL) or INITIAL_CAPITAL)
        prev_cum_pnl = float(prev.get("cumulative_pnl", 0) or 0)
        prev_peak = float(prev.get("peak_value", INITIAL_CAPITAL) or INITIAL_CAPITAL)
    else:
        prev_value = INITIAL_CAPITAL
        prev_cum_pnl = 0.0
        prev_peak = INITIAL_CAPITAL

    portfolio_value = account_value if account_value > 0 else prev_value
    cash = portfolio_value
    invested = 0.0
    daily_pnl = portfolio_value - prev_value
    cumulative_pnl = prev_cum_pnl + daily_pnl
    cumulative_return_pct = (portfolio_value / INITIAL_CAPITAL - 1) * 100
    peak_value = max(prev_peak, portfolio_value)
    drawdown_pct = max(0.0, (1 - portfolio_value / peak_value) * 100) if peak_value > 0 else 0.0

    new_row = {
        "date": today,
        "portfolio_value": round(portfolio_value, 2),
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "daily_pnl": round(daily_pnl, 2),
        "cumulative_pnl": round(cumulative_pnl, 2),
        "cumulative_return_pct": round(cumulative_return_pct, 4),
        "drawdown_pct": round(drawdown_pct, 4),
        "peak_value": round(peak_value, 2),
        "trade_count_today": trade_count,
        "signal_count_today": signal_count,
    }

    rows = [r for r in rows if r.get("date") != today]
    rows.append(new_row)

    with open(eq_path, "w", newline="") as f:
        writer = _csv.DictWriter(f, fieldnames=EQUITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Canonical equity.csv updated: {eq_path}")


def write_canonical_trades(execution_log: list):
    """Append fill/order records to canonical trades.csv. Flat/hold actions skipped."""
    import csv as _csv
    _ensure_canonical_headers()
    tr_path = os.path.join(CANONICAL_DIR, "trades.csv")

    fill_actions = {"buy", "sell", "close"}
    new_rows = []
    for rec in execution_log:
        action = (rec.get("action") or "flat").lower()
        if action not in fill_actions:
            continue
        qty = rec.get("fill_qty") or 0.0
        price = rec.get("fill_price") or 0.0
        target_notional = rec.get("target_notional") or 0.0
        notional = float(qty) * float(price) if float(qty) * float(price) > 0 else target_notional
        order_id = rec.get("order_id") or ("dry_run" if rec.get("dry_run") else "")
        signal_type = rec.get("signal_type", "momentum_long" if rec.get("signal") == 1 else "flat")
        new_rows.append({
            "timestamp": rec.get("date", ""),
            "ticker": rec.get("ticker", ""),
            "action": action,
            "qty": qty if qty is not None else 0.0,
            "price": price if price is not None else 0.0,
            "notional": round(float(notional), 4),
            "commission": 0.0,
            "slippage_est": 0.0,
            "signal": signal_type,
            "order_id": order_id,
            "dry_run": str(rec.get("dry_run", False)).lower(),
            "pnl_realized": 0.0,
            "position_after": 0.0,
        })

    if not new_rows:
        return

    with open(tr_path, "a", newline="") as f:
        writer = _csv.DictWriter(f, fieldnames=TRADES_COLUMNS)
        writer.writerows(new_rows)
    logger.info(f"Canonical trades.csv appended: {len(new_rows)} rows → {tr_path}")


def write_canonical_meta(
    account_value: float,
    signals: dict,
    execution_log: list,
    signal_count: int,
):
    """Overwrite meta.json with current runner state (spec §4.2.3)."""
    from datetime import timezone as _tz
    _ensure_canonical_headers()
    meta_path = os.path.join(CANONICAL_DIR, "meta.json")

    existing = {}
    try:
        import json as _json
        with open(meta_path) as f:
            existing = _json.load(f)
    except (FileNotFoundError, Exception):
        pass

    portfolio_value = account_value if account_value > 0 else INITIAL_CAPITAL
    prev_peak = float(existing.get("peak_value", INITIAL_CAPITAL) or INITIAL_CAPITAL)
    peak_value = max(prev_peak, portfolio_value)
    cumulative_pnl = portfolio_value - INITIAL_CAPITAL
    cumulative_return_pct = (portfolio_value / INITIAL_CAPITAL - 1) * 100
    current_drawdown_pct = max(0.0, (1 - portfolio_value / peak_value) * 100) if peak_value > 0 else 0.0
    max_dd_ever = max(float(existing.get("max_drawdown_since_paper_start_pct", 0) or 0), current_drawdown_pct)

    prev_trades = int(existing.get("total_trades", 0) or 0)
    fill_actions = {"buy", "sell", "close"}
    new_fills = sum(
        1 for r in execution_log
        if (r.get("action") or "").lower() in fill_actions
        and r.get("fill_qty") is not None and float(r.get("fill_qty") or 0) > 0
    )
    total_trades = prev_trades + new_fills

    prev_evals = int(existing.get("total_signal_evaluations", 0) or 0)
    total_evals = prev_evals + signal_count

    paper_start = datetime.strptime(PAPER_START_DATE, "%Y-%m-%d")
    days_in_paper = (datetime.now() - paper_start).days

    if current_drawdown_pct >= DEMOTION_THRESHOLD_PCT:
        status = "demotion_alert"
        alert = f"Drawdown {current_drawdown_pct:.2f}% hit demotion threshold {DEMOTION_THRESHOLD_PCT:.2f}%"
    elif current_drawdown_pct >= WARNING_THRESHOLD_PCT:
        status = "warn"
        alert = f"Drawdown {current_drawdown_pct:.2f}% at warning threshold {WARNING_THRESHOLD_PCT:.2f}%"
    else:
        status = "ok"
        alert = None

    buy_tickers = set(signals.get("buy", []))
    last_sig_signals = {t: ("momentum_long" if t in buy_tickers else "flat") for t in UNIVERSE}

    import json as _json
    meta = {
        "strat_id": STRAT_ID,
        "last_update": datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runner_version": RUNNER_VERSION,
        "paper_start_date": PAPER_START_DATE,
        "initial_capital": INITIAL_CAPITAL,
        "current_portfolio_value": round(portfolio_value, 2),
        "current_cash": round(portfolio_value, 2),
        "current_invested": 0.0,
        "cumulative_pnl": round(cumulative_pnl, 2),
        "cumulative_return_pct": round(cumulative_return_pct, 4),
        "current_drawdown_pct": round(current_drawdown_pct, 4),
        "peak_value": round(peak_value, 2),
        "max_drawdown_since_paper_start_pct": round(max_dd_ever, 4),
        "demotion_threshold_pct": DEMOTION_THRESHOLD_PCT,
        "warning_threshold_pct": WARNING_THRESHOLD_PCT,
        "total_trades": total_trades,
        "total_signal_evaluations": total_evals,
        "days_in_paper": days_in_paper,
        "rolling_sharpe_30d": None,
        "rolling_sharpe_since_start": None,
        "status": status,
        "alert": alert,
        "open_positions": [],
        "last_signal_evaluation": {
            "timestamp": datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "signals": last_sig_signals,
        },
    }

    with open(meta_path, "w") as f:
        _json.dump(meta, f, indent=2)
    logger.info(f"Canonical meta.json updated: {meta_path}")


# ── IS Shortfall Report ────────────────────────────────────────────────────────

def compute_shortfall_report(trade_log: list) -> dict:
    """
    Implementation shortfall: (paper_fill - backtest_assumed) / backtest_assumed × 10,000 bps.
    Equities runner does not yet populate entry_backtest_price; report will note insufficient data.
    """
    is_values = []
    for entry in trade_log:
        bp = entry.get("entry_backtest_price")
        pp = entry.get("entry_paper_price")
        if bp and pp and float(bp) > 0:
            is_bps = (float(pp) - float(bp)) / float(bp) * 10000
            is_values.append(is_bps)

    if not is_values:
        return {
            "mean_is_bps": None,
            "max_is_bps": None,
            "fraction_over_10bps": None,
            "n_fills": 0,
            "action_triggered": False,
            "note": "Insufficient data — IS comparison requires entry_backtest_price field.",
        }

    arr = np.array(is_values)
    mean_is = float(arr.mean())
    max_is  = float(arr.max())
    frac_over = float(np.mean(arr > IS_THRESHOLD_BPS))

    return {
        "mean_is_bps":         round(mean_is, 2),
        "max_is_bps":          round(max_is, 2),
        "fraction_over_10bps": round(frac_over, 4),
        "n_fills":             len(arr),
        "action_triggered":    mean_is > IS_WARN_BPS,
        "action_note": (
            f"COST MODEL REVISION REQUIRED: mean IS {mean_is:.1f} bps > {IS_WARN_BPS} bps threshold."
            if mean_is > IS_WARN_BPS else
            f"IS within tolerance ({mean_is:.1f} bps ≤ {IS_WARN_BPS} bps)"
        ),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False, shortfall_report_only: bool = False):
    # DISABLED: Rule 4 violation — gate1_approved is null. Removed 2026-06-22 per QUA-365/QUA-367.
    logger.error(
        "TestMomentum paper runner DISABLED — Rule 4 violation (gate1_approved=null). "
        "See QUA-365 / QUA-367. Strategy removed from paper trading."
    )
    sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"TestMomentum Paper Trading Runner — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Strategy: {STRATEGY_NAME} v1.0")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE PAPER'}")
    logger.info("=" * 60)

    if shortfall_report_only:
        log = load_trade_log()
        report = compute_shortfall_report(log)
        print("\nImplementation Shortfall Report:")
        for k, v in report.items():
            print(f"  {k}: {v}")
        return report

    # 1. Connect to Alpaca
    logger.info("Connecting to Alpaca paper trading account...")
    client = AlpacaClient()

    account = client.get_account()
    logger.info(
        f"Account: portfolio=${float(account.get('portfolio_value', 0)):.2f}, "
        f"cash=${float(account.get('cash', 0)):.2f}, "
        f"status={account.get('status', 'N/A')}"
    )

    # 2. Evaluate momentum signals
    logger.info("Evaluating TestMomentum signals on recent data...")
    signals = get_live_signals(params=PARAMETERS)

    if "error" in signals:
        logger.error(f"Signal evaluation failed: {signals['error']}")
        return {"error": signals["error"]}

    logger.info(f"  As-of date: {signals.get('date')}")
    logger.info(f"  BUY  : {signals.get('buy', [])}")
    logger.info(f"  SELL : {signals.get('sell', [])}")
    for ticker, score in sorted(
        signals.get("momentum_scores", {}).items(), key=lambda x: -x[1]
    ):
        logger.info(f"    {ticker:6s}  {score:+.2%}")

    # 3. Execute
    logger.info(f"Executing signals{'(dry run — no orders)' if dry_run else ''}...")
    execution_log = execute_signals(client, signals, dry_run=dry_run)

    # 4. Log trades (legacy JSON + canonical CSV)
    append_trade_log(execution_log)
    write_canonical_trades(execution_log)

    # 5. IS report
    all_trades = load_trade_log()
    is_report  = compute_shortfall_report(all_trades)
    logger.info(
        f"IS Report: mean={is_report.get('mean_is_bps')} bps, "
        f"n_fills={is_report.get('n_fills')}, "
        f"action_triggered={is_report.get('action_triggered')}"
    )

    if is_report.get("action_triggered"):
        logger.warning(f"ACTION REQUIRED: {is_report.get('action_note')}")

    # 6. Write canonical equity.csv and meta.json
    account_value = float(account.get("portfolio_value", 0))
    signal_count = len(UNIVERSE)
    fill_count = sum(
        1 for r in execution_log
        if (r.get("action") or "").lower() in {"buy", "sell", "close"}
        and r.get("fill_qty") is not None and float(r.get("fill_qty") or 0) > 0
    )
    write_canonical_equity(account_value, signal_count, fill_count)
    write_canonical_meta(account_value, signals, execution_log, signal_count)

    # 7. Summary
    summary = {
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "strategy":      STRATEGY_NAME,
        "dry_run":       dry_run,
        "signals":       signals,
        "execution":     execution_log,
        "is_report":     is_report,
        "account_value": float(account.get("portfolio_value", 0)),
    }
    logger.info("Run complete.")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TestMomentum v1.0 Paper Trading Runner")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Evaluate signals and log but do NOT submit orders",
    )
    parser.add_argument(
        "--shortfall-report", action="store_true",
        help="Print implementation shortfall report from trade log and exit",
    )
    args = parser.parse_args()

    result = main(dry_run=args.dry_run, shortfall_report_only=args.shortfall_report)
    if result and not args.shortfall_report:
        print("\nSummary:")
        print(f"  Account value: ${result.get('account_value', 0):.2f}")
        print(f"  Signals:       buy={result.get('signals', {}).get('buy', [])}")
        print(f"  IS report:     {result.get('is_report', {})}")
