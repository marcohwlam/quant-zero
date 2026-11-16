"""PF-1 trade counts, PF-2 stress MDD and 2022 behavior for H99-H101 on real yfinance daily data (QUA-949)."""
import json
import numpy as np
import pandas as pd
import yfinance as yf

START, END = "1998-01-01", "2024-12-31"
IS = ("2000-01-01", "2019-12-31")
COST = 0.0005  # 5 bps per side
U = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "XLY", "XLP", "EFA", "EEM", "TLT", "IEF", "VUSTX", "VFITX", "SHY"]
raw = yf.download(U, start=START, end=END, auto_adjust=True, progress=False, group_by="ticker")
d = {t: raw[t].dropna(subset=["Close"]) for t in U if t in raw.columns.get_level_values(0)}
C = pd.DataFrame({t: d[t]["Close"] for t in d})
gate = C["SPY"] > C["SPY"].rolling(200).mean()


def mdd(eq): return float((eq / eq.cummax() - 1).min())
def wmdd(r, a, b): return mdd((1 + r.loc[a:b].fillna(0)).cumprod())
def sharpe(r):
    r = r.dropna(); return float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else float("nan")
def ann(r, a, b): return float((1 + r.loc[a:b].fillna(0)).prod() ** (252 / max(len(r.loc[a:b]), 1)) - 1)

out = {}

# ---- H99: month-end Treasury window. Hold from close of 4th-last trading day to close of last trading day.
def month_end_window(px, n):
    ret = pd.Series(0.0, index=px.index); trades = []
    grp = px.index.to_series().groupby(px.index.to_period("M"))
    for _, idx in grp:
        if len(idx) < n + 2: continue
        a, b = idx.iloc[-(n + 1)], idx.iloc[-1]
        trades.append((a, b, px.loc[b] / px.loc[a] - 1 - 2 * COST))
        pos = px.index.get_loc(a)
        pe = px.index.get_loc(b)
        seg = px.iloc[pos:pe + 1].pct_change().iloc[1:]
        ret.loc[seg.index] = seg.values
        ret.loc[seg.index[0]] -= COST; ret.loc[seg.index[-1]] -= COST
    return ret, pd.DataFrame(trades, columns=["a", "b", "r"])

res99 = {}
for n in (3, 4, 5):
    for name, ticks in {"VUSTX": ["VUSTX"], "VFITX": ["VFITX"], "TLT": ["TLT"], "IEF": ["IEF"], "TLT+IEF": ["TLT", "IEF"]}.items():
        rs, ntr = [], 0
        for t in ticks:
            px = C[t].dropna(); r, tr = month_end_window(px, n); rs.append(r); ntr += len(tr[(tr.a >= IS[0]) & (tr.a <= IS[1])])
        r = pd.concat(rs, axis=1).mean(axis=1) if len(rs) > 1 else rs[0]
        px = C[ticks[0]].dropna()
        other = px.pct_change().where(r.reindex(px.index).abs() < 1e-12)  # non-window days
        res99[f"n{n}_{name}"] = dict(is_trades=ntr, div4=ntr / 4, sharpe_is=sharpe(r.loc[IS[0]:IS[1]]),
                                     sharpe_oos=sharpe(r.loc["2020":"2024"]), ret_2022=ann(r, "2022", "2022"),
                                     mdd_is=wmdd(r, *IS), mdd_2000_2002=wmdd(r, "2000", "2002"), mdd_2008_2009=wmdd(r, "2008", "2009"),
                                     mdd_2022=wmdd(r, "2022", "2022"),
                                     avg_window_gross=float(((1 + r[r != 0]).prod()) ** (1 / max((r != 0).sum(), 1)) - 1))
out["H99"] = res99
# window vs non-window mean daily return, VUSTX 1990-2019 sanity
px = C["VUSTX"].dropna(); dr = px.pct_change().dropna()
win = pd.Series(False, index=dr.index)
for _, idx in px.index.to_series().groupby(px.index.to_period("M")):
    win.loc[idx.iloc[-3:].index.intersection(win.index)] = True
sub = dr.loc[IS[0]:IS[1]]; w = win.loc[sub.index]
out["H99_window_vs_other_VUSTX_IS"] = dict(window_mean_bp=float(sub[w].mean() * 1e4), other_mean_bp=float(sub[~w].mean() * 1e4),
                                          t_diff=float((sub[w].mean() - sub[~w].mean()) / np.sqrt(sub[w].var() / w.sum() + sub[~w].var() / (~w).sum())))

# ---- H100: ETF relative-value pairs, dollar-neutral, z-score of 20d relative return.
PAIRS = [("EFA", "SPY"), ("EEM", "SPY"), ("EEM", "EFA"), ("IWM", "SPY"), ("QQQ", "DIA"), ("XLE", "XLK")]
def pair_run(a, b, zin, zout=0.0, hold_max=10, lb=252):
    px = C[[a, b]].dropna(); lr = np.log(px)
    s = (lr[a] - lr[b]).diff(20)
    z = (s - s.rolling(lb).mean()) / s.rolling(lb).std()
    ra, rb = px[a].pct_change(), px[b].pct_change()
    pos = 0; held = 0; rets = pd.Series(0.0, index=px.index); trades = []; entry = None
    for i in range(lb + 20, len(px) - 1):
        zi = z.iloc[i]
        if pos != 0:
            held += 1
            r_next = pos * (ra.iloc[i] - rb.iloc[i]) * 0.5
            rets.iloc[i] = r_next
            if held >= hold_max or (pos == 1 and zi >= -zout) or (pos == -1 and zi <= zout):
                rets.iloc[i] -= 4 * COST * 0.5; trades.append((px.index[entry], px.index[i])); pos = 0
        if pos == 0 and abs(zi) >= zin:
            pos = -1 if zi > 0 else 1  # zi>0: A outperformed -> short A long B
            entry = i; held = 0
    return rets, pd.DataFrame(trades, columns=["a", "b"])
res100 = {}
for zin in (1.5, 2.0):
    allr, ntr = [], 0
    per = {}
    for a, b in PAIRS:
        r, tr = pair_run(a, b, zin); n = int(((tr.a >= IS[0]) & (tr.a <= IS[1])).sum())
        per[f"{a}/{b}"] = dict(is_trades=n, sharpe_is=sharpe(r.loc[IS[0]:IS[1]]), sharpe_oos=sharpe(r.loc["2020":"2024"]))
        allr.append(r); ntr += n
    r = pd.concat(allr, axis=1).fillna(0).mean(axis=1)
    res100[f"z{zin}"] = dict(is_trades=ntr, div4=ntr / 4, per_pair=per, sharpe_is=sharpe(r.loc[IS[0]:IS[1]]), sharpe_oos=sharpe(r.loc["2020":"2024"]),
                             ret_2022=ann(r, "2022", "2022"), mdd_is=wmdd(r, *IS), mdd_2000_2002=wmdd(r, "2000", "2002"),
                             mdd_2008_2009=wmdd(r, "2008", "2009"), mdd_2022=wmdd(r, "2022", "2022"))
out["H100"] = res100

# ---- H101: spring (failed 20d-low breakdown) in 10 ETFs, SPY>200SMA gate, 5-day hold or close<spring low.
U101 = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "XLY", "XLP"]
def spring(variant):
    ev = []
    for t in U101:
        x = d[t]; lo20 = x["Low"].shift(1).rolling(20).min()
        sig = (x["Low"] < lo20) & (x["Close"] > lo20) & (x["Close"] > x["Open"])
        if variant == "gated": sig &= gate.reindex(x.index).fillna(False)
        for dt in x.index[sig]:
            ev.append((t, dt, x["Low"].loc[dt]))
    daily = pd.Series(0.0, index=C.index); trades = []
    for t, dt, lo in ev:
        x = d[t]["Close"]; i = x.index.get_loc(dt); entry = x.iloc[i]
        for k in range(1, 6):
            if i + k >= len(x): break
            c = x.iloc[i + k]
            if c < lo or k == 5:
                trades.append((t, dt, x.index[i + k], c / entry - 1 - 2 * COST)); break
    T = pd.DataFrame(trades, columns=["t", "a", "b", "r"])
    p = T.groupby("b").r.mean() * 0.10 * 1  # 10% per concurrent bucket proxy, booked at exit
    daily = p.reindex(C.index).fillna(0)
    ti = T[(T.a >= IS[0]) & (T.a <= IS[1])]
    # distinct entry days (cluster check)
    return dict(is_trades=len(ti), div4=len(ti) / 4, distinct_days=int(ti.a.nunique()), per_year=len(ti) / 20,
                mean_trade_net=float(ti.r.mean()), win_rate=float((ti.r > 0).mean()),
                mdd_2000_2002=wmdd(daily, "2000", "2002"), mdd_2008_2009=wmdd(daily, "2008", "2009"), mdd_is=wmdd(daily, *IS),
                n_2022=int(((T.a >= "2022-01-01") & (T.a <= "2022-12-31")).sum()),
                mean_trade_net_2022=float(T[(T.a >= "2022-01-01") & (T.a <= "2022-12-31")].r.mean()) if len(T) else None,
                sharpe_is_proxy=sharpe(daily.loc[IS[0]:IS[1]]), sharpe_oos_proxy=sharpe(daily.loc["2020":"2024"]),
                oos_mean_trade_net=float(T[(T.a >= "2020") ].r.mean()))
out["H101"] = {v: spring(v) for v in ("raw", "gated")}

json.dump(out, open("backtests/pf_verify_h99_h101_2026-11-16.json", "w"), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
