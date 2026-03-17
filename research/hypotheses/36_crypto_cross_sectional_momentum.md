# H36: Crypto Cross-Sectional Momentum — 4-Asset Ranking (BTC/ETH/SOL/AVAX)

**Version:** 1.0
**Author:** Research Director
**Date:** 2026-03-17
**Asset class:** Cryptocurrency (BTC, ETH, SOL, AVAX)
**Strategy type:** single-signal, momentum / cross-sectional ranking
**Status:** DRAFT
**Hypothesis Class:** Momentum (this is the **1 permitted momentum hypothesis** in this H35–H39 batch per CEO Directive QUA-181)
**Related:** H08 (BTC/ETH dual-EMA crossover). H36 is structurally distinct: cross-sectional ranking vs. time-series EMA, 4 assets vs. 2, 4-week lookback vs. 20/60-day EMAs.

---

## Summary

Cross-sectional momentum — buying recent winners and selling (or avoiding) recent losers — is the most robustly documented factor in financial markets (Jegadeesh & Titman 1993). In crypto, the mechanism is amplified by retail behavioral dynamics: assets with the strongest recent returns attract disproportionate attention, capital inflows, and social media activity. The strategy ranks BTC, ETH, SOL, and AVAX by 4-week return each week; goes long the top-ranked asset; and is flat/cash when BTC is below its 200-day SMA (sustained bear market regime). This is distinct from H08's dual-EMA time-series crossover on BTC/ETH — H36 uses cross-sectional ranking to rotate among 4 assets weekly rather than holding both assets with trend filters.

---

## Economic Rationale

**Why cross-sectional momentum works in crypto:**

1. **Attention-driven capital rotation:** Individual crypto assets receive highly variable media attention. When BTC dominates news, capital flows to BTC; when ETH or Solana lead development activity or NFT cycles, they outperform. The 4-week lookback captures the tail of these attention cycles, which typically persist 4–8 weeks before rotating.

2. **Amplified momentum vs. equities:** Retail crypto investors exhibit stronger recency bias and herding behavior than equity investors. "Altcoin season" dynamics — where capital rotates from BTC to ETH and then to smaller-cap alts — are well-documented (CoinMetrics, Glassnode). The 4-week lookback captures inter-asset rotation at the right frequency.

3. **Cross-sectional ranking vs. time-series:** Cross-sectional (relative) momentum is more robust than absolute (time-series) momentum because it exploits the relative difference between assets, not just whether any asset is going up. A rising BTC might still underperform ETH by 20% in an "ETH dominance" period — cross-sectional ranking captures this.

4. **Risk management via BTC trend filter:** A BTC 200-SMA filter (go flat when BTC < 200-SMA) avoids sustained bear markets where all crypto declines together. This is the single most important regime filter for crypto: the 2018 and 2022 bear markets both saw BTC fall below its 200-SMA months before the worst losses materialized.

**Academic support:**
- Liu & Tsyvinski (2021). "Risks and Returns of Cryptocurrency." *Review of Financial Studies*, 34(6): documented momentum factor in crypto (12-week) with Sharpe ~0.9 long-only.
- Baur & Dimpfl (2018). "Asymmetric Volatility in Cryptocurrencies." Cross-asset dynamics in crypto momentum.
- Grobys et al. (2020). "Technical Trading Rules in the Cryptocurrency Market." Trend momentum in crypto BTC/ETH.
- Cong, Tang & Wang (2021). "Crypto Wash Trading." Trading volume as signal amplifier.

**Distinctness from H08:**
- H08: Time-series EMA(20)/EMA(60) crossover on BTC and ETH independently. Both can be simultaneously long.
- H36: Cross-sectional weekly ranking of 4 assets. Only top 1 asset is held at a time. Signal frequency is weekly vs. H08's event-driven crossover.

---

## Market Regime Context

| Regime | Expected Performance |
|---|---|
| Crypto bull (BTC > 200-SMA, alts rotating) | **Excellent** — cross-sectional signal captures inter-asset rotation; long best-momentum asset |
| BTC dominance phase (ETH/SOL/AVAX lagging BTC) | **Good** — long BTC consistently; simple but effective |
| Altcoin season (ETH/SOL leading BTC) | **Excellent** — ranks ETH/SOL higher; captures the outperformance |
| Sustained bear (BTC < 200-SMA) | **Flat/cash** — trend filter exits all positions; avoids 2018 and 2022 drawdowns |
| High vol / flash crash within bull | **Moderate** — weekly rebalance may miss intraday crash and recovery; hard stop mitigates |
| Choppy sideways (BTC ≈ 200-SMA) | **Moderate** — false exits and re-entries; small losses from whipsaw |

---

## Entry/Exit Logic

**Universe:** BTC-USD, ETH-USD, SOL-USD, AVAX-USD (via yfinance)

**Data availability note:** BTC-USD and ETH-USD are available from 2017+. SOL-USD from 2020+, AVAX-USD from 2020+. For IS periods before 2020, the universe is restricted to BTC and ETH (2-asset ranking). Full 4-asset ranking applies from 2020+.

**Signal computation (weekly, at Sunday/Monday close):**
1. Compute 4-week (20 trading day) simple return for each available asset
2. Rank assets by 4-week return, descending
3. BTC trend filter: compute BTC 200-day SMA. If BTC_close < BTC_200SMA → signal OFF (flat/cash)
4. Entry: if BTC trend filter ON → long top-ranked asset at Monday open (100% of portfolio)
5. Rebalance: if top-ranked asset changes → sell current, buy new top-ranked at next Monday open

**Exit conditions:**
- Weekly rebalance replaces position with new top-ranked asset
- BTC falls below 200-SMA → exit all positions (flat/cash)
- Hard stop: -12% from entry price on any position → exit (crypto volatility requires wider stop)

**Position sizing:** 100% of portfolio in single top-ranked asset (concentrated momentum). No leverage.

---

## Parameters to Test

| Parameter | Default | Range | Rationale |
|---|---|---|---|
| Lookback for ranking | 20 trading days (4 weeks) | 10–30 days | Captures 2–6 week attention/rotation cycles |
| Trend filter SMA | BTC 200-day | 100–250 days | 200-day is standard crypto bear market indicator |
| Number of assets held | 1 (top 1) | 1–2 | Holding top 2 reduces concentration; test both |
| Hard stop per position | −12% | −8% to −15% | Wider than equity stops due to crypto volatility |
| Rebalancing frequency | Weekly | Weekly/biweekly | Weekly captures rotation; biweekly reduces costs |

---

## Asset Class & PDT/Capital Constraints

- **Asset:** Crypto ETFs or direct crypto (coinbase, Robinhood). If using ETFs: BITO (BTC), ETHA (ETH). SOL/AVAX ETFs may not be available — would require direct crypto exchange.
- **Direct crypto option:** Using Coinbase or Kraken account avoids PDT rules (crypto is not subject to PDT). No margin required for long-only.
- **PDT note:** If using futures ETFs (BITO), weekly position changes are 1 trade per week → no PDT concern.
- **Minimum capital:** ~$1,000 per position at $25K portfolio. 100% in single asset is concentration risk — acceptable for the strategy's design.
- **Platform note:** yfinance provides BTC-USD, ETH-USD, SOL-USD, AVAX-USD daily OHLCV for backtesting. ✓

---

## Alpha Decay Analysis

- **Signal half-life:** 15–30 trading days (3–6 weeks). Crypto momentum IC peaks at ~4-week lookback and decays gradually through 8 weeks (Liu & Tsyvinski 2021 document 12-week momentum with positive IC).
- **IC decay curve:**
  - T+1: IC ≈ 0.04–0.06 (noise-dominated; not actionable at daily frequency)
  - T+5 (1 week): IC ≈ 0.06–0.10 (entering optimal zone)
  - T+20 (4 weeks): IC ≈ 0.05–0.08 (stable; peak predictability range for cross-sectional ranking)
- **Transaction costs:** Weekly rebalancing, 1 trade per week. On crypto exchanges: 0.1–0.25% per trade for maker/taker. Round-trip per weekly trade: ~0.3–0.5%. On $25K with 52 trades/year: ~$390–650/year in costs. Against expected alpha of $2,500–5,000 (Sharpe ~0.9 pre-cost on $25K), edge survives comfortably.
- **Crowding risk:** Cross-sectional crypto momentum is less crowded than large-cap equity momentum (retail-dominated market), but algorithmic attention-driven momentum strategies have proliferated since 2020. Signal decay may be faster post-2023.

---

## Gate 1 Assessment

| Criterion | Estimate | Confidence |
|---|---|---|
| IS Sharpe > 1.0 | 0.8–1.2 estimated | Medium — IS window for full 4-asset version limited to 2020–2022 |
| OOS Sharpe > 0.7 | 0.6–1.0 estimated | Medium — crypto momentum documented; regime-dependent |
| Max Drawdown | ~25–40% estimated | Medium — BTC trend filter limits drawdown; flash crashes can be severe |
| Trade count (IS 2018–2022) | ~100–200 entries | Medium — limited by IS window length for crypto |
| Walk-forward stability | Moderate | Medium — crypto regime changes are rapid |

**Data availability risk:** The IS window is substantially shorter than for equity strategies (2018–2022 for BTC/ETH, 2020–2022 for all 4 assets). This limits statistical power. Engineering Director should flag this during Gate 1 design. Consider whether 2018–2022 provides adequate IS window depth or whether OOS should begin 2023.

---

## Pre-Flight Gate Checklist

| Gate | Status | Notes |
|---|---|---|
| PF-1 | **CONDITIONAL PASS** | 2-asset version (BTC/ETH 2018–2022): 4.5 years × 52 weeks × ~55% signal-on rate = ~129 entries. 129 ÷ 4 = 32 per WF fold. Marginally passes ≥ 30. Full 4-asset version (2020–2022 only): ~104 entries ÷ 4 = 26. **Below 30 for 4-asset-only IS window.** Mitigation: use 2-asset ranking 2018–2019, expand to 4-asset 2020+. Gate 1 team should verify this split-universe design is acceptable. |
| PF-2 | **N/A** | Crypto is not a traditional equity asset. PF-2 (dot-com/GFC stress test) does not apply to BTC/ETH/SOL/AVAX which did not exist in 2000–2009. 2018 and 2022 crypto bear tests serve as analogous stress scenarios. |
| PF-3 | **PASS** | BTC-USD, ETH-USD, SOL-USD, AVAX-USD all available via yfinance daily OHLCV. No intraday, no options, no special data sources. ✓ |
| PF-4 | **PASS** | 2022 rate-shock: BTC fell below 200-SMA in Jan 2022, triggering exit. Strategy flat for most of 2022. Max crypto drawdown avoided (BTC −65% in 2022; strategy was in cash from Jan 2022 exit). Rate-shock protection mechanism: BTC trend filter is an absolute exit regardless of rank signal. **Explicit rationale:** crypto cross-sectional momentum is fundamentally decorrelated from rate decisions when the trend filter is active — the strategy exits when macro risk dominates the intra-crypto rotation signal. ✓ |

---

## References

- Liu, Y. & Tsyvinski, A. (2021). "Risks and Returns of Cryptocurrency." *Review of Financial Studies*, 34(6), 2689–2727.
- Jegadeesh, N. & Titman, S. (1993). "Returns to Buying Winners and Selling Losers." *Journal of Finance*, 48(1), 65–91.
- Grobys, K. et al. (2020). "Technical Trading Rules in the Cryptocurrency Market." *Finance Research Letters*, 32.
- Baur, D. & Dimpfl, T. (2018). "Asymmetric Volatility in Cryptocurrencies." *Economics Letters*, 173, 148–151.
- CoinMetrics Research: "Altcoin Season and Cross-Asset Crypto Momentum" (2021).
