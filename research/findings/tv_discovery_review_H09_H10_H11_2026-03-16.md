# TV Discovery Review — H09, H10, H11

**Date:** 2026-03-16
**Reviewer:** Research Director
**Source tickets:** QUA-128 (H09), QUA-129 (H10), QUA-130 (H11)
**Origin:** QUA-117 TV Discovery first run (Alpha Research Agent)

---

## Summary Verdicts

| Hypothesis | Title | Verdict | Gate 1 Confidence |
|---|---|---|---|
| H09 | TQQQ Weekly Snapback | **FORWARD** (conditional) | Marginal — regime-gated |
| H10 | Crypto Equal H/L Reversal | **FORWARD** (conditional) | Uncertain — crowding risk |
| H11 | CVD-Confirmed Breakout | **FORWARD** (conditional) | Moderate — CVD IC validation required |

---

## H09 — TQQQ Weekly Snapback (QUA-128)

**Verdict: FORWARD to Engineering Director**

### Checklist
- [x] Clear entry/exit logic — Yes. Entry on ≥N% weekly drawdown, exit TP/SL/time-stop.
- [x] Market regime context identified — Yes. QQQ 200-SMA gate + VIX < 30 gate.
- [x] Economic rationale — Strong. Cheng & Madhavan (2009), Avellaneda & Zhang (2010) document leveraged ETF volatility-decay overshoot mechanism.
- [x] Alpha decay analysis — Complete. Half-life ~3–4 days; cost survival confirmed (TQQQ spread ~0.04% round-trip, 1% target provides buffer).
- [x] Signal combination policy — N/A (single signal).
- [x] ML anti-snooping — N/A (rule-based).

### Conditions for Engineering Director

1. **Regime gate is mandatory** — backtest must include QQQ 200-SMA gate (disable entries when QQQ < 200-day SMA) AND VIX < 30 gate. Do not run without regime filter.
2. **Sub-period testing required** — explicitly test 2008–2010 (GFC), 2022 bear market sub-periods separately. TASC source likely cherry-picks 2020–2025 bull regime.
3. **TASC crowding caveat** — TASC March 2026 publication means potential crowding by retail readers. If edge shows rapid post-publication decay in OOS data, flag for Research Director.
4. **Parameter sensitivity** — sweep `entry_decline_pct` (2.5–7.0%) and `vix_gate` (25–35) across a grid; flag if Gate 1 performance is localised to a narrow window.

### Key Risks
- IS Sharpe > 1.0 unlikely without regime filter (Sharpe marginal even with filter)
- TASC strategies have survivorship bias; the 1% target may be curve-fitted
- 2022 bear market is the critical OOS test — H09 may FAIL if regime dependency is severe (cf. H08 crypto momentum)

---

## H10 — Crypto Equal H/L Liquidity Reversal (QUA-129)

**Verdict: FORWARD to Engineering Director**

### Checklist
- [x] Clear entry/exit logic — Yes. EQH/EQL zone identification, entry on recovery bar, ATR-scaled exits.
- [x] Market regime context identified — Yes. Regime gate: disable long entries when BTC 20-day ROC < -15%.
- [x] Economic rationale — Plausible. Stop-clustering mechanics and institutional absorption at liquidity pools (SMC/ICT framework, Williams 2001). Less rigorous academic grounding than H09/H11 — primarily practitioner methodology.
- [x] Alpha decay analysis — Complete. Half-life ~4–6 days; cost survival confirmed (BTC/ETH round-trip ~0.10–0.15%; structural trade targets exceed this).
- [x] Signal combination policy — N/A (single signal).
- [x] ML anti-snooping — N/A (rule-based).

### Conditions for Engineering Director

1. **Sub-period testing required** — must test 2022–2023 bear market sub-period separately from 2024–2025 bull. SMC-based strategies are known to be regime-dependent.
2. **IC validation** — confirm EQL/EQH signal has IC > 0.02 in IS data before declaring the hypothesis viable.
3. **Crowding caveat** — SMC/ICT is one of the most widely followed frameworks on TradingView (2020–2026). If the signal is widely followed, EQL/EQH levels may be self-defeating (too many participants front-running the setup). Flag if win-rate is below 40% in recent data.
4. **Asset scope** — start with BTC/ETH daily bars only. Do not expand to altcoins until BTC/ETH shows IC > 0.02.

### Key Risks
- IR estimate (0.25–0.35) is below Gate 1 target of IS Sharpe > 1.0; will likely require strong regime filtering to qualify
- SMC crowding risk is the highest of the three hypotheses — this edge may have been arbitraged away by 2024–2026
- TV source (TedDibiase21) is a community script, not professional publisher — moderate confidence

---

## H11 — CVD-Confirmed Breakout (QUA-130)

**Verdict: FORWARD to Engineering Director**

### Checklist
- [x] Clear entry/exit logic — Yes. Dual AND condition: price close > N-bar high AND CVD proxy > threshold × 20-day average CVD.
- [x] Market regime context identified — Yes. Works in trending/high-volume regimes; fails in range-bound/low-volume.
- [x] Economic rationale — Strong. Kyle (1985), Glosten-Milgrom (1985), Lo et al. (2000) — solid microstructure foundation for order flow predictiveness of breakout continuation.
- [x] Alpha decay analysis — Complete. Half-life 5–10 days; cost survival confirmed (SPY/QQQ spread < 0.05%; 2×ATR target survives).
- [x] Signal combination policy:
  - 2 signals ≤ 3 max ✓
  - Price breakout IC > 0.03 (confirmed by H05/H07 backtests) ✓
  - CVD proxy IC estimated 0.03–0.05 but **not empirically confirmed at this firm** — see Required Gate below
  - Equal-weight blending (default) ✓
- [x] ML anti-snooping — N/A (rule-based).

### Signal Combination Required Gate (HIGH PRIORITY)

**Per Signal Combination Policy: CVD IC must be validated > 0.02 individually before combining with price breakout.**

The hypothesis explicitly acknowledges that CVD IC is an informed estimate from literature, not empirically confirmed at this firm. Engineering Director must:

1. **First backtest price breakout signal alone** (single-signal baseline) — confirm IC in IS data.
2. **Then backtest CVD proxy signal alone** — confirm IC > 0.02 individually.
3. **Only proceed with combined signal if both clear IC floors** — if CVD proxy IC < 0.02, reject the CVD component and consider H11 as a single-signal breakout (which is effectively H05 variant).

### Data Feasibility Flag

- **yfinance limitation:** yfinance provides end-of-day OHLCV only — no intrabar volume. CVD proxy must use `(Close - Open) / (High - Low) × Volume` approximation.
- Engineering Director should document whether Polygon.io (tick/1-min data) is available. If so, prefer actual intraday CVD over daily proxy.
- If daily proxy proves too noisy (IC near zero), consider downgrading to single-signal breakout strategy.

### Conditions for Engineering Director

1. **Sequential validation** — test price breakout IC alone first, then CVD proxy IC alone, before combining.
2. **CVD threshold sensitivity** — `cvd_threshold_mult` is flagged as high-sensitivity parameter; sweep broadly (0.5–2.0) and confirm edge is not localised.
3. **Universe scope** — limit to SPY/QQQ/IWM + top-50 S&P500 by ADV; do not expand until IC confirmed.
4. **Data source documentation** — Engineering Director must document whether actual CVD (intraday) or daily proxy was used in backtest spec.

### Key Risks
- CVD proxy may be too crude to add predictive value over price alone
- High parameter sensitivity on `cvd_threshold_mult` — risk of overfitting to threshold
- If CVD IC < 0.02, the combined strategy collapses to a standard breakout (H05 analogue already tested and failed Gate 1)

---

## Research Director Sign-Off

All three hypotheses meet the minimum forward criteria:
- Economic rationale documented
- Entry/exit logic is codifiable
- Alpha decay analysis complete
- No ML anti-snooping concerns

H09 and H11 have the strongest economic rationale. H10 has the highest crowding risk. All three are conditional passes — failure to meet the stated conditions should result in escalation back to Research Director before further backtest investment.

**Forwarded to Engineering Director:** 2026-03-16
**Next review trigger:** Gate 1 results for each hypothesis
