"""
Universe / Liquidity Filter — Layer 3 of the minute-level pipeline.

Filters an asset universe down to eligible names per rebalance bar.
Thresholds are grounded in:
  - Kyle (1985) price impact (ADV floor)
  - Almgren & Chriss (2000) temporary impact cost stack (spread ceiling)
See workflow-contracts/workspace/universe-filter-spec.md for full derivation.

Usage:
    eligible = filter_universe(snapshot_df)
    eligible_with_custom = filter_universe(snapshot_df, adv_floor=50_000_000)
"""

from __future__ import annotations

import pandas as pd

# ── Default thresholds (working targets from spec §Universe Filter Specification)
# Override per strategy via constructor args or filter_universe() kwargs.
DEFAULT_ADV_FLOOR_USD = 10_000_000       # $10M/day (Kyle λ-derived)
DEFAULT_SPREAD_MAX_BPS = 10.0            # 10 bps quoted (range-proxy; see spec §Limitations)
DEFAULT_MKTCAP_FLOOR_USD = 500_000_000   # $500M market cap (mid-cap floor)
DEFAULT_MIN_DATA_DAYS = 20               # out of 30 trailing days (data quality gate)


class UniverseFilter:
    """
    Stateless per-rebalance filter. Instantiate once; call filter() each bar.

    Parameters
    ----------
    adv_floor_usd : float
        Minimum 30-day average daily dollar volume to be eligible.
    spread_max_bps : float
        Maximum 30-day average quoted spread in basis points.
        Note: yfinance proxy uses daily range / 2; see spec for limitations.
    mktcap_floor_usd : float
        Minimum market capitalization.
    min_data_days : int
        Minimum trading days with price data in the trailing 30-day window.
    exclusions : set[str] | None
        Static exclusion list (halted, delisted, restricted tickers).
    """

    def __init__(
        self,
        adv_floor_usd: float = DEFAULT_ADV_FLOOR_USD,
        spread_max_bps: float = DEFAULT_SPREAD_MAX_BPS,
        mktcap_floor_usd: float = DEFAULT_MKTCAP_FLOOR_USD,
        min_data_days: int = DEFAULT_MIN_DATA_DAYS,
        exclusions: set[str] | None = None,
    ) -> None:
        self.adv_floor_usd = adv_floor_usd
        self.spread_max_bps = spread_max_bps
        self.mktcap_floor_usd = mktcap_floor_usd
        self.min_data_days = min_data_days
        self.exclusions: set[str] = exclusions or set()

    def filter(self, snapshot: pd.DataFrame) -> pd.DataFrame:
        """
        Return eligible subset of the universe snapshot for one rebalance bar.

        Parameters
        ----------
        snapshot : pd.DataFrame
            One row per asset. Required columns:
              ticker         str    — asset identifier
              adv_30d_usd    float  — 30-day avg daily dollar volume
              spread_bps     float  — 30-day avg spread proxy (bps)
              market_cap_usd float  — latest market cap ($)
              data_days_30d  int    — trading days with data in last 30 days
            Optional:
              ipo_days_ago   int    — days since IPO (equities; filters < 126 days)

        Returns
        -------
        pd.DataFrame
            Filtered subset, same schema as input, with a boolean column
            `eligible` (always True) and a `filter_reason` column (always None
            for returned rows — useful when called via filter_with_reasons()).
        """
        required = {"ticker", "adv_30d_usd", "spread_bps", "market_cap_usd", "data_days_30d"}
        missing = required - set(snapshot.columns)
        if missing:
            raise ValueError(f"snapshot missing required columns: {missing}")

        mask = (
            (snapshot["adv_30d_usd"] >= self.adv_floor_usd)
            & (snapshot["spread_bps"] <= self.spread_max_bps)
            & (snapshot["market_cap_usd"] >= self.mktcap_floor_usd)
            & (snapshot["data_days_30d"] >= self.min_data_days)
            & (~snapshot["ticker"].isin(self.exclusions))
        )

        if "ipo_days_ago" in snapshot.columns:
            mask = mask & (snapshot["ipo_days_ago"] >= 126)

        eligible = snapshot.loc[mask].copy()
        eligible["eligible"] = True
        eligible["filter_reason"] = None
        return eligible.reset_index(drop=True)

    def filter_with_reasons(self, snapshot: pd.DataFrame) -> pd.DataFrame:
        """
        Return all assets with eligibility flag and rejection reason.

        Useful for audit logs and threshold calibration — lets the caller see
        how many assets each threshold rejects without having to run multiple
        passes.

        Returns
        -------
        pd.DataFrame
            Full snapshot with columns added:
              eligible      bool   — True if all gates pass
              filter_reason str    — first-failing gate label, or None if eligible
        """
        required = {"ticker", "adv_30d_usd", "spread_bps", "market_cap_usd", "data_days_30d"}
        missing = required - set(snapshot.columns)
        if missing:
            raise ValueError(f"snapshot missing required columns: {missing}")

        result = snapshot.copy()
        result["eligible"] = True
        result["filter_reason"] = None

        # Apply gates in priority order; first failure sets the reason.
        _set_reason(result, ~result["ticker"].isin(self.exclusions), "exclusion_list")
        _set_reason(result, result["data_days_30d"] >= self.min_data_days, "insufficient_data")
        _set_reason(result, result["adv_30d_usd"] >= self.adv_floor_usd, "adv_below_floor")
        _set_reason(result, result["spread_bps"] <= self.spread_max_bps, "spread_above_max")
        _set_reason(result, result["market_cap_usd"] >= self.mktcap_floor_usd, "mktcap_below_floor")

        if "ipo_days_ago" in snapshot.columns:
            _set_reason(result, result["ipo_days_ago"] >= 126, "ipo_too_recent")

        result["eligible"] = result["filter_reason"].isna()
        return result


def _set_reason(df: pd.DataFrame, passing_mask: pd.Series, reason: str) -> None:
    """Mark first-failing gate; leave already-failed rows unchanged."""
    failing = ~passing_mask
    untagged = df["filter_reason"].isna()
    df.loc[failing & untagged, "filter_reason"] = reason


def filter_universe(
    snapshot: pd.DataFrame,
    adv_floor_usd: float = DEFAULT_ADV_FLOOR_USD,
    spread_max_bps: float = DEFAULT_SPREAD_MAX_BPS,
    mktcap_floor_usd: float = DEFAULT_MKTCAP_FLOOR_USD,
    min_data_days: int = DEFAULT_MIN_DATA_DAYS,
    exclusions: set[str] | None = None,
) -> pd.DataFrame:
    """
    Functional convenience wrapper around UniverseFilter.filter().

    Returns the eligible subset only (no filter_reason column).
    Use UniverseFilter().filter_with_reasons() for audit output.
    """
    return UniverseFilter(
        adv_floor_usd=adv_floor_usd,
        spread_max_bps=spread_max_bps,
        mktcap_floor_usd=mktcap_floor_usd,
        min_data_days=min_data_days,
        exclusions=exclusions,
    ).filter(snapshot)


def build_snapshot_from_yfinance(tickers: list[str], as_of_date: str) -> pd.DataFrame:
    """
    Construct a universe snapshot DataFrame from yfinance for the given date.

    This is the data-loading half — must be called before filter_universe().
    Returns a DataFrame suitable for passing to filter_universe().

    Parameters
    ----------
    tickers : list[str]
        Ticker symbols to fetch.
    as_of_date : str
        ISO date string (YYYY-MM-DD). Data fetched up to this date.

    Notes
    -----
    - spread_bps uses range-based proxy: (30d avg daily range / close) / 2 * 10000
      This overestimates true quoted spread; threshold of 10 bps is calibrated
      for this proxy. See spec §Data Sources for limitation.
    - market_cap from .info['marketCap'] is a point-in-time snapshot, not
      trailing 30d average. Re-fetch at each monthly rebalance.
    """
    import yfinance as yf
    from datetime import datetime, timedelta

    end = datetime.fromisoformat(as_of_date)
    start = end - timedelta(days=45)  # 45 calendar days ≈ ~30 trading days + buffer
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    rows = []
    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(start=start_str, end=end_str, auto_adjust=True)
            info = tk.info

            if hist.empty or len(hist) < 5:
                rows.append(_empty_row(ticker))
                continue

            hist = hist.tail(30)
            data_days = len(hist)
            adv_30d_usd = float((hist["Volume"] * hist["Close"]).mean())
            daily_range_bps = float(
                ((hist["High"] - hist["Low"]) / hist["Close"] * 10000).mean()
            )
            spread_bps = daily_range_bps / 2  # range-proxy; see spec limitation
            market_cap = float(info.get("marketCap") or 0)

            ipo_date = info.get("ipoExpectedDate") or info.get("firstTradeDateEpochUtc")
            ipo_days_ago = None
            if ipo_date:
                try:
                    ipo_dt = (
                        datetime.fromtimestamp(ipo_date)
                        if isinstance(ipo_date, (int, float))
                        else datetime.fromisoformat(str(ipo_date)[:10])
                    )
                    ipo_days_ago = (end - ipo_dt).days
                except Exception:
                    ipo_days_ago = None

            rows.append({
                "ticker": ticker,
                "adv_30d_usd": adv_30d_usd,
                "spread_bps": spread_bps,
                "market_cap_usd": market_cap,
                "data_days_30d": data_days,
                "ipo_days_ago": ipo_days_ago,
            })
        except Exception:
            rows.append(_empty_row(ticker))

    return pd.DataFrame(rows)


def _empty_row(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "adv_30d_usd": 0.0,
        "spread_bps": 9999.0,
        "market_cap_usd": 0.0,
        "data_days_30d": 0,
        "ipo_days_ago": None,
    }


if __name__ == "__main__":
    # Quick smoke test with synthetic data
    test_universe = pd.DataFrame([
        {"ticker": "AAPL", "adv_30d_usd": 15_000_000_000, "spread_bps": 1.2,  "market_cap_usd": 3_000_000_000_000, "data_days_30d": 30},
        {"ticker": "MSFT", "adv_30d_usd": 8_000_000_000,  "spread_bps": 1.5,  "market_cap_usd": 2_800_000_000_000, "data_days_30d": 30},
        {"ticker": "SMID", "adv_30d_usd": 500_000,        "spread_bps": 45.0, "market_cap_usd": 80_000_000,        "data_days_30d": 28},  # fails ADV + spread + mktcap
        {"ticker": "MID1", "adv_30d_usd": 12_000_000,     "spread_bps": 12.0, "market_cap_usd": 600_000_000,       "data_days_30d": 30},  # fails spread only
        {"ticker": "MID2", "adv_30d_usd": 25_000_000,     "spread_bps": 8.0,  "market_cap_usd": 750_000_000,       "data_days_30d": 30},  # passes all
    ])

    print("=== filter_universe (eligible only) ===")
    eligible = filter_universe(test_universe)
    print(eligible[["ticker", "adv_30d_usd", "spread_bps", "market_cap_usd"]])

    print("\n=== filter_with_reasons (all assets) ===")
    uf = UniverseFilter()
    full = uf.filter_with_reasons(test_universe)
    print(full[["ticker", "eligible", "filter_reason"]])
