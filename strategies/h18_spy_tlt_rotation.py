"""
Strategy: H18 SPY/TLT Weekly Momentum Rotation
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: SPY and TLT exhibit persistent relative momentum at weekly frequency.
            Rotate to the outperforming asset (100%) or hold 50/50 in neutral zone.
            A dual-vol filter exits to cash when both assets show simultaneous high vol
            (inflation / correlation-breakdown regime detection).
Asset class: equities + bonds (ETFs)
Parent task: QUA-187

References:
  - Grossmann, F. (2015) "The SPY-TLT Universal Investment Strategy." Logical Invest.
  - Alvarez Quant Trading. "SPY TLT Rotation."
  - QuantifiedStrategies.com. "Monthly Momentum in S&P 500 and Treasury Bonds."

IS window:  2018-01-01 to 2022-12-31
OOS window: 2023-01-01 to 2025-12-31

Universe notes:
  - SPY (S&P 500 ETF): launched 1993. Full IS/OOS coverage.
  - TLT (20+ Year Treasury Bond ETF): launched July 2002. Full IS/OOS coverage (IS start 2018).
  - Both ETFs are highly liquid (AUM > $30B each) and actively traded. No delisting risk.
  - Prices: auto_adjust=True for split/dividend adjustment.
  - Data gaps: Flag any ticker with >5 missing trading days.
  - Earnings exclusion: N/A — ETFs; no individual earnings events.

Transaction cost model (canonical, per Engineering Director AGENTS.md):
  - Fixed: $0.005/share
  - Slippage: 0.05% of trade value
  - Market impact: k × σ × sqrt(Q / ADV), k=0.1
  - Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True

Key risk — 2022 rate shock:
  The SPY-TLT negative correlation broke down in 2022 (both assets fell simultaneously).
  The dual-vol regime filter (SPY 20d vol > 25% AND TLT 20d vol > 15%) is the primary
  defense: triggers cash exit when simultaneous high vol indicates correlation breakdown.
  Engineering Director must verify this filter triggers before 2022-03-01 (see PF-4).
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    # Universe — 2-asset rotation
    "spy": "SPY",
    "tlt": "TLT",
    # Momentum lookback in trading days — sweep: {10, 15, 20}
    "mom_lookback_days": 15,
    # Dead-band threshold: only rotate if |mom_diff| > threshold — sweep: {0.0, 0.005, 0.01}
    "threshold": 0.0,
    # Dual-vol regime filter: exit to cash when BOTH exceed their respective thresholds
    # Annualized vols (20-day rolling daily return std × sqrt(252))
    "vol_filter_spy_pct": 0.25,    # 25% annualized — sweep: {0.20, 0.25, 0.30}
    "vol_filter_tlt_pct": 0.15,    # 15% annualized
    # Starting capital
    "init_cash": 25000,
    # Vol rolling window (days)
    "vol_window": 20,
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

    Universe: SPY (1993), TLT (July 2002). IS start 2018 covers both fully.
    TLT availability note: TLT launched July 26, 2002. IS window starts 2018-01-01,
    providing 15+ years of TLT history with full coverage.
    """
    report = {
        "survivorship_bias": (
            "Fixed 2-ticker universe (SPY, TLT). Pre-selected by hypothesis specification. "
            "SPY launched 1993; TLT launched July 2002. Full IS/OOS coverage (IS: 2018-2022, "
            "OOS: 2023-2025). Both ETFs active and liquid. No survivorship bias."
        ),
        "tlt_availability": (
            "TLT launched July 26, 2002. IS period starts 2018-01-01 (15+ years of TLT data). "
            "Full IS/OOS coverage confirmed."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — ETFs; no individual earnings events.",
        "delisted": "N/A — SPY (~$500B AUM) and TLT (~$50B AUM) are active major ETFs.",
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


# ── Volatility Computation ──────────────────────────────────────────────────────

def compute_annualized_vol(prices: pd.Series, window: int = 20) -> pd.Series:
    """
    Compute 20-day rolling annualized realized volatility.
    annualized_vol = rolling(window).std(daily_returns) × sqrt(252)
    Strictly backward-looking (no look-ahead bias).
    """
    return prices.pct_change().rolling(window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)


# ── Signal Computation ──────────────────────────────────────────────────────────

def get_weekly_rebalance_dates(price_index: pd.DatetimeIndex, start: str, end: str) -> list:
    """
    Return sorted list of rebalance dates (Friday or last trading day of each week)
    within [start, end] that are present in the price index.
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


def compute_spy_tlt_signal(
    close: pd.DataFrame,
    params: dict,
    window_start: str,
    window_end: str,
) -> pd.DataFrame:
    """
    Compute weekly SPY/TLT rotation signal at each Friday close.

    Signal logic (no look-ahead — uses only prices at/before rebalance date):
      1. mom_spy = SPY.pct_change(lookback)    (trailing lookback-day return)
      2. mom_tlt = TLT.pct_change(lookback)
      3. mom_diff = mom_spy - mom_tlt
      4. Signal:
           - mom_diff >  threshold  → 100% SPY (equity momentum regime)
           - mom_diff < -threshold  → 100% TLT (bond momentum regime)
           - |mom_diff| <= threshold → 50/50 SPY+TLT (neutral zone)
      5. Dual-vol regime filter:
           - If SPY 20d annualized vol > vol_filter_spy_pct
             AND TLT 20d annualized vol > vol_filter_tlt_pct
           → exit all, hold cash (inflation / correlation-breakdown regime)

    Args:
        close:        Full price DataFrame (with pre-window buffer for vol/mom warm-up).
        params:       Strategy parameters.
        window_start: Start date for signal generation.
        window_end:   End date.

    Returns:
        DataFrame indexed by rebalance date with columns:
          - spy_weight: float (0.0, 0.5, or 1.0)
          - tlt_weight: float (0.0, 0.5, or 1.0)
          - regime_active: bool (True = vol filter triggered → cash)
          - mom_diff: float (momentum differential, NaN if insufficient history)
          - spy_vol: float (annualized SPY vol at signal date)
          - tlt_vol: float (annualized TLT vol at signal date)
    """
    spy = params["spy"]
    tlt = params["tlt"]
    lookback = params["mom_lookback_days"]
    threshold = params["threshold"]
    vol_spy_thresh = params["vol_filter_spy_pct"]
    vol_tlt_thresh = params["vol_filter_tlt_pct"]
    vol_window = params["vol_window"]

    # Compute momentum scores and annualized vols (all backward-looking)
    mom_spy = close[spy].pct_change(lookback) if spy in close.columns else pd.Series(dtype=float)
    mom_tlt = close[tlt].pct_change(lookback) if tlt in close.columns else pd.Series(dtype=float)
    vol_spy = compute_annualized_vol(close[spy], vol_window) if spy in close.columns else pd.Series(dtype=float)
    vol_tlt = compute_annualized_vol(close[tlt], vol_window) if tlt in close.columns else pd.Series(dtype=float)

    rebalance_dates = get_weekly_rebalance_dates(close.index, window_start, window_end)

    rows = []
    for date in rebalance_dates:
        # Look up signal values at this date
        m_spy = mom_spy.get(date, np.nan)
        m_tlt = mom_tlt.get(date, np.nan)
        v_spy = vol_spy.get(date, np.nan)
        v_tlt = vol_tlt.get(date, np.nan)

        # Dual-vol regime filter: both must exceed threshold simultaneously
        regime_active = (
            not pd.isna(v_spy) and not pd.isna(v_tlt) and
            v_spy > vol_spy_thresh and v_tlt > vol_tlt_thresh
        )

        if regime_active or pd.isna(m_spy) or pd.isna(m_tlt):
            rows.append({
                "date": date,
                "spy_weight": 0.0,
                "tlt_weight": 0.0,
                "regime_active": regime_active,
                "mom_diff": np.nan if pd.isna(m_spy) or pd.isna(m_tlt) else float(m_spy - m_tlt),
                "spy_vol": float(v_spy) if not pd.isna(v_spy) else None,
                "tlt_vol": float(v_tlt) if not pd.isna(v_tlt) else None,
            })
            continue

        mom_diff = float(m_spy - m_tlt)
        if mom_diff > threshold:
            spy_wt, tlt_wt = 1.0, 0.0     # 100% SPY
        elif mom_diff < -threshold:
            spy_wt, tlt_wt = 0.0, 1.0     # 100% TLT
        else:
            spy_wt, tlt_wt = 0.5, 0.5     # 50/50 neutral zone

        rows.append({
            "date": date,
            "spy_weight": spy_wt,
            "tlt_weight": tlt_wt,
            "regime_active": False,
            "mom_diff": mom_diff,
            "spy_vol": float(v_spy) if not pd.isna(v_spy) else None,
            "tlt_vol": float(v_tlt) if not pd.isna(v_tlt) else None,
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).set_index("date")


# ── Pre-Flight Verification ─────────────────────────────────────────────────────

def check_vol_filter_trigger_2022(close: pd.DataFrame, params: dict) -> dict:
    """
    PF-4 verification: find the first date in 2022 when the dual-vol filter triggers.

    Engineering Director requirement (QUA-187): if the first trigger is after 2022-03-01,
    flag as a concern and notify Engineering Director — the filter may be too late to
    protect against the early 2022 rate-shock drawdown.

    Expected: filter triggers late January / early February 2022.

    Returns:
        dict with first_trigger_date, trigger_before_cutoff, cutoff_date, and details.
    """
    spy = params["spy"]
    tlt = params["tlt"]
    vol_window = params["vol_window"]
    vol_spy_thresh = params["vol_filter_spy_pct"]
    vol_tlt_thresh = params["vol_filter_tlt_pct"]
    cutoff = pd.Timestamp("2022-03-01")

    vol_spy = compute_annualized_vol(close[spy], vol_window) if spy in close.columns else pd.Series()
    vol_tlt = compute_annualized_vol(close[tlt], vol_window) if tlt in close.columns else pd.Series()

    # Find dates in 2022 where both vols exceed their thresholds
    year_2022 = close.index[(close.index >= "2022-01-01") & (close.index <= "2022-12-31")]
    trigger_dates = [
        d for d in year_2022
        if d in vol_spy.index and d in vol_tlt.index
        and not pd.isna(vol_spy[d]) and not pd.isna(vol_tlt[d])
        and vol_spy[d] > vol_spy_thresh and vol_tlt[d] > vol_tlt_thresh
    ]

    if not trigger_dates:
        return {
            "first_trigger_date": None,
            "trigger_before_cutoff": False,
            "cutoff_date": str(cutoff.date()),
            "warning": "No dual-vol filter trigger in 2022. Filter may not protect against 2022 drawdown.",
            "vol_filter_spy_pct": vol_spy_thresh,
            "vol_filter_tlt_pct": vol_tlt_thresh,
        }

    first_trigger = min(trigger_dates)
    before_cutoff = first_trigger <= cutoff

    return {
        "first_trigger_date": str(first_trigger.date()),
        "trigger_before_cutoff": before_cutoff,
        "cutoff_date": str(cutoff.date()),
        "total_trigger_days_2022": len(trigger_dates),
        "pass": before_cutoff,
        "message": (
            f"PASS: filter triggers {first_trigger.date()} ≤ {cutoff.date()}"
            if before_cutoff
            else f"FAIL: filter triggers {first_trigger.date()} > {cutoff.date()} "
                 "— flag to Engineering Director (late trigger may not protect 2022 drawdown)"
        ),
        "vol_filter_spy_pct": vol_spy_thresh,
        "vol_filter_tlt_pct": vol_tlt_thresh,
    }


def check_trade_count_gate(trade_count: int, is_years: float, min_per_year: int = 30) -> dict:
    """
    PF-1 verification: IS annual trade count ≥ min_per_year.
    For H18 (2-asset rotation), Engineering Director requires ≥ 30/yr.
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


# ── Portfolio Simulation ────────────────────────────────────────────────────────

def simulate_spy_tlt_portfolio(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    signal_df: pd.DataFrame,
    params: dict,
    close_full: pd.DataFrame = None,
    volume_full: pd.DataFrame = None,
) -> dict:
    """
    Simulate H18 SPY/TLT rotation portfolio from weekly rebalance signals.

    Execution model:
    - Signal at Friday close T → execute at Friday close T (same-day EOD fill).
    - Rebalance: adjust SPY/TLT weights toward target allocation.
      Execution order: sell excess positions first, then buy new positions.
    - No action if target allocation equals current allocation (no unnecessary costs).
    - 3 possible target states: 100% SPY, 100% TLT, 50/50, or 0% (cash).

    Transaction cost model (canonical):
    - Fixed: $0.005/share
    - Slippage: 0.05% of trade value
    - Market impact: k × σ × sqrt(Q / ADV), k=0.1

    Args:
        close:        Simulation window price data.
        volume:       Simulation window volume data.
        signal_df:    Output of compute_spy_tlt_signal() for this window.
        params:       Strategy parameters.
        close_full:   Full buffered price data for warm σ/ADV rolling windows.
        volume_full:  Full buffered volume data.

    Returns:
        dict with portfolio_value series, trade_log, metrics, and liquidity flags.
    """
    spy = params["spy"]
    tlt = params["tlt"]
    init_cash = params["init_cash"]
    k_impact = 0.1  # Almgren-Chriss constant

    # Precompute sigma and ADV using full buffered history (prevents NaN at window start)
    _close_risk = close_full if close_full is not None else close
    _volume_risk = volume_full if volume_full is not None else volume

    sigma = {}
    adv = {}
    for ticker in [spy, tlt]:
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

    def _sell_shares(ticker: str, date, shares: float) -> float:
        """Sell `shares` of `ticker`; return net proceeds."""
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

    def _buy_shares(ticker: str, date, cash_allocated: float) -> float:
        """Buy `ticker` with `cash_allocated`; return shares bought."""
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
        effective_cost = price * (1 + slippage_pct) + 0.005
        shares_bought = cash_allocated / effective_cost

        if pd.isna(shares_bought) or shares_bought <= 0:
            warnings.warn(
                f"BUY skipped: {ticker} on {date.date()} — "
                f"shares={shares_bought:.4f}, cost={effective_cost:.4f}, sigma={sig_val:.6f}."
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

    # Initialize portfolio state
    holdings = {spy: 0.0, tlt: 0.0}    # shares held per ticker
    cash = float(init_cash)
    trade_log = []
    liquidity_flags = []
    portfolio_value = pd.Series(index=close.index, dtype=float)

    # Build rebalance schedule from signal_df
    rebalance_schedule = {}
    if not signal_df.empty:
        for date, row in signal_df.iterrows():
            if date in close.index:
                rebalance_schedule[date] = {
                    spy: float(row["spy_weight"]),
                    tlt: float(row["tlt_weight"]),
                }

    for i, date in enumerate(close.index):
        if i == 0:
            portfolio_value.iloc[0] = cash
            continue

        # Rebalance on scheduled signal dates
        if date in rebalance_schedule:
            target_weights = rebalance_schedule[date]

            # Compute current portfolio NAV (before rebalance)
            nav = cash
            for ticker in [spy, tlt]:
                if ticker in close.columns and date in close.index:
                    p = close[ticker].loc[date]
                    if not pd.isna(p):
                        nav += holdings[ticker] * p

            # Compute target values
            target_values = {ticker: nav * w for ticker, w in target_weights.items()}

            # Execute sells first (free up cash), then buys
            # SELL: tickers where target_value < current_value
            for ticker in [spy, tlt]:
                if ticker not in close.columns or date not in close.index:
                    continue
                price = close[ticker].loc[date]
                if pd.isna(price) or price <= 0:
                    continue
                current_val = holdings[ticker] * price
                target_val = target_values.get(ticker, 0.0)

                if current_val - target_val > 1.0:  # Need to sell (>$1 threshold)
                    shares_to_sell = (current_val - target_val) / price
                    shares_to_sell = min(shares_to_sell, holdings[ticker])
                    if shares_to_sell > 0:
                        cash += _sell_shares(ticker, date, shares_to_sell)
                        holdings[ticker] -= shares_to_sell
                        if holdings[ticker] < 0:
                            holdings[ticker] = 0.0

            # BUY: tickers where target_value > current_value
            for ticker in [spy, tlt]:
                if ticker not in close.columns or date not in close.index:
                    continue
                price = close[ticker].loc[date]
                if pd.isna(price) or price <= 0:
                    continue
                current_val = holdings[ticker] * price
                target_val = target_values.get(ticker, 0.0)

                if target_val - current_val > 1.0:  # Need to buy (>$1 threshold)
                    cash_to_spend = min(target_val - current_val, cash)
                    if cash_to_spend > 0:
                        shares_bought = _buy_shares(ticker, date, cash_to_spend)
                        if shares_bought > 0:
                            holdings[ticker] += shares_bought
                            cash -= cash_to_spend
            cash = max(cash, 0.0)  # Guard floating-point negative

        # Daily NAV: mark holdings to market
        nav = cash
        for ticker in [spy, tlt]:
            if ticker in close.columns and date in close.index:
                p = close[ticker].loc[date]
                if not pd.isna(p):
                    nav += holdings[ticker] * p
        portfolio_value.iloc[i] = nav

    # Forward-fill any NaN values
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

    # Round-trip trade PnL
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
    Compute round-trip PnL from alternating buy/sell entries (FIFO).
    Open positions (no matching sell) are excluded.
    """
    trades = []
    open_positions = {}

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


# ── Main Backtest Entry Point ───────────────────────────────────────────────────

def run_backtest(
    params: dict = PARAMETERS,
    start: str = "2018-01-01",
    end: str = "2022-12-31",
) -> dict:
    """
    Run H18 SPY/TLT rotation backtest for a given period and parameter set.

    Downloads data (with pre-window buffer for warm-up), validates quality,
    computes weekly rotation signals with dual-vol filter, simulates portfolio,
    and returns a standardized metrics dict.

    Args:
        params: strategy parameters (see PARAMETERS constant)
        start:  backtest start date (inclusive)
        end:    backtest end date (inclusive)

    Returns:
        dict with sharpe, max_drawdown, win_rate, total_return, trade_count, etc.

    Raises:
        ValueError: if data is insufficient or required tickers are missing.
    """
    spy = params["spy"]
    tlt = params["tlt"]
    tickers = [spy, tlt]

    # Buffer: vol_window + lookback + 30 days for rolling warm-up
    vol_window = params["vol_window"]
    lookback = params["mom_lookback_days"]
    buffer_td = max(vol_window, lookback) + 30
    buf_start = str(
        (pd.Timestamp(start) - pd.tseries.offsets.BDay(buffer_td)).date()
    )

    close, volume = download_data(tickers, buf_start, end)

    quality_report = check_data_quality(close, tickers)

    close = close.dropna(axis=1, how="all")
    missing = [t for t in tickers if t not in close.columns]
    if missing:
        raise ValueError(f"Required tickers missing from downloaded data: {missing}")

    min_required = max(vol_window, lookback) + 10
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    # Compute weekly rotation signals using full buffered history
    signal_df = compute_spy_tlt_signal(close, params, start, end)

    if signal_df.empty:
        raise ValueError(f"No weekly signals generated for period {start} to {end}.")

    # Trim to simulation window
    close_window = close.loc[start:end]
    volume_window = volume.reindex(close_window.index).fillna(0)

    # Simulate portfolio with warm σ/ADV from full buffered data
    sim_result = simulate_spy_tlt_portfolio(
        close_window, volume_window, signal_df, params,
        close_full=close, volume_full=volume,
    )

    # Signal allocation breakdown
    spy_weeks = int(sum(1 for _, r in signal_df.iterrows() if r["spy_weight"] == 1.0))
    tlt_weeks = int(sum(1 for _, r in signal_df.iterrows() if r["tlt_weight"] == 1.0))
    neutral_weeks = int(sum(
        1 for _, r in signal_df.iterrows()
        if r["spy_weight"] == 0.5 and r["tlt_weight"] == 0.5
    ))
    cash_weeks = int(sum(1 for _, r in signal_df.iterrows() if r["regime_active"]))
    total_weeks = len(signal_df)

    holding_pct = {
        "SPY_100pct": round(spy_weeks / max(total_weeks, 1), 4),
        "TLT_100pct": round(tlt_weeks / max(total_weeks, 1), 4),
        "neutral_50_50": round(neutral_weeks / max(total_weeks, 1), 4),
        "_cash_regime": round(cash_weeks / max(total_weeks, 1), 4),
    }

    is_years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    trade_count_check = check_trade_count_gate(sim_result["trade_count"], is_years)

    return {
        **sim_result,
        "period": f"{start} to {end}",
        "data_quality": quality_report,
        "holding_pct": holding_pct,
        "trade_count_gate": trade_count_check,
        "mom_lookback_days": params["mom_lookback_days"],
        "threshold": params["threshold"],
        "vol_filter_spy_pct": params["vol_filter_spy_pct"],
        "vol_filter_tlt_pct": params["vol_filter_tlt_pct"],
    }


# ── Parameter Sensitivity Scan ─────────────────────────────────────────────────

def scan_parameters(
    start: str = "2018-01-01",
    end: str = "2022-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Scan IS Sharpe ratio across 27 parameter combinations:
      - mom_lookback_days ∈ {10, 15, 20}
      - threshold ∈ {0.0, 0.005, 0.01}
      - vol_filter_spy_pct ∈ {0.20, 0.25, 0.30}
      (vol_filter_tlt_pct held at default 0.15)

    Returns dict with results for all 27 combinations and stability meta-analysis.
    """
    lookbacks = [10, 15, 20]
    thresholds = [0.0, 0.005, 0.01]
    vol_spy_filters = [0.20, 0.25, 0.30]

    results = {}
    for lb in lookbacks:
        for thr in thresholds:
            for vsf in vol_spy_filters:
                p = {
                    **base_params,
                    "mom_lookback_days": lb,
                    "threshold": thr,
                    "vol_filter_spy_pct": vsf,
                }
                key = f"lb{lb}_thr{thr}_vsf{vsf}"
                try:
                    r = run_backtest(params=p, start=start, end=end)
                    results[key] = {
                        "sharpe": round(r["sharpe"], 4),
                        "total_return": round(r["total_return"], 4),
                        "max_drawdown": round(r["max_drawdown"], 4),
                        "trade_count": r["trade_count"],
                        "trade_count_gate": r["trade_count_gate"]["gate_pass"],
                        "cash_pct": r["holding_pct"].get("_cash_regime", 0),
                    }
                except Exception as exc:
                    results[key] = {"error": str(exc)}

    # Stability meta-analysis vs default config
    default_key = (
        f"lb{base_params['mom_lookback_days']}"
        f"_thr{base_params['threshold']}"
        f"_vsf{base_params['vol_filter_spy_pct']}"
    )
    default_sharpe = results.get(default_key, {}).get("sharpe", None)

    sharpe_nums = [
        v["sharpe"] for v in results.values()
        if isinstance(v, dict) and "sharpe" in v and isinstance(v["sharpe"], (int, float))
    ]

    meta = {
        "default_key": default_key,
        "default_sharpe": default_sharpe,
        "total_combinations": len(lookbacks) * len(thresholds) * len(vol_spy_filters),
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
        description="H18 SPY/TLT Weekly Momentum Rotation backtest."
    )
    parser.add_argument(
        "--lookback", type=int, default=15, choices=[10, 15, 20],
        help="Momentum lookback in trading days (default: 15)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.0,
        help="Dead-band threshold for neutral zone (default: 0.0)"
    )
    parser.add_argument(
        "--vol-spy", type=float, default=0.25,
        help="SPY vol filter threshold annualized (default: 0.25)"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Run full 27-combination parameter sensitivity scan"
    )
    args = parser.parse_args()

    params = {
        **PARAMETERS,
        "mom_lookback_days": args.lookback,
        "threshold": args.threshold,
        "vol_filter_spy_pct": args.vol_spy,
    }

    print(
        f"\nH18 SPY/TLT: IS backtest (2018-01-01 to 2022-12-31) "
        f"lb={args.lookback}d thr={args.threshold} vol_spy={args.vol_spy}..."
    )
    is_result = run_backtest(params=params, start="2018-01-01", end="2022-12-31")
    safe_is = {
        k: v for k, v in is_result.items()
        if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                     "_portfolio_value", "_daily_returns", "_pnl_arr")
    }
    print("IS:", safe_is)

    print(f"\nH18 SPY/TLT: OOS backtest (2023-01-01 to 2025-12-31)...")
    oos_result = run_backtest(params=params, start="2023-01-01", end="2025-12-31")
    safe_oos = {
        k: v for k, v in oos_result.items()
        if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                     "_portfolio_value", "_daily_returns", "_pnl_arr")
    }
    print("OOS:", safe_oos)

    if args.scan:
        import json
        print("\nH18 SPY/TLT: 27-combination parameter sensitivity scan (IS 2018-2022)...")
        scan_results = scan_parameters()
        print(json.dumps(scan_results, indent=2))
