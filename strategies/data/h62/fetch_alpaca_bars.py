"""
Strategy: H62 — Alpaca 30m Historical Data Fetcher
Author: Strategy Coder Agent
Date: 2026-06-10
Hypothesis: N/A — data pipeline utility
Asset class: equities

Fetches 30-minute OHLCV bars for the H62 universe (50 tickers) from
Alpaca Data API v2 for the date range 2021-10-01 → 2024-12-31.
Saves bars_30m.parquet and fetch_summary.json to this directory.

Usage:
    python strategies/data/h62/fetch_alpaca_bars.py

Credentials resolved from (first wins):
    1. ALPACA_API_KEY / ALPACA_API_SECRET env vars
    2. broker/.env in the repo root
"""

import os
import sys
import json
import time
import logging
import requests
import numpy as np
import pandas as pd
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Credential loading ─────────────────────────────────────────────────────────

def _load_broker_env() -> None:
    """Load broker/.env into os.environ without overwriting existing variables."""
    # Walk upward from this file to find broker/.env in the repo root
    search = Path(__file__).resolve()
    for _ in range(6):  # max 6 levels up
        candidate = search / "broker" / ".env"
        if candidate.exists():
            with open(candidate) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, raw_value = line.partition("=")
                    key = key.strip()
                    value = raw_value.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = value
            return
        search = search.parent


_load_broker_env()


# ── Constants ─────────────────────────────────────────────────────────────────

UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA', 'BRK-B',
    'JPM', 'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'BAC', 'INTC', 'CSCO',
    'VZ', 'PFE', 'KO', 'PEP', 'MRK', 'ABT', 'TMO', 'WMT', 'DIS', 'CMCSA',
    'NKE', 'IBM', 'MCD', 'ACN', 'TXN', 'QCOM', 'SBUX', 'GS', 'MS', 'AXP',
    'BA', 'CAT', 'HON', 'MMM', 'MDT', 'USB', 'C', 'WFC', 'MO', 'CL',
    'GE', 'XOM',
]

# yfinance format → Alpaca API format for non-standard symbols
SYMBOL_MAP = {
    "BRK-B": "BRK/B",
}

START_DATE = "2021-10-01"
END_DATE   = "2024-12-31"

DATA_URL = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets")

OUTPUT_DIR   = Path(__file__).parent
PARQUET_PATH = OUTPUT_DIR / "bars_30m.parquet"
SUMMARY_PATH = OUTPUT_DIR / "fetch_summary.json"

RATE_LIMIT_SLEEP  = 0.2    # seconds between requests
LOW_ROW_THRESHOLD = 1000   # warn if ticker has fewer rows
PAGE_SIZE         = 10000  # max rows per page (Alpaca limit)
REQUEST_TIMEOUT   = 30     # seconds per HTTP request


# ── Fetch logic ───────────────────────────────────────────────────────────────

def _make_headers() -> dict:
    api_key    = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        raise EnvironmentError(
            "ALPACA_API_KEY and ALPACA_API_SECRET must be set. "
            "Set them as env vars or in broker/.env."
        )
    return {
        "APCA-API-KEY-ID":     api_key,
        "APCA-API-SECRET-KEY": api_secret,
        "Accept":              "application/json",
    }


def fetch_bars_for_symbol(
    symbol: str,
    headers: dict,
    start: str = START_DATE,
    end: str = END_DATE,
) -> pd.DataFrame:
    """
    Fetch all 30-minute bars for one symbol from Alpaca v2 stocks/bars endpoint.
    Handles multi-page responses via next_page_token.
    Returns empty DataFrame if symbol is unavailable or delisted.
    """
    alpaca_symbol = SYMBOL_MAP.get(symbol, symbol)
    # Per-symbol endpoint: /v2/stocks/{symbol}/bars
    url = f"{DATA_URL}/v2/stocks/{alpaca_symbol}/bars"
    params: dict = {
        "timeframe":  "30Min",
        "start":      f"{start}T00:00:00Z",
        "end":        f"{end}T23:59:59Z",
        "adjustment": "all",
        "feed":       "sip",
        "limit":      PAGE_SIZE,
    }

    all_bars: list[dict] = []
    page_num = 0

    while True:
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status in (404, 422):
                logger.warning(f"WARNING: {symbol} — HTTP {status}, symbol may be delisted or invalid. Skipping.")
                return pd.DataFrame()
            logger.error(f"HTTP error fetching {symbol}: {exc}")
            raise

        data = resp.json()
        bars = data.get("bars", [])
        all_bars.extend(bars)
        page_num += 1

        next_token = data.get("next_page_token")
        if not next_token:
            break
        params["page_token"] = next_token

    if not all_bars:
        logger.warning(f"WARNING: {symbol} — 0 bars returned for requested date range.")
        return pd.DataFrame()

    df = pd.DataFrame(all_bars)
    # Alpaca bar fields: t=timestamp, o=open, h=high, l=low, c=close, v=volume
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df["symbol"]    = symbol  # preserve yfinance symbol for downstream consistency
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Keep only required columns; drop vw (VWAP) and n (trade count) if present
    keep = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]]

    return df.sort_values("timestamp").reset_index(drop=True)


# ── Validation ────────────────────────────────────────────────────────────────

def _max_consecutive_missing_bdays(dates: pd.Series) -> int:
    """
    Estimate max consecutive missing business days in a date series.
    Uses business-day calendar as approximation (ignores market holidays).
    """
    if dates.empty:
        return 999

    sorted_dates = pd.to_datetime(dates).dt.normalize().drop_duplicates().sort_values()
    if len(sorted_dates) < 2:
        return 0

    # Business days between consecutive observed dates minus 1 = missing days
    gaps = []
    for a, b in zip(sorted_dates[:-1], sorted_dates[1:]):
        bdays = len(pd.bdate_range(a, b)) - 1  # -1: exclude start day
        if bdays > 1:
            gaps.append(bdays - 1)  # subtract 1 for the day itself

    return max(gaps) if gaps else 0


def validate_and_summarize(df: pd.DataFrame) -> dict:
    """
    Validate fetched data. Returns summary dict for fetch_summary.json.
    Prints warnings for problematic tickers.
    """
    if df.empty:
        logger.error("No data fetched — DataFrame is empty.")
        return {"total_rows": 0, "tickers": {}, "warnings": ["No data fetched"]}

    total_rows = len(df)
    summary: dict = {
        "total_rows":  total_rows,
        "start_date":  START_DATE,
        "end_date":    END_DATE,
        "tickers":     {},
        "warnings":    [],
    }

    for sym, grp in df.groupby("symbol"):
        ts = grp["timestamp"]
        row_count = len(grp)
        ts_min    = str(ts.min())
        ts_max    = str(ts.max())
        max_gap   = _max_consecutive_missing_bdays(ts)

        ticker_info = {
            "row_count": row_count,
            "min_timestamp": ts_min,
            "max_timestamp": ts_max,
            "max_consecutive_missing_bdays": max_gap,
        }

        if row_count < LOW_ROW_THRESHOLD:
            msg = f"WARNING: {sym} has only {row_count} rows (< {LOW_ROW_THRESHOLD})"
            logger.warning(msg)
            summary["warnings"].append(msg)
            ticker_info["low_row_warning"] = True

        if max_gap > 5:
            msg = f"WARNING: {sym} has {max_gap} consecutive missing business days"
            logger.warning(msg)
            summary["warnings"].append(msg)
            ticker_info["gap_warning"] = True

        summary["tickers"][sym] = ticker_info

    missing_tickers = [t for t in UNIVERSE if t not in summary["tickers"]]
    if missing_tickers:
        msg = f"WARNING: tickers missing entirely: {missing_tickers}"
        logger.warning(msg)
        summary["warnings"].append(msg)

    return summary


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info(f"H62 Alpaca 30m Fetcher — {len(UNIVERSE)} tickers, {START_DATE} → {END_DATE}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    headers = _make_headers()
    all_frames: list[pd.DataFrame] = []

    for i, symbol in enumerate(UNIVERSE, start=1):
        logger.info(f"[{i:02d}/{len(UNIVERSE)}] Fetching {symbol} ...")
        try:
            df = fetch_bars_for_symbol(symbol, headers)
        except Exception as exc:
            logger.warning(f"WARNING: {symbol} — unexpected error: {exc}. Skipping.")
            df = pd.DataFrame()

        row_count = len(df)
        logger.info(f"  → {symbol}: {row_count:,} rows")

        if not df.empty:
            all_frames.append(df)

        # Respect rate limit between requests
        if i < len(UNIVERSE):
            time.sleep(RATE_LIMIT_SLEEP)

    if not all_frames:
        logger.error("No data fetched for any ticker. Check credentials and network.")
        sys.exit(1)

    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    logger.info(f"Saving {len(combined):,} rows to {PARQUET_PATH}")
    combined.to_parquet(PARQUET_PATH, index=False)

    logger.info("Running validation ...")
    summary = validate_and_summarize(combined)

    logger.info(f"Saving summary to {SUMMARY_PATH}")
    with open(SUMMARY_PATH, "w") as fh:
        json.dump(summary, fh, indent=2, default=str)

    # Print human-readable summary
    print("\n" + "=" * 60)
    print(f"FETCH SUMMARY")
    print(f"  Total rows   : {summary['total_rows']:,}")
    print(f"  Tickers      : {len(summary['tickers'])} / {len(UNIVERSE)}")
    print(f"  Date range   : {START_DATE} → {END_DATE}")
    if summary["warnings"]:
        print(f"\n  WARNINGS ({len(summary['warnings'])}):")
        for w in summary["warnings"]:
            print(f"    {w}")
    else:
        print("  No warnings.")
    print("=" * 60)


if __name__ == "__main__":
    main()
