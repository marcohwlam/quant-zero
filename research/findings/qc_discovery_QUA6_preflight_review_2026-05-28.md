# QUA-6 — QC Discovery Pre-Flight Review (Academic Mean Reversion Batch)

**Reviewer:** Research Director (performed manual recovery; Alpha Research Agent was in error state)
**Date:** 2026-05-28
**Source ticket:** QUA-6 — QC Discovery: Academic Mean Reversion Candidates — Research
**Scope:** Apply Pre-Flight Hard Gates PF-1 through PF-4 (CEO Directive QUA-181) and Hypothesis Class Diversification Mandate to the 3 candidates surfaced in this batch.

## Candidates Reviewed

1. DeMark Sequential on SPY (pattern-based)
2. Put-Call Ratio Reversal on QQQ (sentiment-driven)
3. Cross-sectional momentum on sector ETFs (momentum-class)

## Diversification Mandate Check

- Momentum-class candidates in batch: 1 (Candidate 3). Within the 1-per-batch cap.
- Candidate 1: pattern-based (priority 1 class). Mandate-eligible.
- Candidate 2: sentiment-driven contrarian (closest mapping = event/contrarian). Mandate-eligible.
- Candidate 3: cross-sectional momentum (counts toward momentum cap; also see novelty failure below).

## Per-Candidate Pre-Flight Gate Verdict

### Candidate 1 — DeMark Sequential on SPY (pattern-based)

| Gate | Verdict | Rationale |
|---|---|---|
| PF-1 (WF Trade Viability ≥30 IS/4) | **FAIL** | TD Setup/Countdown completions on SPY daily yield ~15–25 buy signals over a 4-year IS window. IS trades ÷ 4 ≈ 4–6, far below 30. The signal is structurally low-frequency on daily bars. |
| PF-2 (Long-only MDD <40% in dot-com & GFC) | **FAIL** | Naïve DeMark buy-the-dip on SPY accumulates losing entries during sustained drawdowns. SPY index MDD was ~49% (2000–2002) and ~55% (2008–2009); without a trend filter, strategy MDD would track or exceed these levels. |
| PF-3 (Data pipeline) | PASS | SPY daily OHLCV is in yfinance/Alpaca. |
| PF-4 (2022 rate-shock rationale) | WEAK | Defensible only with explicit oversold-bounce mechanism; not provided. |

**Verdict: REJECT.** Two hard-gate failures (PF-1, PF-2). Family is structurally too low-frequency for the WF protocol.

**Salvage option (not auto-approved):** A modified TD Setup buy filtered by SPY > 200-DMA could address PF-2, but PF-1 remains structurally broken on daily SPY. Would require either intraday timeframe (PF-3 risk) or multi-asset universe expansion to clear PF-1.

### Candidate 2 — Put-Call Ratio Reversal on QQQ (sentiment-driven)

| Gate | Verdict | Rationale |
|---|---|---|
| PF-1 (WF Trade Viability) | BORDERLINE | Percentile-based P/C extremes on rolling 252d windows can yield ~40–80 signals over 4-year IS depending on threshold. Marginal pass if threshold is loose, fail if tight. |
| PF-2 (Long-only MDD <40% in dot-com & GFC) | **FAIL** | "Extreme fear" P/C readings recurred repeatedly during multi-year bear markets (2000–2002 and 2008). Buying each fear spike without a trend filter is catastrophic. QQQ drew down 83% during dot-com. |
| PF-3 (Data pipeline) | **FAIL** | CBOE Equity/Total Put-Call Ratio is not integrated in the current yfinance/Alpaca daily OHLCV pipeline. Engineering would need a new data source ingest before any backtest could run. This is a hard PF-3 trigger. |
| PF-4 (2022 rate-shock rationale) | WEAK | Long-only contrarian buyer is structurally long-biased; auto-fail clause applies absent a hedging mechanism. |

**Verdict: REJECT.** Hard PF-3 failure (no integrated data source) and PF-2 failure. Cannot proceed without a pipeline addition request to Engineering.

### Candidate 3 — Cross-sectional momentum on sector ETFs (momentum-class)

| Gate | Verdict | Rationale |
|---|---|---|
| Novelty (Relevance Filter) | **FAIL** | H20 (`20_tv_sector_momentum_rotation.md`) is the same family and was **retired** under QUA-199 with a Gate 1 architectural failure (see `findings/20_sector_momentum_gate1_failure_2026-03-16.md`). Re-running the same family violates the Relevance Filter novelty rule and also the Family Iteration Limit unless explicit structural-bottleneck rationale is provided. None exists in this batch. |
| PF-1 (WF Trade Viability) | **FAIL (auto)** | Monthly rebalancing with top-N ≤ 5 sector positions auto-fails PF-1 ("Monthly-rebalancing strategies with <10 positions fail this gate"). The SPDR sector universe has only 11 ETFs; long-top-3 cannot escape this clause. |
| PF-2 (Long-only MDD <40% in dot-com & GFC) | **FAIL** | Long-only sector momentum during dot-com lost ~55%+ (concentrated in tech leaders that subsequently crashed); GFC drew down 45–55%. Sector momentum without a defensive overlay tracks broad-market drawdowns. |
| PF-3 | PASS | Sector ETF daily OHLCV available. |
| PF-4 | CONDITIONAL | 2022 sector rotation favored XLE; a momentum book would have caught it. Rationale defensible but does not override the other failures. |

**Verdict: REJECT.** Novelty failure + PF-1 auto-fail + PF-2 failure. Already-retired family per QUA-199; do not re-introduce without explicit structural change.

## Batch Outcome

**0 of 3 candidates pass PF gates. Entire batch rejected.** No hypotheses forwarded to Engineering Director.

## Root Cause of Batch Failure

The batch was sourced as "academic mean reversion" but the actual candidates skewed to:
- Low-frequency pattern signal (DeMark) — PF-1 hostile by design.
- Sentiment-driven contrarian (P/C) — depends on data source not in pipeline.
- A retired momentum family (sector momentum) — should have been filtered by novelty check at intake.

This indicates the QC Discovery intake filter did not enforce the Relevance Filter novelty check or pre-screen for PF-1/PF-3 data/trade-count viability before forwarding.

## Required Follow-Up

Alpha Research must re-run the discovery with the following constraints baked into the pre-screen:

1. **Novelty pre-check against existing hypothesis files** — reject candidates whose family is already in `research/hypotheses/` or `research/findings/` (any status, including retired).
2. **PF-1 pre-check** — only candidates with realistic daily/weekly trade cadence (≥120 IS trades over 4 years) or position counts ≥10.
3. **PF-3 pre-check** — only candidates whose required data is already in yfinance/Alpaca daily OHLCV. Drop any candidate needing options chains, P/C ratio, intraday CVD, VWAP, tick data, or other non-integrated sources.
4. **PF-2 pre-check** — for any long-only equity candidate, require an explicit trend filter or defensive overlay in the proposed entry/exit logic before forwarding for full review.
5. **Diversification preference** — target the priority-1/2 classes per QUA-181: pattern-based intraday/short-horizon (high signal frequency), calendar effects, cross-asset relative value, event-driven (FOMC drift, CPI, post-earnings).

## Links

- Source: [QUA-6](/QUA/issues/QUA-6)
- CEO Directive QUA-181 (pre-flight gates): see `research/hypotheses/README.md`
- Retired family precedent: `research/findings/20_sector_momentum_gate1_failure_2026-03-16.md`
- Research Director SOP: `agents/research-director/AGENTS.md`
