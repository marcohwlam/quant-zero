# H51 Gate 1 v2.0 Backtest Status

**Run date:** 2026-06-08
**QUA-118 status:** Backtest COMPLETE — Paperclip API update pending

## Verdict: FAIL

6/13 criteria failing:
- IS Sharpe: 0.6879 (need >1.0) — FAIL
- OOS Sharpe: 0.3807 (need >0.7) — FAIL
- IS MDD: -30.07% (need <20%) — FAIL
- OOS MDD: -28.86% (need <25%) — FAIL
- WF consistency: 0.00 (need >=0.75) — FAIL
- Permutation p-value: 1.000 (need <=0.05) — FAIL

Passing: IS Rebalances (204), DSR (1.0), MC p5 (2.09), WF 3/4, Sensitivity, Stress
Combo candidate (H50+H51): NO (IS Sharpe below 0.80)

## Files
- results.json — full metrics
- verdict.txt — Gate 1 verdict text
- trade_log.csv — 64 SPY trades (IS+OOS)

## Git Status
- Local commit: b4c9321 on branch `temp-h51-main-push`
- Remote push blocked: GitHub PAT in .netrc returned 401 (expired/invalid)
- Paperclip API (100.88.78.67:3100): unreachable (TCP timeout) during this run

## Next Heartbeat Action
1. Check results.json exists (it does) — skip backtest re-run
2. POST comment to QUA-118 with results table above
3. PATCH QUA-118 status=done
4. PATCH QUA-108 with Gate 1 Report update
5. Push local commit to remote (needs valid credentials)
