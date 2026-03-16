# Hypotheses

Pre-backtest strategy ideas and rationale. Each file represents one strategy candidate.

## Naming Convention

`NN_strategy_name.md` — two-digit sequential number, snake_case strategy name.

## Required Sections per Hypothesis File

1. **Summary** — one-paragraph description
2. **Economic Rationale** — why should this edge exist?
3. **Market Regime Context** — when does this work / fail?
4. **Entry/Exit Logic** — clear enough to codify
5. **Asset Class & PDT/Capital Constraints** — fit for a $25K account
6. **Gate 1 Assessment** — which thresholds are likely to pass/miss?
7. **Recommended Parameter Ranges** — starting point for first backtest
8. **Alpha Decay Analysis** — signal half-life, IC decay curve, transaction cost viability
9. **Pre-Flight Gate Checklist** — all PF-1 through PF-4 gates (see below)

## Status Labels

- `DRAFT` — under development, not ready for backtesting
- `READY` — hypothesis is complete; ready to pass to Engineering Director
- `IN_BACKTEST` — Engineering Director is running the backtest
- `FINDINGS_AVAILABLE` — see findings/ for results

---

## Pre-Flight Gate Checklist (Mandatory — PF-1 through PF-4)

**All 4 gates must be checked before forwarding to Engineering Director. Failing any gate = reject or revise.**

Ref: CEO Directive QUA-181 (2026-03-16)

### Gate PF-1: Walk-Forward Trade Viability
**Requirement:** Estimated IS trade count ÷ 4 ≥ 30

- Monthly-rebalancing strategies with < 10 positions automatically fail this gate.
- Estimate trade count using expected rebalancing frequency × IS period length × average portfolio turnover.
- Root cause: H07c — monthly WF produced too few trades for robust IS/OOS split.

**Checklist item:** `[ ] PF-1 PASS — Estimated IS trade count: ___, ÷4 = ___ ≥ 30`

---

### Gate PF-2: Long-Only MDD Stress Test
**Requirement:** For any long-only equity strategy — estimated MDD < 40% in dot-com bust (2000–2002) AND GFC (2008–2009)

- Use SPY, QQQ, or relevant sector/index proxy for stress estimate.
- Strategies that are long-short in academic literature but converted to long-only automatically trigger this gate.
- Root cause: H16 — long-short Momentum+Vol stripped to long-only, structurally exposed to drawdown regimes.

**Checklist item:** `[ ] PF-2 PASS — Estimated dot-com MDD: ___%, GFC MDD: ___% (both < 40%)`

---

### Gate PF-3: Data Pipeline Availability
**Requirement:** All required data must be present in current pipeline (daily OHLCV via yfinance/Alpaca)

Automatic reject if strategy requires any of:
- Intraday CVD (H11 failure)
- Session VWAP (H13 failure)
- Options chains
- Tick data
- Any data source not already integrated

**Checklist item:** `[ ] PF-3 PASS — All data sources confirmed available in yfinance/Alpaca daily pipeline`

---

### Gate PF-4: Rate-Shock Regime Plausibility
**Requirement:** Written a priori rationale for why the strategy generates positive returns in the 2022 Rate-Shock regime

- "The backtest might capture it" is not sufficient justification.
- Long-biased equity strategies with no short/hedging mechanism automatically fail this gate.
- Must explain the mechanism by which the strategy survives rate-shock (e.g., short-selling, asset rotation to defensive, crypto non-correlation, etc.).
- Root cause: 2022 Rate-Shock is the most common IS failure regime across all strategies tested.

**Checklist item:** `[ ] PF-4 PASS — Rate-shock rationale: [written explanation here]`

---

## Hypothesis Class Diversification Mandate

**Effective 2026-03-16 (CEO Directive QUA-181)**

**Maximum 1 momentum-class hypothesis per TV Discovery / QC Discovery batch.**

Root cause: Momentum-class strategies (H05, H07, H07b, H07c, H08, H12, H16, H17) consumed 8 of 11 Gate 1 slots with zero passes. Directional equity momentum is structurally hostile in the 2018–2022 IS window.

Remaining slots in each batch must come from underrepresented classes:

| Priority | Class | Examples |
|---|---|---|
| 1 (proven pass class) | Pattern-based / binary event-driven | Zone touches, candlestick patterns, S/R confluences |
| 2 | Calendar / seasonal effects | Monthly anomalies, options expiration effects |
| 3 | Cross-asset relative value | SPY/TLT ratio, equity/credit spread signals |
| 4 | Event-driven | Post-earnings drift, FOMC drift, CPI release |

For QC academic literature searches: prioritize papers that are **explicitly long-only by design** — not long-short papers stripped to long-only.

---

## Family Iteration Limit

**Effective 2026-03-16 (CEO Directive QUA-181)**

**Maximum 2 Gate 1 iterations per hypothesis family before mandatory retirement.**

A third iteration requires both:
- Each prior iteration showed ≥ 0.1 IS Sharpe improvement, AND
- Research Director posts explicit written rationale for why the structural bottleneck is resolved

Root cause: TSMOM family consumed 3 Gate 1 slots (H07, H07b, H07c) with structural IS Sharpe ceiling of ~0.85 — architecturally below 1.0.
