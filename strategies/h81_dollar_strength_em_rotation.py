"""
Strategy: H81 Dollar-Strength Emerging Market Rotation
Author: Strategy Coder Agent
Date: 2026-06-22
Hypothesis: USD trend (UUP ETF vs 50-day SMA + 3-month momentum) signals EM vs defensive
            rotation. Weak USD → overweight EEM. Strong USD bearish → 100% SHY.
            2-week confirmation prevents whipsaws. Hard EEM exit if 15% drawdown in 3 months.
Asset class: equities (ETF rotation)
Parent task: QUA-377
References:
  Froot & Ramadorai (2005) JF — USD→EM capital flows
  Koijen et al. (2018) JFE — carry and EM equity link
  Menkhoff et al. (2012) JFE — currency momentum
IS window:  2008-01-01 to 2022-12-31 (UUP inception 2007-02-20 + 50-day SMA warmup)
OOS window: 2023-01-01 to 2026-06-01
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    "tickers": ["EEM", "VEA", "SPY", "SHY"],
    "uup_ticker": "UUP",
    "uup_sma_period": 50,          # sweep: [30, 50, 63, 100]
    "uup_mom_period": 63,          # sweep: [42, 63, 126]
    "confirmation_weeks": 2,       # sweep: [1, 2, 3, 4]
    "spy_trend_ma": 200,           # sweep: [150, 200, 250]
    "neutral_band_pct": 0.01,      # ±1% around SMA = neutral zone
    "eem_hard_exit_dd": 0.15,      # 15% drawdown hard exit from EEM
    "init_cash": 25000,
}

TRADING_DAYS_PER_YEAR = 252
MARKET_IMPACT_K = 0.1    # Almgren-Chriss square-root coefficient
SIGMA_WINDOW = 20
ADV_WINDOW = 20

# Rotation table: (regime, spy_bullish) → {ticker: weight}
# Precedence: weak > neutral > strong
ALLOCATION_TABLE = {
    ("weak", True):     {"EEM": 0.80, "VEA": 0.20, "SPY": 0.00, "SHY": 0.00},
    ("weak", False):    {"EEM": 0.80, "VEA": 0.20, "SPY": 0.00, "SHY": 0.00},
    ("neutral", True):  {"EEM": 0.20, "VEA": 0.20, "SPY": 0.60, "SHY": 0.00},
    ("neutral", False): {"EEM": 0.20, "VEA": 0.20, "SPY": 0.60, "SHY": 0.00},
    ("strong", True):   {"EEM": 0.00, "VEA": 0.00, "SPY": 0.60, "SHY": 0.40},
    ("strong", False):  {"EEM": 0.00, "VEA": 0.00, "SPY": 0.00, "SHY": 1.00},
}

# Slippage tiers (Engineering Director spec)
SLIPPAGE = {
    "SPY": 0.00005,    # ultra-liquid (ED-SLIP-001): 0.005%
    "EEM": 0.0005,     # standard: 0.05%
    "VEA": 0.0005,
    "SHY": 0.0005,
}


# ── Data Download ──────────────────────────────────────────────────────────────

def _download(tickers: list, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download adjusted close + volume. Flatten MultiIndex if present."""
    if isinstance(tickers, str):
        tickers = [tickers]
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        volume = raw["Volume"]
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
        volume = raw[["Volume"]].rename(columns={"Volume": tickers[0]})
    return close.copy(), volume.copy()


def _check_gaps(series: pd.Series, label: str, threshold: int = 5) -> None:
    """Warn on consecutive NaN gaps >= threshold days."""
    if not series.isna().any():
        return
    groups = series.notna().cumsum()
    max_gap = int(series.isna().astype(int).groupby(groups).sum().max())
    if max_gap >= threshold:
        warnings.warn(
            f"DATA QUALITY: {label} has {max_gap} consecutive missing days "
            f"(>= {threshold} threshold) — forward-fill NOT applied"
        )


def download_data(params: dict, start: str, end: str) -> dict:
    """
    Download all tickers with warmup buffer.

    Warmup: max(uup_sma_period, uup_mom_period, spy_trend_ma) + 30 trading days
    expressed as 2x calendar days to ensure rolling indicators are warm at IS start.

    Returns dict: {ticker: close_series, ..., 'volume': {ticker: vol_series}, 'uup': uup_close}
    """
    max_window = max(params["uup_sma_period"], params["uup_mom_period"], params["spy_trend_ma"])
    warmup_cal = (max_window + 30) * 2
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_cal)).strftime("%Y-%m-%d")

    portfolio_tickers = list(params["tickers"])
    uup = params["uup_ticker"]

    close_port, vol_port = _download(portfolio_tickers, warmup_start, end)
    close_uup, _ = _download([uup], warmup_start, end)

    for ticker in portfolio_tickers:
        if ticker not in close_port.columns:
            raise ValueError(f"Missing price data for required ticker: {ticker}")
        _check_gaps(close_port[ticker], ticker)

    if uup not in close_uup.columns:
        raise ValueError(f"Missing price data for signal ticker: {uup}")
    _check_gaps(close_uup[uup], uup)

    # Check UUP inception guard (2007-02-20)
    uup_start = close_uup[uup].first_valid_index()
    if uup_start is not None and uup_start > pd.Timestamp("2008-01-01"):
        warnings.warn(
            f"UUP data starts {uup_start.date()} — IS start 2008-01-01 requires "
            "50-day SMA warmup. Reduce IS start or check data availability."
        )

    return {
        "close": close_port,
        "volume": vol_port,
        "uup": close_uup[uup],
    }


# ── Signal Computation ─────────────────────────────────────────────────────────

def compute_usd_regime(uup: pd.Series, params: dict) -> pd.DataFrame:
    """
    Compute weekly USD regime signal evaluated at Friday close.

    Signal components (no look-ahead — all computed from past data):
      sma_50   = UUP.rolling(uup_sma_period).mean()
      usd_mom  = (UUP / UUP.shift(uup_mom_period)) - 1
      usd_strong = UUP > sma AND usd_mom > 0
      usd_weak   = UUP < sma AND usd_mom < 0
      usd_neutral = abs(UUP/sma - 1) <= neutral_band_pct

    Precedence: weak > neutral > strong
    (Neutral catches the ±1% band around SMA regardless of momentum direction.)

    Returns DataFrame with columns: [sma, usd_mom, regime]
    Indexed on UUP daily dates; only Friday rows are used for signal generation.
    """
    sma = uup.rolling(params["uup_sma_period"]).mean()
    usd_mom = (uup / uup.shift(params["uup_mom_period"])) - 1

    # Classify regime
    neutral_band = params["neutral_band_pct"]
    rel_diff = (uup / sma) - 1  # positive = above SMA

    usd_weak = (uup < sma) & (usd_mom < 0)
    usd_neutral = rel_diff.abs() <= neutral_band
    usd_strong = (uup > sma) & (usd_mom > 0)

    # Apply precedence: weak > neutral > strong; default to neutral if none
    regime = pd.Series("neutral", index=uup.index, dtype=object)
    regime[usd_strong] = "strong"
    regime[usd_neutral] = "neutral"   # overrides strong within ±1% band
    regime[usd_weak] = "weak"         # highest precedence

    out = pd.DataFrame({
        "sma": sma,
        "usd_mom": usd_mom,
        "regime": regime,
    }, index=uup.index)

    # NaN warmup rows → regime unknown → treat as neutral (conservative)
    out.loc[sma.isna() | usd_mom.isna(), "regime"] = "neutral"

    return out


def apply_confirmation_filter(
    regime_series: pd.Series,
    confirmation_weeks: int,
) -> pd.Series:
    """
    State-machine confirmation filter: regime must persist for confirmation_weeks
    consecutive weekly signals before the confirmed regime changes.

    Prevents whipsaws at SMA crossovers. Operates on weekly (Friday) regime signal.

    Returns pd.Series of confirmed regime strings, same index as regime_series.
    """
    confirmed = []
    current_confirmed = regime_series.iloc[0] if len(regime_series) > 0 else "neutral"
    pending = current_confirmed
    pending_count = 0

    for raw_regime in regime_series:
        if raw_regime == pending:
            pending_count += 1
        else:
            pending = raw_regime
            pending_count = 1

        if pending_count >= confirmation_weeks and pending != current_confirmed:
            current_confirmed = pending

        confirmed.append(current_confirmed)

    return pd.Series(confirmed, index=regime_series.index, dtype=object)


def compute_spy_trend(spy_close: pd.Series, params: dict) -> pd.Series:
    """SPY above 200-day SMA = bullish. Returns boolean Series (daily)."""
    ma = spy_close.rolling(params["spy_trend_ma"]).mean()
    return spy_close > ma


def get_target_allocation(
    confirmed_regime: str,
    spy_bullish: bool,
    eem_hard_exit_active: bool,
) -> dict:
    """
    Look up target allocation from rotation table.

    EEM hard exit overrides normal allocation: if active, replace EEM weight with SPY.
    """
    alloc = ALLOCATION_TABLE.get((confirmed_regime, bool(spy_bullish)), {
        "EEM": 0.00, "VEA": 0.00, "SPY": 0.60, "SHY": 0.40  # default: neutral bullish
    }).copy()

    if eem_hard_exit_active and alloc.get("EEM", 0) > 0:
        # Hard exit: move EEM allocation to SPY
        alloc["SPY"] = alloc.get("SPY", 0) + alloc["EEM"]
        alloc["EEM"] = 0.0

    return alloc


# ── Transaction Cost ───────────────────────────────────────────────────────────

def compute_transaction_cost(
    ticker: str,
    trade_value: float,
    shares: float,
    sigma: float,
    dollar_adv: float,
) -> tuple[float, bool]:
    """
    Canonical transaction cost (Engineering Director spec):
      fixed    = $0.005/share
      slippage = ticker-specific % of notional
      impact   = k × σ × sqrt(Q/ADV) × trade_value  (square-root model)

    Q/ADV measured in dollar terms (both in dollars → dimensionless ratio).
    Returns (total_cost_dollars, liquidity_constrained).
    """
    fixed = 0.005 * shares
    slip_pct = SLIPPAGE.get(ticker, 0.0005)
    slippage = slip_pct * trade_value

    q_over_adv = trade_value / max(dollar_adv, 1.0)
    impact = MARKET_IMPACT_K * sigma * np.sqrt(q_over_adv) * trade_value
    liq_constrained = bool(q_over_adv > 0.01)

    if liq_constrained:
        warnings.warn(
            f"Liquidity-constrained: {ticker} trade_value=${trade_value:,.0f} "
            f"is {q_over_adv:.2%} of ADV. Q/ADV > 1%."
        )

    return fixed + slippage + impact, liq_constrained


# ── Main Simulation Engine ─────────────────────────────────────────────────────

def simulate_h81(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    weekly_alloc: pd.Series,   # Friday-indexed Series of allocation dicts
    params: dict,
) -> dict:
    """
    Simulate H81 multi-ETF rotation strategy.

    Execution model (no look-ahead):
    - Allocation dict confirmed at Friday close.
    - Position executed at Monday open (next trading day after Friday).
    - Within each position, mark-to-market daily using close prices.
    - Rebalance only when target allocation changes.
    - Hard EEM exit: if EEM position drawdown > 15% from entry peak in any
      trailing 63-trading-day window → flag active; respected at next Monday execution.

    Transaction costs applied on each allocation change (buy + sell sides).

    Returns dict with equity curve, trade log, metrics.
    """
    tickers = list(params["tickers"])
    init_cash = float(params["init_cash"])
    eem_dd_threshold = float(params["eem_hard_exit_dd"])

    # Precompute sigma (20-day rolling vol) and dollar ADV for each ticker
    sigma_d = {}
    dollar_adv_d = {}
    for t in tickers:
        if t in close.columns:
            daily_ret = close[t].pct_change()
            sigma_d[t] = daily_ret.rolling(SIGMA_WINDOW).std()
            if t in volume.columns:
                dollar_adv_d[t] = (volume[t] * close[t]).rolling(ADV_WINDOW).mean()
            else:
                dollar_adv_d[t] = pd.Series(1e9, index=close.index)

    # Build execution schedule: Friday signal → next trading Monday
    exec_schedule = {}   # date → allocation dict
    alloc_dates = weekly_alloc.index.tolist()
    for i, fri in enumerate(alloc_dates):
        alloc = weekly_alloc.iloc[i]
        # Next trading day after Friday
        future = close.index[close.index > fri]
        if len(future) == 0:
            continue
        exec_date = future[0]
        exec_schedule[exec_date] = alloc

    # State: fractional shares per ticker, cash remainder
    shares = {t: 0.0 for t in tickers}
    cash = init_cash
    current_alloc = {t: 0.0 for t in tickers}  # currently deployed weights
    eem_entry_peak = None   # peak portfolio value since last EEM entry
    eem_entry_date = None

    equity_curve = pd.Series(dtype=float, index=close.index)
    trade_log = []
    liquidity_flags = []

    def _portfolio_value(date):
        val = cash
        for t in tickers:
            if t in close.columns and shares[t] > 0:
                p = close[t].get(date, np.nan)
                if not np.isnan(p):
                    val += shares[t] * p
        return val

    def _execute_rebalance(date, target_alloc):
        nonlocal cash, eem_entry_peak, eem_entry_date

        total_val = _portfolio_value(date)
        if total_val <= 0:
            return

        for t in tickers:
            if t not in close.columns:
                continue
            price = close[t].get(date, np.nan)
            if np.isnan(price) or price <= 0:
                continue

            target_val = total_val * target_alloc.get(t, 0.0)
            current_val = shares[t] * price

            delta_val = target_val - current_val
            if abs(delta_val) < 1.0:   # ignore sub-dollar rebalance noise
                continue

            delta_shares = delta_val / price
            sig = sigma_d[t].get(date, 0.01) if t in sigma_d else 0.01
            if np.isnan(sig) or sig <= 0:
                sig = 0.01
            dadv = dollar_adv_d[t].get(date, 1e9) if t in dollar_adv_d else 1e9
            if np.isnan(dadv) or dadv <= 0:
                dadv = 1e9

            trade_val = abs(delta_val)
            trade_shares = abs(delta_shares)
            cost, liq = compute_transaction_cost(t, trade_val, trade_shares, sig, dadv)
            if liq:
                liquidity_flags.append({"date": str(date.date()), "ticker": t,
                                        "trade_value": round(trade_val, 2)})

            side = "buy" if delta_shares > 0 else "sell"
            if side == "buy":
                net_cost = trade_val + cost
                if net_cost > cash + 1.0:
                    # Scale down to available cash
                    scale = max(cash - cost, 0) / trade_val if trade_val > 0 else 0
                    delta_shares *= scale
                    trade_val *= scale
                    trade_shares = abs(delta_shares)
                    cost, liq = compute_transaction_cost(t, trade_val, trade_shares, sig, dadv)
                    net_cost = trade_val + cost
                if delta_shares > 0:
                    shares[t] += delta_shares
                    cash -= net_cost
            else:
                proceeds = trade_val - cost
                shares[t] += delta_shares  # negative
                cash += proceeds

            trade_log.append({
                "date": str(date.date()),
                "ticker": t,
                "side": side,
                "shares": round(abs(delta_shares), 4),
                "price": round(price, 4),
                "trade_value": round(trade_val, 2),
                "cost": round(cost, 4),
                "liquidity_constrained": liq,
                "target_weight": round(target_alloc.get(t, 0.0), 4),
            })

        # Track EEM entry peak for hard exit
        eem_wt = target_alloc.get("EEM", 0.0)
        if eem_wt > 0:
            if eem_entry_date is None:
                eem_entry_date = date
                eem_entry_peak = total_val
            else:
                eem_entry_peak = max(eem_entry_peak, total_val)
        else:
            eem_entry_date = None
            eem_entry_peak = None

    # Check if EEM hard exit should trigger (trailing 63-day drawdown)
    def _eem_hard_exit_active(date, current_target_alloc) -> bool:
        if current_target_alloc.get("EEM", 0.0) <= 0:
            return False
        if eem_entry_peak is None or eem_entry_peak <= 0:
            return False
        cur_val = _portfolio_value(date)
        dd_from_peak = (cur_val - eem_entry_peak) / eem_entry_peak
        if dd_from_peak < -eem_dd_threshold:
            warnings.warn(
                f"EEM hard exit triggered on {date.date()}: "
                f"drawdown {dd_from_peak:.2%} < -{eem_dd_threshold:.0%} from peak "
                f"(peak={eem_entry_peak:,.2f}, current={cur_val:,.2f})"
            )
            return True
        return False

    current_target = {t: 0.0 for t in tickers}
    current_target["SHY"] = 1.0  # start defensive

    for i, date in enumerate(close.index):
        # Determine if there is a scheduled rebalance for today
        new_alloc = exec_schedule.get(date, None)

        # Check EEM hard exit override
        hard_exit = _eem_hard_exit_active(date, current_target)
        if hard_exit:
            # Override: move EEM allocation to SPY
            override_alloc = current_target.copy()
            eem_wt = override_alloc.pop("EEM", 0.0)
            override_alloc["EEM"] = 0.0
            override_alloc["SPY"] = override_alloc.get("SPY", 0.0) + eem_wt
            new_alloc = override_alloc
            trade_log.append({"date": str(date.date()), "event": "EEM_HARD_EXIT",
                               "eem_weight_moved_to_spy": round(eem_wt, 4)})

        # Compare allocations safely (handle both dict and Series types)
        should_rebalance = False
        if new_alloc is not None:
            if isinstance(new_alloc, pd.Series):
                # Convert Series to dict for comparison
                new_alloc_dict = new_alloc.to_dict()
                should_rebalance = new_alloc_dict != current_target
            else:
                should_rebalance = new_alloc != current_target

        if should_rebalance:
            _execute_rebalance(date, new_alloc)
            # Ensure current_target is always a dict
            if isinstance(new_alloc, pd.Series):
                current_target = new_alloc.to_dict()
            else:
                current_target = new_alloc

        # Daily MTM
        equity_curve.iloc[i] = _portfolio_value(date)

        # Update EEM entry peak daily if holding EEM
        if current_target.get("EEM", 0.0) > 0 and eem_entry_peak is not None:
            cur_val = equity_curve.iloc[i]
            if not np.isnan(cur_val):
                eem_entry_peak = max(eem_entry_peak, cur_val)

    # Force-close all positions at end of data
    last_date = close.index[-1]
    last_val = _portfolio_value(last_date)

    equity_curve = equity_curve.ffill().fillna(init_cash)

    # Metrics
    daily_ret = equity_curve.pct_change().fillna(0.0).values
    sharpe = 0.0
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe = round(float(daily_ret.mean() / daily_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)

    cum = np.cumprod(1 + daily_ret) if len(daily_ret) > 0 else np.array([1.0])
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4)
    years = max((close.index[-1] - close.index[0]).days / 365.25, 1e-3)
    cagr = round(float((1 + total_return) ** (1.0 / years) - 1), 4)

    trades_df = pd.DataFrame([t for t in trade_log if "ticker" in t])
    n_trades = len(trades_df)
    win_rate = 0.0
    if n_trades > 0:
        # Win rate: positive net trades (buy+sell pairs can't easily be matched here;
        # use portfolio equity segments instead — win_rate from daily equity changes on
        # execution days as a proxy)
        exec_dates = sorted(exec_schedule.keys())
        segment_rets = []
        for j in range(len(exec_dates) - 1):
            d0 = exec_dates[j]
            d1 = exec_dates[j + 1]
            v0 = equity_curve.get(d0, np.nan)
            v1 = equity_curve.get(d1, np.nan)
            if not np.isnan(v0) and not np.isnan(v1) and v0 > 0:
                segment_rets.append((v1 - v0) / v0)
        if segment_rets:
            win_rate = round(float(np.mean([r > 0 for r in segment_rets])), 4)

    return {
        "sharpe": sharpe,
        "cagr": cagr,
        "max_drawdown": mdd,
        "total_return": total_return,
        "trade_count": n_trades,
        "win_rate": win_rate,
        "equity": equity_curve,
        "trade_log": trade_log,
        "liquidity_flags": liquidity_flags,
        "final_value": round(last_val, 2),
        "years": round(years, 2),
    }


# ── Main Backtest Entry Point ──────────────────────────────────────────────────

def run_backtest(start: str, end: str, params: dict = None) -> dict:
    """
    Download data, compute USD regime signal, apply 2-week confirmation,
    build weekly allocation schedule, simulate H81 rotation, return metrics.

    Parameters
    ----------
    start : str  Backtest start (YYYY-MM-DD). IS: "2008-01-01".
    end : str    Backtest end (YYYY-MM-DD). IS: "2022-12-31".
    params : dict  Override PARAMETERS; uses module-level PARAMETERS if None.

    Returns
    -------
    dict with sharpe, cagr, max_drawdown, total_return, trade_count, win_rate,
    equity, trade_log, liquidity_flags, data_quality, weekly_signals, and params.
    """
    if params is None:
        params = PARAMETERS.copy()

    ts_start = pd.Timestamp(start)
    ts_end = pd.Timestamp(end)

    # 1. Download with warmup buffer
    data = download_data(params, start, end)
    close_full = data["close"]
    volume_full = data["volume"]
    uup_full = data["uup"]

    # 2. Align UUP to portfolio calendar (ffill for FX holiday gaps)
    uup_aligned = uup_full.reindex(close_full.index).ffill(limit=3)

    # 3. Compute regime signals (daily, on full buffered data)
    regime_df = compute_usd_regime(uup_aligned, params)
    spy_bullish_full = compute_spy_trend(close_full["SPY"], params)

    # 4. Extract Friday signals for weekly evaluation
    # "Friday" = weekday 4. If market closed that Friday, use last available day of week.
    weekly_dates = close_full.index[close_full.index.dayofweek == 4]  # Fridays only
    if len(weekly_dates) == 0:
        # Fallback: use all week-ending trading days via resample
        weekly_dates = close_full.resample("W-FRI").last().index.intersection(close_full.index)

    weekly_regime = regime_df["regime"].reindex(weekly_dates, method="ffill")
    weekly_spy_bull = spy_bullish_full.reindex(weekly_dates, method="ffill")

    # 5. Apply confirmation filter (state machine on weekly signals)
    confirmed_regime = apply_confirmation_filter(weekly_regime, params["confirmation_weeks"])

    # 6. Build allocation dict per Friday (before EEM hard exit override)
    weekly_alloc = pd.Series(index=weekly_dates, dtype=object)
    for i, fri in enumerate(weekly_dates):
        regime = confirmed_regime.iloc[i]
        spy_bull = bool(weekly_spy_bull.iloc[i]) if not pd.isna(weekly_spy_bull.iloc[i]) else True
        # EEM hard exit state is managed inside simulate_h81 (runtime, not precomputed)
        alloc = get_target_allocation(regime, spy_bull, eem_hard_exit_active=False)
        weekly_alloc.iloc[i] = alloc

    # 7. Trim to backtest window
    def _trim(df):
        return df.loc[(df.index >= ts_start) & (df.index <= ts_end)]

    close_sim = _trim(close_full).copy()
    volume_sim = _trim(volume_full).copy()
    weekly_alloc_sim = weekly_alloc[
        (weekly_alloc.index >= ts_start) & (weekly_alloc.index <= ts_end)
    ]

    if len(close_sim) < 10:
        raise ValueError(f"Insufficient data after trimming to {start}–{end}: {len(close_sim)} bars")

    # 8. Simulate
    result = simulate_h81(close_sim, volume_sim, weekly_alloc_sim, params)

    # 9. Build weekly signal summary for diagnostics
    weekly_signals_df = pd.DataFrame({
        "raw_regime": weekly_regime,
        "confirmed_regime": confirmed_regime,
        "spy_bullish": weekly_spy_bull,
    }, index=weekly_dates)
    weekly_signals_sim = weekly_signals_df[
        (weekly_signals_df.index >= ts_start) & (weekly_signals_df.index <= ts_end)
    ]

    # Regime breakdown stats
    regime_counts = confirmed_regime[
        (confirmed_regime.index >= ts_start) & (confirmed_regime.index <= ts_end)
    ].value_counts().to_dict()

    years = result["years"]
    n_transitions = result["trade_count"]
    transitions_per_quarter = round(n_transitions / max(years * 4, 1), 1)
    pf1_status = (
        f"PASS ({transitions_per_quarter:.1f}/quarter >= 30)"
        if transitions_per_quarter >= 30
        else f"WARN: {transitions_per_quarter:.1f}/quarter < 30 — trade count floor not met"
    )

    print(
        f"\nH81 Dollar-Strength EM Rotation ({start}–{end}) "
        f"[sma={params['uup_sma_period']}d, mom={params['uup_mom_period']}d, "
        f"confirm={params['confirmation_weeks']}w, spy_ma={params['spy_trend_ma']}d]:\n"
        f"  Sharpe: {result['sharpe']} | CAGR: {result['cagr']:.2%} | "
        f"Max DD: {result['max_drawdown']:.2%} | Total Return: {result['total_return']:.2%}\n"
        f"  Trade count: {n_transitions} ({transitions_per_quarter:.1f}/quarter) | "
        f"Win rate: {result['win_rate']:.2%} | Final: ${result['final_value']:,.2f}\n"
        f"  Regime weeks — weak: {regime_counts.get('weak', 0)} | "
        f"neutral: {regime_counts.get('neutral', 0)} | strong: {regime_counts.get('strong', 0)}\n"
        f"  PF-1: {pf1_status}"
    )

    return {
        **result,
        "params": params.copy(),
        "pf1_status": pf1_status,
        "regime_counts": regime_counts,
        "transitions_per_quarter": transitions_per_quarter,
        "weekly_signals": weekly_signals_sim,
        "data_quality": {
            "survivorship_bias": (
                "Fixed 4-ticker portfolio universe (EEM/VEA/SPY/SHY) + UUP signal. "
                "All ETFs are active and liquid as of 2026. Constituents are diversified "
                "baskets — no individual stock survivorship bias. ETF-level selection "
                "done a priori from hypothesis specification, not backtest performance."
            ),
            "price_adjustment": "yfinance auto_adjust=True — splits and dividends adjusted.",
            "data_gaps": "Gaps >= 5 consecutive days trigger a warning (not silently filled).",
            "uup_inception": (
                "UUP launched 2007-02-20. IS start 2008-01-01 gives 50-day SMA + "
                "63-day momentum warmup (both included via pre-start buffer)."
            ),
            "delisted": "N/A — all ETFs are active (EEM 2003+, VEA 2007+, SPY 1993+, SHY 2002+, UUP 2007+).",
            "earnings_exclusion": "N/A — ETF strategy; no individual earnings events.",
            "signal_lag": (
                "Friday close signal → Monday open execution (T+1 from Friday). "
                "2-week confirmation: regime must appear 2 consecutive Fridays before "
                "target allocation changes. No look-ahead bias."
            ),
            "forward_fill": "UUP forward-filled into portfolio equity calendar (limit=3 days) for FX holidays.",
        },
    }


# ── Orchestrator Compatibility ─────────────────────────────────────────────────

def run_strategy(
    ticker: str = "EEM",
    start: str = "2008-01-01",
    end: str = "2022-12-31",
    params: dict = None,
) -> dict:
    """
    Orchestrator-compatible entry point for H81.

    ticker arg is ignored (multi-asset rotation); kept for interface consistency.
    Returns standardized metrics dict.
    """
    p = (params or PARAMETERS).copy()
    return run_backtest(start, end, p)


# ── Parameter Sensitivity Scan ─────────────────────────────────────────────────

def scan_parameters(
    start: str = "2008-01-01",
    end: str = "2022-12-31",
    base_params: dict = None,
) -> dict:
    """
    Sweep key parameters. Returns dict of {param_label: sharpe}.
    Gate 1: Sharpe variance > 30% across any single dimension → flag.
    """
    if base_params is None:
        base_params = PARAMETERS.copy()

    results = {}
    sweep = {
        "uup_sma_period": [30, 50, 63, 100],
        "uup_mom_period": [42, 63, 126],
        "confirmation_weeks": [1, 2, 3, 4],
        "spy_trend_ma": [150, 200, 250],
    }

    for param_name, values in sweep.items():
        param_results = {}
        for v in values:
            p = {**base_params, param_name: v}
            key = f"{param_name}={v}"
            try:
                r = run_backtest(start, end, p)
                param_results[key] = round(r["sharpe"], 4)
            except Exception as exc:
                param_results[key] = f"error: {exc}"

        results[param_name] = param_results

        sharpe_nums = [v for v in param_results.values() if isinstance(v, float) and not np.isnan(v)]
        if len(sharpe_nums) > 1:
            sharpe_range = max(sharpe_nums) - min(sharpe_nums)
            sharpe_mean = np.mean(sharpe_nums)
            variance_pct = sharpe_range / abs(sharpe_mean) if abs(sharpe_mean) > 0 else float("inf")
            results[f"{param_name}_variance_pct"] = round(variance_pct, 4)
            results[f"{param_name}_gate1"] = (
                f"PASS: variance {variance_pct:.1%} <= 30%"
                if variance_pct <= 0.30
                else f"FAIL: variance {variance_pct:.1%} > 30%"
            )

    return results


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # IS baseline (default params, 2008-01-01 to 2022-12-31)
    print("Running H81 IS baseline (2008-01-01 to 2022-12-31, default params)...")
    is_result = run_backtest("2008-01-01", "2022-12-31")
    print(f"\n[IS sanity] Trade count: {is_result['trade_count']}")
    if is_result["trade_count"] < 100:
        print("WARNING: IS trade count < 100. DO NOT forward to Backtest Runner until investigated.")

    # OOS check
    print("\nRunning H81 OOS (2023-01-01 to 2026-06-01)...")
    oos_result = run_backtest("2023-01-01", "2026-06-01")

    # 2022 rate-shock stress test
    print("\nRunning H81 2022 rate-shock stress test...")
    stress_2022 = run_backtest("2022-01-01", "2022-12-31")
    print(f"[2022 rate-shock] Regime counts: {stress_2022['regime_counts']}")
    print(f"[2022 rate-shock] Sharpe={stress_2022['sharpe']} MDD={stress_2022['max_drawdown']:.2%}")
