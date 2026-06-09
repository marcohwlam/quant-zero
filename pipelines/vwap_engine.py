"""
Session-scoped VWAP engine.
VWAP resets at 09:30 ET each trading day (handles DST via zoneinfo).
"""

from zoneinfo import ZoneInfo
from datetime import timezone

import pandas as pd
import numpy as np

from pipelines.minute_bar_store import MinuteBarStore

_ET = ZoneInfo("America/New_York")
_UTC = timezone.utc

# 09:30 ET in (hour, minute) — constant regardless of DST
_SESSION_OPEN_ET = (9, 30)


def _is_session_open(ts_utc: pd.Timestamp) -> bool:
    """True if ts_utc is at the 09:30 ET session boundary (first bar of the day)."""
    ts_et = ts_utc.astimezone(_ET)
    return ts_et.hour == _SESSION_OPEN_ET[0] and ts_et.minute == _SESSION_OPEN_ET[1]


def _session_label(ts_utc: pd.Timestamp) -> str:
    """Return 'YYYY-MM-DD' ET date for a UTC timestamp — groups bars into trading sessions."""
    return ts_utc.astimezone(_ET).strftime("%Y-%m-%d")


class VWAPEngine:
    """Computes session VWAP and VWAP-deviation signals from minute bars."""

    def compute_session_vwap(self, bars: pd.DataFrame) -> pd.Series:
        """
        Compute session VWAP for each bar.

        Input: DataFrame with DatetimeIndex (UTC-aware) and columns [close, volume].
              May span multiple sessions.
        Returns: pd.Series of VWAP values indexed same as bars.
        VWAP resets at 09:30 ET each session.
        """
        if bars.empty:
            return pd.Series(dtype=float)

        df = bars[["close", "volume"]].copy()
        df.index = pd.to_datetime(df.index, utc=True)

        # Group by ET calendar date for session scoping
        df["_session"] = df.index.map(_session_label)
        df["_pv"] = df["close"] * df["volume"]

        vwap_vals = pd.Series(index=df.index, dtype=float)
        for session, grp in df.groupby("_session"):
            cum_pv = grp["_pv"].cumsum()
            cum_vol = grp["volume"].cumsum()
            # Avoid divide-by-zero on zero-volume bars
            session_vwap = cum_pv / cum_vol.replace(0, np.nan)
            vwap_vals.loc[grp.index] = session_vwap.values

        return vwap_vals

    def get_vwap(self, symbol: str, timestamp: str, store: MinuteBarStore) -> float:
        """
        Return session VWAP at (and including) `timestamp`.

        timestamp: ISO8601 UTC string.
        Loads all bars from session open (09:30 ET) up to timestamp.
        """
        ts_utc = pd.Timestamp(timestamp, tz="UTC")
        # Find 09:30 ET for that ET calendar day
        ts_et = ts_utc.astimezone(_ET)
        session_open_et = ts_et.replace(hour=9, minute=30, second=0, microsecond=0)
        session_open_utc = session_open_et.astimezone(_UTC)

        start = session_open_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        end = timestamp

        bars = store.get_bars(symbol, start, end)
        if bars.empty:
            raise ValueError(f"No bars for {symbol} between {start} and {end}")

        vwap_series = self.compute_session_vwap(bars)
        return float(vwap_series.iloc[-1])

    def compute_vwap_deviation(self, bars: pd.DataFrame) -> pd.DataFrame:
        """
        Augment bars with VWAP and VWAP-deviation z-score.

        Adds columns:
          vwap          — session VWAP at each bar
          vwap_std      — rolling 20-bar std of (close - vwap)
          vwap_dev_sigma — (close - vwap) / vwap_std
        Returns augmented DataFrame.
        """
        df = bars.copy()
        df.index = pd.to_datetime(df.index, utc=True)

        df["vwap"] = self.compute_session_vwap(df)
        deviation = df["close"] - df["vwap"]
        df["vwap_std"] = deviation.rolling(20, min_periods=1).std()
        df["vwap_dev_sigma"] = deviation / df["vwap_std"].replace(0, np.nan)

        return df
