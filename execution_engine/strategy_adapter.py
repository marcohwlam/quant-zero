"""
LiveStrategy: abstract base class for all live execution strategies.

on_bar() is the only required method. Returns target notionals in dollars.
The engine calls on_bar() when a new bar arrives for the strategy's universe.
"""

from abc import ABC, abstractmethod


class LiveStrategy(ABC):
    """
    Base class for live trading strategies in the execution engine.

    Subclasses implement on_bar() to process new bar data and return
    target position sizes in dollars for each symbol in the universe.

    Target semantics:
      positive  → long that many dollars
      zero      → flat (no position)
      negative  → short that many dollars (if strategy supports shorting)
    """

    strategy_id: str        # unique identifier matching sleeve.json
    universe: list          # symbols in yfinance format, e.g. ["BTC-USD"]
    bar_frequency: str      # "1d" or "1m"

    @abstractmethod
    def on_bar(self, bars: dict) -> dict:
        """
        Process incoming bar(s) and return target notionals.

        Args:
            bars: {symbol: {ts, open, high, low, close, volume}}
                  Only symbols with a new bar are included.

        Returns:
            {symbol: target_notional_dollars}
        """
        ...

    def on_startup(self, current_positions: dict) -> None:
        """
        Called once on engine startup with current broker positions.
        Override to reconcile strategy-internal state with broker reality.

        Args:
            current_positions: {symbol: {"qty": float, "market_value": float}}
        """
