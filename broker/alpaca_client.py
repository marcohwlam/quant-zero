"""
Alpaca Broker Client — Paper Trading
Quant Zero Engineering Director
Date: 2026-03-16

Wraps the Alpaca REST API for crypto paper trading (Phase 2 paper).
Reads credentials from environment variables or broker/.env file.

Credential resolution order (first wins):
    1. Shell environment variables (ALPACA_API_KEY, ALPACA_API_SECRET)
    2. broker/.env file in the repo root (auto-loaded if env vars not set)

Required credentials:
    ALPACA_API_KEY     — from https://app.alpaca.markets → Paper Trading keys
    ALPACA_API_SECRET  — from https://app.alpaca.markets → Paper Trading keys
    ALPACA_BASE_URL    — defaults to paper endpoint (https://paper-api.alpaca.markets)
    ALPACA_DATA_URL    — defaults to https://data.alpaca.markets

Crypto-specific:
    Alpaca supports crypto trading via the same REST API as equities.
    BTC/USD and ETH/USD are available as BTCUSD and ETHUSD (no hyphen).
    Fractional shares are supported for crypto.

Usage:
    client = AlpacaClient()
    account = client.get_account()
    order = client.submit_order("BTCUSD", qty=0.01, side="buy")
"""

import os
import time
import logging
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _load_broker_env() -> None:
    """
    Load broker/.env into os.environ without overwriting existing variables.

    Searches for broker/.env relative to this file's location (../broker/.env
    from any depth), then falls back to repo-root broker/.env.
    Skips blank lines and comment lines (starting with #).
    Values may optionally be quoted with ' or ".
    """
    # Resolve broker/.env: this file lives in broker/, so sibling .env
    broker_dir = Path(__file__).parent
    env_path = broker_dir / ".env"

    if not env_path.exists():
        return

    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw_value = line.partition("=")
            key = key.strip()
            value = raw_value.strip().strip("'\"")
            # Never overwrite a value already set in the shell environment
            if key and key not in os.environ:
                os.environ[key] = value


# Load .env on module import so AlpacaClient() works without pre-setting env vars
_load_broker_env()


# Alpaca symbol mapping (yfinance format → Alpaca format)
SYMBOL_MAP = {
    "BTC-USD": "BTCUSD",
    "ETH-USD": "ETHUSD",
    "BTCUSD":  "BTCUSD",
    "ETHUSD":  "ETHUSD",
}


class AlpacaClient:
    """
    Lightweight Alpaca REST API client for paper trading.

    Supports:
    - Account queries
    - Order submission (market/limit)
    - Position queries
    - Order status / cancellation

    For crypto, uses Alpaca's crypto trading endpoint.
    All orders are placed as paper trading by default (ALPACA_BASE_URL = paper endpoint).
    """

    def __init__(self):
        self.api_key    = os.environ.get("ALPACA_API_KEY")
        self.api_secret = os.environ.get("ALPACA_API_SECRET")
        self.base_url   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/").removesuffix("/v2")
        self.data_url   = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets")

        if not self.api_key or not self.api_secret:
            raise EnvironmentError(
                "ALPACA_API_KEY and ALPACA_API_SECRET must be set as environment variables. "
                "Get paper trading keys at https://app.alpaca.markets (free, no minimum)."
            )

        self.headers = {
            "APCA-API-KEY-ID":     self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type":        "application/json",
        }
        self._validate_connection()

    def _validate_connection(self):
        """Test API connection on init. Raises on auth failure."""
        account = self.get_account()
        if "error" in str(account).lower():
            raise ConnectionError(f"Alpaca API auth failed: {account}")
        logger.info(
            f"Alpaca connected — account: {account.get('id', 'N/A')}, "
            f"status: {account.get('status', 'N/A')}, "
            f"portfolio_value: ${account.get('portfolio_value', 'N/A')}"
        )

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}/v2/{path.lstrip('/')}"
        resp = requests.get(url, headers=self.headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}/v2/{path.lstrip('/')}"
        resp = requests.post(url, headers=self.headers, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        url = f"{self.base_url}/v2/{path.lstrip('/')}"
        resp = requests.delete(url, headers=self.headers, timeout=10)
        if resp.status_code == 204:
            return {"status": "cancelled"}
        resp.raise_for_status()
        return resp.json()

    # ── Account ──────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Return account summary: portfolio_value, cash, buying_power, status."""
        return self._get("account")

    def get_portfolio_value(self) -> float:
        account = self.get_account()
        return float(account.get("portfolio_value", 0))

    def get_cash(self) -> float:
        account = self.get_account()
        return float(account.get("cash", 0))

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> list:
        """Return list of open positions."""
        return self._get("positions")

    def get_position(self, symbol: str) -> Optional[dict]:
        """Return single position, or None if not held."""
        try:
            return self._get(f"positions/{self._map_symbol(symbol)}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def close_position(self, symbol: str) -> dict:
        """Close entire position for a symbol at market."""
        return self._delete(f"positions/{self._map_symbol(symbol)}")

    def close_all_positions(self) -> list:
        """Close all open positions."""
        return self._delete("positions")

    # ── Orders ────────────────────────────────────────────────────────────────

    def submit_order(
        self,
        symbol: str,
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        side: str = "buy",
        order_type: str = "market",
        time_in_force: str = "gtc",
        limit_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """
        Submit an order to Alpaca.

        For crypto: use fractional qty (e.g., 0.001 BTC) or notional (dollar amount).
        For market orders: either qty or notional required (not both).

        Args:
            symbol:         yfinance or Alpaca format ("BTC-USD" or "BTCUSD")
            qty:            quantity in base asset units (fractional supported for crypto)
            notional:       dollar amount to trade (alternative to qty for market orders)
            side:           "buy" or "sell"
            order_type:     "market" or "limit"
            time_in_force:  "gtc" (crypto), "day" (equities)
            limit_price:    required if order_type="limit"
            client_order_id: optional idempotency key

        Returns:
            Alpaca order dict with id, status, symbol, qty, filled_qty, etc.
        """
        if qty is None and notional is None:
            raise ValueError("Either qty or notional must be specified.")

        alpaca_sym = self._map_symbol(symbol)
        payload = {
            "symbol":         alpaca_sym,
            "side":           side,
            "type":           order_type,
            "time_in_force":  time_in_force,
        }

        if qty is not None:
            payload["qty"] = str(qty)
        elif notional is not None:
            payload["notional"] = str(notional)

        if order_type == "limit" and limit_price is not None:
            payload["limit_price"] = str(limit_price)

        if client_order_id:
            payload["client_order_id"] = client_order_id

        logger.info(f"Submitting order: {side} {alpaca_sym} qty={qty} notional={notional}")
        return self._post("orders", payload)

    def get_order(self, order_id: str) -> dict:
        return self._get(f"orders/{order_id}")

    def cancel_order(self, order_id: str) -> dict:
        return self._delete(f"orders/{order_id}")

    def get_open_orders(self) -> list:
        return self._get("orders", params={"status": "open"})

    def wait_for_fill(self, order_id: str, max_wait_secs: int = 30, poll_secs: int = 2) -> dict:
        """
        Poll order status until filled or timeout.

        For market orders, fill should be near-instant for liquid crypto.
        Returns the final order dict.
        """
        elapsed = 0
        while elapsed < max_wait_secs:
            order = self.get_order(order_id)
            status = order.get("status", "")
            if status in ("filled", "partially_filled"):
                return order
            if status in ("cancelled", "expired", "rejected"):
                logger.warning(f"Order {order_id} ended with status: {status}")
                return order
            time.sleep(poll_secs)
            elapsed += poll_secs

        logger.warning(f"Order {order_id} not filled within {max_wait_secs}s. Returning current state.")
        return self.get_order(order_id)

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_crypto_quote(self, symbol: str) -> dict:
        """
        Get latest crypto quote from Alpaca data API.
        Returns ask, bid, last price.
        """
        alpaca_sym = self._map_symbol(symbol)
        url = f"{self.data_url}/v1beta3/crypto/us/latest/quotes"
        resp = requests.get(
            url,
            headers=self.headers,
            params={"symbols": alpaca_sym},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get("quotes", {})
        return quotes.get(alpaca_sym, {})

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _map_symbol(symbol: str) -> str:
        """Convert yfinance symbol (BTC-USD) to Alpaca format (BTCUSD)."""
        return SYMBOL_MAP.get(symbol, symbol.replace("-", ""))
