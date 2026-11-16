# Spring: Failed 20-Day-Low Breakdown Reclaim (10 sector and index ETFs, SPY 200SMA gate)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-11-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis (weak; PF-1 to PF-4 verified, QUA-949; forwarding is the Research Director's call)

## Economic Rationale

A Wyckoff spring is a bar that trades below the prior 20-day low to trigger stops and then closes back above that low on an up bar. The stop run supplies the liquidity for informed buyers, and the failed breakdown removes the sellers who were triggered. The Weinstein and Darvas lineage describes support tests with the same logic. The evidence is practitioner lore, with no peer-reviewed source verified.

Important finding: ungated, the pattern has a negative edge. The edge exists only when SPY is above its 200-day SMA, which makes it a trend-pullback entry and not a pure pattern edge.

## Entry/Exit Logic

**Entry signal:**
- Low < lowest low of the prior 20 sessions, Close > that 20-day low, Close > Open.
- SPY Close > SPY 200-day SMA.
- Enter at the close of the signal day (engineering should model next-open fill as a sensitivity).

**Exit signal:**
- Close below the spring-bar low (stop), or 5 trading days after entry.

**Holding period:** Swing (1 to 5 days)

## Market Regime Context

Works in uptrends with shallow pullbacks. Fails in downtrends, which is why ungated returns are negative (mean -0.05% per trade net). Pause when SPY is below its 200-day SMA, which is the gate itself.

## Alpha Decay

- **Signal half-life (days):** about 3 to 5 (estimated from the 5-day exit design; no IC decay curve fit was run)
- **Edge erosion rate:** moderate
- **Recommended max holding period:** 5 days (do not exceed 2x half-life)
- **Cost survival:** marginal. Mean net trade return 0.19% IS after 10 bps round trip, so costs consume about one third of the gross edge.
- **Pre-cost IR estimate:** about 0.27 IS, 0.35 OOS (proxy series). This is below the 0.3 warning level IS.
- **Notes:** The OOS mean net trade of 0.51% is larger than IS (0.19%), based on a small number of regime months and should not be read as improving edge.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| breakdown lookback | 10 – 30 days | 20 tested |
| max hold | 3 – 7 days | 5 tested |
| trend gate | SPY 150 – 250 SMA | 200 tested |

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000.
- **PDT impact:** none (holds of 1 to 5 days; a same-day exit cannot occur because entry is at the close).
- **Position sizing:** 10% per signal, up to 5 concurrent positions.

## Verified Pre-Flight Gates (`scripts/pf_verify_h99_h101.py`)

- **PF-1 PASS.** Gated IS entries 698 (323 distinct days, 35 per year, div4 = 174.5). Clustering is real: events average 2.2 per signal day.
- **PF-2 PASS.** Gated proxy MDD: dot-com -1.0%, GFC -0.6%, full IS -3.1% (10% slot proxy). Ungated: dot-com -15.7%, GFC -6.9%, IS -18.1%.
- **PF-3 PASS.** yfinance daily OHLCV.
- **PF-4 PASS, weakly.** A priori: the SPY 200SMA gate moves the strategy to cash in a bear regime, which was most of 2022. Measured: 14 gated trades in 2022 with mean net return +0.9% per trade. That sample is too small to call a result.

## Measured Results (proxy series, 5 bps per side, 10% slot booked at exit)

| Variant | IS trades | Mean net per trade | Win rate | IS Sharpe (proxy) | OOS Sharpe (proxy) |
|---|---|---|---|---|---|
| Ungated | 1,349 | -0.05% | 47.1% | -0.27 | -0.32 |
| SPY > 200SMA | 698 | +0.19% | 51.6% | 0.27 | 0.35 |

The proxy is not the Gate 1 engine and understates or overstates Sharpe depending on concurrency. The sign and size of the edge are the reliable outputs.

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely (proxy 0.27)
- OOS persistence: uncertain
- Walk-forward stability: likely on trade count, unlikely on Sharpe
- Sensitivity risk: high. The result flips sign with the gate.
- Known overfitting risks: one pattern definition, two variants screened. Overlap with H96 (volume capitulation reversal, failed Gate 1) and H34 (RSI2 oversold SPY) may count as the same short-term-reversal family under the Family Iteration Limit; the Research Director should rule on that before any Gate 1 slot is used.

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** none verified.
- **QC backtest window and IS cherry-pick risk:** community spring or false-breakdown scripts usually show 2012-2020 bull-market windows; discount reported results.
- **Adaptation:** daily bars from yfinance, ETF universe, SPY trend gate.
- **Top-10 clone / crowding:** not confirmed; pattern-based reversal scripts are common.

## References

- `docs/knowledge/trading-methodology-jlaw-lineage.md` (Weinstein, Darvas support logic)
- `research/hypotheses/96_qc_volume_capitulation_reversal_etf.md`, `research/hypotheses/34_rsi2_oversold_spy_mean_reversion.md`
- `backtests/pf_verify_h99_h101_2026-11-16.json`
