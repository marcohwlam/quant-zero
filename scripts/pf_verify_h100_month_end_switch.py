"""PF-1..PF-4 verification for H100 month-end equity/bond rebalancing switch (QUA-949). Real yfinance daily data."""
import json
import numpy as np
import pandas as pd
import yfinance as yf

COST = 0.0005
T = ["SPY", "VUSTX", "VFITX", "TLT", "IEF"]
raw = yf.download(T, start="1998-01-01", end="2024-12-31", auto_adjust=True, progress=False, group_by="ticker")
C = pd.DataFrame({t: raw[t]["Close"] for t in T})
spy = C["SPY"].dropna(); R = C.pct_change()


def sh(x):
    x = x.dropna(); return float(x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else float("nan")
def mdd(x):
    e = (1 + x.fillna(0)).cumprod(); return float((e / e.cummax() - 1).min())


def run(bond, n=3, thr=0.0, mode="switch"):
    ret = pd.Series(0.0, index=spy.index); tr = []
    for _, g in spy.index.to_series().groupby(spy.index.to_period("M")):
        if len(g) < n + 2: continue
        a, b = g.iloc[-(n + 1)], g.iloc[-1]
        prev = spy.index.get_loc(g.iloc[0]) - 1
        if prev < 0: continue
        mtd = spy.loc[a] / spy.iloc[prev] - 1
        asset = ("SPY" if mtd < thr else bond) if mode == "switch" else bond
        if mode == "spy_only_down" and mtd >= thr: continue
        if mode == "spy_only_down": asset = "SPY"
        seg = R[asset].loc[a:b].iloc[1:]
        if seg.isna().any() or len(seg) == 0: continue
        ret.loc[seg.index] = seg.values; ret.loc[seg.index[0]] -= COST; ret.loc[seg.index[-1]] -= COST
        tr.append((a, asset))
    return ret, pd.DataFrame(tr, columns=["d", "asset"])


out = {}
for lab, bond, mode in [("switch_VFITX", "VFITX", "switch"), ("switch_VUSTX", "VUSTX", "switch"), ("bond_only_VFITX", "VFITX", "bond"),
                        ("spy_only_when_MTD_down", "VFITX", "spy_only_down"), ("switch_IEF_post2002", "IEF", "switch")]:
    r, tr = run(bond, mode=mode)
    ti = tr[(tr.d >= "2000-01-01") & (tr.d <= "2019-12-31")]
    out[lab] = dict(is_trades=len(ti), div4=len(ti) / 4, exposure=float((r != 0).mean()),
                    sharpe_is=sh(r.loc["2000":"2019"]), sharpe_oos=sh(r.loc["2020":"2024"]), ret_2022=float((1 + r.loc["2022"]).prod() - 1),
                    mdd_is=mdd(r.loc["2000":"2019"]), mdd_dotcom=mdd(r.loc["2000":"2002"]), mdd_gfc=mdd(r.loc["2008":"2009"]), mdd_2022=mdd(r.loc["2022"]),
                    spy_share=float((ti.asset == "SPY").mean()),
                    sharpe_2000_2009=sh(r.loc["2000":"2009"]), sharpe_2010_2019=sh(r.loc["2010":"2019"]))
# threshold sensitivity (single param, reported not tuned)
sens = {}
for thr in (-0.02, -0.01, 0.0, 0.01, 0.02):
    r, tr = run("VFITX", thr=thr); sens[str(thr)] = dict(sharpe_is=sh(r.loc["2000":"2019"]), sharpe_oos=sh(r.loc["2020":"2024"]))
out["threshold_sensitivity_VFITX"] = sens
sens = {}
for n in (2, 3, 4, 5):
    r, tr = run("VFITX", n=n); sens[str(n)] = dict(sharpe_is=sh(r.loc["2000":"2019"]), sharpe_oos=sh(r.loc["2020":"2024"]))
out["window_days_sensitivity_VFITX"] = sens
json.dump(out, open("backtests/pf_verify_h100_2026-11-16.json", "w"), indent=1, default=float)
for k, v in out.items(): print(k, {a: (round(b, 3) if isinstance(b, float) else b) for a, b in v.items()} if "sens" not in k else v)
