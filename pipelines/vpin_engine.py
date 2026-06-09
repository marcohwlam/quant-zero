"""
Bulk Volume Classification (BVC) + rolling VPIN engine.
Based on Lopez de Prado (2018), Chapter 19.
"""

import pandas as pd
import numpy as np
from scipy.stats import norm

from pipelines.minute_bar_store import MinuteBarStore


class VPINEngine:
    """Computes BVC-based order flow imbalance and VPIN."""

    def compute_bvc(self, bars: pd.DataFrame, sigma_window: int = 50) -> pd.DataFrame:
        """
        Bulk Volume Classification.

        Input: DataFrame with [close, volume] columns.
        Adds:
          price_change     — close[t] - close[t-1]
          sigma_close      — rolling std of price_change (lagged to avoid lookahead)
          z_score          — price_change / sigma_close
          buy_vol          — volume * Phi(z_score)
          sell_vol         — volume * (1 - Phi(z_score))
          order_imbalance  — buy_vol - sell_vol
        Returns augmented DataFrame.

        NOTE: sigma_close uses .shift(1) so current bar's change is not included in the σ
        estimate used to classify that same bar (no lookahead).
        """
        df = bars.copy()

        df["price_change"] = df["close"].diff()

        # σ computed on past bars only (shift(1) ensures current change excluded)
        df["sigma_close"] = df["price_change"].rolling(sigma_window, min_periods=2).std().shift(1)

        # Stable Z: replace zero/nan sigma with running std up to that point
        fallback_sigma = df["price_change"].expanding(min_periods=2).std()
        sigma = df["sigma_close"].fillna(fallback_sigma).replace(0, fallback_sigma)
        sigma = sigma.replace(0, np.nan)  # if truly zero, leave z as nan → Phi(nan)=0.5

        df["sigma_close"] = sigma
        df["z_score"] = df["price_change"] / sigma

        phi_z = df["z_score"].apply(lambda z: norm.cdf(z) if pd.notna(z) else 0.5)
        df["buy_vol"] = df["volume"] * phi_z
        df["sell_vol"] = df["volume"] * (1 - phi_z)
        df["order_imbalance"] = df["buy_vol"] - df["sell_vol"]

        return df

    def compute_vpin(self, bars: pd.DataFrame, window: int = 50) -> pd.Series:
        """
        Compute rolling VPIN from BVC-augmented bars.

        Input: DataFrame with buy_vol and sell_vol columns (output of compute_bvc).
        Returns: pd.Series of VPIN ∈ [0, 1].

        Formula: VPIN[t] = rolling_mean(|buy_vol - sell_vol| / volume, window)
        """
        if "buy_vol" not in bars.columns or "sell_vol" not in bars.columns:
            raise ValueError("bars must be BVC-augmented; call compute_bvc first")

        imbalance_ratio = np.abs(bars["buy_vol"] - bars["sell_vol"]) / bars["volume"].replace(0, np.nan)
        vpin = imbalance_ratio.rolling(window, min_periods=1).mean()
        return vpin.rename("vpin")

    def get_vpin(
        self,
        symbol: str,
        timestamp: str,
        window: int,
        store: MinuteBarStore,
    ) -> float:
        """
        Return VPIN scalar at `timestamp` for `symbol`.

        Loads 2x window bars for warmup, computes BVC + VPIN, returns last value.
        timestamp: ISO8601 UTC string.
        """
        ts_end = pd.Timestamp(timestamp, tz="UTC")

        # Fetch enough history for sigma warmup and VPIN window
        lookback_bars = window * 2 + 50
        # Approximate: 1 bar/min × lookback_bars minutes
        ts_start = ts_end - pd.Timedelta(minutes=lookback_bars)
        start = ts_start.strftime("%Y-%m-%dT%H:%M:%SZ")

        bars = store.get_bars(symbol, start, timestamp)
        if bars.empty:
            raise ValueError(f"No bars for {symbol} between {start} and {timestamp}")

        bvc = self.compute_bvc(bars)
        vpin_series = self.compute_vpin(bvc, window=window)
        return float(vpin_series.iloc[-1])

    def classify_regime(self, vpin: float) -> str:
        """
        Map VPIN scalar to market regime label.

        Thresholds from MKB-006:
          > 0.7   → crisis         (close positions)
          0.5–0.7 → directional
          0.3–0.5 → mixed
          < 0.3   → mean_reversion (favors H60)
        """
        if vpin > 0.7:
            return "crisis"
        if vpin > 0.5:
            return "directional"
        if vpin > 0.3:
            return "mixed"
        return "mean_reversion"
