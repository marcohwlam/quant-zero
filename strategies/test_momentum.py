"""
TestMomentum v1.0 — Live Signal Generator
Cross-sectional momentum: rank ETFs by trailing 12-month return, hold top N.

Gate 1 approved: QUA-45 (2026-03-15)
IS Sharpe: 1.50 | OOS Sharpe: 1.10 | MDD: -12.0% | Win Rate: 55%
"""

import warnings
from datetime import date

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

PARAMETERS = {
    "universe": ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV"],
    "top_n": 2,
    "lookback_days": 252,  # 12-month trailing return
}


def get_live_signals(params: dict = None) -> dict:
    """
    Rank universe by trailing return, return top_n as buy signals.

    Returns:
        {
            "date": "YYYY-MM-DD",
            "buy":  ["SPY", "QQQ"],
            "sell": ["IWM", ...],
            "momentum_scores": {"SPY": 0.15, ...},
        }
    """
    if params is None:
        params = PARAMETERS

    universe = params["universe"]
    top_n = params["top_n"]
    lookback = params.get("lookback_days", 252)

    today = date.today().strftime("%Y-%m-%d")
    # 252 trading days ≈ 365 calendar days; add 60-day buffer for weekends/holidays
    calendar_days = int(lookback * 1.5) + 60
    start = (pd.Timestamp(today) - pd.DateOffset(days=calendar_days)).strftime("%Y-%m-%d")

    try:
        raw = yf.download(universe, start=start, end=today, auto_adjust=True, progress=False)

        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]].rename(columns={"Close": universe[0]})

        scores = {}
        for ticker in universe:
            if ticker not in close.columns:
                scores[ticker] = 0.0
                continue
            col = close[ticker].dropna()
            if len(col) < lookback:
                scores[ticker] = 0.0
                continue
            ret = float((col.iloc[-1] - col.iloc[-lookback]) / col.iloc[-lookback])
            scores[ticker] = round(ret, 6)

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        buy_tickers = [t for t, _ in ranked[:top_n]]
        sell_tickers = [t for t in universe if t not in buy_tickers]

        return {
            "date": today,
            "buy": buy_tickers,
            "sell": sell_tickers,
            "momentum_scores": scores,
        }

    except Exception as exc:
        return {
            "date": today,
            "buy": [],
            "sell": list(universe),
            "momentum_scores": {},
            "error": str(exc),
        }
