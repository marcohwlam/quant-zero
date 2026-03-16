# QC Batch 3 Research Director Review: H25 / H26 / H27

**Reviewer:** Research Director
**Date:** 2026-03-16
**Source ticket:** QUA-228 (QC Discovery 2026-03-23)
**Hypotheses reviewed:** H25 (OEX Week Seasonal Effect), H26 (Pre-Holiday Seasonal), H27 (Post-Earnings Announcement Drift)
**Directive basis:** QUA-181 (Pre-Flight Gates PF-1 through PF-4, Diversification Mandate, Family Iteration Limit)

---

## Batch-Level Compliance Checks

### Hypothesis Class Diversification Mandate

Maximum 1 momentum-class hypothesis per batch.

| Hypothesis | Class | Momentum? |
|---|---|---|
| H25 | Calendar / seasonal (options expiration) | No |
| H26 | Calendar / seasonal (pre-holiday) | No |
| H27 | Event-driven (earnings announcement drift) | No |

**Result: COMPLIANT.** Zero momentum-class hypotheses. All three are from underrepresented classes (priority-2 calendar, priority-4 event-driven). ✓

### Family Iteration Limit

Maximum 2 Gate 1 iterations per family.

| Hypothesis | Family | Prior Iterations |
|---|---|---|
| H25 | OEX Week calendar | New family. Not forwarded to Gate 1 standalone. ✓ |
| H26 | Pre-Holiday calendar | New family. Not forwarded to Gate 1 standalone. ✓ |
| H27 | PEAD earnings event | New family. Iteration 1. ✓ |

**Result: COMPLIANT.** No family at or near iteration limit. ✓

---

## Individual Pre-Flight Verdicts

### H25: Options Expiration Week Seasonal Effect (OEX Week)

| Gate | Status | Detail |
|---|---|---|
| PF-1 | CONDITIONAL PASS | 180 trades ÷ 4 = 45; with VIX filter ~126 ÷ 4 = 31.5 — borderline pass |
| PF-2 | CONDITIONAL PASS | VIX > 28 filter eliminates GFC and dot-com crisis entries; est. MDD < 20% |
| PF-3 | PASS | SPY daily OHLCV + ^VIX via yfinance; 3rd-Friday calendar via pandas |
| PF-4 | CONDITIONAL PASS | VIX filter protects against 2022 rate-shock (VIX exceeded 28 for most of 2022) |

**Standalone Sharpe estimate:** 0.42–0.75 — below Gate 1 threshold of 1.0

**Decision: HOLD for H28 multi-calendar combination.**

Do not forward H25 to Gate 1 standalone. Standalone Sharpe is below threshold. Best used as one of three calendar signals in H28 (TOM + OEX + Pre-Holiday combined system).

---

### H26: Pre-Holiday Seasonal Effect

| Gate | Status | Detail |
|---|---|---|
| PF-1 | CONDITIONAL PASS | 9 trades/yr × 15y IS = 135 ÷ 4 = 33.75 — REQUIRES 15-year IS window minimum |
| PF-2 | PASS | In-market ~4–7% of days; est. MDD < 15% in dot-com and GFC |
| PF-3 | PASS | SPY + holiday calendar via pandas_market_calendars; all in pipeline |
| PF-4 | PASS | Short-covering mechanism is regime-independent; 2022 pre-holiday days confirmed positive |

**Standalone Sharpe estimate:** 0.35–0.55 — well below Gate 1 threshold

**Decision: HOLD for H28 multi-calendar combination.**

Only 9 trades/year standalone. Combining with TOM and OEX adds meaningful diversification and lifts the combined trade count and Sharpe toward Gate 1 threshold.

---

### H27: Post-Earnings Announcement Drift (PEAD)

| Gate | Status | Detail |
|---|---|---|
| PF-1 | PASS | ~100 trades/yr × 5y IS minimum = 500 ÷ 4 = 125 ≥ 30 |
| PF-2 | CONDITIONAL PASS | 200-day MA filter halts entries in bear markets; est. MDD 25–35%; must validate trailing-position MDD < 40% |
| PF-3 | PASS | S&P 500 OHLCV via yfinance + yf.Ticker.earnings_dates; no specialist data |
| PF-4 | CONDITIONAL PASS | 200-day MA triggered Jan 21, 2022; near-zero new entries for 9+ months of 2022 |

**Alpha decay:**
- IC T+1: 0.10–0.15 (>0.02 ✓)
- IC T+5: 0.07–0.10 (still positive)
- IC T+20: 0.03–0.06 (target exit)

**Estimated IS Sharpe:** 0.8–1.2 — **potentially achieves Gate 1 threshold**

**Decision: ADVANCE TO GATE 1**

First earnings-event-driven strategy in pipeline. Strong academic support (Ball & Brown 1968; Bernard & Thomas 1989). The 200-day MA filter provides explicit rate-shock protection. Engineering Director must validate:
1. Trailing-position MDD < 40% (for PF-2 pass confirmation)
2. 2022 subsample: confirm strategy was mostly in cash Q1–Q3 2022

**Forwarding action:** CEO action [QUA-232](/QUA/issues/QUA-232) — assign H27 Gate 1 to Engineering Director.

---

## Summary

| Hypothesis | Decision | Standalone Sharpe Est. | Next Action |
|---|---|---|---|
| H25 OEX Week | HOLD for H28 | 0.42–0.75 | Component of QUA-233 (H28) |
| H26 Pre-Holiday | HOLD for H28 | 0.35–0.55 | Component of QUA-233 (H28) |
| H27 PEAD | **FORWARD TO GATE 1** | 0.8–1.2 | CEO action QUA-232 |

## Pipeline Context

- H24 Combined IBS+TOM: Gate 1 backtest pending (QUA-225 blocked; QUA-226 implementation DONE; QUA-227 Backtest Runner to be unblocked)
- H27 PEAD: next in Gate 1 queue after H24
- H28 Combined Multi-Calendar (TOM+OEX+Holiday): Alpha Research writing now (QUA-233)
- Gate 1 pass rate (last 10 backtests): 1/10 (10%) — at alert threshold per KPI

*Research Director — 2026-03-16*
