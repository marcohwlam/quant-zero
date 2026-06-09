"""
PortfolioOverlay: vol-targeting and drawdown circuit-breaker.

Vol-targeting: scales down position sizes when realized volatility exceeds
the annualized target. Never levers up (scalar is clamped to [0, 1]).

Drawdown circuit-breaker: if portfolio drawdown from peak exceeds
max_portfolio_drawdown, all target notionals are zeroed until recovery.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)


class PortfolioOverlay:
    def __init__(
        self,
        max_drawdown: float = 0.15,
        vol_target: float = 0.15,
        vol_lookback: int = 20,
        trading_days_per_year: int = 252,
    ) -> None:
        self._max_drawdown = max_drawdown
        self._vol_target = vol_target
        self._vol_lookback = vol_lookback
        self._ann_factor = np.sqrt(trading_days_per_year)
        self._equity_history: list = []
        self._peak_equity: float = 0.0
        self._circuit_broken: bool = False

    def update_equity(self, portfolio_value: float) -> None:
        """Record new equity observation; update peak and circuit-breaker state."""
        self._equity_history.append(portfolio_value)
        if portfolio_value > self._peak_equity:
            self._peak_equity = portfolio_value

        if self._peak_equity > 0:
            drawdown = (portfolio_value - self._peak_equity) / self._peak_equity
            if drawdown <= -self._max_drawdown:
                if not self._circuit_broken:
                    logger.error(
                        "CIRCUIT BREAKER TRIGGERED: portfolio drawdown %.1f%% exceeds "
                        "%.1f%% limit — zeroing all targets until recovery",
                        drawdown * 100,
                        self._max_drawdown * 100,
                    )
                self._circuit_broken = True
            elif self._circuit_broken and drawdown > -self._max_drawdown * 0.5:
                logger.info(
                    "Circuit breaker reset: drawdown recovered to %.1f%%", drawdown * 100
                )
                self._circuit_broken = False

    def is_circuit_broken(self) -> bool:
        return self._circuit_broken

    def compute_vol_scalar(self, returns: list) -> float:
        """
        Vol-targeting scalar = min(1.0, vol_target / realized_vol).
        Clipped to [0, 1]: only scales down, never levers up.
        """
        if len(returns) < self._vol_lookback:
            return 1.0
        recent = np.array(returns[-self._vol_lookback:])
        realized_vol = float(np.std(recent) * self._ann_factor)
        if realized_vol <= 0:
            return 1.0
        return min(1.0, self._vol_target / realized_vol)

    def size_targets(self, raw_targets: dict, returns: list) -> dict:
        """
        Apply vol-targeting scalar to raw strategy targets.

        Args:
            raw_targets: {symbol: target_notional_dollars}
            returns: recent daily portfolio returns (for vol estimation)

        Returns:
            scaled targets with circuit-breaker applied
        """
        if self._circuit_broken:
            logger.warning("Circuit breaker active — zeroing all targets")
            return {sym: 0.0 for sym in raw_targets}

        scalar = self.compute_vol_scalar(returns)
        if scalar < 0.99:
            logger.info("Vol-target scalar: %.3f", scalar)

        return {sym: notional * scalar for sym, notional in raw_targets.items()}
