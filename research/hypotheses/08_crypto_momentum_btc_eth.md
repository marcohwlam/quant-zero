# Hypothesis 08: Crypto Momentum — BTC/ETH EMA Crossover

**Status:** READY
**Category:** Trend Following / Crypto
**Source:** Cong, Tang & Wang (2021) "Crypto Wash Trading"; Liu & Tsyvinski (2021) "Risks and Returns of Cryptocurrency" — Review of Financial Studies
**Date:** 2026-03-16

---

## Summary

BTC and ETH exhibit strong trend-following properties due to retail behavioral momentum, slow institutional adoption cycles, and sentiment-driven supply/demand imbalances. This strategy applies a dual-EMA crossover (20-day fast / 60-day slow) independently on BTC and ETH to generate long or flat signals. When the fast EMA crosses above the slow EMA, enter long. When it crosses below, exit and go flat (long-only; no shorting). Position sizing splits $25K capital between the two assets with a hard 15% trailing stop per asset. Structurally distinct from all existing hypotheses: different asset class (crypto), different signal mechanism (EMA crossover vs. RSI mean-reversion), and different economic driver (behavioral FOMO and institutional adoption cycle vs. equity market-making).

---

## Economic Rationale

**Why this edge should exist in crypto:**

1. **Behavioral momentum and FOMO:** Crypto markets are dominated by retail participants with high behavioral bias. Rising BTC prices attract new buyers through FOMO (fear of missing out) — each new buyer pushes prices higher, reinforcing the trend. This feedback loop is stronger and more persistent in crypto than equities due to the higher retail concentration and 24/7 news cycle.

2. **Slow institutional adoption cycles:** During 2020–2021, institutional capital slowly moved into crypto (MicroStrategy, Tesla, Grayscale). This was a multi-month flow — institutional adoption created sustained buying pressure that formed a persistent trend, not a one-day event.

3. **Market microstructure:** Crypto lacks circuit breakers, overnight gaps, and specialist market-makers. Trends can persist without the intervention mechanisms that dampen equity trends. The 24/7 market structure allows trends to compound without weekly resets.

4. **Limited short-selling capacity:** Shorting crypto at retail scale requires margin accounts with elevated borrowing costs and liquidation risk. This asymmetry means short-sellers are underrepresented, allowing uptrends to overshoot fair value.

5. **Cross-asset contagion:** BTC and ETH are highly correlated (0.8+) but not identical. Running signals independently on each asset captures when they diverge (ETH sometimes leads or lags BTC) while maintaining diversification within the crypto asset class.

**Why the IS window (2018–2022) contains both signal types:**
- **2018 crypto winter:** EMA(20) < EMA(60) persistently from January 2018 through December 2018 — strategy would be flat (cash), avoiding the -80% BTC drawdown
- **2019–2020 accumulation:** Mixed signals; strategy would enter/exit with modest gains
- **2020–2021 bull:** Persistent uptrend from September 2020 to November 2021 — both BTC (+1,200%) and ETH (+4,000%) in strong EMA uptrend configurations
- **2022 crypto crash:** EMA crossover down in April 2022 — strategy exits before the final -60% leg from $60K to $16K

**The IS window stress-tests both sides of the strategy:** long capture (2020–2021 bull) and capital preservation in bear (2018, 2022). This is a more demanding test than equities for the same period.

---

## Market Regime Context

| Regime | Expected Performance |
|--------|---------------------|
| Crypto bull trend | Excellent — core regime; sustained EMA alignment |
| Crypto bear (sustained) | Good — flat/cash; avoids major drawdowns |
| Choppy / ranging | Poor — EMA whipsaw; false crossings generate small losses |
| High volatility without trend | Challenging — multiple false signals; use wider EMA gap |
| ETH/BTC divergence | Moderate — independent signals reduce correlation, improve diversification |
| 2020-style macro crypto adoption wave | Exceptional — multi-month institutional trend |

**When this strategy breaks down:**
- **Flash crashes and recoveries** (e.g., May 2021 BTC crash from $60K to $30K and recovery): EMA signals may lag, causing late exits and re-entries at higher prices
- **Ranging markets** (2019, mid-2023): price oscillates above/below both EMAs — whipsaw losses accumulate
- **Regulatory shocks** (exchange hacks, OFAC sanctions): sudden price moves that aren't preceded by a trend; stop-loss is the only protection
- **Exchange counterparty risk:** Trading crypto directly exposes to exchange risk (FTX-style); using crypto ETFs (BITO, FETH) mitigates this but introduces tracking error and contango drag

**Key structural advantage:** By being flat in bear markets, the strategy avoids the catastrophic crypto drawdowns (BTC -80% in 2018, -70% in 2022) that would destroy a buy-and-hold crypto portfolio. Capital preservation in bear markets is the core value proposition.

---

## Alpha Decay Analysis

*(Required by Research Director gate before forwarding to Engineering Director)*

**Signal:** 20-day/60-day EMA crossover — trend-following signal, not mean-reverting.

| IC Metric | Estimate | Notes |
|-----------|----------|-------|
| IC at T+1 (next day) | ~0.02–0.04 | Low; momentum takes time to confirm |
| IC at T+5 (1 week) | ~0.04–0.07 | Rising; trend momentum accruing |
| IC at T+20 (1 month) | ~0.06–0.10 | Peak; EMA trend is a medium-term signal |
| IC at T+60 (3 months) | ~0.04–0.07 | Gradual decay as trend matures |
| IC at T+120 (6 months) | ~0.02–0.04 | Near baseline; trend has typically resolved or reversed |

**Signal half-life estimate:** ~40–60 trading days. EMA crossover signals are most predictive in the 20–60 day horizon. After a trend has been running for 3+ months, the predictive power of the signal decays as mean-reversion becomes more likely.

**IC decay shape:** Gradual ramp-up to peak at ~20 days, then gradual decline. No cliff drop — the trend-following signal degrades smoothly.

**Transaction cost viability:**
- BTC/ETH via futures ETF (BITO, FETH): Expense ratio ~1%/year drag; manageable for medium-term holding periods
- BTC/ETH directly via Coinbase/Kraken: 0.10% maker/0.20% taker; at 6–12 round trips/year typical for this strategy, total cost < 2.4% annually
- Estimated average holding period per trade: 30–90 days (based on EMA parameters)
- **Signal half-life (~50 days) >> 1 day → transaction cost concern is immaterial**
- Edge easily survives realistic costs

**Conclusion:** Alpha decay profile is favorable — medium-term trend signal with adequate holding periods to cover transaction costs. Passes alpha decay gate.

---

## Entry / Exit Logic

**Universe:** BTC and ETH (2 assets)

**Implementation options:**
1. **Preferred (backtesting):** BTC daily close price from Binance/CoinGecko; ETH daily close price
2. **Live trading (short-term):** Crypto ETFs: BITO (BTC futures ETF), FETH (Fidelity ETH ETF) — reduces exchange counterparty risk
3. **Live trading (advanced):** Coinbase Advanced Trade API with USDC settlement

**Signal construction (daily, evaluated at close):**
1. Compute `EMA_fast = EMA(close, ema_fast_period)` (default: 20 days)
2. Compute `EMA_slow = EMA(close, ema_slow_period)` (default: 60 days)
3. Signal: +1 (long) if EMA_fast > EMA_slow; 0 (flat) if EMA_fast ≤ EMA_slow
4. Signal changes are detected on each daily bar

**Entry:**
- Go long at the close (or next open) when EMA_fast crosses above EMA_slow
- Initial position: equal capital allocation per asset ($12,500 per asset at $25K starting capital)
- Scale rule: no scaling in; fixed position per asset

**Exit:**
- Exit to cash when EMA_fast crosses below EMA_slow (primary exit)
- Hard stop: exit immediately if drawdown from entry exceeds `trailing_stop_pct` (default: 15%)
- Time stop: none (trend-following strategies should not cap holding periods)

**Trailing stop implementation:**
- Track highest close since entry
- If current close < highest_close × (1 - trailing_stop_pct), exit at next open
- Stop resets to highest close + trailing_stop_pct when position updates (no fixed price stop — trailing)

**Position sizing:**
- Equal allocation: $12,500 per asset at $25K (50/50 BTC/ETH split)
- Alternative: $18,750 BTC / $6,250 ETH (75/25) if BTC-only signal is active and ETH is flat (consolidate idle capital)
- **First backtest: fixed 50/50 split** — simplest implementation

---

## Asset Class & PDT / Capital Constraints ($25K Account)

**PDT Rule Impact:**
- Crypto is NOT a stock/option — PDT rule does NOT apply to crypto trading
- This is a structural advantage: can trade as frequently as signals dictate without PDT restrictions
- However, signal frequency (6–12 round trips/year typical) is already very low

**$25K fit:**
- $12,500 per asset: sufficient for BTC lot sizes (0.01 BTC min at ~$90K = $900 minimum; no issue)
- ETH at ~$2,000/ETH: $12,500 = ~6.25 ETH; viable
- No leverage required
- Slippage at this size: < 0.01% on major exchanges (BTC daily volume > $20B)

**Crypto ETF alternative (for equity accounts):**
- BITO (BTC futures ETF): ~$25/share, $25K = 1,000 shares — highly liquid
- FETH (Fidelity ETH ETF): ~$15/share, $12,500 = 833 shares — liquid
- Disadvantage: contango drag (~5–10%/year on BTC futures) reduces returns vs. spot
- **Backtest should use spot prices; note contango drag for live implementation**

**Tax note:** Crypto gains are taxed as short-term capital gains if held <1 year (same rate as income). Not a Gate 1 criterion but relevant for live trading consideration.

---

## Gate 1 Assessment

| Criterion | Assessment | Rationale |
|-----------|------------|-----------|
| IS Sharpe > 1.0 | **LIKELY PASS** | 2020–2021 bull trend alone could drive Sharpe >1.5; the key question is whether 2018/2022 flat periods preserve enough capital |
| OOS Sharpe > 0.7 | **UNCERTAIN** | OOS window may fall in ranging post-2022 market; crypto Sharpe is highly regime-dependent |
| IS Max Drawdown < 20% | **UNCERTAIN** | Trailing stop at 15% limits individual asset drawdown; combined portfolio drawdown depends on correlation |
| Win Rate > 50% | **UNCERTAIN** | EMA crossover win rates typically 40–55%; compensated by high win/loss ratio (trends produce large wins) |
| Avg Win / Avg Loss > 1.0 | **LIKELY PASS** | Trending asset class with 30–90 day avg holds; losses capped at 15% stop, wins can be 50–200% |
| Trade Count > 50 | **BORDERLINE** | ~6–12 round trips/year × 2 assets × 5 IS years = 60–120 trades; just above threshold with 2 assets |
| PDT Compliance | **PASS** | Crypto not subject to PDT rule |
| Parameter Sensitivity | **UNKNOWN** | EMA periods are known to be sensitive; robustness testing across (fast, slow) combinations is critical |

**Overall Gate 1 Outlook: UNCERTAIN but HIGH UPSIDE POTENTIAL** — The 2020–2021 crypto bull market was one of the most significant trends in any asset class in a generation. If the signal captures even 60–70% of that move, the Sharpe could be exceptional. The primary concern is the OOS window and parameter sensitivity on EMA periods. The 2022 bear market exit capability is a critical differentiator.

**Primary risk for Gate 1:** Parameter sensitivity on EMA_fast/EMA_slow may be high — if different (fast, slow) combinations give very different results, the strategy is likely curve-fitted to the 2020-2021 bull. Explicitly test 6 parameter combinations.

---

## Recommended Parameter Ranges for First Backtest

| Parameter | Seed Value | Test Range | Sensitivity |
|-----------|-----------|------------|-------------|
| ema_fast_period (days) | 20 | [10, 15, 20, 30] | High (expected) |
| ema_slow_period (days) | 60 | [40, 50, 60, 90] | High (expected) |
| trailing_stop_pct | 0.15 | [0.10, 0.15, 0.20, 0.25] | Medium |
| capital_split (BTC/ETH) | 50/50 | [100/0, 75/25, 50/50] | Low |

**Note:** 4 tunable parameters — well within Gate 1 limit of 6. capital_split is a structural allocation decision, not a signal parameter.

**Critical robustness test:** Run all 4×4 = 16 combinations of (ema_fast, ema_slow). If Sharpe varies by >30% across combinations, flag as parameter-sensitive.

**Backtest period:** 2018-01-01 to 2023-12-31 (5 years, consistent with IS window requirement).

**Walk-forward:** 4 windows, 36-month IS / 6-month OOS.

**Data source:** BTC-USD and ETH-USD daily close prices from CoinGecko or Yahoo Finance (^BTCUSD, ^ETHUSD). If using crypto ETFs in backtesting, note the start date limitation (BITO launched October 2021; FETH launched July 2024 — not usable for full IS window). Use spot prices for backtest and convert for live implementation.

**PDT tracking:** Not required (crypto; no PDT).

---

## Pre-Backtest Checklist (Anti-Look-Ahead)

- [x] EMA at time T uses only price data up to and including T — no future prices
- [x] EMA crossover signal evaluated at close T; execution at open T+1 (no same-bar fill on signal bar)
- [x] Trailing stop uses highest close _up to T_ — no look-ahead into future highs
- [x] EMA parameters fixed before backtest (no optimization on OOS window)
- [x] Data split: IS ends strictly before OOS begins; no OOS data visible during IS parameterization

---

## Risk Director Review — QUA-106

**Reviewer:** Risk Director
**Date:** 2026-03-16
**Status:** SIGNED OFF — CLEARED FOR GATE 1 BACKTEST

### 1. IC Estimates (EMA Crossover on Crypto)

**VERIFIED — REASONABLE.**

The IC profile (T+1: ~0.02–0.04 → peak T+20: ~0.06–0.10 → decay T+120: ~0.02–0.04) is consistent with academic literature on crypto trend-following. Liu & Tsyvinski (2021, RFS) document significant return predictability in BTC/ETH at multi-week horizons. The IC estimates may even be slightly conservative relative to crypto-specific momentum studies, which is appropriate for a risk-gated pre-backtest assessment. The medium-term peak at ~20 days is the correct expected shape for a 20/60-day EMA crossover — the signal accumulates confirmation over days before the crossover registers, and decays as trend exhaustion sets in. IC profile: VALID.

### 2. Data Source — Spot BTC/ETH for IS Window 2018–2022

**CONFIRMED — SPOT DATA AVAILABLE.**

- CoinGecko and Yahoo Finance (^BTCUSD, ^ETHUSD) provide BTC daily data from 2013+ and ETH daily data from 2016+. Both fully cover the 2018-01-01 start date.
- BITO launched October 2021 → correctly excluded for IS backtest. Usable for live implementation only post-2021.
- FETH launched July 2024 → correctly excluded for IS backtest. Note: FETH is also effectively unusable for near-term paper trading given limited performance history; BITO is the only viable ETF proxy for BTC live signal routing.
- Crypto asset class constraint (criteria.md §Asset-Class Constraints): BTC and ETH only — SATISFIED.
- 2018 crypto winter included in test period — SATISFIED (criteria.md hard requirement).

Data source: VALID.

### 3. BITO Contango Drag Estimate (~5–10%/year)

**REASONABLE — QUALIFIED FLAG.**

The 5–10%/year estimate is appropriate as a long-run average for BITO front-month roll costs. However, note that during strong bull markets — precisely when this strategy is most active — BTC futures contango was significantly steeper. Annualized roll costs during the 2021 bull market peak were estimated at 15–25%/year. This means the strategy's live returns via BITO could be substantially lower than spot-based backtest returns during its most profitable regime.

**This is not a blocker** — the hypothesis correctly states the backtest uses spot prices and explicitly flags contango drag as a live implementation adjustment. The estimate is directionally correct for baseline planning. Risk flag logged: **live implementation returns via BITO should be modeled with 10–20% drag assumption during bull regimes, not 5–10%.** Engineering Director should account for this during Gate 2 (paper trading with ETFs).

Contango drag note: REASONABLE for hypothesis purposes. Live implementation flag: REQUIRED.

### 4. Anti-Look-Ahead Checklist — Sign-Off

All 5 checklist items reviewed and signed off:

| Item | Assessment |
|------|-----------|
| EMA at T uses only data ≤ T | ✅ SIGNED OFF — standard EMA rolling formula; no look-ahead if implemented correctly |
| Signal at close T, execution at open T+1 | ✅ SIGNED OFF — critical protection against same-bar fill; explicitly specified |
| Trailing stop uses highest close up to T only | ✅ SIGNED OFF — correctly prohibits look-ahead into future highs, which is the most common trailing stop look-ahead bug |
| EMA parameters fixed before OOS window | ✅ SIGNED OFF — walk-forward protocol correct; parameterization on IS only |
| IS/OOS data split strict; no OOS contamination during IS parameterization | ✅ SIGNED OFF — standard walk-forward design |

**Look-ahead risk: NONE DETECTED at hypothesis level.** Engineering Director must certify again in Gate 1 backtest code review.

### 5. Additional Risk Flags for Gate 1 Backtest

1. **BTC/ETH correlation risk:** BTC/ETH correlation ~0.8+ means independent signals provide limited diversification. During simultaneous drawdown events, both positions may hit trailing stops at the same time, producing a synchronized portfolio-level drawdown. Engineering Director must verify combined max drawdown does not approach or exceed 20% IS threshold. This is the primary Gate 1 risk for this strategy.

2. **Trade count borderline:** ~60–120 trades (IS, 2 assets × 5 years × 6–12 round trips) just clears the 50-trade minimum. If EMA whipsaw frequency is lower than estimated, trade count could fall below threshold — automatic disqualification. Engineering Director: report trade count explicitly in Gate 1 submission.

3. **EMA parameter sensitivity flagged as high:** The hypothesis correctly identifies this as the primary overfitting risk. The 4×4 = 16 EMA parameter grid test is required. If Sharpe variance across combinations exceeds 30%, this is an automatic disqualification flag under criteria.md parameter robustness requirement.

4. **Win rate concern:** EMA crossover win rates typically 40–55%; hypothesis projects compensating win/loss ratio. Gate 1 must confirm win rate > 50% OR average win / average loss > 1.2 (per criteria.md). If win rate is below 50%, the win/loss ratio must be explicitly documented to justify approval.

### Verdict

**CLEARED FOR GATE 1 BACKTEST.** Hypothesis is structurally sound, economically motivated, and anti-look-ahead checklist is complete. Data availability confirmed for full IS window. Flag items above (trade count, BTC/ETH correlation, EMA sensitivity) must be explicitly addressed in Gate 1 submission to Risk Director.
