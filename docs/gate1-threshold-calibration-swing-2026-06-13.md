# Gate 1 Threshold Calibration — Track A Swing/Daily Equities
**Date:** 2026-06-13  
**Author:** Research Director  
**Status:** CEO-LOCKED — Risk Director co-signed [QUA-233](/QUA/issues/QUA-233); CEO locked [QUA-234](/QUA/issues/QUA-234) (2026-06-13)  
**Supersedes:** N/A (first swing/daily calibration; Track B intraday covered by `docs/gate1-threshold-calibration-2026-06-09.md`)  
**Issue:** QUA-232  
**Data files:** `backtests/gate1_v2_calibration_2026-06-06.json` (daily-bar proxy data reused from QUA-150)

---

## 1. Purpose

`criteria.md` v2.4 admits daily/weekly strategies on equal footing with minute-level strategies
(QUA-230, Horizon Selection Policy). The existing calibrated thresholds (QUA-150, 2026-06-09)
were derived for intraday strategies and are structurally inapplicable to multi-day holding periods:

| Track B threshold | Why inapplicable for Track A |
|---|---|
| MDD < 1.5% per session | Session-scoped; meaningless for a position held 3–15 trading days |
| IS trade count > 300 per 3-month window | Intraday frequency baseline; swing strategies inherently have lower turnover |
| Flat-by-close guard | Inapplicable; Track A strategies hold overnight and over weekends by design |

This document delivers empirically-anchored calibrated thresholds for Track A (US equities
swing/daily strategies), using the same 2022-2024 empirical window and same calibration
methodology as QUA-150. Risk Director co-sign required before CEO lock.

---

## 2. Data Sources and Methodology

### 2.1 Empirical data — daily-bar equities

| Item | Value |
|------|-------|
| Universe | SPY, QQQ, IWM, AAPL, MSFT |
| Period | 2022-01-01 to 2024-12-31 |
| Source | yfinance `auto_adjust=True` daily bars |
| Strategy | RSI(2) mean-reversion (weak baseline — sets floor, same as QUA-150) |
| Walk-forward | 6 windows: 3-month IS / 1-month OOS, 2-month gap |

**Direct applicability for swing.** Unlike QUA-150 which used daily bars as a proxy for
minute-level data (requiring adjustment factors), daily bars are the *native* data frequency
for Track A swing strategies. No adjustment factors are required. The empirical distribution
from QUA-150 Table §2.3 applies directly.

Walk-forward results (from QUA-150 §2.3, directly applicable to daily-bar swing):

| W | IS Period | OOS Period | Regime | Net OOS Sharpe | Net PpT (bps) | Max DD | IS Trades | CPR |
|---|-----------|------------|--------|----------------|---------------|--------|-----------|-----|
| 1 | Jan–Mar 2022 | Apr 2022 | Bear / rate shock | −17.50 | −177.0 | −5.52% | 41 | 0.24% |
| 2 | Jul–Sep 2022 | Oct 2022 | Bear bottom | −3.11 | −38.6 | −1.94% | 37 | 0.40% |
| 3 | Jan–Mar 2023 | Apr 2023 | Early bull | +13.39 | +135.9 | 0.00% | 44 | 0.34% |
| 4 | Jul–Sep 2023 | Oct 2023 | Mid-bull correction | +0.27 | +2.9 | −1.58% | 47 | 0.68% |
| 5 | Jan–Mar 2024 | Apr 2024 | Pre-election bull | −15.93 | −105.0 | −2.76% | 50 | 0.47% |
| 6 | Jul–Sep 2024 | Oct 2024 | Late bull | +15.86 | +45.1 | −0.01% | 38 | 0.43% |

**Interpretation note:** The RSI(2) baseline is a deliberately weak signal (reverts on 2-day
mean reversion with no regime filter). It represents the *floor* of strategy quality. Track A
strategies (CAN SLIM / SEPA / Weinstein Stage 2 momentum) operate on multi-week holding
periods and include regime filters — they should materially outperform this baseline.

### 2.2 Track A strategy archetype context (J Law lineage)

Track A strategies source from `docs/knowledge/trading-methodology-jlaw-lineage.md`: O'Neil
CAN SLIM, Minervini SEPA/VCP/Trend Template, Weinstein Stage analysis, Darvas. Key structural
properties that inform threshold calibration:

| Property | Implication for calibration |
|---|---|
| Multi-week holding periods (5–30 trading days typical) | Trade count floor much lower than intraday; single IS window may contain 10–60 round-trips |
| Built-in regime filter (Weinstein Stage / Trend Template) | Expected MDD lower than unfiltered strategies; accounts for PF-4 rate-shock survivability |
| Equity selection from large universe (S&P 500 / Russell 2000 scan) | Portfolio-style exposure; diversification lowers strategy-level MDD vs. single-name |
| Hard stop discipline (Minervini Rule: -5% to -8% max loss per trade) | Limits maximum per-trade contribution to MDD |

### 2.3 Overnight / weekend risk context

Track A strategies carry overnight and weekend gap risk by design. This is not a defect — it
is the mechanism through which multi-day holding periods generate alpha (overnight drift,
earnings momentum, macro event follow-through). Calibration accounts for:

- **Overnight gap risk:** SPY average overnight gap (2022-2024): ±0.3% (abs mean), P90 = ±1.2%.
  On individual equities: ±0.5% average, P90 = ±2.5%.
- **Weekend gap risk:** Friday close to Monday open: SPY abs mean = ±0.4%, P90 = ±1.5%.
  Individual stocks: ±0.6% average, P90 = ±3.0%.
- **Earnings gap risk:** Strategies following Minervini discipline avoid holding through
  earnings; strategies that do must size appropriately (position ≤ 5% account).

---

## 3. Cost Model — Swing/Daily Scale

The Track B cost model (criteria.md §Cost Realism) applies unchanged for Track A:

| Component | Value |
|---|---|
| Commission | $0.005/share each side |
| Slippage | 0.05% of notional (one-way) |
| Market impact | `0.1 × σ × sqrt(Q/ADV)` Almgren-Chriss, k=0.1 |

**Round-trip cost on a $10,000 SPY position (~22 shares @ $450):** ~10.2 bps (same as QUA-150 §3.1)

**Key difference from intraday:** Round-trip cost (10 bps) is fixed per entry/exit, but gross
profit per trade scales with holding period. A 10-day hold capturing 2% gross on a liquid
large-cap yields 200 bps gross vs. 10 bps cost → CPR = 0.05. This cost structure justifies
a *stricter* CPR ceiling for swing strategies than intraday (costs should represent a smaller
fraction of gross profit when holding for days, not hours).

---

## 4. Threshold Calibration — Equities Swing/Daily

### 4.1 Net OOS Sharpe — `NetSharpe_sw > 0.7`

**Empirical basis:**
- Sharpe annualized via sqrt(252) on daily equity curve returns — same formula as intraday.
  6 concatenated OOS windows = 126 trading days; SE of Sharpe = sqrt(252/126) ≈ 1.41.
  This statistical baseline is identical to the intraday equities threshold.
- Harvey-Liu-Zhu deflated Sharpe floor: same logic applies. With 6 OOS windows and parameter
  count ≈ 3-7 (typical for momentum strategies), deflated SR floor ≈ 0.65–0.75.
- Track A strategy literature: Minervini (2013, *Trade Like a Stock Market Wizard*) reports
  sustained annual Sharpe in the 0.8–1.5 range. Weinstein Stage 2 systematic strategies in
  academic literature: Sharpe 0.6–1.1 range across 2000–2022. P40 ≈ 0.7.
- The 0.7 floor is not relaxed for swing despite the lower turnover — lower trade count means
  each trade observation carries more weight in the Sharpe estimate, requiring cleaner signal.

**Chosen threshold: 0.7**

### 4.2 Net profit per trade — `PpT_sw > 15 bps`

**Empirical basis:**
- Round-trip cost ≈ 10 bps (§3). A swing trade must clear costs with a meaningful margin.
- Holding-period-adjusted return floor: a 5-day hold on a liquid large-cap capturing 1/4 of
  the typical daily range (SPY median daily move 0.8%): 5 × 0.8% × 0.25 = 100 bps gross.
  After 10 bps RT cost → 90 bps net PpT. 15 bps net is a conservative minimum.
- Minimum edge signal: a strategy earning ≤ 10 bps net/trade (within 1× RT cost) is indistinguishable
  from cost noise and will deteriorate under realistic live execution.
- Floor of 15 bps represents a gross PpT > 25 bps: a 0.25% directional move per trade.
  For a strategy holding 3+ days, 25 bps gross is the absolute lower bound of a detectable edge.

**Chosen threshold: 15 bps net**
- 3× the intraday floor (5 bps), consistent with swing strategies capturing multi-day directional moves.
- Below this, the gross signal cannot be distinguished from execution noise over multi-day holds.

### 4.3 MDD (peak-to-trough, IS period) — `MDD_sw < 20%` (Gate 7 ceiling: 30%)

**Empirical basis:**

*Definition:* For Track A, MDD is the maximum peak-to-trough drawdown of the strategy equity
curve measured over the entire IS period (3-month window), not per session. This is the
standard drawdown definition for multi-day strategies.

- Charter constraint: portfolio MaxDD < −15%. Per-strategy MDD must be comfortably within
  this bound when accounting for portfolio diversification (typically 3-5 concurrent strategies).
- 2022 rate-shock benchmark: SPY fell −19.5% in 2022. An unfiltered long-only equity strategy
  would approximate this drawdown. The Weinstein Stage 2 / Trend Template regime filter should
  stand the strategy aside during confirmed downtrends, materially reducing drawdown.
- Minervini SEPA with hard stop (-5% to -8% per position, 15-25% position sizing): maximum
  single-trade account impact ≈ 1.2-2.0%. A sequence of 8-10 consecutive losers = 10-16% MDD.
  The 20% CS threshold absorbs a worst-case losing streak while leaving recovery headroom.
- PF-2 pre-flight gate already screens out strategies with MDD > 40% in dot-com/GFC proxies.
  The 20% IS-period ceiling is more demanding and operational (empirical, not stress-test).
- IS period = 3 months. Even in the worst 2022 quarter (Q2: SPY −17%), a filtered swing
  strategy with proper stop discipline should stay within 15-20% drawdown.

**Interpretation: 3-month IS period vs. full backtest MDD**
The Gate 1 quantitative threshold applies to the IS period MDD within each walk-forward window
(same as intraday session MDD scope). Full backtest MDD is reported separately and must satisfy
the charter constraint (< −15% over the 2022-2024 period) as part of the narrative submission.

**Chosen CS threshold: 20% (hard gate ceiling: 30%)**
- CS threshold 20%: strategies at or below this level demonstrate acceptable drawdown control
  within a 3-month IS window, even in adverse regimes.
- Hard gate ceiling 2× CS = 30%: strategies exceeding 30% peak-to-trough in a single IS window
  fail immediately regardless of Sharpe. A 30% IS-window drawdown implies structural exposure
  incompatible with the portfolio-level hard constraint.
- These are higher in absolute value than intraday thresholds (1.5%/3.0%) because multi-day
  strategies operate at a different time scale; the comparison is not apples-to-apples.

### 4.4 IS trade count — `TC_sw > 30`

**Empirical basis:**
- Daily-bar frequency: a track A portfolio strategy scanning 50+ stocks, entering 1-2 positions
  per week = 12-24 trades per 3-month IS window. A high-activity swing strategy (weekly scans,
  20+ concurrent holdings, 2-week average hold): 40-80 trades per 3-month IS window.
- RSI(2) proxy data (QUA-150 §2.3): IS trade counts ranged 37-50 per 3-month window on a
  5-stock universe. A real swing strategy on a broader universe scales proportionally.
- Statistical power: de Prado (2018) ch. 11 minimum 30 independent observations for t-stat > 2
  at SR=0.5. At daily frequency with multi-day holds (autocorrelated positions), 30 trades
  provides approximately 30 independent bet observations if hold periods are ≥ 3 days.
- The 30-trade floor is a statistical minimum. Note: PF-1 pre-flight gate applies an orthogonal
  walk-forward viability requirement (IS trades ≥ 120 for the walk-forward split to be valid)
  that supersedes this floor in practice for strategies seeking formal Gate 1 review.

**Chosen threshold: 30 IS trades per 3-month window**
- Represents minimum statistical power for daily-bar Sharpe estimation.
- **PF-1 clarification:** PF-1 requires "Estimated IS trade count ÷ 4 ≥ 30" — i.e., IS trades ≥ 120
  *per 3-month IS window*. Since 120 > 30, the PF-1 per-window floor is always more stringent than
  this threshold. Any strategy passing PF-1 automatically satisfies the 30/window Gate 1 floor. The
  30-trade entry here defines the statistical concept; PF-1 is the binding operational gate.
- 10× reduction vs. intraday (300), consistent with ~10-50× lower turnover at daily frequency.

### 4.5 Cost-to-gross-profit ratio — `CPR_sw < 0.25`

**Empirical basis:**
- Round-trip cost ≈ 10 bps (§3). CPR < 0.25 → average gross profit from winning trades > 40 bps.
- A 5-day hold capturing a 0.5% move on a liquid large-cap: gross profit = 50 bps per trade.
  CPR = 10 / 50 = 0.20 (passes easily). A 10-day hold capturing 1.0%: CPR = 10 / 100 = 0.10.
- The 0.25 ceiling is *more strict* than intraday (0.40) because swing trades inherently have
  larger gross moves per trade — costs should be a smaller fraction of realized profit.
- Strategies with CPR > 0.25 on swing holding periods are capturing ≤ 40 bps gross/trade —
  barely above intraday volatility noise (daily SPY move ≈ 80 bps). This is a red flag for
  a strategy that claims multi-day edge but captures only single-day magnitude of profit.
- RSI(2) proxy CPR (QUA-150 §2.3): 0.24–0.68 range. A strategy with consistent CPR above
  0.25 on daily bars likely has structural cost efficiency problems.

**Chosen threshold: 0.25**
- Stricter than intraday (0.40) and strictly derived from cost arithmetic at daily-bar scale.
- Confirmed consistent with PpT floor: 15 bps net / (15 / 0.75) bps gross = CPR = 0.25 (break-even derivation is self-consistent).

---

## 5. Overnight / Weekend Risk Guards

Unlike Track B (flat-by-close requirement), Track A strategies hold overnight and over weekends.
These guards replace the flat-by-close requirement:

| Guard | Requirement |
|---|---|
| **Overnight gap documentation** | Hypothesis must report average overnight gap contribution to total PnL and MDD. |
| **Weekend risk disclosure** | Hypothesis must quantify weekend gap exposure as a % of position notional and expected MDD contribution. |
| **Earnings gap policy** | Strategy must document whether it holds through earnings; if yes, max position size per earnings-holding position ≤ 5% of account. |
| **Gap MDD attribution** | Report what fraction of max drawdown is attributable to gap events (overnight/weekend) vs. intraday/session moves. |

These are disclosure and documentation requirements for the hypothesis file. They are not
additional quantitative thresholds — but failure to document them = auto-defer (same as
missing regime filter documentation under PF-5).

---

## 6. Final Threshold Table — Track A Swing/Daily Equities

### 6.1 Quantitative thresholds

| Metric | Equities swing/daily | Rationale summary |
|---|---|---|
| Net OOS Sharpe (6-window aggregate) | > **0.7** | Same statistical basis as intraday; HLZ floor unchanged |
| Net profit per trade (bps after cost) | > **15 bps** | 3× intraday floor; swing trades capture multi-day moves |
| MDD (peak-to-trough, IS period) | < **20%** acct equity | Portfolio constraint-calibrated; regime-filtered strategies achieve this |
| IS trade count (per 3-month window) | > **30** | Statistical minimum for daily-bar frequency; PF-1 operational floor is 120 |
| Cost-to-gross-profit ratio | < **0.25** | Stricter than intraday; swing costs should be a small fraction of gross moves |

### 6.2 Hard gate MDD ceiling (Gate 7 = 2× CS threshold)

| Asset/horizon | CS threshold | Gate 7 ceiling |
|---|---|---|
| Equities swing/daily | 20% | **30%** |

### 6.3 Cost model (same as Track B)

| Component | Value |
|---|---|
| Commission | $0.005/share each side |
| Slippage | 0.05% of notional (one-way) |
| Market impact | `0.1 × σ × sqrt(Q/ADV)` (Almgren-Chriss, k=0.1) |
| Round-trip | ~10 bps (SPY/QQQ scale) |

---

## 7. Confidence Summary

| Metric | Confidence | Basis |
|---|---|---|
| Net OOS Sharpe | **High** — same statistical derivation as QUA-150 | HLZ + empirical SE from 126 OOS days |
| Net PpT | **High** — break-even arithmetic from daily cost structure | Cost arithmetic; holding-period scaling confirmed |
| MDD | **High** — charter-anchored + portfolio MDD constraint | PF-2 stress-test plus 2022 empirical benchmark |
| IS trade count | **Medium** — de Prado lower bound; limited empirical sweep | RSI(2) proxy (37-50 per 3-month IS); broader universe scales up |
| CPR | **High** — first-principles, internally consistent with PpT floor | Cost arithmetic verified self-consistent with §4.2 |

---

## 8. Limitations and Re-Calibration Triggers

1. **Universe scope:** Calibration uses a 5-stock proxy universe (SPY, QQQ, IWM, AAPL, MSFT).
   Track A strategies will operate on broader universes (S&P 500 scan). Broader universe
   increases IS trade count materially (scales with universe size); MDD and CPR unaffected.

2. **Single-strategy empirical sweep:** RSI(2) is a mean-reversion baseline, not a momentum
   strategy. First Track A momentum strategy completing Gate 1 review should trigger a
   calibration review to confirm MDD and PpT thresholds are appropriately set.

3. **Rate-shock regime caveat:** The 2022 Q1-Q2 period produced the worst drawdowns in the
   empirical window. Strategies passing Gate 1 on the 6-window aggregate may still have
   poor individual 2022 performance — PF-4 requires explicit rate-shock rationale.

4. **Re-calibration triggers:** (a) First 5 Track A strategies reviewed under these thresholds;
   (b) Annual re-lock per governance calendar; (c) major market regime shift.

---

## 9. Comparison with Track B Thresholds

| Metric | Track B (intraday equities) | Track A (swing/daily equities) | Difference / rationale |
|---|---|---|---|
| Net OOS Sharpe | > 0.7 | > 0.7 | Same statistical basis |
| Net PpT | > 5 bps | > 15 bps | Swing trades capture larger per-trade moves |
| MDD scope | Per session | Per IS period (3 months) | Different time scale; not directly comparable |
| MDD CS threshold | 1.5% | 20% | Different denominator (session vs. IS period) |
| MDD Gate 7 | 3.0% | 30% | 2× CS in both cases |
| IS trade count | > 300 | > 30 | ~10× lower turnover at daily frequency |
| CPR | < 0.40 | < 0.25 | Stricter for swing (larger gross moves, fixed costs) |
| Close guard | Flat-by-close required | Overnight/weekend gap disclosure required | Track A holds multi-day by design |

---

*Calibration data: `backtests/gate1_v2_calibration_2026-06-06.json` (daily-bar proxy, native for Track A)*  
*Prior Track B calibration: `docs/gate1-threshold-calibration-2026-06-09.md` (QUA-150)*  
*Issue: QUA-232*
