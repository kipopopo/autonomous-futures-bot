"""Canonical ICT exit evidence from completed, clock-aligned exchange candles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from autonomous_futures.execution.trade_plan import TradePlan
from autonomous_futures.feed.closed_history import ClosedHistoryReader
from autonomous_futures.feed.exchange_clock import ExchangeClock
from autonomous_futures.strategy.ict_mmxm import Candle


@dataclass(frozen=True)
class ExitObservation:
    symbol: str
    boundary_ms: int
    close: Decimal

    def invalidates(self, plan: TradePlan, first_fill_ms: int) -> bool:
        if first_fill_ms <= 0:
            raise ValueError("Invalid first-fill timestamp for exit evidence")
        if self.symbol != plan.symbol or not self.close.is_finite() or self.close <= 0:
            raise ValueError("Invalid closed-candle exit evidence")
        if self.boundary_ms <= 0 or self.boundary_ms % 60_000:
            raise ValueError("Invalid exit candle boundary")
        if plan.family != "ICT_TWINS" or self.boundary_ms <= first_fill_ms:
            return False
        # Match the frozen replay's one-minute entry-level close invalidation.
        # This is not a newly detected CISD threshold or an intrabar price tick.
        return self.close <= plan.entry if plan.side == "BUY" else self.close >= plan.entry


class CausalExitReader:
    def __init__(
        self, history: ClosedHistoryReader, clock: Callable[[], ExchangeClock | None]
    ) -> None:
        self.history, self.clock = history, clock
        self.observed: dict[str, tuple[int, tuple[Candle, ...]]] = {}

    async def read(self, plan: TradePlan, now_ms: int, first_fill_ms: int) -> ExitObservation:
        clock = self.clock()
        if clock is None:
            raise ValueError("Closed-candle exits require a measured exchange clock")
        boundary = clock.completed_boundary(now_ms, 60_000)
        cached = self.observed.get(plan.symbol)
        candles = (
            cached[1]
            if cached is not None and cached[0] == boundary
            else await self.history.read(plan.symbol, "1m", boundary)
        )
        if not candles or candles[-1].timestamp_ms != boundary - 60_000:
            raise ValueError("Exit history does not reach the verified completed boundary")
        if first_fill_ms < candles[0].timestamp_ms:
            raise ValueError("Exit history does not cover the first fill")
        self.observed[plan.symbol] = (boundary, candles)
        # Recovery must not overlook a prior invalidating close followed by a rebound.
        for candle in candles:
            observation = ExitObservation(plan.symbol, candle.timestamp_ms + 60_000, candle.close)
            if observation.invalidates(plan, first_fill_ms):
                return observation
        return ExitObservation(plan.symbol, boundary, candles[-1].close)
