"""
Strategy: H20 SPDR Sector Momentum Weekly Rotation
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: 9 SPDR sector ETFs exhibit relative momentum — ranking by trailing return
            and holding top-N sectors with weekly rebalancing generates excess returns.
            A 200-day SMA regime filter on SPY exits all positions during bear markets.
Asset class: equities (sector ETFs)
Parent task: QUA-186

References:
  - Moskowitz, T. & Grinblatt, M. (1999) "Do Industries Explain Momentum?" JF 54(4)
  - Asness, Moskowitz & Pedersen (2013) "Value and Momentum Everywhere" JFE
  - Fama & French sector momentum (multi-year robustness evidence)

IS window:  2018-01-01 to 2022-12-31
OOS window: 2023-01-01 to 2025-12-31

Universe: 9 SPDR Select Sector ETFs (current constituents, not point-in-time).
  All ETFs launched Dec 1998; full IS/OOS coverage. No survivorship bias within
  the fixed 9-ETF universe (all remain active and liquid).

Data quality notes:
  - SPDR sector ETFs: current constituent weights (no point-in-time universe available).
    Minor limitation: GICS sector reconstitutions may change ETF basket composition,
    but these changes are infrequent and small. Documented per hypothesis.
  - Prices: auto_adjust=True for split/dividend adjustment.
  - Data gaps: Flag any ticker with >5 missing trading days.
  - Earnings exclusion: N/A — ETFs hold diversified sector baskets; no individual earnings.
  - Delisted: N/A — all 9 SPDR ETFs and SPY are active (launched Dec 1998 / 1993).

Transaction cost model (canonical, per Engineering Director AGENTS.md):
  - Fixed: $0.005/share
  - Slippage: 0.05% of trade value
  - Market impact: k × σ × sqrt(Q / ADV), k=0.1
  - Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    # Sector universe — 9 SPDR Select Sector ETFs
    "universe": ["XLK", "XLV", "XLF", "XLE", "XLU", "XLY", "XLP", "XLI", "XLB"],
    # Regime filter ticker (SPY below SMA → exit all to cash)
    "regime_ticker": "SPY",
    # Momentum lookback in trading days — sweep: {10, 15, 20}
    "mom_lookback_days": 20,
    # Number of top sectors to hold simultaneously — sweep: {1, 2, 3}
    "top_N_sectors": 3,
    # Regime filter SMA period — sweep: {150, 200}
    "regime_filter_sma": 200,
    # Equal-weight allocation among top-N sectors
    "equal_weight": True,
    # Starting capital
    "init_cash": 25000,
}

TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ────────────────────────────────────────────────────────────────

def download_data(
    tickers: list, start: str, end: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
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
        # Single-ticker fallback (shouldn't occur for 10-ticker download)
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

    Survivorship bias: Fixed 9-ETF universe + SPY. ETFs selected a priori by strategy
    specification, not by backtest performance. All SPDR Select Sector ETFs launched
    Dec 1998; IS start 2018 provides 19+ years of history per ticker.

    Earnings exclusion: N/A — sector ETFs; no individual stock earnings events.
    """
    report = {
        "survivorship_bias": (
            "Fixed 9-ticker universe (SPDR Select Sector ETFs) + SPY. All ETFs pre-selected "
            "by hypothesis specification (not by backtest performance). "
            "All launched Dec 1998; full 2018-2022 IS and 2023-2025 OOS coverage. "
            "No delisted ETFs in universe. Minor limitation: current GICS constituent "
            "weights used (no point-in-time universe available via yfinance)."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — sector ETFs; no individual earnings events.",
        "delisted": "N/A — all SPDR Select Sector ETFs and SPY active (launched 1993-1998).",
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
    Return sorted list of rebalance dates (Fridays or last trading day of week)
    within the [start, end] range that are present in the price index.

    For each calendar week, select the last available trading day on or before
    the Friday of that week (handles holiday Fridays gracefully).
    """
    date_range = price_index[(price_index >= start) & (price_index <= end)]
    calendar_fridays = pd.date_range(start=start, end=end, freq="W-FRI")

    rebalance_dates = []
    for friday in calendar_fridays:
        # Find last trading day in this week: from Monday through Friday
        week_start = friday - pd.Timedelta(days=4)
        week_dates = date_range[(date_range >= week_start) & (date_range <= friday)]
        if len(week_dates) > 0:
            rebalance_dates.append(week_dates[-1])

    return sorted(set(rebalance_dates))


def compute_sector_momentum_signal(
    close: pd.DataFrame,
    params: dict,
    window_start: str,
    window_end: str,
) -> pd.DataFrame:
    """
    Compute weekly sector momentum rankings and top-N selection at each rebalance date.

    Signal logic (evaluated at Friday close — no look-ahead):
      1. Compute momentum_score(sector) = pct_change(lookback) for each sector ETF.
         pct_change(n) = (close_t / close_{t-n}) - 1 — strictly backward-looking.
      2. Rank sectors 1-9 by descending momentum score (rank 1 = best momentum).
      3. Select top_N_sectors by rank.
      4. Regime filter: if SPY < SMA(regime_filter_sma), set top_sectors = [] (cash).

    Args:
        close:        Full price DataFrame (includes pre-window buffer for SMA warm-up).
        params:       Strategy parameters.
        window_start: Start date for rebalance signal generation.
        window_end:   End date.

    Returns:
        DataFrame indexed by rebalance date with columns:
          - top_sectors: list of selected ticker strings ([] = cash/regime filter active)
          - regime_active: bool, True when SPY below SMA
          - scores: dict of {ticker: momentum_score}
          - rankings: dict of {ticker: rank}
    """
    universe = list(params["universe"])
    regime_ticker = params["regime_ticker"]
    lookback = params["mom_lookback_days"]
    top_n = params["top_N_sectors"]
    sma_period = params["regime_filter_sma"]

    # Compute regime filter SMA on full buffered history for warm rolling window
    regime_sma = None
    if regime_ticker in close.columns:
        regime_sma = close[regime_ticker].rolling(sma_period).mean()

    # Momentum scores (pct_change is backward-looking; no look-ahead)
    valid_universe = [t for t in universe if t in close.columns]
    mom_scores = close[valid_universe].pct_change(lookback)

    rebalance_dates = get_weekly_rebalance_dates(close.index, window_start, window_end)

    rows = []
    for date in rebalance_dates:
        # Regime check: SPY below SMA → exit all to cash
        regime_active = False
        if regime_sma is not None and date in regime_sma.index:
            spy_price = close[regime_ticker].loc[date]
            sma_val = regime_sma.loc[date]
            if pd.isna(spy_price) or pd.isna(sma_val) or spy_price < sma_val:
                regime_active = True

        if regime_active:
            rows.append({
                "date": date,
                "top_sectors": [],
                "regime_active": True,
                "scores": {},
                "rankings": {},
            })
            continue

        # Momentum scores at this rebalance date
        if date not in mom_scores.index:
            continue

        scores_today = mom_scores.loc[date].dropna()
        if scores_today.empty:
            continue

        # Rank descending (rank 1 = highest momentum score)
        rankings = scores_today.rank(ascending=False, method="first").astype(int)

        # Select top N sectors sorted by rank
        top_sectors = (
            rankings[rankings <= top_n]
            .sort_values()
            .index
            .tolist()
        )

        rows.append({
            "date": date,
            "top_sectors": top_sectors,
            "regime_active": False,
            "scores": scores_today.round(6).to_dict(),
            "rankings": rankings.to_dict(),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("date")
    return df


# ── Portfolio Simulation ────────────────────────────────────────────────────────

def simulate_sector_rotation_portfolio(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    signal_df: pd.DataFrame,
    params: dict,
    close_full: pd.DataFrame = None,
    volume_full: pd.DataFrame = None,
) -> dict:
    """
    Simulate the H20 sector rotation portfolio from weekly rebalance signals.

    Execution model (per hypothesis specification):
    - Signal at Friday close T → execute at Friday close T (same-day EOD fill).
      Rationale: sector ETF daily close prices are used for signal and execution.
      EOD fill is consistent with retail execution on index ETFs at market close.
    - Rebalance logic (minimal-turnover):
      a. SELL sectors that dropped out of top-N (frees cash).
      b. BUY new sectors entering top-N using proceeds (equal allocation per new entry).
      c. Sectors remaining in top-N are HELD unchanged (no action = no unnecessary costs).
      d. Regime filter active: SELL all positions, hold cash.
    - Cash from sector exits is reallocated equally among new sector entrants only.

    Transaction cost model (canonical):
    - Fixed: $0.005/share
    - Slippage: 0.05% of trade value
    - Market impact: k × σ × sqrt(Q / ADV), k=0.1, square-root model (Johnson 2010)

    Args:
        close:        Simulation window price data (IS or OOS period only).
        volume:       Simulation window volume data.
        signal_df:    Output of compute_sector_momentum_signal() for this window.
        params:       Strategy parameters.
        close_full:   Full buffered price data for warm σ/ADV rolling windows.
                      If None, NaN sigma may occur at window start.
        volume_full:  Full buffered volume data. If None, falls back to volume.

    Returns:
        dict with portfolio_value series, trade_log, metrics, and liquidity flags.
    """
    init_cash = params["init_cash"]
    k_impact = 0.1  # Almgren-Chriss square-root impact constant (Johnson 2010)

    # Precompute sigma (20-day rolling daily return std) and ADV using full history
    # for warm rolling windows. Without this, sigma is NaN at simulation window start,
    # causing BUY orders to be skipped (guarded below with warning).
    _close_risk = close_full if close_full is not None else close
    _volume_risk = volume_full if volume_full is not None else volume

    all_tickers = list(params["universe"]) + [params["regime_ticker"]]
    sigma = {}
    adv = {}
    for ticker in all_tickers:
        if ticker in _close_risk.columns:
            sigma[ticker] = _close_risk[ticker].pct_change().rolling(20).std()
            if ticker in _volume_risk.columns:
                # Dollar ADV: shares × price, rolling 20-day mean
                adv[ticker] = (_volume_risk[ticker] * _close_risk[ticker]).rolling(20).mean()
            else:
                adv[ticker] = pd.Series(dtype=float)

    def _get_sigma(ticker: str, date) -> float:
        val = sigma.get(ticker, pd.Series()).get(date, np.nan)
        return 0.0 if pd.isna(val) else float(val)

    def _get_adv(ticker: str, date) -> float:
        val = adv.get(ticker, pd.Series()).get(date, np.nan)
        return float(val) if not pd.isna(val) and val > 0 else 1e9

    def _sell_ticker(ticker: str, date, shares: float) -> float:
        """Execute sell; return net proceeds after costs."""
        if ticker not in close.columns or shares <= 0:
            return 0.0
        price = close[ticker].loc[date] if date in close.index else np.nan
        if pd.isna(price) or price <= 0:
            return 0.0

        sig_val = _get_sigma(ticker, date)
        adv_val = _get_adv(ticker, date)
        q_over_adv = (shares * price) / adv_val

        if q_over_adv > 0.01:
            liquidity_flags.append({
                "date": str(date.date()), "ticker": ticker, "side": "sell",
                "q_over_adv": round(q_over_adv, 6),
            })

        impact = k_impact * sig_val * np.sqrt(max(q_over_adv, 0))
        slippage_pct = 0.0005 + impact
        commission = shares * 0.005
        proceeds = shares * price * (1 - slippage_pct) - commission

        trade_log.append({
            "trade_id": f"sell_{ticker}_{date.date()}",
            "date": str(date.date()), "ticker": ticker, "side": "sell",
            "shares": round(shares, 4), "price": round(price, 4),
            "slippage_pct": round(slippage_pct, 6),
            "commission": round(commission, 4),
            "net_proceeds": round(max(proceeds, 0.0), 4),
            "liquidity_constrained": q_over_adv > 0.01,
        })
        return max(proceeds, 0.0)

    def _buy_ticker(ticker: str, date, cash_allocated: float) -> float:
        """
        Execute buy with cash_allocated; return shares bought.
        Effective cost per share = price × (1 + slippage) + $0.005 fixed commission.
        """
        if ticker not in close.columns or cash_allocated <= 0:
            return 0.0
        price = close[ticker].loc[date] if date in close.index else np.nan
        if pd.isna(price) or price <= 0:
            return 0.0

        sig_val = _get_sigma(ticker, date)
        adv_val = _get_adv(ticker, date)
        est_shares = cash_allocated / price
        q_over_adv = (est_shares * price) / adv_val

        if q_over_adv > 0.01:
            liquidity_flags.append({
                "date": str(date.date()), "ticker": ticker, "side": "buy",
                "q_over_adv": round(q_over_adv, 6),
            })

        impact = k_impact * sig_val * np.sqrt(max(q_over_adv, 0))
        slippage_pct = 0.0005 + impact
        # Effective cost per share (price + slippage markup + $0.005 fixed commission)
        effective_cost = price * (1 + slippage_pct) + 0.005
        shares_bought = cash_allocated / effective_cost

        if pd.isna(shares_bought) or shares_bought <= 0:
            warnings.warn(
                f"BUY skipped: {ticker} on {date.date()} — "
                f"shares_bought={shares_bought:.4f}, effective_cost={effective_cost:.4f}, "
                f"sigma={sig_val:.6f}. Likely NaN sigma at window start; pass close_full."
            )
            return 0.0

        commission = shares_bought * 0.005
        cash_spent = shares_bought * price * (1 + slippage_pct) + commission

        trade_log.append({
            "trade_id": f"buy_{ticker}_{date.date()}",
            "date": str(date.date()), "ticker": ticker, "side": "buy",
            "shares": round(shares_bought, 4), "price": round(price, 4),
            "effective_cost": round(effective_cost, 4),
            "slippage_pct": round(slippage_pct, 6),
            "commission": round(commission, 4),
            "cash_spent": round(cash_spent, 4),
            "liquidity_constrained": q_over_adv > 0.01,
        })
        return shares_bought

    # Initialize state
    holdings = {}       # {ticker: shares_held}
    cash = float(init_cash)
    trade_log = []
    liquidity_flags = []
    portfolio_value = pd.Series(index=close.index, dtype=float)

    # Build rebalance schedule from signal_df (map rebalance date → target sector list)
    rebalance_schedule = {}
    if not signal_df.empty:
        for date, row in signal_df.iterrows():
            if date in close.index:
                rebalance_schedule[date] = list(row["top_sectors"])

    for i, date in enumerate(close.index):
        if i == 0:
            portfolio_value.iloc[0] = cash
            continue

        # Execute rebalance when we have a scheduled signal for this date
        if date in rebalance_schedule:
            target_sectors = rebalance_schedule[date]
            target_set = set(target_sectors)
            current_set = set(holdings.keys())

            # Step 1: Sell sectors leaving top-N (or all if regime filter active)
            sectors_to_exit = current_set - target_set
            for ticker in list(sectors_to_exit):
                shares = holdings.pop(ticker, 0.0)
                if shares > 0:
                    cash += _sell_ticker(ticker, date, shares)

            # Step 2: Enter new sectors using available cash (equal allocation per entrant)
            if target_set:
                new_sectors = [t for t in target_sectors if t not in current_set]
                if new_sectors:
                    # Allocate available cash equally among new sector entrants
                    cash_per_new = cash / len(new_sectors)
                    for ticker in new_sectors:
                        shares_bought = _buy_ticker(ticker, date, cash_per_new)
                        if shares_bought > 0:
                            holdings[ticker] = holdings.get(ticker, 0.0) + shares_bought
                            # Deduct approximate cost (effective_cost ≈ cash_per_new)
                            cash -= cash_per_new
                    cash = max(cash, 0.0)  # Guard against floating-point negative cash

        # Daily NAV: mark all holdings to market at close
        nav = cash
        for ticker, shares in holdings.items():
            if ticker in close.columns and date in close.index:
                price = close[ticker].loc[date]
                if not pd.isna(price):
                    nav += shares * price
        portfolio_value.iloc[i] = nav

    # Forward-fill any NaN values (e.g., pre-first-trade days with all-cash position)
    portfolio_value = portfolio_value.ffill().fillna(init_cash)

    # Compute performance metrics
    daily_returns = portfolio_value.pct_change().fillna(0).values
    sharpe = float(
        daily_returns.mean() / (daily_returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )
    cum = np.cumprod(1 + daily_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(portfolio_value.iloc[-1] / portfolio_value.iloc[0] - 1)

    # Compute round-trip trade PnL
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
        "trade_count": len(trade_pnl),  # round-trip trades
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
    Compute round-trip PnL from alternating buy/sell entries in the trade log.
    Matches each buy with the subsequent sell for the same ticker (FIFO).
    Open positions (no matching sell) are excluded.

    Returns: list of dicts with {ticker, buy_date, sell_date, pnl, return_pct}
    """
    trades = []
    open_positions = {}  # ticker → list of open buy entries (FIFO queue)

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
            open_pos = open_positions[ticker].pop(0)  # FIFO
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

def check_xlk_concentration(signal_df: pd.DataFrame, threshold: float = 0.60) -> dict:
    """
    Count IS period weeks where XLK appears in the top-N selection.
    Flag xlk_concentration_risk = True if XLK is in top-N on >threshold of IS weeks.

    Engineering Director requirement: if XLK appears in top-3 >60% of IS weeks,
    it signals concentration in a single sector, inflating IS Sharpe.

    Args:
        signal_df:  Output of compute_sector_momentum_signal() for IS period.
        threshold:  Concentration threshold (default 0.60 = 60%).

    Returns:
        dict with xlk_in_top_n_count, total_weeks, xlk_pct, xlk_concentration_risk
    """
    if signal_df.empty or "top_sectors" not in signal_df.columns:
        return {
            "xlk_in_top_n_count": 0,
            "total_weeks": 0,
            "xlk_pct": 0.0,
            "xlk_concentration_risk": False,
        }

    total_weeks = len(signal_df)
    xlk_count = sum(1 for sectors in signal_df["top_sectors"] if "XLK" in sectors)
    xlk_pct = xlk_count / total_weeks if total_weeks > 0 else 0.0

    return {
        "xlk_in_top_n_count": xlk_count,
        "total_weeks": total_weeks,
        "xlk_pct": round(xlk_pct, 4),
        "xlk_concentration_risk": xlk_pct > threshold,
    }


def check_trade_count_gate(trade_count: int, is_years: float, min_per_year: int = 30) -> dict:
    """
    Verify IS trade count meets PF-1 gate: trade_count / is_years >= min_per_year.

    Engineering Director requirement (QUA-186): IS trade count with N=3 default ≥ 30/yr.
    Expected range: 30–45/yr based on weekly rebalancing with ~1-2 sector changes/week.

    Returns:
        dict with annual_rate, gate_pass, message
    """
    annual_rate = trade_count / max(is_years, 0.001)
    gate_pass = annual_rate >= min_per_year
    return {
        "trade_count_total": trade_count,
        "is_years": is_years,
        "annual_rate": round(annual_rate, 2),
        "min_per_year": min_per_year,
        "gate_pass": gate_pass,
        "message": (
            f"PASS: {annual_rate:.1f}/yr ≥ {min_per_year}/yr"
            if gate_pass
            else f"FAIL: {annual_rate:.1f}/yr < {min_per_year}/yr — flag to Engineering Director"
        ),
    }


# ── Main Backtest Entry Point ───────────────────────────────────────────────────

def run_backtest(
    params: dict = PARAMETERS,
    start: str = "2018-01-01",
    end: str = "2022-12-31",
) -> dict:
    """
    Run H20 sector momentum backtest for a given period and parameter set.

    Downloads data (with pre-window buffer for warm-up), validates quality,
    computes weekly sector signals with regime filter, simulates portfolio,
    and returns a standardized metrics dict.

    Args:
        params: strategy parameters (see PARAMETERS constant)
        start:  backtest start date (inclusive)
        end:    backtest end date (inclusive)

    Returns:
        dict with sharpe, max_drawdown, win_rate, win_loss_ratio, profit_factor,
        total_return, trade_count, trade_log, data_quality, liquidity_flags,
        xlk_concentration, period, and internal arrays.

    Raises:
        ValueError: if data is insufficient or required tickers are missing.
    """
    universe = list(params["universe"])
    regime_ticker = params["regime_ticker"]
    all_tickers = universe + ([regime_ticker] if regime_ticker not in universe else [])

    # Pre-window buffer: max(regime_filter_sma, mom_lookback_days) + 30 trading days
    sma_period = params["regime_filter_sma"]
    buffer_td = sma_period + params["mom_lookback_days"] + 30
    buf_start = str(
        (pd.Timestamp(start) - pd.tseries.offsets.BDay(buffer_td)).date()
    )

    close, volume = download_data(all_tickers, buf_start, end)

    # Data quality check on full download (including buffer period)
    quality_report = check_data_quality(close, all_tickers)

    close = close.dropna(axis=1, how="all")
    missing_universe = [t for t in universe if t not in close.columns]
    if missing_universe:
        raise ValueError(f"Required universe tickers missing: {missing_universe}")
    if regime_ticker not in close.columns:
        raise ValueError(f"Regime ticker {regime_ticker} missing from downloaded data.")

    min_required = sma_period + params["mom_lookback_days"] + 10
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    # Compute weekly sector momentum signals using full buffered price history
    signal_df = compute_sector_momentum_signal(close, params, start, end)

    if signal_df.empty:
        raise ValueError(f"No weekly signals generated for period {start} to {end}.")

    # Trim to simulation window for portfolio simulation
    close_window = close.loc[start:end]
    volume_window = volume.reindex(close_window.index).fillna(0)

    # Simulate portfolio; pass full buffered data for warm σ/ADV rolling windows
    sim_result = simulate_sector_rotation_portfolio(
        close_window, volume_window, signal_df, params,
        close_full=close, volume_full=volume,
    )

    # Engineering Director flags
    xlk_conc = check_xlk_concentration(signal_df, threshold=0.60)

    is_years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    trade_count_check = check_trade_count_gate(sim_result["trade_count"], is_years)

    # Sector holding breakdown: fraction of IS weeks each sector was in top-N
    sector_week_counts = {}
    cash_weeks = 0
    for sectors in signal_df["top_sectors"]:
        if not sectors:
            cash_weeks += 1
        else:
            for s in sectors:
                sector_week_counts[s] = sector_week_counts.get(s, 0) + 1
    total_weeks = len(signal_df)
    holding_pct = {k: round(v / max(total_weeks, 1), 4) for k, v in sector_week_counts.items()}
    holding_pct["_cash"] = round(cash_weeks / max(total_weeks, 1), 4)

    return {
        **sim_result,
        "period": f"{start} to {end}",
        "data_quality": quality_report,
        "holding_pct": holding_pct,
        "xlk_concentration": xlk_conc,
        "trade_count_gate": trade_count_check,
        "mom_lookback_days": params["mom_lookback_days"],
        "top_N_sectors": params["top_N_sectors"],
        "regime_filter_sma": params["regime_filter_sma"],
    }


# ── Parameter Sensitivity Scan ─────────────────────────────────────────────────

def scan_parameters(
    start: str = "2018-01-01",
    end: str = "2022-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Scan IS Sharpe ratio across 18 parameter combinations:
      - mom_lookback_days ∈ {10, 15, 20}
      - top_N_sectors ∈ {1, 2, 3}
      - regime_filter_sma ∈ {150, 200}

    Gate 1 stability check: <30% Sharpe degradation relative to default configuration.

    Returns dict with Sharpe values for all 18 combinations, heatmap labels,
    and stability flags vs default (lb=20, N=3, sma=200).
    """
    lookbacks = [10, 15, 20]
    top_ns = [1, 2, 3]
    smas = [150, 200]

    results = {}
    for lb in lookbacks:
        for n in top_ns:
            for sma in smas:
                p = {
                    **base_params,
                    "mom_lookback_days": lb,
                    "top_N_sectors": n,
                    "regime_filter_sma": sma,
                }
                key = f"lb{lb}_N{n}_sma{sma}"
                try:
                    r = run_backtest(params=p, start=start, end=end)
                    results[key] = {
                        "sharpe": round(r["sharpe"], 4),
                        "total_return": round(r["total_return"], 4),
                        "max_drawdown": round(r["max_drawdown"], 4),
                        "trade_count": r["trade_count"],
                        "xlk_concentration_risk": r["xlk_concentration"]["xlk_concentration_risk"],
                    }
                except Exception as exc:
                    results[key] = {"error": str(exc)}

    # Stability meta-analysis relative to default config
    default_key = (
        f"lb{base_params['mom_lookback_days']}"
        f"_N{base_params['top_N_sectors']}"
        f"_sma{base_params['regime_filter_sma']}"
    )
    default_sharpe = results.get(default_key, {}).get("sharpe", None)

    sharpe_nums = [
        v["sharpe"] for v in results.values()
        if isinstance(v, dict) and "sharpe" in v and isinstance(v["sharpe"], (int, float))
    ]

    meta = {
        "default_key": default_key,
        "default_sharpe": default_sharpe,
        "total_combinations": len(lookbacks) * len(top_ns) * len(smas),
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
                f"PASS: variance {variance_pct:.1%} ≤ 30%"
                if variance_pct <= 0.30
                else f"FAIL: variance {variance_pct:.1%} > 30%"
            ),
        })

    results["_meta"] = meta
    return results


# ── Entry Point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="H20 SPDR Sector Momentum Weekly Rotation backtest."
    )
    parser.add_argument(
        "--lookback", type=int, default=20, choices=[10, 15, 20],
        help="Momentum lookback in trading days (default: 20)"
    )
    parser.add_argument(
        "--top-n", type=int, default=3, choices=[1, 2, 3],
        help="Number of top sectors to hold (default: 3)"
    )
    parser.add_argument(
        "--sma", type=int, default=200, choices=[150, 200],
        help="Regime filter SMA period (default: 200)"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Run full 18-combination parameter sensitivity scan"
    )
    args = parser.parse_args()

    params = {
        **PARAMETERS,
        "mom_lookback_days": args.lookback,
        "top_N_sectors": args.top_n,
        "regime_filter_sma": args.sma,
    }

    print(
        f"\nH20 Sector Momentum: IS backtest (2018-01-01 to 2022-12-31) "
        f"lb={args.lookback}d N={args.top_n} sma={args.sma}..."
    )
    is_result = run_backtest(params=params, start="2018-01-01", end="2022-12-31")
    safe_is = {
        k: v for k, v in is_result.items()
        if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                     "_portfolio_value", "_daily_returns", "_pnl_arr")
    }
    print("IS:", safe_is)

    print(f"\nH20 Sector Momentum: OOS backtest (2023-01-01 to 2025-12-31)...")
    oos_result = run_backtest(params=params, start="2023-01-01", end="2025-12-31")
    safe_oos = {
        k: v for k, v in oos_result.items()
        if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                     "_portfolio_value", "_daily_returns", "_pnl_arr")
    }
    print("OOS:", safe_oos)

    if args.scan:
        import json
        print("\nH20 Sector Momentum: 18-combination parameter sensitivity scan (IS 2018-2022)...")
        scan_results = scan_parameters()
        print(json.dumps(scan_results, indent=2))
