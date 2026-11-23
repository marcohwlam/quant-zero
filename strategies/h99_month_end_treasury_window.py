"""
H99 Month-End Treasury Window (QUA-989).

Long a Treasury instrument from the close of the (n+1)-th last trading day of each month
to the close of the last trading day (n return days held). Cash otherwise.
Costs: 5 bps per side, applied on the entry day and the exit day.
"""

import numpy as np
import pandas as pd

PARAMETERS = {
    "window_days": 3,     # n return days held; n=3 primary, 4 and 5 sensitivity
    "cost_per_side": 0.0005,
}


def window_positions(index: pd.DatetimeIndex, n: int) -> pd.DataFrame:
    """Return one row per month with entry (close of n+1-th last day) and exit (last day) dates."""
    rows = []
    for _, idx in index.to_series().groupby(index.to_period("M")):
        if len(idx) < n + 2:
            continue
        rows.append((idx.iloc[-(n + 1)], idx.iloc[-1]))
    return pd.DataFrame(rows, columns=["entry", "exit"])


def window_returns(close: pd.Series, n: int, cost: float) -> tuple[pd.Series, pd.DataFrame]:
    """Daily strategy return series (0 outside the window) and a per-window trade log."""
    close = close.dropna()
    px_ret = close.pct_change()
    daily = pd.Series(0.0, index=close.index)
    trades = []
    for _, (a, b) in window_positions(close.index, n).iterrows():
        seg = px_ret.loc[a:b].iloc[1:]
        daily.loc[seg.index] = seg.values
        daily.loc[seg.index[0]] -= cost
        daily.loc[seg.index[-1]] -= cost
        gross = close.loc[b] / close.loc[a] - 1
        trades.append(dict(entry=a, exit=b, entry_px=float(close.loc[a]), exit_px=float(close.loc[b]),
                           gross_ret=float(gross), net_ret=float((1 + gross) * (1 - cost) ** 2 - 1)))
    return daily, pd.DataFrame(trades)
