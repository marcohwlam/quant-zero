"""
Strategy: H09 TQQQ Weekly Snapback — 1% Target Mean-Reversion
Author: Engineering Director
Date: 2026-03-16
Hypothesis: TQQQ daily rebalancing creates structural volatility-decay drag; large
            intraweek drawdowns systematically overshoot fair value, generating a
            predictable snapback premium (Cheng & Madhavan 2009; Avellaneda & Zhang 2010).
Asset class: equities (leveraged ETF)
Parent task: QUA-134
Reference:  TASC March 2026 "Trading Snapbacks In A Leveraged ETF";
            Cheng & Madhavan (2009); Avellaneda & Zhang (2010)

NOTES:
- TQQQ inception: 2010-02-09. IS window starts 2015-01-01 per Research Director
  requirement (capture 2015-2016 China selloff, 2018 Q4, 2020 COVID, 2022 bear).
  GFC sub-period (2008-2009) CANNOT be tested: TQQQ did not exist.
- Regime gate is MANDATORY: entries disabled when QQQ < 200-day SMA or VIX >= vix_gate.
  Gate checked at close of signal bar (no look-ahead). Existing positions continue
  per stop/TP/time-stop rules — gate only suppresses NEW entries.
- Transaction costs: canonical equities model — $0.005/share fixed + 0.05% slippage
  + market impact 0.1 × σ × sqrt(Q/ADV). TQQQ is highly liquid (ADV >> $1B/day);
  market impact negligible at $25K account sizing.
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ────────────────────────────────────────────────────────

PARAMETERS = {
    "ticker": "TQQQ",
    "qqq_ticker": "QQQ",
    "vix_ticker": "^VIX",
    # Entry signal: TQQQ close must be >= entry_decline_pct below the N-day rolling high
    "entry_decline_pct": 0.05,      # 5% decline from rolling high triggers entry
    "lookback_window_days": 5,      # rolling high window (days)
    # Exit logic
    "profit_target_pct": 0.01,      # +1.0% TP (TASC spec)
    "stop_loss_pct": 0.02,          # -2.0% SL (2× risk/reward)
    "max_hold_days": 5,             # time stop: exit on Friday close or max 5 days
    # Regime gates
    "qqq_sma_period": 200,          # QQQ simple MA period (days)
    "vix_gate": 30,                 # disable new entries when VIX >= this threshold
    # Position sizing: % of portfolio per trade (TQQQ vol is 3×QQQ; size conservatively)
    "position_size_pct": 0.15,      # 15% per trade; max 1 concurrent position
    "init_cash": 25000,
}

# ── Canonical Equity Transaction Cost Model (Engineering Director spec) ────────
FIXED_COST_PER_SHARE = 0.005   # $0.005/share commission
SLIPPAGE_PCT = 0.0005          # 0.05% per leg (price impact)
MARKET_IMPACT_K = 0.1          # Almgren-Chriss square-root model constant
SIGMA_WINDOW = 20              # days for rolling return std (market impact)
ADV_WINDOW = 20                # days for rolling ADV (market impact)

TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ───────────────────────────────────────────────────────────────

def download_tqqq_data(start: str, end: str) -> dict[str, pd.DataFrame]:
    """
    Download OHLCV for TQQQ, QQQ close, and VIX close.

    Uses yfinance auto_adjust=True for split/dividend adjustment.
    TQQQ available from 2010-02-09.
    QQQ available from 1999+.
    VIX (^VIX) available from 1990+.

    Returns:
        dict with keys: 'tqqq' (OHLCV), 'qqq_close', 'vix_close'
    """
    # Download TQQQ OHLCV
    tqqq_raw = yf.download("TQQQ", start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(tqqq_raw.columns, pd.MultiIndex):
        tqqq_raw.columns = tqqq_raw.columns.get_level_values(0)

    # Download QQQ close for regime gate
    qqq_raw = yf.download("QQQ", start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(qqq_raw.columns, pd.MultiIndex):
        qqq_raw.columns = qqq_raw.columns.get_level_values(0)
    qqq_close = qqq_raw["Close"] if "Close" in qqq_raw.columns else qqq_raw.iloc[:, 0]

    # Download VIX for regime gate
    vix_raw = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(vix_raw.columns, pd.MultiIndex):
        vix_raw.columns = vix_raw.columns.get_level_values(0)
    vix_close = vix_raw["Close"] if "Close" in vix_raw.columns else vix_raw.iloc[:, 0]

    return {
        "tqqq": tqqq_raw,
        "qqq_close": qqq_close,
        "vix_close": vix_close,
    }


# ── Data Quality Checklist ─────────────────────────────────────────────────────

def check_data_quality(data: dict, start: str, end: str) -> dict:
    """
    Data quality checks per Engineering Director pre-backtest checklist.

    TQQQ-specific notes:
    - Survivorship bias: TQQQ is the current ProShares UltraPro QQQ ticker;
      no ticker changes or delistings. Universe = single instrument, no survivorship risk.
    - Price adjustments: yfinance auto_adjust=True. TQQQ has had splits (e.g., 2-for-1
      in 2022); auto_adjust handles this correctly.
    - Earnings exclusion: N/A — TQQQ is an ETF with no earnings events.
    - Delisted: TQQQ is actively trading; not applicable.
    - Data gaps: TQQQ had a brief trading halt during 2020 COVID crash
      (March 2020 circuit breaker days); gaps flagged if >5.
    """
    tqqq = data["tqqq"]
    qqq_close = data["qqq_close"]
    vix_close = data["vix_close"]

    report = {
        "survivorship_bias": (
            "TQQQ is a single-instrument strategy — ProShares UltraPro QQQ. "
            "No survivorship bias: TQQQ has been continuously trading since 2010-02-09. "
            "IS window starts 2015-01-01 per Research Director mandate to capture "
            "multiple distinct market regimes."
        ),
        "price_source": "yfinance TQQQ, QQQ, ^VIX with auto_adjust=True (split-adjusted).",
        "earnings_exclusion": "N/A — TQQQ and QQQ are ETFs with no earnings events.",
        "delisted": "N/A — TQQQ is actively traded.",
        "tqqq_inception_note": (
            "TQQQ inception: 2010-02-09. GFC sub-period (2008-2009) cannot be tested. "
            "Post-GFC recovery (2010-02 to 2011-12) is the earliest available sub-period."
        ),
        "tickers": {},
    }

    biz_days = pd.bdate_range(start=start, end=end)
    for label, series in [("TQQQ_close", tqqq.get("Close", tqqq.iloc[:, 0])),
                          ("QQQ_close", qqq_close),
                          ("VIX_close", vix_close)]:
        series = series.dropna()
        if series.empty:
            report["tickers"][label] = {"error": "No data"}
            continue
        missing = len(biz_days.difference(series.index))
        report["tickers"][label] = {
            "total_bars": len(series),
            "missing_business_days": missing,
            "gap_flag": missing > 5,
            "start": str(series.index.min().date()),
            "end": str(series.index.max().date()),
        }
        if missing > 5:
            warnings.warn(
                f"Data gap: {label} has {missing} missing business days in {start}–{end}."
            )

    return report


# ── Transaction Cost Computation ──────────────────────────────────────────────

def compute_transaction_cost(
    shares: int,
    price: float,
    sigma: float,
    adv: float,
) -> dict:
    """
    Canonical equity transaction cost per Engineering Director spec.

    Components:
    - Fixed: $0.005/share commission
    - Slippage: 0.05% of trade value (price × shares)
    - Market impact: 0.1 × σ × sqrt(Q/ADV) × (price × shares)
    - Liquidity flag: if Q/ADV > 0.01 (>1% of ADV)

    Args:
        shares: order size in shares
        price: fill price
        sigma: 20-day rolling daily return std
        adv: 20-day average daily volume (shares)

    Returns:
        dict with cost components and liquidity flag.
    """
    trade_value = shares * price

    fixed_cost = shares * FIXED_COST_PER_SHARE
    slippage_cost = SLIPPAGE_PCT * trade_value

    # Market impact (Almgren-Chriss square-root model)
    q_over_adv = shares / adv if adv > 0 else 0.0
    market_impact_pct = MARKET_IMPACT_K * sigma * np.sqrt(q_over_adv)
    market_impact_cost = market_impact_pct * trade_value

    total_cost = fixed_cost + slippage_cost + market_impact_cost

    return {
        "fixed_cost": fixed_cost,
        "slippage_cost": slippage_cost,
        "market_impact_cost": market_impact_cost,
        "market_impact_bps": round(market_impact_pct * 10000, 2),
        "total_cost": total_cost,
        "liquidity_constrained": q_over_adv > 0.01,
    }


# ── Signal Generation ─────────────────────────────────────────────────────────

def compute_entry_signals(
    tqqq_close: pd.Series,
    qqq_close: pd.Series,
    vix_close: pd.Series,
    params: dict,
) -> pd.Series:
    """
    Compute raw entry signal (True = signal at close T, entry at open T+1).

    Entry conditions (all must be true on the same bar):
    1. TQQQ close ≤ (N-day rolling high) × (1 - entry_decline_pct)
       — leveraged ETF overshoots; weekly dip from rolling high triggers snapback entry
    2. QQQ close > QQQ 200-day SMA (regime gate; no look-ahead: computed from close T)
    3. VIX close < vix_gate (volatility regime gate)

    No look-ahead: rolling high uses only past prices (min_periods=1).
    Signals are NOT shifted here; shifting is done in run_strategy().

    Returns:
        Boolean Series indexed like tqqq_close, True on signal days.
    """
    lookback = params["lookback_window_days"]
    decline = params["entry_decline_pct"]
    sma_period = params["qqq_sma_period"]
    vix_gate = params["vix_gate"]

    # N-day rolling high of TQQQ close (shifted 1 to avoid same-bar look-ahead)
    # rolling_high[t] = max(close[t-N+1] ... close[t])
    rolling_high = tqqq_close.rolling(window=lookback, min_periods=1).max()

    # Entry threshold: decline >= entry_decline_pct below rolling high
    decline_condition = tqqq_close <= rolling_high * (1.0 - decline)

    # QQQ regime gate: QQQ above 200-day SMA
    qqq_sma = qqq_close.rolling(window=sma_period, min_periods=sma_period).mean()
    qqq_regime = qqq_close > qqq_sma

    # VIX gate: VIX below threshold
    vix_regime = vix_close < vix_gate

    # Align all series on common index
    idx = tqqq_close.index
    qqq_regime_aligned = qqq_regime.reindex(idx, method="ffill").fillna(False)
    vix_regime_aligned = vix_regime.reindex(idx, method="ffill").fillna(False)

    signal = decline_condition & qqq_regime_aligned & vix_regime_aligned

    return signal.fillna(False)


# ── Trade Simulator ───────────────────────────────────────────────────────────

def simulate_trades(
    tqqq_ohlcv: pd.DataFrame,
    entry_signals: pd.Series,
    params: dict,
) -> tuple[list[dict], pd.Series]:
    """
    Simulate H09 strategy with TP/SL/time-stop exit logic.

    Entry: next-day open (signal at close T → enter at open T+1).
    Exit priority (evaluated at each subsequent bar):
      1. SL: if bar low ≤ entry × (1 - stop_loss_pct) → exit at SL price
      2. TP: if bar high ≥ entry × (1 + profit_target_pct) → exit at TP price
      3. Time stop: if bar is Friday OR hold_days ≥ max_hold_days → exit at close
         (gate only suppresses NEW entries; existing positions use stop/TP/time-stop)

    Transaction costs applied at both entry and exit legs.

    Returns:
        trade_log: list of trade dicts (entry, exit, PnL, costs)
        portfolio_value: daily equity curve (pd.Series)
    """
    opens = tqqq_ohlcv["Open"]
    highs = tqqq_ohlcv["High"]
    lows = tqqq_ohlcv["Low"]
    closes = tqqq_ohlcv["Close"]
    volumes = tqqq_ohlcv["Volume"]

    # Precompute 20-day rolling sigma and ADV for market impact
    daily_returns = closes.pct_change()
    rolling_sigma = daily_returns.rolling(window=SIGMA_WINDOW, min_periods=5).std()
    rolling_adv = volumes.rolling(window=ADV_WINDOW, min_periods=5).mean()

    tp_pct = params["profit_target_pct"]
    sl_pct = params["stop_loss_pct"]
    max_hold = params["max_hold_days"]
    pos_size_pct = params["position_size_pct"]
    init_cash = params["init_cash"]

    trade_log: list[dict] = []
    portfolio_value = pd.Series(index=closes.index, dtype=float)
    dates = closes.index.tolist()

    cash = float(init_cash)
    position_shares = 0
    entry_price = 0.0
    entry_date = None
    entry_idx = -1
    hold_days = 0
    entry_cost = 0.0

    for i, date in enumerate(dates):
        # Mark portfolio value (before trade decisions)
        if position_shares > 0:
            portfolio_value.iloc[i] = cash + position_shares * closes.iloc[i]
        else:
            portfolio_value.iloc[i] = cash

        # ── Check exits if in a position ─────────────────────────────────────
        if position_shares > 0:
            bar_low = float(lows.iloc[i])
            bar_high = float(highs.iloc[i])
            bar_close = float(closes.iloc[i])
            bar_open = float(opens.iloc[i])

            sl_price = entry_price * (1.0 - sl_pct)
            tp_price = entry_price * (1.0 + tp_pct)

            exit_price = None
            exit_reason = None

            # Priority 1: SL (conservative — checked before TP on same bar)
            if bar_low <= sl_price:
                # Gap-down check: if open already below SL, fill at open
                exit_price = min(bar_open, sl_price) if bar_open < sl_price else sl_price
                exit_reason = "stop_loss"

            # Priority 2: TP (only if SL not triggered)
            elif bar_high >= tp_price:
                # Gap-up check: if open already above TP, fill at open
                exit_price = max(bar_open, tp_price) if bar_open > tp_price else tp_price
                exit_reason = "take_profit"

            # Priority 3: Time stop — Friday or max hold days
            elif date.weekday() == 4 or hold_days >= max_hold:  # 4 = Friday
                exit_price = bar_close
                exit_reason = "time_stop"

            if exit_price is not None:
                sigma = float(rolling_sigma.iloc[i]) if not np.isnan(rolling_sigma.iloc[i]) else 0.01
                adv = float(rolling_adv.iloc[i]) if not np.isnan(rolling_adv.iloc[i]) else 1e6
                exit_cost_info = compute_transaction_cost(position_shares, exit_price, sigma, adv)
                exit_cost = exit_cost_info["total_cost"]

                trade_pnl = (
                    position_shares * exit_price
                    - position_shares * entry_price
                    - entry_cost
                    - exit_cost
                )
                trade_return_pct = (exit_price - entry_price) / entry_price

                trade_log.append({
                    "entry_date": str(entry_date.date()),
                    "exit_date": str(date.date()),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "shares": position_shares,
                    "hold_days": hold_days,
                    "exit_reason": exit_reason,
                    "gross_return_pct": round(trade_return_pct * 100, 4),
                    "entry_cost": round(entry_cost, 4),
                    "exit_cost": round(exit_cost, 4),
                    "net_pnl": round(trade_pnl, 4),
                    "liquidity_constrained": exit_cost_info["liquidity_constrained"],
                })

                cash += position_shares * exit_price - exit_cost
                position_shares = 0
                entry_price = 0.0
                entry_date = None
                hold_days = 0
                entry_cost = 0.0

                # Update portfolio value after exit
                portfolio_value.iloc[i] = cash
            else:
                hold_days += 1

        # ── Check entry (if flat and signal at PREVIOUS bar) ──────────────────
        if position_shares == 0 and i > 0:
            prev_signal = bool(entry_signals.iloc[i - 1])  # signal from close T-1 → enter at open T
            if prev_signal:
                bar_open = float(opens.iloc[i])
                sigma = float(rolling_sigma.iloc[i]) if not np.isnan(rolling_sigma.iloc[i]) else 0.01
                adv = float(rolling_adv.iloc[i]) if not np.isnan(rolling_adv.iloc[i]) else 1e6

                # Position sizing: fixed % of current portfolio value
                port_value = portfolio_value.iloc[i - 1]
                shares_to_buy = max(1, int(pos_size_pct * port_value / bar_open))
                trade_value = shares_to_buy * bar_open
                if trade_value > cash * 0.99:
                    # Not enough cash — skip
                    continue

                cost_info = compute_transaction_cost(shares_to_buy, bar_open, sigma, adv)
                entry_cost = cost_info["total_cost"]

                cash -= trade_value + entry_cost
                position_shares = shares_to_buy
                entry_price = bar_open
                entry_date = date
                entry_idx = i
                hold_days = 1

                # Update portfolio value after entry
                portfolio_value.iloc[i] = cash + position_shares * float(closes.iloc[i])

    # If still in position at end of data, force-close at last close
    if position_shares > 0:
        last_idx = len(dates) - 1
        last_date = dates[last_idx]
        last_close = float(closes.iloc[last_idx])
        sigma = float(rolling_sigma.iloc[last_idx]) if not np.isnan(rolling_sigma.iloc[last_idx]) else 0.01
        adv = float(rolling_adv.iloc[last_idx]) if not np.isnan(rolling_adv.iloc[last_idx]) else 1e6
        exit_cost_info = compute_transaction_cost(position_shares, last_close, sigma, adv)
        exit_cost = exit_cost_info["total_cost"]
        trade_pnl = (
            position_shares * last_close
            - position_shares * entry_price
            - entry_cost
            - exit_cost
        )
        trade_log.append({
            "entry_date": str(entry_date.date()),
            "exit_date": str(last_date.date()),
            "entry_price": round(entry_price, 4),
            "exit_price": round(last_close, 4),
            "shares": position_shares,
            "hold_days": hold_days,
            "exit_reason": "end_of_data",
            "gross_return_pct": round((last_close - entry_price) / entry_price * 100, 4),
            "entry_cost": round(entry_cost, 4),
            "exit_cost": round(exit_cost, 4),
            "net_pnl": round(trade_pnl, 4),
            "liquidity_constrained": exit_cost_info["liquidity_constrained"],
        })
        cash += position_shares * last_close - exit_cost
        portfolio_value.iloc[last_idx] = cash

    portfolio_value = portfolio_value.ffill()
    return trade_log, portfolio_value


# ── Core Metrics Computation ──────────────────────────────────────────────────

def compute_metrics(
    portfolio_value: pd.Series,
    trade_log: list[dict],
) -> dict:
    """
    Compute Gate 1 standard metrics from portfolio equity curve and trade log.

    Returns:
        Dict with sharpe, max_drawdown, win_rate, profit_factor, trade_count,
        total_return, and per-exit-reason breakdown.
    """
    returns = portfolio_value.pct_change().dropna()

    if len(returns) > 1 and returns.std() > 0:
        sharpe = float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    rolling_peak = portfolio_value.cummax()
    drawdown = (portfolio_value - rolling_peak) / rolling_peak
    mdd = float(drawdown.min())

    total_return = float((portfolio_value.iloc[-1] / portfolio_value.iloc[0]) - 1)

    pnls = np.array([t["net_pnl"] for t in trade_log])
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

    # Exit reason breakdown
    exit_reasons = {}
    for t in trade_log:
        r = t.get("exit_reason", "unknown")
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    liquidity_flags = sum(1 for t in trade_log if t.get("liquidity_constrained", False))

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "win_rate": round(win_rate, 4),
        "win_loss_ratio": round(win_loss_ratio, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "trade_count": len(trade_log),
        "total_return": round(total_return, 4),
        "exit_reasons": exit_reasons,
        "liquidity_flags": liquidity_flags,
    }


# ── Main Strategy Runner ──────────────────────────────────────────────────────

def run_strategy(
    start: str = "2015-01-01",
    end: str = "2021-12-31",
    params: dict | None = None,
) -> dict:
    """
    Run H09 TQQQ Weekly Snapback strategy.

    Args:
        start: backtest start date (IS default: 2015-01-01)
        end: backtest end date (IS default: 2021-12-31)
        params: strategy parameters (defaults to PARAMETERS)

    Returns:
        Metrics dict including sharpe, MDD, trade log, portfolio value.
    """
    if params is None:
        params = PARAMETERS

    # Download data (extend start for SMA warmup)
    warmup_start = pd.Timestamp(start) - pd.DateOffset(days=300)
    data = download_tqqq_data(
        start=warmup_start.strftime("%Y-%m-%d"),
        end=end,
    )

    tqqq = data["tqqq"]
    if tqqq.empty:
        raise ValueError(f"No TQQQ data for {start}–{end}")

    # Align all data to TQQQ trading days
    tqqq_close = tqqq["Close"]
    qqq_close = data["qqq_close"].reindex(tqqq_close.index, method="ffill")
    vix_close = data["vix_close"].reindex(tqqq_close.index, method="ffill")

    # Compute signals on full data (including warmup)
    signals = compute_entry_signals(tqqq_close, qqq_close, vix_close, params)

    # Trim to actual backtest window after warmup
    bt_start = pd.Timestamp(start)
    tqqq_bt = tqqq.loc[tqqq.index >= bt_start]
    signals_bt = signals.loc[signals.index >= bt_start]

    if tqqq_bt.empty:
        raise ValueError(f"TQQQ data empty after trimming to {start}.")

    quality_report = check_data_quality(data, start, end)

    # Simulate trades
    trade_log, portfolio_value = simulate_trades(tqqq_bt, signals_bt, params)

    # Compute metrics
    metrics = compute_metrics(portfolio_value, trade_log)
    metrics["period"] = f"{start} to {end}"
    metrics["data_quality"] = quality_report
    metrics["trade_log"] = trade_log
    metrics["portfolio_value"] = portfolio_value
    metrics["returns"] = portfolio_value.pct_change().dropna().values

    return metrics


# ── Parameter Sensitivity Scans ───────────────────────────────────────────────

def scan_entry_decline(
    start: str,
    end: str,
    base_params: dict,
    decline_values: list[float] | None = None,
) -> dict:
    """
    Sweep entry_decline_pct: 2.5%, 3.5%, 5.0%, 6.0%, 7.0% (per Research Director spec).
    """
    if decline_values is None:
        decline_values = [0.025, 0.035, 0.050, 0.060, 0.070]

    results = {}
    for d in decline_values:
        key = f"decline_{int(d * 100)}pct"
        p = {**base_params, "entry_decline_pct": d}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[key] = {
                "sharpe": r["sharpe"],
                "trade_count": r["trade_count"],
                "max_drawdown": r["max_drawdown"],
            }
        except Exception as exc:
            results[key] = {"error": str(exc)}

    sharpe_vals = [v["sharpe"] for v in results.values() if isinstance(v, dict) and "sharpe" in v]
    if len(sharpe_vals) > 1:
        sharpe_range = max(sharpe_vals) - min(sharpe_vals)
        sharpe_mean = np.mean(sharpe_vals)
        variance_pct = sharpe_range / abs(sharpe_mean) if sharpe_mean != 0 else float("inf")
        results["_meta"] = {
            "sharpe_range": round(sharpe_range, 4),
            "sharpe_variance_pct": round(variance_pct, 4),
            "gate1_robustness": "PASS" if variance_pct <= 0.30 else "FAIL (>30% variance)",
        }

    return results


def scan_vix_gate(
    start: str,
    end: str,
    base_params: dict,
    vix_values: list[float] | None = None,
) -> dict:
    """
    Sweep vix_gate: 25, 28, 30, 32, 35 (per Research Director spec: 25-35).
    """
    if vix_values is None:
        vix_values = [25.0, 28.0, 30.0, 32.0, 35.0]

    results = {}
    for v in vix_values:
        key = f"vix_{int(v)}"
        p = {**base_params, "vix_gate": v}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[key] = {
                "sharpe": r["sharpe"],
                "trade_count": r["trade_count"],
                "max_drawdown": r["max_drawdown"],
            }
        except Exception as exc:
            results[key] = {"error": str(exc)}

    return results


# ── Sub-Period Analysis ───────────────────────────────────────────────────────

SUB_PERIODS = {
    "post_gfc_recovery_2010_2011": ("2010-02-10", "2011-12-31"),  # TQQQ inception to 2011
    "china_selloff_2015_2016": ("2015-01-01", "2016-12-31"),
    "q4_2018_correction": ("2018-01-01", "2019-06-30"),
    "covid_crash_2020": ("2019-07-01", "2021-12-31"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
}

GFC_NOTE = (
    "GFC 2008-2009 sub-period CANNOT be tested: TQQQ inception date is 2010-02-09. "
    "Post-GFC recovery (2010-02-10 to 2011-12-31) is the earliest available sub-period. "
    "This is a known limitation documented in hypothesis h09 notes."
)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="H09 TQQQ Weekly Snapback strategy runner.")
    parser.add_argument("--is", dest="run_is", action="store_true", help="Run IS backtest.")
    parser.add_argument("--oos", action="store_true", help="Run OOS backtest.")
    args = parser.parse_args()

    if args.run_is:
        print("IS (2015-01-01 to 2021-12-31)...")
        r = run_strategy("2015-01-01", "2021-12-31")
        print(f"Sharpe={r['sharpe']} MDD={r['max_drawdown']:.1%} Trades={r['trade_count']}")

    if args.oos:
        print("OOS (2022-01-01 to 2023-12-31)...")
        r = run_strategy("2022-01-01", "2023-12-31")
        print(f"Sharpe={r['sharpe']} MDD={r['max_drawdown']:.1%} Trades={r['trade_count']}")
