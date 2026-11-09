"""Exploratory backtest: weekly RSI rules on TQQQ (QUA-889).

Signals use completed weekly bars (W-FRI) and are applied from the next daily bar.
Cost: 10 bps per side on each position change (criteria.md equity round-trip ~10 bps is
conservative-low for a 3x ETF; 10 bps/side is used here).
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf

COST = 0.0010
IS_END = "2019-12-31"


def wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn)


def stats(ret: pd.Series, pos: pd.Series) -> dict:
    ret = ret.dropna()
    if ret.empty:
        return {}
    eq = (1 + ret).cumprod()
    yrs = len(ret) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = ret.std() * np.sqrt(252)
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0
    mdd = (eq / eq.cummax() - 1).min()
    trades = int(((pos.diff().fillna(pos) > 0)).sum())
    return dict(cagr=round(cagr, 4), vol=round(vol, 4), sharpe=round(sharpe, 3),
                mdd=round(mdd, 4), trades=trades, exposure=round(pos.mean(), 3))


def run(df, rsi_w, name, entry, exit_):
    pos_w = pd.Series(np.nan, index=rsi_w.index)
    state = 0
    for t, r in rsi_w.items():
        if np.isnan(r):
            pos_w[t] = 0
            continue
        if state == 0 and entry(r):
            state = 1
        elif state == 1 and exit_(r):
            state = 0
        pos_w[t] = state
    # weekly bar dated Friday close; hold from next daily bar
    pos = pos_w.reindex(df.index, method="ffill").shift(1).fillna(0)
    gross = pos * df["ret"]
    net = gross - pos.diff().abs().fillna(0) * COST
    out = {}
    for label, sl in (("full", slice(None)), ("IS", slice(None, IS_END)), ("OOS", slice(IS_END, None))):
        out[label] = stats(net.loc[sl], pos.loc[sl])
    return name, out


def main():
    df = yf.download("TQQQ", start="2010-01-01", auto_adjust=True, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df["ret"] = df["Close"].pct_change()
    wk = df["Close"].resample("W-FRI").last().dropna()
    rsi_w = wilder_rsi(wk, 14)
    rsi_w = rsi_w.reindex(rsi_w.index)

    results = {}
    results["buy_hold"] = stats(df["ret"], pd.Series(1.0, index=df.index))
    for name, en, ex in [
        ("trend_RSI>50_in__<45_out", lambda r: r > 50, lambda r: r < 45),
        ("trend_RSI>55_in__<50_out", lambda r: r > 55, lambda r: r < 50),
        ("meanrev_RSI<40_in__>60_out", lambda r: r < 40, lambda r: r > 60),
        ("meanrev_RSI<30_in__>50_out", lambda r: r < 30, lambda r: r > 50),
    ]:
        n, o = run(df, rsi_w, name, en, ex)
        results[n] = o
    print(f"Data: {df.index[0].date()} -> {df.index[-1].date()}  (IS<= {IS_END})")
    print(json.dumps(results, indent=1))
    with open("backtests/tqqq_weekly_rsi_2026-11-06.json", "w") as f:
        json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
