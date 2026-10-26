"""
Gate 1 v2.0 Threshold Calibration — Proper Intraday Baseline
QUA-244: Replaces RSI(2) from QUA-164 with VWAP deviation mean reversion.

Problem (QUA-244): RSI(2) at 1-min resolution → ~3-min median hold, capturing noise.
Solution: VWAP deviation mean reversion, long+short, targets 15–120 min holds.
         More representative of live intraday strategies (H60 family).

Universe: SPY, QQQ (Alpaca/IEX 1-min bars from minute_bars.db)
Period: 2022-01-03 to 2024-12-31 (same as QUA-164)
Strategy: Fade price deviations ≥ENTRY_Z σ from session VWAP; exit on reversion or EOD.
Cost: $0.005/share fixed + slippage (ED-SLIP-001) + 0.1×σ×sqrt(Q/ADV) market impact
ADV: yfinance total-market (QUA-243 fix applied)
Output: backtests/gate1_v2_calibration_intraday_baseline_2026-06-15.json
Prior baseline: backtests/gate1_v2_calibration_minutebar_2026-06-13.json (RSI(2), QUA-164)
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipelines"))
from minute_bar_store import MinuteBarStore  # noqa: E402

# ── Config ─────────────────────────────────────────────────────────────────────
UNIVERSE = ["SPY", "QQQ"]

# Same 6 windows as QUA-164: 3-month IS / 1-month OOS spanning 2022–2024
WINDOWS = [
    (1, "2022-01-01", "2022-03-31", "2022-04-01", "2022-04-30"),
    (2, "2022-07-01", "2022-09-30", "2022-10-01", "2022-10-31"),
    (3, "2023-01-01", "2023-03-31", "2023-04-01", "2023-04-30"),
    (4, "2023-07-01", "2023-09-30", "2023-10-01", "2023-10-31"),
    (5, "2024-01-01", "2024-03-31", "2024-04-01", "2024-04-30"),
    (6, "2024-07-01", "2024-09-30", "2024-10-01", "2024-10-31"),
]

TRADING_DAYS_PER_YEAR = 252
MINUTES_PER_SESSION = 390
TRADING_MINUTES_PER_YEAR = TRADING_DAYS_PER_YEAR * MINUTES_PER_SESSION  # 98,280
ANNUALIZE_FACTOR = np.sqrt(TRADING_MINUTES_PER_YEAR)

# All tunable strategy parameters
PARAMETERS = {
    "ENTRY_Z": 1.5,            # enter when |vwap_z| > ENTRY_Z (Avellaneda-Lee, adapted)
    "EXIT_Z": 0.25,            # exit when |vwap_z| < EXIT_Z (reversion near VWAP)
    "STOP_Z": 3.0,             # stop-loss when deviation widens (informed flow signal)
    "LOOKBACK_BARS": 30,       # rolling window for z-score denominator (30 min, Kissell 2014)
    "TIME_STOP_BARS": 60,      # max hold 60 bars = 60 min (2× estimated VWAP half-life)
    "TRADE_START_ET": "10:30", # skip opening auction volatility spike
    "TRADE_END_ET": "14:30",   # stop new entries before close-rush regime shift
    "EOD_EXIT_ET": "15:00",    # hard intraday-flat rule (no overnight holds)
    "POSITION_VALUE": 10_000.0,  # $ per trade leg (matches QUA-164 calibration)
}

FIXED_COST_PER_SHARE = 0.005   # canonical equities fixed cost (AGENTS.md)
MI_K = 0.1                     # Almgren-Chriss square-root market impact coefficient

# ED-SLIP-001: ultra-liquid ETF slippage overrides (conservative vs 0.5 bps floor)
SLIPPAGE_OVERRIDES = {
    "SPY": 0.00015,    # 1.5 bps one-way
    "QQQ": 0.00020,    # 2.0 bps one-way
    "default": 0.00050,
}

MARKET_OPEN_TIME = pd.Timestamp("09:30").time()
MARKET_CLOSE_TIME = pd.Timestamp("15:59").time()


# ── VWAP and z-score ───────────────────────────────────────────────────────────

def compute_session_vwap(df_et: pd.DataFrame) -> pd.Series:
    """
    Session VWAP using typical price = (high + low + close) / 3.
    Resets at each ET calendar date (session open = 9:30). No look-ahead.
    """
    df = df_et.copy()
    df["_session"] = df.index.map(lambda ts: ts.strftime("%Y-%m-%d"))
    df["_typical"] = (df["high"] + df["low"] + df["close"]) / 3.0
    df["_tpv"] = df["_typical"] * df["volume"]

    vwap = pd.Series(np.nan, index=df.index)
    for _, grp in df.groupby("_session"):
        cum_tpv = grp["_tpv"].cumsum()
        cum_vol = grp["volume"].cumsum().replace(0, np.nan)
        vwap.loc[grp.index] = (cum_tpv / cum_vol).values
    return vwap


def compute_vwap_zscore(df_et: pd.DataFrame, lookback: int) -> pd.Series:
    """
    z = (close - session_vwap) / rolling_std(deviation, lookback).
    rolling_std uses only past bars — no look-ahead.
    Positive z → price above VWAP (short signal); negative z → below VWAP (long signal).
    """
    vwap = compute_session_vwap(df_et)
    deviation = df_et["close"] - vwap
    rolling_std = deviation.rolling(lookback, min_periods=max(5, lookback // 3)).std()
    return deviation / (rolling_std + 1e-10)


# ── Cost helpers ───────────────────────────────────────────────────────────────

def round_trip_cost_bps(price: float, shares: float, adv: float, sigma: float) -> float:
    """Round-trip fixed + market impact in bps. Slippage is embedded in fill prices."""
    fixed_bps = 2 * FIXED_COST_PER_SHARE / price * 10_000
    mi_bps = MI_K * sigma * np.sqrt(shares / (adv + 1e-8)) * 10_000
    return fixed_bps + mi_bps


# ── Data loading ───────────────────────────────────────────────────────────────

def load_ticker_data(
    store: MinuteBarStore, symbol: str, earliest: str, latest: str
) -> pd.DataFrame:
    """
    Load minute bars for [earliest, latest] + 30-day lookback buffer.
    Converts to America/New_York tz and filters to RTH (9:30–16:00 ET).
    """
    buf_start = (pd.Timestamp(earliest) - pd.Timedelta(days=30)).strftime(
        "%Y-%m-%dT00:00:00Z"
    )
    buf_end = pd.Timestamp(latest).strftime("%Y-%m-%dT23:59:59Z")

    df = store.get_bars(symbol, buf_start, buf_end)
    if df is None or df.empty:
        return pd.DataFrame()

    df.index = pd.to_datetime(df.index, utc=True)
    df = df.tz_convert("America/New_York")

    times = df.index.time
    mask = (times >= MARKET_OPEN_TIME) & (times <= MARKET_CLOSE_TIME)
    return df[mask]


def build_daily_stats(
    df_et: pd.DataFrame,
    ticker: str | None = None,
    yf_start: str | None = None,
    yf_end: str | None = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Rolling 20-day sigma and ADV indexed by date.
    ADV uses yfinance total-market volume (QUA-243 fix: IEX undercounts by ~8.7× for SPY).
    Falls back to IEX volume if yfinance download fails.
    """
    daily_close = df_et["close"].resample("1D").last().dropna()
    sigma_daily = (
        daily_close.pct_change().rolling(20, min_periods=5).std().fillna(0.015)
    )

    adv_daily = None
    if ticker and yf_start and yf_end:
        try:
            raw = yf.download(
                ticker, start=yf_start, end=yf_end,
                auto_adjust=True, progress=False,
            )
            # Handle MultiIndex columns from newer yfinance versions
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            yf_vol = raw["Volume"].squeeze().dropna()
            yf_vol.index = pd.to_datetime(yf_vol.index).normalize()
            adv_series = yf_vol.rolling(20, min_periods=5).mean()
            fallback = float(yf_vol.median()) if not yf_vol.empty else 9e7
            adv_daily = adv_series.fillna(fallback)
            adv_daily.index = adv_daily.index.date
        except Exception as exc:
            print(f"  [WARN] yfinance ADV download failed for {ticker}: {exc} — IEX fallback")

    if adv_daily is None:
        daily_volume = df_et["volume"].resample("1D").sum()
        daily_volume = daily_volume[daily_volume > 0]
        adv_daily = daily_volume.rolling(20, min_periods=5).mean().fillna(
            daily_volume.median() if not daily_volume.empty else 1e7
        )
        adv_daily.index = adv_daily.index.date

    sigma_by_date = sigma_daily.copy()
    sigma_by_date.index = sigma_by_date.index.date
    return sigma_by_date, adv_daily


# ── Strategy simulation ────────────────────────────────────────────────────────

def run_vwap_strategy_minute(
    df_et: pd.DataFrame,
    window_start: str,
    window_end: str,
    ticker: str,
    sigma_by_date: pd.Series,
    adv_by_date: pd.Series,
    params: dict = PARAMETERS,
) -> tuple[pd.Series, list[dict]]:
    """
    VWAP deviation mean reversion on 1-minute bars. Both long and short.

    Entry: signal at bar i (|vwap_z| > ENTRY_Z), fill at close of bar i+1.
           1-bar signal delay prevents look-ahead (consistent with QUA-164 RSI2 baseline).
    Exit:  (1) reversion |z| < EXIT_Z  (2) stop-loss |z| > STOP_Z
           (3) time stop after TIME_STOP_BARS  (4) EOD_EXIT_ET hard flat
    Cost:  slippage embedded in fill prices; fixed + MI deducted as bps cost.

    Returns: (minute_net_returns: pd.Series, trades: list[dict])
    """
    slippage = SLIPPAGE_OVERRIDES.get(ticker, SLIPPAGE_OVERRIDES["default"])
    pos_value = params["POSITION_VALUE"]
    entry_z = params["ENTRY_Z"]
    exit_z = params["EXIT_Z"]
    stop_z = params["STOP_Z"]
    lookback = params["LOOKBACK_BARS"]
    time_stop = params["TIME_STOP_BARS"]
    trade_start = params["TRADE_START_ET"]
    trade_end = params["TRADE_END_ET"]
    eod_exit = params["EOD_EXIT_ET"]

    ws = pd.Timestamp(window_start).date()
    we = pd.Timestamp(window_end).date()
    mask = (df_et.index.date >= ws) & (df_et.index.date <= we)
    seg = df_et[mask].copy()

    if len(seg) < lookback + 10:
        return pd.Series(dtype=float), []

    close_arr = seg["close"].values
    z_arr = compute_vwap_zscore(seg, lookback).values
    dates_arr = seg.index.date
    times_arr = np.array([ts.strftime("%H:%M") for ts in seg.index])
    n = len(seg)

    in_trade = False
    direction = 0        # +1 long, -1 short
    entry_fill = 0.0     # effective entry price after slippage
    entry_bar = 0        # index of entry fill bar
    entry_date = None    # date of entry (for sigma/ADV lookup)
    minute_net_pnl = np.zeros(n)
    trades = []

    for i in range(lookback + 1, n - 1):
        z = z_arr[i]
        if np.isnan(z):
            continue

        et_time = times_arr[i]
        next_is_new_session = dates_arr[i + 1] != dates_arr[i]
        is_eod = et_time >= eod_exit
        is_last_bar = et_time >= "15:59"

        if in_trade:
            bars_held = i - entry_bar + 1  # bars since fill, inclusive

            force_exit = is_eod or next_is_new_session or is_last_bar
            if force_exit:
                exit_reason = "eod_flat"
            elif abs(z) < exit_z:
                exit_reason = "reversion"
            elif abs(z) > stop_z:
                exit_reason = "stop_loss"
            elif bars_held >= time_stop:
                exit_reason = "time_stop"
            else:
                continue  # hold

            exit_idx = min(i + 1, n - 1)
            exit_raw = close_arr[exit_idx]
            # Long: sell at lower price; short: buy back at higher price
            exit_price = exit_raw * (1 - slippage * direction)

            shares = pos_value / abs(entry_fill)
            sig = float(sigma_by_date.get(entry_date, 0.015))
            adv = float(adv_by_date.get(entry_date, 1e7))
            liq_constrained = (shares / (adv + 1e-8)) > 0.01

            gross_pnl = (exit_price - entry_fill) * direction * shares
            cost_bps = round_trip_cost_bps(abs(entry_fill), shares, adv, sig)
            cost_dollars = cost_bps / 10_000 * pos_value
            net_pnl = gross_pnl - cost_dollars

            gross_bps = gross_pnl / pos_value * 10_000
            net_bps = net_pnl / pos_value * 10_000
            hold = exit_idx - entry_bar + 1

            if hold > 0 and entry_bar <= exit_idx < n:
                minute_net_pnl[entry_bar:exit_idx + 1] = net_pnl / hold

            trades.append({
                "gross_bps": round(gross_bps, 2),
                "net_bps": round(net_bps, 2),
                "cost_bps": round(cost_bps, 2),
                "hold_minutes": hold,
                "direction": "long" if direction > 0 else "short",
                "exit_reason": exit_reason,
                "session_forced_exit": exit_reason == "eod_flat",
                "liquidity_constrained": liq_constrained,
            })
            if liq_constrained:
                print(f"  [WARN] Liquidity-constrained trade: {ticker} "
                      f"{entry_date} {shares:.0f} shares, ADV {adv/1e6:.1f}M")
            in_trade = False
            direction = 0
            continue

        # ── Entry ─────────────────────────────────────────────────────────────
        if et_time < trade_start or et_time > trade_end:
            continue
        if is_eod or next_is_new_session or is_last_bar:
            continue
        # Mean-reversion zone: ENTRY_Z < |z| < STOP_Z
        if abs(z) <= entry_z or abs(z) >= stop_z:
            continue

        # z < 0 → price below VWAP → long (expect reversion up)
        # z > 0 → price above VWAP → short (expect reversion down)
        new_direction = +1 if z < 0 else -1

        entry_raw = close_arr[i + 1]
        # Long: pay more (adverse slippage); short: sell at less
        entry_fill = entry_raw * (1 + slippage * new_direction)
        entry_bar = i + 1
        entry_date = dates_arr[i + 1]
        direction = new_direction
        in_trade = True

    minute_returns = pd.Series(minute_net_pnl / pos_value, index=seg.index)
    return minute_returns, trades


# ── Per-window metrics ─────────────────────────────────────────────────────────

def compute_window_metrics(
    window_id: int,
    is_start: str, is_end: str,
    oos_start: str, oos_end: str,
    ticker_data: dict,
    params: dict = PARAMETERS,
) -> dict | None:
    is_trades, oos_trades = [], []
    is_ret_frames, oos_ret_frames = [], []

    for ticker, payload in ticker_data.items():
        ir, it = run_vwap_strategy_minute(
            payload["df"], is_start, is_end, ticker,
            payload["sigma"], payload["adv"], params,
        )
        or_, ot = run_vwap_strategy_minute(
            payload["df"], oos_start, oos_end, ticker,
            payload["sigma"], payload["adv"], params,
        )
        is_trades.extend(it)
        oos_trades.extend(ot)
        if len(ir) > 0:
            is_ret_frames.append(ir.rename(ticker))
        if len(or_) > 0:
            oos_ret_frames.append(or_.rename(ticker))

    if not oos_ret_frames:
        return None

    is_rets = pd.concat(is_ret_frames, axis=1).mean(axis=1).dropna() if is_ret_frames else pd.Series(dtype=float)
    oos_rets = pd.concat(oos_ret_frames, axis=1).mean(axis=1).dropna()

    # 1. Net OOS Sharpe (annualized from minute returns)
    oos_sharpe = (
        float(oos_rets.mean()) / (float(oos_rets.std()) + 1e-10)
    ) * ANNUALIZE_FACTOR

    # 2. Net profit per trade (bps) — OOS
    oos_net_bps = [t["net_bps"] for t in oos_trades]
    net_ppt_bps = float(np.mean(oos_net_bps)) if oos_net_bps else 0.0

    # 3. Max drawdown on OOS minute equity curve
    cum = (1 + oos_rets).cumprod()
    roll_max = cum.cummax()
    max_dd_pct = float(((cum - roll_max) / (roll_max + 1e-10)).min() * 100)

    # 4. IS trade count
    is_tc = len(is_trades)

    # 5. Cost-to-gross ratio (IS, profitable trades only)
    is_gross_sum = sum(t["gross_bps"] for t in is_trades if t["gross_bps"] > 0)
    is_cost_sum = sum(t["cost_bps"] for t in is_trades)
    cost_ratio = min(is_cost_sum / (is_gross_sum + 1e-10), 5.0) if is_gross_sum > 0 else 1.0

    # 6. Session-forced-exit rate and median hold
    all_trades = is_trades + oos_trades
    forced_rate = sum(1 for t in all_trades if t.get("session_forced_exit")) / max(len(all_trades), 1)
    hold_minutes = [t["hold_minutes"] for t in all_trades]
    median_hold = float(np.median(hold_minutes)) if hold_minutes else 0.0

    # 7. Direction breakdown
    long_t = sum(1 for t in all_trades if t.get("direction") == "long")
    short_t = sum(1 for t in all_trades if t.get("direction") == "short")
    exit_reasons = {}
    for t in all_trades:
        exit_reasons[t.get("exit_reason", "unknown")] = (
            exit_reasons.get(t.get("exit_reason", "unknown"), 0) + 1
        )

    return {
        "window_id": window_id,
        "is_period": f"{is_start} to {is_end}",
        "oos_period": f"{oos_start} to {oos_end}",
        "net_oos_sharpe": round(oos_sharpe, 4),
        "net_profit_per_trade_bps": round(net_ppt_bps, 2),
        "max_drawdown_pct": round(max_dd_pct, 3),
        "is_trade_count": is_tc,
        "oos_trade_count": len(oos_trades),
        "cost_to_gross_ratio": round(float(cost_ratio), 4),
        "session_forced_exit_rate": round(forced_rate, 3),
        "median_hold_minutes": round(median_hold, 1),
        "long_trades": long_t,
        "short_trades": short_t,
        "exit_reasons": exit_reasons,
    }


def compute_distributions(results: list[dict]) -> dict:
    df = pd.DataFrame(results)
    metric_cols = [
        "net_oos_sharpe",
        "net_profit_per_trade_bps",
        "max_drawdown_pct",
        "is_trade_count",
        "cost_to_gross_ratio",
    ]
    distros = {}
    for col in metric_cols:
        vals = df[col].values.astype(float)
        distros[col] = {
            "values": [round(float(v), 4) for v in vals],
            "mean": round(float(vals.mean()), 4),
            "std": round(float(vals.std(ddof=1) if len(vals) > 1 else 0.0), 4),
            "p10": round(float(np.percentile(vals, 10)), 4),
            "p25": round(float(np.percentile(vals, 25)), 4),
            "p50": round(float(np.percentile(vals, 50)), 4),
            "p75": round(float(np.percentile(vals, 75)), 4),
            "p90": round(float(np.percentile(vals, 90)), 4),
            "min": round(float(vals.min()), 4),
            "max": round(float(vals.max()), 4),
        }
    return distros


def assess_threshold_shift(rsi2_distros: dict, vwap_distros: dict) -> dict:
    """
    Compare VWAP baseline vs prior RSI(2) distributions (QUA-164).
    Flags metrics where the new P50 differs by >20% — threshold revision candidates.
    """
    assessments = {}
    for metric in ["net_oos_sharpe", "net_profit_per_trade_bps", "cost_to_gross_ratio"]:
        if metric not in rsi2_distros or metric not in vwap_distros:
            continue
        rsi2_p50 = rsi2_distros[metric]["p50"]
        vwap_p50 = vwap_distros[metric]["p50"]
        pct_shift = (
            (vwap_p50 - rsi2_p50) / abs(rsi2_p50) * 100 if abs(rsi2_p50) > 1e-6 else 0.0
        )
        flagged = abs(pct_shift) > 20.0
        assessments[metric] = {
            "rsi2_p50": rsi2_p50,
            "vwap_p50": vwap_p50,
            "pct_shift": round(pct_shift, 1),
            "flagged_gt20pct": flagged,
            "note": "THRESHOLD REVISION CANDIDATE" if flagged else "within tolerance",
        }
    return assessments


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> dict:
    store = MinuteBarStore()

    print("=" * 70)
    print("Gate 1 Calibration — Intraday Baseline (VWAP Deviation Mean Reversion)")
    print("QUA-244: RSI(2) baseline → VWAP mean reversion (15–120 min hold target)")
    print("=" * 70)
    print(f"Universe:  {UNIVERSE}")
    print(f"Annualize: sqrt({TRADING_MINUTES_PER_YEAR}) = {ANNUALIZE_FACTOR:.1f}")
    print(f"Entry |z| > {PARAMETERS['ENTRY_Z']}  |  Exit |z| < {PARAMETERS['EXIT_Z']}  "
          f"|  Stop |z| > {PARAMETERS['STOP_Z']}")
    print(f"Trade window: {PARAMETERS['TRADE_START_ET']}–{PARAMETERS['TRADE_END_ET']} ET  "
          f"|  EOD flat: {PARAMETERS['EOD_EXIT_ET']}  |  Time stop: {PARAMETERS['TIME_STOP_BARS']} bars")
    print("Loading minute bars...")

    YF_ADV_START = "2021-12-01"
    YF_ADV_END = "2024-10-31"
    ticker_data = {}
    for ticker in UNIVERSE:
        df_et = load_ticker_data(store, ticker, "2022-01-01", "2024-10-31")
        if df_et.empty:
            print(f"  {ticker}: NO DATA — skipping")
            continue
        sigma_by_date, adv_by_date = build_daily_stats(
            df_et, ticker=ticker, yf_start=YF_ADV_START, yf_end=YF_ADV_END,
        )
        ticker_data[ticker] = {"df": df_et, "sigma": sigma_by_date, "adv": adv_by_date}
        print(f"  {ticker}: {len(df_et):,} bars  "
              f"sigma {sigma_by_date.min():.4f}–{sigma_by_date.max():.4f}  "
              f"ADV median {adv_by_date.median()/1e6:.1f}M [yfinance total-market]")

    if not ticker_data:
        print("ERROR: No minute data loaded — check minute_bars.db.")
        return {}

    print(f"\nRunning {len(WINDOWS)} walk-forward windows (3m IS / 1m OOS)...")
    results = []

    for wid, is0, is1, oos0, oos1 in WINDOWS:
        print(f"\nWindow {wid}: IS={is0}→{is1} | OOS={oos0}→{oos1}")
        metrics = compute_window_metrics(wid, is0, is1, oos0, oos1, ticker_data)
        if metrics is None:
            print("  [skip] insufficient minute data for this window")
            continue
        results.append(metrics)
        print(f"  Net OOS Sharpe:     {metrics['net_oos_sharpe']:.3f}")
        print(f"  Net PPT (bps):      {metrics['net_profit_per_trade_bps']:.2f}")
        print(f"  Max Drawdown:       {metrics['max_drawdown_pct']:.3f}%")
        print(f"  IS Trades:          {metrics['is_trade_count']}")
        print(f"  OOS Trades:         {metrics['oos_trade_count']}")
        print(f"  Cost/Gross (IS):    {metrics['cost_to_gross_ratio']:.2%}")
        print(f"  Forced-exit rate:   {metrics['session_forced_exit_rate']:.1%}")
        print(f"  Median hold (min):  {metrics['median_hold_minutes']:.0f}")
        print(f"  Long / Short:       {metrics.get('long_trades', '?')} / "
              f"{metrics.get('short_trades', '?')}")
        print(f"  Exit reasons:       {metrics.get('exit_reasons', {})}")

    if not results:
        print("\nERROR: No window results — check minute_bars.db data coverage.")
        return {}

    print(f"\n{'='*70}")
    print("VWAP BASELINE DISTRIBUTION SUMMARY (6-window aggregate)")
    print(f"{'='*70}")

    vwap_distros = compute_distributions(results)
    for metric, d in vwap_distros.items():
        print(f"\n{metric}:")
        print(f"  Values: {d['values']}")
        print(f"  Mean={d['mean']:.4f}  Std={d['std']:.4f}")
        print(f"  P10={d['p10']:.4f}  P25={d['p25']:.4f}  P50={d['p50']:.4f}  "
              f"P75={d['p75']:.4f}  P90={d['p90']:.4f}")

    # Compare vs RSI(2) minute baseline from QUA-164
    rsi2_path = Path(__file__).parent / "gate1_v2_calibration_minutebar_2026-06-13.json"
    rsi2_distros = {}
    assessments = {}
    if rsi2_path.exists():
        with open(rsi2_path) as f:
            rsi2_baseline = json.load(f)
        rsi2_distros = rsi2_baseline.get("distributions", {})
        print(f"\n{'='*70}")
        print("THRESHOLD SHIFT ASSESSMENT (VWAP baseline vs RSI(2) baseline, QUA-164)")
        print(f"{'='*70}")
        assessments = assess_threshold_shift(rsi2_distros, vwap_distros)
        for metric, a in assessments.items():
            flag = "*** FLAG ***" if a["flagged_gt20pct"] else "OK"
            print(f"\n{metric}:")
            print(f"  RSI(2) P50={a['rsi2_p50']:.4f}  VWAP P50={a['vwap_p50']:.4f}  "
                  f"Shift={a['pct_shift']:+.1f}%  [{flag}]")
            print(f"  → {a['note']}")
    else:
        print(f"\n[INFO] RSI(2) baseline not found at {rsi2_path} — skipping shift assessment")

    # Gate 1 Track B (Intraday Equities) thresholds from criteria.md v2.7
    GATE1_THRESHOLDS = {
        "net_oos_sharpe": 0.7,
        "net_profit_per_trade_bps": 5.0,
        "max_drawdown_pct": -1.5,   # stored negative; pass if P50 > -1.5%
        "is_trade_count": 300,
        "cost_to_gross_ratio": 0.40,
    }

    print(f"\n{'='*70}")
    print("GATE 1 THRESHOLD COMPLIANCE (Track B — Equities Intraday, criteria.md v2.7)")
    print(f"{'='*70}")
    threshold_compliance = {}
    for metric, threshold in GATE1_THRESHOLDS.items():
        if metric not in vwap_distros:
            continue
        p50 = vwap_distros[metric]["p50"]
        if metric == "max_drawdown_pct":
            passes = p50 > threshold
        elif metric in ("net_oos_sharpe", "net_profit_per_trade_bps", "is_trade_count"):
            passes = p50 >= threshold
        else:  # cost_to_gross_ratio: lower is better
            passes = p50 <= threshold
        status = "PASS" if passes else "FAIL"
        print(f"  {metric:35s}  P50={p50:.4f}  threshold={threshold}  [{status}]")
        threshold_compliance[metric] = {"p50": p50, "threshold": threshold, "passes": passes}

    # Hold period sanity check — must be 15–120 min per issue spec
    all_holds = [r["median_hold_minutes"] for r in results]
    overall_median_hold = float(np.median(all_holds)) if all_holds else 0.0
    hold_pass = 15.0 <= overall_median_hold <= 120.0
    print(f"  {'median_hold_minutes (overall)':35s}  "
          f"median={overall_median_hold:.0f}  target=15–120 min  "
          f"[{'PASS' if hold_pass else 'FAIL'}]")

    output = {
        "calibration_date": "2026-06-15",
        "ticket": "QUA-244",
        "replaces": "QUA-164 RSI(2) minute-bar baseline",
        "data_source": "Alpaca/IEX 1-minute bars (minute_bars.db)",
        "data_coverage": {
            "SPY": "2022-01-03 to 2024-12-31",
            "QQQ": "2022-01-03 to 2024-12-31",
        },
        "universe": UNIVERSE,
        "n_windows": len(results),
        "strategy": "VWAP deviation mean reversion (long+short, intraday-flat)",
        "strategy_rationale": (
            "RSI(2) at 1-min resolution has ~3-min median hold — captures microstructure "
            "noise rather than signal. VWAP deviation mean reversion (Avellaneda-Lee 2010, "
            "adapted for session VWAP) targets 15–120 min holds and is representative of "
            "the live H60 intraday strategy family. Long + short legs reduce directional bias."
        ),
        "parameters": PARAMETERS,
        "annualization": {
            "method": "sqrt(TRADING_MINUTES_PER_YEAR)",
            "trading_minutes_per_year": TRADING_MINUTES_PER_YEAR,
            "factor": round(ANNUALIZE_FACTOR, 2),
        },
        "cost_model": {
            "fixed_per_share": FIXED_COST_PER_SHARE,
            "market_impact_k": MI_K,
            "slippage_overrides": SLIPPAGE_OVERRIDES,
            "formula": "fixed_bps = 2*0.005/price*10000; mi_bps = 0.1*sigma*sqrt(Q/ADV)*10000",
            "adv_source": "yfinance total-market (consolidated tape) — QUA-243 fix applied",
        },
        "window_results": results,
        "distributions": vwap_distros,
        "threshold_shift_assessment_vs_rsi2": assessments,
        "gate1_threshold_compliance": threshold_compliance,
        "gate1_thresholds_current": GATE1_THRESHOLDS,
        "hold_period_check": {
            "overall_median_hold_minutes": overall_median_hold,
            "passes_15_120_range": hold_pass,
            "target": "15–120 min (criteria: hold period representative of live strategies)",
        },
        "rsi2_baseline_path": str(rsi2_path) if rsi2_path.exists() else None,
    }

    out_path = Path(__file__).parent / "gate1_v2_calibration_intraday_baseline_2026-06-15.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved: {out_path}")

    return output


if __name__ == "__main__":
    main()
