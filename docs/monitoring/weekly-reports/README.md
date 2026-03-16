# Portfolio Monitor — Weekly Reports

**Owner:** Portfolio Monitor Agent
**Cadence:** Every Friday at US market close (4:00 PM ET)
**Template:** `docs/templates/portfolio-monitor-weekly-template.md`
**Established by:** [QUA-223](/QUA/issues/QUA-223) (Risk Director)

---

## Output Path Convention

Each weekly report is saved as:

```
docs/monitoring/weekly-reports/YYYY-MM-DD.md
```

where `YYYY-MM-DD` is the Friday date of the report.

**Example:** `docs/monitoring/weekly-reports/2026-03-20.md`

---

## Report Schema

Each weekly report must include all of the following sections:

| Section | Content | Required when |
|---------|---------|--------------|
| 1. Portfolio Summary | Total capital, cash%, exposure%, portfolio drawdown | Always |
| 2. Strategy-Level Performance | P&L, drawdown, Sharpe, win rate, vol ratio per strategy | Always (one block per active strategy) |
| 3. Cross-Strategy Risk Metrics | Correlation matrix, SPY beta, DMN | Always (when ≥2 strategies active; otherwise state "N/A — single strategy") |
| 4. Drawdown Attribution | Per-strategy P&L contribution | Only when portfolio drawdown > 3% |
| 5. Alerts Fired This Week | All threshold breaches during the week | Always (state "None" if clean) |
| 6. Tail Risk | Crisis scenario loss estimate | Only when VIX > 25 (Friday close) |
| 7. Next-Week Watch List | Elevated-attention items | Always |
| 8. Data Quality Notes | API errors, data gaps | Always (state "None" if clean) |

---

## Cadence Trigger

The Portfolio Monitor Agent produces the weekly report on its **Friday heartbeat**:

1. Pull current equity and positions from Alpaca paper/live API
2. Compute all weekly metrics (P&L, drawdown, Sharpe, win rate, vol ratio, correlations, DMN, SPY beta)
3. Populate template at `docs/templates/portfolio-monitor-weekly-template.md`
4. Save output to `docs/monitoring/weekly-reports/YYYY-MM-DD.md`
5. Post the report as a comment on the active Risk Director monitoring task (QUA-68 or successor)
6. @-mention `@Risk Director` if any Section 5 alerts fired during the week

---

## Key Thresholds (Quick Reference)

| Threshold | Value | Action |
|-----------|-------|--------|
| Strategy demotion trigger | 1.5× IS max drawdown | Escalate to Risk Director immediately |
| Portfolio drawdown warning | 6% | Alert Risk Director |
| Portfolio drawdown halt | 8% | Pause all live trading; escalate to CEO |
| Volatility ratio | >1.5× backtest vol | Position size reduction required (Rule 11 proposed) |
| Cross-strategy correlation | >0.6 (30-day rolling) | Combined exposure review required (Rule 12 proposed) |
| Net SPY beta | >0.50 | Flag in weekly report |
| Diversification multiplier | <0.50 | Escalate to Risk Director |
| VIX tail risk trigger | >25 | Include Section 6 tail risk analysis |

---

## Archive

| Report | Period | Key events |
|--------|--------|-----------|
| *(first report will be 2026-03-20)* | — | — |

---

*Established 2026-03-16 per [QUA-223](/QUA/issues/QUA-223).*
