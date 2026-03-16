"""
Cointegration pre-screen for H04-v2 ETF pair universe.
Task: QUA-82

For each of 5 ETF pairs, compute rolling 252-day Engle-Granger cointegration
test on daily data 2018-01-01 to 2021-12-31. Report p-value statistics and
estimated trade count with entry_zscore=1.5, lookback=63d.
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.stattools import coint

warnings.filterwarnings("ignore")

PAIRS = [
    ("XLF", "KRE"),
    ("XLE", "OIH"),
    ("XLV", "IBB"),
    ("XLP", "XLY"),
    ("GLD", "SLV"),
]

PAIR_LABELS = {
    ("XLF", "KRE"): "US Financials vs. Regional Banks",
    ("XLE", "OIH"): "Energy Sector vs. Oil Services",
    ("XLV", "IBB"): "Healthcare vs. Biotech",
    ("XLP", "XLY"): "Consumer Staples vs. Consumer Discr.",
    ("GLD", "SLV"): "Gold vs. Silver",
}

START = "2017-01-01"  # Extra year for first rolling windows
IS_START = "2018-01-01"
IS_END = "2021-12-31"
COINT_WINDOW = 252   # rolling Engle-Granger window
LOOKBACK = 63        # z-score lookback
ENTRY_ZSCORE = 1.5
EXIT_ZSCORE = 0.0
PASS_THRESHOLD = 0.30  # 30% of days cointegrated (p < 0.10)


def rolling_coint_pvalues(series_a, series_b, window=252):
    """Compute rolling Engle-Granger p-values."""
    n = len(series_a)
    pvals = np.full(n, np.nan)
    for i in range(window - 1, n):
        a_slice = series_a.iloc[i - window + 1: i + 1].values
        b_slice = series_b.iloc[i - window + 1: i + 1].values
        try:
            _, pval, _ = coint(a_slice, b_slice)
            pvals[i] = pval
        except Exception:
            pvals[i] = np.nan
    return pvals


def estimate_trade_count(series_a, series_b, lookback=63, entry_zscore=1.5, exit_zscore=0.0):
    """
    Estimate number of pair entries using rolling OLS z-score with a simple
    state machine: open when |z| > entry_zscore, close when z crosses exit_zscore.
    """
    n = len(series_a)
    trades = 0
    position = 0  # 1 = long A/short B, -1 = short A/long B, 0 = flat

    for i in range(lookback, n):
        a_slice = series_a.iloc[i - lookback: i].values
        b_slice = series_b.iloc[i - lookback: i].values

        # Rolling OLS: spread = A - (alpha + beta * B)
        X = np.column_stack([np.ones(lookback), b_slice])
        try:
            coeffs = np.linalg.lstsq(X, a_slice, rcond=None)[0]
        except Exception:
            continue
        alpha, beta = coeffs[0], coeffs[1]
        spread = a_slice - (alpha + beta * b_slice)
        spread_mean = spread.mean()
        spread_std = spread.std()
        if spread_std < 1e-10:
            continue

        current_spread = series_a.iloc[i] - (alpha + beta * series_b.iloc[i])
        z = (current_spread - spread_mean) / spread_std

        if position == 0:
            if z < -entry_zscore:
                position = 1
                trades += 1
            elif z > entry_zscore:
                position = -1
                trades += 1
        elif position == 1:
            if z >= exit_zscore:
                position = 0
        elif position == -1:
            if z <= -exit_zscore:
                position = 0

    return trades


def main():
    # Download all tickers
    all_tickers = list({t for pair in PAIRS for t in pair})
    print(f"Downloading {len(all_tickers)} tickers from {START} to {IS_END}...")
    raw = yf.download(all_tickers, start=START, end=IS_END, auto_adjust=True, progress=False)
    prices = raw["Close"].dropna(how="all")

    # Filter to IS window
    prices_is = prices.loc[IS_START:IS_END]

    results = []
    for pair in PAIRS:
        a, b = pair
        label = PAIR_LABELS[pair]

        if a not in prices.columns or b not in prices.columns:
            print(f"WARNING: Missing data for {a}/{b}")
            continue

        # Get full series for rolling (need COINT_WINDOW days before IS start)
        full_a = prices[a].dropna()
        full_b = prices[b].dropna()
        combined = pd.concat([full_a, full_b], axis=1).dropna()
        combined.columns = [a, b]

        # Compute rolling cointegration p-values on full window
        print(f"Computing rolling cointegration for {a}/{b}...")
        pvals = rolling_coint_pvalues(combined[a], combined[b], window=COINT_WINDOW)
        combined["pval"] = pvals

        # Filter to IS window for stats
        is_combined = combined.loc[IS_START:IS_END]
        is_pvals = is_combined["pval"].dropna()

        if len(is_pvals) == 0:
            print(f"WARNING: No p-values computed for {a}/{b} in IS window")
            continue

        pct_lt_010 = (is_pvals < 0.10).mean()
        pct_lt_005 = (is_pvals < 0.05).mean()
        avg_pval = is_pvals.mean()
        status = "PASS" if pct_lt_010 >= PASS_THRESHOLD else "AT RISK"

        # Estimate trade count on IS window
        is_a = prices_is[a].dropna()
        is_b = prices_is[b].dropna()
        is_comb = pd.concat([is_a, is_b], axis=1).dropna()
        is_comb.columns = [a, b]
        trade_count = estimate_trade_count(is_comb[a], is_comb[b],
                                           lookback=LOOKBACK,
                                           entry_zscore=ENTRY_ZSCORE,
                                           exit_zscore=EXIT_ZSCORE)

        results.append({
            "Pair": f"{a}/{b}",
            "Description": label,
            "IS Days (total)": len(is_pvals),
            "% Days p<0.10": f"{pct_lt_010:.1%}",
            "% Days p<0.05": f"{pct_lt_005:.1%}",
            "Avg p-value": f"{avg_pval:.4f}",
            "Status": status,
            "IS Trade Count (est.)": trade_count,
        })

        print(f"  {a}/{b}: p<0.10={pct_lt_010:.1%}, p<0.05={pct_lt_005:.1%}, "
              f"avg_p={avg_pval:.4f}, trades={trade_count} [{status}]")

    print("\n" + "=" * 80)
    print("COINTEGRATION PRE-SCREEN RESULTS — H04-v2 ETF Pair Universe")
    print("IS Window: 2018-01-01 to 2021-12-31 | Rolling Engle-Granger (252-day)")
    print("=" * 80)
    df = pd.DataFrame(results)
    print(df.to_string(index=False))
    print()
    print("Pass threshold: >= 30% of trading days with Engle-Granger p < 0.10")
    print("Trade count estimated with: entry_zscore=1.5, lookback=63d, exit_zscore=0.0")

    # Save results
    output_path = "research/findings/h04v2_coint_prescreen_2026-03.md"
    _write_report(results, output_path)
    print(f"\nReport written to: {output_path}")

    return results


def _write_report(results, path):
    lines = [
        "# H04-v2 Cointegration Pre-Screen Results",
        "",
        "**Date:** 2026-03-15  ",
        "**Task:** QUA-82  ",
        "**Author:** Alpha Research Agent  ",
        "**IS Window:** 2018-01-01 to 2021-12-31  ",
        "**Method:** Rolling 252-day Engle-Granger cointegration test  ",
        "**Pass threshold:** ≥ 30% of trading days with p < 0.10  ",
        "",
        "---",
        "",
        "## Results Summary",
        "",
        "| Pair | Description | % Days p<0.10 | % Days p<0.05 | Avg p-value | Status | Est. IS Trades |",
        "|------|-------------|--------------|--------------|-------------|--------|----------------|",
    ]
    for r in results:
        lines.append(
            f"| {r['Pair']} | {r['Description']} | {r['% Days p<0.10']} | "
            f"{r['% Days p<0.05']} | {r['Avg p-value']} | **{r['Status']}** | {r['IS Trade Count (est.)']} |"
        )

    passing = [r for r in results if r["Status"] == "PASS"]
    at_risk = [r for r in results if r["Status"] == "AT RISK"]

    lines += [
        "",
        "---",
        "",
        "## Recommendation",
        "",
    ]

    if passing:
        lines.append(f"**Include in v2.0 backtest ({len(passing)} pairs):**")
        for r in passing:
            lines.append(f"- {r['Pair']} — {r['Description']} (p<0.10 on {r['% Days p<0.10']} of IS days)")
        lines.append("")

    if at_risk:
        lines.append(f"**AT RISK — Exclude or replace ({len(at_risk)} pairs):**")
        for r in at_risk:
            lines.append(f"- {r['Pair']} — {r['Description']} (p<0.10 on {r['% Days p<0.10']} of IS days, below 30% threshold)")
        lines.append("")
        lines.append("**Suggested replacements for AT RISK pairs** (from task spec):")
        lines.append("- XLF/KRE at risk → try FITB/KEY or WFC/USB")
        lines.append("- XLE/OIH at risk → try MRO/DVN")
        lines.append("- XLP/XLY at risk → try PG/CL")
        lines.append("")

    total_est_trades = sum(r["IS Trade Count (est.)"] for r in results)
    pass_trades = sum(r["IS Trade Count (est.)"] for r in passing)
    lines += [
        "---",
        "",
        "## Trade Count Assessment",
        "",
        f"- Total estimated IS trades across all 5 pairs: **{total_est_trades}**",
        f"- Estimated IS trades from passing pairs only: **{pass_trades}**",
        f"- Gate 1 minimum: **50 trades** (across all active pairs)",
        "",
        "_Note: Trade count estimate uses a simplified signal simulation "
        "(rolling OLS z-score, entry_zscore=1.5, lookback=63d, exit_zscore=0.0). "
        "Actual backtest count may differ due to cointegration filter and VIX overlay._",
        "",
        "---",
        "",
        "*Alpha Research Agent | QUA-82 | 2026-03-15*",
    ]

    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
