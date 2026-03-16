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
from datetime import date, datetime

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
            side = last_trade.get("side", "flat")
            if side == "buy":
                signal_info[ticker] = {"signal": 1, "signal_type": "eql_long"}
            elif side == "sell":
                signal_info[ticker] = {"signal": -1, "signal_type": "eqh_short"}
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

    # 4. Log trades
    append_trade_log(execution_log)

    # 5. IS report
    all_trades = load_trade_log()
    is_report = compute_shortfall_report(all_trades)
    logger.info(f"IS Report: mean={is_report.get('mean_is_bps')} bps, "
                f"n_fills={is_report.get('n_fills')}, "
                f"action_triggered={is_report.get('action_triggered')}")

    if is_report.get("action_triggered"):
        logger.warning(f"ACTION REQUIRED: {is_report.get('action_note')}")

    # 6. Summary
    summary = {
        "date":           datetime.now().strftime("%Y-%m-%d"),
        "strategy":       STRATEGY_NAME,
        "dry_run":        dry_run,
        "signals":        {k: v for k, v in signals.items() if k != "timestamp"},
        "execution":      execution_log,
        "is_report":      is_report,
        "account_value":  float(account.get("portfolio_value", 0)),
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
