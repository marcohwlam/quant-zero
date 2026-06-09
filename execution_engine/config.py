"""
EngineConfig: configuration for the paper-trade execution service.
Loaded from environment variables + sleeve.json.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


@dataclass
class StrategyConfig:
    strategy_id: str
    module: str         # python import path, e.g. "execution_engine.strategies.h10_live"
    class_name: str     # class within module
    capital_allocated: float  # dollars allocated to this strategy
    bar_frequency: str  # "1d" or "1m"
    universe: list      # symbols in yfinance format, e.g. ["BTC-USD", "ETH-USD"]
    params: dict = field(default_factory=dict)


@dataclass
class EngineConfig:
    # Storage paths
    db_path: str = str(REPO_ROOT / "execution_engine" / "data" / "execution.db")
    alert_dir: str = str(REPO_ROOT / "execution_engine" / "data" / "alerts")
    healthcheck_file: str = str(REPO_ROOT / "execution_engine" / "data" / "healthcheck.ts")

    # Watchdog
    watchdog_stale_minutes: int = 15    # alert if no bar processed within N minutes during trading hours
    watchdog_poll_seconds: int = 300    # check every 5 minutes

    # Bar polling intervals
    daily_poll_seconds: int = 600       # poll for new daily bars every 10 min
    minute_poll_seconds: int = 30       # poll for new minute bars every 30 sec

    # Portfolio risk overlay
    max_portfolio_drawdown: float = 0.15    # 15% peak-to-trough → pause all trading
    vol_target_annual: float = 0.15         # 15% annualized vol target for position sizing

    # Alpaca credentials + endpoints
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_data_url: str = "https://data.alpaca.markets"

    # Strategy sleeve
    strategies: list = field(default_factory=list)  # list of StrategyConfig


def load_config(sleeve_path: str | None = None) -> EngineConfig:
    cfg = EngineConfig()

    cfg.alpaca_api_key = os.environ.get("ALPACA_API_KEY", "")
    cfg.alpaca_api_secret = os.environ.get("ALPACA_API_SECRET", "")
    cfg.db_path = os.environ.get("EXECUTION_DB_PATH", cfg.db_path)
    cfg.alert_dir = os.environ.get("EXECUTION_ALERT_DIR", cfg.alert_dir)

    sleeve_path = sleeve_path or os.environ.get(
        "EXECUTION_SLEEVE_PATH",
        str(REPO_ROOT / "execution_engine" / "sleeve.json"),
    )
    if Path(sleeve_path).exists():
        with open(sleeve_path) as f:
            sleeve = json.load(f)
        cfg.strategies = [StrategyConfig(**s) for s in sleeve.get("strategies", [])]

    return cfg
