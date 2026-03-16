#!/usr/bin/env python3
"""
TradingView Strategy Discovery Script — Phase 1 (QUA-108 / QUA-115)

Discovers TradingView community strategy and indicator scripts by:
  1. Collecting script page URLs from TV browse/search pages
  2. Visiting each individual script page for og: metadata
  3. Applying acquisition-time filters

Output: research/findings/tv_ideas/YYYY-MM-DD.json

Acquisition-time filters:
  - Tags / description include at least one relevance keyword
  - script_type guessed as strategy or indicator (both accepted)
  - Holding period NOT intraday-only (PDT risk)

Dependencies: requests (stdlib fallback if unavailable)

Usage:
    python tv_idea_discovery.py                    # today's date
    python tv_idea_discovery.py --date 2026-03-16  # specific date
    python tv_idea_discovery.py --pages 5          # browse pages to collect (default: 4)
    python tv_idea_discovery.py --no-detail        # skip individual page visits (fast but less metadata)
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
OUTPUT_DIR = REPO_ROOT / "research" / "findings" / "tv_ideas"

TV_BASE = "https://www.tradingview.com"

# Browse pages that consistently contain script links in the page HTML
BROWSE_PAGES = [
    f"{TV_BASE}/scripts/",
    f"{TV_BASE}/scripts/editors-picks/",
    f"{TV_BASE}/scripts/search/?text=momentum+strategy",
    f"{TV_BASE}/scripts/search/?text=mean+reversion+strategy",
    f"{TV_BASE}/scripts/search/?text=ema+crossover+strategy",
    f"{TV_BASE}/scripts/search/?text=rsi+oscillator+strategy",
    f"{TV_BASE}/scripts/search/?text=macd+strategy",
    f"{TV_BASE}/scripts/search/?text=breakout+strategy",
    f"{TV_BASE}/scripts/search/?text=volatility+strategy",
    f"{TV_BASE}/scripts/search/?text=crypto+momentum+strategy",
    f"{TV_BASE}/scripts/search/?text=pairs+trading+indicator",
    f"{TV_BASE}/scripts/search/?text=bollinger+band+strategy",
    f"{TV_BASE}/scripts/search/?text=trend+following",
]

# Additional paginated browse pages
PAGINATED_PAGES = [f"{TV_BASE}/scripts/page-{i}/" for i in range(2, 6)]

# Keywords: at least one must appear in combined name/description for relevance
RELEVANCE_KEYWORDS = {
    "momentum", "mean reversion", "mean-reversion", "reversion", "reversal",
    "breakout", "trend", "ema", "sma", "macd", "rsi", "bollinger", "atr",
    "crossover", "swing", "volatility", "pairs", "spread", "cointegr",
    "moving average", "oscillator",
}

REQUEST_DELAY = 0.8  # seconds between requests (be polite to TV servers)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
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

def _get_html(url: str, timeout: int = 15) -> Optional[str]:
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
# Link collection
# ---------------------------------------------------------------------------

def collect_script_links(browse_urls: list[str]) -> list[str]:
    """
    Scrape each browse URL and collect unique TV script page URLs.
    TV embeds these as href="/script/{id}-{slug}/" in the page HTML.
    """
    all_links: set[str] = set()
    pattern = re.compile(
        r'href="(https://www\.tradingview\.com/script/[a-zA-Z0-9_-]+/)"'
    )

    for url in browse_urls:
        html = _get_html(url)
        if html is None:
            continue
        found = pattern.findall(html)
        # Deduplicate: strip #anchor variants
        clean = {link.split("#")[0] for link in found}
        new_count = len(clean - all_links)
        all_links |= clean
        log.info("Browse %s → %d links (%d new)", url[:70], len(clean), new_count)
        time.sleep(REQUEST_DELAY)

    log.info("Total unique script links collected: %d", len(all_links))
    return sorted(all_links)


# ---------------------------------------------------------------------------
# Individual script page metadata extraction
# ---------------------------------------------------------------------------

def _parse_og(html: str, key: str) -> str:
    """Extract og: meta tag value from HTML."""
    m = re.search(rf'<meta\s+property="og:{key}"\s+content="([^"]*)"', html)
    return m.group(1).strip() if m else ""


def _parse_script_type_from_title(title: str) -> str:
    """
    TV og:title format: "Script Name — Indicator by Author" or "— Strategy by Author".
    Returns 'strategy' or 'indicator'.
    """
    title_lower = title.lower()
    if " strategy by " in title_lower or "strategy —" in title_lower:
        return "strategy"
    return "indicator"


def _guess_asset_class(text: str) -> str:
    """Guess asset class from combined text."""
    text_low = text.lower()
    crypto_kw = {"btc", "eth", "crypto", "bitcoin", "ethereum", "altcoin", "defi", "xbt"}
    if any(kw in text_low for kw in crypto_kw):
        return "crypto"
    return "equities"


def _guess_strategy_type(text: str) -> str:
    """Guess strategy type from combined text."""
    text_low = text.lower()
    if any(kw in text_low for kw in ["mean rev", "meanrev", "revert", "reversion", "reversal"]):
        return "mean_reversion"
    if any(kw in text_low for kw in ["breakout", "break out"]):
        return "breakout"
    if any(kw in text_low for kw in ["pairs", "cointegr", "spread"]):
        return "pairs"
    if any(kw in text_low for kw in ["volatil", "atr", "squeeze"]):
        return "volatility"
    if any(kw in text_low for kw in [
        "momentum", "trend", "moving average", "ema", "sma", "macd",
        "rsi", "oscillator", "crossover",
    ]):
        return "momentum"
    return "unknown"


def _guess_holding_period(text: str) -> str:
    """Guess holding period from description text."""
    text_low = text.lower()
    if any(kw in text_low for kw in ["intraday", "scalp", "1 min", "5 min", "15 min", "1m ", "5m "]):
        return "intraday"
    if any(kw in text_low for kw in ["swing", "daily", "weekly", "day trade"]):
        return "swing"
    if any(kw in text_low for kw in ["position", "monthly", "long term", "long-term"]):
        return "position"
    return "swing"


def _extract_signals(text: str) -> list[str]:
    """Extract known signal indicator names from text."""
    text_low = text.lower()
    signal_patterns = [
        ("EMA", r"\bema\b"),
        ("SMA", r"\bsma\b"),
        ("RSI", r"\brsi\b"),
        ("MACD", r"\bmacd\b"),
        ("Bollinger Bands", r"\bbollinger\b"),
        ("ATR", r"\batr\b"),
        ("Stochastic", r"\bstochastic\b"),
        ("VWAP", r"\bvwap\b"),
        ("ADX", r"\badx\b"),
        ("CCI", r"\bcci\b"),
        ("OBV", r"\bobv\b"),
        ("Ichimoku", r"\bichimoku\b"),
        ("SuperTrend", r"\bsupertrend\b"),
    ]
    return [name for name, pat in signal_patterns if re.search(pat, text_low)]


def _extract_tv_id(url: str) -> str:
    """Extract TV script ID from URL like /script/ABC123-some-slug/."""
    m = re.search(r"/script/([a-zA-Z0-9]+)(?:-[a-zA-Z0-9_-]*)?/", url)
    return m.group(1) if m else ""


def _slug_to_name_hint(url: str) -> str:
    """Convert URL slug to a readable name hint."""
    m = re.search(r"/script/[a-zA-Z0-9]+-(.+)/", url)
    if m:
        return m.group(1).replace("-", " ").replace("_", " ").title()
    return ""


def fetch_script_metadata(url: str, fetch_detail: bool = True) -> Optional[dict]:
    """
    Fetch metadata for a single TV script page.
    If fetch_detail=False, derive metadata from the URL slug only (no HTTP request).
    """
    today = date.today().isoformat()
    tv_id = _extract_tv_id(url)

    if not fetch_detail:
        # Slug-only mode: derive name from URL, minimal metadata
        slug_name = _slug_to_name_hint(url)
        combined = slug_name
        return {
            "tv_id": tv_id,
            "name": slug_name,
            "description": "",
            "tags": [],
            "script_type": "strategy" if "strategy" in slug_name.lower() else "indicator",
            "asset_class": _guess_asset_class(combined),
            "strategy_type_guess": _guess_strategy_type(combined),
            "holding_period_guess": _guess_holding_period(combined),
            "signals_used": _extract_signals(combined),
            "author": "",
            "likes": 0,
            "source_url": url,
            "discovery_method": "slug-only",
            "fetched_at": today,
        }

    html = _get_html(url)
    if html is None:
        return None

    title = _parse_og(html, "title")
    description = _parse_og(html, "description")[:600]
    script_type = _parse_script_type_from_title(title)

    # Strip " — Indicator by X" / " — Strategy by X" suffix for clean name
    name = re.sub(r"\s*[—–-]\s*(Indicator|Strategy|Study|Library)\s+by\s+.+$", "", title, flags=re.IGNORECASE).strip()
    author_m = re.search(r"(?:Indicator|Strategy|Study)\s+by\s+(.+)$", title, re.IGNORECASE)
    author = author_m.group(1).strip() if author_m else ""

    combined = f"{name} {description}"

    return {
        "tv_id": tv_id,
        "name": name or _slug_to_name_hint(url),
        "description": description,
        "tags": [],  # TV doesn't expose tags in og: meta; derived from text
        "script_type": script_type,
        "asset_class": _guess_asset_class(combined),
        "strategy_type_guess": _guess_strategy_type(combined),
        "holding_period_guess": _guess_holding_period(combined),
        "signals_used": _extract_signals(combined),
        "author": author,
        "likes": 0,  # Not exposed in static HTML; would require JS rendering
        "source_url": url,
        "discovery_method": "og-meta-scrape",
        "fetched_at": today,
    }


# ---------------------------------------------------------------------------
# Acquisition-time filters
# ---------------------------------------------------------------------------

def _passes_acquisition_filter(item: dict) -> bool:
    """Return True if item passes acquisition-time relevance filters."""
    name = (item.get("name") or "").lower()
    description = (item.get("description") or "").lower()
    combined = f"{name} {description}"

    # Must contain at least one relevance keyword
    if not any(kw in combined for kw in RELEVANCE_KEYWORDS):
        return False

    # Script type must be guessable (both strategy and indicator accepted)
    if item.get("script_type") not in {"strategy", "indicator"}:
        return False

    return True


def apply_acquisition_filters(items: list[dict]) -> list[dict]:
    """Apply acquisition filters; log counts."""
    kept, dropped = [], 0
    for item in items:
        if _passes_acquisition_filter(item):
            kept.append(item)
        else:
            dropped += 1
    log.info("Acquisition filter: kept %d, dropped %d", len(kept), dropped)
    return kept


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TradingView strategy discovery — Phase 1")
    parser.add_argument(
        "--date", default=date.today().isoformat(),
        help="Output date label (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--pages", type=int, default=4,
        help="Number of paginated browse pages to include (default: 4).",
    )
    parser.add_argument(
        "--no-detail", action="store_true",
        help="Skip individual script page visits — use URL slug only (faster).",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{args.date}.json"

    log.info("=== TradingView Idea Discovery — Phase 1 ===")
    log.info("Output: %s", output_path)

    # Build list of browse pages
    browse_urls = list(BROWSE_PAGES)
    browse_urls.extend(PAGINATED_PAGES[: args.pages])

    # Step 1: collect script links
    log.info("--- Step 1: Collecting script links ---")
    script_urls = collect_script_links(browse_urls)

    if not script_urls:
        log.error("No script links found. Check network connectivity or TV page structure.")
        raise SystemExit(1)

    # Step 2: fetch metadata for each script
    log.info("--- Step 2: Fetching script metadata (%d pages) ---", len(script_urls))
    items: list[dict] = []
    seen_ids: set[str] = set()

    for i, url in enumerate(script_urls, 1):
        log.debug("[%d/%d] %s", i, len(script_urls), url)
        item = fetch_script_metadata(url, fetch_detail=not args.no_detail)
        if item is None:
            continue

        # Deduplicate by tv_id
        uid = item.get("tv_id") or item.get("source_url")
        if uid in seen_ids:
            continue
        seen_ids.add(uid)
        items.append(item)

        if not args.no_detail:
            time.sleep(REQUEST_DELAY)

    log.info("Metadata fetched: %d items", len(items))

    # Step 3: acquisition filters
    items = apply_acquisition_filters(items)

    # Step 4: sort (strategies first, then by name)
    items.sort(key=lambda x: (0 if x.get("script_type") == "strategy" else 1, x.get("name", "")))

    log.info("Final acquisition output: %d items", len(items))

    with open(output_path, "w") as f:
        json.dump(items, f, indent=2)

    log.info("Written to %s", output_path)

    if len(items) == 0:
        log.warning(
            "Zero items acquired. Try running with --no-detail to use slug-based discovery, "
            "or check that TV pages are accessible."
        )
    elif len(items) < 3:
        log.warning(
            "Fewer than 3 items acquired. Consider increasing --pages to scrape more browse pages."
        )
    else:
        log.info("SUCCESS: %d items ready for Phase 2 filtering", len(items))


if __name__ == "__main__":
    main()
