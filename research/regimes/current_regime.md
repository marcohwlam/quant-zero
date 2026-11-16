# Current Market Regime

**Updated:** 2026-11-16 (SPY 11-16 bar is intraday-partial, volume 6.8M; recheck at close)
**Author:** Market Regime Agent
**Issue:** QUA-951 (prior snapshot QUA-908, 2026-11-09)

## Change vs QUA-908

**Track A unchanged: unfavorable.** Distribution count still 7 (10-14, 10-16, 10-22, 10-29, 10-30, 11-05, 11-13; 10-08 rolled off, 11-13 added). Stage 2 broke: SPY 745.66 is below the 30-week MA 749.63. Track B correlation moved elevated to crisis (0.605). Rates are rising sharply at the long end.

## Track A Regime (Daily/Weekly)

- **O'Neil M-filter:** correction (distribution days in last 25 sessions: 7)
- **Weinstein Stage (SPY):** Stage 3 (close 745.66 is 0.5% below a rising 30-week MA 749.63; MA +1.9% vs 22 sessions ago). Stage 4 only if the MA turns down.
- **SPY 12-1m momentum:** risk-on (+14.8%)

**track_a_regime:** unfavorable
**Track A entry:** PAUSED. M-filter fails (7 >= 5) and Stage 2 fails. Only momentum passes.

## SPY vs Moving Averages

| MA | Level | SPY delta |
|---|---|---|
| 50-day | 763.64 | -2.4% (below) |
| 200-day | 729.61 | +2.2% (above) |
| 30-week (150d) | 749.63 | -0.5% (below) |

SPY lost the 50-day and the 30-week MA while holding the 200-day. Nearest support is the 200-day, 2.2% lower. Note: the task text says SPX; SPY is used as the proxy, consistent with prior snapshots.

## Rate-Shock Indicators

| Series | Now | 5 sessions ago | 1 month ago |
|---|---|---|---|
| ^IRX (3M) | 4.13% | 4.03% | 4.07% |
| ^FVX (5Y) | 4.96% | 4.66% (+30bp) | 4.90% |
| ^TNX (10Y) | 5.14% | 4.86% (+27bp) | 5.10% |
| ^TYX (30Y) | 5.47% | 5.26% (+21bp) | 5.44% |
| HYG/LQD | 0.7469 | | 0.7423 (tightening) |

**Rate shock: YES, 1-week.** The 10Y rose 27bp in 5 sessions to 5.14%, a multi-year high zone. The 1-month change is small (+4bp), so this is a sharp one-week spike, not a trend. Credit is not confirming: HYG/LQD is up 0.6% vs a month ago, so the rising-rates plus widening-spreads macro stress rule is NOT met and no severity amplification applies. This reverses the widening seen in QUA-908.

## Track B Classification (Minute-Level)

- **Trend:** choppy (Hurst 60d = 0.20)
- **Volatility:** high-vol by GARCH (20.1%, just above the 20% line); VIX 20.56 reads normal-vol. Diverge, report both.
- **Momentum:** risk-on
- **Liquidity:** liquid
- **Correlation:** crisis (SPY/BTC 60d = 0.605, was 0.501)

**Track B summary label:** `choppy / high-vol / risk-on / liquid / crisis-corr`

## Key Indicators

| Indicator | Value | Signal |
|---|---|---|
| VIX | 20.56 (17.49 four sessions ago) | normal-vol, rising |
| GARCH(1,1) annualized vol | 20.1% (was 27.7%) | high-vol, borderline |
| SPY 200-day SMA delta | +2.2% (was +2.7%) | above trend |
| SPY 12-1m momentum | +14.8% | risk-on |
| Hurst exponent (60d) | 0.20 | mean-reverting / choppy |
| SPY/BTC-USD 60d corr | 0.605 | crisis |
| 2Y proxy (^IRX) | 4.13% | stable |
| HYG/LQD spread ratio | 0.747 | tightening |

## Regime Stability

**Days in current regime:** 1 day (label changed from 2026-11-09: correlation elevated to crisis)
**Regime stability:** LOW (< 5 days)

## Regime Confidence

**Confidence:** LOW (regime age, GARCH/VIX diverge)
**Volatility signal agreement:** GARCH (20.1%) and VIX (20.56) DIVERGE on the label but both sit near the 20 boundary. VIX has risen 3 points in 4 sessions.
**Transition risk:** HIGH. SPY is below the 50-day and 30-week MA. A close below the 200-day (~730) would end the uptrend structure. Today's bar is partial, so the Stage 3 call may flip back on a strong close above 749.6.

## Strategy Implications

- **Favored this regime:** short-horizon mean reversion on liquid ETFs; defined-risk strategies
- **Caution this regime:** breakout and trend-following longs; leveraged momentum; long-duration exposure (10Y at 5.14%)
- **Pause triggers:** VIX > 40 or GARCH > 35%; SPY close below 200-day (~730)
- **Track A resume trigger:** needs distribution count below 5 and SPY back above the 30-week MA. Next roll-offs: 10-14 and 10-16 (about 11-19/11-20), 10-22 (about 11-24), if no new hits. 11-13 just added a 7th.
- **Correlation note:** crisis band (> 0.6): pause all stat arb / pairs strategies and review immediately.
