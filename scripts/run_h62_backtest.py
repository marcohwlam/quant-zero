"""
H62 Gate 1 v2.2 Backtest Runner
Run date: 2026-06-10

DATA NOTE: yfinance 30m intraday data is limited to the last 60 days.
Historical data from 2021-10 to 2024-12 is NOT available via yfinance free tier.
This runner uses synthetic 30m bars derived from real daily OHLCV data via
Brownian bridge decomposition. Synthetic data has NO embedded cross-sectional
seasonality — it is a null-hypothesis baseline. Results are labeled accordingly.

A real Gate 1 run requires historical 30m data from a commercial provider
(Polygon.io, Refinitiv, Bloomberg, etc.).
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

import numpy as np
import pandas as pd
import scipy.stats
import yfinance as yf

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("h62_runner")

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent
_BACKTEST_DIR = _ROOT / "backtests"
_DATA_DIR = _ROOT / "strategies" / "data" / "h62"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

# ── Universe ───────────────────────────────────────────────────────────────────
UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA', 'BRK-B',
    'JPM', 'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'BAC', 'INTC', 'CSCO',
    'VZ', 'PFE', 'KO', 'PEP', 'MRK', 'ABT', 'TMO', 'WMT', 'DIS', 'CMCSA',
    'NKE', 'IBM', 'MCD', 'ACN', 'TXN', 'QCOM', 'SBUX', 'GS', 'MS', 'AXP',
    'BA', 'CAT', 'HON', 'MMM', 'MDT', 'USB', 'C', 'WFC', 'MO', 'CL',
    'GE', 'XOM',
]

BUCKET_STARTS = [
    '09:30', '10:00', '10:30', '11:00', '11:30',
    '12:00', '12:30',
    '13:00', '13:30', '14:00', '14:30', '15:00', '15:30',
]
ACTIVE_BUCKETS = [0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12]
N_ACTIVE = len(ACTIVE_BUCKETS)

PARAMETERS = {
    "signal_window": 5,
    "long_quantile": 0.80,
    "short_quantile": 0.20,
    "dispersion_min_std": 0.0010,
    "capital": 25_000.0,
    "long_capital": 12_500.0,
    "short_capital": 12_500.0,
    "fixed_per_share": 0.005,
    "slippage_pct": 0.0005,
    "market_impact_k": 0.1,
    "sigma_window": 20,
    "adv_window": 20,
    "wf_windows": [
        ("2022-01-01", "2022-03-31", "2022-04-01", "2022-04-30"),
        ("2022-05-01", "2022-07-31", "2022-08-01", "2022-08-31"),
        ("2022-09-01", "2022-11-30", "2022-12-01", "2022-12-31"),
        ("2023-01-01", "2023-03-31", "2023-04-01", "2023-04-30"),
        ("2023-05-01", "2023-07-31", "2023-08-01", "2023-08-31"),
        ("2023-09-01", "2023-11-30", "2023-12-01", "2023-12-31"),
    ],
    "data_start": "2021-10-01",
    "data_end": "2024-12-31",
    "is_start": "2022-01-01",
    "is_end": "2023-12-31",
    "oos_start": "2024-01-01",
    "oos_end": "2024-12-31",
}

# U-shaped volume profile for 13 intraday 30m bars (normalized to sum to 1)
# Captures known intraday patterns: high at open/close, lower midday
_BUCKET_VOL_WEIGHT = np.array([
    0.14, 0.10, 0.08, 0.07, 0.07,   # h=0..4 (09:30-11:30)
    0.06, 0.06,                       # h=5,6  (midday - skipped in trading)
    0.07, 0.07, 0.08, 0.09, 0.10, 0.11  # h=7..12 (13:00-15:30)
])
_BUCKET_VOL_WEIGHT = _BUCKET_VOL_WEIGHT / _BUCKET_VOL_WEIGHT.sum()

# Per-bucket volatility multiplier (U-shaped: higher at open/close)
_BUCKET_VOL_MULT = np.array([
    1.5, 1.2, 1.0, 0.9, 0.9,
    0.8, 0.8,
    0.9, 0.9, 1.0, 1.0, 1.2, 1.5
])


def download_daily_data(universe: list[str], start: str, end: str) -> pd.DataFrame:
    """Download daily OHLCV for universe. Cache to pickle."""
    cache_path = _DATA_DIR / f"daily_ohlcv_{start}_{end}.pkl"
    if cache_path.exists():
        logger.info("Daily OHLCV cache hit")
        return pd.read_pickle(cache_path)

    logger.info("Downloading daily OHLCV for %d tickers", len(universe))
    raw = yf.download(
        tickers=universe,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError("Daily OHLCV download returned empty DataFrame")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.swaplevel(0, 1)
        raw = raw.sort_index(axis=1)
    else:
        raw.columns = pd.MultiIndex.from_tuples(
            [(universe[0], c) for c in raw.columns], names=["ticker", "field"]
        )

    raw.to_pickle(cache_path)
    logger.info("Daily OHLCV downloaded: %d rows × %d cols", len(raw), len(raw.columns))
    return raw


def synthesize_30m_bars(
    daily_df: pd.DataFrame,
    universe: list[str],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Generate synthetic 30m OHLCV bars from daily OHLCV using Brownian bridge.

    For each ticker × trading day:
    - Decompose the daily [Open, Close] into 13 synthetic 30m bars
    - Each bar's return variance is proportional to bucket volatility weight
    - Brownian bridge ensures the bar path starts at daily Open and ends at daily Close
    - Volume is distributed proportionally to _BUCKET_VOL_WEIGHT

    Returns MultiIndex DataFrame: DatetimeTZ index (ET), (ticker, field) columns.
    """
    cache_path = _DATA_DIR / "synthetic_30m_bars.pkl"
    if cache_path.exists():
        logger.info("Synthetic 30m bars cache hit")
        return pd.read_pickle(cache_path)

    logger.info("Generating synthetic 30m bars from daily OHLCV...")
    records = []
    n_tickers = len(universe)
    tz = "America/New_York"

    # Get trading days
    trading_days = daily_df.index.normalize().unique()

    for day in trading_days:
        if day not in daily_df.index:
            continue

        day_row = daily_df.loc[day]

        for ticker in universe:
            try:
                o_col = (ticker, "Open")
                c_col = (ticker, "Close")
                h_col = (ticker, "High")
                l_col = (ticker, "Low")
                v_col = (ticker, "Volume")

                if o_col not in daily_df.columns:
                    continue

                o = float(day_row.get(o_col, np.nan))
                c = float(day_row.get(c_col, np.nan))
                h = float(day_row.get(h_col, np.nan))
                lo = float(day_row.get(l_col, np.nan))
                v = float(day_row.get(v_col, np.nan))

                if any(np.isnan([o, c, h, lo])) or o <= 0 or c <= 0:
                    continue

                daily_ret = c / o - 1.0
                daily_vol = abs(daily_ret) + 0.001  # floor vol

                # Brownian bridge: generate N_BUCKETS=13 increments
                N = 13
                dt = 1.0 / N
                # Scaled volatility per bucket
                sigma_bucket = daily_vol * _BUCKET_VOL_MULT * math.sqrt(dt)

                # Generate increments
                increments = rng.normal(0, sigma_bucket)

                # Brownian bridge correction: force path to end at daily_ret
                raw_endpoint = increments.sum()
                bridge_increments = increments - (raw_endpoint - daily_ret) / N

                # Build price path
                log_o = math.log(max(o, 1e-6))
                prices = [math.exp(log_o + bridge_increments[:i].sum()) for i in range(N + 1)]
                prices = [max(p, 0.01) for p in prices]

                # Build 30m bars
                bucket_volume = v * _BUCKET_VOL_WEIGHT if not np.isnan(v) else np.ones(N) * 1e6 / N

                for bucket_idx in range(N):
                    bar_open = prices[bucket_idx]
                    bar_close = prices[bucket_idx + 1]
                    bar_high = max(bar_open, bar_close) * (1 + abs(rng.normal(0, 0.0002)))
                    bar_low = min(bar_open, bar_close) * (1 - abs(rng.normal(0, 0.0002)))
                    bar_vol = max(bucket_volume[bucket_idx], 1.0)

                    # Create timestamp for this bucket
                    bucket_time = pd.Timestamp(
                        BUCKET_STARTS[bucket_idx],
                        tz=tz,
                    ).replace(
                        year=day.year, month=day.month, day=day.day
                    )

                    records.append({
                        "timestamp": bucket_time,
                        "ticker": ticker,
                        "Open": round(bar_open, 4),
                        "Close": round(bar_close, 4),
                        "High": round(bar_high, 4),
                        "Low": round(bar_low, 4),
                        "Volume": int(bar_vol),
                    })
            except Exception as exc:
                logger.debug("Synthetic bar failed %s %s: %s", ticker, day, exc)

    if not records:
        raise RuntimeError("No synthetic bars generated")

    df = pd.DataFrame(records)
    df = df.set_index("timestamp").sort_index()

    # Convert to MultiIndex columns (ticker, field)
    melted = df.reset_index()
    dfs = []
    for ticker in universe:
        sub = melted[melted["ticker"] == ticker].copy()
        sub = sub.drop("ticker", axis=1).set_index("timestamp")
        sub.columns = pd.MultiIndex.from_tuples(
            [(ticker, c) for c in sub.columns], names=["ticker", "field"]
        )
        dfs.append(sub)

    combined = pd.concat(dfs, axis=1).sort_index()
    combined.to_pickle(cache_path)
    logger.info("Synthetic 30m bars: %d rows × %d cols", len(combined), len(combined.columns))
    return combined


def build_bucket_returns_from_synthetic(
    intraday: pd.DataFrame,
    universe: list[str],
) -> pd.DataFrame:
    """Build bucket return records from synthetic intraday data."""
    bucket_time_to_idx = {t: i for i, t in enumerate(BUCKET_STARTS)}
    records = []

    for ts, row in intraday.iterrows():
        t_str = ts.strftime("%H:%M")
        b_idx = bucket_time_to_idx.get(t_str)
        if b_idx is None or b_idx not in ACTIVE_BUCKETS:
            continue
        day = ts.normalize().date()
        for ticker in universe:
            o_col = (ticker, "Open")
            c_col = (ticker, "Close")
            if o_col not in intraday.columns:
                continue
            o = row.get(o_col, np.nan)
            c = row.get(c_col, np.nan)
            if pd.isna(o) or pd.isna(c) or float(o) <= 0:
                continue
            records.append({
                "date": pd.Timestamp(day),
                "bucket": b_idx,
                "ticker": ticker,
                "open": float(o),
                "close": float(c),
                "bucket_ret": float(c) / float(o) - 1.0,
            })

    if not records:
        raise RuntimeError("No bucket return records from synthetic data")
    return pd.DataFrame(records)


def build_signals(bucket_df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """5-day rolling same-bucket signal with shift(1) look-ahead guard."""
    window = params["signal_window"]
    pivot = bucket_df.pivot_table(
        index="date", columns=["ticker", "bucket"], values="bucket_ret", aggfunc="mean"
    )
    pivot = pivot.sort_index()
    signal = pivot.shift(1).rolling(window=window, min_periods=window).mean()
    signal_long = signal.stack(level=[0, 1], future_stack=True).reset_index()
    signal_long.columns = ["date", "ticker", "bucket", "signal"]
    return signal_long.dropna(subset=["signal"])


def compute_cost(entry_price, shares, sigma, adv, params):
    fixed = params["fixed_per_share"] * shares
    slippage = params["slippage_pct"] * entry_price * shares
    impact_frac = params["market_impact_k"] * sigma * math.sqrt(shares / (adv + 1e-10))
    impact = impact_frac * entry_price * shares
    total = fixed + slippage + impact
    liquidity_flag = (shares / (adv + 1e-10)) > 0.01
    return total, liquidity_flag


def build_daily_risk_metrics(daily_df: pd.DataFrame, universe: list[str], params: dict) -> pd.DataFrame:
    records = {}
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
            logger.debug("Risk metrics failed %s: %s", ticker, exc)
    combined = pd.concat(records, axis=1)
    combined.columns.names = ["ticker", "metric"]
    return combined


def run_backtest_period(
    signal_df: pd.DataFrame,
    intraday: pd.DataFrame,
    risk_metrics: pd.DataFrame,
    start: str,
    end: str,
    params: dict,
    universe: list[str],
) -> tuple[pd.Series, pd.DataFrame, float]:
    start_dt = pd.Timestamp(start).normalize()
    end_dt = pd.Timestamp(end).normalize()

    mask = (signal_df["date"] >= start_dt) & (signal_df["date"] <= end_dt)
    period_signals = signal_df[mask].copy()

    long_q = params["long_quantile"]
    short_q = params["short_quantile"]
    disp_min = params["dispersion_min_std"]
    cap_per_side = params["long_capital"]
    n_universe = len(universe)
    top_n = max(1, round(n_universe * (1.0 - long_q)))
    bot_n = max(1, round(n_universe * short_q))

    # Build price lookup
    bucket_time_to_idx = {t: i for i, t in enumerate(BUCKET_STARTS)}
    price_lookup = {}
    for ts, row in intraday.iterrows():
        t_str = ts.strftime("%H:%M")
        b_idx = bucket_time_to_idx.get(t_str)
        if b_idx is None or b_idx not in ACTIVE_BUCKETS:
            continue
        d = ts.normalize().date()
        for ticker in universe:
            o_col = (ticker, "Open")
            c_col = (ticker, "Close")
            if o_col not in intraday.columns:
                continue
            o = row.get(o_col, np.nan)
            c = row.get(c_col, np.nan)
            if not pd.isna(o) and not pd.isna(c) and float(o) > 0:
                price_lookup[(d, b_idx, ticker)] = (float(o), float(c))

    trade_records = []
    daily_returns: dict = {}
    dispersion_skips = 0
    total_bucket_days = 0

    for (day, bucket), grp in period_signals.groupby(["date", "bucket"]):
        total_bucket_days += 1
        day_dt = pd.Timestamp(day).normalize()
        std_signal = grp["signal"].std()
        if pd.isna(std_signal) or std_signal < disp_min:
            dispersion_skips += 1
            continue

        grp = grp.copy()
        grp["rank"] = scipy.stats.rankdata(grp["signal"].values) / len(grp)
        long_set = grp[grp["rank"] >= long_q].nlargest(top_n, "rank")["ticker"].tolist()
        short_set = grp[grp["rank"] <= short_q].nsmallest(bot_n, "rank")["ticker"].tolist()
        if not long_set or not short_set:
            continue

        risk_row = risk_metrics.loc[day_dt] if day_dt in risk_metrics.index else None
        n_long, n_short = len(long_set), len(short_set)
        per_long_cap = cap_per_side / max(n_long, 1)
        per_short_cap = cap_per_side / max(n_short, 1)
        day_date = day.date() if hasattr(day, "date") else day

        long_gross_rets, short_gross_rets = [], []
        long_cost_usd = short_cost_usd = long_cap_used = short_cap_used = 0.0

        for side, tickers, per_cap in [
            ("long", long_set, per_long_cap),
            ("short", short_set, per_short_cap),
        ]:
            for ticker in tickers:
                key = (day_date, int(bucket), ticker)
                if key not in price_lookup:
                    continue
                entry_p, exit_p = price_lookup[key]
                shares = per_cap / entry_p

                sigma, adv = 0.02, 1e6
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

                entry_cost, liq_e = compute_cost(entry_p, shares, sigma, adv, params)
                exit_cost, liq_x = compute_cost(exit_p, shares, sigma, adv, params)
                round_trip_cost = entry_cost + exit_cost
                liquidity_flag = liq_e or liq_x

                if side == "long":
                    gross_ret = exit_p / entry_p - 1.0
                    long_gross_rets.append(gross_ret)
                    long_cost_usd += round_trip_cost
                    long_cap_used += per_cap
                else:
                    gross_ret = -(exit_p / entry_p - 1.0)
                    short_gross_rets.append(gross_ret)
                    short_cost_usd += round_trip_cost
                    short_cap_used += per_cap

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
                    "liquidity_flag": liquidity_flag,
                })

        if not long_gross_rets and not short_gross_rets:
            continue

        gross_long = float(np.mean(long_gross_rets)) if long_gross_rets else 0.0
        gross_short = float(np.mean(short_gross_rets)) if short_gross_rets else 0.0
        gross_port = 0.5 * gross_long + 0.5 * gross_short
        total_cap = long_cap_used + short_cap_used
        total_cost = long_cost_usd + short_cost_usd
        cost_frac = total_cost / total_cap if total_cap > 0 else 0.0
        net_port = gross_port - cost_frac

        d_key = day.date() if hasattr(day, "date") else day
        daily_returns[d_key] = daily_returns.get(d_key, 0.0) + net_port

    rets = pd.Series(daily_returns, dtype=float).sort_index()
    rets.index = pd.to_datetime(rets.index)
    trade_log = pd.DataFrame(trade_records)
    disp_pct = dispersion_skips / max(total_bucket_days, 1) * 100.0
    logger.info("Period %s→%s: %d bucket-days, %d skipped, %d trades",
                start, end, total_bucket_days, dispersion_skips, len(trade_records))
    return rets, trade_log, disp_pct


def sharpe_ratio(returns: pd.Series, ann_factor: int = 252) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * math.sqrt(ann_factor))


def max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    cum = (1 + returns).cumprod()
    rolling_max = cum.cummax()
    dd = (cum - rolling_max) / rolling_max
    return float(dd.min())


# ── Statistical Rigor Pipeline ────────────────────────────────────────────────

def monte_carlo_sharpe(trade_pnls: np.ndarray, n_sims: int = 1000) -> dict:
    if len(trade_pnls) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    rng = np.random.default_rng(42)
    sharpes = []
    for _ in range(n_sims):
        sample = rng.choice(trade_pnls, size=len(trade_pnls), replace=True)
        s = sample.mean() / (sample.std() + 1e-8) * math.sqrt(252)
        sharpes.append(s)
    sharpes = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe": float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    if len(returns) < 10:
        return {
            "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
            "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
        }
    T = len(returns)
    block_len = max(1, int(math.sqrt(T)))
    rng = np.random.default_rng(42)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        n_blocks = T // block_len + 1
        starts = rng.integers(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / roll_max))
        s = float(sample.mean() / (sample.std() + 1e-8) * math.sqrt(252))
        wr = float(np.mean(sample > 0))
        sharpes.append(s)
        mdds.append(mdd)
        win_rates.append(wr)
    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low": float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def permutation_test_alpha(
    daily_rets: np.ndarray,
    observed_sharpe: float,
    n_perms: int = 500,
) -> dict:
    if len(daily_rets) < 10:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    rng = np.random.default_rng(42)
    permuted_sharpes = []
    for _ in range(n_perms):
        shuffled = rng.permutation(daily_rets)
        s = float(shuffled.mean() / (shuffled.std() + 1e-8) * math.sqrt(252))
        permuted_sharpes.append(s)
    permuted_sharpes = np.array(permuted_sharpes)
    p_value = float(np.mean(permuted_sharpes >= observed_sharpe))
    return {
        "permutation_pvalue": p_value,
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(wf_oos_sharpes: list) -> dict:
    if not wf_oos_sharpes:
        return {"wf_sharpe_std": 0.0, "wf_sharpe_min": 0.0}
    arr = np.array(wf_oos_sharpes)
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


# ── OOS Data Quality ──────────────────────────────────────────────────────────

def validate_oos_simple(oos_rets: pd.Series, oos_metrics: dict) -> dict:
    """Simplified OOS data quality check."""
    critical_fields = ["oos_sharpe", "oos_mdd", "oos_trades"]
    critical_nan = [f for f in critical_fields if oos_metrics.get(f) is None or (
        isinstance(oos_metrics.get(f), float) and math.isnan(oos_metrics.get(f))
    )]
    nan_count = oos_rets.isna().sum()
    total = len(oos_rets)
    coverage = (total - nan_count) / max(total, 1)

    if critical_nan or coverage < 0.90:
        recommendation = "BLOCK"
    elif coverage < 0.95 or nan_count > 0:
        recommendation = "WARN"
    else:
        recommendation = "PASS"

    return {
        "recommendation": recommendation,
        "nan_count": int(nan_count),
        "coverage_pct": round(coverage * 100, 2),
        "critical_nan_fields": critical_nan,
        "advisory_nan_fields": [],
    }


# ── Gate 1 Verdict ─────────────────────────────────────────────────────────────

def build_gate1_verdict(metrics: dict, run_date: str, is_synthetic: bool) -> tuple[str, str]:
    """Build Gate 1 verdict text and JSON string."""
    data_note = "SYNTHETIC DATA (null-hypothesis baseline)" if is_synthetic else "REAL DATA"

    # Threshold checks
    checks = {
        "IS Sharpe > 1.0": metrics["is_sharpe"] > 1.0,
        "OOS Sharpe > 0.7": metrics["oos_sharpe"] > 0.7,
        "IS MDD > -20%": metrics["is_mdd"] > -0.20,
        "OOS MDD > -20%": metrics["oos_mdd"] > -0.20,
        "IS Trades > 300": metrics["is_trades"] > 300,
        "Profit/Trade > 5 bps": metrics["profit_per_trade_bps"] > 5.0,
        "Cost/Gross < 0.40": metrics["cost_to_gross_ratio"] < 0.40,
        "WF windows passed ≥ 3/6": metrics["wf_windows_passed"] >= 3,
        "Permutation test p < 0.05": metrics.get("permutation_test_pass", False),
        "MC p5 Sharpe > 0.5": metrics.get("mc_p5_sharpe", 0.0) > 0.5,
    }

    passed = sum(checks.values())
    total = len(checks)

    # Auto-disqualification checks
    auto_disq = []
    if metrics.get("cost_to_gross_ratio", 1.0) >= 0.40:
        auto_disq.append("Cost-to-gross ratio ≥ 0.40")
    if metrics.get("is_trades", 0) < 300:
        auto_disq.append("IS trade count < 300")
    if metrics.get("oos_mdd", 0.0) < -0.40:
        auto_disq.append(f"OOS MDD {metrics['oos_mdd']:.1%} exceeds 2× threshold")

    overall_verdict = "FAIL"
    if not auto_disq and passed >= total * 0.8:
        overall_verdict = "PASS"
    elif not auto_disq and passed >= total * 0.6:
        overall_verdict = "CONDITIONAL PASS"

    if is_synthetic:
        overall_verdict = f"FAIL (synthetic data — {data_note})"

    lines = [
        "=" * 60,
        "GATE 1 v2.2 VERDICT REPORT — H62",
        f"Run Date: {run_date}",
        f"Data Source: {data_note}",
        "=" * 60,
        "",
        f"VERDICT: {overall_verdict}",
        "",
        "CORE METRICS",
        "-" * 40,
        f"IS Sharpe:              {metrics['is_sharpe']:.4f}   (threshold > 1.0)  {'PASS' if checks['IS Sharpe > 1.0'] else 'FAIL'}",
        f"OOS Sharpe:             {metrics['oos_sharpe']:.4f}   (threshold > 0.7)  {'PASS' if checks['OOS Sharpe > 0.7'] else 'FAIL'}",
        f"IS Max Drawdown:        {metrics['is_mdd']:.2%}   (threshold > -20%)  {'PASS' if checks['IS MDD > -20%'] else 'FAIL'}",
        f"OOS Max Drawdown:       {metrics['oos_mdd']:.2%}   (threshold > -20%)  {'PASS' if checks['OOS MDD > -20%'] else 'FAIL'}",
        f"IS Trade Count:         {metrics['is_trades']:,}   (threshold > 300)  {'PASS' if checks['IS Trades > 300'] else 'FAIL'}",
        f"Profit/Trade:           {metrics['profit_per_trade_bps']:.2f} bps   (threshold > 5 bps)  {'PASS' if checks['Profit/Trade > 5 bps'] else 'FAIL'}",
        f"Cost/Gross Ratio:       {metrics['cost_to_gross_ratio']:.4f}   (threshold < 0.40)  {'PASS' if checks['Cost/Gross < 0.40'] else 'FAIL'}",
        "",
        "WALK-FORWARD",
        "-" * 40,
        f"WF Windows Passed:      {metrics['wf_windows_passed']}/6   {'PASS' if checks['WF windows passed ≥ 3/6'] else 'FAIL'}",
        f"WF OOS Sharpe Mean:     {metrics['wf_oos_sharpe_mean']:.4f}",
        f"WF OOS Sharpe Min:      {metrics['wf_oos_sharpe_min']:.4f}",
        f"WF OOS Sharpe Std:      {metrics.get('wf_sharpe_std', 0.0):.4f}",
    ]

    # WF table
    lines.append("")
    lines.append("WALK-FORWARD TABLE")
    lines.append("-" * 40)
    lines.append(f"{'Win':>3}  {'IS Start':>10}  {'IS End':>10}  {'OOS Start':>10}  {'OOS End':>10}  {'IS Sharpe':>9}  {'OOS Sharpe':>10}")
    for w in metrics.get("wf_sharpe_by_window", []):
        oos_pass = "✓" if w["oos_sharpe"] > 0 else "✗"
        lines.append(
            f"{w['window']:>3}  {w['is_start']:>10}  {w['is_end']:>10}  {w['oos_start']:>10}  {w['oos_end']:>10}  "
            f"{w['is_sharpe']:>9.4f}  {w['oos_sharpe']:>10.4f} {oos_pass}"
        )

    lines += [
        "",
        "STATISTICAL TESTS",
        "-" * 40,
        f"Permutation p-value:    {metrics.get('permutation_pvalue', 1.0):.4f}   {'PASS' if checks['Permutation test p < 0.05'] else 'FAIL'} (H0: no alpha; p < 0.05 = reject H0)",
        f"MC p5 Sharpe:           {metrics.get('mc_p5_sharpe', 0.0):.4f}   {'PASS' if checks['MC p5 Sharpe > 0.5'] else 'FAIL'} (threshold > 0.5)",
        f"MC Median Sharpe:       {metrics.get('mc_median_sharpe', 0.0):.4f}",
        f"MC p95 Sharpe:          {metrics.get('mc_p95_sharpe', 0.0):.4f}",
        f"Bootstrap Sharpe CI:    [{metrics.get('sharpe_ci_low', 0.0):.4f}, {metrics.get('sharpe_ci_high', 0.0):.4f}]",
        f"Bootstrap MDD CI:       [{metrics.get('mdd_ci_low', 0.0):.4f}, {metrics.get('mdd_ci_high', 0.0):.4f}]",
        f"Bootstrap WinRate CI:   [{metrics.get('win_rate_ci_low', 0.0):.4f}, {metrics.get('win_rate_ci_high', 0.0):.4f}]",
        "",
        "BUCKET BREAKDOWN (IS Sharpe by bucket)",
        "-" * 40,
    ]

    for b_idx, b_sharpe in sorted(metrics.get("bucket_sharpes_is", {}).items()):
        t = BUCKET_STARTS[int(b_idx)]
        lines.append(f"  h={b_idx:>2}  {t}  Sharpe={b_sharpe:.4f}")

    if auto_disq:
        lines += ["", "AUTO-DISQUALIFICATION FLAGS", "-" * 40]
        for flag in auto_disq:
            lines.append(f"  ✗ {flag}")

    lines += [
        "",
        "OOS DATA QUALITY",
        "-" * 40,
        f"  Recommendation: {metrics.get('oos_data_quality', {}).get('recommendation', 'N/A')}",
        f"  Coverage: {metrics.get('oos_data_quality', {}).get('coverage_pct', 0.0):.1f}%",
        "",
        "CHECKS SUMMARY",
        "-" * 40,
        f"  {passed}/{total} checks passed",
    ]
    for check_name, passed_flag in checks.items():
        lines.append(f"  {'[PASS]' if passed_flag else '[FAIL]'} {check_name}")

    lines += [
        "",
        "=" * 60,
        f"DATA AVAILABILITY NOTE:",
        "  yfinance 30m historical data is limited to last 60 days.",
        "  H62 requires 2021-10-01 to 2024-12-31 intraday 30m data.",
        "  This run used SYNTHETIC 30m bars derived from daily OHLCV",
        "  (Brownian bridge, no embedded seasonality).",
        "  Results represent null-hypothesis baseline — NOT a valid",
        "  Gate 1 assessment of the actual H62 hypothesis.",
        "  To produce valid results: provide historical 30m data from",
        "  a commercial source (Polygon.io, Refinitiv, Bloomberg, etc.)",
        "=" * 60,
    ]

    return overall_verdict, "\n".join(lines)


def main() -> dict:
    run_date = date.today().isoformat()
    logger.info("H62 Gate 1 v2.2 runner start — run_date=%s (SYNTHETIC DATA MODE)", run_date)

    IS_SYNTHETIC = True

    rng = np.random.default_rng(42)

    # 1. Download daily OHLCV
    logger.info("Downloading daily OHLCV for %s → %s", PARAMETERS["data_start"], PARAMETERS["data_end"])
    daily_df = download_daily_data(UNIVERSE, PARAMETERS["data_start"], PARAMETERS["data_end"])

    # 2. Synthesize 30m bars
    intraday = synthesize_30m_bars(daily_df, UNIVERSE, rng)

    # 3. Build bucket returns and signals
    logger.info("Building bucket returns...")
    bucket_df = build_bucket_returns_from_synthetic(intraday, UNIVERSE)
    logger.info("Bucket records: %d", len(bucket_df))

    logger.info("Building signals (5-day rolling)...")
    signal_df = build_signals(bucket_df, PARAMETERS)
    logger.info("Signal records: %d", len(signal_df))

    # 4. Daily risk metrics
    logger.info("Building daily risk metrics...")
    risk_metrics = build_daily_risk_metrics(daily_df, UNIVERSE, PARAMETERS)

    # 5. IS backtest
    logger.info("Running IS backtest %s → %s", PARAMETERS["is_start"], PARAMETERS["is_end"])
    is_rets, is_trades, is_disp_pct = run_backtest_period(
        signal_df, intraday, risk_metrics,
        PARAMETERS["is_start"], PARAMETERS["is_end"], PARAMETERS, UNIVERSE,
    )

    # 6. OOS backtest
    logger.info("Running OOS backtest %s → %s", PARAMETERS["oos_start"], PARAMETERS["oos_end"])
    oos_rets, oos_trades, oos_disp_pct = run_backtest_period(
        signal_df, intraday, risk_metrics,
        PARAMETERS["oos_start"], PARAMETERS["oos_end"], PARAMETERS, UNIVERSE,
    )

    # 7. Walk-forward
    wf_results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(PARAMETERS["wf_windows"], 1):
        logger.info("WF window %d: %s → %s / %s → %s", i, is_s, is_e, oos_s, oos_e)
        wf_is, _, _ = run_backtest_period(signal_df, intraday, risk_metrics, is_s, is_e, PARAMETERS, UNIVERSE)
        wf_oos, _, _ = run_backtest_period(signal_df, intraday, risk_metrics, oos_s, oos_e, PARAMETERS, UNIVERSE)
        is_sh = sharpe_ratio(wf_is)
        oos_sh = sharpe_ratio(wf_oos)
        wf_results.append({
            "window": i,
            "is_start": is_s, "is_end": is_e,
            "oos_start": oos_s, "oos_end": oos_e,
            "is_sharpe": round(is_sh, 4),
            "oos_sharpe": round(oos_sh, 4),
            "is_trades": 0,  # placeholder
            "oos_trades": 0,
            "is_mdd": 0.0,
            "oos_mdd": 0.0,
        })
        logger.info("  WF%d: IS Sharpe=%.3f, OOS Sharpe=%.3f", i, is_sh, oos_sh)

    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_results]
    wf_windows_passed = sum(1 for s in wf_oos_sharpes if s > 0.0)

    # 8. Per-bucket IS Sharpe
    bucket_sharpes_is = {}
    for b_idx in ACTIVE_BUCKETS:
        b_trades = is_trades[is_trades["bucket_idx"] == b_idx] if not is_trades.empty else pd.DataFrame()
        if b_trades.empty:
            bucket_sharpes_is[b_idx] = 0.0
            continue
        b_rets = b_trades.groupby("date")["net_ret_pct"].mean() / 100.0
        b_rets.index = pd.to_datetime(b_rets.index)
        bucket_sharpes_is[b_idx] = round(sharpe_ratio(b_rets), 4)

    # 9. Aggregate metrics
    all_trades = pd.concat([is_trades, oos_trades], ignore_index=True) if not is_trades.empty else oos_trades

    cost_to_gross = 0.0
    profit_per_trade_bps = 0.0
    liq_pct = 0.0
    if not all_trades.empty and "gross_ret_pct" in all_trades.columns:
        gross_usd = (all_trades["entry_price"] * all_trades["shares"] * all_trades["gross_ret_pct"].abs() / 100).sum()
        cost_total = all_trades["cost_usd"].sum()
        cost_to_gross = float(cost_total / gross_usd) if gross_usd > 0 else 0.0
        profit_per_trade_bps = float(all_trades["net_ret_pct"].mean() * 100)
        liq_pct = float(all_trades["liquidity_flag"].mean() * 100) if "liquidity_flag" in all_trades.columns else 0.0

    is_sh = sharpe_ratio(is_rets)
    oos_sh = sharpe_ratio(oos_rets)
    is_mdd = max_drawdown(is_rets)
    oos_mdd = max_drawdown(oos_rets)
    win_rate_is = float((is_rets > 0).mean()) if not is_rets.empty else 0.0

    oos_basic = {
        "oos_sharpe": oos_sh,
        "oos_mdd": oos_mdd,
        "oos_trades": len(oos_trades),
    }
    dq_report = validate_oos_simple(oos_rets, oos_basic)
    if dq_report["recommendation"] == "BLOCK":
        logger.error("OOS DATA QUALITY BLOCK: %s", dq_report)
    elif dq_report["recommendation"] == "WARN":
        logger.warning("OOS DATA QUALITY WARN: %s", dq_report)

    # 10. Statistical rigor pipeline
    logger.info("Running Monte Carlo simulation (1000 sims)...")
    trade_pnls = np.array(all_trades["net_ret_pct"].values / 100.0) if not all_trades.empty else np.array([])
    mc_results = monte_carlo_sharpe(trade_pnls, n_sims=1000)

    logger.info("Running block bootstrap CI (1000 boots)...")
    is_rets_arr = is_rets.values if not is_rets.empty else np.array([])
    ci_results = block_bootstrap_ci(is_rets_arr, n_boots=1000)

    logger.info("Running permutation test (500 perms)...")
    perm_results = permutation_test_alpha(is_rets_arr, is_sh, n_perms=500)

    wf_var = walk_forward_variance(wf_oos_sharpes)

    # 11. Market impact (use IS aggregate)
    market_impact_bps = 0.0
    liquidity_constrained = False
    if not is_trades.empty and "shares" in is_trades.columns:
        avg_shares = float(is_trades["shares"].mean())
        avg_adv = 5_000_000.0  # approximate large-cap ADV
        sigma_20 = 0.015
        k = PARAMETERS["market_impact_k"]
        impact_pct = k * sigma_20 * math.sqrt(avg_shares / avg_adv)
        market_impact_bps = round(impact_pct * 10000, 4)
        liquidity_constrained = bool(avg_shares > 0.01 * avg_adv)

    # 12. Full metrics dict
    metrics = {
        "strategy_name": "H62_intraday_half_hour_seasonality",
        "date": run_date,
        "asset_class": "equities",
        "data_source": "SYNTHETIC_30M_FROM_DAILY_OHLCV",
        "data_note": (
            "yfinance 30m data limited to 60 days. Synthetic bars generated "
            "from daily OHLCV via Brownian bridge. NO embedded seasonality. "
            "Results are null-hypothesis baseline."
        ),
        "is_sharpe": round(is_sh, 4),
        "oos_sharpe": round(oos_sh, 4),
        "is_mdd": round(is_mdd, 4),
        "oos_mdd": round(oos_mdd, 4),
        "win_rate_is": round(win_rate_is, 4),
        "is_trades": len(is_trades),
        "oos_trades": len(oos_trades),
        "profit_per_trade_bps": round(profit_per_trade_bps, 4),
        "cost_to_gross_ratio": round(cost_to_gross, 4),
        "wf_sharpe_by_window": wf_results,
        "wf_oos_sharpe_mean": round(float(np.mean(wf_oos_sharpes)) if wf_oos_sharpes else 0.0, 4),
        "wf_oos_sharpe_min": round(float(np.min(wf_oos_sharpes)) if wf_oos_sharpes else 0.0, 4),
        "wf_windows_passed": wf_windows_passed,
        "bucket_sharpes_is": {str(k): v for k, v in bucket_sharpes_is.items()},
        "dispersion_filter_skips_pct": round((is_disp_pct + oos_disp_pct) / 2.0, 2),
        "liquidity_constrained_pct": round(liq_pct, 2),
        "oos_data_quality": dq_report,
        # Statistical rigor
        "mc_p5_sharpe": round(mc_results["mc_p5_sharpe"], 4),
        "mc_median_sharpe": round(mc_results["mc_median_sharpe"], 4),
        "mc_p95_sharpe": round(mc_results["mc_p95_sharpe"], 4),
        "sharpe_ci_low": round(ci_results["sharpe_ci_low"], 4),
        "sharpe_ci_high": round(ci_results["sharpe_ci_high"], 4),
        "mdd_ci_low": round(ci_results["mdd_ci_low"], 4),
        "mdd_ci_high": round(ci_results["mdd_ci_high"], 4),
        "win_rate_ci_low": round(ci_results["win_rate_ci_low"], 4),
        "win_rate_ci_high": round(ci_results["win_rate_ci_high"], 4),
        "market_impact_bps": market_impact_bps,
        "liquidity_constrained": liquidity_constrained,
        "permutation_pvalue": round(perm_results["permutation_pvalue"], 4),
        "permutation_test_pass": perm_results["permutation_test_pass"],
        "wf_sharpe_std": round(wf_var["wf_sharpe_std"], 4),
        "wf_sharpe_min": round(wf_var["wf_sharpe_min"], 4),
        "look_ahead_bias_flag": False,
        "synthetic_data": IS_SYNTHETIC,
        "universe_size": len(UNIVERSE),
        "active_buckets": ACTIVE_BUCKETS,
    }

    # 13. Build verdict
    overall_verdict, verdict_text = build_gate1_verdict(metrics, run_date, IS_SYNTHETIC)

    # 14. Save trade logs
    trade_csv = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}_trades.csv"
    all_trades.to_csv(trade_csv, index=False)
    logger.info("Trade log saved: %s (%d rows)", trade_csv, len(all_trades))

    # 15. Save metrics JSON
    metrics_path = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info("Metrics JSON saved: %s", metrics_path)

    # 16. Save verdict TXT
    verdict_path = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}.txt"
    verdict_path.write_text(verdict_text)
    logger.info("Verdict TXT saved: %s", verdict_path)

    # 17. Save simple HTML report
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>H62 Gate 1 Report — {run_date}</title>
<style>
  body{{font-family:sans-serif;margin:40px;background:#f9f9f9;}}
  pre{{background:#fff;border:1px solid #ddd;padding:20px;white-space:pre-wrap;font-size:13px;}}
  .warn{{background:#fff3cd;border:1px solid #ffc107;padding:12px;margin-bottom:20px;border-radius:4px;}}
  table{{border-collapse:collapse;width:100%;margin-bottom:24px;}}
  th,td{{border:1px solid #ccc;padding:6px 10px;}}
  th{{background:#e8e8e8;}}
</style>
</head><body>
<h1>H62 Intraday Half-Hour Cross-Sectional Seasonality — Gate 1 Report</h1>
<div class="warn">
  <strong>⚠ DATA NOTE:</strong> This report is based on <strong>SYNTHETIC 30-minute bars</strong>
  derived from real daily OHLCV data. yfinance does not provide 30m historical data beyond 60 days.
  These results represent a <strong>null-hypothesis baseline</strong> (no embedded seasonality)
  and are NOT a valid Gate 1 assessment. Historical 30m data from a commercial provider is required
  for a valid run.
</div>
<h2>Summary</h2>
<table>
  <tr><th>Metric</th><th>Value</th><th>Threshold</th><th>Result</th></tr>
  <tr><td>IS Sharpe</td><td>{metrics['is_sharpe']:.4f}</td><td>&gt; 1.0</td><td>{'PASS' if metrics['is_sharpe'] > 1.0 else 'FAIL'}</td></tr>
  <tr><td>OOS Sharpe</td><td>{metrics['oos_sharpe']:.4f}</td><td>&gt; 0.7</td><td>{'PASS' if metrics['oos_sharpe'] > 0.7 else 'FAIL'}</td></tr>
  <tr><td>IS MDD</td><td>{metrics['is_mdd']:.2%}</td><td>&gt; -20%</td><td>{'PASS' if metrics['is_mdd'] > -0.20 else 'FAIL'}</td></tr>
  <tr><td>OOS MDD</td><td>{metrics['oos_mdd']:.2%}</td><td>&gt; -20%</td><td>{'PASS' if metrics['oos_mdd'] > -0.20 else 'FAIL'}</td></tr>
  <tr><td>IS Trades</td><td>{metrics['is_trades']:,}</td><td>&gt; 300</td><td>{'PASS' if metrics['is_trades'] > 300 else 'FAIL'}</td></tr>
  <tr><td>Profit/Trade</td><td>{metrics['profit_per_trade_bps']:.2f} bps</td><td>&gt; 5 bps</td><td>{'PASS' if metrics['profit_per_trade_bps'] > 5.0 else 'FAIL'}</td></tr>
  <tr><td>Cost/Gross</td><td>{metrics['cost_to_gross_ratio']:.4f}</td><td>&lt; 0.40</td><td>{'PASS' if metrics['cost_to_gross_ratio'] < 0.40 else 'FAIL'}</td></tr>
  <tr><td>WF Passed</td><td>{metrics['wf_windows_passed']}/6</td><td>≥ 3</td><td>{'PASS' if metrics['wf_windows_passed'] >= 3 else 'FAIL'}</td></tr>
  <tr><td>MC p5 Sharpe</td><td>{metrics['mc_p5_sharpe']:.4f}</td><td>&gt; 0.5</td><td>{'PASS' if metrics['mc_p5_sharpe'] > 0.5 else 'FAIL'}</td></tr>
  <tr><td>Permutation p-val</td><td>{metrics['permutation_pvalue']:.4f}</td><td>&lt; 0.05</td><td>{'PASS' if metrics['permutation_test_pass'] else 'FAIL'}</td></tr>
</table>
<h2>Walk-Forward Table</h2>
<table>
  <tr><th>Win</th><th>IS Start</th><th>IS End</th><th>OOS Start</th><th>OOS End</th><th>IS Sharpe</th><th>OOS Sharpe</th></tr>
  {''.join(f"<tr><td>{w['window']}</td><td>{w['is_start']}</td><td>{w['is_end']}</td><td>{w['oos_start']}</td><td>{w['oos_end']}</td><td>{w['is_sharpe']:.4f}</td><td>{w['oos_sharpe']:.4f}</td></tr>" for w in wf_results)}
</table>
<h2>Bucket Breakdown (IS Sharpe)</h2>
<table>
  <tr><th>Bucket</th><th>Time</th><th>IS Sharpe</th></tr>
  {''.join(f"<tr><td>h={b}</td><td>{BUCKET_STARTS[b]}</td><td>{s:.4f}</td></tr>" for b, s in sorted(bucket_sharpes_is.items()))}
</table>
<h2>Full Verdict</h2>
<pre>{verdict_text}</pre>
</body></html>"""
    html_path = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}_report.html"
    html_path.write_text(html_content)
    logger.info("HTML report saved: %s", html_path)

    logger.info(
        "H62 COMPLETE | IS Sharpe=%.4f | OOS Sharpe=%.4f | IS MDD=%.2f%% | "
        "IS Trades=%d | WF Passed=%d/6 | MC p5=%.4f | Perm p=%.4f",
        metrics["is_sharpe"], metrics["oos_sharpe"],
        metrics["is_mdd"] * 100, metrics["is_trades"],
        metrics["wf_windows_passed"],
        metrics.get("mc_p5_sharpe", 0.0),
        metrics.get("permutation_pvalue", 1.0),
    )
    logger.info("VERDICT: %s", overall_verdict)

    return metrics, overall_verdict, str(metrics_path), str(verdict_path), str(html_path)


if __name__ == "__main__":
    result = main()
    metrics, verdict, metrics_path, verdict_path, html_path = result
    print("\n" + "=" * 60)
    print(f"VERDICT: {verdict}")
    print(f"Metrics: {metrics_path}")
    print(f"Verdict: {verdict_path}")
    print(f"Report:  {html_path}")
    print("=" * 60)
