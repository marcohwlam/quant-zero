# H82v2: Minervini Trend Template + VCP Breakout — Point-in-Time Universe Fix

**Version:** 2.0
**Author:** Research Director
**Date:** 2026-06-18
**Track:** A — Daily/Weekly (J Law Lineage)
**Asset class:** US equities (broad-market, ~1,500–3,000 stock universe)
**Strategy type:** Pattern-based single-signal
**Status:** retired
**Tier:** CEO Directive QUA-181 Priority Class 1 — Pattern-Based / Binary Event-Driven
**Family:** H82 (iteration 2 of 2 — family limit reached after this run)
**Parent hypothesis:** H82 — Minervini VCP Breakout (2026-06-17)

---

## Why H82v2 (Not a New Hypothesis)

H82 Gate 1 FAIL (2026-06-17) root cause: **survivorship-biased universe**, not alpha logic failure.

| Issue | H82 | H82v2 Fix |
|-------|-----|-----------|
| Universe | 144 large-cap survivors (fallback) | ~1,500+ historical members via iShares PIT holdings |
| IS trades | 101 (barely above threshold) | ~1,500–2,500 (10–15× improvement) |
| Statistical tests | No power (p=1.0, DSR=-4.83) | Sufficient power at 1,500+ trades |
| OOS Sharpe 0.85 | Selection artifact (current survivors = 2024 bull winners) | Bias eliminated; true OOS signal |
| COVID exposure | M-filter lags 4 distribution days | Added VIX >35 speed exit |

The VCP-in-Stage-2 alpha mechanism is intact and economically sound. H82v2 is a data quality correction, not a strategy redesign.

**Family iteration limit note:** This is iteration 2 of 2 for the H82 family. Per CEO Directive QUA-181, a third iteration requires ≥0.1 IS Sharpe improvement per prior iteration AND written Research Director rationale. If H82v2 fails, the VCP family is retired.

---

## Summary

Identical to H82 — stocks in a confirmed Stage 2 uptrend (Minervini 8-point Trend Template) that form a Volatility Contraction Pattern (VCP) and break out above the pivot high on elevated volume produce positive forward returns over 2–10 weeks. Full Minervini SEPA framework: Trend Template universe filter → VCP pivot breakout entry → 7.5% hard stop → 20% partial profit / 25% full exit with trailing stop.

**H82v2 modifications vs H82:**

1. **Universe:** Point-in-time aware ~1,500+ stock universe via iShares historical ETF holdings (IWB + IWM circa Jan 2018). Includes stocks that subsequently delisted — handled gracefully in code.
2. **VIX-speed exit:** If CBOE VIX closes above 35, immediately halt new buys (same effect as M-filter trip) without waiting for 4 distribution days to accumulate. Defends against COVID-style 35-day crash.
3. Everything else: identical to H82.

---

## Economic Rationale

Unchanged from H82. See `research/hypotheses/82_minervini_vcp_breakout.md` — Economic Rationale section.

**Additional note on universe breadth:**
The VCP edge depends on identifying institutional accumulation in mid-cap and small-cap leaders, not just large-cap survivors. Minervini's documented returns come predominantly from mid-cap names (market cap $1B–$10B) entering early Stage 2. The H82 fallback universe (large-cap mega-cap names) systematically excluded the highest-alpha subset of the eligible universe. H82v2 restores coverage of this core alpha source.

---

## Universe Construction (Engineering Director Implementation Notes)

### Primary Approach: iShares Historical Holdings

Engineering Director should download point-in-time holdings for:

| ETF | Index | Approx stocks | Source |
|-----|-------|--------------|--------|
| IWB (iShares Russell 1000) | Russell 1000 | ~1,000 | iShares website historical downloads |
| IWM (iShares Russell 2000) | Russell 2000 | ~2,000 | iShares website historical downloads |

Target snapshot date: **2018-01-01** (or nearest available). This covers the start of IS period — stocks in the index as of that date are used for the full IS window. Annual constituent updates can optionally be applied (2018, 2019, 2020, 2021, 2022, 2023 snapshots) for better point-in-time accuracy.

Store as: `data/h82v2_universe_2018_jan.csv` (columns: ticker, name, market_cap, date_added)

### Handling Delisted Tickers

Many historical Russell members subsequently delisted (bankruptcy, acquisition, going-private). yfinance returns partial data or empty DataFrame for delisted tickers. Strategy code must:

```python
def load_ticker_data(ticker, start, end):
    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if df.empty or len(df) < 252:  # skip if <1 year of data
            return None
        return df
    except Exception:
        return None
```

Delisted stocks contribute their actual returns to the IS period (they went to zero or were acquired at a premium — both outcomes are real). This is the correct treatment.

### Fallback

If iShares historical data is unavailable, use the following hierarchy:
1. S&P 1500 constituents circa 2017 (S&P 500 + 400 + 600) — ~1,500 stocks, annual constituent lists publicly available
2. Static list of ~800 US equities from QQQ + MDY + IWM circa 2017 — still 5–8× broader than H82 fallback

**PF-3 note:** All price data (OHLCV) for historical Russell/S&P members is available via yfinance, including delisted tickers (partial data). Constituent list is a static CSV embedded in the repo — not a live data dependency. PF-3 passes.

---

## Entry/Exit Logic

### Core Logic: Unchanged from H82

See `research/hypotheses/82_minervini_vcp_breakout.md` — Entry/Exit Logic section.

### H82v2 Modification: VIX-Speed Exit

Add to the M-filter:

```python
# Standard M-filter (unchanged)
dist_days_4wk = count_distribution_days(spy, window=25)
m_filter_standard = (dist_days_4wk < 4)

# H82v2 addition: VIX speed exit
vix = yf.download("^VIX", start=start, end=end, auto_adjust=True)["Close"]
vix_spike = vix > 35.0  # CBOE VIX above 35 = crisis/panic regime

# Combined M-filter: halt buys if EITHER condition true
market_ok = m_filter_standard AND NOT vix_spike
```

**Rationale for VIX 35 threshold:**
- VIX 35 corresponds roughly to 2σ daily move in SPY annualized
- Historical VIX > 35 days: COVID peak (March 2020), GFC (late 2008), COVID initial spike (Feb 2020)
- In March 2020, VIX hit 35 on March 9 (Monday after first major selloff) — 11 trading days before SPY bottom
- Without VIX exit: 4 distribution days would have accumulated by ~March 12 (3 days later) — marginal improvement
- With VIX exit: halts buys on March 9, captures 3 extra days of downside protection
- Also closes open positions if VIX >35 persists more than 2 days (same as M-filter trip → exit all)

**VIX exit parameters (for parameter sweep):**
- `vix_halt_threshold`: [30, 35, 40] — starting value 35
- `vix_exit_persistence_days`: [1, 2, 3] — days VIX must stay elevated before closing positions; starting value 2

---

## Asset Class & PDT/Capital Constraints

Unchanged from H82. See `research/hypotheses/82_minervini_vcp_breakout.md`.

---

## Market Regime Context

Unchanged from H82, with clarification:

| Regime | H82 | H82v2 Update |
|--------|-----|-------------|
| COVID crash (2020) | M-filter lags ~4 days | VIX >35 triggers halt on March 9, 2020 — 3 days earlier |
| All other regimes | Same as H82 | Identical |

---

## Gate 1 Assessment

| Metric | Target | H82 Actual | H82v2 Estimate |
|--------|--------|-----------|---------------|
| IS Sharpe | > 1.0 | **-0.12** | **0.9–1.3** |
| OOS Sharpe | > 0.7 | 0.85 (selection artifact) | 0.6–1.0 |
| IS CAGR | ≥ 10% | -1.1% | 12–22% |
| IS MaxDD | < 15% | -16.3% | 10–16% |
| IS Trades | ≥ 100 | 101 | **1,500–2,500** |
| Win rate | > 40% | 40.6% | 45–55% |
| Permutation p | < 0.05 | 1.00 | < 0.05 (at 1,500+ trades) |

**Key upgrade:** Statistical tests (permutation test, DSR, walk-forward) require trade counts in the hundreds to have power. At 101 IS trades, all statistical tests were noise-dominated. At 1,500+ trades, permutation p and DSR will accurately reflect whether the VCP signal has real edge.

**Remaining risk:** IS window 2018–2022 still contains 2022 rate-shock and 2018 Q4 correction. Trend Template + M-filter provide defense, but IS Sharpe < 1.0 remains possible if these two hostile years dominate. IS Sharpe of 0.9–1.3 is the realistic range.

---

## Recommended Parameter Ranges

Identical to H82 plus two new parameters:

| Parameter | Starting Value | Range to Test |
|-----------|--------------|--------------|
| (all H82 parameters) | (same) | (same) |
| `vix_halt_threshold` | 35 | [30, 35, 40] |
| `vix_exit_persistence_days` | 2 | [1, 2, 3] |

**Total parameter count: 11** (within Gate 1 limits for IS period of 5+ years; keep fixed VIX params in v1 to limit degrees of freedom)

---

## Alpha Decay Analysis

Unchanged from H82. See `research/hypotheses/82_minervini_vcp_breakout.md` — Alpha Decay Analysis section.

Signal half-life: 15–30 trading days. IC decay: gradual. Transaction cost viability: PASS.

---

## Signal Combination Policy

Single signal (VCP breakout). Unchanged from H82. Signal combination policy does not apply.

---

## Pre-Flight Gate Checklist

### [✓] PF-1: Walk-Forward Trade Viability

IS period: 2018–2023 (5 years, ~1,260 trading days).

- Broad-market universe ~1,500 stocks (vs 144 in H82)
- TT-passing stocks in bull phase: 150–400 (10% of 1,500)
- VCP setups per week: 10–30 (2–8% of TT-universe)
- Annual trade estimate: 500–1,500
- IS trade count: ~2,500–7,500 midpoint ~3,000
- Conservative estimate: **~1,500 IS trades** (if VCP filter is strict)
- IS trade count ÷ 4 = **375 ≥ 30 ✓**

**PF-1 PASS** — Estimated IS trade count: ~1,500 min, ÷4 = 375 >> 30.

Note: H82 produced 852 VCP signals on 144 stocks (5.9 signals/stock/5yr). With 1,500 stocks, expected: ~8,850 signals → even at 20% conversion to trades: ~1,770 IS trades. PF-1 is robust.

---

### [✓] PF-2: Long-Only MDD Stress

Identical to H82. Trend Template + M-filter create graduated cash mechanism in dot-com and GFC.

- Estimated dot-com (2000–2002) MDD: 15–30%
- Estimated GFC (2008–2009) MDD: 20–35%
- Both < 40% threshold ✓

**PF-2 PASS** — mechanism unchanged from H82.

---

### [✓] PF-3: Data Pipeline Availability

| Data Requirement | Source | Status |
|-----------------|--------|--------|
| Daily OHLCV (all tickers) | yfinance | ✓ Available (incl. partial for delisted) |
| 50/150/200-day SMA | Computed from OHLCV | ✓ Available |
| 52-week high/low | Computed from OHLCV | ✓ Available |
| SPY OHLCV (M-filter) | yfinance | ✓ Available |
| VIX (new) | yfinance `^VIX` | ✓ Available (yfinance ticker: `^VIX`) |
| Universe constituent list | Static CSV embedded in repo | ✓ Available — iShares historical download, no live dependency |

No tick data, no intraday VWAP, no CVD, no options chains.

**PF-3 PASS** — All data in current yfinance/Alpaca daily pipeline. Constituent CSV is a static asset, not a live data feed.

---

### [✓] PF-4: Rate-Shock Regime Plausibility (2022)

Identical to H82. Trend Template MA hierarchy inversion + M-filter distribution-day count create systematic de-risking in rate-shock. See `research/hypotheses/82_minervini_vcp_breakout.md` PF-4 section.

**Additional consideration for broad universe:** With 1,500 stocks including more rate-sensitive mid/small-caps, the 2022 TT failure rate will be higher and faster — this is a protective effect (universe empties out faster in 2022).

**PF-4 PASS** — rate-shock survival mechanism is a priori and quantitatively defined.

---

## H82v2 vs H82 Change Log

| Component | H82 | H82v2 |
|-----------|-----|-------|
| Universe size | 144 (fallback, survivorship-biased) | ~1,500–3,000 (PIT via iShares) |
| Universe source | FALLBACK_UNIVERSE hardcoded list | `data/h82v2_universe_2018_jan.csv` |
| VIX exit | Not present | `vix_halt_threshold=35`, `vix_exit_persistence_days=2` |
| Delisted handling | Excluded (survival bias) | Included with try/except (partial data = real returns) |
| Expected IS trades | 101 | ~1,500–2,500 |
| Everything else | — | Identical |

---

## Known Structural Risks

Identical to H82 with one addition:

| Risk | Severity | Mitigation |
|------|----------|-----------|
| (all H82 risks) | (same) | (same) |
| Universe construction bias if iShares data unavailable | Medium | Fallback to S&P 1500 circa 2017 per Engineering Director discretion |
| Higher small-cap slippage with broader universe | Low | $5M ADV filter eliminates illiquid names; market impact model applied |

---

## References

- H82 hypothesis: `research/hypotheses/82_minervini_vcp_breakout.md`
- H82 Gate 1 verdict: `backtests/H82_MinerviniVCPBreakout_2026-06-17_verdict.txt`
- H82 Gate 1 JSON: `backtests/H82_MinerviniVCPBreakout_2026-06-17.json`
- H82 strategy code: `strategies/h82_minervini_vcp_breakout.py`
- J Law Lineage: `docs/knowledge/trading-methodology-jlaw-lineage.md`
- Objective Function Charter: `docs/objective-function-charter.md`
- QUA-333 (H82 backtest issue): for Gate 1 result context
- QUA-340 (this escalation): decision context
