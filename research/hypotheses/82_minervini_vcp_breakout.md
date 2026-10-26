# H82: Minervini Trend Template + VCP Breakout

**Version:** 1.0
**Author:** Research Director
**Date:** 2026-06-17
**Track:** A — Daily/Weekly (J Law Lineage)
**Asset class:** US equities (large/mid-cap, Russell 3000 universe)
**Strategy type:** Pattern-based single-signal
**Status:** retired
**Tier:** CEO Directive QUA-181 Priority Class 1 — Pattern-Based / Binary Event-Driven
**Family:** New (no prior iterations)

---

## Summary

Stocks in a confirmed Stage 2 uptrend (Minervini 8-point Trend Template) that form a Volatility Contraction Pattern (VCP) — a series of progressively narrowing pullbacks with volume dry-up — and then break out above the pivot high on elevated volume are expected to produce positive forward returns over the next 2–10 weeks. The strategy applies the full Minervini SEPA framework: (1) Trend Template qualification as the universe filter, (2) VCP pivot breakout as the primary entry signal, (3) 7–8% hard stop, and (4) 20–25% profit target with trailing exit for remainder. A market-direction filter (O'Neil M-factor: distribution-day count on SPY/QQQ) halts new buys during market corrections, providing a natural cash mechanism in bear regimes.

This is a direct quant implementation of the most codifiable element of the J Law lineage. The Trend Template and VCP rules are exhaustively specified in `docs/knowledge/trading-methodology-jlaw-lineage.md` (Sections 2.2, 2.3).

---

## Economic Rationale

**Why this edge should exist:**

1. **Institutional supply/demand exhaustion at a defined price level.** The VCP pattern's contracting pullbacks represent progressive exhaustion of overhead supply. Each contraction cycle shakes out weaker holders; volume dry-up at contraction lows signals sellers are exhausted. The breakout above the pivot on high volume is the first moment demand unambiguously overwhelms the remaining supply — a measurable signal, not a narrative.

2. **Trend Template pre-selects for institutional accumulation.** All 8 Trend Template criteria must be simultaneously satisfied. This composite filter selects stocks where: (a) the 200-day MA is trending up (sustained institutional buying), (b) the MA hierarchy (50 > 150 > 200) is intact (trend is strengthening, not weakening), and (c) the stock is near its 52-week high (distribution has not yet begun). This combination is structurally rare — typically 3–8% of the investable universe in bull markets — and mechanically eliminates Stage 3/4 stocks before any signal is generated.

3. **Behavioral anchoring creates systematic underpricing at breakout.** Investor resistance to buying near 52-week highs (anchoring bias, George & Hwang 2004) suppresses demand below the pivot, allowing institutional accumulators to build positions quietly. Once the anchor level breaks, short-sellers covering and previously-sidelined buyers entering simultaneously amplify the initial move. The VCP volume dry-up confirms the setup has reached the inflection point.

4. **Natural regime filter removes exposure in downturns.** In bear markets and 2022-style rate shocks, MA hierarchies invert (50 < 150 < 200) and stocks break below their 52-week highs, failing TT3, TT5, TT7, TT8 simultaneously. The Trend Template universe collapses to near-zero passing stocks, creating an automatic cash allocation without a separate regime signal.

5. **Practitioner evidence.** Minervini's documented USIC championship returns (155% in 1997, 36% annualized over 10 years per public record) and multiple USIC finalist practitioners all rely on this exact pattern. The edge has survived decades of known, public codification — it is not a data-mined artifact.

**Estimated IS Sharpe:** 0.9–1.4 (long-term practitioner evidence; Minervini reports ~36% annualized, ~10–15% MDD in best periods; with universe diversity and strict rules, IS Sharpe of 1.0–1.3 is realistic)

---

## Entry/Exit Logic

### Universe Filter (applied daily on EOD data)

```python
# 1. Minimum price and liquidity
price_filter     = close >= 15.0                      # avoid thin stocks
liquidity_filter = avg_dollar_volume_20d >= 5_000_000  # $5M+ ADV

# 2. Minervini Trend Template (all 8 criteria)
TT1 = close > sma(close, 150)
TT2 = close > sma(close, 200)
TT3 = sma(close, 150) > sma(close, 200)
TT4 = sma(close, 200) > sma(close, 200)[30]  # 200-day MA today > 30 bars ago
TT5 = sma(close, 50) > sma(close, 150)
TT6 = sma(close, 50) > sma(close, 200)
TT7 = close > sma(close, 50)
TT8 = close >= rolling_52wk_low * 1.30       # 30%+ above 52-week low
TT9 = close >= rolling_52wk_high * 0.75      # within 25% of 52-week high

trend_template_pass = TT1 & TT2 & TT3 & TT4 & TT5 & TT6 & TT7 & TT8 & TT9

# 3. Market direction M-filter
dist_days_4wk = count_distribution_days(spy, window=25)
# distribution day = SPY closes down >= 0.2% on volume > prior day
market_ok = (dist_days_4wk < 4)

in_universe = price_filter & liquidity_filter & trend_template_pass & market_ok
```

### VCP Entry Signal

```python
def detect_vcp(highs, lows, closes, volumes, lookback=60):
    """
    Detects 2-4 contraction cycles with contracting depth and volume dry-up.
    Returns (signal: bool, pivot: float).
    """
    swings = find_swing_highs_lows(closes, min_swing_pct=0.04, lookback=lookback)
    if len(swings) < 3:
        return False, None

    contractions = []
    for i in range(0, len(swings)-1, 2):
        swing_high = swings[i]
        swing_low  = swings[i+1]
        depth = (swing_high - swing_low) / swing_high
        vol_at_low = mean_volume(volumes, swing_low_idx)
        contractions.append({'depth': depth, 'vol': vol_at_low})

    if len(contractions) < 2:
        return False, None

    # Each contraction depth < 75% of prior (contracting)
    depths_contracting = all(
        contractions[i]['depth'] < contractions[i-1]['depth'] * 0.75
        for i in range(1, len(contractions))
    )

    # Final contraction volume < 60% of 20-day avg (dry-up)
    avg_vol_20d = mean(volumes[-20:])
    final_vol_dryup = contractions[-1]['vol'] < avg_vol_20d * 0.60

    # Pivot = high of final contraction
    pivot = swings[-2]  # most recent swing high before final low

    return (depths_contracting and final_vol_dryup), pivot


def vcp_entry_trigger(close, volume, pivot, avg_vol_20d):
    """Breakout: close > pivot AND volume >= 1.40x 20-day avg."""
    return (close > pivot) and (volume >= avg_vol_20d * 1.40)
```

### Exit Rules

| Exit Type | Rule |
|-----------|------|
| Hard stop | 7.5% below entry (midpoint of O'Neil/Minervini 7–8% range) |
| Partial profit | Sell 50% at +20% from entry |
| Full/trail exit | Sell remaining 50% at +25%, or trail at 8% from peak |
| 8-week hold rule | If +20% in ≤ 15 calendar days, hold minimum 8 weeks before evaluating |
| Market exit | If M-filter trips (dist_days ≥ 4), close ALL open positions |
| Pattern failure | If stock closes back below pivot within 3 days of entry, exit immediately |

### Position Sizing

```python
# Elder 2% Rule
risk_per_share = entry_price * 0.075         # 7.5% stop
max_risk       = account_equity * 0.02       # 2% of equity
shares         = int(max_risk / risk_per_share)
position_val   = shares * entry_price
max_position   = account_equity * 0.15       # cap at 15% per name
shares         = min(shares, int(max_position / entry_price))

# Max concurrent open positions: 8 (avoids concentration risk)
# Elder 6% Rule: halt new trades if MTD PnL < -6% of equity
```

### Execution Assumption

Signal generated on EOD close (Day 0). Entry at open Day 1. (No same-day look-ahead bias.)

---

## Asset Class & PDT/Capital Constraints

| Constraint | Assessment |
|-----------|-----------|
| Account size | Works at $25K+ — position sizes 15% max (~$3,750 minimum per position); up to 8 positions |
| PDT compliance | Holds 2–10 weeks; NOT a day-trading strategy; PDT is not a concern |
| Short selling | Long-only; no shorting required |
| Options/derivatives | None required |
| Liquidity | $5M ADV minimum filter; no fill issues at $25K account |

---

## Market Regime Context

| Regime | Expected Performance | Mechanism |
|--------|---------------------|-----------|
| Bull market (Stage 2 breadth > 40%) | Strong — many qualifying setups | High TT-pass rate; frequent VCP setups |
| Late bull / selective market | Good — fewer setups, higher quality | TT filter becomes stricter; only leaders qualify |
| Correction (M-filter trips) | Near-zero activity | M-filter halts buys; open positions closed |
| Bear market (Stage 4 breadth) | Cash — no setups | TT fails for virtually all stocks |
| 2022 rate-shock | Cash / small loss | See PF-4 below |
| Choppy/sideways | Reduced activity, mixed | Fewer TT passes; VCP setups incomplete; lower position count |

---

## Gate 1 Assessment

| Metric | Target | Estimate |
|--------|--------|---------|
| IS Sharpe | > 1.0 | 0.9–1.3 |
| OOS Sharpe | > 0.7 | 0.7–1.0 |
| IS CAGR | ≥ 10% | 12–25% |
| IS MaxDD | < 15% (firm hard constraint) | 10–18% |
| Win rate | > 40% | 45–55% (Minervini range) |
| Avg hold | 2–8 weeks | ~3–5 weeks |

**Key risk:** IS window (2018–2022) contains two hostile regimes (COVID crash 2020, rate-shock 2022). The M-filter and Trend Template should preserve capital in both, but COVID's 35-day crash (too fast for MA exits) may cause a 10–20% portfolio drawdown before positions close. This is the primary IS Sharpe risk factor.

---

## Recommended Parameter Ranges

| Parameter | Starting Value | Range to Test |
|-----------|--------------|--------------|
| TT MA periods | [50, 150, 200] | Fixed (Minervini canonical) |
| TT4 lookback | 30 days | 20–40 days |
| Hard stop | 7.5% | 6–10% |
| Partial profit target | 20% | 15–25% |
| VCP volume breakout threshold | 1.40× avg | 1.25–1.60× |
| VCP volume dry-up threshold | 0.60× avg | 0.50–0.70× |
| Max concurrent positions | 8 | 5–12 |
| M-filter distribution-day count | 4 | 3–5 |
| Min ADV | $5M | $3M–$10M |

**Parameter count: 9** (within Gate 1 limits for IS period of 5+ years)

---

## Alpha Decay Analysis

**Signal half-life estimate:** 15–30 trading days.

The VCP breakout signal is a momentum-carry signal with a holding horizon matched to the pattern duration. The edge is primarily in the first 3–6 weeks post-breakout, where the stock is in the "markup" phase. After 6–8 weeks, the stock either forms a new base (new VCP setup) or begins distribution (TT fails → exit).

| Horizon | Estimated IC | Notes |
|---------|-------------|-------|
| T+1 (1 day) | 0.04–0.07 | Volume breakout momentum carry |
| T+5 (1 week) | 0.06–0.10 | Peak IC range — markup phase begins |
| T+20 (1 month) | 0.04–0.08 | Still positive; 20% profit target triggers partial exits |
| T+60 (3 months) | 0.01–0.03 | Near decay; trailing exit handles remainder |

**IC decay shape:** Gradual, not cliff-drop. The Trend Template exit rules (TT failure → close) create a natural stopping point before IC collapses.

**Transaction cost viability:** With ~200–400 trades/year and ~3-week average hold, round-trip costs are ~0.15–0.30% per trade (mid-cap, $5M ADV floor). Annual cost drag: ~0.6–1.2%. Edge (estimated ~15–20% gross CAGR from practitioner evidence) far exceeds cost drag. **VIABLE.**

**Half-life > 1 day:** ✓ — No transaction cost rejection triggered.

---

## Signal Combination Policy

**Primary signal:** VCP breakout (1 signal).
**Universe filters:** Trend Template, M-filter, CAN SLIM fundamentals — these are qualification criteria, not independent alpha signals.
**Signal count: 1** — signal combination policy does not apply; no IC-weighted blending needed.

---

## Pre-Flight Gate Checklist

### [ ✓ ] PF-1: Walk-Forward Trade Viability

IS period: 2018–2023 (approximately 5 years, ~1260 trading days).

- Russell 3000 universe: ~3,000 stocks.
- Typical TT-passing stocks in bull phase: 200–500.
- VCP setups per week (empirically ~2–5% of TT-universe): ~5–20 setups/week.
- Annual trade estimate: ~200–500 trades/year.
- IS trade count: ~1,000–2,500 over 5 years.
- IS trade count ÷ 4 = **250–625 ≥ 30 ✓**

**PF-1 PASS** — Estimated IS trade count: ~1,500 midpoint, ÷4 = ~375 >> 30.

---

### [ ✓ ] PF-2: Long-Only MDD Stress

This strategy is long-only equity but relies on the Trend Template + M-filter as a graduated cash mechanism:

**Dot-com bust (2000–2002):** SPY fell ~45%; QQQ fell ~80%. However:
- Trend Template requires 200-day MA trending up (TT4): by mid-2000, most growth stocks had violated TT4.
- TT8/TT9 (30% above 52wk low, within 25% of 52wk high) fail as stocks decline.
- Expected TT-passing universe: near-zero by late 2000.
- Individual position protection: 7.5% hard stop limits per-position loss.
- **Estimated dot-com MDD: 15–30%** (model to cash before sustained decline).

**GFC (2008–2009):** SPY fell ~55%. Strategy behavior:
- Distribution days accumulated in Q3 2007 through early 2008 → M-filter would have halted new buys by Jan 2008.
- Existing positions: TT criteria fail sequentially as MAs decline; hard stops trigger.
- **Estimated GFC MDD: 20–35%** (dependent on speed of M-filter response vs. forced sells).

**PF-2 PASS** — Both estimated MDDs < 40%; mechanism is the Trend Template's graduated MA-exit stack and M-filter's market-level brake. Subject to backtest confirmation.

---

### [ ✓ ] PF-3: Data Pipeline Availability

| Data Requirement | Source | Status |
|------------------|--------|--------|
| Daily OHLCV (Russell 3000 universe) | yfinance / Alpaca | ✓ Available |
| 50/150/200-day SMA | Computed from OHLCV | ✓ Available |
| 52-week high/low | Computed from OHLCV | ✓ Available |
| Volume averages | Computed from OHLCV | ✓ Available |
| SPY OHLCV (M-filter) | yfinance | ✓ Available |
| EPS fundamentals (CAN SLIM optional) | yfinance `.quarterly_earnings` | ✓ Available (quality caveat: use as soft filter only in initial version) |

No tick data, no VWAP, no CVD, no options chains required.

**PF-3 PASS** — All data available in current yfinance/Alpaca daily pipeline.

*Note: CAN SLIM fundamental filters (C, A criteria) are OPTIONAL for v1. Recommend implementing Trend Template + VCP first; fundamentals can be layered in v2 if needed.*

---

### [ ✓ ] PF-4: Rate-Shock Regime Plausibility (2022)

**A priori mechanism for 2022 rate-shock survival:**

2022 was a broad equity decline (-20% SPY, -33% QQQ) driven by rate normalization hitting high-multiple growth stocks hardest. The strategy's defense:

1. **Trend Template MA decay:** Rate-sensitive growth stocks (high P/E, long-duration earnings) saw their MAs invert first. TT5 (50 > 150 MA) failed for QQQ-type names by Jan–Feb 2022. TT4 (200-day MA trending up) failed by March 2022. Stocks breaking TT criteria were immediately off the eligible universe.

2. **M-filter distribution days:** The Jan 2022 market selloff (~-10% in 3 weeks) would have generated 4+ distribution days on SPY within the 25-day window by late January 2022, halting ALL new buy signals.

3. **Hard stop sequential exits:** Existing positions entering 2022 would have been stopped out at 7.5% loss each as the market declined. At max 8 concurrent positions, total portfolio damage from stops = max 8 × 2% account risk = 16% portfolio loss in a complete wipeout scenario. In practice, positions would close at different times, capping realized loss.

4. **Net result:** The strategy would have entered 2022 with reduced position count (Trend Template universe already thinning in Dec 2021), ceased new buys by late January 2022 (M-filter), and had remaining positions stopped out by Feb–Mar 2022. Expected 2022 contribution to MDD: **8–15%** — well within the firm's hard constraint of MaxDD < 15% if the transition is orderly.

**PF-4 PASS** — Rate-shock survival mechanism is written a priori: Trend Template MA hierarchy inversion + M-filter distribution-day count together create a systematic de-risking path. Not passive long-only; the exit stack is active and quantitatively defined.

---

## Known Structural Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Flash crash / gap-open below stop | High | Gap-open below 7.5% stop = fill at open; slippage in extreme moves |
| COVID-style 35-day bear (2020) | Medium | M-filter lags 4 distribution days; 1–2 weeks of open position loss before full cash |
| TT false positives in choppy market | Medium | Volume confirmation on entry (1.40× avg) reduces false-start setups |
| Small-float slippage | Low | $5M ADV floor mitigates; not using small-cap / low-float filter in v1 |
| Look-ahead bias on VCP pivot detection | Medium | Must implement with rolling window (no future data in pivot detection) |
| 2018 Q4 correction | Medium | M-filter should trigger; 2018 is a key IS stress test |

---

## References

- Minervini, M. (2013). *Trade Like a Stock Market Wizard.* McGraw-Hill.
- Minervini, M. (2017). *Think & Trade Like a Champion.* Access Publishing Group.
- George, T. & Hwang, C.Y. (2004). "The 52-Week High and Momentum Investing." *Journal of Finance*, 59(5).
- J Law Lineage Knowledge Base: `docs/knowledge/trading-methodology-jlaw-lineage.md` (Sections 2.1–2.4 for Trend Template/VCP spec)
- Pre-Flight Gate Framework: `research/hypotheses/README.md`
- Objective Function Charter: `docs/objective-function-charter.md`
