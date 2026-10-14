"""Continuous 24/7 Self-Driving Trading Daemon Module (Phase 317 M2).

Aliases and re-exports ContinuousSelfDrivingTrader from execution module.
"""

from __future__ import annotations

from autonomous_futures.execution.continuous_trader import (
    ContinuousSelfDrivingTrader,
)
from autonomous_futures.strategy.macro_liquidity_scalper import (
    Candle,
    compute_ema,
)

__all__ = [
    "Candle",
    "ContinuousSelfDrivingTrader",
    "compute_ema",
]
