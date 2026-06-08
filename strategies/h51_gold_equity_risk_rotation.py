"""
Strategy: H51 Gold/Equity Relative Momentum Risk Timer — GLD/SPY Monthly Rotation
Author: Strategy Coder Agent
Date: 2026-06-08
Hypothesis: research/hypotheses/51_qc_gold_equity_risk_rotation.md
Parent task: QUA-113

Signal: GLD 20-day return vs SPY 20-day return, checked on last trading day of each month.
  - GLD outperforms SPY (relative_signal > threshold) → rotate to SHY (risk-off)
  - SPY outperforms GLD (relative_signal <= threshold) → hold SPY (risk-on)
Trade count: each calendar month = 1 trade (consistent with hypothesis PF-1 calculation).
IS window:  2005-01-01 to 2021-12-31 (GLD inception Nov 2004; 60-day warmup for first signal)
OOS window: 2022-01-01 to 2024-12-31

Data quality checklist:
  - Survivorship bias: NOT APPLICABLE — SPY, GLD, SHY are all current active ETFs.
  - Price adjustments: auto_adjust=True via yfinance (splits + dividends).
  - GLD inception: 2004-11-18 — limits IS start to January 2005.
  - Data gaps: checked at runtime via _check_data_gaps().
  - Earnings exclusion: NOT APPLICABLE — ETF rotation; no individual equity earnings exposure.
  - Delisted tickers: NOT APPLICABLE — SPY (1993), GLD (2004), SHY (2002) all active.
"""

import logging

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PARAMETERS = {
    # Signal parameters
    "lookback_days": 20,
    "safe_harbor_asset": "SHY",
    "signal_threshold": 0.0,   # GLD must beat SPY by > threshold; 0 = strict outperformance
    "ma_filter": False,        # if True, re-enter SPY only when price >= 200-day MA
    "ma_window": 200,

    # Transaction cost model (Engineering Director standard — equities/ETFs)
    "fixed_cost_per_share": 0.005,
    "slippage_pct": 0.0005,
    "market_impact_k": 0.1,
    "sigma_window": 20,
    "adv_window": 20,
    "order_qty": 100,
    "liquidity_threshold": 0.01,

    # Portfolio
    "init_cash": 25000.0,
}

DATA_QUALITY = {
    "survivorship_bias": (
        "not_applicable — SPY, GLD, SHY are all current active ETFs with no delisting risk. "
        "GLD inception Nov 2004 constrains IS start to Jan 2005."
    ),
    "price_adjustments": "auto_adjust=True via yfinance for SPY, GLD, SHY",
    "earnings_exclusion": (
        "not_applicable — ETF rotation strategy. Monthly hold periods make "
        "individual earnings events irrelevant."
    ),
    "delisted_tickers": (
        "not_applicable — SPY (inception 1993), GLD (Nov 2004), SHY (2002) all currently active."
    ),
    "data_gaps": "pending — checked at runtime",
    "is_window": "2005-01-01 to 2021-12-31",
    "oos_window": "2022-01-01 to 2024-12-31",
}

_GLD_START = "2004-11-18"
_SHY_START = "2002-07-22"
_SPY_START = "1993-01-29"
TRADING_DAYS_PER_YEAR = 252


# ── Data loading ──────────────────────────────────────────────────────────────────

def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
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
    missing_series = pd.Series(missing)
    runs, run = [], 1
    for i in range(1, len(missing_series)):
        if (missing_series.iloc[i] - missing_series.iloc[i - 1]).days == 1:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)
    max_run = max(runs) if runs else 0
    if max_run > 5:
        logger.warning("WARNING: %s consecutive missing weekday run of %d days", label, max_run)
        return f"flagged: max_consecutive_missing={max_run}"
    return f"ok: max_consecutive_missing={max_run} (<=5)"


def load_data(start: str = "2005-01-01", end: str = "2024-12-31"):
    """
    Download SPY, GLD, SHY with 60-day warmup before `start` for signal initialization.
    Returns (spy_df, gld_df, shy_df) aligned to common trading days (warmup + backtest range).
    """
    warmup_start = (pd.Timestamp(start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")

    spy_start = max(pd.Timestamp(warmup_start), pd.Timestamp(_SPY_START)).strftime("%Y-%m-%d")
    gld_start = max(pd.Timestamp(warmup_start), pd.Timestamp(_GLD_START)).strftime("%Y-%m-%d")
    shy_start = max(pd.Timestamp(warmup_start), pd.Timestamp(_SHY_START)).strftime("%Y-%m-%d")

    logger.info("Downloading SPY [%s → %s]", spy_start, end)
    spy_df = _download("SPY", spy_start, end)

    logger.info("Downloading GLD [%s → %s]", gld_start, end)
    gld_df = _download("GLD", gld_start, end)

    logger.info("Downloading SHY [%s → %s]", shy_start, end)
    shy_df = _download("SHY", shy_start, end)

    common_index = spy_df.index.intersection(gld_df.index).intersection(shy_df.index)
    if len(common_index) == 0:
        raise ValueError("No overlapping trading days for SPY / GLD / SHY")

    spy_df = spy_df.reindex(common_index)
    gld_df = gld_df.reindex(common_index)
    shy_df = shy_df.reindex(common_index)

    DATA_QUALITY["data_gaps_spy"] = _check_data_gaps(spy_df["Close"], "SPY")
    DATA_QUALITY["data_gaps_gld"] = _check_data_gaps(gld_df["Close"], "GLD")
    DATA_QUALITY["data_gaps_shy"] = _check_data_gaps(shy_df["Close"], "SHY")
    DATA_QUALITY["data_gaps"] = "checked — see per-ticker gap entries"

    logger.info("Common index: %d days [%s → %s]",
                len(common_index), common_index[0].date(), common_index[-1].date())
    return spy_df, gld_df, shy_df


# ── Helpers ───────────────────────────────────────────────────────────────────────

def _last_trading_days_of_month(index: pd.DatetimeIndex) -> set:
    """Return set of dates that are the last trading day of their calendar month."""
    result = set()
    for i in range(len(index)):
        is_last = (
            i + 1 >= len(index)
            or (index[i + 1].year, index[i + 1].month) != (index[i].year, index[i].month)
        )
        if is_last:
            result.add(index[i])
    return result


# ── Signal generation ─────────────────────────────────────────────────────────────

def generate_signals(
    spy_prices: pd.Series,
    gld_prices: pd.Series,
    params: dict = PARAMETERS,
) -> pd.Series:
    """
    Build daily regime Series: 'SPY' or safe_harbor_asset (default 'SHY').

    Signal logic (no look-ahead):
      At each month-end close T, compute:
        relative_signal = gld_20d_return - spy_20d_return
      Uses only data through close T (current close is known at execution time).
      New regime takes effect starting day T (same-close execution — institutional month-end).
      In build_equity_curve, shift(1) ensures day T's return still comes from old regime.

    Returns:
        pd.Series[str]: daily regime indexed to spy_prices.index
    """
    lookback = params["lookback_days"]
    threshold = params["signal_threshold"]
    safe_harbor = params["safe_harbor_asset"]
    use_ma = params["ma_filter"]
    ma_window = params["ma_window"]

    spy_ret20 = spy_prices.pct_change(lookback)
    gld_ret20 = gld_prices.pct_change(lookback)
    relative = gld_ret20 - spy_ret20

    ma200 = spy_prices.rolling(ma_window).mean() if use_ma else None

    month_end_set = _last_trading_days_of_month(spy_prices.index)

    regime = pd.Series("SPY", index=spy_prices.index, dtype=object)
    current = "SPY"

    for date in spy_prices.index:
        if date in month_end_set:
            rel = relative.loc[date]
            if not pd.isna(rel):
                if rel > threshold:
                    current = safe_harbor
                else:
                    if use_ma and ma200 is not None and not pd.isna(ma200.loc[date]):
                        current = "SPY" if spy_prices.loc[date] >= ma200.loc[date] else safe_harbor
                    else:
                        current = "SPY"
        regime.loc[date] = current

    n_safe = (regime != "SPY").sum()
    n_spy = (regime == "SPY").sum()
    logger.info("Signals: %d SPY days / %d %s days", n_spy, n_safe, safe_harbor)
    return regime


# ── Transaction costs ─────────────────────────────────────────────────────────────

def _compute_leg_cost(price: float, sigma: float, adv: float, params: dict) -> tuple:
    """Per-share cost = fixed + slippage + market impact (Almgren-Chriss square-root model)."""
    Q = params["order_qty"]
    fixed = params["fixed_cost_per_share"]
    slip = params["slippage_pct"] * price
    if adv > 0 and not np.isnan(adv):
        q_ratio = Q / adv
        lc = q_ratio > params["liquidity_threshold"]
        mi = params["market_impact_k"] * sigma * np.sqrt(q_ratio)
    else:
        lc, mi = False, 0.0
    return fixed + slip + mi, lc


def apply_transaction_costs(
    regime: pd.Series,
    spy_df: pd.DataFrame,
    shy_df: pd.DataFrame,
    params: dict,
) -> pd.DataFrame:
    """
    Build trade log for every SPY↔safe_harbor regime transition.
    Returns DataFrame with per-transition cost details.
    """
    spy_close = spy_df["Close"]
    spy_vol = spy_df.get("Volume", pd.Series(np.nan, index=spy_df.index))
    shy_close = shy_df["Close"].reindex(regime.index)
    shy_vol = shy_df.get("Volume", pd.Series(np.nan, index=shy_df.index)).reindex(regime.index)

    spy_sigma = spy_close.pct_change().rolling(params["sigma_window"]).std().reindex(regime.index)
    shy_sigma = shy_close.pct_change().rolling(params["sigma_window"]).std()
    spy_adv = spy_vol.rolling(params["adv_window"]).mean().reindex(regime.index)
    shy_adv = shy_vol.rolling(params["adv_window"]).mean().reindex(regime.index)

    def _psa(asset, date):
        if asset == "SPY":
            p = spy_close.get(date, np.nan)
            s = spy_sigma.get(date, np.nan)
            a = spy_adv.get(date, np.nan)
        else:
            p = shy_close.get(date, np.nan)
            s = shy_sigma.get(date, np.nan)
            a = shy_adv.get(date, np.nan)
        return (
            float(p) if not pd.isna(p) else np.nan,
            float(s) if not pd.isna(s) else 0.0,
            float(a) if not pd.isna(a) else 0.0,
        )

    trade_log = []
    prev_regime = None

    for date in regime.index:
        curr = regime.loc[date]
        if prev_regime is not None and curr != prev_regime:
            sell_price, sell_sigma, sell_adv = _psa(prev_regime, date)
            buy_price, buy_sigma, buy_adv = _psa(curr, date)

            cost_out, lc_out = (
                _compute_leg_cost(sell_price, sell_sigma, sell_adv, params)
                if not np.isnan(sell_price) else (0.0, False)
            )
            cost_in, lc_in = (
                _compute_leg_cost(buy_price, buy_sigma, buy_adv, params)
                if not np.isnan(buy_price) else (0.0, False)
            )

            if lc_out or lc_in:
                logger.warning("LIQUIDITY_CONSTRAINED %s %s→%s", date.date(), prev_regime, curr)

            total_cost_pct = (
                (cost_out + cost_in) / max(sell_price, 1e-6)
                if not np.isnan(sell_price) else 0.0
            )

            trade_log.append({
                "transition_date": date,
                "from_asset": prev_regime,
                "to_asset": curr,
                "price_out": sell_price,
                "price_in": buy_price,
                "cost_per_share_out": cost_out,
                "cost_per_share_in": cost_in,
                "lc_out": lc_out,
                "lc_in": lc_in,
                "total_cost_pct": total_cost_pct,
            })
            logger.info("TRANSITION %s: %s→%s | cost_out=%.5f cost_in=%.5f",
                        date.date(), prev_regime, curr, cost_out, cost_in)
        prev_regime = curr

    return pd.DataFrame(trade_log)


# ── Equity curve ──────────────────────────────────────────────────────────────────

def build_equity_curve(
    regime: pd.Series,
    spy_df: pd.DataFrame,
    shy_df: pd.DataFrame,
    trade_log: pd.DataFrame,
    params: dict,
) -> tuple:
    """
    Construct daily equity curve.
    Yesterday's regime (shift(1)) drives today's gross return — no look-ahead.
    Transaction costs subtracted on transition days.

    Returns:
        (equity_curve, daily_net_returns) as pd.Series
    """
    spy_ret = spy_df["Close"].pct_change().reindex(regime.index).fillna(0.0)
    shy_ret = shy_df["Close"].reindex(regime.index).pct_change().fillna(0.0)

    prev_regime = regime.shift(1)

    daily_gross = pd.Series(0.0, index=regime.index)
    for date in regime.index:
        pr = prev_regime.loc[date]
        if pd.isna(pr):
            continue
        if pr == "SPY":
            daily_gross.loc[date] = spy_ret.loc[date]
        else:
            daily_gross.loc[date] = shy_ret.loc[date]

    cost_series = pd.Series(0.0, index=regime.index)
    if not trade_log.empty:
        for _, row in trade_log.iterrows():
            td = row["transition_date"]
            if td in cost_series.index and not np.isnan(row["price_out"]) and row["price_out"] > 0:
                cost_series.loc[td] -= row["total_cost_pct"]

    net_returns = daily_gross + cost_series
    equity_curve = params["init_cash"] * (1.0 + net_returns).cumprod()
    return equity_curve, net_returns


# ── Monthly trade analysis ────────────────────────────────────────────────────────

def _monthly_trade_stats(
    regime: pd.Series,
    spy_prices: pd.Series,
    shy_prices: pd.Series,
    net_returns: pd.Series,
) -> pd.DataFrame:
    """
    One row per calendar month: asset held, SPY/SHY return, net portfolio return, win flag.
    Win = chosen asset outperformed the unchosen asset for that month.
    Trade count definition: each month = 1 trade (consistent with PF-1: 12/yr × years).
    """
    rows = []
    years_months = sorted(set(zip(regime.index.year, regime.index.month)))

    for yr, mo in years_months:
        mask = (regime.index.year == yr) & (regime.index.month == mo)
        dates = regime.index[mask]
        if len(dates) < 5:
            continue

        asset_held = regime.loc[dates].mode().iloc[0]

        spy_mo_ret = spy_prices.loc[dates[-1]] / spy_prices.loc[dates[0]] - 1
        shy_mo_ret = shy_prices.loc[dates[-1]] / shy_prices.loc[dates[0]] - 1
        monthly_net = float((1 + net_returns.loc[dates]).prod() - 1)

        win = bool(spy_mo_ret > shy_mo_ret if asset_held == "SPY" else shy_mo_ret > spy_mo_ret)

        rows.append({
            "year": yr,
            "month": mo,
            "asset_held": asset_held,
            "spy_return": float(spy_mo_ret),
            "shy_return": float(shy_mo_ret),
            "net_return": monthly_net,
            "win": win,
        })

    return pd.DataFrame(rows)


# ── Main backtest entry point ──────────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Full H51 backtest pipeline. Returns Gate 1 v2.0 compatible result dict.

    Parameters
    ----------
    start : str  Start date YYYY-MM-DD. IS: '2005-01-01'.
    end : str    End date YYYY-MM-DD. IS: '2021-12-31'.
    params : dict  Override PARAMETERS (default None = use PARAMETERS).
    """
    if params is None:
        params = PARAMETERS.copy()

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # Load with warmup; generate signals on warmup-inclusive data; trim to window
    spy_df, gld_df, shy_df = load_data(start=start, end=end)
    regime_full = generate_signals(spy_df["Close"], gld_df["Close"], params)

    mask = (spy_df.index >= ts_start) & (spy_df.index <= ts_end)
    spy_df = spy_df.loc[mask].copy()
    gld_df = gld_df.loc[mask].copy()
    shy_df = shy_df.loc[mask].copy()
    regime = regime_full.loc[mask].copy()

    if len(spy_df) < 20:
        raise ValueError(f"Insufficient data after trim to {start}–{end}: {len(spy_df)} bars")

    trade_log = apply_transaction_costs(regime, spy_df, shy_df, params)
    equity_curve, net_returns = build_equity_curve(regime, spy_df, shy_df, trade_log, params)
    monthly_df = _monthly_trade_stats(regime, spy_df["Close"], shy_df["Close"], net_returns)

    # Annualized metrics
    ret_arr = net_returns.values
    sharpe = 0.0
    if len(ret_arr) > 1 and ret_arr.std() > 0:
        sharpe = round(float(ret_arr.mean() / ret_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + ret_arr)
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)

    trade_count = len(monthly_df)
    years = max((ts_end - ts_start).days / 365.25, 1e-3)
    win_rate = round(float(monthly_df["win"].mean()), 4) if trade_count > 0 else 0.0

    wins = monthly_df.loc[monthly_df["net_return"] > 0, "net_return"]
    losses = monthly_df.loc[monthly_df["net_return"] < 0, "net_return"].abs()
    profit_factor = round(float(wins.sum() / losses.sum()), 4) if losses.sum() > 0 else float("inf")
    avg_pnl_bps = round(float(monthly_df["net_return"].mean() * 10000), 2) if trade_count > 0 else 0.0

    regime_pct = round(float((regime == "SPY").mean()), 4)
    risk_off_months = int((monthly_df["asset_held"] != "SPY").sum())
    risk_on_months = int((monthly_df["asset_held"] == "SPY").sum())
    n_transitions = len(trade_log)
    transitions_per_year = round(n_transitions / years, 1)
    total_cost_pct = round(float(trade_log["total_cost_pct"].sum()), 6) if not trade_log.empty else 0.0

    lc_count = (
        int(trade_log["lc_out"].sum() + trade_log["lc_in"].sum())
        if not trade_log.empty else 0
    )
    if lc_count > 0:
        logger.warning("Liquidity-constrained transitions: %d", lc_count)

    return {
        # Gate 1 standard
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "total_return": total_return,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": trade_count,
        "avg_pnl_bps": avg_pnl_bps,
        "trades_per_year": round(trade_count / years, 1),
        "returns": net_returns,
        "equity": equity_curve,
        "trades": monthly_df,
        "trade_log": trade_log,
        "regime": regime,
        "data_quality": {
            "survivorship_bias_flag": DATA_QUALITY["survivorship_bias"],
            "price_adjusted": True,
            "auto_adjust": True,
            "earnings_exclusion": DATA_QUALITY["earnings_exclusion"],
            "delisted_tickers": DATA_QUALITY["delisted_tickers"],
            "gap_flags": {
                "spy": DATA_QUALITY.get("data_gaps_spy", "pending"),
                "gld": DATA_QUALITY.get("data_gaps_gld", "pending"),
                "shy": DATA_QUALITY.get("data_gaps_shy", "pending"),
            },
        },
        # H51-specific
        "regime_pct": regime_pct,
        "risk_off_months": risk_off_months,
        "risk_on_months": risk_on_months,
        "n_transitions": n_transitions,
        "transitions_per_year": transitions_per_year,
        "total_cost_pct": total_cost_pct,
        "liquidity_constrained_legs": lc_count,
    }


def run_is_oos(params: dict = PARAMETERS) -> dict:
    logger.info("=== IS run (2005-01-01 → 2021-12-31) ===")
    is_result = run_backtest("2005-01-01", "2021-12-31", params=params)
    logger.info("=== OOS run (2022-01-01 → 2024-12-31) ===")
    oos_result = run_backtest("2022-01-01", "2024-12-31", params=params)
    return {"is": is_result, "oos": oos_result}


if __name__ == "__main__":
    import json

    result = run_is_oos()
    for window, res in result.items():
        print(f"\n{'='*60}")
        print(f"  {window.upper()} RESULTS")
        print(f"{'='*60}")
        print(f"  Sharpe         : {res['sharpe']:.4f}")
        print(f"  Max drawdown   : {res['max_drawdown']:.2%}")
        print(f"  Total return   : {res['total_return']:.2%}")
        print(f"  Win rate       : {res['win_rate']:.2%}")
        print(f"  Profit factor  : {res['profit_factor']:.2f}")
        print(f"  Trade count    : {res['trade_count']} ({res['trades_per_year']:.1f}/yr)")
        print(f"  Avg PnL        : {res['avg_pnl_bps']:.1f} bps/month")
        print(f"  Regime (SPY)   : {res['regime_pct']:.1%} of days")
        print(f"  Risk-off months: {res['risk_off_months']}")
        print(f"  Risk-on months : {res['risk_on_months']}")
        print(f"  Transitions/yr : {res['transitions_per_year']}")
        print(f"  Total cost drag: {res['total_cost_pct']:.4%}")
