"""
H84 Gate 1 Backtest — Cross-Asset Return Seasonality
IS:  2003-01-01 to 2023-12-31 (21 years, dynamic universe)
OOS: 2024-01-01 to today
Walk-forward: 4 non-overlapping IS windows
Sweep: 36 combos (lookback × top_k × regime_filter × bond_gold_exempt)
Critical test: WITH vs WITHOUT bond/gold 200-DMA exemption

Criteria: v2.7 / kpi-daily-weekly.md v1.0
  OOS Sharpe > 0.7 (hard gate) | CS >= 0.60 | Gate 7 MDD < 30% per WF window
  NO IS Sharpe gate.

Parent: QUA-380 | Hypothesis: H84 | Keloharju et al. (2016) JF
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
STRATEGY_NAME = "H84_CrossAssetReturnSeasonality"
OUT_DIR = REPO_ROOT / "backtests"
TRADING_DAYS = 252

# ── Universe ───────────────────────────────────────────────────────────────────
EQUITY_TICKERS    = ["SPY", "QQQ", "IWM", "XLE", "XLV", "XLP", "HYG", "EEM"]
BOND_GOLD_TICKERS = ["TLT", "IEF", "GLD"]
SAFE_HAVEN        = "SHY"
ALL_UNIVERSE      = EQUITY_TICKERS + BOND_GOLD_TICKERS + [SAFE_HAVEN]  # 12 ETFs
REGIME_ETF        = "SPY"
# SPY already in ALL_UNIVERSE; deduplicate for download
ALL_DL = list(dict.fromkeys(ALL_UNIVERSE))

# ── Slippage tiers (ED-SLIP-001) ──────────────────────────────────────────────
ULTRA_LIQUID_SET = {"SPY", "QQQ", "IWM"}
ULTRA_SLIP  = 0.00005   # 0.005% — ultra-liquid (ADV > 50M shares/day)
STD_SLIP    = 0.0005    # 0.05%  — standard ETF tier

def _slip(ticker: str) -> float:
    return ULTRA_SLIP if ticker in ULTRA_LIQUID_SET else STD_SLIP

# ── Primary parameters ────────────────────────────────────────────────────────
PARAMETERS = {
    "seasonal_lookback_years": 10,
    "top_k_etfs":              3,
    "use_regime_filter":       True,
    "bond_gold_exempt":        True,   # key H84 structural feature
    "regime_ma_days":          200,
    "init_capital":            100_000.0,
    "commission_per_share":    0.005,
    "market_impact_k":         0.1,
}

IS_START   = "2003-01-01"
IS_END     = "2023-12-31"
OOS_START  = "2024-01-01"
OOS_END    = TODAY
DATA_START = "1993-01-01"

WF_IS_WINDOWS = [
    ("2003-01-01", "2007-12-31"),
    ("2008-01-01", "2012-12-31"),   # GFC — key structural test window
    ("2013-01-01", "2017-12-31"),
    ("2018-01-01", "2023-12-31"),
]

SWEEP_LOOKBACKS        = [5, 10, 15]
SWEEP_TOP_K            = [2, 3, 4]
SWEEP_REGIME           = [True, False]
SWEEP_BOND_GOLD_EXEMPT = [True, False]


# ── Data Download ──────────────────────────────────────────────────────────────

def download_data(start: str = DATA_START, end: str = OOS_END) -> dict:
    print(f"H84: downloading {len(ALL_DL)} tickers from {start} to {end}...")
    raw = yf.download(ALL_DL, start=start, end=end, auto_adjust=True, progress=False)
    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("Expected MultiIndex columns from yfinance multi-ticker download.")
    close  = raw["Close"][ALL_DL].copy()
    open_  = raw["Open"][ALL_DL].copy()
    volume = raw["Volume"][ALL_DL].copy()
    close  = close.dropna(how="all")
    open_  = open_.reindex(close.index)
    volume = volume.reindex(close.index)
    close  = close.ffill(limit=5)
    open_  = open_.ffill(limit=5)
    print(f"H84: data shape {close.shape}, range {close.index[0].date()} – {close.index[-1].date()}")
    return {"close": close, "open_": open_, "volume": volume}


def data_quality_report(data: dict) -> dict:
    close = data["close"]
    report = {
        "universe": ALL_UNIVERSE,
        "regime_etf": REGIME_ETF,
        "safe_haven": SAFE_HAVEN,
        "survivorship_bias": (
            "Fixed 12-ETF cross-asset universe: SPY/QQQ/IWM/XLE/XLV/XLP (1998+), "
            "TLT/IEF/SHY (2002+), EEM (2003+), GLD (2004+), HYG (2007+). "
            "All active ETFs tracking fixed indices — no survivorship bias."
        ),
        "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
        "earnings_exclusion": "N/A — ETFs are diversified portfolios.",
        "slippage_tiers": {
            "ultra_liquid": list(ULTRA_LIQUID_SET),
            "ultra_slip_pct": ULTRA_SLIP * 100,
            "standard_slip_pct": STD_SLIP * 100,
            "ruling": "ED-SLIP-001",
        },
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


def compute_etf_monthly(close: pd.DataFrame) -> pd.DataFrame:
    ltd = get_last_trading_days(close)
    prices_at_ltd = close[ALL_UNIVERSE].reindex(ltd).ffill(limit=3)
    monthly = prices_at_ltd.pct_change()
    return monthly


# ── Seasonal Signal Computation ────────────────────────────────────────────────

def compute_seasonal_score(monthly: pd.DataFrame, t: pd.Timestamp,
                           lookback_years: int, available_tickers: list) -> dict:
    cal_month  = t.month
    start_year = t.year - lookback_years
    scores = {}
    for ticker in available_tickers:
        if ticker not in monthly.columns:
            continue
        hist = monthly[ticker].loc[
            (monthly.index.month == cal_month) &
            (monthly.index.year >= start_year) &
            (monthly.index.year < t.year)
        ].dropna()
        if len(hist) >= 2:
            scores[ticker] = float(hist.mean())
    return scores


def compute_all_signals(monthly: pd.DataFrame, spy_close_daily: pd.Series,
                        params: dict, all_ltd: pd.DatetimeIndex) -> dict:
    lookback   = params["seasonal_lookback_years"]
    top_k      = params["top_k_etfs"]
    use_filter = params["use_regime_filter"]
    exempt     = params.get("bond_gold_exempt", True)
    ma_days    = params.get("regime_ma_days", 200)

    spy_ma = spy_close_daily.rolling(ma_days, min_periods=max(1, ma_days // 2)).mean()

    signals = {}
    for t in all_ltd:
        # Tickers with ≥2 same-calendar-month observations before this date
        avail = [
            tk for tk in ALL_UNIVERSE
            if tk in monthly.columns
            and monthly[tk].loc[
                (monthly.index.month == t.month) &
                (monthly.index.year < t.year)
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
            if exempt:
                # H84 structural feature: bonds/gold exempt from equity 200-DMA exit
                defensive = [tk for tk in avail if tk not in EQUITY_TICKERS]
                if not defensive:
                    defensive = [SAFE_HAVEN]
                def_scores = compute_seasonal_score(monthly, t, lookback, defensive)
                if def_scores:
                    sorted_t = sorted(def_scores, key=lambda x: def_scores[x], reverse=True)
                    target = sorted_t[:top_k]
                else:
                    target = [SAFE_HAVEN]
                signals[t] = {"tickers": target, "regime_bearish": True, "scores": def_scores}
            else:
                # H73-style: all assets exit to SHY
                signals[t] = {"tickers": [SAFE_HAVEN], "regime_bearish": True, "scores": {}}
            continue

        # Normal regime: rank full available universe
        scores = compute_seasonal_score(monthly, t, lookback, avail)
        if not scores:
            target = avail[:top_k] if avail else [SAFE_HAVEN]
        else:
            sorted_t = sorted(scores, key=lambda x: scores[x], reverse=True)
            target = sorted_t[:top_k]

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
    slip   = _slip(ticker)
    comm   = params["commission_per_share"]
    k      = params["market_impact_k"]
    adv    = max(float(adv or 1e6), 1.0)
    sigma  = float(sigma or 0.0)
    q_adv  = shares / adv
    impact = k * sigma * np.sqrt(max(q_adv, 0.0))
    cost_per_share = price * (slip + impact) + comm
    return cost_per_share, q_adv > 0.01, round(q_adv, 8)


def sell_cost_model(ticker, shares, price, sigma, adv, params):
    slip   = _slip(ticker)
    comm   = params["commission_per_share"]
    k      = params["market_impact_k"]
    adv    = max(float(adv or 1e6), 1.0)
    sigma  = float(sigma or 0.0)
    q_adv  = shares / adv
    impact = k * sigma * np.sqrt(max(q_adv, 0.0))
    net = shares * price * (1 - slip - impact) - shares * comm
    return max(net, 0.0), q_adv > 0.01, round(q_adv, 8)


# ── Portfolio Simulation ───────────────────────────────────────────────────────

def run_backtest(data: dict, signals: dict, params: dict,
                 start: str, end: str, period_label: str = "?") -> dict:
    close  = data["close"]
    open_  = data["open_"]
    volume = data["volume"]

    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)
    window   = close.loc[ts_start:ts_end].index
    if len(window) < 5:
        raise ValueError(f"Insufficient data {start}:{end}: {len(window)} days")

    init_cap = params["init_capital"]

    sigma_20 = {}
    adv_20   = {}
    for tk in ALL_UNIVERSE:
        if tk in close.columns:
            sigma_20[tk] = close[tk].pct_change().rolling(20, min_periods=5).std()
        if tk in volume.columns:
            adv_20[tk] = volume[tk].rolling(20, min_periods=5).mean()

    window_signals = {d: s for d, s in signals.items() if ts_start <= d <= ts_end}
    prior = {d: s for d, s in signals.items() if d < ts_start}
    if prior:
        init_sig = prior[max(prior.keys())]
    else:
        first_sig_date = min(window_signals.keys()) if window_signals else None
        init_sig = window_signals.get(first_sig_date, {"tickers": [SAFE_HAVEN]})

    cash        = float(init_cap)
    positions   = {}
    entry_info  = {}
    pending_tgt = list(init_sig["tickers"])

    portfolio_values = pd.Series(index=window, dtype=float)
    trade_log        = []

    def gp(df, ticker, t_day):
        if ticker not in df.columns or t_day not in df.index:
            return np.nan
        v = df.loc[t_day, ticker]
        return float(v) if not pd.isna(v) else np.nan

    for i, t_day in enumerate(window):
        if pending_tgt is not None:
            new_set = set(pending_tgt)
            cur_set = set(positions.keys())
            to_sell = cur_set - new_set
            to_buy  = new_set - cur_set

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
                    "period":      period_label,
                    "ticker":      ticker,
                    "entry_date":  ei["date"],
                    "exit_date":   str(t_day.date()),
                    "entry_price": round(float(ei["price"]), 4),
                    "exit_price":  round(float(px), 4),
                    "shares":      round(float(sh), 4),
                    "pnl":         round(float(pnl), 2),
                    "exit_reason": "rebalance",
                    "liquidity_constrained": liq,
                    "q_over_adv":  q_adv,
                })
                del positions[ticker]

            n_buy = len(to_buy)
            if n_buy > 0:
                cash_per = cash / n_buy
                for ticker in sorted(to_buy):
                    px = gp(open_, ticker, t_day)
                    if np.isnan(px) or px <= 0:
                        px = gp(close, ticker, t_day)
                    if np.isnan(px) or px <= 0:
                        continue
                    sig_v   = _get_val(sigma_20.get(ticker), t_day, 0.0) or 0.0
                    adv_v   = _get_val(adv_20.get(ticker), t_day, 1e6) or 1e6
                    est_sh  = cash_per / (px + 1e-8)
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

        nav = cash
        for ticker, sh in positions.items():
            px = gp(close, ticker, t_day)
            if not np.isnan(px) and px > 0:
                nav += sh * px
        portfolio_values.iloc[i] = max(nav, 0.0)

        if t_day in window_signals:
            new_tgt = window_signals[t_day]["tickers"]
            if set(new_tgt) != set(positions.keys()):
                pending_tgt = list(new_tgt)

    if positions:
        last_t = window[-1]
        for ticker, sh in list(positions.items()):
            px = gp(close, ticker, last_t)
            if np.isnan(px) or px <= 0:
                continue
            ei = entry_info.pop(ticker, {"price": px, "date": str(last_t.date())})
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

def compute_metrics(portfolio_values: pd.Series, trade_log: list,
                    start: str, end: str) -> dict:
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

    closed   = [t for t in trade_log if t.get("exit_reason") != "window_end"]
    switches = [t for t in closed if t.get("exit_reason") == "rebalance"]

    if closed:
        pnl_arr  = np.array([t["pnl"] for t in closed])
        win_rate = float(np.mean(pnl_arr > 0))
        wins     = pnl_arr[pnl_arr > 0]
        losses   = pnl_arr[pnl_arr < 0]
        pf = float(wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 0 else float("inf")
        avg_ppt_bps = float(np.mean(pnl_arr / (portfolio_values.iloc[0] + 1e-8) * 10_000))
    else:
        win_rate = pf = avg_ppt_bps = 0.0

    return {
        "sharpe":            round(sharpe, 4),
        "cagr":              round(cagr, 4),
        "max_drawdown":      round(mdd, 4),
        "total_return":      round(total_ret, 4),
        "trade_count":       len(closed),
        "position_switches": len(switches),
        "win_rate":          round(win_rate, 4),
        "profit_factor":     round(pf, 4) if not np.isinf(pf) else "inf",
        "avg_ppt_bps":       round(avg_ppt_bps, 2),
        "period":            f"{start} to {end}",
        "years":             round(years, 2),
    }


# ── Composite Score (v2.7 / kpi-daily-weekly.md v1.0) ─────────────────────────

def compute_cs(oos_sharpe: float, is_mdd: float,
               is_avg_ppt_bps: float, is_trade_count: int) -> tuple:
    net_sharpe_norm     = float(np.clip((oos_sharpe - (-0.5)) / (2.0 - (-0.5)), 0.0, 1.0))
    stability_norm      = float(np.clip(1.0 - abs(is_mdd) / 0.20, 0.0, 1.0))
    ppt_norm            = float(np.clip(is_avg_ppt_bps / 100.0, 0.0, 1.0))
    trade_adequacy_norm = float(min(1.0, is_trade_count / 30.0))
    cs = (0.40 * net_sharpe_norm
        + 0.30 * stability_norm
        + 0.20 * ppt_norm
        + 0.10 * trade_adequacy_norm)
    return round(cs, 4), {
        "net_sharpe_norm":     round(net_sharpe_norm, 4),
        "stability_norm":      round(stability_norm, 4),
        "ppt_norm":            round(ppt_norm, 4),
        "trade_adequacy_norm": round(trade_adequacy_norm, 4),
    }


# ── Statistical Rigor ──────────────────────────────────────────────────────────

def monte_carlo_sharpe(pnl_arr: np.ndarray, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    if len(pnl_arr) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0,
                "mc_p95_sharpe": 0.0, "mc_flag": "insufficient trades"}
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
        cum      = np.cumprod(1 + sample)
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


def permutation_test(monthly: pd.DataFrame, observed_sharpe: float,
                     start: str, end: str, n_perms: int = 1000) -> dict:
    np.random.seed(44)
    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)
    is_monthly = monthly.loc[ts_start:ts_end].dropna(how="all")
    if len(is_monthly) < 10:
        return {"permutation_pvalue": 0.5, "permutation_test_pass": False,
                "permutation_note": "insufficient data"}

    months_list = is_monthly.index.tolist()
    n_months    = len(months_list)
    tickers_avail = [c for c in ALL_UNIVERSE if c in is_monthly.columns]
    n_t = len(tickers_avail)
    vals = is_monthly[tickers_avail].values  # (n_months, n_t)
    k   = PARAMETERS["top_k_etfs"]

    perm_sharpes = []
    for _ in range(n_perms):
        perm_idx = np.random.permutation(n_months)
        perm_v   = vals[perm_idx, :]
        monthly_pf_rets = []
        for m_i in range(1, n_months):
            lb = max(0, m_i - 10 * 12)
            cal_m = months_list[m_i].month
            hist_mask = np.array([months_list[j].month == cal_m for j in range(lb, m_i)])
            lookback_slice = perm_v[lb:m_i][hist_mask]
            if lookback_slice.shape[0] < 2:
                continue
            scores_perm = np.nanmean(lookback_slice, axis=0)
            top_k_idx = np.argsort(scores_perm)[::-1][:k]
            monthly_pf_rets.append(float(np.nanmean(perm_v[m_i, top_k_idx])))
        perm_arr_m = np.array(monthly_pf_rets)
        if perm_arr_m.std() > 0:
            s = float(perm_arr_m.mean() / perm_arr_m.std() * np.sqrt(12))
        else:
            s = 0.0
        perm_sharpes.append(s)

    perm_np  = np.array(perm_sharpes)
    p_value  = float(np.mean(perm_np >= observed_sharpe))
    return {
        "permutation_pvalue":    round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
        "permutation_perm_mean": float(perm_np.mean()),
        "permutation_perm_p95":  float(np.percentile(perm_np, 95)),
    }


def compute_dsr(is_sharpe: float, n_trials: int, T: int) -> float:
    if T <= 0 or n_trials <= 1:
        return 0.0
    gamma  = 0.5772
    ln_n   = np.log(max(n_trials, 2))
    exp_max = (
        np.sqrt(2 * ln_n)
        - (np.log(np.log(max(n_trials, 2))) + np.log(4 * np.pi)) / (2 * np.sqrt(2 * ln_n))
        + gamma / np.sqrt(2 * ln_n)
    ) / np.sqrt(T)
    return round(float(is_sharpe - exp_max), 4)


def compute_market_impact_report(data: dict, start: str, end: str) -> dict:
    close  = data["close"]
    volume = data["volume"]
    results = {}
    cap_per = 100_000.0 / 3  # ~$33K per position (top-3 equal weight)
    for ticker in ALL_UNIVERSE:
        if ticker not in close.columns:
            continue
        try:
            hist_c  = close[ticker].loc[start:end].dropna()
            hist_v  = volume[ticker].loc[start:end].dropna()
            if len(hist_c) < 20:
                results[ticker] = {"note": "insufficient data"}
                continue
            avg_px  = float(hist_c.tail(20).mean())
            adv     = float(hist_v.tail(20).mean())
            sigma   = float(hist_c.pct_change().tail(60).std())
            qty     = cap_per / max(avg_px, 1.0)
            q_adv   = qty / max(adv, 1.0)
            impact  = 0.1 * sigma * np.sqrt(max(q_adv, 0.0))
            results[ticker] = {
                "market_impact_bps":   round(float(impact * 10_000), 4),
                "adv_20d":             round(float(adv), 0),
                "avg_price":           round(float(avg_px), 2),
                "qty_at_33k":          round(float(qty), 0),
                "q_over_adv":          round(float(q_adv), 6),
                "liquidity_constrained": q_adv > 0.01,
                "slippage_tier":       "ultra" if ticker in ULTRA_LIQUID_SET else "standard",
            }
        except Exception as e:
            results[ticker] = {"error": str(e)}
    return results


# ── Walk-Forward Analysis ──────────────────────────────────────────────────────

def run_walk_forward(data: dict, monthly: pd.DataFrame,
                     params: dict, wf_windows: list) -> list:
    results   = []
    all_ltd   = get_last_trading_days(data["close"])
    spy_daily = data["close"][REGIME_ETF].dropna()

    for i, (wf_start, wf_end) in enumerate(wf_windows):
        try:
            wf_sigs = compute_all_signals(monthly, spy_daily, params, all_ltd)
            wf_res  = run_backtest(data, wf_sigs, params, wf_start, wf_end, f"WF{i+1}")
            wf_m    = compute_metrics(wf_res["portfolio_values"], wf_res["trade_log"],
                                      wf_start, wf_end)
            gate7_pass = wf_m["max_drawdown"] > -0.30
            results.append({
                "window":           i + 1,
                "is_start":         wf_start,
                "is_end":           wf_end,
                "sharpe":           wf_m["sharpe"],
                "max_drawdown":     wf_m["max_drawdown"],
                "win_rate":         wf_m["win_rate"],
                "trade_count":      wf_m["trade_count"],
                "position_switches": wf_m["position_switches"],
                "cagr":             wf_m["cagr"],
                "gate7_pass":       gate7_pass,
            })
            print(f"  WF{i+1} ({wf_start}–{wf_end}): Sharpe={wf_m['sharpe']:.3f}, "
                  f"MDD={wf_m['max_drawdown']:.2%}, trades={wf_m['trade_count']}, "
                  f"Gate7={'PASS' if gate7_pass else 'FAIL'}")
        except Exception as e:
            results.append({"window": i+1, "is_start": wf_start, "is_end": wf_end,
                            "sharpe": 0.0, "max_drawdown": 0.0, "error": str(e),
                            "gate7_pass": False})
            print(f"  WF{i+1} ERROR: {e}")
    return results


# ── Parameter Sweep (36 combos) ────────────────────────────────────────────────

def run_sweep(data: dict, monthly: pd.DataFrame, all_ltd: pd.DatetimeIndex,
              spy_daily: pd.Series) -> list:
    rows   = []
    combos = list(iproduct(SWEEP_LOOKBACKS, SWEEP_TOP_K, SWEEP_REGIME, SWEEP_BOND_GOLD_EXEMPT))
    print(f"  Running {len(combos)} sweep combinations...")

    for lookback, top_k, use_reg, bg_exempt in combos:
        p = {**PARAMETERS,
             "seasonal_lookback_years": lookback,
             "top_k_etfs": top_k,
             "use_regime_filter": use_reg,
             "bond_gold_exempt": bg_exempt}
        label = f"lb={lookback}, k={top_k}, regime={'Y' if use_reg else 'N'}, exempt={'Y' if bg_exempt else 'N'}"
        try:
            sigs = compute_all_signals(monthly, spy_daily, p, all_ltd)
            res  = run_backtest(data, sigs, p, IS_START, IS_END, "SWEEP")
            m    = compute_metrics(res["portfolio_values"], res["trade_log"], IS_START, IS_END)
            rows.append({
                "seasonal_lookback_years": lookback,
                "top_k_etfs": top_k,
                "use_regime_filter": use_reg,
                "bond_gold_exempt": bg_exempt,
                "sharpe":       m["sharpe"],
                "cagr":         m["cagr"],
                "max_drawdown": m["max_drawdown"],
                "win_rate":     m["win_rate"],
                "trade_count":  m["trade_count"],
                "position_switches": m["position_switches"],
                "total_return": m["total_return"],
                "avg_ppt_bps":  m["avg_ppt_bps"],
            })
            print(f"    {label}: Sharpe={m['sharpe']:.3f}, MDD={m['max_drawdown']:.2%}, "
                  f"trades={m['trade_count']}")
        except Exception as e:
            rows.append({"seasonal_lookback_years": lookback, "top_k_etfs": top_k,
                         "use_regime_filter": use_reg, "bond_gold_exempt": bg_exempt,
                         "error": str(e)})
            print(f"    {label}: ERROR {e}")
    return rows


# ── HTML Report ────────────────────────────────────────────────────────────────

def build_html_report(is_m, oos_m, wf_results, sweep_rows, mi_report,
                      mc, bb, perm, dsr, cs, cs_components, verdict_label, checks,
                      comparison_result=None) -> str:
    vc = "#d4edda" if verdict_label == "PASS" else "#f8d7da"
    check_rows = "".join(
        f"<tr style='background:{'#d4edda' if p else '#f8d7da'}'>"
        f"<td>{g}</td><td>{v}</td><td>{t}</td><td>{'✓ PASS' if p else '✗ FAIL'}</td></tr>"
        for g, v, t, p in checks
    )
    wf_rows = "".join(
        f"<tr style='background:{'#d4edda' if w.get('gate7_pass', True) else '#f8d7da'}'>"
        f"<td>{w['window']}</td><td>{w['is_start']}–{w['is_end']}</td>"
        f"<td>{w.get('sharpe', 'ERR'):.4f}</td><td>{w.get('max_drawdown', 0):.2%}</td>"
        f"<td>{w.get('win_rate', 0):.2%}</td><td>{w.get('trade_count', 0)}</td>"
        f"<td>{w.get('position_switches', 0)}</td>"
        f"<td>{'✓' if w.get('gate7_pass', False) else '✗ FAIL'}</td></tr>"
        for w in wf_results
    )
    sweep_df   = pd.DataFrame(sweep_rows)
    sweep_html = sweep_df.to_html(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x), border=1)
    mi_rows = "".join(
        f"<tr><td>{t}</td><td>{d.get('market_impact_bps', 0):.4f}</td>"
        f"<td>{d.get('adv_20d', 0):,.0f}</td><td>{d.get('q_over_adv', 0):.6f}</td>"
        f"<td>{d.get('slippage_tier','std')}</td></tr>"
        for t, d in mi_report.items()
    )
    comp_section = ""
    if comparison_result:
        cm = comparison_result
        comp_section = f"""
<h2>Structural Comparison: WITH vs WITHOUT Bond/Gold 200-DMA Exemption</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>H84 (exempt=True, primary)</th><th>H73-style (exempt=False)</th><th>H73 actual</th></tr>
<tr><td>IS Sharpe</td><td>{is_m['sharpe']:.4f}</td><td>{cm['sharpe']:.4f}</td><td>0.5942</td></tr>
<tr><td>IS MDD</td><td>{is_m['max_drawdown']:.2%}</td><td>{cm['max_drawdown']:.2%}</td><td>-31.06%</td></tr>
<tr><td>IS CAGR</td><td>{is_m['cagr']:.2%}</td><td>{cm['cagr']:.2%}</td><td>7.86%</td></tr>
<tr><td>IS Trades</td><td>{is_m['trade_count']}</td><td>{cm['trade_count']}</td><td>324</td></tr>
</table>
<p><em>MDD improvement vs H73 (exempt=True): {(is_m['max_drawdown'] - (-0.3106))*100:.1f}pp; vs H73-style (exempt=False): {(is_m['max_drawdown'] - cm['max_drawdown'])*100:.1f}pp</em></p>
</div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>H84 Cross-Asset Return Seasonality — Gate 1 Report</title>
<style>
body {{ font-family: monospace; max-width: 1200px; margin: 0 auto; padding: 20px; }}
h1 {{ background: #343a40; color: white; padding: 15px; border-radius: 4px; }}
h2 {{ border-bottom: 2px solid #343a40; padding-bottom: 5px; margin-top: 30px; }}
.verdict {{ font-size: 2em; font-weight: bold; padding: 15px; border-radius: 4px;
           background: {vc}; text-align: center; margin: 20px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th {{ background: #343a40; color: white; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border: 1px solid #dee2e6; }}
.section {{ margin: 20px 0; padding: 15px; border: 1px solid #dee2e6; border-radius: 4px; }}
</style>
</head>
<body>
<h1>H84 Cross-Asset Return Seasonality — Gate 1 Report</h1>
<p><strong>Date:</strong> {TODAY} | <strong>Universe:</strong> {', '.join(ALL_UNIVERSE)}</p>
<p><strong>Signal:</strong> 10-year trailing same-calendar-month avg | <strong>Top-K:</strong> 3 | <strong>Filter:</strong> SPY 200-DMA (equity-only exit, bonds/gold exempt)</p>
<p><strong>Academic:</strong> Keloharju, Linnainmaa &amp; Nyberg (2016), Journal of Finance 71(4)</p>
<p><strong>Criteria:</strong> v2.7 / kpi-daily-weekly.md v1.0 — OOS Sharpe &gt; 0.7 (hard gate) | CS ≥ 0.60 | Gate 7 MDD &lt; 30% | NO IS Sharpe gate</p>
<p><strong>Slippage:</strong> 0.005% ultra-liquid (SPY/QQQ/IWM) | 0.05% standard (all others)</p>

<div class="verdict">GATE 1: {verdict_label}</div>

<h2>Gate 1 Checklist (v2.7)</h2>
<table><tr><th>Gate</th><th>Value</th><th>Threshold</th><th>Result</th></tr>{check_rows}</table>

<h2>Composite Score (v2.7)</h2>
<div class="section">
<p><strong>CS = {cs:.4f}</strong> (threshold ≥ 0.60)</p>
<p>NetSharpe_norm={cs_components['net_sharpe_norm']:.4f} × 0.40 = {cs_components['net_sharpe_norm']*0.40:.4f}</p>
<p>Stability_norm={cs_components['stability_norm']:.4f} × 0.30 = {cs_components['stability_norm']*0.30:.4f}</p>
<p>PpT_norm={cs_components['ppt_norm']:.4f} × 0.20 = {cs_components['ppt_norm']*0.20:.4f}</p>
<p>TradeAdequacy_norm={cs_components['trade_adequacy_norm']:.4f} × 0.10 = {cs_components['trade_adequacy_norm']*0.10:.4f}</p>
</div>

<h2>IS / OOS Summary</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>IS (2003–2023)</th><th>OOS (2024–{TODAY})</th></tr>
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

{comp_section}

<h2>Walk-Forward Analysis (4 IS Windows)</h2>
<table>
<tr><th>Window</th><th>Period</th><th>Sharpe</th><th>MDD</th><th>Win Rate</th><th>Trades</th><th>Switches</th><th>Gate 7</th></tr>
{wf_rows}
</table>

<h2>Statistical Tests</h2>
<div class="section">
<p><strong>Monte Carlo (1000 resamples):</strong> p5={mc['mc_p5_sharpe']:.4f}, median={mc['mc_median_sharpe']:.4f}, p95={mc['mc_p95_sharpe']:.4f}</p>
<p><strong>Block Bootstrap CI (95%):</strong> Sharpe [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}] | MDD [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]</p>
<p><strong>Permutation test (1000 perms):</strong> p={perm['permutation_pvalue']:.4f} — {"PASS" if perm['permutation_test_pass'] else "FAIL"}</p>
<p><strong>DSR:</strong> {dsr:.4f}</p>
</div>

<h2>Parameter Sweep (36 Combinations)</h2>
{sweep_html}

<h2>Market Impact by Ticker</h2>
<table>
<tr><th>Ticker</th><th>Impact (bps)</th><th>ADV 20d</th><th>Q/ADV</th><th>Slip Tier</th></tr>
{mi_rows}
</table>

<hr>
<p><em>Engineering Director | QUA-380 | H84 Gate 1 | {TODAY}</em></p>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H84 Cross-Asset Return Seasonality — Gate 1 Backtest — {TODAY}")
    print(f"Universe: {ALL_UNIVERSE}")
    print(f"IS: {IS_START} → {IS_END} | OOS: {OOS_START} → {OOS_END}")
    print(f"Signal: {PARAMETERS['seasonal_lookback_years']}yr seasonal avg | "
          f"Top-{PARAMETERS['top_k_etfs']} ETFs | 200-DMA SPY filter (bond/gold exempt)")
    print(f"Criteria: v2.7 — OOS Sharpe > 0.7 | CS ≥ 0.60 | Gate 7 MDD < 30%")
    print("=" * 70)

    # ── [1/9] Data Download ───────────────────────────────────────────────────
    print("\n[1/9] Downloading data...")
    data = download_data(DATA_START, OOS_END)
    dq   = data_quality_report(data)
    if dq["flagged"]:
        warnings.warn(f"Data quality flags: {dq['flagged']}")

    close     = data["close"]
    spy_daily = close[REGIME_ETF].dropna()
    all_ltd   = get_last_trading_days(close)

    # ── [2/9] Monthly Returns ─────────────────────────────────────────────────
    print("\n[2/9] Computing monthly returns...")
    monthly = compute_etf_monthly(close)
    print(f"  Monthly matrix: {monthly.shape} | "
          f"range {monthly.index[1].date()} – {monthly.index[-1].date()}")

    # ── [3/9] Primary Signals (bond_gold_exempt=True) ─────────────────────────
    print("\n[3/9] Computing seasonal signals (primary: bond_gold_exempt=True)...")
    all_signals = compute_all_signals(monthly, spy_daily, PARAMETERS, all_ltd)
    print(f"  Signals: {len(all_signals)} month-end dates")
    is_sigs = [d for d in all_signals if pd.Timestamp(IS_START) <= d <= pd.Timestamp(IS_END)]
    bearish_months = sum(1 for d in is_sigs if all_signals[d]["regime_bearish"])
    print(f"  IS months: {len(is_sigs)} | Regime-bearish: {bearish_months}")

    # Count months where bonds/gold were held during bearish regime
    bonds_gold_in_bearish = 0
    for d in is_sigs:
        sig = all_signals[d]
        if sig["regime_bearish"]:
            held = set(sig["tickers"])
            if held & (set(BOND_GOLD_TICKERS) | {SAFE_HAVEN}):
                if held != {SAFE_HAVEN}:
                    bonds_gold_in_bearish += 1
    print(f"  Bearish months with bonds/gold held (not 100% SHY): {bonds_gold_in_bearish}")

    # ── [4/9] IS Backtest ─────────────────────────────────────────────────────
    print(f"\n[4/9] IS backtest ({IS_START} → {IS_END})...")
    is_result  = run_backtest(data, all_signals, PARAMETERS, IS_START, IS_END, "IS")
    is_metrics = compute_metrics(is_result["portfolio_values"], is_result["trade_log"],
                                 IS_START, IS_END)
    print(f"  IS Sharpe: {is_metrics['sharpe']:.4f} | CAGR: {is_metrics['cagr']:.2%} | "
          f"MDD: {is_metrics['max_drawdown']:.2%}")
    print(f"  IS trades: {is_metrics['trade_count']} | Switches: {is_metrics['position_switches']}")
    if is_metrics["position_switches"] < 120:
        print(f"  ⚠  PF-1 FLAG: switches {is_metrics['position_switches']} < 120 "
              f"(flag-only per hypothesis PF-1 note — do not auto-fail)")

    # ── [5/9] OOS Backtest ────────────────────────────────────────────────────
    print(f"\n[5/9] OOS backtest ({OOS_START} → {OOS_END})...")
    oos_result  = run_backtest(data, all_signals, PARAMETERS, OOS_START, OOS_END, "OOS")
    oos_metrics = compute_metrics(oos_result["portfolio_values"], oos_result["trade_log"],
                                  OOS_START, OOS_END)
    print(f"  OOS Sharpe: {oos_metrics['sharpe']:.4f} | CAGR: {oos_metrics['cagr']:.2%} | "
          f"MDD: {oos_metrics['max_drawdown']:.2%}")

    # ── [6/9] Walk-Forward Analysis ───────────────────────────────────────────
    print("\n[6/9] Walk-forward analysis (4 IS windows)...")
    wf_results = run_walk_forward(data, monthly, PARAMETERS, WF_IS_WINDOWS)
    wf_sharpes  = [w.get("sharpe", 0.0) for w in wf_results]
    wf_passed   = sum(1 for s in wf_sharpes if s > 0.0)
    gate7_all   = all(w.get("gate7_pass", False) for w in wf_results)
    print(f"  WF Sharpe>0: {wf_passed}/4 | Gate7 all pass: {gate7_all}")

    # ── [7/9] Statistical Rigor ───────────────────────────────────────────────
    print("\n[7/9] Statistical rigor...")
    is_trades_closed = [t for t in is_result["trade_log"] if t.get("exit_reason") == "rebalance"]
    is_pnl_arr       = np.array([t["pnl"] for t in is_trades_closed]) if is_trades_closed else np.array([0.0])
    is_ret_arr       = is_result["portfolio_values"].pct_change().fillna(0.0).values

    mc   = monte_carlo_sharpe(is_pnl_arr)
    bb   = block_bootstrap_ci(is_ret_arr)
    perm = permutation_test(monthly, is_metrics["sharpe"], IS_START, IS_END)
    n_trials = 36 + 4  # sweep combos + WF windows
    T_is     = len(is_result["portfolio_values"])
    dsr      = compute_dsr(is_metrics["sharpe"], n_trials, T_is)

    print(f"  MC p5={mc['mc_p5_sharpe']:.3f}, median={mc['mc_median_sharpe']:.3f}")
    print(f"  Bootstrap Sharpe CI: [{bb['sharpe_ci_low']:.3f}, {bb['sharpe_ci_high']:.3f}]")
    print(f"  Permutation p={perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'})")
    print(f"  DSR={dsr:.4f}")

    print("  Computing market impact...")
    mi_report = compute_market_impact_report(data, IS_START, IS_END)
    max_mi_bps = max((v.get("market_impact_bps", 0) for v in mi_report.values()
                      if isinstance(v, dict)), default=0.0)
    print(f"  Max market impact: {max_mi_bps:.4f} bps")

    # ── [8/9] Parameter Sweep (36 combos) ────────────────────────────────────
    print("\n[8/9] Parameter sweep (36 combinations)...")
    sweep_rows = run_sweep(data, monthly, all_ltd, spy_daily)
    valid_sharpes = [r["sharpe"] for r in sweep_rows if "sharpe" in r and isinstance(r["sharpe"], float)]
    if valid_sharpes:
        sharpe_range  = max(valid_sharpes) - min(valid_sharpes)
        prim_sharpe   = is_metrics["sharpe"]
        variance_pct  = sharpe_range / abs(prim_sharpe) if prim_sharpe != 0 else float("nan")
        sensitivity_pass = not np.isnan(variance_pct) and variance_pct <= 0.30
    else:
        variance_pct = float("nan"); sensitivity_pass = False
    print(f"  Sharpe range: {min(valid_sharpes):.3f} – {max(valid_sharpes):.3f}" if valid_sharpes else "  No valid sweep results")
    print(f"  Sensitivity: {'PASS' if sensitivity_pass else 'FAIL'} (<30% variance)")

    # Structural comparison: bond_gold_exempt=False (H73-style)
    print("  Structural comparison: bond_gold_exempt=False...")
    p_noexempt = {**PARAMETERS, "bond_gold_exempt": False}
    sigs_noexempt = compute_all_signals(monthly, spy_daily, p_noexempt, all_ltd)
    res_noexempt  = run_backtest(data, sigs_noexempt, p_noexempt, IS_START, IS_END, "COMPARE")
    comparison_metrics = compute_metrics(res_noexempt["portfolio_values"],
                                         res_noexempt["trade_log"], IS_START, IS_END)
    print(f"  Comparison (no exempt): Sharpe={comparison_metrics['sharpe']:.4f}, "
          f"MDD={comparison_metrics['max_drawdown']:.2%}")

    # ── [9/9] Gate 1 Verdict (v2.7) ──────────────────────────────────────────
    is_sharpe   = is_metrics["sharpe"]
    oos_sharpe  = oos_metrics["sharpe"]
    is_mdd      = is_metrics["max_drawdown"]
    is_trades   = is_metrics["trade_count"]
    is_switches = is_metrics["position_switches"]
    is_ppt      = is_metrics["avg_ppt_bps"]

    cs, cs_components = compute_cs(oos_sharpe, is_mdd, is_ppt, is_trades)

    gate_oos_sharpe = oos_sharpe > 0.70
    gate_cs         = cs >= 0.60
    gate_gate7      = gate7_all
    gate_dsr        = dsr > 0.0
    gate_wf         = wf_passed >= 3
    flag_pf1        = is_switches >= 120   # flag-only, not auto-fail

    checks = [
        ("OOS Sharpe (hard gate)",  f"{oos_sharpe:.4f}",    "> 0.70",    gate_oos_sharpe),
        ("Composite Score CS",      f"{cs:.4f}",             ">= 0.60",   gate_cs),
        ("Gate 7 MDD (WF windows)", f"all {'<30%' if gate_gate7 else '>30% FAIL'}", "< 30%", gate_gate7),
        ("DSR",                     f"{dsr:.4f}",            "> 0",       gate_dsr),
        ("Walk-Forward Sharpe>0",   f"{wf_passed}/4",        ">= 3/4",    gate_wf),
    ]
    n_passed      = sum(1 for *_, p in checks if p)
    verdict_label = "PASS" if all(p for *_, p in checks) else "FAIL"

    print(f"\n{'='*70}")
    print(f"H84 Cross-Asset Return Seasonality — GATE 1 VERDICT: {verdict_label}")
    print(f"  Passed {n_passed}/{len(checks)} checks")
    for g, v, t, p in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {g:<30} {v:<14} (threshold: {t})")
    print(f"  CS = {cs:.4f}  (NetSharpe_norm={cs_components['net_sharpe_norm']:.3f} × 0.40 "
          f"+ Stability_norm={cs_components['stability_norm']:.3f} × 0.30 "
          f"+ PpT_norm={cs_components['ppt_norm']:.3f} × 0.20 "
          f"+ TradeAdq_norm={cs_components['trade_adequacy_norm']:.3f} × 0.10)")
    print(f"  PF-1 flag (is_switches={is_switches}): {'OK ≥120' if flag_pf1 else '⚠ <120 (flag-only)'}")
    print(f"  Structural test — MDD with exemption: {is_mdd:.2%} | without: {comparison_metrics['max_drawdown']:.2%} | H73: -31.06%")
    print(f"{'='*70}")

    # ── Build JSON ─────────────────────────────────────────────────────────────
    metrics_json = {
        "strategy_name":  STRATEGY_NAME,
        "date":           TODAY,
        "hypothesis":     "H84",
        "parent_task":    "QUA-380",
        "universe":       ALL_UNIVERSE,
        "equity_tickers": EQUITY_TICKERS,
        "bond_gold_tickers": BOND_GOLD_TICKERS,
        "safe_haven":     SAFE_HAVEN,
        "regime_etf":     REGIME_ETF,
        "parameters":     {k: v for k, v in PARAMETERS.items() if k != "init_capital"},
        "criteria_version": "v2.7 / kpi-daily-weekly.md v1.0",
        "cost_model": {
            "ultra_liquid": list(ULTRA_LIQUID_SET),
            "ultra_slip_pct": ULTRA_SLIP * 100,
            "standard_slip_pct": STD_SLIP * 100,
            "commission": "$0.005/share",
            "market_impact": "0.1 × σ × sqrt(Q/ADV) — Almgren-Chriss",
            "ruling": "ED-SLIP-001",
        },
        # IS metrics
        "is_sharpe":            is_sharpe,
        "is_cagr":              is_metrics["cagr"],
        "is_max_drawdown":      is_mdd,
        "is_total_return":      is_metrics["total_return"],
        "is_win_rate":          is_metrics["win_rate"],
        "is_profit_factor":     is_metrics["profit_factor"],
        "is_trade_count":       is_trades,
        "is_position_switches": is_switches,
        "is_avg_ppt_bps":       is_ppt,
        "regime_bearish_is_months": bearish_months,
        "bonds_gold_held_in_bearish_months": bonds_gold_in_bearish,
        # OOS metrics
        "oos_sharpe":           oos_sharpe,
        "oos_cagr":             oos_metrics["cagr"],
        "oos_max_drawdown":     oos_metrics["max_drawdown"],
        "oos_total_return":     oos_metrics["total_return"],
        "oos_win_rate":         oos_metrics["win_rate"],
        "oos_profit_factor":    oos_metrics["profit_factor"],
        "oos_trade_count":      oos_metrics["trade_count"],
        "oos_position_switches": oos_metrics["position_switches"],
        "oos_avg_ppt_bps":      oos_metrics["avg_ppt_bps"],
        # Composite score
        "composite_score":      cs,
        "cs_components":        cs_components,
        # Statistical
        "dsr":                  dsr,
        "n_trials":             n_trials,
        **mc, **bb, **perm,
        "market_impact_by_ticker": mi_report,
        # Walk-forward
        "wf_windows":           wf_results,
        "wf_windows_passed":    wf_passed,
        "wf_sharpe_std":        round(float(np.std(wf_sharpes)), 4) if wf_sharpes else 0.0,
        "wf_sharpe_min":        round(float(np.min(wf_sharpes)), 4) if wf_sharpes else 0.0,
        "gate7_all_pass":       gate7_all,
        # Sensitivity
        "sensitivity_pass":          sensitivity_pass,
        "sensitivity_max_delta_pct": round(float(variance_pct * 100) if not np.isnan(variance_pct) else 0.0, 2),
        "sweep_sharpe_min":          round(min(valid_sharpes), 4) if valid_sharpes else None,
        "sweep_sharpe_max":          round(max(valid_sharpes), 4) if valid_sharpes else None,
        # Structural comparison
        "comparison_no_exempt": {
            "sharpe":       comparison_metrics["sharpe"],
            "max_drawdown": comparison_metrics["max_drawdown"],
            "cagr":         comparison_metrics["cagr"],
            "trade_count":  comparison_metrics["trade_count"],
        },
        # Gate outcomes
        "gate_oos_sharpe":   gate_oos_sharpe,
        "gate_cs":           gate_cs,
        "gate_gate7":        gate_gate7,
        "gate_dsr":          gate_dsr,
        "gate_wf":           gate_wf,
        "flag_pf1_ok":       flag_pf1,
        "gate1_pass":        verdict_label == "PASS",
        "n_checks_passed":   n_passed,
        # Data quality
        "data_quality":      dq,
    }

    # ── Save Outputs ───────────────────────────────────────────────────────────
    base = f"H84_CrossAssetReturnSeasonality_{TODAY}"

    json_path = OUT_DIR / f"{base}.json"
    with open(json_path, "w") as f:
        json.dump(metrics_json, f, indent=2, default=str)
    print(f"\nSaved: {json_path}")

    all_trades = is_result["trade_log"] + oos_result["trade_log"]
    if all_trades:
        trades_df   = pd.DataFrame(all_trades)
        trades_path = OUT_DIR / f"{base}_trades.csv"
        trades_df.to_csv(trades_path, index=False)
        print(f"Saved: {trades_path} ({len(trades_df)} entries)")

    if sweep_rows:
        sweep_df   = pd.DataFrame(sweep_rows)
        sweep_path = OUT_DIR / f"{base}_sweep.csv"
        sweep_df.to_csv(sweep_path, index=False)
        print(f"Saved: {sweep_path}")

    # Verdict text
    wf_mdd_strs = []
    for w in wf_results:
        s = w.get("sharpe", 0.0)
        gate7 = w.get("gate7_pass", False)
        wf_mdd_strs.append(
            f"  Window {w['window']}: {w['is_start']}–{w['is_end']}: "
            f"Sharpe={s:.4f} {'✓' if s > 0 else '✗'}, MDD={w.get('max_drawdown',0):.2%}, "
            f"trades={w.get('trade_count',0)}, Gate7={'PASS' if gate7 else 'FAIL'}"
        )

    verdict_lines = [
        f"H84 Cross-Asset Return Seasonality — Gate 1 Verdict",
        f"{'='*70}",
        f"Date:     {TODAY}",
        f"Strategy: {STRATEGY_NAME}",
        f"Criteria: v2.7 / kpi-daily-weekly.md v1.0 — NO IS Sharpe gate",
        f"Overall:  {verdict_label} ({n_passed}/{len(checks)} checks passed)",
        f"{'='*70}",
        f"",
        f"=== Universe ===",
        f"Equity:   {', '.join(EQUITY_TICKERS)}",
        f"Bond/Gold:{', '.join(BOND_GOLD_TICKERS)}",
        f"Safe haven: {SAFE_HAVEN}",
        f"Regime:   SPY 200-DMA → exit equity ETFs (bonds/gold exempt=True)",
        f"Signal:   10yr same-calendar-month avg return | Top-3 equal weight",
        f"",
        f"=== IS Performance ({IS_START} to {IS_END}, 21 years) ===",
        f"Sharpe:           {is_sharpe:.4f}    [diagnostic only — no IS Sharpe gate in v2.7]",
        f"CAGR:             {is_metrics['cagr']:.2%}",
        f"Max Drawdown:     {is_mdd:.2%}",
        f"Win Rate:         {is_metrics['win_rate']:.2%}",
        f"Profit Factor:    {is_metrics['profit_factor']}",
        f"Trade Count:      {is_trades}",
        f"Position Switches:{is_switches}   [PF-1 flag: {'OK' if flag_pf1 else '⚠ <120 (not auto-fail)'}]",
        f"Avg PpT:          {is_ppt:.2f} bps",
        f"Regime-bearish months: {bearish_months}/{len(is_sigs)} IS months",
        f"Bonds/gold held in bearish (not 100% SHY): {bonds_gold_in_bearish} months",
        f"",
        f"=== OOS Performance ({OOS_START} to {OOS_END}) ===",
        f"Sharpe:           {oos_sharpe:.4f}  [HARD GATE: {'PASS' if gate_oos_sharpe else 'FAIL'} > 0.70]",
        f"CAGR:             {oos_metrics['cagr']:.2%}",
        f"Max Drawdown:     {oos_metrics['max_drawdown']:.2%}",
        f"Win Rate:         {oos_metrics['win_rate']:.2%}",
        f"Trade Count:      {oos_metrics['trade_count']}",
        f"",
        f"=== Composite Score (v2.7) ===",
        f"CS = {cs:.4f}  [{'PASS' if gate_cs else 'FAIL'}: >= 0.60]",
        f"  NetSharpe_norm  = {cs_components['net_sharpe_norm']:.4f} × 0.40 = {cs_components['net_sharpe_norm']*0.40:.4f}",
        f"  Stability_norm  = {cs_components['stability_norm']:.4f} × 0.30 = {cs_components['stability_norm']*0.30:.4f}",
        f"  PpT_norm        = {cs_components['ppt_norm']:.4f} × 0.20 = {cs_components['ppt_norm']*0.20:.4f}",
        f"  TradeAdq_norm   = {cs_components['trade_adequacy_norm']:.4f} × 0.10 = {cs_components['trade_adequacy_norm']*0.10:.4f}",
        f"",
        f"=== Structural Test: WITH vs WITHOUT Bond/Gold Exemption ===",
        f"Primary (exempt=True):      Sharpe={is_sharpe:.4f}, MDD={is_mdd:.2%}",
        f"H73-style (exempt=False):   Sharpe={comparison_metrics['sharpe']:.4f}, MDD={comparison_metrics['max_drawdown']:.2%}",
        f"H73 actual (equity-only):   Sharpe=0.5942, MDD=-31.06%",
        f"MDD improvement (exemption vs H73): {(is_mdd - (-0.3106))*100:+.1f}pp",
        f"",
        f"=== Statistical Rigor ===",
        f"MC p5 Sharpe:       {mc['mc_p5_sharpe']:.4f}",
        f"MC Median Sharpe:   {mc['mc_median_sharpe']:.4f}",
        f"Sharpe 95% CI:      [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]",
        f"MDD 95% CI:         [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]",
        f"Permutation p:      {perm['permutation_pvalue']:.4f}  [{'PASS' if perm['permutation_test_pass'] else 'FAIL'}: < 0.05]",
        f"DSR:                {dsr:.4f}  [{'PASS' if gate_dsr else 'FAIL'}: > 0]",
        f"Max Market Impact:  {max_mi_bps:.4f} bps",
        f"",
        f"=== Walk-Forward Analysis (4 IS Windows) ===",
    ] + wf_mdd_strs + [
        f"  WF Sharpe>0: {wf_passed}/4  [{'PASS' if gate_wf else 'FAIL'}: >= 3/4]",
        f"  Gate 7 all windows MDD < 30%: {'PASS' if gate_gate7 else 'FAIL'}",
        f"",
        f"=== Parameter Sweep (36 combos) ===",
        f"  Sharpe range: {min(valid_sharpes):.4f} – {max(valid_sharpes):.4f}" if valid_sharpes else "  N/A",
        f"  Variance vs primary: {variance_pct:.1%}  ({'PASS' if sensitivity_pass else 'FAIL'} < 30%)" if not np.isnan(variance_pct) else "  N/A",
        f"",
        f"=== Gate 1 Checks (v2.7) ===",
    ]
    for g, v, t, p in checks:
        verdict_lines.append(f"  [{'PASS' if p else 'FAIL'}] {g:<30} {v}  (threshold: {t})")

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
    print(f"Saved: {verdict_path}")

    html = build_html_report(
        is_metrics, oos_metrics, wf_results, sweep_rows, mi_report,
        mc, bb, perm, dsr, cs, cs_components, verdict_label, checks,
        comparison_result=comparison_metrics,
    )
    html_path = OUT_DIR / f"{base}_report.html"
    html_path.write_text(html)
    print(f"Saved: {html_path}")

    print(f"\nAll outputs → {OUT_DIR}/")
    print(f"GATE 1: {verdict_label} ({n_passed}/{len(checks)} checks)")
    return metrics_json, verdict_label


if __name__ == "__main__":
    metrics, verdict = main()
    sys.exit(0 if verdict == "PASS" else 1)
