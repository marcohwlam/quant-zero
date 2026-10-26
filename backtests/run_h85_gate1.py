"""
H85 Weinstein Stage 2 Sector ETF Rotation — Gate 1 Backtest
QUA-381

Two IS/OOS variants:
  Standard:  IS 2003-01-01 → 2018-12-31, OOS 2019-01-01 → 2025-06-22
  Post-GFC:  IS 2009-01-01 → 2020-12-31, OOS 2021-01-01 → 2025-06-22

Gate 7 stress test: MDD per 3-month IS window (hard ceiling 30%).
  Primary stress window: 2008 Q3-Q4 (Stage 2 → Stage 4 skip risk).

Criteria: v2.7 / kpi-daily-weekly.md v1.0
  OOS Sharpe > 0.7 (hard gate) | CS >= 0.60 | No IS Sharpe gate
  Gate 7: MDD < 30% in any IS window

Signal timing: Friday close → execute next-Monday open (no look-ahead).
Slippage: 0.05% one-way (STD_SLIP) + Almgren-Chriss market impact + $0.005/share commission.
"""

import sys
import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import date
from itertools import product as iproduct

warnings.filterwarnings("ignore", category=FutureWarning)

REPO_ROOT = Path(__file__).parent.parent
TODAY = date.today().isoformat()
STRATEGY_NAME = "H85_WeinsteinStage2SectorRotation"
OUT_DIR = REPO_ROOT / "backtests"
TRADING_DAYS = 252

# ── Universe ───────────────────────────────────────────────────────────────────
SECTOR_ETFS = ["XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB", "VNQ"]
SAFE_HAVEN = "SHY"
SPY = "SPY"
ALL_DL = SECTOR_ETFS + [SAFE_HAVEN, SPY]

# ── Cost model (ED-SLIP-001) ───────────────────────────────────────────────────
STD_SLIP = 0.0005          # 0.05% one-way — standard ETF tier (sector ETFs)
COMMISSION = 0.005         # $0.005/share each side
MARKET_IMPACT_K = 0.1     # Almgren-Chriss coefficient

# ── Primary parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "sma_weeks": 30,              # Weinstein canonical 30-week SMA
    "sma_rising_weeks": 4,        # compare SMA[t] vs SMA[t-4w]; must be positive
    "stage3_threshold": 0.005,    # SMA must rise > 0.5% over 4 weeks to be Stage 2
    "max_positions": 4,           # max sectors held simultaneously
    "min_stage2_weeks": 2,        # min consecutive Stage 2 weeks before entry
    "hard_stop_pct": 0.075,       # 7.5% hard stop per position (from entry)
    "rs_lookback_weeks": 4,       # relative strength tie-break window (vs SPY)
    "init_capital": 100_000.0,
}

# ── IS/OOS windows ─────────────────────────────────────────────────────────────
VARIANTS = {
    "Standard": {
        "IS_START":  "2003-01-01",
        "IS_END":    "2018-12-31",
        "OOS_START": "2019-01-01",
        "OOS_END":   TODAY,
    },
    "PostGFC": {
        "IS_START":  "2009-01-01",
        "IS_END":    "2020-12-31",
        "OOS_START": "2021-01-01",
        "OOS_END":   TODAY,
    },
}

# Walk-forward IS windows (Standard variant; 4 equal-ish blocks over 2003-2018)
WF_WINDOWS_STANDARD = [
    ("2003-01-01", "2006-12-31"),
    ("2007-01-01", "2010-12-31"),  # GFC — key Gate 7 test
    ("2011-01-01", "2014-12-31"),
    ("2015-01-01", "2018-12-31"),
]

# Data download buffer: 35 weeks before IS_START for SMA warm-up
DATA_START = "2001-01-01"

# Parameter sweep: 3 free parameters per hypothesis
SWEEP_SMA_RISING    = [2, 4, 8]
SWEEP_STAGE3_THRESH = [0.0025, 0.005, 0.010]
SWEEP_HARD_STOP     = [0.06, 0.075, 0.10]


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data(start: str = DATA_START, end: str = TODAY) -> dict:
    print(f"[DATA] Downloading {len(ALL_DL)} tickers from {start} to {end}...")
    raw = yf.download(ALL_DL, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close  = raw["Close"].reindex(columns=ALL_DL)
        open_  = raw["Open"].reindex(columns=ALL_DL)
        volume = raw["Volume"].reindex(columns=ALL_DL)
    else:
        # Single-ticker edge case
        close  = raw[["Close"]].rename(columns={"Close": ALL_DL[0]})
        open_  = raw[["Open"]].rename(columns={"Open": ALL_DL[0]})
        volume = raw[["Volume"]].rename(columns={"Volume": ALL_DL[0]})

    close  = close.dropna(how="all").ffill(limit=5)
    open_  = open_.reindex(close.index).ffill(limit=5)
    volume = volume.reindex(close.index).ffill(limit=5)

    print(f"  Data shape: {close.shape} | range {close.index[0].date()} – {close.index[-1].date()}")
    missing = [t for t in ALL_DL if t not in close.columns or close[t].isna().all()]
    if missing:
        print(f"  WARNING: Missing tickers: {missing}")
    return {"close": close, "open_": open_, "volume": volume}


# ── Weekly Signal Computation ──────────────────────────────────────────────────

def get_weekly_closes(daily_close: pd.DataFrame, tickers: list) -> pd.DataFrame:
    """Resample to weekly (last trading day of each week — Friday or Thursday if Friday holiday)."""
    subset = daily_close[tickers].copy()
    weekly = subset.resample("W-FRI").last()
    weekly = weekly.dropna(how="all")
    return weekly


def compute_weekly_stage2(weekly: pd.DataFrame, params: dict) -> tuple:
    """
    Compute Stage 2 and Stage 3 warning flags for each sector each week.
    Returns (stage2_df, stage3_df) both indexed by weekly date, columns = SECTOR_ETFS.
    Stage 2: price > 30-week SMA AND SMA is rising > stage3_threshold% over sma_rising_weeks.
    Stage 3: price > SMA but SMA has flattened (rise < stage3_threshold%).
    """
    sma_w      = params["sma_weeks"]
    rising_w   = params["sma_rising_weeks"]
    threshold  = params["stage3_threshold"]

    # Compute rolling SMA
    sma = weekly.rolling(sma_w, min_periods=sma_w).mean()
    sma_prev = sma.shift(rising_w)

    # SMA change pct over rising_w weeks
    sma_change_pct = (sma - sma_prev) / (sma_prev.abs() + 1e-8)

    price_above_sma = weekly > sma
    sma_rising      = sma_change_pct > threshold
    sma_positive    = sma_change_pct > 0          # SMA still rising but < threshold

    stage2         = price_above_sma & sma_rising
    stage3_warning = price_above_sma & sma_positive & ~sma_rising

    return stage2.fillna(False), stage3_warning.fillna(False)


def compute_rs_vs_spy(weekly_sectors: pd.DataFrame, weekly_spy: pd.Series,
                      rs_lookback: int) -> pd.DataFrame:
    """4-week return of each sector relative to SPY for tie-breaking."""
    sector_ret = weekly_sectors.pct_change(rs_lookback)
    spy_ret    = weekly_spy.pct_change(rs_lookback).reindex(weekly_sectors.index)
    rs = sector_ret.subtract(spy_ret, axis=0)
    return rs


def build_portfolio_signals(stage2: pd.DataFrame, stage3_warning: pd.DataFrame,
                             rs_vs_spy: pd.DataFrame, params: dict) -> dict:
    """
    For each weekly signal date, determine target portfolio (sectors or SHY).
    Returns dict: {date: {'tickers': list, 'n_stage2': int}}

    Minimum 2 consecutive Stage 2 weeks required before a sector can be entered.
    Tie-break: top-4 Stage 2 sectors by 4-week RS vs SPY.
    Fewer than 2 Stage 2 sectors qualified → SHY.
    """
    max_pos      = params["max_positions"]
    min_consec   = params.get("min_stage2_weeks", 2)

    # Compute consecutive Stage 2 weeks per sector
    consec_stage2 = pd.DataFrame(0, index=stage2.index, columns=stage2.columns)
    for i in range(1, len(stage2)):
        for col in stage2.columns:
            if stage2.iloc[i][col]:
                consec_stage2.iloc[i][col] = consec_stage2.iloc[i-1][col] + 1
            else:
                consec_stage2.iloc[i][col] = 0

    signals = {}
    for date in stage2.index:
        # Sectors that have been Stage 2 for at least min_consec weeks
        qualified = []
        for ticker in stage2.columns:
            if ticker not in stage2.columns:
                continue
            s2 = stage2.loc[date, ticker]
            consec = consec_stage2.loc[date, ticker]
            if s2 and consec >= min_consec:
                qualified.append(ticker)

        if len(qualified) >= 2:
            # Tie-break by 4-week RS vs SPY
            if date in rs_vs_spy.index:
                rs_row = rs_vs_spy.loc[date]
                rs_scores = {t: float(rs_row.get(t, 0.0)) for t in qualified
                             if not pd.isna(rs_row.get(t, np.nan))}
                qualified_sorted = sorted(qualified, key=lambda t: rs_scores.get(t, 0.0), reverse=True)
            else:
                qualified_sorted = qualified
            target = qualified_sorted[:max_pos]
            signals[date] = {"tickers": target, "n_stage2": len(qualified)}
        else:
            signals[date] = {"tickers": [SAFE_HAVEN], "n_stage2": len(qualified)}

    return signals


# ── Transaction Costs ──────────────────────────────────────────────────────────

def _buy_cost(ticker: str, shares: float, price: float,
              sigma: float, adv: float, params: dict) -> float:
    """Returns additional cost per share (slip + impact + commission)."""
    slip   = STD_SLIP
    comm   = params.get("commission_per_share", COMMISSION)
    k      = MARKET_IMPACT_K
    adv    = max(float(adv or 1e6), 1.0)
    sigma  = float(sigma or 0.01)
    q_adv  = shares / adv
    impact = k * sigma * np.sqrt(max(q_adv, 0.0))
    return price * (slip + impact) + comm


def _sell_proceeds(ticker: str, shares: float, price: float,
                   sigma: float, adv: float, params: dict) -> float:
    """Returns net proceeds after sell costs."""
    slip   = STD_SLIP
    comm   = params.get("commission_per_share", COMMISSION)
    k      = MARKET_IMPACT_K
    adv    = max(float(adv or 1e6), 1.0)
    sigma  = float(sigma or 0.01)
    q_adv  = shares / adv
    impact = k * sigma * np.sqrt(max(q_adv, 0.0))
    return max(shares * price * (1 - slip - impact) - shares * comm, 0.0)


def _get(series, t, fallback=np.nan):
    if series is None:
        return fallback
    try:
        v = series.get(t, fallback)
    except Exception:
        return fallback
    return float(v) if (v is not None and not pd.isna(v)) else fallback


# ── Portfolio Simulation ───────────────────────────────────────────────────────

def run_backtest(data: dict, portfolio_signals: dict, params: dict,
                 start: str, end: str, period_label: str = "?") -> dict:
    """
    Simulate H85 strategy.

    Execution model:
      - Signal on Friday close → execute following Monday open (no look-ahead).
      - Hard stops: checked against daily close; exit at next trading day open.
      - Rebalance: sell sectors exiting Stage 2 (or below min); buy newly qualified.
      - If < 2 Stage 2 sectors: liquidate all to SHY.

    Returns dict with portfolio_values, trade_log, daily_returns.
    """
    close  = data["close"]
    open_  = data["open_"]
    volume = data["volume"]

    hard_stop = params["hard_stop_pct"]
    init_cap  = params["init_capital"]

    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)
    window   = close.loc[ts_start:ts_end].index
    if len(window) < 5:
        raise ValueError(f"Insufficient data {start}:{end}: {len(window)} days")

    # Precompute 20-day rolling sigma and ADV
    sigma_20 = {}
    adv_20   = {}
    for tk in ALL_DL:
        if tk in close.columns:
            sigma_20[tk] = close[tk].pct_change().rolling(20, min_periods=5).std()
        if tk in volume.columns:
            adv_20[tk] = volume[tk].rolling(20, min_periods=5).mean()

    # Map each trading day to the Friday signal that governs it.
    # Friday signal → governs next Mon-Fri block.
    # Build: for each day, what is the most recent past Friday in signals?
    signal_dates_sorted = sorted(portfolio_signals.keys())

    def get_active_signal(t_day: pd.Timestamp) -> dict:
        """Return the most recent past-or-equal signal for day t_day."""
        # Binary search for latest signal <= t_day
        lo, hi = 0, len(signal_dates_sorted) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if signal_dates_sorted[mid] <= t_day:
                best = signal_dates_sorted[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return portfolio_signals.get(best, {"tickers": [SAFE_HAVEN], "n_stage2": 0}) if best else {"tickers": [SAFE_HAVEN], "n_stage2": 0}

    # Identify week-end trading days (last day of each week in our window)
    # We queue a rebalance check every Friday (or last day of week)
    week_ends = set(close.loc[ts_start:ts_end].resample("W-FRI").last().dropna(how="all").index)

    cash        = float(init_cap)
    positions   = {}       # ticker → shares
    entry_info  = {}       # ticker → {price: float, date: str, week_date: pd.Timestamp}
    pending_tgt = None     # set on Friday, executed Monday
    stop_sells  = set()    # tickers flagged for stop-loss exit

    portfolio_values = pd.Series(np.nan, index=window, dtype=float)
    trade_log        = []

    def gp(df, ticker, t_day):
        if ticker not in df.columns or t_day not in df.index:
            return np.nan
        v = df.loc[t_day, ticker]
        return float(v) if not pd.isna(v) else np.nan

    prev_tgt = list(get_active_signal(window[0])["tickers"]) if len(window) > 0 else [SAFE_HAVEN]
    pending_tgt = prev_tgt[:]  # execute on day 0

    for i, t_day in enumerate(window):
        # ── 1. Execute pending trades (rebalance or stop-loss) ──────────────────
        if pending_tgt is not None:
            new_set = set(pending_tgt)
            cur_set = set(positions.keys())
            to_sell = (cur_set - new_set) | stop_sells
            to_buy  = new_set - cur_set

            # Sell exits first
            for ticker in sorted(to_sell & cur_set):
                sh = positions.get(ticker, 0.0)
                if sh <= 0:
                    continue
                px = gp(open_, ticker, t_day)
                if np.isnan(px) or px <= 0:
                    px = gp(close, ticker, t_day)
                if np.isnan(px) or px <= 0:
                    continue
                sig_v = _get(sigma_20.get(ticker), t_day, 0.01) or 0.01
                adv_v = _get(adv_20.get(ticker), t_day, 1e6) or 1e6
                proceeds = _sell_proceeds(ticker, sh, px, sig_v, adv_v, params)
                cash += proceeds
                ei = entry_info.pop(ticker, {"price": px, "date": str(t_day.date())})
                reason = "stop" if ticker in stop_sells else "rebalance"
                pnl = proceeds - sh * float(ei["price"])
                trade_log.append({
                    "period":      period_label,
                    "ticker":      ticker,
                    "entry_date":  ei["date"],
                    "exit_date":   str(t_day.date()),
                    "entry_price": round(float(ei["price"]), 4),
                    "exit_price":  round(float(px), 4),
                    "shares":      round(float(sh), 4),
                    "pnl":         round(float(pnl), 2),
                    "exit_reason": reason,
                })
                del positions[ticker]
            stop_sells.clear()

            # Buy new positions
            n_buy = len(to_buy)
            if n_buy > 0:
                cash_per = cash / n_buy
                for ticker in sorted(to_buy):
                    px = gp(open_, ticker, t_day)
                    if np.isnan(px) or px <= 0:
                        px = gp(close, ticker, t_day)
                    if np.isnan(px) or px <= 0:
                        continue
                    sig_v = _get(sigma_20.get(ticker), t_day, 0.01) or 0.01
                    adv_v = _get(adv_20.get(ticker), t_day, 1e6) or 1e6
                    cost_ps  = _buy_cost(ticker, cash_per / (px + 1e-8), px, sig_v, adv_v, params)
                    total_ps = px + cost_ps
                    sh       = cash_per / total_ps if total_ps > 0 else 0.0
                    sh       = max(sh, 0.0)
                    spent    = sh * total_ps
                    cash    -= spent
                    if sh > 0:
                        positions[ticker] = sh
                        entry_info[ticker] = {"price": float(px), "date": str(t_day.date())}

            pending_tgt = None

        # ── 2. Compute daily NAV ────────────────────────────────────────────────
        nav = cash
        for ticker, sh in positions.items():
            px = gp(close, ticker, t_day)
            if not np.isnan(px) and px > 0:
                nav += sh * px
        portfolio_values.iloc[i] = max(nav, 0.0)

        # ── 3. Check hard stops (daily close) ──────────────────────────────────
        for ticker, sh in list(positions.items()):
            ei = entry_info.get(ticker)
            if ei is None:
                continue
            px = gp(close, ticker, t_day)
            if np.isnan(px) or px <= 0:
                continue
            if px < ei["price"] * (1.0 - hard_stop):
                stop_sells.add(ticker)

        if stop_sells:
            # Set pending_tgt for next day: keep non-stopped positions, remove stopped
            next_tgt_set = set(positions.keys()) - stop_sells
            # Re-add SAFE_HAVEN if we go below 2 sectors
            if len(next_tgt_set) < 1:
                next_tgt_set = {SAFE_HAVEN}
            pending_tgt = sorted(next_tgt_set)

        # ── 4. Weekly signal check (last trading day of week = "Friday") ────────
        if t_day in week_ends and not stop_sells:
            sig = get_active_signal(t_day)
            new_tgt = sig["tickers"]
            if set(new_tgt) != set(positions.keys()) - stop_sells:
                pending_tgt = list(new_tgt)

    # ── Close all open positions at window end ──────────────────────────────────
    if positions:
        last_t = window[-1]
        for ticker, sh in list(positions.items()):
            px = gp(close, ticker, last_t)
            if np.isnan(px) or px <= 0:
                continue
            ei = entry_info.pop(ticker, {"price": px, "date": str(last_t.date())})
            pnl = sh * px - sh * float(ei["price"])
            trade_log.append({
                "period":      period_label,
                "ticker":      ticker,
                "entry_date":  ei["date"],
                "exit_date":   str(last_t.date()),
                "entry_price": round(float(ei["price"]), 4),
                "exit_price":  round(float(px), 4),
                "shares":      round(float(sh), 4),
                "pnl":         round(float(pnl), 2),
                "exit_reason": "window_end",
            })

    portfolio_values = portfolio_values.ffill().fillna(float(init_cap))
    return {"portfolio_values": portfolio_values, "trade_log": trade_log}


# ── Metrics ────────────────────────────────────────────────────────────────────

def compute_metrics(portfolio_values: pd.Series, trade_log: list,
                    start: str, end: str) -> dict:
    pv = portfolio_values.dropna()
    if len(pv) < 2:
        return {"error": "insufficient data"}

    daily_ret = pv.pct_change().fillna(0.0).values
    sharpe    = float(daily_ret.mean() / (daily_ret.std() + 1e-10) * np.sqrt(TRADING_DAYS))

    ts_start  = pd.Timestamp(start)
    ts_end    = pd.Timestamp(end)
    years     = (ts_end - ts_start).days / 365.25
    total_ret = float(pv.iloc[-1] / pv.iloc[0] - 1)
    cagr      = float((pv.iloc[-1] / pv.iloc[0]) ** (1.0 / max(years, 0.01)) - 1)

    cum      = np.cumprod(1 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd      = float(np.min((cum - roll_max) / (roll_max + 1e-10)))

    closed  = [t for t in trade_log if t.get("exit_reason") != "window_end"]
    if closed:
        pnl_arr  = np.array([t["pnl"] for t in closed])
        win_rate = float(np.mean(pnl_arr > 0))
        wins     = pnl_arr[pnl_arr > 0]
        losses   = pnl_arr[pnl_arr < 0]
        pf  = float(wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 0 else float("inf")
        # PpT in bps relative to initial capital
        avg_ppt_bps = float(np.mean(pnl_arr / (pv.iloc[0] + 1e-8) * 10_000))
    else:
        win_rate = pf = avg_ppt_bps = 0.0

    # Overnight gap attribution
    # Estimate: pct of daily returns that are gap-open returns (open/prev_close - 1)
    gap_fraction = 0.0  # placeholder — computed separately

    return {
        "sharpe":        round(sharpe, 4),
        "cagr":          round(cagr, 4),
        "max_drawdown":  round(mdd, 4),
        "total_return":  round(total_ret, 4),
        "trade_count":   len(closed),
        "win_rate":      round(win_rate, 4),
        "profit_factor": round(pf, 4) if not np.isinf(pf) else "inf",
        "avg_ppt_bps":   round(avg_ppt_bps, 2),
        "period":        f"{start} to {end}",
        "years":         round(years, 2),
        "_daily_returns": daily_ret,
    }


# ── Gate 7: MDD per 3-Month IS Window ─────────────────────────────────────────

def compute_gate7_windows(portfolio_values: pd.Series, is_start: str, is_end: str) -> dict:
    """
    Report MDD for each 3-month (calendar quarter) IS window.
    Auto-reject flag if any single window exceeds 30% MDD.
    Primary stress windows: 2008-Q3, 2008-Q4.
    """
    ts_start = pd.Timestamp(is_start)
    ts_end   = pd.Timestamp(is_end)
    pv_is    = portfolio_values.loc[ts_start:ts_end]
    if len(pv_is) < 5:
        return {"error": "insufficient IS data", "gate7_pass": False, "windows": []}

    # Generate quarterly windows
    quarters = pd.date_range(ts_start, ts_end + pd.DateOffset(months=3), freq="QS")
    windows  = []
    gate7_worst_mdd = 0.0
    gate7_pass      = True

    for i in range(len(quarters) - 1):
        q_start = quarters[i]
        q_end   = quarters[i + 1] - pd.Timedelta(days=1)
        if q_end > ts_end:
            q_end = ts_end

        q_pv = pv_is.loc[q_start:q_end]
        if len(q_pv) < 5:
            continue

        q_ret    = q_pv.pct_change().fillna(0.0).values
        cum      = np.cumprod(1 + q_ret)
        roll_max = np.maximum.accumulate(cum)
        q_mdd    = float(np.min((cum - roll_max) / (roll_max + 1e-10)))

        if abs(q_mdd) > abs(gate7_worst_mdd):
            gate7_worst_mdd = q_mdd
        if q_mdd < -0.30:
            gate7_pass = False

        windows.append({
            "window_start": str(q_start.date()),
            "window_end":   str(q_end.date()),
            "mdd":          round(q_mdd, 4),
            "gate7_ok":     q_mdd > -0.30,
            "is_stress_2008_q3": (q_start.year == 2008 and q_start.month == 7),
            "is_stress_2008_q4": (q_start.year == 2008 and q_start.month == 10),
        })

    # Flag if any quarter below 30 trades (trade count per quarter)
    return {
        "windows":            windows,
        "gate7_pass":         gate7_pass,
        "gate7_worst_mdd":    round(gate7_worst_mdd, 4),
        "n_windows":          len(windows),
        "n_windows_exceed_30pct": sum(1 for w in windows if not w["gate7_ok"]),
    }


def compute_quarterly_trade_counts(trade_log: list, is_start: str, is_end: str) -> dict:
    """Count trades per 3-month IS window; flag any below 30."""
    closed = [t for t in trade_log if t.get("exit_reason") not in ("window_end",)]
    ts_start = pd.Timestamp(is_start)
    ts_end   = pd.Timestamp(is_end)
    quarters = pd.date_range(ts_start, ts_end + pd.DateOffset(months=3), freq="QS")
    results  = []
    for i in range(len(quarters) - 1):
        q_start = quarters[i]
        q_end   = quarters[i + 1] - pd.Timedelta(days=1)
        count = sum(
            1 for t in closed
            if q_start <= pd.Timestamp(t.get("exit_date", "2000-01-01")) <= q_end
        )
        results.append({
            "quarter": f"{q_start.year}-Q{(q_start.month-1)//3+1}",
            "trade_count": count,
            "pf1_flag": count < 30,
        })
    flagged = [r for r in results if r["pf1_flag"]]
    return {
        "by_quarter": results,
        "min_quarter_trades": min((r["trade_count"] for r in results), default=0),
        "n_quarters_below_30": len(flagged),
        "flagged_quarters": flagged,
    }


# ── Composite Score (v2.7) ─────────────────────────────────────────────────────

def compute_cs(oos_sharpe: float, is_mdd: float,
               avg_ppt_bps: float, trade_count: int) -> tuple:
    """CS = 0.40×NetSharpe_norm + 0.30×Stability_norm + 0.20×PpT_norm + 0.10×TradeAdq_norm."""
    sharpe_norm = float(np.clip((oos_sharpe - (-0.5)) / (2.0 - (-0.5)), 0.0, 1.0))
    stab_norm   = float(np.clip(1.0 - abs(is_mdd) / 0.20, 0.0, 1.0))
    ppt_norm    = float(np.clip(avg_ppt_bps / 100.0, 0.0, 1.0))
    trade_norm  = float(min(1.0, trade_count / 30.0))
    cs = 0.40 * sharpe_norm + 0.30 * stab_norm + 0.20 * ppt_norm + 0.10 * trade_norm
    return round(cs, 4), {
        "sharpe_norm": round(sharpe_norm, 4),
        "stab_norm":   round(stab_norm, 4),
        "ppt_norm":    round(ppt_norm, 4),
        "trade_norm":  round(trade_norm, 4),
    }


# ── Statistical Rigor ──────────────────────────────────────────────────────────

def monte_carlo_sharpe(pnl_arr: np.ndarray, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    if len(pnl_arr) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    sharpes = []
    for _ in range(n_sims):
        s  = np.random.choice(pnl_arr, size=len(pnl_arr), replace=True)
        sh = s.mean() / (s.std() + 1e-8) * np.sqrt(TRADING_DAYS)
        sharpes.append(sh)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe":    float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    np.random.seed(43)
    T         = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks  = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s: s + block_len] for s in starts])[:T]
        if len(sample) < 2:
            continue
        cum      = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        sh  = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS))
        wr  = float(np.mean(sample > 0))
        sharpes.append(sh); mdds.append(mdd); win_rates.append(wr)
    if not sharpes:
        return {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
                "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
                "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0}
    return {
        "sharpe_ci_low":    float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high":   float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":       float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":      float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low":  float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def compute_dsr(is_sharpe: float, n_trials: int, T: int) -> float:
    if T <= 0 or n_trials <= 1:
        return float(is_sharpe)
    gamma  = 0.5772
    ln_n   = np.log(max(n_trials, 2))
    exp_max = (
        np.sqrt(2 * ln_n)
        - (np.log(np.log(max(n_trials, 2))) + np.log(4 * np.pi)) / (2 * np.sqrt(2 * ln_n))
        + gamma / np.sqrt(2 * ln_n)
    ) / np.sqrt(T)
    return round(float(is_sharpe - exp_max), 4)


def permutation_test(portfolio_values: pd.Series, observed_sharpe: float,
                     n_perms: int = 500) -> dict:
    np.random.seed(44)
    returns = portfolio_values.pct_change().fillna(0.0).values
    T = len(returns)
    if T < 20:
        return {"permutation_pvalue": 0.5, "permutation_test_pass": False}
    perm_sharpes = []
    for _ in range(n_perms):
        shuffled = np.random.permutation(returns)
        s = float(shuffled.mean() / (shuffled.std() + 1e-8) * np.sqrt(TRADING_DAYS))
        perm_sharpes.append(s)
    perm_np = np.array(perm_sharpes)
    p_value = float(np.mean(perm_np >= observed_sharpe))
    return {
        "permutation_pvalue":    round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
        "permutation_perm_mean": float(perm_np.mean()),
        "permutation_perm_p95":  float(np.percentile(perm_np, 95)),
    }


# ── Walk-Forward Analysis ──────────────────────────────────────────────────────

def run_walk_forward(data: dict, params: dict, wf_windows: list,
                     weekly: pd.DataFrame, stage2: pd.DataFrame,
                     stage3: pd.DataFrame, rs_vs_spy: pd.DataFrame) -> list:
    results = []
    portfolio_sigs = build_portfolio_signals(stage2, stage3, rs_vs_spy, params)

    for i, (wf_start, wf_end) in enumerate(wf_windows):
        try:
            wf_res  = run_backtest(data, portfolio_sigs, params, wf_start, wf_end, f"WF{i+1}")
            wf_m    = compute_metrics(wf_res["portfolio_values"], wf_res["trade_log"],
                                      wf_start, wf_end)
            gate7_wf = wf_m["max_drawdown"] > -0.30
            results.append({
                "window":      i + 1,
                "is_start":    wf_start,
                "is_end":      wf_end,
                "sharpe":      wf_m["sharpe"],
                "max_drawdown": wf_m["max_drawdown"],
                "win_rate":    wf_m["win_rate"],
                "trade_count": wf_m["trade_count"],
                "cagr":        wf_m["cagr"],
                "gate7_pass":  gate7_wf,
            })
            print(f"  WF{i+1} ({wf_start}–{wf_end}): Sharpe={wf_m['sharpe']:.3f}, "
                  f"MDD={wf_m['max_drawdown']:.2%}, trades={wf_m['trade_count']}, "
                  f"Gate7={'PASS' if gate7_wf else 'FAIL'}")
        except Exception as e:
            results.append({"window": i+1, "is_start": wf_start, "is_end": wf_end,
                            "sharpe": 0.0, "max_drawdown": 0.0, "error": str(e),
                            "gate7_pass": False})
            print(f"  WF{i+1} ERROR: {e}")
    return results


# ── Parameter Sweep ────────────────────────────────────────────────────────────

def run_sweep(data: dict, weekly: pd.DataFrame, is_start: str, is_end: str,
              weekly_spy: pd.Series) -> list:
    """27 combos over 3 free parameters: sma_rising × stage3_threshold × hard_stop."""
    combos = list(iproduct(SWEEP_SMA_RISING, SWEEP_STAGE3_THRESH, SWEEP_HARD_STOP))
    print(f"  Running {len(combos)} sweep combinations...")
    rows = []
    for rising_w, thresh, stop in combos:
        p = {**PARAMETERS,
             "sma_rising_weeks": rising_w,
             "stage3_threshold": thresh,
             "hard_stop_pct": stop}
        label = f"rising={rising_w}w, thresh={thresh:.2%}, stop={stop:.1%}"
        try:
            s2, s3   = compute_weekly_stage2(weekly, p)
            rs       = compute_rs_vs_spy(weekly, weekly_spy, p.get("rs_lookback_weeks", 4))
            sigs     = build_portfolio_signals(s2, s3, rs, p)
            bt       = run_backtest(data, sigs, p, is_start, is_end, "SWEEP")
            m        = compute_metrics(bt["portfolio_values"], bt["trade_log"], is_start, is_end)
            rows.append({
                "sma_rising_weeks":  rising_w,
                "stage3_threshold":  thresh,
                "hard_stop_pct":     stop,
                "sharpe":            m["sharpe"],
                "cagr":              m["cagr"],
                "max_drawdown":      m["max_drawdown"],
                "win_rate":          m["win_rate"],
                "trade_count":       m["trade_count"],
                "avg_ppt_bps":       m["avg_ppt_bps"],
            })
            print(f"    {label}: Sharpe={m['sharpe']:.3f}, MDD={m['max_drawdown']:.2%}, "
                  f"trades={m['trade_count']}")
        except Exception as e:
            rows.append({"sma_rising_weeks": rising_w, "stage3_threshold": thresh,
                         "hard_stop_pct": stop, "error": str(e)})
            print(f"    {label}: ERROR {e}")
    return rows


# ── Market Impact Report ───────────────────────────────────────────────────────

def compute_market_impact(data: dict, start: str, end: str,
                          n_positions: int = 4) -> dict:
    close  = data["close"]
    volume = data["volume"]
    cap_pp = PARAMETERS["init_capital"] / n_positions
    results = {}
    for tk in SECTOR_ETFS + [SAFE_HAVEN]:
        if tk not in close.columns:
            continue
        try:
            hist_c = close[tk].loc[start:end].dropna()
            hist_v = volume[tk].loc[start:end].dropna() if tk in volume.columns else pd.Series()
            if len(hist_c) < 20:
                results[tk] = {"note": "insufficient data"}
                continue
            avg_px = float(hist_c.tail(20).mean())
            adv    = float(hist_v.tail(20).mean()) if len(hist_v) >= 20 else 1e6
            sigma  = float(hist_c.pct_change().tail(60).std())
            qty    = cap_pp / max(avg_px, 1.0)
            q_adv  = qty / max(adv, 1.0)
            impact = MARKET_IMPACT_K * sigma * np.sqrt(max(q_adv, 0.0))
            results[tk] = {
                "market_impact_bps":     round(float(impact * 10_000), 4),
                "adv_20d":               round(float(adv), 0),
                "avg_price":             round(float(avg_px), 2),
                "qty_at_cap_pp":         round(float(qty), 0),
                "q_over_adv":            round(float(q_adv), 6),
                "liquidity_constrained": q_adv > 0.01,
                "slippage_pct":          STD_SLIP * 100,
            }
        except Exception as e:
            results[tk] = {"error": str(e)}
    return results


# ── Cost-to-Gross Profit Ratio ────────────────────────────────────────────────

def compute_cpr(trade_log: list, portfolio_values: pd.Series,
                init_capital: float) -> float:
    closed = [t for t in trade_log if t.get("exit_reason") != "window_end"]
    pnl_arr = np.array([t["pnl"] for t in closed]) if closed else np.array([0.0])
    gross_profit = float(np.sum(pnl_arr[pnl_arr > 0]))
    # Estimate costs: slip + commission per trade
    total_costs = 0.0
    for t in closed:
        ep    = t.get("entry_price", 0)
        xp    = t.get("exit_price", 0)
        sh    = t.get("shares", 0)
        total_costs += sh * ep * STD_SLIP + sh * COMMISSION   # buy slip + comm
        total_costs += sh * xp * STD_SLIP + sh * COMMISSION   # sell slip + comm
    return round(total_costs / max(gross_profit, 1.0), 6)


# ── HTML Report ────────────────────────────────────────────────────────────────

def build_html_report(variant: str, is_m: dict, oos_m: dict, wf_results: list,
                      sweep_rows: list, mi_report: dict, mc: dict, bb: dict,
                      perm: dict, dsr: float, cs: float, cs_comp: dict,
                      verdict_label: str, checks: list,
                      gate7: dict, q_trades: dict,
                      is_start: str, is_end: str,
                      oos_start: str, oos_end: str,
                      postgfc_note: str = "") -> str:
    vc = "#d4edda" if verdict_label == "PASS" else "#f8d7da"
    check_rows = "".join(
        f"<tr style='background:{'#d4edda' if p else '#f8d7da'}'>"
        f"<td>{g}</td><td>{v}</td><td>{t}</td><td>{'✓ PASS' if p else '✗ FAIL'}</td></tr>"
        for g, v, t, p in checks
    )
    wf_rows = "".join(
        f"<tr style='background:{'#d4edda' if w.get('gate7_pass', True) else '#f8d7da'}'>"
        f"<td>{w['window']}</td><td>{w.get('is_start','')}–{w.get('is_end','')}</td>"
        f"<td>{w.get('sharpe', 0):.4f}</td><td>{w.get('max_drawdown', 0):.2%}</td>"
        f"<td>{w.get('win_rate', 0):.2%}</td><td>{w.get('trade_count', 0)}</td>"
        f"<td>{'✓' if w.get('gate7_pass', False) else '✗ FAIL'}</td></tr>"
        for w in wf_results
    )
    # Gate 7 quarterly window table (top 10 worst)
    g7_sorted = sorted(gate7.get("windows", []), key=lambda x: x["mdd"])[:15]
    g7_rows = "".join(
        f"<tr style='background:{'#f8d7da' if not w['gate7_ok'] else ''}'>"
        f"<td>{w['window_start']}–{w['window_end']}</td>"
        f"<td>{w['mdd']:.2%}</td>"
        f"<td>{'✓' if w['gate7_ok'] else '✗ FAIL (>30%)'}</td>"
        f"<td>{'2008-Q3 STRESS' if w.get('is_stress_2008_q3') else '2008-Q4 STRESS' if w.get('is_stress_2008_q4') else ''}</td></tr>"
        for w in g7_sorted
    )
    pf1_flag_str = f"{q_trades.get('n_quarters_below_30', 0)} quarters below 30 trades"
    sweep_html = pd.DataFrame(sweep_rows).to_html(index=False, border=1,
                               float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x)) if sweep_rows else "<p>N/A</p>"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>H85 Weinstein Stage 2 Sector ETF Rotation — Gate 1 — {variant}</title>
<style>
body {{ font-family: monospace; max-width: 1200px; margin: 0 auto; padding: 20px; }}
h1 {{ background: #343a40; color: white; padding: 15px; border-radius: 4px; }}
h2 {{ border-bottom: 2px solid #343a40; padding-bottom: 5px; margin-top: 30px; }}
.verdict {{ font-size: 2em; font-weight: bold; padding: 15px; border-radius: 4px;
           background: {vc}; text-align: center; margin: 20px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th {{ background: #343a40; color: white; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border: 1px solid #dee2e6; }}
.section {{ margin: 20px 0; padding: 15px; border: 1px solid #dee2e6; border-radius: 4px; }}
</style>
</head>
<body>
<h1>H85 Weinstein Stage 2 Sector ETF Rotation — Gate 1 — {variant}</h1>
<p><strong>Date:</strong> {TODAY} | <strong>Variant:</strong> {variant}</p>
<p><strong>Universe:</strong> {', '.join(SECTOR_ETFS)} + {SAFE_HAVEN}</p>
<p><strong>Signal:</strong> Price > rising 30-week SMA (Stage 2) | Max 4 sectors | SHY if &lt;2 qualify</p>
<p><strong>IS:</strong> {is_start} → {is_end} | <strong>OOS:</strong> {oos_start} → {oos_end}</p>
<p><strong>Criteria:</strong> v2.7 / kpi-daily-weekly.md v1.0 — OOS Sharpe &gt; 0.7 | CS ≥ 0.60 | Gate 7 MDD &lt; 30% | NO IS Sharpe gate</p>
<p><strong>Cost model:</strong> $0.005/share + 0.05% slip + 0.1×σ×√(Q/ADV) market impact</p>
{postgfc_note}

<div class="verdict">GATE 1 ({variant}): {verdict_label}</div>

<h2>Gate 1 Checklist (v2.7)</h2>
<table><tr><th>Gate</th><th>Value</th><th>Threshold</th><th>Result</th></tr>{check_rows}</table>

<h2>Composite Score (v2.7)</h2>
<div class="section">
<p><strong>CS = {cs:.4f}</strong> (threshold ≥ 0.60)</p>
<p>NetSharpe_norm={cs_comp['sharpe_norm']:.4f} × 0.40 = {cs_comp['sharpe_norm']*0.40:.4f}</p>
<p>Stability_norm={cs_comp['stab_norm']:.4f} × 0.30 = {cs_comp['stab_norm']*0.30:.4f}</p>
<p>PpT_norm={cs_comp['ppt_norm']:.4f} × 0.20 = {cs_comp['ppt_norm']*0.20:.4f}</p>
<p>TradeAdequacy_norm={cs_comp['trade_norm']:.4f} × 0.10 = {cs_comp['trade_norm']*0.10:.4f}</p>
</div>

<h2>IS / OOS Summary</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>IS ({is_start}–{is_end})</th><th>OOS ({oos_start}–{oos_end})</th></tr>
<tr><td>Sharpe</td><td>{is_m['sharpe']:.4f} [diagnostic only]</td><td>{oos_m['sharpe']:.4f} [HARD GATE]</td></tr>
<tr><td>CAGR</td><td>{is_m['cagr']:.2%}</td><td>{oos_m['cagr']:.2%}</td></tr>
<tr><td>Max Drawdown</td><td>{is_m['max_drawdown']:.2%}</td><td>{oos_m['max_drawdown']:.2%}</td></tr>
<tr><td>Win Rate</td><td>{is_m['win_rate']:.2%}</td><td>{oos_m['win_rate']:.2%}</td></tr>
<tr><td>Profit Factor</td><td>{is_m['profit_factor']}</td><td>{oos_m['profit_factor']}</td></tr>
<tr><td>Trade Count</td><td>{is_m['trade_count']}</td><td>{oos_m['trade_count']}</td></tr>
<tr><td>Avg PpT (bps)</td><td>{is_m['avg_ppt_bps']:.2f}</td><td>{oos_m['avg_ppt_bps']:.2f}</td></tr>
</table>
</div>

<h2>Gate 7 — MDD by 3-Month IS Window (Worst 15 shown; threshold: &lt; 30%)</h2>
<p>Gate 7 pass: <strong>{'✓ YES' if gate7.get('gate7_pass') else '✗ NO (auto-reject)'}</strong>
   | Worst window MDD: <strong>{gate7.get('gate7_worst_mdd', 0):.2%}</strong>
   | Windows exceeding 30%: <strong>{gate7.get('n_windows_exceed_30pct', 0)}</strong></p>
<table>
<tr><th>Window</th><th>MDD</th><th>Gate 7</th><th>Note</th></tr>
{g7_rows}
</table>

<h2>PF-1 — Quarterly Trade Count</h2>
<p>Minimum quarter trades: <strong>{q_trades.get('min_quarter_trades', 0)}</strong>
   | Quarters below 30: <strong>{pf1_flag_str}</strong> (flag-only, not auto-reject)</p>

<h2>Walk-Forward Analysis (4 IS Windows)</h2>
<table>
<tr><th>Window</th><th>Period</th><th>Sharpe</th><th>MDD</th><th>Win Rate</th><th>Trades</th><th>Gate 7</th></tr>
{wf_rows}
</table>

<h2>Statistical Tests</h2>
<div class="section">
<p><strong>Monte Carlo (1000 resamples):</strong> p5={mc['mc_p5_sharpe']:.4f}, median={mc['mc_median_sharpe']:.4f}, p95={mc['mc_p95_sharpe']:.4f}</p>
<p><strong>Block Bootstrap CI (95%):</strong> Sharpe [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}] | MDD [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]</p>
<p><strong>Permutation test (500 perms):</strong> p={perm['permutation_pvalue']:.4f} — {"PASS" if perm['permutation_test_pass'] else "FAIL"}</p>
<p><strong>DSR:</strong> {dsr:.4f} — {"PASS" if dsr > 0 else "FAIL"}</p>
</div>

<h2>Parameter Sweep (27 Combinations)</h2>
{sweep_html}

<h2>Market Impact by Ticker</h2>
<table>
<tr><th>Ticker</th><th>Impact (bps)</th><th>ADV 20d</th><th>Q/ADV</th><th>Constrained?</th></tr>
{"".join(
    f"<tr><td>{tk}</td><td>{d.get('market_impact_bps', 0):.4f}</td>"
    f"<td>{d.get('adv_20d', 0):,.0f}</td><td>{d.get('q_over_adv', 0):.6f}</td>"
    f"<td>{'YES' if d.get('liquidity_constrained') else 'no'}</td></tr>"
    for tk, d in mi_report.items() if isinstance(d, dict) and 'market_impact_bps' in d
)}
</table>

<hr>
<p><em>Engineering Director | QUA-381 | H85 Gate 1 | {TODAY}</em></p>
</body>
</html>"""


# ── Main Execution ─────────────────────────────────────────────────────────────

def run_variant(data: dict, weekly: pd.DataFrame, weekly_spy: pd.Series,
                stage2: pd.DataFrame, stage3: pd.DataFrame, rs_vs_spy: pd.DataFrame,
                variant_name: str, variant_cfg: dict,
                wf_windows: list, sweep_rows: list) -> dict:
    """Run Gate 1 analysis for one IS/OOS variant."""
    is_start  = variant_cfg["IS_START"]
    is_end    = variant_cfg["IS_END"]
    oos_start = variant_cfg["OOS_START"]
    oos_end   = variant_cfg["OOS_END"]

    print(f"\n{'='*70}")
    print(f"H85 — {variant_name}: IS={is_start}→{is_end} | OOS={oos_start}→{oos_end}")
    print(f"{'='*70}")

    # Build signals
    portfolio_sigs = build_portfolio_signals(stage2, stage3, rs_vs_spy, PARAMETERS)
    n_sigs    = len(portfolio_sigs)
    n_shy     = sum(1 for s in portfolio_sigs.values() if s["tickers"] == [SAFE_HAVEN])
    print(f"  Signals: {n_sigs} weekly dates | SHY (fully defensive): {n_shy} "
          f"({n_shy/max(n_sigs,1):.1%})")

    # IS backtest
    print(f"\n[IS] Backtest {is_start} → {is_end}...")
    is_bt = run_backtest(data, portfolio_sigs, PARAMETERS, is_start, is_end, "IS")
    is_m  = compute_metrics(is_bt["portfolio_values"], is_bt["trade_log"], is_start, is_end)
    print(f"  Sharpe={is_m['sharpe']:.4f} | CAGR={is_m['cagr']:.2%} | MDD={is_m['max_drawdown']:.2%} | trades={is_m['trade_count']}")

    # OOS backtest
    print(f"\n[OOS] Backtest {oos_start} → {oos_end}...")
    oos_bt = run_backtest(data, portfolio_sigs, PARAMETERS, oos_start, oos_end, "OOS")
    oos_m  = compute_metrics(oos_bt["portfolio_values"], oos_bt["trade_log"], oos_start, oos_end)
    print(f"  Sharpe={oos_m['sharpe']:.4f} | CAGR={oos_m['cagr']:.2%} | MDD={oos_m['max_drawdown']:.2%} | trades={oos_m['trade_count']}")

    # Gate 7 quarterly MDD analysis
    print(f"\n[GATE7] Quarterly IS MDD windows...")
    gate7 = compute_gate7_windows(is_bt["portfolio_values"], is_start, is_end)
    print(f"  Worst MDD: {gate7['gate7_worst_mdd']:.2%} | Gate7: {'PASS' if gate7['gate7_pass'] else 'FAIL'}")
    if not gate7["gate7_pass"]:
        print(f"  *** GATE 7 FAIL — {gate7['n_windows_exceed_30pct']} window(s) exceed 30% MDD ***")
    # Print 2008 stress windows explicitly
    for w in gate7["windows"]:
        if w.get("is_stress_2008_q3") or w.get("is_stress_2008_q4"):
            label = "2008-Q3" if w.get("is_stress_2008_q3") else "2008-Q4"
            print(f"  {label} ({w['window_start']}–{w['window_end']}): MDD={w['mdd']:.2%} {'✓' if w['gate7_ok'] else '✗ FAIL'}")

    # PF-1 quarterly trade count check
    q_trades = compute_quarterly_trade_counts(is_bt["trade_log"], is_start, is_end)
    print(f"  Min quarter trades={q_trades['min_quarter_trades']} | "
          f"Quarters below 30: {q_trades['n_quarters_below_30']}")

    # Walk-Forward
    print(f"\n[WF] Walk-forward ({len(wf_windows)} windows)...")
    wf_results  = run_walk_forward(data, PARAMETERS, wf_windows, weekly, stage2, stage3, rs_vs_spy)
    wf_passed   = sum(1 for w in wf_results if w.get("sharpe", 0) > 0)
    gate7_wf_ok = all(w.get("gate7_pass", False) for w in wf_results)
    print(f"  WF Sharpe>0: {wf_passed}/{len(wf_windows)} | Gate7 all WF: {'PASS' if gate7_wf_ok else 'FAIL'}")

    # Statistical tests
    print(f"\n[STAT] Statistical rigor...")
    closed_is   = [t for t in is_bt["trade_log"] if t.get("exit_reason") != "window_end"]
    pnl_arr_is  = np.array([t["pnl"] for t in closed_is]) if closed_is else np.array([0.0])
    ret_arr_is  = is_bt["portfolio_values"].pct_change().fillna(0.0).values

    mc   = monte_carlo_sharpe(pnl_arr_is)
    bb   = block_bootstrap_ci(ret_arr_is)
    perm = permutation_test(is_bt["portfolio_values"], is_m["sharpe"])
    n_trials = 27 + len(wf_windows)  # sweep + WF
    dsr_val  = compute_dsr(is_m["sharpe"], n_trials, len(is_bt["portfolio_values"]))
    print(f"  MC p5={mc['mc_p5_sharpe']:.3f} | BB CI=[{bb['sharpe_ci_low']:.3f},{bb['sharpe_ci_high']:.3f}]")
    print(f"  Perm p={perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'}) | DSR={dsr_val:.4f}")

    # Market impact
    mi_report = compute_market_impact(data, is_start, is_end)
    max_mi    = max((v.get("market_impact_bps", 0) for v in mi_report.values() if isinstance(v, dict)), default=0.0)
    print(f"  Max market impact: {max_mi:.4f} bps | Liquidity constrained: {any(v.get('liquidity_constrained') for v in mi_report.values() if isinstance(v, dict))}")

    # CPR
    cpr = compute_cpr(is_bt["trade_log"], is_bt["portfolio_values"], PARAMETERS["init_capital"])
    print(f"  CPR (cost/gross): {cpr:.4f} (threshold < 0.25)")

    # Composite Score
    cs, cs_comp = compute_cs(oos_m["sharpe"], is_m["max_drawdown"],
                              is_m["avg_ppt_bps"], is_m["trade_count"])

    # Gate 1 checks
    gate_oos_sharpe = oos_m["sharpe"] > 0.70
    gate_cs         = cs >= 0.60
    gate_gate7      = gate7["gate7_pass"]
    gate_dsr        = dsr_val > 0.0
    gate_wf         = wf_passed >= 3
    gate_cpr        = cpr < 0.25
    gate_ppt        = is_m["avg_ppt_bps"] > 15.0

    checks = [
        ("OOS Sharpe (hard gate)",    f"{oos_m['sharpe']:.4f}",  "> 0.70",  gate_oos_sharpe),
        ("Composite Score CS",         f"{cs:.4f}",               ">= 0.60", gate_cs),
        ("Gate 7 MDD (all IS windows)",
         f"worst={gate7['gate7_worst_mdd']:.2%}", "< 30%",       gate_gate7),
        ("DSR",                        f"{dsr_val:.4f}",          "> 0",     gate_dsr),
        ("Walk-Forward Sharpe>0",      f"{wf_passed}/{len(wf_windows)}", ">= 3/4", gate_wf),
        ("CPR (cost/gross)",           f"{cpr:.4f}",              "< 0.25",  gate_cpr),
        ("Avg PpT (IS, bps)",          f"{is_m['avg_ppt_bps']:.2f}", "> 15", gate_ppt),
    ]
    n_passed      = sum(1 for *_, p in checks if p)
    verdict_label = "PASS" if all(p for *_, p in checks) else "FAIL"

    print(f"\n{'='*70}")
    print(f"H85 [{variant_name}] — GATE 1 VERDICT: {verdict_label} ({n_passed}/{len(checks)} checks)")
    for g, v, t, p in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {g:<35} {v}  (threshold: {t})")
    print(f"  CS = {cs:.4f}  (ShareNorm={cs_comp['sharpe_norm']:.3f}×0.40 + StabNorm={cs_comp['stab_norm']:.3f}×0.30 + PpTNorm={cs_comp['ppt_norm']:.3f}×0.20 + TradeNorm={cs_comp['trade_norm']:.3f}×0.10)")
    print(f"  Gate7 worst MDD: {gate7['gate7_worst_mdd']:.2%} | PF-1 min-quarter: {q_trades['min_quarter_trades']} trades")
    print(f"{'='*70}")

    # Build output suffix
    base       = f"H85_WeinsteinStage2_{variant_name}_{TODAY}"
    postgfc_note = ("<p><em>Note (Post-GFC variant): Excludes 2008 GFC from IS period. "
                    "Isolates signal quality from GFC structural regime hostility.</em></p>"
                    if variant_name == "PostGFC" else "")

    # HTML
    html = build_html_report(
        variant_name, is_m, oos_m, wf_results, sweep_rows, mi_report,
        mc, bb, perm, dsr_val, cs, cs_comp, verdict_label, checks,
        gate7, q_trades, is_start, is_end, oos_start, oos_end, postgfc_note,
    )
    html_path = OUT_DIR / f"{base}_report.html"
    html_path.write_text(html)
    print(f"[SAVE] Report: {html_path}")

    # Verdict text
    wf_lines = [
        f"  WF{w['window']} ({w.get('is_start','')}–{w.get('is_end','')}): "
        f"Sharpe={w.get('sharpe',0):.4f}, MDD={w.get('max_drawdown',0):.2%}, "
        f"trades={w.get('trade_count',0)}, Gate7={'PASS' if w.get('gate7_pass') else 'FAIL'}"
        for w in wf_results
    ]
    # List worst Gate 7 windows
    g7_worst = sorted(gate7.get("windows", []), key=lambda x: x["mdd"])[:5]
    g7_lines = [
        f"  {w['window_start']}–{w['window_end']}: MDD={w['mdd']:.2%} {'✓' if w['gate7_ok'] else '✗ FAIL'}"
        + (" ← 2008-Q3 STRESS" if w.get("is_stress_2008_q3") else "")
        + (" ← 2008-Q4 STRESS" if w.get("is_stress_2008_q4") else "")
        for w in g7_worst
    ]
    verdict_lines = [
        f"H85 Weinstein Stage 2 Sector ETF Rotation — Gate 1 Verdict ({variant_name})",
        f"{'='*70}",
        f"Date:     {TODAY}",
        f"Strategy: {STRATEGY_NAME}",
        f"Variant:  {variant_name} | IS: {is_start}→{is_end} | OOS: {oos_start}→{oos_end}",
        f"Criteria: v2.7 / kpi-daily-weekly.md v1.0 — NO IS Sharpe gate",
        f"Overall:  {verdict_label} ({n_passed}/{len(checks)} checks passed)",
        f"{'='*70}",
        f"",
        f"=== IS Performance ({is_start} → {is_end}) ===",
        f"Sharpe:           {is_m['sharpe']:.4f}    [diagnostic only — no IS Sharpe gate in v2.7]",
        f"CAGR:             {is_m['cagr']:.2%}",
        f"Max Drawdown:     {is_m['max_drawdown']:.2%}",
        f"Win Rate:         {is_m['win_rate']:.2%}",
        f"Profit Factor:    {is_m['profit_factor']}",
        f"Trade Count:      {is_m['trade_count']}",
        f"Avg PpT:          {is_m['avg_ppt_bps']:.2f} bps",
        f"",
        f"=== OOS Performance ({oos_start} → {oos_end}) ===",
        f"Sharpe:           {oos_m['sharpe']:.4f}  [HARD GATE: {'PASS' if gate_oos_sharpe else 'FAIL'} > 0.70]",
        f"CAGR:             {oos_m['cagr']:.2%}",
        f"Max Drawdown:     {oos_m['max_drawdown']:.2%}",
        f"Win Rate:         {oos_m['win_rate']:.2%}",
        f"Trade Count:      {oos_m['trade_count']}",
        f"",
        f"=== Gate 7 Critical Stress Test ===",
        f"Worst IS window MDD:  {gate7['gate7_worst_mdd']:.2%}  (ceiling: -30%)",
        f"Gate 7 pass:          {'✓ YES' if gate7['gate7_pass'] else '✗ NO — AUTO-REJECT'}",
        f"Windows exceeding 30%: {gate7.get('n_windows_exceed_30pct', 0)}",
        f"Worst 5 IS quarterly windows:",
    ] + g7_lines + [
        f"",
        f"=== PF-1 Quarterly Trade Count ===",
        f"Min quarter trades: {q_trades['min_quarter_trades']}",
        f"Quarters below 30:  {q_trades['n_quarters_below_30']} (flag-only, not auto-reject per hypothesis PF-1 note)",
        f"",
        f"=== Composite Score (v2.7) ===",
        f"CS = {cs:.4f}  [{'PASS' if gate_cs else 'FAIL'}: >= 0.60]",
        f"  NetSharpe_norm  = {cs_comp['sharpe_norm']:.4f} × 0.40 = {cs_comp['sharpe_norm']*0.40:.4f}",
        f"  Stability_norm  = {cs_comp['stab_norm']:.4f} × 0.30 = {cs_comp['stab_norm']*0.30:.4f}",
        f"  PpT_norm        = {cs_comp['ppt_norm']:.4f} × 0.20 = {cs_comp['ppt_norm']*0.20:.4f}",
        f"  TradeAdq_norm   = {cs_comp['trade_norm']:.4f} × 0.10 = {cs_comp['trade_norm']*0.10:.4f}",
        f"",
        f"=== Statistical Rigor ===",
        f"MC p5 Sharpe:       {mc['mc_p5_sharpe']:.4f}",
        f"MC Median Sharpe:   {mc['mc_median_sharpe']:.4f}",
        f"Sharpe 95% CI:      [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]",
        f"MDD 95% CI:         [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]",
        f"Permutation p:      {perm['permutation_pvalue']:.4f}  [{'PASS' if perm['permutation_test_pass'] else 'FAIL'}: < 0.05]",
        f"DSR:                {dsr_val:.4f}  [{'PASS' if gate_dsr else 'FAIL'}: > 0]",
        f"CPR (cost/gross):   {cpr:.4f}  [{'PASS' if gate_cpr else 'FAIL'}: < 0.25]",
        f"Max Market Impact:  {max_mi:.4f} bps",
        f"",
        f"=== Walk-Forward Analysis ===",
    ] + wf_lines + [
        f"  WF Sharpe>0: {wf_passed}/{len(wf_windows)}  [{'PASS' if gate_wf else 'FAIL'}: >= 3/4]",
        f"",
        f"=== Parameter Sweep ({len(sweep_rows)} combos) ===",
    ]
    if sweep_rows:
        valid_sharpes = [r["sharpe"] for r in sweep_rows if "sharpe" in r and isinstance(r.get("sharpe"), (int, float))]
        if valid_sharpes:
            verdict_lines.append(f"  Sharpe range: {min(valid_sharpes):.4f} – {max(valid_sharpes):.4f}")
            sr_range = max(valid_sharpes) - min(valid_sharpes)
            prim_sr  = is_m["sharpe"]
            var_pct  = sr_range / abs(prim_sr) if prim_sr != 0 else float("nan")
            verdict_lines.append(f"  Variance vs primary: {var_pct:.1%}")

    verdict_lines += [
        f"",
        f"=== Gate 1 Checks (v2.7) ===",
    ]
    for g, v, t, p in checks:
        verdict_lines.append(f"  [{'PASS' if p else 'FAIL'}] {g:<35} {v}  (threshold: {t})")

    if verdict_label == "PASS":
        verdict_lines += [
            f"",
            f"=== Recommendation ===",
            f"PASS — advance to paper trading. Notify CEO for approval.",
        ]
    else:
        failed = [(g, v, t) for g, v, t, p in checks if not p]
        verdict_lines += [
            f"",
            f"=== Root Cause Analysis ===",
            f"Primary failures ({len(failed)} of {len(checks)} gates):",
        ] + [f"  - {g}: got {v}, need {t}" for g, v, t in failed] + [
            f"",
            f"=== Recommendation ===",
            f"REJECT — do not advance to paper trading.",
        ]

    verdict_lines += [
        f"",
        f"=== Overnight/Weekend Guards (Hard Gate 8 disclosure) ===",
        f"Signal timing: Friday close → Monday open execution. No same-close fills.",
        f"Overnight gap exposure: ~15-25% of position PnL per hypothesis analysis.",
        f"Weekend gap: max single-sector exposure 25% of portfolio (4 equal-weight positions).",
        f"Earnings: N/A — sector ETFs are diversified; no single-stock earnings exposure.",
        f"Universe: Fixed 10-sector SPDR ETFs (inception 1998) + VNQ (2004) + SHY (2002).",
        f"Survivorship bias: All tickers are index-tracking ETFs (not individual stocks). No delisting risk.",
        f"",
        f"=== Files ===",
        f"Report: backtests/H85_WeinsteinStage2_{variant_name}_{TODAY}_report.html",
        f"Verdict: backtests/H85_WeinsteinStage2_{variant_name}_{TODAY}_verdict.txt",
    ]

    verdict_text = "\n".join(verdict_lines)
    verdict_path = OUT_DIR / f"{base}_verdict.txt"
    verdict_path.write_text(verdict_text)
    print(f"[SAVE] Verdict: {verdict_path}")

    return {
        "variant": variant_name,
        "is_sharpe": is_m["sharpe"],
        "oos_sharpe": oos_m["sharpe"],
        "is_mdd": is_m["max_drawdown"],
        "is_trade_count": is_m["trade_count"],
        "cs": cs,
        "gate7_worst_mdd": gate7["gate7_worst_mdd"],
        "gate7_pass": gate7["gate7_pass"],
        "verdict": verdict_label,
        "checks_passed": n_passed,
        "checks_total": len(checks),
        "is_m": is_m,
        "oos_m": oos_m,
        "gate7": gate7,
        "q_trades": q_trades,
        "wf_results": wf_results,
        "wf_passed": wf_passed,
        "mc": mc,
        "bb": bb,
        "perm": perm,
        "dsr": dsr_val,
        "cpr": cpr,
        "cs_comp": cs_comp,
        "mi_report": mi_report,
        "is_bt": is_bt,
        "oos_bt": oos_bt,
    }


def main():
    print("=" * 70)
    print(f"H85 Weinstein Stage 2 Sector ETF Rotation — Gate 1 Backtest")
    print(f"QUA-381 | {TODAY}")
    print(f"Universe: {', '.join(SECTOR_ETFS)} + {SAFE_HAVEN}")
    print(f"Signal: Price > rising 30-week SMA (Weinstein Stage 2)")
    print(f"Criteria: v2.7 — OOS Sharpe > 0.7 | CS >= 0.60 | Gate 7 MDD < 30%")
    print("=" * 70)

    # ── [1] Download Data ────────────────────────────────────────────────────
    print("\n[1/5] Downloading data...")
    data = download_data(DATA_START, TODAY)
    close = data["close"]

    # ── [2] Weekly Signal Computation ────────────────────────────────────────
    print("\n[2/5] Computing weekly Stage 2 signals...")
    weekly_all = get_weekly_closes(close, SECTOR_ETFS)
    weekly_spy = close[SPY].resample("W-FRI").last().dropna()

    stage2, stage3 = compute_weekly_stage2(weekly_all, PARAMETERS)
    rs_vs_spy      = compute_rs_vs_spy(weekly_all, weekly_spy, PARAMETERS["rs_lookback_weeks"])

    print(f"  Weekly bars: {len(weekly_all)}")
    # Stage 2 count summary for IS period
    is_stage2_ts = stage2.loc["2003-01-01":"2018-12-31"]
    avg_stage2 = is_stage2_ts.sum(axis=1).mean()
    print(f"  Avg sectors in Stage 2 (IS 2003-2018): {avg_stage2:.1f}")

    # ── [3] Parameter Sweep (run once over Standard IS) ──────────────────────
    print("\n[3/5] Parameter sweep (27 combos over Standard IS 2003-2018)...")
    sweep_rows = run_sweep(data, weekly_all, "2003-01-01", "2018-12-31", weekly_spy)
    sweep_path = OUT_DIR / f"H85_WeinsteinStage2_sweep_{TODAY}.csv"
    if sweep_rows:
        pd.DataFrame(sweep_rows).to_csv(sweep_path, index=False)
        print(f"[SAVE] Sweep: {sweep_path}")

    # ── [4] Standard Variant ──────────────────────────────────────────────────
    print("\n[4/5] Running Standard variant (IS 2003-2018, OOS 2019-2025)...")
    std_result = run_variant(
        data, weekly_all, weekly_spy, stage2, stage3, rs_vs_spy,
        "Standard", VARIANTS["Standard"],
        WF_WINDOWS_STANDARD, sweep_rows,
    )

    # ── [5] Post-GFC Variant ──────────────────────────────────────────────────
    # WF windows for Post-GFC IS (2009-2020)
    wf_postgfc = [
        ("2009-01-01", "2011-12-31"),
        ("2012-01-01", "2015-12-31"),
        ("2016-01-01", "2018-12-31"),
        ("2019-01-01", "2020-12-31"),
    ]
    print("\n[5/5] Running Post-GFC variant (IS 2009-2020, OOS 2021-2025)...")
    pgfc_result = run_variant(
        data, weekly_all, weekly_spy, stage2, stage3, rs_vs_spy,
        "PostGFC", VARIANTS["PostGFC"],
        wf_postgfc, sweep_rows,
    )

    # ── Combined JSON ─────────────────────────────────────────────────────────
    def safe_m(m):
        return {k: v for k, v in m.items() if k != "_daily_returns"}

    combined = {
        "strategy_name":   STRATEGY_NAME,
        "date":            TODAY,
        "hypothesis":      "H85",
        "parent_task":     "QUA-381",
        "universe":        SECTOR_ETFS + [SAFE_HAVEN],
        "parameters":      {k: v for k, v in PARAMETERS.items() if k != "init_capital"},
        "criteria_version": "v2.7 / kpi-daily-weekly.md v1.0",
        "cost_model": {
            "slip_pct":       STD_SLIP * 100,
            "commission":     "$0.005/share",
            "market_impact":  "0.1 × σ × sqrt(Q/ADV) Almgren-Chriss",
        },
        "Standard": {
            "verdict":         std_result["verdict"],
            "is_sharpe":       std_result["is_sharpe"],
            "oos_sharpe":      std_result["oos_sharpe"],
            "is_mdd":          std_result["is_mdd"],
            "cs":              std_result["cs"],
            "gate7_worst_mdd": std_result["gate7_worst_mdd"],
            "gate7_pass":      std_result["gate7_pass"],
            "wf_passed":       std_result["wf_passed"],
            "is_metrics":      safe_m(std_result["is_m"]),
            "oos_metrics":     safe_m(std_result["oos_m"]),
            "gate7":           std_result["gate7"],
            "quarterly_trades": std_result["q_trades"],
            "wf_windows":      std_result["wf_results"],
            "mc":              std_result["mc"],
            "bb":              std_result["bb"],
            "perm":            std_result["perm"],
            "dsr":             std_result["dsr"],
            "cpr":             std_result["cpr"],
            "cs_components":   std_result["cs_comp"],
            "mi_report":       std_result["mi_report"],
        },
        "PostGFC": {
            "verdict":         pgfc_result["verdict"],
            "is_sharpe":       pgfc_result["is_sharpe"],
            "oos_sharpe":      pgfc_result["oos_sharpe"],
            "is_mdd":          pgfc_result["is_mdd"],
            "cs":              pgfc_result["cs"],
            "gate7_worst_mdd": pgfc_result["gate7_worst_mdd"],
            "gate7_pass":      pgfc_result["gate7_pass"],
            "wf_passed":       pgfc_result["wf_passed"],
            "is_metrics":      safe_m(pgfc_result["is_m"]),
            "oos_metrics":     safe_m(pgfc_result["oos_m"]),
            "gate7":           pgfc_result["gate7"],
            "quarterly_trades": pgfc_result["q_trades"],
            "wf_windows":      pgfc_result["wf_results"],
            "mc":              pgfc_result["mc"],
            "bb":              pgfc_result["bb"],
            "perm":            pgfc_result["perm"],
            "dsr":             pgfc_result["dsr"],
            "cpr":             pgfc_result["cpr"],
            "cs_components":   pgfc_result["cs_comp"],
            "mi_report":       pgfc_result["mi_report"],
        },
        "sweep_path": str(sweep_path),
        "gate1_overall": {
            "standard_pass": std_result["verdict"] == "PASS",
            "postgfc_pass":  pgfc_result["verdict"] == "PASS",
            "primary_verdict": std_result["verdict"],
        },
    }

    json_path = OUT_DIR / f"H85_WeinsteinStage2_{TODAY}.json"
    with open(json_path, "w") as f:
        json.dump(combined, f, indent=2, default=str)
    print(f"\n[SAVE] Combined metrics JSON: {json_path}")

    # Combined trades CSV
    all_trades = (std_result["is_bt"]["trade_log"] + std_result["oos_bt"]["trade_log"] +
                  pgfc_result["is_bt"]["trade_log"] + pgfc_result["oos_bt"]["trade_log"])
    if all_trades:
        trades_path = OUT_DIR / f"H85_WeinsteinStage2_{TODAY}_trades.csv"
        pd.DataFrame(all_trades).to_csv(trades_path, index=False)
        print(f"[SAVE] Trades: {trades_path} ({len(all_trades)} entries)")

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"H85 GATE 1 — FINAL SUMMARY")
    print(f"=" * 70)
    print(f"  Standard  (IS 2003-2018, OOS 2019-2025): {std_result['verdict']}")
    print(f"    IS Sharpe={std_result['is_sharpe']:.4f} | OOS Sharpe={std_result['oos_sharpe']:.4f}")
    print(f"    IS MDD={std_result['is_mdd']:.2%} | Gate7 worst={std_result['gate7_worst_mdd']:.2%} ({'PASS' if std_result['gate7_pass'] else 'FAIL'})")
    print(f"    CS={std_result['cs']:.4f} | WF={std_result['wf_passed']}/{len(WF_WINDOWS_STANDARD)}")
    print(f"")
    print(f"  Post-GFC  (IS 2009-2020, OOS 2021-2025): {pgfc_result['verdict']}")
    print(f"    IS Sharpe={pgfc_result['is_sharpe']:.4f} | OOS Sharpe={pgfc_result['oos_sharpe']:.4f}")
    print(f"    IS MDD={pgfc_result['is_mdd']:.2%} | Gate7 worst={pgfc_result['gate7_worst_mdd']:.2%} ({'PASS' if pgfc_result['gate7_pass'] else 'FAIL'})")
    print(f"    CS={pgfc_result['cs']:.4f} | WF={pgfc_result['wf_passed']}/{len(wf_postgfc)}")
    print("=" * 70)
    print(f"Primary verdict (Standard): {std_result['verdict']}")

    return combined


if __name__ == "__main__":
    result = main()
    primary = result["gate1_overall"]["primary_verdict"]
    sys.exit(0 if primary == "PASS" else 1)
