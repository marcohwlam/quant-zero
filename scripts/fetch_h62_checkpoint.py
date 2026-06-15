"""
H62 Alpaca 30m Checkpoint Fetcher
Saves partial data every SAVE_EVERY pages so heartbeat kills don't lose all progress.
Resume by running again — detects checkpoint and continues from last saved page token.
"""
import os, sys, json, time, pickle, logging
from pathlib import Path

import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("h62_ckpt")

# Load .env
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

UNIVERSE_49 = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA',
    'JPM', 'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'BAC', 'INTC', 'CSCO',
    'VZ', 'PFE', 'KO', 'PEP', 'MRK', 'ABT', 'TMO', 'WMT', 'DIS', 'CMCSA',
    'NKE', 'IBM', 'MCD', 'ACN', 'TXN', 'QCOM', 'SBUX', 'GS', 'MS', 'AXP',
    'BA', 'CAT', 'HON', 'MMM', 'MDT', 'USB', 'C', 'WFC', 'MO', 'CL',
    'GE', 'XOM',
]

OUTPUT_DIR    = Path(__file__).resolve().parent / "strategies" / "data" / "h62"
PARQUET_PATH  = OUTPUT_DIR / "bars_30m.parquet"
CHECKPOINT    = OUTPUT_DIR / "fetch_checkpoint.pkl"
SAVE_EVERY    = 50   # save every N pages
MAX_SECONDS   = 480  # stop after 8 min and save checkpoint (leaves 1 min buffer in 9-min timeout)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_chunk(page_token: str | None, symbols_str: str) -> tuple[list[dict], str | None]:
    """Fetch one page. Returns (rows, next_page_token)."""
    params = {
        "symbols":   symbols_str,
        "timeframe": "30Min",
        "start":     "2021-10-01T00:00:00Z",
        "end":       "2024-12-31T23:59:59Z",
        "adjustment": "all",
        "feed":      "sip",
        "limit":     10000,
        "sort":      "asc",
    }
    if page_token:
        params["page_token"] = page_token

    resp = requests.get(
        f"{DATA_URL}/v2/stocks/bars",
        headers=HEADERS, params=params, timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    bars_by_sym = data.get("bars", {})
    rows = []
    for sym, bars in bars_by_sym.items():
        for b in bars:
            rows.append({
                "symbol":    sym,
                "timestamp": b["t"],
                "open":      b["o"],
                "high":      b["h"],
                "low":       b["l"],
                "close":     b["c"],
                "volume":    b["v"],
            })
    return rows, data.get("next_page_token")


def main():
    if not API_KEY or not API_SECRET:
        log.error("Missing ALPACA_API_KEY / ALPACA_API_SECRET"); sys.exit(1)

    symbols_str = ",".join(UNIVERSE_49)
    t_start = time.time()

    # Load checkpoint if it exists
    if CHECKPOINT.exists():
        ckpt = pickle.loads(CHECKPOINT.read_bytes())
        all_rows: list[dict] = ckpt["rows"]
        next_token: str | None = ckpt["next_token"]
        page_num: int = ckpt["page_num"]
        log.info("Resuming from checkpoint: page %d, %d rows, next_token=%s",
                 page_num, len(all_rows), next_token[:20] if next_token else "None")
        if next_token is None:
            log.info("Checkpoint shows complete fetch. Saving parquet and exiting.")
            _save_parquet(all_rows)
            CHECKPOINT.unlink(missing_ok=True)
            return
    else:
        all_rows = []
        next_token = None
        page_num = 0
        log.info("Starting fresh fetch: %d symbols, 2021-10-01 → 2024-12-31", len(UNIVERSE_49))

    done = False
    while True:
        elapsed = time.time() - t_start
        if elapsed > MAX_SECONDS:
            log.info("Time limit %.0fs reached at page %d (%d rows). Saving checkpoint.",
                     MAX_SECONDS, page_num, len(all_rows))
            break

        try:
            rows, next_token = fetch_chunk(next_token, symbols_str)
        except Exception as e:
            log.error("Fetch error page %d: %s", page_num + 1, e)
            break

        page_num += 1
        all_rows.extend(rows)

        if page_num % 10 == 0:
            log.info("Page %d: +%d rows (total %d, elapsed %.0fs)",
                     page_num, len(rows), len(all_rows), time.time() - t_start)

        if next_token is None:
            log.info("Fetch complete! %d rows in %d pages (%.0fs)",
                     len(all_rows), page_num, time.time() - t_start)
            done = True
            break

        if page_num % SAVE_EVERY == 0:
            _save_checkpoint(all_rows, next_token, page_num)

    # Save checkpoint (or final parquet if done)
    if done:
        _save_parquet(all_rows)
        CHECKPOINT.unlink(missing_ok=True)
        log.info("SUCCESS: %s written (%.1f MB)", PARQUET_PATH,
                 PARQUET_PATH.stat().st_size / 1e6)
    else:
        _save_checkpoint(all_rows, next_token, page_num)
        pct = len(all_rows) / 1_200_000 * 100
        log.info("CHECKPOINT saved — %.0f%% done (~%d rows). Re-run to continue.",
                 pct, len(all_rows))
        sys.exit(42)  # signal: needs another run


def _save_checkpoint(rows, next_token, page_num):
    CHECKPOINT.write_bytes(pickle.dumps({
        "rows":       rows,
        "next_token": next_token,
        "page_num":   page_num,
    }))
    log.info("Checkpoint saved: page %d, %d rows", page_num, len(rows))


def _save_parquet(rows):
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    df.to_parquet(PARQUET_PATH, index=False)

    # Summary
    summary = {
        "total_rows": len(df),
        "symbols": df["symbol"].nunique(),
        "tickers": {sym: len(grp) for sym, grp in df.groupby("symbol")},
    }
    (OUTPUT_DIR / "fetch_summary.json").write_text(json.dumps(summary, indent=2))
    log.info("Parquet: %d rows, %d symbols", len(df), df["symbol"].nunique())


if __name__ == "__main__":
    main()
