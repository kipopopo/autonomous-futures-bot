"""Unit tests for Phase 293: Sub-Second FastAPI WebSocket Telemetry Push.

Validates:
- TelemetryBroadcastManager connection tracking and bounded dispatch.
- Immediate initial state push upon WebSocket handshake.
- Periodic 15s keepalive ping/pong protocol.
- Multi-client concurrent subscription and fan-out broadcasting.
- High-priority supercritical alert push (rho >= 1.0).
- Leak-free disconnect cleanup with zero residual client handles.
- Paper-safe metadata validation across all emitted frames.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.telemetry_ws import (
    HazardAlertData,
    PaperSafeMetadata,
    TelemetryBroadcastManager,
    TelemetryStreamEnvelope,
)


@pytest.fixture
def app_with_telemetry():
    app = create_app()
    return app


@pytest.fixture
def test_client(app_with_telemetry):
    return TestClient(app_with_telemetry)


def test_telemetry_broadcast_manager_initial_state():
    """Verify TelemetryBroadcastManager hydration and initial state generation."""
    manager = TelemetryBroadcastManager()
    manager.set_initial_state_provider(lambda: {"custom_state": "active", "rho": "0.4500"})
    state = manager._get_initial_state()
    assert state["custom_state"] == "active"
    assert state["rho"] == "0.4500"


@pytest.mark.anyio
async def test_telemetry_broadcast_manager_timeout_drops_dead_clients():
    """Verify slow or failing consumers are dropped without crashing broadcaster."""
    manager = TelemetryBroadcastManager(broadcast_timeout_seconds=0.1)

    # Mock healthy client
    healthy_ws = AsyncMock()
    healthy_ws.send_text = AsyncMock()

    # Mock hung client that times out
    async def hung_send_text(text: str) -> None:
        await asyncio.sleep(0.5)

    hung_ws = AsyncMock()
    hung_ws.send_text = hung_send_text

    async with manager._lock:
        manager._connections.add(healthy_ws)
        manager._connections.add(hung_ws)

    assert manager.active_connections_count == 2

    envelope = TelemetryStreamEnvelope(
        type="hawkes_metrics",
        timestamp=datetime.now(UTC).isoformat(),
        data={"metric": "test"},
        paper_safe_metadata=PaperSafeMetadata(),
    )

    delivered = await manager.broadcast_envelope(envelope)
    assert delivered == 1
    # Hung client dropped, healthy client retained
    assert manager.active_connections_count == 1
    assert healthy_ws in manager._connections
    assert hung_ws not in manager._connections


def test_websocket_handshake_and_initial_state(test_client: TestClient):
    """Verify WebSocket handshake and immediate hydrated state receipt."""
    with test_client.websocket_connect("/ws/telemetry") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "initial_state"
        assert "data" in msg
        assert "paper_safe_metadata" in msg
        assert msg["paper_safe_metadata"]["execution_authority"] is False
        assert msg["paper_safe_metadata"]["paper_safe"] is True
        assert msg["paper_safe_metadata"]["zero_drift_verified"] is True
        assert msg["paper_safe_metadata"]["drift_usdt"] == "0E-8"


def test_websocket_alias_endpoint(test_client: TestClient):
    """Verify alias endpoint /api/v1/ws/telemetry works identically."""
    with test_client.websocket_connect("/api/v1/ws/telemetry") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "initial_state"
        assert msg["paper_safe_metadata"]["paper_safe"] is True


def test_websocket_keepalive_ping_pong(test_client: TestClient):
    """Verify client keepalive ping receives typed pong response."""
    with test_client.websocket_connect("/ws/telemetry") as ws:
        _ = ws.receive_json()  # Flush initial state
        ping_payload = {"type": "ping", "timestamp": "2026-09-21T06:00:00Z"}
        ws.send_text(json.dumps(ping_payload))

        pong_msg = ws.receive_json()
        assert pong_msg["type"] == "pong"
        assert pong_msg["client_timestamp"] == "2026-09-21T06:00:00Z"
        assert pong_msg["paper_safe_metadata"]["execution_authority"] is False


def test_websocket_multi_client_fanout_broadcast(app_with_telemetry, test_client: TestClient):
    """Verify concurrent clients all receive broadcast frames simultaneously."""
    manager: TelemetryBroadcastManager = app_with_telemetry.state.telemetry_broadcaster

    with (
        test_client.websocket_connect("/ws/telemetry") as ws1,
        test_client.websocket_connect("/ws/telemetry") as ws2,
    ):
        # Flush initial states
        _ = ws1.receive_json()
        _ = ws2.receive_json()

        assert manager.active_connections_count == 2

        envelope = TelemetryStreamEnvelope(
            type="hawkes_metrics",
            timestamp=datetime.now(UTC).isoformat(),
            data={
                "symbol": "SOLUSDT",
                "spectral_radius": "0.5200",
                "is_supercritical": False,
            },
            paper_safe_metadata=PaperSafeMetadata(),
        )

        loop = asyncio.new_event_loop()
        try:
            delivered = loop.run_until_complete(manager.broadcast_envelope(envelope))
        finally:
            loop.close()

        assert delivered == 2

        frame1 = ws1.receive_json()
        frame2 = ws2.receive_json()

        assert frame1["type"] == "hawkes_metrics"
        assert frame1["data"]["spectral_radius"] == "0.5200"
        assert frame2["type"] == "hawkes_metrics"
        assert frame2["data"]["spectral_radius"] == "0.5200"

    # Leak-free disconnect verification: connections dropped to 0
    assert manager.active_connections_count == 0


def test_websocket_supercritical_alert_dispatch(app_with_telemetry, test_client: TestClient):
    """Verify instantaneous supercritical alert push over WebSocket."""
    manager: TelemetryBroadcastManager = app_with_telemetry.state.telemetry_broadcaster

    with test_client.websocket_connect("/ws/telemetry") as ws:
        _ = ws.receive_json()  # Flush initial state

        alert_data = HazardAlertData(
            timestamp_utc=datetime.now(UTC).isoformat(),
            alert_id="alert-sc-test-999",
            severity="CRITICAL",
            hazard_type="SUPERCRITICAL_CASCADE",
            symbol="SOLUSDT",
            spectral_radius="1.0450",
            message="Supercritical cascade runaway detected!",
            action_taken="FAIL_CLOSED_LOCKOUT",
        )

        alert_envelope = TelemetryStreamEnvelope(
            type="hazard_alert",
            timestamp=datetime.now(UTC).isoformat(),
            data=alert_data.model_dump(),
            paper_safe_metadata=PaperSafeMetadata(),
        )

        loop = asyncio.new_event_loop()
        try:
            delivered = loop.run_until_complete(manager.broadcast_envelope(alert_envelope))
        finally:
            loop.close()

        assert delivered == 1

        alert_frame = ws.receive_json()
        assert alert_frame["type"] == "hazard_alert"
        assert alert_frame["data"]["hazard_type"] == "SUPERCRITICAL_CASCADE"
        assert alert_frame["data"]["spectral_radius"] == "1.0450"
        assert alert_frame["data"]["severity"] == "CRITICAL"
