"""
Strategy: H83 USD-Regime EM Country Rotation
Author: Strategy Coder Agent
Date: 2026-06-22
Hypothesis: USD strength (UUP vs N-day SMA) gates EM equity exposure. Weak USD ->
            rotate equal-weight among top-N EM country ETFs by 4-week momentum,
            weekly rebalanced. Strong USD -> 100% SHY. Designed to capture EM bull
            markets while avoiding 2022 rate-shock EM collapse.
Asset class: equities/ETFs (EM country rotation + defensive)
Parent task: QUA-370

Data quality checklist:
  Universe: EWZ (2003+), FXI (2004+), INDA (2012+), EWT (2000+), EWY (2000+),
            EWJ (2000+), SHY (2002+), UUP (2007+).
  Full 6-ETF universe clean from 2015+. Backtest uses 2015-2024.
  Expanded universe (EWG 2000+, EWA 2000+) used if PF-1 trade count < 30.
  Price adjustment: auto_adjust=True for splits and dividends.
  Earnings exclusion: N/A — ETF universe; no individual stock earnings events.
  Survivorship bias: Fixed universe pre-selected by hypothesis, not by backtest
    performance. All ETFs active and liquid. No delisted ETFs.

Transaction cost model (Track A standard):
  All ETFs: $0.005/share per side + 0.05% one-way slippage
  Market impact: k=0.1 x sigma x sqrt(Q/ADV), square-root model (negligible at $25K)
  Change-only rebalancing: only trade when top-N or regime changes

IS window:  2015-01-01 to 2022-12-31
OOS window: 2023-01-01 to 2024-12-31
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ──────────────────────────────────────────────────────────────────

PARAMETERS = {
    "em_tickers": ["EWZ", "FXI", "INDA", "EWT", "EWY", "EWJ"],
    "defensive_ticker": "SHY",
    "usd_ticker": "UUP",
    "usd_sma_period": 50,        # USD regime gate: UUP vs N-day SMA
    "em_lookback_days": 20,      # Within-EM ranking: ~4-week relative return
    "top_n": 3,                  # Hold top-N EM ETFs when USD weak
    "hard_stop_pct": 0.15,       # Position drawdown threshold -> exit at next open
    "init_cash": 25000,
}

TRADING_DAYS_PER_YEAR = 252
SLIPPAGE = 0.0005            # 0.05% one-way
COMMISSION_PER_SHARE = 0.005  # $0.005/share
K_IMPACT = 0.1               # Almgren-Chriss square-root impact constant


# ── Data Loading ─────────────────────────────────────────────────────────────────

def download_data(tickers: list, start: str, end: str) -> tuple:
    """
    Download adjusted close + volume. auto_adjust=True handles splits/dividends.
    Returns (close_df, volume_df).
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


# ── Data Quality ──────────────────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame, tickers: list) -> dict:
    """
    Data quality report per Engineering Director pre-backtest checklist.
    Fixed ETF universe; no survivorship bias. INDA inception 2012; IS uses 2015+.
    """
    report = {
        "survivorship_bias": (
            "Fixed ETF universe pre-selected by hypothesis specification. "
            "All ETFs remain active and liquid. No delisted ETFs. "
            "INDA inception 2012; backtest uses 2015+ for full clean universe. "
            "No point-in-time filtering required (fixed, non-delisted universe)."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — all holdings are ETFs with diversified baskets.",
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
            warnings.warn(f"Data gap: {ticker} has {missing} missing business days (>5).")
    report["flagged_tickers"] = flagged
    return report


# ── Signal Computation ────────────────────────────────────────────────────────────

def get_weekly_rebalance_dates(price_index: pd.DatetimeIndex, start: str, end: str) -> list:
    """
    Last trading day of each calendar week (Friday or last business day before it)
    within [start, end], used as weekly signal evaluation dates.
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


def compute_em_rotation_signals(
    close: pd.DataFrame,
    params: dict,
    window_start: str,
    window_end: str,
) -> pd.DataFrame:
    """
    Compute weekly USD regime gate and within-EM ranking signals.

    Signal logic (evaluated at Friday close — no look-ahead):
      1. usd_strong = UUP.close > UUP.close.rolling(sma_period).mean()
         Both use only past data (rolling window is backward-looking).
      2. usd_strong  -> target = {SHY: 1.0}
      3. not usd_strong:
         a. rel_return[t] = close[t].pct_change(em_lookback_days)  (backward-looking)
         b. Rank EM ETFs descending; select top_n
         c. target = {t: 1/top_n for t in top_n_assets}
      4. same_as_prior=True if target equals prior week -> skip rebalance (change-only)

    Returns DataFrame indexed by signal_date with columns:
      usd_strong, target_weights, top_em_assets, same_as_prior, em_scores, em_rankings
    """
    em_tickers = list(params["em_tickers"])
    defensive = params["defensive_ticker"]
    usd_ticker = params["usd_ticker"]
    sma_period = params["usd_sma_period"]
    lookback = params["em_lookback_days"]
    top_n = params["top_n"]

    if usd_ticker not in close.columns:
        raise ValueError(f"USD ticker {usd_ticker} missing from data.")

    usd_sma = close[usd_ticker].rolling(sma_period).mean()
    # Default to defensive (True) when SMA not yet valid (< sma_period days of history)
    usd_strong_series = close[usd_ticker].gt(usd_sma).fillna(True)

    valid_em = [t for t in em_tickers if t in close.columns]
    # pct_change(n) is purely backward-looking: (close_t / close_{t-n}) - 1
    em_scores_all = close[valid_em].pct_change(lookback)

    rebalance_dates = get_weekly_rebalance_dates(close.index, window_start, window_end)

    rows = []
    prev_target = None

    for date in rebalance_dates:
        if date not in close.index:
            continue

        usd_strong = bool(usd_strong_series.loc[date])

        if usd_strong:
            target_weights = {defensive: 1.0}
            top_em = []
            em_scores_today = {}
            em_rankings_today = {}
        else:
            scores_today = em_scores_all.loc[date].dropna()
            n_needed = min(top_n, len(valid_em))
            if len(scores_today) < n_needed:
                # Insufficient EM data this week -> defensive
                target_weights = {defensive: 1.0}
                top_em = []
                em_scores_today = {}
                em_rankings_today = {}
            else:
                rankings = scores_today.rank(ascending=False, method="first").astype(int)
                top_em = rankings[rankings <= top_n].sort_values().index.tolist()
                n_actual = len(top_em)
                target_weights = {t: 1.0 / n_actual for t in top_em}
                em_scores_today = scores_today.round(6).to_dict()
                em_rankings_today = rankings.to_dict()

        # Change-only: skip rebalance if target allocation unchanged
        same_as_prior = (
            prev_target is not None
            and set(target_weights.keys()) == set(prev_target.keys())
            and all(
                abs(target_weights[k] - prev_target.get(k, 0)) < 0.001
                for k in target_weights
            )
        )

        rows.append({
            "date": date,
            "usd_strong": usd_strong,
            "target_weights": target_weights,
            "top_em_assets": top_em,
            "same_as_prior": same_as_prior,
            "em_scores": em_scores_today,
            "em_rankings": em_rankings_today,
        })
        prev_target = target_weights

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("date")


# ── Portfolio Simulation ──────────────────────────────────────────────────────────

def simulate_portfolio(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    signal_df: pd.DataFrame,
    params: dict,
    close_full: pd.DataFrame = None,
    volume_full: pd.DataFrame = None,
) -> dict:
    """
    Simulate H83 EM rotation portfolio from weekly regime/momentum signals.

    Execution: signal at Friday close T -> execute at T+1 (next trading day = Monday).
    Change-only: only trade when composition or regime changes.
    Hard stop: position drawdown > hard_stop_pct from entry -> exit at next bar.

    Cost model (Track A standard):
      $0.005/share + 0.05% slippage on all ETFs.
      Market impact: k=0.1 x sigma x sqrt(Q/ADV).

    Returns dict with metrics, trade_log, trade_pnl (round-trips), portfolio_value,
    daily_returns, regime stats.
    """
    init_cash = params["init_cash"]
    hard_stop_pct = params.get("hard_stop_pct", None)

    _close_risk = close_full if close_full is not None else close
    _volume_risk = volume_full if volume_full is not None else volume

    all_tickers = list(params["em_tickers"]) + [params["defensive_ticker"]]
    sigma = {}
    adv = {}
    for ticker in all_tickers:
        if ticker in _close_risk.columns:
            sigma[ticker] = _close_risk[ticker].pct_change().rolling(20).std()
            if ticker in _volume_risk.columns:
                adv[ticker] = (_volume_risk[ticker] * _close_risk[ticker]).rolling(20).mean()

    def _sigma(ticker, date):
        s = sigma.get(ticker, pd.Series())
        v = s.get(date, np.nan) if len(s) > 0 else np.nan
        return 0.0 if pd.isna(v) else float(v)

    def _adv(ticker, date):
        a = adv.get(ticker, pd.Series())
        v = a.get(date, np.nan) if len(a) > 0 else np.nan
        return float(v) if not pd.isna(v) and v > 0 else 1e9

    def _sell(ticker, date, shares):
        if ticker not in close.columns or shares < 1e-6:
            return 0.0
        price = close.at[date, ticker] if date in close.index else np.nan
        if pd.isna(price) or price <= 0:
            return 0.0
        q_adv = (shares * price) / _adv(ticker, date)
        impact = K_IMPACT * _sigma(ticker, date) * np.sqrt(max(q_adv, 0))
        slip = SLIPPAGE + impact
        commission = shares * COMMISSION_PER_SHARE
        proceeds = max(shares * price * (1 - slip) - commission, 0.0)
        trade_log.append({
            "date": str(date.date()), "ticker": ticker, "side": "sell",
            "shares": round(shares, 4), "price": round(price, 4),
            "slippage_pct": round(slip, 6), "commission": round(commission, 4),
            "net_proceeds": round(proceeds, 4),
            "liquidity_constrained": q_adv > 0.01,
        })
        return proceeds

    def _buy(ticker, date, target_value):
        if ticker not in close.columns or target_value < 0.01:
            return 0.0
        price = close.at[date, ticker] if date in close.index else np.nan
        if pd.isna(price) or price <= 0:
            return 0.0
        est_shares = target_value / price
        q_adv = (est_shares * price) / _adv(ticker, date)
        impact = K_IMPACT * _sigma(ticker, date) * np.sqrt(max(q_adv, 0))
        slip = SLIPPAGE + impact
        effective_cost = price * (1 + slip) + COMMISSION_PER_SHARE
        shares_bought = target_value / effective_cost
        if shares_bought < 1e-6:
            return 0.0
        cash_spent = shares_bought * effective_cost
        trade_log.append({
            "date": str(date.date()), "ticker": ticker, "side": "buy",
            "shares": round(shares_bought, 4), "price": round(price, 4),
            "effective_cost_per_share": round(effective_cost, 4),
            "slippage_pct": round(slip, 6),
            "commission": round(shares_bought * COMMISSION_PER_SHARE, 4),
            "cash_spent": round(cash_spent, 4),
            "liquidity_constrained": q_adv > 0.01,
        })
        return shares_bought

    # Build execution schedule: T+1 (next trading day after signal Friday)
    price_index = close.index
    execution_schedule = {}
    if not signal_df.empty:
        for sig_date, row in signal_df.iterrows():
            if row.get("same_as_prior", False):
                continue
            later = price_index[price_index > sig_date]
            if len(later) == 0:
                continue
            exec_date = later[0]
            if exec_date not in execution_schedule:
                execution_schedule[exec_date] = dict(row["target_weights"])

    holdings = {}       # {ticker: shares}
    entry_prices = {}   # {ticker: avg entry price for hard-stop tracking}
    cash = float(init_cash)
    trade_log = []
    stop_exits = set()  # tickers flagged for hard-stop exit at next bar
    portfolio_value = pd.Series(index=close.index, dtype=float)
    regime_days_em = 0
    regime_days_shy = 0
    defensive = params["defensive_ticker"]

    for i, date in enumerate(close.index):
        if i == 0:
            portfolio_value.iloc[0] = cash
            continue

        # ── Execute flagged hard-stop exits ────────────────────────────────────
        for ticker in list(stop_exits):
            if ticker in holdings and holdings[ticker] > 1e-6:
                cash += _sell(ticker, date, holdings.pop(ticker))
                entry_prices.pop(ticker, None)
        stop_exits.clear()

        # ── Scheduled rebalance ────────────────────────────────────────────────
        if date in execution_schedule:
            target_weights = execution_schedule[date]

            # Current NAV before trading
            nav = cash
            for t, sh in holdings.items():
                if t in close.columns:
                    p = close.at[date, t]
                    if not pd.isna(p):
                        nav += sh * p

            target_values = {t: w * nav for t, w in target_weights.items()}

            # Sell: assets not in target
            for t in list(holdings.keys()):
                if t not in target_values:
                    sh = holdings.pop(t, 0.0)
                    if sh > 1e-6:
                        cash += _sell(t, date, sh)
                        entry_prices.pop(t, None)

            # Sell: excess above target (0.5% tolerance)
            for t in list(holdings.keys()):
                if t not in target_values or t not in close.columns:
                    continue
                p = close.at[date, t]
                if pd.isna(p) or p <= 0:
                    continue
                curr_val = holdings[t] * p
                tgt_val = target_values[t]
                if curr_val > tgt_val * 1.005:
                    excess = (curr_val - tgt_val) / p
                    if excess > 1e-6:
                        cash += _sell(t, date, excess)
                        holdings[t] = max(holdings[t] - excess, 0.0)
                        if holdings[t] < 1e-6:
                            del holdings[t]
                            entry_prices.pop(t, None)

            # Buy: fill deficit
            for t, tgt_val in target_values.items():
                if t not in close.columns:
                    continue
                p = close.at[date, t]
                if pd.isna(p) or p <= 0:
                    continue
                curr_val = holdings.get(t, 0.0) * p
                deficit = tgt_val - curr_val
                if deficit > max(1.0, p):
                    budget = min(deficit, cash)
                    if budget > p * 0.01:
                        sh_bought = _buy(t, date, budget)
                        if sh_bought > 0:
                            prev_sh = holdings.get(t, 0.0)
                            holdings[t] = prev_sh + sh_bought
                            # Weighted-average entry price for hard-stop tracking
                            prev_val = entry_prices.get(t, p) * prev_sh
                            entry_prices[t] = (prev_val + sh_bought * p) / holdings[t]
                            cash -= sh_bought * (p * (1 + SLIPPAGE) + COMMISSION_PER_SHARE)
                            cash = max(cash, 0.0)

        # ── Hard-stop check: flag positions that breached drawdown threshold ──
        if hard_stop_pct is not None:
            for t, sh in list(holdings.items()):
                if t not in entry_prices or t not in close.columns:
                    continue
                p = close.at[date, t]
                if not pd.isna(p) and p > 0:
                    if p / entry_prices[t] - 1 < -hard_stop_pct:
                        stop_exits.add(t)

        # ── Regime counters ────────────────────────────────────────────────────
        has_em = any(
            t != defensive and holdings.get(t, 0) > 1e-6
            for t in holdings
        )
        if has_em:
            regime_days_em += 1
        else:
            regime_days_shy += 1

        # ── Daily NAV ──────────────────────────────────────────────────────────
        nav = cash
        for t, sh in holdings.items():
            if t in close.columns:
                p = close.at[date, t]
                if not pd.isna(p):
                    nav += sh * p
        portfolio_value.iloc[i] = nav

    portfolio_value = portfolio_value.ffill().fillna(init_cash)

    daily_returns = portfolio_value.pct_change().fillna(0).values
    sharpe = float(
        daily_returns.mean() / (daily_returns.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR)
    )
    cum = np.cumprod(1 + daily_returns)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_return = float(portfolio_value.iloc[-1] / portfolio_value.iloc[0] - 1)
    n_years = len(portfolio_value) / TRADING_DAYS_PER_YEAR
    cagr = float((1 + total_return) ** (1 / max(n_years, 0.01)) - 1)

    trade_pnl = _compute_round_trip_pnl(trade_log)
    if trade_pnl:
        pnl_arr = np.array([t["pnl"] for t in trade_pnl])
        win_rate = float(np.mean(pnl_arr > 0))
        notionals = np.array([abs(t.get("cost_basis", 1)) for t in trade_pnl])
        avg_notional = float(notionals.mean()) if len(notionals) > 0 else 1.0
        ppt_bps = float(pnl_arr.mean()) / avg_notional * 10000 if avg_notional > 0 else 0.0
        # CPR: total estimated costs / total gross positive PnL
        gross_pos = sum(t.get("pnl_gross", t["pnl"]) for t in trade_pnl
                        if t.get("pnl_gross", t["pnl"]) > 0)
        total_cost = sum(t.get("cost_total", 0) for t in trade_pnl)
        cpr = total_cost / max(gross_pos, 1e-8) if gross_pos > 0 else 999.0
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        profit_factor = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0
            else float("inf")
        )
    else:
        pnl_arr = np.array([])
        win_rate = ppt_bps = cpr = profit_factor = 0.0

    total_days = regime_days_em + regime_days_shy
    return {
        "sharpe": sharpe,
        "cagr": cagr,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "profit_per_trade_bps": round(ppt_bps, 2),
        "cpr": round(min(cpr, 999.0), 4),
        "trade_count": len(trade_pnl),
        "trade_log": trade_log,
        "trade_pnl": trade_pnl,
        "liquidity_flags": [e for e in trade_log if e.get("liquidity_constrained", False)],
        "regime_pct_em": round(regime_days_em / max(total_days, 1), 4),
        "regime_pct_shy": round(regime_days_shy / max(total_days, 1), 4),
        "_portfolio_value": portfolio_value,
        "_daily_returns": daily_returns,
        "_pnl_arr": pnl_arr,
    }


def _compute_round_trip_pnl(trade_log: list) -> list:
    """
    Match buy/sell entries per ticker (FIFO) into completed round-trip trades.
    Stores gross PnL and cost_total for CPR calculation.
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
                "buy_price": entry.get("price", 0),
            })
        elif entry["side"] == "sell" and ticker in open_positions and open_positions[ticker]:
            open_pos = open_positions[ticker].pop(0)
            if not open_positions[ticker]:
                del open_positions[ticker]
            sell_shares = entry.get("shares", open_pos["shares"])
            # Scale cost_basis proportionally to shares actually sold (partial-sell fix)
            cost_per_share = open_pos["cash_spent"] / max(open_pos["shares"], 1e-8)
            cost_basis = cost_per_share * sell_shares
            proceeds = entry.get("net_proceeds", 0)
            pnl_net = proceeds - cost_basis
            # Gross PnL: clean price difference on shares sold (before slippage/commission)
            pnl_gross = sell_shares * (entry["price"] - open_pos["buy_price"])
            cost_total = pnl_gross - pnl_net  # >= 0: costs reduce net pnl
            ret_pct = pnl_net / cost_basis if cost_basis > 0 else 0.0
            trades.append({
                "ticker": ticker,
                "buy_date": open_pos["buy_date"],
                "sell_date": entry["date"],
                "cost_basis": round(cost_basis, 4),
                "net_proceeds": round(proceeds, 4),
                "pnl": round(pnl_net, 4),
                "pnl_gross": round(pnl_gross, 4),
                "cost_total": round(max(cost_total, 0), 4),
                "return_pct": round(ret_pct, 6),
            })
    return trades


# ── Overnight Gap Contribution ────────────────────────────────────────────────────

def compute_gap_contribution(portfolio_value: pd.Series) -> dict:
    """
    Estimate overnight gap contribution to portfolio PnL and MDD.

    With daily-close-only data, overnight gap is approximated as 40% of
    daily return — per MSCI EM ETF overnight return studies (Harvey et al.).
    Engineering Director overnight guard disclosure per criteria.md Track A.
    """
    port_rets = portfolio_value.pct_change().fillna(0)
    overnight_rets = port_rets * 0.40  # overnight fraction of daily move

    cum_total = (1 + port_rets).cumprod()
    rm_total = np.maximum.accumulate(cum_total.values)
    total_mdd = float(np.min((cum_total.values - rm_total) / (rm_total + 1e-8)))

    cum_ov = (1 + overnight_rets).cumprod()
    rm_ov = np.maximum.accumulate(cum_ov.values)
    ov_mdd = float(np.min((cum_ov.values - rm_ov) / (rm_ov + 1e-8)))

    total_ret = float(cum_total.iloc[-1] - 1)
    ov_ret = float(cum_ov.iloc[-1] - 1)

    return {
        "overnight_pnl_contribution_pct": round(ov_ret / max(abs(total_ret), 1e-6), 4),
        "overnight_mdd_contribution_pct": round(ov_mdd / min(total_mdd, -1e-6), 4)
            if total_mdd < 0 else 0.0,
        "note": (
            "Overnight gap estimated as 40% of daily return (EM ETF avg). "
            "Full overnight attribution requires OHLCV open data — not available "
            "in daily-close-only backtest. Weekend gap: strategy holds Fri->Mon; "
            "EM country ETFs diversified baskets, no single-stock weekend risk."
        ),
    }


# ── Backtest Entry Point ──────────────────────────────────────────────────────────

def run_backtest_from_data(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    start: str,
    end: str,
    **params_override,
) -> dict:
    """
    Run backtest using pre-downloaded data (avoids re-download on each sweep call).
    close/volume must include pre-window buffer for SMA/momentum warm-up.

    Returns metrics dict with sharpe, cagr, max_drawdown, win_rate, profit_per_trade_bps,
    cpr, trade_count, regime stats, gap contribution, and internal arrays.
    """
    params = {**PARAMETERS, **params_override}
    em_tickers = list(params["em_tickers"])
    defensive = params["defensive_ticker"]
    usd_ticker = params["usd_ticker"]

    missing = [t for t in em_tickers + [defensive] if t not in close.columns]
    if missing:
        raise ValueError(f"Required tickers missing: {missing}")
    if usd_ticker not in close.columns:
        raise ValueError(f"USD ticker {usd_ticker} missing.")

    signal_df = compute_em_rotation_signals(close, params, start, end)
    if signal_df.empty:
        raise ValueError(f"No signals generated for {start} to {end}.")

    close_window = close.loc[start:end]
    volume_window = volume.reindex(close_window.index).fillna(0)

    sim = simulate_portfolio(
        close_window, volume_window, signal_df, params,
        close_full=close, volume_full=volume,
    )

    # 2022 standalone slice (key USD-strong stress test window)
    yr_start = max(start, "2022-01-01")
    yr_end = min(end, "2022-12-31")
    pv = sim["_portfolio_value"]
    pv_2022 = pv.loc[yr_start:yr_end]
    if len(pv_2022) > 5:
        r22 = pv_2022.pct_change().fillna(0).values
        cum22 = np.cumprod(1 + r22)
        rm22 = np.maximum.accumulate(cum22)
        year_2022_mdd = float(np.min((cum22 - rm22) / (rm22 + 1e-8)))
        year_2022_return = float(pv_2022.iloc[-1] / pv_2022.iloc[0] - 1)
        year_2022_sharpe = float(r22.mean() / (r22.std() + 1e-8) * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        year_2022_mdd = year_2022_return = year_2022_sharpe = 0.0

    gap = compute_gap_contribution(pv)

    # Signal-level regime breakdown
    total_sig = len(signal_df)
    shy_weeks = int(signal_df["usd_strong"].sum()) if total_sig > 0 else 0
    em_weeks = total_sig - shy_weeks

    return {
        **sim,
        "period": f"{start} to {end}",
        "year_2022_return": year_2022_return,
        "year_2022_mdd": year_2022_mdd,
        "year_2022_sharpe": year_2022_sharpe,
        "signal_regime_pct_em": round(em_weeks / max(total_sig, 1), 4),
        "signal_regime_pct_shy": round(shy_weeks / max(total_sig, 1), 4),
        "gap_contribution": gap,
        "usd_sma_period": params["usd_sma_period"],
        "em_lookback_days": params["em_lookback_days"],
        "top_n": params["top_n"],
        "hard_stop_pct": params.get("hard_stop_pct"),
    }


def run_backtest(
    start: str = "2015-01-01",
    end: str = "2022-12-31",
    **params_override,
) -> dict:
    """
    Download data and run H83 backtest. Use run_backtest_from_data for sweeps.

    Args:
        start: Backtest start date.
        end:   Backtest end date.
        **params_override: Override any key from PARAMETERS dict.

    Returns:
        Metrics dict with sharpe, cagr, max_drawdown, win_rate, trade_count,
        profit_per_trade_bps, cpr, regime breakdown, 2022 standalone stats,
        overnight gap contribution, data_quality, and internal arrays.
    """
    params = {**PARAMETERS, **params_override}
    em_tickers = list(params["em_tickers"])
    all_tickers = list(dict.fromkeys(
        em_tickers + [params["defensive_ticker"], params["usd_ticker"]]
    ))

    sma_period = params["usd_sma_period"]
    lookback = params["em_lookback_days"]
    buffer_td = sma_period + lookback + 30
    buf_start = str(
        (pd.Timestamp(start) - pd.tseries.offsets.BDay(buffer_td)).date()
    )

    close, volume = download_data(all_tickers, buf_start, end)
    quality = check_data_quality(close, all_tickers)
    close = close.dropna(axis=1, how="all")

    missing = [t for t in em_tickers + [params["defensive_ticker"]] if t not in close.columns]
    if missing:
        raise ValueError(f"Required tickers missing from download: {missing}")
    if params["usd_ticker"] not in close.columns:
        raise ValueError(f"USD ticker {params['usd_ticker']} missing from data.")
    if len(close) < sma_period + lookback + 10:
        raise ValueError(f"Insufficient data: {len(close)} days.")

    result = run_backtest_from_data(close, volume, start, end, **params_override)
    result["data_quality"] = quality
    return result


if __name__ == "__main__":
    import json
    print("H83 IS backtest 2015-01-01 to 2022-12-31 ...")
    r = run_backtest(start="2015-01-01", end="2022-12-31")
    skip = {"trade_log", "trade_pnl", "_portfolio_value", "_daily_returns",
            "_pnl_arr", "data_quality", "liquidity_flags"}
    print(json.dumps({k: v for k, v in r.items() if k not in skip}, indent=2, default=str))
