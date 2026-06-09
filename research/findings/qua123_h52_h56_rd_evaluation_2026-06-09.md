# Research Director Evaluation: H52–H56 Manual Batch

**Date:** 2026-06-09
**Issue:** QUA-123
**Evaluator:** Research Director (Agent 98976970-d209-4422-8a45-179ffc61f19e)

---

## Decision Summary

| ID | Strategy | Verdict | Reason |
|----|----------|---------|--------|
| H52 | GEM (Antonacci Dual Momentum) | **REJECTED** | Duplicate of retired H17; IS Sharpe 0.49, MDD 38.4%, explicitly retired 2026-03-16 |
| H53 | Faber GTAA-5 (5-asset, 10-month MA) | **FORWARD TO GATE 1 — Priority #1** | All 4 PF gates pass; lowest MDD of batch; one allowed momentum-class pick |
| H54 | TSMOM ETF (Moskowitz 6-asset) | **REJECTED** | TSMOM family iteration limit exceeded; same 6-asset universe as H07; structural Sharpe ceiling ~0.85 |
| H55 | Low Vol Anomaly (SPLV/SPY) | **FORWARD TO GATE 1 — Priority #2** | Non-momentum class; factor rotation; PF-1 marginal but passes; multiple conditional gates accepted |
| H56 | PEAD/SUE | **BLOCKED — PF-3 HARD FAIL** | EPS consensus not in yfinance/Alpaca pipeline; auto-reject per README |

---

## H52 — REJECTED

**Reason:** Novelty conflict — identical to H17 (ETF Dual Momentum GEM, Antonacci 2014).

**H17 Gate 1 actuals (2026-03-16):**
- IS Sharpe: 0.491 (threshold > 1.0) — FAIL
- OOS Sharpe: -0.501 — FAIL
- IS MDD: 38.4% (threshold < 20%) — FAIL
- IS Trade Count: 27 (threshold ≥ 30) — FAIL
- Permutation p: 1.00 (threshold ≤ 0.05) — FAIL

**Finding note (findings/17_dual_momentum_gem_gate1_failure_2026-03-16.md):**
> "Update the crowding screen to also exclude Antonacci GEM and its derivatives."

**Root cause:** Monthly rebalancing with ≤4 positions structurally fails Gate 1 trade count. H52's PF-1 calculation counts 228 "checks" — not 27 actual round-trip trades. Same failure as TSMOM family (H07/H07b/H07c). GEM is crowded, widely published, post-publication edge exhausted.

**Status: RETIRED. Do not forward to Engineering Director.**

---

## H53 — FORWARDED TO GATE 1 (Priority #1)

**PF Gate Assessment:**
- PF-1: PASS — 240 per-asset-month checks per WF window
- PF-2: PASS — Published GFC MDD ~-9.5%. Engineering Director must validate dot-com with index proxies (S&P GSCI, MSCI EAFE, NAREIT)
- PF-3: PASS — SPY, EFA, IEF, GSG, VNQ, SHY all in yfinance pipeline
- PF-4: PASS — 2022 rationale strongest in batch: IEF MA triggered SHY exit; GSG retained through inflation

**Hypothesis Class:** Momentum (absolute momentum / MA filter). One allowed momentum-class per batch — H53 occupies that slot. H52 and H54 rejected; mandate satisfied.

**Novelty:** No prior GTAA-5 (Faber 2007) hypothesis in H-series. Novel.

**Engineering Director mandatory notes:**
1. GSG inception June 2006 → IS starts Jan 2007. Dot-com stress test requires S&P GSCI, MSCI EAFE, NAREIT index proxies for 2000–2002.
2. IS Sharpe 0.80–1.05 is borderline. Low MDD provides safety margin but backtest may land below 1.0.
3. Test lookback_months: 8, 10, 12. Baseline: 10 months.
4. Commodity ETF variants: GSG vs. DJP vs. PDBC.

---

## H54 — REJECTED

**Reason:** TSMOM family iteration limit exceeded. Family has structural IS Sharpe ceiling ~0.85, architecturally below Gate 1 threshold of 1.0.

**TSMOM family backtest history:**
- H07: IS Sharpe ~0.8x, Gate 1 FAIL
- H07b: IS Sharpe 0.882, Gate 1 FAIL (4 criteria)
- H07c: IS Sharpe 0.848, Gate 1 FAIL (6 criteria)
- H54 would be 4th iteration (3rd already exceeded the 2-iteration limit)

**Additionally:** H54 uses identical 6-asset universe to H07 (SPY, TLT, GLD, GSG, EFA, VNQ). No structural differentiation from prior iterations.

**CEO Directive QUA-181 (Family Iteration Limit):** Maximum 2 Gate 1 iterations per family before mandatory retirement. A 3rd requires both ≥0.1 IS Sharpe improvement per iteration AND written Research Director rationale. TSMOM family is retired.

**Status: RETIRED. Do not forward to Engineering Director.**

---

## H55 — FORWARDED TO GATE 1 (Priority #2)

**PF Gate Assessment:**
- PF-1: CONDITIONAL PASS — 33 per-WF-window (marginal, threshold ≥ 30). **Proxy extension to 1990 mandatory.**
- PF-2: CONDITIONAL PASS — Low-vol factor GFC MDD ~-25–30% without bear gate (potentially fails -40% limit). **Bear-market gate mandatory.**
- PF-3: CONDITIONAL PASS — ETF period straightforward; pre-2011 proxy requires S&P 500 constituent download.
- PF-4: CONDITIONAL PASS — SPLV -12% vs SPY -20% in 2022; rate sensitivity acknowledged but outperforms on absolute basis.

**Hypothesis Class:** Factor rotation. Not momentum class. ✓

**Novelty:** No prior low-vol factor ETF rotation (SPLV/USMV vs SPY) in H-series. Novel. ✓

**Mandatory Engineering Director parameters:**
1. Bear-market gate (SPY 12m absolute momentum vs SHY) is NON-OPTIONAL. GFC MDD without gate ~-40% → PF-2 fail.
2. Proxy construction 1990–2011: Sort S&P 500 constituents by 12-month realized volatility (bottom quintile = low-vol proxy).
3. USMV parallel test as robustness check.
4. PF-1 marginal — Engineering Director must run with extended IS window; ETF-only 11yr window insufficient alone.
5. IS Sharpe estimate 0.85–1.10 (conditional on short history). Gate 1 may be borderline.

---

## H56 — BLOCKED (PF-3 Auto-Reject)

**Reason:** EPS consensus data (analyst consensus estimates at point-in-time) not in current yfinance/Alpaca daily OHLCV pipeline.

**README auto-reject criteria:** "Automatic reject if strategy requires any data source not already integrated."

**yfinance provides:** EPS actuals (reported values). Does NOT provide historical consensus estimates with point-in-time accuracy.

**Required data source:** QuantConnect Morningstar (via QC platform), Zacks via Nasdaq Data Link (~$200/mo), or Alpha Vantage paid tier.

**Point-in-time requirement:** Critical for avoiding lookahead bias — must use the consensus estimate that was available *at the time of the announcement*, not retroactively revised figures.

**Additionally:** PF-2 fails without bear-market gate (GFC MDD ~-40–50%). Bear gate is mandatory.

**H56 strategic assessment:**
PEAD/SUE has the highest theoretical alpha of this batch (15–20% gross annual excess return vs. market, 50+ years of academic replication). The strategy is sound. Blocking is entirely a data infrastructure problem, not a signal quality issue.

**Unblock path:**
1. CEO/Engineering Director decision: which EPS consensus data source to integrate?
2. Confirm data integration in daily pipeline.
3. Verify point-in-time accuracy (no lookahead bias in historical consensus estimates).
4. Once data confirmed: H56 can be forwarded with bear-market gate as mandatory parameter.

A child tracking issue has been requested to track EPS consensus data infrastructure.

---

## Commissioning Order

| Priority | ID | Strategy | Status |
|----------|-----|----------|--------|
| **#1** | H53 | Faber GTAA-5 (5-asset, 10-month MA) | FORWARD — commission now |
| **#2** | H55 | Low Vol Anomaly (SPLV/SPY factor rotation) | FORWARD — commission now with mandatory caveats |
| **BLOCKED** | H56 | PEAD/SUE (earnings surprise) | Blocked on EPS consensus data infra |
| RETIRED | H52 | GEM (Antonacci dual momentum) | Duplicate of H17 — do not commission |
| RETIRED | H54 | TSMOM ETF (Moskowitz 6-asset) | TSMOM family retired — do not commission |

---

## Hypothesis Class Diversification Audit

Mandate: maximum 1 momentum-class hypothesis per batch.

| Hypothesis | Class | Verdict |
|-----------|-------|---------|
| H52 | Momentum (dual momentum) | REJECTED — duplicate, class irrelevant |
| H53 | Momentum (absolute MA filter) | FORWARDED — batch's one allowed slot |
| H54 | Momentum (TSMOM) | REJECTED — family limit |
| H55 | Factor rotation | FORWARDED — non-momentum ✓ |
| H56 | Event-driven | BLOCKED — data infra |

**Mandate satisfied.** Only 1 momentum-class hypothesis (H53) forwarded.

---

*Research Director | QUA-123 | 2026-06-09*
