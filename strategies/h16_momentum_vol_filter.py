"""
Strategy: H16 Momentum + Volatility Effect (Long-Only)
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: Monthly long-only strategy: sort S&P 500 large-cap universe by 6m realized
            volatility, then by 6m momentum within the top-vol group. Long Q5 (highest
            momentum within high-vol group), equal-weighted, monthly rebalance.
            Cao & Han (2016): momentum is strongest among high-volatility stocks where
            behavioral biases (underreaction, herding) are most pronounced.
Asset class: equities
Parent task: QUA-172 / QUA-165
References:
  - Jegadeesh & Titman (1993) "Returns to Buying Winners" — JF 48(1)
  - Cao & Han (2016) "Idiosyncratic Risk, Costly Arbitrage, and the Cross-Section of
    Stock Returns" — JFE 119(3), 519-536
  - QC Learning: Momentum and Reversal Combined with Volatility Effect in Stocks
    https://www.quantconnect.com/learning/articles/investment-strategy-library/

IS window:  2000-01-01 to 2020-12-31 (20 years)
OOS window: 2021-01-01 to 2024-12-31

SURVIVORSHIP BIAS WARNING:
  Universe is a fixed list of ~87 current S&P 500 large-cap stocks. This introduces
  survivorship bias because stocks that went bankrupt or were delisted between 2000 and
  2024 are excluded (e.g., Enron, Lehman Brothers, Bear Stearns, Washington Mutual).
  The effect overstates performance, particularly in crash regimes (2001-02, 2008-09).
  Alternative (CRSP/Fama-French point-in-time data) was not used due to
  pandas_datareader API availability constraints.
  Workaround chosen: option 2 per Engineering Director spec (top large-caps from yfinance
  with survivorship bias documented explicitly as Gate 1 caveat).

LONG-ONLY ONLY: This implementation is long Q5 only. The short leg (Q1) is NOT
  implemented. Research Director approval is for long-only variant only.

Transaction cost model (canonical, per Engineering Director AGENTS.md):
  - Fixed: $0.005/share
  - Slippage: 0.05% of trade value
  - Market impact: k × σ × sqrt(Q / ADV), k=0.1 (Almgren-Chriss square-root model)
  - Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Universe ──────────────────────────────────────────────────────────────────
# Fixed list of ~87 S&P 500 large-cap stocks with long public trading history.
# SURVIVORSHIP BIAS: uses current members only; delisted stocks (2000-2024) excluded.
# This overstates IS returns in crash regimes. Documented as Gate 1 caveat.
LARGE_CAP_UNIVERSE = [
    # Technology (13)
    "AAPL", "MSFT", "IBM", "INTC", "CSCO", "ORCL", "QCOM", "TXN",
    "ADI", "AMAT", "MU", "GLW", "HPQ",
    # Communication Services (4)
    "VZ", "T", "DIS", "CMCSA",
    # Consumer Discretionary (8)
    "AMZN", "HD", "NKE", "MCD", "TGT", "LOW", "SBUX", "YUM",
    # Consumer Staples (8)
    "WMT", "PG", "KO", "PEP", "COST", "CL", "MDLZ", "KMB",
    # Energy (10)
    "XOM", "CVX", "COP", "SLB", "OXY", "HAL", "DVN", "EOG", "PSX", "VLO",
    # Financials (12)
    "JPM", "BAC", "WFC", "C", "GS", "MS", "AXP", "USB", "PNC",
    "COF", "BK", "STT",
    # Healthcare (10)
    "JNJ", "PFE", "MRK", "ABT", "LLY", "AMGN", "BMY", "MDT", "UNH", "HUM",
    # Industrials (10)
    "GE", "HON", "CAT", "MMM", "UPS", "FDX", "LMT", "RTX", "DE", "EMR",
    # Materials (5)
    "DD", "APD", "ECL", "NEM", "FCX",
    # Real Estate (2)
    "SPG", "PSA",
    # Utilities (5)
    "NEE", "DUK", "SO", "AEP", "EXC",
]

# ── Parameters ────────────────────────────────────────────────────────────────

PARAMETERS = {
    # Core signal parameters
    "formation_months": 6,       # lookback for momentum and vol signal [3, 6, 9]
    "vol_filter_pct": 0.20,      # top fraction by realized vol to keep [0.15, 0.20, 0.25]
    # Universe filters
    "universe": LARGE_CAP_UNIVERSE,
    "min_price": 5.0,            # minimum stock price filter
    "min_history_mult": 0.7,     # require formation_months * mult days of data
    # Portfolio construction
    "init_cash": 25000,          # starting capital ($)
    "order_qty": 500,            # approx shares per trade for market impact calc
}

TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ──────────────────────────────────────────────────────────────

def download_data(
    tickers: list, start: str, end: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Download adjusted close prices and volume via yfinance.
    auto_adjust=True: prices adjusted for splits and dividends.

    Returns:
        close:  DataFrame of adjusted closing prices (columns = tickers)
        volume: DataFrame of daily share volumes (columns = tickers)
    """
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        volume = raw["Volume"]
    else:
        # Single-ticker fallback
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
        volume = raw[["Volume"]].rename(columns={"Volume": tickers[0]})

    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    if isinstance(volume, pd.Series):
        volume = volume.to_frame(name=tickers[0])

    available = [t for t in tickers if t in close.columns]
    return close[available].copy(), volume[available].copy()


# ── Data Quality ──────────────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame, tickers: list) -> dict:
    """
    Data quality report per Engineering Director pre-backtest checklist.

    Survivorship bias: Fixed large-cap universe (current S&P 500 members).
    Stocks delisted 2000-2024 are excluded, overstating IS returns in crash regimes.
    Gate 1 caveat: survivorship bias overstates performance by est. 1-3% annually
    based on academic literature (Elton et al., 1996).
    """
    report = {
        "survivorship_bias": (
            "WARN: Fixed 87-ticker universe uses current S&P 500 large-caps only. "
            "Survivorship bias present: stocks delisted 2000-2024 (e.g., Lehman, Enron, "
            "Bear Stearns) excluded. Estimated impact: +1-3% annual alpha inflation "
            "(Elton et al. 1996). Documented as Gate 1 caveat per Engineering Director spec."
        ),
        "universe_method": (
            "Option 2 per task spec: top large-caps from yfinance with documented bias. "
            "CRSP/Fama-French point-in-time data was the preferred alternative but "
            "requires pandas_datareader which has API availability constraints."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": (
            "N/A — strategy uses monthly rebalancing. Earnings events within a month "
            "are not individually excluded (consistent with QC source implementation)."
        ),
        "long_only_flag": "Long Q5 only. Short leg (Q1) NOT implemented per Research Director approval.",
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


# ── Signal Computation ────────────────────────────────────────────────────────

def compute_monthly_allocations(
    close: pd.DataFrame,
    params: dict,
    start: str,
    end: str,
) -> dict:
    """
    Compute Q5 long portfolio for each monthly rebalance date in [start, end].

    Two-step cross-sectional sort (Cao & Han 2016):
      Step 1 — Volatility filter:
        Compute 6m (formation_months) realized vol for each eligible stock.
        Keep top vol_filter_pct (default 20%) — the "high-vol group".
      Step 2 — Momentum sort:
        Within the high-vol group, sort by 6m momentum (total return).
        Long the top quintile (Q5, top 20%) — highest momentum winners.

    No look-ahead: signal at month-end T uses only prices ≤ T.
    Execution on first trading day of T+1 (implemented in simulate_portfolio).

    Args:
        close: DataFrame of adjusted close prices (full history including buffer)
        params: strategy parameters
        start:  first date of backtest window (signals from here onward)
        end:    last date of backtest window

    Returns:
        dict of {signal_date (Timestamp): [ticker, ...]} — list of Q5 long tickers
    """
    formation_td = params["formation_months"] * TRADING_DAYS_PER_MONTH
    # Require at least 70% of formation window to avoid sparse data
    min_required = int(formation_td * params["min_history_mult"])
    min_price = params["min_price"]
    vol_filter_pct = params["vol_filter_pct"]

    # Month-end dates within backtest window (last calendar day of each month)
    month_ends = pd.date_range(start=start, end=end, freq="ME")

    allocations = {}
    for month_end in month_ends:
        # Snap to last available trading day ≤ month_end
        available_dates = close.index[close.index <= month_end]
        if len(available_dates) == 0:
            continue
        signal_date = available_dates[-1]

        # Use data strictly up to signal_date (backward-looking)
        data_subset = close.loc[:signal_date]

        eligible = {}
        for ticker in close.columns:
            price_series = data_subset[ticker].dropna()
            if len(price_series) < min_required:
                continue
            current_price = float(price_series.iloc[-1])
            if current_price < min_price:
                continue

            # Use up to formation_td trading days for signal computation
            lookback = min(formation_td, len(price_series) - 1)
            if lookback < min_required:
                continue

            # 6m momentum: total return over formation window
            momentum = float(price_series.iloc[-1] / price_series.iloc[-lookback] - 1)

            # 6m realized volatility: annualized std of daily returns over formation window
            recent_prices = price_series.iloc[-lookback:]
            daily_rets = recent_prices.pct_change().dropna()
            if len(daily_rets) < int(lookback * 0.5):
                continue
            vol = float(daily_rets.std() * np.sqrt(TRADING_DAYS_PER_YEAR))

            eligible[ticker] = {"momentum": momentum, "vol": vol}

        if len(eligible) < 5:
            # Not enough stocks to form a meaningful portfolio
            allocations[signal_date] = []
            continue

        # Step 1: Sort by vol → keep top vol_filter_pct (high-vol group)
        tickers_list = list(eligible.keys())
        n_vol_keep = max(2, int(len(tickers_list) * vol_filter_pct))
        vol_sorted = sorted(tickers_list, key=lambda t: eligible[t]["vol"], reverse=True)
        high_vol_group = vol_sorted[:n_vol_keep]

        if len(high_vol_group) < 2:
            allocations[signal_date] = []
            continue

        # Step 2: Sort by momentum → top quintile (Q5, top 20%) within high-vol group
        # Q5 = int(N/5): with 15 stocks → 3 positions; with 20 → 4 positions
        mom_sorted = sorted(
            high_vol_group,
            key=lambda t: eligible[t]["momentum"],
            reverse=True,
        )
        n_q5 = max(1, len(high_vol_group) // 5)
        q5_longs = mom_sorted[:n_q5]

        allocations[signal_date] = q5_longs

    return allocations


# ── Portfolio Simulation ──────────────────────────────────────────────────────

def simulate_portfolio(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    monthly_alloc: dict,
    params: dict,
) -> dict:
    """
    Simulate H16 long-only portfolio with full monthly rebalance.

    Execution model:
    - Signal at month-end T → execute on first trading day of T+1 (no look-ahead).
    - Full rebalance each month: sell ALL positions, then buy new equal-weight Q5 longs.
    - Equal-weight: total portfolio value / n_positions per position.
    - Transaction costs applied on both buys and sells.

    Transaction cost model (canonical):
    - Fixed: $0.005/share
    - Slippage: 0.05% of trade value
    - Market impact: k × σ × sqrt(Q / ADV), k=0.1 (Almgren-Chriss)

    Args:
        close:        DataFrame of adjusted close prices
        volume:       DataFrame of daily share volumes
        monthly_alloc: {signal_date: [ticker, ...]} from compute_monthly_allocations
        params:       strategy parameters

    Returns:
        dict with sharpe, max_drawdown, win_rate, win_loss_ratio, profit_factor,
        total_return, trade_count, trade_log, trade_pnl, liquidity_flags,
        _portfolio_value, _daily_returns, _pnl_arr.
    """
    init_cash = params["init_cash"]
    k_impact = 0.1   # Almgren-Chriss market impact constant

    # Precompute sigma (20-day rolling daily return std) and ADV (dollar vol) for impact
    sigma_df = {}
    adv_df = {}
    for ticker in close.columns:
        if ticker in volume.columns:
            sigma_df[ticker] = close[ticker].pct_change().rolling(20).std()
            # ADV in dollar terms: rolling 20-day average of (volume × close)
            adv_df[ticker] = (volume[ticker] * close[ticker]).rolling(20).mean()

    # Build execution schedule: {exec_date: [tickers to hold]}
    # Signal at month_end → first trading day strictly after month_end
    exec_schedule = {}
    for signal_date in sorted(monthly_alloc.keys()):
        future_days = close.index[close.index > signal_date]
        if len(future_days) == 0:
            continue
        exec_date = future_days[0]
        exec_schedule[exec_date] = monthly_alloc[signal_date]

    # Daily portfolio simulation
    portfolio_value = pd.Series(np.nan, index=close.index, dtype=float)
    portfolio_value.iloc[0] = float(init_cash)

    current_positions = {}   # ticker → shares held (float)
    cash = float(init_cash)
    trade_log = []
    liquidity_flags = []

    def _get_mkt_vals(date: pd.Timestamp, ticker: str, shares: float):
        """Helper: get price, sigma, ADV for a ticker on date."""
        price = float(close.at[date, ticker]) if ticker in close.columns else np.nan
        sig = float(sigma_df.get(ticker, pd.Series()).get(date, 0) or 0)
        if np.isnan(sig):
            sig = 0.0
        adv = float(adv_df.get(ticker, pd.Series()).get(date, np.nan))
        if np.isnan(adv) or adv <= 0:
            adv = 1e12   # fallback: treat as highly liquid
        return price, sig, adv

    def _sell(date: pd.Timestamp, ticker: str, shares: float):
        nonlocal cash
        price, sig, adv = _get_mkt_vals(date, ticker, shares)
        if np.isnan(price) or price <= 0 or shares <= 0:
            return 0.0
        q_over_adv = (shares * price) / adv
        if q_over_adv > 0.01:
            liquidity_flags.append({
                "date": str(date.date()), "ticker": ticker,
                "side": "sell", "q_over_adv": round(q_over_adv, 6),
            })
        # Market impact (Almgren-Chriss square-root model)
        impact = k_impact * sig * np.sqrt(max(q_over_adv, 0))
        slippage = 0.0005 + impact          # 0.05% + market impact
        # Net proceeds: gross - slippage - fixed commission ($0.005/share)
        proceeds = shares * price * (1 - slippage) - shares * 0.005
        proceeds = max(proceeds, 0.0)
        cash += proceeds
        trade_log.append({
            "date": str(date.date()), "ticker": ticker, "side": "sell",
            "shares": round(shares, 4), "price": round(price, 4),
            "slippage_pct": round(slippage, 6), "commission": round(shares * 0.005, 4),
            "net_proceeds": round(proceeds, 4),
            "liquidity_constrained": q_over_adv > 0.01,
        })
        return proceeds

    def _buy(date: pd.Timestamp, ticker: str, cash_alloc: float):
        nonlocal cash
        price, sig, adv = _get_mkt_vals(date, ticker, 0)
        if np.isnan(price) or price <= 0 or cash_alloc <= 0:
            return 0.0
        est_shares = cash_alloc / price
        q_over_adv = (est_shares * price) / adv
        if q_over_adv > 0.01:
            liquidity_flags.append({
                "date": str(date.date()), "ticker": ticker,
                "side": "buy", "q_over_adv": round(q_over_adv, 6),
            })
        impact = k_impact * sig * np.sqrt(max(q_over_adv, 0))
        slippage = 0.0005 + impact
        # Effective cost per share (price × (1 + slippage)) + $0.005 commission
        effective_cost = price * (1 + slippage)
        shares_bought = cash_alloc / (effective_cost + 0.005)
        commission = shares_bought * 0.005
        cash_spent = shares_bought * effective_cost + commission
        cash -= cash_spent
        cash = max(cash, 0.0)
        trade_log.append({
            "date": str(date.date()), "ticker": ticker, "side": "buy",
            "shares": round(shares_bought, 4), "price": round(price, 4),
            "effective_cost": round(effective_cost, 4),
            "slippage_pct": round(slippage, 6), "commission": round(commission, 4),
            "cash_spent": round(cash_spent, 4),
            "liquidity_constrained": q_over_adv > 0.01,
        })
        return shares_bought

    for i, date in enumerate(close.index):
        if i == 0:
            portfolio_value.iloc[0] = cash
            continue

        # Execute monthly rebalance if scheduled for this date
        if date in exec_schedule:
            target_tickers = [
                t for t in exec_schedule[date]
                if t in close.columns and not pd.isna(close.at[date, t])
            ]

            # 1. Sell ALL current positions (full rebalance each month)
            for ticker, shares in list(current_positions.items()):
                _sell(date, ticker, shares)
            current_positions.clear()

            # 2. Buy new Q5 longs with equal weight
            if target_tickers and cash > 0:
                cash_per_position = cash / len(target_tickers)
                for ticker in target_tickers:
                    shares = _buy(date, ticker, cash_per_position)
                    if shares > 0:
                        current_positions[ticker] = shares

        # Daily portfolio valuation: mark-to-market all positions + cash
        pos_value = 0.0
        for ticker, shares in current_positions.items():
            if ticker in close.columns:
                price = close.at[date, ticker]
                if not np.isnan(price):
                    pos_value += shares * price
        portfolio_value.iloc[i] = pos_value + cash

    # Forward-fill any NaN gaps (e.g., pre-first-trade period)
    portfolio_value = portfolio_value.ffill().fillna(float(init_cash))

    # Compute portfolio-level metrics
    daily_returns = portfolio_value.pct_change().fillna(0).values
    sharpe = float(
        daily_returns.mean() / (daily_returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )
    cum = np.cumprod(1 + daily_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(portfolio_value.iloc[-1] / portfolio_value.iloc[0] - 1)

    # Trade-level statistics
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
        "trade_count": len(trade_pnl),   # round-trip count
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
    Match each buy with the subsequent sell for the same ticker to compute
    round-trip PnL. Open positions without a closing sell are excluded.

    Returns: list of {ticker, buy_date, sell_date, cost_basis, net_proceeds, pnl, return_pct}
    """
    open_positions = {}   # ticker → {buy_date, cash_spent, shares}
    trades = []

    for entry in trade_log:
        ticker = entry["ticker"]
        if entry["side"] == "buy":
            # If already open, close it first (should not happen with full rebalance logic)
            if ticker not in open_positions:
                open_positions[ticker] = {
                    "buy_date": entry["date"],
                    "cash_spent": entry.get("cash_spent", 0.0),
                    "shares": entry.get("shares", 0.0),
                }
        elif entry["side"] == "sell" and ticker in open_positions:
            open_pos = open_positions.pop(ticker)
            cost_basis = open_pos["cash_spent"]
            proceeds = entry.get("net_proceeds", 0.0)
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


# ── Main Backtest Entry Point ─────────────────────────────────────────────────

def run_backtest(
    params: dict = PARAMETERS,
    start: str = "2000-01-01",
    end: str = "2020-12-31",
) -> dict:
    """
    Run H16 Momentum + Vol Filter backtest for a given period and parameter set.

    Downloads price/volume data, validates quality, computes monthly Q5 allocations,
    simulates portfolio with full transaction costs, and returns standardized metrics dict.

    Args:
        params: strategy parameters (see PARAMETERS constant)
        start:  backtest start date (inclusive)
        end:    backtest end date (inclusive)

    Returns:
        dict with sharpe, max_drawdown, win_rate, win_loss_ratio, profit_factor,
        total_return, trade_count, trade_log, data_quality, liquidity_flags,
        period, and internal arrays for statistical tests.

    Raises:
        ValueError: if data is insufficient for the requested formation period.
    """
    tickers = params["universe"]
    formation_td = params["formation_months"] * TRADING_DAYS_PER_MONTH

    # Download with a buffer before start to populate the formation-period lookback
    buffer_months = params["formation_months"] + 2
    buf_start = str((pd.Timestamp(start) - pd.DateOffset(months=buffer_months)).date())

    close, volume = download_data(tickers, buf_start, end)

    # Data quality check
    quality_report = check_data_quality(close, tickers)

    close = close.dropna(axis=1, how="all")
    available_tickers = list(close.columns)

    if len(available_tickers) < 10:
        raise ValueError(
            f"Insufficient tickers: need ≥ 10, got {len(available_tickers)}. "
            "Check yfinance connectivity."
        )

    # Verify sufficient total history
    min_required_days = formation_td + 20
    if len(close) < min_required_days:
        raise ValueError(
            f"Insufficient data: need ≥ {min_required_days} trading days, got {len(close)}."
        )

    # Compute monthly Q5 allocations (backward-looking, no look-ahead)
    monthly_alloc = compute_monthly_allocations(close, params, start, end)

    # Trim to the actual backtest window for simulation
    close_window = close.loc[start:end]
    volume_window = volume.reindex(close_window.index, fill_value=0)

    # Only pass allocations whose signal dates fall within (or just before) the window
    alloc_in_window = {
        k: v for k, v in monthly_alloc.items()
        if k >= (pd.Timestamp(start) - pd.DateOffset(months=1))
    }

    if not alloc_in_window:
        raise ValueError(f"No monthly allocations generated for period {start} to {end}.")

    sim_result = simulate_portfolio(close_window, volume_window, alloc_in_window, params)

    # Average portfolio size (positions per month)
    non_empty = [v for v in monthly_alloc.values() if v]
    avg_positions = float(np.mean([len(v) for v in non_empty])) if non_empty else 0.0

    result = {
        **sim_result,
        "period": f"{start} to {end}",
        "data_quality": quality_report,
        "avg_positions_per_month": round(avg_positions, 2),
        "formation_months": params["formation_months"],
        "vol_filter_pct": params["vol_filter_pct"],
        "n_tickers_downloaded": len(available_tickers),
    }
    return result


# ── Parameter Sensitivity Scan ────────────────────────────────────────────────

def scan_parameters(
    start: str = "2000-01-01",
    end: str = "2020-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Scan Sharpe ratio across a 2D parameter grid:
      - formation_months: [3, 6, 9]
      - vol_filter_pct:   [0.15, 0.20, 0.25]

    Gate 1 disqualification: Sharpe variance > 30% across either parameter dimension.

    Returns:
        dict of {param_label: sharpe_value, "_gate1_variance_flag": ..., ...}
    """
    results = {}
    formation_periods = [3, 6, 9]
    vol_filters = [0.15, 0.20, 0.25]

    for fm in formation_periods:
        for vf in vol_filters:
            p = {**base_params, "formation_months": fm, "vol_filter_pct": vf}
            key = f"fm={fm}m_vf={int(vf * 100)}pct"
            try:
                r = run_backtest(params=p, start=start, end=end)
                results[key] = round(r["sharpe"], 4)
            except Exception as exc:
                results[key] = f"error: {exc}"

    sharpe_nums = [
        v for v in results.values()
        if isinstance(v, (int, float)) and not np.isnan(v)
    ]
    if len(sharpe_nums) > 1:
        sharpe_range = max(sharpe_nums) - min(sharpe_nums)
        sharpe_mean = float(np.mean(sharpe_nums))
        variance_pct = (
            sharpe_range / abs(sharpe_mean) if abs(sharpe_mean) > 0 else float("inf")
        )
        results["_sharpe_range"] = round(sharpe_range, 4)
        results["_sharpe_variance_pct"] = round(variance_pct, 4)
        results["_gate1_variance_flag"] = (
            f"PASS: variance {variance_pct:.1%} ≤ 30%"
            if variance_pct <= 0.30
            else f"FAIL: variance {variance_pct:.1%} > 30%"
        )

    return results


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="H16 Momentum + Volatility Filter (Long-Only) backtest."
    )
    parser.add_argument(
        "--formation", type=int, default=6, choices=[3, 6, 9],
        help="Formation period in months (default: 6)"
    )
    parser.add_argument(
        "--vol-filter", type=float, default=0.20,
        help="Top vol fraction to keep as high-vol group (default: 0.20)"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Run 2D parameter sensitivity scan (formation × vol filter)"
    )
    args = parser.parse_args()

    params = {**PARAMETERS, "formation_months": args.formation, "vol_filter_pct": args.vol_filter}

    print(f"\nH16 Momentum+Vol: IS backtest (2000-01-01 to 2020-12-31), "
          f"formation={args.formation}m, vol_filter={args.vol_filter:.0%}...")
    is_result = run_backtest(params=params, start="2000-01-01", end="2020-12-31")
    safe_keys = {k: v for k, v in is_result.items()
                 if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                              "_portfolio_value", "_daily_returns", "_pnl_arr")}
    print("IS:", safe_keys)

    print(f"\nH16 Momentum+Vol: OOS backtest (2021-01-01 to 2024-12-31)...")
    oos_result = run_backtest(params=params, start="2021-01-01", end="2024-12-31")
    safe_oos = {k: v for k, v in oos_result.items()
                if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                             "_portfolio_value", "_daily_returns", "_pnl_arr")}
    print("OOS:", safe_oos)

    if args.scan:
        print("\nH16 Momentum+Vol: 2D parameter scan (formation [3,6,9]m × vol [15,20,25]%)...")
        scan_results = scan_parameters()
        print("Scan:", scan_results)
