"""
H12 — SuperTrend ATR Momentum
==============================
Gate 1 strategy implementation.

Signal: ATR-adaptive SuperTrend band flip (long-only).
Regime gates: VIX < 30, price > 200-day SMA.
Universe: SPY, QQQ, IWM (ETFs only in Gate 1).

Entry: Close crosses above SuperTrend line (bearish → bullish flip).
Exit:  Close crosses below SuperTrend line (bullish → bearish flip).
       Time stop: 30 days max.

Parameters:
  atr_lookback (int): ATR period. Default 14.
  atr_multiplier (float): Band width. Default 2.5.
  vix_threshold (float): Max VIX for entry. Default 30.
  sma_period (int): Long-term SMA period for trend filter. Default 200.

References:
  - Moskowitz, Ooi, Pedersen (2012) — Time Series Momentum
  - Hurst et al. (2017) AQR — Two Centuries of Trend
  - KivancOzbilgic SuperTrend STRATEGY (TradingView, low cherry-pick risk)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from typing import Optional


# ---------------------------------------------------------------------------
# Core indicators
# ---------------------------------------------------------------------------

def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range."""
    n = len(close)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = np.empty(n)
    atr[:period] = np.nan
    atr[period-1] = np.mean(tr[:period])
    alpha = 1.0 / period
    for i in range(period, n):
        atr[i] = alpha * tr[i] + (1 - alpha) * atr[i-1]
    return atr


def compute_supertrend(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
    multiplier: float = 2.5,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute SuperTrend line and direction.

    Returns
    -------
    supertrend : np.ndarray  — SuperTrend value (nan before ATR period)
    direction  : np.ndarray  — +1 = bullish (price above ST), -1 = bearish
    """
    n = len(close)
    hl2 = (high + low) / 2.0
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    upper = np.empty(n)
    lower = np.empty(n)
    supertrend = np.full(n, np.nan)
    direction = np.zeros(n)

    for i in range(n):
        if np.isnan(atr[i]):
            upper[i] = upper_basic[i]
            lower[i] = lower_basic[i]
            continue

        # Adjust bands to prevent premature flips
        upper[i] = upper_basic[i]
        lower[i] = lower_basic[i]
        if i > 0 and not np.isnan(atr[i-1]):
            if upper_basic[i] < upper[i-1] or close[i-1] > upper[i-1]:
                upper[i] = upper_basic[i]
            else:
                upper[i] = upper[i-1]
            if lower_basic[i] > lower[i-1] or close[i-1] < lower[i-1]:
                lower[i] = lower_basic[i]
            else:
                lower[i] = lower[i-1]

        if i == 0 or np.isnan(atr[i-1]):
            direction[i] = 1 if close[i] <= upper[i] else -1
        elif supertrend[i-1] == upper[i-1]:
            direction[i] = 1 if close[i] <= upper[i] else -1
        else:
            direction[i] = -1 if close[i] >= lower[i] else 1

        supertrend[i] = lower[i] if direction[i] == -1 else upper[i]

    return supertrend, direction


def compute_sma(prices: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    sma = np.empty(len(prices))
    sma[:] = np.nan
    for i in range(period - 1, len(prices)):
        sma[i] = np.mean(prices[i - period + 1 : i + 1])
    return sma


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def generate_signals(
    df: pd.DataFrame,
    atr_lookback: int = 14,
    atr_multiplier: float = 2.5,
    vix_threshold: float = 30.0,
    sma_period: int = 200,
    vix_data: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Generate long entry/exit signals with regime gates.

    Parameters
    ----------
    df          : OHLCV DataFrame (columns: Open, High, Low, Close, Volume)
    vix_data    : Series of VIX close prices aligned to df.index

    Returns
    -------
    DataFrame with additional columns:
      atr, supertrend, direction, sma200
      regime_ok  : VIX < threshold AND close > SMA200
      entry      : bool — bullish flip in regime
      exit       : bool — bearish flip
    """
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values

    atr = compute_atr(h, l, c, period=atr_lookback)
    supertrend, direction = compute_supertrend(h, l, c, atr, multiplier=atr_multiplier)
    sma200 = compute_sma(c, period=sma_period)

    df = df.copy()
    df["atr"] = atr
    df["supertrend"] = supertrend
    df["direction"] = direction
    df["sma200"] = sma200

    # Regime: price > SMA200
    df["sma_ok"] = c > sma200

    # Regime: VIX < threshold
    if vix_data is not None:
        vix_aligned = vix_data.reindex(df.index, method="ffill")
        df["vix"] = vix_aligned.values
        df["vix_ok"] = df["vix"] < vix_threshold
    else:
        df["vix_ok"] = True
        df["vix"] = np.nan

    df["regime_ok"] = df["sma_ok"] & df["vix_ok"]

    # Flip detection
    direction_prev = np.roll(direction, 1)
    direction_prev[0] = direction[0]

    # Long entry: direction flipped from bearish to bullish, regime OK
    bullish_flip = (direction == -1) & (direction_prev == 1)
    df["entry"] = bullish_flip & df["regime_ok"].values

    # Exit: bearish flip (direction flipped from bullish to bearish)
    bearish_flip = (direction == 1) & (direction_prev == -1)
    df["exit"] = bearish_flip

    return df


# ---------------------------------------------------------------------------
# Trade simulation
# ---------------------------------------------------------------------------

def simulate_trades(
    df: pd.DataFrame,
    position_size_pct: float = 0.5,
    max_hold_days: int = 30,
    cost_per_share: float = 0.005,
    slippage_pct: float = 0.0005,
) -> list[dict]:
    """
    Simulate trade-by-trade PnL with transaction costs.

    Entry at next open after signal bar.
    Exit at next open after exit signal or time stop.
    """
    trades = []
    in_trade = False
    entry_price = 0.0
    entry_date = None
    entry_bar = 0

    opens = df["Open"].values
    closes = df["Close"].values
    entries = df["entry"].values
    exits = df["exit"].values
    dates = df.index

    for i in range(1, len(df)):
        if not in_trade:
            if entries[i - 1]:  # signal on bar i-1, enter at open of bar i
                raw_entry = opens[i]
                slip = raw_entry * slippage_pct
                entry_price = raw_entry + slip
                entry_date = dates[i]
                entry_bar = i
                in_trade = True
        else:
            bars_held = i - entry_bar
            if exits[i - 1] or bars_held >= max_hold_days:
                raw_exit = opens[i]
                slip = raw_exit * slippage_pct
                exit_price = raw_exit - slip

                # Transaction costs
                shares = position_size_pct * 10_000 / entry_price  # notional $10k per trade
                cost = cost_per_share * shares * 2  # round-trip
                gross_pnl = (exit_price - entry_price) * shares
                net_pnl = gross_pnl - cost

                trades.append({
                    "entry_date": entry_date,
                    "exit_date": dates[i],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "bars_held": bars_held,
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "return_pct": (exit_price - entry_price) / entry_price,
                })
                in_trade = False

    return trades


# ---------------------------------------------------------------------------
# Portfolio metrics
# ---------------------------------------------------------------------------

def compute_metrics(trades: list[dict], returns_series: Optional[pd.Series] = None) -> dict:
    """Compute standard Gate 1 metrics from trade list."""
    if not trades:
        return {
            "trade_count": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "sharpe": 0.0, "max_drawdown": 0.0,
        }

    pnls = np.array([t["net_pnl"] for t in trades])
    returns = np.array([t["return_pct"] for t in trades])

    win_rate = float(np.mean(pnls > 0))
    gross_profits = pnls[pnls > 0].sum()
    gross_losses = abs(pnls[pnls < 0].sum())
    profit_factor = gross_profits / (gross_losses + 1e-8)

    sharpe = float(returns.mean() / (returns.std() + 1e-8) * np.sqrt(252 / 14))  # ~annualised

    # Max drawdown from cumulative PnL curve
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / (np.abs(peak) + 1e-8)
    max_dd = float(dd.min())

    return {
        "trade_count": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
    }


def compute_ic(df: pd.DataFrame, signal_col: str = "direction", forward_days: int = 5) -> float:
    """
    Compute Information Coefficient: Spearman correlation between
    SuperTrend direction signal and forward returns.
    """
    from scipy import stats
    closes = df["Close"].values
    signal = df[signal_col].values
    fwd_ret = np.empty(len(closes))
    fwd_ret[:] = np.nan
    for i in range(len(closes) - forward_days):
        fwd_ret[i] = (closes[i + forward_days] - closes[i]) / closes[i]

    mask = ~np.isnan(fwd_ret) & ~np.isnan(signal) & (signal != 0)
    if mask.sum() < 20:
        return 0.0
    ic, _ = stats.spearmanr(signal[mask], fwd_ret[mask])
    return float(ic)


# ---------------------------------------------------------------------------
# Strategy entry point
# ---------------------------------------------------------------------------

def run_strategy(
    ticker: str,
    start: str,
    end: str,
    atr_lookback: int = 14,
    atr_multiplier: float = 2.5,
    vix_threshold: float = 30.0,
    sma_period: int = 200,
    position_size_pct: float = 0.5,
    max_hold_days: int = 30,
) -> dict:
    """
    Full strategy run for a single ticker over a date range.

    Returns dict with trades list and metrics.
    """
    # Download price data
    price_df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if price_df.empty or len(price_df) < sma_period + 50:
        return {"ticker": ticker, "error": "insufficient_data", "trades": [], "metrics": {}}

    # Flatten multi-index columns if present
    if isinstance(price_df.columns, pd.MultiIndex):
        price_df.columns = price_df.columns.get_level_values(0)

    # Download VIX
    vix_df = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)
    vix_series = vix_df["Close"] if not vix_df.empty else None

    df = generate_signals(
        price_df,
        atr_lookback=atr_lookback,
        atr_multiplier=atr_multiplier,
        vix_threshold=vix_threshold,
        sma_period=sma_period,
        vix_data=vix_series,
    )

    ic = compute_ic(df, signal_col="direction")
    trades = simulate_trades(df, position_size_pct=position_size_pct, max_hold_days=max_hold_days)
    metrics = compute_metrics(trades)
    metrics["ic"] = ic

    return {
        "ticker": ticker,
        "start": start,
        "end": end,
        "ic": ic,
        "trades": trades,
        "metrics": metrics,
        "df": df,
    }


def run_multi_asset(
    tickers: list[str],
    start: str,
    end: str,
    atr_lookback: int = 14,
    atr_multiplier: float = 2.5,
    vix_threshold: float = 30.0,
    sma_period: int = 200,
    position_size_pct: float = 0.33,
    max_hold_days: int = 30,
) -> dict:
    """Aggregate strategy over multiple tickers (equal-weight combination)."""
    all_trades = []
    per_ticker = {}
    for tkr in tickers:
        result = run_strategy(
            tkr, start, end,
            atr_lookback=atr_lookback,
            atr_multiplier=atr_multiplier,
            vix_threshold=vix_threshold,
            sma_period=sma_period,
            position_size_pct=position_size_pct,
            max_hold_days=max_hold_days,
        )
        if "error" not in result:
            all_trades.extend(result["trades"])
            per_ticker[tkr] = result["metrics"]

    metrics = compute_metrics(all_trades)
    return {"tickers": tickers, "trades": all_trades, "metrics": metrics, "per_ticker": per_ticker}


# ---------------------------------------------------------------------------
# Parameter sensitivity scanner
# ---------------------------------------------------------------------------

def scan_atr_params(
    tickers: list[str],
    start: str,
    end: str,
    multipliers: Optional[list] = None,
    lookbacks: Optional[list] = None,
) -> pd.DataFrame:
    """
    Sweep ATR multiplier × lookback grid.
    Returns DataFrame with Sharpe per combination.
    """
    if multipliers is None:
        multipliers = [1.5, 2.0, 2.5, 3.0, 3.5]
    if lookbacks is None:
        lookbacks = [7, 10, 14, 17, 20]

    rows = []
    for mult in multipliers:
        for lb in lookbacks:
            result = run_multi_asset(tickers, start, end, atr_lookback=lb, atr_multiplier=mult)
            rows.append({
                "atr_multiplier": mult,
                "atr_lookback": lb,
                "sharpe": result["metrics"].get("sharpe", 0.0),
                "trade_count": result["metrics"].get("trade_count", 0),
                "win_rate": result["metrics"].get("win_rate", 0.0),
            })
    return pd.DataFrame(rows)
