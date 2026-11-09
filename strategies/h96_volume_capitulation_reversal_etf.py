"""
Strategy: H96 Volume Capitulation Reversal on Liquid ETFs
Author: Strategy Coder Agent
Date: 2026-11-09
Hypothesis: A close-to-close drop larger than 1.5 ATR(14) on volume above 2x its 20-day average marks
            forced, liquidity-driven selling in a liquid ETF. The next 1-5 days rebound as liquidity
            providers are paid.
Asset class: equities (ETFs)
Parent task: QUA-913 (parent QUA-911)
References: Cooper (1999) RFS; Lee and Swaminathan (2000) JF;
            research/hypotheses/96_qc_volume_capitulation_reversal_etf.md

Trade rules (long-only, daily bars):
  Entry at Close of the signal day.
  Exit at the first Close above the prior Close, or the Close of day max_hold_days, or the first Close
  below the capitulation-day Low (hard stop), whichever comes first.
Position sizing: size_frac of equity per signal, at most max_positions concurrent.
Trend gate modes: none | spy_sma | own_sma | either (own OR SPY above SMA(200)).
"""

import logging
import math
import warnings

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# All tunable parameters exposed here for sensitivity scanning
PARAMETERS = {
    "universe": ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "XLY", "XLP"],
    "atr_window": 14,            # ATR lookback (test range 10-20)
    "drop_atr_mult": 1.5,        # drop must exceed mult * ATR / Close (test range 1.0-2.5)
    "vol_mult": 2.0,             # volume must exceed mult * average volume (test range 1.5-3.0)
    "vol_avg_window": 20,        # baseline volume window, includes signal day (test range 10-30)
    "sma_window": 200,           # trend gate SMA window
    "trend_gate": "spy_sma",     # none | spy_sma | own_sma | either
    "max_hold_days": 5,          # time stop in trading days (test range 3-7)
    "size_frac": 0.20,           # fraction of equity per signal
    "max_positions": 4,          # concurrent positions
    "spy_pause_signals": 3,      # pause entries when SPY raw signals in last 5 days >= this (0 disables)
    "vix_pause": 40.0,           # pause entries when VIX close > this (None disables)
    "init_cash": 100000.0,
}

# ── Transaction cost constants (Engineering Director AGENTS.md, ED-SLIP-001) ───
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_ULTRA_LIQUID = 0.00005      # 0.005%: SPY, QQQ, IWM
SLIPPAGE_STANDARD = 0.0005           # 0.05%: all other ETFs
ULTRA_LIQUID = ("SPY", "QQQ", "IWM")
MARKET_IMPACT_K = 0.1
SIGMA_WINDOW = 20
ADV_WINDOW = 20
LIQUIDITY_FLAG_RATIO = 0.01          # flag Q/ADV above 1%
TRADING_DAYS_PER_YEAR = 252
VALID_GATES = ("none", "spy_sma", "own_sma", "either")
REQUIRED_COLS = ("Open", "High", "Low", "Close", "Volume")


# ── Data ──────────────────────────────────────────────────────────────────────

def download_data(tickers: list, start: str, end: str) -> dict:
    """
    Download split/dividend-adjusted daily OHLCV (yfinance auto_adjust=True) per ticker.

    Returns dict ticker -> DataFrame with REQUIRED_COLS. Raises ValueError if a ticker is empty.
    """
    import yfinance as yf

    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False, group_by="ticker")
    out = {}
    for t in tickers:
        if t not in raw.columns.get_level_values(0):
            raise ValueError(f"yfinance returned no data for {t}")
        df = raw[t].dropna(subset=["Close"])
        out[t] = validate_ohlcv(df, t)
    return out


def download_vix(start: str, end: str) -> pd.Series:
    """Download VIX daily close (^VIX)."""
    import yfinance as yf

    raw = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    if close.empty:
        raise ValueError("yfinance returned no VIX data")
    return close


def validate_ohlcv(df: pd.DataFrame, ticker: str = "") -> pd.DataFrame:
    """Check columns, ordering and basic sanity. Returns the frame restricted to REQUIRED_COLS."""
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{ticker}: missing columns {missing}")
    df = df[list(REQUIRED_COLS)].copy()
    if df.empty:
        raise ValueError(f"{ticker}: empty frame")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError(f"{ticker}: index must be strictly increasing")
    if (df["Close"] <= 0).any():
        raise ValueError(f"{ticker}: non-positive Close")
    return df


def data_quality_report(data: dict, gap_days: int = 5) -> dict:
    """Per-ticker coverage, calendar gaps longer than gap_days, and zero-volume bar counts."""
    rep = {}
    for t, df in data.items():
        gaps = df.index.to_series().diff().dt.days
        big = gaps[gaps > gap_days]
        rep[t] = {
            "first_date": str(df.index[0].date()),
            "last_date": str(df.index[-1].date()),
            "rows": int(len(df)),
            "gaps_gt_days": [[str(d.date()), int(g)] for d, g in big.items()],
            "zero_volume_bars": int((df["Volume"] <= 0).sum()),
            "nan_ohlc_bars": int(df[["Open", "High", "Low", "Close"]].isna().any(axis=1).sum()),
        }
    return rep


# ── Signals ───────────────────────────────────────────────────────────────────

def _indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """ATR, 1-day return, volume ratio, rolling sigma and ADV for one ETF. Uses only data up to each bar."""
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    out = pd.DataFrame(index=df.index)
    out["atr"] = tr.rolling(params["atr_window"]).mean()
    out["ret"] = df["Close"].pct_change()
    out["volx"] = df["Volume"] / df["Volume"].rolling(params["vol_avg_window"]).mean()
    out["sigma"] = out["ret"].rolling(SIGMA_WINDOW).std()
    out["adv"] = df["Volume"].rolling(ADV_WINDOW).mean()
    out["sma"] = df["Close"].rolling(params["sma_window"]).mean()
    # Drop size in ATR units; larger means a deeper capitulation. Used to rank competing signals.
    out["strength"] = -out["ret"] * df["Close"] / out["atr"]
    out["raw"] = (out["ret"] < -params["drop_atr_mult"] * out["atr"] / df["Close"]) & (out["volx"] > params["vol_mult"])
    return out


def generate_signals(data: dict, params: dict = PARAMETERS, vix: pd.Series = None) -> dict:
    """
    Build per-ticker signal frames.

    Returns dict ticker -> DataFrame with columns raw, gated, strength, sigma, adv. `gated` is the entry
    signal after the trend gate and the SPY cluster / VIX pause. Requires SPY in data.
    """
    gate = params["trend_gate"]
    if gate not in VALID_GATES:
        raise ValueError(f"trend_gate must be one of {VALID_GATES}, got {gate!r}")
    if "SPY" not in data:
        raise ValueError("SPY must be in data (trend gate and pause rules reference it)")

    ind = {t: _indicators(df, params) for t, df in data.items()}
    spy_close = data["SPY"]["Close"]
    spy_up = spy_close > ind["SPY"]["sma"]

    # Pause rules from the hypothesis: 3 SPY signals in 5 days, or VIX above threshold.
    pause = pd.Series(False, index=spy_close.index)
    if params.get("spy_pause_signals"):
        pause |= ind["SPY"]["raw"].astype(int).rolling(5, min_periods=1).sum() >= params["spy_pause_signals"]
    if params.get("vix_pause") is not None and vix is not None:
        pause |= (vix.reindex(spy_close.index) > params["vix_pause"]).fillna(False)

    out = {}
    for t, df in data.items():
        i = ind[t]
        own_up = df["Close"] > i["sma"]
        spy_ok = spy_up.reindex(df.index).fillna(False)
        if gate == "none":
            g = pd.Series(True, index=df.index)
        elif gate == "spy_sma":
            g = spy_ok
        elif gate == "own_sma":
            g = own_up
        else:
            g = own_up | spy_ok
        p = pause.reindex(df.index).fillna(False)
        res = pd.DataFrame(index=df.index)
        res["raw"] = i["raw"].fillna(False)
        res["gated"] = res["raw"] & g.fillna(False) & ~p
        res["strength"] = i["strength"]
        res["sigma"] = i["sigma"]
        res["adv"] = i["adv"]
        out[t] = res
    return out


def count_signal_days(signals: dict, start: str, end: str) -> dict:
    """Event counts and distinct signal days (cross-ETF clustering) in [start, end], plus per-year counts."""
    days = []
    for t, s in signals.items():
        ix = s.index[s["gated"]]
        days += [d for d in ix if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    ser = pd.Series(days, dtype="datetime64[ns]")
    years = range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1)
    per_year = ser.dt.year.value_counts().reindex(years, fill_value=0).sort_index() if len(ser) else \
        pd.Series(0, index=years)
    return {
        "events": int(len(ser)),
        "distinct_days": int(ser.nunique()) if len(ser) else 0,
        "years_with_zero_events": [int(y) for y in per_year.index[per_year == 0]],
        "events_per_year": {int(y): int(n) for y, n in per_year.items()},
    }


# ── Simulation ────────────────────────────────────────────────────────────────

def _slippage(ticker: str) -> float:
    return SLIPPAGE_ULTRA_LIQUID if ticker in ULTRA_LIQUID else SLIPPAGE_STANDARD


def _impact(sigma: float, qty: float, adv: float) -> float:
    """Square-root market impact fraction: k * sigma * sqrt(Q / ADV). Zero if inputs are unavailable."""
    if not (np.isfinite(sigma) and np.isfinite(adv)) or adv <= 0:
        return 0.0
    return MARKET_IMPACT_K * sigma * math.sqrt(qty / adv)


def simulate(data: dict, signals: dict, params: dict, start: str, end: str) -> dict:
    """
    Run the portfolio simulation on [start, end]. Signals may be computed on a longer history (warmup).

    Entries and exits fill at the Close with slippage, fixed cost and sqrt impact on both sides. Open
    positions at the window end are closed at the last Close (reason window_end).

    Returns dict with equity (Series), returns (daily Series), trades (DataFrame), liquidity_flags (int).
    """
    dates = sorted(set().union(*[set(df.index) for df in data.values()]))
    dates = [d for d in dates if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    if not dates:
        raise ValueError(f"no bars in [{start}, {end}]")

    cash = float(params["init_cash"])
    open_pos = {}
    last_close = {}
    trades = []
    equity = {}
    liq_flags = 0

    def close_pos(t, px, dt, reason):
        nonlocal cash
        p = open_pos.pop(t)
        row = signals[t].loc[dt]
        imp = _impact(row["sigma"], p["shares"], row["adv"])
        net_px = px * (1 - _slippage(t) - imp)
        proceeds = p["shares"] * net_px - p["shares"] * FIXED_COST_PER_SHARE
        cash += proceeds
        net_pnl = proceeds - p["cost_basis"]
        trades.append({
            "ticker": t, "entry_date": p["entry_date"], "exit_date": dt, "entry_px": p["entry_px"],
            "exit_px": px, "shares": p["shares"], "net_pnl": net_pnl,
            "ret_net": net_pnl / p["cost_basis"], "hold_days": p["days"], "reason": reason,
            "liquidity_flag": p["liq"],
        })

    for n, dt in enumerate(dates):
        for t, df in data.items():
            if dt in df.index:
                last_close[t] = float(df.at[dt, "Close"])

        # 1. exits
        for t in list(open_pos):
            df = data[t]
            if dt not in df.index:
                continue
            p = open_pos[t]
            i = df.index.get_loc(dt)
            c, prev_c = float(df["Close"].iloc[i]), float(df["Close"].iloc[i - 1])
            p["days"] += 1
            if c < p["cap_low"]:
                close_pos(t, c, dt, "stop")
            elif c > prev_c:
                close_pos(t, c, dt, "target")
            elif p["days"] >= params["max_hold_days"]:
                close_pos(t, c, dt, "time")

        # 2. entries (rank by capitulation depth so slot allocation is deterministic)
        cands = [(float(signals[t].at[dt, "strength"]), t) for t in data
                 if dt in signals[t].index and bool(signals[t].at[dt, "gated"]) and t not in open_pos]
        cands.sort(key=lambda x: (-x[0], x[1]))
        mtm = cash + sum(p["shares"] * last_close[t] for t, p in open_pos.items())
        for _, t in cands:
            if len(open_pos) >= params["max_positions"]:
                break
            px = float(data[t].at[dt, "Close"])
            shares = math.floor(params["size_frac"] * mtm / px)
            if shares <= 0:
                continue
            row = signals[t].loc[dt]
            adv = row["adv"]
            liq = bool(np.isfinite(adv) and adv > 0 and shares / adv > LIQUIDITY_FLAG_RATIO)
            liq_flags += int(liq)
            imp = _impact(row["sigma"], shares, adv)
            cost_basis = shares * px * (1 + _slippage(t) + imp) + shares * FIXED_COST_PER_SHARE
            if cost_basis > cash:
                continue
            cash -= cost_basis
            open_pos[t] = {"entry_date": dt, "entry_px": px, "shares": shares, "cost_basis": cost_basis,
                           "cap_low": float(data[t].at[dt, "Low"]), "days": 0, "liq": liq}

        # 3. window end: flatten
        if n == len(dates) - 1:
            for t in list(open_pos):
                close_pos(t, last_close[t], dt, "window_end")

        equity[dt] = cash + sum(p["shares"] * last_close[t] for t, p in open_pos.items())

    eq = pd.Series(equity)
    rets = eq.pct_change().fillna(eq.iloc[0] / params["init_cash"] - 1)
    return {"equity": eq, "returns": rets, "trades": pd.DataFrame(trades), "liquidity_flags": liq_flags}


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(returns: pd.Series, trades: pd.DataFrame) -> dict:
    """Net Sharpe (daily, annualised sqrt(252)), MDD, total return, win rate, profit factor, trade count."""
    r = returns.dropna()
    sd = r.std()
    sharpe = float(r.mean() / sd * math.sqrt(TRADING_DAYS_PER_YEAR)) if sd and sd > 0 else 0.0
    eq = (1 + r).cumprod()
    mdd = float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0
    n = int(len(trades))
    if n:
        wins, losses = trades.loc[trades["net_pnl"] > 0, "net_pnl"], trades.loc[trades["net_pnl"] <= 0, "net_pnl"]
        win_rate = float((trades["net_pnl"] > 0).mean())
        pf = float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
        ppt_bps = float(trades["ret_net"].mean() * 1e4)
    else:
        win_rate, pf, ppt_bps = 0.0, 0.0, 0.0
    return {
        "sharpe": sharpe, "max_drawdown": mdd, "total_return": float(eq.iloc[-1] - 1) if len(eq) else 0.0,
        "win_rate": win_rate, "profit_factor": pf, "trade_count": n, "ppt_bps": ppt_bps,
        "bars": int(len(r)),
    }


def run_backtest(data: dict, params: dict, start: str, end: str, vix: pd.Series = None) -> dict:
    """Generate signals on the full history and simulate [start, end]. Returns simulate() output plus metrics."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sig = generate_signals(data, params, vix)
        res = simulate(data, sig, params, start, end)
    res["metrics"] = compute_metrics(res["returns"], res["trades"])
    res["signal_counts"] = count_signal_days(sig, start, end)
    return res


if __name__ == "__main__":
    d = download_data(PARAMETERS["universe"], "1999-01-01", "2024-12-31")
    out = run_backtest(d, PARAMETERS, "2000-01-01", "2019-12-31")
    print(out["metrics"], out["signal_counts"]["distinct_days"])
