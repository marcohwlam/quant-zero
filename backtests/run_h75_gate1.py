"""
H75 Gate 1 Backtest Runner — Equity Carry (Dividend Yield Sector Rotation)
IS:  2003-01-01 to 2021-12-31 (~18 years, monthly rebalance)
OOS: 2022-01-01 to 2023-12-31 (~2 years)
Walk-forward: 4 non-overlapping IS windows (~4-5yr each)
Parameter sweep: 18 combos (yield_lookback × top_k × spy_filter)
Parent: QUA-316 | Hypothesis: H75 | Source: Koijen et al. (2018) JFE 127(2)

Signal: Trailing N-month dividend yield per sector ETF, rank descending, hold top-K.
        Regime filter: SPY < 200-DMA → 100% SHY.

Universe: 10 SPDR sector ETFs — XLK, XLY, XLF, XLI, XLV, XLB, XLP, XLE, XLU, XLRE
          XLRE launched Oct 2015. 9-sector universe pre-2015; 10-sector after.

Transaction cost model (canonical AGENTS.md — standard ETF tier):
  Sector ETFs (ADV ~5-30M shares/day): $0.005/share + 0.05% slippage + market impact
  SHY: same as sector ETFs
  Market impact: 0.1 × σ × sqrt(Q/ADV) — Almgren-Chriss square-root model
  Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True
  Note: Sector ETFs ADV << 50M/day → standard tier applies (not ultra-liquid tier ED-SLIP-001)
"""

import sys
import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import date
from itertools import product as iproduct

REPO_ROOT = Path(__file__).parent.parent
TODAY = date.today().isoformat()
STRATEGY_NAME = "H75_EquityCarryDividendYield"
OUT_DIR = REPO_ROOT / "backtests"
TRADING_DAYS = 252

SECTOR_UNIVERSE = ["XLK", "XLY", "XLF", "XLI", "XLV", "XLB", "XLP", "XLE", "XLU", "XLRE"]
XLRE_LAUNCH = pd.Timestamp("2015-10-07")
REGIME_ETF = "SPY"
SAFE_HAVEN = "SHY"
ALL_PRICE_DL = SECTOR_UNIVERSE + [REGIME_ETF, SAFE_HAVEN]

PARAMETERS = {
    "yield_lookback_months": 12,  # trailing months for dividend yield (Koijen 2018 standard)
    "top_k": 3,                   # top-K sectors by yield to hold
    "spy_filter": True,           # SPY < 200-DMA → 100% SHY
    "regime_ma_days": 200,
    "init_capital": 100_000.0,
    "slippage": 0.0005,           # 0.05% standard ETF tier
    "commission_per_share": 0.005,
    "market_impact_k": 0.1,       # Almgren-Chriss
}

IS_START = "2003-01-01"
IS_END = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END = "2023-12-31"
DATA_START = "2001-01-01"  # warmup buffer for 200-DMA + 12M dividend lookback

WF_IS_WINDOWS = [
    ("2003-01-01", "2007-12-31"),
    ("2008-01-01", "2012-12-31"),
    ("2013-01-01", "2017-12-31"),
    ("2018-01-01", "2021-12-31"),
]

SWEEP_LOOKBACKS = [3, 6, 12]
SWEEP_TOP_K = [2, 3, 4]
SWEEP_FILTER = [True, False]


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data(start: str = DATA_START, end: str = OOS_END) -> dict:
    """
    Download price data and historical dividends.

    Returns:
      close:      Total-return adjusted closes (auto_adjust=True) — used for simulation/returns
      close_unadj: Split-adjusted only closes (auto_adjust=False) — used as yield denominator
      open_:      Total-return adjusted opens
      volume:     Daily share volumes
      dividends:  Split-adjusted dividend per share indexed to trading calendar (ex-div dates)
    """
    print(f"H75: downloading {len(ALL_PRICE_DL)} tickers (auto_adjust=True) {start} → {end}...")
    raw_adj = yf.download(ALL_PRICE_DL, start=start, end=end, auto_adjust=True, progress=False)
    if not isinstance(raw_adj.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex columns from yfinance multi-ticker download.")

    close = raw_adj["Close"][ALL_PRICE_DL].copy()
    open_ = raw_adj["Open"][ALL_PRICE_DL].copy()
    volume = raw_adj["Volume"][ALL_PRICE_DL].copy()
    close = close.dropna(how="all")
    open_ = open_.reindex(close.index).ffill(limit=5)
    volume = volume.reindex(close.index).ffill(limit=5)
    close = close.ffill(limit=5)

    print(f"H75: data shape {close.shape}, range {close.index[0].date()} – {close.index[-1].date()}")

    # Download split-adjusted (not dividend-adjusted) closes for yield denominator
    print(f"H75: downloading split-adjusted prices (auto_adjust=False) for yield denominator...")
    raw_unadj = yf.download(
        SECTOR_UNIVERSE, start=start, end=end, auto_adjust=False, progress=False
    )
    if isinstance(raw_unadj.columns, pd.MultiIndex):
        close_unadj = raw_unadj["Close"][SECTOR_UNIVERSE].copy()
    else:
        close_unadj = raw_unadj[["Close"]].rename(columns={"Close": SECTOR_UNIVERSE[0]})
    close_unadj = close_unadj.reindex(close.index).ffill(limit=5)

    # Download historical dividends per sector ETF (split-adjusted amounts at ex-div date)
    print(f"H75: downloading historical dividends for {len(SECTOR_UNIVERSE)} sector ETFs...")
    div_series = {}
    for ticker in SECTOR_UNIVERSE:
        try:
            hist = yf.Ticker(ticker).history(
                start=start, end=end, auto_adjust=False, actions=True
            )
            if "Dividends" in hist.columns:
                divs = hist["Dividends"].copy()
                divs.index = divs.index.tz_localize(None) if divs.index.tz is not None else divs.index
                # Keep only non-zero entries (actual dividend payments)
                div_series[ticker] = divs[divs > 0]
            else:
                div_series[ticker] = pd.Series(dtype=float)
            n_divs = len(div_series[ticker])
            print(f"  {ticker}: {n_divs} dividend payments found")
        except Exception as e:
            warnings.warn(f"Dividend download failed for {ticker}: {e}")
            div_series[ticker] = pd.Series(dtype=float)

    # Build dividends DataFrame aligned to trading calendar (0 on non-div-payment days)
    dividends = pd.DataFrame(index=close.index, columns=SECTOR_UNIVERSE, dtype=float).fillna(0.0)
    for ticker in SECTOR_UNIVERSE:
        if len(div_series[ticker]) == 0:
            continue
        d = div_series[ticker]
        # Map ex-div dates to trading calendar (nearest trading day at or before ex-date)
        for ex_date, amount in d.items():
            ex_ts = pd.Timestamp(ex_date)
            # Find the trading day at or before ex_date
            avail = close.index[close.index <= ex_ts]
            if len(avail) > 0:
                trade_day = avail[-1]
                dividends.loc[trade_day, ticker] += amount

    print(f"H75: data downloaded. Dividends shape: {dividends.shape}")
    return {
        "close": close,
        "close_unadj": close_unadj,
        "open_": open_,
        "volume": volume,
        "dividends": dividends,
    }


def data_quality_report(data: dict) -> dict:
    close = data["close"]
    dividends = data["dividends"]
    report = {
        "universe": SECTOR_UNIVERSE,
        "regime_etf": REGIME_ETF,
        "safe_haven": SAFE_HAVEN,
        "survivorship_bias": (
            "Fixed 10-sector universe: 9 SPDR ETFs (inception Dec 1998) + XLRE (inception Oct 2015). "
            "All active ETFs — no delisting risk. XLRE excluded from ranking pre-2015 (not yet launched). "
            "No survivorship bias: universe selected a priori by hypothesis specification."
        ),
        "price_adjustment": (
            "Simulation prices: yfinance auto_adjust=True (total-return adjusted). "
            "Yield denominator: auto_adjust=False (split-adjusted only, not dividend-adjusted). "
            "Dividend numerator: split-adjusted historical ex-date amounts via yf.Ticker.history()."
        ),
        "earnings_exclusion": "N/A — sector ETFs are diversified baskets; no individual earnings events.",
        "xlre_note": (
            f"XLRE launched Oct 2015. Pre-launch: 9-sector universe used for yield ranking. "
            "Post-launch: 10-sector universe including XLRE."
        ),
        "tickers": {},
        "dividend_coverage": {},
        "flagged": [],
    }

    def _gap_check(series, label):
        clean = series.dropna()
        if len(clean) == 0:
            return {"error": "No data"}, True
        trimmed = series.loc[clean.index[0]:]
        max_gap = consec = 0
        for v in trimmed.isna():
            consec = (consec + 1) if v else 0
            max_gap = max(max_gap, consec)
        gap_flag = max_gap > 5
        if gap_flag:
            warnings.warn(f"Data gap flag: {label} has {max_gap} consecutive missing days")
        return {
            "total_obs": int(len(clean)),
            "start": str(clean.index.min().date()),
            "end": str(clean.index.max().date()),
            "max_consecutive_missing": max_gap,
            "gap_flag": gap_flag,
        }, gap_flag

    for t in ALL_PRICE_DL:
        if t not in close.columns:
            report["tickers"][t] = {"error": "not found"}
            report["flagged"].append(t)
            continue
        info, flagged = _gap_check(close[t], t)
        report["tickers"][t] = info
        if flagged:
            report["flagged"].append(t)

    for ticker in SECTOR_UNIVERSE:
        if ticker in dividends.columns:
            n_payments = int((dividends[ticker] > 0).sum())
            report["dividend_coverage"][ticker] = {
                "total_dividend_payments": n_payments,
                "note": "OK" if n_payments >= 10 else "LOW — may affect yield signal quality",
                "coverage_flag": n_payments < 10,
            }
            if n_payments < 10:
                report["flagged"].append(f"{ticker}_div_coverage")

    return report


# ── Month-End Signal Computation ───────────────────────────────────────────────

def get_last_trading_days(close: pd.DataFrame) -> pd.DatetimeIndex:
    helper = pd.Series(close.index, index=close.index)
    last_days = helper.resample("ME").last().dropna()
    return pd.DatetimeIndex(last_days.values)


def compute_trailing_div_yield(
    dividends: pd.DataFrame,
    close_unadj: pd.DataFrame,
    as_of_date: pd.Timestamp,
    lookback_months: int,
    universe: list,
) -> dict:
    """
    At `as_of_date` (month-end), compute trailing N-month dividend yield per sector.

    yield(ticker, t) = sum(dividends[ticker, t-N months : t]) / close_unadj[ticker, t]

    Uses split-adjusted prices and dividends for consistency.
    Returns {ticker: yield_value} for all tickers with valid data.
    """
    cutoff = as_of_date - pd.DateOffset(months=lookback_months)
    yields = {}
    for ticker in universe:
        if ticker not in dividends.columns:
            continue
        # Sum dividends in trailing lookback window (ex-div date inclusive on both ends)
        div_slice = dividends[ticker].loc[cutoff:as_of_date]
        trailing_divs = float(div_slice.sum()) if len(div_slice) > 0 else 0.0

        # Price at month-end (use split-adjusted close for yield denominator)
        if ticker in close_unadj.columns:
            px_avail = close_unadj[ticker].dropna()
            price_series = px_avail[px_avail.index <= as_of_date]
            if len(price_series) == 0:
                continue
            price = float(price_series.iloc[-1])
        else:
            continue

        if price > 0:
            yields[ticker] = trailing_divs / price
    return yields


def compute_all_signals(data: dict, params: dict, all_ltd: pd.DatetimeIndex) -> dict:
    """
    Compute monthly target portfolios at each last-trading-day in all_ltd.

    Returns dict[Timestamp] → {"tickers": [...], "regime_bearish": bool, "yields": dict}
    """
    close = data["close"]
    close_unadj = data["close_unadj"]
    dividends = data["dividends"]

    lookback = params["yield_lookback_months"]
    top_k = params["top_k"]
    use_filter = params["spy_filter"]
    ma_days = params.get("regime_ma_days", 200)

    spy_ma = close[REGIME_ETF].rolling(ma_days, min_periods=max(1, ma_days // 2)).mean()

    signals = {}
    for t in all_ltd:
        # SPY regime filter
        spy_val = close[REGIME_ETF].get(t, np.nan)
        ma_val = spy_ma.get(t, np.nan)
        if use_filter and not np.isnan(spy_val) and not np.isnan(ma_val):
            regime_bearish = bool(spy_val < ma_val)
        else:
            regime_bearish = False

        if regime_bearish:
            signals[t] = {"tickers": [SAFE_HAVEN], "regime_bearish": True, "yields": {}}
            continue

        # Universe: 9 sectors before XLRE launch, 10 after
        universe = [s for s in SECTOR_UNIVERSE if s != "XLRE" or t >= XLRE_LAUNCH]

        # Compute trailing dividend yield per sector
        yields = compute_trailing_div_yield(dividends, close_unadj, t, lookback, universe)

        # Filter to sectors with positive yield (excludes tickers with no dividend data)
        valid_yields = {k: v for k, v in yields.items() if v > 0}

        if not valid_yields:
            # Fallback: hold SHY if no sectors have valid yield data
            signals[t] = {"tickers": [SAFE_HAVEN], "regime_bearish": False, "yields": yields}
            continue

        # Rank descending by yield, select top-K
        sorted_tickers = sorted(valid_yields.keys(), key=lambda x: valid_yields[x], reverse=True)
        target = sorted_tickers[:top_k]

        signals[t] = {"tickers": target, "regime_bearish": False, "yields": yields}

    return signals


# ── Transaction Cost Model ─────────────────────────────────────────────────────

def _get_val(series, t_day, fallback=np.nan):
    if series is None:
        return fallback
    try:
        v = series.get(t_day, fallback)
    except Exception:
        return fallback
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return fallback
    return float(v)


def buy_cost_model(ticker, shares, price, sigma, adv, params):
    """Returns (cost_per_share, liquidity_constrained, q_over_adv)."""
    slip = params["slippage"]
    comm = params["commission_per_share"]
    k = params["market_impact_k"]
    adv = max(float(adv or 1e6), 1.0)
    sigma = float(sigma or 0.0)
    q_adv = shares / adv
    impact = k * sigma * np.sqrt(max(q_adv, 0.0))
    cost_per_share = price * (slip + impact) + comm
    return cost_per_share, q_adv > 0.01, round(q_adv, 8)


def sell_cost_model(ticker, shares, price, sigma, adv, params):
    """Returns (net_proceeds, liquidity_constrained, q_over_adv)."""
    slip = params["slippage"]
    comm = params["commission_per_share"]
    k = params["market_impact_k"]
    adv = max(float(adv or 1e6), 1.0)
    sigma = float(sigma or 0.0)
    q_adv = shares / adv
    impact = k * sigma * np.sqrt(max(q_adv, 0.0))
    total_pct = slip + impact
    net = shares * price * (1 - total_pct) - shares * comm
    return max(net, 0.0), q_adv > 0.01, round(q_adv, 8)


# ── Portfolio Simulation ───────────────────────────────────────────────────────

def run_backtest(
    data: dict,
    signals: dict,
    params: dict,
    start: str,
    end: str,
    period_label: str = "?",
) -> dict:
    """
    Daily mark-to-market backtest with monthly rebalancing.

    Execution: signal at month-end close T → execute at open of next trading day.
    Multi-position: sell exiting sectors, buy entering sectors (equal weight).
    """
    close = data["close"]
    open_ = data["open_"]
    volume = data["volume"]

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)
    window = close.loc[ts_start:ts_end].index

    if len(window) < 5:
        raise ValueError(f"Insufficient data {start}:{end}: {len(window)} days")

    init_cap = params["init_capital"]
    all_tickers_sim = SECTOR_UNIVERSE + [SAFE_HAVEN]

    # Rolling 20-day vol and ADV for transaction cost model
    sigma_20 = {}
    adv_20 = {}
    for tk in all_tickers_sim:
        if tk in close.columns:
            sigma_20[tk] = close[tk].pct_change().rolling(20, min_periods=5).std()
        if tk in volume.columns:
            adv_20[tk] = volume[tk].rolling(20, min_periods=5).mean()

    # Signals in window
    window_signals = {d: s for d, s in signals.items() if ts_start <= d <= ts_end}

    # Initial target: last signal before window start, or first in window
    prior = {d: s for d, s in signals.items() if d < ts_start}
    if prior:
        init_sig = prior[max(prior.keys())]
    else:
        first_dt = min(window_signals.keys()) if window_signals else None
        init_sig = window_signals.get(first_dt, {"tickers": [SAFE_HAVEN]})

    # State
    cash = float(init_cap)
    positions = {}      # ticker → shares
    entry_info = {}     # ticker → {"price": float, "date": str}
    pending_tgt = list(init_sig["tickers"])  # execute at open of first day
    position_switch_count = 0

    portfolio_values = pd.Series(index=window, dtype=float)
    trade_log = []

    def gp(df, ticker, t_day):
        if ticker not in df.columns or t_day not in df.index:
            return np.nan
        v = df.loc[t_day, ticker]
        return float(v) if not pd.isna(v) else np.nan

    for i, t_day in enumerate(window):
        # ── Execute pending rebalance at today's open ─────────────────────────
        if pending_tgt is not None:
            new_set = set(pending_tgt)
            cur_set = set(positions.keys())
            to_sell = cur_set - new_set
            to_buy = new_set - cur_set

            # Count as position switch if any change
            if to_sell or to_buy:
                position_switch_count += 1

            # Sell exiting positions
            for ticker in sorted(to_sell):
                sh = positions.get(ticker, 0.0)
                if sh <= 0:
                    continue
                px = gp(open_, ticker, t_day)
                if np.isnan(px) or px <= 0:
                    px = gp(close, ticker, t_day)
                if np.isnan(px) or px <= 0:
                    continue

                sig_v = _get_val(sigma_20.get(ticker), t_day, 0.0) or 0.0
                adv_v = _get_val(adv_20.get(ticker), t_day, 1e6) or 1e6
                proceeds, liq, q_adv = sell_cost_model(ticker, sh, px, sig_v, adv_v, params)
                cash += proceeds

                ei = entry_info.pop(ticker, {"price": px, "date": str(t_day.date())})
                pnl = proceeds - sh * float(ei["price"])
                trade_log.append({
                    "period": period_label,
                    "ticker": ticker,
                    "entry_date": ei["date"],
                    "exit_date": str(t_day.date()),
                    "entry_price": round(float(ei["price"]), 4),
                    "exit_price": round(float(px), 4),
                    "shares": round(float(sh), 4),
                    "pnl": round(float(pnl), 2),
                    "exit_reason": "rebalance",
                    "liquidity_constrained": liq,
                    "q_over_adv": q_adv,
                })
                del positions[ticker]

            # Buy new positions (equal weight from available cash across new entries)
            n_buy = len(to_buy)
            if n_buy > 0:
                cash_per = cash / n_buy
                for ticker in sorted(to_buy):
                    px = gp(open_, ticker, t_day)
                    if np.isnan(px) or px <= 0:
                        px = gp(close, ticker, t_day)
                    if np.isnan(px) or px <= 0:
                        continue

                    sig_v = _get_val(sigma_20.get(ticker), t_day, 0.0) or 0.0
                    adv_v = _get_val(adv_20.get(ticker), t_day, 1e6) or 1e6
                    est_sh = cash_per / (px + 1e-8)
                    cps, liq, q_adv = buy_cost_model(ticker, est_sh, px, sig_v, adv_v, params)
                    total_per_share = px + cps
                    sh = cash_per / total_per_share if total_per_share > 0 else 0.0
                    sh = max(sh, 0.0)
                    spent = sh * total_per_share
                    cash -= spent
                    if sh > 0:
                        positions[ticker] = sh
                        entry_info[ticker] = {"price": float(px), "date": str(t_day.date())}

            cash = max(cash, 0.0)
            pending_tgt = None

        # ── Mark to market at close ───────────────────────────────────────────
        nav = cash
        for ticker, sh in positions.items():
            px = gp(close, ticker, t_day)
            if not np.isnan(px) and px > 0:
                nav += sh * px
        portfolio_values.iloc[i] = max(nav, 0.0)

        # ── Check month-end signal ────────────────────────────────────────────
        if t_day in window_signals:
            new_tgt = window_signals[t_day]["tickers"]
            if set(new_tgt) != set(positions.keys()):
                pending_tgt = list(new_tgt)

    # Final close-out (mark-to-market, no trade cost)
    if positions:
        last_t = window[-1]
        for ticker, sh in list(positions.items()):
            px = gp(close, ticker, last_t)
            if np.isnan(px) or px <= 0:
                continue
            ei = entry_info.pop(ticker, {"price": px, "date": str(last_t.date())})
            pnl = sh * px - sh * float(ei["price"])
            trade_log.append({
                "period": period_label,
                "ticker": ticker,
                "entry_date": ei["date"],
                "exit_date": str(last_t.date()),
                "entry_price": round(float(ei["price"]), 4),
                "exit_price": round(float(px), 4),
                "shares": round(float(sh), 4),
                "pnl": round(float(pnl), 2),
                "exit_reason": "window_end",
                "liquidity_constrained": False,
                "q_over_adv": 0.0,
            })

    portfolio_values = portfolio_values.ffill().fillna(float(init_cap))
    return {
        "portfolio_values": portfolio_values,
        "trade_log": trade_log,
        "position_switch_count": position_switch_count,
    }


# ── Performance Metrics ────────────────────────────────────────────────────────

def compute_metrics(portfolio_values: pd.Series, trade_log: list, start: str, end: str) -> dict:
    pv = portfolio_values.dropna()
    if len(pv) < 2:
        return {"error": "Insufficient data"}

    daily_ret = pv.pct_change().fillna(0.0).values
    sharpe = float(daily_ret.mean() / (daily_ret.std() + 1e-10) * np.sqrt(TRADING_DAYS))

    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    total_ret = float(pv.iloc[-1] / pv.iloc[0] - 1)
    cagr = float((pv.iloc[-1] / pv.iloc[0]) ** (1.0 / max(years, 0.01)) - 1)

    cum = np.cumprod(1 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd = float(np.min((cum - roll_max) / (roll_max + 1e-10)))

    closed = [t for t in trade_log if t.get("exit_reason") == "rebalance"]

    if closed:
        pnl_arr = np.array([t["pnl"] for t in closed])
        win_rate = float(np.mean(pnl_arr > 0))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        pf = (
            float(wins.sum() / abs(losses.sum()))
            if len(losses) > 0 and abs(losses.sum()) > 0
            else float("inf")
        )
        avg_ppt_bps = float(np.mean(pnl_arr / (pv.iloc[0] + 1e-8) * 10_000))
    else:
        win_rate = avg_ppt_bps = 0.0
        pf = 0.0

    return {
        "sharpe": round(sharpe, 4),
        "cagr": round(cagr, 4),
        "max_drawdown": round(mdd, 4),
        "total_return": round(total_ret, 4),
        "trade_count": len(closed),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(pf, 4) if not np.isinf(pf) else "inf",
        "avg_ppt_bps": round(avg_ppt_bps, 2),
        "period": f"{start} to {end}",
        "years": round(years, 2),
    }


# ── Statistical Rigor ──────────────────────────────────────────────────────────

def monte_carlo_sharpe(pnl_arr: np.ndarray, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    if len(pnl_arr) < 5:
        return {
            "mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0,
            "mc_p95_sharpe": 0.0, "mc_flag": "insufficient trades",
        }
    sharpes = []
    for _ in range(n_sims):
        s = np.random.choice(pnl_arr, size=len(pnl_arr), replace=True)
        sh = s.mean() / (s.std() + 1e-8) * np.sqrt(TRADING_DAYS)
        sharpes.append(sh)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe": float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe": float(np.percentile(arr, 95)),
        "mc_flag": f"MC on {len(pnl_arr)} IS trade PnLs",
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    np.random.seed(43)
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s: s + block_len] for s in starts])[:T]
        if len(sample) < 2:
            continue
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd_val = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        sh = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS))
        wr = float(np.mean(sample > 0))
        sharpes.append(sh)
        mdds.append(mdd_val)
        win_rates.append(wr)
    if not sharpes:
        return {
            "sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
            "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
            "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0,
        }
    return {
        "sharpe_ci_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high": float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low": float(np.percentile(mdds, 2.5)),
        "mdd_ci_high": float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low": float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def permutation_test_yield(
    data: dict,
    params: dict,
    observed_sharpe: float,
    all_ltd: pd.DatetimeIndex,
    start: str,
    end: str,
    n_perms: int = 1000,
) -> dict:
    """
    Permutation test for dividend yield carry signal.

    At each month-end, randomly shuffle which sector has which yield rank.
    This destroys the cross-sectional relationship between yield and forward return.
    p-value = fraction of permuted Sharpes >= observed IS Sharpe.
    """
    np.random.seed(44)
    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    is_ltd = [d for d in all_ltd if ts_start <= d <= ts_end]
    if len(is_ltd) < 10:
        return {
            "permutation_pvalue": 0.5,
            "permutation_test_pass": False,
            "permutation_perm_mean": 0.0,
            "permutation_perm_p95": 0.0,
            "permutation_note": "insufficient IS months for permutation test",
        }

    # Precompute the yield ranking at each IS month-end (already done in signals dict)
    # Rebuild original signals yield data for shuffling
    close_unadj = data["close_unadj"]
    dividends = data["dividends"]
    lookback = params["yield_lookback_months"]
    top_k = params["top_k"]

    # Get list of available tickers per date and their yields
    per_date_info = []
    for t in is_ltd:
        universe = [s for s in SECTOR_UNIVERSE if s != "XLRE" or t >= XLRE_LAUNCH]
        yields = compute_trailing_div_yield(dividends, close_unadj, t, lookback, universe)
        valid_tickers = [k for k, v in yields.items() if v > 0]
        if len(valid_tickers) < 2:
            per_date_info.append(None)
            continue
        per_date_info.append({"tickers": valid_tickers, "yields": yields})

    # Compute daily portfolio returns (total return adj) for permutation simulation
    close = data["close"]
    window_ret = {}
    for i, t in enumerate(is_ltd[:-1]):
        next_t = is_ltd[i + 1]
        # Returns from t to next_t for all sector ETFs + SHY
        for tk in SECTOR_UNIVERSE + [SAFE_HAVEN]:
            if tk in close.columns:
                p1 = close[tk].get(t, np.nan)
                p2 = close[tk].get(next_t, np.nan)
                if not np.isnan(p1) and not np.isnan(p2) and p1 > 0:
                    window_ret.setdefault(i, {})[tk] = float(p2 / p1 - 1)

    perm_sharpes = []
    for _ in range(n_perms):
        # Shuffle which month gets which yield ranking (scramble signal-return relationship)
        perm_idx = np.random.permutation(len(per_date_info))
        monthly_pf_rets = []

        for i in range(len(is_ltd) - 1):
            shuffled_signal = per_date_info[perm_idx[i]]
            if shuffled_signal is None or not window_ret.get(i):
                monthly_pf_rets.append(0.0)
                continue

            tickers = shuffled_signal["tickers"]
            if not tickers:
                monthly_pf_rets.append(0.0)
                continue

            # Sort by yields (from shuffled month) and take top_k
            yields = shuffled_signal["yields"]
            ranked = sorted(tickers, key=lambda x: yields.get(x, 0), reverse=True)[:top_k]

            # Actual returns come from the current (non-shuffled) period
            rets = [window_ret[i].get(tk, 0.0) for tk in ranked if tk in window_ret[i]]
            if rets:
                monthly_pf_rets.append(float(np.mean(rets)))
            else:
                monthly_pf_rets.append(0.0)

        arr = np.array(monthly_pf_rets)
        if arr.std() > 0:
            sh = float(arr.mean() / arr.std() * np.sqrt(12))
        else:
            sh = 0.0
        perm_sharpes.append(sh)

    perm_arr = np.array(perm_sharpes)
    p_value = float(np.mean(perm_arr >= observed_sharpe))
    return {
        "permutation_pvalue": round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
        "permutation_perm_mean": float(perm_arr.mean()),
        "permutation_perm_p95": float(np.percentile(perm_arr, 95)),
    }


def compute_dsr(is_sharpe: float, n_trials: int, T: int) -> float:
    if T <= 0 or n_trials <= 1:
        return 0.0
    gamma = 0.5772
    ln_n = np.log(max(n_trials, 2))
    expected_max = (
        np.sqrt(2 * ln_n)
        - (np.log(np.log(max(n_trials, 2))) + np.log(4 * np.pi)) / (2 * np.sqrt(2 * ln_n))
        + gamma / np.sqrt(2 * ln_n)
    ) / np.sqrt(T)
    return round(float(is_sharpe - expected_max), 4)


def compute_market_impact_report(data: dict, start: str, end: str) -> dict:
    """Market impact at $100K / top_k positions = ~$33K per sector (k=3)."""
    close = data["close"]
    volume = data["volume"]
    cap_per_position = 33_333.0  # $100K / 3 positions
    results = {}
    for ticker in SECTOR_UNIVERSE:
        if ticker not in close.columns:
            continue
        try:
            hist_c = close[ticker].loc[start:end].dropna()
            hist_v = volume[ticker].loc[start:end].dropna()
            if len(hist_c) < 20:
                results[ticker] = {"market_impact_bps": 0.0, "note": "insufficient data"}
                continue
            avg_price = float(hist_c.tail(20).mean())
            adv = float(hist_v.tail(20).mean())
            sigma = float(hist_c.pct_change().tail(60).std())
            qty = cap_per_position / max(avg_price, 1.0)
            q_adv = qty / max(adv, 1.0)
            impact = 0.1 * sigma * np.sqrt(max(q_adv, 0.0))
            impact_bps = impact * 10_000
            results[ticker] = {
                "market_impact_bps": round(float(impact_bps), 4),
                "adv_20d": round(float(adv), 0),
                "avg_price": round(float(avg_price), 2),
                "qty_at_33k": round(float(qty), 0),
                "q_over_adv": round(float(q_adv), 6),
                "liquidity_constrained": q_adv > 0.01,
            }
        except Exception as e:
            results[ticker] = {"market_impact_bps": 0.0, "error": str(e)}
    return results


# ── Walk-Forward Analysis ──────────────────────────────────────────────────────

def run_walk_forward(
    data: dict,
    params: dict,
    all_ltd: pd.DatetimeIndex,
    wf_windows: list,
) -> list:
    """Run each IS-only WF window independently using pre-computed full signal set."""
    results = []
    print(f"  Computing walk-forward signals (full IS period)...")
    all_signals = compute_all_signals(data, params, all_ltd)

    for i, (wf_start, wf_end) in enumerate(wf_windows):
        try:
            wf_result = run_backtest(data, all_signals, params, wf_start, wf_end, f"WF{i+1}")
            wf_metrics = compute_metrics(
                wf_result["portfolio_values"], wf_result["trade_log"], wf_start, wf_end
            )
            results.append({
                "window": i + 1,
                "is_start": wf_start,
                "is_end": wf_end,
                "sharpe": wf_metrics["sharpe"],
                "max_drawdown": wf_metrics["max_drawdown"],
                "win_rate": wf_metrics["win_rate"],
                "trade_count": wf_metrics["trade_count"],
                "cagr": wf_metrics["cagr"],
                "position_switches": wf_result["position_switch_count"],
            })
            print(
                f"  WF{i+1} ({wf_start}–{wf_end}): Sharpe={wf_metrics['sharpe']:.3f}, "
                f"MDD={wf_metrics['max_drawdown']:.2%}, trades={wf_metrics['trade_count']}"
            )
        except Exception as e:
            results.append({
                "window": i + 1, "is_start": wf_start, "is_end": wf_end,
                "sharpe": 0.0, "error": str(e),
            })
            print(f"  WF{i+1} ERROR: {e}")

    return results


# ── Parameter Sweep ────────────────────────────────────────────────────────────

def run_sweep(data: dict, all_ltd: pd.DatetimeIndex) -> list:
    """18-combination sweep on IS: yield_lookback × top_k × spy_filter."""
    rows = []
    combos = list(iproduct(SWEEP_LOOKBACKS, SWEEP_TOP_K, SWEEP_FILTER))
    print(f"  Running {len(combos)} sweep combinations on IS ({IS_START}–{IS_END})...")

    for lookback, top_k, use_filter in combos:
        p = {**PARAMETERS, "yield_lookback_months": lookback, "top_k": top_k, "spy_filter": use_filter}
        label = f"lb={lookback}m, k={top_k}, filter={'Y' if use_filter else 'N'}"
        try:
            sigs = compute_all_signals(data, p, all_ltd)
            res = run_backtest(data, sigs, p, IS_START, IS_END, "SWEEP")
            m = compute_metrics(res["portfolio_values"], res["trade_log"], IS_START, IS_END)
            rows.append({
                "yield_lookback_months": lookback,
                "top_k": top_k,
                "spy_filter": use_filter,
                "sharpe": m["sharpe"],
                "cagr": m["cagr"],
                "max_drawdown": m["max_drawdown"],
                "win_rate": m["win_rate"],
                "trade_count": m["trade_count"],
                "total_return": m["total_return"],
                "position_switches": res["position_switch_count"],
            })
            print(
                f"    {label}: Sharpe={m['sharpe']:.3f}, MDD={m['max_drawdown']:.2%}, "
                f"trades={m['trade_count']}, switches={res['position_switch_count']}"
            )
        except Exception as e:
            rows.append({
                "yield_lookback_months": lookback, "top_k": top_k,
                "spy_filter": use_filter, "error": str(e),
            })
            print(f"    {label}: ERROR {e}")

    return rows


# ── HTML Report ────────────────────────────────────────────────────────────────

def build_html_report(
    is_m: dict, oos_m: dict, wf_results: list, sweep_rows: list,
    mi_report: dict, mc: dict, bb: dict, perm: dict, dsr: float,
    verdict_label: str, checks: list,
    is_regime_months: int, is_total_months: int,
    is_switch_count: int,
) -> str:
    verdict_color = "#d4edda" if verdict_label == "PASS" else "#f8d7da"
    check_rows = "".join(
        f"<tr style='background:{'#d4edda' if p else '#f8d7da'}'>"
        f"<td>{g}</td><td>{v}</td><td>{t}</td><td>{'&#10003; PASS' if p else '&#10007; FAIL'}</td></tr>"
        for g, v, t, p in checks
    )
    wf_rows = "".join(
        f"<tr><td>{w['window']}</td><td>{w['is_start']}–{w['is_end']}</td>"
        f"<td>{w.get('sharpe', 0):.4f}</td><td>{w.get('max_drawdown', 0):.2%}</td>"
        f"<td>{w.get('win_rate', 0):.2%}</td><td>{w.get('trade_count', 0)}</td>"
        f"<td>{w.get('cagr', 0):.2%}</td></tr>"
        for w in wf_results
    )
    try:
        sweep_df = pd.DataFrame(sweep_rows)
        sweep_html = sweep_df.to_html(
            index=False,
            float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x),
            border=1,
        )
    except Exception:
        sweep_html = "<p>Sweep data unavailable</p>"

    mi_rows = "".join(
        f"<tr><td>{t}</td><td>{d.get('market_impact_bps', 0):.4f}</td>"
        f"<td>{d.get('adv_20d', 0):,.0f}</td><td>{d.get('q_over_adv', 0):.6f}</td>"
        f"<td>{d.get('liquidity_constrained', False)}</td></tr>"
        for t, d in mi_report.items()
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>H75 Equity Carry (Dividend Yield Sector Rotation) — Gate 1 Report</title>
<style>
body {{ font-family: monospace; max-width: 1200px; margin: 0 auto; padding: 20px; }}
h1 {{ background: #343a40; color: white; padding: 15px; border-radius: 4px; }}
h2 {{ border-bottom: 2px solid #343a40; padding-bottom: 5px; margin-top: 30px; }}
.verdict {{ font-size: 2em; font-weight: bold; padding: 15px; border-radius: 4px;
           background: {verdict_color}; text-align: center; margin: 20px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th {{ background: #343a40; color: white; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border: 1px solid #dee2e6; }}
.section {{ margin: 20px 0; padding: 15px; border: 1px solid #dee2e6; border-radius: 4px; }}
.note {{ background: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>H75 Equity Carry — Dividend Yield Sector Rotation — Gate 1 Report</h1>
<p><strong>Date:</strong> {TODAY} | <strong>Universe:</strong> {', '.join(SECTOR_UNIVERSE)}</p>
<p><strong>Signal:</strong> Trailing 12M dividend yield rank → top-3 sectors equal weight | <strong>Filter:</strong> SPY 200-DMA → SHY</p>
<p><strong>Academic source:</strong> Koijen, Moskowitz, Pedersen &amp; Vrugt (2018) — "Carry", <em>Journal of Financial Economics</em> 127(2)</p>
<p><strong>Slippage:</strong> 0.05% standard ETF tier (sector ETFs ADV &lt;&lt; 50M shares/day, ED-SLIP-001 ultra-liquid tier NOT applied)</p>
<p><strong>Regime-SHY months (IS):</strong> {is_regime_months} / {is_total_months} months | <strong>IS position switches:</strong> {is_switch_count}</p>

<div class="verdict">GATE 1: {verdict_label}</div>

<div class="note">
<strong>Research Director Note (H75):</strong> IS Sharpe &gt; 1.0 may be difficult for this strategy.
Expected range from Koijen et al. (2018) is 0.4–0.8 Sharpe. If IS Sharpe is 0.6–0.9, results are
documented for carry premium evidence even if Gate 1 strict threshold is not met.
</div>

<h2>Gate 1 Checklist</h2>
<table><tr><th>Gate</th><th>Value</th><th>Threshold</th><th>Result</th></tr>{check_rows}</table>

<h2>IS / OOS Summary</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>IS (2003–2021, ~18yr)</th><th>OOS (2022–2023, ~2yr)</th></tr>
<tr><td>Sharpe</td><td>{is_m['sharpe']:.4f}</td><td>{oos_m['sharpe']:.4f}</td></tr>
<tr><td>CAGR</td><td>{is_m['cagr']:.2%}</td><td>{oos_m['cagr']:.2%}</td></tr>
<tr><td>Max Drawdown</td><td>{is_m['max_drawdown']:.2%}</td><td>{oos_m['max_drawdown']:.2%}</td></tr>
<tr><td>Win Rate</td><td>{is_m['win_rate']:.2%}</td><td>{oos_m['win_rate']:.2%}</td></tr>
<tr><td>Profit Factor</td><td>{is_m['profit_factor']}</td><td>{oos_m['profit_factor']}</td></tr>
<tr><td>Trade Count</td><td>{is_m['trade_count']}</td><td>{oos_m['trade_count']}</td></tr>
<tr><td>Avg PpT (bps)</td><td>{is_m['avg_ppt_bps']:.2f}</td><td>{oos_m['avg_ppt_bps']:.2f}</td></tr>
</table>
</div>

<h2>Walk-Forward Analysis (4 IS Windows)</h2>
<table>
<tr><th>Window</th><th>Period</th><th>Sharpe</th><th>MDD</th><th>Win Rate</th><th>Trades</th><th>CAGR</th></tr>
{wf_rows}
</table>

<h2>Statistical Tests</h2>
<div class="section">
<p><strong>Monte Carlo (1000 resamples on IS trade PnLs):</strong>
   p5={mc['mc_p5_sharpe']:.4f}, median={mc['mc_median_sharpe']:.4f}, p95={mc['mc_p95_sharpe']:.4f}</p>
<p><strong>Block Bootstrap CI (95%):</strong>
   Sharpe [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]
   MDD [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]</p>
<p><strong>Permutation test (yield ranking shuffle, 1000 perms):</strong>
   p={perm['permutation_pvalue']:.4f} — {"PASS" if perm['permutation_test_pass'] else "FAIL"}</p>
<p><strong>DSR (Deflated Sharpe Ratio):</strong> {dsr:.4f}</p>
</div>

<h2>Parameter Sweep (18 Combinations: lookback × top_k × spy_filter)</h2>
{sweep_html}

<h2>Market Impact by Ticker (at ~$33K/position)</h2>
<table>
<tr><th>Ticker</th><th>Impact (bps)</th><th>ADV 20d</th><th>Q/ADV</th><th>Liq. Constrained</th></tr>
{mi_rows}
</table>

<hr>
<p><em>Generated by Engineering Director (QUA-316) | H75 Gate 1 | {TODAY}</em></p>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H75 Equity Carry — Dividend Yield Sector Rotation — Gate 1 — {TODAY}")
    print(f"Universe: {SECTOR_UNIVERSE}")
    print(f"IS: {IS_START} → {IS_END} | OOS: {OOS_START} → {OOS_END}")
    print(
        f"Signal: trailing {PARAMETERS['yield_lookback_months']}M div yield | "
        f"Top-{PARAMETERS['top_k']} | 200-DMA SPY filter={PARAMETERS['spy_filter']}"
    )
    print("=" * 70)

    # ── [1/8] Data Download ───────────────────────────────────────────────────
    print("\n[1/8] Downloading data...")
    data = download_data(DATA_START, OOS_END)
    dq = data_quality_report(data)
    if dq["flagged"]:
        warnings.warn(f"Data quality flags: {dq['flagged']}")

    close = data["close"]
    all_ltd = get_last_trading_days(close)

    # ── [2/8] Signal Computation ──────────────────────────────────────────────
    print("\n[2/8] Computing monthly dividend yield signals (primary params)...")
    all_signals = compute_all_signals(data, PARAMETERS, all_ltd)
    print(f"  Signals computed: {len(all_signals)} month-end dates")

    # PF-2/PF-4 analysis: count IS regime months
    is_sigs_months = [d for d in all_signals if pd.Timestamp(IS_START) <= d <= pd.Timestamp(IS_END)]
    regime_bearish_months = sum(1 for d in is_sigs_months if all_signals[d]["regime_bearish"])
    print(f"  IS months: {len(is_sigs_months)} | Regime-bearish (SHY) months: {regime_bearish_months}")

    # PF-2 / PF-4 specific date checks
    gfc_check_dates = pd.date_range("2007-12-01", "2009-03-31", freq="ME")
    gfc_shy_months = [d for d in gfc_check_dates if d in all_signals and all_signals[d]["regime_bearish"]]
    rate_shock_dates = pd.date_range("2022-01-01", "2022-06-30", freq="ME")
    rate_shy_months = [d for d in rate_shock_dates if d in all_signals and all_signals[d]["regime_bearish"]]
    print(f"  PF-2 (GFC 2008-2009): regime→SHY months: {len(gfc_shy_months)} "
          f"(first: {gfc_shy_months[0].date() if gfc_shy_months else 'none'})")
    print(f"  PF-4 (2022 rate shock): regime→SHY months: {len(rate_shy_months)} "
          f"(first: {rate_shy_months[0].date() if rate_shy_months else 'none'})")

    # ── [3/8] IS Backtest ─────────────────────────────────────────────────────
    print(f"\n[3/8] IS backtest ({IS_START} → {IS_END})...")
    is_result = run_backtest(data, all_signals, PARAMETERS, IS_START, IS_END, "IS")
    is_metrics = compute_metrics(is_result["portfolio_values"], is_result["trade_log"], IS_START, IS_END)
    is_switch_count = is_result["position_switch_count"]

    print(
        f"  IS Sharpe: {is_metrics['sharpe']:.4f} | CAGR: {is_metrics['cagr']:.2%} | "
        f"MDD: {is_metrics['max_drawdown']:.2%}"
    )
    print(f"  IS trades: {is_metrics['trade_count']} | Position switches: {is_switch_count}")

    if is_switch_count < 60:
        print(
            f"  FLAG: IS position switches {is_switch_count} < 60. "
            f"Yield rankings may be too stable → low effective trade count."
        )

    # ── [4/8] OOS Backtest ────────────────────────────────────────────────────
    print(f"\n[4/8] OOS backtest ({OOS_START} → {OOS_END})...")
    oos_result = run_backtest(data, all_signals, PARAMETERS, OOS_START, OOS_END, "OOS")
    oos_metrics = compute_metrics(oos_result["portfolio_values"], oos_result["trade_log"], OOS_START, OOS_END)
    oos_switch_count = oos_result["position_switch_count"]

    print(
        f"  OOS Sharpe: {oos_metrics['sharpe']:.4f} | CAGR: {oos_metrics['cagr']:.2%} | "
        f"MDD: {oos_metrics['max_drawdown']:.2%}"
    )
    print(f"  OOS trades: {oos_metrics['trade_count']} | Position switches: {oos_switch_count}")

    # ── [5/8] Walk-Forward Analysis ───────────────────────────────────────────
    print("\n[5/8] Walk-forward analysis (4 IS windows)...")
    wf_results = run_walk_forward(data, PARAMETERS, all_ltd, WF_IS_WINDOWS)
    wf_sharpes = [w.get("sharpe", 0.0) for w in wf_results]
    wf_passed = sum(1 for s in wf_sharpes if s > 0.0)
    wf_sharpe_std = float(np.std(wf_sharpes)) if wf_sharpes else 0.0
    wf_sharpe_min = float(np.min(wf_sharpes)) if wf_sharpes else 0.0
    print(f"  WF passed (Sharpe>0): {wf_passed}/4 | std={wf_sharpe_std:.3f} | min={wf_sharpe_min:.3f}")

    # ── [6/8] Statistical Rigor Pipeline ─────────────────────────────────────
    print("\n[6/8] Statistical rigor pipeline...")
    is_closed = [t for t in is_result["trade_log"] if t.get("exit_reason") == "rebalance"]
    is_pnl_arr = np.array([t["pnl"] for t in is_closed]) if is_closed else np.array([0.0])
    is_ret_arr = is_result["portfolio_values"].pct_change().fillna(0.0).values

    mc = monte_carlo_sharpe(is_pnl_arr)
    bb = block_bootstrap_ci(is_ret_arr)
    perm = permutation_test_yield(
        data, PARAMETERS, is_metrics["sharpe"], all_ltd, IS_START, IS_END
    )
    n_trials = 18 + 4  # sweep combos + WF windows
    T_is = len(is_result["portfolio_values"])
    dsr = compute_dsr(is_metrics["sharpe"], n_trials, T_is)

    print(f"  MC p5={mc['mc_p5_sharpe']:.3f}, median={mc['mc_median_sharpe']:.3f}")
    print(f"  Bootstrap Sharpe CI: [{bb['sharpe_ci_low']:.3f}, {bb['sharpe_ci_high']:.3f}]")
    print(f"  Permutation p={perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})")
    print(f"  DSR={dsr:.4f}")

    print("  Computing market impact...")
    mi_report = compute_market_impact_report(data, IS_START, IS_END)
    max_mi_bps = max((v.get("market_impact_bps", 0) for v in mi_report.values()), default=0.0)
    print(f"  Max market impact: {max_mi_bps:.4f} bps")

    # ── [7/8] Parameter Sweep ─────────────────────────────────────────────────
    print("\n[7/8] Parameter sweep (18 combinations)...")
    sweep_rows = run_sweep(data, all_ltd)
    valid_sharpes = [
        r["sharpe"] for r in sweep_rows
        if "sharpe" in r and isinstance(r["sharpe"], (int, float))
    ]
    if valid_sharpes:
        primary_sharpe = is_metrics["sharpe"]
        sharpe_range = max(valid_sharpes) - min(valid_sharpes)
        variance_pct = sharpe_range / abs(primary_sharpe) if primary_sharpe != 0 else float("nan")
        sensitivity_pass = not np.isnan(variance_pct) and variance_pct <= 0.30
    else:
        variance_pct = float("nan")
        sensitivity_pass = False
    if valid_sharpes:
        print(
            f"  Sharpe range: {min(valid_sharpes):.3f} – {max(valid_sharpes):.3f} "
            f"| Variance: {variance_pct:.1%} | Sensitivity: {'PASS' if sensitivity_pass else 'FAIL'}"
        )

    # ── [8/8] Gate 1 Verdict ─────────────────────────────────────────────────
    print("\n[8/8] Computing Gate 1 verdict...")
    is_sharpe = is_metrics["sharpe"]
    oos_sharpe = oos_metrics["sharpe"]
    is_mdd = is_metrics["max_drawdown"]
    oos_mdd = oos_metrics["max_drawdown"]
    is_cagr = is_metrics["cagr"]
    is_trades = is_metrics["trade_count"]

    gate_is_sharpe = is_sharpe > 1.0
    gate_oos_sharpe = oos_sharpe > 0.70
    gate_is_cagr = is_cagr >= 0.10
    gate_is_mdd = is_mdd > -0.15
    gate_oos_mdd = oos_mdd > -0.15
    gate_wf = wf_passed >= 3
    gate_perm = perm["permutation_test_pass"]
    gate_trades = is_trades >= 100
    gate_dsr = dsr > 0.0
    gate_switches = is_switch_count >= 60

    checks = [
        ("IS Sharpe", f"{is_sharpe:.4f}", "> 1.0", gate_is_sharpe),
        ("OOS Sharpe", f"{oos_sharpe:.4f}", "> 0.70", gate_oos_sharpe),
        ("IS CAGR", f"{is_cagr:.2%}", ">= 10%", gate_is_cagr),
        ("IS MDD", f"{is_mdd:.2%}", "> -15%", gate_is_mdd),
        ("OOS MDD", f"{oos_mdd:.2%}", "> -15%", gate_oos_mdd),
        ("Walk-Forward", f"{wf_passed}/4", ">= 3/4", gate_wf),
        ("Permutation p", f"{perm['permutation_pvalue']:.4f}", "< 0.05", gate_perm),
        ("IS Trade Count", f"{is_trades}", ">= 100", gate_trades),
        ("DSR", f"{dsr:.4f}", "> 0", gate_dsr),
        ("IS Switches", f"{is_switch_count}", ">= 60", gate_switches),
    ]
    n_passed = sum(1 for *_, p in checks if p)
    verdict_label = "PASS" if all(p for *_, p in checks) else "FAIL"

    print(f"\n{'='*70}")
    print(f"H75 Equity Carry — GATE 1 VERDICT: {verdict_label}")
    print(f"  Passed {n_passed}/{len(checks)} checks")
    for g, v, t, p in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {g:<22} {v:<12} (threshold: {t})")
    print(f"{'='*70}")

    # ── Build Metrics JSON ─────────────────────────────────────────────────────
    metrics_json = {
        "strategy_name": STRATEGY_NAME,
        "date": TODAY,
        "hypothesis": "H75",
        "asset_class": "equities",
        "parent_task": "QUA-316",
        "universe": SECTOR_UNIVERSE,
        "regime_etf": REGIME_ETF,
        "safe_haven": SAFE_HAVEN,
        "xlre_note": "XLRE excluded from ranking pre-Oct-2015 (not yet launched)",
        "parameters": {
            "yield_lookback_months": PARAMETERS["yield_lookback_months"],
            "top_k": PARAMETERS["top_k"],
            "spy_filter": PARAMETERS["spy_filter"],
            "regime_ma_days": PARAMETERS["regime_ma_days"],
        },
        "cost_model": {
            "slippage": "0.05% (standard ETF tier — sector ETFs ADV << 50M/day)",
            "commission": "$0.005/share",
            "market_impact": "0.1 × σ × sqrt(Q/ADV) — Almgren-Chriss",
            "ruling": "ED-SLIP-001 ultra-liquid tier NOT applied (sector ETFs ADV << 50M/day)",
        },
        "is_sharpe": is_sharpe,
        "is_cagr": is_cagr,
        "is_max_drawdown": is_mdd,
        "is_total_return": is_metrics["total_return"],
        "is_win_rate": is_metrics["win_rate"],
        "is_profit_factor": is_metrics["profit_factor"],
        "is_trade_count": is_trades,
        "is_position_switches": is_switch_count,
        "is_avg_ppt_bps": is_metrics["avg_ppt_bps"],
        "oos_sharpe": oos_sharpe,
        "oos_cagr": oos_metrics["cagr"],
        "oos_max_drawdown": oos_mdd,
        "oos_total_return": oos_metrics["total_return"],
        "oos_win_rate": oos_metrics["win_rate"],
        "oos_profit_factor": oos_metrics["profit_factor"],
        "oos_trade_count": oos_metrics["trade_count"],
        "oos_position_switches": oos_switch_count,
        "oos_avg_ppt_bps": oos_metrics["avg_ppt_bps"],
        "post_cost_sharpe": is_sharpe,
        "dsr": dsr,
        "n_trials": n_trials,
        **mc,
        **bb,
        **perm,
        "market_impact_by_ticker": mi_report,
        "wf_windows": wf_results,
        "wf_windows_passed": wf_passed,
        "wf_consistency_score": round(wf_passed / 4, 4),
        "wf_sharpe_std": round(wf_sharpe_std, 4),
        "wf_sharpe_min": round(wf_sharpe_min, 4),
        "sensitivity_pass": sensitivity_pass,
        "sensitivity_max_delta_pct": round(float(variance_pct * 100) if not np.isnan(variance_pct) else 0.0, 2),
        "sweep_sharpe_min": round(min(valid_sharpes), 4) if valid_sharpes else None,
        "sweep_sharpe_max": round(max(valid_sharpes), 4) if valid_sharpes else None,
        "gate_is_sharpe": gate_is_sharpe,
        "gate_oos_sharpe": gate_oos_sharpe,
        "gate_is_cagr": gate_is_cagr,
        "gate_is_mdd": gate_is_mdd,
        "gate_oos_mdd": gate_oos_mdd,
        "gate_wf": gate_wf,
        "gate_perm": gate_perm,
        "gate_trades": gate_trades,
        "gate_dsr": gate_dsr,
        "gate_pf1_switches": gate_switches,
        "gate1_pass": verdict_label == "PASS",
        "n_checks_passed": n_passed,
        "regime_bearish_is_months": regime_bearish_months,
        "is_total_months": len(is_sigs_months),
        "pf2_gfc_shy_months": len(gfc_shy_months),
        "pf2_gfc_first_shy": str(gfc_shy_months[0].date()) if gfc_shy_months else "none",
        "pf4_rate_shock_shy_months": len(rate_shy_months),
        "pf4_rate_shock_first_shy": str(rate_shy_months[0].date()) if rate_shy_months else "none",
        "data_quality": dq,
    }

    # ── Save Outputs ───────────────────────────────────────────────────────────
    base = f"H75_EquityCarryDividendYield_{TODAY}"

    json_path = OUT_DIR / f"{base}.json"
    with open(json_path, "w") as f:
        json.dump(metrics_json, f, indent=2, default=str)
    print(f"\nSaved metrics: {json_path}")

    all_trades = is_result["trade_log"] + oos_result["trade_log"]
    if all_trades:
        trades_df = pd.DataFrame(all_trades)
        trades_path = OUT_DIR / f"{base}_trades.csv"
        trades_df.to_csv(trades_path, index=False)
        print(f"Saved trades: {trades_path} ({len(trades_df)} entries)")

    if sweep_rows:
        sweep_df = pd.DataFrame(sweep_rows)
        sweep_path = OUT_DIR / f"{base}_sweep.csv"
        sweep_df.to_csv(sweep_path, index=False)
        print(f"Saved sweep: {sweep_path}")

    # Verdict TXT
    verdict_lines = [
        f"H75 Equity Carry — Dividend Yield Sector Rotation — Gate 1 Verdict",
        f"{'='*70}",
        f"Date:     {TODAY}",
        f"Strategy: {STRATEGY_NAME}",
        f"Overall:  {verdict_label} ({n_passed}/{len(checks)} checks passed)",
        f"{'='*70}",
        f"",
        f"=== Universe ===",
        f"Sectors:  {', '.join(SECTOR_UNIVERSE)}",
        f"Regime:   SPY 200-DMA → exit to SHY",
        f"Signal:   trailing {PARAMETERS['yield_lookback_months']}M dividend yield rank, top-{PARAMETERS['top_k']} equal weight",
        f"Academic: Koijen, Moskowitz, Pedersen & Vrugt (2018) JFE 127(2)",
        f"XLRE:     excluded pre-Oct-2015 (not yet launched)",
        f"",
        f"=== IS Performance ({IS_START} to {IS_END}, ~18 years) ===",
        f"Sharpe:              {is_sharpe:.4f}    [{'PASS' if gate_is_sharpe else 'FAIL'}: > 1.0]",
        f"CAGR:                {is_cagr:.2%}    [{'PASS' if gate_is_cagr else 'FAIL'}: >= 10%]",
        f"Max Drawdown:        {is_mdd:.2%}    [{'PASS' if gate_is_mdd else 'FAIL'}: > -15%]",
        f"Win Rate:            {is_metrics['win_rate']:.2%}",
        f"Profit Factor:       {is_metrics['profit_factor']}",
        f"Trade Count:         {is_trades}    [{'PASS' if gate_trades else 'FAIL'}: >= 100]",
        f"Position Switches:   {is_switch_count}    [{'PASS' if gate_switches else 'FAIL'}: >= 60]",
        f"Avg PpT:             {is_metrics['avg_ppt_bps']:.2f} bps",
        f"Regime-SHY months:   {regime_bearish_months}/{len(is_sigs_months)} IS months",
        f"PF-2 GFC (2008-09):  {len(gfc_shy_months)} SHY months; first exit: {gfc_shy_months[0].date() if gfc_shy_months else 'none'}",
        f"PF-4 Rate shock 2022:{len(rate_shy_months)} SHY months; first exit: {rate_shy_months[0].date() if rate_shy_months else 'none'}",
        f"",
        f"=== OOS Performance ({OOS_START} to {OOS_END}, ~2 years) ===",
        f"Sharpe:              {oos_sharpe:.4f}  [{'PASS' if gate_oos_sharpe else 'FAIL'}: > 0.70]",
        f"CAGR:                {oos_metrics['cagr']:.2%}",
        f"Max Drawdown:        {oos_mdd:.2%}  [{'PASS' if gate_oos_mdd else 'FAIL'}: > -15%]",
        f"Win Rate:            {oos_metrics['win_rate']:.2%}",
        f"Profit Factor:       {oos_metrics['profit_factor']}",
        f"Trade Count:         {oos_metrics['trade_count']}",
        f"Position Switches:   {oos_switch_count}",
        f"",
        f"=== Statistical Rigor ===",
        f"MC p5 Sharpe:        {mc['mc_p5_sharpe']:.4f}",
        f"MC Median Sharpe:    {mc['mc_median_sharpe']:.4f}",
        f"Sharpe 95% CI:       [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]  (block bootstrap)",
        f"MDD 95% CI:          [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]",
        f"Permutation p-value: {perm['permutation_pvalue']:.4f}    [{'PASS' if gate_perm else 'FAIL'}: < 0.05]",
        f"DSR:                 {dsr:.4f}    [{'PASS' if gate_dsr else 'FAIL'}: > 0]",
        f"Max Market Impact:   {max_mi_bps:.4f} bps",
        f"",
        f"=== Walk-Forward Analysis (4 IS Windows) ===",
    ]
    for w in wf_results:
        s = w.get("sharpe", 0.0)
        verdict_lines.append(
            f"  Window {w['window']}: {w['is_start']}–{w['is_end']}: "
            f"Sharpe={s:.4f} {'✓' if s > 0.0 else '✗'}, "
            f"MDD={w.get('max_drawdown', 0):.2%}, trades={w.get('trade_count', 0)}"
        )
    verdict_lines += [
        f"  WF Passed: {wf_passed}/4   [{'PASS' if gate_wf else 'FAIL'}: >= 3/4]",
        f"  WF Sharpe std: {wf_sharpe_std:.4f}",
        f"  WF Sharpe min: {wf_sharpe_min:.4f}",
        f"",
        f"=== Sensitivity Sweep (18 combinations: yield_lookback × top_k × spy_filter) ===",
    ]
    if valid_sharpes:
        verdict_lines.append(f"  Sharpe range: {min(valid_sharpes):.4f} – {max(valid_sharpes):.4f}")
        verdict_lines.append(
            f"  Variance vs primary: {variance_pct:.1%} ({'PASS' if sensitivity_pass else 'FAIL'} < 30%)"
        )
    verdict_lines += [
        f"  See: {base}_sweep.csv",
        f"",
        f"=== Research Director Note ===",
        f"IS Sharpe > 1.0 may be difficult for equity carry strategy (Koijen et al. estimate 0.4–0.8).",
        f"If IS Sharpe is 0.6–0.9, results are documented as carry premium evidence.",
        f"OOS Sharpe > 0.7 and walk-forward stability are key secondary indicators.",
        f"",
        f"=== Gate 1 Checks ===",
    ]
    for g, v, t, p in checks:
        verdict_lines.append(f"  [{'PASS' if p else 'FAIL'}] {g:<22} {v}  (threshold: {t})")

    if verdict_label == "PASS":
        verdict_lines += [
            f"",
            f"=== Recommendation ===",
            f"PASS — advance to paper trading. Notify CEO for approval.",
        ]
    else:
        failed = [(g, v, t) for g, v, t, p in checks if not p]
        verdict_lines += [
            f"",
            f"=== Root Cause Analysis ===",
            f"Primary failures ({len(failed)} of {len(checks)} gates):",
        ]
        for g, v, t in failed:
            verdict_lines.append(f"  - {g}: got {v}, need {t}")
        verdict_lines += [
            f"",
            f"=== Recommendation ===",
            f"REJECT — do not advance to paper trading. Return to Research Director with metrics.",
            f"Note: If IS Sharpe in 0.6–0.9 range, carry premium evidence is still valuable.",
        ]

    verdict_lines += [
        f"",
        f"=== Files ===",
        f"Metrics: backtests/{base}.json",
        f"Trades:  backtests/{base}_trades.csv",
        f"Sweep:   backtests/{base}_sweep.csv",
        f"Report:  backtests/{base}_report.html",
        f"Verdict: backtests/{base}_verdict.txt",
    ]

    verdict_text = "\n".join(verdict_lines)
    verdict_path = OUT_DIR / f"{base}_verdict.txt"
    verdict_path.write_text(verdict_text)
    print(f"Saved verdict: {verdict_path}")

    # HTML Report
    html = build_html_report(
        is_metrics, oos_metrics, wf_results, sweep_rows,
        mi_report, mc, bb, perm, dsr, verdict_label, checks,
        regime_bearish_months, len(is_sigs_months), is_switch_count,
    )
    html_path = OUT_DIR / f"{base}_report.html"
    html_path.write_text(html)
    print(f"Saved HTML: {html_path}")

    print(f"\nAll outputs → {OUT_DIR}/")
    print(f"  Metrics: {base}.json")
    print(f"  Report:  {base}_report.html")
    print(f"  Sweep:   {base}_sweep.csv")
    print(f"  Trades:  {base}_trades.csv")
    print(f"  Verdict: {base}_verdict.txt")
    print(f"\nGATE 1: {verdict_label} ({n_passed}/{len(checks)} checks)")

    return metrics_json, verdict_label


if __name__ == "__main__":
    metrics, verdict = main()
    sys.exit(0 if verdict == "PASS" else 1)
