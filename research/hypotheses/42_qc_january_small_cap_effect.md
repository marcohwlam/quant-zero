# H42: January Small-Cap Tax-Loss Reversal — IWM January Seasonal

**Version:** 1.0
**Author:** Alpha Research Agent (QC Discovery — QUA-308)
**Date:** 2026-03-17
**Asset class:** US equities (ETFs)
**Strategy type:** single-signal, calendar/seasonal
**Status:** hypothesis

## Economic Rationale

The January Effect is one of the oldest and most replicated anomalies in financial markets: small-capitalization stocks systematically outperform large-cap stocks in January, with the majority of the outperformance concentrated in the first 5 trading days of the year. The core mechanism is **tax-loss selling reversal**: in December, investors sell losing small-cap positions to realize capital losses for tax purposes, depressing small-cap prices below fundamental value. When selling pressure exhausts at year-end, prices snap back in January — often sharply.

**Mechanism (tax-loss reversal hypothesis, supported by institutional flow amplification):**

1. **Tax-loss selling exhaustion (Keim 1983, Reinganum 1983):** Individual investors concentrate tax-loss harvesting in December to reduce year-end capital gains. Small-cap stocks, with lower institutional holding and higher individual ownership, bear disproportionate selling pressure. By December 31, these stocks are undervalued relative to their fundamental anchors. January buying flows reverse this pressure.

2. **Institutional year-end window dressing amplification:** Year-end window dressing exacerbates small-cap selling: fund managers sell small-cap losers in Q4 to avoid disclosing embarrassing positions in annual reports (13-F filings). This adds institutional supply to individual tax-loss selling, amplifying the December suppression effect. The January reversal is therefore larger than pure tax-loss mechanics would predict.

3. **January inflow effect:** Defined-benefit pension plans and 401(k) plan matching contributions deployed on January 1 disproportionately target equity index funds, but secondary allocation to small-cap funds creates above-average demand for IWM constituents in early January.

4. **Risk appetite reset:** Investors psychologically "reset" risk appetite at the calendar year turn, increasing willingness to re-enter beaten-down small-cap positions. Behavioral calendar-anchoring amplifies the fundamental tax-loss reversal.

**Evidence:**
- Keim (1983): 1963–1979 CRSP data; small-cap January return premium ≈ 5–8% over large-cap in same month
- Reinganum (1983): Independent replication; confirmed tax-loss hypothesis as primary driver
- Haugen & Lakonishok (1988): *The Incredible January Effect* — documented the full anomaly with cross-country evidence
- Roll (1983): Provided evidence linking December tax-loss selling to January reversal
- Post-2003 (after SEC Regulation SHO): Effect has modestly weakened but remains statistically significant in the first 5 trading days of January per Gu (2003) and updated Quantpedia data

**Implementation (ETF-based, yfinance-compatible):**
- **Long IWM** (iShares Russell 2000 ETF, launched May 2000) in January
- **Compare to benchmark SPY** or hold SPY the other 11 months
- No need for individual stock data, earnings calendars, or fundamental databases — pure calendar + ETF signal

**Novel vs. existing hypotheses:**
- H22 (Turn of Month): Captures all 12 month-end windows. H42 is specifically the January IWM long — targeting IWM vs. SPY rather than absolute SPY timing.
- H25/H26 (Options Expiration / Pre-Holiday): Mechanism-distinct calendar effects.
- H40 (Halloween): November entry overlaps — but H42 exits by end of January; H40 holds through April. H42 is a sub-component of the winter period that focuses on the IWM/SPY spread rather than the absolute equity/cash switch.
- H41 (Turn of Quarter): Quarter-start inflow signal for large-cap SPY. H42 uses the *small-cap* version of this effect in January specifically — distinct asset (IWM vs. SPY) and distinct mechanism (tax-loss reversal vs. generic window dressing).
- H31 (IWM Small-Cap Turn of Month): Checks if IWM does a monthly ToM effect. H42 is specifically the full-January holding of IWM as a **spread vs. SPY** — a different bet (IWM outperformance relative to large-cap, not absolute IWM long).

## Entry/Exit Logic

**Entry signal — Option A (pure January hold):**
- December 31 close (or last trading day of December): buy IWM (100% portfolio or defined size)
- Hold through January 31 close (or last trading day of January)
- January 1 is market holiday — first entry is December 31 close or January 2 open

**Entry signal — Option B (concentrated first-week):**
- December 31 close: enter IWM
- Exit after 5 trading days into January (captures the front-loaded reversal only)
- This captures the strongest part of the anomaly but reduces holding period to ~1 week

**Exit signal:**
- Option A: January 31 close — exit IWM, return to SPY (or cash)
- Option B: 5th trading day of January close — exit IWM, shift immediately to SPY

**Additional filter:**
- Only enter if IWM is below its 12-month high by > 5% (i.e., small-caps are meaningfully below peak, consistent with tax-loss selling thesis having room to run)
- Skip year if December IWM return was positive and > 5% (suggests no meaningful tax-loss selling pressure, reducing the reversal magnitude)

**Holding period:** 21 trading days (full January) or 5 trading days (first week variant)

## Market Regime Context

**Works best:** Years following weak December small-cap performance (high tax-loss selling pressure); bear market recoveries at year-end; high individual investor activity environments.

**Tends to fail:** When December small-cap prices have already recovered (no tax-loss overhang), in January 2022-type environments (Fed tightening shock overwhelms the seasonal pattern), and when IWM is above its 12-month high entering January.

**Regimes to pause:** If VIX > 35 entering January (extreme panic environment may prevent the tax-loss buying recovery). If IWM has already rallied > 10% in December (suggests tax-loss selling exhausted itself already, no reversal needed).

**PDT note:** 2 trades/year (enter December 31, exit January 31). Zero PDT concern.

## Alpha Decay

- **Signal half-life (days):** ~5 trading days (Keim 1983 documents that more than half the January small-cap premium arrives in the first week of January)
- **Edge erosion rate:** Fast within January (front-loaded), but the annual calendar reset means the signal recurs predictably each year
- **Recommended max holding period:** 5–21 trading days depending on variant. Do not extend beyond January — historical data shows the IWM/SPY spread flattens by February.
- **Cost survival:** Yes — 2 round-trip trades/year = $100/year cost on $25K = 0.4% drag. Historical January IWM outperformance vs. SPY is documented at 2–5%. Post-cost alpha: 1.6–4.6%.
- **Notes:** Some evidence that the January Effect has been partially front-run into late December since Keim's 1983 publication. Testing entry on December 26–28 vs. December 31 may recover front-run alpha.
- **Annualized IR estimate:** Isolating January only: assume 3% IWM excess return vs. SPY in January, with ~4% volatility of this spread over 21 days → annualized (×√12 for 1-month holding scaled to year) IR ≈ 3% / (4% × √12) ≈ 0.22 on January-period basis. However, if compared to SPY (or cash) held the other 11 months with normal SPY returns, combined strategy IR likely 0.3–0.5 annualized. **Warning: marginal pre-cost IR suggests this hypothesis requires combination with another signal or the Halloween Effect (H40) as a multi-calendar portfolio.**

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| entry_date | Dec 26, Dec 28, Dec 31 | Test front-running of the signal |
| exit_date | Jan 5 (1 week), Jan 15 (mid), Jan 31 (full) | Front-loaded vs. full-month hold |
| december_filter_threshold | 0%, -5%, -10% December IWM return | Ensure tax-loss overhang exists |
| 12m_below_peak_filter | 5%, 10%, 15% below 52-week high | Confirm small-cap suppression |

## Capital and PDT Compatibility

- **Minimum capital required:** $500 (IWM ≈ $220/share as of 2026; fractional shares available)
- **PDT impact:** None — 2 trades per year, held for 5–21 days each.
- **Position sizing:** 100% of portfolio in IWM during January; 100% SPY or 100% cash the other 11 months. Single-position, no concurrent positions.

## Gate 1 Outlook

- **IS Sharpe > 1.0:** Unlikely as a standalone strategy on full-year returns — the 11-month SPY hold will dominate. Need to evaluate as a *spread* (IWM - SPY return in January) with proper annualized risk-adjustment. IS Sharpe on January-period only: ~0.5–0.8.
- **OOS persistence:** Moderate — Post-1983 publication, the anomaly has weakened and partly front-run into late December. The first-week variant shows better OOS persistence than the full-month hold.
- **Walk-forward stability:** Low-Moderate — only 1 January window per year; walk-forward requires 20+ years to get meaningful out-of-sample windows. Use minimum 10-year IS, 5-year OOS.
- **Sensitivity risk:** Moderate — entry date sensitivity (late December vs. January 1) can materially shift captured alpha.
- **Known overfitting risks:** Minimal by design — pure calendar rule with simple filters. Risk is that post-2000 evidence (with IWM as the vehicle) is thinner than the theoretical evidence from individual stocks.
- **Primary concern:** IS Sharpe likely below 1.0. This strategy is best evaluated as a **component signal** in a multi-calendar portfolio alongside H40 (Halloween) and H22/H41 (ToM/ToQ). Recommend Research Director approval for submission as part of a multi-calendar combined strategy rather than standalone Gate 1 candidate.

## QuantConnect Source Caveat

- **Original QC strategy:** "January Effect" — QuantConnect Investment Strategy Library (Quantpedia #0001)
- **QC backtest window:** QuantConnect's version typically runs 2009–present (post-ETF inception). This hypothesis uses IWM (2000+) — 25 years of data, sufficient for 5+ year OOS window.
- **Cherry-pick risk:** LOW — the January Effect is the most replicated calendar anomaly in financial history (Keim 1983, Reinganum 1983, Haugen & Lakonishok 1988). It is not a data-mined artifact.
- **Crowding risk:** MODERATE — widely known since 1983. The first-week front-running risk is real; entry on December 26–28 may be necessary to capture the full effect. This is a testable robustness check.
- **Novel signal insight vs. H01–H39:** H31 tested IWM Turn of Month (monthly ToM applied to IWM). H42 is specifically the annual January IWM seasonal — a distinct annual calendar effect driven by tax-loss reversal, not the generic monthly ToM mechanism. This is the first tax-loss-reversal hypothesis in the pipeline.

## References

- Keim, D.B. (1983). "Size-Related Anomalies and Stock Return Seasonality: Further Empirical Evidence." *Journal of Financial Economics*, 12(1), 13–32.
- Reinganum, M.R. (1983). "The Anomalous Stock Market Behavior of Small Firms in January." *Journal of Financial Economics*, 12(1), 89–104.
- Roll, R. (1983). "Vas ist das? The Turn-of-the-Year Effect and the Return Premia of Small Firms." *Journal of Portfolio Management*, 9(2), 18–28.
- Haugen, R.A. & Lakonishok, J. (1988). *The Incredible January Effect*. Dow Jones-Irwin.
- Gu, A.Y. (2003). "The Declining January Effect: Evidences from the U.S. Equity Markets." *Quarterly Review of Economics and Finance*, 43(2), 395–404.
- Quantpedia #0001: "January Effect in Stocks"
- Related hypotheses: H22 (Turn of Month), H31 (IWM Small-Cap TOM), H40 (Halloween), H41 (Turn of Quarter)
