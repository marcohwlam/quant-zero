# Broker Configuration

Broker API integrations for Quant Zero. API keys are **never committed** — use environment variables.

## Required Environment Variables

### Alpaca (Equities / Options)

```bash
ALPACA_API_KEY=your_key_here
ALPACA_API_SECRET=your_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets   # paper trading
# ALPACA_BASE_URL=https://api.alpaca.markets       # live trading (Phase 3+)
```

Sign up: https://alpaca.markets
Paper trading: free, no minimum
Docs: https://docs.alpaca.markets

### Crypto (Coinbase Advanced Trade or Kraken)

```bash
# Coinbase Advanced Trade
COINBASE_API_KEY=your_key_here
COINBASE_API_SECRET=your_secret_here
COINBASE_SANDBOX=true   # set to false for live

# OR Kraken
KRAKEN_API_KEY=your_key_here
KRAKEN_API_SECRET=your_secret_here
KRAKEN_SANDBOX=true
```

## Setup Checklist

- [ ] Create Alpaca account at https://alpaca.markets
- [ ] Generate paper trading API key + secret
- [ ] Verify paper account is funded (simulated $100k default)
- [ ] Create crypto exchange account (Coinbase Advanced or Kraken)
- [ ] Generate API key with trading permissions
- [ ] Confirm testnet/sandbox access
- [ ] Add all keys to `.env` (see `.env.example`)
- [ ] Verify yfinance data feed works: `python broker/verify_feeds.py`

## Data Feeds

| Asset Class | Feed          | Notes                          |
|-------------|---------------|--------------------------------|
| Equities    | yfinance      | Free, sufficient for backtesting |
| Options     | Alpaca API    | Phase 2+ (paper → live)       |
| Crypto      | Exchange API  | BTC/ETH only in Phase 1-2      |

## File Structure

```
broker/
  README.md          — this file
  .env.example       — env var template (commit-safe, no real keys)
  alpaca_client.py   — Alpaca API wrapper (Phase 2)
  crypto_client.py   — Crypto exchange wrapper (Phase 2)
  verify_feeds.py    — Data feed verification script
```

> **Security:** Never commit `.env`, `*.key`, or any file containing real API credentials.
> Add these patterns to `.gitignore`.
