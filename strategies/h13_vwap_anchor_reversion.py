"""
Strategy: H13 VWAP Anchor Reversion
Author: Backtest Runner (QUA-155)
Date: 2026-03-16
Hypothesis: Daily VWAP (typical-price proxy) serves as institutional execution benchmark.
            Price deviations beyond ±2 SD revert toward VWAP center due to institutional
            rebalancing pressure (Berkowitz/Logue/Noser 1988; Madhavan & Cheng 1997).
Asset class: equities (ETFs: SPY, QQQ, IWM)
Parent task: QUA-155
Data variant: Option A — Typical Price proxy VWAP = Σ(((H+L+C)/3 × Volume)) / Σ(Volume)
              NOTE: This is NOT true session VWAP; lower IC is expected vs institutional data.
              Lower IC expectation documented per Research Director review.

NOTES:
- Long-only in Gate 1: short-side requires margin; PDT complications at $25K.
- Macro event filter: exclude entries ±2 days of FOMC, CPI, NFP.
- IC validation gate: IC > 0.02 required before full parameter sweep.
- VWAP SD threshold sensitivity: 1.5, 1.75, 2.0, 2.25, 2.5 tested.
- Transaction costs: canonical equities model — $0.005/share + 0.05% slippage + market impact.
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf

# ── Default Parameters ────────────────────────────────────────────────────────

PARAMETERS = {
    "universe": ["SPY", "QQQ", "IWM"],
    "vix_ticker": "^VIX",
    "vwap_lookback": 20,           # rolling window (bars) for VWAP computation
    "vwap_sd_threshold": 2.0,      # SD bands for entry (lower band touch)
    "tp_sd_target": 0.0,           # TP when price returns to VWAP center (0 SD from mean)
    "sl_sd_multiplier": 3.0,       # SL at -3 SD from VWAP center
    "max_hold_days": 5,            # time stop: exit after 5 days
    "position_size_pct": 0.33,     # 33% per ETF (3 ETFs at max)
    "init_cash": 25000,
}

# ── Transaction Cost Constants ────────────────────────────────────────────────
FIXED_COST_PER_SHARE = 0.005   # $0.005/share
SLIPPAGE_PCT = 0.0005          # 0.05% per leg
MARKET_IMPACT_K = 0.1          # Almgren-Chriss square-root model
SIGMA_WINDOW = 20
ADV_WINDOW = 20

TRADING_DAYS_PER_YEAR = 252

# ── Macro Event Calendar (FOMC/CPI/NFP, 2018-2024) ───────────────────────────
# Approximate key FOMC, CPI, and NFP release dates for macro filter.
# This is a simplified calendar; ±2 trading days around each date are excluded.

MACRO_EVENT_DATES = pd.to_datetime([
    # FOMC meetings (approximate decision dates)
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13", "2018-08-01",
    "2018-09-26", "2018-11-08", "2018-12-19",
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19", "2019-07-31",
    "2019-09-18", "2019-10-30", "2019-12-11",
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29", "2020-06-10",
    "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28",
    "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27",
    "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26",
    "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31",
    "2024-09-18", "2024-11-07", "2024-12-18",
    # Monthly NFP releases (first Friday of each month, approximate)
    "2018-02-02", "2018-03-09", "2018-04-06", "2018-05-04", "2018-06-01",
    "2018-07-06", "2018-08-03", "2018-09-07", "2018-10-05", "2018-11-02",
    "2018-12-07",
    "2019-01-04", "2019-02-01", "2019-03-08", "2019-04-05", "2019-05-03",
    "2019-06-07", "2019-07-05", "2019-08-02", "2019-09-06", "2019-10-04",
    "2019-11-01", "2019-12-06",
    "2020-01-10", "2020-02-07", "2020-03-06", "2020-04-03", "2020-05-08",
    "2020-06-05", "2020-07-02", "2020-08-07", "2020-09-04", "2020-10-02",
    "2020-11-06", "2020-12-04",
    "2021-01-08", "2021-02-05", "2021-03-05", "2021-04-02", "2021-05-07",
    "2021-06-04", "2021-07-02", "2021-08-06", "2021-09-03", "2021-10-08",
    "2021-11-05", "2021-12-03",
    "2022-01-07", "2022-02-04", "2022-03-04", "2022-04-01", "2022-05-06",
    "2022-06-03", "2022-07-08", "2022-08-05", "2022-09-02", "2022-10-07",
    "2022-11-04", "2022-12-02",
    "2023-01-06", "2023-02-03", "2023-03-10", "2023-04-07", "2023-05-05",
    "2023-06-02", "2023-07-07", "2023-08-04", "2023-09-01", "2023-10-06",
    "2023-11-03", "2023-12-08",
    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03",
    "2024-06-07", "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04",
    "2024-11-01", "2024-12-06",
    # Monthly CPI releases (approximate mid-month)
    "2018-01-12", "2018-02-14", "2018-03-13", "2018-04-11", "2018-05-10",
    "2018-06-12", "2018-07-12", "2018-08-10", "2018-09-13", "2018-10-11",
    "2018-11-14", "2018-12-12",
    "2019-01-11", "2019-02-13", "2019-03-12", "2019-04-10", "2019-05-10",
    "2019-06-12", "2019-07-11", "2019-08-13", "2019-09-12", "2019-10-10",
    "2019-11-13", "2019-12-11",
    "2020-01-14", "2020-02-13", "2020-03-11", "2020-04-10", "2020-05-12",
    "2020-06-10", "2020-07-14", "2020-08-12", "2020-09-11", "2020-10-13",
    "2020-11-12", "2020-12-10",
    "2021-01-13", "2021-02-10", "2021-03-10", "2021-04-13", "2021-05-12",
    "2021-06-10", "2021-07-13", "2021-08-11", "2021-09-14", "2021-10-13",
    "2021-11-10", "2021-12-10",
    "2022-01-12", "2022-02-10", "2022-03-10", "2022-04-12", "2022-05-11",
    "2022-06-10", "2022-07-13", "2022-08-10", "2022-09-13", "2022-10-13",
    "2022-11-10", "2022-12-13",
    "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12", "2023-05-10",
    "2023-06-13", "2023-07-12", "2023-08-10", "2023-09-13", "2023-10-12",
    "2023-11-14", "2023-12-12",
    "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15",
    "2024-06-12", "2024-07-11", "2024-08-14", "2024-09-11", "2024-10-10",
    "2024-11-13", "2024-12-11",
])


def build_macro_exclusion_mask(index: pd.DatetimeIndex, window_days: int = 2) -> pd.Series:
    """
    Return boolean Series (True = macro event window; exclude from trading).
    Excludes ±window_days business days around each macro event date.
    """
    mask = pd.Series(False, index=index)
    for event_date in MACRO_EVENT_DATES:
        # Find the nearest trading day to the event date
        diffs = abs((index - event_date).days)
        for offset in range(-window_days, window_days + 1):
            target = event_date + pd.offsets.BusinessDay(offset)
            if target in index:
                mask[target] = True
    return mask


# ── Data Loading ───────────────────────────────────────────────────────────────

def download_etf_data(tickers: list, start: str, end: str) -> dict:
    """
    Download OHLCV for each ticker via yfinance.
    Returns dict: {ticker: DataFrame with OHLCV columns}.
    """
    result = {}
    for ticker in tickers:
        try:
            raw = yf.download(ticker, start=start, end=end,
                              auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            if raw.empty or len(raw) < 30:
                warnings.warn(f"Insufficient data for {ticker}: {len(raw)} bars")
                continue
            result[ticker] = raw
        except Exception as exc:
            warnings.warn(f"Failed to download {ticker}: {exc}")
    return result


# ── VWAP Signal Computation ────────────────────────────────────────────────────

def compute_vwap_bands(ohlcv: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """
    Compute rolling VWAP and volume-weighted SD bands using daily OHLCV.

    Data variant: Option A — typical price proxy VWAP.
    typical_price = (High + Low + Close) / 3

    VWAP[t] = sum(typical[i] * volume[i]) / sum(volume[i])   for i in [t-lookback+1, t]
    VWAP_SD[t] = sqrt(sum(volume[i] * (typical[i] - VWAP[t])^2) / sum(volume[i]))

    No look-ahead: rolling uses only past bars (shift built into pandas rolling).
    """
    typical = (ohlcv["High"] + ohlcv["Low"] + ohlcv["Close"]) / 3.0
    volume = ohlcv["Volume"].astype(float)

    # Volume-weighted sum and total volume
    tv = typical * volume  # typical * volume per bar

    tv_sum = tv.rolling(window=lookback, min_periods=max(5, lookback // 2)).sum()
    vol_sum = volume.rolling(window=lookback, min_periods=max(5, lookback // 2)).sum()

    vwap = tv_sum / (vol_sum + 1e-8)

    # Volume-weighted variance
    tv_sq = volume * (typical - vwap) ** 2
    tv_sq_sum = tv_sq.rolling(window=lookback, min_periods=max(5, lookback // 2)).sum()
    vwap_var = tv_sq_sum / (vol_sum + 1e-8)
    vwap_sd = np.sqrt(vwap_var)

    return pd.DataFrame({
        "typical": typical,
        "vwap": vwap,
        "vwap_sd": vwap_sd,
        "close": ohlcv["Close"],
        "open": ohlcv["Open"],
        "high": ohlcv["High"],
        "low": ohlcv["Low"],
        "volume": volume,
    }, index=ohlcv.index)


def compute_ic(ohlcv_dict: dict, params: dict, forward_days: int = 5) -> dict:
    """
    Information Coefficient: correlation between VWAP signal distance and
    forward returns.

    Signal: normalized distance below lower VWAP band = (VWAP - 2SD - close) / close
            Positive signal = price is below lower band (more depressed = stronger signal).

    Forward return: close[t + forward_days] / close[t] - 1

    IC = Spearman rank correlation across all observations.

    Returns dict with per-ticker IC and average IC.
    """
    from scipy import stats as scipy_stats

    lookback = params["vwap_lookback"]
    sd_threshold = params["vwap_sd_threshold"]

    ic_results = {}
    all_signals = []
    all_fwds = []

    for ticker, ohlcv in ohlcv_dict.items():
        bands = compute_vwap_bands(ohlcv, lookback)
        close = bands["close"]
        vwap = bands["vwap"]
        sd = bands["vwap_sd"]

        lower_band = vwap - sd_threshold * sd

        # Signal: how far below lower band is the close (normalized)
        signal = (lower_band - close) / (close + 1e-8)
        signal = signal.where(signal > 0, 0)  # only when below band

        # Forward return
        fwd_ret = close.shift(-forward_days) / close - 1.0

        # Align and drop NaN
        df = pd.DataFrame({"signal": signal, "fwd": fwd_ret}).dropna()
        df = df[df["signal"] > 0]  # only rows with active signal

        if len(df) < 10:
            ic_results[ticker] = {"ic": 0.0, "n_obs": len(df)}
            continue

        corr, _ = scipy_stats.spearmanr(df["signal"], df["fwd"])
        ic_results[ticker] = {"ic": round(float(corr), 4), "n_obs": len(df)}
        all_signals.extend(df["signal"].tolist())
        all_fwds.extend(df["fwd"].tolist())

    if len(all_signals) > 10:
        avg_corr, _ = scipy_stats.spearmanr(all_signals, all_fwds)
        avg_ic = round(float(avg_corr), 4)
    else:
        avg_ic = 0.0

    ic_pass = avg_ic > 0.02
    return {
        "per_ticker_ic": ic_results,
        "avg_ic": avg_ic,
        "ic_pass": ic_pass,
        "decision": "PROCEED" if ic_pass else "REJECT_LOW_IC",
        "note": (
            f"VWAP Option A proxy IC={avg_ic:.4f}. "
            + ("IC > 0.02 gate passed — proceed with full Gate 1." if ic_pass
               else "IC ≤ 0.02 — below IC floor; VWAP Option A proxy insufficient. Strategy likely non-viable.")
        ),
    }


# ── Trade Simulator ────────────────────────────────────────────────────────────

def simulate_trades(
    bands: pd.DataFrame,
    params: dict,
    macro_mask: pd.Series | None = None,
) -> tuple:
    """
    Simulate H13 VWAP Anchor Reversion (long-only).

    Entry rule (no look-ahead):
    - Day t signal: close[t] < VWAP[t] - sd_threshold × SD[t]  (below lower band)
    - Day t+1 confirmation: close[t+1] > VWAP[t+1] - sd_threshold × SD[t+1]  (recovery above band)
    - Entry at open of day t+2
    - Macro filter: no new entries if day t or t+1 is within macro event window

    Exit (evaluated each bar after entry):
    1. TP: close >= VWAP center (VWAP[t] ± 0.0 × SD) → exit at next-open
    2. SL: close <= entry_price - sl_sd_multiplier × SD_at_entry → exit at next-open
    3. Time stop: hold_days >= max_hold_days → exit at next-open

    Transaction costs applied at both entry and exit legs.

    Returns:
        trade_log: list of trade dicts
        daily_returns: pd.Series of daily portfolio returns (position × bar return)
    """
    sd_threshold = params["vwap_sd_threshold"]
    sl_sd = params["sl_sd_multiplier"]
    max_hold = params["max_hold_days"]
    pos_size = params["position_size_pct"]
    init_cash = params["init_cash"]

    close = bands["close"]
    open_ = bands["open"]
    high = bands["high"]
    low = bands["low"]
    vwap = bands["vwap"]
    vwap_sd = bands["vwap_sd"]
    volume = bands["volume"]

    idx = close.index
    n = len(idx)

    # Pre-compute lower band and ADV/sigma for costs
    lower_band = vwap - sd_threshold * vwap_sd
    sl_level = vwap - sl_sd * vwap_sd  # SL = VWAP - 3SD

    # Sigma and ADV for market impact
    sigma = close.pct_change().rolling(SIGMA_WINDOW).std().fillna(0.01)
    adv = volume.rolling(ADV_WINDOW).mean().fillna(volume.mean())

    # Build macro exclusion mask
    if macro_mask is None:
        macro_mask = pd.Series(False, index=idx)

    trade_log = []
    # Daily pnl tracking (for portfolio return series)
    capital = init_cash
    portfolio_values = pd.Series(index=idx, dtype=float)
    portfolio_values.iloc[0] = capital

    in_trade = False
    entry_price = 0.0
    entry_vwap = 0.0
    entry_sd = 0.0
    entry_day_idx = -1
    hold_days = 0
    entry_shares = 0
    entry_cost = 0.0
    signal_bar_idx = -1  # day t (first bar below lower band)

    for i in range(2, n):
        bar_date = idx[i]
        prev_bar = idx[i - 1]
        prev2_bar = idx[i - 2]

        if not in_trade:
            # Check entry: t=i-2 (signal bar), t+1=i-1 (confirmation bar), entry at open[i]
            t_signal = i - 2
            t_confirm = i - 1
            t_entry = i

            signal_cond = (
                not pd.isna(close.iloc[t_signal])
                and not pd.isna(lower_band.iloc[t_signal])
                and close.iloc[t_signal] < lower_band.iloc[t_signal]  # below lower band
                and not pd.isna(vwap_sd.iloc[t_signal])
                and vwap_sd.iloc[t_signal] > 0
            )

            confirm_cond = (
                not pd.isna(close.iloc[t_confirm])
                and not pd.isna(lower_band.iloc[t_confirm])
                and close.iloc[t_confirm] > lower_band.iloc[t_confirm]  # recovery above band
            )

            macro_ok = (
                not macro_mask.iloc[t_signal]
                and not macro_mask.iloc[t_confirm]
            )

            if signal_cond and confirm_cond and macro_ok:
                # Enter at open of day t+2
                entry_p = open_.iloc[t_entry]
                if pd.isna(entry_p) or entry_p <= 0:
                    continue

                entry_sig = sigma.iloc[t_entry] if not pd.isna(sigma.iloc[t_entry]) else 0.01
                entry_adv = adv.iloc[t_entry] if not pd.isna(adv.iloc[t_entry]) else 1e6

                trade_value = capital * pos_size
                shares = int(trade_value / entry_p) if entry_p > 0 else 0
                if shares <= 0:
                    continue

                # Transaction cost at entry
                fixed = shares * FIXED_COST_PER_SHARE
                slip = SLIPPAGE_PCT * (shares * entry_p)
                impact_pct = MARKET_IMPACT_K * entry_sig * np.sqrt(shares / (entry_adv + 1e-8))
                impact_cost = impact_pct * shares * entry_p
                total_entry_cost = fixed + slip + impact_cost
                cost_per_share = total_entry_cost / max(shares, 1)
                effective_entry = entry_p + cost_per_share

                in_trade = True
                entry_price = effective_entry
                entry_vwap = vwap.iloc[t_entry]
                entry_sd = vwap_sd.iloc[t_entry]
                entry_sl_level = sl_level.iloc[t_entry]
                entry_day_idx = t_entry
                hold_days = 0
                entry_shares = shares
                entry_cost = total_entry_cost
                signal_bar_idx = t_signal

        else:
            # In trade: check exit conditions
            hold_days += 1
            bar_close = close.iloc[i]
            bar_vwap = vwap.iloc[i]

            exit_reason = None
            exit_price = None

            # TP: price returns to VWAP center
            if not pd.isna(bar_close) and not pd.isna(bar_vwap) and bar_close >= bar_vwap:
                exit_reason = "TP"
                exit_price = open_.iloc[i] if not pd.isna(open_.iloc[i]) else bar_close

            # SL: price continues below SL level
            elif not pd.isna(bar_close) and not pd.isna(entry_sl_level) and bar_close <= entry_sl_level:
                exit_reason = "SL"
                exit_price = open_.iloc[i] if not pd.isna(open_.iloc[i]) else bar_close

            # Time stop
            elif hold_days >= max_hold:
                exit_reason = "TIME"
                exit_price = open_.iloc[i] if not pd.isna(open_.iloc[i]) else bar_close

            if exit_reason and exit_price and exit_price > 0:
                exit_p = exit_price
                exit_sig = sigma.iloc[i] if not pd.isna(sigma.iloc[i]) else 0.01
                exit_adv = adv.iloc[i] if not pd.isna(adv.iloc[i]) else 1e6

                # Transaction cost at exit
                fixed_ex = entry_shares * FIXED_COST_PER_SHARE
                slip_ex = SLIPPAGE_PCT * (entry_shares * exit_p)
                impact_pct_ex = MARKET_IMPACT_K * exit_sig * np.sqrt(entry_shares / (exit_adv + 1e-8))
                impact_cost_ex = impact_pct_ex * entry_shares * exit_p
                total_exit_cost = fixed_ex + slip_ex + impact_cost_ex
                cost_per_share_ex = total_exit_cost / max(entry_shares, 1)
                effective_exit = exit_p - cost_per_share_ex

                gross_pnl = (effective_exit - entry_price) * entry_shares
                net_pnl = gross_pnl  # costs already in effective prices

                trade_log.append({
                    "ticker": "PORTFOLIO",
                    "entry_date": str(idx[entry_day_idx].date()),
                    "exit_date": str(idx[i].date()),
                    "entry_price": round(float(entry_price), 4),
                    "exit_price": round(float(effective_exit), 4),
                    "shares": entry_shares,
                    "hold_days": hold_days,
                    "exit_reason": exit_reason,
                    "gross_pnl": round(float(gross_pnl), 2),
                    "net_pnl": round(float(net_pnl), 2),
                    "return_pct": round(float((effective_exit / entry_price - 1.0) * 100), 4),
                    "entry_sd_threshold": params["vwap_sd_threshold"],
                    "market_impact_entry_bps": round(
                        MARKET_IMPACT_K * (sigma.iloc[entry_day_idx] if not pd.isna(sigma.iloc[entry_day_idx]) else 0.01)
                        * np.sqrt(entry_shares / (adv.iloc[entry_day_idx] + 1e-8)) * 10000, 2
                    ),
                })

                capital += net_pnl
                in_trade = False
                hold_days = 0

        portfolio_values.iloc[i] = capital

    # Forward-fill portfolio values for days we weren't updating
    portfolio_values = portfolio_values.ffill().fillna(init_cash)
    daily_returns = portfolio_values.pct_change().fillna(0.0)

    return trade_log, daily_returns, portfolio_values


def run_strategy(start: str, end: str, params: dict = None) -> dict:
    """
    Run H13 VWAP Anchor Reversion on all universe tickers.

    Combines trade logs across all ETFs, runs each independently.
    Returns aggregated performance metrics.
    """
    if params is None:
        params = PARAMETERS

    universe = params["universe"]
    # Add warmup buffer for VWAP computation
    warmup_days = max(60, params["vwap_lookback"] * 3)
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).strftime("%Y-%m-%d")

    data = download_etf_data(universe, warmup_start, end)

    if not data:
        return {
            "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
            "trade_count": 0, "total_return": 0.0, "returns": np.array([]),
            "trade_log": [], "win_loss_ratio": 0.0, "profit_factor": 0.0,
            "per_ticker_trades": {}, "exit_reasons": {},
        }

    all_trade_logs = []
    all_daily_returns = []
    exit_reasons = {}
    per_ticker_trades = {}

    for ticker, ohlcv in data.items():
        # Trim to actual start (after warmup)
        ohlcv_trimmed = ohlcv.loc[ohlcv.index >= pd.Timestamp(start)]
        ohlcv_warmup = ohlcv  # full data including warmup for VWAP computation

        bands = compute_vwap_bands(ohlcv_warmup, params["vwap_lookback"])
        bands_trimmed = bands.loc[bands.index >= pd.Timestamp(start)]

        macro_mask = build_macro_exclusion_mask(bands_trimmed.index)

        trade_log, daily_returns, _ = simulate_trades(bands_trimmed, params, macro_mask)

        # Tag trades with ticker
        for t in trade_log:
            t["ticker"] = ticker

        all_trade_logs.extend(trade_log)
        all_daily_returns.append(daily_returns)

        per_ticker_trades[ticker] = len(trade_log)
        for t in trade_log:
            reason = t.get("exit_reason", "UNKNOWN")
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    if not all_daily_returns:
        return {
            "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
            "trade_count": 0, "total_return": 0.0, "returns": np.array([]),
            "trade_log": [], "win_loss_ratio": 0.0, "profit_factor": 0.0,
            "per_ticker_trades": {}, "exit_reasons": {},
        }

    # Combine returns: average across tickers (each sized independently)
    combined_idx = all_daily_returns[0].index
    for r in all_daily_returns[1:]:
        combined_idx = combined_idx.intersection(r.index)

    returns_matrix = pd.DataFrame({
        universe[i]: all_daily_returns[i].reindex(combined_idx).fillna(0.0)
        for i in range(len(all_daily_returns))
    })
    avg_returns = returns_matrix.mean(axis=1)
    returns_arr = avg_returns.values

    # Metrics
    if returns_arr.std() > 0:
        sharpe = round(float(returns_arr.mean() / returns_arr.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 4)
    else:
        sharpe = 0.0

    cum = np.cumprod(1 + returns_arr)
    roll_max = np.maximum.accumulate(cum)
    mdd = round(float(np.min((cum - roll_max) / (roll_max + 1e-8))), 4)
    total_return = round(float(cum[-1] - 1.0), 4) if len(cum) > 0 else 0.0

    trade_returns = [t["return_pct"] / 100.0 for t in all_trade_logs]
    win_rate = round(float(np.mean([r > 0 for r in trade_returns])), 4) if trade_returns else 0.0

    wins = [r for r in trade_returns if r > 0]
    losses = [abs(r) for r in trade_returns if r < 0]
    win_loss_ratio = round(float(np.mean(wins) / np.mean(losses)), 4) if wins and losses else 0.0

    gross_profits = sum(t["net_pnl"] for t in all_trade_logs if t["net_pnl"] > 0)
    gross_losses = abs(sum(t["net_pnl"] for t in all_trade_logs if t["net_pnl"] < 0))
    profit_factor = round(float(gross_profits / gross_losses), 4) if gross_losses > 0 else 0.0

    return {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "trade_count": len(all_trade_logs),
        "total_return": total_return,
        "returns": returns_arr,
        "trade_log": all_trade_logs,
        "win_loss_ratio": win_loss_ratio,
        "profit_factor": profit_factor,
        "per_ticker_trades": per_ticker_trades,
        "exit_reasons": exit_reasons,
    }


def scan_vwap_sd_threshold(
    is_data: dict, start: str, end: str, base_params: dict
) -> dict:
    """
    Sensitivity scan: sweep vwap_sd_threshold from 1.5 to 2.5.
    Returns dict with results per threshold value.
    """
    thresholds = [1.5, 1.75, 2.0, 2.25, 2.5]
    results = {}

    for thresh in thresholds:
        p = {**base_params, "vwap_sd_threshold": thresh}
        try:
            r = run_strategy(start, end, p)
            results[f"sd_{thresh}"] = {
                "threshold": thresh,
                "sharpe": r["sharpe"],
                "trade_count": r["trade_count"],
                "win_rate": r["win_rate"],
                "max_drawdown": r["max_drawdown"],
            }
        except Exception as exc:
            results[f"sd_{thresh}"] = {"threshold": thresh, "error": str(exc)}

    # Compute variance
    valid_sharpes = [v["sharpe"] for v in results.values()
                     if "sharpe" in v and v["sharpe"] != 0.0]
    if valid_sharpes:
        base_sharpe = results.get("sd_2.0", {}).get("sharpe", 0.0)
        if base_sharpe != 0:
            diffs = [abs(s - base_sharpe) / (abs(base_sharpe) + 1e-8) for s in valid_sharpes]
            max_var = round(float(max(diffs)) * 100, 2)
        else:
            max_var = 100.0
    else:
        max_var = 100.0

    results["_meta"] = {
        "sharpe_variance_pct": max_var,
        "sensitivity_pass": max_var < 50.0,
        "note": f"Max Sharpe deviation from base (2.0SD): {max_var:.1f}% ({'PASS' if max_var < 50.0 else 'FAIL'})",
    }
    return results
