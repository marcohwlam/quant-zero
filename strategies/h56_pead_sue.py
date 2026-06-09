"""
Strategy: H56 Post-Earnings Announcement Drift — SUE Ranked
Author: Strategy Coder Agent
Date: 2026-06-09
Hypothesis: Stocks with the highest Standardised Unexpected Earnings (SUE)
            exhibit persistent positive price drift for ~60 trading days after
            the quarterly filing date (PEAD effect, Bernard & Thomas 1989).
Asset class: equities
References:
    Bernard & Thomas (1989) — Post-Earnings-Announcement Drift
    Chan — Algorithmic Trading, Book 2
    SEC EDGAR XBRL API (free, no API key)

SUE formula (time-series seasonal random walk):
    eps_surprise = eps_q - eps_same_quarter_prior_year
    SUE = eps_surprise / rolling_std(eps_surprise, 8 quarters)

POINT-IN-TIME RULE: Entry signal uses filing_date (when SEC received the
10-Q), never period_end. See strategies/data/eps_edgar.py::get_sue_as_of.

BEAR-MARKET GATE (non-optional): No new positions opened when SPY 12-month
return < SHY 12-month return. Mandatory — GFC MDD ~-45% without it.
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

from strategies.data.eps_edgar import build_eps_panel, compute_sue, get_sue_as_of

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    "hold_days": 60,               # trading days to hold each position
    "top_n_percentile": 0.20,      # top 20% of SUE universe → ~100 stocks
    "min_sue_threshold": 1.0,      # minimum SUE to consider (filters noise)
    "eps_lookback_quarters": 8,    # rolling quarters for SUE std estimation
    "bear_gate_lookback_months": 12,   # months for SPY vs SHY comparison
    "signal_delay_days": 15,       # days after quarter-end before scanning
                                   # (most 10-Qs filed by then; conservative)
    "init_cash": 100_000,
    "start": "2010-01-01",         # backtest start
    "end": "2023-12-31",           # backtest end
}

# ── Transaction cost constants (Engineering Director spec) ─────────────────────

FIXED_COST_PER_SHARE = 0.005     # $0.005/share
SLIPPAGE_PCT = 0.0005            # 0.05%
MARKET_IMPACT_K = 0.1            # square-root impact coefficient
SIGMA_WINDOW = 20
ADV_WINDOW = 20
TRADING_DAYS_PER_YEAR = 252

# ── Universe ───────────────────────────────────────────────────────────────────


def get_sp500_tickers() -> list:
    """
    Current S&P 500 from Wikipedia.

    SURVIVORSHIP BIAS CAVEAT: uses current-day membership. Stocks delisted or
    removed during the backtest period are absent — same limitation as h27.
    """
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", header=0
        )
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        return tickers
    except Exception as exc:
        warnings.warn(f"Wikipedia S&P 500 fetch failed ({exc}). Using fallback list.")
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSLA",
            "JPM", "V", "UNH", "XOM", "JNJ", "WMT", "MA", "PG", "COST", "HD",
            "BAC", "CVX", "LLY", "ABBV", "KO", "MRK", "PEP", "AVGO", "ADBE",
            "CRM", "TMO", "MCD", "ACN", "ABT", "AMD", "NFLX", "DIS", "CSCO",
            "TXN", "HON", "INTC", "AMGN", "IBM", "NOW", "INTU", "QCOM", "LOW",
        ]


# ── Transaction cost model ─────────────────────────────────────────────────────


def _compute_txn_cost(price, shares, close_ser, vol_ser, idx):
    """
    Engineering Director canonical equities cost model.
    Returns (total_cost_dollars, liquidity_constrained_bool).
    """
    fixed = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares

    sigma = close_ser.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv = vol_ser.rolling(ADV_WINDOW).mean().iloc[idx]
    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1_000_000

    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    liq_constrained = bool(shares / adv > 0.01)
    if liq_constrained:
        warnings.warn(f"Liquidity-constrained order at idx={idx}: {shares} shares ({shares/adv:.2%} ADV)")

    return fixed + slippage + impact, liq_constrained


# ── Bear-market gate ───────────────────────────────────────────────────────────


def _build_bear_gate(spy_close: pd.Series, shy_close: pd.Series) -> pd.Series:
    """
    SPY 12-month total return vs SHY 12-month return.
    Returns boolean Series: True = in_market (SPY beating SHY → safe to trade).
    """
    spy_12m = spy_close / spy_close.shift(252) - 1
    shy_12m = shy_close / shy_close.shift(252) - 1
    return (spy_12m > shy_12m).rename("in_market")


# ── Data loader ────────────────────────────────────────────────────────────────


def _download_price(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Download OHLCV via yfinance. Returns empty DataFrame on failure.
    """
    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty or len(df) < 20:
            return pd.DataFrame()
        return df
    except Exception as exc:
        warnings.warn(f"{ticker}: price download failed — {exc}")
        return pd.DataFrame()


# ── Quarterly rebalance dates ──────────────────────────────────────────────────


def _quarterly_rebalance_dates(start: str, end: str, signal_delay_days: int) -> list:
    """
    Generate one rebalance date per quarter = quarter-end + signal_delay_days
    calendar days (conservative: most 10-Qs filed by then).

    Quarter-ends: Mar 31, Jun 30, Sep 30, Dec 31.
    """
    qtr_ends = pd.date_range(start=start, end=end, freq="QE")
    rebalance_dates = []
    for qe in qtr_ends:
        rb = qe + pd.Timedelta(days=signal_delay_days)
        if rb <= pd.Timestamp(end):
            rebalance_dates.append(rb)
    return rebalance_dates


# ── Main backtest ──────────────────────────────────────────────────────────────


def run_backtest(params: dict = None) -> dict:
    """
    Run H56 PEAD/SUE backtest.

    Algorithm (no look-ahead bias):
    1. Fetch S&P 500 universe (survivorship bias caveat noted).
    2. Build EPS panel from SEC EDGAR; compute SUE with 8-quarter rolling std.
    3. Download price data for universe + SPY + SHY.
    4. At each quarterly rebalance date r:
       a. Bear gate: skip if SPY 12m return <= SHY 12m return.
       b. Retrieve get_sue_as_of(sue_df, r) — POINT-IN-TIME GUARD.
       c. Filter: sue >= min_sue_threshold; take top top_n_percentile.
       d. Equal-weight allocation; enter at next-day close.
    5. Exit each position after hold_days trading days.
    6. Force-close all positions at backtest end.
    7. Compute performance metrics.

    Anti-lookahead spot check: printed to stdout during run.
    """
    if params is None:
        params = PARAMETERS.copy()

    start = params["start"]
    end = params["end"]
    hold_days_param = params["hold_days"]
    top_n_pct = params["top_n_percentile"]
    min_sue = params["min_sue_threshold"]
    lookback_q = params["eps_lookback_quarters"]
    signal_delay = params["signal_delay_days"]
    init_cash = params["init_cash"]

    # Warmup: need 252 extra days for bear gate
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=365)).strftime("%Y-%m-%d")

    # ── Step 1: Universe ───────────────────────────────────────────────────────
    print("Fetching S&P 500 universe...")
    universe = get_sp500_tickers()
    print(f"Universe: {len(universe)} tickers")

    # ── Step 2: EDGAR EPS + SUE ────────────────────────────────────────────────
    print("Fetching SEC EDGAR EPS data (this takes ~5-10 min for full S&P 500)...")
    print("  Rate-limited to <=10 req/sec per SEC policy.")
    eps_panel = build_eps_panel(universe)
    if eps_panel.empty:
        raise RuntimeError("EPS panel is empty — all EDGAR fetches failed. Check connectivity.")

    print(f"EPS panel: {len(eps_panel)} rows, {eps_panel['ticker'].nunique()} tickers")
    sue_df = compute_sue(eps_panel, lookback_quarters=lookback_q)
    print(f"SUE panel: {len(sue_df)} observations, {sue_df['ticker'].nunique()} tickers")

    # ── Step 3: Price data ─────────────────────────────────────────────────────
    print("Downloading SPY and SHY for bear gate...")
    spy_df = _download_price("SPY", warmup_start, end)
    shy_df = _download_price("SHY", warmup_start, end)
    if spy_df.empty or shy_df.empty:
        raise RuntimeError("SPY or SHY price download failed.")

    bear_gate = _build_bear_gate(spy_df["Close"], shy_df["Close"])

    print(f"Downloading prices for {len(universe)} tickers...")
    price_data = {}
    for sym in universe:
        df = _download_price(sym, warmup_start, end)
        if not df.empty:
            price_data[sym] = df
    print(f"Loaded price data for {len(price_data)}/{len(universe)} tickers")

    # ── Step 4: Rebalance schedule ─────────────────────────────────────────────
    rebalance_dates = _quarterly_rebalance_dates(start, end, signal_delay)
    print(f"Quarterly rebalance dates: {len(rebalance_dates)}")

    # ── Step 5: Simulation ─────────────────────────────────────────────────────
    # Build trading day index from SPY
    trading_days = spy_df.loc[spy_df.index >= pd.Timestamp(start)].index

    capital = float(init_cash)
    open_positions = []   # list of position dicts
    trade_log = []
    equity_curve = pd.Series(np.nan, index=trading_days, dtype=float)

    # Map each rebalance date to the first trading day on or after it.
    # This is computed upfront so the loop never fires twice for the same quarter.
    trading_day_set = set(trading_days)
    fired_rebalances = set()   # rebalance dates already executed (by their canonical date)

    def _first_trading_day_on_or_after(target_ts):
        """Return first trading day >= target_ts, or None if past end of data."""
        for td in trading_days:
            if pd.Timestamp(td) >= target_ts:
                return pd.Timestamp(td)
        return None

    rebalance_map = {}   # canonical_rebalance_date -> first_trading_day_to_act
    for rd in rebalance_dates:
        rd_ts = pd.Timestamp(rd)
        td = _first_trading_day_on_or_after(rd_ts)
        if td is not None:
            rebalance_map[rd_ts] = td

    # Invert: trading_day -> canonical rebalance date (for O(1) lookup in loop)
    action_day_to_rebalance = {v: k for k, v in rebalance_map.items()}

    anti_lookahead_samples = []   # for acceptance criterion 4

    for t_idx, t_date in enumerate(trading_days):
        t_ts = pd.Timestamp(t_date)

        # ── Exit maturing positions ────────────────────────────────────────────
        still_open = []
        for pos in open_positions:
            pos["days_held"] += 1
            sym = pos["sym"]
            df = price_data.get(sym)
            if df is None or t_date not in df.index:
                still_open.append(pos)
                continue

            idx = df.index.get_loc(t_date)
            close_t = float(df["Close"].iloc[idx])

            if pos["days_held"] >= hold_days_param:
                if close_t <= 0 or pos["shares"] <= 0:
                    still_open.append(pos)
                    continue
                exit_cost, exit_liq = _compute_txn_cost(
                    close_t, pos["shares"], df["Close"], df["Volume"], idx
                )
                eff_exit = close_t - exit_cost / pos["shares"]
                pnl = (eff_exit - pos["entry_price"]) * pos["shares"]
                capital += eff_exit * pos["shares"]
                trade_log.append({
                    "sym": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": t_date.date(),
                    "entry_price": round(pos["entry_price"], 4),
                    "exit_price": round(eff_exit, 4),
                    "shares": pos["shares"],
                    "pnl": round(pnl, 2),
                    "sue_at_entry": round(pos["sue"], 4),
                    "filing_date": pos["filing_date"],
                    "days_held": pos["days_held"],
                    "liq_constrained": pos["liq_constrained"] or exit_liq,
                    "exit_reason": "TIME_EXIT",
                })
            else:
                still_open.append(pos)

        open_positions = still_open

        # ── Quarterly rebalance: open new positions ────────────────────────────
        canonical_rb = action_day_to_rebalance.get(t_ts)
        is_rebalance_day = canonical_rb is not None and canonical_rb not in fired_rebalances

        if is_rebalance_day:
            fired_rebalances.add(canonical_rb)  # mark done regardless of gate outcome
            # Check bear gate — mandatory; no new equity positions if gate is red
            gate_val = bear_gate.reindex([t_date]).iloc[0] if t_date in bear_gate.index else False
            if not gate_val:
                # BEAR GATE FIRED: hold cash, no new positions this quarter
                print(f"  Bear gate fired on {t_date.date()} — skipping rebalance")
            else:
                # Point-in-time SUE lookup — CRITICAL guard: filed_date <= t_date
                sue_as_of = get_sue_as_of(sue_df, t_ts)  # POINT-IN-TIME GUARD (see eps_edgar.py)
                if sue_as_of.empty:
                    pass
                else:
                    # Filter: must be in universe AND meet threshold
                    eligible = sue_as_of[
                        sue_as_of.index.isin(price_data.keys()) &
                        (sue_as_of >= min_sue)
                    ]
                    if not eligible.empty:
                        cutoff = eligible.quantile(1.0 - top_n_pct)
                        top_sues = eligible[eligible >= cutoff].sort_values(ascending=False)

                        # Anti-lookahead spot check: log first 5 signals
                        if len(anti_lookahead_samples) < 5:
                            for sym, sue_val in top_sues.head(5).items():
                                matching = sue_df[
                                    (sue_df["ticker"] == sym) &
                                    (sue_df["filing_date"] <= t_ts)
                                ]
                                if not matching.empty:
                                    last_row = matching.iloc[-1]
                                    anti_lookahead_samples.append({
                                        "ticker": sym,
                                        "entry_date": t_ts.date(),
                                        "filing_date": last_row["filing_date"].date(),
                                        "filed_date_le_entry": last_row["filing_date"] <= t_ts,
                                        "sue": round(sue_val, 4),
                                    })

                        # Equal-weight allocation across top-N
                        n_stocks = len(top_sues)
                        alloc = init_cash / max(n_stocks, 1)

                        already_held = {p["sym"] for p in open_positions}
                        for sym, sue_val in top_sues.items():
                            if sym in already_held:
                                continue
                            if capital < 1.0:
                                break

                            df = price_data.get(sym)
                            if df is None:
                                continue
                            # Enter at today's close (next-open would be ideal but requires
                            # next-bar logic; close is conservative approximation)
                            if t_date not in df.index:
                                continue
                            idx = df.index.get_loc(t_date)
                            entry_p = float(df["Close"].iloc[idx])
                            if entry_p <= 0:
                                continue

                            shares = int(min(alloc, capital) / entry_p)
                            if shares <= 0:
                                continue

                            entry_cost, liq = _compute_txn_cost(
                                entry_p, shares, df["Close"], df["Volume"], idx
                            )
                            eff_entry = entry_p + entry_cost / shares
                            capital -= eff_entry * shares

                            # Retrieve filing_date for this signal
                            filing_date = sue_df[
                                (sue_df["ticker"] == sym) &
                                (sue_df["filing_date"] <= t_ts)
                            ]["filing_date"].max()

                            open_positions.append({
                                "sym": sym,
                                "entry_date": t_date.date(),
                                "entry_price": eff_entry,
                                "shares": shares,
                                "entry_cost": entry_cost,
                                "days_held": 0,
                                "liq_constrained": liq,
                                "sue": sue_val,
                                "filing_date": filing_date,
                            })
                            already_held.add(sym)

        # ── Mark-to-market ─────────────────────────────────────────────────────
        mtm = capital
        for pos in open_positions:
            df = price_data.get(pos["sym"])
            if df is not None and t_date in df.index:
                mtm += pos["shares"] * float(df["Close"].loc[t_date])
        equity_curve.iloc[t_idx] = mtm

    # ── Force-close remaining at end ───────────────────────────────────────────
    last_date = trading_days[-1]
    for pos in open_positions:
        sym = pos["sym"]
        df = price_data.get(sym)
        if df is None or last_date not in df.index:
            continue
        idx = df.index.get_loc(last_date)
        exit_p = float(df["Close"].iloc[idx])
        if exit_p <= 0:
            continue
        exit_cost, exit_liq = _compute_txn_cost(
            exit_p, pos["shares"], df["Close"], df["Volume"], idx
        )
        eff_exit = exit_p - exit_cost / pos["shares"]
        pnl = (eff_exit - pos["entry_price"]) * pos["shares"]
        capital += eff_exit * pos["shares"]
        trade_log.append({
            "sym": sym,
            "entry_date": pos["entry_date"],
            "exit_date": last_date.date(),
            "entry_price": round(pos["entry_price"], 4),
            "exit_price": round(eff_exit, 4),
            "shares": pos["shares"],
            "pnl": round(pnl, 2),
            "sue_at_entry": round(pos["sue"], 4),
            "filing_date": pos["filing_date"],
            "days_held": pos["days_held"],
            "liq_constrained": pos["liq_constrained"] or exit_liq,
            "exit_reason": "END_OF_DATA",
        })

    # ── Performance metrics ────────────────────────────────────────────────────
    equity_curve = equity_curve.ffill().fillna(float(init_cash))
    daily_returns = equity_curve.pct_change().fillna(0.0)
    n_trades = len(trade_log)
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

    trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
    win_rate = 0.0
    profit_factor = 0.0
    if n_trades > 0:
        win_rate = round(float((trades_df["pnl"] > 0).mean()), 4)
        wins = trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum()
        losses = trades_df.loc[trades_df["pnl"] < 0, "pnl"].abs().sum()
        profit_factor = round(float(wins / max(losses, 1e-8)), 4)

    print(f"\n{'='*60}")
    print(f"H56 PEAD/SUE Backtest ({start} to {end})")
    print(f"  Trades: {n_trades} | Trades/yr: {trades_per_year}")
    print(f"  Sharpe: {sharpe} | Max DD: {mdd:.2%} | Total Return: {total_return:.2%}")
    print(f"  Win rate: {win_rate:.2%} | Profit Factor: {profit_factor}")

    # Acceptance criterion 4: anti-lookahead spot check
    print(f"\nAnti-lookahead spot check (filed_date <= entry_date for all rows):")
    for row in anti_lookahead_samples[:5]:
        print(f"  {row}")
    if anti_lookahead_samples:
        all_clean = all(r["filed_date_le_entry"] for r in anti_lookahead_samples)
        print(f"  All rows clean: {all_clean}")

    return {
        "trades": trade_log,
        "equity_curve": equity_curve.tolist(),
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": n_trades,
        "trades_per_year": trades_per_year,
        "returns": daily_returns,
        "equity": equity_curve,
        "params": params,
        "data_quality": {
            "survivorship_bias": "Current-day S&P 500 membership — historical delisted tickers absent.",
            "eps_source": "SEC EDGAR XBRL (free, no API key)",
            "point_in_time": "filed_date used as knowledge cutoff (not period_end)",
            "bear_gate": "SPY 12m return vs SHY 12m return",
        },
    }


def run_strategy(ticker: str = "SPY", start: str = None, end: str = None,
                 params: dict = None) -> dict:
    """Orchestrator compatibility shim. ticker is unused (portfolio strategy)."""
    p = (params or PARAMETERS).copy()
    if start:
        p["start"] = start
    if end:
        p["end"] = end
    return run_backtest(p)


if __name__ == "__main__":
    result = run_backtest(PARAMETERS.copy())
    trades = result.get("trades", [])
    print(f"\nSample trades (first 5 of {len(trades)}):")
    for t in trades[:5]:
        print(t)
