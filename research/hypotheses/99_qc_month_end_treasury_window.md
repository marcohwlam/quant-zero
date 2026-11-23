# Month-End Treasury Window (long TLT/IEF, last 3 trading days)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-11-16
**Asset class:** equities (Treasury ETFs)
**Strategy type:** single-signal
**Status:** hypothesis (PF-1 to PF-4 verified on yfinance, QUA-949; ready for Research Director review with the ETF-vs-fund caveat below)

## Economic Rationale

Practitioners attribute a month-end bid in Treasuries to index duration extension: bond index funds and benchmarked managers buy longer duration ahead of the month-end index rebalance, and month-end cash and rebalancing flows concentrate in the last days of the month. The equity analogue, turn-of-month liquidity, is documented in Ogden (1990, Journal of Finance) and Lakonishok and Smidt (1988, Review of Financial Studies). I did not find a peer-reviewed source for the Treasury version that I can cite with certainty, so the mechanism is a practitioner explanation, not an established result. The test below is therefore the only evidence.

Measured on VUSTX (long Treasury mutual fund, 2000-2019, total return): the last 3 trading days of each month average +22.3 bp per day versus -0.2 bp per day on all other days (difference t-stat 7.9).

## Entry/Exit Logic

**Entry signal:**
- At the close of the 4th-last trading day of each month, buy TLT (or IEF, or an equal split).

**Exit signal:**
- Sell at the close of the last trading day of the month. No stop, no profit target.

**Holding period:** Swing (3 trading days, about 13.5% of days exposed)

## Market Regime Context

Works in any rate regime in the tests, with the smallest edge in rising-rate years. Fails when the month-end flow is overwhelmed by a rate shock inside the 3-day window (a surprise FOMC or CPI release on days 28-31). Pause trigger: two consecutive years of negative window returns after costs. Cash otherwise, so there is no regime where the position stays on.

## Alpha Decay

- **Signal half-life (days):** about 3 (the effect is confined to the window, then reverses to zero drift)
- **Edge erosion rate:** fast within the window, but the entry is calendar-fixed so decay applies to crowding rather than holding time
- **Recommended max holding period:** 3 trading days, which is already the design
- **Cost survival:** yes at 5 bps per side. Mean gross window return is about 6 to 20 bp per window depending on instrument, so 10 bps round trip is a large share for IEF (about 3 bp mean window return) and marginal there.
- **Pre-cost IR estimate:** 0.64 to 0.80 on TLT and IEF ETFs (IS), above the 0.3 warning level.
- **Notes:** Crowding is the main risk. If month-end extension is widely traded, the window can start earlier (day 5 or 6 tested, similar Sharpe) and the edge shifts earlier.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| window length n (days before month-end) | 3 – 5 | Tested 3, 4, 5 on real data; n=3 is the primary and n=4, 5 are reported as sensitivity |
| instrument | TLT, IEF, TLT+IEF | Duration exposure choice |

## Capital and PDT Compatibility

- **Minimum capital required:** $5,000 for one ETF position.
- **PDT impact:** none. Holding period is 3 days and one round trip per month per ticker.
- **Position sizing:** 100% of strategy sleeve in one ETF during the window; 12 trades per year per ticker.

## Verified Pre-Flight Gates (real yfinance data, `scripts/pf_verify_h99_h101.py`, `backtests/pf_verify_h99_h101_2026-11-16.json`)

- **PF-1 PASS.** IS 2000-2019. TLT and IEF start in July 2002 (209 IS trades each, TLT+IEF 418, div4 = 104.5). VUSTX and VFITX proxies cover 2000-2019 (240 trades, div4 = 60). Threshold is div4 >= 30.
- **PF-2 PASS.** Strategy return series, 5 bps per side:

| Instrument | Dot-com 2000-02 MDD | GFC 2008-09 MDD |
|---|---|---|
| VUSTX (proxy) | -2.0% | -9.3% |
| VFITX (proxy) | -1.4% | -3.5% |
| TLT (from 2002-07) | n/a (no data) | -13.0% |
| IEF (from 2002-07) | n/a (no data) | -6.4% |
| TLT+IEF | n/a (no data) | -9.6% |

  Both windows are under 40%. The dot-com window for ETFs is covered by the mutual fund proxies only.
- **PF-3 PASS.** Daily OHLCV from yfinance for TLT, IEF, VUSTX, VFITX.
- **PF-4 PASS, with a stated limit.** A priori: exposure is 13.5% of days, the long position is only held while month-end index flows are the marginal buyer, and a bond rate shock is bounded by the 3-day window. Measured 2022 return of the window strategy: TLT +1.1%, IEF +3.2%, TLT+IEF +2.2% (MDD in 2022: -4.9%, -2.4%, -3.6%). The 2022 result is one year of evidence, not proof of a rate-shock mechanism; the window return was positive despite the worst bond year on record.

## Measured Results (gross of nothing; 5 bps per side included)

| Instrument | IS Sharpe | OOS 2020-24 Sharpe |
|---|---|---|
| VUSTX proxy, n=3 | 1.56 | 0.87 |
| VFITX proxy, n=3 | 1.86 | 1.36 |
| TLT, n=3 | 0.80 | 0.39 |
| IEF, n=3 | 0.64 | 0.61 |
| TLT+IEF, n=3 | 0.76 | 0.47 |

Sharpe is computed on the daily series including the zero-return days outside the window, so it reflects the full-capital profile. Absolute return is low (about 2 to 4% per year at 1x on a fully allocated sleeve), because the position is on 13.5% of days.

**Caveat on the fund proxies.** VUSTX and VFITX are mutual funds priced at NAV once a day, with accrual and valuation conventions that can inflate month-end patterns. The tradable instruments are the ETFs, and their IS Sharpe (0.64 to 0.80) is roughly half the proxy Sharpe. Gate 1 should be judged on TLT and IEF, not the proxies.

## Variant Tested and Rejected: Equity/Bond Rebalancing Switch

Hypothesis: hold SPY in the window when SPY month-to-date return is negative (pensions buy equities) and bonds when it is positive. On VFITX the switch scored IS Sharpe 0.87 and OOS 0.30, versus 1.86 and 1.36 for bonds only. The SPY leg degraded results, so it is dropped. Output in `backtests/pf_verify_h100_2026-11-16.json`.

## Gate 1 Outlook

- IS Sharpe > 1.0: unlikely on ETFs (0.64 to 0.80), likely only on the mutual fund proxies
- OOS persistence: TLT weaker (0.39), IEF holds (0.61)
- Walk-forward stability: likely, 209 to 418 trades gives about 52 to 104 per fold
- Sensitivity risk: medium. n=3, 4, 5 all positive (VUSTX IS Sharpe 1.56, 1.28, 1.29) but 3 windows were examined on the same data.
- Known overfitting risks: window length selected after looking at 3 values; no other parameters. Four weakly related ideas were screened in this batch (see H100, H101 and the payday, VIX term structure tests in the QUA-949 comment).
- Family iteration count: 0 prior Gate 1 runs for this mechanism. H44 (LQD/IEF timer) is a different mechanism.

## QuantConnect Source Caveat

- **Original QC algorithm name and URL:** none verified. Month-end Treasury seasonality is discussed in community threads, but I did not locate a specific algorithm and will not cite one.
- **QC backtest window and IS cherry-pick risk:** QC TLT/IEF data start in 2002; community results quoted for 2010-2020 sit in a falling-yield period that favors long duration. Discount any quoted Sharpe above 1.5.
- **Adaptation:** daily bars from yfinance, entry and exit at the close, calendar rule only.
- **Top-10 clone / crowding:** not confirmed outside the top-10 most cloned; the calendar effect itself is widely discussed by practitioners.

## References

- Ogden, J.P. (1990), Turn-of-Month Evaluations of Liquid Profits and Stock Returns, Journal of Finance 45(4). Equity analogue.
- Lakonishok, J. and Smidt, S. (1988), Are Seasonal Anomalies Real? A Ninety-Year Perspective, Review of Financial Studies 1(4). Equity analogue.
- `research/hypotheses/22_tv_turn_of_month_multi_etf.md`, `research/hypotheses/44_lqd_ief_credit_risk_appetite_timer.md`
- `scripts/pf_verify_h99_h101.py`, `scripts/pf_verify_h100_month_end_switch.py`
