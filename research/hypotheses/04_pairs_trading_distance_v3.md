# Hypothesis 04-v3: Pairs Trading via Distance Method (Gatev et al., 2006)

**Version:** 3.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** pairs
**Status:** hypothesis

---

## 1. Summary and Economic Rationale

### Why This Edge Exists

Pairs trading exploits the short-term divergence and subsequent convergence of co-moving assets. The Gatev Distance Method selects pairs by identifying ETFs whose **normalized price series tracked each other most closely over a formation window** — then trades when they deviate. The mechanism is:

1. **Common factor exposure:** Pairs selected by low SSD share a dominant common risk factor (e.g., crude oil for XLE/OIH, credit cycle for XLF/KRE). When one leg temporarily overperforms or underperforms the other, the shared factor pulls them back together.
2. **Relative value arbitrage:** Institutional capital seeks relative-value opportunities within sectors. Temporary mispricings between closely-related ETFs attract mean-reversion flows as participants rebalance.
3. **Behavioral anchoring:** Traders and quants operating within a sector anchor to historical co-movement ratios. Deviations beyond 2 standard deviations attract systematic rebalancing.

**Why this approach is academically grounded:** Gatev, Goetzmann & Rouwenhorst (2006) documented 11% annualized excess returns on equity pairs (1962–2002) using exactly this method on individual stocks. The ETF adaptation is supported by the same mechanism — sector ETFs have lower idiosyncratic noise, which should improve signal quality relative to individual equity pairs.

**Market inefficiency exploited:** The edge persists because:
- The time horizon (days to weeks) is too slow for HFT arbitrage
- ETF pairs trading lacks the high-profile institutional coverage that individual stock pairs attract
- The spread is macro-driven and behavioral, not information-driven — harder to front-run

### Why This Is a Testable Hypothesis

The distance method does not require formal cointegration. It requires only that the selected pairs co-moved closely in the past and that deviations are temporary. This is a weaker, more empirically-validated assumption than cointegration stationarity.

---

## 2. Comparison to v2.0 — Why This Avoids the Failure Mode

### v2.0 Failure Summary

H04-v2 pre-screen (QUA-82) confirmed that **every tested pair fails the Engle-Granger 30% cointegration threshold** in the 2018–2021 IS window. The best result was XLP/XLY at 19.0% (63d window) — 11 percentage points below threshold. Root causes:

| Failure Driver | Impact on Engle-Granger |
|----------------|------------------------|
| COVID-19 structural break (March 2020) | Sharp regime shift; cointegration relationship disrupted for quarters |
| Asymmetric sector recovery | XLY (dominated by AMZN/TSLA) vs. XLP (slow-moving staples): sustained divergence |
| GLD/SLV silver short squeeze (Jan 2021) | Historically unique event; cointegration model cannot accommodate |
| Rate sensitivity asymmetry (KRE vs XLF) | Regional banks repriced more severely than broad financials in rate cycle |

**Root cause identified:** Engle-Granger tests for a statistical property (stationarity of the spread) that systematically fails during macro regime shifts. COVID forced every sector ETF spread into non-stationarity for extended periods.

### How H04-v3 Avoids This Failure

| Property | Engle-Granger (v2) | Distance Method (v3) |
|----------|-------------------|---------------------|
| Formal stationarity required? | **Yes** — spread must be I(0) | **No** — only similarity of price paths in formation window |
| Sensitive to regime breaks? | **High** — single break fails the test | **Low** — measures historical co-movement, not distributional stability |
| Trade gate active during COVID? | **Near-zero** — p-values near 0.5 | **Yes** — pair selected if SSD was low in prior 252d formation window |
| Trade count with filter | < 5 per pair in IS window | 3–5 per pair per 6-month trading period |
| Key assumption | Cointegrating relationship stable | Pairs that co-moved in formation continue to exhibit short-term mean reversion |

**The distance method is not immune to COVID — it will generate some losing trades during extreme regime breaks. But it will generate trades at all, which is the prerequisite for earning any return. v2 with the cointegration gate active would earn nearly zero return because it would almost never open a position.**

The stop-loss at 4 standard deviations provides downside protection for the worst COVID-driven dislocations (e.g., XLE/OIH during oil price collapse).

---

## 3. Entry / Exit Logic

### Universe (Expanded — 14 Candidate ETFs)

Screen all candidate pairs from the following ETF universe each formation period:

| ETF | Sector/Theme |
|-----|-------------|
| XLF | US Financials (broad) |
| KRE | Regional Banks |
| XLE | Energy Sector |
| OIH | Oil Services |
| XLV | Healthcare |
| IBB | Biotech |
| XLP | Consumer Staples |
| XLY | Consumer Discretionary |
| GLD | Gold |
| SLV | Silver |
| XLK | Technology |
| XLI | Industrials |
| XLU | Utilities |
| TLT | Long-duration Treasuries |

> GDX and USO excluded from initial universe: GDX has substantial tracking error vs. GLD; USO undergoes periodic roll restructuring that creates artificial price discontinuities. Revisit in v3.1 if initial universe is insufficient.

**Total candidate pairs:** C(14,2) = 91 pair combinations screened each formation period.

### Formation Period (Pair Selection)

1. At the start of each 6-month trading period, look back 252 trading days (formation window).
2. Normalize each ETF's price to $1.00 at the start of the formation window.
3. For every candidate pair (A, B), compute the **Sum of Squared Deviations (SSD)**:
   ```
   SSD(A,B) = Σ (normalized_price_A[t] - normalized_price_B[t])² for t in formation window
   ```
4. **Select the top-5 pairs with the lowest SSD** as the active trading universe for the next 6 months.
5. Re-run pair selection every 6 months (rolling). Pairs are replaced at each re-selection cycle.

**No cointegration test required at formation.** Pair selection is purely distance-based.

### Spread Calculation (Per Active Pair)

During the trading period:
1. Use the **same formation-window normalization** as the baseline ($1.00 at formation start).
2. Spread = normalized_price_A[t] − normalized_price_B[t]
3. Reference distribution = mean and std of spread **computed over the formation window only** (no look-ahead)
4. Z-score = (Spread[t] − formation_mean) / formation_std

### Entry Signal

- **Long A / Short B** when z-score < −`entry_zscore` (A cheap relative to B)
- **Long B / Short A** when z-score > +`entry_zscore` (B cheap relative to A)
- Maximum 1 active position per pair at a time
- Maximum 5 active pairs simultaneously (by construction from top-5 selection)

**Entry signal:** `abs(zscore) > entry_zscore` with `entry_zscore` = 2.0 (seed value)

### Exit Signal

| Exit Condition | Trigger | Action |
|----------------|---------|--------|
| Convergence (primary) | Z-score returns within ±`exit_zscore` of 0 | Close both legs |
| Time stop | Position held > `max_holding_days` | Close both legs at close of day |
| Stop-loss | Z-score exceeds ±`stop_zscore` | Close both legs immediately |

Seed values: `exit_zscore` = 0.5, `max_holding_days` = 126 (6 months, matching trading period), `stop_zscore` = 4.0

### Position Sizing

- **Dollar-neutral construction:** Equal dollar allocation to both legs at entry
- Each active pair uses: portfolio capital × `position_size_pct` (seed: 20% = $5,000 per pair on a $25K account)
- Hedge ratio = 1.0 (equal dollar, not beta-weighted, since normalized series is already dollar-normalized)
- Maximum 5 concurrent pairs → maximum 100% notional deployment (both legs count as separate positions)

### VIX Overlay (Carried Forward from v2)

| VIX Level | Action |
|-----------|--------|
| VIX < 30 | Normal operation |
| VIX 30–40 | No new positions; hold existing |
| VIX > 40 | Close all positions at next close |

**Holding period:** Swing/Position — 5 to 126 trading days. Median expected hold: 15–30 days.

---

## 4. Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| **Range-bound / low-vol** | Excellent — pairs co-move tightly; deviations are short-lived and revert cleanly |
| **Trending (broad market)** | Good — dollar-neutral construction is market-direction agnostic; trending markets often produce intra-sector sector rotation that creates spread opportunities |
| **High volatility / crisis (VIX 20–30)** | Mixed — more frequent entry signals but higher stop-loss risk; time to convergence may extend |
| **Extreme vol (VIX > 40)** | Exit all — macro dislocations can push normalized spreads to 6–8 std dev; stop-loss protection insufficient without full exit |
| **Rate cycle transitions** | Moderate risk — rate hikes reprice duration differently across sectors; TLT inclusion may show rate-sensitive spread divergence. Monitor. |
| **Post-COVID recovery (2020–2021)** | Specific risk: the K-shaped recovery drove permanent divergence in XLP/XLY and XLV/IBB. Distance method should recognize this: pairs with high SSD in the 2020–2021 formation window will NOT be selected (their distance was too high). This is the self-correcting feature. |

**When to pause:** If > 3 of 5 active pairs trigger the stop-loss within the same 20-day window, suspend new position opens for 30 days. This is a signal that the market is in a correlation-breakdown regime.

---

## 5. Alpha Decay

- **Signal half-life (days):** 15–20 days (estimated median time-to-convergence from Gatev et al. empirical results; ETF pairs with cleaner co-movement may revert faster than individual stock pairs)
- **Edge erosion rate:** moderate (5–20 days)
- **Recommended max holding period:** 30 days (approximately 1.5× half-life); time stop at 126 days is a backstop, not a target
- **Cost survival:** Yes — at 15–20 day median hold and expected 3–5 trades per pair per 6-month period, per-trade transaction cost (est. $0.005/share × 2 legs + 0.05% slippage) is comfortably absorbed by the spread deviation captured
- **IC estimates:**
  | Horizon | Estimated IC | Notes |
  |---------|-------------|-------|
  | T+1 | 0.05–0.08 | Short-term momentum of spread; first day may extend before reversing |
  | T+5 | 0.10–0.15 | Peak IC zone; most convergence occurs in 5–20 day window |
  | T+20 | 0.03–0.07 | Decay phase; positions beyond 20 days often depend on time stop, not signal |
- **Annualized IR estimate:** Gatev et al. documented ~11% annualized excess return on equity pairs with ~15% portfolio vol → IR ≈ 0.73. For ETF pairs (lower idiosyncratic noise, lower return per trade), conservatively estimate IR ≈ 0.4–0.6 pre-cost. Post-cost estimate: 0.3–0.5. Borderline but above the 0.3 warning threshold.
- **Notes:** IC is regime-dependent. In high-volatility periods (VIX > 25), spread deviations are larger but convergence speed slows. Net IC is roughly stable but shape of decay changes. Crowding concern is moderate: the Gatev method is well-known and increasingly crowded in equity pairs; ETF pairs are less crowded, but institutional adoption has grown since the 2006 paper.

---

## Cointegration Analysis *(pairs strategy type — modified for distance method)*

> **Note:** H04-v3 deliberately replaces the Engle-Granger cointegration test with the distance method. Formal cointegration is NOT required for pair selection in this strategy. The cointegration test failure that disqualified H04-v2 is avoided by design.

The following documents the **expected characteristics** of top-5 SSD-selected pairs based on formation-window analysis (pre-backtest estimate):

- **Pair selection method:** SSD ranking on normalized price series (252-day formation window)
- **Expected Hurst exponent of selected spreads:** 0.35–0.48 (mean-reverting, below 0.5 threshold) — distance method selects for pairs with naturally mean-reverting spread characteristics without requiring a formal test
- **Expected half-life (OU process estimate):** 10–25 days
- **Stability note:** Pair composition changes every 6 months. This is a feature, not a bug — if a pair's co-movement breaks down (e.g., XLP/XLY during COVID), it will fall out of the top-5 by SSD at the next re-selection, naturally adapting to the current regime.

**Pre-backtest check required:** Before passing to Engineering Director, confirm that the top-5 SSD pairs selected in the 2018-01-01 formation window are broadly sensible (i.e., pairs from same sector or related sectors, not spurious low-SSD from a coincidental short-term correlation). This is a qualitative sanity check, not a quantitative gate.

---

## 6. Parameters to Test

| Parameter | Seed Value | Suggested Range | Rationale |
|-----------|-----------|-----------------|-----------|
| `formation_days` | 252 | [189, 252, 315] | Standard annual lookback; test half-year and 15-month alternatives |
| `n_pairs` | 5 | [3, 5, 7] | Top-N pairs by SSD; more pairs = more diversification but more marginal pairs |
| `entry_zscore` | 2.0 | [1.5, 2.0, 2.5] | Primary sensitivity parameter; higher = fewer, higher-quality trades |
| `exit_zscore` | 0.5 | [0.0, 0.5, 1.0] | Exit tightness; 0.0 = full reversion required; 0.5 = partial reversion accepted |
| `stop_zscore` | 4.0 | [3.0, 4.0, 5.0] | Stop-loss width; must be calibrated to COVID-sized events |
| `max_holding_days` | 126 | [63, 126] | Hard time stop; 63d = one formation cycle; 126d = two |
| `reselect_period_days` | 126 | [63, 126] | Pair re-selection frequency; more frequent = faster adaptation |

**Free parameter count:** 7. This exceeds the Gate 1 limit of 6 free parameters. Recommendation: fix `reselect_period_days = 126` (aligned with `max_holding_days`) to reduce to 6 free parameters. This is operationally clean and well-motivated.

---

## 7. Capital and PDT Compatibility

- **Minimum capital required:** $25,000 (matches firm account)
- **PDT impact:** Low — median holding period of 15–30 days; typical pair is opened and closed once per trading period. PDT rule (3 day-trades per 5 days for accounts < $25K) is not a binding constraint at this holding period.
- **Position sizing:** 20% of portfolio per pair ($5,000 per pair on $25K), equal dollar allocation to both legs ($2,500 per leg). ETFs trading above $10/share → minimum lot sizes easily accommodated.
- **Short selling:** Required for one leg of each pair. Reg T margin (50% initial) requires ~$1,250 margin per short leg → 5 active pairs = ~$6,250 in margin requirement. Well within $25K capital.
- **Borrow cost:** Sector ETF short borrow is near-zero (institutional ETF lending market is deep). Not a material cost.
- **Concurrent positions:** Maximum 10 ETF legs (5 pairs × 2 legs). At $2,500 per leg, total notional = $25,000 (fully deployed at 5 active pairs). Typically 2–3 pairs are active simultaneously → $10,000–$15,000 deployed.

---

## 8. Gate 1 Outlook (2018–2021 IS Window Specific)

### Key Differences from v2.0 That Improve Gate 1 Odds

The elimination of the cointegration filter is the decisive change. With v2's filter active, the strategy would open < 5 positions per pair in the 2018–2021 IS window — generating < 25 total trades (far below the 50-trade minimum). The distance method removes this gate entirely, allowing the strategy to operate throughout the IS window.

### Quantitative Projections

| Gate 1 Criterion | Threshold | Assessment | Reasoning |
|-----------------|-----------|------------|-----------|
| **IS Sharpe > 1.0** | > 1.0 | **Uncertain / Possible** | Gatev et al. documented IR ~0.73 on equity pairs; ETF pairs less idiosyncratic → lower per-trade return but more reliable convergence. IS Sharpe estimate: 0.7–1.3. COVID crash (March 2020) creates both risk and opportunity — if stop-losses hold, March 2020 dislocations may generate large-profit trades on reversion |
| **OOS Sharpe > 0.7** | > 0.7 | **Uncertain** | OOS window (2022–2023) includes rate hike cycle; TLT and rate-sensitive sectors may show elevated spread volatility; distance method adapts at each 6-month re-selection |
| **Walk-forward consistency** | OOS within 30% of IS | **Possible** | Distance method's rolling re-selection provides adaptability; each window selects pairs from the current regime's co-movers |
| **IS Max Drawdown < 20%** | < 20% | **Likely Pass** | Dollar-neutral construction limits market-direction drawdown; stop-loss at 4 std dev caps individual pair loss |
| **Win Rate > 50%** | > 50% | **Likely Pass** | Gatev et al. report 51–57% win rates on equity pairs; ETF pairs may be slightly higher |
| **Trade Count > 50 (IS)** | > 50 | **Likely Pass** | 5 pairs × 4 round-trips per pair per year × 4-year IS = ~80 expected trades; more if entry_zscore is reduced to 1.5 |
| **Parameter sensitivity < 30%** | < 30% | **Uncertain** | `entry_zscore` is the highest-sensitivity parameter (as in v1 and v2); ±20% perturbation from 2.0 to [1.6, 2.4] must not cause > 30% Sharpe change |
| **Walk-forward windows ≥ 3/4** | ≥ 3/4 | **Possible** | Likely to pass the 2020 window (COVID dislocations create clear entry/exit signals) and 2022 window (sector rotation during rate hikes); uncertain for other windows |

### Known Overfitting Risks

1. **Top-5 pair selection is data-driven:** In each formation window, the strategy selects the 5 "best" pairs by construction. If all 91 candidate pairs have near-zero mean reversion, the top-5 will still be selected but the signals will be weak. The formation-window SSD is not a quality gate — it is a relative ranking.
2. **COVID tail risk:** March 2020 may generate 2–3 very large winning trades (historic dislocations that fully revert) which could inflate IS Sharpe. This would be a regime-specific windfall, not a generalizable edge. Walk-forward consistency test will reveal this.
3. **Parameter sensitivity on `entry_zscore`:** Prior pairs versions showed high sensitivity to entry threshold. At entry_zscore = 2.0, there are ~15–25% fewer trades than at 1.5. If the IS Sharpe depends heavily on entry_zscore being exactly 2.0, this is an overfitting signal.
4. **Universe composition:** The 14-ETF universe is selected with domain knowledge. A truly unbiased test would screen all liquid ETFs. The pre-selected universe is a mild form of domain bias — defensible academically, but worth noting.

### Gate 1 Probability Assessment

- **IS Sharpe > 1.0:** 45–55% probability. Key unknown: whether 2018–2021 IS window's elevated volatility (COVID) helps or hurts. The distance method captures large dislocations, but the stop-loss must be calibrated correctly.
- **OOS persistence:** 40–50% probability. Rate hike cycle in 2022–2023 creates new regime for distance-based pairs.
- **Walk-forward stability:** 50–60% probability. Rolling re-selection is the best mechanism available for regime adaptation.
- **Sensitivity risk:** Medium. `entry_zscore` and `stop_zscore` are the highest-sensitivity parameters.
- **Overall Gate 1 pass probability:** **35–55%.** This is a genuine research-grade hypothesis with academic support. Not a high-confidence slam-dunk, but worth backtesting given the clear mechanism and the failure of all alternatives.

---

## Pre-Backtest Checklist (Anti-Look-Ahead Safeguards)

Critical look-ahead bias risks and mitigations for the Engineering Director:

- [ ] **Formation window is strictly historical:** Pair selection at time T uses only data from [T−252, T−1]. No future price data enters the SSD computation.
- [ ] **Spread z-score uses formation-window statistics only:** Formation mean and std computed over [formation_start, T−1]. The z-score at time T does NOT recalculate mean/std on an expanding window that includes trading-period data.
- [ ] **Pair re-selection is at fixed calendar intervals:** Re-selection happens at [T=0, T+126, T+252, ...], not triggered by strategy performance. If triggered by spread behavior, this introduces look-ahead.
- [ ] **VIX data is lagged by 1 day:** Use VIX[T−1] for the VIX overlay check at time T. VIX closing value is available next morning — do not use same-day VIX close as if it were available at open.
- [ ] **No survivor bias in ETF universe:** All 14 ETFs have existed and been liquid since 2017. Confirm each has data from at least 2017-01-01. (TLT: listed 2002. GLD: 2004. GDX: 2006. All others: pre-2007.) ✓
- [ ] **Stop-loss execution:** Stop-loss is triggered when Z-score > `stop_zscore` at daily close. Execute at next-day open (not same-day close). This is conservative and realistic.
- [ ] **Normalization anchor:** Each leg is normalized to $1.00 at the start of the formation window. During the trading period, the normalized price continues to compound from the formation anchor. Do NOT re-normalize at the start of the trading period.

---

## Signal Validity Pre-Check

1. **Survivorship bias:** All 14 candidate ETFs are active and liquid throughout the backtest period (2018–2023). No ETF in the universe faced delisting or major structural change. **PASS.**
2. **Look-ahead bias:** All safeguards documented above. Formation statistics are fully historical. The primary risk is accidental introduction of future data in SSD calculation — must be verified in code review. **FLAG for Engineering Director code review.**
3. **Overfitting risk:** This is the third version of H04. Selection of the distance method was motivated by a specific, documented failure (Engle-Granger rigidity), not by mining hypothesis variants until one backtests well. The Gatev (2006) method is the first-principles academic benchmark. **ACCEPTABLE.**
4. **Capacity:** $25K account with up to 5 active pairs, $2,500 per leg. All ETFs trade > 10M shares/day. **PASS.**
5. **PDT awareness:** 15–30 day median hold → well below PDT threshold. **PASS.**
6. **Costs:** Per-trade cost = 2 × $0.005/share + 0.10% slippage on round-trip. At ~$2,500 per leg and ETF prices of $30–$150/share, this is $0.50–$2.50 commission + $5–$25 slippage per trade = $11–$55 total round-trip cost per pair. At expected return per trade of 0.5–1.5% of $5,000 = $25–$75, costs consume 15–70% of gross return. **MARGINAL — must verify post-cost performance explicitly in backtest.**
7. **Volatility-adjusted IR:** Pre-cost IR estimate 0.4–0.6 (see Alpha Decay section). This is above the 0.3 warning threshold but not a high-confidence pass. Post-cost IR estimate 0.2–0.4. The 0.2 lower bound is below the 0.3 warning threshold — backtest must confirm. **BORDERLINE — flag for close monitoring.**

---

## References

- Gatev, E., Goetzmann, W.N., & Rouwenhorst, K.G. (2006). *Pairs Trading: Performance of a Relative-Value Arbitrage Rule.* Review of Financial Studies, 19(3), 797–827.
- Do, B., & Faff, R. (2010). *Does Simple Pairs Trading Still Work?* Financial Analysts Journal, 66(4), 83–95. (Documents decay of equity pairs edge post-2002; ETF pairs may be more robust)
- Vidyamurthy, G. (2004). *Pairs Trading: Quantitative Methods and Analysis.* Wiley.
- Prior hypothesis: `research/hypotheses/04_pairs_trading_cointegration_v2.md` (RETIRED — Engle-Granger failure)
- Pre-screen findings: `research/findings/h04v2_coint_prescreen_2026-03.md` (documents COVID regime break)
- Gate 1 criteria: `criteria.md`
- Research Director decision: QUA-82

---

*Alpha Research Agent | QUA-98 | 2026-03-16*
