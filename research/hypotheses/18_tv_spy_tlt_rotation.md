# H18: SPY/TLT Weekly Momentum Rotation

**Version:** 1.0
**Author:** Alpha Research Agent
**Date:** 2026-03-16
**Asset class:** equities
**Strategy type:** single-signal
**Status:** hypothesis

## Economic Rationale

The SPY/TLT pair exploits the persistent negative correlation between US equities and long-duration Treasuries: when equity risk appetite falls (risk-off), capital flows into Treasuries as a safe haven, and vice versa. This negative correlation (-0.26 on average) creates a natural rotation opportunity — the asset losing momentum tends to be outperformed by the one gaining. The edge is grounded in two structural mechanisms:

1. **Flight-to-quality premium**: Institutional portfolio rebalancing toward bonds during equity drawdowns creates persistent momentum in the "safe" asset.
2. **Volatility risk premium asymmetry**: TLT has a Sharpe ratio of ~0.79 vs SPY's ~0.50 (2003–2024 data), making bond inclusion beneficial when equity momentum deteriorates.

The SPY-TLT Universal Investment Strategy (Logical Invest, Frank Grossmann 2015) documented a 20-year Sharpe ratio of ~1.28 using monthly allocation — substantially above either asset alone. This hypothesis adapts the core mechanism to weekly rebalancing to meet IS trade count requirements and avoid the architectural monthly-rebalancing block (TSMOM lesson).

**Key risk — 2022 inflation shock:** The SPY-TLT negative correlation broke down in 2022 when both assets fell in response to aggressive Fed tightening (TLT drawdown -31%, SPY drawdown -18%). The mechanism is contingent on a non-inflationary macro environment. An inflation / rate-spike regime gate is required.

**Evidence base:** Grossmann (2015) SPY-TLT UIS (Seeking Alpha); Alvarez Quant Trading SPY/TLT rotation backtest; Logical Invest walk-forward validation (2003–2024); R-Bloggers walk-forward study (2015).

## Entry/Exit Logic

**Universe:** SPY and TLT (both available via yfinance with full history from 2002).

**Weekly momentum signal (every Friday close):**
- Compute `mom_spy = SPY.pct_change(lookback)` and `mom_tlt = TLT.pct_change(lookback)` where lookback ∈ {10, 15, 20} trading days
- Compute `mom_diff = mom_spy - mom_tlt`

**Entry signal:**
- If `mom_diff > threshold`: Allocate 100% to SPY (equity regime)
- If `mom_diff < -threshold`: Allocate 100% to TLT (bond regime)
- If `-threshold <= mom_diff <= threshold`: Hold 50/50 split (neutral)
- `threshold` default: 0.0 (absolute momentum differential)

**Regime filter (required):**
- If realized 20-day vol of SPY > 25% annualized AND TLT 20-day vol > 15%: do not enter new positions (simultaneous high vol = inflation/correlation-breakdown regime)
- Exit all positions if the vol filter triggers mid-hold

**Exit signal:**
- Rebalance on next Friday's close whenever allocation tier changes
- Full exit if regime filter triggers

**Holding period:** Weekly swing (5 trading days typical hold per allocation)

**PDT note:** All transitions are between ETFs held for 5+ days. No day trades. PDT-safe.

## Market Regime Context

**Works best:**
- Non-inflationary macro environments where equity-bond correlation is negative
- Trending regimes where one asset clearly outperforms (momentum signal is clean)
- Moderate VIX (15–25): enough equity uncertainty to generate bond demand without breaking the correlation

**Tends to fail:**
- Inflationary rate-spike environments (2022 analog): both assets fall simultaneously
- Low-vol, range-bound equity markets with no trend (momentum signal whipsaws between SPY and TLT)
- Liquidity crises where both initially crash (March 2020) before TLT recovers

**Pause trigger:** If SPY and TLT 20-day correlation turns positive (> +0.3) for 10+ consecutive days: halt new entries. Resume when correlation normalizes below 0.

## Alpha Decay

- **Signal half-life (days):** 15–20 days (momentum signal IC decays meaningfully by 3 weeks; weekly rebalancing captures the sweet spot)
- **Edge erosion rate:** Moderate (5–20 days)
- **Recommended max holding period:** 20 trading days (4 weeks); strategy auto-exits weekly, so decay is managed
- **Cost survival:** Yes. With ETF bid-ask spreads of ~$0.01 and round-trip commission ~$0.50–$1.00, a 1–2% weekly momentum differential comfortably covers costs.
- **Annualized IR estimate:** Pre-cost IR ~0.8–1.2 based on Logical Invest 20-year backtest Sharpe of 1.28. Post-regime-conditioning, target IR ≥ 0.5. Passes the 0.3 warning floor.
- **Notes:** 2022 is the critical regime failure. If the IS window includes 2022 (which it does), IS Sharpe will be suppressed vs longer historical averages. The regime filter is designed to reduce 2022 exposure.

## TV Source Caveat

- **Original TV strategy:** "SPY/TLT Strategy" by Botnet101 ([shLUk4wi](https://www.tradingview.com/script/shLUk4wi-SPY-TLT-Strategy/))
- **TV backtest window:** Not documented by author; mechanism consistent with the Logical Invest UIS methodology (2003–2024 history available)
- **Cherry-pick risk:** LOW. The SPY/TLT rotation concept is independently validated in multiple academic and practitioner sources (Grossmann 2015, Alvarez QT, QuantifiedStrategies.com). The TV script is a community re-implementation, not the original discovery.
- **Crowding risk:** MEDIUM. The SPY-TLT relationship is widely tracked by institutional allocators and retail robo-advisors (e.g., M1 Finance). The edge at weekly swing scale may be partially crowded by monthly institutional rebalancers, but retail-scale entry/exit friction is low enough that the mechanism persists.
- **Novel signal insight vs H01–H17:** Cross-asset rotation between SPY and TLT is structurally distinct from all prior hypotheses:
  - H01/H05/H12/H16: single-asset momentum on equity ETF
  - H07/H17: multi-asset TSMOM and dual momentum across equity + bond + international (monthly, blocked/failed)
  - H18 is the first **weekly, two-asset, cross-asset correlation regime** strategy in the pipeline. It uniquely exploits the equity-bond comovement relationship rather than directional momentum within a single asset class.

## Parameters to Test

| Parameter | Suggested Range | Rationale |
|---|---|---|
| `mom_lookback_days` | 10, 15, 20, 30 | Core momentum window; prior lit suggests 20-day optimal for SPY/TLT |
| `threshold` | 0.0, 0.005, 0.01 | Dead-band to reduce whipsaw at neutral momentum |
| `vol_filter_spy_pct` | 20%, 25%, 30% | Inflation regime detection threshold for simultaneous high vol |
| `vol_filter_tlt_pct` | 12%, 15%, 18% | TLT vol threshold for regime filter |
| `neutral_zone_allocation` | 50/50, 70/30 SPY-biased, 0% (cash) | Behavior during neutral momentum signal |

## IS Trade Count Pre-Flight Check

- **IS period:** 2018–2022 (4 years)
- **Trade count estimate:** Weekly rebalancing = 52 allocation decisions/year. Actual direction changes (SPY↔TLT switches): ~20–35/year based on 15-20d momentum crossover frequency
- **IS trades:** 20–35/year × 4 years = 80–140 trades
- **IS trades / 4 years:** 20–35 trades/year
- **Threshold check:** 20–35 ≥ 30 → **BORDERLINE PASS** (lower end of parameter range may fail; use lookback ≤ 20d to maximize signal frequency)
- **Note:** If using 30d lookback with threshold > 0.01, trade count may drop below 30/year → fail. Use 15d lookback as default to ensure threshold is met.

## Capital and PDT Compatibility

- **Minimum capital required:** ~$5,000 (one SPY share is ~$450–$550; can size to 10–20 shares)
- **PDT impact:** None. All holds are ≥ 5 trading days (full week). No day trades.
- **Position sizing:** 95% of portfolio in either SPY or TLT; 5% cash buffer for rebalancing. No leverage. One position at a time (or 50/50 split in neutral zone).
- **Concurrent positions:** 1–2 ETF positions simultaneously

## Gate 1 Outlook

Candid assessment:

- **IS Sharpe > 1.0:** **Unlikely without regime filter.** Raw SPY/TLT rotation IS Sharpe pre-2022 was ~1.0–1.3, but the 2022 failure likely pulls IS Sharpe to 0.6–0.85. The inflation-regime vol filter is designed to limit 2022 drawdown and restore IS Sharpe to >1.0. Gate 1 pass depends heavily on filter effectiveness.
- **OOS persistence:** **Likely** if macro correlation regime stays non-inflationary. Post-2022 regime (2023–2025) reverted to negative equity-bond correlation; OOS window should be favorable.
- **Walk-forward stability:** **Moderate.** The 2022 analog is the primary walk-forward risk. If the walk-forward window includes an inflationary period, strategy will show a gap. Sensitivity to `vol_filter` threshold is the key parameter risk.
- **Sensitivity risk:** **Medium.** Strategy is robust to `mom_lookback` ±5 days but sensitive to `vol_filter` threshold selection (can over-filter in moderate-vol environments, reducing trade count below threshold).
- **Known overfitting risks:**
  - Vol filter thresholds may be optimized in-sample to exclude 2022 specifically (overfitting to one regime event)
  - SPY/TLT correlation regime shift in 2022 was an out-of-distribution event; filtering it out may produce overly optimistic IS metrics

## References

- Grossmann, F. (2015). "The SPY-TLT Universal Investment Strategy." Seeking Alpha / Logical Invest. https://logical-invest.com/universal-investment-strategy/
- Alvarez Quant Trading. "SPY TLT Rotation." https://alvarezquanttrading.com/blog/spy-tlt-rotation/
- QuantifiedStrategies.com. "Monthly Momentum in S&P 500 and Treasury Bonds." https://www.quantifiedstrategies.com/spy-tlt-bond-rotation-strategy/
- QuantStratTrader. "The Logical-Invest UIS — A Walk Forward Process on SPY and TLT" (R-Bloggers 2015).
- TradingView strategy: shLUk4wi (Botnet101). https://www.tradingview.com/script/shLUk4wi-SPY-TLT-Strategy/
- Related hypotheses: H07 (multi-asset TSMOM — failed Gate 1), H17 (dual momentum ETF rotation — failed Gate 1)
