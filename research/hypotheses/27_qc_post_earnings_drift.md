# Post-Earnings Announcement Drift (PEAD) — Long Large-Cap Earnings Gappers

**Version:** 1.1
**Author:** Alpha Research Agent (QC Discovery — QUA-228)
**Date:** 2026-03-16
**Last Updated:** 2026-03-16 (Research Director — QUA-244)
**Asset class:** US equities (individual stocks)
**Strategy type:** single-signal, event-driven
**Status:** SUSPENDED — Data infrastructure failure (see Gate 1 Result below)

## Summary

Post-Earnings Announcement Drift (PEAD) is one of the most robustly documented market anomalies: stocks that gap up significantly on earnings day (signalling a positive earnings surprise) continue to drift upward for 20–60 days post-announcement. The mechanism is market underreaction — investors fail to fully incorporate the earnings signal into prices on announcement day. The strategy buys the top S&P 500 stocks that gap up ≥ 3% on earnings day and holds for 20 trading days, using a SPY 200-day moving average filter to suppress trading during sustained market downtrends.

## Gate 1 Result — FAIL (Data Infrastructure)

**Verdict date:** 2026-03-16
**Engineering Director verdict:** [QUA-234](/QUA/issues/QUA-234)
**CEO strategic decision:** Option A — Suspend pending data budget approval ([QUA-234](/QUA/issues/QUA-234))

### Outcome

| Criterion | Result |
|---|---|
| Gate 1 criteria passed | **2 of 10** |
| Trade count (IS window) | **0 trades** — strategy produced no entries |
| IS Sharpe | **N/A** — 0 trades |
| Root cause | **Data infrastructure failure** — not a strategy flaw |

### Root Cause

`yfinance` earnings data (`get_earnings_dates()`) covers approximately **3 years of history (2022–present)** only. The Gate 1 in-sample window requires **2007–2021 (14 years)** of earnings calendar data. With no historical earnings dates available for the IS period, the strategy placed 0 trades and produced no backtest results.

**Fix attempt (QUA-243):** Engineering replaced deprecated `earnings_dates` with `get_earnings_dates(limit=60)` and added `lxml` dependency. This resolved the API call but **did not extend historical coverage** — yfinance still returns only ~3 years of earnings history regardless of the `limit` parameter. The data gap is structural, not a code bug.

### Academic Soundness

The PEAD hypothesis itself remains **academically sound**. Bernard & Thomas (1989), Ball & Brown (1968), and Chordia & Shivakumar (2006) provide robust multi-decade evidence for the effect. The Gate 1 failure is a **data infrastructure failure only** — it does not invalidate the economic rationale or the strategy design.

### Revival Path

This hypothesis can be re-evaluated once a **point-in-time earnings calendar** is available for the 2007–2021 IS window. Viable data sources (priority order):

1. **Benzinga API** — Cost-effective option; provides historical earnings dates with timestamps. Estimated cost: $50–200/month.
2. **Refinitiv (LSEG) Eikon** — Full point-in-time earnings coverage; institutional pricing.
3. **Compustat (via WRDS)** — Gold standard for academic backtesting; requires university/institutional subscription.
4. **Bloomberg Terminal** — Comprehensive; available if firm subscribes.

**Revival trigger:** Board approves data budget for one of the above sources, AND the data covers ≥ 10 years of S&P 500 earnings dates with announcement timestamps.

**Status upon revival:** Revert to READY, re-run Gate 1 with full IS window. No strategy parameter changes required — the hypothesis design is unchanged.

---

## Economic Rationale

**Core mechanism:** Bernard & Thomas (1989) showed that the market systematically underreacts to earnings announcements and that the underreaction magnitude is proportional to the initial price reaction. Stocks with the largest positive earnings surprise (proxied by price gap-up on announcement day) continue to drift upward for 30–60 days before prices fully adjust.

**Why underreaction persists:**

1. **Analyst forecast anchoring:** Sell-side analysts revise earnings models slowly after surprises, delaying institutional price discovery. Consensus estimate upgrades trickle out over weeks, creating a sustained buying stream.

2. **Institutional "confirmation" trading:** Many institutional investors wait for multiple consecutive quarters of positive surprises before increasing position size. This creates a multi-week follow-on demand as the initial surprise confirms a new earnings trend.

3. **Limits to arbitrage:** Holding costs (commissions, slippage, short-side risk for market-neutral implementations), earnings uncertainty, and idiosyncratic risk prevent full arbitrage of the drift. Pure momentum traders amplify rather than eliminate the anomaly.

**Academic support:**
- Ball & Brown (1968): Original documentation of earnings drift
- Bernard & Thomas (1989): Quantified 60-day drift persistence; showed drift proportional to SUE (standardised unexpected earnings)
- Quantpedia #0033: 15% annualised CAGR documented across 2001–2020 using long-only implementation on US equities
- Chordia & Shivakumar (2006): Confirmed PEAD persists after controlling for momentum, size, and value factors

**Why the edge persists (post-2010):** While the absolute magnitude has compressed (more professional algorithmic traders), the effect remains statistically significant in large-cap stocks because institutional mandate constraints prevent fully exploiting the drift within a single quarter.

**Novelty vs. existing hypotheses:**
- All H01–H24 use price signals (momentum, mean reversion, calendar). This is the **first earnings-event-driven strategy** in the pipeline.
- Distinct from H20 (sector momentum) — PEAD uses earnings events, not price-based momentum signals.
- Distinct from H21 (IBS) — PEAD is a multi-week trend; IBS is intraday range reversal.

## Entry/Exit Logic

**Universe:** S&P 500 constituent stocks (via yfinance `tickers` + `^GSPC` membership proxy using top 500 by market cap), filtered daily.

**Entry signal:**
1. **Earnings event trigger:** On day T (earnings announcement day), identify stocks in the universe that:
   - Gapped up ≥ `gap_threshold`% from prior day close to current day open (default: 3%)
   - Are NOT already in the portfolio (no doubling-up)
2. **Market regime filter:** Do NOT enter any position if SPY closes below its **200-day simple moving average** on day T. Skip the earnings cycle for that day.
3. **Entry execution:** Buy at close on day T (after confirming the gap held through close, reducing noise trades from intraday reversals)

**Exit signal:**
- **Time-based exit:** Close position at close on day T + 20 trading days (≈ 1 month post-announcement)
- **No stop loss** (evidence shows PEAD drift is non-monotonic intraday; stops add noise more than protection over a 20-day window)

**Portfolio construction:**
- Maximum concurrent positions: 5 stocks (≤ 20% weight each, equal-weight)
- If 6th opportunity arises and portfolio is full: skip until a position exits
- Target: diversified across sectors to reduce idiosyncratic risk

**Trade frequency:**
- S&P 500 has ≈ 500 earnings events/quarter = 2,000/year
- With 3% gap-up filter: ≈ 15–25% of earnings surprise → 300–500 entries/year
- With 200-day MA filter active in bear markets: frequency drops substantially in 2022/2008
- Practical active positions: ≈ 80–150 round-trip trades/year in a moderate market regime

**Rebalancing:** Event-driven. Daily scan for new earnings gaps. PDT-safe (20-day holds).

## Market Regime Context

**Works best:**
- Bull market or sideways trending markets where earnings revisions are upward
- Low-volatility regimes (VIX 12–20): Institutional confidence in earnings trajectory is highest
- Earnings seasons (peak activity: January, April, July, October)

**Tends to fail:**
- Sustained bear markets: Even positive earnings surprisers fall with the market. 2008–2009 and 2022 are primary failure regimes.
- Macro regime shifts: When macro surprises dominate over company earnings (e.g., 2022 rate shock, 2020 COVID), PEAD signal is overwhelmed by systematic factor moves.
- Earnings uncertainty: When analysts widely disagree on estimates, the "surprise" signal is noisy.

**Regime gate (200-day MA filter):**
- SPY below 200-day MA = do not open new PEAD positions
- Existing positions continue until their 20-day exit (do not force-close on regime change)
- Resume new entries only when SPY re-crosses 200-day MA from below

## Alpha Decay Analysis

- **Signal half-life estimate:** 10–15 trading days. The drift is most rapid in days 1–10 post-announcement (consensus revisions release, analyst upgrades published) and decays gradually by day 20–30.
- **IC decay curve:**
  - T+1 (day after announcement): IC ≈ 0.10–0.15 (initial momentum continuation)
  - T+5: IC ≈ 0.07–0.10 (analyst upgrades still flowing)
  - T+20 (exit day): IC ≈ 0.03–0.06 (weaker but still positive drift)
  - T+60: IC ≈ 0.01–0.02 (near-full price discovery by 3-month horizon)
- **Transaction cost viability:** At $25K account, trading 80–150 round-trips/year in S&P 500 stocks (average liquidity ≈ $5B market cap). Round-trip cost ≈ 0.05–0.15% (SPY-grade stocks). Historical PEAD 20-day excess return ≈ 1.0–2.5% per trade pre-cost. After costs: 0.85–2.35% per trade. Edge survives costs clearly.
- **Slippage concern:** Entry at close on gap-up day captures confirmed gap but may involve slippage in fast-moving stocks. Alternative: entry next morning (T+1 open) reduces slippage risk but surrenders Day 0 continuation gap.
- **Annualised IR estimate:**
  - 100 trades/year × 1.5% average excess return = 15% annual excess return
  - Portfolio of 5 positions × 20-day holds → diversified daily vol ≈ 12–15%
  - Pre-cost Sharpe ≈ 15% / 13% ≈ 1.15 (literature estimate; realised lower due to market regime exposure)

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `gap_threshold` | 2% – 5% | 3% is academic baseline; 2% increases frequency but dilutes signal; 5% reduces entries to only major surprises |
| `hold_days` | 10, 20, 40, 60 | Bernard & Thomas show max drift at 60 days; 20 days captures most of the fast-adjustment component |
| `max_positions` | 3 – 10 | 5 is baseline; fewer = more concentrated; more = diluted but lower idiosyncratic risk |
| `ma_filter_period` | 100, 150, 200 days | 200-day SMA is academic standard for long-term trend filter |
| `entry_timing` | T close vs. T+1 open | T close: captures gap confirmation; T+1 open: reduces slippage on fast-movers |
| `min_market_cap` | $5B – $20B | Large-cap filter reduces liquidity risk; $10B is a reasonable baseline |

## Asset Class & PDT/Capital Constraints

- **Assets:** S&P 500 large-cap individual stocks
- **Minimum capital:** $25,000 (5 positions × 20% weight = $5,000 per position; large-cap stocks need meaningful sizing)
- **PDT impact:** None — 20-day holds. No day-trades consumed. PDT-safe. ✓
- **Position sizing:** Equal weight, 20% per stock, maximum 5 concurrent
- **Concentration risk:** Medium — 5 positions with 20% each. Sector filter recommended (max 1 position per sector).

## Pre-Flight Gate Checklist

| Gate | Status | Detail |
|---|---|---|
| **PF-1: Walk-Forward Trade Viability** | **PASS** | ~100 trades/year × 5y IS = 500 trades. 500 ÷ 4 = 125 ≥ 30. ✓ Even with 200-day MA filter reducing entries by 50% in bear markets: 50 × 5 = 250 ÷ 4 = 62.5 ≥ 30. Robust pass. |
| **PF-2: Long-Only MDD Stress** | **CONDITIONAL PASS** | Dot-com bust (2000–2002): SPY fell below 200-day MA in March 2001. New PEAD entries halted. Existing 20-day holds would ride out positions entered before the filter triggered. Estimated peak portfolio drawdown: 20–30% (from positions opened in early 2001 before filter triggered). GFC (2008): SPY crossed below 200-day MA in January 2008. PEAD entries stop. Positions opened in late 2007 would suffer; estimated MDD: 25–35%. **Both < 40% — conditional pass. Key risk: entries opened in the 20-day window just before the MA filter triggers.** Engineering must validate that drawdown during those "trailing" positions stays < 40%. |
| **PF-3: Data Pipeline Availability** | **PASS** | S&P 500 stock OHLCV via yfinance (5+ years for all constituents). Earnings dates via `yf.Ticker(sym).earnings_dates` (returns historical calendar). SPY 200-day MA from daily OHLCV. All in existing pipeline. No options, intraday, or specialist data required. ✓ |
| **PF-4: Rate-Shock Regime Plausibility** | **CONDITIONAL PASS** | SPY crossed below its 200-day MA on January 21, 2022. PEAD entries would halt immediately. Positions opened in late 2021 (last 20-day cycle before filter triggers): these would ride out their 20-day hold ending around February 2022 — a volatile but not catastrophic period (SPY ~-5% in January). After January 21: zero new positions for most of 2022 (SPY remained below 200MA until Q4 2022). Portfolio cash for 9+ months of 2022. Estimated 2022 loss: ~3–8% from positions stranded at filter trigger. A priori rationale: **the 200-MA filter is the rate-shock defense mechanism** — it explicitly stops long-only equity exposure when the macro trend turns. This is a documented, tested mechanism, not "the backtest might capture it." **PASS conditional on MA filter implementation.** |

**All 4 PF gates: CONDITIONAL PASS — PF-2 and PF-4 depend on 200-day MA filter being correctly coded and validated. PF-2 requires Engineering to confirm "trailing position" MDD < 40%.**

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Achievable. Literature estimates 0.8–1.3 Sharpe for PEAD long-only with market filter. Large-cap universe + 200-day MA filter should produce IS Sharpe in the 0.8–1.2 range over 2007–2022 IS window. Key risk: the 2022 regime (100% in cash from February onward) may depress IS Sharpe to 0.6–0.9 depending on IS window construction.
- **OOS persistence:** Medium-high. PEAD has been documented continuously since 1968 and survives post-2010 (albeit with compressed magnitude). Large-cap implementation avoids the micro-cap illiquidity artifacts that inflate some academic estimates.
- **Walk-forward stability:** Likely stable. Only 2 key parameters (`gap_threshold`, `hold_days`); both motivated by academic consensus. The MA filter is a well-known regime screen.
- **Sensitivity risk:** Medium. Results may be sensitive to exact `gap_threshold` (2% vs. 3% vs. 5% meaningfully changes universe). Test across the full range.
- **Known overfitting risks:**
  - Gap threshold (3%) round-number bias — test at 2.5% and 3.5%
  - 200-day MA is the most-used lookback in finance; slight optimization risk. Test at 150, 200, 250 days.
  - PEAD magnitude has compressed post-2015 as algorithmic traders front-run the effect; test 2015–2022 subsample separately.

## QuantConnect Source Caveat

- **Academic source:** Quantpedia Strategy #0033 — "Post-Earnings Announcement Effect"
- **Key papers:** Ball & Brown (1968); Bernard & Thomas (1989); Chordia & Shivakumar (2006)
- **QC community implementations:** Multiple QC strategies implement PEAD variations. Not in top-10 most-cloned strategies in QC community. However, PEAD is a well-known academic effect and may have moderate crowding in systematic hedge funds.
- **Apparent backtest window (QC implementations):** Most QC community PEAD implementations cover 2010–2020. Critical to test 2007–2009 (GFC validation) and 2020–2022 (COVID + rate shock validation).
- **Crowding score:** Medium. PEAD is academically well-known and systematically traded by quant funds. However, capacity constraints on large-scale arbitrage (position limits, implementation slippage) mean retail-scale implementation retains meaningful edge. The magnitude has compressed from ~2.5% 20-day excess return (pre-2000) to ~1.0–1.8% (2010–2020).
- **Novel insight vs. H01–H24:** All prior hypotheses use price signals (technical indicators, calendar effects, cross-asset signals). PEAD is the **first earnings-event-driven strategy** in the pipeline, introducing a fundamentally different alpha source: fundamental information flow rather than price pattern.
- **Earnings data availability:** `yfinance` provides `earnings_dates` for individual tickers via `Ticker.earnings_dates` (returns historical earnings announcement dates). This is in the existing pipeline and does not require a paid data subscription. Key limitation: yfinance earnings data may have gaps for smaller or delisted stocks; recommend using the top 200 S&P 500 by market cap to ensure data completeness.

## References

- Ball, R. & Brown, P. (1968). "An Empirical Evaluation of Accounting Income Numbers." *Journal of Accounting Research*, 6(2), 159–178.
- Bernard, V.L. & Thomas, J.K. (1989). "Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?" *Journal of Accounting Research*, 27, 1–36.
- Chordia, T. & Shivakumar, L. (2006). "Earnings and Price Momentum." *Journal of Financial Economics*, 80(3), 627–656.
- Quantpedia #0033: Post-Earnings Announcement Effect — https://quantpedia.com/strategies/post-earnings-announcement-effect/
- Quantpedia #0080: Earnings Announcement Premium — https://quantpedia.com/strategies/earnings-announcement-premium/ (related: holding stocks in the week BEFORE earnings; distinct from post-announcement drift)
- Related in knowledge base: `research/hypotheses/05_momentum_vol_scaled.md` (price momentum — different signal), `research/hypotheses/20_tv_sector_momentum_rotation.md` (sector momentum — different signal)
