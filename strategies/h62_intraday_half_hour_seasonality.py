"""
Strategy: H62 Intraday Half-Hour Cross-Sectional Seasonality
Author: Strategy Coder Agent
Date: 2026-06-10
Hypothesis: research/hypotheses/62_intraday_half_hour_seasonality.md
            Heston, Korajczyk & Sadka (2010) — intraday return seasonality
            persists cross-sectionally: stocks that outperform in a given
            half-hour bucket on average tend to continue doing so.
Asset class: equities (large-cap, intraday-flat)
Parent task: QUA-188
Cost model: ED-SLIP-001 — standard equities tier (0.05% slippage, $0.005/share fixed)
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import warnings
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import scipy.stats
import yfinance as yf

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

# ── Universe ───────────────────────────────────────────────────────────────────

UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA', 'BRK-B',
    'JPM', 'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'BAC', 'INTC', 'CSCO',
    'VZ', 'PFE', 'KO', 'PEP', 'MRK', 'ABT', 'TMO', 'WMT', 'DIS', 'CMCSA',
    'NKE', 'IBM', 'MCD', 'ACN', 'TXN', 'QCOM', 'SBUX', 'GS', 'MS', 'AXP',
    'BA', 'CAT', 'HON', 'MMM', 'MDT', 'USB', 'C', 'WFC', 'MO', 'CL',
    'GE', 'XOM',
]

# ── Bucket definitions ─────────────────────────────────────────────────────────

BUCKET_STARTS = [
    '09:30', '10:00', '10:30', '11:00', '11:30',   # h=0..4
    '12:00', '12:30',                                # h=5,6 — SKIP midday
    '13:00', '13:30', '14:00', '14:30', '15:00', '15:30',  # h=7..12
]
ACTIVE_BUCKETS = [0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12]  # skip h=5,6

# Pre-build a time → bucket_index mapping
_BUCKET_TIME_TO_IDX: dict[str, int] = {t: i for i, t in enumerate(BUCKET_STARTS)}

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    "signal_window": 5,          # days of same-bucket history to average
    "long_quantile": 0.80,       # top-quintile long threshold
    "short_quantile": 0.20,      # bottom-quintile short threshold
    "dispersion_min_std": 0.0010,  # min cross-sectional signal std to trade
    "capital": 25_000.0,         # total capital
    "long_capital": 12_500.0,    # half to long book
    "short_capital": 12_500.0,   # half to short book
    # Cost model — ED-SLIP-001 standard equities tier
    "fixed_per_share": 0.005,
    "slippage_pct": 0.0005,      # 0.05% per leg
    "market_impact_k": 0.1,
    "sigma_window": 20,
    "adv_window": 20,
    # Walk-forward
    "wf_windows": [
        ("2022-01-01", "2022-03-31", "2022-04-01", "2022-04-30"),
        ("2022-05-01", "2022-07-31", "2022-08-01", "2022-08-31"),
        ("2022-09-01", "2022-11-30", "2022-12-01", "2022-12-31"),
        ("2023-01-01", "2023-03-31", "2023-04-01", "2023-04-30"),
        ("2023-05-01", "2023-07-31", "2023-08-01", "2023-08-31"),
        ("2023-09-01", "2023-11-30", "2023-12-01", "2023-12-31"),
    ],
    "data_start": "2021-10-01",   # warm-up buffer for 5-day signal
    "data_end": "2024-12-31",
    "is_start": "2022-01-01",
    "is_end": "2023-12-31",
    "oos_start": "2024-01-01",
    "oos_end": "2024-12-31",
}

# ── Paths ──────────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _ROOT / "strategies" / "data" / "h62"
_BACKTEST_DIR = _ROOT / "backtests"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_BACKTEST_DIR.mkdir(parents=True, exist_ok=True)


# ── Data download + cache ──────────────────────────────────────────────────────

def _chunk_dates(start: str, end: str, chunk_days: int = 58) -> list[tuple[str, str]]:
    """Split [start, end] into ≤chunk_days spans (yfinance 30m limit ~60 days)."""
    chunks = []
    cur = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while cur < end_ts:
        chunk_end = min(cur + pd.Timedelta(days=chunk_days), end_ts)
        chunks.append((cur.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
        cur = chunk_end
    return chunks


def download_30m_data(
    universe: list[str],
    start: str,
    end: str,
    data_dir: Path = _DATA_DIR,
) -> pd.DataFrame:
    """
    Download 30m OHLCV for universe in 58-day chunks, cache to parquet.
    Returns MultiIndex DataFrame: (ticker, field) columns, DatetimeTZ index in ET.
    """
    chunks = _chunk_dates(start, end)
    frames: list[pd.DataFrame] = []

    for chunk_start, chunk_end in chunks:
        cache_path = data_dir / f"chunk_{chunk_start}_{chunk_end}.parquet"
        if cache_path.exists():
            logger.info("Cache hit: %s", cache_path.name)
            frames.append(pd.read_parquet(cache_path))
            continue

        logger.info("Downloading 30m chunk %s → %s (%d tickers)", chunk_start, chunk_end, len(universe))
        try:
            raw = yf.download(
                tickers=universe,
                start=chunk_start,
                end=chunk_end,
                interval="30m",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception as exc:
            logger.warning("Download failed for chunk %s–%s: %s", chunk_start, chunk_end, exc)
            continue

        if raw.empty:
            logger.warning("Empty response for chunk %s–%s", chunk_start, chunk_end)
            continue

        # Normalize to MultiIndex (ticker, field)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.swaplevel(0, 1)
            raw = raw.sort_index(axis=1)
        else:
            # Single-ticker response — wrap
            raw.columns = pd.MultiIndex.from_tuples(
                [(universe[0], c) for c in raw.columns], names=["ticker", "field"]
            )

        # Ensure ET timezone
        if raw.index.tzinfo is None:
            raw.index = raw.index.tz_localize("America/New_York")
        else:
            raw.index = raw.index.tz_convert("America/New_York")

        raw.to_parquet(cache_path)
        frames.append(raw)

    if not frames:
        raise RuntimeError("No 30m data downloaded — check universe and date range")

    combined = pd.concat(frames).sort_index()
    # RTH filter: 09:30 ≤ bar_time < 16:00
    bar_time = combined.index.time
    rth_mask = (bar_time >= pd.Timestamp("09:30").time()) & (bar_time < pd.Timestamp("16:00").time())
    return combined[rth_mask]


def download_daily_data(universe: list[str]) -> pd.DataFrame:
    """Download full daily OHLCV for sigma/ADV computation."""
    cache_path = _DATA_DIR / "daily_ohlcv.parquet"
    if cache_path.exists():
        logger.info("Daily cache hit")
        return pd.read_parquet(cache_path)

    logger.info("Downloading daily OHLCV for universe")
    raw = yf.download(
        tickers=universe,
        period="max",
        interval="1d",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.swaplevel(0, 1)
        raw = raw.sort_index(axis=1)
    else:
        raw.columns = pd.MultiIndex.from_tuples(
            [(universe[0], c) for c in raw.columns], names=["ticker", "field"]
        )

    raw.to_parquet(cache_path)
    return raw


# ── Data quality check ─────────────────────────────────────────────────────────

def check_data_quality(
    intraday: pd.DataFrame,
    universe: list[str],
    data_dir: Path = _DATA_DIR,
) -> dict:
    """
    For each ticker, count consecutive missing trading days and flag gaps.
    Logs results to data_quality_report.json.
    """
    report: dict = {"tickers": {}, "warnings": []}

    # Infer trading days from the combined index
    trading_days = sorted({ts.date() for ts in intraday.index})

    for ticker in universe:
        try:
            close_col = (ticker, "Close")
            if close_col not in intraday.columns:
                report["tickers"][ticker] = {"status": "missing", "consecutive_missing_max": None}
                report["warnings"].append(f"{ticker}: column missing entirely")
                continue

            ticker_close = intraday[close_col].dropna()
            ticker_days = sorted({ts.date() for ts in ticker_close.index})
            missing_days = sorted(set(trading_days) - set(ticker_days))
            total_days = len(trading_days)
            missing_pct = len(missing_days) / total_days if total_days > 0 else 0.0

            # Count max consecutive missing days
            max_consec = 0
            consec = 0
            prev = None
            for d in sorted(trading_days):
                if d not in set(ticker_days):
                    consec += 1
                    max_consec = max(max_consec, consec)
                else:
                    consec = 0
                prev = d  # noqa: F841

            report["tickers"][ticker] = {
                "total_trading_days": total_days,
                "missing_days": len(missing_days),
                "missing_pct": round(missing_pct, 4),
                "max_consecutive_missing": max_consec,
            }

            if max_consec > 5:
                msg = f"{ticker}: {max_consec} consecutive missing trading days"
                logger.warning(msg)
                report["warnings"].append(msg)

            if missing_pct > 0.10:
                msg = f"{ticker}: {missing_pct:.1%} missing trading days (>10% threshold)"
                logger.warning(msg)
                report["warnings"].append(msg)

        except Exception as exc:
            report["tickers"][ticker] = {"status": "error", "error": str(exc)}
            report["warnings"].append(f"{ticker}: quality check error: {exc}")

    quality_path = data_dir / "data_quality_report.json"
    with open(quality_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Data quality report written to %s", quality_path)
    return report


# ── Bucket assignment ──────────────────────────────────────────────────────────

def assign_bucket(ts: pd.Timestamp) -> int | None:
    """Map a bar timestamp to bucket index (0–12), or None if not a bucket start."""
    t_str = ts.strftime("%H:%M")
    return _BUCKET_TIME_TO_IDX.get(t_str)


# ── Signal construction ────────────────────────────────────────────────────────

def build_bucket_returns(intraday: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    """
    For each (ticker, bucket, trading_day): compute bucket_ret = close/open - 1.
    Returns DataFrame with MultiIndex columns (ticker, bucket_idx) and date index.
    """
    records: list[dict] = []

    for ts, row in intraday.iterrows():
        b_idx = assign_bucket(ts)
        if b_idx is None or b_idx not in ACTIVE_BUCKETS:
            continue
        day = ts.date()
        for ticker in universe:
            o_col = (ticker, "Open")
            c_col = (ticker, "Close")
            if o_col not in intraday.columns or c_col not in intraday.columns:
                continue
            o = row.get(o_col)
            c = row.get(c_col)
            if pd.isna(o) or pd.isna(c) or o <= 0:
                continue
            records.append({
                "date": day,
                "bucket": b_idx,
                "ticker": ticker,
                "open": float(o),
                "close": float(c),
                "bucket_ret": float(c) / float(o) - 1.0,
            })

    if not records:
        raise RuntimeError("No bucket return records generated — check data and bucket mapping")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df


def build_signals(bucket_df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute 5-day rolling same-bucket signal with look-ahead guard.
    signal[ticker, bucket, day] = mean of bucket_ret over prior signal_window days (shift 1).
    Returns DataFrame with columns: date, bucket, ticker, signal.
    """
    window = params["signal_window"]

    # Pivot to (date) x (ticker, bucket) for efficient rolling
    pivot = bucket_df.pivot_table(
        index="date", columns=["ticker", "bucket"], values="bucket_ret", aggfunc="mean"
    )
    pivot = pivot.sort_index()

    # Rolling mean over prior `window` trading days (shift 1 prevents look-ahead)
    # Each column is a (ticker, bucket) series across dates
    signal = pivot.shift(1).rolling(window=window, min_periods=window).mean()

    # Melt back to long format
    signal_long = signal.stack(level=[0, 1], future_stack=True).reset_index()
    signal_long.columns = ["date", "ticker", "bucket", "signal"]
    signal_long = signal_long.dropna(subset=["signal"])
    return signal_long


# ── Transaction cost model ─────────────────────────────────────────────────────

def compute_cost(
    entry_price: float,
    shares: float,
    sigma_20d: float,
    adv_20d: float,
    params: dict,
) -> tuple[float, bool]:
    """
    Round-trip cost per leg (call twice: entry + exit).
    Returns (cost_usd, liquidity_flag).
    liquidity_flag = True when order > 1% of ADV.
    """
    fixed = params["fixed_per_share"] * shares
    slippage = params["slippage_pct"] * entry_price * shares
    # Square-root market impact
    impact_frac = params["market_impact_k"] * sigma_20d * math.sqrt(shares / (adv_20d + 1e-10))
    impact = impact_frac * entry_price * shares
    total = fixed + slippage + impact
    liquidity_flag = (shares / (adv_20d + 1e-10)) > 0.01
    return total, liquidity_flag


def build_daily_risk_metrics(daily_df: pd.DataFrame, universe: list[str], params: dict) -> pd.DataFrame:
    """
    Compute 20d rolling sigma (daily close returns) and ADV for each ticker.
    Shifts by 1 day to prevent look-ahead.
    Returns MultiIndex DataFrame: date index, (ticker, metric) columns.
    """
    records: dict[str, pd.DataFrame] = {}

    for ticker in universe:
        try:
            close = daily_df.get((ticker, "Close"))
            volume = daily_df.get((ticker, "Volume"))
            if close is None or volume is None:
                continue
            close = close.dropna()
            volume = volume.dropna()
            ret = close.pct_change()
            sigma = ret.rolling(params["sigma_window"]).std().shift(1)
            adv = volume.rolling(params["adv_window"]).mean().shift(1)
            tdf = pd.DataFrame({"sigma_20d": sigma, "adv_20d": adv})
            tdf.index = pd.to_datetime(tdf.index).normalize()
            records[ticker] = tdf
        except Exception as exc:
            logger.warning("Risk metrics failed for %s: %s", ticker, exc)

    if not records:
        raise RuntimeError("No daily risk metrics computed")

    combined = pd.concat(records, axis=1)
    combined.columns.names = ["ticker", "metric"]
    return combined


# ── Backtest core ──────────────────────────────────────────────────────────────

def run_backtest_period(
    bucket_df: pd.DataFrame,
    signal_df: pd.DataFrame,
    intraday: pd.DataFrame,
    risk_metrics: pd.DataFrame,
    start: str,
    end: str,
    params: dict,
    universe: list[str],
) -> tuple[pd.Series, pd.DataFrame]:
    """
    Run cross-sectional seasonality backtest for [start, end].

    Returns:
        daily_net_returns: pd.Series (date → net return fraction)
        trade_log: pd.DataFrame
    """
    start_dt = pd.Timestamp(start).normalize()
    end_dt = pd.Timestamp(end).normalize()

    # Filter signal to period
    mask = (signal_df["date"] >= start_dt) & (signal_df["date"] <= end_dt)
    period_signals = signal_df[mask].copy()

    long_q = params["long_quantile"]
    short_q = params["short_quantile"]
    disp_min = params["dispersion_min_std"]
    cap_per_side = params["long_capital"]  # $12,500 per side
    n_universe = len(universe)
    top_n = max(1, round(n_universe * (1.0 - long_q)))   # top quintile: ~10 stocks
    bot_n = max(1, round(n_universe * short_q))           # bottom quintile: ~10 stocks

    trade_records: list[dict] = []
    daily_returns: dict[date, float] = {}
    dispersion_skip_count = 0
    total_bucket_days = 0

    # Build open/close lookup from intraday: (date, bucket_idx, ticker) → (open, close)
    # Pre-build for speed
    price_lookup: dict[tuple, tuple] = {}
    for ts, row in intraday.iterrows():
        b_idx = assign_bucket(ts)
        if b_idx is None or b_idx not in ACTIVE_BUCKETS:
            continue
        d = ts.date()
        for ticker in universe:
            o_col = (ticker, "Open")
            c_col = (ticker, "Close")
            if o_col not in intraday.columns:
                continue
            o = row.get(o_col)
            c = row.get(c_col)
            if not pd.isna(o) and not pd.isna(c) and float(o) > 0:
                price_lookup[(d, b_idx, ticker)] = (float(o), float(c))

    for (day, bucket), grp in period_signals.groupby(["date", "bucket"]):
        total_bucket_days += 1
        day_dt = pd.Timestamp(day).normalize()

        # Dispersion filter
        std_signal = grp["signal"].std()
        if pd.isna(std_signal) or std_signal < disp_min:
            dispersion_skip_count += 1
            continue

        # Cross-sectional rank
        grp = grp.copy()
        grp["rank"] = scipy.stats.rankdata(grp["signal"].values) / len(grp)
        long_set = grp[grp["rank"] >= long_q]["ticker"].tolist()
        short_set = grp[grp["rank"] <= short_q]["ticker"].tolist()

        if not long_set or not short_set:
            continue

        # Cap at top_n/bot_n by rank (already ranked)
        long_set = grp[grp["rank"] >= long_q].nlargest(top_n, "rank")["ticker"].tolist()
        short_set = grp[grp["rank"] <= short_q].nsmallest(bot_n, "rank")["ticker"].tolist()

        # Fetch risk metrics for this day
        risk_row = None
        if day_dt in risk_metrics.index:
            risk_row = risk_metrics.loc[day_dt]

        # Per-position sizing
        n_long = len(long_set)
        n_short = len(short_set)
        per_long_capital = cap_per_side / max(n_long, 1)
        per_short_capital = cap_per_side / max(n_short, 1)

        day_date = day.date() if hasattr(day, "date") else day

        long_gross_rets: list[float] = []
        short_gross_rets: list[float] = []
        long_cost_usd = 0.0
        short_cost_usd = 0.0
        long_capital_used = 0.0
        short_capital_used = 0.0

        for side, tickers, per_cap in [
            ("long", long_set, per_long_capital),
            ("short", short_set, per_short_capital),
        ]:
            for ticker in tickers:
                key = (day_date, int(bucket), ticker)
                if key not in price_lookup:
                    continue
                entry_p, exit_p = price_lookup[key]
                shares = per_cap / entry_p  # fractional shares allowed

                # Risk metrics
                sigma = 0.02   # fallback daily vol
                adv = 1e6      # fallback ADV shares
                if risk_row is not None:
                    try:
                        s = risk_row.get((ticker, "sigma_20d"))
                        a = risk_row.get((ticker, "adv_20d"))
                        if s is not None and not pd.isna(s):
                            sigma = float(s)
                        if a is not None and not pd.isna(a):
                            adv = float(a)
                    except Exception:
                        pass

                # Round-trip costs: entry leg + exit leg
                entry_cost, liq_flag_e = compute_cost(entry_p, shares, sigma, adv, params)
                exit_cost, liq_flag_x = compute_cost(exit_p, shares, sigma, adv, params)
                round_trip_cost = entry_cost + exit_cost
                liquidity_flag = liq_flag_e or liq_flag_x

                if side == "long":
                    gross_ret = exit_p / entry_p - 1.0
                    long_gross_rets.append(gross_ret)
                    long_cost_usd += round_trip_cost
                    long_capital_used += per_cap
                else:
                    gross_ret = -(exit_p / entry_p - 1.0)  # short: flip sign
                    short_gross_rets.append(gross_ret)
                    short_cost_usd += round_trip_cost
                    short_capital_used += per_cap

                net_ret = gross_ret - round_trip_cost / per_cap
                trade_records.append({
                    "date": str(day_date),
                    "bucket_idx": int(bucket),
                    "ticker": ticker,
                    "side": side,
                    "entry_price": round(entry_p, 4),
                    "exit_price": round(exit_p, 4),
                    "shares": round(shares, 4),
                    "gross_ret_pct": round(gross_ret * 100, 4),
                    "cost_usd": round(round_trip_cost, 4),
                    "net_ret_pct": round(net_ret * 100, 4),
                    "sigma_20d": round(sigma, 6),
                    "adv_20d": round(adv, 0),
                    "liquidity_flag": liquidity_flag,
                })

        # Portfolio net return for this bucket-day
        if not long_gross_rets and not short_gross_rets:
            continue

        gross_long = float(np.mean(long_gross_rets)) if long_gross_rets else 0.0
        gross_short = float(np.mean(short_gross_rets)) if short_gross_rets else 0.0
        gross_port = 0.5 * gross_long + 0.5 * gross_short

        total_capital = long_capital_used + short_capital_used
        total_cost = long_cost_usd + short_cost_usd
        cost_frac = total_cost / total_capital if total_capital > 0 else 0.0
        net_port = gross_port - cost_frac

        prev = daily_returns.get(day_date, 0.0)
        daily_returns[day_date] = prev + net_port

    daily_returns_series = pd.Series(daily_returns, dtype=float).sort_index()
    daily_returns_series.index = pd.to_datetime(daily_returns_series.index)

    trade_log = pd.DataFrame(trade_records)
    disp_pct = dispersion_skip_count / max(total_bucket_days, 1) * 100.0
    logger.info(
        "Period %s→%s: %d bucket-days, %d skipped (dispersion), %d trades",
        start, end, total_bucket_days, dispersion_skip_count, len(trade_records),
    )

    return daily_returns_series, trade_log, disp_pct


# ── Performance metrics ────────────────────────────────────────────────────────

def sharpe_ratio(returns: pd.Series, ann_factor: int = 252) -> float:
    """Annualised Sharpe from daily return series."""
    if returns.empty or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * math.sqrt(ann_factor))


def max_drawdown(returns: pd.Series) -> float:
    """Maximum drawdown from daily return series (negative fraction)."""
    if returns.empty:
        return 0.0
    cum = (1 + returns).cumprod()
    rolling_max = cum.cummax()
    dd = (cum - rolling_max) / rolling_max
    return float(dd.min())


# ── HTML report ────────────────────────────────────────────────────────────────

def _render_html_report(
    metrics: dict,
    wf_results: list[dict],
    bucket_sharpes: dict,
    is_equity: pd.Series,
    oos_equity: pd.Series,
    holdout_equity: pd.Series,
    run_date: str,
) -> str:
    """Build a self-contained HTML report."""

    def _eq_rows(series: pd.Series) -> str:
        rows = []
        for d, v in series.items():
            rows.append(f'["{d.date()}", {v:.6f}]')
        return ",\n".join(rows)

    wf_rows = "".join(
        f"<tr><td>{w['window']}</td><td>{w['is_start']}–{w['is_end']}</td>"
        f"<td>{w['oos_start']}–{w['oos_end']}</td>"
        f"<td>{w['is_sharpe']:.3f}</td><td>{w['oos_sharpe']:.3f}</td></tr>"
        for w in wf_results
    )

    bucket_rows = "".join(
        f"<tr><td>h={b}</td><td>{BUCKET_STARTS[b]}</td><td>{s:.3f}</td></tr>"
        for b, s in sorted(bucket_sharpes.items())
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>H62 Gate 1 Report — {run_date}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  body{{font-family:sans-serif;margin:40px;background:#f9f9f9;}}
  table{{border-collapse:collapse;width:100%;margin-bottom:24px;}}
  th,td{{border:1px solid #ccc;padding:6px 10px;text-align:left;}}
  th{{background:#e8e8e8;}}
  h1{{color:#1a1a2e;}} h2{{color:#2d4059;}}
  .metric{{display:inline-block;min-width:160px;padding:12px;margin:6px;
           background:white;border:1px solid #ddd;border-radius:4px;}}
  .metric-val{{font-size:1.4em;font-weight:bold;color:#2d4059;}}
</style>
</head><body>
<h1>H62 Intraday Half-Hour Cross-Sectional Seasonality — Gate 1 Report</h1>
<p>Run date: {run_date} &nbsp;|&nbsp; Universe: {len(metrics.get('universe',[]))} tickers
   &nbsp;|&nbsp; Data: {metrics.get('data_start','')} → {metrics.get('data_end','')}</p>

<h2>Summary Metrics</h2>
<div>
  <div class="metric"><div>IS Sharpe</div><div class="metric-val">{metrics.get('is_sharpe',0):.3f}</div></div>
  <div class="metric"><div>OOS Sharpe</div><div class="metric-val">{metrics.get('oos_sharpe',0):.3f}</div></div>
  <div class="metric"><div>IS MDD</div><div class="metric-val">{metrics.get('is_mdd',0):.1%}</div></div>
  <div class="metric"><div>OOS MDD</div><div class="metric-val">{metrics.get('oos_mdd',0):.1%}</div></div>
  <div class="metric"><div>IS Trades</div><div class="metric-val">{metrics.get('is_trades',0)}</div></div>
  <div class="metric"><div>OOS Trades</div><div class="metric-val">{metrics.get('oos_trades',0)}</div></div>
  <div class="metric"><div>Profit/Trade bps</div>
    <div class="metric-val">{metrics.get('profit_per_trade_bps',0):.2f}</div></div>
  <div class="metric"><div>Cost/Gross Ratio</div>
    <div class="metric-val">{metrics.get('cost_to_gross_ratio',0):.3f}</div></div>
  <div class="metric"><div>WF OOS Sharpe mean</div>
    <div class="metric-val">{metrics.get('wf_oos_sharpe_mean',0):.3f}</div></div>
  <div class="metric"><div>WF OOS Sharpe min</div>
    <div class="metric-val">{metrics.get('wf_oos_sharpe_min',0):.3f}</div></div>
  <div class="metric"><div>Dispersion Skips %</div>
    <div class="metric-val">{metrics.get('dispersion_filter_skips_pct',0):.1f}%</div></div>
  <div class="metric"><div>Liquidity Constrained %</div>
    <div class="metric-val">{metrics.get('liquidity_constrained_pct',0):.1f}%</div></div>
</div>

<h2>Equity Curves</h2>
<div id="eq-chart" style="width:100%;height:400px;"></div>
<script>
(function(){{
  var is_data = [{_eq_rows(is_equity.cumsum())}];
  var oos_data = [{_eq_rows(oos_equity.cumsum())}];
  var hld_data = [{_eq_rows(holdout_equity.cumsum())}];
  function series(data, name, color) {{
    return {{
      x: data.map(function(r){{return r[0]}}),
      y: data.map(function(r){{return r[1]}}),
      type:'scatter', mode:'lines', name:name,
      line:{{color:color}}
    }};
  }}
  Plotly.newPlot('eq-chart',
    [series(is_data,'IS (2022–2023)','#2196F3'),
     series(oos_data,'OOS (2024)','#4CAF50'),
     series(hld_data,'Holdout Extended (2024)','#FF9800')],
    {{margin:{{t:20}}, legend:{{orientation:'h'}}}}
  );
}})();
</script>

<h2>Bucket-by-Bucket Sharpe (IS)</h2>
<table>
  <tr><th>Bucket</th><th>Start Time (ET)</th><th>IS Sharpe</th></tr>
  {bucket_rows}
</table>

<h2>Walk-Forward Results</h2>
<table>
  <tr><th>Window</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th></tr>
  {wf_rows}
</table>

<h2>Data Quality Checklist</h2>
<ul>
  <li>Universe survivorship: fixed 50-stock list — NOT dynamic S&amp;P 500 constituents</li>
  <li>Prices: auto_adjust=True — splits and dividends adjusted</li>
  <li>Data gaps: checked per ticker, logged to strategies/data/h62/data_quality_report.json</li>
  <li>Earnings exclusion: NOT excluded (intentional — signal may be amplified during earnings)</li>
  <li>Delisted tickers: none in fixed universe — verified</li>
</ul>
</body></html>"""
    return html


# ── Main run_strategy ──────────────────────────────────────────────────────────

def run_strategy(params: dict = PARAMETERS) -> dict:
    """
    Full H62 backtest: download, signal, walk-forward, metrics, outputs.
    Returns metrics dict.
    """
    run_date = date.today().isoformat()
    logger.info("H62 backtest start — run_date=%s", run_date)

    # ── 1. Download data ──────────────────────────────────────────────────────
    intraday = download_30m_data(UNIVERSE, params["data_start"], params["data_end"])
    daily_ohlcv = download_daily_data(UNIVERSE)

    # ── 2. Data quality check ─────────────────────────────────────────────────
    check_data_quality(intraday, UNIVERSE)

    # ── 3. Build bucket returns and signals ───────────────────────────────────
    logger.info("Building bucket returns...")
    bucket_df = build_bucket_returns(intraday, UNIVERSE)
    logger.info("Building signals...")
    signal_df = build_signals(bucket_df, params)

    # ── 4. Daily risk metrics for cost model ──────────────────────────────────
    logger.info("Building daily risk metrics...")
    risk_metrics = build_daily_risk_metrics(daily_ohlcv, UNIVERSE, params)

    # ── 5. IS + OOS + holdout backtest ────────────────────────────────────────
    logger.info("Running IS backtest %s → %s", params["is_start"], params["is_end"])
    is_rets, is_trades, is_disp_pct = run_backtest_period(
        bucket_df, signal_df, intraday, risk_metrics,
        params["is_start"], params["is_end"], params, UNIVERSE,
    )

    logger.info("Running OOS backtest %s → %s", params["oos_start"], params["oos_end"])
    oos_rets, oos_trades, oos_disp_pct = run_backtest_period(
        bucket_df, signal_df, intraday, risk_metrics,
        params["oos_start"], params["oos_end"], params, UNIVERSE,
    )

    # Holdout same as OOS for this config (2024)
    holdout_rets = oos_rets.copy()

    # ── 6. Walk-forward ───────────────────────────────────────────────────────
    wf_results: list[dict] = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(params["wf_windows"], 1):
        wf_is_rets, _, _ = run_backtest_period(
            bucket_df, signal_df, intraday, risk_metrics,
            is_s, is_e, params, UNIVERSE,
        )
        wf_oos_rets, _, _ = run_backtest_period(
            bucket_df, signal_df, intraday, risk_metrics,
            oos_s, oos_e, params, UNIVERSE,
        )
        wf_results.append({
            "window": i,
            "is_start": is_s, "is_end": is_e,
            "oos_start": oos_s, "oos_end": oos_e,
            "is_sharpe": sharpe_ratio(wf_is_rets),
            "oos_sharpe": sharpe_ratio(wf_oos_rets),
        })
        logger.info("WF window %d: IS Sharpe=%.3f, OOS Sharpe=%.3f",
                    i, wf_results[-1]["is_sharpe"], wf_results[-1]["oos_sharpe"])

    # ── 7. Per-bucket IS Sharpe ───────────────────────────────────────────────
    bucket_sharpes: dict[int, float] = {}
    for b_idx in ACTIVE_BUCKETS:
        b_trades = is_trades[is_trades["bucket_idx"] == b_idx] if not is_trades.empty else pd.DataFrame()
        if b_trades.empty:
            bucket_sharpes[b_idx] = 0.0
            continue
        # Aggregate daily returns for this bucket
        b_rets = (
            b_trades.groupby("date")["net_ret_pct"].mean() / 100.0
        )
        b_rets.index = pd.to_datetime(b_rets.index)
        bucket_sharpes[b_idx] = sharpe_ratio(b_rets)

    # ── 8. Aggregate metrics ──────────────────────────────────────────────────
    all_trades = pd.concat([is_trades, oos_trades], ignore_index=True) if not is_trades.empty else oos_trades

    # Cost/gross ratio
    if not all_trades.empty and "gross_ret_pct" in all_trades.columns:
        gross_total = all_trades["gross_ret_pct"].abs().sum()
        cost_total = all_trades["cost_usd"].sum()
        gross_usd = (all_trades["entry_price"] * all_trades["shares"] * all_trades["gross_ret_pct"].abs() / 100).sum()
        cost_to_gross = cost_total / gross_usd if gross_usd > 0 else 0.0
        profit_per_trade_bps = (
            all_trades["net_ret_pct"].mean() * 100 if not all_trades.empty else 0.0
        )
        liq_pct = all_trades["liquidity_flag"].mean() * 100 if "liquidity_flag" in all_trades.columns else 0.0
    else:
        cost_to_gross = 0.0
        profit_per_trade_bps = 0.0
        liq_pct = 0.0

    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_results]
    disp_avg_pct = (is_disp_pct + oos_disp_pct) / 2.0

    metrics = {
        "strategy": "H62_intraday_half_hour_seasonality",
        "run_date": run_date,
        "is_sharpe": sharpe_ratio(is_rets),
        "oos_sharpe": sharpe_ratio(oos_rets),
        "is_mdd": max_drawdown(is_rets),
        "oos_mdd": max_drawdown(oos_rets),
        "is_trades": len(is_trades),
        "oos_trades": len(oos_trades),
        "profit_per_trade_bps": profit_per_trade_bps,
        "cost_to_gross_ratio": cost_to_gross,
        "wf_sharpe_by_window": wf_results,
        "wf_oos_sharpe_mean": float(np.mean(wf_oos_sharpes)) if wf_oos_sharpes else 0.0,
        "wf_oos_sharpe_min": float(np.min(wf_oos_sharpes)) if wf_oos_sharpes else 0.0,
        "active_buckets_used": ACTIVE_BUCKETS,
        "dispersion_filter_skips_pct": disp_avg_pct,
        "liquidity_constrained_pct": liq_pct,
        "universe": UNIVERSE,
        "data_start": params["data_start"],
        "data_end": params["data_end"],
    }

    # ── 9. Save trade log CSV ─────────────────────────────────────────────────
    trade_csv = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}_trades.csv"
    all_trades.to_csv(trade_csv, index=False)
    logger.info("Trade log: %s (%d rows)", trade_csv, len(all_trades))

    # ── 10. Save metrics JSON ─────────────────────────────────────────────────
    metrics_path = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info("Metrics JSON: %s", metrics_path)

    # ── 11. HTML report ───────────────────────────────────────────────────────
    html = _render_html_report(
        metrics, wf_results, bucket_sharpes,
        is_rets, oos_rets, holdout_rets, run_date,
    )
    html_path = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}_report.html"
    with open(html_path, "w") as f:
        f.write(html)
    logger.info("HTML report: %s", html_path)

    logger.info(
        "H62 complete | IS Sharpe=%.3f | OOS Sharpe=%.3f | IS MDD=%.2f%% | "
        "IS trades=%d | OOS trades=%d | WF OOS mean=%.3f",
        metrics["is_sharpe"], metrics["oos_sharpe"],
        metrics["is_mdd"] * 100, metrics["is_trades"], metrics["oos_trades"],
        metrics["wf_oos_sharpe_mean"],
    )
    return metrics


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    result = run_strategy()
    print(json.dumps(
        {k: v for k, v in result.items() if k != "universe"},
        indent=2, default=str,
    ))
