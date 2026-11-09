"""
Strategy: H97 52-Week-High Proximity Sector Rotation (Long-Only, Trend-Gated)
Author: Strategy Coder Agent
Date: 2026-11-09
Hypothesis: Sector ETFs closest to their 252-day high keep outperforming (George and Hwang 2004
            anchoring, Moskowitz and Grinblatt 1999 industry momentum). Buy the top 3 sectors by
            Close / max(High, 252d) at month-end when ratio > 0.90 and SPY Close > SMA(200); hold SHY
            when the gate is off. Exit when a sector leaves the top 3 or ratio < 0.85, or when it
            closes more than 12% below entry.
Asset class: equities (SPDR sector ETFs)
Parent task: QUA-914 (QUA-911)
References:
    research/hypotheses/97_qc_52wk_high_sector_momentum.md

Execution model: signal and fill both at the month-end Close (market-on-close convention from the
hypothesis). Every rank input uses data up to and including that Close. The stop is evaluated on
the daily Close and fills at that Close. A stopped sector stays out until the next month-end.
Held sectors keep their drifted weight between rebalances (equal weight applies at entry only).
Slots with no qualifying sector stay in cash; SHY is held only when the SPY gate is off.
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
    "refuge_ticker": "SHY",     # held while the gate is off; yfinance history starts 2002-07
    "high_window": 252,         # trading days for the rolling High
    "n_long": 3,                # top-N sectors by ratio
    "min_ratio": 0.90,          # entry needs ratio > min_ratio
    "exit_ratio": 0.85,         # a held sector exits below this ratio
    "trend_sma": 200,           # SPY SMA gate length
    "stop_pct": 0.12,           # None disables the stop; exit when Close < entry * (1 - stop_pct)
    "position_pct": 1.0 / 3.0,  # fraction of equity per position
    "init_cash": 100000.0,
    "data_start": "1998-12-01",
}

# Transaction cost model (Engineering Director AGENTS.md, ruling ED-SLIP-001)
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_STANDARD = 0.0005       # 0.05%
SLIPPAGE_ULTRA_LIQUID = 0.00005  # 0.005% for SPY/QQQ/IWM
MARKET_IMPACT_K = 0.1
SIGMA_WINDOW = 20
ADV_WINDOW = 20
LIQUIDITY_FLAG_THRESHOLD = 0.01  # Q / ADV
TRADING_DAYS_PER_YEAR = 252


def download_data(params: dict = PARAMETERS, start: Optional[str] = None,
                  end: Optional[str] = None) -> Dict[str, pd.DataFrame]:
    """
    Download split/dividend-adjusted daily OHLCV (yfinance auto_adjust=True) for sectors, gate and refuge.
    Returns dict of field name -> DataFrame (columns = tickers).
    """
    import yfinance as yf

    tickers = list(params["tickers"]) + [params["gate_ticker"], params["refuge_ticker"]]
    raw = yf.download(tickers, start=start or params["data_start"], end=end, auto_adjust=True,
                      progress=False, group_by="column")
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned no data for H97 universe")
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
    """Per-ticker first date, bar count, and gaps > 5 calendar days. Feeds the pre-backtest checklist."""
    close = data["close"]
    report = {}
    for tk in close.columns:
        s = close[tk].dropna()
        if s.empty:
            report[tk] = {"first_date": None, "last_date": None, "n_bars": 0, "gaps_gt_5d": []}
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


def monthly_rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last trading day of each calendar month present in `index`."""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby(index.to_period("M")).max().values)


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


def select_targets(ratio: pd.Series, held: set, params: dict, rng=None) -> List[str]:
    """
    Month-end target sectors. A candidate qualifies when ratio > min_ratio (new entry) or, if already
    held, ratio >= exit_ratio. Real mode: top n_long by ratio, then filtered by qualification.
    Null mode (rng given): n_long random picks from the qualifying pool, which tests ranking skill only.
    """
    r = ratio.dropna()

    def qualifies(tk: str) -> bool:
        return r[tk] >= params["exit_ratio"] if tk in held else r[tk] > params["min_ratio"]

    if rng is None:
        return [tk for tk in r.nlargest(params["n_long"]).index if qualifies(tk)]
    pool = [tk for tk in r.index if qualifies(tk)]
    if not pool:
        return []
    k = min(params["n_long"], len(pool))
    return list(rng.choice(pool, size=k, replace=False))


def run_backtest(data: Dict[str, pd.DataFrame], params: dict = PARAMETERS, seed: Optional[int] = None) -> dict:
    """
    Simulate the strategy over all of `data`. Returns equity Series, daily returns, trade list.
    seed: when set, picks sectors at random from the qualifying pool (permutation null).
    """
    sectors = [t for t in params["tickers"] if t in data["close"].columns]
    gate_tk, refuge = params["gate_ticker"], params["refuge_ticker"]
    close = data["close"]
    spy = close[gate_tk]
    gate = spy > spy.rolling(params["trend_sma"]).mean()
    ratio = close[sectors] / data["high"][sectors].rolling(params["high_window"]).max()
    cols = sectors + ([refuge] if refuge in close.columns else [])
    sigma = close[cols].pct_change(fill_method=None).rolling(SIGMA_WINDOW).std()
    adv = data["volume"][cols].rolling(ADV_WINDOW).mean()
    rebal = set(monthly_rebalance_dates(close.index))
    rng = np.random.default_rng(seed) if seed is not None else None
    stop_pct = params["stop_pct"]

    # first day with a valid SMA gate and at least one valid ratio
    valid = gate.notna().values & ratio.notna().any(axis=1).values
    start_i = int(np.argmax(valid))
    cash = float(params["init_cash"])
    positions: Dict[str, dict] = {}
    trades: List[dict] = []
    equity = {}

    def close_pos(tk: str, dt: pd.Timestamp, px: float, reason: str) -> float:
        p = positions.pop(tk)
        cost, liq = trade_cost(p["shares"], px, tk, sigma.at[dt, tk], adv.at[dt, tk], params)
        proceeds = p["shares"] * px - cost
        pnl = proceeds - p["cost_basis"]
        trades.append({
            "ticker": tk, "entry_date": str(p["date"].date()), "exit_date": str(dt.date()),
            "entry_px": p["px"], "exit_px": px, "shares": p["shares"], "pnl": float(pnl),
            "ret": float(pnl / p["cost_basis"]), "reason": reason,
            "liquidity_constrained": bool(liq or p["liq"]), "refuge": tk == refuge,
        })
        return proceeds

    def open_pos(tk: str, dt: pd.Timestamp, budget: float, cash_now: float) -> float:
        """Buy up to `budget` dollars of `tk` at Close; return cash spent (0 if the order is skipped)."""
        px = float(close.at[dt, tk])
        if not np.isfinite(px):
            return 0.0
        shares = int(budget // px)
        if shares <= 0:
            return 0.0
        cost, liq = trade_cost(shares, px, tk, sigma.at[dt, tk], adv.at[dt, tk], params)
        outlay = shares * px + cost
        if outlay > cash_now:
            shares = int((cash_now - cost) // px)
            if shares <= 0:
                return 0.0
            cost, liq = trade_cost(shares, px, tk, sigma.at[dt, tk], adv.at[dt, tk], params)
            outlay = shares * px + cost
        stop_px = px * (1 - stop_pct) if stop_pct is not None and tk != refuge else -np.inf
        positions[tk] = {"shares": shares, "px": px, "date": dt, "stop": float(stop_px),
                         "cost_basis": outlay, "liq": liq}
        return outlay

    for i in range(start_i, len(close.index)):
        dt = close.index[i]
        # 1. stops on Close
        if stop_pct is not None:
            for tk in list(positions):
                px = close.at[dt, tk]
                if np.isfinite(px) and px < positions[tk]["stop"]:
                    cash += close_pos(tk, dt, float(px), "stop")
        # 2. monthly rebalance at Close
        if dt in rebal:
            if not bool(gate.iat[i]):
                for tk in list(positions):
                    if tk != refuge and np.isfinite(close.at[dt, tk]):
                        cash += close_pos(tk, dt, float(close.at[dt, tk]), "gate_off")
                if refuge in close.columns and refuge not in positions and np.isfinite(close.at[dt, refuge]):
                    cash -= open_pos(refuge, dt, cash, cash)
            else:
                if refuge in positions and np.isfinite(close.at[dt, refuge]):
                    cash += close_pos(refuge, dt, float(close.at[dt, refuge]), "gate_on")
                held = {tk for tk in positions if tk != refuge}
                targets = select_targets(ratio.loc[dt], held, params, rng)
                for tk in list(positions):
                    if tk not in targets and np.isfinite(close.at[dt, tk]):
                        cash += close_pos(tk, dt, float(close.at[dt, tk]), "rebalance")
                equity_now = cash + sum(p["shares"] * close.at[dt, k] for k, p in positions.items())
                for tk in targets:
                    if tk not in positions:
                        cash -= open_pos(tk, dt, params["position_pct"] * equity_now, cash)
        mtm = sum(p["shares"] * close.at[dt, tk] for tk, p in positions.items() if np.isfinite(close.at[dt, tk]))
        equity[dt] = cash + mtm

    eq = pd.Series(equity, name="equity")
    return {"equity": eq, "returns": eq.pct_change().dropna(), "trades": trades}


def compute_metrics(res: dict, start: str, end: str) -> dict:
    """
    Sharpe (rf=0), MDD, CAGR, per-trade win rate and profit factor for sector trades exited in [start, end].
    Refuge (SHY) trades are excluded from trade statistics and counted separately.
    """
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
    all_tr = [t for t in res["trades"] if start <= t["exit_date"] <= end]
    tr = [t for t in all_tr if not t["refuge"]]
    wins = [t["pnl"] for t in tr if t["pnl"] > 0]
    losses = [-t["pnl"] for t in tr if t["pnl"] <= 0]
    return {
        "sharpe": round(sharpe, 4), "max_drawdown": round(mdd, 4), "cagr": round(cagr, 4),
        "win_rate": round(len(wins) / len(tr), 4) if tr else 0.0,
        "profit_factor": round(sum(wins) / sum(losses), 4) if losses and sum(losses) > 0 else 0.0,
        "trade_count": len(tr), "refuge_trade_count": len(all_tr) - len(tr), "n_days": int(len(r)),
        "stop_exits": sum(1 for t in tr if t["reason"] == "stop"),
        "liquidity_constrained_trades": sum(1 for t in all_tr if t["liquidity_constrained"]),
    }


if __name__ == "__main__":
    d = download_data()
    out = run_backtest(d)
    print(compute_metrics(out, "2000-01-01", "2019-12-31"))
