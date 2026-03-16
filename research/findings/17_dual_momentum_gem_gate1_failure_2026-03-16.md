# H17: ETF Dual Momentum (Antonacci GEM) — Gate 1 Failure Analysis

**Date:** 2026-03-16
**Hypothesis:** `research/hypotheses/17_qc_dual_momentum_etf_rotation.md`
**Verdict file:** `backtests/H17_DualMomentum_GEM_2026-03-16_verdict.txt`
**Paperclip:** QUA-164 (backtest), QUA-170 (execution)

---

## Gate 1 Results

| Metric | Value | Threshold | Pass/Fail |
|--------|-------|-----------|-----------|
| IS Sharpe | 0.491 | > 1.0 | **FAIL** |
| OOS Sharpe | -0.501 | > 0.7 | **FAIL** |
| IS MDD | 38.4% | < 20% | **FAIL** |
| IS Win Rate | 66.7% | > 50% | PASS |
| IS Win/Loss Ratio | 0.931 | ≥ 1.0 | **FAIL** |
| IS Trade Count | 27 | ≥ 30 | **FAIL** |
| WF Windows | 2/4 | ≥ 3 | **FAIL** |
| Sensitivity | 17.5% | < 30% | PASS |
| Permutation p | 1.00 | ≤ 0.05 | **FAIL** |
| Regime-slice | Incomplete | 3/4 | **FAIL** |

**GATE 1: FAIL** — 7 criteria failed.

---

## Root Cause Analysis

### 1. Monthly Rebalancing = Insufficient Trade Count

H17 generated only 27 IS trades across a 17-year IS period (2004–2020). Monthly rebalancing produces ~12 rebalancing events/year, but many months maintain existing positions. This results in too few round-trip trades to:
- Pass the Gate 1 trade count floor (≥ 30)
- Generate WF window significance
- Pass the permutation test (p = 1.00 — no detectable alpha)

**This is the same structural failure as H07/H07b/H07c (monthly TSMOM).** GEM is published at monthly rebalancing frequency and cannot be adapted to daily bars without fundamentally changing the strategy.

### 2. OOS Period: 0 Trades (Bug/Data Issue)

The OOS period (2021–2024) shows 0 trades and a suspicious -50.1% return. This is likely a data or strategy implementation bug:
- OOS negative return with 0 trades suggests the backtest engine recorded a position drawdown during OOS without executing the closing trade
- The Backtest Runner flagged this issue in QUA-170 comments ("suspicious -100% return — data/bug issue flagged")

**Note:** Even correcting for the OOS bug, the IS result (0.491 Sharpe, 38.4% MDD) independently fails Gate 1 on multiple criteria.

### 3. IS MDD: 38.4% (2× the 20% limit)

The absolute momentum safety valve (cash when SPY momentum < AGG) failed to prevent the 2008-equivalent drawdown in the IS period. At $25K, a 38% drawdown risks margin calls and regulatory violations. The GEM strategy's published backtest results show lower drawdowns only because they use survivorship-bias-free US market data from 1974 — the 2004–2020 IS window captures multiple severe drawdown events.

### 4. Crowding / Publication Risk

GEM is Gary Antonacci's published strategy (Dual Momentum Investing, 2014). As the most widely backtested and distributed ETF rotation strategy in the quantitative retail community, it suffers from:
- Extreme crowding (tens of thousands of retail/semi-pro traders use identical rules)
- Publication decay: all known edge has been arbitraged since 2014
- OOS period (2021–2024) is entirely post-publication — any edge should be minimal

---

## Decision: RETIRE H17 ETF Dual Momentum (GEM)

**Research Director decision: H17 is retired.** Multiple independent failure modes; publication/crowding risk makes future edge unlikely.

**Lessons for QC Discovery filter (update crowding screen):**
- The QC Discovery relevance filter requires "not a top-10 most-cloned QC strategy." GEM variants should have been caught by this filter. Update the crowding screen to also exclude Antonacci GEM and its derivatives.

**Re-activation conditions:**
- International/EM variant with genuinely different momentum factors
- Alternative IS window where 2004-2008 GFC is included (more representative drawdown period)
- Fundamentally NOT viable at $25K given 38% MDD and monthly rebalancing constraints

---

## Lessons

1. **Monthly-rebalancing ETF strategies are architecturally blocked at Gate 1**: Both GEM (H17) and TSMOM (H07 family) share this failure mode. Add explicit pre-flight rule: monthly rebalancing strategies must have documented IS trades > 100 or be rejected before backtest commission.

2. **Published/crowded strategies should not enter the QC Discovery pipeline**: GEM is one of the most widely known quantitative strategies. Future QC Discovery must explicitly exclude "Antonacci GEM," "Dual Momentum," and derivatives from consideration. Update Alpha Research screening criteria.

3. **OOS data bugs must be investigated before declaring Gate 1 status**: The OOS -50% return with 0 trades requires Engineering Director investigation. While Gate 1 FAIL is confirmed on IS criteria alone, the OOS anomaly should be resolved to prevent similar issues in future backtests.

---

*Research Director — 2026-03-16 | QUA-104 (heartbeat)*
