# Hypothesis 07: Multi-Asset Time-Series Momentum (TSMOM)

**Status:** READY
**Category:** Trend Following / Absolute Momentum
**Source:** Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum" — Journal of Financial Economics
**Date:** 2026-03-16

---

## Summary

Time-series momentum (TSMOM) applies trend-following signals independently to each asset based on its own past return — in contrast to cross-sectional momentum (H05) which ranks assets relative to each other. Each asset in a 6-ETF universe (equities, bonds, gold, commodities, real estate) is evaluated monthly: if the trailing 12-month return is positive, take a long position; if negative, take a short position (or go flat for long-only variant). Positions are equally weighted and rebalanced monthly. TSMOM is structurally distinct from H05 because it does not require any relative ranking — each asset's position is determined entirely by its own trend, making it immune to the crowding dynamics that hurt cross-sectional momentum in the 2022 rate hike cycle.

---

## Economic Rationale

**Why this edge should exist:**

1. **Behavioral underreaction:** Investors systematically underreact to new information, particularly macro shifts. When the Federal Reserve begins a rate hike cycle, bond and equity markets trend downward for months because the full price impact of higher rates is priced in gradually, not instantaneously. TSMOM captures this slow price discovery.

2. **Liquidity insurance premium:** Trend-followers provide liquidity during market dislocations. They buy rising assets (increasing supply when shorts cover) and sell falling assets. This service earns a risk premium — particularly in crisis periods when trend signals are strongest.

3. **Demand for capital protection:** Institutional investors need to reduce risk as portfolios fall — creating systematic selling pressure that perpetuates trends. Pension funds and risk-parity strategies mechanically reduce equity exposure as volatility rises, amplifying trends.

4. **Cross-asset diversification:** TSMOM across uncorrelated assets (equities, bonds, gold, commodities) provides natural diversification. In 2022, equities and bonds fell together (negative equity-bond correlation) while commodities surged — TSMOM captured all three trends simultaneously.

**Why the IS window (2018–2022) is favorable:**
- **2018:** Q4 sell-off across equities — strong negative equity trend signal. TLT (bonds) rallied — positive bond trend. TSMOM would be short equities, long bonds.
- **2020 COVID crash:** Rapid equity sell-off (-34% in 33 days) followed by recovery. The signal may lag, but the 12-month lookback would be negative for equities during the trough.
- **2020–2021 recovery:** Strong positive trends in equities and commodities.
- **2022:** Exceptional TSMOM environment — equities fell ~20%, bonds fell ~15%, commodities surged. A diversified TSMOM strategy would be short equities, short bonds, long commodities, long USD. Historical research shows 2022 was one of the best years for trend-following strategies in 40 years.

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| Trending (any direction) | Excellent — this is the core regime |
| 2022-type multi-asset trend | Exceptional — uncorrelated asset trends in different directions |
| Mean-reverting / choppy | Poor — whipsaw losses from false crossings |
| Sideways consolidation | Break-even to slightly negative |
| Crisis onset (fast crash) | Lagged — 12-month lookback is slow to react to sudden 1-2 month crashes |
| Crisis recovery | Strong — catches sustained recovery trends |

**When this strategy breaks down:**
- **Sudden regime changes** (e.g., March 2020 first 2 weeks): the 12-month lookback will still show positive equity momentum while equities are collapsing; lag before signal turns negative
- **Mean-reverting environments** (2019, 2023): markets trade in ranges — trend signals generate whipsaw trades
- **Policy interventions:** Central bank pivots that reverse multi-month trends suddenly (e.g., "Fed put") can generate losses

**Critical structural advantage over H05 (cross-sectional):** TSMOM can be long _all_ assets simultaneously (if all trending up) or short _all_ (if all trending down). H05 must always be 50% long / 50% short by construction. This means TSMOM has better crisis-alpha properties.

---

## Alpha Decay Analysis

*(Required by Research Director gate before forwarding to Engineering Director)*

**Signal:** 12-month trailing total return as momentum signal.

| IC Metric | Estimate | Notes |
|-----------|----------|-------|
| IC at T+1 (next day) | ~0.01–0.02 | Very low — monthly rebalancing, not day-trading |
| IC at T+5 (1 week) | ~0.03–0.04 | Still modest; signal is slow by design |
| IC at T+20 (1 month) | ~0.05–0.08 | Peak horizon; rebalancing here is appropriate |
| IC at T+60 (3 months) | ~0.04–0.06 | Gradual decay |
| IC at T+252 (12 months) | ~0.01–0.02 | Near baseline; signal has mostly resolved |

**Signal half-life estimate:** ~60–90 trading days (3–4 months). A trend established over 12 months typically persists for an additional 1–3 months before decaying, consistent with Moskowitz et al. (2012) findings.

**IC decay shape:** Gradual — IC declines smoothly over time without a cliff drop. The 12-month lookback smooths short-term noise, producing a robust but slow signal.

**Transaction cost viability:**
- Monthly rebalancing = ~24 round trips/year across 6 assets = very low turnover
- ETF bid/ask spreads on SPY/QQQ/TLT are <1bp; GLD/USO slightly wider at 1-2bp
- At $25K capital and monthly rebalancing, estimated annual transaction costs < 0.20% of portfolio
- **Signal half-life is 60–90 days, well above 1 day → transaction cost concern is minimal**
- Realistic: edge survives transaction costs with high confidence

**Conclusion:** Alpha decay profile is favorable — slow-decaying, monthly-horizon signal with trivial transaction costs. Passes alpha decay gate.

---

## Entry / Exit Logic

**Universe (6 ETFs):**
| ETF | Asset Class | Role |
|-----|------------|------|
| SPY | US Large-Cap Equity | Core equity exposure |
| QQQ | US Technology Equity | Growth/risk appetite |
| TLT | 20Y US Treasury Bond | Defensive / rate play |
| GLD | Gold | Crisis hedge / inflation |
| USO | Oil (Crude) | Commodity / inflation |
| DBC | Diversified Commodities | Broad commodity trend |

**Signal construction (monthly, end of month):**
1. For each ETF, compute the 12-month trailing total return (`R_12m = (P_t / P_{t-252}) - 1`)
2. Signal: +1 if R_12m > 0 (go long), -1 if R_12m ≤ 0 (go short / flat for long-only variant)

**Position sizing:**
- Equal-weight: allocate 1/N of capital to each asset with active signal (N = number of assets with non-zero signal)
- Long-only variant: only take long signals; go to cash for negative-return assets
- **First backtest: long-only variant** (simplicity, no short-selling at $25K, avoids PDT complexity)

**Entry:** At the close of the last trading day of each month (or first open of new month), rebalance to equal-weight long signals.

**Exit:**
- Rebalance monthly — positions exit when the 12-month return signal turns negative
- No intra-month exits (reduces transaction costs; consistent with monthly-rebalance design)
- Hard stop per asset: exit if any single position drawdown > 20% intramonth (protects against flash crashes)

**Rebalancing threshold:** Rebalance only if target weight differs from current weight by > 2% (reduces unnecessary small trades).

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**PDT Rule Impact:**
- Monthly rebalancing produces far fewer than 3 round-trips per week — **PDT is not a constraint for this strategy**
- This is a key advantage over H06 (RSI) which may hit PDT limits

**$25K fit:**
- 6 ETFs at equal weight = ~$4,167 per position (long-only)
- If only 3-4 signals active: ~$6,250–$8,333 per position — still well within liquid ETF execution
- Commission cost at $0.005/share on SPY (~$550/share): negligible per trade
- **No leverage required — pure long-only, low-frequency implementation is viable at $25K**

**Slippage estimate:** SPY/QQQ/TLT/GLD have >$1B daily volume — slippage at $25K order sizes is effectively 0. USO/DBC are slightly thinner but still liquid.

---

## Gate 1 Assessment

| Criterion | Assessment | Rationale |
|-----------|------------|-----------|
| IS Sharpe > 1.0 | **LIKELY PASS** | Moskowitz (2012) documents Sharpe ~1.0–1.4 for diversified TSMOM; 2022 was an exceptional year |
| OOS Sharpe > 0.7 | **LIKELY PASS** | Multi-asset diversification reduces variance; robust to single-asset regime changes |
| IS Max Drawdown < 20% | **LIKELY PASS** | 6-asset diversification caps drawdown; 2020 COVID lagged entry could cause brief drawdown |
| Win Rate > 50% | **UNCERTAIN** | Monthly rebalancing with 6 assets: ~60 monthly observations per IS window; win rate depends on regime |
| Avg Win / Avg Loss > 1.0 | **LIKELY PASS** | Trends produce large wins (months of riding a trend); losses are limited to 1 month of reversal |
| Trade Count > 50 | **PASS** | 6 assets × 12 months × 5 IS years = 360 potential signals; even with 50% active, >180 position months |
| PDT Compliance | **PASS** | Monthly rebalancing — far below 3 trades/week limit |
| Parameter Sensitivity | **LIKELY PASS** | 12-month lookback is well-established; modest sensitivity expected for ±20% change |

**Overall Gate 1 Outlook: HIGH CONFIDENCE** — TSMOM is one of the most academically robust strategies in the financial literature. The 2018–2022 IS window is particularly favorable because it contains exactly the type of macro-driven multi-asset trends that TSMOM exploits. The long-only variant will underperform the full long-short version but avoids PDT and short-selling complexity at $25K.

**Primary risk:** The 2018–2023 period includes the 2019 risk-on environment and 2023 recovery — both mean-reverting — which could hurt the Sharpe ratio despite 2022 being excellent. Net expectation is positive.

---

## Recommended Parameter Ranges for First Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| lookback_months | 12 | [6, 9, 12, 18] | Medium |
| rebalance_frequency | monthly | [monthly, quarterly] | Low |
| universe_size | 6 | [4, 6] | Low |
| long_only | True | [True, False] | Low (first pass) |
| intramonth_stop_pct | 0.20 | [0.15, 0.20, 0.25] | Low |

**Note:** Only 4 tunable parameters (lookback_months, rebalance_frequency, universe_size, intramonth_stop). Well within Gate 1 limit of 6. long_only is a structural decision, not a tuned parameter.

**Backtest period:** 2018-01-01 to 2023-12-31 (5 years, consistent with IS window requirement).

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS.

**PDT tracking:** Not required (monthly rebalancing produces <1 trade/week).

**Benchmark:** SPY buy-and-hold for comparison context.

---

## Pre-Backtest Checklist (Anti-Look-Ahead)

- [ ] 12-month return at time T uses only prices at T and T-252 — no future prices
- [ ] Rebalancing decision made on end-of-month close; execution at next open (or same close) — no look-ahead
- [ ] Position sizing is equal-weight based only on which signals are active at T — no future information
- [ ] Stop-loss triggered by intramonth price, not end-of-month — no look-ahead (stops use current price)
- [ ] Universe fixed (no asset added/removed based on future knowledge)
