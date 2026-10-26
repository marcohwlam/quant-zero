"""
Strategy: H79 — 52-Week High Proximity Cross-Section
Author: Strategy Coder Agent
Date: 2026-06-19
Hypothesis: Stocks near 52-week high outperform anchored stocks (George & Hwang 2004).
             Monthly rebalance long-short: top decile by Price/52WH = long,
             bottom decile = short. Market-neutral (~50L + ~50S positions).
Asset class: equities
Parent task: QUA-347

Data quality:
  Universe: ~1,047 PIT members from h82v2_universe_2018_jan.csv (Russell 1000+2000 circa 2018).
    Point-in-time proxy — NOT current index constituents (eliminates survivorship bias).
    Some 2018-era members since delisted will be absent from yfinance (real returns through
    delisting date contribute correctly; tickers with <252 total days excluded pre-backtest).
  Price adjustments: yfinance auto_adjust=True (splits + dividends).
  Data gaps: tickers with >5 missing business days flagged in data_quality output.
  Earnings exclusion: NOT excluded (21-day hold period dilutes event impact).
  Delisted tickers: forward-filled at last known price for MTM; excluded from new position
    signals when prox_52wh is NaN; closed at next rebalance at forward-filled price.

Transaction cost model (canonical per AGENTS.md):
  Fixed: $0.005/share per leg
  Slippage: 0.05% per leg (equities standard tier)
  Short borrow: 1.0%/year applied daily to short position market value
  Market impact: k=0.1 × σ × sqrt(order_value / dollar_ADV)
  Liquidity flag: order_value / dollar_ADV > 0.01 → liquidity_constrained warning

Signal: prox_52wh = Close / rolling(252).max() — computed at day T, traded at T close.
        Higher ratio → closer to 52WH → long signal (underreaction / anchoring bias).
        Top decile = long; bottom decile = short; monthly rebalance.

Positions: 100% gross long + 100% gross short = 200% gross, ~0% net (market-neutral).
           Short proceeds offset long purchases; equity tracks the long-short spread.
"""

import math
import os
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

PARAMETERS = {
    "universe_file": "data/h82v2_universe_2018_jan.csv",
    "min_price": 5.0,
    "min_adv_dollars": 5_000_000,
    "prox_lookback": 252,
    "rebalance_freq": 21,            # trading days between rebalances (~monthly)
    "long_decile": 0.10,             # top fraction → long
    "short_decile": 0.10,            # bottom fraction → short
    "max_long_positions": 50,
    "max_short_positions": 50,
    "borrow_cost_annual": 0.01,      # 1%/year short borrow rate
    "impact_k": 0.1,
    "adv_liquidity_threshold": 0.01,
    "is_start": "2018-01-01",
    "is_end": "2023-12-31",
    "oos_start": "2024-01-01",
    "oos_end": "2026-05-31",
    "init_cash": 100_000.0,
    "buffer_start": "2017-01-01",    # warm-up buffer for 252-day rolling window
}


# ── Universe Loading ────────────────────────────────────────────────────────────

def load_universe(params: dict) -> list:
    """Load PIT universe from CSV; fall back to compact 50-name list."""
    fpath = params.get("universe_file", "data/h82v2_universe_2018_jan.csv")
    if os.path.exists(fpath):
        df = pd.read_csv(fpath)
        col = next(
            (c for c in df.columns if c.lower() in ("ticker", "symbol")),
            df.columns[0],
        )
        tickers = df[col].dropna().str.strip().str.upper().tolist()
        tickers = [t for t in tickers if t and "/" not in t and len(t) <= 5]
        print(f"Loaded {len(tickers)} tickers from {fpath}")
        return list(dict.fromkeys(tickers))

    warnings.warn(f"Universe file not found: {fpath}. Using 50-name fallback (survivorship-biased).")
    return [
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "JPM", "JNJ", "XOM",
        "BAC", "UNH", "V", "HD", "PG", "MA", "DIS", "ADBE", "NFLX", "CRM",
        "PYPL", "TMO", "ABT", "COST", "NKE", "ABBV", "AVGO", "PEP", "MCD", "LLY",
        "MDT", "TXN", "HON", "UNP", "QCOM", "PM", "CVX", "BMY", "AMGN", "SBUX",
        "IBM", "INTU", "GS", "ISRG", "CAT", "GE", "DE", "MO", "GILD", "LMT",
    ]


# ── Data Download ───────────────────────────────────────────────────────────────

def download_data(tickers: list, buf_start: str, end: str) -> tuple:
    """
    Batch-download adjusted OHLCV for all universe tickers (batches of 50).
    auto_adjust=True: prices adjusted for splits and dividends.
    Returns (close_df, volume_df) with tickers as columns, dates as index.
    """
    close_list, vol_list = [], []
    batch_size = 50

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i: i + batch_size]
        try:
            raw = yf.download(batch, start=buf_start, end=end, auto_adjust=True, progress=False)
        except Exception as exc:
            warnings.warn(f"Download batch {i // batch_size} failed: {exc}")
            continue
        if raw.empty:
            continue

        if isinstance(raw.columns, pd.MultiIndex):
            top = raw.columns.get_level_values(0).unique()
            if "Close" in top:
                close_list.append(raw["Close"])
            if "Volume" in top:
                vol_list.append(raw["Volume"])
        else:
            t0 = batch[0]
            close_list.append(raw[["Close"]].rename(columns={"Close": t0}))
            vol_list.append(raw[["Volume"]].rename(columns={"Volume": t0}))

    if not close_list:
        raise RuntimeError("No price data downloaded. Check yfinance connectivity.")

    close = pd.concat(close_list, axis=1)
    vol = pd.concat(vol_list, axis=1)
    close = close.loc[:, ~close.columns.duplicated()]
    vol = vol.loc[:, ~vol.columns.duplicated()]

    print(f"Downloaded {close.shape[1]} tickers × {close.shape[0]} days")
    return close, vol


# ── Market Impact ───────────────────────────────────────────────────────────────

def _impact_cost(order_value: float, dollar_adv: float, sigma: float, k: float) -> float:
    """
    Square-root market impact in dollars: k × σ × sqrt(order_value / dollar_ADV) × order_value.
    Returns 0 when ADV or sigma is unavailable/zero.
    """
    if dollar_adv <= 0 or sigma <= 0 or order_value <= 0 or not math.isfinite(dollar_adv):
        return 0.0
    return order_value * k * sigma * math.sqrt(order_value / dollar_adv)


# ── Period Simulation ───────────────────────────────────────────────────────────

def _run_period(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    close_ffilled: pd.DataFrame,
    dollar_adv_full: pd.DataFrame,
    sigma_full: pd.DataFrame,
    params: dict,
    start: str,
    end: str,
) -> dict:
    """
    Simulate one period (IS or OOS) of the 52WH cross-section strategy.

    close: full adjusted prices including warm-up buffer (non-ffilled) — used for signals.
    close_ffilled: forward-filled prices — used for MTM and position closing.
    dollar_adv_full, sigma_full: precomputed from full history (no look-ahead).

    Returns dict: equity_curve, trade_log, positions_df, sharpe, max_drawdown,
                  total_return, trade_count, win_rate, liquidity_flags.
    """
    close_period = close_ffilled.loc[start:end]
    dates = close_period.index
    n_dates = len(dates)

    if n_dates == 0:
        return {
            "equity_curve": pd.Series(dtype=float),
            "trade_log": [],
            "positions_df": pd.DataFrame(),
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "trade_count": 0,
            "win_rate": 0.0,
            "liquidity_flags": 0,
        }

    # 52WH proximity signal (non-ffilled close — delisted tickers give NaN, excluded from signal)
    high_52w = close.rolling(params["prox_lookback"]).max()
    prox_52wh = (close / high_52w).loc[start:end]

    dollar_adv_p = dollar_adv_full.loc[start:end]
    sigma_p = sigma_full.loc[start:end]

    # Rebalance schedule: every rebalance_freq trading days, starting day 0
    rebal_freq = params["rebalance_freq"]
    rebal_dates_set = set(dates[i] for i in range(0, n_dates, rebal_freq))

    # Mutable portfolio state
    cash = float(params["init_cash"])
    # positions: {ticker: {shares, entry_price, entry_date, side, entry_cost, borrow_accrued}}
    positions = {}
    equity_list = []
    trade_log = []
    positions_snapshots = {}
    liquidity_flags = 0

    def _do_impact(ticker, order_value, date):
        nonlocal liquidity_flags
        try:
            adv_val = dollar_adv_p.at[date, ticker] if ticker in dollar_adv_p.columns else np.nan
            sig_val = sigma_p.at[date, ticker] if ticker in sigma_p.columns else np.nan
        except (KeyError, TypeError):
            adv_val, sig_val = np.nan, np.nan
        if pd.isna(adv_val) or pd.isna(sig_val) or adv_val <= 0:
            return 0.0
        if order_value / adv_val > params["adv_liquidity_threshold"]:
            liquidity_flags += 1
        return _impact_cost(order_value, adv_val, sig_val, params["impact_k"])

    for i, date in enumerate(dates):
        day_prices = close_period.loc[date]

        # Daily short borrow costs (accrued before MTM)
        for ticker, pos in positions.items():
            if pos["side"] == "short":
                px = day_prices.get(ticker, np.nan)
                if not pd.isna(px) and px > 0:
                    borrow = abs(pos["shares"]) * px * params["borrow_cost_annual"] / 252
                    cash -= borrow
                    pos["borrow_accrued"] += borrow

        # Monthly rebalance: close all positions, open new ones
        if date in rebal_dates_set:
            # Close all existing positions at today's (ffilled) close
            for ticker in list(positions.keys()):
                pos = positions.pop(ticker)
                px = day_prices.get(ticker, np.nan)
                if pd.isna(px) or px <= 0:
                    continue

                n = abs(pos["shares"])
                side = pos["side"]
                entry_px = pos["entry_price"]
                order_val = n * px
                impact = _do_impact(ticker, order_val, date)
                close_cost = 0.0005 * px * n + 0.005 * n + impact

                if side == "long":
                    cash += n * px - close_cost
                    pnl_gross = n * (px - entry_px)
                else:
                    cash -= n * px + close_cost
                    pnl_gross = n * (entry_px - px)

                borrow_acc = pos.get("borrow_accrued", 0.0)
                pnl_net = pnl_gross - pos["entry_cost"] - close_cost - borrow_acc

                trade_log.append({
                    "date": str(date.date()) if hasattr(date, "date") else str(date),
                    "entry_date": (
                        str(pos["entry_date"].date())
                        if hasattr(pos["entry_date"], "date")
                        else str(pos["entry_date"])
                    ),
                    "ticker": ticker,
                    "side": side,
                    "qty": round(float(n), 4),
                    "entry_price": round(float(entry_px), 4),
                    "exit_price": round(float(px), 4),
                    "pnl_gross": round(float(pnl_gross), 4),
                    "pnl_net": round(float(pnl_net), 4),
                    "cost_total": round(float(pos["entry_cost"] + close_cost + borrow_acc), 4),
                })

            # Compute new signal rankings
            prox_row = prox_52wh.loc[date] if date in prox_52wh.index else pd.Series(dtype=float)
            adv_row = dollar_adv_p.loc[date] if date in dollar_adv_p.index else pd.Series(dtype=float)

            # Universe filter: valid signal, valid price, min price, min ADV
            common = prox_row.index.intersection(day_prices.index)
            prox_sub = prox_row.reindex(common)
            px_sub = day_prices.reindex(common)
            adv_sub = adv_row.reindex(common, fill_value=np.nan)

            valid_mask = (
                prox_sub.notna()
                & px_sub.notna()
                & (px_sub >= params["min_price"])
                & (adv_sub >= params["min_adv_dollars"]).fillna(False)
            )
            valid_tickers = prox_sub[valid_mask].index.tolist()

            if len(valid_tickers) < 20:
                positions_snapshots[date] = {}
            else:
                prox_valid = prox_sub[valid_tickers].sort_values(ascending=False)
                n_universe = len(prox_valid)

                n_long = min(
                    params["max_long_positions"],
                    max(1, int(n_universe * params["long_decile"]))
                )
                n_short = min(
                    params["max_short_positions"],
                    max(1, int(n_universe * params["short_decile"]))
                )

                long_tickers = prox_valid.index[:n_long].tolist()
                short_tickers = prox_valid.index[-n_short:].tolist()

                # Port value = cash after all closes (all positions liquidated)
                port_value = max(cash, float(params["init_cash"]) * 0.001)
                # 100% gross long + 100% gross short = 200% gross, ~0% net
                long_alloc = port_value / n_long if n_long > 0 else 0.0
                short_alloc = port_value / n_short if n_short > 0 else 0.0

                # Open long positions (top decile by 52WH proximity — underreaction)
                for ticker in long_tickers:
                    px = day_prices.get(ticker, np.nan)
                    if pd.isna(px) or px <= 0:
                        continue
                    shares = long_alloc / px
                    order_val = shares * px
                    impact = _do_impact(ticker, order_val, date)
                    entry_cost = 0.0005 * px * shares + 0.005 * shares + impact
                    cash -= shares * px + entry_cost
                    positions[ticker] = {
                        "shares": shares,
                        "entry_price": px,
                        "entry_date": date,
                        "side": "long",
                        "entry_cost": entry_cost,
                        "borrow_accrued": 0.0,
                    }

                # Open short positions (bottom decile — anchored far below 52WH)
                for ticker in short_tickers:
                    if ticker in positions:
                        continue  # skip if also selected long (rare edge case)
                    px = day_prices.get(ticker, np.nan)
                    if pd.isna(px) or px <= 0:
                        continue
                    shares = short_alloc / px
                    order_val = shares * px
                    impact = _do_impact(ticker, order_val, date)
                    entry_cost = 0.0005 * px * shares + 0.005 * shares + impact
                    cash += shares * px - entry_cost  # receive short sale proceeds
                    positions[ticker] = {
                        "shares": -shares,  # negative = short
                        "entry_price": px,
                        "entry_date": date,
                        "side": "short",
                        "entry_cost": entry_cost,
                        "borrow_accrued": 0.0,
                    }

                # Snapshot position weights for positions_df
                port_val_now = cash + sum(
                    pos["shares"] * day_prices.get(t, 0.0)
                    for t, pos in positions.items()
                )
                snap = {}
                if port_val_now > 0:
                    for ticker, pos in positions.items():
                        px = day_prices.get(ticker, np.nan)
                        if not pd.isna(px):
                            snap[ticker] = round(float(pos["shares"] * px / port_val_now), 6)
                positions_snapshots[date] = snap

        # End-of-day mark-to-market equity
        port_value = cash
        for ticker, pos in positions.items():
            px = day_prices.get(ticker, np.nan)
            if not pd.isna(px) and px > 0:
                port_value += pos["shares"] * px
        equity_list.append(port_value)

    # Close remaining open positions at period end
    last_date = dates[-1]
    last_prices = close_period.loc[last_date]
    for ticker in list(positions.keys()):
        pos = positions.pop(ticker)
        px = last_prices.get(ticker, np.nan)
        if pd.isna(px) or px <= 0:
            continue

        n = abs(pos["shares"])
        side = pos["side"]
        entry_px = pos["entry_price"]
        close_cost = 0.0005 * px * n + 0.005 * n

        if side == "long":
            cash += n * px - close_cost
            pnl_gross = n * (px - entry_px)
        else:
            cash -= n * px + close_cost
            pnl_gross = n * (entry_px - px)

        borrow_acc = pos.get("borrow_accrued", 0.0)
        pnl_net = pnl_gross - pos["entry_cost"] - close_cost - borrow_acc

        trade_log.append({
            "date": str(last_date.date()) if hasattr(last_date, "date") else str(last_date),
            "entry_date": (
                str(pos["entry_date"].date())
                if hasattr(pos["entry_date"], "date")
                else str(pos["entry_date"])
            ),
            "ticker": ticker,
            "side": side,
            "qty": round(float(n), 4),
            "entry_price": round(float(entry_px), 4),
            "exit_price": round(float(px), 4),
            "pnl_gross": round(float(pnl_gross), 4),
            "pnl_net": round(float(pnl_net), 4),
            "cost_total": round(float(pos["entry_cost"] + close_cost + borrow_acc), 4),
        })

    # Build outputs
    equity_curve = pd.Series(equity_list, index=dates, name="equity")

    # Forward-fill position snapshots to daily positions_df
    if positions_snapshots:
        pos_df = pd.DataFrame(positions_snapshots).T
        pos_df = pos_df.reindex(dates).ffill().fillna(0.0)
    else:
        pos_df = pd.DataFrame(index=dates)

    # Scalar metrics
    returns = equity_curve.pct_change().fillna(0.0)
    std = float(returns.std())
    sharpe = float(returns.mean() / (std + 1e-8) * math.sqrt(252)) if std > 1e-10 else 0.0

    cum = equity_curve / equity_curve.iloc[0]
    roll_max = cum.cummax()
    max_dd = float(((cum - roll_max) / (roll_max + 1e-8)).min())
    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)

    pnls = [t["pnl_net"] for t in trade_log]
    win_rate = sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0.0

    return {
        "equity_curve": equity_curve,
        "trade_log": trade_log,
        "positions_df": pos_df,
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "total_return": round(total_return, 4),
        "trade_count": len(trade_log),
        "win_rate": round(win_rate, 4),
        "liquidity_flags": liquidity_flags,
    }


# ── Main Entry Point ────────────────────────────────────────────────────────────

def run_strategy(params: dict = PARAMETERS) -> dict:
    """
    Download data and run IS + OOS periods of H79 52WH Proximity Cross-Section.

    Warm-up: downloads from buffer_start (2017-01-01) so the 252-day rolling window
    has full history on the first IS rebalance date (2018-01-01).

    Returns:
        is, oos: sub-dicts with scalar metrics + trade_log
        _is_equity_curve, _oos_equity_curve: pd.Series (portfolio value in $)
        _is_positions_df, _oos_positions_df: date × ticker weight DataFrames
        liquidity_flags_is, liquidity_flags_oos: int
        universe_size: int (after data quality filter)
        universe_size_raw: int (before filter)
        data_quality: {"is": {...}, "oos": {...}} with flagged ticker lists
        positions_df, equity_curve, trade_log: IS-period top-level aliases
    """
    tickers = load_universe(params)

    print(f"Downloading price data {params['buffer_start']} → {params['oos_end']} ...")
    close, volume = download_data(tickers, params["buffer_start"], params["oos_end"])

    # Remove tickers with <252 total days of valid data
    valid_cols = [c for c in close.columns if close[c].notna().sum() >= params["prox_lookback"]]
    close = close[valid_cols]
    volume = volume.reindex(columns=valid_cols, fill_value=0.0)
    universe_size = len(valid_cols)
    print(f"Universe after data filter: {universe_size} tickers")

    # Forward-fill for MTM; original used for signals (NaN = truly missing/delisted)
    close_ffilled = close.ffill()

    # Precompute dollar ADV and sigma over full history (backward-looking, no look-ahead)
    dollar_adv_full = (close * volume).rolling(20).mean()
    sigma_full = close.pct_change().rolling(20).std()

    # Data quality: flag tickers with >5 NaN trading days per period
    def _flag_missing(p_start, p_end):
        sub = close.loc[p_start:p_end]
        missing = sub.isna().sum()
        flagged = missing[missing > 5].index.tolist()
        return {"flagged": flagged, "missing_counts": missing[missing > 5].to_dict()}

    dq_is = _flag_missing(params["is_start"], params["is_end"])
    dq_oos = _flag_missing(params["oos_start"], params["oos_end"])
    print(
        f"Data quality: IS flagged {len(dq_is['flagged'])} tickers, "
        f"OOS flagged {len(dq_oos['flagged'])} tickers (>5 NaN days)"
    )

    print("\nRunning IS period ...")
    is_r = _run_period(
        close, volume, close_ffilled, dollar_adv_full, sigma_full,
        params, params["is_start"], params["is_end"]
    )

    print("\nRunning OOS period ...")
    oos_r = _run_period(
        close, volume, close_ffilled, dollar_adv_full, sigma_full,
        params, params["oos_start"], params["oos_end"]
    )

    return {
        "is": {
            "sharpe": is_r["sharpe"],
            "max_drawdown": is_r["max_drawdown"],
            "total_return": is_r["total_return"],
            "trade_count": is_r["trade_count"],
            "win_rate": is_r["win_rate"],
            "trade_log": is_r["trade_log"],
        },
        "oos": {
            "sharpe": oos_r["sharpe"],
            "max_drawdown": oos_r["max_drawdown"],
            "total_return": oos_r["total_return"],
            "trade_count": oos_r["trade_count"],
            "win_rate": oos_r["win_rate"],
            "trade_log": oos_r["trade_log"],
        },
        "_is_equity_curve": is_r["equity_curve"],
        "_oos_equity_curve": oos_r["equity_curve"],
        "_is_positions_df": is_r["positions_df"],
        "_oos_positions_df": oos_r["positions_df"],
        "liquidity_flags_is": is_r["liquidity_flags"],
        "liquidity_flags_oos": oos_r["liquidity_flags"],
        "universe_size": universe_size,
        "universe_size_raw": len(tickers),
        "data_quality": {"is": dq_is, "oos": dq_oos},
        # IS-period top-level aliases
        "positions_df": is_r["positions_df"],
        "equity_curve": is_r["equity_curve"],
        "trade_log": is_r["trade_log"],
    }


if __name__ == "__main__":
    result = run_strategy(PARAMETERS)
    is_r = result["is"]
    oos_r = result["oos"]
    print(f"\n=== H79 52WH Proximity Cross-Section ===")
    print(f"Universe: {result['universe_size']} tickers (raw: {result['universe_size_raw']})")
    print(f"\n--- IS ({PARAMETERS['is_start']} → {PARAMETERS['is_end']}) ---")
    print(f"Sharpe:        {is_r['sharpe']:.4f}")
    print(f"Max Drawdown:  {is_r['max_drawdown']:.2%}")
    print(f"Total Return:  {is_r['total_return']:.2%}")
    print(f"Trade Count:   {is_r['trade_count']}")
    print(f"Win Rate:      {is_r['win_rate']:.2%}")
    print(f"\n--- OOS ({PARAMETERS['oos_start']} → {PARAMETERS['oos_end']}) ---")
    print(f"Sharpe:        {oos_r['sharpe']:.4f}")
    print(f"Max Drawdown:  {oos_r['max_drawdown']:.2%}")
    print(f"Total Return:  {oos_r['total_return']:.2%}")
    print(f"Trade Count:   {oos_r['trade_count']}")
    print(f"Win Rate:      {oos_r['win_rate']:.2%}")
