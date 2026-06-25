"""
Strategy: H45v2 NR7 Sector ETF Universe Expansion
Author: Strategy Coder Agent
Date: 2026-06-25
Hypothesis: H45v2 expands NR7 volatility compression breakout from 3 broad ETFs
            (SPY/QQQ/IWM) to 15 sector/commodity/bond ETFs. Signal logic, parameters,
            and exit rules are identical to H45. Universe expansion fixes the H45
            trade-count floor failure (5.5/qtr → ~31.5/qtr estimated).
Asset class: US equity/commodity/bond sector ETFs
"""

import numpy as np
import pandas as pd
import yfinance as yf

# ED-SLIP-001: ultra-liquid tier — ADV > $5B/day (SPY/QQQ/IWM/GLD/TLT) → 0.005% slippage
ULTRA_LIQUID_TICKERS = {"SPY", "QQQ", "IWM", "GLD", "TLT"}

PARAMETERS = {
    "tickers": [
        "SPY", "QQQ", "IWM",
        "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLB", "XLU",
        "GLD", "TLT", "SLV",
        "XLRE", "XLC",   # partial IS coverage — handled as NaN/no-signal before inception
    ],
    "nr7_lookback": 7,           # Crabel canonical — DO NOT change; definitional
    "trend_ma": 200,             # per-ETF 200-DMA trend filter (applied independently)
    "hold_days": 5,              # holding period in trading days
    "atr_period": 14,            # ATR window for stop calculation
    "atr_stop_mult": 2.0,        # stop = entry - mult * ATR(14)
    "max_positions": 5,          # max concurrent positions
    "position_size_pct": 0.20,   # 20% of portfolio per position (equal weight)
    "init_cash": 100_000,
    "is_start": "2005-01-01",
    "is_end": "2018-12-31",
    "oos_start": "2019-01-01",
    "oos_end": "2026-06-25",
    # Transaction costs per ED-SLIP-001 authoritative model
    "fixed_cost_per_share": 0.005,         # both sides
    "slippage_pct_ultra": 0.00005,         # 0.005% — SPY, QQQ, IWM
    "slippage_pct_std": 0.0005,            # 0.05%  — all other ETFs
    "market_impact_k": 0.1,                # Almgren-Chriss square-root model
}

TRADING_DAYS_PER_YEAR = 252


def download_data(tickers: list, start: str, end: str) -> dict:
    """
    Download adjusted OHLCV for all tickers with indicator warmup extension.
    Returns dict[ticker -> DataFrame]. Tickers with no data (pre-inception) are
    excluded from the dict; callers handle missing tickers as no-signal.
    """
    extended_start = (pd.Timestamp(start) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
    raw = yf.download(tickers, start=extended_start, end=end,
                      auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns.names = ["field", "ticker"]

    result = {}
    for t in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if t not in raw.columns.get_level_values("ticker"):
                    print(f"  WARN: {t} not in download result — skipping")
                    continue
                df = raw.xs(t, axis=1, level="ticker").dropna(how="all")
            else:
                df = raw.copy()

            df.columns = [c.strip() for c in df.columns]

            if len(df) == 0:
                print(f"  WARN: {t} — zero rows after dropna; skipping")
                continue

            if len(df) > 1:
                gaps = pd.Series(df.index).diff().dt.days
                large = gaps[gaps > 7]
                if len(large) > 0:
                    print(f"  DATA WARN: {t} — {len(large)} gap(s) > 5 trading days")

            result[t] = df
        except Exception as exc:
            print(f"  ERROR downloading {t}: {exc}")

    return result


def compute_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Compute True Range, NR7, ATR(14), 200-SMA, and market impact inputs.
    All series use only data available at or before each date (no look-ahead).
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    prev_close = close.shift(1)

    tr = (pd.concat([high, prev_close], axis=1).max(axis=1) -
          pd.concat([low, prev_close], axis=1).min(axis=1))

    tr_min7 = tr.rolling(params["nr7_lookback"]).min()
    nr7 = (tr == tr_min7) & tr_min7.notna() & (tr > 0)

    atr = tr.rolling(params["atr_period"]).mean()
    sma200 = close.rolling(params["trend_ma"]).mean()

    sigma = close.pct_change().rolling(20).std()
    adv_dollar = (volume * close).rolling(20).mean()

    return pd.DataFrame({
        "open": df["Open"],
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "tr": tr,
        "nr7": nr7,
        "atr": atr,
        "sma200": sma200,
        "sigma": sigma,
        "adv_dollar": adv_dollar,
    })


def _one_way_cost(ticker: str, shares: float, price: float, sigma: float,
                  adv_dollar: float, params: dict) -> float:
    """Dollar cost for one side of a trade using per-ticker slippage tier."""
    fixed = shares * params["fixed_cost_per_share"]

    if ticker in ULTRA_LIQUID_TICKERS:
        slip_pct = params.get("slippage_pct_ultra", 0.00005)
    else:
        slip_pct = params.get("slippage_pct_std", 0.0005)
    slip = shares * price * slip_pct

    if adv_dollar > 0 and not np.isnan(sigma) and sigma > 0:
        q_dollar = shares * price
        impact_pct = params["market_impact_k"] * sigma * np.sqrt(q_dollar / adv_dollar)
        impact = shares * price * impact_pct
    else:
        impact = 0.0

    return fixed + slip + impact


def simulate(indicator_dict: dict, params: dict, start: str, end: str) -> dict:
    """
    Event-driven daily simulation across the 15-ETF universe.

    Uses SPY's trading calendar as the master date index. Tickers with partial
    history (SLV, XLRE, XLC) are skipped for signal generation on dates where
    their data is NaN — no look-ahead, no survivorship bias.

    Entry logic:
      - NR7 signal at close of day S (per ETF independently)
      - Entry at open of day S+1 only if Open[S+1] > High[S] (breakout confirm)
      - Max 5 concurrent positions; if full, signal expires (deleted next day)
      - Tiebreaker: alphabetical by ticker

    Exit logic (first trigger wins):
      1. Trend break: prior close < 200-SMA → exit at today's open
      2. Stop loss: Low <= stop_price → exit at min(open, stop_price)
      3. Time exit: close of (entry_day + hold_days - 1)
    """
    tickers = params["tickers"]
    init_cash = float(params["init_cash"])
    max_pos = params["max_positions"]
    hold_days = params["hold_days"]
    pos_size_pct = params.get("position_size_pct", 0.20)

    # SPY as master calendar; SPY has full coverage across IS and OOS periods
    calendar_ticker = "SPY"
    if calendar_ticker not in indicator_dict:
        calendar_ticker = next(iter(indicator_dict))

    cal_dates = indicator_dict[calendar_ticker].loc[start:end].index
    if len(cal_dates) < hold_days + 5:
        return {
            "equity": pd.Series(init_cash, index=cal_dates),
            "trades": [],
            "total_cost": 0.0,
        }

    common_dates = cal_dates

    # Reindex each ticker to master calendar (NaN where ticker has no data)
    inds = {}
    for t in tickers:
        if t in indicator_dict:
            inds[t] = indicator_dict[t].reindex(common_dates)

    available_tickers = sorted(inds.keys())  # alphabetical for deterministic tie-breaking

    cash = init_cash
    equity_arr = np.full(len(common_dates), np.nan)
    equity_arr[0] = cash
    open_pos = {}    # ticker -> position dict
    pending = {}     # ticker -> (signal_idx, nr7_high, atr_at_signal)
    trades = []
    total_cost = 0.0

    for d in range(len(common_dates)):
        date = common_dates[d]

        # ── Step 1: Process exits ──────────────────────────────────────────────
        exited = []
        for ticker, pos in open_pos.items():
            ind = inds[ticker]
            open_v = ind["open"].iloc[d]
            low_v = ind["low"].iloc[d]
            close_v = ind["close"].iloc[d]
            sma200_v = ind["sma200"].iloc[d]
            sigma_v = float(ind["sigma"].iloc[d]) if not pd.isna(ind["sigma"].iloc[d]) else 0.01
            adv_v = float(ind["adv_dollar"].iloc[d]) if not pd.isna(ind["adv_dollar"].iloc[d]) else 1e9

            exit_type = None
            exit_price = None

            if pos["trend_break_pending"] and not pd.isna(open_v):
                exit_type = "trend_break"
                exit_price = float(open_v)
            elif not pd.isna(low_v) and float(low_v) <= pos["stop_price"]:
                open_f = float(open_v) if not pd.isna(open_v) else pos["stop_price"]
                exit_price = open_f if open_f <= pos["stop_price"] else pos["stop_price"]
                exit_type = "stop"
            elif d >= pos["exit_day"]:
                if not pd.isna(close_v):
                    exit_price = float(close_v)
                    exit_type = "time"

            if exit_type and exit_price is not None:
                shares = pos["shares"]
                exit_cost = _one_way_cost(ticker, shares, exit_price, sigma_v, adv_v, params)
                total_cost += exit_cost
                gross_pnl = shares * (exit_price - pos["entry_price"])
                net_pnl = gross_pnl - pos["entry_cost"] - exit_cost
                cash += shares * exit_price - exit_cost
                trades.append({
                    "ticker": ticker,
                    "entry_date": pos["entry_date"],
                    "exit_date": date,
                    "entry_price": round(pos["entry_price"], 4),
                    "exit_price": round(exit_price, 4),
                    "shares": round(shares, 4),
                    "gross_pnl": round(gross_pnl, 4),
                    "total_cost": round(pos["entry_cost"] + exit_cost, 4),
                    "pnl": round(net_pnl, 4),
                    "exit_type": exit_type,
                    "hold_trading_days": d - pos["entry_idx"],
                    "atr_stop": round(pos["stop_price"], 4),
                    "liquidity_constrained": (adv_v > 0 and (shares * exit_price) / adv_v > 0.01),
                })
                exited.append(ticker)
            else:
                if (not pd.isna(sma200_v) and not pd.isna(close_v) and
                        float(close_v) < float(sma200_v)):
                    open_pos[ticker]["trend_break_pending"] = True

        for t in exited:
            del open_pos[t]

        # ── Step 2: Process pending entries (signal from d-1) ─────────────────
        # Sort alphabetically for deterministic tiebreaking (hypothesis spec)
        stale = []
        for ticker in sorted(pending.keys()):
            sig_idx, nr7_high, atr_sig = pending[ticker]
            if d == sig_idx + 1:
                open_v = inds[ticker]["open"].iloc[d]
                if not pd.isna(open_v) and float(open_v) > nr7_high:
                    if ticker not in open_pos and len(open_pos) < max_pos:
                        mark = sum(
                            p["shares"] * float(inds[t]["close"].iloc[d - 1])
                            for t, p in open_pos.items()
                            if not pd.isna(inds[t]["close"].iloc[d - 1])
                        )
                        port_val = cash + mark
                        pos_val = port_val * pos_size_pct
                        ep = float(open_v)
                        shares = pos_val / ep

                        sigma_e = float(inds[ticker]["sigma"].iloc[d])
                        sigma_e = sigma_e if not pd.isna(sigma_e) else 0.01
                        adv_e = float(inds[ticker]["adv_dollar"].iloc[d])
                        adv_e = adv_e if not pd.isna(adv_e) else 1e9
                        entry_cost = _one_way_cost(ticker, shares, ep, sigma_e, adv_e, params)
                        total_cost += entry_cost

                        q_dollar = shares * ep
                        if adv_e > 0 and q_dollar / adv_e > 0.01:
                            print(f"  LIQUIDITY WARN: {ticker} {date.date()} "
                                  f"Q/ADV={q_dollar / adv_e:.4%} — liquidity_constrained=True")

                        cash -= shares * ep + entry_cost
                        open_pos[ticker] = {
                            "ticker": ticker,
                            "entry_date": date,
                            "entry_idx": d,
                            "entry_price": ep,
                            "shares": shares,
                            "stop_price": ep - params["atr_stop_mult"] * atr_sig,
                            "exit_day": d + hold_days - 1,
                            "entry_cost": entry_cost,
                            "trend_break_pending": False,
                        }
                stale.append(ticker)
            elif d > sig_idx + 1:
                stale.append(ticker)

        for t in stale:
            if t in pending:
                del pending[t]

        # ── Step 3: Detect new NR7 signals at today's close ───────────────────
        for ticker in available_tickers:
            if ticker in open_pos or ticker in pending:
                continue
            ind = inds[ticker]
            close_v = ind["close"].iloc[d]
            nr7_v = ind["nr7"].iloc[d]
            if pd.isna(close_v) or pd.isna(nr7_v):
                continue  # ticker has no data on this date (pre-inception)
            sma200_v = ind["sma200"].iloc[d]
            atr_v = ind["atr"].iloc[d]
            trend_ok = (not pd.isna(sma200_v) and float(close_v) > float(sma200_v))
            if bool(nr7_v) and trend_ok and not pd.isna(atr_v):
                pending[ticker] = (d, float(ind["high"].iloc[d]), float(atr_v))

        # ── Step 4: Mark to market at close ───────────────────────────────────
        mark = sum(
            p["shares"] * float(inds[t]["close"].iloc[d])
            for t, p in open_pos.items()
            if not pd.isna(inds[t]["close"].iloc[d])
        )
        equity_arr[d] = cash + mark

    equity = pd.Series(equity_arr, index=common_dates)
    equity = equity.ffill().fillna(init_cash)
    return {"equity": equity, "trades": trades, "total_cost": total_cost}


def compute_metrics(equity: pd.Series, trades: list, total_cost: float,
                    init_cash: float) -> dict:
    """Compute strategy performance metrics from equity curve and trade log."""
    ret = equity.pct_change().fillna(0.0)
    n = len(ret)

    sharpe = (float(ret.mean() / ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
              if n > 2 and ret.std() > 0 else 0.0)

    cum = equity.values / (equity.values[0] + 1e-12)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1) if n > 1 else 0.0

    trade_count = len(trades)
    if trade_count > 0:
        net_pnls = [t["pnl"] for t in trades]
        gross_pnls = [t["gross_pnl"] for t in trades]
        winners = [p for p in net_pnls if p > 0]
        win_rate = len(winners) / trade_count

        # PpT: profit per trade relative to 20%-of-portfolio position size
        avg_pos_val = init_cash * 0.20
        ppt_bps = float(np.mean(net_pnls)) / avg_pos_val * 10_000

        gross_profit = sum(g for g in gross_pnls if g > 0) or 0.0
        cpr = total_cost / gross_profit if gross_profit > 0 else 999.0

        gross_loss = abs(sum(g for g in gross_pnls if g < 0))
        profit_factor = gross_profit / max(gross_loss, 1e-8)
    else:
        win_rate = 0.0
        ppt_bps = 0.0
        cpr = 999.0
        profit_factor = 0.0

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "total_return": round(total_return, 4),
        "win_rate": round(win_rate, 4),
        "ppt_bps": round(ppt_bps, 4),
        "cpr": round(cpr, 4),
        "profit_factor": round(profit_factor, 4),
        "trade_count": trade_count,
        "total_cost": round(total_cost, 2),
    }


def compute_overnight_gap_stats(equity: pd.Series, indicator_dict: dict,
                                trades: list) -> dict:
    """
    Track A Hard Gate 8: overnight gap attribution.

    Universe note: 15 sector/commodity/bond ETFs — no individual stock earnings risk.
    All tickers are ETF baskets or index-tracking funds. Survivorship bias: NONE for
    equity/sector ETFs (all continuously listed from inception). XLRE/XLC contribute
    OOS signals only; inception dates are after IS period ends.
    """
    earnings_policy = (
        "N/A — All 15 tickers are ETFs (sector baskets, commodity ETFs, bond ETF). "
        "No individual earnings risk. ETFs do not report earnings and cannot be halted "
        "for single-stock earnings. 5% per-earnings-position cap is inapplicable by "
        "asset-class definition."
    )
    survivorship_note = (
        "NONE — SPY/QQQ/IWM (1993-2000), SPDR sector ETFs (1998), GLD (2004), TLT (2002), "
        "SLV (2006) all continuously listed. XLRE (2015) and XLC (2018) contribute OOS "
        "signals only; pre-inception NaN handled as no-signal (no data fabrication). "
        "No delisting risk for any ticker in universe."
    )

    if not trades:
        return {
            "overnight_gap_pnl_contribution_pct": 0.0,
            "weekend_gap_exposure_pct": 0.0,
            "gap_mdd_attribution_pct": 0.0,
            "earnings_policy": earnings_policy,
            "survivorship_bias": survivorship_note,
            "earnings_hold_ok": True,
        }

    total_net_pnl = sum(t["pnl"] for t in trades)
    overnight_gap_pnl = 0.0
    weekend_gap_notional = 0.0
    total_notional = 0.0

    for trade in trades:
        ticker = trade["ticker"]
        if ticker not in indicator_dict:
            continue
        ind = indicator_dict[ticker]
        entry_dt = pd.Timestamp(trade["entry_date"])
        exit_dt = pd.Timestamp(trade["exit_date"])
        hold = ind.loc[entry_dt:exit_dt]
        if len(hold) < 2:
            continue
        shares = trade["shares"]
        for i in range(1, len(hold)):
            if pd.isna(hold["open"].iloc[i]) or pd.isna(hold["close"].iloc[i - 1]):
                continue
            gap = float(hold["open"].iloc[i]) - float(hold["close"].iloc[i - 1])
            overnight_gap_pnl += gap * shares
            if (hold.index[i] - hold.index[i - 1]).days > 3:
                weekend_gap_notional += abs(gap * shares)
        total_notional += shares * trade["entry_price"] * len(hold)

    avg_daily_notional = total_notional / max(len(trades), 1)
    overnight_pnl_pct = overnight_gap_pnl / max(abs(total_net_pnl), 1.0) * 100
    weekend_pct = weekend_gap_notional / max(avg_daily_notional, 1.0) * 100

    eq_range = float(equity.max() - equity.min())
    gap_mdd_pct = abs(overnight_gap_pnl) / max(eq_range, 1.0) * 100

    return {
        "overnight_gap_pnl_contribution_pct": round(overnight_pnl_pct, 2),
        "weekend_gap_exposure_pct": round(weekend_pct, 2),
        "gap_mdd_attribution_pct": round(gap_mdd_pct, 2),
        "earnings_policy": earnings_policy,
        "survivorship_bias": survivorship_note,
        "earnings_hold_ok": True,
    }


def run_strategy(params: dict = PARAMETERS) -> dict:
    """Download data, run IS and OOS simulations. Returns full results dict."""
    tickers = params["tickers"]
    print(f"Downloading OHLCV for {len(tickers)} tickers: {tickers[:5]}... +{len(tickers)-5} more")
    raw_data = download_data(tickers, params["is_start"], params["oos_end"])
    available = list(raw_data.keys())
    print(f"  Available tickers: {available}")
    indicator_dict = {t: compute_indicators(raw_data[t], params) for t in available}

    print(f"\nIS:  {params['is_start']} → {params['is_end']}")
    is_res = simulate(indicator_dict, params, params["is_start"], params["is_end"])
    is_m = compute_metrics(is_res["equity"], is_res["trades"], is_res["total_cost"], params["init_cash"])

    print(f"OOS: {params['oos_start']} → {params['oos_end']}")
    oos_res = simulate(indicator_dict, params, params["oos_start"], params["oos_end"])
    oos_m = compute_metrics(oos_res["equity"], oos_res["trades"], oos_res["total_cost"], params["init_cash"])

    gap_stats = compute_overnight_gap_stats(is_res["equity"], indicator_dict, is_res["trades"])

    return {
        "is_sharpe": is_m["sharpe"],
        "is_max_drawdown": is_m["max_drawdown"],
        "is_total_return": is_m["total_return"],
        "is_win_rate": is_m["win_rate"],
        "is_ppt_bps": is_m["ppt_bps"],
        "is_cpr": is_m["cpr"],
        "is_profit_factor": is_m["profit_factor"],
        "is_trade_count": is_m["trade_count"],
        "oos_sharpe": oos_m["sharpe"],
        "oos_max_drawdown": oos_m["max_drawdown"],
        "oos_total_return": oos_m["total_return"],
        "oos_trade_count": oos_m["trade_count"],
        "oos_win_rate": oos_m["win_rate"],
        "is_equity": is_res["equity"],
        "oos_equity": oos_res["equity"],
        "is_trades": is_res["trades"],
        "oos_trades": oos_res["trades"],
        "indicator_dict": indicator_dict,
        "gap_stats": gap_stats,
    }


if __name__ == "__main__":
    r = run_strategy()
    print(f"\nIS  Sharpe={r['is_sharpe']:.3f} | MDD={r['is_max_drawdown']:.2%} | "
          f"Trades={r['is_trade_count']} | PpT={r['is_ppt_bps']:.1f}bps | CPR={r['is_cpr']:.3f}")
    print(f"OOS Sharpe={r['oos_sharpe']:.3f} | MDD={r['oos_max_drawdown']:.2%} | "
          f"Trades={r['oos_trade_count']}")
    g = r["gap_stats"]
    print(f"\nTrack A Hard Gate 8:")
    print(f"  Overnight gap PnL contribution: {g['overnight_gap_pnl_contribution_pct']:.1f}%")
    print(f"  Weekend gap exposure:            {g['weekend_gap_exposure_pct']:.1f}%")
    print(f"  Gap MDD attribution:             {g['gap_mdd_attribution_pct']:.1f}%")
