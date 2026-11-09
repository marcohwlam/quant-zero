"""PF-1 event counts and PF-2 proxy MDD for H95, H96, H97 on real yfinance daily data (QUA-905)."""
import json
import numpy as np
import pandas as pd
import yfinance as yf

START, END = "1998-01-01", "2024-12-31"
IS = ("2000-01-01", "2019-12-31")
S11 = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
H96U = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "XLY", "XLP"]
ALL = sorted(set(S11 + H96U + ["SHY"]))
raw = yf.download(ALL, start=START, end=END, auto_adjust=True, progress=False, group_by="ticker")
d = {t: raw[t].dropna(subset=["Close"]) for t in ALL if t in raw.columns.get_level_values(0)}
C = pd.DataFrame({t: d[t]["Close"] for t in d})
spy = C["SPY"]
gate = (spy > spy.rolling(200).mean()).shift(0)


def mdd(eq):
    return float((eq / eq.cummax() - 1).min())


def window_mdd(r, a, b):
    s = r.loc[a:b]
    return mdd((1 + s).cumprod())


def sharpe(r):
    return float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else float("nan")


def slice_is(idx):
    return idx[(idx >= IS[0]) & (idx <= IS[1])]


out = {}

# H95: weekly, 2 worst 5-day return, SPY gate, hold to next Friday (no stop modelled; stop only lowers loss)
fri = list(C.index.to_series().groupby(C.index.to_period("W-FRI")).last())
wk = C.loc[fri]
ret5 = wk.pct_change()
fwd = wk.pct_change().shift(-1)
trades, wret = [], []
for dt in wk.index[:-1]:
    if not gate.get(dt, False):
        wret.append((wk.index[wk.index.get_loc(dt) + 1], 0.0)); continue
    r = ret5.loc[dt].dropna()
    if len(r) < 4:
        continue
    pick = r.nsmallest(2).index
    f = fwd.loc[dt, pick]
    trades += [(dt, p) for p in pick]
    wret.append((wk.index[wk.index.get_loc(dt) + 1], float(f.mean() * 0.8)))
w = pd.Series(dict(wret)).sort_index()
tr = pd.DataFrame(trades, columns=["d", "t"])
tis = tr[(tr.d >= IS[0]) & (tr.d <= IS[1])]
out["H95"] = dict(is_trades=len(tis), per_year=len(tis) / 20, div4=len(tis) / 4,
                  mdd_2000_2002=window_mdd(w, "2000", "2002"), mdd_2008_2009=window_mdd(w, "2008", "2009"),
                  mdd_is=window_mdd(w, *IS), mdd_2022=window_mdd(w, "2022", "2022"), sharpe_is_gross=sharpe(w.loc[IS[0]:IS[1]]) * np.sqrt(52 / 252))

# H96: capitulation events
ev = []
dret = {}
for t in H96U:
    x = d[t]
    pc = x["Close"].shift(1)
    tr_ = pd.concat([x["High"] - x["Low"], (x["High"] - pc).abs(), (x["Low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr_.rolling(14).mean()
    r1 = x["Close"].pct_change()
    volx = x["Volume"] / x["Volume"].rolling(20).mean()
    base = (r1 < -1.5 * atr / x["Close"]) & (volx > 2.0)
    own = x["Close"] > x["Close"].rolling(200).mean()
    for name, g in [("raw", pd.Series(True, index=x.index)), ("own_sma", own), ("spy_sma", gate.reindex(x.index).fillna(False)), ("either", own | gate.reindex(x.index).fillna(False))]:
        for dt in x.index[base & g]:
            ev.append((name, t, dt))
E = pd.DataFrame(ev, columns=["variant", "t", "d"])
res = {}
for v, g in E.groupby("variant"):
    gi = g[(g.d >= IS[0]) & (g.d <= IS[1])]
    # distinct days (clustering) too
    res[v] = dict(is_events=len(gi), distinct_days=gi.d.nunique(), per_year=len(gi) / 20, div4=len(gi) / 4,
                  min_year=int(gi.groupby(gi.d.dt.year).size().reindex(range(2000, 2020), fill_value=0).min()))
out["H96_events"] = res
# H96 PF-2 proxy: equal-weight events, simulate trades with exit rules, "either" and "spy_sma" gates
def sim(variant):
    g = E[E.variant == variant]
    pnl = []
    for t, dt in zip(g.t, g.d):
        x = d[t]; i = x.index.get_loc(dt)
        entry, low = x["Close"].iloc[i], x["Low"].iloc[i]
        for k in range(1, 6):
            if i + k >= len(x): break
            c = x["Close"].iloc[i + k]
            if c < low or c > x["Close"].iloc[i + k - 1] or k == 5:
                pnl.append((x.index[i + k], c / entry - 1)); break
    p = pd.DataFrame(pnl, columns=["d", "r"]).groupby("d").r.mean()
    daily = p.reindex(C.index).fillna(0) * 0.10  # 10% slot size per concurrent day-bucket proxy
    return daily
for v in ["spy_sma", "either", "raw"]:
    s = sim(v)
    out[f"H96_pf2_{v}"] = dict(mdd_2000_2002=window_mdd(s, "2000", "2002"), mdd_2008_2009=window_mdd(s, "2008", "2009"), mdd_is=window_mdd(s, *IS))

# H97: monthly top3 by Close/252d high, ratio>0.9, gate else SHY
hi = pd.DataFrame({t: d[t]["High"].rolling(252).max() for t in S11 if t in d})
ratio = C[hi.columns] / hi
me = list(C.index.to_series().groupby(C.index.to_period("M")).last())
mr, prev, ntr = [], set(), []
for a, b in zip(me[:-1], me[1:]):
    r = ratio.loc[a].dropna()
    if not gate.get(a, False):
        sel = set()
        ret = C["SHY"].loc[b] / C["SHY"].loc[a] - 1
    else:
        top = r[r > 0.90].nlargest(3).index
        sel = set(top)
        ret = float(np.mean([C[t].loc[b] / C[t].loc[a] - 1 for t in top])) if len(top) else 0.0
        if len(top):
            ret *= len(top) / 3
            ret += (3 - len(top)) / 3 * (C["SHY"].loc[b] / C["SHY"].loc[a] - 1) if False else 0
    for t in sel - prev: ntr.append((a, t))
    prev = sel
    mr.append((b, ret))
m = pd.Series(dict(mr))
tr97 = pd.DataFrame(ntr, columns=["d", "t"])
t97 = tr97[(tr97.d >= IS[0]) & (tr97.d <= IS[1])]
out["H97"] = dict(is_entries=len(t97), per_year=len(t97) / 20, div4=len(t97) / 4,
                  mdd_2000_2002=window_mdd(m, "2000", "2002"), mdd_2008_2009=window_mdd(m, "2008", "2009"),
                  mdd_is=window_mdd(m, *IS), mdd_2022=window_mdd(m, "2022", "2022"),
                  note="monthly close-to-close, no intramonth stop; XLC/XLRE enter when listed; <3 qualifying = partial cash")
print(json.dumps(out, indent=1, default=float))
json.dump(out, open("backtests/pf_verify_h95_h97_2026-11-09.json", "w"), indent=1, default=float)
