# Current Market Regime

**Updated:** 2026-11-02 (SPY bar for 2026-11-02 may be intraday-partial; recheck at close)
**Author:** Market Regime Agent
**Issue:** QUA-866

## Track A Regime (Daily/Weekly)

- **O'Neil M-filter:** correction (distribution days in last 25 sessions: 7; dates 2026-09-30, 10-08, 10-14, 10-16, 10-22, 10-29, 10-30)
- **Weinstein Stage (SPY):** Stage 2 (close 760.23 above rising 30-week MA 744.03; MA +2.1% vs 22 sessions ago)
- **SPY 12-1m momentum:** risk-on (+14.4%)

**track_a_regime:** unfavorable
**Track A entry:** PAUSED. M-filter fails (7 >= 5). Stage 2 and momentum still pass, so this is a distribution-driven correction warning inside an intact uptrend, not a trend break.

## Track B Classification (Minute-Level)

- **Trend:** choppy (Hurst 60d = 0.19, below 0.45)
- **Volatility:** normal-vol
- **Momentum:** risk-on
- **Liquidity:** liquid
- **Correlation:** normal (0.398, borderline: 0.002 under the elevated threshold)

**Track B summary label:** `choppy / normal-vol / risk-on / liquid / normal-corr`

## Key Indicators

| Indicator | Value | Signal |
|---|---|---|
| VIX | 19.07 | normal-vol |
| GARCH(1,1) annualized vol | 14.87% | normal-vol |
| SPY 200-day SMA delta | +4.7% | above trend |
| SPY 12-1m momentum | +14.4% | risk-on |
| Hurst exponent (60d) | 0.19 | mean-reverting / choppy |
| SPY/BTC-USD 60d corr | 0.398 | normal (edge of elevated) |
| 2Y Treasury yield (^IRX) | 4.00% | stable (3.993% one month ago) |
| HYG/LQD spread ratio | 0.741 | widening (0.755 one month ago, -1.9%) |

Macro overlay: rates stable, spreads widening. Rising-rates condition not met, so no severity amplification. Credit is a watch item.

## Regime Stability

**Days in current regime:** 1 day (prior entry 2026-03-16 is 7 months stale; history has a gap, no continuity claimed)
**Regime stability:** LOW (< 5 days)

## Regime Confidence

**Confidence:** LOW (regime age)
**Volatility signal agreement:** GARCH (14.87%) and VIX (19.07) both normal-vol, AGREE.
**Transition risk:** MEDIUM-HIGH. Distribution days clustered in the last 5 sessions (10-22, 10-29, 10-30), HYG/LQD widening, corr 0.398 about to cross 0.4.

## Strategy Implications

- **Favored this regime:** short-horizon mean reversion on liquid ETFs; overnight/gap reversal families; defined-risk strategies
- **Caution this regime:** breakout and trend-following longs (M-filter fails, Hurst choppy); stat arb (corr at elevated threshold)
- **Pause triggers:** VIX > 40 or GARCH > 35%; SPY close below 30-week MA (744) → Stage 3/4, M-filter failure becomes confirmed; SPY/BTC corr > 0.6 → pause stat arb
- **Track A resume trigger:** distribution count back below 5 (oldest hits roll off from 2026-09-30 onward; need 3 to expire with no new ones, earliest around 2026-10-16 + 25 sessions, about 2026-11-20, if no new distribution days)
- **Correlation note:** no stat arb pause required at 0.398, monitor daily

## Track A Family Fit (QUA-866)

| Family | Fit now | Reason |
|---|---|---|
| Momentum / breakout longs (Stage 2 VCP style) | POOR, paused | M-filter correction (7 distribution days); Hurst choppy |
| Overnight gainer reversal (H91 to H93) | NEUTRAL to FAVORABLE | Mean-reversion mechanism suits choppy, normal-vol tape; not gated on trend. Still Track A, so honor the M-filter pause for any long-only variant, or test with the filter as a stated condition |
| Index/ETF short-term mean reversion (IWM, H70 style) | FAVORABLE | Hurst 0.19, VIX 19, liquid |
| Stat arb / pairs | OK, monitor | Corr 0.398, 0.002 under elevated |
| Multi-month trend following | WAIT | Stage 2 intact, but resume only when distribution count < 5 |
