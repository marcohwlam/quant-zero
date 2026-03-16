"""
Strategy: H21 IBS SPY Mean Reversion
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: IBS (Internal Bar Strength) daily mean reversion on SPY/QQQ.
            When the close is near the day's low (low IBS), intraday selling
            pressure has been absorbed and a short-term reversal is likely.
            200-SMA regime filter restricts entries to uptrending markets.
Asset class: equities
Parent task: QUA-216
References: Connors & Alvarez (2009); QuantifiedStrategies.com IBS study
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────

PARAMETERS = {
    "ticker": "SPY",
    "ibs_entry_threshold": 0.25,
    "ibs_exit_threshold": 0.75,
    "max_hold_days": 3,
    "stop_atr_mult": 1.5,
    "atr_period": 14,
    "sma_regime_period": 200,
    "position_size_pct": 0.95,   # near-full investment when in position (single ETF)
    "init_cash": 25000,
}

# ── Transaction Cost Constants ─────────────────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_PCT = 0.0005        # 0.05%
MARKET_IMPACT_K = 0.1
SIGMA_WINDOW = 20
ADV_WINDOW = 20

TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ───────────────────────────────────────────────────────────────

def download_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Download OHLCV data using yfinance with auto_adjust=True.
    Raises ValueError if data is insufficient or missing required columns.
    """
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Missing columns for {ticker}: {missing}")

    if raw.empty or len(raw) < 50:
        raise ValueError(f"Insufficient data for {ticker}: {len(raw)} bars")

    # Flag tickers with > 5 missing trading days (NaN in Close after ffill check)
    na_count = raw["Close"].isna().sum()
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing trading days detected")

    return raw


# ── Indicator Computation ─────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute IBS, ATR (Wilder smoothing via EWM), and 200-SMA regime filter.

    IBS = (Close - Low) / (High - Low)
    ATR = EWM of True Range with span=atr_period (Wilder smoothing approximation)
    SMA regime = Close > SMA(sma_regime_period)
    """
    atr_period = params["atr_period"]
    sma_period = params["sma_regime_period"]

    # IBS: 0 = close at day's low (oversold intraday), 1 = close at day's high
    hl_range = df["High"] - df["Low"]
    # Avoid division by zero on flat bars (e.g. trading halts)
    ibs = np.where(hl_range > 0, (df["Close"] - df["Low"]) / hl_range, 0.5)
    df = df.copy()
    df["ibs"] = ibs

    # True Range for ATR
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder smoothing: equivalent to EWM with span = atr_period (adjust=False)
    df["atr"] = tr.ewm(span=atr_period, adjust=False).mean()

    # 200-day SMA regime filter (only enter in uptrending market)
    df["sma_regime"] = df["Close"].rolling(sma_period).mean()
    df["regime_up"] = df["Close"] > df["sma_regime"]

    return df


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def compute_transaction_cost(
    price: float,
    shares: int,
    df: pd.DataFrame,
    idx: int,
) -> tuple:
    """
    Canonical equities transaction cost model (Engineering Director spec).

    Components:
    - Fixed: $0.005/share
    - Slippage: 0.05% of notional
    - Market impact: k × σ × sqrt(Q / ADV) × notional  (square-root impact model)

    Returns (total_cost, liquidity_constrained_flag).
    Flags orders where Q/ADV > 1% as liquidity-constrained.
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = df["Close"].pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = df["Volume"].rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1e6

    # Square-root market impact (Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liquidity_constrained = bool(shares / adv > 0.01)

    if liquidity_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares/adv:.2%} of ADV)"
        )

    total_cost = fixed + slippage + impact
    return total_cost, liquidity_constrained


# ── Trade Simulator ────────────────────────────────────────────────────────────

def simulate_trades(df: pd.DataFrame, params: dict) -> tuple:
    """
    Simulate H21 IBS mean reversion strategy (long-only, single position).

    Entry rule (no look-ahead):
    - Signal and entry at the CLOSE of bar i
    - Conditions at bar i: IBS < ibs_entry_threshold AND regime_up AND not in_position

    Exit rules (checked from bar i+1 onward):
    1. IBS TP: IBS > ibs_exit_threshold → exit at close
    2. ATR stop: close < (entry_price - stop_atr_mult × atr_at_entry) → exit at close
    3. Time stop: hold_days >= max_hold_days → exit at close

    Returns (trade_log list, daily_returns Series, equity_curve Series).
    """
    ibs_entry = params["ibs_entry_threshold"]
    ibs_exit = params["ibs_exit_threshold"]
    max_hold = params["max_hold_days"]
    stop_mult = params["stop_atr_mult"]
    pos_size = params["position_size_pct"]
    init_cash = params["init_cash"]

    n = len(df)
    idx = df.index

    trade_log = []
    equity = pd.Series(np.nan, index=idx, dtype=float)
    capital = float(init_cash)
    equity.iloc[0] = capital

    in_position = False
    entry_price = 0.0
    atr_at_entry = 0.0
    entry_idx = -1
    entry_shares = 0
    entry_cost = 0.0
    hold_days = 0
    entry_liquidity = False

    for i in range(1, n):
        close_i = float(df["Close"].iloc[i])

        if not in_position:
            # Check entry signal at bar i
            ibs_i = float(df["ibs"].iloc[i])
            regime_i = bool(df["regime_up"].iloc[i])
            atr_i = float(df["atr"].iloc[i])

            # Entry conditions: IBS oversold + uptrend regime + valid ATR
            if (ibs_i < ibs_entry
                    and regime_i
                    and not pd.isna(atr_i)
                    and atr_i > 0):
                # Enter at close of bar i
                entry_p = close_i
                if entry_p <= 0:
                    equity.iloc[i] = capital
                    continue

                trade_value = capital * pos_size
                shares = int(trade_value / entry_p)
                if shares <= 0:
                    equity.iloc[i] = capital
                    continue

                cost, liq_flag = compute_transaction_cost(entry_p, shares, df, i)
                # Effective entry price includes cost per share
                eff_entry = entry_p + cost / shares

                in_position = True
                entry_price = eff_entry
                atr_at_entry = atr_i
                entry_idx = i
                entry_shares = shares
                entry_cost = cost
                entry_liquidity = liq_flag
                hold_days = 0

                # Capital committed (shares bought at eff_entry)
                capital -= eff_entry * shares

        else:
            # Position is open: check exit conditions
            hold_days += 1
            ibs_i = float(df["ibs"].iloc[i])
            exit_reason = None

            # Priority 1: IBS take profit
            if ibs_i > ibs_exit:
                exit_reason = "IBS_TP"
            # Priority 2: ATR-based stop loss
            elif close_i < (entry_price - stop_mult * atr_at_entry):
                exit_reason = "ATR_STOP"
            # Priority 3: time stop
            elif hold_days >= max_hold:
                exit_reason = "TIME_STOP"

            if exit_reason:
                # Exit at close of bar i
                exit_p = close_i
                exit_cost, exit_liq = compute_transaction_cost(exit_p, entry_shares, df, i)
                eff_exit = exit_p - exit_cost / entry_shares

                gross_pnl = (eff_exit - entry_price) * entry_shares
                total_cost = entry_cost + exit_cost

                capital += eff_exit * entry_shares

                trade_log.append({
                    "entry_date": idx[entry_idx].date(),
                    "exit_date": idx[i].date(),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(eff_exit, 4),
                    "shares": entry_shares,
                    "pnl": round(gross_pnl, 2),
                    "cost": round(total_cost, 4),
                    "liquidity_constrained": entry_liquidity or exit_liq,
                    "hold_days": hold_days,
                    "exit_reason": exit_reason,
                })

                in_position = False
                hold_days = 0

        equity.iloc[i] = capital + (entry_shares * close_i if in_position else 0.0)

    # Force-close any open position at end of data
    if in_position and n > 0:
        i = n - 1
        exit_p = float(df["Close"].iloc[i])
        exit_cost, exit_liq = compute_transaction_cost(exit_p, entry_shares, df, i)
        eff_exit = exit_p - exit_cost / entry_shares
        gross_pnl = (eff_exit - entry_price) * entry_shares
        total_cost = entry_cost + exit_cost
        capital += eff_exit * entry_shares
        equity.iloc[i] = capital

        trade_log.append({
            "entry_date": idx[entry_idx].date(),
            "exit_date": idx[i].date(),
            "entry_price": round(entry_price, 4),
            "exit_price": round(eff_exit, 4),
            "shares": entry_shares,
            "pnl": round(gross_pnl, 2),
            "cost": round(total_cost, 4),
            "liquidity_constrained": entry_liquidity or exit_liq,
            "hold_days": n - 1 - entry_idx,
            "exit_reason": "END_OF_DATA",
        })

    equity = equity.ffill().fillna(float(init_cash))
    daily_returns = equity.pct_change().fillna(0.0)

    return trade_log, daily_returns, equity


# ── Main Backtest Entry Point ───────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download data, run H21 IBS mean reversion, and return standardised results dict.

    Returns:
        {
            "returns": pd.Series,          daily portfolio returns
            "trades": pd.DataFrame,        per-trade log
            "equity": pd.Series,           equity curve
            "params": dict,                params used
            "data_quality": dict,          pre-flight data quality flags
        }
    Also prints summary statistics including trade count/yr for PF-1 verification.
    """
    if params is None:
        params = PARAMETERS.copy()

    ticker = params["ticker"]

    # ── Warmup: load extra data for SMA/ATR indicator warm-up ─────────────────
    warmup_days = max(params["sma_regime_period"], params["atr_period"]) + 30
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=int(warmup_days * 1.5))
    ).strftime("%Y-%m-%d")

    df_raw = download_data(ticker, warmup_start, end)

    # ── Data quality checklist ─────────────────────────────────────────────────
    na_days = int(df_raw["Close"].isna().sum())
    gap_flags = [ticker] if na_days > 5 else []
    data_quality = {
        "survivorship_bias_flag": (
            "SPY is current constituent — no survivorship bias (single ETF)"
        ),
        "price_adjusted": True,       # yfinance auto_adjust=True
        "gap_flags": gap_flags,
        "earnings_exclusion": (
            "Not excluded — SPY is ETF, earnings event risk negligible"
        ),
        "delisted_tickers": "N/A — SPY is ongoing",
    }

    # ── Compute indicators (on full warmup data) ───────────────────────────────
    df_indicators = compute_indicators(df_raw, params)

    # ── Trim to requested backtest window ─────────────────────────────────────
    df = df_indicators.loc[df_indicators.index >= pd.Timestamp(start)].copy()
    if len(df) < 10:
        raise ValueError(
            f"Insufficient backtest data after trimming to {start}–{end}: {len(df)} bars"
        )

    # ── Simulate trades ────────────────────────────────────────────────────────
    trade_log, daily_returns, equity = simulate_trades(df, params)

    # ── Build output DataFrame ─────────────────────────────────────────────────
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=[
        "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "cost", "liquidity_constrained", "hold_days", "exit_reason",
    ])

    # ── Summary metrics ────────────────────────────────────────────────────────
    n_trades = len(trades_df)
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    trades_per_year = round(n_trades / max(years, 1e-3), 1)

    ret_arr = daily_returns.values
    sharpe = 0.0
    if ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + ret_arr)
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    win_rate = 0.0
    if n_trades > 0:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)

    # ── PF-1 pre-condition check ───────────────────────────────────────────────
    pf1_status = "PASS" if trades_per_year >= 30 else "FAIL — switch to IBS < 0.30"
    print(
        f"\nH21 IBS Backtest Summary ({start} to {end}):\n"
        f"  Ticker: {ticker}\n"
        f"  Trades total: {n_trades} | Trades/yr: {trades_per_year} "
        f"(PF-1 ≥30/yr: {pf1_status})\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%}\n"
        f"  IBS entry threshold: {params['ibs_entry_threshold']}"
    )

    if trades_per_year < 30:
        warnings.warn(
            f"PF-1 FAIL: {trades_per_year:.1f} trades/yr < 30 at "
            f"ibs_entry_threshold={params['ibs_entry_threshold']}. "
            f"Consider raising threshold to 0.30."
        )

    return {
        "returns": daily_returns,
        "trades": trades_df,
        "equity": equity,
        "params": params,
        "data_quality": data_quality,
        # Convenience summary fields for Backtest Runner
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "pf1_status": pf1_status,
    }


# ── Convenience alias for orchestrator compatibility ───────────────────────────

def run_strategy(ticker: str, start: str, end: str, params: dict = None) -> dict:
    """Thin wrapper so orchestrator can call run_strategy(ticker, start, end)."""
    p = (params or PARAMETERS).copy()
    p["ticker"] = ticker
    return run_backtest(start, end, p)


if __name__ == "__main__":
    result = run_backtest("2010-01-01", "2021-12-31")
    print(f"\nTrade log sample (first 5 trades):")
    if not result["trades"].empty:
        print(result["trades"].head().to_string(index=False))
