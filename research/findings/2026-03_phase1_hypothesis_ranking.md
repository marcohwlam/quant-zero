# Phase 1 Hypothesis Ranking — March 2026

**Author:** Alpha Research Agent
**Date:** 2026-03-15
**Task:** QUA-36
**Status:** Ready for Research Director Review

---

## Executive Summary

All 6 Phase 0 hypotheses have been evaluated against Gate 1 criteria (IS Sharpe > 1.0, OOS Sharpe > 0.7, IS MDD < 20%, Win Rate > 50%, Trade Count > 50, Parameter Sensitivity < 30% Sharpe degradation, DSR > 0). Rankings are based on probability of clearing Gate 1, economic rationale strength, sensitivity risk, and capital efficiency at $25K.

**Note on Market Regime:** The Market Regime Agent classification for March 2026 (`research/regimes/2026-03_regime_classification.md`) was not yet available at time of writing. Rankings below are based on hypothesis analysis and historical analogs. The regime-dependent rankings (Bollinger Band vs. Pairs Trading) may shift once the official classification is available. The Research Director should revisit this ranking after the Market Regime Agent completes its task.

---

## Ranking Summary

| Rank | Strategy | Gate 1 Probability | Primary Risk | $25K Fit |
|------|----------|--------------------|--------------|---------|
| 1 | Bollinger Band Mean Reversion (#02) | **High** | entry_std sensitivity | Good (ETFs) |
| 2 | Pairs Trading Cointegration (#04) | **High** | Survivorship bias, margin constraints | Marginal |
| 3 | RSI Short-Term Reversal (#06) | **Moderate** | PDT compliance, high param sensitivity | Good (ETFs) |
| 4 | Momentum Vol-Scaled (#05) | **Conditional** | IS MDD exceeds threshold without crash protection | Poor (L/S required) |
| 5 | Multi-Factor Long-Short (#03) | **Uncertain** | Factor decay post-2018, data requirements | Poor |
| 6 | Dual MA Crossover (#01) | **Low** | IS Sharpe chronically below 1.0, win rate < 50% | Good (baseline only) |

---

## Detailed Evaluations

---

### Rank 1: Bollinger Band Mean Reversion (Hypothesis 02)

**Gate 1 Probability: HIGH**

**Why #1:**
This is the highest-confidence Gate 1 candidate in the pool. Historical Sharpe of 1.1 on a liquid equity basket (2010-2020) and MDD of -14% both sit comfortably within Gate 1 thresholds. The mean reversion mechanism is one of the most robust in systematic trading — it works across regimes (though best in range-bound/choppy markets) and the ETF universe avoids the earnings-event failures that plague single-stock mean reversion.

The 2018-2023 Gate 1 test period is reasonably favorable for this strategy: the period contains multiple range-bound episodes (2018 Q4 chop, 2019, late 2021, mid-2022 consolidations) broken up by directional moves. A regime filter (suspend when VIX > 30 or instrument in confirmed downtrend) will reduce performance during the 2022 bear market leg but is well worth the protection.

**Key risks:**
- `entry_std` is flagged **HIGH sensitivity** in the knowledge base — this is the single most important parameter to stress-test. The cliff-edge behavior around entry_std = 2.0 must be confirmed NOT to violate the ±20% perturbation rule (range [1.6, 2.4] must all sustain Sharpe within 30% of peak).
- PDT is manageable at $25K with ETF universe and 5+ day target holding periods, but must be confirmed in backtest trade-frequency tracking.
- Regime mismatch risk: the 2022 sustained bear market (full year downtrend) is the most dangerous window — the time-stop and stop-loss rules are critical guard rails during this period.

**Refinement opportunities:**
- Add a VIX-based regime filter (suspend longs when VIX > 30) — this would have reduced damage in March 2020 and the 2022 drawdown
- Test a "decreasing exposure" rule as `entry_std` falls below the signal threshold (scale in rather than full size at first signal)
- ETF basket: SPY, QQQ, XLV, XLF, XLE, IWM — provides sector diversification without single-stock earnings risk

**Gate 1 outlook:**
- IS Sharpe > 1.0: **LIKELY PASS** (historical 1.1; with good implementation, achievable)
- OOS Sharpe > 0.7: **POSSIBLE PASS** (regime mismatches in OOS windows are the risk)
- IS MDD < 20%: **LIKELY PASS** (historical -14%; stops add protection)
- Win Rate > 50%: **LIKELY PASS** (mean reversion typically 55-65%)
- Trade Count > 50: **PASS**
- Parameter Sensitivity: **AT RISK** — entry_std is the critical test; must pass

**Recommendation:** **Backtest this strategy first.** Prioritize validating the entry_std robustness and regime filter impact. If entry_std shows cliff-edge behavior, consider fixing it at 2.0 and testing only lookback_period and max_holding_days as free parameters.

---

### Rank 2: Pairs Trading Cointegration (Hypothesis 04)

**Gate 1 Probability: HIGH**

**Why #2:**
Pairs Trading has the best historical risk-adjusted characteristics in the group: Sharpe 1.3 and MDD -8% (2008-2018). The market-neutral construction is a significant structural advantage — it provides hedge against broad market direction, meaning the 2022 bear market is theoretically less damaging than it would be for directional strategies. Gate 1 outlook shows "LIKELY PASS" across almost every criterion in the hypothesis file.

The low MDD (-8% historical) gives substantial headroom under the Gate 1 20% threshold even if post-2018 conditions are somewhat worse than the historical record.

**Key risks:**
- **Survivorship bias in pair selection** is the most important methodological risk. The backtest MUST use only point-in-time data for pair selection — cannot select the "XOM/CVX" pair today and test it as if we knew in 2018 it would cointegrate. The Overfit Detector Agent should verify this explicitly.
- The historical record is 2008-2018 vs. Gate 1's 2018-2023 test period — there may be regime shifts (e.g., tech pairs like AMZN/MSFT are more volatile and less cointegrated than legacy industrials).
- `entry_zscore` is flagged HIGH sensitivity — same stress-test requirement as entry_std in the Bollinger Band strategy.
- $25K margin constraints are real: 5-8 pairs maximum at $25K. The backtest should use this scaled-down version rather than 20 pairs to avoid overstating live-tradable performance.

**Refinement opportunities:**
- Limit starting pairs to the 5 well-established, liquid pairs listed in the hypothesis (XOM/CVX, JPM/BAC, KO/PEP, GS/MS, AMZN/MSFT) — avoids pair-selection look-ahead bias in the first backtest
- Implement rolling cointegration testing (re-test every 60 days, drop pairs with p-value > 0.05) to handle cointegration breakdown risk
- Use large-cap pairs only to minimize short borrowing cost issues

**Gate 1 outlook:**
- IS Sharpe > 1.0: **LIKELY PASS**
- OOS Sharpe > 0.7: **LIKELY PASS** (market-neutral = more regime-consistent)
- IS MDD < 20%: **LIKELY PASS** (historical -8%; large cushion)
- Win Rate > 50%: **LIKELY PASS** (mean reversion character; 55-65% expected)
- Trade Count > 50: **LIKELY PASS**
- Parameter Sensitivity: **LIKELY PASS** (lookback and stop_zscore low-sensitivity; entry_zscore the risk)
- Survivorship Bias: **FLAG** — must be explicitly verified by Overfit Detector

**Recommendation:** **Backtest this strategy second.** Establish the 5-pair starting universe explicitly and commit to using only the pairs identifiable at backtest start. Flag the survivorship bias concern to the Overfit Detector Agent as a mandatory check.

---

### Rank 3: RSI Short-Term Reversal (Hypothesis 06)

**Gate 1 Probability: MODERATE**

**Why #3:**
RSI short-term reversal has solid empirical backing (KB historical Sharpe 1.2, MDD -11%) and a well-documented theoretical basis (Connors RSI(2)). The expected win rate of 60-70% easily clears the Gate 1 50% threshold. The short holding period (1-5 days) keeps drawdowns naturally contained. Of the mean reversion strategies, this one has the most parameter sensitivity uncertainty — rsi_period and the entry threshold are both flagged HIGH sensitivity but have not been characterized in a prior backtest.

The 200-day SMA filter is a non-negotiable structural element that significantly improves behavior in trending markets. With this filter in place, the 2022 bear market becomes a "sit out" period rather than a drawdown-generating period (instruments below 200d SMA are not traded long).

**Key risks:**
- **PDT compliance in live trading** is a real and specific constraint. If signals fire more than 3 times per week on the ETF universe, live trading at $25K will miss signals. The backtest must track weekly round-trip count.
- The win/loss ratio may be unfavorable: high win rate (small gains) combined with hard stops (larger losses) creates an asymmetric payoff structure. Must verify average win > average loss simultaneously with Win Rate > 50%.
- Parameter sensitivity on rsi_period and rsi_oversold_threshold has not been characterized — this is the biggest unknown. The Gate 1 ±20% perturbation test will be the first characterization.
- 6 parameters is at the Gate 1 limit — consider fixing rsi_overbought_threshold (long-only first test) to reduce to 5 free parameters.

**Refinement opportunities:**
- Start with long-only variant (ETF universe, 200d SMA filter mandatory) — reduces complexity and avoids PDT/margin issues on the short side
- Use a 3-ETF universe (SPY, QQQ, IWM) for first backtest to limit signal frequency and stay within PDT bounds
- Consider "cumulative RSI" entry (sum of 2 consecutive days' RSI < 35) instead of single-day RSI threshold — may improve quality filter and reduce overfitting on single threshold value

**Gate 1 outlook:**
- IS Sharpe > 1.0: **POSSIBLE** (1.2 in KB; implementation-dependent)
- OOS Sharpe > 0.7: **UNCERTAIN** (2022 bear market is the main risk window for this strategy — 200d SMA filter must work)
- IS MDD < 20%: **LIKELY PASS** (short holding period + hard stop = natural containment)
- Win Rate > 50%: **LIKELY PASS** (expected 60-70%)
- Trade Count > 50: **PASS** (high signal frequency)
- Parameter Sensitivity: **UNKNOWN** (first backtest will characterize this)
- PDT Compliance (live trading): **AT RISK** — must track

**Recommendation:** **Backtest third.** Run with the 3-ETF long-only variant as the first test. Track weekly round-trip count in all walk-forward windows. Flag any window with > 3 average weekly trades as a live-trading concern. Explicitly verify win/loss ratio alongside win rate.

---

### Rank 4: Momentum Vol-Scaled (Hypothesis 05)

**Gate 1 Probability: CONDITIONAL**

**Why #4:**
Momentum vol-scaled has the strongest raw historical Sharpe (1.4 on 2000-2020) and the most rigorous academic backing (Jegadeesh & Titman 1993), but the **historical MDD of -25% already exceeds the Gate 1 IS MDD threshold of -20%**. The crash protection mechanism (50% position reduction when SPY 1-month return < -10%) is designed to address this — but the backtest must confirm it actually keeps IS MDD below -20% in the 2018-2023 test period, which includes the COVID crash (March 2020) and the 2022 bear market (the most challenging period for cross-sectional momentum since 2009).

Additionally, the $25K implementation constraint is significant: full long-short quintile portfolios (100+ positions) are impractical at this capital level. A long-only top-decile variant sacrifices a material portion of the alpha (the short leg contributes meaningfully to the Sharpe).

**Key risks:**
- IS MDD failure is the primary gate blocker. Without crash protection functioning correctly, this strategy fails Gate 1 on drawdown.
- The 2020 COVID crash/recovery is the most acute test: the strategy likely suffered a large drawdown in March 2020 AND then was underweight during the violent April-December 2020 recovery (crash protection kept positions reduced).
- Cross-sectional momentum crowding post-2018 may reduce IS Sharpe below 1.0 in the 2018-2023 specific test window.
- Monthly rebalance of a large portfolio generates transaction costs that must be realistically modeled.

**Refinement opportunities:**
- Consider a tighter crash protection trigger (-7% or -8% SPY monthly) to activate protection faster in fast-moving markets like March 2020
- Test the long-only top-decile variant first at the $25K scale — if IS MDD clears 20% and Sharpe > 1.0, this is a viable live-trading implementation
- Volatility targeting (inverse-vol weighting) is the most differentiated feature — retain it in all variants

**Gate 1 outlook:**
- IS Sharpe > 1.0: **LIKELY PASS** (conditional on 2018-2023 momentum decay not being too severe)
- OOS Sharpe > 0.7: **UNCERTAIN** (momentum crashes risk)
- IS MDD < 20%: **AT RISK** — this is the primary gate blocker; crash protection must work
- Win Rate > 50%: **UNCERTAIN** (monthly rebalance definition makes this complex)
- Trade Count > 50: **PASS**
- Parameter Sensitivity: **LIKELY PASS** (medium sensitivity parameters)

**Recommendation:** Test after the top 3 are completed. **MDD is the gate.** If crash protection keeps IS MDD under 20%, this strategy moves up in priority. If not, retire this configuration and explore a modified version with tighter crash protection.

---

### Rank 5: Multi-Factor Long-Short (Hypothesis 03)

**Gate 1 Probability: UNCERTAIN**

**Why #5:**
The highest historical Sharpe (1.8) is on 2010-2018 data — the peak of factor investing's golden era. Gate 1 requires 2018-2023 testing, which is precisely the period of documented factor crowding and decay. This is the most honest uncertainty in the portfolio: the strategy may retain sufficient alpha on 2018-2023 data, or it may fall significantly below the IS Sharpe > 1.0 threshold. There is no strong prior to lean either way.

The practical $25K constraint is also a significant concern: the true long-short implementation (100+ positions, sector-neutral) is simply not executable at $25K without substantial capital (Reg T margin, short borrowing fees, minimum position sizes). The long-only top-quintile adaptation sacrifices market neutrality and a meaningful portion of the alpha.

An additional execution dependency: this strategy requires fundamental data (P/E, P/B, ROE, debt-to-equity) which may not be available through yfinance. **Engineering Director must confirm data availability before committing backtest resources.**

**Key risks:**
- Post-2018 factor alpha decay — the primary uncertainty
- Data availability: fundamental data not available in yfinance (requires separate data source)
- $25K implementation: long-short at this scale is structurally difficult
- 2020 factor crowding event (momentum crash + value trap persistence) is specifically in the Gate 1 test window

**Gate 1 outlook:**
- IS Sharpe > 1.0: **AT RISK** (post-2018 factor decay may push below threshold)
- OOS Sharpe > 0.7: **AT RISK** (same factor decay argument)
- IS MDD < 20%: **LIKELY PASS** (historical -10%; sector-neutral construction is protective)
- Win Rate > 50%: **UNCERTAIN**
- Trade Count > 50: **PASS** (hundreds of trades at monthly rebalance)
- Data Requirements: **FLAG** — Engineering Director must confirm fundamental data source

**Recommendation:** Deprioritize for Phase 1. Allocate backtest resources here only after the top 3-4 strategies have been tested. Flag the fundamental data dependency to Engineering Director immediately — if data is not available, this strategy cannot be tested and should be retired from Phase 1 scope.

---

### Rank 6: Dual Moving Average Crossover (Hypothesis 01)

**Gate 1 Probability: LOW**

**Why last:**
The Dual MA Crossover is a baseline/benchmark strategy, not a primary alpha candidate. Historical Sharpe of 0.6 on a diversified ETF basket (2005-2020) is below the Gate 1 IS threshold of > 1.0. Even with an optimized multi-ETF basket, clearing 1.0 IS Sharpe is unlikely given the well-documented crowding of this signal. Trend-following strategies also have win rates of 40-45% (relying on large wins to compensate for frequent small losses), which is structurally below the Gate 1 > 50% win rate requirement.

This strategy belongs to Phase 1 only as a benchmark to calibrate the backtest engine. It should not consume priority backtest slots.

**Key risks (primary):**
- IS Sharpe structurally below Gate 1 threshold on liquid ETFs
- Win rate < 50% by design (trend-following payoff profile)
- Window-length sensitivity is well-documented — parameter stability testing will likely reveal fragility

**Recommendation:** **Run as the engine calibration/baseline test** — useful to confirm the backtest infrastructure is working correctly. Do not prioritize as a Gate 1 candidate. If the engine is confirmed working on this simple strategy, move to higher-priority strategies immediately.

---

## Cross-Strategy Observations

### Regime Dependency (Without Official Classification)
Without the Market Regime Agent output, ranking assumes a mixed/uncertain current regime. Key regime-contingent notes:
- If current regime is **mean-reverting/choppy** → Bollinger Band (#2) and Pairs Trading (#4) move up significantly; Momentum (#5) moves down
- If current regime is **trending bull** → Momentum (#5) and DMA Crossover (#1) improve; mean reversion strategies see reduced signal quality
- If current regime is **high volatility/risk-off** → Pairs Trading (#4) benefits from market neutrality; Bollinger Band (#2) faces increased structural break risk

**Action item:** Update this ranking once the Market Regime Agent classification is available.

### Shared Failure Modes
Three of the 6 strategies are mean reversion (Bollinger Band, RSI, Pairs Trading). This creates a concentration risk in the hypothesis portfolio — if the current regime is a sustained trend (as in 2022), all three will underperform simultaneously. The Research Director should consider this when deciding how many strategies to run in Phase 1 simultaneously.

### Parameter Sensitivity — Common Thread
`entry_zscore` (Pairs) and `entry_std` (Bollinger Band) are both HIGH sensitivity. The Overfit Detector Agent should be briefed to specifically stress-test these parameters in their ±20% perturbation analysis.

### $25K Capital Constraint Summary
| Strategy | $25K Implementation | Notes |
|----------|--------------------|----|
| Bollinger Band (#2) | **Good** | ETF-only variant, long-only |
| Pairs Trading (#4) | **Marginal** | 5-8 pairs max; margin required |
| RSI Reversal (#6) | **Good** | 1-3 ETF positions, long-only |
| Momentum (#5) | **Poor** | Long-only only; sacrifices alpha |
| Multi-Factor L/S (#3) | **Poor** | Long-only only; fundamental data needed |
| DMA Crossover (#1) | **Good** | ETF basket, swing trade |

---

## Phase 1 Backtest Priority Queue

**Recommended order for Phase 1 iteration allocation:**

1. **Bollinger Band Mean Reversion** — highest Gate 1 confidence; test entry_std robustness as primary focus
2. **Pairs Trading Cointegration** — strong Gate 1 outlook; survivorship bias methodology must be validated first
3. **RSI Short-Term Reversal** — solid empirical basis; PDT tracking is mandatory deliverable from backtest
4. **Momentum Vol-Scaled** — conditional on crash protection keeping MDD < 20%; test after top 3
5. **DMA Crossover** — baseline calibration only; run early to validate backtest engine, not as Gate 1 candidate
6. **Multi-Factor Long-Short** — defer pending Engineering Director confirmation of fundamental data availability

---

## Dependencies and Open Items

| Item | Owner | Priority |
|------|-------|----------|
| Market Regime classification | Market Regime Agent | High — needed to finalize regime-dependent rankings |
| Fundamental data availability confirmation (P/E, P/B, ROE) | Engineering Director | High — gating for Strategy #03 |
| Survivorship bias methodology validation for Pairs Trading | Overfit Detector Agent | High — must be confirmed before Pairs Trading backtest is accepted |
| PDT weekly trade count tracking in backtest engine | Engineering Director | Medium — required for RSI Reversal live-trading assessment |
| entry_std and entry_zscore sensitivity flagged for stress testing | Overfit Detector Agent | High — these are the critical sensitivity parameters across top 2 strategies |

---

*Generated by Alpha Research Agent | QUA-36 | 2026-03-15*
