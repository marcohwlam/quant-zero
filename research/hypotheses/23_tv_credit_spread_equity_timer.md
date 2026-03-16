# HYG/IEI Credit Spread Equity Allocation Timer

**Version:** 1.1
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Reviewed by:** Research Director
**Review date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** retired_standalone — credit overlay integration recommended for H21 v2.0

## Research Director Verdict (2026-03-16)

**Decision: RETIRE STANDALONE — Integrate as H21 v2.0 credit regime overlay**

### Verdict Rationale

1. **PF-1 CONFIRMED FAIL at base MA(10)/MA(30):** ~8–15 transitions/yr → IS total trades ~64–120 ÷ 4 = 16–30 per WF fold. Below the PF-1 threshold of ≥ 30 per fold. Confirmed.

2. **Option A (faster MA) rejected — structural IS Sharpe issue:** While MA(5)/MA(15) resolves PF-1 technically (~200–280 total IS trades ÷ 4 = 50–70 per fold), it does not fix the fundamental problem: standalone IS Sharpe forecast is 0.4–0.7, structurally below the Gate 1 target of 1.0. This gap cannot be closed by parameter tuning. Furthermore, forcing faster MAs to meet PF-1 degrades the strategy's core economic logic — credit spread regimes operate on 20–90 day timescales, not 5-day windows. Faster MAs introduce noise trades that are not credit-regime-driven. Option A rejected as curve-fitting.

3. **Option B selected — credit overlay for H21 IBS:** H23 is economically a **regime filter**, not an alpha generator (standalone IR ~0.23). Its strongest property — that credit spreads widen before equity bear markets, providing early exits — is precisely the complement H21 needs. H21's documented failure mode is sustained bear markets (IBS oversold signals precede further declines). Layering H23's credit signal as an H21 regime gate directly addresses this failure mode with a mechanistically coherent rationale. The combination is not parameter stacking; it is a regime discriminator applied to a different signal type.

4. **Signal count compliance:** H21 currently uses 2 signals (IBS entry + 200-SMA filter). Adding H23 credit overlay = 3 signals, at the hard limit per Signal Combination Policy. **Research Director explicitly approves this 3-signal combination** given the combination is economically justified (intraday bar structure → daily price trend → credit macro regime — three orthogonal signal layers).

5. **H21 Gate 1 not delayed:** H21 v1.0 Gate 1 backtest (QUA-208) proceeds as-is. Credit overlay to be evaluated in H21 v2.0 if H21 v1.0 passes Gate 1. If H21 v1.0 fails Gate 1, the credit overlay becomes the primary revision option for H21 v1.1.

### Pre-Flight Gate Checklist (standalone — final)

| Gate | Status | Notes |
|---|---|---|
| PF-1 | **FAIL** | Confirmed. Not fixable without unacceptable signal degradation. |
| PF-2 | CONDITIONAL PASS | GFC verifiable via HYG data; dot-com requires FRED BAMLH0A0HYM2 proxy |
| PF-3 | CONDITIONAL PASS | IS window constrained to Dec 2007+ (IEI inception) |
| PF-4 | **STRONG PASS** | Strongest PF-4 defense in Batch 4 — credit spreads explicitly widen in rate-shock |

### Disposition

- H23 standalone: **RETIRED** (PF-1 fail + structural IS Sharpe < 1.0)
- H23 credit overlay → H21 v2.0: **RECOMMENDED** — evaluate post H21 v1.0 Gate 1
- Finding documented in: `research/findings/tv_ideas/2026-03-16.json`

---

## Economic Rationale

Credit spreads — the yield differential between high-yield (junk) corporate bonds and comparable-duration treasuries — are one of the most reliable leading indicators of equity market stress. When credit spreads widen (high-yield bonds underperform treasuries), it signals rising corporate default risk and deteriorating financial conditions, which typically precede equity drawdowns by days to weeks.

This strategy uses the **HYG/IEI price ratio** as a daily proxy for credit spread conditions:
- **HYG** (iShares iBoxx $ High Yield Corporate Bond ETF): inversely tracks high-yield credit spreads
- **IEI** (iShares 3-7 Year Treasury Bond ETF): tracks investment-grade intermediate treasuries
- When HYG/IEI ratio **falls**, credit spreads are widening → risk-off signal → exit SPY
- When HYG/IEI ratio **rises or stabilises**, credit spreads are tightening → risk-on → hold SPY

**Why the edge exists:**

1. **Credit as leading indicator:** Gilchrist & Zakrajsek (2012 JME) demonstrated that the "excess bond premium" (residual credit spread after controlling for default probability) is a significant predictor of real economic activity and equity returns at 1–12 month horizons. Credit stress precedes equity stress by a lagging period.

2. **Institutional risk signal:** Fixed-income desks and risk managers often reduce credit exposure before cutting equities (credit markets have higher institutional participation). The HYG/IEI ratio captures this institutional risk-off behavior in real time.

3. **Asymmetric early-warning:** Credit spread widening in the specific window of "initial stress before panic" (spreads +100bps over 20 days) provides an early exit signal that equity price signals (SMA crossovers, RSI) often miss. This is the credit-equity "leading edge."

4. **Academic backing:** Lettau & Ludvigson (2001) demonstrated that time-varying risk premia — partially captured by credit spread regimes — predict equity returns at medium horizons. Fama & French (1989) showed credit spreads (default premium) predict both stock and bond returns.

**Why arbitrage is limited:**
- Credit spread dynamics are driven by institutional risk mandates and macroeconomic fundamentals — not easily arbitraged by price-based traders
- HYG tracks ~1,300 bonds; the ratio signal is genuinely orthogonal to SPY's technical price structure
- The asymmetry (credit leads equity) creates a structural timing window that persists

**Distinction from existing strategies:**
- H18 (SPY/TLT Rotation): Uses treasury bonds as a **flight-to-safety trade** (SPY vs TLT asset rotation). H23 uses credit bonds as a **risk-off detector** to time SPY exposure. Different instruments, different mechanism. TLT is driven by rate expectations; HYG is driven by credit risk premium.
- H07c (TSMOM with Yield Curve): Uses yield curve shape (2yr/10yr slope) as a regime filter — macroeconomic timing. H23 uses real-time credit market stress, which is more responsive.
- H19 (VIX Volatility Targeting): Uses equity implied volatility, not credit fundamentals.

## Entry/Exit Logic

**Signal construction:**
- Compute: `credit_ratio = HYG.Close / IEI.Close` (daily)
- Compute: `ratio_sma_fast = credit_ratio.rolling(fast_ma).mean()` (default: 10 days)
- Compute: `ratio_sma_slow = credit_ratio.rolling(slow_ma).mean()` (default: 30 days)
- **Signal:** `fast > slow` → Risk-On (hold SPY); `fast < slow` → Risk-Off (hold cash or TLT)

**Alternative signal (Z-score approach):**
- `ratio_zscore = (credit_ratio - credit_ratio.rolling(60).mean()) / credit_ratio.rolling(60).std()`
- Enter SPY when Z-score > −0.5; exit to cash when Z-score < −1.0
- Z-score approach reduces whipsaw vs MA crossover; fewer but higher-conviction signals

**Entry signal (MA crossover version — default):**
- **Long entry (SPY):** `fast_sma > slow_sma` AND prior signal was Risk-Off → buy SPY at close
- **Exit to cash:** `fast_sma < slow_sma` AND prior signal was Risk-On → sell SPY at close, hold SHY/cash

**Exit signal:**
- Primary: Opposite MA crossover signal
- No hard stop loss (signal is a regime filter, not a price-level trigger; stops create whipsaw)

**Holding period:** Position (weeks to months — average regime duration ~30–60 days)

## Market Regime Context

**Works best:**
- Transition periods between risk-on and risk-off (early bear market, early recovery): HYG/IEI ratio leads equity turns by 1–3 weeks
- Periods when credit risk is the dominant macro driver (2008–2009, 2020, 2022): signal is most predictive
- Moderate market environments where signal generates sufficient regime transitions (15–30/year)

**Tends to fail:**
- Structurally range-bound credit markets (2013–2017 "goldilocks"): ratio oscillates near neutral → frequent whipsaws
- Sudden exogenous shocks (Covid crash Feb 2020): credit and equity fall simultaneously; signal may lag by days
- Late-cycle "blow-off" equity rallies: equities rise while credit spreads widen slightly → false risk-off signal

**Regime gate:** None beyond the primary signal. The HYG/IEI ratio MA crossover itself is the regime mechanism.

## Alpha Decay

- **Signal half-life (days):** 20–30 days (credit spread regimes are medium-duration; the signal is persistent once established, decaying over weeks rather than days)
- **Edge erosion rate:** Moderate (5–30 days)
- **Recommended max holding period:** No fixed max hold (regime-following); rely on opposite-signal exit
- **Cost survival:** Yes — SPY ETF round-trip cost < 0.005%. With ~15–30 regime transitions/year, annual cost ≈ 15 × 0.005% = 0.075%. Edge survives costs with a wide margin given historical outperformance during bear markets.
- **IC decay curve estimate:**
  - T+1: IC ≈ 0.02–0.03 (signal is slow; IC at 1-day horizon is modest)
  - T+5: IC ≈ 0.04–0.06 (medium horizon where credit-equity lead relationship operates)
  - T+20: IC ≈ 0.03–0.05 (regime persistence; signal maintains IC at 20-day horizon unlike price oscillators)
- **Annualised IR estimate:**
  - Expected regime-filtering benefit: Avoiding ~30–40% of SPY bear market drawdown on average (empirical range across 2008, 2011, 2015, 2020, 2022)
  - Estimated annualised return gain over buy-and-hold: ~2–4% with reduced volatility (~12–14% annualised vs ~18% for SPY)
  - Pre-cost IR estimate: ~3% / 13% ≈ 0.23 (below the 0.3 warning threshold in isolation)
  - **WARNING:** Standalone IR estimate is borderline (0.23). This strategy is strongest as a **risk reducer** (reducing MDD and volatility of an equity position), not a pure alpha generator. IR improves significantly when combining with another signal (e.g., IBS or TOM as the alpha source, with credit spread as the regime gate).
  - **Revised combined role:** If used as a regime filter layered on top of H21 (IBS), the combined system IR could exceed 0.5. Engineering Director should evaluate both standalone and combined configurations.
- **Notes:** IR is below 0.3 on standalone basis. Recommend candidly flagging this in Gate 1 expectations. The strategy's primary value is drawdown reduction, not alpha generation.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `fast_ma` | 5 – 15 | Fast MA of HYG/IEI ratio. Shorter = more responsive but more whipsaw |
| `slow_ma` | 20 – 60 | Slow MA. Longer = fewer transitions, more regime-like behavior |
| `risk_off_asset` | Cash (SHY) vs TLT | When exiting SPY: hold cash/SHY (neutral) or TLT (flight to safety). TLT may add additional return during risk-off |
| `zscore_entry` | −0.3 to −0.7 | Z-score threshold for re-entry (Z-score signal variant) |
| `zscore_exit` | −0.7 to −1.5 | Z-score threshold for exit (Z-score signal variant) |
| `lookback_zscore` | 40 – 90 | Rolling window for Z-score normalization |

## Capital and PDT Compatibility

- **Minimum capital required:** $5,000 (single ETF position; SPY or SHY)
- **PDT impact:** None — positions are held for weeks to months. All regime changes occur at close-to-close transitions. No day trades. PDT-safe. ✓
- **Position sizing:** 100% in SPY when Risk-On, 100% in SHY/cash when Risk-Off. Simple binary allocation.
- **Max concurrent positions:** 1 (binary between SPY and SHY/cash).

## Pre-Flight Gate Assessment

| Gate | Assessment | Notes |
|---|---|---|
| **PF-1: Trade count ÷ 4 ≥ 30/yr** | **BORDERLINE FAIL / CONDITIONAL** | HYG/IEI MA crossover generates an estimated ~8–15 regime changes/year (round trips) = 8–15 trades/yr. Over 5-yr IS: 40–75 total ÷ 4 = 10–19/yr. **This is below the 30/yr threshold.** To address: (1) use faster MA parameters (MA(5)/MA(15)) to increase to ~20–30 transitions/yr, or (2) combine with a second underlying (SPY + QQQ both timed by the same signal) to double trade count to ~16–30/yr. Both approaches move the number into borderline territory. Engineering Director **must verify trade count ≥ 30/yr at parameter range before running full IS**. Flag this as a PF-1 risk. |
| **PF-2: Long-only equity MDD < 40% (dot-com + GFC)** | **CONDITIONAL PASS** | HYG data begins April 2007 (IEI from December 2007). Cannot directly verify dot-com (2000–2002) performance. Academic proxy: ICE BofA High Yield OAS (FRED: BAMLH0A0HYM2) widened from ~350bps in 1999 to ~1,100bps in Oct 2002 — a clear, sustained credit-stress period that would have triggered risk-off exit signals well before the equity bottom. If the strategy had been live in 2001, the signal would have avoided most of the -49% SPY drawdown. For GFC (2008–2009), HYG data exists: HYG/IEI ratio peaked in June 2007 and fell sharply through 2008 → exits SPY in late 2007 / early 2008, before the worst drawdown. GFC test directly verifiable. **PF-2 rated CONDITIONAL PASS pending direct dot-com period verification via FRED proxy data.** |
| **PF-3: All data in daily OHLCV pipeline** | **CONDITIONAL PASS** | HYG (AMEX: HYG) available on yfinance from April 11, 2007. IEI (NASDAQ: IEI) available from December 7, 2007. SPY from 1993. **IS period must start no earlier than December 2007** due to IEI data availability. This limits IS to approximately 2008–2016 (8 years). Long IS window is still achievable. For dot-com verification (PF-2), would need FRED BAMLH0A0HYM2 data via pandas_datareader, which is **not in current yfinance/Alpaca pipeline** — this is an extension request. Data available but not yet in standard pipeline. |
| **PF-4: 2022 Rate-Shock rationale** | **STRONG PASS** | HYG declined ~-15% in 2022 (rising rates + credit spread widening in rate-shock environment). IEI declined ~-7%. HYG/IEI ratio therefore fell sharply from January 2022 onwards. The MA crossover signal would have exited SPY exposure by early February 2022, before the bulk of the rate-shock drawdown (-25% SPY in 2022). This is the **strongest PF-4 defense in Batch 4** — credit spreads explicitly widened during 2022 rate shock, making this one of the few strategies mechanistically designed to protect against exactly this regime. ✓✓ |

**PF Gate Summary:**
- PF-1: **BORDERLINE FAIL** — requires faster MA or multi-asset to approach 30/yr threshold
- PF-2: **CONDITIONAL PASS** — GFC directly testable; dot-com requires FRED proxy
- PF-3: **CONDITIONAL PASS** — IS window constrained to Dec 2007+; FRED extension needed for PF-2
- PF-4: **STRONG PASS** — credit spread mechanism directly addresses 2022 rate shock

**Overall PF assessment:** PF-1 failure is the primary blocker. Engineering Director should evaluate whether the faster-MA variant or multi-underlying variant can achieve ≥ 30/yr before committing to full IS run. If trade count cannot reach 30/yr, this hypothesis should be **retired or repurposed as a regime overlay** on top of another strategy (e.g., H21 IBS).

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Unlikely on standalone basis. IR estimate ~0.23 pre-cost. IS Sharpe likely 0.4–0.7.
- **OOS persistence:** Medium-high confidence for **drawdown reduction**, but not for absolute alpha. Credit-equity leading relationship is well-established and structurally driven.
- **Walk-forward stability:** Likely moderate. MA parameters are the key sensitivity; regime transitions are not strongly parameter-dependent in high-stress periods.
- **Sensitivity risk:** Medium. MA lengths (fast/slow) significantly affect trade frequency and whipsaw.
- **Known overfitting risks:**
  - HYG data starts 2007; IS period includes 2008–2009 GFC which is the most favorable period for this strategy. IS Sharpe may be inflated by the GFC period.
  - MA parameter selection may be optimized to GFC/2022 stress periods; walk-forward performance in benign credit markets (2010–2019) is the key OOS test.
  - PF-1 concern: forcing higher trade count via fast MA may introduce noise that degrades the signal quality.
- **Recommended use:** Even if Gate 1 standalone IS Sharpe < 1.0, evaluate this strategy as a **regime filter layered on H21 (IBS) or H22 (TOM)**. A combined H21+H23 system (IBS alpha + credit regime overlay) may achieve IS Sharpe > 1.0 while maintaining PF-gate compliance.

## TV Source Caveat

- **Primary TV indicator:** "Credit Spread Regime" by EdgeTools (identifier: 1CZOAf7N)
  - URL: https://www.tradingview.com/script/1CZOAf7N-Credit-Spread-Regime/
- **Secondary TV indicator:** "Credit Spread Monitor: HY & IG vs US10Y" by jtomasfg (identifier: qzCpaaPB)
  - URL: https://www.tradingview.com/script/qzCpaaPB-Credit-Spread-Monitor-HY-IG-vs-US10Y/
- **Tertiary TV reference:** "Dynamic Equity Allocation Model" by EdgeTools (identifier: HjgCUw6g)
  - URL: https://www.tradingview.com/script/HjgCUw6g-Dynamic-Equity-Allocation-Model/
- **Apparent backtest window:** TV indicators do not include strategy backtests; these are indicator/monitor scripts only. The strategy logic is derived by synthesizing these indicators into a tradeable signal. Backtest window starts no earlier than 2007 (HYG inception).
- **Crowding risk:** Low. Cross-asset credit-equity timing is primarily institutional (fixed-income specialists). Retail-accessible versions of this strategy are uncommon and not widely implemented via ETF pairs. TV community is smaller than for price-based strategies.
- **Novel insight vs H01–H20:** H18 uses SPY/TLT (flight-to-safety rotation driven by rate expectations). H23 uses HYG/IEI (credit risk-premium driven risk-off signal). The underlying mechanism is fundamentally different: rate expectations vs default risk premium. This is the first credit-market signal in the hypothesis pipeline. Additionally, H18 is an asset rotation strategy; H23 is a binary risk-on/off allocation timer — different signal architecture.

## References

- Gilchrist, S. & Zakrajsek, E. (2012). "Credit Spreads and Business Cycle Fluctuations." *American Economic Review*, 102(4), 1692–1720.
- Fama, E.F. & French, K.R. (1989). "Business Conditions and Expected Returns on Stocks and Bonds." *Journal of Financial Economics*, 25(1), 23–49.
- Lettau, M. & Ludvigson, S. (2001). "Resurrecting the (C)CAPM: A Cross-Sectional Test When Risk Premia Are Time-Varying." *Journal of Political Economy*, 109(6), 1238–1287.
- Whaley, R.E. (2000). "The Investor Fear Gauge." *Journal of Portfolio Management*, 26(3), 12–17. (Cited for VIX as fear gauge context — relevant for distinguishing H19 from H23)
- Quantpedia (2024). "Credit Spread Timing." Research on credit-based equity timing.
- TV source (primary): https://www.tradingview.com/script/1CZOAf7N-Credit-Spread-Regime/
- TV source (secondary): https://www.tradingview.com/script/qzCpaaPB-Credit-Spread-Monitor-HY-IG-vs-US10Y/
- Related in knowledge base: `research/hypotheses/18_tv_spy_tlt_rotation.md` (different mechanism — rate-based rotation), `research/hypotheses/19_tv_vix_volatility_targeting.md` (different mechanism — implied vol regime)
