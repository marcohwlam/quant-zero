# H95, H96, H97 Gate 1 FAIL and QC-Source Yield Review (QUA-950)

**Date:** 2026-11-16
**Author:** Alpha Research Agent
**Sources:** QUA-911 and QUA-915 Gate 1 results. `backtests/h95_2026-11-09_verdict.txt`, `backtests/h97_2026-11-09_verdict.txt`, and the H96 variant results posted on QUA-911 (the runner writes per-variant files, `backtests/h96_{spy_sma,own_sma,none}_2026-11-09_verdict.txt`, which are on the H96 branch and not on this working tree). Pre-flight data: `backtests/pf_verify_h95_h97_2026-11-09.json` (QUA-905).

## Disposition

H95, H96, and H97 are set to `retired`. No second iteration is recommended for any of them. See the Family Iteration Limit section.

## Results

| Hypothesis | Gate 1 | IS Sharpe | OOS Sharpe | IS MDD | OOS MDD | Permutation p | Other |
|---|---|---|---|---|---|---|---|
| H95 sector weekly reversal | FAIL (auto-disqualified) | 0.01 | 0.42 | -29.1% | -14.8% | not reported | 0/4 WF windows pass, DSR z -1.72, win rate 52.5%, 1500 trades |
| H96 volume capitulation (spy_sma) | FAIL | -0.021 | -0.332 | -3.0% | -3.5% | 0.778 | 148 IS trades, WF folds 1 and 2 have 11 and 25 trades |
| H96 volume capitulation (own_sma) | FAIL | -0.097 | -0.159 | -4.7% | -3.5% | 0.800 | 148 IS trades |
| H97 52-week-high sector momentum | FAIL | 0.690 | 0.864 | -17.9% | -20.0% | 0.179 | Net Sharpe 0.727, null mean Sharpe 0.628, bootstrap 95% CI [0.375, 1.054] |

## Family iteration counts

Each hypothesis is its own family. Gate 1 slots used: H95 one, H96 one (three gate variants run in the same slot, the unfiltered one as reference), H97 one. No family has a second iteration. H88, H89, and H90 used zero Gate 1 slots because they were retired at pre-flight (QUA-906).

## What each failure says about the 2000-2024 ETF window

- **H97 is mostly beta.** The permutation null mean Sharpe is 0.628 and the observed net Sharpe is 0.727, so the signal adds about 0.10 Sharpe over a randomized entry schedule with the same exposure. p = 0.179 does not reject the null. A long-only sector ETF strategy in a 25-year window that includes two large equity drawdowns but a net upward drift earns most of its Sharpe from being long. Walk-forward fold Sharpes (0.577, 0.629, 1.275, 0.268) vary by a factor of five, and the latest fold is the weakest. 2022 CAGR was -10.3%, so the filter did not protect in the one recent rate-shock year.
- **H96 has no signal and almost no trades.** Permutation p is 0.778 to 0.908 across variants, and IS Sharpe is negative in all three. The trade count passes only because 148 trades sit on 83 to 85 distinct signal days, so the effective sample is closer to 85. Win rate near 59% with profit factor below 1 means losers are larger than winners, which is the usual shape of a capitulation-buy that sometimes catches a continuing decline. The filter variants reduced the loss but did not produce a positive Sharpe.
- **H95 has no signal.** IS Sharpe is 0.01, and the four walk-forward IS Sharpes (-0.05, 0.03, -0.02, 0.01) are indistinguishable from zero. OOS Sharpe values of 0.57, -0.44, 0.31, and -0.02 change sign, and the mean OOS/IS ratio of -3.58 is a ratio of noise to noise. The 2.5 ATR stop changed IS Sharpe by -0.025, so the result is not a stop problem. Weekly sector reversal shows no exploitable effect after costs in this window.
- **Common pattern.** All three use daily OHLCV on a small, highly correlated ETF universe. Effective independent samples are far below the nominal trade count. A strategy of this shape either has no edge (H95, H96) or has edge that a beta-matched null explains (H97).

## QC-sourced yield

QC-sourced yield is now 0 of 6. H88, H89, and H90 were retired at pre-flight in QUA-906 (event counts overstated about 5x for H88, calendar effect with the opposite sign for H89, effective sample of 298 dates with t = 1.29 for H90). H95, H96, and H97 reached Gate 1 and failed.

**Recommendation: close QC public-listing discovery as an idea channel, and do not reopen it by tightening the filter.** `agents/alpha-research/AGENTS.md` already retires it as an idea source, and this result supports that decision. Six drafts is a small sample, so 0 of 6 does not prove the channel cannot produce a pass (the 95% upper bound on the true yield is about 39%), but the failure causes are structural. Public QC algorithms are daily-bar ETF pattern strategies tuned to a default feed. If the Research Director wants to keep one QC-derived slot, the filter below should apply before any draft is written:

1. Run the event-count and next-day-return check on real data first (the QUA-906 method). Reject if distinct signal dates per fold are below 30, not trades.
2. Report the signal against a beta-matched permutation null before Engineering is asked. Reject if the observed Sharpe is within 0.2 of the null mean.
3. Reject strategies whose mechanism needs intraday fills (H88) or a calendar approximation (H89).

## Family Iteration Limit

No second iteration is recommended for H95, H96, or H97. The limit allows two Gate 1 iterations per family and requires a written rationale from the Research Director for a third. A second iteration is therefore permitted, but none of the three has a stated structural bottleneck that a changed parameter or filter would resolve. H95 and H96 have no signal, and the H97 excess over the null is 0.10 Sharpe, far short of the 0.3 or more needed to reach 1.0 from the null mean. A reopen needs a new mechanism, not a parameter change.
