"""Exploratory backtest: TQQQ when QQQ > 200SMA, bond ETF otherwise (QUA-889 follow-up).

Signal on daily close, applied next bar. Cost 10 bps per side per leg traded. Sharpe uses rf=0.
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf

from backtest_tqqq_weekly_rsi import stats, COST, IS_END

BONDS = ["BIL", "SHY", "IEF", "TLT"]


def rotate(rets, gate, risk, off):
    w = gate.astype(float).shift(1).fillna(0)
    cost = w.diff().abs().fillna(0) * 2 * COST if off else w.diff().abs().fillna(0) * COST
    r_off = rets[off] if off else 0.0
    net = w * rets[risk] + (1 - w) * r_off - cost
    out = {lab: stats(net.loc[sl], w.loc[sl]) for lab, sl in
           (("full", slice(None)), ("IS", slice(None, IS_END)), ("OOS", slice(IS_END, None)),
            ("2022", slice("2022-01-01", "2022-12-31")))}
    return out, net


def main():
    tk = ["TQQQ", "QQQ"] + BONDS
    raw = yf.download(tk, start="2009-01-01", auto_adjust=True, progress=False)["Close"].dropna()
    rets = raw.pct_change()
    gate = raw["QQQ"] > raw["QQQ"].rolling(200).mean()
    keep = raw.index >= "2010-02-11"
    rets, gate = rets[keep], gate[keep]
    res = {"TQQQ_buy_hold": {"full": stats(rets["TQQQ"], pd.Series(1.0, index=rets.index))}}
    res["TQQQ_gate_cash"], _ = rotate(rets, gate, "TQQQ", None)
    for b in BONDS:
        res[f"TQQQ_gate_{b}"], _ = rotate(rets, gate, "TQQQ", b)
    res["QQQ_buy_hold"] = {"full": stats(rets["QQQ"], pd.Series(1.0, index=rets.index))}
    res["QQQ_gate_IEF"], _ = rotate(rets, gate, "QQQ", "IEF")
    for b in BONDS:
        res[f"{b}_buy_hold"] = {"full": stats(rets[b], pd.Series(1.0, index=rets.index))}
    print(f"{rets.index[0].date()} -> {rets.index[-1].date()}")
    for k, v in res.items():
        f = v["full"]
        print(f"{k:18s} CAGR {f['cagr']:.3f} Sh {f['sharpe']:.2f} MDD {f['mdd']:.3f} tr {f['trades']}",
              "" if "IS" not in v else f"| IS {v['IS']['sharpe']} OOS {v['OOS']['sharpe']} 2022 CAGR {v['2022']['cagr']} MDD {v['2022']['mdd']}")
    with open("../backtests/tqqq_bond_rotation_2026-11-06.json", "w") as fh:
        json.dump(res, fh, indent=1)


if __name__ == "__main__":
    main()
