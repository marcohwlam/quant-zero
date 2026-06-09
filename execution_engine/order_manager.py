"""
OrderManager: idempotent order submission and startup reconciliation.

Idempotency: every order carries a deterministic client_order_id derived from
(strategy_id, symbol, bar_date, side). On restart, pending orders are checked
against the broker; duplicate submissions are suppressed.

Startup reconciliation: fetches open orders and positions from Alpaca (source of
truth) and syncs the local store — no double-submit, no position drift.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# yfinance → Alpaca symbol for position lookup
_ALPACA_SYM = {
    "BTC-USD": "BTCUSD",
    "ETH-USD": "ETHUSD",
    "SOL-USD": "SOLUSD",
    "AVAX-USD": "AVAXUSD",
    "DOGE-USD": "DOGEUSD",
}


def to_alpaca_symbol(symbol: str) -> str:
    return _ALPACA_SYM.get(symbol, symbol)


def _make_client_order_id(strategy_id: str, symbol: str, bar_date: str, side: str) -> str:
    """
    Deterministic client_order_id, max 48 chars (Alpaca limit).
    Format: {strat12}_{sym8}_{date8}_{side4}
    """
    strat = strategy_id[:12].replace("_", "")
    sym = to_alpaca_symbol(symbol)[:8]
    date = bar_date[:10].replace("-", "")
    oid = f"{strat}_{sym}_{date}_{side[:4]}"
    return oid[:48]


class OrderManager:
    def __init__(self, alpaca_client, store) -> None:
        self._client = alpaca_client
        self._store = store

    def startup_reconcile(self) -> dict:
        """
        Reconcile broker state with local store on startup.

        1. For each locally-pending order, check its status at the broker.
        2. Fetch current positions as source of truth for engine state.

        Returns:
            {alpaca_symbol: {"qty": float, "market_value": float, "current_price": float}}
        """
        logger.info("Startup reconciliation: syncing broker state...")

        pending_orders = self._store.get_pending_orders()
        if pending_orders:
            try:
                open_at_broker = {
                    o.get("client_order_id"): o
                    for o in self._client.get_open_orders()
                    if o.get("client_order_id")
                }
            except Exception as exc:
                logger.warning("Could not fetch open orders from broker: %s", exc)
                open_at_broker = {}

            for local in pending_orders:
                coid = local["client_order_id"]
                if coid in open_at_broker:
                    self._store.update_order(coid, {"status": "submitted"})
                    logger.info("Reconcile: %s still open at broker", coid)
                    continue
                try:
                    broker = self._client.get_order(coid)
                    status = broker.get("status", "unknown")
                    updates = {"status": status}
                    if status == "filled":
                        updates["fill_price"] = float(broker.get("filled_avg_price") or 0)
                        updates["fill_qty"] = float(broker.get("filled_qty") or 0)
                        updates["filled_at"] = broker.get("filled_at")
                    self._store.update_order(coid, updates)
                    logger.info("Reconcile: %s → status=%s", coid, status)
                except Exception as exc:
                    logger.warning("Reconcile lookup failed for %s: %s", coid, exc)

        # Fetch current positions (source of truth)
        positions = {}
        try:
            for pos in self._client.get_positions():
                sym = pos.get("symbol", "")
                positions[sym] = {
                    "qty": float(pos.get("qty", 0)),
                    "market_value": float(pos.get("market_value", 0)),
                    "current_price": float(pos.get("current_price", 0)),
                }
        except Exception as exc:
            logger.warning("Could not fetch positions from broker: %s", exc)

        logger.info("Startup reconciliation complete. Positions: %s", list(positions.keys()))
        return positions

    def submit_target(
        self,
        strategy_id: str,
        symbol: str,
        target_notional: float,
        current_qty: float,
        current_price: float,
        bar_ts: str,
    ) -> Optional[dict]:
        """
        Submit an order to move from current_qty toward target_notional.

        Idempotent: an existing non-rejected order for the same
        (strategy_id, symbol, bar_date, side) is not resubmitted.

        Args:
            target_notional: desired dollar exposure (0 = flat)
            current_qty: current position quantity (shares / coins)
            current_price: current market price for notional estimation
            bar_ts: ISO8601 timestamp of bar triggering this order

        Returns:
            order dict or None if no action needed
        """
        current_notional = current_qty * current_price
        diff = target_notional - current_notional

        # Dead-band: skip tiny adjustments (< 2% of target or < $10)
        threshold = max(abs(target_notional) * 0.02, 10.0)
        if abs(diff) < threshold:
            logger.debug(
                "Skip order %s: diff $%.2f below threshold $%.2f",
                symbol, diff, threshold,
            )
            return None

        # Special case: closing to flat — use close_position for precision
        if target_notional == 0.0 and current_qty != 0.0:
            return self._close_position(strategy_id, symbol, current_qty, bar_ts)

        side = "buy" if diff > 0 else "sell"
        abs_notional = abs(diff)
        bar_date = bar_ts[:10]
        coid = _make_client_order_id(strategy_id, symbol, bar_date, side)

        existing = self._store.get_order(coid)
        if existing and existing["status"] not in ("rejected", "canceled"):
            logger.info("Idempotent skip: %s already %s", coid, existing["status"])
            return existing

        record = {
            "client_order_id": coid,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "notional": round(abs_notional, 2),
            "order_type": "market",
            "status": "pending",
            "bar_ts": bar_ts,
            "submitted_at": datetime.utcnow().isoformat(),
        }
        self._store.save_order(record)

        try:
            from execution_engine.bar_feed import is_crypto
            tif = "gtc" if is_crypto(symbol) else "day"

            resp = self._client.submit_order(
                symbol=symbol,
                qty=None,
                notional=round(abs_notional, 2),
                side=side,
                order_type="market",
                time_in_force=tif,
                limit_price=None,
                client_order_id=coid,
            )
            broker_id = resp.get("id")
            self._store.update_order(coid, {
                "broker_order_id": broker_id,
                "status": "submitted",
                "raw_response": str(resp),
            })
            logger.info(
                "Order submitted: %s %s %s $%.2f  broker_id=%s",
                coid, side, symbol, abs_notional, broker_id,
            )
            return {**record, "broker_order_id": broker_id, "status": "submitted"}

        except Exception as exc:
            logger.error("Order submission failed %s: %s", coid, exc)
            self._store.update_order(coid, {"status": "rejected", "raw_response": str(exc)})
            return None

    def _close_position(
        self,
        strategy_id: str,
        symbol: str,
        current_qty: float,
        bar_ts: str,
    ) -> Optional[dict]:
        """Close an existing position using close_position()."""
        side = "sell" if current_qty > 0 else "buy"
        bar_date = bar_ts[:10]
        coid = _make_client_order_id(strategy_id, symbol, bar_date, f"{side}cl")

        existing = self._store.get_order(coid)
        if existing and existing["status"] not in ("rejected", "canceled"):
            logger.info("Idempotent skip close: %s already %s", coid, existing["status"])
            return existing

        record = {
            "client_order_id": coid,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "qty": abs(current_qty),
            "order_type": "market",
            "status": "pending",
            "bar_ts": bar_ts,
            "submitted_at": datetime.utcnow().isoformat(),
        }
        self._store.save_order(record)

        try:
            resp = self._client.close_position(symbol)
            broker_id = resp.get("id")
            self._store.update_order(coid, {
                "broker_order_id": broker_id,
                "status": "submitted",
            })
            logger.info("Position closed: %s  broker_id=%s", symbol, broker_id)
            return {**record, "broker_order_id": broker_id, "status": "submitted"}
        except Exception as exc:
            logger.error("Close position failed %s: %s", symbol, exc)
            self._store.update_order(coid, {"status": "rejected", "raw_response": str(exc)})
            return None
