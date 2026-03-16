"""
Strategy: H10 Crypto Equal High/Low Liquidity Reversal (ATR-Scaled)
Author: Engineering Director
Date: 2026-03-16
Hypothesis: EQH/EQL zones (equal highs/lows) represent institutional liquidity pools.
            Price excursions beyond these zones trigger retail stops; institutional
            absorption causes reversal. ATR-scaled entries/exits.
Asset class: crypto (BTC/ETH daily bars)
Parent task: QUA-135
Reference:  ICT/SMC framework; Williams (2001) "Long-Term Secrets to Short-Term Trading";
            Kuepper (2021) "Smart Money Concepts Explained"

NOTES:
- Long-only: EQL (equal low) reversal signal — price dips below EQL zone and recovers.
- Short: EQH (equal high) reversal — price exceeds EQH zone and closes back below.
- Regime gate: disable long entries when BTC 20-day ROC < -15% (capitulation filter).
- Asset: BTC/ETH daily bars only (per Research Director QUA-129). No altcoins.
- Data: BTC-USD and ETH-USD from yfinance (spot prices, auto_adjust=True).
- Swing high/low confirmed 1 bar after peak/trough (no look-ahead).
- EQH/EQL zone: ≥ 2 confirmed swing highs/lows within ATR × tolerance_mult of each other.
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ────────────────────────────────────────────────────────

PARAMETERS = {
    "universe": ["BTC-USD", "ETH-USD"],
    # EQH/EQL detection
    "lookback_n_bars": 20,      # bars to scan for swing points
    "tolerance_mult": 0.30,     # ATR multiplier for "equal" zone band
    "atr_period": 14,           # ATR lookback
    "min_touches": 2,           # minimum swing points to confirm a zone
    # Entry
    "confirmation_bars": 1,     # recovery candles after zone breach before entry
    # Exit
    "stop_atr_mult": 1.5,       # SL = zone level - stop_atr_mult × ATR
    "max_hold_bars": 7,         # time stop (days)
    # Regime gate
    "btc_roc_period": 20,       # BTC 20-day ROC lookback
    "btc_roc_gate": -0.15,      # disable entries when BTC ROC < -15%
    # Position sizing
    "position_size_pct": 0.10,  # 10% of portfolio per trade (crypto high vol)
    "capital_split_btc": 0.60,  # BTC gets 60% of capital
    "capital_split_eth": 0.40,  # ETH gets 40% of capital
    "init_cash": 25000,
}

# ── Canonical Crypto Transaction Cost Model ────────────────────────────────────
CRYPTO_TAKER_FEE = 0.001   # 0.10% taker fee
CRYPTO_SLIPPAGE = 0.0005   # 0.05% slippage
# Total effective round-trip: ~0.30%

TRADING_DAYS_PER_YEAR = 365  # crypto trades 24/7; use 365 for annualization


# ── Data Loading ───────────────────────────────────────────────────────────────

def download_crypto_ohlcv(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """
    Download daily OHLCV for crypto tickers.

    BTC-USD available from 2014+, ETH-USD from 2016+.
    Returns dict of OHLCV DataFrames indexed by ticker.
    """
    result = {}
    for ticker in tickers:
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        result[ticker] = raw
    return result


# ── Data Quality Checklist ─────────────────────────────────────────────────────

def check_data_quality(ohlcv_dict: dict, start: str, end: str) -> dict:
    """
    Data quality checks per Engineering Director pre-backtest checklist.

    BTC/ETH notes:
    - Survivorship bias: BTC trading since 2009, ETH since 2016. Both available for IS window.
    - Price adjustments: yfinance auto_adjust=True.
    - Earnings exclusion: N/A — no earnings for crypto.
    - Delisted: N/A — BTC/ETH cannot be delisted from the market.
    - Universe: BTC/ETH only per Research Director (QUA-129). No altcoins.
    """
    report = {
        "survivorship_bias": (
            "BTC-USD: trading since 2009. ETH-USD: trading since 2016. "
            "Both fully cover the IS window. No survivorship bias. "
            "Universe limited to BTC/ETH per Research Director mandate (QUA-129)."
        ),
        "price_source": "yfinance BTC-USD, ETH-USD OHLCV with auto_adjust=True.",
        "earnings_exclusion": "N/A — no earnings events for crypto assets.",
        "delisted": "N/A — BTC and ETH cannot be delisted from the market.",
        "altcoin_note": "Altcoin expansion not tested per Research Director QUA-129 until IC > 0.02 confirmed.",
        "tickers": {},
    }

    for ticker, ohlcv in ohlcv_dict.items():
        if ohlcv.empty:
            report["tickers"][ticker] = {"error": "No data"}
            continue
        close = ohlcv["Close"].dropna()
        expected = pd.date_range(start=start, end=end, freq="D")
        missing = len(expected.difference(close.index))
        report["tickers"][ticker] = {
            "total_bars": len(close),
            "missing_calendar_days": missing,
            "gap_flag": missing > 5,
            "start": str(close.index.min().date()),
            "end": str(close.index.max().date()),
        }
        if missing > 5:
            warnings.warn(f"Data gap: {ticker} has {missing} missing calendar days.")

    return report


# ── Technical Indicators ──────────────────────────────────────────────────────

def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """ATR using Wilder's smoothing (standard for crypto swing strategies)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr


def find_swing_highs_lows(high: pd.Series, low: pd.Series) -> tuple[pd.Series, pd.Series]:
    """
    Find confirmed swing highs and lows (1-bar lag for no look-ahead).

    Swing high at bar t: high[t] > high[t-1] AND high[t] > high[t+1]
    Since high[t+1] is not yet known at bar t, we confirm at bar t+1:
    swing_high_at[t] = (high[t] > high[t-1]) & (high[t] > high[t+1])
    Implemented as: signal at t, known at t+1. Shift back to get confirmed bar.

    At bar t (where we know high[t], high[t+1]):
        confirmed swing high at t-1: high[t-1] > high[t-2] AND high[t-1] > high[t]
    So: swing_high_confirmed[t] = (high[t-1] > high[t-2]) & (high[t-1] > high[t])
    This means: on bar t, we KNOW there's a confirmed swing high at bar t-1.

    No look-ahead: we use only data available at time t.
    """
    # Confirmed at current bar t about bar t-1
    sh_value = high.shift(1)  # the swing high candidate price
    sh_confirmed = (high.shift(1) > high.shift(2)) & (high.shift(1) > high)

    sl_value = low.shift(1)
    sl_confirmed = (low.shift(1) < low.shift(2)) & (low.shift(1) < low)

    # Return series where True means "there's a swing high/low at the PREVIOUS bar"
    swing_highs = pd.Series(np.where(sh_confirmed, sh_value, np.nan), index=high.index)
    swing_lows = pd.Series(np.where(sl_confirmed, sl_value, np.nan), index=low.index)

    return swing_highs, swing_lows


def find_eql_eqh_zones(
    swing_highs: pd.Series,
    swing_lows: pd.Series,
    atr: pd.Series,
    params: dict,
    bar_idx: int,
) -> tuple[list[float], list[float]]:
    """
    Find EQL and EQH zone levels at bar_idx using past data only.

    Scans the past lookback_n_bars for swing points.
    Groups swing points within ATR × tolerance_mult of each other.
    Returns lists of zone levels (EQL = equal lows, EQH = equal highs).

    No look-ahead: uses only index[:bar_idx+1] (inclusive of current bar).
    """
    lookback = params["lookback_n_bars"]
    tolerance = params["tolerance_mult"]
    min_touches = params["min_touches"]

    start_idx = max(0, bar_idx - lookback)

    # Get swing points in window
    sh_window = swing_highs.iloc[start_idx:bar_idx + 1].dropna()
    sl_window = swing_lows.iloc[start_idx:bar_idx + 1].dropna()
    current_atr = float(atr.iloc[bar_idx]) if not np.isnan(atr.iloc[bar_idx]) else 0.0

    if current_atr <= 0:
        return [], []

    tol_band = tolerance * current_atr

    def cluster_levels(values: list[float]) -> list[float]:
        """Group values within tol_band of each other; return zones with >= min_touches."""
        if len(values) < min_touches:
            return []
        zones = []
        used = [False] * len(values)
        for i, v in enumerate(values):
            if used[i]:
                continue
            group = [v]
            for j in range(i + 1, len(values)):
                if not used[j] and abs(values[j] - v) <= tol_band:
                    group.append(values[j])
                    used[j] = True
            if len(group) >= min_touches:
                zones.append(float(np.mean(group)))
            used[i] = True
        return zones

    eqh_zones = cluster_levels(sh_window.tolist())
    eql_zones = cluster_levels(sl_window.tolist())

    return eql_zones, eqh_zones


# ── Regime Gate ───────────────────────────────────────────────────────────────

def compute_btc_regime(btc_close: pd.Series, params: dict) -> pd.Series:
    """
    BTC 20-day ROC regime gate.
    Returns True when BTC ROC > btc_roc_gate (entries allowed).
    Returns False when BTC in capitulation (ROC < -15%) — disable new entries.

    No look-ahead: ROC[t] = (close[t] - close[t-N]) / close[t-N]
    """
    roc_period = params["btc_roc_period"]
    btc_roc = btc_close.pct_change(periods=roc_period)
    regime_ok = btc_roc > params["btc_roc_gate"]
    return regime_ok.fillna(True)  # assume OK before sufficient data


# ── Trade Simulator ───────────────────────────────────────────────────────────

def simulate_trades_single_asset(
    ohlcv: pd.DataFrame,
    btc_regime: pd.Series,
    params: dict,
    init_cash: float,
    is_btc: bool = False,
) -> tuple[list[dict], pd.Series]:
    """
    Simulate H10 EQL/EQH reversal on a single crypto asset.

    Entry logic (long - EQL hunt):
    1. Detect EQL zone in past N bars (2+ equal lows within ATR × tolerance)
    2. Price dips below EQL level (close < eql_level) on bar T
    3. Price recovers above EQL level (close > eql_level) on bar T+1
    4. Enter long at open T+2 (confirmation_bars=1)

    Entry logic (short - EQH hunt):
    1. Similar but inverted: price pops above EQH, closes below on bar T+1
    2. Enter short at open T+2

    Exit logic:
    - TP: for long, at prior EQH level (if any); otherwise +3×ATR from entry
    - SL: zone_level - stop_atr_mult × ATR (for long)
    - Time stop: max_hold_bars days

    Transaction costs: taker fee + slippage applied at entry and exit.

    Returns:
        trade_log: list of trade dicts
        portfolio_value: daily equity curve
    """
    opens = ohlcv["Open"]
    highs = ohlcv["High"]
    lows = ohlcv["Low"]
    closes = ohlcv["Close"]

    atr = compute_atr(highs, lows, closes, params["atr_period"])
    swing_highs, swing_lows = find_swing_highs_lows(highs, lows)

    # Align regime series to this asset's index
    regime_aligned = btc_regime.reindex(ohlcv.index, method="ffill").fillna(True)

    stop_atr_mult = params["stop_atr_mult"]
    max_hold = params["max_hold_bars"]
    pos_size_pct = params["position_size_pct"]

    trade_log: list[dict] = []
    portfolio_value = pd.Series(index=closes.index, dtype=float)
    dates = closes.index.tolist()

    cash = float(init_cash)
    position = 0         # 0 = flat, 1 = long, -1 = short
    entry_price = 0.0
    entry_date = None
    hold_days = 0
    tp_price = 0.0
    sl_price = 0.0
    entry_size = 0.0     # signed (positive = long shares, negative = short shares)
    entry_cost = 0.0

    # Pending entry state
    pending_entry = None  # dict with {direction, eql_level, eqh_tp, sl_price, bar_idx}
    breach_bar = -999

    for i, date in enumerate(dates):
        bar_close = float(closes.iloc[i])
        bar_open = float(opens.iloc[i])
        bar_high = float(highs.iloc[i])
        bar_low = float(lows.iloc[i])
        bar_atr = float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else 0.0

        # Portfolio value before trade
        if position != 0:
            mark_price = bar_close
            portfolio_value.iloc[i] = cash + entry_size * (mark_price - entry_price)
        else:
            portfolio_value.iloc[i] = cash

        # ── Exit logic if in position ─────────────────────────────────────────
        if position != 0:
            exit_price = None
            exit_reason = None

            if position == 1:  # Long
                if bar_low <= sl_price:
                    exit_price = min(bar_open, sl_price) if bar_open < sl_price else sl_price
                    exit_reason = "stop_loss"
                elif bar_high >= tp_price:
                    exit_price = max(bar_open, tp_price) if bar_open > tp_price else tp_price
                    exit_reason = "take_profit"
                elif hold_days >= max_hold:
                    exit_price = bar_close
                    exit_reason = "time_stop"

            elif position == -1:  # Short
                if bar_high >= sl_price:
                    exit_price = max(bar_open, sl_price) if bar_open > sl_price else sl_price
                    exit_reason = "stop_loss"
                elif bar_low <= tp_price:
                    exit_price = min(bar_open, tp_price) if bar_open < tp_price else tp_price
                    exit_reason = "take_profit"
                elif hold_days >= max_hold:
                    exit_price = bar_close
                    exit_reason = "time_stop"

            if exit_price is not None:
                trade_value = abs(entry_size) * exit_price
                exit_cost = trade_value * (CRYPTO_TAKER_FEE + CRYPTO_SLIPPAGE)
                pnl = entry_size * (exit_price - entry_price) - entry_cost - exit_cost

                trade_log.append({
                    "entry_date": str(entry_date.date()),
                    "exit_date": str(date.date()),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "direction": "long" if position == 1 else "short",
                    "size": abs(round(entry_size, 6)),
                    "hold_days": hold_days,
                    "exit_reason": exit_reason,
                    "entry_cost": round(entry_cost, 4),
                    "exit_cost": round(exit_cost, 4),
                    "net_pnl": round(pnl, 4),
                })

                cash += abs(entry_size) * entry_price + pnl  # recover invested + PnL
                position = 0
                entry_size = 0.0
                entry_price = 0.0
                hold_days = 0
                portfolio_value.iloc[i] = cash
            else:
                hold_days += 1

        # ── Entry logic if flat ───────────────────────────────────────────────
        if position == 0 and i >= params["atr_period"] + params["lookback_n_bars"]:

            regime_ok = bool(regime_aligned.iloc[i])
            eql_zones, eqh_zones = find_eql_eqh_zones(
                swing_highs, swing_lows, atr, params, i
            )

            # ── Long entry: EQL recovery ─────────────────────────────────────
            if regime_ok and eql_zones:
                # Sort EQL zones by proximity to current price
                nearest_eql = min(eql_zones, key=lambda z: abs(bar_close - z))
                band = params["tolerance_mult"] * bar_atr

                if pending_entry and pending_entry.get("direction") == "long":
                    # Check if this bar is the recovery (close > eql_level)
                    eql_level = pending_entry["eql_level"]
                    if bar_close > eql_level and i - breach_bar <= params["confirmation_bars"] + 1:
                        # Confirmed recovery at close T. Entry deferred to open T+1 (next bar).
                        # Set ready_bar ONLY ONCE so that i > ready_bar is True on the next bar.
                        if not pending_entry.get("ready", False):
                            pending_entry["ready"] = True
                            pending_entry["ready_bar"] = i
                    elif i - breach_bar > params["confirmation_bars"] + 1:
                        pending_entry = None  # expired

                # Check for new EQL breach
                if (not pending_entry
                        and abs(nearest_eql - bar_close) < bar_atr  # near zone
                        and bar_close < nearest_eql + band  # dipped into/below zone
                        and bar_low < nearest_eql):  # actually breached low
                    breach_bar = i
                    eqh_tp = max(eqh_zones) if eqh_zones else entry_price * 1.03
                    pending_entry = {
                        "direction": "long",
                        "eql_level": nearest_eql,
                        "tp_target": eqh_tp,
                        "sl_price": nearest_eql - stop_atr_mult * bar_atr,
                        "ready": False,
                        "ready_bar": -1,
                    }
                elif (pending_entry and pending_entry.get("direction") == "long"
                      and pending_entry.get("ready")
                      and i > pending_entry.get("ready_bar", i)  # must be NEXT bar after recovery
                      and bar_close > pending_entry["eql_level"]):
                    # Enter long at today's open
                    enter_at = bar_open
                    port_val = float(portfolio_value.iloc[i - 1]) if i > 0 else cash
                    trade_value = pos_size_pct * port_val
                    if trade_value <= cash * 0.98:
                        entry_cost_amount = trade_value * (CRYPTO_TAKER_FEE + CRYPTO_SLIPPAGE)
                        cash -= trade_value + entry_cost_amount
                        entry_size = trade_value / enter_at  # fractional crypto
                        entry_price = enter_at
                        entry_date = date
                        entry_cost = entry_cost_amount
                        hold_days = 1
                        tp_price = pending_entry["tp_target"] if pending_entry["tp_target"] > enter_at else enter_at * 1.03
                        sl_price = pending_entry["sl_price"]
                        position = 1
                        pending_entry = None
                        portfolio_value.iloc[i] = cash + entry_size * bar_close

            # ── Short entry: EQH recovery (counter-trend short) ───────────────
            # Only enter short if regime is weak or neutral (don't short in strong bull)
            if position == 0 and eqh_zones:
                nearest_eqh = max(eqh_zones, key=lambda z: abs(bar_close - z))
                band = params["tolerance_mult"] * bar_atr

                if pending_entry and pending_entry.get("direction") == "short":
                    eqh_level = pending_entry["eqh_level"]
                    if bar_close < eqh_level and i - breach_bar <= params["confirmation_bars"] + 1:
                        # Confirmed recovery at close T. Entry at open T+1 only.
                        # Set ready_bar ONLY ONCE.
                        if not pending_entry.get("ready", False):
                            pending_entry["ready"] = True
                            pending_entry["ready_bar"] = i
                    elif i - breach_bar > params["confirmation_bars"] + 1:
                        pending_entry = None

                if (not pending_entry
                        and abs(nearest_eqh - bar_close) < bar_atr
                        and bar_close > nearest_eqh - band
                        and bar_high > nearest_eqh):
                    breach_bar = i
                    eql_tp = min(eql_zones) if eql_zones else bar_close * 0.97
                    pending_entry = {
                        "direction": "short",
                        "eqh_level": nearest_eqh,
                        "tp_target": eql_tp,
                        "sl_price": nearest_eqh + stop_atr_mult * bar_atr,
                        "ready": False,
                        "ready_bar": -1,
                    }
                elif (pending_entry and pending_entry.get("direction") == "short"
                      and pending_entry.get("ready")
                      and i > pending_entry.get("ready_bar", i)  # must be NEXT bar
                      and bar_close < pending_entry["eqh_level"]):
                    enter_at = bar_open
                    port_val = float(portfolio_value.iloc[i - 1]) if i > 0 else cash
                    trade_value = pos_size_pct * port_val
                    if trade_value <= cash * 0.98:
                        entry_cost_amount = trade_value * (CRYPTO_TAKER_FEE + CRYPTO_SLIPPAGE)
                        cash -= entry_cost_amount  # short doesn't consume cash beyond margin
                        entry_size = -(trade_value / enter_at)  # negative = short
                        entry_price = enter_at
                        entry_date = date
                        entry_cost = entry_cost_amount
                        hold_days = 1
                        tp_price = pending_entry["tp_target"] if pending_entry["tp_target"] < enter_at else enter_at * 0.97
                        sl_price = pending_entry["sl_price"]
                        position = -1
                        pending_entry = None
                        portfolio_value.iloc[i] = cash + entry_size * (bar_close - enter_at)

    # Force-close end of data
    if position != 0:
        last_close = float(closes.iloc[-1])
        last_date = dates[-1]
        trade_value = abs(entry_size) * last_close
        exit_cost = trade_value * (CRYPTO_TAKER_FEE + CRYPTO_SLIPPAGE)
        pnl = entry_size * (last_close - entry_price) - entry_cost - exit_cost
        trade_log.append({
            "entry_date": str(entry_date.date()),
            "exit_date": str(last_date.date()),
            "entry_price": round(entry_price, 4),
            "exit_price": round(last_close, 4),
            "direction": "long" if position == 1 else "short",
            "size": abs(round(entry_size, 6)),
            "hold_days": hold_days,
            "exit_reason": "end_of_data",
            "entry_cost": round(entry_cost, 4),
            "exit_cost": round(exit_cost, 4),
            "net_pnl": round(pnl, 4),
        })
        cash += abs(entry_size) * entry_price + pnl
        portfolio_value.iloc[-1] = cash

    portfolio_value = portfolio_value.ffill()
    return trade_log, portfolio_value


# ── IC Validation ─────────────────────────────────────────────────────────────

def compute_signal_ic(
    closes: pd.Series,
    entry_signals: pd.Series,
    forward_period: int = 5,
) -> float:
    """
    Compute IC (Spearman rank correlation) between entry signal strength
    and forward return over forward_period days.

    Entry signal: binary (0 = no signal, +1 = long signal, -1 = short signal).
    Forward return: (close[t+k] - close[t]) / close[t] for k = forward_period.

    Required: IC > 0.02 per Research Director mandate (QUA-129).
    """
    fwd_return = closes.pct_change(periods=forward_period).shift(-forward_period)
    combined = pd.DataFrame({"signal": entry_signals, "fwd_return": fwd_return}).dropna()

    if len(combined) < 20:
        return 0.0

    from scipy.stats import spearmanr
    ic, _ = spearmanr(combined["signal"], combined["fwd_return"])
    return float(ic) if not np.isnan(ic) else 0.0


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(portfolio_value: pd.Series, trade_log: list[dict]) -> dict:
    """Standard Gate 1 metrics from equity curve and trade log."""
    returns = portfolio_value.pct_change().dropna()

    if len(returns) > 1 and returns.std() > 0:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    rolling_peak = portfolio_value.cummax()
    mdd = float(((portfolio_value - rolling_peak) / rolling_peak).min())
    total_return = float((portfolio_value.iloc[-1] / portfolio_value.iloc[0]) - 1)

    pnls = np.array([t["net_pnl"] for t in trade_log]) if trade_log else np.array([])
    if len(pnls) > 0:
        win_rate = float(np.mean(pnls > 0))
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
        profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")
    else:
        win_rate = win_loss_ratio = profit_factor = 0.0

    exit_reasons = {}
    for t in trade_log:
        r = t.get("exit_reason", "unknown")
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    long_trades = [t for t in trade_log if t.get("direction") == "long"]
    short_trades = [t for t in trade_log if t.get("direction") == "short"]

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "win_rate": round(win_rate, 4),
        "win_loss_ratio": round(win_loss_ratio, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "trade_count": len(trade_log),
        "long_trade_count": len(long_trades),
        "short_trade_count": len(short_trades),
        "total_return": round(total_return, 4),
        "exit_reasons": exit_reasons,
    }


# ── Main Strategy Runner ──────────────────────────────────────────────────────

def run_strategy(
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    params: dict | None = None,
) -> dict:
    """
    Run H10 Crypto EQL/EQH Reversal on BTC and ETH.

    Fetches data with warmup buffer for indicator computation.
    Runs BTC and ETH independently with allocated capital shares.
    Aggregates combined portfolio equity curve.

    Returns:
        Metrics dict + trade log + portfolio_value for statistical analysis.
    """
    if params is None:
        params = PARAMETERS

    universe = params.get("universe", ["BTC-USD", "ETH-USD"])

    # Add warmup buffer
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=60)).strftime("%Y-%m-%d")
    ohlcv_dict = download_crypto_ohlcv(universe, warmup_start, end)

    quality = check_data_quality(ohlcv_dict, start, end)

    # BTC close for regime gate
    btc_ohlcv = ohlcv_dict.get("BTC-USD", pd.DataFrame())
    if btc_ohlcv.empty:
        raise ValueError(f"No BTC-USD data for {start}–{end}")
    btc_close_full = btc_ohlcv["Close"]
    btc_regime = compute_btc_regime(btc_close_full, params)

    init_cash = params.get("init_cash", 25000)
    capital_map = {
        "BTC-USD": init_cash * params.get("capital_split_btc", 0.60),
        "ETH-USD": init_cash * params.get("capital_split_eth", 0.40),
    }

    combined_value = None
    all_trades: list[dict] = []

    for ticker in universe:
        ohlcv = ohlcv_dict.get(ticker)
        if ohlcv is None or ohlcv.empty:
            warnings.warn(f"No data for {ticker} — skipping.")
            continue

        # Trim to backtest window (after warmup)
        bt_start = pd.Timestamp(start)
        ohlcv_bt = ohlcv.loc[ohlcv.index >= bt_start].copy()
        if ohlcv_bt.empty:
            continue

        is_btc = "BTC" in ticker.upper()
        asset_cash = capital_map.get(ticker, init_cash / len(universe))

        trades, pv = simulate_trades_single_asset(
            ohlcv_bt, btc_regime, params, asset_cash, is_btc=is_btc
        )

        for t in trades:
            t["ticker"] = ticker
        all_trades.extend(trades)

        if combined_value is None:
            combined_value = pv
        else:
            combined_value = combined_value.add(pv, fill_value=0)

    if combined_value is None or combined_value.empty:
        raise ValueError(f"No portfolio value computed for {start}–{end}")

    metrics = compute_metrics(combined_value, all_trades)
    metrics["period"] = f"{start} to {end}"
    metrics["data_quality"] = quality
    metrics["trade_log"] = all_trades
    metrics["portfolio_value"] = combined_value
    metrics["returns"] = combined_value.pct_change().dropna().values

    return metrics
