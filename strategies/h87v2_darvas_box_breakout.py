"""
Strategy: H87v2 Darvas Box Breakout — Regime-Adjusted Gate 1 Window
Author: Strategy Coder Agent / Engineering Director
Date: 2026-06-25
Version: 2.0
Hypothesis: Stocks near 52-week highs that form a tight Darvas Box (price consolidation
            between a ceiling and floor, lasting 20–30 trading days) and break above the
            ceiling on above-average volume deliver positive returns over 10–25 day holds.
Asset class: US large-cap and mid-cap equities (S&P 500 + S&P 400)
Universe: data/h82v2_universe_2018_jan.csv (~1,047 PIT tickers, S&P 1500 proxy circa 2018)
Track: A (Daily signals, swing hold ~10-25 trading days)
Issue: QUA-423
Parent: QUA-422

H87v2 changes from H87 (QUA-418):
  IS period: 2022-01-01–2024-12-31 → 2023-01-01–2025-12-31 (remove 2022 bear contamination)
  Walk-forward: 6 × (3mo IS / 1mo OOS) → 4 × (6mo IS / 3mo OOS)
  box_n sweep: [15, 20, 25] → [20, 25, 30] (box_n=15 produced negative IS Sharpe in H87)
  Signal logic: UNCHANGED

Data quality checklist:
  [x] Survivorship bias: Universe is h82v2_universe_2018_jan.csv (PIT proxy circa 2018).
      Stocks delisted after 2018 absent from yfinance — bias directionally inflates Sharpe.
      Same treatment as H82v2 / H87 (Hard Gate 9 option b: documented survivorship bias direction).
  [x] Price adjustments: yfinance auto_adjust=True (splits + dividends corrected).
  [x] Data gaps: Tickers with >5 missing business days in backtest window flagged in output JSON.
  [x] Earnings exclusion: Implemented via earnings blackout (earnings_exit rule). If yfinance
      earnings data unavailable for a ticker, position held through earnings with 8% hard stop
      protection. Count of earnings-exited trades reported in output.
  [x] Delisted tickers: yfinance returns data through delisting date (correct treatment).
      Tickers with <252 total days of data excluded pre-backtest.

Transaction cost model (Engineering Director AGENTS.md — equities standard tier):
  Fixed: $0.005/share
  Slippage: 0.05% (0.0005) one-way
  Market impact: k=0.1 × sigma_20d × sqrt(Q / dollar_ADV_20d), Almgren-Chriss square-root
  Total fill cost per share = price × slippage_pct + fixed_cost + price × impact
  Liquidity flag: (shares × price) / dollar_ADV_20d > 0.01 → liquidity_constrained
"""

import math
import os
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Constants ────────────────────────────────────────────────────────────────────

IS_START = "2023-01-01"
IS_END   = "2025-12-31"
TRADING_DAYS_PER_YEAR = 252
_K_IMPACT = 0.1  # Almgren-Chriss square-root market impact coefficient

# ── Parameters ───────────────────────────────────────────────────────────────────

PARAMETERS = {
    # Swept parameters — 27 combos in Gate 1 sweep (box_n × box_width_max × vol_ratio_min)
    # H87v2 change: box_n sweep [20, 25, 30] (was [15, 20, 25] in H87)
    "box_n": 25,               # box lookback in trading days [20, 25, 30]
    "box_width_max": 0.10,     # max (ceiling-floor)/ceiling ratio [0.08, 0.10, 0.12]
    "vol_ratio_min": 1.30,     # min volume / 20d avg for confirmation [1.20, 1.30, 1.40]

    # Fixed parameters (identical to H87)
    "spy_sma_days": 150,           # regime filter SMA
    "hard_stop_pct": 0.08,         # 8% hard stop below entry
    "max_hold_days": 25,           # time stop in trading days
    "partial_profit_pct": 0.20,    # take 50% off at +20%
    "trail_stop_pct": 0.08,        # trailing 8% on remainder after partial
    "high_proximity_pct": 0.25,    # must be within 25% of 52-week high
    "min_price": 10.0,             # no penny stocks
    "min_adv_dollars": 2_000_000,  # $2M daily dollar volume minimum
    "max_positions": 10,
    "risk_per_trade_pct": 0.02,    # Elder 2% rule
    "max_position_pct": 0.10,      # 10% concentration cap
    "init_cash": 25_000,

    # Data settings
    "universe_file": "data/h82v2_universe_2018_jan.csv",
}


# ── Earnings cache (module-level, lazy-loaded per ticker) ────────────────────────

_earnings_cache: dict = {}


def _get_earnings_dates(ticker: str) -> list:
    """
    Lazy-load historical earnings dates for a ticker from yfinance.
    Returns sorted list of pd.Timestamp. Empty list on failure (fallback: hard stop only).
    """
    if ticker in _earnings_cache:
        return _earnings_cache[ticker]
    try:
        raw = yf.Ticker(ticker).get_earnings_dates(limit=50)
        if raw is not None and not raw.empty:
            dates = sorted(raw.index.normalize().unique().tolist())
            _earnings_cache[ticker] = dates
        else:
            _earnings_cache[ticker] = []
    except Exception:
        _earnings_cache[ticker] = []
    return _earnings_cache[ticker]


def _has_earnings_within_n_bdays(ticker: str, current_date: pd.Timestamp, n: int = 3) -> bool:
    """Return True if ticker has an earnings date within n trading days after current_date."""
    dates = _get_earnings_dates(ticker)
    if not dates:
        return False
    try:
        future = pd.bdate_range(current_date + pd.Timedelta(days=1), periods=n)
        lo, hi = future[0], future[-1]
        return any(lo <= d <= hi for d in dates)
    except Exception:
        return False


# ── Universe Loading ─────────────────────────────────────────────────────────────

_STRATEGY_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_STRATEGY_DIR)


def _load_tickers(params: dict) -> list:
    raw_path = params.get("universe_file", "data/h82v2_universe_2018_jan.csv")
    # Resolve relative paths against repo root so the file is found regardless of CWD.
    if not os.path.isabs(raw_path):
        fpath = os.path.join(_REPO_ROOT, raw_path)
    else:
        fpath = raw_path
    if os.path.exists(fpath):
        df = pd.read_csv(fpath)
        col = next(
            (c for c in df.columns if c.lower() in ("ticker", "symbol")),
            df.columns[0],
        )
        tickers = df[col].dropna().str.strip().str.upper().tolist()
        tickers = [t for t in tickers if t and "/" not in t and len(t) <= 5]
        print(f"Loaded {len(tickers)} tickers from {fpath}")
        return list(dict.fromkeys(tickers))
    warnings.warn(
        f"Universe file not found: {fpath}. Using compact fallback (survivorship-biased)."
    )
    return [
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "JPM",
        "JNJ", "XOM", "BAC", "UNH", "V", "HD", "PG", "MA", "DIS",
        "ADBE", "NFLX", "CRM", "PYPL", "TMO", "ABT", "COST", "NKE",
    ]


def load_universe_data(params: dict) -> tuple:
    """
    Download OHLCV for universe + SPY in batches of 50.
    Buffer extends to 2022-01-01 (>252 trading days before IS_START=2023-01-01) to ensure
    52-week high and 150-day SPY SMA are fully populated at backtest start.
    H87v2: data end extended to 2026-01-15 to cover WF4 OOS 2025-10-01–2025-12-31.
    Returns: (close, open_px, high, low, volume, spy_close, spy_volume)
    All DataFrames share the same date index; SPY removed from universe frames.
    """
    tickers = _load_tickers(params)
    buf_start = "2022-01-01"   # 1 full year before IS_START for 52wk high + SPY SMA
    end = "2026-01-15"         # covers WF4 OOS 2025-10-01–2025-12-31 + buffer

    all_tickers = list(dict.fromkeys(["SPY"] + tickers))
    c_frames, o_frames, h_frames, l_frames, v_frames = [], [], [], [], []

    batch_size = 50
    for i in range(0, len(all_tickers), batch_size):
        batch = all_tickers[i: i + batch_size]
        try:
            raw = yf.download(
                batch, start=buf_start, end=end, auto_adjust=True, progress=False
            )
        except Exception as exc:
            warnings.warn(f"Batch {i // batch_size} download failed: {exc}")
            continue
        if raw.empty:
            continue

        if isinstance(raw.columns, pd.MultiIndex):
            top = raw.columns.get_level_values(0).unique()
            def _g(field, fallback=pd.DataFrame()):
                return raw[field] if field in top else fallback
            c, o, h, l, v = _g("Close"), _g("Open"), _g("High"), _g("Low"), _g("Volume")
        else:
            t0 = batch[0]
            c = raw[["Close"]].rename(columns={"Close": t0})
            o = raw[["Open"]].rename(columns={"Open": t0})
            h = raw[["High"]].rename(columns={"High": t0})
            l = raw[["Low"]].rename(columns={"Low": t0})
            v = raw[["Volume"]].rename(columns={"Volume": t0})

        for frame_list, frame in [(c_frames, c), (o_frames, o), (h_frames, h),
                                   (l_frames, l), (v_frames, v)]:
            if not frame.empty:
                frame_list.append(frame)

    if not c_frames:
        raise ValueError("No data downloaded for any ticker.")

    def _merge(frames):
        df = pd.concat(frames, axis=1).sort_index()
        return df.loc[:, ~df.columns.duplicated()]

    close = _merge(c_frames)
    open_px = _merge(o_frames)
    high = _merge(h_frames)
    low = _merge(l_frames)
    volume = _merge(v_frames)

    spy_close = close["SPY"].copy() if "SPY" in close.columns else pd.Series(dtype=float)
    spy_volume = volume["SPY"].copy() if "SPY" in volume.columns else pd.Series(dtype=float)
    for df in (close, open_px, high, low, volume):
        if "SPY" in df.columns:
            df.drop(columns=["SPY"], inplace=True)

    available_raw = [t for t in tickers if t in close.columns]
    available = _filter_min_days(close, available_raw)
    close = close.reindex(columns=available)
    open_px = open_px.reindex(columns=available)
    high = high.reindex(columns=available)
    low = low.reindex(columns=available)
    volume = volume.reindex(columns=available)

    print(f"Universe after delisted filter: {len(available)} tickers")
    return close, open_px, high, low, volume, spy_close, spy_volume


def _filter_min_days(close: pd.DataFrame, tickers: list, min_days: int = 252) -> list:
    kept = [t for t in tickers if t in close.columns and close[t].dropna().shape[0] >= min_days]
    print(f"Delisted filter: {len(tickers)} -> {len(kept)} with >=252 days data")
    return kept


def _check_data_quality(
    close: pd.DataFrame, tickers: list, start: str, end: str
) -> dict:
    """Flag tickers with >5 missing business days in the specified window."""
    window = close.loc[start:end]
    expected = pd.bdate_range(start=start, end=end)
    flagged = []
    summary = {}
    for t in tickers:
        if t not in window.columns:
            flagged.append(t)
            summary[t] = {"error": "not_in_download"}
            continue
        s = window[t].dropna()
        missing = len(expected.difference(s.index))
        summary[t] = {"days": len(s), "missing": missing, "flagged": missing > 5}
        if missing > 5:
            flagged.append(t)
    return {
        "flagged_count": len(flagged),
        "flagged_sample": flagged[:20],
        "total_tickers": len(tickers),
    }


# ── Core Simulation ──────────────────────────────────────────────────────────────

def simulate_strategy(
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
    spy_close: pd.Series,
    spy_volume: pd.Series,
    params: dict,
    start: str = IS_START,
    end: str = IS_END,
) -> dict:
    """
    Simulate H87v2 Darvas Box Breakout on preloaded OHLCV data.

    Execution model (Hard Gate 3 compliant):
      Signal at close T -> fill at open T+1. No same-bar fills.

    Exit priority order:
      1. Hard stop: close < stop_price -> SELL ALL "hard_stop"
      2. Time stop: days_held >= max_hold_days AND not yet +20% -> SELL ALL "time_stop"
      3. Earnings blackout: earnings within 3 trading days -> SELL ALL "earnings_exit"
      4. Partial profit: close >= entry*1.20 and not partial_taken -> SELL HALF "partial_profit"
         (raises stop to entry; trailing starts)
      5. Trailing stop (after partial): peak_close * (1-trail_pct) -> SELL ALL "trail_stop"

    H87v2 parameter sweep ranges:
      box_n:          [20, 25, 30]  (H87: [15, 20, 25])
      box_width_max:  [0.08, 0.10, 0.12]
      vol_ratio_min:  [1.20, 1.30, 1.40]

    Returns dict with: sharpe, mdd, trades, win_rate, profit_factor, ppt_bps,
    trade_log (DataFrame), equity_curve (Series), earnings_exits, liquidity_constrained_pct.
    """
    box_n = params["box_n"]
    box_width_max = params["box_width_max"]
    vol_ratio_min = params["vol_ratio_min"]
    spy_sma_days = params["spy_sma_days"]
    hard_stop_pct = params["hard_stop_pct"]
    max_hold_days = params["max_hold_days"]
    partial_pct = params["partial_profit_pct"]
    trail_pct = params["trail_stop_pct"]
    high_prox = params["high_proximity_pct"]
    min_price = params["min_price"]
    min_adv = params["min_adv_dollars"]
    max_pos = params["max_positions"]
    risk_pct = params["risk_per_trade_pct"]
    max_pos_pct = params["max_position_pct"]
    init_cash = params["init_cash"]

    # ── Precompute vectorized indicators ─────────────────────────────────────

    # Shift box construction and vol avg by 1 so today's close can exceed yesterday's ceiling.
    avg_vol_20d = volume.rolling(20).mean().shift(1)  # prior 20-day avg (no look-ahead)
    dollar_adv_20d = (volume * close).rolling(20).mean()
    sigma_20d = close.pct_change().rolling(20).std()
    high_52w = close.rolling(252).max()
    spy_sma = spy_close.rolling(spy_sma_days).mean()

    box_ceiling = high.rolling(box_n).max().shift(1)  # max high over [T-N, T-1]
    box_floor = low.rolling(box_n).min().shift(1)     # min low over [T-N, T-1]
    box_width = (box_ceiling - box_floor) / (box_ceiling + 1e-8)
    box_midpoint = box_floor + 0.5 * (box_ceiling - box_floor)

    n_tickers = len(close.columns)
    regime_arr = np.tile(
        (spy_close > spy_sma).reindex(close.index, fill_value=False).values.reshape(-1, 1),
        (1, n_tickers),
    )
    regime_df = pd.DataFrame(regime_arr, index=close.index, columns=close.columns)

    price_ok = close >= min_price
    liq_ok = dollar_adv_20d >= min_adv
    high_prox_ok = close >= high_52w * (1.0 - high_prox)
    in_universe = price_ok & liq_ok & high_prox_ok & regime_df

    tight_box = box_width <= box_width_max
    in_upper_half = close >= box_midpoint
    valid_box = tight_box & in_upper_half

    price_breakout = close > box_ceiling * 1.001
    vol_confirm = volume > avg_vol_20d * vol_ratio_min
    not_extended = close <= box_ceiling * 1.05

    entry_signal = (
        price_breakout & vol_confirm & not_extended & valid_box & in_universe
    ).fillna(False)

    vol_ratio_df = volume / (avg_vol_20d + 1e-8)

    # ── Simulation loop ───────────────────────────────────────────────────────

    sim_dates = close.loc[start:end].index
    cash = float(init_cash)
    positions: dict = {}
    trade_log: list = []
    equity_curve = pd.Series(0.0, index=sim_dates)

    pending_entries: dict = {}
    pending_exits: dict = {}

    earnings_exit_count = 0
    liq_constrained_entries = 0

    def _get_open(ticker: str, date: pd.Timestamp) -> float:
        if date in open_px.index and ticker in open_px.columns:
            v = open_px.at[date, ticker]
            if not (np.isnan(v) or v <= 0):
                return float(v)
        if date in close.index and ticker in close.columns:
            v = close.at[date, ticker]
            if not (np.isnan(v) or v <= 0):
                return float(v)
        return np.nan

    def _cost_per_share(ticker: str, date: pd.Timestamp, shares: int, price: float):
        """Returns (cost_per_share_one_way, liquidity_constrained_flag)."""
        sig = 0.01
        adv = float(min_adv)
        if date in sigma_20d.index and ticker in sigma_20d.columns:
            v = sigma_20d.at[date, ticker]
            if not np.isnan(v) and v > 0:
                sig = float(v)
        if date in dollar_adv_20d.index and ticker in dollar_adv_20d.columns:
            v = dollar_adv_20d.at[date, ticker]
            if not np.isnan(v) and v > 0:
                adv = float(v)
        dollar_qty = shares * price
        q_over_adv = dollar_qty / adv
        impact = _K_IMPACT * sig * math.sqrt(max(q_over_adv, 0.0))
        liq_flag = q_over_adv > 0.01
        cost_ps = price * (0.0005 + impact) + 0.005
        return cost_ps, liq_flag

    def _execute_buy(
        ticker: str, date: pd.Timestamp, fill_price: float,
        box_ceil: float, box_floor_val: float
    ) -> None:
        nonlocal cash, liq_constrained_entries
        if ticker in positions or len(positions) >= max_pos:
            return
        nav = cash + sum(
            pos["shares"] * float(
                close.at[date, t]
                if date in close.index and t in close.columns
                else pos["entry_price"]
            )
            for t, pos in positions.items()
            if not np.isnan(
                close.at[date, t]
                if date in close.index and t in close.columns
                else np.nan
            )
        )
        stop_price = max(box_floor_val, fill_price * (1.0 - hard_stop_pct))
        risk_per_share = max(fill_price - stop_price, 0.01)
        shares = int(nav * risk_pct / risk_per_share)
        shares = min(shares, int(nav * max_pos_pct / max(fill_price, 1e-8)))
        if shares < 1:
            return
        cost_ps, liq = _cost_per_share(ticker, date, shares, fill_price)
        total_outlay = shares * (fill_price + cost_ps)
        if total_outlay > cash * 0.995:
            shares = max(int(cash * 0.995 / (fill_price + cost_ps)), 0)
            if shares < 1:
                return
            total_outlay = shares * (fill_price + cost_ps)
        cash -= total_outlay
        if liq:
            liq_constrained_entries += 1
        positions[ticker] = {
            "entry_price": fill_price,
            "entry_date": date,
            "shares": shares,
            "stop_price": stop_price,
            "partial_taken": False,
            "td_count": 0,
            "box_ceiling_val": box_ceil,
            "box_floor_val": box_floor_val,
            "peak_close": fill_price,
            "liquidity_constrained": liq,
        }

    def _execute_sell(
        ticker: str, date: pd.Timestamp, fill_price: float,
        reason: str, half_only: bool
    ) -> None:
        nonlocal cash, earnings_exit_count
        if ticker not in positions:
            return
        pos = positions[ticker]
        if half_only:
            shares = max(pos["shares"] // 2, 1)
            shares = min(shares, pos["shares"])
        else:
            shares = pos["shares"]
        if shares < 1:
            return
        cost_ps, _ = _cost_per_share(ticker, date, shares, fill_price)
        proceeds = shares * (fill_price - cost_ps)
        cost_basis = shares * pos["entry_price"]
        pnl = proceeds - cost_basis
        cash += proceeds

        if "earnings" in reason:
            earnings_exit_count += 1

        trade_log.append({
            "ticker": ticker,
            "entry_date": str(pos["entry_date"].date()),
            "exit_date": str(date.date() if hasattr(date, "date") else date),
            "entry_price": round(pos["entry_price"], 4),
            "exit_price": round(fill_price, 4),
            "shares": shares,
            "pnl": round(pnl, 4),
            "return_pct": round(pnl / max(abs(cost_basis), 1e-8), 6),
            "reason": reason,
            "days_held": pos["td_count"],
            "liquidity_constrained": pos.get("liquidity_constrained", False),
        })

        if half_only:
            pos["shares"] -= shares
            pos["partial_taken"] = True
            pos["stop_price"] = max(pos["stop_price"], pos["entry_price"])
            if pos["shares"] < 1:
                del positions[ticker]
        else:
            del positions[ticker]

    for i, date in enumerate(sim_dates):

        # Step 1: Execute pending exits at today's open (from yesterday's close signals)
        for ticker, (exit_type, reason) in list(pending_exits.items()):
            fp = _get_open(ticker, date)
            if (np.isnan(fp) or fp <= 0) and ticker in close.columns and date in close.index:
                fp = float(close.at[date, ticker])
            if not (np.isnan(fp) or fp <= 0) and ticker in positions:
                _execute_sell(ticker, date, fp, reason, half_only=(exit_type == "half"))
        pending_exits.clear()

        # Step 2: Execute pending entries at today's open (from yesterday's close signals)
        for ticker, (box_ceil, box_fl) in list(pending_entries.items()):
            if ticker in positions or len(positions) >= max_pos:
                continue
            fp = _get_open(ticker, date)
            if np.isnan(fp) or fp <= 0:
                continue
            _execute_buy(ticker, date, fp, box_ceil, box_fl)
        pending_entries.clear()

        # Step 3: Check exit conditions at today's CLOSE
        if date in close.index:
            for ticker in list(positions.keys()):
                if ticker in pending_exits:
                    continue
                if ticker not in close.columns:
                    continue
                pos = positions[ticker]
                c_today = close.at[date, ticker]
                if np.isnan(c_today):
                    continue

                pos["td_count"] += 1
                if c_today > pos["peak_close"]:
                    pos["peak_close"] = float(c_today)

                if c_today < pos["stop_price"]:
                    if pos["partial_taken"] and pos["stop_price"] > pos["entry_price"] * (1.0 - hard_stop_pct):
                        reason = "trail_stop"
                    else:
                        reason = "hard_stop"
                    pending_exits[ticker] = ("full", reason)
                    continue

                if (pos["td_count"] >= max_hold_days
                        and not pos["partial_taken"]
                        and c_today < pos["entry_price"] * (1.0 + partial_pct)):
                    pending_exits[ticker] = ("full", "time_stop")
                    continue

                if _has_earnings_within_n_bdays(ticker, date, n=3):
                    pending_exits[ticker] = ("full", "earnings_exit")
                    continue

                if (not pos["partial_taken"]
                        and c_today >= pos["entry_price"] * (1.0 + partial_pct)):
                    pending_exits[ticker] = ("half", "partial_profit")
                    continue

                if pos["partial_taken"]:
                    new_trail = pos["peak_close"] * (1.0 - trail_pct)
                    pos["stop_price"] = max(pos["stop_price"], new_trail)
                    if c_today < pos["stop_price"]:
                        pending_exits[ticker] = ("full", "trail_stop")
                        continue

        # Step 4: Generate new entry signals from today's CLOSE
        if date in entry_signal.index:
            sig_row = entry_signal.loc[date]
            signal_tickers = [t for t in sig_row.index if bool(sig_row.get(t, False))]

            if signal_tickers:
                vr_row = vol_ratio_df.loc[date] if date in vol_ratio_df.index else pd.Series(dtype=float)
                signal_tickers.sort(
                    key=lambda t: (
                        float(vr_row.get(t, 0.0))
                        if not np.isnan(vr_row.get(t, 0.0))
                        else 0.0
                    ),
                    reverse=True,
                )
                slots = max_pos - len(positions)
                for ticker in signal_tickers:
                    if len(pending_entries) >= slots:
                        break
                    if ticker in positions or ticker in pending_entries:
                        continue
                    bc = (
                        float(box_ceiling.at[date, ticker])
                        if date in box_ceiling.index and ticker in box_ceiling.columns
                        else np.nan
                    )
                    bf = (
                        float(box_floor.at[date, ticker])
                        if date in box_floor.index and ticker in box_floor.columns
                        else np.nan
                    )
                    if np.isnan(bc) or np.isnan(bf):
                        continue
                    pending_entries[ticker] = (bc, bf)

        # Daily NAV (mark-to-market)
        nav = cash
        for t, pos in positions.items():
            if t in close.columns and date in close.index:
                p = close.at[date, t]
                if not np.isnan(p):
                    nav += pos["shares"] * float(p)
        equity_curve.iloc[i] = nav

    # Liquidate residual positions at period end (mark-to-close)
    if len(sim_dates) > 0:
        last_date = sim_dates[-1]
        for ticker in list(positions.keys()):
            if ticker in close.columns and last_date in close.index:
                p = close.at[last_date, ticker]
                if not np.isnan(p):
                    _execute_sell(ticker, last_date, float(p), "end_of_period", half_only=False)

    # ── Metrics ───────────────────────────────────────────────────────────────

    equity_curve = equity_curve.ffill().fillna(float(init_cash))
    daily_ret = equity_curve.pct_change().fillna(0.0).values
    std = daily_ret.std()
    sharpe = float(daily_ret.mean() / (std + 1e-8) * math.sqrt(TRADING_DAYS_PER_YEAR))

    cum = np.cumprod(1.0 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))

    trade_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
    n_trades = len(trade_df)

    if n_trades > 0:
        pnl_arr = trade_df["pnl"].values
        win_rate = float(np.mean(pnl_arr > 0))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses).mean()) if len(losses) > 0 else 1e-8
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 999.0
        avg_notional = float((trade_df["entry_price"] * trade_df["shares"]).mean())
        ppt_bps = (float(trade_df["pnl"].mean()) / avg_notional * 10000) if avg_notional > 0 else 0.0
        liq_pct = float(trade_df["liquidity_constrained"].sum()) / n_trades
    else:
        win_rate = 0.0
        profit_factor = 0.0
        ppt_bps = 0.0
        liq_pct = 0.0

    return {
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4),
        "trades": n_trades,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "ppt_bps": round(ppt_bps, 2),
        "trade_log": trade_df,
        "equity_curve": equity_curve,
        "earnings_exits": earnings_exit_count,
        "liquidity_constrained_pct": round(liq_pct, 4),
        "liq_constrained_entries": liq_constrained_entries,
    }


# ── Parameter Sweep ───────────────────────────────────────────────────────────────

def scan_parameters(
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
    spy_close: pd.Series,
    spy_volume: pd.Series,
    param_grid: list,
    start: str = IS_START,
    end: str = IS_END,
) -> pd.DataFrame:
    """
    Run simulate_strategy over all param combos in param_grid.
    H87v2 grid: box_n [20,25,30] × box_width_max [0.08,0.10,0.12] × vol_ratio_min [1.20,1.30,1.40]
    = 27 combos (identical grid size to H87; better parameter range).
    """
    rows = []
    for i, p in enumerate(param_grid):
        print(f"  Sweep [{i + 1}/{len(param_grid)}] "
              f"box_n={p['box_n']} width_max={p['box_width_max']} "
              f"vol_ratio={p['vol_ratio_min']} ...", end=" ", flush=True)
        try:
            res = simulate_strategy(
                close, open_px, high, low, volume, spy_close, spy_volume, p, start, end
            )
            row = {
                "box_n": p["box_n"],
                "box_width_max": p["box_width_max"],
                "vol_ratio_min": p["vol_ratio_min"],
                "sharpe": res["sharpe"],
                "mdd": res["mdd"],
                "trades": res["trades"],
                "win_rate": res["win_rate"],
                "profit_factor": res["profit_factor"],
                "ppt_bps": res["ppt_bps"],
                "error": "",
            }
            print(f"Sharpe={res['sharpe']:.3f} trades={res['trades']}")
        except Exception as exc:
            print(f"ERROR: {exc}")
            row = {
                "box_n": p["box_n"],
                "box_width_max": p["box_width_max"],
                "vol_ratio_min": p["vol_ratio_min"],
                "sharpe": 0.0,
                "mdd": 0.0,
                "trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "ppt_bps": 0.0,
                "error": str(exc),
            }
        rows.append(row)
    return pd.DataFrame(rows)
