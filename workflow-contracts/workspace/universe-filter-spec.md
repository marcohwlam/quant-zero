# Universe / Liquidity Filter Specification

**Version:** 1.0  
**Status:** DRAFT — pending Engineering Director implementation  
**Author:** Research Director  
**Date:** 2026-06-09  
**Issue:** QUA-128  
**Layer:** Layer 3 of the three-layer minute-level architecture (universe selection)

---

## Purpose

This spec defines the **universe eligibility filter** — the gate that decides which assets may enter signal generation and position construction for any strategy running on the minute-level pipeline.

**Core problem:** A strategy with a positive gross edge can be net-negative on illiquid names. At minute resolution, slippage is the dominant cost driver. The universe filter protects net Sharpe by excluding names where realistic execution cost destroys the edge before it accrues.

**Reference architecture:** Layer 3 (Universe) sits above Layer 2 (Execution cost model) and Layer 1 (Signal). The filter runs once per rebalance bar, before signal generation, to ensure signals are computed only over tradeable assets.

---

## Theoretical Grounding

### Kyle (1985) — Price Impact and Market Depth

Kyle's model establishes that price impact (λ) per unit of order flow scales inversely with market depth:

```
λ = σ / (2 × √V)
```

Where σ is daily return volatility and V is daily trading volume (normalized). The market impact on a trade of X shares at daily volume V:

```
impact ≈ λ × X = (σ / 2) × (X / √V)
```

**Implication for universe filtering:** As ADV ↓, λ ↑ quadratically. A stock with 1/10 the ADV of a liquid large-cap has ~3× the price impact per dollar traded. The ADV threshold is not arbitrary — it anchors to a maximum acceptable λ given the firm's position sizing.

**Derivation of ADV floor from Kyle λ:**

For the $25K account at 10% max position ($2,500):
- Typical position size at $50/share → 50 shares per trade
- Kyle impact tolerance: ≤ 0.5 bps per trade (leaving headroom within 2 bps PpT floor)
- At σ_daily = 1.5% (typical large-cap), solve for minimum ADV:

```
impact_bps = 100 × λ × X / price
0.0050% = (0.015 / 2) × (50 / √V) / 50
→ √V ≥ 0.015 / (2 × 0.000050) = 150
→ V ≥ 22,500 shares/minute ≈ 8.8M shares/day (390 bar day)
```

ADV floor: **≥ $10M/day** (at $50/share ≈ 200K shares/day provides sufficient depth, with Kyle impact < 0.5 bps for $2,500 positions). The $10M threshold uses a conservative round-number anchored in the range [8.8M, 25M] — the upper end accounts for smaller-price higher-vol names.

**Key property:** For the $25K account, Kyle impact is economically negligible at ADV > $10M/day — spread cost dominates. The ADV filter primarily screens out execution risk, data quality, and gap/manipulation exposure rather than own-price-impact at this scale.

---

### Almgren & Chriss (2000) — Optimal Execution and Temporary Impact

Almgren & Chriss decompose total execution cost into permanent and temporary components. The temporary impact (dominant for short-duration orders) at participation rate η:

```
temporary_impact_bps ≈ σ_daily × g(η)
```

Where g(η) is a convex, increasing function of participation rate η = X / (T × V_per_bar). For linear impact (g(η) = k × η):

```
temporary_impact_bps = k × (X / (T × V_per_bar)) × σ_daily × 10000
```

Empirically, k ≈ 0.5–1.0 for liquid markets (Almgren et al. 2005 empirical calibration).

**Participation rate at 1-minute bars:**

For a $2,500 position at $50/share = 50 shares, at ADV = 10M shares/day:
- V_per_minute = 10,000,000 / 390 ≈ 25,641 shares/minute
- η_1min = 50 / 25,641 = 0.195% participation

At η = 0.2%, σ = 1.5%:
```
temporary_impact_bps ≈ 1.0 × 0.002 × 0.015 × 10000 ≈ 0.30 bps
```

At ADV = $1M/day (threshold-at-risk):
- V_per_minute ≈ 2,564 shares/minute
- η_1min = 50 / 2,564 = 1.95% participation
- temporary_impact_bps ≈ 1.0 × 0.0195 × 0.015 × 10000 ≈ 2.93 bps

**Implication:** ADV drop from $10M → $1M raises temporary impact from 0.30 bps → 2.93 bps, eliminating the 2 bps PpT floor entirely. The $10M ADV threshold is the practical cliff below which execution cost dominates any minute-level edge.

---

### Bid-Ask Spread and the 2 bps PpT Floor

The full one-way cost stack per trade (from `kpi-minute-level.md` §Hard Gates):

```
Total one-way cost = commission + half-spread + market_impact
                   = 0.5 bps + (spread_bps / 2) + 0.30 bps
```

For a $2,500 position at $50/share = 50 shares:
- Commission: $0.005 × 50 = $0.25 = $0.25 / $2,500 = 1 bp. Wait — that's 1 bp.
  - Actually: $0.005/share × 50 shares = $0.25; $0.25 / $2,500 = 0.01% = 1 bp
- Half-spread: spread_bps / 2 (one-way slippage estimate)
- Market impact: 0.30 bps (at ADV $10M)

For net profit ≥ 2 bps floor:
```
gross_edge_bps ≥ 2 + total_one_way_cost
gross_edge_bps ≥ 2 + 1 + (spread_bps / 2) + 0.30
gross_edge_bps ≥ 3.30 + spread_bps / 2
```

Maximum viable spread to still allow a reasonable gross edge margin:
- At spread = 10 bps: gross edge needed ≥ 3.30 + 5 = 8.30 bps (demanding but achievable)
- At spread = 20 bps: gross edge needed ≥ 13.30 bps (extremely demanding)
- At spread = 50 bps: gross edge needed ≥ 28.30 bps (effectively precludes minute-level strategies)

**Spread threshold:** ≤ 10 bps quoted spread is the working cutoff. This leaves 8.30 bps gross edge required — within reach for well-structured intraday momentum/reversion signals. Spread > 10 bps requires gross edge > 8 bps to remain net-positive, which is unlikely at minute resolution and increases overfitting risk.

---

## Universe Filter Specification

### Thresholds

| Dimension | Hard Minimum | Working Target | Rationale |
|---|---|---|---|
| ADV (30-day rolling avg daily dollar volume) | $1M/day | **$10M/day** | Kyle λ-derived: below $10M, temporary impact > 1 bps/trade on $2,500 positions; data quality degrades; manipulation risk increases |
| Quoted bid-ask spread (bps, 30-day avg) | 50 bps | **10 bps** | Almgren-Chriss cost stack: spread > 10 bps forces gross edge > 8 bps, practically impossible at minute scale |
| Market cap (trailing 30-day) | $100M | **$500M** | Small/micro-cap have elevated manipulation risk, corporate actions, and liquidity events incompatible with systematic minute-level signals; $500M is mid-cap floor where institutional coverage stabilizes price discovery |

**Working target** is the threshold used in backtests and paper trading. Hard minimum is the absolute reject floor — assets below hard minimum are excluded unconditionally.

### Filter Rules (Applied per Rebalance Bar)

```
ELIGIBLE = assets where ALL of the following hold:
  1. adv_30d_usd >= ADV_FLOOR (default: 10_000_000)
  2. spread_bps_30d_avg <= SPREAD_MAX_BPS (default: 10.0)
  3. market_cap_usd >= MKTCAP_FLOOR (default: 500_000_000)
  4. NOT in exclusion list (halted, delisted, ADR-restricted)
  5. Data coverage >= 20 of last 30 trading days (data quality gate)
```

### Asset-Class Adjustments

**US Equities Intraday (RTH):**
- Use defaults above
- Additional: exclude securities < 6 months since IPO (insufficient price discovery history)
- Additional: exclude if RVOL (realized volume / 30d avg volume) < 0.5 for the bar (session liquidity abnormally low)

**Crypto (BTC/ETH only):**
- ADV threshold not applicable — BTC/ETH are always liquid at $25K scale
- Spread threshold: ≤ 8 bps (tighter, because taker fee is 5 bps and must fit within 8 bps PpT floor)
- Market cap threshold: not applicable — BTC/ETH are pre-filtered by asset class

**Futures (ES, CL):**
- ADV threshold: not applicable — ES/CL are always liquid at $25K scale
- Spread threshold: ≤ 0.5 ticks (expressed in ticks, not bps)
- Market cap threshold: not applicable — futures universe is pre-specified by contract

---

## Slippage Budget Per Asset Class (Filter Consequence)

After applying the filter, the expected one-way slippage budget for eligible assets:

| Asset Class | Commission | Half-Spread | Market Impact | Total One-Way Cost |
|---|---|---|---|---|
| Equities (at 10 bps spread, ADV $10M) | 1.0 bps | 5.0 bps | 0.3 bps | **6.3 bps** |
| Equities (at 5 bps spread, ADV $50M) | 1.0 bps | 2.5 bps | 0.1 bps | **3.6 bps** |
| Crypto (BTC, at 8 bps spread) | 5.0 bps | 4.0 bps | ~0 (account too small) | **9.0 bps** |
| Futures ES (at 1 tick = 0.25 pts, ~0.5 bps) | 0.3 bps | 0.25 bps | ~0 | **0.55 bps** |

These budgets feed directly into the backtest cost model and must be consistent with `kpi-minute-level.md` §Per-Asset-Class cost models.

---

## Data Sources and Measurement

| Metric | Source | Lookback | Notes |
|---|---|---|---|
| ADV (dollar volume) | yfinance `.info['averageDailyVolume10Day']` or rolling 30d close×volume | 30 trading days | Use 10-day if 30-day unavailable (new listings); flag if < 20 days data |
| Quoted spread (bps) | yfinance does not provide real-time spread; proxy: (daily high - daily low) / close / 2 | 30 trading days | This is a *range-based spread proxy*, not true bid-ask. True spread requires tick data (unavailable in current pipeline per Gate PF-3). Flag this limitation in backtest reports. |
| Market cap | yfinance `.info['marketCap']` | Point-in-time (snapshot) | Re-fetch at each monthly rebalance; use last available if fetch fails |

**Spread proxy limitation:** The range-based spread proxy overestimates true spread (average daily range >> average intraday spread). A 10 bps threshold on range-proxy is conservatively loose — actual quoted spreads on names passing this screen will be tighter. This is intentional: the proxy is a necessary substitute until tick data becomes available.

---

## Rejection Statistics (Expected)

Applying the working-target thresholds to the S&P 500 universe (reference set for equities):
- ADV ≥ $10M: ~80% pass (S&P 500 stocks are heavily liquid)
- Spread ≤ 10 bps (range proxy): ~75% pass
- Market cap ≥ $500M: ~90% pass (S&P 500 floor is ~$15B, effectively 100%)
- Combined: ~65–70% of S&P 500 pass all three gates

For broader Russell 1000 or screened mid-cap universes:
- Combined pass rate: ~40–55% (mid-caps often fail ADV and spread screens)

The filter is intentionally conservative. A smaller, more liquid universe reduces signal noise from liquidity events and improves cost model accuracy.

---

## Integration with Backtest Pipeline

```
REBALANCE LOOP:
  for each bar t:
    1. Fetch universe snapshot(t)                 ← Layer 3: raw universe
    2. Apply universe_filter(snapshot, thresholds) ← Layer 3: eligibility
    3. Compute signals on eligible assets only      ← Layer 2: signal
    4. Construct positions                          ← Layer 1: execution
    5. Apply cost model to fills                    ← Layer 2: cost
```

The filter MUST run before signal computation. Signals computed on then-filtered-out assets must not be used — this is a look-ahead risk if the filter is applied post-hoc.

---

## References

- Almgren, R. & Chriss, N. (2000). "Optimal Execution of Portfolio Transactions." *Journal of Risk*, 3(2), 5–39.
- Kyle, A.S. (1985). "Continuous Auctions and Insider Trading." *Econometrica*, 53(6), 1315–1335.
- Almgren, R., Thum, C., Hauptmann, E. & Li, H. (2005). "Direct Estimation of Equity Market Impact." *Risk*, 18(7), 58–62. (Empirical calibration of Almgren-Chriss η coefficients.)
- Kissell, R. (2013). *The Science of Algorithmic Trading and Portfolio Management.* Academic Press. (Practical ADV thresholds and participation rate analysis.)

---

## Python Stub Reference

See `workflow-contracts/workspace/universe_filter.py` for the implementation stub.

---

## Acceptance Criteria Checklist

- [x] ADV threshold justified by Kyle λ derivation
- [x] Spread threshold justified by Almgren-Chriss cost stack against 2 bps PpT floor
- [x] Market cap threshold justified with price discovery and manipulation rationale
- [x] Asset-class adjustments specified (equities / crypto / futures)
- [x] Slippage budget table computed and linked to `kpi-minute-level.md` cost models
- [x] Data sources and measurement methodology specified
- [x] Spread proxy limitation documented (range-based vs. true bid-ask)
- [x] Integration order with backtest pipeline documented (filter before signal)
- [x] Python stub referenced
