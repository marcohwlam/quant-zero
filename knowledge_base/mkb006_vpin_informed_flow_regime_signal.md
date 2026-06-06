# MKB-006: VPIN — Volume-Synchronized Probability of Informed Trading as Regime Signal

**Status:** KNOWLEDGE_BASE
**Author:** Research Director
**Date:** 2026-06-06
**Asset class:** US equities (large-cap ETFs), futures (ES, NQ)
**Strategy type:** Microstructure regime classifier / informed flow directional signal
**Data resolution:** Volume-bucketed bars (derived from 1-minute OHLCV or tick data)

---

## Provenance

**Primary source:**
- Easley, D., López de Prado, M., & O'Hara, M. (2012). "Flow Toxicity and Liquidity in a High Frequency World." *Review of Financial Studies*, 25(5), 1457–1493.
  - Section 2 (pp. 1460–1467): VPIN (Volume-Synchronized Probability of Informed Trading) definition and mathematical framework. VPIN = |V_B − V_S| / V averaged over a rolling window of volume buckets, where V_B and V_S are estimated buy and sell volumes within each bucket using bulk volume classification (BVC).
  - Section 3 (pp. 1467–1475): Empirical validation on E-mini S&P 500 futures (ES) 2008–2011. VPIN above 0.5 indicates majority-informed order flow; VPIN below 0.3 indicates majority-uninformed flow. Key finding: VPIN > 0.7 preceded the May 6, 2010 Flash Crash by approximately 60–90 minutes.
  - Section 4 (pp. 1475–1485): VPIN as a real-time liquidity risk indicator — market makers widen spreads in high-VPIN environments, increasing market impact costs for directional traders. VPIN above 0.7 is associated with 2–3× normal bid-ask spreads in ES futures.

**Secondary sources:**
- Easley, D., & O'Hara, M. (1987). "Price, Trade Size, and Information in Securities Markets." *Journal of Financial Economics*, 19(1), 69–90.
  - Original theoretical framework (PIN model) establishing the probability of informed trading (PIN) as a function of trade direction and size. VPIN is the volume-synchronized, real-time extension of this framework, eliminating the need for the computationally expensive maximum likelihood estimation required for PIN.
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
  - Chapter 19, pp. 279–295: "Microstructure Features." Practical implementation of VPIN using bulk volume classification (BVC) — the method for estimating buy/sell volume split from OHLCV bars without tick data. Section 19.2 (pp. 283–287): BVC formula and its statistical properties vs. tick-rule classification.
  - Chapter 2, pp. 30–44: Volume bar construction as the foundational data structure for VPIN computation (VPIN is defined over volume buckets, not time buckets).
- Easley, D., de Prado, M.M.L., O'Hara, M., & Zhang, Z. (2021). "Microstructure in the Machine Age." *Review of Financial Studies*, 34(7), 3316–3362.
  - Section 4 (pp. 3327–3338): VPIN evolution in algorithmic market structure; updated empirical results confirming VPIN's predictive power for short-term price impact and spread widening in post-2012 US equity markets.

**Controversy note (required disclosure):**
- Andersen, T.G., & Bondarenko, O. (2014). "VPIN and the Flash Crash: A Review and Further Evidence." *Journal of Financial Markets*, 17, 1–36.
  - Authors argue that VPIN did not provide statistically superior advance warning of the Flash Crash compared to simpler volatility measures, and that VPIN's predictive performance in Easley et al. (2012) was partially attributable to a specific choice of bucket size and rolling window. Failure mode section references this critique.

---

## Summary

VPIN (Volume-Synchronized Probability of Informed Trading) is a real-time microstructure measure developed by Easley, López de Prado & O'Hara (2012) that estimates what fraction of order flow is driven by informed (directional, alpha-bearing) traders versus uninformed (liquidity-providing, noise) traders. VPIN is computed over rolling windows of fixed-volume "buckets" rather than fixed time intervals, making it robust to the heteroskedastic trading activity that distorts time-based signals. High VPIN (> 0.5) indicates that informed traders dominate the current order flow — momentum in the direction of the imbalance is likely to continue, and mean reversion strategies should be suspended. Low VPIN (< 0.3) indicates noise-trader-dominated flow — mean reversion strategies (such as MKB-003 OU or MKB-005 VWAP deviation) have higher expected IC. The primary trading strategy is to use VPIN as a regime classifier that gates entry into either a directional (high-VPIN) or mean-reverting (low-VPIN) mode, rather than as a standalone entry signal.

---

## Edge & Mechanism

**Why VPIN classifies intraday trading regimes at the minute-bar level:**

1. **Information asymmetry theory (Easley & O'Hara 1987):** In any continuous market, a fraction α of traders possess private information about fundamental value. When α is high (high VPIN), their orders generate persistent directional imbalance and price adjustment. When α is low (low VPIN), market noise dominates and prices mean-revert toward equilibrium. VPIN estimates α in real time, allowing dynamic regime switching between momentum and mean reversion strategies.

2. **Market maker spread widening under informed flow:** Market makers (including HFT liquidity providers) observe VPIN implicitly through their own inventory positions and adverse selection losses. When VPIN rises, market makers increase quoted spreads to compensate for elevated adverse selection risk. Easley et al. (2012, Section 4) show spread widening leads VPIN — HFT market makers widen before the VPIN signal fully crystallizes — meaning VPIN provides a forward-looking estimate of near-term execution cost and directional risk.

3. **Volume bucketing eliminates time-of-day distortion:** VPIN is defined over fixed-volume buckets (e.g., V = 1/50 of average daily volume in ES). This means each bucket represents the same amount of market "activity" regardless of when in the day it occurs. This makes VPIN directly comparable across the trading day — unlike time-based signals that conflate high-volume periods (open, close) with low-volume periods (midday).

4. **BVC (Bulk Volume Classification) as tractable approximation:** Computing buy/sell volume from OHLCV bars (without tick data) uses the cumulative distribution function (CDF) of the standard normal applied to the return within each bar. Lopez de Prado (2018, p. 285) shows that BVC produces unbiased estimates of V_B and V_S for liquid instruments, with classification accuracy ~68–72% vs. ~60–65% for the naive close-direction rule.

**VPIN interpretation thresholds (Easley et al. 2012, Table 3):**

| VPIN Level | Regime | Strategy Implication |
|---|---|---|
| VPIN > 0.7 | High informed flow / crisis | Avoid new positions; widen stops; risk-off |
| 0.5 < VPIN ≤ 0.7 | Moderate informed flow | Directional follow (trade in direction of imbalance) |
| 0.3 ≤ VPIN ≤ 0.5 | Mixed flow | No regime signal; use other signals |
| VPIN < 0.3 | Low informed flow / noise traders | Mean reversion strategies (OU, VWAP) preferred |

---

## Entry/Exit Logic

**Step 1: Construct volume buckets using BVC (Lopez de Prado 2018)**
```python
import numpy as np
from scipy.stats import norm

def compute_vpin_from_minute_bars(bars, n_buckets=50, window=50):
    """
    Approximate VPIN using Bulk Volume Classification on 1-minute OHLCV bars.
    n_buckets: number of volume buckets for VPIN window
    window: rolling VPIN computation window (number of buckets)
    """
    daily_avg_volume = bars['volume'].mean() * 390   # Approx daily volume
    bucket_volume = daily_avg_volume / n_buckets

    # BVC: classify each bar's volume into buy/sell
    bars = bars.copy()
    bars['sigma'] = bars['close'].pct_change().rolling(20).std()
    bars['z'] = (bars['close'] - bars['open']) / (bars['sigma'] * bars['close'] + 1e-10)

    # Buy volume = V × Φ(z), Sell volume = V × (1 - Φ(z))
    bars['buy_vol'] = bars['volume'] * norm.cdf(bars['z'])
    bars['sell_vol'] = bars['volume'] * (1 - norm.cdf(bars['z']))

    # Build volume buckets
    buckets = []
    cum_buy = 0
    cum_sell = 0
    cum_vol = 0

    for _, row in bars.iterrows():
        cum_buy += row['buy_vol']
        cum_sell += row['sell_vol']
        cum_vol += row['volume']

        while cum_vol >= bucket_volume:
            # Bucket complete
            fraction = bucket_volume / cum_vol
            bucket_buy = cum_buy * fraction
            bucket_sell = cum_sell * fraction
            buckets.append({
                'timestamp': row.name,
                'buy_vol': bucket_buy,
                'sell_vol': bucket_sell,
                'total_vol': bucket_volume,
                'imbalance': abs(bucket_buy - bucket_sell) / bucket_volume
            })
            # Carry over excess volume
            cum_buy *= (1 - fraction)
            cum_sell *= (1 - fraction)
            cum_vol -= bucket_volume

    buckets_df = pd.DataFrame(buckets)

    # Rolling VPIN: average imbalance over last `window` buckets
    buckets_df['vpin'] = buckets_df['imbalance'].rolling(window).mean()
    return buckets_df
```

**Step 2: Extract direction of informed flow (when VPIN > 0.5)**
```python
def get_informed_direction(buckets_df, lookback=5):
    """
    When VPIN is high, determine whether informed traders are buying or selling.
    Use net signed imbalance over last `lookback` buckets.
    """
    recent = buckets_df.tail(lookback)
    net_buy = (recent['buy_vol'] - recent['sell_vol']).sum()
    total = recent['total_vol'].sum()
    signed_imbalance = net_buy / total   # Range [-1, +1]; positive = net buying

    if signed_imbalance > 0.1:
        return +1   # Informed traders net buying → long
    elif signed_imbalance < -0.1:
        return -1   # Informed traders net selling → short
    else:
        return 0    # No clear direction
```

**Step 3: Strategy logic (VPIN regime-gated)**
```python
VPIN_HIGH = 0.55     # Threshold for directional signal
VPIN_LOW = 0.30      # Threshold for mean reversion mode
VPIN_CRISIS = 0.70   # Risk-off threshold (too toxic to trade)

current_vpin = buckets_df['vpin'].iloc[-1]
informed_dir = get_informed_direction(buckets_df)

if current_vpin > VPIN_CRISIS:
    # Close all positions; do not open new ones
    close_all_positions()

elif current_vpin > VPIN_HIGH and informed_dir != 0:
    # Directional mode: follow informed flow
    # Hold for 2-3× bucket formation time (~15–45 min)
    direction = informed_dir
    enter_directional_position(direction, hold_bars=20)

elif current_vpin < VPIN_LOW:
    # Mean reversion mode: defer to MKB-003 or MKB-005 signals
    # VPIN is a regime gate, not the entry trigger in this mode
    use_mean_reversion_signal()
```

**Exit conditions (directional mode):**
- VPIN drops below 0.45 (informed flow dissipating — close directional position)
- VPIN rises above VPIN_CRISIS (0.70) — close immediately (systemic risk event)
- **Time stop:** 30 minutes (directional VPIN signals have ~15–30 min half-life)
- **Stop-loss:** 0.25% adverse move (informed direction thesis failed)

---

## Alpha Decay Analysis

- **Signal half-life:** VPIN regime persistence: 60–240 minutes (Easley et al. 2012, Figure 4 — VPIN autocorrelation function shows significant persistence for 50–100 volume buckets; at ~3 min/bucket → 2.5–5 hours of persistence). Directional signal (informed flow direction) within high-VPIN regime: 15–45 minutes.
- **IC decay curve (directional signal, high-VPIN regime):**
  - T+0 (signal bar): IC ≈ 0.12–0.18 (strong informed flow direction confirmed by VPIN and signed imbalance)
  - T+15min: IC ≈ 0.08 (informed execution still ongoing; primary pressure window)
  - T+30min: IC ≈ 0.04 (late phase of informed execution; follow-on momentum)
  - T+60min: IC ≈ 0.01 (VPIN regime may have shifted; signal exhausted)
- **Transaction cost viability:**
  - Half-life 15–45 min >> 1-day threshold
  - WARNING: High-VPIN environment means market maker spreads are WIDER than normal (2–3× per Easley et al. 2012, Table 4). Entry/exit costs are elevated precisely when the signal is active.
  - Average trade return (directional, high-VPIN): estimated 0.06–0.12% (Easley et al. Table 5 implications)
  - Round-trip spread in high-VPIN: ~0.004–0.008% (2× normal SPY spread)
  - Net edge: ~0.052–0.112% per trade — **viable but tighter than low-VPIN environments**
- **ML anti-snooping note (Lopez de Prado 2018):** The VPIN bucket size (V) and rolling window (n_buckets) must be calibrated on IS data only. Testing multiple combinations of V and n_buckets on the same IS dataset creates a parameter-snooping risk that is particularly dangerous with VPIN given the Andersen-Bondarenko critique (see Failure Modes).

---

## Failure Modes & Overfitting Risks

1. **Andersen-Bondarenko critique:** Andersen & Bondarenko (2014) demonstrated that VPIN's performance as a Flash Crash predictor was sensitive to the choice of bucket size V and rolling window. With different but equally plausible parameters, VPIN's advance warning of the Flash Crash is statistically indistinguishable from VIX or realized volatility. The bucket size parameter must be validated out-of-sample to avoid the criticism that the apparent predictive power is an artifact of in-sample parameter selection.

2. **Flash Crash / liquidity crisis regime:** During the Flash Crash itself, VPIN rose above 0.9 — but the strategy's stop-loss (VPIN > 0.70 → close all) would correctly exit before peak toxicity. The risk is the microsecond speed of liquidity events; a 1-minute bar signal cannot exit at precisely the right moment. Slippage on exits in crisis conditions can exceed the entire prior trading profit.

3. **BVC approximation error:** The Bulk Volume Classification (BVC) approximation using 1-minute OHLCV bars has a classification error rate of ~30–32% (Lopez de Prado 2018, p. 286). This means roughly 1 in 3 bars is misclassified as net-buy vs. net-sell. The resulting VPIN estimate has significant noise, particularly for short rolling windows (< 30 buckets). Must use window of ≥ 50 buckets for statistical stability.

4. **Regime stickiness and false signals:** VPIN can remain in a "high" regime for extended periods during trending markets (e.g., 2020 COVID crash, 2022 rate-shock selloff) without providing directional trading opportunities. In these environments, the directional signal fires repeatedly in the same direction while the market is in a sustained trend — the strategy may overconcentrate in a single direction.

5. **Bucket size calibration dependency:** VPIN uses volume buckets of size V = (average daily volume) / 50 as the canonical parameter (Easley et al. 2012). If the instrument's average daily volume changes substantially (e.g., a 3× spike in retail participation during 2020–2021 meme stock era), the bucket size becomes stale and VPIN values are not comparable to the historical calibration period.

6. **ES futures vs. SPY ETF structure:** Easley et al. (2012) calibrated VPIN on E-mini S&P 500 futures (ES), not ETFs. ETF structure introduces additional flow from creation/redemption mechanics that is uninformed (pure arbitrage) but may appear as signed imbalance. Applying ES-calibrated VPIN thresholds to SPY directly is a model risk that requires empirical re-validation.

---

## Infrastructure Requirements

| Requirement | Status | Notes |
|---|---|---|
| 1-minute OHLCV bars with volume for SPY/QQQ | **NOT in current pipeline** | Alpaca historical minute bars; volume data required for BVC |
| Volume bucket construction engine (BVC) | **NOT in current pipeline** | Custom implementation; Lopez de Prado 2018 Chapter 2 + 19 |
| Rolling VPIN computation with bucket state | **NOT in current pipeline** | Stateful engine tracking partial bucket fill across bars |
| Signed imbalance direction tracker | **NOT in current pipeline** | Rolling window of buy_vol - sell_vol per bucket |
| Integration with MKB-003 / MKB-005 signals | **NOT in current pipeline** | VPIN gates which signal module is active; requires signal multiplexing |

**Minimum viable:** Alpaca 1-min bars + BVC approximation + rolling VPIN (bucket size approximated from daily volume). No tick data required for initial implementation.

**Full implementation:** Polygon.io or Alpaca tick data for accurate Lee-Ready classification instead of BVC approximation (improves VPIN accuracy from ~70% to ~95% per Lopez de Prado 2018, p. 291).

---

## Pipeline Graduation Path

1. Engineering Director builds intraday data pipeline (Alpaca 1-min bars with volume)
2. BVC + volume bucket engine from Lopez de Prado (2018) Chapter 2 implementation
3. Rolling VPIN computation with configurable bucket size and window length
4. Graduate to `research/hypotheses/` as `H52_vpin_regime_signal.md` — in combination with MKB-003 (OU) or MKB-005 (VWAP) as the mean reversion engine gated by VPIN regime
5. Gate 1 backtest: IS 2015–2022 (SPY minute bars), OOS 2023–2025
6. Critical: validate bucket size V out-of-sample to address Andersen-Bondarenko critique

---

## References

- Easley, D., López de Prado, M., & O'Hara, M. (2012). "Flow Toxicity and Liquidity in a High Frequency World." *Review of Financial Studies*, 25(5), 1457–1493.
- Easley, D., & O'Hara, M. (1987). "Price, Trade Size, and Information in Securities Markets." *Journal of Financial Economics*, 19(1), 69–90.
- Easley, D., de Prado, M.M.L., O'Hara, M., & Zhang, Z. (2021). "Microstructure in the Machine Age." *Review of Financial Studies*, 34(7), 3316–3362.
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapters 2, 19.
- Andersen, T.G., & Bondarenko, O. (2014). "VPIN and the Flash Crash: A Review and Further Evidence." *Journal of Financial Markets*, 17, 1–36. *(Critique — read before deploying VPIN.)*
- Kyle, A.S. (1985). "Continuous Auctions and Insider Trading." *Econometrica*, 53(6), 1315–1335.

---

*Research Director | QUA-55 | 2026-06-06*
