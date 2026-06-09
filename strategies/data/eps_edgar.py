"""
Module: strategies/data/eps_edgar.py
Author: Strategy Coder Agent
Date: 2026-06-09
Purpose: SEC EDGAR XBRL EPS data loader with point-in-time safety.

POINT-IN-TIME RULE: All filtering uses 'filed' date (when SEC received the
filing), NOT 'end' (period end date). A Q1 10-Q ending Mar 31 is filed ~early
May; the market cannot know EPS on Mar 31.

Rate limiting: <=10 req/sec per SEC EDGAR policy (10-req/s limit).
No API key required.
"""

import time
import warnings
import requests
import numpy as np
import pandas as pd

# SEC EDGAR endpoints — no API key required
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/{cik}.json"

# SEC EDGAR requests headers (required — they block default Python UA)
_HEADERS = {
    "User-Agent": "QuantZero research@quantzero.example.com",
    "Accept-Encoding": "gzip, deflate",
}

# Rate limit: <=10 req/sec → sleep 0.1s between calls
_RATE_SLEEP = 0.11


def load_cik_map() -> dict:
    """
    Fetch ticker -> CIK map from SEC EDGAR.

    Returns dict[ticker_upper -> zero_padded_10digit_cik_str].
    Raises on network error.
    """
    resp = requests.get(_TICKERS_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # data: {idx: {"cik_str": int, "ticker": str, "title": str}, ...}
    cik_map = {}
    for entry in data.values():
        ticker = entry["ticker"].upper().replace(".", "-")
        cik = str(entry["cik_str"]).zfill(10)
        cik_map[ticker] = cik
    return cik_map


def fetch_edgar_eps(ticker: str, cik: str) -> pd.DataFrame:
    """
    Fetch EPS (EarningsPerShareBasic) filings for one ticker from SEC EDGAR.

    Returns DataFrame with columns:
        ticker, period_end, filed_date, eps, form
    Only includes 10-Q and 10-K filings. Empty DataFrame on failure.

    POINT-IN-TIME: filed_date is the knowledge cutoff, not period_end.
    """
    time.sleep(_RATE_SLEEP)
    url = _FACTS_URL.format(cik=f"CIK{cik}")
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        facts = resp.json()
    except Exception as exc:
        warnings.warn(f"{ticker}: EDGAR fetch failed — {exc}")
        return pd.DataFrame()

    try:
        units = facts["facts"]["us-gaap"]["EarningsPerShareBasic"]["units"]
        # Key is "USD/shares" — iterate to find it
        entries = None
        for unit_key, unit_vals in units.items():
            if "shares" in unit_key.lower() or "usd" in unit_key.lower():
                entries = unit_vals
                break
        if entries is None:
            warnings.warn(f"{ticker}: no USD/shares unit found in EarningsPerShareBasic")
            return pd.DataFrame()
    except KeyError:
        warnings.warn(f"{ticker}: EarningsPerShareBasic not found in EDGAR facts")
        return pd.DataFrame()

    rows = []
    for e in entries:
        form = e.get("form", "")
        if form not in ("10-Q", "10-K"):
            continue
        period_end = e.get("end", "")
        filed_date = e.get("filed", "")
        val = e.get("val", None)
        if not period_end or not filed_date or val is None:
            continue
        rows.append({
            "ticker": ticker,
            "period_end": pd.Timestamp(period_end),
            "filed_date": pd.Timestamp(filed_date),
            "eps": float(val),
            "form": form,
        })

    if not rows:
        warnings.warn(f"{ticker}: no valid 10-Q/10-K EPS rows from EDGAR")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Deduplicate: keep last filed per period_end (amendments supersede)
    df = df.sort_values("filed_date").drop_duplicates(subset=["ticker", "period_end"], keep="last")
    df = df.sort_values("period_end").reset_index(drop=True)
    return df


def build_eps_panel(tickers: list) -> pd.DataFrame:
    """
    Fetch EPS for all tickers and merge into one DataFrame.

    Returns DataFrame with columns: ticker, period_end, filed_date, eps, form.
    Tickers with no data are silently skipped (warned individually).
    """
    cik_map = load_cik_map()
    frames = []
    for ticker in tickers:
        cik = cik_map.get(ticker.upper())
        if cik is None:
            warnings.warn(f"{ticker}: not found in SEC EDGAR CIK map — skipping")
            continue
        df = fetch_edgar_eps(ticker, cik)
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["ticker", "period_end", "filed_date", "eps", "form"])
    return pd.concat(frames, ignore_index=True)


def compute_sue(eps_panel: pd.DataFrame, lookback_quarters: int = 8) -> pd.DataFrame:
    """
    Compute time-series SUE (seasonal random walk, Bernard & Thomas 1989):

        eps_surprise_q = eps_actual_q - eps_actual_same_quarter_prior_year
        eps_surprise_std = rolling_std(eps_surprise, window=lookback_quarters)
        SUE = eps_surprise_q / eps_surprise_std

    Returns DataFrame with columns:
        ticker, filing_date, period_end, eps, eps_prior_year_same_q, sue

    Uses filed_date as the forward-knowledge cutoff — never uses period_end for signal.
    Annual (10-K) filings are excluded from the SUE time-series (quarterly seasonality).
    """
    if eps_panel.empty:
        return pd.DataFrame(
            columns=["ticker", "filing_date", "period_end", "eps", "eps_prior_year_same_q", "sue"]
        )

    # Only quarterly (10-Q) filings for SUE seasonal comparison
    quarterly = eps_panel[eps_panel["form"] == "10-Q"].copy()
    # Infer fiscal quarter from period_end month
    quarterly["fiscal_q"] = quarterly["period_end"].dt.month.map(
        {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4}
    )
    quarterly["fiscal_year"] = quarterly["period_end"].dt.year

    rows = []
    for ticker, grp in quarterly.groupby("ticker"):
        grp = grp.sort_values("period_end").reset_index(drop=True)
        surprises = []
        for i, row in grp.iterrows():
            fq = row["fiscal_q"]
            fy = row["fiscal_year"]
            # Prior year same quarter: same fiscal_q, fiscal_year - 1
            prior = grp[(grp["fiscal_q"] == fq) & (grp["fiscal_year"] == fy - 1)]
            if prior.empty:
                surprises.append(np.nan)
                continue
            eps_py = float(prior["eps"].iloc[-1])
            surprise = row["eps"] - eps_py
            surprises.append(surprise)

        grp["eps_surprise"] = surprises
        # Rolling std of surprises over lookback_quarters for standardisation
        grp["surprise_std"] = grp["eps_surprise"].rolling(lookback_quarters, min_periods=2).std()
        grp["eps_prior_year_same_q"] = grp["eps"] - grp["eps_surprise"]

        # SUE = surprise / std; nan where std=0 or surprise is nan
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            grp["sue"] = grp["eps_surprise"] / grp["surprise_std"].replace(0, np.nan)

        for _, row in grp.iterrows():
            if pd.isna(row.get("sue", np.nan)):
                continue
            rows.append({
                "ticker": ticker,
                "filing_date": row["filed_date"],   # POINT-IN-TIME: use filed_date
                "period_end": row["period_end"],
                "eps": row["eps"],
                "eps_prior_year_same_q": row["eps_prior_year_same_q"],
                "sue": row["sue"],
            })

    if not rows:
        return pd.DataFrame(
            columns=["ticker", "filing_date", "period_end", "eps", "eps_prior_year_same_q", "sue"]
        )
    result = pd.DataFrame(rows)
    result = result.sort_values(["ticker", "filing_date"]).reset_index(drop=True)
    return result


def get_sue_as_of(sue_df: pd.DataFrame, as_of_date) -> pd.Series:
    """
    Return latest SUE per ticker as of as_of_date (point-in-time safe).

    CRITICAL POINT-IN-TIME GUARD: filters filed_date <= as_of_date,
    ensuring only filings the market could have known by that date are used.

    Returns pd.Series indexed by ticker, values = most recent SUE.
    """
    as_of_date = pd.Timestamp(as_of_date)
    # Only filings already received by SEC on or before as_of_date
    visible = sue_df[sue_df["filing_date"] <= as_of_date]  # POINT-IN-TIME GUARD
    if visible.empty:
        return pd.Series(dtype=float)
    # Latest filing per ticker
    latest = visible.sort_values("filing_date").groupby("ticker").last()
    return latest["sue"]
