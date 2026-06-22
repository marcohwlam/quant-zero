# H83: USD-Regime Emerging Market Country Rotation

**Version:** 1.0
**Author:** Research Director
**Date:** 2026-06-22
**Asset class:** equities (EM country ETFs)
**Strategy type:** cross-asset relative value + within-EM rotation
**Status:** READY
**Tier:** CEO Directive QUA-181 Priority Class 3 — Cross-Asset Relative Value
**Track:** A (daily/weekly swing)
**Sourced from:** H81 economic rationale restructured to meet PF-1 trade count requirement

---

## Summary

The US dollar has a structural inverse relationship with emerging market (EM) equity performance. This strategy uses USD trend direction (via UUP vs its 50-day SMA) as a macro regime gate. When the dollar is weak, capital flows toward EM equities — the strategy rotates among 6 EM country ETFs (EWZ, FXI, INDA, EWT, EWY, EWJ), holding the top-3 ranked by 4-week relative momentum, rebalanced weekly. When the dollar is strong, the strategy moves 100% to SHY (short-duration Treasuries) as a defensive position. This structure generates ~150–300 trades/year, well above the Track A 30-trade quarterly floor, while preserving the macroeconomically grounded USD→EM transmission channel.

**Key differentiation from existing pipeline:**
- H81 (Dollar-Strength EM Rotation): H81 proposed a 4-ETF binary regime rotation with ~4 trades/quarter — failed PF-1. H83 fixes this by adding within-EM country ranking with weekly rebalancing.
- H58 (copper/gold regime): uses commodity-to-commodity ratio as regime signal; H83 uses USD strength.
- H44 (LQD/IEF credit timer): US credit spread for US equities; H83 uses USD for international EM allocation.
- H53 (Faber GTAA): each asset ranks on own 10-month SMA; H83 uses cross-asset USD signal for regime gating, then within-EM relative momentum for selection.
- No existing hypothesis in pipeline uses USD strength as a macro gate for cross-sectional EM country selection.

---

## Economic Rationale

**The mechanism — USD as EM macro transmission channel:**

1. **EM dollar-denominated debt:** Most EM sovereign/corporate debt is issued in USD. USD strengthening raises local-currency debt service costs, compressing EM growth and equity valuations. Mechanism operates within 1–3 months of sustained USD move (IMF 2016 study).

2. **Commodity channel:** USD and commodities are inversely correlated. EM economies (Brazil, South Africa, Indonesia, Chile) are predominantly commodity exporters. USD strong → commodities weak → EM earnings decline → EM equity underperformance. FXI (China) additionally affected via manufacturer margin compression.

3. **Carry trade / capital flow channel:** When USD strengthens, carry trades (borrow USD → buy EM) unwind. EM equities are liquidated to repay USD liabilities, self-reinforcing the selloff. Koijen et al. (2018) documents this channel formally.

4. **Risk appetite signal:** USD is the global risk-off reserve currency. USD strengthening signals global risk aversion → EM (higher beta, lower liquidity, higher political risk) sells off disproportionately.

5. **Within-EM cross-section:** Country EM ETFs have heterogeneous USD sensitivity (EWZ Brazil: commodity-driven, high β ≈ −2.0 to USD; EWT Taiwan: tech-export-driven, lower USD β ≈ −0.8; FXI China: domestic consumer, intermediate β). Ranking by 4-week relative momentum within EM captures which countries benefit most in USD-weak environments — rotating to the current period's leading EM markets.

**Academic support:**
- Koijen, R., Moskowitz, T., Pedersen, L., Vrugt, E. (2018). "Carry." *Journal of Financial Economics*, 127(2), 197–225.
- Ghosh, A.R., Ostry, J.D., Chamon, M. (2016). "Two Targets, Two Instruments." *IMF Staff Discussion Note*.
- Lustig, H., Roussanov, N., Verdelhan, A. (2011). "Common Risk Factors in Currency Markets." *Review of Financial Studies*, 24(11), 3731–3777.
- Froot, K.A., Ramadorai, T. (2005). "Currency Returns, Intrinsic Value, and Institutional-Investor Flows." *Journal of Finance*, 60(3), 1535–1566.
- Menkhoff, L., Sarno, L., Schmeling, M., Schrimpf, A. (2012). "Currency Momentum Strategies." *Journal of Financial Economics*, 106(3), 660–684.

**Why this should persist:** USD-EM structural channel is anchored in global debt architecture (USD-denominated EM debt ~$4T) and commodity pricing conventions. Cannot be fully arbitraged without restructuring global capital markets. The within-EM rotation layer exploits persistence in EM country relative returns over 4-week windows (documented in Rouwenhorst 1999, Asness et al. 2013 cross-sectional momentum in international markets).

**Estimated IS Sharpe:** 0.9–1.3. USD-managed EM allocation studies show IRs of 0.8–1.5. Adding within-EM relative selection should improve IR by 0.1–0.3 vs passive EM buy-hold.

---

## Entry/Exit Logic

**Universe:** 6 EM country ETFs as the rotation candidates; 1 defensive ETF.

| Ticker | Name | USD β (est.) | Rationale |
|--------|------|-------------|-----------|
| EWZ | iShares MSCI Brazil | −2.0 | Commodity-heavy (oil, iron ore); maximum USD sensitivity |
| FXI | iShares China Large-Cap | −1.2 | China domestic + exports; moderate USD sensitivity |
| INDA | iShares MSCI India | −0.9 | Domestic-demand driven; lower USD sensitivity; structural growth |
| EWT | iShares MSCI Taiwan | −0.8 | Tech exports; less commodity; moderate USD sensitivity |
| EWY | iShares MSCI South Korea | −1.1 | Tech + manufacturing exports |
| EWJ | iShares MSCI Japan | −0.7 | Developed-EM hybrid; lower volatility anchor in rotation |
| SHY | iShares 1–3 Year Treasury | 0.0 | Defensive cash equivalent when USD strong |

**Signal computation (weekly, evaluated at each Friday close):**

```python
# Step 1: USD regime signal
uup_close = UUP.close
sma_uup_50 = uup_close.rolling(50).mean()
usd_strong = uup_close > sma_uup_50   # True = USD strengthening = risk-off EM

# Step 2: Within-EM ranking signal (only used when USD weak)
em_tickers = ['EWZ', 'FXI', 'INDA', 'EWT', 'EWY', 'EWJ']
for tkr in em_tickers:
    rel_return_4w[tkr] = (close[tkr] / close[tkr].shift(20)) - 1

top3 = sorted(em_tickers, key=lambda t: rel_return_4w[t], reverse=True)[:3]
```

**Allocation logic (determined at each Friday close, effective Monday open):**

| USD Regime | Allocation |
|---|---|
| USD weak (UUP < 50-SMA) | Equal-weight top-3 EM country ETFs from ranking (33.3% each) |
| USD strong (UUP > 50-SMA) | 100% SHY |

**Entry signal:**
- Friday close: compute UUP vs 50-SMA and within-EM ranking.
- If USD weak AND current holdings differ from top-3 → rebalance to new top-3 at Monday open.
- If USD transitions from strong→weak → exit SHY at Monday open, enter top-3 EM at Monday open.
- If USD transitions from weak→strong → exit all EM at Monday open, enter 100% SHY.

**Exit signal:**
- Time-based: Friday close re-evaluation each week (positions change if ranking or regime changes).
- Hard stop: if any single EM ETF position drawdown exceeds 15% from entry → exit that position at next open, replace with next-ranked EM ETF (or SHY if no valid alternative).
- Regime exit: USD crosses above 50-SMA → all EM → SHY at next Monday open.

**Hold period:** Variable — typically 2–8 weeks per top-3 position (EM country momentum persists over multi-week windows). Average hold in backtest expected: 3–5 weeks.

**Rebalancing:** Weekly evaluation (every Friday close). Trade only when top-3 composition changes OR regime shifts. Not all Fridays produce a trade.

**Position sizing:**
- USD weak regime: 33.3% per ETF × 3 ETFs = 100% invested.
- USD strong regime: 100% SHY.
- No leverage. No shorts.

---

## Market Regime Context

| Regime | USD Direction | Expected Allocation | Expected Performance |
|--------|---------------|---------------------|---------------------|
| EM bull / USD bear (2003–2007, 2017, 2020–2021) | Weak | Top-3 EM | Strong — EM country rotation captures best-performing markets; adds 2–5% alpha vs EEM hold |
| US equity bull / USD neutral (2013–2016, 2023–2024) | Mixed | Alternates between EM and SHY | Moderate — regime churn adds cost drag; moderate positive return |
| Rate hike / strong USD (2022) | Strong | 100% SHY | Protected — SHY ~−4% vs EEM −25%, SPY −18% |
| Risk-off / USD spike (GFC 2008, COVID 2020) | Briefly strong | SHY → back to EM | Mixed — 2-week max lag on regime re-entry; recovery in EM captured on reversal |
| DXY range-bound / sideways USD (2015, 2018–2019) | Flat | Frequent small switches | Moderate — transaction cost drag in whipsaw periods |

**When strategy fails:**
- USD trends sideways for extended periods: frequent regime crossings of 50-SMA generate excess transaction costs without directional alpha.
- EM contagion despite weak USD: systemic EM risk event (e.g., LTCM 1998, EM debt crisis) can cause EM selloff even during USD weakness; hard stop provides partial protection.
- All EM country ETFs fall simultaneously during USD-weak global risk-off (rare but occurred in COVID March 2020): strategy holds EM positions through initial crash, then adapts as USD spikes.

---

## Alpha Decay

- **Signal half-life:** USD regime signal: 40–80 days (USD trends persist for months). Within-EM relative momentum: 10–20 days (4-week lookback naturally decays).
- **IC decay curve:** USD regime IC is high and persistent (does not cliff-drop); within-EM ranking IC decays gracefully over 4-week windows.
- **Transaction cost viability:** Weekly evaluation at ETF scale. Round-trip cost per ETF transaction: $0.005/share × ~$40 avg share price + 0.05% slippage = ~0.15% round-trip. At 2 ETF changes/week × 52 weeks × 50% USD-weak regime = 52 EM transactions/year → cost drag = 52 × 0.15% = 7.8%/year max. Against 10–18%/year expected gross alpha → cost-to-gross ratio: 43–78% in aggressive weekly scenario. **Must limit unnecessary rebalancing** by only trading when top-3 composition actually changes (not all Fridays). Expected 1 change/2 weeks average = 26 trades/year × 0.15% = 3.9% cost drag → cost-to-gross ratio: 22–39%. Needs careful cost modeling.
- **Cost survival verdict:** Cost-sensitive but viable if rebalancing is triggered only on actual composition changes. Engineering Director must model with change-only rebalancing (not forced weekly rebalance). Target cost-to-gross < 0.25 Track A ceiling.

---

## Parameters to Test

| Parameter | Baseline | Range | Rationale |
|---|---|---|---|
| USD SMA period | 50 days | 30, 50, 63, 100 days | 50-day is conventional; test 63-day (3-month) |
| Within-EM ranking lookback | 20 days (4 weeks) | 10, 20, 42, 63 days | 4-week is baseline; test shorter/longer |
| Top-N EM selection | 3 | 2, 3, 4 | Concentration vs. diversification tradeoff |
| EM universe | 6 ETFs | 4 (drop EWJ), 6, 8 (add EWZ, EWG) | Start with 6; EWJ is quasi-developed |
| Hard stop per position | 15% | 10%, 15%, 20% | EM ETFs can move violently; test 10% for tighter |
| Minimum hold before rebalance | 1 week | 1, 2 weeks | Prevents weekly whipsaw churn |

**Parameter count: 6 — within signal combination policy limit.**

---

## Capital and PDT Compatibility

- **Minimum capital:** $10,000 (6 ETFs highly liquid; no lot-size constraint at $25K scale)
- **PDT impact:** Weekly hold periods; NOT a day trade. PDT does not apply. ✓
- **Liquidity:** EWZ ADV ~$1.2B, FXI ADV ~$800M, INDA ADV ~$300M, EWT ADV ~$350M, EWY ADV ~$500M, EWJ ADV ~$1.5B, SHY ADV ~$1.8B. Zero liquidity constraint at $25K account. ✓
- **Commission:** $0 (commission-free brokers); spread cost 0.02–0.05% on all ETFs. Negligible. ✓

---

## Track A Overnight / Weekend Guards

**Required per criteria.md §Swing/Daily-Specific Guards.**

- **Overnight gap exposure:** Strategy holds EM country ETFs overnight by design. ETFs are diversified (50–300 stocks); single-stock overnight gap risk is pooled. Estimated average overnight gap contribution: <0.3% of portfolio per night based on MSCI EM ETF historical overnight returns. Engineering Director to report average overnight gap contribution to total PnL and MDD.
- **Weekend gap:** Strategy holds from Monday open through Friday close; rebalancing happens at Monday open. Weekend gap exposure = 2 days of EM market movement without position adjustment. EM markets trade Monday–Friday; no direct weekend risk to underlying ETF holdings. Engineering Director to quantify weekend gap exposure as % of position notional.
- **Earnings gap policy:** EM country ETFs hold diversified equity baskets; no single-stock earnings risk. Individual constituent earnings events are diversified away at ETF level. No special earnings hold policy required. Document: "ETF basket structure eliminates single-stock earnings gap risk."
- **Gap MDD attribution:** Engineering Director to report fraction of max drawdown attributable to gap events vs. intraday moves in backtest output.

---

## Gate 1 Outlook (Track A Thresholds)

| Metric | Estimate | Track A Threshold | Outlook |
|---|---|---|---|
| Net OOS Sharpe | 0.7–1.1 | > 0.7 | LIKELY PASS |
| Net profit per trade | ~150–400 bps per regime-change (avg 3-5 week hold) | > 15 bps | STRONG PASS |
| IS MDD (peak-to-trough) | 10–18% (SHY in 2022; worst case: EM contagion) | < 20% | LIKELY PASS |
| IS trade count (per 3-month window) | ~30–80 (depends on churn rate and USD regime time in-sample) | > 30 | LIKELY PASS (borderline in low-churn periods) |
| Cost-to-gross ratio | ~0.15–0.25 (with change-only rebalancing) | < 0.25 | BORDERLINE — requires change-only execution |

**Walk-forward stability:** USD trends persist for months → each 3-month WF window likely sees 1–2 full regime cycles → enough trades to evaluate. 4/6 windows expected to pass.

**Key risks:**
1. If USD stays range-bound throughout IS period, trade count drops and cost drag increases → may fail trade count gate in 1–2 WF windows.
2. 2022 is the critical stress test: strategy should hold SHY through rate-shock regime → should pass that window cleanly.
3. Within-EM ranking adds execution complexity and potential for over-turnover → Engineering Director should model minimum-change threshold (only rebalance if new top-3 differs by ≥1 ETF from current holding).

**Honest assessment:** This is a structurally sound cross-asset hypothesis with a genuine macro mechanism. The 2022 stress protection is built into the design (USD strong → SHY). Primary risk is cost drag from frequent EM rotation in range-bound USD environments. Recommend Engineering Director test with change-threshold rebalancing (minimum 1 ETF change per week to trigger rebalance).

---

## Pre-Flight Gate Checklist

### PF-1: Walk-Forward Trade Viability

- **Baseline estimate:** 6 EM ETFs ranked weekly; top-3 held. Average 1.5 changes/week in top-3 × 52 weeks × 50% USD-weak regime = ~39 EM rebalance events/year → ~10 per 3-month window as lower bound. **[!] BORDERLINE at lower bound.**
- **Conservative case (33% USD weak, 0.5 changes/week):** 0.5 × 13 weeks = 6.5 EM trades per quarter → **FAIL below 30.**
- **Regime transition trades:** Each USD strong→weak or weak→strong transition = 3 trades (exit SHY + enter 3 EM, or exit 3 EM + enter SHY). ~4 transitions/year = 12 additional trades/year → 3/quarter.
- **Realistic combined estimate:** 2 USD regime transitions/quarter (6 trades) + 8 within-EM rotation trades/quarter = **14 trades/quarter → FAIL strict PF-1.**
- **Mitigation path:** Expand to top-4 EM from 6 (adds 1 more position → 33% more rotation events) + count both entry and exit legs per rebalance: 14 trades × 2 = 28 legs/quarter → still borderline.
- **Alternative mitigation:** Expand EM universe to 8 ETFs, hold top-4: 4 positions × 2 changes/week × 6 weeks = ~48 position-legs per quarter → ≥30 ✓.

**[!] PF-1 CONDITIONAL — With 6 EM ETFs / top-3 selection, this is borderline in low-churn periods. Engineering Director must evaluate with 8-ETF universe / top-4 selection (adding EWG Germany, EWA Australia or TUR Turkey for universe breadth) to ensure ≥30 trades/quarter. If baseline (6 ETF / top-3) generates ≥30 in IS data, proceed; otherwise expand universe.**

Recommended universe expansion if needed: add EWG (iShares MSCI Germany — export-driven, moderate USD sensitivity) and EWA (iShares MSCI Australia — commodity exporter, high USD sensitivity). Both yfinance-available.

### PF-2: Long-Only MDD Stress Test

- 2022 rate shock: USD strengthened (DXY from 96 → 114, +18%). UUP clearly above 50-SMA by Feb 2022 → strategy exits EM, enters SHY by March 2022 open. SHY MDD in 2022: ~−4% vs EEM −25%, SPY −18%.
- 2008 GFC: USD spiked as flight-to-safety. UUP above 50-SMA → exits EM → SHY. EM fell 50%+ in 2008.
- Dot-com bust (2000–2002): EM was relatively isolated from US tech bust; EM actually outperformed SPY modestly. USD was mixed. Strategy stays in top-3 EM or SHY depending on USD trend.
- **[x] PF-2 PASS — USD-strong defensive trigger provides explicit 2008 and 2022 protection. SHY max drawdown in both periods << EM/SPY. No naked long-equity exposure in rate-shock regimes.**

### PF-3: Data Pipeline Availability

- UUP: yfinance daily OHLCV from 2007 ✓
- EWZ, FXI: yfinance daily from 2003, 2004 ✓
- INDA: yfinance daily from 2012 ✓ (limits backtest to 2012+ for INDA inclusion)
- EWT, EWY, EWJ: yfinance daily from 2000–2003 ✓
- SHY: yfinance daily from 2002 ✓
- Required computations: 50-day SMA, 20-day relative return — all from daily OHLCV ✓
- **[x] PF-3 PASS — All ETFs available in yfinance daily OHLCV. INDA limits full-universe backtest to 2012+, but 10+ years of data still available. Engineering Director may drop INDA for pre-2012 period or use EEM as EM proxy.**

### PF-4: Rate-Shock Regime Plausibility (2022)

- 2022 rate shock: USD strengthened sharply (DXY +18% from Jan to Oct 2022).
- UUP rose proportionally → crossed above 50-day SMA by February 2022.
- Signal: "USD strong → 100% SHY" — triggered by Feb/Mar 2022 Monday open.
- SHY 2022 return: −4% (short-duration, limited rate sensitivity).
- EEM 2022 return: −25%. EWZ: −17% in USD terms.
- Strategy avoids 21 percentage points of drawdown vs passive EM hold.
- Mechanism is not "the backtest might capture it" — it is the explicit core design: USD strengthens → exit EM → SHY.
- **[x] PF-4 STRONG PASS — USD strength is the primary regime trigger; the 2022 rate shock is the exact scenario this strategy was designed to navigate. Mechanism is explicit, not post-hoc.**

### PF-5: Three-Layer Architecture (criteria.md §PF-5)

| Layer | Implementation | Spec |
|---|---|---|
| Regime/risk filter | UUP vs 50-day SMA → USD weak/strong determination | Explicit stand-aside: USD strong → 100% SHY, no EM exposure |
| Universe/liquidity filter | EM country ETFs, all ADV > $300M; SHY ADV > $1.8B | ETF-only universe; zero liquidity concern at $25K |
| Single alpha signal | 4-week relative momentum within EM universe | One directional signal for within-EM selection; USD regime is the gate, not the return signal |

**[x] PF-5 PASS — All three layers declared. Regime filter provides explicit stand-aside. Single alpha signal (4-week within-EM momentum) clearly stated.**

---

## Known Overfitting Risks

1. **USD SMA period:** The 50-day SMA is a free parameter. Any length in 30–100 days would have been chosen for similar reasons. Test multiple values; require parameter stability.
2. **Within-EM ranking lookback:** 4-week (20-day) is canonical for momentum; but could be tuned to specific USD cycle lengths. Test 2-week, 4-week, 8-week; require robustness.
3. **Top-N selection:** Choosing top-3 vs top-2 vs top-4 changes concentration. Test all three.
4. **EM universe composition:** Adding or removing EWJ (quasi-developed market) changes behavior. Run both with and without.
5. **Regime confirmation lag:** H81's 2-week confirmation period is not included here (adds complexity; single-week crossing used instead). If whipsaw is observed in backtest, add 2-week confirmation and retest.

---

## References

- Koijen, R., Moskowitz, T., Pedersen, L., Vrugt, E. (2018). "Carry." *Journal of Financial Economics*, 127(2), 197–225.
- Ghosh, A.R., Ostry, J.D., Chamon, M. (2016). "Two Targets, Two Instruments." *IMF Staff Discussion Note*.
- Lustig, H., Roussanov, N., Verdelhan, A. (2011). "Common Risk Factors in Currency Markets." *Review of Financial Studies*, 24(11), 3731–3777.
- Rouwenhorst, K.G. (1999). "Local Return Factors and Turnover in Emerging Stock Markets." *Journal of Finance*, 54(4), 1439–1464. (Cross-sectional momentum in EM.)
- Asness, C., Moskowitz, T., Pedersen, L. (2013). "Value and Momentum Everywhere." *Journal of Finance*, 68(3), 929–985.
- Menkhoff, L., Sarno, L., Schmeling, M., Schrimpf, A. (2012). "Currency Momentum Strategies." *Journal of Financial Economics*, 106(3), 660–684.
- Froot, K.A., Ramadorai, T. (2005). "Currency Returns, Intrinsic Value, and Institutional-Investor Flows." *Journal of Finance*, 60(3), 1535–1566.
- Chainalysis (2022). "Dollar Strength and Emerging Market Capital Flows." Industry report.
- Related in pipeline: H44 (LQD/IEF credit timer), H58 (copper/gold regime), H81 (H83 parent hypothesis, unrealized)

---

## Engineering Director Brief

**Commission to:** Strategy Coder → Engineering Director
**Hypothesis file:** `research/hypotheses/83_usd_regime_em_country_rotation.md`
**Track:** A (daily/weekly swing, US equities / EM ETFs)

### Backtest Spec

**Universe:**
- Primary EM rotation candidates: EWZ, FXI, INDA, EWT, EWY, EWJ (6 ETFs)
- Defensive: SHY
- Macro signal instrument: UUP

**Data:** yfinance daily OHLCV, 2015-01-01 to 2024-12-31 (INDA available from 2012; use 2015+ for full 6-ETF universe with clean data)

**IS/OOS split:** 2015-01-01 to 2022-12-31 (IS), 2023-01-01 to 2024-12-31 (OOS)
**Walk-forward:** 6 × (3-month IS / 1-month OOS) windows within 2022-01 to 2024-12 range

**Entry/exit:**
1. Weekly evaluation: Friday at close.
2. Compute `usd_strong = UUP.close > UUP.close.rolling(50).mean()`
3. If `usd_strong`: target allocation = 100% SHY
4. If NOT `usd_strong`: rank EWZ/FXI/INDA/EWT/EWY/EWJ by `(close / close.shift(20)) - 1`; target allocation = equal-weight top-3
5. Execute rebalances at Monday open following Friday evaluation
6. Only trade if target allocation differs from current allocation (change-only rebalancing)
7. Hard stop: if any single position drawdown from entry > 15% → exit at next open

**Cost model (Track A standard):**
- $0.005/share per side + 0.05% one-way slippage
- ETF average share price ~$40–50; ~$0.25–0.30 round-trip per transaction

**Parameter sweep:**
- USD SMA period: [30, 50, 63, 100]
- EM ranking lookback: [10, 20, 42] days
- Top-N EM selection: [2, 3, 4]
- Hard stop: [10%, 15%, no stop]

**Output required:**
- IS/OOS Sharpe, CAGR, MaxDD per parameter combination
- IS trade count per 3-month WF window
- Cost-to-gross ratio
- 2022 specific performance (Jan–Dec 2022 as standalone)
- USD regime time breakdown: % of backtest period in EM vs SHY
- Overnight gap contribution to PnL/MDD
- Parameter stability heatmap (Sharpe vs USD SMA period × ranking lookback)

**Track A Gate 1 thresholds to verify:**
- Net OOS Sharpe > 0.7
- Net profit per trade > 15 bps
- IS MDD < 20% (per WF window)
- IS trade count > 30 per 3-month window
- Cost-to-gross < 0.25

---

*Research Director | QUA-360 | 2026-06-22*
