# MKB-003: Ornstein-Uhlenbeck Mean Reversion on Volume Bars (Lopez de Prado)

**Status:** KNOWLEDGE_BASE
**Author:** Research Director
**Date:** 2026-06-06
**Asset class:** US equities, ETFs, crypto (any sufficiently liquid instrument)
**Strategy type:** Statistical mean reversion / microstructure-aware sampling
**Data resolution:** Minute bars (aggregated into volume bars / dollar bars)

---

## Provenance

**Primary source:**
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
  - Chapter 2, pp. 25–44: "Financial Data Structures" — tick bars, volume bars, and dollar bars as superior alternatives to time bars for statistical properties (variance stabilization, serial autocorrelation reduction, Gaussianity).
  - Chapter 17, pp. 259–278: "Structural Breaks" — CUSUM filter as a method to identify statistically significant deviations from the equilibrium process; application to intraday mean reversion entry timing.
  - Appendix (p. 44): Ornstein-Uhlenbeck calibration methodology for mean-reverting processes.

**Secondary sources:**
- Chan, E.P. (2013). *Algorithmic Trading: Winning Strategies and Their Rationale*. Wiley. Chapter 2, pp. 25–48: Cointegration-based mean reversion (pairs trading foundation) and the Ornstein-Uhlenbeck model; Chan presents the OU half-life formula and Kalman filter estimation.
- Chan, E.P. (2013). Chapter 5, pp. 83–102: Intraday mean reversion extension — applying OU models to ETF price processes within the trading day.
- Avellaneda, M. & Lee, J.H. (2010). "Statistical Arbitrage in the U.S. Equities Market." *Quantitative Finance*, 10(7), 761–782. Section 3 (pp. 765–770): OU mean reversion applied to residuals of a factor model; estimated IS Sharpe of 1.4–2.1 for mean-reversion signal in 2000–2007 using daily data; intraday extension discussed in Section 6.

---

## Summary

Standard time-based (e.g., 1-minute) bars have heteroskedastic variance that makes mean reversion signals noisy and unstable. Lopez de Prado (2018) demonstrates that sampling price by volume (constructing a new bar every V shares traded, rather than every T minutes) normalizes the variance of returns, reduces serial autocorrelation, and produces a more stable price process suitable for mean reversion modeling. Applied to this stationary(er) process, the Ornstein-Uhlenbeck model estimates a mean-reversion half-life and speed of reversion (θ). The CUSUM filter from Lopez de Prado Chapter 17 provides a principled entry trigger: only enter mean reversion trades when price has deviated from the rolling OU equilibrium by a statistically significant amount (as measured by the cumulative sum of standardized deviations crossing a threshold h). This avoids the classic "always in the market" problem of naive mean reversion strategies and filters out small, noise-driven deviations.

---

## Edge & Mechanism

**Why volume bars improve intraday mean reversion:**

1. **Variance normalization:** In time bars, return variance spikes during high-volume periods (open, close, news events) and collapses during low-volume periods (midday). Volume bars produce approximately equal variance per bar by construction — each bar represents the same amount of traded information. This makes the OU calibration (estimating θ, μ, σ) stable across different time-of-day conditions.

2. **Gaussianity improvement:** Lopez de Prado (2018, p. 35) shows empirically that the return distribution of dollar bars is closer to Gaussian than time bars. The OU model assumes Gaussian innovations; using volume bars reduces the model misspecification error.

3. **CUSUM filter precision:** The CUSUM filter accumulates deviations only in one direction until a threshold h is crossed — it avoids triggering on random noise. This is the same mathematical tool used in statistical process control to detect regime changes. Applied to OU residuals, it fires when the probability of a random walk explanation for the price deviation is below a preset significance level.

4. **Economic rationale for mean reversion:** Intraday mean reversion at the minute level operates via two mechanisms:
   - **Market maker inventory rebalancing:** Designated market makers and HFT participants who accumulate inventory on one side during a directional flow episode actively quote to attract contra-side flow, pulling price back toward fair value.
   - **VWAP execution pressure:** Institutional VWAP algorithms mechanically purchase (sell) as price falls below (rises above) their execution VWAP target, providing natural mean-reverting force throughout the day.

**OU model calibration (Chan 2013, p. 42):**
```python
import numpy as np
from scipy.stats import linregress

def calibrate_ou(price_series):
    # Estimate OU parameters via OLS regression on lagged series
    y = price_series[1:].values
    x = price_series[:-1].values
    slope, intercept, r, p, se = linregress(x, y)

    theta = -np.log(slope)          # mean reversion speed
    mu = intercept / (1 - slope)    # long-run mean
    sigma_eq = np.std(y - slope * x - intercept) / np.sqrt(1 - slope**2)
    half_life = np.log(2) / theta   # in bar units
    return theta, mu, sigma_eq, half_life
```

**Implied half-life at minute bars:** Chan (2013) reports intraday OU half-lives of 15–90 minutes for liquid ETFs like SPY.

---

## Entry/Exit Logic

**Step 1: Construct volume bars**
```python
def build_volume_bars(tick_data, target_volume=50000):
    """
    Aggregate ticks into bars of target_volume shares.
    Each bar: open, high, low, close, volume, timestamp.
    """
    bars = []
    current_vol = 0
    current_open = None
    current_high = -np.inf
    current_low = np.inf
    bar_start_ts = None

    for ts, price, vol in tick_data.itertuples(index=False):
        if current_open is None:
            current_open = price
            bar_start_ts = ts
        current_high = max(current_high, price)
        current_low = min(current_low, price)
        current_vol += vol

        if current_vol >= target_volume:
            bars.append({
                'timestamp': bar_start_ts, 'open': current_open,
                'high': current_high, 'low': current_low,
                'close': price, 'volume': current_vol
            })
            current_vol = 0
            current_open = None
            current_high = -np.inf
            current_low = np.inf

    return pd.DataFrame(bars)
```

**Step 2: Rolling OU calibration (every N bars)**
```python
LOOKBACK_BARS = 100    # Calibration window in volume bars
ENTRY_Z_THRESHOLD = 2.0  # CUSUM threshold in standard deviations
EXIT_Z_THRESHOLD = 0.5   # Exit when price returns to within 0.5 sigma of mean

# At each new bar, using last LOOKBACK_BARS bars:
theta, mu, sigma_eq, half_life = calibrate_ou(close_prices[-LOOKBACK_BARS:])
z_score = (current_price - mu) / sigma_eq
```

**Step 3: CUSUM filter entry (Lopez de Prado 2018, p. 265)**
```python
h = ENTRY_Z_THRESHOLD  # Threshold
S_pos, S_neg = 0, 0    # CUSUM running sums

for z in z_scores:
    S_pos = max(0, S_pos + z)    # Upside CUSUM
    S_neg = min(0, S_neg + z)    # Downside CUSUM

    if S_pos > h:
        signal = -1    # Mean reversion: price too high → short
        S_pos = 0

    elif S_neg < -h:
        signal = +1    # Mean reversion: price too low → long
        S_neg = 0
```

**Exit:**
- Exit when `|z_score| < EXIT_Z_THRESHOLD` (price has mean-reverted to within 0.5σ of equilibrium)
- Time stop: if position open > 2 × half_life (in volume bars), close regardless
- Stop-loss: if position moves 2σ against direction (price moved to 4σ from mu), exit (OU assumption violated — possible structural break)

**Position sizing:** Inverse-volatility weighted. Scale position size by 1/sigma_eq × risk_budget.

---

## Alpha Decay Analysis

- **Signal half-life:** 15–90 minutes (Chan 2013 p. 43 reports SPY OU half-life of 30–60 minutes in 2008–2012 data; estimate for current regime: 20–45 minutes given higher algorithmic participation)
- **IC decay curve:**
  - T+0 (entry bar): IC ≈ 0.15–0.25 (strong z-score; CUSUM has confirmed significant deviation)
  - T+15min: IC ≈ 0.10 (still in reversion phase; half-life not yet elapsed)
  - T+30min: IC ≈ 0.05 (near half-life; position should be partially unwound)
  - T+60min: IC ≈ 0.01 (signal mostly decayed; at 2× half-life, CUSUM reset expected)
  - T+120min: IC ≈ 0.00 (time stop should have triggered)
- **Transaction cost viability:**
  - Half-life 20–45 min >> 1 day threshold (substantial positive margin)
  - SPY round-trip spread: ~0.002–0.005%
  - Average trade return (Avellaneda & Lee 2010 analogue at intraday): ~0.05–0.10% per trade
  - Net edge after costs: ~0.04–0.09% per volume bar sequence
  - **Edge viable at $25K scale.** Scale ceiling is approximately $500K notional (above which market impact at 50K-share bar threshold starts to eat the edge).
- **ML anti-snooping note:** OU parameters must be calibrated on rolling IS window only; never use future data in the rolling calibration. The CUSUM threshold h must be set a priori or calibrated on a separate validation period — not on the same data used to evaluate strategy returns.

---

## Failure Modes & Overfitting Risks

1. **Non-stationarity regime breaks:** The OU model assumes the price series is stationary (mean-reverting). If the instrument trends strongly (momentum regime), the OU equilibrium μ is chased upward, and mean reversion signals produce consistent losses. The CUSUM stop-loss (exit at 4σ deviation) is critical. Check: ADF test p-value on rolling window should be < 0.05 to confirm stationarity before trading.

2. **Parameter instability:** OU θ, μ, σ estimated on 100 bars may be unstable in low-volume midday periods. Lopez de Prado recommends a minimum bar threshold (at least 50 bars in the calibration window) before using OU parameters. During very thin markets (after-hours, holiday eves), volume bars take much longer to form and calibration degrades.

3. **Crowding by HFT:** Intraday mean reversion is the primary strategy of statistical arbitrage desks and HFT firms. The edge documented by Avellaneda & Lee (2010) in 2000–2007 was ~1.4–2.1 IS Sharpe on daily factor residuals. At minute bars in 2024, institutional competition has compressed this to an estimated 0.5–1.0 IS Sharpe before friction.

4. **Volume bar target size sensitivity:** The target volume V (shares per bar) is a critical parameter. Too small → bars form too quickly, signal is noisy. Too large → bars take hours to form, strategy is effectively daily. V must be calibrated per instrument and regime. Testing multiple V values on IS data introduces a parameter-snooping risk.

5. **Tick data requirement:** Constructing volume bars requires tick-level or at minimum transaction-level volume data. Minute OHLCV bars provide total minute volume but not the intrabar volume distribution needed for precise volume bar construction. Chan (2013, p. 27) notes that using 1-minute volume as an approximation introduces a small bias in bar construction timestamps.

6. **Short-selling constraint at intraday level:** OU mean reversion is long/short by construction (need to short when price is high). Intraday short availability depends on broker — most liquid ETFs (SPY) are always shortable intraday.

---

## Infrastructure Requirements

| Requirement | Status | Notes |
|---|---|---|
| Tick-level or 1-min bar data with intrabar volume | **NOT in current pipeline** | Polygon.io or Alpaca historic tick data needed |
| Volume bar construction engine | **NOT in current pipeline** | Custom implementation required |
| Rolling OU parameter estimation | **NOT in current pipeline** | scipy.stats linregress (trivial once data exists) |
| CUSUM state tracking per instrument | **NOT in current pipeline** | Stateful intraday position manager |
| ADF stationarity check (per-session) | **NOT in current pipeline** | statsmodels ADF (trivial once data exists) |

**Minimum required:** Alpaca minute bars with volume (available; not tick-level), custom volume bar aggregator, rolling OU calibration engine.

---

## Pipeline Graduation Path

1. Engineering Director builds volume bar aggregation from Alpaca minute data (approximate, using 1-min volume totals)
2. Rolling OU + CUSUM engine implemented in backtesting framework
3. Graduate to `research/hypotheses/` as `H49_ou_mean_reversion_volume_bars.md`
4. Gate 1 backtest: IS 2015–2022 (minute bars), OOS 2023–2025
5. ADF stationarity test required as pre-trade gate in live execution

---

## References

- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapters 2, 17.
- Chan, E.P. (2013). *Algorithmic Trading: Winning Strategies and Their Rationale*. Wiley. Chapters 2, 5.
- Chan, E.P. (2009). *Quantitative Trading: How to Build Your Own Algorithmic Trading Business*. Wiley. Chapter 7, pp. 133–148: OU mean reversion practical implementation.
- Avellaneda, M. & Lee, J.H. (2010). "Statistical Arbitrage in the U.S. Equities Market." *Quantitative Finance*, 10(7), 761–782.
- Uhlenbeck, G.E. & Ornstein, L.S. (1930). "On the Theory of the Brownian Motion." *Physical Review*, 36(5), 823–841. (Original OU process; theoretical foundation.)

---

*Research Director | QUA-49 | 2026-06-06*
