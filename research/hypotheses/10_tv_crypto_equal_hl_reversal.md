# Crypto Equal High/Low Liquidity Reversal (ATR-Scaled)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** crypto
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Equal highs (EQH) and equal lows (EQL) — horizontal price zones where 2+ swing points cluster within a tolerance band — represent institutional liquidity pools. At these levels, retail stop-loss orders accumulate densely. Market makers and institutional participants ("smart money") engineer price excursions above/below these zones to trigger stops, collect liquidity, and then reverse.

This concept is formalised in Smart Money Concepts (SMC) literature (e.g., Inner Circle Trader methodology, widely documented in practitioner communities since ~2018). The edge derives from:

1. **Stop-clustering mechanics:** Retail traders systematically place stops just beyond prior swing highs/lows. When multiple swing points align at the same price level (EQH/EQL), the stop density is disproportionately high.
2. **Institutional absorption:** Once stops are triggered, institutional liquidity absorbs the resulting market orders. Price reversal follows as the temporary liquidity event exhausts.
3. **Crypto applicability:** Crypto markets exhibit stronger retail participation and more predictable stop-clustering than mature equity markets (lower institutional sophistication among retail participants, 24/7 trading reduces mean-reversion overnight holding costs).

ATR-scaled entries/exits account for the high cross-asset volatility variation in crypto (BTC vs. altcoins) without requiring separate parameter sets.

The strategy is **not** equivalent to H02 (Bollinger Band MR) or H06 (RSI Reversal): those use statistical oscillators; this uses structural price geometry (liquidity zone identification), which is mechanistically distinct.

## Entry/Exit Logic

**Entry signal:**
- Scan lookback period (N bars) for equal highs: `count(highs within EQH_level ± ATR × tolerance_mult) >= 2`
- Scan lookback period for equal lows: same logic on lows
- **Long entry (EQL hunt):** Price trades below the confirmed EQL zone (ATR-defined band), closes back above it within 2 bars → enter long on close of the recovery bar
- **Short entry (EQH hunt):** Price trades above the confirmed EQH zone, closes back below it within 2 bars → enter short on close of the recovery bar

**Exit signal:**
- Take profit: prior EQH (for long) or prior EQL (for short) — structural target
- Stop loss: 1.5× ATR(14) beyond the breached level
- Time stop: exit after N_bars_max bars if neither target nor stop hit

**Holding period:** Swing (2–7 trading days on daily bars)

## Market Regime Context

**Works best:**
- Range-bound or mild-trend crypto markets
- BTC/ETH on daily bars where structural levels are respected
- Moderate volatility (ATR < 5% of price per day) — sufficient range without chaos

**Tends to fail:**
- Strong trending markets (bull runs / capitulation): EQL zones are broken without reversal
- Extreme high-vol events (CME gap fills, liquidation cascades): price blows through zones
- Low-liquidity altcoins: EQH/EQL zones are less meaningful; thin order books distort patterns

**Regime gate:**
- Disable long entries when BTC's 20-day ROC < -15% (capitulation filter)
- Consider BTC dominance as a secondary regime indicator

## Alpha Decay

- **Signal half-life (days):** ~4–6 days (crypto mean-reversion typically resolves within 1–2 weeks)
- **Edge erosion rate:** moderate (5–10 days)
- **Recommended max holding period:** 7 trading days
- **Cost survival:** Yes — BTC/ETH on major exchanges: maker fee ~0.01–0.04%, taker ~0.04–0.06%. Round-trip cost ≈ 0.10–0.15%. Minimum viable profit target should be 3× ATR × entry_price which typically exceeds 1% on daily bars. Edge survives costs given the structural trade construct.
- **Annualised IR estimate:** Conservative IC estimate of 0.04 on daily bars (liquidity-level signals have moderate but non-trivial predictive value in crypto). With 2–3% average move per trade and ~40 signals/year → approximate annualised return 3–5%; crypto daily vol ~50–70%/year → IR ≈ 0.25–0.35. Marginal. Edge will need to show higher IC in backtesting to reach IR > 0.3.
- **Notes:** SMC-based approaches became widely known by 2022–2023. Crowding may have reduced edge in BTC/ETH. Consider testing on ETH, SOL, or BNB where institutional sophistication is lower.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| lookback_n_bars | 10 – 30 | How far back to search for EQH/EQL formation |
| tolerance_mult | 0.1 – 0.5 | ATR multiplier defining "equal" price band |
| atr_period | 10 – 20 | ATR lookback for volatility scaling |
| stop_atr_mult | 1.0 – 2.5 | Stop distance in ATR units beyond the zone |
| confirmation_bars | 1 – 3 | Recovery candles required after zone breach |
| min_touches | 2 – 3 | Minimum swing points to confirm EQH/EQL zone |

## Capital and PDT Compatibility

- **Minimum capital required:** $1,000 (crypto — no PDT; fractional positions available on most exchanges)
- **PDT impact:** None — crypto markets have no PDT rule. Swing holds of 2–7 days.
- **Position sizing:** 5–15% of portfolio per trade (crypto volatility is high; size small). Max 2 concurrent positions across different assets.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Uncertain. SMC/liquidity concepts perform inconsistently across backtests; depends heavily on parameter choices. The structural edge is plausible but may not yield Sharpe > 1.0 without regime filtering.
- **OOS persistence:** Medium risk. Crypto mean-reversion edges are well-known and may be crowded. 2022–2023 bear market is a key OOS test period.
- **Walk-forward stability:** Medium risk. `lookback_n_bars` and `tolerance_mult` are the most parameter-sensitive variables.
- **Sensitivity risk:** Medium. Two key sensitivity parameters; need to confirm edge is not localised to a narrow parameter window.
- **Known overfitting risks:** SMC strategies are popular on TradingView — many variants are published with cherry-picked parameters. The TV source (same author as the equities EQL/EQH version) may be optimised for recent crypto bull periods.

## TV Source Caveat

- **Original TV strategy:** "Anti- Equal prices ATR" by TedDibiase21
- **URL:** https://www.tradingview.com/script/YhkzTWJE-Anti-Equal-prices-ATR/
- **Apparent backtest window:** Not disclosed in metadata. Likely optimised for 2021–2025 crypto range (both bull and bear included). Sub-period analysis required to identify regime-dependency.
- **Crowding risk:** Medium. SMC/ICT concepts are among the most popular trading frameworks on TradingView by 2024–2026. If widely followed, EQL/EQH levels may be self-fulfilling or self-defeating depending on participation.
- **Novel insight vs H01–H08:** H08 (Crypto Momentum BTC/ETH) is trend-following. This strategy is counter-trend and uses structural price geometry rather than technical oscillators. The liquidity-pool concept is mechanistically distinct from H06 (RSI reversal) and H08. First crypto mean-reversion hypothesis in the pipeline.

## References

- Inner Circle Trader (ICT) methodology: widely documented on YouTube/TradingView (~2018–2024) — SMC framework for institutional order flow
- Kuepper, J. (2021): "Smart Money Concepts Explained" — Investopedia (accessible overview)
- Williams, L. (2001): "Long-Term Secrets to Short-Term Trading" — discussions of stop-hunting mechanics
- Related in knowledge base: research/hypotheses/06_rsi_short_term_reversal.md (reversal logic), research/hypotheses/08_crypto_momentum_btc_eth.md (crypto asset class)
- TV source: https://www.tradingview.com/script/YhkzTWJE-Anti-Equal-prices-ATR/
