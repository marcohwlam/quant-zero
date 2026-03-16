"""
Strategy: H11 CVD-Confirmed Breakout — Volume Delta as Breakout Strength Filter
Author: Engineering Director
Date: 2026-03-16
Hypothesis: Standard price breakouts have ~60-70% false-breakout rate. CVD proxy
            (order flow delta estimate from daily OHLCV) filters for genuine directional
            buying pressure, reducing false positives and improving follow-through.
Asset class: equities (ETFs + large-cap stocks)
Parent task: QUA-136
Reference:  Kyle (1985), Glosten-Milgrom (1985), Lo et al. (2000)
            Flux Charts "Breakout Volume Delta" indicator

RESEARCH DIRECTOR CONDITIONS (QUA-130):
1. Sequential IC validation: test price breakout IC alone FIRST, then CVD proxy IC alone.
   Only combine if both IC > 0.02 individually.
2. CVD threshold sensitivity sweep: cvd_threshold_mult (0.5-2.0)
3. Universe: SPY/QQQ/IWM + top-50 S&P500 by ADV (using 12 liquid proxies here)
4. Asset: equity ETFs + large-cap stocks

DATA QUALITY NOTE:
- Survivorship bias: universe uses CURRENT large-cap tickers; companies that dropped
  out of top-50 during backtest window are NOT included. This INFLATES performance.
  Documented as known bias — point-in-time universe not available without paid service.
- CVD proxy: yfinance provides daily OHLCV only. Proxy = (C-O)/(H-L) × Volume.
  True intrabar CVD requires tick/1-min data (Polygon.io). Daily proxy is imperfect.
- Earnings exclusion: NOT applied in this backtest. Earnings breakouts (news-driven)
  may inflate performance. Engineering Director note: earnings exposure included.

TRANSACTION COST MODEL (canonical equities):
- Fixed: $0.005/share
- Slippage: 0.05%
- Market impact: 0.1 × σ × sqrt(Q/ADV)
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import spearmanr

# ── Universe ───────────────────────────────────────────────────────────────────
# SPY/QQQ/IWM + top large-caps by market cap (proxy for ADV; current tickers only)
DEFAULT_UNIVERSE = [
    "SPY", "QQQ", "IWM",
    "AAPL", "MSFT", "AMZN", "GOOGL", "NVDA", "META",
    "JPM", "JNJ", "XOM", "BRK-B", "UNH", "V",
]

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "universe": DEFAULT_UNIVERSE,
    # Price breakout
    "breakout_lookback": 20,        # N-day high lookback for price breakout
    # CVD proxy signal
    "cvd_lookback": 20,             # rolling average window for CVD normalization
    "cvd_threshold_mult": 1.0,      # CVD proxy must exceed X × 20-day avg |CVD|
    # Exit parameters
    "atr_period": 14,               # ATR lookback
    "profit_r_multiple": 2.0,       # TP = entry + profit_r × ATR
    "stop_r_multiple": 1.0,         # SL = entry - stop_r × ATR
    "max_hold_days": 10,            # time stop
    # Position sizing
    "position_size_pct": 0.10,      # 10% of portfolio per trade
    "max_concurrent": 3,            # max simultaneous positions
    "init_cash": 25000,
}

# ── Canonical Equity Transaction Cost Model ────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005   # $0.005/share
SLIPPAGE_PCT = 0.0005          # 0.05%
MARKET_IMPACT_K = 0.1          # Almgren-Chriss k
SIGMA_WINDOW = 20
ADV_WINDOW = 20

TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ───────────────────────────────────────────────────────────────

def download_equity_data(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """
    Download daily OHLCV for equity tickers via yfinance (auto_adjust=True).
    Returns dict of {ticker: DataFrame} with OHLCV columns.
    """
    result = {}
    for ticker in tickers:
        try:
            raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            if not raw.empty and len(raw) > 20:
                result[ticker] = raw
        except Exception as exc:
            warnings.warn(f"Failed to download {ticker}: {exc}")
    return result


# ── Data Quality Checklist ─────────────────────────────────────────────────────

def check_data_quality(ohlcv_dict: dict, start: str, end: str) -> dict:
    """
    Data quality notes:
    - Survivorship bias: PRESENT. Using current tickers only. Documented limitation.
    - Price adjustments: yfinance auto_adjust=True.
    - Earnings exclusion: NOT applied. Earnings breakouts included.
    - CVD proxy: daily approximation only (no tick data).
    """
    biz_days = pd.bdate_range(start=start, end=end)
    report = {
        "survivorship_bias": (
            "PRESENT — universe uses current tickers only. Companies that dropped from "
            "top-50 S&P500 ADV during backtest period are not included. This likely "
            "inflates IS performance. Documented limitation: point-in-time universe "
            "requires paid data service (not available)."
        ),
        "price_source": "yfinance with auto_adjust=True (split/dividend adjusted).",
        "earnings_exclusion": (
            "NOT applied. Earnings breakouts (±5 days) are included. "
            "This may inflate Sharpe by capturing news-driven breakout momentum. "
            "Future revision should exclude earnings windows."
        ),
        "cvd_proxy_note": (
            "CVD proxy = (Close - Open) / (High - Low) × Volume. "
            "Daily approximation only. True CVD requires tick/1-min data. "
            "Proxy may be too noisy to add predictive value over price alone."
        ),
        "tickers": {},
    }
    for ticker, ohlcv in ohlcv_dict.items():
        if ohlcv.empty:
            report["tickers"][ticker] = {"error": "No data"}
            continue
        close = ohlcv["Close"].dropna()
        missing = len(biz_days.difference(close.index))
        report["tickers"][ticker] = {
            "total_bars": len(close),
            "missing_business_days": missing,
            "gap_flag": missing > 5,
            "start": str(close.index.min().date()),
            "end": str(close.index.max().date()),
        }
    return report


# ── Indicator Computation ──────────────────────────────────────────────────────

def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """ATR using exponential smoothing (Wilder's method)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute_cvd_proxy(ohlcv: pd.DataFrame) -> pd.Series:
    """
    Daily CVD proxy: (Close - Open) / (High - Low) × Volume
    Estimates the fraction of bar volume that was net buying (+) or selling (-).
    Denominator clamped to avoid division by zero on doji candles.
    """
    high_low_range = (ohlcv["High"] - ohlcv["Low"]).clip(lower=1e-8)
    cvd = (ohlcv["Close"] - ohlcv["Open"]) / high_low_range * ohlcv["Volume"]
    return cvd.fillna(0.0)


def compute_signals(ohlcv: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute price breakout and CVD proxy signals for a single ticker.

    Price breakout (no look-ahead):
    - rolling_high[t] = max(close[t-N+1] ... close[t])
    - entry_signal[t] = close[t] > rolling_high[t-1] (shifted 1 to avoid same-bar look-ahead)
    - Execution at open[t+1]

    CVD proxy signal (no look-ahead):
    - cvd_proxy[t] = (close[t] - open[t]) / (high[t] - low[t]) × volume[t]
    - cvd_avg[t] = rolling mean of |cvd_proxy| over last N bars
    - cvd_signal[t] = cvd_proxy[t] > cvd_threshold_mult × cvd_avg[t]
    - Computed at bar T alongside price signal; both evaluated at close

    Combined signal: price_breakout AND cvd_confirmation (both at same bar T)
    Entry: open[T+1] (next bar)

    Returns DataFrame with columns:
        price_breakout, cvd_proxy, cvd_signal, combined_signal, atr
    """
    close = ohlcv["Close"]
    lookback = params["breakout_lookback"]
    cvd_lookback = params["cvd_lookback"]
    cvd_thresh = params["cvd_threshold_mult"]

    # Price breakout: close > previous N-day high (shift(1) on rolling max)
    rolling_high = close.rolling(window=lookback, min_periods=lookback).max().shift(1)
    price_breakout = (close > rolling_high).fillna(False)

    # CVD proxy
    cvd_proxy = compute_cvd_proxy(ohlcv)
    # Average absolute CVD (for normalization)
    cvd_avg = cvd_proxy.abs().rolling(window=cvd_lookback, min_periods=cvd_lookback).mean()
    cvd_signal = (cvd_proxy > cvd_thresh * cvd_avg).fillna(False)

    # ATR
    atr = compute_atr(ohlcv["High"], ohlcv["Low"], close, params["atr_period"])

    # Combined signal
    combined = price_breakout & cvd_signal

    return pd.DataFrame({
        "close": close,
        "price_breakout": price_breakout,
        "cvd_proxy": cvd_proxy,
        "cvd_avg": cvd_avg,
        "cvd_signal": cvd_signal,
        "combined_signal": combined,
        "atr": atr,
    })


# ── IC Validation (Sequential per Research Director QUA-130) ─────────────────

def compute_signal_ic(
    signal: pd.Series,
    closes: pd.Series,
    forward_period: int = 5,
    label: str = "signal",
) -> dict:
    """
    Compute Spearman IC between signal and forward return.
    Signal can be binary (0/1) or continuous.
    """
    fwd_return = closes.pct_change(periods=forward_period).shift(-forward_period)
    combined = pd.DataFrame({"signal": signal.astype(float), "fwd_return": fwd_return}).dropna()
    active = combined[combined["signal"] != 0]

    if len(active) < 10:
        return {
            "label": label, "ic": 0.0, "ic_pass": False,
            "n_signals": len(active), "note": "Insufficient signals."
        }

    ic, pval = spearmanr(active["signal"], active["fwd_return"])
    ic = float(ic) if not np.isnan(ic) else 0.0

    return {
        "label": label,
        "ic": round(ic, 4),
        "ic_pass": abs(ic) > 0.02,
        "ic_pvalue": round(float(pval), 4),
        "n_signals": len(active),
        "note": f"IC={ic:.4f} ({'PASS' if abs(ic) > 0.02 else 'FAIL — IC below 0.02 threshold'})",
    }


def validate_sequential_ic(
    ohlcv_dict: dict,
    params: dict,
) -> dict:
    """
    Research Director QUA-130 sequential IC validation:
    1. Price breakout IC alone
    2. CVD proxy IC alone
    3. Combined IC

    Reports whether each signal meets the 0.02 IC threshold.
    Decision: combine only if BOTH signals clear IC floor.
    """
    all_price_ic, all_cvd_ic, all_combined_ic = [], [], []
    all_signals = {}

    for ticker, ohlcv in ohlcv_dict.items():
        if ohlcv.empty:
            continue
        sigs = compute_signals(ohlcv, params)
        close = sigs["close"]

        # 1. Price breakout IC
        price_ic = compute_signal_ic(
            sigs["price_breakout"].astype(float), close, label=f"{ticker}_price_breakout"
        )
        all_price_ic.append(price_ic["ic"])

        # 2. CVD proxy IC (positive CVD as standalone signal)
        cvd_ic = compute_signal_ic(
            sigs["cvd_signal"].astype(float), close, label=f"{ticker}_cvd_proxy"
        )
        all_cvd_ic.append(cvd_ic["ic"])

        # 3. Combined IC
        combined_ic = compute_signal_ic(
            sigs["combined_signal"].astype(float), close, label=f"{ticker}_combined"
        )
        all_combined_ic.append(combined_ic["ic"])

        all_signals[ticker] = {
            "price_ic": price_ic,
            "cvd_ic": cvd_ic,
            "combined_ic": combined_ic,
        }

    avg_price_ic = float(np.mean(all_price_ic)) if all_price_ic else 0.0
    avg_cvd_ic = float(np.mean(all_cvd_ic)) if all_cvd_ic else 0.0
    avg_combined_ic = float(np.mean(all_combined_ic)) if all_combined_ic else 0.0

    price_ic_pass = abs(avg_price_ic) > 0.02
    cvd_ic_pass = abs(avg_cvd_ic) > 0.02
    both_pass = price_ic_pass and cvd_ic_pass

    decision = "COMBINE" if both_pass else (
        "PRICE_ONLY" if price_ic_pass else "REJECT_BOTH"
    )

    return {
        "avg_price_breakout_ic": round(avg_price_ic, 4),
        "avg_cvd_proxy_ic": round(avg_cvd_ic, 4),
        "avg_combined_ic": round(avg_combined_ic, 4),
        "price_ic_pass": price_ic_pass,
        "cvd_ic_pass": cvd_ic_pass,
        "decision": decision,
        "per_ticker": all_signals,
        "note": (
            f"Price IC={avg_price_ic:.4f} ({'PASS' if price_ic_pass else 'FAIL'}), "
            f"CVD IC={avg_cvd_ic:.4f} ({'PASS' if cvd_ic_pass else 'FAIL'}). "
            f"Decision: {decision}. "
            + ("Both signals cleared IC floor — combined signal is valid."
               if both_pass else
               "CVD IC below floor — downgraded to price breakout only."
               if price_ic_pass else
               "Both signals below IC floor — strategy rejected.")
        ),
    }


# ── Transaction Costs ─────────────────────────────────────────────────────────

def compute_transaction_cost(shares: int, price: float, sigma: float, adv: float) -> dict:
    """Canonical equity transaction cost."""
    trade_value = shares * price
    fixed = shares * FIXED_COST_PER_SHARE
    slippage = SLIPPAGE_PCT * trade_value
    q_over_adv = shares / adv if adv > 0 else 0.0
    impact_pct = MARKET_IMPACT_K * sigma * np.sqrt(q_over_adv)
    impact = impact_pct * trade_value
    return {
        "total": fixed + slippage + impact,
        "liquidity_constrained": q_over_adv > 0.01,
        "impact_bps": round(impact_pct * 10000, 2),
    }


# ── Trade Simulator ───────────────────────────────────────────────────────────

def simulate_trades_single(
    ohlcv: pd.DataFrame,
    signals: pd.DataFrame,
    params: dict,
    init_cash: float,
    other_positions_count: callable,  # callable returning current open position count
) -> tuple[list[dict], pd.Series]:
    """
    Simulate H11 breakout strategy on a single ticker.

    Entry: signal at close T → enter at open T+1 (no look-ahead).
    - Price breakout AND CVD confirmation at close T
    - Max concurrent positions: params["max_concurrent"]

    Exit (checked at each bar):
    - TP: bar high >= entry + profit_r × ATR
    - SL: bar low <= entry - stop_r × ATR
    - Time stop: hold >= max_hold_days
    """
    opens = ohlcv["Open"]
    highs = ohlcv["High"]
    lows = ohlcv["Low"]
    closes = ohlcv["Close"]
    volumes = ohlcv["Volume"]

    combined_signal = signals["combined_signal"]
    atr_series = signals["atr"]

    rolling_sigma = closes.pct_change().rolling(SIGMA_WINDOW, min_periods=5).std()
    rolling_adv = volumes.rolling(ADV_WINDOW, min_periods=5).mean()

    tp_r = params["profit_r_multiple"]
    sl_r = params["stop_r_multiple"]
    max_hold = params["max_hold_days"]
    pos_pct = params["position_size_pct"]

    trade_log: list[dict] = []
    portfolio_value = pd.Series(index=closes.index, dtype=float)
    dates = closes.index.tolist()

    cash = float(init_cash)
    position_shares = 0
    entry_price = 0.0
    entry_date = None
    hold_days = 0
    tp_price = 0.0
    sl_price = 0.0
    entry_cost = 0.0

    for i, date in enumerate(dates):
        bar_close = float(closes.iloc[i])
        bar_open = float(opens.iloc[i])
        bar_high = float(highs.iloc[i])
        bar_low = float(lows.iloc[i])

        if position_shares > 0:
            portfolio_value.iloc[i] = cash + position_shares * bar_close
        else:
            portfolio_value.iloc[i] = cash

        # ── Exit ─────────────────────────────────────────────────────────────
        if position_shares > 0:
            exit_price = None
            exit_reason = None

            if bar_low <= sl_price:
                exit_price = min(bar_open, sl_price) if bar_open < sl_price else sl_price
                exit_reason = "stop_loss"
            elif bar_high >= tp_price:
                exit_price = max(bar_open, tp_price) if bar_open > tp_price else tp_price
                exit_reason = "take_profit"
            elif hold_days >= max_hold:
                exit_price = bar_close
                exit_reason = "time_stop"

            if exit_price is not None:
                sigma = float(rolling_sigma.iloc[i]) if not np.isnan(rolling_sigma.iloc[i]) else 0.01
                adv = float(rolling_adv.iloc[i]) if not np.isnan(rolling_adv.iloc[i]) else 1e6
                cost_info = compute_transaction_cost(position_shares, exit_price, sigma, adv)
                exit_cost = cost_info["total"]
                pnl = position_shares * (exit_price - entry_price) - entry_cost - exit_cost

                trade_log.append({
                    "entry_date": str(entry_date.date()),
                    "exit_date": str(date.date()),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "shares": position_shares,
                    "hold_days": hold_days,
                    "exit_reason": exit_reason,
                    "net_pnl": round(pnl, 4),
                    "entry_cost": round(entry_cost, 4),
                    "exit_cost": round(exit_cost, 4),
                    "liquidity_constrained": cost_info["liquidity_constrained"],
                })

                cash += position_shares * exit_price - exit_cost
                position_shares = 0
                hold_days = 0
                portfolio_value.iloc[i] = cash
            else:
                hold_days += 1

        # ── Entry ─────────────────────────────────────────────────────────────
        if position_shares == 0 and i > 0:
            prev_signal = bool(combined_signal.iloc[i - 1])
            if prev_signal and other_positions_count() < params["max_concurrent"]:
                entry_atr = float(atr_series.iloc[i]) if not np.isnan(atr_series.iloc[i]) else bar_open * 0.01
                sigma = float(rolling_sigma.iloc[i]) if not np.isnan(rolling_sigma.iloc[i]) else 0.01
                adv = float(rolling_adv.iloc[i]) if not np.isnan(rolling_adv.iloc[i]) else 1e6

                port_val = float(portfolio_value.iloc[i - 1])
                shares = max(1, int(pos_pct * port_val / bar_open))
                trade_val = shares * bar_open

                if trade_val <= cash * 0.98:
                    cost_info = compute_transaction_cost(shares, bar_open, sigma, adv)
                    entry_cost = cost_info["total"]
                    cash -= trade_val + entry_cost
                    position_shares = shares
                    entry_price = bar_open
                    entry_date = date
                    hold_days = 1
                    tp_price = bar_open + tp_r * entry_atr
                    sl_price = bar_open - sl_r * entry_atr
                    portfolio_value.iloc[i] = cash + position_shares * bar_close

    # Force-close end of data
    if position_shares > 0:
        last_close = float(closes.iloc[-1])
        sigma = float(rolling_sigma.iloc[-1]) if not np.isnan(rolling_sigma.iloc[-1]) else 0.01
        adv = float(rolling_adv.iloc[-1]) if not np.isnan(rolling_adv.iloc[-1]) else 1e6
        cost_info = compute_transaction_cost(position_shares, last_close, sigma, adv)
        exit_cost = cost_info["total"]
        pnl = position_shares * (last_close - entry_price) - entry_cost - exit_cost
        trade_log.append({
            "entry_date": str(entry_date.date()),
            "exit_date": str(dates[-1].date()),
            "entry_price": round(entry_price, 4),
            "exit_price": round(last_close, 4),
            "shares": position_shares,
            "hold_days": hold_days,
            "exit_reason": "end_of_data",
            "net_pnl": round(pnl, 4),
            "entry_cost": round(entry_cost, 4),
            "exit_cost": round(exit_cost, 4),
            "liquidity_constrained": cost_info["liquidity_constrained"],
        })
        cash += position_shares * last_close - exit_cost
        portfolio_value.iloc[-1] = cash

    portfolio_value = portfolio_value.ffill()
    return trade_log, portfolio_value


# ── Core Strategy Runner ──────────────────────────────────────────────────────

def run_strategy(
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    params: dict | None = None,
    signal_override: str | None = None,  # "price_only", "cvd_only", "combined"
) -> dict:
    """
    Run H11 CVD-Confirmed Breakout on multi-ticker universe.

    Args:
        start/end: backtest period
        params: strategy parameters
        signal_override: force signal type for IC validation
            "price_only" = price breakout signal only
            "cvd_only" = CVD proxy signal only
            "combined" = both signals (default)

    Returns:
        Metrics dict with sharpe, MDD, trade log, per-ticker breakdown.
    """
    if params is None:
        params = PARAMETERS

    universe = params.get("universe", DEFAULT_UNIVERSE)
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=60)).strftime("%Y-%m-%d")
    ohlcv_dict = download_equity_data(universe, warmup_start, end)

    quality = check_data_quality(ohlcv_dict, start, end)

    bt_start = pd.Timestamp(start)

    # Combined portfolio tracking
    combined_value = None
    all_trades: list[dict] = []

    # Track all open positions across tickers (for max_concurrent)
    open_positions: dict[str, bool] = {ticker: False for ticker in ohlcv_dict}

    def count_open():
        return sum(open_positions.values())

    for ticker, ohlcv in ohlcv_dict.items():
        ohlcv_bt = ohlcv.loc[ohlcv.index >= bt_start].copy()
        if len(ohlcv_bt) < 30:
            continue

        sigs = compute_signals(ohlcv_bt, params)

        # Apply signal override for IC validation
        if signal_override == "price_only":
            sigs["combined_signal"] = sigs["price_breakout"]
        elif signal_override == "cvd_only":
            sigs["combined_signal"] = sigs["cvd_signal"]
        # default: combined (already computed)

        init_cash_per_ticker = params["init_cash"] / max(1, len(ohlcv_dict))

        def ticker_open():
            return count_open()

        trades, pv = simulate_trades_single(
            ohlcv_bt, sigs, params, init_cash_per_ticker, ticker_open
        )

        # Update open position tracker based on trade log
        open_positions[ticker] = bool(trades) and trades[-1].get("exit_reason") == "end_of_data"

        for t in trades:
            t["ticker"] = ticker
        all_trades.extend(trades)

        if combined_value is None:
            combined_value = pv
        else:
            combined_value = combined_value.add(pv, fill_value=0)

    if combined_value is None or combined_value.empty:
        raise ValueError(f"No portfolio value computed for {start}–{end}")

    # Compute metrics
    returns = combined_value.pct_change().dropna()
    if len(returns) > 1 and returns.std() > 0:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    rolling_peak = combined_value.cummax()
    mdd = float(((combined_value - rolling_peak) / rolling_peak).min())
    total_return = float((combined_value.iloc[-1] / combined_value.iloc[0]) - 1)

    pnls = np.array([t["net_pnl"] for t in all_trades]) if all_trades else np.array([])
    if len(pnls) > 0:
        win_rate = float(np.mean(pnls > 0))
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
        profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")
    else:
        win_rate = win_loss_ratio = profit_factor = 0.0

    exit_reasons = {}
    for t in all_trades:
        r = t.get("exit_reason", "unknown")
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    liquidity_flags = sum(1 for t in all_trades if t.get("liquidity_constrained", False))

    per_ticker_trades = {}
    for t in all_trades:
        tk = t.get("ticker", "unknown")
        per_ticker_trades[tk] = per_ticker_trades.get(tk, 0) + 1

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "win_rate": round(win_rate, 4),
        "win_loss_ratio": round(win_loss_ratio, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "trade_count": len(all_trades),
        "total_return": round(total_return, 4),
        "exit_reasons": exit_reasons,
        "per_ticker_trades": per_ticker_trades,
        "liquidity_flags": liquidity_flags,
        "data_quality": quality,
        "trade_log": all_trades,
        "portfolio_value": combined_value,
        "returns": returns.values,
        "period": f"{start} to {end}",
    }


# ── CVD Threshold Sensitivity Scan ────────────────────────────────────────────

def scan_cvd_threshold(
    ohlcv_dict: dict,
    start: str,
    end: str,
    base_params: dict,
    threshold_values: list[float] | None = None,
) -> dict:
    """
    Sweep cvd_threshold_mult: 0.5, 0.75, 1.0, 1.25, 1.5, 2.0
    """
    if threshold_values is None:
        threshold_values = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

    results = {}
    for t in threshold_values:
        key = f"cvd_mult_{str(t).replace('.', 'p')}"
        p = {**base_params, "cvd_threshold_mult": t}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[key] = {
                "cvd_threshold_mult": t,
                "sharpe": r["sharpe"],
                "trade_count": r["trade_count"],
                "max_drawdown": r["max_drawdown"],
            }
        except Exception as exc:
            results[key] = {"error": str(exc)}

    sharpe_vals = [v["sharpe"] for v in results.values()
                   if isinstance(v, dict) and "sharpe" in v and isinstance(v["sharpe"], float)]
    if len(sharpe_vals) > 1:
        sharpe_range = max(sharpe_vals) - min(sharpe_vals)
        sharpe_mean = np.mean(sharpe_vals)
        variance_pct = sharpe_range / abs(sharpe_mean) if sharpe_mean != 0 else float("inf")
        results["_meta"] = {
            "sharpe_range": round(sharpe_range, 4),
            "sharpe_variance_pct": round(float(variance_pct), 4),
            "gate1_robustness": "PASS" if variance_pct <= 0.30 else f"FAIL (>{30:.0f}% variance)",
        }
    return results
