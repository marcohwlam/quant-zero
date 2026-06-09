"""
Docker HEALTHCHECK script.

The engine writes execution_engine/data/healthcheck.ts on every tick.
This script exits 0 if that file was written within STALE_MINUTES, else exits 1.

Used as: CMD python execution_engine/healthcheck.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HEALTHCHECK_FILE = REPO_ROOT / "execution_engine" / "data" / "healthcheck.ts"
STALE_MINUTES = 30


def main() -> None:
    if not HEALTHCHECK_FILE.exists():
        print("UNHEALTHY: healthcheck.ts missing (engine never ticked)")
        sys.exit(1)

    raw = HEALTHCHECK_FILE.read_text().strip()
    try:
        last = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"UNHEALTHY: unparseable timestamp: {raw!r}")
        sys.exit(1)

    age = (datetime.now(timezone.utc) - last).total_seconds() / 60
    if age > STALE_MINUTES:
        print(f"UNHEALTHY: last tick {age:.1f} min ago (threshold {STALE_MINUTES} min)")
        sys.exit(1)

    print(f"HEALTHY: last tick {age:.1f} min ago")
    sys.exit(0)


if __name__ == "__main__":
    main()
