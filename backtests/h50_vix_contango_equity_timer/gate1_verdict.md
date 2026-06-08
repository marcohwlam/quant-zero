# Gate 1 v2.0 Verdict: H50 VIX Contango/Backwardation Equity Timer

**Overall: ❌ FAIL (2/7 criteria)**

## Parameters

- `exit_persistence`:    3 days
- `reentry_persistence`: 2 days
- `ratio_threshold`:     1.0
- `init_cash`:           $25,000

## Gate 1 Criteria

| Criterion | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| IS Sharpe > 1.0 | 0.7631 | 1.00 | ❌ FAIL |
| OOS Sharpe > 0.7 | 0.5135 | 0.70 | ❌ FAIL |
| IS MDD > -30% | -0.3446 | -0.30 | ❌ FAIL |
| IS Trade Count >= 120 | 61 | 120 | ❌ FAIL |
| WF Stability >= 4/6 | 5 | 4 | ✅ PASS |
| Param Sensitivity < 50% | 14.3000 | 50.00 | ✅ PASS |
| IS Win Rate > 50% | 0.4262 | 0.50 | ❌ FAIL |

## In-Sample Performance (2008–2021)

- Sharpe:        0.7631
- Max Drawdown:  -34.46%
- Total Return:  298.98%
- Ann. Return:   10.39%
- Ann. Vol:      14.31%
- Win Rate:      42.62%
- Profit Factor: 2.8535
- Trade Count:   61

## Out-of-Sample Performance (2022–2024)

- Sharpe:        0.5135
- Max Drawdown:  -24.50%
- Total Return:  24.68%
- Ann. Return:   7.64%
- Ann. Vol:      17.32%
- Win Rate:      60.00%
- Profit Factor: 2.3841
- Trade Count:   5

## Walk-Forward Stability

**5/6 windows pass (threshold: ≥4)**

| Window | Sharpe | MDD | Win Rate | Trades | Result |
|--------|--------|-----|----------|--------|--------|
| 2008-2009 | -0.0375 | -34.46% | 26.67% | 15 | ❌ |
| 2010-2011 | 0.4467 | -16.95% | 53.33% | 15 | ✅ |
| 2012-2013 | 1.6717 | -9.69% | 66.67% | 3 | ✅ |
| 2014-2015 | 0.3006 | -14.18% | 42.86% | 7 | ✅ |
| 2016-2018 | 0.5917 | -17.28% | 33.33% | 18 | ✅ |
| 2019-2021 | 1.7432 | -9.44% | 75.00% | 8 | ✅ |

## Parameter Sensitivity

**Max Sharpe reduction: 14.3% (threshold: <50%)**

Base Sharpe (IS): 0.7631

| Variant | Sharpe | Trades | Δ vs Base |
|---------|--------|--------|-----------|
| exit=1d | 0.6542 | 159 | -14.3% |
| exit=5d | 0.7203 | 37 | -5.6% |
| reentry=1d | 0.7911 | 67 | +3.7% |
| reentry=3d | 0.8122 | 51 | +6.4% |
| threshold=0.95 | 0.8336 | 117 | +9.2% |
| threshold=1.05 | 0.7816 | 29 | +2.4% |
| aggressive(e=1,r=1) | 0.7019 | 211 | -8.0% |
| conservative(e=5,t=1.05) | 0.7546 | 21 | -1.1% |

## Hard Gate Checks

- HG-1: OOS Sharpe > 0.7 — ❌ FAIL
- HG-2: Same-bar fill — ✅ PASS (close-to-close rotation)
- HG-3: Look-ahead bias — ✅ PASS (signal uses only historical data)
- HG-4: Net-positive IS — ✅ PASS
- HG-5: IS trade count ≥ 120 — ❌ FAIL
- HG-6: MDD < 40% (IS) — ✅ PASS
- HG-7: PDT compliance — ✅ PASS (ETF rotation, no PDT concern)
