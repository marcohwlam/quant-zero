# Ornstein-Uhlenbeck Mean Reversion Cloud

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** retired — Gate 1 FAIL (2026-03-16, QUA-162/QUA-211). Do not re-queue.

## Economic Rationale

The Ornstein-Uhlenbeck (OU) process is the canonical continuous-time model for mean-reverting dynamics, widely used in fixed income (interest rate models: Vasicek 1977), statistical arbitrage (pairs trading half-life estimation), and commodity pricing. Its discrete-time AR(1) analog is the simplest mean-reversion model: `x(t) = κ × (μ − x(t−1)) + σ × ε(t)`, where κ is the mean-reversion speed, μ is the long-run mean, and σ is the noise level.

The insight in this hypothesis: apply the OU model directly to individual equity price series (or log-price series) on a rolling window to estimate whether the current asset is exhibiting mean-reverting dynamics at a given moment. If the estimated κ (mean-reversion speed) is significantly positive and the current price deviation from the OU mean (μ̂) is large relative to σ̂, the model predicts a reversion opportunity.

This is **not pairs trading** (H04) — no second leg is needed. It is a single-asset, statistically-grounded mean-reversion signal that uses the same OU machinery but applies it directly to a univariate price series rather than a spread.

The edge mechanism has three parts:
1. **Regime detection:** OU κ estimate identifies when a security is in a mean-reverting regime (κ > 0, statistically significant) vs trending (κ ≈ 0 or negative). This allows the strategy to self-select into active periods.
2. **Signal generation:** OU deviation cloud generates entry/exit levels with explicit statistical confidence intervals rather than ad-hoc band multiples.
3. **Self-adjusting risk:** As OU parameters are re-estimated on each bar, the cloud widens during volatile periods (reducing false signal rate) and tightens during stable mean-reverting periods (increasing signal frequency).

Economic rationale for mean reversion in individual equities: temporary supply/demand imbalances (institutional block sales, index rebalancing, short-term momentum overshoot) create predictable reversion. The OU model estimates the speed and amplitude of this reversion, providing a principled entry threshold.

## Entry/Exit Logic

**Entry signal:**
- Fit OU model to rolling window (default: 60 bars of daily data) using OLS regression of `ΔX(t) = a + b × X(t−1) + ε` where `κ = −b`, `μ̂ = −a/b`, `σ̂ = StdDev(ε)`
- Compute OU half-life: `t_half = ln(2) / κ`
- **Long entry:** `X(t) < μ̂ − 1.5 × σ_ou` AND `κ > 0` (confirmed mean-reverting regime) AND `t_half < 30 days` (reversion expected within holding period)
- **Short entry (if allowed):** `X(t) > μ̂ + 1.5 × σ_ou` AND same regime conditions

**Exit signal:**
- **Take profit:** Price returns to OU mean `μ̂ ± 0.2 × σ_ou`
- **Stop loss:** Price extends deviation beyond `3.0 × σ_ou` from mean (OU model breakdown signal)
- **Regime exit:** If re-estimated κ drops below zero (regime shifts from mean-reverting to trending), exit immediately
- **Time stop:** Exit after `2 × t_half` days if no target or stop hit

**Holding period:** Swing (3–20 days, determined dynamically by estimated half-life)

## Market Regime Context

**Works best in:**
- Securities exhibiting confirmed mean-reverting dynamics (OU κ > 0, p-value < 0.05)
- Large-cap equities or ETFs with stable fundamental valuation anchors (sector ETFs, index ETFs)
- Low-to-moderate volatility environments where the OU mean is stable

**Tends to fail in:**
- Trending regimes where κ estimate collapses toward zero (strategy should self-detect and exit)
- High-information events (earnings announcements, M&A) that shift the fundamental mean permanently
- Illiquid securities where price impact of entry distorts the OU dynamics

**Built-in regime self-detection:** The continuous re-estimation of κ on each bar means the strategy natively identifies regime changes. When κ drops below significance threshold, the strategy stops generating new entries — this is a key differentiator from H02 and H06 which use static bands.

## Alpha Decay

- **Signal half-life (days):** Dynamically estimated via OU model — typical range 5–20 days for individual equities; 3–8 days for liquid ETFs
- **Edge erosion rate:** Moderate (5–20 days); adapts to estimated OU half-life
- **Recommended max holding period:** Dynamic — `2 × t_half_estimated` per trade; never exceed 30 days
- **Cost survival:** Yes — at the estimated IC of 0.03–0.05 and a 10-day average hold, the annualized IR of ~0.5 pre-cost gives sufficient margin above transaction costs for ETF-scale trades
- **Estimated annualized IR (pre-cost):** IC ≈ 0.04 (OU signals typically slightly higher than naive mean reversion due to regime conditioning); annualized IR ≈ `0.04 × √252 ≈ 0.63`. Regime conditioning (only trading when κ > 0) should improve effective IC by reducing entries in non-reverting regimes, potentially pushing effective IC to 0.05–0.07 and annualized IR to 0.8–1.1.
- **Notes:** This strategy has significantly lower crowding risk than Bollinger (H02) or RSI (H06) approaches because OU parameter fitting is computationally intensive and less accessible to retail traders. The academic backing is strong (OU process is the textbook mean-reversion model), reducing the risk that the edge exists only due to data snooping.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| OU lookback window | 30 – 90 bars | Trades off parameter stability vs responsiveness to regime change |
| Entry threshold (σ multiple) | 1.0 – 2.0 × σ_ou | Controls signal frequency vs quality |
| Stop loss threshold | 2.5 – 4.0 × σ_ou | Controls max loss per trade |
| Min κ significance | p < 0.05 vs p < 0.10 | Controls regime filter strictness |
| Max half-life filter | 10 – 30 days | Ensures reversion is fast enough to realize within hold period |
| Universe | SPY, QQQ, sector ETFs (XLE, XLF, XLK), large-cap individual stocks | ETFs first; add individual stocks in Phase 2 |

## Capital and PDT Compatibility

- **Minimum capital required:** $5,000 (ETF-based)
- **PDT impact:** Low — dynamic hold period keyed to estimated half-life (typically 5–20 days) means day trades are rare. Compatible with PDT rule.
- **Position sizing:** 50–75% of portfolio per position; reduce to 25–33% if multiple concurrent signals across different ETFs. For $25K account: $12,500–$18,750 per position.
- **Note:** The OU model re-estimation generates a natural Kelly fraction estimate (derived from expected return / variance of reversion), which could be used for principled position sizing in Phase 2.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Likely, if regime conditioning is effective. The OU model's native regime filter (κ > 0 requirement) should improve IS Sharpe above naive mean reversion strategies. Target IS Sharpe: 0.8–1.3.
- **OOS persistence:** Likely — the OU model is academically grounded and the regime detection mechanism prevents the strategy from trading in unfavorable environments. OOS degradation expected to be smaller than for static-band strategies (H02, H06).
- **Walk-forward stability:** High (relative to peers) — OU parameter re-estimation adapts to changing regime, reducing look-ahead sensitivity. The lookback window length is the primary sensitivity parameter.
- **Sensitivity risk:** Medium — performance is sensitive to the lookback window length (30 vs 90 bars can differ significantly) and the significance threshold for κ. These require robust sensitivity analysis.
- **Known overfitting risks:**
  - OU fitting can find spurious mean-reversion in any finite sample; the significance test for κ is critical
  - The specific σ multiple for entry (1.5) should be tested across a range rather than optimized
  - Testing on ETFs vs individual stocks produces very different results; scope must be pre-specified

## TV Source Caveat

- **Original TV strategy name:** Mean Reversion Cloud (Ornstein-Uhlenbeck) // AlgoFyre
- **TV author:** AlgoFyre
- **TV URL:** https://www.tradingview.com/script/39Nkoycz-Mean-Reversion-Cloud-Ornstein-Uhlenbeck-AlgoFyre/
- **TV ID:** 39Nkoycz
- **Apparent backtest window:** Not specified; the TV script is an indicator (not a full strategy backtest), so it provides visual clouds rather than performance statistics. This is appropriate for a component signal that requires independent backtesting.
- **Cherry-pick risk:** Low — the AlgoFyre OU cloud is an indicator/signal tool, not a strategy with cherry-picked backtest results. The underlying OU mathematics is well-established. Risk of cherry-picking is at the parameter level (lookback, σ multiple) during our own backtesting.
- **Crowding risk:** Low — OU process-based single-asset mean reversion is not widely implemented in retail systematic trading. Institutional stat-arb desks use OU for pairs trading, but direct single-asset OU signal trading is niche. Low crowding risk at $25K scale.
- **Novel signal insight vs H01–H11:** Genuinely distinct from all prior hypotheses. H02 uses static Bollinger Bands (SMA + price SD). H04 uses OU for pairs spread modeling. H06 uses RSI oscillator. H14 applies the OU model directly to single-asset price series with continuous parameter re-estimation, native regime detection (κ significance filter), and dynamically computed bands — a fundamentally different implementation of mean reversion theory with explicit statistical rigor. The regime self-detection capability is unique in the H01–H13 universe.

## References

- Vasicek, O. (1977). "An Equilibrium Characterization of the Term Structure." *Journal of Financial Economics*
- Avellaneda, M., Lee, J. (2010). "Statistical Arbitrage in the US Equities Market." *Quantitative Finance*
- Jurek, J., Yang, H. (2007). "Dynamic Portfolio Selection in Arbitrage." Harvard Working Paper
- Chan, E. (2013). *Algorithmic Trading: Winning Strategies and Their Rationale.* Wiley. (Chapter 2: Mean Reversion Strategies)
- TradingView source: https://www.tradingview.com/script/39Nkoycz-Mean-Reversion-Cloud-Ornstein-Uhlenbeck-AlgoFyre/ (AlgoFyre)
- Related: H02 (Bollinger Band MR), H04 (pairs trading cointegration), H06 (RSI short-term reversal)
