"""
Strategy: H27 Post-Earnings Announcement Drift (PEAD)
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: Stocks with earnings gap-ups ≥3% (open vs prior close) exhibit positive
            price drift over the following 20 trading days (PEAD effect), particularly
            in bull market regimes (SPY above 200-day SMA).
Asset class: equities
Parent task: QUA-236
References: Ball & Brown (1968); Foster, Olsen & Shevlin (1984); Chan — Algorithmic Trading
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ─────────────────────────────────────────────────────────

PARAMETERS = {
    "gap_threshold": 0.03,       # 3% gap-up required at open vs prior close
    "hold_days": 20,             # calendar of trading days to hold post-entry
    "max_positions": 5,          # max concurrent positions (slots)
    "ma_filter_period": 200,     # SPY regime filter SMA period
    "min_market_cap_b": 10.0,    # minimum market cap in $B (current-day filter)
    "init_cash": 25000,
}

# ── Transaction Cost Constants ─────────────────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005     # $0.005/share
SLIPPAGE_PCT = 0.0005            # 0.05%
MARKET_IMPACT_K = 0.1            # square-root impact coefficient (Johnson — DMA)
SIGMA_WINDOW = 20                # rolling window for volatility estimate
ADV_WINDOW = 20                  # rolling window for average daily volume
TRADING_DAYS_PER_YEAR = 252


# ── Universe Builder ────────────────────────────────────────────────────────────

def get_sp500_universe(min_market_cap_b: float = 10.0, top_n: int = 200) -> list:
    """
    Fetch current S&P 500 tickers from Wikipedia and filter to top N by market cap.

    SURVIVORSHIP BIAS CAVEAT:
    This universe reflects current-day S&P 500 membership and market cap rankings.
    It does NOT reflect point-in-time index membership. Stocks that were delisted,
    merged, or removed from the index during the backtest period are excluded,
    biasing results upward. This is a known limitation of the yfinance data source.

    Returns list of ticker symbols (up to top_n by market cap, ≥ min_market_cap_b).
    """
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", header=0
        )
        sp500_df = tables[0]
        # Wikipedia uses '.' for BRK.B etc.; yfinance expects '-'
        tickers = sp500_df["Symbol"].str.replace(".", "-", regex=False).tolist()
    except Exception as exc:
        warnings.warn(
            f"Failed to fetch S&P 500 list from Wikipedia ({exc}). Using fallback large-cap list."
        )
        tickers = [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSLA",
            "JPM", "V", "UNH", "XOM", "JNJ", "WMT", "MA", "PG", "COST", "HD",
            "BAC", "CVX", "LLY", "ABBV", "KO", "MRK", "PEP", "AVGO", "ADBE",
            "CRM", "TMO", "MCD", "ACN", "ABT", "AMD", "NFLX", "DIS", "CSCO",
            "TXN", "HON", "INTC", "AMGN", "IBM", "NOW", "INTU", "QCOM", "LOW",
        ]

    # Rank by market cap and keep top N above the minimum threshold
    market_caps = {}
    for sym in tickers:
        try:
            info = yf.Ticker(sym).info
            cap = info.get("marketCap", 0) or 0
            if cap >= min_market_cap_b * 1e9:
                market_caps[sym] = cap
        except Exception:
            continue  # silently skip if info fetch fails

    sorted_tickers = sorted(market_caps, key=market_caps.get, reverse=True)
    universe = sorted_tickers[:top_n]
    print(
        f"Universe built: {len(universe)} tickers "
        f"(top {top_n} by market cap, ≥${min_market_cap_b}B)"
    )
    return universe


# ── Earnings Date Loader ────────────────────────────────────────────────────────

def load_earnings_dates(tickers: list) -> tuple:
    """
    Load historical earnings announcement dates via yfinance for each ticker.

    Uses `get_earnings_dates(limit=60)` which requires `lxml` to be installed.
    This covers ~15 years of data for large-caps (vs the old `earnings_dates`
    property which only returned ~12 quarters and required lxml without a clear error).

    Run environment note: execute with a venv that has lxml installed, e.g.:
        python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    Or use the pre-built venv at /tmp/test_lxml_venv (if available on the runner).

    DATA LIMITATION: yfinance `get_earnings_dates(limit=60)` typically covers
    ~50–60 rows (quarters) going back to ~2010–2012 for large-caps.
    Coverage for the 2007–2021 in-sample period may be incomplete for tickers
    without long listing histories.

    Returns:
        earnings_map: dict mapping ticker → set of pd.Timestamp (normalized, tz-naive)
        coverage_rate: fraction of tickers with at least one valid earnings date
    """
    earnings_map = {}
    no_data_count = 0

    for sym in tickers:
        try:
            ed = yf.Ticker(sym).get_earnings_dates(limit=60)
            if ed is None or len(ed) < 4:
                # Skip tickers with insufficient earnings history (< 4 quarters)
                no_data_count += 1
                warnings.warn(f"{sym}: insufficient earnings_dates data (<4 rows) — skipping")
                continue
            # Index is tz-aware; normalize to midnight and strip tz for comparison
            dates = set(
                pd.DatetimeIndex(ed.index).normalize().tz_localize(None)
            )
            earnings_map[sym] = dates
        except Exception as exc:
            no_data_count += 1
            warnings.warn(f"{sym}: get_earnings_dates fetch failed ({exc}) — skipping")

    coverage_rate = len(earnings_map) / max(len(tickers), 1)
    print(
        f"Earnings coverage: {len(earnings_map)}/{len(tickers)} tickers "
        f"({coverage_rate:.1%})"
    )
    return earnings_map, coverage_rate


# ── Data Loader ────────────────────────────────────────────────────────────────

def download_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Download OHLCV data using yfinance with auto_adjust=True.
    Raises ValueError for missing columns or insufficient bars.
    Warns if > 5 trading days have missing Close data.
    """
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Missing columns for {ticker}: {missing}")

    if raw.empty or len(raw) < 50:
        raise ValueError(f"Insufficient data for {ticker}: {len(raw)} bars")

    na_count = raw["Close"].isna().sum()
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing trading days detected")

    return raw


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def compute_transaction_cost(
    price: float,
    shares: int,
    close_series: pd.Series,
    vol_series: pd.Series,
    idx: int,
) -> tuple:
    """
    Canonical equities transaction cost model (Engineering Director spec).

    Components:
    - Fixed: $0.005/share
    - Slippage: 0.05% of notional
    - Market impact: k × σ × sqrt(Q / ADV) × notional  (square-root impact model)
      where σ = 20-day rolling daily return vol, ADV = 20-day avg daily volume (shares)

    Returns (total_cost_dollars, liquidity_constrained_bool).
    Flags orders where Q/ADV > 1% as liquidity-constrained (per Engineering Director spec).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    # Fall back to conservative estimates when rolling data is unavailable
    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1e6

    # Square-root market impact (Johnson — Algorithmic Trading & DMA)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liquidity_constrained = bool(shares / adv > 0.01)

    if liquidity_constrained:
        warnings.warn(
            f"Liquidity-constrained order at idx={idx}: "
            f"{shares} shares ({shares / adv:.2%} of ADV)"
        )

    total_cost = fixed + slippage + impact
    return total_cost, liquidity_constrained


# ── Main Backtest Entry Point ───────────────────────────────────────────────────

def run_backtest(params: dict, start: str, end: str) -> dict:
    """
    Run H27 PEAD strategy backtest over [start, end].

    Algorithm (no look-ahead bias):
    1. Build top-200 S&P 500 universe by current-day market cap.
    2. Load earnings dates for all tickers via yfinance.
    3. Download OHLCV for all tickers + SPY over [warmup_start, end].
    4. For each trading day t in [start, end]:
       a. Exit maturing positions: if hold_days reached, sell at Close_t.
       b. Check SPY regime: Close_t > SMA200_t (using only past data).
       c. If regime is up and slots are available:
          - Scan universe for earnings gap-ups: (Open_t - Close_{t-1}) / Close_{t-1} >= gap_threshold
          - Gap must also hold through close: Close_t > Close_{t-1}
          - Enter at Close_t with equal-weight allocation (init_cash / max_positions)
    5. Force-close all open positions at end of data.
    6. Compute performance metrics on equity curve.

    DATA QUALITY FLAGS:
    - Survivorship bias: current-day universe (see get_sp500_universe docstring)
    - Earnings data: yfinance typically covers last ~12 quarters only
    - Price adjustments: auto_adjust=True applied

    Returns standardised results dict compatible with backtest runner.
    """
    if params is None:
        params = PARAMETERS.copy()

    gap_threshold = params["gap_threshold"]
    hold_days_param = params["hold_days"]
    max_positions = params["max_positions"]
    ma_period = params["ma_filter_period"]
    init_cash = params["init_cash"]

    # ── Build universe ─────────────────────────────────────────────────────────
    print("Building S&P 500 universe...")
    universe = get_sp500_universe(
        min_market_cap_b=params["min_market_cap_b"], top_n=200
    )

    # ── Load earnings dates ────────────────────────────────────────────────────
    print("Loading earnings dates...")
    earnings_map, coverage_rate = load_earnings_dates(universe)

    # ── Download SPY + compute regime filter ───────────────────────────────────
    # Warmup: extra days so SMA(200) is fully initialised at backtest start
    warmup_days = ma_period + 30
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=int(warmup_days * 1.5))
    ).strftime("%Y-%m-%d")

    print(f"Downloading SPY data ({warmup_start} to {end})...")
    spy_raw = download_data("SPY", warmup_start, end)
    spy_raw["sma200"] = spy_raw["Close"].rolling(ma_period).mean()
    spy_raw["regime_up"] = spy_raw["Close"] > spy_raw["sma200"]

    # Restrict trading calendar to requested backtest window
    spy_bt = spy_raw.loc[spy_raw.index >= pd.Timestamp(start)]
    trading_days = spy_bt.index

    # ── Download price data for universe ──────────────────────────────────────
    print(f"Downloading price data for {len(universe)} tickers...")
    price_data = {}
    gap_flags = []
    for sym in universe:
        try:
            df = download_data(sym, warmup_start, end)
            na_count = int(df["Close"].isna().sum())
            if na_count > 5:
                gap_flags.append(sym)
            price_data[sym] = df
        except Exception as exc:
            warnings.warn(f"{sym}: download failed — {exc}")

    print(f"Loaded price data for {len(price_data)}/{len(universe)} tickers")

    # ── Simulation loop ────────────────────────────────────────────────────────
    capital = float(init_cash)
    equity_curve = pd.Series(np.nan, index=trading_days, dtype=float)

    # open_positions: list of active trade dicts
    open_positions: list = []
    trade_log: list = []

    # Fixed allocation per slot — equal weight 20% of initial capital
    alloc_per_slot = init_cash / max_positions

    for t_idx, t_date in enumerate(trading_days):
        t_ts = pd.Timestamp(t_date).normalize()  # tz-naive midnight for date comparison

        # ── Step 1: Exit maturing positions ───────────────────────────────────
        still_open = []
        for pos in open_positions:
            pos["hold_days"] += 1
            sym = pos["sym"]
            df = price_data.get(sym)

            if df is None or t_date not in df.index:
                still_open.append(pos)
                continue

            t_pos_idx = df.index.get_loc(t_date)
            close_t = float(df["Close"].iloc[t_pos_idx])

            if pos["hold_days"] >= hold_days_param:
                # TIME EXIT: sell at close of T + hold_days
                if close_t <= 0 or pos["shares"] <= 0:
                    still_open.append(pos)
                    continue

                exit_cost, exit_liq = compute_transaction_cost(
                    close_t, pos["shares"],
                    df["Close"], df["Volume"], t_pos_idx,
                )
                eff_exit = close_t - exit_cost / pos["shares"]
                gross_pnl = (eff_exit - pos["entry_price"]) * pos["shares"]
                capital += eff_exit * pos["shares"]

                trade_log.append({
                    "sym": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": t_date.date(),
                    "entry_price": round(pos["entry_price"], 4),
                    "exit_price": round(eff_exit, 4),
                    "shares": pos["shares"],
                    "pnl": round(gross_pnl, 2),
                    "cost": round(pos["entry_cost"] + exit_cost, 4),
                    "hold_days": pos["hold_days"],
                    "liquidity_constrained": pos["liquidity_constrained"] or exit_liq,
                    "exit_reason": "TIME_EXIT",
                })
                # slot freed — do not append to still_open
            else:
                still_open.append(pos)

        open_positions = still_open

        # ── Step 2: Scan for new entries ──────────────────────────────────────
        regime_today = bool(spy_bt["regime_up"].loc[t_date]) if t_date in spy_bt.index else False

        if regime_today and len(open_positions) < max_positions:
            for sym in earnings_map:
                if len(open_positions) >= max_positions:
                    break

                # Check if today is an earnings announcement date for this ticker
                if t_ts not in earnings_map[sym]:
                    continue

                df = price_data.get(sym)
                if df is None or t_date not in df.index:
                    continue

                t_pos_idx = df.index.get_loc(t_date)
                if t_pos_idx < 1:
                    continue  # Need prior day close for gap calculation

                open_t = float(df["Open"].iloc[t_pos_idx])
                close_tm1 = float(df["Close"].iloc[t_pos_idx - 1])
                close_t = float(df["Close"].iloc[t_pos_idx])

                if close_tm1 <= 0 or open_t <= 0 or close_t <= 0:
                    continue

                # Gap-up check: open_t must be ≥ gap_threshold above prior close
                gap = (open_t - close_tm1) / close_tm1
                if gap < gap_threshold:
                    continue

                # Gap must hold through close (close_t > close_{t-1})
                if close_t <= close_tm1:
                    continue

                # Skip if we already hold this ticker
                if any(p["sym"] == sym for p in open_positions):
                    continue

                # Must have enough capital to open a position
                if capital < 1.0:
                    break

                # Equal-weight: init_cash / max_positions, capped by available cash
                alloc = min(alloc_per_slot, capital)
                entry_p = close_t
                shares = int(alloc / entry_p)
                if shares <= 0:
                    continue

                entry_cost, liq_flag = compute_transaction_cost(
                    entry_p, shares,
                    df["Close"], df["Volume"], t_pos_idx,
                )
                eff_entry = entry_p + entry_cost / shares
                capital -= eff_entry * shares

                open_positions.append({
                    "sym": sym,
                    "entry_date": t_date.date(),
                    "entry_price": eff_entry,
                    "shares": shares,
                    "entry_cost": entry_cost,
                    "hold_days": 0,
                    "liquidity_constrained": liq_flag,
                })

        # ── Step 3: Mark-to-market equity snapshot ────────────────────────────
        mtm = capital
        for pos in open_positions:
            df = price_data.get(pos["sym"])
            if df is not None and t_date in df.index:
                mtm += pos["shares"] * float(df["Close"].loc[t_date])
        equity_curve.iloc[t_idx] = mtm

    # ── Force-close remaining positions at end of backtest ────────────────────
    last_date = trading_days[-1]
    for pos in open_positions:
        sym = pos["sym"]
        df = price_data.get(sym)
        if df is None or last_date not in df.index:
            continue

        t_pos_idx = df.index.get_loc(last_date)
        exit_p = float(df["Close"].iloc[t_pos_idx])
        if exit_p <= 0:
            continue

        exit_cost, exit_liq = compute_transaction_cost(
            exit_p, pos["shares"],
            df["Close"], df["Volume"], t_pos_idx,
        )
        eff_exit = exit_p - exit_cost / pos["shares"]
        gross_pnl = (eff_exit - pos["entry_price"]) * pos["shares"]
        capital += eff_exit * pos["shares"]

        trade_log.append({
            "sym": sym,
            "entry_date": pos["entry_date"],
            "exit_date": last_date.date(),
            "entry_price": round(pos["entry_price"], 4),
            "exit_price": round(eff_exit, 4),
            "shares": pos["shares"],
            "pnl": round(gross_pnl, 2),
            "cost": round(pos["entry_cost"] + exit_cost, 4),
            "hold_days": pos["hold_days"],
            "liquidity_constrained": pos["liquidity_constrained"] or exit_liq,
            "exit_reason": "END_OF_DATA",
        })

    # ── Build output ──────────────────────────────────────────────────────────
    equity_curve = equity_curve.ffill().fillna(float(init_cash))
    daily_returns = equity_curve.pct_change().fillna(0.0)

    col_names = [
        "sym", "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "cost", "hold_days", "liquidity_constrained", "exit_reason",
    ]
    trades_df = (
        pd.DataFrame(trade_log) if trade_log
        else pd.DataFrame(columns=col_names)
    )

    # ── Performance Metrics ────────────────────────────────────────────────────
    n_trades = len(trades_df)
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    trades_per_year = round(n_trades / max(years, 1e-3), 1)

    ret_arr = daily_returns.values
    sharpe = 0.0
    if ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + ret_arr)
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    win_rate = 0.0
    profit_factor = 0.0
    if n_trades > 0:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        gross_wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        gross_losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = round(float(gross_wins / max(gross_losses, 1e-8)), 4)

    data_quality = {
        "survivorship_bias_flag": (
            "WARNING: Universe is current-day top 200 S&P 500 by market cap. "
            "Not point-in-time — historical delisted/demoted tickers excluded. "
            "Results are biased upward by survivorship."
        ),
        "price_adjusted": True,   # yfinance auto_adjust=True
        "gap_flags": gap_flags,   # tickers with > 5 missing trading days
        "earnings_exclusion": "N/A — strategy is earnings-driven, not excluding earnings",
        "delisted_tickers": (
            "yfinance top-200 may miss historical S&P 500 members — survivorship caveat applies"
        ),
        "earnings_coverage_rate": coverage_rate,
        "earnings_data_caveat": (
            "yfinance get_earnings_dates(limit=60) covers ~50-60 quarters (~15 years) for large-caps. "
            "Requires lxml>=5.0. Coverage for pre-2012 events may be incomplete."
        ),
    }

    print(
        f"\nH27 PEAD Backtest Summary ({start} to {end}):\n"
        f"  Trades total: {n_trades} | Trades/yr: {trades_per_year}\n"
        f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}\n"
        f"  Win rate: {win_rate:.2%} | Profit Factor: {profit_factor}\n"
        f"  Earnings coverage: {coverage_rate:.1%}\n"
        f"  Data quality flags: {len(gap_flags)} tickers with >5 missing days\n"
        f"  CAVEAT: survivorship bias present (current-day universe)"
    )

    return {
        "trades": trades_df.to_dict("records"),
        "equity_curve": equity_curve.tolist(),
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "earnings_coverage_rate": coverage_rate,
        # Additional fields for orchestrator / Backtest Runner compatibility
        "returns": daily_returns,
        "equity": equity_curve,
        "params": params,
        "data_quality": data_quality,
        "total_return": total_return,
    }


def run_strategy(ticker: str, start: str, end: str, params: dict = None) -> dict:
    """
    Thin wrapper for orchestrator compatibility.
    `ticker` is unused — PEAD strategy operates on the full S&P 500 universe.
    """
    return run_backtest(params=params or PARAMETERS.copy(), start=start, end=end)


if __name__ == "__main__":
    result = run_backtest(PARAMETERS.copy(), "2021-01-01", "2023-12-31")
    trades = result.get("trades", [])
    print("\nSample trades (first 5):")
    for t in trades[:5]:
        print(t)
