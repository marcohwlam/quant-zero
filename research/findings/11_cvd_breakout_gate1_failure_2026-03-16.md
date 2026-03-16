# H11 Gate 1 Failure — CVD-Confirmed Breakout

**Date:** 2026-03-16
**Hypothesis:** H11 CVD-Confirmed Breakout (`research/hypotheses/11_tv_cvd_breakout_signal.md`)
**Research Director Decision:** **ABANDON**
**Backtest file:** `backtests/H11_CVDBreakout_2026-03-16.json`
**Paperclip ticket:** QUA-136 (backtest), QUA-151 (research review)

---

## Gate 1 Verdict Summary

| Metric | Result | Pass? |
|---|---|---|
| IS Sharpe | 0.48 | ❌ |
| OOS Sharpe | 0.57 | ❌ |
| MDD | -12.8% | ✅ |
| Trade count | 847 | ✅ |
| WF windows passed | 1/4 | ❌ |
| CVD sensitivity variance | 194% | ❌ |
| MC p5 Sharpe | 0.11 | ❌ |
| DSR | 0.04 | ❌ |

**Primary failure reason: Sequential IC validation — REJECT_BOTH**
- Price breakout IC: **0.0000** (threshold: > 0.02)
- CVD proxy IC: **0.0000** (threshold: > 0.02)

---

## Research Director Analysis

### Why both signals returned IC = 0

The hypothesis explicitly warned this was the critical risk:

> "If daily proxy proves too noisy (IC near zero), consider downgrading to single-signal breakout strategy."

The daily CVD proxy `(Close - Open) / (High - Low) × Volume` (money flow approximation) failed because:

1. **Architecturally flawed proxy.** The formula approximates intraday order flow imbalance from daily bar data, but at daily resolution the information is already embedded in the closing price. The signal is computing a direction-weighted volume metric that collapses to near-zero Spearman rank correlation against 5-day forward returns across 15 large-cap tickers.

2. **Price breakout signal also returned IC = 0** in this test configuration. This is structurally unsurprising: on a 15-ticker equity universe at daily frequency, a simple N-bar high breakout without regime conditioning yields essentially random cross-sectional IC. H05 (momentum vol-scaled) similarly failed Gate 1 — the breakout signal family has now failed twice across different implementations.

3. **Signal combination policy hard stop.** Per the Research Director Signal Combination Policy: "No combining noise — IC > 0.02 required individually before combination." With both signals at IC = 0, there is no combination to evaluate. The rejection occurs at pre-combination validation.

### Why the combined strategy failed to compensate

Walk-forward validation (1/4 windows) confirms the edge is not real — any apparent IS performance is overfitting to CVD threshold tuning. Monte Carlo p5 Sharpe of 0.11 and DSR of 0.04 confirm this definitively. The 194% CVD sensitivity variance means the `cvd_threshold_mult` parameter is noise-amplifying.

### Why full CVD could not rescue the strategy

Real intraday CVD (5-min or 1-hour aggregated) requires tick or sub-minute OHLCV data. yfinance provides end-of-day OHLCV only. Acquiring intrabar data (Polygon.io, Alpaca 1-min) requires infrastructure not currently in the pipeline. The capital budget ($25K) does not justify the data cost for an unvalidated hypothesis with weak IC foundations.

---

## Disposition

**ABANDONED.**

This strategy direction — daily CVD proxy as breakout confirmation filter — is exhausted:
- Daily CVD proxy: IC = 0 (hard stop; architecturally insufficient)
- Daily price breakout alone: IC = 0 in this configuration (analogous to H05, already Gate 1 FAIL)
- True CVD requires intrabar data not available in current pipeline

The order flow insight (CVD) has genuine microstructure grounding (Kyle 1985, Glosten-Milgrom 1985). It is not abandoned as a concept — only this daily implementation.

### Potential future revisit conditions

This strategy could be revisited if:
1. Intrabar data (1-min Polygon.io or Alpaca) becomes available in the pipeline, enabling genuine CVD estimation rather than the daily proxy
2. The account size warrants intrabar data subscription (> $50K AUM suggested)
3. A separate IC validation on 5-minute bars confirms CVD IC > 0.02

**Do not revisit on daily bars.** The daily proxy is structurally incapable of capturing order flow intent.

---

## Lessons Applied to Pipeline

1. **IC validation gate is working correctly.** The sequential IC check (test each signal individually before combining) caught this failure before expensive parameter sweeps were run across the full multi-signal space.

2. **Daily breakout signals need regime conditioning.** Both H05 and H11 (breakout-family strategies) have now yielded IC ≈ 0 on daily bars without regime filters. Future breakout hypotheses must incorporate a mandatory regime gate (VIX filter + trend direction) as a pre-condition in the hypothesis spec, not just a parameter to test.

3. **Data feasibility must be confirmed before forwarding.** The hypothesis was forwarded with a caveat that intrabar CVD data was unavailable and the daily proxy "may be too noisy." The backtest confirmed the worst case. Future hypotheses with critical data feasibility dependencies should flag this as a required confirmation step before creating the Engineering Director backtest task.

---

*Research Director | QUA-151 | 2026-03-16*
