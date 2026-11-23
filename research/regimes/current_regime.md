# Current Market Regime

**Updated:** 2026-11-23 (computed on the last complete SPY bar, 2026-11-20. The 11-23 bar is intraday-partial, volume 18.7M, and was not used for classification.)
**Author:** Market Regime Agent
**Issue:** QUA-991 (prior snapshot QUA-951, 2026-11-16)

## Change vs QUA-951

**Track A unchanged: unfavorable, and worse.** Distribution count rose from 7 to 9. The 11-16 bar is now final: close 739.95, not the partial 745.66. Recomputed with final data, 11-16 and 11-17 both count as distribution days. SPY closed 11-20 at 689.81 (-3.6% on 151M shares, the heaviest volume in the window), 8.0% below the 30-week MA. Track B volatility stays high-vol, now confirmed by both GARCH and VIX.

## Track A Regime (Daily/Weekly)

- **O'Neil M-filter:** correction (distribution days in last 25 sessions: 9: 10-22, 10-29, 10-30, 11-05, 11-13, 11-16, 11-17, 11-19, 11-20)
- **Weinstein Stage (SPY):** Stage 3 (close 689.81 is below a rising 30-week MA 750.00; MA +1.7% vs 22 sessions ago). Stage 4 only if the MA turns down.
- **SPY 12-1m momentum:** risk-on (+16.5%)

**track_a_regime:** unfavorable
**Track A entry:** PAUSED. M-filter fails (9 >= 5) and Stage 2 fails. Only momentum passes.

## SPY vs Moving Averages (11-20 close)

| MA | Level | SPY delta |
|---|---|---|
| 50-day | 760.03 | -9.2% (below) |
| 200-day | 730.29 | -5.5% (below) |
| 30-week (150d) | 750.00 | -8.0% (below) |

SPY lost the 200-day on 11-20, which it held on 11-16. The 11-23 partial bar (721.64, +4.6%) is still below the 200-day.

## Rate and Credit Indicators (through 11-20)

| Series | Now | 5 sessions ago | 1 month ago |
|---|---|---|---|
| ^IRX (3M) | 4.12% | 4.12% | 4.02% |
| ^TNX (10Y) | 4.91% | 5.15% | 4.95% |
| HYG/LQD | 0.7361 | | 0.7384 (marginally widening) |

The 10Y fell 24bp in the week, reversing the prior spike (flight to quality). Rates are not rising and the spread move is small, so the rising-rates plus widening-spreads amplification rule is NOT met.

## Track B Classification (Minute-Level)

- **Trend:** choppy (Hurst 60d = 0.25)
- **Volatility:** high-vol. GARCH 21.82% (20-35% band) and VIX 35.89 (> 25) agree.
- **Momentum:** risk-on
- **Liquidity:** liquid
- **Correlation:** crisis (SPY/BTC 60d = 0.625, was 0.605)

**Track B summary label:** `choppy / high-vol / risk-on / liquid / crisis-corr`

## Key Indicators

| Indicator | Value | Signal |
|---|---|---|
| VIX (11-20 close) | 35.89 | high-vol, 4 points below the 40 crisis line (11-23 intraday 28.56) |
| GARCH(1,1) annualized vol | 21.82% | high-vol |
| SPY 200-day SMA delta | -5.5% | below trend |
| SPY 12-1m momentum | +16.5% | risk-on |
| Hurst exponent (60d) | 0.25 | mean-reverting/choppy |
| SPY/BTC-USD 60d corr | 0.625 | crisis (> 0.6) |
| 2Y proxy (^IRX) | 4.12% | stable |
| HYG/LQD spread ratio | 0.7361 | stable to marginally widening |

## Regime Stability

**Days in current regime:** 2 (snapshots 11-16 and 11-20 share the label; the CSV is sampled weekly)
**Regime stability:** LOW (< 5 days)

## Regime Confidence

**Confidence:** LOW
**Volatility signal agreement:** GARCH and VIX agree (both high-vol), so no divergence downgrade. LOW is from regime age.
**Transition risk:** HIGH. VIX hit 35.89 on 11-20, near the 40 crisis trigger, then fell to 28.56 on the 11-23 bounce. GARCH lags VIX and is likely to rise on the 11-20 move. The 200-day break and a -3.6% day on 2x average volume raise the odds of Stage 4 if the 30-week MA turns down.

## Strategy Implications

- **Favored this regime:** volatility premium capture (watch the VIX spike), short-term reversals on liquid ETFs, defensive factors
- **Caution this regime:** leveraged momentum and any Track A long entry (paused)
- **PAUSE (correlation crisis):** all stat arb, pairs and cointegration strategies (SPY/BTC 0.625)
- **Pause triggers:** VIX > 40 or GARCH > 35% pauses all live strategies. A fall of the 30-week MA turns Stage 3 into Stage 4.
- **Track A resume:** distribution count below 5 AND SPY back above a rising 30-week MA (about 750).
