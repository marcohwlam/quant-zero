"""
Gate 1 v2.0 Threshold Calibration — Equities Intraday
Compute candidate metric distributions across 6 walk-forward windows
using 2022-2024 daily-bar data as structural proxy.

DATA CAVEAT: yfinance 1-min bars only available for last 7 days.
This script uses DAILY ADJUSTED bars (2022-2024) as a structural proxy.
Minute-level characteristics (higher turnover, higher cost-drag per trade,
finer drawdown texture) are acknowledged but not modeled here.
Thresholds derived here should be treated as conservative lower bounds —
actual minute strategies must clear higher bars in absolute cost terms.

Output:
  backtests/gate1_v2_calibration_2026-06-06.json
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Config ─────────────────────────────────────────────────────────────────────
UNIVERSE = ["SPY", "QQQ", "IWM", "AAPL", "MSFT"]

# 6 non-overlapping windows: 3m IS + 1m OOS, spaced across 2022-2024
# 6 * 4 months = 24 months of active coverage; ~2m gap between each window
WINDOWS = [
    (1, "2022-01-01", "2022-03-31", "2022-04-01", "2022-04-30"),
    (2, "2022-07-01", "2022-09-30", "2022-10-01", "2022-10-31"),
    (3, "2023-01-01", "2023-03-31", "2023-04-01", "2023-04-30"),
    (4, "2023-07-01", "2023-09-30", "2023-10-01", "2023-10-31"),
    (5, "2024-01-01", "2024-03-31", "2024-04-01", "2024-04-30"),
    (6, "2024-07-01", "2024-09-30", "2024-10-01", "2024-10-31"),
]

TRADING_DAYS_PER_YEAR = 252
RSI_PERIOD = 2
RSI_BUY_THRESHOLD = 30.0
RSI_EXIT_THRESHOLD = 50.0
POSITION_VALUE = 10_000.0   # $10k per ticker position

# Cost model — canonical per Engineering Director AGENTS.md
FIXED_COST_PER_SHARE = 0.005
SLIPPAGE_PCT = 0.0005       # 0.05% half-spread (one-way); embedded in fill price
MI_K = 0.1                  # Almgren-Chriss square-root model coefficient

# Instrument-class slippage overrides (one-way half-spread estimate)
# Replaces scalar SLIPPAGE_PCT for named instruments.
SLIPPAGE_OVERRIDES = {
    # Highly liquid intraday ETFs — $0.01 spread + 0.5 bps execution overhead
    "SPY": 0.00015,    # 0.015% = 1.5 bps one-way
    "QQQ": 0.00020,    # 0.020% = 2.0 bps one-way
    "IWM": 0.00025,    # 0.025% = 2.5 bps one-way
    # Leveraged ETFs — wider spread, higher impact
    "SPXL": 0.00060,   # 0.060% = 6 bps one-way
    "TQQQ": 0.00060,
    "UPRO": 0.00060,
    # Default for daily-bar / mid-cap (unchanged)
    "default": 0.00050,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def compute_rsi(prices: pd.Series, period: int = 2) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def round_trip_cost_bps(price: float, shares: float, adv: float, sigma: float) -> float:
    """Round-trip cost in bps. Both slippage legs already embedded in fill prices."""
    fixed_bps = 2 * FIXED_COST_PER_SHARE / price * 10_000
    mi_bps = MI_K * sigma * np.sqrt(shares / (adv + 1e-8)) * 10_000
    return fixed_bps + mi_bps


def run_rsi_strategy(close: pd.Series, volume: pd.Series,
                     start: str, end: str, ticker: str = "default") -> tuple:
    """
    RSI(2) mean-reversion strategy on daily bars.
    Long-only, next-bar fill with slippage embedded in fill prices.
    Returns (daily_net_returns: pd.Series, trades: list[dict]).
    """
    slippage = SLIPPAGE_OVERRIDES.get(ticker, SLIPPAGE_OVERRIDES["default"])

    mask = (close.index >= start) & (close.index <= end)
    p = close[mask].copy()
    v = volume[mask].copy()
    n = len(p)

    if n < RSI_PERIOD + 10:
        return pd.Series(dtype=float), []

    rsi = compute_rsi(p, RSI_PERIOD)
    # Use rolling 20-day vol/adv; fall back to sample stats for short windows
    sigma_s = p.pct_change().rolling(20, min_periods=5).std().fillna(0.02)
    adv_s = v.rolling(20, min_periods=5).mean().fillna(v.mean())

    in_trade = False
    entry_price = None
    entry_bar = None
    daily_net_pnl = np.zeros(n)
    trades = []

    for i in range(RSI_PERIOD + 1, n - 1):
        r = rsi.iloc[i]
        if np.isnan(r):
            continue

        if not in_trade and r < RSI_BUY_THRESHOLD:
            # Fill next bar with slippage premium
            entry_price = p.iloc[i + 1] * (1 + slippage)
            entry_bar = i + 1
            in_trade = True

        elif in_trade and (r > RSI_EXIT_THRESHOLD or i == n - 2):
            # Fill next bar with slippage discount
            exit_price = p.iloc[i + 1] * (1 - slippage)
            shares = POSITION_VALUE / entry_price

            sig = float(sigma_s.iloc[i]) if not np.isnan(sigma_s.iloc[i]) else 0.02
            adv = float(adv_s.iloc[i]) if not np.isnan(adv_s.iloc[i]) else 1e6

            gross_pnl = (exit_price - entry_price) * shares
            cost_bps = round_trip_cost_bps(entry_price, shares, adv, sig)
            cost_dollars = cost_bps / 10_000 * POSITION_VALUE
            net_pnl = gross_pnl - cost_dollars

            gross_bps = gross_pnl / POSITION_VALUE * 10_000
            net_bps = net_pnl / POSITION_VALUE * 10_000

            # Spread pnl evenly over holding period for daily return series
            hold = i + 1 - entry_bar + 1
            if hold > 0 and entry_bar < n:
                daily_net_pnl[entry_bar: i + 2] = net_pnl / hold

            trades.append({
                "gross_bps": round(gross_bps, 2),
                "net_bps": round(net_bps, 2),
                "cost_bps": round(cost_bps, 2),
                "hold_days": hold,
            })
            in_trade = False

    daily_returns = pd.Series(daily_net_pnl / POSITION_VALUE, index=p.index)
    return daily_returns, trades


def compute_window_metrics(window_id: int, is_start: str, is_end: str,
                            oos_start: str, oos_end: str,
                            all_data: dict) -> dict | None:
    is_trades, oos_trades = [], []
    is_ret_frames, oos_ret_frames = [], []

    for ticker, df in all_data.items():
        ir, it = run_rsi_strategy(df["Close"], df["Volume"], is_start, is_end, ticker)
        or_, ot = run_rsi_strategy(df["Close"], df["Volume"], oos_start, oos_end, ticker)
        is_trades.extend(it)
        oos_trades.extend(ot)
        if len(ir) > 0:
            is_ret_frames.append(ir.rename(ticker))
        if len(or_) > 0:
            oos_ret_frames.append(or_.rename(ticker))

    if not oos_trades or not oos_ret_frames:
        return None

    # Average daily returns across tickers (equal-weight portfolio)
    is_rets = pd.concat(is_ret_frames, axis=1).mean(axis=1).dropna()
    oos_rets = pd.concat(oos_ret_frames, axis=1).mean(axis=1).dropna()

    # 1. Net OOS Sharpe (annualized daily returns)
    oos_std = oos_rets.std()
    oos_sharpe = (float(oos_rets.mean()) / (float(oos_std) + 1e-10)
                  * np.sqrt(TRADING_DAYS_PER_YEAR))

    # 2. Net profit per trade (bps) — OOS trades
    oos_net_bps = [t["net_bps"] for t in oos_trades]
    net_ppt_bps = float(np.mean(oos_net_bps)) if oos_net_bps else 0.0

    # 3. Max intraday drawdown (OOS cumulative equity curve)
    cum = (1 + oos_rets).cumprod()
    roll_max = cum.cummax()
    max_dd_pct = float(((cum - roll_max) / (roll_max + 1e-10)).min() * 100)

    # 4. IS trade count
    is_tc = len(is_trades)

    # 5. Cost-to-gross-profit ratio (IS, using only profitable gross trades)
    is_gross_sum = sum(t["gross_bps"] for t in is_trades if t["gross_bps"] > 0)
    is_cost_sum = sum(t["cost_bps"] for t in is_trades)
    cost_ratio = min(is_cost_sum / (is_gross_sum + 1e-10), 5.0) if is_gross_sum > 0 else 1.0

    return {
        "window_id": window_id,
        "is_period": f"{is_start} to {is_end}",
        "oos_period": f"{oos_start} to {oos_end}",
        "net_oos_sharpe": round(oos_sharpe, 4),
        "net_profit_per_trade_bps": round(net_ppt_bps, 2),
        "max_intraday_drawdown_pct": round(max_dd_pct, 3),
        "is_trade_count": is_tc,
        "oos_trade_count": len(oos_trades),
        "cost_to_gross_ratio": round(float(cost_ratio), 4),
    }


def compute_distributions(results: list[dict]) -> dict:
    df = pd.DataFrame(results)
    metric_cols = [
        "net_oos_sharpe",
        "net_profit_per_trade_bps",
        "max_intraday_drawdown_pct",
        "is_trade_count",
        "cost_to_gross_ratio",
    ]
    distros = {}
    for col in metric_cols:
        vals = df[col].values.astype(float)
        distros[col] = {
            "values": [round(float(v), 4) for v in vals],
            "mean": round(float(vals.mean()), 4),
            "std": round(float(vals.std(ddof=1) if len(vals) > 1 else 0.0), 4),
            "p10": round(float(np.percentile(vals, 10)), 4),
            "p25": round(float(np.percentile(vals, 25)), 4),
            "p50": round(float(np.percentile(vals, 50)), 4),
            "p75": round(float(np.percentile(vals, 75)), 4),
            "p90": round(float(np.percentile(vals, 90)), 4),
            "min": round(float(vals.min()), 4),
            "max": round(float(vals.max()), 4),
        }
    return distros


def main():
    np.random.seed(42)
    print("=" * 65)
    print("Gate 1 v2.0 Threshold Calibration — Equities Intraday Proxy")
    print("=" * 65)
    print(f"Universe: {UNIVERSE}")
    print(f"Fetching daily data 2021-10-01 to 2024-12-31...")

    raw = {}
    for ticker in UNIVERSE:
        df = yf.download(ticker, start="2021-10-01", end="2024-12-31",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) > 100:
            raw[ticker] = df
            print(f"  {ticker}: {len(df)} trading days")

    print(f"\nRunning {len(WINDOWS)} walk-forward windows (3m IS / 1m OOS)...")
    results = []

    for wid, is0, is1, oos0, oos1 in WINDOWS:
        print(f"\nWindow {wid}: IS={is0} to {is1} | OOS={oos0} to {oos1}")
        metrics = compute_window_metrics(wid, is0, is1, oos0, oos1, raw)
        if metrics is None:
            print("  [skip] insufficient data")
            continue
        results.append(metrics)
        print(f"  Net OOS Sharpe:     {metrics['net_oos_sharpe']:.3f}")
        print(f"  Net PPT (bps):      {metrics['net_profit_per_trade_bps']:.1f}")
        print(f"  Max DrawdownOOS:    {metrics['max_intraday_drawdown_pct']:.2f}%")
        print(f"  IS Trade Count:     {metrics['is_trade_count']}")
        print(f"  OOS Trade Count:    {metrics['oos_trade_count']}")
        print(f"  Cost/Gross (IS):    {metrics['cost_to_gross_ratio']:.2%}")

    if not results:
        print("\nERROR: No results computed — check data availability")
        return {}

    print(f"\n{'='*65}")
    print("DISTRIBUTION SUMMARY")
    print(f"{'='*65}")

    distros = compute_distributions(results)
    for metric, d in distros.items():
        print(f"\n{metric}:")
        print(f"  Values: {d['values']}")
        print(f"  Mean={d['mean']:.3f}  Std={d['std']:.3f}")
        print(f"  P10={d['p10']:.3f}  P25={d['p25']:.3f}  P50={d['p50']:.3f}  "
              f"P75={d['p75']:.3f}  P90={d['p90']:.3f}")

    output = {
        "calibration_date": "2026-06-06",
        "data_source": "yfinance daily adjusted close (auto_adjust=True)",
        "data_caveat": (
            "DAILY BARS proxy for minute-level behavior. "
            "Actual minute distributions will differ: higher trade counts, "
            "higher per-trade cost drag, finer intraday drawdown texture."
        ),
        "universe": UNIVERSE,
        "n_windows": len(results),
        "strategy": "RSI(2) mean-reversion, long-only, next-bar fill",
        "cost_model": {
            "fixed_per_share": FIXED_COST_PER_SHARE,
            "slippage_overrides": SLIPPAGE_OVERRIDES,
            "market_impact": "0.1 * sigma * sqrt(Q/ADV)",
        },
        "window_results": results,
        "distributions": distros,
    }

    out_path = Path("/repos/quant-zero/backtests/gate1_v2_calibration_2026-06-06.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved: {out_path}")

    return output


if __name__ == "__main__":
    main()
