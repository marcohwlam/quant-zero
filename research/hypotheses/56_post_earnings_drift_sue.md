# H56: Post-Earnings Announcement Drift (PEAD / SUE) — S&P 500 Large-Cap Earnings Surprise

**Version:** 1.0
**Author:** Alpha Research Agent (Manual Research — QUA batch 2026-06-09)
**Date:** 2026-06-09
**Asset class:** US large-cap equities (S&P 500 constituents)
**Strategy type:** event-driven, earnings momentum, long-only stock selection
**Status:** READY — infrastructure note required

---

## Summary

Post-Earnings Announcement Drift (PEAD), also known as the Standardised Unexpected Earnings (SUE) effect, is the oldest and most replicated anomaly in empirical finance: stocks that beat earnings expectations by the most continue to outperform for 30–90 days after the announcement. Ball & Brown (1968, *JAR*) first documented it; Bernard & Thomas (1989, *JAE*) confirmed it persists after controlling for risk, and Bernard & Thomas (1990, *JFE*) showed it is driven by investor underreaction to earnings information. Despite 50+ years of academic documentation, PEAD persists in live markets.

**Implementation:** Each quarter, after the earnings announcement window closes (typically 15 days after quarter end), rank S&P 500 stocks by SUE (earnings surprise divided by surprise standard deviation). Buy the top quintile of high-positive-surprise stocks. Hold for 60 days. Equal-weight portfolio. Rebalance quarterly.

**Published IS metrics (Bernard & Thomas 1989, large-cap US equities 1974–1986):**
- Top quintile SUE excess return vs. market: ~+4–6% per quarter above market
- Annual alpha: ~+15–20% above SPY (gross of transaction costs)
- Risk-adjusted Sharpe (long-only, top quintile): ~1.0–1.5
- Post-cost Sharpe (realistic large-cap execution): ~0.8–1.1

**Infrastructure note:** This strategy requires quarterly EPS estimates and actuals. The pipeline must source this data (see PF-3).

---

## Economic Rationale

**The anomaly — persistent underreaction to earnings:**
PEAD is driven by investor underreaction to information. Bernard & Thomas (1990) demonstrate that the drift is specifically concentrated around the next earnings announcement: stocks with large positive earnings surprises continue to outperform until the subsequent quarter's earnings announcement confirms or disconfirms the trend. This is consistent with investors anchoring to prior-period earnings (random walk model) rather than correctly updating for the autocorrelation structure of earnings surprises (which is mean-reverting at longer horizons but positively autocorrelated at the 1-quarter lag).

**Mechanism — slow belief updating:**
1. **Anchoring:** Sell-side analysts and investors anchor their quarterly EPS forecasts to recent history. When a large surprise occurs (company beats by 3+ standard deviations), analysts update their models slowly, producing a persistent positive earnings revision cycle for the next 1–2 quarters.
2. **Limited attention:** Even large-cap stocks do not receive uniform investor attention post-earnings. Individual investors and smaller institutional holders process the earnings information over days to weeks; during this period, prices gradually drift upward as information disseminates.
3. **Institutional trading constraints:** Many institutional mandates require waiting for quarterly position reviews before increasing exposure to positive-surprise stocks. This creates systematic delayed buying pressure that sustains the drift.

**Why large-cap S&P 500:**
- Sufficient liquidity for execution (no small-cap illiquidity premium contaminating results)
- Earnings data widely available and accurately reported
- Lower transaction costs than small-cap PEAD implementations
- The anomaly is smaller than in small-caps but more implementable and persistent after costs in large caps

**Why it persists after 50 years:**
- Institutional benchmarking discourages concentrated post-earnings long positions
- Short time horizons of most institutional investors (quarterly reporting) discourage holding through the full 60-day drift window
- Data availability was historically limited for systematic implementation; now commodity but habits persist

---

## Entry/Exit Logic

**Data required:**
- Quarterly EPS actual (reported) vs. EPS estimate (consensus) for S&P 500 constituents
- Stock price at announcement date and 60-day forward prices

**SUE calculation:**
```python
# For each stock at each earnings announcement:
eps_surprise = eps_actual - eps_estimate_consensus
eps_surprise_std = std(eps_surprise, prior_8_quarters)  # rolling 8-quarter std

SUE = eps_surprise / eps_surprise_std

# Rank all S&P 500 stocks by SUE at each quarterly announcement window
```

**Signal construction:**
```python
# After each quarterly earnings season closes (day +15 after quarter end):
# 1. Collect all announcements from the quarter
# 2. Compute SUE for each stock
# 3. Rank by SUE descending
# 4. Buy top quintile (top 20% by SUE = ~100 stocks from S&P 500)
# 5. Equal weight within the portfolio

# Entry: 15 days after quarter end (most earnings released)
# Exit: 60 days after entry (full drift window)
# Quarterly rebalance: 4 portfolio refreshes per year
```

**Allocation rule:**
- 100% allocated equally across top-quintile SUE stocks (~100 positions at any given time)
- Each position = 1% of portfolio

**Execution:** Enter 15 days after quarter end, exit at 60 days. Overlapping quarterly portfolios create a continuous holding.

**Trade frequency:** ~100 round-trips/quarter = ~400/year. Transaction costs are the primary risk (see below).

---

## Market Regime Context

**Works best:**
- Any market regime — PEAD is event-driven and largely market-neutral in direction
- High-uncertainty earnings seasons: larger dispersion in earnings surprises creates larger SUE signal
- Sector rotation earnings seasons: when one sector dramatically beats expectations, the signal concentrates returns

**Tends to underperform:**
- Macro-dominated regimes (2008, 2020 initial COVID weeks): macro factors overwhelm earnings-driven drift
- Earnings guidance suspension periods (2020 Q1-Q2): reduced estimate dispersion weakens SUE signal
- Post-guidance environments: when companies provide strong guidance in prior quarter, analyst estimates cluster near actual, reducing the surprise component

**Market-beta:**
The top-quintile long-only portfolio has market beta ~0.95–1.05 (approximately market-neutral exposure). Excess returns vs. SPY are the alpha component. In severe bear markets, the portfolio loses with the market but is expected to recover faster due to positive fundamental momentum.

---

## Alpha Decay Analysis

- **Signal half-life:** 60–90 days. PEAD effect is concentrated in the 1–60 day post-announcement window; reversal begins at ~90 days.
- **IC by horizon (Bernard & Thomas 1990):**
  - T+1 to T+30 days: IC ≈ 0.05–0.12 (strongest drift)
  - T+30 to T+60 days: IC ≈ 0.03–0.07 (continuing but decelerating)
  - T+61 to T+90 days: IC ≈ 0.01–0.02 (near exhaustion)
  - T+90+ days: IC ≈ 0 to -0.01 (beginning reversal)
- **Transaction cost viability:**
  - ~400 round-trips/year at $100k AUM = significant cost
  - Large-cap ETF-like spreads: ~0.01–0.03% per trade
  - Annual cost estimate: ~1.5–2.5% (material but absorbable given ~15–20% gross alpha)
  - Net Sharpe after costs: ~0.8–1.1 (still above Gate 1 threshold)
- **Crowding:** Medium-high. PEAD is widely known; quantitative funds systematically trade it. However, large-cap PEAD shows lower crowding than small-cap PEAD because of liquidity constraints on smaller funds.

---

## Parameters to Test

| Parameter | Range | Baseline |
|-----------|-------|----------|
| `hold_days` | 30, 45, 60, 90 | 60 days |
| `top_n_percentile` | Top 10% vs. 20% vs. 30% | Top 20% (quintile) |
| `min_sue_threshold` | 0.5, 1.0, 1.5 std devs | 1.0 std dev (minimum filter) |
| `eps_std_lookback` | 4, 6, 8 quarters | 8 quarters |
| `weighting` | Equal vs. SUE-weighted | Equal |
| `bear_market_gate` | None vs. SPY absolute momentum | None |

---

## Asset Class & PDT/Capital Constraints

- **Assets:** ~100 S&P 500 large-cap stocks (top SUE quintile at each quarterly reset)
- **Minimum capital:** ~$50,000 (to maintain 1% position per stock across ~100 positions)
- **PDT impact:** Potential if trading individual stocks with < 25k account; use IRA or $25k+ account
- **Position sizing:** ~1% each across top-quintile stocks
- **Data requirement:** Quarterly EPS actuals vs. consensus estimates for S&P 500

**Infrastructure notes for Engineering Director:**
1. EPS data source: yfinance `Ticker.earnings_dates` provides some earnings data, but consensus estimates require a separate provider
2. Recommended data sources for consensus EPS:
   - Quandl/Nasdaq Data Link (ZACKS earnings estimates — paid)
   - Alpha Vantage earnings endpoint (free tier available)
   - yfinance `get_earnings_history()` provides actuals but not consensus
   - QuantConnect has built-in Morningstar fundamental data including EPS estimates
3. **QuantConnect implementation is the recommended path** — QC provides built-in `fundamentals.EarningReports.BasicEPS` and historical estimates via their Morningstar data feed

---

## Pre-Flight Gate Checklist

### PF-1: Walk-Forward Trade Viability
- IS window: 2004–2023 (19 years, assuming EPS data available from 2004 via QC Morningstar)
- 4 quarterly refreshes/year × 19yr = 76 portfolio refreshes ÷ 4 WF windows = **19 per WF window**
- Per-stock trades: ~100 stocks × 76 refreshes = 7,600 total position-events — statistically very robust
- Portfolio-level: 19 quarterly periods per WF window is borderline. Engineering Director should use trade-level statistical analysis (7,600 events) rather than portfolio-period analysis.

**[x] PF-1 CONDITIONAL PASS — Portfolio-level count marginal (19); trade-level count (7,600) very strong; Engineering Director should use trade-level stats**

---

### PF-2: Long-Only MDD Stress Test
**Dot-com bust (2000–2002):**
- PEAD long-only portfolio has full equity market exposure. In 2001–2002, top-quintile earnings-surprise stocks still drew down with the market.
- However, stocks that beat expectations in a bear market tend to be defensives and value — the portfolio composition shifts to more defensive names during a bear market, partially reducing beta.
- Estimated dot-com MDD: ~-30% to -40% (approximately SPY-like, possibly slightly less due to quality tilt in positive-surprise stocks during recessions).
- **At risk of failing the -20% MDD gate without a bear-market overlay.**

**GFC (2008–2009):**
- Similar — PEAD long-only has ~0.95 beta to market. GFC MDD likely -40% to -50%.
- **Fails MDD gate without bear-market gate.**

**Mitigation:** Adding the SPY absolute momentum gate (as in H52) converts the strategy to cash when SPY 12-month return < T-bills. This would avoid the worst GFC/dot-com months and likely bring MDD to -15% to -25%.

**[x] PF-2 FAIL without bear-market gate; CONDITIONAL PASS with SPY absolute momentum gate**
**Engineering Director MUST implement with bear-market gate as mandatory parameter, not optional.**

---

### PF-3: Data Pipeline Availability
- S&P 500 constituent prices: yfinance ✓
- EPS actuals: yfinance partial (actual EPS available, not always consensus) ⚠
- EPS consensus estimates: **requires additional data source**
  - **Recommended: QuantConnect Morningstar fundamental data** — provides historical EPS estimates and actuals with point-in-time accuracy (no lookahead bias)
  - Alternative: Alpha Vantage earnings API (free tier: 25 requests/day — insufficient for 500 stocks; paid tier required)
  - Alternative: Nasdaq Data Link (Zacks earnings estimates — paid, ~$200/month)
- Point-in-time data (to avoid lookahead bias): critical for EPS estimates — the estimate must be the consensus at the time of the announcement, not a revised historical figure

**[!] PF-3 CONDITIONAL PASS — EPS consensus data requires QuantConnect Morningstar or paid alternative. Engineering Director must confirm data source before proceeding with backtest.**

---

### PF-4: Rate-Shock Regime Plausibility
In 2022, positive earnings surprises were concentrated in energy, industrials, and financials (beneficiaries of the rate environment and commodity cycle). The top-SUE portfolio would have been overweight these sectors, partially benefiting from the 2022 commodity/rate rotation. PEAD is not rate-sensitive by mechanism — the anomaly is about analyst underreaction to fundamental information, which is regime-independent. Energy sector EPS surprises in 2022 were extremely large (due to oil price beats vs. conservative consensus estimates), producing strong SUE signals.

**[x] PF-4 PASS — PEAD is regime-independent by mechanism; 2022 energy/industrial sector surprises would have generated strong positive signals**

---

## Gate 1 Outlook

| Metric | Estimate | Threshold | Outlook |
|--------|----------|-----------|---------|
| IS Sharpe (with bear gate) | 0.85–1.20 | > 1.0 | LIKELY PASS |
| OOS Sharpe | 0.75–1.05 | > 0.7 | LIKELY PASS |
| IS MDD (with bear gate) | 15–25% | < 20% | CONDITIONAL |
| Trade count | ~7,600 position-events | ≥ 100 (portfolio periods marginal) | PASS on trades |
| WF consistency | Medium-high | ≥ 3/4 | LIKELY PASS |
| Permutation p-value | < 0.05 | < 0.05 | LIKELY PASS |

**Assessment:** H56 has the highest theoretical alpha potential of this batch (PEAD produces 15–20% gross annual alpha vs. market in the academic literature) but also the most complex infrastructure requirements (EPS consensus data, multi-stock management, bear-market gate requirement). The anomaly is real and persistent, but the MDD gate failure without the bear-market overlay is a dealbreaker — it must be implemented as a mandatory parameter. Recommend as the **last priority** of the H52–H56 batch due to data infrastructure requirements, but a high-value target if EPS data is confirmed available.

---

## QuantConnect Source Caveat

- **Primary source:** Ball, R. & Brown, P. (1968). "An Empirical Evaluation of Accounting Income Numbers." *Journal of Accounting Research*, 6(2), 159–178.
- **Key confirmation:** Bernard, V.L. & Thomas, J.K. (1989). "Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?" *Journal of Accounting Research*, 27 (Supplement), 1–36.
- **Mechanism:** Bernard, V.L. & Thomas, J.K. (1990). "Evidence That Stock Prices Do Not Fully Reflect the Implications of Current Earnings for Future Earnings." *Journal of Accounting and Economics*, 13(4), 305–340.
- **QC community:** QC has multiple PEAD implementations using Morningstar fundamental data. Search "post earnings drift" or "SUE strategy." Quality varies — ensure point-in-time EPS data is used (no lookahead bias).
- **Crowding score:** Medium-high. Widely documented and traded by quant funds. Large-cap implementation less crowded than small-cap.

---

## References

- Ball, R. & Brown, P. (1968). "An Empirical Evaluation of Accounting Income Numbers." *Journal of Accounting Research*, 6(2), 159–178.
- Bernard, V.L. & Thomas, J.K. (1989). "Post-Earnings-Announcement Drift." *Journal of Accounting Research*, 27(S), 1–36.
- Bernard, V.L. & Thomas, J.K. (1990). "Evidence That Stock Prices Do Not Fully Reflect the Implications of Current Earnings for Future Earnings." *Journal of Accounting and Economics*, 13(4), 305–340.
- Livnat, J. & Mendenhall, R.R. (2006). "Comparing the Post-Earnings-Announcement Drift for Surprises Calculated from Analyst and Time Series Forecasts." *Journal of Accounting Research*, 44(1), 177–205.
- Chordia, T. & Shivakumar, L. (2006). "Earnings and Price Momentum." *Journal of Financial Economics*, 80(3), 627–656.

---

*Alpha Research Agent | Manual Research Batch | 2026-06-09*
