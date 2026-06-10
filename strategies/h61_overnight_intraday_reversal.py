"""
Strategy: H61 Overnight Return Anomaly — Intraday-Reversal Selection Signal
Author: Engineering Director
Date: 2026-06-10
Hypothesis: Hold SPY overnight (close-to-open) only on days when intraday
            return (open-to-close) is negative AND SPY is above 200-DMA.
            Mechanism: Lou, Polk & Skouras (2019) "tug of war" — negative
            intraday return signals elevated institutional MOC demand that
            resolves as positive overnight return.
Asset class: equities (SPY ETF — ultra-liquid, ADV >> 50M shares/day)
Parent task: QUA-183
References:
  Lou, Polk & Skouras (2019). "A Tug of War." JFE 134(1), 192–213.
  Bogousslavsky (2021). "Cross-Section of Intraday and Overnight Returns." JFE 141(1).
  research/hypotheses/61_overnight_intraday_reversal.md
Slippage: ED-SLIP-001 — SPY ultra-liquid tier 0.005% (not standard 0.05%)
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "ticker": "SPY",
    "intraday_threshold": -0.002,   # Enter when intraday return < this (-0.2%); test range: -0.005 to 0.0
    "trend_ma_period": 200,         # 200-DMA regime filter; test range: 100–250
    "init_cash": 25000,
}

# ── IS/OOS Windows ─────────────────────────────────────────────────────────────
IS_START = "2018-01-01"
IS_END   = "2024-12-31"

# Walk-forward: 4 windows, IS 36mo / OOS 6mo, non-overlapping, within IS_START–IS_END
WF_WINDOWS = [
    {"window": 1, "is_start": "2018-01-01", "is_end": "2020-12-31", "oos_start": "2021-01-01", "oos_end": "2021-06-30"},
    {"window": 2, "is_start": "2018-07-01", "is_end": "2021-06-30", "oos_start": "2021-07-01", "oos_end": "2021-12-31"},
    {"window": 3, "is_start": "2019-01-01", "is_end": "2021-12-31", "oos_start": "2022-01-01", "oos_end": "2022-06-30"},
    {"window": 4, "is_start": "2019-07-01", "is_end": "2022-06-30", "oos_start": "2022-07-01", "oos_end": "2022-12-31"},
    {"window": 5, "is_start": "2020-01-01", "is_end": "2022-12-31", "oos_start": "2023-01-01", "oos_end": "2023-06-30"},
    {"window": 6, "is_start": "2020-07-01", "is_end": "2023-06-30", "oos_start": "2023-07-01", "oos_end": "2023-12-31"},
]

# ── Transaction Cost Constants (ED-SLIP-001: SPY ultra-liquid tier) ────────────
FIXED_COST_PER_SHARE = 0.005   # $0.005/share per leg
SLIPPAGE_PCT = 0.00005         # 0.005% per leg — ultra-liquid SPY (ADV >> 50M/day)
MARKET_IMPACT_K = 0.1          # Almgren-Chriss square-root model
SIGMA_WINDOW = 20              # rolling vol window for σ
ADV_WINDOW = 20                # rolling volume window for ADV
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data(ticker: str, start: str, end: str, trend_ma_period: int) -> pd.DataFrame:
    """
    Download SPY OHLCV with warmup for 200-DMA computation.
    Warmup = trend_ma_period * 1.5 + 30 calendar days.
    Uses auto_adjust=True for split/dividend-adjusted prices.
    """
    warmup_days = int(trend_ma_period * 1.5) + 30
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")

    raw = yf.download(ticker, start=warmup_start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns for {ticker}: {missing}")
    if len(raw) < trend_ma_period + 10:
        raise ValueError(f"Insufficient data for {ticker}: {len(raw)} bars (need {trend_ma_period + 10})")

    na_count = int(raw["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing Close values in download range")

    return raw


# ── Transaction Cost ───────────────────────────────────────────────────────────

def _transaction_cost_pct(
    entry_price: float,
    shares: int,
    sigma: float,
    adv: float,
) -> float:
    """
    Round-trip transaction cost as a fraction of entry price.
    Applied once per overnight round-trip (entry + exit).
    SPY ultra-liquid: slippage = 0.005% per leg per ED-SLIP-001.
    """
    # Fixed cost (both legs)
    fixed = 2.0 * FIXED_COST_PER_SHARE / (entry_price + 1e-10)
    # Slippage (both legs)
    slippage = 2.0 * SLIPPAGE_PCT
    # Market impact (both legs, square-root model)
    impact = 2.0 * MARKET_IMPACT_K * sigma * np.sqrt(max(shares, 1) / (adv + 1.0))
    return fixed + slippage + impact


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute entry signals on the full OHLCV DataFrame.

    Signal fires on day T when:
      1. intraday_return_T = (Close_T - Open_T) / Open_T < intraday_threshold
      2. Close_T > SMA(Close, trend_ma_period)_T  [200-DMA trend filter]

    Entry: Close of day T (MOC order)
    Exit:  Open of day T+1 (MOO order)

    All signals are computed without look-ahead: each day T signal uses only
    price data available at 4:00 PM ET on day T (no forward price access).
    """
    threshold = params["intraday_threshold"]
    trend_period = params["trend_ma_period"]

    out = df.copy()
    out["intraday_return"] = (out["Close"] - out["Open"]) / out["Open"]
    out["sma200"] = out["Close"].rolling(trend_period).mean()
    out["trend_filter"] = out["Close"] > out["sma200"]

    # Signal: negative intraday return AND above 200-DMA
    out["signal"] = (out["intraday_return"] < threshold) & out["trend_filter"]

    # Entry price = Close of signal day; Exit price = Open of next day
    # shift(-1) on Open gives next-day open — valid because we fill at MOO next morning
    out["entry_price"] = out["Close"]
    out["exit_price"] = out["Open"].shift(-1)

    # Rolling 20-day vol and ADV for market impact
    out["sigma"] = out["Close"].pct_change().rolling(SIGMA_WINDOW).std()
    out["adv"] = out["Volume"].rolling(ADV_WINDOW).mean()

    return out


# ── Strategy Simulation ────────────────────────────────────────────────────────

def run_strategy(
    df: pd.DataFrame,
    params: dict,
    start: str,
    end: str,
) -> dict:
    """
    Simulate H61 overnight holds on SPY from start to end (inclusive).

    Returns dict with:
      - trade_log: list of per-trade dicts
      - daily_returns: pd.Series of daily portfolio returns (overnight trade days have
        the overnight return; all other days are 0)
      - summary: dict of aggregate metrics
    """
    data = compute_signals(df, params)

    # Restrict to the simulation window
    mask = (data.index >= pd.Timestamp(start)) & (data.index <= pd.Timestamp(end))
    window = data[mask].copy()

    init_cash = params.get("init_cash", 25000)
    trade_log = []
    daily_returns = pd.Series(0.0, index=window.index)

    for i, (date, row) in enumerate(window.iterrows()):
        if not row["signal"]:
            continue
        if pd.isna(row["exit_price"]):
            # Last bar in window — no next open available
            continue
        if pd.isna(row["entry_price"]) or row["entry_price"] <= 0:
            continue

        entry = float(row["entry_price"])
        exit_p = float(row["exit_price"])
        sigma = float(row["sigma"]) if not pd.isna(row["sigma"]) else 0.01
        adv = float(row["adv"]) if not pd.isna(row["adv"]) else 200_000_000.0

        shares = max(1, int(init_cash / entry))
        liquidity_flag = bool(shares > 0.01 * adv)

        gross_return = (exit_p - entry) / entry
        cost_pct = _transaction_cost_pct(entry, shares, sigma, adv)
        net_return = gross_return - cost_pct

        daily_returns[date] = net_return

        trade_log.append({
            "date": str(date.date()),
            "entry_price": round(entry, 4),
            "exit_price": round(exit_p, 4),
            "shares": shares,
            "gross_return_pct": round(gross_return * 100, 4),
            "cost_pct": round(cost_pct * 100, 4),
            "net_return_pct": round(net_return * 100, 4),
            "intraday_return_pct": round(float(row["intraday_return"]) * 100, 4),
            "sma200": round(float(row["sma200"]), 2),
            "sigma": round(sigma, 6),
            "adv_shares": int(adv),
            "liquidity_constrained": liquidity_flag,
        })

    summary = _compute_summary(daily_returns, trade_log)
    return {
        "trade_log": trade_log,
        "daily_returns": daily_returns,
        "summary": summary,
    }


# ── Metrics Computation ────────────────────────────────────────────────────────

def _compute_summary(daily_returns: pd.Series, trade_log: list) -> dict:
    """Compute Gate 1 metrics from daily return series and trade log."""
    rets = daily_returns.dropna()
    trade_returns = np.array([t["net_return_pct"] / 100.0 for t in trade_log]) if trade_log else np.array([])

    n_trades = len(trade_log)
    win_rate = float(np.mean(trade_returns > 0)) if n_trades > 0 else 0.0

    gains = trade_returns[trade_returns > 0]
    losses = trade_returns[trade_returns < 0]
    profit_factor = (
        float(np.sum(gains) / (-np.sum(losses))) if len(losses) > 0 and np.sum(losses) != 0 else np.inf
    )

    avg_net_bps = float(np.mean(trade_returns) * 10000) if n_trades > 0 else 0.0

    # Annualized Sharpe from daily returns (252 trading days)
    if rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    # Max drawdown from cumulative equity curve
    cum = (1.0 + rets).cumprod()
    roll_max = cum.expanding().max()
    dd = (cum - roll_max) / roll_max
    max_drawdown = float(dd.min()) if len(dd) > 0 else 0.0

    total_return_pct = float((cum.iloc[-1] - 1.0) * 100) if len(cum) > 0 else 0.0

    return {
        "trade_count": n_trades,
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if np.isfinite(profit_factor) else None,
        "avg_net_bps": round(avg_net_bps, 2),
        "total_return_pct": round(total_return_pct, 2),
    }


def compute_metrics(result: dict) -> dict:
    """Alias: return summary metrics from run_strategy output."""
    return result["summary"]


def compute_daily_pnl(result: dict) -> pd.Series:
    """Alias: return daily returns series from run_strategy output."""
    return result["daily_returns"]
