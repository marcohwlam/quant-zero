# Research Note: H63 Family Retirement — SPY/QQQ Intraday Pairs Mean Reversion

**Status:** RETIRED (family)
**Author:** Research Director (QUA-182)
**Date:** 2026-06-10
**Covers:** H63v1 (QUA-167), H63v2 (QUA-177)
**Retirement decision:** QUA-182

---

## Retirement Summary

| Iteration | Issue | Root Cause | Best IS Sharpe | Verdict |
|---|---|---|---|---|
| H63v1 | [QUA-167](/QUA/issues/QUA-167) | Rolling z-score window mechanics artifact | 0.636 (artifact-inflated) | FAIL |
| H63v2 | [QUA-177](/QUA/issues/QUA-177) | No alpha — spread trends intraday | −0.11 (best of 324 combos) | FAIL |

Both permitted iterations exhausted under the 2-iteration family limit (CEO Directive QUA-181). No further SPY/QQQ intraday pairs iterations will be initiated.

---

## H63v2 Diagnostic — Critical Findings

With the H63v1 window-mechanics artifact removed (daily z-score baseline):

- **86% of positions stopped out at |z| > 3.0** — spread did not revert; it diverged through the hard stop.
- **Best IS Sharpe across 324 parameter combinations: −0.11** (at extreme low-frequency settings: BASELINE=10d, ENTRY=2.0, EXIT=0.1, HEDGE=10d). All other combinations were substantially worse (median: −1.54).
- **Permutation p-value: 1.00** — the strategy underperforms random chance on every walk-forward window. This is not marginal; the signal has zero predictive content.
- **Win rate: 12.1% IS, 12.8% OOS** — versus an expected 62–68% from Chan (2013).
- **0/4 walk-forward windows passed** across all four IS/OOS splits.

The hypothesis is **empirically rejected**. The spread does not mean-revert intraday in the 2018–2026 period.

---

## Why Intraday SPY/QQQ Pairs Mean Reversion Failed

### 1. The theoretical mechanism no longer operates at the intraday scale

The a priori rationale for H63 assumed three structural mean-reversion forces:
1. ETF market maker arbitrage
2. Index arbitrage from the ~80-stock overlap
3. Institutional long/short hedge rebalancing

All three forces still exist. **The critical error was assuming these forces operate at a 30-minute to 2-hour intraday timescale.** They do not.

**ETF creation/redemption mechanics** — the primary arbitrage channel — operate at the **end-of-day NAV settlement level**, not within the session. Authorized Participants (APs) can create/redeem ETF shares to exploit price discrepancies, but only during the T+1 settlement window. Intraday AP activity is far less frequent than retail and institutional open-market activity, meaning the spread can spend most of a session diverging before AP forces restore it.

**What the 86% stop-out rate reveals:** The spread was not returning to the daily baseline — it was trending through the 3σ stop for 86% of trades. This is characteristic of **intraday momentum**, not noise. When the spread widens intraday, it tends to keep widening (directional momentum in the spread), not revert.

### 2. Post-2018 ETF microstructure has changed

Chan (2013) Table 6.3 reflects 2004–2012 market microstructure. Since then:

**Rise of intraday ETF flows from retail and passive investing.** The 2018–2026 period saw explosive growth in intraday ETF trading from retail platforms (Robinhood, Schwab, Fidelity commission-free). This flow tends to be **directional and correlated with recent intraday momentum**, not mean-reverting. When tech sentiment shifts intraday, retail flows pile into QQQ relative to SPY (or vice versa), creating **persistent intraday spread trends** rather than noise.

**QQQ's tech-sector concentration increased structurally.** The top-10 NASDAQ 100 constituents (AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AVGO, COST, AMD) now represent ~50%+ of QQQ by weight (vs. ~35% in 2012). When any of these mega-caps has an intraday catalyst (earnings leak, analyst note, Fed commentary on rates), QQQ moves independently from SPY — creating **persistent intraday directional spread deviations**, not transient noise.

**Index arbitrage at microsecond speed eliminates the tradeable spread window.** Modern index arbitrage via HFT eliminates the large-spread dislocations that Chan (2013) captured in the 2004–2012 era at minute-bar resolution. Any spread deviation that could be profitably faded by a retail strategy (executing at the 1-minute bar + 1 latency) is now resolved by HFT within milliseconds. What remains at the 1-minute resolution is directional flow, not arbitrageable noise.

### 3. The daily baseline doesn't resolve the structural problem

H63v2's hypothesis was: the H63v1 artifact (window mechanics) masked a real signal. If we anchor z-scores to a stable daily baseline, genuine intraday mean reversion will be visible.

**The backtest falsified this hypothesis.** With the daily baseline:
- Deviations from the multi-day spread equilibrium do NOT revert within the session in 2018–2026.
- Instead, intraday spread moves follow the direction of the deviation: when the spread widens relative to the daily anchor, it keeps widening within the session (intraday trend).
- This is consistent with modern ETF microstructure: intraday SPY/QQQ spread deviations are driven by persistent intraday order flow, not arbitrageable noise.

**The fundamental hypothesis was wrong**: the intraday SPY/QQQ spread is not a stationary, noise-driven process at minute resolution in 2018–2026. It exhibits intraday momentum.

---

## Implications for Adjacent Hypotheses

### Direct implication: Intraday ETF pairs are not mean-reverting

Any cross-asset relative-value strategy that assumes intraday mean reversion in ETF spread pairs faces the same structural challenge:
- H60/H60b (Intraday VWAP Mean Reversion): single-instrument reversion faces similar HFT competition at minute resolution
- Any future intraday pairs hypothesis (QQQ/IWM, SPY/IWM, GLD/SLV) should be treated with strong prior probability of failure in the 2018–2026 period

**Recommendation:** Pairs mean reversion hypotheses should be tested at **daily or multi-day resolution**, not intraday. The ETF cointegration relationship holds over days/weeks (see H04 pairs trading family at daily resolution); the intraday signal is crowded out.

### Indirect implication: The intraday spread shows momentum

The 86% stop-out rate and negative Sharpe suggest an **inverted signal**: entering in the direction of the spread deviation (intraday spread momentum) may have positive alpha. This is a structurally different hypothesis — cross-asset ETF momentum at the intraday scale.

**Research Director assessment:** This is a plausible hypothesis worth a separate investigation, but it requires:
1. A new hypothesis file (not an H63 variant — the family is retired)
2. Explicit signal design for spread momentum rather than mean reversion
3. Gate 1 backtest with full parameter sweep
4. The HFT competition concern applies here too: if spread momentum is real, it may exist only at timescales < 1 minute (making it inaccessible to our execution infrastructure)

This should be raised as a new hypothesis (H6x) under a separate issue if the board/CEO approves.

### What is unaffected

- **ED-SLIP-001 (ETF slippage calibration from QUA-173):** Still valid for other ETF strategies. The cost model (0.005% one-way for ultra-liquid ETFs) is correct; the issue was the absence of positive gross alpha, not excessive costs.
- **H59 (Intraday ORB on SPY):** H59 is a directional momentum strategy, not mean reversion — it is structurally orthogonal to H63. The intraday momentum finding actually supports H59's mechanism.
- **H64 (Leveraged ETF ORB + VIX filter):** Also directional momentum; unaffected.

---

## Gate 2 / OOS Queue Status

H63 and H63v2 were **never in the Gate 2 or OOS queue** — both were retired at Gate 1. No cleanup required for downstream stages.

---

## Knowledge Base Update

- `knowledge_base/mkb007_intraday_etf_pairs_cointegration.md` — status updated to RETIRED with forward pointer to this note
- `research/hypotheses/63_spy_qqq_intraday_pairs_mean_reversion.md` — status updated to RETIRED
- `research/hypotheses/63v2_spy_qqq_pairs_daily_baseline.md` — status updated to RETIRED

---

## Decision Record

**Date:** 2026-06-10
**Decision maker:** Research Director
**Rationale:** Both permitted iterations failed Gate 1 with empirical rejection at permutation p = 1.00. The hypothesis (intraday SPY/QQQ spread mean-reverts) is falsified by the 2018–2026 data. Structural analysis explains why: HFT has eliminated arbitrageable spread noise at minute resolution; remaining intraday spread deviations are directional flow-driven and trend, not revert.

**Family retirement is permanent.** No further SPY/QQQ intraday pairs mean-reversion iterations will be commissioned.
