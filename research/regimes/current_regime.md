# Current Market Regime

**Updated:** 2026-03-16
**Author:** Market Regime Agent

## Classification

- **Trend:** choppy
- **Volatility:** normal-vol
- **Momentum:** risk-on
- **Liquidity:** liquid
- **Correlation:** crisis

**Summary label:** `choppy / normal-vol / risk-on / liquid / crisis-corr`

## Key Indicators

| Indicator | Value | Signal |
|---|---|---|
| VIX | 23.51 | normal-vol (15–25 range) |
| GARCH(1,1) annualized vol | 14.55% | normal-vol (12–20%) |
| SPY 200-day SMA delta | +1.86% | above trend (bullish long-term structure) |
| SPY 12-1m momentum | +22.56% | risk-on |
| Hurst exponent (60d) | -0.003 | choppy (near-zero, well below 0.45 threshold) |
| SPY/BTC-USD 60d corr | 0.615 | **CRISIS (> 0.6) — stat arb pause triggered** |
| 2Y Treasury yield (^IRX) | 3.605% | marginally rising (+0.007% vs 1m ago) |
| HYG/LQD spread ratio | 0.7310 | tightening (was 0.7253 one month ago — credit stable) |

## Regime Stability

**Days in current regime:** 1 day
**Regime stability:** LOW (< 5 days — regime just changed today)
**Note:** Transition from prior `mildly-trending / high-vol / risk-on / liquid` regime. Multiple dimensions shifted simultaneously; treat as fresh classification.

## Regime Confidence

**Confidence:** LOW
**Volatility signal agreement:** GARCH (14.55%, normal-vol) and VIX (23.51, normal-vol) AGREE → HIGH vol confidence. Overall confidence downgraded to LOW due to regime age (1 day).
**Transition risk:** MEDIUM — VIX is in the upper half of the normal-vol band (23.5). A further selloff could push VIX back above 25 (high-vol). Hurst near zero suggests market is directionless; watch for trend establishment or continuation of choppy action.

## ⚠️ Critical Alert: Correlation Crisis

**SPY/BTC-USD 60-day rolling correlation: 0.615 (CRISIS level > 0.6)**

Per firm policy, a **crisis correlation** requires **immediate pause of all stat arb / pairs / cointegration strategies**. When equity-crypto correlation is this elevated, cross-asset diversification collapses and pairs assumptions break down.

- **Action required:** Pause any active stat arb / pairs trading strategies pending regime normalization
- **Resume trigger:** SPY/BTC 60d correlation drops below 0.4 (normal) or 0.6 (elevated) for ≥ 5 consecutive days

## Strategy Implications

- **Favored this regime:** Volatility premium capture strategies; short-term mean reversion on liquid ETFs; defensive factor tilt (low-beta, quality)
- **Caution this regime:** Trend-following / momentum (Hurst near zero indicates no persistent trend direction); leveraged directional bets
- **PAUSE — correlation crisis:** All stat arb, pairs trading, and cointegration strategies (H04, H31, H32 in backtest) — SPY/BTC crisis correlation collapses diversification assumptions
- **Pause triggers:**
  - VIX > 40 or GARCH vol > 35% → crisis regime, pause ALL strategies
  - SPY breaks 200d SMA (currently at 656.84) → suspend trend-following entirely
  - 12-1m momentum turns negative → suspend equity momentum (H05)
  - SPY/BTC corr remains above 0.6 → keep stat arb paused

## Macro Context

- **Rates:** 2Y Treasury (^IRX) at 3.605%, marginally rising (+0.007% vs 1 month ago) — not a stress signal on its own
- **Credit:** HYG/LQD ratio tightening (0.7310 vs 0.7253) — credit spreads contracting, supportive of risk-on
- **Macro overlay:** Rising rates (marginally) + tightening spreads → macro stress signal NOT triggered; risk-on supported by credit market
