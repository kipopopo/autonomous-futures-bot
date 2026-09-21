"""Phase 292: Binance Futures Public WebSocket Feed Client and Sequencer.

Resilient asynchronous WebSocket client connecting strictly to Binance
Futures public read-only combined streams with RFC 6455 Ping/Pong handling,
exponential backoff reconnection with jitter, sequence gap deduplication,
gateway heartbeat health monitoring, bounded execution, and zero credentials.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import time
from collections.abc import Callable, Coroutine, Mapping
from typing import Any

import httpx
import websockets

from autonomous_futures.feed.models import (
    _to_int,
    parse_binance_agg_trade,
    parse_binance_book_ticker,
    parse_binance_depth5,
    parse_binance_kline,
    parse_binance_mark_price,
)
from autonomous_futures.feed.telemetry import FeedTelemetryAccumulator

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL: str = "wss://fstream.binance.com"
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_STREAMS: tuple[str, ...] = ("depth5@100ms", "aggTrade", "markPrice@1s")


class PublicMarketStreamSequencer:
    """Tracks update IDs, trade IDs, and timestamps to detect sequence gaps and duplicates."""

    def __init__(self) -> None:
        self._last_u: dict[str, int] = {}
        self._last_a: dict[str, int] = {}
        self._last_e: dict[str, int] = {}
        self._gaps: dict[str, int] = {}
        self._duplicates: dict[str, int] = {}

    def check_depth(self, symbol: str, u: int, pu: int | None = None) -> tuple[bool, bool]:
        """Check depth snapshot sequence.

        Returns (is_duplicate, is_gap).
        - If u <= last_u, it is a duplicate packet.
        - If last_u > 0 and pu is not None and pu != last_u, it is a sequence gap.
        """
        sym = symbol.upper()
        last_u = self._last_u.get(sym, 0)

        if last_u > 0 and u <= last_u:
            self._duplicates[sym] = self._duplicates.get(sym, 0) + 1
            return True, False

        is_gap = False
        if last_u > 0 and pu is not None and pu != last_u:
            is_gap = True
            self._gaps[sym] = self._gaps.get(sym, 0) + 1

        self._last_u[sym] = u
        return False, is_gap

    def check_agg_trade(self, symbol: str, a: int) -> bool:
        """Check aggregate trade ID monotonically increases.

        Returns True if duplicate, False otherwise.
        """
        sym = symbol.upper()
        last_a = self._last_a.get(sym, 0)
        if last_a > 0 and a <= last_a:
            self._duplicates[sym] = self._duplicates.get(sym, 0) + 1
            return True
        self._last_a[sym] = a
        return False

    def check_mark_price(self, symbol: str, event_time_ms: int) -> bool:
        """Check mark price event timestamp increases.

        Returns True if duplicate, False otherwise.
        """
        sym = symbol.upper()
        last_e = self._last_e.get(sym, 0)
        if last_e > 0 and event_time_ms <= last_e:
            self._duplicates[sym] = self._duplicates.get(sym, 0) + 1
            return True
        self._last_e[sym] = event_time_ms
        return False

    @property
    def duplicate_count(self) -> int:
        return sum(self._duplicates.values())

    @property
    def sequence_gap_count(self) -> int:
        return sum(self._gaps.values())

    @property
    def gaps_by_symbol(self) -> dict[str, int]:
        return dict(self._gaps)

    @property
    def duplicates_by_symbol(self) -> dict[str, int]:
        return dict(self._duplicates)

    def reset(self) -> None:
        self._last_u.clear()
        self._last_a.clear()
        self._last_e.clear()
        self._gaps.clear()
        self._duplicates.clear()


class BinancePublicFeedClient:
    """Resilient async public WebSocket client for Binance Futures multiplexed streams."""

    DEFAULT_BASE_URL: str = DEFAULT_BASE_URL
    DEFAULT_SYMBOLS: tuple[str, ...] = DEFAULT_SYMBOLS
    DEFAULT_STREAMS: tuple[str, ...] = DEFAULT_STREAMS

    def __init__(
        self,
        symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
        streams: tuple[str, ...] | None = None,
        stream_types: tuple[str, ...] | None = None,
        url: str | None = None,
        base_url: str | None = None,
        telemetry: FeedTelemetryAccumulator | None = None,
        sequencer: PublicMarketStreamSequencer | None = None,
        rest_url: str = "https://fapi.binance.com",
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
        self.rest_url = rest_url.rstrip("/")
        self.telemetry = telemetry
        self.sequencer = sequencer if sequencer is not None else PublicMarketStreamSequencer()

        self.api_key: None = None
        self.api_secret: None = None

        self._ws: Any = None
        self._running: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()
        self._cb_param_counts: dict[Any, int] = {}
        self.reconnect_count: int = 0

        # Gateway telemetry metrics
        self.clock_skew_ms: float = 0.0
        self.last_heartbeat_time_ms: float = 0.0
        self.last_latency_ms: float = 0.0
        self.packet_gap_count: int = 0
        self.total_messages_received: int = 0

        # Strict paper-safe boundaries
        self.execution_authority: bool = False
        self.paper_safe: bool = True

    def get_connect_headers(self) -> dict[str, str]:
        """Return HTTP headers for WebSocket handshake (strictly zero credentials)."""
        return {}

    def build_stream_url(self) -> str:
        """Construct Binance multiplexed combined stream URL."""
        seen: set[str] = set()
        stream_names: list[str] = []

        for symbol in self.symbols:
            sym_lower = symbol.lower()
            for stream in self.streams:
                if stream.lower().startswith(f"{sym_lower}@"):
                    name = stream.lower()
                elif "@" in stream:
                    prefix = stream.split("@", 1)[0].upper()
                    if prefix in self.symbols:
                        name = stream.lower()
                    else:
                        name = f"{sym_lower}@{stream}"
                else:
                    name = f"{sym_lower}@{stream}"

                if name not in seen:
                    seen.add(name)
                    stream_names.append(name)

        # Handle fully-qualified streams that may not have matched above
        for stream in self.streams:
            if "@" in stream:
                prefix = stream.split("@", 1)[0].upper()
                if prefix in self.symbols and stream.lower() not in seen:
                    seen.add(stream.lower())
                    stream_names.append(stream.lower())

        query = "/".join(stream_names)
        return f"{self.url}/stream?streams={query}"

    @staticmethod
    def compute_backoff_delay(attempt: int, jitter: float | None = None) -> float:
        """Compute exponential backoff delay with random jitter.

        Base delay: 0.5s, multiplier: 2.0, ceiling: 8.0s, jitter: +0.1..0.4s.
        """
        exp = max(0, attempt - 1)
        base = min(8.0, 0.5 * (2.0**exp))
        j = random.uniform(0.1, 0.4) if jitter is None else jitter
        return base + j

    @property
    def heartbeat_age_ms(self) -> float:
        """Age of last received message in milliseconds."""
        if self.last_heartbeat_time_ms <= 0:
            return 0.0
        now_ms = time.time_ns() / 1_000_000.0
        return max(0.0, now_ms - self.last_heartbeat_time_ms)

    @property
    def is_heartbeat_healthy(self) -> bool:
        """True if stream is receiving messages within <= 500ms freshness threshold."""
        return self.heartbeat_age_ms <= 500.0

    async def sync_server_time(
        self,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
    ) -> float:
        """Query Binance Futures REST endpoint /fapi/v1/time to compute clock skew."""
        owns_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=timeout_seconds)
            owns_client = True

        try:
            url = f"{self.rest_url}/fapi/v1/time"
            t0_mono = time.perf_counter()
            t0_wall = time.time() * 1000.0
            response = await client.get(url)
            t1_mono = time.perf_counter()
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or "serverTime" not in data:
                raise ValueError("Invalid response from Binance /fapi/v1/time")
            server_ms = int(data["serverTime"])
            rtt_ms = max(0.1, (t1_mono - t0_mono) * 1000.0)
            client_est_ms = t0_wall + (rtt_ms / 2.0)
            self.clock_skew_ms = float(server_ms - client_est_ms)
            return self.clock_skew_ms
        finally:
            if owns_client:
                await client.aclose()

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
        on_depth: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_agg_trade: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_mark_price: Callable[..., Coroutine[Any, Any, None]] | None = None,
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
                self.last_heartbeat_time_ms = vps_received_ms
                self.total_messages_received += 1

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
                    if isinstance(payload.get("data"), (dict, Mapping))
                    else payload
                )
                symbol = (
                    str(data_obj.get("s", "")).upper()
                    if isinstance(data_obj, (dict, Mapping))
                    else ""
                )
                if not symbol and stream_name and "@" in stream_name:
                    symbol = stream_name.split("@")[0].upper()

                event_time_ms = (
                    (data_obj.get("E") or data_obj.get("T"))
                    if isinstance(data_obj, (dict, Mapping))
                    else None
                )

                if event_time_ms is not None:
                    try:
                        self.last_latency_ms = max(
                            0.0, vps_received_ms - float(_to_int(event_time_ms, "event_time"))
                        )
                    except Exception:
                        pass

                # Infer stream_name if not provided in envelope
                if not stream_name and symbol and isinstance(data_obj, (dict, Mapping)):
                    e_type = data_obj.get("e")
                    if "k" in data_obj or e_type == "kline":
                        interval = (
                            data_obj.get("k", {}).get("i", "5m")
                            if isinstance(data_obj.get("k"), dict)
                            else "5m"
                        )
                        stream_name = f"{symbol.lower()}@kline_{interval}"
                    elif e_type == "depthUpdate" or (
                        "b" in data_obj and isinstance(data_obj["b"], (list, tuple))
                    ):
                        stream_name = f"{symbol.lower()}@depth5@100ms"
                    elif e_type == "aggTrade" or (
                        "a" in data_obj and "p" in data_obj and "m" in data_obj
                    ):
                        stream_name = f"{symbol.lower()}@aggTrade"
                    elif e_type == "markPriceUpdate" or (
                        "p" in data_obj and "r" in data_obj and "i" in data_obj
                    ):
                        stream_name = f"{symbol.lower()}@markPrice@1s"
                    elif e_type == "bookTicker" or ("b" in data_obj and "a" in data_obj):
                        stream_name = f"{symbol.lower()}@bookTicker"

                # Record EVERY valid wire frame at ingress
                if self.telemetry is not None:
                    ev_ms = (
                        _to_int(event_time_ms, "event_time_ms")
                        if event_time_ms is not None
                        else int(vps_received_ms)
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

                # Route event based on stream or event type
                event_type = data_obj.get("e", "") if isinstance(data_obj, (dict, Mapping)) else ""

                if (
                    "depth" in stream_name
                    or event_type == "depthUpdate"
                    or (
                        isinstance(data_obj, (dict, Mapping))
                        and "b" in data_obj
                        and isinstance(data_obj["b"], (list, tuple))
                        and "a" in data_obj
                    )
                ) and event_type != "bookTicker":
                    u_val = _to_int(data_obj.get("u") or data_obj.get("lastUpdateId") or 0, "u_val")
                    pu_val = (
                        _to_int(data_obj["pu"], "pu_val")
                        if "pu" in data_obj and data_obj["pu"] is not None
                        else None
                    )
                    is_dup, is_gap = self.sequencer.check_depth(symbol, u_val, pu_val)
                    if is_gap:
                        self.packet_gap_count += 1
                    if not is_dup:
                        depth = parse_binance_depth5(payload)
                        if on_depth is not None:
                            await self._invoke_callback(on_depth, depth, recv_ns)

                elif (
                    "aggTrade" in stream_name
                    or event_type == "aggTrade"
                    or (
                        isinstance(data_obj, (dict, Mapping))
                        and "a" in data_obj
                        and "p" in data_obj
                        and "m" in data_obj
                    )
                ):
                    a_val = _to_int(data_obj.get("a", 0), "a_val")
                    is_dup = self.sequencer.check_agg_trade(symbol, a_val)
                    if not is_dup:
                        trade = parse_binance_agg_trade(payload)
                        if on_agg_trade is not None:
                            await self._invoke_callback(on_agg_trade, trade, recv_ns)

                elif (
                    "markPrice" in stream_name
                    or event_type == "markPriceUpdate"
                    or (
                        isinstance(data_obj, (dict, Mapping))
                        and "p" in data_obj
                        and "r" in data_obj
                        and "i" in data_obj
                    )
                ):
                    e_val = _to_int(data_obj.get("E") or data_obj.get("T") or 0, "e_val")
                    is_dup = self.sequencer.check_mark_price(symbol, e_val)
                    if not is_dup:
                        mark = parse_binance_mark_price(payload)
                        if on_mark_price is not None:
                            await self._invoke_callback(on_mark_price, mark, recv_ns)

                elif "kline" in stream_name or (
                    isinstance(data_obj, (dict, Mapping))
                    and (data_obj.get("e") == "kline" or "k" in data_obj)
                ):
                    bar = parse_binance_kline(payload)
                    if bar is not None:
                        if self.telemetry is not None:
                            self.telemetry.record_bar(bar, recv_ns=recv_ns, record_latency=False)
                        if on_bar is not None:
                            await self._invoke_callback(on_bar, bar, recv_ns)

                elif "bookTicker" in stream_name or (
                    isinstance(data_obj, (dict, Mapping))
                    and (
                        data_obj.get("e") == "bookTicker"
                        or ("b" in data_obj and "a" in data_obj and "u" not in data_obj)
                    )
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
            self._ws = None
            if self.telemetry is not None:
                self.telemetry.stop()

    async def connect_and_stream(
        self,
        duration_seconds: float | None = None,
        on_bar: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_ticker: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_depth: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_agg_trade: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_mark_price: Callable[..., Coroutine[Any, Any, None]] | None = None,
        on_raw_message: Callable[..., Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Connect to Binance Futures WebSocket and stream messages with automatic Ping/Pong."""
        endpoint = self.build_stream_url()
        self._running = True
        self._stop_event.clear()

        start_time = time.monotonic()
        reconnect_attempt = 0
        healthy_threshold_seconds = 30.0

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

                conn_start = time.monotonic()
                try:
                    async with websockets.connect(
                        endpoint,
                        ping_interval=None,
                        close_timeout=10.0,
                        max_size=2**20,
                    ) as ws:
                        logger.info("Connected to Binance public feed: %s", endpoint)
                        await self.consume_stream(
                            ws,
                            duration_seconds=remaining,
                            on_bar=on_bar,
                            on_ticker=on_ticker,
                            on_depth=on_depth,
                            on_agg_trade=on_agg_trade,
                            on_mark_price=on_mark_price,
                            on_raw_message=on_raw_message,
                        )
                except (websockets.exceptions.ConnectionClosed, Exception) as exc:
                    if self._stop_event.is_set():
                        break
                    if (
                        duration_seconds is not None
                        and (time.monotonic() - start_time) >= duration_seconds
                    ):
                        break

                    conn_duration = time.monotonic() - conn_start
                    if conn_duration >= healthy_threshold_seconds:
                        reconnect_attempt = 0  # Reset backoff after healthy connection >= 30s

                    reconnect_attempt += 1
                    self.reconnect_count += 1
                    delay = self.compute_backoff_delay(reconnect_attempt)

                    logger.warning(
                        "WebSocket connection dropped (%s); reconnecting in %.2fs (attempt %d)...",
                        exc,
                        delay,
                        reconnect_attempt,
                    )

                    if duration_seconds is not None:
                        rem = duration_seconds - (time.monotonic() - start_time)
                        if rem <= 0:
                            break
                        delay = min(delay, rem)

                    await asyncio.sleep(delay)
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


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_STREAMS",
    "DEFAULT_SYMBOLS",
    "BinancePublicFeedClient",
    "PublicMarketStreamSequencer",
]
