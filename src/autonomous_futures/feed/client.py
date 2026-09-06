"""Phase 257: Binance Futures Public WebSocket Feed Client.

Resilient asynchronous WebSocket client connecting strictly to Binance
Futures public read-only combined streams with RFC 6455 Ping/Pong handling,
bounded duration execution, and zero credentials.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

import websockets

from autonomous_futures.feed.models import (
    parse_binance_book_ticker,
    parse_binance_kline,
)
from autonomous_futures.feed.telemetry import FeedTelemetryAccumulator

logger = logging.getLogger(__name__)


class BinancePublicFeedClient:
    """Resilient async public WebSocket client for Binance Futures multiplexed streams."""

    DEFAULT_BASE_URL: str = "wss://fstream.binance.com"
    DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
    DEFAULT_STREAMS: tuple[str, ...] = ("bookTicker", "kline_5m")

    def __init__(
        self,
        symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
        streams: tuple[str, ...] | None = None,
        stream_types: tuple[str, ...] | None = None,
        url: str | None = None,
        base_url: str | None = None,
        telemetry: FeedTelemetryAccumulator | None = None,
        **kwargs: Any,
    ) -> None:
        # Strict zero-credential invariant enforcement
        forbidden_keys = {
            "api_key",
            "api_secret",
            "secret",
            "token",
            "password",
            "auth",
            "private_key",
        }
        for k in kwargs:
            if any(fk in k.lower() for fk in forbidden_keys):
                raise ValueError("Credentials and authenticated parameters are strictly forbidden")

        if not symbols:
            raise ValueError("At least one symbol must be specified")

        raw_streams = (
            streams
            if streams is not None
            else (stream_types if stream_types is not None else self.DEFAULT_STREAMS)
        )
        if not raw_streams:
            raise ValueError("At least one stream must be specified")

        self.symbols = tuple(s.upper() for s in symbols)
        self.streams = tuple(raw_streams)
        self.stream_types = self.streams
        self.url = (url or base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.base_url = self.url
        self.telemetry = telemetry

        self.api_key: None = None
        self.api_secret: None = None

        self._ws: Any = None
        self._running: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._cb_param_counts: dict[Any, int] = {}

    def get_connect_headers(self) -> dict[str, str]:
        """Return HTTP headers for WebSocket handshake (strictly zero credentials)."""
        return {}

    def build_stream_url(self) -> str:
        """Construct Binance multiplexed combined stream URL."""
        seen: set[str] = set()
        stream_names: list[str] = []
        if self.streams and all("@" in s for s in self.streams):
            for stream in self.streams:
                parts = stream.split("@", 1)
                name = f"{parts[0].lower()}@{parts[1]}"
                if name not in seen:
                    seen.add(name)
                    stream_names.append(name)
        else:
            for symbol in self.symbols:
                for stream in self.streams:
                    if "@" in stream:
                        parts = stream.split("@", 1)
                        name = f"{parts[0].lower()}@{parts[1]}"
                    else:
                        name = f"{symbol.lower()}@{stream}"
                    if name not in seen:
                        seen.add(name)
                        stream_names.append(name)
        query = "/".join(stream_names)
        return f"{self.url}/stream?streams={query}"

    async def _invoke_callback(
        self, cb: Callable[..., Coroutine[Any, Any, None]], *args: Any
    ) -> None:
        """Invoke callback adapting to parameter count."""
        num_params = self._cb_param_counts.get(cb)
        if num_params is None:
            sig = inspect.signature(cb)
            num_params = len(sig.parameters)
            self._cb_param_counts[cb] = num_params
        if num_params >= len(args):
            await cb(*args)
        elif num_params == 1:
            await cb(args[0])
        elif num_params == 0:
            await cb()

    async def consume_stream(
        self,
        ws: Any,
        duration_seconds: float | None = None,
        on_bar: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_ticker: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_raw_message: Callable[..., Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Consume messages from active WebSocket session and dispatch parsed models."""
        self._ws = ws
        self._running = True
        self._stop_event.clear()

        if self.telemetry is not None:
            self.telemetry.start()

        start_time = time.monotonic()
        deadline = (start_time + duration_seconds) if duration_seconds is not None else None
        ws_iter = ws.__aiter__() if hasattr(ws, "__aiter__") else None

        try:
            while self._running and not self._stop_event.is_set():
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        logger.info("Reached probe duration deadline (%.2fs)", duration_seconds)
                        break
                    timeout = min(1.0, remaining)
                else:
                    timeout = 1.0

                try:
                    if hasattr(ws, "recv"):
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    elif ws_iter is not None:
                        raw_msg = await asyncio.wait_for(ws_iter.__anext__(), timeout=timeout)
                    else:
                        break
                except TimeoutError:
                    continue
                except StopAsyncIteration:
                    break
                except websockets.exceptions.ConnectionClosed as exc:
                    logger.warning(
                        "WebSocket connection closed by remote peer: %s (code=%s, reason=%s)",
                        exc,
                        getattr(exc, "code", None),
                        getattr(exc, "reason", None),
                    )
                    break

                recv_ns = time.time_ns()
                vps_received_ms = recv_ns / 1_000_000.0

                try:
                    payload = json.loads(raw_msg)
                except json.JSONDecodeError, TypeError:
                    if self.telemetry is not None:
                        self.telemetry.record_error()
                    continue

                if not isinstance(payload, dict):
                    continue

                stream_name = payload.get("stream", "")
                data_obj = (
                    payload.get("data", payload)
                    if isinstance(payload.get("data"), dict)
                    else payload
                )
                symbol = data_obj.get("s", "").upper() if isinstance(data_obj, dict) else ""
                event_time_ms = (
                    (data_obj.get("E") or data_obj.get("T")) if isinstance(data_obj, dict) else None
                )

                # Infer stream_name if not provided in envelope
                if not stream_name and symbol and isinstance(data_obj, dict):
                    if "k" in data_obj or data_obj.get("e") == "kline":
                        interval = (
                            data_obj.get("k", {}).get("i", "5m")
                            if isinstance(data_obj.get("k"), dict)
                            else "5m"
                        )
                        stream_name = f"{symbol.lower()}@kline_{interval}"
                    elif ("b" in data_obj and "a" in data_obj) or data_obj.get("e") == "bookTicker":
                        stream_name = f"{symbol.lower()}@bookTicker"

                # Single Source of Truth: Record EVERY valid wire frame exactly once at ingress
                if self.telemetry is not None:
                    ev_ms = (
                        int(event_time_ms) if event_time_ms is not None else int(vps_received_ms)
                    )
                    self.telemetry.record_message(
                        stream=stream_name,
                        symbol=symbol,
                        event_time_ms=ev_ms,
                        vps_received_time_ms=vps_received_ms,
                    )

                # Skip RPC acknowledgments from model parsing/dispatch
                if "result" in payload and "s" not in payload and "k" not in payload:
                    continue

                if on_raw_message is not None:
                    await self._invoke_callback(on_raw_message, payload)

                if "kline" in stream_name or (
                    isinstance(data_obj, dict) and (data_obj.get("e") == "kline" or "k" in data_obj)
                ):
                    bar = parse_binance_kline(payload)
                    if bar is not None:
                        if self.telemetry is not None:
                            self.telemetry.record_bar(bar, recv_ns=recv_ns, record_latency=False)
                        if on_bar is not None:
                            await self._invoke_callback(on_bar, bar, recv_ns)
                elif "bookTicker" in stream_name or (
                    isinstance(data_obj, dict)
                    and (data_obj.get("e") == "bookTicker" or ("b" in data_obj and "a" in data_obj))
                ):
                    ticker = parse_binance_book_ticker(payload)
                    if ticker is not None:
                        if self.telemetry is not None:
                            self.telemetry.record_ticker(
                                ticker, recv_ns=recv_ns, record_latency=False
                            )
                        if on_ticker is not None:
                            await self._invoke_callback(on_ticker, ticker, recv_ns)

        finally:
            self._running = False
            if self.telemetry is not None:
                self.telemetry.stop()

    async def connect_and_stream(
        self,
        duration_seconds: float | None = None,
        on_bar: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_ticker: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_raw_message: Callable[..., Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Connect to Binance Futures WebSocket and stream messages with automatic Ping/Pong."""
        endpoint = self.build_stream_url()
        self._running = True
        self._stop_event.clear()

        start_time = time.monotonic()
        try:
            while self._running and not self._stop_event.is_set():
                if duration_seconds is not None:
                    elapsed = time.monotonic() - start_time
                    remaining = duration_seconds - elapsed
                    if remaining <= 0:
                        logger.info("Probe duration deadline reached (%.2fs)", duration_seconds)
                        break
                else:
                    remaining = None

                try:
                    async with websockets.connect(
                        endpoint,
                        ping_interval=20.0,
                        ping_timeout=10.0,
                        close_timeout=10.0,
                        max_size=2**20,
                    ) as ws:
                        logger.info("Connected to Binance public feed: %s", endpoint)
                        await self.consume_stream(
                            ws,
                            duration_seconds=remaining,
                            on_bar=on_bar,
                            on_ticker=on_ticker,
                            on_raw_message=on_raw_message,
                        )
                except websockets.exceptions.ConnectionClosed as exc:
                    if self._stop_event.is_set():
                        break
                    if (
                        duration_seconds is not None
                        and (time.monotonic() - start_time) >= duration_seconds
                    ):
                        break
                    logger.warning(
                        "WebSocket connection dropped (%s, code=%s); reconnecting...",
                        exc,
                        getattr(exc, "code", None),
                    )
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    if self._stop_event.is_set():
                        break
                    if (
                        duration_seconds is not None
                        and (time.monotonic() - start_time) >= duration_seconds
                    ):
                        break
                    logger.warning("WebSocket error (%s); reconnecting in 1s...", exc)
                    await asyncio.sleep(1.0)
        finally:
            await self.close()

    async def close(self) -> None:
        """Gracefully close connection sending RFC 6455 Close frame code 1000."""
        self._running = False
        self._stop_event.set()
        if self._ws is not None:
            try:
                if hasattr(self._ws, "closed") and not self._ws.closed:
                    await self._ws.close(code=1000, reason="Normal Closure: probe terminated")
                elif hasattr(self._ws, "close"):
                    await self._ws.close(code=1000, reason="Normal Closure: probe terminated")
            except Exception as exc:
                logger.debug("Error while closing websocket: %s", exc)
            finally:
                self._ws = None
