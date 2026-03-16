#!/usr/bin/env python3
"""
QuantConnect Public Strategy Discovery Script (QUA-146)

Discovers quantitative trading strategies from the QuantConnect public strategy library:
  https://www.quantconnect.com/strategies/

Steps:
  1. Scrape strategy listings from QC strategies page (HTML + embedded JSON)
  2. Parse per-strategy metadata: name, URL, asset class, backtest stats, clone count
  3. Apply pre-filters (asset class, backtest window ≥ 5yr, exclude top-10 cloned)
  4. Deduplicate against existing archive files in research/findings/qc_strategies/
  5. Write raw output (all scraped) and filtered output (max N candidates)

Output schema (per strategy):
  {
    "qc_id": str,           # QuantConnect strategy ID or slug
    "name": str,            # Strategy name
    "url": str,             # Full URL to strategy page
    "author": str,          # Author username
    "asset_class": str,     # "equities" | "options" | "crypto" | "forex" | "unknown"
    "strategy_type": str,   # "momentum" | "mean_reversion" | "breakout" | "ml" | "unknown"
    "sharpe": float | null, # Reported backtest Sharpe ratio
    "cagr": float | null,   # Reported CAGR (as decimal, e.g., 0.15 for 15%)
    "max_drawdown": float | null,  # Reported max drawdown (negative, e.g., -0.12)
    "backtest_years": float | null,  # Length of backtest window in years
    "clone_count": int,     # Number of times the strategy has been cloned/forked
    "description": str,     # Strategy description excerpt (≤500 chars)
    "tags": list[str],      # Tags/labels from the strategy page
    "discovery_method": str, # How metadata was obtained
    "fetched_at": str,      # ISO date
  }

Acquisition-time filters (applied before output):
  - asset_class ∈ {equities, options, crypto}
  - backtest_years ≥ 5 (or null — included but flagged)
  - Exclude top-10 most-cloned strategies (crowding risk)
  - Deduplicate against existing archive files

Usage:
    python research/scripts/qc_strategy_discovery.py
    python research/scripts/qc_strategy_discovery.py --date 2026-03-16
    python research/scripts/qc_strategy_discovery.py --max 10 --no-detail

Dependencies: requests (optional, falls back to urllib)
"""

import argparse
import json
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Optional

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    import urllib.request
    import urllib.error
    _REQUESTS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "research" / "findings" / "qc_strategies"

QC_BASE = "https://www.quantconnect.com"
QC_STRATEGIES_URL = f"{QC_BASE}/strategies/"

# QC paginates strategy listings; try a few pages
QC_BROWSE_PAGES = [
    f"{QC_STRATEGIES_URL}",
    f"{QC_STRATEGIES_URL}?page=2",
    f"{QC_STRATEGIES_URL}?page=3",
    f"{QC_STRATEGIES_URL}?page=4",
    f"{QC_STRATEGIES_URL}?page=5",
]

# Asset classes we care about
ACCEPTED_ASSET_CLASSES = {"equities", "options", "crypto"}

# Minimum backtest window in years (filter)
MIN_BACKTEST_YEARS = 5.0

# Crowding exclusion: skip strategies above this clone count percentile
# Evaluated dynamically from the scraped set (top-10 most cloned excluded)
TOP_N_CROWDED_TO_EXCLUDE = 10

REQUEST_DELAY = 1.0  # seconds between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get_html(url: str, timeout: int = 20) -> Optional[str]:
    """Fetch URL and return response text; returns None on failure."""
    try:
        if _REQUESTS_AVAILABLE:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        else:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("Request failed: %s — %s", url[:80], exc)
        return None


# ---------------------------------------------------------------------------
# Strategy link collection
# ---------------------------------------------------------------------------

# QC strategy URLs follow: /strategies/{id}-{slug}/ or /strategies/{id}/
_QC_STRATEGY_LINK_RE = re.compile(
    r'href="(/strategies/[a-zA-Z0-9][a-zA-Z0-9_-]+/?)(?:"|\s|>)'
)

# Embedded JSON data — QC sometimes hydrates page state as window.__INITIAL_STATE__
_QC_INITIAL_STATE_RE = re.compile(
    r'window\.__(?:INITIAL_STATE|APP_STATE|QC_DATA)__\s*=\s*(\{.+?\})(?:;</script>|;\s*\n)',
    re.DOTALL,
)

# JSON array of strategies sometimes embedded in <script type="application/json">
_QC_JSON_SCRIPT_RE = re.compile(
    r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _extract_strategy_links_from_html(html: str) -> set[str]:
    """Extract all /strategies/... hrefs from raw HTML."""
    raw = set(_QC_STRATEGY_LINK_RE.findall(html))
    # Exclude the root /strategies/ listing page itself
    return {
        QC_BASE + href.rstrip("/") + "/"
        for href in raw
        if href not in {"/strategies/", "/strategies"}
        and len(href.strip("/").split("/")[-1]) > 3  # skip very short IDs/slugs
    }


def _extract_strategy_data_from_json(html: str) -> list[dict]:
    """
    Try to extract strategy records from embedded JSON in the page.
    QC embeds strategy data as JSON in <script type="application/json"> tags.
    Returns list of raw dicts or empty list if not found.
    """
    candidates = []

    # Try JSON script blocks
    for m in _QC_JSON_SCRIPT_RE.finditer(html):
        raw = m.group(1).strip()
        if len(raw) < 20:
            continue
        try:
            data = json.loads(raw)
            # Look for a list or dict containing strategy records
            if isinstance(data, list) and data and isinstance(data[0], dict):
                if any(k in data[0] for k in ("name", "title", "sharpe", "cagr", "id")):
                    candidates.extend(data)
            elif isinstance(data, dict):
                # Recurse one level for nested arrays
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        if any(k in v[0] for k in ("name", "title", "sharpe", "cagr", "id")):
                            candidates.extend(v)
        except (json.JSONDecodeError, KeyError, IndexError):
            continue

    # Try window.__INITIAL_STATE__
    m = _QC_INITIAL_STATE_RE.search(html)
    if m:
        try:
            data = json.loads(m.group(1))
            # Walk top-level keys looking for strategy arrays
            for v in data.values():
                if isinstance(v, dict):
                    for vv in v.values():
                        if isinstance(vv, list) and vv and isinstance(vv[0], dict):
                            if any(k in vv[0] for k in ("name", "sharpe", "cagr")):
                                candidates.extend(vv)
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    log.debug("JSON extraction yielded %d candidate records", len(candidates))
    return candidates


def collect_strategy_links(browse_urls: list[str]) -> tuple[list[str], list[dict]]:
    """
    Collect strategy page URLs (for detail scraping) and any inline JSON records.

    Returns:
        (links, json_records): list of strategy URLs + any pre-extracted JSON records
    """
    all_links: set[str] = set()
    json_records: list[dict] = []

    for url in browse_urls:
        html = _get_html(url)
        if html is None:
            log.warning("Skipping browse URL (no response): %s", url)
            continue

        links = _extract_strategy_links_from_html(html)
        new_count = len(links - all_links)
        all_links |= links
        log.info("Browse %s → %d links (%d new)", url[:70], len(links), new_count)

        inline = _extract_strategy_data_from_json(html)
        if inline:
            log.info("  JSON records found in page: %d", len(inline))
            json_records.extend(inline)

        time.sleep(REQUEST_DELAY)

    log.info("Total unique strategy links: %d | JSON records: %d", len(all_links), len(json_records))
    return sorted(all_links), json_records


# ---------------------------------------------------------------------------
# Individual strategy page parsing
# ---------------------------------------------------------------------------

# Patterns to pull stats from strategy detail HTML
_STAT_PATTERNS = {
    # QC often shows stats in <td> or <span> near labeled rows
    "sharpe": re.compile(
        r"(?:sharpe\s*(?:ratio)?)\s*[:\|]?\s*<[^>]*>?\s*([-+]?\d+\.?\d*)",
        re.IGNORECASE,
    ),
    "cagr": re.compile(
        r"(?:cagr|annual\s*return|annualized\s*return)\s*[:\|]?\s*<[^>]*>?\s*([-+]?\d+\.?\d*)\s*%?",
        re.IGNORECASE,
    ),
    "max_drawdown": re.compile(
        r"(?:max(?:imum)?\s*drawdown|drawdown)\s*[:\|]?\s*<[^>]*>?\s*([-+]?\d+\.?\d*)\s*%?",
        re.IGNORECASE,
    ),
    "clone_count": re.compile(
        r"(?:clone[sd]?|fork[sed]*)\s*[:\|]?\s*<[^>]*>?\s*(\d+)",
        re.IGNORECASE,
    ),
}

# Backtest window: look for "N years" / "YYYY-MM-DD to YYYY-MM-DD" patterns
_BACKTEST_YEARS_RE = re.compile(
    r"(?:backtest\s+(?:period|window|length)|tested\s+(?:over|for))\D{0,30}(\d+)\s*(?:years?|yr)",
    re.IGNORECASE,
)
_DATE_RANGE_RE = re.compile(
    r"(\d{4})-\d{2}-\d{2}\s+to\s+(\d{4})-\d{2}-\d{2}"
)


def _parse_float(text: str) -> Optional[float]:
    try:
        return float(text.strip().replace(",", "").replace("%", ""))
    except (ValueError, AttributeError):
        return None


def _parse_og(html: str, key: str) -> str:
    m = re.search(rf'<meta\s+property="og:{key}"\s+content="([^"]*)"', html)
    return m.group(1).strip() if m else ""


def _guess_asset_class(text: str) -> str:
    """Categorise strategy asset class from free text."""
    text_low = text.lower()
    if any(kw in text_low for kw in ("option", "put", "call", "straddle", "strangle", "theta")):
        return "options"
    if any(kw in text_low for kw in ("btc", "eth", "crypto", "bitcoin", "ethereum", "altcoin", "defi")):
        return "crypto"
    if any(kw in text_low for kw in ("forex", "fx ", "currency pair", "eurusd", "gbpusd")):
        return "forex"
    if any(kw in text_low for kw in (
        "equity", "equities", "stock", "etf", "spy", "qqq", "shares", "s&p",
        "nasdaq", "nyse", "large.cap", "small.cap",
    )):
        return "equities"
    return "unknown"


def _guess_strategy_type(text: str) -> str:
    text_low = text.lower()
    if any(kw in text_low for kw in ("machine learning", "ml ", "neural", "random forest", "xgboost", "lstm")):
        return "ml"
    if any(kw in text_low for kw in ("mean rev", "reversion", "reversal", "cointegr", "pairs", "spread")):
        return "mean_reversion"
    if any(kw in text_low for kw in ("breakout", "channel break", "donchian")):
        return "breakout"
    if any(kw in text_low for kw in (
        "momentum", "trend following", "trend-following", "moving average",
        "ema", "sma", "macd", "crossover", "dual momentum",
    )):
        return "momentum"
    if any(kw in text_low for kw in ("volatility", "vix", "atr", "vol.targeting")):
        return "volatility"
    if any(kw in text_low for kw in ("arbitrage", "stat.arb")):
        return "arbitrage"
    return "unknown"


def _extract_backtest_years(html: str) -> Optional[float]:
    """Attempt to parse backtest window length from HTML."""
    m = _BACKTEST_YEARS_RE.search(html)
    if m:
        return float(m.group(1))

    # Try computing from date range
    dates = _DATE_RANGE_RE.findall(html)
    if dates:
        # Use the widest span found
        years = [(int(end) - int(start)) for start, end in dates]
        best = max(years, default=None)
        if best and best > 0:
            return float(best)

    return None


def _extract_tags(html: str) -> list[str]:
    """Extract strategy tags from HTML (QC uses <span class="tag"> or similar)."""
    tags = re.findall(r'<(?:span|a)[^>]+class="[^"]*tag[^"]*"[^>]*>([^<]{2,40})</', html, re.IGNORECASE)
    return [t.strip() for t in tags[:20]]


def _extract_qc_id(url: str) -> str:
    """Extract strategy ID or slug from QC URL."""
    m = re.search(r"/strategies/([a-zA-Z0-9][a-zA-Z0-9_-]+)/?", url)
    return m.group(1) if m else ""


def fetch_strategy_metadata(url: str, fetch_detail: bool = True) -> Optional[dict]:
    """
    Fetch and parse metadata for a single QC strategy page.
    If fetch_detail=False, only slug-derived metadata is returned (no HTTP request).
    """
    today = date.today().isoformat()
    qc_id = _extract_qc_id(url)
    slug_name = qc_id.replace("-", " ").replace("_", " ").title() if qc_id else ""

    if not fetch_detail:
        combined = slug_name
        return {
            "qc_id": qc_id,
            "name": slug_name,
            "url": url,
            "author": "",
            "asset_class": _guess_asset_class(combined),
            "strategy_type": _guess_strategy_type(combined),
            "sharpe": None,
            "cagr": None,
            "max_drawdown": None,
            "backtest_years": None,
            "clone_count": 0,
            "description": "",
            "tags": [],
            "discovery_method": "slug-only",
            "fetched_at": today,
        }

    html = _get_html(url)
    if html is None:
        return None

    # Prefer og:title for name
    og_title = _parse_og(html, "title")
    og_desc = _parse_og(html, "description")[:500]

    # Clean name: strip "| QuantConnect" suffixes
    name = re.sub(r"\s*\|\s*QuantConnect.*$", "", og_title, flags=re.IGNORECASE).strip()
    name = name or slug_name

    # Author from structured data or meta
    author_m = re.search(r'"author"\s*:\s*\{\s*"name"\s*:\s*"([^"]+)"', html)
    author = author_m.group(1).strip() if author_m else ""

    combined = f"{name} {og_desc}"

    # Extract stats via pattern matching on raw HTML
    stats: dict[str, Optional[float]] = {}
    for stat, pattern in _STAT_PATTERNS.items():
        m = pattern.search(html)
        if m:
            val = _parse_float(m.group(1))
            # Normalize: drawdown should be negative; CAGR from percent to decimal
            if stat == "max_drawdown" and val is not None and val > 0:
                val = -val / 100.0 if val > 1 else -val
            elif stat == "cagr" and val is not None and val > 1:
                val = val / 100.0
            stats[stat] = val
        else:
            stats[stat] = None

    backtest_years = _extract_backtest_years(html)
    tags = _extract_tags(html)

    clone_count = int(stats.pop("clone_count", 0) or 0)

    return {
        "qc_id": qc_id,
        "name": name,
        "url": url,
        "author": author,
        "asset_class": _guess_asset_class(combined),
        "strategy_type": _guess_strategy_type(combined),
        "sharpe": stats.get("sharpe"),
        "cagr": stats.get("cagr"),
        "max_drawdown": stats.get("max_drawdown"),
        "backtest_years": backtest_years,
        "clone_count": clone_count,
        "description": og_desc,
        "tags": tags,
        "discovery_method": "html-scrape",
        "fetched_at": today,
    }


def _coerce_json_record(raw: dict, source_url: str = "") -> Optional[dict]:
    """
    Normalise a raw JSON record extracted from embedded page data
    into the canonical output schema.
    """
    today = date.today().isoformat()

    # Extract name: try several common key names
    name = (
        raw.get("name") or raw.get("title") or raw.get("strategyName") or ""
    ).strip()
    if not name:
        return None

    qc_id = str(raw.get("id") or raw.get("strategyId") or "")
    url = raw.get("url") or raw.get("link") or (f"{QC_BASE}/strategies/{qc_id}" if qc_id else source_url)
    author = str(raw.get("author") or raw.get("authorName") or raw.get("userName") or "")

    # Stats — QC JSON may use various key names
    sharpe = _parse_float(str(raw.get("sharpe") or raw.get("sharpeRatio") or ""))
    cagr = _parse_float(str(raw.get("cagr") or raw.get("annualReturn") or raw.get("returns") or ""))
    if cagr is not None and abs(cagr) > 1:
        cagr = cagr / 100.0  # percent → decimal
    max_dd = _parse_float(str(raw.get("maxDrawdown") or raw.get("drawdown") or ""))
    if max_dd is not None and max_dd > 0:
        max_dd = -abs(max_dd) / (100.0 if abs(max_dd) > 1 else 1.0)

    years = _parse_float(str(raw.get("backtestYears") or raw.get("years") or ""))
    if years is None:
        start = raw.get("start") or raw.get("startDate") or ""
        end = raw.get("end") or raw.get("endDate") or ""
        if start and end:
            try:
                from datetime import datetime
                y_start = int(str(start)[:4])
                y_end = int(str(end)[:4])
                years = float(y_end - y_start)
            except (ValueError, TypeError):
                pass

    clone_count = int(raw.get("cloneCount") or raw.get("forkCount") or raw.get("clones") or 0)
    description = (raw.get("description") or raw.get("summary") or "")[:500]
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    combined = f"{name} {description} {' '.join(tags)}"

    return {
        "qc_id": qc_id,
        "name": name,
        "url": str(url),
        "author": author,
        "asset_class": _guess_asset_class(combined),
        "strategy_type": _guess_strategy_type(combined),
        "sharpe": sharpe,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "backtest_years": years,
        "clone_count": clone_count,
        "description": description,
        "tags": tags if isinstance(tags, list) else list(tags),
        "discovery_method": "embedded-json",
        "fetched_at": today,
    }


# ---------------------------------------------------------------------------
# Deduplication against archive
# ---------------------------------------------------------------------------

def load_seen_ids(archive_dir: Path) -> set[str]:
    """
    Load all qc_id values from existing archive files to prevent re-processing.
    Looks for both raw (*YYYY-MM-DD.json) and filtered (*_filtered.json) files.
    """
    seen: set[str] = set()
    for f in archive_dir.glob("*.json"):
        if f.name.startswith("."):
            continue
        try:
            data = json.loads(f.read_text())
            if isinstance(data, list):
                for rec in data:
                    qc_id = rec.get("qc_id") or ""
                    if qc_id:
                        seen.add(qc_id)
        except (json.JSONDecodeError, OSError):
            continue
    log.info("Archive dedup: %d previously-seen QC IDs", len(seen))
    return seen


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def _passes_asset_filter(item: dict) -> bool:
    return item.get("asset_class") in ACCEPTED_ASSET_CLASSES


def _passes_backtest_window_filter(item: dict) -> bool:
    """Accept items with backtest_years ≥ 5 OR where years is unknown (None)."""
    years = item.get("backtest_years")
    return years is None or years >= MIN_BACKTEST_YEARS


def apply_pre_filters(items: list[dict], seen_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """
    Apply acquisition-time filters and return (passing, rejected) lists.

    Filters:
      1. Asset class ∈ {equities, options, crypto}
      2. Backtest window ≥ 5 years (or unknown — flagged, not rejected)
      3. Not already seen in archive
      4. Top-10 most-cloned excluded (crowding risk; computed after sorting)
    """
    # Step 1: asset class + archive dedup
    candidates = []
    rejected_count = 0
    for item in items:
        qc_id = item.get("qc_id") or ""
        if qc_id and qc_id in seen_ids:
            log.debug("Dedup skip: %s", qc_id)
            rejected_count += 1
            continue
        if not _passes_asset_filter(item):
            log.debug("Asset filter drop: %s (%s)", item.get("name"), item.get("asset_class"))
            rejected_count += 1
            continue
        candidates.append(item)

    log.info("After asset filter + dedup: %d kept, %d dropped", len(candidates), rejected_count)

    # Step 2: identify and exclude top-10 most-cloned (crowding risk)
    sorted_by_clones = sorted(candidates, key=lambda x: x.get("clone_count", 0), reverse=True)
    crowded_ids: set[str] = set()
    for item in sorted_by_clones[:TOP_N_CROWDED_TO_EXCLUDE]:
        clone_cnt = item.get("clone_count", 0)
        if clone_cnt > 0:  # only exclude if we actually have clone data
            qc_id = item.get("qc_id") or item.get("name")
            crowded_ids.add(qc_id)
            log.info("Crowding exclusion: %s (clones=%d)", item.get("name"), clone_cnt)

    filtered, rejected = [], []
    for item in candidates:
        qc_id = item.get("qc_id") or item.get("name")
        if qc_id in crowded_ids:
            item["crowding_excluded"] = True
            rejected.append(item)
            continue
        # Flag (but don't reject) items with unknown backtest window
        if not _passes_backtest_window_filter(item):
            item["window_too_short"] = True
            rejected.append(item)
            continue
        filtered.append(item)

    log.info("After crowding + window filters: %d passing, %d rejected", len(filtered), len(rejected))
    return filtered, rejected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="QuantConnect public strategy discovery (QUA-146)",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Output date label (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=10,
        metavar="N",
        help="Maximum number of strategies in the filtered output (default: 10).",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Skip individual strategy page visits — use URL slug only (faster).",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        metavar="N",
        help="Number of QC strategy listing pages to browse (default: 5).",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUTPUT_DIR / f"{args.date}.json"
    filtered_path = OUTPUT_DIR / f"{args.date}_filtered.json"

    log.info("=== QuantConnect Strategy Discovery (QUA-146) ===")
    log.info("Date: %s | Max filtered: %d | Detail scraping: %s",
             args.date, args.max, not args.no_detail)
    log.info("Raw output:      %s", raw_path)
    log.info("Filtered output: %s", filtered_path)

    # ── Step 1: Load archive seen IDs for deduplication ───────────────────────
    log.info("--- Step 1: Loading archive for deduplication ---")
    seen_ids = load_seen_ids(OUTPUT_DIR)

    # ── Step 2: Collect strategy links from browse pages ──────────────────────
    log.info("--- Step 2: Collecting strategy links ---")
    browse_urls = QC_BROWSE_PAGES[:max(1, args.pages)]
    strategy_links, inline_json_records = collect_strategy_links(browse_urls)

    # ── Step 3: Normalise inline JSON records ─────────────────────────────────
    all_items: list[dict] = []
    seen_in_batch: set[str] = set()

    for raw in inline_json_records:
        item = _coerce_json_record(raw)
        if item is None:
            continue
        uid = item.get("qc_id") or item.get("url")
        if uid in seen_in_batch:
            continue
        seen_in_batch.add(uid)
        all_items.append(item)

    log.info("Inline JSON records normalised: %d", len(all_items))

    # ── Step 4: Fetch detail for HTML-scraped links ───────────────────────────
    log.info("--- Step 4: Fetching detail for %d strategy pages ---", len(strategy_links))
    for i, url in enumerate(strategy_links, 1):
        qc_id = _extract_qc_id(url)
        if qc_id in seen_in_batch:
            continue

        log.debug("[%d/%d] %s", i, len(strategy_links), url)
        item = fetch_strategy_metadata(url, fetch_detail=not args.no_detail)
        if item is None:
            continue

        uid = item.get("qc_id") or url
        if uid in seen_in_batch:
            continue
        seen_in_batch.add(uid)
        all_items.append(item)

        if not args.no_detail:
            time.sleep(REQUEST_DELAY)

    log.info("Total raw strategies collected: %d", len(all_items))

    # ── Step 5: Write raw output ───────────────────────────────────────────────
    with open(raw_path, "w") as f:
        json.dump(all_items, f, indent=2)
    log.info("Raw output written: %s (%d records)", raw_path, len(all_items))

    # ── Step 6: Apply pre-filters ─────────────────────────────────────────────
    log.info("--- Step 6: Applying pre-filters ---")
    filtered, rejected = apply_pre_filters(all_items, seen_ids)

    # Sort: prefer items with known Sharpe (higher = better), then by CAGR
    filtered.sort(
        key=lambda x: (
            -(x.get("sharpe") or -99),
            -(x.get("cagr") or -99),
        )
    )

    # Cap at --max
    filtered = filtered[:args.max]

    # ── Step 7: Write filtered output ─────────────────────────────────────────
    with open(filtered_path, "w") as f:
        json.dump(filtered, f, indent=2)
    log.info("Filtered output written: %s (%d records)", filtered_path, len(filtered))

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"QC Strategy Discovery — {args.date}")
    print("=" * 60)
    print(f"Browse pages:       {len(browse_urls)}")
    print(f"Raw strategies:     {len(all_items)}")
    print(f"After filters:      {len(filtered)}")
    print(f"Raw file:           {raw_path.name}")
    print(f"Filtered file:      {filtered_path.name}")
    print()
    if filtered:
        print("Top candidates (filtered):")
        for i, item in enumerate(filtered, 1):
            sharpe_str = f"Sharpe={item['sharpe']:.2f}" if item.get("sharpe") else "Sharpe=N/A"
            cagr_str = f"CAGR={item['cagr']:.1%}" if item.get("cagr") else ""
            years_str = f"Yrs={item['backtest_years']:.0f}" if item.get("backtest_years") else "Yrs=?"
            clones_str = f"Clones={item['clone_count']}"
            print(f"  [{i}] {item['name'][:45]:<45} {sharpe_str}  {cagr_str}  {years_str}  {clones_str}")
    else:
        print("No candidates passed filters. Try --no-detail or --pages to increase coverage.")
        print()
        print("Troubleshooting:")
        print("  - QC may require JS rendering for full strategy listings")
        print("  - Try running with --no-detail for slug-based discovery")
        print(f"  - Raw output still written to {raw_path.name} for inspection")

    return filtered


if __name__ == "__main__":
    main()
