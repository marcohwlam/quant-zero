"""
H69: Macro-Regime Sector Rotation
QUA-278 — Engineering Director Gate 1 backtest

SPY + TLT 20-day momentum → 4-regime SPDR sector ETF rotation.
Monthly rebalancing, $100K initial capital, Track A (daily bars).

Regime map:
  A: EM>0 & BM<=0 → XLK, XLY, XLF   (Growth / Risk-On)
  B: EM<=0 & BM>0 → XLU, XLP, XLV   (Defensive / Risk-Off)
  C: EM<=0 & BM<=0 → XLE, XLB        (Stagflation; +cash gate if SPY<200-DMA)
  D: EM>0 & BM>0  → XLI, XLRE, XLF  (Recovery / Reflation; XLRE from 2015-10-07)

Cost model (ED canonical):
  Fixed:   $0.005/share
  Slip:    0.05% of notional (standard tier — sector ETFs ADV < 50M/day)
  Impact:  k=0.1 × σ × √(Q/ADV) × notional  (Almgren-Chriss)
"""

import warnings
import logging
from datetime import timedelta

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252

SIGNAL_TICKERS = ["SPY", "TLT"]
CASH_TICKER = "SHY"
SECTOR_TICKERS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLRE", "XLC", "XLU", "XLB"]
ALL_TICKERS = SIGNAL_TICKERS + [CASH_TICKER] + SECTOR_TICKERS

XLRE_INCEPTION = pd.Timestamp("2015-10-07")

REGIME_SECTORS = {
    "A": ["XLK", "XLY", "XLF"],
    "B": ["XLU", "XLP", "XLV"],
    "C": ["XLE", "XLB"],
    "D": ["XLI", "XLRE", "XLF"],
}

PARAMETERS = {
    "lookback_days":      20,
    "dma_gate":           True,
    "regime_c_cash_pct":  0.50,
    "rebal_day":          "first",
    "init_cash":          100_000.0,
}

FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_RATE        = 0.0005   # 0.05% standard tier
MARKET_IMPACT_K      = 0.1


# ── Data ─────────────────────────────────────────────────────────────────────

def _download_single(ticker: str, fetch_from: str, fetch_to: str) -> tuple:
    """Download a single ticker; return (close_series, volume_series) or (None, None)."""
    try:
        raw = yf.download(ticker, start=fetch_from, end=fetch_to,
                          auto_adjust=True, progress=False, threads=False)
        if raw.empty:
            return None, None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        close_s  = raw["Close"]  if "Close"  in raw.columns else None
        volume_s = raw["Volume"] if "Volume" in raw.columns else None
        return close_s, volume_s
    except Exception as e:
        logger.warning("Individual download failed for %s: %s", ticker, e)
        return None, None


def download_data(start: str, end: str):
    """
    Download daily close + volume for all tickers.
    Internally fetches 380 extra calendar days before `start` to
    support 200-DMA and 20-day lookback at the IS start boundary.
    Falls back to individual downloads for critical tickers that fail.
    Returns (close_df, volume_df).
    """
    dt_start   = pd.Timestamp(start)
    dt_end     = pd.Timestamp(end)
    fetch_from = (dt_start - timedelta(days=380)).strftime("%Y-%m-%d")
    fetch_to   = (dt_end + timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info("Downloading data: %s → %s (fetch from %s)", start, end, fetch_from)

    # Download signal + cash tickers separately to avoid bulk-download failures
    # on long date ranges when mixed with many sector tickers
    sig_raw = yf.download(
        SIGNAL_TICKERS + [CASH_TICKER],
        start=fetch_from, end=fetch_to,
        auto_adjust=True, progress=False, threads=True,
    )
    sec_raw = yf.download(
        SECTOR_TICKERS,
        start=fetch_from, end=fetch_to,
        auto_adjust=True, progress=False, threads=True,
    )

    def _extract(raw, tickers):
        if raw.empty:
            return pd.DataFrame(), pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            cl = raw["Close"].copy()
            vo = raw["Volume"].copy()
        else:
            # single ticker fallback
            cl = raw[["Close"]].rename(columns={"Close": tickers[0]}) if len(tickers) == 1 else raw
            vo = raw[["Volume"]].rename(columns={"Volume": tickers[0]}) if len(tickers) == 1 else raw
        cl.columns = [str(c) for c in cl.columns]
        vo.columns = [str(c) for c in vo.columns]
        return cl, vo

    sig_close, sig_vol = _extract(sig_raw, SIGNAL_TICKERS + [CASH_TICKER])
    sec_close, sec_vol = _extract(sec_raw, SECTOR_TICKERS)

    # Merge on common index
    close  = pd.concat([sig_close, sec_close], axis=1)
    volume = pd.concat([sig_vol,  sec_vol],  axis=1)

    # Retry any missing critical tickers individually
    for ticker in ["SPY", "TLT"]:
        col = str(ticker)
        if col not in close.columns or close[col].dropna().empty:
            logger.info("Retrying individual download for %s ...", ticker)
            cs, vs = _download_single(ticker, fetch_from, fetch_to)
            if cs is not None:
                close[col]  = cs
            if vs is not None:
                volume[col] = vs

    # Remove duplicate columns
    close  = close.loc[:, ~close.columns.duplicated()]
    volume = volume.loc[:, ~volume.columns.duplicated()]

    # Forward-fill up to 3 days (holidays, missing data)
    close  = close.ffill(limit=3)
    volume = volume.ffill(limit=3)

    return close, volume


# ── Signal & Allocation ───────────────────────────────────────────────────────

def classify_regime(em: float, bm: float) -> str:
    if em > 0 and bm <= 0:
        return "A"
    if em <= 0 and bm > 0:
        return "B"
    if em <= 0 and bm <= 0:
        return "C"
    return "D"  # em > 0 and bm > 0


def get_target_allocation(
    regime: str,
    exec_date: pd.Timestamp,
    spy_hist: pd.Series,
    dma_gate: bool,
    regime_c_cash_pct: float,
    close_on_exec: pd.Series,
) -> dict:
    """
    Return {ticker: weight} for the given regime.
    Handles XLRE missing history and Regime C cash gate.
    """
    if regime in ("A", "B"):
        sectors = REGIME_SECTORS[regime]
        w = 1.0 / len(sectors)
        return {s: w for s in sectors}

    if regime == "D":
        sectors = list(REGIME_SECTORS["D"])  # ["XLI", "XLRE", "XLF"]
        # XLRE unavailable before inception date
        if exec_date < XLRE_INCEPTION or "XLRE" not in close_on_exec.index or pd.isna(close_on_exec.get("XLRE", float("nan"))):
            sectors = ["XLI", "XLF"]
        # Also skip any ticker with NaN price
        avail = [s for s in sectors if s in close_on_exec.index and not pd.isna(close_on_exec.get(s, float("nan")))]
        if not avail:
            return {}
        w = 1.0 / len(avail)
        return {s: w for s in avail}

    # Regime C
    sectors = list(REGIME_SECTORS["C"])  # ["XLE", "XLB"]
    avail = [s for s in sectors if s in close_on_exec.index and not pd.isna(close_on_exec.get(s, float("nan")))]
    if not avail:
        return {}

    cash_pct = 0.0
    if dma_gate and len(spy_hist) >= 200:
        dma200 = float(spy_hist.iloc[-200:].mean())
        current_spy = float(spy_hist.iloc[-1])
        if current_spy < dma200:
            cash_pct = regime_c_cash_pct

    sector_pct = 1.0 - cash_pct
    alloc = {s: sector_pct / len(avail) for s in avail}
    if cash_pct > 0.0:
        alloc[CASH_TICKER] = cash_pct
    return alloc


# ── Cost Model ────────────────────────────────────────────────────────────────

def compute_trade_cost(
    shares: float,
    price: float,
    adv: float,
    sigma: float,
) -> float:
    """One-way transaction cost (ED canonical table)."""
    notional = abs(shares) * price
    fixed    = abs(shares) * FIXED_COST_PER_SHARE
    slip     = notional * SLIPPAGE_RATE
    impact   = notional * MARKET_IMPACT_K * sigma * np.sqrt(abs(shares) / max(adv, 1.0))
    return fixed + slip + impact


# ── Simulation ────────────────────────────────────────────────────────────────

def simulate_h69(close: pd.DataFrame, volume: pd.DataFrame, params: dict) -> dict:
    """
    Core H69 monthly rotation simulation.

    Returns dict with equity curve, trades, daily_df, and summary metrics.
    """
    lookback          = int(params.get("lookback_days", 20))
    dma_gate          = bool(params.get("dma_gate", True))
    regime_c_cash_pct = float(params.get("regime_c_cash_pct", 0.50))
    rebal_day         = str(params.get("rebal_day", "first"))
    init_cash         = float(params.get("init_cash", 100_000.0))

    if "SPY" not in close.columns or "TLT" not in close.columns:
        return _empty_result("Missing SPY or TLT in data")

    spy_full = close["SPY"].dropna()
    tlt_full = close["TLT"].dropna()

    # Build monthly groups
    all_dates = pd.DatetimeIndex(sorted(close.index))
    month_groups = {}
    for d in all_dates:
        key = (d.year, d.month)
        month_groups.setdefault(key, []).append(d)
    sorted_months = sorted(month_groups.keys())

    # Build (signal_date, exec_date, month_key) schedule
    schedule = []
    for i, mkey in enumerate(sorted_months):
        days = sorted(month_groups[mkey])
        if rebal_day == "first":
            sig_date = days[-1]  # last day of this month → signal
            if i + 1 < len(sorted_months):
                next_days = sorted(month_groups[sorted_months[i + 1]])
                exec_date = next_days[0]  # first day of next month → execution
            else:
                continue
        else:  # "last"
            # Signal on second-to-last day; execute on last day
            if len(days) < 2:
                continue
            sig_date  = days[-2]
            exec_date = days[-1]

        schedule.append((sig_date, exec_date))

    # Simulation state
    cash       = init_cash
    positions  = {}   # {ticker: shares}
    prev_alloc = {}

    equity_daily = {}
    regime_daily = {}   # exec_date → regime
    trades_list  = []
    rt_list      = []   # round-trip records: {ticker, buy_date, sell_date, buy_price, sell_price, shares, gross_pnl, cost_total, net_pnl}

    # Track open buys per ticker for round-trip pairing
    open_buys = {}  # {ticker: {date, price, shares, cost}}

    # Rolling ADV and sigma helpers
    def _adv_sigma(ticker, as_of_date):
        try:
            if ticker not in volume.columns or ticker not in close.columns:
                return 1e6, 0.01
            vol_hist = volume[ticker][volume.index <= as_of_date]
            prc_hist = close[ticker][close.index <= as_of_date]
            adv_ = float(vol_hist.rolling(20).mean().iloc[-1]) if len(vol_hist) >= 20 else 1e6
            sigma_ = float(prc_hist.pct_change().rolling(20).std().iloc[-1]) if len(prc_hist) >= 21 else 0.01
            if np.isnan(adv_) or adv_ <= 0:
                adv_ = 1e6
            if np.isnan(sigma_) or sigma_ <= 0:
                sigma_ = 0.01
            return adv_, sigma_
        except Exception:
            return 1e6, 0.01

    def _price(ticker, date):
        if ticker not in close.columns:
            return None
        p = close.loc[date, ticker] if date in close.index else None
        if p is None or (isinstance(p, float) and np.isnan(p)):
            return None
        return float(p)

    for sig_date, exec_date in schedule:
        # Compute signals at sig_date
        spy_hist_sig = spy_full[spy_full.index <= sig_date]
        tlt_hist_sig = tlt_full[tlt_full.index <= sig_date]

        if len(spy_hist_sig) < lookback + 2 or len(tlt_hist_sig) < lookback + 2:
            continue
        if exec_date not in close.index:
            continue

        em = float(spy_hist_sig.iloc[-1]) / float(spy_hist_sig.iloc[-(lookback + 1)]) - 1
        bm = float(tlt_hist_sig.iloc[-1]) / float(tlt_hist_sig.iloc[-(lookback + 1)]) - 1
        regime = classify_regime(em, bm)

        close_exec = close.loc[exec_date]
        new_alloc  = get_target_allocation(
            regime, exec_date, spy_hist_sig,
            dma_gate, regime_c_cash_pct, close_exec
        )

        if not new_alloc:
            regime_daily[exec_date] = regime
            continue

        # Skip rebalancing if allocation unchanged
        if new_alloc == prev_alloc:
            regime_daily[exec_date] = regime
            continue

        # --- Mark current portfolio value at exec_date prices ---
        pv = cash
        for t, sh in positions.items():
            p = _price(t, exec_date)
            if p is not None:
                pv += sh * p

        # --- Sell all existing positions ---
        for t, sh in list(positions.items()):
            if sh <= 0:
                continue
            p = _price(t, exec_date)
            if p is None:
                continue
            adv, sigma = _adv_sigma(t, exec_date)
            cost = compute_trade_cost(sh, p, adv, sigma)
            proceeds = sh * p - cost
            cash += proceeds

            trades_list.append({
                "date": exec_date, "ticker": t, "action": "sell",
                "shares": sh, "price": p, "cost": cost,
                "gross_notional": sh * p, "regime": regime,
            })
            # Pair with open buy
            if t in open_buys:
                ob = open_buys.pop(t)
                gross_pnl = (p - ob["price"]) * sh
                net_pnl   = gross_pnl - cost - ob["cost"]
                rt_list.append({
                    "ticker": t,
                    "buy_date": ob["date"], "sell_date": exec_date,
                    "buy_price": ob["price"], "sell_price": p,
                    "shares": sh,
                    "gross_pnl": gross_pnl,
                    "cost_total": cost + ob["cost"],
                    "net_pnl": net_pnl,
                    "buy_notional": ob["price"] * sh,
                    "regime": regime,
                })

        positions   = {}
        open_buys   = {}

        # --- Buy new target positions ---
        for t, w in new_alloc.items():
            if t == CASH_TICKER:
                # Keep as uninvested cash (SHY return approximated by holding cash)
                # Optionally buy SHY — treat cash as 0% for simplicity in simulation
                continue
            p = _price(t, exec_date)
            if p is None or p <= 0:
                continue
            notional = pv * w
            sh       = notional / p
            adv, sigma = _adv_sigma(t, exec_date)
            cost = compute_trade_cost(sh, p, adv, sigma)
            cash -= (sh * p + cost)
            positions[t] = sh

            trades_list.append({
                "date": exec_date, "ticker": t, "action": "buy",
                "shares": sh, "price": p, "cost": cost,
                "gross_notional": sh * p, "regime": regime,
            })
            open_buys[t] = {"date": exec_date, "price": p, "shares": sh, "cost": cost}

        prev_alloc     = dict(new_alloc)
        regime_daily[exec_date] = regime

    # --- Daily equity curve ---
    last_known_regime = "—"
    for date in sorted(close.index):
        pv = cash
        for t, sh in positions.items():
            p = _price(t, date)
            if p is not None:
                pv += sh * p
        equity_daily[date] = pv
        if date in regime_daily:
            last_known_regime = regime_daily[date]

    equity = pd.Series(equity_daily).sort_index()
    returns = equity.pct_change().fillna(0.0)

    # --- Metrics ---
    n = len(returns)
    if n < 2 or returns.std() < 1e-10:
        return _empty_result("Insufficient returns")

    sharpe       = float(returns.mean() / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    n_years      = n / TRADING_DAYS_PER_YEAR
    cagr         = float((1 + total_return) ** (1 / max(n_years, 0.1)) - 1)

    roll_max     = equity.cummax()
    drawdowns    = (equity - roll_max) / roll_max
    max_drawdown = float(drawdowns.min())

    # Round-trip stats
    rt_df = pd.DataFrame(rt_list) if rt_list else pd.DataFrame()
    if not rt_df.empty:
        winners    = rt_df[rt_df["net_pnl"] > 0]["net_pnl"]
        losers     = rt_df[rt_df["net_pnl"] <= 0]["net_pnl"]
        win_rate   = float(len(winners) / len(rt_df))
        pf_denom   = abs(losers.sum()) if not losers.empty else 1e-8
        profit_factor = float(winners.sum() / pf_denom) if not winners.empty else 0.0
        avg_ppt_bps  = float(rt_df["net_pnl"].mean() / rt_df["buy_notional"].mean() * 10000) if not rt_df.empty else 0.0
        # CPR: total costs / sum of gross profit from winning round-trips
        total_costs  = float(rt_df["cost_total"].sum())
        gross_wins   = float(rt_df[rt_df["net_pnl"] > 0]["gross_pnl"].sum()) if not winners.empty else 1.0
        cpr          = total_costs / gross_wins if gross_wins > 0 else 1.0
        trade_count  = len(rt_df)
        avg_hold_days = float((rt_df["sell_date"] - rt_df["buy_date"]).dt.days.mean()) if not rt_df.empty else 22.0
    else:
        win_rate = profit_factor = avg_ppt_bps = cpr = 0.0
        trade_count = avg_hold_days = 0

    # Regime counts and transitions
    rm_list = [v for _, v in sorted(regime_daily.items())]
    regime_counts = {"A": rm_list.count("A"), "B": rm_list.count("B"),
                     "C": rm_list.count("C"), "D": rm_list.count("D")}
    n_transitions = sum(1 for i in range(1, len(rm_list)) if rm_list[i] != rm_list[i - 1])
    transitions_per_year = float(n_transitions) / max(n_years, 0.1)

    # Daily df for permutation test
    daily_df = pd.DataFrame({"equity": equity})
    daily_df["regime"] = None
    for d, r in regime_daily.items():
        if d in daily_df.index:
            daily_df.loc[d, "regime"] = r
    daily_df["regime"] = daily_df["regime"].ffill()

    # Monthly regime sequence for permutation test
    regime_monthly = [
        {"date": str(exec_date.date()), "regime": r}
        for exec_date, r in sorted(regime_daily.items())
    ]

    trades_df = pd.DataFrame(trades_list)

    return {
        "sharpe":           sharpe,
        "cagr":             cagr,
        "max_drawdown":     max_drawdown,
        "total_return":     total_return,
        "win_rate":         win_rate,
        "profit_factor":    profit_factor,
        "trade_count":      trade_count,
        "n_transitions":    n_transitions,
        "transitions_per_year": transitions_per_year,
        "avg_hold_days":    avg_hold_days,
        "cpr":              cpr,
        "net_ppt_bps":      avg_ppt_bps,
        "regime_counts":    regime_counts,
        "equity":           equity,
        "trades":           trades_df,
        "round_trips":      rt_df,
        "daily_df":         daily_df,
        "regime_monthly":   regime_monthly,
        "n_months":         len(schedule),
    }


def _empty_result(reason: str = "") -> dict:
    return {
        "sharpe": np.nan, "cagr": 0.0, "max_drawdown": 0.0,
        "total_return": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
        "trade_count": 0, "n_transitions": 0, "transitions_per_year": 0.0,
        "avg_hold_days": 0.0, "cpr": 1.0, "net_ppt_bps": 0.0,
        "regime_counts": {"A": 0, "B": 0, "C": 0, "D": 0},
        "equity": pd.Series(dtype=float),
        "trades": pd.DataFrame(),
        "round_trips": pd.DataFrame(),
        "daily_df": pd.DataFrame(),
        "regime_monthly": [],
        "n_months": 0,
        "error": reason,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict) -> dict:
    """Full backtest for [start, end] with given params. Downloads data internally."""
    try:
        close, volume = download_data(start, end)
        # Clip to requested window
        dt_start = pd.Timestamp(start)
        dt_end   = pd.Timestamp(end)
        close    = close[(close.index >= dt_start) | True]   # keep full for lookback
        result   = simulate_h69(close, volume, params)
        # Clip equity to requested window
        if "equity" in result and not result["equity"].empty:
            result["equity"] = result["equity"][
                (result["equity"].index >= dt_start) &
                (result["equity"].index <= dt_end)
            ]
            if not result["equity"].empty:
                eq = result["equity"]
                rets = eq.pct_change().fillna(0.0)
                n = len(rets)
                result["sharpe"] = (
                    float(rets.mean() / rets.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
                    if rets.std() > 1e-10 else np.nan
                )
                result["total_return"] = float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0
                n_years = n / TRADING_DAYS_PER_YEAR
                result["cagr"] = float(
                    (1 + result["total_return"]) ** (1 / max(n_years, 0.1)) - 1
                )
                roll_max = eq.cummax()
                result["max_drawdown"] = float(((eq - roll_max) / roll_max).min())
        return result
    except Exception as e:
        logger.exception("run_backtest failed: %s", e)
        r = _empty_result(str(e))
        return r
