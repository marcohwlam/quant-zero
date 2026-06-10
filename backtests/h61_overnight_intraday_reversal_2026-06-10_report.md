# H61 Gate 1 Backtest Report

**Strategy:** Overnight Intraday Reversal — SPY
**Date:** 2026-06-10
**Issue:** QUA-183
**Hypothesis:** research/hypotheses/61_overnight_intraday_reversal.md
**Source:** Lou, Polk & Skouras (2019), JFE 134(1)

---

## Gate 1 Verdict: FAIL

### Failures
- IS Sharpe 0.153 < 1.0 threshold
- OOS avg Sharpe 0.074 < 0.7 threshold

---

## Key Metrics (SPY)

| Metric | IS (2018–2024) | OOS (WF avg) | Gate |
|---|---|---|---|
| Net Sharpe | 0.153 | 0.074 | IS > 1.0, OOS > 0.7 |
| Max Drawdown | -13.0% | — | < 20% |
| Win Rate | 56.7% | — | — |
| Trade Count | 425 | — | IS ≥ 100 |
| Profit Factor | 1.0567 | — | — |
| Avg Net P&L (bps) | 1.25 | — | > 0 |
| Total Return | 4.56% | — | — |

### Walk-Forward Stability
- Profitable OOS windows: 4/6
- WF Sharpe std: 1.118
- WF Sharpe min: -1.518
- Gate (≥ 3/6): PASS

### Walk-Forward Window Detail

| Window | IS Sharpe | OOS Sharpe | OOS Trades | OOS Win% |
|---|---|---|---|---|
| W1 IS 2018-01–2020-12 → OOS 2021-01 | -0.267 | 1.117 | 37 | 56.8% |
| W2 IS 2018-07–2021-06 → OOS 2021-07 | -0.433 | 0.647 | 36 | 63.9% |
| W3 IS 2019-01–2021-12 → OOS 2022-01 | -0.232 | -1.432 | 14 | 35.7% |
| W4 IS 2019-07–2022-06 → OOS 2022-07 | -0.389 | -1.518 | 2 | 0.0% |
| W5 IS 2020-01–2022-12 → OOS 2023-01 | -0.357 | 0.517 | 34 | 50.0% |
| W6 IS 2020-07–2023-06 → OOS 2023-07 | 0.230 | 1.113 | 36 | 55.6% |

---

## Statistical Rigor

| Test | Value | Note |
|---|---|---|
| MC p5 Sharpe | -0.930 | Pessimistic bound (flag if < 0.5) |
| MC Median Sharpe | 0.342 | Bootstrap median |
| Sharpe 95% CI | [-0.469, 0.806] | Block bootstrap |
| Win Rate 95% CI | [10.9%, 16.0%] | |
| Permutation p-value | 1.0000 | PASS if ≤ 0.05 |
| Permutation test | FAIL | |
| Market impact (bps) | 0.018 | SPY 200-share order |
| Liquidity constrained | False | |

---

## Data Quality

- Universe: Single ETF, no survivorship bias applicable
- Price adjustment: yfinance auto_adjust=True (split + dividend adjusted)
- Total bars (IS window): 1760
- Missing Close bars: 0
- Coverage: 100.0%
- Large gap flag: False
- Earnings exclusion: Not applicable — SPY ETF, no single-stock earnings events

---

## Transaction Cost Model (Applied)

- Asset class: SPY (ultra-liquid ETF, ADV >> 50M shares/day per ED-SLIP-001)
- Fixed cost: $0.005/share per leg
- Slippage: 0.005% per leg (ED-SLIP-001 ultra-liquid tier, NOT standard 0.05%)
- Market impact: 0.1 × σ × sqrt(Q / ADV) per leg

---

## Files

- Metrics: `backtests/h61_overnight_intraday_reversal_2026-06-10.json`
- Report: `backtests/h61_overnight_intraday_reversal_2026-06-10_report.md`
- Verdict: `backtests/h61_overnight_intraday_reversal_2026-06-10_verdict.txt`
- Trades: `backtests/h61_overnight_intraday_reversal_2026-06-10_trades.csv`