"""
Strategy: H82v2 Minervini Trend Template + VCP Breakout — Point-in-Time Universe Fix
Author: Strategy Coder Agent / Engineering Director
Date: 2026-06-18
Hypothesis: H82v2 — same VCP-in-Stage-2 alpha as H82; universe corrected to ~1,047 PIT
            tickers via iShares Russell 1000+2000 proxy (S&P 1500 circa 2017-2018).
            Two new features: VIX-speed exit (>35 → halt buys immediately) and
            VIX persistence exit (>35 for ≥2 days → close all positions).
Parent task: QUA-341

Changes vs H82:
  1. Universe: data/h82v2_universe_2018_jan.csv (~1,047 PIT tickers) vs 144-name fallback.
  2. VIX exit: ^VIX > vix_halt_threshold (35) → halt new buys immediately.
     VIX > 35 for vix_exit_persistence_days (2) consecutive days → liquidate all positions.
  3. Delisted tickers: excluded by batch yfinance download (returns NaN rows or empty).
     Post-download filter removes tickers with <252 total days of data to ensure stability.
     VCP logic already skips NaN price windows — no additional per-ticker download loop needed.

Data quality:
  Universe: ~1,047 PIT members from iShares IWB+IWM proxy (S&P 1500 circa 2017-2018).
    Significant improvement vs H82 (144 survivorship-biased fallback).
    Still imperfect PIT — some 2018-era members since delisted will be absent from yfinance;
    some current members not in 2018 universe may appear if ticker existed. Bias materially
    reduced vs H82 fallback.
  Price adjustments: yfinance auto_adjust=True (splits + dividends adjusted).
  Data gaps: tickers with >5 missing business days flagged. <252 days → excluded pre-backtest.
  Earnings exclusion: NOT excluded. Hard stop (7.5%) provides gap-down protection.
  Delisted tickers: yfinance returns partial data (real returns through delisting date).
    Tickers with <252 total days of price data are excluded as unstable; those with partial
    data (e.g. delisted mid-backtest) contribute their actual returns — correct treatment.

Transaction cost model (per Engineering Director AGENTS.md spec):
  Fixed: $0.005/share
  Slippage: 0.05% (equities, standard tier — most universe members have ADV < 50M shares)
  Market impact: k=0.1 × σ × sqrt(Q / dollar_ADV), square-root model (Johnson 2010)
  Liquidity flag: (shares × price) / dollar_ADV > 0.01 → liquidity_constrained = True
"""

import math
import os
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    "universe_file": "data/h82v2_universe_2018_jan.csv",
    "min_price": 15.0,
    "min_adv_dollars": 5_000_000,
    "tt4_lookback": 30,
    "vcp_lookback": 60,
    "min_swing_pct": 0.03,
    "vcp_contraction_ratio": 0.99,
    "vcp_volume_dryup_ratio": 0.95,
    "breakout_volume_ratio": 1.05,
    "hard_stop_pct": 0.075,
    "partial_profit_pct": 0.20,
    "full_exit_pct": 0.25,
    "trail_stop_pct": 0.08,
    "pattern_failure_days": 3,
    "max_positions": 8,
    "risk_per_trade_pct": 0.02,
    "max_position_pct": 0.15,
    "elder_6pct_halt": 0.06,
    "m_filter_dist_days": 6,
    "m_filter_window": 25,
    "m_filter_down_threshold": 0.002,
    # H82v2 additions
    "vix_halt_threshold": 35.0,
    "vix_exit_persistence_days": 2,
    # Backtest periods
    "is_start": "2018-01-01",
    "is_end": "2023-12-31",
    "oos_start": "2024-01-01",
    "oos_end": "2025-12-31",
    "init_cash": 100_000,
}


# ── Universe Loading ────────────────────────────────────────────────────────────

def load_universe(params: dict) -> list:
    """Load ticker list from CSV or fall back to broad US equities list."""
    fpath = params.get("universe_file", "data/h82v2_universe_2018_jan.csv")
    if os.path.exists(fpath):
        df = pd.read_csv(fpath)
        col = next(
            (c for c in df.columns if c.lower() in ("ticker", "symbol")),
            df.columns[0],
        )
        tickers = df[col].dropna().str.strip().str.upper().tolist()
        # Remove obviously bad ticker formats (e.g. blank, slash-separated)
        tickers = [t for t in tickers if t and "/" not in t and len(t) <= 5]
        print(f"Loaded {len(tickers)} tickers from {fpath}")
        return list(dict.fromkeys(tickers))  # deduplicate, preserve order

    warnings.warn(
        f"Universe file not found: {fpath}. "
        "Using compact fallback (survivorship-biased). Check data/ directory."
    )
    # Compact fallback — 50 liquid names only; strategy should fail fast if file missing
    return [
        "AAPL", "MSFT", "AMZN", "GOOGL", "FB", "NVDA", "TSLA", "JPM", "JNJ", "XOM",
        "BAC", "UNH", "V", "HD", "PG", "MA", "DIS", "ADBE", "NFLX", "CRM",
        "PYPL", "TMO", "ABT", "COST", "NKE", "ABBV", "AVGO", "PEP", "MCD", "LLY",
        "MDT", "TXN", "HON", "UNP", "QCOM", "PM", "CVX", "BMY", "AMGN", "SBUX",
        "IBM", "INTU", "GS", "ISRG", "CAT", "GE", "DE", "MO", "GILD", "LMT",
    ]


# ── Data Download ───────────────────────────────────────────────────────────────

def download_data(tickers: list, buf_start: str, end: str) -> tuple:
    """
    Download OHLCV for universe + SPY + ^VIX in batches of 50.
    buf_start: pre-window buffer start (includes 260-day SMA warm-up).
    Returns: (close, open_px, volume, spy_close, spy_volume, vix_close).
    """
    all_tickers = list(dict.fromkeys(["SPY"] + tickers))
    close_list, open_list, vol_list = [], [], []

    batch_size = 50
    for i in range(0, len(all_tickers), batch_size):
        batch = all_tickers[i: i + batch_size]
        try:
            raw = yf.download(batch, start=buf_start, end=end, auto_adjust=True, progress=False)
        except Exception as exc:
            warnings.warn(f"Download batch {i // batch_size} failed: {exc}")
            continue
        if raw.empty:
            continue

        if isinstance(raw.columns, pd.MultiIndex):
            top = raw.columns.get_level_values(0).unique()
            c = raw["Close"] if "Close" in top else pd.DataFrame()
            o = raw["Open"] if "Open" in top else pd.DataFrame()
            v = raw["Volume"] if "Volume" in top else pd.DataFrame()
        else:
            t0 = batch[0]
            c = raw[["Close"]].rename(columns={"Close": t0})
            o = raw[["Open"]].rename(columns={"Open": t0})
            v = raw[["Volume"]].rename(columns={"Volume": t0})

        close_list.append(c)
        open_list.append(o)
        vol_list.append(v)

    if not close_list:
        raise ValueError("No data downloaded for any ticker.")

    def _merge(frames):
        df = pd.concat(frames, axis=1).sort_index()
        return df.loc[:, ~df.columns.duplicated()]

    close = _merge(close_list)
    open_px = _merge(open_list)
    volume = _merge(vol_list)

    spy_close = close["SPY"] if "SPY" in close.columns else pd.Series(dtype=float)
    spy_volume = volume["SPY"] if "SPY" in volume.columns else pd.Series(dtype=float)

    # Download VIX separately (^VIX)
    vix_close = pd.Series(dtype=float)
    try:
        vix_raw = yf.download("^VIX", start=buf_start, end=end, auto_adjust=False, progress=False)
        if not vix_raw.empty:
            if isinstance(vix_raw.columns, pd.MultiIndex):
                col = vix_raw["Close"] if "Close" in vix_raw.columns.get_level_values(0) else pd.DataFrame()
                if isinstance(col, pd.DataFrame) and not col.empty:
                    vix_close = col.squeeze()
            else:
                vix_close = vix_raw["Close"].squeeze()
            print(f"VIX data: {len(vix_close)} days ({vix_close.index[0].date()} to {vix_close.index[-1].date()})")
        else:
            warnings.warn("VIX download returned empty — VIX speed exit disabled.")
    except Exception as exc:
        warnings.warn(f"VIX download failed: {exc} — VIX speed exit disabled.")

    return close, open_px, volume, spy_close, spy_volume, vix_close


# ── Data Quality ────────────────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame, tickers: list, start: str, end: str) -> dict:
    """Flag tickers with >5 missing business days in the backtest window."""
    window = close.loc[start:end]
    expected = pd.bdate_range(start=start, end=end)
    flagged, per_ticker = [], {}
    for t in tickers:
        if t not in window.columns:
            flagged.append(t)
            per_ticker[t] = {"error": "not_in_download"}
            continue
        s = window[t].dropna()
        missing = len(expected.difference(s.index))
        per_ticker[t] = {"days": len(s), "missing": missing, "flagged": missing > 5}
        if missing > 5:
            flagged.append(t)
    return {"flagged": flagged, "per_ticker": per_ticker}


def filter_min_days(close: pd.DataFrame, tickers: list, min_days: int = 252) -> list:
    """
    Return tickers with at least min_days of non-NaN close data across the full window.
    Excludes tickers that were delisted very early or have nearly no data.
    """
    kept = []
    for t in tickers:
        if t not in close.columns:
            continue
        n = close[t].dropna().shape[0]
        if n >= min_days:
            kept.append(t)
    print(f"Pre-backtest delisted filter: {len(tickers)} → {len(kept)} tickers with ≥{min_days} days data")
    return kept


# ── Trend Template ──────────────────────────────────────────────────────────────

def compute_trend_template(
    close: pd.DataFrame, volume: pd.DataFrame, params: dict
) -> pd.DataFrame:
    """
    Minervini 9-point Trend Template (TT1–TT9) plus price and liquidity filters.
    All criteria computed backward-looking (no look-ahead).
    Returns bool DataFrame (True = qualifies), shape (dates, tickers).
    """
    tt4_lb = params["tt4_lookback"]

    sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean()
    sma200 = close.rolling(200).mean()
    low52 = close.rolling(252).min()
    high52 = close.rolling(252).max()
    dollar_adv20 = (volume * close).rolling(20).mean()

    TT1 = close > sma150
    TT2 = close > sma200
    TT3 = sma150 > sma200
    TT4 = sma200 > sma200.shift(tt4_lb)
    TT5 = sma50 > sma150
    TT6 = sma50 > sma200
    TT7 = close > sma50
    TT8 = close >= low52 * 1.30
    TT9 = close >= high52 * 0.75

    price_ok = close >= params["min_price"]
    liq_ok = dollar_adv20 >= params["min_adv_dollars"]

    tt_pass = (
        TT1 & TT2 & TT3 & TT4 & TT5 & TT6 & TT7 & TT8 & TT9 & price_ok & liq_ok
    )
    tt_pass = tt_pass.fillna(False)

    _criteria = {
        "TT1 (close>sma150)": TT1, "TT2 (close>sma200)": TT2,
        "TT3 (sma150>sma200)": TT3, "TT4 (sma200 trending)": TT4,
        "TT5 (sma50>sma150)": TT5, "TT6 (sma50>sma200)": TT6,
        "TT7 (close>sma50)": TT7, "TT8 (≥30%abv 52wLow)": TT8,
        "TT9 (≤25%blw 52wHigh)": TT9,
        "price_ok": price_ok, "liq_ok": liq_ok,
    }
    total_cells = float(tt_pass.shape[0] * tt_pass.shape[1]) or 1.0
    print("Trend Template per-criterion pass rates:")
    for name, cond in _criteria.items():
        pct = cond.fillna(False).values.sum() / total_cells * 100
        print(f"  {name}: {pct:.1f}%")
    print(f"  ALL combined: {tt_pass.values.sum() / total_cells * 100:.1f}%")

    return tt_pass


# ── M-Filter + VIX Speed Exit ───────────────────────────────────────────────────

def compute_m_filter(
    spy_close: pd.Series, spy_volume: pd.Series, vix_close: pd.Series, params: dict
) -> pd.Series:
    """
    O'Neil M-factor: count SPY distribution days in rolling window.
    Distribution day = SPY close down >= 0.2% AND volume > prior day volume.
    market_ok = True when dist_days < m_filter_dist_days.

    H82v2 addition: VIX speed exit.
    If VIX > vix_halt_threshold, market_ok → False immediately (do not wait for
    4 distribution days to accumulate). Combined condition: standard M-filter AND NOT vix_spike.
    """
    spy_ret = spy_close.pct_change()
    dist_day = (spy_ret <= -params["m_filter_down_threshold"]) & (
        spy_volume > spy_volume.shift(1)
    )
    dist_days = dist_day.rolling(params["m_filter_window"]).sum()
    m_ok_standard = dist_days < params["m_filter_dist_days"]

    if not vix_close.empty:
        vix_thresh = params.get("vix_halt_threshold", 35.0)
        vix_halt = (vix_close > vix_thresh).reindex(m_ok_standard.index).fillna(False)
        m_ok = m_ok_standard & ~vix_halt
        n_vix_halt = int(vix_halt.sum())
        print(f"VIX speed exit: {n_vix_halt} days with VIX > {vix_thresh} (halt new buys)")
    else:
        m_ok = m_ok_standard
        print("VIX speed exit: DISABLED (no VIX data)")

    return m_ok.fillna(True)


def compute_vix_persistence_exit(
    vix_close: pd.Series, m_filter_index: pd.Index, params: dict
) -> pd.Series:
    """
    Returns a boolean Series (indexed to m_filter_index / business days) where True
    indicates VIX has been CONTINUOUSLY above vix_halt_threshold for at least
    vix_exit_persistence_days consecutive days → trigger: close all open positions.

    Logic: rolling sum of (vix > threshold) over window == window → all consecutive.
    This captures the "VIX >35 persists 2 days → exit all" rule from H82v2 spec.
    """
    if vix_close.empty:
        return pd.Series(False, index=m_filter_index)

    thresh = params.get("vix_halt_threshold", 35.0)
    persist = int(params.get("vix_exit_persistence_days", 2))

    above = (vix_close > thresh).astype(int)
    # True on day T if VIX > threshold for all days in [T-persist+1, T]
    consecutive_ok = above.rolling(persist).sum() >= persist
    # Reindex to simulation business-day calendar; forward-fill gaps (weekends, holidays)
    persistence_exit = consecutive_ok.reindex(m_filter_index, method="ffill").fillna(False)
    n_exit_days = int(persistence_exit.sum())
    print(f"VIX persistence exit: {n_exit_days} days trigger (VIX >{thresh} for ≥{persist} consecutive days)")
    return persistence_exit


# ── VCP Detection ───────────────────────────────────────────────────────────────

def zigzag_swings(closes_arr: np.ndarray, min_pct: float = 0.04) -> list:
    """
    Zigzag swing detector. Returns list of (idx, price, 'H'|'L') alternating extrema.
    Each swing must represent >= min_pct reversal from the prior extreme.
    """
    n = len(closes_arr)
    if n < 4:
        return []

    swings = []
    direction = 0
    last_high_idx, last_high_price = 0, closes_arr[0]
    last_low_idx, last_low_price = 0, closes_arr[0]

    for i in range(1, n):
        p = closes_arr[i]
        if direction == 0:
            chg = (p - closes_arr[0]) / max(closes_arr[0], 1e-8)
            if chg >= min_pct:
                direction = 1
                last_high_idx, last_high_price = i, p
            elif chg <= -min_pct:
                direction = -1
                last_low_idx, last_low_price = i, p
        elif direction == 1:
            if p > last_high_price:
                last_high_idx, last_high_price = i, p
            elif p <= last_high_price * (1.0 - min_pct):
                swings.append((last_high_idx, last_high_price, "H"))
                direction = -1
                last_low_idx, last_low_price = i, p
        else:
            if p < last_low_price:
                last_low_idx, last_low_price = i, p
            elif p >= last_low_price * (1.0 + min_pct):
                swings.append((last_low_idx, last_low_price, "L"))
                direction = 1
                last_high_idx, last_high_price = i, p

    if direction == 1:
        swings.append((last_high_idx, last_high_price, "H"))
    elif direction == -1:
        swings.append((last_low_idx, last_low_price, "L"))

    return swings


def detect_vcp(
    closes_window: np.ndarray,
    volumes_window: np.ndarray,
    avg_vol_20d: float,
    params: dict,
) -> tuple:
    """
    Detect VCP in a rolling lookback window (no look-ahead).
    Returns (vcp_found: bool, pivot: float | None, reason: str).
    """
    swings = zigzag_swings(closes_window, params["min_swing_pct"])

    filtered = []
    for s in swings:
        if not filtered or filtered[-1][2] != s[2]:
            filtered.append(s)

    cycles = []
    i = 0
    while i < len(filtered) - 1:
        if filtered[i][2] == "H" and filtered[i + 1][2] == "L":
            hi_idx, hi_price = filtered[i][0], filtered[i][1]
            lo_idx, lo_price = filtered[i + 1][0], filtered[i + 1][1]
            depth = (hi_price - lo_price) / max(hi_price, 1e-8)
            v_slice = volumes_window[max(0, lo_idx - 1): lo_idx + 2]
            vol_at_low = float(np.mean(v_slice)) if len(v_slice) > 0 else 0.0
            cycles.append(
                {"hi_price": hi_price, "depth": depth, "vol_at_low": vol_at_low}
            )
            i += 2
        else:
            i += 1

    if len(cycles) < 2:
        return False, None, "no_cycles"

    if not all(
        cycles[j]["depth"] < cycles[j - 1]["depth"] * params["vcp_contraction_ratio"]
        for j in range(1, len(cycles))
    ):
        return False, None, "no_contraction"

    if avg_vol_20d <= 0:
        return False, None, "no_avg_vol"
    if cycles[-1]["vol_at_low"] >= avg_vol_20d * params["vcp_volume_dryup_ratio"]:
        return False, None, "no_dryup"

    pivot = cycles[-1]["hi_price"]
    return True, pivot, "pass"


def compute_vcp_signals(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    tt_pass: pd.DataFrame,
    params: dict,
) -> dict:
    """
    Roll through all (date, ticker) pairs where TT passes; run VCP detection
    on the prior-60-day window (no look-ahead). On VCP setup days also check
    breakout confirmation (close > pivot AND volume >= breakout_volume_ratio × avg).
    Returns: {date: {ticker: pivot}} for signal days only.
    """
    lookback = params["vcp_lookback"]
    vol20 = volume.rolling(20).mean()
    vcp_map: dict = {}
    scan_count = 0
    funnel: dict = {}

    tickers = [t for t in tt_pass.columns if t in close.columns and t in volume.columns]
    dates = tt_pass.index

    for ticker in tickers:
        c = close[ticker].values
        v = volume[ticker].values
        v20 = vol20[ticker].values if ticker in vol20.columns else np.full(len(c), np.nan)
        tt = tt_pass[ticker].values

        for di in range(lookback + 1, len(dates)):
            if not tt[di]:
                continue

            closes_60 = c[di - lookback: di]
            volumes_60 = v[di - lookback: di]

            if np.any(np.isnan(closes_60)) or len(closes_60) < 20:
                continue

            avg_vol = v20[di - 1]
            if np.isnan(avg_vol) or avg_vol <= 0:
                continue

            scan_count += 1
            vcp_found, pivot, reason = detect_vcp(closes_60, volumes_60, float(avg_vol), params)
            if not vcp_found:
                funnel[reason] = funnel.get(reason, 0) + 1
                continue

            c_today = c[di]
            v_today = v[di]
            if np.isnan(c_today) or np.isnan(v_today):
                continue
            if c_today > pivot and v_today >= avg_vol * params["breakout_volume_ratio"]:
                date = dates[di]
                if date not in vcp_map:
                    vcp_map[date] = {}
                vcp_map[date][ticker] = float(pivot)
            else:
                funnel["no_breakout"] = funnel.get("no_breakout", 0) + 1

    print(f"TT pass: {int(tt_pass.values.sum())} ticker-days | VCP scans: {scan_count}")
    print(f"VCP funnel — no_cycles: {funnel.get('no_cycles',0)}, "
          f"no_contraction: {funnel.get('no_contraction',0)}, "
          f"no_dryup: {funnel.get('no_dryup',0)}, "
          f"no_breakout: {funnel.get('no_breakout',0)}")
    return vcp_map


# ── Portfolio Simulation ────────────────────────────────────────────────────────

def simulate_portfolio(
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    volume: pd.DataFrame,
    vcp_signals: dict,
    m_filter: pd.Series,
    vix_persistence_exit: pd.Series,
    params: dict,
    start: str,
    end: str,
) -> dict:
    """
    Custom multi-position simulation for H82v2 VCP Breakout.

    H82v2 additions vs H82:
      - vix_persistence_exit: on days where this is True, liquidate ALL positions
        (same as M-filter liquidation). Triggered when VIX has been >35 for
        vix_exit_persistence_days consecutive days.

    Execution model (unchanged from H82):
      Signal at close T → execute at open T+1.
      Exit rules (in priority order):
        1. Hard stop: prev_close < entry × (1 - hard_stop_pct) → full exit next open
        2. Pattern failure: close < pivot within pattern_failure_days td → full exit
        3. Partial profit: close >= entry × (1 + partial_profit_pct) → sell 50% next open
           (8-week hold rule: postpone if +20% hit within 15 calendar days of entry)
        4. Full/trail exit (on 50%-remaining leg): full_exit_pct or trailing_stop or 8wk_max
      M-filter trip (first False day) → liquidate ALL positions.
      VIX persistence trip → liquidate ALL positions (same as M-filter).
    """
    init_cash = params["init_cash"]
    max_pos = params["max_positions"]
    hard_stop = params["hard_stop_pct"]
    partial_pct = params["partial_profit_pct"]
    full_pct = params["full_exit_pct"]
    trail_pct = params["trail_stop_pct"]
    fail_days = params["pattern_failure_days"]
    elder_halt_pct = params["elder_6pct_halt"]
    k_impact = 0.1

    sim_dates = close.loc[start:end].index
    cash = float(init_cash)
    positions: dict = {}
    trade_log: list = []
    equity_curve = pd.Series(index=sim_dates, dtype=float)

    sigma_df = close.pct_change().rolling(20).std()
    adv_df = (volume * close).rolling(20).mean()

    current_month = None
    month_start_equity = float(init_cash)
    mtd_realized = 0.0
    halt_new_trades = False

    pending_entries: dict = {}
    pending_exits: dict = {}

    prev_m_ok = True
    prev_vix_persist = False

    def _nav():
        total = cash
        for t, pos in positions.items():
            if t in close.columns:
                p = close[t].get(last_close_date, np.nan)
                if not np.isnan(p):
                    total += pos["shares"] * p
        return total

    def _cost_params(ticker, exec_date, shares, exec_price):
        slip_pct = 0.0005
        sig = sigma_df.at[exec_date, ticker] if ticker in sigma_df.columns and exec_date in sigma_df.index else 0.01
        adv_val = adv_df.at[exec_date, ticker] if ticker in adv_df.columns and exec_date in adv_df.index else float(params["min_adv_dollars"])
        if np.isnan(sig):
            sig = 0.01
        if np.isnan(adv_val) or adv_val <= 0:
            adv_val = float(params["min_adv_dollars"])
        dollar_qty = shares * exec_price
        q_over_adv = dollar_qty / adv_val
        impact = k_impact * sig * math.sqrt(max(q_over_adv, 0.0))
        return slip_pct + impact, q_over_adv

    def _execute_exit(ticker, exec_date, exec_price, reason, half_only):
        nonlocal cash, mtd_realized
        if ticker not in positions:
            return
        pos = positions[ticker]
        shares = max(int(pos["shares"] / 2), 1) if half_only else pos["shares"]
        shares = min(shares, pos["shares"])
        if shares < 1:
            return

        total_slip, q_over_adv = _cost_params(ticker, exec_date, shares, exec_price)
        proceeds = max(shares * exec_price * (1.0 - total_slip) - shares * 0.005, 0.0)
        cost_basis = shares * pos["entry_price"]
        pnl = proceeds - cost_basis
        cash += proceeds
        mtd_realized += pnl

        trade_log.append({
            "ticker": ticker,
            "entry_date": str(pos["entry_date"].date()),
            "exit_date": str(exec_date.date() if hasattr(exec_date, "date") else exec_date),
            "entry_price": round(pos["entry_price"], 4),
            "exit_price": round(exec_price, 4),
            "shares": shares,
            "pnl": round(pnl, 4),
            "return_pct": round(pnl / max(cost_basis, 1e-8), 6),
            "reason": reason,
            "liquidity_constrained": q_over_adv > 0.01,
        })

        if half_only:
            pos["shares"] -= shares
            pos["half_sold"] = True
            if pos["shares"] < 1:
                del positions[ticker]
        else:
            del positions[ticker]

    def _get_open(ticker, date):
        if date not in open_px.index or ticker not in open_px.columns:
            if date in close.index and ticker in close.columns:
                return float(close.at[date, ticker])
            return np.nan
        return float(open_px.at[date, ticker])

    last_close_date = None

    for i, date in enumerate(sim_dates):
        month_key = (date.year, date.month)
        if month_key != current_month:
            current_month = month_key
            month_start_equity = _nav() if last_close_date is not None else float(init_cash)
            mtd_realized = 0.0
            halt_new_trades = False

        # Execute pending exits (from prior day's close signals)
        for ticker, (exit_type, reason) in list(pending_exits.items()):
            exec_price = _get_open(ticker, date)
            if np.isnan(exec_price) or exec_price <= 0:
                exec_price = (
                    float(close.at[date, ticker])
                    if date in close.index and ticker in close.columns
                    else 0.0
                )
            if exec_price > 0 and ticker in positions:
                _execute_exit(ticker, date, exec_price, reason, half_only=(exit_type == "half"))
        pending_exits = {}

        # Execute pending entries
        if not halt_new_trades:
            for ticker, pivot in list(pending_entries.items()):
                if ticker in positions or len(positions) >= max_pos:
                    continue
                exec_price = _get_open(ticker, date)
                if np.isnan(exec_price) or exec_price <= 0:
                    continue

                equity_now = cash + sum(
                    positions[t]["shares"]
                    * (float(close.at[date, t]) if date in close.index and t in close.columns else 0)
                    for t in positions
                )
                risk_per_share = exec_price * hard_stop
                if risk_per_share <= 0:
                    continue
                max_risk = equity_now * params["risk_per_trade_pct"]
                max_val = equity_now * params["max_position_pct"]
                shares = int(max_risk / risk_per_share)
                shares = min(shares, int(max_val / max(exec_price, 1e-8)))
                if shares < 1:
                    continue

                total_slip, q_over_adv = _cost_params(ticker, date, shares, exec_price)
                total_cost = shares * exec_price * (1.0 + total_slip) + shares * 0.005
                if total_cost > cash:
                    continue

                cash -= total_cost
                positions[ticker] = {
                    "entry_price": exec_price,
                    "entry_date": date,
                    "shares": shares,
                    "pivot": pivot,
                    "peak_close": exec_price,
                    "half_sold": False,
                    "td_count": 0,
                    "hold_8wk_until": None,
                    "liquidity_constrained": q_over_adv > 0.01,
                }
        pending_entries = {}

        if month_start_equity > 0:
            mtd_pct = mtd_realized / month_start_equity
            if mtd_pct < -elder_halt_pct:
                halt_new_trades = True

        # M-filter state
        m_ok = bool(m_filter.get(date, True) if isinstance(m_filter, dict)
                    else (m_filter.loc[date] if date in m_filter.index else True))

        # VIX persistence exit state
        vix_persist_now = bool(
            vix_persistence_exit.loc[date] if date in vix_persistence_exit.index else False
        )

        # M-filter trip → liquidate all
        m_filter_tripped = prev_m_ok and not m_ok
        if m_filter_tripped:
            for ticker in list(positions.keys()):
                if ticker not in pending_exits:
                    pending_exits[ticker] = ("full", "m_filter_liquidate")

        # VIX persistence trip (NEW in H82v2) → liquidate all
        vix_persist_tripped = (not prev_vix_persist) and vix_persist_now
        if vix_persist_tripped:
            for ticker in list(positions.keys()):
                if ticker not in pending_exits:
                    pending_exits[ticker] = ("full", "vix_persistence_liquidate")

        prev_m_ok = m_ok
        prev_vix_persist = vix_persist_now

        # Position exit signal checks at today's close
        if date in close.index:
            for ticker in list(positions.keys()):
                if ticker in pending_exits:
                    continue
                if ticker not in close.columns:
                    continue
                pos = positions[ticker]
                c_today = float(close.at[date, ticker])
                if np.isnan(c_today):
                    continue

                pos["td_count"] += 1
                entry_price = pos["entry_price"]
                peak = pos["peak_close"]
                if c_today > peak:
                    pos["peak_close"] = c_today
                    peak = c_today

                pnl_pct = (c_today - entry_price) / max(entry_price, 1e-8)
                cal_days = (date - pos["entry_date"]).days

                # 8-week hold rule
                if (not pos["half_sold"]
                        and not pos["hold_8wk_until"]
                        and pnl_pct >= partial_pct
                        and cal_days <= 15):
                    pos["hold_8wk_until"] = pos["entry_date"] + pd.Timedelta(weeks=8)

                # Priority 1: Hard stop
                prev_close = np.nan
                if i > 0:
                    prev_d = sim_dates[i - 1]
                    if prev_d in close.index and ticker in close.columns:
                        prev_close = float(close.at[prev_d, ticker])
                if not np.isnan(prev_close) and prev_close < entry_price * (1.0 - hard_stop):
                    pending_exits[ticker] = ("full", "hard_stop")
                    continue

                # Priority 2: Pattern failure
                if not pos["half_sold"] and pos["td_count"] <= fail_days:
                    if c_today < pos["pivot"]:
                        pending_exits[ticker] = ("full", "pattern_failure")
                        continue

                # Priority 3: Partial profit at +20%
                if not pos["half_sold"]:
                    hold_until = pos.get("hold_8wk_until")
                    hold_expired = hold_until is None or date >= hold_until
                    if hold_expired and pnl_pct >= partial_pct:
                        pending_exits[ticker] = ("half", "partial_profit")
                        continue

                # Priority 4: Full exit on 50%-remaining leg
                if pos["half_sold"]:
                    trail_hit = peak > 0 and c_today <= peak * (1.0 - trail_pct)
                    profit_hit = pnl_pct >= full_pct
                    weeks_max = cal_days >= 56
                    if profit_hit:
                        pending_exits[ticker] = ("full", "full_profit_target")
                    elif trail_hit:
                        pending_exits[ticker] = ("full", "trailing_stop")
                    elif weeks_max:
                        pending_exits[ticker] = ("full", "8_week_max")

        # Queue new entries from today's VCP signals
        if not halt_new_trades and m_ok and not vix_persist_now and date in vcp_signals:
            for ticker, pivot in vcp_signals[date].items():
                slots_taken = len(positions) + sum(
                    1 for t in pending_entries if t not in positions
                )
                if slots_taken >= max_pos:
                    break
                if ticker not in positions and ticker not in pending_entries:
                    pending_entries[ticker] = pivot

        # Daily NAV
        last_close_date = date
        nav = cash
        for t, pos in positions.items():
            if t in close.columns and date in close.index:
                p = float(close.at[date, t])
                if not np.isnan(p):
                    nav += pos["shares"] * p
        equity_curve.iloc[i] = nav

    equity_curve = equity_curve.ffill().fillna(init_cash)

    daily_ret = equity_curve.pct_change().fillna(0.0).values
    sharpe = float(daily_ret.mean() / (daily_ret.std() + 1e-8) * np.sqrt(252))
    cum = np.cumprod(1.0 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(equity_curve.iloc[-1] / init_cash - 1)

    pnl_arr = np.array([t["pnl"] for t in trade_log]) if trade_log else np.array([])
    win_rate = float(np.mean(pnl_arr > 0)) if len(pnl_arr) > 0 else 0.0
    avg_win = float(pnl_arr[pnl_arr > 0].mean()) if np.any(pnl_arr > 0) else 0.0
    avg_loss = float(np.abs(pnl_arr[pnl_arr < 0]).mean()) if np.any(pnl_arr < 0) else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "win_rate": round(win_rate, 4),
        "win_loss_ratio": round(win_loss_ratio, 4) if win_loss_ratio != float("inf") else None,
        "total_return": round(total_return, 4),
        "trade_count": len(trade_log),
        "trade_log": trade_log,
        "_equity_curve": equity_curve,
    }


# ── Main Entry Point ────────────────────────────────────────────────────────────

def run_strategy(params: dict = PARAMETERS) -> dict:
    """
    Run H82v2 for IS and OOS windows. Downloads data once (including VIX); computes
    TT, M-filter (with VIX speed exit), VCP signals, and VIX persistence exit signal
    on full buffered history; then simulates IS and OOS separately.

    H82v2 vs H82:
      - Universe: ~1,047 PIT tickers from h82v2_universe_2018_jan.csv
      - VIX: downloaded and integrated into M-filter and persistence exit
      - Delisted filter: tickers with <252 days total data removed pre-simulation

    Returns dict with IS metrics, OOS metrics, trade logs, and data quality report.
    """
    tickers = load_universe(params)
    print(f"Universe: {len(tickers)} tickers loaded")

    is_start = params["is_start"]
    oos_end = params["oos_end"]

    buf_start = (pd.Timestamp(is_start) - pd.DateOffset(days=390)).strftime("%Y-%m-%d")

    print(f"Downloading OHLCV + VIX: {buf_start} to {oos_end} ...")
    close, open_px, volume, spy_close, spy_volume, vix_close = download_data(
        tickers, buf_start, oos_end
    )
    print(f"Downloaded. Dates: {len(close)}, Columns in close: {len(close.columns)}")

    # Restrict universe to downloaded tickers; filter out <252-day tickers (delistings)
    available_raw = [t for t in tickers if t in close.columns]
    available = filter_min_days(close, available_raw, min_days=252)
    print(f"Universe after delisted filter: {len(available)} tickers")

    dq_is = check_data_quality(close, available, is_start, params["is_end"])
    dq_oos = check_data_quality(close, available, params["oos_start"], oos_end)

    print("Computing Trend Template ...")
    close_universe = close[available]
    vol_universe = volume.reindex(columns=available)
    tt_pass = compute_trend_template(close_universe, vol_universe, params)

    print("Computing M-filter (with VIX speed exit) ...")
    m_filter = compute_m_filter(spy_close, spy_volume, vix_close, params)

    print("Computing VIX persistence exit signal ...")
    vix_persistence_exit = compute_vix_persistence_exit(vix_close, m_filter.index, params)

    print("Computing VCP signals (rolling 60-day window) ...")
    vcp_signals = compute_vcp_signals(close_universe, vol_universe, tt_pass, params)
    total_signals = sum(len(v) for v in vcp_signals.values())
    is_signals = sum(
        len(v) for d, v in vcp_signals.items()
        if is_start <= str(d.date()) <= params["is_end"]
    )
    print(f"VCP signal days: {len(vcp_signals)}, total signals: {total_signals}, IS signals: {is_signals}")

    print(f"Simulating IS: {is_start} to {params['is_end']} ...")
    is_result = simulate_portfolio(
        close_universe, open_px.reindex(columns=available),
        vol_universe, vcp_signals, m_filter, vix_persistence_exit, params,
        start=is_start, end=params["is_end"],
    )

    print(f"Simulating OOS: {params['oos_start']} to {oos_end} ...")
    oos_result = simulate_portfolio(
        close_universe, open_px.reindex(columns=available),
        vol_universe, vcp_signals, m_filter, vix_persistence_exit, params,
        start=params["oos_start"], end=oos_end,
    )

    liq_is = [t for t in is_result["trade_log"] if t.get("liquidity_constrained")]
    liq_oos = [t for t in oos_result["trade_log"] if t.get("liquidity_constrained")]

    return {
        "is": {k: v for k, v in is_result.items() if not k.startswith("_")},
        "oos": {k: v for k, v in oos_result.items() if not k.startswith("_")},
        "data_quality": {"is": dq_is, "oos": dq_oos},
        "universe_size": len(available),
        "universe_size_raw": len(available_raw),
        "vcp_signal_days": len(vcp_signals),
        "total_vcp_signals": total_signals,
        "is_vcp_signals": is_signals,
        "liquidity_flags_is": len(liq_is),
        "liquidity_flags_oos": len(liq_oos),
        "_is_equity_curve": is_result["_equity_curve"],
        "_oos_equity_curve": oos_result["_equity_curve"],
    }


# ── CLI Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    result = run_strategy()

    print("\n=== IS Results (2018-01-01 to 2023-12-31) ===")
    print(json.dumps({k: v for k, v in result["is"].items() if k != "trade_log"}, indent=2, default=str))

    print("\n=== OOS Results (2024-01-01 to 2025-12-31) ===")
    print(json.dumps({k: v for k, v in result["oos"].items() if k != "trade_log"}, indent=2, default=str))

    print(f"\nIS trade count:  {result['is']['trade_count']}")
    print(f"OOS trade count: {result['oos']['trade_count']}")
    print(f"Universe (after delisted filter): {result['universe_size']}")
    print(f"Liquidity flags IS:  {result['liquidity_flags_is']}")
    print(f"Liquidity flags OOS: {result['liquidity_flags_oos']}")
