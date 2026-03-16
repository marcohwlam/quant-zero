```
GATE 1 VERDICT: FAIL
Strategy: H24 Combined IBS+TOM v1.0 (Internal Bar Strength + Turn-of-Month)
Date: 2026-03-16

QUANTITATIVE SUMMARY
- IS Sharpe: -0.144  [FAIL — AUTO-DQ: threshold > 1.0]
- OOS Sharpe: 0.1921  [FAIL — AUTO-DQ: threshold > 0.7]
- Walk-forward consistency: OOS/IS ratio 0.620  [FAIL: threshold ≥ 0.70]
- IS Max Drawdown: -13.0%  [PASS: threshold < 20%]
- OOS Max Drawdown: -7.19%  [PASS: threshold < 25%]
- Win Rate: 56.03%  [PASS: threshold > 50%]
- Deflated Sharpe Ratio: -83.66  [FAIL — AUTO-DQ: threshold > 0]
- Parameter sensitivity: 167.78% max Sharpe change  [FAIL — AUTO-DQ: threshold < 30%]
- Walk-forward windows passed: 2/4  [FAIL: threshold ≥ 3/4]
- Post-cost Sharpe: -0.144  [FAIL: threshold > 0.7]
- Test period: 6 years (2018–2023 IS)  [PASS: threshold ≥ 5 years]
- Trade count IS: 373 (62.2/yr)  [PASS: threshold ≥ 100]

AUTOMATIC DISQUALIFICATION FLAGS — TRIGGERED (4)
⛔ IS Sharpe -0.144 < 1.0 → AUTO-REJECT
⛔ OOS Sharpe 0.1921 < 0.7 → AUTO-REJECT
⛔ DSR -83.66 < 0 → AUTO-REJECT
⛔ Parameter sensitivity 167.78% > 30% → AUTO-REJECT

Per criteria.md: any single auto-DQ flag = immediate rejection. 4 auto-DQs confirmed.

STATISTICAL RIGOR
- Monte Carlo p5 Sharpe: -1.809 (worst 5th pct is deeply negative)
- Monte Carlo median Sharpe: -0.450 (central estimate is negative — no edge)
- Bootstrap 95% CI: [-0.780, 0.620] (CI spans negative; true Sharpe almost certainly ≤ 0)
- Permutation p-value: 0.517 (>> 0.05 — performance is indistinguishable from random)
- Market impact: 0.0071 bps (negligible — cost not the issue; alpha is the issue)

WALK-FORWARD ANALYSIS — FAIL (2/4 windows)
- W1: IS 2018-2019 / OOS 2020 → IS -0.858 / OOS +0.281  [FAIL: IS deeply negative]
- W2: IS 2018-2020 / OOS 2021 → IS -0.403 / OOS +0.481  [PASS: OOS positive]
- W3: IS 2018-2021 / OOS 2022 → IS -0.201 / OOS -0.791  [FAIL: both negative]
- W4: IS 2018-2022 / OOS 2023 → IS -0.342 / OOS +1.147  [PASS: OOS positive]
WF Sharpe std = 0.696 (high variance), WF avg IS = -0.451 (IS is persistently negative)
Note: IS Sharpe is negative across ALL 4 windows — strategy shows no in-sample edge in any period.

REGIME ANALYSIS — FAIL (0/4 regimes meet ≥ 0.8 threshold)
- Pre-COVID 2018-2019: -0.858 (FAIL — IBS leg drags in trending bull market)
- COVID crash 2020: +0.281 (marginal — below threshold)
- Stimulus era 2021: +0.481 (partial — below threshold)
- Rate-shock 2022: -0.791 (FAIL — combined strategy collapses)
Regime criterion (≥ 2/4 pass, incl ≥ 1 stress): FAIL — 0/4 regimes pass ≥ 0.8

KELLY CRITERION ANALYSIS
- IS annualized mean return (mu): -0.0104 (-1.04%/yr from is_total_return -6.21% over 6yr)
- IS annualized volatility (sigma): 0.0722 (7.22%/yr, derived: mu/Sharpe = -0.0104/-0.144)
- Kelly fraction (f* = mu/sigma^2): -0.0104 / (0.0722)^2 = -0.0104 / 0.00521 ≈ -2.00
- Recommended max position (25% Kelly × capital): $0 — Kelly is NEGATIVE
- Binding cap: N/A — negative Kelly means position size = 0
- Kelly flag: NEGATIVE KELLY — strategy actively destroys value; deploy nothing
  A negative Kelly fraction confirms the strategy has no positive edge over the IS period.
  This is consistent with negative IS Sharpe and permutation p-value of 0.517.

QUALITATIVE ASSESSMENT
- Economic rationale: WEAK
  IBS mean reversion and TOM calendar effects are individually documented in literature,
  but the combined strategy shows net-negative IS performance across all regimes.
  The IBS leg (mean reversion) and TOM leg (momentum/seasonality) may structurally
  conflict — IBS fades intraday extremes while TOM buys near month-end highs.
  Combined OR-logic creates excessive entry frequency with diluted alpha per trade.
- Look-ahead bias: NONE DETECTED
  OOS data quality 100%. SMA/ATR computed on warmup data outside backtest window.
  Survivorship bias flag: false. look_ahead_bias_flag: false.
- Overfitting risk: HIGH
  - DSR z = -83.66 (3rd worst in pipeline, behind only H21 -110.51 and H23 ~-100)
  - Permutation p = 0.517 confirms performance is random noise
  - Sensitivity 167.78%: TOM entry day shift (+1 day: -0.261 vs base -0.144) is highly unstable
  - IS Sharpe negative across all 4 WF windows — no in-sample regime where strategy works
  - 8 free parameters across IBS and TOM legs — complexity penalty severe (DSR -83.66 confirms)

ROOT CAUSE ANALYSIS
1. IBS leg underperformance: IBS mean reversion relies on intraday bar extremes. In a
   predominantly trending bull market (2018-2023), intraday reversals are unreliable;
   the strategy repeatedly fades breakouts rather than capturing them.
2. TOM leg dilution: The TOM calendar effect was diluted by the 50/50 capital split with
   the loss-making IBS leg. TOM alone (H29 with regime filter) is the cleaner H28/H24
   refinement path.
3. Parameter interaction: 8 free parameters (ibs_entry, ibs_exit, max_hold, vix_threshold,
   ibs_alloc, tom_alloc, tom_entry_day, tom_exit_day) create excessive optimization surface.
   DSR -83.66 reflects the full penalty for this parameter count at negative IS Sharpe.
4. No regime filter: Without a 200-SMA regime filter, the strategy enters indiscriminately
   in both bull and bear regimes, causing the rate-shock 2022 failure.

RECOMMENDATION: FAIL — Retire H24 Combined IBS+TOM v1.0
CONFIDENCE: HIGH (4 auto-DQs, negative Kelly, permutation p=0.517, IS negative in all WF windows)
CONCERNS:
- H24 represents the second consecutive combined-signal failure (after H28): combining
  two separate calendar signals (IBS+TOM) without a regime filter consistently produces
  negative IS Sharpe due to signal interference.
- The remaining viable path is H29 (TOM+Pre-Holiday+200-SMA) which removes IBS entirely
  and adds a bear-market regime filter. H29 should NOT repeat the IBS combination.
- Pipeline note: H24 and H28 failures indicate that OR-logic signal combination without
  regime filters is structurally unreliable. Future combined strategies must address this.

NEXT STEPS (post-FAIL):
1. Retire H24 Combined IBS+TOM v1.0 — no revision path recommended
2. H29 (TOM+Pre-Holiday+200-SMA) is the active Gate 1 candidate — already in backtest queue
3. Research Director may evaluate IBS as a standalone strategy (without TOM combination)
   in a future hypothesis, but only with a regime filter and reduced parameter count

ISSUED BY: Risk Director (agent 0ba97256-23a8-46eb-b9ad-9185506bf2de)
BACKTEST FILES: backtests/h24_combined_ibs_tom/H24_CombinedIBSTOM_2026-03-16.json
OVERFIT ANALYSIS: Delegated to Overfit Detector — QUA-248 (pending)
PARENT TICKET: QUA-225
```
