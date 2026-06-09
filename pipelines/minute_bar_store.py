"""
SQLite-backed 1-minute OHLCV bar store.
"""

import os
import sqlite3
from typing import Optional

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "minute_bars.db")

_DDL = """
CREATE TABLE IF NOT EXISTS minute_bars (
    symbol  TEXT NOT NULL,
    ts      TEXT NOT NULL,
    open    REAL NOT NULL,
    high    REAL NOT NULL,
    low     REAL NOT NULL,
    close   REAL NOT NULL,
    volume  REAL NOT NULL,
    PRIMARY KEY (symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_symbol_ts ON minute_bars (symbol, ts);
"""


class MinuteBarStore:
    """SQLite store for 1-minute OHLCV bars."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def upsert_bars(self, symbol: str, bars: list[dict]) -> int:
        """
        Insert or replace bars for a symbol.

        bars: list of dicts with keys ts, open, high, low, close, volume.
        Returns count of rows inserted/replaced.
        """
        if not bars:
            return 0
        rows = [
            (symbol, b["ts"], b["open"], b["high"], b["low"], b["close"], b["volume"])
            for b in bars
        ]
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO minute_bars (symbol, ts, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def get_bars(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """
        Fetch bars for symbol between start and end (ISO8601 UTC strings, inclusive).

        Returns DataFrame with columns [open, high, low, close, volume], ts as DatetimeIndex (UTC).
        """
        query = (
            "SELECT ts, open, high, low, close, volume FROM minute_bars "
            "WHERE symbol = ? AND ts >= ? AND ts <= ? ORDER BY ts"
        )
        with self._conn() as conn:
            df = pd.read_sql_query(query, conn, params=(symbol, start, end))
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts")
        return df

    def latest_ts(self, symbol: str) -> Optional[str]:
        """Return ISO8601 UTC string of last stored bar, or None."""
        query = "SELECT MAX(ts) FROM minute_bars WHERE symbol = ?"
        with self._conn() as conn:
            row = conn.execute(query, (symbol,)).fetchone()
        return row[0] if row and row[0] else None
