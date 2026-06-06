# Minute-Level KPI Objective Function — v0 Draft

**Status:** DRAFT — pending Risk Director co-sign and CEO lock  
**Version:** 0.1  
**Author:** Research Director (Quant Metrics delegation)  
**Date:** 2026-06-06  
**Referenced by:** `criteria.md` §Per-Asset KPI Spec  
**Governance:** Risk Director must co-sign before CEO locks values into `criteria.md`.

---

## Purpose

This document defines the objective function that balances **return** and **stability** for minute-level strategy evaluation across all three asset classes: equities intraday, crypto, and futures.

At daily resolution, the dominant failure mode is overfitting to in-sample noise. At minute resolution, the dominant failure mode is **transaction cost destruction** — a strategy that is grossly profitable can be net-negative after realistic slippage and commissions. This shifts the objective function: cost-adjusted return is primary; raw Sharpe without cost realism is meaningless.

---

## Core Objective Function

The objective is to maximize a composite score (CS) that rewards net risk-adjusted return, punishes cost drag, penalizes deep intraday drawdowns, and ensures statistical adequacy:

```
CS = 0.40 × NetSharpe_norm
   + 0.30 × ProfitPerTrade_norm
   + 0.20 × Stability_norm
   + 0.10 × TradeAdequacy_norm
```

### Component Definitions

| Component | Weight | Formula | Rationale |
|---|---|---|---|
| `NetSharpe_norm` | 40% | Normalized Net OOS Sharpe (post-cost, annualized via daily aggregation → sqrt(252)) | Primary return-quality signal. Net-only; gross Sharpe is diagnostic, never gates. |
| `ProfitPerTrade_norm` | 30% | Normalized net profit per trade in bps after all costs | At minute scale, each trade must cover spread + slippage + commission. Low PpT → strategy dies on cost. |
| `Stability_norm` | 20% | `1 - (MaxIntradayMDD / MDD_ceiling)` — inverted drawdown score | Intraday MDD reveals whether the strategy can survive adverse sessions without blowing stop-limits. |
| `TradeAdequacy_norm` | 10% | `min(1.0, TradeCount_IS / min_trades_floor)` — capped at 1.0 | Ensures statistical power. A strategy with 15 IS trades and Sharpe 2.0 is untrustworthy. |

**Normalization:** Each component is min-max normalized to [0, 1] against the asset-class calibration range. Calibration values are PLACEHOLDER until Engineering Director runs live 2022–2024 data (see §Calibration Protocol).

**Pass threshold:** CS ≥ 0.60 is the proposed Gate 1 composite pass bar (subject to calibration and CEO lock).

---

## Hard Gates (any single flag = reject regardless of CS)

These operate before the composite score is computed:

1. **Net OOS Sharpe < asset-class floor** — composite score irrelevant if net edge is below floor.
2. **Cost-to-gross-profit ratio ≥ asset-class ceiling** — strategy is economically non-viable.
3. **Same-bar fill assumption** — latency cheating; automatic disqualification (per `criteria.md`).
4. **Look-ahead bias detected** — rewrite and re-test from scratch.
5. **Gross-profitable but net-negative** — no exceptions; cost model is non-negotiable.

---

## Per-Asset-Class KPI Specification

### 1. Equities Intraday

**Session:** Regular Trading Hours (RTH) only — 09:30–16:00 ET, 390 bars/day.  
**Cost model:** $0.005/share + half-spread slippage + 0.02% market impact (per `criteria.md`).  
**PDT constraint:** Strategy design must be PDT-compatible (≤3 day trades per 5-day rolling window in margin accounts, OR cash account with no leverage).

| KPI | Symbol | Gate Role | Threshold | Rationale |
|---|---|---|---|---|
| Net OOS Sharpe (annualized) | `NetSharpe_eq` | Hard gate + CS component | > **TBD** (placeholder; propose 0.8 as working floor) | Annualize via daily PnL aggregation; sqrt(252). RTH-only baseline. |
| Net profit per trade (bps) | `PpT_eq` | Hard gate + CS component | > **TBD** (placeholder; propose 2 bps minimum) | Must exceed half-spread + commission. 2 bps is break-even estimate for liquid large-caps. |
| Max intraday drawdown (session) | `MDD_eq` | CS component | < **TBD** (placeholder; propose 1.5% of equity) | Per-session MDD. Intraday strategies with >2% session swings are incompatible with risk budget. |
| IS trade count | `TC_eq` | Hard gate | > **TBD** (placeholder; propose 300 over IS window) | 300 trades provides ~90% CI on IS Sharpe estimate. |
| Cost-to-gross-profit ratio | `CPR_eq` | Hard gate | < **TBD** (placeholder; propose 0.40 = costs ≤ 40% of gross) | If costs eat >40% of gross profit, net edge is fragile to cost drift. |

**Secondary diagnostics (non-gating, report only):**
- Win rate (>50% expected for low-PpT strategies)
- Session split performance: open (09:30–10:00), midday (10:00–14:00), close (14:00–16:00)
- Consecutive losing trades (max drawdown depth)
- Slippage-sensitivity analysis: 2×, 3× cost scenario

**Alpha decay note:** Equities intraday edges are fastest-decaying. Expect IC half-life 1–10 days. Require decay analysis per Alpha Decay Review Gate before promotion.

---

### 2. Crypto (BTC/ETH only)

**Session:** 24/7 continuous, 1440 1-min bars/day. No session boundary.  
**Cost model:** 0.05% taker fee + 0.03% slippage (per `criteria.md`).  
**Overnight:** Holds permitted (no PDT analog). Document overnight risk explicitly.

| KPI | Symbol | Gate Role | Threshold | Rationale |
|---|---|---|---|---|
| Net OOS Sharpe (annualized) | `NetSharpe_cr` | Hard gate + CS component | > **TBD** (placeholder; propose 1.0) | Crypto has higher vol; same annualized Sharpe implies better raw edge. Higher floor than equities justified. |
| Net profit per trade (bps) | `PpT_cr` | Hard gate + CS component | > **TBD** (placeholder; propose 8 bps minimum) | Taker fee alone is 5 bps; strategy must clear 5 bps just to break even. 8 bps net provides margin. |
| Max 24h drawdown | `MDD_cr` | CS component | < **TBD** (placeholder; propose 3% of equity) | Crypto vol is 3–5× equity; 3% 24h MDD consistent with 10% portfolio drawdown budget. |
| IS trade count | `TC_cr` | Hard gate | > **TBD** (placeholder; propose 200 over IS window) | 24/7 window generates more bars; 200 trades sufficient for significance. |
| Cost-to-gross-profit ratio | `CPR_cr` | Hard gate | < **TBD** (placeholder; propose 0.35) | Stricter than equities because crypto cost model is a percentage (not fixed per share); scales with notional. |

**Secondary diagnostics (non-gating):**
- Performance by time-of-day (UTC buckets: Asia, Europe, US sessions)
- BTC vs. ETH split if strategy trades both
- Weekend vs. weekday performance (crypto exhibits structural calendar effects)
- Funding rate impact if perpetual futures used

---

### 3. Futures

**Session:** Contract-dependent. ES: 09:30–16:15 ET (RTH); extended electronic session also relevant. CL: near-24h. Document session assumption explicitly per strategy.  
**Cost model:** Per-contract commission + 1 tick slippage (per `criteria.md`). Actual $ cost depends on contract (ES tick = $12.50; CL tick = $10).  
**Leverage:** Futures are inherently leveraged. All Sharpe and PpT metrics computed on notional exposure, not margin.

| KPI | Symbol | Gate Role | Threshold | Rationale |
|---|---|---|---|---|
| Net OOS Sharpe (annualized) | `NetSharpe_fx` | Hard gate + CS component | > **TBD** (placeholder; propose 0.9) | Between equities and crypto; futures have moderate inherent leverage that amplifies both edges and drawdowns. |
| Net profit per trade (ticks or bps) | `PpT_fx` | Hard gate + CS component | > **TBD** (placeholder; propose 0.5 ticks net after commission) | Absolute tick-based floor: must exceed 1 round-trip tick cost. Bps equivalent also tracked for cross-class comparison. |
| Max session drawdown (per contract) | `MDD_fx` | CS component | < **TBD** (placeholder; propose 2.0% of contract notional) | Futures session drawdowns compound with leverage. 2% on notional is risk-budget-consistent. |
| IS trade count | `TC_fx` | Hard gate | > **TBD** (placeholder; propose 150 over IS window) | Futures strategies often lower-frequency than crypto; 150 IS trades is statistical floor. |
| Cost-to-gross-profit ratio | `CPR_fx` | Hard gate | < **TBD** (placeholder; propose 0.35) | Same as crypto; commission + tick slippage is material per trade. |

**Secondary diagnostics (non-gating):**
- Performance split: RTH session vs. extended electronic (if strategy trades both)
- Roll-period performance (near contract expiry edge decay)
- Intraday margin utilization (ensure strategy fits $25K account margin rules)
- Correlation with equity IS performance (avoid double-counting equity exposure via ES)

---

## Metric Rationale vs. Alternatives Considered

| Metric | Chosen | Alternative Considered | Why Chosen |
|---|---|---|---|
| **Net OOS Sharpe** | Yes | Gross OOS Sharpe | Gross ignores cost. At minute level, a gross Sharpe of 2.0 can be net 0.3. Gross is reported but never gates. |
| **Profit per trade (bps)** | Yes | Profit factor (gross profit / gross loss) | PpT is cost-anchored; profit factor is not. PpT directly answers "does each trade cover costs?" — the core minute-level question. |
| **Max intraday MDD** | Yes | Annual MDD | Intraday MDD reveals session-level risk that annual MDD masks. A strategy with 30% annual MDD may have 5% same-session swings that hit intraday stops. |
| **IS trade count floor** | Yes | OOS trade count | IS trade count is observable before the split; it governs whether IS statistics are trustworthy. OOS trade count is a secondary diagnostic. |
| **Cost-to-gross-profit ratio** | Yes | Net margin % | Cost ratio is strategy-agnostic (works across asset classes). Net margin % depends on position sizing. Cost ratio isolates the cost-as-signal-killer dynamic. |
| **Composite Score (weighted)** | Yes | Lexicographic ranking | Weighted composite allows a high-Sharpe strategy with moderate trade count to pass; lexicographic ranking would reject it at the trade count step. Composite reflects real tradeoffs. |

---

## Calibration Protocol (Thresholds Are PLACEHOLDERS)

All threshold values marked **TBD** above must be calibrated against real 2022–2024 data before CEO lock:

1. **Engineering Director** runs a calibration sweep across the IS window (2022-01 to 2024-12) using representative baseline strategies for each asset class.
2. Calibration outputs: distribution of each KPI metric across strategy population.
3. **Quant Metrics / Research Director** proposes thresholds at the 40th percentile of the strategy distribution (i.e., gate rejects bottom 40%).
4. **Risk Director co-signs** proposed thresholds before CEO lock.
5. CEO locks thresholds into `criteria.md` and this document simultaneously.

Until calibration: use placeholder values in brackets above as working estimates only. Do not use these values to promote or reject strategies — the Gate 1 §Quantitative Thresholds section in `criteria.md` governs.

---

## Composite Score Normalization Reference (Post-Calibration)

Once calibration data is available, populate this table:

| Asset Class | KPI | Min (0.0 score) | Max (1.0 score) |
|---|---|---|---|
| Equities | NetSharpe | TBD | TBD |
| Equities | PpT (bps) | TBD | TBD |
| Equities | MDD (%) | TBD (worst) | TBD (best) |
| Equities | TradeCount | TBD (floor) | TBD (ceiling) |
| Crypto | NetSharpe | TBD | TBD |
| Crypto | PpT (bps) | TBD | TBD |
| Crypto | MDD (%) | TBD | TBD |
| Crypto | TradeCount | TBD | TBD |
| Futures | NetSharpe | TBD | TBD |
| Futures | PpT (ticks) | TBD | TBD |
| Futures | MDD (%) | TBD | TBD |
| Futures | TradeCount | TBD | TBD |

---

## Version History

| Version | Date | Change | Author |
|---|---|---|---|
| 0.1 | 2026-06-06 | Initial draft — objective function structure, per-class KPIs, rationale, calibration protocol | Research Director |

---

*Next step: Risk Director co-sign → CEO lock → populate TBD thresholds after calibration sweep.*
