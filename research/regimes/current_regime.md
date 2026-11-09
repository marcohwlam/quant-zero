# Current Market Regime

**Updated:** 2026-11-09 (SPY bar for 2026-11-09 may be intraday-partial; recheck at close)
**Author:** Market Regime Agent
**Issue:** QUA-908 (prior snapshot QUA-866, 2026-11-02)

## Change vs QUA-866

**Track A unchanged: unfavorable.** Distribution count still 7 (10-08, 10-14, 10-16, 10-22, 10-29, 10-30, 11-05; 09-30 rolled off, 11-05 added). Stage 2 is now marginal: close 747.37 vs 30-week MA 747.14. Track B shifted: volatility normal to divergent (GARCH high-vol), correlation normal to elevated.

## Track A Regime (Daily/Weekly)

- **O'Neil M-filter:** correction (distribution days in last 25 sessions: 7)
- **Weinstein Stage (SPY):** Stage 2, marginal (close 747.37 is 0.03% above rising 30-week MA 747.14; MA +2.1% vs 22 sessions ago). SPY closed 733.00 on 11-05, below the MA.
- **SPY 12-1m momentum:** risk-on (+17.4%)

**track_a_regime:** unfavorable
**Track A entry:** PAUSED. M-filter fails (7 >= 5). Stage 2 holds by a hair and momentum passes.

## Track B Classification (Minute-Level)

- **Trend:** choppy (Hurst 60d = 0.24)
- **Volatility:** high-vol by GARCH (27.7%); VIX 21.97 reads normal-vol. Diverge, report both.
- **Momentum:** risk-on
- **Liquidity:** liquid
- **Correlation:** elevated (SPY/BTC 60d = 0.501, was 0.398)

**Track B summary label:** `choppy / high-vol / risk-on / liquid / elevated-corr`

## Key Indicators

| Indicator | Value | Signal |
|---|---|---|
| VIX | 21.97 (25.64 on 11-06) | normal-vol, falling |
| GARCH(1,1) annualized vol | 27.7% (was 14.87%) | high-vol |
| SPY 200-day SMA delta | +2.7% (was +4.7%) | above trend |
| SPY 12-1m momentum | +17.4% | risk-on |
| Hurst exponent (60d) | 0.24 | mean-reverting / choppy |
| SPY/BTC-USD 60d corr | 0.501 | elevated |
| 2Y Treasury yield (^IRX) | 4.02% | stable (4.06% one month ago) |
| HYG/LQD spread ratio | 0.739 | widening (0.754 one month ago, -2.0%) |

Macro overlay: rates stable to falling, spreads widening. Rising-rates condition not met, so no severity amplification. Credit stress is a watch item for a second consecutive snapshot.

## Regime Stability

**Days in current regime:** 1 day (label changed from 2026-11-02)
**Regime stability:** LOW (< 5 days)

## Regime Confidence

**Confidence:** LOW (regime age, GARCH/VIX diverge)
**Volatility signal agreement:** GARCH (27.7%) and VIX (21.97) DIVERGE. VIX was 25.64 on 11-06, so the GARCH reading likely carries the 11-05/11-06 selloff.
**Transition risk:** HIGH. SPY sits on the 30-week MA; a close below 747 moves Stage 2 to Stage 3/4 and turns the M-filter warning into a trend break.

## Strategy Implications

- **Favored this regime:** short-horizon mean reversion on liquid ETFs; gap reversal families; defined-risk strategies
- **Caution this regime:** breakout and trend-following longs; stat arb and pairs (corr 0.50, elevated); leveraged momentum (GARCH high-vol)
- **Pause triggers:** VIX > 40 or GARCH > 35%; SPY close below 30-week MA (~747) ; SPY/BTC corr > 0.6 pauses stat arb
- **Track A resume trigger:** count below 5 requires 3 of the 7 to expire with no new hits. Next roll-offs: 10-08 (about 11-12), 10-14, 10-16 (about 11-20), if no new distribution days.
- **Correlation note:** elevated band: reduce stat arb sizing, no new stat arb entries.
