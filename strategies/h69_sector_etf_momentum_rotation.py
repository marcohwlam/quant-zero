"""
Strategy: H69 Sector ETF Momentum Rotation via Trend Template
Author: Engineering Director
Date: 2026-06-15
Hypothesis: Rotate weekly among 11 SPDR sector ETFs, selecting top-3 by 63-day
            relative strength vs SPY that also pass Minervini Trend Template.
            SPY 200-DMA acts as bear-market regime gate (100% cash when below).
Asset class: US equities (sector ETFs), Track A (daily/weekly)
Parent task: QUA-279

References:
  - Moskowitz & Grinblatt (1999) "Do Industries Explain Momentum?" JF 54(4)
  - Faber (2007) "A Quantitative Approach to Tactical Asset Allocation" SSRN
  - Minervini (2013) Trade Like a Stock Market Wizard — Trend Template pp.217-231

IS window:  2006-01-01 to 2018-12-31
OOS window: 2019-01-01 to 2024-12-31

Universe: 11 SPDR Sector ETFs + SPY (regime gate + RS benchmark)
  - XLK, XLF, XLE, XLV, XLU, XLI, XLY, XLP, XLB: inception 1998-1999, full IS coverage
  - XLRE: inception Oct 2015 (NaN-eligible pre-inception; included post-Oct 2015 only)
  - XLC: inception Jun 2018 (NaN-eligible pre-inception; minimal IS contribution)

Data quality notes:
  - Survivorship bias: Zero for original 9-ETF core (all launched 1998, still active).
    XLRE/XLC: ETFs do not delist due to poor performance — zero survivorship bias.
  - Prices: auto_adjust=True (splits + dividends).
  - Data gaps: flag if >5 missing trading days per ticker.
  - Earnings exclusion: N/A — sector ETFs.
  - Delisted: N/A — all ETFs and SPY active.

Transaction cost model (canonical, per ED AGENTS.md + ruling ED-SLIP-001):
  - Sector ETFs (all): $0.005/share + 0.05% slippage + 0.1×σ×sqrt(Q/ADV) impact
    (None of the 11 sector ETFs meet the 50M ADV threshold for ultra-liquid tier)
  - Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ──────────────────────────────────────────────────────────────────

PARAMETERS = {
    "universe": [
        "XLK", "XLF", "XLE", "XLV", "XLU",
        "XLI", "XLY", "XLP", "XLB", "XLRE", "XLC",
    ],
    "regime_ticker": "SPY",
    "rs_lookback": 63,          # days — 3-month horizon, Jegadeesh/Titman intermediate
    "top_n": 3,                  # sectors to hold simultaneously
    "regime_sma_period": 200,   # Faber (2007) SPY 200-DMA regime gate
    "tt_sma_short": 50,         # Minervini Trend Template SMA periods (fixed)
    "tt_sma_mid": 150,
    "tt_sma_long": 200,
    "tt_slope_window": 20,      # trading days for 200-SMA slope check
    "init_cash": 25000,
}

TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ────────────────────────────────────────────────────────────────

def download_data(tickers: list, start: str, end: str) -> tuple:
    """
    Download OHLCV with auto_adjust=True.
    Returns: (close, open_prices, volume, high, low) — all DataFrames.
    """
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

    def _extract(field: str) -> pd.DataFrame:
        if isinstance(raw.columns, pd.MultiIndex):
            if field in raw.columns.get_level_values(0):
                df = raw[field]
                if isinstance(df, pd.Series):
                    df = df.to_frame(name=tickers[0] if len(tickers) == 1 else field)
                available = [t for t in tickers if t in df.columns]
                return df[available].copy() if available else pd.DataFrame(index=raw.index)
        if field in raw.columns:
            name = tickers[0] if len(tickers) == 1 else field
            return raw[[field]].rename(columns={field: name})
        return pd.DataFrame(index=raw.index)

    close = _extract("Close")
    open_prices = _extract("Open")
    volume = _extract("Volume")
    high = _extract("High")
    low = _extract("Low")
    return close, open_prices, volume, high, low


# ── Data Quality ────────────────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame, tickers: list) -> dict:
    """Pre-backtest data quality checklist per ED AGENTS.md."""
    report = {
        "survivorship_bias": (
            "Fixed 11-ticker SPDR Sector ETF universe + SPY. Selected a priori by hypothesis "
            "specification. Original 9 ETFs launched Dec 1998 — all active, zero survivorship bias. "
            "XLRE (Oct 2015) and XLC (Jun 2018): ETFs do not delist due to poor performance; "
            "zero survivorship bias. Missing rows pre-inception treated as NaN (not selectable)."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — sector ETFs hold diversified sector baskets; no earnings events.",
        "delisted": "N/A — all SPDR Sector ETFs and SPY are active (launched 1993–2018).",
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
            warnings.warn(f"Data gap: {ticker} has {missing} missing business days (>5 threshold).")
    report["flagged_tickers"] = flagged
    return report


# ── Signal Indicators ────────────────────────────────────────────────────────────

def _precompute_indicators(
    close: pd.DataFrame, params: dict
) -> tuple:
    """
    Precompute Trend Template pass/fail and RS scores as DataFrames.
    All indicators are backward-looking only (no look-ahead).

    Returns:
        tt_pass:      DataFrame[bool] — TT status per ticker per date
        rs_scores:    DataFrame[float] — 63-day RS vs SPY per ticker per date
        regime_active: Series[bool] — True when SPY < 200-SMA (go to cash)
    """
    universe = params["universe"]
    regime_ticker = params["regime_ticker"]
    rs_lb = params["rs_lookback"]
    sma_s = params["tt_sma_short"]
    sma_m = params["tt_sma_mid"]
    sma_l = params["tt_sma_long"]
    slope_w = params["tt_slope_window"]
    regime_sma_period = params["regime_sma_period"]

    valid = [t for t in universe if t in close.columns]

    # TT conditions computed on close prices
    sma_short = close[valid].rolling(sma_s).mean()
    sma_mid   = close[valid].rolling(sma_m).mean()
    sma_long  = close[valid].rolling(sma_l).mean()
    sma_long_slope = sma_long.diff(slope_w)

    # 52-week high/low using rolling close (252 trading days)
    high52 = close[valid].rolling(252).max()
    low52  = close[valid].rolling(252).min()

    # (a) Close > SMA50 > SMA150 > SMA200
    tt_a = (close[valid] > sma_short) & (sma_short > sma_mid) & (sma_mid > sma_long)
    # (b) SMA200 slope positive over trailing 20 days
    tt_b = sma_long_slope > 0
    # (c) Close >= 1.25 × 52-week low
    tt_c = close[valid] >= 1.25 * low52
    # (d) Close >= 0.75 × 52-week high (within 25% of high)
    tt_d = close[valid] >= 0.75 * high52

    tt_pass = tt_a & tt_b & tt_c & tt_d

    # RS score: ETF 63-day return minus SPY 63-day return
    if regime_ticker in close.columns:
        spy_ret = close[regime_ticker].pct_change(rs_lb)
        rs_scores = close[valid].pct_change(rs_lb).subtract(spy_ret, axis=0)
    else:
        rs_scores = pd.DataFrame(np.nan, index=close.index, columns=valid)

    # Regime gate: SPY below 200-SMA
    if regime_ticker in close.columns:
        spy_sma = close[regime_ticker].rolling(regime_sma_period).mean()
        regime_active = close[regime_ticker] < spy_sma
    else:
        regime_active = pd.Series(True, index=close.index)

    return tt_pass, rs_scores, regime_active


# ── Weekly Signal Generation ─────────────────────────────────────────────────────

def generate_weekly_signals(
    close: pd.DataFrame,
    params: dict,
    start: str,
    end: str,
) -> dict:
    """
    Generate weekly execution schedule for H69.

    Signal: last trading day of each week (Friday close) → no look-ahead.
    Execution: following trading day (Monday open) — fills occur at open price.

    Returns:
        exec_schedule: dict {exec_date: target_sectors_list}
        Empty list = full cash (regime active or 0 TT-qualified sectors).
    """
    universe = params["universe"]
    top_n = params["top_n"]

    tt_pass, rs_scores, regime_active = _precompute_indicators(close, params)

    # Build ordered date list for finding "next trading day" efficiently
    all_dates = list(close.index)
    date_to_next = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}

    # Signal dates = last trading day of each calendar week within [start, end]
    date_range = close.index[(close.index >= start) & (close.index <= end)]
    week_last: dict = {}
    for d in date_range:
        wk_key = (d.year, int(d.isocalendar()[1]))
        week_last[wk_key] = d

    valid = [t for t in universe if t in close.columns]
    exec_schedule: dict = {}

    for wk_key in sorted(week_last):
        sig_date = week_last[wk_key]

        # Execution date = next available trading day
        exec_date = date_to_next.get(sig_date)
        if exec_date is None:
            continue

        # Regime check at Friday close (no look-ahead)
        if sig_date in regime_active.index and bool(regime_active.loc[sig_date]):
            exec_schedule[exec_date] = []
            continue

        # Gather TT-qualified sectors with valid RS scores
        qualified = []
        for t in valid:
            if t not in tt_pass.columns or sig_date not in tt_pass.index:
                continue
            tt_val = tt_pass[t].loc[sig_date]
            if pd.isna(tt_val) or not bool(tt_val):
                continue
            if t not in rs_scores.columns:
                continue
            rs_val = rs_scores[t].loc[sig_date] if sig_date in rs_scores.index else np.nan
            if pd.isna(rs_val):
                continue
            qualified.append((t, float(rs_val)))

        # Sort by RS descending, select top N
        qualified.sort(key=lambda x: x[1], reverse=True)
        exec_schedule[exec_date] = [t for t, _ in qualified[:top_n]]

    return exec_schedule


# ── Portfolio Simulation ─────────────────────────────────────────────────────────

def simulate_portfolio(
    close: pd.DataFrame,
    open_prices: pd.DataFrame,
    volume: pd.DataFrame,
    exec_schedule: dict,
    params: dict,
    close_full: pd.DataFrame = None,
    volume_full: pd.DataFrame = None,
) -> dict:
    """
    Simulate H69 portfolio. Rebalance at Monday OPEN price; mark to market at daily CLOSE.

    Transaction cost model (canonical, sector ETFs — standard tier):
      - Slippage: 0.05% one-way
      - Commission: $0.005/share each side
      - Market impact: 0.1 × σ × sqrt(Q / ADV), k=0.1 (Almgren-Chriss)
      - Liquidity flag: Q/ADV > 0.01 (using share-count ADV from volume)
    """
    init_cash = params["init_cash"]
    k_impact = 0.1
    slippage_pct = 0.0005  # 0.05% — standard sector ETF tier

    # Use full buffered data for warm rolling sigma/ADV
    _cr = close_full if close_full is not None else close
    _vr = volume_full if volume_full is not None else volume

    all_tickers = list(params["universe"])
    sigma: dict = {}
    adv_shares: dict = {}
    for t in all_tickers:
        if t in _cr.columns:
            sigma[t] = _cr[t].pct_change().rolling(20).std()
        if t in _vr.columns:
            adv_shares[t] = _vr[t].rolling(20).mean()

    def _get_sigma(t: str, d) -> float:
        v = sigma.get(t, pd.Series()).get(d, np.nan)
        return 0.0 if pd.isna(v) else float(v)

    def _get_adv(t: str, d) -> float:
        v = adv_shares.get(t, pd.Series()).get(d, np.nan)
        return float(v) if not pd.isna(v) and v > 0 else 1e9

    trade_log: list = []
    liquidity_flags: list = []
    total_costs = 0.0

    def _sell(t: str, d, shares: float, exec_p: dict) -> float:
        nonlocal total_costs
        price = exec_p.get(t, np.nan)
        if pd.isna(price) or price <= 0 or shares <= 0:
            return 0.0
        sig_v = _get_sigma(t, d)
        adv_v = _get_adv(t, d)
        q_adv = shares / (adv_v + 1e-9)
        if q_adv > 0.01:
            liquidity_flags.append({"date": str(d.date()), "ticker": t, "side": "sell", "q_over_adv": round(q_adv, 6)})
        impact = k_impact * sig_v * np.sqrt(max(q_adv, 0))
        slip = slippage_pct + impact
        commission = shares * 0.005
        total_costs += shares * price * slip + commission
        proceeds = shares * price * (1 - slip) - commission
        trade_log.append({
            "trade_id": f"sell_{t}_{d.date()}",
            "date": str(d.date()), "ticker": t, "side": "sell",
            "shares": round(shares, 4), "price": round(price, 4),
            "slippage_pct": round(slip, 6), "commission": round(commission, 4),
            "net_proceeds": round(max(proceeds, 0.0), 4),
            "liquidity_constrained": q_adv > 0.01,
        })
        return max(proceeds, 0.0)

    def _buy(t: str, d, cash_alloc: float, exec_p: dict) -> float:
        nonlocal total_costs
        price = exec_p.get(t, np.nan)
        if pd.isna(price) or price <= 0 or cash_alloc <= 0:
            return 0.0
        sig_v = _get_sigma(t, d)
        adv_v = _get_adv(t, d)
        est_shares = cash_alloc / price
        q_adv = est_shares / (adv_v + 1e-9)
        if q_adv > 0.01:
            liquidity_flags.append({"date": str(d.date()), "ticker": t, "side": "buy", "q_over_adv": round(q_adv, 6)})
        impact = k_impact * sig_v * np.sqrt(max(q_adv, 0))
        slip = slippage_pct + impact
        effective_cost = price * (1 + slip) + 0.005
        shares = cash_alloc / effective_cost
        if pd.isna(shares) or shares <= 0:
            warnings.warn(f"BUY skipped {t} on {d.date()}: sigma={sig_v:.6f}")
            return 0.0
        commission = shares * 0.005
        total_costs += shares * price * slip + commission
        trade_log.append({
            "trade_id": f"buy_{t}_{d.date()}",
            "date": str(d.date()), "ticker": t, "side": "buy",
            "shares": round(shares, 4), "price": round(price, 4),
            "effective_cost": round(effective_cost, 4),
            "slippage_pct": round(slip, 6), "commission": round(commission, 4),
            "cash_spent": round(shares * effective_cost, 4),
            "liquidity_constrained": q_adv > 0.01,
        })
        return shares

    holdings: dict = {}
    cash = float(init_cash)
    portfolio_value = pd.Series(index=close.index, dtype=float)

    for i, date in enumerate(close.index):
        if i == 0:
            portfolio_value.iloc[0] = cash
            continue

        if date in exec_schedule:
            target_sectors = exec_schedule[date]
            target_set = set(target_sectors)
            current_set = set(holdings.keys())

            # Resolve execution prices: Monday open, fall back to prior close
            exec_p: dict = {}
            for t in current_set | target_set:
                if t in open_prices.columns and date in open_prices.index:
                    p = open_prices[t].loc[date]
                    if not pd.isna(p) and p > 0:
                        exec_p[t] = float(p)
                if t not in exec_p and t in close.columns and i > 0:
                    p = close[t].iloc[i - 1]
                    if not pd.isna(p) and p > 0:
                        exec_p[t] = float(p)

            # Sell exits first
            for t in list(current_set - target_set):
                shares = holdings.pop(t, 0.0)
                if shares > 0:
                    cash += _sell(t, date, shares, exec_p)

            # Buy new entrants
            new_sectors = [t for t in target_sectors if t not in current_set]
            if new_sectors:
                cash_per_new = cash / len(new_sectors)
                for t in new_sectors:
                    shares_bought = _buy(t, date, cash_per_new, exec_p)
                    if shares_bought > 0:
                        holdings[t] = holdings.get(t, 0.0) + shares_bought
                        cash -= cash_per_new
                cash = max(cash, 0.0)

        # Mark to market at close
        nav = cash
        for t, shares in holdings.items():
            if t in close.columns:
                p = close[t].iloc[i]
                if not pd.isna(p):
                    nav += shares * p
        portfolio_value.iloc[i] = nav

    portfolio_value = portfolio_value.ffill().fillna(init_cash)

    # Metrics
    trade_pnl = _compute_round_trip_pnl(trade_log)
    daily_ret = portfolio_value.pct_change().fillna(0).values
    sharpe = float(daily_ret.mean() / (daily_ret.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
    cum = np.cumprod(1 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(portfolio_value.iloc[-1] / portfolio_value.iloc[0] - 1)
    n_years = len(portfolio_value) / TRADING_DAYS_PER_YEAR
    cagr = float((portfolio_value.iloc[-1] / portfolio_value.iloc[0]) ** (1 / max(n_years, 0.001)) - 1)

    if trade_pnl:
        pnl_arr = np.array([t["pnl"] for t in trade_pnl])
        cb_arr = np.array([t["cost_basis"] for t in trade_pnl])
        ppt_bps = float(np.mean(pnl_arr / (cb_arr + 1e-9))) * 10000
        win_rate = float(np.mean(pnl_arr > 0))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        profit_factor = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0 else float("inf")
        )
        gross_pnl = total_return * init_cash + total_costs
        cpr = total_costs / max(gross_pnl, 1.0) if gross_pnl > 0 else 1.0
    else:
        pnl_arr = np.array([])
        cb_arr = np.array([])
        ppt_bps = win_rate = profit_factor = cpr = 0.0

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "ppt_bps": ppt_bps,
        "cpr": cpr,
        "total_return": total_return,
        "cagr": cagr,
        "trade_count": len(trade_pnl),
        "trade_log": trade_log,
        "trade_pnl": trade_pnl,
        "liquidity_flags": liquidity_flags,
        "total_costs": total_costs,
        "_portfolio_value": portfolio_value,
        "_daily_returns": daily_ret,
        "_pnl_arr": pnl_arr,
    }


def _compute_round_trip_pnl(trade_log: list) -> list:
    """FIFO round-trip PnL matching. Returns list of closed trade records."""
    open_pos: dict = {}
    result = []
    for entry in trade_log:
        t = entry["ticker"]
        if entry["side"] == "buy":
            open_pos.setdefault(t, []).append({
                "buy_date": entry["date"],
                "cash_spent": entry.get("cash_spent", 0),
                "shares": entry.get("shares", 0),
            })
        elif entry["side"] == "sell" and t in open_pos and open_pos[t]:
            op = open_pos[t].pop(0)
            if not open_pos[t]:
                del open_pos[t]
            cb = op["cash_spent"]
            pr = entry.get("net_proceeds", 0)
            pnl = pr - cb
            result.append({
                "ticker": t,
                "buy_date": op["buy_date"],
                "sell_date": entry["date"],
                "cost_basis": round(cb, 4),
                "net_proceeds": round(pr, 4),
                "pnl": round(pnl, 4),
                "return_pct": round(pnl / cb if cb > 0 else 0.0, 6),
            })
    return result


# ── Main Backtest Entry ──────────────────────────────────────────────────────────

def run_backtest(
    params: dict = PARAMETERS,
    start: str = "2006-01-01",
    end: str = "2018-12-31",
) -> dict:
    """
    Full H69 backtest for a given period.
    Downloads OHLCV with pre-window buffer for warm-up, generates weekly signals,
    simulates portfolio with Monday-open execution, returns standardized metrics dict.
    """
    universe = list(params["universe"])
    regime_ticker = params["regime_ticker"]
    all_tickers = universe + ([regime_ticker] if regime_ticker not in universe else [])

    # Buffer: 200-SMA + 52-week window + RS lookback + 30 days
    buffer_days = params["regime_sma_period"] + 252 + params["rs_lookback"] + 30
    buf_start = str(
        (pd.Timestamp(start) - pd.tseries.offsets.BDay(buffer_days)).date()
    )

    close, open_prices, volume, high, low = download_data(all_tickers, buf_start, end)
    quality_report = check_data_quality(close, all_tickers)

    close = close.dropna(axis=1, how="all")
    if regime_ticker not in close.columns:
        raise ValueError(f"Regime ticker {regime_ticker} missing from downloaded data.")

    min_required = params["regime_sma_period"] + 252 + params["rs_lookback"] + 10
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} trading days, got {len(close)}."
        )

    exec_schedule = generate_weekly_signals(close, params, start, end)
    if not exec_schedule:
        raise ValueError(f"No execution signals generated for {start} to {end}.")

    close_win = close.loc[start:end]
    open_win = open_prices.reindex(close_win.index)
    open_win = open_win.ffill()
    vol_win = volume.reindex(close_win.index).fillna(0)

    sim = simulate_portfolio(
        close_win, open_win, vol_win,
        exec_schedule, params,
        close_full=close, volume_full=volume,
    )

    # Sector holding breakdown
    sector_counts: dict = {}
    cash_weeks = 0
    total_execs = len(exec_schedule)
    for secs in exec_schedule.values():
        if not secs:
            cash_weeks += 1
        else:
            for s in secs:
                sector_counts[s] = sector_counts.get(s, 0) + 1
    holding_pct = {k: round(v / max(total_execs, 1), 4) for k, v in sector_counts.items()}
    holding_pct["_cash"] = round(cash_weeks / max(total_execs, 1), 4)

    return {
        **sim,
        "period": f"{start} to {end}",
        "data_quality": quality_report,
        "holding_pct": holding_pct,
        "exec_weeks": total_execs,
        "cash_weeks": cash_weeks,
        "rs_lookback": params["rs_lookback"],
        "top_n": params["top_n"],
        "regime_sma_period": params["regime_sma_period"],
    }


# ── Entry Point ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    print("H69 IS backtest (2006-01-01 to 2018-12-31)...")
    r = run_backtest()
    safe = {k: v for k, v in r.items()
            if k not in ("data_quality", "trade_log", "trade_pnl", "liquidity_flags",
                         "_portfolio_value", "_daily_returns", "_pnl_arr")}
    print(json.dumps(safe, indent=2, default=str))
