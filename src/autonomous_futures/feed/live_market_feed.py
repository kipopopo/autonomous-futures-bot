"""Persistent Testnet market ingress with independently refreshed clock and Hawkes fit."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterable, Callable
from typing import Any

import httpx
import websockets

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.feed.exchange_clock import ExchangeClock
from autonomous_futures.feed.runtime_microstructure import RuntimeMicrostructure


class LiveMarketFeed:
    def __init__(
        self,
        gateway: BinanceFuturesGateway,
        monitor: RuntimeMicrostructure,
        *,
        on_frame: Callable[[dict[str, Any], int], None] | None = None,
    ) -> None:
        if gateway.offline_mode or not gateway.testnet:
            raise ValueError("This rollout requires an authenticated Testnet gateway")
        self.gateway, self.monitor = gateway, monitor
        self.on_frame = on_frame
        self.clock: ExchangeClock | None = None
        self.connected = False
        self._connected_channels: set[str] = set()
        self.last_error_type: str | None = None

    @property
    def market_endpoint(self) -> str:
        """Aggregate trades belong on Binance's regular market-data route."""
        streams = "/".join(f"{symbol.lower()}@aggTrade" for symbol in self.monitor.symbols)
        return f"{self.gateway.market_ws_base}/stream?streams={streams}"

    @property
    def public_endpoint(self) -> str:
        """Depth updates belong on Binance's high-frequency public-data route."""
        streams = "/".join(f"{symbol.lower()}@depth5@100ms" for symbol in self.monitor.symbols)
        return f"{self.gateway.public_ws_base}/stream?streams={streams}"

    @property
    def endpoint(self) -> str:
        """Compatibility alias for callers inspecting the regular market route."""
        return self.market_endpoint

    @property
    def market_connected(self) -> bool:
        return "market" in self._connected_channels

    @property
    def public_connected(self) -> bool:
        return "public" in self._connected_channels

    async def refresh_clock(self, client: httpx.AsyncClient) -> None:
        observations = []
        for _ in range(3):
            sent = time.time_ns() // 1_000_000
            response = await client.get("/fapi/v1/time")
            received = time.time_ns() // 1_000_000
            response.raise_for_status()
            try:
                observations.append(
                    ExchangeClock(sent, received, int(response.json()["serverTime"]))
                )
            except ValueError:
                continue
        if not observations:
            raise ValueError("No trustworthy exchange clock observation")
        chosen = min(observations, key=lambda sample: sample.uncertainty_ms)
        if self.clock is not None and abs(chosen.offset_ms - self.clock.offset_ms) > 500:
            self.monitor.disconnect()
        self.clock = chosen

    async def consume(self, stream: AsyncIterable[Any], channel: str = "market") -> None:
        if channel not in {"market", "public"}:
            raise ValueError("Unknown Binance market-data channel")
        self.monitor.disconnect()
        self._connected_channels.add(channel)
        self.connected = self._connected_channels == {"market", "public"}
        try:
            async for wire in stream:
                local_ms = time.time_ns() // 1_000_000
                if self.clock is None:
                    raise ValueError("Market ingress has no observed exchange clock")
                payload = json.loads(wire)
                aligned = self.clock.aligned_ms(local_ms)
                if self.on_frame is not None:
                    self.on_frame(payload, aligned)
                self.monitor.ingest(payload, aligned, uncertainty_ms=self.clock.uncertainty_ms)
        finally:
            self._connected_channels.discard(channel)
            self.connected = self._connected_channels == {"market", "public"}
            self.monitor.disconnect()

    async def run(self) -> None:
        """Reconnect genuine streams; disconnects always invalidate execution evidence."""

        async def calibrations() -> None:
            while True:
                if self.connected:
                    await self.monitor.calibrate()
                await asyncio.sleep(5)

        async def clocks() -> None:
            async with httpx.AsyncClient(base_url=self.gateway.rest_base, timeout=10) as client:
                while True:
                    try:
                        await self.refresh_clock(client)
                        self.last_error_type = None
                    except Exception as exc:
                        self.clock = None
                        self.monitor.disconnect()
                        self.last_error_type = type(exc).__name__
                    await asyncio.sleep(60 if self.clock is not None else 5)

        async def ingress(channel: str, endpoint: str) -> None:
            while True:
                if self.clock is None:
                    await asyncio.sleep(1)
                    continue
                try:
                    async with websockets.connect(
                        endpoint,
                        open_timeout=15,
                        close_timeout=5,
                        max_size=2**20,
                        max_queue=32,
                    ) as stream:
                        await self.consume(stream, channel)
                except Exception as exc:
                    self.connected = False
                    self.monitor.disconnect()
                    self.last_error_type = type(exc).__name__
                await asyncio.sleep(2)

        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(clocks())
                group.create_task(ingress("market", self.market_endpoint))
                group.create_task(ingress("public", self.public_endpoint))
                group.create_task(calibrations())
        finally:
            self.connected = False
            self._connected_channels.clear()
            self.monitor.disconnect()
