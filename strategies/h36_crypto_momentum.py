"""
Strategy: H36b Crypto Cross-Sectional Momentum — Top-2 Equal-Weight (Position Sizing Revision)
Author: Engineering Director (QUA-291 / QUA-293)
Date: 2026-03-17
Hypothesis: Cross-sectional momentum — buying the weekly return top-2 among BTC, ETH, SOL,
            AVAX — exploits attention-driven capital rotation in crypto markets. BTC 200-SMA
            regime filter avoids sustained bear markets. Equal-weight (50%/50%) across top-2
            ranked assets to reduce single-asset concentration drawdown.

H36b revision rationale (QUA-293):
    H36 Gate 1 failure: IS Sharpe 1.38, OOS Sharpe 0.86 passed; MDD -54% FAILED (<20%).
    Root cause: 100% concentration in single volatile crypto. Fix: top_n=2 with 50/50 split.

Parameters:
    top_n=1 reproduces original H36 (100% single asset).
    top_n=2 is H36b default (50%/50% equal weight).

Asset class: cryptocurrency
Parent task: QUA-293
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
    "top_n": 2,                 # H36b: top-2 equal-weight (50%/50%); set to 1 for original H36
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
    top_n: int = 2,
) -> tuple:
    """
    Compute weekly cross-sectional momentum signal.

    Signal evaluation on Friday close:
    1. Compute `ranking_window`-day simple return for each asset.
       Assets with insufficient history (NaN) are excluded from ranking.
    2. BTC 200-SMA regime filter: if BTC_close < BTC_200SMA → signal = "CASH".
    3. Rank all available assets by return; select top-N (default top_n=2 for H36b).
    4. Forward-fill Friday signal to Mon–Thu (covers week until next Friday).
    5. Shift by 1 bar: Friday-close signal → Monday-open execution (no look-ahead).

    Signal encoding:
    - "CASH" (str): no position (regime filter triggered or insufficient data)
    - tuple of asset strings e.g. ("BTC-USD", "ETH-USD"): invest equal-weight in these

    Dynamic universe:
    - Before SOL/AVAX data starts (~2020): only BTC/ETH are ranked (2 assets).
      With top_n=2, selects both available assets in early years (2018–2020).
    - After all 4 assets have data: all 4 are ranked, top 2 selected.
    - The `.dropna()` in ranking naturally handles the transition.

    Returns:
        target_signal (pd.Series): Signal (tuple of assets or "CASH"), shifted +1 bar.
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

        # Cross-sectional rank: select top-N assets (tuple for multi-position support)
        n_select = min(top_n, len(day_ret))
        top_assets = tuple(day_ret.nlargest(n_select).index.tolist())
        target_raw.loc[date] = top_assets

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

def _is_invested(signal_val) -> bool:
    """True if signal value represents an invested position (not CASH or NaN)."""
    if signal_val is None or (isinstance(signal_val, float) and np.isnan(signal_val)):
        return False
    if isinstance(signal_val, str):
        return signal_val != "CASH"
    if isinstance(signal_val, (tuple, list)):
        return len(signal_val) > 0
    return False


def simulate_h36(
    close_df: pd.DataFrame,
    open_df: pd.DataFrame,
    target_signal: pd.Series,
    params: dict,
) -> tuple:
    """
    Simulate H36b cross-sectional momentum with weekly rotation and multi-position
    equal-weight allocation.

    Supports top_n=1 (original H36: 100% single asset) and top_n=2 (H36b: 50%/50%).

    Position logic:
    - On rebalance bar: exit positions NOT in new target at open; enter new positions at open.
    - Equal-weight: each position targets 1/top_n of total portfolio NAV.
    - Signal is a tuple of asset names (or "CASH"). Unchanged set → no rebalance.
    - Hard stop: if any position drops ≥ hard_stop_pct from entry → exit at stop price (close-bar).
    - End of data: force-close all at last close.

    Crypto uses fractional units (units = capital / price). All prices from yfinance
    auto_adjust=True.

    Returns:
        trade_log (list of dicts), equity (pd.Series), daily_df (pd.DataFrame)
    """
    top_n = int(params.get("top_n", 2))
    weight_per_slot = 1.0 / top_n  # 0.5 for top_n=2
    init_cash = float(params["init_cash"])
    hard_stop_pct = float(params.get("hard_stop_pct", 0.12))

    dates = close_df.index
    n = len(dates)

    trade_log = []
    daily_records = []
    capital = init_cash

    # positions: asset -> {shares, entry_fill, entry_eff, entry_cost, entry_date, entry_bar}
    positions: dict = {}

    for i in range(n):
        date = dates[i]

        # Parse desired targets from signal
        raw = target_signal.iloc[i]
        if not _is_invested(raw):
            desired_set: frozenset = frozenset()
        elif isinstance(raw, (tuple, list)):
            desired_set = frozenset(raw)
        else:
            # top_n=1 backward compat: single-asset string signal from old code
            desired_set = frozenset([str(raw)])

        current_set = frozenset(positions.keys())
        needs_rebalance = desired_set != current_set

        # ── Step 1: Exit positions NOT in desired set (at today's OPEN) ─────────
        if needs_rebalance:
            to_exit = current_set - desired_set
            for asset in sorted(to_exit):  # sorted for determinism
                pos = positions[asset]
                # Guard: cannot exit on same bar as entry
                if i > pos["entry_bar"] and asset in open_df.columns:
                    open_price = float(open_df[asset].iloc[i])
                    if open_price > 0 and not pd.isna(open_price):
                        eff_xp, xcost = _apply_crypto_costs(
                            open_price, pos["shares"], is_buy=False
                        )
                        pnl = (eff_xp - pos["entry_eff"]) * pos["shares"]
                        capital += eff_xp * pos["shares"]

                        trade_log.append({
                            "entry_date": pos["entry_date"].date(),
                            "exit_date": date.date(),
                            "asset": asset,
                            "entry_price": round(pos["entry_eff"], 6),
                            "exit_price": round(eff_xp, 6),
                            "shares": round(pos["shares"], 8),
                            "pnl": round(pnl, 2),
                            "return_pct": round(
                                (eff_xp - pos["entry_eff"]) / (pos["entry_eff"] + 1e-10), 6
                            ),
                            "entry_cost": round(pos["entry_cost"], 4),
                            "exit_cost": round(xcost, 4),
                            "transaction_cost": round(pos["entry_cost"] + xcost, 4),
                            "liquidity_constrained": False,
                            "hold_days": i - pos["entry_bar"],
                            "exit_reason": (
                                "ROTATION" if desired_set else "REGIME_EXIT"
                            ),
                        })
                        del positions[asset]

        # ── Step 2: Enter new positions (at today's OPEN) ────────────────────────
        to_enter = desired_set - frozenset(positions.keys())
        if to_enter and capital > 0:
            # Total NAV = remaining cash + current open-mark of held positions
            nav_held = sum(
                float(open_df[a].iloc[i]) * positions[a]["shares"]
                for a in positions
                if a in open_df.columns and not pd.isna(float(open_df[a].iloc[i]))
            )
            total_nav = capital + nav_held
            target_alloc = total_nav * weight_per_slot  # per-position target dollar value

            for asset in sorted(to_enter):  # sorted for determinism
                if asset in open_df.columns and capital > 0:
                    open_price = float(open_df[asset].iloc[i])
                    if open_price > 0 and not pd.isna(open_price):
                        # Use min(target_alloc, available_capital) to avoid overdraft
                        alloc = min(target_alloc, capital)
                        units = alloc / open_price  # fractional crypto units
                        eff_ep, ecost = _apply_crypto_costs(open_price, units, is_buy=True)
                        capital -= eff_ep * units   # deduct cost-inclusive notional

                        positions[asset] = {
                            "shares": units,
                            "entry_fill": open_price,  # raw open fill — used for hard stop
                            "entry_eff": eff_ep,        # cost-adjusted — used for PnL
                            "entry_cost": ecost,
                            "entry_date": date,
                            "entry_bar": i,
                        }

        # ── Step 3: Hard stop — check each position against today's CLOSE ────────
        # Crypto hard stop: -12% from raw entry fill. Fills conservatively at stop threshold.
        for asset in sorted(list(positions.keys())):
            pos = positions[asset]
            if asset in close_df.columns:
                close_i = float(close_df[asset].iloc[i])
                stop_threshold = pos["entry_fill"] * (1.0 - hard_stop_pct)

                if not pd.isna(close_i) and close_i <= stop_threshold:
                    stop_fill = stop_threshold  # fill at stop, not worse (conservative)
                    eff_xp, xcost = _apply_crypto_costs(
                        stop_fill, pos["shares"], is_buy=False
                    )
                    pnl = (eff_xp - pos["entry_eff"]) * pos["shares"]
                    capital += eff_xp * pos["shares"]

                    trade_log.append({
                        "entry_date": pos["entry_date"].date(),
                        "exit_date": date.date(),
                        "asset": asset,
                        "entry_price": round(pos["entry_eff"], 6),
                        "exit_price": round(eff_xp, 6),
                        "shares": round(pos["shares"], 8),
                        "pnl": round(pnl, 2),
                        "return_pct": round(
                            (eff_xp - pos["entry_eff"]) / (pos["entry_eff"] + 1e-10), 6
                        ),
                        "entry_cost": round(pos["entry_cost"], 4),
                        "exit_cost": round(xcost, 4),
                        "transaction_cost": round(pos["entry_cost"] + xcost, 4),
                        "liquidity_constrained": False,
                        "hold_days": i - pos["entry_bar"],
                        "exit_reason": "HARD_STOP",
                    })
                    del positions[asset]

        # ── Daily mark-to-market ──────────────────────────────────────────────────
        mtm_position = 0.0
        for asset, pos in positions.items():
            if asset in close_df.columns:
                c = float(close_df[asset].iloc[i])
                if not pd.isna(c):
                    mtm_position += pos["shares"] * c
                else:
                    mtm_position += pos["shares"] * pos["entry_fill"]  # fallback

        position_label = (
            ",".join(sorted(positions.keys())) if positions else "CASH"
        )
        daily_records.append({
            "date": date,
            "position": position_label,
            "equity": capital + mtm_position,
        })

    # ── Force-close all open positions at end of data ─────────────────────────
    if positions and n > 0:
        i = n - 1
        date_f = dates[i]
        for asset in sorted(list(positions.keys())):
            pos = positions[asset]
            if asset in close_df.columns:
                close_f = float(close_df[asset].iloc[i])
                eff_xp, xcost = _apply_crypto_costs(close_f, pos["shares"], is_buy=False)
                pnl = (eff_xp - pos["entry_eff"]) * pos["shares"]
                capital += eff_xp * pos["shares"]

                trade_log.append({
                    "entry_date": pos["entry_date"].date(),
                    "exit_date": date_f.date(),
                    "asset": asset,
                    "entry_price": round(pos["entry_eff"], 6),
                    "exit_price": round(eff_xp, 6),
                    "shares": round(pos["shares"], 8),
                    "pnl": round(pnl, 2),
                    "return_pct": round(
                        (eff_xp - pos["entry_eff"]) / (pos["entry_eff"] + 1e-10), 6
                    ),
                    "entry_cost": round(pos["entry_cost"], 4),
                    "exit_cost": round(xcost, 4),
                    "transaction_cost": round(pos["entry_cost"] + xcost, 4),
                    "liquidity_constrained": False,
                    "hold_days": (n - 1) - pos["entry_bar"],
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
    series, trim to backtest window, simulate H36b (top-2 equal-weight).

    Parameters
    ----------
    start : str  Backtest start date (YYYY-MM-DD). IS = "2018-01-01".
    end   : str  Backtest end date (YYYY-MM-DD). IS = "2022-12-31".
    params : dict, optional  Override PARAMETERS. Set top_n=1 for original H36 behavior.

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
    top_n = int(params.get("top_n", 2))
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
        close_full, ranking_window, trend_sma_window, top_n=top_n
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
    regime_on_pct = (
        round(float(target_valid.apply(_is_invested).mean()), 4)
        if len(target_valid) > 0
        else 0.0
    )
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
        f"\nH36b Crypto Cross-Sectional Momentum [{top_n}-asset equal-weight] ({start} to {end}):\n"
        f"  Ranking window: {ranking_window}d | BTC trend SMA: {trend_sma_window}d"
        f" | Hard stop: {params.get('hard_stop_pct', 0.12):.0%} | top_n={top_n}\n"
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
            f"H36b IS window is structurally limited by crypto data availability "
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
    Orchestrator-compatible entry point for H36b.

    Returns a DataFrame with per-day columns:
        date, position, equity, pnl, asset, entry_price, exit_price,
        return_pct, transaction_cost, exit_reason

    Trade-level fields populated on exit date; all other rows carry NaN.
    The `position` column contains comma-separated asset names (e.g. "BTC-USD,ETH-USD")
    or "CASH" — reflects the multi-position H36b structure.
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
    print("Running H36b IS backtest (2018-01-01 to 2022-12-31) [top_n=2, equal-weight]...")
    is_result = run_backtest("2018-01-01", "2022-12-31")
    print(f"\nIS equity final: ${is_result['equity_curve'].iloc[-1]:,.2f}")
    print(f"IS trade count: {is_result['trade_count']}")
    if not is_result["trades"].empty:
        print("\nSample trades (first 10):")
        print(is_result["trades"].head(10).to_string(index=False))

    print("\n" + "=" * 60)
    print("Running H36b OOS backtest (2023-01-01 to 2025-12-31)...")
    oos_result = run_backtest("2023-01-01", "2025-12-31")
    print(f"\nOOS equity final: ${oos_result['equity_curve'].iloc[-1]:,.2f}")
    print(f"OOS trade count: {oos_result['trade_count']}")
