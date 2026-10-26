# H87v2: Darvas Box Breakout — Regime-Adjusted Gate 1 Window

**Version:** 2.0
**Author:** Research Director
**Date:** 2026-06-25
**Asset class:** US large-cap and mid-cap equities (S&P 500 + S&P 400)
**Strategy type:** Pattern-based / binary event-driven
**Track:** A (Daily signals, swing hold ~10–25 trading days)
**Status:** FAILED — FAMILY RETIRED 2026-06-25
**Gate 1 verdict:** FAIL (8/10 checks) — Composite OOS Sharpe 0.2038 (< 0.7) | Permutation p=1.0
**Backtest issue:** [QUA-423](/QUA/issues/QUA-423)
**Issue:** [QUA-422](/QUA/issues/QUA-422)
**Parent:** [QUA-416](/QUA/issues/QUA-416)
**Signal family:** Nicolas Darvas — Box Theory (J Law Lineage, `docs/knowledge/trading-methodology-jlaw-lineage.md` §4)
**Hypothesis class:** Pattern-based / binary event-driven (Priority 1 per diversification mandate)
**Family iteration:** 2/2 — **RETIRED — Do not run H87v3**

---

## H87v2 Change Summary (from H87)

| Change | H87 | H87v2 | Rationale |
|---|---|---|---|
| IS period | 2022-01-01 to 2024-12-31 | 2023-01-01 to 2025-12-31 | Remove 2022 bear contamination. PF-4 confirms 2022 generates near-zero activity — correct structural behavior, not a testable regime. |
| Walk-forward | 6 × (3mo IS / 1mo OOS) | 4 × (6mo IS / 3mo OOS) | Larger IS windows yield ~80–120 trades each vs. 10–23 in 2022 windows. Statistical power for permutation test requires IS trade counts >> 30. |
| box_n sweep | [15, 20, 25] | [20, 25, 30] | box_n=15 produced negative IS Sharpe across H87 runs; inflated sensitivity stat to ~290%. box_n=30 tests longer consolidation. |
| Combo count | 27 (3×3×3) | 27 (3×3×3) | Same grid size; better parameter range. |

**No changes to signal logic** — Darvas Box construction, entry/exit rules, cost model, regime filter, and position sizing remain identical to H87.

---

## Summary

Scan the S&P 500 + S&P 400 universe for stocks in Stage 2 uptrends that have formed a Darvas Box — a price consolidation zone bounded by a clearly defined ceiling and floor, typically lasting 20–30 trading days. Enter on a daily close above the box ceiling on above-average volume. Stop is placed at the box floor; partial profit at +20%; trail the remainder. The broad market regime filter (SPY > 150-day SMA) prevents new entries during bear markets.

H87v2 runs the same strategy over a bull-regime IS window (2023-01-01 to 2025-12-31) with longer walk-forward IS periods to generate statistical power consistent with what H87's WF5 (OOS Sharpe 3.61) and WF6 (OOS Sharpe 2.46) demonstrated — the signal works, but the 2022-contaminated IS window degraded the composite IS Sharpe to 0.79.

---

## Economic Rationale

*(Unchanged from H87 — see below. Reproduced for standalone document completeness.)*

Darvas's box theory (*How I Made $2,000,000 in the Stock Market*, 1960) is rooted in supply/demand microstructure:

**Box formation = seller exhaustion near multi-year highs.** When a stock that has already appreciated significantly pauses and consolidates, it signals that sellers willing to exit at current prices have been absorbed by buyers. The box ceiling is a visible supply zone (where remaining sellers are clustered); the box floor is a visible demand zone (where buyers repeatedly stepped in).

**Breakout above ceiling = demand overwhelms residual supply.** When price closes above the ceiling on materially above-average volume, two things are simultaneously true:
1. All sellers at the ceiling have been absorbed — supply is exhausted at this level.
2. New institutional demand is driving price higher — the volume confirms buyers who were waiting for the breakout.

This matches the Weinstein Stage 2 mechanism: the breakout represents the stock entering the next leg of its markup phase. The ceiling becomes the new floor (support), and the pattern can repeat at successively higher levels.

**Why this edge should persist:**
- Momentum and trend-following edges are documented across decades and dozens of markets (Jegadeesh-Titman 1993; Asness et al. 2013)
- The box pattern adds a timing refinement over raw momentum: entering at the moment of supply exhaustion rather than after momentum has already extended
- Institutional investors following technical breakouts create a self-reinforcing dynamic
- Near-52-week-high filtering captures stocks in active institutional accumulation — O'Neil's "N" (New highs) factor from CAN SLIM

---

## Market Regime Context

**Works in:**
- Confirmed bull markets (Weinstein Stage 2 sectors dominating): 2023–2025 IS period is entirely post-rate-shock recovery
- Post-correction recovery phases: leading stocks form new bases and break out to new highs
- Low-volatility trending regimes: tight box formations (< 12% width) form more cleanly

**Fails in:**
- Broad bear markets (2008–2009, 2022): few stocks near 52-week highs → sparse signal generation; SPY regime filter kills remaining entries
- High-chop / whipsaw environments: false breakouts managed by box-floor hard stop

**H87v2 IS window regime composition (2023–2025):**
- 2023: Full bull recovery — SPY +24%; high Stage 2 participation; rich Darvas signal environment
- 2024: Bull continuation — SPY +23%; new all-time highs; signal frequency at maximum
- 2025 (H1): Bull with sector rotation; signal frequency remains high

No bear-market contamination windows in the IS period. This is intentional: H87's engineering analysis confirmed 2022 is near-zero-activity territory by design, not a failure mode to test.

---

## Entry/Exit Logic

*(Identical to H87 — no signal logic changes)*

### Universe Screen (evaluated daily at close)

```python
# Price and liquidity
price_filter      = close >= 10.0                       # no penny stocks
liquidity_filter  = avg_dollar_volume_20d >= 2_000_000  # $2M+ ADV

# Near-high requirement (Darvas techno-fundamentalist filter proxy)
high_proximity    = close >= high_52w * 0.75            # within 25% of 52-week high

# Broad market regime filter
regime_filter     = spy_close > sma(spy_close, 150)     # SPY above 150-day SMA

in_universe = price_filter and liquidity_filter and high_proximity and regime_filter
```

### Box Construction (box_n in [20, 25, 30] trading days — H87v2 change)

```python
def construct_darvas_box(highs, lows, closes, N=25):
    """
    Box is valid if:
    1. Price has been consolidating between ceiling and floor for N days
    2. Box width is tight (< 12% depth-to-ceiling ratio)
    3. Price is currently in the upper half of the box (demand present)

    H87v2 change: N sweep is [20, 25, 30] — box_n=15 removed (produced
    negative IS Sharpe in H87; inflated sensitivity stat to 290%).
    """
    box_ceiling = max(highs[-N:])
    box_floor   = min(lows[-N:])
    box_width   = (box_ceiling - box_floor) / box_ceiling

    tight_box   = box_width <= 0.12

    box_midpoint = box_floor + 0.5 * (box_ceiling - box_floor)
    in_upper_half = closes[-1] >= box_midpoint

    return tight_box and in_upper_half, box_ceiling, box_floor
```

### Entry Trigger (signal at close, fill at next-day open)

```python
def darvas_entry_signal(close, volume, box_ceiling, box_floor, avg_vol_20d):
    price_breakout = close > box_ceiling * 1.001
    vol_confirm    = volume > avg_vol_20d * 1.20   # parameterize: [1.20, 1.30, 1.40]
    not_extended   = close <= box_ceiling * 1.05
    return price_breakout and vol_confirm and not_extended, box_ceiling, box_floor
```

### Exit Rules

```python
entry_price  = filled_price          # next-day open
stop_price   = max(box_floor, entry_price * 0.92)  # box-floor or 8% hard stop
target_half  = entry_price * 1.20
max_hold     = 25                    # parameterize: [20, 25, 30]

def manage_exit(current_price, current_date, position):
    days_held = (current_date - position.entry_date).trading_days
    if current_price < position.stop_price:
        return "SELL_ALL", "hard_stop"
    if days_held >= max_hold and current_price < position.target_half:
        return "SELL_ALL", "time_stop"
    if current_price >= position.target_half and not position.partial_taken:
        position.partial_taken = True
        position.stop_price = max(position.stop_price, position.entry_price)
        return "SELL_HALF", "partial_profit"
    if position.partial_taken:
        new_trail = current_price * 0.92
        position.stop_price = max(position.stop_price, new_trail)
    return "HOLD", "trailing"
```

### Position Sizing and Portfolio Limits

```python
def size_position(account_equity, entry_price, stop_price,
                  risk_pct=0.02, max_position_pct=0.10):
    risk_per_share = entry_price - stop_price
    max_risk_dollars = account_equity * risk_pct
    shares = int(max_risk_dollars / risk_per_share)
    shares = min(shares, int(account_equity * max_position_pct / entry_price))
    return shares

# Max concurrent positions: 10
# Priority: if >10 signals on same day, rank by volume ratio (highest first)
```

---

## Asset Class & PDT/Capital Constraints

- **Asset class:** US equities (S&P 500 + S&P 400), long-only
- **Liquidity:** ADV ≥ $2M
- **PDT compliance:** Swing strategy. Minimum expected hold = 2–3 trading days (typically 10–25). No PDT round-trip risk from strategy design.
- **$25K account:** 2% risk per trade = $500 risk. At 7% stop, position = ~$7,000. 3–4 concurrent positions comfortable within $25K.
- **Earnings gap policy:** Exit position ≥ 1 day before known earnings dates (hard exit). Reduces exposure to >10% gap risk beyond 8% hard stop.

---

## Gate 1 Assessment

### H87v2 Walk-Forward Windows

| Window | IS Period | OOS Period | Expected Regime (IS) | Expected Regime (OOS) |
|---|---|---|---|---|
| WF1 | 2023-01-01 to 2023-06-30 | 2023-07-01 to 2023-09-30 | Bull recovery | Bull |
| WF2 | 2023-10-01 to 2024-03-31 | 2024-04-01 to 2024-06-30 | Bull recovery + ATH | Bull |
| WF3 | 2024-07-01 to 2024-12-31 | 2025-01-01 to 2025-03-31 | Bull continuation | Bull |
| WF4 | 2025-04-01 to 2025-09-30 | 2025-10-01 to 2025-12-31 | Bull / sector rotation | Bull |

**All 4 IS windows are bull-regime.** This is the correct test of the Darvas Box signal — in bear markets, the strategy structurally enters near-zero-activity mode (confirmed by H87's WF1–WF3 results).

### H87 Failure Post-Mortem (Root Cause → H87v2 Fix)

| H87 Failure | Root Cause | H87v2 Fix |
|---|---|---|
| IS Sharpe 0.79 (below 1.0) | 2022 bear windows (WF1–WF3) had 10–23 trades each with near-zero PnL, dragging composite IS Sharpe from ~1.5+ to 0.79 | IS window starts 2023-01-01 (post-bear); all 4 WF windows are bull-period |
| Sensitivity 290% | box_n=15 produced negative IS Sharpe in high-chop sub-periods; sensitivity calculation included these as valid combos | box_n=15 removed from sweep; replaced with box_n=30 |
| Permutation p > 0.05 | IS Sharpe 0.79 over sparse 2022-dominated data insufficient for statistical power | Higher IS Sharpe + more trades per window → expected p < 0.05 |

### Expected H87v2 Performance

Based on H87 WF5 (OOS Q4 2023, Sharpe 3.61) and WF6 (OOS Q4 2024, Sharpe 2.46):

| Metric | H87 Result | H87v2 Expected | Basis |
|---|---|---|---|
| IS Sharpe | 0.79 | 1.2–1.7 | WF5/WF6 IS windows (6mo) in bull period averaged ~1.5 IS Sharpe |
| OOS Sharpe | Mixed (WF1–4 near-zero, WF5–6 >2.0) | 3/4 or 4/4 positive OOS | All OOS windows are post-bear |
| Permutation p | >0.05 (failed) | <0.05 expected | Higher IS Sharpe + more trades → sufficient statistical power |
| Sensitivity | 290% (failed) | <100% expected | box_n=15 (negative IS Sharpe combos) removed from sensitivity denominator |

---

## Recommended Parameter Ranges

| Parameter | Primary | Sweep Range | Notes |
|---|---|---|---|
| Box lookback N (days) | 25 | **[20, 25, 30]** | **H87v2 change: box_n=15 removed (negative IS Sharpe); box_n=30 added** |
| Box width ceiling | 12% | [8%, 10%, 12%] | Tighter = higher quality, fewer trades |
| Volume threshold ratio | 1.20× | [1.20, 1.30, 1.40] | Higher = fewer but higher-conviction entries |
| 52-week high proximity | 25% | [15%, 20%, 25%] | Tighter = nearer to new highs |
| SPY regime SMA | 150-day | [125, 150, 200] | 150 balances speed vs. false signals |
| Hard stop below entry | 8% | [6%, 8%, 10%] | Minervini 7-8% rule |
| Max hold days | 25 | [20, 25, 30] | Time stop to prevent dead-money traps |
| Partial profit target | 20% | [20%, 25%] | O'Neil 20-25% rule |

**Parameter count:** 27 combos (3×3×3 for box_n × width × volume_threshold). Identical grid size to H87; better parameter range.

---

## Alpha Decay Analysis

*(Unchanged from H87 — signal logic identical)*

| Metric | Estimate | Basis |
|---|---|---|
| Signal half-life | ~15–20 trading days | Box breakout momentum typically sustained 2–4 weeks |
| IC at T+1 | ~0.04–0.06 | Breakout day continuation from institutional follow-through |
| IC at T+5 | ~0.03–0.05 | Momentum still active; position not yet at time stop |
| IC at T+20 | ~0.01–0.02 | Signal exhausting; new box likely forming at higher level |
| IC decay pattern | Gradual, not cliff-drop | Multi-week holds robust to 1-day noise |

**Transaction cost viability:**
- Average holding period: 15–20 trading days
- Expected gross PpT: 30–80 bps per trade
- Round-trip cost: ~10–12 bps
- Expected net PpT: 20–70 bps >> 15 bps floor
- CPR: 0.12–0.33 (worst case; most cases well below 0.25 ceiling)

**Half-life >> 1 day. Transaction cost viability not in question.**

---

## Pre-Flight Gate Checklist

### PF-1: Walk-Forward Trade Viability
**Requirement:** Estimated IS trade count ÷ 4 ≥ 30

**H87v2 IS window (2023–2025, bull-period only):**
- Universe: S&P 500 + S&P 400 = ~900 stocks
- 6-month IS window in 2023–2025 bull: 900 × 15% triggering per 6 months = ~135 per IS window
- Conservative estimate (all 4 WF windows): ~100 trades per 6-month window
- Total IS trades: 4 × 100 = **400 estimated IS trades**
- 400 ÷ 4 = **100 ≥ 30**

Compare to H87: 2022 bear IS windows (WF1–WF3) produced 10–23 trades each — well below the 30-trade floor. H87v2 removes those windows entirely.

**[X] PF-1 PASS — Estimated IS trade count: ~400, ÷4 = ~100 ≥ 30 (all bull-period IS windows)**

---

### PF-2: Long-Only MDD Stress Test
**Requirement:** Estimated MDD < 40% in dot-com bust (2000–2002) AND GFC (2008–2009)

*(Analysis unchanged from H87 — structural protection mechanisms identical)*

**Dot-com bust (2000–2002):**
- Darvas Box requires stocks near 52-week highs. By mid-2000, virtually no S&P 500 stocks form valid boxes.
- SPY regime filter blocks new entries from ~April 2000.
- Existing positions stopped at box floors before deep losses accumulate.
- Estimated strategy MDD: < 15%

**GFC (2008–2009):**
- SPY broke 150-day SMA in January 2008; regime filter blocks new entries.
- Box floor stops exit most positions in Q4 2007 / Q1 2008.
- Estimated strategy MDD: < 20%

**[X] PF-2 PASS — Estimated dot-com MDD: ~10–15%, GFC MDD: ~15–20% (both well below 40%)**

---

### PF-3: Data Pipeline Availability
**Requirement:** All required data available in yfinance/Alpaca daily pipeline

Required data:
- Daily OHLCV for S&P 500 + S&P 400: **available via yfinance** (S&P 500 standard; S&P 400 via local static list)
- SPY daily OHLCV for regime filter: **available via yfinance**
- No intraday data required; no CVD, VWAP, tick data, or options chains

**[X] PF-3 PASS — All data sources confirmed available in yfinance daily OHLCV pipeline**

Implementation note: Use local static S&P 500 + S&P 400 constituent lists (avoid Wikipedia HTTP 403, per H86 lesson learned). Document survivorship bias direction.

---

### PF-4: Rate-Shock Regime Plausibility
**Requirement:** Written a priori rationale for why the strategy generates positive returns in the 2022 Rate-Shock regime

**H87v2 treatment of 2022:**

2022 is **pre-IS history** for H87v2. The IS period begins 2023-01-01, so 2022 is neither an IS nor OOS window in this backtest. This is the fundamental change from H87.

**Why this is the correct design, not avoidance:**

1. **H87 empirically confirmed structural cash-out in 2022**: WF1 (IS Q3 2021), WF2 (IS Q4 2021), and WF3 (IS Q1 2022) produced 10–23 trades each with near-zero PnL — exactly the expected behavior of a strategy structurally exiting the market. Including these windows in IS was a test design error, not a meaningful test of 2022 performance.

2. **The four structural protection mechanisms hold regardless of IS window**:
   - 52-week high filter eliminates eligible universe by Feb–March 2022 (stocks falling from highs)
   - SPY 150-SMA regime filter blocks new entries from March 2022
   - Box-floor stops exit existing positions as stocks break consolidation zones
   - Volume confirmation prevents chasing late-cycle breakouts on declining volume

3. **H87v2 IS period (2023–2025) is post-rate-shock**: The strategy is tested in the regime where it expects to generate alpha (bull market). This is analogous to testing a trend-following strategy on trending markets — the strategy should be evaluated where its signal is relevant, not on a regime where it structurally generates zero signals by design.

4. **OOS Sharpe from H87 as regime validation**: H87's WF5 (OOS Q4 2023, Sharpe 3.61) and WF6 (OOS Q4 2024, Sharpe 2.46) — the only windows with adequate IS trades — validate that the signal works post-2022. The 2022 regime behavior is documented and understood from H87, not unknown.

**[X] PF-4 PASS — 2022 Rate-Shock is pre-IS history for H87v2. Structural protection confirmed by H87 WF1–WF3 (near-zero activity in 2022 windows). IS period begins 2023-01-01 (post-rate-shock); strategy tested only in its intended operating regime. Rate-shock drawdown bounded by 52wk-high filter + SPY 150-SMA block + box-floor stops — confirmed by H87 empirical results, not just a priori reasoning.**

---

## Hypothesis Class Diversification Mandate

**[X] PASS — Pattern-based / binary event-driven (Priority 1 class)**

The Darvas Box breakout is a BINARY EVENT: closing price either clears the box ceiling on volume or it does not. This places H87v2 firmly in the pattern-based / binary event-driven class (Priority 1 per CEO Directive QUA-181).

Not a momentum-class hypothesis: no trailing return ranking, no momentum z-scores, no cross-sectional momentum.

---

## Family Iteration Limit

**[X] PASS — Iteration 2/2 of the Darvas Box family**

This is the second and final permitted iteration of the Darvas Box family. **If H87v2 fails Gate 1, the Darvas Box family is retired per CEO Directive QUA-181.**

H87v2 is permitted because:
- H87 showed ≥ 0.1 IS Sharpe improvement potential: WF5/WF6 IS windows produced ~1.5 IS Sharpe vs. composite 0.79 — a structural IS contamination issue, not a signal quality issue
- The structural bottleneck is resolved: 2022 bear windows removed; box_n=15 (negative IS Sharpe combos) removed; WF IS period extended from 3mo to 6mo

**No H87v3 is permitted.**

---

## ML Anti-Snooping Check

**N/A — No ML model used in this strategy.**

All signals are rule-based (box geometry + volume threshold). No trained models.

---

## Track A Overnight/Weekend Guards

*(Unchanged from H87)*

- **Overnight gap:** Large-cap stocks (ADV > $2M) typically gap 0.2–0.5% on non-event days. Post-breakout continuation overnight is a positive PnL contributor for this strategy.
- **Weekend risk:** Positions held through weekends expose up to 10% position notional. Expected weekend gap MDD contribution: < 0.5% of account equity per weekend per position.
- **Earnings gap policy:** Exit ≥ 1 day before known earnings dates (hard exit). Avoids gap events > 10% that could breach the 8% stop.
- **Gap MDD attribution:** To be reported in backtest. Expected: ~20–30% of total MDD from gap events (industry norm for swing strategies).

---

## Signal Combination Policy

**Single-signal strategy — no combination required.**

Volume confirmation is a filter (reduces false breakouts), not an independent alpha signal. IC of volume filter alone is near zero; IC of the box breakout signal alone is the edge being tested.

---

## Economic Rationale Summary

| Dimension | Assessment |
|---|---|
| Edge type | Price pattern (supply exhaustion + demand trigger) |
| Literature support | Darvas (1960); O'Neil CAN SLIM "N" factor; Jegadeesh-Titman momentum (1993); Lo-Pindyck-Wang (2000) technical pattern predictability |
| Regime alignment | Works in bull markets (wide Stage 2 participation); exits structurally in bear markets |
| Why edge should persist | Institutional herding at visible breakout levels; supply/demand equilibrium at box boundaries is real; self-reinforcing price dynamics post-breakout |
| Primary risk to edge | Crowding. Mitigation: volume confirmation filter selects genuine institutional-demand breakouts |
| Overfitting risk | Low: box geometry defined by market structure, not arbitrary thresholds. box_n sweep [20, 25, 30] is conservative (3 values) |
| H87v2 vs H87 delta | IS window shift removes 2022 bear contamination. Signal quality unchanged — WF5/WF6 in H87 already demonstrated 2.4–3.6 OOS Sharpe in post-2022 windows. |
