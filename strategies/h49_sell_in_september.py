"""
Strategy: H49 Sell-in-September Effect — SPY/SHY Monthly Calendar Rotation
Author: Strategy Coder Agent
Date: 2026-06-08
Hypothesis: September is the worst calendar month for US equities (Bouman & Jacobsen 2002;
            Jacobsen & Zhang 2012). Hold SPY 11 months/year; rotate to SHY (1-3yr Treasury)
            during September only to avoid the seasonal drawdown while remaining cash-neutral
            (SHY avoids duration risk from rate shocks that would hurt TLT).
Asset class: equities (ETFs) / short-duration Treasuries
References: research/hypotheses/49_qc_sell_in_september.md
Parent task: QUA-96

Data quality checklist:
  - Survivorship bias: NOT APPLICABLE. SPY and SHY are current ETFs with no delisting risk.
    Both are ultra-liquid index ETFs; no survivor bias in either ticker.
  - Price adjustments: auto_adjust=True via yfinance (splits, dividends adjusted)
  - Backtest window: 2002-01-01 to 2024-12-31 (SHY inception July 2002; SPY from 1993)
  - IS window: 2002-2017 (~16 years, 16 September-avoidance events)
  - OOS window: 2018-2024 (~7 years, 7 September-avoidance events)
  - Data gaps: checked at runtime via _check_data_gaps()
"""

import logging

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# All tunable parameters exposed here for sensitivity scanning
PARAMETERS = {
    # Calendar parameters
    "safe_harbor_asset": "SHY",          # safe harbor during September (SHY or TLT or BIL)
    "exit_timing_month": 8,              # August — last trading day triggers SPY→SHY rotation
    "reentry_timing_month": 9,           # September — last trading day triggers SHY→SPY rotation
    "ma_filter": False,                  # if True, only re-enter SPY if above 200-day MA
    "ma_window": 200,                    # 200-day MA window (used when ma_filter=True)

    # Transaction cost model (Engineering Director standard — equities)
    "fixed_cost_per_share": 0.005,       # $0.005/share fixed
    "slippage_pct": 0.0005,              # 0.05% slippage
    "market_impact_k": 0.1,             # square-root impact coefficient (Johnson 2010)
    "sigma_window": 20,                  # rolling vol window for market impact
    "adv_window": 20,                    # rolling ADV window
    "order_qty": 100,                    # default order size in shares
    "liquidity_threshold": 0.01,         # Q/ADV > 1% → flag liquidity-constrained

    # Portfolio
    "init_cash": 25000.0,
}

DATA_QUALITY = {
    "survivorship_bias": (
        "not_applicable — SPY and SHY are both current active ETFs with no delisting risk. "
        "SPY tracks S&P 500 (index survivorship is a separate issue; irrelevant here as "
        "we trade the ETF vehicle). SHY tracks 1-3yr Treasury index; zero delisting risk."
    ),
    "price_adjustments": "auto_adjust=True via yfinance for both SPY and SHY",
    "data_gaps": "pending — checked at runtime",
    "backtest_window": "2002-01-01 to 2024-12-31 (SHY inception ~July 2002)",
    "is_window": "2002-01-01 to 2017-12-31",
    "oos_window": "2018-01-01 to 2024-12-31",
}

_SPY_START = "1993-01-29"
_SHY_START = "2002-07-22"   # SHY inception date


# ── Data loading ──────────────────────────────────────────────────────────────────

def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV with auto_adjust=True; flatten MultiIndex columns if present."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw.empty:
        raise ValueError(f"No data for {ticker} [{start} → {end}]")
    return raw


def _check_data_gaps(prices: pd.Series, label: str) -> str:
    """Return a data-quality string flagging consecutive missing weekday runs > 5."""
    all_dates = pd.date_range(prices.index.min(), prices.index.max(), freq="B")
    missing = all_dates.difference(prices.index)
    if len(missing) == 0:
        return "no_gaps_detected"

    missing_series = pd.Series(missing)
    runs = []
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
        return f"flagged: max_consecutive_missing={max_run}"
    return f"ok: max_consecutive_missing={max_run} (<=5)"


def load_data(start: str = "2002-01-01", end: str = "2024-12-31") -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Download SPY and SHY close prices and volumes for the specified window.

    Returns:
        (spy_df, shy_df): DataFrames with at minimum Close and Volume columns.
    """
    logger.info("Downloading SPY [%s → %s]", start, end)
    spy_df = _download("SPY", start=start, end=end)

    logger.info("Downloading SHY [%s → %s]", max(start, _SHY_START), end)
    shy_start = max(pd.Timestamp(start), pd.Timestamp(_SHY_START)).strftime("%Y-%m-%d")
    shy_df = _download("SHY", start=shy_start, end=end)

    DATA_QUALITY["data_gaps_spy"] = _check_data_gaps(spy_df["Close"], "SPY")
    DATA_QUALITY["data_gaps_shy"] = _check_data_gaps(shy_df["Close"], "SHY")
    DATA_QUALITY["data_gaps"] = "checked — see data_gaps_spy and data_gaps_shy"

    return spy_df, shy_df


# ── Signal generation ─────────────────────────────────────────────────────────────

def generate_signals(
    spy_prices: pd.Series,
    params: dict = PARAMETERS,
) -> pd.Series:
    """
    Generate a daily regime series: 'SPY' or 'SHY'.

    Logic (calendar-mechanical — no price signal):
    - Hold SPY for all months EXCEPT September.
    - On the last trading day of August: switch SPY → SHY.
    - On the last trading day of September: switch SHY → SPY.
    - Optional 200-day MA filter at SHY→SPY re-entry (params['ma_filter']).

    Returns:
        pd.Series[str]: index=spy_prices.index, values in {'SPY', 'SHY'}
    """
    exit_month = params["exit_timing_month"]      # 8 = August
    reentry_month = params["reentry_timing_month"]  # 9 = September
    use_ma = params["ma_filter"]
    ma_window = params["ma_window"]

    if use_ma:
        ma200 = spy_prices.rolling(ma_window).mean()

    regime = pd.Series("SPY", index=spy_prices.index)
    in_shy = False

    for i, date in enumerate(spy_prices.index):
        month = date.month

        if not in_shy:
            # Check for last trading day of August (exit_month)
            if month == exit_month:
                is_last = (
                    i + 1 >= len(spy_prices.index)
                    or spy_prices.index[i + 1].month != exit_month
                )
                if is_last:
                    # Switch to SHY starting today's close
                    in_shy = True
                    regime.at[date] = "SHY"
                    logger.debug("AUG_EXIT %s — rotate SPY→SHY", date.date())
            # else remain SPY
        else:
            # In SHY (September): check for last trading day of September (reentry_month)
            if month == reentry_month:
                is_last = (
                    i + 1 >= len(spy_prices.index)
                    or spy_prices.index[i + 1].month != reentry_month
                )
                if is_last:
                    # Re-enter SPY, subject to optional MA filter
                    if use_ma and not np.isnan(ma200.iloc[i]):
                        if spy_prices.iloc[i] < ma200.iloc[i]:
                            # Below MA — stay in SHY (extend safe harbor one more month)
                            regime.at[date] = "SHY"
                            logger.info(
                                "MA_FILTER blocked re-entry %s: price=%.2f < MA200=%.2f",
                                date.date(), spy_prices.iloc[i], ma200.iloc[i],
                            )
                            continue
                    in_shy = False
                    regime.at[date] = "SPY"
                    logger.debug("SEP_EXIT %s — rotate SHY→SPY", date.date())
                else:
                    # Still in September, hold SHY
                    regime.at[date] = "SHY"
            else:
                # Unexpected: in_shy but not in reentry_month — keep SHY
                # This can happen on the last trading day of August itself
                regime.at[date] = "SHY"

    return regime


# ── Transaction costs ─────────────────────────────────────────────────────────────

def _compute_leg_cost(
    price: float,
    sigma: float,
    adv: float,
    params: dict,
) -> tuple[float, bool]:
    """
    Compute per-share cost for one trade leg.

    cost = fixed + slippage + market_impact
    market_impact = k * sigma * sqrt(Q / ADV)

    Returns:
        (cost_per_share, liquidity_constrained)
    """
    Q = params["order_qty"]
    fixed = params["fixed_cost_per_share"]
    slip = params["slippage_pct"] * price

    if adv > 0 and not np.isnan(adv):
        q_ratio = Q / adv
        lc = q_ratio > params["liquidity_threshold"]
        mi = params["market_impact_k"] * sigma * np.sqrt(q_ratio)
    else:
        lc = False
        mi = 0.0

    return fixed + slip + mi, lc


def apply_transaction_costs(
    regime: pd.Series,
    spy_df: pd.DataFrame,
    shy_df: pd.DataFrame,
    params: dict,
) -> pd.DataFrame:
    """
    Build a trade log for each SPY→SHY→SPY rotation cycle.

    Each round-trip generates two entries in the trade log:
      1. Exit SPY leg (sell SPY on last day of August)
      2. Exit SHY leg (sell SHY on last day of September, re-enter SPY)

    Both legs contribute transaction costs.

    Returns:
        pd.DataFrame: trade log with columns:
            transition_date, from_asset, to_asset, price_out, price_in,
            cost_per_share_out, cost_per_share_in, lc_out, lc_in
    """
    spy_close = spy_df["Close"]
    spy_vol = spy_df["Volume"] if "Volume" in spy_df.columns else pd.Series(np.nan, index=spy_df.index)
    shy_close = shy_df["Close"].reindex(regime.index)
    shy_vol = (
        shy_df["Volume"].reindex(regime.index)
        if "Volume" in shy_df.columns
        else pd.Series(np.nan, index=regime.index)
    )

    spy_sigma = spy_close.pct_change().rolling(params["sigma_window"]).std().reindex(regime.index)
    shy_sigma = shy_close.pct_change().rolling(params["sigma_window"]).std()
    spy_adv = spy_vol.rolling(params["adv_window"]).mean().reindex(regime.index)
    shy_adv = shy_vol.rolling(params["adv_window"]).mean().reindex(regime.index)

    trade_log = []
    prev_regime = None

    for date in regime.index:
        curr = regime.loc[date]
        if prev_regime is not None and curr != prev_regime:
            # Transition detected
            sell_asset = prev_regime
            buy_asset = curr

            if sell_asset == "SPY":
                sell_price = spy_close.loc[date] if date in spy_close.index else np.nan
                sell_sigma = spy_sigma.loc[date] if not np.isnan(spy_sigma.get(date, np.nan)) else 0.0
                sell_adv = spy_adv.loc[date] if not np.isnan(spy_adv.get(date, np.nan)) else 0.0
            else:
                sell_price = shy_close.loc[date] if not np.isnan(shy_close.get(date, np.nan)) else np.nan
                sell_sigma = shy_sigma.get(date, 0.0) if not np.isnan(shy_sigma.get(date, np.nan)) else 0.0
                sell_adv = shy_adv.loc[date] if not np.isnan(shy_adv.get(date, np.nan)) else 0.0

            if buy_asset == "SPY":
                buy_price = spy_close.loc[date] if date in spy_close.index else np.nan
                buy_sigma = spy_sigma.loc[date] if not np.isnan(spy_sigma.get(date, np.nan)) else 0.0
                buy_adv = spy_adv.loc[date] if not np.isnan(spy_adv.get(date, np.nan)) else 0.0
            else:
                buy_price = shy_close.loc[date] if not np.isnan(shy_close.get(date, np.nan)) else np.nan
                buy_sigma = shy_sigma.get(date, 0.0) if not np.isnan(shy_sigma.get(date, np.nan)) else 0.0
                buy_adv = shy_adv.loc[date] if not np.isnan(shy_adv.get(date, np.nan)) else 0.0

            if not np.isnan(sell_price):
                cost_out, lc_out = _compute_leg_cost(sell_price, sell_sigma, sell_adv, params)
            else:
                cost_out, lc_out = 0.0, False

            if not np.isnan(buy_price):
                cost_in, lc_in = _compute_leg_cost(buy_price, buy_sigma, buy_adv, params)
            else:
                cost_in, lc_in = 0.0, False

            if lc_out or lc_in:
                logger.warning(
                    "LIQUIDITY_CONSTRAINED transition %s %s→%s", date.date(), sell_asset, buy_asset
                )

            trade_log.append({
                "transition_date": date,
                "from_asset": sell_asset,
                "to_asset": buy_asset,
                "price_out": sell_price,
                "price_in": buy_price,
                "cost_per_share_out": cost_out,
                "cost_per_share_in": cost_in,
                "lc_out": lc_out,
                "lc_in": lc_in,
                "total_cost_pct": (cost_out + cost_in) / max(sell_price, 1e-6) if not np.isnan(sell_price) else 0.0,
            })

            logger.info(
                "TRANSITION %s: %s→%s | cost_out=%.5f cost_in=%.5f",
                date.date(), sell_asset, buy_asset, cost_out, cost_in,
            )

        prev_regime = curr

    return pd.DataFrame(trade_log)


# ── Equity curve ──────────────────────────────────────────────────────────────────

def build_equity_curve(
    regime: pd.Series,
    spy_df: pd.DataFrame,
    shy_df: pd.DataFrame,
    trade_log: pd.DataFrame,
    params: dict,
) -> tuple[pd.Series, pd.Series]:
    """
    Construct daily equity curve by applying:
      - SPY daily returns when regime == 'SPY'
      - SHY daily returns when regime == 'SHY'
      - Transaction cost drag on transition days (from trade_log)

    Returns:
        (equity_curve, daily_returns)
    """
    spy_ret = spy_df["Close"].pct_change().reindex(regime.index).fillna(0.0)
    shy_ret = shy_df["Close"].reindex(regime.index).pct_change().fillna(0.0)

    # Daily portfolio return: weighted by yesterday's regime (position held at open)
    # We use shift(1) to apply yesterday's signal to today's return (no look-ahead)
    prev_regime = regime.shift(1)

    daily_gross = pd.Series(0.0, index=regime.index)
    for date in regime.index:
        pr = prev_regime.loc[date]
        if pr == "SPY":
            daily_gross.loc[date] = spy_ret.loc[date]
        elif pr == "SHY":
            daily_gross.loc[date] = shy_ret.loc[date]
        # else 0.0 (first day, no prior position)

    # Cost drag on transition days
    cost_series = pd.Series(0.0, index=regime.index)
    for _, row in trade_log.iterrows():
        td = row["transition_date"]
        if td in cost_series.index and not np.isnan(row["price_out"]) and row["price_out"] > 0:
            cost_series.loc[td] -= row["total_cost_pct"]

    net_returns = daily_gross + cost_series
    equity_curve = params["init_cash"] * (1.0 + net_returns).cumprod()

    return equity_curve, net_returns


# ── Metrics ───────────────────────────────────────────────────────────────────────

def compute_metrics(
    equity_curve: pd.Series,
    net_returns: pd.Series,
    trade_log: pd.DataFrame,
) -> dict:
    """Compute standard Gate 1 performance metrics."""
    trading_days = 252
    n = len(equity_curve)

    ann_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (trading_days / max(n, 1)) - 1
    vol = net_returns.std() * np.sqrt(trading_days)
    sharpe = ann_return / vol if vol > 0 else 0.0

    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_dd = drawdown.min()

    # Summarize September events from trade log
    sep_events = []
    if not trade_log.empty:
        # Group into round-trip cycles: SPY→SHY (entry) paired with SHY→SPY (exit)
        entries = trade_log[trade_log["from_asset"] == "SPY"].reset_index(drop=True)
        exits = trade_log[trade_log["from_asset"] == "SHY"].reset_index(drop=True)
        n_cycles = min(len(entries), len(exits))
        total_cost_pct = trade_log["total_cost_pct"].sum()
        lc_count = int(trade_log["lc_out"].sum() + trade_log["lc_in"].sum())
    else:
        n_cycles = 0
        total_cost_pct = 0.0
        lc_count = 0

    return {
        "sharpe_ratio": float(sharpe),
        "annualized_return": float(ann_return),
        "max_drawdown": float(max_dd),
        "volatility": float(vol),
        "total_transitions": len(trade_log),
        "september_cycles": n_cycles,
        "total_cost_pct_all_transitions": float(total_cost_pct),
        "liquidity_constrained_legs": lc_count,
        "win_rate": float(np.nan),  # not meaningful for 1-month holds; see september avoidance rate
    }


# ── September avoidance analysis ──────────────────────────────────────────────────

def september_avoidance_stats(
    regime: pd.Series,
    spy_df: pd.DataFrame,
    shy_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    For each September in the data, compute SPY return and SHY return.
    Shows year-by-year attribution of avoidance benefit/cost.
    """
    spy_close = spy_df["Close"].reindex(regime.index)
    shy_close = shy_df["Close"].reindex(regime.index)

    rows = []
    years = sorted(regime.index.year.unique())
    for yr in years:
        sept_mask = (regime.index.year == yr) & (regime.index.month == 9)
        sept_dates = regime.index[sept_mask]
        if len(sept_dates) < 2:
            continue

        spy_sep_ret = spy_close.loc[sept_dates].pct_change().sum()
        shy_all_nan = shy_close.loc[sept_dates].isna().all()
        shy_sep_ret = shy_close.loc[sept_dates].pct_change().sum() if not shy_all_nan else np.nan

        # Was the strategy in SHY during September this year?
        in_shy = (regime.loc[sept_dates] == "SHY").any()

        rows.append({
            "year": yr,
            "spy_sept_return": spy_sep_ret,
            "shy_sept_return": shy_sep_ret,
            "strategy_in_shy": in_shy,
            "avoidance_alpha": (shy_sep_ret - spy_sep_ret) if (in_shy and not np.isnan(shy_sep_ret)) else np.nan,
        })

    return pd.DataFrame(rows)


# ── Main entry point ──────────────────────────────────────────────────────────────

def run_strategy(
    params: dict = PARAMETERS,
    start: str = "2002-01-01",
    end: str = "2024-12-31",
) -> dict:
    """
    Full run: load data → signals → transaction costs → equity curve → metrics.

    Returns:
        dict with equity_curve, returns, trade_log, metrics, sept_stats,
              data_quality, params
    """
    spy_df, shy_df = load_data(start=start, end=end)

    # Align both series to the common trading calendar (SPY drives the index)
    common_index = spy_df.index.intersection(shy_df.index)
    if len(common_index) == 0:
        raise ValueError("No overlapping trading days between SPY and SHY in the specified window")
    spy_df = spy_df.reindex(common_index)
    shy_df = shy_df.reindex(common_index)

    logger.info("Common index: %d trading days [%s → %s]", len(common_index),
                common_index[0].date(), common_index[-1].date())

    logger.info("Generating signals")
    regime = generate_signals(spy_df["Close"], params)

    # Count September months in SHY vs not
    sept_in_shy = ((regime.index.month == 9) & (regime == "SHY")).sum()
    sept_total_days = (regime.index.month == 9).sum()
    logger.info("September days in SHY: %d / %d", sept_in_shy, sept_total_days)

    logger.info("Computing transaction costs")
    trade_log = apply_transaction_costs(regime, spy_df, shy_df, params)
    logger.info("Total transitions: %d", len(trade_log))

    logger.info("Building equity curve")
    equity_curve, net_returns = build_equity_curve(regime, spy_df, shy_df, trade_log, params)

    metrics = compute_metrics(equity_curve, net_returns, trade_log)
    logger.info("Metrics: %s", metrics)

    sept_stats = september_avoidance_stats(regime, spy_df, shy_df)

    # Liquidity check summary
    if not trade_log.empty:
        lc_flags = trade_log[trade_log["lc_out"] | trade_log["lc_in"]]
        if not lc_flags.empty:
            logger.warning("Liquidity-constrained transitions: %d", len(lc_flags))

    return {
        "equity_curve": equity_curve,
        "returns": net_returns,
        "trade_log": trade_log,
        "metrics": metrics,
        "sept_stats": sept_stats,
        "data_quality": DATA_QUALITY.copy(),
        "params": params,
    }


# ── IS / OOS split ────────────────────────────────────────────────────────────────

def run_is_oos(params: dict = PARAMETERS) -> dict:
    """
    Run strategy on IS (2002-2017) and OOS (2018-2024) windows separately.

    Returns:
        dict with keys 'is' and 'oos', each containing the run_strategy() dict.
    """
    logger.info("=== IS run (2002-01-01 → 2017-12-31) ===")
    is_result = run_strategy(params=params, start="2002-01-01", end="2017-12-31")

    logger.info("=== OOS run (2018-01-01 → 2024-12-31) ===")
    oos_result = run_strategy(params=params, start="2018-01-01", end="2024-12-31")

    return {"is": is_result, "oos": oos_result}


# ── CLI ───────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    result = run_is_oos()

    for window, res in result.items():
        m = res["metrics"]
        tl = res["trade_log"]
        ss = res["sept_stats"]
        print(f"\n{'='*60}")
        print(f"  {window.upper()} RESULTS")
        print(f"{'='*60}")
        print(f"  Sharpe ratio     : {m['sharpe_ratio']:.3f}")
        print(f"  Annualized return: {m['annualized_return']:.2%}")
        print(f"  Max drawdown     : {m['max_drawdown']:.2%}")
        print(f"  Volatility       : {m['volatility']:.2%}")
        print(f"  September cycles : {m['september_cycles']}")
        print(f"  Total transitions: {m['total_transitions']}")
        print(f"  Total cost drag  : {m['total_cost_pct_all_transitions']:.4%}")
        print(f"  Liq-constrained  : {m['liquidity_constrained_legs']}")
        if not ss.empty:
            print()
            print("  September avoidance by year:")
            print(f"  {'Year':<6} {'SPY Sept':>10} {'SHY Sept':>10} {'In SHY':>7} {'Alpha':>10}")
            for _, row in ss.iterrows():
                alpha_str = f"{row['avoidance_alpha']:.2%}" if not np.isnan(row['avoidance_alpha']) else "  n/a"
                shy_str = f"{row['shy_sept_return']:.2%}" if not np.isnan(row['shy_sept_return']) else "  n/a"
                print(
                    f"  {int(row['year']):<6} {row['spy_sept_return']:>10.2%} "
                    f"{shy_str:>10} {str(row['strategy_in_shy']):>7} {alpha_str:>10}"
                )
        print()

    print("\nData quality:")
    print(json.dumps(result["is"]["data_quality"], indent=2, default=str))
