"""
ExecutionStore: durable SQLite state for orders, bar heartbeats, and equity snapshots.

WAL mode ensures crash-safe writes. Survives restarts: the engine reconciles from
this store + the Alpaca broker on startup to prevent double-submit.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


_DDL = """
CREATE TABLE IF NOT EXISTS orders (
    client_order_id  TEXT PRIMARY KEY,
    broker_order_id  TEXT,
    strategy_id      TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    qty              REAL,
    notional         REAL,
    order_type       TEXT NOT NULL DEFAULT 'market',
    status           TEXT NOT NULL DEFAULT 'pending',
    bar_ts           TEXT,
    submitted_at     TEXT,
    filled_at        TEXT,
    fill_price       REAL,
    fill_qty         REAL,
    raw_response     TEXT
);

CREATE TABLE IF NOT EXISTS bar_heartbeats (
    strategy_id   TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    bar_ts        TEXT NOT NULL,
    processed_at  TEXT NOT NULL,
    PRIMARY KEY (strategy_id, symbol, bar_ts)
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts               TEXT PRIMARY KEY,
    portfolio_value  REAL NOT NULL,
    cash             REAL
);
"""


class ExecutionStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Orders ────────────────────────────────────────────────────────────────

    def save_order(self, order: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO orders
                   (client_order_id, broker_order_id, strategy_id, symbol, side,
                    qty, notional, order_type, status, bar_ts, submitted_at, raw_response)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order["client_order_id"],
                    order.get("broker_order_id"),
                    order["strategy_id"],
                    order["symbol"],
                    order["side"],
                    order.get("qty"),
                    order.get("notional"),
                    order.get("order_type", "market"),
                    order.get("status", "pending"),
                    order.get("bar_ts"),
                    order.get("submitted_at"),
                    json.dumps(order.get("raw_response")) if order.get("raw_response") else None,
                ),
            )

    def update_order(self, client_order_id: str, updates: dict) -> None:
        if not updates:
            return
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [client_order_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE orders SET {cols} WHERE client_order_id = ?", vals)

    def get_order(self, client_order_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_pending_orders(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE status IN ('pending', 'submitted')"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Bar heartbeats ────────────────────────────────────────────────────────

    def record_bar_heartbeat(self, strategy_id: str, symbol: str, bar_ts: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO bar_heartbeats
                   (strategy_id, symbol, bar_ts, processed_at) VALUES (?, ?, ?, ?)""",
                (strategy_id, symbol, bar_ts, datetime.utcnow().isoformat()),
            )

    def get_last_bar_ts(self, strategy_id: str, symbol: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(bar_ts) FROM bar_heartbeats WHERE strategy_id = ? AND symbol = ?",
                (strategy_id, symbol),
            ).fetchone()
        return row[0] if row else None

    def get_last_processed_at(self) -> Optional[str]:
        """Most recent processed_at across all strategies (watchdog uses this)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(processed_at) FROM bar_heartbeats"
            ).fetchone()
        return row[0] if row else None

    # ── Equity snapshots ──────────────────────────────────────────────────────

    def save_equity_snapshot(self, portfolio_value: float, cash: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO equity_snapshots (ts, portfolio_value, cash) VALUES (?, ?, ?)",
                (datetime.utcnow().isoformat(), portfolio_value, cash),
            )

    def get_peak_equity(self) -> float:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(portfolio_value) FROM equity_snapshots"
            ).fetchone()
        return float(row[0]) if row and row[0] else 0.0

    def get_latest_equity(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT ts, portfolio_value, cash FROM equity_snapshots ORDER BY ts DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
