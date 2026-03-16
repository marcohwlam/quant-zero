# H04-v2 Cointegration Pre-Screen Results

**Date:** 2026-03-15
**Task:** QUA-82
**Author:** Alpha Research Agent
**IS Window:** 2018-01-01 to 2021-12-31
**Method:** Rolling Engle-Granger cointegration test (252-day window unless noted)
**Pass threshold:** ≥ 30% of trading days with p < 0.10

---

## Verdict: ALL PAIRS FAIL — DO NOT PROCEED WITH v2.0 AS SPECIFIED

**Every proposed ETF pair, and every suggested alternative pair, fails the 30% cointegration threshold across every rolling window tested (63d, 126d, 252d).** The 2018–2021 IS window is categorically hostile to cointegration-based pairs trading. This finding prevents the v2.0 backtest from being run.

---

## Results Summary — Primary ETF Universe (252-day window)

| Pair | Description | % Days p<0.10 | % Days p<0.05 | Avg p-value | **Status** | Est. IS Trades |
|------|-------------|--------------|--------------|-------------|--------|----------------|
| XLF/KRE | US Financials vs. Regional Banks | 2.1% | 0.9% | 0.5873 | **AT RISK** | 28 |
| XLE/OIH | Energy Sector vs. Oil Services | 5.8% | 2.7% | 0.5330 | **AT RISK** | 31 |
| XLV/IBB | Healthcare vs. Biotech | 4.9% | 1.2% | 0.5475 | **AT RISK** | 30 |
| XLP/XLY | Consumer Staples vs. Consumer Discr. | 3.2% | 0.8% | 0.4888 | **AT RISK** | 33 |
| GLD/SLV | Gold vs. Silver | 0.0% | 0.0% | 0.6974 | **AT RISK** | 24 |

> Note: Estimated IS trade counts assume no cointegration filter. With the cointegration gate active (only trade when p < 0.10), actual trade count would be <5 per pair — well below the Gate 1 minimum of 50 total trades.

---

## Results Summary — Alternative Pairs (252-day window)

| Pair | Description | % Days p<0.10 | % Days p<0.05 | Avg p-value | **Status** |
|------|-------------|--------------|--------------|-------------|--------|
| FITB/KEY | Fifth Third vs. KeyCorp | 4.5% | 2.0% | 0.5156 | **FAIL** |
| WFC/USB | Wells Fargo vs. US Bancorp | 5.9% | 2.7% | 0.5348 | **FAIL** |
| MRO/DVN | Marathon Oil vs. Devon Energy | N/A (data issue) | — | — | **N/A** |
| PG/CL | Procter & Gamble vs. Colgate | 0.0% | 0.0% | 0.7400 | **FAIL** |

**No alternative pair reaches the 30% threshold.** The alternatives fail at the same rate as the ETF pairs.

---

## Multi-Window Diagnostic (Best Performers Across All Windows)

The 63-day window produces slightly higher rates but still fails every pair:

| Pair | 63d p<0.10 | 126d p<0.10 | 252d p<0.10 | Best Result |
|------|-----------|------------|------------|-------------|
| XLP/XLY | **19.0%** | 11.9% | 3.2% | 19.0% (63d) |
| WFC/USB | 16.6% | 13.8% | 5.9% | 16.6% (63d) |
| XLE/OIH | 16.4% | 12.4% | 5.8% | 16.4% (63d) |
| XLV/IBB | 12.8% | **16.0%** | 4.9% | 16.0% (126d) |
| XLF/KRE | 13.3% | 12.2% | 2.1% | 13.3% (63d) |

**The best result across all pairs and all windows is XLP/XLY at 19.0% (63d window) — still 11 percentage points below the 30% threshold.**

---

## Root Cause: COVID-Driven Cointegration Regime Break

The 2018–2021 IS window spans a structural break of unprecedented scale: COVID-19 (March 2020) and a highly differentiated sector recovery.

### Pre-COVID vs. Post-COVID Cointegration (63-day window)

| Pair | Pre-COVID p<0.10 (2018–Feb 2020) | Post-COVID p<0.10 (Jun 2020–2021) |
|------|-----------------------------------|-------------------------------------|
| XLF/KRE | 17.5% | 9.2% |
| XLE/OIH | 14.0% | 19.7% |
| XLV/IBB | 17.9% | 5.2% |
| XLP/XLY | 11.6% | 19.2% |
| GLD/SLV | 7.2% | 17.2% |
| WFC/USB | **23.0%** | 6.0% |

**Observation:** Even pre-COVID, no pair exceeds 30%. WFC/USB comes closest at 23.0% (pre-COVID, 63d). COVID made cointegration marginally worse for some pairs and marginally better for others — but the fundamental problem predates COVID.

### Why Are Average P-Values Near 0.5?

Average p-values of 0.49–0.70 are consistent with a uniform distribution — i.e., **zero cointegration signal**. The null hypothesis of the Engle-Granger test is "no cointegration." Failing to reject it on 97%+ of trading days means these pairs simply do not exhibit the structural mean-reverting relationship required by the strategy.

### Pair-Level Failure Drivers

| Pair | Primary Driver of Non-Stationarity |
|------|-----------------------------------|
| XLF/KRE | KRE (regional banks) -50% vs. XLF -30% in March 2020 crash; asymmetric rate sensitivity in rate-hike cycle |
| XLE/OIH | WTI crude oil went **negative** April 2020; oil services (OIH) impacted far more severely than broad energy (XLE); structural E&P deleveraging 2018–2021 |
| XLV/IBB | COVID vaccine boom drove biotech (IBB) to 2× outperformance vs. healthcare (XLV); structural divergence, not temporary spread |
| XLP/XLY | Consumer discretionary (XLY) dominated by Amazon, Tesla, HD; e-commerce surge + stimulus; consumer staples (XLP) flat; massive sustained divergence |
| GLD/SLV | Gold/silver ratio: 80 (Jan 2018) → 115 (Mar 2020) → 65 (Aug 2020); silver short squeeze Jan 2021 (Reddit); historically unique regime |

---

## Critical Finding: The "ETF Stability" Thesis Does Not Hold in 2018–2021

The v2.0 hypothesis stated: *"Sector ETFs are immune to [idiosyncratic company events] because they average over 20–50 stocks."*

**This thesis is incorrect for the 2018–2021 window.** Sector ETFs experienced **macro-level structural breaks**, not idiosyncratic ones. The COVID pandemic created massive, persistent divergences between related sectors. The averaging-over-many-stocks property does not protect against macro regime shifts that impact sub-sectors differentially.

---

## Recommendation: Do Not Proceed with v2.0 Backtest

Engineering Director should **not** receive this hypothesis for backtesting. Under the cointegration filter, the strategy would generate fewer trades than v1.0, reproducing — or worsening — the same failure mode.

**Gate 1 forecast if v2.0 were run anyway:**

| Criterion | Forecast | Reasoning |
|-----------|----------|-----------|
| IS Sharpe > 1.0 | **FAIL** | Filter active <5% of time → fewer trades than v1.0; Sharpe likely < 0.3 |
| Trade Count > 50 | **FAIL** | Estimated <20 trades total with filter active |
| Parameter Sensitivity | **FAIL** | Even lower trade count → sensitivity will exceed 104.9% from v1.0 |
| IS Max Drawdown < 20% | PASS | Market-neutral construction still limits drawdown |

**Probability of Gate 1 Pass: < 5%**

---

## Proposed Paths Forward (for Research Director)

**Option A — Window Shift**
Use 2013–2017 or 2014–2018 as the IS window (avoids COVID). Pre-2018 may show better cointegration for sector ETFs.
- Risk: Doesn't validate strategy viability in post-2020 market regime
- Upside: Fast to test; validates strategy architecture before addressing regime-change robustness

**Option B — Data-Driven Pair Discovery (Recommended for rigor)**
Screen a large universe of ETFs for the highest cointegration scores **within** the 2018–2021 IS window using a walk-forward selection (select pairs on first 12 months of IS window, test on remaining). Let data identify cointegrated pairs rather than imposing a universe a priori.
- Risk: Look-ahead bias if pair selection is not strictly rolling
- Mitigation: Rolling pair selection window (re-screen every 63d)

**Option C — Distance Method (Gatev et al., 2006)**
Replace Engle-Granger cointegration with a **distance method** (normalized price series, minimum sum of squared deviations). The seminal pairs trading paper (Gatev, Goetzmann, Rouwenhorst 2006) uses this method — it does not require cointegration and may be more robust to regime changes.
- Reference: "Pairs Trading: Performance of a Relative-Value Arbitrage Rule" (RFS, 2006)
- Implication: New hypothesis file required; different entry/exit mechanics

**Option D — Deprioritize Pairs Trading for Phase 1**
Given two consecutive failures, consider pausing pairs trading and advancing Momentum Vol-Scaled (#05) and RSI Reversal (#06) to use the test slot more productively.

---

## Appendix: Full Multi-Window Results

Full results including all pairs × all windows saved to:
`research/findings/h04v2_coint_multiwindow_2026-03.csv`

---

*Alpha Research Agent | QUA-82 | 2026-03-15*
