# CVD-Confirmed Breakout — Volume Delta as Breakout Strength Filter

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** multi-signal
**Status:** hypothesis

## Economic Rationale

Standard price-breakout strategies (buy when price closes above N-bar high) suffer from high false-breakout rates (~60–70% in equity markets). The root cause: price-based triggers are agnostic to whether the breakout was driven by genuine directional order flow or by low-volume/noise-driven price movement.

Cumulative Volume Delta (CVD) — the running sum of (buy volume minus sell volume) within a candle's time period, estimated from lower-timeframe sub-candles — provides a direct proxy for order flow intent. A breakout candle where buyers significantly dominate sellers (strongly positive CVD within that candle) has higher follow-through probability than one driven by passive market-making.

This hypothesis wraps the **Breakout Volume Delta** indicator (Flux Charts) as a confirmation filter on a standard price-breakout signal:
- **Signal 1 (price breakout):** Close above N-bar high (standard momentum entry)
- **Signal 2 (CVD confirmation):** CVD delta within the breakout candle exceeds a threshold (bullish dominance confirmed by order flow)

The economic mechanism is supported by:
- Market microstructure theory: aggressive buying during a breakout is predictive of continuation (Kyle 1985, Glosten-Milgrom model)
- Empirical findings: volume-price divergence (breakout with weak volume) signals lower follow-through (Lo, Mamaysky & Wang 2000, "Foundations of Technical Analysis")

At a $25K account scale, this applies to liquid ETFs (SPY, QQQ, IWM) or large-cap stocks where intraday volume data is accessible. CVD estimation requires a data source that provides sub-candle volume (many charting platforms; yfinance provides daily OHLCV but not intrabar volume — see feasibility note below).

## Signal Combination *(multi-signal)*

- **Component signals (2 signals):**
  | Signal | IC Estimate | Weight | Source |
  |--------|-------------|--------|--------|
  | Price breakout (N-bar high close) | 0.03–0.05 | 0.5 (equal) | Standard momentum entry, well-documented |
  | CVD delta within breakout candle | 0.03–0.05 | 0.5 (equal) | Flux Charts BVD indicator; order flow confirmation |

- **Combination method:** equal-weight (Research Director approval required for IC-weighted)
- **Combined signal IC estimate:** 0.05–0.08 (diversification benefit expected; price and order flow partially independent)
- **Rationale for combination:** Price-breakout and CVD measure different dimensions of the same event (price action vs. order flow). When both confirm simultaneously, false-breakout probability is reduced.
- **Overfitting guard:** Price breakout IC > 0.03 (confirmed by H05, H07 backtests). CVD IC must be confirmed at > 0.02 before use. Both individually qualify.

> **Feasibility note on CVD data:** yfinance provides end-of-day OHLCV only — no intrabar volume. To estimate CVD from daily data, a proxy approach is required: `CVD_proxy = (Close - Open) / (High - Low) × Volume` (the "money flow" approximation). This is an imperfect proxy but directionally meaningful. Full CVD requires tick or 1-minute data (e.g., Polygon.io). Engineering Director should flag data feasibility during backtesting.

## Entry/Exit Logic

**Entry signal (AND conditions):**
1. Daily close > N-day high (lookback = 20 bars default)
2. CVD_proxy within breakout candle > `cvd_threshold` × average(CVD_proxy, 20 days) — confirms above-average buying pressure on the breakout day

**Exit signal:**
- Take profit: +R×ATR(14) above entry (e.g., R=2.0)
- Stop loss: -1×ATR(14) below entry
- Trailing stop option: trail at 1×ATR once +1×ATR profit reached

**Holding period:** Swing (2–10 trading days)

## Market Regime Context

**Works best:**
- Trending markets with momentum (uptrend confirmation for long breakouts)
- Moderate to high volume regimes (CVD signal requires genuine order flow)
- Earnings season: higher volume → more reliable CVD estimates

**Tends to fail:**
- Range-bound markets: false breakouts are frequent regardless of CVD
- Low-volume environments (summer, holiday periods): CVD proxy becomes noisy
- Large-cap stocks pre/post-earnings: price gap breakouts are news-driven; CVD adds less predictive value

## Alpha Decay

- **Signal half-life (days):** 5–10 days (price momentum signal typically has IC that decays over 1–2 weeks on daily bars)
- **Edge erosion rate:** moderate (5–15 days)
- **Recommended max holding period:** 10 trading days (2 calendar weeks)
- **Cost survival:** Yes — SPY/QQQ/large-caps have minimal spread; round-trip cost < 0.05% + commissions. With 2×ATR profit target (~1–2% on daily bars), edge survives realistically.
- **Annualised IR estimate:** IC of 0.05 on combined signal × average return ~1.5% per trade × ~35 signals/year → raw return ~5–7%; realised vol ~15–20% → IR ≈ 0.35–0.45. Achievable if CVD confirmation genuinely reduces false breakouts from 60% to <45%.
- **Notes:** CVD IC estimate is theoretical — no backtesting on daily proxy data has been done. The 0.03–0.05 IC is an informed estimate based on literature, not empirically confirmed at this firm.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| breakout_lookback | 15 – 40 | N-bar high for price breakout signal |
| cvd_threshold_mult | 0.5 – 2.0 | CVD proxy must exceed X × 20-day average |
| atr_period | 10 – 20 | ATR for stop/target sizing |
| profit_r_multiple | 1.5 – 3.0 | Reward multiple in ATR units |
| universe | SPY/QQQ/IWM, top 50 S&P500 | Limit to liquid names where volume is meaningful |

## Capital and PDT Compatibility

- **Minimum capital required:** $2,500 (single lot in liquid ETFs)
- **PDT impact:** Low — swing holding of 2–10 days avoids day-trade classification. At 1–3 signals/week, well within PDT limits. If signal frequency is higher, must gate to avoid PDT violation.
- **Position sizing:** 10–20% of portfolio per trade; max 3 concurrent positions to stay within signal frequency constraints.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Uncertain. Price-breakout alone typically yields Sharpe 0.6–0.9. CVD filter may push it above 1.0 if it genuinely improves win-rate by reducing false breakouts. Not guaranteed.
- **OOS persistence:** Medium confidence — order flow logic is economically grounded, but daily CVD proxy may be too noisy to add consistent value over price alone.
- **Walk-forward stability:** Medium-high risk. `cvd_threshold_mult` is a new parameter type (continuous threshold on an approximate proxy); high sensitivity risk. Must test robustness across a wide range.
- **Sensitivity risk:** High. CVD proxy quality is uncertain; small changes in `cvd_threshold_mult` could drastically alter signal frequency.
- **Known overfitting risks:** The TV indicator (Flux Charts BVD) was designed for intraday visual use, not daily backtesting. Translating from intraday CVD to a daily proxy introduces model risk. If the proxy is too crude, the CVD "signal" may be noise. Must confirm IC > 0.02 for CVD component before building multi-signal combination.

## TV Source Caveat

- **Original TV indicator:** "Breakout Volume Delta | Flux Charts" by fluxchart
- **URL:** https://www.tradingview.com/script/BsWaPtEz-Breakout-Volume-Delta-Flux-Charts/
- **Apparent backtest window:** Indicator (not a strategy), so no backtest window disclosed. Flux Charts is a serious indicator publisher with multiple professional tools — higher quality bar than typical community scripts.
- **Crowding risk:** Low–medium. Volume delta is a well-known concept but not commonly systematised as a daily breakout filter. The specific Flux Charts implementation uses lower-timeframe sub-candle volume, which requires intrabar data not available in standard daily backtests.
- **Novel insight vs H01–H08:** All prior hypotheses use price/oscillator signals. This is the first hypothesis introducing order flow (volume delta) as a filter. The combination of price structure breakout + CVD confirmation is meaningfully distinct from H05 (momentum vol-scaled) and from every prior hypothesis.

## References

- Kyle, A. (1985): "Continuous Auctions and Insider Trading" — Econometrica (theoretical basis for order flow predictiveness)
- Glosten, L. & Milgrom, P. (1985): "Bid, Ask and Transaction Prices in a Specialist Market" — Journal of Financial Economics
- Lo, Mamaysky & Wang (2000): "Foundations of Technical Analysis" — Journal of Finance (volume-price relationship)
- Flux Charts Breakout Volume Delta: https://www.tradingview.com/script/BsWaPtEz-Breakout-Volume-Delta-Flux-Charts/
- Related in knowledge base: research/hypotheses/05_momentum_vol_scaled.md (momentum entry framework), research/hypotheses/01_dual_moving_average_crossover.md (breakout analogue)
