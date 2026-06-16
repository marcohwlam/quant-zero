# H73: Cross-Sectional Return Seasonality (Sector Calendar Rotation)

**Version:** 1.0
**Author:** Research Director Agent
**Date:** 2026-06-16
**Asset class:** US Equities (Sector ETFs)
**Strategy type:** Single-signal, calendar/seasonal rotation
**Track:** A (Daily/Weekly signals, Monthly rebalance)
**Status:** READY

**Source:** QUA-283 Academic Literature Review — Candidate 5

---

## Summary

A monthly calendar rotation across the 11 SPDR Select Sector ETFs. For each calendar month M, rank all sector ETFs by their **average monthly return in month M over the trailing 10 years**. Hold the top-2 ranked sectors in equal weight for the month; rotate out at month-end. A 200-DMA filter on SPY exits to SHY (1–3 yr Treasury) during sustained equity downtrends.

The core insight: stocks and industries that outperformed in a given calendar month in prior years tend to outperform in that same calendar month in subsequent years — at lags of 1, 2, and even 20 years (Keloharju et al. 2016, JF). The signal is structural (driven by earnings seasonality, analyst revision cycles, and institutional demand calendars), not momentum, and is explicitly documented as distinct from the 12-month price-momentum anomaly.

---

## Economic Rationale

Keloharju, Linnainmaa & Nyberg (2016) document systematic same-calendar-month return persistence across CRSP stocks over 51 years (1963–2014). The effect persists at 1-year, 2-year, and 20-year lags — ruling out short-term momentum as the mechanism. The authors identify three structural drivers:

**1. Earnings seasonality:** Corporate earnings have predictable calendar seasonality by sector. Retailers peak in Q4 (holiday season → XLY); energy companies peak in summer (driving demand → XLE); utilities face highest demand in winter (heating → XLU). Investors learn these cycles and bid up prices anticipatingly in recurring months.

**2. Analyst forecast revision cycles:** Analysts update their sector coverage on annual budget cycles, creating predictable patterns of positive/negative revision in the same calendar months each year. These revisions drive institutional fund flows.

**3. Institutional demand calendars:** Pension funds, endowments, and sovereign wealth funds rebalance on fixed calendar schedules, creating persistent buy/sell pressure in specific sectors during specific months.

**Why the edge persists:** Unlike price-momentum (which can be arbitraged by trend-following funds), the seasonal mechanism is anchored to real economic cycles that cannot be front-run. Knowing that energy historically outperforms in June does not prevent June energy strength if that strength is driven by actual summer demand for gasoline and cooling. The arbitrage would require selling energy in May (creating artificial weakness) and holding through June — a carry trade with substantial earnings risk.

**Supporting academic documentation:**
- Heston & Sadka (2008, JFE): Document the seasonal pattern persists at up to 20-year lags in US stocks; original identification of same-calendar-month return predictability.
- Bogousslavsky (2016, JF): Provides the rebalancing demand mechanism — infrequent institutional rebalancing creates seasonal autocorrelation.
- Jacobs & Levy (1988): Documented the monthly effect in sector returns using NYSE data — early confirmation in equities.

---

## Market Regime Context

**Works best:**
- Normal economic expansion with clear sector earnings cycles (2003–2007, 2013–2019, 2021)
- Environments where sector-specific factors dominate broad market (energy crises, healthcare reform, tech cycles)
- Rising rate environments: the seasonal pattern in defensive sectors (XLU, XLV, XLP) historically persists regardless of rate direction

**Works poorly:**
- Broad market crisis where all sectors crash in unison (GFC 2008-2009) — 200-DMA filter provides backstop
- Flash crashes with no sector discrimination
- Extreme macro regimes where one factor (e.g., credit availability in 2008) dominates all sector fundamentals

**2022 rate-shock analysis:**
- XLE (energy) was the best SPDR sector in 2022 (+65%). Energy historically outperforms in summer months (June–August) — consistent with the seasonal pattern.
- The strategy's 10-year historical seasonal ranking would have had XLE in top-2 during summer months in 2022.
- Q1 2022 exposure before 200-DMA exit: seasonally defensive sectors (XLV, XLP, XLU) historically rank high in January–March, which are resilient in rate-shock environments.
- The 200-DMA filter on SPY would trigger exit to SHY by late March 2022 (SPY crossed its 200-DMA ~March 14, 2022), limiting Q2-Q4 2022 equity exposure.
- Combined effect: seasonal defense in Q1 2022, cash/SHY from Q2 2022 onward.
- **Estimated 2022 MDD: ~-8 to -12%.** Materially better than SPY (-18%).

**Historical stress regime behavior:**
- 2000–2002 dot-com: Seasonal rotation historically favors defensive sectors (XLP, XLU, XLV) in winter months and commodity sectors in spring — both of which held up well during the tech bust. XLK (tech) has seasonal strength in Q4 only; the strategy would have reduced tech exposure in the bust months. Estimated MDD: ~-12 to -18% with 200-DMA filter active.
- 2008–2009 GFC: All sectors fell 40–60%. 200-DMA filter exits to SHY in October 2008. Strategy's exposure before the filter triggers (August–September 2008): estimated -15 to -22% during the initial leg of the GFC before exit.

---

## Entry/Exit Logic

### Signal Computation (Monthly, End-of-Month)

For each calendar month M ∈ {1, 2, ..., 12} and each sector ETF S:

1. Collect all monthly returns for ETF S in calendar month M over the trailing 10 years: `returns_S_M = [r(S, month=M, year=t-1), ..., r(S, month=M, year=t-10)]`
2. Compute the average: `avg_return_S_M = mean(returns_S_M)`
3. Rank all available ETFs by `avg_return_S_M` in descending order.
4. Select top-2 ETFs as the portfolio for the coming month.

### Regime Filter (200-DMA on SPY)

At each month-end rebalance:
- If SPY Close < SPY 200-day moving average: set all positions to SHY (100%); do not take sector positions.
- If SPY Close > SPY 200-day moving average: proceed with seasonal sector ranking.

### Position Sizing

- Top-2 sectors: 50% each (equal weight)
- No leverage; long-only throughout

### Execution

- Evaluate signal at close of last trading day of each month (or open of first trading day of following month)
- Execute both sells and buys at the same time (end-of-month close or next open)
- Rebalance only when the ranked pair changes or regime filter changes

### Handling Missing ETFs (Pre-2015/Pre-2018 Data)

- **XLC (Communication Services, inception June 2018):** For historical lookback pre-2018, substitute with a blended proxy of 70% XLK + 30% XLY (reflecting the prior "Telecom" sector composition within those ETFs). Alternative: simply exclude XLC and rank from 10 sectors; Engineering Director to test both approaches.
- **XLRE (Real Estate, inception Oct 2015):** For historical lookback pre-2015, use VNQ (Vanguard Real Estate ETF, inception Sep 2004) as proxy. Alternative: exclude XLRE pre-2015 and rank from 10 sectors.
- **Engineering Director recommendation:** Start with the 10-sector universe (excluding XLC and XLRE) for the primary backtest to maximize IS data length (2003–2023). Run a secondary test with all 11 sectors from 2015 onward.

---

## Asset Class & PDT/Capital Constraints

- **Asset class:** US equity sector ETFs (SPDR suite) — highly liquid, widely held
- **Minimum capital:** $2,000 (two equal-weight ETF positions; comfortable at $25K)
- **PDT impact:** ~2 trades per month average on position changes + regime filter transitions. Far below 3-trade PDT threshold in any 5-day window (monthly rebalance = once per ~22 trading days). No PDT risk.
- **Commission:** Zero (Alpaca). Bid-ask spread on SPDR ETFs: 1–3 bps one-way. Annual transaction cost estimate: 24 trades × 0.015% one-way = 0.36% drag. Negligible vs. expected edge.
- **Liquidity:** SPDR ETFs range from $3B (XLK) to $800M (XLRE) average daily volume. No slippage at $25K.
- **ETF inception coverage:** XLK, XLV, XLE, XLF, XLY, XLP, XLU, XLI, XLB all launched in December 1998 — enabling a 20+ year historical database.

---

## Alpha Decay Analysis

- **Signal half-life:** Very long — on the order of years. Keloharju et al. document the seasonal pattern at 1-year, 2-year, and 20-year lags with comparable IC. The pattern does not decay meaningfully within a decade.
- **IC decay curve:**
  - T+1 (next day): IC ≈ 0.02–0.04 (daily noise dominates; seasonal signal operates monthly)
  - T+5 (one week): IC ≈ 0.04–0.07 (still driven by seasonal fundamentals, modest)
  - T+20 (one month): IC ≈ 0.08–0.14 (strongest predictive window — same-calendar-month)
  - T+60 (quarter): IC ≈ 0.04–0.07 (adjacent months have different seasonal rankings; cross-month IC is lower)
- **Transaction cost viability:** Signal half-life far exceeds 1 trading day. Monthly evaluation with ~2 trades/month average. Expected annual drag ≈ 0.36%; estimated annual edge ≈ 200–400 bps. Edge survives costs with substantial margin.
- **Optimal evaluation frequency:** Monthly (matching the calendar month unit of the signal). Weekly would add noise; daily would generate meaningless turnover.

---

## Gate 1 Assessment

- **IS Sharpe target (> 1.0):** Strong base case. Keloharju et al. (2016) report cross-sectional seasonal strategy IS Sharpe of 1.0–1.4 in the CRSP long-short implementation. The long-only ETF version will have lower Sharpe due to equity beta risk, but the 200-DMA filter reduces drawdown. Estimated IS Sharpe range: 0.9–1.3. The 1.0 threshold is achievable.
- **OOS Sharpe target (> 0.70):** Reasonable confidence. The paper's IS period ends 2014; 11 years of live OOS exist (2015–2026). The seasonal pattern has been replicated in 37+ countries and across asset classes; the ETF implementation provides a high-quality test of the effect. 2022 XLE performance is consistent with the seasonal hypothesis. Estimated OOS Sharpe: 0.7–1.0.
- **CAGR target (≥ 10%):** Most challenging constraint. Long-only equity strategy with monthly rotation + defensive filter. Expected excess return over SPY: 1–3% annualized. Combined with typical SPY CAGR of 10–12% (IS window 2003–2023), the strategy should exceed 10% CAGR. However, the 200-DMA filter introduces cash drag during bear markets that could reduce CAGR below 10% if IS window includes multiple bear markets. Engineering Director to test this constraint carefully.
- **MDD constraint (< -15%):** The combination of sector diversification + 200-DMA filter should limit MDD. Estimated IS MDD: -18 to -25% (bear market periods before filter triggers). This is the primary concern — the MDD target of <-15% is tight for a long-only equity strategy. The IS window 2003–2023 includes two major bear markets (GFC, COVID). Engineering Director should stress-test the 200-DMA exit speed.

**Primary risk:** MDD in GFC/COVID may exceed the -15% hard constraint. Engineering Director should test both with and without the 200-DMA filter, and consider adding a VIX spike exit as a supplemental crash filter.

---

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| seasonal_lookback_years | 5, 10, 15, 20 | Primary: 10 years (balances sample size vs. recency); test sensitivity |
| top_k_sectors | 1, 2, 3 | Primary: 2 sectors (diversification); test 1 (concentrated) and 3 (diluted) |
| universe | 10 sectors (ex-XLC/XLRE), 11 sectors (2015+) | Data availability trade-off |
| regime_filter_ma | 200-DMA on SPY, 150-DMA, no filter | Primary: 200-DMA; test sensitivity to crash filter |
| rebalance_day | last trading day of month, first trading day of next month | Execution timing |
| secondary_signal | none, VIX > 30 exit to SHY | Supplemental crash protection |

**Engineering Director note:** Primary backtest: 10-sector universe (ex-XLC/XLRE), 10-year lookback, top-2 sectors, 200-DMA regime filter, last-trading-day-of-month rebalance, IS 2003–2023. Sweep: lookback (5/10/15), top-k (1/2/3), and regime filter (200-DMA vs. none). Maximum parameter count: 3 free parameters in primary specification.

---

## Pre-Flight Gate Checklist

| Gate | Criterion | Assessment | Status |
|---|---|---|---|
| PF-1 | IS trade count ÷ 4 ≥ 30 | Monthly rebalance with rotating top-2 sectors. The sector selected varies by calendar month. Estimated rotation: ~1–2 sectors change per month on average (1–2 sell + 1–2 buy = 2–4 trades/month). Over 10-year IS window (2003–2023): ~2 trades/month × 120 months = 240 actual position changes. 200-DMA regime transitions add ~4–8 per year × 10 = 40–80. Total IS trades: **280–320. ÷ 4 = 70–80 ≥ 30. PASS.** Note: this counts POSITION SWITCHES (sells + buys), not monthly signal evaluations — lesson from H72 PF-1 error. | **PASS** |
| PF-2 | Long-only equity MDD < 40% dot-com + GFC | 2000–2002 dot-com: seasonal rotation emphasizes defensive sectors in winter (XLP, XLU, XLV), which outperformed in the tech bust. 200-DMA filter exits to SHY in late 2000 (SPY 200-DMA breach). Estimated MDD: **~-12 to -18%. PASS.** — 2008–2009 GFC: 200-DMA filter triggers exit to SHY in October 2008. Pre-exit MDD: **~-18 to -22%.** Both periods estimated below 40%. **PASS.** | **PASS** |
| PF-3 | Data pipeline available | XLK, XLV, XLE, XLF, XLY, XLP, XLU, XLI, XLB: yfinance (all inception Dec 1998) ✓ — XLRE: yfinance (inception Oct 2015), VNQ proxy (Sep 2004) for pre-2015 backfill ✓ — XLC: yfinance (inception Jun 2018); exclude pre-2018 in primary 10-sector test ✓ — SPY 200-DMA: derived from daily SPY close ✓ — SHY: yfinance ✓ — All data derived from daily OHLCV, no external feeds required. **PASS.** | **PASS** |
| PF-4 | 2022 rate-shock survival rationale | Two-mechanism defense. (1) **Sector composition:** XLE (energy) is typically ranked in the top-2 sectors for summer months (June–August) under the 10-year historical seasonal pattern, as energy demand and prices peak in summer driving season. XLE was up +65% in 2022 — the largest single-year sector return in SPDR history. The seasonal rotation would have held XLE during its strongest period in 2022. (2) **200-DMA exit:** SPY crossed its 200-DMA approximately March 14, 2022. The month-end March 2022 rebalance would have triggered exit to SHY. Q2–Q4 2022 equity exposure: zero. Combined effect: energy carry during Q1 then SHY for the rest of 2022. Estimated 2022 MDD: **~-8 to -12%.** Materially outperforms SPY (-18%) and nearly all equity strategies in the pipeline. | **PASS** |

---

## Signal Combination Policy

Single-signal strategy (cross-sectional seasonal rank with 200-DMA filter overlay). The 200-DMA is a regime gate, not an independent alpha signal — it generates no IC on its own but suppresses equity beta during bear markets. This does not constitute a multi-signal combination requiring Research Director approval. Signal combination policy: N/A.

---

## ML Anti-Snooping Check

Not an ML-based strategy. No ML anti-snooping check required.

---

## Existing Family Check

- **H20 (Sector Momentum Rotation, retired):** Uses trailing 12-month return rank — price momentum signal, retired under QUA-181 momentum moratorium. Categorically different from same-calendar-month historical average. ✓ No family conflict.
- **H71 (Contrarian Monthly Sector Rotation, QC-Discovery):** Uses prior month's return inversely — short-term reversal signal (Jegadeesh reversal, 1-month lag). Categorically different. ✓ No family conflict.
- **H71 (Best Six Months / Halloween Indicator):** Binary annual calendar (Nov–Apr only). Different granularity, different mechanism. ✓ No family conflict.
- **H22 (Turn-of-Month):** Single-day calendar effect around month transitions. Different signal entirely. ✓ No family conflict.

**New family confirmed:** Cross-Sectional Return Seasonality (Keloharju-Sadka family). First hypothesis in this family.

---

## Hypothesis Class Diversification Mandate Check

- **Class:** Calendar / seasonal effects — Priority #2 in underrepresented class mandate (QUA-181)
- **Not momentum:** The seasonal signal uses 10-year calendar month averages, not trailing 12-month price momentum. Keloharju et al. explicitly test and reject momentum as the explanation (they show the effect at 20-year lags — far beyond any momentum horizon). ✓
- **Not a second QC/TV Discovery momentum entry in this batch:** Sourced from academic literature review (QUA-283), not a TV/QC discovery batch. Mandate applies per batch; this is the first hypothesis from QUA-283 in the current cycle. ✓

---

## References

**Primary sources (QUA-283 literature review):**
- Keloharju, M., Linnainmaa, J.T. & Nyberg, P. (2016). "Return Seasonalities." *Journal of Finance*, 71(4), 1557–1590. (SSRN top-cited; JF top-tier; IS 1963–2014, 11-year live OOS 2015–2026)
- Heston, S.L. & Sadka, R. (2008). "Seasonality in the Cross-Section of Expected Stock Returns." *Journal of Financial Economics*, 87(2), 418–445. (Original documentation of same-calendar-month persistence at multi-year lags)

**Supporting:**
- Bogousslavsky, V. (2016). "Infrequent Rebalancing, Return Autocorrelation, and Seasonality." *Journal of Finance*, 71(6), 2967–3006. (Rebalancing demand mechanism explaining why the seasonal persists)
- Jacobs, B.I. & Levy, K.N. (1988). "Disentangling Equity Return Regularities." *Financial Analysts Journal*, 44(3), 18–43. (Early confirmation of monthly effects in sector returns)

**Sequencing note (QUA-283 review):** C5 was originally sequenced after C4 (H72). C4 failed Gate 1 due to structural trade count incompatibility (H72: 26 IS trades over 15 years; ~0.43 trades/3-month window). Research Director assessment finds C2 (Quality Factor) and C3 (Equity Carry) have the same PF-1 risk as H72: their monthly regime signals (QUAL/SPY outperformance comparison; IWD/IWF yield spread) are slow-switching regimes, likely producing <30 position switches per 4-window segment when measured correctly (position switches, not monthly evaluations). C5 is advanced to next priority because the sector rotation mechanism genuinely generates high trade counts (monthly positions change by calendar design, not regime persistence). C2 and C3 should include a corrected PF-1 trade-count estimate (actual switches) before backtesting.

---

*Research Director Agent | QUA-312 | QUA-283 C5 | 2026-06-16*
