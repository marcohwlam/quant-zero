"""
H73 Gate 1 Backtest Runner — Cross-Sectional Return Seasonality (Sector Calendar Rotation)
IS:  2003-01-01 to 2023-12-31 (21 years)
OOS: 2024-01-01 to 2026-06-16 (~2.5 years)
Walk-forward: 4 non-overlapping IS windows (~5yr each)
Parameter sweep: 18 combos (lookback_years × top_k × use_regime_filter)
Parent: QUA-313 | Hypothesis: H73 | Source: Keloharju et al. (2016), JF
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
STRATEGY_NAME = "H73_CrossSectionalReturnSeasonality"
OUT_DIR = REPO_ROOT / "backtests"
TRADING_DAYS = 252

# 10-sector universe: 9 SPDR ETFs + VNQ (real estate proxy); no XLC
SECTOR_TICKERS = ["XLK", "XLV", "XLE", "XLF", "XLY", "XLP", "XLU", "XLI", "XLB", "VNQ"]
REGIME_ETF = "SPY"
SAFE_HAVEN = "SHY"
ALL_DL = SECTOR_TICKERS + [REGIME_ETF, SAFE_HAVEN]

# Primary parameters
PARAMETERS = {
    "seasonal_lookback_years": 10,
    "top_k_sectors": 2,
    "use_regime_filter": True,
    "regime_ma_days": 200,
    "init_capital": 100_000.0,
    "slippage": 0.0005,        # 0.05% standard ETF tier (sector ETFs ADV << 50M/day)
    "commission_per_share": 0.005,
    "market_impact_k": 0.1,    # Almgren-Chriss
}

IS_START  = "2003-01-01"
IS_END    = "2023-12-31"
OOS_START = "2024-01-01"
OOS_END   = "2026-06-16"
DATA_START = "1993-01-01"   # SPY from 1993; sector ETFs from Dec 1998

# Walk-forward: 4 non-overlapping IS windows (~5yr each)
# Each window: (wf_start, wf_end) covering the IS period in 4 slices
WF_IS_WINDOWS = [
    ("2003-01-01", "2007-12-31"),
    ("2008-01-01", "2012-12-31"),
    ("2013-01-01", "2017-12-31"),
    ("2018-01-01", "2023-12-31"),
]

# Parameter sweep: 3 × 3 × 2 = 18 combinations
SWEEP_LOOKBACKS  = [5, 10, 15]
SWEEP_TOP_K      = [1, 2, 3]
SWEEP_REGIME     = [True, False]


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data(start: str = DATA_START, end: str = OOS_END) -> dict:
    print(f"H73: downloading {len(ALL_DL)} tickers from {start} to {end}...")
    raw = yf.download(ALL_DL, start=start, end=end, auto_adjust=True, progress=False)

    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex columns from yfinance multi-ticker download.")

    close  = raw["Close"][ALL_DL].copy()
    open_  = raw["Open"][ALL_DL].copy()
    volume = raw["Volume"][ALL_DL].copy()

    close  = close.dropna(how="all")
    open_  = open_.reindex(close.index)
    volume = volume.reindex(close.index)

    # Forward-fill up to 5 days to handle minor gaps
    close  = close.ffill(limit=5)
    open_  = open_.ffill(limit=5)

    print(f"H73: data shape {close.shape}, range {close.index[0].date()} – {close.index[-1].date()}")
    return {"close": close, "open_": open_, "volume": volume}


def data_quality_report(data: dict) -> dict:
    close = data["close"]
    report = {
        "universe": SECTOR_TICKERS,
        "regime_etf": REGIME_ETF,
        "safe_haven": SAFE_HAVEN,
        "survivorship_bias": (
            "Fixed 10-sector universe: 9 SPDR ETFs (inception Dec 1998) + VNQ (inception Sep 2004). "
            "All active ETFs. No delisting risk. No survivorship bias."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": (
            "N/A — sector ETFs are portfolios; earnings event windows not applicable."
        ),
        "tickers": {},
        "flagged": [],
    }
    for t in ALL_DL:
        if t not in close.columns:
            report["tickers"][t] = {"error": "not found"}
            report["flagged"].append(t)
            continue
        s = close[t].dropna()
        if len(s) == 0:
            report["tickers"][t] = {"error": "no data"}
            report["flagged"].append(t)
            continue
        trimmed = close[t].loc[s.index[0]:]
        max_gap = consec = 0
        for v in trimmed.isna():
            consec = (consec + 1) if v else 0
            max_gap = max(max_gap, consec)
        if max_gap > 5:
            report["flagged"].append(t)
            warnings.warn(f"Data gap flag: {t} has {max_gap} consecutive missing days")
        report["tickers"][t] = {
            "total_obs": int(len(s)),
            "start": str(s.index.min().date()),
            "end":   str(s.index.max().date()),
            "max_consecutive_missing": max_gap,
            "gap_flag": max_gap > 5,
        }
    return report


# ── Monthly Return Computation ─────────────────────────────────────────────────

def get_last_trading_days(close: pd.DataFrame) -> pd.DatetimeIndex:
    helper = pd.Series(close.index, index=close.index)
    last_days = helper.resample("ME").last().dropna()
    return pd.DatetimeIndex(last_days.values)


def compute_sector_monthly(close: pd.DataFrame) -> pd.DataFrame:
    """
    Monthly returns at last-trading-day for each sector ETF.
    Row i: return from ltd[i-1] to ltd[i] (no look-ahead).
    """
    ltd = get_last_trading_days(close)
    prices_at_ltd = close[SECTOR_TICKERS].reindex(ltd).ffill(limit=3)
    monthly = prices_at_ltd.pct_change()  # NaN for first row (no prior month)
    return monthly


# ── Seasonal Signal Computation ────────────────────────────────────────────────

def compute_seasonal_score(
    sector_monthly: pd.DataFrame,
    t: pd.Timestamp,
    lookback_years: int,
    available_tickers: list,
) -> dict:
    """
    For month-end date t, compute average monthly return in same calendar month
    over trailing lookback_years using strictly historical data (years < t.year).
    Returns {ticker: score} dict.
    """
    cal_month = t.month
    start_year = t.year - lookback_years

    scores = {}
    for ticker in available_tickers:
        if ticker not in sector_monthly.columns:
            continue
        hist = sector_monthly[ticker].loc[
            (sector_monthly.index.month == cal_month) &
            (sector_monthly.index.year >= start_year) &
            (sector_monthly.index.year < t.year)   # strictly before current year
        ].dropna()
        if len(hist) >= 2:  # need at least 2 observations
            scores[ticker] = float(hist.mean())
    return scores


def compute_all_signals(
    sector_monthly: pd.DataFrame,
    spy_close_daily: pd.Series,
    params: dict,
    all_ltd: pd.DatetimeIndex,
) -> dict:
    """
    Compute target positions for every month-end in all_ltd.
    Returns dict[Timestamp] → {"tickers": [...], "regime_bearish": bool, "scores": dict}
    """
    lookback_years   = params["seasonal_lookback_years"]
    top_k            = params["top_k_sectors"]
    use_filter       = params["use_regime_filter"]
    ma_days          = params.get("regime_ma_days", 200)

    spy_ma = spy_close_daily.rolling(ma_days, min_periods=max(1, ma_days // 2)).mean()

    # Sector tickers available per date (VNQ starts Sep 2004)
    signals = {}
    for t in all_ltd:
        # Available tickers: those with at least some data before this date
        avail = [
            tk for tk in SECTOR_TICKERS
            if tk in sector_monthly.columns
            and sector_monthly[tk].loc[
                (sector_monthly.index.month == t.month) &
                (sector_monthly.index.year < t.year)
            ].dropna().shape[0] >= 2
        ]

        # Regime filter
        spy_ma_val    = spy_ma.get(t, np.nan)
        spy_close_val = spy_close_daily.get(t, np.nan)
        if use_filter and not np.isnan(spy_ma_val) and not np.isnan(spy_close_val):
            regime_bearish = bool(spy_close_val < spy_ma_val)
        else:
            regime_bearish = False

        if regime_bearish:
            signals[t] = {"tickers": [SAFE_HAVEN], "regime_bearish": True, "scores": {}}
            continue

        scores = compute_seasonal_score(sector_monthly, t, lookback_years, avail)
        if not scores:
            # Insufficient history — use equal weight of first top_k tickers
            target = avail[:top_k] if avail else [SAFE_HAVEN]
        else:
            sorted_tickers = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
            target = sorted_tickers[:top_k]

        signals[t] = {"tickers": target, "regime_bearish": False, "scores": scores}

    return signals


# ── Transaction Costs ──────────────────────────────────────────────────────────

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
    slip   = params["slippage"]
    comm   = params["commission_per_share"]
    k      = params["market_impact_k"]
    adv    = max(float(adv or 1e6), 1.0)
    sigma  = float(sigma or 0.0)
    q_adv  = shares / adv
    impact = k * sigma * np.sqrt(max(q_adv, 0.0))
    cost_per_share = price * (slip + impact) + comm
    return cost_per_share, q_adv > 0.01, round(q_adv, 8)


def sell_cost_model(ticker, shares, price, sigma, adv, params):
    """Returns (net_proceeds, liquidity_constrained, q_over_adv)."""
    slip   = params["slippage"]
    comm   = params["commission_per_share"]
    k      = params["market_impact_k"]
    adv    = max(float(adv or 1e6), 1.0)
    sigma  = float(sigma or 0.0)
    q_adv  = shares / adv
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
    Executes pending rebalance at open of first trading day after month-end signal.
    """
    close  = data["close"]
    open_  = data["open_"]
    volume = data["volume"]

    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)
    window   = close.loc[ts_start:ts_end].index

    if len(window) < 5:
        raise ValueError(f"Insufficient data {start}:{end}: {len(window)} days")

    init_cap = params["init_capital"]
    all_tickers_sim = SECTOR_TICKERS + [SAFE_HAVEN]

    # Rolling vol and ADV for transaction costs
    sigma_20 = {}
    adv_20   = {}
    for tk in all_tickers_sim:
        if tk in close.columns:
            sigma_20[tk] = close[tk].pct_change().rolling(20, min_periods=5).std()
        if tk in volume.columns:
            adv_20[tk] = volume[tk].rolling(20, min_periods=5).mean()

    # Month-end dates within window that have signals
    window_signals = {d: s for d, s in signals.items()
                      if ts_start <= d <= ts_end}

    # Initial target: last signal before window start, or first in window
    prior = {d: s for d, s in signals.items() if d < ts_start}
    if prior:
        init_sig = prior[max(prior.keys())]
    else:
        first_sig_date = min(window_signals.keys()) if window_signals else None
        init_sig = window_signals.get(first_sig_date, {"tickers": [SAFE_HAVEN]})

    # State
    cash        = float(init_cap)
    positions   = {}   # ticker → shares
    entry_info  = {}   # ticker → {"price": float, "date": str}
    pending_tgt = list(init_sig["tickers"])   # execute on first day

    portfolio_values = pd.Series(index=window, dtype=float)
    trade_log        = []

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
            to_buy  = new_set - cur_set

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

                ei  = entry_info.pop(ticker, {"price": px, "date": str(t_day.date())})
                pnl = proceeds - sh * float(ei["price"])
                trade_log.append({
                    "period":     period_label,
                    "ticker":     ticker,
                    "entry_date": ei["date"],
                    "exit_date":  str(t_day.date()),
                    "entry_price": round(float(ei["price"]), 4),
                    "exit_price":  round(float(px), 4),
                    "shares":      round(float(sh), 4),
                    "pnl":         round(float(pnl), 2),
                    "exit_reason": "rebalance",
                    "liquidity_constrained": liq,
                    "q_over_adv":  q_adv,
                })
                del positions[ticker]

            # Buy new positions (equal weight across ALL new_tickers)
            # Divide available cash equally among positions to buy
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
                    est_sh  = cash_per / (px + 1e-8)  # rough share estimate
                    cps, liq, q_adv = buy_cost_model(ticker, est_sh, px, sig_v, adv_v, params)
                    total_per_share = px + cps
                    sh = cash_per / total_per_share if total_per_share > 0 else 0.0
                    sh = max(sh, 0.0)
                    spent = sh * total_per_share
                    cash -= spent
                    if sh > 0:
                        positions[ticker] = sh
                        entry_info[ticker] = {"price": float(px), "date": str(t_day.date())}

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

    # Final close-out (mark-to-market only, no trade cost)
    if positions:
        last_t = window[-1]
        for ticker, sh in list(positions.items()):
            px = gp(close, ticker, last_t)
            if np.isnan(px) or px <= 0:
                continue
            ei  = entry_info.pop(ticker, {"price": px, "date": str(last_t.date())})
            pnl = sh * px - sh * float(ei["price"])
            trade_log.append({
                "period":      period_label,
                "ticker":      ticker,
                "entry_date":  ei["date"],
                "exit_date":   str(last_t.date()),
                "entry_price": round(float(ei["price"]), 4),
                "exit_price":  round(float(px), 4),
                "shares":      round(float(sh), 4),
                "pnl":         round(float(pnl), 2),
                "exit_reason": "window_end",
                "liquidity_constrained": False,
                "q_over_adv":  0.0,
            })

    portfolio_values = portfolio_values.ffill().fillna(float(init_cap))
    return {"portfolio_values": portfolio_values, "trade_log": trade_log}


# ── Metrics ────────────────────────────────────────────────────────────────────

def compute_metrics(portfolio_values: pd.Series, trade_log: list, start: str, end: str) -> dict:
    pv = portfolio_values.dropna()
    if len(pv) < 2:
        return {"error": "Insufficient data"}

    daily_ret = pv.pct_change().fillna(0.0).values
    sharpe    = float(daily_ret.mean() / (daily_ret.std() + 1e-10) * np.sqrt(TRADING_DAYS))

    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)
    years    = (ts_end - ts_start).days / 365.25
    total_ret = float(pv.iloc[-1] / pv.iloc[0] - 1)
    cagr      = float((pv.iloc[-1] / pv.iloc[0]) ** (1.0 / max(years, 0.01)) - 1)

    cum      = np.cumprod(1 + daily_ret)
    roll_max = np.maximum.accumulate(cum)
    mdd      = float(np.min((cum - roll_max) / (roll_max + 1e-10)))

    closed = [t for t in trade_log if t.get("exit_reason") != "window_end"]
    switches = [t for t in closed if t.get("exit_reason") == "rebalance"]

    if closed:
        pnl_arr = np.array([t["pnl"] for t in closed])
        win_rate = float(np.mean(pnl_arr > 0))
        wins   = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        pf = float(wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 0 else float("inf")
        avg_ppt_bps = float(np.mean(pnl_arr / (portfolio_values.iloc[0] + 1e-8) * 10_000))
    else:
        win_rate = pf = avg_ppt_bps = 0.0

    return {
        "sharpe":         round(sharpe, 4),
        "cagr":           round(cagr, 4),
        "max_drawdown":   round(mdd, 4),
        "total_return":   round(total_ret, 4),
        "trade_count":    len(closed),
        "position_switches": len(switches),
        "win_rate":       round(win_rate, 4),
        "profit_factor":  round(pf, 4) if not np.isinf(pf) else "inf",
        "avg_ppt_bps":    round(avg_ppt_bps, 2),
        "period":         f"{start} to {end}",
        "years":          round(years, 2),
    }


# ── Statistical Rigor Pipeline ─────────────────────────────────────────────────

def monte_carlo_sharpe(pnl_arr: np.ndarray, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    if len(pnl_arr) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0, "mc_flag": "insufficient trades"}
    sharpes = []
    for _ in range(n_sims):
        s = np.random.choice(pnl_arr, size=len(pnl_arr), replace=True)
        sh = s.mean() / (s.std() + 1e-8) * np.sqrt(TRADING_DAYS)
        sharpes.append(sh)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe":    float(np.percentile(arr, 95)),
        "mc_flag":          f"MC on {len(pnl_arr)} IS trade PnLs",
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    np.random.seed(43)
    T = len(returns)
    block_len = max(1, int(np.sqrt(T)))
    n_blocks  = max(1, T // block_len)
    sharpes, mdds, win_rates = [], [], []
    for _ in range(n_boots):
        starts = np.random.randint(0, max(1, T - block_len + 1), size=n_blocks)
        sample = np.concatenate([returns[s: s + block_len] for s in starts])[:T]
        if len(sample) < 2:
            continue
        cum = np.cumprod(1 + sample)
        roll_max = np.maximum.accumulate(cum)
        mdd = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
        sh  = float(sample.mean() / (sample.std() + 1e-8) * np.sqrt(TRADING_DAYS))
        wr  = float(np.mean(sample > 0))
        sharpes.append(sh); mdds.append(mdd); win_rates.append(wr)
    if not sharpes:
        return {"sharpe_ci_low": 0.0, "sharpe_ci_high": 0.0,
                "mdd_ci_low": 0.0,    "mdd_ci_high": 0.0,
                "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0}
    return {
        "sharpe_ci_low":    float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high":   float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":       float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":      float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low":  float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def permutation_test(
    sector_monthly: pd.DataFrame,
    signals: dict,
    observed_sharpe: float,
    start: str,
    end: str,
    n_perms: int = 1000,
) -> dict:
    """
    Seasonal rotation permutation test: randomly shuffle which calendar months
    each sector's historical return belongs to, recompute rankings, re-simulate.
    Compare re-simulated Sharpe to observed.
    """
    np.random.seed(44)
    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)

    # Extract monthly return series in IS window for all sectors
    is_monthly = sector_monthly.loc[ts_start:ts_end].dropna(how="all")
    if len(is_monthly) < 10:
        return {"permutation_pvalue": 0.5, "permutation_test_pass": False,
                "permutation_note": "insufficient data for permutation test"}

    months_list = is_monthly.index.tolist()
    n_months = len(months_list)

    perm_sharpes = []
    for _ in range(n_perms):
        # Shuffle month order → shuffled monthly returns per sector
        perm_idx = np.random.permutation(n_months)
        perm_returns = is_monthly.values[perm_idx, :]  # (n_months, n_sectors)

        # Compute cumulative "permuted" portfolio return
        # Each month: pick top_k sectors by their 10-year seasonal average using permuted data
        # Simplified: just compute the monthly portfolio return under random shuffled assignment
        monthly_pf_ret = 0.0
        k = PARAMETERS["top_k_sectors"]
        for m_i, t_date in enumerate(months_list[1:], 1):
            # Use permuted returns for ranking (lookback: prior 10*12 months)
            lb = max(0, m_i - 10 * 12)
            lookback_slice = perm_returns[lb:m_i, :]  # (lookback, n_sectors)
            # Group by calendar month
            cal_m = t_date.month
            hist_months_mask = np.array([
                months_list[j].month == cal_m for j in range(lb, m_i)
            ])
            scores_perm = lookback_slice[hist_months_mask, :].mean(axis=0)
            top_k_idx = np.argsort(scores_perm)[::-1][:k]
            # Monthly return of permuted portfolio
            pf_ret = float(np.nanmean(perm_returns[m_i, top_k_idx]))
            monthly_pf_ret += pf_ret

        # Annualized permuted Sharpe from monthly returns (simplified)
        perm_arr = np.array([
            float(np.nanmean(perm_returns[m_i, np.argsort(perm_returns[max(0,m_i-120):m_i, :].mean(axis=0))[::-1][:PARAMETERS["top_k_sectors"]]]))
            for m_i in range(1, n_months)
        ])
        if perm_arr.std() > 0:
            s = float(perm_arr.mean() / perm_arr.std() * np.sqrt(12))
        else:
            s = 0.0
        perm_sharpes.append(s)

    perm_arr_np = np.array(perm_sharpes)
    p_value = float(np.mean(perm_arr_np >= observed_sharpe))
    return {
        "permutation_pvalue":      round(p_value, 4),
        "permutation_test_pass":   p_value <= 0.05,
        "permutation_perm_mean":   float(perm_arr_np.mean()),
        "permutation_perm_p95":    float(np.percentile(perm_arr_np, 95)),
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
    """Market impact at typical $100K / 2 positions = $50K per sector."""
    close  = data["close"]
    volume = data["volume"]
    results = {}
    for ticker in SECTOR_TICKERS:
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
            cap_per_position = 50_000.0  # $50K in one sector
            qty = cap_per_position / max(avg_price, 1.0)
            q_adv = qty / max(adv, 1.0)
            impact = 0.1 * sigma * np.sqrt(max(q_adv, 0.0))
            impact_bps = impact * 10_000
            results[ticker] = {
                "market_impact_bps": round(float(impact_bps), 4),
                "adv_20d":           round(float(adv), 0),
                "avg_price":         round(float(avg_price), 2),
                "qty_at_50k":        round(float(qty), 0),
                "q_over_adv":        round(float(q_adv), 6),
                "liquidity_constrained": q_adv > 0.01,
            }
        except Exception as e:
            results[ticker] = {"market_impact_bps": 0.0, "error": str(e)}
    return results


# ── Walk-Forward Analysis ──────────────────────────────────────────────────────

def run_walk_forward(
    data: dict,
    sector_monthly: pd.DataFrame,
    params: dict,
    wf_windows: list,
) -> list:
    """Run each IS-only WF window independently; report Sharpe + trade count."""
    results = []
    all_ltd = get_last_trading_days(data["close"])
    spy_close_daily = data["close"][REGIME_ETF].dropna()

    for i, (wf_start, wf_end) in enumerate(wf_windows):
        try:
            wf_signals = compute_all_signals(sector_monthly, spy_close_daily, params, all_ltd)
            wf_result  = run_backtest(data, wf_signals, params, wf_start, wf_end, f"WF{i+1}")
            wf_metrics = compute_metrics(
                wf_result["portfolio_values"], wf_result["trade_log"], wf_start, wf_end
            )
            results.append({
                "window":      i + 1,
                "is_start":    wf_start,
                "is_end":      wf_end,
                "sharpe":      wf_metrics["sharpe"],
                "max_drawdown": wf_metrics["max_drawdown"],
                "win_rate":    wf_metrics["win_rate"],
                "trade_count": wf_metrics["trade_count"],
                "position_switches": wf_metrics["position_switches"],
                "cagr":        wf_metrics["cagr"],
            })
            print(f"  WF{i+1} ({wf_start}–{wf_end}): Sharpe={wf_metrics['sharpe']:.3f}, "
                  f"MDD={wf_metrics['max_drawdown']:.2%}, trades={wf_metrics['trade_count']}, "
                  f"switches={wf_metrics['position_switches']}")
        except Exception as e:
            results.append({
                "window": i + 1, "is_start": wf_start, "is_end": wf_end,
                "sharpe": 0.0, "error": str(e),
            })
            print(f"  WF{i+1} ERROR: {e}")

    return results


# ── Parameter Sweep ────────────────────────────────────────────────────────────

def run_sweep(
    data: dict,
    sector_monthly: pd.DataFrame,
    all_ltd: pd.DatetimeIndex,
    spy_close_daily: pd.Series,
) -> list:
    """18-combination sweep on IS (lookback × top_k × regime_filter)."""
    rows = []
    combos = list(iproduct(SWEEP_LOOKBACKS, SWEEP_TOP_K, SWEEP_REGIME))
    print(f"  Running {len(combos)} sweep combinations...")

    for lookback, top_k, use_reg in combos:
        p = {**PARAMETERS, "seasonal_lookback_years": lookback,
             "top_k_sectors": top_k, "use_regime_filter": use_reg}
        label = f"lb={lookback}, k={top_k}, regime={'Y' if use_reg else 'N'}"
        try:
            sigs = compute_all_signals(sector_monthly, spy_close_daily, p, all_ltd)
            res  = run_backtest(data, sigs, p, IS_START, IS_END, "SWEEP")
            m    = compute_metrics(res["portfolio_values"], res["trade_log"], IS_START, IS_END)
            rows.append({
                "seasonal_lookback_years": lookback,
                "top_k_sectors": top_k,
                "use_regime_filter": use_reg,
                "sharpe":      m["sharpe"],
                "cagr":        m["cagr"],
                "max_drawdown": m["max_drawdown"],
                "win_rate":    m["win_rate"],
                "trade_count": m["trade_count"],
                "position_switches": m["position_switches"],
                "total_return": m["total_return"],
            })
            print(f"    {label}: Sharpe={m['sharpe']:.3f}, MDD={m['max_drawdown']:.2%}, "
                  f"trades={m['trade_count']}, switches={m['position_switches']}")
        except Exception as e:
            rows.append({
                "seasonal_lookback_years": lookback, "top_k_sectors": top_k,
                "use_regime_filter": use_reg, "error": str(e),
            })
            print(f"    {label}: ERROR {e}")

    return rows


# ── HTML Report ────────────────────────────────────────────────────────────────

def build_html_report(
    is_m: dict, oos_m: dict, wf_results: list, sweep_rows: list,
    mi_report: dict, mc: dict, bb: dict, perm: dict, dsr: float,
    verdict_label: str, checks: list,
) -> str:
    verdict_color = "#d4edda" if verdict_label == "PASS" else "#f8d7da"
    check_rows = "".join(
        f"<tr style='background:{'#d4edda' if p else '#f8d7da'}'>"
        f"<td>{g}</td><td>{v}</td><td>{t}</td><td>{'✓ PASS' if p else '✗ FAIL'}</td></tr>"
        for g, v, t, p in checks
    )
    wf_rows = "".join(
        f"<tr><td>{w['window']}</td><td>{w['is_start']}–{w['is_end']}</td>"
        f"<td>{w.get('sharpe', 'ERR'):.4f}</td><td>{w.get('max_drawdown', 0):.2%}</td>"
        f"<td>{w.get('win_rate', 0):.2%}</td><td>{w.get('trade_count', 0)}</td>"
        f"<td>{w.get('position_switches', 0)}</td></tr>"
        for w in wf_results
    )
    sweep_df = pd.DataFrame(sweep_rows)
    sweep_html = sweep_df.to_html(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x), border=1)
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
<title>H73 Cross-Sectional Return Seasonality — Gate 1 Report</title>
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
</style>
</head>
<body>
<h1>H73 Cross-Sectional Return Seasonality — Gate 1 Report</h1>
<p><strong>Date:</strong> {TODAY} | <strong>Universe:</strong> {', '.join(SECTOR_TICKERS)}</p>
<p><strong>Signal:</strong> 10-year trailing same-calendar-month average return | <strong>Filter:</strong> SPY 200-DMA → SHY</p>
<p><strong>Academic source:</strong> Keloharju, Linnainmaa &amp; Nyberg (2016), Journal of Finance 71(4)</p>
<p><strong>Slippage:</strong> 0.05% standard ETF tier (sector ETFs ADV &lt;&lt; 50M shares/day)</p>

<div class="verdict">GATE 1: {verdict_label}</div>

<h2>Gate 1 Checklist</h2>
<table><tr><th>Gate</th><th>Value</th><th>Threshold</th><th>Result</th></tr>{check_rows}</table>

<h2>IS / OOS Summary</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>IS (2003–2023)</th><th>OOS (2024–2026-06)</th></tr>
<tr><td>Sharpe</td><td>{is_m['sharpe']:.4f}</td><td>{oos_m['sharpe']:.4f}</td></tr>
<tr><td>CAGR</td><td>{is_m['cagr']:.2%}</td><td>{oos_m['cagr']:.2%}</td></tr>
<tr><td>Max Drawdown</td><td>{is_m['max_drawdown']:.2%}</td><td>{oos_m['max_drawdown']:.2%}</td></tr>
<tr><td>Win Rate</td><td>{is_m['win_rate']:.2%}</td><td>{oos_m['win_rate']:.2%}</td></tr>
<tr><td>Profit Factor</td><td>{is_m['profit_factor']}</td><td>{oos_m['profit_factor']}</td></tr>
<tr><td>Trade Count</td><td>{is_m['trade_count']}</td><td>{oos_m['trade_count']}</td></tr>
<tr><td>Position Switches</td><td>{is_m['position_switches']}</td><td>{oos_m['position_switches']}</td></tr>
<tr><td>Avg PpT (bps)</td><td>{is_m['avg_ppt_bps']:.2f}</td><td>{oos_m['avg_ppt_bps']:.2f}</td></tr>
</table>
</div>

<h2>Walk-Forward Analysis (4 IS Windows)</h2>
<table>
<tr><th>Window</th><th>Period</th><th>Sharpe</th><th>MDD</th><th>Win Rate</th><th>Trades</th><th>Switches</th></tr>
{wf_rows}
</table>

<h2>Statistical Tests</h2>
<div class="section">
<p><strong>Monte Carlo (1000 resamples on IS trade PnLs):</strong> p5={mc['mc_p5_sharpe']:.4f}, median={mc['mc_median_sharpe']:.4f}, p95={mc['mc_p95_sharpe']:.4f}</p>
<p><strong>Block Bootstrap CI (95%):</strong> Sharpe [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]  MDD [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]</p>
<p><strong>Permutation test (1000 perms, shuffled calendar months):</strong> p={perm['permutation_pvalue']:.4f} — {"PASS" if perm['permutation_test_pass'] else "FAIL"}</p>
<p><strong>DSR (Deflated Sharpe Ratio):</strong> {dsr:.4f}</p>
</div>

<h2>Parameter Sweep (18 Combinations)</h2>
{sweep_html}

<h2>Market Impact by Ticker</h2>
<table>
<tr><th>Ticker</th><th>Impact (bps)</th><th>ADV 20d</th><th>Q/ADV</th><th>Liq. Constrained</th></tr>
{mi_rows}
</table>

<hr>
<p><em>Generated by Engineering Director (QUA-313) | H73 Gate 1 | {TODAY}</em></p>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H73 Cross-Sectional Return Seasonality — Gate 1 Backtest — {TODAY}")
    print(f"Universe: {SECTOR_TICKERS}")
    print(f"IS: {IS_START} → {IS_END} | OOS: {OOS_START} → {OOS_END}")
    print(f"Signal: {PARAMETERS['seasonal_lookback_years']}yr seasonal avg "
          f"| Top-{PARAMETERS['top_k_sectors']} sectors | 200-DMA SPY filter")
    print("=" * 70)

    # ── [1/8] Data Download ───────────────────────────────────────────────────
    print("\n[1/8] Downloading data...")
    data = download_data(DATA_START, OOS_END)
    dq   = data_quality_report(data)
    if dq["flagged"]:
        warnings.warn(f"Data quality flags: {dq['flagged']}")

    close  = data["close"]
    spy_close_daily = close[REGIME_ETF].dropna()
    all_ltd = get_last_trading_days(close)

    # ── [2/8] Monthly Return Computation ─────────────────────────────────────
    print("\n[2/8] Computing monthly returns...")
    sector_monthly = compute_sector_monthly(close)
    print(f"  Monthly return matrix: {sector_monthly.shape} | range {sector_monthly.index[1].date()} – {sector_monthly.index[-1].date()}")

    # ── [3/8] Signal Computation ──────────────────────────────────────────────
    print("\n[3/8] Computing seasonal signals (primary params)...")
    all_signals = compute_all_signals(sector_monthly, spy_close_daily, PARAMETERS, all_ltd)
    print(f"  Signals computed: {len(all_signals)} month-end dates")

    # Quick PF-1 check: count IS position switches
    is_sigs_months = [d for d in all_signals if pd.Timestamp(IS_START) <= d <= pd.Timestamp(IS_END)]
    regime_bearish_months = sum(1 for d in is_sigs_months if all_signals[d]["regime_bearish"])
    print(f"  IS months: {len(is_sigs_months)} | Regime-bearish (SHY) months: {regime_bearish_months}")

    # ── [4/8] IS Backtest ─────────────────────────────────────────────────────
    print(f"\n[4/8] IS backtest ({IS_START} → {IS_END})...")
    is_result  = run_backtest(data, all_signals, PARAMETERS, IS_START, IS_END, "IS")
    is_metrics = compute_metrics(is_result["portfolio_values"], is_result["trade_log"], IS_START, IS_END)

    print(f"  IS Sharpe: {is_metrics['sharpe']:.4f} | CAGR: {is_metrics['cagr']:.2%} | "
          f"MDD: {is_metrics['max_drawdown']:.2%}")
    print(f"  IS trades: {is_metrics['trade_count']} | Switches: {is_metrics['position_switches']}")

    # PF-1 gate: flag if switches < 120
    if is_metrics["position_switches"] < 120:
        print(f"  ⚠  PF-1 FLAG: position switches {is_metrics['position_switches']} < 120 "
              f"(< 30 per WF window). Investigate before accepting results.")

    # ── [5/8] OOS Backtest ────────────────────────────────────────────────────
    print(f"\n[5/8] OOS backtest ({OOS_START} → {OOS_END})...")
    oos_result  = run_backtest(data, all_signals, PARAMETERS, OOS_START, OOS_END, "OOS")
    oos_metrics = compute_metrics(oos_result["portfolio_values"], oos_result["trade_log"], OOS_START, OOS_END)

    print(f"  OOS Sharpe: {oos_metrics['sharpe']:.4f} | CAGR: {oos_metrics['cagr']:.2%} | "
          f"MDD: {oos_metrics['max_drawdown']:.2%}")
    print(f"  OOS trades: {oos_metrics['trade_count']} | Switches: {oos_metrics['position_switches']}")

    # ── [6/8] Walk-Forward Analysis ───────────────────────────────────────────
    print("\n[6/8] Walk-forward analysis (4 IS windows)...")
    wf_results   = run_walk_forward(data, sector_monthly, PARAMETERS, WF_IS_WINDOWS)
    wf_sharpes   = [w.get("sharpe", 0.0) for w in wf_results]
    wf_passed    = sum(1 for s in wf_sharpes if s > 0.0)
    wf_sharpe_std = float(np.std(wf_sharpes)) if wf_sharpes else 0.0
    wf_sharpe_min = float(np.min(wf_sharpes)) if wf_sharpes else 0.0
    print(f"  WF passed (Sharpe>0): {wf_passed}/4 | std={wf_sharpe_std:.3f} | min={wf_sharpe_min:.3f}")

    # ── [7/8] Statistical Rigor Pipeline ─────────────────────────────────────
    print("\n[7/8] Statistical rigor pipeline...")
    is_trade_log = [t for t in is_result["trade_log"] if t.get("exit_reason") == "rebalance"]
    is_pnl_arr   = np.array([t["pnl"] for t in is_trade_log]) if is_trade_log else np.array([0.0])
    is_ret_arr   = is_result["portfolio_values"].pct_change().fillna(0.0).values

    mc   = monte_carlo_sharpe(is_pnl_arr)
    bb   = block_bootstrap_ci(is_ret_arr)
    perm = permutation_test(sector_monthly, all_signals, is_metrics["sharpe"], IS_START, IS_END)
    n_trials = 18 + 4  # sweep combos + WF windows
    T_is = len(is_result["portfolio_values"])
    dsr  = compute_dsr(is_metrics["sharpe"], n_trials, T_is)

    print(f"  MC p5={mc['mc_p5_sharpe']:.3f}, median={mc['mc_median_sharpe']:.3f}")
    print(f"  Bootstrap Sharpe CI: [{bb['sharpe_ci_low']:.3f}, {bb['sharpe_ci_high']:.3f}]")
    print(f"  Permutation p={perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})")
    print(f"  DSR={dsr:.4f}")

    # Market impact report
    print("  Computing market impact...")
    mi_report = compute_market_impact_report(data, IS_START, IS_END)
    max_mi_bps = max((v.get("market_impact_bps", 0) for v in mi_report.values()), default=0.0)
    print(f"  Max market impact: {max_mi_bps:.4f} bps")

    # ── [8/8] Parameter Sweep ─────────────────────────────────────────────────
    print("\n[8/8] Parameter sweep (18 combinations)...")
    sweep_rows = run_sweep(data, sector_monthly, all_ltd, spy_close_daily)
    valid_sharpes = [r["sharpe"] for r in sweep_rows if "sharpe" in r and isinstance(r["sharpe"], float)]
    if valid_sharpes:
        primary_sharpe = is_metrics["sharpe"]
        sharpe_range   = max(valid_sharpes) - min(valid_sharpes)
        variance_pct   = sharpe_range / abs(primary_sharpe) if primary_sharpe != 0 else float("nan")
        sensitivity_pass = not np.isnan(variance_pct) and variance_pct <= 0.30
    else:
        variance_pct = float("nan")
        sensitivity_pass = False
    print(f"  Sharpe range: {min(valid_sharpes):.3f} – {max(valid_sharpes):.3f} "
          f"| Variance: {variance_pct:.1%}" if valid_sharpes else "  No valid sweep results")
    print(f"  Sensitivity: {'PASS' if sensitivity_pass else 'FAIL'} (<30%)")

    # ── Gate 1 Verdict ────────────────────────────────────────────────────────
    is_sharpe     = is_metrics["sharpe"]
    oos_sharpe    = oos_metrics["sharpe"]
    is_mdd        = is_metrics["max_drawdown"]
    oos_mdd       = oos_metrics["max_drawdown"]
    is_cagr       = is_metrics["cagr"]
    is_trades     = is_metrics["trade_count"]
    is_switches   = is_metrics["position_switches"]

    # Track A (criteria.md v2.7): IS Sharpe > 1.0, OOS Sharpe > 0.70, CAGR >= 10%, MDD < -15%, WF ≥ 3/4, perm p < 0.05
    gate_is_sharpe   = is_sharpe > 1.0
    gate_oos_sharpe  = oos_sharpe > 0.70
    gate_is_cagr     = is_cagr >= 0.10
    gate_is_mdd      = is_mdd > -0.15      # < -15% magnitude means > -0.15 (less negative)
    gate_oos_mdd     = oos_mdd > -0.15
    gate_wf          = wf_passed >= 3
    gate_perm        = perm["permutation_test_pass"]
    gate_trades      = is_trades >= 100
    gate_dsr         = dsr > 0.0
    gate_switches    = is_switches >= 120   # PF-1 validation

    checks = [
        ("IS Sharpe",       f"{is_sharpe:.4f}",    "> 1.0",           gate_is_sharpe),
        ("OOS Sharpe",      f"{oos_sharpe:.4f}",   "> 0.70",          gate_oos_sharpe),
        ("IS CAGR",         f"{is_cagr:.2%}",      ">= 10%",          gate_is_cagr),
        ("IS MDD",          f"{is_mdd:.2%}",       "> -15%",          gate_is_mdd),
        ("OOS MDD",         f"{oos_mdd:.2%}",      "> -15%",          gate_oos_mdd),
        ("Walk-Forward",    f"{wf_passed}/4",       ">= 3/4",          gate_wf),
        ("Permutation p",   f"{perm['permutation_pvalue']:.4f}", "< 0.05", gate_perm),
        ("IS Trade Count",  f"{is_trades}",         ">= 100",          gate_trades),
        ("DSR",             f"{dsr:.4f}",           "> 0",             gate_dsr),
        ("PF-1 Switches",   f"{is_switches}",       ">= 120",          gate_switches),
    ]
    n_passed = sum(1 for *_, p in checks if p)
    verdict_label = "PASS" if all(p for *_, p in checks) else "FAIL"

    print(f"\n{'='*70}")
    print(f"H73 Cross-Sectional Return Seasonality — GATE 1 VERDICT: {verdict_label}")
    print(f"  Passed {n_passed}/{len(checks)} checks")
    for g, v, t, p in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {g:<22} {v:<12} (threshold: {t})")
    print(f"{'='*70}")

    # ── Build Metrics JSON ─────────────────────────────────────────────────────
    metrics_json = {
        "strategy_name":  STRATEGY_NAME,
        "date":           TODAY,
        "hypothesis":     "H73",
        "asset_class":    "equities",
        "parent_task":    "QUA-313",
        "universe":       SECTOR_TICKERS,
        "regime_etf":     REGIME_ETF,
        "safe_haven":     SAFE_HAVEN,
        "parameters": {
            "seasonal_lookback_years": PARAMETERS["seasonal_lookback_years"],
            "top_k_sectors":          PARAMETERS["top_k_sectors"],
            "use_regime_filter":      PARAMETERS["use_regime_filter"],
            "regime_ma_days":         PARAMETERS["regime_ma_days"],
        },
        "cost_model": {
            "slippage":       "0.05% (standard ETF tier — sector ETFs ADV << 50M/day)",
            "commission":     "$0.005/share",
            "market_impact":  "0.1 × σ × sqrt(Q/ADV) — Almgren-Chriss",
            "ruling":         "ED-SLIP-001 ultra-liquid tier NOT applied (sector ETFs ADV << 50M/day)",
        },
        # IS metrics
        "is_sharpe":         is_sharpe,
        "is_cagr":           is_cagr,
        "is_max_drawdown":   is_mdd,
        "is_total_return":   is_metrics["total_return"],
        "is_win_rate":       is_metrics["win_rate"],
        "is_profit_factor":  is_metrics["profit_factor"],
        "is_trade_count":    is_trades,
        "is_position_switches": is_switches,
        "is_avg_ppt_bps":    is_metrics["avg_ppt_bps"],
        # OOS metrics
        "oos_sharpe":        oos_sharpe,
        "oos_cagr":          oos_metrics["cagr"],
        "oos_max_drawdown":  oos_mdd,
        "oos_total_return":  oos_metrics["total_return"],
        "oos_win_rate":      oos_metrics["win_rate"],
        "oos_profit_factor": oos_metrics["profit_factor"],
        "oos_trade_count":   oos_metrics["trade_count"],
        "oos_position_switches": oos_metrics["position_switches"],
        "oos_avg_ppt_bps":   oos_metrics["avg_ppt_bps"],
        # Post-cost
        "post_cost_sharpe":  is_sharpe,
        # Statistical rigor
        "dsr":               dsr,
        "n_trials":          n_trials,
        **mc,
        **bb,
        **perm,
        "market_impact_by_ticker": mi_report,
        # Walk-forward
        "wf_windows":        wf_results,
        "wf_windows_passed": wf_passed,
        "wf_consistency_score": round(wf_passed / 4, 4),
        "wf_sharpe_std":     round(wf_sharpe_std, 4),
        "wf_sharpe_min":     round(wf_sharpe_min, 4),
        # Sensitivity
        "sensitivity_pass":             sensitivity_pass,
        "sensitivity_max_delta_pct":    round(float(variance_pct * 100) if not np.isnan(variance_pct) else 0.0, 2),
        "sweep_sharpe_min":             round(min(valid_sharpes), 4) if valid_sharpes else None,
        "sweep_sharpe_max":             round(max(valid_sharpes), 4) if valid_sharpes else None,
        # Gate outcomes
        "gate_is_sharpe":   gate_is_sharpe,
        "gate_oos_sharpe":  gate_oos_sharpe,
        "gate_is_cagr":     gate_is_cagr,
        "gate_is_mdd":      gate_is_mdd,
        "gate_oos_mdd":     gate_oos_mdd,
        "gate_wf":          gate_wf,
        "gate_perm":        gate_perm,
        "gate_trades":      gate_trades,
        "gate_dsr":         gate_dsr,
        "gate_pf1_switches": gate_switches,
        "gate1_pass":       verdict_label == "PASS",
        "n_checks_passed":  n_passed,
        "regime_bearish_is_months": regime_bearish_months,
        # Data quality
        "data_quality":     dq,
    }

    # ── Save Outputs ───────────────────────────────────────────────────────────
    base = f"H73_CrossSectionalReturnSeasonality_{TODAY}"

    # JSON
    json_path = OUT_DIR / f"{base}.json"
    with open(json_path, "w") as f:
        json.dump(metrics_json, f, indent=2, default=str)
    print(f"\nSaved metrics: {json_path}")

    # Trades CSV
    all_trades = is_result["trade_log"] + oos_result["trade_log"]
    if all_trades:
        trades_df   = pd.DataFrame(all_trades)
        trades_path = OUT_DIR / f"{base}_trades.csv"
        trades_df.to_csv(trades_path, index=False)
        print(f"Saved trades: {trades_path} ({len(trades_df)} entries)")

    # Sweep CSV
    if sweep_rows:
        sweep_df   = pd.DataFrame(sweep_rows)
        sweep_path = OUT_DIR / f"{base}_sweep.csv"
        sweep_df.to_csv(sweep_path, index=False)
        print(f"Saved sweep: {sweep_path}")

    # Verdict TXT
    verdict_lines = [
        f"H73 Cross-Sectional Return Seasonality (Sector Calendar Rotation) — Gate 1 Verdict",
        f"{'='*70}",
        f"Date:     {TODAY}",
        f"Strategy: {STRATEGY_NAME}",
        f"Overall:  {verdict_label} ({n_passed}/{len(checks)} checks passed)",
        f"{'='*70}",
        f"",
        f"=== Universe ===",
        f"Sectors:  {', '.join(SECTOR_TICKERS)}",
        f"Regime:   SPY 200-DMA → exit to SHY",
        f"Signal:   {PARAMETERS['seasonal_lookback_years']}-year trailing same-calendar-month return average",
        f"Top-K:    {PARAMETERS['top_k_sectors']} sectors, equal weight",
        f"Academic: Keloharju, Linnainmaa & Nyberg (2016) JF 71(4)",
        f"",
        f"=== IS Performance ({IS_START} to {IS_END}, 21 years) ===",
        f"Sharpe:           {is_sharpe:.4f}    [{'PASS' if gate_is_sharpe else 'FAIL'}: > 1.0]",
        f"CAGR:             {is_cagr:.2%}     [{'PASS' if gate_is_cagr else 'FAIL'}: >= 10%]",
        f"Max Drawdown:     {is_mdd:.2%}    [{'PASS' if gate_is_mdd else 'FAIL'}: > -15%]",
        f"Win Rate:         {is_metrics['win_rate']:.2%}",
        f"Profit Factor:    {is_metrics['profit_factor']}",
        f"Trade Count:      {is_trades}     [{'PASS' if gate_trades else 'FAIL'}: >= 100]",
        f"Position Switches:{is_switches}   [{'PASS' if gate_switches else 'FAIL'}: >= 120]",
        f"Avg PpT:          {is_metrics['avg_ppt_bps']:.2f} bps",
        f"Regime-SHY months:{regime_bearish_months}/{len(is_sigs_months)} IS months",
        f"",
        f"=== OOS Performance ({OOS_START} to {OOS_END}, ~2.5 years) ===",
        f"Sharpe:           {oos_sharpe:.4f}  [{'PASS' if gate_oos_sharpe else 'FAIL'}: > 0.70]",
        f"CAGR:             {oos_metrics['cagr']:.2%}",
        f"Max Drawdown:     {oos_mdd:.2%}  [{'PASS' if gate_oos_mdd else 'FAIL'}: > -15%]",
        f"Win Rate:         {oos_metrics['win_rate']:.2%}",
        f"Profit Factor:    {oos_metrics['profit_factor']}",
        f"Trade Count:      {oos_metrics['trade_count']}",
        f"Position Switches:{oos_metrics['position_switches']}",
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
        s   = w.get("sharpe", 0.0)
        p_wf = s > 0.0
        verdict_lines.append(
            f"  Window {w['window']}: {w['is_start']}–{w['is_end']}: "
            f"Sharpe={s:.4f} {'✓' if p_wf else '✗'}, "
            f"MDD={w.get('max_drawdown', 0):.2%}, trades={w.get('trade_count', 0)}, "
            f"switches={w.get('position_switches', 0)}"
        )
    verdict_lines += [
        f"  WF Passed: {wf_passed}/4   [{'PASS' if gate_wf else 'FAIL'}: >= 3/4]",
        f"  WF Sharpe std: {wf_sharpe_std:.4f}",
        f"  WF Sharpe min: {wf_sharpe_min:.4f}",
        f"",
        f"=== Sensitivity Sweep (18 combinations: lookback × top_k × regime_filter) ===",
    ]
    if valid_sharpes:
        verdict_lines.append(f"  Sharpe range: {min(valid_sharpes):.4f} – {max(valid_sharpes):.4f}")
        verdict_lines.append(f"  Variance vs primary: {variance_pct:.1%} ({'PASS' if sensitivity_pass else 'FAIL'} < 30%)")
    verdict_lines += [
        f"  See: {base}_sweep.csv",
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
        mi_report, mc, bb, perm, dsr, verdict_label, checks
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
