"""
Strategy: H40 Halloween Effect — Seasonal Equity/Bond Switch
Author: Strategy Coder Agent
Date: 2026-03-17
Hypothesis: Equity returns in the November–April "winter half" significantly exceed
            returns in the May–October "summer half" (Bouman & Jacobsen 2002).
            Buy ^GSPC/SPY on last trading day of October; exit to cash on last
            trading day of April. Circuit breaker exits at 15% peak-to-trough.
Asset class: equities (US, ^GSPC index proxy + SPY ETF)
Parent task: QUA-321
References: Bouman & Jacobsen (2002) AER; Jacobsen & Zhang (2014) SSRN;
            Andrade, Chhaochharia & Fuerst (2013) FAJ;
            research/hypotheses/40_qc_halloween_seasonal_switch.md
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ── Logging ──────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Parameters ───────────────────────────────────────────────────────────────────
PARAMETERS = {
    # Signal windows
    "winter_entry_month": 10,           # October (primary); test 9=Sep, 11=Nov as variants
    "winter_exit_month": 4,             # April (primary); test 3=Mar, 5=May as variants
    # Summer allocation
    "summer_allocation": "cash",        # "cash" (primary) | "agg" | "shy"
    # Circuit breaker
    "circuit_breaker_drawdown": 0.15,   # 15% peak-to-trough (primary); test 0.10, 0.20
    # Transaction cost model (Engineering Director standard)
    "fixed_cost_per_share": 0.005,      # $0.005/share fixed
    "slippage_pct": 0.0005,             # 0.05% slippage
    "market_impact_k": 0.1,             # square-root impact coefficient (Johnson 2010)
    "sigma_window": 20,                 # rolling vol window for market impact
    "adv_window": 20,                   # rolling ADV window
    "order_qty": 100,                   # default order size in shares
    "liquidity_threshold": 0.01,        # Q/ADV ratio flag threshold
    # Portfolio
    "init_cash": 25000.0,
}

# Data quality checklist (assessed at module level; updated dynamically in load_stitched_data)
DATA_QUALITY = {
    "survivorship_bias": "not_applicable",    # single ticker (^GSPC/SPY) — no universe
    "price_adjustments": "auto_adjust=True for both ^GSPC and SPY via yfinance",
    "data_gaps": "pending",                   # checked at runtime in load_stitched_data
    "earnings_exclusion": "not_applicable",   # SPY/^GSPC, no earnings effect
    "delisted_tickers": "not_applicable",     # ^GSPC and SPY are both active
}

# Stitch constants
_GSPC_END = "1993-01-28"       # last day of ^GSPC-only period (day before SPY inception)
_SPY_START = "1993-01-29"      # SPY inception date
_AGG_START = "2003-09-26"      # AGG inception date


# ── Helper: single-ticker download ───────────────────────────────────────────────

def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw.empty:
        raise ValueError(f"No data returned for {ticker} [{start} → {end}]")
    return raw


# ── Step 1: Stitch ^GSPC + SPY ───────────────────────────────────────────────────

def load_stitched_data(start: str = "1950-01-01", end: str = "2026-03-01") -> pd.Series:
    """
    Download ^GSPC (1950–1993-01-28) and SPY (1993-01-29 onward), then stitch.

    Normalization: multiply ^GSPC prices by SPY.iloc[0] / GSPC.loc["1993-01-29"]
    so both series align at the stitch date. This preserves relative returns while
    making the absolute price level continuous.

    Returns:
        pd.Series: daily Close prices, index = DatetimeIndex
    """
    # Determine whether we need ^GSPC at all (only if start is before the SPY inception)
    need_gspc = pd.Timestamp(start) <= pd.Timestamp(_GSPC_END)

    if need_gspc:
        logger.info("Downloading ^GSPC from %s to %s", start, _GSPC_END)
        gspc_raw = _download("^GSPC", start=start, end=_GSPC_END)
        gspc_close = gspc_raw["Close"]
    else:
        gspc_close = pd.Series(dtype=float)

    # SPY start: use max(start, _SPY_START) to avoid requesting dates before SPY inception
    spy_dl_start = max(pd.Timestamp(start), pd.Timestamp(_SPY_START)).strftime("%Y-%m-%d")
    logger.info("Downloading SPY from %s to %s", spy_dl_start, end)
    spy_raw = _download("SPY", start=spy_dl_start, end=end)
    spy_close = spy_raw["Close"]

    if need_gspc and not gspc_close.empty:
        # Align normalization: find ^GSPC value on or just before first SPY date
        spy_first_date = spy_close.index[0]
        candidates = gspc_close.index[gspc_close.index <= spy_first_date]
        gspc_stitch_date = candidates[-1] if len(candidates) > 0 else gspc_close.index[-1]

        scale_factor = spy_close.iloc[0] / gspc_close.loc[gspc_stitch_date]
        logger.info(
            "Stitch normalization: ^GSPC(%s)=%.4f × %.6f → SPY(%s)=%.4f",
            gspc_stitch_date, gspc_close.loc[gspc_stitch_date],
            scale_factor, spy_first_date, spy_close.iloc[0],
        )
        gspc_scaled = gspc_close * scale_factor

        # Combine: ^GSPC (scaled) up to last ^GSPC date, then SPY
        stitched = pd.concat([gspc_scaled, spy_close])
    else:
        stitched = spy_close.copy()

    stitched = stitched[~stitched.index.duplicated(keep="last")]
    stitched = stitched.sort_index()

    # ── Data quality: check for unexpected intraweek gaps in ^GSPC pre-1993 ────
    if need_gspc and not gspc_close.empty:
        gspc_portion = stitched.loc[:_GSPC_END]
        _check_data_gaps(gspc_portion, label="^GSPC 1950–1993")

    logger.info(
        "Stitched series: %d trading days [%s → %s]",
        len(stitched), stitched.index[0].date(), stitched.index[-1].date(),
    )
    return stitched


def _check_data_gaps(prices: pd.Series, label: str) -> None:
    """
    Flag if any calendar year has >5 consecutive missing weekdays.
    Weekend/holiday gaps (1–2 days) are expected; intraweek streaks of >5 are anomalies.
    Updates the global DATA_QUALITY dict.
    """
    all_dates = pd.date_range(prices.index.min(), prices.index.max(), freq="B")
    missing = all_dates.difference(prices.index)
    if len(missing) == 0:
        DATA_QUALITY["data_gaps"] = "no_gaps_detected"
        return

    # Find consecutive runs of missing weekdays
    missing_series = pd.Series(missing)
    runs: list[int] = []
    run = 1
    for i in range(1, len(missing_series)):
        if (missing_series.iloc[i] - missing_series.iloc[i - 1]).days == 1:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)

    max_run = max(runs) if runs else 0
    if max_run > 5:
        msg = f"WARNING: {label} has consecutive missing weekday run of {max_run} days"
        logger.warning(msg)
        DATA_QUALITY["data_gaps"] = f"flagged: max_consecutive_missing={max_run}"
    else:
        DATA_QUALITY["data_gaps"] = f"ok: max_consecutive_missing={max_run} (≤5)"


# ── Step 2: Generate signals ──────────────────────────────────────────────────────

def generate_signals(prices: pd.Series, params: dict = PARAMETERS) -> pd.DataFrame:
    """
    Generate daily position signals for the Halloween seasonal switch.

    Logic:
    - Position = 1 (long) from last trading day of winter_entry_month
      through last trading day of winter_exit_month.
    - Position = 0 (cash/summer) otherwise.
    - Circuit breaker: if price falls >= circuit_breaker_drawdown from peak
      during a winter holding period, exit immediately and skip re-entry
      until the next October signal.

    Returns:
        pd.DataFrame with columns:
            position (int): 1=long, 0=cash
            circuit_breaker_triggered (bool): True on the day CB fires
    """
    entry_month = params["winter_entry_month"]    # 10 = October
    exit_month = params["winter_exit_month"]       # 4 = April
    cb_threshold = params["circuit_breaker_drawdown"]

    signals = pd.DataFrame(
        {"position": 0, "circuit_breaker_triggered": False},
        index=prices.index,
        dtype=object,
    )
    signals["position"] = signals["position"].astype(int)
    signals["circuit_breaker_triggered"] = signals["circuit_breaker_triggered"].astype(bool)

    # Identify all years present in the price series
    years = sorted(prices.index.year.unique())

    # State machine per winter cycle
    in_winter = False
    cb_fired_this_cycle = False
    peak_price = np.nan

    for i, date in enumerate(prices.index):
        price = prices.iloc[i]
        month = date.month
        year = date.year

        # ── Entry trigger: last trading day of entry_month ──────────────────────
        # Check if we just left entry_month (next day is a different month)
        # Implementation: enter on the last trading day of entry_month.
        # We set in_winter=True as soon as we're past the last day of entry_month — but we
        # need to capture that final day's close. We look ahead: if today is in entry_month
        # and the next trading day is NOT in entry_month, today is the entry signal.
        if not in_winter and not cb_fired_this_cycle:
            if month == entry_month:
                # Check if next trading day is in a different month
                if i + 1 < len(prices.index):
                    next_month = prices.index[i + 1].month
                    if next_month != entry_month:
                        # Today is the last trading day of October → enter long
                        in_winter = True
                        peak_price = price
                        signals.at[date, "position"] = 1
                        logger.debug("ENTRY %s @ %.4f", date.date(), price)
                else:
                    # Last row and in entry_month — treat as entry
                    in_winter = True
                    peak_price = price
                    signals.at[date, "position"] = 1

        elif in_winter:
            # Update peak (running maximum from entry date)
            if price > peak_price:
                peak_price = price

            # Circuit breaker check: drawdown from peak
            drawdown = (peak_price - price) / peak_price
            if drawdown >= cb_threshold:
                # Exit immediately; skip the rest of this winter cycle
                signals.at[date, "position"] = 0
                signals.at[date, "circuit_breaker_triggered"] = True
                logger.warning(
                    "CIRCUIT BREAKER %s: peak=%.4f trough=%.4f drawdown=%.2f%%",
                    date.date(), peak_price, price, drawdown * 100,
                )
                in_winter = False
                cb_fired_this_cycle = True
                peak_price = np.nan
                continue

            # Exit trigger: last trading day of exit_month
            if month == exit_month:
                if i + 1 < len(prices.index):
                    next_month = prices.index[i + 1].month
                    if next_month != exit_month:
                        # Today is the last trading day of April → exit
                        signals.at[date, "position"] = 0   # exit at close — next day is cash
                        in_winter = False
                        logger.debug("EXIT %s @ %.4f", date.date(), price)
                    else:
                        signals.at[date, "position"] = 1
                else:
                    signals.at[date, "position"] = 0
                    in_winter = False
            else:
                signals.at[date, "position"] = 1

        # Reset circuit-breaker block after exiting summer (new winter cycle starts)
        if cb_fired_this_cycle and month == entry_month:
            # Check whether next trading day leaves entry_month — if so, new cycle
            if i + 1 < len(prices.index):
                next_month = prices.index[i + 1].month
                if next_month != entry_month:
                    cb_fired_this_cycle = False  # allow re-entry next October

    return signals


# ── Step 3: Transaction costs ─────────────────────────────────────────────────────

def _compute_trade_cost(
    price: float,
    volume: float,
    params: dict,
) -> tuple[float, bool]:
    """
    Compute total per-share transaction cost at one trade leg.

    Cost = fixed_cost_per_share + slippage_pct * price + market_impact
    market_impact = k * sigma * sqrt(Q / ADV)  [square-root model]

    Returns:
        (cost_per_share, liquidity_constrained)
    """
    Q = params["order_qty"]
    k = params["market_impact_k"]
    fixed = params["fixed_cost_per_share"]
    slip = params["slippage_pct"] * price

    # ADV in shares (volume is already in shares for SPY; ^GSPC has no volume — use 0 impact)
    adv = volume if volume > 0 else np.nan

    liquidity_constrained = False
    market_impact = 0.0

    if not np.isnan(adv) and adv > 0:
        q_over_adv = Q / adv
        if q_over_adv > params["liquidity_threshold"]:
            liquidity_constrained = True
            logger.warning("LIQUIDITY_CONSTRAINED: Q/ADV=%.4f (>%.2f)", q_over_adv, params["liquidity_threshold"])
        # sigma provided externally; approximated as 0 here — caller passes sigma
        market_impact = 0.0  # computed in apply_transaction_costs with rolling sigma

    total = fixed + slip + market_impact
    return total, liquidity_constrained


def apply_transaction_costs(
    prices: pd.Series,
    signals: pd.DataFrame,
    params: dict,
    volume: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Identify trade entry/exit days and compute per-trade cost.

    Market impact uses 20-day rolling sigma and 20-day rolling ADV (volume × price).
    Applied at entry and exit legs independently.

    Returns:
        pd.DataFrame: trade log with columns:
            entry_date, exit_date, entry_price, exit_price, return_pct,
            pnl, circuit_breaker, liquidity_constrained, entry_cost, exit_cost
    """
    pos = signals["position"].astype(int)
    cb = signals["circuit_breaker_triggered"].astype(bool)

    # Rolling sigma (20-day return vol)
    returns = prices.pct_change()
    sigma = returns.rolling(params["sigma_window"]).std()

    # Rolling ADV in shares (volume series; fall back to NaN if not available)
    if volume is not None:
        adv = volume.rolling(params["adv_window"]).mean()
    else:
        adv = pd.Series(np.nan, index=prices.index)

    # Identify position changes
    pos_diff = pos.diff().fillna(pos.astype(float))

    trade_log = []
    entry_date = None
    entry_price = np.nan
    entry_cost = 0.0
    entry_lc = False

    for date in prices.index:
        p = prices.loc[date]
        sig = pos.loc[date]
        chg = pos_diff.loc[date]
        is_cb = cb.loc[date]

        # Entry: position flips from 0 → 1
        if chg == 1:
            entry_date = date
            entry_price = p
            s = sigma.loc[date] if not np.isnan(sigma.loc[date]) else 0.0
            a = adv.loc[date] if not np.isnan(adv.loc[date]) else 0.0
            Q = params["order_qty"]
            k = params["market_impact_k"]
            mi = k * s * np.sqrt(Q / a) if a > 0 else 0.0
            lc = (Q / a > params["liquidity_threshold"]) if a > 0 else False
            entry_cost = params["fixed_cost_per_share"] + params["slippage_pct"] * p + mi
            entry_lc = lc

        # Exit: position flips from 1 → 0 (either normal or CB)
        elif chg == -1 and entry_date is not None:
            exit_price = p
            s = sigma.loc[date] if not np.isnan(sigma.loc[date]) else 0.0
            a = adv.loc[date] if not np.isnan(adv.loc[date]) else 0.0
            Q = params["order_qty"]
            k = params["market_impact_k"]
            mi = k * s * np.sqrt(Q / a) if a > 0 else 0.0
            lc = (Q / a > params["liquidity_threshold"]) if a > 0 else False
            exit_cost = params["fixed_cost_per_share"] + params["slippage_pct"] * exit_price + mi

            gross_ret = (exit_price - entry_price) / entry_price
            # Cost drag: total cost in price units / entry_price
            total_cost_pct = (entry_cost + exit_cost) / entry_price
            net_ret = gross_ret - total_cost_pct
            pnl = net_ret * params["init_cash"]

            trade_log.append({
                "entry_date": entry_date,
                "exit_date": date,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": net_ret,
                "pnl": pnl,
                "circuit_breaker": is_cb,
                "liquidity_constrained": entry_lc or lc,
                "entry_cost": entry_cost,
                "exit_cost": exit_cost,
            })
            entry_date = None
            entry_price = np.nan

    return pd.DataFrame(trade_log)


# ── Step 4: Equity curve ──────────────────────────────────────────────────────────

def _build_equity_curve(
    prices: pd.Series,
    signals: pd.DataFrame,
    trade_log: pd.DataFrame,
    params: dict,
) -> tuple[pd.Series, pd.Series]:
    """
    Construct daily equity curve from position signals and per-trade costs.

    Method: apply daily price returns when in position (position=1); apply 0 when flat.
    Deduct entry/exit costs on the exact trade dates from the trade log.

    Returns:
        equity_curve (pd.Series): daily portfolio value
        daily_returns (pd.Series): daily portfolio returns
    """
    pos = signals["position"].astype(float)
    price_returns = prices.pct_change().fillna(0.0)

    # Raw strategy returns (before cost adjustment)
    strat_returns = pos.shift(1).fillna(0.0) * price_returns  # shift(1): yesterday's position

    # Apply cost drag on entry and exit days
    cost_series = pd.Series(0.0, index=prices.index)
    for _, row in trade_log.iterrows():
        if row["entry_date"] in cost_series.index:
            cost_series.loc[row["entry_date"]] -= row["entry_cost"] / row["entry_price"]
        if row["exit_date"] in cost_series.index:
            cost_series.loc[row["exit_date"]] -= row["exit_cost"] / row["exit_price"]

    net_returns = strat_returns + cost_series
    equity_curve = params["init_cash"] * (1 + net_returns).cumprod()

    return equity_curve, net_returns


# ── Step 5: Metrics ───────────────────────────────────────────────────────────────

def _compute_metrics(equity_curve: pd.Series, daily_returns: pd.Series, trade_log: pd.DataFrame) -> dict:
    """Compute standard Gate 1 performance metrics."""
    trading_days = 252

    annualized_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (
        trading_days / max(len(equity_curve), 1)
    ) - 1

    vol = daily_returns.std() * np.sqrt(trading_days)
    sharpe = annualized_return / vol if vol > 0 else 0.0

    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_drawdown = drawdown.min()

    if trade_log.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": float(max_drawdown),
            "sharpe_ratio": float(sharpe),
            "annualized_return": float(annualized_return),
        }

    winners = trade_log[trade_log["return_pct"] > 0]
    losers = trade_log[trade_log["return_pct"] <= 0]
    win_rate = len(winners) / len(trade_log)

    gross_profit = winners["pnl"].sum() if not winners.empty else 0.0
    gross_loss = abs(losers["pnl"].sum()) if not losers.empty else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf

    return {
        "total_trades": len(trade_log),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "max_drawdown": float(max_drawdown),
        "sharpe_ratio": float(sharpe),
        "annualized_return": float(annualized_return),
    }


# ── Main entry point ──────────────────────────────────────────────────────────────

def run_strategy(
    params: dict = PARAMETERS,
    start: str = "1950-01-01",
    end: str = "2026-03-01",
) -> dict:
    """
    Full run: load stitched data → signals → transaction costs → equity curve → metrics.

    Returns dict with:
        equity_curve, returns, trade_log, metrics, data_quality, params
    """
    prices = load_stitched_data(start=start, end=end)

    # Download volume for SPY (needed for market impact; ^GSPC has no volume)
    logger.info("Downloading SPY volume for market impact calculation")
    spy_vol_raw = yf.download("SPY", start=_SPY_START, end=end, auto_adjust=True, progress=False)
    if isinstance(spy_vol_raw.columns, pd.MultiIndex):
        spy_vol_raw.columns = spy_vol_raw.columns.get_level_values(0)
    spy_volume = spy_vol_raw["Volume"] if "Volume" in spy_vol_raw.columns else pd.Series(dtype=float)
    # Reindex to full stitched index; NaN for pre-SPY dates (^GSPC period)
    volume = spy_volume.reindex(prices.index)

    logger.info("Generating signals (%s → %s)", start, end)
    signals = generate_signals(prices, params)

    logger.info("Building trade log with transaction costs")
    trade_log = apply_transaction_costs(prices, signals, params, volume=volume)

    logger.info("Building equity curve")
    equity_curve, daily_returns = _build_equity_curve(prices, signals, trade_log, params)

    metrics = _compute_metrics(equity_curve, daily_returns, trade_log)
    logger.info("Metrics: %s", metrics)

    # Log circuit breaker events
    cb_events = trade_log[trade_log["circuit_breaker"]] if not trade_log.empty else pd.DataFrame()
    if not cb_events.empty:
        logger.info("Circuit breaker triggered %d time(s):", len(cb_events))
        for _, ev in cb_events.iterrows():
            logger.info("  CB exit: %s, return=%.2f%%", ev["exit_date"], ev["return_pct"] * 100)

    # Liquidity-constrained trades
    lc_trades = trade_log[trade_log["liquidity_constrained"]] if not trade_log.empty else pd.DataFrame()
    if not lc_trades.empty:
        logger.warning("Liquidity-constrained trades: %d (Q/ADV > %.2f)", len(lc_trades), params["liquidity_threshold"])

    return {
        "equity_curve": equity_curve,
        "returns": daily_returns,
        "trade_log": trade_log,
        "metrics": metrics,
        "data_quality": DATA_QUALITY.copy(),
        "params": params,
    }


# ── IS / OOS split helper ─────────────────────────────────────────────────────────

def run_is_oos(params: dict = PARAMETERS) -> dict:
    """
    Run strategy on IS (1950–2018) and OOS (2019–2026-03-01) windows separately.

    Returns:
        dict with keys "is" and "oos", each containing the full run_strategy() dict.
    """
    logger.info("=== IS run (1950–2018) ===")
    is_result = run_strategy(params=params, start="1950-01-01", end="2018-12-31")

    logger.info("=== OOS run (2019–2026-03-01) ===")
    oos_result = run_strategy(params=params, start="2019-01-01", end="2026-03-01")

    return {"is": is_result, "oos": oos_result}


# ── CLI entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    result = run_is_oos()

    for window, res in result.items():
        m = res["metrics"]
        tl = res["trade_log"]
        print(f"\n{'='*60}")
        print(f"  {window.upper()} RESULTS")
        print(f"{'='*60}")
        print(f"  Total trades     : {m['total_trades']}")
        print(f"  Win rate         : {m['win_rate']:.1%}")
        print(f"  Profit factor    : {m['profit_factor']:.2f}")
        print(f"  Annualized return: {m['annualized_return']:.2%}")
        print(f"  Sharpe ratio     : {m['sharpe_ratio']:.3f}")
        print(f"  Max drawdown     : {m['max_drawdown']:.2%}")
        if not tl.empty:
            print(f"  First trade entry: {tl['entry_date'].iloc[0]}")
            print(f"  Last trade exit  : {tl['exit_date'].iloc[-1]}")
        print()

    print("Data quality:")
    print(json.dumps(result["is"]["data_quality"], indent=2, default=str))
