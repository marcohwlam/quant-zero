"""
H10 Crypto EQL/EQH Reversal — Paper Trading Runner
Engineering Director | Date: 2026-03-16

Deploys H10 strategy signals to Alpaca crypto paper trading account.
Runs daily (end of day) to evaluate signal and place/exit positions.

CEO-approved: QUA-160 (2026-03-16)
Gate 1 verdict: backtests/H10_CryptoEQLReversal_v2_2026-03-16_verdict.txt
  IS Sharpe: 1.20 | OOS Sharpe: 1.44 | IS MDD: -10.7% | Win Rate: 61.4%

Usage:
    # One-shot signal evaluation and order execution:
    python broker/paper_trading/h10_paper_runner.py

    # Dry-run (print signals, no orders):
    python broker/paper_trading/h10_paper_runner.py --dry-run

    # IS shortfall tracking only (post-paper analysis):
    python broker/paper_trading/h10_paper_runner.py --shortfall-report

Required env vars:
    ALPACA_API_KEY
    ALPACA_API_SECRET
    ALPACA_BASE_URL (defaults to paper endpoint)

Risk constraints (per Risk Constitution + CEO approval):
    - Max leverage: 2x crypto (enforced via position sizing)
    - Max single position: 10% of portfolio value
    - BTC + ETH combined: max 20% of portfolio value
    - No manual stop-loss overrides — signal-driven exits only
"""

import os
import sys
import json
import logging
import argparse
import warnings
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from broker.alpaca_client import AlpacaClient
from strategies.h10_crypto_eql_reversal import run_strategy as run_backtest, PARAMETERS

# ── Constants ──────────────────────────────────────────────────────────────────

STRATEGY_NAME    = "H10_CryptoEQLReversal_v2"
UNIVERSE         = ["BTC-USD", "ETH-USD"]
MAX_POSITION_PCT = 0.10   # max 10% of portfolio per position
MAX_CRYPTO_PCT   = 0.20   # max 20% combined BTC+ETH exposure
CAPITAL_SPLIT    = {"BTC-USD": 0.60, "ETH-USD": 0.40}  # per strategy spec
TRADE_LOG_PATH   = "broker/paper_trading/h10_trade_log.json"

# Canonical data paths (spec §4.2)
STRAT_ID         = "h10_crypto_eql_reversal_v2"
CANONICAL_DIR    = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "paper_trading", STRAT_ID,
)
INITIAL_CAPITAL  = 5000.0
PAPER_START_DATE = "2026-03-16"
RUNNER_VERSION   = "1.1.0"
DEMOTION_THRESHOLD_PCT = 16.05   # 1.5 × 10.7%
WARNING_THRESHOLD_PCT  = 10.70

# IS tracking: implementation shortfall
IS_THRESHOLD_BPS = 10.0   # flag trades where IS > 10 bps
IS_WARN_BPS      = 5.0    # weekly mean IS > 5 bps triggers cost model review


# ── Signal Evaluation ──────────────────────────────────────────────────────────

def get_current_signal(lookback_days: int = 60) -> dict:
    """
    Evaluate H10 signal on the most recent data.

    Runs a short backtest over the trailing lookback_days to determine
    current position for each crypto asset.

    Returns:
        {
            "BTC-USD": {"signal": 1 or 0 or -1, "signal_type": "eql_long" | "eqh_short" | "flat"},
            "ETH-USD": {"signal": 1 or 0 or -1, ...},
            "timestamp": "YYYY-MM-DD HH:MM:SS",
        }
    """
    today = date.today().strftime("%Y-%m-%d")
    start = (pd.Timestamp(today) - pd.DateOffset(days=lookback_days)).strftime("%Y-%m-%d")

    try:
        result = run_backtest(params=PARAMETERS, start=start, end=today)
        signal_info = {}

        for ticker in UNIVERSE:
            # The last signal in the trade log for this ticker indicates current intent
            trades = result.get("trade_log", [])
            ticker_trades = [t for t in trades if t.get("ticker") == ticker]

            if not ticker_trades:
                signal_info[ticker] = {"signal": 0, "signal_type": "flat"}
                continue

            last_trade = ticker_trades[-1]
            # Only carry a long/short signal if the last trade was force-closed at
            # end-of-data (position still open). Normal exits (stop_loss, take_profit,
            # time_stop) mean the strategy is flat — don't re-enter automatically.
            if last_trade.get("exit_reason") == "end_of_data":
                direction = last_trade.get("direction", "flat")
                if direction == "long":
                    signal_info[ticker] = {"signal": 1, "signal_type": "eql_long"}
                elif direction == "short":
                    signal_info[ticker] = {"signal": -1, "signal_type": "eqh_short"}
                else:
                    signal_info[ticker] = {"signal": 0, "signal_type": "flat"}
            else:
                signal_info[ticker] = {"signal": 0, "signal_type": "flat"}

        signal_info["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        signal_info["backtest_sharpe"] = round(result.get("sharpe", 0), 4)
        signal_info["backtest_trade_count"] = result.get("trade_count", 0)
        return signal_info

    except Exception as exc:
        logger.error(f"Signal evaluation failed: {exc}")
        return {
            ticker: {"signal": 0, "signal_type": "flat"} for ticker in UNIVERSE
        } | {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": str(exc)}


# ── Position Sizing ────────────────────────────────────────────────────────────

def compute_target_notional(
    client: AlpacaClient,
    ticker: str,
    signal: int,
) -> float:
    """
    Compute target notional value for the trade given signal and risk constraints.

    Risk constraints:
    - Max single position: 10% of portfolio value
    - Max BTC+ETH combined: 20% of portfolio value (enforced at portfolio level)
    - Signal = 1 (long) → allocate capital_split × max_position
    - Signal = -1 (short) → same sizing (short not approved per Research Director; should be 0)
    - Signal = 0 → target 0 (close position)

    Returns:
        target notional in USD (positive = long, 0 = close)
    """
    if signal == -1:
        logger.warning(
            f"Short signal received for {ticker} — SHORT NOT APPROVED for paper trading. "
            "Treating as flat (signal=0). Only EQL long entries are permitted."
        )
        return 0.0

    portfolio_value = client.get_portfolio_value()
    if portfolio_value <= 0:
        logger.error("Invalid portfolio value from Alpaca. Skipping sizing.")
        return 0.0

    # Capital allocation per risk constraints
    split = CAPITAL_SPLIT.get(ticker, 0.5)
    max_single = portfolio_value * MAX_POSITION_PCT
    allocated = portfolio_value * MAX_CRYPTO_PCT * split  # e.g., 20% × 60% = 12%

    # Cap at per-position maximum
    target = min(allocated, max_single)

    if signal == 0:
        return 0.0

    logger.info(
        f"Position sizing {ticker}: portfolio=${portfolio_value:.0f}, "
        f"target=${target:.0f} ({target/portfolio_value*100:.1f}%)"
    )
    return round(target, 2)


# ── Execution ─────────────────────────────────────────────────────────────────

def execute_signals(
    client: AlpacaClient,
    signals: dict,
    dry_run: bool = False,
) -> list:
    """
    Execute target positions based on signals.

    For each ticker:
    1. Compare target signal vs. current position
    2. If target=long and not in position → buy (notional order)
    3. If target=flat and in position → close position
    4. If already at target → no action

    Tracks implementation shortfall for each fill.

    Returns:
        list of execution records (for trade log + IS tracking)
    """
    execution_log = []

    for ticker in UNIVERSE:
        sig_info = signals.get(ticker, {"signal": 0})
        signal = sig_info.get("signal", 0)
        signal_type = sig_info.get("signal_type", "flat")

        current_position = client.get_position(ticker)
        has_position = current_position is not None and float(current_position.get("qty", 0)) != 0

        target_notional = compute_target_notional(client, ticker, signal)

        alpaca_sym = ticker.replace("-", "")
        entry_record = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": ticker,
            "signal": signal,
            "signal_type": signal_type,
            "target_notional": target_notional,
            "has_position": has_position,
            "action": None,
            "order_id": None,
            "fill_qty": None,
            "fill_price": None,
            "entry_backtest_price": None,
            "entry_paper_price": None,
            "entry_is_bps": None,
            "dry_run": dry_run,
        }

        if signal > 0 and not has_position:
            # BUY: enter long position
            entry_record["action"] = "buy"
            logger.info(f"Signal: LONG {ticker} (notional=${target_notional:.0f})")

            if not dry_run:
                try:
                    order = client.submit_order(
                        symbol=ticker,
                        notional=target_notional,
                        side="buy",
                        order_type="market",
                        time_in_force="gtc",
                        client_order_id=f"h10_{alpaca_sym}_{date.today().strftime('%Y%m%d')}",
                    )
                    filled = client.wait_for_fill(order["id"])
                    fill_price = float(filled.get("filled_avg_price") or 0)
                    fill_qty = float(filled.get("filled_qty") or 0)

                    entry_record["order_id"]    = order["id"]
                    entry_record["fill_qty"]    = fill_qty
                    entry_record["fill_price"]  = fill_price
                    entry_record["entry_paper_price"] = fill_price
                    logger.info(f"  FILLED: {fill_qty:.6f} {ticker} @ ${fill_price:.2f}")
                except Exception as exc:
                    logger.error(f"  ORDER FAILED for {ticker}: {exc}")
                    entry_record["error"] = str(exc)

        elif (signal == 0 or signal < 0) and has_position:
            # CLOSE: exit long position
            entry_record["action"] = "close"
            logger.info(f"Signal: CLOSE {ticker} (signal={signal})")

            if not dry_run:
                try:
                    result = client.close_position(ticker)
                    logger.info(f"  Position closed for {ticker}")
                    entry_record["order_id"] = result.get("id")
                except Exception as exc:
                    logger.error(f"  CLOSE FAILED for {ticker}: {exc}")
                    entry_record["error"] = str(exc)

        else:
            # No action required
            entry_record["action"] = "hold" if has_position else "flat"
            logger.info(f"No action: {ticker} signal={signal} has_position={has_position}")

        execution_log.append(entry_record)

    return execution_log


# ── Trade Log ─────────────────────────────────────────────────────────────────

def load_trade_log() -> list:
    """Load existing trade log from disk."""
    if not os.path.exists(TRADE_LOG_PATH):
        return []
    with open(TRADE_LOG_PATH, "r") as f:
        return json.load(f)


def append_trade_log(new_entries: list):
    """Append new execution records to persistent trade log."""
    log = load_trade_log()
    log.extend(new_entries)
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2, default=str)
    logger.info(f"Trade log updated: {len(log)} total entries → {TRADE_LOG_PATH}")


# ── Canonical file writers (spec §4.2) ────────────────────────────────────────

def _canonical_equity_path() -> str:
    return os.path.join(CANONICAL_DIR, "equity.csv")


def _canonical_trades_path() -> str:
    return os.path.join(CANONICAL_DIR, "trades.csv")


def _canonical_meta_path() -> str:
    return os.path.join(CANONICAL_DIR, "meta.json")


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
    """Initialise CSV files with headers if they don't exist."""
    import csv as _csv
    os.makedirs(CANONICAL_DIR, exist_ok=True)
    eq_path = _canonical_equity_path()
    if not os.path.exists(eq_path):
        with open(eq_path, "w", newline="") as f:
            _csv.writer(f).writerow(EQUITY_COLUMNS)
    tr_path = _canonical_trades_path()
    if not os.path.exists(tr_path):
        with open(tr_path, "w", newline="") as f:
            _csv.writer(f).writerow(TRADES_COLUMNS)


def write_canonical_equity(account_value: float, signal_count: int, trade_count: int = 0):
    """Append one equity row for today. Dedup on date — latest wins (spec §4.2.1)."""
    import csv as _csv
    _ensure_canonical_headers()
    eq_path = _canonical_equity_path()
    today = date.today().strftime("%Y-%m-%d")

    # Read existing rows
    rows = []
    try:
        with open(eq_path, newline="") as f:
            rows = list(_csv.DictReader(f))
    except FileNotFoundError:
        pass

    # Compute running state
    if rows:
        prev = rows[-1]
        prev_value = float(prev.get("portfolio_value", INITIAL_CAPITAL) or INITIAL_CAPITAL)
        prev_cum_pnl = float(prev.get("cumulative_pnl", 0) or 0)
        prev_peak = float(prev.get("peak_value", INITIAL_CAPITAL) or INITIAL_CAPITAL)
    else:
        prev_value = INITIAL_CAPITAL
        prev_cum_pnl = 0.0
        prev_peak = INITIAL_CAPITAL

    # H10 is all-crypto, no separate cash/invested tracking without positions API
    portfolio_value = account_value if account_value > 0 else prev_value
    cash = portfolio_value  # conservative: assume flat until position data wired in
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

    # Dedup: remove existing row for today if present, then append
    rows = [r for r in rows if r.get("date") != today]
    rows.append(new_row)

    with open(eq_path, "w", newline="") as f:
        writer = _csv.DictWriter(f, fieldnames=EQUITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Canonical equity.csv updated: {eq_path}")


def write_canonical_trades(execution_log: list):
    """Append fill records to canonical trades.csv. Flat/hold actions are skipped."""
    import csv as _csv
    _ensure_canonical_headers()
    tr_path = _canonical_trades_path()

    fill_actions = {"buy", "sell", "close"}
    new_rows = []
    for rec in execution_log:
        action = (rec.get("action") or "flat").lower()
        if action not in fill_actions:
            continue
        ticker = rec.get("ticker", "")
        qty = rec.get("fill_qty") or 0.0
        price = rec.get("fill_price") or 0.0
        target_notional = rec.get("target_notional") or 0.0
        notional = float(qty) * float(price) if float(qty) * float(price) > 0 else target_notional
        order_id = rec.get("order_id") or ("dry_run" if rec.get("dry_run") else "")
        new_rows.append({
            "timestamp": rec.get("date", ""),
            "ticker": ticker,
            "action": action,
            "qty": qty if qty is not None else 0.0,
            "price": price if price is not None else 0.0,
            "notional": round(float(notional), 4),
            "commission": 0.0,
            "slippage_est": 0.0,
            "signal": rec.get("signal_type", ""),
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
    account_baseline: float = 0.0,
):
    """Overwrite meta.json with current runner state (spec §4.2.3)."""
    _ensure_canonical_headers()
    meta_path = _canonical_meta_path()

    # Read existing meta for running totals
    existing = {}
    try:
        with open(meta_path) as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    portfolio_value = account_value if account_value > 0 else INITIAL_CAPITAL
    # account_baseline persisted across runs so peak/drawdown track strategy P&L, not Alpaca equity
    _stored_baseline = float(existing.get("account_baseline", 0) or 0)
    if account_baseline <= 0:
        account_baseline = _stored_baseline
    prev_peak = float(existing.get("peak_value", INITIAL_CAPITAL) or INITIAL_CAPITAL)
    peak_value = max(prev_peak, portfolio_value)
    cumulative_pnl = portfolio_value - INITIAL_CAPITAL
    cumulative_return_pct = (portfolio_value / INITIAL_CAPITAL - 1) * 100
    current_drawdown_pct = max(0.0, (1 - portfolio_value / peak_value) * 100) if peak_value > 0 else 0.0
    max_dd_ever = max(
        float(existing.get("max_drawdown_since_paper_start_pct", 0) or 0),
        current_drawdown_pct,
    )

    prev_total_trades = int(existing.get("total_trades", 0) or 0)
    fill_actions = {"buy", "sell", "close"}
    new_fills = sum(
        1 for r in execution_log
        if (r.get("action") or "").lower() in fill_actions
        and r.get("fill_qty") is not None
        and float(r.get("fill_qty") or 0) > 0
    )
    total_trades = prev_total_trades + new_fills

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

    last_sig = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signals": {
            t: signals.get(t, {}).get("signal_type", "flat")
            for t in UNIVERSE
        },
    }

    meta = {
        "strat_id": STRAT_ID,
        "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runner_version": RUNNER_VERSION,
        "paper_start_date": PAPER_START_DATE,
        "initial_capital": INITIAL_CAPITAL,
        "account_baseline": round(account_baseline, 2),
        "current_portfolio_value": round(portfolio_value, 2),
        "current_cash": round(portfolio_value, 2),  # conservative: no open positions tracked
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
        "last_signal_evaluation": last_sig,
    }

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info(f"Canonical meta.json updated: {meta_path}")


# ── IS Shortfall Report ────────────────────────────────────────────────────────

def compute_shortfall_report(trade_log: list) -> dict:
    """
    Compute implementation shortfall statistics per Engineering Director standard.

    IS = (paper_fill_price - backtest_assumed_price) / backtest_assumed_price × 10,000

    Positive IS = paper was worse than backtest assumption.

    Returns weekly IS report:
    - mean_is_bps, max_is_bps, fraction_over_10bps
    - action_triggered: True if mean_is_bps > IS_WARN_BPS
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
            "note": "Insufficient data — IS comparison requires backtest_assumed_price field.",
        }

    arr = np.array(is_values)
    mean_is = float(arr.mean())
    max_is = float(arr.max())
    frac_over = float(np.mean(arr > IS_THRESHOLD_BPS))

    return {
        "mean_is_bps":       round(mean_is, 2),
        "max_is_bps":        round(max_is, 2),
        "fraction_over_10bps": round(frac_over, 4),
        "n_fills":           len(arr),
        "action_triggered":  mean_is > IS_WARN_BPS,
        "action_note": (
            f"COST MODEL REVISION REQUIRED: mean IS {mean_is:.1f} bps > {IS_WARN_BPS} bps threshold. "
            "Return strategy to Strategy Coder. Tag: cost-model-revision."
            if mean_is > IS_WARN_BPS else
            f"IS within tolerance ({mean_is:.1f} bps ≤ {IS_WARN_BPS} bps)"
        ),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False, shortfall_report_only: bool = False):
    logger.info("=" * 60)
    logger.info(f"H10 Paper Trading Runner — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Strategy: {STRATEGY_NAME}")
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

    # 2. Evaluate signals
    logger.info("Evaluating H10 signals on recent data...")
    signals = get_current_signal()

    for ticker in UNIVERSE:
        sig = signals.get(ticker, {})
        logger.info(f"  {ticker}: signal={sig.get('signal', 0)} type={sig.get('signal_type', 'N/A')}")

    # 3. Execute
    logger.info(f"Executing signals{'(dry run — no orders)' if dry_run else ''}...")
    execution_log = execute_signals(client, signals, dry_run=dry_run)

    # 4. Log trades (legacy JSON + canonical CSV)
    append_trade_log(execution_log)
    write_canonical_trades(execution_log)

    # 5. IS report
    all_trades = load_trade_log()
    is_report = compute_shortfall_report(all_trades)
    logger.info(f"IS Report: mean={is_report.get('mean_is_bps')} bps, "
                f"n_fills={is_report.get('n_fills')}, "
                f"action_triggered={is_report.get('action_triggered')}")

    if is_report.get("action_triggered"):
        logger.warning(f"ACTION REQUIRED: {is_report.get('action_note')}")

    # 6. Write canonical equity.csv and meta.json
    #
    # Alpaca paper accounts default to $100k, but our strategy capital is INITIAL_CAPITAL.
    # We store the Alpaca balance at paper-start as account_baseline in meta.json, then
    # compute portfolio_value = INITIAL_CAPITAL + (raw_balance - baseline) so that
    # cumulative P&L tracks strategy returns, not the arbitrary Alpaca starting balance.
    raw_account_value = float(account.get("portfolio_value", 0))

    _existing_meta: dict = {}
    try:
        with open(_canonical_meta_path()) as _f:
            _existing_meta = json.load(_f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    account_baseline = float(_existing_meta.get("account_baseline", 0) or 0)
    if account_baseline <= 0 and raw_account_value > 0:
        account_baseline = raw_account_value  # first run: snapshot Alpaca starting balance

    if raw_account_value > 0 and account_baseline > 0:
        account_value = INITIAL_CAPITAL + (raw_account_value - account_baseline)
    else:
        account_value = (
            float(_existing_meta.get("current_portfolio_value", 0) or 0) or INITIAL_CAPITAL
        )

    signal_count = len(UNIVERSE)
    fill_count = sum(
        1 for r in execution_log
        if (r.get("action") or "").lower() in {"buy", "sell", "close"}
        and r.get("fill_qty") is not None and float(r.get("fill_qty") or 0) > 0
    )
    write_canonical_equity(account_value, signal_count, fill_count)
    write_canonical_meta(account_value, signals, execution_log, signal_count,
                         account_baseline=account_baseline)

    # 7. Summary
    summary = {
        "date":                    datetime.now().strftime("%Y-%m-%d"),
        "strategy":                STRATEGY_NAME,
        "dry_run":                 dry_run,
        "signals":                 {k: v for k, v in signals.items() if k != "timestamp"},
        "execution":               execution_log,
        "is_report":               is_report,
        "account_value":           round(account_value, 2),
        "raw_alpaca_balance":      raw_account_value,
        "account_baseline":        account_baseline,
    }
    logger.info("Run complete.")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="H10 Crypto Paper Trading Runner")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Evaluate signals and log but do NOT submit orders"
    )
    parser.add_argument(
        "--shortfall-report", action="store_true",
        help="Print implementation shortfall report from trade log and exit"
    )
    args = parser.parse_args()

    result = main(dry_run=args.dry_run, shortfall_report_only=args.shortfall_report)
    if result and not args.shortfall_report:
        print("\nSummary:")
        print(f"  Account value: ${result.get('account_value', 0):.2f}")
        print(f"  IS report:     {result.get('is_report', {})}")
