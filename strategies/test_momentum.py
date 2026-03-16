"""
Strategy: TestMomentum v1.0
Author: Engineering Director (Quant Zero)
Date: 2026-03-16
Hypothesis: ETFs exhibiting strong relative momentum over a 1-month lookback
            tend to outperform over the following month. Buy the top-ranked ETFs
            by 21-day return and hold until momentum rank degrades.
Asset class: equities (ETFs, long-only)
Parent task: QUA-62

Gate 1 Backtest Results (2018–2023):
  IS Sharpe: 1.50 | OOS Sharpe: 1.10
  IS Max DD: 12.0% | Trade Count: 200
  Win Rate: 55.0%  | Confidence: MEDIUM

NOTE: This strategy uses synthetic backtest data generated to validate the Gate 1
pipeline. Paper trading begins 2026-03-16 with $5,000 allocated capital.
Monitoring thresholds: warn at 12% DD, auto-demotion trigger at 18% DD.
"""

import vectorbt as vbt
import pandas as pd
import numpy as np
import yfinance as yf

# ── All tunable parameters exposed here for sensitivity scanning ──────────────
PARAMETERS = {
    "momentum_window": 21,       # Lookback window for momentum ranking (trading days)
    "top_n": 2,                  # Number of top-ranked ETFs to hold simultaneously
    "hold_days": 21,             # Target holding period (exit after N days)
    "stop_loss_pct": 0.05,       # Hard stop-loss: exit if price falls 5% from entry
    "min_momentum_pct": 0.02,    # Minimum 21-day return to qualify for entry (filters noise)
    "universe": ["SPY", "QQQ", "XLV", "XLF", "XLE", "IWM"],
}


# ── Signal Generation ─────────────────────────────────────────────────────────

def compute_momentum_scores(close: pd.DataFrame, window: int) -> pd.DataFrame:
    """
    Compute rolling N-day return for each ticker.
    Returns DataFrame of same shape as `close` with momentum scores.
    """
    return close.pct_change(window)


def generate_signals(
    close: pd.DataFrame,
    params: dict = PARAMETERS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generate entry and exit signals for the momentum strategy.

    Entry logic:
        On each rebalance day (every `hold_days` bars), rank tickers by
        `momentum_window`-day return. Enter top_n tickers with positive
        momentum above `min_momentum_pct`.

    Exit logic:
        Exit at next rebalance date OR when stop-loss fires.

    Args:
        close: DataFrame of closing prices (rows=dates, columns=tickers).
        params: Strategy parameter dict.

    Returns:
        entries: Boolean DataFrame — True where a long position is opened.
        exits:   Boolean DataFrame — True where a long position is closed.
    """
    momentum = compute_momentum_scores(close, params["momentum_window"])
    entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    exits = pd.DataFrame(False, index=close.index, columns=close.columns)

    # Rebalance every hold_days bars
    rebalance_idx = list(range(params["momentum_window"], len(close), params["hold_days"]))

    for i in rebalance_idx:
        date = close.index[i]
        scores = momentum.iloc[i]
        # Filter: only consider tickers above minimum momentum threshold
        qualified = scores[scores >= params["min_momentum_pct"]]
        if qualified.empty:
            # Close all positions on this rebalance if no qualified tickers
            exits.iloc[i] = True
            continue
        top_tickers = qualified.nlargest(params["top_n"]).index.tolist()
        for ticker in close.columns:
            if ticker in top_tickers:
                entries.iloc[i][ticker] = True
            else:
                # Exit on rebalance if not in top selections
                exits.iloc[i][ticker] = True

    return entries, exits


def generate_stop_loss_mask(close: pd.DataFrame, stop_loss_pct: float) -> pd.DataFrame:
    """
    Compute per-bar stop-loss exit signals.
    Fires when the current close is stop_loss_pct below the prior-bar close
    (simplified trailing stop proxy for vectorbt signal-based backtest).
    """
    daily_return = close.pct_change()
    return daily_return < -stop_loss_pct


# ── Backtest Runner ───────────────────────────────────────────────────────────

def run_backtest(
    start: str,
    end: str,
    params: dict = PARAMETERS,
    init_cash: float = 5_000.0,
    asset_class: str = "equities",
) -> dict:
    """
    Download data and run a vectorbt long-only momentum backtest.

    Returns a dict with Sharpe, max drawdown, win rate, trade count,
    and the Portfolio object.
    """
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator"))
    from quant_orchestrator import get_cost_params

    tickers = params["universe"]
    close = yf.download(tickers, start=start, end=end, auto_adjust=True)["Close"]
    close = close.dropna(how="all")

    entries, exits = generate_signals(close, params)
    stop_exits = generate_stop_loss_mask(close, params["stop_loss_pct"])
    combined_exits = exits | stop_exits

    costs = get_cost_params(asset_class)

    portfolio = vbt.Portfolio.from_signals(
        close,
        entries,
        combined_exits,
        init_cash=init_cash,
        fees=costs["fees"],
        slippage=costs["slippage"],
        freq="1D",
    )

    trades = portfolio.trades.records_readable
    total_trades = len(trades)
    winning = trades[trades["PnL"] > 0] if total_trades > 0 else pd.DataFrame()
    losing = trades[trades["PnL"] <= 0] if total_trades > 0 else pd.DataFrame()

    win_count = len(winning)
    loss_count = len(losing)
    win_rate = win_count / total_trades if total_trades > 0 else 0.0

    avg_win = winning["PnL"].mean() if len(winning) > 0 else 0.0
    avg_loss = abs(losing["PnL"].mean()) if len(losing) > 0 else 1.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

    sharpe = float(portfolio.sharpe_ratio())
    max_dd = float(abs(portfolio.max_drawdown()))

    return {
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "win_loss_ratio": win_loss_ratio,
        "trade_count": total_trades,
        "portfolio": portfolio,
    }


# ── Paper Trading Signal Generator ───────────────────────────────────────────

def get_live_signals(
    params: dict = PARAMETERS,
    lookback_days: int = 30,
) -> dict:
    """
    Generate current paper trading signals using recent market data.
    Fetches the last `lookback_days + momentum_window` days of price history,
    computes momentum scores, and returns the current top_n selections.

    Returns:
        dict with:
            'buy': list of tickers to open/maintain long positions
            'sell': list of tickers to exit
            'momentum_scores': dict of {ticker: 21d_return}
            'date': as-of date
    """
    import datetime
    tickers = params["universe"]
    fetch_days = params["momentum_window"] + lookback_days + 10  # buffer
    end_date = datetime.date.today().isoformat()
    start_date = (datetime.date.today() - datetime.timedelta(days=fetch_days * 2)).isoformat()

    close = yf.download(tickers, start=start_date, end=end_date, auto_adjust=True)["Close"]
    close = close.dropna(how="all")

    if len(close) < params["momentum_window"] + 1:
        return {"error": "Insufficient data for momentum calculation", "buy": [], "sell": list(tickers)}

    scores = compute_momentum_scores(close, params["momentum_window"]).iloc[-1]
    qualified = scores[scores >= params["min_momentum_pct"]]
    buy_tickers = qualified.nlargest(params["top_n"]).index.tolist() if not qualified.empty else []
    sell_tickers = [t for t in tickers if t not in buy_tickers]

    return {
        "buy": buy_tickers,
        "sell": sell_tickers,
        "momentum_scores": scores.to_dict(),
        "date": close.index[-1].date().isoformat(),
    }


# ── Gate 1 Metric Documentation ──────────────────────────────────────────────

GATE1_DOCUMENTED_METRICS = {
    "strategy": "TestMomentum v1.0",
    "backtest_date": "2026-03-15",
    "is_period": "2018-01-01 to 2021-12-31",
    "oos_period": "2022-01-01 to 2023-12-31",
    "is_sharpe": 1.50,
    "oos_sharpe": 1.10,
    "is_max_drawdown_pct": 12.0,
    "oos_max_drawdown_pct": 15.0,
    "win_rate_pct": 55.0,
    "trade_count": 200,           # IS trade count — confirmed > 50 threshold ✓
    # NOTE: avg_win_loss_ratio was not reported in the original backtest JSON.
    # The backtest win_rate (55%) and IS Sharpe (1.50) imply a positive expectancy,
    # which requires avg_win / avg_loss > 0.818 at minimum. However, the exact
    # win/loss ratio requires access to the per-trade PnL log, which was not
    # persisted with the original synthetic backtest run.
    # ACTION REQUIRED: Re-run `run_backtest(start='2018-01-01', end='2021-12-31')`
    # on IS data to compute the exact win_loss_ratio and update this value.
    "avg_win_loss_ratio": None,   # PENDING — see note above
    "avg_win_loss_ratio_note": (
        "Not available from original backtest report. "
        "Run run_backtest(IS window) to populate. "
        "Gate 1 approval granted by CEO without this metric (2026-03-15)."
    ),
    "post_cost_sharpe": 0.95,
    "dsr_z_score": 1.80,
    "walk_forward_pass_rate": "3/4",
    "parameter_sensitivity_max_sharpe_delta_pct": 12.0,
    "gate1_status": "PASS",
    "gate1_confidence": "MEDIUM",
    "gate1_approval_issue": "QUA-45",
    "paper_trading_start": "2026-03-16",
    "capital_allocated_usd": 5000,
    "demotion_drawdown_threshold_pct": 18.0,
    "warning_drawdown_threshold_pct": 12.0,
}


if __name__ == "__main__":
    print("TestMomentum v1.0 — Live Signal Check")
    signals = get_live_signals()
    if "error" in signals:
        print(f"  Error: {signals['error']}")
    else:
        print(f"  As-of date : {signals['date']}")
        print(f"  BUY        : {signals['buy']}")
        print(f"  SELL/HOLD  : {signals['sell']}")
        print("  Momentum scores:")
        for ticker, score in sorted(signals["momentum_scores"].items(), key=lambda x: -x[1]):
            print(f"    {ticker:6s}  {score:+.2%}")
