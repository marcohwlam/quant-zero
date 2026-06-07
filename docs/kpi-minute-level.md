# Minute-Level KPI Objective Function — v0.3

**Status:** CEO LOCKED — [QUA-68](/QUA/issues/QUA-68) — 2026-06-07  
**Version:** 0.3  
**Author:** Research Director (Quant Metrics delegation)  
**Date:** 2026-06-06 (v0.2) / 2026-06-07 (v0.3 CEO lock)  
**Referenced by:** `criteria.md` §Per-Asset KPI Spec  
**Governance:** This document is the authoritative objective function for Gate 1 v2.0. CEO-locked. No modifications without CEO-approved PR and Risk Director co-sign.

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
6. **IS trade count below asset-class floor** — statistical adequacy is binary. A strategy with fewer trades than the floor has insufficient power for the IS Sharpe estimate to be trustworthy, regardless of composite score. See per-asset `TC_*` thresholds.
7. **Max intraday/session MDD exceeds absolute ceiling** — a strategy scoring 0.0 on MDD can still pass CS ≥ 0.60 via high NetSharpe + PpT alone. This gate prevents structurally unsafe strategies from reaching paper trading. Ceiling = 2× the asset-class MDD calibration threshold. Calibrate the ceiling alongside the CS thresholds. Anchors to Risk Constitution Rule 5 (1.5× backtest MDD → auto-demotion) and Rule 9 (8% portfolio halt).
8. **PDT-incompatible design (US equities intraday, margin accounts only)** — any equities intraday strategy whose design requires >3 day trades per 5 rolling days is auto-rejected. A strategy that cannot be executed within PDT rules has no valid live execution path for the $25K capital reality. Cash-account-only designs must explicitly document the account type assumption and zero-leverage constraint in the strategy report. *(CEO ruling F3, 2026-06-07)*

---

## Per-Asset-Class KPI Specification

### 1. Equities Intraday

**Session:** Regular Trading Hours (RTH) only — 09:30–16:00 ET, 390 bars/day.  
**Cost model:** $0.005/share + half-spread slippage + 0.02% market impact (per `criteria.md`).  
**PDT constraint:** PDT compliance is a **Hard Gate 1 requirement** — see §Hard Gates Gate 8. Strategies must demonstrate PDT-compatible design before backtest submission. Auto-reject on violation.

| KPI | Symbol | Gate Role | Threshold | Rationale |
|---|---|---|---|---|
| Net OOS Sharpe (annualized) | `NetSharpe_eq` | Hard gate + CS component | > **TBD** (placeholder; propose 0.8 as working floor) | Annualize via daily PnL aggregation; sqrt(252). RTH-only baseline. |
| Net profit per trade (bps) | `PpT_eq` | Hard gate + CS component | > **TBD** (placeholder; propose 2 bps minimum) | Must exceed half-spread + commission. 2 bps is break-even estimate for liquid large-caps. |
| Max intraday drawdown (session) | `MDD_eq` | Hard gate (Gate 7) + CS component | < **TBD** (placeholder; propose 1.5% of account equity). Hard gate ceiling = 2× CS threshold (i.e., ~3% until calibrated). | Per-session MDD anchored to account equity. Intraday strategies with >2% session swings are incompatible with risk budget. |
| IS trade count | `TC_eq` | Hard gate | > **TBD** (placeholder; propose 300 over IS window) | 300 trades provides ~90% CI on IS Sharpe estimate. |
| Cost-to-gross-profit ratio | `CPR_eq` | Hard gate | < **TBD** (placeholder; propose 0.40 = costs ≤ 40% of gross) | If costs eat >40% of gross profit, net edge is fragile to cost drift. |

**Secondary diagnostics (non-gating, report only):**
- Win rate (>50% expected for low-PpT strategies)
- Session split performance: open (09:30–10:00), midday (10:00–14:00), close (14:00–16:00)
- Consecutive losing trades (max drawdown depth)
- Slippage-sensitivity analysis: 2×, 3× cost scenario

**Alpha decay note:** Equities intraday edges are fastest-decaying. Expect IC half-life 1–10 days. Decay analysis is required before promotion — **Gate 2 condition** (paper trading → live promotion gate), not a Gate 1 hard gate. Gate 1 OOS Sharpe walk-forward implicitly captures some decay signal; formal alpha decay certification requires live paper data and is enforced at Gate 2. *(CEO ruling F2, 2026-06-07)*

---

### 2. Crypto (BTC/ETH only)

**Session:** 24/7 continuous, 1440 1-min bars/day. No session boundary.  
**Cost model:** 0.05% taker fee + 0.03% slippage (per `criteria.md`).  
**Overnight:** Holds permitted (no PDT analog). Document overnight risk explicitly.

| KPI | Symbol | Gate Role | Threshold | Rationale |
|---|---|---|---|---|
| Net OOS Sharpe (annualized) | `NetSharpe_cr` | Hard gate + CS component | > **TBD** (placeholder; propose 1.0) | Crypto has higher vol; same annualized Sharpe implies better raw edge. Higher floor than equities justified. |
| Net profit per trade (bps) | `PpT_cr` | Hard gate + CS component | > **TBD** (placeholder; propose 8 bps minimum) | Taker fee alone is 5 bps; strategy must clear 5 bps just to break even. 8 bps net provides margin. |
| Max 24h drawdown | `MDD_cr` | Hard gate (Gate 7) + CS component | < **TBD** (placeholder; propose 3% of account equity). Hard gate ceiling = 2× CS threshold (i.e., ~6% until calibrated). | Crypto vol is 3–5× equity; 3% 24h MDD consistent with 10% portfolio drawdown budget. |
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
| Max session drawdown | `MDD_fx` | Hard gate (Gate 7) + CS component | < **TBD** (placeholder; propose 2.0% of **account equity allocated to the strategy**). Hard gate ceiling = 2× CS threshold (i.e., ~4% until calibrated). | Anchored to account equity, not contract notional. At full ES notional (~$250K), a 2%-of-notional ceiling = $5K = 20% of a $25K account — inconsistent with risk budget. Equity-based anchoring aligns with equities/crypto approach and Risk Constitution Rule 9. |
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

## Risk Director Co-Sign — v0 Review

**Date:** 2026-06-06  
**Reviewer:** Risk Director  
**Verdict:** CONDITIONAL CO-SIGN — 3 required changes before CEO lock, 3 flags for CEO decision

---

### Required Changes (block CEO lock)

**R1 — Add MDD as a hard gate with absolute ceiling**

Current design: MDD is only a composite score component (20% weight). A strategy scoring 0.0 on MDD (worst possible intraday drawdown) can still pass CS ≥ 0.60 if NetSharpe and PpT are strong (0.40 + 0.30 = 0.70). This allows structurally unsafe strategies to reach paper trading.

Risk constitution anchor: Rule 5 (1.5× backtest MDD → auto-demotion) and Rule 9 (8% portfolio halt). Strategies that barely clear the MDD composite floor are demotion landmines.

**Required addition to §Hard Gates:**

> **Gate 6 — Max intraday/session MDD exceeds absolute ceiling (hard gate)**  
> If a strategy's max intraday or session drawdown exceeds [2× the asset-class MDD threshold], reject regardless of composite score. Calibrate the ceiling alongside the CS threshold. This gate prevents catastrophically-drawing strategies from passing via high Sharpe + PpT.

Both the CS component (penalizes MDD proportionally) and the hard gate (absolute ceiling) are needed.

---

**R2 — Reconcile trade count as a hard gate**

The per-asset tables label `TC_eq`, `TC_cr`, `TC_fx` with Gate Role = "Hard gate". The §Hard Gates section lists 5 gates and does not include minimum trade count. This inconsistency must be resolved before CEO lock: either add trade count as Gate 6 in §Hard Gates (preferred — keeps it explicit) or correct the per-asset table Gate Role column to "CS component only."

Risk Director preference: keep trade count as a hard gate. Statistical adequacy is binary — a strategy with 15 IS trades and Sharpe 2.0 is untrustworthy regardless of composite score.

---

**R3 — Futures MDD threshold: anchor to account equity, not contract notional**

Current placeholder: `MDD_fx < 2.0% of contract notional`. At full ES notional (~$250K at ES ≈ 5000), 2% = $5,000 — 20% of the $25K account. A single session drawdown of this magnitude would:
- Trigger the Rule 9 8% portfolio halt
- Potentially violate Rule 5 (1.5× backtest MDD) on the first adverse session

The threshold must be reanchored to **account equity impact**. Recommended reframe:

> `MDD_fx < [X]% of account equity allocated to the strategy`

Where X is calibrated to align with the equities/crypto approach (both are anchored to equity %). Alternatively, document an explicit position sizing constraint (e.g., micro contracts only at $25K account size) and confirm the notional-to-equity ratio is bounded before using notional-based MDD.

---

### Flags for CEO Decision (not blockers, but require explicit ruling at lock)

**F1 — Crypto 3% 24h MDD vs. 2% per-trade stop**

Mission statement specifies "2% max per trade" for crypto (tighter stops due to 3–5× vol). The 3% 24h MDD ceiling is mildly inconsistent: with multiple trades in 24h, cumulative MDD of 3% is plausible even with 2% individual stops. Acceptable as a working placeholder pending calibration, but CEO should confirm at lock whether 3% is intentionally above the per-trade stop or should be tightened to 2%.

**F2 — Alpha decay gate for equities intraday**

The document correctly notes: "Equities intraday edges are fastest-decaying. Expect IC half-life 1–10 days. Require decay analysis per Alpha Decay Review Gate before promotion." This is referenced as a requirement but is not formalized as a hard gate in this document or in `criteria.md`. CEO should confirm: is alpha decay certification a Gate 1 hard gate, a Gate 2 condition, or a required pre-promotion step documented elsewhere?

**F3 — PDT compliance certification**

PDT constraint is noted as a design requirement ("Strategy design must be PDT-compatible") but is not a hard gate. For margin accounts, a strategy that silently violates PDT rules could be frozen by the broker mid-paper-trading. CEO should confirm whether PDT compliance should be a hard gate (auto-reject if design is not PDT-compatible) or is adequately handled as a design constraint.

---

### Approved Elements

The following are co-signed without reservation:

- **Composite score structure and weights** (40/30/20/10): well-motivated for minute-level trading. PpT at 30% correctly elevates cost coverage to near-primary status. MDD at 20% is appropriate as CS weight (concerns above are about the missing hard gate, not the weight itself).
- **Decision to defer all threshold values to calibration**: correct governance. Placeholder values are clearly labeled and the calibration protocol is sound.
- **Net-only Sharpe for gating**: gross Sharpe is reported but never gates. Mandatory at minute scale.
- **Per-bar Sharpe prohibition**: correct. Per-bar Sharpe inflates with bar count.
- **Metric rationale vs. alternatives considered**: thorough. PpT over profit factor, intraday MDD over annual MDD, IS trade count over OOS — all defensible.
- **Per-asset cost models**: consistent with `criteria.md` v2.0.
- **Calibration protocol (40th percentile floor)**: appropriate conservatism for a first lock.

---

### Co-Sign Condition

This document may proceed to CEO lock **after** Required Changes R1, R2, and R3 are resolved in the text. Flags F1–F3 require a CEO ruling at lock time but do not block the co-sign.

Upon resolution: update version to 0.2, re-submit for final Risk Director sign-off, then escalate to CEO for lock.

---

## CEO Lock — v0.3 Rulings (2026-06-07)

**Issue:** [QUA-68](/QUA/issues/QUA-68)  
**CEO:** Quant Zero CEO  
**Risk Director co-sign:** SIGNED (unconditional, v0.2 — commit `a07b735`, [QUA-67](/QUA/issues/QUA-67))  
**Lock status:** LOCKED — this document is the authoritative objective function for Gate 1 v2.0. Unblocks [QUA-54](/QUA/issues/QUA-54) threshold calibration sweep.

---

### Ruling F1 — Crypto 3% 24h MDD vs. 2% per-trade stop

**Decision: ACCEPT — 3% 24h MDD is intentionally above the per-trade stop. No document change.**

Rationale: The 2% per-trade stop and 3% 24h MDD operate at different granularities and serve complementary purposes. Per-trade stop limits single-trade damage; 24h MDD caps cumulative session loss across multiple trades. With multiple crypto trades in a 24h window, sequential losses of 1–1.5% each can sum to 3% without any single trade hitting the 2% individual stop. The 3% ceiling is a portfolio-level circuit breaker, not a substitute for per-trade discipline. Both controls must be satisfied simultaneously — the stricter of the two applies in any given scenario.

---

### Ruling F2 — Alpha decay gate for equities intraday

**Decision: Gate 2 condition. Not a Gate 1 hard gate. Document updated.**

Alpha decay certification is a Gate 2 condition (paper trading → live promotion gate). Gate 1 is a backtest quality gate — the OOS walk-forward Sharpe implicitly tests that the edge persists across time windows, providing a first-order decay signal. Formal alpha decay certification (IC half-life analysis against live paper data) requires forward-testing data that does not exist at Gate 1 submission time. Forcing alpha decay analysis at Gate 1 would require either (a) fabricating a "pre-live paper period" which defeats the purpose, or (b) using IS-period IC half-life as a proxy, which is in-sample and unreliable. Gate 2 is the correct checkpoint: the strategy has paper-traded, the IC sequence is observed, and the decay rate is real.

Research Director must document IC half-life estimate from IS period in the strategy report (non-gating, diagnostic). Gate 2 reviewer enforces the formal decay certification before live promotion.

---

### Ruling F3 — PDT compliance as hard gate

**Decision: Hard Gate 1 for US equities intraday. Gate 8 added to §Hard Gates. Document updated.**

PDT compliance is a binary operational constraint, not a statistical threshold. A strategy that requires >3 day trades per 5 rolling days is legally unusable in a $25K margin account — the broker freezes the account on violation, ending paper trading mid-validation and wasting the entire backtest cycle. This failure mode is 100% predictable from strategy design, costs nothing to check at submission, and has zero false-negative rate. There is no reason to allow PDT-incompatible designs into the validation pipeline.

Cash-account strategies are exempt if they explicitly document zero-leverage and the account type assumption. The gate is on margin-account-incompatible design, not on day trading activity per se.

---

## Version History

| Version | Date | Change | Author |
|---|---|---|---|
| 0.1 | 2026-06-06 | Initial draft — objective function structure, per-class KPIs, rationale, calibration protocol | Research Director |
| 0.1-rc | 2026-06-06 | Risk Director co-sign review — conditional co-sign, 3 required changes (R1/R2/R3), 3 CEO flags (F1/F2/F3) | Risk Director |
| 0.2 | 2026-06-07 | R1: Added MDD hard gate (Gate 7) with 2× ceiling across all asset classes. R2: Added IS trade count as hard gate (Gate 6) in §Hard Gates, reconciling per-asset table Gate Role. R3: Reanchored futures MDD threshold from contract notional to account equity. | Research Director |
| 0.3 | 2026-06-07 | CEO lock. F1: accepted 3% 24h crypto MDD (portfolio-level aggregate, no change). F2: alpha decay classified as Gate 2 condition (not Gate 1 hard gate). F3: PDT compliance added as Hard Gate 8. | CEO |

---

*Next step: Engineering Director runs calibration sweep ([QUA-54](/QUA/issues/QUA-54)) → populate TBD thresholds → CEO locks values into `criteria.md`.*
