"""
migrate_add_timeseries.py
Schema migration: add equity_curve and trade_log fields to existing backtest JSON files.

Since historical Portfolio objects are no longer available, we inject empty arrays
as placeholder fields. Future backtest runs will populate these with real data.

Usage:
    python backtests/migrate_add_timeseries.py [--dry-run]
"""

import json
import sys
from pathlib import Path

_BACKTESTS_DIR = Path(__file__).parent


def migrate(dry_run: bool = False) -> None:
    json_files = sorted(_BACKTESTS_DIR.glob("*.json"))
    # Exclude this script's own output directory and the migration script itself
    json_files = [f for f in json_files if not f.name.startswith("migrate_")]

    updated = 0
    skipped = 0

    for path in json_files:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [SKIP]  {path.name}: could not parse — {e}")
            skipped += 1
            continue

        needs_update = "equity_curve" not in data or "trade_log" not in data
        if not needs_update:
            print(f"  [OK]    {path.name}: already has equity_curve + trade_log")
            skipped += 1
            continue

        data.setdefault("equity_curve", [])
        data.setdefault("trade_log", [])

        if dry_run:
            print(f"  [DRY]   {path.name}: would add missing fields")
        else:
            path.write_text(json.dumps(data, indent=2))
            print(f"  [FIXED] {path.name}: added equity_curve + trade_log (empty placeholders)")
        updated += 1

    print(f"\nDone. {updated} files updated, {skipped} files skipped.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no files will be modified.\n")
    migrate(dry_run=dry_run)
