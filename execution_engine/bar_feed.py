"""
BarFeed: polls Alpaca REST data API for new bars per symbol.

Tracks the last seen bar timestamp per symbol. On each poll, fetches recent bars
and returns only those newer than the last seen timestamp. This provides the
"new bar available" event that drives the main engine loop.

Supports daily and minute bar frequencies.
Handles crypto (v1beta3 endpoint) and equities (v2 endpoint) transparently.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# yfinance symbol → Alpaca symbol mapping
_ALPACA_SYM = {
    "BTC-USD": "BTCUSD",
    "ETH-USD": "ETHUSD",
    "SOL-USD": "SOLUSD",
    "AVAX-USD": "AVAXUSD",
    "DOGE-USD": "DOGEUSD",
}

_CRYPTO_BASE = set(_ALPACA_SYM.keys())


def to_alpaca_symbol(symbol: str) -> str:
    return _ALPACA_SYM.get(symbol, symbol)


def is_crypto(symbol: str) -> bool:
    return symbol in _CRYPTO_BASE or (symbol.endswith("-USD") and "-" in symbol)


class BarFeed:
    """
    Polls Alpaca for new OHLCV bars. Returns bars with timestamps strictly
    later than the last seen bar for each symbol.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        data_url: str = "https://data.alpaca.markets",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._data_url = data_url.rstrip("/")
        self._last_ts: dict[str, str] = {}  # symbol (yfinance) → last bar ISO8601 ts

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
            "Accept": "application/json",
        }

    def _get(self, url: str, params: dict) -> dict:
        resp = requests.get(url, headers=self._headers(), params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def initialize_last_seen(self, symbol: str, bar_ts: Optional[str]) -> None:
        """Seed last-seen timestamp from the store on startup."""
        if bar_ts:
            self._last_ts[symbol] = bar_ts

    # ── Public API ────────────────────────────────────────────────────────────

    def get_new_daily_bars(self, symbols: list) -> dict:
        """
        Poll for the latest daily bar for each symbol.

        Returns {symbol: bar_dict} for symbols that have a bar newer than last seen.
        Returns {symbol: None} for symbols with no new bar.

        bar_dict keys: ts, open, high, low, close, volume, symbol
        """
        result = {}
        for symbol in symbols:
            bar = self._fetch_latest_daily(symbol)
            if bar is None:
                result[symbol] = None
                continue
            last = self._last_ts.get(symbol)
            if last and bar["ts"] <= last:
                result[symbol] = None
            else:
                self._last_ts[symbol] = bar["ts"]
                result[symbol] = bar
        return result

    # ── Internal fetchers ─────────────────────────────────────────────────────

    def _fetch_latest_daily(self, symbol: str) -> Optional[dict]:
        try:
            if is_crypto(symbol):
                return self._fetch_crypto_daily(symbol)
            return self._fetch_stock_daily(symbol)
        except requests.HTTPError as exc:
            logger.warning("BarFeed HTTP error for %s: %s", symbol, exc)
            return None
        except Exception as exc:
            logger.warning("BarFeed error for %s: %s", symbol, exc)
            return None

    def _fetch_crypto_daily(self, symbol: str) -> Optional[dict]:
        alpaca_sym = to_alpaca_symbol(symbol)
        start = (datetime.utcnow() - timedelta(days=4)).strftime("%Y-%m-%d")
        data = self._get(
            f"{self._data_url}/v1beta3/crypto/us/bars",
            {
                "symbols": alpaca_sym,
                "timeframe": "1Day",
                "start": start,
                "limit": 5,
                "sort": "desc",
            },
        )
        bars = data.get("bars", {}).get(alpaca_sym, [])
        if not bars:
            return None
        b = bars[0]
        return {
            "ts": b["t"],
            "open": float(b["o"]),
            "high": float(b["h"]),
            "low": float(b["l"]),
            "close": float(b["c"]),
            "volume": float(b["v"]),
            "symbol": symbol,
        }

    def _fetch_stock_daily(self, symbol: str) -> Optional[dict]:
        start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        data = self._get(
            f"{self._data_url}/v2/stocks/{symbol}/bars",
            {
                "timeframe": "1Day",
                "start": start,
                "limit": 5,
                "feed": "iex",
                "adjustment": "split",
                "sort": "desc",
            },
        )
        bars = data.get("bars", [])
        if not bars:
            return None
        b = bars[0]
        return {
            "ts": b["t"],
            "open": float(b["o"]),
            "high": float(b["h"]),
            "low": float(b["l"]),
            "close": float(b["c"]),
            "volume": float(b["v"]),
            "symbol": symbol,
        }
