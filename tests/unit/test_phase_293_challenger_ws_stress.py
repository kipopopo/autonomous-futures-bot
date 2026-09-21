"""Adversarial stress and concurrency verification for Phase 293 WebSocket Telemetry Streaming.

Challenger: challenger_phase293_2
Scope:
1. High Concurrency: 25 concurrent WebSocket clients, high-frequency burst broadcast,
   ordered delivery verification, task safety.
2. Slow / Stalling Consumers: Eviction of hung clients after timeout (0.5s), zero broadcast
   starvation for healthy clients, subsequent low-latency delivery.
3. Connection Churn & Leaks: 50 sequential & concurrent client connect/disconnect cycles,
   assert active_connections_count == 0, heartbeat task lifecycle hygiene.
4. Keepalive & Fuzzing: Ping/keepalive protocol, malformed JSON fuzzing, huge payloads,
   unhandled event rejection without connection drop.
5. Paper-Safe Metadata Invariants: Strict verification of execution_authority == False,
   paper_safe == True, zero_drift_verified == True across all envelope types.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.telemetry_ws import (
    HawkesLiveMetricsData,
    HazardAlertData,
    MicrostructureTelemetryData,
    PaperSafeMetadata,
    RegimeChangeData,
    TelemetryBroadcastManager,
    TelemetryStreamEnvelope,
)


@pytest.fixture
def app_with_telemetry() -> FastAPI:
    """Create fresh application instance with registered telemetry broadcaster."""
    return create_app()


@pytest.fixture
def test_client(app_with_telemetry: FastAPI) -> TestClient:
    """Create TestClient fixture."""
    return TestClient(app_with_telemetry)


# ---------------------------------------------------------------------------
# 1. High Concurrency & Burst Broadcasting
# ---------------------------------------------------------------------------


def test_high_concurrency_25_clients_burst_broadcast(
    app_with_telemetry: FastAPI, test_client: TestClient
) -> None:
    """Connect 25 concurrent WebSocket clients, burst 30 envelopes, verify delivery and ordering."""
    manager: TelemetryBroadcastManager = app_with_telemetry.state.telemetry_broadcaster
    num_clients = 25
    burst_count = 30

    with ExitStack() as stack:
        clients = [
            stack.enter_context(test_client.websocket_connect("/ws/telemetry"))
            for _ in range(num_clients)
        ]

        assert manager.active_connections_count == num_clients

        # Drain initial state for each client
        for client in clients:
            init_frame = client.receive_json()
            assert init_frame["type"] == "initial_state"
            assert init_frame["paper_safe_metadata"]["paper_safe"] is True

        # Broadcast high-frequency burst across event loop
        loop = asyncio.new_event_loop()
        try:
            for seq in range(burst_count):
                envelope = TelemetryStreamEnvelope(
                    type="hawkes_metrics",
                    timestamp=datetime.now(UTC).isoformat(),
                    data={
                        "seq": seq,
                        "symbol": "BTCUSDT",
                        "spectral_radius": f"{0.40 + (seq * 0.01):.4f}",
                    },
                    paper_safe_metadata=PaperSafeMetadata(),
                )
                delivered = loop.run_until_complete(manager.broadcast_envelope(envelope))
                assert delivered == num_clients
        finally:
            loop.close()

        # Verify all clients received every frame in exact sequence
        for client in clients:
            for expected_seq in range(burst_count):
                frame = client.receive_json()
                assert frame["type"] == "hawkes_metrics"
                assert frame["data"]["seq"] == expected_seq
                assert frame["paper_safe_metadata"]["execution_authority"] is False
                assert frame["paper_safe_metadata"]["paper_safe"] is True

    # After exit stack closes all connections, verify 0 leak
    assert manager.active_connections_count == 0


# ---------------------------------------------------------------------------
# 2. Slow & Stalling Consumers Eviction
# ---------------------------------------------------------------------------


def test_slow_consumer_timeout_eviction_and_healthy_delivery(
    app_with_telemetry: FastAPI, test_client: TestClient
) -> None:
    """Verify that slow consumers stalling past timeout (0.5s) are dropped cleanly."""
    manager: TelemetryBroadcastManager = app_with_telemetry.state.telemetry_broadcaster
    manager.broadcast_timeout_seconds = 0.5

    # Connect 3 healthy clients
    with (
        test_client.websocket_connect("/ws/telemetry") as ws1,
        test_client.websocket_connect("/ws/telemetry") as ws2,
        test_client.websocket_connect("/ws/telemetry") as ws3,
    ):
        # Flush initial states
        _ = ws1.receive_json()
        _ = ws2.receive_json()
        _ = ws3.receive_json()

        assert manager.active_connections_count == 3

        # Inject 2 slow/hung consumers into manager connections
        async def hung_send_text(text: str) -> None:
            await asyncio.sleep(2.0)  # Exceeds 0.5s timeout

        hung_ws1 = AsyncMock()
        hung_ws1.send_text = hung_send_text
        hung_ws2 = AsyncMock()
        hung_ws2.send_text = hung_send_text

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(manager._lock.acquire())
            manager._connections.add(hung_ws1)
            manager._connections.add(hung_ws2)
            manager._lock.release()

            assert manager.active_connections_count == 5

            envelope = TelemetryStreamEnvelope(
                type="hawkes_metrics",
                timestamp=datetime.now(UTC).isoformat(),
                data={"metric": "eviction_test_1"},
                paper_safe_metadata=PaperSafeMetadata(),
            )

            # Broadcast should drop the 2 hung clients and deliver to 3 healthy clients
            t_start = time.perf_counter()
            delivered = loop.run_until_complete(manager.broadcast_envelope(envelope))
            t_elapsed = time.perf_counter() - t_start

            assert delivered == 3
            assert manager.active_connections_count == 3
            assert hung_ws1 not in manager._connections
            assert hung_ws2 not in manager._connections

            # The broadcast should have experienced bounded timeout for the hung clients
            assert t_elapsed >= 0.5

            # Subsequent broadcast should execute immediately without delay (< 0.1s)
            subsequent_envelope = TelemetryStreamEnvelope(
                type="hawkes_metrics",
                timestamp=datetime.now(UTC).isoformat(),
                data={"metric": "eviction_test_2"},
                paper_safe_metadata=PaperSafeMetadata(),
            )
            t_subsequent_start = time.perf_counter()
            delivered_subsequent = loop.run_until_complete(
                manager.broadcast_envelope(subsequent_envelope)
            )
            t_subsequent_elapsed = time.perf_counter() - t_subsequent_start

            assert delivered_subsequent == 3
            assert t_subsequent_elapsed < 0.1
        finally:
            loop.close()

        # Verify healthy clients received both messages
        for ws in (ws1, ws2, ws3):
            msg1 = ws.receive_json()
            assert msg1["data"]["metric"] == "eviction_test_1"
            msg2 = ws.receive_json()
            assert msg2["data"]["metric"] == "eviction_test_2"

    assert manager.active_connections_count == 0


@pytest.mark.anyio
async def test_slow_consumer_isolation_with_short_timeout() -> None:
    """Unit test TelemetryBroadcastManager eviction with tight timeout deadline."""
    manager = TelemetryBroadcastManager(broadcast_timeout_seconds=0.15)

    healthy_client = AsyncMock()
    healthy_client.send_text = AsyncMock()

    async def stalling_send(text: str) -> None:
        await asyncio.sleep(1.0)

    stalling_client = AsyncMock()
    stalling_client.send_text = stalling_send

    async with manager._lock:
        manager._connections.add(healthy_client)
        manager._connections.add(stalling_client)

    assert manager.active_connections_count == 2

    envelope = TelemetryStreamEnvelope(
        type="hawkes_metrics",
        timestamp=datetime.now(UTC).isoformat(),
        data={"metric": "quick_timeout"},
        paper_safe_metadata=PaperSafeMetadata(),
    )

    t0 = time.perf_counter()
    delivered = await manager.broadcast_envelope(envelope)
    duration = time.perf_counter() - t0

    assert delivered == 1
    assert manager.active_connections_count == 1
    assert healthy_client in manager._connections
    assert stalling_client not in manager._connections
    assert 0.10 <= duration < 0.50


# ---------------------------------------------------------------------------
# 3. Connection Churn & Leak-Free Disconnects
# ---------------------------------------------------------------------------


def test_connection_churn_50_sequential_sessions(
    app_with_telemetry: FastAPI, test_client: TestClient
) -> None:
    """Rapidly connect and disconnect 50 sequential client sessions; verify zero leaks."""
    manager: TelemetryBroadcastManager = app_with_telemetry.state.telemetry_broadcaster

    for session_idx in range(50):
        with test_client.websocket_connect("/ws/telemetry") as ws:
            init = ws.receive_json()
            assert init["type"] == "initial_state"
            assert manager.active_connections_count == 1
        assert manager.active_connections_count == 0, (
            f"Session {session_idx} leaked connection handle"
        )

    assert manager.active_connections_count == 0


def test_connection_churn_50_concurrent_batch_sessions(
    app_with_telemetry: FastAPI, test_client: TestClient
) -> None:
    """Rapidly cycle 5 batches of 10 concurrent clients (50 total sessions); verify zero leaks."""
    manager: TelemetryBroadcastManager = app_with_telemetry.state.telemetry_broadcaster

    for batch_idx in range(5):
        with ExitStack() as stack:
            batch = [
                stack.enter_context(test_client.websocket_connect("/ws/telemetry"))
                for _ in range(10)
            ]
            assert manager.active_connections_count == 10
            for ws in batch:
                _ = ws.receive_json()
        assert manager.active_connections_count == 0, (
            f"Batch {batch_idx} leaked connections after context exit"
        )

    assert manager.active_connections_count == 0


@pytest.mark.anyio
async def test_disconnect_idempotency_and_background_heartbeat_hygiene() -> None:
    """Verify disconnect is idempotent and repeated start/stop leaves no orphaned tasks."""
    manager = TelemetryBroadcastManager(heartbeat_interval_seconds=0.05)

    # Idempotent disconnect on mock
    mock_ws = AsyncMock()
    mock_ws.close = AsyncMock()

    await manager.disconnect(mock_ws)
    assert manager.active_connections_count == 0

    # Add to connections and disconnect twice
    async with manager._lock:
        manager._connections.add(mock_ws)
    assert manager.active_connections_count == 1

    await manager.disconnect(mock_ws)
    assert manager.active_connections_count == 0
    await manager.disconnect(mock_ws)  # Second call should be no-op
    assert manager.active_connections_count == 0

    # Test repeated start/stop heartbeat task lifecycle
    for _ in range(5):
        manager.start_heartbeat()
        assert manager._heartbeat_task is not None
        assert not manager._heartbeat_task.done()
        await asyncio.sleep(0.01)
        await manager.stop_heartbeat()
        assert manager._heartbeat_task is None
        assert manager._is_running is False


# ---------------------------------------------------------------------------
# 4. Keepalive Protocol & Malformed Payload Fuzzing
# ---------------------------------------------------------------------------


def test_keepalive_protocol_and_malformed_frame_fuzzing(test_client: TestClient) -> None:
    """Send ping, keepalive, and malformed JSON payloads; verify server survives without drop."""
    with test_client.websocket_connect("/ws/telemetry") as ws:
        init_frame = ws.receive_json()
        assert init_frame["type"] == "initial_state"

        # Fuzzing cases: invalid syntax, empty, unexpected types, giant payload
        malformed_inputs = [
            "{{{ NOT VALID JSON",
            "",
            "   ",
            "123456",
            "true",
            "false",
            "null",
            '"a raw json string"',
            json.dumps(["list", "of", "items"]),
            json.dumps({"type": "unrecognized_action_123", "data": "ignore_me"}),
            json.dumps({"type": "execute_live_order", "quantity": 100}),
            "X" * 65536,  # 64 KB text blob
        ]

        for payload in malformed_inputs:
            ws.send_text(payload)

        # Connection MUST remain alive: verify by sending a valid ping
        ping_payload = {
            "type": "ping",
            "timestamp": "2026-09-21T07:15:00.123456Z",
        }
        ws.send_text(json.dumps(ping_payload))

        pong_frame = ws.receive_json()
        assert pong_frame["type"] == "pong"
        assert pong_frame["client_timestamp"] == "2026-09-21T07:15:00.123456Z"
        assert pong_frame["paper_safe_metadata"]["execution_authority"] is False
        assert pong_frame["paper_safe_metadata"]["paper_safe"] is True

        # Also test keepalive type alias
        keepalive_payload = {
            "type": "keepalive",
            "timestamp": "2026-09-21T07:15:01.000000Z",
        }
        ws.send_text(json.dumps(keepalive_payload))

        pong_frame_2 = ws.receive_json()
        assert pong_frame_2["type"] == "pong"
        assert pong_frame_2["client_timestamp"] == "2026-09-21T07:15:01.000000Z"


# ---------------------------------------------------------------------------
# 5. Paper-Safe Metadata Invariants across All Envelopes
# ---------------------------------------------------------------------------


def test_paper_safe_metadata_invariants_across_all_envelopes(
    app_with_telemetry: FastAPI, test_client: TestClient
) -> None:
    """Assert all envelope types strictly adhere to paper-safe metadata invariants."""
    manager: TelemetryBroadcastManager = app_with_telemetry.state.telemetry_broadcaster

    def assert_paper_safe(envelope_dict: dict[str, Any]) -> None:
        assert "paper_safe_metadata" in envelope_dict
        meta = envelope_dict["paper_safe_metadata"]
        assert meta["execution_authority"] is False
        assert meta["paper_safe"] is True
        assert meta["zero_drift_verified"] is True
        assert float(meta["drift_usdt"]) == 0.0

    with test_client.websocket_connect("/ws/telemetry") as ws:
        # 1. Initial State
        initial_frame = ws.receive_json()
        assert initial_frame["type"] == "initial_state"
        assert_paper_safe(initial_frame)

        # 2. Pong Frame
        ws.send_text(json.dumps({"type": "ping", "timestamp": "2026-09-21T07:20:00Z"}))
        pong_frame = ws.receive_json()
        assert pong_frame["type"] == "pong"
        assert_paper_safe(pong_frame)

        loop = asyncio.new_event_loop()
        try:
            # 3. Hawkes Metrics Envelope
            hawkes_data = HawkesLiveMetricsData(
                timestamp_utc=datetime.now(UTC).isoformat(),
                symbol="BTCUSDT",
                jump_intensity={"BTCUSDT": "1.25", "ETHUSDT": "0.95", "SOLUSDT": "0.45"},
                spectral_radius="0.4500",
                branching_ratios={"BTCUSDT": "0.35", "ETHUSDT": "0.25", "SOLUSDT": "0.15"},
                regimes={"BTCUSDT": "NOMINAL", "ETHUSDT": "NOMINAL", "SOLUSDT": "NOMINAL"},
                cascade_states={
                    "BTCUSDT": "STABLE",
                    "ETHUSDT": "STABLE",
                    "SOLUSDT": "STABLE",
                },
                pacing_intervals_ms={"BTCUSDT": 250.0, "ETHUSDT": 250.0, "SOLUSDT": 250.0},
                limit_offset_cushions_bps={"BTCUSDT": "1.5", "ETHUSDT": "1.5", "SOLUSDT": "1.5"},
                full_branching_matrix={
                    "BTCUSDT": {"BTCUSDT": "0.2", "ETHUSDT": "0.1", "SOLUSDT": "0.05"}
                },
            )
            hawkes_env = TelemetryStreamEnvelope(
                type="hawkes_metrics",
                timestamp=datetime.now(UTC).isoformat(),
                data=hawkes_data.model_dump(),
                paper_safe_metadata=PaperSafeMetadata(),
            )
            loop.run_until_complete(manager.broadcast_envelope(hawkes_env))
            hawkes_frame = ws.receive_json()
            assert hawkes_frame["type"] == "hawkes_metrics"
            assert_paper_safe(hawkes_frame)

            # 4. Microstructure Snapshot Envelope
            micro_data = MicrostructureTelemetryData(
                timestamp_utc=datetime.now(UTC).isoformat(),
                symbol="ETHUSDT",
                bid_price="3500.00",
                ask_price="3500.10",
                spread_bps="0.28",
                mark_price="3500.05",
                funding_rate="0.0001",
                bids=[["3500.00", "5.2"]],
                asks=[["3500.10", "4.8"]],
            )
            micro_env = TelemetryStreamEnvelope(
                type="microstructure_snapshot",
                timestamp=datetime.now(UTC).isoformat(),
                data=micro_data.model_dump(),
                paper_safe_metadata=PaperSafeMetadata(),
            )
            loop.run_until_complete(manager.broadcast_envelope(micro_env))
            micro_frame = ws.receive_json()
            assert micro_frame["type"] == "microstructure_snapshot"
            assert_paper_safe(micro_frame)

            # 5. Regime Change Envelope
            regime_data = RegimeChangeData(
                timestamp_utc=datetime.now(UTC).isoformat(),
                symbol="SOLUSDT",
                previous_regime="NOMINAL",
                current_regime="ELEVATED_INTENSITY",
                spectral_radius="0.6500",
                pacing_interval_ms=500.0,
                limit_offset_cushion_bps="3.0",
                reason="Hysteresis threshold cross",
            )
            regime_env = TelemetryStreamEnvelope(
                type="regime_change",
                timestamp=datetime.now(UTC).isoformat(),
                data=regime_data.model_dump(),
                paper_safe_metadata=PaperSafeMetadata(),
            )
            loop.run_until_complete(manager.broadcast_envelope(regime_env))
            regime_frame = ws.receive_json()
            assert regime_frame["type"] == "regime_change"
            assert_paper_safe(regime_frame)

            # 6. Hazard Alert Envelope
            hazard_data = HazardAlertData(
                timestamp_utc=datetime.now(UTC).isoformat(),
                alert_id="hazard-sc-101",
                severity="CRITICAL",
                hazard_type="SUPERCRITICAL_CASCADE",
                symbol="SOLUSDT",
                spectral_radius="1.1500",
                message="Branching ratio runaway",
                action_taken="FAIL_CLOSED_LOCKOUT",
            )
            hazard_env = TelemetryStreamEnvelope(
                type="hazard_alert",
                timestamp=datetime.now(UTC).isoformat(),
                data=hazard_data.model_dump(),
                paper_safe_metadata=PaperSafeMetadata(),
            )
            loop.run_until_complete(manager.broadcast_envelope(hazard_env))
            hazard_frame = ws.receive_json()
            assert hazard_frame["type"] == "hazard_alert"
            assert_paper_safe(hazard_frame)

            # 7. Heartbeat Envelope
            heartbeat_env = TelemetryStreamEnvelope(
                type="heartbeat",
                timestamp=datetime.now(UTC).isoformat(),
                data={"server_time_utc": datetime.now(UTC).isoformat(), "active_clients": 1},
                paper_safe_metadata=PaperSafeMetadata(),
            )
            loop.run_until_complete(manager.broadcast_envelope(heartbeat_env))
            heartbeat_frame = ws.receive_json()
            assert heartbeat_frame["type"] == "heartbeat"
            assert_paper_safe(heartbeat_frame)

            # 8. Raw Dict Broadcast with auto-injected paper-safe metadata
            raw_dict = {
                "type": "hawkes_metrics",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {"custom": "injected_metadata"},
            }
            loop.run_until_complete(manager.broadcast_envelope(raw_dict))
            raw_frame = ws.receive_json()
            assert_paper_safe(raw_frame)
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# 6. Broadcaster Edge Case Robustness
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_broadcaster_zero_clients_and_type_safety() -> None:
    """Verify broadcaster behaves gracefully with 0 clients and raises TypeError on invalid."""
    manager = TelemetryBroadcastManager()
    assert manager.active_connections_count == 0

    envelope = TelemetryStreamEnvelope(
        type="hawkes_metrics",
        timestamp=datetime.now(UTC).isoformat(),
        data={"metric": "empty_pool"},
        paper_safe_metadata=PaperSafeMetadata(),
    )
    delivered = await manager.broadcast_envelope(envelope)
    assert delivered == 0

    with pytest.raises(TypeError, match="Unsupported envelope type"):
        await manager.broadcast_envelope(["invalid_list"])  # type: ignore[arg-type]
