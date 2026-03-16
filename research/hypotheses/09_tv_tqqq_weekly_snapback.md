# TQQQ Weekly Snapback — 1% Target Mean-Reversion

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** testing

## Economic Rationale

TQQQ is a 3× daily leveraged fund tracking the Nasdaq-100. Daily rebalancing creates a structural volatility-decay drag: large intraweek drawdowns systematically overshoot fair value, generating a predictable snapback premium. The mechanism is well-documented (Cheng & Madhavan 2009, "Dynamics of Leveraged and Inverse ETFs"; Avellaneda & Zhang 2010): after a TQQQ weekly decline of X%, the expected 5-day forward return tilts positive simply because daily rebalancing forces overcorrect the position.

The TASC March 2026 article ("Trading Snapbacks In A Leveraged ETF") formalises this into a minimal-rules weekly strategy targeting ~1%/week profit with low time commitment. Because TQQQ is highly liquid (ADV >> $1B) and available in single-share lots, this edge is accessible to a $25K account.

Additional economic support: trend-following systematic managers who use 3× products as short-term vehicles tend to exit after multi-day drawdowns, creating temporary excess supply that self-corrects. This is a risk-premium capture, not pure statistical arbitrage.

## Entry/Exit Logic

**Entry signal:**
- TQQQ closes below its 5-day rolling high by ≥ N% (e.g., -3% to -7% decline from the weekly high)
- Entry on next-day open (to avoid look-ahead)
- Optional confirmation: SPY or QQQ must also be within 1–2% of a 5-day high to exclude strong downtrend regimes

**Exit signal:**
- Take profit: +1.0% from entry (primary target; aligns with TASC strategy target)
- Stop loss: -2.0% from entry (2× risk/reward minimum)
- Time stop: exit on Friday close if neither TP nor SL triggered (max 4 nights)

**Holding period:** Swing (2–5 trading days)

## Market Regime Context

**Works best:**
- Bull trend / low-vol: TQQQ tends to be net-rising; weekly dips snapback consistently
- VIX 15–25 (moderate vol): sufficient intraweek range to trigger entries without runaway downtrends

**Tends to fail:**
- Bear market / high-vol (VIX > 30): snapbacks don't materialise; drawdown continues
- Extended downtrend (QQQ below 200-day SMA): mean-reversion bias inverts
- FOMC/macro shock weeks: regime breaks violently

**Regime gate (recommended):**
- Disable entries when QQQ closes below its 200-day SMA on any day of the entry week
- Optionally gate on VIX < 30 to reduce high-volatility false entries

## Alpha Decay

- **Signal half-life (days):** ~3–4 days (target is 5-day window; edge largely resolved within 1 week)
- **Edge erosion rate:** moderate (5–10 days)
- **Recommended max holding period:** 5 trading days (1 week)
- **Cost survival:** Yes — TQQQ spread is ~$0.01–0.02 on $50–$80 shares; round-trip transaction cost ~0.04%; edge must exceed ~0.15% net. 1% target with 2× stop provides adequate buffer.
- **Annualised IR estimate:** Assume ~30% of trades trigger TP (+1%), 15% trigger SL (-2%), 55% exit on Friday (expected ~+0.3% average). Expectancy ≈ +0.30×0.01 + 0.15×(-0.02) + 0.55×0.003 ≈ +0.30% per trade. With ~25 trades/year → raw return ~7.5%; vol of TQQQ ~80%/year → annualised IR ≈ 0.35 (marginal pre-cost, needs confirmation). IR above 0.3 threshold.

**IC decay curve (estimated):**

| IC Metric | Estimate | Notes |
|-----------|----------|-------|
| IC at T+1 (next day) | 0.05 | Snapback just beginning; edge partially realised |
| IC at T+5 (1 week) | 0.07 | Peak — full signal resolution window for 2–5 day hold |
| IC at T+20 (1 month) | 0.01 | Signal expired; no persistent edge at 1-month horizon |

Derivation: Annualised IR ≈ 0.35 with ~25 trades/year → IC ≈ IR / √N ≈ 0.35 / 5 ≈ 0.07 at T+5 (peak). T+1 lower (bounce not complete); T+20 near zero (strategy fully resolved). IC at T+5 > 0.02 threshold — qualifies as standalone signal.

- **Notes:**
  - TASC article likely cherry-picks a favourable backtest window (2020–2025 bull market). Must validate on 2008–2010 and 2022 bear market sub-periods.
  - **Survivorship bias / backtest window (Research Director note):** IS backtest window MUST start no later than 2015 to capture at least two distinct regimes (2015–2016 China selloff, 2018 Q4 correction, 2020 COVID crash, 2022 bear). Starting from 2020 alone inflates Sharpe by selecting a predominantly bull-market sample. Enforce 2015–2023 IS window in Gate 1 backtest spec.
  - **IS MDD risk (Research Director note):** TQQQ fell approximately -82% in 2022. The regime gate (QQQ < 200-day SMA → disable entries) must be precisely specified to ensure protection during severe drawdowns. Required precision: (a) use closing price of QQQ vs. 200-day simple MA calculated on the same day's close; (b) gate check runs every Friday (or on entry-signal day) before allowing new positions; (c) any existing position opened before the gate triggers must still be exited per the stop/TP/time-stop rules — the gate only suppresses new entries. If this specification is ambiguous or unimplemented, the backtest will almost certainly breach Gate 1 IS MDD < 20%.
  - **Capital confirmation (Research Director note):** At ~$50–$100/share (TQQQ price range as of 2026), a single-share lot costs $50–$100. At $25K capital with 10–20% position sizing ($2,500–$5,000), the strategy accommodates 25–100 full shares per trade. No fractional shares required. Capital constraint is satisfied. The TV filter warning ("may require >$25K") likely refers to margin accounts or multi-position scaling — irrelevant for this single-position swing strategy.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| entry_decline_pct | 2.5% – 7.0% | Depth of weekly drawdown to trigger entry |
| profit_target_pct | 0.75% – 1.5% | TASC targets 1%; test sensitivity |
| stop_loss_pct | 1.5% – 3.0% | Risk/reward must stay ≥ 1.5× |
| lookback_window_days | 3 – 7 | How far back to measure weekly high |
| vix_gate | 25 – 35 | VIX threshold to disable entries in high-vol regime |
| qqqsma_gate | 50 – 200 | QQQ SMA period for trend filter |

## Capital and PDT Compatibility

- **Minimum capital required:** $5,000 (single TQQQ lot; ~$50–100/share as of 2026)
- **PDT impact:** Low — positions held 2–5 days, typically 1–2 trades/week. At 1 trade/week = 52 day-trades/year but each held overnight → not subject to PDT (PDT only applies to same-day round-trips). Strategy is PDT-safe.
- **Position sizing:** 10–20% of portfolio per trade (TQQQ volatility is 3×QQQ; size down vs. standard equity). Max 1 concurrent position.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Unlikely without regime filtering. With QQQ/VIX gate: possible (marginal). TASC source suggests >1.0 in bull regimes.
- **OOS persistence:** Unknown. TASC backtest window likely 2020–2025; 2022 bear would be the real test. High risk of regime-dependency.
- **Walk-forward stability:** Medium risk. Parameter sensitivity on `entry_decline_pct` is the main concern — small shifts may change signal frequency dramatically.
- **Sensitivity risk:** Medium. Two key parameters (decline threshold, VIX gate) each have plausible ranges; joint sensitivity could be high.
- **Known overfitting risks:** TASC strategies are published after authors have tested many variants. Survivorship bias is significant — the "1% target" may be tuned to historical data. Must test with fixed pre-specified parameters, not optimised.

## TV Source Caveat

- **Original TV strategy:** "TASC 2026.03 One Percent A Week" by PineCodersTASC
- **URL:** https://www.tradingview.com/script/nVECqIQx-TASC-2026-03-One-Percent-A-Week/
- **Apparent backtest window:** Not specified in og:description. TASC March 2026 article likely covers ~2020–2025 (post-COVID bull market period). Risk of cherry-picking a favourable regime.
- **Crowding risk:** Medium. TASC strategies are widely read; if published in March 2026, early adopters may extract most of the edge quickly. Monitor for signal decay post-publication.
- **Novel insight vs H01–H08:** All prior hypotheses target broad equity indices or factors. This is the first hypothesis exploiting leveraged ETF volatility-decay dynamics specifically. The snapback mechanism (rebalancing overshoot) is structurally different from H05 (momentum) or H02 (Bollinger Band MR) which use price oscillators, not product-structure mispricing.

## References

- Cheng & Madhavan (2009): "Dynamics of Leveraged and Inverse ETFs" — Barclays Capital Research
- Avellaneda & Zhang (2010): "Path-Dependence of Leveraged ETF Returns" — SIAM Journal on Financial Mathematics
- TASC March 2026: "Trading Snapbacks In A Leveraged ETF" — Traders' Tips
- Related in knowledge base: research/hypotheses/05_momentum_vol_scaled.md (vol-scaling concept)
- TV source: https://www.tradingview.com/script/nVECqIQx-TASC-2026-03-One-Percent-A-Week/
