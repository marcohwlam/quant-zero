"""
Entry point for the Quant Zero Execution Engine.

Usage:
    python -m execution_engine.main
    python -m execution_engine.main --sleeve execution_engine/sleeve.json

Environment variables:
    ALPACA_API_KEY          required
    ALPACA_API_SECRET       required
    EXECUTION_DB_PATH       path for SQLite store (default: execution_engine/data/execution.db)
    EXECUTION_ALERT_DIR     path for alert files (default: execution_engine/data/alerts)
    EXECUTION_SLEEVE_PATH   path to sleeve.json (default: execution_engine/sleeve.json)
"""

import argparse
import logging
import signal
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from execution_engine.config import load_config
from execution_engine.engine import ExecutionEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Quant Zero Execution Engine")
    parser.add_argument("--sleeve", default=None, help="Path to sleeve.json config file")
    args = parser.parse_args()

    config = load_config(sleeve_path=args.sleeve)

    if not config.alpaca_api_key or not config.alpaca_api_secret:
        logger.error("ALPACA_API_KEY and ALPACA_API_SECRET must be set in environment.")
        sys.exit(1)

    if not config.strategies:
        logger.warning(
            "No strategies loaded from sleeve.json. "
            "Engine will run watchdog-only. Check EXECUTION_SLEEVE_PATH."
        )

    engine = ExecutionEngine(config)

    def _shutdown(signum, frame):
        logger.info("Signal %s — shutting down gracefully.", signum)
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info(
        "Starting execution engine with %d strategies.",
        len(config.strategies),
    )
    engine.run()


if __name__ == "__main__":
    main()
