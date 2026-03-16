# H19: VIX-Percentile Volatility-Targeting SPY

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Volatility targeting exploits the well-documented negative relationship between realized equity volatility and forward returns: periods of high volatility (fear spikes) tend to be followed by mean-reverting returns, while low-volatility environments support trend continuation. By scaling SPY position size inversely to the prevailing VIX regime, the strategy:

1. **Captures the equity risk premium more efficiently**: Moreira & Muir (2017, Journal of Finance) showed that scaling equity exposure by the inverse of lagged realized variance improves Sharpe ratio from ~0.40 to ~0.73 for the US market without changing the fundamental long-equity exposure.
2. **Exploits VIX mean reversion**: VIX is a mean-reverting process. After spikes above historical percentile highs, VIX tends to revert, creating a window where reduced equity exposure avoids the initial drawdown while re-entry on VIX normalization captures the rebound.
3. **Addresses the CAPM anomaly**: High-beta / high-volatility stocks have historically underperformed on a risk-adjusted basis (Baker et al. 2011 low-volatility anomaly). Volatility targeting applies this insight at the portfolio level.

The **VIX percentile** approach (vs raw VIX level) adjusts for secular shifts in the VIX baseline — a VIX of 20 in 2010 has different regime implications than a VIX of 20 in 2022. The rolling 252-day percentile normalizes this.

**Evidence base:** Moreira & Muir (2017) "Volatility-Managed Portfolios" JF; Asvanunt, Clarke, De Silva (2015) on volatility targeting; RobotWealth volatility targeting cheat sheet; Tradewell.app VIX-based strategy backtests.

## Entry/Exit Logic

**Universe:** SPY (primary), VIX daily close (available via yfinance ticker `^VIX`).

**Weekly VIX percentile signal (every Friday close):**
- Compute `vix_pct = percentile_rank(VIX, lookback=252)` — where is today's VIX within the past 252 trading days?
- Map to 3-tier allocation:

| VIX Percentile | Regime | SPY Allocation |
|---|---|---|
| < 40th pct | Low vol (calm) | 100% SPY |
| 40th–70th pct | Elevated vol | 60% SPY, 40% cash |
| > 70th pct | High fear | 0% SPY (cash) |

**Entry signal:**
- Enter / increase SPY when `vix_pct` drops below current tier boundary (downward crossing)
- Re-enter 100% when `vix_pct < 40th pct` after a high-vol period

**Exit signal:**
- Reduce to 60% SPY when `vix_pct` crosses above 40th percentile
- Exit to cash when `vix_pct` crosses above 70th percentile

**Minimum hold between rebalances:** 5 trading days (weekly rebalancing) to avoid whipsaw and PDT complications.

**Holding period:** Weekly swing; re-evaluated each Friday. Typical equity hold: 2–6 weeks. Cash holds: 1–8 weeks (duration of fear regime).

**PDT note:** All position changes are between SPY and cash with weekly minimum hold. No fractional-day trades. PDT-safe.

## Market Regime Context

**Works best:**
- Clear VIX trending regimes: sustained low-vol bull markets (VIX below its annual median) where 100% allocation gives maximum equity exposure
- VIX spike-and-recovery events (e.g., Feb 2018 XIV implosion, Dec 2018 selloff): strategy exits near the spike, re-enters after normalization
- 2019 goldilocks environment (VIX mostly < 20): 100% SPY holding, minimum churn

**Tends to fail:**
- Extended fear regimes (2022): VIX stays elevated (> 70th percentile) for months → extended cash hold → misses any dead-cat bounces in equity
- VIX "false spikes" that immediately reverse (strategy exits and misses the intraday recovery)
- Rapid VIX mean-reversion (< 5 days): weekly rebalancing cannot react fast enough; position is already at full allocation when VIX has already normalized

**Pause trigger:** No explicit pause (the percentile tiers ARE the regime conditioning). If SPY shows positive momentum while VIX is in the high-fear tier, remain in cash — do not override the VIX signal.

## Alpha Decay

- **Signal half-life (days):** 10–15 days (VIX regime persistence; a VIX spike typically lasts 5–20 days before mean-reverting)
- **Edge erosion rate:** Moderate (5–20 days)
- **Recommended max holding period:** 15 trading days (3 weeks) before reassessing position tier; weekly rebalancing auto-handles this
- **Cost survival:** Yes. Position changes are infrequent (1–2 tier changes per fear episode). With SPY commissions of ~$0.50–$1.00 round-trip and typical 1–3% VIX-regime signal premium, costs are well-covered.
- **Annualized IR estimate:** Moreira & Muir (2017) report IR improvement from 0.40 to 0.73 for the US market using realized variance. With VIX percentile regime tiers instead of continuous scaling, estimated IR: 0.4–0.7. Post-cost IR estimate: 0.35–0.60. Passes the 0.3 warning floor; borderline above disqualifier floor of 0.1.
- **Notes:** 2022 is the stress test for this strategy as well. Extended cash holding during 2022 reduces drawdown but forfeits positive equity returns on dead-cat bounces. The 3-tier design (vs binary exit) mitigates this by maintaining 60% equity in elevated-but-not-extreme VIX environments.

## TV Source Caveat

- **Original TV indicator:** "TTP VIX Spy" by TheTradingParrot ([Rv3pibXO](https://www.tradingview.com/script/Rv3pibXO-TTP-VIX-Spy/))
- **TV backtest window:** Not documented by author; indicator-only (not a strategy backtest). Cherry-pick risk assessment is via the TV indicator's own discovery window.
- **Cherry-pick risk:** LOW for the underlying mechanism. Volatility targeting / VIX regime gating has extensive independent validation in academic literature (Moreira & Muir 2017, Baker et al. 2011). The TV indicator is the inspiration for the visualization, not the source of the signal validity.
- **Crowding risk:** LOW-MEDIUM. Institutional risk-parity funds (Bridgewater All Weather, AQR Risk Parity) use volatility targeting at macro scale, but their rebalancing happens at monthly/quarterly intervals. Weekly VIX percentile rebalancing at $25K retail scale occupies a different execution window.
- **Novel signal insight vs H01–H17:** No prior hypothesis in the pipeline uses VIX as the PRIMARY signal generator (vs a filter/gate):
  - H05, H12: use ATR for volatility scaling within a momentum strategy — VIX here REPLACES the directional momentum signal entirely
  - H16: used vol filter but as a pass/fail gate, not a continuous tiered allocation
  - H19 is the first **volatility-as-signal** (not just volatility-as-filter) approach in the pipeline

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `vix_lookback_days` | 126, 252, 504 | Rolling window for VIX percentile; 252 = 1 year standard |
| `tier1_threshold` | 30th, 40th, 50th pct | Low/elevated vol boundary |
| `tier2_threshold` | 60th, 70th, 80th pct | Elevated/high-fear boundary |
| `neutral_allocation_pct` | 40%, 50%, 60% | SPY allocation in elevated-vol tier |
| `rebalance_frequency` | weekly (5d), 10d | Weekly = more responsive; 10d = fewer whipsaws |

## IS Trade Count Pre-Flight Check

- **IS period:** 2018–2022 (4 years)
- **Trade count estimate:** Based on VIX percentile history in this period:
  - 2018: ~3–4 tier transitions (Feb spike, Dec spike, normalizations)
  - 2019: ~1–2 transitions (mostly low-vol)
  - 2020: ~6–8 transitions (COVID spike, multiple recovery phases)
  - 2021: ~2–3 transitions
  - 2022: ~8–10 transitions (multiple VIX excursions between 60th–80th pct)
  - Total estimated transitions: ~20–27/year across all tier boundaries
- **IS trades (counting each tier change as 1 trade leg):** ~20–27/year × 4 years = 80–108 trades
- **IS trades / 4 years:** 20–27 trades/year
- **Threshold check:** 20–27 vs threshold of 30/year → **BORDERLINE FAIL AT LOWER END**
- **⚠ Pre-flight flag:** With conservative tier thresholds (40th/70th pct), IS trades/year may fall to 18–22 during low-volatility sub-periods. This may fall below the 30/year minimum. **Recommend testing with tighter thresholds (30th/60th pct) to increase transition frequency before Engineering Director finalizes parameters.** If IS trades/year cannot reach 30 under reasonable parameters, Engineering Director should flag this back to Research Director for disposition.
- **Mitigation:** Add a secondary signal — e.g., VIX 10-day MA crossover — to increase minor entry/exit frequency while keeping the primary tier structure intact.

## Capital and PDT Compatibility

- **Minimum capital required:** ~$5,000 (SPY fractional shares not required; 10+ shares at ~$450–550/share)
- **PDT impact:** None. Weekly rebalancing means all positions held ≥ 5 days. Cash is not a "trade" in PDT terms. PDT-safe.
- **Position sizing:** 0%, 60%, or 100% of portfolio in SPY based on VIX tier. No leverage. No short exposure.
- **Concurrent positions:** 1 position (SPY) at varying allocation.

## Gate 1 Outlook

Candid assessment:

- **IS Sharpe > 1.0:** **Unlikely without parameter tuning.** Moreira & Muir report IS Sharpe improvement to ~0.73 with continuous volatility scaling; tiered approach may reach 0.7–0.9 IS Sharpe. Gate 1 threshold of 1.0 is likely out of reach unless the tier boundaries are precisely calibrated in-sample — which creates overfitting risk.
- **OOS persistence:** **Likely moderate.** VIX regime persistence is a structural feature of equity markets. However, post-2022 low-vol environment (2023–2025 bull market) means the strategy mostly holds 100% SPY, generating no alpha vs buy-and-hold. OOS Sharpe may equal or only modestly exceed buy-and-hold.
- **Walk-forward stability:** **Moderate.** Strategy degrades in environments where VIX percentile thresholds do not accurately identify regime transitions (e.g., slow-creep bear markets without VIX spikes).
- **Sensitivity risk:** **Medium.** Results are sensitive to percentile tier thresholds (±10th percentile can meaningfully change trade count and allocation time). Engineering Director must document sensitivity heatmap.
- **Known overfitting risks:**
  - Tier boundaries chosen in-sample to optimally exclude 2022 drawdown (the most likely overfitting mode)
  - 252-day VIX lookback may require > 252 days of warmup before first valid signal — reduces usable IS history
  - IS trade count borderline at lower parameter ranges; risk of selecting parameters that artificially inflate Sharpe by reducing trade frequency

## References

- Moreira, A. & Muir, T. (2017). "Volatility-Managed Portfolios." *Journal of Finance*, 72(4), 1611–1644.
- Baker, M., Bradley, B., & Wurgler, J. (2011). "Benchmarks as Limits to Arbitrage: Understanding the Low-Volatility Anomaly." *Financial Analysts Journal*, 67(1).
- Asvanunt, A., Clarke, R., De Silva, H. (2015). "Volatility Targeting in Practice." *Journal of Portfolio Management*.
- RobotWealth. "TradingView Volatility Targeting Tools Cheat Sheet." https://robotwealth.com/tradingview-volatility-targeting-tools-cheat-sheet/
- QuantifiedStrategies. "Trading SPY and S&P 500 Using VIX." https://www.quantifiedstrategies.com/using-vix-to-trade-spy-and-sp-500/
- TradingView indicator: Rv3pibXO (TheTradingParrot). https://www.tradingview.com/script/Rv3pibXO-TTP-VIX-Spy/
- Related hypotheses: H05 (momentum + vol scaled — FAILED Gate 1), H12 (SuperTrend ATR momentum — in testing)
