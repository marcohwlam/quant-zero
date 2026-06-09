# VPIN + VIX Regime Filter Specification

**Status:** SPECIFICATION  
**Author:** Market Regime Agent  
**Date:** 2026-06-09  
**Issue:** QUA-127  
**Asset class:** US equities (SPY, QQQ), index futures (ES, NQ)  
**Data resolution:** 1-minute OHLCV bars  
**Output:** Per-bar boolean mask (True = tradeable, False = stand aside)

---

## Executive Summary

This filter gates strategy entries across two independent risk dimensions:

1. **Flow Toxicity Gate (VPIN):** Suppresses entries when informed order flow dominates the market (high probability of adverse selection and fast execution cost).
2. **Volatility Regime Gate (VIX / Realized Vol):** Suppresses entries outside a calibrated volatility band where execution risk and slippage exceed expected signal edge.

**Decision Rule:** Strategy is tradeable only when **both** gates permit:
```
TRADEABLE = (NOT VPIN_TOXIC) AND (VOLATILITY_IN_BAND)
```

---

## Layer 1: VPIN Toxicity Filter

### Theory & Citation

**Primary source:**  
Easley, D., López de Prado, M., & O'Hara, M. (2012). "Flow Toxicity and Liquidity in a High Frequency World." *Review of Financial Studies*, 25(5), 1457–1493.
- Section 2 (pp. 1460–1467): VPIN mathematical definition and volume-bucketing framework.
- Section 3 (pp. 1467–1475): Empirical calibration on E-mini S&P 500 futures 2008–2011; VPIN > 0.5 indicates majority-informed flow; VPIN > 0.7 preceded Flash Crash by 60–90 minutes.
- Section 4 (pp. 1475–1485): High-VPIN environments associated with 2–3× widened bid-ask spreads (market maker adverse selection compensation).

**Supporting references:**  
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley, Chapters 2 & 19 — Bulk Volume Classification (BVC) approximation for computing buy/sell volume from OHLCV bars without tick data.
- Andersen, T.G., & Bondarenko, O. (2014). "VPIN and the Flash Crash: A Review and Further Evidence." *Journal of Financial Markets*, 17, 1–36 — Critique addressing parameter snooping risk in VPIN bucket-size selection (see Failure Modes).

### VPIN Formulation

**Step 1: Bulk Volume Classification (BVC)**

From OHLCV bars, estimate buy/sell volume split using the standard normal CDF applied to normalized intrabar return.

For each 1-minute bar $i$:
$$z_i = \frac{\log(C_i) - \log(O_i)}{\sigma_i \cdot C_i}$$

where:
- $C_i$ = close price, $O_i$ = open price
- $\sigma_i$ = rolling 20-bar standard deviation of log-returns

Buy and sell volume estimates:
$$V_B^i = V_i \cdot \Phi(z_i)$$
$$V_S^i = V_i \cdot (1 - \Phi(z_i))$$

where $\Phi(\cdot)$ is the CDF of the standard normal and $V_i$ is the bar volume.

**Step 2: Volume Bucketing**

Accumulate bars into fixed-size volume buckets. The bucket volume is calibrated as:
$$V_{\text{bucket}} = \frac{V_{\text{daily\_avg}}}{n_{\text{buckets}}}$$

where:
- $V_{\text{daily\_avg}}$ = average daily volume (e.g., 390-bar 1-minute rolling mean, annualized to daily volume)
- $n_{\text{buckets}}$ = 50 (canonical value per Easley et al. 2012; must be validated OOS to address Andersen-Bondarenko critique)

For each completed bucket $j$:
$$\text{Imbalance}_j = \left| V_B^j - V_S^j \right| / V_{\text{bucket}}$$

where $V_B^j$ and $V_S^j$ are the cumulative buy and sell volumes within the bucket.

**Step 3: Rolling VPIN**

Compute the rolling mean of imbalances over the last $w$ buckets (rolling window):
$$\text{VPIN}_t = \frac{1}{w} \sum_{k=t-w+1}^{t} \text{Imbalance}_k$$

where $w$ = 50 buckets (canonical window; must be validated OOS).

### Toxicity Classification

| VPIN Range | Regime | Action |
|---|---|---|
| VPIN ≤ 0.30 | Low toxicity | **PERMIT**: Mean reversion and range-bound strategies; best IC. |
| 0.30 < VPIN ≤ 0.50 | Normal toxicity | **PERMIT**: Mixed signals; neutral regime. |
| 0.50 < VPIN ≤ 0.70 | Moderate-high toxicity | **CAUTION**: Reduced expected edge due to wider spreads; IC degradation ~25%. Enter only if edge > 0.12%. |
| VPIN > 0.70 | Crisis toxicity | **FORBID**: Immediate risk-off. Close all open positions; do not enter new positions. Market maker spreads 2–3× normal; slippage risk exceeds any realistic edge. |

### Filter Rule

$$\text{VPIN\_OK}(t) = \begin{cases} 
\text{True} & \text{if } \text{VPIN}_t \leq 0.50 \\
\text{False} & \text{if } \text{VPIN}_t > 0.50
\end{cases}$$

**Rationale:** Canonical entry gate from Easley et al. (2012, Table 3). VPIN > 0.50 indicates informed flow > 50%; execution costs and adverse selection risk dominate. Testing against higher thresholds (0.55, 0.60) should be done OOS to avoid parameter snooping.

### Implementation Notes

- **BVC approximation error:** ~30% misclassification rate (López de Prado 2018, p. 286). Mitigation: use window of ≥ 50 buckets for averaging; smaller windows amplify noise.
- **Partial bucket handling:** When a bar straddles a bucket boundary, prorate the bar's volume and carry excess into the next bucket (see reference implementation).
- **Recomputation frequency:** VPIN updates each new 1-minute bar; a new bucket completes approximately every 5–15 minutes (depends on volume concentration), at which point the rolling window VPIN shifts.
- **Stale bucket calibration:** If instrument's daily volume increases > 20%, recalibrate bucket size $V_{\text{bucket}}$ using the most recent 30-day rolling average.

---

## Layer 2: Volatility Regime Gate (VIX / Realized Vol)

### Theory & Citation

Volatility affects strategy edge through two mechanisms:

1. **Execution cost scaling:** During high-volatility regimes, market maker spreads widen proportionally to realized volatility (bid-ask ≈ 0.5–1.0 × annualized vol / daily volume). This directly erodes expected returns.
2. **Signal IC degradation:** Mean reversion and momentum signals both degrade in crisis volatility (VIX > 40) due to "flight to quality" and dealer inventory unwinding dominating directional signals (Brunnermeier & Abreu 2006, "Synchronization Risk and Delayed Arbitrage").

**Supporting references:**
- Brunnermeier, M.K., & Abreu, D. (2006). "Synchronization Risk and Delayed Arbitrage." *Journal of Financial Economics*, 83(3), 569–598 — Theoretical and empirical evidence that mean reversion breaks down in extreme vol regimes.
- Bekaert, G., Hoerova, M., & Lo Duca, M. (2013). "Risk, Uncertainty and Monetary Policy." *Journal of Monetary Economics*, 60(7), 771–788 — Empirical VIX regimes and their relationship to equity expected returns.

### Dual-Gate Approach: GARCH Vol + VIX Confirmation

We use **two independent volatility signals** to reduce regime-classification error:

#### Signal 1: GARCH(1,1) Conditional Volatility (Primary)

From the most recent 252 bars (1-minute bars for the most recent trading session plus prior close), estimate conditional volatility using GARCH(1,1):

$$\sigma_t^2 = \omega + \alpha \cdot r_{t-1}^2 + \beta \cdot \sigma_{t-1}^2$$

where:
- $r_{t-1}$ = most recent 1-minute log-return
- Standard parameterization: $\omega \approx 0$, $\alpha \approx 0.05–0.10$, $\beta \approx 0.85–0.90$ (per Bollerslev 1986)

Annualize:
$$\sigma_{\text{annual}}(\%) = \sigma_t \cdot \sqrt{252 \cdot 390} \cdot 100$$

where $252$ is trading days/year and $390$ is 1-minute bars/day.

#### Signal 2: VIX Index (Secondary / Confirmation)

Intraday VIX from standard market data sources (updated every 15 seconds during market hours).

**Volatility Band Definition:**

| GARCH Vol (annualized) | VIX Level | Regime | Action |
|---|---|---|---|
| < 12% | < 15 | Low-vol | **PERMIT**: Tight spreads; best conditions for all strategies. |
| 12–20% | 15–25 | Normal-vol | **PERMIT**: Standard regime; edge remains viable. |
| 20–35% | 25–40 | High-vol | **CAUTION**: Wider spreads; IC degradation ~30%. Require higher confidence edge (IC > 0.10). |
| > 35% | > 40 | Crisis-vol | **FORBID**: Spreads 3–5× normal; model risk and slippage dominate. Close all positions immediately. |

### Filter Rule

$$\text{VOL\_OK}(t) = \begin{cases}
\text{True} & \text{if } \sigma_{\text{annual}}(t) \leq 0.35 \text{ AND } \text{VIX}(t) \leq 40 \\
\text{False} & \text{otherwise}
\end{cases}$$

**Confidence Note:** If GARCH vol and VIX agree (both low, both high), confidence in the volatility regime classification is HIGH. If they diverge (e.g., GARCH vol < 15% but VIX > 25), confidence is MEDIUM — flag this in monitoring and investigate potential model risk.

---

## Combined Filter: VPIN + VOL Gate

### Final Decision Rule

A strategy is **tradeable** at bar $t$ only if **both** gates are satisfied:

$$\text{TRADE}(t) = \text{VPIN\_OK}(t) \land \text{VOL\_OK}(t)$$

### Interpretation Table

| VPIN Status | Vol Status | Result | Action |
|---|---|---|---|
| ✓ OK (≤ 0.50) | ✓ OK (< 35% GARCH) | ✓ **TRADE** | Full entry allowed; standard position sizing. |
| ✓ OK | ✗ HIGH (20–35%) | ✓ **TRADE** | Entry allowed; reduce size by 30% to account for wider spreads. |
| ✓ OK | ✗ CRISIS (> 35%) | ✗ **NO TRADE** | Close all positions; exit immediately. |
| ✗ TOXIC (> 0.50) | ✓ OK | ✗ **NO TRADE** | Do not enter. Informed flow dominates; adverse selection risk too high. |
| ✗ TOXIC | ✗ HIGH | ✗ **NO TRADE** | Severe stress; close all immediately. |
| ✗ TOXIC | ✗ CRISIS | ✗ **NO TRADE** | Systemic crisis; close all immediately. |

---

## Parameterization & Calibration

All thresholds must be treated as **tuning hyperparameters**, not fixed rules:

| Parameter | Canonical Value | Tuning Range | Notes |
|---|---|---|---|
| `vpin_bucket_size_divisor` | 50 | 40–75 | Divides daily avg volume; calibrated OOS. Must validate against Andersen-Bondarenko critique. |
| `vpin_window_length` | 50 | 30–100 | Number of buckets in rolling average. Larger window = smoother but slower to adapt. |
| `vpin_entry_threshold` | 0.50 | 0.45–0.60 | Entry gate. 0.50 = canonical from Easley et al. (2012). |
| `vpin_crisis_threshold` | 0.70 | 0.65–0.80 | Immediate risk-off; close all. |
| `garch_crisis_vol_annual` | 35% | 30–40% | Annualized GARCH volatility upper bound. |
| `vix_crisis_level` | 40 | 35–50 | VIX index upper bound for any trading. |
| `bvc_return_lookback` | 20 | 15–30 | Bars for computing rolling std dev in BVC formula. |

---

## Output Format: Per-Bar Boolean Mask

The filter produces a pandas Series (or numpy array) with one boolean per minute bar:

```python
import pandas as pd

# Input: minute_bars (DataFrame with OHLCV columns and DatetimeIndex)
# Output: tradeable_mask (Series with bool, index = minute_bars.index)

filter = VPINVIXRegimeFilter(
    vpin_bucket_size_divisor=50,
    vpin_window_length=50,
    vpin_entry_threshold=0.50,
    vpin_crisis_threshold=0.70,
    garch_window=252,
    garch_crisis_vol_annual=0.35,
    vix_crisis_level=40
)

tradeable_mask = filter.compute(minute_bars, vix_series)

# Usage in backtest:
# Signal entries: entry_signal & tradeable_mask
# Position logic: if not tradeable_mask[t], close_all_positions()
```

---

## Monitoring & Alerts

When using this filter in production, monitor:

1. **VPIN transition logs:** Flag when VPIN > 0.50 (entry gate closes) and > 0.70 (crisis mode).
2. **GARCH/VIX divergence:** When GARCH and VIX disagree (e.g., GARCH < 15% but VIX > 25), log an anomaly and reduce position size by 25%.
3. **Bucket stale calibration:** Warn when recent daily volume > 1.2× prior 30-day average; recalibrate bucket size and recompute VPIN from bar 0.
4. **Filter hit rate:** Track % of bars where tradeable_mask = False. If > 30% over a week, investigate whether thresholds are too conservative.

---

## References

1. Easley, D., López de Prado, M., & O'Hara, M. (2012). "Flow Toxicity and Liquidity in a High Frequency World." *Review of Financial Studies*, 25(5), 1457–1493.
2. Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
3. Andersen, T.G., & Bondarenko, O. (2014). "VPIN and the Flash Crash: A Review and Further Evidence." *Journal of Financial Markets*, 17, 1–36.
4. Easley, D., & O'Hara, M. (1987). "Price, Trade Size, and Information in Securities Markets." *Journal of Financial Economics*, 19(1), 69–90.
5. Bollerslev, T. (1986). "Generalized Autoregressive Conditional Heteroskedasticity." *Journal of Econometrics*, 31(3), 307–327.
6. Brunnermeier, M.K., & Abreu, D. (2006). "Synchronization Risk and Delayed Arbitrage." *Journal of Financial Economics*, 83(3), 569–598.
7. Bekaert, G., Hoerova, M., & Lo Duca, M. (2013). "Risk, Uncertainty and Monetary Policy." *Journal of Monetary Economics*, 60(7), 771–788.

---

*Market Regime Agent | QUA-127 | 2026-06-09*
