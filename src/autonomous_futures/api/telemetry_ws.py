"""Real-Time Telemetry Streaming & WebSocket Push (Phase 293).

Provides:
- Strictly typed DomainModel envelopes and payloads conforming to causal schema:
  - PaperSafeMetadata: execution_authority: False, zero_drift_verified: True
  - HawkesLiveMetricsData: rolling jump intensities lambda_i(t), spectral radius rho
  - MicrostructureTelemetryData: orderbook depth top levels, spread, mark price
  - RegimeChangeData: anti-flapping transitions between Hawkes regimes
  - HazardAlertData: high-priority alerts for supercritical runaway (rho >= 1.0)
  - TelemetryStreamEnvelope: wire protocol envelope
- TelemetryBroadcastManager: thread-safe / async set-based WebSocket manager with
  bounded timeout dispatch (0.5s), periodic 15s heartbeats, initial state hydration,
  and leak-free disconnect handling.
- Registration of /ws/telemetry and /api/v1/ws/telemetry endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import Field

from autonomous_futures.domain.contracts import DomainModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telemetry Pydantic Schemas
# ---------------------------------------------------------------------------


class PaperSafeMetadata(DomainModel):
    """Immutable paper-safe metadata attached to every telemetry broadcast frame."""

    execution_authority: bool = False
    paper_safe: bool = True
    zero_drift_verified: bool = True
    drift_usdt: str = "0E-8"


class HawkesLiveMetricsData(DomainModel):
    """Sub-second multivariate Hawkes jump intensity and spectral radius payload."""

    timestamp_utc: str
    symbol: str
    jump_intensity: dict[str, str]
    spectral_radius: str
    branching_ratios: dict[str, str]
    regimes: dict[str, str]
    cascade_states: dict[str, str]
    pacing_intervals_ms: dict[str, float]
    limit_offset_cushions_bps: dict[str, str]
    full_branching_matrix: dict[str, dict[str, str]]
    is_supercritical: bool = False
    is_predatory_front_running: bool = False


class MicrostructureTelemetryData(DomainModel):
    """Top-of-book depth, spread, and trade telemetry payload."""

    timestamp_utc: str
    symbol: str
    bid_price: str
    ask_price: str
    spread_bps: str
    mark_price: str | None = None
    funding_rate: str | None = None
    last_trade_price: str | None = None
    last_trade_quantity: str | None = None
    bids: list[list[str]] = Field(default_factory=list)
    asks: list[list[str]] = Field(default_factory=list)


class RegimeChangeData(DomainModel):
    """Regime transition telemetry emitted upon anti-flapping state change."""

    timestamp_utc: str
    symbol: str
    previous_regime: str
    current_regime: str
    spectral_radius: str
    pacing_interval_ms: float
    limit_offset_cushion_bps: str
    reason: str


class HazardAlertData(DomainModel):
    """High-priority hazard alert emitted on supercritical runaway (rho >= 1.0)."""

    timestamp_utc: str
    alert_id: str
    severity: Literal["CRITICAL", "HIGH", "WARNING", "INFO"] = "CRITICAL"
    hazard_type: str
    symbol: str
    spectral_radius: str
    message: str
    action_taken: str


class TelemetryStreamEnvelope(DomainModel):
    """Standardized causal telemetry envelope pushed over WebSockets."""

    type: Literal[
        "hawkes_metrics",
        "microstructure_snapshot",
        "regime_change",
        "hazard_alert",
        "heartbeat",
        "initial_state",
    ]
    timestamp: str
    data: dict[str, Any]
    paper_safe_metadata: PaperSafeMetadata = Field(default_factory=PaperSafeMetadata)


# ---------------------------------------------------------------------------
# Telemetry Broadcast Manager
# ---------------------------------------------------------------------------


class TelemetryBroadcastManager:
    """Manages connected WebSocket clients with bounded timeouts and leak-free disconnects."""

    def __init__(
        self,
        initial_state_provider: Callable[[], dict[str, Any]] | None = None,
        heartbeat_interval_seconds: float = 15.0,
        broadcast_timeout_seconds: float = 0.5,
    ) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._initial_state_provider = initial_state_provider
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.broadcast_timeout_seconds = broadcast_timeout_seconds
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._is_running: bool = False

    @property
    def active_connections_count(self) -> int:
        """Return the number of currently active WebSocket clients."""
        return len(self._connections)

    def set_initial_state_provider(self, provider: Callable[[], dict[str, Any]] | None) -> None:
        """Configure callable to generate hydrated state for newly connected clients."""
        self._initial_state_provider = provider

    def _get_initial_state(self) -> dict[str, Any]:
        if self._initial_state_provider is not None:
            try:
                return self._initial_state_provider()
            except Exception as exc:
                logger.warning("Error fetching initial state: %s", exc)
        return {
            "status": "INITIALIZED",
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "spectral_radius": "0.428571",
            "current_regime": "NOMINAL",
            "message": "Connected to Autonomous Futures Hawkes Telemetry Stream",
        }

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection and push immediate hydrated state."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

        initial_envelope = TelemetryStreamEnvelope(
            type="initial_state",
            timestamp=datetime.now(UTC).isoformat(),
            data=self._get_initial_state(),
            paper_safe_metadata=PaperSafeMetadata(),
        )
        try:
            await websocket.send_text(initial_envelope.model_dump_json())
        except Exception as exc:
            logger.debug("Failed sending initial state to client: %s", exc)
            await self.disconnect(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Cleanly remove a client connection without throwing exceptions."""
        async with self._lock:
            self._connections.discard(websocket)
        try:
            await websocket.close()
        except Exception:
            pass

    async def broadcast_envelope(self, envelope: TelemetryStreamEnvelope | dict[str, Any]) -> int:
        """Broadcast an envelope to all connected clients with bounded timeout.

        Drops slow consumers that exceed broadcast_timeout_seconds to prevent
        event loop starvation.
        """
        if isinstance(envelope, TelemetryStreamEnvelope):
            payload = envelope.model_dump_json()
        elif isinstance(envelope, dict):
            if "paper_safe_metadata" not in envelope:
                envelope["paper_safe_metadata"] = PaperSafeMetadata().model_dump()
            payload = json.dumps(envelope)
        else:
            raise TypeError(f"Unsupported envelope type: {type(envelope)}")

        async with self._lock:
            clients = list(self._connections)

        if not clients:
            return 0

        dead_clients: list[WebSocket] = []
        successful_count = 0

        for client in clients:
            try:
                await asyncio.wait_for(
                    client.send_text(payload),
                    timeout=self.broadcast_timeout_seconds,
                )
                successful_count += 1
            except (
                TimeoutError,
                WebSocketDisconnect,
                RuntimeError,
                ConnectionResetError,
                Exception,
            ) as exc:
                logger.debug("Client broadcast failed or timed out (%s), dropping", exc)
                dead_clients.append(client)

        if dead_clients:
            async with self._lock:
                for dead in dead_clients:
                    self._connections.discard(dead)

        return successful_count

    async def start_heartbeat_loop(self) -> None:
        """Run continuous periodic 15-second server keepalive broadcasts."""
        self._is_running = True
        try:
            while self._is_running:
                await asyncio.sleep(self.heartbeat_interval_seconds)
                if not self._is_running:
                    break
                heartbeat_envelope = TelemetryStreamEnvelope(
                    type="heartbeat",
                    timestamp=datetime.now(UTC).isoformat(),
                    data={
                        "server_time_utc": datetime.now(UTC).isoformat(),
                        "active_clients": len(self._connections),
                        "heartbeat_interval_s": self.heartbeat_interval_seconds,
                    },
                    paper_safe_metadata=PaperSafeMetadata(),
                )
                await self.broadcast_envelope(heartbeat_envelope)
        except asyncio.CancelledError:
            pass
        finally:
            self._is_running = False

    def start_heartbeat(self) -> None:
        """Schedule background heartbeat loop in current asyncio event loop."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            loop = asyncio.get_event_loop()
            self._heartbeat_task = loop.create_task(self.start_heartbeat_loop())

    async def stop_heartbeat(self) -> None:
        """Cancel and await termination of the background heartbeat task."""
        self._is_running = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None


# ---------------------------------------------------------------------------
# FastAPI WebSocket Route Registration
# ---------------------------------------------------------------------------


def register_telemetry_websocket(
    app: FastAPI,
    broadcaster: TelemetryBroadcastManager | None = None,
    manager: TelemetryBroadcastManager | None = None,
) -> TelemetryBroadcastManager:
    """Register /ws/telemetry and /api/v1/ws/telemetry endpoints on FastAPI application."""
    broadcast_manager = broadcaster or manager or TelemetryBroadcastManager()
    app.state.telemetry_broadcaster = broadcast_manager

    async def telemetry_ws_endpoint(websocket: WebSocket) -> None:
        await broadcast_manager.connect(websocket)
        try:
            while True:
                data_text = await websocket.receive_text()
                # Process client keepalive or ping
                try:
                    msg = json.loads(data_text)
                    if isinstance(msg, dict) and msg.get("type") in ("ping", "keepalive"):
                        pong_response = {
                            "type": "pong",
                            "timestamp": datetime.now(UTC).isoformat(),
                            "client_timestamp": msg.get("timestamp"),
                            "paper_safe_metadata": {
                                "execution_authority": False,
                                "paper_safe": True,
                                "zero_drift_verified": True,
                                "drift_usdt": "0E-8",
                            },
                        }
                        await websocket.send_text(json.dumps(pong_response))
                except Exception:
                    # Ignore non-json or unhandled client frames
                    pass
        except WebSocketDisconnect:
            await broadcast_manager.disconnect(websocket)
        except Exception:
            await broadcast_manager.disconnect(websocket)

    # Register both primary /ws/telemetry and alias /api/v1/ws/telemetry
    app.websocket("/ws/telemetry")(telemetry_ws_endpoint)
    app.websocket("/api/v1/ws/telemetry")(telemetry_ws_endpoint)

    return broadcast_manager
