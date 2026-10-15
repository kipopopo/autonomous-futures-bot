"""Read contiguous completed exchange candles for causal runtime strategy decisions."""

from __future__ import annotations

from typing import Any

from autonomous_futures.execution.account_evidence import finite_decimal
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.strategy.ict_mmxm import Candle

WIDTH_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def parse_closed_history(
    rows: list[list[Any]], interval: str, decision_ms: int, *, minimum: int = 250
) -> tuple[Candle, ...]:
    width = WIDTH_MS[interval]
    boundary = decision_ms // width * width
    candles: list[Candle] = []
    for row in rows:
        opened, closed = int(row[0]), int(row[6])
        if opened <= 0 or opened % width or closed != opened + width - 1:
            raise ValueError("Exchange candle has invalid interval boundaries")
        if closed >= boundary:
            continue  # Never expose the currently forming candle to strategy code.
        prices = [finite_decimal(value) for value in row[1:5]]
        volume = finite_decimal(row[5])
        o, h, low, c = prices
        if min(prices) <= 0 or volume < 0 or not low <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Exchange candle has invalid price/volume geometry")
        if candles and opened != candles[-1].timestamp_ms + width:
            raise ValueError("Closed exchange history has gaps, duplicates or reordered bars")
        candles.append(Candle(opened, o, h, low, c, volume))
    if len(candles) < minimum or candles[-1].timestamp_ms != boundary - width:
        raise ValueError("Closed exchange history is incomplete or stale")
    return tuple(candles)


class ClosedHistoryReader:
    def __init__(self, gateway: BinanceFuturesGateway) -> None:
        if gateway.offline_mode:
            raise ValueError("Runtime histories require observed exchange candles")
        self.gateway = gateway
        self._cache: dict[tuple[str, str], tuple[int, tuple[Candle, ...]]] = {}

    async def read(self, symbol: str, interval: str, decision_ms: int) -> tuple[Candle, ...]:
        if interval not in WIDTH_MS:
            raise ValueError("Unsupported canonical runtime timeframe")
        width = WIDTH_MS[interval]
        boundary = decision_ms // width * width
        cache_key = (symbol.upper(), interval)
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] == boundary:
            return cached[1]
        rows = await self.gateway.get_klines(symbol, interval, limit=251, end_time=decision_ms - 1)
        parsed = parse_closed_history(rows, interval, decision_ms)[-250:]
        self._cache[cache_key] = (boundary, parsed)
        return parsed
