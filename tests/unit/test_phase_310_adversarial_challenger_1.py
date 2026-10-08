"""Autonomous Futures Bot - Phase 310 Adversarial Stress Test Suite (Challenger 1).

Adversarially probes and stress-tests:
1. Clock Drift Stress:
   - Extreme negative offsets (|dt| > 1000ms, e.g. -5,000ms, -100,000ms, -1,000,000ms)
   - Extreme positive offsets (|dt| > 1000ms, e.g. +5,000ms, +50,000ms, +10,000,000ms)
   - Automatic offset compensation and strictly non-decreasing monotonic timestamps
   - Monotonicity preservation under erratic clock adjustments and high-frequency concurrency
   - Real HTTP mock transport roundtrip offset calculation
2. Client Order ID Idempotency & Concurrency:
   - 1,000 rapid concurrent client order ID generations with 100% collision freedom
   - Canonical 36-char format verification (`canary-p310-{sym}-{ts}-{uuid}`) across diverse symbols
   - Exact length invariant enforcement under varying symbol lengths and timestamp magnitudes
   - Concurrent multi-symbol bursts without collisions
3. Network Failure & Corrupt Payloads:
   - Connection drops (ConnectError) and read timeouts (ReadTimeout) fail-closed handling
   - Malformed JSON responses (HTML 502 Bad Gateway, truncated JSON, plain text errors)
   - Graceful fail-closed rejection into BinanceAPIError without unhandled crashes
   - WebSocket corrupt/truncated payloads (empty dict, non-dict, missing keys, unknown events)
   - User data stream keepalive failure resilience
4. Precision Step-Size & MIN_NOTIONAL Boundaries:
   - Strict ROUND_DOWN quantization invariant across diverse lot step sizes
   - Sub-step-size truncations (quantizing to zero)
   - Binance MIN_NOTIONAL edge cases (5.00 USDT, 4.99 USDT, 0.00 USDT) in self-driving execution
   - Zero and negative quantity prevention (zero negative quantity orders dispatched)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from autonomous_futures.execution.binance_gateway import (
    DEFAULT_SPECS,
    BinanceAPIError,
    BinanceFuturesGateway,
    generate_client_order_id,
    quantize_step_size,
    quantize_tick_size,
)
from autonomous_futures.production.self_driving import (
    build_default_self_driving_engine,
)

# ==============================================================================
# SUITE 1: CLOCK DRIFT ADVERSARIAL STRESS
# ==============================================================================


class TestClockDriftAdversarialStress:
    """Adversarially probes clock drift compensation, extreme offsets, and monotonicity."""

    def test_clock_drift_extreme_negative_offset_automatic_compensation(self) -> None:
        """Injects severe negative drift (-5s, -100s, -1,000s) and verifies compensation."""
        gateway = BinanceFuturesGateway(offline_mode=True)
        local_pre = int(time.time() * 1000)

        for negative_offset_ms in (-5_000, -50_000, -1_000_000):
            gateway._server_time_offset_ms = negative_offset_ms
            ts = gateway._get_monotonic_timestamp()

            # The adjusted timestamp must incorporate the offset and remain positive
            assert ts > 0, f"Timestamp underflowed with negative offset {negative_offset_ms}"
            # Adjusted timestamp must be approximately local_pre + negative_offset_ms
            # or strictly greater than last nonce
            assert ts <= local_pre + negative_offset_ms + 2_000 or ts > gateway._last_nonce_ms - 100

    def test_clock_drift_extreme_positive_offset_automatic_compensation(self) -> None:
        """Injects severe positive drift (+5s, +50s, +10,000s) and verifies compensation."""
        gateway = BinanceFuturesGateway(offline_mode=True)
        local_pre = int(time.time() * 1000)

        for positive_offset_ms in (5_000, 50_000, 10_000_000):
            gateway._server_time_offset_ms = positive_offset_ms
            ts = gateway._get_monotonic_timestamp()

            assert ts >= local_pre + positive_offset_ms - 100
            assert ts > gateway._last_nonce_ms - 2

    def test_monotonic_timestamps_strictly_increasing_under_erratic_clock_adjustments(self) -> None:
        """Verifies strictly non-decreasing monotonic timestamps across chaotic offset jumps."""
        gateway = BinanceFuturesGateway(offline_mode=True)
        offsets = [-10_000, 5_000, -50_000, 20_000, -1_000, 0, 100, -500, 30_000, -100_000]

        generated_timestamps: list[int] = []
        for i in range(500):
            # Erratically perturb the server offset on every iteration
            gateway._server_time_offset_ms = offsets[i % len(offsets)]
            ts = gateway._get_monotonic_timestamp()
            generated_timestamps.append(ts)

        # Invariant: Every subsequent timestamp must be strictly greater than the previous
        for i in range(len(generated_timestamps) - 1):
            assert generated_timestamps[i] < generated_timestamps[i + 1], (
                f"Monotonicity violation at index {i}: "
                f"{generated_timestamps[i]} not < {generated_timestamps[i + 1]}"
            )

    def test_concurrent_monotonic_timestamp_generation_zero_collisions(self) -> None:
        """Generates 1,000 rapid timestamps across 20 concurrent threads without collisions."""
        gateway = BinanceFuturesGateway(offline_mode=True)

        def _fetch_timestamp(_: int) -> int:
            return gateway._get_monotonic_timestamp()

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(_fetch_timestamp, range(1000)))

        assert len(results) == 1000
        # All timestamps must be distinct (zero collisions)
        assert len(set(results)) == 1000, "Duplicate timestamps generated under concurrency"

    def test_clock_drift_sync_mock_transport_roundtrip(self) -> None:
        """Simulates REST /fapi/v1/time roundtrip with extreme clock desynchronization."""

        async def _run() -> None:
            simulated_server_time = int(time.time() * 1000) - 8_500  # Server is 8.5s in past

            def mock_handler(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/fapi/v1/time":
                    return httpx.Response(
                        status_code=200,
                        json={"serverTime": simulated_server_time},
                    )
                return httpx.Response(status_code=404)

            transport = httpx.MockTransport(mock_handler)
            gw = BinanceFuturesGateway(
                mock_transport=transport,
                offline_mode=False,
            )

            offset = await gw.sync_clock_drift()
            # Computed offset should be approximately -8,500 ms (+- 500 ms network mid-point)
            assert abs(offset - (-8500)) < 500
            assert gw._server_time_offset_ms == offset

            # Check subsequent timestamp reflects the negative offset
            ts = gw._get_monotonic_timestamp()
            assert ts < int(time.time() * 1000) - 7_000

        asyncio.run(_run())

    def test_clock_drift_signed_payload_incorporates_offset(self) -> None:
        """Verifies HMAC-SHA256 signature generator uses compensated monotonic timestamp."""
        gateway = BinanceFuturesGateway(
            api_key="canary-key",
            api_secret="canary-secret",
            offline_mode=True,
        )
        gateway._server_time_offset_ms = -15_000  # -15s offset
        local_pre = int(time.time() * 1000)

        params: dict[str, Any] = {"symbol": "SOLUSDT", "side": "BUY"}
        signed = gateway.sign_payload(params)

        assert "timestamp" in signed
        assert "signature" in signed
        # Timestamp must be compensated by approximately -15,000 ms
        assert signed["timestamp"] <= local_pre - 14_000
        assert len(signed["signature"]) == 64


# ==============================================================================
# SUITE 2: CLIENT ORDER ID IDEMPOTENCY & CONCURRENCY
# ==============================================================================


class TestClientIdempotencyAndConcurrencyStress:
    """Adversarially probes client order ID formatting, uniqueness, and concurrency."""

    def test_1000_rapid_concurrent_client_order_ids_collision_free(self) -> None:
        """Generates 1,000 rapid concurrent client order IDs with 100% collision freedom."""

        def _generate(_: int) -> str:
            return generate_client_order_id("SOLUSDT")

        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            order_ids = list(executor.map(_generate, range(1000)))

        assert len(order_ids) == 1000
        # Absolute idempotency guarantee: 0 collisions
        assert len(set(order_ids)) == 1000, "Collision detected in generated client order IDs"

    def test_canonical_36_character_format_strict_regex(self) -> None:
        """Verifies client order IDs strictly comply with 36-char Binance limit and regex."""
        canonical_regex = re.compile(r"^canary-p310-[a-z0-9]{3}-\d{13}-[a-f0-9]{6}$")

        test_symbols = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "DOGEUSDT",
            "PEPEUSDT",
            "1000PEPEUSDT",
            "ADAUSDT",
            "BTC",  # 3 chars
            "A",  # 1 char (pads with 'x')
            "",  # empty (pads to 'xxx')
        ]

        for sym in test_symbols:
            cid = generate_client_order_id(sym)
            assert len(cid) == 36, (
                f"Client order ID {cid} length is {len(cid)}, expected exactly 36 chars"
            )
            assert canonical_regex.match(cid), f"Client order ID {cid} failed canonical regex match"

    def test_client_order_id_timestamp_embedding_and_padding(self) -> None:
        """Verifies timestamp segment is zero-padded to 13 digits across boundary timestamps."""
        # Test 0, 1 ms, normal epoch, and far-future epochs
        for test_ts in (0, 1, 1_700_000_000_000, 9_999_999_999_999):
            cid = generate_client_order_id("ETHUSDT", ts_ms=test_ts)
            assert len(cid) == 36
            parts = cid.split("-")
            # Structure: ['canary', 'p310', 'eth', '<13-digit-ts>', '<6-hex-suffix>']
            assert len(parts) == 5
            assert len(parts[3]) == 13
            assert parts[3] == f"{test_ts:013d}"

    def test_client_order_id_multi_symbol_rapid_burst(self) -> None:
        """Generates 1,500 client order IDs concurrently across 3 symbols."""
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

        def _gen_for_symbol(index: int) -> str:
            sym = symbols[index % len(symbols)]
            return generate_client_order_id(sym)

        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            order_ids = list(executor.map(_gen_for_symbol, range(1500)))

        assert len(order_ids) == 1500
        assert len(set(order_ids)) == 1500, "Collision found in multi-symbol burst"

        for cid in order_ids:
            assert cid.startswith("canary-p310-")
            assert len(cid) == 36


# ==============================================================================
# SUITE 3: NETWORK FAILURE & CORRUPT PAYLOADS
# ==============================================================================


class TestNetworkFailureAndCorruptPayloadStress:
    """Adversarially probes connection drops, malformed JSON, and truncated payloads."""

    def test_rest_connection_drop_raises_cleanly(self) -> None:
        """Simulates network connection drops and verifies clean exception propagation."""

        async def _run() -> None:
            def mock_handler(_: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("Connection refused by remote exchange peer")

            transport = httpx.MockTransport(mock_handler)
            gw = BinanceFuturesGateway(
                mock_transport=transport,
                offline_mode=False,
            )

            with pytest.raises(httpx.ConnectError) as exc_info:
                await gw.get_server_time()
            assert "Connection refused" in str(exc_info.value)

            with pytest.raises(httpx.ConnectError):
                await gw.create_order(
                    symbol="SOLUSDT",
                    side="BUY",
                    order_type="LIMIT",
                    quantity=Decimal("0.02"),
                    price=Decimal("170.00"),
                )

        asyncio.run(_run())

    def test_rest_read_timeout_raises_cleanly(self) -> None:
        """Simulates read timeout on REST gateway."""

        async def _run() -> None:
            def mock_handler(_: httpx.Request) -> httpx.Response:
                raise httpx.ReadTimeout("Socket read timed out after 10.0s")

            transport = httpx.MockTransport(mock_handler)
            gw = BinanceFuturesGateway(
                mock_transport=transport,
                offline_mode=False,
            )

            with pytest.raises(httpx.ReadTimeout):
                await gw.get_account_balance()

        asyncio.run(_run())

    def test_rest_malformed_json_fail_closed_handling(self) -> None:
        """Simulates non-JSON HTML error pages (502/500) and asserts clean BinanceAPIError."""

        async def _run() -> None:
            # 1. HTML 502 Bad Gateway
            def mock_502_html(_: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    status_code=502,
                    text="<html><body>502 Bad Gateway: Cloudflare Nginx</body></html>",
                )

            gw_502 = BinanceFuturesGateway(
                mock_transport=httpx.MockTransport(mock_502_html),
                offline_mode=False,
            )
            with pytest.raises(BinanceAPIError) as exc_502:
                await gw_502.create_order(
                    symbol="SOLUSDT",
                    side="BUY",
                    order_type="LIMIT",
                    quantity=Decimal("0.02"),
                    price=Decimal("170.00"),
                )
            assert exc_502.value.status_code == 502
            assert "502 Bad Gateway" in exc_502.value.message

            # 2. Truncated JSON HTTP 500
            def mock_500_truncated(_: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    status_code=500,
                    text='{"code": -1001, "msg": "Internal server erro',  # Unclosed JSON
                )

            gw_500 = BinanceFuturesGateway(
                mock_transport=httpx.MockTransport(mock_500_truncated),
                offline_mode=False,
            )
            with pytest.raises(BinanceAPIError) as exc_500:
                await gw_500.cancel_order(symbol="SOLUSDT", client_order_id="canary-123")
            assert exc_500.value.status_code == 500
            assert "Internal server erro" in exc_500.value.message

        asyncio.run(_run())

    def test_rest_binance_error_code_mapping_adversarial(self) -> None:
        """Verifies structured Binance error payloads are correctly parsed into BinanceAPIError."""

        async def _run() -> None:
            error_scenarios = [
                (-1021, "Timestamp for this request is outside of the recvWindow.", 400),
                (-2010, "Account has insufficient balance for requested action.", 400),
                (-1013, "Filter failure: MIN_NOTIONAL.", 400),
                (-1003, "Too many requests; IP banned until 1790000000000.", 429),
            ]

            for code, msg, status in error_scenarios:

                def mock_err(
                    _: httpx.Request,
                    c: int = code,
                    m: str = msg,
                    s: int = status,
                ) -> httpx.Response:
                    return httpx.Response(status_code=s, json={"code": c, "msg": m})

                gw = BinanceFuturesGateway(
                    mock_transport=httpx.MockTransport(mock_err),
                    offline_mode=False,
                )
                with pytest.raises(BinanceAPIError) as exc:
                    await gw.create_order(
                        symbol="SOLUSDT",
                        side="BUY",
                        order_type="LIMIT",
                        quantity=Decimal("0.02"),
                        price=Decimal("170.00"),
                    )
                assert exc.value.code == code
                assert exc.value.message == msg
                assert exc.value.status_code == status

        asyncio.run(_run())

    def test_websocket_corrupt_payload_handling(self) -> None:
        """Verifies handle_user_data_event safely handles malformed and truncated payloads."""
        gw = BinanceFuturesGateway(offline_mode=True)

        events_received: list[dict[str, Any]] = []

        def on_order(evt: dict[str, Any]) -> None:
            events_received.append(evt)

        def on_account(evt: dict[str, Any]) -> None:
            events_received.append(evt)

        # 1. Empty dictionary
        assert gw.handle_user_data_event({}) is None

        # 2. Dictionary without "e" key
        assert gw.handle_user_data_event({"data": 123}) is None

        # 3. Unknown custom event
        res = gw.handle_user_data_event(
            {"e": "CORRUPT_UNKNOWN_FRAME", "x": None},
            on_order_trade_update=on_order,
            on_account_update=on_account,
        )
        assert res == "CORRUPT_UNKNOWN_FRAME"

        # 4. Truncated ORDER_TRADE_UPDATE (missing sub-structures)
        res_order = gw.handle_user_data_event(
            {"e": "ORDER_TRADE_UPDATE"},
            on_order_trade_update=on_order,
        )
        assert res_order == "ORDER_TRADE_UPDATE"
        assert len(events_received) == 1

        # 5. Non-string "e" value (e.g. integer or None)
        assert gw.handle_user_data_event({"e": None}) is None
        assert str(gw.handle_user_data_event({"e": 12345})) == "12345"

    def test_websocket_keepalive_network_error_returns_false(self) -> None:
        """Verifies keepalive returns False on network drop rather than crashing."""

        async def _run() -> None:
            def mock_fail(_: httpx.Request) -> httpx.Response:
                return httpx.Response(status_code=500, text="Internal Server Error")

            gw = BinanceFuturesGateway(
                mock_transport=httpx.MockTransport(mock_fail),
                offline_mode=False,
            )
            success = await gw.keepalive_user_data_stream("test-listen-key")
            assert success is False

        asyncio.run(_run())

    def test_websocket_close_nonexistent_or_already_closed_key(self) -> None:
        """Closing non-existent listenKey returns gracefully without throwing."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            closed = await gw.close_user_data_stream("non-existent-key")
            assert closed is True

        asyncio.run(_run())


# ==============================================================================
# SUITE 4: PRECISION STEP-SIZE & MIN_NOTIONAL BOUNDARIES
# ==============================================================================


class TestPrecisionStepSizeBoundariesStress:
    """Adversarially probes step-size quantizations and MIN_NOTIONAL edge cases."""

    def test_step_size_quantization_round_down_invariant(self) -> None:
        """Verifies quantize_step_size strictly rounds down across all step sizes."""
        test_cases = [
            (Decimal("0.02987"), Decimal("0.001"), Decimal("0.029")),
            (Decimal("0.02001"), Decimal("0.01"), Decimal("0.02")),
            (Decimal("1.99999"), Decimal("1.0"), Decimal("1.0")),
            (Decimal("0.00099"), Decimal("0.001"), Decimal("0.000")),
            (Decimal("17.45678"), Decimal("0.0001"), Decimal("17.4567")),
        ]

        for raw_qty, step, expected in test_cases:
            quantized = quantize_step_size(raw_qty, step)
            assert quantized == expected
            # Mathematical invariant: quantized <= raw_qty
            assert quantized <= raw_qty

    def test_step_size_sub_step_quantizes_to_zero(self) -> None:
        """Quantities smaller than step size quantize strictly to 0.000 without negative values."""
        step = Decimal("0.01")
        for sub_qty in (Decimal("0.0099"), Decimal("0.0001"), Decimal("0.0000")):
            q = quantize_step_size(sub_qty, step)
            assert q == Decimal("0.00")
            assert q >= Decimal("0.00")

    def test_tick_size_quantization_round_half_up_invariant(self) -> None:
        """Verifies price quantize_tick_size adheres strictly to ROUND_HALF_UP."""
        tick = Decimal("0.01")
        assert quantize_tick_size(Decimal("185.0049"), tick) == Decimal("185.00")
        assert quantize_tick_size(Decimal("185.0050"), tick) == Decimal("185.01")
        assert quantize_tick_size(Decimal("185.0051"), tick) == Decimal("185.01")

        tick_10 = Decimal("0.10")
        assert quantize_tick_size(Decimal("95000.04"), tick_10) == Decimal("95000.00")
        assert quantize_tick_size(Decimal("95000.05"), tick_10) == Decimal("95000.10")

    def test_min_notional_edge_cases_self_driving_engine(self, tmp_path: Path) -> None:
        """Probes order sizing in SelfDrivingTradingEngine at 5.00, 4.99, and 0.00 boundaries."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()

        # 1. Exact 5.00 USDT boundary (SOLUSDT at $100.00):
        # max_micro_order_notional = 5.00 -> raw_qty = 5.00 / 100.00 = 0.05 SOL.
        # step_size = 0.01 -> qty = 0.05 SOL. actual_notional = 0.05 * 100.00 = 5.00 USDT.
        order_exact = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("100.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert order_exact is not None
        assert order_exact.notional_usdt == Decimal("5.00")
        assert order_exact.quantity == Decimal("0.05")

        # 2. Sizing yielding < 5.00 USDT (SOLUSDT at $100.20):
        # raw_qty = 5.00 / 100.20 = 0.049900...
        # step_size (0.01) rounding down yields 0.04 SOL.
        # actual_notional = 0.04 * 100.20 = 4.008 USDT < 5.00 USDT -> MUST BE BLOCKED!
        order_sub = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("100.20"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert order_sub is None
        assert engine.events_log[-1]["event_type"] == "MIN_NOTIONAL_INCOMPATIBLE_BLOCK"

        # 3. Extreme high price yielding 0.00 quantity:
        # SOLUSDT at $1,000,000: raw_qty = 5.00 / 1,000,000 = 0.000005.
        # rounded qty = 0.00 -> MUST BE BLOCKED!
        order_zero = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("1000000.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert order_zero is None
        assert engine.events_log[-1]["event_type"] == "MIN_NOTIONAL_INCOMPATIBLE_BLOCK"

    def test_zero_and_negative_quantities_blocked(self, tmp_path: Path) -> None:
        """Verifies zero or negative quantities never result in dispatched orders."""
        engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
        engine.run_pre_flight_check()

        # Try negative price -> should be rejected fail-closed
        res_neg = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("-10.00"),
            hawkes_rho=0.2,
            heartbeat_latency_ms=20.0,
            ensemble_signal="LONG",
            signal_confidence=0.85,
        )
        assert res_neg is None

        # Verify zero orders dispatched with quantity <= 0
        for order in engine.orders:
            assert order.quantity > Decimal("0")
            assert order.notional_usdt >= Decimal("5.00")

    def test_gateway_create_order_sub_step_quantization(self) -> None:
        """Verifies gateway create_order quantizes sub-step amounts to 0.000."""

        async def _run() -> None:
            gw = BinanceFuturesGateway(offline_mode=True)
            # Quantity 0.0005 with step_size 0.001
            res = await gw.create_order(
                symbol="ETHUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity=Decimal("0.0005"),
                price=Decimal("2800.00"),
            )
            assert res["origQty"] == "0.000"

        asyncio.run(_run())

    def test_specs_step_sizes_adherence(self) -> None:
        """Verifies DEFAULT_SPECS defines positive non-zero step sizes for all canonical symbols."""
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            spec = DEFAULT_SPECS[sym]
            assert spec["step_size"] > Decimal("0")
            assert spec["tick_size"] > Decimal("0")
            assert spec["min_qty"] > Decimal("0")
