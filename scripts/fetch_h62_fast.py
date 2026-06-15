"""
Fast H62 Alpaca data fetcher — multi-symbol batch endpoint.
Downloads all 50 tickers using /v2/stocks/bars?symbols=... in paginated batches.
Much faster than per-symbol sequential: ~3-6 requests total vs 150+.
"""

import os, sys, json, time, logging
from pathlib import Path

import requests
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_h62_fast")

# Load broker/.env
_ENV = Path(__file__).resolve().parent / "broker" / ".env"
if _ENV.exists():
    for _line in _ENV.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        k, _, v = _line.partition("=")
        k, v = k.strip(), v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v

API_KEY    = os.environ.get("ALPACA_API_KEY", "")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "")
DATA_URL   = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets")

HEADERS = {
    "APCA-API-KEY-ID":     API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET,
    "Accept":              "application/json",
}

UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA', 'BRK-B',
    'JPM', 'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'BAC', 'INTC', 'CSCO',
    'VZ', 'PFE', 'KO', 'PEP', 'MRK', 'ABT', 'TMO', 'WMT', 'DIS', 'CMCSA',
    'NKE', 'IBM', 'MCD', 'ACN', 'TXN', 'QCOM', 'SBUX', 'GS', 'MS', 'AXP',
    'BA', 'CAT', 'HON', 'MMM', 'MDT', 'USB', 'C', 'WFC', 'MO', 'CL',
    'GE', 'XOM',
]
# BRK-B is not supported by Alpaca multi-symbol endpoint — skip it
# (Warren Buffett's class B shares; Alpaca symbol is BRK.B but rarely needed)
ALPACA_SYMS = [s for s in UNIVERSE if s != 'BRK-B']
SYM_MAP_BACK: dict = {}  # no remapping needed when BRK-B excluded

OUTPUT_DIR   = Path(__file__).resolve().parent / "strategies" / "data" / "h62"
PARQUET_PATH = OUTPUT_DIR / "bars_30m.parquet"
SUMMARY_PATH = OUTPUT_DIR / "fetch_summary.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

START = "2021-10-01T00:00:00Z"
END   = "2024-12-31T23:59:59Z"


def fetch_all_symbols() -> pd.DataFrame:
    """
    Fetch 30m bars for all 50 symbols using the multi-symbol Alpaca endpoint.
    Handles pagination via next_page_token.
    Returns long-format DataFrame with columns: symbol, timestamp, open, high, low, close, volume.
    """
    url = f"{DATA_URL}/v2/stocks/bars"
    params = {
        "symbols":   ",".join(ALPACA_SYMS),
        "timeframe": "30Min",
        "start":     START,
        "end":       END,
        "adjustment": "all",
        "feed":      "sip",
        "limit":     10000,
        "sort":      "asc",
    }

    all_frames: list[pd.DataFrame] = []
    page = 0
    total_rows = 0
    t0 = time.time()

    while True:
        page += 1
        log.info("Page %d — fetching ... (elapsed %.0fs)", page, time.time() - t0)
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=60)
            resp.raise_for_status()
        except requests.HTTPError as e:
            log.error("HTTP error: %s  body=%s", e, resp.text[:200])
            raise

        data = resp.json()
        bars_by_sym = data.get("bars", {})

        # Flatten to rows
        rows = []
        for sym, bars in bars_by_sym.items():
            out_sym = SYM_MAP_BACK.get(sym, sym)
            for b in bars:
                rows.append({
                    "symbol":    out_sym,
                    "timestamp": b["t"],
                    "open":      b["o"],
                    "high":      b["h"],
                    "low":       b["l"],
                    "close":     b["c"],
                    "volume":    b["v"],
                })
        if rows:
            frame = pd.DataFrame(rows)
            all_frames.append(frame)
            total_rows += len(rows)

        sym_counts = {SYM_MAP_BACK.get(s, s): len(bs) for s, bs in bars_by_sym.items()}
        log.info("  page %d: %d rows for %d symbols (total so far: %d)",
                 page, len(rows), len(bars_by_sym), total_rows)

        next_token = data.get("next_page_token")
        if not next_token:
            log.info("No more pages. Done in %.0fs", time.time() - t0)
            break
        params["page_token"] = next_token

    if not all_frames:
        raise RuntimeError("No data returned from Alpaca multi-symbol endpoint")

    combined = pd.concat(all_frames, ignore_index=True)
    combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
    combined = combined.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    log.info("Total: %d rows across %d symbols", len(combined), combined["symbol"].nunique())
    return combined


def save_and_validate(df: pd.DataFrame) -> dict:
    log.info("Saving to %s ...", PARQUET_PATH)
    df.to_parquet(PARQUET_PATH, index=False)
    log.info("Saved. File size: %.1f MB", PARQUET_PATH.stat().st_size / 1e6)

    summary = {
        "total_rows": len(df),
        "symbols_fetched": df["symbol"].nunique(),
        "start_date": str(df["timestamp"].min()),
        "end_date":   str(df["timestamp"].max()),
        "tickers": {},
        "warnings": [],
    }
    for sym, grp in df.groupby("symbol"):
        summary["tickers"][sym] = {
            "row_count": len(grp),
            "min_ts": str(grp["timestamp"].min()),
            "max_ts": str(grp["timestamp"].max()),
        }
        if len(grp) < 5000:
            msg = f"WARNING: {sym} only {len(grp)} rows"
            log.warning(msg)
            summary["warnings"].append(msg)

    missing = [s for s in UNIVERSE if s not in summary["tickers"]]
    if missing:
        msg = f"Missing tickers: {missing}"
        log.warning(msg)
        summary["warnings"].append(msg)

    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    log.info("Summary: %s", SUMMARY_PATH)
    return summary


def main():
    log.info("Fast H62 fetch: %d symbols, %s → %s", len(UNIVERSE), START[:10], END[:10])
    if not API_KEY or not API_SECRET:
        log.error("Missing ALPACA_API_KEY / ALPACA_API_SECRET")
        sys.exit(1)

    df = fetch_all_symbols()
    summary = save_and_validate(df)

    print(f"\n{'='*60}")
    print(f"FETCH COMPLETE")
    print(f"  Total rows : {summary['total_rows']:,}")
    print(f"  Symbols    : {summary['symbols_fetched']}/{len(UNIVERSE)}")
    if summary["warnings"]:
        print(f"  Warnings   : {len(summary['warnings'])}")
        for w in summary["warnings"]:
            print(f"    {w}")
    else:
        print("  No warnings.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
