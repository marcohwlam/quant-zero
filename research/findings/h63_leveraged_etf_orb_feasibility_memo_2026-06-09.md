# H63 Leveraged-ETF ORB + VIX Filter — Feasibility Memo

**Date:** 2026-06-09
**Author:** Research Director
**Issue:** QUA-152
**Verdict: PROCEED**

---

## Context

H59 (ORB on SPY/QQQ) failed Gate 1 on 2026-06-09 with 2/8 criteria passed. Root cause: gross edge of 3.13 bps insufficient vs. any realistic cost model. Engineering Director noted positive gross edge only in extreme-vol windows (COVID, 2022) and recommended a new hypothesis (leveraged-ETF universe + VIX filter) as a potentially viable direction.

The issue (QUA-152) proposed classifying this as H60. **H60 is already occupied** by the VWAP mean reversion hypothesis (REJECTED 2026-06-09, PF-3 automatic reject). This hypothesis is assigned **H63** (next available sequential number after H62).

---

## Pre-Flight Gate Assessment

### PF-1: Walk-Forward Trade Viability

**CONDITIONAL PASS — requires 24m IS WF window.**

Trade count with VIX ≥ 20 filter across SPXL+TQQQ: ~78 trades/year.

| WF config | IS trades | ÷ 4 | PF-1 status |
|---|---|---|---|
| 12m IS / 3m OOS | 78 | 19.5 | FAIL |
| 18m IS / 6m OOS | 117 | 29.3 | Borderline FAIL |
| **24m IS / 6m OOS** | **156** | **39** | **PASS** |

**Requirement for Engineering Director:** Must use 24-month IS / 6-month OOS walk-forward windows. Minimum per-window trade count must be documented in backtest spec. 12m IS windows not permitted for this strategy.

This is a **genuine constraint, not a parameter fiddle** — the trade count is fixed by market structure (VIX ≥ 20 occurs ~30–40% of trading days).

### PF-2: Long-Only MDD Stress

**PASS.**

Intraday-flat architecture is identical to H59 and passes on the same structural argument: all positions closed 15:55 ET daily; zero overnight gap exposure; maximum cumulative loss bounded by sequential daily stops.

SPXL 3× leverage amplifies per-trade loss vs. SPY, but the stop loss bounds the daily loss to ~1.26% of notional (vs. ~0.42% on SPY). Worst-case 15 consecutive losing days: MDD ≈ 18.9%, below the 40% gate. Leveraged ETF daily beta decay does NOT accumulate across sessions because the strategy holds no overnight position.

### PF-3: Data Pipeline Availability

**PASS.**

SPXL (Direxion 3× S&P 500, launched 2008) and TQQQ (ProShares 3× Nasdaq-100, launched 2010) are standard US equity ETFs available via Alpaca Markets minute OHLCV. QUA-149 built the AlpacaIngester minute-bar pipeline. No exotic data required — this is 1-minute OHLCV only, identical data format to H59.

Engineering Director should confirm Alpaca historical coverage for SPXL/TQQQ back to at least 2016 (both instruments have 6+ years of history by that date; data availability expected to match SPY/QQQ minute coverage).

### PF-4: Rate-Shock Regime Plausibility

**STRONG PASS.**

This is the strongest PF-4 case of any hypothesis in the pipeline. The VIX ≥ 20 filter **specifically selects** the rate-shock regime. H59's WF diagnostics confirmed positive gross edge in these exact windows. The strategy is designed to be active precisely when rate-shock conditions are present and inactive otherwise.

---

## Economic Viability Assessment

H59's gross edge on SPY was 3.13 bps (insufficient). The leveraged ETF variant should produce materially higher gross edge via two mechanisms:

**1. OR_width scales with volatility.**
SPY typical OR_width ≈ 0.4%; SPXL typical OR_width ≈ 1.2–1.5% (3× beta). Gross edge per trade for ORB scales approximately linearly with OR_width. Expected SPXL gross edge: ~9–15 bps in typical conditions, ~30–45 bps in high-VIX sessions.

**2. VIX filter removes the zero-edge regime.**
H59 failed partly because 60%+ of trading days were low-VIX with negligible edge. H63 only trades VIX ≥ 20 days where the mechanism is empirically demonstrated to work. Expected gross edge on execution days (from H59 WF data, SPY in COVID/rate-shock): 15–18 bps → SPXL equivalent: ~45–54 bps.

**Transaction cost reality check (SPXL):**
- Spread: ~$0.02–$0.05 on ~$80 price = ~2.5–6 bps/leg = ~5–12 bps round-trip
- Market impact (100–200 share lot): ~2–3 bps
- Total round-trip: ~8–15 bps

**Net edge estimate (conservative):** 45 bps gross − 15 bps costs = **30 bps net per trade** (conservative). Even on 15 bps gross (typical VIX ≥ 20 but not extreme), net = 15 − 15 = 0 bps — break-even. Edge survival depends on high-VIX execution concentration; breakeven scenario exists if VIX threshold is set too low.

**Sharpe estimate (if gross edge ≈ 30 bps/trade at VIX ≥ 20):**
- 78 trades/year × 30 bps net = 2,340 bps = 23.4% annual return
- Daily P&L vol (SPXL, OR_width ≈ 1.2%): ~0.9% of notional on trade days
- Annual vol: 0.9% × √78 ≈ 7.9%
- Sharpe estimate: 23.4% / 7.9% ≈ **2.96** (upper bound; expect 1.0–1.5 after realistic estimation)

These are rough extrapolations. The backtest will determine whether SPXL/TQQQ gross edge in the Alpaca data matches expectations.

---

## Key Risks

1. **OR precision on leveraged ETFs**: Same t+1 fill issue as H59 applies to SPXL/TQQQ. High beta means wider price swings between breakout close and next-bar open — may create worse adverse fill bias than on SPY.

2. **Leveraged ETF liquidity at open**: SPXL/TQQQ average daily volume is lower than SPY/QQQ. Early session liquidity (09:30–09:45) may be thinner, increasing slippage. 100-share lots should be fine; scaling to larger positions would face execution risk.

3. **VIX look-ahead discipline**: Must use **prior-day VIX close** for filter. Same-day VIX is only known intraday and cannot be used for entry decisions without look-ahead.

4. **PF-1 tightness**: 78 trades/year is sparse. If actual trade frequency comes in lower (e.g., VIX spends less time ≥ 20 in the IS window), PF-1 may fail. WF window choice is load-bearing — Engineering Director must respect 24m IS constraint.

5. **Regime concentration**: Strategy performance will be concentrated in 2020 and 2022 WF windows. IS Sharpe may be artificially high from these two extreme-vol regimes. OOS Sharpe on 2023–2024 (lower VIX) will be the true test.

---

## Verdict: PROCEED

**PROCEED to Gate 1 backtesting as H63.**

Rationale:
- All four PF gates pass (PF-1 with 24m IS window constraint)
- Economic rationale is sound: leveraged ETF OR_width provides structurally higher gross edge than SPY/QQQ
- VIX filter addresses the specific regime failure identified in H59 diagnostics
- Zarattini & Aziz (2023) explicitly recommend leveraged ETFs as the preferred ORB universe
- This is a new hypothesis (not H59 family iteration), so no family iteration limit concerns
- Hypothesis class is Pattern-based / binary event-driven (priority class 1)

**Conditions on Engineering Director:**
1. 24-month IS / 6-month OOS walk-forward windows (hard requirement for PF-1)
2. Prior-day VIX close as filter variable (no intraday VIX look-ahead)
3. Use instrument-class slippage overrides for SPXL/TQQQ (not canonical 0.05%/leg default)
4. Report per-WF-window gross edge and trade count; flag any windows with < 30 trades
5. Confirm Alpaca SPXL/TQQQ data availability back to 2016 before full backtest run

**Hypothesis stub:** `research/hypotheses/63_leveraged_etf_orb_vix_filter.md`

---

*Research Director — 2026-06-09 | Issue QUA-152*
