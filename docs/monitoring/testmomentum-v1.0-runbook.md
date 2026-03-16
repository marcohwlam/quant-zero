# TestMomentum v1.0 — Paper Trading Monitoring Runbook

**Status:** Active — Paper Trading
**Gate 1 Approval:** [QUA-45](/QUA/issues/QUA-45) — Approved 2026-03-15
**Runbook Author:** Portfolio Monitor Agent
**Last Updated:** 2026-03-16

---

## 1. Strategy Overview

| Field | Value |
|---|---|
| Strategy | TestMomentum v1.0 |
| Asset Class | US Equities |
| Status | Paper Trading |
| Capital Allocated | $5,000 (paper) |
| Paper Trading Start | 2026-03-16 |
| Backtest Period | 2018-01-01 to 2023-12-31 (6 years) |
| Backtest IS Sharpe | 1.50 |
| Backtest OOS Sharpe | 1.10 |
| IS Max Drawdown | 12.0% |
| OOS Max Drawdown | 15.0% |
| Win Rate (backtest) | 55.0% |
| Trade Count (backtest) | 200 over 6 years (~33/year) |

---

## 2. Monitoring Metrics (Tracked Daily)

### 2.1 Daily P&L
- **Absolute $:** Dollar gain/loss vs. prior day closing equity
- **Percentage:** Daily return as % of allocated capital ($5,000)
- **Source:** Alpaca paper trading API (`ALPACA_PAPER_BASE_URL`)

### 2.2 Running Drawdown
- **Definition:** `(peak_equity - current_equity) / peak_equity`
- **Peak tracking:** Rolling peak of cumulative strategy equity since paper start
- **Frequency:** Updated daily at market close

### 2.3 Rolling Sharpe Ratio
- **20-day window:** Captures short-term performance regime
- **60-day window:** Captures medium-term consistency vs. backtest
- **Benchmark:** OOS Sharpe of 1.10 (annualized)
- **Alert trigger:** Rolling Sharpe deviates > 1 std dev (±0.20) from 1.10

### 2.4 Trade Win Rate
- **Backtest expectation:** 55% win rate
- **Alert trigger:** Win rate drops below 45% over 30+ completed trades
- **Window:** Rolling last-30-trades win rate

### 2.5 Trade Frequency
- **Backtest expectation:** ~33 trades/year (~0.6/week)
- **Monitoring:** Flag if weekly trade count deviates > 2× or < 0.5× expectation for 4 consecutive weeks

---

## 3. Alert Thresholds

| Alert | Condition | Action |
|---|---|---|
| ⚠️ WARNING | Drawdown ≥ 12% (= IS max DD) | Post warning comment to Risk Director task |
| 🔴 DEMOTION TRIGGER | Drawdown ≥ 18% (1.5× IS max DD) | Immediately escalate to Risk Director; flag for demotion per Rule 5 |
| 📉 DIVERGENCE ALERT | Rolling Sharpe deviates > 1σ (>1.30 or <0.90) | Escalate to Risk Director with deviation details |
| 🎯 WIN RATE ALERT | Win rate < 45% over 30+ trades | Escalate to Risk Director |
| 📊 FREQUENCY ALERT | Weekly trade count 2× or 0.5× expectation for 4 weeks | Flag in daily report; no immediate escalation |

---

## 4. Risk Calculations

### 4.1 Demotion Threshold Check

```python
from math import sqrt

# Constants for TestMomentum v1.0
BACKTEST_MAX_DRAWDOWN = 0.12
DEMOTION_MULTIPLIER = 1.5
DEMOTION_THRESHOLD = BACKTEST_MAX_DRAWDOWN * DEMOTION_MULTIPLIER  # = 0.18

def check_demotion(peak_value: float, current_value: float) -> dict:
    current_drawdown = (peak_value - current_value) / peak_value
    if current_drawdown >= DEMOTION_THRESHOLD:
        return {"status": "DEMOTION", "drawdown": current_drawdown, "threshold": DEMOTION_THRESHOLD}
    elif current_drawdown >= BACKTEST_MAX_DRAWDOWN:
        return {"status": "WARNING", "drawdown": current_drawdown, "threshold": BACKTEST_MAX_DRAWDOWN}
    return {"status": "OK", "drawdown": current_drawdown}
```

### 4.2 Sharpe Divergence Check

```python
BACKTEST_OOS_SHARPE = 1.10
BACKTEST_SHARPE_STD = 0.20
DIVERGENCE_THRESHOLD_Z = 1.0

def check_sharpe_divergence(rolling_sharpe: float) -> dict:
    z_score = (rolling_sharpe - BACKTEST_OOS_SHARPE) / BACKTEST_SHARPE_STD
    if abs(z_score) > DIVERGENCE_THRESHOLD_Z:
        return {"status": "ALERT", "z_score": z_score, "rolling_sharpe": rolling_sharpe}
    return {"status": "OK", "z_score": z_score}
```

### 4.3 Win Rate Check

```python
WIN_RATE_THRESHOLD = 0.45
WIN_RATE_MIN_TRADES = 30

def check_win_rate(wins: int, total_trades: int) -> dict:
    if total_trades < WIN_RATE_MIN_TRADES:
        return {"status": "INSUFFICIENT_DATA", "trades": total_trades}
    win_rate = wins / total_trades
    if win_rate < WIN_RATE_THRESHOLD:
        return {"status": "ALERT", "win_rate": win_rate, "threshold": WIN_RATE_THRESHOLD}
    return {"status": "OK", "win_rate": win_rate}
```

---

## 5. Data Sources

| Data | Source | Notes |
|---|---|---|
| Paper positions & P&L | Alpaca paper API (`ALPACA_PAPER_BASE_URL`) | Auth via env vars only — never hardcode |
| Historical prices | yfinance | For rolling Sharpe calculation |
| Portfolio peak equity | Local state tracking | Reset on strategy restart |

**Credentials:** All API credentials sourced exclusively from environment variables. See `/broker/.env.example`.

---

## 6. Daily Monitoring Checklist

Run each heartbeat:

1. **Fetch current equity** from Alpaca paper API
2. **Update peak equity** (rolling max since paper start)
3. **Calculate drawdown** → check vs. 12% (warning) and 18% (demotion trigger)
4. **Calculate daily return** and update rolling P&L log
5. **Calculate rolling Sharpe** (20-day and 60-day)
6. **Check win rate** from completed trades (if ≥ 30 trades)
7. **Check trade frequency** vs. backtest expectation
8. **Post daily report** comment to Risk Director monitoring task

---

## 7. Escalation Procedure

### Immediate Escalation (same heartbeat)
Triggered by demotion threshold, divergence alert, or win rate alert:

1. Post urgent comment to Risk Director's active monitoring task
2. Mark task as `blocked` with escalation note
3. Tag Risk Director (`@Risk Director`) in the comment

### Demotion Recommendation
When demotion trigger fires:
- Include: current drawdown %, date first breached, peak equity, current equity
- Recommend: Halt paper trading pending Risk Director + CEO review
- Never halt independently — recommendation only

---

## 8. Weekly Report Cadence

Every Friday heartbeat, include TestMomentum v1.0 metrics in the weekly risk summary:

- Week P&L ($ and %)
- Max intra-week drawdown
- Rolling 20-day and 60-day Sharpe
- Win rate (if ≥ 30 trades) or trade count progress
- Status vs. all alert thresholds
- Any threshold breaches during the week

---

## 9. Promotion Criteria (Paper → Live)

Monitoring does not gate promotion decisions — that is a CEO + Risk Director decision. However, Portfolio Monitor will flag to Risk Director when the following OOS thresholds are met:

- ≥ 90 days of paper trading with no demotion trigger hit
- Rolling 60-day Sharpe remains within 1σ of backtest OOS Sharpe (1.10)
- Win rate ≥ 50% over all completed trades
- No individual week with drawdown > 10%

Promotion requires a separate Gate 2 review — not within scope of this runbook.

---

## 10. Runbook Maintenance

- **Owner:** Portfolio Monitor Agent
- **Review trigger:** Any significant threshold breach, strategy parameter change, or capital reallocation
- **Update process:** Edit this file and post comment to Risk Director's monitoring task noting the change

---

*This runbook was created per [QUA-64](/QUA/issues/QUA-64) and is linked to strategy registry at `/broker/strategy_registry.json`.*
