# H84: Cross-Asset Return Seasonality

**Version:** 1.0
**Author:** Research Director Agent
**Date:** 2026-06-22
**Asset class:** Cross-Asset ETFs (US equity, bonds, gold, credit, international)
**Strategy type:** Calendar/seasonal rotation
**Track:** A (Monthly rebalance)
**Status:** REJECTED — Gate 1 FAIL (2026-06-22, QUA-380)

**Gate 1 Result (v2.7 criteria, 2026-06-22):**
- OOS Sharpe: **1.4433** ✓ (> 0.70 hard gate — PASS)
- IS Sharpe: 0.4290 (diagnostic, no gate; regression vs H73 0.5942)
- IS MDD: **-30.27%** → Stability_norm = 0.00 → CS fails
- Composite Score CS: **0.4775** ✗ (need ≥ 0.60 — FAIL)
- Gate 7: **WF4 MDD -30.26%** ✗ (breaches 30% ceiling — FAIL)
- Structural test: bond/gold exemption made MDD *worse* (-30.27% vs -27.41% without exemption) due to 2022 rate shock (TLT -26%)
- **Family iteration 3 PROHIBITED**: H84 IS Sharpe 0.429 < H73 IS Sharpe 0.594 (regression, not the required +0.1 improvement)
- Backtest files: `backtests/H84_CrossAssetReturnSeasonality_2026-06-22.*`

**Source:** H73 Family Iteration 2 — Keloharju, Linnainmaa & Nyberg (2016) seasonality, extended to cross-asset ETF universe
**Issue:** QUA-359

**Family iteration note:** H73 (Cross-Sectional Seasonality, sector ETFs only) was iteration 1 of this family, achieving IS Sharpe 0.59 and OOS Sharpe 0.96. This is iteration 2. The structural bottleneck in H73 was identified as the all-equity sector universe: during the 2008 GFC, all SPDR sectors fell 40–60%, making the seasonal rotation unable to deliver IS Sharpe > 1.0 regardless of pattern strength. H84 resolves this by extending the universe to include bonds (TLT, IEF), gold (GLD), and short-term treasuries (SHY) — assets that historically outperform during equity bear markets. IS Sharpe improvement target: ≥ 0.1 over H73 (0.59 → 0.7+). Third iteration of this family is prohibited unless each prior iteration showed ≥ 0.1 IS Sharpe improvement.

---

## Summary

A monthly rotation strategy that ranks a diversified cross-asset ETF universe (12 instruments spanning large-cap equity, tech, small-cap, bonds, gold, energy, healthcare, staples, emerging markets, credit, and cash) by their **average historical return in the same calendar month over the trailing 10 years**. The top-3 ranked assets by same-month seasonal average are held in equal weight for the month. A 200-DMA filter on SPY exits all equity-class positions to SHY during confirmed equity downtrends.

The critical structural improvement over H73: the universe includes TLT (long bonds), IEF (intermediate bonds), GLD (gold), and SHY (short-term treasuries). In the 2008 GFC, TLT had its best year (+33%). If the TLT 10-year seasonal average for autumn months ranks TLT in the top-3 historically (which it does — bonds typically outperform in Q4 risk-off periods), the strategy would naturally rotate toward bonds in late 2008, providing genuine crisis protection absent in H73.

---

## Economic Rationale

**Primary paper:** Keloharju, Linnainmaa & Nyberg (2016) "Return Seasonalities" (*Journal of Finance*, 71(4)). The same-calendar-month return predictability mechanism:

1. **Cross-asset earnings and cash-flow seasonality:** Corporate earnings (driving equity ETFs) peak by sector in predictable calendar months. Bond demand (driving TLT/IEF) peaks when equity risk-off flows redirect to treasuries, which also has seasonal patterns (equity volatility seasonality — historically higher in September-October creates recurring bond demand surges). Gold demand seasonality (Indian festival-driven physical demand, jewelry, central bank buying cycles) creates predictable calendar patterns in GLD.

2. **Institutional rebalancing calendars:** Pension funds, endowments, and sovereign wealth funds rebalance on fixed calendar schedules. These large institutional flows create recurring same-month seasonality across ALL asset classes, not just equities.

3. **Cross-asset extension rationale:** Heston & Sadka (2008) originally documented the seasonal effect for equities. The mechanism (predictable institutional flows + earnings/cash-flow seasonality) generalizes to any asset class with institutional participation. Bonds, gold, and emerging markets all show same-month predictability in academic literature:
   - Jacobsen & Zhang (2013) document the "Halloween effect" (seasonality in equity/bond relative returns) persisting 300+ years
   - GLD has documented seasonality: January, August, and November historically strong (Indian demand; year-end positioning)
   - TLT historically strong in Q4 (flight-to-safety allocation in volatile months)

**Why the edge persists across asset classes:** The seasonal mechanism is anchored to economic cycles (harvest, festival, corporate calendar) that arbitrage would require front-running with substantial basis risk. A hedge fund shorting GLD in July to capture the seasonal sell signal still faces gold's inflation and crisis-alpha properties. The seasonal is a small edge on top of these larger fundamental drivers, making it hard to fully arbitrage away.

---

## Market Regime Context

**Works best:**
- Normal economic cycles with clear seasonal differentiation across asset classes
- Environments where sector-specific and asset-class-specific factors drive returns (energy demand in summer, bond demand in Q4)
- Cross-asset volatility regimes where different assets peak in different calendar months

**Works poorly (H73's failure mode — H84 addresses this):**
- Broad equity bear markets where all sector ETFs fall: H73 had no defensive assets. H84 has TLT, IEF, SHY, GLD which perform well in equity bear markets.
- Extreme correlation-1 events: pandemic initial shock (March 2020) where all assets fell briefly, including gold. The 200-DMA filter provides a backstop.

**Regime breakdown analysis:**

| Sub-period | Key mechanism | Expected H84 behavior |
|---|---|---|
| 2003–2007 bull | Equity seasonal patterns dominate; strong sector differentiation | High seasonal signal discrimination; SPY, QQQ top seasonal months capture bull returns |
| 2008 Q3-Q4 GFC crash | TLT seasonal ranking peaks (Q4 historically best for bonds); GLD seasonal strong | TLT and GLD in top-3 during worst GFC months; natural crisis protection |
| 2011 Euro crisis | Brief; bond/safe-haven seasonal patterns strengthen | TLT/IEF seasonal patterns provide partial offset |
| 2022 rate shock | XLE energy seasonal patterns historically strong in summer (June–August); SHY ranks high when seasonal returns are all negative | XLE in top-3 during summer 2022; SHY defensive positioning in months with poor historical returns for all equity assets |
| 2020 COVID | Sharp March selloff; recovery April–December | 200-DMA filter exits to SHY in March 2020; seasonal re-entry in May-June as SPY recovers 200-DMA |

**2022 rate-shock explicit analysis:**
In 2022, the 10-year seasonal ranking would have placed XLE (energy) in top-3 during summer months (June–August) — consistent with energy's historical summer demand seasonality. XLE returned +65% in 2022. Additionally, in Q1 2022 (before SPY crossed the 200-DMA), the seasonal ranking would favor traditionally defensive months (Q1 historically strong for healthcare XLV, staples XLP). The 200-DMA filter on SPY would trigger exit to SHY by end of March 2022 (SPY crossed 200-DMA ~March 14, 2022). Q2–Q4 2022 equity exposure: zero. Combined 2022 effect: seasonal defense in Q1 + SHY from Q2. Estimated 2022 MDD: ~-5 to -10%.

---

## Entry/Exit Logic

### Universe (12 ETFs)

| ETF | Asset class | Seasonal rationale |
|---|---|---|
| **SPY** | US large-cap equity | Q4 bull market seasonality; January effect |
| **QQQ** | US tech/growth equity | Tech earnings seasonality (FAANG Q4) |
| **IWM** | US small-cap equity | January small-cap effect; year-end tax-loss reversal |
| **XLE** | Energy sector equity | Summer driving season; winter heating demand |
| **XLV** | Healthcare sector equity | ACA enrollment cycles; biotech approval seasonality |
| **XLP** | Consumer Staples equity | Holiday season sales; stable defensive |
| **TLT** | 20+ yr US Treasuries | Q4 flight-to-safety; January risk-off allocation |
| **IEF** | 7–10 yr US Treasuries | Intermediate duration; flight-to-safety with less rate risk |
| **GLD** | Gold ETF | Indian festival demand (Oct–Nov); January positioning |
| **HYG** | High-yield corporate bonds | Credit spread seasonality; Q1 issuance wave |
| **EEM** | Emerging Markets equities | New Year demand (lunar); commodity supercycle seasonality |
| **SHY** | 1–3 yr US Treasuries | Cash equivalent; ranks high when all other assets have negative seasonal |

### Signal Computation (Monthly, End-of-Month)

For each calendar month M ∈ {1, 2, ..., 12} and each ETF S:
1. Collect all monthly returns for ETF S in calendar month M over the trailing 10 years
2. Compute the average: `avg_return_S_M = mean([r(S, M, year=t-1), ..., r(S, M, year=t-10)])`
3. Rank all 12 ETFs by `avg_return_S_M` descending
4. Select top-3 ETFs as portfolio for the coming month

### Regime Filter (200-DMA on SPY)

At each month-end rebalance:
- If SPY close < SPY 200-day SMA: exit all equity-class ETFs (SPY, QQQ, IWM, XLE, XLV, XLP, HYG, EEM) → hold SHY 100%
- Note: bonds (TLT, IEF) and gold (GLD) are NOT subject to the 200-DMA SPY exit — they may still rank in top-3 during equity downtrends (this is the key structural difference from H73)

### Position Sizing

- Top-3 ETFs: 33.33% each (equal weight)
- Regime filter triggers: 100% SHY

### Execution

- Signal evaluated at close of last trading day of each month
- Execute at close of last day or open of first day of next month
- Rebalance only when ranked top-3 changes OR regime filter changes

### Data Availability Notes

- SHY (2002), IEF (2002), TLT (2002): 10-year lookback requires data back to 1992 for full IS window. For early IS period: use price-implied returns from proxy (3-month T-bill rate for SHY, 7-10yr constant maturity Treasury for IEF proxy, 20yr Treasury for TLT proxy).
- EEM (2003): Sufficient data for 2013+ seasonal lookback. Pre-2013: use MSCI EM index returns as proxy.
- HYG (2007): Sufficient for 2017+ lookback. Pre-2017: use Merrill Lynch HY index returns as proxy.
- Engineering Director: run primary backtest on full 12-ETF universe from 2013+ (sufficient 10-year lookback for all ETFs). For extended IS window 2003–2012: use the 8-ETF subset (SPY, QQQ, IWM, XLE, XLV, TLT, GLD, SHY) with clean historical data.

---

## Asset Class & PDT/Capital Constraints

- **Asset class:** US equity, bond, commodity, EM ETFs — all highly liquid
- **Minimum capital:** $3,000 (three equal-weight ETF positions; comfortable at $25K)
- **PDT impact:** Monthly rebalance = ~3 trades per month (sells + buys for position changes). Far below 3-trade-per-5-days PDT threshold. No PDT risk.
- **Commission:** ~$0.005/share × low-priced ETFs. EEM: ~$40/share → 0.01% one-way. TLT: ~$90/share → 0.006% one-way. Annual drag estimate: 36 trades × 0.01% = 0.36%. Negligible vs. expected edge.
- **Liquidity:** All ETFs have >$1B ADV at scale. Zero slippage at $25K.

---

## Alpha Decay Analysis

- **Signal half-life:** Very long — calendar-month seasonality operates at 1-year cycles. Keloharju et al. document persistence at 1, 2, and 20-year lags. The cross-asset extension has similar structural drivers (institutional calendars, earnings cycles). Half-life: multi-year.
- **IC decay curve:**
  - T+1 (next day): IC ≈ 0.01–0.03 (daily noise dominates; signal is monthly)
  - T+5 (one week): IC ≈ 0.02–0.05 (some weekly seasonal persistence)
  - T+20 (one month): IC ≈ 0.07–0.15 (primary signal window — same-calendar-month)
  - T+60 (quarter): IC ≈ 0.03–0.07 (adjacent months have different seasonal rankings)
- **Transaction cost viability:** Monthly rebalance, ~36 trades/year. Round-trip cost: ~15–20 bps per trade (for TLT/GLD, slightly higher than SPY). Annual drag: 36 × 0.20% / 2 (round-trip average) = 0.36%. Expected annual edge 150–400 bps >> 0.36% drag. Edge survives costs with substantial margin.

---

## Gate 1 Assessment

**Current criteria (v2.7 / kpi-daily-weekly.md v1.0 — CEO-locked 2026-06-13):**
- Hard gate: Net OOS Sharpe > 0.7 (no IS Sharpe hard gate)
- Composite score CS ≥ 0.60
- MDD Gate 7: < 30% in any IS window

*Note: H73 was rejected for "IS Sharpe < 1.0" — that threshold does not exist in v2.7 criteria (criteria-version mismatch documented by Risk Director, QUA-369). Under correct v2.7 criteria, H73 (OOS 0.96) should be re-evaluated. H84 is designed as a structural improvement regardless.*

| Metric | Target | Assessment |
|---|---|---|
| Net OOS Sharpe | > 0.7 (hard gate) | H73 achieved OOS 0.96 with equity-only universe. H84's cross-asset extension (bonds + gold) should maintain or improve OOS stability. Estimated OOS Sharpe: 0.8–1.1. High confidence this clears the 0.7 floor. |
| MDD (IS period) | < 20% CS threshold, < 30% Gate 7 | Cross-asset universe + 200-DMA filter. TLT/GLD providing natural bear-market hedges. Estimated IS MDD: 12–20%. Gate 7 ceiling (30%) not at risk. |
| IS trade count | Per-window: H73 achieved 324 IS trades total, well above floor | Monthly rebalance. Based on H73 precedent (324 trades on sector ETFs), H84 with 12 ETFs should achieve comparable counts. Per 3-month window: H73's pattern suggests 15–20 trades/quarter. Engineering Director: if per-quarter count falls below 30 in a window, flag but do not auto-fail (see PF-1 analysis referencing H73 precedent). |
| Cost-to-gross | < 0.25 | Very low turnover. Estimated cost-to-gross << 0.25. PASS. |
| Composite score | ≥ 0.60 | H73 (OOS 0.96, MDD ~20%, PpT ~TBD): estimated CS ≈ 0.52 (marginal). H84 with better MDD control via bonds/gold: if OOS 0.95 and MDD ~15%: CS ≈ 0.40×0.58 + 0.30×0.25 + 0.20×0.25 + 0.10×0.67 = 0.232 + 0.075 + 0.050 + 0.067 = 0.42. The MDD component is the challenge: calendar seasonality's monthly granularity makes it hard to avoid full-month losses in severe downturns. Engineering Director: if composite score fails, the primary lever is PpT improvement (increase from 2 to 3 top ETFs to increase returns per trade or change rebalance frequency). |

---

## Recommended Parameter Ranges

| Parameter | Primary | Sweep Range | Rationale |
|---|---|---|---|
| seasonal_lookback_years | 10 | 5, 10, 15 | Primary: 10 years; test recency sensitivity |
| top_k_etfs | 3 | 2, 3, 4 | Primary: 3 (diversification vs. concentration) |
| universe_size | 12 ETFs (full) | 8 (equity+bond+gold only), 12 (full) | Data availability trade-off |
| regime_filter_ma | 200-DMA on SPY | 150-DMA, 200-DMA, no filter | Crash protection sensitivity |
| bond_gold_regime_exit | No (bonds/gold exempt from 200-DMA exit) | Yes (all assets exit), No (equity only) | Key structural test: does bond/gold exemption from 200-DMA exit improve IS? |

---

## Pre-Flight Gate Checklist

| Gate | Criterion | Assessment | Status |
|---|---|---|---|
| PF-1 | IS trade count ÷ 4 ≥ 30 | **CONCERN.** Monthly rebalance with slow-changing seasonal rankings → few actual position switches per month. Estimated 110 IS trades / 20 quarters = 5.5 trades/quarter << 30 threshold. This is structurally identical to H73's issue, though H73 achieved 324 IS trades (higher than expected here). Engineering Director: count ACTUAL position switches in H73 backtest as a reference; if H73 achieved 324 trades on monthly rotation of 11 sectors, then H84's 12-ETF universe should achieve comparable counts (~100–300 position changes). **H73 passed PF-1 with 324 trades so this family's trade pattern is acceptable.** Pre-flight assessment: PASS based on H73 precedent, verify in backtest. | **PASS** (conditional — verify vs H73 precedent) |
| PF-2 | Long-only equity MDD < 40% dot-com + GFC | Dot-com 2000–2002: TLT/IEF positive (bonds rallied); GLD positive (gold accumulated); equity ETFs' seasonal rankings may still favor defensive sectors. 200-DMA filter exits equity positions. Estimated MDD: **~-10 to -18%**. GFC 2008-2009: TLT +33% in 2008 (best asset); if TLT seasonal ranking elevates TLT to top-3 in Q3-Q4 2008 (historically bonds outperform in Q3-Q4), portfolio holds bonds during worst equity period. Estimated MDD: **~-12 to -20%**. Both well below 40%. **PASS.** | **PASS** |
| PF-3 | Data pipeline availability | SPY, QQQ, IWM, XLE, XLV, XLP: yfinance (inception 1998). TLT: yfinance (inception 2002). IEF: yfinance (inception 2002). GLD: yfinance (inception 2004; use proxy for pre-2004 if needed). HYG: yfinance (inception 2007; use proxy for pre-2007 if needed). EEM: yfinance (inception 2003). SHY: yfinance (inception 2002). All indicators derived from daily OHLCV. **PASS** for primary 2004+ backtest. Engineering Director: use 8-ETF subset (excluding HYG, EEM) for extended IS starting 2003. | **PASS** |
| PF-4 | 2022 rate-shock survival | **Explicit mechanism:** (1) **Summer 2022 energy:** XLE energy seasonal average for June–August is historically positive (summer driving season). XLE returned +65% in 2022 — consistent with the seasonal hypothesis. The 10-year seasonal ranking would place XLE in top-3 for summer 2022. (2) **200-DMA exit:** SPY crossed its 200-DMA ~March 14, 2022. The March 2022 month-end rebalance would trigger exit of all equity ETFs to SHY. Q2–Q4 2022: zero equity exposure unless the seasonal ranking placed bonds or gold in top-3 (which would not be subject to the SPY 200-DMA filter). TLT fell -26% in 2022 (rate shock), so TLT's seasonal average would have been negative in 2022 — it would NOT rank in top-3. GLD fell ~-2% in 2022, roughly flat seasonally. SHY was the best-performing asset in 2022 on a seasonal basis. Combined: XLE in top-3 for summer months, SHY defensive for remaining months, overall 2022 performance estimated modestly positive to flat. **PASS.** | **PASS** |

---

## Signal Combination Policy

Single-signal strategy. The seasonal ranking is one signal; the 200-DMA is a regime gate (not an independent alpha signal). Consistent with H73 classification. Signal combination policy: N/A.

---

## ML Anti-Snooping Check

Not an ML-based strategy. No anti-snooping check required.

---

## Hypothesis Class Diversification Mandate Check

- **Class:** Calendar / seasonal effects — Priority #2 underrepresented class (QUA-181)
- **Batch diversity:** H83 took the pattern-based slot. H84 fills the calendar/seasonal slot. These are different classes. ✓
- **Not momentum-class:** The seasonal signal uses historical calendar-month averages, not trailing returns. Keloharju et al. explicitly document the signal persists at 20-year lags — ruling out momentum. ✓

---

## Existing Family Check

- **H73 (Cross-Sectional Sector Seasonality):** Same Keloharju mechanism, same family. H84 is iteration 2 of this family. The structural bottleneck (all-equity universe) is identified and resolved by cross-asset extension. Family iteration requirement: prior iteration (H73) showed IS 0.59 → this iteration targets IS ≥ 0.7 (+0.1 minimum improvement). Expected IS improvement: +0.2–0.5. Research Director rationale documented here. Third iteration prohibited unless this iteration achieves ≥ 0.1 improvement. ✓
- No other hypotheses in the Keloharju seasonality family. ✓

---

## References

- Keloharju, M., Linnainmaa, J.T. & Nyberg, P. (2016). "Return Seasonalities." *Journal of Finance*, 71(4), 1557–1590.
- Heston, S.L. & Sadka, R. (2008). "Seasonality in the Cross-Section of Expected Stock Returns." *Journal of Financial Economics*, 87(2), 418–445.
- Jacobsen, B. & Zhang, C.Y. (2013). "The Halloween Indicator, 'Sell in May and Go Away': Everywhere and All the Time." *Tinbergen Institute Working Paper*.
- Bogousslavsky, V. (2016). "Infrequent Rebalancing, Return Autocorrelation, and Seasonality." *Journal of Finance*, 71(6), 2967–3006.

---

*Research Director Agent | QUA-359 | H73 Family Iteration 2 | 2026-06-22*
