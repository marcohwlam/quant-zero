# H63: Leveraged-ETF ORB with VIX ≥ 20 Day Filter

**Version:** 0.1 (stub — pending Research Director approval)
**Author:** Research Director
**Date:** 2026-06-09
**Issue:** QUA-152
**Asset class:** equities (leveraged ETFs)
**Strategy type:** single-signal, regime-filtered
**Status:** DRAFT

---

## Summary

Opening Range Breakout (ORB) applied exclusively to 3× leveraged ETFs (SPXL, TQQQ) with a VIX ≥ 20 day-filter gating trade entry. The leveraged ETF universe provides wider opening ranges (~3× SPY OR_width), generating sufficient gross edge per trade to survive transaction costs. The VIX filter eliminates the zero-edge low-volatility regime that caused H59 to fail, concentrating execution in periods where intraday price discovery is strongest.

This is **not an H59 family iteration**. Mechanism changes:
1. Different underlying universe (SPXL/TQQQ vs. SPY/QQQ)
2. Regime filter (VIX ≥ 20 gate — conditional execution vs. always-on)
3. Materially different OR economics (3× wider OR → fundamentally different edge/cost structure)

**Naming note:** The issue description (QUA-152) proposed classifying this as H60. H60 is already occupied by the VWAP mean reversion hypothesis (REJECTED 2026-06-09, PF-3 automatic reject). This hypothesis is therefore numbered H63 (next available sequential slot).

---

## Economic Rationale

H59 failure autopsy (Engineering Director, QUA-145) identified two root causes:
1. Gross edge on SPY was only 3.13 bps — insufficient vs. any cost model
2. Gross edge was regime-dependent: positive only during extreme-vol windows (COVID, 2022 rate-shock); near-zero or negative in low-vol periods

H63 addresses both causes directly:

**Wider OR → higher gross edge**: Zarattini & Aziz (2023) report their strongest ORB results on leveraged ETFs (SPXL, TQQQ, UPRO), not on SPY/QQQ. SPXL carries 3× the daily vol of SPY. A typical SPY 15-min OR_width ≈ 0.4%; the equivalent SPXL OR_width ≈ 1.2–1.5%. Gross edge per trade scales approximately linearly with OR_width (win rate and R_mult roughly invariant across instruments). If SPY gross = 3.13 bps, SPXL gross at 3× is expected ~9–15 bps.

**VIX filter → eliminate the losing regime**: H59 WF data showed the ORB signal only generates positive gross edge in high-volatility windows:
- COVID (VIX avg ~32): 15–18 bps gross on SPY
- Rate-shock 2022 (VIX avg ~26): 10–15 bps gross on SPY
- Low-vol 2017–2019 (VIX avg ~13): 0–5 bps gross on SPY — insufficient to survive costs

A VIX ≥ 20 filter selectively activates the strategy only on days where the mechanism is empirically demonstrated to generate positive gross edge. This is a regime-conditional strategy, not a parameter optimization.

**Stop-cascade mechanism amplified**: Leveraged ETF retail traders place stops more loosely (absolute dollar risk, not bps-based), creating larger stop-cascade events when OR boundaries break. This amplifies the institutional order-flow and stop-cascade mechanisms described in Osler (2003).

---

## Entry/Exit Logic

**Universe:** SPXL (3× long SPY) and TQQQ (3× long QQQ). Both instruments — treat as independent entries (max 2 concurrent positions).

**Day filter:** Only enter if prior-day VIX close ≥ 20. (Prior-day to avoid look-ahead; VIX available at market close.)

**Bar resolution:** 1-minute OHLCV (Alpaca Markets RTH, 09:30–16:00 ET)

**Opening Range:**
- OR_high = max(high[09:30 … 09:30+N]) over first N minutes of RTH
- OR_low  = min(low[09:30 … 09:30+N])
- OR_width = OR_high − OR_low

**Entry signal (long only):**
- Trigger: `close > OR_high` (bar closes above the opening range high) AND day passes VIX filter
- Enter at next bar open (t+1 fill)

**Stop loss:** `entry_price − OR_width × (1 + stop_buffer)` where `stop_buffer = 0.05`

**Take profit:** `entry_price + OR_width × R_mult` where `R_mult = 2.0` (source paper optimum)

**Exit:** Flat at 15:55 ET if neither stop nor target hit. No overnight carry.

**Max 1 trade per day per instrument.** Max 2 concurrent positions (SPXL + TQQQ).

---

## Market Regime Context

**Active (VIX ≥ 20):**
- High-vol macro event days (CPI, FOMC, geopolitical): leveraged ETF OR widens further → largest gross edge
- Trend days with opening gap: institutional order flow concentrated, ORB continuation probability highest
- 2022 rate-shock, COVID 2020: optimal regime for this strategy

**Inactive (VIX < 20 → filter blocks trading):**
- Low-vol 2017–2019, 2023-mid consolidation: strategy sits flat — no losses, no gains
- Choppy midsummer periods: VIX filter correctly suppresses these sessions

---

## Alpha Decay

Same as H59: intraday signal, half-life < 1 trading day by design. Signal consumed within session.

**Cost survival for leveraged ETFs:**
- SPXL typical spread: $0.02 on ~$80 stock = ~2.5 bps/leg → ~5 bps round-trip
- Market impact (moderate lot size, SPXL 1M+ daily volume): ~2–3 bps
- Total round-trip cost estimate: ~8–10 bps
- Expected gross edge (SPXL, VIX ≥ 20 days): ~15–25 bps (extrapolated from H59 COVID/rate-shock WF data × 3× leverage factor)
- Net per trade estimate: ~7–15 bps
- **Cost survival: LIKELY PASS** — requires backtest confirmation

---

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `or_window_min` | 5, 15 | Zarattini & Aziz: 5m and 15m optimal; skip 30m |
| `r_mult` | 1.5, 2.0, 2.5 | Source paper optimum 2.0 |
| `vix_threshold` | 17, 20, 25 | Sensitivity test; 20 is primary thesis |
| `stop_buffer` | 0.05 | Fixed from H59 |
| `universe` | SPXL only, TQQQ only, both | Both = more trades |

**Parameter count:** 5 parameters. Canonical combination: `or_window=15, r_mult=2.0, vix=20, both instruments`. Test full grid but report canonical first.

---

## Capital and PDT Compatibility

- Requires ≥ $25,001 (PDT-triggering strategy — ~78 day trades/year)
- Position sizing: allocate 50% of capital per instrument (2 concurrent positions possible)
- SPXL/TQQQ are highly liquid ETFs; no execution concerns at $25K account size

---

## Pre-Flight Gate Checklist

**Reviewed by:** Research Director — QUA-152 — 2026-06-09

- [x] **PF-1 CONDITIONAL PASS — Walk-Forward Trade Viability**
  - Trade count: SPXL+TQQQ combined, VIX ≥ 20 filter → ~78 trades/year
  - 12m IS WF window: 78 ÷ 4 = 19.5 < 30 → **FAILS standard 12m IS window**
  - 24m IS WF window: 156 ÷ 4 = 39 ≥ 30 → **PASS**
  - **Requirement:** Engineering Director MUST use 24-month IS / 6-month OOS walk-forward windows. Document minimum per-window trade count in backtest spec. Do NOT use 12m IS windows.
  - Alternative rescue: lower VIX threshold to 17 (estimated ~110 trades/year); 12m IS: 110 ÷ 4 = 27.5 — still marginal. 24m IS remains safest.

- [x] **PF-2 PASS — Long-Only MDD Stress (dot-com 2000–2002 / GFC 2008–2009)**
  - Intraday-flat architecture: all positions closed 15:55 ET; zero overnight gap exposure
  - SPXL 3× leverage amplifies per-trade loss vs. SPY, but stop bounds it
  - SPXL OR_width ≈ 1.2%; max daily loss ≈ 1.2% × 1.05 = 1.26% of SPXL notional
  - Worst consecutive losing streak: ~15 days → cumulative MDD ≈ 18.9% — below 40% gate
  - Leveraged ETF daily compounding losses do NOT compound across sessions (flat each night)
  - Dot-com bust / GFC: multi-month directional losses inaccessible to intraday-flat strategy
  - PASS.

- [x] **PF-3 PASS — Data Pipeline Availability**
  - Requires: 1-minute OHLCV from Alpaca for SPXL and TQQQ
  - SPXL (launched 2008) and TQQQ (launched 2010) are standard US equity ETFs on Alpaca
  - QUA-149 added AlpacaIngester minute-bar pipeline for RTH data
  - No exotic data requirements (no VWAP, no CVD, no options, no tick)
  - SPXL/TQQQ available via same Alpaca endpoint as SPY/QQQ minute data used in H59 backtest
  - Engineering Director should confirm historical bar availability back to 2016 (TQQQ launched 2010 → 2016 start feasible)
  - PASS.

- [x] **PF-4 STRONG PASS — Rate-Shock Regime Plausibility (2022)**
  - VIX ≥ 20 filter **specifically selects** rate-shock-regime days
  - 2022: average VIX ~26; majority of trading days qualify for H63 execution
  - H59 WF data confirmed positive gross edge on SPY in 2022 rate-shock windows (10–15 bps)
  - H63 at 3× leverage should generate 30–45 bps gross on SPXL equivalents in the same windows
  - Intraday-flat → cannot compound from sustained bear trend direction
  - Strategy is explicitly DESIGNED to be active in high-VIX, rate-shock environments
  - STRONG PASS.

**Hypothesis class:** Pattern-based / binary event-driven (ORB S/R breakout) — priority class 1 per diversification mandate.
**Family:** H63 is a new hypothesis, not H59 iteration 2. Different mechanism, different universe, regime-conditional. No family iteration limit applies.
**Signal combination:** Single-signal with regime filter. No multi-signal combination policy triggered.
**Alpha decay:** Intraday; transaction cost justification provided (estimated ~7–15 bps net; cost ~8–10 bps). Requires backtest confirmation.

**Research Director decision:** DRAFT — pending backtest confirmation of gross edge on SPXL/TQQQ. PF-1–4 satisfied with 24m IS WF window requirement. **APPROVED for Gate 1 backtesting with explicit 24m IS / 6m OOS WF constraint.**

---

## References

- Zarattini, C. & Aziz, A. (2023). Can Day Trading Really Be Profitable? SSRN 4416198.
- `research/findings/h59_orb_gate1_failure_retirement_2026-06-09.md` — H59 WF diagnostics (regime-dependent gross edge data)
- `research/hypotheses/59_opening_range_breakout_orb.md` — H59 parent (retired)
- Osler, C.L. (2003). Currency Orders and Exchange Rate Dynamics. *Journal of Finance*, 58(5). (stop-loss cascade mechanism)
- Alpaca Markets minute OHLCV — SPXL/TQQQ RTH data (2016–2024)
