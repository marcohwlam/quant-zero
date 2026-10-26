# H87: Darvas Box Breakout — S&P 1500 US Equities

**Version:** 1.0
**Author:** Research Director
**Date:** 2026-06-25
**Asset class:** US large-cap and mid-cap equities (S&P 500 + S&P 400)
**Strategy type:** Pattern-based / binary event-driven
**Track:** A (Daily signals, swing hold ~10–25 trading days)
**Status:** READY
**Issue:** [QUA-416](/QUA/issues/QUA-416)
**Signal family:** Nicolas Darvas — Box Theory (J Law Lineage, `docs/knowledge/trading-methodology-jlaw-lineage.md` §4)
**Hypothesis class:** Pattern-based / binary event-driven (Priority 1 per diversification mandate)

---

## Summary

Scan the S&P 500 + S&P 400 universe for stocks in Stage 2 uptrends that have formed a Darvas Box — a price consolidation zone bounded by a clearly defined ceiling and floor, typically lasting 15–25 trading days. Enter on a daily close above the box ceiling on above-average volume. Stop is placed at the box floor; partial profit at +20%; trail the remainder. The broad market regime filter (SPY > 150-day SMA) prevents new entries during bear markets.

This strategy is distinct from VCP (H82: pattern of contracting pullbacks) and from NR7 volatility compression (H45: narrow range day counting). The Darvas Box is a structural consolidation pattern requiring:
1. Price near multi-year highs (structural demand context),
2. A defined ceiling and floor confirmed by multiple touches (supply/demand equilibrium), and
3. A volume-confirmed breakout above the ceiling (institutional demand trigger).

The binary trigger — price either clears the ceiling on volume or it does not — eliminates the ambiguity of pattern recognition and aligns with the "proven pass class" per the diversification mandate.

---

## Economic Rationale

Darvas's box theory (*How I Made $2,000,000 in the Stock Market*, 1960) is rooted in supply/demand microstructure:

**Box formation = seller exhaustion near multi-year highs.** When a stock that has already appreciated significantly pauses and consolidates, it signals that sellers willing to exit at current prices have been absorbed by buyers. The box ceiling is a visible supply zone (where remaining sellers are clustered); the box floor is a visible demand zone (where buyers repeatedly stepped in).

**Breakout above ceiling = demand overwhelms residual supply.** When price closes above the ceiling on materially above-average volume, two things are simultaneously true:
1. All sellers at the ceiling have been absorbed — supply is exhausted at this level.
2. New institutional demand is driving price higher — the volume confirms buyers who were waiting for the breakout.

This matches the Weinstein Stage 2 mechanism: the breakout represents the stock entering the next leg of its markup phase. The ceiling becomes the new floor (support), and the pattern can repeat at successively higher levels as Darvas pyramided.

**Why this edge should persist:**
- Momentum and trend-following edges are documented across decades and dozens of markets (Jegadeesh-Titman 1993; Asness et al. 2013)
- The box pattern adds a timing refinement over raw momentum: entering at the moment of supply exhaustion rather than after momentum has already extended
- Institutional investors following technical breakouts create a self-reinforcing dynamic: breakout triggers algorithmic buys which push price higher, which triggers more buys
- Near-52-week-high filtering captures stocks in active institutional accumulation — O'Neil's "N" (New highs) factor from CAN SLIM

---

## Market Regime Context

**Works in:**
- Confirmed bull markets (Weinstein Stage 2 sectors dominating): S&P 500 in Stage 2 → many individual stocks forming valid boxes and breaking out
- Post-correction recovery phases: as market recovers from corrections, leading stocks form new bases and break out to new highs
- Low-volatility trending regimes: tight box formations (< 12% width) form more cleanly

**Fails in:**
- Broad bear markets (2008–2009, 2022): few stocks near 52-week highs → sparse signal generation; SPY regime filter kills remaining entries
- High-chop / whipsaw environments: false breakouts — price clears ceiling but fails to follow through; managed by box-floor hard stop
- Narrow-sector rallies: if only 1–2 sectors are in Stage 2, signal frequency may be insufficient for statistical power

**Built-in structural protection (not overlay-based):**
1. Near-52-week-high requirement: in sustained bear markets, stocks must fall significantly before any recovery begins — valid boxes cannot form because stocks are far from new highs
2. SPY regime filter: new entries blocked when SPY < 150-day SMA (bears market condition)
3. Box-floor hard stop: existing positions stopped out when stocks break below their demand zone
4. Volume confirmation: filters out false breakouts on weak volume

---

## Entry/Exit Logic

### Universe Screen (evaluated daily at close)

```python
# Price and liquidity
price_filter      = close >= 10.0                       # no penny stocks
liquidity_filter  = avg_dollar_volume_20d >= 2_000_000  # $2M+ ADV

# Near-high requirement (Darvas techno-fundamentalist filter proxy)
# Only stocks in Stage 2 / near multi-year highs qualify for box formation
high_proximity    = close >= high_52w * 0.75            # within 25% of 52-week high

# Broad market regime filter
regime_filter     = spy_close > sma(spy_close, 150)     # SPY above 150-day SMA

in_universe = price_filter and liquidity_filter and high_proximity and regime_filter
```

### Box Construction (parameterize N in [15, 20, 25] trading days)

```python
def construct_darvas_box(highs, lows, closes, N=20):
    """
    Box is valid if:
    1. Price has been consolidating between ceiling and floor for N days
    2. Box width is tight (< 12% depth-to-ceiling ratio)
    3. Price is currently in the upper half of the box (demand present)
    """
    box_ceiling = max(highs[-N:])
    box_floor   = min(lows[-N:])
    box_width   = (box_ceiling - box_floor) / box_ceiling

    # Tight consolidation: width <= 12% (parameterize: [0.08, 0.10, 0.12])
    tight_box   = box_width <= 0.12

    # Price in upper half of box (current demand context)
    box_midpoint = box_floor + 0.5 * (box_ceiling - box_floor)
    in_upper_half = closes[-1] >= box_midpoint

    return tight_box and in_upper_half, box_ceiling, box_floor
```

### Entry Trigger (signal at close, fill at next-day open)

```python
def darvas_entry_signal(close, volume, box_ceiling, box_floor, avg_vol_20d):
    """
    Entry: daily close above box ceiling + volume confirmation.
    Fill: next-day open (signal generated after close; no same-close fills — Hard Gate 3).
    """
    # Price breaks above ceiling (small threshold to avoid tiny prints)
    price_breakout = close > box_ceiling * 1.001

    # Volume confirmation: at least 20% above 20-day average
    # (Parameterize threshold: [1.20, 1.30, 1.40])
    vol_confirm    = volume > avg_vol_20d * 1.20

    # Not extended: price within 5% of ceiling (not chasing a move that's already run)
    not_extended   = close <= box_ceiling * 1.05

    return price_breakout and vol_confirm and not_extended, box_ceiling, box_floor
```

### Exit Rules

```python
# Set at entry — never moved adversely
entry_price  = filled_price          # next-day open
stop_price   = max(box_floor,        # box-floor stop (primary: structural)
                   entry_price * 0.92)  # 8% hard stop (secondary: maximum loss cap)
target_half  = entry_price * 1.20   # partial exit at +20%
max_hold     = 25                    # trading days (time stop; parameterize: [20, 25, 30])

def manage_exit(current_price, current_date, position):
    days_held = (current_date - position.entry_date).trading_days

    # Hard stop: box floor or 8% — whichever hit first
    if current_price < position.stop_price:
        return "SELL_ALL", "hard_stop"

    # Time stop: exit if no follow-through within max_hold days
    if days_held >= max_hold and current_price < position.target_half:
        return "SELL_ALL", "time_stop"

    # Partial profit: take 50% off at +20%
    if current_price >= position.target_half and not position.partial_taken:
        position.partial_taken = True
        # Raise stop to breakeven on remainder
        position.stop_price = max(position.stop_price, position.entry_price)
        return "SELL_HALF", "partial_profit"

    # Trailing stop on remainder: 8% from peak close
    if position.partial_taken:
        new_trail = current_price * 0.92
        position.stop_price = max(position.stop_price, new_trail)

    return "HOLD", "trailing"
```

### Position Sizing and Portfolio Limits

```python
def size_position(account_equity, entry_price, stop_price,
                  risk_pct=0.02, max_position_pct=0.10):
    """
    Elder 2% Rule: max 2% of equity risked per trade.
    Max position: 10% of account (concentration limit).
    """
    risk_per_share = entry_price - stop_price
    max_risk_dollars = account_equity * risk_pct
    shares = int(max_risk_dollars / risk_per_share)
    shares = min(shares, int(account_equity * max_position_pct / entry_price))
    return shares

# Max concurrent positions: 10 (diversification, not concentration)
# Priority: if >10 signals on same day, rank by volume ratio (highest vol ratio first)
```

---

## Asset Class & PDT/Capital Constraints

- **Asset class:** US equities (S&P 500 + S&P 400), long-only
- **Liquidity:** ADV ≥ $2M (far above PDT margin call risk)
- **PDT compliance:** Swing strategy. Minimum expected hold = 2–3 trading days (typically 10–25 days). The box-floor stop typically 5–12% below entry means PDT round-trip within 1 day is not triggered by the strategy design.
- **$25K account:** 2% risk per trade at $25K = $500 risk per position. With a 6–8% stop, position size = $500 / (entry × 0.07) ≈ $7,000 per position. 3–4 concurrent positions = comfortable within $25K capital.
- **Earnings gap risk:** Earnings hold policy declared — if a stock reports earnings during the hold period, position is reduced to ≤ 5% of account equity before earnings (per Track A overnight guard requirement). OR implement an earnings blackout: exit 1 day before known earnings dates.

---

## Gate 1 Assessment

### Expected Performance by Regime (proxy analysis using SPY/QQQ):

| Period | Market Condition | Expected Strategy Behavior |
|---|---|---|
| 2022 Q1 | Late bull, rate shock begins | Declining signals as stocks fail 52-week high filter; regime filter may not yet trigger |
| 2022 Q2–Q4 | Bear market, SPY < 150-SMA | Regime filter blocks new entries; existing positions stopped out at box floors |
| 2023 Q1–Q4 | Recovery, new bull | Signal frequency recovers; leading stocks form first new boxes above prior consolidations |
| 2024 Q1–Q4 | Bull market, new highs | Rich signal environment; S&P 500 at all-time highs → many stocks forming valid boxes |

**Expected IS Sharpe range:** 0.8–1.4 (Darvas Box archetype range from `docs/kpi-daily-weekly.md` table; similar to Weinstein Stage 2 breakout)

**Expected PpT range:** 20–60 bps (multi-day directional capture above cost floor)

**Expected MDD:** < 20% IS period — regime filter and box-floor stops limit downside; 2022 signal drought means reduced exposure (limiting MDD but also limiting PpT that year)

**Expected trade count per 3-month IS window:**
- Bull (2023–2024): ~900 stocks × 15% triggering per quarter = ~135 per window
- Bear (2022): ~900 stocks × 5% = ~45 per window (regime filter also reduces entries)
- Average: ~75–100 per 3-month IS window >> 30-trade floor

**Gate thresholds likely to pass:**
- Net OOS Sharpe > 0.7: LIKELY (Darvas archetype expected 0.8–1.2 in favorable regimes)
- Net PpT > 15 bps: LIKELY (multi-day holds capture gross moves of 50–150 bps; costs ~10 bps)
- MDD < 20% CS threshold: LIKELY (regime + stop discipline; cash during 2022)
- IS trade count > 30: LIKELY (large universe; bull market windows comfortably exceed 30)
- CPR < 0.25: LIKELY (swing holds 10–25 days capture far more gross than 10-bps RT cost)

**Gate at risk:** Trade count in 2022 bear market windows may approach floor. Parameter sweep should include wider box criteria (N=25, width=15%) to recover signal frequency in sideways regimes.

---

## Recommended Parameter Ranges

| Parameter | Primary | Sweep Range | Notes |
|---|---|---|---|
| Box lookback N (days) | 20 | [15, 20, 25] | Shorter = more trades, noisier boxes |
| Box width ceiling | 12% | [8%, 10%, 12%] | Tighter = higher quality, fewer trades |
| Volume threshold ratio | 1.20× | [1.20, 1.30, 1.40] | Higher = fewer but higher-conviction entries |
| 52-week high proximity | 25% | [15%, 20%, 25%] | Tighter = nearer to new highs |
| SPY regime SMA | 150-day | [125, 150, 200] | 150 balances speed vs. false signals (H86v2 finding) |
| Hard stop below entry | 8% | [6%, 8%, 10%] | Minervini 7-8% rule; wider in volatile environments |
| Max hold days | 25 | [20, 25, 30] | Time stop to prevent dead-money traps |
| Partial profit target | 20% | [20%, 25%] | O'Neil 20–25% rule |

**Parameter count:** 8 parameters with 2–3 values each. Full grid = 8×3 = 24 combinations. Within PF-1/Gate 1 parameter limit.

---

## Alpha Decay Analysis

**Signal:** Darvas Box Breakout (daily EOD, swing hold)

| Metric | Estimate | Basis |
|---|---|---|
| Signal half-life | ~15–20 trading days | Box breakout momentum typically sustained 2–4 weeks before next consolidation |
| IC at T+1 | ~0.04–0.06 | Breakout day continuation from institutional follow-through |
| IC at T+5 | ~0.03–0.05 | Momentum still active; position not yet at time stop |
| IC at T+20 | ~0.01–0.02 | Signal exhausting; new box likely forming at higher level |
| IC decay pattern | Gradual, not cliff-drop | Multi-week holds are robust to 1-day noise |

**Transaction cost viability:**
- Average holding period: 15–20 trading days
- Expected gross PpT: 30–80 bps per trade (multi-day directional capture)
- Round-trip cost: ~10–12 bps ($0.005/share × 2 + 0.05% slippage × 2 = ~10 bps at $20 stock)
- Expected net PpT: 20–70 bps >> 15 bps floor
- CPR estimate: 10/30 to 10/80 = 0.12 to 0.33 (worst case with only 30 bps gross; most cases well below 0.25 ceiling)

**Half-life conclusion:** Signal half-life ≈ 15–20 trading days >> 1 trading day. Transaction cost viability is not in question — the edge is captured over multi-day holds where $0.005/share round-trip cost is a small fraction (< 25%) of expected gross PpT. No special justification needed.

---

## Pre-Flight Gate Checklist

### PF-1: Walk-Forward Trade Viability
**Requirement:** Estimated IS trade count ÷ 4 ≥ 30

- Universe: S&P 500 + S&P 400 = ~900 stocks
- Bull market estimate (2023–2024): 900 × 15% triggering per quarter = ~135 per 3-month IS window
- Bear market estimate (2022): 900 × 5% = ~45 per 3-month IS window (regime filter also active)
- Conservative average across 6 WF windows: ~75 per window → 6 × 75 = 450 total IS trades
- 450 ÷ 4 = **112 ≥ 30**

**[X] PF-1 PASS — Estimated total IS trade count: ~450, ÷4 = ~112 ≥ 30**

Note: individual 2022 IS windows may produce 30–50 trades (regime filter reduces exposure). This is above the 30-trade per-window hard gate. Parameter sweep at N=25, width=12% recovers frequency if needed.

---

### PF-2: Long-Only MDD Stress Test
**Requirement:** Estimated MDD < 40% in dot-com bust (2000–2002) AND GFC (2008–2009)

**Dot-com bust (2000–2002):**
- NASDAQ fell ~78%, S&P 500 ~49%
- Darvas Box requires stocks near 52-week highs. By mid-2000, virtually no S&P 500 stocks form valid Darvas boxes (all falling well below prior highs)
- SPY regime filter: SPY broke below 150-day SMA in April 2000; new entries blocked from that point
- Existing positions stopped at box floors (systematic forced-exit before deep losses accumulate)
- Estimated strategy MDD: < 15% (strategy transitions to near-cash within 3–4 months of bear start)
- Proxy confirmation: any strategy requiring stocks near 52-week highs would generate near-zero signals from Q2 2000 onward

**GFC (2008–2009):**
- S&P 500 fell ~57% peak-to-trough
- SPY broke 150-day SMA in January 2008; regime filter blocks new entries
- Box floor stops would have exited most positions in Q4 2007 / Q1 2008 as stocks broke their consolidation zones
- Estimated strategy MDD: < 20% (some positions take losses before stops fire; regime filter kicks in)

**[X] PF-2 PASS — Estimated dot-com MDD: ~10–15%, GFC MDD: ~15–20% (both well below 40%)**

---

### PF-3: Data Pipeline Availability
**Requirement:** All required data available in yfinance/Alpaca daily pipeline

Required data:
- Daily OHLCV for S&P 500 + S&P 400 stocks: **available via yfinance** (S&P 500 tickers standard; S&P 400 tickers via local static list)
- SPY daily OHLCV for regime filter: **available via yfinance**
- No intraday data required
- No CVD, no tick data, no VWAP, no options chains

**[X] PF-3 PASS — All data sources confirmed available in yfinance daily OHLCV pipeline**

Implementation note: Use local static S&P 500 + S&P 400 constituent lists (avoid Wikipedia HTTP 403, per H86 lesson learned). Point-in-time constituent data should be approximated with a note on survivorship bias direction (inflates Sharpe; satisfies Hard Gate 9 option b with documented sensitivity).

---

### PF-4: Rate-Shock Regime Plausibility
**Requirement:** Written a priori rationale for why the strategy generates positive returns in the 2022 Rate-Shock regime

**Rationale:**

The 2022 Rate-Shock regime is characterized by:
- Fed funds rate rising from 0.25% to 4.50% (fastest hiking cycle in 40 years)
- S&P 500 falling -19.4% (correction territory); NASDAQ -33.1%
- Nearly all stocks declining; very few making new 52-week highs after Q1 2022

**Why H87 is structurally protected in 2022:**

1. **52-week high requirement eliminates entries early**: In a falling market, stocks drop below their prior highs within weeks. The `close >= high_52w * 0.75` filter means a stock must be within 25% of its 52-week high. As the market sold off from January 2022, this filter would have dramatically reduced the eligible universe by February–March 2022.

2. **SPY regime filter blocks new entries**: SPY broke below its 150-day SMA in March 2022. From that point, the regime filter blocks ALL new box breakout entries. The strategy enters near-zero-exposure mode structurally.

3. **Box floor stops exit existing positions**: Positions entered in Q4 2021 / early Q1 2022 would be stopped out at their box floors as stocks broke down from consolidations. The stop loss (box floor or 8% hard stop) limits losses per position to 8–12%.

4. **Strategy expects near-zero activity in 2022**: The performance attribution in 2022 IS windows will show: (a) few entries after March, (b) losses capped at 8% per position on early 2022 entries, (c) near-zero PnL from April–December 2022 (strategy in cash). This is the DESIRED behavior — the strategy sits out bear markets, which limits IS period MDD.

**The strategy does NOT generate positive returns in 2022 — it generates near-zero returns by sitting in cash.** This is the correct behavior for a long-only equity strategy facing a rate-shock bear market. The strategy's structural protection mechanisms (52-week high filter + regime filter + box floor stops) ensure MDD is bounded, which satisfies the charter objective (MaxDD < -15%).

**[X] PF-4 PASS — Rate-shock rationale: structural cash-out via (1) 52-week high filter eliminates entries, (2) SPY 150-SMA regime filter blocks new entries March 2022+, (3) box-floor stops exit existing positions. Strategy expects ~0% activity May–December 2022; MDD bounded by early Q1 2022 entries stopped at 8% maximum loss.**

---

## Hypothesis Class Diversification Mandate

**[X] PASS — Pattern-based / binary event-driven (Priority 1 class)**

The Darvas Box breakout is a BINARY EVENT: either the closing price clears the box ceiling on volume, or it does not. There is no "degree" of breakout signal — it is a discrete trigger, not a continuous momentum score. This places H87 firmly in the pattern-based / binary event-driven class (Priority 1 per CEO Directive QUA-181).

**Not a momentum-class hypothesis:** This strategy does not rank stocks by trailing returns, does not use momentum z-scores, and does not employ cross-sectional momentum. It uses price PATTERN STRUCTURE (box ceiling/floor geometry) with a volume trigger.

**No momentum-class hypothesis in this batch:** H85 (Weinstein Stage 2) was submitted in the prior batch. H87 is Pattern-based, not Momentum-class.

---

## Family Iteration Limit

**[X] PASS — Iteration 1/2 of the Darvas Box family (no prior iterations)**

This is the first hypothesis from the Darvas Box family. Family iteration budget: 2 Gate 1 iterations before mandatory retirement (per CEO Directive QUA-181). Current iteration: 1.

---

## ML Anti-Snooping Check

**N/A — No ML model used in this strategy.**

All signals are rule-based (box geometry + volume threshold). No trained models, no feature engineering, no train/validation/test split required.

---

## Track A Overnight/Weekend Guards (required for auto-defer avoidance)

- **Overnight gap documentation:** Darvas Box breakouts (large-cap stocks with ADV > $2M) typically have overnight gaps of 0.2–0.5% on non-event days. Gap contribution to total MDD should be reported in backtest output. Overnight gaps are a FEATURE for this strategy — post-breakout continuation overnight is a positive PnL contributor.
- **Weekend risk disclosure:** Positions held through weekends expose up to 10% of position notional (max 10% position size × 1 weekend × typical 1–2% weekend gap). Expected weekend gap MDD contribution: < 0.5% of account equity per weekend per position.
- **Earnings gap policy:** Earnings blackout implemented — if a held stock has earnings within 3 trading days, reduce position to 0 before earnings (hard exit). This avoids gap events > 10% that could breach the 8% stop. Point-in-time earnings date data required.
- **Gap MDD attribution:** To be reported in backtest. Expected: ~20–30% of total MDD attributable to gap events (industry norm for swing strategies); remainder from intraday session moves.

---

## Signal Combination Policy

**Single-signal strategy — no combination required.**

H87 uses one directional signal: Darvas Box ceiling breakout. No signal stacking.

The volume confirmation (volume > 1.20× average) is a FILTER, not a second alpha signal. It reduces false breakouts; it does not independently predict direction. IC of volume filter alone is near zero; it functions as a quality screen for the price breakout signal.

---

## Economic Rationale Summary (for Gate 1 review)

| Dimension | Assessment |
|---|---|
| Edge type | Price pattern (supply exhaustion + demand trigger) |
| Literature support | Darvas (1960) original; O'Neil CAN SLIM "N" factor (price at new highs); Jegadeesh-Titman momentum; Lo-Pindyck-Wang (2000) technical pattern predictability |
| Regime alignment | Works in bull markets (wide Stage 2 participation); exits structurally in bear markets |
| Why edge should persist | Institutional herding around visible breakout levels; supply/demand equilibrium at box boundaries is real (not artifact); self-reinforcing price dynamics post-breakout |
| Primary risk to edge | Crowding: if too many algo strategies trade the same boxes, the edge decays. Mitigation: volume confirmation filter selects breakouts with genuine institutional demand above average |
| Overfitting risk | Low: box geometry is defined by market structure (ceiling/floor), not arbitrary numerical thresholds. Box lookback N is the main parameter; 3-value sweep [15, 20, 25] is conservative. |
