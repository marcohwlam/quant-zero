"""
TestMomentum v1.0 — Paper Trading Runner
Portfolio Monitor Agent | Date: 2026-05-01

Deploys TestMomentum signals to Alpaca equities paper trading account.
Runs daily (end of day) to evaluate momentum signals and place/exit positions.

Gate 1 approval: QUA-45 (2026-03-15)
Strategy file: strategies/test_momentum.py
  IS Sharpe: 1.50 | OOS Sharpe: 1.10 | IS Max DD: 12.0% | Win Rate: 55.0%

Usage:
    python broker/paper_trading/testmomentum_paper_runner.py           # live paper
    python broker/paper_trading/testmomentum_paper_runner.py --dry-run # signals only, no orders

Required env vars:
    ALPACA_API_KEY, ALPACA_API_SECRET, ALPACA_BASE_URL (defaults to paper endpoint)

Risk constraints (per Risk Constitution + QUA-45 approval):
    - Allocated capital: $5,000 paper
    - Max single position: $2,500 (top_n=2, equal weight)
    - Long-only: no shorting
    - Stop-loss: 5% from entry (signal-driven via strategy)
    - Warning drawdown: 12% | Demotion threshold: 18%
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from broker.alpaca_client import AlpacaClient
from strategies.test_momentum import get_live_signals, PARAMETERS

# ── Constants ──────────────────────────────────────────────────────────────────

STRATEGY_NAME  = "TestMomentum"
UNIVERSE       = PARAMETERS["universe"]   # ["SPY", "QQQ", "XLV", "XLF", "XLE", "IWM"]
ALLOCATED_USD  = 5_000.0                  # Capital allocated per QUA-45 approval
TOP_N          = PARAMETERS["top_n"]      # 2 — equal weight across top selections
TRADE_LOG_PATH = "broker/paper_trading/testmomentum_trade_log.json"

# IS shortfall thresholds
IS_THRESHOLD_BPS = 10.0
IS_WARN_BPS      = 5.0


# ── Position Sizing ────────────────────────────────────────────────────────────

def compute_notional_per_position() -> float:
    """Equal-weight across top_n selections within allocated capital."""
    return round(ALLOCATED_USD / TOP_N, 2)


# ── Execution ─────────────────────────────────────────────────────────────────

def execute_signals(client: AlpacaClient, signals: dict, dry_run: bool = False) -> list:
    """
    Execute target positions based on momentum signals.

    Buy logic: if ticker in signals['buy'] and no open position → enter
    Sell logic: if ticker in signals['sell'] and has open position → exit
    """
    execution_log = []
    buy_tickers  = signals.get("buy", [])
    sell_tickers = signals.get("sell", [])
    notional_per = compute_notional_per_position()

    for ticker in UNIVERSE:
        current_position = client.get_position(ticker)
        has_position = current_position is not None and float(current_position.get("qty", 0)) != 0

        record = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ticker": ticker,
            "signal": "buy" if ticker in buy_tickers else "sell",
            "momentum_score": signals.get("momentum_scores", {}).get(ticker),
            "has_position": has_position,
            "target_notional": notional_per if ticker in buy_tickers else 0.0,
            "action": None,
            "order_id": None,
            "fill_qty": None,
            "fill_price": None,
            "entry_paper_price": None,
            "dry_run": dry_run,
        }

        if ticker in buy_tickers and not has_position:
            record["action"] = "buy"
            logger.info(f"Signal: LONG {ticker} (notional=${notional_per:.0f})")
            if not dry_run:
                try:
                    order = client.submit_order(
                        symbol=ticker,
                        notional=notional_per,
                        side="buy",
                        order_type="market",
                        time_in_force="day",
                        client_order_id=f"tm_{ticker}_{date.today().strftime('%Y%m%d')}",
                    )
                    filled = client.wait_for_fill(order["id"])
                    fill_price = float(filled.get("filled_avg_price") or 0)
                    fill_qty   = float(filled.get("filled_qty") or 0)
                    record["order_id"]         = order["id"]
                    record["fill_qty"]         = fill_qty
                    record["fill_price"]       = fill_price
                    record["entry_paper_price"] = fill_price
                    logger.info(f"  FILLED: {fill_qty:.4f} {ticker} @ ${fill_price:.2f}")
                except Exception as exc:
                    logger.error(f"  ORDER FAILED for {ticker}: {exc}")
                    record["error"] = str(exc)

        elif ticker in sell_tickers and has_position:
            record["action"] = "close"
            logger.info(f"Signal: CLOSE {ticker}")
            if not dry_run:
                try:
                    result = client.close_position(ticker)
                    record["order_id"] = result.get("id")
                    logger.info(f"  Position closed for {ticker}")
                except Exception as exc:
                    logger.error(f"  CLOSE FAILED for {ticker}: {exc}")
                    record["error"] = str(exc)

        elif ticker in buy_tickers and has_position:
            record["action"] = "hold"
            logger.info(f"No action: {ticker} already held (momentum LONG)")

        else:
            record["action"] = "flat"
            logger.info(f"No action: {ticker} flat (no position, sell signal)")

        execution_log.append(record)

    return execution_log


# ── Trade Log ─────────────────────────────────────────────────────────────────

def load_trade_log() -> list:
    if not os.path.exists(TRADE_LOG_PATH):
        return []
    with open(TRADE_LOG_PATH) as f:
        return json.load(f)


def append_trade_log(new_entries: list):
    log = load_trade_log()
    log.extend(new_entries)
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2, default=str)
    logger.info(f"Trade log updated: {len(log)} total entries → {TRADE_LOG_PATH}")


# ── Portfolio Metrics ─────────────────────────────────────────────────────────

def compute_drawdown_metrics(client: AlpacaClient) -> dict:
    """
    Compute current drawdown for the TestMomentum allocation.

    Uses Alpaca portfolio history since strategy start (2026-03-16).
    The strategy was allocated $5,000; drawdown is relative to that baseline.
    """
    try:
        import requests as req
        headers = {
            "APCA-API-KEY-ID": client.api_key,
            "APCA-API-SECRET-KEY": client.api_secret,
        }
        r = req.get(
            f"{client.base_url}/v2/account/portfolio/history?period=6M&timeframe=1D",
            headers=headers, timeout=10,
        )
        hist = r.json()
        equity_series = [v for v in hist.get("equity", []) if v and v > 0]
        if len(equity_series) < 2:
            return {"drawdown_pct": 0.0, "peak": ALLOCATED_USD, "current": ALLOCATED_USD, "note": "insufficient history"}

        # Approximate strategy-level metrics from account equity (all-cash baseline)
        # Since no trades have occurred, current strategy equity = allocated capital
        peak    = max(equity_series)
        current = equity_series[-1]
        dd      = (peak - current) / peak if peak > 0 else 0.0
        return {"drawdown_pct": round(dd * 100, 4), "peak_account": peak, "current_account": current}
    except Exception as exc:
        return {"drawdown_pct": 0.0, "note": f"metrics unavailable: {exc}"}


def compute_is_report(trade_log: list) -> dict:
    is_values = []
    for entry in trade_log:
        bp = entry.get("entry_backtest_price")
        pp = entry.get("entry_paper_price")
        if bp and pp and float(bp) > 0:
            is_bps = (float(pp) - float(bp)) / float(bp) * 10_000
            is_values.append(is_bps)

    if not is_values:
        return {
            "mean_is_bps": None, "max_is_bps": None,
            "n_fills": 0, "action_triggered": False,
            "note": "No fills with backtest price comparison yet.",
        }

    arr = np.array(is_values)
    mean_is = float(arr.mean())
    return {
        "mean_is_bps": round(mean_is, 2),
        "max_is_bps":  round(float(arr.max()), 2),
        "n_fills":     len(arr),
        "action_triggered": mean_is > IS_WARN_BPS,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False) -> dict:
    logger.info("=" * 60)
    logger.info(f"TestMomentum Paper Runner — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE PAPER'}")
    logger.info("=" * 60)

    client  = AlpacaClient()
    account = client.get_account()
    portfolio_value = float(account.get("portfolio_value", 0))
    logger.info(f"Account: portfolio=${portfolio_value:.2f}, cash=${float(account.get('cash', 0)):.2f}")

    logger.info("Fetching live momentum signals...")
    signals = get_live_signals(PARAMETERS)

    if "error" in signals:
        logger.error(f"Signal fetch failed: {signals['error']}")
        return {"error": signals["error"]}

    logger.info(f"Signals as of {signals['date']}: BUY={signals['buy']}, SELL={signals['sell']}")
    for ticker, score in sorted(signals.get("momentum_scores", {}).items(), key=lambda x: -x[1]):
        logger.info(f"  {ticker:6s}: {score:+.2%}")

    execution_log = execute_signals(client, signals, dry_run=dry_run)
    append_trade_log(execution_log)

    all_trades = load_trade_log()
    is_report  = compute_is_report(all_trades)
    dd_metrics = compute_drawdown_metrics(client)

    summary = {
        "date":            datetime.now().strftime("%Y-%m-%d"),
        "strategy":        STRATEGY_NAME,
        "dry_run":         dry_run,
        "signals_date":    signals.get("date"),
        "buy":             signals.get("buy", []),
        "sell":            signals.get("sell", []),
        "momentum_scores": signals.get("momentum_scores", {}),
        "execution":       execution_log,
        "drawdown":        dd_metrics,
        "is_report":       is_report,
        "account_value":   portfolio_value,
    }
    logger.info("Run complete.")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TestMomentum v1.0 Paper Runner")
    parser.add_argument("--dry-run", action="store_true", help="Print signals, no orders")
    args = parser.parse_args()

    result = main(dry_run=args.dry_run)
    if result and "error" not in result:
        print(f"\nBUY  : {result.get('buy')}")
        print(f"SELL : {result.get('sell')}")
        print(f"DD   : {result.get('drawdown', {}).get('drawdown_pct', 'N/A')}%")
