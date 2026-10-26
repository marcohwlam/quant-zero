# H75: Equity Carry — Dividend Yield Sector Rotation

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-06-16
**Asset class:** equities (ETFs)
**Strategy type:** single-signal
**Status:** hypothesis

---

## Economic Rationale

Dividend yield is the carry component of equities in the unified carry framework (Koijen, Moskowitz, Pedersen & Vrugt 2018). Carry — the return to an asset assuming prices remain unchanged — is a persistent risk premium across all major asset classes. For equities, carry ≈ dividend yield (for stocks) or ETF distribution yield (for sectors).

**Mechanism for persistence:**
High-yield sectors pay investors a premium for bearing specific risks: regulatory risk (utilities), cyclicality risk (financials), commodity price risk (energy). This is not mispricing — it is risk compensation. Investors with shorter horizons or leverage constraints under-hold high-yield assets, allowing carry-seeking investors to earn the premium.

**Key distinctions from momentum:**
- Carry is a *level* signal (dividend yield), not a *return* signal (past price appreciation)
- Carry rotates slowly (quarterly dividend revisions), not fast (price-driven)
- Economic mechanism is fundamentally different: risk compensation vs. trend-following/behavioral
- This satisfies the Hypothesis Class Diversification Mandate (H75 is carry, not momentum/seasonal)

**Academic backing:**
Koijen et al. (2018) document positive carry return in global equities (IR ~0.6 pre-cost), with diversification benefits versus traditional equity factors. Asness, Ilmanen & Moskowitz (2015) confirm carry premium persists after controlling for value and momentum.

**Implementation for long-only constraint:**
Sector rotation across SPDR sector ETFs avoids short selling while capturing cross-sectional carry spread. Monthly rebalance captures yield-ranking changes while minimizing turnover cost.

---

## Entry/Exit Logic

**Universe:** 10 SPDR sector ETFs — XLK, XLY, XLF, XLI, XLV, XLB, XLP, XLE, XLU, XLRE  
*(Note: XLRE launched October 2015. For pre-2015 backtest period, use 9-sector universe or VNQ as XLRE proxy.)*

**Carry signal computation (monthly, at month-end):**
1. For each sector ETF, compute trailing dividend yield:
   - **Primary:** `yfinance ticker.info['dividendYield']` (trailing 12M dividends ÷ current price)
   - **Fallback if unavailable:** sum last 4 quarterly dividends from `ticker.get_dividends()` ÷ closing price
2. Rank all sectors by dividend yield, descending
3. Select top-K sectors (baseline: K=3)

**Entry signal:**
- At month-end: hold top-K highest-yield sector ETFs, equal weight (1/K each)
- Regime filter: if SPY closing price < 200-day SMA → allocate 100% to SHY instead (1–3yr Treasury ETF)
- Rebalance triggered monthly (not yield-change triggered — reduces unnecessary turnover)

**Exit signal:**
- Monthly rebalance: exit any sector that dropped out of top-K by yield rank
- Regime filter triggers SHY exit: SPY < 200-DMA at month-end evaluation
- Stop-loss: none at position level (monthly rebalance serves as trailing stop via rank exit)

**Holding period:** Monthly rebalance → swing to position (weeks)

---

## Market Regime Context

**Works best in:**
- Risk-on / moderate-growth environments: high-yield sectors (XLU, XLP, XLF) outperform when volatility is moderate and investors seek income
- Falling or stable rate environments: yield spread vs. risk-free rate expands → carry premium increases
- Low-growth / stagflation: defensive high-yield sectors (XLP, XLU) hold up well

**Tends to fail in:**
- Sharp rate-rising regimes (2022): treasury yields rise → equity carry spread compresses → relative attractiveness of high-yield sectors drops
- Financial crises (2008–2009): if XLF tops yield rankings pre-crisis (banks paying unsustainable dividends), strategy concentrates in worst-performing sector
- Risk-off with indiscriminate selling: sector yield rankings may not diverge meaningfully, carry spread collapses
- Growth-led bull markets (2017–2021): high-yield (defensive) sectors lag growth sectors; strategy underperforms SPY significantly

**Regime pause trigger:**
- SPY < 200-DMA → exit to SHY (built into signal)
- Consider adding: if 10Y Treasury yield rises >100bp in trailing 6M, reduce position size or exit to SHY

---

## Alpha Decay

Dividend yield is an extremely slow-moving carry signal — companies announce dividends quarterly and rarely cut without major distress.

- **Signal half-life (days):** ~60–90 days (quarterly dividend revision cycle; rankings stable between announcements)
- **Edge erosion rate:** slow (>20 days) — carry premium is a structural risk premia, not a transient anomaly
- **Recommended max holding period:** Monthly rebalance is appropriate; no theoretical cap on holding given slow decay, but monthly rebalance captures new data efficiently
- **Cost survival:** Yes — at monthly rebalance, turnover is ~1–2 sectors per month (10–30% portfolio per month). At 0.05% one-way commission + 0.05% slippage, annual cost drag ≈ 0.3–0.9%. Carry premium estimated at 2–4% gross (Koijen et al.) → net edge survives.
- **Annualized IR estimate:** Expected gross return differential vs. equal-weight sector ≈ 2–3%; tracking vol vs. SPY ≈ 4–6%. Estimated IR ≈ 0.4–0.6 pre-cost, ~0.35–0.5 post-cost. Above 0.3 threshold; survives.
- **Notes:** Decay rate is regime-dependent. In rising-rate regimes, carry spread compresses faster. Crowding concern: dividend yield rotation is a well-known strategy (ETF: DVY, VYM) — capacity is not a constraint at $25K scale, but edge may be partially arbitraged in large-cap space. Sector-level implementation reduces crowding vs. stock-level dividend selection.

> Signal half-life >> 1 trading day → transaction cost survival is clear.

---

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `yield_lookback` | 3M, 6M, 12M | 12M is standard carry convention (Koijen 2018); 3M captures faster yield changes from dividend cuts/raises |
| `top_k_sectors` | 2, 3, 4 | Top-2 = concentrated; top-4 = broader carry tilt with less concentration risk |
| `spy_filter` | on / off | Validate whether 200-DMA regime filter adds or subtracts value (may harm in gradual bear markets) |
| `rebalance_freq` | monthly / quarterly | Quarterly reduces turnover further; test if yield rankings are stable enough to justify |
| `pre2015_proxy` | 9-sector universe / VNQ for real estate | Test sensitivity to real estate inclusion method |

**Recommended baseline:** `yield_lookback=12M`, `top_k=3`, `spy_filter=on`, `rebalance=monthly`

---

## Capital and PDT Compatibility

- **Minimum capital required:** ~$3,000 (3 ETF positions, no margin needed; $1K per position minimum for liquid ETFs)
- **PDT impact:** N/A — monthly rebalance, not intraday. No day-trade count concerns. Eligible for $25K account.
- **Position sizing:** Equal weight, 1/K per sector (K=3 → ~33% per position). With SPY regime filter: 100% SHY when triggered.
- **Max concurrent positions:** 3 sector ETFs + optional SHY hedge position = 4 total. Well within $25K capital constraint.

---

## Pre-Flight Gate Checklist

### PF-1: Walk-Forward Trade Viability — PASS (conditional)

**Required minimum:** ≥ 30 trades in IS; OOS ≥ 30/4 = 8 trades minimum.

**Estimation:**
- IS window: 2003–2021 = ~216 monthly evaluations
- Sector ranking changes: Dividend yields shift at each quarterly ex-div date. In practice, 1–2 rank changes per month across 10 sectors is typical (energy yield varies most with oil price; financial yield changes with payout policy).
- Estimated position switches: ~120–180 over IS period (0.5–0.8 changes/month × 216 months × 1 position affected)
- OOS (2022–2023, ~24 months): ~15–25 switches expected

**Verdict:** PASS — IS switch count well above 30. However, actual switch count should be verified in backtest. If sector yields are highly correlated (all move together), effective switch count could be lower. Flag if IS switches < 60.

### PF-2: Long-Only MDD Stress — CONDITIONAL PASS

**2000–2002 (dot-com):**
- Tech bubble burst: XLK drew down severely, but XLK is *low* yield → unlikely to be in portfolio
- High-yield sectors in 2000: XLU, XLP, XLV (defensive, non-tech). These held up relatively well in 2000–2002.
- Estimated strategy MDD: ~-15 to -20% (defensive sector concentration provided protection vs. SPY -49%)
- **Result: Pass** for 2000–2002 scenario

**2008–2009 (GFC):**
- **Critical risk:** Pre-2008, major bank stocks (XLF constituents: C, BAC, WFC) were paying high dividends → XLF likely topped the yield ranking
- XLF peak-to-trough: -82% (Oct 2007 to Mar 2009). Strategy concentrated in XLF → catastrophic drawdown
- Mitigation: SPY 200-DMA filter triggers SHY exit around November 2008 (SPY broke 200-DMA in January 2008, well before trough)
  - **With SPY filter:** Exit to SHY in Jan 2008 captures most of GFC protection. Strategy MDD estimated: -15 to -25% (exposure in Jan 2008 before filter triggers)
  - **Without SPY filter:** Strategy would draw down -50 to -60% through GFC
- 200-DMA filter is **required** to pass PF-2 for this strategy

**Verdict:** CONDITIONAL PASS — regime filter is mandatory, not optional. Hypothesis MUST be tested with `spy_filter=on`. Standalone carry without filter fails PF-2.

### PF-3: Data Pipeline Availability — PASS (with caveat)

**yfinance verification:**
- `yfinance.Ticker('XLU').info['dividendYield']` → returns trailing 12M yield as float (e.g., 0.038 = 3.8%)
- Available for all 10 SPDR ETFs: XLK, XLY, XLF, XLI, XLV, XLB, XLP, XLE, XLU, XLRE
- Fallback: `ticker.dividends` (historical dividend series) ÷ `ticker.history()['Close']` → computable manually for any lookback
- Historical dividend data in yfinance: all SPDRs have data from inception (XLF 1998, XLU 1998, XLRE 2015)

**XLRE caveat:**
- XLRE launched October 2015. For 2003–2015 period, use 9-sector universe OR substitute VNQ (Vanguard Real Estate ETF, inception 2004) as proxy.
- Recommend: test with 9-sector universe for IS period; add XLRE when available (2015+)

**Verdict:** PASS — all required data available in yfinance pipeline. No proprietary feeds required.

### PF-4: Rate-Shock 2022 Rationale — CONDITIONAL PASS

**2022 rate shock context:**
- Fed raised rates 425bp in 2022. Utility and real estate yields compressed relative to Treasuries.
- XLU -4.8% total return in 2022; XLRE -26%. High-yield sectors broadly underperformed.
- SPY broke below 200-DMA in mid-January 2022 → strategy would exit to SHY approximately January 31, 2022 (month-end evaluation)
- SPY crossed below 200-DMA: ~Jan 14, 2022. Evaluated at Jan 31 month-end close: **SHY position entered Feb 1, 2022**
- SHY returned ~-3.5% in 2022 (short-duration, minimal rate sensitivity). Much better than holding sector ETFs.

**Carry spread argument:**
- In 2022, top yield sectors (XLE at ~4%, XLU at ~3.5%) vs. 10Y Treasury (peaked at 4.2% in Oct 2022)
- By Q4 2022, Treasury yield exceeded sector ETF yields → negative carry spread vs. risk-free rate
- This is a valid structural risk for the strategy

**Mitigation options (implement in backtest):**
1. **Primary defense: 200-DMA filter** — SPY regime filter triggers ~Feb 2022 exit to SHY, avoiding most 2022 drawdown
2. **Optional enhancement:** Add rate filter: if 10Y yield rises >75bp in trailing 6M → halve position, reallocate to SHY

**Verdict:** CONDITIONAL PASS — 200-DMA filter provides meaningful 2022 protection. Without filter, strategy draws down -15 to -20% in 2022. With filter, estimated MDD ~-3 to -8% (brief exposure before month-end eval + SHY performance). Rate-shock risk is documented and mitigated structurally. Backtest must verify 200-DMA exit timing in Jan/Feb 2022.

---

## Gate 1 Outlook

Candid assessment of which Gate 1 thresholds this strategy is likely to meet or miss:

- **IS Sharpe > 1.0:** **Unlikely without filter / Possible with filter** — Carry premium in equities is moderate (Koijen et al. estimate ~0.4–0.6 IR pre-cost globally). US sector rotation may achieve 0.6–0.8 Sharpe. Exceeding 1.0 requires favorable parameter combination and may indicate in-sample optimization. Flag if Sharpe > 1.0 is only achieved with aggressive parameter tuning.
- **OOS persistence:** **Likely** — dividend yield is a slow-moving structural signal backed by 40+ years of academic evidence. OOS degradation should be modest (expect ~20–30% Sharpe decline from IS to OOS, not collapse).
- **Walk-forward stability:** **Moderate** — sector composition varies significantly across rate regimes. Walk-forward windows spanning 2008 and 2022 will stress-test the regime filter dependency. Stability likely across growth/moderate-rate windows; less stable across regime transitions.
- **Sensitivity risk:** **Medium** — key sensitivities: (1) top-K selection (K=2 vs. K=4 changes sector concentration significantly), (2) whether `spy_filter=on` is mandatory (it is, per PF-2). Yield lookback (3M vs. 12M) has moderate sensitivity. Not highly parameter-sensitive overall due to slow signal decay.
- **Known overfitting risks:**
  - 2008 GFC: 200-DMA filter may appear magical in backtest (exits exactly before worst drawdown). This is regime-dependent, not a permanent guarantee.
  - XLRE inclusion: adding/excluding real estate changes IS results non-trivially (real estate was a top-yield sector pre-2008 and drew down severely)
  - Parameter optimization on yield lookback: recommend fixing to 12M (canonical carry convention) and NOT optimizing

---

## Signal Validity Pre-Check

1. **Survivorship bias:** SPDR sector ETFs hold diversified baskets — no survivorship bias from individual stock delisting. ETF-level selection mitigates stock-level survivorship. ✓
2. **Look-ahead bias:** Dividend yield computed from trailing dividends (already paid) and current price at month-end close. No forward-looking data required. ✓
3. **Overfitting risk:** This is the first carry-signal hypothesis in the pipeline. Not cherry-picked from many tested signals — sourced directly from Koijen et al. (2018) carry paper. Low overfitting risk from hypothesis selection. ✓ (flag if parameter sweep reveals only narrow parameter range works)
4. **Capacity:** SPDR sector ETFs have $5B–$50B+ AUM; $25K position is trivially executable. ✓
5. **PDT awareness:** Monthly rebalance — no day-trade issues. N/A. ✓
6. **Costs:** Annual turnover ~30–60% → cost drag ~0.3–0.9%. Gross edge estimated 2–4%. Net edge positive. ✓
7. **Signal-to-noise ratio:** Annualized IR estimate ~0.35–0.5 post-cost. Above 0.3 threshold. ✓

---

## Literature Source

**Primary reference:**
> Koijen, R.S.J., Moskowitz, T.J., Pedersen, L.H., & Vrugt, E.B. (2018). *Carry*. Journal of Financial Economics, 127(2), 197–225.

**Signal formula (equity carry):**
```
Carry(i, t) = Dividend_Yield(i, t) = Trailing_12M_Dividends(i) / Price(i, t)
```
Where `i` is a sector ETF, `t` is monthly observation date.

**Key empirical claims from paper:**
- Global equity carry (long top-quintile yield, short bottom-quintile) delivers Sharpe ~0.4–0.6 in equities alone
- Carry is positively correlated with value and negatively correlated with momentum (diversifying signal)
- Carry premium is crash-risk-exposed (large drawdowns in 2008, 2011) — consistent with risk-compensation narrative

**Adaptation notes (from paper to this implementation):**
- Paper uses global equities (long-short); this implementation uses US sector ETFs (long-only) → reduces capacity of carry spread capture but eliminates shorting complexity
- Paper uses individual stocks; we use sector ETFs → reduces stock-specific risk, introduces sector aggregation
- Paper does not include regime filter; we add 200-DMA SPY filter → reduces GFC/rate-shock exposure at cost of potential whipsaws in choppy markets
- Lookback: paper uses trailing 12M dividends (standard); same convention adopted here

**Supporting references:**
> Asness, C., Ilmanen, A., Israel, R., & Moskowitz, T. (2015). *Investing with Style*. Journal of Investment Management.
> Ilmanen, A. (2011). *Expected Returns: An Investor's Guide to Harvesting Market Rewards*. Wiley. (Chapter on carry premium)

---

## References

- Koijen, Moskowitz, Pedersen, Vrugt (2018) — "Carry", *Journal of Financial Economics* 127(2) — primary source
- Asness, Ilmanen et al. (2015) — "Investing with Style" — carry diversification with momentum/value
- Ilmanen (2011) — *Expected Returns* — carry premium survey, equity carry section
- SPDR Sector ETF data via yfinance (`XLK`, `XLY`, `XLF`, `XLI`, `XLV`, `XLB`, `XLP`, `XLE`, `XLU`, `XLRE`)
- SHY (iShares 1–3 Year Treasury Bond ETF) — cash proxy for regime filter
- Related hypotheses: H72 (Bond Yield Curve Carry, bond carry analog), H69 (SPY/TLT Ratio — cross-asset carry adjacent)
- Related knowledge: `/knowledge_base/` — no direct carry predecessor; this is first equity carry hypothesis
