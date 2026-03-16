# Market Regime Classification — March 2026

**Updated:** 2026-03-15
**Author:** Market Regime Agent
**Task:** QUA-35

---

## Classification

- **Trend:** mildly-trending (long-term uptrend intact, near-term correction underway)
- **Volatility:** high-vol (VIX 27.19, spiked from 90-day baseline of 18.4)
- **Momentum:** risk-on (12-1m SPY momentum = +25.0%, canonical signal positive)
- **Liquidity:** liquid (VIX < 40, realized vol below implied vol — no systemic stress)

**Summary label:** `mildly-trending / high-vol / risk-on (transitioning) / liquid`

---

## Key Indicators

| Indicator | Value | Signal |
|---|---|---|
| VIX (current) | 27.19 | high-vol (>25) |
| VIX 30d avg | 21.05 | normal-vol baseline |
| VIX 90d avg | 18.39 | low-to-normal baseline |
| VIX 30d high | 29.49 | approaching crisis-adjacent zone |
| SPY vs 200d SMA | +0.90% | mildly above trend — barely holding |
| 200d SMA 20d slope | +1.61% | upward-sloping — long-term trend intact |
| SPY 12-1m momentum | +25.0% | risk-on (strong trailing momentum) |
| SPY 1m return | -4.29% | near-term correction |
| SPY 3m return | -3.62% | near-term correction |
| Hurst exponent (60d) | 0.732 | strongly trending (reflects trailing uptrend) |
| SPY Realized Vol 21d (ann) | 12.3% | low realized vol vs high implied — vol premium elevated |
| Sectors above 50d SMA | 4/11 | bearish breadth (only defensives: XLE, XLP, XLU, XLRE) |
| TLT 1m return | -1.40% | no flight to safety in bonds |
| GLD 1m return | -1.45% | gold also weak |
| BTC 1m return | +4.72% | mixed risk appetite signal |

---

## Regime Narrative

As of 2026-03-15, the market is in a **risk-off correction within a longer-term uptrend**. The structure is:

**Longer-term (bullish, intact):**
- SPY is above its 200-day SMA (barely, +0.90%) — the secular trend is technically unbroken
- The 200-day SMA slope is positive (+1.61% over 20 days) — still rising
- 12-1 month momentum is +25.0% — the canonical momentum signal remains firmly risk-on
- BTC +4.72% month-over-month suggests speculative appetite hasn't fully collapsed

**Near-term (bearish, deteriorating):**
- VIX has spiked sharply from a 90-day baseline of 18.4 to 27.19 — a +48% spike in implied volatility
- Only 4 of 11 S&P sectors are above their 50-day SMA — and all 4 are defensive sectors (energy, staples, utilities, REITs)
- Growth/cyclical sectors (tech, financials, consumer discretionary, industrials) are all below 50d SMA
- SPY 1-month return: -4.29%; 3-month return: -3.62% — clear near-term weakness
- VIX 30-day high of 29.49 shows recent stress events

**Implied vs. realized volatility divergence:**
- Realized vol (21d): 12.3% — remarkably calm actual price action
- Implied vol (VIX): 27.19% — fear premium well above realized
- This divergence (~15pp) is elevated; the market is pricing in significantly more risk than it has experienced. This is consistent with a **fear-driven selloff** rather than a fundamental breakdown — uncertainty and sentiment are driving the VIX spike more than actual realized volatility.

---

## Regime Confidence

**Confidence:** MEDIUM

**Transition risk: HIGH**

The market is near several key inflection points simultaneously:

1. **SPY at the 200d SMA edge** (+0.90%): Any continued selling pushes SPY below its 200d SMA, triggering trend-following exits and shifting the regime to `mean-reverting / risk-off`. This is the most critical pivot.

2. **VIX approaching 30**: If VIX crosses 30 and holds there, mean-reversion strategies should reduce exposure further (per H02 guidelines). If VIX reaches 40, all strategies should pause per the crisis protocol.

3. **Sector rotation is underway**: The rotation from growth (tech, consumer discretionary) to defensive (utilities, staples, energy) is a classic risk-off rotation pattern. If this accelerates, the 12-1m momentum signal may flip negative within 2-3 months.

4. **Macro catalyst watch**: Without knowing the specific macro catalyst (tariff announcements, rate decisions, geopolitical events), the primary risk is that the current correction deepens into a sustained downtrend.

---

## Strategy Suitability Matrix

| # | Strategy | Category | Regime Fit | Notes |
|---|---|---|---|---|
| H04 | Pairs Trading (Cointegration) | Stat Arb | **Strong** | Market-neutral hedges broad selloff; mean reversion in pairs works in high-vol; low historical MDD |
| H02 | Bollinger Band Mean Reversion | Mean Reversion | **Neutral** | Near the VIX > 30 suspension threshold; only safe on instruments in intact uptrends (XLE, XLU, XLP, XLRE) |
| H06 | RSI Short-Term Reversal | Mean Reversion | **Neutral** | High VIX = more extreme RSI readings = more signal opportunities; SPY barely above 200d SMA (trend filter barely satisfied); elevated PDT risk at $25K with frequent signals |
| H05 | Momentum Vol-Scaled | Momentum | **Caution** | Vol-scaling auto-reduces exposure (good); crash protection not yet triggered (-4.3% vs -10% threshold); momentum crash risk if rotation continues |
| H03 | Multi-Factor Long-Short | Factor | **Caution** | Market-neutral design helps; but factor crowding unwinds hit in high-vol (2018, 2020 pattern); growth-to-defensive rotation punishes momentum factor; quality factor benefits |
| H01 | Dual MA Crossover | Trend Following | **Weak** | High-vol = whipsaw environment for MA crossovers; 200d SMA filter protects against net short, but crossover signals are noisy in corrections |

---

## Priority Ranking for Phase 1

**Recommended order for intensive backtesting:**

### Tier 1 — Run aggressively
1. **H04 — Pairs Trading (Cointegration)**
   - Best fit for current regime: market-neutral hedges broad uncertainty
   - Lowest historical MDD (~8%) — important when vol is elevated
   - Mean-reversion mechanism works well when fundamentally-linked pairs are stable
   - Caution: ensure selected pairs don't span the growth/defensive divide (avoid tech vs. energy pairs in current rotation)

2. **H02 — Bollinger Band Mean Reversion**
   - Best overall Gate 1 odds per historical analysis
   - In current regime: restrict universe to the 4 sectors above 50d SMA (XLE, XLU, XLP, XLRE)
   - Ensure VIX guard rails are active (reduce positions as VIX approaches 30)

### Tier 2 — Run with regime-aware guard rails
3. **H06 — RSI Short-Term Reversal**
   - More signals in high-vol environment (good for trade count)
   - 200d SMA filter currently satisfied (SPY barely above)
   - If SPY breaks 200d SMA, long-side signals are disabled — plan for this

4. **H05 — Momentum Vol-Scaled**
   - Long-term momentum is still positive; don't abandon prematurely
   - Vol-scaling will automatically reduce exposure — let it work
   - Watch crash protection trigger (-10% monthly threshold)

### Tier 3 — Deprioritize for Phase 1
5. **H03 — Multi-Factor Long-Short**
   - Factor crowding risk in high-vol regimes
   - Growth-to-defensive rotation actively punishes momentum leg
   - $25K implementation concerns remain

6. **H01 — Dual MA Crossover**
   - Weakest fit for current volatile, correcting environment
   - Use as baseline benchmark; don't allocate Phase 1 backtest resources here first

---

## Pause / Escalation Triggers

The following events should trigger immediate strategy review and escalation to Research Director:

| Trigger | Threshold | Action |
|---|---|---|
| SPY breaks 200d SMA | SPY < SMA (currently at 656.41) | Shift regime to `mean-reverting / risk-off`; suspend trend-following signals; reduce Bollinger Band exposure |
| VIX > 30 | Sustained (3+ days) | Reduce all mean-reversion position sizes by 50% |
| VIX > 40 | Any day | **Pause all live strategies immediately** — crisis regime |
| 12-1m SPY momentum turns negative | SPY 12-1m < 0 | Momentum signals flip; reclassify as risk-off; pause H05 |
| Sector breadth worsens | < 2/11 sectors above 50d SMA | Escalate to Research Director; potential bear market regime |

---

## Data Sources & Methodology

- **VIX**: Yahoo Finance `^VIX`
- **SPY**: Yahoo Finance `SPY` (adjusted close)
- **Sector ETFs**: XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC
- **Hurst Exponent**: R/S analysis on 60-day daily returns (Python `hmmlearn` not used; direct R/S computation)
- **12-1m Momentum**: SPY 252-day return excluding most recent 21 days
- **Analysis date**: 2026-03-15 (VIX data through 2026-03-13, most recent available)
