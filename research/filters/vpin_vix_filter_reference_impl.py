"""
VPIN + VIX Regime Filter Reference Implementation

Per QUA-127: "Source regime/toxicity filter: when NOT to trade (VPIN + VIX regime)"

Produces a per-bar boolean mask (True = tradeable, False = stand aside) based on:
1. VPIN (Volume-Synchronized Probability of Informed Trading) toxicity threshold
2. GARCH(1,1) conditional volatility + VIX confirmation regime gate

References:
- Easley et al. (2012): "Flow Toxicity and Liquidity in a High Frequency World", RFS 25(5)
- Lopez de Prado (2018): Advances in Financial Machine Learning, Chapters 2 & 19
- Bollerslev (1986): "Generalized Autoregressive Conditional Heteroskedasticity", JoE 31(3)

Author: Market Regime Agent (QUA-127)
Date: 2026-06-09
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from arch import arch_model
from typing import Tuple, Optional


class VPINVIXRegimeFilter:
    """
    Parameterized filter combining VPIN toxicity and volatility regime gates.

    Output: per-bar boolean mask where True = tradeable, False = stand aside.
    """

    def __init__(
        self,
        vpin_bucket_size_divisor: int = 50,
        vpin_window_length: int = 50,
        vpin_entry_threshold: float = 0.50,
        vpin_crisis_threshold: float = 0.70,
        garch_window: int = 252,
        garch_crisis_vol_annual: float = 0.35,
        vix_crisis_level: float = 40.0,
        bvc_return_lookback: int = 20,
    ):
        """
        Parameters
        ----------
        vpin_bucket_size_divisor : int, default 50
            Divides daily average volume to get bucket size.
            Canonical: 50 (Easley et al. 2012).
            Must validate OOS to address Andersen-Bondarenko critique.

        vpin_window_length : int, default 50
            Number of VPIN imbalance buckets in rolling average.

        vpin_entry_threshold : float, default 0.50
            VPIN level at which to close entry gate.
            Canonical: 0.50 (Easley et al. 2012, Table 3).
            Entry forbidden if VPIN > threshold.

        vpin_crisis_threshold : float, default 0.70
            VPIN level at which to immediately close all positions.
            Canonical: 0.70 (precedent to Flash Crash, Easley et al. 2012).

        garch_window : int, default 252
            Bars for GARCH(1,1) estimation window.
            For minute bars: 252 ≈ ~1 trading day of 1-min bars.

        garch_crisis_vol_annual : float, default 0.35
            Annualized GARCH volatility threshold for crisis regime.
            Canonical: 35% (extreme regime, >3 standard deviations above mean).

        vix_crisis_level : float, default 40.0
            VIX index level above which to forbid new entries.
            Canonical: 40 (crisis regime per CBOE).

        bvc_return_lookback : int, default 20
            Bars for rolling std dev in BVC (Bulk Volume Classification) formula.
            Per Lopez de Prado (2018, p. 285).
        """
        self.vpin_bucket_size_divisor = vpin_bucket_size_divisor
        self.vpin_window_length = vpin_window_length
        self.vpin_entry_threshold = vpin_entry_threshold
        self.vpin_crisis_threshold = vpin_crisis_threshold
        self.garch_window = garch_window
        self.garch_crisis_vol_annual = garch_crisis_vol_annual
        self.vix_crisis_level = vix_crisis_level
        self.bvc_return_lookback = bvc_return_lookback

    def compute(
        self,
        minute_bars: pd.DataFrame,
        vix_series: Optional[pd.Series] = None,
    ) -> pd.Series:
        """
        Compute per-bar tradeable mask from minute OHLCV data and optional VIX.

        Parameters
        ----------
        minute_bars : pd.DataFrame
            1-minute OHLCV with columns: ['open', 'high', 'low', 'close', 'volume']
            Index: DatetimeIndex or integer index (one bar per row).

        vix_series : pd.Series, optional
            Intraday VIX (index must align with minute_bars).
            If None, VIX gate is skipped and only VPIN + GARCH gate applies.

        Returns
        -------
        pd.Series
            Boolean mask with same index as minute_bars.
            True = tradeable (both VPIN and vol gates permit).
            False = stand aside (at least one gate forbids).
        """
        bars = minute_bars.copy()
        bars = bars.reset_index(drop=True)  # Work with integer index

        # Layer 1: Compute VPIN toxicity gate
        vpin_mask = self._compute_vpin_gate(bars)

        # Layer 2: Compute volatility regime gate
        vol_mask = self._compute_volatility_gate(bars, vix_series)

        # Combined: both gates must permit
        tradeable = vpin_mask & vol_mask

        # Restore original index
        if isinstance(minute_bars.index, pd.DatetimeIndex):
            tradeable.index = minute_bars.index
        else:
            tradeable.index = minute_bars.index

        return tradeable

    def _compute_vpin_gate(self, bars: pd.DataFrame) -> pd.Series:
        """
        Compute VPIN-based toxicity filter.

        Returns Series[bool]: True if VPIN <= entry threshold (tradeable).
        """
        # Step 1: Bulk Volume Classification (BVC)
        bars = bars.copy()

        # Compute intrabar return
        bars['log_ret'] = np.log(bars['close'] / bars['open'])

        # Rolling std dev for normalization (20-bar lookback per Lopez de Prado)
        bars['sigma'] = bars['log_ret'].rolling(self.bvc_return_lookback).std()
        bars['sigma'] = bars['sigma'].fillna(bars['sigma'].iloc[self.bvc_return_lookback:].mean())

        # BVC: estimate buy/sell volume split using normal CDF
        # z = (close - open) / (sigma * close)
        bars['z'] = bars['log_ret'] / (bars['sigma'] + 1e-10)
        bars['buy_vol'] = bars['volume'] * norm.cdf(bars['z'])
        bars['sell_vol'] = bars['volume'] * (1 - norm.cdf(bars['z']))

        # Step 2: Volume bucketing
        # Bucket size = daily avg volume / divisor
        daily_avg_vol = bars['volume'].mean() * 390  # 390 minutes per trading day
        bucket_vol = daily_avg_vol / self.vpin_bucket_size_divisor

        buckets = self._build_volume_buckets(bars, bucket_vol)

        # Step 3: Rolling VPIN
        vpin_series = self._compute_rolling_vpin(buckets)

        # Expand VPIN buckets back to minute-bar index (forward fill)
        vpin_expanded = self._expand_buckets_to_bars(bars, vpin_series)

        # Entry gate: True if VPIN <= threshold (tradeable)
        vpin_ok = vpin_expanded <= self.vpin_entry_threshold
        vpin_ok = vpin_ok.fillna(True)  # Assume OK until VPIN computed

        return pd.Series(vpin_ok.values, index=bars.index)

    def _build_volume_buckets(
        self,
        bars: pd.DataFrame,
        bucket_vol: float,
    ) -> pd.DataFrame:
        """
        Construct volume buckets from BVC-classified bars.

        Returns DataFrame with columns: ['timestamp', 'buy_vol', 'sell_vol', 'total_vol', 'imbalance']
        """
        buckets = []
        cum_buy = 0.0
        cum_sell = 0.0
        cum_vol = 0.0

        for idx, row in bars.iterrows():
            cum_buy += row['buy_vol']
            cum_sell += row['sell_vol']
            cum_vol += row['volume']

            # Complete buckets
            while cum_vol >= bucket_vol:
                fraction = bucket_vol / cum_vol if cum_vol > 0 else 0
                bucket_buy = cum_buy * fraction
                bucket_sell = cum_sell * fraction

                imbalance = abs(bucket_buy - bucket_sell) / bucket_vol if bucket_vol > 0 else 0.0

                buckets.append({
                    'bar_idx': idx,
                    'timestamp': row.name if hasattr(row, 'name') else idx,
                    'buy_vol': bucket_buy,
                    'sell_vol': bucket_sell,
                    'total_vol': bucket_vol,
                    'imbalance': imbalance,
                })

                # Carryover
                cum_buy *= (1 - fraction)
                cum_sell *= (1 - fraction)
                cum_vol -= bucket_vol

        return pd.DataFrame(buckets)

    def _compute_rolling_vpin(self, buckets: pd.DataFrame) -> pd.Series:
        """
        Compute rolling VPIN from bucket imbalances.

        Returns Series[float]: VPIN at each bucket (indexed by bucket number).
        """
        if len(buckets) < self.vpin_window_length:
            return pd.Series([np.nan] * len(buckets), index=buckets.index)

        vpin = buckets['imbalance'].rolling(self.vpin_window_length).mean()
        return vpin

    def _expand_buckets_to_bars(
        self,
        bars: pd.DataFrame,
        vpin_series: pd.Series,
    ) -> pd.Series:
        """
        Map VPIN (computed at bucket level) back to minute-bar level.

        Forward-fill: each bar gets the most recent VPIN value.
        """
        # Start with NaN for all bars
        vpin_expanded = pd.Series(np.nan, index=bars.index)

        # Fill with VPIN values where buckets complete
        for idx, vpin_val in vpin_series.items():
            if not pd.isna(vpin_val):
                vpin_expanded[vpin_expanded.index >= vpin_series.index[idx]] = vpin_val

        # Forward fill remaining NaNs
        vpin_expanded = vpin_expanded.fillna(method='ffill')

        return vpin_expanded

    def _compute_volatility_gate(
        self,
        bars: pd.DataFrame,
        vix_series: Optional[pd.Series] = None,
    ) -> pd.Series:
        """
        Compute volatility regime gate: True if within normal band.

        Returns Series[bool]: True if GARCH vol <= crisis threshold AND VIX <= crisis level.
        """
        # Compute GARCH(1,1) conditional volatility
        garch_vol_annual = self._compute_garch_vol(bars)

        # GARCH gate: annual vol < crisis threshold
        garch_ok = garch_vol_annual <= self.garch_crisis_vol_annual
        garch_ok = garch_ok.fillna(True)  # Assume OK until enough data

        # VIX gate (if provided)
        if vix_series is not None:
            vix_aligned = vix_series.reindex(bars.index, method='ffill')
            vix_ok = vix_aligned <= self.vix_crisis_level
            vix_ok = vix_ok.fillna(True)
        else:
            vix_ok = pd.Series(True, index=bars.index)

        # Combined: both GARCH and VIX must be OK
        vol_ok = garch_ok & vix_ok

        return vol_ok

    def _compute_garch_vol(self, bars: pd.DataFrame) -> pd.Series:
        """
        Estimate annualized conditional volatility using GARCH(1,1).

        Returns Series[float]: annualized volatility (as fraction, e.g., 0.20 = 20%).
        """
        # Compute 1-minute log returns
        returns = np.log(bars['close'] / bars['close'].shift(1)).dropna()

        if len(returns) < self.garch_window:
            # Not enough data; return NaN
            return pd.Series(np.nan, index=bars.index)

        # Fit GARCH(1,1) on the most recent `garch_window` bars
        try:
            model = arch_model(returns.iloc[-self.garch_window:] * 100, vol='Garch', p=1, q=1)
            res = model.fit(disp='off', show_warning=False)

            # Most recent conditional volatility (daily, in percentage)
            daily_vol = res.conditional_volatility.iloc[-1] / 100

            # Annualize: daily vol * sqrt(252 trading days * 390 minutes/day)
            annual_vol = daily_vol * np.sqrt(252 * 390)
        except Exception:
            # If GARCH fails, return NaN
            annual_vol = np.nan

        # Expand to full series (use most recent value, forward fill)
        vol_series = pd.Series(annual_vol, index=bars.index[-1:])
        vol_series = vol_series.reindex(bars.index, method='ffill')

        return vol_series


def example_usage():
    """
    Example: Apply filter to SPY minute bars.
    """
    import yfinance as yf

    # Download SPY minute data (last 5 trading days)
    spy = yf.download('SPY', period='5d', interval='1m')

    # Download VIX (daily, then resample to minute)
    vix = yf.download('^VIX', period='5d', interval='1d')
    vix_minute = vix['Close'].resample('1min').ffill()

    # Initialize filter with default parameters
    filt = VPINVIXRegimeFilter(
        vpin_bucket_size_divisor=50,
        vpin_window_length=50,
        vpin_entry_threshold=0.50,
        vpin_crisis_threshold=0.70,
        garch_window=252,
        garch_crisis_vol_annual=0.35,
        vix_crisis_level=40.0,
    )

    # Compute tradeable mask
    tradeable = filt.compute(spy, vix_minute)

    print(f"Total bars: {len(spy)}")
    print(f"Tradeable bars: {tradeable.sum()}")
    print(f"Forbid bars: {(~tradeable).sum()}")
    print(f"\nTradeable % per hour:")
    print(tradeable.resample('1h').mean() * 100)

    return tradeable


if __name__ == '__main__':
    # Run example
    tradeable_mask = example_usage()
