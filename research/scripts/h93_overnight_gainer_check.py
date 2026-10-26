"""QUA-823: IS-only overnight top-decile gainer check, survivor subset vs delisting-inclusive universe.
Input: backtests/h93_cache/daily.csv (Alpaca daily, 2017-06..2021-12, adjusted). No 2022+ data."""
import sys, numpy as np, pandas as pd

d = pd.read_csv("backtests/h93_cache/daily.csv", parse_dates=["date"])
d = d.sort_values(["sym", "date"]).reset_index(drop=True)
g = d.groupby("sym")
d["ret"] = g.close.pct_change()
d["on"] = g.open.shift(-1) / d.close - 1          # overnight: open(t+1)/close(t)-1
d["last_bar"] = g.date.shift(-1).isna()           # no next bar: data ends after this close
d["dv20"] = g.apply(lambda x: (x.close * x.volume).rolling(20).mean(), include_groups=False).reset_index(level=0, drop=True)
d["pclose"] = g.close.shift(1)
d["pdv20"] = d.groupby("sym").dv20.shift(1)
ndays = g.date.transform("count")
d["survivor"] = ndays >= 800                      # replicates the 734-name rule in hypothesis 92
last = g.date.transform("max")
d["delisted_in_window"] = last < pd.Timestamp("2021-12-20")
d = d[d.date >= "2018-01-01"]
elig = d[(d.pclose > 5) & (d.pdv20 > 5e6) & (d.volume > 0) & d.ret.notna()].copy()
# eligible but final bar of a delisted name: next-open return unobservable
unobs = elig[elig.on.isna()]
print("eligible rows", len(elig), "| unobservable overnight (data ends):", len(unobs),
      "| of which delisted-in-window names:", int(unobs.delisted_in_window.sum()))

def run(df, label, fill_missing=None):
    df = df.copy()
    if fill_missing is not None:                  # delisting-day treatment: assume exit return = fill_missing
        df.loc[df.on.isna() & df.delisted_in_window, "on"] = fill_missing
    df = df[df.on.notna()]
    df["rk"] = df.groupby("date").ret.rank(pct=True)
    top = df[df.rk > 0.9]
    base = df.groupby("date").on.mean()
    sig = top.groupby("date").on.mean()
    n = len(top); m = top.on.mean() * 1e4
    daily = sig.reindex(base.index)
    ex = (sig - base.reindex(sig.index)).dropna()
    # SE clustered by day: daily mean of per-day average, weighted by trades
    w = top.groupby("date").size().reindex(sig.index)
    se = np.sqrt(np.sum((w * (sig - m / 1e4)) ** 2)) / w.sum() * 1e4
    sh = sig.mean() / sig.std() * np.sqrt(252)
    eq = (1 + sig.fillna(0)).cumprod(); mdd = (eq / eq.cummax() - 1).min()
    q = top.groupby(top.date.dt.to_period("Q")).size()
    per = {k: top[(top.date.dt.year.isin(v))].on.mean() * 1e4 for k, v in {"18-19": [2018, 2019], "20-21": [2020, 2021]}.items()}
    print(f"{label:34s} trades {n:6d} medQ {int(q.median()):5d} hit {100*(top.on>0).mean():5.1f}% "
          f"mean {m:6.1f}bp (SE {se:4.1f}, t {m/se:4.1f}) base {df.on.mean()*1e4:5.1f}bp excess {m-df.on.mean()*1e4:5.1f}bp "
          f"net10 {m-10:6.1f} net20 {m-20:6.1f} Sharpe {sh:4.2f} MDD {100*mdd:6.1f}% 18-19 {per['18-19']:5.1f} 20-21 {per['20-21']:5.1f} "
          f"med {top.on.median()*1e4:5.1f} p1 {top.on.quantile(.01)*1e4:7.1f} min {top.on.min()*1e4:8.1f}")
    return top

run(elig[elig.survivor], "A survivor subset (>=800d)")
run(elig, "B full universe, drop unobservable")
run(elig, "C full, delisting exit -10%", -0.10)
run(elig, "D full, delisting exit -30%", -0.30)
run(elig[~elig.survivor], "E non-survivor names only")
top = run(elig, "B repeat")
big = top.sort_values("on")
print("\nworst 8 / best 8 trades in B:\n", big.head(8)[["sym", "date", "ret", "on"]].to_string(), "\n", big.tail(8)[["sym", "date", "ret", "on"]].to_string())
print("\nuniverse:", d.sym.nunique(), "names with bars | survivors:", d[d.survivor].sym.nunique(), "| delisted in window:", d[d.delisted_in_window].sym.nunique())
# trimmed mean sensitivity
t = top.on
print("B trimmed (drop 0.5% each tail) mean bp:", t[(t > t.quantile(.005)) & (t < t.quantile(.995))].mean() * 1e4)

if "--variants" in sys.argv:
    print("\n-- reproduction attempts for hypothesis 92 control (+13.3 bps) --")
    s = d[d.survivor & d.on.notna() & d.ret.notna()].copy()
    def tp(df, lab):
        df = df.copy(); df["rk"] = df.groupby("date").ret.rank(pct=True); t = df[df.rk > 0.9]
        print(f"{lab:46s} n {len(t):6d} mean {t.on.mean()*1e4:6.1f}bp base {df.on.mean()*1e4:5.1f}bp")
    tp(s, "no eligibility filter (survivors)")
    tp(s[(s.pclose > 5)], "price>5 only")
    tp(s[(s.pclose > 5) & (s.pdv20 > 5e6)], "price>5 & dv20>5M (as primary)")
    e = s[(s.pclose > 5) & (s.pdv20 > 5e6)].copy()
    for lo, hi in [(2018, 2019), (2020, 2021)]:
        tp(e[e.date.dt.year.between(lo, hi)], f"primary {lo}-{hi}")
    e["rk"] = e.groupby("date").ret.rank(pct=True)
    print("mean overnight by return decile (bps):", (e.groupby(pd.cut(e.rk, 10, labels=False)).on.mean() * 1e4).round(1).tolist())
    e["rk2"] = e.groupby("date").ret.rank(pct=True, method="first")
    print("trimmed top decile mean (winsor +-50%):", (e[e.rk > .9].on.clip(-.5, .5).mean() * 1e4).round(1))
