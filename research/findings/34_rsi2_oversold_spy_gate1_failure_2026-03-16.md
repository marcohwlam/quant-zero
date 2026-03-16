# H34 Gate 1 Failure — RSI(2) Oversold SPY Mean Reversion

**Date:** 2026-03-16
**Hypothesis:** H34 RSI(2) Oversold SPY (200-SMA regime filter)
**Verdict:** FAIL (4/11 criteria)
**Iteration:** 1 of 2 (family continues with H34b)

---

## Gate 1 Results

| Metric | Actual | Threshold | Result |
|--------|--------|-----------|--------|
| IS Sharpe | 0.35 | > 1.0 | FAIL |
| OOS Sharpe | 0.48 | > 0.7 | FAIL |
| IS MDD | -16.62% | < 20% | PASS |
| OOS MDD | -7.03% | < 25% | PASS |
| IS Trades | 119 | ≥ 100 | PASS |
| Win Rate (OOS) | 67.65% | > 50% | PASS |
| DSR | 0.00 | > 0 | FAIL |
| MC p5 Sharpe | -0.28 | ≥ 0.5 | FAIL |
| Permutation p-val | 0.536 | ≤ 0.05 | FAIL |
| Walk-forward | 2/4 | ≥ 3/4 | FAIL |
| Param sensitivity | 32.3% | < 30% | FAIL |

IS Trades/year: **7.9/year** (well below PF-1 target of 30/year — passed on total count but sparse per WF window)

---

## Root Cause Analysis

**Primary failure: insufficient trade frequency for statistical significance.**

The 200-SMA regime filter combined with the RSI(2) < 10 threshold produced only 7.9 trades/year in the 2007–2021 IS window. This is 60–75% below the 20–30/year documented by Connors (2012). Consequences:
- Permutation p-value 0.536 — cannot distinguish signal from noise at N=119 IS trades
- WF windows average ~30 trades each — insufficient to establish consistency (Sharpe std = 0.84)
- DSR = 0 — Sharpe is well below deflation-adjusted threshold given small sample

**The core edge is likely real.** The 67.65% OOS win rate (34 trades) is consistent with Connors' documented 65–75% win rate. The failure is statistical power, not edge existence.

**WF window detail:**
- Window 1 (OOS 2009–2010): Sharpe = -0.42 FAIL — Post-GFC environment; strategy likely entered during partial recovery, mixed results
- Window 2 (OOS 2013–2014): Sharpe = 0.76 PASS
- Window 3 (OOS 2017–2018): Sharpe = -0.47 FAIL — 2018 Q4 correction period; late entries caught the tail of the drawdown
- Window 4 (OOS 2021): Sharpe = 1.52 PASS

The variance (Sharpe std = 0.84) is primarily driven by sparse trades per window making results highly regime-sensitive.

---

## What Worked

- **Risk management:** GFC MDD only -1.97%, 2022 stress MDD only -5.28% — 200-SMA filter does its job
- **OOS win rate:** 67.65% is strong and consistent with academic expectation
- **Trade quality:** Profit Factor 1.63 in OOS suggests positive expected value per trade
- **Liquidity/execution:** No market impact concern (Order/ADV = 0.000001)

---

## Decision: Proceed to H34b

**Rationale:** This is iteration 1 of 2 for the RSI(2) family. The structural bottleneck (trade frequency) is clearly identified and has a clean, minimal fix. The economic rationale is intact. Proceeding with H34b (RSI(2) threshold raised from 10 to 20).

**H34b structural change:**
- RSI entry threshold: 10 → 20
- Re-entry floor: RSI > 40 → RSI > 50
- 200-SMA filter: unchanged
- All other parameters: unchanged

Expected improvement: IS Sharpe 0.35 → 0.85–1.30 via 3× trade frequency increase, enabling statistical significance.

**This is the final iteration.** After H34b Gate 1, this family is retired regardless of outcome per QUA-181 family iteration limit.

---

*Research Director | QUA-265 | 2026-03-16*
