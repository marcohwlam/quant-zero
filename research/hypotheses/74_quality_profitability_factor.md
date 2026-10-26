# Quality Sector Rotation (Quality/Profitability Factor)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-06-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

Novy-Marx (2013, *JFE*) demonstrated that gross profitability (gross profit / total assets) strongly predicts cross-sectional stock returns, with near-zero correlation to the value factor (HML). The quality premium is compensation for holding stable, capital-efficient firms: high-quality businesses generate consistent earnings, maintain low leverage, and attract institutional demand during risk-off regimes. These characteristics reduce distress probability and create persistent return premium over the junk end of the spectrum.

AQR's Quality Minus Junk (QMJ) factor (Asness et al., 2019) documented ~4–5% annualized alpha above the market portfolio with live OOS performance since 2013. The premium appears structural: low-quality firms are held by retail investors with lottery-return preference, and their short-selling costs deter arbitrage, sustaining mispricing. Quality has been documented in 30+ years of international data and across asset classes.

**Sector ETF implementation:** Individual stock gross profitability backtesting over 20 years requires historical point-in-time fundamental data unavailable in yfinance (see PF-3). Sector ETF rotation is the feasible alternative. Quality maps to observable sector characteristics: dividend yield stability (a proxy for earnings consistency), inverse rolling price volatility (stable sectors have lower vol), and earnings payout history. These are computable from yfinance daily OHLCV + dividend data without look-ahead bias.

**Why quality differs from H73 (seasonality):** H73's seasonal ranking is a statistical anomaly with no fundamental mechanism for persistence. Quality's persistence mechanism is structural: capital efficiency and earnings stability are self-reinforcing competitive advantages that regenerate each year.

## Entry/Exit Logic

**Quality composite score (computed monthly, last trading day of month):**

1. `div_yield_score`: trailing 12-month dividend yield for each sector ETF = sum(dividends paid in prior 12 months) / month-end price. Higher = more stable earnings. Cross-sectional z-score across 10 sectors.
2. `stability_score`: inverse of rolling 12-month annualized price volatility (daily returns std × √252). Lower vol = more stable business quality. Cross-sectional z-score across 10 sectors.
3. `quality_composite`: equal-weight average of `div_yield_score` and `stability_score`. (P/E sub-score deferred — historical P/E data not available in yfinance pipeline; see PF-3.)

**Sector universe:** XLK, XLV, XLF, XLY, XLP, XLU, XLI, XLB, XLE, VNQ (10 SPDR sector ETFs + VNQ).

**Entry signal:**
- Rank 10 sector ETFs by `quality_composite` score at month-end
- Long equal-weight top-3 sectors
- Enter positions at next-day market open

**Regime filter (highest priority — overrides entry):**
- If SPY close < 200-day simple moving average: exit all sector positions, enter SHY (short-term Treasuries)
- Re-enter sectors when SPY closes above 200-DMA on next rebalance date

**Exit signal:**
- Monthly rebalance: sell sectors dropping out of top-3 ranking; buy replacements
- 200-DMA breach (intramonth): exit all to SHY at next open; do not wait for month-end

**Holding period:** Monthly swing (sector positions held 1 month average, reduced in SHY periods)

## Market Regime Context

**Works best:** Stable-to-bull equity markets where fundamental quality is rewarded (2003–2007, 2013–2019, 2023–2024). Low-macro-volatility environments where defensive sectors (XLV, XLP) deliver steady compounding. Quality sectors show greatest relative outperformance during late-cycle deceleration.

**Fails / underperforms:**
- Strong commodity/energy rallies (2021–2022): XLE gains +65% while defensive quality sectors lag. Quality composite scores XLE low (minimal dividends relative to vol), so strategy misses energy rally.
- Early bear-market drawdown: quality sectors fall with the market before 200-DMA triggers. Expect 10–20% drawdown before regime filter activates.
- Extreme momentum regimes (1999, 2020 rebound): growth/momentum sectors dominate, quality underperforms.

**Regime pause triggers:**
- SPY < 200-DMA → full exit to SHY (built-in)
- If entering SHY causes >3 regime switches in 6 months (whipsaw), increase DMA window to 250 days

## Alpha Decay

Quality factor operates at slow fundamental decay due to multi-year persistence in sector earnings characteristics:

- **Signal half-life (days):** 90–120 trading days (quality rankings shift with quarterly earnings cycles; sector changes are slow)
- **Edge erosion rate:** slow (>20 days)
- **Recommended max holding period:** 60 days (2 monthly rebalances). Quality composite rarely changes dramatically in a single month.
- **Cost survival:** YES — monthly rotation incurs ~8–12 bps round-trip per position switch (3 ETF positions, ~1 switch/month average = ~12 round-trips/year). Expected quality premium ~50–100 bps/month gross. Cost-to-premium ratio estimated 10–20%.
- **Annualized IR estimate (pre-cost):** Novy-Marx (2013) reports ~0.44 Sharpe for gross profitability factor standalone in US stocks. AQR QMJ live net Sharpe ~0.4–0.6. Sector ETF implementation adds diversification noise across only 10 instruments; estimated gross IR ~0.4–0.6, net IR ~0.3–0.5.
- **Notes:** Quality premium crowding is highest in individual stock long/short implementations. Sector ETF level is less crowded. Decay rate accelerates in momentum-driven markets where factor exposure gets rotated out.

> IR estimate of 0.3–0.5 net is above the 0.3 warning threshold but may fall short of IS Sharpe > 1.0 Gate 1 requirement. See Gate 1 Outlook.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `sectors_held` | 2, 3, 4 | Concentration vs diversification tradeoff |
| `quality_lookback_months` | 6, 12, 18 | Trailing div yield / vol estimation window |
| `dma_window` | 150, 200, 250 | Standard MA range; 200 is academic default |
| `rebalance_frequency` | monthly, bi-monthly | Turnover cost tradeoff vs signal freshness |

Restrict sweep to above combinations (4 × 3 × 3 × 2 = 72 combinations). Avoid expanding further to limit overfit risk.

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000 (3 ETF positions at $3,000–4,000 each; no PDT concern for swing)
- **PDT impact:** N/A — monthly rebalance swing strategy; all trades held >1 day
- **Position sizing:** Equal-weight 33% per sector ETF (3 positions). SHY regime: 100% SHY. No leverage.

## Pre-Flight Gate Checklist

### PF-1 — Walk-Forward Trade Viability

**Methodology:** Sector rotation monthly, hold top-3 of 10 sectors.

Historical turnover estimate for top-3 sector rotation:
- Average monthly churn at top-3 positions: approximately 0.8–1.2 sector changes per month
- Each sector change = 1 sell + 1 buy = 2 trades
- IS window: 20 years (2003–2023), 240 months
- Monthly rebalance trades: 240 months × 1.0 avg changes × 2 = **480 rebalance trades**
- 200-DMA regime transitions: estimated 4–8 full exits per decade (based on H73 observed regime behavior), 2-way (exit + re-entry): ~16–32 additional trades over 20 years
- **Total IS trade estimate: 496–512 trades**

Threshold check: 496 ÷ 4 quarters = 124 per quarter ≫ 30. **PF-1: PASS**

H72 comparison: H72 had 26 IS trades over 15 years (monthly TLT/SHY binary switch, only ~1–2 switches/year). Sector rotation with 10 instruments and 3 held positions generates orders of magnitude more trades.

### PF-2 — Long-Only MDD Stress Test

**2000–2002 dot-com bust:**
- SPY total drawdown: –49%
- Defensive quality sectors: XLV (–15% from 2000 peak), XLP (–10% from 2000 peak)
- 200-DMA breach: SPY crossed below 200-DMA in September 2000. Strategy exits to SHY by early October 2000, avoiding 2001–2002 deepening (–38% SPY from Sept 2000 to Oct 2002).
- Pre-breach exposure: Jan–Sept 2000 portfolio of quality sectors (XLV, XLP likely in top-3) would have declined approximately –8 to –12% before 200-DMA exit.
- **Estimated 2000–2002 MDD: –10 to –18%**

**2008–2009 GFC:**
- SPY total drawdown: –57%
- Quality sector behavior: XLV –22% (calendar 2008), XLP –15% (calendar 2008), XLU –28% (calendar 2008)
- 200-DMA breach: SPY crossed below 200-DMA in late June 2008. Strategy exits to SHY by early July 2008. July–March 2009 decline avoided (–40% from June 2008 peak).
- Pre-breach exposure: Jan–June 2008 (~6 months), quality sectors declined approximately –10 to –15%.
- **Estimated 2008–2009 MDD: –15 to –22%**

**Assessment:** MDD estimate of –15 to –22% is borderline around the –20% equity constraint. Quality sectors' defensive character provides meaningful protection relative to SPY (–57% GFC), but worst-case scenario touches –22% before regime filter activates. This is better than H73 (–31.06% actual IS MDD) because quality sectors have structurally lower drawdowns than seasonal rotation picks.

**PF-2: CONDITIONAL PASS** — estimate within range; backtest confirmation required. If MDD exceeds –20%, add secondary drawdown control (reduce positions by 50% when any held sector draws down >10% from entry).

### PF-3 — Data Pipeline Availability

| Data requirement | Source | Status |
|---|---|---|
| Sector ETF daily OHLCV | yfinance (all 10 ETFs) | ✅ Available to 1998 |
| Historical dividends (for div_yield_score) | yfinance Ticker.dividends | ✅ Available |
| Rolling price volatility | Computed from daily returns | ✅ Computable |
| Forward P/E (optional sub-score) | yfinance Ticker.info['forwardPE'] | ⚠️ Current data only; NOT historical |

**Critical PF-3 flag:** The P/E sub-score would require historical sector P/E ratios going back to 2003. yfinance does not store historical P/E time-series for ETFs. Using current P/E values in a historical backtest introduces look-ahead bias.

**Resolution:** Default to 2-factor quality composite (div_yield + stability_score). P/E-based filtering can be added if Engineering sources historical ETF P/E from a secondary data provider (FRED/Refinitiv/Simfin). If P/E data is not available for backtest, the 2-factor composite is fully viable and avoids bias.

**PF-3: PASS** — 2-factor composite with div_yield + inverse volatility is fully computable from yfinance historical data with no look-ahead risk.

### PF-4 — Rate-Shock 2022 Rationale

**The risk:** Rate-shock environments (2022) hurt growth and technology stocks sharply as rate discount on future cash flows increased. XLK fell –33% in 2022. If "quality" is proxied incorrectly (e.g., using Sharpe alone which rewards recent momentum), XLK could be ranked high going into 2022.

**Why this quality composite avoids the 2022 trap:**

1. **Dividend yield sub-score:** XLK's dividend yield has historically been <0.8% (AAPL/MSFT pay minimal dividends relative to their price). XLP yields ~2.5–3.0%, XLV ~1.5–2.0%, XLU ~3.0–3.5%. XLK would consistently rank low on div_yield_score, excluding it from the top-3 quality basket.

2. **Inverse volatility sub-score:** XLK has higher realized volatility than XLP, XLV, or XLU. This further down-ranks tech relative to defensive sectors. The stable, mature sectors (staples, healthcare) that historically survive rate shocks score highest on both sub-scores.

3. **200-DMA exit:** SPY crossed below 200-DMA in mid-March 2022 after the initial –12% decline. The strategy exits to SHY at that point, capturing a neutral result for the remaining –22% SPY decline through October 2022.

4. **Pre-breach exposure (Jan–Feb 2022):** Portfolio in early 2022 would have been holding XLP, XLV, XLU (per quality ranking). These sectors returned –2% to –5% in Jan–Feb 2022 vs SPY –8%. The strategy's early-2022 drawdown would be smaller than market.

**PF-4: PASS** — The dividend-yield + inverse-volatility quality composite structurally excludes high-PE tech. The 200-DMA exit limits post-breach losses. No structural modification required.

## Gate 1 Outlook

**IS Sharpe > 1.0: UNLIKELY**

H73 (same sector rotation architecture, 200-DMA filter, monthly rebalance) achieved IS Sharpe 0.59 over a 21-year IS window. Quality ranking is a better economic signal than seasonal ranking, but the architecture is fundamentally the same. The annualized quality premium at sector ETF level is estimated at 2–4% above SPY benchmark, with similar volatility. Expected IS Sharpe: **0.55–0.75**. This is unlikely to clear the 1.0 Gate 1 threshold.

Research Director note: If H73 and H74 both achieve IS Sharpe ~0.6 and OOS persistence, this may indicate the IS Sharpe > 1.0 threshold is too stringent for monthly-rebalance sector strategies. A portfolio of 3–4 such uncorrelated sector strategies could achieve a combined Sharpe > 1.0 at the portfolio level.

**IS CAGR ≥ 10%: UNCERTAIN (45–55%)**

Quality sectors have historically matched or modestly exceeded SPY CAGR (~10% nominal). The 200-DMA compounding protection in 2000–2002 and 2008–2009 could add 1–2% annualized CAGR. Assessment: borderline.

**IS MDD < 20%: POSSIBLE (50–60%)**

Quality's defensive sector composition + 200-DMA filter should limit GFC MDD to –15 to –22% range. H73 hit –31.06%; quality sectors are demonstrably more defensive. Higher probability of clearing than H73, but not guaranteed.

**Walk-Forward Stability: LIKELY**

Quality premium persistence is structural and multi-decade. AQR QMJ has documented 30+ years OOS performance. Walk-forward windows should show consistent OOS performance; quality ranking is less regime-dependent than seasonal calendar.

**Permutation test p < 0.05: UNCERTAIN**

H73 failed at p=0.45 with 324 trades. With ~500 IS trades and stronger economic rationale (slow-decay factor vs. calendar anomaly), permutation test probability of passing is higher, but 10-sector universe is still small for robust statistical testing.

**Sensitivity: MEDIUM**

`sectors_held` and `dma_window` are the key sensitivities. Quality composite sub-score weighting is secondary (both sub-scores point to same defensive sectors). Sensitivity risk: MEDIUM — lower than H73's 46.8% variance.

**Known overfitting risks:**
1. 10-sector universe — easy to post-hoc select "quality" definition that picks defensive sectors in backtesting
2. Quality metric (div_yield + inv_vol) may accidentally proxy for low-beta / low-vol factor rather than pure quality
3. 200-DMA parameter selection — any DMA between 150–250 produces similar results, but reported on the best value

## References

- Novy-Marx, R. (2013). "The Other Side of Value: The Gross Profitability Premium." *Journal of Financial Economics*, 108(1), 1–28. — primary signal source; gross profitability → excess returns
- Asness, C., Frazzini, A., & Pedersen, L. H. (2019). "Quality Minus Junk." *Review of Accounting Studies*, 24(1), 34–112. — QMJ factor construction, live OOS performance 2013+
- Frazzini, A., & Pedersen, L. H. (2014). "Betting Against Beta." *Journal of Financial Economics*, 111(1), 1–28. — low-volatility quality overlap; inv_vol sub-score rationale
- Piotroski, J. D. (2000). "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers." *Journal of Accounting Research*, 38, 1–41. — earnings quality signal construction
- H73 backtest verdict: `backtests/H73_CrossSectionalReturnSeasonality_2026-06-16_verdict.txt` — architecture reference; sector rotation performance baseline
- Related hypothesis: `research/hypotheses/73_cross_sectional_return_seasonality.md` — same sector ETF universe and 200-DMA regime filter
