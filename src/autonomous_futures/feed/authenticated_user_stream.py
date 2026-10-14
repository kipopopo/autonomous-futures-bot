"""Authenticated Binance USDⓈ-M user events with fail-closed REST resynchronization."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import websockets

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway

USER_DATA_EVENTS = (
    "ACCOUNT_UPDATE",
    "ACCOUNT_CONFIG_UPDATE",
    "ORDER_TRADE_UPDATE",
    "ALGO_UPDATE",
    "MARGIN_CALL",
    "CONDITIONAL_ORDER_TRIGGER_REJECT",
    "listenKeyExpired",
)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]
LifecycleHandler = Callable[[], Awaitable[None]]


class AuthenticatedUserDataStream:
    """Consume private account/order events; REST remains the reconciliation authority.

    The connection only accelerates recovery. It never treats an event as a confirmed
    balance, position, fill, or protective-order state. Every new connection runs the
    supplied REST resynchronization callback before event handling resumes.
    """

    def __init__(
        self,
        gateway: BinanceFuturesGateway,
        *,
        on_event: EventHandler | None = None,
        on_reconnect: LifecycleHandler | None = None,
        on_disconnect: LifecycleHandler | None = None,
        connector: Callable[..., Any] | None = None,
        keepalive_interval_seconds: float = 1800,
        max_connection_age_seconds: float = 23 * 60 * 60,
        reconnect_delay_seconds: float = 2,
    ) -> None:
        if gateway.offline_mode:
            raise ValueError("Authenticated user stream requires a real exchange gateway")
        if not 0 < keepalive_interval_seconds < 3600:
            raise ValueError("Listen-key keepalive must occur before its 60-minute expiry")
        if not 0 < max_connection_age_seconds < 24 * 60 * 60:
            raise ValueError("WebSocket connection must renew before Binance's 24-hour limit")
        if reconnect_delay_seconds < 0:
            raise ValueError("Reconnect delay cannot be negative")
        self.gateway = gateway
        self.on_event = on_event
        self.on_reconnect = on_reconnect
        self.on_disconnect = on_disconnect
        self.connector = connector or websockets.connect
        self.keepalive_interval_seconds = keepalive_interval_seconds
        self.max_connection_age_seconds = max_connection_age_seconds
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.connected = False
        self.reconciliation_required = True
        self.entry_block_reason: str | None = None
        self.listen_key: str | None = None
        self.last_event_type: str | None = None
        self.last_event_ms: int | None = None
        self._last_event_ms_by_type: dict[str, int] = {}
        self.event_count = 0
        self.last_error_type: str | None = None
        self._rotate_listen_key = False

    @property
    def endpoint(self) -> str:
        if not self.listen_key:
            raise ValueError("User-data stream has no active listen key")
        events = "/".join(USER_DATA_EVENTS)
        return (
            f"{self.gateway.private_ws_base}/ws?listenKey={quote(self.listen_key, safe='')}"
            f"&events={quote(events, safe='/')}"
        )

    def assert_entry_ready(self) -> None:
        if (
            not self.connected
            or self.reconciliation_required
            or self.entry_block_reason is not None
        ):
            raise ValueError(
                "Authenticated user stream is disconnected or awaiting REST reconciliation"
            )

    def block_entries(self, reason: str) -> None:
        if not reason:
            raise ValueError("Entry block requires an evidence-backed reason")
        self.entry_block_reason = reason

    def clear_entry_block(self, reason: str) -> None:
        if self.entry_block_reason == reason:
            self.entry_block_reason = None

    def mark_reconciled(self, observed_event_count: int) -> bool:
        """Clear the event gap only if no newer event arrived during REST recovery."""
        if self.connected and self.event_count == observed_event_count:
            self.reconciliation_required = False
            return True
        return False

    @staticmethod
    def decode_event(wire: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(wire)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Malformed user-data WebSocket payload") from exc
        if not isinstance(decoded, dict):
            raise ValueError("User-data WebSocket payload must be an object")
        payload = decoded.get("data", decoded)
        if not isinstance(payload, dict) or not isinstance(payload.get("e"), str):
            raise ValueError("User-data WebSocket event is missing its event type")
        return payload

    async def _keepalive(self, socket: Any) -> None:
        assert self.listen_key is not None
        while True:
            await asyncio.sleep(self.keepalive_interval_seconds)
            try:
                success = await self.gateway.keepalive_user_data_stream(self.listen_key)
            except Exception as exc:
                self.last_error_type = type(exc).__name__
                success = False
            if not success:
                self._rotate_listen_key = True
                await socket.close()
                return

    async def _consume_connection(self) -> None:
        assert self.listen_key is not None
        was_connected = False
        keepalive_task: asyncio.Task[None] | None = None
        try:
            async with self.connector(
                self.endpoint,
                open_timeout=15,
                close_timeout=5,
                max_size=2**20,
                max_queue=64,
                ping_interval=20,
                ping_timeout=20,
            ) as socket:
                if self.on_reconnect is not None:
                    await self.on_reconnect()
                self.reconciliation_required = False
                self.connected = True
                was_connected = True
                self.last_error_type = None
                keepalive_task = asyncio.create_task(self._keepalive(socket))
                async with asyncio.timeout(self.max_connection_age_seconds):
                    async for wire in socket:
                        event = self.decode_event(wire)
                        event_type = event["e"]
                        self.last_event_type = event_type
                        raw_time = event.get("E")
                        self.last_event_ms = raw_time if isinstance(raw_time, int) else None
                        if self.last_event_ms is not None:
                            previous = self._last_event_ms_by_type.get(event_type)
                            if previous is not None and self.last_event_ms <= previous:
                                raise ValueError("User-data stream event order moved backwards")
                            self._last_event_ms_by_type[event_type] = self.last_event_ms
                        self.reconciliation_required = True
                        self.event_count += 1
                        if self.on_event is not None:
                            await self.on_event(event)
                        if event_type == "listenKeyExpired":
                            self._rotate_listen_key = True
                            break
        finally:
            self.connected = False
            self.reconciliation_required = True
            if keepalive_task is not None:
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass
            if was_connected and self.on_disconnect is not None:
                await self.on_disconnect()

    async def run(self) -> None:
        """Reconnect indefinitely; cancellation closes only the stream owned here."""
        last_keepalive = 0.0
        try:
            while True:
                if not self.gateway.api_key or not self.gateway.api_secret:
                    self.last_error_type = "MissingSelectedEnvironmentCredentials"
                    if self.reconnect_delay_seconds:
                        await asyncio.sleep(self.reconnect_delay_seconds)
                    else:
                        await asyncio.sleep(1)
                    continue
                try:
                    if self.listen_key is None or self._rotate_listen_key:
                        self.listen_key = await self.gateway.create_listen_key()
                        self._rotate_listen_key = False
                        last_keepalive = time.monotonic()
                    elif time.monotonic() - last_keepalive >= self.keepalive_interval_seconds:
                        if not await self.gateway.keepalive_user_data_stream(self.listen_key):
                            self.listen_key = await self.gateway.create_listen_key()
                        last_keepalive = time.monotonic()
                    await self._consume_connection()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error_type = type(exc).__name__
                    self.connected = False
                if self.reconnect_delay_seconds:
                    await asyncio.sleep(self.reconnect_delay_seconds)
        finally:
            self.connected = False
            self.reconciliation_required = True
            if self.listen_key is not None:
                try:
                    await self.gateway.close_user_data_stream(self.listen_key)
                except Exception as exc:
                    self.last_error_type = type(exc).__name__
                finally:
                    self.listen_key = None
