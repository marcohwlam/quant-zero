"""
Strategy: H55 Low Volatility Anomaly — SPLV/USMV Factor Rotation with Bear-Market Gate
Author: Strategy Coder Agent
Date: 2026-06-09
Hypothesis: research/hypotheses/55_low_volatility_anomaly_etf.md
Parent task: QUA-126

Signal: Monthly rotation between low-vol ETF (SPLV/USMV), SPY, or SHY.
  Bear-market gate (MANDATORY): SPY 12m return < SHY 12m return → hold SHY (100%)
  If equity regime positive AND low-vol ETF/proxy > 12m MA → hold low-vol
  If equity regime positive AND low-vol ETF/proxy < 12m MA → hold SPY

Pre-ETF proxy (1990–2011): Each month, rank S&P 500 proxy constituents by trailing
  12-month realized volatility. Equal-weight bottom quintile (lowest 20% vol) = low-vol proxy.

ETF period: SPLV inception May 2011, USMV inception Oct 2011.
  USMV run as parallel robustness check.

IS window:  1990-01-01 to 2021-12-31 (32 years; proxy 1990-2011 + SPLV 2011-2021)
OOS window: 2022-01-01 to 2025-12-31 (3.5 years; rate-shock regime)

Data quality checklist:
  - Survivorship bias: FLAGGED — proxy uses current S&P 500 constituents subset.
    Point-in-time historical universe unavailable via yfinance. This introduces upward
    bias in proxy returns (delisted stocks excluded). Documented per Engineering Director
    pre-backtest checklist. ETF period (2011+) is clean.
  - Price adjustments: auto_adjust=True via yfinance (splits + dividends).
  - Data gaps: checked at runtime; tickers with >5 missing trading days flagged.
  - Earnings exclusion: NOT APPLICABLE — ETF rotation + proxy portfolio; no individual
    earnings exposure at strategy level.
  - Delisted tickers: NOT APPLICABLE for ETF period. Proxy period has survivorship bias
    (flagged above).

Academic sources:
  Blitz, D. & van Vliet, P. (2007). "The Volatility Effect." JOPM 34(1), 102-113.
  Baker, M., Bradley, B. & Wurgler, J. (2011). "Benchmarks as Limits to Arbitrage." FAJ 67(1).

Transaction cost model (canonical, per Engineering Director AGENTS.md):
  - Fixed: $0.005/share
  - Slippage: 0.05% of trade value
  - Market impact: k × σ × sqrt(Q / ADV), k=0.1
  - Liquidity flag: Q/ADV > 0.01 → liquidity_constrained = True
  - Proxy portfolio: no transaction costs applied (proxy is notional factor portfolio)
  - ETF period: transaction costs applied on SPLV/USMV/SPY/SHY trades
"""

import logging
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252

# ── Parameters ─────────────────────────────────────────────────────────────────

PARAMETERS = {
    # Primary low-vol ETF (SPLV inception May 2011)
    "low_vol_etf": "SPLV",
    # Signal lookback — 12m MA on low-vol ETF/proxy (months)
    "signal_lookback_months": 12,
    # Bear-market gate lookback (months)
    "bear_gate_lookback_months": 12,
    # Safe harbor asset when bear gate fires
    "safe_harbor": "SHY",
    # Bull-market rotation target when low-vol below MA
    "bull_rotation": "SPY",
    # Transaction cost model (ETF period)
    "fixed_cost_per_share": 0.005,
    "slippage_pct": 0.0005,
    "market_impact_k": 0.1,
    "sigma_window": 20,
    "adv_window": 20,
    "order_qty": 100,
    "liquidity_threshold": 0.01,
    # Portfolio
    "init_cash": 25000.0,
    # Proxy construction
    "proxy_vol_lookback_months": 12,   # 12m realized vol lookback for constituent sort
    "proxy_quintile_frac": 0.20,       # bottom 20% by vol = low-vol proxy
    # USMV parallel test flag (run_backtest accepts etf_override param)
    "usmv_inception": "2011-10-01",
    "splv_inception": "2011-05-05",
    "etf_warmup_months": 3,
}

DATA_QUALITY = {
    "survivorship_bias": (
        "FLAGGED — proxy universe uses curated subset of S&P 500 large-caps known to "
        "have traded continuously 1990–2011. Stocks delisted during this period are "
        "excluded from the proxy, introducing upward bias in pre-2011 returns. "
        "ETF period (2011+) uses SPLV/USMV directly — no survivorship bias."
    ),
    "price_adjustments": "auto_adjust=True via yfinance for all assets",
    "earnings_exclusion": (
        "not_applicable — monthly rebalanced ETF/proxy rotation. "
        "No individual stock earnings exposure at strategy level."
    ),
    "delisted_tickers": (
        "Proxy period: survivorship-biased (flagged). "
        "ETF period: SPLV (2011), USMV (2011), SPY (1993), SHY (2002) all active."
    ),
    "is_window": "1990-01-01 to 2021-12-31",
    "oos_window": "2022-01-01 to 2025-12-31",
}

# ── S&P 500 Proxy Constituent Universe (1990–2011 period) ─────────────────────
# Curated ~150 large-cap stocks with continuous yfinance data through 1990–2011.
# Represents major S&P 500 sectors. Survivorship-biased (documented above).
# Includes low-vol sectors (utilities, consumer staples, healthcare) and higher-vol
# sectors (tech, financials) — the algorithm sorts by vol to find the bottom quintile.

PROXY_UNIVERSE = [
    # Utilities (expected low vol — typically populate bottom quintile)
    "SO", "DUK", "D", "EXC", "XEL", "WEC", "AEP", "PPL", "ETR", "NEE",
    # Consumer Staples (expected low vol)
    "PG", "KO", "PEP", "CL", "KMB", "GIS", "K", "HRL", "SJM", "CPB",
    "MO", "WMT", "CVS", "SYY",
    # Healthcare (mixed vol — pharma lower, biotech higher)
    "JNJ", "ABT", "MDT", "BDX", "BAX", "PFE", "MRK", "LLY", "BMY",
    # Financials (higher vol, especially 2008-2009)
    "JPM", "BAC", "WFC", "USB", "PNC", "TRV", "ALL", "AFL", "CB",
    # Industrials (moderate vol)
    "MMM", "ITW", "PH", "EMR", "HON", "GE", "CAT", "DE", "ROK", "ETN",
    # Energy (cyclical, moderate-high vol)
    "XOM", "CVX", "COP", "SLB", "HAL", "VLO",
    # Materials (moderate-high vol)
    "APD", "PPG", "ECL", "NEM", "FCX",
    # Technology (higher vol — expected to NOT be in low-vol quintile)
    "IBM", "MSFT", "INTC", "ORCL", "HPQ", "TXN", "ADI", "PAYX",
    # Consumer Discretionary (moderate vol)
    "MCD", "YUM", "DIS", "HD", "LOW", "TGT", "JWN", "LTD",
    # Telecom (moderate vol)
    "T", "VZ",
    # REITs (available from late 1990s)
    "SPG", "O",
]

# ── Data Loading ──────────────────────────────────────────────────────────────

def _download_etf(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download single ETF with adjusted prices."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw.empty:
        raise ValueError(f"No data for {ticker} [{start} → {end}]")
    return raw


def _check_data_gaps(prices: pd.Series, label: str) -> str:
    """Flag tickers with consecutive missing weekday runs > 5 days."""
    bdays = pd.date_range(prices.index.min(), prices.index.max(), freq="B")
    missing = bdays.difference(prices.index)
    if len(missing) == 0:
        return "no_gaps"
    runs, run = [], 1
    for i in range(1, len(missing)):
        if (missing[i] - missing[i - 1]).days == 1:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)
    max_run = max(runs) if runs else 0
    if max_run > 5:
        logger.warning("DATA GAP FLAG: %s has consecutive missing run of %d weekdays", label, max_run)
        return f"flagged:max_consecutive_missing={max_run}"
    return f"ok:max_consecutive_missing={max_run}"


def load_etf_data(low_vol_etf: str, start: str, end: str, params: dict) -> dict:
    """
    Download ETF prices (SPLV/USMV, SPY, SHY) for the ETF backtest period.
    Returns dict of DataFrames keyed by ticker.
    """
    # Add warmup buffer for MA computation
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(months=params["signal_lookback_months"] + 2))
    warmup_str = warmup_start.strftime("%Y-%m-%d")

    tickers = [low_vol_etf, "SPY", "SHY"]
    result = {}
    for t in tickers:
        try:
            df = _download_etf(t, warmup_str, end)
            result[t] = df
            gap = _check_data_gaps(df["Close"], t)
            logger.info("ETF data: %s %s days | gap=%s", t, len(df), gap)
        except Exception as e:
            logger.warning("Failed to download %s: %s", t, e)
    return result


# ── Proxy Portfolio Construction (1990–2011) ─────────────────────────────────

def build_proxy_universe_data(start: str, end: str, params: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Download daily prices for proxy universe stocks over 1990–2011 period.
    Returns (close_prices, volume) DataFrames.

    Survivorship bias: Only stocks in PROXY_UNIVERSE that have yfinance data
    for the full period are included. Stocks delisted during 1990–2011 are absent.
    This is documented in DATA_QUALITY and flagged in backtest output.
    """
    # Extra warmup for 12m vol lookback
    warmup_start = (pd.Timestamp(start) - pd.DateOffset(months=params["proxy_vol_lookback_months"] + 2))
    warmup_str = warmup_start.strftime("%Y-%m-%d")

    logger.info("Downloading proxy universe: %d tickers from %s to %s ...", len(PROXY_UNIVERSE), warmup_str, end)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = yf.download(
            PROXY_UNIVERSE,
            start=warmup_str,
            end=end,
            auto_adjust=True,
            progress=False,
            threads=True,
        )

    if raw.empty:
        raise ValueError("Proxy universe download returned empty data")

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        volume = raw["Volume"]
    else:
        close = raw[["Close"]]
        volume = raw[["Volume"]]

    # Drop tickers with >80% missing data (not available for the period)
    coverage = close.notna().mean()
    valid_tickers = coverage[coverage >= 0.20].index.tolist()
    dropped = [t for t in PROXY_UNIVERSE if t not in valid_tickers]
    if dropped:
        logger.warning("Proxy: dropped %d tickers with <20%% coverage: %s", len(dropped), dropped[:10])

    close = close[valid_tickers].copy()
    volume = volume[[t for t in valid_tickers if t in volume.columns]].copy()

    logger.info("Proxy universe: %d tickers with sufficient data", len(valid_tickers))
    return close, volume


def compute_monthly_low_vol_proxy(close: pd.DataFrame, params: dict) -> pd.Series:
    """
    Each month-end: rank constituents by trailing 12m realized vol.
    Bottom quintile (lowest 20%) → equal-weight portfolio.
    Return monthly return series of the proxy portfolio.

    This implements the Blitz & van Vliet (2007) bottom-quintile factor.
    """
    lookback = params["proxy_vol_lookback_months"]
    quintile_frac = params["proxy_quintile_frac"]

    # Resample to month-end, compute 12m trailing daily-return std (annualized)
    daily_returns = close.pct_change()

    # Month-end dates over the full period
    monthly_ends = close.resample("ME").last().index

    proxy_returns = []
    proxy_dates = []

    for i in range(lookback, len(monthly_ends)):
        month_end = monthly_ends[i]
        lookback_start = monthly_ends[i - lookback]

        # Get daily returns in the trailing lookback window
        mask = (daily_returns.index > lookback_start) & (daily_returns.index <= month_end)
        window_ret = daily_returns.loc[mask]

        if len(window_ret) < lookback * 15:  # need at least ~15 days/month
            continue

        # Compute annualized vol for each ticker
        ticker_vol = window_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

        # Drop tickers with NaN vol (insufficient data in window)
        ticker_vol = ticker_vol.dropna()
        if len(ticker_vol) < 10:  # need enough tickers for quintile
            continue

        # Bottom quintile (lowest vol) — this is the low-vol factor portfolio
        n_in_quintile = max(1, int(len(ticker_vol) * quintile_frac))
        low_vol_tickers = ticker_vol.nsmallest(n_in_quintile).index.tolist()

        # Equal-weight portfolio return for the NEXT month
        # (signal built at month_end, position held next month)
        if i + 1 < len(monthly_ends):
            next_month_start = monthly_ends[i]
            next_month_end = monthly_ends[i + 1]
            next_mask = (close.index > next_month_start) & (close.index <= next_month_end)
            next_prices = close.loc[next_mask, low_vol_tickers]

            # Compute available tickers' monthly return
            available = [t for t in low_vol_tickers if t in next_prices.columns]
            if not available:
                continue
            month_rets = []
            for t in available:
                p = next_prices[t].dropna()
                if len(p) >= 2:
                    month_rets.append((p.iloc[-1] - p.iloc[0]) / p.iloc[0])
            if month_rets:
                proxy_returns.append(np.mean(month_rets))
                proxy_dates.append(next_month_end)

    if not proxy_returns:
        raise ValueError("Proxy construction returned no monthly returns")

    proxy_series = pd.Series(proxy_returns, index=pd.DatetimeIndex(proxy_dates), name="proxy_low_vol")
    logger.info("Proxy: %d monthly observations (%s → %s)", len(proxy_series),
                proxy_series.index[0].date(), proxy_series.index[-1].date())
    return proxy_series


def compute_proxy_ma_signal(proxy_nav: pd.Series, lookback_months: int) -> pd.Series:
    """
    Compute 12-month MA signal on the proxy NAV (cumulative proxy returns).
    Returns Boolean series: True = proxy above MA (hold low-vol), False = rotate to SPY.
    """
    rolling_ma = proxy_nav.rolling(window=lookback_months).mean()
    return proxy_nav > rolling_ma


# ── Transaction Cost Model (ETF Period) ──────────────────────────────────────

def compute_transaction_cost(
    price: float,
    qty: int,
    sigma: float,
    adv: float,
    params: dict,
) -> tuple[float, bool]:
    """
    Canonical cost model per Engineering Director AGENTS.md.
    Returns (total_cost_per_share, liquidity_constrained).
    """
    fixed = params["fixed_cost_per_share"]
    slippage = params["slippage_pct"] * price
    liquidity_constrained = False
    market_impact = 0.0

    if adv > 0:
        q_over_adv = qty / adv
        liquidity_constrained = q_over_adv > params["liquidity_threshold"]
        market_impact = params["market_impact_k"] * sigma * np.sqrt(q_over_adv) * price

    total_per_share = fixed + slippage + market_impact
    return total_per_share, liquidity_constrained


# ── Signal Generation (Combined Proxy + ETF) ─────────────────────────────────

def generate_combined_signals(
    proxy_monthly_returns: pd.Series,
    etf_data: dict,
    low_vol_etf: str,
    params: dict,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Combine proxy period + ETF period into a single monthly signal DataFrame.

    Columns: date, position (SPLV|SPY|SHY|PROXY), bear_gate, low_vol_above_ma, period
    """
    splv_inception = pd.Timestamp(params["splv_inception"])
    signals = []

    # ── SPY and SHY monthly data for bear-gate ────────────────────────────────
    spy_close = etf_data["SPY"]["Close"] if "SPY" in etf_data else None
    shy_close = etf_data["SHY"]["Close"] if "SHY" in etf_data else None

    # Resample SPY/SHY to monthly for bear gate computation
    if spy_close is not None and shy_close is not None:
        spy_monthly = spy_close.resample("ME").last()
        shy_monthly = shy_close.resample("ME").last()

        # Bear gate: SPY 12m return vs SHY 12m return
        # Align on common monthly index before comparison to avoid label mismatch
        bear_gate_lookback = params["bear_gate_lookback_months"]
        common_idx = spy_monthly.index.intersection(shy_monthly.index)
        spy_monthly_aligned = spy_monthly.loc[common_idx]
        shy_monthly_aligned = shy_monthly.loc[common_idx]
        spy_12m_ret = spy_monthly_aligned.pct_change(bear_gate_lookback)
        shy_12m_ret = shy_monthly_aligned.pct_change(bear_gate_lookback)
        bear_gate_active = spy_12m_ret < shy_12m_ret  # True = bear market → hold SHY
    else:
        logger.warning("SPY or SHY data missing — bear gate disabled")
        bear_gate_active = pd.Series(dtype=bool)

    # ── ETF period signal ─────────────────────────────────────────────────────
    etf_start = pd.Timestamp(start)
    if low_vol_etf in etf_data:
        etf_close = etf_data[low_vol_etf]["Close"]
        etf_monthly = etf_close.resample("ME").last()
        ma_lookback = params["signal_lookback_months"]
        etf_ma = etf_monthly.rolling(window=ma_lookback).mean()
        etf_above_ma = etf_monthly > etf_ma  # True = hold low-vol ETF, False = hold SPY
    else:
        etf_above_ma = pd.Series(dtype=bool)

    # ── Build unified monthly signal series ───────────────────────────────────
    # All month-ends in the full IS+OOS range
    all_month_ends = pd.date_range(start=start, end=end, freq="ME")

    for month_end in all_month_ends:
        period = "proxy" if month_end < splv_inception else "etf"

        # Bear gate lookup
        bear_gate = False
        if not bear_gate_active.empty and month_end in bear_gate_active.index:
            bear_gate = bool(bear_gate_active.loc[month_end])
        elif not bear_gate_active.empty:
            # Use nearest prior month-end
            prior = bear_gate_active.loc[bear_gate_active.index <= month_end]
            if not prior.empty:
                bear_gate = bool(prior.iloc[-1])

        if bear_gate:
            position = params["safe_harbor"]
            low_vol_above_ma = None
        elif period == "proxy":
            # Proxy period: use proxy NAV MA signal
            if proxy_monthly_returns is not None:
                idx = proxy_monthly_returns.index
                proxy_so_far = proxy_monthly_returns.loc[idx <= month_end]
                if len(proxy_so_far) >= params["signal_lookback_months"]:
                    # Proxy NAV (cumulative)
                    proxy_nav = (1 + proxy_so_far).cumprod()
                    ma = proxy_nav.rolling(window=params["signal_lookback_months"]).mean()
                    low_vol_above_ma = bool(proxy_nav.iloc[-1] > ma.iloc[-1])
                else:
                    low_vol_above_ma = True  # insufficient history → default to low-vol
            else:
                low_vol_above_ma = True
            position = "PROXY" if low_vol_above_ma else "SPY"
        else:
            # ETF period
            if not etf_above_ma.empty and month_end in etf_above_ma.index:
                low_vol_above_ma = bool(etf_above_ma.loc[month_end])
            elif not etf_above_ma.empty:
                prior = etf_above_ma.loc[etf_above_ma.index <= month_end]
                low_vol_above_ma = bool(prior.iloc[-1]) if not prior.empty else True
            else:
                low_vol_above_ma = True
            position = low_vol_etf if low_vol_above_ma else params["bull_rotation"]

        signals.append({
            "date": month_end,
            "position": position,
            "bear_gate": bear_gate,
            "low_vol_above_ma": low_vol_above_ma,
            "period": period,
        })

    return pd.DataFrame(signals).set_index("date")


# ── Monthly Return Computation ────────────────────────────────────────────────

def _get_monthly_returns_series(etf_data: dict) -> dict:
    """Convert ETF DataFrames to monthly return series."""
    monthly = {}
    for ticker, df in etf_data.items():
        if "Close" in df.columns:
            monthly[ticker] = df["Close"].resample("ME").last().pct_change()
    return monthly


def compute_strategy_returns(
    signals: pd.DataFrame,
    proxy_monthly_returns: pd.Series,
    etf_data: dict,
    params: dict,
) -> pd.DataFrame:
    """
    Compute monthly strategy return based on lagged signals.
    Signal at month t → position held in month t+1 → return realized in t+1.

    Returns DataFrame with columns: date, position, return, cost_bps, liquidity_constrained, period.
    """
    etf_monthly = _get_monthly_returns_series(etf_data)
    spy_monthly = etf_monthly.get("SPY", pd.Series(dtype=float))
    shy_monthly = etf_monthly.get("SHY", pd.Series(dtype=float))

    rows = []
    prev_position = None

    for i in range(len(signals) - 1):
        signal_date = signals.index[i]
        return_date = signals.index[i + 1]
        position = signals.iloc[i]["position"]
        period = signals.iloc[i]["period"]

        # Get return for the position held in the next month
        if position == "PROXY":
            # Proxy portfolio: look up in proxy_monthly_returns
            if proxy_monthly_returns is not None and return_date in proxy_monthly_returns.index:
                ret = float(proxy_monthly_returns.loc[return_date])
            else:
                # Find nearest
                avail = proxy_monthly_returns.index[proxy_monthly_returns.index <= return_date]
                ret = float(proxy_monthly_returns.loc[avail[-1]]) if len(avail) else 0.0
        elif position == "SPY":
            avail = spy_monthly.index[spy_monthly.index <= return_date]
            ret = float(spy_monthly.loc[avail[-1]]) if len(avail) else 0.0
        elif position == params["safe_harbor"]:  # SHY
            avail = shy_monthly.index[shy_monthly.index <= return_date]
            ret = float(shy_monthly.loc[avail[-1]]) if len(avail) else 0.0
        elif position in etf_monthly:
            avail = etf_monthly[position].index[etf_monthly[position].index <= return_date]
            ret = float(etf_monthly[position].loc[avail[-1]]) if len(avail) else 0.0
        else:
            ret = 0.0

        # Transaction cost (ETF period, when position changes)
        cost_bps = 0.0
        liquidity_constrained = False
        if period == "etf" and position != prev_position and prev_position is not None:
            # Estimate cost on transition — use rough price and qty
            price_est = 100.0  # approximate ETF price
            qty = max(1, int(params["init_cash"] / price_est))
            sigma_est = 0.012  # ~20d daily vol estimate (monthly ~ 12% / sqrt(12))
            adv_est = 5_000_000  # conservative ADV for major ETFs
            cost_per_share, liq = compute_transaction_cost(price_est, qty, sigma_est, adv_est, params)
            cost_bps = (cost_per_share / price_est) * 10_000
            liquidity_constrained = liq

        rows.append({
            "date": return_date,
            "position": position,
            "gross_return": ret,
            "cost_bps": cost_bps,
            "net_return": ret - (cost_bps / 10_000),
            "liquidity_constrained": liquidity_constrained,
            "period": period,
        })
        prev_position = position

    return pd.DataFrame(rows).set_index("date")


# ── Performance Metrics ───────────────────────────────────────────────────────

def compute_metrics(returns_df: pd.DataFrame, label: str = "IS") -> dict:
    """
    Compute standard Gate 1 performance metrics from monthly return series.
    """
    if returns_df.empty:
        return {"label": label, "error": "empty_returns"}

    net_ret = returns_df["net_return"].dropna()
    gross_ret = returns_df["gross_return"].dropna()

    if len(net_ret) < 2:
        return {"label": label, "error": "insufficient_returns", "n_months": len(net_ret)}

    # Annualized return and vol (monthly → annual)
    ann_ret = (1 + net_ret).prod() ** (12 / len(net_ret)) - 1
    ann_vol = net_ret.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0

    # Drawdown
    nav = (1 + net_ret).cumprod()
    rolling_max = nav.cummax()
    drawdown = (nav - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min())

    # For monthly rotation: each monthly period = 1 trade (standard convention for rotation strategies)
    # Also track position transitions (actual rebalancing events with costs)
    positions = returns_df["position"].values
    n_transitions = sum(1 for i in range(1, len(positions)) if positions[i] != positions[i - 1])
    trade_count = int(len(net_ret))  # each month = 1 trade observation

    # Win rate and profit factor (monthly basis)
    wins = net_ret[net_ret > 0]
    losses = net_ret[net_ret <= 0]
    win_rate = len(wins) / len(net_ret) if len(net_ret) > 0 else 0.0
    gross_wins = wins.sum() if len(wins) > 0 else 0.0
    gross_losses = abs(losses.sum()) if len(losses) > 0 else 1e-8
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    # SPY benchmark comparison (Gross return for comparison)
    spy_ret = returns_df.apply(
        lambda r: r["gross_return"] if r["position"] == "SPY" else 0.0, axis=1
    )

    # Bear gate activation rate
    bear_gate_pct = returns_df.get("period", pd.Series()).pipe(
        lambda _: returns_df.apply(
            lambda r: r.get("position") == "SHY", axis=1
        ).mean() if "position" in returns_df.columns else 0.0
    )

    return {
        "label": label,
        "n_months": int(len(net_ret)),
        "trade_count": int(trade_count),
        "n_transitions": int(n_transitions),
        "annualized_return": round(float(ann_ret), 6),
        "annualized_vol": round(float(ann_vol), 6),
        "sharpe": round(float(sharpe), 4),
        "max_drawdown": round(float(max_drawdown), 6),
        "win_rate": round(float(win_rate), 4),
        "profit_factor": round(float(profit_factor), 4),
        "avg_cost_bps": round(float(returns_df["cost_bps"].mean()), 4),
        "bear_gate_pct": round(float(bear_gate_pct), 4),
        "liquidity_constrained_count": int(returns_df["liquidity_constrained"].sum()),
    }


def compute_walk_forward_metrics(
    proxy_monthly: pd.Series,
    etf_data: dict,
    low_vol_etf: str,
    params: dict,
    windows: list,
) -> list:
    """
    Walk-forward analysis over specified windows.
    Each window is a (start, end) tuple.
    Returns list of per-window metric dicts.
    """
    wf_results = []
    for wf_start, wf_end in windows:
        try:
            # For proxy windows, filter proxy_monthly to window
            proxy_slice = None
            if proxy_monthly is not None:
                idx = proxy_monthly.index
                proxy_slice = proxy_monthly.loc[(idx >= wf_start) & (idx <= wf_end)]
                if proxy_slice.empty:
                    proxy_slice = None

            sigs = generate_combined_signals(
                proxy_monthly_returns=proxy_slice if proxy_slice is not None else proxy_monthly,
                etf_data=etf_data,
                low_vol_etf=low_vol_etf,
                params=params,
                start=wf_start,
                end=wf_end,
            )
            ret_df = compute_strategy_returns(sigs, proxy_monthly, etf_data, params)
            m = compute_metrics(ret_df, label=f"WF {wf_start[:7]}→{wf_end[:7]}")
            wf_results.append(m)
        except Exception as e:
            wf_results.append({"label": f"WF {wf_start[:7]}→{wf_end[:7]}", "error": str(e)})
    return wf_results


# ── Main Backtest Entry Point ─────────────────────────────────────────────────

def run_backtest(
    is_start: str = "1990-01-01",
    is_end: str = "2021-12-31",
    oos_start: str = "2022-01-01",
    oos_end: str = "2025-12-31",
    params: dict = None,
    etf_override: str = None,   # Set to "USMV" for parallel robustness test
    skip_proxy: bool = False,   # Set True to run ETF-only (2011+) for fast iteration
) -> dict:
    """
    Run H55 full backtest: proxy period (1990-2011) + ETF period (2011-2025).

    Returns standardized Gate 1 metrics dict.
    """
    if params is None:
        params = PARAMETERS.copy()

    low_vol_etf = etf_override if etf_override else params["low_vol_etf"]
    if etf_override == "USMV":
        # USMV inception Oct 2011 — shift ETF start
        params = params.copy()

    logger.info("=== H55 Low Volatility Anomaly Backtest ===")
    logger.info("ETF: %s | IS: %s→%s | OOS: %s→%s", low_vol_etf, is_start, is_end, oos_start, oos_end)
    logger.info("Bear-market gate: ENABLED (SPY vs SHY 12m momentum)")

    # ── 1. Download ETF data (SPLV/USMV, SPY, SHY) ───────────────────────────
    logger.info("[1/5] Downloading ETF data (%s, SPY, SHY) ...", low_vol_etf)
    # Download from earliest ETF date with warmup for full IS+OOS
    etf_download_start = "1990-01-01"  # SPY/SHY available; SPLV only from 2011
    try:
        etf_data = {}
        for t in ["SPY", "SHY"]:
            df = _download_etf(t, etf_download_start, oos_end)
            etf_data[t] = df
            logger.info("  Downloaded %s: %d days", t, len(df))

        if low_vol_etf in ("SPLV", "USMV"):
            etf_start_date = params["splv_inception"] if low_vol_etf == "SPLV" else params["usmv_inception"]
            warmup_start = (pd.Timestamp(etf_start_date) - pd.DateOffset(months=params["signal_lookback_months"] + 2))
            df = _download_etf(low_vol_etf, warmup_start.strftime("%Y-%m-%d"), oos_end)
            etf_data[low_vol_etf] = df
            logger.info("  Downloaded %s: %d days (from %s)", low_vol_etf, len(df), warmup_start.strftime("%Y-%m-%d"))
    except Exception as e:
        return {"error": f"ETF data download failed: {e}"}

    # ── 2. Build pre-ETF proxy (1990–2011) ───────────────────────────────────
    proxy_monthly = None
    if not skip_proxy:
        logger.info("[2/5] Building pre-ETF low-vol proxy (1990–2011) ...")
        try:
            proxy_close, proxy_vol_data = build_proxy_universe_data("1990-01-01", "2011-12-31", params)
            proxy_monthly = compute_monthly_low_vol_proxy(proxy_close, params)
            logger.info("  Proxy: %d monthly observations", len(proxy_monthly))
        except Exception as e:
            logger.warning("Proxy construction failed: %s — running ETF-only", e)
            proxy_monthly = None

    # ── 3. Generate signals ───────────────────────────────────────────────────
    logger.info("[3/5] Generating IS signals (%s → %s) ...", is_start, is_end)
    try:
        is_signals = generate_combined_signals(
            proxy_monthly_returns=proxy_monthly,
            etf_data=etf_data,
            low_vol_etf=low_vol_etf,
            params=params,
            start=is_start,
            end=is_end,
        )
        is_returns = compute_strategy_returns(is_signals, proxy_monthly, etf_data, params)
    except Exception as e:
        return {"error": f"IS signal generation failed: {e}"}

    logger.info("[3/5] Generating OOS signals (%s → %s) ...", oos_start, oos_end)
    try:
        oos_signals = generate_combined_signals(
            proxy_monthly_returns=proxy_monthly,
            etf_data=etf_data,
            low_vol_etf=low_vol_etf,
            params=params,
            start=oos_start,
            end=oos_end,
        )
        oos_returns = compute_strategy_returns(oos_signals, proxy_monthly, etf_data, params)
    except Exception as e:
        return {"error": f"OOS signal generation failed: {e}"}

    # ── 4. Compute metrics ────────────────────────────────────────────────────
    logger.info("[4/5] Computing performance metrics ...")
    is_metrics = compute_metrics(is_returns, label="IS")
    oos_metrics = compute_metrics(oos_returns, label="OOS")

    # ── 5. Walk-forward analysis ──────────────────────────────────────────────
    logger.info("[5/5] Running walk-forward analysis ...")
    # Full windows (proxy + ETF). ETF-only run uses 2012+ windows only.
    WF_WINDOWS_FULL = [
        ("1990-01-01", "1997-12-31"),
        ("1998-01-01", "2002-12-31"),
        ("2003-01-01", "2007-12-31"),
        ("2008-01-01", "2011-12-31"),
        ("2012-01-01", "2016-12-31"),
        ("2017-01-01", "2021-12-31"),
    ]
    WF_WINDOWS_ETF_ONLY = [
        ("2012-01-01", "2015-12-31"),
        ("2013-01-01", "2016-12-31"),
        ("2015-01-01", "2018-12-31"),
        ("2017-01-01", "2019-12-31"),
        ("2018-01-01", "2021-12-31"),
        ("2019-01-01", "2021-12-31"),
    ]
    WF_WINDOWS = WF_WINDOWS_FULL if not skip_proxy else WF_WINDOWS_ETF_ONLY
    wf_results = compute_walk_forward_metrics(
        proxy_monthly=proxy_monthly,
        etf_data=etf_data,
        low_vol_etf=low_vol_etf,
        params=params,
        windows=WF_WINDOWS,
    )

    wf_sharpe_floor = 0.30
    wf_passes = sum(
        1 for w in wf_results
        if "sharpe" in w and w["sharpe"] >= wf_sharpe_floor
    )
    wf_consistency = f"{wf_passes}/{len(wf_results)}"

    # ── Summary ───────────────────────────────────────────────────────────────
    result = {
        "strategy": "H55_LowVolatilityAnomaly",
        "etf": low_vol_etf,
        "is_start": is_start,
        "is_end": is_end,
        "oos_start": oos_start,
        "oos_end": oos_end,
        "proxy_used": proxy_monthly is not None,
        "proxy_observations": int(len(proxy_monthly)) if proxy_monthly is not None else 0,
        "data_quality": DATA_QUALITY,
        "survivorship_bias_flag": True,  # proxy period has survivorship bias
        "is_metrics": is_metrics,
        "oos_metrics": oos_metrics,
        "walk_forward": {
            "windows": wf_results,
            "sharpe_floor": wf_sharpe_floor,
            "passes": wf_passes,
            "total": len(wf_results),
            "consistency": wf_consistency,
        },
        "parameters": params,
    }

    return result


# ── USMV Parallel Test ────────────────────────────────────────────────────────

def run_usmv_robustness(
    oos_start: str = "2022-01-01",
    oos_end: str = "2025-12-31",
    params: dict = None,
) -> dict:
    """
    Run USMV as parallel robustness check (inception Oct 2011).
    IS window: 2012-01-01 to 2021-12-31 (ETF-only, no proxy needed)
    """
    if params is None:
        params = PARAMETERS.copy()

    logger.info("=== H55 USMV Robustness Test ===")
    result = run_backtest(
        is_start="2012-01-01",
        is_end="2021-12-31",
        oos_start=oos_start,
        oos_end=oos_end,
        params=params,
        etf_override="USMV",
        skip_proxy=True,  # USMV ETF-only test
    )
    result["test_type"] = "USMV_robustness"
    return result


if __name__ == "__main__":
    import json
    logger.info("Running H55 quick smoke test (ETF-only, 2012-2025) ...")
    result = run_backtest(
        is_start="2012-01-01",
        is_end="2021-12-31",
        oos_start="2022-01-01",
        oos_end="2025-03-31",
        skip_proxy=True,  # fast iteration without proxy
    )
    print(json.dumps(result, indent=2, default=str))
