# Gate 1 Verdict: H37 G10 Currency Carry

**Version:** 1.0
**Date:** 2026-03-17
**Author:** Engineering Director (QUA-298)
**Verdict: FAIL**

---

## Strategy Summary

- **Asset class:** FX ETFs (FXA/AUD, FXB/GBP, FXC/CAD, FXE/EUR, FXF/CHF, FXY/JPY)
- **Signal 1 (Carry):** Rank by 3-month central bank rate differential vs. USD (FRED). Long top-2, short bottom-2.
- **Signal 2 (Momentum filter):** Long only if ETF close > 60-day SMA; short only if < 60-day SMA.
- **Rebalancing:** Monthly at month-end. VIX > 35 emergency exit.
- **Hard stop:** -8% per position from entry.
- **IS window:** 2007-01-01 to 2021-12-31 (14 years)

---

## Final Metrics

| Metric | Value | Gate 1 Threshold | Pass? |
|---|---|---|---|
| IS Sharpe | -0.2254 | > 1.0 | ❌ FAIL |
| OOS Sharpe (WF mean) | 0.2798 | > 0.7 | ❌ FAIL |
| IS Max Drawdown | -25.66% | < 20% | ❌ FAIL |
| Trade Count (IS) | 254 | ≥ 100 | ✅ PASS |
| Win Rate | 39.76% | ≥ 50% | ❌ FAIL |
| Profit Factor | 0.82 | ≥ 1.0 | ❌ FAIL |
| Permutation p-value | 1.0 | ≤ 0.05 | ❌ FAIL |
| Best sensitivity Sharpe | 0.1905 | > 1.0 | ❌ FAIL |

---

## Disposition

**Status: RETIRED**

H37 fails 9 of 10 Gate 1 criteria. The strategy produces negative risk-adjusted returns over the 2007–2021 IS window, driven by:
1. Two severe carry crashes (2008 GFC, 2020 COVID) within the IS window
2. Near-zero rate environment (2010–2021) compressing carry differentials
3. VIX exit whipsaw: 64.6% of trades are VIX-triggered exits, generating excessive transaction costs
4. Short CHF (FXF) drag from 2015 SNB floor removal

No parameter combination in the 27-combination sensitivity sweep approaches Gate 1 threshold (best: Sharpe = 0.19).

**Research Director action required:** Propose H38 hypothesis. H37 is formally retired.

---

## References

- Full backtest report: `backtests/h37_g10_carry_gate1_report.md`
- Strategy code: `strategies/h37_g10_currency_carry.py`
- Hypothesis: `research/hypotheses/37_g10_currency_carry.md`
- Authorization: QUA-294 (CEO), QUA-298 (this task)
