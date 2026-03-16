"""
Supplementary cointegration analysis for QUA-82:
1. Test alternative pairs (FITB/KEY, WFC/USB, MRO/DVN, PG/CL)
2. Test all pairs with shorter windows (63d, 126d) for diagnostic purposes
3. Investigate COVID impact on cointegration break pattern
"""

import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.stattools import coint

warnings.filterwarnings("ignore")

# Original ETF pairs
ETF_PAIRS = [
    ("XLF", "KRE"), ("XLE", "OIH"), ("XLV", "IBB"), ("XLP", "XLY"), ("GLD", "SLV"),
]

# Alternative equity pairs suggested in task spec
ALT_PAIRS = [
    ("FITB", "KEY"),   # Regional bank alternative to XLF/KRE
    ("WFC", "USB"),    # Bank pair alternative to XLF/KRE
    ("MRO", "DVN"),    # E&P oil alternative to XLE/OIH
    ("PG", "CL"),      # Consumer staples alternative to XLP/XLY
]

ALL_PAIRS = ETF_PAIRS + ALT_PAIRS

START = "2017-01-01"
IS_START = "2018-01-01"
IS_END = "2021-12-31"
PRE_COVID_END = "2020-02-28"
POST_COVID_START = "2020-06-01"

WINDOWS = [63, 126, 252]
PASS_THRESHOLD = 0.30


def rolling_coint_pvalues(series_a, series_b, window):
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


def analyze_pair(prices, a, b, window):
    if a not in prices.columns or b not in prices.columns:
        return None
    combined = pd.concat([prices[a], prices[b]], axis=1).dropna()
    combined.columns = [a, b]
    pvals = rolling_coint_pvalues(combined[a], combined[b], window=window)
    combined["pval"] = pvals
    is_data = combined.loc[IS_START:IS_END]
    is_pvals = is_data["pval"].dropna()
    if len(is_pvals) == 0:
        return None
    pre_covid = is_data.loc[:PRE_COVID_END]["pval"].dropna()
    post_covid = is_data.loc[POST_COVID_START:]["pval"].dropna()
    return {
        "pct_lt_010": (is_pvals < 0.10).mean(),
        "pct_lt_005": (is_pvals < 0.05).mean(),
        "avg_pval": is_pvals.mean(),
        "pre_covid_pct_lt_010": (pre_covid < 0.10).mean() if len(pre_covid) > 0 else np.nan,
        "post_covid_pct_lt_010": (post_covid < 0.10).mean() if len(post_covid) > 0 else np.nan,
    }


def main():
    all_tickers = list({t for pair in ALL_PAIRS for t in pair})
    print(f"Downloading {len(all_tickers)} tickers...")
    raw = yf.download(all_tickers, start=START, end=IS_END, auto_adjust=True, progress=False)
    prices = raw["Close"].dropna(how="all")

    print("\n" + "=" * 100)
    print("MULTI-WINDOW COINTEGRATION ANALYSIS — Full Universe + Alternative Pairs")
    print("IS Window: 2018-01-01 to 2021-12-31")
    print("=" * 100)

    rows = []
    for window in WINDOWS:
        print(f"\n--- Window: {window} days ---")
        for pair in ALL_PAIRS:
            a, b = pair
            result = analyze_pair(prices, a, b, window)
            if result is None:
                print(f"  {a}/{b}: MISSING DATA")
                continue
            status = "PASS" if result["pct_lt_010"] >= PASS_THRESHOLD else "FAIL"
            category = "ETF" if pair in ETF_PAIRS else "ALT"
            rows.append({
                "Pair": f"{a}/{b}",
                "Category": category,
                "Window": window,
                "% p<0.10 (IS)": f"{result['pct_lt_010']:.1%}",
                "% p<0.05 (IS)": f"{result['pct_lt_005']:.1%}",
                "Avg p-val": f"{result['avg_pval']:.4f}",
                "Pre-COVID p<0.10": f"{result['pre_covid_pct_lt_010']:.1%}" if not np.isnan(result['pre_covid_pct_lt_010']) else "N/A",
                "Post-COVID p<0.10": f"{result['post_covid_pct_lt_010']:.1%}" if not np.isnan(result['post_covid_pct_lt_010']) else "N/A",
                "Status": status,
                "raw_pct": result['pct_lt_010'],
            })
            print(f"  {a}/{b} [{category}]: p<0.10={result['pct_lt_010']:.1%}, avg_p={result['avg_pval']:.4f}, "
                  f"pre-COVID={result['pre_covid_pct_lt_010']:.1%}, post-COVID={result['post_covid_pct_lt_010']:.1%}  [{status}]")

    df = pd.DataFrame(rows)

    print("\n\n" + "=" * 100)
    print("BEST PAIRS BY WINDOW (sorted by % days p < 0.10):")
    print("=" * 100)
    for window in WINDOWS:
        subset = df[df["Window"] == window].sort_values("raw_pct", ascending=False).head(5)
        print(f"\nTop 5 pairs at {window}-day window:")
        print(subset[["Pair", "Category", "% p<0.10 (IS)", "% p<0.05 (IS)", "Avg p-val", "Status"]].to_string(index=False))

    # Save CSV
    df.drop(columns=["raw_pct"]).to_csv("research/findings/h04v2_coint_multiwindow_2026-03.csv", index=False)
    print("\nFull results saved to: research/findings/h04v2_coint_multiwindow_2026-03.csv")


if __name__ == "__main__":
    main()
