# Phase 1 Hypothesis Ranking — March 2026

**Author:** Alpha Research Agent
**Date:** 2026-03-15
**Task:** QUA-36
**Status:** Updated — Post H04 Gate 1 Failure (QUA-79) — v2.0 hypothesis issued

---

## Executive Summary

All 6 Phase 0 hypotheses have been evaluated against Gate 1 criteria (IS Sharpe > 1.0, OOS Sharpe > 0.7, IS MDD < 20%, Win Rate > 50%, Trade Count > 50, Parameter Sensitivity < 30% Sharpe degradation, DSR > 0). Rankings are based on probability of clearing Gate 1, economic rationale strength, sensitivity risk, and capital efficiency at $25K.

**Note on Market Regime:** Updated 2026-03-16 by Research Director (QUA-56) following Market Regime Agent classification (QUA-35).

**Regime (March 2026):** `mildly-trending / high-vol / risk-on / liquid` — **Transition Risk: HIGH**
- VIX: 27.19 (elevated, approaching the 30 structural-break threshold)
- SPY vs 200d SMA: +0.90% (barely above trend — fragile)
- Hurst exponent (60d): 0.732 (trailing uptrend confirmed)
- SPY 1m return: -4.29% (near-term correction in progress)
- Sector breadth: only 4/11 sectors above 50d SMA (defensive rotation underway)

**Ranking changes from original QUA-36 output:**
- H04 Pairs Trading promoted to #1 (from #2): market-neutral construction is the strongest fit for high-vol + regime-uncertain environment
- H02 Bollinger Band moved to #2 (from #1): remains high-priority, but VIX at 27 is approaching the 30 pause trigger — structural break risk elevated
- H05 Momentum Vol-Scaled confirmed at #4 (not promoted): mildly trending regime would normally support promotion, but the near-term correction (-4.29% 1m) and defensive sector rotation argue for keeping it conditional; vol scaling will auto-reduce exposure

**⚠️ Ranking revision — Post QUA-79 (2026-03-16, H04 Gate 1 FAIL):**
- H04 Pairs Trading v1.0 **FAILED** — IS Sharpe 0.50, OOS 0.02, Trade Count 38, Param Sensitivity 104.9% (full analysis: `research/findings/04_pairs_trading_gate1_failure_2026-03.md`)
- Root cause: large-cap equity pairs (XOM/CVX, JPM/BAC, KO/PEP, GS/MS, AMZN/MSFT) not cointegrated in 2018–2023 due to post-2018 business model divergence
- **H04 v2.0 issued** — sector ETF universe (XLF/KRE, XLE/OIH, XLV/IBB, XLP/XLY, GLD/SLV); 63d lookback; entry_zscore 1.5; Alpha Research pre-screen required before backtest
- H05 Momentum Vol-Scaled **confirmed at Rank 2** — schedule in parallel with H04 v2.0 research
- Strategy **NOT retired** — economic rationale valid; only pair selection failed

**⚠️ Ranking revision — Post QUA-74 (2026-03-16, H02 Gate 1 FAIL):**
- H02 Bollinger Band **RETIRED** — Gate 1 FAIL (IS Sharpe 0.029; full analysis in `research/findings/02_bollinger_band_gate1_failure_2026-03.md`)
- H04 Pairs Trading confirmed **clear Rank 1** — market-neutral construction validated (survivorship bias methodology pre-validated, QUA-55); most insulated from the 2018-2021 trending test window
- H05 Momentum Vol-Scaled **promoted to Rank 2** — the 2018-2021 IS test window is a trending regime (COVID crash → recovery, 2019 and 2021 bull run); trend-following / momentum strategies are structurally better suited to this window than mean reversion
- H06 RSI Reversal **demoted to Rank 3** — same mean-reversion structure as H02; carries structural risk in the Gate 1 test window; test after H05 is validated

**⚠️ Hypothesis scoring note (added QUA-74):** The H02 "HIGH probability" projection was based on historical Sharpe from 2010-2017 — a period structurally different from the Gate 1 IS window (2018-2021). Historical Sharpe from non-Gate-1 periods is **not predictive of Gate 1 outcomes**. Future hypothesis ratings must be validated against the 2018-2021 IS window specifically. Trend/crisis-hostile strategies (mean reversion, RSI) should be downgraded when the test window includes sustained trending or crisis episodes.

**Mean-reversion concentration risk — REDUCED (updated QUA-74):** H02 is eliminated, removing one of three mean-reversion strategies from the active queue. H04 (market-neutral) and H06 (RSI reversal) remain. H04's market-neutral construction provides meaningful protection vs. directional regime shifts — it does not rely on prices reverting in a directional market. H06 carries genuine concentration risk if run alongside a directional strategy in a trending regime. Mitigation: run H04 first, then validate H05 (momentum) before scheduling H06.

---

## Ranking Summary

| Rank | Strategy | Gate 1 Probability | Regime Fit (Mar 2026) | Primary Risk | $25K Fit |
|------|----------|--------------------|----------------------|--------------|---------|
| 1 | **Pairs Trading v2.0 (#04-v2)** | **High (conditional on ETF cointegration pre-screen)** | **Strong** — market-neutral, ETF pairs more stable; sector ETF pairs insulated from idiosyncratic business divergence | ETF pairs pre-screen must validate cointegration in 2018–2021 IS window | Good (ETFs, low borrow cost) |
| 2 | **Momentum Vol-Scaled (#05)** | **Conditional** | **Favorable** — 2018-2021 IS window is trending regime; COVID recovery + 2019/2021 bull runs support momentum | IS MDD without crash protection; long-only constraint at $25K | Poor (L/S required) |
| 3 | RSI Short-Term Reversal (#06) | **Moderate** | **Uncertain** — same mean-reversion structure as H02; defer until H04-v2 and H05 validated | PDT compliance, mean-reversion structural risk in Gate 1 window | Good (ETFs) |
| 4 | Dual MA Crossover (#01) | **Low–Moderate** | **Trend-following benefit** — 2019/2021 uptrends visible in IS window; baseline calibration only | IS Sharpe historically below 1.0; win rate < 50% | Good (baseline only) |
| 5 | Multi-Factor Long-Short (#03) | **Uncertain** | **Weak** — factor crowding + data dependency | Factor decay post-2018, fundamental data unavailable in yfinance | Poor |
| — | ~~Pairs Trading v1.0 (#04)~~ | **⛔ FAILED** | **—** | IS Sharpe 0.50; pairs not cointegrated in 2018–2023 test window; v2.0 issued | — |
| — | ~~Bollinger Band Mean Reversion (#02)~~ | **⛔ FAILED** | **—** | IS Sharpe 0.029 — 34× below threshold; hostile test window | — |

---

## Detailed Evaluations

---

### ⛔ RETIRED: Bollinger Band Mean Reversion (Hypothesis 02) — Gate 1 FAIL

**Gate 1 Result: FAILED (QUA-65, 2026-03-15)**

**Outcome:** IS Sharpe 0.029 (threshold > 1.0). Failed 5 of 9 Gate 1 criteria. Auto-disqualified.

**Root cause:** The 2018-2021 IS test window is structurally hostile to mean reversion — the COVID crash (March 2020) and the 2019/2021 bull market trends both systematically impaired the strategy. The historical Sharpe projection of 1.1 was measured on 2010-2017 data (a range-bound regime) and was not predictive of 2018-2021 performance.

**Key lessons:**
- Historical performance from a different epoch is not a valid proxy for Gate 1 IS performance — ratings must use the 2018-2021 window specifically
- OOS windows in 2021 H1 and H2 showed Sharpe 1.63 and 1.11 respectively — the economic rationale is valid, but only in stable low-trend regimes not present in the test window

**Status:** Strategy hypothesis retired from Phase 1. Full analysis: `research/findings/02_bollinger_band_gate1_failure_2026-03.md`. May be reconsidered for a paper trading regime-gated variant (VIX < 20, SPY above 200d SMA, Hurst < 0.55) in a future phase.

---

### Rank 1: Pairs Trading Cointegration (Hypothesis 04)

**Gate 1 Probability: HIGH**

**Why #1 (clear leader post-H02 retirement):**
Pairs Trading has the best historical risk-adjusted characteristics in the active pool: Sharpe 1.3 and MDD -8% (2008-2018). The market-neutral construction is a critical structural advantage — it provides a hedge against broad market direction, meaning the COVID crash and the 2018-2021 trending test window are theoretically far less damaging than for directional mean-reversion strategies (which H02 confirmed are severely impaired by this window). Gate 1 outlook shows "LIKELY PASS" across almost every criterion.

Survivorship bias methodology has been pre-validated (QUA-55) — the key blocking risk is resolved. Backtest can proceed immediately once QUA-55 output is confirmed.

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

**Recommendation:** **Backtest this strategy first (clear Rank 1).** Survivorship bias methodology pre-validated (QUA-55) — confirm QUA-55 output, then proceed immediately. Establish the 5-pair starting universe explicitly and commit to using only the pairs identifiable at backtest start.

---

### Rank 2: Momentum Vol-Scaled (Hypothesis 05) ⬆️ — Promoted post H02 FAIL

**Gate 1 Probability: CONDITIONAL**

**Why #2 (promoted from #4, QUA-74):**
The 2018-2021 IS test window is a trending regime — the COVID crash was followed by a violent V-recovery (April–December 2020), and 2019 and 2021 both saw strong sustained uptrends. Trend-following and momentum strategies are structurally favored in this environment in a way that mean-reversion strategies (H02, H06) are not. H02's Gate 1 failure confirms this: the 2018-2021 window is hostile to mean reversion, which by implication means it should support trend continuation strategies.

H05 Momentum Vol-Scaled has the strongest raw historical Sharpe (1.4 on 2000-2020) and the most rigorous academic backing (Jegadeesh & Titman 1993). The volatility scaling mechanism is a key differentiator — it auto-reduces exposure in high-vol / crash environments, which is exactly what 2020 required. The crash protection rule (50% position reduction when SPY 1-month return < -10%) further mitigates the acute March 2020 risk.

**Critical gate blocker:** The historical MDD of -25% already exceeds the Gate 1 IS MDD threshold of -20%. The backtest must confirm crash protection keeps IS MDD below 20% in the 2018-2021 window, specifically through March 2020.

**Key risks:**
- IS MDD failure remains the primary gate blocker. Crash protection must function correctly in the March 2020 drawdown window.
- The 2020 COVID crash/recovery dynamic cuts both ways: protection triggers during the crash but also keeps positions reduced during the April–December 2020 recovery rally — this may reduce IS Sharpe.
- Cross-sectional momentum crowding post-2018 may reduce IS Sharpe below 1.0; must be confirmed in the specific 2018-2021 window.
- $25K constraint: long-only top-decile variant is the only viable implementation; the short leg (which drives much of the alpha) cannot be executed at this capital level.

**Refinement opportunities:**
- Tighten crash protection trigger to -7% or -8% SPY monthly to activate faster in fast-moving markets like March 2020
- Volatility targeting (inverse-vol weighting) is the most differentiated feature — retain in all variants
- Test long-only top-decile variant first at the $25K scale

**Gate 1 outlook:**
- IS Sharpe > 1.0: **LIKELY** (conditional on 2018-2021 momentum not showing severe decay; trending regime helps)
- OOS Sharpe > 0.7: **UNCERTAIN** (momentum crashes risk in OOS windows; COVID recovery tailwind may not persist)
- IS MDD < 20%: **AT RISK** — this is the primary gate blocker; crash protection must work in March 2020
- Win Rate > 50%: **UNCERTAIN** (monthly rebalance definition makes this complex)
- Trade Count > 50: **PASS**
- Parameter Sensitivity: **LIKELY PASS** (medium sensitivity; inverse-vol weighting is robust)

**Recommendation:** **Backtest second**, after Pairs Trading. MDD is the gate. If crash protection keeps IS MDD under 20%, this strategy is the strongest remaining trend-following candidate for Phase 1. If not, explore tightening the crash protection trigger before retiring.

---

### Rank 3: RSI Short-Term Reversal (Hypothesis 06) ⬇️ — Demoted post H02 FAIL

**Gate 1 Probability: MODERATE (conditional — same structural risk as H02)**

**Why #3 (demoted from prior Rank 3, QUA-74):**
RSI short-term reversal has solid empirical backing (KB historical Sharpe 1.2, MDD -11%) and a well-documented theoretical basis (Connors RSI(2)). The expected win rate of 60-70% easily clears the Gate 1 50% threshold. The short holding period (1-5 days) keeps drawdowns naturally contained.

**Important caveat post H02 failure (QUA-74):** H06 is a mean-reversion strategy with the same structural weakness as H02. The 2018-2021 Gate 1 IS window contains the COVID crash and strong directional trends — H02 produced an IS Sharpe of 0.029 in this exact environment. H06's 200d SMA filter ("sit out" when below trend) is a meaningful protection H02 lacked, but it is not guaranteed to produce a materially better outcome. The H06 backtest must be watched carefully for the same pattern: IS Sharpe near zero, OOS Sharpe reasonable only in post-crash recovery windows.

The 200-day SMA filter is a non-negotiable structural element that significantly improves behavior in trending markets. With this filter in place, the 2022 bear market becomes a "sit out" period rather than a drawdown-generating period (instruments below 200d SMA are not traded long). This gives H06 a structural edge over H02 which lacked this filter — but the COVID crash (2020 Q1) is still a risk window: the 200d SMA break may lag the actual crash by weeks.

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

**Recommendation:** **Backtest third** (after H04 and H05). Run with the 3-ETF long-only variant as the first test. Track weekly round-trip count in all walk-forward windows. Flag any window with > 3 average weekly trades as a live-trading concern. Explicitly verify win/loss ratio alongside win rate. **Watch for H02-pattern failure** (IS Sharpe near zero due to 2018-2021 trending regime) — if the 200d SMA filter does not provide sufficient regime protection, H06 should be deprioritized similarly to H02.

---

*(H05 Momentum Vol-Scaled evaluation moved to Rank 2 — see above)*

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

### Rank 4: Dual Moving Average Crossover (Hypothesis 01)

**Gate 1 Probability: Low–Moderate (re-evaluated post H02 FAIL)**

**Why #4 (re-evaluated post QUA-74):**
The Dual MA Crossover is primarily a baseline/benchmark strategy, but deserves re-evaluation in light of H02's failure. The Gate 1 IS window (2018-2021) includes strong uptrends (2019 bull, 2020 recovery, 2021 bull) that trend-following strategies like DMA Crossover benefit from. Historical Sharpe of 0.6 on 2005-2020 data may understate performance on the 2018-2021 window specifically. However, it still carries structural weaknesses: win rate < 50% by design (trend-following payoff) and documented whipsaw behavior per Market Regime Agent classification. Historical Sharpe of 0.6 on a diversified ETF basket (2005-2020) is below the Gate 1 IS threshold of > 1.0. Even with an optimized multi-ETF basket, clearing 1.0 IS Sharpe is unlikely given the well-documented crowding of this signal. Trend-following strategies also have win rates of 40-45% (relying on large wins to compensate for frequent small losses), which is structurally below the Gate 1 > 50% win rate requirement.

This strategy belongs to Phase 1 only as a benchmark to calibrate the backtest engine. It should not consume priority backtest slots.

**Key risks (primary):**
- IS Sharpe structurally below Gate 1 threshold on liquid ETFs
- Win rate < 50% by design (trend-following payoff profile)
- Window-length sensitivity is well-documented — parameter stability testing will likely reveal fragility

**Recommendation:** **Run as the engine calibration/baseline test** — useful to confirm the backtest infrastructure is working correctly. Do not prioritize as a Gate 1 candidate. If the engine is confirmed working on this simple strategy, move to higher-priority strategies immediately.

---

## Cross-Strategy Observations

### Regime Dependency (Updated — Official Classification Available)
Market Regime Agent classification (QUA-35) delivered: `mildly-trending / high-vol / risk-on / liquid` with **HIGH transition risk**.

**Current regime impacts:**
- **High-vol (VIX 27.19):** Favors market-neutral (H04 Pairs Trading). Disfavors directional mean-reversion (H02 Bollinger Band faces structural-break risk at VIX > 30; H06 RSI generates more signals but at lower quality). Disfavors trend-following (H01 DMA in whipsaw mode per regime agent).
- **Mildly trending (Hurst 0.732, trailing uptrend):** Marginally supports Momentum (#05) but the near-term correction (-4.29% 1m) and defensive sector rotation (only 4/11 sectors above 50d SMA) indicate the trend is not broad-based — vol scaling will auto-reduce H05 exposure appropriately.
- **HIGH transition risk:** The most important regime signal. SPY is barely above its 200d SMA (+0.90%), a break would shift the regime to risk-off/bear. This is the primary reason for the mean-reversion concentration risk warning below.

**Pause/escalation triggers to monitor (from Market Regime Agent):**
- SPY breaks 200d SMA (currently at ~656.41) → flag to Research Director and Engineering Director immediately; shift to H04-only running
- VIX sustains > 30 → reduce all mean-reversion exposure 50%; suspend H06 (H02 already retired)
- VIX > 40 → pause all strategies; escalate to CEO

### Shared Failure Modes — Mean Reversion Concentration Risk (REDUCED — updated QUA-74)
~~Three of the 6 strategies are mean reversion~~ H02 is retired. **Two** mean-reversion strategies remain active: Pairs Trading (#04, market-neutral) and RSI Reversal (#06, directional). H04's market-neutral construction significantly reduces its directional regime exposure — it is not impaired by a broad market downtrend in the same way as H02 or H06. The primary residual risk is H06 (RSI Reversal), which shares H02's structural vulnerability to the 2018-2021 trending test window.

**Updated mitigation protocol:**
1. Run H04 Pairs Trading first (market-neutral, most regime-insulated)
2. Run H05 Momentum Vol-Scaled second (trend-following — aligned with Gate 1 IS window regime)
3. Run H06 RSI Reversal third — do not schedule until H04 and H05 results are reviewed; if H04/H05 show issues in the 2018-2021 window, delay H06 and assess
4. If SPY breaks its 200d SMA during Phase 1 testing, pause H06 immediately; continue H04 with monitoring; H05 vol scaling will auto-reduce exposure

### Parameter Sensitivity — Common Thread
`entry_zscore` (Pairs) is HIGH sensitivity. The Overfit Detector Agent should be briefed to specifically stress-test this parameter in its ±20% perturbation analysis. Note: `entry_std` (Bollinger Band) is now moot — H02 is retired.

### $25K Capital Constraint Summary
| Strategy | $25K Implementation | Notes |
|----------|--------------------|----|
| ~~Bollinger Band (#2)~~ | **⛔ RETIRED** | Gate 1 FAIL — eliminated |
| Pairs Trading (#4) | **Marginal** | 5-8 pairs max; margin required |
| Momentum (#5) | **Poor** | Long-only only; sacrifices alpha |
| RSI Reversal (#6) | **Good** | 1-3 ETF positions, long-only |
| DMA Crossover (#1) | **Good** | ETF basket, swing trade |
| Multi-Factor L/S (#3) | **Poor** | Long-only only; fundamental data needed |

---

## Phase 1 Backtest Priority Queue

**Recommended order for Phase 1 iteration allocation** *(updated 2026-03-16, QUA-74 — post H02 Gate 1 FAIL revision):*

1. **Pairs Trading v2.0 (#04-v2)** — sector ETF universe (XLF/KRE, XLE/OIH, XLV/IBB, XLP/XLY, GLD/SLV); 63d lookback; entry_zscore 1.5; ETF pairs immune to business model divergence that broke v1.0; **requires Alpha Research cointegration pre-screen before backtest** (see `04_pairs_trading_cointegration_v2.md`)
2. **Momentum Vol-Scaled (#05)** ⬆️ *promoted from #4* — trending regime (2018-2021) is structurally favorable for momentum; MDD is the gate (crash protection must keep IS MDD < 20% through March 2020); run second
3. **RSI Short-Term Reversal (#06)** — mean-reversion structural risk (same category as retired H02); PDT tracking mandatory; run third, only after H04 and H05 results reviewed; watch for H02-pattern IS Sharpe collapse
4. **DMA Crossover (#01)** — baseline calibration only; trend-following payoff may benefit from 2018-2021 window; run to validate backtest engine; do not treat as primary Gate 1 candidate
5. **Multi-Factor Long-Short (#03)** — defer pending Engineering Director confirmation of fundamental data availability (yfinance does not have P/E, P/B, ROE); regime fit is also weak (factor crowding in high-vol)
6. ~~**Bollinger Band Mean Reversion (#02)**~~ — **RETIRED** — Gate 1 FAIL (IS Sharpe 0.029)

---

## Dependencies and Open Items

| Item | Owner | Priority |
|------|-------|----------|
| Market Regime classification | Market Regime Agent | ✅ Complete — QUA-35 delivered |
| Fundamental data availability confirmation (P/E, P/B, ROE) | Engineering Director | High — gating for Strategy #03 |
| Survivorship bias methodology validation for Pairs Trading | Overfit Detector Agent | ✅ Pre-validated — QUA-55 done; confirm output before backtest launch |
| PDT weekly trade count tracking in backtest engine | Engineering Director | Medium — required for RSI Reversal live-trading assessment |
| entry_zscore sensitivity flagged for stress testing | Overfit Detector Agent | High — critical sensitivity parameter for Pairs Trading |
| H02 Gate 1 failure root cause analysis + strategic implications | Research Director | ✅ Complete — `research/findings/02_bollinger_band_gate1_failure_2026-03.md` |
| Phase 1 ranking revision post H02 FAIL | Alpha Research Agent | ✅ Complete — QUA-74 (this document) |

---

*Generated by Alpha Research Agent | QUA-36 | 2026-03-15*
*Updated by Research Director | QUA-56 | 2026-03-16 — regime-informed revision following Market Regime Agent classification (QUA-35)*
*Updated by Alpha Research Agent | QUA-74 | 2026-03-16 — post H02 Gate 1 FAIL: H02 retired, H05 promoted to Rank 2, mean-reversion risk reduced, hypothesis scoring methodology updated*
