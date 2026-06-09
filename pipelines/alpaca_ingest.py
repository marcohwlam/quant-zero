"""
Alpaca Historical Data API fetcher for 1-minute OHLCV bars.
Handles pagination and exponential-backoff retry on 429/503.
"""

import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from pipelines.minute_bar_store import MinuteBarStore

logger = logging.getLogger(__name__)

INTRADAY_UNIVERSE = ["SPY", "QQQ"]

_BASE_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
_BACKFILL_START = "2016-01-04"
_MAX_RETRIES = 3
_RETRY_CODES = {429, 503}


def _iso_now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yesterday_end_utc() -> str:
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    return f"{yesterday}T23:59:00Z"


class AlpacaMinuteIngester:
    """Fetches 1-minute bars from Alpaca v2 and stores them via MinuteBarStore."""

    def __init__(self, api_key: str, api_secret: str, store: MinuteBarStore) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.store = store

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    def _get_with_retry(self, url: str, params: dict) -> dict:
        """GET with exponential backoff on 429/503, max 3 retries."""
        delay = 2.0
        for attempt in range(_MAX_RETRIES + 1):
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in _RETRY_CODES and attempt < _MAX_RETRIES:
                logger.warning("HTTP %s — retry %d/%d in %.1fs", resp.status_code, attempt + 1, _MAX_RETRIES, delay)
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Max retries exceeded for {url}")  # should not reach here

    def fetch_and_store(self, symbol: str, start_date: str, end_date: str) -> int:
        """
        Fetch 1-min bars from Alpaca for symbol between start_date and end_date.
        Handles pagination automatically. Returns total bars stored.
        """
        url = _BASE_URL.format(symbol=symbol)
        params: dict = {
            "timeframe": "1Min",
            "start": start_date,
            "end": end_date,
            "adjustment": "split",
            "limit": 10000,
            "feed": "iex",  # free-tier feed
        }

        total = 0
        page = 0
        while True:
            data = self._get_with_retry(url, params)
            raw_bars = data.get("bars", []) or []
            if raw_bars:
                bars = [
                    {
                        "ts": b["t"],
                        "open": b["o"],
                        "high": b["h"],
                        "low": b["l"],
                        "close": b["c"],
                        "volume": b["v"],
                    }
                    for b in raw_bars
                ]
                stored = self.store.upsert_bars(symbol, bars)
                total += stored
                page += 1
                logger.debug("%s page %d: %d bars stored (cumulative %d)", symbol, page, stored, total)

            next_token = data.get("next_page_token")
            if not next_token:
                break
            params["page_token"] = next_token

        logger.info("%s: fetch_and_store complete — %d total bars", symbol, total)
        return total

    def catch_up(self, symbol: str) -> int:
        """
        Fetch from (latest stored bar + 1 min) to yesterday 23:59 UTC.
        For fresh symbols, starts from BACKFILL_START.
        """
        latest = self.store.latest_ts(symbol)
        if latest:
            # Advance by 1 minute to avoid re-fetching last bar
            last_dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            start = (last_dt + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            start = f"{_BACKFILL_START}T00:00:00Z"

        end = _yesterday_end_utc()
        if start >= end:
            logger.info("%s: already up-to-date (latest=%s)", symbol, latest)
            return 0

        logger.info("%s: catching up from %s to %s", symbol, start, end)
        return self.fetch_and_store(symbol, start, end)

    def catch_up_all(self) -> dict[str, int]:
        """Run catch_up for all symbols in INTRADAY_UNIVERSE."""
        results = {}
        for symbol in INTRADAY_UNIVERSE:
            results[symbol] = self.catch_up(symbol)
        return results


def make_ingester_from_env(store: Optional[MinuteBarStore] = None) -> AlpacaMinuteIngester:
    """Convenience factory — reads creds from env."""
    key = os.environ["ALPACA_API_KEY"]
    secret = os.environ["ALPACA_API_SECRET"]
    if store is None:
        store = MinuteBarStore()
    return AlpacaMinuteIngester(api_key=key, api_secret=secret, store=store)
