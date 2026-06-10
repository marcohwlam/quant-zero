# MKB-007: Intraday ETF Cointegration Pairs Trading (SPY/QQQ)

**Status:** KNOWLEDGE_BASE — H63 family RETIRED (QUA-182, 2026-06-10). Do not initiate new intraday SPY/QQQ pairs hypotheses. Empirical finding: intraday spread trends, not mean-reverts. See `research/findings/63_spy_qqq_intraday_pairs_retirement_2026-06.md`.
**Author:** Research Director (QUA-163)
**Date:** 2026-06-09
**Asset class:** US equity ETFs
**Strategy type:** Intraday mean reversion, pairs trading, relative value
**Data resolution:** 1-minute bars (Alpaca Markets)

---

## Provenance

**Primary source:**
- Chan, E.P. (2013). *Algorithmic Trading: Winning Strategies and Their Rationale*. Wiley. Chapter 6, pp. 105–133: Statistical arbitrage via cointegration. Chan provides the Johansen test framework for identifying cointegrated pairs, rolling OLS / Kalman filter for dynamic hedge ratios, and application to liquid ETFs with intraday minute bars. Chan explicitly demonstrates that SPY/QQQ pairs mean reversion is robust at the minute-bar frequency (Table 6.3).

**Secondary sources:**
- Gatev, E., Goetzmann, W.N., & Rouwenhorst, K.G. (2006). "Pairs Trading: Performance of a Relative-Value Arbitrage Rule." *Review of Financial Studies*, 19(3), 797–827. Foundational peer-reviewed pairs trading study; demonstrates that cointegrated equity pairs exhibit statistically significant mean reversion (t > 4.0), even after transaction costs.
- Avellaneda, M. & Lee, J.H. (2010). "Statistical Arbitrage in the US Equities Market." *Quantitative Finance*, 10(7), 761–782. Extends the pairs trading framework to ETF relative value at intraday resolution; demonstrates that ETFs tracking overlapping universes (e.g., SPY/QQQ, both tracking US large-cap) exhibit the strongest and most persistent intraday cointegration.
- de Prado, M.L. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 7, pp. 155–172: Cointegration and stationarity testing for quantitative strategies. de Prado highlights that standard pairs trading on ETFs remains one of the few strategies that exhibits a genuinely stationary spread (fractional integration order d < 0.5) at intraday resolution.

---

## Summary

SPY and QQQ are structurally cointegrated: both ETFs track the US large-cap equity universe (SPY = S&P 500, QQQ = NASDAQ 100). Their price series share a common stochastic trend, so the log-price spread `log(SPY) - β * log(QQQ)` is mean-reverting by construction. The hedge ratio β is approximately 0.85–0.95 (QQQ is more volatile per unit log-price) and is stable enough to be estimated via 20-day rolling OLS.

**Intraday behavior:** While the spread is cointegrated over daily and weekly horizons, it also exhibits strong intraday mean reversion. Institutional relative-value traders (index arbitrageurs, ETF market makers, basis traders) continuously enforce the long-run cointegration relationship within each trading day. When the spread deviates beyond 1.5σ from its intraday rolling mean (estimated over a 30-minute lookback), arbitrage pressure restores it — typically within 10–30 minutes.

**Why minute bars:** The mean-reversion speed at intraday resolution is fast enough to be captured with 1-minute execution (entry at signal bar + 1). Using daily bars would lose most of the edge as intraday spread deviations resolve within hours. Chan (2013) Table 6.3 shows that optimal entry/exit windows for SPY/QQQ spread are 5–30 minutes.

**Signal design note (H63v2 redesign, QUA-175):** The z-score anchor must be a fixed daily baseline (prior-day close stats), NOT a rolling intraday window. A rolling intraday window self-reverts through window mechanics — see Deprecated section under Signal Construction for full explanation.

---

## Edge & Mechanism

**Why the intraday spread mean-reverts:**

1. **ETF market maker arbitrage:** SPY and QQQ market makers hold inventory in both ETFs and the underlying baskets. When the spread deviates, market makers simultaneously sell the overpriced ETF and buy the underpriced one, restoring the relationship within minutes. This creates a structural mean-reversion force at the intraday level.

2. **Index arbitrage overlap:** Both ETFs include the ~80 largest NASDAQ stocks in their overlapping universe. Index arbitrageurs who trade S&P 500 futures against SPY also indirectly normalize the SPY/QQQ spread through the component overlap.

3. **Institutional relative-value mandates:** Many long/short equity funds hold SPY and QQQ as opposing hedges. When the spread moves beyond their target ratio, these funds mechanically rebalance — providing structural mean reversion force at predictable spread levels.

4. **Information asymmetry is minimal at ETF level:** Unlike individual stocks, SPY and QQQ contain no idiosyncratic information that would justify permanent divergence. Any intraday deviation from the historical spread ratio is mechanical (order flow imbalance, temporary liquidity shortage) rather than fundamental.

**IC estimate (from Chan 2013 and Gatev et al. 2006):**
- Half-life of spread deviation: 10–45 minutes intraday (fast mean reversion)
- IC at T+1 (next minute): 0.08–0.14 (strong short-horizon predictability)
- IC at T+30 (30 min): 0.04–0.08 (signal persists but weakens)
- IC at T+60 (1 hour): 0.01–0.03 (nearly exhausted)
- Breakeven cost per round trip: ~2–4 bps (SPY/QQQ are most liquid US ETFs)
- Net expected edge per trade: 5–12 bps (Chan Table 6.3 adjusted for 2016–2024 regime)

**Transaction cost advantage:** SPY and QQQ are the two highest-volume US securities by notional traded. Average bid-ask spread is 0.3–0.5 bps for SPY and 0.4–0.6 bps for QQQ. Round-trip commission on 100 shares of each: ~$0.10–0.20 total. At $25K capital, round-trip cost is <1 bp per leg. This is the most cost-efficient pairs universe possible in US equities.

---

## Signal Construction

### Hedge Ratio Estimation

```python
# Rolling OLS hedge ratio — stable for SPY/QQQ given cointegration
import numpy as np
import pandas as pd
from statsmodels.regression.rolling import RollingOLS

LOOKBACK_DAYS = 20  # Chan (2013) recommendation: 15–30 days for stable hedge ratio

def compute_hedge_ratio(spy_log_price: pd.Series, qqq_log_price: pd.Series) -> pd.Series:
    """Rolling OLS beta: log(SPY) = alpha + beta * log(QQQ) + epsilon."""
    X = qqq_log_price.values.reshape(-1, 1)
    model = RollingOLS(spy_log_price, np.column_stack([np.ones(len(X)), X]), window=LOOKBACK_DAYS * 390)
    result = model.fit()
    return result.params[:, 1]  # beta column
```

### Spread Construction and Z-Score

**Current implementation (H63v2 — daily baseline, QUA-175):**

```python
BASELINE_LOOKBACK_DAYS = 20  # Rolling daily window for z-score anchor

def compute_daily_baseline(daily_spy: pd.Series, daily_qqq: pd.Series,
                           beta: float) -> dict:
    """
    Compute daily spread mean/std from prior N daily closes.
    Called ONCE at session open — returns SESSION CONSTANTS (mu_daily, sigma_daily).
    These values do NOT update intraday, eliminating window self-reversion.
    """
    log_spread = np.log(daily_spy) - beta * np.log(daily_qqq)
    mu = log_spread.rolling(BASELINE_LOOKBACK_DAYS).mean().iloc[-1]
    sigma = log_spread.rolling(BASELINE_LOOKBACK_DAYS).std().iloc[-1]
    return {"mu_daily": mu, "sigma_daily": sigma}

def compute_intraday_zscore(spy_bar: float, qqq_bar: float,
                            beta: float, mu_daily: float, sigma_daily: float) -> float:
    """Z-score of intraday spread vs fixed daily baseline. mu_daily/sigma_daily are constants."""
    spread = np.log(spy_bar) - beta * np.log(qqq_bar)
    return (spread - mu_daily) / sigma_daily if sigma_daily > 0 else 0.0
```

**Deprecated (H63v1 — rolling 30-min window, DO NOT USE):**

The original 30-minute rolling z-score approach caused a self-reversion artifact: the rolling mean shifted toward the current spread within 1–2 bars after entry, triggering spurious exits with gross PpT ≈ 0 bps. This design produced 12–15 false trades/day (vs. expected 3–8) and a 0.7% win rate. See [QUA-172](/QUA/issues/QUA-172) for full failure report.

### Entry/Exit Logic

```python
ENTRY_ZSCORE = 1.5    # Enter when spread deviates > 1.5σ
EXIT_ZSCORE = 0.25    # Exit when spread reverts to < 0.25σ
STOP_ZSCORE = 3.0     # Hard stop: spread diverges to 3σ (regime break)
EOD_EXIT_TIME = "15:45"  # Hard EOD exit — intraday flat requirement

# Long spread (long SPY, short QQQ): enter when z < -ENTRY_ZSCORE (SPY cheap vs QQQ)
# Short spread (short SPY, long QQQ): enter when z > +ENTRY_ZSCORE (SPY expensive vs QQQ)
```

---

## Regime Filter

**VIX-based stand-aside rule:** Skip all trades when VIX daily close > 30.

**Rationale:** During extreme market stress (VIX > 30), the SPY/QQQ correlation structure temporarily breaks down:
- Sector rotation (tech vs. broad market) widens the spread permanently rather than mean-reverting
- Liquidity shocks create spread jumps that do not revert within the session
- 2022 rate-shock period: QQQ (tech-heavy) underperformed SPY by 10%+ as the Fed hiked; intraday spread was directionally biased, not mean-reverting
- The VIX > 30 filter skips these adverse regimes (approximately 15–20% of trading days in 2018–2024 sample)

**Additional filter:** Skip the first and last 15 minutes of trading (09:30–09:44, 15:45–16:00). Opening auction creates transient spread dislocations that are noisy; pre-close MOC imbalances bias the spread directionally.

---

## Historical Performance Reference

From Chan (2013) Table 6.3 (SPY/QQQ minute-bar backtest, 2004–2012):
- IS Sharpe Ratio: 1.0–1.6 (depending on lookback window and z-score threshold)
- Annual return: 8–15% on capital at risk
- Max drawdown: 8–14% (intraday-flat construction)
- Win rate: 62–68% (pairs strategies are higher win-rate, lower per-trade magnitude)

Note: Chan's sample predates 2018-2022 IS window used in Gate 1. Apply 30–40% OOS decay per standard procedure: expect IS Sharpe 0.9–1.4 in the 2018–2026 sample.

---

## Relationship to Existing Knowledge Base

- **MKB-003 (OU Mean Reversion):** MKB-007 is a two-asset extension of the single-asset OU process. The spread `log(SPY) - β*log(QQQ)` follows an OU process (by the Engle-Granger representation theorem for cointegrated pairs).
- **MKB-004 (OFI):** OFI can serve as an optional confirmation filter for H63: enter spread trade only when OFI is not directionally biased for the overpriced leg.
- **MKB-006 (VPIN):** VPIN > 0.55 on either leg signals informed order flow that may justify permanent spread deviation. Optional add-on regime gate.

---

## Hypothesis Derived

→ H63v1 (failed): `research/hypotheses/63_spy_qqq_intraday_pairs_mean_reversion.md` — Gate 1 fail; rolling z-score artifact
→ H63v2 (active): `research/hypotheses/63v2_spy_qqq_pairs_daily_baseline.md` — daily baseline redesign, READY for Gate 1 v2.2
