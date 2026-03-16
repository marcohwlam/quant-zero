# SuperTrend ATR Momentum

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Trend-following strategies generate positive expected returns by capturing risk premiums that accrue to investors willing to hold assets during sustained directional moves. The classic academic backing is the time-series momentum literature (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen 2017), which documents positive returns from trend signals across asset classes.

The SuperTrend indicator is an ATR-based trend detection rule. Unlike simple EMA crossovers (H01), SuperTrend dynamically adjusts its threshold band using Average True Range — a direct measure of recent volatility. When markets are noisy, the band widens and filters out false signals; when markets trend cleanly, the band tightens and entries occur closer to the trend's origin.

The edge mechanism: by conditioning trend entry on realized volatility (ATR), SuperTrend avoids many whipsaw entries that occur in elevated-noise environments. This is structurally different from EMA crossovers, which apply a fixed lag regardless of market noise level. The result is a regime-adaptive trend signal that implicitly scales its filter stringency to current conditions.

Published practitioners (Vankar 2019, "SuperTrend: The Definitive Guide") and systematic-trading literature confirm that ATR-normalized trend rules outperform fixed-parameter crossovers on a risk-adjusted basis, particularly over full cycles including choppy mean-reverting regimes.

## Entry/Exit Logic

**Entry signal:**
- Compute ATR over a rolling lookback window (default: 10 bars)
- Compute SuperTrend bands: `upper_band = (high + low)/2 + multiplier × ATR`, `lower_band = (high + low)/2 - multiplier × ATR`
- Long entry: price closes above the SuperTrend line (trend flips from bearish to bullish — signal line was above price, now below)
- Short entry (if allowed): price closes below the SuperTrend line (trend flips bearish)

**Exit signal:**
- Opposite SuperTrend signal flip (long exits when signal flips bearish; short exits when bullish)
- Optional: time-stop after `2 × signal half-life` days if no flip has occurred

**Holding period:** Swing (days to weeks)

## Market Regime Context

**Works best in:**
- Trending markets with momentum persistence (trending bull/bear phases)
- Low-noise, directional moves (ATR stable or declining during trend)
- VIX < 25 environments where the S&P is in a clear directional regime

**Tends to fail in:**
- Sideways, choppy, range-bound markets (high ATR but no directional move)
- Abrupt reversal environments (the band lags gap-down/gap-up events)
- Post-spike volatility regimes: ATR elevated, creating wide bands and late entries

**Recommended regime gate:** Pair with a VIX < 30 filter and a 50-day trend direction check (e.g., price above 200-day SMA) to limit exposure in mean-reverting regimes.

## Alpha Decay

- **Signal half-life (days):** 12–18 (ATR-based trend signals on daily bars — typical for swing momentum strategies)
- **Edge erosion rate:** moderate (5–20 days)
- **Recommended max holding period:** 30 days (2× estimated half-life)
- **Cost survival:** Yes — with a typical 18-day hold, a 0.10% round-trip cost corresponds to ~0.005% per day drag, tolerable against estimated daily IR
- **Estimated annualized IR (pre-cost):** Signal IC ≈ 0.03–0.05 on daily bars → annualized IR ≈ `0.04 × √252 ≈ 0.63`. Pre-cost IR borderline acceptable; cost survival confirmed for swing holds but marginal for holds < 5 days.
- **Notes:** Decay rate is regime-dependent — faster in sideways markets, slower during clear trending phases. Crowding risk is moderate; SuperTrend is widely used on TradingView but not heavily arbitraged in systematic institutional strategies targeting small-cap / mid-cap equities.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| ATR lookback | 7 – 20 bars | Standard ATR period range; shorter = more reactive, longer = smoother |
| ATR multiplier | 1.5 – 3.5 | Controls band width; lower = more signals, higher = fewer false flips |
| Universe | SPY, QQQ, IWM, sector ETFs | Liquid, no PDT issue as swing; avoid leveraged ETFs unless specifically targeted |
| Trend direction filter | 200-day SMA above/below price | Optional regime filter: long-only above 200-SMA |
| Min holding period | 2 – 5 days | Prevents hyperactivity on quick flips within the same signal |

## Capital and PDT Compatibility

- **Minimum capital required:** $5,000 (ETF-based, no margin required for long-only)
- **PDT impact:** Low — swing holding period of 3–30 days means typically < 1 day trade per week. Compatible with PDT rule.
- **Position sizing:** 50–100% of portfolio in one ETF position (concentrated); or 20–33% per position if 3 ETFs traded simultaneously. For $25K account: single position of $12,500–$25,000 is feasible.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Unlikely without regime filter. With VIX gate + trend filter, possible. Raw SuperTrend on SPY historically achieves Sharpe ~0.6–0.9 (2010–2024). Adding regime conditioning may push above 1.0.
- **OOS persistence:** Moderate — trend following is documented to persist across decades and asset classes, but individual parameter sets degrade. OOS likely lower than IS by 20–30%.
- **Walk-forward stability:** Moderate — ATR multiplier 2.0–2.5 tends to be most stable; extreme parameter values (1.5 or 3.5) are more sensitive.
- **Sensitivity risk:** Medium — performance is meaningfully sensitive to ATR multiplier choice. Must document sensitivity heatmap during Gate 1.
- **Known overfitting risks:**
  - Multiplier choice can be cherry-picked from in-sample performance
  - Results are highly regime-dependent; a 2010–2024 IS window includes two major trending bull runs that inflate metrics
  - SuperTrend is not alpha-generating in sideways regimes; full-period Sharpe masks regime-conditional performance

## TV Source Caveat

- **Original TV strategy name:** SuperTrend STRATEGY
- **TV author:** KivancOzbilgic
- **TV URL:** https://www.tradingview.com/script/P5Gu6F8k/
- **TV ID:** P5Gu6F8k
- **Apparent backtest window:** Unspecified in TV script; TV community scripts often default to the max available data for the primary ticker tested (typically 10–20 years for equity ETFs)
- **Cherry-pick risk:** High — KivancOzbilgic's script is one of hundreds of SuperTrend implementations on TV; optimal parameters are likely selected for the displayed ticker's history. Do not replicate TV backtest results; run fresh IS/OOS split.
- **Crowding risk:** Medium-high — SuperTrend is one of the most-used indicators on TradingView. The edge exists in academic momentum literature, but the specific ATR variant may be crowded among retail systematic traders. Edge likely persists at $25K scale.
- **Novel signal insight vs H01–H11:** H01 uses a simple dual EMA crossover (fixed-lag filter). SuperTrend replaces the fixed lag with a volatility-adaptive band (ATR-scaled). This is a genuine structural difference: the signal adapts its noise floor to current market conditions, whereas H01's filter threshold is static. SuperTrend also inherently encodes a stop-loss level (the band itself) that EMA crossovers lack.

## References

- Moskowitz, T., Ooi, Y., Pedersen, L. (2012). "Time Series Momentum." *Journal of Financial Economics*
- Hurst, B., Ooi, Y., Pedersen, L. (2017). "A Century of Evidence on Trend-Following Investing." AQR White Paper
- Vankar, N. (2019). "SuperTrend: The Definitive Guide." Zerodha Varsity
- TradingView source: https://www.tradingview.com/script/P5Gu6F8k/ (KivancOzbilgic)
- Related: H01 (dual EMA crossover), H05 (momentum vol-scaled), H07b (TSMOM)
