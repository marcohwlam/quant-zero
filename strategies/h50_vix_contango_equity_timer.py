"""
Strategy: H50 VIX Contango/Backwardation Equity Timer
Author: Engineering Director (claude_local)
Date: 2026-06-08
Hypothesis: research/hypotheses/50_qc_vix_contango_equity_timer.md
Parent task: QUA-105

Signal: Daily VIX term structure.
  - VIX > VIX3M × ratio_threshold → backwardation (stress) → hold SHY
  - VIX ≤ VIX3M × ratio_threshold → contango (calm) → hold SPY

Persistence filters (look-ahead free):
  - Exit to SHY: exit_persistence consecutive backwardation days at close T → SHY from T+1
  - Re-entry to SPY: reentry_persistence consecutive contango days at close T → SPY from T+1

Data:
  - ^VIX  (CBOE VIX spot, available from 1990)
  - ^VIX3M (CBOE 3-Month VIX, available from Nov 2007; IS starts 2008 = full coverage)
  - SPY (risk-on ETF), SHY (risk-off short-term treasury ETF)

IS window:  2008-01-01 to 2021-12-31
OOS window: 2022-01-01 to 2024-12-31
"""

import logging
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_PARAMS = {
    "exit_persistence":   3,      # consecutive backwardation days before switching to SHY
    "reentry_persistence": 2,     # consecutive contango days before returning to SPY
    "ratio_threshold":    1.0,    # VIX/VIX3M ratio above which = backwardation

    # Transaction cost model (Almgren-Chriss square-root, Engineering Director standard)
    "fixed_cost_per_share": 0.005,
    "slippage_pct":          0.0005,
    "market_impact_k":       0.1,
    "sigma_window":          20,
    "adv_window":            20,
    "order_qty":             100,
    "liquidity_threshold":   0.01,

    "init_cash": 25000.0,
}

IS_START  = "2008-01-01"
IS_END    = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END   = "2024-12-31"
TRADING_DAYS_PER_YEAR = 252
WF_SHARPE_FLOOR = 0.3

WALK_FORWARD_WINDOWS = [
    ("2008-2009", "2008-01-01", "2009-12-31"),  # GFC crisis
    ("2010-2011", "2010-01-01", "2011-12-31"),  # recovery + European debt crisis
    ("2012-2013", "2012-01-01", "2013-12-31"),  # QE era, low VIX
    ("2014-2015", "2014-01-01", "2015-12-31"),  # China devaluation shock
    ("2016-2018", "2016-01-01", "2018-12-31"),  # volmageddon + Q4 2018 selloff
    ("2019-2021", "2019-01-01", "2021-12-31"),  # COVID crash + recovery
]

SENSITIVITY_GRID = [
    ("exit=1d",                  {"exit_persistence": 1}),
    ("exit=5d",                  {"exit_persistence": 5}),
    ("reentry=1d",               {"reentry_persistence": 1}),
    ("reentry=3d",               {"reentry_persistence": 3}),
    ("threshold=0.95",           {"ratio_threshold": 0.95}),
    ("threshold=1.05",           {"ratio_threshold": 1.05}),
    ("aggressive(e=1,r=1)",      {"exit_persistence": 1, "reentry_persistence": 1}),
    ("conservative(e=5,t=1.05)", {"exit_persistence": 5, "ratio_threshold": 1.05}),
]


# ── Data loading ──────────────────────────────────────────────────────────────

def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw.empty:
        raise ValueError(f"No data for {ticker} [{start} → {end}]")
    return raw


def _check_data_gaps(prices: pd.Series, label: str) -> str:
    all_dates = pd.date_range(prices.index.min(), prices.index.max(), freq="B")
    missing = all_dates.difference(prices.index)
    if len(missing) == 0:
        return "no_gaps_detected"
    missing_list = list(missing)
    runs, run = [], 1
    for i in range(1, len(missing_list)):
        if (missing_list[i] - missing_list[i - 1]).days == 1:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)
    max_run = max(runs) if runs else 0
    if max_run > 5:
        logger.warning("WARNING: %s max consecutive missing weekday run: %d", label, max_run)
        return f"flagged: max_consecutive_missing={max_run}"
    return f"ok: max_consecutive_missing={max_run} (<=5)"


def load_data(start: str, end: str):
    """
    Download ^VIX, ^VIX3M, SPY, SHY aligned to common trading days.
    Uses a 30-day warmup before `start` so persistence counters initialise cleanly.
    VIX3M (^VIX3M) available from Nov 2007; IS starts 2008, so full IS coverage.
    """
    warmup_start = (pd.Timestamp(start) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")

    logger.info("Downloading ^VIX  [%s → %s]", warmup_start, end)
    vix_df = _download("^VIX", warmup_start, end)

    logger.info("Downloading ^VIX3M [%s → %s]", warmup_start, end)
    try:
        vix3m_df = _download("^VIX3M", warmup_start, end)
    except ValueError:
        logger.warning("^VIX3M not found; trying ^VXV fallback")
        vix3m_df = _download("^VXV", warmup_start, end)

    logger.info("Downloading SPY   [%s → %s]", warmup_start, end)
    spy_df = _download("SPY", warmup_start, end)

    logger.info("Downloading SHY   [%s → %s]", warmup_start, end)
    shy_df = _download("SHY", warmup_start, end)

    common = (vix_df.index
              .intersection(vix3m_df.index)
              .intersection(spy_df.index)
              .intersection(shy_df.index))

    if len(common) == 0:
        raise ValueError("No overlapping trading days across VIX, VIX3M, SPY, SHY")

    vix_df   = vix_df.reindex(common)
    vix3m_df = vix3m_df.reindex(common)
    spy_df   = spy_df.reindex(common)
    shy_df   = shy_df.reindex(common)

    logger.info("Common index: %d days [%s → %s]",
                len(common), common[0].date(), common[-1].date())
    return vix_df, vix3m_df, spy_df, shy_df


# ── Signal generation ─────────────────────────────────────────────────────────

def generate_signals(
    vix_close: pd.Series,
    vix3m_close: pd.Series,
    params: dict,
) -> pd.Series:
    """
    Build daily regime Series: 'SPY' or 'SHY'.

    No look-ahead: VIX signal at close T determines regime from T+1.
    Equity curve applies shift(1), so position on T+1 earns T+1's return.

    Persistence:
      - current='SPY': switch to SHY after exit_persistence consecutive backwardation closes
      - current='SHY': switch to SPY after reentry_persistence consecutive contango closes
    """
    threshold  = params["ratio_threshold"]
    exit_pers  = params["exit_persistence"]
    re_pers    = params["reentry_persistence"]

    ratio = vix_close / vix3m_close

    regime = pd.Series("SPY", index=vix_close.index, dtype=object)
    current     = "SPY"
    consec_back = 0
    consec_cont = 0

    for date in vix_close.index:
        r = ratio.loc[date]
        if pd.isna(r):
            regime.loc[date] = current
            continue

        is_back = bool(r > threshold)

        if is_back:
            consec_back += 1
            consec_cont  = 0
        else:
            consec_cont  += 1
            consec_back   = 0

        if current == "SPY" and consec_back >= exit_pers:
            current = "SHY"
        elif current == "SHY" and consec_cont >= re_pers:
            current = "SPY"

        regime.loc[date] = current

    n_spy = int((regime == "SPY").sum())
    n_shy = int((regime == "SHY").sum())
    logger.info("Signals: %d SPY days / %d SHY days", n_spy, n_shy)
    return regime


# ── Transaction costs ─────────────────────────────────────────────────────────

def _compute_leg_cost(price: float, sigma: float, adv: float, params: dict) -> tuple:
    Q     = params["order_qty"]
    fixed = params["fixed_cost_per_share"]
    slip  = params["slippage_pct"] * price
    if adv > 0 and not np.isnan(adv):
        q_ratio = Q / adv
        lc      = q_ratio > params["liquidity_threshold"]
        mi      = params["market_impact_k"] * sigma * np.sqrt(q_ratio)
    else:
        lc, mi = False, 0.0
    return fixed + slip + mi, lc


def apply_transaction_costs(
    regime: pd.Series, spy_df: pd.DataFrame, shy_df: pd.DataFrame, params: dict
) -> pd.DataFrame:
    spy_close = spy_df["Close"]
    shy_close = shy_df["Close"].reindex(regime.index)

    spy_vol = (spy_df["Volume"] if "Volume" in spy_df.columns
               else pd.Series(np.nan, index=spy_df.index))
    shy_vol = (shy_df["Volume"] if "Volume" in shy_df.columns
               else pd.Series(np.nan, index=shy_df.index)).reindex(regime.index)

    spy_sigma = spy_close.pct_change().rolling(params["sigma_window"]).std()
    shy_sigma = shy_close.pct_change().rolling(params["sigma_window"]).std()
    spy_adv   = spy_vol.rolling(params["adv_window"]).mean()
    shy_adv   = shy_vol.rolling(params["adv_window"]).mean().reindex(regime.index)

    def _psa(asset, date):
        if asset == "SPY":
            p = spy_close.loc[date] if date in spy_close.index else np.nan
            s = spy_sigma.loc[date] if date in spy_sigma.index else np.nan
            a = spy_adv.loc[date]   if date in spy_adv.index   else np.nan
        else:
            p = shy_close.loc[date] if date in shy_close.index else np.nan
            s = shy_sigma.loc[date] if date in shy_sigma.index else np.nan
            a = shy_adv.loc[date]   if date in shy_adv.index   else np.nan
        return (
            float(p) if not pd.isna(p) else np.nan,
            float(s) if not pd.isna(s) else 0.0,
            float(a) if not pd.isna(a) else 0.0,
        )

    trade_log   = []
    prev_regime = None

    for date in regime.index:
        curr = regime.loc[date]
        if prev_regime is not None and curr != prev_regime:
            sell_p, sell_s, sell_a = _psa(prev_regime, date)
            buy_p,  buy_s,  buy_a  = _psa(curr, date)

            c_out, lc_out = (
                _compute_leg_cost(sell_p, sell_s, sell_a, params)
                if not np.isnan(sell_p) else (0.0, False)
            )
            c_in, lc_in = (
                _compute_leg_cost(buy_p, buy_s, buy_a, params)
                if not np.isnan(buy_p) else (0.0, False)
            )

            total_cost_pct = (
                (c_out + c_in) / max(sell_p, 1e-6)
                if not np.isnan(sell_p) else 0.0
            )

            if lc_out or lc_in:
                logger.warning("LIQUIDITY_CONSTRAINED %s %s→%s", date.date(), prev_regime, curr)

            trade_log.append({
                "transition_date":    date,
                "from_asset":         prev_regime,
                "to_asset":           curr,
                "price_out":          sell_p,
                "price_in":           buy_p,
                "cost_per_share_out": c_out,
                "cost_per_share_in":  c_in,
                "lc_out":             lc_out,
                "lc_in":              lc_in,
                "total_cost_pct":     total_cost_pct,
            })
        prev_regime = curr

    return pd.DataFrame(trade_log)


# ── Equity curve ──────────────────────────────────────────────────────────────

def build_equity_curve(
    regime: pd.Series,
    spy_df: pd.DataFrame,
    shy_df: pd.DataFrame,
    trade_log: pd.DataFrame,
    params: dict,
) -> tuple:
    """
    Daily equity curve. Yesterday's regime (shift(1)) drives today's gross return.
    Transaction costs subtracted on transition days.
    """
    spy_ret = spy_df["Close"].pct_change().reindex(regime.index).fillna(0.0)
    shy_ret = shy_df["Close"].reindex(regime.index).pct_change().fillna(0.0)

    prev_regime = regime.shift(1)

    daily_gross = pd.Series(0.0, index=regime.index)
    for date in regime.index:
        pr = prev_regime.loc[date]
        if pd.isna(pr):
            continue
        daily_gross.loc[date] = spy_ret.loc[date] if pr == "SPY" else shy_ret.loc[date]

    cost_series = pd.Series(0.0, index=regime.index)
    if not trade_log.empty:
        for _, row in trade_log.iterrows():
            td = row["transition_date"]
            if td in cost_series.index:
                p_out = row.get("price_out", float("nan"))
                if not (isinstance(p_out, float) and np.isnan(p_out)) and p_out > 0:
                    cost_series.loc[td] -= row["total_cost_pct"]

    net_returns  = daily_gross + cost_series
    equity_curve = params["init_cash"] * (1.0 + net_returns).cumprod()
    return equity_curve, net_returns


# ── Period (regime-block) trade stats ────────────────────────────────────────

def _period_trade_stats(
    regime: pd.Series,
    spy_prices: pd.Series,
    shy_prices: pd.Series,
    net_returns: pd.Series,
) -> pd.DataFrame:
    """
    One row per contiguous regime block. Win = held asset outperformed the alternative.
    Trade count = number of blocks (both SPY and SHY periods count as trades).
    """
    rows  = []
    dates = regime.index
    i     = 0

    while i < len(dates):
        asset = regime.iloc[i]
        j = i
        while j < len(dates) and regime.iloc[j] == asset:
            j += 1

        period_dates = dates[i:j]
        if len(period_dates) < 1:
            i = j
            continue

        entry = period_dates[0]
        exit_ = period_dates[-1]

        if len(period_dates) > 1:
            spy_ret = float(spy_prices.loc[exit_] / spy_prices.loc[entry] - 1)
            shy_ret = float(shy_prices.loc[exit_] / shy_prices.loc[entry] - 1)
        else:
            spy_ret = 0.0
            shy_ret = 0.0

        period_net = float((1 + net_returns.loc[period_dates]).prod() - 1)
        win = bool(spy_ret > shy_ret if asset == "SPY" else shy_ret > spy_ret)

        rows.append({
            "entry_date":  entry,
            "exit_date":   exit_,
            "asset_held":  asset,
            "days_held":   len(period_dates),
            "spy_return":  spy_ret,
            "shy_return":  shy_ret,
            "net_return":  period_net,
            "win":         win,
        })
        i = j

    return pd.DataFrame(rows)


# ── Core backtest ─────────────────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """Full H50 backtest pipeline for a given date window."""
    if params is None:
        params = DEFAULT_PARAMS.copy()

    ts_start = pd.Timestamp(start)
    ts_end   = pd.Timestamp(end)

    vix_df, vix3m_df, spy_df, shy_df = load_data(start, end)
    regime_full = generate_signals(vix_df["Close"], vix3m_df["Close"], params)

    mask   = (spy_df.index >= ts_start) & (spy_df.index <= ts_end)
    spy_w  = spy_df.loc[mask].copy()
    shy_w  = shy_df.loc[mask].copy()
    regime = regime_full.loc[mask].copy()

    if len(spy_w) < 20:
        raise ValueError(f"Insufficient data after trim to {start}–{end}: {len(spy_w)} bars")

    trade_log    = apply_transaction_costs(regime, spy_w, shy_w, params)
    equity_curve, net_returns = build_equity_curve(regime, spy_w, shy_w, trade_log, params)
    period_df    = _period_trade_stats(regime, spy_w["Close"], shy_w["Close"], net_returns)

    ret_arr = net_returns.values
    sharpe  = 0.0
    if len(ret_arr) > 1 and ret_arr.std() > 1e-12:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum      = np.cumprod(1 + ret_arr)
    roll_max = np.maximum.accumulate(cum)
    mdd      = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)

    total_return = round(float(cum[-1] - 1.0), 4)
    years        = max((ts_end - ts_start).days / 365.25, 1e-3)
    ann_return   = round(float((1.0 + total_return) ** (1.0 / years) - 1.0), 4)
    ann_vol      = round(float(ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    trade_count  = len(period_df)
    win_rate     = round(float(period_df["win"].mean()), 4) if trade_count > 0 else 0.0

    wins   = period_df.loc[period_df["net_return"] > 0, "net_return"]
    losses = period_df.loc[period_df["net_return"] < 0, "net_return"].abs()
    profit_factor = (round(float(wins.sum() / losses.sum()), 4)
                     if losses.sum() > 1e-12 else float("inf"))
    avg_pnl_bps   = (round(float(period_df["net_return"].mean() * 10000), 2)
                     if trade_count > 0 else 0.0)

    n_transitions   = len(trade_log)
    regime_pct_spy  = round(float((regime == "SPY").mean()), 4)

    gap_flags = {
        "vix":   _check_data_gaps(vix_df["Close"],   "VIX"),
        "vix3m": _check_data_gaps(vix3m_df["Close"], "VIX3M"),
        "spy":   _check_data_gaps(spy_df["Close"],   "SPY"),
        "shy":   _check_data_gaps(shy_df["Close"],   "SHY"),
    }

    return {
        "sharpe":          sharpe,
        "mdd":             mdd,
        "max_drawdown":    mdd,
        "total_return":    total_return,
        "ann_return":      ann_return,
        "ann_vol":         ann_vol,
        "win_rate":        win_rate,
        "profit_factor":   profit_factor,
        "trade_count":     trade_count,
        "avg_pnl_bps":     avg_pnl_bps,
        "trades_per_year": round(trade_count / years, 1),
        "n_transitions":   n_transitions,
        "regime_pct":      regime_pct_spy,
        "returns":         net_returns,
        "equity":          equity_curve,
        "trades":          period_df,
        "trade_log":       trade_log,
        "regime":          regime,
        "data_quality":    gap_flags,
    }


# ── Gate 1 v2.0 entry point ───────────────────────────────────────────────────

def run_strategy(params: dict = None) -> dict:
    """
    Full Gate 1 v2.0 pipeline for H50.
    Returns dict compatible with backtests/h50_vix_contango_equity_timer/run_h50_gate1.py.
    """
    if params is None:
        p = DEFAULT_PARAMS.copy()
    else:
        p = DEFAULT_PARAMS.copy()
        p.update(params)

    logger.info("=== H50 IS run  (%s → %s) ===", IS_START, IS_END)
    is_r = run_backtest(IS_START, IS_END, p)

    logger.info("=== H50 OOS run (%s → %s) ===", OOS_START, OOS_END)
    oos_r = run_backtest(OOS_START, OOS_END, p)

    def _metrics(r):
        return {
            "sharpe":        r["sharpe"],
            "mdd":           r["mdd"],
            "total_return":  r["total_return"],
            "ann_return":    r["ann_return"],
            "ann_vol":       r["ann_vol"],
            "win_rate":      r["win_rate"],
            "profit_factor": r["profit_factor"],
            "trade_count":   r["trade_count"],
        }

    is_m  = _metrics(is_r)
    oos_m = _metrics(oos_r)

    # ── Walk-forward (6 non-overlapping IS sub-windows) ────────────────────────
    wf_list = []
    for label, wf_start, wf_end in WALK_FORWARD_WINDOWS:
        wf_r = run_backtest(wf_start, wf_end, p)
        w_pass = wf_r["sharpe"] >= WF_SHARPE_FLOOR
        wf_list.append({
            "window":   label,
            "sharpe":   wf_r["sharpe"],
            "mdd":      wf_r["mdd"],
            "win_rate": wf_r["win_rate"],
            "trades":   wf_r["trade_count"],
            "pass":     w_pass,
        })
    wf_pass_count = sum(1 for w in wf_list if w["pass"])

    # ── Parameter sensitivity (IS window) ──────────────────────────────────────
    base_sharpe = is_r["sharpe"]
    sens_list   = []
    for variant_label, overrides in SENSITIVITY_GRID:
        p_var = p.copy()
        p_var.update(overrides)
        var_r = run_backtest(IS_START, IS_END, p_var)
        if abs(base_sharpe) > 1e-8:
            delta_pct = round(
                (var_r["sharpe"] - base_sharpe) / abs(base_sharpe) * 100, 1
            )
        else:
            delta_pct = None
        sens_list.append({
            "variant":   variant_label,
            "sharpe":    var_r["sharpe"],
            "trades":    var_r["trade_count"],
            "delta_pct": delta_pct,
        })

    max_red_pct = max(
        (abs(s["delta_pct"]) for s in sens_list
         if s["delta_pct"] is not None and s["delta_pct"] < 0),
        default=0.0,
    )

    # ── Gate criteria ──────────────────────────────────────────────────────────
    gate_criteria = {
        "IS Sharpe > 1.0":        {"value": is_m["sharpe"],     "threshold": 1.0,   "pass": is_m["sharpe"] > 1.0},
        "OOS Sharpe > 0.7":       {"value": oos_m["sharpe"],    "threshold": 0.7,   "pass": oos_m["sharpe"] > 0.7},
        "IS MDD > -30%":          {"value": is_m["mdd"],        "threshold": -0.30, "pass": is_m["mdd"] > -0.30},
        "IS Trade Count >= 120":  {"value": is_m["trade_count"], "threshold": 120,  "pass": is_m["trade_count"] >= 120},
        "WF Stability >= 4/6":    {"value": wf_pass_count,      "threshold": 4,     "pass": wf_pass_count >= 4},
        "Param Sensitivity < 50%": {"value": max_red_pct,       "threshold": 50.0,  "pass": max_red_pct < 50.0},
        "IS Win Rate > 50%":      {"value": is_m["win_rate"],   "threshold": 0.50,  "pass": is_m["win_rate"] > 0.50},
    }

    pass_count = sum(1 for g in gate_criteria.values() if g["pass"])
    verdict    = "PASS" if pass_count == 7 else "FAIL"

    return {
        "strategy":      "H50 VIX Contango/Backwardation Equity Timer",
        "params":        p,
        "is_metrics":    is_m,
        "oos_metrics":   oos_m,
        "walk_forward":  wf_list,
        "sensitivity":   sens_list,
        "gate_criteria": gate_criteria,
        "pass_count":    pass_count,
        "verdict":       verdict,
        "is_trade_log":  is_r["trades"],
        "oos_trade_log": oos_r["trades"],
    }


if __name__ == "__main__":
    result = run_strategy()
    m   = result["is_metrics"]
    om  = result["oos_metrics"]
    wf  = result["walk_forward"]

    print(f"\n{'='*65}")
    print(f"  H50 VIX Contango/Backwardation Equity Timer — Gate 1 v2.0")
    print(f"{'='*65}")
    print(f"  Verdict: {result['verdict']} ({result['pass_count']}/7 criteria)")
    print(f"\n  IS  ({IS_START} → {IS_END})")
    print(f"    Sharpe      : {m['sharpe']:.4f}")
    print(f"    MDD         : {m['mdd']:.2%}")
    print(f"    Total return: {m['total_return']:.2%}")
    print(f"    Win rate    : {m['win_rate']:.2%}")
    print(f"    Trade count : {m['trade_count']}")
    print(f"\n  OOS ({OOS_START} → {OOS_END})")
    print(f"    Sharpe      : {om['sharpe']:.4f}")
    print(f"    MDD         : {om['mdd']:.2%}")
    print(f"    Total return: {om['total_return']:.2%}")
    print(f"    Win rate    : {om['win_rate']:.2%}")
    print(f"    Trade count : {om['trade_count']}")
    print(f"\n  Walk-Forward:")
    for w in wf:
        icon = "PASS" if w["pass"] else "FAIL"
        print(f"    [{icon}] {w['window']}: Sharpe={w['sharpe']:.3f}  trades={w['trades']}")
    print(f"{'='*65}")
