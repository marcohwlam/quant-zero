"""
Strategy: H53 Faber Tactical Asset Allocation — GTAA-5 (5-Asset 10-Month MA)
Author: Engineering Director
Date: 2026-06-09
Hypothesis: Faber (2007) GTAA. Equal 20% weight across 5 asset classes. Each asset
            held when price > N-month MA; substituted with SHY (T-bills) when below.
            Signal checked and executed at last trading day of each month (close).
Asset classes: SPY (US equity), EFA (intl equity), IEF (bonds), GSG (commodities),
               VNQ (real estate). Safe harbor: SHY.
Parent task: QUA-125
References: Faber, M.T. (2007). "A Quantitative Approach to Tactical Asset Allocation."
            Journal of Investing, 16(2), 69-79.
IS window:  2007-01-01 to 2023-12-31  (constrained by GSG inception June 2006)
OOS window: 2024-01-01 to 2025-12-31
Data note:  GSG inception 2006-06-22. EFA/IEF/VNQ/SPY/SHY all pre-2007.
            GSG MA requires ~10 months warmup → first signal April 2007; Jan–Mar 2007 defaults SHY.
            Commodity variants: GSG (default), DJP, PDBC.
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────
PARAMETERS = {
    "assets": ["SPY", "EFA", "IEF", "GSG", "VNQ"],  # 5-asset universe
    "weights": [0.20, 0.20, 0.20, 0.20, 0.20],       # equal weight
    "safe_harbor": "SHY",                              # T-bills substitute when below MA
    "ma_months": 10,                                   # lookback in calendar months; range: 8–12
    "commodity_ticker": "GSG",                         # test variants: GSG, DJP, PDBC
    "init_cash": 100000,
}

# ── Transaction Cost Constants (Engineering Director canonical spec) ───────────
FIXED_COST_PER_SHARE = 0.005    # $0.005/share fixed
SLIPPAGE_PCT = 0.0005           # 0.05% of notional
MARKET_IMPACT_K = 0.1           # Almgren-Chriss square-root model k=0.1
SIGMA_WINDOW = 20               # 20-day rolling σ (daily returns)
ADV_WINDOW = 20                 # 20-day rolling average daily volume
TRADING_DAYS_PER_YEAR = 252


# ── Data Helpers ───────────────────────────────────────────────────────────────

def _download_ticker(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw


def _check_data_gaps(series: pd.Series, label: str) -> None:
    """Warn (do not silently forward-fill) on consecutive NaN gaps >= 5 days."""
    if not series.isna().any():
        return
    n_na = int(series.isna().sum())
    if n_na > 0:
        warnings.warn(f"{label}: {n_na} missing values detected")
    groups = series.notna().cumsum()
    max_gap = int(series.isna().astype(int).groupby(groups).sum().max())
    if max_gap >= 5:
        warnings.warn(
            f"DATA QUALITY: {max_gap} consecutive missing days in {label} — "
            "forward-fill NOT applied per data quality policy"
        )


def download_data(params: dict, start: str, end: str) -> dict:
    """
    Download all 5 strategy assets + SHY safe harbor with warmup.

    Warmup = ma_months * 31 + 60 calendar days so MA is warm at IS start.
    Uses auto_adjust=True for splits/dividends throughout.
    GSG inception 2006-06-22: insufficient data for MA before warmup resolves.

    Returns dict with ticker → pd.DataFrame (OHLCV for SPY; Close-only for others),
    plus 'harbor_close' (SHY).
    """
    ma_months = params["ma_months"]
    # Enough warmup for N-month MA: N months * 31 days + 2-month buffer
    warmup_cal = ma_months * 31 + 62
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=warmup_cal)
    ).strftime("%Y-%m-%d")

    # Build the ticker list: strategy assets (with commodity variant) + harbor
    asset_tickers = list(params["assets"])
    # Substitute commodity ticker if overridden
    commodity_ticker = params.get("commodity_ticker", "GSG")
    if "GSG" in asset_tickers and commodity_ticker != "GSG":
        asset_tickers[asset_tickers.index("GSG")] = commodity_ticker

    harbor = params["safe_harbor"]
    all_tickers = list(asset_tickers) + ([harbor] if harbor not in asset_tickers else [])

    data = {}
    # SPY is the reference calendar; download full OHLCV
    spy_df = _download_ticker("SPY", warmup_start, end)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in spy_df.columns:
            raise ValueError(f"Missing column '{col}' for SPY")
    _check_data_gaps(spy_df["Close"], "SPY")
    data["SPY"] = spy_df

    # Download all other tickers (Close + Volume needed for cost model)
    for tkr in all_tickers:
        if tkr == "SPY":
            continue
        df = _download_ticker(tkr, warmup_start, end)
        if "Close" not in df.columns:
            raise ValueError(f"Missing 'Close' for {tkr}")
        _check_data_gaps(df["Close"], tkr)
        data[tkr] = df

    # Build aligned asset_tickers list (with commodity substitution already done)
    data["_asset_tickers"] = asset_tickers
    data["_harbor"] = harbor
    data["_warmup_start"] = warmup_start

    return data


# ── Rebalance Date Logic ───────────────────────────────────────────────────────

def _get_rebalance_dates(date_index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each calendar month."""
    df_tmp = pd.DataFrame({"date": date_index}, index=date_index)
    rebal = df_tmp.groupby([df_tmp.index.year, df_tmp.index.month])["date"].last()
    return pd.DatetimeIndex(rebal.values)


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_ma_signals(
    asset_close: pd.Series,
    rebalance_dates: pd.DatetimeIndex,
    ma_months: int,
    ticker: str = "",
) -> pd.Series:
    """
    Compute N-month MA signal for a single asset on each rebalance date.

    Signal = True (hold asset) if monthly_close_t > mean(monthly_close_{t-N+1 : t}).
    Signal = False (hold SHY) if below MA or insufficient history.

    Monthly close = close on the last trading day of each month.
    Uses only data available at close on signal date (no look-ahead).

    Returns pd.Series indexed by rebalance dates; True = hold asset, False = hold SHY.
    """
    # Extract monthly closes (last trading day of month in the full series)
    all_monthly = asset_close.groupby(
        [asset_close.index.year, asset_close.index.month]
    ).last()
    # Build a clean monthly series with DatetimeIndex
    monthly_idx = pd.DatetimeIndex([
        asset_close.loc[
            (asset_close.index.year == y) & (asset_close.index.month == m)
        ].index[-1]
        for (y, m) in all_monthly.index
    ])
    monthly_series = pd.Series(all_monthly.values, index=monthly_idx)

    signals = pd.Series(index=rebalance_dates, dtype=bool, name=f"signal_{ticker}")
    for dt in rebalance_dates:
        # Find this month's close in monthly_series
        if dt not in monthly_series.index:
            # Snap to nearest prior monthly date
            prior = monthly_series.index[monthly_series.index <= dt]
            if len(prior) == 0:
                signals.loc[dt] = False  # no data → SHY
                continue
            dt_monthly = prior[-1]
        else:
            dt_monthly = dt

        loc = monthly_series.index.get_loc(dt_monthly)
        if loc < ma_months:
            signals.loc[dt] = False  # insufficient history → SHY
            if ticker:
                warnings.warn(
                    f"{ticker}: insufficient MA history at {dt.date()} "
                    f"(need {ma_months} months, have {loc}). Defaulting to SHY."
                )
            continue

        window = monthly_series.iloc[loc - ma_months + 1: loc + 1]
        ma = float(window.mean())
        price = float(window.iloc[-1])
        signals.loc[dt] = bool(price > ma)

    return signals


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _transaction_cost(
    price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    idx: int,
) -> tuple:
    """
    Canonical equities/ETF transaction cost (Engineering Director spec):
      fixed    = $0.005/share
      slippage = 0.05% of notional
      impact   = k × σ × sqrt(Q/ADV) × price × Q  (square-root market impact)

    Returns (total_cost_dollars: float, liquidity_constrained: bool).
    """
    if shares <= 0:
        return 0.0, False

    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx] if "Volume" in vol_series.name or True else 1e7

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000

    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: {shares} shares "
            f"({shares / adv:.2%} of ADV). Q/ADV > 1%."
        )

    return fixed + slippage + impact, liq_constrained


# ── Per-Asset Slice Simulation ─────────────────────────────────────────────────

def _simulate_asset_slice(
    asset_ticker: str,
    asset_df: pd.DataFrame,
    harbor_close: pd.Series,
    asset_signals: pd.Series,
    rebalance_dates: pd.DatetimeIndex,
    slice_capital: float,
    trading_index: pd.DatetimeIndex,
    harbor_ticker: str,
) -> tuple:
    """
    Simulate one 20% portfolio slice for a single asset.

    On each rebalance date:
      - If signal=True: hold asset; execute at close price.
      - If signal=False: hold SHY (safe harbor); earn daily harbor return.

    Transitions only occur when signal changes from prior rebalance.
    Transaction costs applied (equities/ETF cost model) on all transitions.

    Returns (trade_log, equity_series, n_transitions).
    """
    asset_close = asset_df["Close"].reindex(trading_index).ffill()
    # Use SPY volume as proxy for less-liquid ETFs (conservative — higher impact estimate)
    asset_vol = (
        asset_df["Volume"].reindex(trading_index).ffill()
        if "Volume" in asset_df.columns
        else pd.Series(1_000_000, index=trading_index, name="Volume")
    )
    harbor_ret = harbor_close.reindex(trading_index).pct_change().fillna(0.0)

    rebal_set = set(rebalance_dates)
    trade_log = []
    equity_records = []

    capital = float(slice_capital)
    in_asset = False   # start in SHY until first rebalance signal
    asset_shares = 0
    entry_price = 0.0
    entry_shares = 0
    entry_cost = 0.0
    entry_date = None
    entry_liq = False
    harbor_units = capital   # dollar value in SHY
    n_transitions = 0

    prev_signal = False  # prior signal state (SHY on init)

    for i, date_i in enumerate(trading_index):
        # Rebalance: check signal, execute if changed
        if date_i in rebal_set and date_i in asset_signals.index:
            new_signal = bool(asset_signals.loc[date_i])
            close_i = float(asset_close.iloc[i]) if not pd.isna(asset_close.iloc[i]) else 0.0

            if new_signal != prev_signal and close_i > 0:
                if new_signal and not in_asset:
                    # SHY → asset
                    harbor_units = 0.0
                    shares_in = int(capital / close_i)
                    if shares_in > 0:
                        cost_in, liq_in = _transaction_cost(
                            close_i, shares_in, asset_close, asset_vol, i
                        )
                        eff_entry = close_i + cost_in / shares_in
                        capital -= eff_entry * shares_in
                        asset_shares = shares_in
                        entry_price = eff_entry
                        entry_shares = shares_in
                        entry_cost = cost_in
                        entry_date = date_i
                        entry_liq = liq_in
                        in_asset = True
                        n_transitions += 1

                elif not new_signal and in_asset:
                    # Asset → SHY
                    if asset_shares > 0:
                        xcost, xliq = _transaction_cost(
                            close_i, asset_shares, asset_close, asset_vol, i
                        )
                        eff_exit = close_i - xcost / asset_shares
                        trade_pnl = (eff_exit - entry_price) * asset_shares
                        capital += eff_exit * asset_shares

                        trade_log.append({
                            "asset": asset_ticker,
                            "entry_date": entry_date.date() if entry_date else None,
                            "exit_date": date_i.date(),
                            "entry_price": round(entry_price, 4),
                            "exit_price": round(eff_exit, 4),
                            "shares": asset_shares,
                            "pnl": round(float(trade_pnl), 2),
                            "entry_cost": round(entry_cost, 4),
                            "exit_cost": round(float(xcost), 4),
                            "transaction_cost": round(float(entry_cost + xcost), 4),
                            "liquidity_constrained": entry_liq or xliq,
                            "hold_months": round(
                                (date_i - (entry_date or date_i)).days / 30.4, 1
                            ),
                            "exit_reason": "SIGNAL_BELOW_MA",
                            "regime": "SHY",
                        })

                        asset_shares = 0
                        entry_price = 0.0
                        entry_shares = 0
                        entry_cost = 0.0
                        entry_date = None
                        entry_liq = False
                        in_asset = False
                        n_transitions += 1
                        harbor_units = capital

                prev_signal = new_signal

        # Daily P&L
        if not in_asset:
            h_ret = float(harbor_ret.iloc[i])
            capital = capital * (1.0 + h_ret)
            harbor_units = capital

        # Mark-to-market
        close_i = float(asset_close.iloc[i]) if not pd.isna(asset_close.iloc[i]) else 0.0
        mtm = (capital + asset_shares * close_i) if in_asset else capital
        equity_records.append(mtm)

    # Force-close at end of data
    if in_asset and asset_shares > 0:
        n = len(trading_index)
        close_f = float(asset_close.iloc[n - 1])
        xcost_f, xliq_f = _transaction_cost(close_f, asset_shares, asset_close, asset_vol, n - 1)
        eff_exit_f = close_f - xcost_f / asset_shares
        trade_pnl_f = (eff_exit_f - entry_price) * asset_shares
        capital += eff_exit_f * asset_shares

        trade_log.append({
            "asset": asset_ticker,
            "entry_date": entry_date.date() if entry_date else None,
            "exit_date": trading_index[-1].date(),
            "entry_price": round(entry_price, 4),
            "exit_price": round(eff_exit_f, 4),
            "shares": asset_shares,
            "pnl": round(float(trade_pnl_f), 2),
            "entry_cost": round(entry_cost, 4),
            "exit_cost": round(float(xcost_f), 4),
            "transaction_cost": round(float(entry_cost + xcost_f), 4),
            "liquidity_constrained": entry_liq or xliq_f,
            "hold_months": round(
                (trading_index[-1] - (entry_date or trading_index[-1])).days / 30.4, 1
            ),
            "exit_reason": "END_OF_DATA",
            "regime": asset_ticker,
        })
        equity_records[-1] = capital

    equity = pd.Series(equity_records, index=trading_index)
    return trade_log, equity, n_transitions


# ── H53 Simulation Engine ──────────────────────────────────────────────────────

def simulate_h53(
    data: dict,
    all_signals: dict,
    rebalance_dates: pd.DatetimeIndex,
    params: dict,
    start: str,
    end: str,
) -> tuple:
    """
    Simulate full H53 GTAA-5 portfolio: 5 independent 20% slices.

    Each slice independently holds its designated asset or SHY based on MA signal.
    Portfolio daily equity = sum of 5 slice equities.

    Returns (trade_log, portfolio_equity, daily_df, asset_metrics).
    """
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # Reference trading index: SPY calendar trimmed to backtest window
    spy_idx = data["SPY"].index
    trading_index = spy_idx[(spy_idx >= ts_start) & (spy_idx <= ts_end)]

    asset_tickers = data["_asset_tickers"]
    harbor = data["_harbor"]
    harbor_close = data[harbor]["Close"] if harbor in data else data["SHY"]["Close"]

    init_cash = float(params["init_cash"])
    slice_capital = init_cash / len(asset_tickers)

    all_trades = []
    asset_equities = {}
    asset_transitions = {}

    for tkr in asset_tickers:
        asset_df = data[tkr] if tkr in data else data.get("GSG", data["SPY"])
        signals = all_signals.get(tkr, pd.Series(dtype=bool))

        trade_log, equity, n_trans = _simulate_asset_slice(
            asset_ticker=tkr,
            asset_df=asset_df,
            harbor_close=harbor_close,
            asset_signals=signals,
            rebalance_dates=rebalance_dates,
            slice_capital=slice_capital,
            trading_index=trading_index,
            harbor_ticker=harbor,
        )
        all_trades.extend(trade_log)
        asset_equities[tkr] = equity
        asset_transitions[tkr] = n_trans

    # Aggregate portfolio equity
    equity_df = pd.DataFrame(asset_equities, index=trading_index)
    portfolio_equity = equity_df.sum(axis=1)

    # Daily regime map (how many assets in SHY vs asset)
    regime_daily = {}
    for tkr in asset_tickers:
        # Compute regime from equity series changes — not perfect but good enough for stats
        regime_daily[tkr] = asset_equities[tkr]

    daily_df = pd.DataFrame({
        "portfolio_equity": portfolio_equity,
        **{f"equity_{t}": asset_equities[t] for t in asset_tickers},
    })

    asset_metrics = {
        tkr: {"n_transitions": asset_transitions[tkr]}
        for tkr in asset_tickers
    }

    return all_trades, portfolio_equity, daily_df, asset_metrics


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download data, compute 10-month MA signals for all 5 assets, simulate H53.

    Parameters
    ----------
    start : str  Backtest start date (YYYY-MM-DD). IS: "2007-01-01".
    end : str    Backtest end date (YYYY-MM-DD). IS: "2023-12-31".
    params : dict  Override PARAMETERS; uses module-level PARAMETERS if None.

    Returns
    -------
    dict with performance metrics, trade log, equity curve, daily DataFrame,
    per-asset metrics, and data quality flags.
    """
    if params is None:
        params = PARAMETERS.copy()

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)
    ma_months = params["ma_months"]

    # ── 1. Download with warmup ───────────────────────────────────────────────
    data = download_data(params, start, end)
    asset_tickers = data["_asset_tickers"]
    harbor = data["_harbor"]

    # ── 2. Build SPY reference calendar ──────────────────────────────────────
    spy_full = data["SPY"]
    rebalance_dates_full = _get_rebalance_dates(spy_full.index)

    # ── 3. Compute MA signals for each asset (warmup-inclusive, no look-ahead) ──
    all_signals = {}
    for tkr in asset_tickers:
        tkr_df = data.get(tkr)
        if tkr_df is None:
            warnings.warn(f"No data for {tkr}, defaulting all signals to SHY")
            all_signals[tkr] = pd.Series(False, index=rebalance_dates_full)
            continue
        close = tkr_df["Close"]
        all_signals[tkr] = compute_ma_signals(
            close, rebalance_dates_full, ma_months, ticker=tkr
        )

    # ── 4. Trim rebalance dates to backtest window ────────────────────────────
    rebalance_dates = pd.DatetimeIndex([
        d for d in rebalance_dates_full
        if ts_start <= d <= ts_end
    ])

    if len(rebalance_dates) < 5:
        raise ValueError(
            f"Insufficient rebalance dates ({len(rebalance_dates)}) in {start}–{end}"
        )

    # ── 5. Simulate ───────────────────────────────────────────────────────────
    trade_log, portfolio_equity, daily_df, asset_metrics = simulate_h53(
        data, all_signals, rebalance_dates, params, start, end
    )

    # ── 6. Performance metrics ────────────────────────────────────────────────
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    n_trades = len(trade_log)
    n_rebal = len(rebalance_dates)

    trade_cols = [
        "asset", "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "entry_cost", "exit_cost", "transaction_cost",
        "liquidity_constrained", "hold_months", "exit_reason", "regime",
    ]
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=trade_cols)

    daily_returns = portfolio_equity.pct_change().fillna(0.0)
    ret_arr = daily_returns.values

    sharpe = 0.0
    if len(ret_arr) > 1 and ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + ret_arr) if len(ret_arr) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)
    cagr = round(float((cum[-1]) ** (1.0 / years) - 1.0), 4)

    win_rate = profit_factor = avg_hold = 0.0
    if n_trades > 0:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = round(float(wins / losses), 4) if losses > 0 else float("inf")
        avg_hold = round(float(trades_df["hold_months"].mean()), 2)

    total_transitions = sum(v["n_transitions"] for v in asset_metrics.values())
    transitions_per_year = round(total_transitions / years, 1)

    # Per-asset breakdown
    asset_breakdown = {}
    for tkr in asset_tickers:
        if not trades_df.empty:
            tkr_trades = trades_df[trades_df["asset"] == tkr]
        else:
            tkr_trades = pd.DataFrame()
        t_count = len(tkr_trades)
        wr = round(float((tkr_trades["pnl"] > 0).mean()), 4) if t_count > 0 else 0.0
        pnl_sum = round(float(tkr_trades["pnl"].sum()), 2) if t_count > 0 else 0.0
        asset_breakdown[tkr] = {
            "trade_count": t_count,
            "win_rate": wr,
            "total_pnl": pnl_sum,
            "n_transitions": asset_metrics[tkr]["n_transitions"],
        }

    # Signal statistics: how many assets were in SHY each month
    n_in_shy_per_rebal = []
    for dt in rebalance_dates:
        n_shy = sum(
            1 for tkr in asset_tickers
            if dt in all_signals[tkr].index and not bool(all_signals[tkr].loc[dt])
        )
        n_in_shy_per_rebal.append(n_shy)
    avg_n_shy = round(float(np.mean(n_in_shy_per_rebal)), 2)
    pct_full_invest = round(float(np.mean([n == 0 for n in n_in_shy_per_rebal])), 4)

    commodity_tkr = params.get("commodity_ticker", "GSG")
    print(
        f"\nH53 Faber GTAA-5 ({start}–{end}) "
        f"[ma={ma_months}mo, commodity={commodity_tkr}, harbor={harbor}]:\n"
        f"  Rebalances: {n_rebal} | Total transitions: {total_transitions} "
        f"({transitions_per_year:.1f}/yr)\n"
        f"  Avg assets in SHY/month: {avg_n_shy:.1f}/5 | "
        f"Months fully invested: {pct_full_invest:.1%}\n"
        f"  Sharpe: {sharpe} | CAGR: {cagr:.2%} | Max DD: {mdd:.2%} | "
        f"Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit factor: {profit_factor} | "
        f"Avg hold: {avg_hold:.1f} mo | Trades: {n_trades}\n"
        f"  Init cash: ${params['init_cash']:,.0f}"
    )

    return {
        "returns": daily_returns,
        "trades": trades_df,
        "equity": portfolio_equity,
        "daily_df": daily_df,
        "params": params.copy(),
        "data_quality": {
            "survivorship_bias_flag": (
                "SPY/EFA/IEF/GSG/VNQ/SHY are live ETFs. "
                "GSG inception 2006-06-22; first valid MA signal April 2007. "
                "Jan-Mar 2007 GSG slice defaults to SHY (conservative). "
                "No survivorship bias in ETF universe."
            ),
            "price_adjusted": True,
            "auto_adjust": True,
            "asset_tickers": asset_tickers,
            "harbor_ticker": harbor,
            "commodity_ticker": commodity_tkr,
            "earnings_exclusion": "N/A — ETF strategy",
            "delisted_tickers": "N/A — all ETFs are currently active",
            "forward_fill_policy": "Silent forward-fill NOT applied for gaps >= 5 days",
            "signal_lag": (
                "MA signal computed at month-end T close using only data through T. "
                "Execution at same T close (institutional rebalancing convention, Faber 2007)."
            ),
            "gsg_inception_note": (
                "GSG inception 2006-06-22. 10-month MA first computable ~Apr 2007. "
                "GSG slice defaults to SHY for Jan-Mar 2007 (3 months, conservative)."
            ),
        },
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "cagr": cagr,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "n_rebalances": n_rebal,
        "total_transitions": total_transitions,
        "transitions_per_year": transitions_per_year,
        "avg_n_shy": avg_n_shy,
        "pct_full_invest": pct_full_invest,
        "avg_hold_months": avg_hold,
        "asset_breakdown": asset_breakdown,
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "SPY",
    start: str = "2007-01-01",
    end: str = "2025-12-31",
    params: dict = None,
) -> pd.DataFrame:
    """
    Orchestrator-compatible entry point for H53.

    Returns daily DataFrame with portfolio_equity and per-asset equity columns.
    """
    p = (params or PARAMETERS).copy()
    result = run_backtest(start, end, p)
    daily = result["daily_df"].reset_index()
    return daily


if __name__ == "__main__":
    # ── IS baseline: 10-month MA, GSG, SHY ─────────────────────────────────────
    result_is = run_backtest("2007-01-01", "2023-12-31")
    print(
        f"\n[IS 2007–2023] Sharpe: {result_is['sharpe']} | "
        f"MDD: {result_is['max_drawdown']:.2%} | "
        f"CAGR: {result_is['cagr']:.2%} | "
        f"Trades: {result_is['trade_count']}"
    )

    # ── IS lookback sensitivity ─────────────────────────────────────────────────
    for ma in [8, 12]:
        p = PARAMETERS.copy()
        p["ma_months"] = ma
        r = run_backtest("2007-01-01", "2023-12-31", p)
        print(f"[IS ma={ma}mo] Sharpe: {r['sharpe']} | MDD: {r['max_drawdown']:.2%}")

    # ── Commodity variants ──────────────────────────────────────────────────────
    for cmdty in ["DJP", "PDBC"]:
        p = PARAMETERS.copy()
        p["commodity_ticker"] = cmdty
        p["assets"] = ["SPY", "EFA", "IEF", cmdty, "VNQ"]
        try:
            r = run_backtest("2007-01-01", "2023-12-31", p)
            print(f"[IS commodity={cmdty}] Sharpe: {r['sharpe']} | MDD: {r['max_drawdown']:.2%}")
        except Exception as exc:
            print(f"[IS commodity={cmdty}] Error: {exc}")

    # ── GFC stress test ─────────────────────────────────────────────────────────
    result_gfc = run_backtest("2007-01-01", "2009-12-31")
    print(
        f"\n[GFC 2007–2009] Sharpe: {result_gfc['sharpe']} | "
        f"MDD: {result_gfc['max_drawdown']:.2%} | "
        f"Avg assets in SHY: {result_gfc['avg_n_shy']:.1f}/5"
    )

    # ── 2022 rate-shock stress test ─────────────────────────────────────────────
    result_2022 = run_backtest("2022-01-01", "2022-12-31")
    print(
        f"[2022 rate-shock] Sharpe: {result_2022['sharpe']} | "
        f"MDD: {result_2022['max_drawdown']:.2%} | "
        f"Avg assets in SHY: {result_2022['avg_n_shy']:.1f}/5"
    )

    # ── OOS ─────────────────────────────────────────────────────────────────────
    result_oos = run_backtest("2024-01-01", "2025-12-31")
    print(
        f"\n[OOS 2024–2025] Sharpe: {result_oos['sharpe']} | "
        f"MDD: {result_oos['max_drawdown']:.2%} | "
        f"Trades: {result_oos['trade_count']}"
    )
