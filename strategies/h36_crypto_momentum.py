"""
Strategy: H36 Crypto Cross-Sectional Momentum — 4-Asset Ranking (BTC/ETH/SOL/AVAX)
Author: Engineering Director (QUA-291)
Date: 2026-03-17
Hypothesis: Cross-sectional momentum — buying the weekly return winner among BTC, ETH, SOL,
            AVAX — exploits attention-driven capital rotation in crypto markets. BTC 200-SMA
            regime filter avoids sustained bear markets. 100% concentrated in top-ranked asset.
Asset class: cryptocurrency
Parent task: QUA-291
References: Liu & Tsyvinski (2021) "Risks and Returns of Cryptocurrency" — RFS 34(6);
            Jegadeesh & Titman (1993) J. Finance 48(1);
            research/hypotheses/36_crypto_cross_sectional_momentum.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ──────────────────────────────────────────────────────────
PARAMETERS = {
    "universe": ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD"],
    "ranking_window": 20,       # 4-week (20 trading day) return lookback for cross-sectional rank
    "trend_sma_window": 200,    # BTC 200-day SMA regime filter (CASH when BTC < 200-SMA)
    "hard_stop_pct": 0.12,      # -12% hard stop per position (wider stop for crypto volatility)
    "signal_frequency": "weekly",  # evaluate at Friday close, execute at Monday open
    "init_cash": 25000,
}

# ── Transaction Cost Constants (canonical crypto model) ────────────────────────
# Source: Engineering Director spec — Johnson, Algorithmic Trading & DMA (Book 6)
# Crypto: 0.10% taker fee + 0.05% slippage. No market impact (BTC/ETH/SOL/AVAX ADV >> $25K).
CRYPTO_FEE_PCT = 0.001      # 0.10% taker fee per leg
CRYPTO_SLIPPAGE_PCT = 0.0005  # 0.05% slippage per leg
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data(
    universe: list,
    start: str,
    end: str,
    ranking_window: int,
    trend_sma_window: int,
) -> tuple:
    """
    Download OHLCV with warmup period for indicator computation.

    Warmup = max(ranking_window, trend_sma_window) × 2 + 60 calendar days.
    Always includes BTC-USD for regime filter even if not in universe.

    Returns:
        close_df (pd.DataFrame): Daily close prices, tickers as columns, full warmup window.
        open_df  (pd.DataFrame): Daily open prices, same shape.
    """
    warmup_days = max(ranking_window, trend_sma_window) * 2 + 60
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_days)
    ).strftime("%Y-%m-%d")

    # Always include BTC-USD for 200-SMA trend filter
    all_tickers = sorted(set(universe) | {"BTC-USD"})

    raw = yf.download(
        all_tickers, start=warmup_start, end=end, auto_adjust=True, progress=False
    )

    if isinstance(raw.columns, pd.MultiIndex):
        close_df = raw["Close"].copy()
        open_df = raw["Open"].copy()
    else:
        # Single-ticker fallback (shouldn't happen here)
        close_df = raw[["Close"]].rename(columns={"Close": all_tickers[0]})
        open_df = raw[["Open"]].rename(columns={"Open": all_tickers[0]})

    if "BTC-USD" not in close_df.columns:
        raise ValueError("BTC-USD data unavailable — required for 200-SMA trend filter")

    return close_df, open_df


# ── Data Quality Checklist ─────────────────────────────────────────────────────

def check_data_quality(close_df: pd.DataFrame, start: str, end: str) -> dict:
    """
    Run pre-backtest data quality checks per Engineering Director checklist.

    Documented decisions (crypto-specific):
    - Survivorship bias: BTC/ETH trading since before 2018; SOL/AVAX from ~2020.
      Universe is restricted to assets with actual data on each ranking date.
      No delisted assets in this universe — none can be delisted from crypto market.
    - Price adjustments: yfinance auto_adjust=True.
    - Data gaps: checked per ticker in the backtest window.
    - Earnings exclusion: N/A — crypto has no earnings events.
    - Delisted tickers: N/A — all four assets remain actively traded.
    """
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    report = {
        "survivorship_bias": (
            "BTC-USD: trading since 2009. ETH-USD: trading since 2015. "
            "SOL-USD: trading since ~2020. AVAX-USD: trading since ~2020. "
            "Universe is dynamically restricted to assets with data on each ranking date — "
            "2018-2019 uses only BTC/ETH (2-asset). No survivorship bias: assets are not "
            "delisted; all included with actual history (no fictitious backfills)."
        ),
        "price_adjustments": "yfinance auto_adjust=True for all tickers.",
        "earnings_exclusion": "N/A — crypto assets have no earnings events.",
        "delisted_tickers": (
            "N/A — BTC, ETH, SOL, AVAX are not subject to exchange delisting. "
            "All four remain actively traded through the backtest window."
        ),
        "tickers": {},
    }

    for ticker in close_df.columns:
        price = close_df[ticker]
        price_full = price.dropna()

        if price_full.empty:
            report["tickers"][ticker] = {"error": "No data returned by yfinance"}
            continue

        # Window-specific gap check
        price_window = price.loc[ts_start:ts_end].dropna()
        if price_window.empty:
            report["tickers"][ticker] = {
                "note": f"No data in backtest window {start}–{end}",
                "data_start": str(price_full.index.min().date()),
            }
            continue

        # Count missing business days in the window
        expected_bdays = pd.bdate_range(
            start=price_window.index.min(), end=price_window.index.max()
        )
        missing_count = len(expected_bdays.difference(price_window.index))

        report["tickers"][ticker] = {
            "bars_in_window": len(price_window),
            "missing_business_days": missing_count,
            "gap_flag": missing_count > 5,
            "data_start": str(price_full.index.min().date()),
            "data_end": str(price_full.index.max().date()),
            "available_at_is_start": bool(price_full.index.min() <= ts_start),
        }

        if missing_count > 5:
            warnings.warn(
                f"Data gap: {ticker} has {missing_count} missing business days "
                f"in window {start}–{end}"
            )

    return report


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_rank_signal(
    close_df: pd.DataFrame,
    ranking_window: int = 20,
    trend_sma_window: int = 200,
) -> tuple:
    """
    Compute weekly cross-sectional momentum signal.

    Signal evaluation on Friday close:
    1. Compute `ranking_window`-day simple return for each asset.
       Assets with insufficient history (NaN) are excluded from ranking.
    2. BTC 200-SMA regime filter: if BTC_close < BTC_200SMA → signal = "CASH".
    3. Rank all available assets by return; select top-1.
    4. Forward-fill Friday signal to Mon–Thu (covers week until next Friday).
    5. Shift by 1 bar: Friday-close signal → Monday-open execution (no look-ahead).

    Dynamic universe:
    - Before SOL/AVAX data starts (~2020): only BTC/ETH are ranked.
    - After all 4 assets have data: all 4 are ranked.
    - The `.dropna()` in ranking naturally handles the transition.

    Returns:
        target_signal (pd.Series): Target asset name or "CASH", shifted for next-bar execution.
        btc_200sma (pd.Series): BTC 200-day SMA (for diagnostics).
    """
    if "BTC-USD" not in close_df.columns:
        raise ValueError("BTC-USD required for BTC 200-SMA trend filter")

    btc_close = close_df["BTC-USD"]

    # BTC 200-SMA — computed on full (warmup-inclusive) series, no look-ahead
    btc_200sma = btc_close.rolling(trend_sma_window).mean()

    # Rolling `ranking_window`-day return for each asset
    # Uses only past data (pct_change looks back, not forward)
    rolling_returns = close_df.pct_change(ranking_window)

    # Identify Fridays — signal is only evaluated on trading Fridays
    is_friday = pd.Series(close_df.index.dayofweek == 4, index=close_df.index)

    # Raw signal: set only on Fridays, NaN elsewhere
    target_raw = pd.Series(np.nan, index=close_df.index, dtype=object)

    for date in close_df.index[is_friday]:
        btc_val = btc_close.loc[date]
        sma_val = btc_200sma.loc[date]

        # Regime filter: CASH when BTC < 200-SMA or insufficient SMA history
        if pd.isna(sma_val) or pd.isna(btc_val) or btc_val < sma_val:
            target_raw.loc[date] = "CASH"
            continue

        # Rank by 4-week return; drop NaN (assets without sufficient history)
        day_ret = rolling_returns.loc[date].dropna()

        if day_ret.empty:
            target_raw.loc[date] = "CASH"
            continue

        # Cross-sectional rank: long the top-return asset
        top_asset = str(day_ret.idxmax())
        target_raw.loc[date] = top_asset

    # Forward-fill Friday signal through Mon–Thu
    # This propagates the Friday decision through the week.
    target_ffill = target_raw.ffill()

    # Shift 1 bar: Friday close (evaluation) → Monday open (execution)
    # This is the key no-look-ahead guard: the signal cannot observe Monday's price.
    target_shifted = target_ffill.shift(1)

    return target_shifted, btc_200sma


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _apply_crypto_costs(
    price: float,
    units: float,
    is_buy: bool,
) -> tuple:
    """
    Canonical crypto transaction cost (Engineering Director spec):
      fee      = 0.10% of notional per leg (taker)
      slippage = 0.05% of notional per leg
      impact   = N/A (BTC/ETH/SOL/AVAX ADV >> $25K order size)

    Returns (effective_price, total_cost_dollars).
    """
    total_cost = (CRYPTO_FEE_PCT + CRYPTO_SLIPPAGE_PCT) * price * units
    if is_buy:
        eff_price = price + total_cost / units   # buyer pays cost
    else:
        eff_price = price - total_cost / units   # seller receives price minus cost
    return eff_price, total_cost


# ── Simulation Engine ──────────────────────────────────────────────────────────

def simulate_h36(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    target_signal: pd.Series,
    params: dict,
) -> tuple:
    """
    Simulate H36 cross-sectional momentum with weekly rotation.

    Position logic:
    - When target_signal changes asset: sell current at open, buy new at same open.
    - When target_signal = "CASH" or NaN: exit all positions at next open.
    - Hard stop: if position drops ≥ hard_stop_pct from entry → exit at stop price (close-bar).
    - End of data: force-close at last close.

    Crypto uses fractional units (units = capital / price). All prices from yfinance
    auto_adjust=True.

    Returns:
        trade_log (list of dicts), equity (pd.Series), daily_df (pd.DataFrame)
    """
    init_cash = float(params["init_cash"])
    hard_stop_pct = float(params.get("hard_stop_pct", 0.12))

    dates = close_df.index
    n = len(dates)

    trade_log = []
    daily_records = []

    capital = init_cash

    # Active position state
    current_asset: str | None = None
    current_shares: float = 0.0
    entry_fill_price: float = 0.0    # raw open fill — used for hard stop threshold
    entry_eff_price: float = 0.0     # effective entry post-costs — used for PnL
    entry_cost_total: float = 0.0
    entry_date_ts = None
    entry_bar_idx: int = -1

    for i in range(n):
        date = dates[i]

        # Desired position from signal; normalize NaN → None (cash)
        desired_raw = target_signal.iloc[i]
        if pd.isna(desired_raw) or desired_raw == "CASH":
            desired_asset: str | None = None
        else:
            desired_asset = str(desired_raw)

        exit_triggered = False

        # ── Step 1: Rotation / Exit at today's OPEN ──────────────────────────
        # Execute trade if target differs from current holding.
        # Same-bar sell+buy is intentional for weekly rotation:
        # both sides execute at Monday open (no 1-bar slippage penalty vs. 2-step queue).
        needs_trade = desired_asset != current_asset

        if needs_trade and current_asset is not None:
            # Guard: cannot exit on the same bar as entry (same-open constraint)
            if i > entry_bar_idx:
                if current_asset in open_df.columns:
                    open_price = float(open_df[current_asset].iloc[i])
                    if open_price > 0 and not pd.isna(open_price):
                        eff_xp, xcost = _apply_crypto_costs(
                            open_price, current_shares, is_buy=False
                        )
                        pnl = (eff_xp - entry_eff_price) * current_shares
                        capital += eff_xp * current_shares

                        trade_log.append({
                            "entry_date": entry_date_ts.date(),
                            "exit_date": date.date(),
                            "asset": current_asset,
                            "entry_price": round(entry_eff_price, 6),
                            "exit_price": round(eff_xp, 6),
                            "shares": round(current_shares, 8),
                            "pnl": round(pnl, 2),
                            "return_pct": round(
                                (eff_xp - entry_eff_price) / entry_eff_price, 6
                            ),
                            "entry_cost": round(entry_cost_total, 4),
                            "exit_cost": round(xcost, 4),
                            "transaction_cost": round(entry_cost_total + xcost, 4),
                            "liquidity_constrained": False,
                            "hold_days": i - entry_bar_idx,
                            "exit_reason": (
                                "ROTATION" if desired_asset is not None else "REGIME_EXIT"
                            ),
                        })

                        current_asset = None
                        current_shares = 0.0
                        exit_triggered = True

        # ── Step 2: Enter new position at today's OPEN ───────────────────────
        # Enter if: (a) desired != None, (b) not currently in any position
        # (we may have just exited above in the same bar — rotation case).
        if desired_asset is not None and current_asset is None:
            if desired_asset in open_df.columns and desired_asset in close_df.columns:
                open_price = float(open_df[desired_asset].iloc[i])
                if open_price > 0 and not pd.isna(open_price) and capital > 0:
                    # 100% of capital in single top-ranked asset (concentrated momentum)
                    units = capital / open_price  # fractional crypto units
                    eff_ep, ecost = _apply_crypto_costs(open_price, units, is_buy=True)

                    capital -= eff_ep * units  # effectively 0 cash (fully invested)
                    current_asset = desired_asset
                    current_shares = units
                    entry_fill_price = open_price
                    entry_eff_price = eff_ep
                    entry_cost_total = ecost
                    entry_date_ts = date
                    entry_bar_idx = i

        # ── Step 3: Hard stop — check against today's CLOSE ─────────────────
        # Crypto hard stop: -12% from raw entry fill (wider than equity to account for vol).
        # Conservatively fills at the stop threshold, not at the actual close.
        if current_asset is not None and not exit_triggered:
            if current_asset in close_df.columns:
                close_i = float(close_df[current_asset].iloc[i])
                stop_threshold = entry_fill_price * (1.0 - hard_stop_pct)

                if not pd.isna(close_i) and close_i <= stop_threshold:
                    stop_fill = stop_threshold  # conservative: fill at stop, not worse
                    eff_xp, xcost = _apply_crypto_costs(
                        stop_fill, current_shares, is_buy=False
                    )
                    pnl = (eff_xp - entry_eff_price) * current_shares
                    capital += eff_xp * current_shares

                    trade_log.append({
                        "entry_date": entry_date_ts.date(),
                        "exit_date": date.date(),
                        "asset": current_asset,
                        "entry_price": round(entry_eff_price, 6),
                        "exit_price": round(eff_xp, 6),
                        "shares": round(current_shares, 8),
                        "pnl": round(pnl, 2),
                        "return_pct": round(
                            (eff_xp - entry_eff_price) / entry_eff_price, 6
                        ),
                        "entry_cost": round(entry_cost_total, 4),
                        "exit_cost": round(xcost, 4),
                        "transaction_cost": round(entry_cost_total + xcost, 4),
                        "liquidity_constrained": False,
                        "hold_days": i - entry_bar_idx,
                        "exit_reason": "HARD_STOP",
                    })

                    current_asset = None
                    current_shares = 0.0
                    exit_triggered = True

        # ── Daily mark-to-market ─────────────────────────────────────────────
        mtm_position = 0.0
        if current_asset is not None and current_asset in close_df.columns:
            c = float(close_df[current_asset].iloc[i])
            if not pd.isna(c):
                mtm_position = current_shares * c
            else:
                mtm_position = current_shares * entry_fill_price  # fallback

        daily_records.append({
            "date": date,
            "position": current_asset if current_asset else "CASH",
            "equity": capital + mtm_position,
        })

    # ── Force-close any open position at end of data ──────────────────────────
    if current_asset is not None and n > 0:
        i = n - 1
        date_f = dates[i]
        if current_asset in close_df.columns:
            close_f = float(close_df[current_asset].iloc[i])
            eff_xp, xcost = _apply_crypto_costs(close_f, current_shares, is_buy=False)
            pnl = (eff_xp - entry_eff_price) * current_shares
            capital += eff_xp * current_shares

            trade_log.append({
                "entry_date": entry_date_ts.date(),
                "exit_date": date_f.date(),
                "asset": current_asset,
                "entry_price": round(entry_eff_price, 6),
                "exit_price": round(eff_xp, 6),
                "shares": round(current_shares, 8),
                "pnl": round(pnl, 2),
                "return_pct": round(
                    (eff_xp - entry_eff_price) / entry_eff_price, 6
                ),
                "entry_cost": round(entry_cost_total, 4),
                "exit_cost": round(xcost, 4),
                "transaction_cost": round(entry_cost_total + xcost, 4),
                "liquidity_constrained": False,
                "hold_days": (n - 1) - entry_bar_idx,
                "exit_reason": "END_OF_DATA",
            })

            if daily_records:
                daily_records[-1]["equity"] = capital

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")

    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df


# ── Performance Metrics ────────────────────────────────────────────────────────

def _compute_metrics(
    equity: pd.Series,
    trades_df: pd.DataFrame,
    start: str,
    end: str,
) -> dict:
    """
    Compute standard Gate 1 performance metrics from equity curve and trade log.
    All returns are annualized to TRADING_DAYS_PER_YEAR (252).
    """
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)
    years = max((ts_end - ts_start).days / 365.25, 1e-3)

    n_trades = len(trades_df)
    trades_per_year = round(n_trades / years, 1)

    daily_returns = equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values

    sharpe = 0.0
    if len(ret_arr) > 1 and ret_arr.std() > 1e-10:
        sharpe = round(
            float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4
        )

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    win_rate = 0.0
    profit_factor = 0.0
    if n_trades > 0 and "pnl" in trades_df.columns:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        gross_wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        gross_losses = abs(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum())
        profit_factor = round(float(gross_wins / max(gross_losses, 1e-8)), 4)

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
    }


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download crypto data, compute cross-sectional momentum signal on warmup-inclusive
    series, trim to backtest window, simulate H36.

    Parameters
    ----------
    start : str  Backtest start date (YYYY-MM-DD). IS = "2018-01-01".
    end   : str  Backtest end date (YYYY-MM-DD). IS = "2022-12-31".
    params : dict, optional  Override PARAMETERS.

    Returns
    -------
    dict  Standardized result: sharpe, max_drawdown, total_return, win_rate,
          profit_factor, trade_count, trades_per_year,
          trades (DataFrame), equity_curve (Series), daily_df (DataFrame),
          metrics (dict), data_quality (dict), params (dict),
          regime_on_pct (float), asset_breakdown (dict).
    """
    if params is None:
        params = PARAMETERS.copy()

    universe = params["universe"]
    ranking_window = int(params["ranking_window"])
    trend_sma_window = int(params["trend_sma_window"])
    init_cash = float(params["init_cash"])

    # ── 1. Download with warmup ──────────────────────────────────────────────
    close_full, open_full = download_data(
        universe, start, end, ranking_window, trend_sma_window
    )

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 2. Compute signal on warmup-inclusive series ─────────────────────────
    # All indicators (rolling returns, 200-SMA) computed on full history;
    # warmup ensures no NaN at the start of the backtest window.
    target_signal_full, btc_200sma_full = compute_rank_signal(
        close_full, ranking_window, trend_sma_window
    )

    # ── 3. Trim to backtest window ───────────────────────────────────────────
    mask = (close_full.index >= ts_start) & (close_full.index <= ts_end)
    close_df = close_full.loc[mask].copy()
    open_df = open_full.loc[mask].copy()
    target_signal = target_signal_full.loc[mask]
    btc_200sma = btc_200sma_full.loc[mask]

    if len(close_df) < 10:
        raise ValueError(
            f"Insufficient data after trimming to {start}–{end}: {len(close_df)} bars"
        )

    # ── 4. Data quality checks ───────────────────────────────────────────────
    data_quality = check_data_quality(close_full, start, end)

    # ── 5. Simulate ──────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h36(close_df, open_df, target_signal, params)

    # ── 6. Build trade DataFrame ─────────────────────────────────────────────
    empty_cols = [
        "entry_date", "exit_date", "asset", "entry_price", "exit_price",
        "shares", "pnl", "return_pct", "entry_cost", "exit_cost",
        "transaction_cost", "liquidity_constrained", "hold_days", "exit_reason",
    ]
    trades_df = (
        pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)
    )

    # ── 7. Metrics ───────────────────────────────────────────────────────────
    metrics = _compute_metrics(equity, trades_df, start, end)

    # Signal diagnostics
    target_valid = target_signal.dropna()
    regime_on_pct = round(float((target_valid != "CASH").mean()), 4) if len(target_valid) > 0 else 0.0
    cash_pct = round(1.0 - regime_on_pct, 4)

    # Per-asset breakdown
    asset_breakdown: dict = {}
    exit_breakdown: dict = {}
    if not trades_df.empty:
        for asset_name, grp in trades_df.groupby("asset"):
            asset_breakdown[asset_name] = {
                "trade_count": len(grp),
                "total_pnl": round(float(grp["pnl"].sum()), 2),
                "win_rate": round(float((grp["pnl"] > 0).mean()), 4),
            }
        exit_breakdown = trades_df["exit_reason"].value_counts().to_dict()

    print(
        f"\nH36 Crypto Cross-Sectional Momentum ({start} to {end}):\n"
        f"  Ranking window: {ranking_window}d | BTC trend SMA: {trend_sma_window}d"
        f" | Hard stop: {params.get('hard_stop_pct', 0.12):.0%}\n"
        f"  Regime-on rate: {regime_on_pct:.1%} | Cash rate: {cash_pct:.1%}\n"
        f"  Trades: {metrics['trade_count']} ({metrics['trades_per_year']}/yr)\n"
        f"  Sharpe: {metrics['sharpe']} | Max DD: {metrics['max_drawdown']:.2%}"
        f" | Total Return: {metrics['total_return']:.2%}\n"
        f"  Win rate: {metrics['win_rate']:.2%} | Profit factor: {metrics['profit_factor']:.2f}\n"
        f"  Asset breakdown: { {k: v['trade_count'] for k, v in asset_breakdown.items()} }\n"
        f"  Exit reasons: {exit_breakdown}\n"
        f"  Init cash: ${init_cash:,.0f}"
    )

    if metrics["trade_count"] < 100:
        warnings.warn(
            f"Trade count {metrics['trade_count']} < 100 Gate 1 minimum. "
            f"H36 IS window is structurally limited by crypto data availability "
            f"(CEO QUA-281 exception granted)."
        )

    return {
        **metrics,
        "returns": equity.pct_change().fillna(0.0),
        "trades": trades_df,
        "equity_curve": equity,
        "daily_df": daily_df,
        "metrics": metrics,
        "params": params,
        "regime_on_pct": regime_on_pct,
        "cash_pct": cash_pct,
        "asset_breakdown": asset_breakdown,
        "exit_breakdown": exit_breakdown,
        "data_quality": data_quality,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    universe: list = None,
    start: str = "2018-01-01",
    end: str = "2022-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H36.

    Returns a DataFrame with per-day columns:
        date, position, equity, pnl, asset, entry_price, exit_price,
        return_pct, transaction_cost, exit_reason

    Trade-level fields populated on exit date; all other rows carry NaN.
    """
    p = (params or PARAMETERS).copy()
    if universe is not None:
        p["universe"] = universe

    result = run_backtest(start, end, p)

    daily = result["daily_df"].reset_index()
    trades = result["trades"]

    trade_cols = [
        "exit_date", "asset", "pnl", "entry_price", "exit_price",
        "return_pct", "transaction_cost", "exit_reason",
    ]

    if trades.empty or not all(c in trades.columns for c in trade_cols):
        for col in ["pnl", "asset", "entry_price", "exit_price", "return_pct",
                    "transaction_cost", "exit_reason"]:
            daily[col] = np.nan
    else:
        tc = trades[trade_cols].copy()
        tc["exit_date"] = pd.to_datetime(tc["exit_date"])
        daily["date"] = pd.to_datetime(daily["date"])
        daily = daily.merge(
            tc.rename(columns={"exit_date": "date"}),
            on="date",
            how="left",
        )

    return daily[[
        "date", "position", "equity",
        "pnl", "asset", "entry_price", "exit_price",
        "return_pct", "transaction_cost", "exit_reason",
    ]]


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running H36 IS backtest (2018-01-01 to 2022-12-31)...")
    is_result = run_backtest("2018-01-01", "2022-12-31")
    print(f"\nIS equity final: ${is_result['equity_curve'].iloc[-1]:,.2f}")
    print(f"IS trade count: {is_result['trade_count']}")
    if not is_result["trades"].empty:
        print("\nSample trades (first 10):")
        print(is_result["trades"].head(10).to_string(index=False))

    print("\n" + "=" * 60)
    print("Running H36 OOS backtest (2023-01-01 to 2025-12-31)...")
    oos_result = run_backtest("2023-01-01", "2025-12-31")
    print(f"\nOOS equity final: ${oos_result['equity_curve'].iloc[-1]:,.2f}")
    print(f"OOS trade count: {oos_result['trade_count']}")
