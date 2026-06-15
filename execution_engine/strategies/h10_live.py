"""
H10 Live Strategy: Crypto EQL/EQH Reversal — execution engine adapter.
Gate 1 PASS. Paper trading approved.

Uses the replay-to-present approach: on each daily bar, downloads the last
TRAILING_DAYS of OHLCV and replays the H10 backtest simulation to determine
the desired position. If the simulation ends with an open trade
(exit_reason == "end_of_data"), we are currently in that position.

This is the same approach used by h10_paper_runner.get_current_signal() and
ensures the live strategy stays aligned with the backtest logic.

QUA-151 slippage measurement runs on top of this strategy via the execution engine.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from execution_engine.strategy_adapter import LiveStrategy

logger = logging.getLogger(__name__)

STRATEGY_ID = "h10_crypto_eql_reversal_v2"
UNIVERSE = ["BTC-USD", "ETH-USD"]
TRAILING_DAYS = 90      # rolling backtest window


class H10LiveStrategy(LiveStrategy):
    """
    H10 Crypto EQL/EQH Reversal — live execution adapter.

    Signal interpretation:
      - exit_reason == "end_of_data" on last simulated trade → still in position
      - Otherwise → flat

    Targets:
      - Long signal:  position_size_pct * asset_capital_allocated
      - Flat signal:  0
      - Short signal: -(position_size_pct * asset_capital_allocated)
    """

    strategy_id = STRATEGY_ID
    universe = UNIVERSE
    bar_frequency = "1d"

    def __init__(self, params: Optional[dict] = None) -> None:
        from strategies.h10_crypto_eql_reversal import PARAMETERS
        self._params = {**PARAMETERS, **(params or {})}
        self._capital_allocated: float = 5000.0  # overridden by engine from sleeve.json
        # Last computed targets — returned on simulation errors to avoid abrupt flips
        self._last_targets: dict = {sym: 0.0 for sym in UNIVERSE}

    def on_startup(self, current_positions: dict) -> None:
        for sym, pos in current_positions.items():
            logger.info(
                "H10 startup position: %s qty=%.6f mv=$%.2f",
                sym, pos.get("qty", 0), pos.get("market_value", 0),
            )

    def on_bar(self, bars: dict) -> dict:
        """
        Process new daily bar(s). Returns {symbol: target_notional_dollars}.
        Replays H10 backtest over the last TRAILING_DAYS to get current signal.
        """
        import pandas as pd

        bar_ts = next(iter(bars.values()))["ts"]
        try:
            end_date = pd.Timestamp(bar_ts[:10]).strftime("%Y-%m-%d")
        except Exception:
            from datetime import datetime
            end_date = datetime.utcnow().strftime("%Y-%m-%d")

        start_date = (
            pd.Timestamp(end_date) - pd.DateOffset(days=TRAILING_DAYS)
        ).strftime("%Y-%m-%d")

        try:
            targets = self._compute_targets(start_date, end_date)
            self._last_targets = targets
            return targets
        except Exception as exc:
            logger.error(
                "H10 signal computation failed (%s → %s): %s",
                start_date, end_date, exc, exc_info=True,
            )
            # Return last known targets to avoid flipping positions on transient errors
            return dict(self._last_targets)

    def _compute_targets(self, start_date: str, end_date: str) -> dict:
        """
        Run the H10 backtest simulation over [start_date, end_date] and
        extract target notionals for each symbol.
        """
        import pandas as pd
        from strategies.h10_crypto_eql_reversal import (
            download_crypto_ohlcv,
            compute_btc_regime,
            simulate_trades_single_asset,
        )

        params = self._params
        universe = params.get("universe", UNIVERSE)
        pos_size_pct = params.get("position_size_pct", 0.10)

        # Warm up the simulation with extra history for indicator convergence
        warmup_start = (
            pd.Timestamp(start_date) - pd.DateOffset(days=60)
        ).strftime("%Y-%m-%d")
        ohlcv_dict = download_crypto_ohlcv(universe, warmup_start, end_date)

        btc_ohlcv = ohlcv_dict.get("BTC-USD", pd.DataFrame())
        if btc_ohlcv.empty:
            raise ValueError("No BTC-USD data — cannot compute regime gate")

        btc_regime = compute_btc_regime(btc_ohlcv["Close"], params)

        capital_map = {
            "BTC-USD": self._capital_allocated * params.get("capital_split_btc", 0.60),
            "ETH-USD": self._capital_allocated * params.get("capital_split_eth", 0.40),
        }

        targets = {}
        for symbol in universe:
            ohlcv = ohlcv_dict.get(symbol)
            if ohlcv is None or ohlcv.empty:
                logger.warning("H10: no data for %s — setting target=0", symbol)
                targets[symbol] = 0.0
                continue

            bt_start = pd.Timestamp(start_date)
            if ohlcv.loc[ohlcv.index >= bt_start].empty:
                targets[symbol] = 0.0
                continue

            # Pass full ohlcv (warmup + backtest) so ATR/swing indicators are pre-warmed.
            warmup_count = int((ohlcv.index < bt_start).sum())
            asset_cash = capital_map.get(symbol, self._capital_allocated / len(universe))
            trades, _ = simulate_trades_single_asset(
                ohlcv, btc_regime, params, asset_cash, is_btc=("BTC" in symbol),
                warmup_bars=warmup_count,
            )
            trades = [t for t in trades if t.get("entry_date", "") >= start_date]

            # Determine current position intent from the last trade
            target_notional = 0.0
            signal_type = "flat"

            if trades:
                last = trades[-1]
                if last.get("exit_reason") == "end_of_data":
                    direction = last.get("direction", "long")
                    signal_type = direction
                    sign = 1 if direction == "long" else -1
                    target_notional = sign * pos_size_pct * asset_cash

            targets[symbol] = round(target_notional, 2)
            logger.info(
                "H10 %s signal: %s  target_notional=$%.2f",
                symbol, signal_type, target_notional,
            )

        return targets
