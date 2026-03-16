#!/usr/bin/env python3
"""
TradingView Relevance Filter — Phase 2 (QUA-108 / QUA-115)

Reads the raw acquisition output from tv_idea_discovery.py and applies
firm-specific relevance criteria to produce a curated set of strategy ideas.

Input:  research/findings/tv_ideas/YYYY-MM-DD.json          (from Phase 1)
Output: research/findings/tv_ideas/YYYY-MM-DD_filtered.json  (Phase 2 result)

Filters applied (in order):
  1. PDT compatibility: exclude intraday unless explicitly marked swing
  2. Capital requirement: flag strategies requiring > $25K minimum lot
  3. Asset class: keep equities (US stocks/ETFs) and crypto only
  4. Edge type: must map to one of approved edge types
  5. Novelty: skip ideas structurally identical to H01–H08
  6. Duplicate guard: skip TV IDs already processed in archive
  7. Indicator handling: indicators accepted if usable as component signal

Usage:
    python tv_relevance_filter.py                    # filter today's raw file
    python tv_relevance_filter.py --date 2026-03-16  # filter specific date
    python tv_relevance_filter.py --raw path/to/raw.json --out path/to/out.json
"""

import argparse
import json
import logging
import re
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
TV_IDEAS_DIR = REPO_ROOT / "research" / "findings" / "tv_ideas"
HYPOTHESES_DIR = REPO_ROOT / "research" / "hypotheses"

APPROVED_EDGE_TYPES = {
    "momentum",
    "mean_reversion",
    "breakout",
    "volatility",
    "pairs",
}

# Asset classes allowed through
ALLOWED_ASSET_CLASSES = {"equities", "crypto"}

# Structural fingerprints of H01–H08 (signals + strategy type pairs).
# An incoming idea is flagged as a structural duplicate if it matches any fingerprint.
EXISTING_HYPOTHESIS_FINGERPRINTS = [
    {"strategy_type": "momentum", "signals": {"EMA", "SMA"}},       # H01: dual MA crossover
    {"strategy_type": "mean_reversion", "signals": {"Bollinger Bands"}},  # H02: Bollinger Band MR
    {"strategy_type": "mean_reversion", "signals": {"RSI"}},         # H06: RSI short-term reversal
    {"strategy_type": "momentum", "signals": {"RSI"}},               # H05: momentum vol-scaled
    {"strategy_type": "pairs", "signals": set()},                    # H04: pairs trading
    {"strategy_type": "momentum", "signals": set()},                 # H07: multi-asset TSMOM
    {"strategy_type": "momentum", "signals": {"EMA"}},               # H08: crypto EMA crossover
]

# TV IDs already processed in prior runs (loaded dynamically from archive)
_PROCESSED_TV_IDS: set[str] = set()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Archive loader
# ---------------------------------------------------------------------------

def load_processed_ids() -> set[str]:
    """Load all TV IDs from previously generated *_filtered.json files."""
    processed: set[str] = set()
    for path in TV_IDEAS_DIR.glob("*_filtered.json"):
        try:
            with open(path) as f:
                items = json.load(f)
            for item in items:
                tv_id = item.get("tv_id") or ""
                if tv_id:
                    processed.add(tv_id)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read archive file %s: %s", path, exc)
    log.info("Loaded %d previously processed TV IDs from archive", len(processed))
    return processed


# ---------------------------------------------------------------------------
# Filter functions
# ---------------------------------------------------------------------------

def filter_pdt_compatibility(item: dict) -> tuple[bool, str]:
    """
    Exclude intraday strategies (PDT compliance).
    Intraday scripts require >= 4 round-trips/week → PDT violation risk.
    Exception: if explicitly described as 'swing' despite intraday signals.
    """
    hp = item.get("holding_period_guess", "swing")
    desc = (item.get("description") or "").lower()
    name = (item.get("name") or "").lower()
    combined = f"{hp} {desc} {name}"

    if hp == "intraday":
        # Allow through if explicitly labelled as swing elsewhere in the text
        if "swing" in combined:
            return True, ""
        return False, "intraday_pdt_risk"
    return True, ""


def filter_capital_requirement(item: dict) -> tuple[bool, dict]:
    """
    Flag (but do not exclude) strategies that may require > $25K minimum lot.
    Returns (pass=True always, flags dict).
    """
    desc = (item.get("description") or "").lower()
    flags: dict = {}
    # Keywords suggesting large capital requirements
    high_capital_kw = ["futures", "options", "margin", "leveraged", "100k", "50k", "500k"]
    if any(kw in desc for kw in high_capital_kw):
        flags["capital_flag"] = "may_require_over_25k — manual review required"
    return True, flags


def filter_asset_class(item: dict) -> tuple[bool, str]:
    """
    Keep only equities (US stocks/ETFs) and crypto.
    Exclude forex, futures, commodities, bonds.
    """
    asset_class = item.get("asset_class", "equities")
    desc = (item.get("description") or "").lower()
    name = (item.get("name") or "").lower()
    combined = f"{desc} {name}"

    # Explicit exclusion keywords
    excluded_kw = ["forex", "fx ", "currency pair", "futures", "commodity", "bond", "treasury"]
    if any(kw in combined for kw in excluded_kw):
        return False, "excluded_asset_class"

    if asset_class not in ALLOWED_ASSET_CLASSES:
        return False, f"asset_class_{asset_class}_not_allowed"

    return True, ""


def filter_edge_type(item: dict) -> tuple[bool, str]:
    """
    Strategy type must map to one of the approved edge types.
    """
    edge = item.get("strategy_type_guess", "unknown")
    if edge == "unknown":
        # Last-chance: try to derive from name/description
        combined = (f"{item.get('name','')} {item.get('description','')}").lower()
        if "momentum" in combined or "trend" in combined:
            item["strategy_type_guess"] = "momentum"
            edge = "momentum"
        elif "revers" in combined or "mean" in combined:
            item["strategy_type_guess"] = "mean_reversion"
            edge = "mean_reversion"
        elif "breakout" in combined:
            item["strategy_type_guess"] = "breakout"
            edge = "breakout"
        elif "volatil" in combined:
            item["strategy_type_guess"] = "volatility"
            edge = "volatility"
        elif "pairs" in combined or "spread" in combined or "cointegr" in combined:
            item["strategy_type_guess"] = "pairs"
            edge = "pairs"

    if edge not in APPROVED_EDGE_TYPES:
        return False, f"edge_type_{edge}_not_in_approved_set"

    return True, ""


def filter_novelty(item: dict) -> tuple[bool, str]:
    """
    Skip ideas structurally identical to H01–H08.
    A structural match requires BOTH strategy_type AND signals to overlap.
    """
    item_type = item.get("strategy_type_guess", "")
    item_signals = set(item.get("signals_used", []))

    for fp in EXISTING_HYPOTHESIS_FINGERPRINTS:
        type_match = fp["strategy_type"] == item_type
        signal_overlap = fp["signals"] and (fp["signals"] & item_signals == fp["signals"])
        # Only flag as duplicate if type matches AND all fingerprint signals overlap
        if type_match and signal_overlap and fp["signals"]:
            return False, f"structural_duplicate_of_h01_h08 (type={item_type}, signals={fp['signals']})"

    return True, ""


def filter_duplicate_guard(item: dict, processed_ids: set[str]) -> tuple[bool, str]:
    """
    Skip TV IDs already processed in prior weekly runs.
    """
    tv_id = item.get("tv_id") or ""
    if tv_id and tv_id in processed_ids:
        return False, "already_processed_in_prior_run"
    return True, ""


def filter_indicator_handling(item: dict) -> tuple[bool, dict]:
    """
    Indicator scripts are accepted only if they can serve as a component signal
    with plausible IC > 0.02. Pass all indicators but flag them for IC estimation.
    Strategies are always allowed through this filter.
    """
    flags: dict = {}
    if item.get("script_type") == "indicator":
        flags["indicator_note"] = (
            "Indicator script: accepted as candidate component signal. "
            "IC > 0.02 must be confirmed before use in multi-signal strategy."
        )
    return True, flags


# ---------------------------------------------------------------------------
# Main filter pipeline
# ---------------------------------------------------------------------------

def apply_filters(raw_items: list[dict], processed_ids: set[str]) -> list[dict]:
    """Run all filters; return items that pass with added filter metadata."""
    passed: list[dict] = []
    stats = {
        "total": len(raw_items),
        "pdt": 0,
        "asset_class": 0,
        "edge_type": 0,
        "novelty": 0,
        "duplicate": 0,
        "passed": 0,
    }

    for item in raw_items:
        # Make a copy so we can annotate with filter results
        item = dict(item)
        flags: dict = {}

        # 1. PDT compatibility
        ok, reason = filter_pdt_compatibility(item)
        if not ok:
            stats["pdt"] += 1
            log.debug("DROP [pdt] %s — %s", item.get("name"), reason)
            continue

        # 2. Capital requirement (flagging only, never drops)
        _, cap_flags = filter_capital_requirement(item)
        flags.update(cap_flags)

        # 3. Asset class
        ok, reason = filter_asset_class(item)
        if not ok:
            stats["asset_class"] += 1
            log.debug("DROP [asset] %s — %s", item.get("name"), reason)
            continue

        # 4. Edge type
        ok, reason = filter_edge_type(item)
        if not ok:
            stats["edge_type"] += 1
            log.debug("DROP [edge] %s — %s", item.get("name"), reason)
            continue

        # 5. Novelty check
        ok, reason = filter_novelty(item)
        if not ok:
            stats["novelty"] += 1
            log.debug("DROP [novelty] %s — %s", item.get("name"), reason)
            continue

        # 6. Duplicate guard
        ok, reason = filter_duplicate_guard(item, processed_ids)
        if not ok:
            stats["duplicate"] += 1
            log.debug("DROP [dup] %s — %s", item.get("name"), reason)
            continue

        # 7. Indicator handling (flagging only)
        _, ind_flags = filter_indicator_handling(item)
        flags.update(ind_flags)

        item["filter_flags"] = flags
        passed.append(item)
        stats["passed"] += 1

    stats["dropped"] = stats["total"] - stats["passed"]
    log.info("Filter stats: %s", stats)
    return passed


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def rank_results(items: list[dict]) -> list[dict]:
    """
    Rank filtered items for Research Director review.
    Scoring:
      - strategy > indicator (+2)
      - higher likes (+1 per 100 likes, capped at 5)
      - non-crypto equities (+1, to balance crypto-heavy acquisition)
      - novel edge type not in H01–H08 pool (+1 bonus: volatility, pairs, breakout)
    """
    def score(item: dict) -> float:
        s = 0.0
        s += 2.0 if item.get("script_type") == "strategy" else 0.0
        s += min(5.0, item.get("likes", 0) / 100.0)
        s += 1.0 if item.get("asset_class") == "equities" else 0.0
        edge = item.get("strategy_type_guess", "")
        s += 1.0 if edge in {"volatility", "pairs", "breakout"} else 0.0
        return s

    return sorted(items, key=score, reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TradingView relevance filter — Phase 2")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Date label for raw input / filtered output (YYYY-MM-DD). Default: today.")
    parser.add_argument("--raw", type=Path, default=None,
                        help="Path to raw JSON file (overrides --date for input).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Path for filtered output JSON (overrides --date for output).")
    args = parser.parse_args()

    # Resolve paths
    raw_path = args.raw or (TV_IDEAS_DIR / f"{args.date}.json")
    out_path = args.out or (TV_IDEAS_DIR / f"{args.date}_filtered.json")

    log.info("=== TradingView Relevance Filter — Phase 2 ===")
    log.info("Input:  %s", raw_path)
    log.info("Output: %s", out_path)

    if not raw_path.exists():
        log.error("Raw input file not found: %s", raw_path)
        log.error("Run tv_idea_discovery.py first to generate the raw acquisition file.")
        raise SystemExit(1)

    with open(raw_path) as f:
        raw_items = json.load(f)

    log.info("Loaded %d raw items from acquisition", len(raw_items))

    # Load archive of already-processed TV IDs
    processed_ids = load_processed_ids()

    # Run filter pipeline
    filtered = apply_filters(raw_items, processed_ids)

    # Rank results
    filtered = rank_results(filtered)

    log.info("Filtered result: %d items (target: 3+ for weekly synthesis)", len(filtered))

    if len(filtered) < 3:
        log.warning(
            "Fewer than 3 items passed all filters. "
            "Consider relaxing novelty criteria, increasing scraping pages, "
            "or adjusting minimum likes threshold in tv_idea_discovery.py."
        )

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(filtered, f, indent=2)

    log.info("Written to %s", out_path)

    # Print summary for Research Director review
    print("\n=== Filtered Results Summary ===")
    print(f"Date: {args.date}")
    print(f"Raw items acquired: {len(raw_items)}")
    print(f"Items passing all filters: {len(filtered)}")
    print(f"Output: {out_path}")
    print()
    if filtered:
        print("Top candidates for hypothesis synthesis:")
        for i, item in enumerate(filtered[:10], 1):
            flags_str = ""
            for k, v in item.get("filter_flags", {}).items():
                flags_str += f"\n     [{k}] {v}"
            print(
                f"  {i}. [{item.get('script_type','?').upper()}] {item.get('name','?')} "
                f"({item.get('strategy_type_guess','?')}, {item.get('asset_class','?')}, "
                f"likes={item.get('likes',0)})"
                f"{flags_str}"
            )
    else:
        print("  No items passed filters — check logs for drop reasons.")


if __name__ == "__main__":
    main()
