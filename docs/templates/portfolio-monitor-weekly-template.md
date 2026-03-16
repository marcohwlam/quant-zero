# Portfolio Monitor — Weekly Risk Report

**Report date:** YYYY-MM-DD (Friday)
**Period covered:** YYYY-MM-DD to YYYY-MM-DD
**Prepared by:** Portfolio Monitor Agent
**Paperclip task:** [QUA-XXX](/QUA/issues/QUA-XXX)
**Output path:** `docs/monitoring/weekly-reports/YYYY-MM-DD.md`

---

## 1. Portfolio Summary

| Metric | Value | Status |
|--------|-------|--------|
| Total capital | $XX,XXX | — |
| Cash / stablecoins | $XX,XXX (XX%) | ✅ OK / ⚠️ WARN |
| Total exposure | XX% | ✅ ≤80% / 🔴 BREACH |
| Portfolio drawdown (peak) | X.X% | ✅ OK / ⚠️ WARN / 🔴 CRITICAL |
| Portfolio drawdown (8% halt threshold) | X.X% used of 8% | — |

**Portfolio status:** `NORMAL` | `WARNING (drawdown >6%)` | `HALT TRIGGER (drawdown >8%)`

---

## 2. Strategy-Level Performance

Repeat this block for each active strategy (paper and live).

### 2.1 [Strategy Name] — [paper | live]

| Metric | This week | Backtest expectation | Status |
|--------|-----------|---------------------|--------|
| Capital allocated | $X,XXX | — | — |
| Week P&L ($) | +/- $XXX | — | — |
| Week P&L (%) | +/- X.X% | — | — |
| Cumulative P&L since start ($) | +/- $XXX | — | — |
| Running drawdown | X.X% | IS max DD: X.X% | ✅ OK / ⚠️ WARN / 🔴 DEMOTION |
| Demotion threshold (1.5× IS max DD) | X.X% | X.X% | — |
| Rolling 20-day Sharpe | X.XX | OOS Sharpe: X.XX | ✅ / ⚠️ |
| Rolling 60-day Sharpe | X.XX | OOS Sharpe: X.XX | ✅ / ⚠️ |
| Win rate (if ≥30 trades) | XX.X% | Backtest: XX.X% | ✅ / ⚠️ |
| Trade count (week) | N | Expected: ~X/week | ✅ / ⚠️ |
| Realized vol (20-day, annualized) | X.X% | Backtest: X.X% | ✅ / ⚠️ |
| Vol ratio (realized / backtest) | X.XXx | Threshold: 1.5× | ✅ OK / 🔴 REDUCE POSITION |

**Strategy status:** `NORMAL` | `WARNING` | `DEMOTION TRIGGER` | `PAUSED`

**Threshold breaches this week:** [None / describe each breach with date and value]

---

## 3. Cross-Strategy Risk Metrics

_(Complete only when ≥2 strategies are active.)_

### 3.1 Correlation Matrix (30-day rolling returns)

| Strategy pair | 30-day correlation | Threshold | Status |
|--------------|-------------------|-----------|--------|
| [A] vs [B] | X.XX | 0.60 | ✅ / 🔴 BREACH |

**Combined exposure for correlated pairs (if any pair >0.6):**
- Pair [A + B]: $X,XXX combined (XX% of total capital) — Rule 12 cap: 25%

### 3.2 Portfolio SPY Beta

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Net portfolio SPY beta | X.XX | Alert >0.50 | ✅ / ⚠️ |

### 3.3 Diversification Multiplier (DMN)

| Metric | This week | Prior week | Trend | Status |
|--------|-----------|-----------|-------|--------|
| DMN | X.XX | X.XX | ↑/↓/→ | ✅ / ⚠️ (below 0.5) |

---

## 4. Drawdown Attribution

_(Complete only when total portfolio drawdown > 3%.)_

| Strategy | P&L contribution ($) | P&L contribution (%) | Notes |
|----------|---------------------|---------------------|-------|
| [Strategy A] | -$XXX | -X.X% | — |
| Cash drag | — | — | — |
| **Total** | **-$XXX** | **-X.X%** | — |

---

## 5. Alerts Fired This Week

List every alert threshold hit during the week. If none, state "None."

| Date | Strategy | Alert type | Value | Threshold | Action taken |
|------|----------|-----------|-------|-----------|-------------|
| YYYY-MM-DD | [name] | DEMOTION / VOL SPIKE / CORRELATION / etc. | X.X% | X.X% | Escalated to Risk Director |

---

## 6. Tail Risk (VIX > 25 trigger only)

_(Omit this section if VIX ≤ 25. Include when VIX > 25 per Risk Director instructions.)_

| Metric | Value |
|--------|-------|
| VIX (Friday close) | XX.X |
| Crisis scenario portfolio vol (monthly) | X.X% |
| Worst-case 1-month loss (99th pct) | X.X% / $X,XXX |
| 8% halt threshold | $X,XXX |
| Crisis scenario assessment | SAFE / WARNING / CRITICAL |

---

## 7. Next-Week Watch List

Items requiring elevated attention in the coming week.

- [ ] [item — e.g., strategy approaching demotion threshold]
- [ ] [item — e.g., correlation pair trending toward 0.6]

---

## 8. Data Quality Notes

Any data gaps, API errors, or incomplete metrics this week.

- [None / describe issue and impact on report completeness]

---

*Generated per [QUA-223](/QUA/issues/QUA-223). Template version: 2026-03-16.*
*Output path: `docs/monitoring/weekly-reports/YYYY-MM-DD.md` — one file per Friday.*
