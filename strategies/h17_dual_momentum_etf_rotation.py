"""
Strategy: H17 ETF Dual Momentum Rotation (Antonacci GEM)
Author: Engineering Director
Date: 2026-03-16
Hypothesis: Monthly rotation across SPY/EFA/AGG using relative momentum
            (SPY vs EFA) + absolute momentum (equity vs T-bills) filter.
            Rotates to AGG if absolute momentum is negative.
Asset class: equities/bonds (ETFs)
Parent task: QUA-164
References:
  - Antonacci (2014) "Dual Momentum Investing" McGraw-Hill
  - Asness, Moskowitz & Pedersen (2013) "Value and Momentum Everywhere" JFE
  - Jegadeesh & Titman (1993) "Returns to Buying Winners" JF 48(1)

IS window: 2004-01-01 to 2020-12-31 (ETF era; EFA and AGG both available from 2004)
OOS window: 2021-01-01 to 2024-12-31
Lookback sweep: [6, 9, 12] months

Note on pre-2004 data:
  EFA launched in 2001-08, AGG in 2003-09. To use the Antonacci academic period
  (1974-2013) would require index-level proxy data (MSCI EAFE, Bloomberg AGG index),
  which is not available via yfinance. Engineering Director decision: use ETF-era only
  (2004-2024) with SHY as T-bill proxy (BIL launched 2007). SHY (2002 launch)
  provides full IS coverage. Trade-off: shorter IS window (17 years vs 40+) but
  actual fund costs included. Documented per hypothesis specification.

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
    # Core universe — Antonacci GEM canonical 3-ETF setup
    "equity_us": "SPY",          # US equity proxy
    "equity_intl": "EFA",        # International equity proxy (MSCI EAFE)
    "bonds": "AGG",              # Safe-harbor bonds (US Aggregate)
    "tbill_proxy": "SHY",        # T-bill proxy: SHY (1-3yr treasury); BIL from 2007+
    # Signal lookback (months)
    "lookback_months": 12,       # [6, 9, 12] for sweep — Antonacci canonical: 12
    # Position sizing
    "init_cash": 25000,          # Starting capital
    # Execution
    "exec_day": "first",         # Rotate on first trading day of month (next-month open)
    # Transaction cost model
    "order_qty": 200,            # Approximate shares per trade at ~$25K in SPY ($500/sh)
}

TRADING_DAYS_PER_MONTH = 21
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

    Survivorship bias: Fixed 4-ticker universe. ETFs selected a priori by strategy
    specification, not by backtest performance. SPY (1993), EFA (2001), SHY (2002),
    AGG (2003) — all present for full IS window 2004-2020.

    Earnings exclusion: N/A — ETFs hold diversified baskets; no individual earnings events.
    Delisted: N/A — all are major iShares/SPDR ETFs with negligible delisting risk.
    """
    report = {
        "survivorship_bias": (
            "Fixed 4-ticker universe (SPY/EFA/AGG/SHY). All ETFs pre-selected by "
            "hypothesis specification (not by backtest performance). "
            "SPY: 1993, EFA: 2001, SHY: 2002, AGG: 2003. Full 2004-2020 IS coverage."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — ETFs; no individual earnings events.",
        "delisted": "N/A — all major liquid ETFs (SPY >$400B AUM, EFA/AGG >$50B).",
        "proxy_method": (
            "ETF-era only (2004+). Pre-2004 Antonacci academic data (MSCI EAFE index, "
            "Bloomberg AGG) not available via yfinance. SHY used as T-bill proxy "
            "(BIL available only from 2007). IS window: 2004-2020 (17 years)."
        ),
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

def compute_gem_signal(
    close: pd.DataFrame,
    params: dict,
) -> pd.Series:
    """
    Compute Antonacci GEM signal at monthly frequency.

    Two-step logic (evaluated on last trading day of each month):
      Step 1 — Relative momentum:
        R_us  = SPY total return over trailing lookback_months
        R_int = EFA total return over trailing lookback_months
        winner = SPY if R_us ≥ R_int else EFA

      Step 2 — Absolute momentum (trend filter):
        R_tb  = SHY (T-bill proxy) total return over trailing lookback_months
        If R_winner > R_tb → hold winner (positive equity momentum)
        Else               → rotate to AGG (safe harbor; negative equity momentum)

    Signal values: "SPY" | "EFA" | "AGG"
    No look-ahead: signal computed from price at end of month T,
    execution on first trading day of month T+1.

    Returns:
        pd.Series of signal strings indexed by month-end dates.
    """
    equity_us   = params["equity_us"]    # SPY
    equity_intl = params["equity_intl"]  # EFA
    bonds       = params["bonds"]        # AGG
    tbill       = params["tbill_proxy"]  # SHY

    lookback_td = params["lookback_months"] * TRADING_DAYS_PER_MONTH

    # Compute N-month trailing return for each ticker
    # pct_change(n): (P_t / P_{t-n}) - 1; strictly backward-looking
    returns = close.pct_change(lookback_td)

    # Resample to month-end (last available trading day in each calendar month)
    monthly_ret = returns.resample("ME").last()

    signals = []
    for month_end, row in monthly_ret.iterrows():
        # Guard: require all 4 tickers to have valid data
        if any(pd.isna(row.get(t)) for t in [equity_us, equity_intl, tbill]):
            signals.append((month_end, None))
            continue

        r_us   = row[equity_us]
        r_int  = row[equity_intl]
        r_tb   = row[tbill]

        # Step 1: relative momentum
        winner = equity_us if r_us >= r_int else equity_intl
        r_winner = r_us if winner == equity_us else r_int

        # Step 2: absolute momentum filter
        if r_winner > r_tb:
            signal = winner        # positive momentum → ride equity winner
        else:
            signal = bonds         # negative momentum → rotate to safe harbor

        signals.append((month_end, signal))

    signal_series = pd.Series(
        {dt: sig for dt, sig in signals if sig is not None},
        name="gem_signal",
    )
    return signal_series


# ── Portfolio Simulation ────────────────────────────────────────────────────────

def simulate_gem_portfolio(
    close: pd.DataFrame,
    signal_series: pd.Series,
    params: dict,
    volume: pd.DataFrame,
    close_full: pd.DataFrame = None,
    volume_full: pd.DataFrame = None,
) -> dict:
    """
    Simulate GEM portfolio: always 100% in one ETF.

    Execution model:
    - Signal at month-end T → execution on first trading day of T+1.
    - Rotate only when signal changes (no unnecessary trades).
    - 100% capital always deployed (no cash allocation).
    - Transaction costs applied on each rotation.

    Transaction cost model (canonical):
    - Fixed: $0.005/share
    - Slippage: 0.05% of trade value
    - Market impact: k × σ × sqrt(Q / ADV), k=0.1

    Args:
        close:       Simulation window price data (IS or OOS period only).
        signal_series: Monthly GEM signals (may include pre-window signal for first execution).
        params:      Strategy parameters.
        volume:      Simulation window volume data.
        close_full:  Full buffered price data (includes pre-window history). Used for
                     sigma/ADV computation to avoid NaN at window start. If None, falls
                     back to close (may produce NaN sigma at start of short windows).
        volume_full: Full buffered volume data. If None, falls back to volume.

    Returns:
        dict with daily portfolio values, trade log, and metrics.
    """
    equity_us   = params["equity_us"]
    equity_intl = params["equity_intl"]
    bonds       = params["bonds"]
    all_etfs    = [equity_us, equity_intl, bonds]
    init_cash   = params["init_cash"]
    order_qty   = params["order_qty"]
    k_impact    = 0.1  # Almgren-Chriss square-root model constant

    # Precompute sigma (20-day rolling daily return std) and ADV for market impact.
    # Use full buffered data if provided so rolling windows are warm at simulation start.
    # Bug fix: computing sigma/ADV from close_window only gives NaN on early dates
    # (e.g., rolling(20).std() requires 20 returns; the first execution date may fall
    # within the first 20 trading days of the window). Passing close_full ensures the
    # rolling windows are warm before the simulation window begins.
    _close_risk  = close_full if close_full is not None else close
    _volume_risk = volume_full if volume_full is not None else volume

    sigma = {}
    adv = {}
    for etf in all_etfs:
        if etf in _close_risk.columns:
            sigma[etf] = _close_risk[etf].pct_change().rolling(20).std()
            adv[etf] = (_volume_risk[etf] * _close_risk[etf]).rolling(20).mean() if etf in _volume_risk.columns else pd.Series(dtype=float)

    # Build execution schedule:
    # For each month-end signal, find the first trading day of the next month.
    exec_schedule = {}  # exec_date → ETF to hold
    monthly_dates = signal_series.index.tolist()
    for i, month_end in enumerate(monthly_dates):
        sig = signal_series.loc[month_end]
        # First trading day strictly after month_end
        future_days = close.index[close.index > month_end]
        if len(future_days) == 0:
            continue
        exec_date = future_days[0]
        exec_schedule[exec_date] = sig

    # Simulate daily portfolio value
    portfolio_value = pd.Series(index=close.index, dtype=float)
    portfolio_value.iloc[0] = init_cash

    current_holding = None  # ETF ticker currently held
    current_shares = 0.0
    cash = init_cash

    trade_log = []
    liquidity_flags = []

    for i, date in enumerate(close.index):
        if i == 0:
            portfolio_value.iloc[0] = cash
            continue

        # Check if we have an execution signal for this date
        if date in exec_schedule:
            target = exec_schedule[date]
            if target != current_holding and target in close.columns:
                # SELL current holding
                if current_holding is not None and current_holding in close.columns:
                    sell_price = close[current_holding].loc[date]
                    if not pd.isna(sell_price) and current_shares > 0:
                        # Apply sell costs
                        # NaN guard: pd.Series.get() may return NaN; `NaN or 0` = NaN in Python
                        # because NaN is truthy. Use explicit pd.isna check instead.
                        _sv = sigma.get(current_holding, pd.Series()).get(date, np.nan)
                        sig_val = 0.0 if pd.isna(_sv) else float(_sv)
                        adv_val = adv.get(current_holding, pd.Series()).get(date, np.nan)
                        adv_val = adv_val if not np.isna(adv_val) and adv_val > 0 else 1e9
                        q_over_adv_sell = (current_shares * sell_price) / adv_val
                        if q_over_adv_sell > 0.01:
                            liquidity_flags.append({
                                "date": str(date.date()),
                                "ticker": current_holding,
                                "side": "sell",
                                "q_over_adv": round(q_over_adv_sell, 6),
                            })
                        impact_sell = k_impact * sig_val * np.sqrt(max(q_over_adv_sell, 0))
                        # Gross proceeds - slippage - market impact - fixed commission
                        slippage_sell = 0.0005 + impact_sell
                        proceeds = current_shares * sell_price * (1 - slippage_sell)
                        commission_sell = current_shares * 0.005
                        proceeds -= commission_sell

                        trade_log.append({
                            "trade_id": f"sell_{current_holding}_{date.date()}",
                            "date": str(date.date()),
                            "ticker": current_holding,
                            "side": "sell",
                            "shares": round(current_shares, 4),
                            "price": round(sell_price, 4),
                            "slippage_pct": round(slippage_sell, 6),
                            "commission": round(commission_sell, 4),
                            "net_proceeds": round(proceeds, 4),
                            "liquidity_constrained": q_over_adv_sell > 0.01,
                        })
                        cash += proceeds
                        current_holding = None
                        current_shares = 0.0

                # BUY target ETF with all available cash
                buy_price = close[target].loc[date]
                if not pd.isna(buy_price) and buy_price > 0:
                    # NaN guard: same as sell side — use pd.isna check not `or 0`
                    _sv = sigma.get(target, pd.Series()).get(date, np.nan)
                    sig_val = 0.0 if pd.isna(_sv) else float(_sv)
                    adv_val = adv.get(target, pd.Series()).get(date, np.nan)
                    adv_val = adv_val if not np.isna(adv_val) and adv_val > 0 else 1e9

                    # Estimate shares we can buy
                    est_shares = cash / buy_price
                    q_over_adv_buy = (est_shares * buy_price) / adv_val
                    if q_over_adv_buy > 0.01:
                        liquidity_flags.append({
                            "date": str(date.date()),
                            "ticker": target,
                            "side": "buy",
                            "q_over_adv": round(q_over_adv_buy, 6),
                        })
                    impact_buy = k_impact * sig_val * np.sqrt(max(q_over_adv_buy, 0))
                    slippage_buy = 0.0005 + impact_buy

                    # Effective cost per share (price + slippage)
                    effective_cost = buy_price * (1 + slippage_buy)
                    # Fixed commission: $0.005/share
                    # Cash = shares × (effective_cost + 0.005)
                    shares_bought = cash / (effective_cost + 0.005)
                    commission_buy = shares_bought * 0.005
                    cash_spent = shares_bought * effective_cost + commission_buy

                    # Guard: abort if shares_bought is NaN or non-positive (prevents
                    # cascade failure where NaN shares destroy portfolio valuation).
                    if pd.isna(shares_bought) or shares_bought <= 0:
                        warnings.warn(
                            f"BUY skipped: {target} on {date.date()} — "
                            f"shares_bought={shares_bought} (effective_cost={effective_cost:.4f}, "
                            f"slippage={slippage_buy:.6f}). "
                            "Likely cause: sigma NaN at window start (use close_full parameter)."
                        )
                    else:
                        trade_log.append({
                            "trade_id": f"buy_{target}_{date.date()}",
                            "date": str(date.date()),
                            "ticker": target,
                            "side": "buy",
                            "shares": round(shares_bought, 4),
                            "price": round(buy_price, 4),
                            "effective_cost": round(effective_cost, 4),
                            "slippage_pct": round(slippage_buy, 6),
                            "commission": round(commission_buy, 4),
                            "cash_spent": round(cash_spent, 4),
                            "liquidity_constrained": q_over_adv_buy > 0.01,
                        })
                        current_holding = target
                        current_shares = shares_bought
                        cash = 0.0  # Fully invested

        # Daily portfolio valuation
        if current_holding is not None and current_holding in close.columns:
            price_today = close[current_holding].loc[date]
            if not pd.isna(price_today):
                portfolio_value.iloc[i] = current_shares * price_today + cash
            else:
                portfolio_value.iloc[i] = portfolio_value.iloc[i - 1]  # carry forward
        else:
            portfolio_value.iloc[i] = cash  # No position → hold cash

    # Forward-fill any missing values (e.g., pre-first-trade days)
    portfolio_value = portfolio_value.ffill().fillna(init_cash)

    # Compute daily returns and metrics
    daily_returns = portfolio_value.pct_change().fillna(0).values
    sharpe = float(daily_returns.mean() / (daily_returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
    cum = np.cumprod(1 + daily_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(portfolio_value.iloc[-1] / portfolio_value.iloc[0] - 1)

    # Trade-level PnL (compute round-trip trades from trade log)
    trade_pnl = _compute_round_trip_pnl(trade_log)
    if trade_pnl:
        pnl_arr = np.array([t["pnl"] for t in trade_pnl])
        win_rate = float(np.mean(pnl_arr > 0)) if len(pnl_arr) > 0 else 0.0
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
        "trade_count": len(trade_pnl),  # round trips
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

    Matches each buy with the subsequent sell for the same ticker.
    Open positions (no matching sell) are excluded.

    Returns: list of dicts with {ticker, buy_date, sell_date, pnl, return_pct}
    """
    trades = []
    open_positions = {}  # ticker → {"date": ..., "net_proceeds_buy": ..., "shares": ...}

    for entry in trade_log:
        ticker = entry["ticker"]
        if entry["side"] == "buy":
            # cash_spent = total cost including slippage + commission
            open_positions[ticker] = {
                "buy_date": entry["date"],
                "cash_spent": entry.get("cash_spent", 0),
                "shares": entry.get("shares", 0),
            }
        elif entry["side"] == "sell" and ticker in open_positions:
            open_pos = open_positions.pop(ticker)
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


# ── Main Backtest Entry Point ───────────────────────────────────────────────────

def run_backtest(
    params: dict = PARAMETERS,
    start: str = "2004-01-01",
    end: str = "2020-12-31",
) -> dict:
    """
    Run H17 GEM backtest for a given period and parameter set.

    Downloads price data, validates quality, computes GEM signal,
    simulates portfolio, and returns standardized metrics dict.

    Args:
        params: strategy parameters (see PARAMETERS constant)
        start:  backtest start date (inclusive)
        end:    backtest end date (inclusive)

    Returns:
        dict with sharpe, max_drawdown, win_rate, win_loss_ratio, profit_factor,
        total_return, trade_count, trade_log, data_quality, liquidity_flags,
        period, and internal arrays for statistical tests.

    Raises:
        ValueError: if data is insufficient for the requested lookback.
    """
    all_tickers = [
        params["equity_us"],
        params["equity_intl"],
        params["bonds"],
        params["tbill_proxy"],
    ]

    # Download data with a 14-month pre-start buffer to populate the lookback window
    buffer_months = params["lookback_months"] + 2
    buf_start = str((pd.Timestamp(start) - pd.DateOffset(months=buffer_months)).date())
    close, volume = download_data(all_tickers, buf_start, end)

    # Data quality check
    quality_report = check_data_quality(close, all_tickers)

    close = close.dropna(axis=1, how="all")
    required_tickers = [params["equity_us"], params["equity_intl"], params["tbill_proxy"]]
    missing = [t for t in required_tickers if t not in close.columns]
    if missing:
        raise ValueError(f"Required tickers missing from price data: {missing}")

    # Ensure we have sufficient lookback data
    min_required = params["lookback_months"] * TRADING_DAYS_PER_MONTH + 20
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    # Compute GEM signal (uses full buffered history for first lookback computation)
    signal_series = compute_gem_signal(close, params)

    # Trim to the actual backtest window for portfolio simulation
    close_window = close.loc[start:end]
    volume_window = volume.reindex(close_window.index).fillna(0)
    # Only include signals that apply within the backtest window
    # A signal at month-end M triggers execution in month M+1; filter signal_series
    # to months that fall within or just before the backtest window
    signal_in_window = signal_series[
        signal_series.index >= (pd.Timestamp(start) - pd.DateOffset(months=1))
    ]
    signal_in_window = signal_in_window[signal_in_window.index <= pd.Timestamp(end)]

    if signal_in_window.empty:
        raise ValueError(f"No GEM signals generated for period {start} to {end}.")

    # Simulate portfolio.
    # Pass full buffered close/volume as close_full/volume_full so sigma/ADV rolling
    # windows are warm at the simulation window start (fixes NaN sigma on first trade).
    sim_result = simulate_gem_portfolio(
        close_window, signal_in_window, params, volume_window,
        close_full=close, volume_full=volume,
    )

    # Holdings breakdown (what fraction of time in each ETF)
    holding_counts = {}
    for sig in signal_series.loc[signal_in_window.index]:
        holding_counts[sig] = holding_counts.get(sig, 0) + 1
    total_months = len(signal_in_window)
    holding_pct = {
        k: round(v / max(total_months, 1), 4)
        for k, v in holding_counts.items()
    }

    result = {
        **sim_result,
        "period": f"{start} to {end}",
        "data_quality": quality_report,
        "holding_pct": holding_pct,
        "lookback_months": params["lookback_months"],
    }
    # Remove internal arrays from top-level (kept with underscore prefix for runners)
    return result


# ── Parameter Sensitivity Scan ─────────────────────────────────────────────────

def scan_parameters(
    start: str = "2004-01-01",
    end: str = "2020-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Scan Sharpe ratio across H17 lookback parameter grid: [6, 9, 12] months.

    Gate 1 disqualification: Sharpe variance > 30% across the parameter dimension.

    Returns dict: {param_label: sharpe_value, "_gate1_variance_flag": ...}
    """
    results = {}
    for lb in [6, 9, 12]:
        p = {**base_params, "lookback_months": lb}
        key = f"lookback_months={lb}"
        try:
            r = run_backtest(params=p, start=start, end=end)
            results[key] = round(r["sharpe"], 4)
        except Exception as exc:
            results[key] = f"error: {exc}"

    sharpe_nums = [v for v in results.values() if isinstance(v, (int, float)) and not np.isnan(v)]
    if len(sharpe_nums) > 1:
        sharpe_range = max(sharpe_nums) - min(sharpe_nums)
        sharpe_mean = np.mean(sharpe_nums)
        variance_pct = sharpe_range / abs(sharpe_mean) if abs(sharpe_mean) > 0 else float("inf")
        results["_sharpe_range"] = round(sharpe_range, 4)
        results["_sharpe_variance_pct"] = round(variance_pct, 4)
        results["_gate1_variance_flag"] = (
            f"PASS: variance {variance_pct:.1%} ≤ 30%"
            if variance_pct <= 0.30
            else f"FAIL: variance {variance_pct:.1%} > 30%"
        )

    return results


# ── Entry Point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="H17 Dual Momentum ETF Rotation (Antonacci GEM) backtest."
    )
    parser.add_argument(
        "--lookback", type=int, default=12, choices=[6, 9, 12],
        help="Lookback period in months (default: 12)"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Run parameter sensitivity scan across lookback [6, 9, 12]"
    )
    args = parser.parse_args()

    params = {**PARAMETERS, "lookback_months": args.lookback}

    print(f"\nH17 GEM: Running IS backtest (2004-01-01 to 2020-12-31), lookback={args.lookback}m...")
    is_result = run_backtest(params=params, start="2004-01-01", end="2020-12-31")
    safe_keys = {k: v for k, v in is_result.items()
                 if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                              "_portfolio_value", "_daily_returns", "_pnl_arr")}
    print("IS:", safe_keys)

    print(f"\nH17 GEM: Running OOS backtest (2021-01-01 to 2024-12-31)...")
    oos_result = run_backtest(params=params, start="2021-01-01", end="2024-12-31")
    safe_oos = {k: v for k, v in oos_result.items()
                if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                             "_portfolio_value", "_daily_returns", "_pnl_arr")}
    print("OOS:", safe_oos)

    if args.scan:
        print("\nH17 GEM: Parameter sensitivity scan (lookback 6/9/12m, IS 2004-2020)...")
        scan_results = scan_parameters()
        print("Scan:", scan_results)
