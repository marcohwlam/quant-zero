"""
H86 Post-Earnings Gap Continuation — Gate 1 Backtest
QUA-393

IS:  2023-07-01 → 2025-03-31
OOS: 2025-04-01 → 2026-06-23

Criteria: v2.7 / kpi-daily-weekly.md
  IS Sharpe > 1.0 | OOS Sharpe > 0.7 | IS MDD < 20%
  IS trade count >= 100 | Win rate IS > 50% | Profit factor IS > 1.0

Execution model (no look-ahead):
  - Gap = T+0 open vs T-1 close + 20d vol through T-1
  - Entry at T+entry_delay close (regime gate checked at entry time)
  - Stop/regime: same-day close flag → next-day open exit
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

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

REPO_ROOT = Path(__file__).parent.parent
TODAY = date.today().isoformat()
STRATEGY_NAME = "H86_PostEarningsGapContinuation"
OUT_DIR = REPO_ROOT / "backtests"
TRADING_DAYS = 252

IS_START  = "2023-07-01"
IS_END    = "2025-03-31"
OOS_START = "2025-04-01"
OOS_END   = TODAY

# Cost model (ED-SLIP-001 equities)
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_PCT         = 0.0005   # 0.05% one-way
MARKET_IMPACT_K      = 0.1
SIGMA_WINDOW         = 20
ADV_WINDOW           = 20

# Base parameters
BASE_PARAMS = {
    "gap_pct_min":       0.03,
    "gap_vol_ratio_min": 1.5,
    "entry_delay_days":  2,
    "hold_days":         30,
    "stop_loss_pct":     0.07,
    "spy_sma_period":    200,
    "max_positions":     10,
    "max_position_pct":  0.05,
    "init_cash":         25_000,
}

# Sweep grid (hypothesis §Parameters to Test)
SWEEP_GAP_PCT       = [0.02, 0.03, 0.05]
SWEEP_VOL_RATIO     = [1.0,  1.5,  2.0]
SWEEP_ENTRY_DELAY   = [1,    2,    3]
SWEEP_HOLD_DAYS     = [20,   30,   40]
SWEEP_STOP_LOSS     = [0.05, 0.07, 0.10]


# ── Universe ────────────────────────────────────────────────────────────────────

def get_sp500_universe() -> list:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", header=0)
        tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"Universe: {len(tickers)} tickers (Wikipedia S&P 500)")
        return tickers
    except Exception as exc:
        warnings.warn(f"Wikipedia fetch failed ({exc}). Using fallback list.")
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSLA",
            "JPM", "V", "UNH", "XOM", "JNJ", "WMT", "MA", "PG", "COST", "HD",
            "BAC", "CVX", "LLY", "ABBV", "KO", "MRK", "PEP", "AVGO", "ADBE",
            "CRM", "TMO", "MCD", "ACN", "ABT", "AMD", "NFLX", "DIS", "CSCO",
            "TXN", "HON", "INTC", "AMGN", "IBM", "NOW", "INTU", "QCOM", "LOW",
        ]


def get_earnings_dates(ticker: str) -> pd.DatetimeIndex:
    try:
        df = yf.Ticker(ticker).get_earnings_dates(limit=60)
        if df is None or df.empty:
            return pd.DatetimeIndex([])
        dates = df.index.tz_localize(None) if df.index.tz is not None else df.index
        return dates[dates <= pd.Timestamp.today()].normalize()
    except Exception:
        return pd.DatetimeIndex([])


def load_earnings_dates(tickers: list) -> tuple:
    earnings_map = {}
    skipped = 0
    for sym in tickers:
        dates = get_earnings_dates(sym)
        if len(dates) < 2:
            skipped += 1
            continue
        earnings_map[sym] = set(dates)
    coverage_rate = len(earnings_map) / max(len(tickers), 1)
    print(f"Earnings: {len(earnings_map)}/{len(tickers)} ({coverage_rate:.1%}) | skipped: {skipped}")
    return earnings_map, coverage_rate


# ── Data Download ────────────────────────────────────────────────────────────────

def download_ticker(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(set(raw.columns)) or len(raw) < 50:
            return None
        return raw
    except Exception:
        return None


# ── Transaction Cost ─────────────────────────────────────────────────────────────

def compute_cost(price: float, shares: int, close_series: pd.Series,
                 vol_series: pd.Series, idx: int) -> float:
    fixed    = FIXED_COST_PER_SHARE * shares
    slippage = SLIPPAGE_PCT * price * shares
    sigma    = close_series.pct_change().rolling(SIGMA_WINDOW).std().iloc[idx]
    adv      = vol_series.rolling(ADV_WINDOW).mean().iloc[idx]
    if pd.isna(sigma) or sigma <= 0:
        sigma = 0.01
    if pd.isna(adv) or adv <= 0:
        adv = 1e6
    impact = MARKET_IMPACT_K * sigma * np.sqrt(shares / adv) * price * shares
    return fixed + slippage + impact


# ── Core Simulation (reusable with pre-loaded data) ─────────────────────────────

def simulate(
    params: dict,
    trading_days: pd.DatetimeIndex,
    spy_regime: pd.Series,        # bool series indexed by trading_days
    price_data: dict,             # sym -> DataFrame (OHLCV, full history incl. warmup)
    earnings_map: dict,           # sym -> set[Timestamp]
) -> dict:
    """
    Run the H86 simulation loop over `trading_days` with pre-loaded data.
    Returns dict with equity_curve, trade_log, daily_returns.
    """
    gap_pct_min    = params["gap_pct_min"]
    vol_ratio_min  = params["gap_vol_ratio_min"]
    entry_delay    = params["entry_delay_days"]
    hold_days_p    = params["hold_days"]
    stop_pct       = params["stop_loss_pct"]
    max_pos        = params["max_positions"]
    max_pos_pct    = params["max_position_pct"]
    init_cash      = params["init_cash"]

    capital         = float(init_cash)
    equity_curve    = pd.Series(np.nan, index=trading_days, dtype=float)
    pending_entries = []   # {sym, entry_day_idx}
    open_positions  = []   # position dicts
    trade_log       = []

    for t_idx, t_date in enumerate(trading_days):
        regime_today = bool(spy_regime.get(t_date, False))
        t_ts = pd.Timestamp(t_date).normalize()

        # ── 1. Open-priced exits ────────────────────────────────────────────────
        still_open = []
        for pos in open_positions:
            reason = pos.get("open_exit_reason")
            if not reason:
                still_open.append(pos)
                continue
            sym = pos["sym"]
            df  = price_data.get(sym)
            if df is None or t_date not in df.index:
                pos["open_exit_reason"] = None
                still_open.append(pos)
                continue
            pidx    = df.index.get_loc(t_date)
            open_p  = float(df["Open"].iloc[pidx])
            if open_p <= 0:
                pos["open_exit_reason"] = None
                still_open.append(pos)
                continue
            cost    = compute_cost(open_p, pos["shares"], df["Close"], df["Volume"], pidx)
            eff_ex  = open_p - cost / pos["shares"]
            pnl     = (eff_ex - pos["entry_price"]) * pos["shares"]
            capital += eff_ex * pos["shares"]
            trade_log.append({
                "sym":           sym,
                "entry_date":    pos["entry_date"],
                "exit_date":     str(t_date.date()),
                "entry_price":   round(pos["entry_price"], 4),
                "exit_price":    round(eff_ex, 4),
                "shares":        pos["shares"],
                "pnl":           round(pnl, 2),
                "hold_days":     pos["hold_days"],
                "exit_reason":   reason,
            })
        open_positions = still_open

        # ── 2. Close-priced entries (pending due today) ─────────────────────────
        new_pending = []
        for pend in pending_entries:
            if pend["entry_day_idx"] > t_idx:
                new_pending.append(pend)
                continue
            if pend["entry_day_idx"] < t_idx:
                continue  # past-due, drop
            sym = pend["sym"]
            if not regime_today:
                continue
            if len(open_positions) >= max_pos:
                continue
            if any(p["sym"] == sym for p in open_positions):
                continue
            df = price_data.get(sym)
            if df is None or t_date not in df.index:
                continue
            pidx    = df.index.get_loc(t_date)
            close_p = float(df["Close"].iloc[pidx])
            if close_p <= 0:
                continue
            alloc  = min(init_cash * max_pos_pct, capital)
            shares = int(alloc / close_p)
            if shares <= 0:
                continue
            cost   = compute_cost(close_p, shares, df["Close"], df["Volume"], pidx)
            eff_en = close_p + cost / shares
            capital -= eff_en * shares
            open_positions.append({
                "sym":              sym,
                "entry_date":       str(t_date.date()),
                "entry_price":      eff_en,
                "entry_close":      close_p,
                "shares":           shares,
                "hold_days":        0,
                "open_exit_reason": None,
            })
        pending_entries = new_pending

        # ── 3. Scan earnings gaps; queue entries ────────────────────────────────
        if regime_today:
            active_syms  = {p["sym"] for p in open_positions}
            pending_syms = {p["sym"] for p in pending_entries}
            for sym, earn_dates in earnings_map.items():
                if t_ts not in earn_dates:
                    continue
                if sym in active_syms or sym in pending_syms:
                    continue
                df = price_data.get(sym)
                if df is None or t_date not in df.index:
                    continue
                pidx = df.index.get_loc(t_date)
                if pidx < 1:
                    continue
                open_t    = float(df["Open"].iloc[pidx])
                close_tm1 = float(df["Close"].iloc[pidx - 1])
                if close_tm1 <= 0 or open_t <= 0:
                    continue
                gap_pct = (open_t - close_tm1) / close_tm1
                if gap_pct < gap_pct_min:
                    continue
                vol_20d = df["Close"].pct_change().rolling(SIGMA_WINDOW).std().iloc[pidx - 1]
                if pd.isna(vol_20d) or vol_20d <= 0:
                    continue
                if gap_pct < vol_ratio_min * vol_20d:
                    continue
                eidx = t_idx + entry_delay
                if eidx >= len(trading_days):
                    continue
                pending_entries.append({"sym": sym, "entry_day_idx": eidx})

        # ── 4. Time-based exits at today's close ────────────────────────────────
        still_open = []
        for pos in open_positions:
            pos["hold_days"] += 1
            if pos["hold_days"] < hold_days_p:
                still_open.append(pos)
                continue
            sym = pos["sym"]
            df  = price_data.get(sym)
            if df is None or t_date not in df.index:
                still_open.append(pos)
                continue
            pidx    = df.index.get_loc(t_date)
            close_p = float(df["Close"].iloc[pidx])
            if close_p <= 0 or pos["shares"] <= 0:
                still_open.append(pos)
                continue
            cost    = compute_cost(close_p, pos["shares"], df["Close"], df["Volume"], pidx)
            eff_ex  = close_p - cost / pos["shares"]
            pnl     = (eff_ex - pos["entry_price"]) * pos["shares"]
            capital += eff_ex * pos["shares"]
            trade_log.append({
                "sym":           sym,
                "entry_date":    pos["entry_date"],
                "exit_date":     str(t_date.date()),
                "entry_price":   round(pos["entry_price"], 4),
                "exit_price":    round(eff_ex, 4),
                "shares":        pos["shares"],
                "pnl":           round(pnl, 2),
                "hold_days":     pos["hold_days"],
                "exit_reason":   "TIME_EXIT",
            })
        open_positions = still_open

        # ── 5. Flag for next-open exits ─────────────────────────────────────────
        for pos in open_positions:
            df = price_data.get(pos["sym"])
            if df is None or t_date not in df.index:
                continue
            pidx    = df.index.get_loc(t_date)
            close_p = float(df["Close"].iloc[pidx])
            if close_p < pos["entry_close"] * (1.0 - stop_pct):
                pos["open_exit_reason"] = "STOP_LOSS"
            elif not regime_today:
                pos["open_exit_reason"] = "REGIME_EXIT"
            else:
                pos["open_exit_reason"] = None

        # ── 6. Mark-to-market ───────────────────────────────────────────────────
        mtm = capital
        for pos in open_positions:
            df = price_data.get(pos["sym"])
            if df is not None and t_date in df.index:
                mtm += pos["shares"] * float(df["Close"].loc[t_date])
        equity_curve.iloc[t_idx] = mtm

    # Force-close remaining at end
    last_date = trading_days[-1]
    for pos in open_positions:
        df = price_data.get(pos["sym"])
        if df is None or last_date not in df.index:
            continue
        pidx    = df.index.get_loc(last_date)
        close_p = float(df["Close"].iloc[pidx])
        if close_p <= 0:
            continue
        cost    = compute_cost(close_p, pos["shares"], df["Close"], df["Volume"], pidx)
        eff_ex  = close_p - cost / pos["shares"]
        pnl     = (eff_ex - pos["entry_price"]) * pos["shares"]
        capital += eff_ex * pos["shares"]
        trade_log.append({
            "sym":           pos["sym"],
            "entry_date":    pos["entry_date"],
            "exit_date":     str(last_date.date()),
            "entry_price":   round(pos["entry_price"], 4),
            "exit_price":    round(eff_ex, 4),
            "shares":        pos["shares"],
            "pnl":           round(pnl, 2),
            "hold_days":     pos["hold_days"],
            "exit_reason":   "END_OF_DATA",
        })

    equity_curve = equity_curve.ffill().fillna(float(init_cash))
    daily_returns = equity_curve.pct_change().fillna(0.0)
    return {
        "equity_curve":   equity_curve,
        "daily_returns":  daily_returns,
        "trade_log":      trade_log,
    }


# ── Metrics ──────────────────────────────────────────────────────────────────────

def compute_metrics(equity: pd.Series, trade_log: list, label: str) -> dict:
    pv  = equity.dropna()
    if len(pv) < 2:
        return {"error": "insufficient data"}
    ret = pv.pct_change().fillna(0.0).values
    sharpe = float(ret.mean() / (ret.std() + 1e-10) * np.sqrt(TRADING_DAYS))
    cum      = np.cumprod(1 + ret)
    roll_max = np.maximum.accumulate(cum)
    mdd      = float(np.min((cum - roll_max) / (roll_max + 1e-8)))
    total_ret = float(cum[-1] - 1.0)

    closed = [t for t in trade_log if t.get("exit_reason") != "END_OF_DATA"]
    win_rate = pf = 0.0
    if closed:
        pnl_arr  = np.array([t["pnl"] for t in closed])
        win_rate = float(np.mean(pnl_arr > 0))
        wins     = pnl_arr[pnl_arr > 0].sum()
        losses   = abs(pnl_arr[pnl_arr < 0].sum())
        pf       = round(float(wins / max(losses, 1e-8)), 4)
        pf       = float("inf") if pf > 1e6 else pf
    return {
        "label":         label,
        "sharpe":        round(sharpe, 4),
        "max_drawdown":  round(mdd, 4),
        "total_return":  round(total_ret, 4),
        "win_rate":      round(win_rate, 4),
        "profit_factor": pf,
        "trade_count":   len(closed),
        "_ret":          ret,
    }


# ── Statistical Rigor ─────────────────────────────────────────────────────────────

def monte_carlo_sharpe(pnl_arr: np.ndarray, n_sims: int = 1000) -> dict:
    np.random.seed(42)
    if len(pnl_arr) < 5:
        return {"mc_p5_sharpe": 0.0, "mc_median_sharpe": 0.0, "mc_p95_sharpe": 0.0}
    sharpes = []
    for _ in range(n_sims):
        s  = np.random.choice(pnl_arr, size=len(pnl_arr), replace=True)
        sh = s.mean() / (s.std() + 1e-8) * np.sqrt(TRADING_DAYS)
        sharpes.append(sh)
    arr = np.array(sharpes)
    return {
        "mc_p5_sharpe":     float(np.percentile(arr, 5)),
        "mc_median_sharpe": float(np.median(arr)),
        "mc_p95_sharpe":    float(np.percentile(arr, 95)),
    }


def block_bootstrap_ci(returns: np.ndarray, n_boots: int = 1000) -> dict:
    np.random.seed(43)
    T         = len(returns)
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
                "mdd_ci_low": 0.0, "mdd_ci_high": 0.0,
                "win_rate_ci_low": 0.0, "win_rate_ci_high": 0.0}
    return {
        "sharpe_ci_low":    float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_high":   float(np.percentile(sharpes, 97.5)),
        "mdd_ci_low":       float(np.percentile(mdds, 2.5)),
        "mdd_ci_high":      float(np.percentile(mdds, 97.5)),
        "win_rate_ci_low":  float(np.percentile(win_rates, 2.5)),
        "win_rate_ci_high": float(np.percentile(win_rates, 97.5)),
    }


def compute_dsr(is_sharpe: float, n_trials: int, T: int) -> float:
    if T <= 0 or n_trials <= 1:
        return float(is_sharpe)
    gamma  = 0.5772
    ln_n   = np.log(max(n_trials, 2))
    exp_max = (
        np.sqrt(2 * ln_n)
        - (np.log(np.log(max(n_trials, 2))) + np.log(4 * np.pi)) / (2 * np.sqrt(2 * ln_n))
        + gamma / np.sqrt(2 * ln_n)
    ) / np.sqrt(T)
    return round(float(is_sharpe - exp_max), 4)


def permutation_test(equity: pd.Series, observed_sharpe: float, n_perms: int = 500) -> dict:
    np.random.seed(44)
    returns = equity.pct_change().fillna(0.0).values
    T = len(returns)
    if T < 20:
        return {"permutation_pvalue": 0.5, "permutation_test_pass": False}
    perm_sharpes = []
    for _ in range(n_perms):
        shuffled = np.random.permutation(returns)
        s = float(shuffled.mean() / (shuffled.std() + 1e-8) * np.sqrt(TRADING_DAYS))
        perm_sharpes.append(s)
    perm_np = np.array(perm_sharpes)
    p_value = float(np.mean(perm_np >= observed_sharpe))
    return {
        "permutation_pvalue":    round(p_value, 4),
        "permutation_test_pass": p_value <= 0.05,
    }


def walk_forward_variance(oos_sharpes: list) -> dict:
    arr = np.array(oos_sharpes)
    return {
        "wf_sharpe_std": float(arr.std()),
        "wf_sharpe_min": float(arr.min()),
    }


# ── Walk-Forward ─────────────────────────────────────────────────────────────────

WF_WINDOWS = [
    ("2023-07-01", "2023-12-31", "2024-01-01", "2024-03-31"),
    ("2024-01-01", "2024-06-30", "2024-07-01", "2024-09-30"),
    ("2024-07-01", "2024-12-31", "2025-01-01", "2025-03-31"),
    ("2024-10-01", "2025-03-31", "2025-04-01", "2025-06-30"),
]


def run_walk_forward(spy_regime: pd.Series, price_data: dict,
                     earnings_map: dict, params: dict) -> list:
    results = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(WF_WINDOWS):
        try:
            all_days = spy_regime.index
            is_days  = all_days[(all_days >= pd.Timestamp(is_s)) & (all_days <= pd.Timestamp(is_e))]
            oos_days = all_days[(all_days >= pd.Timestamp(oos_s)) & (all_days <= pd.Timestamp(oos_e))]

            is_res  = simulate(params, is_days,  spy_regime, price_data, earnings_map)
            oos_res = simulate(params, oos_days, spy_regime, price_data, earnings_map)
            is_m    = compute_metrics(is_res["equity_curve"],  is_res["trade_log"],  "IS")
            oos_m   = compute_metrics(oos_res["equity_curve"], oos_res["trade_log"], "OOS")

            print(f"  WF{i+1} IS {is_s}–{is_e}: Sharpe={is_m['sharpe']:.3f} | "
                  f"OOS {oos_s}–{oos_e}: Sharpe={oos_m['sharpe']:.3f} | "
                  f"trades IS={is_m['trade_count']} OOS={oos_m['trade_count']}")
            results.append({
                "window":      i + 1,
                "is_start":    is_s, "is_end":   is_e,
                "oos_start":   oos_s, "oos_end": oos_e,
                "is_sharpe":   is_m["sharpe"],
                "oos_sharpe":  oos_m["sharpe"],
                "is_mdd":      is_m["max_drawdown"],
                "oos_mdd":     oos_m["max_drawdown"],
                "is_trades":   is_m["trade_count"],
                "oos_trades":  oos_m["trade_count"],
                "wf_pass":     oos_m["sharpe"] > 0.0,
            })
        except Exception as e:
            print(f"  WF{i+1} ERROR: {e}")
            results.append({"window": i+1, "error": str(e), "wf_pass": False,
                            "is_sharpe": 0.0, "oos_sharpe": 0.0})
    return results


# ── Parameter Sweep ───────────────────────────────────────────────────────────────

def run_sweep(spy_regime: pd.Series, price_data: dict, earnings_map: dict,
              is_days: pd.DatetimeIndex) -> list:
    """
    Run 3^5 = 243 combos over IS period using cached data.
    Only varies 5 parameters; spy_regime/price_data/earnings_map reused.
    """
    combos = list(iproduct(SWEEP_GAP_PCT, SWEEP_VOL_RATIO, SWEEP_ENTRY_DELAY,
                           SWEEP_HOLD_DAYS, SWEEP_STOP_LOSS))
    print(f"  {len(combos)} sweep combinations...")
    rows = []
    for i, (gp, vr, ed, hd, sl) in enumerate(combos):
        p = {**BASE_PARAMS, "gap_pct_min": gp, "gap_vol_ratio_min": vr,
             "entry_delay_days": ed, "hold_days": hd, "stop_loss_pct": sl}
        try:
            res = simulate(p, is_days, spy_regime, price_data, earnings_map)
            m   = compute_metrics(res["equity_curve"], res["trade_log"], "SWEEP")
            rows.append({
                "gap_pct_min": gp, "gap_vol_ratio_min": vr,
                "entry_delay_days": ed, "hold_days": hd, "stop_loss_pct": sl,
                "sharpe":        m["sharpe"],
                "max_drawdown":  m["max_drawdown"],
                "win_rate":      m["win_rate"],
                "profit_factor": m["profit_factor"],
                "trade_count":   m["trade_count"],
            })
            if (i + 1) % 30 == 0:
                print(f"    {i+1}/{len(combos)} done...")
        except Exception as e:
            rows.append({"gap_pct_min": gp, "gap_vol_ratio_min": vr,
                         "entry_delay_days": ed, "hold_days": hd, "stop_loss_pct": sl,
                         "error": str(e)})
    return rows


# ── HTML Report ───────────────────────────────────────────────────────────────────

def build_html_report(is_m: dict, oos_m: dict, checks: list, verdict_label: str,
                      mc: dict, bb: dict, perm: dict, dsr_val: float,
                      wf_results: list, sweep_rows: list, coverage_rate: float,
                      n_tickers: int) -> str:
    vc = "#d4edda" if verdict_label == "PASS" else "#f8d7da"
    check_rows = "".join(
        f"<tr style='background:{'#d4edda' if p else '#f8d7da'}'>"
        f"<td>{g}</td><td>{v}</td><td>{t}</td><td>{'✓ PASS' if p else '✗ FAIL'}</td></tr>"
        for g, v, t, p in checks
    )
    wf_rows = "".join(
        f"<tr style='background:{'#d4edda' if w.get('wf_pass') else '#f8d7da'}'>"
        f"<td>{w['window']}</td>"
        f"<td>{w.get('is_start','')}–{w.get('is_end','')}</td>"
        f"<td>{w.get('is_sharpe', 0):.4f}</td>"
        f"<td>{w.get('oos_start','')}–{w.get('oos_end','')}</td>"
        f"<td>{w.get('oos_sharpe', 0):.4f}</td>"
        f"<td>{w.get('is_trades', 0)}</td><td>{w.get('oos_trades', 0)}</td>"
        f"<td>{'✓' if w.get('wf_pass') else '✗'}</td></tr>"
        for w in wf_results
    )
    sweep_html = (pd.DataFrame(sweep_rows).to_html(index=False, border=1,
                  float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else str(x))
                  if sweep_rows else "<p>N/A</p>")

    pf = is_m.get("profit_factor", 0)
    pf_str = f"{pf:.4f}" if isinstance(pf, float) and not (pf == float("inf")) else str(pf)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>H86 Post-Earnings Gap Continuation — Gate 1</title>
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
<h1>H86 Post-Earnings Gap Continuation — Gate 1</h1>
<p><strong>Date:</strong> {TODAY} | <strong>Issue:</strong> QUA-393</p>
<p><strong>Universe:</strong> S&P 500 ({n_tickers} tickers, current constituents) | <strong>Earnings coverage:</strong> {coverage_rate:.1%}</p>
<p><strong>Signal:</strong> Earnings gap-up ≥ {BASE_PARAMS['gap_pct_min']:.0%} AND ≥ {BASE_PARAMS['gap_vol_ratio_min']}× 20d vol | Entry T+{BASE_PARAMS['entry_delay_days']} close | Hold {BASE_PARAMS['hold_days']}d | Stop {BASE_PARAMS['stop_loss_pct']:.0%}</p>
<p><strong>Regime gate:</strong> SPY > 200-SMA (long-only; cash when gate closed)</p>
<p><strong>IS:</strong> {IS_START} → {IS_END} | <strong>OOS:</strong> {OOS_START} → {OOS_END}</p>
<p><strong>Criteria:</strong> v2.7 — IS Sharpe &gt; 1.0 | OOS Sharpe &gt; 0.7 | IS MDD &lt; 20% | IS trades ≥ 100 | Win rate &gt; 50% | PF &gt; 1.0</p>
<p><strong>Cost model:</strong> $0.005/share + 0.05% slip + 0.1×σ×√(Q/ADV) market impact (equities ED-SLIP-001)</p>
<p><strong>Survivorship bias:</strong> MODERATE RISK, LOW MAGNITUDE — current S&P 500 constituent list; large-cap names rarely exit via bankruptcy.</p>

<div class="verdict">GATE 1: {verdict_label}</div>

<h2>Gate 1 Checklist (v2.7 / kpi-daily-weekly.md)</h2>
<table><tr><th>Gate</th><th>Value</th><th>Threshold</th><th>Result</th></tr>{check_rows}</table>

<h2>IS / OOS Summary</h2>
<div class="section">
<table>
<tr><th>Metric</th><th>IS ({IS_START}–{IS_END})</th><th>OOS ({OOS_START}–{OOS_END})</th></tr>
<tr><td>Sharpe</td><td>{is_m['sharpe']:.4f}</td><td>{oos_m['sharpe']:.4f}</td></tr>
<tr><td>Max Drawdown</td><td>{is_m['max_drawdown']:.2%}</td><td>{oos_m['max_drawdown']:.2%}</td></tr>
<tr><td>Total Return</td><td>{is_m['total_return']:.2%}</td><td>{oos_m['total_return']:.2%}</td></tr>
<tr><td>Win Rate</td><td>{is_m['win_rate']:.2%}</td><td>{oos_m['win_rate']:.2%}</td></tr>
<tr><td>Profit Factor</td><td>{pf_str}</td><td>{oos_m.get('profit_factor', 0):.4f}</td></tr>
<tr><td>Trade Count (closed)</td><td>{is_m['trade_count']}</td><td>{oos_m['trade_count']}</td></tr>
</table>
</div>

<h2>Statistical Tests</h2>
<div class="section">
<p><strong>Monte Carlo (1000 resamples):</strong> p5={mc['mc_p5_sharpe']:.4f}, median={mc['mc_median_sharpe']:.4f}, p95={mc['mc_p95_sharpe']:.4f}
   {'⚠️ MC p5 < 0.5 — pessimistic bound weak' if mc['mc_p5_sharpe'] < 0.5 else '✓'}</p>
<p><strong>Block Bootstrap CI (95%):</strong> Sharpe [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}] | MDD [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]</p>
<p><strong>Permutation test (500 perms):</strong> p={perm['permutation_pvalue']:.4f} — {'✓ PASS' if perm['permutation_test_pass'] else '✗ FAIL (no significant alpha)'}</p>
<p><strong>DSR:</strong> {dsr_val:.4f} — {'✓ PASS' if dsr_val > 0 else '✗ FAIL'}</p>
</div>

<h2>Walk-Forward Analysis ({len(WF_WINDOWS)} windows)</h2>
<table>
<tr><th>Win</th><th>IS Period</th><th>IS Sharpe</th><th>OOS Period</th><th>OOS Sharpe</th><th>IS Trades</th><th>OOS Trades</th><th>Pass</th></tr>
{wf_rows}
</table>

<h2>Parameter Sweep ({len(sweep_rows)} combinations — 3^5 grid)</h2>
{sweep_html}

<hr>
<p><em>Backtest Runner Agent | QUA-393 | H86 Gate 1 | {TODAY}</em></p>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print(f"H86 Post-Earnings Gap Continuation — Gate 1 Backtest")
    print(f"QUA-393 | {TODAY}")
    print(f"IS: {IS_START} → {IS_END} | OOS: {OOS_START} → {OOS_END}")
    print("=" * 70)

    # ── [1] Universe + Earnings ─────────────────────────────────────────────────
    print("\n[1/6] Fetching S&P 500 universe...")
    universe = get_sp500_universe()

    print("[2/6] Loading earnings dates (yfinance; ~3yr coverage; may take several minutes)...")
    earnings_map, coverage_rate = load_earnings_dates(universe)
    n_tickers = len(earnings_map)

    # ── [2] SPY + Price Data ────────────────────────────────────────────────────
    sma_period  = BASE_PARAMS["spy_sma_period"]
    warmup_days = int((sma_period + 30) * 1.5)
    data_start  = (pd.Timestamp(IS_START) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")

    print(f"\n[3/6] Downloading SPY ({data_start} → {TODAY})...")
    spy_raw = yf.download("SPY", start=data_start, end=TODAY, auto_adjust=True, progress=False)
    if isinstance(spy_raw.columns, pd.MultiIndex):
        spy_raw.columns = spy_raw.columns.get_level_values(0)
    spy_raw["sma200"]     = spy_raw["Close"].rolling(sma_period).mean()
    spy_raw["regime_up"]  = spy_raw["Close"] > spy_raw["sma200"]
    spy_regime = spy_raw["regime_up"].dropna()

    print(f"[4/6] Downloading price data for {n_tickers} tickers...")
    price_data = {}
    failed = 0
    for i, sym in enumerate(earnings_map):
        df = download_ticker(sym, data_start, TODAY)
        if df is not None:
            price_data[sym] = df
        else:
            failed += 1
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{n_tickers} downloaded ({failed} failed)...")
    print(f"  Done: {len(price_data)} loaded, {failed} failed")

    # Filter earnings_map to only tickers with price data
    earnings_map = {sym: dates for sym, dates in earnings_map.items() if sym in price_data}

    # ── [3] IS Backtest ─────────────────────────────────────────────────────────
    print(f"\n[5/6] IS Backtest {IS_START} → {IS_END}...")
    all_days = spy_regime.index
    is_days  = all_days[(all_days >= pd.Timestamp(IS_START)) & (all_days <= pd.Timestamp(IS_END))]
    oos_days = all_days[(all_days >= pd.Timestamp(OOS_START)) & (all_days <= pd.Timestamp(OOS_END))]

    is_res = simulate(BASE_PARAMS, is_days, spy_regime, price_data, earnings_map)
    is_m   = compute_metrics(is_res["equity_curve"], is_res["trade_log"], "IS")
    print(f"  Sharpe={is_m['sharpe']:.4f} | MDD={is_m['max_drawdown']:.2%} | "
          f"trades={is_m['trade_count']} | WR={is_m['win_rate']:.2%} | PF={is_m['profit_factor']}")

    # ── [4] OOS Backtest ────────────────────────────────────────────────────────
    print(f"\n[5/6] OOS Backtest {OOS_START} → {OOS_END}...")
    oos_res = simulate(BASE_PARAMS, oos_days, spy_regime, price_data, earnings_map)
    oos_m   = compute_metrics(oos_res["equity_curve"], oos_res["trade_log"], "OOS")
    print(f"  Sharpe={oos_m['sharpe']:.4f} | MDD={oos_m['max_drawdown']:.2%} | "
          f"trades={oos_m['trade_count']} | WR={oos_m['win_rate']:.2%} | PF={oos_m['profit_factor']}")

    # ── [5] Statistical Tests ───────────────────────────────────────────────────
    print("\n[6/6] Statistical rigor pipeline...")
    closed_is  = [t for t in is_res["trade_log"] if t.get("exit_reason") != "END_OF_DATA"]
    pnl_arr    = np.array([t["pnl"] for t in closed_is]) if closed_is else np.array([0.0])
    ret_arr_is = is_res["daily_returns"].values

    mc      = monte_carlo_sharpe(pnl_arr)
    bb      = block_bootstrap_ci(ret_arr_is)
    perm    = permutation_test(is_res["equity_curve"], is_m["sharpe"])
    n_sweep = len(list(iproduct(SWEEP_GAP_PCT, SWEEP_VOL_RATIO, SWEEP_ENTRY_DELAY,
                                SWEEP_HOLD_DAYS, SWEEP_STOP_LOSS)))
    dsr_val = compute_dsr(is_m["sharpe"], n_sweep + len(WF_WINDOWS), len(is_days))
    print(f"  MC p5={mc['mc_p5_sharpe']:.3f} | BB CI=[{bb['sharpe_ci_low']:.3f},{bb['sharpe_ci_high']:.3f}]")
    print(f"  Perm p={perm['permutation_pvalue']:.4f} ({'PASS' if perm['permutation_test_pass'] else 'FAIL'}) | DSR={dsr_val:.4f}")

    # Walk-forward
    print("\n[WF] Walk-forward (4 windows)...")
    wf_results  = run_walk_forward(spy_regime, price_data, earnings_map, BASE_PARAMS)
    oos_sharpes = [w.get("oos_sharpe", 0.0) for w in wf_results]
    wf_passed   = sum(1 for w in wf_results if w.get("wf_pass", False))
    wf_var      = walk_forward_variance(oos_sharpes)
    print(f"  WF OOS Sharpe>0: {wf_passed}/{len(WF_WINDOWS)} | std={wf_var['wf_sharpe_std']:.3f} | min={wf_var['wf_sharpe_min']:.3f}")

    # Parameter sweep
    print("\n[SWEEP] Parameter sweep (3^5=243 combos over IS)...")
    sweep_rows = run_sweep(spy_regime, price_data, earnings_map, is_days)
    valid_sh   = [r["sharpe"] for r in sweep_rows if "sharpe" in r and isinstance(r.get("sharpe"), float)]
    if valid_sh:
        sr_range = max(valid_sh) - min(valid_sh)
        sr_base  = abs(is_m["sharpe"]) if is_m["sharpe"] != 0 else 1.0
        sens_var_pct = sr_range / sr_base
        sens_pass = sens_var_pct < 0.50
        print(f"  Sharpe range: {min(valid_sh):.3f}–{max(valid_sh):.3f} | var={sens_var_pct:.1%} | {'PASS' if sens_pass else 'FAIL'}")
    else:
        sens_pass = False
        sens_var_pct = float("nan")

    # ── Gate 1 Checklist ────────────────────────────────────────────────────────
    gate_is_sharpe = is_m["sharpe"]   > 1.0
    gate_oos_sharpe= oos_m["sharpe"]  > 0.7
    gate_is_mdd    = is_m["max_drawdown"] > -0.20
    gate_trades    = is_m["trade_count"] >= 100
    gate_win_rate  = is_m["win_rate"]  > 0.50
    pf_val = is_m["profit_factor"]
    gate_pf        = (isinstance(pf_val, float) and pf_val > 1.0) or pf_val == float("inf")
    gate_dsr       = dsr_val > 0.0
    gate_wf        = wf_passed >= 3
    gate_sens      = sens_pass
    gate_perm      = perm["permutation_test_pass"]
    pf_str         = f"{pf_val:.4f}" if isinstance(pf_val, float) and pf_val != float("inf") else "inf"

    checks = [
        ("IS Sharpe",                 f"{is_m['sharpe']:.4f}",    "> 1.0",   gate_is_sharpe),
        ("OOS Sharpe",                f"{oos_m['sharpe']:.4f}",   "> 0.7",   gate_oos_sharpe),
        ("IS Max Drawdown",           f"{is_m['max_drawdown']:.2%}", "< 20%", gate_is_mdd),
        ("IS Trade Count",            str(is_m["trade_count"]),   ">= 100",  gate_trades),
        ("IS Win Rate",               f"{is_m['win_rate']:.2%}",  "> 50%",   gate_win_rate),
        ("IS Profit Factor",          pf_str,                     "> 1.0",   gate_pf),
        ("DSR",                       f"{dsr_val:.4f}",           "> 0",     gate_dsr),
        ("Walk-Forward OOS Sharpe>0", f"{wf_passed}/{len(WF_WINDOWS)}", ">= 3/4", gate_wf),
        ("Parameter Sensitivity",     f"{sens_var_pct:.1%}" if not np.isnan(sens_var_pct) else "N/A",
                                      "< 50% SR change",          gate_sens),
        ("Permutation Test",          f"p={perm['permutation_pvalue']:.4f}", "p < 0.05", gate_perm),
    ]
    n_passed      = sum(1 for *_, p in checks if p)
    verdict_label = "PASS" if all(p for *_, p in checks) else "FAIL"

    print(f"\n{'='*70}")
    print(f"H86 — GATE 1 VERDICT: {verdict_label} ({n_passed}/{len(checks)} checks)")
    for g, v, t, p in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {g:<30} {v}  (threshold: {t})")
    print(f"{'='*70}")

    # ── Save Outputs ────────────────────────────────────────────────────────────
    base = f"H86_PostEarningsGapContinuation_{TODAY}"

    # Trades CSV
    all_trades = is_res["trade_log"] + oos_res["trade_log"]
    trades_path = OUT_DIR / f"{base}_trades.csv"
    if all_trades:
        pd.DataFrame(all_trades).to_csv(trades_path, index=False)
        print(f"[SAVE] Trades: {trades_path} ({len(all_trades)} rows)")

    # Sweep CSV
    sweep_path = OUT_DIR / f"{base}_sweep.csv"
    if sweep_rows:
        pd.DataFrame(sweep_rows).to_csv(sweep_path, index=False)
        print(f"[SAVE] Sweep: {sweep_path} ({len(sweep_rows)} combos)")

    # HTML Report
    html = build_html_report(
        is_m, oos_m, checks, verdict_label, mc, bb, perm, dsr_val,
        wf_results, sweep_rows, coverage_rate, n_tickers,
    )
    html_path = OUT_DIR / f"{base}_report.html"
    html_path.write_text(html)
    print(f"[SAVE] Report: {html_path}")

    # JSON Metrics
    def safe_dict(d):
        return {k: v for k, v in d.items() if k not in ("_ret",)}

    metrics = {
        "strategy_name":          STRATEGY_NAME,
        "date":                   TODAY,
        "asset_class":            "equities",
        "is_sharpe":              is_m["sharpe"],
        "oos_sharpe":             oos_m["sharpe"],
        "is_max_drawdown":        is_m["max_drawdown"],
        "oos_max_drawdown":       oos_m["max_drawdown"],
        "is_win_rate":            is_m["win_rate"],
        "oos_win_rate":           oos_m["win_rate"],
        "is_profit_factor":       pf_str,
        "oos_profit_factor":      str(oos_m.get("profit_factor", 0)),
        "is_trade_count":         is_m["trade_count"],
        "oos_trade_count":        oos_m["trade_count"],
        "is_total_return":        is_m["total_return"],
        "oos_total_return":       oos_m["total_return"],
        "dsr":                    dsr_val,
        "gate1_pass":             verdict_label == "PASS",
        "overall_verdict":        verdict_label,
        "n_checks_passed":        n_passed,
        "n_checks_total":         len(checks),
        "mc_p5_sharpe":           mc["mc_p5_sharpe"],
        "mc_median_sharpe":       mc["mc_median_sharpe"],
        "mc_p95_sharpe":          mc["mc_p95_sharpe"],
        "sharpe_ci_low":          bb["sharpe_ci_low"],
        "sharpe_ci_high":         bb["sharpe_ci_high"],
        "mdd_ci_low":             bb["mdd_ci_low"],
        "mdd_ci_high":            bb["mdd_ci_high"],
        "win_rate_ci_low":        bb["win_rate_ci_low"],
        "win_rate_ci_high":       bb["win_rate_ci_high"],
        "permutation_pvalue":     perm["permutation_pvalue"],
        "permutation_test_pass":  perm["permutation_test_pass"],
        "wf_windows_passed":      wf_passed,
        "wf_sharpe_std":          wf_var["wf_sharpe_std"],
        "wf_sharpe_min":          wf_var["wf_sharpe_min"],
        "sensitivity_pass":       sens_pass,
        "sensitivity_sharpe_var_pct": float(sens_var_pct) if not np.isnan(sens_var_pct) else None,
        "earnings_coverage_rate": coverage_rate,
        "n_tickers_with_data":    n_tickers,
        "base_params":            BASE_PARAMS,
        "is_period":              f"{IS_START} to {IS_END}",
        "oos_period":             f"{OOS_START} to {OOS_END}",
        "criteria_version":       "v2.7 / kpi-daily-weekly.md",
        "wf_windows":             wf_results,
        "checks":                 [
            {"gate": g, "value": v, "threshold": t, "passed": p}
            for g, v, t, p in checks
        ],
        "survivorship_bias_note": (
            "WARNING: Universe = current-day S&P 500. Delisted/demoted stocks excluded. "
            "Mild upward bias; large-cap names rarely exit via bankruptcy."
        ),
        "look_ahead_bias_flag":   False,
        "look_ahead_note": (
            "CLEAN — gap = T+0 open vs T-1 close + 20d vol through T-1. "
            "Entry at T+entry_delay close. Stop/regime: same-day close flag, next-day open exit."
        ),
    }
    json_path = OUT_DIR / f"{base}.json"
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"[SAVE] Metrics JSON: {json_path}")

    # Verdict TXT
    failed_gates = [(g, v, t) for g, v, t, p in checks if not p]
    wf_lines = [
        f"  WF{w['window']} IS {w.get('is_start','')}–{w.get('is_end','')}: Sharpe={w.get('is_sharpe',0):.4f} | "
        f"OOS {w.get('oos_start','')}–{w.get('oos_end','')}: Sharpe={w.get('oos_sharpe',0):.4f} | "
        f"IS trades={w.get('is_trades',0)} | {'PASS' if w.get('wf_pass') else 'FAIL'}"
        for w in wf_results
    ]
    verdict_lines = [
        f"H86 Post-Earnings Gap Continuation — Gate 1 Verdict",
        f"{'='*70}",
        f"Date:       {TODAY}",
        f"Strategy:   {STRATEGY_NAME}",
        f"Issue:      QUA-393",
        f"IS:         {IS_START} → {IS_END}",
        f"OOS:        {OOS_START} → {OOS_END}",
        f"Criteria:   v2.7 / kpi-daily-weekly.md",
        f"Overall:    {verdict_label} ({n_passed}/{len(checks)} checks passed)",
        f"{'='*70}",
        f"",
        f"=== Universe ===",
        f"S&P 500 constituents (current): {len(universe)} tickers",
        f"Earnings coverage (yfinance):    {coverage_rate:.1%}",
        f"Tickers with price data:         {n_tickers}",
        f"Survivorship bias:               MODERATE RISK, LOW MAGNITUDE (large-cap names)",
        f"",
        f"=== IS Performance ({IS_START} → {IS_END}) ===",
        f"Sharpe:           {is_m['sharpe']:.4f}   [GATE: {'PASS' if gate_is_sharpe else 'FAIL'} > 1.0]",
        f"Max Drawdown:     {is_m['max_drawdown']:.2%}  [GATE: {'PASS' if gate_is_mdd else 'FAIL'} < 20%]",
        f"Total Return:     {is_m['total_return']:.2%}",
        f"Win Rate:         {is_m['win_rate']:.2%}     [GATE: {'PASS' if gate_win_rate else 'FAIL'} > 50%]",
        f"Profit Factor:    {pf_str}    [GATE: {'PASS' if gate_pf else 'FAIL'} > 1.0]",
        f"Trade Count:      {is_m['trade_count']}          [GATE: {'PASS' if gate_trades else 'FAIL'} >= 100]",
        f"",
        f"=== OOS Performance ({OOS_START} → {OOS_END}) ===",
        f"Sharpe:           {oos_m['sharpe']:.4f}   [GATE: {'PASS' if gate_oos_sharpe else 'FAIL'} > 0.7]",
        f"Max Drawdown:     {oos_m['max_drawdown']:.2%}",
        f"Total Return:     {oos_m['total_return']:.2%}",
        f"Win Rate:         {oos_m['win_rate']:.2%}",
        f"Trade Count:      {oos_m['trade_count']}",
        f"",
        f"=== Statistical Rigor ===",
        f"MC p5 Sharpe:       {mc['mc_p5_sharpe']:.4f}  {'⚠ weak' if mc['mc_p5_sharpe'] < 0.5 else '✓'}",
        f"MC Median Sharpe:   {mc['mc_median_sharpe']:.4f}",
        f"Sharpe 95% CI:      [{bb['sharpe_ci_low']:.4f}, {bb['sharpe_ci_high']:.4f}]",
        f"MDD 95% CI:         [{bb['mdd_ci_low']:.4f}, {bb['mdd_ci_high']:.4f}]",
        f"Permutation p:      {perm['permutation_pvalue']:.4f}  [{'PASS' if perm['permutation_test_pass'] else 'FAIL'}: < 0.05]",
        f"DSR:                {dsr_val:.4f}  [{'PASS' if gate_dsr else 'FAIL'}: > 0]",
        f"",
        f"=== Walk-Forward ({len(WF_WINDOWS)} windows) ===",
    ] + wf_lines + [
        f"  WF OOS Sharpe>0: {wf_passed}/{len(WF_WINDOWS)}  [{'PASS' if gate_wf else 'FAIL'}: >= 3/4]",
        f"  WF std={wf_var['wf_sharpe_std']:.4f} | min={wf_var['wf_sharpe_min']:.4f}",
        f"  {'⚠ min WF OOS Sharpe < 0 (at least one losing OOS window)' if wf_var['wf_sharpe_min'] < 0 else '✓ all WF OOS windows positive'}",
        f"",
        f"=== Parameter Sweep ({n_sweep} combos — 3^5 grid) ===",
    ]
    if valid_sh:
        verdict_lines += [
            f"  Sharpe range: {min(valid_sh):.4f} – {max(valid_sh):.4f}",
            f"  Variance vs primary: {sens_var_pct:.1%}  [{'PASS' if sens_pass else 'FAIL'}: < 50%]",
        ]
    verdict_lines += [
        f"",
        f"=== Gate 1 Checks (v2.7) ===",
    ] + [
        f"  [{'PASS' if p else 'FAIL'}] {g:<30} {v}  (threshold: {t})"
        for g, v, t, p in checks
    ]

    if verdict_label == "PASS":
        verdict_lines += [
            f"",
            f"=== Recommendation ===",
            f"PASS — advance to paper trading. Notify CEO for approval.",
        ]
    else:
        verdict_lines += [
            f"",
            f"=== Root Cause Analysis ===",
            f"Primary failures ({len(failed_gates)} of {len(checks)} gates):",
        ] + [f"  - {g}: got {v}, need {t}" for g, v, t in failed_gates] + [
            f"",
            f"=== Recommendation ===",
            f"REJECT — do not advance to paper trading.",
        ]

    verdict_lines += [
        f"",
        f"=== Data Quality ===",
        f"Look-ahead:         CLEAN (gap=T0_open/T-1_close+20d_vol; entry T+{BASE_PARAMS['entry_delay_days']} close)",
        f"Earnings source:    yfinance get_earnings_dates(limit=60) ~3yr coverage",
        f"Survivorship:       Current S&P 500 list — MODERATE RISK, LOW MAGNITUDE",
        f"Price adjusted:     True (auto_adjust=True)",
        f"",
        f"=== Files ===",
        f"Report:  backtests/{base}_report.html",
        f"Metrics: backtests/{base}.json",
        f"Verdict: backtests/{base}_verdict.txt",
        f"Trades:  backtests/{base}_trades.csv",
        f"Sweep:   backtests/{base}_sweep.csv",
    ]

    verdict_text = "\n".join(verdict_lines)
    verdict_path = OUT_DIR / f"{base}_verdict.txt"
    verdict_path.write_text(verdict_text)
    print(f"[SAVE] Verdict: {verdict_path}")

    print(f"\n{'='*70}")
    print(f"H86 GATE 1 FINAL: {verdict_label} ({n_passed}/{len(checks)} checks)")
    print(f"  IS  Sharpe={is_m['sharpe']:.4f} | OOS Sharpe={oos_m['sharpe']:.4f}")
    print(f"  IS  MDD={is_m['max_drawdown']:.2%} | IS trades={is_m['trade_count']}")
    print(f"  WF={wf_passed}/{len(WF_WINDOWS)} | DSR={dsr_val:.4f} | Perm p={perm['permutation_pvalue']:.4f}")
    print(f"{'='*70}")

    return metrics


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result.get("gate1_pass") else 1)
