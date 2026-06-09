"""
ExecutionEngine: always-on main loop for the strategy sleeve.

Architecture:
  - Loads N LiveStrategy objects defined in sleeve.json
  - Polls BarFeed for new daily bars every `daily_poll_seconds`
  - On new bar: strategy.on_bar() → raw targets → PortfolioOverlay → OrderManager
  - Watchdog thread checks liveness on every tick
  - All state (orders, bar timestamps, equity) persisted to SQLite
  - Decoupled from Paperclip: never calls Paperclip API; writes alert files instead

Startup: reconciles broker positions/orders → no double-submit across restarts.
"""

import importlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .bar_feed import BarFeed, to_alpaca_symbol
from .config import EngineConfig, StrategyConfig
from .order_manager import OrderManager
from .portfolio import PortfolioOverlay
from .store import ExecutionStore
from .watchdog import Watchdog

logger = logging.getLogger(__name__)


def _load_strategy(cfg: StrategyConfig):
    """Dynamically import and instantiate a strategy class from sleeve.json config."""
    module = importlib.import_module(cfg.module)
    cls = getattr(module, cfg.class_name)
    instance = cls(params=cfg.params)
    # Inject capital from sleeve config so strategy can compute target notionals
    if hasattr(instance, "_capital_allocated"):
        instance._capital_allocated = cfg.capital_allocated
    return instance


class ExecutionEngine:
    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._running = False

        self._store = ExecutionStore(config.db_path)
        self._bar_feed = BarFeed(
            api_key=config.alpaca_api_key,
            api_secret=config.alpaca_api_secret,
            data_url=config.alpaca_data_url,
        )
        self._portfolio = PortfolioOverlay(
            max_drawdown=config.max_portfolio_drawdown,
            vol_target=config.vol_target_annual,
        )
        self._watchdog = Watchdog(
            store=self._store,
            alert_dir=config.alert_dir,
            stale_minutes=config.watchdog_stale_minutes,
        )

        # Load strategies from sleeve config
        self._strategies = []
        self._strategy_capital: dict = {}
        for scfg in config.strategies:
            try:
                strategy = _load_strategy(scfg)
                self._strategies.append(strategy)
                self._strategy_capital[scfg.strategy_id] = scfg.capital_allocated
                logger.info(
                    "Strategy loaded: %s  capital=$%.0f  universe=%s",
                    scfg.strategy_id, scfg.capital_allocated, scfg.universe,
                )
            except Exception as exc:
                logger.error("Failed to load strategy %s: %s", scfg.strategy_id, exc, exc_info=True)

        # Alpaca client (import deferred so missing credentials don't fail at module import)
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from broker.alpaca_client import AlpacaClient
        self._alpaca = AlpacaClient()
        self._order_manager = OrderManager(self._alpaca, self._store)

        # Daily return history per strategy for vol-targeting
        self._return_history: dict = {s.strategy_id: [] for s in self._strategies}
        self._last_equity: Optional[float] = None

    # ── Startup ───────────────────────────────────────────────────────────────

    def startup(self) -> None:
        logger.info("=== ExecutionEngine startup ===")

        # Broker reconciliation: sync pending orders + fetch current positions
        broker_positions = self._order_manager.startup_reconcile()

        # Notify each strategy of current broker positions
        for strategy in self._strategies:
            strat_positions = {}
            for symbol in strategy.universe:
                alpaca_sym = to_alpaca_symbol(symbol)
                pos = broker_positions.get(alpaca_sym) or broker_positions.get(symbol)
                if pos:
                    strat_positions[symbol] = pos
            strategy.on_startup(strat_positions)

        # Seed bar feed from last processed timestamps in the store
        for strategy in self._strategies:
            for symbol in strategy.universe:
                last_ts = self._store.get_last_bar_ts(strategy.strategy_id, symbol)
                self._bar_feed.initialize_last_seen(symbol, last_ts)

        # Seed portfolio overlay with last known equity
        latest = self._store.get_latest_equity()
        if latest:
            self._portfolio.update_equity(latest["portfolio_value"])
            self._last_equity = latest["portfolio_value"]

        logger.info("Startup complete. %d strategies active.", len(self._strategies))

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Block indefinitely, ticking on daily_poll_seconds interval."""
        self.startup()
        self._running = True
        logger.info("=== ExecutionEngine running ===")

        while self._running:
            try:
                self._tick()
            except Exception as exc:
                logger.error("Tick exception: %s", exc, exc_info=True)

            self._write_healthcheck()
            time.sleep(self._config.daily_poll_seconds)

    def _tick(self) -> None:
        logger.debug("Tick @ %s UTC", datetime.utcnow().isoformat())

        # Refresh portfolio value and equity history
        portfolio_value, cash, broker_positions = self._refresh_account()

        has_crypto = any(
            any(s.endswith("-USD") for s in strat.universe)
            for strat in self._strategies
        )

        # Process each strategy
        for strategy in self._strategies:
            try:
                self._process_strategy(strategy, broker_positions, portfolio_value)
            except Exception as exc:
                logger.error(
                    "Strategy %s tick error: %s", strategy.strategy_id, exc, exc_info=True
                )

        # Watchdog liveness check
        self._watchdog.check(has_crypto=has_crypto)

    def _refresh_account(self) -> tuple:
        """Fetch portfolio value, cash, and positions from broker."""
        portfolio_value = 0.0
        cash = 0.0
        broker_positions = {}
        try:
            account = self._alpaca.get_account()
            portfolio_value = float(account.get("portfolio_value", 0))
            cash = float(account.get("cash", 0))
            self._portfolio.update_equity(portfolio_value)
            self._store.save_equity_snapshot(portfolio_value, cash)

            # Compute return for vol-targeting
            if self._last_equity and self._last_equity > 0:
                ret = (portfolio_value - self._last_equity) / self._last_equity
                for strat in self._strategies:
                    self._return_history[strat.strategy_id].append(ret)
            self._last_equity = portfolio_value

            logger.info("Portfolio value: $%.2f  cash: $%.2f", portfolio_value, cash)
        except Exception as exc:
            logger.warning("Account refresh failed: %s", exc)

        try:
            for pos in self._alpaca.get_positions():
                sym = pos.get("symbol", "")
                broker_positions[sym] = {
                    "qty": float(pos.get("qty", 0)),
                    "market_value": float(pos.get("market_value", 0)),
                    "current_price": float(pos.get("current_price", 0)),
                }
        except Exception as exc:
            logger.warning("Position fetch failed: %s", exc)

        return portfolio_value, cash, broker_positions

    def _process_strategy(self, strategy, broker_positions: dict, portfolio_value: float) -> None:
        """Fetch new bars → run strategy → size targets → submit orders."""
        new_bars = self._bar_feed.get_new_daily_bars(strategy.universe)
        fresh = {sym: bar for sym, bar in new_bars.items() if bar is not None}
        if not fresh:
            logger.debug("No new bars for %s", strategy.strategy_id)
            return

        logger.info(
            "New bars for %s: %s",
            strategy.strategy_id,
            {sym: bar["ts"] for sym, bar in fresh.items()},
        )

        # Run strategy signal
        raw_targets = strategy.on_bar(fresh)
        logger.info("Raw targets from %s: %s", strategy.strategy_id, raw_targets)

        # Apply portfolio overlay (vol-targeting + circuit-breaker)
        returns = self._return_history.get(strategy.strategy_id, [])
        sized_targets = self._portfolio.size_targets(raw_targets, returns)

        # Submit orders (idempotent)
        bar_ts = next(iter(fresh.values()))["ts"]
        for symbol, target_notional in sized_targets.items():
            alpaca_sym = to_alpaca_symbol(symbol)
            pos = broker_positions.get(alpaca_sym) or broker_positions.get(symbol) or {}
            current_qty = pos.get("qty", 0.0)
            current_price = pos.get("current_price", 0.0)
            if current_price == 0.0:
                current_price = fresh.get(symbol, {}).get("close", 1.0)

            self._order_manager.submit_target(
                strategy_id=strategy.strategy_id,
                symbol=symbol,
                target_notional=target_notional,
                current_qty=current_qty,
                current_price=current_price,
                bar_ts=bar_ts,
            )
            self._store.record_bar_heartbeat(strategy.strategy_id, symbol, bar_ts)

    # ── Healthcheck ───────────────────────────────────────────────────────────

    def _write_healthcheck(self) -> None:
        path = Path(self._config.healthcheck_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.utcnow().isoformat())

    def stop(self) -> None:
        self._running = False
        logger.info("ExecutionEngine stop requested.")
