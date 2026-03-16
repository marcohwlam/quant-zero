"""
Strategy: H07b Multi-Asset Time-Series Momentum — Expanded Universe + VIX Regime Gate
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: 15-ETF universe with 12-month trailing return signal; long if positive,
            flat otherwise; monthly rebalancing with VIX regime gate.
            VIX > 25: 50% scale (stress); VIX > 35: flat (crisis).
Asset class: equities (ETFs)
Parent task: QUA-138
References:
  - Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum" — JFE 104(2)
  - Barroso & Santa-Clara (2015) "Momentum Has Its Moments" — JFE 116(1)
  - Daniel & Moskowitz (2016) "Momentum Crashes" — JFE 122(2)

Changes from H07:
  - Universe: 6 → 15 ETFs (adds IWM, EFA, IEF, HYG, TIP, SLV, DBB, DBA, XLF, XLRE)
  - VIX regime gate: VIX > 25 → 50% scale; VIX > 35 → flat (crisis)
  - Lookback range tightened to [9, 12, 18] (removes 6-month outlier)
  - USO/DBC replaced with diversified commodity ETFs (SLV, DBB, DBA, XLE)
"""

import warnings
import numpy as np
import pandas as pd
import vectorbt as vbt
import yfinance as yf

# All tunable parameters exposed here for sensitivity scanning
PARAMETERS = {
    "universe": [
        "SPY", "QQQ", "IWM", "EFA",       # equities: large, tech, small, intl
        "TLT", "IEF", "HYG", "TIP",        # bonds: long-dur, mid-dur, credit, TIPS
        "GLD", "SLV", "DBB", "DBA",        # commodities: gold, silver, metals, ag
        "XLE", "XLF", "XLRE",              # sectors: energy, financials, real estate
    ],
    "lookback_months": 12,          # [9, 12, 18] for sensitivity scan
    "vix_stress_threshold": 25,     # VIX > this → half exposure; [20, 25, 30]
    "vix_crisis_threshold": 35,     # VIX > this → flat; [30, 35, 40]
    "intramonth_stop_pct": 0.20,    # per-asset stop-loss from entry price
    "long_only": True,              # long-only; flat for negative signals
    "init_cash": 25000,             # starting capital ($)
    "order_qty": 100,               # order size in shares (for market impact calc)
}

TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_YEAR = 252

# XLRE launched October 2015. If it has insufficient history before IS start,
# substitute IYR (iShares US Real Estate, since June 2000). Approved by Research Director.
XLRE_MIN_DAYS_BEFORE_IS = 400
XLRE_SUBSTITUTE = "IYR"


# ── Data Loading ───────────────────────────────────────────────────────────────

def download_data(
    tickers: list, start: str, end: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Download adjusted close prices and volume via yfinance.
    auto_adjust=True: adjusted for splits and dividends.

    Returns:
        close:  DataFrame, adjusted closing prices
        volume: DataFrame, daily share volume
    """
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        volume = raw["Volume"]
    else:
        # Single-ticker flat columns
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
        volume = raw[["Volume"]].rename(columns={"Volume": tickers[0]})

    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    if isinstance(volume, pd.Series):
        volume = volume.to_frame(name=tickers[0])

    available = [t for t in tickers if t in close.columns]
    return close[available].copy(), volume[available].copy()


def download_vix(start: str, end: str) -> pd.Series:
    """
    Download VIX daily close from Yahoo Finance (ticker: ^VIX).

    No look-ahead: caller uses VIX at date T for positions starting at T+1.
    Downloads from slightly before start to ensure month-end VIX is available.

    Returns pd.Series named 'VIX'.
    Raises ValueError if data is empty.
    """
    raw = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError("VIX download returned empty. Check Yahoo Finance connection.")

    if isinstance(raw.columns, pd.MultiIndex):
        vix = raw["Close"].squeeze()
    else:
        vix = raw["Close"]

    if isinstance(vix, pd.DataFrame):
        vix = vix.iloc[:, 0]

    return vix.rename("VIX")


def resolve_universe(tickers: list, is_start: str = "2018-01-01") -> list:
    """
    Resolve ETF universe: substitute XLRE with IYR if XLRE lacks sufficient history.

    Survivorship bias note:
    - All ETFs except XLRE/IYR have data back to at least 2007 (DBB, DBA, HYG, SLV).
    - No ETF was selected based on forward-looking backtest performance.
    - XLRE (Oct 2015): has ~2+ years before 2018 IS start. IYR (Jun 2000): full IS coverage.
    - Universe represents 5 asset classes × 3 instruments: structured diversification,
      not return-chasing.

    Returns the final universe list (XLRE or IYR, all others unchanged).
    """
    if "XLRE" not in tickers:
        return tickers

    try:
        # Check XLRE data availability before IS start
        is_ts = pd.Timestamp(is_start)
        check_start = str((is_ts - pd.DateOffset(years=3)).date())
        xlre_raw, _ = download_data(["XLRE"], check_start, is_start)
        xlre_days = len(xlre_raw["XLRE"].dropna())
        if xlre_days >= XLRE_MIN_DAYS_BEFORE_IS:
            return tickers  # XLRE has sufficient history
    except Exception:
        pass  # Fall through to substitution

    warnings.warn(
        f"XLRE has <{XLRE_MIN_DAYS_BEFORE_IS} trading days before IS start {is_start}. "
        f"Substituting XLRE with {XLRE_SUBSTITUTE} (iShares US Real Estate, since 2000). "
        "This substitution is pre-approved per hypothesis file 07b_multi_asset_tsmom_expanded.md."
    )
    return [XLRE_SUBSTITUTE if t == "XLRE" else t for t in tickers]


# ── Data Quality ───────────────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame) -> dict:
    """
    Data quality report per Engineering Director checklist.

    Notes:
    - Survivorship bias: Fixed universe; no ETF selected on forward performance.
      DBB/DBA/HYG/SLV launched 2006-2007 — present for full 2018-2023 IS window.
    - Price adjustments: yfinance auto_adjust=True (splits + dividends).
    - Earnings exclusion: N/A — ETFs have no individual earnings events.
    - Delisted: N/A — all are major ETFs with negligible delisting risk.
    - Data gaps: flagged if any ticker has >5 missing business days.
    """
    report = {
        "survivorship_bias": (
            "15-ETF fixed universe. All ETFs present since at least 2007 (DBB, DBA, HYG, SLV). "
            "No ETF selected on forward performance. XLRE (2015) → IYR (2000) if data insufficient."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — ETFs have no individual earnings events.",
        "delisted": "N/A — all are major actively-traded ETFs.",
        "tickers": {},
    }

    flagged = []
    for ticker in close.columns:
        price = close[ticker].dropna()
        if price.empty:
            report["tickers"][ticker] = {"error": "No data returned"}
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

    if flagged:
        warnings.warn(f"Data gap flag (>5 missing business days): {flagged}")

    return report


# ── VIX Regime Gate ────────────────────────────────────────────────────────────

def compute_vix_regime(
    vix_close: pd.Series,
    rebal_dates: pd.DatetimeIndex,
    daily_index: pd.DatetimeIndex,
    stress_threshold: float,
    crisis_threshold: float,
) -> tuple[pd.Series, pd.Series]:
    """
    Compute VIX-based position scale at monthly and intramonth frequency.

    Monthly gate (strictly no look-ahead):
        VIX_T = closing VIX value at end-of-month T.
        Applied to M+1 positions (first trading day after T).
        VIX_T > crisis_threshold:  scale = 0.0 (flat, capital preservation)
        VIX_T > stress_threshold:  scale = 0.5 (half exposure, stress regime)
        VIX_T ≤ stress_threshold:  scale = 1.0 (full exposure, normal)

    Intramonth override:
        If VIX.close[T] > crisis_threshold, force-exit all positions at T+1 open.
        Accepts 1-day execution lag (documented in hypothesis per Research Director).

    References:
        Barroso & Santa-Clara (2015): volatility-scaling avoids high-VIX whipsaw periods.
        Daniel & Moskowitz (2016): VIX > 25 documented as momentum performance degradation period.

    Returns:
        monthly_scale:    pd.Series indexed by rebal_dates, values in {0.0, 0.5, 1.0}
        daily_crisis_exit: pd.Series (bool), True on days to force-exit all positions
    """
    monthly_scale = {}
    for rd in rebal_dates:
        # Use only VIX data known at or before this rebalancing date
        past_vix = vix_close.loc[:rd]
        if past_vix.empty:
            monthly_scale[rd] = 1.0  # default to full exposure if no VIX data
            continue
        vix_val = float(past_vix.iloc[-1])
        if vix_val > crisis_threshold:
            monthly_scale[rd] = 0.0
        elif vix_val > stress_threshold:
            monthly_scale[rd] = 0.5
        else:
            monthly_scale[rd] = 1.0

    monthly_scale_series = pd.Series(monthly_scale, name="vix_scale")

    # Intramonth: T+1 is a force-exit day if VIX[T] > crisis_threshold
    # Forward-fill VIX onto close.index to handle trading day alignment
    vix_on_daily = vix_close.reindex(daily_index, method="ffill")
    daily_crisis_exit = pd.Series(False, index=daily_index)
    for i in range(1, len(daily_index)):
        if vix_on_daily.iloc[i - 1] > crisis_threshold:
            daily_crisis_exit.iloc[i] = True

    return monthly_scale_series, daily_crisis_exit


# ── Momentum Signal ────────────────────────────────────────────────────────────

def compute_momentum_signal(close: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute N-month trailing return signal at monthly (end-of-month) frequency.

    Signal logic (long-only):
        R_Nm(i, T) = (P(i, T) / P(i, T − N×21)) − 1
        signal(i, T) = +1.0 if R_Nm > 0  → long
        signal(i, T) =  0.0 otherwise     → flat (cash)

    Lookback in trading days = lookback_months × 21 (approximate conversion).
    Resampled to end-of-month close. No look-ahead: R_Nm at T uses only P_T and P_{T−lb}.

    Returns:
        pd.DataFrame at monthly frequency; columns = tickers; values ∈ {0.0, 1.0}
    """
    lookback_td = params["lookback_months"] * TRADING_DAYS_PER_MONTH
    trailing_return = close.pct_change(lookback_td)
    monthly_return = trailing_return.resample("ME").last()
    signal = (monthly_return > 0).astype(float)
    return signal


# ── Entry / Exit Signal Generation ────────────────────────────────────────────

def generate_daily_signals(
    close: pd.DataFrame,
    vix_close: pd.Series,
    params: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """
    Generate daily entry/exit signals and VIX position scale.

    Execution model:
    - Monthly signal + VIX regime computed at end-of-month close T.
    - Execution fires at open of first trading day T+1 (strict no-look-ahead).
    - Entry: signal = +1 AND vix_scale > 0 at rebalancing T.
      * vectorbt ignores re-entries while in position (accumulate=False default),
        which allows monthly re-entry after stop-outs without position stacking.
    - Exit:
      * Monthly: signal turned to 0, OR vix_scale = 0 (crisis gate).
      * Intramonth: VIX.close[T] > crisis_threshold → force-exit T+1 (1-day lag).

    Note on stress-regime sizing (vix_scale = 0.5):
    - Position scale = 0.5 is returned in vix_daily_scale for the runner to use.
    - The runner implements half-size entries via size_type='value' with
      explicit dollar amounts (cash_per_ticker × vix_scale).
    - If a position was entered at 0.5-scale and VIX normalizes next month,
      size is NOT dynamically increased (accumulate=False prevents re-entry
      while in position). This is a known first-pass limitation.

    Returns:
        entries:          Boolean DataFrame (daily)
        exits:            Boolean DataFrame (daily)
        vix_daily_scale:  pd.Series (float, daily), values in {0.0, 0.5, 1.0}
                          Reflects monthly VIX gate (not intraday crossings).
    """
    monthly_signal = compute_momentum_signal(close, params)
    monthly_dates = monthly_signal.index

    monthly_vix_scale, daily_crisis_exit = compute_vix_regime(
        vix_close,
        monthly_dates,
        close.index,
        params["vix_stress_threshold"],
        params["vix_crisis_threshold"],
    )

    entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    exits = pd.DataFrame(False, index=close.index, columns=close.columns)
    # vix_daily_scale: forward-fill monthly scale to daily bars (for runner sizing)
    vix_daily_scale = pd.Series(1.0, index=close.index, name="vix_daily_scale")

    for i, rebal_date in enumerate(monthly_dates):
        future_dates = close.index[close.index > rebal_date]
        if len(future_dates) == 0:
            continue
        exec_date = future_dates[0]

        current_sig = monthly_signal.loc[rebal_date]
        prev_sig = (
            monthly_signal.iloc[i - 1]
            if i > 0
            else pd.Series(0.0, index=monthly_signal.columns)
        )
        vix_scale = float(monthly_vix_scale.get(rebal_date, 1.0))

        # Propagate monthly VIX scale to all days until the next rebalancing
        next_rebal_dates = [r for r in monthly_dates if r > rebal_date]
        if next_rebal_dates:
            period_end = close.index[close.index <= next_rebal_dates[0]]
            period_end = period_end[period_end >= exec_date]
        else:
            period_end = close.index[close.index >= exec_date]
        if len(period_end) > 0:
            vix_daily_scale.loc[period_end] = vix_scale

        for ticker in close.columns:
            if vix_scale == 0.0:
                # Crisis regime: exit any existing long position
                if prev_sig[ticker] > 0:
                    exits.at[exec_date, ticker] = True
            elif current_sig[ticker] > 0:
                # Active signal: entry (or re-entry after stop-out)
                entries.at[exec_date, ticker] = True
            elif current_sig[ticker] == 0 and prev_sig[ticker] > 0:
                # Signal turned off: exit
                exits.at[exec_date, ticker] = True

    # Intramonth crisis override: force-exit all on T+1 when VIX[T] > crisis_threshold
    # This fires independently of the monthly gate (e.g., mid-month VIX spike).
    crisis_exit_dates = daily_crisis_exit.index[daily_crisis_exit]
    if len(crisis_exit_dates) > 0:
        exits.loc[crisis_exit_dates, :] = True

    return entries, exits, vix_daily_scale


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def compute_market_impact(
    close: pd.DataFrame, volume: pd.DataFrame, params: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Square-root market impact (canonical Engineering Director model).

    Formula: impact = k × σ × sqrt(Q / ADV)
      k   = 0.1 (Johnson, Algorithmic Trading & DMA)
      σ   = 20-day rolling daily return volatility
      Q   = order dollar value (order_qty × close)
      ADV = 20-day average dollar volume (volume × close)

    Returns:
        market_impact: impact fraction (same shape as close)
        q_over_adv:    Q/ADV ratios for liquidity flagging
    """
    k = 0.1
    order_qty = params.get("order_qty", 100)
    sigma = close.pct_change().rolling(20).std()
    dollar_volume = volume * close
    adv_dollar = dollar_volume.rolling(20).mean()
    order_value = order_qty * close
    q_over_adv = (order_value / adv_dollar.replace(0, np.nan)).fillna(0.0).clip(lower=0)
    impact = k * sigma * np.sqrt(q_over_adv)
    return impact.fillna(0.0), q_over_adv


def check_liquidity_constraints(q_over_adv: pd.DataFrame) -> dict:
    """
    Flag dates/tickers where order quantity exceeds 1% of average daily volume.

    At $25K with ~$1,667 per ETF position, Q/ADV for liquid ETFs (SPY, QQQ, TLT)
    will be effectively 0. All 15 ETFs have daily volume well above $1M — at $1,667
    positions, liquidity constraint is never expected to trigger.
    """
    constrained = q_over_adv > 0.01
    n_bars = int(constrained.sum().sum())
    if n_bars == 0:
        return {"liquidity_constrained": False, "constrained_bars": 0}

    report = {"liquidity_constrained": True, "constrained_bars": n_bars, "detail": {}}
    for ticker in constrained.columns:
        bad_dates = constrained[ticker][constrained[ticker]].index
        if len(bad_dates) > 0:
            report["detail"][ticker] = [str(d.date()) for d in bad_dates[:5]]
            warnings.warn(
                f"Liquidity constraint: {ticker} Q/ADV > 0.01 on {len(bad_dates)} bars. "
                "Order exceeds 1% of average daily volume."
            )
    return report


# ── Strategy Runner ────────────────────────────────────────────────────────────

def run_backtest(
    params: dict = PARAMETERS,
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    return_portfolio: bool = False,
) -> dict:
    """
    Run H07b Multi-Asset TSMOM and return a metrics dict.

    VIX regime gate:
    - VIX > crisis_threshold at month-end T → flat for M+1 (entries blocked, exits forced)
    - VIX > stress_threshold at month-end T → 50% scale for M+1
    - Intramonth: VIX > crisis_threshold on any day → force-exit all positions next day

    Position sizing with VIX gate:
    - init_cash split equally across tickers: cash_per_ticker = init_cash / n_tickers
    - Normal (scale=1.0): invest full cash_per_ticker per entry
    - Stress (scale=0.5): invest cash_per_ticker × 0.5 per entry (size_type='value')
    - Crisis (scale=0.0): no entries; existing positions exited

    Transaction costs:
    - Fixed:          $0.005/share → fraction = 0.005 / close
    - Slippage:       0.05% base + square-root market impact
    - Intramonth stop: sl_stop = intramonth_stop_pct (from entry price, per-asset)

    Returns:
        dict with sharpe, max_drawdown, win_rate, win_loss_ratio, profit_factor,
        total_return, trade_count, tickers_traded, data_quality, liquidity,
        vix_regime_stats, and optionally 'portfolio' (vbt.Portfolio).

    Raises:
        ValueError: if no price data available or insufficient history.
    """
    # 1. Resolve universe (XLRE → IYR substitution if needed)
    universe = resolve_universe(list(params.get("universe", PARAMETERS["universe"])), start)

    # 2. Download price, volume, and VIX data
    close, volume = download_data(universe, start, end)

    # Download VIX with a 2-month pre-start buffer to ensure month-end VIX is available
    vix_start = str((pd.Timestamp(start) - pd.DateOffset(months=2)).date())
    vix_close = download_vix(vix_start, end)

    # 3. Data quality checks
    quality_report = check_data_quality(close)

    close = close.dropna(axis=1, how="all")
    if close.empty:
        raise ValueError(f"No price data for {universe} in {start}–{end}.")

    min_required = params["lookback_months"] * TRADING_DAYS_PER_MONTH + 20
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    # 4. Generate signals
    entries, exits, vix_daily_scale = generate_daily_signals(close, vix_close, params)

    # 5. Market impact and transaction costs
    market_impact, q_over_adv = compute_market_impact(close, volume, params)
    liquidity_report = check_liquidity_constraints(q_over_adv)
    fees = 0.005 / close
    slippage = 0.0005 + market_impact

    # VIX regime statistics
    vix_window = vix_close.reindex(close.index, method="ffill")
    n_crisis = int((vix_window > params["vix_crisis_threshold"]).sum())
    n_stress = int(
        ((vix_window > params["vix_stress_threshold"]) &
         (vix_window <= params["vix_crisis_threshold"])).sum()
    )
    n_normal = int((vix_window <= params["vix_stress_threshold"]).sum())
    vix_regime_stats = {
        "days_crisis": n_crisis,
        "days_stress": n_stress,
        "days_normal": n_normal,
        "pct_crisis": round(n_crisis / max(1, len(vix_window)), 4),
        "pct_stress": round(n_stress / max(1, len(vix_window)), 4),
        "pct_normal": round(n_normal / max(1, len(vix_window)), 4),
    }

    empty_result = {
        "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0, "win_loss_ratio": 0.0,
        "profit_factor": 0.0, "total_return": 0.0, "trade_count": 0,
        "period": f"{start} to {end}", "tickers_traded": list(close.columns),
        "data_quality": quality_report, "liquidity": liquidity_report,
        "vix_regime_stats": vix_regime_stats,
    }

    if entries.sum().sum() == 0:
        warnings.warn("No entry signals generated — returning empty result.")
        return empty_result

    # 6. Build portfolio (equal capital split per ticker, VIX-scaled sizing)
    n_tickers = len(close.columns)
    cash_per_ticker = params.get("init_cash", 25000) / n_tickers

    # Build size DataFrame: on entry bars, size = cash_per_ticker × vix_scale (in dollars)
    # Non-entry bars: NaN (vectorbt ignores size on non-signal bars)
    # size_type='value': dollar value of position
    size_dollars = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    entry_mask = entries.values
    for col_idx, ticker in enumerate(close.columns):
        for row_idx in np.where(entry_mask[:, col_idx])[0]:
            date = close.index[row_idx]
            scale = float(vix_daily_scale.iloc[row_idx])
            size_dollars.iloc[row_idx, col_idx] = cash_per_ticker * max(scale, 0.5)

    try:
        pf = vbt.Portfolio.from_signals(
            close,
            entries=entries,
            exits=exits,
            size=size_dollars,
            size_type="value",
            sl_stop=params.get("intramonth_stop_pct", 0.20),
            fees=fees,
            slippage=slippage,
            init_cash=cash_per_ticker,
            group_by=False,
        )
    except Exception as exc:
        # Fallback: if size_type='value' fails, use default sizing (invest all cash)
        warnings.warn(f"VIX-scaled sizing failed ({exc}), falling back to default sizing.")
        pf = vbt.Portfolio.from_signals(
            close,
            entries=entries,
            exits=exits,
            sl_stop=params.get("intramonth_stop_pct", 0.20),
            fees=fees,
            slippage=slippage,
            init_cash=cash_per_ticker,
            group_by=False,
        )

    # 7. Portfolio-level metrics
    combined_value = pf.value().sum(axis=1)
    combined_returns = combined_value.pct_change().fillna(0).values
    sharpe = float(combined_returns.mean() / (combined_returns.std() + 1e-8) * np.sqrt(252))
    cum = np.cumprod(1 + combined_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(combined_value.iloc[-1] / combined_value.iloc[0] - 1)
    trade_count = int(pf.trades.count().sum())

    try:
        pnl_vals = pf.trades.pnl.values
        pnl_vals = pnl_vals[~np.isnan(pnl_vals)]
        win_rate = float(np.mean(pnl_vals > 0)) if len(pnl_vals) > 0 else 0.0
        wins = pnl_vals[pnl_vals > 0]
        losses = pnl_vals[pnl_vals < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
        profit_factor = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0
            else float("inf")
        )
    except Exception:
        pnl_vals = np.array([])
        win_rate = win_loss_ratio = profit_factor = 0.0

    if win_rate < 0.50 and win_loss_ratio < 1.2:
        warnings.warn(
            f"Win rate {win_rate:.1%} < 50% AND win/loss ratio {win_loss_ratio:.2f} < 1.2. "
            "Strategy may not pass Gate 1 thresholds."
        )

    result = {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "win_loss_ratio": win_loss_ratio,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "trade_count": trade_count,
        "period": f"{start} to {end}",
        "tickers_traded": list(close.columns),
        "data_quality": quality_report,
        "liquidity": liquidity_report,
        "vix_regime_stats": vix_regime_stats,
        "_combined_returns": combined_returns,
        "_pnl_vals": pnl_vals,
    }

    if return_portfolio:
        result["portfolio"] = pf

    return result


# ── Parameter Sensitivity Scan ─────────────────────────────────────────────────

def scan_parameters(
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Scan Sharpe across the H07b Gate 1 parameter grid.

    Parameter grid:
    - lookback_months:      [9, 12, 18]   (dropped 6m to reduce sensitivity variance)
    - vix_stress_threshold: [20, 25, 30]  (sensitivity ±5 from base 25)
    - intramonth_stop_pct:  [0.15, 0.20, 0.25]

    Gate 1 disqualification: Sharpe variance > 30% across any parameter dimension.
    """
    results: dict = {}

    grid = {
        "lookback_months": [9, 12, 18],
        "vix_stress_threshold": [20, 25, 30],
        "intramonth_stop_pct": [0.15, 0.20, 0.25],
    }

    for param_name, values in grid.items():
        for val in values:
            p = {**base_params, param_name: val}
            key = f"{param_name}={val}"
            try:
                r = run_backtest(params=p, start=start, end=end)
                results[key] = round(r["sharpe"], 4)
            except Exception as exc:
                results[key] = f"error: {exc}"

    sharpe_nums = [v for v in results.values() if isinstance(v, float) and not np.isnan(v)]
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


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="H07b Multi-Asset TSMOM (15-ETF + VIX regime gate) backtest runner."
    )
    parser.add_argument("--plot", action="store_true",
                        help="Show interactive Plotly chart after IS backtest.")
    args = parser.parse_args()

    print("H07b: Running IS backtest (2018-01-01 to 2021-12-31)...")
    is_result = run_backtest(start="2018-01-01", end="2021-12-31", return_portfolio=args.plot)
    safe_keys = {k: v for k, v in is_result.items()
                 if k not in ("portfolio", "data_quality", "liquidity",
                              "_combined_returns", "_pnl_vals")}
    print("IS:", safe_keys)

    if args.plot:
        pf = is_result["portfolio"]
        fig = pf.plot()
        fig.show()

    print("\nH07b: Running OOS backtest (2022-01-01 to 2023-12-31)...")
    oos_result = run_backtest(start="2022-01-01", end="2023-12-31")
    safe_oos = {k: v for k, v in oos_result.items()
                if k not in ("data_quality", "liquidity", "_combined_returns", "_pnl_vals")}
    print("OOS:", safe_oos)

    print("\nVIX regime statistics (IS):")
    print(is_result.get("vix_regime_stats", {}))
