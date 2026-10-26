# Corporate Buyback Blackout Window Seasonality (SPY)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-10-26
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

US corporations are the largest net buyers of US equities. Most issuers observe a self-imposed blackout on repurchases from roughly two weeks before quarter end until two days after earnings release (Rule 10b5-1 and insider-trading policy practice). When the blackout is dense (late March/June/September/December through mid-to-late earnings season), the largest marginal buyer is absent; when it lifts (after earnings, typically weeks 4-9 of each quarter), buyback demand returns. This is an event-driven flow effect with a clear mechanism, not a pricing anomaly that arbitrageurs can trivially remove because the buyer's constraint is legal. Evidence: Ikenberry, Lakonishok, Vermaelen (1995) on repurchase announcements; Bonaime, Hankins, Harford (2014) on repurchase timing and flexibility; practitioner desk notes (bank equity-derivatives desks publish "buyback window" calendars). Evidence on index-level seasonality is practitioner-grade and has not been confirmed in peer-reviewed work for the index return pattern, so the economic rationale is plausible but the empirical edge is unproven.

## Entry/Exit Logic

**Entry signal:**
- Buy SPY at the Close of the 3rd trading day after the start of the post-earnings open window (approximately trading day 22 after quarter end, equivalent to the Close on or after Feb 5, May 5, Aug 5, Nov 5)
- Prior Close > SMA(200)

**Exit signal:**
- Exit at the Close ~13 trading days before the next quarter end (approximately Mar 15, Jun 15, Sep 15, Dec 15), when the blackout starts
- Stop: Close < SMA(200) by more than 3%

**Holding period:** Position (about 6 weeks per window, 4 windows per year)

## Market Regime Context

Works when buybacks are large and corporate balance sheets are healthy (2012-2021, 2023-2025). Fails when issuers suspend buybacks (2008-2009, 2020 Q2) because the window effect disappears with the flow. Pause when S&P 500 aggregate buyback authorizations fall by more than 30% year-over-year.

## Alpha Decay

- **Signal half-life (days):** ~20 (estimate from calendar structure; no decay fit)
- **Edge erosion rate:** slow (>20 days)
- **Recommended max holding period:** 40 trading days (hold span is ~30)
- **Cost survival:** yes; 8 round trips per year on SPY
- **Notes:** Annualized IR estimate: if the window return exceeds the blackout return by 2% per quarter with 15% annualized vol and 50% invested, IR is ~0.3-0.5 pre-cost. Close to the 0.3 warning line. Crowding is possible because desk calendars are public.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| entry_offset_days | 18 - 28 (after quarter end) | Earnings release timing |
| exit_offset_days | 8 - 18 (before quarter end) | Blackout start |
| trend_filter_sma | 100 - 200 | Regime filter |
| instrument | SPY, RSP, IWM | Test breadth of effect |

## Capital and PDT Compatibility

- **Minimum capital required:** $5,000
- **PDT impact:** None (multi-week holds)
- **Position sizing:** 100% in SPY during window, 0% otherwise

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** No known single QC algorithm. QC community has "Earnings Season" and "Seasonal Quarter Rotation" examples; none verified to encode buyback windows. Engineering must confirm before citing a URL.
- **QC backtest window and IS cherry-pick risk:** Calendar-window strategies on QC are usually tested 2010-2024, a period that coincides with record buybacks (2018 and 2022 were peak years). The effect is likely strongest in that sample.
- **Adaptation to framework and data source:** Uses only daily SPY OHLCV and a fixed calendar. No QC dependency.
- **Top-10 clone / crowding confirmation:** Not in the top-10 most cloned QC algorithms (to my knowledge, unverified). Crowding via public desk calendars is possible.

## Pre-Flight Checklist

### PF-1: Walk-Forward Trade Viability
- Single instrument, 4 windows per year = 4 trades/year, ~80 over 2000-2019 IS; ÷4 = ~20 per fold.
- **[ ] PF-1 FAIL as specified (< 30).** Conditional remedy: expand to 6 instruments (SPY, QQQ, IWM, DIA, RSP, MDY) = 24 trades/year, ~480 IS, ÷4 = 120; instruments are highly correlated, so the effective sample is still small. Flagged to Research Director as a conditional pass with low statistical power.

### PF-2: Long-Only MDD Stress Test
- Exposure is ~50% of days. 2000-2002: SMA(200) filter would have exited most of the decline; estimated MDD 20-25%. 2008-2009: estimated 20-25%.
- **[x] PF-2 PASS (estimate, conditional on SMA(200) filter)**

### PF-3: Data Pipeline Availability
- Needs SPY daily Close and a trading calendar only. No buyback data feed required for the base spec (the regime-pause rule uses aggregate buyback data, which is not in the pipeline; drop the pause rule in the backtest).
- **[x] PF-3 PASS (base spec)**

### PF-4: Rate-Shock Regime Plausibility (2022)
- A priori argument: 2022 buybacks were a record (~$900B+), so the open-window flow was supportive, but the Fed rate path dominated returns. The SMA(200) filter is expected to keep the strategy flat for most of 2022 (SPY < SMA(200) from ~Jan to Dec, with brief exceptions).
- No claim of positive 2022 return. The strategy sidesteps the regime.
- **[!] PF-4 WEAK PASS: capital preservation only; long-biased with no hedge.**

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely (expect 0.3-0.7; low exposure and low gross edge)
- OOS persistence: unknown
- Walk-forward stability: unlikely to be demonstrable at 4 trades/year
- Sensitivity risk: medium-high (offset days)
- Known overfitting risks: calendar-offset selection, small effective sample, buyback boom coincides with the sample

## References

- Ikenberry, D., Lakonishok, J., Vermaelen, T. (1995). "Market Underreaction to Open Market Share Repurchases." *Journal of Financial Economics*.
- Bonaime, A., Hankins, K., Harford, J. (2014). "Financial Flexibility, Risk Management, and Payout Choice." *Review of Financial Studies*.
- Related: `41_qc_turn_of_quarter_window_dressing`, `27_qc_post_earnings_drift`
