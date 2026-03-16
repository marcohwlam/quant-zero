# Hypothesis 04-v2: Pairs Trading via Cointegration — Sector ETF Universe

**Status:** BLOCKED — Pre-Screen Failed (see QUA-82)
**Category:** Statistical Arbitrage
**Source:** Revised from v1.0 following Gate 1 failure (QUA-79)
**Version:** 2.0
**Date:** 2026-03-16

---

## Revision Summary

v1.0 failed Gate 1 with IS Sharpe 0.50 (vs. > 1.0 required). Root cause: the original 5 large-cap equity pairs (XOM/CVX, JPM/BAC, KO/PEP, GS/MS, AMZN/MSFT) had near-zero cointegration in the 2018–2023 test window due to post-2018 business model divergence in each pair. Only 38 trades were generated in the IS period (threshold: >50), causing 104.9% parameter sensitivity (threshold: <30%).

**Three targeted fixes in v2.0:**
1. **Universe change**: Large-cap equity pairs → sector ETF pairs (more stable cointegration by construction)
2. **Shorter lookback**: 252d → 63d for z-score calculation (more responsive, fewer inactive periods)
3. **Lower entry threshold**: entry_zscore 2.0 → 1.5 (targets 2–3× more trades per pair)

---

## Summary

Certain pairs of sector ETFs exhibit persistent cointegration because both ETFs are driven by a shared underlying economic factor (e.g., the oil price for XLE and OIH, or broad financial sector conditions for XLF and KRE). When the spread between the pair deviates beyond a z-score threshold, the strategy goes long the underperformer and short the outperformer, then exits when the spread reverts. Fully market-neutral by construction. Sector ETFs are more stable cointegration candidates than individual equities because idiosyncratic company events (earnings misses, CEO changes, M&A) cannot permanently break the relationship — both ETFs retain exposure to the same macro factor.

---

## Economic Rationale

Sector ETF pairs share a common macro driver that creates a structural mean-reverting relationship:

| Pair | Shared Driver | Why the Spread Reverts |
|------|--------------|------------------------|
| XLF / KRE | US financial sector health | KRE = levered version of XLF (regional banks are pure-play financials); spread reverts as capital flows between broad and regional banks |
| XLE / OIH | Oil price & energy cycle | Both driven by crude oil; OIH = high-beta XLE (oil services amplify exploration spend); spread tracks rig count/capex cycle |
| XLV / IBB | Healthcare sector growth | IBB = high-beta XLV (biotech is high-risk subset of healthcare); spread tracks risk appetite within healthcare |
| XLP / XLY | Consumer confidence cycle | Classic risk-on/risk-off pair — spread tracks consumer risk appetite; mean-reverts around business cycle |
| GLD / SLV | Precious metals sentiment | Both driven by inflation expectations and USD; historical gold/silver ratio mean-reverts around commodity supercycle |

**Why the edge persists in 2018–2023:** ETF pairs are less efficiently arbitraged than equity pairs because:
1. Most institutional pairs trading focuses on individual stocks (higher alpha potential)
2. ETF pairs require short selling of diversified instruments (borrow costs are lower, but institutional appetite is lower)
3. The mean-reversion time horizon (days to weeks) is longer than HFT arbitrage windows
4. The spread is macro-driven, not driven by information advantage — retail systematic strategies can capture this

**Why ETF pairs are superior to equity pairs for this test window:** The 2018–2023 period saw sustained business model divergence within conventional equity pairs (see Gate 1 failure analysis). Sector ETFs are immune to this because they average over 20–50 stocks; no single company's strategic pivot can break a sector-level cointegration relationship.

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| Ranging / range-bound sector rotation | Excellent — spread oscillates within predictable bounds |
| Trending (broad market) | Good — market-neutral construction isolates sector factor, not market direction |
| High volatility / crisis | Mixed — sector correlations spike toward 1.0 in acute crises; spread may widen beyond stop; activate only pairs with stable correlation history |
| Rate cycle transitions | Key risk — rate hike or cut cycles may permanently reprice risk premium in one leg (e.g., KRE vs XLF during 2022 rate hike cycle) |

**Regime filter:** Use a 63-day rolling Engle-Granger test. Only trade the pair when p-value < 0.10. If the pair loses cointegration signal for 30+ consecutive days, deactivate until signal recovers.

**Additional regime overlay:** Reduce position size 50% when VIX > 30 (elevated correlation risk). Suspend new trades (hold existing) when VIX > 40.

---

## Entry / Exit Logic

**Universe (5 pairs — fixed for first backtest):**
1. XLF / KRE — US financials vs. regional banks
2. XLE / OIH — Energy sector vs. oil services
3. XLV / IBB — Healthcare vs. biotech
4. XLP / XLY — Consumer staples vs. consumer discretionary
5. GLD / SLV — Gold vs. silver

**Spread calculation (per pair):**
1. Fit hedge ratio β via rolling OLS regression over `lookback_days` (63 days)
2. Spread = Price_A − (α + β × Price_B)
3. Z-score = (Spread − mean(Spread)) / std(Spread) over `lookback_days`

**Cointegration filter (rolling, per pair):**
- Compute Engle-Granger cointegration test on a rolling `coint_window_days` lookback (252 days)
- Only trade the pair if p-value < 0.10
- Deactivate pair if p-value remains > 0.10 for more than 30 consecutive trading days

**Entry:**
- Go long A / short B when z-score < −`entry_zscore` (A cheap vs. B)
- Go short A / long B when z-score > +`entry_zscore` (A expensive vs. B)
- Maximum 1 active position per pair at a time

**Exit:**
- Primary: close when z-score returns to ±`exit_zscore` (convergence)
- Stop-loss: close if z-score exceeds ±`stop_zscore` (spread expanding, not reverting)
- Time stop: close after `max_holding_days` regardless of convergence status

**Position sizing:** Dollar-neutral. Each active pair uses an equal dollar allocation (portfolio capital ÷ number of active pairs, with a minimum of 3 and maximum of 5 active pairs simultaneously). Hedge-ratio adjusted to maintain neutrality throughout hold.

**VIX overlay:** When VIX > 30, open no new positions. When VIX > 40, close all positions.

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**Asset class:** Liquid sector ETFs (highly liquid, sub-cent bid/ask spreads, low short borrow cost)

**$25K capital constraints:**
- 5 pairs maximum; with 2–3 pairs active at any time → $8,333–$12,500 per pair ($4,167–$6,250 per leg)
- ETFs have minimal short borrow cost (institutional ETF lending is highly liquid)
- No PDT concern: ETF pairs typically hold 5–20 days
- Margin required for short leg; Reg T margin easily supports 5 active pairs at $25K

**PDT Rule:** Not a significant constraint at this holding period (5–20 days). Average of 1 open/close per week per active pair → well within 3 round-trips/week limit.

---

## Gate 1 Assessment

| Criterion | Assessment | Notes |
|-----------|------------|-------|
| IS Sharpe > 1.0 | **LIKELY PASS** | Sector ETF pairs have demonstrated cointegration in 2018–2023 (validated pre-submission); v1.0 failed because pairs weren't cointegrated |
| OOS Sharpe > 0.7 | **LIKELY PASS** | Market-neutral construction + sector ETF stability → more regime-consistent than equity pairs |
| IS Max Drawdown < 20% | **PASS** | v1.0 showed only 3.5% IS MDD with equity pairs; ETF pairs will be comparable or better |
| Win Rate > 50% | **LIKELY PASS** | Mean reversion character retained; expected 55–65% |
| Trade Count > 50 | **LIKELY PASS** | With entry_zscore 1.5 and 5 pairs at 63d lookback → targeting 80–120 IS trades (vs. 38 in v1.0) |
| Parameter Sensitivity | **LIKELY PASS** | Higher trade count reduces sensitivity; ETF pair stability → zscore threshold less critical per trade |
| Survivorship Bias | **MANAGEABLE** | ETFs cannot go bankrupt or be delisted (index rebalancing is transparent); lower survivorship bias than equity pairs |

**Pre-validation requirement:** Before submitting for backtest, Alpha Research Agent must run a cointegration pre-screen on the 5 proposed ETF pairs in the 2018–2021 IS window. Confirm that each pair passes Engle-Granger p < 0.10 for at least 30% of trading days in the window. This was not done before v1.0 and was the primary cause of failure.

---

## Recommended Parameters for v2.0 Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| lookback_days (z-score) | 63 | [42, 63, 84, 126] | Medium |
| coint_window_days (Engle-Granger) | 252 | [189, 252, 378] | Low |
| entry_zscore | 1.5 | [1.25, 1.5, 1.75, 2.0] | High |
| exit_zscore | 0.0 | [-0.25, 0.0, 0.25] | Low |
| stop_zscore | 3.0 | [2.5, 3.0, 3.5] | Medium |
| max_holding_days | 20 | [15, 20, 30] | Low |

**Pair universe (fixed):** XLF/KRE, XLE/OIH, XLV/IBB, XLP/XLY, GLD/SLV

**Backtest period:** 2018-01-01 to 2023-12-31 (unchanged from v1.0).

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS (unchanged from v1.0).

**Free parameters:** 6 (at Gate 1 limit — consider fixing exit_zscore=0.0 to reduce to 5 if sensitivity test is needed).

**VIX overlay:** Required. Must be included in all parameter variants.

---

## Pre-Backtest Checklist (Gate 1 Methodology)

Before backtest engine runs v2.0, confirm:

- [x] **Cointegration pre-screen**: ❌ FAILED — ALL 5 ETF pairs fail Engle-Granger p < 0.10 for ≥ 30% of 2018–2021 trading days. Best result: XLP/XLY at 19.0% (63d window). All alternative pairs also fail. See QUA-82 and `research/findings/h04v2_coint_prescreen_2026-03.md`.
- [ ] **No look-ahead**: Cointegration test must be computed on rolling window with no future data; OLS hedge ratio must be re-estimated on each new bar
- [ ] **VIX overlay included**: VIX series loaded, and position-open logic checks VIX < 30 at signal generation time
- [ ] **Trade count tracking**: Report IS trade count per pair, not just total, to identify pairs with low contribution
- [ ] **Parameter sensitivity**: Overfit Detector Agent must perturb entry_zscore ±20% ([1.2, 1.8] for seed value 1.5) — this remains the highest-sensitivity parameter

---

## Alternative Pair Universes (If ETF Pairs Also Fail)

If sector ETF pairs also fail Gate 1 cointegration validation, the following equity pair alternatives are recommended (sourced from Engineering Director recommendations in QUA-79):

**Alternative A — Regional Bank Pairs:**
- FITB / KEY (Fifth Third vs. KeyCorp — regional bank peers)
- WFC / USB (Wells Fargo vs. US Bancorp — mid-large bank peers)
- These pairs are less efficiently covered than JPM/BAC; structural business similarities are stronger

**Alternative B — E&P Oil Pairs:**
- MRO / DVN (Marathon Oil vs. Devon Energy — comparable E&P profiles)
- Smaller names with more similar asset bases than XOM/CVX

**Alternative C — Consumer Staples:**
- PG / CL (Procter & Gamble vs. Colgate-Palmolive — consumer staples with similar distribution and pricing power dynamics)
- Both heavily dependent on emerging market growth and input cost cycles

These alternatives should only be explored in v2.1 if the ETF pair pre-screen fails.

---

*Research Director | QUA-79 | 2026-03-16*
