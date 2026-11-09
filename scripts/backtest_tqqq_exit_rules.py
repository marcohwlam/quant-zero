"""Exploratory backtest: exit rules for a TQQQ satellite position (QUA-889 follow-up).

Signals use daily closes and are applied from the next daily bar. Cost: 10 bps per side.
Out-of-market capital earns 0%.
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf

from backtest_tqqq_weekly_rsi import stats, COST, IS_END


def sim(df, gate, trail=None):
    """gate: bool Series (entry allowed). trail: trailing stop fraction from peak since entry."""
    pos = np.zeros(len(df))
    state, peak, stopped = 0, 0.0, False
    c, g = df["Close"].values, gate.values
    for i in range(len(df)):
        if state == 1:
            peak = max(peak, c[i])
            hit = bool(trail) and c[i] <= peak * (1 - trail)
            if (not g[i]) or hit:
                state, stopped = 0, hit
        else:
            # after a trail stop, wait for gate to turn off then on again (fresh trend)
            if stopped and not g[i]:
                stopped = False
            if g[i] and not stopped:
                state, peak = 1, c[i]
        pos[i] = state
    pos = pd.Series(pos, index=df.index).shift(1).fillna(0)
    net = pos * df["ret"] - pos.diff().abs().fillna(0) * COST
    return {lab: stats(net.loc[sl], pos.loc[sl]) for lab, sl in
            (("full", slice(None)), ("IS", slice(None, IS_END)), ("OOS", slice(IS_END, None)))}


def main():
    raw = yf.download(["TQQQ", "QQQ"], start="2009-01-01", auto_adjust=True, progress=False)["Close"]
    df = pd.DataFrame({"Close": raw["TQQQ"], "q": raw["QQQ"]}).dropna()
    df["ret"] = df["Close"].pct_change()
    df["q200"] = df["q"].rolling(200).mean()
    df["t200"] = df["Close"].rolling(200).mean()
    df["t50"] = df["Close"].rolling(50).mean()
    df = df.loc["2010-02-11":]
    qg = df["q"] > df["q200"]
    tg = df["Close"] > df["t200"]
    always = pd.Series(True, index=df.index)
    res = {"buy_hold": stats(df["ret"], pd.Series(1.0, index=df.index))}
    res["TQQQ<200SMA"] = sim(df, tg)
    res["QQQ<200SMA"] = sim(df, qg)
    res["QQQ<200SMA+trail35"] = sim(df, qg, 0.35)
    res["QQQ<200SMA+trail25"] = sim(df, qg, 0.25)
    res["QQQ200&TQQQ>50SMA"] = sim(df, qg & (df["Close"] > df["t50"]))
    # QQQ unleveraged with 200SMA gate for comparison
    qdf = df.assign(Close=df["q"], ret=df["q"].pct_change())
    res["QQQ_buy_hold"] = stats(qdf["ret"], pd.Series(1.0, index=df.index))
    res["QQQ_200SMA_gate"] = sim(qdf, qg)
    print(f"{df.index[0].date()} -> {df.index[-1].date()}")
    for k, v in res.items():
        f = v.get("full", v)
        print(f"{k:22s} CAGR {f['cagr']:.3f} Vol {f['vol']:.3f} Sh {f['sharpe']:.2f} MDD {f['mdd']:.3f} tr {f['trades']} exp {f['exposure']}",
              "" if "IS" not in v else f"| IS Sh {v['IS'].get('sharpe')} OOS Sh {v['OOS'].get('sharpe')}")
    with open("../backtests/tqqq_exit_rules_2026-11-06.json", "w") as fh:
        json.dump(res, fh, indent=1)


if __name__ == "__main__":
    main()
