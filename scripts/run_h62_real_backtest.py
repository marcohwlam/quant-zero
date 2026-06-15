"""
H62 Gate 1 v2.2 Backtest Runner — REAL DATA (Alpaca SIP 30m bars)
Run date: 2026-06-10

Reads strategies/data/h62/bars_30m.parquet produced by fetch_alpaca_bars.py.
Converts Alpaca long-format to strategy-compatible MultiIndex format.
Runs full Gate 1 v2.2 pipeline: IS/OOS, 6 WF windows, statistical rigor.
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

warnings.filterwarnings("ignore")

# Load broker credentials from .env if not already in environment
_ENV_PATH = Path(__file__).resolve().parent / "broker" / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k = _k.strip()
        _v = _v.strip().strip("'\"")
        if _k and _k not in os.environ:
            os.environ[_k] = _v

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("h62_real")

_ROOT = Path(__file__).resolve().parent
_BACKTEST_DIR = _ROOT / "backtests"
_DATA_DIR = _ROOT / "strategies" / "data" / "h62"
_BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

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


def load_alpaca_parquet() -> pd.DataFrame:
    """
    Load bars_30m.parquet (long format) and pivot to MultiIndex (ticker, field).
    Returns DataFrame with ET-localized DatetimeTZ index, filtered to RTH.
    """
    parquet_path = _DATA_DIR / "bars_30m.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(f"bars_30m.parquet not found at {parquet_path}. Run fetch_alpaca_bars.py first.")

    logger.info("Loading %s", parquet_path)
    df = pd.read_parquet(parquet_path)
    logger.info("Loaded %d rows × %d cols", len(df), len(df.columns))

    # Alpaca timestamps are UTC — convert to ET
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df["timestamp"] = df["timestamp"].dt.tz_convert("America/New_York")

    # RTH filter: 09:30 ≤ time < 16:00
    bar_time = df["timestamp"].dt.time
    rth_mask = (bar_time >= pd.Timestamp("09:30").time()) & (bar_time < pd.Timestamp("16:00").time())
    df = df[rth_mask].copy()
    logger.info("After RTH filter: %d rows", len(df))

    # Pivot to MultiIndex: index=timestamp, columns=(ticker, field)
    df = df.set_index("timestamp").sort_index()
    df.columns.name = "field"

    fields = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    frames = []
    for ticker in UNIVERSE:
        sub = df[df["symbol"] == ticker][fields].copy() if "symbol" in df.columns else pd.DataFrame()
        if sub.empty:
            continue
        sub = sub.rename(columns=str.capitalize)  # open→Open, close→Close, etc.
        sub.columns = pd.MultiIndex.from_tuples(
            [(ticker, c) for c in sub.columns], names=["ticker", "field"]
        )
        frames.append(sub)

    if not frames:
        raise RuntimeError("No ticker data after pivot — check parquet content")

    combined = pd.concat(frames, axis=1).sort_index()
    logger.info("MultiIndex intraday: %d rows × %d cols", len(combined), len(combined.columns))
    return combined


def build_bucket_returns(intraday: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    """Build bucket return records from real intraday data."""
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
        raise RuntimeError("No bucket return records built from Alpaca data")
    return pd.DataFrame(records)


def build_signals(bucket_df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """5-day rolling same-bucket signal — shift(1) prevents look-ahead."""
    window = params["signal_window"]
    pivot = bucket_df.pivot_table(
        index="date", columns=["ticker", "bucket"], values="bucket_ret", aggfunc="mean"
    )
    pivot = pivot.sort_index()
    signal = pivot.shift(1).rolling(window=window, min_periods=window).mean()
    signal_long = signal.stack(level=[0, 1], future_stack=True).reset_index()
    signal_long.columns = ["date", "ticker", "bucket", "signal"]
    return signal_long.dropna(subset=["signal"])


def build_daily_risk_metrics(intraday: pd.DataFrame, universe: list[str], params: dict) -> pd.DataFrame:
    """Compute 20d rolling sigma and ADV from intraday close prices, shifted 1 day."""
    records = {}
    for ticker in universe:
        try:
            c_col = (ticker, "Close")
            v_col = (ticker, "Volume")
            if c_col not in intraday.columns:
                continue
            # Daily close = last bar of each trading day
            daily_close = intraday[c_col].resample("1B").last().dropna()
            daily_volume = intraday[v_col].resample("1B").sum().dropna() if v_col in intraday.columns else None
            ret = daily_close.pct_change()
            sigma = ret.rolling(params["sigma_window"]).std().shift(1)
            if daily_volume is not None:
                adv = daily_volume.rolling(params["adv_window"]).mean().shift(1)
            else:
                adv = pd.Series(1e6, index=sigma.index)
            tdf = pd.DataFrame({"sigma_20d": sigma, "adv_20d": adv})
            tdf.index = pd.to_datetime(tdf.index).normalize()
            records[ticker] = tdf
        except Exception as exc:
            logger.debug("Risk metrics failed %s: %s", ticker, exc)
    if not records:
        raise RuntimeError("No daily risk metrics computed")
    combined = pd.concat(records, axis=1)
    combined.columns.names = ["ticker", "metric"]
    return combined


def compute_cost(entry_price, shares, sigma, adv, params):
    fixed = params["fixed_per_share"] * shares
    slippage = params["slippage_pct"] * entry_price * shares
    impact_frac = params["market_impact_k"] * sigma * math.sqrt(shares / (adv + 1e-10))
    impact = impact_frac * entry_price * shares
    total = fixed + slippage + impact
    liquidity_flag = (shares / (adv + 1e-10)) > 0.01
    return total, liquidity_flag


def run_backtest_period(
    signal_df: pd.DataFrame,
    intraday: pd.DataFrame,
    risk_metrics: pd.DataFrame,
    start: str, end: str,
    params: dict,
    universe: list[str],
) -> tuple[pd.Series, pd.DataFrame, float]:
    start_dt = pd.Timestamp(start).normalize()
    end_dt = pd.Timestamp(end).normalize()
    mask = (signal_df["date"] >= start_dt) & (signal_df["date"] <= end_dt)
    period_signals = signal_df[mask].copy()

    long_q, short_q = params["long_quantile"], params["short_quantile"]
    disp_min = params["dispersion_min_std"]
    cap_per_side = params["long_capital"]
    n_universe = len(universe)
    top_n = max(1, round(n_universe * (1.0 - long_q)))
    bot_n = max(1, round(n_universe * short_q))

    # Build price lookup: (date, bucket_idx, ticker) → (open, close)
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
        per_long_cap = cap_per_side / max(len(long_set), 1)
        per_short_cap = cap_per_side / max(len(short_set), 1)
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
                    "liquidity_flag": liq_e or liq_x,
                })

        if not long_gross_rets and not short_gross_rets:
            continue

        gross_port = (
            0.5 * float(np.mean(long_gross_rets)) if long_gross_rets else 0.0
        ) + (
            0.5 * float(np.mean(short_gross_rets)) if short_gross_rets else 0.0
        )
        total_cap = long_cap_used + short_cap_used
        total_cost = long_cost_usd + short_cost_usd
        net_port = gross_port - (total_cost / total_cap if total_cap > 0 else 0.0)

        d_key = day.date() if hasattr(day, "date") else day
        daily_returns[d_key] = daily_returns.get(d_key, 0.0) + net_port

    rets = pd.Series(daily_returns, dtype=float).sort_index()
    rets.index = pd.to_datetime(rets.index)
    disp_pct = dispersion_skips / max(total_bucket_days, 1) * 100.0
    logger.info("Period %s→%s: %d bucket-days, %d skipped, %d trades",
                start, end, total_bucket_days, dispersion_skips, len(trade_records))
    return rets, pd.DataFrame(trade_records), disp_pct


def sharpe_ratio(returns: pd.Series, ann_factor: int = 252) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * math.sqrt(ann_factor))


def max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    cum = (1 + returns).cumprod()
    rolling_max = cum.cummax()
    return float(((cum - rolling_max) / rolling_max).min())


def monte_carlo_sharpe(daily_rets: np.ndarray, n_sims: int = 10000) -> dict:
    if len(daily_rets) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    rng = np.random.default_rng(42)
    sharpes = []
    for _ in range(n_sims):
        sample = rng.choice(daily_rets, size=len(daily_rets), replace=True)
        sharpes.append(float(sample.mean() / (sample.std() + 1e-8) * math.sqrt(252)))
    return {
        "mc_p5_sharpe": float(np.percentile(sharpes, 5)),
        "mc_median_sharpe": float(np.median(sharpes)),
        "mc_p95_sharpe": float(np.percentile(sharpes, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    if len(returns) < 10:
        return {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0}
    T = len(returns)
    block_len = max(1, int(math.sqrt(T)))
    rng = np.random.default_rng(42)
    sharpes = []
    for _ in range(n_boots):
        n_blocks = T // block_len + 1
        starts = rng.integers(0, T - block_len + 1, size=n_blocks)
        sample = np.concatenate([returns[s:s + block_len] for s in starts])[:T]
        sharpes.append(float(sample.mean() / (sample.std() + 1e-8) * math.sqrt(252)))
    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
    }


def permutation_test(daily_rets: np.ndarray, observed_sharpe: float, n_perms: int = 1000) -> dict:
    if len(daily_rets) < 10:
        return {"permutation_pvalue": 1.0, "permutation_test_pass": False}
    rng = np.random.default_rng(42)
    permuted = [float(rng.permutation(daily_rets).mean() / (rng.permutation(daily_rets).std() + 1e-8) * math.sqrt(252))
                for _ in range(n_perms)]
    p = float(np.mean(np.array(permuted) >= observed_sharpe))
    return {"permutation_pvalue": round(p, 4), "permutation_test_pass": p <= 0.05}


def build_bucket_breakdown(is_trades: pd.DataFrame) -> dict:
    """Bucket-by-bucket IS Sharpe, mean net return, trade count, % sessions active."""
    breakdown = {}
    if is_trades.empty:
        return breakdown
    total_dates = is_trades["date"].nunique() if "date" in is_trades.columns else 1
    for b_idx in ACTIVE_BUCKETS:
        b_trades = is_trades[is_trades["bucket_idx"] == b_idx]
        if b_trades.empty:
            breakdown[b_idx] = {"sharpe": 0.0, "mean_net_ret_bps": 0.0, "trade_count": 0, "pct_sessions_active": 0.0}
            continue
        b_rets = b_trades.groupby("date")["net_ret_pct"].mean() / 100.0
        b_rets.index = pd.to_datetime(b_rets.index)
        bucket_dates = b_trades["date"].nunique()
        breakdown[b_idx] = {
            "sharpe": round(sharpe_ratio(b_rets), 4),
            "mean_net_ret_bps": round(float(b_trades["net_ret_pct"].mean() * 100), 4),
            "trade_count": len(b_trades),
            "pct_sessions_active": round(bucket_dates / max(total_dates, 1) * 100, 2),
            "bucket_time": BUCKET_STARTS[b_idx],
        }
    return breakdown


def build_verdict_text(metrics: dict, run_date: str) -> str:
    is_sh = metrics["is_sharpe"]
    oos_sh = metrics["oos_sharpe"]
    is_mdd = metrics["is_mdd"]
    oos_mdd = metrics["oos_mdd"]
    is_trades = metrics["is_trades"]
    ppt = metrics["profit_per_trade_bps"]
    c2g = metrics["cost_to_gross_ratio"]
    perm_p = metrics.get("permutation_pvalue", 1.0)
    mc_p5 = metrics.get("mc_p5_sharpe", 0.0)
    bs_lo = metrics.get("sharpe_ci_low", 0.0)
    bs_hi = metrics.get("sharpe_ci_high", 0.0)
    wf_var = metrics.get("wf_sharpe_std", 0.0)
    wf_passed = metrics["wf_windows_passed"]

    checks = {
        "IS Sharpe > 1.0": is_sh > 1.0,
        "OOS Sharpe > 0.7": oos_sh > 0.7,
        "IS MDD > -20%": is_mdd > -0.20,
        "OOS MDD > -20%": oos_mdd > -0.20,
        "IS Trades > 300": is_trades > 300,
        "Profit/Trade > 5 bps": ppt > 5.0,
        "Cost/Gross < 0.40": c2g < 0.40,
        "WF passed ≥ 3/6": wf_passed >= 3,
        "Permutation p < 0.05": perm_p <= 0.05,
        "MC p5 Sharpe > 0.5": mc_p5 > 0.5,
    }
    auto_disq = []
    if c2g >= 0.40:
        auto_disq.append(f"Cost/Gross ≥ 0.40 ({c2g:.4f})")
    if is_trades < 300:
        auto_disq.append(f"IS trade count < 300 ({is_trades})")
    if oos_mdd < -0.40:
        auto_disq.append(f"OOS MDD {oos_mdd:.1%} exceeds 2× threshold")

    passed_n = sum(checks.values())
    total_n = len(checks)
    if auto_disq:
        verdict = "FAIL"
    elif passed_n >= total_n * 0.8:
        verdict = "PASS"
    elif passed_n >= total_n * 0.6:
        verdict = "CONDITIONAL PASS"
    else:
        verdict = "FAIL"

    lines = [
        "=" * 60,
        "GATE 1 v2.2 VERDICT REPORT — H62",
        f"Run Date: {run_date}",
        f"Data Source: Alpaca SIP 30m bars (REAL DATA)",
        "=" * 60,
        "",
        f"VERDICT: {verdict}",
        "",
        f"IS Sharpe:   {is_sh:.4f}",
        f"OOS Sharpe:  {oos_sh:.4f}",
        f"IS MDD:      {is_mdd:.2%}",
        f"OOS MDD:     {oos_mdd:.2%}",
        f"IS trades:   {is_trades:,}",
        f"Permutation p-value: {perm_p:.4f}",
        f"MC p5 Sharpe: {mc_p5:.4f}",
        f"Bootstrap CI: [{bs_lo:.4f}, {bs_hi:.4f}]",
        f"WF variance: {wf_var:.4f}",
        "",
        "CORE METRICS",
        "-" * 40,
    ]
    for name, passed in checks.items():
        lines.append(f"  {'[PASS]' if passed else '[FAIL]'} {name}")

    lines += [
        "",
        "WALK-FORWARD TABLE",
        "-" * 40,
        f"{'Win':>3}  {'IS Start':>10}  {'IS End':>10}  {'OOS Start':>10}  {'OOS End':>10}  {'IS Sharpe':>9}  {'OOS Sharpe':>10}",
    ]
    for w in metrics.get("wf_sharpe_by_window", []):
        lines.append(
            f"{w['window']:>3}  {w['is_start']:>10}  {w['is_end']:>10}  "
            f"{w['oos_start']:>10}  {w['oos_end']:>10}  "
            f"{w['is_sharpe']:>9.4f}  {w['oos_sharpe']:>10.4f}"
        )

    lines += [
        "",
        "BUCKET BREAKDOWN (IS)",
        "-" * 40,
        f"{'Bucket':>8}  {'Time':>5}  {'Sharpe':>7}  {'MeanNet bps':>11}  {'Trades':>7}  {'%Active':>7}",
    ]
    for b_idx, bd in sorted(metrics.get("bucket_breakdown", {}).items()):
        lines.append(
            f"  h={b_idx:>2}  {bd.get('bucket_time','?'):>5}  "
            f"{bd['sharpe']:>7.4f}  {bd['mean_net_ret_bps']:>11.2f}  "
            f"{bd['trade_count']:>7}  {bd['pct_sessions_active']:>6.1f}%"
        )

    if auto_disq:
        lines += ["", "AUTO-DISQUALIFICATION", "-" * 40]
        for f in auto_disq:
            lines.append(f"  ✗ {f}")

    lines += [
        "",
        f"CHECKS: {passed_n}/{total_n} passed",
        "=" * 60,
    ]
    return "\n".join(lines)


def main() -> dict:
    run_date = date.today().isoformat()
    logger.info("H62 Gate 1 v2.2 REAL DATA run — %s", run_date)

    # 1. Load real Alpaca data
    intraday = load_alpaca_parquet()

    # 2. Bucket returns + signals
    logger.info("Building bucket returns from real data...")
    bucket_df = build_bucket_returns(intraday, UNIVERSE)
    logger.info("Bucket records: %d", len(bucket_df))

    logger.info("Building signals...")
    signal_df = build_signals(bucket_df, PARAMETERS)
    logger.info("Signal records: %d", len(signal_df))

    # 3. Daily risk metrics
    logger.info("Building daily risk metrics...")
    risk_metrics = build_daily_risk_metrics(intraday, UNIVERSE, PARAMETERS)

    # 4. IS backtest
    logger.info("IS backtest %s → %s", PARAMETERS["is_start"], PARAMETERS["is_end"])
    is_rets, is_trades, is_disp_pct = run_backtest_period(
        signal_df, intraday, risk_metrics,
        PARAMETERS["is_start"], PARAMETERS["is_end"], PARAMETERS, UNIVERSE,
    )

    # 5. OOS / holdout (2024)
    logger.info("OOS backtest %s → %s", PARAMETERS["oos_start"], PARAMETERS["oos_end"])
    oos_rets, oos_trades, oos_disp_pct = run_backtest_period(
        signal_df, intraday, risk_metrics,
        PARAMETERS["oos_start"], PARAMETERS["oos_end"], PARAMETERS, UNIVERSE,
    )

    # 6. Walk-forward (6 windows)
    wf_results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(PARAMETERS["wf_windows"], 1):
        logger.info("WF%d: %s → %s / %s → %s", i, is_s, is_e, oos_s, oos_e)
        wf_is, wf_is_tr, _ = run_backtest_period(signal_df, intraday, risk_metrics, is_s, is_e, PARAMETERS, UNIVERSE)
        wf_oos, wf_oos_tr, _ = run_backtest_period(signal_df, intraday, risk_metrics, oos_s, oos_e, PARAMETERS, UNIVERSE)
        is_sh_w = sharpe_ratio(wf_is)
        oos_sh_w = sharpe_ratio(wf_oos)
        wf_results.append({
            "window": i,
            "is_start": is_s, "is_end": is_e,
            "oos_start": oos_s, "oos_end": oos_e,
            "is_sharpe": round(is_sh_w, 4),
            "oos_sharpe": round(oos_sh_w, 4),
            "is_trades": len(wf_is_tr),
            "oos_trades": len(wf_oos_tr),
            "is_mdd": round(max_drawdown(wf_is), 4),
            "oos_mdd": round(max_drawdown(wf_oos), 4),
        })
        logger.info("  WF%d IS=%.4f OOS=%.4f", i, is_sh_w, oos_sh_w)

    wf_oos_sharpes = [w["oos_sharpe"] for w in wf_results]
    wf_windows_passed = sum(1 for s in wf_oos_sharpes if s > 0.7)

    # 7. Bucket breakdown
    bucket_breakdown = build_bucket_breakdown(is_trades)

    # 8. Aggregate cost metrics
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

    # 9. Statistical rigor pipeline
    is_rets_arr = is_rets.values if not is_rets.empty else np.array([])
    logger.info("Monte Carlo (10000 sims)...")
    mc = monte_carlo_sharpe(is_rets_arr, n_sims=10000)

    logger.info("Block bootstrap CI (1000 boots)...")
    ci = block_bootstrap_ci(is_rets_arr, n_boots=1000)

    logger.info("Permutation test (1000 perms)...")
    perm = permutation_test(is_rets_arr, is_sh, n_perms=1000)

    wf_std = float(np.std(wf_oos_sharpes)) if len(wf_oos_sharpes) > 1 else 0.0
    wf_std_flag = wf_std > 1.5

    # 10. Full metrics dict
    metrics = {
        "strategy_name": "H62_intraday_half_hour_seasonality",
        "date": run_date,
        "asset_class": "equities",
        "data_source": "Alpaca_SIP_30m_real_data",
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
        "wf_oos_sharpe_mean": round(float(np.mean(wf_oos_sharpes)), 4),
        "wf_oos_sharpe_min": round(float(np.min(wf_oos_sharpes)), 4),
        "wf_windows_passed": wf_windows_passed,
        "wf_sharpe_std": round(wf_std, 4),
        "wf_sharpe_std_flag": wf_std_flag,
        "bucket_breakdown": {str(k): v for k, v in bucket_breakdown.items()},
        "dispersion_filter_skips_pct": round((is_disp_pct + oos_disp_pct) / 2.0, 2),
        "liquidity_constrained_pct": round(liq_pct, 2),
        "mc_p5_sharpe": round(mc["mc_p5_sharpe"], 4),
        "mc_median_sharpe": round(mc["mc_median_sharpe"], 4),
        "mc_p95_sharpe": round(mc["mc_p95_sharpe"], 4),
        "sharpe_ci_low": round(ci["sharpe_ci_low"], 4),
        "sharpe_ci_high": round(ci["sharpe_ci_high"], 4),
        "permutation_pvalue": perm["permutation_pvalue"],
        "permutation_test_pass": perm["permutation_test_pass"],
        "holdout_sharpe_2024": round(oos_sh, 4),
        "holdout_mdd_2024": round(oos_mdd, 4),
        "look_ahead_bias_flag": False,
        "same_bar_fill_flag": False,
        "synthetic_data": False,
        "universe_size": len(UNIVERSE),
        "active_buckets": ACTIVE_BUCKETS,
    }

    # 11. Build verdict
    verdict_text = build_verdict_text(metrics, run_date)
    verdict_line = [l for l in verdict_text.split("\n") if l.startswith("VERDICT:")]
    overall_verdict = verdict_line[0].replace("VERDICT: ", "").strip() if verdict_line else "FAIL"

    # 12. Save trade CSV
    trade_csv = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}_trades.csv"
    all_trades.to_csv(trade_csv, index=False)
    logger.info("Trades: %s (%d rows)", trade_csv, len(all_trades))

    # 13. Save metrics JSON
    metrics_path = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info("Metrics: %s", metrics_path)

    # 14. Save verdict TXT
    verdict_path = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}.txt"
    verdict_path.write_text(verdict_text)
    logger.info("Verdict: %s", verdict_path)

    # 15. HTML report
    wf_rows = "".join(
        f"<tr><td>{w['window']}</td><td>{w['is_start']}–{w['is_end']}</td>"
        f"<td>{w['oos_start']}–{w['oos_end']}</td>"
        f"<td>{w['is_sharpe']:.4f}</td><td>{w['oos_sharpe']:.4f}</td>"
        f"<td>{w['is_trades']}</td><td>{w['oos_trades']}</td></tr>"
        for w in wf_results
    )
    bucket_rows = "".join(
        f"<tr><td>h={b}</td><td>{bd.get('bucket_time','?')}</td><td>{bd['sharpe']:.4f}</td>"
        f"<td>{bd['mean_net_ret_bps']:.2f}</td><td>{bd['trade_count']}</td>"
        f"<td>{bd['pct_sessions_active']:.1f}%</td></tr>"
        for b, bd in sorted(bucket_breakdown.items())
    )
    verdict_color = "#27ae60" if overall_verdict == "PASS" else "#e74c3c"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>H62 Gate 1 Report — {run_date}</title>
<style>
  body{{font-family:sans-serif;margin:40px;background:#f9f9f9;}}
  table{{border-collapse:collapse;width:100%;margin-bottom:24px;}}
  th,td{{border:1px solid #ccc;padding:6px 10px;text-align:left;}}
  th{{background:#e8e8e8;}}
  .verdict{{font-size:2em;font-weight:bold;color:{verdict_color};margin:20px 0;}}
  .metric{{display:inline-block;min-width:160px;padding:12px;margin:6px;
           background:white;border:1px solid #ddd;border-radius:4px;}}
  .metric-val{{font-size:1.4em;font-weight:bold;}}
  .pass{{color:#27ae60;}} .fail{{color:#e74c3c;}}
  pre{{background:#fff;border:1px solid #ddd;padding:20px;white-space:pre-wrap;font-size:13px;}}
</style>
</head><body>
<h1>H62 Intraday Half-Hour Cross-Sectional Seasonality — Gate 1 v2.2</h1>
<p>Run date: {run_date} | Data: Alpaca SIP 30m (REAL) | Universe: {len(UNIVERSE)} tickers</p>
<div class="verdict">VERDICT: {overall_verdict}</div>
<h2>Core Metrics</h2>
<div>
  <div class="metric"><div>IS Sharpe</div><div class="metric-val {'pass' if is_sh>1.0 else 'fail'}">{is_sh:.4f}</div></div>
  <div class="metric"><div>OOS Sharpe</div><div class="metric-val {'pass' if oos_sh>0.7 else 'fail'}">{oos_sh:.4f}</div></div>
  <div class="metric"><div>IS MDD</div><div class="metric-val {'pass' if is_mdd>-0.20 else 'fail'}">{is_mdd:.2%}</div></div>
  <div class="metric"><div>OOS MDD</div><div class="metric-val {'pass' if oos_mdd>-0.20 else 'fail'}">{oos_mdd:.2%}</div></div>
  <div class="metric"><div>IS Trades</div><div class="metric-val {'pass' if len(is_trades)>300 else 'fail'}">{len(is_trades):,}</div></div>
  <div class="metric"><div>Profit/Trade</div><div class="metric-val {'pass' if profit_per_trade_bps>5 else 'fail'}">{profit_per_trade_bps:.2f} bps</div></div>
  <div class="metric"><div>Cost/Gross</div><div class="metric-val {'pass' if cost_to_gross<0.40 else 'fail'}">{cost_to_gross:.4f}</div></div>
  <div class="metric"><div>WF Passed</div><div class="metric-val {'pass' if wf_windows_passed>=3 else 'fail'}">{wf_windows_passed}/6</div></div>
  <div class="metric"><div>MC p5 Sharpe</div><div class="metric-val {'pass' if mc['mc_p5_sharpe']>0.5 else 'fail'}">{mc['mc_p5_sharpe']:.4f}</div></div>
  <div class="metric"><div>Permutation p</div><div class="metric-val {'pass' if perm['permutation_test_pass'] else 'fail'}">{perm['permutation_pvalue']:.4f}</div></div>
</div>
<h2>Walk-Forward Table</h2>
<table>
  <tr><th>Win</th><th>IS Period</th><th>OOS Period</th><th>IS Sharpe</th><th>OOS Sharpe</th><th>IS Trades</th><th>OOS Trades</th></tr>
  {wf_rows}
</table>
<h2>Bucket Breakdown (IS)</h2>
<table>
  <tr><th>Bucket</th><th>Time</th><th>IS Sharpe</th><th>Mean Net (bps)</th><th>Trades</th><th>% Active</th></tr>
  {bucket_rows}
</table>
<h2>Statistical Tests</h2>
<table>
  <tr><th>Test</th><th>Value</th><th>Threshold</th><th>Result</th></tr>
  <tr><td>MC p5 Sharpe</td><td>{mc['mc_p5_sharpe']:.4f}</td><td>&gt; 0.5</td><td class="{'pass' if mc['mc_p5_sharpe']>0.5 else 'fail'}">{'PASS' if mc['mc_p5_sharpe']>0.5 else 'FAIL'}</td></tr>
  <tr><td>MC Median Sharpe</td><td>{mc['mc_median_sharpe']:.4f}</td><td>—</td><td>—</td></tr>
  <tr><td>Bootstrap Sharpe CI</td><td>[{ci['sharpe_ci_low']:.4f}, {ci['sharpe_ci_high']:.4f}]</td><td>—</td><td>—</td></tr>
  <tr><td>Permutation p-value</td><td>{perm['permutation_pvalue']:.4f}</td><td>&lt; 0.05</td><td class="{'pass' if perm['permutation_test_pass'] else 'fail'}">{'PASS' if perm['permutation_test_pass'] else 'FAIL'}</td></tr>
  <tr><td>WF OOS Sharpe Std</td><td>{wf_std:.4f}</td><td>&lt; 1.5</td><td class="{'fail' if wf_std_flag else 'pass'}">{'FLAG' if wf_std_flag else 'OK'}</td></tr>
</table>
<h2>Full Verdict</h2>
<pre>{verdict_text}</pre>
</body></html>"""
    html_path = _BACKTEST_DIR / f"h62_intraday_half_hour_seasonality_{run_date}_report.html"
    html_path.write_text(html)
    logger.info("HTML: %s", html_path)

    logger.info(
        "DONE | IS Sharpe=%.4f | OOS Sharpe=%.4f | IS MDD=%.2f%% | IS Trades=%d | WF Passed=%d/6 | MC p5=%.4f | Perm p=%.4f",
        is_sh, oos_sh, is_mdd * 100, len(is_trades), wf_windows_passed,
        mc["mc_p5_sharpe"], perm["permutation_pvalue"],
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
