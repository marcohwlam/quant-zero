"""
Strategy: H19 VIX-Percentile Volatility-Targeting SPY
Author: Strategy Coder Agent
Date: 2026-03-16
Version: 1.2
Hypothesis: SPY allocation is inversely scaled to VIX regime (3-tier percentile system):
            100% SPY when VIX is calm (<30th pct), 60% SPY in elevated (30-60th pct),
            0% SPY (cash) in high-fear (>60th pct). Mitigation B: VIX 10-day MA crossover
            within elevated tier generates incremental 30% / 60% SPY transitions.
Asset class: equities (ETFs)
Parent task: QUA-201

References:
  - Moreira, A. & Muir, T. (2017). "Volatility-Managed Portfolios." JF 72(4), 1611-1644.
  - Baker, M., Bradley, B., Wurgler, J. (2011). "Benchmarks as Limits to Arbitrage." FAJ 67(1).
  - Sinclair, E. (2013). Volatility Trading (2nd ed.). Wiley.
  - TheTradingParrot TV indicator: Rv3pibXO

IS window:  2018-01-01 to 2022-12-31
OOS window: 2023-01-01 to 2025-12-31

Universe notes:
  - SPY (S&P 500 ETF): launched 1993. Full IS/OOS coverage.
  - VIX (CBOE Volatility Index): available via yfinance ^VIX from 1990.
  - Prices: auto_adjust=True for SPY split/dividend adjustment.
  - Survivorship bias: SPY is a surviving ETF — explicit note: this introduces upward bias
    to absolute return estimates; relative drawdown protection metrics are unaffected.
  - Earnings exclusion: N/A — index ETF; no individual earnings events.

Transaction cost model (canonical, per Engineering Director AGENTS.md):
  - Fixed: $0.005/share
  - Slippage: 0.05% of trade value
  - Market impact: k × sigma × sqrt(Q / ADV), k=0.1
  - Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True

Pre-conditions (per Engineering Director QUA-201 specification):
  1. IS trade count / 4 >= 30/year (at conservative params)
  2. First 2022 cash trigger date <= 2022-01-31

PDT compliance:
  - Primary tier transitions: weekly minimum hold (5 days) — PDT-safe by design.
  - Mitigation B: 2-day minimum hold between intra-tier signal changes.
  - PDT violation window logged if any 5-day rolling window has >3 day-trades.
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    # Asset tickers
    "spy_ticker": "SPY",
    "vix_ticker": "^VIX",
    # Rolling window for VIX percentile rank — sweep: {126, 252, 504}
    "vix_lookback_days": 252,
    # VIX percentile tier boundaries — sweep: tier1 {0.25, 0.30, 0.35}, tier2 {0.55, 0.60, 0.65}
    "tier1_threshold": 0.30,          # calm/elevated boundary (30th pct)
    "tier2_threshold": 0.60,          # elevated/fear boundary (60th pct)
    # SPY allocation per tier
    "calm_allocation_pct": 1.00,       # 100% SPY in calm tier
    "neutral_allocation_pct": 0.60,    # 60% SPY in elevated tier
    "fear_allocation_pct": 0.00,       # 0% SPY in fear tier
    # Mitigation B (intra-tier MA crossover within elevated tier only)
    "vix_ma_days": 10,                 # VIX MA period — sweep: {10, 15}
    "mitigation_b_alloc": 0.30,        # SPY alloc when VIX > MA within elevated tier
    # Rebalancing frequency and minimum holds
    "rebalance_frequency": 5,          # Weekly primary rebalance (every 5 trading days ~ Friday)
    "min_hold_primary_days": 5,        # Min hold between tier-level transitions
    "min_hold_mitb_days": 2,           # Min hold between Mitigation B signal changes
    # Portfolio initial capital
    "init_cash": 25000,
    # Market impact parameters
    "impact_k": 0.1,                   # Square-root market impact coefficient
    "vol_window": 20,                   # Rolling window for sigma / ADV
    "order_qty": 100,                   # Default order size (shares) for impact calc
}

TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ────────────────────────────────────────────────────────────────

def download_data(
    spy_ticker: str, vix_ticker: str, start: str, end: str
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Download SPY adjusted close + volume and VIX close.

    Returns:
        spy_close:  SPY adjusted closing prices (Series)
        spy_volume: SPY daily volume (Series)
        vix_close:  VIX daily close prices (Series)
    """
    # Download SPY with volume (auto_adjust handles splits and dividends)
    spy_raw = yf.download(spy_ticker, start=start, end=end, auto_adjust=True, progress=False)
    if spy_raw.empty:
        raise ValueError(f"No SPY data returned for [{start}, {end}].")
    spy_close = spy_raw["Close"].squeeze()
    spy_volume = spy_raw["Volume"].squeeze()
    spy_close.name = spy_ticker
    spy_volume.name = spy_ticker

    # Download VIX (volume not meaningful for VIX; yfinance provides Close only reliably)
    vix_raw = yf.download(vix_ticker, start=start, end=end, auto_adjust=False, progress=False)
    if vix_raw.empty:
        raise ValueError(f"No VIX data returned for [{start}, {end}].")
    vix_close = vix_raw["Close"].squeeze()
    vix_close.name = "VIX"

    # Align on common trading days (inner join)
    common_idx = spy_close.index.intersection(vix_close.index)
    spy_close = spy_close.reindex(common_idx)
    spy_volume = spy_volume.reindex(common_idx)
    vix_close = vix_close.reindex(common_idx)

    return spy_close, spy_volume, vix_close


# ── Data Quality ────────────────────────────────────────────────────────────────

def check_data_quality(spy_close: pd.Series, vix_close: pd.Series) -> dict:
    """
    Data quality report per Engineering Director pre-backtest checklist.

    Survivorship bias note: SPY is a surviving ETF — upward absolute return bias is present.
    This is unavoidable with a fixed single-asset universe. It does not affect the
    drawdown protection comparison vs buy-and-hold (both series are affected equally).
    """
    report = {
        "survivorship_bias": (
            "SPY is a surviving ETF. Absolute return estimates carry upward survivorship bias. "
            "Risk-reduction vs buy-and-hold metrics are unaffected (both on same SPY series). "
            "Earnings exclusion: N/A — index ETF."
        ),
        "price_adjustment": "SPY: yfinance auto_adjust=True (splits+dividends). VIX: raw close.",
        "earnings_exclusion": "N/A — SPY is an index ETF; no individual earnings events.",
        "vix_source": "^VIX (CBOE Volatility Index via yfinance). Daily close.",
        "tickers": {},
    }

    flagged = []
    for name, series in [("SPY", spy_close), ("VIX", vix_close)]:
        if series.empty:
            report["tickers"][name] = {"error": "Empty price series"}
            flagged.append(name)
            continue
        s = series.dropna()
        expected = pd.bdate_range(start=s.index.min(), end=s.index.max())
        missing = len(expected.difference(s.index))
        report["tickers"][name] = {
            "total_days": len(s),
            "missing_business_days": missing,
            "gap_flag": missing > 5,
            "start": str(s.index.min().date()),
            "end": str(s.index.max().date()),
        }
        if missing > 5:
            flagged.append(name)
            warnings.warn(
                f"Data gap flag: {name} has {missing} missing business days (>5 threshold).",
                stacklevel=2,
            )

    report["flagged_tickers"] = flagged
    return report


# ── VIX Percentile Computation ──────────────────────────────────────────────────

def compute_vix_percentile(vix: pd.Series, lookback: int) -> pd.Series:
    """
    Compute rolling VIX percentile rank within a trailing window of `lookback` days.

    vix_pct[t] = (# of days in vix[t-lookback:t] where vix[i] <= vix[t]) / lookback

    Strictly backward-looking — no look-ahead bias.
    Returns NaN for the first `lookback` observations (insufficient history).
    """
    def rank_pct(window):
        # Percentile rank: fraction of past values <= current (last element)
        current = window[-1]
        return np.sum(window <= current) / len(window)

    return vix.rolling(window=lookback, min_periods=lookback).apply(rank_pct, raw=True)


# ── Signal Computation ──────────────────────────────────────────────────────────

def _get_friday_rebalance_dates(index: pd.DatetimeIndex, start: str, end: str) -> list:
    """
    Return sorted list of Friday (or last trading day of week) rebalance dates
    within [start, end] that are present in the price index.
    """
    date_range = index[(index >= start) & (index <= end)]
    calendar_fridays = pd.date_range(start=start, end=end, freq="W-FRI")

    rebalance_dates = []
    for friday in calendar_fridays:
        week_start = friday - pd.Timedelta(days=4)
        week_dates = date_range[(date_range >= week_start) & (date_range <= friday)]
        if len(week_dates) > 0:
            rebalance_dates.append(week_dates[-1])

    return sorted(set(rebalance_dates))


def compute_allocation_series(
    spy_close: pd.Series,
    vix_close: pd.Series,
    params: dict,
) -> pd.DataFrame:
    """
    Compute the daily SPY allocation series implementing the full H19 signal logic:

      Primary signal (checked at weekly Friday close):
        - vix_pct < tier1  → calm tier   → 100% SPY
        - tier1 <= vix_pct <= tier2 → elevated tier → 60% SPY (default)
        - vix_pct > tier2  → fear tier   → 0% SPY (cash)

      Secondary signal — Mitigation B (evaluated daily, only in elevated tier):
        - VIX crosses above 10d MA → reduce to mitigation_b_alloc (30%)
        - VIX crosses below 10d MA → restore to neutral_allocation_pct (60%)

      Hold rules:
        - min_hold_primary_days (5d): minimum time between primary tier transitions
        - min_hold_mitb_days (2d): minimum time between Mitigation B changes

    Returns:
        DataFrame indexed by trading day with columns:
          - allocation:        float (SPY weight, 0.0 to 1.0)
          - vix_pct:           float (rolling VIX percentile)
          - tier:              str ('calm', 'elevated', 'fear', or 'warmup')
          - mitigation_b:      bool (True if Mitigation B is reducing allocation)
          - vix_ma:            float (VIX 10-day MA)
          - vix_above_ma:      bool (VIX close > VIX 10-day MA)
    """
    lookback = params["vix_lookback_days"]
    tier1 = params["tier1_threshold"]
    tier2 = params["tier2_threshold"]
    calm_alloc = params["calm_allocation_pct"]
    neutral_alloc = params["neutral_allocation_pct"]
    fear_alloc = params["fear_allocation_pct"]
    mitb_alloc = params["mitigation_b_alloc"]
    vix_ma_days = params["vix_ma_days"]
    min_hold_primary = params["min_hold_primary_days"]
    min_hold_mitb = params["min_hold_mitb_days"]

    # VIX percentile (rolling, backward-looking)
    vix_pct = compute_vix_percentile(vix_close, lookback)

    # VIX 10-day MA for Mitigation B
    vix_ma = vix_close.rolling(vix_ma_days, min_periods=vix_ma_days).mean()
    vix_above_ma = vix_close > vix_ma

    # Pre-compute Friday rebalance dates for the entire data range
    all_dates = spy_close.index
    friday_dates = set(
        _get_friday_rebalance_dates(all_dates, str(all_dates[0].date()), str(all_dates[-1].date()))
    )

    # Build allocation day-by-day
    n = len(all_dates)
    allocations = np.full(n, np.nan)
    tiers = np.array(["warmup"] * n, dtype=object)
    mitb_flags = np.zeros(n, dtype=bool)

    # State variables
    current_alloc = fear_alloc          # Start in warmup/cash (no valid signal yet)
    current_tier = "warmup"
    current_mitb = False
    last_primary_change_idx = -min_hold_primary   # Allow immediate first signal
    last_mitb_change_idx = -min_hold_mitb

    for i, date in enumerate(all_dates):
        pct = vix_pct.iloc[i]

        # Not enough history for a valid signal
        if pd.isna(pct):
            allocations[i] = fear_alloc    # Hold cash during warmup
            tiers[i] = "warmup"
            mitb_flags[i] = False
            continue

        # ── Primary tier determination (evaluated on Friday rebalance dates) ──
        if date in friday_dates:
            days_since_primary = i - last_primary_change_idx

            if pct < tier1:
                target_tier = "calm"
                target_alloc = calm_alloc
            elif pct <= tier2:
                target_tier = "elevated"
                target_alloc = neutral_alloc
            else:
                target_tier = "fear"
                target_alloc = fear_alloc

            # Apply minimum hold — only change tier if hold period elapsed
            if target_tier != current_tier and days_since_primary >= min_hold_primary:
                current_tier = target_tier
                current_alloc = target_alloc
                current_mitb = False     # Reset Mitigation B on tier change
                last_primary_change_idx = i

        # ── Mitigation B signal (daily, only within elevated tier) ──
        if current_tier == "elevated":
            days_since_mitb = i - last_mitb_change_idx
            above_ma = bool(vix_above_ma.iloc[i]) if not pd.isna(vix_ma.iloc[i]) else False

            if above_ma and not current_mitb and days_since_mitb >= min_hold_mitb:
                # VIX crosses above MA → reduce to mitigation_b_alloc
                current_mitb = True
                current_alloc = mitb_alloc
                last_mitb_change_idx = i
            elif not above_ma and current_mitb and days_since_mitb >= min_hold_mitb:
                # VIX crosses below MA → restore to neutral_alloc
                current_mitb = False
                current_alloc = neutral_alloc
                last_mitb_change_idx = i
        else:
            current_mitb = False

        allocations[i] = current_alloc
        tiers[i] = current_tier
        mitb_flags[i] = current_mitb

    result = pd.DataFrame({
        "allocation": allocations,
        "vix_pct": vix_pct.values,
        "tier": tiers,
        "mitigation_b": mitb_flags,
        "vix_ma": vix_ma.values,
        "vix_above_ma": vix_above_ma.values,
    }, index=all_dates)

    return result


# ── Pre-Condition Verification ──────────────────────────────────────────────────

def verify_preconditions(
    signals: pd.DataFrame,
    is_start: str = "2018-01-01",
    is_end: str = "2022-12-31",
) -> dict:
    """
    Pre-condition checks per QUA-201 specification:
      1. IS trade count / 4 >= 30/year
      2. First 2022 cash trigger (tier == 'fear') <= 2022-01-31
    """
    is_signals = signals.loc[is_start:is_end].copy()

    # Count allocation changes as trades
    alloc_changes = is_signals["allocation"].diff().abs()
    trade_count = int((alloc_changes > 1e-9).sum())
    years = (pd.Timestamp(is_end) - pd.Timestamp(is_start)).days / 365.25
    annual_rate = trade_count / years if years > 0 else 0

    tc_pass = annual_rate >= 30
    if not tc_pass:
        warnings.warn(
            f"PF-1 FAIL: IS trade count = {trade_count} ({annual_rate:.1f}/year) — "
            f"below 30/year threshold. Strategy may have insufficient signal granularity.",
            stacklevel=2,
        )

    # First 2022 cash trigger
    year_2022 = signals.loc["2022-01-01":"2022-12-31"]
    fear_days_2022 = year_2022[year_2022["tier"] == "fear"]
    if fear_days_2022.empty:
        first_cash_trigger = None
        trigger_pass = False
        warnings.warn(
            "PF-4 WARNING: No fear-tier (cash) signal detected in 2022. "
            "Strategy may not defend against 2022 rate shock.",
            stacklevel=2,
        )
    else:
        first_cash_trigger = fear_days_2022.index[0]
        trigger_pass = first_cash_trigger <= pd.Timestamp("2022-01-31")
        if not trigger_pass:
            warnings.warn(
                f"PF-4 WARNING: First 2022 cash trigger = {first_cash_trigger.date()} — "
                f"after 2022-01-31 threshold. VIX gating may not provide early enough protection.",
                stacklevel=2,
            )

    return {
        "is_trade_count": trade_count,
        "is_annual_trade_rate": round(annual_rate, 1),
        "pf1_pass": tc_pass,
        "pf1_threshold": 30,
        "first_2022_cash_trigger": str(first_cash_trigger.date()) if first_cash_trigger else None,
        "pf4_pass": trigger_pass,
        "pf4_threshold": "2022-01-31",
    }


# ── PDT Compliance Check ────────────────────────────────────────────────────────

def check_pdt_compliance(signals: pd.DataFrame) -> dict:
    """
    Check for PDT violations: no more than 3 day-trades in any 5-trading-day window.
    A day-trade is counted when allocation changes (entry + exit) within the same
    5-day window. Conservative: count each allocation change as a potential day-trade.

    Returns a dict with violation windows (if any) and overall PDT pass/fail.
    """
    alloc = signals["allocation"]
    changes = (alloc.diff().abs() > 1e-9).astype(int)

    # Rolling 5-day window sum of changes — flag if > 3
    rolling_changes = changes.rolling(5).sum()
    violation_dates = rolling_changes[rolling_changes > 3].index.tolist()

    return {
        "pdt_pass": len(violation_dates) == 0,
        "violation_windows": [str(d.date()) for d in violation_dates],
        "max_trades_in_5d": int(rolling_changes.max()) if not rolling_changes.empty else 0,
    }


# ── Transaction Cost & Trade Log ────────────────────────────────────────────────

def build_trade_log(
    signals: pd.DataFrame,
    spy_close: pd.Series,
    spy_volume: pd.Series,
    params: dict,
    init_cash: float,
) -> pd.DataFrame:
    """
    Build a trade log from the allocation series.

    A "trade" occurs whenever the allocation changes, triggering a buy or sell of SPY.
    Shares are computed from the portfolio value at the time of the trade.

    Columns:
        trade_id, entry_date, exit_date, entry_price, exit_price, shares,
        allocation_pct, tier, mitigation_b_active, pnl, costs, net_pnl, liquidity_constrained
    """
    k = params["impact_k"]
    vol_window = params["vol_window"]

    # 20-day rolling sigma (daily return std) and ADV (dollar volume)
    spy_returns = spy_close.pct_change()
    sigma = spy_returns.rolling(vol_window, min_periods=vol_window).std()
    adv_shares = spy_volume.rolling(vol_window, min_periods=vol_window).mean()  # shares ADV

    alloc = signals["allocation"].reindex(spy_close.index).ffill()
    tier_col = signals["tier"].reindex(spy_close.index).ffill()
    mitb_col = signals["mitigation_b"].reindex(spy_close.index).ffill()

    trades = []
    portfolio_value = init_cash

    # Identify allocation change points
    change_mask = alloc.diff().abs() > 1e-9
    change_mask.iloc[0] = alloc.iloc[0] > 0   # Treat first non-zero allocation as entry

    prev_alloc = 0.0
    prev_entry_date = None
    prev_entry_price = None
    prev_shares = 0.0
    prev_tier = "warmup"
    prev_mitb = False
    trade_id = 0

    for date, row in signals.iterrows():
        if date not in spy_close.index:
            continue

        cur_alloc = alloc.get(date, 0.0)
        if pd.isna(cur_alloc):
            cur_alloc = 0.0
        price = float(spy_close.get(date, np.nan))
        if pd.isna(price):
            continue

        # Check for allocation change
        if abs(cur_alloc - prev_alloc) > 1e-9:
            # Close previous position if held
            if prev_shares > 0 and prev_entry_date is not None:
                # Compute costs for closing trade
                q_close = prev_shares
                sig_val = float(sigma.get(date, 0.0)) if not pd.isna(sigma.get(date, np.nan)) else 0.0
                adv_val = float(adv_shares.get(date, 0.0)) if not pd.isna(adv_shares.get(date, np.nan)) else 1.0
                if adv_val <= 0:
                    adv_val = 1.0
                impact = k * sig_val * np.sqrt(q_close / adv_val)
                fixed_cost = 0.005 * q_close       # $0.005/share
                slippage_cost = 0.0005 * price * q_close   # 0.05%
                total_cost = fixed_cost + slippage_cost + impact * price * q_close
                pnl_gross = (price - prev_entry_price) * prev_shares
                net_pnl = pnl_gross - total_cost
                portfolio_value += net_pnl
                liq_constrained = (q_close / adv_val) > 0.01 if adv_val > 0 else False

                trades.append({
                    "trade_id": trade_id,
                    "entry_date": str(prev_entry_date.date()),
                    "exit_date": str(date.date()),
                    "entry_price": round(prev_entry_price, 4),
                    "exit_price": round(price, 4),
                    "shares": round(prev_shares, 2),
                    "allocation_pct": round(prev_alloc, 4),
                    "tier": prev_tier,
                    "mitigation_b_active": bool(prev_mitb),
                    "pnl": round(pnl_gross, 2),
                    "costs": round(total_cost, 2),
                    "net_pnl": round(net_pnl, 2),
                    "liquidity_constrained": bool(liq_constrained),
                })
                trade_id += 1

            # Open new position if allocation > 0
            if cur_alloc > 0:
                new_value = portfolio_value * cur_alloc
                prev_shares = new_value / price if price > 0 else 0.0
                prev_entry_date = date
                prev_entry_price = price
                prev_alloc = cur_alloc
                prev_tier = str(tier_col.get(date, "unknown"))
                prev_mitb = bool(mitb_col.get(date, False))

                # Liquidity flag for entry
                sig_val = float(sigma.get(date, 0.0)) if not pd.isna(sigma.get(date, np.nan)) else 0.0
                adv_val = float(adv_shares.get(date, 0.0)) if not pd.isna(adv_shares.get(date, np.nan)) else 1.0
                if adv_val <= 0:
                    adv_val = 1.0
                if (prev_shares / adv_val) > 0.01:
                    warnings.warn(
                        f"Liquidity-constrained entry on {date.date()}: "
                        f"order {prev_shares:.0f} shares = {100 * prev_shares/adv_val:.2f}% of ADV.",
                        stacklevel=2,
                    )
            else:
                prev_shares = 0.0
                prev_alloc = 0.0
                prev_entry_date = None
                prev_entry_price = None

    # Close any remaining open position at last price
    if prev_shares > 0 and prev_entry_date is not None:
        last_date = spy_close.index[-1]
        price = float(spy_close.iloc[-1])
        q_close = prev_shares
        sig_val = float(sigma.iloc[-1]) if not pd.isna(sigma.iloc[-1]) else 0.0
        adv_val = float(adv_shares.iloc[-1]) if not pd.isna(adv_shares.iloc[-1]) else 1.0
        if adv_val <= 0:
            adv_val = 1.0
        impact = k * sig_val * np.sqrt(q_close / adv_val)
        fixed_cost = 0.005 * q_close
        slippage_cost = 0.0005 * price * q_close
        total_cost = fixed_cost + slippage_cost + impact * price * q_close
        pnl_gross = (price - prev_entry_price) * prev_shares
        net_pnl = pnl_gross - total_cost
        liq_constrained = (q_close / adv_val) > 0.01

        trades.append({
            "trade_id": trade_id,
            "entry_date": str(prev_entry_date.date()),
            "exit_date": str(last_date.date()),
            "entry_price": round(prev_entry_price, 4),
            "exit_price": round(price, 4),
            "shares": round(prev_shares, 2),
            "allocation_pct": round(prev_alloc, 4),
            "tier": prev_tier,
            "mitigation_b_active": bool(prev_mitb),
            "pnl": round(pnl_gross, 2),
            "costs": round(total_cost, 2),
            "net_pnl": round(net_pnl, 2),
            "liquidity_constrained": bool(liq_constrained),
        })

    return pd.DataFrame(trades)


# ── Strategy Metrics ────────────────────────────────────────────────────────────

def compute_metrics(trade_log: pd.DataFrame, spy_close: pd.Series, init_cash: float) -> dict:
    """
    Compute summary strategy performance metrics from the trade log.
    """
    if trade_log.empty:
        return {
            "total_return": 0.0,
            "sharpe": np.nan,
            "max_drawdown": np.nan,
            "win_rate": np.nan,
            "trade_count": 0,
            "total_costs": 0.0,
            "net_pnl": 0.0,
        }

    total_pnl = trade_log["net_pnl"].sum()
    total_costs = trade_log["costs"].sum()
    total_return = total_pnl / init_cash

    wins = (trade_log["net_pnl"] > 0).sum()
    win_rate = wins / len(trade_log) if len(trade_log) > 0 else np.nan

    # Reconstruct cumulative equity curve from trade log for Sharpe / MDD
    # Simple approximation: equity = init_cash + cumulative net_pnl per exit date
    trade_log_sorted = trade_log.copy()
    trade_log_sorted["exit_date"] = pd.to_datetime(trade_log_sorted["exit_date"])
    trade_log_sorted = trade_log_sorted.sort_values("exit_date")
    equity = init_cash + trade_log_sorted["net_pnl"].cumsum()

    # MDD from equity curve
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    max_drawdown = float(drawdown.min())

    # Daily returns approximation (between exit dates)
    equity_series = equity.values
    if len(equity_series) > 1:
        daily_rets = np.diff(equity_series) / equity_series[:-1]
        sharpe = (daily_rets.mean() / (daily_rets.std() + 1e-12)) * np.sqrt(TRADING_DAYS_PER_YEAR)
    else:
        sharpe = np.nan

    return {
        "total_return": round(total_return, 4),
        "sharpe": round(float(sharpe), 4) if not np.isnan(sharpe) else np.nan,
        "max_drawdown": round(max_drawdown, 4),
        "win_rate": round(float(win_rate), 4),
        "trade_count": int(len(trade_log)),
        "total_costs": round(float(total_costs), 2),
        "net_pnl": round(float(total_pnl), 2),
    }


# ── Main Entry Point ────────────────────────────────────────────────────────────

def run_strategy(
    start: str = "2017-01-01",   # Extra year before IS for VIX percentile warmup
    end: str = "2022-12-31",
    is_start: str = "2018-01-01",
    is_end: str = "2022-12-31",
    params: dict = None,
) -> dict:
    """
    Full H19 strategy run: download data, generate signals, build trade log,
    verify pre-conditions, check PDT compliance, return metrics dict.

    Args:
        start:    Data download start (earlier than is_start for VIX percentile warmup).
        end:      Data download end.
        is_start: In-sample start for pre-condition checks.
        is_end:   In-sample end.
        params:   Parameter override dict (uses PARAMETERS defaults if None).

    Returns:
        dict with keys: metrics, preconditions, pdt, trade_log (first 10 rows), data_quality.
    """
    if params is None:
        params = PARAMETERS.copy()

    print(f"[H19] Downloading data: SPY + VIX | {start} → {end}")
    spy_close, spy_volume, vix_close = download_data(
        params["spy_ticker"], params["vix_ticker"], start, end
    )

    # Data quality check
    dq_report = check_data_quality(spy_close, vix_close)
    if dq_report["flagged_tickers"]:
        warnings.warn(
            f"[H19] Data quality flags: {dq_report['flagged_tickers']}", stacklevel=2
        )

    print(f"[H19] Computing VIX percentile (lookback={params['vix_lookback_days']}d) + allocation signals...")
    signals = compute_allocation_series(spy_close, vix_close, params)

    print("[H19] Running pre-condition verification...")
    preconditions = verify_preconditions(signals, is_start=is_start, is_end=is_end)
    print(
        f"  PF-1: trade count = {preconditions['is_trade_count']} "
        f"({preconditions['is_annual_trade_rate']}/yr) — "
        f"{'PASS' if preconditions['pf1_pass'] else 'FAIL'}"
    )
    print(
        f"  PF-4: first 2022 cash trigger = {preconditions['first_2022_cash_trigger']} — "
        f"{'PASS' if preconditions['pf4_pass'] else 'FAIL'}"
    )

    print("[H19] Checking PDT compliance...")
    is_signals = signals.loc[is_start:is_end]
    pdt_report = check_pdt_compliance(is_signals)
    if not pdt_report["pdt_pass"]:
        warnings.warn(
            f"[H19] PDT compliance issue: {len(pdt_report['violation_windows'])} "
            f"potential violation windows detected. Max trades in 5d: {pdt_report['max_trades_in_5d']}.",
            stacklevel=2,
        )

    print("[H19] Building trade log...")
    trade_log = build_trade_log(signals, spy_close, spy_volume, params, params["init_cash"])

    metrics = compute_metrics(trade_log, spy_close, params["init_cash"])

    print(f"[H19] Done. Sharpe={metrics['sharpe']}, Return={metrics['total_return']:.1%}, "
          f"MaxDD={metrics['max_drawdown']:.1%}, Trades={metrics['trade_count']}")

    return {
        "metrics": metrics,
        "preconditions": preconditions,
        "pdt": pdt_report,
        "data_quality": dq_report,
        "trade_log_head": trade_log.head(10).to_dict("records"),
        "trade_log_full": trade_log,
    }


if __name__ == "__main__":
    result = run_strategy(
        start="2017-01-01",    # 1 year warmup before IS for VIX percentile
        end="2022-12-31",
        is_start="2018-01-01",
        is_end="2022-12-31",
    )
    print("\n=== H19 VIX Volatility Targeting — IS Results ===")
    print("Metrics:", result["metrics"])
    print("Pre-conditions:", result["preconditions"])
    print("PDT:", result["pdt"])
    print("Trade log (first 10):")
    for t in result["trade_log_head"]:
        print(" ", t)
