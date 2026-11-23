#!/usr/bin/env python3
"""
Gate 1 Backtest Runner: H99 Month-End Treasury Window (QUA-989)

IS 2000-01-01 to 2019-12-31 (ETFs start 2002-07; VUSTX/VFITX proxies cover pre-2002)
OOS 2020-01-01 to 2024-12-31
Primary: TLT n=3. Sensitivity: IEF, TLT+IEF, n=4,5, fund proxies (informational only).

Gate 1: IS Sharpe > 1.0, OOS Sharpe > 0.7, MaxDD < 20%, >= 100 IS trades.
Charter hard constraint reported separately: Net CAGR >= 10%.
"""

import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from strategies.h99_month_end_treasury_window import PARAMETERS, window_returns, window_positions

IS = ("2000-01-01", "2019-12-31")
OOS = ("2020-01-01", "2024-12-31")
WF = [("2002-07-01", "2005-12-31"), ("2006-01-01", "2009-06-30"), ("2009-07-01", "2012-12-31"),
      ("2013-01-01", "2016-06-30"), ("2016-07-01", "2019-12-31")]
COST = PARAMETERS["cost_per_side"]
N_PERM, N_BOOT, SEED = 5000, 5000, 42
TODAY = str(date.today())
HERE = os.path.dirname(__file__)
STEM = f"H99_MonthEndTreasury_{TODAY}"

THRESH = dict(is_sharpe=1.0, oos_sharpe=0.7, max_dd=-0.20, min_trades=100)


def sharpe(r):
    r = r.dropna()
    return float(r.mean() / r.std() * np.sqrt(252)) if len(r) > 1 and r.std() > 0 else float("nan")


def cagr(r):
    r = r.dropna()
    return float((1 + r).prod() ** (252 / len(r)) - 1) if len(r) else float("nan")


def mdd(r):
    eq = (1 + r.fillna(0)).cumprod()
    return float((eq / eq.cummax() - 1).min())


def load():
    raw = yf.download(["TLT", "IEF", "VUSTX", "VFITX", "^IRX"], start="1999-06-01", end="2024-12-31",
                      auto_adjust=True, progress=False, group_by="ticker")
    px = {t: raw[t]["Close"].dropna() for t in ["TLT", "IEF", "VUSTX", "VFITX"]}
    irx = (raw["^IRX"]["Close"].dropna() / 100 / 252)  # 13-week bill yield, daily cash return
    return px, irx


def stats(daily, trades, irx, lo, hi):
    """Standalone, sleeve-level and cash-adjusted stats over [lo, hi]."""
    r = daily.loc[lo:hi]
    r = r[r.index >= daily.index[0]]
    inwin = r != 0
    cash = irx.reindex(r.index).ffill().fillna(0.0)
    cash_adj = r.where(inwin, cash)
    t = trades[(trades.entry >= lo) & (trades.entry <= hi)]
    sleeve_days = r[inwin]
    return dict(
        sharpe=sharpe(r), net_cagr=cagr(r), max_dd=mdd(r), n_trades=int(len(t)),
        win_rate=float((t.net_ret > 0).mean()) if len(t) else None,
        profit_factor=float(t.net_ret[t.net_ret > 0].sum() / -t.net_ret[t.net_ret < 0].sum())
        if (t.net_ret < 0).any() else None,
        mean_window_net_bp=float(t.net_ret.mean() * 1e4) if len(t) else None,
        exposure_frac=float(inwin.mean()),
        sleeve_cagr_exposed_days=cagr(sleeve_days),          # annualized over exposed days only
        sleeve_sharpe_exposed_days=sharpe(sleeve_days),
        cash_adjusted_cagr=cagr(cash_adj), cash_adjusted_sharpe=sharpe(cash_adj),
        leverage_to_10pct_cagr_linear=float(0.10 / cagr(r)) if cagr(r) and cagr(r) > 0 else None,
    )


def permutation_test(close, trades, lo, hi, n, rng):
    """Null: one random n-day window per month (same cost, same month count). Stat: mean net window return."""
    close = close.dropna()
    pr = close.pct_change()
    t = trades[(trades.entry >= lo) & (trades.entry <= hi)]
    obs = float(t.net_ret.mean())
    months = [idx for _, idx in close.loc[lo:hi].index.to_series().groupby(close.loc[lo:hi].index.to_period("M"))
              if len(idx) >= n + 2]
    vals = np.array([(1 + pr.loc[m.index]).values for m in months], dtype=object)
    null = np.empty(N_PERM)
    for k in range(N_PERM):
        rs = []
        for m in months:
            i = rng.integers(1, len(m) - n + 1)  # return days i..i+n-1 within month
            seg = pr.loc[m].iloc[i:i + n].values
            rs.append(np.prod(1 + seg) * (1 - COST) ** 2 - 1)
        null[k] = np.mean(rs)
    return dict(observed_mean_net_bp=obs * 1e4, null_mean_bp=float(null.mean() * 1e4),
                null_p95_bp=float(np.percentile(null, 95) * 1e4),
                p_value=float((1 + (null >= obs).sum()) / (N_PERM + 1)), n_windows=len(months))


def bootstrap(daily, lo, hi, rng):
    """Block bootstrap by calendar month: Sharpe CI and p5."""
    r = daily.loc[lo:hi]
    r = r[r.index >= daily.index[0]]
    blocks = [g.values for _, g in r.groupby(r.index.to_period("M"))]
    sh = np.empty(N_BOOT)
    for k in range(N_BOOT):
        s = np.concatenate([blocks[i] for i in rng.integers(0, len(blocks), len(blocks))])
        sh[k] = s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else np.nan
    return dict(sharpe_ci95=[float(np.nanpercentile(sh, 2.5)), float(np.nanpercentile(sh, 97.5))],
                mc_p5_sharpe=float(np.nanpercentile(sh, 5)))


def main():
    rng = np.random.default_rng(SEED)
    px, irx = load()
    series = {"TLT": px["TLT"], "IEF": px["IEF"]}
    out = dict(hypothesis="H99", ticket="QUA-989", run_date=TODAY, cost_per_side=COST, is_window=IS, oos_window=OOS,
               permutation_runs=N_PERM, bootstrap_runs=N_BOOT, results={})

    def run(name, closes, n):
        ds, trs = [], []
        for c in closes:
            d, t = window_returns(c, n, COST)
            ds.append(d); trs.append(t)
        daily = pd.concat(ds, axis=1).mean(axis=1) if len(ds) > 1 else ds[0]
        if len(ds) > 1:  # combined: start only once both exist
            daily = pd.concat(ds, axis=1).dropna().mean(axis=1)
        trades = pd.concat(trs).sort_values("entry").reset_index(drop=True)
        return daily, trades

    cases = {"TLT": [px["TLT"]], "IEF": [px["IEF"]], "TLT+IEF": [px["TLT"], px["IEF"]],
             "VUSTX_proxy": [px["VUSTX"]], "VFITX_proxy": [px["VFITX"]]}
    for n in (3, 4, 5):
        for name, closes in cases.items():
            daily, trades = run(name, closes, n)
            res = dict(IS=stats(daily, trades, irx, *IS), OOS=stats(daily, trades, irx, *OOS))
            res["IS"]["n_trades_all_legs"] = res["IS"]["n_trades"]
            if name in ("TLT", "IEF") and n == 3 or (name == "TLT" and n in (4, 5)):
                res["walk_forward"] = [dict(window=w, sharpe=sharpe(daily.loc[w[0]:w[1]])) for w in WF]
                res["wf_pass_count_sharpe_ge_0.3"] = int(sum(x["sharpe"] >= 0.3 for x in res["walk_forward"]))
                res["bootstrap_IS"] = bootstrap(daily, *IS, rng)
                res["permutation_IS"] = permutation_test(closes[0], trades, *IS, n, rng)
            out["results"][f"n{n}_{name}"] = res
            if name == "TLT" and n == 3:
                trades.to_csv(os.path.join(HERE, f"{STEM}_tlt_n3_trades.csv"), index=False)

    p = out["results"]["n3_TLT"]
    checks = dict(
        is_sharpe=p["IS"]["sharpe"] > THRESH["is_sharpe"], oos_sharpe=p["OOS"]["sharpe"] > THRESH["oos_sharpe"],
        max_dd=p["IS"]["max_dd"] > THRESH["max_dd"], trades=p["IS"]["n_trades"] >= THRESH["min_trades"])
    out["gate1_primary_TLT_n3"] = dict(checks=checks, thresholds=THRESH, result="PASS" if all(checks.values()) else "FAIL")
    out["charter_hard_constraints_TLT_n3"] = dict(
        net_cagr_ge_10pct=p["IS"]["net_cagr"] >= 0.10, net_cagr_is=p["IS"]["net_cagr"],
        maxdd_lt_15pct=p["IS"]["max_dd"] > -0.15, net_sharpe_gt_0_8=p["IS"]["sharpe"] > 0.8)

    with open(os.path.join(HERE, f"{STEM}.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    g = out["gate1_primary_TLT_n3"]
    lines = [f"H99 Month-End Treasury Window | TLT n=3 | {TODAY}", f"Gate 1: {g['result']}", json.dumps(checks),
             f"IS Sharpe {p['IS']['sharpe']:.2f}  OOS Sharpe {p['OOS']['sharpe']:.2f}  IS MDD {p['IS']['max_dd']:.1%}  "
             f"IS trades {p['IS']['n_trades']}",
             f"IS Net CAGR {p['IS']['net_cagr']:.2%} (hard constraint 10%)  perm p={p['permutation_IS']['p_value']:.4f}"]
    with open(os.path.join(HERE, f"{STEM}_verdict.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
