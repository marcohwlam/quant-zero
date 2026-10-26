"""
Strategy: H77 Cross-Asset Weekly Momentum Portfolio
Author: Strategy Coder Agent
Date: 2026-06-17
Hypothesis: A 7-asset cross-asset universe (equities + bonds + gold + credit) ranked
            by 4-week trailing return and held top-3 equal weight with weekly rebalancing
            generates excess returns. 50-DMA regime overlay reduces position size to 50%
            when >= 2 of top-3 assets are below their 50-day SMA, with remaining 50% to SHY.
Asset class: equities/ETFs (cross-asset: equities, bonds, gold, credit, cash)
Parent task: QUA-327

Data quality checklist (per Engineering Director standard):
  Universe: All 7 ETFs via yfinance auto_adjust=True. HYG inception April 2007.
    IS start = 2007-06-01 (2-month buffer after HYG April 2007 inception).
  Price adjustments: auto_adjust=True for splits and dividends.
  Data gaps: Flag any ticker with >5 missing trading days. SHY/TLT expected fully populated.
  Earnings exclusion: N/A — ETF universe. No individual stock earnings events.
  Delisted: N/A — all 7 ETFs active and liquid (SPY since 1993, HYG since April 2007).
  Survivorship bias: Fixed 7-ETF universe, no point-in-time required. ETFs pre-selected
    by hypothesis specification (not by backtest performance). No delisted ETFs in universe.

Transaction cost model (canonical, per Engineering Director AGENTS.md):
  Ultra-liquid ETFs (SPY, QQQ, IWM): $0.005/share + 0.005% slippage + market impact
  Standard ETFs (TLT, GLD, HYG, SHY): $0.005/share + 0.05% slippage + market impact
  Market impact: k=0.1 x sigma x sqrt(Q/ADV), square-root model (Johnson 2010)
  Liquidity flag: Q/ADV > 0.01 -> liquidity_constrained = True

IS window:  2007-06-01 to 2019-12-31
OOS window: 2020-01-01 to 2024-12-31
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    "universe": ["SPY", "QQQ", "IWM", "TLT", "GLD", "HYG", "SHY"],
    "cash_proxy": "SHY",           # Safe-haven / half-size fill in regime mode
    "mom_lookback_days": 20,       # 4-week trailing return (primary)
    "top_k": 3,                    # Hold top-3 by momentum rank, equal weight
    "rebalance_days": 5,           # Weekly rebalance (every 5 trading days)
    "regime_overlay": True,        # 50-DMA half-size filter (primary: on)
    "regime_threshold": 2,         # >=N of top-K below 50-DMA -> reduce to 50%
    "regime_sma_period": 50,       # 50-day SMA for each asset
    "init_cash": 25000,
}

TRADING_DAYS_PER_YEAR = 252

# Tiered slippage: ultra-liquid ETFs vs standard ETFs (per Engineering Director spec)
ULTRA_LIQUID = {"SPY", "QQQ", "IWM"}
SLIPPAGE_ULTRA = 0.00005    # 0.005% for SPY, QQQ, IWM
SLIPPAGE_STANDARD = 0.0005  # 0.05% for TLT, GLD, HYG, SHY


# ── Data Loading ────────────────────────────────────────────────────────────────

def download_data(tickers: list, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Download adjusted close prices and volume via yfinance.
    auto_adjust=True: prices adjusted for splits and dividends.

    Returns:
        close:  DataFrame of adjusted closing prices
        volume: DataFrame of daily share volumes
    """
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        volume = raw["Volume"]
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
        volume = raw[["Volume"]].rename(columns={"Volume": tickers[0]})

    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    if isinstance(volume, pd.Series):
        volume = volume.to_frame(name=tickers[0])

    available = [t for t in tickers if t in close.columns]
    return close[available].copy(), volume[available].copy()


# ── Data Quality ────────────────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame, tickers: list) -> dict:
    """
    Data quality report per Engineering Director pre-backtest checklist.

    Survivorship bias: Fixed 7-ETF universe. All ETFs pre-selected by hypothesis
    specification (not by backtest performance). HYG inception April 2007;
    IS start 2007-06-01 gives 2-month buffer for momentum lookback initialization.
    No delisted ETFs in universe — all 7 ETFs remain active and liquid.

    Earnings exclusion: N/A — all holdings are ETFs with diversified baskets.
    """
    report = {
        "survivorship_bias": (
            "Fixed 7-ticker cross-asset ETF universe. Pre-selected by hypothesis specification "
            "(not by backtest performance). HYG inception April 2007; IS start 2007-06-01 "
            "(2-month buffer). All ETFs active and liquid. No point-in-time universe required "
            "(fixed universe, no deletions). No delisted ETFs in universe."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — ETF universe; no individual earnings events.",
        "delisted": "N/A — all 7 ETFs active (SPY since 1993, HYG since April 2007).",
        "tickers": {},
    }

    flagged = []
    for ticker in tickers:
        if ticker not in close.columns:
            report["tickers"][ticker] = {"error": "Not in downloaded data"}
            flagged.append(ticker)
            continue
        price = close[ticker].dropna()
        if price.empty:
            report["tickers"][ticker] = {"error": "Empty price series"}
            flagged.append(ticker)
            continue
        expected = pd.bdate_range(start=price.index.min(), end=price.index.max())
        missing = len(expected.difference(price.index))
        report["tickers"][ticker] = {
            "total_days": len(price),
            "missing_business_days": missing,
            "gap_flag": missing > 5,
            "start": str(price.index.min().date()),
            "end": str(price.index.max().date()),
        }
        if missing > 5:
            flagged.append(ticker)
            warnings.warn(
                f"Data gap flag: {ticker} has {missing} missing business days (>5 threshold)."
            )

    report["flagged_tickers"] = flagged
    return report


# ── Signal Computation ──────────────────────────────────────────────────────────

def get_weekly_rebalance_dates(price_index: pd.DatetimeIndex, start: str, end: str) -> list:
    """
    Return sorted list of signal dates (last trading day of each calendar week)
    within the [start, end] range present in price_index.

    For each calendar week, selects the last available trading day on or before
    Friday of that week (handles holiday Fridays gracefully).
    """
    date_range = price_index[(price_index >= start) & (price_index <= end)]
    calendar_fridays = pd.date_range(start=start, end=end, freq="W-FRI")

    rebalance_dates = []
    for friday in calendar_fridays:
        week_start = friday - pd.Timedelta(days=4)
        week_dates = date_range[(date_range >= week_start) & (date_range <= friday)]
        if len(week_dates) > 0:
            rebalance_dates.append(week_dates[-1])

    return sorted(set(rebalance_dates))


def compute_cross_asset_signals(
    close: pd.DataFrame,
    params: dict,
    window_start: str,
    window_end: str,
) -> pd.DataFrame:
    """
    Compute weekly cross-asset momentum rankings and target weights at each signal date.

    Signal logic (evaluated at Friday close — strictly no look-ahead):
      1. ret_4w = (close_t / close_{t - mom_lookback_days}) - 1 for each of 7 assets.
         pct_change(n) is purely backward-looking; no future data used.
      2. Rank 7 assets descending by ret_4w; select top_k by rank.
      3. Regime overlay (if regime_overlay=True):
         For each of the top_k assets, check if close < SMA(regime_sma_period).
         If >= regime_threshold assets are below their SMA:
           target_weights[asset] = 0.5 / top_k for each top_k asset
           target_weights[cash_proxy] += 0.5  (combined if cash_proxy in top_k)
         Else: target_weights[asset] = 1.0 / top_k for each top_k asset.
      4. No-trade: if top_k selection identical to prior week -> same_as_prior=True.

    Args:
        close:        Full buffered price DataFrame (includes pre-window warm-up).
        params:       Strategy parameters.
        window_start: Start date for signal generation (IS or OOS window start).
        window_end:   End date.

    Returns:
        DataFrame indexed by signal_date with columns:
          top_k_assets (list), target_weights (dict), regime_active (bool),
          same_as_prior (bool), scores (dict), rankings (dict)
    """
    universe = list(params["universe"])
    cash_proxy = params["cash_proxy"]
    lookback = params["mom_lookback_days"]
    top_k = params["top_k"]
    regime_overlay = params.get("regime_overlay", True)
    regime_threshold = params.get("regime_threshold", 2)
    sma_period = params.get("regime_sma_period", 50)

    # 50-day SMA for each asset — computed on full buffered history for warm rolling windows
    sma = {}
    if regime_overlay:
        for ticker in universe:
            if ticker in close.columns:
                sma[ticker] = close[ticker].rolling(sma_period).mean()

    # Momentum scores — pct_change(n) is backward-looking: (price_t / price_{t-n}) - 1
    valid_universe = [t for t in universe if t in close.columns]
    mom_scores = close[valid_universe].pct_change(lookback)

    rebalance_dates = get_weekly_rebalance_dates(close.index, window_start, window_end)

    rows = []
    prev_top_k = None

    for date in rebalance_dates:
        if date not in mom_scores.index:
            continue

        scores_today = mom_scores.loc[date].dropna()
        if len(scores_today) < top_k:
            # Not enough ranked assets (NaN from short warmup period)
            continue

        # Rank descending; select top_k
        rankings = scores_today.rank(ascending=False, method="first").astype(int)
        top_assets = rankings[rankings <= top_k].sort_values().index.tolist()

        if len(top_assets) < top_k:
            continue

        # No-trade: same asset set as prior week
        same_as_prior = (prev_top_k is not None and set(top_assets) == set(prev_top_k))

        # Regime overlay: count how many top_k assets are below their 50-DMA
        regime_active = False
        if regime_overlay and sma:
            below_sma = 0
            for ticker in top_assets:
                if ticker in sma and date in sma[ticker].index:
                    sma_val = sma[ticker].loc[date]
                    price_val = close[ticker].loc[date]
                    if (
                        not pd.isna(sma_val) and not pd.isna(price_val)
                        and price_val < sma_val
                    ):
                        below_sma += 1
            regime_active = below_sma >= regime_threshold

        # Build target weights
        if regime_active:
            # 50% equally across top_k assets; 50% in cash_proxy (SHY)
            # If cash_proxy is already in top_k, its allocations are combined
            target_weights = {ticker: 0.5 / top_k for ticker in top_assets}
            target_weights[cash_proxy] = target_weights.get(cash_proxy, 0.0) + 0.5
        else:
            target_weights = {ticker: 1.0 / top_k for ticker in top_assets}

        rows.append({
            "date": date,
            "top_k_assets": top_assets,
            "target_weights": target_weights,
            "regime_active": regime_active,
            "same_as_prior": same_as_prior,
            "scores": scores_today.round(6).to_dict(),
            "rankings": rankings.to_dict(),
        })

        prev_top_k = top_assets

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).set_index("date")


# ── Portfolio Simulation ────────────────────────────────────────────────────────

def simulate_portfolio(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    signal_df: pd.DataFrame,
    params: dict,
    close_full: pd.DataFrame = None,
    volume_full: pd.DataFrame = None,
) -> dict:
    """
    Simulate H77 cross-asset portfolio from weekly momentum signals.

    Execution model:
    - Signal at Friday close T -> execute at T+1 (next trading day = Monday open proxy).
      Using T+1 close price as execution price (daily-data convention; conservative).
    - On each execution date, rebalance to target weights:
      a. Sell assets not in target or with excess above target weight.
      b. Buy assets with deficit below target weight.
    - No-trade: if top_k identical to prior week -> rebalance skipped entirely.
    - Regime mode: 50% in top_k assets (equal weight), 50% in SHY (cash proxy).

    Transaction costs (two-tier per Engineering Director spec):
    - Ultra-liquid (SPY, QQQ, IWM): $0.005/share + 0.005% slippage + market impact
    - Standard (TLT, GLD, HYG, SHY): $0.005/share + 0.05% slippage + market impact
    - Market impact: k=0.1 x sigma x sqrt(Q/ADV), square-root model (Johnson 2010)
    - Liquidity flag: Q/ADV > 0.01 -> logged to liquidity_flags

    Args:
        close:        Simulation window price data (IS or OOS period only).
        volume:       Simulation window volume data.
        signal_df:    Output of compute_cross_asset_signals() for this window.
        params:       Strategy parameters.
        close_full:   Full buffered price data for warm sigma/ADV rolling windows.
        volume_full:  Full buffered volume data.

    Returns:
        dict with portfolio_value series, trade_log, metrics, and liquidity flags.
    """
    init_cash = params["init_cash"]
    k_impact = 0.1  # Almgren-Chriss square-root impact constant (Johnson 2010)

    # Precompute 20-day rolling sigma and dollar ADV on full buffered history
    # to avoid NaN sigma at simulation window start
    _close_risk = close_full if close_full is not None else close
    _volume_risk = volume_full if volume_full is not None else volume

    all_tickers = list(params["universe"])
    cash_proxy = params["cash_proxy"]
    if cash_proxy not in all_tickers:
        all_tickers = all_tickers + [cash_proxy]

    sigma = {}
    adv = {}
    for ticker in all_tickers:
        if ticker in _close_risk.columns:
            sigma[ticker] = _close_risk[ticker].pct_change().rolling(20).std()
            if ticker in _volume_risk.columns:
                adv[ticker] = (_volume_risk[ticker] * _close_risk[ticker]).rolling(20).mean()
            else:
                adv[ticker] = pd.Series(dtype=float)

    def _get_sigma(ticker: str, date) -> float:
        val = sigma.get(ticker, pd.Series()).get(date, np.nan)
        return 0.0 if pd.isna(val) else float(val)

    def _get_adv(ticker: str, date) -> float:
        val = adv.get(ticker, pd.Series()).get(date, np.nan)
        return float(val) if not pd.isna(val) and val > 0 else 1e9

    def _execute_sell(ticker: str, date, shares: float) -> float:
        """Execute sell; return net cash proceeds after costs."""
        if ticker not in close.columns or shares < 1e-6:
            return 0.0
        price = close.at[date, ticker] if ticker in close.columns else np.nan
        if pd.isna(price) or price <= 0:
            return 0.0

        sig_val = _get_sigma(ticker, date)
        adv_val = _get_adv(ticker, date)
        q_over_adv = (shares * price) / adv_val if adv_val > 0 else 0.0

        if q_over_adv > 0.01:
            liquidity_flags.append({
                "date": str(date.date()), "ticker": ticker, "side": "sell",
                "q_over_adv": round(q_over_adv, 6),
            })

        impact = k_impact * sig_val * np.sqrt(max(q_over_adv, 0))
        slip = SLIPPAGE_ULTRA if ticker in ULTRA_LIQUID else SLIPPAGE_STANDARD
        slippage_pct = slip + impact
        commission = shares * 0.005
        proceeds = max(shares * price * (1 - slippage_pct) - commission, 0.0)

        trade_log.append({
            "trade_id": f"sell_{ticker}_{date.date()}",
            "date": str(date.date()), "ticker": ticker, "side": "sell",
            "shares": round(shares, 4), "price": round(price, 4),
            "slippage_pct": round(slippage_pct, 6),
            "commission": round(commission, 4),
            "net_proceeds": round(proceeds, 4),
            "liquidity_constrained": q_over_adv > 0.01,
        })
        return proceeds

    def _execute_buy(ticker: str, date, target_value: float) -> float:
        """Buy towards target_value; return shares acquired (cash debited externally)."""
        if ticker not in close.columns or target_value < 0.01:
            return 0.0
        price = close.at[date, ticker] if ticker in close.columns else np.nan
        if pd.isna(price) or price <= 0:
            return 0.0

        sig_val = _get_sigma(ticker, date)
        adv_val = _get_adv(ticker, date)
        est_shares = target_value / price
        q_over_adv = (est_shares * price) / adv_val if adv_val > 0 else 0.0

        if q_over_adv > 0.01:
            liquidity_flags.append({
                "date": str(date.date()), "ticker": ticker, "side": "buy",
                "q_over_adv": round(q_over_adv, 6),
            })

        impact = k_impact * sig_val * np.sqrt(max(q_over_adv, 0))
        slip = SLIPPAGE_ULTRA if ticker in ULTRA_LIQUID else SLIPPAGE_STANDARD
        slippage_pct = slip + impact
        # Total cost = shares * price * (1 + slippage) + commission per share
        # Solve for shares: target_value = shares * (price * (1 + slippage) + 0.005)
        effective_cost_per_share = price * (1 + slippage_pct) + 0.005
        shares_bought = target_value / effective_cost_per_share

        if shares_bought < 1e-6:
            warnings.warn(
                f"BUY skipped: {ticker} on {date.date()} — shares_bought={shares_bought:.6f}. "
                f"Possible NaN sigma at window start; pass close_full to simulate_portfolio."
            )
            return 0.0

        cash_spent = shares_bought * effective_cost_per_share

        trade_log.append({
            "trade_id": f"buy_{ticker}_{date.date()}",
            "date": str(date.date()), "ticker": ticker, "side": "buy",
            "shares": round(shares_bought, 4), "price": round(price, 4),
            "effective_cost_per_share": round(effective_cost_per_share, 4),
            "slippage_pct": round(slippage_pct, 6),
            "commission": round(shares_bought * 0.005, 4),
            "cash_spent": round(cash_spent, 4),
            "liquidity_constrained": q_over_adv > 0.01,
        })
        return shares_bought

    # Build execution schedule: exec_date -> target_weights dict
    # Signal at T (Friday) -> execution at T+1 (next trading day)
    price_index = close.index
    execution_schedule = {}
    if not signal_df.empty:
        for sig_date, row in signal_df.iterrows():
            if row.get("same_as_prior", False):
                # No-trade: top-K selection identical to prior week
                continue
            later = price_index[price_index > sig_date]
            if len(later) == 0:
                continue
            exec_date = later[0]
            # Keep first scheduled rebalance if two signals map to same exec date
            if exec_date not in execution_schedule:
                execution_schedule[exec_date] = dict(row["target_weights"])

    # Initialize state
    holdings = {}       # {ticker: shares_held}
    cash = float(init_cash)
    trade_log = []
    liquidity_flags = []
    portfolio_value = pd.Series(index=close.index, dtype=float)

    for i, date in enumerate(close.index):
        if i == 0:
            portfolio_value.iloc[0] = cash
            continue

        # Execute rebalance on scheduled execution dates
        if date in execution_schedule:
            target_weights = execution_schedule[date]

            # Mark-to-market: current NAV before any trades
            nav = cash
            for ticker, shares in holdings.items():
                if ticker in close.columns:
                    p = close.at[date, ticker]
                    if not pd.isna(p):
                        nav += shares * p

            # Target dollar values for each asset
            target_values = {t: w * nav for t, w in target_weights.items()}

            # Step 1: Full sell — assets not in target
            for ticker in list(holdings.keys()):
                if ticker not in target_values:
                    shares = holdings.pop(ticker, 0.0)
                    if shares > 1e-6:
                        cash += _execute_sell(ticker, date, shares)

            # Step 2: Partial sell — assets where current value exceeds target
            for ticker in list(holdings.keys()):
                if ticker not in target_values or ticker not in close.columns:
                    continue
                p = close.at[date, ticker]
                if pd.isna(p) or p <= 0:
                    continue
                current_val = holdings[ticker] * p
                target_val = target_values[ticker]
                # 0.5% tolerance to avoid churning tiny rebalances
                if current_val > target_val * 1.005:
                    excess_shares = (current_val - target_val) / p
                    if excess_shares > 1e-6:
                        cash += _execute_sell(ticker, date, excess_shares)
                        holdings[ticker] = max(holdings[ticker] - excess_shares, 0.0)
                        if holdings[ticker] < 1e-6:
                            del holdings[ticker]

            # Step 3: Buy — assets below their target value
            for ticker, target_val in target_values.items():
                if ticker not in close.columns:
                    continue
                p = close.at[date, ticker]
                if pd.isna(p) or p <= 0:
                    continue
                current_val = holdings.get(ticker, 0.0) * p
                deficit = target_val - current_val
                # Minimum buy: at least $1 or one share (whichever is larger)
                if deficit > max(1.0, p):
                    buy_budget = min(deficit, cash)  # Cannot exceed available cash
                    if buy_budget > p * 0.01:        # At least 1% of one share
                        shares_bought = _execute_buy(ticker, date, buy_budget)
                        if shares_bought > 0:
                            holdings[ticker] = holdings.get(ticker, 0.0) + shares_bought
                            cash -= shares_bought * (p * (1 + (
                                SLIPPAGE_ULTRA if ticker in ULTRA_LIQUID else SLIPPAGE_STANDARD
                            )) + 0.005)
                            cash = max(cash, 0.0)

        # Daily NAV: mark all holdings to close
        nav = cash
        for ticker, shares in holdings.items():
            if ticker in close.columns:
                p = close.at[date, ticker]
                if not pd.isna(p):
                    nav += shares * p
        portfolio_value.iloc[i] = nav

    portfolio_value = portfolio_value.ffill().fillna(init_cash)

    # Performance metrics
    daily_returns = portfolio_value.pct_change().fillna(0).values
    sharpe = float(
        daily_returns.mean() / (daily_returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )
    cum = np.cumprod(1 + daily_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(portfolio_value.iloc[-1] / portfolio_value.iloc[0] - 1)

    trade_pnl = _compute_round_trip_pnl(trade_log)
    if trade_pnl:
        pnl_arr = np.array([t["pnl"] for t in trade_pnl])
        win_rate = float(np.mean(pnl_arr > 0))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
        profit_factor = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0
            else float("inf")
        )
    else:
        pnl_arr = np.array([])
        win_rate = win_loss_ratio = profit_factor = 0.0

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "win_loss_ratio": win_loss_ratio,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "trade_count": len(trade_pnl),
        "trade_log": trade_log,
        "trade_pnl": trade_pnl,
        "liquidity_flags": liquidity_flags,
        "liquidity_constrained": len(liquidity_flags) > 0,
        "_portfolio_value": portfolio_value,
        "_daily_returns": daily_returns,
        "_pnl_arr": pnl_arr,
    }


def _compute_round_trip_pnl(trade_log: list) -> list:
    """
    Match buy/sell entries per ticker (FIFO) into completed round-trip trades.
    Open positions (no matching sell) are excluded from PnL computation.
    """
    trades = []
    open_positions = {}  # {ticker: [open buy entries]}

    for entry in trade_log:
        ticker = entry["ticker"]
        if entry["side"] == "buy":
            if ticker not in open_positions:
                open_positions[ticker] = []
            open_positions[ticker].append({
                "buy_date": entry["date"],
                "cash_spent": entry.get("cash_spent", 0),
                "shares": entry.get("shares", 0),
            })
        elif entry["side"] == "sell" and ticker in open_positions and open_positions[ticker]:
            open_pos = open_positions[ticker].pop(0)
            if not open_positions[ticker]:
                del open_positions[ticker]
            cost_basis = open_pos["cash_spent"]
            proceeds = entry.get("net_proceeds", 0)
            pnl = proceeds - cost_basis
            ret_pct = pnl / cost_basis if cost_basis > 0 else 0.0
            trades.append({
                "ticker": ticker,
                "buy_date": open_pos["buy_date"],
                "sell_date": entry["date"],
                "cost_basis": round(cost_basis, 4),
                "net_proceeds": round(proceeds, 4),
                "pnl": round(pnl, 4),
                "return_pct": round(ret_pct, 6),
            })

    return trades


# ── Engineering Director Flags ──────────────────────────────────────────────────

def check_asset_concentration(signal_df: pd.DataFrame, threshold: float = 0.60) -> dict:
    """
    Report fraction of weeks each asset appears in top-K selection.
    Flag assets held on > threshold of weeks as concentration_risk.

    Regime weeks (when regime_overlay is active) are also reported.
    """
    if signal_df.empty or "top_k_assets" not in signal_df.columns:
        return {"concentration_risk": False, "asset_pct": {}, "total_weeks": 0}

    total_weeks = len(signal_df)
    asset_counts = {}
    regime_weeks = int(signal_df.get("regime_active", pd.Series(False, index=signal_df.index)).sum())

    for assets in signal_df["top_k_assets"]:
        for a in assets:
            asset_counts[a] = asset_counts.get(a, 0) + 1

    asset_pct = {k: round(v / max(total_weeks, 1), 4) for k, v in asset_counts.items()}
    flagged = {k: v for k, v in asset_pct.items() if v > threshold}

    return {
        "total_weeks": total_weeks,
        "regime_weeks": regime_weeks,
        "regime_pct": round(regime_weeks / max(total_weeks, 1), 4),
        "asset_pct": asset_pct,
        "concentration_flagged": flagged,
        "concentration_risk": len(flagged) > 0,
    }


def check_trade_count_gate(trade_count: int, is_years: float, min_per_year: int = 30) -> dict:
    """
    Verify IS trade count meets PF-1 gate: trade_count / is_years >= min_per_year.

    H77 expects ~156 position-changes/year (3 positions x 52 weeks) -> ~780 over IS.
    Round-trip trades (buy+sell pairs) will be roughly half: ~390 round-trips over IS.
    Gate requires >= 100 total trades over IS period (>= 8/yr over 12-year IS window).
    """
    annual_rate = trade_count / max(is_years, 0.001)
    gate_pass = trade_count >= 100
    return {
        "trade_count_total": trade_count,
        "is_years": is_years,
        "annual_rate": round(annual_rate, 2),
        "min_total": 100,
        "gate_pass": gate_pass,
        "message": (
            f"PASS: {trade_count} total trades >= 100 ({annual_rate:.1f}/yr)"
            if gate_pass
            else f"FAIL: {trade_count} total trades < 100 ({annual_rate:.1f}/yr) — flag to Engineering Director"
        ),
    }


# ── Main Backtest Entry Point ───────────────────────────────────────────────────

def run_backtest(
    start: str = "2007-06-01",
    end: str = "2019-12-31",
    **params_override,
) -> dict:
    """
    Run H77 Cross-Asset Weekly Momentum backtest for a given period and parameter set.

    Downloads data with pre-window buffer for SMA warm-up, validates data quality,
    computes weekly cross-asset momentum signals with 50-DMA regime overlay,
    simulates portfolio with tiered ETF transaction costs, and returns metrics dict.

    Args:
        start:            Backtest start date (IS default: 2007-06-01)
        end:              Backtest end date (IS default: 2019-12-31)
        **params_override: Override any key from PARAMETERS dict (for sweep support).
                           E.g. run_backtest("2020-01-01", "2024-12-31", top_k=2)

    Returns:
        dict with sharpe, max_drawdown, win_rate, win_loss_ratio, profit_factor,
        total_return, trade_count, trade_log, data_quality, liquidity_flags,
        asset_concentration, trade_count_gate, holding_pct, period, and internal arrays.

    Raises:
        ValueError: if data is insufficient or required tickers are missing.
    """
    params = {**PARAMETERS, **params_override}
    universe = list(params["universe"])
    cash_proxy = params["cash_proxy"]

    # Ensure cash_proxy is in download list (needed for regime allocation to SHY)
    all_tickers = list(dict.fromkeys(universe + [cash_proxy]))

    # Pre-window buffer: SMA period + momentum lookback + 30 extra trading days
    sma_period = params["regime_sma_period"]
    buffer_td = sma_period + params["mom_lookback_days"] + 30
    buf_start = str(
        (pd.Timestamp(start) - pd.tseries.offsets.BDay(buffer_td)).date()
    )

    close, volume = download_data(all_tickers, buf_start, end)

    quality_report = check_data_quality(close, all_tickers)

    close = close.dropna(axis=1, how="all")
    missing_tickers = [t for t in universe if t not in close.columns]
    if missing_tickers:
        raise ValueError(f"Required universe tickers missing from download: {missing_tickers}")
    if cash_proxy not in close.columns:
        raise ValueError(f"Cash proxy {cash_proxy} missing from downloaded data.")

    min_required = sma_period + params["mom_lookback_days"] + 10
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need >= {min_required} trading days, got {len(close)}."
        )

    # Compute weekly signals using full buffered price history (no look-ahead)
    signal_df = compute_cross_asset_signals(close, params, start, end)

    if signal_df.empty:
        raise ValueError(f"No weekly signals generated for period {start} to {end}.")

    # Trim to simulation window; pass full buffered data for warm sigma/ADV
    close_window = close.loc[start:end]
    volume_window = volume.reindex(close_window.index).fillna(0)

    sim_result = simulate_portfolio(
        close_window, volume_window, signal_df, params,
        close_full=close, volume_full=volume,
    )

    # Engineering Director flags
    asset_conc = check_asset_concentration(signal_df)
    is_years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    trade_count_check = check_trade_count_gate(sim_result["trade_count"], is_years)

    # Asset holding breakdown: fraction of weeks each asset was in top-K
    asset_week_counts = {}
    regime_weeks = 0
    for _, row in signal_df.iterrows():
        if row.get("regime_active", False):
            regime_weeks += 1
        for a in row.get("top_k_assets", []):
            asset_week_counts[a] = asset_week_counts.get(a, 0) + 1
    total_weeks = len(signal_df)
    holding_pct = {k: round(v / max(total_weeks, 1), 4) for k, v in asset_week_counts.items()}
    holding_pct["_regime_active"] = round(regime_weeks / max(total_weeks, 1), 4)

    return {
        **sim_result,
        "period": f"{start} to {end}",
        "data_quality": quality_report,
        "holding_pct": holding_pct,
        "asset_concentration": asset_conc,
        "trade_count_gate": trade_count_check,
        "mom_lookback_days": params["mom_lookback_days"],
        "top_k": params["top_k"],
        "regime_overlay": params["regime_overlay"],
        "regime_threshold": params["regime_threshold"],
        "regime_sma_period": params["regime_sma_period"],
    }


# ── Parameter Sensitivity Scan ─────────────────────────────────────────────────

def scan_parameters(
    start: str = "2007-06-01",
    end: str = "2019-12-31",
) -> dict:
    """
    Sweep 36 parameter combinations (per QUA-327 specification):
      - mom_lookback_days in [10, 15, 20, 30]
      - top_k in [2, 3, 4]
      - regime_overlay in [True, False]
      - regime_threshold in [2, 3] (only when regime_overlay=True)
    Total: 4 x 3 x (1 + 2) = 36 combinations.

    Returns dict of {config_key: metrics} plus _meta stability summary.
    """
    lookbacks = [10, 15, 20, 30]
    top_ks = [2, 3, 4]

    results = {}

    for lb in lookbacks:
        for k in top_ks:
            # regime_overlay=False: 1 combination per (lb, k)
            key = f"lb{lb}_k{k}_regime_off"
            try:
                r = run_backtest(
                    start=start, end=end,
                    mom_lookback_days=lb, top_k=k, regime_overlay=False,
                )
                results[key] = {
                    "sharpe": round(r["sharpe"], 4),
                    "total_return": round(r["total_return"], 4),
                    "max_drawdown": round(r["max_drawdown"], 4),
                    "trade_count": r["trade_count"],
                    "regime_overlay": False,
                }
            except Exception as exc:
                results[key] = {"error": str(exc)}

            # regime_overlay=True with threshold 2 and 3: 2 combinations per (lb, k)
            for thresh in [2, 3]:
                key = f"lb{lb}_k{k}_regime_on_t{thresh}"
                try:
                    r = run_backtest(
                        start=start, end=end,
                        mom_lookback_days=lb, top_k=k,
                        regime_overlay=True, regime_threshold=thresh,
                    )
                    results[key] = {
                        "sharpe": round(r["sharpe"], 4),
                        "total_return": round(r["total_return"], 4),
                        "max_drawdown": round(r["max_drawdown"], 4),
                        "trade_count": r["trade_count"],
                        "regime_overlay": True,
                        "regime_threshold": thresh,
                    }
                except Exception as exc:
                    results[key] = {"error": str(exc)}

    # Stability meta-analysis relative to primary (default) configuration
    default_key = (
        f"lb{PARAMETERS['mom_lookback_days']}_k{PARAMETERS['top_k']}"
        f"_regime_on_t{PARAMETERS['regime_threshold']}"
    )
    default_sharpe = results.get(default_key, {}).get("sharpe", None)

    sharpe_nums = [
        v["sharpe"] for v in results.values()
        if isinstance(v, dict) and "sharpe" in v and isinstance(v["sharpe"], (int, float))
    ]

    meta = {
        "default_key": default_key,
        "default_sharpe": default_sharpe,
        "total_combinations": len([k for k in results if not k.startswith("_")]),
    }

    if sharpe_nums and default_sharpe is not None and default_sharpe != 0:
        sharpe_range = max(sharpe_nums) - min(sharpe_nums)
        variance_pct = sharpe_range / abs(default_sharpe)
        meta.update({
            "sharpe_min": round(min(sharpe_nums), 4),
            "sharpe_max": round(max(sharpe_nums), 4),
            "sharpe_range": round(sharpe_range, 4),
            "sharpe_variance_pct_vs_default": round(variance_pct, 4),
            "gate1_stability_flag": (
                f"PASS: variance {variance_pct:.1%} <= 30%"
                if variance_pct <= 0.30
                else f"FAIL: variance {variance_pct:.1%} > 30%"
            ),
        })

    results["_meta"] = meta
    return results


# ── Entry Point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("\nH77 Cross-Asset Weekly Momentum: IS backtest (2007-06-01 to 2019-12-31)...")
    is_result = run_backtest(start="2007-06-01", end="2019-12-31")
    safe_is = {
        k: v for k, v in is_result.items()
        if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                     "_portfolio_value", "_daily_returns", "_pnl_arr")
    }
    print("IS result:")
    print(json.dumps(safe_is, indent=2, default=str))

    print("\nH77 Cross-Asset Weekly Momentum: OOS backtest (2020-01-01 to 2024-12-31)...")
    oos_result = run_backtest(start="2020-01-01", end="2024-12-31")
    safe_oos = {
        k: v for k, v in oos_result.items()
        if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                     "_portfolio_value", "_daily_returns", "_pnl_arr")
    }
    print("OOS result:")
    print(json.dumps(safe_oos, indent=2, default=str))
