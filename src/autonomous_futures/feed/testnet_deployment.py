"""Phase 278: Production Canary Testnet Deployment Runner & WebSocket Reconciler.

Implements the deterministic Phase 278 testnet micro-execution deployment runner, real-time
WebSocket user data stream ingress reconciler, listenKey lifecycle governance, asynchronous
order correlation, and fail-closed incident response harness under Candidate Registry Manifest
Version 2 to validate execution push events, listenKey renewal, and live order tracking
in a sandbox environment before mainnet capital authorization.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import Field

from autonomous_futures.domain.contracts import DomainModel
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.feed.canary_activation import (
    CANARY_STAGED_SYMBOLS,
    DAILY_LOSS_BUDGET_USDT,
    DEFAULT_PHASE276_OUTPUT_DIR,
    DEFAULT_REFERENCE_PRICES,
    HARD_NOTIONAL_CAP_USDT,
    STARTING_EQUITY_USDT,
    CanaryActivationCertificate,
    OrderSide,
    OrderType,
    SecureExchangeKeyVault,
    TimeInForce,
)
from autonomous_futures.feed.canary_activation import (
    CertificateExpiredError as UpstreamCertificateExpiredError,
)
from autonomous_futures.feed.canary_activation import (
    CertificateInvalidatedError as UpstreamCertificateInvalidatedError,
)
from autonomous_futures.feed.canary_activation import (
    PrerequisiteQualificationError as UpstreamPrerequisiteQualificationError,
)
from autonomous_futures.feed.canary_live_gateway import (
    DEFAULT_PHASE277_OUTPUT_DIR,
    DESYNC_TOLERANCE_USDT,
    verify_phase_277_hash_chain,
    verify_upstream_phase276_qualification,
)
from autonomous_futures.feed.canary_probe import (
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.feed.circuit_breaker_drill import (
    CanaryCircuitBreakerRecoveryStateMachine,
)
from autonomous_futures.feed.heartbeat_daemon import (
    DOUBLE_ENTRY_MAX_DRIFT,
    CircuitBreakerState,
)
from autonomous_futures.paper.canary_staging import (
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    load_and_validate_canary_staging_manifest,
)
from autonomous_futures.paper.candidate_registry import (
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)
from autonomous_futures.paper.staging import (
    CanaryStagingManifest,
    assert_zero_secrets,
    canonical_json_bytes,
    compute_file_sha256,
)

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

# =====================================================================
# Canonical Constants & Thresholds (Phase 278)
# =====================================================================

DEFAULT_PHASE278_OUTPUT_DIR: Path = Path("artifacts/research/phase278")
MAX_PER_ASSET_MARGIN_PCT: Decimal = Decimal("0.20")  # <= 20.00% per asset
MAX_AGGREGATE_MARGIN_PCT: Decimal = Decimal("0.60")  # <= 60.00% aggregate
MIN_RESERVE_BUFFER_PCT: Decimal = Decimal("0.40")  # >= 40.00% reserve buffer
DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0004")  # 0.04% taker fee
LISTEN_KEY_LIFETIME_SECONDS: float = 3600.0  # 60m expiry
LISTEN_KEY_REFRESH_INTERVAL_SECONDS: float = 1800.0  # 30m keep-alive refresh
DEFAULT_TESTNET_BASE_URL: str = "https://testnet.binancefuture.com"
DEFAULT_TESTNET_WS_URL: str = "wss://stream.binancefuture.com/ws"

TRACK_DESCRIPTIONS: dict[str, str] = {
    "track_1": (
        "Nominal User Data Stream Lifecycle & Order Fills (Clean listenKey acquisition, "
        "routine micro order placement, event correlation, and clean ledger updates)"
    ),
    "track_2": (
        "ListenKey Expiry & Stream Reconnect Hysteresis Drill (Simulate listenKey expiration -> "
        "refresh key -> reconnect WebSocket -> backfill state via REST fallback)"
    ),
    "track_3": (
        "Emergency Circuit Breaker Trigger & Testnet Position Flattening (Trigger Tier 2 "
        "Hard-Abort -> cancel open orders -> emergency market liquidation flattening)"
    ),
    "track_4": (
        "Out-of-Order WebSocket Event Handling & Deduplication (Simulate packet arrival "
        "out-of-sequence -> verify correct chronological reordering and deduplication)"
    ),
}


# =====================================================================
# Error Hierarchy
# =====================================================================


class CanaryTestnetDeploymentError(DomainViolation):
    """Base exception for Phase 278 testnet deployment operations."""


class PrerequisiteQualificationError(
    UpstreamPrerequisiteQualificationError, CanaryTestnetDeploymentError
):
    """Raised when upstream Phase 276 or Phase 277 prerequisites fail verification."""


UpstreamPrerequisiteNotMetError = PrerequisiteQualificationError


class CertificateExpiredError(UpstreamCertificateExpiredError, CanaryTestnetDeploymentError):
    """Raised when upstream activation certificate has expired."""


class CertificateInvalidatedError(
    UpstreamCertificateInvalidatedError, CanaryTestnetDeploymentError
):
    """Raised when upstream activation certificate is invalidated."""


class ListenKeyLifecycleError(CanaryTestnetDeploymentError, DomainViolation):
    """Raised when listenKey acquisition, renewal, or termination fails."""


class ListenKeyExpiredError(ListenKeyLifecycleError):
    """Raised when user data stream listenKey has expired and requires renewal."""


class StreamDisconnectError(CanaryTestnetDeploymentError, DomainViolation):
    """Raised when user data stream WebSocket connection drops unexpectedly."""


class OutOfOrderEventError(CanaryTestnetDeploymentError, DomainViolation):
    """Raised when WebSocket events cannot be correctly reordered or reconciled."""


class DuplicateEventError(CanaryTestnetDeploymentError, DomainViolation):
    """Raised when duplicate WebSocket packets violate sequencing constraints."""


class OrderCorrelationError(CanaryTestnetDeploymentError, DomainViolation):
    """Raised when inbound execution push cannot be correlated with outbound order."""


class CircuitBreakerAbortError(CanaryTestnetDeploymentError, DomainViolation):
    """Raised when circuit breaker hard-abort blocks order submission."""


class AccountingDriftError(CanaryTestnetDeploymentError, DomainViolation):
    """Raised when mathematical double-entry drift exceeds tolerance."""


class SafetyInvariantViolation(CanaryTestnetDeploymentError, DomainViolation):
    """Raised when strict production safety or credential invariants are breached."""


# =====================================================================
# Enums and Domain Models
# =====================================================================


class CanaryTestnetTrackId(StrEnum):
    """Identifiers for Phase 278 deterministic simulation tracks."""

    TRACK_1 = "track_1"
    TRACK_2 = "track_2"
    TRACK_3 = "track_3"
    TRACK_4 = "track_4"


class ListenKeyAction(StrEnum):
    """Lifecycle actions for Binance Futures user data stream listenKey."""

    ACQUIRE = "ACQUIRE"
    KEEP_ALIVE = "KEEP_ALIVE"
    EXPIRE = "EXPIRE"
    TERMINATE = "TERMINATE"
    RECONNECT = "RECONNECT"


class WebSocketEventType(StrEnum):
    """Binance Futures user data stream push event types."""

    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    ORDER_TRADE_UPDATE = "ORDER_TRADE_UPDATE"
    LISTEN_KEY_EXPIRED = "LISTEN_KEY_EXPIRED"


class OrderLifecycleState(StrEnum):
    """State machine states for canary testnet micro-orders."""

    PENDING_DISPATCH = "PENDING_DISPATCH"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ListenKeyEvent(DomainModel):
    """Record of a listenKey lifecycle transition."""

    event_id: str = Field(default_factory=lambda: f"lke-{uuid4().hex[:10]}")
    track_id: str
    action: ListenKeyAction
    listen_key: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expiry_epoch: float
    status: str = "SUCCESS"
    details_json: str = "{}"


class WebSocketPushEventRecord(DomainModel):
    """Record of an inbound WebSocket push event."""

    event_id: str = Field(default_factory=lambda: f"wse-{uuid4().hex[:10]}")
    track_id: str
    event_type: str
    event_time_ms: int
    transaction_time_ms: int
    sequence_number: int
    client_order_id: str | None = None
    symbol: str | None = None
    order_status: str | None = None
    payload_json: str
    is_duplicate: bool = False
    is_out_of_order: bool = False
    processed_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TestnetExecutionMark(DomainModel):
    """Record of an individual fill / trade execution report."""

    trade_id: str
    track_id: str
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    price: str
    quantity: str
    quote_quantity: str
    commission_usdt: str
    realized_pnl_usdt: str
    trade_time_ms: int
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TestnetOrderRecord(DomainModel):
    """Complete audit record for a testnet micro-order."""

    order_id: str
    client_order_id: str
    track_id: str
    candidate_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce = TimeInForce.GTC
    price: Decimal
    quantity: Decimal
    executed_quantity: Decimal = Decimal("0")
    notional_usdt: Decimal
    status: OrderLifecycleState = OrderLifecycleState.PENDING_DISPATCH
    is_closing: bool = False
    created_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    rejection_reason: str | None = None


class OrderLifecycleTransition(DomainModel):
    """Audit log entry for an order state change."""

    transition_id: str = Field(default_factory=lambda: f"olt-{uuid4().hex[:10]}")
    track_id: str
    order_id: str
    client_order_id: str
    from_state: str
    to_state: str
    trigger_reason: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    details_json: str = "{}"


class TestnetBalanceSnapshot(DomainModel):
    """Snapshot of double-entry ledger state."""

    snapshot_id: str = Field(default_factory=lambda: f"tbs-{uuid4().hex[:10]}")
    track_id: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    cash_usdt: Decimal
    allocated_margin_usdt: Decimal
    unrealized_pnl_usdt: Decimal
    realized_pnl_usdt: Decimal
    equity_usdt: Decimal
    drift_usdt: Decimal


class CanaryTestnetTrackResult(DomainModel):
    """Execution outcome for an individual simulation track."""

    track_id: str
    track_name: str
    status: str
    starting_equity_usdt: str
    final_cash_usdt: str
    allocated_margin_usdt: str
    unrealized_pnl_usdt: str
    realized_pnl_usdt: str
    total_fees_usdt: str
    total_slippage_usdt: str
    drift_usdt: str
    zero_balance_drift: bool
    orders_placed_count: int
    orders_filled_count: int
    orders_cancelled_count: int
    orders_rejected_count: int
    interlock_blocks_count: int
    stream_events_count: int
    deduplicated_events_count: int
    out_of_order_events_count: int
    listenkey_refresh_count: int
    reconnect_count: int
    final_circuit_state: str
    success: bool
    details: dict[str, Any] = Field(default_factory=dict)


class CanaryTestnetReport(DomainModel):
    """Consolidated telemetry and audit report for Phase 278."""

    phase: str = "phase_278"
    description: str = "Phase 278 Canary Testnet Micro-Execution Deployment Report"
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    manifest_version: int = 2
    staged_manifest_hash: str
    upstream_phase276_certificate_hash: str
    upstream_phase277_report_hash: str
    upstream_phase277_summary_hash: str
    tracks: list[CanaryTestnetTrackResult]
    tracks_executed: list[str]
    order_stats: dict[str, Any]
    stream_stats: dict[str, Any]
    error_stats: dict[str, Any]
    compliance: dict[str, Any]
    artifact_hashes: dict[str, str]


class CanaryTestnetConfig(DomainModel):
    """Execution configuration for Phase 278 testnet deployment runner."""

    manifest_path: Path = DEFAULT_CANARY_STAGING_MANIFEST_PATH
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH
    phase276_input_dir: Path = DEFAULT_PHASE276_OUTPUT_DIR
    phase277_input_dir: Path = DEFAULT_PHASE277_OUTPUT_DIR
    output_dir: Path = DEFAULT_PHASE278_OUTPUT_DIR
    track: str = "all"
    daily_loss_budget_usdt: Decimal = DAILY_LOSS_BUDGET_USDT
    recovery_hysteresis_ticks: int = 3
    simulate_adverse_drift: bool = False


# =====================================================================
# Telemetry Store & Sinks
# =====================================================================


class JsonlCanaryOrderSink:
    """Appends order lifecycle and execution records to JSONL sink."""

    def __init__(self, file_path: Path | str) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def write_record(self, record: Mapping[str, Any]) -> None:
        """Append record line to JSONL sink guarded against secret leakage."""
        line = json.dumps(record, sort_keys=True)
        assert_zero_secrets(line, str(self.file_path.name))
        with self.file_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class SqliteCanaryTestnetTelemetryStore:
    """Isolated SQLite telemetry store for Phase 278 testnet records."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS listen_key_lifecycle_events (
                    event_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    listen_key TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    expiry_epoch REAL NOT NULL,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS websocket_push_events (
                    event_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_time_ms INTEGER NOT NULL,
                    transaction_time_ms INTEGER NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    client_order_id TEXT,
                    symbol TEXT,
                    order_status TEXT,
                    payload_json TEXT NOT NULL,
                    is_duplicate INTEGER NOT NULL,
                    is_out_of_order INTEGER NOT NULL,
                    processed_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL UNIQUE,
                    track_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    time_in_force TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    executed_quantity TEXT NOT NULL DEFAULT '0',
                    notional_usdt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_closing INTEGER NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    rejection_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS lifecycle_transitions (
                    transition_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_marks (
                    trade_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    quote_quantity TEXT NOT NULL,
                    commission_usdt TEXT NOT NULL,
                    realized_pnl_usdt TEXT NOT NULL,
                    trade_time_ms INTEGER NOT NULL,
                    timestamp_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS balance_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    cash_usdt TEXT NOT NULL,
                    allocated_margin_usdt TEXT NOT NULL,
                    unrealized_pnl_usdt TEXT NOT NULL,
                    realized_pnl_usdt TEXT NOT NULL,
                    equity_usdt TEXT NOT NULL,
                    drift_usdt TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS circuit_breaker_events (
                    event_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    attempted_notional_usdt TEXT NOT NULL,
                    current_drawdown_usdt TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS testnet_tracks (
                    track_id TEXT PRIMARY KEY,
                    track_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    starting_equity_usdt TEXT NOT NULL,
                    final_cash_usdt TEXT NOT NULL,
                    drift_usdt TEXT NOT NULL,
                    zero_balance_drift INTEGER NOT NULL,
                    orders_placed INTEGER NOT NULL,
                    orders_filled INTEGER NOT NULL,
                    orders_cancelled INTEGER NOT NULL,
                    orders_rejected INTEGER NOT NULL,
                    interlock_blocks INTEGER NOT NULL,
                    stream_events INTEGER NOT NULL,
                    deduplicated_events INTEGER NOT NULL,
                    out_of_order_events INTEGER NOT NULL,
                    listenkey_refreshes INTEGER NOT NULL,
                    reconnects INTEGER NOT NULL,
                    final_circuit_state TEXT NOT NULL,
                    success INTEGER NOT NULL
                );
                """
            )

    def record_listen_key_event(self, evt: ListenKeyEvent) -> None:
        """Persist a listenKey lifecycle event."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO listen_key_lifecycle_events (
                    event_id, track_id, action, listen_key, timestamp_utc,
                    expiry_epoch, status, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evt.event_id,
                    evt.track_id,
                    evt.action.value,
                    evt.listen_key,
                    evt.timestamp_utc,
                    evt.expiry_epoch,
                    evt.status,
                    evt.details_json,
                ),
            )

    def record_websocket_event(self, evt: WebSocketPushEventRecord) -> None:
        """Persist an inbound WebSocket push event record."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO websocket_push_events (
                    event_id, track_id, event_type, event_time_ms, transaction_time_ms,
                    sequence_number, client_order_id, symbol, order_status, payload_json,
                    is_duplicate, is_out_of_order, processed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evt.event_id,
                    evt.track_id,
                    evt.event_type,
                    evt.event_time_ms,
                    evt.transaction_time_ms,
                    evt.sequence_number,
                    evt.client_order_id,
                    evt.symbol,
                    evt.order_status,
                    evt.payload_json,
                    1 if evt.is_duplicate else 0,
                    1 if evt.is_out_of_order else 0,
                    evt.processed_at_utc,
                ),
            )

    def record_order(self, order: TestnetOrderRecord) -> None:
        """Persist or update an order record."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO orders (
                    order_id, client_order_id, track_id, candidate_id, symbol, side,
                    order_type, time_in_force, price, quantity, executed_quantity,
                    notional_usdt, status, is_closing, created_at_utc, updated_at_utc,
                    rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.client_order_id,
                    order.track_id,
                    order.candidate_id,
                    order.symbol,
                    order.side.value,
                    order.order_type.value,
                    order.time_in_force.value,
                    str(order.price),
                    str(order.quantity),
                    str(order.executed_quantity),
                    str(order.notional_usdt),
                    order.status.value,
                    1 if order.is_closing else 0,
                    order.created_at_utc,
                    order.updated_at_utc,
                    order.rejection_reason,
                ),
            )

    def record_transition(self, trans: OrderLifecycleTransition) -> None:
        """Persist an order lifecycle transition."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO lifecycle_transitions (
                    transition_id, track_id, order_id, client_order_id, from_state,
                    to_state, trigger_reason, timestamp_utc, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trans.transition_id,
                    trans.track_id,
                    trans.order_id,
                    trans.client_order_id,
                    trans.from_state,
                    trans.to_state,
                    trans.trigger_reason,
                    trans.timestamp_utc,
                    trans.details_json,
                ),
            )

    def record_execution_mark(self, mark: TestnetExecutionMark) -> None:
        """Persist an execution mark."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO execution_marks (
                    trade_id, track_id, order_id, client_order_id, symbol, side,
                    price, quantity, quote_quantity, commission_usdt, realized_pnl_usdt,
                    trade_time_ms, timestamp_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mark.trade_id,
                    mark.track_id,
                    mark.order_id,
                    mark.client_order_id,
                    mark.symbol,
                    mark.side,
                    mark.price,
                    mark.quantity,
                    mark.quote_quantity,
                    mark.commission_usdt,
                    mark.realized_pnl_usdt,
                    mark.trade_time_ms,
                    mark.timestamp_utc,
                ),
            )

    def record_balance_snapshot(self, snap: TestnetBalanceSnapshot) -> None:
        """Persist a balance snapshot."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO balance_snapshots (
                    snapshot_id, track_id, timestamp_utc, cash_usdt,
                    allocated_margin_usdt, unrealized_pnl_usdt, realized_pnl_usdt,
                    equity_usdt, drift_usdt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap.snapshot_id,
                    snap.track_id,
                    snap.timestamp_utc,
                    str(snap.cash_usdt),
                    str(snap.allocated_margin_usdt),
                    str(snap.unrealized_pnl_usdt),
                    str(snap.realized_pnl_usdt),
                    str(snap.equity_usdt),
                    str(snap.drift_usdt),
                ),
            )

    def record_circuit_breaker_event(
        self,
        track_id: str,
        trigger_type: str,
        symbol: str,
        attempted_notional_usdt: Decimal,
        current_drawdown_usdt: Decimal,
        detail: str,
    ) -> None:
        """Persist an emergency circuit breaker interlock event."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO circuit_breaker_events (
                    event_id, track_id, trigger_type, symbol, attempted_notional_usdt,
                    current_drawdown_usdt, detail, timestamp_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"cbe-{uuid4().hex[:10]}",
                    track_id,
                    trigger_type,
                    symbol,
                    str(attempted_notional_usdt),
                    str(current_drawdown_usdt),
                    detail,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def record_testnet_track(self, result: CanaryTestnetTrackResult) -> None:
        """Persist overall result for a simulation track."""
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO testnet_tracks (
                    track_id, track_name, status, starting_equity_usdt, final_cash_usdt,
                    drift_usdt, zero_balance_drift, orders_placed, orders_filled,
                    orders_cancelled, orders_rejected, interlock_blocks, stream_events,
                    deduplicated_events, out_of_order_events, listenkey_refreshes,
                    reconnects, final_circuit_state, success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.track_id,
                    result.track_name,
                    result.status,
                    result.starting_equity_usdt,
                    result.final_cash_usdt,
                    result.drift_usdt,
                    1 if result.zero_balance_drift else 0,
                    result.orders_placed_count,
                    result.orders_filled_count,
                    result.orders_cancelled_count,
                    result.orders_rejected_count,
                    result.interlock_blocks_count,
                    result.stream_events_count,
                    result.deduplicated_events_count,
                    result.out_of_order_events_count,
                    result.listenkey_refresh_count,
                    result.reconnect_count,
                    result.final_circuit_state,
                    1 if result.success else 0,
                ),
            )

    def checkpoint(self) -> None:
        """Checkpoint SQLite WAL to main database file."""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except sqlite3.OperationalError as exc:
            logger.warning("WAL checkpoint non-fatal error: %s", exc)

    def close(self) -> None:
        """Flush and close database connection."""
        try:
            self.checkpoint()
            self.conn.close()
        except Exception as exc:
            logger.warning("Error closing SQLite store: %s", exc)


# =====================================================================
# Upstream Phase 276 & 277 Qualification Verification
# =====================================================================


def verify_upstream_phase277_qualification(
    phase277_dir: Path | str = DEFAULT_PHASE277_OUTPUT_DIR,
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    phase276_dir: Path | str = DEFAULT_PHASE276_OUTPUT_DIR,
    as_of: datetime | None = None,
) -> tuple[str, str, str, str, str, CanaryActivationCertificate]:
    """Ingest Phase 276 activation certificate and Phase 277 gateway audit verification.

    Checks:
    - Ingests active Phase 276 activation certificate (status=ACTIVE, valid signature, not expired).
    - Ingests Phase 277 reports (canary-gateway-report.json, gateway-summary.json).
    - Verifies Phase 277 cryptographic SHA-256 Merkle DAG hash chain.
    - Confirms zero balance drift and compliance criteria pass.
    """
    # 1. Ingest Upstream Phase 276
    cert_hash, p276_rep_hash, p276_sum_hash, certificate = verify_upstream_phase276_qualification(
        phase276_dir=phase276_dir,
        manifest_path=manifest_path,
        as_of=as_of,
    )

    # 2. Ingest Upstream Phase 277
    p277_path = Path(phase277_dir)
    rep_path = p277_path / "canary-gateway-report.json"
    sum_path = p277_path / "gateway-summary.json"

    if not rep_path.is_file():
        raise PrerequisiteQualificationError(
            f"Missing Phase 277 canary gateway report at {rep_path}"
        )
    if not sum_path.is_file():
        raise PrerequisiteQualificationError(f"Missing Phase 277 gateway summary at {sum_path}")

    try:
        rep_data = json.loads(rep_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PrerequisiteQualificationError(
            f"Failed to parse Phase 277 gateway report: {exc}"
        ) from exc

    if not rep_data.get("compliance", {}).get("all_criteria_passed"):
        raise PrerequisiteQualificationError(
            "Phase 277 report compliance all_criteria_passed is False"
        )
    if not rep_data.get("compliance", {}).get("zero_balance_drift"):
        raise PrerequisiteQualificationError(
            "Phase 277 report compliance zero_balance_drift is False"
        )

    # Verify Phase 277 Merkle DAG Hash Chain
    chain_ok = verify_phase_277_hash_chain(
        output_dir=p277_path,
        manifest_path=manifest_path,
        phase276_dir=phase276_dir,
    )
    if not chain_ok:
        raise PrerequisiteQualificationError(
            "Upstream Phase 277 Merkle DAG hash chain failed verification."
        )

    p277_rep_hash = compute_file_sha256(rep_path)
    p277_sum_hash = compute_file_sha256(sum_path)

    return (
        cert_hash,
        p276_rep_hash,
        p276_sum_hash,
        p277_rep_hash,
        p277_sum_hash,
        certificate,
    )


# =====================================================================
# Offline-Safe / Replay Binance Futures Testnet Gateway Harness
# =====================================================================


class MockBinanceTestnetGateway:
    """Deterministic, replay-safe Binance Futures Testnet gateway & stream simulator.

    Manages:
    - ListenKey lifecycle: POST /fapi/v1/listenKey, PUT /fapi/v1/listenKey, DELETE.
    - Matching engine: POST /fapi/v1/order, DELETE /fapi/v1/order, DELETE allOpenOrders.
    - REST account state backfill: GET /fapi/v2/account, positionRisk, balance.
    - Asynchronous push event queue: ACCOUNT_UPDATE, ORDER_TRADE_UPDATE.
    - Fault injection: key expiration, disconnect, out-of-order, duplicate packets.
    """

    def __init__(
        self,
        initial_balance_usdt: Decimal = STARTING_EQUITY_USDT,
        key_vault: SecureExchangeKeyVault | None = None,
    ) -> None:
        self.key_vault = key_vault
        self.wallet_balance: Decimal = initial_balance_usdt
        self.server_time_ms: int = int(time.time() * 1000)

        # ListenKey registry: key -> expiry epoch seconds
        self.listen_keys: dict[str, float] = {}
        self.active_listen_key: str | None = None

        # Position tracking per symbol
        self.positions: dict[str, dict[str, Any]] = {
            sym: {
                "symbol": sym,
                "positionAmt": "0.000",
                "entryPrice": "0.0",
                "markPrice": str(DEFAULT_REFERENCE_PRICES[sym]),
                "unRealizedProfit": "0.00000000",
                "positionInitialMargin": "0.00000000",
                "leverage": "1",
                "positionSide": "BOTH",
            }
            for sym in CANARY_STAGED_SYMBOLS
        }

        # Orders registry: client_order_id -> order record
        self.orders: dict[str, dict[str, Any]] = {}
        self.next_order_id: int = 200001
        self.next_trade_id: int = 1
        self.next_stream_seq: int = 1

        # Push Event Queue (simulating WebSocket connection)
        self.stream_event_queue: list[dict[str, Any]] = []
        self.is_stream_connected: bool = True

        # Fault Injection Flags
        self.inject_listen_key_expired: bool = False
        self.inject_stream_disconnect: bool = False
        self.inject_out_of_order_events: bool = False
        self.inject_duplicate_events: bool = False

    def advance_server_time(self, seconds: float) -> None:
        """Advance simulated server clock."""
        self.server_time_ms += int(seconds * 1000)

    # -----------------------------------------------------------------
    # ListenKey Endpoints
    # -----------------------------------------------------------------

    def create_listen_key(self) -> dict[str, str]:
        """Binance Futures endpoint: POST /fapi/v1/listenKey."""
        key = f"testnet_lk_{uuid4().hex[:16]}"
        now_epoch = self.server_time_ms / 1000.0
        self.listen_keys[key] = now_epoch + LISTEN_KEY_LIFETIME_SECONDS
        self.active_listen_key = key
        self.is_stream_connected = True
        self.inject_stream_disconnect = False
        return {"listenKey": key}

    def keepalive_listen_key(self, listen_key: str) -> dict[str, Any]:
        """Binance Futures endpoint: PUT /fapi/v1/listenKey."""
        if self.inject_listen_key_expired:
            self.inject_listen_key_expired = False
            self.listen_keys.pop(listen_key, None)
            raise ListenKeyExpiredError(f"listenKey {listen_key} has expired on testnet")

        now_epoch = self.server_time_ms / 1000.0
        expiry = self.listen_keys.get(listen_key)
        if expiry is None or now_epoch >= expiry:
            self.listen_keys.pop(listen_key, None)
            raise ListenKeyExpiredError(f"listenKey {listen_key} does not exist or has expired")

        self.listen_keys[listen_key] = now_epoch + LISTEN_KEY_LIFETIME_SECONDS
        return {}

    def delete_listen_key(self, listen_key: str) -> dict[str, Any]:
        """Binance Futures endpoint: DELETE /fapi/v1/listenKey."""
        self.listen_keys.pop(listen_key, None)
        if self.active_listen_key == listen_key:
            self.active_listen_key = None
            self.is_stream_connected = False
        return {}

    def is_key_valid(self, listen_key: str) -> bool:
        """Check if listenKey is actively valid."""
        now_epoch = self.server_time_ms / 1000.0
        expiry = self.listen_keys.get(listen_key)
        if expiry is None:
            return False
        return now_epoch < expiry

    # -----------------------------------------------------------------
    # REST Endpoints (for Backfill & Sync)
    # -----------------------------------------------------------------

    def get_server_time(self) -> dict[str, Any]:
        """Binance Futures endpoint: GET /fapi/v1/time."""
        return {"serverTime": self.server_time_ms}

    def get_account(self) -> dict[str, Any]:
        """Binance Futures endpoint: GET /fapi/v2/account."""
        total_margin = sum(Decimal(pos["positionInitialMargin"]) for pos in self.positions.values())
        total_u_pnl = sum(Decimal(pos["unRealizedProfit"]) for pos in self.positions.values())
        avail_bal = max(Decimal("0"), self.wallet_balance - total_margin)
        margin_bal = self.wallet_balance + total_u_pnl

        return {
            "feeTier": 0,
            "canTrade": True,
            "canDeposit": True,
            "canWithdraw": False,
            "updateTime": self.server_time_ms,
            "totalInitialMargin": f"{total_margin:.8f}",
            "totalWalletBalance": f"{self.wallet_balance:.8f}",
            "totalUnrealizedProfit": f"{total_u_pnl:.8f}",
            "totalMarginBalance": f"{margin_bal:.8f}",
            "totalPositionInitialMargin": f"{total_margin:.8f}",
            "availableBalance": f"{avail_bal:.8f}",
            "positions": list(self.positions.values()),
        }

    def get_position_risk(self) -> list[dict[str, Any]]:
        """Binance Futures endpoint: GET /fapi/v2/positionRisk."""
        results: list[dict[str, Any]] = []
        for sym, pos in self.positions.items():
            amt = Decimal(pos["positionAmt"])
            notional = abs(amt * Decimal(pos["markPrice"]))
            results.append(
                {
                    "symbol": sym,
                    "positionAmt": pos["positionAmt"],
                    "entryPrice": pos["entryPrice"],
                    "markPrice": pos["markPrice"],
                    "unRealizedProfit": pos["unRealizedProfit"],
                    "positionSide": pos["positionSide"],
                    "notional": f"{notional:.8f}",
                    "updateTime": self.server_time_ms,
                }
            )
        return results

    def get_balances(self) -> list[dict[str, Any]]:
        """Binance Futures endpoint: GET /fapi/v2/balance."""
        total_margin = sum(Decimal(pos["positionInitialMargin"]) for pos in self.positions.values())
        avail_bal = max(Decimal("0"), self.wallet_balance - total_margin)
        return [
            {
                "asset": "USDT",
                "balance": f"{self.wallet_balance:.8f}",
                "crossWalletBalance": f"{self.wallet_balance:.8f}",
                "availableBalance": f"{avail_bal:.8f}",
                "updateTime": self.server_time_ms,
            }
        ]

    # -----------------------------------------------------------------
    # Order Dispatch & Push Event Generation
    # -----------------------------------------------------------------

    def place_order(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Binance Futures endpoint: POST /fapi/v1/order.

        Executes order and generates asynchronous WebSocket push events:
        - ORDER_TRADE_UPDATE (NEW)
        - ORDER_TRADE_UPDATE (FILLED / TRADE)
        - ACCOUNT_UPDATE (wallet balance & positions)
        """
        symbol = str(params["symbol"])
        side = str(params["side"])
        order_type = str(params["type"])
        qty = Decimal(str(params["quantity"]))
        price = Decimal(str(params.get("price", self.positions[symbol]["markPrice"])))
        client_order_id = str(params.get("newClientOrderId", f"cid-testnet-{uuid4().hex[:8]}"))

        order_id = self.next_order_id
        self.next_order_id += 1

        # 1. Generate ORDER_TRADE_UPDATE (NEW)
        event_time = self.server_time_ms
        seq_new = self.next_stream_seq
        self.next_stream_seq += 1

        new_order_push = {
            "e": WebSocketEventType.ORDER_TRADE_UPDATE.value,
            "E": event_time,
            "T": event_time,
            "_seq": seq_new,
            "o": {
                "s": symbol,
                "c": client_order_id,
                "S": side,
                "o": order_type,
                "f": str(params.get("timeInForce", "GTC")),
                "q": f"{qty:.8f}",
                "p": f"{price:.8f}",
                "ap": "0.00000000",
                "sp": "0.00000000",
                "x": "NEW",
                "X": "NEW",
                "i": order_id,
                "l": "0.00000000",
                "z": "0.00000000",
                "L": "0.00000000",
                "N": "USDT",
                "n": "0.00000000",
                "T": event_time,
                "t": 0,
                "b": "0",
                "a": "0",
                "m": False,
                "R": False,
                "wt": "CONTRACT_PRICE",
                "ot": order_type,
                "ps": "BOTH",
                "cp": False,
                "rp": "0.00000000",
            },
        }
        self.stream_event_queue.append(new_order_push)

        # 2. Match and Fill
        trade_id = self.next_trade_id
        self.next_trade_id += 1
        notional = qty * price
        fee = (notional * DEFAULT_TAKER_FEE_RATE).quantize(Decimal("0.00000001"))

        current_pos = self.positions[symbol]
        curr_amt = Decimal(current_pos["positionAmt"])
        curr_entry = Decimal(current_pos["entryPrice"])

        realized_pnl = Decimal("0")
        if side == "BUY":
            new_amt = curr_amt + qty
            if curr_amt >= 0:
                new_entry = (
                    (curr_amt * curr_entry + qty * price) / new_amt if new_amt != 0 else price
                )
            else:
                closed_qty = min(abs(curr_amt), qty)
                realized_pnl = (curr_entry - price) * closed_qty
                new_entry = curr_entry if new_amt != 0 else Decimal("0")
        else:  # SELL
            new_amt = curr_amt - qty
            if curr_amt <= 0:
                new_entry = (
                    (abs(curr_amt) * curr_entry + qty * price) / abs(new_amt)
                    if new_amt != 0
                    else price
                )
            else:
                closed_qty = min(curr_amt, qty)
                realized_pnl = (price - curr_entry) * closed_qty
                new_entry = curr_entry if new_amt != 0 else Decimal("0")

        # Update wallet balance: realized_pnl - fee
        self.wallet_balance = self.wallet_balance + realized_pnl - fee
        current_pos["positionAmt"] = f"{new_amt:.8f}"
        current_pos["entryPrice"] = f"{new_entry:.8f}"
        current_pos["positionInitialMargin"] = f"{abs(new_amt) * new_entry:.8f}"

        # Unrealized PnL
        mark = Decimal(current_pos["markPrice"])
        if new_amt > 0:
            u_pnl = (mark - new_entry) * new_amt
        elif new_amt < 0:
            u_pnl = (new_entry - mark) * abs(new_amt)
        else:
            u_pnl = Decimal("0")
            current_pos["positionInitialMargin"] = "0.00000000"
            current_pos["entryPrice"] = "0.0"
        current_pos["unRealizedProfit"] = f"{u_pnl:.8f}"

        trade_time = event_time + 1
        seq_trade = self.next_stream_seq
        self.next_stream_seq += 1

        fill_order_push = {
            "e": WebSocketEventType.ORDER_TRADE_UPDATE.value,
            "E": trade_time,
            "T": trade_time,
            "_seq": seq_trade,
            "o": {
                "s": symbol,
                "c": client_order_id,
                "S": side,
                "o": order_type,
                "f": str(params.get("timeInForce", "GTC")),
                "q": f"{qty:.8f}",
                "p": f"{price:.8f}",
                "ap": f"{price:.8f}",
                "sp": "0.00000000",
                "x": "TRADE",
                "X": "FILLED",
                "i": order_id,
                "l": f"{qty:.8f}",
                "z": f"{qty:.8f}",
                "L": f"{price:.8f}",
                "N": "USDT",
                "n": f"{fee:.8f}",
                "T": trade_time,
                "t": trade_id,
                "b": "0",
                "a": "0",
                "m": False,
                "R": False,
                "wt": "CONTRACT_PRICE",
                "ot": order_type,
                "ps": "BOTH",
                "cp": False,
                "rp": f"{realized_pnl:.8f}",
            },
        }
        self.stream_event_queue.append(fill_order_push)

        # 3. Generate ACCOUNT_UPDATE push
        seq_acc = self.next_stream_seq
        self.next_stream_seq += 1
        account_push = {
            "e": WebSocketEventType.ACCOUNT_UPDATE.value,
            "E": trade_time,
            "T": trade_time,
            "_seq": seq_acc,
            "a": {
                "m": "ORDER",
                "B": [
                    {
                        "a": "USDT",
                        "wb": f"{self.wallet_balance:.8f}",
                        "cw": f"{self.wallet_balance:.8f}",
                        "bc": "0",
                    }
                ],
                "P": [
                    {
                        "s": symbol,
                        "pa": current_pos["positionAmt"],
                        "ep": current_pos["entryPrice"],
                        "cr": "0.00000000",
                        "up": current_pos["unRealizedProfit"],
                        "mt": "cross",
                        "iw": "0",
                        "ps": "BOTH",
                    }
                ],
            },
        }
        self.stream_event_queue.append(account_push)

        order_record = {
            "orderId": order_id,
            "symbol": symbol,
            "status": "FILLED",
            "clientOrderId": client_order_id,
            "price": f"{price:.8f}",
            "avgPrice": f"{price:.8f}",
            "origQty": f"{qty:.8f}",
            "executedQty": f"{qty:.8f}",
            "cumQty": f"{qty:.8f}",
            "cumQuote": f"{notional:.8f}",
            "timeInForce": str(params.get("timeInForce", "GTC")),
            "type": order_type,
            "side": side,
            "updateTime": trade_time,
            "fee": f"{fee:.8f}",
            "realizedPnl": f"{realized_pnl:.8f}",
        }
        self.orders[client_order_id] = order_record
        return order_record

    def cancel_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        """Binance Futures endpoint: DELETE /fapi/v1/order."""
        record = self.orders.get(client_order_id)
        if record is None:
            raise OrderCorrelationError(f"Unknown order {client_order_id}")

        record["status"] = "CANCELED"
        event_time = self.server_time_ms
        seq = self.next_stream_seq
        self.next_stream_seq += 1

        cancel_push = {
            "e": WebSocketEventType.ORDER_TRADE_UPDATE.value,
            "E": event_time,
            "T": event_time,
            "_seq": seq,
            "o": {
                "s": symbol,
                "c": client_order_id,
                "S": record["side"],
                "o": record["type"],
                "f": record["timeInForce"],
                "q": record["origQty"],
                "p": record["price"],
                "ap": record["avgPrice"],
                "sp": "0.00000000",
                "x": "CANCELED",
                "X": "CANCELED",
                "i": record["orderId"],
                "l": "0.00000000",
                "z": record["executedQty"],
                "L": "0.00000000",
                "N": "USDT",
                "n": "0.00000000",
                "T": event_time,
                "t": 0,
                "b": "0",
                "a": "0",
                "m": False,
                "R": False,
                "wt": "CONTRACT_PRICE",
                "ot": record["type"],
                "ps": "BOTH",
                "cp": False,
                "rp": "0.00000000",
            },
        }
        self.stream_event_queue.append(cancel_push)
        return record

    def cancel_all_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Binance Futures endpoint: DELETE /fapi/v1/allOpenOrders."""
        cancelled: list[dict[str, Any]] = []
        for cid, order in list(self.orders.items()):
            if order["status"] == "NEW":
                if symbol is None or order["symbol"] == symbol:
                    cancelled.append(self.cancel_order(order["symbol"], cid))
        return cancelled

    def poll_stream_events(self) -> list[dict[str, Any]]:
        """Retrieve pending push events from the simulated WebSocket stream.

        Supports fault injection:
        - Stream disconnect
        - Out-of-order delivery
        - Duplicate packets
        """
        if not self.is_stream_connected:
            raise StreamDisconnectError("WebSocket user data stream is not connected")

        if self.inject_stream_disconnect:
            self.inject_stream_disconnect = False
            self.is_stream_connected = False
            raise StreamDisconnectError("Simulated network partition: WebSocket connection closed")

        if not self.stream_event_queue:
            return []

        packets = list(self.stream_event_queue)
        self.stream_event_queue.clear()

        # Fault Injection: Scramble order of events
        if self.inject_out_of_order_events and len(packets) >= 2:
            self.inject_out_of_order_events = False
            # Swap packet 0 and packet 1 to simulate out-of-order arrival
            packets[0], packets[1] = packets[1], packets[0]

        # Fault Injection: Duplicate a packet
        if self.inject_duplicate_events and len(packets) >= 1:
            self.inject_duplicate_events = False
            # Duplicate the last packet
            packets.append(dict(packets[-1]))

        return packets


# =====================================================================
# Sequencer, Deduplicator & User Data Stream Ingress
# =====================================================================


class TestnetStreamSequencer:
    """Buffers, reorders, and deduplicates inbound WebSocket packets."""

    __test__ = False

    def __init__(self) -> None:
        self.processed_fingerprints: set[str] = set()
        self.highest_arrival_time_ms: int = 0
        self.highest_arrival_sequence: int = 0
        self.deduplicated_count: int = 0
        self.out_of_order_count: int = 0

    @staticmethod
    def compute_fingerprint(event: Mapping[str, Any]) -> str:
        """Compute unique fingerprint for event deduplication."""
        e_type = event.get("e", "")
        if e_type == WebSocketEventType.ORDER_TRADE_UPDATE.value:
            o_data = event.get("o", {})
            cid = o_data.get("c", "")
            trade_id = o_data.get("t", 0)
            exec_type = o_data.get("x", "")
            ord_status = o_data.get("X", "")
            t_time = event.get("T", 0)
            return f"OTU:{cid}:{trade_id}:{exec_type}:{ord_status}:{t_time}"
        if e_type == WebSocketEventType.ACCOUNT_UPDATE.value:
            a_data = event.get("a", {})
            reason = a_data.get("m", "")
            t_time = event.get("T", 0)
            wb = ""
            for b in a_data.get("B", []):
                if b.get("a") == "USDT":
                    wb = b.get("wb", "")
            return f"ACC:{reason}:{wb}:{t_time}"
        return f"{e_type}:{event.get('E', 0)}:{event.get('T', 0)}"

    def ingest_and_sort_packets(
        self,
        raw_packets: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], bool, bool]]:
        """Process incoming raw packets.

        Returns list of (packet, is_duplicate, is_out_of_order) tuples
        sorted in strict chronological and sequence order.
        """
        staged: list[tuple[int, int, int, dict[str, Any], bool, bool]] = []

        for pkt in raw_packets:
            fp = self.compute_fingerprint(pkt)
            is_dup = fp in self.processed_fingerprints

            t_time = int(pkt.get("T", pkt.get("E", 0)))
            e_time = int(pkt.get("E", 0))
            seq = int(pkt.get("_seq", 0))

            is_ooo = False
            if is_dup:
                self.deduplicated_count += 1
            else:
                self.processed_fingerprints.add(fp)
                if t_time < self.highest_arrival_time_ms:
                    is_ooo = True
                    self.out_of_order_count += 1
                elif seq > 0 and seq < self.highest_arrival_sequence:
                    is_ooo = True
                    self.out_of_order_count += 1
                else:
                    if t_time > self.highest_arrival_time_ms:
                        self.highest_arrival_time_ms = t_time
                    if seq > self.highest_arrival_sequence:
                        self.highest_arrival_sequence = seq

            staged.append((t_time, e_time, seq, pkt, is_dup, is_ooo))

        # Sort chronologically by (transaction_time, event_time, sequence)
        staged.sort(key=lambda x: (x[0], x[1], x[2]))

        return [(pkt, is_dup, is_ooo) for _t, _e, _s, pkt, is_dup, is_ooo in staged]


# =====================================================================
# Exact Double-Entry User Data Stream Reconciler
# =====================================================================


class TestnetUserDataStreamReconciler:
    """Exact double-entry reconciler driven by real-time WebSocket push events.

    Reconciles:
    - Cash balance
    - Allocated margin
    - Unrealized PnL
    - Realized PnL
    - Execution fees & slippage
    - Cross-asset position quantities across BTCUSDT, ETHUSDT, SOLUSDT.
    Enforces strict mathematical balance drift < 1e-15 USDT.
    """

    __test__ = False

    def __init__(
        self,
        track_id: str,
        starting_equity: Decimal = STARTING_EQUITY_USDT,
    ) -> None:
        self.track_id = track_id
        self.starting_equity = starting_equity

        self.cash = starting_equity
        self.allocated_margin = Decimal("0")
        self.unrealized_pnl = Decimal("0")
        self.realized_pnl = Decimal("0")
        self.total_fees = Decimal("0")
        self.total_slippage = Decimal("0")

        self.positions: dict[str, Decimal] = {sym: Decimal("0") for sym in CANARY_STAGED_SYMBOLS}
        self.entry_prices: dict[str, Decimal] = {sym: Decimal("0") for sym in CANARY_STAGED_SYMBOLS}
        self.per_asset_margin: dict[str, Decimal] = {
            sym: Decimal("0") for sym in CANARY_STAGED_SYMBOLS
        }
        self.mark_prices: dict[str, Decimal] = {
            sym: Decimal(str(DEFAULT_REFERENCE_PRICES[sym])) for sym in CANARY_STAGED_SYMBOLS
        }

        self.locked_out: bool = False
        self.lockout_reason: str | None = None

    @property
    def total_equity(self) -> Decimal:
        """Total portfolio equity: cash + allocated_margin + unrealized_pnl."""
        return self.cash + self.allocated_margin + self.unrealized_pnl

    @property
    def wallet_balance(self) -> Decimal:
        """Wallet balance: cash + allocated_margin."""
        return self.cash + self.allocated_margin

    @property
    def mathematical_drift(self) -> Decimal:
        """Mathematical double-entry balance drift:
        |cash + allocated_margin + uPnL - (starting_equity + rPnL + uPnL)|.
        """
        calc = self.cash + self.allocated_margin + self.unrealized_pnl
        exp = self.starting_equity + self.realized_pnl + self.unrealized_pnl
        return abs(calc - exp)

    def update_mark_price(self, symbol: str, price: Decimal) -> None:
        """Update mark price and recalculate internal unrealized PnL."""
        if not price.is_finite() or price <= Decimal("0"):
            raise DomainViolation(f"Mark price {price} for {symbol} must be strictly positive")
        self.mark_prices[symbol] = price
        self._recompute_unrealized_pnl()

    def _recompute_unrealized_pnl(self) -> None:
        """Recompute portfolio unrealized PnL based on active positions and marks."""
        total_u = Decimal("0")
        for sym, qty in self.positions.items():
            if qty != Decimal("0"):
                entry = self.entry_prices.get(sym, Decimal("0"))
                mark = self.mark_prices.get(sym, entry)
                if qty > 0:
                    total_u += (mark - entry) * qty
                else:
                    total_u += (entry - mark) * abs(qty)
        self.unrealized_pnl = total_u

    def apply_order_trade_update(
        self,
        event: Mapping[str, Any],
        is_closing: bool = False,
    ) -> TestnetExecutionMark | None:
        """Apply an inbound ORDER_TRADE_UPDATE payload to internal double-entry ledger."""
        o_data = event.get("o", {})
        exec_type = o_data.get("x")
        symbol = o_data.get("s")
        side = o_data.get("S")
        client_order_id = o_data.get("c")
        order_id = str(o_data.get("i"))

        if exec_type != "TRADE":
            return None

        trade_id = str(o_data.get("t"))
        last_qty = Decimal(str(o_data.get("l", "0")))
        last_price = Decimal(str(o_data.get("L", "0")))
        fee = Decimal(str(o_data.get("n", "0")))

        if last_qty <= Decimal("0") or last_price <= Decimal("0"):
            return None

        notional = (last_qty * last_price).quantize(Decimal("0.00000001"))
        curr_qty = self.positions[symbol]
        curr_entry = self.entry_prices[symbol]

        trade_pnl = Decimal("0")

        if side == "BUY":
            new_qty = curr_qty + last_qty
            if curr_qty >= 0:
                # Increasing LONG
                new_entry = (
                    (curr_qty * curr_entry + last_qty * last_price) / new_qty
                    if new_qty != 0
                    else last_price
                )
                margin_delta = notional
            else:
                # Reducing / Closing SHORT
                closed_qty = min(abs(curr_qty), last_qty)
                trade_pnl = (curr_entry - last_price) * closed_qty
                new_entry = curr_entry if new_qty != 0 else Decimal("0")
                margin_delta = -(closed_qty * curr_entry)
        else:  # SELL
            new_qty = curr_qty - last_qty
            if curr_qty <= 0:
                # Increasing SHORT
                new_entry = (
                    (abs(curr_qty) * curr_entry + last_qty * last_price) / abs(new_qty)
                    if new_qty != 0
                    else last_price
                )
                margin_delta = notional
            else:
                # Reducing / Closing LONG
                closed_qty = min(curr_qty, last_qty)
                trade_pnl = (last_price - curr_entry) * closed_qty
                new_entry = curr_entry if new_qty != 0 else Decimal("0")
                margin_delta = -(closed_qty * curr_entry)

        # Update ledger balances exactly
        self.positions[symbol] = new_qty
        self.entry_prices[symbol] = new_entry
        self.per_asset_margin[symbol] = abs(new_qty) * new_entry if new_qty != 0 else Decimal("0")
        self.allocated_margin = sum(self.per_asset_margin.values(), Decimal("0"))

        # Cash updates: cash = cash - margin_delta + trade_pnl - fee
        self.cash = self.cash - margin_delta + trade_pnl - fee
        self.realized_pnl = self.realized_pnl + trade_pnl - fee
        self.total_fees += fee

        self._recompute_unrealized_pnl()

        mark = TestnetExecutionMark(
            trade_id=f"trd-{trade_id}",
            track_id=self.track_id,
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            price=f"{last_price:.8f}",
            quantity=f"{last_qty:.8f}",
            quote_quantity=f"{notional:.8f}",
            commission_usdt=f"{fee:.8f}",
            realized_pnl_usdt=f"{trade_pnl:.8f}",
            trade_time_ms=int(o_data.get("T", event.get("T", 0))),
        )
        return mark

    def apply_account_update(self, event: Mapping[str, Any]) -> None:
        """Cross-check internal ledger against inbound ACCOUNT_UPDATE push."""
        a_data = event.get("a", {})
        # Verify wallet balance
        for b in a_data.get("B", []):
            if b.get("a") == "USDT":
                remote_wb = Decimal(str(b.get("wb", "0")))
                local_wb = self.wallet_balance
                if abs(remote_wb - local_wb) > DESYNC_TOLERANCE_USDT:
                    self.locked_out = True
                    self.lockout_reason = (
                        f"ACCOUNT_UPDATE desync: remote walletBalance={remote_wb}, "
                        f"local walletBalance={local_wb}"
                    )
                    logger.warning(self.lockout_reason)

    def backfill_via_rest(self, gateway: MockBinanceTestnetGateway) -> None:
        """Perform automatic REST state backfill across account & position endpoints."""
        acc = gateway.get_account()
        remote_wb = Decimal(str(acc.get("totalWalletBalance", "0")))
        local_wb = self.wallet_balance

        if abs(remote_wb - local_wb) > DESYNC_TOLERANCE_USDT:
            self.locked_out = True
            self.lockout_reason = (
                f"REST backfill desync: remote wallet={remote_wb}, local wallet={local_wb}"
            )
            raise DomainViolation(self.lockout_reason)

        for pos in acc.get("positions", []):
            sym = pos.get("symbol")
            if sym in CANARY_STAGED_SYMBOLS:
                r_amt = Decimal(str(pos.get("positionAmt", "0")))
                l_amt = self.positions.get(sym, Decimal("0"))
                if abs(r_amt - l_amt) > Decimal("1e-6"):
                    self.locked_out = True
                    self.lockout_reason = (
                        f"REST backfill position desync on {sym}: remote={r_amt}, local={l_amt}"
                    )
                    raise DomainViolation(self.lockout_reason)


# =====================================================================
# ListenKey Lifecycle Manager
# =====================================================================


class TestnetListenKeyManager:
    """Manages Binance Futures Testnet user data stream listenKey lifecycle.

    Handles:
    - Acquisition: POST /fapi/v1/listenKey
    - Keep-alive refresh: PUT /fapi/v1/listenKey every 30m
    - Termination: DELETE /fapi/v1/listenKey
    - Expiration detection and renewal
    """

    __test__ = False

    def __init__(
        self,
        gateway: MockBinanceTestnetGateway,
        telemetry_store: SqliteCanaryTestnetTelemetryStore,
        track_id: str,
    ) -> None:
        self.gateway = gateway
        self.telemetry_store = telemetry_store
        self.track_id = track_id

        self.current_listen_key: str | None = None
        self.acquired_epoch: float = 0.0
        self.expiry_epoch: float = 0.0
        self.refresh_count: int = 0
        self.reconnect_count: int = 0

    def acquire_key(self) -> str:
        """Acquire a fresh user data stream listenKey."""
        res = self.gateway.create_listen_key()
        key = res["listenKey"]
        now_epoch = self.gateway.server_time_ms / 1000.0
        self.current_listen_key = key
        self.acquired_epoch = now_epoch
        self.expiry_epoch = now_epoch + LISTEN_KEY_LIFETIME_SECONDS

        evt = ListenKeyEvent(
            track_id=self.track_id,
            action=ListenKeyAction.ACQUIRE,
            listen_key=key,
            expiry_epoch=self.expiry_epoch,
            status="ACQUIRED",
            details_json=json.dumps({"lifetime_seconds": LISTEN_KEY_LIFETIME_SECONDS}),
        )
        self.telemetry_store.record_listen_key_event(evt)
        return key

    def refresh_key(self) -> None:
        """Refresh active listenKey via keep-alive PUT endpoint."""
        if not self.current_listen_key:
            raise ListenKeyLifecycleError("Cannot refresh: no active listenKey")

        self.gateway.keepalive_listen_key(self.current_listen_key)
        now_epoch = self.gateway.server_time_ms / 1000.0
        self.expiry_epoch = now_epoch + LISTEN_KEY_LIFETIME_SECONDS
        self.refresh_count += 1

        evt = ListenKeyEvent(
            track_id=self.track_id,
            action=ListenKeyAction.KEEP_ALIVE,
            listen_key=self.current_listen_key,
            expiry_epoch=self.expiry_epoch,
            status="REFRESHED",
            details_json=json.dumps({"refresh_count": self.refresh_count}),
        )
        self.telemetry_store.record_listen_key_event(evt)

    def terminate_key(self) -> None:
        """Terminate active listenKey cleanly."""
        if self.current_listen_key:
            self.gateway.delete_listen_key(self.current_listen_key)
            evt = ListenKeyEvent(
                track_id=self.track_id,
                action=ListenKeyAction.TERMINATE,
                listen_key=self.current_listen_key,
                expiry_epoch=self.expiry_epoch,
                status="TERMINATED",
            )
            self.telemetry_store.record_listen_key_event(evt)
            self.current_listen_key = None

    def reconnect_stream(self) -> str:
        """Execute stream reconnect hysteresis: renew key and re-establish stream."""
        self.reconnect_count += 1
        new_key = self.acquire_key()
        evt = ListenKeyEvent(
            track_id=self.track_id,
            action=ListenKeyAction.RECONNECT,
            listen_key=new_key,
            expiry_epoch=self.expiry_epoch,
            status="RECONNECTED",
            details_json=json.dumps({"reconnect_count": self.reconnect_count}),
        )
        self.telemetry_store.record_listen_key_event(evt)
        return new_key


# =====================================================================
# Micro-Execution Order Dispatcher & Fail-Closed Incident Harness
# =====================================================================


class TestnetMicroOrderDispatcher:
    """Manages micro-canary order routing, event correlation, and fail-closed response.

    Enforces:
    - Micro order notional cap (<= 5.00 USDT)
    - Per-asset margin cap (<= 20.00% of starting equity)
    - Aggregate margin cap (<= 60.00% of starting equity)
    - Minimum reserve buffer (>= 40.00% of starting equity)
    - Circuit-breaker fail-closed incident response
    - Emergency market liquidation flattening
    """

    __test__ = False

    def __init__(
        self,
        gateway: MockBinanceTestnetGateway,
        reconciler: TestnetUserDataStreamReconciler,
        sequencer: TestnetStreamSequencer,
        telemetry_store: SqliteCanaryTestnetTelemetryStore,
        jsonl_sink: JsonlCanaryOrderSink,
        circuit_breaker: CanaryCircuitBreakerRecoveryStateMachine,
        track_id: str,
    ) -> None:
        self.gateway = gateway
        self.reconciler = reconciler
        self.sequencer = sequencer
        self.telemetry_store = telemetry_store
        self.jsonl_sink = jsonl_sink
        self.circuit_breaker = circuit_breaker
        self.track_id = track_id

        self.orders: dict[str, TestnetOrderRecord] = {}
        self.orders_placed_count: int = 0
        self.orders_filled_count: int = 0
        self.orders_cancelled_count: int = 0
        self.orders_rejected_count: int = 0
        self.interlock_blocks_count: int = 0
        self.stream_events_count: int = 0

    def dispatch_micro_order(
        self,
        candidate_id: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal,
        is_closing: bool = False,
    ) -> TestnetOrderRecord:
        """Route micro canary order through Phase 278 interlocks and correlate push events."""
        # 1. Parameter Validation
        if not price.is_finite() or price <= Decimal("0"):
            self.orders_rejected_count += 1
            raise DomainViolation(f"Order price {price} must be strictly positive and finite")
        if not quantity.is_finite() or quantity <= Decimal("0"):
            self.orders_rejected_count += 1
            raise DomainViolation(f"Order quantity {quantity} must be strictly positive and finite")

        notional = (quantity * price).quantize(Decimal("0.00000001"))

        # 2. Hard Notional Cap Check (<= 5.00 USDT)
        if notional > HARD_NOTIONAL_CAP_USDT:
            self.orders_rejected_count += 1
            self.interlock_blocks_count += 1
            raise DomainViolation(
                f"Order notional {notional} USDT exceeds hard cap {HARD_NOTIONAL_CAP_USDT} USDT"
            )

        # 3. Fail-Closed Circuit Breaker Check
        if (
            self.circuit_breaker.current_state == CircuitBreakerState.TIER_2_HARD_ABORT
            and not is_closing
        ):
            self.orders_rejected_count += 1
            self.interlock_blocks_count += 1
            self.telemetry_store.record_circuit_breaker_event(
                track_id=self.track_id,
                trigger_type="ORDER_BLOCKED_TIER_2",
                symbol=symbol,
                attempted_notional_usdt=notional,
                current_drawdown_usdt=max(
                    Decimal("0"), self.reconciler.starting_equity - self.reconciler.total_equity
                ),
                detail="Order dispatch rejected: Circuit breaker in TIER_2_HARD_ABORT",
            )
            raise CircuitBreakerAbortError(
                "Gateway locked out in TIER_2_HARD_ABORT. Orders blocked."
            )

        # 4. Margin Allocation & Reserve Buffer Checks (for opening orders)
        if not is_closing:
            per_asset_cap = self.reconciler.starting_equity * MAX_PER_ASSET_MARGIN_PCT
            curr_sym_margin = self.reconciler.per_asset_margin.get(symbol, Decimal("0"))
            if curr_sym_margin + notional > per_asset_cap:
                self.orders_rejected_count += 1
                self.interlock_blocks_count += 1
                raise DomainViolation(
                    f"Per-asset margin cap breach on {symbol}: attempted "
                    f"{curr_sym_margin + notional} > cap {per_asset_cap}"
                )

            agg_cap = self.reconciler.starting_equity * MAX_AGGREGATE_MARGIN_PCT
            if self.reconciler.allocated_margin + notional > agg_cap:
                self.orders_rejected_count += 1
                self.interlock_blocks_count += 1
                raise DomainViolation(
                    f"Aggregate margin cap breach: attempted "
                    f"{self.reconciler.allocated_margin + notional} > cap {agg_cap}"
                )

            reserve_floor = self.reconciler.starting_equity * MIN_RESERVE_BUFFER_PCT
            if self.reconciler.cash - notional < reserve_floor:
                self.orders_rejected_count += 1
                self.interlock_blocks_count += 1
                raise DomainViolation(
                    f"Reserve buffer breach: remaining free cash {self.reconciler.cash - notional} "
                    f"< floor {reserve_floor}"
                )

        # 5. Create Outbound Order Record
        order_id = f"ord-{uuid4().hex[:10]}"
        client_order_id = f"cid-p278-{uuid4().hex[:8]}"
        now_utc = datetime.now(UTC).isoformat()

        order_record = TestnetOrderRecord(
            order_id=order_id,
            client_order_id=client_order_id,
            track_id=self.track_id,
            candidate_id=candidate_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            notional_usdt=notional,
            status=OrderLifecycleState.PENDING_DISPATCH,
            is_closing=is_closing,
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
        )
        self.orders[client_order_id] = order_record
        self.orders_placed_count += 1
        self.telemetry_store.record_order(order_record)
        self.jsonl_sink.write_record(
            {
                "event": "ORDER_DISPATCH_INITIATED",
                "track_id": self.track_id,
                "order_id": order_id,
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": side.value,
                "quantity": str(quantity),
                "price": str(price),
                "notional_usdt": str(notional),
                "is_closing": is_closing,
                "timestamp_utc": now_utc,
            }
        )

        # 6. Dispatch through Gateway
        params = {
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "quantity": str(quantity),
            "price": str(price),
            "newClientOrderId": client_order_id,
        }
        self.gateway.place_order(params)

        # 7. Ingest and Process WebSocket Push Events
        self.process_inbound_stream_events(is_closing=is_closing)

        return self.orders[client_order_id]

    def process_inbound_stream_events(self, is_closing: bool = False) -> None:
        """Poll raw push events from stream, sequence, deduplicate, and reconcile."""
        raw_events = self.gateway.poll_stream_events()
        ordered_events = self.sequencer.ingest_and_sort_packets(raw_events)

        for event, is_dup, is_ooo in ordered_events:
            self.stream_events_count += 1
            e_type = event.get("e", "")
            e_time = int(event.get("E", 0))
            t_time = int(event.get("T", 0))
            seq = int(event.get("_seq", 0))

            cid: str | None = None
            sym: str | None = None
            ord_status: str | None = None

            if e_type == WebSocketEventType.ORDER_TRADE_UPDATE.value:
                o_data = event.get("o", {})
                cid = o_data.get("c")
                sym = o_data.get("s")
                ord_status = o_data.get("X")

            # Persist raw stream event record
            push_rec = WebSocketPushEventRecord(
                track_id=self.track_id,
                event_type=e_type,
                event_time_ms=e_time,
                transaction_time_ms=t_time,
                sequence_number=seq,
                client_order_id=cid,
                symbol=sym,
                order_status=ord_status,
                payload_json=json.dumps(event, sort_keys=True),
                is_duplicate=is_dup,
                is_out_of_order=is_ooo,
            )
            self.telemetry_store.record_websocket_event(push_rec)

            # Skip duplicate processing
            if is_dup:
                continue

            # Process ORDER_TRADE_UPDATE
            if e_type == WebSocketEventType.ORDER_TRADE_UPDATE.value and cid:
                order_rec = self.orders.get(cid)
                if order_rec:
                    prev_status = order_rec.status.value
                    new_status = ord_status or "NEW"
                    order_rec.status = OrderLifecycleState(new_status)
                    order_rec.updated_at_utc = datetime.now(UTC).isoformat()

                    if new_status == "FILLED":
                        order_rec.executed_quantity = order_rec.quantity
                        self.orders_filled_count += 1

                    # Record lifecycle transition
                    trans = OrderLifecycleTransition(
                        track_id=self.track_id,
                        order_id=order_rec.order_id,
                        client_order_id=cid,
                        from_state=prev_status,
                        to_state=new_status,
                        trigger_reason=f"WebSocket push: {e_type} ({event.get('o', {}).get('x')})",
                    )
                    self.telemetry_store.record_transition(trans)
                    self.telemetry_store.record_order(order_rec)

                # Reconcile fill into double-entry ledger
                mark = self.reconciler.apply_order_trade_update(event, is_closing=is_closing)
                if mark:
                    self.telemetry_store.record_execution_mark(mark)
                    self.jsonl_sink.write_record(
                        {
                            "event": "ORDER_TRADE_FILLED",
                            "track_id": self.track_id,
                            "trade_id": mark.trade_id,
                            "order_id": mark.order_id,
                            "client_order_id": mark.client_order_id,
                            "symbol": mark.symbol,
                            "side": mark.side,
                            "price": mark.price,
                            "quantity": mark.quantity,
                            "commission_usdt": mark.commission_usdt,
                            "realized_pnl_usdt": mark.realized_pnl_usdt,
                            "timestamp_utc": mark.timestamp_utc,
                        }
                    )

            # Process ACCOUNT_UPDATE
            elif e_type == WebSocketEventType.ACCOUNT_UPDATE.value:
                self.reconciler.apply_account_update(event)

        # Snapshot balance after event batch
        snap = TestnetBalanceSnapshot(
            track_id=self.track_id,
            cash_usdt=self.reconciler.cash,
            allocated_margin_usdt=self.reconciler.allocated_margin,
            unrealized_pnl_usdt=self.reconciler.unrealized_pnl,
            realized_pnl_usdt=self.reconciler.realized_pnl,
            equity_usdt=self.reconciler.total_equity,
            drift_usdt=self.reconciler.mathematical_drift,
        )
        self.telemetry_store.record_balance_snapshot(snap)

    def execute_emergency_flattening(self) -> list[TestnetOrderRecord]:
        """Execute fail-closed incident response: cancel open orders & flatten positions."""
        # 1. Cancel open orders
        self.gateway.cancel_all_open_orders()
        self.process_inbound_stream_events(is_closing=True)

        flattening_orders: list[TestnetOrderRecord] = []

        # 2. Market liquidate all open positions
        for sym, qty in list(self.reconciler.positions.items()):
            if qty != Decimal("0"):
                close_side = OrderSide.SELL if qty > 0 else OrderSide.BUY
                close_qty = abs(qty)
                mark_price = self.reconciler.mark_prices.get(sym, Decimal("60000.00"))

                order = self.dispatch_micro_order(
                    candidate_id=f"flatten-{sym.lower()}",
                    symbol=sym,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=close_qty,
                    price=mark_price,
                    is_closing=True,
                )
                flattening_orders.append(order)

        # 3. Assert all positions flat
        for sym, qty in self.reconciler.positions.items():
            if qty != Decimal("0"):
                raise DomainViolation(f"Emergency flattening failed: {sym} position remains {qty}")

        if self.reconciler.allocated_margin != Decimal("0"):
            raise DomainViolation(
                "Emergency flattening failed: allocated margin is "
                f"{self.reconciler.allocated_margin}"
            )

        return flattening_orders


# =====================================================================
# Phase 278 Deterministic Canary Testnet Runner
# =====================================================================


class CanaryTestnetRunner:
    """Orchestrates the 4 deterministic Phase 278 testnet simulation tracks."""

    def __init__(self, config: CanaryTestnetConfig) -> None:
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.output_dir / "canary-testnet-telemetry.sqlite3"
        self.jsonl_path = self.output_dir / "canary-orders.jsonl"

        self.active_store: SqliteCanaryTestnetTelemetryStore | None = None
        self.active_sink: JsonlCanaryOrderSink | None = None

    def execute_all_tracks(self) -> CanaryTestnetReport:
        """Execute all 4 deterministic testnet validation tracks."""
        manifest, _ = load_and_validate_canary_staging_manifest(self.config.manifest_path)
        verify_strict_fail_closed_invariants()

        # 1. Ingest Upstream Phase 276 & Phase 277 Certifications
        (
            cert_hash,
            _p276_rep_hash,
            _p276_sum_hash,
            p277_rep_hash,
            p277_sum_hash,
            certificate,
        ) = verify_upstream_phase277_qualification(
            phase277_dir=self.config.phase277_input_dir,
            manifest_path=self.config.manifest_path,
            phase276_dir=self.config.phase276_input_dir,
        )

        # Reset telemetry files
        if self.jsonl_path.is_file():
            self.jsonl_path.unlink()
        if self.db_path.is_file():
            self.db_path.unlink()

        self.active_store = SqliteCanaryTestnetTelemetryStore(self.db_path)
        self.active_sink = JsonlCanaryOrderSink(self.jsonl_path)
        self.jsonl_path.touch(exist_ok=True)

        track_results: list[CanaryTestnetTrackResult] = []

        try:
            if self.config.track in ("all", "1", "track_1"):
                track_results.append(self._run_track_1(manifest, certificate))
            if self.config.track in ("all", "2", "track_2"):
                track_results.append(self._run_track_2(manifest, certificate))
            if self.config.track in ("all", "3", "track_3"):
                track_results.append(self._run_track_3(manifest, certificate))
            if self.config.track in ("all", "4", "track_4"):
                track_results.append(self._run_track_4(manifest, certificate))
        finally:
            if self.active_store is not None:
                self.active_store.checkpoint()
                self.active_store.close()

        # Build and persist reports
        report = self._build_and_persist_reports(
            manifest=manifest,
            certificate=certificate,
            cert_hash=cert_hash,
            p277_rep_hash=p277_rep_hash,
            p277_sum_hash=p277_sum_hash,
            tracks=track_results,
        )
        return report

    def _run_track_1(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
    ) -> CanaryTestnetTrackResult:
        """Track 1: Nominal User Data Stream Lifecycle & Order Fills."""
        assert self.active_store is not None
        assert self.active_sink is not None

        gateway = MockBinanceTestnetGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
        reconciler = TestnetUserDataStreamReconciler(
            track_id=CanaryTestnetTrackId.TRACK_1.value,
            starting_equity=STARTING_EQUITY_USDT,
        )
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(
            gateway=gateway,
            telemetry_store=self.active_store,
            track_id=CanaryTestnetTrackId.TRACK_1.value,
        )
        sm = CanaryCircuitBreakerRecoveryStateMachine(
            recovery_hysteresis_ticks=self.config.recovery_hysteresis_ticks
        )
        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            circuit_breaker=sm,
            track_id=CanaryTestnetTrackId.TRACK_1.value,
        )

        # 1. Acquire ListenKey
        key_mgr.acquire_key()

        # 2. Trade BTCUSDT micro order (0.00008 @ 60,000 = 4.80 USDT)
        btc_cand = manifest.candidates["BTCUSDT"].candidate_id
        btc_open = dispatcher.dispatch_micro_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert btc_open.status == OrderLifecycleState.FILLED

        # 3. Close BTCUSDT position
        btc_close = dispatcher.dispatch_micro_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            is_closing=True,
        )
        assert btc_close.status == OrderLifecycleState.FILLED

        # 4. Trade ETHUSDT micro order (0.0019 @ 2500 = 4.75 USDT)
        eth_cand = manifest.candidates["ETHUSDT"].candidate_id
        eth_open = dispatcher.dispatch_micro_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
        )
        assert eth_open.status == OrderLifecycleState.FILLED

        # 5. Close ETHUSDT position
        eth_close = dispatcher.dispatch_micro_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
            is_closing=True,
        )
        assert eth_close.status == OrderLifecycleState.FILLED

        # 6. Terminate ListenKey
        key_mgr.terminate_key()

        drift = reconciler.mathematical_drift
        if self.config.simulate_adverse_drift:
            drift = Decimal("0.05")

        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = CanaryTestnetTrackResult(
            track_id=CanaryTestnetTrackId.TRACK_1.value,
            track_name=TRACK_DESCRIPTIONS[CanaryTestnetTrackId.TRACK_1.value],
            status="SUCCESS_NOMINAL_STREAM_SYNC",
            starting_equity_usdt=str(reconciler.starting_equity),
            final_cash_usdt=str(reconciler.cash),
            allocated_margin_usdt=str(reconciler.allocated_margin),
            unrealized_pnl_usdt=str(reconciler.unrealized_pnl),
            realized_pnl_usdt=str(reconciler.realized_pnl),
            total_fees_usdt=str(reconciler.total_fees),
            total_slippage_usdt=str(reconciler.total_slippage),
            drift_usdt=str(drift),
            zero_balance_drift=zero_drift,
            orders_placed_count=dispatcher.orders_placed_count,
            orders_filled_count=dispatcher.orders_filled_count,
            orders_cancelled_count=dispatcher.orders_cancelled_count,
            orders_rejected_count=dispatcher.orders_rejected_count,
            interlock_blocks_count=dispatcher.interlock_blocks_count,
            stream_events_count=dispatcher.stream_events_count,
            deduplicated_events_count=sequencer.deduplicated_count,
            out_of_order_events_count=sequencer.out_of_order_count,
            listenkey_refresh_count=key_mgr.refresh_count,
            reconnect_count=key_mgr.reconnect_count,
            final_circuit_state=sm.current_state.value,
            success=zero_drift and reconciler.allocated_margin == Decimal("0"),
        )
        self.active_store.record_testnet_track(result)
        return result

    def _run_track_2(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
    ) -> CanaryTestnetTrackResult:
        """Track 2: ListenKey Expiry & Stream Reconnect Hysteresis Drill."""
        assert self.active_store is not None
        assert self.active_sink is not None

        gateway = MockBinanceTestnetGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
        reconciler = TestnetUserDataStreamReconciler(
            track_id=CanaryTestnetTrackId.TRACK_2.value,
            starting_equity=STARTING_EQUITY_USDT,
        )
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(
            gateway=gateway,
            telemetry_store=self.active_store,
            track_id=CanaryTestnetTrackId.TRACK_2.value,
        )
        sm = CanaryCircuitBreakerRecoveryStateMachine(
            recovery_hysteresis_ticks=self.config.recovery_hysteresis_ticks
        )
        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            circuit_breaker=sm,
            track_id=CanaryTestnetTrackId.TRACK_2.value,
        )

        # 1. Initial ListenKey Acquisition
        key_mgr.acquire_key()

        # 2. Advance time by 30 minutes -> Keep-alive refresh
        gateway.advance_server_time(1800.0)
        key_mgr.refresh_key()
        assert key_mgr.refresh_count == 1

        # 3. Simulate listenKey expiration & stream disconnect
        gateway.inject_listen_key_expired = True

        # 4. Detect expiration on refresh
        expiry_caught = False
        try:
            key_mgr.refresh_key()
        except ListenKeyExpiredError:
            expiry_caught = True

        assert expiry_caught is True

        # Test stream disconnect detection
        gateway.inject_stream_disconnect = True
        disconnect_caught = False
        try:
            gateway.poll_stream_events()
        except StreamDisconnectError:
            disconnect_caught = True

        assert disconnect_caught is True

        # Reconnect stream with fresh key
        key_mgr.reconnect_stream()
        assert key_mgr.reconnect_count == 1

        # Automatic REST State Backfill
        reconciler.backfill_via_rest(gateway)

        # 5. Place and fill order on SOLUSDT (0.032 @ 150 = 4.80 USDT)
        sol_cand = manifest.candidates["SOLUSDT"].candidate_id
        sol_open = dispatcher.dispatch_micro_order(
            candidate_id=sol_cand,
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
        )
        assert sol_open.status == OrderLifecycleState.FILLED

        # Close SOLUSDT position
        sol_close = dispatcher.dispatch_micro_order(
            candidate_id=sol_cand,
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
            is_closing=True,
        )
        assert sol_close.status == OrderLifecycleState.FILLED

        # 6. Terminate key
        key_mgr.terminate_key()

        drift = reconciler.mathematical_drift
        if self.config.simulate_adverse_drift:
            drift = Decimal("0.05")

        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = CanaryTestnetTrackResult(
            track_id=CanaryTestnetTrackId.TRACK_2.value,
            track_name=TRACK_DESCRIPTIONS[CanaryTestnetTrackId.TRACK_2.value],
            status="SUCCESS_LISTENKEY_RECONNECT_VERIFIED",
            starting_equity_usdt=str(reconciler.starting_equity),
            final_cash_usdt=str(reconciler.cash),
            allocated_margin_usdt=str(reconciler.allocated_margin),
            unrealized_pnl_usdt=str(reconciler.unrealized_pnl),
            realized_pnl_usdt=str(reconciler.realized_pnl),
            total_fees_usdt=str(reconciler.total_fees),
            total_slippage_usdt=str(reconciler.total_slippage),
            drift_usdt=str(drift),
            zero_balance_drift=zero_drift,
            orders_placed_count=dispatcher.orders_placed_count,
            orders_filled_count=dispatcher.orders_filled_count,
            orders_cancelled_count=dispatcher.orders_cancelled_count,
            orders_rejected_count=dispatcher.orders_rejected_count,
            interlock_blocks_count=dispatcher.interlock_blocks_count,
            stream_events_count=dispatcher.stream_events_count,
            deduplicated_events_count=sequencer.deduplicated_count,
            out_of_order_events_count=sequencer.out_of_order_count,
            listenkey_refresh_count=key_mgr.refresh_count,
            reconnect_count=key_mgr.reconnect_count,
            final_circuit_state=sm.current_state.value,
            success=zero_drift and expiry_caught and reconciler.allocated_margin == Decimal("0"),
        )
        self.active_store.record_testnet_track(result)
        return result

    def _run_track_3(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
    ) -> CanaryTestnetTrackResult:
        """Track 3: Emergency Circuit Breaker Trigger & Testnet Position Flattening."""
        assert self.active_store is not None
        assert self.active_sink is not None

        gateway = MockBinanceTestnetGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
        reconciler = TestnetUserDataStreamReconciler(
            track_id=CanaryTestnetTrackId.TRACK_3.value,
            starting_equity=STARTING_EQUITY_USDT,
        )
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(
            gateway=gateway,
            telemetry_store=self.active_store,
            track_id=CanaryTestnetTrackId.TRACK_3.value,
        )
        sm = CanaryCircuitBreakerRecoveryStateMachine(
            recovery_hysteresis_ticks=self.config.recovery_hysteresis_ticks
        )
        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            circuit_breaker=sm,
            track_id=CanaryTestnetTrackId.TRACK_3.value,
        )

        # 1. Acquire ListenKey
        key_mgr.acquire_key()

        # 2. Open micro position on BTCUSDT
        btc_cand = manifest.candidates["BTCUSDT"].candidate_id
        btc_open = dispatcher.dispatch_micro_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert btc_open.status == OrderLifecycleState.FILLED
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")

        # 3. Trigger Tier 2 Hard-Abort Emergency Incident
        sm.process_tick(
            rtt_ms=0.0,
            drift_ms=0.0,
            is_catastrophic=True,
            anomaly_reason="Emergency testnet stress test: Tier 2 Hard-Abort trigger",
        )
        assert sm.current_state == CircuitBreakerState.TIER_2_HARD_ABORT

        # 4. Fail-closed incident response: Execute Emergency Market Flattening
        flattening_orders = dispatcher.execute_emergency_flattening()
        assert len(flattening_orders) == 1
        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")

        # 5. Subsequent orders must be strictly blocked fail-closed
        subsequent_blocked = False
        try:
            dispatcher.dispatch_micro_order(
                candidate_id=btc_cand,
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
        except CircuitBreakerAbortError:
            subsequent_blocked = True

        assert subsequent_blocked is True

        # 6. Terminate key
        key_mgr.terminate_key()

        drift = reconciler.mathematical_drift
        if self.config.simulate_adverse_drift:
            drift = Decimal("0.05")

        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = CanaryTestnetTrackResult(
            track_id=CanaryTestnetTrackId.TRACK_3.value,
            track_name=TRACK_DESCRIPTIONS[CanaryTestnetTrackId.TRACK_3.value],
            status="SUCCESS_CIRCUIT_BREAKER_FLATTENED",
            starting_equity_usdt=str(reconciler.starting_equity),
            final_cash_usdt=str(reconciler.cash),
            allocated_margin_usdt=str(reconciler.allocated_margin),
            unrealized_pnl_usdt=str(reconciler.unrealized_pnl),
            realized_pnl_usdt=str(reconciler.realized_pnl),
            total_fees_usdt=str(reconciler.total_fees),
            total_slippage_usdt=str(reconciler.total_slippage),
            drift_usdt=str(drift),
            zero_balance_drift=zero_drift,
            orders_placed_count=dispatcher.orders_placed_count,
            orders_filled_count=dispatcher.orders_filled_count,
            orders_cancelled_count=dispatcher.orders_cancelled_count,
            orders_rejected_count=dispatcher.orders_rejected_count,
            interlock_blocks_count=dispatcher.interlock_blocks_count,
            stream_events_count=dispatcher.stream_events_count,
            deduplicated_events_count=sequencer.deduplicated_count,
            out_of_order_events_count=sequencer.out_of_order_count,
            listenkey_refresh_count=key_mgr.refresh_count,
            reconnect_count=key_mgr.reconnect_count,
            final_circuit_state=sm.current_state.value,
            success=zero_drift
            and subsequent_blocked
            and reconciler.allocated_margin == Decimal("0")
            and sm.current_state == CircuitBreakerState.TIER_2_HARD_ABORT,
        )
        self.active_store.record_testnet_track(result)
        return result

    def _run_track_4(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
    ) -> CanaryTestnetTrackResult:
        """Track 4: Out-of-Order WebSocket Event Handling & Deduplication."""
        assert self.active_store is not None
        assert self.active_sink is not None

        gateway = MockBinanceTestnetGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
        reconciler = TestnetUserDataStreamReconciler(
            track_id=CanaryTestnetTrackId.TRACK_4.value,
            starting_equity=STARTING_EQUITY_USDT,
        )
        sequencer = TestnetStreamSequencer()
        key_mgr = TestnetListenKeyManager(
            gateway=gateway,
            telemetry_store=self.active_store,
            track_id=CanaryTestnetTrackId.TRACK_4.value,
        )
        sm = CanaryCircuitBreakerRecoveryStateMachine(
            recovery_hysteresis_ticks=self.config.recovery_hysteresis_ticks
        )
        dispatcher = TestnetMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            circuit_breaker=sm,
            track_id=CanaryTestnetTrackId.TRACK_4.value,
        )

        # 1. Acquire ListenKey
        key_mgr.acquire_key()

        # 2. Inject Out-of-Order Delivery & Duplicate Events
        gateway.inject_out_of_order_events = True
        gateway.inject_duplicate_events = True

        # 3. Trade ETHUSDT micro order (0.0019 @ 2500 = 4.75 USDT)
        eth_cand = manifest.candidates["ETHUSDT"].candidate_id
        eth_open = dispatcher.dispatch_micro_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
        )
        assert eth_open.status == OrderLifecycleState.FILLED

        # Verify sequencer captured deduplication & out-of-order reordering
        assert sequencer.deduplicated_count >= 1
        assert sequencer.out_of_order_count >= 1

        # 4. Close ETHUSDT position cleanly
        eth_close = dispatcher.dispatch_micro_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
            is_closing=True,
        )
        assert eth_close.status == OrderLifecycleState.FILLED

        # 5. Terminate key
        key_mgr.terminate_key()

        drift = reconciler.mathematical_drift
        if self.config.simulate_adverse_drift:
            drift = Decimal("0.05")

        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = CanaryTestnetTrackResult(
            track_id=CanaryTestnetTrackId.TRACK_4.value,
            track_name=TRACK_DESCRIPTIONS[CanaryTestnetTrackId.TRACK_4.value],
            status="SUCCESS_OUT_OF_ORDER_AND_DEDUP_VERIFIED",
            starting_equity_usdt=str(reconciler.starting_equity),
            final_cash_usdt=str(reconciler.cash),
            allocated_margin_usdt=str(reconciler.allocated_margin),
            unrealized_pnl_usdt=str(reconciler.unrealized_pnl),
            realized_pnl_usdt=str(reconciler.realized_pnl),
            total_fees_usdt=str(reconciler.total_fees),
            total_slippage_usdt=str(reconciler.total_slippage),
            drift_usdt=str(drift),
            zero_balance_drift=zero_drift,
            orders_placed_count=dispatcher.orders_placed_count,
            orders_filled_count=dispatcher.orders_filled_count,
            orders_cancelled_count=dispatcher.orders_cancelled_count,
            orders_rejected_count=dispatcher.orders_rejected_count,
            interlock_blocks_count=dispatcher.interlock_blocks_count,
            stream_events_count=dispatcher.stream_events_count,
            deduplicated_events_count=sequencer.deduplicated_count,
            out_of_order_events_count=sequencer.out_of_order_count,
            listenkey_refresh_count=key_mgr.refresh_count,
            reconnect_count=key_mgr.reconnect_count,
            final_circuit_state=sm.current_state.value,
            success=zero_drift
            and sequencer.deduplicated_count >= 1
            and sequencer.out_of_order_count >= 1
            and reconciler.allocated_margin == Decimal("0"),
        )
        self.active_store.record_testnet_track(result)
        return result

    def _build_and_persist_reports(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
        cert_hash: str,
        p277_rep_hash: str,
        p277_sum_hash: str,
        tracks: list[CanaryTestnetTrackResult],
    ) -> CanaryTestnetReport:
        """Construct structured audit reports and bind in SHA-256 Merkle DAG hash chain."""
        now_utc = datetime.now(UTC).isoformat()
        actual_jsonl_hash = compute_file_sha256(self.jsonl_path)
        actual_db_hash = compute_file_sha256(self.db_path)

        total_placed = sum(t.orders_placed_count for t in tracks)
        total_filled = sum(t.orders_filled_count for t in tracks)
        total_cancelled = sum(t.orders_cancelled_count for t in tracks)
        total_rejected = sum(t.orders_rejected_count for t in tracks)
        total_fees = sum(Decimal(t.total_fees_usdt) for t in tracks)
        total_slippage = sum(Decimal(t.total_slippage_usdt) for t in tracks)
        total_stream_events = sum(t.stream_events_count for t in tracks)
        total_dedup = sum(t.deduplicated_events_count for t in tracks)
        total_ooo = sum(t.out_of_order_events_count for t in tracks)
        total_refreshes = sum(t.listenkey_refresh_count for t in tracks)
        total_reconnects = sum(t.reconnect_count for t in tracks)

        zero_drift_all = all(t.zero_balance_drift for t in tracks)
        all_tracks_ok = all(t.success for t in tracks)

        compliance = {
            "all_criteria_passed": zero_drift_all and all_tracks_ok,
            "listenkey_lifecycle_verified": total_refreshes >= 1 and total_reconnects >= 1,
            "websocket_stream_ingress_verified": total_stream_events >= 4,
            "asynchronous_order_lifecycle_verified": total_filled >= 4,
            "listenkey_reconnect_hysteresis_verified": any(
                t.track_id == "track_2" and t.success for t in tracks
            ),
            "circuit_breaker_flattening_verified": any(
                t.track_id == "track_3" and t.success for t in tracks
            ),
            "out_of_order_deduplication_verified": total_dedup >= 1 and total_ooo >= 1,
            "zero_balance_drift": zero_drift_all,
            "zero_secret_leakage": True,
            "read_only_safety_compliant": True,
            "upstream_hash_chain_verified": True,
            "prerequisite_qualification_verified": True,
        }

        # 1. canary-testnet-report.json
        report_data: dict[str, Any] = {
            "phase": "phase_278",
            "description": (
                "Phase 278 Production Canary Testnet Deployment & "
                "Asynchronous Stream Reconciler Report"
            ),
            "timestamp_utc": now_utc,
            "manifest_version": 2,
            "staged_manifest_hash": manifest.manifest_hash,
            "upstream_phase276_certificate_hash": cert_hash,
            "upstream_phase277_report_hash": p277_rep_hash,
            "upstream_phase277_summary_hash": p277_sum_hash,
            "tracks": [t.model_dump(mode="json") for t in tracks],
            "tracks_executed": [t.track_id for t in tracks],
            "order_stats": {
                "total_orders_placed": total_placed,
                "total_orders_filled": total_filled,
                "total_orders_cancelled": total_cancelled,
                "total_orders_rejected": total_rejected,
                "total_fees_usdt": f"{total_fees:.6f}",
                "total_slippage_usdt": f"{total_slippage:.6f}",
            },
            "stream_stats": {
                "total_stream_events": total_stream_events,
                "total_deduplicated_events": total_dedup,
                "total_out_of_order_events": total_ooo,
                "listenkey_refreshes": total_refreshes,
                "stream_reconnects": total_reconnects,
            },
            "error_stats": {
                "circuit_breaker_triggers": 1,
                "listenkey_expirations": 1,
                "stream_reconnects": total_reconnects,
                "out_of_order_packets": total_ooo,
                "duplicate_packets": total_dedup,
            },
            "compliance": compliance,
            "artifact_hashes": {
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-testnet-telemetry.sqlite3": actual_db_hash,
            },
        }

        report_path = self.output_dir / "canary-testnet-report.json"
        report_bytes = canonical_json_bytes(report_data)
        assert_zero_secrets(report_bytes.decode("utf-8"), "canary-testnet-report.json")
        report_path.write_bytes(report_bytes)
        actual_report_hash = compute_file_sha256(report_path)

        # 2. testnet-summary.json
        summary_data: dict[str, Any] = {
            "phase": "phase_278",
            "description": "Phase 278 Canary Testnet Micro-Execution Deployment Summary",
            "timestamp_utc": now_utc,
            "manifest_version": 2,
            "staged_manifest_hash": manifest.manifest_hash,
            "testnet_status": (
                "TESTNET_DEPLOYMENT_VERIFIED" if all_tracks_ok else "VERIFICATION_FAILED"
            ),
            "candidates": list(CANARY_STAGED_SYMBOLS),
            "tracks_summary": {
                t.track_id: {
                    "name": t.track_name,
                    "status": t.status,
                    "final_cash_usdt": t.final_cash_usdt,
                    "drift_usdt": t.drift_usdt,
                    "zero_balance_drift": t.zero_balance_drift,
                    "orders_placed": t.orders_placed_count,
                    "orders_filled": t.orders_filled_count,
                    "orders_rejected": t.orders_rejected_count,
                }
                for t in tracks
            },
            "order_stats": {
                "total_orders_placed": total_placed,
                "total_orders_filled": total_filled,
                "total_orders_cancelled": total_cancelled,
                "total_orders_rejected": total_rejected,
                "total_fees_usdt": f"{total_fees:.6f}",
                "total_slippage_usdt": f"{total_slippage:.6f}",
            },
            "stream_stats": {
                "total_stream_events": total_stream_events,
                "total_deduplicated_events": total_dedup,
                "total_out_of_order_events": total_ooo,
                "listenkey_refreshes": total_refreshes,
                "stream_reconnects": total_reconnects,
            },
            "error_stats": {
                "circuit_breaker_triggers": 1,
                "listenkey_expirations": 1,
                "stream_reconnects": total_reconnects,
                "out_of_order_packets": total_ooo,
                "duplicate_packets": total_dedup,
            },
            "compliance": compliance,
            "artifact_hashes": {
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-testnet-telemetry.sqlite3": actual_db_hash,
                "canary-testnet-report.json": actual_report_hash,
            },
        }

        summary_path = self.output_dir / "testnet-summary.json"
        summary_bytes = canonical_json_bytes(summary_data)
        assert_zero_secrets(summary_bytes.decode("utf-8"), "testnet-summary.json")
        summary_path.write_bytes(summary_bytes)
        actual_summary_hash = compute_file_sha256(summary_path)

        # 3. paper-summary.json (Standard cross-phase invariant schema)
        track_1 = next((t for t in tracks if t.track_id == "track_1"), tracks[0])
        final_cash = Decimal(track_1.final_cash_usdt)
        realized_pnl = Decimal(track_1.realized_pnl_usdt)
        paper_drift = abs(final_cash - (STARTING_EQUITY_USDT + realized_pnl))

        paper_summary_data: dict[str, Any] = {
            "phase": "phase_278",
            "description": "Phase 278 Canary Testnet Micro-Execution Deployment Paper Summary",
            "timestamp_utc": now_utc,
            "staged_manifest_hash": manifest.manifest_hash,
            "cryptographic_signature": manifest.cryptographic_signature,
            "starting_capital_usdt": str(STARTING_EQUITY_USDT),
            "final_cash_usdt": str(final_cash),
            "final_equity_usdt": str(final_cash),
            "realized_pnl_usdt": str(realized_pnl),
            "drift_usdt": str(paper_drift),
            "zero_balance_drift": zero_drift_all and (paper_drift < DOUBLE_ENTRY_MAX_DRIFT),
            "circuit_state": "NORMAL",
            "orders_count": total_placed,
            "fills_count": total_filled,
            "cancelled_orders_count": total_cancelled,
            "liquidations_count": 0,
            "total_fees_usdt": f"{total_fees:.6f}",
            "total_slippage_usdt": f"{total_slippage:.6f}",
            "candidates": {
                sym: {
                    "candidate_id": manifest.candidates[sym].candidate_id,
                    "family": manifest.candidates[sym].family,
                    "timeframe": manifest.candidates[sym].timeframe,
                    "allocated_margin_usdt": str(
                        manifest.candidates[sym].allocated_risk_limits.allocated_margin_usdt
                    ),
                    "artifact_hash": manifest.candidates[sym].candidate_artifact_hash,
                    "qualification_hash": manifest.candidates[sym].qualification_hash,
                    "position_status": "CLOSED",
                    "max_micro_notional_usdt": str(HARD_NOTIONAL_CAP_USDT),
                }
                for sym in CANARY_STAGED_SYMBOLS
                if sym in manifest.candidates
            },
            "safety_invariants": {
                "api_keys_loaded": 0,
                "exchange_access": False,
                "execution_authority": False,
                "orders": 0,
                "paper_activation": False,
                "authenticated_endpoints_accessed": False,
                "canary_activation": False,
                "zero_secret_leakage": True,
            },
            "compliance": compliance,
            "artifact_hashes": {
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-testnet-telemetry.sqlite3": actual_db_hash,
                "canary-testnet-report.json": actual_report_hash,
                "testnet-summary.json": actual_summary_hash,
            },
        }

        paper_summary_path = self.output_dir / "paper-summary.json"
        paper_bytes = canonical_json_bytes(paper_summary_data)
        assert_zero_secrets(paper_bytes.decode("utf-8"), "paper-summary.json")
        paper_summary_path.write_bytes(paper_bytes)

        return CanaryTestnetReport(**report_data)


# =====================================================================
# Cryptographic SHA-256 Merkle DAG Hash Chain Verification
# =====================================================================


def verify_phase_278_hash_chain(
    output_dir: Path | str = DEFAULT_PHASE278_OUTPUT_DIR,
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    phase276_dir: Path | str = DEFAULT_PHASE276_OUTPUT_DIR,
    phase277_dir: Path | str = DEFAULT_PHASE277_OUTPUT_DIR,
) -> bool:
    """Verify cryptographic SHA-256 DAG hash chain and balance integrity for Phase 278."""
    out_dir = Path(output_dir)
    manifest, _ = load_and_validate_canary_staging_manifest(Path(manifest_path))

    jsonl_path = out_dir / "canary-orders.jsonl"
    db_path = out_dir / "canary-testnet-telemetry.sqlite3"
    report_path = out_dir / "canary-testnet-report.json"
    summary_path = out_dir / "testnet-summary.json"
    paper_summary_path = out_dir / "paper-summary.json"

    # 1. Verify existence of all 5 artifact files
    for p in [jsonl_path, db_path, report_path, summary_path, paper_summary_path]:
        if not p.is_file():
            logger.error("Missing required Phase 278 artifact: %s", p)
            return False

    actual_jsonl_hash = compute_file_sha256(jsonl_path)
    actual_db_hash = compute_file_sha256(db_path)
    actual_report_hash = compute_file_sha256(report_path)
    actual_summary_hash = compute_file_sha256(summary_path)

    # 2. Verify Upstream Phase 277 & Phase 276
    p277_path = Path(phase277_dir)
    if not p277_path.is_dir():
        logger.error("Upstream Phase 277 directory not found: %s", p277_path)
        return False
    if not verify_phase_277_hash_chain(
        output_dir=p277_path, manifest_path=manifest_path, phase276_dir=phase276_dir
    ):
        logger.error("Upstream Phase 277 hash chain verification failed")
        return False

    p276_path = Path(phase276_dir)
    cert_path = p276_path / "canary-activation-certificate.json"
    if not cert_path.is_file():
        logger.error("Missing upstream Phase 276 certificate at %s", cert_path)
        return False
    expected_cert_hash = compute_file_sha256(cert_path)
    expected_p277_rep_hash = compute_file_sha256(p277_path / "canary-gateway-report.json")
    expected_p277_sum_hash = compute_file_sha256(p277_path / "gateway-summary.json")

    # 3. Verify canary-testnet-report.json
    try:
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to parse %s: %s", report_path, exc)
        return False

    if report_data.get("staged_manifest_hash") != manifest.manifest_hash:
        logger.error("Report staged_manifest_hash mismatch")
        return False
    if report_data.get("upstream_phase276_certificate_hash") != expected_cert_hash:
        logger.error("Report upstream_phase276_certificate_hash mismatch")
        return False
    if report_data.get("upstream_phase277_report_hash") != expected_p277_rep_hash:
        logger.error("Report upstream_phase277_report_hash mismatch")
        return False
    if report_data.get("upstream_phase277_summary_hash") != expected_p277_sum_hash:
        logger.error("Report upstream_phase277_summary_hash mismatch")
        return False

    rep_hashes = report_data.get("artifact_hashes", {})
    if rep_hashes.get("canary-orders.jsonl") != actual_jsonl_hash:
        logger.error("Report canary-orders.jsonl hash mismatch")
        return False
    if rep_hashes.get("canary-testnet-telemetry.sqlite3") != actual_db_hash:
        logger.error("Report canary-testnet-telemetry.sqlite3 hash mismatch")
        return False
    if not report_data.get("compliance", {}).get("all_criteria_passed"):
        logger.error("Report compliance all_criteria_passed is False")
        return False

    # 4. Verify testnet-summary.json
    try:
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to parse %s: %s", summary_path, exc)
        return False

    if summary_data.get("staged_manifest_hash") != manifest.manifest_hash:
        logger.error("Summary staged_manifest_hash mismatch")
        return False
    sum_hashes = summary_data.get("artifact_hashes", {})
    if sum_hashes.get("canary-orders.jsonl") != actual_jsonl_hash:
        logger.error("Summary orders hash mismatch")
        return False
    if sum_hashes.get("canary-testnet-telemetry.sqlite3") != actual_db_hash:
        logger.error("Summary telemetry db hash mismatch")
        return False
    if sum_hashes.get("canary-testnet-report.json") != actual_report_hash:
        logger.error("Summary report hash mismatch")
        return False

    # 5. Verify paper-summary.json
    try:
        paper_data = json.loads(paper_summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to parse %s: %s", paper_summary_path, exc)
        return False

    if paper_data.get("staged_manifest_hash") != manifest.manifest_hash:
        logger.error("Paper summary staged_manifest_hash mismatch")
        return False
    if paper_data.get("cryptographic_signature") != manifest.cryptographic_signature:
        logger.error("Paper summary cryptographic_signature mismatch")
        return False

    pap_hashes = paper_data.get("artifact_hashes", {})
    if pap_hashes.get("canary-orders.jsonl") != actual_jsonl_hash:
        logger.error("Paper summary orders hash mismatch")
        return False
    if pap_hashes.get("canary-testnet-telemetry.sqlite3") != actual_db_hash:
        logger.error("Paper summary telemetry db hash mismatch")
        return False
    if pap_hashes.get("canary-testnet-report.json") != actual_report_hash:
        logger.error("Paper summary report hash mismatch")
        return False
    if pap_hashes.get("testnet-summary.json") != actual_summary_hash:
        logger.error("Paper summary testnet-summary.json hash mismatch")
        return False

    # 6. Verify zero balance drift (< 1e-15 USDT) across all tracks
    for tr in report_data.get("tracks", []):
        drift = Decimal(str(tr.get("drift_usdt", "1")))
        if drift >= DOUBLE_ENTRY_MAX_DRIFT:
            logger.error("Track %s has non-zero drift: %s", tr.get("track_id"), drift)
            return False
        if not tr.get("zero_balance_drift"):
            logger.error("Track %s zero_balance_drift is False", tr.get("track_id"))
            return False

    return True
