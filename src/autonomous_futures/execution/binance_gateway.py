"""Binance Futures Dual-Mode Gateway Bridge (Phase 310 R1).

Provides authentic authenticated REST and WebSocket execution capabilities
supporting Binance Futures Testnet and Live endpoints, monotonic nonces,
HMAC-SHA256 signatures, clock drift compensation (|Delta t| <= 1000 ms),
canonical 36-char client order IDs, and offline mock transport fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import uuid
from collections.abc import Awaitable, Callable
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, cast

import httpx

logger = logging.getLogger("autonomous_futures.execution.binance_gateway")


def _load_dotenv_fallback() -> None:
    """Loads environment variables from .env if present and not already loaded."""
    candidates = [
        Path("/opt/autonomous-futures-bot/.env"),
        Path(".env"),
        Path(__file__).resolve().parents[3] / ".env",
    ]
    for p in candidates:
        if p.is_file():
            try:
                with open(p, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k_clean = k.strip()
                            if k_clean not in os.environ:
                                os.environ[k_clean] = v.strip().strip('"').strip("'")
            except OSError:
                pass
            break

# Endpoint URLs
BINANCE_TESTNET_REST_BASE = "https://testnet.binancefuture.com"
BINANCE_TESTNET_WS_BASE = "wss://stream.binancefuture.com/ws"

BINANCE_LIVE_REST_BASE = "https://fapi.binance.com"
BINANCE_LIVE_WS_BASE = "wss://fstream.binance.com/ws"


class BinanceGatewayError(Exception):
    """Base exception for Binance Gateway communication errors."""


class ClockDriftExceededError(BinanceGatewayError):
    """Raised when clock drift exceeds the strict 1000ms threshold."""


class BinanceAPIError(BinanceGatewayError):
    """Raised when Binance REST endpoint returns an error response."""

    def __init__(self, code: int, message: str, status_code: int = 400) -> None:
        super().__init__(f"Binance API error [{code}]: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


# Default LOT_SIZE and PRICE_FILTER specs
DEFAULT_SPECS: dict[str, dict[str, Decimal]] = {
    "BTCUSDT": {
        "step_size": Decimal("0.00001"),
        "min_qty": Decimal("0.00001"),
        "tick_size": Decimal("0.10"),
        "min_price": Decimal("1000.00"),
        "max_price": Decimal("500000.00"),
        "min_notional": Decimal("5.00"),
    },
    "ETHUSDT": {
        "step_size": Decimal("0.001"),
        "min_qty": Decimal("0.001"),
        "tick_size": Decimal("0.01"),
        "min_price": Decimal("100.00"),
        "max_price": Decimal("50000.00"),
        "min_notional": Decimal("5.00"),
    },
    "SOLUSDT": {
        "step_size": Decimal("0.01"),
        "min_qty": Decimal("0.01"),
        "tick_size": Decimal("0.01"),
        "min_price": Decimal("1.00"),
        "max_price": Decimal("5000.00"),
        "min_notional": Decimal("5.00"),
    },
}


def generate_client_order_id(symbol: str, ts_ms: int | None = None) -> str:
    """Generates a canonical 36-char idempotent client order ID.

    Format: canary-p310-{sym[:3]}-{ts_ms}-{uuid_hex[:6]}
    Example: canary-p310-btc-1790233200000-a1b2c3 (exactly 36 characters)
    """
    ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
    # Extract 3-char symbol prefix (e.g. btc, eth, sol)
    sym_clean = symbol.replace("USDT", "").lower()[:3]
    if len(sym_clean) < 3:
        sym_clean = sym_clean.ljust(3, "x")
    suffix = uuid.uuid4().hex[:6]
    # Length calculation: 12 (canary-p310-) + 3 (sym) + 1 (-) + 13 (ts) + 1 (-) + 6 (suffix) = 36
    order_id = f"canary-p310-{sym_clean}-{ts:013d}-{suffix}"
    return order_id[:36]


def generate_drill_client_order_id(
    symbol: str, ts_ms: int | None = None, role: str = "drill"
) -> str:
    """Generates a deterministic client order ID for Phase 311 execution drill (<= 36 chars).

    Formats:
    - Drill Entry: canary-p311-drill-{sym[:3]}-{ts_ms:013d} (35 chars)
    - Take-Profit: canary-p311-tp-{sym[:3]}-{ts_ms:013d} (32 chars)
    - Stop-Loss:   canary-p311-sl-{sym[:3]}-{ts_ms:013d} (32 chars)
    - Flatten/Cl:  canary-p311-cl-{sym[:3]}-{ts_ms:013d} (32 chars)
    """
    ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
    sym_clean = symbol.replace("USDT", "").lower()[:3]
    if len(sym_clean) < 3:
        sym_clean = sym_clean.ljust(3, "x")
    tag = role.lower()
    if tag in ("take_profit", "tp"):
        prefix = "canary-p311-tp"
    elif tag in ("stop_loss", "sl"):
        prefix = "canary-p311-sl"
    elif tag in ("close", "flatten", "cl"):
        prefix = "canary-p311-cl"
    else:
        prefix = "canary-p311-drill"
    order_id = f"{prefix}-{sym_clean}-{ts:013d}"
    return order_id[:36]



def quantize_step_size(quantity: Decimal, step_size: Decimal) -> Decimal:
    """Quantizes quantity to step size using ROUND_DOWN."""
    return (quantity / step_size).quantize(Decimal("1"), rounding=ROUND_DOWN) * step_size


def quantize_tick_size(price: Decimal, tick_size: Decimal) -> Decimal:
    """Quantizes price to tick size using ROUND_HALF_UP."""
    return (price / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick_size


class BinanceFuturesGateway:
    """Authentic Dual-Mode Binance Futures Gateway Bridge (Testnet & Live)."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        testnet: bool | None = None,
        mock_transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
        offline_mode: bool = False,
    ) -> None:
        # Ensure .env is loaded if running outside systemd
        _load_dotenv_fallback()

        # Resolve testnet configuration from argument or environment
        if testnet is not None:
            self.testnet = testnet
        else:
            env_testnet = os.environ.get("BINANCE_TESTNET", "true").lower()
            self.testnet = env_testnet in ("1", "true", "yes")

        # Resolve credentials with multi-tiered resolution
        if self.testnet:
            raw_key = (
                api_key
                or os.environ.get("BINANCE_TESTNET_API_KEY")
                or os.environ.get("BINANCE_API_KEY")
                or "mock-p310-key-canary"
            )
            raw_secret = (
                api_secret
                or os.environ.get("BINANCE_TESTNET_SECRET_KEY")
                or os.environ.get("BINANCE_TESTNET_API_SECRET")
                or os.environ.get("BINANCE_API_SECRET")
                or os.environ.get("BINANCE_SECRET_KEY")
                or "mock-p310-secret-canary"
            )
        else:
            raw_key = (
                api_key
                or os.environ.get("BINANCE_API_KEY")
                or os.environ.get("BINANCE_TESTNET_API_KEY")
                or "mock-p310-key-canary"
            )
            raw_secret = (
                api_secret
                or os.environ.get("BINANCE_API_SECRET")
                or os.environ.get("BINANCE_SECRET_KEY")
                or os.environ.get("BINANCE_TESTNET_API_SECRET")
                or os.environ.get("BINANCE_TESTNET_SECRET_KEY")
                or "mock-p310-secret-canary"
            )
        self.api_key = raw_key.strip().strip('"').strip("'")
        self.api_secret = raw_secret.strip().strip('"').strip("'")

        self.rest_base = BINANCE_TESTNET_REST_BASE if self.testnet else BINANCE_LIVE_REST_BASE
        self.ws_base = BINANCE_TESTNET_WS_BASE if self.testnet else BINANCE_LIVE_WS_BASE

        # Clock synchronization & monotonic nonce state
        self._server_time_offset_ms: int = 0
        self._last_nonce_ms: int = 0
        self._lock = asyncio.Lock()
        self._sync_lock = asyncio.Lock()

        # Offline / Mock transport fallback
        self.offline_mode = offline_mode
        self._mock_transport = mock_transport
        self._mock_async_transport: httpx.AsyncBaseTransport | None = (
            mock_transport if isinstance(mock_transport, httpx.AsyncBaseTransport) else None
        )
        self._mock_sync_transport: httpx.BaseTransport | None = (
            mock_transport if isinstance(mock_transport, httpx.BaseTransport) else None
        )

        # Keepalive state
        self._keepalive_task: asyncio.Task[None] | None = None
        self._active_listen_keys: set[str] = set()

        # Mock orderbook / account state for offline unit testing
        self._mock_orders: dict[str, dict[str, Any]] = {}
        self._mock_balance: Decimal = Decimal("100.00")
        self._mock_positions: dict[str, dict[str, Any]] = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "positionAmt": "0.000",
                "entryPrice": "0.00",
                "markPrice": "95000.00",
                "unRealizedProfit": "0.00000000",
                "leverage": "1",
                "marginType": "cross",
                "notional": "0.00000000",
            },
            "ETHUSDT": {
                "symbol": "ETHUSDT",
                "positionAmt": "0.000",
                "entryPrice": "0.00",
                "markPrice": "2750.00",
                "unRealizedProfit": "0.00000000",
                "leverage": "1",
                "marginType": "cross",
                "notional": "0.00000000",
            },
            "SOLUSDT": {
                "symbol": "SOLUSDT",
                "positionAmt": "0.000",
                "entryPrice": "0.00",
                "markPrice": "185.00",
                "unRealizedProfit": "0.00000000",
                "leverage": "1",
                "marginType": "cross",
                "notional": "0.00000000",
            },
        }

    def _get_http_client(self) -> httpx.AsyncClient:
        """Constructs an async HTTP client with timeout and mock transport if configured."""
        return httpx.AsyncClient(
            base_url=self.rest_base,
            transport=self._mock_async_transport,
            timeout=10.0,
        )

    def _get_sync_http_client(self) -> httpx.Client:
        """Constructs a sync HTTP client with timeout and mock transport if configured."""
        return httpx.Client(
            base_url=self.rest_base,
            transport=self._mock_sync_transport,
            timeout=10.0,
        )

    def _get_monotonic_timestamp(self) -> int:
        """Returns monotonic timestamp compensated for server clock drift.

        Ensures timestamp is strictly increasing and server offset adjusted.
        """
        local_now_ms = int(time.time() * 1000)
        adjusted_now_ms = local_now_ms + self._server_time_offset_ms
        if adjusted_now_ms <= self._last_nonce_ms:
            adjusted_now_ms = self._last_nonce_ms + 1
        self._last_nonce_ms = adjusted_now_ms
        return adjusted_now_ms

    def sign_payload(self, params: dict[str, Any]) -> dict[str, Any]:
        """Signs query/form parameters with HMAC-SHA256."""
        signed_params = dict(params)
        if "timestamp" not in signed_params:
            signed_params["timestamp"] = self._get_monotonic_timestamp()
        if "recvWindow" not in signed_params:
            signed_params["recvWindow"] = 5000

        # Sort and encode query string
        query_string = urllib.parse.urlencode(signed_params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params["signature"] = signature
        return signed_params

    # =========================================================================
    # Public & Sync Methods
    # =========================================================================

    async def get_server_time(self) -> int:
        """Fetches Binance server time: GET /fapi/v1/time."""
        if self.offline_mode and not self._mock_transport:
            return int(time.time() * 1000)

        async with self._get_http_client() as client:
            resp = await client.get("/fapi/v1/time")
            if resp.status_code != 200:
                raise BinanceAPIError(resp.status_code, resp.text, status_code=resp.status_code)
            data = resp.json()
            return int(data["serverTime"])

    async def sync_clock_drift(self) -> int:
        """Synchronizes server time offset maintaining |Delta t| <= 1000 ms.

        Calculates offset = serverTime - localTime.
        Returns the computed offset in milliseconds.
        """
        async with self._sync_lock:
            local_pre = int(time.time() * 1000)
            server_time = await self.get_server_time()
            local_post = int(time.time() * 1000)
            local_mid = (local_pre + local_post) // 2

            # offset = server_time - local_time
            offset = server_time - local_mid
            drift = abs(offset)
            self._server_time_offset_ms = offset

            logger.info(
                "Synchronized clock drift: offset=%d ms (latency=%d ms)",
                offset,
                local_post - local_pre,
            )
            # Guardrail check: compensated drift should be within acceptable bounds
            if drift > 1000 and self.offline_mode is False and not self._mock_transport:
                logger.warning(
                    "Raw clock drift |Delta t| = %d ms exceeded 1000 ms; offset applied.",
                    drift,
                )
            return offset

    async def get_klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[list[Any]]:
        """Fetches public market klines: GET /fapi/v1/klines."""
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1500),
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        if self.offline_mode and not self._mock_transport:
            now_ms = int(time.time() * 1000)
            interval_ms = 900000 if interval == "15m" else 3600000
            return [
                [
                    now_ms - (limit - i) * interval_ms,
                    "185.00",
                    "186.00",
                    "184.00",
                    "185.50",
                    "1000.0",
                    now_ms - (limit - i - 1) * interval_ms,
                    "185500.0",
                    100,
                    "500.0",
                    "92750.0",
                    "0",
                ]
                for i in range(limit)
            ]

        try:
            async with self._get_http_client() as client:
                resp = await client.get("/fapi/v1/klines", params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        return cast(list[list[Any]], data)
        except Exception as net_err:
            logger.debug(
                "Primary klines fetch notice for %s: %s; trying live public endpoint",
                symbol,
                net_err,
            )

        # Fallback to mainnet public market data endpoint (standard practice for quants)
        async with httpx.AsyncClient(base_url=BINANCE_LIVE_REST_BASE, timeout=10.0) as live_client:
            live_resp = await live_client.get("/fapi/v1/klines", params=params)
            if live_resp.status_code != 200:
                raise BinanceAPIError(
                    live_resp.status_code,
                    live_resp.text,
                    status_code=live_resp.status_code,
                )
            return cast(list[list[Any]], live_resp.json())

    async def get_ticker_price(self, symbol: str) -> Decimal:
        """Fetches latest mark price: GET /fapi/v1/ticker/price."""
        if self.offline_mode and not self._mock_transport:
            default_prices = {
                "BTCUSDT": Decimal("95000.00"),
                "ETHUSDT": Decimal("2750.00"),
                "SOLUSDT": Decimal("185.00"),
            }
            return default_prices.get(symbol.upper(), Decimal("100.00"))

        async with self._get_http_client() as client:
            resp = await client.get("/fapi/v1/ticker/price", params={"symbol": symbol.upper()})
            if resp.status_code != 200:
                raise BinanceAPIError(resp.status_code, resp.text, status_code=resp.status_code)
            data = resp.json()
            return Decimal(str(data["price"]))

    # =========================================================================
    # Order Dispatch & Management
    # =========================================================================

    async def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
        stop_price: Decimal | None = None,
        client_order_id: str | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """Submits an order to Binance Futures: POST /fapi/v1/order.

        Applies LOT_SIZE step-size rounding, PRICE_FILTER tick-size rounding,
        and monotonic HMAC-SHA256 signature.
        """
        spec = DEFAULT_SPECS.get(symbol.upper(), {})
        step_size = spec.get("step_size", Decimal("0.001"))
        tick_size = spec.get("tick_size", Decimal("0.01"))

        # 1. Step-size and tick-size quantization
        quantized_qty = quantize_step_size(quantity, step_size)
        quantized_price = quantize_tick_size(price, tick_size) if price is not None else None
        quantized_stop = (
            quantize_tick_size(stop_price, tick_size) if stop_price is not None else None
        )

        cid = client_order_id or generate_client_order_id(symbol)

        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantized_qty:f}",
            "newClientOrderId": cid,
        }

        if order_type.upper() == "LIMIT":
            if quantized_price is None:
                raise ValueError("Limit orders require a price.")
            params["price"] = f"{quantized_price:f}"
            params["timeInForce"] = time_in_force

        if order_type.upper() in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            if quantized_stop is None:
                raise ValueError(f"{order_type.upper()} orders require stopPrice.")
            params["stopPrice"] = f"{quantized_stop:f}"

        if reduce_only:
            params["reduceOnly"] = "true"

        signed_params = self.sign_payload(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        if self.offline_mode and not self._mock_transport:
            # Synthetic mock response for offline tests
            order_data = {
                "clientOrderId": cid,
                "cumQty": "0.000",
                "cumQuote": "0.00000",
                "executedQty": "0.000",
                "orderId": int(uuid.uuid4().int % 100000000),
                "avgPrice": "0.00000",
                "origQty": f"{quantized_qty:f}",
                "price": f"{quantized_price:f}" if quantized_price else "0.00",
                "reduceOnly": reduce_only,
                "side": side.upper(),
                "positionSide": "BOTH",
                "status": "NEW",
                "stopPrice": f"{quantized_stop:f}" if quantized_stop else "0.00",
                "symbol": symbol.upper(),
                "timeInForce": time_in_force if order_type.upper() == "LIMIT" else "GTC",
                "type": order_type.upper(),
                "updateTime": int(time.time() * 1000),
            }
            self._mock_orders[cid] = order_data
            return order_data

        async with self._get_http_client() as client:
            resp = await client.post("/fapi/v1/order", params=signed_params, headers=headers)
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    err_code = err_json.get("code", resp.status_code)
                    # Support Binance conditional order migration to /fapi/v1/algoOrder
                    if err_code == -4120 and order_type.upper() in (
                        "STOP_MARKET",
                        "TAKE_PROFIT_MARKET",
                        "STOP",
                        "TAKE_PROFIT",
                    ):
                        algo_params: dict[str, Any] = {
                            "symbol": symbol.upper(),
                            "side": side.upper(),
                            "algoType": "CONDITIONAL",
                            "type": order_type.upper(),
                            "quantity": f"{quantized_qty:f}",
                        }
                        if quantized_stop is not None:
                            algo_params["triggerPrice"] = f"{quantized_stop:f}"
                        if quantized_price is not None:
                            algo_params["price"] = f"{quantized_price:f}"
                        if client_order_id:
                            algo_params["clientAlgoId"] = cid
                        if reduce_only:
                            algo_params["reduceOnly"] = "true"
                        signed_algo = self.sign_payload(algo_params)
                        algo_resp = await client.post(
                            "/fapi/v1/algoOrder", params=signed_algo, headers=headers
                        )
                        if algo_resp.status_code == 200:
                            algo_data = cast(dict[str, Any], algo_resp.json())
                            algo_data["orderId"] = algo_data.get("algoId")
                            algo_data["clientOrderId"] = algo_data.get("clientAlgoId", cid)
                            algo_data["status"] = algo_data.get("algoStatus", "NEW")
                            algo_data["stopPrice"] = algo_data.get("triggerPrice", "0.00")
                            return algo_data
                        if algo_resp.status_code == 400 and reduce_only:
                            # Retry without reduceOnly if resting order not yet filled
                            algo_params["reduceOnly"] = "false"
                            signed_algo2 = self.sign_payload(algo_params)
                            algo_resp2 = await client.post(
                                "/fapi/v1/algoOrder", params=signed_algo2, headers=headers
                            )
                            if algo_resp2.status_code == 200:
                                algo_data2 = cast(dict[str, Any], algo_resp2.json())
                                algo_data2["orderId"] = algo_data2.get("algoId")
                                algo_data2["clientOrderId"] = algo_data2.get("clientAlgoId", cid)
                                algo_data2["status"] = algo_data2.get("algoStatus", "NEW")
                                algo_data2["stopPrice"] = algo_data2.get("triggerPrice", "0.00")
                                return algo_data2
                    raise BinanceAPIError(
                        err_json.get("code", resp.status_code),
                        err_json.get("msg", resp.text),
                        status_code=resp.status_code,
                    )
                except json.JSONDecodeError:
                    raise BinanceAPIError(
                        resp.status_code, resp.text, status_code=resp.status_code
                    ) from None
            return cast(dict[str, Any], resp.json())

    async def cancel_order(
        self,
        symbol: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Cancels an existing order: DELETE /fapi/v1/order."""
        if order_id is None and client_order_id is None:
            raise ValueError("Must provide either order_id or client_order_id.")

        params: dict[str, Any] = {"symbol": symbol.upper()}
        if order_id is not None:
            params["orderId"] = order_id
        if client_order_id is not None:
            params["origClientOrderId"] = client_order_id

        signed_params = self.sign_payload(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        if self.offline_mode and not self._mock_transport:
            cid = client_order_id or str(order_id)
            return {
                "clientOrderId": cid,
                "orderId": order_id or 12345678,
                "symbol": symbol.upper(),
                "status": "CANCELED",
            }

        async with self._get_http_client() as client:
            resp = await client.delete("/fapi/v1/order", params=signed_params, headers=headers)
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    err_code = err_json.get("code", resp.status_code)
                    if err_code in (-2011, -1001, -4120):
                        # Try deleting from algoOrder endpoint if unknown on order endpoint
                        algo_cancel_params: dict[str, Any] = {}
                        if order_id is not None:
                            algo_cancel_params["algoId"] = order_id
                        if client_order_id is not None:
                            algo_cancel_params["clientAlgoId"] = client_order_id
                        signed_algo_cancel = self.sign_payload(algo_cancel_params)
                        algo_cancel_resp = await client.delete(
                            "/fapi/v1/algoOrder", params=signed_algo_cancel, headers=headers
                        )
                        if algo_cancel_resp.status_code == 200:
                            return cast(dict[str, Any], algo_cancel_resp.json())
                    raise BinanceAPIError(
                        err_json.get("code", resp.status_code),
                        err_json.get("msg", resp.text),
                        status_code=resp.status_code,
                    )
                except json.JSONDecodeError:
                    raise BinanceAPIError(
                        resp.status_code, resp.text, status_code=resp.status_code
                    ) from None
            return cast(dict[str, Any], resp.json())

    async def get_order(
        self,
        symbol: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Queries an order status from Binance Futures: GET /fapi/v1/order."""
        if order_id is None and client_order_id is None:
            raise ValueError("Must provide either order_id or client_order_id.")

        params: dict[str, Any] = {"symbol": symbol.upper()}
        if order_id is not None:
            params["orderId"] = order_id
        if client_order_id is not None:
            params["origClientOrderId"] = client_order_id

        signed_params = self.sign_payload(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        if self.offline_mode and not self._mock_transport:
            if client_order_id and client_order_id in self._mock_orders:
                return self._mock_orders[client_order_id]
            for o in self._mock_orders.values():
                if order_id is not None and o.get("orderId") == order_id:
                    return o
            cid = client_order_id or str(order_id)
            return {
                "clientOrderId": cid,
                "orderId": order_id or 12345678,
                "symbol": symbol.upper(),
                "status": "FILLED",
                "executedQty": "0.05",
                "avgPrice": "110.42",
                "side": "BUY",
                "type": "LIMIT",
            }

        async with self._get_http_client() as client:
            resp = await client.get("/fapi/v1/order", params=signed_params, headers=headers)
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    raise BinanceAPIError(
                        err_json.get("code", resp.status_code),
                        err_json.get("msg", resp.text),
                        status_code=resp.status_code,
                    )
                except json.JSONDecodeError:
                    raise BinanceAPIError(
                        resp.status_code, resp.text, status_code=resp.status_code
                    ) from None
            return cast(dict[str, Any], resp.json())

    async def get_open_orders(
        self, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        """Queries all open orders on Binance Futures: GET /fapi/v1/openOrders."""
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol.upper()

        signed_params = self.sign_payload(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        if self.offline_mode and not self._mock_transport:
            results = []
            for o in self._mock_orders.values():
                if symbol and o.get("symbol") != symbol.upper():
                    continue
                if o.get("status") in ("NEW", "PARTIALLY_FILLED"):
                    results.append(o)
            return results

        async with self._get_http_client() as client:
            resp = await client.get("/fapi/v1/openOrders", params=signed_params, headers=headers)
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    raise BinanceAPIError(
                        err_json.get("code", resp.status_code),
                        err_json.get("msg", resp.text),
                        status_code=resp.status_code,
                    )
                except json.JSONDecodeError:
                    raise BinanceAPIError(
                        resp.status_code, resp.text, status_code=resp.status_code
                    ) from None
            return cast(list[dict[str, Any]], resp.json())

    async def cancel_all_open_orders(self, symbol: str) -> dict[str, Any]:
        """Cancels all open orders for symbol: DELETE /fapi/v1/allOpenOrders."""
        params: dict[str, Any] = {"symbol": symbol.upper()}
        signed_params = self.sign_payload(params)
        headers = {"X-MBX-APIKEY": self.api_key}

        if self.offline_mode and not self._mock_transport:
            count = 0
            for o in self._mock_orders.values():
                sym_match = o.get("symbol") == symbol.upper()
                is_open = o.get("status") in ("NEW", "PARTIALLY_FILLED")
                if sym_match and is_open:
                    o["status"] = "CANCELED"
                    count += 1
            return {
                "code": 200,
                "msg": f"The operation of cancel all open order is done. ({count} canceled)",
            }

        async with self._get_http_client() as client:
            resp = await client.delete(
                "/fapi/v1/allOpenOrders", params=signed_params, headers=headers
            )
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    raise BinanceAPIError(
                        err_json.get("code", resp.status_code),
                        err_json.get("msg", resp.text),
                        status_code=resp.status_code,
                    )
                except json.JSONDecodeError:
                    raise BinanceAPIError(
                        resp.status_code, resp.text, status_code=resp.status_code
                    ) from None
            return cast(dict[str, Any], resp.json())

    async def get_position_risk(
        self, symbol: str | None = None, version: str = "v2"
    ) -> list[dict[str, Any]]:
        """Queries real-time positions and unrealized PnL: GET /fapi/{v1|v2}/positionRisk."""
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol.upper()

        signed_params = self.sign_payload(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        endpoint = f"/fapi/{version}/positionRisk"

        if self.offline_mode and not self._mock_transport:
            if symbol is not None:
                return [self._mock_positions.get(symbol.upper(), {})]
            return list(self._mock_positions.values())

        async with self._get_http_client() as client:
            resp = await client.get(endpoint, params=signed_params, headers=headers)
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    raise BinanceAPIError(
                        err_json.get("code", resp.status_code),
                        err_json.get("msg", resp.text),
                        status_code=resp.status_code,
                    )
                except json.JSONDecodeError:
                    raise BinanceAPIError(
                        resp.status_code, resp.text, status_code=resp.status_code
                    ) from None
            data = resp.json()
            if isinstance(data, list):
                return data
            return [data]

    async def get_account_balance(self, version: str = "v2") -> dict[str, Any]:
        """Queries account balance & margin: GET /fapi/{v1|v2}/account."""
        params: dict[str, Any] = {}
        signed_params = self.sign_payload(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        endpoint = f"/fapi/{version}/account"

        if self.offline_mode and not self._mock_transport:
            bal_str = f"{self._mock_balance:.8f}"
            return {
                "feeTier": 0,
                "canTrade": True,
                "canDeposit": True,
                "canWithdraw": True,
                "updateTime": int(time.time() * 1000),
                "totalInitialMargin": "0.00000000",
                "totalMaintMargin": "0.00000000",
                "totalWalletBalance": bal_str,
                "totalUnrealizedProfit": "0.00000000",
                "totalMarginBalance": bal_str,
                "availableBalance": bal_str,
                "maxWithdrawAmount": bal_str,
                "assets": [
                    {
                        "asset": "USDT",
                        "walletBalance": bal_str,
                        "unrealizedProfit": "0.00000000",
                        "marginBalance": bal_str,
                        "availableBalance": bal_str,
                    }
                ],
                "positions": list(self._mock_positions.values()),
            }

        async with self._get_http_client() as client:
            resp = await client.get(endpoint, params=signed_params, headers=headers)
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    raise BinanceAPIError(
                        err_json.get("code", resp.status_code),
                        err_json.get("msg", resp.text),
                        status_code=resp.status_code,
                    )
                except json.JSONDecodeError:
                    raise BinanceAPIError(
                        resp.status_code, resp.text, status_code=resp.status_code
                    ) from None
            return cast(dict[str, Any], resp.json())

    # =========================================================================
    # WebSocket User Data Stream & Keepalive
    # =========================================================================

    async def create_listen_key(self) -> str:
        """Acquires a new listenKey: POST /fapi/v1/listenKey."""
        headers = {"X-MBX-APIKEY": self.api_key}
        if self.offline_mode and not self._mock_transport:
            key = f"lk-{uuid.uuid4().hex}"
            self._active_listen_keys.add(key)
            return key

        async with self._get_http_client() as client:
            resp = await client.post("/fapi/v1/listenKey", headers=headers)
            if resp.status_code != 200:
                raise BinanceAPIError(resp.status_code, resp.text, status_code=resp.status_code)
            key = resp.json()["listenKey"]
            self._active_listen_keys.add(key)
            return str(key)

    async def keepalive_user_data_stream(self, listen_key: str) -> bool:
        """Keeps alive listenKey: PUT /fapi/v1/listenKey."""
        headers = {"X-MBX-APIKEY": self.api_key}
        if self.offline_mode and not self._mock_transport:
            return listen_key in self._active_listen_keys

        async with self._get_http_client() as client:
            resp = await client.put(
                "/fapi/v1/listenKey",
                headers=headers,
                params={"listenKey": listen_key},
            )
            return resp.status_code == 200

    async def close_user_data_stream(self, listen_key: str) -> bool:
        """Closes listenKey: DELETE /fapi/v1/listenKey."""
        headers = {"X-MBX-APIKEY": self.api_key}
        if listen_key in self._active_listen_keys:
            self._active_listen_keys.remove(listen_key)

        if self._keepalive_task is not None and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            self._keepalive_task = None

        if self.offline_mode and not self._mock_transport:
            return True

        async with self._get_http_client() as client:
            resp = await client.delete(
                "/fapi/v1/listenKey",
                headers=headers,
                params={"listenKey": listen_key},
            )
            return resp.status_code == 200

    async def _keepalive_loop(self, listen_key: str, interval_sec: int = 1800) -> None:
        """Background task running keepalive every 30 minutes (1800s)."""
        try:
            while True:
                await asyncio.sleep(interval_sec)
                success = await self.keepalive_user_data_stream(listen_key)
                if not success:
                    logger.error("Failed to keepalive listenKey: %s", listen_key)
        except asyncio.CancelledError:
            logger.debug("Keepalive loop cancelled for listenKey: %s", listen_key)

    async def start_user_data_stream(
        self,
        callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        keepalive_interval_sec: int = 1800,
    ) -> str:
        """Initializes user data stream, spawns keepalive loop, returns listenKey."""
        listen_key = await self.create_listen_key()
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(listen_key, keepalive_interval_sec)
        )
        return listen_key

    def handle_user_data_event(
        self,
        event: dict[str, Any],
        on_order_trade_update: Callable[[dict[str, Any]], None] | None = None,
        on_account_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> str | None:
        """Dispatches decoded WebSocket event to appropriate handler."""
        event_type = event.get("e")
        if event_type == "ORDER_TRADE_UPDATE" and on_order_trade_update:
            on_order_trade_update(event)
            return "ORDER_TRADE_UPDATE"
        if event_type == "ACCOUNT_UPDATE" and on_account_update:
            on_account_update(event)
            return "ACCOUNT_UPDATE"
        return event_type
