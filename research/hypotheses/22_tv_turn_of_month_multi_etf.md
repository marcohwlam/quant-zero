# Turn-of-Month Calendar Effect — SPY/QQQ/IWM with VIX Filter

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

The turn-of-month (TOM) effect is one of the most replicated calendar anomalies in equity markets: stocks exhibit systematically higher returns during the last 1–3 trading days of a month and the first 1–3 trading days of the subsequent month, compared to mid-month periods.

**Why the edge exists:**

1. **Payroll-cycle demand:** Monthly employee payroll cycles (401k contributions, pension inflows) concentrate institutional equity purchases at month-end and month-start. Lakonishok & Smidt (1988) identified this as the primary mechanism, observing that Dow Jones Industrial Average returns were significantly concentrated in the TOM window (days −1 through +4).

2. **Institutional window-dressing:** Fund managers rebalance and "window-dress" portfolios at month-end for reporting purposes, generating systematic buying pressure near the last trading day of each month.

3. **Futures/options rollover:** Index futures rolls at month-end create mechanical buying in the underlying index ETFs (SPY, QQQ) as arbitrageurs work the convergence.

4. **Robust international replication:** McConnell & Xu (2008) extended the Ariel (1987) and Lakonishok & Smidt (1988) studies using 81 years of CRSP data (1926–2006) and found the TOM effect accounts for the entirety of the US equity market's average monthly excess return. The effect also holds across 35 international markets.

5. **Persistence in ETF era:** FPA Journal (2011) reexamination confirmed the TOM anomaly persists in the ETF era for SPY, QQQ, and IWM specifically.

**Why arbitrage is limited:**
- Monthly payroll and institutional calendar effects are structural, not price-based — cannot be front-run with momentum signals without changing the mechanism
- The window is short (5–6 trading days) but widely known; partial crowding has occurred without eliminating the premium
- Institutional constraints (end-of-month risk limits, reporting cycles) perpetuate the supply/demand imbalance

**Distinction from existing strategies:**
- H07 (Multi-Asset TSMOM), H08 (Crypto Momentum), H17 (GEM ETF Rotation): All momentum strategies with multi-week to multi-month lookbacks — mechanistically and temporally distinct
- H18 (SPY/TLT Rotation): Cross-asset relative value, not calendar-driven
- This is the **first calendar/seasonal strategy** in the hypothesis pipeline

## Entry/Exit Logic

**Entry signal:**
- **Long entry:** At close on trading day `entry_day` before month-end (default: Day −2, i.e., 2nd-to-last trading day)
  - VIX filter (required): Do NOT enter if VIX closes > `vix_threshold` (default: 30) on the entry day
  - Assets: SPY, QQQ, IWM — enter all three simultaneously
- Equal weight across the three ETFs (1/3 portfolio weight each)

**Exit signal:**
- **Close position:** At close on trading day `exit_day` of the next month (default: Day +3, i.e., 3rd trading day of new month)
- No stop loss (short hold period; stop adds noise more than protection given < 6 day hold)
- Force exit at Day +3 regardless of profit/loss

**Holding period:** Calendar — typically 5–6 trading days spanning the month turn

**Entry/Exit schedule:**
- Monthly cycle: Enter T-2, exit T+3 of next month = 12 entry-exit cycles per year
- With 3 ETFs (SPY, QQQ, IWM), this generates **36 round-trip trades per year**

## Market Regime Context

**Works best:**
- Low-to-moderate volatility environments (VIX < 25)
- Bull markets or range-bound markets with upward drift
- Periods when 401k and pension inflows are strong (low unemployment, wage growth)

**Tends to fail:**
- High-stress market environments (VIX > 30): Institutional selling overrides payroll demand; TOM premium reverses or disappears
- Sustained bear markets: Payroll inflows are overwhelmed by risk-off institutional selling; window-dressing effect becomes window-selling
- Deflationary shock periods: If equity inflows dry up (2020 initial Covid shock, 2008 Oct-Nov), TOM effect temporarily breaks down

**Regime gate:**
- **VIX > 30 filter:** Do not enter at any month-turn when VIX closes above 30 on the entry day. This single rule captures most of the high-stress periods where TOM anomaly breaks down and replaces the edge with losses.

## Alpha Decay

- **Signal half-life (days):** 3–4 days (TOM edge is concentrated in the 5–6 day window; decays sharply beyond Day +3)
- **Edge erosion rate:** Fast (< 5 days)
- **Recommended max holding period:** 6 trading days (2× half-life; matches exit on Day +3)
- **Cost survival:** Yes — SPY/QQQ/IWM are the most liquid US equity ETFs. Round-trip cost < 0.005% (bid-ask + commission). The TOM premium is historically ~0.2–0.5% per month-turn on SPY. Edge survives costs by a wide margin.
- **IC decay curve estimate:**
  - T+1 (Day −1 through +0): IC ≈ 0.08–0.12 (primary TOM window)
  - T+5 (Day +3): IC ≈ 0.02–0.04 (tail; exit here)
  - T+20 (mid-month): IC ≈ 0.00 (outside TOM window; no signal)
- **Annualised IR estimate:**
  - TOM premium historically ~3–4% annualised excess return over buy-and-hold for the window equivalent
  - SPY annualised vol ≈ 15–18%. For the ~25% time in-market, blended vol ≈ 7–9% annualised.
  - Pre-cost annualised IR estimate: ~3.5% / 8% ≈ 0.44 (marginal but above the 0.3 warning threshold)
  - With VIX filter, reduced in-market time but higher win-rate → IR may improve toward 0.5–0.7
- **Notes:** TOM effect is widely documented and crowded. IR in recent periods (2018–2026) likely lower than historical estimate. Critical to test walk-forward out-of-sample.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `entry_day` | −3 to −1 (trading days from month-end) | Earlier entry captures more of the effect; later entry reduces holding cost |
| `exit_day` | +2 to +5 (trading days into next month) | Academic consensus suggests +3 to +4 as optimal exit |
| `vix_threshold` | 20 – 35 | VIX filter sensitivity. 25 is conservative; 35 is permissive |
| `assets` | SPY only vs SPY+QQQ+IWM | Single vs multi-asset: multi-asset increases trade count, diversifies concentration |
| `position_size` | 100% of portfolio (single asset) or 33% each (3-asset) | Equal weight is baseline |

## Capital and PDT Compatibility

- **Minimum capital required:** $3,000 (3 ETF positions at 33% each)
- **PDT impact:** None — all positions are held overnight for 5–6 calendar days. Entries and exits are at the close. No day trades consumed. PDT-safe. ✓
- **Position sizing:** Equal weight across 3 ETFs: 33% each (SPY, QQQ, IWM). Or 100% in SPY alone (simpler, lower trade count).
- **Max concurrent positions:** 3 ETFs held simultaneously during the TOM window; no other positions during this window.

## Pre-Flight Gate Assessment

| Gate | Assessment | Notes |
|---|---|---|
| **PF-1: Trade count ÷ 4 ≥ 30/yr** | **PASS** | 3 ETFs × 12 month-turns = 36 trades/yr. Over 5-yr IS: 36 × 5 = 180 trades. 180 ÷ 4 = 45/yr ≥ 30. ✓ With VIX > 30 filter: some months skipped (est. 3–4/yr in normal regimes); min trades ~30–32/yr → borderline PASS even with filter. |
| **PF-2: Long-only equity MDD < 40% (dot-com + GFC)** | **PASS** | VIX filter (VIX > 30) eliminates most high-stress TOM windows. During dot-com bust (2000–2002), VIX repeatedly exceeded 30 → most TOM entries skipped. During GFC (Sept–Dec 2008), VIX exceeded 30 for extended period → most TOM entries skipped. Estimated TOM drawdown without VIX filter: dot-com ~-18%, GFC ~-22%. With VIX filter: both estimated < 10%. Both < 40%. ✓ |
| **PF-3: All data in daily OHLCV pipeline** | **PASS** | SPY (1993), QQQ (1999), IWM (2000) — all yfinance daily. VIX (^VIX from 1990) — yfinance daily. Calendar-based entry days computable from pandas DateOffset. ✓ |
| **PF-4: 2022 Rate-Shock rationale** | **PASS** | VIX filter provides primary defense. In 2022: VIX exceeded 30 in January, March–May, June–July, September–October. Most high-volatility TOM windows were filtered. In low-VIX months (February, August), TOM trades occurred but SPY/QQQ/IWM were in downtrend — these are the residual loss months. Estimated 2022 net loss without filter: ~-12%. With VIX > 30 filter: ~-4 to -6% (losses on unfiltered months only). Not a strong year but survivable with filter. Defense a priori plausible — requires confirmation in backtest. |

**All 4 PF gates: PASS (PF-1 borderline with VIX filter; PF-4 conditional on VIX filter effectiveness in 2022)**

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Uncertain. TOM premium is real but the raw annualised excess return (~3–4%) relative to SPY volatility gives IS Sharpe ~0.4–0.7. Gate 1 IS Sharpe > 1.0 is a stretch — depends heavily on whether VIX filter significantly reduces drawdown periods (which would boost risk-adjusted return). IS Sharpe likely 0.5–0.9.
- **OOS persistence:** Medium-high confidence. TOM anomaly has been documented since 1926 in US data and internationally — one of the most robust calendar anomalies. Effect has weakened in post-2010 era but not eliminated. OOS Sharpe likely 0.3–0.7.
- **Walk-forward stability:** Likely stable. Only 2 key parameters (`entry_day`, `exit_day`); both motivated by academic consensus.
- **Sensitivity risk:** Low. The calendar timing is structural; small shifts in entry/exit window (±1 day) don't dramatically change the signal.
- **Known overfitting risks:**
  - VIX threshold (30) is round number — slight optimization bias possible. Test at 25 and 35 to check robustness.
  - 3-ETF selection (SPY/QQQ/IWM) is standard but not formally optimized.
  - IS Sharpe may not reach 1.0 — this strategy may only qualify as a component signal within a multi-signal framework rather than a standalone strategy.

## TV Source Caveat

- **Original TV strategy name:** "Turn of the Month Strategy [Honestcowboy]" by Honestcowboy
- **TV URL:** https://www.tradingview.com/script/NXejRbFv-Turn-of-the-Month-Strategy-Honestcowboy/
- **Apparent backtest window:** Strategy description cites "S&P 500 9.8% annualised return" — implies a multi-year backtest. Exact date range not disclosed. TV Strategy Tester default is typically 2 years, which would miss stress-test periods. **Caution:** TV backtest window likely excludes the 2008 and 2022 drawdown periods. Use independent 1999–2023 backtest on yfinance.
- **Crowding risk:** Low-Medium. Turn-of-month is academically published and well-known. However, it requires holding for 5–6 days (unlike intraday strategies), which limits capacity for intraday arbitrageurs to eliminate the premium. ETF-based implementation is accessible to retail, but the structural demand drivers (payroll, pension) are not arbitrageable.
- **Novel insight vs H01–H20:** Zero overlap with any existing hypothesis. No calendar/seasonal strategy exists in the pipeline. This is the first time-series calendar strategy; all prior hypotheses are technical-signal or factor-based.

## References

- Ariel, R.A. (1987). "A Monthly Effect in Stock Returns." *Journal of Financial Economics*, 18(1), 161–174.
- Lakonishok, J. & Smidt, S. (1988). "Are Seasonal Anomalies Real? A Ninety-Year Perspective." *Review of Financial Studies*, 1(4), 403–425.
- McConnell, J.J. & Xu, W. (2008). "Equity Returns at the Turn of the Month." *Financial Analysts Journal*, 64(2), 49–64. (SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=917884)
- Quantpedia (2024). "Turn of the Month in Equity Indexes." https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes
- FPA Journal (2011). "The Turn-of-the-Month Anomaly in the Age of ETFs." Financial Planning Association.
- TV source: https://www.tradingview.com/script/NXejRbFv-Turn-of-the-Month-Strategy-Honestcowboy/
- Related in knowledge base: `research/hypotheses/07_multi_asset_tsmom.md` (different mechanism — multi-month momentum), `research/hypotheses/17_qc_dual_momentum_etf_rotation.md` (different mechanism — relative momentum)
