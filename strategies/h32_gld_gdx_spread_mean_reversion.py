"""
Strategy: H32 GLD/GDX Gold-Miners Spread Mean Reversion
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: GLD and GDX share structural cointegration — miners' revenues are
            anchored to gold price with ~1.5–2× operational leverage. When the
            GDX/GLD log-price ratio z-score drops below -2σ (GDX temporarily
            underperforms GLD), buy GDX at next open and hold until the z-score
            reverts to 0 or 10 days elapse, whichever comes first. Entry only
            permitted when GLD > 200-day SMA (gold bull regime).
Asset class: equities/commodity ETF pair (GDX long-only, GLD regime filter)
Parent task: QUA-270
References: Gatev, Goetzmann & Rouwenhorst (2006) RFS 19(3);
            Avellaneda & Lee (2010) QF 10(7);
            research/hypotheses/32_gld_gdx_spread_mean_reversion.md
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "gld_ticker": "GLD",
    "gdx_ticker": "GDX",
    # Spread z-score parameters
    "zscore_threshold": 2.0,      # entry when z-score < -zscore_threshold (range: 1.5–2.5)
    "zscore_window": 60,          # rolling window for log-ratio mean/std (range: 40–90 days)
    # Regime filter
    "sma_window": 200,            # GLD SMA window — gold bull regime gate (range: 150–250)
    # Exit parameters
    "hold_days": 10,              # time stop: max trading days held (range: 5–20)
    "exit_zscore": 0.0,           # mean reversion exit: z-score >= this value (return to mean)
    "zscore_stop": -4.0,          # cointegration breakdown stop: z-score ≤ this (range: -3 to -5)
    "gdx_stop_loss_pct": 0.10,    # GDX price stop-loss from effective entry (range: 7–15%)
    # Capital
    "init_cash": 25000,           # initial capital in USD
}

# ── Transaction Cost Constants (Engineering Director spec) ─────────────────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share fixed
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root impact coefficient k
SIGMA_WINDOW = 20               # 20-day rolling vol for market impact σ
ADV_WINDOW = 20                 # 20-day rolling ADV for Q/ADV ratio
TRADING_DAYS_PER_YEAR = 252


# ── Data Download ──────────────────────────────────────────────────────────────

def _download_single(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def download_data(
    gld_ticker: str, gdx_ticker: str, start: str, end: str, params: dict
) -> dict:
    """
    Download GLD and GDX OHLCV with warmup window.

    Warmup = max(sma_window, zscore_window, SIGMA_WINDOW, ADV_WINDOW) + 60 calendar-day buffer.
    Returns dict: {'gld': DataFrame, 'gdx': DataFrame}
    Raises ValueError if data is insufficient or columns are missing.
    """
    warmup_days = max(
        params["sma_window"], params["zscore_window"], SIGMA_WINDOW, ADV_WINDOW
    ) + 60
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")

    required = {"Open", "High", "Low", "Close", "Volume"}

    gld_df = _download_single(gld_ticker, warmup_start, end)
    missing = required - set(gld_df.columns)
    if missing:
        raise ValueError(f"Missing columns for {gld_ticker}: {missing}")
    if len(gld_df) < params["sma_window"] + 10:
        raise ValueError(
            f"Insufficient data for {gld_ticker}: {len(gld_df)} bars "
            f"(need {params['sma_window'] + 10})"
        )
    gld_na = int(gld_df["Close"].isna().sum())
    if gld_na > 5:
        warnings.warn(f"{gld_ticker}: {gld_na} missing trading days detected")

    gdx_df = _download_single(gdx_ticker, warmup_start, end)
    missing = required - set(gdx_df.columns)
    if missing:
        raise ValueError(f"Missing columns for {gdx_ticker}: {missing}")
    if len(gdx_df) < params["zscore_window"] + 10:
        raise ValueError(
            f"Insufficient data for {gdx_ticker}: {len(gdx_df)} bars "
            f"(need {params['zscore_window'] + 10})"
        )
    gdx_na = int(gdx_df["Close"].isna().sum())
    if gdx_na > 5:
        warnings.warn(f"{gdx_ticker}: {gdx_na} missing trading days detected")

    # GDX inception is 2006-05-16; warn if IS start predates inception
    gdx_start = gdx_df.index[0]
    if gdx_start > pd.Timestamp("2007-01-01"):
        warnings.warn(
            f"GDX data starts {gdx_start.date()} — IS window may have limited early history"
        )

    return {"gld": gld_df, "gdx": gdx_df}


# ── Signal Generation ──────────────────────────────────────────────────────────

def compute_spread_signals(
    gld_df: pd.DataFrame, gdx_df: pd.DataFrame, params: dict
) -> dict:
    """
    Compute GDX/GLD log-ratio z-score and derived entry/exit signals.

    Spread = log(GDX_close) − log(GLD_close)  (approximates log hedge ratio = 1)
    Z-score = (spread − rolling_mean) / rolling_std  (60-day window)

    Entry signal: z-score < -zscore_threshold AND GLD > GLD_200SMA
    Exit z-score conditions: z-score >= exit_zscore (mean revert) or z-score <= zscore_stop

    All signals are end-of-day (no look-ahead). Signals computed on the joined index.

    Returns dict with Series aligned to the joined GLD/GDX trading calendar.
    """
    # Join on common trading dates (inner join to drop GLD-only or GDX-only dates)
    combined = pd.DataFrame({
        "gld_close": gld_df["Close"],
        "gdx_close": gdx_df["Close"],
    }).dropna()

    window = params["zscore_window"]

    # Log ratio spread (no OLS — simple log-ratio is standard for ETF pairs)
    # log(GDX/GLD) captures relative performance with daily compounding symmetry
    log_ratio = np.log(combined["gdx_close"] / combined["gld_close"])

    ratio_mean = log_ratio.rolling(window, min_periods=window).mean()
    ratio_std = log_ratio.rolling(window, min_periods=window).std()

    # Z-score: negative = GDX has underperformed GLD relative to rolling norm
    zscore = (log_ratio - ratio_mean) / (ratio_std + 1e-10)

    # GLD 200-SMA regime filter (bull gold market required)
    gld_sma = combined["gld_close"].rolling(params["sma_window"], min_periods=params["sma_window"]).mean()
    regime_ok = combined["gld_close"] > gld_sma

    # Entry: GDX underperformed by ≥ zscore_threshold σ AND gold in uptrend
    entry_signal = (zscore < -params["zscore_threshold"]) & regime_ok

    # Exit conditions (checked independently; simulation uses priority ordering)
    mean_revert_signal = zscore >= params["exit_zscore"]    # spread normalized
    zscore_stop_signal = zscore <= params["zscore_stop"]     # cointegration breakdown risk

    return {
        "combined": combined,
        "zscore": zscore,
        "regime_ok": regime_ok,
        "entry_signal": entry_signal,
        "mean_revert_signal": mean_revert_signal,
        "zscore_stop_signal": zscore_stop_signal,
    }


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    idx: int,
) -> tuple:
    """
    Canonical equities transaction cost (Engineering Director spec):
      fixed    = $0.005/share
      slippage = 0.05% of notional
      impact   = k × σ × sqrt(Q / ADV) × price × Q  (Almgren-Chriss square-root model)

    Flags orders where Q/ADV > 1% as liquidity-constrained.
    Returns (total_cost_dollars: float, liquidity_constrained: bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01    # fallback: 1% daily vol
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000  # fallback: 1M shares ADV

    # Square-root market impact (Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV). "
            "Q/ADV > 1% — market impact elevated."
        )

    return fixed + slippage + impact, liq_constrained


# ── H32 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h32(
    gdx_df: pd.DataFrame,
    signals: dict,
    params: dict,
) -> tuple:
    """
    Simulate H32 GDX/GLD Spread Mean Reversion using a daily bar loop.

    Entry/exit logic (all exits execute at next open; no look-ahead):
    - Entry: z-score < -zscore_threshold AND GLD > 200-SMA at close → buy GDX next open.
    - Exit (first to trigger, checked at end of each day):
        1. Cointegration breakdown stop: z-score ≤ zscore_stop (-4.0) → sell next open
        2. Price stop-loss: GDX close ≤ entry_price × (1 − gdx_stop_loss_pct) → sell next open
        3. Mean reversion exit: z-score ≥ exit_zscore (0.0) → sell next open
        4. Time stop: days_held ≥ hold_days − 1 → sell next open
           (hold_days=10 → hold from open[E] through close[E+9]; sell open[E+10])
    - Only one position at a time.

    Note: GDX stop-loss uses daily close (conservative daily approximation).
    Z-score stop uses daily close z-score. Both execute at next open to avoid look-ahead.

    Returns (trade_log: list, equity: pd.Series, daily_df: pd.DataFrame)
    """
    hold_days = params["hold_days"]
    exit_zscore = params["exit_zscore"]
    zscore_stop = params["zscore_stop"]
    gdx_stop_loss_pct = params["gdx_stop_loss_pct"]
    init_cash = float(params["init_cash"])

    combined = signals["combined"]
    zscore = signals["zscore"]
    entry_signal = signals["entry_signal"]
    mean_revert_signal = signals["mean_revert_signal"]
    zscore_stop_signal = signals["zscore_stop_signal"]

    # Restrict to GDX trading dates (GDX is the position; it drives the simulation)
    dates = gdx_df.index
    n = len(dates)
    close_s = gdx_df["Close"]
    open_s = gdx_df["Open"]
    vol_s = gdx_df["Volume"]

    # Align all signals to GDX trading calendar
    entry_sig_aligned = entry_signal.reindex(dates).fillna(False)
    mean_revert_aligned = mean_revert_signal.reindex(dates).fillna(False)
    zscore_stop_aligned = zscore_stop_signal.reindex(dates).fillna(False)
    zscore_aligned = zscore.reindex(dates).fillna(0.0)

    trade_log = []
    daily_records = []

    capital = init_cash
    in_pos = False
    pending_entry = False
    pending_exit_reason = None  # set at close; executed at next open

    entry_date_ts = None
    entry_price = 0.0      # effective entry price (cost-inclusive open)
    entry_shares = 0
    entry_cost_total = 0.0
    entry_liq = False
    entry_bar_idx = -1

    for i in range(n):
        date = dates[i]
        close_i = float(close_s.iloc[i])
        open_i = float(open_s.iloc[i])

        # ── 1. Execute pending exit at today's open ───────────────────────────
        if pending_exit_reason is not None and in_pos:
            exit_price_raw = open_i
            xcost, xliq = _transaction_cost(exit_price_raw, entry_shares, close_s, vol_s, i)
            eff_xp = exit_price_raw - xcost / entry_shares
            pnl = (eff_xp - entry_price) * entry_shares
            capital += eff_xp * entry_shares

            trade_log.append({
                "entry_date": entry_date_ts.date(),
                "exit_date": date.date(),
                "entry_price": round(entry_price, 4),
                "exit_price": round(eff_xp, 4),
                "shares": entry_shares,
                "pnl": round(pnl, 2),
                "entry_cost": round(entry_cost_total, 4),
                "exit_cost": round(xcost, 4),
                "transaction_cost": round(entry_cost_total + xcost, 4),
                "liquidity_constrained": entry_liq or xliq,
                "hold_bars": i - entry_bar_idx,
                "exit_zscore": round(float(zscore_aligned.iloc[i]), 4),
                "exit_reason": pending_exit_reason,
            })

            in_pos = False
            pending_exit_reason = None
            entry_date_ts = None
            entry_bar_idx = -1

        # ── 2. Execute pending entry at today's open ──────────────────────────
        if pending_entry and not in_pos:
            if open_i > 0 and not pd.isna(open_i):
                shares = int(capital / open_i)
                if shares > 0:
                    cost, liq = _transaction_cost(open_i, shares, close_s, vol_s, i)
                    eff_ep = open_i + cost / shares
                    capital -= eff_ep * shares

                    in_pos = True
                    entry_date_ts = date
                    entry_price = eff_ep
                    entry_shares = shares
                    entry_cost_total = cost
                    entry_liq = liq
                    entry_bar_idx = i
            pending_entry = False

        # ── 3. End-of-day checks (priority order: breakdown > price-stop > revert > time) ──
        if in_pos:
            days_held = i - entry_bar_idx  # 0 on entry bar

            if bool(zscore_stop_aligned.iloc[i]) and pending_exit_reason is None:
                # Cointegration breakdown: z-score too negative (spread diverging further)
                pending_exit_reason = "ZSCORE_STOP"
            elif close_i <= entry_price * (1 - gdx_stop_loss_pct) and pending_exit_reason is None:
                # Price-based stop-loss: GDX fell > gdx_stop_loss_pct from entry
                pending_exit_reason = "GDX_STOP_LOSS"
            elif bool(mean_revert_aligned.iloc[i]) and pending_exit_reason is None:
                # Mean reversion complete: z-score returned to exit_zscore level
                pending_exit_reason = "MEAN_REVERT"
            elif days_held >= hold_days - 1 and pending_exit_reason is None:
                # Time stop: hold_days bars held → sell at open of next bar
                pending_exit_reason = "TIME_STOP"

        else:
            # Not in position: check entry signal at today's close
            if (
                not pending_entry
                and bool(entry_sig_aligned.iloc[i])
                and i < n - 1  # need a next bar to execute entry
            ):
                pending_entry = True

        # ── 4. Daily mark-to-market ───────────────────────────────────────────
        mtm = capital + (entry_shares * close_i if in_pos else 0.0)
        daily_records.append({
            "date": date,
            "position": 1 if in_pos else 0,
            "signal_type": "GDX_SPREAD" if in_pos else "",
            "zscore": round(float(zscore_aligned.iloc[i]), 4),
            "equity": mtm,
        })

    # ── Force-close any open position at end of data ──────────────────────────
    if in_pos and n > 0:
        i = n - 1
        close_f = float(close_s.iloc[i])
        xcost, xliq = _transaction_cost(close_f, entry_shares, close_s, vol_s, i)
        eff_xp = close_f - xcost / entry_shares
        pnl = (eff_xp - entry_price) * entry_shares
        capital += eff_xp * entry_shares

        trade_log.append({
            "entry_date": entry_date_ts.date(),
            "exit_date": dates[i].date(),
            "entry_price": round(entry_price, 4),
            "exit_price": round(eff_xp, 4),
            "shares": entry_shares,
            "pnl": round(pnl, 2),
            "entry_cost": round(entry_cost_total, 4),
            "exit_cost": round(xcost, 4),
            "transaction_cost": round(entry_cost_total + xcost, 4),
            "liquidity_constrained": entry_liq or xliq,
            "hold_bars": i - entry_bar_idx,
            "exit_zscore": round(float(zscore_aligned.iloc[i]), 4),
            "exit_reason": "END_OF_DATA",
        })
        if daily_records:
            daily_records[-1]["equity"] = capital

    daily_df = pd.DataFrame(daily_records)
    if not daily_df.empty:
        daily_df = daily_df.set_index("date")

    equity = daily_df["equity"] if not daily_df.empty else pd.Series(dtype=float)
    return trade_log, equity, daily_df


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download GLD and GDX data, compute spread z-score signals, and simulate H32.

    Parameters
    ----------
    start : str
        Backtest start date (YYYY-MM-DD). IS period: "2007-01-01".
    end : str
        Backtest end date (YYYY-MM-DD). IS period: "2021-12-31".
    params : dict, optional
        Override PARAMETERS dict. Uses module-level PARAMETERS if None.

    Returns
    -------
    dict
        Standard result with:
        - sharpe, max_drawdown, total_return, win_rate, profit_factor
        - trade_count, trades_per_year, pf1_status
        - entry_signals_total, regime_blocked_count, exit_reason_summary
        - trades (DataFrame), equity (Series), daily_df (DataFrame)
        - data_quality (dict)
    """
    if params is None:
        params = PARAMETERS.copy()

    gld_ticker = params["gld_ticker"]
    gdx_ticker = params["gdx_ticker"]
    init_cash = float(params["init_cash"])

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # ── 1. Download (warmup window included) ──────────────────────────────────
    data = download_data(gld_ticker, gdx_ticker, start, end, params)
    gld_full = data["gld"]
    gdx_full = data["gdx"]

    # ── 2. Compute signals on full series (warmup ensures rolling stats are warm) ─
    signals_full = compute_spread_signals(gld_full, gdx_full, params)

    # ── 3. Trim to backtest window ────────────────────────────────────────────
    gdx_df = gdx_full.loc[
        (gdx_full.index >= ts_start) & (gdx_full.index <= ts_end)
    ].copy()

    def _trim_to_window(series: pd.Series) -> pd.Series:
        return series.reindex(gdx_df.index).fillna(False)

    # Rebuild trimmed signals dict aligned to GDX backtest window
    signals_trimmed = {
        "combined": signals_full["combined"].loc[
            (signals_full["combined"].index >= ts_start) &
            (signals_full["combined"].index <= ts_end)
        ],
        "zscore": signals_full["zscore"].reindex(gdx_df.index).fillna(0.0),
        "regime_ok": signals_full["regime_ok"].reindex(gdx_df.index).fillna(False),
        "entry_signal": signals_full["entry_signal"].reindex(gdx_df.index).fillna(False),
        "mean_revert_signal": signals_full["mean_revert_signal"].reindex(gdx_df.index).fillna(False),
        "zscore_stop_signal": signals_full["zscore_stop_signal"].reindex(gdx_df.index).fillna(False),
    }

    if len(gdx_df) < 10:
        raise ValueError(
            f"Insufficient GDX data after trimming to {start}–{end}: {len(gdx_df)} bars"
        )

    # ── 4. Data quality checks ────────────────────────────────────────────────
    max_gap = 0
    if gdx_df["Close"].isna().any():
        is_na = gdx_df["Close"].isna().astype(int)
        max_gap = int(is_na.groupby((~gdx_df["Close"].isna()).cumsum()).sum().max())
    if max_gap >= 5:
        warnings.warn(f"Data gap: {max_gap} consecutive missing days in {gdx_ticker}")

    gld_in_window = gld_full.loc[
        (gld_full.index >= ts_start) & (gld_full.index <= ts_end)
    ]
    gld_na = int(gld_in_window["Close"].isna().sum())
    if gld_na > 5:
        warnings.warn(f"GLD has {gld_na} NaN values in backtest window")

    # ── 5. Simulate ───────────────────────────────────────────────────────────
    trade_log, equity, daily_df = simulate_h32(gdx_df, signals_trimmed, params)

    # ── 6. Performance metrics ────────────────────────────────────────────────
    years = (ts_end - ts_start).days / 365.25
    n_trades = len(trade_log)
    trades_per_year = round(n_trades / max(years, 1e-3), 1)

    empty_cols = [
        "entry_date", "exit_date", "entry_price", "exit_price", "shares",
        "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_bars", "exit_zscore", "exit_reason",
    ]
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=empty_cols)

    daily_returns = equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values
    sharpe = 0.0
    if len(ret_arr) > 0 and ret_arr.std() > 0:
        sharpe = round(
            float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4
        )

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)
    win_rate = round(float((trades_df["pnl"] > 0).mean()), 4) if n_trades > 0 else 0.0

    # Profit factor = sum(wins) / sum(|losses|)
    profit_factor = 0.0
    if n_trades > 0 and not trades_df.empty:
        wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = round(float(wins / losses) if losses > 0 else float("inf"), 4)

    # PF-1: ~18–25 triggers/yr × 14y IS = 252–350 → ÷4 = 63–87 ≥ 30 ✅
    pf1_threshold = 30
    trades_per_wf_fold = round(n_trades / 4, 1)
    if trades_per_wf_fold >= pf1_threshold:
        pf1_status = f"PASS ({trades_per_wf_fold:.1f}/fold ≥ {pf1_threshold})"
    else:
        pf1_status = f"WARN: {trades_per_wf_fold:.1f}/fold < {pf1_threshold}"
        warnings.warn(f"PF-1 WARN: {trades_per_wf_fold:.1f} trades/wf-fold < {pf1_threshold}")

    exit_reason_summary = {}
    if n_trades > 0:
        exit_reason_summary = trades_df["exit_reason"].value_counts().to_dict()

    # Diagnostic: count entry signals that were blocked by regime filter
    entry_sig_full_count = int(
        (signals_trimmed["zscore"] < -params["zscore_threshold"]).sum()
    )
    regime_blocked = int(
        (
            (signals_trimmed["zscore"] < -params["zscore_threshold"])
            & (~signals_trimmed["regime_ok"])
        ).sum()
    )

    print(
        f"\nH32 GLD/GDX Spread Mean Reversion ({start} to {end}):\n"
        f"  Z<-{params['zscore_threshold']:.1f} signals: {entry_sig_full_count} | "
        f"Regime-blocked: {regime_blocked} | Trades executed: {n_trades} ({trades_per_year:.1f}/yr)\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor} | "
        f"PF-1: {pf1_status}\n"
        f"  Exit reasons: {exit_reason_summary}\n"
        f"  Init cash: ${init_cash:,.0f}"
    )

    return {
        "returns": daily_returns,
        "trades": trades_df,
        "equity": equity,
        "daily_df": daily_df,
        "params": params,
        "data_quality": {
            "survivorship_bias_flag": "GLD and GDX are market ETFs — no survivorship bias",
            "price_adjusted": True,
            "auto_adjust": True,
            "warmup_bars": max(
                params["sma_window"], params["zscore_window"], SIGMA_WINDOW, ADV_WINDOW
            ) + 60,
            "gap_flags": ([f"{max_gap} consecutive missing days"] if max_gap >= 5 else []),
            "gld_na_count": gld_na,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — GLD and GDX still active",
            "gdx_inception": "2006-05-16 — IS start 2007-01-01 is within available data",
        },
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "trades_per_wf_fold": trades_per_wf_fold,
        "pf1_status": pf1_status,
        "entry_signals_total": entry_sig_full_count,
        "regime_blocked_count": regime_blocked,
        "exit_reason_summary": exit_reason_summary,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "GDX",
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H32.

    Returns a DataFrame with per-day columns:
        date, position, signal_type, pnl, entry_price, exit_price,
        transaction_cost, exit_reason

    Trade-level fields populated on the exit date; all other rows carry NaN.
    `ticker` parameter accepted for orchestrator compatibility but ignored —
    H32 always uses GDX (long) + GLD (regime filter) via PARAMETERS.
    """
    p = (params or PARAMETERS).copy()
    result = run_backtest(start, end, p)

    daily = result["daily_df"].reset_index()
    trades = result["trades"]

    if trades.empty:
        daily["pnl"] = np.nan
        daily["entry_price"] = np.nan
        daily["exit_price"] = np.nan
        daily["transaction_cost"] = np.nan
        daily["exit_reason"] = np.nan
    else:
        trade_cols = trades[
            ["exit_date", "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason"]
        ].copy()
        trade_cols["exit_date"] = pd.to_datetime(trade_cols["exit_date"])
        daily["date"] = pd.to_datetime(daily["date"])

        daily = daily.merge(
            trade_cols.rename(columns={"exit_date": "date"}),
            on="date",
            how="left",
        )

    return daily[[
        "date", "position", "signal_type",
        "pnl", "entry_price", "exit_price", "transaction_cost", "exit_reason",
    ]]


if __name__ == "__main__":
    # IS period
    result_is = run_backtest("2007-01-01", "2021-12-31")
    print(f"\n[IS] Trades: {result_is['trade_count']} | Sharpe: {result_is['sharpe']} | "
          f"Win rate: {result_is['win_rate']:.2%}")

    # OOS period
    result_oos = run_backtest("2022-01-01", "2025-12-31")
    print(f"\n[OOS] Trades: {result_oos['trade_count']} | Sharpe: {result_oos['sharpe']} | "
          f"Win rate: {result_oos['win_rate']:.2%}")

    print("\nSample IS trades (first 5):")
    if not result_is["trades"].empty:
        print(result_is["trades"].head().to_string(index=False))

    print(f"\nEquity final (IS): ${result_is['equity'].iloc[-1]:,.2f}")
    print(f"Equity final (OOS): ${result_oos['equity'].iloc[-1]:,.2f}")
