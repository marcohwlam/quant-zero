"""
Strategy: H24 Combined IBS Mean Reversion + Turn-of-Month Calendar
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: Two decorrelated signal streams targeting combined IS Sharpe 1.0–1.3 via
            diversification benefit.
            Signal 1 (50% capital): IBS mean reversion on SPY — enter when IBS < 0.25
            and SPY is above its 200-SMA; exit on IBS > 0.75, 1.5×ATR stop, or 3-day
            time stop.
            Signal 2 (50% capital): Turn-of-Month calendar on SPY/QQQ/IWM — enter on
            Day -2 from month-end (VIX ≤ 30 filter); exit on Day +3 of following month.
            Independent capital pools prevent over-leveraging; concurrent positions are
            handled naturally by the separate leg structure (max 100% combined exposure).
Asset class: equities
Parent task: QUA-226
References: H21 (IBS); H22 (TOM); Connors & Alvarez (2009); McConnell & Xu (2008);
            Lakonishok & Smidt (1988)
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
# All 6 free parameters exposed here; 3 additional are fixed at canonical defaults.
PARAMETERS = {
    # IBS signal (free parameters)
    "ibs_ticker": "SPY",
    "ibs_entry_threshold": 0.25,    # IBS < threshold → entry (oversold close)
    "ibs_exit_threshold": 0.75,     # IBS > threshold → take-profit exit
    "max_hold_days": 3,             # IBS time stop (trading days); free param
    # TOM signal (free parameters)
    "tom_tickers": ["SPY", "QQQ", "IWM"],
    "vix_ticker": "^VIX",
    "tom_entry_day": -2,            # 2nd-to-last trading day of month; free param
    "tom_exit_day": 3,              # 3rd trading day of following month; free param
    "vix_threshold": 30.0,          # VIX filter ceiling; free param
    # Fixed at canonical defaults — not varied in sensitivity testing
    "stop_atr_mult": 1.5,           # ATR stop multiplier (fixed)
    "atr_period": 14,               # ATR lookback (fixed)
    "sma_regime_period": 200,       # SMA regime filter period (fixed)
    # Capital allocation
    "ibs_alloc": 0.50,              # 50% of portfolio to IBS leg
    "tom_alloc": 0.50,              # 50% of portfolio to TOM leg
    "init_cash": 25000,
}

# ── Transaction Cost Constants ─────────────────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005   # $0.005/share fixed
SLIPPAGE_PCT = 0.0005          # 0.05% slippage
MARKET_IMPACT_K = 0.1          # institutional square-root impact coefficient
SIGMA_WINDOW = 20              # 20-day rolling vol for market impact
ADV_WINDOW = 20                # 20-day rolling ADV for market impact

TRADING_DAYS_PER_YEAR = 252


# ── Data Helpers ────────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(
    spy_ticker: str,
    tom_tickers: list,
    vix_ticker: str,
    start: str,
    end: str,
) -> dict:
    """
    Download all required market data with extra warmup for SMA(200)/ATR(14).

    Returns a dict keyed by ticker (OHLCV DataFrames) plus 'vix' (Close Series).
    Raises ValueError if any ticker returns insufficient or structurally invalid data.
    """
    # Extra calendar days to cover 200-day SMA warm-up (×1.5 for weekends/holidays)
    warmup_days = 200 + 30
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=int(warmup_days * 1.5))
    ).strftime("%Y-%m-%d")

    data = {}
    all_tickers = list({spy_ticker} | set(tom_tickers))
    for tkr in all_tickers:
        df = _download_single(tkr, warmup_start, end)
        required = {"Open", "High", "Low", "Close", "Volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns for {tkr}: {missing}")
        if len(df) < 50:
            raise ValueError(f"Insufficient data for {tkr}: {len(df)} bars")
        na_count = int(df["Close"].isna().sum())
        if na_count > 5:
            warnings.warn(f"{tkr}: {na_count} missing trading days detected")
        data[tkr] = df

    # VIX: Close only — used only as daily regime filter
    vix_raw = _download_single(vix_ticker, warmup_start, end)
    if "Close" not in vix_raw.columns:
        raise ValueError(f"Missing Close for {vix_ticker}")
    data["vix"] = vix_raw["Close"].rename("vix")

    return data


# ── IBS Indicator Computation ──────────────────────────────────────────────────

def compute_ibs_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute IBS, ATR (Wilder EWM), and 200-SMA regime filter on SPY OHLCV.

    IBS = (Close - Low) / (High - Low); falls back to 0.5 on flat bars (H == L)
          to prevent division by zero on trading halts or auction-only bars.
    ATR = EWM True Range with span=atr_period (Wilder smoothing; adjust=False).
    regime_up = Close > SMA(sma_regime_period): enter IBS only in uptrending market.
    """
    atr_period = params["atr_period"]
    sma_period = params["sma_regime_period"]

    hl_range = df["High"] - df["Low"]
    ibs = np.where(hl_range > 0, (df["Close"] - df["Low"]) / hl_range, 0.5)

    df = df.copy()
    df["ibs"] = ibs

    # True Range: max(H-L, |H-prev_C|, |L-prev_C|)
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=atr_period, adjust=False).mean()

    df["sma_regime"] = df["Close"].rolling(sma_period).mean()
    df["regime_up"] = df["Close"] > df["sma_regime"]

    return df


# ── TOM Window Computation ─────────────────────────────────────────────────────

def compute_tom_windows(dates: pd.DatetimeIndex, params: dict) -> tuple:
    """
    Identify TOM entry and exit dates from a full set of trading dates.

    entry_day = -2 → 2nd-to-last trading day of each calendar month
    exit_day  = +3 → 3rd trading day of the following calendar month

    Negative entry_day uses Python-style indexing into the sorted month day list:
    index = n + entry_day (e.g., n=21, entry_day=-2 → index 19 = 20th day, 2nd-to-last).

    Returns:
        tom_entry_set:  set of Timestamp entry dates (VIX filter applied in sim loop)
        entry_to_exit:  dict mapping entry_date Timestamp → exit_date Timestamp
    """
    entry_day = params["tom_entry_day"]   # e.g., -2
    exit_day = params["tom_exit_day"]     # e.g., 3

    df_dates = pd.DataFrame({"date": dates})
    df_dates["ym"] = df_dates["date"].dt.to_period("M")

    months = sorted(df_dates["ym"].unique())
    month_to_days = {
        ym: sorted(df_dates[df_dates["ym"] == ym]["date"].tolist())
        for ym in months
    }

    tom_entry_set = set()
    entry_to_exit = {}

    for i, ym in enumerate(months):
        month_days = month_to_days[ym]
        n = len(month_days)

        # Resolve entry index: negative = relative to end; positive = from start (1-based)
        entry_idx = n + entry_day if entry_day < 0 else entry_day - 1
        if not (0 <= entry_idx < n):
            continue
        entry_date = month_days[entry_idx]

        # Resolve exit from the NEXT month
        if i + 1 >= len(months):
            continue
        next_ym = months[i + 1]
        next_days = month_to_days[next_ym]
        # exit_day=+3 → index 2 (0-based: Day+1 = index 0, Day+2 = index 1, Day+3 = index 2)
        exit_idx = exit_day - 1
        if not (0 <= exit_idx < len(next_days)):
            continue
        exit_date = next_days[exit_idx]

        tom_entry_set.add(entry_date)
        entry_to_exit[entry_date] = exit_date

    return tom_entry_set, entry_to_exit


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    price: float,
    shares: int,
    df: pd.DataFrame,
    idx: int,
) -> tuple:
    """
    Canonical equities transaction cost (Engineering Director spec):
      fixed = $0.005/share
      slippage = 0.05% of notional
      market_impact = k × σ × sqrt(Q / ADV) × notional  (square-root model)

    Flags orders where Q/ADV > 1% as liquidity-constrained and emits a warning.
    Returns (total_cost_dollars, liquidity_constrained_bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = df["Close"].pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = df["Volume"].rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000

    # Square-root market impact (Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV)"
        )

    return fixed + slippage + impact, liq_constrained


# ── IBS Leg Simulator ──────────────────────────────────────────────────────────

def simulate_ibs_leg(df: pd.DataFrame, capital: float, params: dict) -> tuple:
    """
    Simulate the IBS mean reversion leg on SPY.

    Entry (at close of bar i, no look-ahead):
        IBS < ibs_entry_threshold AND regime_up AND not in position

    Exit (checked on subsequent bars, priority order):
        1. IBS > ibs_exit_threshold → IBS take-profit
        2. Close < entry_price - stop_atr_mult × atr_at_entry → ATR stop
        3. hold_days >= max_hold_days → time stop

    capital is the IBS leg allocation (50% of total portfolio).
    Returns (trade_log list, equity pd.Series indexed like df).
    """
    ibs_entry = params["ibs_entry_threshold"]
    ibs_exit = params["ibs_exit_threshold"]
    max_hold = params["max_hold_days"]
    stop_mult = params["stop_atr_mult"]

    n = len(df)
    idx = df.index
    trade_log = []
    equity = pd.Series(np.nan, index=idx, dtype=float)
    equity.iloc[0] = capital

    in_pos = False
    entry_price = 0.0
    atr_at_entry = 0.0
    entry_idx = -1
    entry_shares = 0
    entry_cost = 0.0
    hold_days = 0
    entry_liq = False

    for i in range(1, n):
        close_i = float(df["Close"].iloc[i])

        if not in_pos:
            ibs_i = float(df["ibs"].iloc[i])
            regime_i = bool(df["regime_up"].iloc[i])
            atr_i = float(df["atr"].iloc[i])

            if (ibs_i < ibs_entry
                    and regime_i
                    and not pd.isna(atr_i) and atr_i > 0):
                ep = close_i
                if ep <= 0:
                    equity.iloc[i] = capital
                    continue
                # Invest full IBS leg capital in SPY
                shares = int(capital / ep)
                if shares <= 0:
                    equity.iloc[i] = capital
                    continue

                cost, liq = _transaction_cost(ep, shares, df, i)
                eff_ep = ep + cost / shares   # effective entry price (cost included)
                capital -= eff_ep * shares

                in_pos = True
                entry_price = eff_ep
                atr_at_entry = atr_i
                entry_idx = i
                entry_shares = shares
                entry_cost = cost
                hold_days = 0
                entry_liq = liq

        else:
            hold_days += 1
            ibs_i = float(df["ibs"].iloc[i])
            exit_reason = None

            if ibs_i > ibs_exit:
                exit_reason = "IBS_TP"
            elif close_i < (entry_price - stop_mult * atr_at_entry):
                exit_reason = "ATR_STOP"
            elif hold_days >= max_hold:
                exit_reason = "TIME_STOP"

            if exit_reason:
                xcost, xliq = _transaction_cost(close_i, entry_shares, df, i)
                eff_xp = close_i - xcost / entry_shares
                pnl = (eff_xp - entry_price) * entry_shares
                capital += eff_xp * entry_shares

                trade_log.append({
                    "leg": "IBS",
                    "ticker": params["ibs_ticker"],
                    "entry_date": idx[entry_idx].date(),
                    "exit_date": idx[i].date(),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(eff_xp, 4),
                    "shares": entry_shares,
                    "pnl": round(pnl, 2),
                    "cost": round(entry_cost + xcost, 4),
                    "liquidity_constrained": entry_liq or xliq,
                    "hold_days": hold_days,
                    "exit_reason": exit_reason,
                })
                in_pos = False
                hold_days = 0

        equity.iloc[i] = capital + (entry_shares * close_i if in_pos else 0.0)

    # Force close any open position at end of data
    if in_pos and n > 0:
        i = n - 1
        xp = float(df["Close"].iloc[i])
        xcost, xliq = _transaction_cost(xp, entry_shares, df, i)
        eff_xp = xp - xcost / entry_shares
        pnl = (eff_xp - entry_price) * entry_shares
        capital += eff_xp * entry_shares
        equity.iloc[i] = capital
        trade_log.append({
            "leg": "IBS",
            "ticker": params["ibs_ticker"],
            "entry_date": idx[entry_idx].date(),
            "exit_date": idx[i].date(),
            "entry_price": round(entry_price, 4),
            "exit_price": round(eff_xp, 4),
            "shares": entry_shares,
            "pnl": round(pnl, 2),
            "cost": round(entry_cost + xcost, 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_days": n - 1 - entry_idx,
            "exit_reason": "END_OF_DATA",
        })

    equity = equity.ffill().fillna(float(capital))
    return trade_log, equity


# ── TOM Leg Simulator ──────────────────────────────────────────────────────────

def simulate_tom_leg(
    tom_prices: dict,
    tom_volumes: dict,
    vix: pd.Series,
    capital: float,
    tom_entry_set: set,
    entry_to_exit: dict,
    params: dict,
) -> tuple:
    """
    Simulate the TOM calendar leg on SPY/QQQ/IWM.

    Entry: On date in tom_entry_set, if VIX close ≤ vix_threshold.
           Capital is split equally across all 3 ETFs (~1/3 each, ~17% of total portfolio).

    Exit: At close on the precomputed exit date (Day +3 of next month).
          Uses >= comparison so exit fires on first trading day >= exit_date (handles
          non-trading-day edge cases gracefully).

    tom_prices: {ticker: pd.Series of Close prices, aligned to common DatetimeIndex}
    tom_volumes: {ticker: pd.Series of Volume, aligned to same index}

    Returns (trade_log list, equity pd.Series indexed by tom_prices common index).
    """
    tickers = params["tom_tickers"]
    n_assets = len(tickers)
    vix_thresh = params["vix_threshold"]

    # Build aligned price and volume DataFrames from the common-indexed Series
    price_df = pd.DataFrame({t: tom_prices[t] for t in tickers})
    vol_df = pd.DataFrame({t: tom_volumes[t] for t in tickers})
    dates = price_df.index
    n = len(dates)

    trade_log = []
    equity = pd.Series(np.nan, index=dates, dtype=float)
    equity.iloc[0] = capital

    in_pos = False
    entry_date_key = None
    exit_date = None
    entry_prices = {}
    entry_shares_map = {}
    entry_costs = {}
    entry_liq_map = {}

    for i in range(1, n):
        date = dates[i]

        if not in_pos:
            if date in tom_entry_set:
                vix_today = float(vix.reindex([date]).iloc[0]) if date in vix.index else np.nan
                if pd.isna(vix_today) or vix_today > vix_thresh:
                    # VIX filter: skip this TOM window
                    equity.iloc[i] = capital
                    continue

                # Enter all 3 ETFs with equal capital allocation
                alloc_per_asset = capital / n_assets
                entry_prices = {}
                entry_shares_map = {}
                entry_costs = {}
                entry_liq_map = {}
                total_committed = 0.0
                valid_entry = True

                for tkr in tickers:
                    ep = float(price_df[tkr].iloc[i])
                    if ep <= 0 or pd.isna(ep):
                        valid_entry = False
                        break
                    shares = int(alloc_per_asset / ep)
                    if shares <= 0:
                        valid_entry = False
                        break

                    # Build per-ticker DataFrame for cost model (needs Close + Volume)
                    tkr_df = pd.DataFrame({
                        "Close": price_df[tkr].values,
                        "Volume": vol_df[tkr].values,
                    })
                    cost, liq = _transaction_cost(ep, shares, tkr_df, i)
                    eff_ep = ep + cost / shares
                    entry_prices[tkr] = eff_ep
                    entry_shares_map[tkr] = shares
                    entry_costs[tkr] = cost
                    entry_liq_map[tkr] = liq
                    total_committed += eff_ep * shares

                if not valid_entry:
                    equity.iloc[i] = capital
                    continue

                capital -= total_committed
                in_pos = True
                entry_date_key = date
                exit_date = entry_to_exit.get(date)

        else:
            # Exit when we reach or pass the scheduled exit date
            should_exit = (exit_date is not None and date >= exit_date)

            if should_exit:
                total_proceeds = 0.0
                for tkr in tickers:
                    xp = float(price_df[tkr].iloc[i])
                    if pd.isna(xp) or xp <= 0:
                        xp = entry_prices[tkr]   # fallback: exit at entry price (zero P&L)
                    shares = entry_shares_map[tkr]
                    tkr_df = pd.DataFrame({
                        "Close": price_df[tkr].values,
                        "Volume": vol_df[tkr].values,
                    })
                    xcost, xliq = _transaction_cost(xp, shares, tkr_df, i)
                    eff_xp = xp - xcost / shares
                    pnl = (eff_xp - entry_prices[tkr]) * shares
                    total_proceeds += eff_xp * shares

                    # Calendar days held (actual calendar distance, not trading days)
                    hold_cal = (date - entry_date_key).days

                    entry_dt = (
                        entry_date_key.date()
                        if hasattr(entry_date_key, "date")
                        else entry_date_key
                    )
                    exit_dt = date.date() if hasattr(date, "date") else date

                    trade_log.append({
                        "leg": "TOM",
                        "ticker": tkr,
                        "entry_date": entry_dt,
                        "exit_date": exit_dt,
                        "entry_price": round(entry_prices[tkr], 4),
                        "exit_price": round(eff_xp, 4),
                        "shares": shares,
                        "pnl": round(pnl, 2),
                        "cost": round(entry_costs[tkr] + xcost, 4),
                        "liquidity_constrained": entry_liq_map[tkr] or xliq,
                        "hold_days": hold_cal,
                        "exit_reason": "TOM_CALENDAR",
                    })

                capital += total_proceeds
                in_pos = False
                entry_date_key = None
                exit_date = None

        # Mark-to-market equity for this bar
        if in_pos:
            mtm = capital + sum(
                float(price_df[t].iloc[i]) * entry_shares_map[t]
                for t in tickers
            )
        else:
            mtm = capital
        equity.iloc[i] = mtm

    # Force close any open position at end of data
    if in_pos and n > 0:
        i = n - 1
        date = dates[i]
        total_proceeds = 0.0
        for tkr in tickers:
            xp = float(price_df[tkr].iloc[i])
            if pd.isna(xp) or xp <= 0:
                xp = entry_prices[tkr]
            shares = entry_shares_map[tkr]
            tkr_df = pd.DataFrame({
                "Close": price_df[tkr].values,
                "Volume": vol_df[tkr].values,
            })
            xcost, xliq = _transaction_cost(xp, shares, tkr_df, i)
            eff_xp = xp - xcost / shares
            pnl = (eff_xp - entry_prices[tkr]) * shares
            total_proceeds += eff_xp * shares

            entry_dt = (
                entry_date_key.date() if hasattr(entry_date_key, "date") else entry_date_key
            )
            exit_dt = date.date() if hasattr(date, "date") else date
            trade_log.append({
                "leg": "TOM",
                "ticker": tkr,
                "entry_date": entry_dt,
                "exit_date": exit_dt,
                "entry_price": round(entry_prices[tkr], 4),
                "exit_price": round(eff_xp, 4),
                "shares": shares,
                "pnl": round(pnl, 2),
                "cost": round(entry_costs[tkr] + xcost, 4),
                "liquidity_constrained": entry_liq_map[tkr] or xliq,
                "hold_days": (date - entry_date_key).days,
                "exit_reason": "END_OF_DATA",
            })

        capital += total_proceeds
        equity.iloc[i] = capital

    equity = equity.ffill().fillna(float(capital))
    return trade_log, equity


# ── Main Backtest Entry Point ───────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download data, simulate H24 combined IBS+TOM strategy, return standardised dict.

    The two legs run independently with separate capital pools (50/50 split).
    Their equity curves are combined by summing on a shared DatetimeIndex.
    Concurrent signal handling (when both legs are invested simultaneously) is
    inherent to the separate capital pool design — no special overlap logic required.

    Returns:
        {
            "returns": pd.Series,       daily portfolio returns (combined)
            "trades": pd.DataFrame,     per-trade log for both legs
            "equity": pd.Series,        combined equity curve
            "ibs_equity": pd.Series,    IBS leg equity curve only
            "tom_equity": pd.Series,    TOM leg equity curve only
            "params": dict,
            "data_quality": dict,
            "sharpe": float,
            "max_drawdown": float,
            "total_return": float,
            "win_rate": float,
            "trade_count": int,
            "trades_per_year": float,
            "pf1_status": str,
            "ibs_trade_count": int,
            "tom_trade_count": int,
        }
    """
    if params is None:
        params = PARAMETERS.copy()

    spy_tkr = params["ibs_ticker"]
    tom_tkrs = params["tom_tickers"]
    vix_tkr = params["vix_ticker"]
    init_cash = float(params["init_cash"])
    ibs_alloc = params["ibs_alloc"]
    tom_alloc = params["tom_alloc"]

    # 1. Download all data (with warmup for SMA/ATR indicators)
    data = download_data(spy_tkr, tom_tkrs, vix_tkr, start, end)

    # 2. Compute IBS indicators on SPY (use full warmup data for correct SMA/ATR)
    spy_df_full = compute_ibs_indicators(data[spy_tkr], params)

    # 3. Trim all data to the requested backtest start date
    ts = pd.Timestamp(start)
    spy_df = spy_df_full.loc[spy_df_full.index >= ts].copy()

    tom_prices = {t: data[t]["Close"].loc[data[t].index >= ts] for t in tom_tkrs}
    tom_volumes = {t: data[t]["Volume"].loc[data[t].index >= ts] for t in tom_tkrs}
    vix_close = data["vix"].loc[data["vix"].index >= ts]

    # Align all TOM data to a common trading calendar (intersection of all tickers + VIX)
    tom_common_idx = tom_prices[tom_tkrs[0]].index
    for t in tom_tkrs[1:]:
        tom_common_idx = tom_common_idx.intersection(tom_prices[t].index)
    tom_common_idx = tom_common_idx.intersection(vix_close.index)

    for t in tom_tkrs:
        tom_prices[t] = tom_prices[t].reindex(tom_common_idx)
        tom_volumes[t] = tom_volumes[t].reindex(tom_common_idx)
    vix_close = vix_close.reindex(tom_common_idx)

    if len(spy_df) < 10:
        raise ValueError(
            f"Insufficient IBS data after trimming to {start}–{end}: {len(spy_df)} bars"
        )
    if len(tom_common_idx) < 10:
        raise ValueError(
            f"Insufficient TOM data after alignment to {start}–{end}: "
            f"{len(tom_common_idx)} bars"
        )

    # 4. Compute TOM windows from the aligned trading calendar
    tom_entry_set, entry_to_exit = compute_tom_windows(tom_common_idx, params)

    # 5. Simulate IBS leg (uses 50% of total portfolio capital)
    ibs_capital = init_cash * ibs_alloc
    ibs_trades, ibs_equity = simulate_ibs_leg(spy_df, ibs_capital, params)

    # 6. Simulate TOM leg (uses remaining 50% of total portfolio capital)
    tom_capital = init_cash * tom_alloc
    tom_trades, tom_equity = simulate_tom_leg(
        tom_prices, tom_volumes, vix_close,
        tom_capital, tom_entry_set, entry_to_exit, params,
    )

    # 7. Combine equity curves on union index (forward-fill gaps between legs)
    combined_idx = spy_df.index.union(tom_common_idx).sort_values()
    ibs_eq_aligned = ibs_equity.reindex(combined_idx).ffill().fillna(ibs_capital)
    tom_eq_aligned = tom_equity.reindex(combined_idx).ffill().fillna(tom_capital)
    total_equity = ibs_eq_aligned + tom_eq_aligned
    daily_returns = total_equity.pct_change().fillna(0.0)

    # 8. Build combined trade log and compute summary metrics
    all_trades_list = ibs_trades + tom_trades
    all_trades = (
        pd.DataFrame(all_trades_list)
        if all_trades_list
        else pd.DataFrame(columns=[
            "leg", "ticker", "entry_date", "exit_date",
            "entry_price", "exit_price", "shares", "pnl",
            "cost", "liquidity_constrained", "hold_days", "exit_reason",
        ])
    )

    n_trades = len(all_trades)
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
        win_rate = round(float((all_trades["pnl"] > 0).mean()), 4)

    pf1_status = "PASS" if trades_per_year >= 30 else f"WARN: {trades_per_year:.1f}/yr < 30"
    ibs_trade_count = len(ibs_trades)
    tom_trade_count = len(tom_trades)

    print(
        f"\nH24 Combined IBS+TOM Backtest ({start} to {end}):\n"
        f"  IBS trades: {ibs_trade_count} | TOM trades: {tom_trade_count} "
        f"| Total: {n_trades} ({trades_per_year}/yr) — PF-1: {pf1_status}\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%}\n"
        f"  IBS alloc: {ibs_alloc:.0%} (SPY only) | "
        f"TOM alloc: {tom_alloc:.0%} (SPY/QQQ/IWM equal) | "
        f"Init cash: ${init_cash:,.0f}"
    )

    if trades_per_year < 30:
        warnings.warn(f"PF-1 WARN: {trades_per_year:.1f} trades/yr < 30 threshold")

    return {
        "returns": daily_returns,
        "trades": all_trades,
        "equity": total_equity,
        "ibs_equity": ibs_equity,
        "tom_equity": tom_equity,
        "params": params,
        "data_quality": {
            "survivorship_bias_flag": (
                "SPY/QQQ/IWM/^VIX are market ETFs — no survivorship bias"
            ),
            "price_adjusted": True,    # yfinance auto_adjust=True
            "gap_flags": [],
            "earnings_exclusion": "N/A — ETF universe, no single-stock event risk",
            "delisted_tickers": "N/A — all ongoing market ETFs",
        },
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "pf1_status": pf1_status,
        "ibs_trade_count": ibs_trade_count,
        "tom_trade_count": tom_trade_count,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(ticker: str, start: str, end: str, params: dict = None) -> dict:
    """
    Thin wrapper for orchestrator compatibility (run_strategy(ticker, start, end) API).
    `ticker` is ignored — H24 uses a fixed universe (SPY for IBS; SPY/QQQ/IWM for TOM).
    """
    p = (params or PARAMETERS).copy()
    return run_backtest(start, end, p)


if __name__ == "__main__":
    result = run_backtest("2018-01-01", "2023-12-31")
    print(f"\nSample trades (first 5 rows):")
    if not result["trades"].empty:
        print(result["trades"].head().to_string(index=False))
    print(f"\nIBS leg equity final: ${result['ibs_equity'].iloc[-1]:,.2f}")
    print(f"TOM leg equity final: ${result['tom_equity'].iloc[-1]:,.2f}")
    print(f"Combined equity final: ${result['equity'].iloc[-1]:,.2f}")
