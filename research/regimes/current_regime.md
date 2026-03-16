# Current Market Regime

**Updated:** 2026-03-15
**Author:** Market Regime Agent

## Classification

- **Trend:** mildly-trending
- **Volatility:** high-vol
- **Momentum:** risk-on
- **Liquidity:** liquid

**Summary label:** `mildly-trending / high-vol / risk-on / liquid`

## Key Indicators

| Indicator | Value | Signal |
|---|---|---|
| VIX | 27.19 | high-vol (crossed above 25) |
| SPY 200-day SMA delta | +0.90% | barely above trend |
| SPY 12-1m momentum | +25.0% | risk-on |
| Hurst exponent (60d) | 0.732 | trending (reflecting trailing uptrend) |
| Sectors above 50d SMA | 4/11 | bearish breadth — defensives only |
| SPY 1m return | -4.29% | near-term correction |
| Realized vol 21d (ann) | 12.3% | low (large implied vs realized gap) |

## Regime Confidence

**Confidence:** MEDIUM
**Transition risk:** HIGH — SPY barely above 200d SMA; VIX approaching 30; only defensive sectors holding up. Regime may shift to `mean-reverting / high-vol / risk-off` if SPY breaks 200d SMA or VIX sustains above 30.

## Strategy Implications

- **Favored this regime:** Pairs trading (H04), Bollinger Band mean reversion on defensive sectors (H02)
- **Caution this regime:** Momentum (H05 — vol scaling helps but crash risk elevated), Multi-factor L/S (H03 — factor crowding risk)
- **Pause triggers:** VIX > 40 (pause all strategies); SPY breaks 200d SMA (suspend trend-following, reduce mean-reversion exposure); 12-1m momentum turns negative (suspend H05)
