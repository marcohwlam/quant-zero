"""
Strategy: H95 Sector ETF Weekly Reversal (Long-Only, Trend-Gated)
Author: Strategy Coder Agent
Date: 2026-11-09
Hypothesis: Sector ETFs that fell the most over the last 5 trading days mean-revert over the next
            week. Buy the 2 worst sectors at Friday Close, exit at the next Friday Close, and stay
            in cash when SPY Close <= SMA(200). Hard stop at 2.5 x ATR(14) below entry.
Asset class: equities (SPDR sector ETFs)
Parent task: QUA-912 (QUA-911)
References:
    research/hypotheses/95_qc_sector_weekly_reversal.md
    Lo and MacKinlay (1990), Jegadeesh (1990)

Execution model: signal and fill both at the Friday Close (market-on-close convention from the
hypothesis). All rank inputs use data up to and including that Close. The stop is evaluated on daily
Close and fills at that Close.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SECTOR_TICKERS = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
ULTRA_LIQUID = {"SPY", "QQQ", "IWM"}

PARAMETERS = {
    "tickers": SECTOR_TICKERS,
    "gate_ticker": "SPY",
    "lookback_days": 5,         # reversal horizon in trading days
    "n_long": 2,                # number of worst sectors to buy
    "trend_sma": 200,           # SPY SMA gate length
    "stop_atr_mult": 2.5,       # None disables the stop
    "atr_window": 14,
    "position_pct": 0.40,       # fraction of equity per position
    "init_cash": 100000.0,
    "data_start": "1998-12-01",
}

# Transaction cost model (Engineering Director AGENTS.md, ruling ED-SLIP-001)
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_STANDARD = 0.0005      # 0.05%
SLIPPAGE_ULTRA_LIQUID = 0.00005  # 0.005% for SPY/QQQ/IWM
MARKET_IMPACT_K = 0.1
SIGMA_WINDOW = 20
ADV_WINDOW = 20
LIQUIDITY_FLAG_THRESHOLD = 0.01  # Q / ADV
TRADING_DAYS_PER_YEAR = 252


def download_data(params: dict = PARAMETERS, start: Optional[str] = None,
                  end: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    """
    Download split/dividend-adjusted daily OHLCV (yfinance auto_adjust=True) for sectors + gate ticker.
    Returns dict of field name -> DataFrame (columns = tickers).
    """
    import yfinance as yf

    tickers = list(params["tickers"]) + [params["gate_ticker"]]
    raw = yf.download(tickers, start=start or params["data_start"], end=end, auto_adjust=True,
                      progress=False, group_by="column")
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned no data for H95 universe")
    data = {f.lower(): raw[f].sort_index() for f in ["Open", "High", "Low", "Close", "Volume"]}
    data["close"] = data["close"].dropna(how="all")
    return validate_data(data, params)


def validate_data(data: Dict[str, pd.DataFrame], params: dict = PARAMETERS) -> Dict[str, pd.DataFrame]:
    """Check required fields and tickers; raise ValueError with a descriptive message otherwise."""
    for f in ("open", "high", "low", "close", "volume"):
        if f not in data:
            raise ValueError(f"missing data field: {f}")
    if params["gate_ticker"] not in data["close"].columns:
        raise ValueError(f"gate ticker {params['gate_ticker']} missing from data")
    if not data["close"].index.is_monotonic_increasing:
        raise ValueError("price index must be sorted ascending")
    if (data["close"].dropna(how="all") <= 0).any().any():
        raise ValueError("non-positive close prices found")
    return data


def data_quality_report(data: Dict[str, pd.DataFrame], params: dict = PARAMETERS) -> dict:
    """Per-ticker first date, gaps > 5 calendar days, and NaN share. Used for the pre-backtest checklist."""
    close = data["close"]
    report = {}
    for tk in close.columns:
        s = close[tk].dropna()
        if s.empty:
            report[tk] = {"first_date": None, "n_bars": 0, "gaps_gt_5d": []}
            continue
        gaps = s.index.to_series().diff().dt.days
        big = gaps[gaps > 5]
        report[tk] = {
            "first_date": str(s.index[0].date()),
            "last_date": str(s.index[-1].date()),
            "n_bars": int(len(s)),
            "gaps_gt_5d": [{"end": str(d.date()), "days": int(v)} for d, v in big.items()],
        }
    return report


def _atr(data: Dict[str, pd.DataFrame], tickers: List[str], window: int) -> pd.DataFrame:
    """ATR(window) as the simple rolling mean of true range, from adjusted OHLC."""
    high, low, close = data["high"][tickers], data["low"][tickers], data["close"][tickers]
    pc = close.shift(1)
    tr = np.maximum(high - low, np.maximum((high - pc).abs(), (low - pc).abs()))
    return tr.rolling(window).mean()


def weekly_rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each ISO calendar week (Friday, or Thursday when Friday is a holiday)."""
    s = pd.Series(index, index=index)
    iso = index.isocalendar()
    keys = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    return pd.DatetimeIndex(s.groupby(keys.values).max().values)


def trade_cost(shares: int, price: float, ticker: str, sigma: float, adv: float, params: dict = PARAMETERS):
    """
    One-side cost in dollars for an order of `shares` at `price`.
    Returns (cost_dollars, liquidity_constrained). Impact = k * sigma * sqrt(Q / ADV).
    """
    if shares <= 0:
        return 0.0, False
    slip = SLIPPAGE_ULTRA_LIQUID if ticker in ULTRA_LIQUID else SLIPPAGE_STANDARD
    participation = shares / adv if adv and adv > 0 and np.isfinite(adv) else 0.0
    impact = MARKET_IMPACT_K * (sigma if np.isfinite(sigma) else 0.0) * np.sqrt(participation)
    notional = shares * price
    cost = shares * FIXED_COST_PER_SHARE + notional * (slip + impact)
    return float(cost), bool(participation > LIQUIDITY_FLAG_THRESHOLD)


def run_backtest(data: Dict[str, pd.DataFrame], params: dict = PARAMETERS, seed: Optional[int] = None) -> dict:
    """
    Simulate the strategy over all of `data`. Returns equity Series, daily returns, trade list.
    seed: when set, picks n_long sectors at random instead of the worst (permutation null).
    """
    sectors = [t for t in params["tickers"] if t in data["close"].columns]
    gate_tk = params["gate_ticker"]
    close = data["close"]
    spy = close[gate_tk]
    gate = (spy > spy.rolling(params["trend_sma"]).mean())
    ret_n = close[sectors].pct_change(params["lookback_days"], fill_method=None)
    atr = _atr(data, sectors, params["atr_window"])
    sigma = close[sectors].pct_change(fill_method=None).rolling(SIGMA_WINDOW).std()
    adv = data["volume"][sectors].rolling(ADV_WINDOW).mean()
    rebal = set(weekly_rebalance_dates(close.index))
    rng = np.random.default_rng(seed) if seed is not None else None

    start_i = int(np.argmax(gate.notna().values))  # first day with a valid SMA
    cash = float(params["init_cash"])
    positions: Dict[str, dict] = {}
    trades: List[dict] = []
    equity = {}
    stop_mult = params["stop_atr_mult"]

    def close_pos(tk: str, dt: pd.Timestamp, px: float, reason: str) -> float:
        p = positions.pop(tk)
        cost, liq = trade_cost(p["shares"], px, tk, sigma.at[dt, tk], adv.at[dt, tk], params)
        proceeds = p["shares"] * px - cost
        pnl = proceeds - p["cost_basis"]
        trades.append({
            "ticker": tk, "entry_date": str(p["date"].date()), "exit_date": str(dt.date()),
            "entry_px": p["px"], "exit_px": px, "shares": p["shares"], "pnl": float(pnl),
            "ret": float(pnl / p["cost_basis"]), "reason": reason,
            "liquidity_constrained": bool(liq or p["liq"]),
        })
        return proceeds

    for i in range(start_i, len(close.index)):
        dt = close.index[i]
        # 1. stops on Close
        if stop_mult is not None:
            for tk in list(positions):
                px = close.at[dt, tk]
                if np.isfinite(px) and px < positions[tk]["stop"]:
                    cash += close_pos(tk, dt, float(px), "stop")
        # 2. weekly rebalance at Close
        if dt in rebal:
            for tk in list(positions):
                px = close.at[dt, tk]
                if not np.isfinite(px):
                    continue
                cash += close_pos(tk, dt, float(px), "rebalance")
            if bool(gate.iat[i]):
                cand = ret_n.loc[dt].dropna()
                cand = cand[[t for t in cand.index if np.isfinite(atr.at[dt, t]) and np.isfinite(close.at[dt, t])]]
                if len(cand) >= params["n_long"]:
                    if rng is not None:
                        picks = list(rng.choice(cand.index.values, size=params["n_long"], replace=False))
                    else:
                        picks = list(cand.nsmallest(params["n_long"]).index)
                    equity_now = cash + sum(p["shares"] * close.at[dt, k] for k, p in positions.items())
                    for tk in picks:
                        px = float(close.at[dt, tk])
                        shares = int(params["position_pct"] * equity_now // px)
                        if shares <= 0:
                            continue
                        cost, liq = trade_cost(shares, px, tk, sigma.at[dt, tk], adv.at[dt, tk], params)
                        outlay = shares * px + cost
                        if outlay > cash:
                            continue
                        cash -= outlay
                        stop_px = px - stop_mult * atr.at[dt, tk] if stop_mult is not None else -np.inf
                        positions[tk] = {"shares": shares, "px": px, "date": dt, "stop": float(stop_px),
                                         "cost_basis": outlay, "liq": liq}
        mtm = sum(p["shares"] * close.at[dt, tk] for tk, p in positions.items() if np.isfinite(close.at[dt, tk]))
        equity[dt] = cash + mtm

    eq = pd.Series(equity, name="equity")
    return {"equity": eq, "returns": eq.pct_change().dropna(), "trades": trades}


def compute_metrics(res: dict, start: str, end: str) -> dict:
    """Sharpe (rf=0), MDD, CAGR, per-trade win rate and profit factor for trades exited in [start, end]."""
    r = res["returns"].loc[start:end]
    if len(r) < 2:
        return {"sharpe": 0.0, "max_drawdown": 0.0, "cagr": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
                "trade_count": 0, "n_days": len(r)}
    cum = (1 + r).cumprod()
    mdd = float(((cum - cum.cummax()) / cum.cummax()).min())
    sd = r.std()
    sharpe = float(r.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR)) if sd > 1e-12 else 0.0
    years = len(r) / TRADING_DAYS_PER_YEAR
    cagr = float(cum.iloc[-1] ** (1 / years) - 1)
    tr = [t for t in res["trades"] if start <= t["exit_date"] <= end]
    wins = [t["pnl"] for t in tr if t["pnl"] > 0]
    losses = [-t["pnl"] for t in tr if t["pnl"] <= 0]
    return {
        "sharpe": round(sharpe, 4), "max_drawdown": round(mdd, 4), "cagr": round(cagr, 4),
        "win_rate": round(len(wins) / len(tr), 4) if tr else 0.0,
        "profit_factor": round(sum(wins) / sum(losses), 4) if losses and sum(losses) > 0 else 0.0,
        "trade_count": len(tr), "n_days": int(len(r)),
        "stop_exits": sum(1 for t in tr if t["reason"] == "stop"),
        "liquidity_constrained_trades": sum(1 for t in tr if t["liquidity_constrained"]),
    }


if __name__ == "__main__":
    d = download_data()
    out = run_backtest(d)
    print(compute_metrics(out, "2000-01-01", "2019-12-31"))
