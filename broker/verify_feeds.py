"""
verify_feeds.py
Quick sanity check to confirm market data feeds are accessible.

Usage:
    python broker/verify_feeds.py
"""

import sys
from datetime import datetime, timedelta


def verify_yfinance():
    """Verify yfinance can fetch equity data."""
    try:
        import yfinance as yf
        end = datetime.today().strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        data = yf.download("SPY", start=start, end=end, progress=False)
        if data.empty:
            print("  [FAIL] yfinance: SPY returned empty data")
            return False
        rows = len(data)
        print(f"  [OK]   yfinance: SPY — {rows} trading days fetched ({start} to {end})")
        return True
    except ImportError:
        print("  [FAIL] yfinance not installed. Run: pip install yfinance")
        return False
    except Exception as e:
        print(f"  [FAIL] yfinance: {e}")
        return False


def verify_alpaca():
    """Verify Alpaca API connectivity (requires env vars)."""
    import os
    import requests as req
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2").rstrip("/")

    if not api_key or api_key == "your_alpaca_api_key_here":
        print("  [SKIP] Alpaca: ALPACA_API_KEY not configured")
        return None

    try:
        headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
        r = req.get(f"{base_url}/account", headers=headers, timeout=10)
        if r.status_code != 200:
            print(f"  [FAIL] Alpaca: HTTP {r.status_code} — {r.text[:100]}")
            return False
        d = r.json()
        print(f"  [OK]   Alpaca: account {d['id']} — equity ${float(d['equity']):,.2f} — status: {d['status']}")
        return True
    except Exception as e:
        print(f"  [FAIL] Alpaca: {e}")
        return False


def verify_kraken():
    """Verify Kraken API connectivity (requires env vars)."""
    import os
    api_key = os.getenv("KRAKEN_API_KEY")
    api_secret = os.getenv("KRAKEN_API_SECRET")

    if not api_key or api_key == "your_kraken_api_key_here":
        print("  [SKIP] Kraken: KRAKEN_API_KEY not configured")
        return None

    try:
        import requests as req
        r = req.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=10)
        r.raise_for_status()
        ticker = r.json().get("result", {}).get("XXBTZUSD", {})
        btc_last = float(ticker.get("c", [0])[0])
        print(f"  [OK]   Kraken public: BTC/USD last ${btc_last:,.2f}")
    except Exception as e:
        print(f"  [FAIL] Kraken public feed: {e}")
        return False

    try:
        import krakenex  # type: ignore
        api = krakenex.API()
        api.key = api_key
        api.secret = api_secret
        resp = api.query_private("Balance")
        if resp.get("error"):
            print(f"  [FAIL] Kraken private API: {resp['error']}")
            return False
        print(f"  [OK]   Kraken private API authenticated — {len(resp.get('result', {}))} balance entries")
        return True
    except ImportError:
        print("  [SKIP] krakenex not installed. Run: pip install krakenex")
        return None
    except Exception as e:
        print(f"  [FAIL] Kraken private API: {e}")
        return False


def main():
    print("=" * 50)
    print("DATA FEED VERIFICATION")
    print("=" * 50)

    results = []
    print("\n[1] yfinance (equities backtest data):")
    results.append(verify_yfinance())

    print("\n[2] Alpaca (paper trading API):")
    results.append(verify_alpaca())

    print("\n[3] Kraken (crypto exchange API):")
    results.append(verify_kraken())

    print("\n" + "=" * 50)
    failures = [r for r in results if r is False]
    if failures:
        print(f"RESULT: {len(failures)} check(s) failed.")
        sys.exit(1)
    else:
        print("RESULT: All configured feeds OK.")


if __name__ == "__main__":
    main()
