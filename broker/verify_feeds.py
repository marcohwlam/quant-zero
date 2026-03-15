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
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not api_key or api_key == "your_alpaca_api_key_here":
        print("  [SKIP] Alpaca: ALPACA_API_KEY not configured")
        return None

    try:
        import alpaca_trade_api as tradeapi  # type: ignore
        api = tradeapi.REST(api_key, api_secret, base_url)
        account = api.get_account()
        print(f"  [OK]   Alpaca: account {account.id} — equity ${float(account.equity):,.2f}")
        return True
    except ImportError:
        print("  [SKIP] alpaca-trade-api not installed. Run: pip install alpaca-trade-api")
        return None
    except Exception as e:
        print(f"  [FAIL] Alpaca: {e}")
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

    print("\n" + "=" * 50)
    failures = [r for r in results if r is False]
    if failures:
        print(f"RESULT: {len(failures)} check(s) failed.")
        sys.exit(1)
    else:
        print("RESULT: All configured feeds OK.")


if __name__ == "__main__":
    main()
