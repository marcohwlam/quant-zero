# Stage 2 VCP Breakout with Entry-Defined Stop and Risk-Based Sizing (QUA-830)

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-10-26
**Asset class:** equities (US single stocks, liquid large and mid caps)
**Strategy type:** multi-signal
**Status:** hypothesis
**Source:** QUA-830, board request on QUA-829 (screened mid-term trade versus a discretionary ladder plan)
**Class:** momentum. This hypothesis uses the single momentum slot of its batch (Hypothesis Class Diversification Mandate, QUA-181).
**Track:** A (daily bars, holding period weeks to months)

> All numbers marked "prior" or "estimate" below are a priori judgments from the literature and arithmetic. No backtest has been run. Nothing here is a trade call on any ticker.

## Economic Rationale

Three documented effects, combined in one rule:

1. **Intermediate-horizon momentum and 52-week-high anchoring.** Stocks near their 52-week high with positive 6 to 12 month relative strength continue to outperform because investors anchor to the high and under-react to news (George and Hwang 2004, *The 52-Week High and Momentum Investing*, Journal of Finance; Jegadeesh and Titman 1993). The mechanism that limits arbitrage is the risk of momentum crashes and the cost of holding through drawdowns, which keeps the premium alive for a capital-constrained trader.
2. **Volatility contraction before breakout.** A Stage 2 stock whose pullbacks shrink and whose volume dries up has shown that supply is exhausted at the pivot. The breakout on high volume marks the point where demand overwhelms the remaining supply. This is the Minervini VCP and Weinstein Stage 1 to 2 transition (`docs/knowledge/trading-methodology-jlaw-lineage.md` sections 2.3 and 3.2). Practitioner evidence only. No peer-reviewed test of the exact VCP is known to this author.
3. **Asymmetric payoff from a stop defined at entry.** Position size equals risk budget divided by (entry minus stop). Losses are truncated at about 1R, winners are allowed to run. Positive expectancy needs only a modest hit rate (about 40 percent) at a payoff ratio of 2 or more. This changes the shape of the return distribution, not the signal.

The regime gate (index above its 200 day SMA) exists because momentum breakouts fail in clusters during index downtrends (Daniel and Moskowitz 2016, *Momentum Crashes*). The gate turns the strategy into cash in those periods.

## Structural Change Versus Failed Momentum Hypotheses

Prior momentum hypotheses (H05, H07, H07b, H07c, H17, H20, H36) were scheduled rank-and-rebalance rules: monthly or weekly sampling, always invested, no per-position loss limit, and a fixed asset universe (ETFs, crypto). Documented failure modes: too few trades (H17), single-regime alpha (H20), structural Sharpe ceiling near 0.85 (TSMOM family), parameter variance above 100 percent (H20).

This rule differs on four structural points:

| Failed pattern | This rule |
|---|---|
| Trade count tied to a rebalance calendar | Trade count driven by event arrival (VCP breakouts) across hundreds of single stocks, so PF-1 does not depend on a sampling frequency |
| Always invested, no cash state | Explicit cash state from the regime gate and the open risk cap |
| No per-trade loss bound, drawdown set by market | Stop at entry, sizing by risk, total open risk capped, so drawdown is bounded by construction |
| 10 to 30 liquid ETFs, high cross-correlation | Single stock cross-section, lower pairwise correlation |

**Family iteration limit.** This is iteration 1 of a new family ("Stage 2 pattern breakout, single stock"). The closest existing hypothesis is H70, which used a Weinstein Stage 2 filter on a mean-reversion entry, not a breakout entry, so I do not count it as the same family. If the Research Director rules that this overlaps the momentum family of H05 or H36, the limit of 2 Gate 1 iterations before mandatory retirement applies, and I accept that ruling. I do not claim the structural changes above resolve the Sharpe ceiling of the TSMOM family. They remove the stated causes of the earlier failures. Whether they raise Sharpe is the test.

## Entry/Exit Logic

All signals computed on daily close, orders executed at the next open (no look-ahead).

**Universe screen (evaluated daily):**
- Dollar volume: 50 day average of close times volume at least $20M
- Price at least $10
- Trend Template criteria 1 to 6 and 8 from the lineage doc (close above 50, 150, 200 day SMA; 50 > 150 > 200; 200 day SMA higher than 30 trading days ago; close within 25% of the 52-week high). Criterion 7 (30 percent above 52-week low) is kept at 30%.
- Relative strength: 6 month (126 day) total return minus SPY 126 day return is positive, and the stock ranks in the top 30 percent of the universe on this measure

**Regime gate (index level):** SPY close above SPY 200 day SMA AND SPY 200 day SMA higher than 20 trading days ago. If false, no new entries. Open positions keep their stops.

**Setup:** simplified VCP, fully computable from daily OHLCV.
- Base length 30 to 60 trading days
- At least 2 contractions, each measured high to subsequent low; each contraction depth at most 0.6 times the prior depth; each low higher than the prior low
- Final contraction depth at most 10 percent
- 10 day average volume at most 0.75 times the 50 day average volume at the final low (dry-up proxy)
- Pivot = high of the final contraction

**Entry signal:** close above pivot AND day volume at least 1.4 times the 50 day average volume AND close within the top half of the day's range AND price not extended more than 5 percent above the pivot. Buy at next open.

**Earnings rule: skip the entry** (not reduce size). A stop-defined risk budget cannot cover an overnight earnings gap, so reduced size does not restore the 1R loss bound. No entry if the estimated next earnings date falls within 5 trading days. Data: the pipeline holds no earnings calendar, so the next date is estimated as the last detected earnings gap (overnight gap above 3 percent with volume above 2.5 times average) plus 63 trading days, with a plus or minus 3 day window. If Engineering finds that SEC EDGAR filing dates (`strategies/data/eps_edgar.py`) are point-in-time clean, they replace the proxy. Open positions are held through earnings only if they are above +2R on the open stop, otherwise they are sold at the close before the estimated date.

**Stop (set at entry, never moved down):** initial stop = the lower of (final contraction low minus 0.5 ATR(14)) and (entry minus 8 percent). Entries where (entry minus stop) exceeds 10 percent of entry are skipped, which enforces a minimum payoff ratio.

**Sizing:** shares = (0.75 percent of equity) / (entry minus stop). Position cap 15 percent of equity. Total open risk (sum of position size times distance to current stop) capped at 6 percent of equity. New entries are skipped when the cap would be exceeded. Entries are ranked by relative strength when several trigger the same day.

**Exit signal (first to occur):**
1. Stop hit (intraday low at or below stop, fill at stop or next open if gapped)
2. Close below 50 day SMA for 2 consecutive days
3. Trailing stop: once price reaches +2R, the stop moves to breakeven; once price reaches +3R, the stop trails at the higher of breakeven and 3 ATR(14) below the highest close
4. Partial profit: sell one third at +3R (multiple of initial risk)
5. Regime gate off for 5 consecutive days: tighten all stops to the 20 day low (does not liquidate)
6. Time stop: 120 trading days

**Holding period:** swing to position. Expected median 25 to 45 trading days.

## Market Regime Context

- **Works best:** broad uptrends with rising breadth and leadership rotation (2013, 2016 to 2017, 2019, 2020 H2 to 2021).
- **Fails:** choppy range-bound markets where breakouts reverse (late 2015, Q4 2018, parts of 2022 bear rallies) and sharp V-shaped reversals where the stop is gapped through.
- **Pause trigger:** the regime gate. Additional manual pause for the Research Director: 8 consecutive stop-outs.
- **Known weakness:** the 200 day SMA gate lags. The first leg of a crash is taken at full risk, bounded by the 6 percent open risk cap.

## Alpha Decay

All IC figures are a priori estimates from the cited literature for the composite screen, not measurements. Quant Metrics should measure them on the PIT universe before Gate 1.

- **Signal half-life (days):** about 40 (prior; 52-week high and RS effects persist for months, the breakout trigger itself decays faster, about 10 to 15 days)
- **IC estimate (rank IC of screen score vs forward return):** T+1 about 0.01, T+5 about 0.02, T+20 about 0.035, T+60 about 0.03
- **Edge erosion rate:** slow (more than 20 days)
- **Recommended max holding period:** 80 days from the signal half-life rule (2 times half-life). The rule uses 120 as a time stop. **This is a deviation** from the 2x half-life guidance. I keep 120 because exits are stop-driven and I expect few trades to reach it, but the Research Director should decide whether to tighten to 80.
- **Cost survival:** yes (estimate). Round trip cost at the Track A model ($0.005/share each side, 0.05 percent one-way slippage, impact on $20M+ names negligible for a $25K to $100K account): about 12 to 20 bps. Net profit per trade must exceed 15 bps. Expected gross profit per trade is 1.0 to 2.5 percent (prior; Minervini's own 6.5 percent expectancy is not credible out of sample), so the cost-to-gross ratio is about 0.01 to 0.02, well below the 0.25 ceiling.
- **Volatility-adjusted signal-to-noise:** annualized IR estimate = expected return / realized vol. Strategy-level prior: 10 to 14 percent annual return on deployed capital, 12 to 16 percent vol, IR about 0.6 to 1.0 pre-cost. Above the 0.3 warning level. Uncertain, driven by the exposure fraction.
- **Notes:** Crowding risk is real because the pattern is widely published. Edge may be smaller after 2015 than in Minervini's reported 1990s results. Decay rate is regime dependent (faster in the bear rallies of 2022).

## Signal Combination

- **Component signals (3, the policy maximum):**

  | Signal | IC Estimate (prior) | Weight | Source |
  |--------|-------------|--------|--------|
  | S1 Relative strength rank (126 day return vs SPY) | 0.03 to 0.05 at T+20 | Rank filter, not blended | Jegadeesh and Titman 1993 |
  | S2 52-week-high proximity and Trend Template (trend state) | 0.02 to 0.04 at T+20 | Binary pass | George and Hwang 2004; Weinstein stage rules |
  | S3 VCP breakout trigger with volume confirmation | 0.02 to 0.03 at T+5 (least certain) | Binary entry trigger | Minervini; practitioner only |

- **Combination method:** equal weight, sequential AND filter (S1 AND S2 AND S3). No IC weighting, so no Research Director approval needed for the weighting method.
- **Combined signal IC estimate:** not additive. Because the signals are positively correlated (a stock near its high usually has high RS), the AND filter mainly raises selectivity. Expected composite IC at T+20 is 0.04 to 0.06 on the selected subset (prior).
- **Rationale for combination:** S1 and S2 pick the stock state, S3 times the entry and defines the stop. The three address different questions: relative leadership, trend integrity, and entry timing.
- **Overfitting guard:** each signal must show IC above 0.02 individually. **S3 is the weakest claim; its IC may fall below 0.02.** If Quant Metrics measures S3 below 0.02, S3 is dropped and the entry becomes a simple 20 day high breakout with the same stop and sizing.
- **Regime gate:** index-level binary gate, not a stock-selection signal. I do not count it toward the 3-signal limit. **Research Director to confirm this reading of the Signal Combination Policy.** If it counts, S2 must be folded into the gate and the stock-level trend filter reduced to the 150/200 day pair.

## Parameters to Test

Free parameters: 8 (limit for sweep: 4). Remaining parameters are fixed from the lineage doc and are not swept.

| Parameter | Suggested Range | Rationale | Swept? |
|---|---|---|---|
| RS percentile cutoff | 20 – 40 (top percent) | Minervini asks RS 70+ | Yes |
| Breakout volume multiple | 1.2 – 1.6 | Lineage doc 1.4 to 1.5 | Yes |
| Risk per trade (percent equity) | 0.5 – 1.0 | Capped below Minervini's 1.25 | Yes |
| Trailing stop ATR multiple | 2 – 4 | Standard trailing range | Yes |
| Maximum contraction ratio | 0.6 fixed | Lineage doc 50 percent rule with slack | No |
| Final contraction depth cap | 10 percent fixed | Lineage doc 3 to 8 percent plus slack | No |
| Maximum initial risk distance | 10 percent fixed | Payoff ratio floor | No |
| Total open risk cap | 6 percent fixed | Drawdown bound | No |

Sensitivity target: Sharpe change under plus or minus 20 percent parameter perturbation within the Gate 1 variance limit.

## Pre-Flight Gate Checklist

Per CEO Directive QUA-181.

| Gate | Result | Basis |
|---|---|---|
| **PF-1** Trade viability (IS trades / 4 ≥ 30) | **PASS (estimate, margin uncertain)** | Estimate: about 500 liquid names, about 15 percent pass the trend screen in a bull regime, about 1 to 2 percent of those trigger a VCP breakout per month, giving about 75 to 150 raw triggers per year. The 6 percent open risk cap and the earnings skip remove about half, leaving about 40 to 75 trades per year in gate-on years. Over a 5 year IS window with 1 to 2 gate-off years, expect about 150 to 300 trades. Divided by 4: about 38 to 75, above 30. **If the real VCP filter is stricter than estimated, this can drop below 30.** Fallback: relax the contraction rule (2 contractions, ratio 0.7). Verify by counting signals before any parameter work. |
| **PF-2** Long-only MDD < 40 percent in 2000–2002 and 2008–2009 (SPY/QQQ proxy) | **PASS (a priori bound, not simulated)** | Buy and hold SPY lost about 49 percent (2000–2002) and about 55 percent (2008–2009); QQQ lost about 83 percent in 2000–2002. This rule is not buy and hold. SPY crossed below its 200 day SMA in the second half of 2000 and in early 2008. Loss in a gate-on whipsaw is bounded by 6 percent open risk per cycle at gap-free stops. Reaching 40 percent would need roughly 6 or more full-cap losing cycles with no recovery. Bear market rallies in 2001, 2002 and 2008 re-open the gate several times, so I estimate MDD 15 to 25 percent, which is **above the Track A 20 percent target at the upper end**. Single stock PIT data for 2000–2009 is not in the pipeline, so this cannot be simulated with the current data. Proxy test by Engineering: run the regime gate plus a SPY/QQQ 20 day breakout with 1R stop on those windows. |
| **PF-3** Data in existing daily OHLCV pipeline | **PASS with one flagged item** | All signals use daily OHLCV from yfinance or Alpaca. Flagged item: the universe needs a delisting-aware, point-in-time constituent list (H93 precedent: Jan 2018 S&P 500 list with delistings). The earnings rule uses a gap-based proxy from OHLCV, not an external calendar. No fundamentals, no intraday, no options. |
| **PF-4** A priori rationale for 2022 rate shock | **PASS (conditional)** | Mechanism: SPY fell below its 200 day SMA in January 2022 and stayed there for most of the year, so the regime gate blocks most entries (cash is the hedge). During the short gate-on windows (March to early April, August 2022), the RS filter selects relative leaders. In 2022 those leaders were concentrated in energy and defensives, which were in Stage 2 while growth names were in Stage 4. Expected 2022 result: flat to modestly positive (about minus 3 to plus 5 percent), not a large gain. **Condition:** PF-4 asks for positive returns. If the Research Director reads that literally, the honest answer is "not guaranteed". The rule's claim is capital preservation through cash, with a small positive contribution from energy and defensive leaders. |

## Capital and PDT Compatibility

- **Minimum capital required:** $25,000 (about 8 concurrent positions at about 12 percent each). Works down to about $10,000 with fewer positions.
- **PDT impact:** none expected. Median hold is weeks. A stop-out on entry day or day 2 is possible and counts as a day trade. Estimate: fewer than 3 day trades per 5 business days in all but extreme volatility. Under $25K, Engineering should block same-day exits except stop-outs.
- **Position sizing:** 0.75 percent of equity risk per trade, 15 percent maximum position, 6 percent maximum total open risk, about 8 maximum concurrent positions.
- **Capacity:** $20M+ dollar volume names, positions of $25K to $100K are below 1 percent of daily volume. Not capacity constrained at this account size.

## Signal Validity Pre-Check

1. **Survivorship bias:** The main risk. A current-constituent universe overstates results because it contains only stocks that later became large. Mitigation: delisting-aware PIT universe (H93 precedent). The 2018 start of that list limits IS to 2018 onward, which is a short window and includes only one rate-shock regime. Unresolved for 2000–2009.
2. **Look-ahead bias:** All signals use the close of day t and orders fill at the open of t+1. Pivot and contraction lows are computed from completed bars only. The 52-week high uses data through t.
3. **Overfitting risk:** The rule was written once from the lineage doc. Variants tried before writing: 0. Free parameters: 8, swept: 4. Setup thresholds come from published rules, not from fitting.
4. **Capacity:** adequate (see above).
5. **PDT:** see above.
6. **Costs:** survives at the Track A cost model (estimate above).
7. **Signal-to-noise:** IR prior 0.6 to 1.0 pre-cost, above the 0.3 warning line. Uncertain.

## Gate 1 Outlook

Targets: Track A (`criteria.md` v2.7): net OOS Sharpe above 0.7, net profit per trade above 15 bps, MDD below 20 percent, more than 30 IS trades per window, cost-to-gross below 0.25. Objective function charter (`docs/objective-function-charter.md`): net Sharpe above 0.8, net CAGR at least 10 percent, MaxDD within 15 percent.

- IS Sharpe > 1.0: **unlikely to unknown.** Systematic implementations of trend template style screens usually report 0.6 to 1.0. Reaching 1.0 needs the regime gate to avoid most of the drawdown periods.
- OOS Sharpe > 0.7: **marginal.** Plausible only if the edge persists after the pattern became widely known.
- Net profit per trade > 15 bps: **likely.** Expected gross 1 to 2.5 percent against 12 to 20 bps cost.
- Cost-to-gross < 0.25: **likely.**
- Trade count per window > 30: **likely, marginal in gate-off windows.** A 3 month window during a gate-off period will have few or zero trades. Gate 1 evaluation by window should be read with this in mind. **This may fail the per-window rule mechanically even if the strategy works.** Flag for the Research Director.
- MDD < 20 percent: **plausible** by construction (6 percent open risk cap), uncertain in whipsaw years.
- Walk-forward stability: **medium risk.** Bull windows and bear windows differ sharply.
- Sensitivity risk: **medium.** Few swept parameters, but pattern thresholds interact.
- Known overfitting risks: VCP definition has many degrees of freedom; PIT universe window is short (2018 onward), so IS may be effectively one cycle.

## Handoff Notes for Research Director Review

1. Confirm the regime gate is not counted as a fourth signal.
2. Rule on the 120 versus 80 day time stop (2x half-life guidance).
3. Rule on PF-4: literal "positive in 2022" versus "capital preservation with small positive".
4. Confirm the per-window trade-count rule is applied to gate-on windows only.
5. Confirm the family classification (new family, iteration 1).
6. Engineering Director, if forwarded: PIT delisting-aware universe and the earnings gap proxy are the two data items to resolve first.

## References

- Jegadeesh, N. and Titman, S. (1993), Returns to Buying Winners and Selling Losers, Journal of Finance
- George, T. and Hwang, C. (2004), The 52-Week High and Momentum Investing, Journal of Finance
- Daniel, K. and Moskowitz, T. (2016), Momentum Crashes, Journal of Financial Economics
- Minervini, M., *Trade Like a Stock Market Wizard* (2013); Weinstein, S., *Secrets for Profiting in Bull and Bear Markets* (1988)
- `docs/knowledge/trading-methodology-jlaw-lineage.md` sections 2.2 to 2.4 and 3.2
- `research/hypotheses/70_iwm_smallcap_mean_reversion.md` (Stage 2 filter precedent), `93_ta_overnight_top_gainer_pit_universe.md` (PIT universe precedent)
- `criteria.md` v2.7, `docs/objective-function-charter.md`
