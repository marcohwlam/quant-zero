# H13 VWAP Anchor Reversion — Gate 1 FAIL

**Date:** 2026-03-16
**Hypothesis:** H13 — VWAP Anchor Reversion
**Hypothesis file:** `research/hypotheses/13_tv_vwap_anchor_reversion.md`
**Backtest ticket:** QUA-155
**Research Director decision ticket:** QUA-163
**Final status:** ABANDONED

---

## Verdict

**Gate 1: FAIL — ABANDONED**

6/12 criteria passed. Three independent critical failures (trade count, permutation test, sensitivity) make this hypothesis non-viable at daily ETF granularity.

---

## Scorecard

| Criterion | Threshold | Actual | Pass? |
|---|---|---|---|
| IS Sharpe | > 1.0 | 0.73 | FAIL |
| OOS Sharpe | > 0.7 | 0.26 | FAIL |
| IS MDD | < 20% | 0.2% | PASS |
| Win Rate | > 50% | 75.0% | PASS |
| Walk-forward (windows) | 3/4 | 2/4 | FAIL |
| Sensitivity | < 50% Sharpe var | 123.6% | FAIL |
| Trade Count IS | ≥ 30 | 8 | FAIL |
| Signal IC | > 0.02 | 0.0897 | PASS |
| Permutation test | p ≤ 0.05 | p=0.636 | FAIL |
| MC p5 Sharpe | > 0.5 | 1.09* | PASS* |

*MC result unreliable — only 8-trade sample; insufficient for Monte Carlo inference.

---

## Root Cause Analysis

**Primary failure: structural trade sparsity at daily granularity.**

The hypothesis requires a daily closing price to touch or exceed the VWAP ±2 SD band, followed by reversion confirmation on the next bar. On liquid ETFs (SPY, QQQ, IWM) with daily OHLCV data:

- VWAP is approximated as `(H+L+C)/3` (typical price) — not true session VWAP
- At 2.0 SD, this event occurs ~2×/year/ETF → ~6 opportunities/year across 3 ETFs
- Over the IS window (estimated ~8 years), only 8 total IS trades were generated
- 8 trades is statistically insufficient: no reliable performance estimation, permutation tests lack power, walk-forward windows near-empty

**Secondary failure: permutation test (p=0.636).**

After 1,000 random label permutations, the observed Sharpe rank was consistent with random chance. The signal is statistically indistinguishable from noise at daily resolution using the typical-price VWAP proxy. This is the most fundamental failure — it indicates no detectable edge, not merely insufficient trades.

**Why the proxy fails the theory.**

The economic rationale depends on institutional VWAP benchmarking pressure — execution algorithms constrained to achieve fills better than session VWAP. This mechanism operates intraday, not at daily close. A typical-price proxy on daily bars captures end-of-day deviations from a rolling average, which does not correspond to the institutional behavioral pattern the theory predicts.

---

## Options Considered and Rejected

### Option A: Abandon (Selected)

**Decision:** Correct. The permutation test failure and proxy mismatch confirm no edge at daily resolution. Abandonment avoids compounding time on a structurally broken implementation.

### Option B: Lower SD to 1.5

**Rejected.** Engineering Director sensitivity analysis showed SD=1.5 yields IS Sharpe 1.07 with 33 trades. However:
- Selecting this threshold after observing the Gate 1 failure is post-hoc snooping
- The 123.6% Sharpe sensitivity across the SD sweep (1.5–2.5) means even SD=1.5 would fail the sensitivity criterion
- The permutation test was run at SD=2.0; SD=1.5 includes lower-quality touch events with higher noise contamination
- This option violates the anti-overfitting principle: do not select parameters in response to observed test failure

### Option C: Revise to intraday (archived for future)

Not pursued in current cycle due to infrastructure requirements (Polygon/Alpaca 1-min data pipeline not yet built). See "Archive Note" below.

---

## Archive Note: Future Revisit Conditions

This hypothesis is archived, not permanently discarded. The economic rationale is academically grounded (Berkowitz/Logue/Noser 1988; Madhavan & Cheng 1997). The implementation failure is in the data source, not the theory.

**Trigger for re-evaluation:** When Polygon or Alpaca 1-min intraday data pipeline is operational.

At intraday resolution:
- True session VWAP can be computed from tick-level or 1-min OHLCV with volume
- Signal fires on ~30-min intervals at ±2 SD → substantially higher trade frequency
- The institutional benchmarking mechanism is directly testable
- Expected trade frequency: 50–100 IS signals on 3 ETFs over a 3-year IS window

**Suggested intraday hypothesis parameters:**
- Timeframe: 30-min or 1-hr bars
- Signal: price crosses ±2 SD VWAP band + reversion confirmation bar
- Hold: 1 session to 3 sessions
- Universe: SPY, QQQ, IWM (same, high institutional participation)
- Macro filter: same ±2-day FOMC/CPI/NFP exclusion applies

---

## Lessons Learned

1. **Pre-flight data feasibility is critical.** The Research Director review noted the typical-price proxy risk but forwarded conditionally. In retrospect, the IC validation gate at the hypothesis stage should have included a rough trade-count estimate. If expected trades < 30 in IS window, do not forward — the backtest will be structurally underpowered.

2. **Daily granularity creates trade-count floors.** Any mean-reversion strategy that fires on extreme band touches (±2+ SD) at daily frequency will generate < 10–20 signals per ETF per year. Multi-ETF universes partially mitigate this, but for niche signals (VWAP touch + reversal), the structural ceiling is low. Require trade-count projections in hypothesis documents.

3. **Permutation test p=0.636 is a hard stop.** This result, combined with a 8-trade sample, confirms the signal is noise. No parameter sweep remediation is appropriate after a failed permutation test.

---

*Research Director | QUA-163 | 2026-03-16*
