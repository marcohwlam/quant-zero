"""
Watchdog: monitors execution engine liveness.

During market hours (and always for crypto strategies), checks whether the
engine has processed a bar within the stale threshold. If not, emits a
JSON alert file to alert_dir for the Portfolio Monitor agent to pick up.

Alert files are the only output — the service does NOT depend on Paperclip
being reachable to emit alerts.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def _in_us_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    open_ = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_ <= now <= close


class Watchdog:
    def __init__(self, store, alert_dir: str, stale_minutes: int = 15) -> None:
        self._store = store
        self._alert_dir = Path(alert_dir)
        self._stale_minutes = stale_minutes
        self._alert_dir.mkdir(parents=True, exist_ok=True)
        self._alerted: bool = False

    def check(self, has_crypto: bool = False) -> bool:
        """
        Assess liveness. Returns True if healthy, False if stale.

        has_crypto=True means crypto strategies are loaded — check 24/7 since
        crypto trades around the clock. Without crypto, only check during US
        equity market hours.
        """
        if not has_crypto and not _in_us_market_hours():
            return True

        last_processed = self._store.get_last_processed_at()
        if last_processed is None:
            return True  # Engine just started; no bars expected yet

        try:
            last_dt = datetime.fromisoformat(last_processed.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60

            if age_minutes > self._stale_minutes:
                if not self._alerted:
                    self._emit_alert(age_minutes)
                    self._alerted = True
                return False

            if self._alerted:
                logger.info("Watchdog: liveness restored (last bar %.1f min ago)", age_minutes)
                self._alerted = False
            return True

        except Exception as exc:
            logger.warning("Watchdog check error: %s", exc)
            return True

    def _emit_alert(self, age_minutes: float) -> None:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        alert = {
            "type": "execution_engine_stale",
            "severity": "high",
            "message": (
                f"Execution engine has not processed a bar in {age_minutes:.1f} minutes "
                f"(threshold: {self._stale_minutes} min)"
            ),
            "emitted_at": datetime.utcnow().isoformat(),
            "stale_minutes": round(age_minutes, 1),
            "threshold_minutes": self._stale_minutes,
            "action": (
                "Check execution-engine container health, Alpaca data feed connectivity, "
                "and broker/alpaca_client.py credentials."
            ),
        }
        path = self._alert_dir / f"execution_stale_{ts}.json"
        with open(path, "w") as f:
            json.dump(alert, f, indent=2)
        logger.error(
            "WATCHDOG ALERT emitted (%.1f min stale) → %s", age_minutes, path
        )
