# Current Market Regime

**Updated:** 2026-10-26
**Author:** Market Regime Agent
**Issue:** QUA-800

## Track A Regime (Daily/Weekly)

- **O'Neil M-filter:** correction (distribution days in last 25 sessions: 7, threshold 5)
- **Weinstein Stage (SPY):** Stage 2 (price 763.48 above rising 30-week MA 739.87; MA was 725.84 22 sessions ago)
- **SPY 12-1m momentum:** risk-on (+14.3%)

**track_a_regime:** unfavorable
**Track A entry:** PAUSED. M-filter fails (7 >= 5 distribution days). Stage 2 and momentum pass, so this is a distribution-driven pause inside an intact uptrend, not a trend break.

## Track B Classification (Minute-Level)

- **Trend:** choppy (Hurst 0.23, 20d return -0.3%, 60d return +2.5%)
- **Volatility:** normal-vol
- **Momentum:** risk-on
- **Liquidity:** liquid
- **Correlation:** normal

**Track B summary label:** `choppy / normal-vol / risk-on / liquid / normal-corr`

## Key Indicators

| Indicator | Value | Signal |
|---|---|---|
| SPY close | 763.48 | 2.0% below 52-week high |
| VIX | 18.61 | normal-vol |
| GARCH(1,1) annualized vol | 12.77% | normal-vol (low edge of 12-20%) |
| SPY 200-day SMA delta | +5.4% | above trend |
| SPY 12-1m momentum | +14.3% | risk-on |
| Hurst exponent (120d log-price, lags 2-19) | 0.23 | mean-reverting / choppy (< 0.45) |
| SPY/BTC-USD 60d corr | 0.37 | normal (< 0.4, close to elevated) |
| 3M T-bill (^IRX) | 4.04% | stable (4.07% one month ago) |
| 10Y yield (^TNX) | 4.97% | falling (5.18% one month ago) |
| HYG/LQD ratio | 0.7403 | widening (0.7543 one month ago, -1.9%) |

## Rate State

Front end flat (^IRX 4.04%). Long end easing (10Y 4.97%, -21 bp in one month) but still near 5%. Rates are not rising, so the macro overlay (rising rates AND widening spreads) is not triggered. Credit is the soft spot: HYG/LQD widened 1.9% in one month. Watch for a second signal.

## Regime Stability

**Days in current regime:** 1 day (historical CSV had a gap from 2026-03-16; day count restarts)
**Regime stability:** LOW (< 5 days)

## Regime Confidence

**Confidence:** LOW (regime age). Volatility: GARCH 12.8% and VIX 18.6 both classify normal-vol, so vol signal itself is HIGH confidence.
**Transition risk:** MEDIUM. Hurst 0.23 with 7 distribution days signals churn under a still-rising 30-week MA. Correlation 0.37 sits near the 0.4 elevated line. Credit spread widening adds downside risk.

## Track A Suitability

| Family | Fit | Reason |
|---|---|---|
| Weinstein Stage 2 (breakout above 30-week MA, relative-volume confirmation) | Structurally fits, entries PAUSED | SPY is Stage 2, but M-filter reads correction. Resume new entries when distribution count falls below 5. |
| Pattern-based (cup-with-handle, flat base, VCP breakouts) | Poor fit now | Breakouts fail in distribution-heavy, low-Hurst tape. Wait for M-filter to clear. |

Resume trigger: distribution days < 5 in rolling 25 sessions AND SPY holds above rising 30-week MA. Hard stop: SPY closes below 30-week MA (739.87) moves to Stage 3/4 and keeps Track A off regardless of M-filter.
Existing positions: manage with stops; no new adds.

## Strategy Implications

- **Favored this regime:** short-term mean reversion on liquid ETFs; volatility premium capture; stat arb is permitted (corr normal), with reduced size given proximity to 0.4
- **Caution this regime:** trend-following and breakout momentum (Hurst 0.23, 7 distribution days)
- **Pause triggers:** VIX > 40 or GARCH > 35%; SPY below 30-week MA; SPY/BTC corr >= 0.4 (reduce stat arb) or >= 0.6 (pause); HYG/LQD widening continues alongside rising yields
- **Correlation note:** normal, no stat arb pause. The March 2026 correlation-crisis pause (corr 0.615) has cleared.
