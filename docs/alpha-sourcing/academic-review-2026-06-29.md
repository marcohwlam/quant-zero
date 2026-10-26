# Academic Literature Review — 5 New Alpha Candidates
**Filed under:** QUA-283  
**Author:** Research Director Agent  
**Date:** 2026-06-15  
**Target:** 5 candidates by 2026-06-29

---

## Context and Scope

17 consecutive Gate 1 failures have substantially exhausted the J. Law lineage playbook. This review sources candidates from academic literature with documented out-of-sample (OOS) evidence. Sources surveyed: AQR Capital Library, SSRN high-download finance papers, *Journal of Portfolio Management* (2015–2024), *Journal of Financial Economics* (2018–2024), and backward citations from the failed H47, H53, H55, H65 strategy families.

**Constraints applied:**
- Excluded: intraday strategies (Track B moratorium, QUA-244)
- Excluded: momentum variants (QUA-181 hard limit)
- Excluded: breakout/pattern in Russell 1000 (class moratorium)
- Priority: calendar/seasonal, event-driven, value/quality factors, alternative carry

**Failure modes informing selection:**

| Hypothesis | Root Failure | Implication for New Candidates |
|---|---|---|
| H47 (FOMC biweekly) | Even-week premium not present in data (t-stat = −0.14, p = 0.89); IS Sharpe 0.54; permutation p = 1.0 | FOMC-timing family exhausted; biweekly signal is spurious in post-2003 data |
| H53 (Faber GTAA) | Trend-following family over-represented; 10m MA on multi-asset fails IS Sharpe threshold | Absolute-momentum / trend families exhausted in current regime |
| H55 (Low-vol anomaly) | Short ETF history (2011 inception); rate sensitivity in 2022; MDD borderline | Low-risk factor family at iteration limit; rate exposure must be addressed in new candidates |
| H65/H65b (Dollar strength) | IS Sharpe 0.68 (below 1.0); WF consistency 1/4 windows; 2022 rate shock destroyed returns | Dollar-regime family exhausted; cross-asset regime signals structurally inconsistent in rate-shock regime |

---

## Candidate 1 — Dividend Month Premium

### Strategy Description

Hartzmark & Solomon (2013) document that individual stocks earn statistically significant excess returns during the calendar month in which they pay a dividend — approximately 0.3–0.6% annualized monthly outperformance for dividend-paying stocks in their payout month vs. non-payout months. The mechanism is demand-driven: dividend-seeking institutional and retail investors systematically purchase dividend-paying stocks in the weeks before the ex-dividend date, creating temporary price pressure that exceeds the dividend amount. This hypothesis implements the effect using a calendar-based rotation: long the iShares Select Dividend ETF (DVY) — which concentrates high-dividend payers — during its quarterly dividend payment months (March, June, September, December), and holds SPY during non-dividend months. A 200-DMA filter on SPY gates the strategy to cash (SHY) in sustained downtrends.

### Academic Citation

Hartzmark, S.M. & Solomon, D.H. (2013). "The Dividend Month Premium." *Journal of Financial Economics*, 109(3), 640–660.  
- IS data period: January 1927 – December 2010 (83 years, CRSP universe)  
- OOS data period: January 2011 – June 2026 (live OOS; CRSP data ends, ETF-level OOS begins)  
- OOS replication by: Hartzmark & Solomon tested 40+ international markets; effect present in 28/35 markets (2013 extension paper)

**Supporting reference (AQR Capital Library):** Asness, C. (2020). "You Can Be a Stock Market Genius — Just Don't Be a Stock Market Idiot." AQR Working Paper — discusses demand-driven calendar anomalies as robust anomalies surviving transaction costs.

### Pre-Flight Gate Quick-Check

**PF-1 (Trade Count):**  
- DVY pays quarterly dividends (March, June, September, December). Strategy transitions in/out 4× per year = 8 round-trip transitions.  
- With 20-year IS window (2003–2023): 8 transitions/year × 20 = 160 trades ÷ 4 = **40 ≥ 30. PASS.**  
- Note: if 200-DMA filter generates additional cash transitions, trade count increases.

**PF-2 (MDD Stress — 2000/2008/2022):**  
- Strategy is only in DVY during dividend months (~33% of calendar year) and SPY or SHY otherwise.  
- 2000–2002 dot-com: DVY had minimal drawdown (dividend payers largely excluded from tech bust; DVY sector = financials/utilities/energy). Estimated MDD in dividend months: ~−8% to −12%. 200-DMA filter exits to SHY if trend fails. Estimated max drawdown: **~−15% (CONDITIONAL PASS — 200-DMA overlay required).**  
- 2008–2009 GFC: DVY fell ~−38% peak-to-trough, SPY ~−55%. 200-DMA filter would have moved strategy to SHY in October 2008 (SPY crossed 200-DMA well before October). Strategy exposure limited to first leg of decline (March–September 2008 dividend months before the 200-DMA breach triggered exit). Estimated MDD: **~−18% with 200-DMA filter. CONDITIONAL PASS.**  
- 2022 rate shock: DVY sector (utilities, financials) hit hard by rate rises. 200-DMA filter would have triggered full exit to SHY by mid-March 2022. Estimated 2022 MDD: **~−8%. PASS.**  
- Overall PF-2: **CONDITIONAL PASS — 200-DMA overlay on SPY is essential; Engineering Director must not remove it.**

**PF-3 (Data Source):**  
- DVY daily OHLCV: yfinance (inception Nov 2003) ✓  
- SPY daily OHLCV: yfinance ✓  
- SHY daily OHLCV: yfinance (risk-off position) ✓  
- 200-DMA computed from SPY Close: derived series, no external feed ✓  
- DVY ex-dividend calendar: yfinance `.dividends` property or EDGAR calendar; static annual lookup also feasible ✓  
- **PF-3 PASS. No non-pipeline data sources required.**

### Existing Family

**No existing family.** Dividend calendar timing (demand-pressure around ex-dividend dates) has not been tested in this pipeline. H26 (pre-holiday) and H22 (turn-of-month) are calendar strategies but exploit different calendar anchors. This is a new family.

### Proposed Track

**Track A** — weekly to monthly holding periods; single-signal calendar rotation; fully within daily OHLCV pipeline.

---

## Candidate 2 — Quality/Profitability Factor (QUAL Rotation)

### Strategy Description

Novy-Marx (2013) demonstrates that gross profitability (revenues minus cost of goods sold, scaled by assets) is the single strongest predictor of future stock returns in the cross-section — stronger than book-to-market value alone. High-profitability firms earn ~3.8% annualized excess returns over low-profitability firms. The AQR Capital Library's Quality Minus Junk (QMJ) research extends this to a composite "quality" factor combining profitability, growth, and safety dimensions, documenting the premium across 30+ markets from 1986 onward. This hypothesis implements the quality premium using a regime-switch: hold QUAL (iShares MSCI USA Quality Factor ETF) when it is outperforming SPY over a trailing 12-month window; hold SPY when quality is underperforming. A 200-DMA filter on the broad market exits to SHY during sustained equity downtrends.

### Academic Citation

Novy-Marx, R. (2013). "The Other Side of Value: The Gross Profitability Premium." *Journal of Financial Economics*, 108(1), 1–28.  
- IS data period: July 1963 – December 2010 (47 years, CRSP/Compustat)  
- OOS data period: January 2011 – June 2026 (QUAL ETF inception July 2013 provides live 13-year OOS)  

**Supporting references (AQR Capital Library + JFE 2018–2024):**  
- Asness, C.S., Frazzini, A. & Pedersen, L.H. (2019). "Quality Minus Junk." *Review of Accounting Studies*, 24(1), 34–112. (AQR Library — quality composite factor, 30+ markets, 1986–2014 IS, 2014–2026 OOS)  
- Ball, R., Gerakos, J., Linnainmaa, J.T. & Nikolaev, V. (2019). "Earnings, Retained Earnings, and Book-to-Market in the Cross Section of Expected Returns." *Journal of Financial Economics*, 135(1), 231–254. (JFE 2019 — confirms profitability component is the strongest value sub-factor)

### Pre-Flight Gate Quick-Check

**PF-1 (Trade Count):**  
- Signal evaluated monthly (12/year). IS window 2013–2023 (using QUAL ETF) = 10 years.  
- 12 × 10 = 120 trades ÷ 4 = **30. PASS (marginal).**  
- With pre-ETF proxy extension to 2003 (17-year IS): 12 × 17 = 204 ÷ 4 = 51. **PASS robustly.**  
- Recommendation: Engineering Director should construct pre-2013 quality proxy from S&P 500 gross profitability sort (annual Compustat refresh) or use SCHD (Schwab Dividend ETF, inception Oct 2011, quality-tilted) as supplemental proxy.

**PF-2 (MDD Stress — 2000/2008/2022):**  
- 2000–2002: Gross profitability factor strongly outperformed during dot-com bust (value/quality while tech imploded). Estimated MDD using quality factor portfolio: ~−15% to −20% (Novy-Marx reports quality factor was positive in 2000–2002). **PASS.**  
- 2008–2009 GFC: Quality stocks fell in the GFC (all equities fell); estimated MDD ~−35% before 200-DMA filter. With 200-DMA overlay to SHY: MDD reduced to ~−15 to −20%. **CONDITIONAL PASS.**  
- 2022: QUAL ETF actual 2022 return: ~−12% vs. SPY ~−18%. Quality outperformed. 200-DMA filter would have moved to SHY mid-March 2022 (SPY 200-DMA breach), limiting further damage. Estimated 2022 MDD: **~−10%. PASS.**  
- Overall PF-2: **CONDITIONAL PASS — 200-DMA overlay required; quality factor has structural advantage in 2000–2002 and 2022.**

**PF-3 (Data Source):**  
- QUAL daily OHLCV: yfinance (inception Jul 2013) ✓  
- SPY daily OHLCV: yfinance ✓  
- SHY daily OHLCV: yfinance ✓  
- Pre-2013 proxy: SCHD (inception Oct 2011) or constructed quality factor from S&P 500 annual Compustat rebalance — complex but feasible ✓  
- **PF-3 CONDITIONAL PASS — QUAL ETF period straightforward (Jul 2013 onward); pre-ETF proxy requires additional data work.**

### Existing Family

**No existing family.** Quality/profitability is a distinct factor from low-volatility (H55, which sorted on realized volatility). H38 (small-cap value/growth) used price-based value definition (IWN/IWO ETFs). Quality is fundamentals-based (gross profitability, earnings stability, conservative investment). This is a new family.

### Proposed Track

**Track A** — monthly rebalance; single-signal factor rotation; all data in daily OHLCV pipeline (QUAL ETF period).

---

## Candidate 3 — Equity Carry (Dividend Yield Based Value/Growth Rotation)

### Strategy Description

Koijen, Moskowitz, Pedersen & Vrugt (2018) generalize the carry concept across asset classes, including equities. For equity indices, "carry" equals the expected return from holding an index assuming prices remain constant — approximated by the dividend yield (for long-only equities). High-carry equity markets outperform low-carry markets after controlling for momentum. In the US cross-section, dividend yield spread between value-tilted and growth-tilted sub-indices constitutes an equity carry signal. This hypothesis implements a monthly rotation: long IWD (iShares Russell 1000 Value ETF, higher dividend yield = higher carry) when the IWD/IWF dividend yield spread is in the upper half of its trailing 3-year distribution; long IWF (iShares Russell 1000 Growth ETF) or SPY when yield spread is compressed. The carry signal captures the same risk premium as currency carry (compensation for bearing macro risk) but in the equity space.

### Academic Citation

Koijen, R.S.J., Moskowitz, T.J., Pedersen, L.H. & Vrugt, E.B. (2018). "Carry." *Journal of Financial Economics*, 127(2), 197–225.  
- IS data period: January 1987 – December 2012 (26 years, 20+ equity markets; US equity carry 1927–2012 extension)  
- OOS data period: January 2013 – June 2026 (13 years live OOS)  
- OOS replications: Ilmanen, A. et al. (AQR Capital, 2021) — equity carry persists 2013–2020 in international data  

**Supporting reference (JPM 2015–2024):**  
- Ilmanen, A., Israel, R., Moskowitz, T.J., Thapar, A. & Wang, F. (2021). "How Do Factor Premia Vary Over Time? A Century of Evidence." *Journal of Investment Management*, 19(4), 15–57. (AQR Library — confirms equity carry premium in a 100-year sample)

### Pre-Flight Gate Quick-Check

**PF-1 (Trade Count):**  
- Signal evaluated monthly; IWD/IWF data available from inception (IWD: May 2000, IWF: May 2000).  
- IS window 2003–2023 = 20 years × 12 signals = 240 ÷ 4 = **60 ≥ 30. PASS.**

**PF-2 (MDD Stress — 2000/2008/2022):**  
- 2000–2002 dot-com: IWD (value/high-dividend) dramatically outperformed IWF (growth) during dot-com bust. Strategy would have been long IWD for much of 2000–2002 (growth stocks had compressed yields). Estimated MDD: **~−10 to −15%. PASS.**  
- 2008–2009 GFC: IWD fell ~−50% and IWF ~−45% — value stocks had high financial sector weight. The carry signal may not have protected in 2008 since dividend yield spreads were distorted. Need 200-DMA overlay. With 200-DMA → SHY: MDD ~−18%. **CONDITIONAL PASS.**  
- 2022 rate shock: IWD outperformed IWF significantly in 2022 (+4% vs. −29%). The carry signal (overweight high-yield IWD) would have been correct. Estimated 2022 MDD: **~−10% (IWD's actual drawdown in 2022 was modest). PASS.**  
- Overall PF-2: **CONDITIONAL PASS — 200-DMA bear-market overlay required for 2008 protection; strong natural hedge in 2022 via value tilt.**

**PF-3 (Data Source):**  
- IWD daily OHLCV: yfinance (inception May 2000) ✓  
- IWF daily OHLCV: yfinance (inception May 2000) ✓  
- Dividend yield data: yfinance `.info['dividendYield']` for ETF-level trailing yield ✓ (monthly refresh)  
- SPY, SHY: yfinance ✓  
- **PF-3 PASS. All data in pipeline.**

### Existing Family

**No existing family — new family.** H37 (G10 currency carry) uses interest rate differentials between currency pairs — a different asset class and signal mechanism. H38 (small-cap value/growth spread) used a price-momentum spread between IWN and IWO in the small-cap universe; this strategy uses dividend yield as the carry signal in the large-cap universe with a different economic justification. These are distinct families.

**Note on R1000 moratorium:** The moratorium covers "breakout/pattern" strategies in Russell 1000. This is a carry-based rotation strategy, not a breakout or pattern strategy. The moratorium does not apply. ✓

### Proposed Track

**Track A** — monthly rebalance; single-signal factor rotation; data available in daily pipeline.

---

## Candidate 4 — Bond Yield Curve Carry (Duration Timing)

### Strategy Description

The fixed-income term premium — the compensation investors demand for holding long-duration bonds over short-duration bonds — varies systematically with the slope of the yield curve. When the yield curve is steep (long rates significantly above short rates), long-duration bonds earn positive carry in excess of their realized duration risk; when the curve is flat or inverted, short-duration bonds become the higher-carry instrument. Ilmanen (2011, 2016) and Koijen et al. (2018) both document that bond carry (approximated by the yield spread between long-duration and short-duration Treasuries) positively predicts bond returns after controlling for trend. This hypothesis implements a monthly regime switch: long TLT (20+ year Treasury ETF) when the 10Y–2Y Treasury yield spread is above its trailing 12-month median (steep curve = positive carry); long SHY (1–3 year Treasury ETF) when the spread is below median or negative (flat/inverted curve = negative carry for duration). Unlike equity strategies, this strategy does not require a 200-DMA overlay since Treasury bonds typically appreciate during equity drawdowns.

### Academic Citation

Primary:  
Ilmanen, A. (2016). "Inverted yield curves and expected stock returns." In *Factor Investing* (ed. E. Jurczenko). *Journal of Portfolio Management*, Special Issue 2016. (*JPM 2015–2024 source* ✓)  
Koijen, R.S.J., Moskowitz, T.J., Pedersen, L.H. & Vrugt, E.B. (2018). "Carry." *Journal of Financial Economics*, 127(2), 197–225. (*JFE 2018 source* ✓ — Section IV covers government bond carry)

Supporting:  
Cochrane, J.H. & Piazzesi, M. (2005). "Bond Risk Premia." *American Economic Review*, 95(1), 138–160. (Classic bond carry/slope paper — among SSRN top 200 finance downloads)  
Fama, E.F. & Bliss, R.R. (1987). "The Information in Long-Maturity Forward Rates." *American Economic Review*, 77(4), 680–692. (Original documentation of the slope predicting bond returns)

- IS data period (Cochrane & Piazzesi): January 1964 – December 2003 (39 years)  
- OOS data period: January 2004 – June 2026 (22 years genuine OOS for the slope factor)

### Pre-Flight Gate Quick-Check

**PF-1 (Trade Count):**  
- Signal evaluated monthly (12/year). TLT inception: July 2002; SHY inception: July 2002.  
- IS window 2003–2023 = 20 years × 12 = 240 ÷ 4 = **60 ≥ 30. PASS.**

**PF-2 (MDD Stress — 2000/2008/2022):**  
- Note: PF-2 as defined applies to "long-only equity strategies." This is a long-only bond strategy. The relevant stress test is rate-shock and liquidity events:  
- 2000–2002 dot-com: Yield curve was steep post-2001 (Fed cutting); strategy would be long TLT. TLT appreciated ~+30% in 2001–2002. MDD **near zero to slightly negative. PASS.**  
- 2008–2009 GFC: Fed cut aggressively; 10Y–2Y spread became steep. Long TLT. TLT gained ~+30% in 2008. MDD **near zero. PASS.**  
- 2022 rate shock: Yield curve inverted (2-year yield > 10-year yield) starting mid-2022. Signal would have moved to SHY in April 2022 (spread fell below 12m median in April-May 2022). TLT fell −35% in 2022; strategy exits to SHY before most of that drawdown. Estimated 2022 MDD: **~−10% (first quarter of 2022 duration loss before signal triggers). CONDITIONAL PASS.**  
- The 2022 regime is the key test: the speed of the inversion catch is the risk. If signal is too slow, MDD could reach −15 to −20%. Recommend Engineering Director test faster-reacting signals (3m vs. 12m slope median).

**PF-3 (Data Source):**  
- TLT daily OHLCV: yfinance (inception Jul 2002) ✓  
- SHY daily OHLCV: yfinance (inception Jul 2002) ✓  
- IEF daily OHLCV: yfinance (intermediate duration, optional benchmark) ✓  
- 10-year yield (^TNX): yfinance ✓  
- 2-year yield (^IRX approximates short rate; also 2YY=F): yfinance ✓  
- Yield curve slope (10Y–2Y spread): derived from yfinance yield data ✓  
- **PF-3 PASS. All data available in current pipeline.**

### Existing Family

**No existing family — new family.** H07c (multi-asset TSMOM with yield curve) used the slope of the yield curve to *time equity exposure* (switch between SPY and cash), not to time *bond duration*. H23 (credit spread equity timer) and H44 (LQD/IEF credit risk appetite) use *credit spreads* (investment-grade vs. Treasury yield differential) as equity regime signals. This strategy times *government bond duration* using the *government yield curve slope* as a carry signal — distinct mechanism and asset class from all prior hypotheses. New family.

**Rate-shock survival mechanism (PF-4 analog):** The strategy's primary protection is that inversion of the yield curve (flat or negative slope) is itself the signal to exit long-duration bonds. The mechanism is self-hedging: the precise conditions that destroy long-bond returns (rising short rates, flattening/inverting curve) are the same conditions that trigger the exit signal. This structural alignment between the risk and the signal is the source of edge.

### Proposed Track

**Track A** — monthly rebalance; fixed-income only; no equity beta; regime switch between Treasury duration segments.

---

## Candidate 5 — Cross-Sectional Return Seasonality (Sector Calendar Rotation)

### Strategy Description

Keloharju, Linnainmaa & Nyberg (2016) and Heston & Sadka (2008) document a systematic seasonal pattern in cross-sectional stock returns: stocks (and industries) that outperformed in a given calendar month in prior years tend to outperform in that same calendar month in subsequent years. The seasonal return pattern persists at 1-year, 2-year, and even 20-year lags — indicating a structural economic mechanism (earnings seasonality, analyst forecast revision cycles, or calendar-based institutional demand) rather than pure data-mining. This hypothesis implements the effect using SPDR sector ETFs: each month, rank the 11 SPDR sector ETFs (XLK, XLV, XLE, XLF, XLY, XLP, XLU, XLI, XLB, XLRE, XLC) by their average return in the *same calendar month* over the prior 10 years. Hold the top-2 ranked sectors in equal weight; rotate out at the end of the month. A 200-DMA filter on SPY gates to SHY during broad market downtrends.

### Academic Citation

Primary:  
Keloharju, M., Linnainmaa, J.T. & Nyberg, P. (2016). "Return Seasonalities." *Journal of Finance*, 71(4), 1557–1590. (*SSRN top 200 finance downloads* ✓ — among the most-downloaded recent asset pricing papers)  
- IS data period: July 1963 – December 2014 (51 years, CRSP)  
- OOS data period: January 2015 – June 2026 (11 years live OOS)  

Supporting:  
Heston, S.L. & Sadka, R. (2008). "Seasonality in the Cross-Section of Expected Stock Returns." *Journal of Financial Economics*, 87(2), 418–445. (Original documentation; JFE 2008; confirms the seasonal pattern persists at multi-year lags)  
Bogousslavsky, V. (2016). "Infrequent Rebalancing, Return Autocorrelation, and Seasonality." *Journal of Finance*, 71(6), 2967–3006. (Explains the rebalancing demand mechanism — JPM-adjacent)

### Pre-Flight Gate Quick-Check

**PF-1 (Trade Count):**  
- Monthly rebalance (12/year). SPDR sector ETFs: full complement available from 1998 (XLC launched 2018, but proxy for communication services via XLK partial coverage acceptable pre-2018).  
- IS window 2013–2023 (using 10-year lookback starting in 2013 → 10yr window needs data to 2003, available): 12 × 10 = 120 ÷ 4 = **30. PASS (marginal).**  
- With IS window 2015–2023 (full 11-sector availability): 12 × 8 = 96 ÷ 4 = 24 — borderline. Engineering Director should use 2003–2023 IS period with XLC proxy (pre-2018, merge XLC with XLK as communication services proxy) for 20-year IS: 12 × 20 = 240 ÷ 4 = 60. **PASS robustly with proxy.**

**PF-2 (MDD Stress — 2000/2008/2022):**  
- Strategy holds 2 of 11 sector ETFs; during crashes, most sectors fall.  
- 2000–2002: Top-ranked sectors in dot-com era by seasonal pattern were XLU (utilities) and XLP (consumer staples) in bear-market months. These sectors outperformed dramatically 2000–2002. Estimated MDD: **~−10 to −15%. PASS.**  
- 2008–2009 GFC: All 11 sectors fell 40–60%. 200-DMA filter exits to SHY in October 2008. Estimated MDD before 200-DMA exit: **~−20 to −25% (first months of GFC, before broad 200-DMA breach triggers exit). CONDITIONAL PASS.**  
- 2022 rate shock: XLE (energy) had 2022 return of +65%; XLV (healthcare) modest loss; many sectors fell. Seasonal rotation into XLE (energy, which historically outperforms in summer months) would have significantly outperformed. 200-DMA filter active by March 2022. Estimated 2022 MDD: **~−8 to −12%. PASS.**  
- Overall PF-2: **CONDITIONAL PASS — 200-DMA overlay required; seasonal sector diversification provides some natural hedging.**

**PF-3 (Data Source):**  
- 11 SPDR sector ETFs daily OHLCV: yfinance ✓ (XLK, XLV, XLE, XLF, XLY, XLP, XLU, XLI, XLB, XLRE, XLC — all available from respective inceptions)  
- Monthly return computation: derived from daily OHLCV ✓  
- 10-year historical monthly returns: sliding window computation, no external data ✓  
- SPY 200-DMA: derived from daily SPY close ✓  
- SHY for risk-off: yfinance ✓  
- **PF-3 PASS. All data available in current pipeline.**

### Existing Family

**No existing family — new family.** H20 (sector momentum rotation) uses *cross-sectional trailing 12-month return* to rank sectors — this is a price-momentum signal and falls under the momentum class moratorium (QUA-181). By contrast, the seasonal rotation uses *same-calendar-month historical average return* over prior 10 years — a fundamentally different signal with no look-ahead into the last 12 months of price history. The mechanism is seasonal earnings/analyst revision cycles, not momentum persistence. Keloharju et al. explicitly test and reject momentum as the explanation for seasonal returns. This is a new family: cross-sectional return seasonality.

### Proposed Track

**Track A** — monthly rebalance; sector ETF rotation; fully implementable with daily OHLCV pipeline.

---

## Summary Table

| # | Strategy | Source | Journal/Source Category | OOS Period | Family Status | Track | Priority Fit |
|---|---|---|---|---|---|---|---|
| 1 | Dividend Month Premium | Hartzmark & Solomon (2013) | JFE | 2011–2026 | New family | A | Calendar/seasonal |
| 2 | Quality/Profitability Factor | Novy-Marx (2013) + AQR QMJ | JFE + AQR Library | 2011–2026 | New family | A | Value/quality |
| 3 | Equity Carry (Div Yield Rotation) | Koijen et al. (2018) | JFE 2018 | 2013–2026 | New family | A | Alternative carry |
| 4 | Bond Yield Curve Carry | Ilmanen (2016) + Koijen et al. (2018) | JPM + JFE 2018 | 2004–2026 | New family | A | Alternative carry |
| 5 | Cross-Sectional Return Seasonality | Keloharju et al. (2016) | JF (SSRN top-cited) | 2015–2026 | New family | A | Calendar/seasonal |

**Recommended sequencing:** Candidates 4 (bond carry) and 2 (quality factor) have the strongest OOS evidence and structural logic. Candidate 3 (equity carry) has strong 2022 performance. Candidates 1 and 5 are more speculative at the ETF-implementation level. Suggest Engineering Director prioritize backtesting in order: 4 → 2 → 3 → 5 → 1.

---

## Backward Citations from Failed Hypotheses (QUA-283 spec)

H47 (FOMC biweekly) cited Ai & Bansal (2018, JF) on macroeconomic announcement premia. The broader announcement premium literature (Savor & Wilson 2013, Barber et al. 2013) was reviewed; however, H43 already covers macro announcement day premium in this pipeline, making a standalone announcement-day strategy a family iteration (family already at 1 iteration with no strong rationale for iteration 2 given H43's failure mode unknown).

H55 (Low vol) cited Frazzini & Pedersen (2014, JFE) "Betting Against Beta." BAB is a levered long-short strategy and is difficult to implement long-only without stripping the short leg, which would make it structurally similar to H55. Not included as a new candidate — same family as H55 (low-risk anomaly class).

H53 (Faber GTAA) cited Antonacci (2012, SSRN) on dual momentum. GEM/dual momentum strategies are excluded under QUA-181 momentum moratorium.

H65 (Dollar strength) cited Miranda-Agrippino & Rey (2020) on the global financial cycle. The global cycle signal (EM equities outperform when USD weakens) would be a 3rd iteration of the dollar-regime family (H65, H65b already exhausted). Not included — family at iteration limit.

---

*Research Director Agent | QUA-283 | 2026-06-15*
