"""QUA-831 Step 1: H94 feasibility pre-check on the H93 delisting-aware PIT universe (Jan 2018 list).

Data is IS only (cache ends 2021-12-31). Outputs trade-count funnel, PF-2 index proxy and IC of S1/S2/S3.
Usage: .venv/bin/python research/scripts/h94_step1_precheck.py [ncontr ratio]
"""
import sys, warnings
import numpy as np, pandas as pd, yfinance as yf
warnings.filterwarnings("ignore")

NCONTR = int(sys.argv[1]) if len(sys.argv) > 1 else 2
RATIO = float(sys.argv[2]) if len(sys.argv) > 2 else 0.6
IS_END = pd.Timestamp("2021-12-31")
THR = 0.03  # zigzag reversal threshold for swing detection

# ---------- data ----------
d = pd.read_csv("backtests/h93_cache/daily.csv", parse_dates=["date"])
d = d[d.date <= IS_END].drop_duplicates(["sym", "date"], keep="last")
P = {c: d.pivot(index="date", columns="sym", values=c).sort_index() for c in ["open", "high", "low", "close", "volume"]}
dates = P["close"].index
O, H, L, C, V = (P[k].values for k in ["open", "high", "low", "close", "volume"])
syms = P["close"].columns.tolist()
nD, nS = C.shape
last_bar = np.array([np.where(~np.isnan(C[:, j]))[0].max() if (~np.isnan(C[:, j])).any() else -1 for j in range(nS)])
spy = yf.download("SPY", start="2017-01-01", end="2022-01-05", auto_adjust=True, progress=False)
spy.columns = [c[0] for c in spy.columns]
spyc = spy["Close"].reindex(dates).ffill()

def sma(a, n): return pd.DataFrame(a).rolling(n, min_periods=n).mean().values
sma50, sma150, sma200 = sma(C, 50), sma(C, 150), sma(C, 200)
hi252 = pd.DataFrame(H).rolling(252, min_periods=200).max().values
lo252 = pd.DataFrame(L).rolling(252, min_periods=200).min().values
vol50 = sma(V, 50)
vol10 = sma(V, 10)
dv50 = sma(C * V, 50)
pc = np.vstack([np.full((1, nS), np.nan), C[:-1]])
tr = np.nanmax(np.stack([H - L, np.abs(H - pc), np.abs(L - pc)]), axis=0)
atr14 = pd.DataFrame(tr).rolling(14, min_periods=14).mean().values
ret126 = C / pd.DataFrame(C).shift(126).values - 1
spy126 = (spyc / spyc.shift(126) - 1).values[:, None]
rs = ret126 - spy126
spy200 = spyc.rolling(200).mean()
regime = ((spyc > spy200) & (spy200 > spy200.shift(20))).values

# ---------- screens ----------
liq = (dv50 >= 20e6) & (C >= 10)
trend = ((C > sma50) & (C > sma150) & (C > sma200) & (sma50 > sma150) & (sma150 > sma200)
         & (sma200 > pd.DataFrame(sma200).shift(30).values) & (C >= 1.3 * lo252) & (C >= 0.75 * hi252))
rs_masked = np.where(liq, rs, np.nan)
rs_pct = pd.DataFrame(rs_masked).rank(axis=1, pct=True).values
s1 = liq & (rs > 0) & (rs_pct >= 0.70)
s2 = liq & trend
# earnings-gap proxy: gap >3% with volume >2.5x avg, next date = last gap + 63 trading days (rolled)
gap = (O / pc - 1 > 0.03) & (V > 2.5 * vol50)
last_gap = pd.DataFrame(np.where(gap, np.arange(nD)[:, None], np.nan)).ffill().values  # PIT: known at close of gap day

def near_earnings(i, j):
    g = last_gap[i, j]
    if np.isnan(g): return False
    est = g + 63 * max(1, int(np.ceil((i - 3 - g) / 63)))  # earliest estimate >= i-3
    return (est - 3 <= i + 6) and (est + 3 >= i + 1)

def zigzag(h, l):
    """Alternating completed (peak_idx, trough_idx) pairs using THR reversal."""
    pairs, n = [], len(h)
    pk, up, tk = 0, True, 0
    cur_peak = 0
    for k in range(n):
        if up:
            if h[k] >= h[pk]: pk = k
            elif l[k] <= h[pk] * (1 - THR): up, tk, cur_peak = False, k, pk
        else:
            if l[k] <= l[tk]: tk = k
            elif h[k] >= l[tk] * (1 + THR):
                pairs.append((cur_peak, tk)); up, pk = True, k
    return pairs

REASON = {}
def _r(k):
    REASON[k] = REASON.get(k, 0) + 1
    return None

def vcp(i, j):
    """Return (pivot, final_low, ncontr) if a valid VCP completes before breakout day i, else None."""
    s = i - 60
    if s < 0: return _r("hist")
    h, l = H[s:i, j], L[s:i, j]
    if np.isnan(h).any() or np.isnan(l).any(): return _r("nan")
    pairs = zigzag(h, l)
    if len(pairs) < NCONTR: return _r("pairs<n")
    depth = [(h[p] - l[t]) / h[p] for p, t in pairs]
    k = 1
    # extend the chain backward while contraction and higher-low rules hold
    while k < len(pairs):
        a, b = len(pairs) - k - 1, len(pairs) - k
        if depth[b] <= RATIO * depth[a] and l[pairs[b][1]] > l[pairs[a][1]]: k += 1
        else: break
    if k < NCONTR: return _r("chain<n")
    fp, ft = pairs[-1]
    first_peak = pairs[-k][0]
    base_len = i - (s + first_peak)
    if not (30 <= base_len <= 60): return _r("baselen")
    if depth[-1] > 0.10: return _r("depth")
    pivot = h[fp]
    if h[fp:].max() > pivot * 1.0000001: return _r("prior_break")
    # volume dry-up at final low
    ti = s + ft
    if not (vol10[ti, j] <= 0.75 * vol50[ti, j]): return _r("dryup")
    return pivot, l[ft], k

# ---------- signals ----------
brk = ((V >= 1.4 * vol50) & (C >= (H + L) / 2)) & regime[:, None] & s1 & s2
raw = []
funnel = dict(brk_filter=int(brk.sum()))
for i, j in zip(*np.where(brk)):
    if i + 1 >= nD or i >= last_bar[j]: continue
    r = vcp(i, j)
    if r is None: continue
    pivot, flow, k = r
    if not (C[i, j] > pivot and C[i, j] <= 1.05 * pivot): continue
    raw.append((i, j, pivot, flow, k))
funnel["raw_vcp_signals"] = len(raw)
print("VCP reject reasons", REASON)
sig = []
for i, j, pivot, flow, k in raw:
    if near_earnings(i, j): continue
    sig.append((i, j, pivot, flow, k))
funnel["after_earnings_skip"] = len(sig)
sig2 = []
for i, j, pivot, flow, k in sig:
    e = O[i + 1, j]
    stop = min(flow - 0.5 * atr14[i, j], e * 0.92)
    if (e - stop) / e > 0.10 or np.isnan(stop): continue
    sig2.append((i, j, pivot, flow, k, e, stop))
funnel["after_stop_dist_filter"] = len(sig2)

# ---------- portfolio sim (counts + rough R stats; costs not applied) ----------
def sim(sigs):
    by_day = {}
    for s in sigs: by_day.setdefault(s[0], []).append(s)
    cash, pos, trades, eq_curve = 1.0, {}, [], []
    gate_off = 0
    for i in range(nD):
        # exits / stop management on bar i
        for j in list(pos):
            p = pos[j]
            if i >= last_bar[j] and i > p["i0"]:
                px = C[i, j] * 0.90 if i == last_bar[j] and last_bar[j] < nD - 20 else C[i, j]
                cash += p["sh"] * px; trades.append((j, p["i0"], i, p["e"], px, p["R"], "delist")); del pos[j]; continue
            if i <= p["i0"]: continue
            px, why = None, None
            if p["pending"]:
                px, why = O[i, j], p["pending"]
            elif L[i, j] <= p["stop"]:
                px, why = min(O[i, j], p["stop"]), "stop"
            if px is not None:
                cash += p["sh"] * px; trades.append((j, p["i0"], i, p["e"], px, p["R"], why)); del pos[j]; continue
            c = C[i, j]; age = i - p["i0"]
            p["mc"] = max(p["mc"], c)
            if c >= p["e"] + 2 * p["R"]: p["r2"] = True; p["stop"] = max(p["stop"], p["e"])
            if c >= p["e"] + 3 * p["R"]:
                p["stop"] = max(p["stop"], p["e"], p["mc"] - 3 * atr14[i, j])
                if not p["part"]:
                    p["part"] = True; q = p["sh"] / 3; cash += q * c; p["sh"] -= q
                    trades.append((j, p["i0"], i, p["e"], c, p["R"], "partial", q))
            p["below"] = p["below"] + 1 if c < sma50[i, j] else 0
            if p["below"] >= 2: p["pending"] = "sma50"
            if not p["r2"] and age >= 80: p["pending"] = "time80"
            if age >= 120: p["pending"] = "time120"
            if gate_off >= 5:
                p["stop"] = max(p["stop"], np.nanmin(L[max(0, i - 19):i + 1, j]))
            if not p["r2"] and near_earnings(i, j) and (last_gap[i, j] + 63 * max(1, int(np.ceil((i - 3 - last_gap[i, j]) / 63))) - 3 == i + 1 or False):
                px = c; cash += p["sh"] * px; trades.append((j, p["i0"], i, p["e"], px, p["R"], "earnings")); del pos[j]
        gate_off = 0 if regime[i] else gate_off + 1
        eq = cash + sum(p["sh"] * (C[i, j] if not np.isnan(C[i, j]) else p["e"]) for j, p in pos.items())
        eq_curve.append(eq)
        # entries at close i for open i+1
        for s in sorted(by_day.get(i, []), key=lambda x: -rs[x[0], x[1]]):
            _, j, pivot, flow, k, e, stop = s
            if j in pos: continue
            R = e - stop
            sh = min(0.0075 * eq / R, 0.15 * eq / e)
            open_risk = sum(max(0, q["sh"] * (C[i, jj] - q["stop"])) for jj, q in pos.items())
            if open_risk + sh * R > 0.06 * eq or sh * e > cash: continue
            cash -= sh * e
            pos[j] = dict(i0=i + 1, e=e, stop=stop, R=R, sh=sh, mc=e, r2=False, part=False, below=0, pending=None)
    return trades, np.array(eq_curve)

trades, eq = sim(sig2)
full = [t for t in trades if t[6] != "partial"]
funnel["realized_trades"] = len(full)
print("PARAMS ncontr=%d ratio=%.2f" % (NCONTR, RATIO))
print("FUNNEL", funnel)
yrs = pd.Series([dates[t[2]].year for t in full]).value_counts().sort_index().to_dict()
print("trades by exit year", yrs)
print("IS trades/4 =", len(full) / 4, "(>=30 required)")
rm = np.array([(t[4] - t[3]) / t[5] for t in full])
if len(rm):
    print("R-multiples: mean %.2f median %.2f win%% %.1f" % (rm.mean(), np.median(rm), (rm > 0).mean() * 100))
    print("exit reasons", pd.Series([t[6] for t in full]).value_counts().to_dict())
print("gate-on days %d / %d" % (regime.sum(), nD))
print("rough equity (no costs): start 1.0 end %.3f, maxdd %.1f%%" % (eq[-1], ((eq / np.maximum.accumulate(eq) - 1).min()) * 100))
ey = pd.Series(eq, index=dates)
print("calendar-year return:", (ey.groupby(ey.index.year).last() / ey.groupby(ey.index.year).first() - 1).round(3).to_dict())

# ---------- IC (S1, S2, S3) ----------
def fwd(k): return np.vstack([C[k:, :] / np.vstack([O[1:nD - k + 1, :]]) - 1, np.full((k, nS), np.nan)]) if False else None
def fret(k):
    out = np.full((nD, nS), np.nan)
    out[:nD - k - 1] = C[k:nD - 1] / O[1:nD - k] - 1  # buy next open, exit close of day t+k (k>=1 -> index t+k)
    return out
def xs_ic(score, mask, fr):
    s = np.where(mask, score, np.nan)
    df = pd.DataFrame(s).rank(axis=1)
    fd = pd.DataFrame(np.where(mask, fr, np.nan)).rank(axis=1)
    ics = df.corrwith(fd, axis=1)
    return ics.mean(), ics.std() / np.sqrt(ics.count()), int(ics.count())
print("\nIC (rank IC; OOS excluded; window starts when 252d history exists)")
valid = np.zeros((nD, nS), bool); valid[210:] = True
for k in (5, 20):
    fr = fret(k)
    m1 = liq & valid & ~np.isnan(rs)
    ic1 = xs_ic(rs, m1, fr)
    prox = C / hi252
    ic2 = xs_ic(prox, liq & valid & ~np.isnan(prox) & s1 & (C > sma200), fr)  # S2 trend-state score among RS leaders
    # S3: breakout indicator (VCP) among S1&S2 stock-days, pooled, day-demeaned forward return
    base = s1 & s2 & valid & regime[:, None] & ~np.isnan(fr)
    frd = fr - np.nanmean(np.where(base, fr, np.nan), axis=1, keepdims=True)
    vc = np.zeros((nD, nS)); [vc.__setitem__((i, j), 1.0) for i, j, *_ in raw]
    b20 = (C > pd.DataFrame(H).rolling(20).max().shift(1).values) & (V >= 1.4 * vol50) & (C >= (H + L) / 2)
    from scipy.stats import spearmanr
    out = {}
    for nm, ind in (("S3_vcp", vc), ("S3_20dHigh", b20.astype(float))):
        sel = base & ~np.isnan(frd)
        x, y = ind[sel], frd[sel]
        rho = spearmanr(x, y)[0] if x.std() > 0 else np.nan
        out[nm] = (rho, int(x.sum()), int(sel.sum()))
    print("T+%d  S1 RS: IC=%.4f (se %.4f, n_days=%d) | S2 prox: IC=%.4f (se %.4f) | S3: %s" % (k, ic1[0], ic1[1], ic1[2], ic2[0], ic2[1], out))

# ---------- PF-2 proxy ----------
print("\nPF-2 proxy: regime gate + 20d-high breakout, 1R stop")
def pf2(tkr, start, end, stress):
    x = yf.download(tkr, start="1999-01-01", end="2010-01-01", auto_adjust=True, progress=False)
    x.columns = [c[0] for c in x.columns]
    c, h, l, o = x.Close, x.High, x.Low, x.Open
    s200 = c.rolling(200).mean(); g = ((c > s200) & (s200 > s200.shift(20)))
    s50 = c.rolling(50).mean(); hh = h.rolling(20).max().shift(1)
    trr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1); a = trr.rolling(14).mean()
    ll = l.rolling(10).min()
    idx = x.index; eq, cash, sh, stp, e0 = 1.0, 1.0, 0.0, None, None
    pend, ev, below, goff = None, [], 0, 0
    for n in range(210, len(idx) - 1):
        px = c.iloc[n]
        if sh > 0:
            if pend: cash += sh * o.iloc[n]; sh = 0; pend = None
            elif l.iloc[n] <= stp: cash += sh * min(o.iloc[n], stp); sh = 0
            else:
                below = below + 1 if px < s50.iloc[n] else 0
                if below >= 2: pend = 1
                goff = 0 if g.iloc[n] else goff + 1
                if goff >= 5: stp = max(stp, l.iloc[max(0, n - 19):n + 1].min())
        goff = 0 if g.iloc[n] else goff
        eqn = cash + sh * px
        if sh == 0 and g.iloc[n] and px > hh.iloc[n] and idx[n] >= pd.Timestamp(start) and idx[n] <= pd.Timestamp(end):
            en = o.iloc[n + 1]; st = min(ll.iloc[n] - 0.5 * a.iloc[n], en * 0.92)
            R = en - st
            if R > 0 and R / en <= 0.10:
                shn = (0.06 * eqn / R) if stress else (0.0075 * eqn / R)
                shn = min(shn, eqn / en if stress else 0.15 * eqn / en)
                cash -= shn * en; sh = shn; stp = st; below = 0
        ev.append((idx[n], cash + sh * px))
    s = pd.Series([v for _, v in ev], index=[t for t, _ in ev])
    s = s[(s.index >= start) & (s.index <= end)]
    return (s / s.cummax() - 1).min(), s.iloc[-1] / s.iloc[0] - 1, (s.index[0].date(), s.index[-1].date())
for tkr in ("SPY", "QQQ"):
    for (a, b) in (("2000-01-01", "2002-12-31"), ("2008-01-01", "2009-12-31")):
        for stress in (False, True):
            try:
                mdd, ret, rng = pf2(tkr, a, b, stress)
                print("%s %s..%s %s: MDD %.1f%% ret %.1f%%" % (tkr, a[:4], b[:4], "STRESS(6%% risk,100%% cap)" if stress else "spec sizing", mdd * 100, ret * 100))
            except Exception as ex:
                print(tkr, a, b, "error", ex)
