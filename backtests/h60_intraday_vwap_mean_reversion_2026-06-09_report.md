# H60 Gate 1 Backtest Report

**Strategy:** Intraday VWAP Mean Reversion
**Date:** 2026-06-09
**Issue:** QUA-166
**Instrument (primary):** SPY
**Instrument (robustness):** QQQ
**Hypothesis:** research/hypotheses/60_intraday_vwap_mean_reversion.md (v1.2)

---

## Gate 1 Verdict: FAIL

### Failures
- IS Sharpe -15.044 < 1.0 threshold
- OOS Sharpe -7.969 < 0.7 threshold
- WF stability 0/6 < 3/6

---

## Key Metrics (SPY Primary)

| Metric | IS (2022–2023) | OOS (WF avg) | Gate |
|---|---|---|---|
| Net Sharpe (annualized) | -15.044 | -7.969 | IS > 1.0, OOS > 0.7 |
| Max Drawdown | -5.2% | -2.0% | < -20% |
| Win Rate | 17.0% | 15.3% | — |
| Trade Count | 1068 | 352 | IS ≥ 100 |
| Profit Factor | 0.134 | 0.110 | — |
| Avg P&L / trade (bps) | -9.51 | -9.82 | > 0 |
| Avg bars held | 10.2 | 9.9 | — |
| Total return | -5.20% | -2.02% | — |

### WF Stability
- Profitable OOS windows: 0/6
- Stability fraction: 0%
- Gate (≥ 3/6): FAIL

### Walk-Forward Window Detail

| Window | IS Sharpe | OOS Sharpe | OOS Trades | OOS Win% |
|---|---|---|---|---|
| W1 IS 2022-01–2022-03 → OOS 2022-04 | -19.767 | -20.422 | 58 | 24.1% |
| W2 IS 2022-05–2022-07 → OOS 2022-08 | -13.496 | -30.061 | 62 | 14.5% |
| W3 IS 2022-09–2022-11 → OOS 2022-12 | -14.503 | -22.892 | 59 | 17.0% |
| W4 IS 2023-01–2023-03 → OOS 2023-04 | -21.650 | -26.975 | 56 | 12.5% |
| W5 IS 2023-05–2023-07 → OOS 2023-08 | -31.086 | -22.990 | 65 | 18.5% |
| W6 IS 2023-09–2023-11 → OOS 2023-12 | -26.636 | -30.486 | 52 | 3.9% |

---

## Robustness (QQQ)

| Metric | IS Sharpe | OOS Sharpe | IS Trades |
|---|---|---|---|
| QQQ | -10.043 | -6.636 | 1004 |

---

## Parameters (Baseline — committed before IS optimization)

- `ENTRY_Z`: 1.5
- `EXIT_Z`: 0.25
- `STOP_Z`: 3.0
- `LOOKBACK_BARS`: 30
- `VPIN_INFORMED`: 0.55
- `VPIN_CRISIS`: 0.7
- `VPIN_WINDOW`: 50
- `time_stop_bars`: 60
- `TRADE_START_ET`: 10:30
- `TRADE_END_ET`: 14:30
- `EOD_EXIT_ET`: 15:00
- `VIX_NORMAL`: 25.0
- `VIX_ELEVATED`: 35.0
- `POSITION_SIZE_FULL`: 0.07
- `POSITION_SIZE_REDUCED`: 0.04
- `INIT_CASH`: 25000
- `PRIMARY`: SPY
- `ROBUSTNESS`: QQQ

---

## Exit Reason Distribution (OOS)

- reversion: 91 (25.9%)
- stop_loss: 260 (73.9%)
- time_stop: 1 (0.3%)

---

## Data Quality Notes

- **Universe:** SPY (continuous ETF, no survivorship bias)
- **Price adjustments:** Alpaca split-adjusted data (`adjustment=split`)
- **Data source:** Alpaca IEX free feed (1-min OHLCV)
- **VWAP formula:** Typical price = (H+L+C)/3 (per hypothesis)
- **VPIN:** BVC-based rolling window, 50-bar default
- **Signal-to-fill delay:** 1 bar enforced via lagged features
- **Intraday flat:** Hard exit at 15:00 ET enforced
- **PDT:** Intraday round-trips; $25K+ account required (Gate 8 compliant)
- **Earnings exclusion:** Not explicitly excluded; VPIN gate provides primary filter

---

## Known Overfitting Risks (from hypothesis)

1. Kissell (2014) IC estimate may be stale post-2015 HFT proliferation — 2022–2024 backtest is key test
2. VPIN parameter sensitivity (Andersen-Bondarenko 2014 critique) — validate VPIN gate OOS separately
3. Midday window (10:30–14:30) is a priori from Harris (2003), not IS-optimized
4. Short-leg dependency — long-only variant available but Sharpe degrades ~40%

---

## Files

- Metrics: `backtests/h60_intraday_vwap_mean_reversion_2026-06-09.json`
- Report: `backtests/h60_intraday_vwap_mean_reversion_2026-06-09_report.md`
- Verdict: `backtests/h60_intraday_vwap_mean_reversion_2026-06-09_verdict.txt`