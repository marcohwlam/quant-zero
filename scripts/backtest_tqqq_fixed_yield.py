"""Exploratory backtest: TQQQ when QQQ > 200SMA, fixed-yield cash otherwise (QUA-889 follow-up).

Off-state earns a constant annual yield (daily accrual /252), no trading cost on the off leg.
Signal on daily close, applied next bar. Cost 10 bps per side on the risk leg. Sharpe uses rf=0.
"""
import json
import pandas as pd
import yfinance as yf

from backtest_tqqq_weekly_rsi import stats, COST, IS_END

YIELDS = [0.0, 0.04, 0.06, 0.08]


def run(rets, gate, risk, y):
    w = gate.astype(float).shift(1).fillna(0)
    net = w * rets[risk] + (1 - w) * (y / 252) - w.diff().abs().fillna(0) * COST
    return {lab: stats(net.loc[sl], w.loc[sl]) for lab, sl in
            (("full", slice(None)), ("IS", slice(None, IS_END)), ("OOS", slice(IS_END, None)),
             ("2022", slice("2022-01-01", "2022-12-31")))}


def main():
    raw = yf.download(["TQQQ", "QQQ"], start="2009-01-01", auto_adjust=True, progress=False)["Close"].dropna()
    rets = raw.pct_change()
    gate = raw["QQQ"] > raw["QQQ"].rolling(200).mean()
    keep = raw.index >= "2010-02-11"
    rets, gate = rets[keep], gate[keep]
    res = {"TQQQ_buy_hold": {"full": stats(rets["TQQQ"], pd.Series(1.0, index=rets.index))},
           "QQQ_buy_hold": {"full": stats(rets["QQQ"], pd.Series(1.0, index=rets.index))}}
    for risk in ("TQQQ", "QQQ"):
        for y in YIELDS:
            res[f"{risk}_gate_y{int(y*100)}"] = run(rets, gate, risk, y)
    print(f"{rets.index[0].date()} -> {rets.index[-1].date()}  off-days {(~gate).mean():.1%}")
    for k, v in res.items():
        f = v["full"]
        print(f"{k:16s} CAGR {f['cagr']:.3f} Sh {f['sharpe']:.2f} MDD {f['mdd']:.3f} tr {f['trades']}",
              "" if "IS" not in v else f"| IS {v['IS']['sharpe']} OOS {v['OOS']['sharpe']} 2022 CAGR {v['2022']['cagr']} MDD {v['2022']['mdd']}")
    with open("../backtests/tqqq_fixed_yield_2026-11-06.json", "w") as fh:
        json.dump(res, fh, indent=1)


if __name__ == "__main__":
    main()
