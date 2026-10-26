# H10 Offline Signal Replay (QUA-825)

Date: 2026-10-26
Analyst: Overfit Detector Agent
Scope: replay `strategies/h10_crypto_eql_reversal.py` (PARAMETERS unchanged) on yfinance BTC-USD/ETH-USD daily bars, warmup from 2025-12-01 through 2026-10-26. Script: scratch `h10_replay.py` (continuous run, plus a per-day emulation of `get_current_signal(lookback_days=60)` from `broker/paper_trading/h10_paper_runner.py`).

## Result

Expected entries over the paper window (2026-03-16 to 2026-10-25) are greater than 0. Live trades: 0.

| Entry date | Asset | Dir | Exit | In paper-approved set (long only) |
|---|---|---|---|---|
| 2026-03-31 | BTC | long | 04-07 TP | yes |
| 2026-04-09 | BTC | short | 04-14 SL | no (shorts blocked) |
| 2026-05-02 | ETH | long | 05-06 TP | yes |
| 2026-07-28 | BTC | short | 08-04 time | no |
| 2026-08-05 | ETH | long | 08-12 time | yes |
| 2026-08-06 | BTC | long | 08-13 time | yes |
| 2026-09-01 | BTC | long | 09-03 TP | yes |
| 2026-09-01 | ETH | long | 09-08 time | yes |
| 2026-09-12 | ETH | long | 09-14 TP | yes |
| 2026-09-16 | ETH | short | 09-21 SL | no |

Long entries: 7 (about 11 per year, matches the Gate 1 expectation of 10-14). Shorts: 3, correctly suppressed by the runner. BTC ROC gate blocked 31 of 299 days since 2026-01-01, so the regime gate does not explain zero trades.

## Why live shows 0 trades

1. Evaluation coverage. trades.csv holds evaluations on 2026-03-16, 2026-05-29 to 2026-06-08 and 2026-10-26 only. Not one of the 7 long entries falls on or is visible from an evaluated day. Replay of the runner's own 60-day view on every evaluated day returns flat. So 0 trades is the correct output of the runner as run. Reading A (sparse sample) holds for the evaluated days; reading B (feed defect) is not supported.
2. Design defect, stateless runner. `get_current_signal` re-runs a 60-day backtest and acts only when the last trade is `end_of_data` (open on the final bar). An entry on day D is visible only from D+1 and only if the runner executes before the trade exits (hold 1 to 7 days). Any missed day can lose a trade entirely, and entry price is an open that has already passed. Runner days with a visible open position in replay: 40+ of 223.
3. Outage and gaps. 2026-03-17 to 2026-05-28 (73 days, not only the 116-day outage in the memo) and 2026-06-09 to 2026-10-25 had no evaluations. Entries missed: all 7 longs. Memo section 4 Poisson reasoning should use evaluated days, not 223 calendar days.

## Flags

- No signal or data feed defect found: data complete (BTC/ETH 391 bars each, 2025-10-01 to 2026-10-26, no gaps).
- Runner design flaw (item 2): recommend Engineering replace the replay-derived position check with persisted state (pending breach, zone levels), evaluated every day, plus a missed-evaluation alarm. Owner: Engineering Director.
- ETH-USD yfinance returned transient "possibly delisted" warnings on 2026-06-27 to 2026-10-25 range requests during replay; final data was complete. Retry logic is absent in `download_crypto_ohlcv`.
- Caveat: yfinance data is revised after the fact; replay entries are based on bars as downloaded today.
- Reset-clock criterion (memo section 5): count only days with a verified evaluation.
