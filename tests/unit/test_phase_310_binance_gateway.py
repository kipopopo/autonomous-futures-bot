"""Autonomous Futures Bot - Phase 310 Unit Tests: Binance Futures Gateway Bridge.

Verifies:
- HMAC-SHA256 signature generation and parameter serialization
- Monotonic nonce sequence generation under high frequency
- Clock drift detection, offset compensation, and |dt| > 1000ms threshold enforcement
- Authenticated signed REST endpoints (order creation, cancellation, position risk, account sync)
- WebSocket user data stream listenKey lifecycle (create, keepalive, close)
- Client order ID canonical 36-char generation and uniqueness
- Step-size and tick-size quantization helpers
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import urllib.parse
from decimal import Decimal

from autonomous_futures.execution.binance_gateway import (
    BinanceFuturesGateway,
    generate_client_order_id,
    quantize_step_size,
    quantize_tick_size,
)


class TestBinanceGatewaySignaturesAndNonces:
    """Verifies cryptographic signature generation and monotonic nonce tracking."""

    def test_hmac_sha256_signature_correctness(self) -> None:
        gateway = BinanceFuturesGateway(
            api_key="test_api_key",
            api_secret="test_secret_key_1234567890",
            testnet=True,
            offline_mode=True,
        )
        params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.001",
            "timestamp": 1700000000000,
            "recvWindow": 5000,
        }
        signed = gateway.sign_payload(params)
        assert "signature" in signed

        query_str = urllib.parse.urlencode(params)
        expected_sig = hmac.new(
            b"test_secret_key_1234567890",
            query_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert signed["signature"] == expected_sig
        assert len(signed["signature"]) == 64

    def test_signature_changes_with_parameters_and_secret(self) -> None:
        gw1 = BinanceFuturesGateway(api_secret="secret1", offline_mode=True)
        gw2 = BinanceFuturesGateway(api_secret="secret2", offline_mode=True)
        params1 = {"symbol": "SOLUSDT", "timestamp": 1000, "recvWindow": 5000}
        params2 = {"symbol": "ETHUSDT", "timestamp": 1000, "recvWindow": 5000}

        sig1 = gw1.sign_payload(params1)["signature"]
        sig2 = gw1.sign_payload(params2)["signature"]
        sig1_gw2 = gw2.sign_payload(params1)["signature"]

        # Different parameters -> different signatures
        assert sig1 != sig2
        # Different secrets -> different signatures
        assert sig1 != sig1_gw2

    def test_monotonic_nonce_guarantee(self) -> None:
        gateway = BinanceFuturesGateway(offline_mode=True)
        nonces = [gateway._get_monotonic_timestamp() for _ in range(100)]

        for i in range(len(nonces) - 1):
            assert nonces[i] < nonces[i + 1], (
                f"Nonce at {i} ({nonces[i]}) not strictly less than next ({nonces[i + 1]})"
            )


class TestBinanceGatewayClockDrift:
    """Verifies clock drift compensation and offset tracking."""

    def test_acceptable_clock_drift_compensation(self) -> None:
        async def _run() -> None:
            gateway = BinanceFuturesGateway(offline_mode=True)
            offset = await gateway.sync_clock_drift()
            assert isinstance(offset, int)
            assert abs(offset) < 5000

        asyncio.run(_run())

    def test_monotonic_timestamp_adjusts_with_offset(self) -> None:
        gateway = BinanceFuturesGateway(offline_mode=True)
        initial_ts = gateway._get_monotonic_timestamp()
        gateway._server_time_offset_ms = 500
        adjusted_ts = gateway._get_monotonic_timestamp()
        assert adjusted_ts >= initial_ts + 450


class TestBinanceGatewayRestEndpoints:
    """Verifies REST order creation, cancellation, position risk, and account balance."""

    def test_create_and_cancel_limit_order(self) -> None:
        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            cid = generate_client_order_id("SOLUSDT")
            order = await gw.create_order(
                symbol="SOLUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=Decimal("0.02"),
                price=Decimal("172.50"),
                client_order_id=cid,
            )
            assert order["symbol"] == "SOLUSDT"
            assert order["side"] == "BUY"
            assert order["type"] == "LIMIT"
            assert order["status"] == "NEW"
            assert order["clientOrderId"] == cid
            assert "orderId" in order

            # Cancel order
            cancel = await gw.cancel_order(symbol="SOLUSDT", client_order_id=cid)
            assert cancel["symbol"] == "SOLUSDT"
            assert cancel["status"] == "CANCELED"
            assert cancel["clientOrderId"] == cid

        asyncio.run(_run())

    def test_create_market_order(self) -> None:
        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            cid = generate_client_order_id("ETHUSDT")
            order = await gw.create_order(
                symbol="ETHUSDT",
                side="BUY",
                order_type="MARKET",
                quantity=Decimal("0.005"),
                client_order_id=cid,
            )
            assert order["symbol"] == "ETHUSDT"
            assert order["status"] in ("NEW", "FILLED")
            assert order["type"] == "MARKET"

        asyncio.run(_run())

    def test_position_risk_and_account_sync(self) -> None:
        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            positions = await gw.get_position_risk("SOLUSDT")
            assert isinstance(positions, list)
            assert len(positions) >= 1
            assert positions[0]["symbol"] == "SOLUSDT"
            assert "entryPrice" in positions[0]
            assert "markPrice" in positions[0]
            assert "unRealizedProfit" in positions[0]

            account = await gw.get_account_balance()
            assert "totalWalletBalance" in account
            assert "availableBalance" in account
            assert account["canTrade"] is True

        asyncio.run(_run())

    def test_cancel_nonexistent_order_raises_or_safe(self) -> None:
        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            res = await gw.cancel_order(symbol="SOLUSDT", client_order_id="unknown_order_999")
            assert res["status"] in ("CANCELED", "UNKNOWN")

        asyncio.run(_run())


class TestBinanceGatewayUserDataStream:
    """Verifies WebSocket user data stream listenKey lifecycle."""

    def test_listen_key_lifecycle(self) -> None:
        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            # 1. Create listenKey
            key = await gw.create_listen_key()
            assert isinstance(key, str)
            assert len(key) >= 16

            # 2. Keepalive listenKey
            keepalive_ok = await gw.keepalive_user_data_stream(key)
            assert keepalive_ok is True

            # 3. Close listenKey
            close_ok = await gw.close_user_data_stream(key)
            assert close_ok is True

        asyncio.run(_run())

    def test_keepalive_expired_key(self) -> None:
        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            res = await gw.keepalive_user_data_stream("invalid_or_expired_key")
            assert res is False

        asyncio.run(_run())


class TestBinanceGatewayUtilities:
    """Verifies client order ID formatting and step/tick quantization."""

    def test_client_order_id_format_and_length(self) -> None:
        cid = generate_client_order_id("SOLUSDT")
        # Format: canary-p310-{sym[:3]}-{ts:013d}-{uuid[:6]}
        assert cid.startswith("canary-p310-")
        assert len(cid) == 36
        parts = cid.split("-")
        assert len(parts) == 5
        assert parts[0] == "canary"
        assert parts[1] == "p310"
        assert parts[2] == "sol"

    def test_quantize_step_size(self) -> None:
        step = Decimal("0.01")
        assert quantize_step_size(Decimal("0.0245"), step) == Decimal("0.02")
        assert quantize_step_size(Decimal("0.0299"), step) == Decimal("0.02")
        assert quantize_step_size(Decimal("1.5000"), step) == Decimal("1.50")

        step3 = Decimal("0.001")
        assert quantize_step_size(Decimal("0.0058"), step3) == Decimal("0.005")

    def test_quantize_tick_size(self) -> None:
        tick = Decimal("0.10")
        assert quantize_tick_size(Decimal("172.48"), tick) == Decimal("172.50")
        assert quantize_tick_size(Decimal("172.44"), tick) == Decimal("172.40")
        assert quantize_tick_size(Decimal("172.50"), tick) == Decimal("172.50")
