# H76: Multi-ETF RSI-2 Daily Mean Reversion Portfolio

**Status:** RETIRED — Gate 1 FAIL (IS Sharpe 0.5404). Family iteration 1/2. See H76b for revision. Family retired after H76b also failed. See QUA-329.
**Class:** Pattern-based / Mean Reversion
**Track:** A — Daily/Swing
**Author:** Research Director
**Date:** 2026-06-17
**Rationale for creation:** QUA-322 — all QUA-283 candidates failed on monthly rotation trade count floor. This hypothesis addresses the structural failure by spreading daily RSI(2) signals across 12 ETFs, generating 150-300 IS trades/year vs 26-64 for monthly rotation strategies.

---

## Summary

A mean-reversion portfolio strategy that monitors RSI(2) on 12 liquid ETFs daily. When any ETF's RSI(2) drops below 5, it is bought at the next open and held until RSI(2) recovers above 65 or for a maximum of 5 trading days. A maximum of 4 concurrent positions are held simultaneously (equal-weighted at 25% each). A SPY 200-day SMA regime filter blocks all new entries when the broad market is in a downtrend.

This strategy extends the single-ETF RSI(2) concept tested in H34/H34b (SPY only, failed — too few trades) and H70b (IWM only, failed — too few trades) to a diversified multi-ETF universe, directly addressing the Gate 1 IS trade count failure that eliminated all QUA-283 strategies.

---

## Economic Rationale

Short-term mean reversion in liquid ETFs is one of the most robust and well-documented equity anomalies. When RSI(2) falls below 5, the ETF has experienced extreme short-term selling pressure — typically from institutional tax-loss selling, forced margin calls, or panic exits driven by short-term liquidity needs rather than fundamental value change.

This creates temporary price dislocations that revert as the imbalance clears, typically within 2–5 trading days. The edge is structural: ETFs represent diversified baskets, so single-stock blowup risk is absent; they are extremely liquid so fill quality is high; and the daily RSI(2) < 5 threshold is severe enough to filter out routine pullbacks.

Empirical evidence: Connors & Alvarez ("Short-Term Trading Strategies That Work," 2008) document RSI(2) < 5 strategies producing win rates above 70% across major equity indices. The multi-ETF extension captures more diverse oversold episodes (different sectors, asset classes) without increasing correlation to single-factor risk.

The key structural insight distinguishing H76 from H34/H70b: a single ETF generates only 8–15 RSI(2) < 5 events per year, yielding 40–75 IS trades over 5 years — below the 100-trade floor. Twelve ETFs cycling asynchronously through oversold conditions generate 150–300 events/year, comfortably above the 100-trade floor and providing statistical power for permutation testing.

---

## Market Regime Context

**Works in:**
- Moderate pullbacks within uptrends (2003–2007, 2009–2019, 2020–2021)
- High-volatility consolidation periods: VIX 20–35 generates more RSI(2) < 5 readings and stronger rebounds
- Sector rotation cycles: when one sector corrects while others hold, oversold signals fire independently across universe

**Fails in:**
- Sustained bear markets where oversold readings cascade lower without recovery (2001–2002, 2008–2009 without regime filter)
- Correlated crashes where all ETFs drop simultaneously — regime filter blocks new entries

**2022 Rate Shock Survival:**
SPY broke below its 200-DMA on 2022-01-24 and remained below through most of 2022. The regime filter blocks all new entries from that date forward. Capital remains in SHY equivalent. The strategy stands aside for the entire 2022 bear leg. Residual risk: positions entered before the filter triggers in January 2022 may experience 5% stop-loss exits. This is the explicit mechanism for 2022 survival — not coincidental.

---

## Entry/Exit Logic

**Universe (12 ETFs):**
SPY, QQQ, IWM, XLK, XLV, XLE, XLF, XLY, XLP, XLU, XLI, XLB

**Regime filter:**
- Calculate SPY 200-day simple moving average daily
- If SPY closing price < SPY 200-DMA: no new entries (all open positions continue to their exit signals)

**Entry:**
- Calculate RSI(2) for each universe ETF on daily closing prices
- If RSI(2) < 5.0: buy at next open (T+1 open)
- If multiple signals on same day: rank by RSI(2) ascending (most oversold first); fill up to 4 concurrent positions
- If already at 4 positions: queue signal but do not fill until a position exits

**Position sizing:**
- Equal weight: 25% of portfolio per position
- Max 4 concurrent positions
- Cash remainder (if fewer than 4 positions) held as SHY equivalent

**Exit (first condition triggers):**
1. RSI(2) of held ETF closes above 65 → sell at next open
2. 5 calendar day hard stop from entry date → sell at next open
3. 5% stop-loss from entry price (position-level, intraday trigger)

**Cost model:**
- $0.005/share per side + 0.05% slippage one-way + Almgren-Chriss impact
- All liquid ETFs: SPY/QQQ/IWM ADV >$20B daily, sector ETFs >$500M daily — market impact negligible

---

## Asset Class & PDT/Capital Constraints

- US equities (ETFs), daily OHLCV bars
- All data available via yfinance ✓
- **PDT compliance:** Hold 1–5 days = swing positions. Not day trades. PDT rule does not apply to multi-day holds. ✓
- **$25K account fit:** 25% per position = $6,250 at $25K. 4 positions × $6,250 = $25,000 fully deployed. Positions are ETFs with fractional share capability via Alpaca. ✓
- **Overnight/weekend risk:** Strategy holds overnight by design. Weekend gaps are a documented risk. Earnings gap risk mitigated by using ETFs (diversified baskets; single earnings event = 1–5% weight of ETF basket). ✓

**Track A swing guards (mandatory):**
- Overnight gap contribution: expected <0.5% per position given ETF diversification
- Weekend risk: max 2-day gap; ETF baskets reduce idiosyncratic jump risk
- Earnings gap policy: ETFs held through earnings; max exposure per earnings-holding ETF ≤ 25% (enforced by position limit)
- Gap MDD attribution: estimated <30% of total MDD from overnight/weekend gaps

---

## Gate 1 Assessment

| Metric | Expected | Threshold | Assessment |
|---|---|---|---|
| IS Trade Count | 150–300/year × 5 years = 750–1500 IS trades | ≥ 100 | ✓ STRONG PASS |
| IS Sharpe | 1.0–1.5 (RSI mean reversion in regime-filtered setting) | > 1.0 | ✓ Credible |
| OOS Sharpe | 0.7–1.0 (regime filter limits 2022 exposure) | > 0.70 | ✓ Credible |
| IS MDD | ~10–18% (regime filter + stop-loss) | < 20% | ✓ Credible |
| Permutation p | < 0.05 (750+ trades provides strong statistical power) | < 0.05 | ✓ Credible |
| WF stability | RSI(2) is robust across parameter ranges | ≥ 3/4 windows | ✓ Expected |
| Cost-to-profit | ~15–25% (avg hold 3 days, 80–150 bps gross profit) | < 25% | ✓ Credible |

---

## Recommended Parameter Ranges (for sweep)

| Parameter | Primary | Sweep Range |
|---|---|---|
| RSI period | 2 | [2, 3, 4] |
| RSI entry threshold | 5 | [3, 5, 7] |
| RSI exit threshold | 65 | [60, 65, 70, 75] |
| Max hold days | 5 | [3, 5, 7] |
| Regime DMA | 200 | [150, 200, 250] |
| Stop-loss % | 5% | [4%, 5%, 7%] |
| Max concurrent positions | 4 | [2, 3, 4, 5] |

---

## Alpha Decay Analysis

**Signal half-life:** 2–5 trading days. RSI(2) signals are explicitly short-term; predictive power decays rapidly.

**IC decay curve:**
- T+1: IC ≈ 0.08–0.12 (primary signal window)
- T+3: IC ≈ 0.04–0.06 (still positive, exit window)
- T+5: IC ≈ 0.01–0.02 (marginal)
- T+10: IC ≈ 0.00 (fully decayed)

Signal half-life >> 1 day; transaction cost viability is confirmed.

**Transaction cost viability:**
- Avg hold 3 days → round-trip cost spread over 3-day PnL
- Estimated round-trip: ~20–25 bps (equity ETFs, $0.005/share × 2 sides + slippage)
- Expected gross profit per trade: 80–150 bps (RSI<5 recovery magnitude)
- Cost-to-profit ratio: ~15–25% — within Track A ceiling of 25%
- Half-life > 1 day + cost ratio < 25%: **Transaction cost viability CONFIRMED** ✓

---

## Pre-Flight Gate Checklist

- [x] **PF-1 PASS** — Estimated IS trade count: 200/year × 5 years = 1000 total. 1000 ÷ 4 = 250 ≥ 30 ✓
- [x] **PF-2 PASS** — Long-only equity strategy: SPY 200-DMA filter triggers in dot-com (SPY below 200-DMA ~2000-10 to 2003-03) and GFC (2007-11 to 2009-07). Strategy stands aside in cash for both periods. Proxy estimate: during 200-DMA breach periods, strategy is mostly cash; estimated full-period MDD < 25% using SPY proxy. Dot-com estimated MDD: < 25%. GFC estimated MDD: < 20% ✓
- [x] **PF-3 PASS** — All data via yfinance daily OHLCV: SPY, QQQ, IWM, XLK, XLV, XLE, XLF, XLY, XLP, XLU, XLI, XLB — all confirmed available via yfinance ✓
- [x] **PF-4 PASS** — 2022 rate-shock rationale: SPY broke below 200-DMA on 2022-01-24. The regime filter is a hard no-entry gate. Capital moves to cash (SHY equivalent) for the entire 2022 downtrend. Strategy participates in the 2023 recovery (SPY recrossed 200-DMA ~2023-02). The mechanism is explicit and structural: the 200-DMA regime filter is the primary capital preservation tool during rate-shock environments ✓
