"""
Strategy: H08 Crypto Momentum — BTC/ETH EMA Crossover
Author: Strategy Coder Agent
Date: 2026-03-16
Hypothesis: BTC and ETH exhibit persistent trend-following properties driven by retail
            FOMO, slow institutional adoption cycles, and absence of market-maker
            circuit breakers. Dual EMA crossover (fast/slow) on each asset independently
            generates long or flat signals; 50/50 BTC/ETH capital split; long-only.
Asset class: crypto
Parent task: QUA-118
Reference: Liu & Tsyvinski (2021) "Risks and Returns of Cryptocurrency" — RFS;
           Cong, Tang & Wang (2021) "Crypto Wash Trading"

LIVE IMPLEMENTATION NOTE:
    Backtest uses spot BTC/ETH prices (Yahoo Finance: BTC-USD, ETH-USD).
    Live trading via BITO (BTC futures ETF) incurs ~10-20%/year contango roll drag
    during bull regimes (Risk Director review QUA-106). Spot backtest returns will
    exceed live BITO-based returns, particularly during the 2020-2021 bull market.
    FETH (Fidelity ETH ETF) launched July 2024 — not suitable for IS backtesting.
"""

import warnings
import numpy as np
import pandas as pd
import vectorbt as vbt
import yfinance as yf

# All tunable parameters exposed here for sensitivity scanning
PARAMETERS = {
    "universe": ["BTC-USD", "ETH-USD"],
    "ema_fast_period": 20,       # Fast EMA window (days)
    "ema_slow_period": 60,       # Slow EMA window (days)
    "trailing_stop_pct": 0.15,   # Trailing stop: exit if price < (peak × (1 - stop))
    "capital_split_btc": 0.50,   # Fraction of init_cash allocated to BTC
    "capital_split_eth": 0.50,   # Fraction of init_cash allocated to ETH
    "init_cash": 25000,          # Starting capital ($)
}

# Canonical crypto transaction cost model (no market impact — BTC/ETH always liquid)
CRYPTO_FEES = 0.001      # 0.10% taker fee
CRYPTO_SLIPPAGE = 0.0005  # 0.05% slippage
# Total effective cost: 0.15% per leg, 0.30% per round trip

TRADING_DAYS_PER_YEAR = 252


# ── Data Loading ──────────────────────────────────────────────────────────────

def download_crypto_data(
    tickers: list[str], start: str, end: str
) -> pd.DataFrame:
    """
    Download adjusted daily close prices for crypto tickers via yfinance.

    Yahoo Finance provides BTC-USD from 2014+ and ETH-USD from 2016+.
    Both fully cover the 2018-01-01 backtest start date.
    auto_adjust=True: prices adjusted for any splits (rare for crypto).

    Returns:
        close: DataFrame of adjusted closing prices, columns = tickers
    """
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        # Single-ticker fallback
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})

    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])

    available = [t for t in tickers if t in close.columns]
    return close[available].copy()


# ── Data Quality Checklist ────────────────────────────────────────────────────

def check_data_quality(close: pd.DataFrame) -> dict:
    """
    Run data quality checks per the Engineering Director checklist.

    Data quality notes (documented per spec):
    - Survivorship bias: BTC and ETH are the two largest cryptocurrencies.
      Both have been continuously trading since before 2018. No survivorship bias.
    - Price adjustments: yfinance auto_adjust=True.
    - Earnings exclusion: N/A — crypto assets have no earnings events.
    - Delisted: N/A — BTC and ETH cannot be delisted from the crypto market.
    - Data gaps: Crypto trades 24/7 but Yahoo Finance daily bars may have calendar gaps.
      Flagged if >5 missing calendar days (note: not business days for crypto).
    """
    report = {
        "survivorship_bias": (
            "BTC-USD: trading since 2009. ETH-USD: trading since 2015. "
            "Both fully available for 2018-01-01 to 2023-12-31 backtest window. "
            "No survivorship bias — neither can be delisted from the universe."
        ),
        "price_source": "yfinance BTC-USD, ETH-USD with auto_adjust=True.",
        "earnings_exclusion": "N/A — crypto assets have no earnings events.",
        "delisted": "N/A — BTC and ETH are not subject to exchange delisting.",
        "tickers": {},
    }

    for ticker in close.columns:
        price = close[ticker].dropna()
        if price.empty:
            report["tickers"][ticker] = {"error": "No data returned"}
            continue

        # Crypto trades 24/7; check calendar days (not business days)
        expected = pd.date_range(start=price.index.min(), end=price.index.max(), freq="D")
        missing_count = len(expected.difference(price.index))

        report["tickers"][ticker] = {
            "total_bars": len(price),
            "missing_calendar_days": missing_count,
            "gap_flag": missing_count > 5,
            "start": str(price.index.min().date()),
            "end": str(price.index.max().date()),
        }
        if missing_count > 5:
            warnings.warn(
                f"Data gap: {ticker} has {missing_count} missing calendar days "
                f"({price.index.min().date()} to {price.index.max().date()})."
            )

    return report


# ── EMA Signal Generation ─────────────────────────────────────────────────────

def compute_ema_signals(
    price: pd.Series, fast: int, slow: int
) -> tuple[pd.Series, pd.Series]:
    """
    Compute dual-EMA crossover entry/exit signals for a single price series.

    EMA formula: uses adjust=False (standard recursive EMA) — no look-ahead.
    EMA_t = alpha * price_t + (1 - alpha) * EMA_{t-1}
    where alpha = 2 / (span + 1)

    Signal logic:
    - Entry: EMA_fast crosses ABOVE EMA_slow (prev bar: fast ≤ slow; curr bar: fast > slow)
    - Exit:  EMA_fast crosses BELOW EMA_slow (prev bar: fast > slow; curr bar: fast ≤ slow)

    Signals are shifted +1 bar for next-open execution:
    signal at close T → execution at open T+1 (no same-bar fill; no look-ahead).

    Returns:
        entries: Boolean Series, True on entry bar
        exits:   Boolean Series, True on exit bar
    """
    ema_fast = price.ewm(span=fast, adjust=False).mean()
    ema_slow = price.ewm(span=slow, adjust=False).mean()

    # Crossover at bar T (evaluated at close T)
    cross_up = (ema_fast.shift(1) <= ema_slow.shift(1)) & (ema_fast > ema_slow)
    cross_down = (ema_fast.shift(1) > ema_slow.shift(1)) & (ema_fast <= ema_slow)

    # Shift +1 for next-bar execution; fills NaN at bar 0 with False
    entries = cross_up.shift(1).fillna(False).astype(bool)
    exits = cross_down.shift(1).fillna(False).astype(bool)

    return entries, exits


# ── Per-Asset Strategy Runner ─────────────────────────────────────────────────

def run_single_asset(
    price: pd.Series, params: dict, init_cash: float
) -> vbt.Portfolio:
    """
    Run EMA crossover with trailing stop on a single crypto asset.

    tsl_stop in vectorbt implements: exit if price < (highest_price_since_entry × (1 - tsl_stop)).
    This matches the hypothesis trailing stop specification exactly.

    Transaction costs:
    - fees=0.001 (0.10% taker fee per leg)
    - slippage=0.0005 (0.05% per leg)
    - No market impact (BTC/ETH ADV >> any $25K order)
    """
    entries, exits = compute_ema_signals(
        price,
        fast=params["ema_fast_period"],
        slow=params["ema_slow_period"],
    )

    pf = vbt.Portfolio.from_signals(
        price,
        entries=entries,
        exits=exits,
        tsl_stop=params["trailing_stop_pct"],
        fees=CRYPTO_FEES,
        slippage=CRYPTO_SLIPPAGE,
        init_cash=init_cash,
    )

    return pf


# ── Correlation Monitoring ────────────────────────────────────────────────────

def compute_btc_eth_correlation(close: pd.DataFrame) -> dict:
    """
    Track BTC/ETH rolling 30-day daily return correlation.

    Per Risk Director review QUA-106: BTC/ETH correlation ~0.8+ may cause
    synchronized drawdowns (both assets hitting stops simultaneously), potentially
    exceeding the 20% combined portfolio max drawdown Gate 1 threshold.

    Returns dict with average/max rolling correlation and flag status.
    """
    btc_cols = [c for c in close.columns if "BTC" in c.upper()]
    eth_cols = [c for c in close.columns if "ETH" in c.upper()]

    if not btc_cols or not eth_cols:
        return {"note": "BTC or ETH not in universe — correlation check skipped."}

    btc_col, eth_col = btc_cols[0], eth_cols[0]
    returns = close[[btc_col, eth_col]].pct_change()
    rolling_corr = returns[btc_col].rolling(30).corr(returns[eth_col]).dropna()

    if rolling_corr.empty:
        return {"note": "Insufficient data for rolling correlation."}

    avg_corr = float(rolling_corr.mean())
    max_corr = float(rolling_corr.max())

    result = {
        "btc_eth_avg_30d_corr": round(avg_corr, 4),
        "btc_eth_max_30d_corr": round(max_corr, 4),
        "high_correlation_flag": avg_corr > 0.7,
    }

    if avg_corr > 0.7:
        warnings.warn(
            f"BTC/ETH avg 30d correlation {avg_corr:.2f} > 0.7. "
            "Simultaneous drawdowns possible — verify combined portfolio MDD < 20%. "
            "(Per Risk Director review QUA-106)"
        )

    return result


# ── Strategy Runner ───────────────────────────────────────────────────────────

def run_strategy(
    universe: list[str] | None = None,
    start: str = "2018-01-01",
    end: str = "2023-12-31",
    params: dict = PARAMETERS,
    return_portfolio: bool = False,
) -> dict:
    """
    Run H08 Crypto Momentum BTC/ETH EMA Crossover strategy and return a metrics dict.

    Runs each asset independently with its allocated capital share (50/50 default),
    then aggregates portfolio-level metrics by summing asset equity curves.

    Transaction cost model (canonical crypto):
    - Taker fee: 0.10% per leg
    - Slippage: 0.05% per leg
    - Market impact: N/A (BTC/ETH always liquid at $25K order sizes)

    Risk Director flags checked:
    1. BTC/ETH correlation → combined portfolio max drawdown
    2. Trade count must exceed 50 (automatic disqualification if below)
    3. Win rate < 50% → win/loss ratio must be > 1.2

    Returns:
        Metrics dict: Sharpe, MDD, win rate, win/loss ratio, trade count,
        per-asset trade counts, BTC/ETH correlation report, data quality,
        contango note.
        If return_portfolio=True, also includes 'portfolios' dict of per-asset
        vbt.Portfolio objects.

    Raises:
        ValueError: if no price data or insufficient history for EMA computation.
    """
    if universe is None:
        universe = params.get("universe", PARAMETERS["universe"])

    close = download_crypto_data(universe, start, end)
    quality_report = check_data_quality(close)

    close = close.dropna(axis=1, how="all")
    if close.empty:
        raise ValueError(f"No price data for {universe} in {start}–{end}.")

    min_required = params["ema_slow_period"] + 10
    if len(close) < min_required:
        raise ValueError(
            f"Insufficient data: need ≥{min_required} bars for EMA({params['ema_slow_period']}), "
            f"got {len(close)}."
        )

    # Capital allocation per asset
    init_cash = params.get("init_cash", 25000)
    btc_cols = [c for c in close.columns if "BTC" in c.upper()]
    eth_cols = [c for c in close.columns if "ETH" in c.upper()]

    capital_map = {}
    for ticker in close.columns:
        if ticker in btc_cols:
            capital_map[ticker] = init_cash * params.get("capital_split_btc", 0.50)
        elif ticker in eth_cols:
            capital_map[ticker] = init_cash * params.get("capital_split_eth", 0.50)
        else:
            capital_map[ticker] = init_cash / len(close.columns)

    # Run per-asset portfolios
    portfolios: dict[str, vbt.Portfolio] = {}
    for ticker in close.columns:
        pf = run_single_asset(close[ticker], params, capital_map[ticker])
        portfolios[ticker] = pf

    # Aggregate combined portfolio equity (sum of per-asset value curves)
    combined_value = sum(pf.value() for pf in portfolios.values())
    combined_returns = combined_value.pct_change().dropna()

    # Sharpe ratio (annualized)
    if combined_returns.std() > 0:
        sharpe = float(combined_returns.mean() / combined_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    # Max drawdown (combined portfolio)
    rolling_peak = combined_value.cummax()
    drawdown = (combined_value - rolling_peak) / rolling_peak
    mdd = float(drawdown.min())

    # Total return
    total_return = float((combined_value.iloc[-1] / combined_value.iloc[0]) - 1)

    # Trade count (sum across assets)
    per_asset_trades = {t: int(pf.trades.count()) for t, pf in portfolios.items()}
    trade_count = sum(per_asset_trades.values())

    # Win rate and win/loss ratio (combined across all assets)
    all_pnl: list[float] = []
    for pf in portfolios.values():
        try:
            pnl = np.array(pf.trades.pnl.to_pandas()).flatten()
            all_pnl.extend(pnl[~np.isnan(pnl)].tolist())
        except Exception:
            pass

    pnl_arr = np.array(all_pnl)
    if len(pnl_arr) > 0:
        win_rate = float(np.mean(pnl_arr > 0))
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr < 0]
        avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
        win_loss_ratio = avg_win / avg_loss if avg_loss != 0 else float("inf")
    else:
        win_rate, win_loss_ratio = 0.0, 0.0

    # Risk Director flag checks (per QUA-106 and criteria.md)
    if win_rate < 0.50 and win_loss_ratio < 1.2:
        warnings.warn(
            f"Win rate {win_rate:.1%} < 50% AND win/loss ratio {win_loss_ratio:.2f} < 1.2. "
            "Gate 1 requires win rate > 50% OR avg_win / avg_loss > 1.2."
        )
    if trade_count < 50:
        warnings.warn(
            f"Trade count {trade_count} < 50 minimum threshold. "
            "Automatic disqualification risk per criteria.md."
        )
    if mdd < -0.20:
        warnings.warn(
            f"Combined portfolio max drawdown {mdd:.1%} < -20% IS threshold. "
            "BTC/ETH high correlation may be amplifying simultaneous drawdowns."
        )

    corr_report = compute_btc_eth_correlation(close)

    result = {
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "win_loss_ratio": win_loss_ratio,
        "total_return": total_return,
        "trade_count": trade_count,
        "per_asset_trades": per_asset_trades,
        "period": f"{start} to {end}",
        "tickers_traded": list(close.columns),
        "btc_eth_correlation": corr_report,
        "data_quality": quality_report,
        "contango_note": (
            "LIVE IMPLEMENTATION NOTE: Backtest uses spot BTC/ETH prices. "
            "BITO (BTC futures ETF) incurs ~10-20%/year contango drag in bull regimes "
            "(per Risk Director review QUA-106). Spot backtest returns exceed live BITO returns."
        ),
    }

    if return_portfolio:
        result["portfolios"] = portfolios

    return result


# ── Parameter Sensitivity Scans ───────────────────────────────────────────────

def scan_ema_combinations(
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """
    Run all 4×4 = 16 EMA (fast, slow) combinations per QUA-118 spec.

    fast_periods: [10, 15, 20, 30]
    slow_periods: [40, 50, 60, 90]

    All 16 combinations are valid (max fast=30 < min slow=40).

    Gate 1 disqualification criterion: Sharpe variance > 30% across combinations.
    Variance is measured as (max_sharpe - min_sharpe) / |mean_sharpe|.
    """
    fast_periods = [10, 15, 20, 30]
    slow_periods = [40, 50, 60, 90]

    results: dict = {}
    for fast in fast_periods:
        for slow in slow_periods:
            key = f"ema_{fast}_{slow}"
            p = {**base_params, "ema_fast_period": fast, "ema_slow_period": slow}
            try:
                r = run_strategy(start=start, end=end, params=p)
                results[key] = round(r["sharpe"], 4)
            except Exception as exc:
                results[key] = f"error: {exc}"

    # Gate 1 Sharpe variance check across all 16 combinations
    sharpe_vals = [v for v in results.values() if isinstance(v, float) and not np.isnan(v)]
    if len(sharpe_vals) > 1:
        sharpe_range = max(sharpe_vals) - min(sharpe_vals)
        sharpe_mean = np.mean(sharpe_vals)
        variance_pct = sharpe_range / abs(sharpe_mean) if sharpe_mean != 0 else float("inf")
        results["_sharpe_range"] = round(sharpe_range, 4)
        results["_sharpe_variance_pct"] = round(variance_pct, 4)
        if variance_pct > 0.30:
            results["_gate1_variance_flag"] = (
                f"FAIL: Sharpe variance {variance_pct:.1%} > 30% across 16 EMA combinations — "
                "automatic disqualification per criteria.md parameter robustness requirement."
            )
        else:
            results["_gate1_variance_flag"] = (
                f"PASS: Sharpe variance {variance_pct:.1%} ≤ 30% across 16 EMA combinations."
            )

    return results


def scan_trailing_stops(
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """Scan trailing stop values: [0.10, 0.15, 0.20, 0.25]."""
    results: dict = {}
    for stop in [0.10, 0.15, 0.20, 0.25]:
        p = {**base_params, "trailing_stop_pct": stop}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[f"stop_{int(stop * 100)}pct"] = round(r["sharpe"], 4)
        except Exception as exc:
            results[f"stop_{int(stop * 100)}pct"] = f"error: {exc}"
    return results


def scan_capital_splits(
    start: str = "2018-01-01",
    end: str = "2021-12-31",
    base_params: dict = PARAMETERS,
) -> dict:
    """Scan capital splits: [100/0, 75/25, 50/50] BTC/ETH."""
    splits = [
        (1.0, 0.0, "btc_only_100_0"),
        (0.75, 0.25, "btc_eth_75_25"),
        (0.50, 0.50, "btc_eth_50_50"),
    ]
    results: dict = {}
    for btc_frac, eth_frac, label in splits:
        p = {**base_params, "capital_split_btc": btc_frac, "capital_split_eth": eth_frac}
        try:
            r = run_strategy(start=start, end=end, params=p)
            results[label] = round(r["sharpe"], 4)
        except Exception as exc:
            results[label] = f"error: {exc}"
    return results


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="H08 Crypto Momentum BTC/ETH EMA Crossover backtest runner."
    )
    parser.add_argument(
        "--plot", action="store_true",
        help="Open interactive Plotly charts for IS backtest per-asset portfolios.",
    )
    parser.add_argument(
        "--scan-ema", action="store_true",
        help="Run all 16 EMA (fast, slow) combinations (Gate 1 required).",
    )
    parser.add_argument(
        "--scan-all", action="store_true",
        help="Run all parameter scans (EMA, trailing stop, capital split).",
    )
    args = parser.parse_args()

    print("Running IS backtest (2018-01-01 to 2021-12-31)...")
    is_result = run_strategy(start="2018-01-01", end="2021-12-31", return_portfolio=args.plot)
    safe = {k: v for k, v in is_result.items() if k not in ("portfolios", "data_quality")}
    print("IS:", safe)

    if args.plot:
        for ticker, pf in is_result.get("portfolios", {}).items():
            print(f"\nPlotting {ticker}...")
            pf.plot().show()

    print("\nRunning OOS backtest (2022-01-01 to 2023-12-31)...")
    oos_result = run_strategy(start="2022-01-01", end="2023-12-31")
    safe_oos = {k: v for k, v in oos_result.items() if k not in ("data_quality",)}
    print("OOS:", safe_oos)

    print("\nBTC/ETH correlation (IS):")
    print(is_result.get("btc_eth_correlation", {}))

    print("\nData quality report:")
    for ticker, info in is_result.get("data_quality", {}).get("tickers", {}).items():
        print(f"  {ticker}: {info}")

    if args.scan_ema or args.scan_all:
        print("\nRunning 16 EMA combinations scan (Gate 1 required)...")
        ema_scan = scan_ema_combinations()
        for k, v in sorted(ema_scan.items()):
            print(f"  {k}: {v}")

    if args.scan_all:
        print("\nRunning trailing stop scan...")
        stop_scan = scan_trailing_stops()
        print(stop_scan)

        print("\nRunning capital split scan...")
        split_scan = scan_capital_splits()
        print(split_scan)
