"""
Strategy: H86v2 Post-Earnings Gap Continuation v2
Author: Strategy Coder Agent (Engineering Director commissioned)
Date: 2026-06-24
Hypothesis: H86 targeted fixes on a proven signal (IS Sharpe 1.82, perm p=0.000).
  Fix 1: Full S&P 500 universe via local static CSV (eliminates H86 Wikipedia 403 → 45 tickers)
  Fix 2: 150-SMA regime gate replaces 200-SMA (recovers WF4 zero-trade window)
  Fix 3: Narrow parameter grid removes known-weak combos (gap_pct_min=0.02, gap_vol_ratio_min=1.0)
Asset class: US large-cap equities (S&P 500)
Issue: QUA-398 / Source: QUA-397
References: Ball & Brown (1968); Bernard & Thomas (1989, 1990); Foster, Olsen & Shevlin (1984);
            Krinsky & Lee (1996); Livnat & Mendenhall (2006); Chordia & Shivakumar (2006)
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path

# ── Parameters ───────────────────────────────────────────────────────────────

PARAMETERS = {
    "gap_pct_min": 0.03,            # sweep: [0.03, 0.05]       (0.02 removed — weak combos only)
    "gap_vol_ratio_min": 1.5,       # sweep: [1.5, 2.0]          (1.0 removed — weak combos only)
    "entry_delay_days": 2,          # sweep: [1, 2, 3]
    "hold_days": 20,                # sweep: [15, 20, 25]        (changed from [20,30,40])
    "stop_loss_pct": 0.07,          # sweep: [0.05, 0.07, 0.10]
    "spy_sma_period": 150,          # FIXED — 150-SMA (Fix 2: replaces 200-SMA; WF4 recovery)
    "max_positions": 10,            # fixed
    "max_position_pct": 0.05,       # fixed
    "init_cash": 25000,
    "start": "2023-07-01",
    "end": "2026-06-24",
}

PARAM_GRID = {
    "gap_pct_min":       [0.03, 0.05],
    "gap_vol_ratio_min": [1.5, 2.0],
    "entry_delay_days":  [1, 2, 3],
    "hold_days":         [15, 20, 25],
    "stop_loss_pct":     [0.05, 0.07, 0.10],
}
# Total: 2 × 2 × 3 × 3 × 3 = 108 combos (vs 243 in H86)

FIXED_COST_PER_SHARE = 0.005        # $0.005/share fixed
SLIPPAGE_PCT = 0.0005               # 0.05% one-way (ED-SLIP-001; ultra-liquid 0.005% N/A for stocks)
MARKET_IMPACT_K = 0.1               # Almgren-Chriss square-root model
SIGMA_WINDOW = 20                   # 20-day rolling vol
ADV_WINDOW = 20                     # 20-day average daily volume
TRADING_DAYS_PER_YEAR = 252
IS_END = "2025-03-31"               # in-sample cutoff for Gate 1 checks

_HERE = Path(__file__).parent
_REPO = _HERE.parent
SP500_CSV = _REPO / "data" / "sp500_constituents_2026.csv"


# ── Universe ──────────────────────────────────────────────────────────────────

def get_sp500_universe() -> list:
    """
    Load S&P 500 tickers from local static CSV (Fix 1 of 3).

    Replaces H86's Wikipedia scrape which returned HTTP 403 at run-time, leaving
    only the 45-ticker fallback and producing a data-artifact trade count of 26.

    SURVIVORSHIP BIAS: Current-day S&P 500 members only. Delisted/demoted stocks
    absent → mild upward bias. Large-cap names rarely exit via bankruptcy.
    MODERATE RISK, LOW MAGNITUDE per data quality checklist.
    """
    if not SP500_CSV.exists():
        raise FileNotFoundError(
            f"S&P 500 constituent file not found: {SP500_CSV}. "
            "Engineering Director must provide data/sp500_constituents_2026.csv."
        )
    df = pd.read_csv(SP500_CSV)
    tickers = df["ticker"].str.strip().tolist()
    if len(tickers) < 450:
        raise ValueError(
            f"Universe too small: {len(tickers)} tickers (minimum 450 required). "
            f"Check {SP500_CSV.name} for completeness."
        )
    print(f"Universe: {len(tickers)} tickers (local static CSV — {SP500_CSV.name})")
    return tickers


# ── Earnings Dates ────────────────────────────────────────────────────────────

def get_earnings_dates(ticker: str) -> pd.DatetimeIndex:
    """Fetch past earnings announcement dates for ticker via yfinance."""
    try:
        df = yf.Ticker(ticker).get_earnings_dates(limit=60)
        if df is None or df.empty:
            return pd.DatetimeIndex([])
        dates = df.index.tz_localize(None) if df.index.tz is not None else df.index
        past = dates[dates <= pd.Timestamp.today()].normalize()
        return past
    except Exception:
        return pd.DatetimeIndex([])


def load_earnings_dates(tickers: list) -> tuple:
    """
    Load past earnings dates for all tickers.
    Returns (earnings_map: dict[ticker -> set[Timestamp]], coverage_rate: float).
    Skips tickers with < 2 past dates (insufficient coverage for backtest window).

    yfinance get_earnings_dates(limit=60) covers ~3 years from query date (~2023-06).
    IS window starts 2023-07-01 per PF-3 to avoid coverage gap.
    """
    earnings_map = {}
    skipped = 0
    for i, sym in enumerate(tickers):
        if i % 50 == 0:
            print(f"  Earnings dates: {i}/{len(tickers)} tickers processed...")
        dates = get_earnings_dates(sym)
        if len(dates) < 2:
            skipped += 1
            continue
        earnings_map[sym] = set(dates)

    coverage_rate = len(earnings_map) / max(len(tickers), 1)
    print(
        f"Earnings coverage: {len(earnings_map)}/{len(tickers)} ({coverage_rate:.1%})"
        f" | skipped (< 2 dates): {skipped}"
    )
    return earnings_map, coverage_rate


# ── Data Download ─────────────────────────────────────────────────────────────

def download_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV (auto_adjust=True). Raises on missing cols or < 50 bars."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Missing columns for {ticker}: {missing}")
    if raw.empty or len(raw) < 50:
        raise ValueError(f"Insufficient data for {ticker}: {len(raw)} bars")
    na_count = int(raw["Close"].isna().sum())
    if na_count > 5:
        warnings.warn(f"{ticker}: {na_count} missing trading days")
    return raw


# ── Transaction Cost ──────────────────────────────────────────────────────────

def compute_transaction_cost(
    price: float, shares: int, close_series: pd.Series, vol_series: pd.Series, idx: int
) -> tuple:
    """
    Equities cost model (ED-SLIP-001): $0.005/share + 0.05% slippage + sqrt market impact.
    Returns (total_cost_dollars, liquidity_constrained_bool).
    Flags Q/ADV > 1% as liquidity-constrained.
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]

    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1e6

    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liquidity_constrained = bool(shares / adv > 0.01)
    if liquidity_constrained:
        warnings.warn(f"Liquidity-constrained: {shares} shares ({shares / adv:.2%} of ADV)")

    return fixed + slippage + impact, liquidity_constrained


# ── Data Loading (cache once, reuse for all sweep combos) ────────────────────

def load_universe_data(start: str, end: str, sma_period: int = 150) -> dict:
    """
    Pre-load all data for H86v2 backtests.
    Call once per (start, end) window; pass the result to simulate_strategy()
    for all parameter combos — avoids re-downloading 500 tickers per combo.

    Returns dict with keys:
      universe, earnings_map, coverage_rate, price_data,
      spy_full (with sma + regime_up), warmup_start, gap_flags
    """
    universe = get_sp500_universe()
    print(f"Loading earnings dates for {len(universe)} tickers...")
    earnings_map, coverage_rate = load_earnings_dates(universe)

    warmup_days = sma_period + 30
    warmup_start = (
        pd.Timestamp(start) - pd.DateOffset(days=int(warmup_days * 1.5))
    ).strftime("%Y-%m-%d")

    print(f"Downloading SPY ({warmup_start} to {end}) with {sma_period}-SMA...")
    spy_raw = download_data("SPY", warmup_start, end)
    spy_raw["sma"] = spy_raw["Close"].rolling(sma_period).mean()
    spy_raw["regime_up"] = spy_raw["Close"] > spy_raw["sma"]

    print(f"Downloading price data for {len(earnings_map)} tickers with earnings coverage...")
    price_data = {}
    gap_flags = []
    for i, sym in enumerate(earnings_map):
        if i % 100 == 0:
            print(f"  Price data: {i}/{len(earnings_map)} tickers...")
        try:
            df = download_data(sym, warmup_start, end)
            if int(df["Close"].isna().sum()) > 5:
                gap_flags.append(sym)
            price_data[sym] = df
        except Exception as exc:
            warnings.warn(f"{sym}: download failed — {exc}")

    print(f"Price data loaded: {len(price_data)}/{len(earnings_map)} tickers")

    return {
        "universe": universe,
        "earnings_map": earnings_map,
        "coverage_rate": coverage_rate,
        "price_data": price_data,
        "spy_full": spy_raw,
        "warmup_start": warmup_start,
        "gap_flags": gap_flags,
        "sma_period": sma_period,
    }


# ── Simulation ────────────────────────────────────────────────────────────────

def simulate_strategy(params: dict, cached: dict, start: str, end: str) -> dict:
    """
    Run H86v2 Post-Earnings Gap Continuation on pre-loaded data (no downloads).

    Simulation order per trading day t:
      1. Open-priced exits: stop-loss / regime exits flagged at prev-day close → exit at open_t
      2. Close-priced entries: pending entries execute at close_t (regime up, slots available)
      3. Signal scan: earnings gap-up detected → queue entry at T + entry_delay_days
      4. Time-based exits: positions reaching hold_days → exit at close_t
      5. Flag open positions for next-open exit (stop-loss or regime check on today's close)
      6. Mark-to-market at close

    No look-ahead: gap = T+0 open vs T-1 close + 20d vol through T-1.
    Entry at T+entry_delay close. Stop/regime: same-day close flag, next-day open exit.
    """
    gap_pct_min = params["gap_pct_min"]
    gap_vol_ratio_min = params["gap_vol_ratio_min"]
    entry_delay = params["entry_delay_days"]
    hold_days_param = params["hold_days"]
    stop_loss_pct = params["stop_loss_pct"]
    max_positions = params["max_positions"]
    max_pos_pct = params["max_position_pct"]
    init_cash = params["init_cash"]

    earnings_map = cached["earnings_map"]
    price_data = cached["price_data"]
    spy_full = cached["spy_full"]
    coverage_rate = cached["coverage_rate"]
    gap_flags = cached["gap_flags"]

    spy_bt = spy_full.loc[spy_full.index >= pd.Timestamp(start)].copy()
    spy_bt = spy_bt.loc[spy_bt.index <= pd.Timestamp(end)].copy()
    trading_days = spy_bt.index

    capital = float(init_cash)
    equity_curve = pd.Series(np.nan, index=trading_days, dtype=float)
    pending_entries: list = []
    open_positions: list = []
    trade_log: list = []

    for t_idx, t_date in enumerate(trading_days):
        regime_today = bool(spy_bt["regime_up"].loc[t_date]) if t_date in spy_bt.index else False
        t_ts = pd.Timestamp(t_date).normalize()

        # Step 1: Open-priced exits (flagged from prev-day close)
        still_open = []
        for pos in open_positions:
            reason = pos.get("open_exit_reason")
            if not reason:
                still_open.append(pos)
                continue

            sym = pos["sym"]
            df = price_data.get(sym)
            if df is None or t_date not in df.index:
                pos["open_exit_reason"] = None
                still_open.append(pos)
                continue

            t_pos_idx = df.index.get_loc(t_date)
            open_t = float(df["Open"].iloc[t_pos_idx])
            if open_t <= 0:
                pos["open_exit_reason"] = None
                still_open.append(pos)
                continue

            exit_cost, exit_liq = compute_transaction_cost(
                open_t, pos["shares"], df["Close"], df["Volume"], t_pos_idx
            )
            eff_exit = open_t - exit_cost / pos["shares"]
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
                "exit_reason": reason,
            })

        open_positions = still_open

        # Step 2: Close-priced entries (pending entries due today)
        new_pending = []
        for pend in pending_entries:
            if pend["entry_day_idx"] != t_idx:
                if pend["entry_day_idx"] > t_idx:
                    new_pending.append(pend)
                continue

            sym = pend["sym"]
            if not regime_today:
                continue
            if len(open_positions) >= max_positions:
                continue
            if any(p["sym"] == sym for p in open_positions):
                continue

            df = price_data.get(sym)
            if df is None or t_date not in df.index:
                continue

            t_pos_idx = df.index.get_loc(t_date)
            close_t = float(df["Close"].iloc[t_pos_idx])
            if close_t <= 0:
                continue

            alloc = min(init_cash * max_pos_pct, capital)
            shares = int(alloc / close_t)
            if shares <= 0:
                continue

            entry_cost, liq_flag = compute_transaction_cost(
                close_t, shares, df["Close"], df["Volume"], t_pos_idx
            )
            eff_entry = close_t + entry_cost / shares
            capital -= eff_entry * shares

            open_positions.append({
                "sym": sym,
                "entry_date": t_date.date(),
                "entry_price": eff_entry,
                "entry_close": close_t,
                "shares": shares,
                "entry_cost": entry_cost,
                "hold_days": 0,
                "liquidity_constrained": liq_flag,
                "open_exit_reason": None,
            })

        pending_entries = new_pending

        # Step 3: Scan earnings gap signals; queue entries for T+entry_delay
        if regime_today:
            active_syms = {p["sym"] for p in open_positions}
            pending_syms = {p["sym"] for p in pending_entries}

            for sym, earn_dates in earnings_map.items():
                if t_ts not in earn_dates:
                    continue
                if sym in active_syms or sym in pending_syms:
                    continue
                if sym not in price_data:
                    continue

                df = price_data[sym]
                if t_date not in df.index:
                    continue

                t_pos_idx = df.index.get_loc(t_date)
                if t_pos_idx < 1:
                    continue

                open_t = float(df["Open"].iloc[t_pos_idx])
                close_tm1 = float(df["Close"].iloc[t_pos_idx - 1])

                if close_tm1 <= 0 or open_t <= 0:
                    continue

                gap_pct = (open_t - close_tm1) / close_tm1
                if gap_pct < gap_pct_min:
                    continue

                daily_ret = df["Close"].pct_change()
                vol_20d = daily_ret.rolling(SIGMA_WINDOW).std().iloc[t_pos_idx - 1]
                if pd.isna(vol_20d) or vol_20d <= 0:
                    continue
                if gap_pct < gap_vol_ratio_min * vol_20d:
                    continue

                entry_day_idx = t_idx + entry_delay
                if entry_day_idx >= len(trading_days):
                    continue

                pending_entries.append({"sym": sym, "entry_day_idx": entry_day_idx})

        # Step 4: Time-based exits at today's close
        still_open = []
        for pos in open_positions:
            pos["hold_days"] += 1
            if pos["hold_days"] < hold_days_param:
                still_open.append(pos)
                continue

            sym = pos["sym"]
            df = price_data.get(sym)
            if df is None or t_date not in df.index:
                still_open.append(pos)
                continue

            t_pos_idx = df.index.get_loc(t_date)
            close_t = float(df["Close"].iloc[t_pos_idx])
            if close_t <= 0 or pos["shares"] <= 0:
                still_open.append(pos)
                continue

            exit_cost, exit_liq = compute_transaction_cost(
                close_t, pos["shares"], df["Close"], df["Volume"], t_pos_idx
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

        open_positions = still_open

        # Step 5: Flag positions for next-open exit (stop-loss or regime close)
        for pos in open_positions:
            df = price_data.get(pos["sym"])
            if df is None or t_date not in df.index:
                continue
            t_pos_idx = df.index.get_loc(t_date)
            close_t = float(df["Close"].iloc[t_pos_idx])

            if close_t < pos["entry_close"] * (1.0 - stop_loss_pct):
                pos["open_exit_reason"] = "STOP_LOSS"
            elif not regime_today:
                pos["open_exit_reason"] = "REGIME_EXIT"
            else:
                pos["open_exit_reason"] = None

        # Step 6: Mark-to-market at close
        mtm = capital
        for pos in open_positions:
            df = price_data.get(pos["sym"])
            if df is not None and t_date in df.index:
                mtm += pos["shares"] * float(df["Close"].loc[t_date])
        equity_curve.iloc[t_idx] = mtm

    # Force-close remaining positions at end of backtest
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
            exit_p, pos["shares"], df["Close"], df["Volume"], t_pos_idx
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

    # ── Performance Metrics ─────────────────────────────────────────────────
    equity_curve = equity_curve.ffill().fillna(float(init_cash))
    daily_returns = equity_curve.pct_change().fillna(0.0)

    col_names = [
        "sym", "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl", "cost", "hold_days", "liquidity_constrained", "exit_reason",
    ]
    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame(columns=col_names)

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

    is_trades = 0
    if n_trades > 0:
        is_trades = int((pd.to_datetime(trades_df["entry_date"]) <= pd.Timestamp(IS_END)).sum())

    data_quality = {
        "survivorship_bias": (
            "WARNING: Universe = current-day S&P 500 (local CSV). Delisted/demoted stocks excluded. "
            "Mild upward bias; large-cap names rarely exit via bankruptcy. MODERATE RISK, LOW MAGNITUDE."
        ),
        "look_ahead_status": (
            "CLEAN — signal uses T+0 open vs T-1 close + 20d vol through T-1. "
            "Entry at T+entry_delay close. Stop/regime: same-day close flag, next-day open exit."
        ),
        "earnings_coverage_rate": coverage_rate,
        "earnings_data_caveat": (
            "yfinance get_earnings_dates(limit=60) covers ~3 years from query date. "
            "IS window starts 2023-07-01 per PF-3 to avoid coverage gap."
        ),
        "price_adjusted": True,
        "gap_flags": gap_flags,
        "sma_gate": "150-SMA (Fix 2: replaces 200-SMA; recovers WF4 zero-trade window)",
        "universe_source": "Local static CSV — no runtime scrape dependency",
    }

    print(
        f"\nH86v2 ({start}–{end}):\n"
        f"  Total trades: {n_trades} | IS trades (<={IS_END}): {is_trades}\n"
        f"  Trades/yr: {trades_per_year}\n"
        f"  Sharpe: {sharpe} | MaxDD: {mdd:.2%} | TotalReturn: {total_return:.2%}\n"
        f"  WinRate: {win_rate:.2%} | ProfitFactor: {profit_factor}\n"
        f"  Earnings coverage: {coverage_rate:.1%} | Price data: {len(price_data)} tickers"
    )

    if is_trades < 100:
        warnings.warn(
            f"IS trade count = {is_trades} (threshold: 100). "
            "Investigate earnings date coverage or widen gap filters."
        )

    return {
        "trades": trades_df.to_dict("records"),
        "equity_curve": equity_curve,
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "is_trade_count": is_trades,
        "trades_per_year": trades_per_year,
        "total_return": total_return,
        "earnings_coverage_rate": coverage_rate,
        "returns": daily_returns,
        "equity": equity_curve,
        "params": params,
        "data_quality": data_quality,
    }


# ── Convenience Wrapper ───────────────────────────────────────────────────────

def run_backtest(params: dict = None, start: str = None, end: str = None) -> dict:
    """Full backtest: load data then simulate. Use simulate_strategy() for sweeps."""
    p = params or PARAMETERS.copy()
    s = start or p.get("start", "2023-07-01")
    e = end or p.get("end", "2026-06-24")
    sma_period = p.get("spy_sma_period", 150)
    cached = load_universe_data(s, e, sma_period=sma_period)
    return simulate_strategy(p, cached, s, e)


def run_strategy(ticker: str, start: str, end: str, params: dict = None) -> dict:
    """Orchestrator compatibility wrapper. `ticker` unused — strategy runs on full S&P 500."""
    p = params or PARAMETERS.copy()
    return run_backtest(params=p, start=p.get("start", start), end=p.get("end", end))


# ── Parameter Sweep ───────────────────────────────────────────────────────────

def scan_parameters(start: str, end: str, base_params: dict = None, cached: dict = None) -> list:
    """
    Run all 108 combos of the H86v2 parameter grid on pre-loaded IS data.
    Returns list of dicts: {gap_pct_min, gap_vol_ratio_min, ..., sharpe, mdd, win_rate, ...}

    Pass `cached` (from load_universe_data) to avoid re-downloading data for each combo.
    """
    import itertools

    if cached is None:
        sma_period = (base_params or PARAMETERS).get("spy_sma_period", 150)
        cached = load_universe_data(start, end, sma_period=sma_period)

    base = base_params or PARAMETERS.copy()
    keys = list(PARAM_GRID.keys())
    combos = list(itertools.product(*[PARAM_GRID[k] for k in keys]))

    print(f"Parameter sweep: {len(combos)} combos...")
    results = []
    for i, combo_vals in enumerate(combos):
        if i % 20 == 0:
            print(f"  Combo {i}/{len(combos)}...")
        p = base.copy()
        for k, v in zip(keys, combo_vals):
            p[k] = v
        try:
            r = simulate_strategy(p, cached, start, end)
            row = {k: v for k, v in zip(keys, combo_vals)}
            row.update({
                "sharpe": r["sharpe"],
                "max_drawdown": r["max_drawdown"],
                "win_rate": r["win_rate"],
                "profit_factor": r["profit_factor"],
                "trade_count": r["trade_count"],
            })
            results.append(row)
        except Exception as exc:
            warnings.warn(f"Combo {combo_vals} failed: {exc}")
            row = {k: v for k, v in zip(keys, combo_vals)}
            row.update({"sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
                         "profit_factor": 0.0, "trade_count": 0})
            results.append(row)

    return results


if __name__ == "__main__":
    result = run_backtest(PARAMETERS.copy(), PARAMETERS["start"], PARAMETERS["end"])
    is_count = result.get("is_trade_count", 0)
    total_count = result.get("trade_count", 0)

    print(f"\n--- SANITY CHECK ---")
    print(f"IS trade count (entry <= {IS_END}): {is_count}")
    print(f"Total trade count: {total_count}")
    if is_count < 100:
        print("CRITICAL FLAG: IS trade count below 100")
    else:
        print("IS trade count OK — ready for Backtest Runner delegation")
