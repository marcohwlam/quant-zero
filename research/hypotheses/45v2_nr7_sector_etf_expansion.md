# H45v2: NR7 Sector ETF Universe Expansion

**Version:** 2.0
**Author:** Research Director
**Date:** 2026-06-24
**Asset class:** US equity / commodity ETFs (sector expansion)
**Strategy type:** single-signal, pattern-based
**Status:** READY
**Tier:** CEO Directive QUA-181 Priority Class 1 — Pattern-Based / Binary Event-Driven
**Parent hypothesis:** `research/hypotheses/45_qc_nr7_volatility_compression_breakout.md`
**Commission ticket:** QUA-407
**Parent ticket:** QUA-403

---

## Summary

H45v2 is a direct structural fix for H45's trade-count failure. H45 (NR7 on SPY/QQQ/IWM) failed Gate 1 with 5.5 trades/quarter — a frequency floor violation rooted in having only 3 ETFs. The NR7 signal itself showed statistical validity (permutation p=0.005, WF 3/4, IS MDD 9.2%) in the 2026-06-24 backtest. The core hypothesis remains intact: Crabel (1990) NR7 narrow-range compression days predict directional breakouts filtered by individual trend alignment.

This revision expands the universe to 15 liquid sector/commodity/bond ETFs. All entry/exit logic, parameters, and signal definitions are identical to H45. The 200-DMA trend filter is applied independently per ETF — this is the key structural enhancement: sector ETFs have uncorrelated drawdowns (e.g., XLE was above its 200-DMA for much of 2022 while SPY was below), generating valid long signals in resilient sectors even during broad-market corrections.

**Estimated IS trades per 4-year WF window:** ~504 (5× H45 actual average of 101 per window for 3 ETFs). Exceeds PF-1 floor (≥120) and QUA-407 acceptance criteria (≥120 IS trades, 30/qtr × 4 years).

---

## Family Iteration Limit Exception (Required — Third Iteration)

**This is the third iteration of the NR7 hypothesis family.** CEO Directive QUA-181 requires explicit written rationale when the ≥0.1 IS Sharpe improvement criterion is not met.

**Iteration history:**
| Iteration | Date | IS Window | IS Sharpe | Permutation p | Verdict |
|---|---|---|---|---|---|
| Iter 1 | 2026-05-28 | 2007–2021 | 0.4686 | 0.55 | RETIRED (noise) |
| Iter 2 | 2026-06-24 | 2005–2018 | 0.2529 | 0.005 | FAIL (trade count floor) |
| **Iter 3 (this)** | **2026-06-24** | **TBD** | **TBD** | **TBD** | **READY** |

**IS Sharpe comparison across iterations:** Not directly comparable. Iter 1 and Iter 2 used different IS/OOS windows (2007–2021 vs. 2005–2018). The ≥0.1 improvement criterion is inapplicable when IS windows differ.

**Why this iteration is authorized (QUA-407 CEO mandate):**

The Iter 1 retirement was on the correct grounds — permutation p=0.55 confirmed the signal was noise in the 2007–2021 IS window. Iter 2 (2005–2018 IS) produced p=0.005, revealing a real signal edge in the earlier IS window. The structural bottleneck in Iter 2 is **trade count** (5.5/quarter), not signal absence. This is fundamentally different from the Iter 1 retirement reason (confirmed noise).

Universe expansion (3→15 ETFs) directly addresses and resolves the trade count structural bottleneck:
- Root cause isolated: 3 ETFs at 7.3 trades/year/ETF × 3 = 22/year is insufficient
- Fix: 15 ETFs × 7.3 trades/year/ETF = 109/year = 27+ trades/quarter over 4-year WF window
- No changes to signal logic, parameters, or any element that could introduce overfitting

**Commission authority:** QUA-407 (CEO directive, high priority). Third iteration authorized by CEO via QUA-407.

---

## Economic Rationale

**Unchanged from H45 — see parent hypothesis for full documentation.**

Core mechanism: GARCH volatility clustering (Engle 1982) causes daily range compression to resolve directionally. The NR7 day — whose true range is the minimum of the prior 7 days — identifies peak compression. Post-NR7 directional expansion, filtered by per-ETF 200-DMA trend, generates a statistically detectable edge (confirmed p=0.005 in 2005–2018 IS window).

**Sector diversification adds one structural enhancement:**

Broad-market ETFs (SPY, QQQ, IWM) are highly correlated. When SPY breaks below its 200-DMA (rate-shock, GFC onset), all three ETFs tend to simultaneously enter bear-market regimes, halting all signal generation. Sector ETFs exhibit lower cross-sector correlation in drawdowns:

- **2022 rate-shock:** SPY and QQQ broke below 200-DMA by March 2022. Energy (XLE) remained above its 200-DMA through most of 2022 (crude oil/energy sector tailwind). Healthcare (XLV) and Consumer Staples (XLP) showed defensive resilience. These sectors would have continued generating valid NR7 signals.
- **2008–2009 GFC:** Even in a systemic drawdown, commodity ETFs (GLD) and defensive sectors (XLV, XLP, XLU) maintained their 200-DMAs for portions of the downturn.

**Quantified improvement in expected OOS signal generation:** In a broad-market bear where SPY generates 0 NR7 signals, a 15-ETF portfolio with independent 200-DMA filters is expected to have 2–5 sectors generating valid signals. This partial-market exposure is a structural OOS durability improvement over the H45 3-ETF construct.

---

## Market Regime Context

| Regime | H45 (3 ETFs) | H45v2 (15 ETFs) |
|--------|-------------|-----------------|
| Bull trend (2003–2007, 2010–2019, 2020–2021) | Strong | Strong — all/most sectors above 200-DMA |
| Choppy sideways (2015–2016, 2018 Q4) | Moderate | Moderate-to-improved — sector rotation means some ETFs still trend |
| 2000–2002 dot-com bust | Protected (SPY below 200-DMA) | Protected — most sectors below 200-DMA, limited signals; GLD/XLU/XLV may generate partial signals |
| 2008–2009 GFC | Protected | Protected — most sectors below 200-DMA; GLD, XLV, XLP partial signals |
| **2022 rate-shock** | **Protected (SPY filter)** | **Better — XLE above 200-DMA; defensive sectors partial; more signal generation than H45** |
| High-VIX / volatility spike | Weaker — whipsaws | Weaker — same exposure; ATR stop compensates |

**Key regime differentiation:** H45v2 generates non-zero signals during sector-rotation environments where the broad market is bearish but select sectors are in uptrend. This reduces the OOS dead periods that likely drove the H45 OOS Sharpe to -0.30.

---

## Universe

**Primary universe — 15 ETFs:**

| Ticker | Sector/Theme | Data Start | IS Coverage (2005–2018) |
|--------|-------------|------------|------------------------|
| SPY | S&P 500 | 1993 | ✅ Full |
| QQQ | Nasdaq-100 | 1999 | ✅ Full |
| IWM | Russell 2000 | 2000 | ✅ Full |
| XLK | Technology | Dec 1998 | ✅ Full |
| XLF | Financials | Dec 1998 | ✅ Full |
| XLV | Health Care | Dec 1998 | ✅ Full |
| XLE | Energy | Dec 1998 | ✅ Full |
| XLI | Industrials | Dec 1998 | ✅ Full |
| XLY | Consumer Discretionary | Dec 1998 | ✅ Full |
| XLP | Consumer Staples | Dec 1998 | ✅ Full |
| XLB | Materials | Dec 1998 | ✅ Full |
| XLU | Utilities | Dec 1998 | ✅ Full |
| GLD | Gold | Nov 2004 | ✅ Near-full (starts Dec 2004) |
| TLT | 20+ Year Treasury | Jul 2002 | ✅ Full |
| SLV | Silver | Apr 2006 | ⚠️ Partial (starts Apr 2006 in IS) |

**Excluded (data limitation):**
- XLRE (Real Estate): launched Oct 2015 — only 3 years of IS coverage; negligible contribution to IS statistics
- XLC (Communications): launched Jun 2018 — effectively no IS coverage

Engineering Director note: include XLRE and XLC in the backtested universe; yfinance will return NaN for dates before each ETF's launch — engine should handle gracefully (skip signal if no data). XLRE and XLC will contribute OOS signals (2019+) without contaminating IS statistics.

**Why this universe:** All 9 original SPDR sector ETFs (launched 1998), the 3 original H45 ETFs, plus GLD/TLT/SLV for cross-asset diversification. Sector ETFs provide the uncorrelated-drawdown property that enables signal generation during sector-rotation regimes. GLD provides inflation-hedge exposure (historically strong in 2022 rate-shock environment).

---

## Entry/Exit Logic

**All signal logic is identical to H45.** Only the universe changes.

**Signal computation (per ETF ticker, at daily close):**
1. True Range: `TR_t = max(High_t, Close_{t-1}) - min(Low_t, Close_{t-1})`
2. NR7 flag: `NR7_t = 1 if TR_t == min(TR_t, TR_{t-1}, ..., TR_{t-6}) else 0`
3. Trend filter (per ETF): `trend_ok = 1 if Close_t > SMA(Close, 200)_t else 0`

**Entry:** If `NR7_t == 1` AND `trend_ok == 1` AND concurrent positions < 5: enter at next-day market open. Breakout confirmation check: only enter if open ≥ NR7 day's High (if open gaps below the NR7 high, skip).

**Exit (first of):**
1. Time exit: close at end of day 5
2. Stop-loss: 2×ATR(14) below entry price (ATR computed at entry date)
3. Trend break: close at next open if ETF's own 200-DMA is crossed below during holding period

**Position sizing:**
- Max 5 concurrent positions
- Each position: 20% of portfolio (equal weight, fixed allocation)
- If fewer than 5 positions active: remaining capital in cash (no leverage)
- If simultaneous signals exceed 5: rank by signal date/time; take first 5 in ticker-alphabetical order as tiebreaker

**Holding period:** 5 trading days (unchanged from H45)

---

## Asset Class & PDT/Capital Constraints

- **Assets:** 15 ETFs, all highly liquid (ADV > $500M/day for sector ETFs; SPY/QQQ/GLD/TLT ADV > $5B/day)
- **Min capital:** $25,000 (5 positions × 20% each; position sizing works at PDT minimum)
- **PDT:** 5-day hold — overnight holds throughout — NOT day trades ✅
- **Commission:** $0 (commission-free brokers). Bid-ask spread cost: SPY ~0.002%, XLK/XLF/XLV ~0.005%, sector ETFs ~0.01%. Negligible versus expected per-trade return.
- **Liquidity:** No impact at $25K account size for any ticker in the universe

---

## Gate 1 Assessment

| Metric | H45 Actual | H45v2 Estimate | Threshold | Outlook |
|--------|-----------|----------------|-----------|---------|
| IS Sharpe | 0.2529 (FAIL) | 0.5–0.9 | > 1.0 | UNCERTAIN — universe expansion may not recover Sharpe to 1.0; marginal at best |
| OOS Sharpe | -0.30 (FAIL) | 0.2–0.6 | > 0.7 | BORDERLINE — sector diversification helps but OOS regime is challenging |
| IS MDD | -9.17% (PASS) | ~12–18% | < 20% | PASS — more positions slightly higher aggregate exposure |
| IS Trade Count (4y WF window) | 101/window for 3 ETFs (FAIL) | ~504 (5×) | ≥ 120 | **STRONG PASS** |
| Trades/quarter | 5.5 (FAIL) | ~31.5 | > 30 | **PASS** (marginally) |
| WF Stability | 3/4 (PASS) | 3/4–4/4 | ≥ 3/4 | LIKELY PASS |
| Parameter Sensitivity | 112% (FAIL) | TBD | < 50% | UNCERTAIN — same parameter set; improvement unclear |

**Honest assessment:** The primary value of H45v2 is fixing the trade-count floor to make the backtest statistically meaningful. H45 produced a real permutation result (p=0.005) despite the 5.5/quarter trade-count failure, but the Gate 1 verdict cannot be fully trusted with so few trades. With 500+ IS trades, the Gate 1 statistics become reliable. Whether the IS Sharpe reaches 1.0 or OOS Sharpe exceeds 0.7 after the universe expansion is genuinely uncertain — this is the empirical question H45v2 tests.

**If IS Sharpe does not improve to 1.0:** This family should be retired (3rd iteration, final). The sector expansion is the last structural fix available without changing the core NR7 signal.

---

## Recommended Parameter Ranges

| Parameter | H45 Value | H45v2 Value | Notes |
|---|---|---|---|
| NR7 lookback | 7 (Crabel canonical) | **7 — DO NOT CHANGE** | Definitional; grid search would be overfitting |
| Trend filter MA | 200 days | 200 days | Applied per-ETF independently |
| Holding period | 5 days | 5 days | Do not vary in first run |
| Stop-loss ATR multiplier | 2.0× | 2.0× | Keep identical to H45 for clean comparison |
| Entry method | Next-day open if open ≥ NR7 high | Identical | |
| Max concurrent positions | N/A (3-ETF universe) | **5** | New parameter; test 3 and 7 in robustness sweep |

**Robustness sweep:** Only vary max_concurrent_positions (3, 5, 7) in the sweep. All other parameters held at H45 canonical values. This is intentional: varying only the structural fix parameter provides a clean test of whether trade-count alone was the bottleneck.

**Parameter count:** 5 (NR7 window fixed, MA period, hold period, ATR stop, max_positions). NR7 window treated as fixed (definitional) — effectively 4 free parameters. Within Gate 1 parameter budget.

---

## Alpha Decay Analysis

**Unchanged from H45** — the NR7 signal mechanism and half-life are unchanged.

- **Signal half-life:** 3–7 trading days (same as H45)
- **IC decay:** T+1 ≈ 0.04–0.07; T+3 ≈ 0.03–0.05; T+5 ≈ 0.01–0.02; T+10 ≈ 0.00
- **Transaction cost viability:** Round-trip spread cost ~0.005–0.01% for sector ETFs. Against expected 0.5–1.0% per-trade average, edge survives by 50–200×. ✅
- **H45v2-specific crowding note:** Sector ETF NR7 strategies are less common than broad-market NR7 implementations. Retail execution is fragmented across 15 tickers versus concentrated in SPY. Slightly lower crowding risk than H45.

---

## Pre-Flight Gate Checklist

### PF-1: Walk-Forward Trade Viability

**Calibration basis:** H45 actual backtest (2026-06-24) produced 305 total IS trades for 3 ETFs over 14 years (2005–2018). WF 4-year IS windows averaged 100.75 trades per window (101, 116, 97, 89). Per-ETF rate: 33.6 trades per 4-year WF window.

**H45v2 estimate (15 ETFs, proportional scaling):**
- Per 4-year WF IS window: 33.6 trades/ETF × 15 ETFs = **504 trades**
- PF-1 formula: 504 ÷ 4 = **126 ≥ 30** ✅
- QUA-407 acceptance criteria: 504 ≥ 120 ✅
- Implied trades/quarter: 504 / 16 quarters = **31.5/quarter** ✅

**Sensitivity:** If sector ETFs generate 20% fewer NR7 signals than broad-market ETFs due to more individual downtrends: 504 × 0.80 = 403 trades. 403 ÷ 4 = 101 ≥ 30 ✅. 403 ≥ 120 ✅. Still passes.

**[x] PF-1 PASS — Estimated IS trades per 4-year WF window: 504, ÷4 = 126 ≥ 30**

---

### PF-2: Long-Only MDD Stress Test

**2000–2002 dot-com bust:**
- SPY crossed below 200-DMA Q4 2000. Technology (XLK) and Discretionary (XLY) led the decline — below 200-DMA early and deep.
- Defensive sectors (XLV, XLU, XLP) held up significantly better; GLD and TLT in bull market during 2000-2002.
- H45v2 with per-ETF trend filter: minimal long entries in any declining-trend sector. GLD/TLT were in uptrend during this period, potentially generating safe NR7 signals.
- Estimated dot-com MDD: **< 15%** (same 200-DMA protection per ETF; diversification limits aggregate exposure). ✅

**2008–2009 GFC:**
- Systemic drawdown — most ETFs below 200-DMA by Oct 2008.
- Defensive sectors (XLV, XLP, XLU) slightly less severe; GLD briefly above 200-DMA in flight-to-safety.
- Estimated GFC MDD: **< 18%** (broadly similar to H45; slightly more cross-sector diversification offers modest improvement). ✅

**[x] PF-2 PASS — Estimated dot-com MDD: ~12%, GFC MDD: ~16% (both < 40%)**

---

### PF-3: Data Pipeline Availability

All 15 primary ETFs are available via yfinance daily OHLCV from respective launch dates:
- SPY, QQQ, IWM, XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLB, XLU: full history to 1998–2000 ✅
- GLD: Nov 2004 ✅
- TLT: Jul 2002 ✅
- SLV: Apr 2006 (engine handles pre-launch dates as NaN/no-signal) ✅

Required computations: daily True Range (High, Low, prior Close), 7-day minimum True Range, 200-day SMA of Close, 14-day ATR. All derived from standard daily OHLCV. No intraday data, no options chains, no tick data, no external data sources.

**[x] PF-3 PASS — All data sources confirmed in yfinance/Alpaca daily OHLCV pipeline**

---

### PF-4: Rate-Shock Regime Plausibility

**2022 rate-shock mechanism for H45v2:**

SPY broke below its 200-DMA on March 14, 2022. In H45, this halted all signal generation. H45v2 with sector-independent 200-DMA filters:

1. **XLE (Energy):** In 2022, crude oil prices surged due to Ukraine/Russia supply disruption and post-COVID demand recovery. XLE was the top-performing SPDR sector ETF in 2022 (+66% total return). XLE remained **above its 200-DMA for most of 2022** — a rate-shock environment that SPY cannot survive is an energy bull market. XLE NR7 signals in 2022 would have been valid and directionally favorable.

2. **XLF (Financials):** Rising rates benefit net-interest-margin businesses. XLF declined but less than SPY in H1 2022; recovered above its 200-DMA intermittently in H2 2022.

3. **XLV (Health Care) and XLP (Consumer Staples):** Defensive sectors declined less than SPY and SPX; these ETFs maintained their 200-DMA crossings for shorter periods.

4. **GLD (Gold):** Historically, gold is a rate-shock hedge. In 2022, GLD was above its 200-DMA through Q1 and intermittently through 2022 as inflation drove gold demand.

**Mechanism by which H45v2 survives rate-shock:** Per-ETF 200-DMA filters allow the portfolio to continue generating long NR7 signals in sectors (XLE, GLD, defensive sectors) that are in uptrend during rate-shock regimes, while zero long entries are generated for rate-sensitive sectors (XLU, XLRE, XLK) that break below their 200-DMAs. This sector-diversified regime survival is structurally superior to the broad-market-only H45 which goes completely to cash.

**[x] PF-4 PASS — Rate-shock rationale: sector-independent 200-DMA filters allow signal generation in resilient sectors (XLE, GLD, XLV, XLP) while filtering rate-sensitive sectors; XLE alone generated strong positive returns in 2022**

---

## Signal Combination Policy Compliance

Single-signal strategy — no signal combination. Policy does not apply. NR7 is the only signal; 200-DMA is a regime filter (not a signal combination).

---

## ML Anti-Snooping

Not applicable — no ML features in this strategy.

---

## QuantConnect Source Caveat

**Strategy source:** Direct extension of H45 (QC-sourced NR7 strategy). H45v2 adds no new QC-sourced elements — universe expansion to sector ETFs is a Research Director structural fix, not a new QC discovery.

**Not a new QC hypothesis** — this hypothesis does not consume a QC discovery batch slot per the QC Discovery Gate. QUA-407 commission authority applies.

---

## Relationship to H45

| Dimension | H45 | H45v2 | Changed? |
|---|---|---|---|
| NR7 lookback | 7 | 7 | No |
| Trend filter | 200-SMA per ETF | 200-SMA per ETF | No |
| Entry logic | Next-open if open ≥ NR7 high | Identical | No |
| Holding period | 5 days | 5 days | No |
| Stop-loss | 2×ATR(14) | 2×ATR(14) | No |
| Universe | SPY, QQQ, IWM (3 ETFs) | 15 ETFs | **YES — structural fix** |
| Max positions | 3 (1 per ETF) | 5 | **YES — new constraint** |
| Position sizing | 1/3 portfolio per position | 20% per position (max 5) | **YES — adjusted for larger universe** |

The only changes are: (1) universe expansion, (2) max concurrent positions cap at 5, (3) position sizing adjusted to 20% per position.

---

## References

- Crabel, T. (1990). *Day Trading with Short-Term Price Patterns and Opening Range Breakout.* Traders Press.
- Engle, R. (1982). "Autoregressive Conditional Heteroscedasticity." *Econometrica*, 50(4), 987–1007.
- H45 verdict: `backtests/H45_NR7VolatilityBreakout_2026-06-24_verdict.txt`
- H45 hypothesis: `research/hypotheses/45_qc_nr7_volatility_compression_breakout.md`
- QUA-407 (commission mandate), QUA-403 (parent)

---

*Research Director | QUA-407 | 2026-06-24*
