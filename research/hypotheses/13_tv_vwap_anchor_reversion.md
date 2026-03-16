# VWAP Anchor Reversion

**Version:** 1.1
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** abandoned (Gate 1 FAIL — 2026-03-16)

## Gate 1 Result

**Verdict: ABANDONED** — 2026-03-16

**Gate 1 scorecard:** 6/12 criteria passed. Critical failures:

| Criterion | Threshold | Actual | Pass? |
|---|---|---|---|
| IS Sharpe | > 1.0 | 0.73 | FAIL |
| OOS Sharpe | > 0.7 | 0.26 | FAIL |
| Trade Count IS | ≥ 30 | 8 | FAIL |
| Walk-forward | 3/4 windows | 2/4 | FAIL |
| Sensitivity | < 50% var | 123.6% | FAIL |
| Permutation test | p ≤ 0.05 | p=0.636 | FAIL |

**Root cause:** The daily typical-price VWAP proxy (`(H+L+C)/3`) does not capture institutional VWAP benchmarking mechanics. At daily resolution with a 2.0 SD threshold, the signal fires ~2×/year/ETF — structurally insufficient for Gate 1 (need ≥ 30 IS trades). The permutation test failure (p=0.636) confirms the signal is statistically indistinguishable from noise at this granularity.

**Why options 3 (SD=1.5) was rejected:** Sensitivity analysis showed SD=1.5 yields Sharpe 1.07 with 33 trades. However, selecting this parameter after observing the failed backtest constitutes post-hoc data snooping. The 123.6% Sharpe sensitivity across the SD sweep (1.5–2.5) also means Gate 1 would reject even at SD=1.5 on the sensitivity criterion.

**Archive note:** Hypothesis preserved. The microstructure rationale (institutional VWAP benchmarking) is sound but requires true intraday VWAP data (Polygon/Alpaca 1-min). Revisit if the intraday data pipeline is built — at 5-min or 15-min granularity with true session VWAP, this hypothesis may generate adequate trade frequency and recover the institutional-reversion mechanism.

## Economic Rationale

VWAP (Volume Weighted Average Price) is the benchmark price most institutional investors use for execution quality measurement. Large mutual funds, pension funds, and algorithmic execution desks measure their fills against VWAP — meaning they are programmatically incentivized to trade near the VWAP level, creating a gravitational pull back to it when price deviates.

When price moves significantly above or below the session VWAP, several mechanisms act to restore it:
1. **Institutional rebalancing:** Execution algorithms constrained to achieve "better than VWAP" fills actively push price back toward VWAP when deviations occur
2. **Statistical mean reversion:** Price deviations driven by transient order flow imbalances (not fundamental news) revert as liquidity is restored
3. **VWAP as resistance/support:** Retail and systematic traders widely use VWAP as a reference, concentrating limit orders near ±1–2 SD bands

The specific edge in this hypothesis: price touching the **±2 SD VWAP band** on daily timeframe signals likely exhaustion of the deviation move, with follow-through probability to the downside (from upper band) or upside (from lower band). This is empirically documented in academic microstructure literature (Berkowitz, Logue & Noser 1988; Madhavan & Cheng 1997).

Crucially, **daily VWAP resets each session** — making this a fundamentally different signal structure from Bollinger Bands (H02), which use price-only SMA as the mean and do not reset. VWAP's volume-weighted nature means that high-volume days anchor the mean more firmly, reducing false signals on low-volume gap moves.

This strategy is most effective on highly liquid US equity ETFs (SPY, QQQ, IWM) where institutional VWAP execution is heavily present and where the mean-reversion mechanism is strongest.

## Entry/Exit Logic

**Entry signal:**
- Compute daily VWAP = Σ(typical_price × volume) / Σ(volume) for the session (or rolling multi-day anchored VWAP)
- Compute VWAP standard deviation bands at ±1 SD and ±2 SD
- **Long entry (fade upper band):** Price closes above VWAP +2 SD AND next-bar price crosses back below VWAP +2 SD (reversion confirmation)
- **Short entry (fade lower band, if allowed):** Price closes below VWAP −2 SD AND next-bar price crosses back above VWAP −2 SD

**Exit signal:**
- **Take profit:** Price returns to VWAP (±0.1 SD of center) — this is the natural reversion target
- **Stop loss:** Price moves further against entry by 1 SD (i.e., touches ±3 SD from center while in trade)
- **Time stop:** Exit after 5 trading days if neither target nor stop hit

**Holding period:** Swing (1–5 days)

## Market Regime Context

**Works best in:**
- Low-to-moderate volatility regimes where intraday trends are volume-confirmed (not gap-driven)
- Consolidating markets where VWAP is well-defined and stable
- High-liquidity sessions with balanced buy/sell volume

**Tends to fail in:**
- Macro event-driven gap moves (FOMC, earnings gaps) — price may not revert; VWAP is breached with fundamental justification
- Trending breakout environments where ±2 SD band breaks are legitimate continuation signals
- Low-volume days where VWAP is influenced by opening or closing print only

**Recommended regime gate:** Exclude entries within ±2 days of FOMC, major CPI, or NFP releases. Optionally add ATR filter: only trade reversion when ATR is in the lower 50th percentile of its 60-day distribution (low-volatility regime confirms noise-driven deviation).

## Alpha Decay

- **Signal half-life (days):** 3–5 (short — mean reversion to VWAP is fast when institutional execution is active)
- **Edge erosion rate:** fast (< 5 days)
- **Recommended max holding period:** 5 days (aligned with time stop)
- **Cost survival:** Yes — at a 3–5 day hold with a typical ETF round-trip cost of 0.05–0.10%, the edge survives if expected return per trade exceeds ~0.15%. Historical VWAP reversion from ±2 SD produces mean returns of 0.3–0.8% per trade on liquid ETFs (based on analogous Bollinger-band studies, adjusted for VWAP's volume-weighting advantage).
- **Estimated annualized IR (pre-cost):** With ~8–12 signals per year on SPY and expected return ~0.4% per trade → annualized return ~3–5%. Divided by realized vol of SPY (~15%), annualized IR ≈ 0.2–0.33. Pre-cost IR is marginal; the strategy likely passes only in higher-vol environments where the reversion amplitude is larger.
- **Notes:** Short-side VWAP reversion historically has stronger IC than long-side (confirmed by practitioner research: ExMon Academy 2026, "VWAP & Standard Deviations"). The strategy should be tested long-and-short, with short-side expected to carry more of the performance.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| VWAP SD threshold | 1.5 – 2.5 | Entry at 2.0 SD is standard; test sensitivity around this level |
| VWAP lookback type | Session-reset vs 5-day anchored | Session-reset captures institutional intraday flow; anchored VWAP captures multi-day mean |
| Take profit target | Return to center vs +0.5 SD | Full reversion vs partial — test both for risk/reward |
| Stop loss distance | 0.5 – 1.5 SD beyond entry | Controls max drawdown per trade |
| Universe | SPY, QQQ, IWM | Start with ETFs; expand to large-cap equities in Phase 2 |
| Macro event filter | ±1 day vs ±2 day exclusion window | Test sensitivity of performance around high-impact events |

## Capital and PDT Compatibility

- **Minimum capital required:** $5,000 (ETF-based, long-only)
- **PDT impact:** Moderate — with 1–5 day holds, some trades may be completed within a single day if price reverts quickly. If hold > 1 day is enforced via min-holding-period parameter, PDT risk is eliminated.
- **Position sizing:** 50–100% of portfolio in one ETF position for concentrated approach; 33% per position if three ETFs traded. Recommend 50% ($12,500 on $25K account) for initial test.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Unknown — this depends heavily on parameter choice and universe. VWAP strategies are not as well-documented in open-source backtests as Bollinger strategies. Expect IS Sharpe of 0.5–1.2 depending on the period tested. Pre-cost IR is marginal (est. 0.2–0.33), so Gate 1 pass is uncertain.
- **OOS persistence:** Likely — the economic mechanism (institutional VWAP benchmarking) is structural and not easily arbitraged. However, the short-side component may degrade if shorting ETFs becomes more crowded.
- **Walk-forward stability:** Moderate — the ±2 SD threshold is a stable industry standard, but exact performance depends on regime (works poorly in strong trending markets).
- **Sensitivity risk:** Medium — performance is sensitive to VWAP type (session-reset vs anchored) and the macro event filter. These are non-trivial choices.
- **Known overfitting risks:**
  - Time period selection matters greatly: VWAP reversion worked well 2014–2022; post-2022 inflationary regime has had more persistent directional moves
  - The choice of 2 SD threshold may look optimized in hindsight — sensitivity test required
  - Short-side requires margin; PDT implications may limit the short-side component at $25K

## TV Source Caveat

- **Original TV strategy name:** HYE Mean Reversion VWAP [Strategy]
- **TV author:** HYE0619
- **TV URL:** https://www.tradingview.com/script/WeAMGj9j/
- **TV ID:** WeAMGj9j
- **Apparent backtest window:** Not specified in TV script description; assume default TV window (2–5 years on daily bars)
- **Cherry-pick risk:** Medium — TV VWAP scripts typically display backtest results for a single ticker, usually SPY or a trending stock, over a cherry-picked favorable window. Independent IS/OOS backtest required on a cross-section of ETFs.
- **Crowding risk:** Medium — VWAP reversion is widely discussed but less systematically implemented than Bollinger strategies at retail level. Institutional crowding on the long side at VWAP −2 SD is documented but not extreme.
- **Novel signal insight vs H01–H11:** Structurally distinct from H02 (Bollinger Band mean reversion): Bollinger Bands use a price-SMA as the mean and a price-based standard deviation. VWAP uses a volume-weighted mean that resets daily and is directly tied to institutional execution benchmarks. H02 is statistical; H13 is microstructure-grounded. Also distinct from H06 (RSI reversal) because entry is anchored to a specific price level rather than an oscillator reading.

## References

- Berkowitz, S., Logue, D., Noser, E. (1988). "The Total Cost of Transactions on the NYSE." *Journal of Finance*
- Madhavan, A., Cheng, M. (1997). "In Search of Liquidity: Block Trades in the Upstairs and Downstairs Markets." *Review of Financial Studies*
- ExMon Academy (2026). "VWAP & Standard Deviations: The Only Honest Indicator in 2026."
- ChartSwatcher (2025). "6 Powerful VWAP Trading Strategies for 2025."
- TradingView source: https://www.tradingview.com/script/WeAMGj9j/ (HYE0619)
- Related: H02 (Bollinger Band mean reversion), H06 (RSI short-term reversal)
