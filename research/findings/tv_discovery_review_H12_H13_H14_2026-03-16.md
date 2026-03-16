# TV Discovery Review — H12, H13, H14

**Date:** 2026-03-16
**Reviewer:** Research Director
**Source ticket:** QUA-140 (TV Discovery second weekly run)
**Origin:** QUA-108 TradingView Ideas pipeline

---

## Summary Verdicts

| Hypothesis | Title | Verdict | Gate 1 Confidence |
|---|---|---|---|
| H12 | SuperTrend ATR Momentum | **FORWARD** (conditional) | Moderate — regime gate mandatory |
| H13 | VWAP Anchor Reversion | **FORWARD** (conditional) | Marginal — IC confirmation required |
| H14 | OU Mean Reversion Cloud | **FORWARD** (conditional) | Moderate-High — strongest novel signal in pipeline |

---

## H12 — SuperTrend ATR Momentum

**Verdict: FORWARD to Engineering Director**

### Checklist
- [x] Clear entry/exit logic — Yes. SuperTrend band flip (price crosses above/below ATR-scaled band). Explicit long/short entry and exit on opposite flip.
- [x] Market regime context identified — Yes. VIX < 30 filter + 200-day SMA directional filter recommended.
- [x] Economic rationale — Solid. ATR-adaptive trend filter documented in Moskowitz/Ooi/Pedersen (2012 TSMOM), Hurst et al. (2017 AQR). Genuine structural improvement over H01 EMA crossover: volatility-adaptive vs fixed-lag.
- [x] Alpha decay analysis — Complete. Half-life 12–18 days; cost survival confirmed for swing holds > 5 days.
- [x] Signal combination policy — N/A (single signal).
- [x] ML anti-snooping — N/A (rule-based).
- [x] TV source caveat — Present. KivancOzbilgic SuperTrend STRATEGY. Cherry-pick risk HIGH — fresh IS/OOS split required.

### Conditions for Engineering Director

1. **Regime gate is mandatory** — backtest must include VIX < 30 filter AND 200-day SMA long-only gate. Do not run without regime conditioning. Without it, SuperTrend degrades to near H01 performance in choppy markets.
2. **ATR multiplier sensitivity** — sweep `ATR_multiplier` across 1.5–3.5 and `ATR_lookback` across 7–20. Document sensitivity heatmap. Gate 1 will reject if performance is localized to a narrow parameter window (< 30% Sharpe degradation on ±20% perturbation required).
3. **Sub-period testing required** — explicitly test 2022 bear market sub-period. Trend-following strategies should outperform (2022 was a strong trending bear); if H12 fails 2022, the strategy is structurally flawed.
4. **Universe** — SPY, QQQ, IWM ETFs for initial test. Do not expand to individual stocks in Gate 1.
5. **No shortside in Gate 1** — long-only first. If long-only clears IS Sharpe ≥ 1.0, add short-side in Gate 2 if capital permits.

### Key Risks
- Gate 1 IS Sharpe > 1.0 is unlikely without regime filter (estimated 0.6–0.9 raw)
- SuperTrend is among the most-used TradingView indicators — edge crowding at retail level is real, though at $25K swing scale it likely persists
- 2010–2024 IS window includes two major trending bull runs that artificially inflate unconditioned metrics

---

## H13 — VWAP Anchor Reversion

**Verdict: FORWARD to Engineering Director**

### Checklist
- [x] Clear entry/exit logic — Yes. Price touches VWAP ±2 SD band, entry on reversion confirmation bar, TP at VWAP center, SL at ±3 SD, time stop 5 days.
- [x] Market regime context identified — Yes. ATR percentile filter (lower 50th of 60-day distribution) + macro event exclusion window (±2 days FOMC/CPI/NFP).
- [x] Economic rationale — Strong microstructure grounding. Berkowitz/Logue/Noser (1988), Madhavan & Cheng (1997) document institutional VWAP benchmarking. Genuinely distinct from H02 Bollinger Band (volume-weighted mean vs price-only SMA; daily session reset vs rolling).
- [x] Alpha decay analysis — Complete. Half-life 3–5 days; cost survival confirmed for ≥ 3-day holds on ETFs.
- [x] Signal combination policy — N/A (single signal).
- [x] ML anti-snooping — N/A (rule-based).
- [x] TV source caveat — Present. HYE0619 VWAP Mean Reversion Strategy. Cherry-pick risk MEDIUM.

### Data Feasibility Note (Required Engineering Director Action)

Daily VWAP from yfinance OHLCV uses `Typical Price = (H + L + C) / 3`. This is NOT true session VWAP (which requires intraday tick data). For multi-day anchored VWAP, the rolling typical price × volume is an approximation.

Engineering Director must document which VWAP variant is used:
- **Option A:** Typical price as VWAP proxy (feasible with yfinance, but not true institutional VWAP)
- **Option B:** True intraday VWAP via 1-min data from Polygon/Alpaca (preferred but requires infrastructure)

If Option A is used, lower the IC expectation — the mean-reversion may be weaker than institutional VWAP theory predicts.

### Conditions for Engineering Director

1. **Data feasibility documentation required** — specify in backtest spec whether true VWAP or typical-price proxy is used.
2. **IC validation gate** — confirm VWAP signal IC > 0.02 in IS data before proceeding with full Gate 1 parameter sweep. Given pre-cost IR estimate of 0.2–0.33 (marginal), IC validation is the primary gate.
3. **Macro event filter required** — exclude entries ±2 days of FOMC, CPI, NFP. Events create trending breakouts that invalidate the VWAP reversion mechanism.
4. **Long-only in Gate 1** — short-side requires margin; PDT complications at $25K. Test long-only (fade lower band only) first.
5. **Sub-period testing** — 2020 COVID crash (sharp directional moves, VWAP frequently breached without reversion) and 2022 bear (persistent downtrend) are the critical stress tests.

### Key Risks
- Pre-cost annualized IR of 0.2–0.33 is the lowest of the three hypotheses — Gate 1 pass depends heavily on regime filter effectiveness
- yfinance VWAP proxy may reduce IC sufficiently to make this strategy unviable without intrabar data
- Post-2022 inflationary/volatile regime may have degraded the mean-reversion mechanism

---

## H14 — OU Mean Reversion Cloud (Ornstein-Uhlenbeck)

**Verdict: FORWARD to Engineering Director**

### Checklist
- [x] Clear entry/exit logic — Yes. OU parameter fitting on rolling 60-bar window; entry at ±1.5σ_ou when κ > 0 (confirmed mean-reverting regime); TP at OU mean; SL at ±3σ_ou; regime exit when κ drops below significance.
- [x] Market regime context identified — Yes. Built-in native regime detection: κ > 0 with p < 0.05 required before any entry. Strategy self-disables in trending regimes.
- [x] Economic rationale — Strongest of the three. OU process is the canonical mean-reversion model (Vasicek 1977). Single-asset OU application with regime self-detection is academically grounded (Avellaneda & Lee 2010, Chan 2013). Not pairs trading — genuinely distinct from H04.
- [x] Alpha decay analysis — Complete. Half-life dynamically estimated per trade (5–20 days typical). IC estimate 0.04–0.07 with regime conditioning.
- [x] Signal combination policy — N/A (single signal).
- [x] ML anti-snooping — N/A (rule-based parameter fitting, not ML). OU fitting uses OLS regression in-sample; no OOS data leakage.
- [x] TV source caveat — Present. AlgoFyre OU Cloud indicator (not a strategy backtest — low cherry-pick risk). Cherry-pick risk is primarily in parameter selection during our own backtesting.

### Why H14 Stands Out

H14 is the most sophisticated mean-reversion hypothesis submitted to date. Its key differentiators:

1. **Native regime detection:** κ significance filter means the strategy doesn't trade in non-mean-reverting environments. Unlike H02 (Bollinger) or H06 (RSI) which generate signals regardless of regime, H14 only enters when the OU model confirms stationarity.

2. **Dynamically calibrated bands:** σ_ou widens during volatile periods and tightens during stable regimes — reducing false signals without requiring a separate regime gate.

3. **Low crowding risk:** OU parameter fitting is computationally non-trivial. This strategy is not implementable by the average retail trader following a TradingView script. Institutional stat-arb desks use OU for pairs trading, not single-asset; this fills a niche between retail mean reversion and institutional pairs.

4. **Gate 1 IS Sharpe > 1.0 assessed as LIKELY** — if regime conditioning is effective, expected IS Sharpe 0.8–1.3. This is the highest Gate 1 confidence of any remaining hypothesis in the pipeline.

### Conditions for Engineering Director

1. **OU lookback sensitivity is the primary parameter** — sweep `OU_lookback_window` across 30/45/60/90 bars. This is the key parameter that must show robustness. Document heatmap.
2. **κ significance threshold test** — test both p < 0.05 and p < 0.10 cutoffs. Report the difference in entry frequency and Sharpe.
3. **Universe: ETFs first** — start with SPY, QQQ, IWM, and sector ETFs (XLE, XLF, XLK). Do NOT include individual stocks in Gate 1. OU behavior on individual equities is more erratic (fundamental shifts break stationarity).
4. **Half-life filter** — enforce `t_half < 30 days` as coded. Report how many entries are filtered by this constraint.
5. **Sub-period testing** — 2022 bear market is the key test. Mean-reverting OU with κ > 0 on ETFs should self-detect and reduce/stop trading during the 2022 persistent downtrend. If the strategy still loses significantly in 2022, investigate whether κ significance filter is operating correctly.
6. **Spurious OU fitting guard** — with a 60-bar window, the OLS regression can find "significant" κ by chance ~5% of the time even in trending data. Report how often the κ filter fires in IS data vs how often the trade is profitable.

### Key Risks
- OU model can find spurious mean reversion in finite samples — significance test critical
- IS window 2018–2023 includes the 2022 bear market; self-detection of regime shifts is the critical mechanism to verify
- Lookback window choice (30 vs 90 bars) can produce very different results

---

## Research Director Sign-Off

All three hypotheses meet the forward criteria:
- Economic rationale documented
- Entry/exit logic is codifiable
- Alpha decay analysis complete
- No ML anti-snooping concerns
- TV source caveat section present
- Novel signal insight confirmed vs H01–H11 universe

**Priority order for Engineering Director backtest queue:**
1. **H14 (OU Mean Reversion Cloud)** — highest Gate 1 confidence; novel model-based approach; low crowding risk
2. **H12 (SuperTrend ATR Momentum)** — moderate confidence; trend-following during 2022 bear is valuable sub-period test
3. **H13 (VWAP Anchor Reversion)** — marginal pre-cost IR; IC validation gate may reject; lower priority

**Forwarded to Engineering Director:** 2026-03-16
**Next review trigger:** Gate 1 results for each hypothesis

---

*Research Director | QUA-151 | 2026-03-16*
