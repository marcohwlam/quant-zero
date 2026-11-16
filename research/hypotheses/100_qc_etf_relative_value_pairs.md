# Region and Style ETF Relative-Value Pairs (dollar-neutral z-score reversion)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-11-16
**Asset class:** equities
**Strategy type:** pairs
**Status:** retired (signal absent on real data; PF-1 to PF-4 verified, QUA-949). Do not forward to Gate 1.

## Economic Rationale

Relative performance of broad ETFs that share a dominant risk factor (EFA vs SPY, EEM vs SPY, EEM vs EFA, IWM vs SPY, QQQ vs DIA, XLE vs XLK) is hypothesized to mean-revert over weeks because flows chase recent winners and push short-term relative prices away from fair value. A dollar-neutral position removes market beta, which addresses PF-2 and PF-4 by construction. No academic source is cited because none was verified; the pairs were fixed a priori by economic grouping and not selected by backtest.

## Entry/Exit Logic

**Entry signal:**
- s = 20-day log relative return of A minus B. z = (s - rolling 252-day mean) / rolling 252-day std.
- If z >= +Z_in short A and long B; if z <= -Z_in long A and short B (each leg 50% of sleeve).

**Exit signal:**
- z crosses 0, or 10 trading days elapsed.

**Holding period:** Swing (up to 10 days)

## Market Regime Context

Expected to work in range-bound relative markets, fail in persistent leadership (2020-2024 US mega-cap leadership). Measured behavior matches the failure case.

## Cointegration Analysis

Not run. The pairs are ratio-of-indices relative return reversion, not a cointegrated price pair. If this idea is revived, an Engle-Granger test per pair is required first and the pair must show p < 0.05. Per the format rule, no pair is passed to Gate 1 without it.

## Alpha Decay

- **Signal half-life (days):** unknown; not estimated because the IC is near zero
- **Edge erosion rate:** not applicable
- **Recommended max holding period:** 10 days in the test
- **Cost survival:** no. 5 bps per side per leg is included in the results below and the net Sharpe is 0.2.
- **Pre-cost IR estimate:** 0.2 to 0.25 IS, below the 0.3 warning level and negative OOS.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| Z_in | 1.5 – 2.0 | Both tested |
| lookback for z | 252 | Fixed |

## Capital and PDT Compatibility

- **Minimum capital required:** $10,000 (short leg needs margin).
- **PDT impact:** none (multi-day holds).
- **Position sizing:** 50% long, 50% short per pair, six pairs, equal weight.

## Verified Pre-Flight Gates (`scripts/pf_verify_h99_h101.py`)

- **PF-1 PASS.** IS trades: Z_in 2.0: 366 (div4 = 91.5); Z_in 1.5: 809 (div4 = 202).
- **PF-2 PASS.** Market neutral. MDD: dot-com -2.1% (Z 2.0), -3.4% (Z 1.5); GFC -2.5% and -3.1%.
- **PF-3 PASS.** yfinance daily ETF data. EFA starts 2001-08, EEM 2003-04.
- **PF-4 PASS by construction.** Long-short, no net equity beta. Measured 2022 return: +0.5% (Z 2.0), -1.7% (Z 1.5).

## Measured Results

| Variant | IS Sharpe | OOS 2020-24 Sharpe |
|---|---|---|
| Z_in 2.0, six pairs | 0.22 | -0.14 |
| Z_in 1.5, six pairs | 0.25 | -0.40 |

Per pair IS Sharpe ranges from -0.12 to 0.31, and no pair clears 0.35 in either IS or OOS.

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely (0.22 to 0.25)
- OOS persistence: unlikely (negative)
- Walk-forward stability: unlikely
- Sensitivity risk: not meaningful; signal is absent
- Known overfitting risks: six pairs and two thresholds screened; none worked.

## Disposition

Retire at intake. Learning: ETF-level relative return reversion at 20-day horizon has no edge net of 5 bps costs, 2002-2024. Consistent with the failure of H95 (sector weekly reversal).

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** none verified.
- **QC backtest window and IS cherry-pick risk:** community pairs on country ETFs typically show 2010-2019 windows; not relied on here.
- **Adaptation:** daily yfinance bars; dollar-neutral two-leg ETF positions.
- **Top-10 clone / crowding:** not confirmed.

## References

- `research/hypotheses/95_qc_sector_weekly_reversal.md` (failed Gate 1)
- `research/hypotheses/70_iwm_smallcap_mean_reversion.md`
- `backtests/pf_verify_h99_h101_2026-11-16.json`
