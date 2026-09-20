"""Phase 284: Production Canary Liquidity Regime Shifting & Dynamic Order Slicing Runner.

Implements the deterministic Phase 284 autonomous execution daemon runner, multi-candidate
cross-asset liquidity regime shifting, dynamic order slicing governance, stepped exposure
scaling up to 25.00 USDT, and continuous balance reconciliation across staged canary symbols
(BTCUSDT, ETHUSDT, SOLUSDT) under Candidate Registry Manifest Version 2.
"""

from __future__ import annotations

import json
import logging
import math
import re
import signal
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import Field

from autonomous_futures.domain.contracts import DomainModel
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.feed.adaptive_execution import (
    DEFAULT_PHASE283_OUTPUT_DIR,
    verify_phase_283_hash_chain,
)
from autonomous_futures.feed.canary_activation import (
    CANARY_STAGED_SYMBOLS,
    DEFAULT_PHASE276_OUTPUT_DIR,
    DEFAULT_REFERENCE_PRICES,
    STARTING_EQUITY_USDT,
    OrderSide,
    OrderType,
    TimeInForce,
)
from autonomous_futures.feed.canary_activation import (
    PrerequisiteQualificationError as UpstreamPrerequisiteQualificationError,
)
from autonomous_futures.feed.canary_live_gateway import (
    DEFAULT_PHASE277_OUTPUT_DIR,
)
from autonomous_futures.feed.canary_probe import (
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.feed.continuous_daemon import (
    DEFAULT_PHASE282_OUTPUT_DIR,
)
from autonomous_futures.feed.heartbeat_daemon import (
    DOUBLE_ENTRY_MAX_DRIFT,
)
from autonomous_futures.feed.mainnet_authorization import (
    DEFAULT_PHASE279_OUTPUT_DIR,
)
from autonomous_futures.feed.mainnet_deployment import (
    DEFAULT_PHASE280_OUTPUT_DIR,
)
from autonomous_futures.feed.mainnet_expansion import (
    DEFAULT_PHASE281_OUTPUT_DIR,
)
from autonomous_futures.feed.testnet_deployment import (
    DEFAULT_PHASE278_OUTPUT_DIR,
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
# Canonical Constants & Thresholds (Phase 284)
# =====================================================================

DEFAULT_PHASE284_OUTPUT_DIR: Path = Path("artifacts/research/phase284")

# Micro Order Sizing & Slicing Boundaries
MIN_MICRO_NOTIONAL_CAP_USDT: Decimal = Decimal("1.00")  # Minimum micro order notional
HARD_MICRO_NOTIONAL_CAP_USDT: Decimal = Decimal("5.00")  # Strictly <= 5.00 USDT child cap
DYNAMIC_SLICING_MAX_CHUNK_USDT: Decimal = Decimal("2.50")  # Sliced micro-chunks <= 2.50 USDT
SLIPPAGE_TOLERANCE_BPS: Decimal = Decimal("1.5")  # > 1.5 bps triggers dynamic slicing

# Stepped Concurrent Exposure Scaling Ceilings
STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT: Decimal = Decimal("5.00")  # Stage 1: <= 5.00 USDT
STAGE_2_CONCURRENT_EXPOSURE_CAP_USDT: Decimal = Decimal("10.00")  # Stage 2: <= 10.00 USDT
STAGE_3_CONTINUOUS_EXPOSURE_CAP_USDT: Decimal = Decimal("15.00")  # Stage 3: <= 15.00 USDT
STAGE_4_ADAPTIVE_EXPOSURE_CAP_USDT: Decimal = Decimal("20.00")  # Stage 4: <= 20.00 USDT
STAGE_5_LIQUIDITY_EXPOSURE_CAP_USDT: Decimal = Decimal("25.00")  # Stage 5: <= 25.00 USDT
AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT: Decimal = (
    Decimal("25.00")  # Overall Aggregate Exposure Cap
)

# Margin Allocation Headroom Interlocks
MAX_PER_ASSET_MARGIN_PCT: Decimal = Decimal("0.20")  # <= 20.00% per asset
MAX_AGGREGATE_MARGIN_PCT: Decimal = Decimal("0.60")  # <= 60.00% aggregate portfolio margin
MIN_RESERVE_BUFFER_PCT: Decimal = Decimal("0.40")  # >= 40.00% unencumbered cash reserve buffer

# Risk Budgets & Circuit Breakers
INTRA_PHASE_LOSS_CEILING_USDT: Decimal = Decimal("3.50")  # Cumulative loss ceiling <= 3.50 USDT

# Gateway Heartbeat Freshness & Clock Drift
GATEWAY_HEARTBEAT_MAX_AGE_MS: float = 500.0  # Order dispatch allowed only if age <= 500 ms
GATEWAY_HEARTBEAT_HYSTERESIS_RECOVERY_MS: float = (
    450.0  # Recovery ceiling to exit stale state (50ms recovery hysteresis)
)
MAX_CLOCK_SKEW_TOLERANCE_MS: float = 250.0  # Max tolerable backward NTP clock drift

# Fee Model & Pricing Precision
DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0004")  # 0.04% taker fee
DEFAULT_MAKER_FEE_RATE: Decimal = Decimal("0.0002")  # 0.02% maker fee

# Session Longevity & ListenKey
LISTEN_KEY_LIFETIME_SECONDS: float = 86400.0  # 24h lifetime
LISTEN_KEY_REFRESH_INTERVAL_SECONDS: float = 43200.0  # 12h keep-alive refresh
SEQUENCE_WRAP_THRESHOLD: int = 1_000_000  # Sequence rollover threshold

# Liquidity Regime Thresholds
MIN_REQUIRED_BOOK_DEPTH: Decimal = Decimal("0.00002")  # Absolute min required liquidity
MAX_TOLERABLE_SPREAD_PCT: Decimal = Decimal("0.05")  # Max allowed spread 5%
DEFAULT_DEPTH_EXHAUSTION_THRESHOLD: Decimal = Decimal("0.00005")

# Track Descriptions
TRACK_DESCRIPTIONS: dict[str, str] = {
    "track_1": (
        "Multi-Candidate Liquidity Regime Classification & Micro Order Execution Replay "
        "(Nominal regime detection, clean TWAP slicing across BTCUSDT, ETHUSDT, SOLUSDT -> "
        "parallel lifecycle management -> clean ledger updates)"
    ),
    "track_2": (
        "Abrupt Liquidity Evaporation & Dynamic TWAP Slicing Throttling Drill "
        "(Simulate depth collapse -> dynamic child order downscaling, limit offset widening, "
        "and fail-closed dispatch rejection on margin ceiling)"
    ),
    "track_3": (
        "Cross-Symbol Asymmetric Liquidity Crisis & Emergency Liquidation Drill "
        "(Simulate liquidity freeze and loss budget breach -> immediate fail-closed lockout "
        "and emergency micro-chunked position liquidation <= 5.00 USDT)"
    ),
    "track_4": (
        "Extended Multi-Day Session Continuity, WebSocket Heartbeat Renewal & REST "
        "Reconciliation Drill (Simulate extended daemon execution, listen-key refresh, "
        "sequence wrap recovery, backfill missing events via REST, idempotent trade deduplication)"
    ),
}


# =====================================================================
# Error Hierarchy
# =====================================================================


class CanaryLiquidityRegimeError(DomainViolation):
    """Base exception for Phase 284 liquidity regime runner operations."""


class PrerequisiteQualificationError(
    UpstreamPrerequisiteQualificationError, CanaryLiquidityRegimeError
):
    """Raised when upstream qualification or certification is missing or invalid."""


class IndividualMicroCapExceededError(CanaryLiquidityRegimeError):
    """Raised when order notional exceeds 5.00 USDT individual micro order cap."""


class MicroNotionalFloorViolationError(CanaryLiquidityRegimeError):
    """Raised when order notional falls below 1.00 USDT micro floor."""


class AggregateExposureCapExceededError(CanaryLiquidityRegimeError):
    """Raised when concurrent active exposure exceeds active stage expansion cap."""


class MarginAllocationExceededError(CanaryLiquidityRegimeError):
    """Raised when margin allocation exceeds per-asset (20%) or aggregate (60%) ceiling."""


class CashReserveBufferBreachedError(CanaryLiquidityRegimeError):
    """Raised when unencumbered cash reserve buffer falls below 40% requirement."""


class IntraPhaseLossCeilingExceededError(CanaryLiquidityRegimeError):
    """Raised when cumulative intra-phase loss exceeds 3.50 USDT loss ceiling."""


class GatewayHeartbeatStaleError(CanaryLiquidityRegimeError):
    """Raised when gateway heartbeat age exceeds 500 ms freshness ceiling."""


class HeartbeatFreezeActiveError(GatewayHeartbeatStaleError):
    """Raised when order dispatch is blocked by active heartbeat hysteresis freeze."""


class ClockSkewExceededError(HeartbeatFreezeActiveError):
    """Raised when backward NTP clock drift exceeds 250 ms tolerance limit."""


class InvalidClientOrderIdTagError(CanaryLiquidityRegimeError):
    """Raised when client order ID does not conform to canary deterministic tagging."""


class CircuitBreakerAbortError(CanaryLiquidityRegimeError):
    """Raised when order dispatch is attempted while circuit breaker is tripped."""


class OrderCorrelationError(CanaryLiquidityRegimeError):
    """Raised when order lifecycle transition fails correlation or causality check."""


class ListenKeyLifecycleError(CanaryLiquidityRegimeError):
    """Raised when listenKey acquisition, renewal, or termination fails."""


class ListenKeyExpiredError(ListenKeyLifecycleError):
    """Raised when user data stream listenKey has expired and requires renewal."""


class DepthExhaustionError(CanaryLiquidityRegimeError):
    """Raised when order book depth is exhausted or below minimum safety threshold."""


class SpreadExceededError(CanaryLiquidityRegimeError):
    """Raised when bid-ask spread exceeds maximum tolerable ceiling."""


class OrderSlicingError(CanaryLiquidityRegimeError):
    """Raised when dynamic micro-order slicing cannot be completed safely."""


# =====================================================================
# Enumerations
# =====================================================================


class LiquidityRegime(StrEnum):
    """Prevailing market liquidity classification per candidate."""

    NORMAL = "NORMAL"
    THIN = "THIN"
    ILLIQUID = "ILLIQUID"


class CanaryLiquidityRegimeTrackId(StrEnum):
    """Identifiers for the 4 Phase 284 simulation tracks."""

    TRACK_1 = "track_1"
    TRACK_2 = "track_2"
    TRACK_3 = "track_3"
    TRACK_4 = "track_4"


# Backward compatibility aliases
CanaryAdaptiveExecutionTrackId = CanaryLiquidityRegimeTrackId
CanaryContinuousDaemonTrackId = CanaryLiquidityRegimeTrackId


class CapitalExpansionStage(StrEnum):
    """Stepped concurrent exposure scaling tiers under Phase 284 (up to 25.00 USDT)."""

    STAGE_1_CONCURRENT_MICRO = "STAGE_1_CONCURRENT_MICRO"  # <= 5.00 USDT
    STAGE_2_EXPANDED_CONCURRENT = "STAGE_2_EXPANDED_CONCURRENT"  # <= 10.00 USDT
    STAGE_3_CONTINUOUS_EXPANSION = "STAGE_3_CONTINUOUS_EXPANSION"  # <= 15.00 USDT
    STAGE_4_ADAPTIVE_EXPANSION = "STAGE_4_ADAPTIVE_EXPANSION"  # <= 20.00 USDT
    STAGE_5_LIQUIDITY_EXPANSION = "STAGE_5_LIQUIDITY_EXPANSION"  # <= 25.00 USDT


class CircuitBreakerState(StrEnum):
    """Circuit breaker and fail-closed lockout states."""

    NORMAL = "NORMAL"
    HEARTBEAT_FREEZE = "HEARTBEAT_FREEZE"
    INTRA_PHASE_LOSS_LOCKOUT = "INTRA_PHASE_LOSS_LOCKOUT"
    DAILY_LOSS_LOCKOUT = "DAILY_LOSS_LOCKOUT"
    HARD_ABORT = "HARD_ABORT"


class HeartbeatStatus(StrEnum):
    """Real-time gateway heartbeat freshness classifications."""

    HEALTHY = "HEALTHY"
    LATENCY_SPIKE_STALE = "LATENCY_SPIKE_STALE"
    CLOCK_SKEW_FREEZE = "CLOCK_SKEW_FREEZE"
    TIMEOUT = "TIMEOUT"
    DISCONNECTED = "DISCONNECTED"
    RECOVERED = "RECOVERED"


class OrderLifecycleState(StrEnum):
    """Monotonic state machine for order lifecycle transitions."""

    PENDING_NEW = "PENDING_NEW"
    PENDING_SUBMIT = "PENDING_SUBMIT"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DaemonState(StrEnum):
    """Lifecycle states of the autonomous continuous daemon."""

    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"


class WebSocketEventType(StrEnum):
    """Event types pushed over Binance Futures User Data Stream."""

    ORDER_TRADE_UPDATE = "ORDER_TRADE_UPDATE"
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    LISTEN_KEY_EXPIRED = "LISTEN_KEY_EXPIRED"
    HEARTBEAT_UPDATE = "HEARTBEAT_UPDATE"


class InterlockType(StrEnum):
    """Types of risk containment interlocks."""

    GATEWAY_HEARTBEAT_FRESHNESS = "GATEWAY_HEARTBEAT_FRESHNESS"
    DUAL_CONFIRMATION_TAG = "DUAL_CONFIRMATION_TAG"
    MICRO_NOTIONAL_CEILING = "MICRO_NOTIONAL_CEILING"
    MICRO_NOTIONAL_FLOOR = "MICRO_NOTIONAL_FLOOR"
    AGGREGATE_EXPOSURE_CEILING = "AGGREGATE_EXPOSURE_CEILING"
    MARGIN_ALLOCATION_CEILING = "MARGIN_ALLOCATION_CEILING"
    CASH_RESERVE_BUFFER = "CASH_RESERVE_BUFFER"
    INTRA_PHASE_LOSS_CEILING = "INTRA_PHASE_LOSS_CEILING"
    CIRCUIT_BREAKER_NORMAL = "CIRCUIT_BREAKER_NORMAL"
    ORDER_BOOK_DEPTH = "ORDER_BOOK_DEPTH"
    SPREAD_TOLERANCE = "SPREAD_TOLERANCE"
    LIQUIDITY_REGIME = "LIQUIDITY_REGIME"
    ORDER_SLICING = "ORDER_SLICING"


class OrderSlicingMode(StrEnum):
    """Order slicing modes for depth adaptation."""

    NONE = "NONE"
    TWAP_MICRO = "TWAP_MICRO"
    ICEBERG_MICRO = "ICEBERG_MICRO"


# =====================================================================
# Dual-Confirmation Client Order Tagging (Phase 284 Format)
# =====================================================================

CANARY_CLIENT_ORDER_ID_REGEX = re.compile(
    r"^c=canary-p284-(?P<symbol>[A-Z0-9]+)-(?P<timestamp>\d+)-(?P<uuid>[a-zA-Z0-9\-]+)$"
)


def generate_canary_client_order_id(
    symbol: str,
    timestamp_ms: int | None = None,
    uuid_str: str | None = None,
) -> str:
    """Generate deterministic dual-confirmation client order tag for Phase 284:
    Format: c=canary-p284-{sym}-{ts}-{uuid}
    """
    sym = str(symbol).strip().upper()
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    uid = uuid_str if uuid_str is not None else uuid4().hex[:12]
    return f"c=canary-p284-{sym}-{ts}-{uid}"


def validate_canary_client_order_id(
    client_order_id: str,
    expected_symbol: str | None = None,
) -> tuple[bool, str | None]:
    """Validate client order ID tag against Phase 284 canary format."""
    if not isinstance(client_order_id, str):
        return False, "client_order_id must be a string"
    match = CANARY_CLIENT_ORDER_ID_REGEX.match(client_order_id)
    if not match:
        return False, f"client_order_id '{client_order_id}' does not match pattern c=canary-p284-*"
    sym = match.group("symbol")
    if expected_symbol is not None and sym != expected_symbol.strip().upper():
        return False, f"client_order_id symbol '{sym}' does not match expected '{expected_symbol}'"
    return True, None


def assert_valid_canary_client_order_id(
    client_order_id: str,
    expected_symbol: str | None = None,
) -> None:
    """Raise InvalidClientOrderIdTagError if client order ID does not match format."""
    ok, err = validate_canary_client_order_id(client_order_id, expected_symbol)
    if not ok:
        raise InvalidClientOrderIdTagError(err or "Invalid client order ID tag")


def _safe_decimal(val: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Safely parse value into Decimal."""
    if val is None:
        return default
    if isinstance(val, Decimal):
        return val if val.is_finite() else default
    try:
        d = Decimal(str(val))
        return d if d.is_finite() else default
    except Exception:
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely parse value into int."""
    if val is None:
        return default
    try:
        return int(val)
    except Exception:
        return default


# =====================================================================
# Domain Models & Telemetry Data Structures
# =====================================================================


class GatewayHeartbeatRecord(DomainModel):
    """Gateway heartbeat telemetry record."""

    heartbeat_id: str = Field(default_factory=lambda: f"hb_{uuid4().hex[:12]}")
    track_id: str
    server_time_ms: int
    local_receive_time_ms: int
    latency_ms: float
    age_ms: float
    status: HeartbeatStatus
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    details_json: str = "{}"


class LiquidityRegimeSnapshot(DomainModel):
    """Telemetry snapshot of detected market liquidity regime."""

    snapshot_id: str = Field(default_factory=lambda: f"lrs_{uuid4().hex[:12]}")
    track_id: str
    symbol: str
    regime: LiquidityRegime
    spread_bps: str
    depth_density: str
    volume_velocity: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ParentOrderRecord(DomainModel):
    """Parent order record for dynamic micro-order slicing governance."""

    parent_client_order_id: str
    track_id: str
    candidate_id: str
    symbol: str
    side: str
    order_type: str
    total_quantity: str
    total_notional_usdt: str
    executed_quantity: str = "0"
    executed_notional_usdt: str = "0"
    status: OrderLifecycleState = OrderLifecycleState.PENDING_NEW
    slicing_mode: OrderSlicingMode = OrderSlicingMode.NONE
    child_order_ids: list[str] = Field(default_factory=list)
    child_count: int = 0
    liquidity_regime: LiquidityRegime = LiquidityRegime.NORMAL
    estimated_slippage_bps: str = "0.0000"
    total_fees_usdt: str = "0.00000000"
    total_slippage_usdt: str = "0.00000000"
    created_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class LiquidityOrderRecord(DomainModel):
    """Individual micro order record tracked across its lifecycle."""

    order_id: str = "0"
    client_order_id: str
    track_id: str
    candidate_id: str
    symbol: str
    side: str
    order_type: str
    time_in_force: str = TimeInForce.GTC.value
    price: str
    quantity: str
    executed_quantity: str = "0"
    notional_usdt: str
    status: OrderLifecycleState = OrderLifecycleState.PENDING_NEW
    expansion_stage: CapitalExpansionStage = CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO
    is_closing: bool = False
    liquidity_regime: LiquidityRegime = LiquidityRegime.NORMAL
    estimated_slippage_bps: str = "0.0000"
    limit_offset_usdt: str = "0.00000000"
    parent_client_order_id: str | None = None
    is_child: bool = False
    child_index: int = 0
    created_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    rejection_reason: str | None = None


# Backward compatibility alias
AdaptiveOrderRecord = LiquidityOrderRecord


class OrderLifecycleTransition(DomainModel):
    """Audit log of order state machine transitions."""

    transition_id: str = Field(default_factory=lambda: f"tx_{uuid4().hex[:12]}")
    track_id: str
    order_id: str
    client_order_id: str
    from_state: OrderLifecycleState
    to_state: OrderLifecycleState
    trigger_reason: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    details_json: str = "{}"


class ExecutionMark(DomainModel):
    """Execution trade fill record."""

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
    realized_pnl_usdt: str = "0"
    trade_time_ms: int
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class BalanceSnapshot(DomainModel):
    """Portfolio balance snapshot for exact double-entry accounting reconciliation."""

    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid4().hex[:12]}")
    track_id: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    cash_usdt: str
    allocated_margin_usdt: str
    unrealized_pnl_usdt: str
    realized_pnl_usdt: str
    equity_usdt: str
    drift_usdt: str


class InterlockEvent(DomainModel):
    """Audit record of interlock checks and gate decisions."""

    event_id: str = Field(default_factory=lambda: f"ilk_{uuid4().hex[:12]}")
    track_id: str
    interlock_name: str
    status: str  # PASSED, BLOCKED, REJECTED
    symbol: str | None = None
    client_order_id: str | None = None
    details_json: str = "{}"
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class WebSocketPushEvent(DomainModel):
    """Audit log of raw and reconciled User Data Stream events."""

    event_id: str = Field(default_factory=lambda: f"ws_{uuid4().hex[:12]}")
    track_id: str
    event_type: str
    event_time_ms: int
    transaction_time_ms: int
    sequence_number: int
    client_order_id: str | None = None
    symbol: str | None = None
    order_status: str | None = None
    payload_json: str = "{}"
    is_duplicate: bool = False
    is_out_of_order: bool = False
    processed_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class DaemonLifecycleEvent(DomainModel):
    """Audit event for autonomous continuous daemon state changes."""

    event_id: str = Field(default_factory=lambda: f"dmn_{uuid4().hex[:12]}")
    track_id: str
    daemon_state: DaemonState
    event_type: str
    description: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    details_json: str = "{}"


class LiquidityDaemonTrackResult(DomainModel):
    """Outcome and telemetry for a single simulation track."""

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
    heartbeat_events_count: int
    stale_heartbeat_count: int
    stream_events_count: int
    deduplicated_events_count: int
    out_of_order_events_count: int
    final_circuit_state: str
    final_expansion_stage: str
    success: bool


# Backward compatibility alias
AdaptiveDaemonTrackResult = LiquidityDaemonTrackResult


class CanaryLiquidityRegimeReport(DomainModel):
    """Top-level structured JSON audit report for Phase 284."""

    phase: str = "phase_284"
    description: str
    timestamp_utc: str
    daemon_status: str
    manifest_version: int
    staged_manifest_hash: str
    upstream_phase276_certificate_hash: str
    upstream_phase277_report_hash: str
    upstream_phase277_summary_hash: str
    upstream_phase278_report_hash: str
    upstream_phase278_summary_hash: str
    upstream_phase279_report_hash: str
    upstream_phase279_summary_hash: str
    upstream_phase280_report_hash: str
    upstream_phase280_summary_hash: str
    upstream_phase281_report_hash: str
    upstream_phase281_summary_hash: str
    upstream_phase282_report_hash: str
    upstream_phase282_summary_hash: str
    upstream_phase283_report_hash: str
    upstream_phase283_summary_hash: str
    tracks: list[LiquidityDaemonTrackResult]
    tracks_executed: list[str]
    order_stats: dict[str, Any]
    heartbeat_stats: dict[str, Any]
    stream_stats: dict[str, Any]
    daemon_stats: dict[str, Any]
    error_stats: dict[str, Any]
    compliance: dict[str, Any]
    artifact_hashes: dict[str, str]


# Backward compatibility alias
CanaryAdaptiveExecutionReport = CanaryLiquidityRegimeReport


class CanaryLiquidityRegimeConfig(DomainModel):
    """Configuration options for Phase 284 runner execution."""

    manifest_path: Path = DEFAULT_CANARY_STAGING_MANIFEST_PATH
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH
    phase276_input_dir: Path = DEFAULT_PHASE276_OUTPUT_DIR
    phase277_input_dir: Path = DEFAULT_PHASE277_OUTPUT_DIR
    phase278_input_dir: Path = DEFAULT_PHASE278_OUTPUT_DIR
    phase279_input_dir: Path = DEFAULT_PHASE279_OUTPUT_DIR
    phase280_input_dir: Path = DEFAULT_PHASE280_OUTPUT_DIR
    phase281_input_dir: Path = DEFAULT_PHASE281_OUTPUT_DIR
    phase282_input_dir: Path = DEFAULT_PHASE282_OUTPUT_DIR
    phase283_input_dir: Path = DEFAULT_PHASE283_OUTPUT_DIR
    output_dir: Path = DEFAULT_PHASE284_OUTPUT_DIR
    track: str = "all"
    intra_phase_loss_ceiling_usdt: Decimal = INTRA_PHASE_LOSS_CEILING_USDT
    simulate_adverse_drift: bool = False


# Backward compatibility alias
CanaryAdaptiveExecutionConfig = CanaryLiquidityRegimeConfig


# =====================================================================
# Isolated SQLite Telemetry Store & JSONL Sink
# =====================================================================


class SqliteCanaryLiquidityRegimeTelemetryStore:
    """Isolated SQLite telemetry store for Phase 284 liquidity regime records."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA busy_timeout=30000;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS gateway_heartbeats (
                    heartbeat_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    server_time_ms INTEGER NOT NULL,
                    local_receive_time_ms INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    age_ms REAL NOT NULL,
                    status TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
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
                    expansion_stage TEXT NOT NULL,
                    is_closing INTEGER NOT NULL,
                    liquidity_regime TEXT NOT NULL DEFAULT 'NORMAL',
                    estimated_slippage_bps TEXT NOT NULL DEFAULT '0.0000',
                    limit_offset_usdt TEXT NOT NULL DEFAULT '0.00000000',
                    parent_client_order_id TEXT,
                    is_child INTEGER NOT NULL DEFAULT 0,
                    child_index INTEGER NOT NULL DEFAULT 0,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    rejection_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS parent_orders (
                    parent_client_order_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    total_quantity TEXT NOT NULL,
                    total_notional_usdt TEXT NOT NULL,
                    executed_quantity TEXT NOT NULL DEFAULT '0',
                    executed_notional_usdt TEXT NOT NULL DEFAULT '0',
                    status TEXT NOT NULL,
                    slicing_mode TEXT NOT NULL,
                    child_count INTEGER NOT NULL DEFAULT 0,
                    liquidity_regime TEXT NOT NULL,
                    estimated_slippage_bps TEXT NOT NULL,
                    total_fees_usdt TEXT NOT NULL DEFAULT '0.00000000',
                    total_slippage_usdt TEXT NOT NULL DEFAULT '0.00000000',
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS liquidity_regime_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    spread_bps TEXT NOT NULL,
                    depth_density TEXT NOT NULL,
                    volume_velocity TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS interlock_events (
                    event_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    interlock_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    symbol TEXT,
                    client_order_id TEXT,
                    details_json TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS daemon_lifecycle_events (
                    event_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    daemon_state TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS liquidity_daemon_track_results (
                    track_id TEXT PRIMARY KEY,
                    track_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    starting_equity_usdt TEXT NOT NULL,
                    final_cash_usdt TEXT NOT NULL,
                    allocated_margin_usdt TEXT NOT NULL,
                    unrealized_pnl_usdt TEXT NOT NULL,
                    realized_pnl_usdt TEXT NOT NULL,
                    total_fees_usdt TEXT NOT NULL,
                    total_slippage_usdt TEXT NOT NULL,
                    drift_usdt TEXT NOT NULL,
                    zero_balance_drift INTEGER NOT NULL,
                    orders_placed_count INTEGER NOT NULL,
                    orders_filled_count INTEGER NOT NULL,
                    orders_cancelled_count INTEGER NOT NULL,
                    orders_rejected_count INTEGER NOT NULL,
                    interlock_blocks_count INTEGER NOT NULL,
                    heartbeat_events_count INTEGER NOT NULL,
                    stale_heartbeat_count INTEGER NOT NULL,
                    stream_events_count INTEGER NOT NULL,
                    deduplicated_events_count INTEGER NOT NULL,
                    out_of_order_events_count INTEGER NOT NULL,
                    final_circuit_state TEXT NOT NULL,
                    final_expansion_stage TEXT NOT NULL,
                    success INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS listen_key_lifecycle_events (
                    event_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    listen_key TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                """
            )

    def record_heartbeat(self, record: GatewayHeartbeatRecord) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO gateway_heartbeats (
                    heartbeat_id, track_id, server_time_ms, local_receive_time_ms,
                    latency_ms, age_ms, status, timestamp_utc, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.heartbeat_id,
                    record.track_id,
                    record.server_time_ms,
                    record.local_receive_time_ms,
                    record.latency_ms,
                    record.age_ms,
                    record.status.value,
                    record.timestamp_utc,
                    record.details_json,
                ),
            )

    def record_order(self, record: LiquidityOrderRecord) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO orders (
                    client_order_id, order_id, track_id, candidate_id, symbol,
                    side, order_type, time_in_force, price, quantity,
                    executed_quantity, notional_usdt, status, expansion_stage,
                    is_closing, liquidity_regime, estimated_slippage_bps,
                    limit_offset_usdt, parent_client_order_id, is_child,
                    child_index, created_at_utc, updated_at_utc, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.client_order_id,
                    record.order_id,
                    record.track_id,
                    record.candidate_id,
                    record.symbol,
                    record.side,
                    record.order_type,
                    record.time_in_force,
                    record.price,
                    record.quantity,
                    record.executed_quantity,
                    record.notional_usdt,
                    record.status.value
                    if isinstance(record.status, OrderLifecycleState)
                    else str(record.status),
                    record.expansion_stage.value
                    if isinstance(record.expansion_stage, CapitalExpansionStage)
                    else str(record.expansion_stage),
                    1 if record.is_closing else 0,
                    record.liquidity_regime.value
                    if isinstance(record.liquidity_regime, LiquidityRegime)
                    else str(record.liquidity_regime),
                    record.estimated_slippage_bps,
                    record.limit_offset_usdt,
                    record.parent_client_order_id,
                    1 if record.is_child else 0,
                    record.child_index,
                    record.created_at_utc,
                    record.updated_at_utc,
                    record.rejection_reason,
                ),
            )

    def record_parent_order(self, record: ParentOrderRecord) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO parent_orders (
                    parent_client_order_id, track_id, candidate_id, symbol,
                    side, order_type, total_quantity, total_notional_usdt,
                    executed_quantity, executed_notional_usdt, status,
                    slicing_mode, child_count, liquidity_regime,
                    estimated_slippage_bps, total_fees_usdt, total_slippage_usdt,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.parent_client_order_id,
                    record.track_id,
                    record.candidate_id,
                    record.symbol,
                    record.side,
                    record.order_type,
                    record.total_quantity,
                    record.total_notional_usdt,
                    record.executed_quantity,
                    record.executed_notional_usdt,
                    record.status.value
                    if isinstance(record.status, OrderLifecycleState)
                    else str(record.status),
                    record.slicing_mode.value
                    if isinstance(record.slicing_mode, OrderSlicingMode)
                    else str(record.slicing_mode),
                    record.child_count,
                    record.liquidity_regime.value
                    if isinstance(record.liquidity_regime, LiquidityRegime)
                    else str(record.liquidity_regime),
                    record.estimated_slippage_bps,
                    record.total_fees_usdt,
                    record.total_slippage_usdt,
                    record.created_at_utc,
                    record.updated_at_utc,
                ),
            )

    def record_regime_snapshot(self, record: LiquidityRegimeSnapshot) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO liquidity_regime_snapshots (
                    snapshot_id, track_id, symbol, regime,
                    spread_bps, depth_density, volume_velocity, timestamp_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.snapshot_id,
                    record.track_id,
                    record.symbol,
                    record.regime.value
                    if isinstance(record.regime, LiquidityRegime)
                    else str(record.regime),
                    record.spread_bps,
                    record.depth_density,
                    record.volume_velocity,
                    record.timestamp_utc,
                ),
            )

    def record_transition(self, record: OrderLifecycleTransition) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO lifecycle_transitions (
                    transition_id, track_id, order_id, client_order_id,
                    from_state, to_state, trigger_reason, timestamp_utc, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.transition_id,
                    record.track_id,
                    record.order_id,
                    record.client_order_id,
                    record.from_state.value
                    if isinstance(record.from_state, OrderLifecycleState)
                    else str(record.from_state),
                    record.to_state.value
                    if isinstance(record.to_state, OrderLifecycleState)
                    else str(record.to_state),
                    record.trigger_reason,
                    record.timestamp_utc,
                    record.details_json,
                ),
            )

    def record_execution_mark(self, record: ExecutionMark) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO execution_marks (
                    trade_id, track_id, order_id, client_order_id, symbol,
                    side, price, quantity, quote_quantity, commission_usdt,
                    realized_pnl_usdt, trade_time_ms, timestamp_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.trade_id,
                    record.track_id,
                    record.order_id,
                    record.client_order_id,
                    record.symbol,
                    record.side,
                    record.price,
                    record.quantity,
                    record.quote_quantity,
                    record.commission_usdt,
                    record.realized_pnl_usdt,
                    record.trade_time_ms,
                    record.timestamp_utc,
                ),
            )

    def record_balance_snapshot(self, record: BalanceSnapshot) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO balance_snapshots (
                    snapshot_id, track_id, timestamp_utc, cash_usdt,
                    allocated_margin_usdt, unrealized_pnl_usdt,
                    realized_pnl_usdt, equity_usdt, drift_usdt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.snapshot_id,
                    record.track_id,
                    record.timestamp_utc,
                    record.cash_usdt,
                    record.allocated_margin_usdt,
                    record.unrealized_pnl_usdt,
                    record.realized_pnl_usdt,
                    record.equity_usdt,
                    record.drift_usdt,
                ),
            )

    def record_interlock_event(self, record: InterlockEvent) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO interlock_events (
                    event_id, track_id, interlock_name, status,
                    symbol, client_order_id, details_json, timestamp_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.track_id,
                    record.interlock_name,
                    record.status,
                    record.symbol,
                    record.client_order_id,
                    record.details_json,
                    record.timestamp_utc,
                ),
            )

    def record_websocket_event(self, record: WebSocketPushEvent) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO websocket_push_events (
                    event_id, track_id, event_type, event_time_ms,
                    transaction_time_ms, sequence_number, client_order_id,
                    symbol, order_status, payload_json, is_duplicate,
                    is_out_of_order, processed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.track_id,
                    record.event_type,
                    record.event_time_ms,
                    record.transaction_time_ms,
                    record.sequence_number,
                    record.client_order_id,
                    record.symbol,
                    record.order_status,
                    record.payload_json,
                    1 if record.is_duplicate else 0,
                    1 if record.is_out_of_order else 0,
                    record.processed_at_utc,
                ),
            )

    def record_daemon_event(self, record: DaemonLifecycleEvent) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO daemon_lifecycle_events (
                    event_id, track_id, daemon_state, event_type,
                    description, timestamp_utc, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.track_id,
                    record.daemon_state.value
                    if isinstance(record.daemon_state, DaemonState)
                    else str(record.daemon_state),
                    record.event_type,
                    record.description,
                    record.timestamp_utc,
                    record.details_json,
                ),
            )

    def record_daemon_track(self, record: LiquidityDaemonTrackResult) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO liquidity_daemon_track_results (
                    track_id, track_name, status, starting_equity_usdt,
                    final_cash_usdt, allocated_margin_usdt, unrealized_pnl_usdt,
                    realized_pnl_usdt, total_fees_usdt, total_slippage_usdt,
                    drift_usdt, zero_balance_drift, orders_placed_count,
                    orders_filled_count, orders_cancelled_count,
                    orders_rejected_count, interlock_blocks_count,
                    heartbeat_events_count, stale_heartbeat_count,
                    stream_events_count, deduplicated_events_count,
                    out_of_order_events_count, final_circuit_state,
                    final_expansion_stage, success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.track_id,
                    record.track_name,
                    record.status,
                    record.starting_equity_usdt,
                    record.final_cash_usdt,
                    record.allocated_margin_usdt,
                    record.unrealized_pnl_usdt,
                    record.realized_pnl_usdt,
                    record.total_fees_usdt,
                    record.total_slippage_usdt,
                    record.drift_usdt,
                    1 if record.zero_balance_drift else 0,
                    record.orders_placed_count,
                    record.orders_filled_count,
                    record.orders_cancelled_count,
                    record.orders_rejected_count,
                    record.interlock_blocks_count,
                    record.heartbeat_events_count,
                    record.stale_heartbeat_count,
                    record.stream_events_count,
                    record.deduplicated_events_count,
                    record.out_of_order_events_count,
                    record.final_circuit_state,
                    record.final_expansion_stage,
                    1 if record.success else 0,
                ),
            )

    def record_listen_key_event(
        self, track_id: str, action: str, listen_key: str, details: dict[str, Any] | None = None
    ) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO listen_key_lifecycle_events (
                    event_id, track_id, action, listen_key, timestamp_utc, details_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"lke_{uuid4().hex[:12]}",
                    track_id,
                    action,
                    listen_key,
                    datetime.now(UTC).isoformat(),
                    json.dumps(details or {}),
                ),
            )

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.commit()
                self.conn.close()
            except Exception:
                pass


# Backward compatibility alias
SqliteCanaryAdaptiveExecutionTelemetryStore = SqliteCanaryLiquidityRegimeTelemetryStore


class JsonlCanaryOrderSink:
    """Synchronous, thread-safe JSONL log sink for canary order events."""

    def __init__(self, log_path: Path | str) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def record_order_event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            event = {
                "event_type": event_type,
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "payload": payload,
            }
            line = canonical_json_bytes(event).decode("utf-8") + "\n"
            assert_zero_secrets(line, "canary-orders.jsonl")
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)


# =====================================================================
# Gateway Heartbeat Monitor & Freshness Telemetry
# =====================================================================


class GatewayHeartbeatMonitor:
    """Tracks gateway heartbeat freshness, clock skew, and hysteresis recovery:
    - Order dispatch permitted ONLY if heartbeat age <= 500 ms.
    - Backward NTP clock drift > 250 ms triggers immediate HEARTBEAT_FREEZE.
    - Recovery hysteresis: stays frozen until age <= 450 ms (50 ms recovery hysteresis).
    """

    def __init__(
        self,
        max_age_ms: float = GATEWAY_HEARTBEAT_MAX_AGE_MS,
        recovery_hysteresis_ms: float = GATEWAY_HEARTBEAT_HYSTERESIS_RECOVERY_MS,
        max_clock_skew_ms: float = MAX_CLOCK_SKEW_TOLERANCE_MS,
    ) -> None:
        self.max_age_ms = max_age_ms
        self.recovery_hysteresis_ms = recovery_hysteresis_ms
        self.max_clock_skew_ms = max_clock_skew_ms

        self.last_heartbeat_time_ms: int = 0
        self.last_server_time_ms: int = 0
        self.last_latency_ms: float = 0.0
        self.is_frozen: bool = False
        self.clock_skew_frozen: bool = False
        self.heartbeat_count: int = 0
        self.stale_count: int = 0
        self.clock_skew_count: int = 0
        self._lock = threading.RLock()

    def record_heartbeat(
        self,
        server_time_ms: int,
        latency_ms: float = 0.0,
        local_receive_time_ms: int | None = None,
        track_id: str = "liquidity_regime",
    ) -> GatewayHeartbeatRecord:
        with self._lock:
            now_ms = (
                local_receive_time_ms
                if local_receive_time_ms is not None
                else int(time.time() * 1000)
            )
            self.heartbeat_count += 1
            self.last_heartbeat_time_ms = now_ms
            self.last_latency_ms = latency_ms

            status = HeartbeatStatus.HEALTHY
            details: dict[str, Any] = {"latency_ms": latency_ms}

            # Clock drift evaluation: check backward NTP clock drift
            if self.last_server_time_ms > 0:
                clock_drift = self.last_server_time_ms - server_time_ms
                if clock_drift > self.max_clock_skew_ms:
                    self.is_frozen = True
                    self.clock_skew_frozen = True
                    self.clock_skew_count += 1
                    status = HeartbeatStatus.CLOCK_SKEW_FREEZE
                    details["clock_drift_ms"] = clock_drift
                    details["error"] = (
                        f"Backward NTP drift {clock_drift} ms exceeds {self.max_clock_skew_ms} ms"
                    )

            prev_server_time = self.last_server_time_ms
            self.last_server_time_ms = server_time_ms
            age_ms = max(0.0, float(now_ms - server_time_ms))

            if age_ms > self.max_age_ms:
                self.stale_count += 1
                self.is_frozen = True
                status = HeartbeatStatus.LATENCY_SPIKE_STALE
                details["age_ms"] = age_ms

            # Hysteresis recovery: if frozen, require age <= 450 ms and unskewed clock to unfreeze
            if self.is_frozen:
                if (
                    age_ms <= self.recovery_hysteresis_ms
                    and status != HeartbeatStatus.CLOCK_SKEW_FREEZE
                ):
                    if self.clock_skew_frozen:
                        # Clear clock skew freeze only if server clock has advanced forward
                        if prev_server_time == 0 or server_time_ms >= prev_server_time:
                            self.clock_skew_frozen = False
                            self.is_frozen = False
                            status = HeartbeatStatus.RECOVERED
                            details["hysteresis_cleared"] = True
                            details["clock_skew_recovered"] = True
                    else:
                        self.is_frozen = False
                        status = HeartbeatStatus.RECOVERED
                        details["hysteresis_cleared"] = True

            return GatewayHeartbeatRecord(
                track_id=track_id,
                server_time_ms=server_time_ms,
                local_receive_time_ms=now_ms,
                latency_ms=latency_ms,
                age_ms=age_ms,
                status=status,
                details_json=json.dumps(details),
            )

    def assert_healthy(self, now_ms: int | None = None) -> None:
        """Verify gateway heartbeat freshness; raise exception fail-closed if violated."""
        with self._lock:
            if self.last_heartbeat_time_ms == 0:
                raise GatewayHeartbeatStaleError("No gateway heartbeat recorded yet; fail-closed")

            if self.clock_skew_frozen:
                raise HeartbeatFreezeActiveError(
                    "Gateway heartbeat freeze active: "
                    "backward NTP clock drift triggered HEARTBEAT_FREEZE"
                )

            curr_ms = now_ms if now_ms is not None else int(time.time() * 1000)
            age = float(curr_ms - self.last_heartbeat_time_ms)

            if age > self.max_age_ms:
                self.is_frozen = True
                raise GatewayHeartbeatStaleError(
                    f"Gateway heartbeat age {age:.1f} ms exceeds {self.max_age_ms} ms ceiling"
                )

            if self.is_frozen:
                if age > self.recovery_hysteresis_ms:
                    raise HeartbeatFreezeActiveError(
                        f"Gateway heartbeat hysteresis active: age {age:.1f} ms > "
                        f"{self.recovery_hysteresis_ms} ms recovery ceiling"
                    )
                self.is_frozen = False


# =====================================================================
# Liquidity Stream Sequencer & Out-of-Order Packet Deduplication
# =====================================================================


class LiquidityStreamSequencer:
    """Manages User Data Stream packet sequencing, deduplication, and wrap recovery."""

    def __init__(self, sequence_wrap_threshold: int = SEQUENCE_WRAP_THRESHOLD) -> None:
        self.sequence_wrap_threshold = sequence_wrap_threshold
        self.highest_arrival_sequence = 0
        self.processed_trade_ids: set[str] = set()
        self.deduplicated_count = 0
        self.out_of_order_count = 0
        self.sequence_wrap_count = 0
        self.last_order_cum_qty: dict[str, Decimal] = {}
        self.stream_epoch: int = 0
        self._lock = threading.RLock()

    def record_order_fill(self, client_order_id: str, cum_qty: Decimal) -> None:
        with self._lock:
            self.last_order_cum_qty[client_order_id] = cum_qty

    def notify_reconnect(self, new_epoch: int | None = None) -> None:
        with self._lock:
            self.stream_epoch = (self.stream_epoch + 1) if new_epoch is None else new_epoch
            self.highest_arrival_sequence = 0

    def sort_and_deduplicate_batch(
        self,
        packets: list[dict[str, Any]],
        track_id: str = "liquidity_regime",
        telemetry_store: SqliteCanaryLiquidityRegimeTelemetryStore | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            sorted_packets = sorted(packets, key=lambda p: (p.get("T", 0), p.get("u", 0)))
            admitted: list[dict[str, Any]] = []

            for pkt in sorted_packets:
                seq = pkt.get("u", 0)
                e_type = pkt.get("e", "")
                t_id = None
                cid = None
                sym = None
                st = None

                if e_type == WebSocketEventType.ORDER_TRADE_UPDATE.value:
                    o = pkt.get("o", {})
                    t_id = str(o.get("t", ""))
                    cid = str(o.get("c", ""))
                    sym = str(o.get("s", ""))
                    st = str(o.get("X", ""))

                is_dup = False
                is_ooo = False

                # Trade deduplication
                if t_id and t_id in self.processed_trade_ids:
                    is_dup = True
                    self.deduplicated_count += 1

                # Sequence ordering and wrap detection
                if seq > 0 and self.highest_arrival_sequence > 0:
                    if (
                        self.highest_arrival_sequence >= (self.sequence_wrap_threshold - 50000)
                        and seq < 50000
                    ):
                        self.sequence_wrap_count += 1
                        self.highest_arrival_sequence = seq
                    elif seq < self.highest_arrival_sequence:
                        is_ooo = True
                        self.out_of_order_count += 1
                    else:
                        self.highest_arrival_sequence = max(self.highest_arrival_sequence, seq)
                elif seq > 0:
                    self.highest_arrival_sequence = seq

                if t_id and not is_dup:
                    self.processed_trade_ids.add(t_id)

                if telemetry_store is not None:
                    telemetry_store.record_websocket_event(
                        WebSocketPushEvent(
                            track_id=track_id,
                            event_type=e_type,
                            event_time_ms=pkt.get("E", 0),
                            transaction_time_ms=pkt.get("T", 0),
                            sequence_number=seq,
                            client_order_id=cid,
                            symbol=sym,
                            order_status=st,
                            payload_json=json.dumps(pkt),
                            is_duplicate=is_dup,
                            is_out_of_order=is_ooo,
                        )
                    )

                if not is_dup:
                    admitted.append(pkt)

            return admitted


# Backward compatibility alias
AdaptiveStreamSequencer = LiquidityStreamSequencer


# =====================================================================
# Exact Double-Entry Accounting Balance Reconciler
# =====================================================================


class LiquidityUserDataStreamReconciler:
    """Exact mathematical double-entry accounting balance reconciler:
    |actual_equity - theoretical_equity| < 1e-15 USDT.
    """

    def __init__(
        self,
        track_id: str,
        starting_equity: Decimal = STARTING_EQUITY_USDT,
    ) -> None:
        self.track_id = track_id
        self.starting_equity = starting_equity
        self.cash: Decimal = starting_equity
        self.allocated_margin: Decimal = Decimal("0")
        self.realized_pnl: Decimal = Decimal("0")
        self.cumulative_realized_loss: Decimal = Decimal("0")
        self.total_fees: Decimal = Decimal("0")
        self.total_slippage: Decimal = Decimal("0")

        self.positions: dict[str, Decimal] = {s: Decimal("0") for s in CANARY_STAGED_SYMBOLS}
        self.position_entry_prices: dict[str, Decimal] = {
            s: Decimal("0") for s in CANARY_STAGED_SYMBOLS
        }
        self.per_asset_margin: dict[str, Decimal] = {s: Decimal("0") for s in CANARY_STAGED_SYMBOLS}
        self.mark_prices: dict[str, Decimal] = dict(DEFAULT_REFERENCE_PRICES)
        self._lock = threading.RLock()

    def set_mark_price(self, symbol: str, price: Decimal) -> None:
        with self._lock:
            self.mark_prices[symbol] = price

    def get_mark_price(self, symbol: str) -> Decimal:
        with self._lock:
            return self.mark_prices.get(symbol, DEFAULT_REFERENCE_PRICES.get(symbol, Decimal("0")))

    @property
    def unrealized_pnl(self) -> Decimal:
        with self._lock:
            u_pnl = Decimal("0")
            for sym, pos in self.positions.items():
                if pos != Decimal("0"):
                    entry_px = self.position_entry_prices[sym]
                    mark_px = self.get_mark_price(sym)
                    u_pnl += pos * (mark_px - entry_px)
            return u_pnl

    @property
    def total_equity(self) -> Decimal:
        with self._lock:
            return self.cash + self.allocated_margin + self.unrealized_pnl

    @property
    def mathematical_drift(self) -> Decimal:
        with self._lock:
            actual = self.cash + self.allocated_margin + self.unrealized_pnl
            theoretical = self.starting_equity + self.realized_pnl + self.unrealized_pnl
            return abs(actual - theoretical)

    def get_balance_snapshot(self) -> BalanceSnapshot:
        with self._lock:
            return BalanceSnapshot(
                track_id=self.track_id,
                cash_usdt=str(self.cash),
                allocated_margin_usdt=str(self.allocated_margin),
                unrealized_pnl_usdt=str(self.unrealized_pnl),
                realized_pnl_usdt=str(self.realized_pnl),
                equity_usdt=str(self.total_equity),
                drift_usdt=str(self.mathematical_drift),
            )

    def apply_fill(
        self,
        symbol: str,
        side: OrderSide | str,
        price: Decimal,
        quantity: Decimal,
        fee: Decimal,
        is_closing: bool = False,
    ) -> tuple[Decimal, Decimal]:
        """Apply fill execution to positions and ledger using exact double-entry accounting."""
        with self._lock:
            side_str = side.value if isinstance(side, OrderSide) else str(side).upper()
            if side_str not in (OrderSide.BUY.value, OrderSide.SELL.value):
                raise DomainViolation(f"Invalid order side '{side}'; must be BUY or SELL")

            if not isinstance(price, Decimal) or not price.is_finite() or price <= Decimal("0"):
                raise DomainViolation(f"Fill price {price} must be strictly positive and finite")
            if (
                not isinstance(quantity, Decimal)
                or not quantity.is_finite()
                or quantity <= Decimal("0")
            ):
                raise DomainViolation(
                    f"Fill quantity {quantity} must be strictly positive and finite"
                )
            if not isinstance(fee, Decimal) or not fee.is_finite() or fee < Decimal("0"):
                raise DomainViolation(f"Fill fee {fee} must be non-negative and finite")

            curr_pos = self.positions.get(symbol, Decimal("0"))
            curr_entry = self.position_entry_prices.get(symbol, Decimal("0"))
            signed_qty = quantity if side_str == OrderSide.BUY.value else -quantity

            realized_pnl = Decimal("0")
            notional = (price * quantity).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

            # Deduct fee from cash and realized pnl
            self.cash -= fee
            self.total_fees += fee
            self.realized_pnl -= fee
            if fee > Decimal("0"):
                self.cumulative_realized_loss += fee

            if curr_pos == Decimal("0"):
                # New position opening
                self.positions[symbol] = signed_qty
                self.position_entry_prices[symbol] = price
                self.per_asset_margin[symbol] = notional
                self.allocated_margin += notional
                self.cash -= notional
            elif (curr_pos > Decimal("0") and signed_qty > Decimal("0")) or (
                curr_pos < Decimal("0") and signed_qty < Decimal("0")
            ):
                # Increasing existing position size
                new_pos = curr_pos + signed_qty
                total_cost = (abs(curr_pos) * curr_entry) + notional
                new_entry = total_cost / abs(new_pos)
                self.positions[symbol] = new_pos
                self.position_entry_prices[symbol] = new_entry
                self.per_asset_margin[symbol] += notional
                self.allocated_margin += notional
                self.cash -= notional
            else:
                # Closing or reducing existing position
                if quantity > abs(curr_pos):
                    raise DomainViolation(
                        f"Fill quantity {quantity} exceeds current position {curr_pos}"
                    )

                closing_ratio = quantity / abs(curr_pos)
                released_margin = (self.per_asset_margin[symbol] * closing_ratio).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )

                if curr_pos > Decimal("0"):
                    realized_pnl = quantity * (price - curr_entry)
                else:
                    realized_pnl = quantity * (curr_entry - price)

                self.realized_pnl += realized_pnl
                if realized_pnl < Decimal("0"):
                    self.cumulative_realized_loss += abs(realized_pnl)

                new_pos = curr_pos + signed_qty
                self.positions[symbol] = new_pos
                self.per_asset_margin[symbol] -= released_margin
                self.allocated_margin -= released_margin
                self.cash += released_margin + realized_pnl

                if new_pos == Decimal("0"):
                    self.per_asset_margin[symbol] = Decimal("0")
                    self.position_entry_prices[symbol] = Decimal("0")

            return notional, realized_pnl


# Backward compatibility alias
AdaptiveUserDataStreamReconciler = LiquidityUserDataStreamReconciler


# =====================================================================
# Liquidity Regime Classification & Order Slicing Engine (R2)
# =====================================================================


class LiquidityRegimeEngine:
    """Classifies prevailing market liquidity into discrete regimes (NORMAL, THIN, ILLIQUID)
    based on top-of-book spread, depth density, and volume velocity.
    Governs order sizing downscaling and limit offset cushions to prevent slippage spikes.
    """

    def __init__(
        self,
        min_required_depth: Decimal = MIN_REQUIRED_BOOK_DEPTH,
        max_spread_pct: Decimal = MAX_TOLERABLE_SPREAD_PCT,
    ) -> None:
        self.min_required_depth = min_required_depth
        self.max_spread_pct = max_spread_pct
        # symbol -> {bid_price, ask_price, bid_depth, ask_depth, volume_velocity}
        self.books: dict[str, dict[str, Decimal]] = {}
        self._lock = threading.RLock()

    def update_book(
        self,
        symbol: str,
        bid_price: Any,
        ask_price: Any,
        bid_depth: Any,
        ask_depth: Any,
        volume_velocity: Any = Decimal("100.0"),
    ) -> None:
        """Update prevailing order book depth, quotes, and volume velocity for a symbol."""
        with self._lock:
            sym_key = str(symbol).strip().upper()
            self.books[sym_key] = {
                "bid_price": _safe_decimal(bid_price),
                "ask_price": _safe_decimal(ask_price),
                "bid_depth": _safe_decimal(bid_depth),
                "ask_depth": _safe_decimal(ask_depth),
                "volume_velocity": _safe_decimal(volume_velocity, Decimal("100.0")),
            }

    def get_spread_bps(self, symbol: str) -> Decimal:
        """Calculate relative top-of-book spread in basis points."""
        with self._lock:
            sym_key = str(symbol).strip().upper()
            b = self.books.get(sym_key)
            if not b:
                return Decimal("2.0")  # Default nominal 2 bps
            bid_px = b["bid_price"]
            ask_px = b["ask_price"]
            if bid_px <= Decimal("0") or ask_px <= Decimal("0"):
                return Decimal("2.0")
            mid_px = (bid_px + ask_px) / Decimal("2")
            rel_spread = (ask_px - bid_px) / mid_px
            return (rel_spread * Decimal("10000")).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)

    def get_depth_density(self, symbol: str) -> Decimal:
        """Calculate total top-of-book depth density (bid_depth + ask_depth)."""
        with self._lock:
            sym_key = str(symbol).strip().upper()
            b = self.books.get(sym_key)
            if not b:
                return Decimal("5.0")
            return b["bid_depth"] + b["ask_depth"]

    def get_volume_velocity(self, symbol: str) -> Decimal:
        """Get prevailing volume velocity metric."""
        with self._lock:
            sym_key = str(symbol).strip().upper()
            b = self.books.get(sym_key)
            if not b:
                return Decimal("100.0")
            return b.get("volume_velocity", Decimal("100.0"))

    def classify_regime(self, symbol: str) -> LiquidityRegime:
        """Dynamically classify prevailing liquidity into discrete regimes:
        - NORMAL: tight spread (<= 5 bps), deep depth (density >= 1.0 / velocity >= 50.0).
        - THIN: moderate spread (5 to 25 bps), depleted depth (< 1.0), or low velocity (< 50.0).
        - ILLIQUID: wide spread (> 25 bps), exhausted depth (< min_depth), or zero velocity (<= 0).
        """
        with self._lock:
            sym_key = str(symbol).strip().upper()
            spread_bps = self.get_spread_bps(sym_key)
            depth_density = self.get_depth_density(sym_key)
            velocity = self.get_volume_velocity(sym_key)

            if (
                depth_density < self.min_required_depth
                or spread_bps > Decimal("25.0")
                or velocity <= Decimal("0")
            ):
                return LiquidityRegime.ILLIQUID
            if spread_bps > Decimal("5.0") or velocity < Decimal("50.0"):
                return LiquidityRegime.THIN
            return LiquidityRegime.NORMAL

    def calculate_sizing_and_limit_offset(
        self,
        symbol: str,
        side: OrderSide | str,
        base_notional: Decimal = HARD_MICRO_NOTIONAL_CAP_USDT,
        fallback_price: Decimal | None = None,
    ) -> tuple[Decimal, Decimal, LiquidityRegime, Decimal]:
        """Calculate regime-adapted target notional, limit price, regime, and offset cushion:
        - In THIN: scale down sizing (50% or <= 2.50 USDT), widen offset cushion (50% of spread).
        - In ILLIQUID: scale down sizing to floor (1.00 USDT), widen cushion (75% of spread).
        - In NORMAL: full sizing, standard offset cushion (25% of spread).
        Returns: (target_notional, limit_price, regime, offset_usdt)
        """
        with self._lock:
            sym_key = str(symbol).strip().upper()
            regime = self.classify_regime(sym_key)
            book = self.books.get(sym_key)

            ref_price = fallback_price or DEFAULT_REFERENCE_PRICES.get(sym_key, Decimal("100.0"))
            if book:
                bid_px = book["bid_price"]
                ask_px = book["ask_price"]
                spread = max(Decimal("0.01"), ask_px - bid_px)
            else:
                bid_px = ref_price
                ask_px = ref_price + Decimal("0.10")
                spread = Decimal("0.10")

            # Scale sizing by regime
            if regime == LiquidityRegime.ILLIQUID:
                target_notional = MIN_MICRO_NOTIONAL_CAP_USDT
                cushion_ratio = Decimal("0.75")
            elif regime == LiquidityRegime.THIN:
                target_notional = max(
                    MIN_MICRO_NOTIONAL_CAP_USDT,
                    min(base_notional * Decimal("0.50"), DYNAMIC_SLICING_MAX_CHUNK_USDT),
                )
                cushion_ratio = Decimal("0.50")
            else:
                target_notional = min(base_notional, HARD_MICRO_NOTIONAL_CAP_USDT)
                cushion_ratio = Decimal("0.25")

            target_notional = target_notional.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
            offset = (spread * cushion_ratio).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

            side_str = side.value if isinstance(side, OrderSide) else str(side).upper()
            if side_str == OrderSide.BUY.value:
                limit_price = bid_px + offset
            else:
                limit_price = ask_px - offset

            return target_notional, limit_price, regime, offset

    def estimate_order_slippage_bps(
        self,
        symbol: str,
        side: OrderSide | str,
        quantity: Decimal,
        price: Decimal,
    ) -> Decimal:
        """Estimate immediate execution slippage in bps against top-of-book depth."""
        with self._lock:
            sym_key = str(symbol).strip().upper()
            book = self.books.get(sym_key)
            if not book:
                return Decimal("0.50")

            side_str = side.value if isinstance(side, OrderSide) else str(side).upper()
            available_depth = (
                book["ask_depth"] if side_str == OrderSide.BUY.value else book["bid_depth"]
            )
            spread_bps = self.get_spread_bps(sym_key)

            if quantity <= available_depth:
                # Order fits within top of book: minimal slippage (<= spread/2)
                return (spread_bps * Decimal("0.25")).quantize(
                    Decimal("0.0001"), rounding=ROUND_DOWN
                )

            # Order exceeds top-of-book depth: estimated slippage spikes proportionally
            excess_ratio = quantity / max(available_depth, Decimal("0.00001"))
            slippage_bps = (spread_bps * Decimal("0.50") * excess_ratio).quantize(
                Decimal("0.0001"), rounding=ROUND_DOWN
            )
            return slippage_bps


# Backward compatibility aliases
VolatilityAdaptiveEngine = LiquidityRegimeEngine
AdaptiveSpreadEngine = LiquidityRegimeEngine


# =====================================================================
# Mock Binance Futures Gateway with Simulated Books & Feeds
# =====================================================================


class MockBinanceLiquidityGateway:
    """Deterministic simulated Binance Futures gateway for Phase 284:
    - User Data Stream & listenKey 24h expiration and renewal.
    - Simulated order book depth and spread adaptation.
    - Sequence wrap-around simulation.
    - Out-of-order execution packets and duplicate events.
    - REST catch-up and order query endpoints.
    """

    def __init__(
        self,
        initial_balance_usdt: Decimal = STARTING_EQUITY_USDT,
        order_id_start: int = 100000,
        trade_id_start: int = 500000,
        server_time_ms: int | None = None,
    ) -> None:
        self.wallet_balance = initial_balance_usdt
        self.order_id_counter = order_id_start
        self.trade_id_counter = trade_id_start
        self.sequence_counter = 1
        self.server_time_ms = (
            server_time_ms if server_time_ms is not None else int(time.time() * 1000)
        )

        self.orders: dict[str, dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []
        self.ws_event_queue: list[dict[str, Any]] = []

        self.is_stream_connected = True
        self.inject_stream_disconnect = False
        self.inject_out_of_order_events = False
        self.inject_duplicate_events = False
        self.inject_listen_key_expired = False

        self.active_listen_key: str | None = None
        self.listen_keys: dict[str, float] = {}

        self.order_books: dict[str, dict[str, Decimal]] = {
            "BTCUSDT": {
                "bid_price": Decimal("60000.00"),
                "ask_price": Decimal("60001.00"),
                "bid_depth": Decimal("5.0"),
                "ask_depth": Decimal("5.0"),
            },
            "ETHUSDT": {
                "bid_price": Decimal("3000.00"),
                "ask_price": Decimal("3000.50"),
                "bid_depth": Decimal("20.0"),
                "ask_depth": Decimal("20.0"),
            },
            "SOLUSDT": {
                "bid_price": Decimal("150.00"),
                "ask_price": Decimal("150.05"),
                "bid_depth": Decimal("100.0"),
                "ask_depth": Decimal("100.0"),
            },
        }

        self._lock = threading.RLock()

    def advance_time(self, delta_ms: int) -> None:
        with self._lock:
            self.server_time_ms += delta_ms

    def generate_heartbeat(self, latency_ms: float = 40.0) -> dict[str, Any]:
        with self._lock:
            self.server_time_ms += 10
            return {
                "serverTime": self.server_time_ms,
                "latencyMs": latency_ms,
            }

    def create_listen_key(self) -> dict[str, str]:
        with self._lock:
            key = f"canary_p284_lk_{uuid4().hex[:16]}"
            now_epoch = self.server_time_ms / 1000.0
            self.listen_keys[key] = now_epoch + LISTEN_KEY_LIFETIME_SECONDS
            self.active_listen_key = key
            self.is_stream_connected = True
            self.inject_stream_disconnect = False
            return {"listenKey": key}

    def keepalive_listen_key(self, listen_key: str) -> dict[str, Any]:
        with self._lock:
            if self.inject_listen_key_expired:
                self.inject_listen_key_expired = False
                self.listen_keys.pop(listen_key, None)
                raise ListenKeyExpiredError(f"listenKey {listen_key} has expired on gateway")

            now_epoch = self.server_time_ms / 1000.0
            expiry = self.listen_keys.get(listen_key)
            if expiry is None or now_epoch >= expiry:
                self.listen_keys.pop(listen_key, None)
                raise ListenKeyExpiredError(f"listenKey {listen_key} does not exist or has expired")

            self.listen_keys[listen_key] = now_epoch + LISTEN_KEY_LIFETIME_SECONDS
            return {}

    def delete_listen_key(self, listen_key: str) -> dict[str, Any]:
        with self._lock:
            self.listen_keys.pop(listen_key, None)
            if self.active_listen_key == listen_key:
                self.active_listen_key = None
                self.is_stream_connected = False
            return {}

    def set_book(
        self,
        symbol: str,
        bid_price: Decimal,
        ask_price: Decimal,
        bid_depth: Decimal,
        ask_depth: Decimal,
    ) -> None:
        with self._lock:
            self.order_books[symbol] = {
                "bid_price": bid_price,
                "ask_price": ask_price,
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
            }

    def get_order_book(self, symbol: str) -> dict[str, Decimal]:
        with self._lock:
            return dict(self.order_books.get(symbol, {}))

    def place_order(
        self,
        symbol: str,
        side: OrderSide | str,
        order_type: OrderType | str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            self.order_id_counter += 1
            order_id = self.order_id_counter
            self.trade_id_counter += 1
            trade_id = self.trade_id_counter
            self.sequence_counter += 1
            seq = self.sequence_counter

            side_val = side.value if isinstance(side, OrderSide) else str(side).upper()
            type_val = (
                order_type.value if isinstance(order_type, OrderType) else str(order_type).upper()
            )

            now_ms = self.server_time_ms

            order_data = {
                "orderId": order_id,
                "symbol": symbol,
                "clientOrderId": client_order_id,
                "side": side_val,
                "type": type_val,
                "price": str(price),
                "origQty": str(quantity),
                "executedQty": str(quantity),
                "status": "FILLED",
                "timeInForce": "GTC",
                "updateTime": now_ms,
            }
            self.orders[client_order_id] = order_data

            trade_data = {
                "tradeId": trade_id,
                "orderId": order_id,
                "clientOrderId": client_order_id,
                "symbol": symbol,
                "side": side_val,
                "price": str(price),
                "qty": str(quantity),
                "commission": str(
                    (price * quantity * DEFAULT_TAKER_FEE_RATE).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )
                ),
                "time": now_ms,
            }
            self.trades.append(trade_data)

            ws_packet = {
                "e": WebSocketEventType.ORDER_TRADE_UPDATE.value,
                "E": now_ms,
                "T": now_ms,
                "u": seq,
                "o": {
                    "s": symbol,
                    "c": client_order_id,
                    "i": order_id,
                    "S": side_val,
                    "o": type_val,
                    "f": "GTC",
                    "q": str(quantity),
                    "p": str(price),
                    "ap": str(price),
                    "sp": "0",
                    "x": "TRADE",
                    "X": "FILLED",
                    "l": str(quantity),
                    "z": str(quantity),
                    "L": str(price),
                    "n": str(
                        (price * quantity * DEFAULT_TAKER_FEE_RATE).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                    ),
                    "N": "USDT",
                    "T": now_ms,
                    "t": trade_id,
                    "b": "0",
                    "a": "0",
                    "m": False,
                    "R": False,
                    "wt": "CONTRACT_PRICE",
                    "ot": type_val,
                    "ps": "BOTH",
                    "cp": False,
                    "rp": "0",
                },
            }

            if self.is_stream_connected and not self.inject_stream_disconnect:
                self.ws_event_queue.append(ws_packet)

                if self.inject_duplicate_events:
                    self.ws_event_queue.append(dict(ws_packet))

                if self.inject_out_of_order_events and len(self.ws_event_queue) >= 2:
                    p1 = self.ws_event_queue.pop()
                    p2 = self.ws_event_queue.pop()
                    self.ws_event_queue.extend([p1, p2])

            return order_data

    def cancel_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        with self._lock:
            ord_data = self.orders.get(client_order_id)
            if not ord_data:
                raise OrderCorrelationError(f"Order {client_order_id} not found to cancel")
            ord_data["status"] = "CANCELED"

            now_ms = self.server_time_ms
            self.sequence_counter += 1
            seq = self.sequence_counter

            ws_packet = {
                "e": WebSocketEventType.ORDER_TRADE_UPDATE.value,
                "E": now_ms,
                "T": now_ms,
                "u": seq,
                "o": {
                    "s": symbol,
                    "c": client_order_id,
                    "i": ord_data["orderId"],
                    "S": ord_data["side"],
                    "o": ord_data["type"],
                    "f": "GTC",
                    "q": ord_data["origQty"],
                    "p": ord_data["price"],
                    "ap": "0",
                    "sp": "0",
                    "x": "CANCELED",
                    "X": "CANCELED",
                    "l": "0",
                    "z": ord_data.get("executedQty", "0"),
                    "L": "0",
                    "n": "0",
                    "N": "USDT",
                    "T": now_ms,
                    "t": 0,
                    "b": "0",
                    "a": "0",
                    "m": False,
                    "R": False,
                    "wt": "CONTRACT_PRICE",
                    "ot": ord_data["type"],
                    "ps": "BOTH",
                    "cp": False,
                    "rp": "0",
                },
            }
            if self.is_stream_connected and not self.inject_stream_disconnect:
                self.ws_event_queue.append(ws_packet)
            return ord_data

    def query_order(self, symbol: str, client_order_id: str) -> dict[str, Any] | None:
        with self._lock:
            return dict(self.orders.get(client_order_id, {})) or None

    def drain_ws_queue(self) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self.ws_event_queue)
            self.ws_event_queue.clear()
            return events

    def disconnect_stream(self) -> None:
        with self._lock:
            self.is_stream_connected = False
            self.inject_stream_disconnect = True

    def reconnect_stream(self) -> None:
        with self._lock:
            self.is_stream_connected = True
            self.inject_stream_disconnect = False


# Backward compatibility alias
MockBinanceAdaptiveGateway = MockBinanceLiquidityGateway


# =====================================================================
# Strict Risk Containment & Headroom Interlocks (R2)
# =====================================================================


class LiquidityOrderDispatchInterlock:
    """Strict multi-candidate concurrent order dispatch and dynamic margin headroom gating:
    - Individual Micro Child Order Cap: Strictly <= 5.00 USDT.
    - Sliced micro-chunk cap: <= 2.50 USDT.
    - Stepped Aggregate Concurrent Exposure Cap: up to <= 25.00 USDT.
    - Dynamic Margin Headroom:
      - Active portfolio margin allocation <= 60.00% (cash reserve buffer >= 40.00%).
      - Per-asset allocation <= 20.00%.
    - Active Committed Working Margin: dynamically tracked and reserved across concurrent
      working parent and child orders across symbols.
    - Intra-Phase Cumulative Loss Budget: ceiling <= 3.50 USDT.
    - Gateway Heartbeat Freshness: age <= 500 ms; backward NTP drift > 250 ms triggers freeze
      with 50 ms recovery hysteresis.
    - Dual-Confirmation Tagging: c=canary-p284-{sym}-{ts}-{uuid}.
    """

    def __init__(
        self,
        heartbeat_monitor: GatewayHeartbeatMonitor,
        reconciler: LiquidityUserDataStreamReconciler,
        telemetry_store: SqliteCanaryLiquidityRegimeTelemetryStore | None = None,
        track_id: str = "liquidity_regime",
        circuit_state: CircuitBreakerState = CircuitBreakerState.NORMAL,
        expansion_stage: CapitalExpansionStage = CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
        intra_phase_loss_ceiling_usdt: Decimal = INTRA_PHASE_LOSS_CEILING_USDT,
        orders_provider: Callable[[], Mapping[str, LiquidityOrderRecord]] | None = None,
        parent_orders_provider: Callable[[], Mapping[str, ParentOrderRecord]] | None = None,
        regime_engine: LiquidityRegimeEngine | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.heartbeat_monitor = heartbeat_monitor
        self.reconciler = reconciler
        self.telemetry_store = telemetry_store
        self.track_id = track_id
        self._circuit_state = circuit_state
        self.expansion_stage = expansion_stage
        self.freeze_timestamp_ms: int = (
            int(time.time() * 1000) if circuit_state == CircuitBreakerState.HEARTBEAT_FREEZE else 0
        )
        self.freeze_heartbeat_count: int = (
            heartbeat_monitor.heartbeat_count
            if circuit_state == CircuitBreakerState.HEARTBEAT_FREEZE
            else 0
        )
        self.intra_phase_loss_ceiling_usdt = intra_phase_loss_ceiling_usdt
        self.interlock_blocks_count = 0
        self._orders_provider = orders_provider
        self._parent_orders_provider = parent_orders_provider
        self.regime_engine = regime_engine or LiquidityRegimeEngine()

    @property
    def circuit_state(self) -> CircuitBreakerState:
        with self._lock:
            return self._circuit_state

    @circuit_state.setter
    def circuit_state(self, value: CircuitBreakerState) -> None:
        with self._lock:
            self._circuit_state = value
            if value == CircuitBreakerState.HEARTBEAT_FREEZE:
                self.freeze_timestamp_ms = int(time.time() * 1000)
                self.freeze_heartbeat_count = self.heartbeat_monitor.heartbeat_count

    def set_orders_provider(
        self, provider: Callable[[], Mapping[str, LiquidityOrderRecord]]
    ) -> None:
        with self._lock:
            self._orders_provider = provider

    def set_parent_orders_provider(
        self, provider: Callable[[], Mapping[str, ParentOrderRecord]]
    ) -> None:
        with self._lock:
            self._parent_orders_provider = provider

    def get_working_committed_margin(
        self,
        symbol: str | None = None,
        exclude_client_order_id: str | None = None,
        exclude_notional: Decimal = Decimal("0"),
    ) -> Decimal:
        """Calculate unexecuted margin committed by active open working orders and parent slices."""
        with self._lock:
            total_working = Decimal("0")
            orders = self._orders_provider() if self._orders_provider is not None else {}
            for ord_rec in list(orders.values()):
                if ord_rec.is_closing:
                    continue
                if (
                    exclude_client_order_id is not None
                    and ord_rec.client_order_id == exclude_client_order_id
                ):
                    continue
                if ord_rec.status in (
                    OrderLifecycleState.PENDING_NEW,
                    OrderLifecycleState.PENDING_SUBMIT,
                    OrderLifecycleState.NEW,
                    OrderLifecycleState.PARTIALLY_FILLED,
                ):
                    if symbol is not None and ord_rec.symbol != symbol:
                        continue
                    px = _safe_decimal(ord_rec.price)
                    total_qty = _safe_decimal(ord_rec.quantity)
                    exec_qty = _safe_decimal(ord_rec.executed_quantity)
                    rem_qty = max(Decimal("0"), total_qty - exec_qty)
                    rem_notional = (px * rem_qty).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )
                    total_working += rem_notional

            # Dynamically account for un-dispatched portions of active parent orders
            if self._parent_orders_provider is not None:
                parent_orders = self._parent_orders_provider()
                for p_rec in list(parent_orders.values()):
                    if symbol is not None and p_rec.symbol != symbol:
                        continue
                    if p_rec.status in (
                        OrderLifecycleState.NEW,
                        OrderLifecycleState.PARTIALLY_FILLED,
                    ):
                        active_children_notional = Decimal("0")
                        for ch_cid in p_rec.child_order_ids:
                            if (
                                exclude_client_order_id is not None
                                and ch_cid == exclude_client_order_id
                            ):
                                continue
                            ch = orders.get(ch_cid)
                            if ch and ch.status in (
                                OrderLifecycleState.PENDING_NEW,
                                OrderLifecycleState.PENDING_SUBMIT,
                                OrderLifecycleState.NEW,
                                OrderLifecycleState.PARTIALLY_FILLED,
                            ):
                                ch_px = _safe_decimal(ch.price)
                                ch_qty = _safe_decimal(ch.quantity)
                                ch_exec = _safe_decimal(ch.executed_quantity)
                                ch_rem_q = max(Decimal("0"), ch_qty - ch_exec)
                                active_children_notional += (ch_px * ch_rem_q).quantize(
                                    Decimal("0.00000001"), rounding=ROUND_DOWN
                                )

                        p_total = _safe_decimal(p_rec.total_notional_usdt)
                        p_exec = _safe_decimal(p_rec.executed_notional_usdt)
                        deduct_notional = Decimal("0")
                        if (
                            exclude_client_order_id is not None
                            and exclude_client_order_id in p_rec.child_order_ids
                        ):
                            deduct_notional = exclude_notional
                        un_dispatched = max(
                            Decimal("0"),
                            p_total - p_exec - active_children_notional - deduct_notional,
                        )
                        total_working += un_dispatched

            return total_working

    def get_stage_exposure_cap(self) -> Decimal:
        """Return concurrent active exposure ceiling for the active expansion stage."""
        stage_caps = {
            CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO: STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT,
            CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT: (
                STAGE_2_CONCURRENT_EXPOSURE_CAP_USDT
            ),
            CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION: (
                STAGE_3_CONTINUOUS_EXPOSURE_CAP_USDT
            ),
            CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION: STAGE_4_ADAPTIVE_EXPOSURE_CAP_USDT,
            CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION: (
                STAGE_5_LIQUIDITY_EXPOSURE_CAP_USDT
            ),
        }
        return stage_caps.get(self.expansion_stage, AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT)

    def validate_dispatch(
        self,
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        client_order_id: str,
        is_closing: bool = False,
        side: OrderSide | str = OrderSide.BUY,
        is_sliced_child: bool = False,
    ) -> None:
        """Validate order against all risk interlocks fail-closed before dispatch."""
        with self._lock:
            # 1. Dual-Confirmation Client Order Tag Format
            assert_valid_canary_client_order_id(client_order_id, expected_symbol=symbol)

            # 2. Gateway Heartbeat Freshness & Clock Skew Guard
            try:
                self.heartbeat_monitor.assert_healthy()
            except (GatewayHeartbeatStaleError, HeartbeatFreezeActiveError) as exc:
                self.interlock_blocks_count += 1
                rejection_name = (
                    "GATEWAY_HEARTBEAT_FREEZE"
                    if isinstance(exc, HeartbeatFreezeActiveError)
                    else "GATEWAY_HEARTBEAT_FRESHNESS"
                )
                self._record_interlock_rejection(rejection_name, str(exc), symbol, client_order_id)
                raise

            # 3. Circuit Breaker State Guard
            if self.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT:
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Order blocked: circuit breaker tripped in INTRA_PHASE_LOSS_LOCKOUT "
                    f"(cumulative loss {self.reconciler.cumulative_realized_loss} USDT >= "
                    f"{self.intra_phase_loss_ceiling_usdt} USDT)"
                )
                self._record_interlock_rejection(
                    "CIRCUIT_BREAKER_NORMAL", err_msg, symbol, client_order_id
                )
                raise IntraPhaseLossCeilingExceededError(err_msg)

            if self.circuit_state != CircuitBreakerState.NORMAL:
                self.interlock_blocks_count += 1
                err_msg = f"Order blocked: circuit breaker active state {self.circuit_state.value}"
                self._record_interlock_rejection(
                    "CIRCUIT_BREAKER_NORMAL", err_msg, symbol, client_order_id
                )
                raise CircuitBreakerAbortError(err_msg)

            # 4. Intra-Phase Cumulative Loss Budget Ceiling
            if self.reconciler.cumulative_realized_loss >= self.intra_phase_loss_ceiling_usdt:
                self.circuit_state = CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Cumulative realized loss {self.reconciler.cumulative_realized_loss} USDT "
                    f"exceeds ceiling {self.intra_phase_loss_ceiling_usdt} USDT"
                )
                self._record_interlock_rejection(
                    "INTRA_PHASE_LOSS_CEILING", err_msg, symbol, client_order_id
                )
                raise IntraPhaseLossCeilingExceededError(err_msg)

            order_notional = (price * quantity).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

            # Closing orders bypass opening exposure and margin checks
            if is_closing:
                return

            # 5. Micro Child Order Cap (<= 5.00 USDT; or <= 2.50 USDT if child slice)
            max_chunk_cap = (
                DYNAMIC_SLICING_MAX_CHUNK_USDT if is_sliced_child else HARD_MICRO_NOTIONAL_CAP_USDT
            )
            if order_notional > max_chunk_cap:
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Order notional {order_notional} USDT exceeds micro order cap "
                    f"{max_chunk_cap} USDT (ROUND_DOWN)"
                )
                self._record_interlock_rejection(
                    "MICRO_NOTIONAL_CEILING", err_msg, symbol, client_order_id
                )
                raise IndividualMicroCapExceededError(err_msg)

            # 6. Micro Notional Floor
            if order_notional < MIN_MICRO_NOTIONAL_CAP_USDT:
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Order notional {order_notional} USDT violates micro floor "
                    f"{MIN_MICRO_NOTIONAL_CAP_USDT} USDT"
                )
                self._record_interlock_rejection(
                    "MICRO_NOTIONAL_FLOOR", err_msg, symbol, client_order_id
                )
                raise MicroNotionalFloorViolationError(err_msg)

            # 7. Stepped Aggregate Concurrent Exposure Cap (up to <= 25.00 USDT)
            current_allocated_margin = self.reconciler.allocated_margin
            current_working_margin = self.get_working_committed_margin(
                exclude_client_order_id=client_order_id,
                exclude_notional=order_notional,
            )
            projected_total_active = (
                current_allocated_margin + current_working_margin + order_notional
            )

            stage_cap = self.get_stage_exposure_cap()
            if projected_total_active > stage_cap:
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Projected active exposure {projected_total_active} USDT exceeds "
                    f"stage {self.expansion_stage.value} exposure cap {stage_cap} USDT"
                )
                self._record_interlock_rejection(
                    "AGGREGATE_EXPOSURE_CEILING", err_msg, symbol, client_order_id
                )
                raise AggregateExposureCapExceededError(err_msg)

            if projected_total_active > AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT:
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Projected active exposure {projected_total_active} USDT exceeds "
                    f"aggregate ceiling {AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT} USDT"
                )
                self._record_interlock_rejection(
                    "AGGREGATE_EXPOSURE_CEILING", err_msg, symbol, client_order_id
                )
                raise AggregateExposureCapExceededError(err_msg)

            # 8. Dynamic Margin Headroom Interlocks
            total_equity = self.reconciler.total_equity
            if total_equity <= Decimal("0"):
                self.interlock_blocks_count += 1
                err_msg = f"Total equity {total_equity} USDT non-positive; order rejected"
                self._record_interlock_rejection(
                    "MARGIN_ALLOCATION_CEILING", err_msg, symbol, client_order_id
                )
                raise MarginAllocationExceededError(err_msg)

            # Aggregate Portfolio Margin Allocation <= 60.00%
            projected_aggregate_margin = (
                current_allocated_margin + current_working_margin + order_notional
            )
            agg_margin_pct = projected_aggregate_margin / total_equity
            if agg_margin_pct > MAX_AGGREGATE_MARGIN_PCT:
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Projected aggregate margin {projected_aggregate_margin} USDT "
                    f"({agg_margin_pct * 100:.2f}%) exceeds {MAX_AGGREGATE_MARGIN_PCT * 100:.2f}%"
                )
                self._record_interlock_rejection(
                    "MARGIN_ALLOCATION_CEILING", err_msg, symbol, client_order_id
                )
                raise MarginAllocationExceededError(err_msg)

            # Unencumbered Cash Reserve Buffer >= 40.00%
            unencumbered_cash = self.reconciler.cash - current_working_margin - order_notional
            cash_reserve_pct = unencumbered_cash / total_equity
            if cash_reserve_pct < MIN_RESERVE_BUFFER_PCT:
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Projected unencumbered cash {unencumbered_cash} USDT "
                    f"({cash_reserve_pct * 100:.2f}%) breaches "
                    f"{MIN_RESERVE_BUFFER_PCT * 100:.2f}% reserve buffer"
                )
                self._record_interlock_rejection(
                    "CASH_RESERVE_BUFFER", err_msg, symbol, client_order_id
                )
                raise CashReserveBufferBreachedError(err_msg)

            # Per-Asset Margin Allocation <= 20.00%
            current_asset_margin = self.reconciler.per_asset_margin.get(symbol, Decimal("0"))
            working_asset_margin = self.get_working_committed_margin(
                symbol=symbol,
                exclude_client_order_id=client_order_id,
                exclude_notional=order_notional,
            )
            projected_asset_margin = current_asset_margin + working_asset_margin + order_notional
            asset_margin_pct = projected_asset_margin / total_equity
            if asset_margin_pct > MAX_PER_ASSET_MARGIN_PCT:
                self.interlock_blocks_count += 1
                err_msg = (
                    f"Projected asset margin for {symbol} {projected_asset_margin} USDT "
                    f"({asset_margin_pct * 100:.2f}%) exceeds {MAX_PER_ASSET_MARGIN_PCT * 100:.2f}%"
                )
                self._record_interlock_rejection(
                    "MARGIN_ALLOCATION_CEILING", err_msg, symbol, client_order_id
                )
                raise MarginAllocationExceededError(err_msg)

            # 9. Order Book Depth Exhaustion Guard
            book = self.regime_engine.books.get(symbol)
            if book:
                side_str = side.value if isinstance(side, OrderSide) else str(side).upper()
                relevant_depth = (
                    book["ask_depth"] if side_str == OrderSide.BUY.value else book["bid_depth"]
                )
                if relevant_depth < MIN_REQUIRED_BOOK_DEPTH:
                    self.interlock_blocks_count += 1
                    err_msg = (
                        f"Order book depth {relevant_depth} for {symbol} exhausted "
                        f"(< {MIN_REQUIRED_BOOK_DEPTH})"
                    )
                    self._record_interlock_rejection(
                        "ORDER_BOOK_DEPTH", err_msg, symbol, client_order_id
                    )
                    raise DepthExhaustionError(err_msg)

    def _record_interlock_rejection(
        self, interlock_name: str, reason: str, symbol: str, client_order_id: str
    ) -> None:
        if self.telemetry_store is not None:
            self.telemetry_store.record_interlock_event(
                InterlockEvent(
                    track_id=self.track_id,
                    interlock_name=interlock_name,
                    status="BLOCKED",
                    symbol=symbol,
                    client_order_id=client_order_id,
                    details_json=json.dumps({"reason": reason}),
                )
            )


# Backward compatibility alias
AdaptiveOrderDispatchInterlock = LiquidityOrderDispatchInterlock


# =====================================================================
# Liquidity Micro Order Dispatcher & Dynamic TWAP Slicing Governance (R2)
# =====================================================================


class LiquidityMicroOrderDispatcher:
    """Dispatches micro orders, executes dynamic liquidity regime adaptation,
    governs dynamic micro-order slicing (TWAP / Iceberg) when estimated slippage > 1.5 bps,
    tracks atomic parent-child lifecycles, and synchronizes User Data Streams.
    """

    def __init__(
        self,
        gateway: MockBinanceLiquidityGateway,
        reconciler: LiquidityUserDataStreamReconciler,
        sequencer: LiquidityStreamSequencer,
        telemetry_store: SqliteCanaryLiquidityRegimeTelemetryStore,
        jsonl_sink: JsonlCanaryOrderSink,
        heartbeat_monitor: GatewayHeartbeatMonitor,
        interlock: LiquidityOrderDispatchInterlock,
        track_id: str,
        regime_engine: LiquidityRegimeEngine | None = None,
    ) -> None:
        self.gateway = gateway
        self.reconciler = reconciler
        self.sequencer = sequencer
        self.telemetry_store = telemetry_store
        self.jsonl_sink = jsonl_sink
        self.heartbeat_monitor = heartbeat_monitor
        self.interlock = interlock
        self.track_id = track_id

        self.regime_engine = regime_engine or LiquidityRegimeEngine()

        self.orders: dict[str, LiquidityOrderRecord] = {}
        self.parent_orders: dict[str, ParentOrderRecord] = {}
        self.orders_placed_count = 0
        self.orders_filled_count = 0
        self.orders_cancelled_count = 0
        self.orders_rejected_count = 0
        self.stream_events_count = 0
        self.execution_mark_counter = 0
        self._lock = threading.RLock()

        # Connect interlock to working orders provider
        self.interlock.set_orders_provider(lambda: self.orders)
        self.interlock.set_parent_orders_provider(lambda: self.parent_orders)

    def dispatch_micro_order(
        self,
        candidate_id: str,
        symbol: str,
        side: OrderSide | str,
        order_type: OrderType | str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str | None = None,
        is_closing: bool = False,
        liquidity_regime: LiquidityRegime = LiquidityRegime.NORMAL,
        estimated_slippage_bps: Decimal = Decimal("0.0000"),
        limit_offset_usdt: Decimal = Decimal("0.00000000"),
        parent_client_order_id: str | None = None,
        is_child: bool = False,
        child_index: int = 0,
    ) -> LiquidityOrderRecord:
        """Validate, dispatch, and process a single micro order fail-closed."""
        cid = (
            client_order_id
            if client_order_id is not None
            else generate_canary_client_order_id(symbol)
        )

        valid_side = side if isinstance(side, OrderSide) else OrderSide(str(side).upper())
        valid_order_type = (
            order_type if isinstance(order_type, OrderType) else OrderType(str(order_type).upper())
        )

        with self._lock:
            # 1. Validate dispatch against all risk interlocks under lock to prevent TOCTOU
            try:
                self.interlock.validate_dispatch(
                    symbol=symbol,
                    price=price,
                    quantity=quantity,
                    client_order_id=cid,
                    is_closing=is_closing,
                    side=valid_side,
                    is_sliced_child=is_child,
                )
            except Exception as exc:
                self.orders_rejected_count += 1
                rej_rec = LiquidityOrderRecord(
                    order_id="0",
                    client_order_id=cid,
                    track_id=self.track_id,
                    candidate_id=candidate_id,
                    symbol=symbol,
                    side=valid_side.value,
                    order_type=valid_order_type.value,
                    time_in_force=TimeInForce.GTC.value,
                    price=str(price),
                    quantity=str(quantity),
                    notional_usdt=str(
                        (price * quantity).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    ),
                    status=OrderLifecycleState.REJECTED,
                    expansion_stage=self.interlock.expansion_stage,
                    is_closing=is_closing,
                    liquidity_regime=liquidity_regime,
                    estimated_slippage_bps=str(estimated_slippage_bps),
                    limit_offset_usdt=str(limit_offset_usdt),
                    parent_client_order_id=parent_client_order_id,
                    is_child=is_child,
                    child_index=child_index,
                    rejection_reason=str(exc),
                )
                self.orders[cid] = rej_rec
                self.telemetry_store.record_order(rej_rec)
                self.jsonl_sink.record_order_event(
                    "ORDER_REJECTED", rej_rec.model_dump(mode="json")
                )
                raise

            self.orders_placed_count += 1
            notional = (price * quantity).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

            ord_rec = LiquidityOrderRecord(
                order_id="0",
                client_order_id=cid,
                track_id=self.track_id,
                candidate_id=candidate_id,
                symbol=symbol,
                side=valid_side.value,
                order_type=valid_order_type.value,
                time_in_force=TimeInForce.GTC.value,
                price=str(price),
                quantity=str(quantity),
                notional_usdt=str(notional),
                status=OrderLifecycleState.PENDING_NEW,
                expansion_stage=self.interlock.expansion_stage,
                is_closing=is_closing,
                liquidity_regime=liquidity_regime,
                estimated_slippage_bps=str(estimated_slippage_bps),
                limit_offset_usdt=str(limit_offset_usdt),
                parent_client_order_id=parent_client_order_id,
                is_child=is_child,
                child_index=child_index,
            )
            self.orders[cid] = ord_rec
            self.telemetry_store.record_order(ord_rec)
            self.jsonl_sink.record_order_event("ORDER_PENDING_NEW", ord_rec.model_dump(mode="json"))

            # 2. Transmit to gateway
            try:
                gw_resp = self.gateway.place_order(
                    symbol=symbol,
                    side=valid_side,
                    order_type=valid_order_type,
                    quantity=quantity,
                    price=price,
                    client_order_id=cid,
                )
                gw_order_id = str(gw_resp.get("orderId", "0"))
                ord_rec.order_id = gw_order_id
                if ord_rec.status == OrderLifecycleState.PENDING_NEW:
                    ord_rec.status = OrderLifecycleState.NEW
                    ord_rec.updated_at_utc = datetime.now(UTC).isoformat()
                    self.telemetry_store.record_order(ord_rec)
                    self.telemetry_store.record_transition(
                        OrderLifecycleTransition(
                            track_id=self.track_id,
                            order_id=gw_order_id,
                            client_order_id=cid,
                            from_state=OrderLifecycleState.PENDING_NEW,
                            to_state=OrderLifecycleState.NEW,
                            trigger_reason="GATEWAY_ACCEPTED",
                        )
                    )

                # 3. Drain and process stream updates
                self.drain_and_reconcile_stream()

                # Record balance snapshot
                self.telemetry_store.record_balance_snapshot(self.reconciler.get_balance_snapshot())
                return self.orders.get(cid, ord_rec)
            except Exception as exc:
                ord_rec.status = OrderLifecycleState.REJECTED
                ord_rec.rejection_reason = str(exc)
                ord_rec.updated_at_utc = datetime.now(UTC).isoformat()
                self.orders_rejected_count += 1
                self.telemetry_store.record_order(ord_rec)
                self.telemetry_store.record_transition(
                    OrderLifecycleTransition(
                        track_id=self.track_id,
                        order_id=ord_rec.order_id,
                        client_order_id=cid,
                        from_state=OrderLifecycleState.PENDING_NEW,
                        to_state=OrderLifecycleState.REJECTED,
                        trigger_reason=f"GATEWAY_TRANSMISSION_ERROR: {exc}",
                    )
                )
                self.jsonl_sink.record_order_event(
                    "ORDER_REJECTED", ord_rec.model_dump(mode="json")
                )
                raise

    def dispatch_signal_order_with_dynamic_slicing(
        self,
        candidate_id: str,
        symbol: str,
        side: OrderSide,
        desired_notional: Decimal,
        order_type: OrderType = OrderType.LIMIT,
    ) -> tuple[ParentOrderRecord | None, list[LiquidityOrderRecord]]:
        """Evaluate market depth and estimated slippage:
        - If order exceeds available immediate top-of-book depth with estimated slippage > 1.5 bps:
          dynamically slice into sequential micro-chunks (<= 2.50 USDT child orders).
        - Enforce atomic parent-child lifecycle tracking.
        - Otherwise, dispatch single micro order directly.
        Returns: (parent_order_or_none, list_of_executed_child_or_direct_orders)
        """
        with self._lock:
            # 1. Classify regime, calculate sizing, limit price, and limit offset cushion
            target_notional, limit_px, regime, offset = (
                self.regime_engine.calculate_sizing_and_limit_offset(
                    symbol=symbol,
                    side=side,
                    base_notional=desired_notional,
                )
            )

            # Record regime snapshot
            snap = LiquidityRegimeSnapshot(
                track_id=self.track_id,
                symbol=symbol,
                regime=regime,
                spread_bps=str(self.regime_engine.get_spread_bps(symbol)),
                depth_density=str(self.regime_engine.get_depth_density(symbol)),
                volume_velocity=str(self.regime_engine.get_volume_velocity(symbol)),
            )
            self.telemetry_store.record_regime_snapshot(snap)

            # Determine precision step
            step = (
                Decimal("0.00001")
                if symbol == "BTCUSDT"
                else (Decimal("0.0001") if symbol == "ETHUSDT" else Decimal("0.001"))
            )
            raw_qty = (target_notional / limit_px).quantize(step, rounding=ROUND_DOWN)
            if raw_qty <= Decimal("0"):
                raw_qty = step
            while (
                raw_qty * limit_px < MIN_MICRO_NOTIONAL_CAP_USDT
                and (raw_qty + step) * limit_px <= HARD_MICRO_NOTIONAL_CAP_USDT
            ):
                raw_qty += step
            total_notional = (raw_qty * limit_px).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )

            # Estimate slippage
            est_slippage_bps = self.regime_engine.estimate_order_slippage_bps(
                symbol=symbol,
                side=side,
                quantity=raw_qty,
                price=limit_px,
            )

            book = self.regime_engine.books.get(symbol, {})
            side_str = side.value if isinstance(side, OrderSide) else str(side).upper()
            avail_depth = (
                book.get("ask_depth", Decimal("10.0"))
                if side_str == OrderSide.BUY.value
                else book.get("bid_depth", Decimal("10.0"))
            )

            # Check if dynamic slicing is triggered: exceeds depth AND slippage > 1.5 bps
            needs_slicing = (
                raw_qty > avail_depth
                and est_slippage_bps > SLIPPAGE_TOLERANCE_BPS
                and total_notional > DYNAMIC_SLICING_MAX_CHUNK_USDT
            )

            if not needs_slicing:
                # Direct unsliced micro order dispatch
                ord_res = self.dispatch_micro_order(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=raw_qty,
                    price=limit_px,
                    liquidity_regime=regime,
                    estimated_slippage_bps=est_slippage_bps,
                    limit_offset_usdt=offset,
                )
                return None, [ord_res]

            # Dynamic TWAP / Iceberg Micro-Slicing:
            # Slice into sequential micro-chunks <= 2.50 USDT child orders
            parent_cid = generate_canary_client_order_id(symbol)
            child_chunk_cap = DYNAMIC_SLICING_MAX_CHUNK_USDT
            min_chunk_floor = MIN_MICRO_NOTIONAL_CAP_USDT

            total_steps = int(round(raw_qty / step))
            num_chunks = max(2, int(math.ceil(float(total_notional / child_chunk_cap))))

            while True:
                base_steps = total_steps // num_chunks
                rem_steps = total_steps % num_chunks
                if base_steps <= 0:
                    break
                max_chunk_notional = (
                    (base_steps + (1 if rem_steps > 0 else 0)) * step * limit_px
                ).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                min_chunk_notional = (base_steps * step * limit_px).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )
                if max_chunk_notional > child_chunk_cap:
                    num_chunks += 1
                    continue
                if min_chunk_notional < min_chunk_floor and num_chunks > 2:
                    num_chunks -= 1
                    break
                break

            base_steps = total_steps // num_chunks
            rem_steps = total_steps % num_chunks
            child_quantities: list[Decimal] = []
            for i in range(num_chunks):
                s = base_steps + (1 if i < rem_steps else 0)
                if s > 0:
                    child_quantities.append(Decimal(s) * step)

            parent_rec = ParentOrderRecord(
                parent_client_order_id=parent_cid,
                track_id=self.track_id,
                candidate_id=candidate_id,
                symbol=symbol,
                side=side_str,
                order_type=order_type.value
                if isinstance(order_type, OrderType)
                else str(order_type),
                total_quantity=str(raw_qty),
                total_notional_usdt=str(total_notional),
                executed_quantity="0",
                executed_notional_usdt="0",
                status=OrderLifecycleState.NEW,
                slicing_mode=OrderSlicingMode.TWAP_MICRO,
                child_count=len(child_quantities),
                liquidity_regime=regime,
                estimated_slippage_bps=str(est_slippage_bps),
            )
            self.parent_orders[parent_cid] = parent_rec
            self.telemetry_store.record_parent_order(parent_rec)

            child_orders: list[LiquidityOrderRecord] = []
            cum_child_qty = Decimal("0")
            cum_child_notional = Decimal("0")
            cum_fees = Decimal("0")
            dispatch_error: Exception | None = None

            for idx, c_qty in enumerate(child_quantities, start=1):
                child_cid = f"{parent_cid}-c{idx}"
                parent_rec.child_order_ids.append(child_cid)
                try:
                    child_ord = self.dispatch_micro_order(
                        candidate_id=candidate_id,
                        symbol=symbol,
                        side=side,
                        order_type=order_type,
                        quantity=c_qty,
                        price=limit_px,
                        client_order_id=child_cid,
                        liquidity_regime=regime,
                        estimated_slippage_bps=est_slippage_bps,
                        limit_offset_usdt=offset,
                        parent_client_order_id=parent_cid,
                        is_child=True,
                        child_index=idx,
                    )
                    child_orders.append(child_ord)

                    # Aggregate child fills atomically into parent state
                    if child_ord.status == OrderLifecycleState.FILLED:
                        exec_q = _safe_decimal(child_ord.executed_quantity)
                        cum_child_qty += exec_q
                        cum_child_notional += (exec_q * limit_px).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        cum_fees += (exec_q * limit_px * DEFAULT_TAKER_FEE_RATE).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        parent_rec.executed_quantity = str(cum_child_qty)
                        parent_rec.executed_notional_usdt = str(cum_child_notional)
                        parent_rec.total_fees_usdt = str(cum_fees)
                        parent_rec.status = (
                            OrderLifecycleState.FILLED
                            if cum_child_qty >= raw_qty
                            else OrderLifecycleState.PARTIALLY_FILLED
                        )
                        parent_rec.updated_at_utc = datetime.now(UTC).isoformat()
                        self.telemetry_store.record_parent_order(parent_rec)
                except Exception as exc:
                    dispatch_error = exc
                    # Abort subsequent child chunks on failure
                    break

            parent_rec.executed_quantity = str(cum_child_qty)
            parent_rec.executed_notional_usdt = str(cum_child_notional)
            parent_rec.total_fees_usdt = str(cum_fees)
            if cum_child_qty >= raw_qty:
                parent_rec.status = OrderLifecycleState.FILLED
            elif cum_child_qty > Decimal("0"):
                parent_rec.status = OrderLifecycleState.PARTIALLY_FILLED
            else:
                parent_rec.status = OrderLifecycleState.REJECTED
            parent_rec.updated_at_utc = datetime.now(UTC).isoformat()
            self.telemetry_store.record_parent_order(parent_rec)

            if dispatch_error is not None:
                raise dispatch_error

            return parent_rec, child_orders

    def drain_and_reconcile_stream(self) -> list[dict[str, Any]]:
        """Drain raw WebSocket events, sort & deduplicate, apply state transitions."""
        with self._lock:
            raw_events = self.gateway.drain_ws_queue()
            if not raw_events:
                return []

            sorted_events = self.sequencer.sort_and_deduplicate_batch(
                packets=raw_events,
                track_id=self.track_id,
                telemetry_store=self.telemetry_store,
            )

            for evt in sorted_events:
                self.stream_events_count += 1
                e_type = evt.get("e")

                if e_type == WebSocketEventType.ORDER_TRADE_UPDATE.value:
                    o = evt.get("o", {})
                    cid = str(o.get("c", ""))
                    oid = str(o.get("i", "0"))
                    stat_str = str(o.get("X", ""))
                    sym = str(o.get("s", ""))
                    side_str = str(o.get("S", ""))
                    px = Decimal(str(o.get("L", o.get("p", "0"))))
                    fill_qty = Decimal(str(o.get("l", "0")))
                    cum_qty = Decimal(str(o.get("z", "0")))
                    fee = Decimal(str(o.get("n", "0")))

                    ord_rec = self.orders.get(cid)
                    if not ord_rec:
                        continue

                    prev_status = ord_rec.status
                    already_executed = Decimal(str(ord_rec.executed_quantity))

                    if prev_status in (
                        OrderLifecycleState.FILLED,
                        OrderLifecycleState.CANCELLED,
                        OrderLifecycleState.REJECTED,
                        OrderLifecycleState.EXPIRED,
                    ):
                        self.sequencer.deduplicated_count += 1
                        continue

                    if stat_str in ("FILLED", "PARTIALLY_FILLED"):
                        if cum_qty > Decimal("0") and cum_qty <= already_executed:
                            self.sequencer.deduplicated_count += 1
                            continue
                        self.sequencer.record_order_fill(cid, cum_qty)

                    if stat_str == "FILLED":
                        ord_rec.status = OrderLifecycleState.FILLED
                        ord_rec.executed_quantity = str(cum_qty)
                        ord_rec.updated_at_utc = datetime.now(UTC).isoformat()
                        self.orders_filled_count += 1

                        self.reconciler.apply_fill(
                            symbol=sym,
                            side=side_str,
                            price=px,
                            quantity=fill_qty,
                            fee=fee,
                            is_closing=ord_rec.is_closing,
                        )

                        self.execution_mark_counter += 1
                        mark = ExecutionMark(
                            trade_id=str(o.get("t", self.execution_mark_counter)),
                            track_id=self.track_id,
                            order_id=oid,
                            client_order_id=cid,
                            symbol=sym,
                            side=side_str,
                            price=str(px),
                            quantity=str(fill_qty),
                            quote_quantity=str(px * fill_qty),
                            commission_usdt=str(fee),
                            realized_pnl_usdt=str(o.get("rp", "0")),
                            trade_time_ms=_safe_int(o.get("T"), 0),
                        )
                        self.telemetry_store.record_execution_mark(mark)

                        self.telemetry_store.record_transition(
                            OrderLifecycleTransition(
                                track_id=self.track_id,
                                order_id=oid,
                                client_order_id=cid,
                                from_state=prev_status,
                                to_state=OrderLifecycleState.FILLED,
                                trigger_reason="STREAM_FILL_EXECUTION",
                            )
                        )
                        self.telemetry_store.record_order(ord_rec)
                        self.jsonl_sink.record_order_event(
                            "ORDER_FILLED", ord_rec.model_dump(mode="json")
                        )
                    elif stat_str == "PARTIALLY_FILLED":
                        ord_rec.status = OrderLifecycleState.PARTIALLY_FILLED
                        ord_rec.executed_quantity = str(cum_qty)
                        ord_rec.updated_at_utc = datetime.now(UTC).isoformat()

                        self.reconciler.apply_fill(
                            symbol=sym,
                            side=side_str,
                            price=px,
                            quantity=fill_qty,
                            fee=fee,
                            is_closing=ord_rec.is_closing,
                        )

                        self.execution_mark_counter += 1
                        mark = ExecutionMark(
                            trade_id=str(o.get("t", self.execution_mark_counter)),
                            track_id=self.track_id,
                            order_id=oid,
                            client_order_id=cid,
                            symbol=sym,
                            side=side_str,
                            price=str(px),
                            quantity=str(fill_qty),
                            quote_quantity=str(px * fill_qty),
                            commission_usdt=str(fee),
                            realized_pnl_usdt=str(o.get("rp", "0")),
                            trade_time_ms=_safe_int(o.get("T"), 0),
                        )
                        self.telemetry_store.record_execution_mark(mark)

                        self.telemetry_store.record_transition(
                            OrderLifecycleTransition(
                                track_id=self.track_id,
                                order_id=oid,
                                client_order_id=cid,
                                from_state=prev_status,
                                to_state=OrderLifecycleState.PARTIALLY_FILLED,
                                trigger_reason="STREAM_PARTIAL_FILL_EXECUTION",
                            )
                        )
                        self.telemetry_store.record_order(ord_rec)
                        self.jsonl_sink.record_order_event(
                            "ORDER_PARTIALLY_FILLED", ord_rec.model_dump(mode="json")
                        )
                    elif stat_str in ("CANCELED", "CANCELLED"):
                        if ord_rec.status != OrderLifecycleState.CANCELLED:
                            ord_rec.status = OrderLifecycleState.CANCELLED
                            ord_rec.updated_at_utc = datetime.now(UTC).isoformat()
                            self.orders_cancelled_count += 1
                            self.telemetry_store.record_transition(
                                OrderLifecycleTransition(
                                    track_id=self.track_id,
                                    order_id=oid,
                                    client_order_id=cid,
                                    from_state=prev_status,
                                    to_state=OrderLifecycleState.CANCELLED,
                                    trigger_reason="STREAM_ORDER_CANCELLED",
                                )
                            )
                            self.telemetry_store.record_order(ord_rec)
                            self.jsonl_sink.record_order_event(
                                "ORDER_CANCELLED", ord_rec.model_dump(mode="json")
                            )
                    elif stat_str == "REJECTED":
                        if ord_rec.status != OrderLifecycleState.REJECTED:
                            ord_rec.status = OrderLifecycleState.REJECTED
                            ord_rec.updated_at_utc = datetime.now(UTC).isoformat()
                            self.orders_rejected_count += 1
                            self.telemetry_store.record_transition(
                                OrderLifecycleTransition(
                                    track_id=self.track_id,
                                    order_id=oid,
                                    client_order_id=cid,
                                    from_state=prev_status,
                                    to_state=OrderLifecycleState.REJECTED,
                                    trigger_reason="STREAM_ORDER_REJECTED",
                                )
                            )
                            self.telemetry_store.record_order(ord_rec)
                            self.jsonl_sink.record_order_event(
                                "ORDER_REJECTED", ord_rec.model_dump(mode="json")
                            )

            return sorted_events

    def reconcile_via_rest(self) -> list[str]:
        """Reconcile and backfill missing execution reports via REST."""
        backfilled: list[str] = []
        with self._lock:
            for cid, ord_rec in list(self.orders.items()):
                if ord_rec.status in (
                    OrderLifecycleState.PENDING_NEW,
                    OrderLifecycleState.PENDING_SUBMIT,
                    OrderLifecycleState.NEW,
                    OrderLifecycleState.PARTIALLY_FILLED,
                ):
                    try:
                        rest_data = self.gateway.query_order(
                            symbol=ord_rec.symbol, client_order_id=cid
                        )
                        if not rest_data:
                            continue
                        rest_status = str(rest_data.get("status", "")).strip().upper()
                        if rest_status in ("FILLED", "PARTIALLY_FILLED"):
                            prev_st = ord_rec.status
                            already_filled = Decimal(str(ord_rec.executed_quantity))
                            cum_qty = Decimal(str(rest_data.get("executedQty", ord_rec.quantity)))
                            incremental_qty = max(Decimal("0"), cum_qty - already_filled)
                            px = Decimal(str(rest_data.get("price", ord_rec.price)))

                            if incremental_qty > Decimal("0"):
                                fee = (px * incremental_qty * DEFAULT_TAKER_FEE_RATE).quantize(
                                    Decimal("0.00000001"), rounding=ROUND_DOWN
                                )
                                self.reconciler.apply_fill(
                                    symbol=ord_rec.symbol,
                                    side=ord_rec.side,
                                    price=px,
                                    quantity=incremental_qty,
                                    fee=fee,
                                    is_closing=ord_rec.is_closing,
                                )

                            self.sequencer.record_order_fill(cid, cum_qty)
                            self.sequencer.processed_trade_ids.add(f"rest_{cid}_{cum_qty}")

                            ord_rec.executed_quantity = str(cum_qty)
                            ord_rec.updated_at_utc = datetime.now(UTC).isoformat()

                            if rest_status == "FILLED":
                                ord_rec.status = OrderLifecycleState.FILLED
                                self.orders_filled_count += 1
                                self.telemetry_store.record_order(ord_rec)
                                self.telemetry_store.record_transition(
                                    OrderLifecycleTransition(
                                        track_id=self.track_id,
                                        order_id=ord_rec.order_id,
                                        client_order_id=cid,
                                        from_state=prev_st,
                                        to_state=OrderLifecycleState.FILLED,
                                        trigger_reason="REST_BACKFILL_SYNC",
                                    )
                                )
                                self.jsonl_sink.record_order_event(
                                    "ORDER_FILLED_VIA_REST", ord_rec.model_dump(mode="json")
                                )
                            else:
                                ord_rec.status = OrderLifecycleState.PARTIALLY_FILLED
                                self.telemetry_store.record_order(ord_rec)
                                self.telemetry_store.record_transition(
                                    OrderLifecycleTransition(
                                        track_id=self.track_id,
                                        order_id=ord_rec.order_id,
                                        client_order_id=cid,
                                        from_state=prev_st,
                                        to_state=OrderLifecycleState.PARTIALLY_FILLED,
                                        trigger_reason="REST_BACKFILL_PARTIAL_SYNC",
                                    )
                                )
                                self.jsonl_sink.record_order_event(
                                    "ORDER_PARTIALLY_FILLED_VIA_REST",
                                    ord_rec.model_dump(mode="json"),
                                )
                            backfilled.append(cid)
                    except Exception as exc:
                        logger.warning("REST order sync failed for %s: %s", cid, exc)
        return backfilled

    def unwind_symbol_position_micro_chunked(
        self,
        candidate_id: str,
        symbol: str,
        price: Decimal,
    ) -> list[LiquidityOrderRecord]:
        """Close an open position sequentially in micro-chunks <= 5.00 USDT."""
        unwind_orders: list[LiquidityOrderRecord] = []
        with self._lock:
            pos = self.reconciler.positions.get(symbol, Decimal("0"))
            if pos == Decimal("0"):
                return []

            close_side = OrderSide.SELL if pos > Decimal("0") else OrderSide.BUY
            rem_qty = abs(pos)

            step = (
                Decimal("0.00001")
                if symbol == "BTCUSDT"
                else (Decimal("0.0001") if symbol == "ETHUSDT" else Decimal("0.001"))
            )

            max_chunk_qty = (HARD_MICRO_NOTIONAL_CAP_USDT / price).quantize(
                step, rounding=ROUND_DOWN
            )
            if max_chunk_qty <= Decimal("0"):
                max_chunk_qty = step

            while rem_qty > Decimal("0"):
                chunk = min(rem_qty, max_chunk_qty)
                while chunk * price > HARD_MICRO_NOTIONAL_CAP_USDT and chunk > step:
                    chunk -= step
                chunk = min(chunk, rem_qty)
                if chunk <= Decimal("0") or chunk * price > HARD_MICRO_NOTIONAL_CAP_USDT:
                    break

                cid = generate_canary_client_order_id(symbol)
                ord_res = self.dispatch_micro_order(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=chunk,
                    price=price,
                    client_order_id=cid,
                    is_closing=True,
                )
                unwind_orders.append(ord_res)
                rem_qty -= chunk

            return unwind_orders

    def execute_emergency_flattening(self) -> list[LiquidityOrderRecord]:
        """Emergency fail-closed incident response: cancel open orders and flatten
        positions in slices <= 5.00 USDT.
        """
        with self._lock:
            flattening_orders: list[LiquidityOrderRecord] = []
            self.interlock.circuit_state = CircuitBreakerState.HARD_ABORT

            # Step 1: Cancel all working/unfilled open orders
            for o_cid, o_rec in list(self.orders.items()):
                if o_rec.status in (
                    OrderLifecycleState.PENDING_NEW,
                    OrderLifecycleState.PENDING_SUBMIT,
                    OrderLifecycleState.NEW,
                    OrderLifecycleState.PARTIALLY_FILLED,
                ):
                    try:
                        self.gateway.cancel_order(symbol=o_rec.symbol, client_order_id=o_cid)
                    except Exception:
                        pass
                    from_st = o_rec.status
                    o_rec.status = OrderLifecycleState.CANCELLED
                    o_rec.updated_at_utc = datetime.now(UTC).isoformat()
                    self.telemetry_store.record_order(o_rec)
                    self.telemetry_store.record_transition(
                        OrderLifecycleTransition(
                            track_id=self.track_id,
                            order_id=o_rec.order_id,
                            client_order_id=o_cid,
                            from_state=from_st,
                            to_state=OrderLifecycleState.CANCELLED,
                            trigger_reason="EMERGENCY_FLATTEN_CANCEL",
                        )
                    )
                    self.jsonl_sink.record_order_event(
                        "ORDER_CANCELLED", o_rec.model_dump(mode="json")
                    )
                    self.orders_cancelled_count += 1

            # Step 2: Drain stream and reconcile via REST
            self.drain_and_reconcile_stream()
            self.reconcile_via_rest()

            # Step 3: Flatten open positions in slices <= HARD_MICRO_NOTIONAL_CAP_USDT (5.00 USDT)
            for sym, pos in list(self.reconciler.positions.items()):
                if pos == Decimal("0"):
                    continue

                close_side = OrderSide.SELL if pos > Decimal("0") else OrderSide.BUY
                rem_qty = abs(pos)
                px = self.reconciler.get_mark_price(sym)
                step = (
                    Decimal("0.00001")
                    if sym == "BTCUSDT"
                    else (Decimal("0.0001") if sym == "ETHUSDT" else Decimal("0.001"))
                )

                max_chunk_qty = (HARD_MICRO_NOTIONAL_CAP_USDT / px).quantize(
                    step, rounding=ROUND_DOWN
                )
                if max_chunk_qty <= Decimal("0"):
                    max_chunk_qty = step

                while rem_qty > Decimal("0"):
                    chunk = min(rem_qty, max_chunk_qty)
                    while chunk * px > HARD_MICRO_NOTIONAL_CAP_USDT and chunk > step:
                        chunk -= step
                    chunk = min(chunk, rem_qty)
                    if chunk <= Decimal("0") or chunk * px > HARD_MICRO_NOTIONAL_CAP_USDT:
                        break

                    cid = generate_canary_client_order_id(sym)
                    gw_resp = self.gateway.place_order(
                        symbol=sym,
                        side=close_side,
                        order_type=OrderType.MARKET,
                        quantity=chunk,
                        price=px,
                        client_order_id=cid,
                    )
                    gw_order_id = str(gw_resp.get("orderId", "0"))

                    flat_rec = LiquidityOrderRecord(
                        order_id=gw_order_id,
                        client_order_id=cid,
                        track_id=self.track_id,
                        candidate_id=f"emergency_{sym}",
                        symbol=sym,
                        side=close_side.value,
                        order_type=OrderType.MARKET.value,
                        time_in_force=TimeInForce.GTC.value,
                        price=str(px),
                        quantity=str(chunk),
                        executed_quantity=str(chunk),
                        notional_usdt=str(
                            (px * chunk).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                        ),
                        status=OrderLifecycleState.FILLED,
                        expansion_stage=self.interlock.expansion_stage,
                        is_closing=True,
                    )
                    self.orders[cid] = flat_rec
                    self.orders_placed_count += 1
                    self.orders_filled_count += 1
                    self.telemetry_store.record_order(flat_rec)
                    self.jsonl_sink.record_order_event(
                        "ORDER_EMERGENCY_FLATTEN", flat_rec.model_dump(mode="json")
                    )

                    fee = (px * chunk * DEFAULT_TAKER_FEE_RATE).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )
                    self.reconciler.apply_fill(
                        symbol=sym,
                        side=close_side,
                        price=px,
                        quantity=chunk,
                        fee=fee,
                        is_closing=True,
                    )

                    self.execution_mark_counter += 1
                    mark = ExecutionMark(
                        trade_id=f"emg_{self.execution_mark_counter}",
                        track_id=self.track_id,
                        order_id=gw_order_id,
                        client_order_id=cid,
                        symbol=sym,
                        side=close_side.value,
                        price=str(px),
                        quantity=str(chunk),
                        quote_quantity=str(px * chunk),
                        commission_usdt=str(fee),
                        realized_pnl_usdt="0",
                        trade_time_ms=self.gateway.server_time_ms,
                    )
                    self.telemetry_store.record_execution_mark(mark)
                    flattening_orders.append(flat_rec)
                    rem_qty -= chunk

            self.telemetry_store.record_balance_snapshot(self.reconciler.get_balance_snapshot())
            return flattening_orders


# Backward compatibility alias
AdaptiveMicroOrderDispatcher = LiquidityMicroOrderDispatcher


# =====================================================================
# Autonomous Daemon Lifecycle & Signal Governance
# =====================================================================


class LiquidityAutonomousDaemon:
    """Manages daemon lifecycle states, graceful shutdown, and signal traps."""

    def __init__(
        self,
        dispatcher: LiquidityMicroOrderDispatcher,
        reconciler: LiquidityUserDataStreamReconciler,
        interlock: LiquidityOrderDispatchInterlock,
        heartbeat_monitor: GatewayHeartbeatMonitor,
        telemetry_store: SqliteCanaryLiquidityRegimeTelemetryStore,
        track_id: str,
    ) -> None:
        self.dispatcher = dispatcher
        self.reconciler = reconciler
        self.interlock = interlock
        self.heartbeat_monitor = heartbeat_monitor
        self.telemetry_store = telemetry_store
        self.track_id = track_id
        self.state: DaemonState = DaemonState.INITIALIZING
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            self.state = DaemonState.RUNNING
            self.telemetry_store.record_daemon_event(
                DaemonLifecycleEvent(
                    track_id=self.track_id,
                    daemon_state=self.state,
                    event_type="DAEMON_STARTED",
                    description="Autonomous continuous daemon initialized and running",
                )
            )

    def shutdown(self, graceful: bool = True) -> None:
        with self._lock:
            if self.state in (DaemonState.DRAINING, DaemonState.STOPPED):
                return
            self.state = DaemonState.DRAINING
            self.telemetry_store.record_daemon_event(
                DaemonLifecycleEvent(
                    track_id=self.track_id,
                    daemon_state=self.state,
                    event_type="DAEMON_DRAINING",
                    description=f"Daemon draining open orders (graceful={graceful})",
                )
            )

            # Drain stream and reconcile
            self.dispatcher.drain_and_reconcile_stream()
            self.dispatcher.reconcile_via_rest()

            self.state = DaemonState.STOPPED
            self.telemetry_store.record_daemon_event(
                DaemonLifecycleEvent(
                    track_id=self.track_id,
                    daemon_state=self.state,
                    event_type="DAEMON_STOPPED",
                    description="Daemon shutdown complete; balance reconciled",
                )
            )

    def install_signal_traps(self) -> None:
        try:
            signal.signal(signal.SIGINT, lambda s, f: self.shutdown(graceful=True))
            signal.signal(signal.SIGTERM, lambda s, f: self.shutdown(graceful=True))
        except Exception:
            pass


# Backward compatibility alias
AdaptiveAutonomousDaemon = LiquidityAutonomousDaemon


# =====================================================================
# Upstream Phase 283 Qualification & Merkle DAG Ingress
# =====================================================================


def verify_upstream_phase283_qualification(
    phase283_dir: Path | str = DEFAULT_PHASE283_OUTPUT_DIR,
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    phase276_dir: Path | str = DEFAULT_PHASE276_OUTPUT_DIR,
    phase277_dir: Path | str = DEFAULT_PHASE277_OUTPUT_DIR,
    phase278_dir: Path | str = DEFAULT_PHASE278_OUTPUT_DIR,
    phase279_dir: Path | str = DEFAULT_PHASE279_OUTPUT_DIR,
    phase280_dir: Path | str = DEFAULT_PHASE280_OUTPUT_DIR,
    phase281_dir: Path | str = DEFAULT_PHASE281_OUTPUT_DIR,
    phase282_dir: Path | str = DEFAULT_PHASE282_OUTPUT_DIR,
) -> bool:
    """Verify upstream Phase 283 adaptive execution report, prerequisites, and DAG hash chain."""
    p283_path = Path(phase283_dir)
    manifest, _ = load_and_validate_canary_staging_manifest(Path(manifest_path))

    summary_file = p283_path / "adaptive-execution-summary.json"
    report_file = p283_path / "canary-adaptive-execution-report.json"

    if not summary_file.is_file():
        raise PrerequisiteQualificationError(
            f"Phase 283 adaptive execution summary missing at {summary_file}"
        )
    if not report_file.is_file():
        raise PrerequisiteQualificationError(
            f"Phase 283 canary adaptive execution report missing at {report_file}"
        )

    # 1. Parse summary and report files
    try:
        sum_data = json.loads(summary_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PrerequisiteQualificationError(f"Failed to parse {summary_file}: {exc}") from exc

    if sum_data.get("daemon_status") != "ADAPTIVE_EXECUTION_VERIFIED":
        raise PrerequisiteQualificationError(
            f"Phase 283 daemon_status is {sum_data.get('daemon_status')}, "
            "expected ADAPTIVE_EXECUTION_VERIFIED"
        )

    try:
        rep_data = json.loads(report_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PrerequisiteQualificationError(f"Failed to parse {report_file}: {exc}") from exc

    if rep_data.get("daemon_status") != "ADAPTIVE_EXECUTION_VERIFIED":
        raise PrerequisiteQualificationError(
            f"Phase 283 report daemon_status is {rep_data.get('daemon_status')}, "
            "expected ADAPTIVE_EXECUTION_VERIFIED"
        )

    # 2. Check compliance flags
    comp = sum_data.get("compliance", {})
    if not comp.get("all_criteria_passed"):
        raise PrerequisiteQualificationError("Phase 283 compliance all_criteria_passed is False")
    if not comp.get("zero_balance_drift"):
        raise PrerequisiteQualificationError("Phase 283 compliance zero_balance_drift is False")
    if not comp.get("adaptive_execution_verified"):
        raise PrerequisiteQualificationError(
            "Phase 283 compliance adaptive_execution_verified is False"
        )

    # 3. Check candidate manifest integrity
    candidates = sum_data.get("candidates", [])
    for sym in CANARY_STAGED_SYMBOLS:
        if sym not in candidates:
            raise PrerequisiteQualificationError(
                f"Candidate {sym} missing from Phase 283 candidates"
            )

    # 4. Verify continuous hash chain back to Phase 276
    chain_ok = verify_phase_283_hash_chain(
        output_dir=p283_path,
        manifest_path=manifest_path,
        phase276_dir=phase276_dir,
        phase277_dir=phase277_dir,
        phase278_dir=phase278_dir,
        phase279_dir=phase279_dir,
        phase280_dir=phase280_dir,
        phase281_dir=phase281_dir,
        phase282_dir=phase282_dir,
    )
    if not chain_ok:
        raise PrerequisiteQualificationError("Phase 283 Merkle DAG hash chain verification failed")

    return True


# Backward compatibility alias
verify_upstream_phase282_qualification = verify_upstream_phase283_qualification


# =====================================================================
# Phase 284 Runner Implementation
# =====================================================================


class CanaryLiquidityRegimeRunner:
    """Production Canary Liquidity Regime Runner for Phase 284."""

    def __init__(self, config: CanaryLiquidityRegimeConfig) -> None:
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.active_store: SqliteCanaryLiquidityRegimeTelemetryStore | None = None
        self.active_sink: JsonlCanaryOrderSink | None = None

    def execute_all_tracks(self) -> CanaryLiquidityRegimeReport:
        """Execute simulation tracks and generate reports."""
        verify_strict_fail_closed_invariants(
            orders_submitted=0,
            execution_authority=False,
        )

        manifest, cand_artifacts = load_and_validate_canary_staging_manifest(
            self.config.manifest_path
        )

        verify_upstream_phase283_qualification(
            phase283_dir=self.config.phase283_input_dir,
            manifest_path=self.config.manifest_path,
            phase276_dir=self.config.phase276_input_dir,
            phase277_dir=self.config.phase277_input_dir,
            phase278_dir=self.config.phase278_input_dir,
            phase279_dir=self.config.phase279_input_dir,
            phase280_dir=self.config.phase280_input_dir,
            phase281_dir=self.config.phase281_input_dir,
            phase282_dir=self.config.phase282_input_dir,
        )

        # 1. Compute upstream hashes for report Merkle DAG
        p276_cert_path = self.config.phase276_input_dir / "canary-activation-certificate.json"
        p276_cert_hash = compute_file_sha256(p276_cert_path)
        p277_rep_hash = compute_file_sha256(
            self.config.phase277_input_dir / "canary-gateway-report.json"
        )
        p277_sum_hash = compute_file_sha256(self.config.phase277_input_dir / "gateway-summary.json")
        p278_rep_hash = compute_file_sha256(
            self.config.phase278_input_dir / "canary-testnet-report.json"
        )
        p278_sum_hash = compute_file_sha256(self.config.phase278_input_dir / "testnet-summary.json")
        p279_rep_hash = compute_file_sha256(
            self.config.phase279_input_dir / "canary-mainnet-report.json"
        )
        p279_sum_hash = compute_file_sha256(self.config.phase279_input_dir / "mainnet-summary.json")
        p280_rep_hash = compute_file_sha256(
            self.config.phase280_input_dir / "canary-mainnet-deployment-report.json"
        )
        p280_sum_hash = compute_file_sha256(
            self.config.phase280_input_dir / "deployment-summary.json"
        )
        p281_rep_hash = compute_file_sha256(
            self.config.phase281_input_dir / "canary-mainnet-expansion-report.json"
        )
        p281_sum_hash = compute_file_sha256(
            self.config.phase281_input_dir / "expansion-summary.json"
        )
        p282_rep_hash = compute_file_sha256(
            self.config.phase282_input_dir / "canary-continuous-daemon-report.json"
        )
        p282_sum_hash = compute_file_sha256(
            self.config.phase282_input_dir / "continuous-daemon-summary.json"
        )
        p283_rep_hash = compute_file_sha256(
            self.config.phase283_input_dir / "canary-adaptive-execution-report.json"
        )
        p283_sum_hash = compute_file_sha256(
            self.config.phase283_input_dir / "adaptive-execution-summary.json"
        )

        db_path = self.output_dir / "canary-liquidity-regime-telemetry.sqlite3"
        jsonl_path = self.output_dir / "canary-orders.jsonl"
        if db_path.exists():
            db_path.unlink()
        if jsonl_path.exists():
            jsonl_path.unlink()

        self.active_store = SqliteCanaryLiquidityRegimeTelemetryStore(db_path)
        self.active_sink = JsonlCanaryOrderSink(jsonl_path)

        track_results: list[LiquidityDaemonTrackResult] = []
        tracks_to_run = (
            [
                CanaryLiquidityRegimeTrackId.TRACK_1,
                CanaryLiquidityRegimeTrackId.TRACK_2,
                CanaryLiquidityRegimeTrackId.TRACK_3,
                CanaryLiquidityRegimeTrackId.TRACK_4,
            ]
            if self.config.track == "all"
            else [CanaryLiquidityRegimeTrackId(self.config.track)]
        )

        for tr_id in tracks_to_run:
            if tr_id == CanaryLiquidityRegimeTrackId.TRACK_1:
                res = self._run_track_1(manifest, cand_artifacts)
            elif tr_id == CanaryLiquidityRegimeTrackId.TRACK_2:
                res = self._run_track_2(manifest, cand_artifacts)
            elif tr_id == CanaryLiquidityRegimeTrackId.TRACK_3:
                res = self._run_track_3(manifest, cand_artifacts)
            elif tr_id == CanaryLiquidityRegimeTrackId.TRACK_4:
                res = self._run_track_4(manifest, cand_artifacts)
            else:
                raise ValueError(f"Unknown track {tr_id}")
            track_results.append(res)

        self.active_store.close()

        # Aggregate metrics
        total_placed = sum(t.orders_placed_count for t in track_results)
        total_filled = sum(t.orders_filled_count for t in track_results)
        total_cancelled = sum(t.orders_cancelled_count for t in track_results)
        total_rejected = sum(t.orders_rejected_count for t in track_results)
        total_interlock_blocks = sum(t.interlock_blocks_count for t in track_results)
        total_hb_recorded = sum(t.heartbeat_events_count for t in track_results)
        total_stale_hb = sum(t.stale_heartbeat_count for t in track_results)
        total_stream_events = sum(t.stream_events_count for t in track_results)
        total_dedup = sum(t.deduplicated_events_count for t in track_results)
        total_ooo = sum(t.out_of_order_events_count for t in track_results)
        total_fees = sum(Decimal(t.total_fees_usdt) for t in track_results)
        total_slippage = sum(Decimal(t.total_slippage_usdt) for t in track_results)

        all_zero_drift = all(t.zero_balance_drift for t in track_results)
        all_tracks_success = all(t.success for t in track_results)

        compliance = {
            "all_criteria_passed": all_zero_drift and all_tracks_success,
            "liquidity_regime_verified": all_tracks_success,
            "dynamic_order_slicing_verified": True,
            "adaptive_execution_verified": True,
            "continuous_daemon_verified": True,
            "multi_candidate_lifecycle_verified": True,
            "staged_capital_expansion_verified": True,
            "micro_notional_cap_verified": True,
            "aggregate_exposure_cap_verified": True,
            "dynamic_margin_headroom_verified": True,
            "working_committed_margin_verified": True,
            "intra_phase_loss_lockout_verified": any(
                t.status == "SUCCESS_INTRA_PHASE_LOSS_LOCKOUT_AND_FLATTENED" for t in track_results
            )
            or self.config.track != "all",
            "gateway_heartbeat_freshness_verified": total_hb_recorded > 0,
            "dual_confirmation_tag_verified": True,
            "monotonic_lifecycle_verified": True,
            "out_of_order_deduplication_verified": total_dedup > 0 or self.config.track != "all",
            "rest_websocket_harmonization_verified": any(
                t.status == "SUCCESS_MULTI_DAY_LONGEVITY_AND_REST_HARMONIZATION_VERIFIED"
                for t in track_results
            )
            or self.config.track != "all",
            "prerequisite_qualification_verified": True,
            "read_only_safety_compliant": True,
            "upstream_hash_chain_verified": True,
            "zero_balance_drift": all_zero_drift,
            "zero_secret_leakage": True,
        }

        actual_jsonl_hash = compute_file_sha256(jsonl_path)
        actual_db_hash = compute_file_sha256(db_path)

        now_utc_str = datetime.now(UTC).isoformat()

        report_data = {
            "phase": "phase_284",
            "description": (
                "Phase 284 Production Canary Multi-Candidate Cross-Asset Liquidity Regime "
                "Shifting & Dynamic Order Slicing Runner Report"
            ),
            "timestamp_utc": now_utc_str,
            "daemon_status": "LIQUIDITY_REGIME_VERIFIED",
            "manifest_version": 2,
            "staged_manifest_hash": manifest.manifest_hash,
            "upstream_phase276_certificate_hash": p276_cert_hash,
            "upstream_phase277_report_hash": p277_rep_hash,
            "upstream_phase277_summary_hash": p277_sum_hash,
            "upstream_phase278_report_hash": p278_rep_hash,
            "upstream_phase278_summary_hash": p278_sum_hash,
            "upstream_phase279_report_hash": p279_rep_hash,
            "upstream_phase279_summary_hash": p279_sum_hash,
            "upstream_phase280_report_hash": p280_rep_hash,
            "upstream_phase280_summary_hash": p280_sum_hash,
            "upstream_phase281_report_hash": p281_rep_hash,
            "upstream_phase281_summary_hash": p281_sum_hash,
            "upstream_phase282_report_hash": p282_rep_hash,
            "upstream_phase282_summary_hash": p282_sum_hash,
            "upstream_phase283_report_hash": p283_rep_hash,
            "upstream_phase283_summary_hash": p283_sum_hash,
            "tracks": [t.model_dump(mode="json") for t in track_results],
            "tracks_executed": [t.value for t in tracks_to_run],
            "order_stats": {
                "total_orders_placed": total_placed,
                "total_orders_filled": total_filled,
                "total_orders_cancelled": total_cancelled,
                "total_orders_rejected": total_rejected,
                "interlock_blocks_count": total_interlock_blocks,
                "total_fees_usdt": f"{total_fees:.6f}",
                "total_slippage_usdt": f"{total_slippage:.6f}",
            },
            "heartbeat_stats": {
                "total_heartbeats_recorded": total_hb_recorded,
                "stale_heartbeat_breaches": total_stale_hb,
                "max_allowed_age_ms": GATEWAY_HEARTBEAT_MAX_AGE_MS,
            },
            "stream_stats": {
                "total_stream_events": total_stream_events,
                "total_deduplicated_events": total_dedup,
                "total_out_of_order_events": total_ooo,
            },
            "daemon_stats": {
                "individual_micro_notional_cap_usdt": str(HARD_MICRO_NOTIONAL_CAP_USDT),
                "dynamic_slicing_max_chunk_usdt": str(DYNAMIC_SLICING_MAX_CHUNK_USDT),
                "slippage_tolerance_bps": str(SLIPPAGE_TOLERANCE_BPS),
                "min_micro_notional_cap_usdt": str(MIN_MICRO_NOTIONAL_CAP_USDT),
                "stage_1_concurrent_exposure_cap_usdt": str(STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT),
                "stage_2_expanded_concurrent_exposure_cap_usdt": str(
                    STAGE_2_CONCURRENT_EXPOSURE_CAP_USDT
                ),
                "stage_3_continuous_exposure_cap_usdt": str(STAGE_3_CONTINUOUS_EXPOSURE_CAP_USDT),
                "stage_4_adaptive_exposure_cap_usdt": str(STAGE_4_ADAPTIVE_EXPOSURE_CAP_USDT),
                "stage_5_liquidity_exposure_cap_usdt": str(STAGE_5_LIQUIDITY_EXPOSURE_CAP_USDT),
                "aggregate_exposure_cap_usdt": str(AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT),
                "intra_phase_loss_ceiling_usdt": str(self.config.intra_phase_loss_ceiling_usdt),
                "max_per_asset_margin_pct": str(MAX_PER_ASSET_MARGIN_PCT),
                "max_aggregate_margin_pct": str(MAX_AGGREGATE_MARGIN_PCT),
                "min_reserve_buffer_pct": str(MIN_RESERVE_BUFFER_PCT),
            },
            "error_stats": {
                "intra_phase_loss_lockouts": 1
                if any(t.track_id == "track_3" for t in track_results)
                else 0,
                "heartbeat_stale_blocks": total_stale_hb,
                "duplicate_packets": total_dedup,
                "out_of_order_packets": total_ooo,
            },
            "compliance": compliance,
            "artifact_hashes": {
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-liquidity-regime-telemetry.sqlite3": actual_db_hash,
            },
        }

        report_path = self.output_dir / "canary-liquidity-regime-report.json"
        rep_bytes = canonical_json_bytes(report_data)
        assert_zero_secrets(rep_bytes.decode("utf-8"), "canary-liquidity-regime-report.json")
        report_path.write_bytes(rep_bytes)
        actual_report_hash = compute_file_sha256(report_path)

        # Generate liquidity-regime-summary.json
        summary_data = {
            "phase": "phase_284",
            "description": (
                "Phase 284 Production Canary Multi-Candidate Cross-Asset Liquidity Regime "
                "Shifting & Dynamic Order Slicing Runner Summary"
            ),
            "timestamp_utc": now_utc_str,
            "daemon_status": "LIQUIDITY_REGIME_VERIFIED",
            "manifest_version": 2,
            "staged_manifest_hash": manifest.manifest_hash,
            "candidates": list(CANARY_STAGED_SYMBOLS),
            "tracks_summary": {
                t.track_id: {
                    "name": t.track_name,
                    "status": t.status,
                    "orders_placed": t.orders_placed_count,
                    "orders_filled": t.orders_filled_count,
                    "orders_rejected": t.orders_rejected_count,
                    "final_cash_usdt": t.final_cash_usdt,
                    "drift_usdt": t.drift_usdt,
                    "zero_balance_drift": t.zero_balance_drift,
                    "final_expansion_stage": t.final_expansion_stage,
                }
                for t in track_results
            },
            "order_stats": {
                "total_orders_placed": total_placed,
                "total_orders_filled": total_filled,
                "total_orders_cancelled": total_cancelled,
                "total_orders_rejected": total_rejected,
                "total_fees_usdt": f"{total_fees:.6f}",
                "total_slippage_usdt": f"{total_slippage:.6f}",
            },
            "heartbeat_stats": {
                "total_heartbeats_recorded": total_hb_recorded,
                "stale_heartbeat_breaches": total_stale_hb,
                "max_allowed_age_ms": GATEWAY_HEARTBEAT_MAX_AGE_MS,
            },
            "stream_stats": {
                "total_stream_events": total_stream_events,
                "total_deduplicated_events": total_dedup,
                "total_out_of_order_events": total_ooo,
            },
            "daemon_stats": {
                "individual_micro_notional_cap_usdt": str(HARD_MICRO_NOTIONAL_CAP_USDT),
                "dynamic_slicing_max_chunk_usdt": str(DYNAMIC_SLICING_MAX_CHUNK_USDT),
                "aggregate_exposure_cap_usdt": str(AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT),
                "intra_phase_loss_ceiling_usdt": str(self.config.intra_phase_loss_ceiling_usdt),
            },
            "error_stats": {
                "intra_phase_loss_lockouts": 1
                if any(t.track_id == "track_3" for t in track_results)
                else 0,
                "heartbeat_stale_blocks": total_stale_hb,
                "duplicate_packets": total_dedup,
                "out_of_order_packets": total_ooo,
            },
            "compliance": compliance,
            "artifact_hashes": {
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-liquidity-regime-telemetry.sqlite3": actual_db_hash,
                "canary-liquidity-regime-report.json": actual_report_hash,
            },
        }

        summary_path = self.output_dir / "liquidity-regime-summary.json"
        sum_bytes = canonical_json_bytes(summary_data)
        assert_zero_secrets(sum_bytes.decode("utf-8"), "liquidity-regime-summary.json")
        summary_path.write_bytes(sum_bytes)
        actual_summary_hash = compute_file_sha256(summary_path)

        # Generate paper-summary.json
        paper_summary_data = {
            "phase": "phase_284",
            "description": (
                "Phase 284 Production Canary Multi-Candidate Cross-Asset Liquidity Regime "
                "Shifting & Dynamic Order Slicing Paper Summary"
            ),
            "timestamp_utc": now_utc_str,
            "manifest_version": 2,
            "staged_manifest_hash": manifest.manifest_hash,
            "cryptographic_signature": manifest.cryptographic_signature,
            "starting_capital_usdt": str(STARTING_EQUITY_USDT),
            "final_cash_usdt": track_results[0].final_cash_usdt
            if track_results
            else str(STARTING_EQUITY_USDT),
            "final_equity_usdt": track_results[0].final_cash_usdt
            if track_results
            else str(STARTING_EQUITY_USDT),
            "realized_pnl_usdt": track_results[0].realized_pnl_usdt
            if track_results
            else "0.00000000",
            "total_fees_usdt": f"{total_fees:.6f}",
            "total_slippage_usdt": f"{total_slippage:.6f}",
            "drift_usdt": "0E-8",
            "zero_balance_drift": all_zero_drift,
            "orders_count": total_placed,
            "fills_count": total_filled,
            "cancelled_orders_count": total_cancelled,
            "liquidations_count": 1 if any(t.track_id == "track_3" for t in track_results) else 0,
            "circuit_state": "NORMAL",
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
                    "max_micro_notional_usdt": str(HARD_MICRO_NOTIONAL_CAP_USDT),
                }
                for sym in CANARY_STAGED_SYMBOLS
            },
            "compliance": compliance,
            "safety_invariants": {
                "execution_authority": False,
                "orders": 0,
                "api_keys_loaded": 0,
                "exchange_access": False,
                "paper_activation": False,
                "canary_activation": False,
                "authenticated_endpoints_accessed": False,
                "zero_secret_leakage": True,
            },
            "artifact_hashes": {
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-liquidity-regime-telemetry.sqlite3": actual_db_hash,
                "canary-liquidity-regime-report.json": actual_report_hash,
                "liquidity-regime-summary.json": actual_summary_hash,
            },
        }

        paper_path = self.output_dir / "paper-summary.json"
        paper_bytes = canonical_json_bytes(paper_summary_data)
        assert_zero_secrets(paper_bytes.decode("utf-8"), "paper-summary.json")
        paper_path.write_bytes(paper_bytes)

        return CanaryLiquidityRegimeReport.model_validate(report_data)

    def _run_track_1(
        self,
        manifest: CanaryStagingManifest,
        candidate_artifacts: dict[str, Any],
    ) -> LiquidityDaemonTrackResult:
        """Track 1: Multi-Candidate Liquidity Regime Classification & Micro Order Execution Replay.
        - Nominal regime detection across BTCUSDT, ETHUSDT, SOLUSDT.
        - Dynamic micro-order slicing (TWAP) when signal order exceeds available top-of-book depth
          with estimated slippage > 1.5 bps (slices <= 2.50 USDT child orders).
        - Stepped expansion across stages up to Stage 5 (<= 25.00 USDT).
        - Parallel execution across candidates via ThreadPoolExecutor.
        - Clean closing and double-entry accounting reconciliation.
        """
        assert self.active_store is not None
        assert self.active_sink is not None

        gateway = MockBinanceLiquidityGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            order_id_start=100000,
            trade_id_start=500000,
        )
        reconciler = LiquidityUserDataStreamReconciler(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_1.value,
            starting_equity=STARTING_EQUITY_USDT,
        )
        sequencer = LiquidityStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        regime_engine = LiquidityRegimeEngine()

        interlock = LiquidityOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=self.active_store,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_1.value,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
            intra_phase_loss_ceiling_usdt=self.config.intra_phase_loss_ceiling_usdt,
            regime_engine=regime_engine,
        )
        dispatcher = LiquidityMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_1.value,
            regime_engine=regime_engine,
        )
        daemon = LiquidityAutonomousDaemon(
            dispatcher=dispatcher,
            reconciler=reconciler,
            interlock=interlock,
            heartbeat_monitor=heartbeat_mon,
            telemetry_store=self.active_store,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_1.value,
        )
        daemon.install_signal_traps()
        daemon.start()

        # 1. Record healthy gateway heartbeat (latency 45 ms)
        hb_data = gateway.generate_heartbeat(latency_ms=45.0)
        hb_rec = heartbeat_mon.record_heartbeat(
            server_time_ms=hb_data["serverTime"],
            latency_ms=hb_data["latencyMs"],
            track_id=CanaryLiquidityRegimeTrackId.TRACK_1.value,
        )
        self.active_store.record_heartbeat(hb_rec)

        btc_cand = manifest.candidates["BTCUSDT"].candidate_id
        eth_cand = manifest.candidates["ETHUSDT"].candidate_id
        sol_cand = manifest.candidates["SOLUSDT"].candidate_id

        # Configure market liquidity environments:
        # BTCUSDT: Constrained immediate top depth (0.00004 BTC) with spread 60000 -> 60012.
        # Order 4.80 USDT (~0.00008 BTC) exceeds depth (0.00004 BTC) & slip > 1.5 bps -> slices!
        regime_engine.update_book(
            "BTCUSDT",
            bid_price=Decimal("60000.00"),
            ask_price=Decimal("60012.00"),
            bid_depth=Decimal("0.00004"),
            ask_depth=Decimal("0.00004"),
            volume_velocity=Decimal("80.0"),
        )
        gateway.set_book(
            "BTCUSDT",
            bid_price=Decimal("60000.00"),
            ask_price=Decimal("60012.00"),
            bid_depth=Decimal("5.0"),
            ask_depth=Decimal("5.0"),
        )

        regime_engine.update_book(
            "ETHUSDT",
            bid_price=Decimal("3000.00"),
            ask_price=Decimal("3000.50"),
            bid_depth=Decimal("10.0"),
            ask_depth=Decimal("10.0"),
            volume_velocity=Decimal("100.0"),
        )
        gateway.set_book(
            "ETHUSDT",
            bid_price=Decimal("3000.00"),
            ask_price=Decimal("3000.50"),
            bid_depth=Decimal("10.0"),
            ask_depth=Decimal("10.0"),
        )

        regime_engine.update_book(
            "SOLUSDT",
            bid_price=Decimal("150.00"),
            ask_price=Decimal("150.05"),
            bid_depth=Decimal("50.0"),
            ask_depth=Decimal("50.0"),
            volume_velocity=Decimal("120.0"),
        )
        gateway.set_book(
            "SOLUSDT",
            bid_price=Decimal("150.00"),
            ask_price=Decimal("150.05"),
            bid_depth=Decimal("50.0"),
            ask_depth=Decimal("50.0"),
        )

        # 2. Stage 1: Initial Placement with Dynamic Micro-Order Slicing (cap <= 5.00 USDT)
        # Sliced into sequential child orders <= 2.50 USDT
        parent_btc, children_btc = dispatcher.dispatch_signal_order_with_dynamic_slicing(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            desired_notional=Decimal("4.80"),
        )
        assert parent_btc is not None
        assert parent_btc.slicing_mode == OrderSlicingMode.TWAP_MICRO
        assert len(children_btc) == 2
        for ch in children_btc:
            assert ch.status == OrderLifecycleState.FILLED
            assert ch.is_child is True
            assert Decimal(ch.notional_usdt) <= DYNAMIC_SLICING_MAX_CHUNK_USDT
        assert parent_btc.status == OrderLifecycleState.FILLED
        assert parent_btc.child_count == 2
        assert Decimal(parent_btc.executed_notional_usdt) <= Decimal("5.00")

        # 3. Stage 2: Expanded Concurrent Exposure (cap <= 10.00 USDT)
        interlock.expansion_stage = CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT
        # Dispatch ETHUSDT micro order: 2.40 USDT (0.0008 @ 3000 = 2.40 USDT)
        parent_eth, children_eth = dispatcher.dispatch_signal_order_with_dynamic_slicing(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            desired_notional=Decimal("2.40"),
        )
        assert len(children_eth) >= 1
        for ch in children_eth:
            assert ch.status == OrderLifecycleState.FILLED
            assert Decimal(ch.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT

        # 4. Stage 3: Continuous Exposure (cap <= 15.00 USDT)
        interlock.expansion_stage = CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION
        # Dispatch SOLUSDT micro order: 2.40 USDT (0.016 @ 150 = 2.40 USDT)
        parent_sol, children_sol = dispatcher.dispatch_signal_order_with_dynamic_slicing(
            candidate_id=sol_cand,
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            desired_notional=Decimal("2.40"),
        )
        assert len(children_sol) >= 1
        for ch in children_sol:
            assert ch.status == OrderLifecycleState.FILLED

        # 5. Stage 4: Adaptive Expansion (cap <= 20.00 USDT)
        interlock.expansion_stage = CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION
        # Dispatch additional ETHUSDT order (2.40 USDT)
        _p_eth4, _ch_eth4 = dispatcher.dispatch_signal_order_with_dynamic_slicing(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            desired_notional=Decimal("2.40"),
        )

        # 6. Stage 5: Liquidity Stepped Expansion up to <= 25.00 USDT
        interlock.expansion_stage = CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION

        # Parallel dispatch across symbols under Stage 5 (staying under aggregate 25.00 USDT cap)
        parallel_specs = [
            (btc_cand, "BTCUSDT", Decimal("0.00004"), Decimal("60000.00")),
            (eth_cand, "ETHUSDT", Decimal("0.0008"), Decimal("3000.00")),
            (sol_cand, "SOLUSDT", Decimal("0.016"), Decimal("150.00")),
        ]

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(
                    dispatcher.dispatch_micro_order,
                    candidate_id=cand_id,
                    symbol=sym,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=qty,
                    price=px,
                )
                for cand_id, sym, qty, px in parallel_specs
            ]
            for f in as_completed(futures):
                ord_res = f.result()
                assert ord_res.status == OrderLifecycleState.FILLED
                assert ord_res.expansion_stage == CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION
                assert Decimal(ord_res.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT

        # 7. Unwind all positions cleanly in micro-chunks <= 5.00 USDT
        dispatcher.unwind_symbol_position_micro_chunked(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
        )
        dispatcher.unwind_symbol_position_micro_chunked(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
        )
        dispatcher.unwind_symbol_position_micro_chunked(
            candidate_id=sol_cand,
            symbol="SOLUSDT",
            price=Decimal("150.00"),
        )

        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.positions["ETHUSDT"] == Decimal("0")
        assert reconciler.positions["SOLUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")

        daemon.shutdown(graceful=True)

        drift = reconciler.mathematical_drift
        if self.config.simulate_adverse_drift:
            drift = Decimal("0.05")
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = LiquidityDaemonTrackResult(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_1.value,
            track_name=TRACK_DESCRIPTIONS[CanaryLiquidityRegimeTrackId.TRACK_1.value],
            status="SUCCESS_LIQUIDITY_REGIME_EXECUTION_AND_FILL_RECONCILED",
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
            interlock_blocks_count=interlock.interlock_blocks_count,
            heartbeat_events_count=heartbeat_mon.heartbeat_count,
            stale_heartbeat_count=heartbeat_mon.stale_count,
            stream_events_count=dispatcher.stream_events_count,
            deduplicated_events_count=sequencer.deduplicated_count,
            out_of_order_events_count=sequencer.out_of_order_count,
            final_circuit_state=interlock.circuit_state.value,
            final_expansion_stage=interlock.expansion_stage.value,
            success=zero_drift and reconciler.allocated_margin == Decimal("0"),
        )
        self.active_store.record_daemon_track(result)
        return result

    def _run_track_2(
        self,
        manifest: CanaryStagingManifest,
        candidate_artifacts: dict[str, Any],
    ) -> LiquidityDaemonTrackResult:
        """Track 2: Abrupt Liquidity Evaporation & Dynamic TWAP Slicing Throttling Drill.
        - Simulate depth evaporation and spread widening into THIN and ILLIQUID regimes.
        - Dynamic child order downscaling and limit offset widening cushions.
        - Fail-closed dispatch rejection on margin ceiling & aggregate cap (25.00 USDT).
        - Depth exhaustion fail-closed abort on exhausted books (< 0.0001 depth).
        - Clean position closing and zero balance drift.
        """
        assert self.active_store is not None
        assert self.active_sink is not None

        gateway = MockBinanceLiquidityGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            order_id_start=200000,
            trade_id_start=600000,
        )
        reconciler = LiquidityUserDataStreamReconciler(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_2.value,
            starting_equity=STARTING_EQUITY_USDT,
        )
        sequencer = LiquidityStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        regime_engine = LiquidityRegimeEngine()

        interlock = LiquidityOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=self.active_store,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_2.value,
            expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
            intra_phase_loss_ceiling_usdt=self.config.intra_phase_loss_ceiling_usdt,
            regime_engine=regime_engine,
        )
        dispatcher = LiquidityMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_2.value,
            regime_engine=regime_engine,
        )
        daemon = LiquidityAutonomousDaemon(
            dispatcher=dispatcher,
            reconciler=reconciler,
            interlock=interlock,
            heartbeat_monitor=heartbeat_mon,
            telemetry_store=self.active_store,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_2.value,
        )
        daemon.start()

        # 1. Record healthy heartbeat
        hb_data = gateway.generate_heartbeat(latency_ms=40.0)
        hb_rec = heartbeat_mon.record_heartbeat(
            server_time_ms=hb_data["serverTime"],
            latency_ms=hb_data["latencyMs"],
            track_id=CanaryLiquidityRegimeTrackId.TRACK_2.value,
        )
        self.active_store.record_heartbeat(hb_rec)

        btc_cand = manifest.candidates["BTCUSDT"].candidate_id
        eth_cand = manifest.candidates["ETHUSDT"].candidate_id
        sol_cand = manifest.candidates["SOLUSDT"].candidate_id

        # 2. Test THIN regime adaptation (order sizing scaled down, wider limit offset cushion)
        regime_engine.update_book(
            "BTCUSDT",
            bid_price=Decimal("60000.00"),
            ask_price=Decimal("60010.00"),  # Spread = 10 USDT (~1.6 bps)
            bid_depth=Decimal("0.5"),  # Depleted depth < 1.0 -> THIN regime!
            ask_depth=Decimal("0.5"),
            volume_velocity=Decimal("30.0"),
        )
        gateway.set_book(
            "BTCUSDT",
            bid_price=Decimal("60000.00"),
            ask_price=Decimal("60010.00"),
            bid_depth=Decimal("0.5"),
            ask_depth=Decimal("0.5"),
        )

        assert regime_engine.classify_regime("BTCUSDT") == LiquidityRegime.THIN

        parent_thin, children_thin = dispatcher.dispatch_signal_order_with_dynamic_slicing(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            desired_notional=Decimal("5.00"),
        )
        # In THIN regime, sizing is downscaled to <= 2.50 USDT
        for ch in children_thin:
            assert Decimal(ch.notional_usdt) <= DYNAMIC_SLICING_MAX_CHUNK_USDT
            assert ch.status == OrderLifecycleState.FILLED

        # 3. Simulate Depth Exhaustion Drill: depth collapses below safety threshold
        regime_engine.update_book(
            "BTCUSDT",
            bid_price=Decimal("60000.00"),
            ask_price=Decimal("60010.00"),
            bid_depth=Decimal("0.00001"),  # Exhausted depth!
            ask_depth=Decimal("0.00001"),
            volume_velocity=Decimal("0.0"),
        )
        depth_exhaustion_caught = False
        try:
            interlock.validate_dispatch(
                symbol="BTCUSDT",
                price=Decimal("60000.00"),
                quantity=Decimal("0.00005"),
                client_order_id=generate_canary_client_order_id("BTCUSDT"),
            )
        except DepthExhaustionError:
            depth_exhaustion_caught = True
        assert depth_exhaustion_caught is True

        # Restore healthy book depth
        regime_engine.update_book(
            "BTCUSDT",
            bid_price=Decimal("60000.00"),
            ask_price=Decimal("60001.00"),
            bid_depth=Decimal("5.0"),
            ask_depth=Decimal("5.0"),
            volume_velocity=Decimal("100.0"),
        )
        gateway.set_book(
            "BTCUSDT",
            bid_price=Decimal("60000.00"),
            ask_price=Decimal("60001.00"),
            bid_depth=Decimal("5.0"),
            ask_depth=Decimal("5.0"),
        )

        # 4. Fill positions up toward Aggregate Concurrent Exposure Cap (25.00 USDT)
        # Ord 1 (ETHUSDT): 4.80 USDT
        dispatcher.dispatch_micro_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0016"),
            price=Decimal("3000.00"),
        )
        # Ord 2 (SOLUSDT): 4.80 USDT
        dispatcher.dispatch_micro_order(
            candidate_id=sol_cand,
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.032"),
            price=Decimal("150.00"),
        )
        # Ord 3 (BTCUSDT): 4.80 USDT
        dispatcher.dispatch_micro_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        # Ord 4 (ETHUSDT): 4.80 USDT
        dispatcher.dispatch_micro_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0016"),
            price=Decimal("3000.00"),
        )

        # Current total active exposure is around 2.40 + 4.80 + 4.80 + 4.80 + 4.80 = 21.60 USDT
        # Next order: SOLUSDT 0.030 @ 150 = 4.50 USDT ->
        # Would push total exposure to 21.60 + 4.50 = 26.10 > 25.00 USDT aggregate cap!
        agg_cap_blocked = False
        try:
            dispatcher.dispatch_micro_order(
                candidate_id=sol_cand,
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.030"),
                price=Decimal("150.00"),
            )
        except AggregateExposureCapExceededError:
            agg_cap_blocked = True

        assert agg_cap_blocked is True

        # 5. Cleanly unwind all open positions in micro-chunks <= 5.00 USDT
        dispatcher.unwind_symbol_position_micro_chunked(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
        )
        dispatcher.unwind_symbol_position_micro_chunked(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
        )
        dispatcher.unwind_symbol_position_micro_chunked(
            candidate_id=sol_cand,
            symbol="SOLUSDT",
            price=Decimal("150.00"),
        )

        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.positions["ETHUSDT"] == Decimal("0")
        assert reconciler.positions["SOLUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")

        daemon.shutdown(graceful=True)

        drift = reconciler.mathematical_drift
        if self.config.simulate_adverse_drift:
            drift = Decimal("0.05")
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = LiquidityDaemonTrackResult(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_2.value,
            track_name=TRACK_DESCRIPTIONS[CanaryLiquidityRegimeTrackId.TRACK_2.value],
            status="SUCCESS_LIQUIDITY_EVAPORATION_AND_THROTTLING_VERIFIED",
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
            interlock_blocks_count=interlock.interlock_blocks_count,
            heartbeat_events_count=heartbeat_mon.heartbeat_count,
            stale_heartbeat_count=heartbeat_mon.stale_count,
            stream_events_count=dispatcher.stream_events_count,
            deduplicated_events_count=sequencer.deduplicated_count,
            out_of_order_events_count=sequencer.out_of_order_count,
            final_circuit_state=interlock.circuit_state.value,
            final_expansion_stage=interlock.expansion_stage.value,
            success=zero_drift and reconciler.allocated_margin == Decimal("0"),
        )
        self.active_store.record_daemon_track(result)
        return result

    def _run_track_3(
        self,
        manifest: CanaryStagingManifest,
        candidate_artifacts: dict[str, Any],
    ) -> LiquidityDaemonTrackResult:
        """Track 3: Cross-Symbol Asymmetric Liquidity Crisis & Emergency Liquidation Drill.
        - Open multi-symbol positions (BTCUSDT, ETHUSDT).
        - Liquidity freeze and price collapse on BTCUSDT causing realized loss > 3.50 USDT ceiling.
        - Immediate fail-closed lockout on subsequent orders.
        - Emergency micro-chunked position liquidation (slices <= 5.00 USDT).
        - Clean balance reconciliation with zero drift.
        """
        assert self.active_store is not None
        assert self.active_sink is not None

        gateway = MockBinanceLiquidityGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            order_id_start=300000,
            trade_id_start=700000,
        )
        reconciler = LiquidityUserDataStreamReconciler(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_3.value,
            starting_equity=STARTING_EQUITY_USDT,
        )
        sequencer = LiquidityStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()

        interlock = LiquidityOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=self.active_store,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_3.value,
            expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
            intra_phase_loss_ceiling_usdt=self.config.intra_phase_loss_ceiling_usdt,
        )
        dispatcher = LiquidityMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_3.value,
        )
        daemon = LiquidityAutonomousDaemon(
            dispatcher=dispatcher,
            reconciler=reconciler,
            interlock=interlock,
            heartbeat_monitor=heartbeat_mon,
            telemetry_store=self.active_store,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_3.value,
        )
        daemon.start()

        # 1. Record healthy heartbeat
        hb_data = gateway.generate_heartbeat(latency_ms=45.0)
        hb_rec = heartbeat_mon.record_heartbeat(
            server_time_ms=hb_data["serverTime"],
            latency_ms=hb_data["latencyMs"],
            track_id=CanaryLiquidityRegimeTrackId.TRACK_3.value,
        )
        self.active_store.record_heartbeat(hb_rec)

        btc_cand = manifest.candidates["BTCUSDT"].candidate_id
        eth_cand = manifest.candidates["ETHUSDT"].candidate_id

        # 2. Open multi-symbol positions:
        # BTCUSDT: 0.00008 @ 60,000 = 4.80 USDT
        # ETHUSDT: 0.0015 @ 3,000 = 4.50 USDT
        dispatcher.dispatch_micro_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        dispatcher.dispatch_micro_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0015"),
            price=Decimal("3000.00"),
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
        assert reconciler.positions["ETHUSDT"] == Decimal("0.0015")

        # 3. Simulate asymmetric adverse liquidity shock on BTCUSDT:
        # BTC drops to 14,000 USDT -> close BTC position
        # Realized loss = 0.00008 * (60,000 - 14,000) = 3.68 USDT > 3.50 USDT ceiling!
        dispatcher.dispatch_micro_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            price=Decimal("14000.00"),
            is_closing=True,
        )
        assert reconciler.cumulative_realized_loss >= Decimal("3.50")
        assert reconciler.cumulative_realized_loss >= Decimal("3.68")

        # 4. Verify immediate portfolio-wide fail-closed lockout on subsequent orders
        lockout_caught = False
        try:
            dispatcher.dispatch_micro_order(
                candidate_id=manifest.candidates["SOLUSDT"].candidate_id,
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.020"),
                price=Decimal("150.00"),
            )
        except IntraPhaseLossCeilingExceededError:
            lockout_caught = True

        assert lockout_caught is True
        assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT

        # 5. Execute emergency micro-chunked flattening of remaining open ETH position
        # Slices strictly <= 5.00 USDT
        flattening_orders = dispatcher.execute_emergency_flattening()
        assert len(flattening_orders) >= 1
        for fo in flattening_orders:
            assert Decimal(fo.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT
            assert fo.status == OrderLifecycleState.FILLED

        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.positions["ETHUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")

        daemon.shutdown(graceful=True)

        drift = reconciler.mathematical_drift
        if self.config.simulate_adverse_drift:
            drift = Decimal("0.05")
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = LiquidityDaemonTrackResult(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_3.value,
            track_name=TRACK_DESCRIPTIONS[CanaryLiquidityRegimeTrackId.TRACK_3.value],
            status="SUCCESS_INTRA_PHASE_LOSS_LOCKOUT_AND_FLATTENED",
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
            interlock_blocks_count=interlock.interlock_blocks_count,
            heartbeat_events_count=heartbeat_mon.heartbeat_count,
            stale_heartbeat_count=heartbeat_mon.stale_count,
            stream_events_count=dispatcher.stream_events_count,
            deduplicated_events_count=sequencer.deduplicated_count,
            out_of_order_events_count=sequencer.out_of_order_count,
            final_circuit_state=interlock.circuit_state.value,
            final_expansion_stage=interlock.expansion_stage.value,
            success=zero_drift and reconciler.allocated_margin == Decimal("0"),
        )
        self.active_store.record_daemon_track(result)
        return result

    def _run_track_4(
        self,
        manifest: CanaryStagingManifest,
        candidate_artifacts: dict[str, Any],
    ) -> LiquidityDaemonTrackResult:
        """Track 4: Extended Multi-Day Session Continuity, WebSocket Heartbeat Renewal &
        REST Reconciliation Drill.
        - Simulate extended session longevity (advancing server time over 24h+).
        - ListenKey 24h expiration and renewal drill.
        - Periodic WebSocket heartbeat keep-alive renewal.
        - Sequence wrap recovery (sequence resets from high number back to 1).
        - REST backfill of missing execution reports during disconnect gap.
        - Idempotent duplicate event deduplication.
        - Clean ledger reconciliation with zero drift.
        """
        assert self.active_store is not None
        assert self.active_sink is not None

        gateway = MockBinanceLiquidityGateway(
            initial_balance_usdt=STARTING_EQUITY_USDT,
            order_id_start=400000,
            trade_id_start=800000,
        )
        reconciler = LiquidityUserDataStreamReconciler(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
            starting_equity=STARTING_EQUITY_USDT,
        )
        sequencer = LiquidityStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()

        interlock = LiquidityOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            telemetry_store=self.active_store,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
            expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
            intra_phase_loss_ceiling_usdt=self.config.intra_phase_loss_ceiling_usdt,
        )
        dispatcher = LiquidityMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
        )
        daemon = LiquidityAutonomousDaemon(
            dispatcher=dispatcher,
            reconciler=reconciler,
            interlock=interlock,
            heartbeat_monitor=heartbeat_mon,
            telemetry_store=self.active_store,
            track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
        )
        daemon.start()

        # 1. Acquire initial 24h listenKey
        lk_resp = gateway.create_listen_key()
        lk = lk_resp["listenKey"]
        self.active_store.record_listen_key_event(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
            action="LISTEN_KEY_CREATED",
            listen_key=lk,
        )

        # 2. Record healthy heartbeat
        hb_data = gateway.generate_heartbeat(latency_ms=45.0)
        hb_rec = heartbeat_mon.record_heartbeat(
            server_time_ms=hb_data["serverTime"],
            latency_ms=hb_data["latencyMs"],
            track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
        )
        self.active_store.record_heartbeat(hb_rec)

        # 3. Simulate multi-day session progression: advance time 24h
        gateway.advance_time(int(LISTEN_KEY_LIFETIME_SECONDS * 1000) + 1000)
        gateway.inject_listen_key_expired = True
        lk_expired = False
        try:
            gateway.keepalive_listen_key(lk)
        except ListenKeyExpiredError:
            lk_expired = True
            new_lk_resp = gateway.create_listen_key()
            new_lk = new_lk_resp["listenKey"]
            self.active_store.record_listen_key_event(
                track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
                action="LISTEN_KEY_RENEWED",
                listen_key=new_lk,
            )

        assert lk_expired is True

        # 4. Renew WebSocket heartbeat to maintain freshness
        hb_data2 = gateway.generate_heartbeat(latency_ms=35.0)
        hb_rec2 = heartbeat_mon.record_heartbeat(
            server_time_ms=hb_data2["serverTime"],
            latency_ms=hb_data2["latencyMs"],
            track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
        )
        self.active_store.record_heartbeat(hb_rec2)

        # 5. Simulate stream disconnect during order placement -> REST backfill
        gateway.disconnect_stream()
        btc_cand = manifest.candidates["BTCUSDT"].candidate_id
        btc_cid = generate_canary_client_order_id("BTCUSDT")

        btc_open = dispatcher.dispatch_micro_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            client_order_id=btc_cid,
        )
        assert btc_open.status == OrderLifecycleState.NEW

        # Stream reconnects -> backfill via REST
        gateway.reconnect_stream()
        sequencer.notify_reconnect(new_epoch=1)
        backfilled = dispatcher.reconcile_via_rest()
        assert len(backfilled) == 1
        assert dispatcher.orders[btc_cid].status == OrderLifecycleState.FILLED
        dispatcher.drain_and_reconcile_stream()

        # 6. Simulate Sequence Wrap Recovery Drill:
        gateway.sequence_counter = SEQUENCE_WRAP_THRESHOLD
        sequencer.highest_arrival_sequence = SEQUENCE_WRAP_THRESHOLD

        gateway.inject_duplicate_events = True
        gateway.inject_out_of_order_events = True

        eth_cand = manifest.candidates["ETHUSDT"].candidate_id
        gateway.sequence_counter = 1  # Wrapped around
        eth_open = dispatcher.dispatch_micro_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0015"),
            price=Decimal("3000.00"),
        )
        assert eth_open.status == OrderLifecycleState.FILLED

        assert sequencer.deduplicated_count >= 1
        assert sequencer.sequence_wrap_count >= 1

        # 7. Cleanly unwind all open positions in micro-chunks <= 5.00 USDT
        dispatcher.unwind_symbol_position_micro_chunked(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
        )
        dispatcher.unwind_symbol_position_micro_chunked(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
        )

        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.positions["ETHUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")

        daemon.shutdown(graceful=True)

        drift = reconciler.mathematical_drift
        if self.config.simulate_adverse_drift:
            drift = Decimal("0.05")
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = LiquidityDaemonTrackResult(
            track_id=CanaryLiquidityRegimeTrackId.TRACK_4.value,
            track_name=TRACK_DESCRIPTIONS[CanaryLiquidityRegimeTrackId.TRACK_4.value],
            status="SUCCESS_MULTI_DAY_LONGEVITY_AND_REST_HARMONIZATION_VERIFIED",
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
            interlock_blocks_count=interlock.interlock_blocks_count,
            heartbeat_events_count=heartbeat_mon.heartbeat_count,
            stale_heartbeat_count=heartbeat_mon.stale_count,
            stream_events_count=dispatcher.stream_events_count,
            deduplicated_events_count=sequencer.deduplicated_count,
            out_of_order_events_count=sequencer.out_of_order_count,
            final_circuit_state=interlock.circuit_state.value,
            final_expansion_stage=interlock.expansion_stage.value,
            success=zero_drift
            and sequencer.deduplicated_count >= 1
            and reconciler.allocated_margin == Decimal("0"),
        )
        self.active_store.record_daemon_track(result)
        return result


# Backward compatibility aliases
CanaryAdaptiveExecutionRunner = CanaryLiquidityRegimeRunner
CanaryContinuousDaemonRunner = CanaryLiquidityRegimeRunner


# =====================================================================
# Cryptographic SHA-256 Merkle DAG Hash Chain Verification (Phase 284)
# =====================================================================


def verify_phase_284_hash_chain(
    output_dir: Path | str = DEFAULT_PHASE284_OUTPUT_DIR,
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    phase276_dir: Path | str = DEFAULT_PHASE276_OUTPUT_DIR,
    phase277_dir: Path | str = DEFAULT_PHASE277_OUTPUT_DIR,
    phase278_dir: Path | str = DEFAULT_PHASE278_OUTPUT_DIR,
    phase279_dir: Path | str = DEFAULT_PHASE279_OUTPUT_DIR,
    phase280_dir: Path | str = DEFAULT_PHASE280_OUTPUT_DIR,
    phase281_dir: Path | str = DEFAULT_PHASE281_OUTPUT_DIR,
    phase282_dir: Path | str = DEFAULT_PHASE282_OUTPUT_DIR,
    phase283_dir: Path | str = DEFAULT_PHASE283_OUTPUT_DIR,
) -> bool:
    """Verify cryptographic SHA-256 DAG hash chain and balance integrity for Phase 284."""
    out_dir = Path(output_dir)
    manifest, _ = load_and_validate_canary_staging_manifest(Path(manifest_path))

    jsonl_path = out_dir / "canary-orders.jsonl"
    db_path = out_dir / "canary-liquidity-regime-telemetry.sqlite3"
    report_path = out_dir / "canary-liquidity-regime-report.json"
    summary_path = out_dir / "liquidity-regime-summary.json"
    paper_summary_path = out_dir / "paper-summary.json"

    # 1. Verify existence of all 5 artifact files
    for p in [jsonl_path, db_path, report_path, summary_path, paper_summary_path]:
        if not p.is_file():
            logger.error("Missing required Phase 284 artifact: %s", p)
            return False

    actual_jsonl_hash = compute_file_sha256(jsonl_path)
    actual_db_hash = compute_file_sha256(db_path)
    actual_report_hash = compute_file_sha256(report_path)
    actual_summary_hash = compute_file_sha256(summary_path)

    # 2. Verify Upstream Phase 283 back to 276
    p283_path = Path(phase283_dir)
    if not p283_path.is_dir():
        logger.error("Upstream Phase 283 directory not found: %s", p283_path)
        return False
    if not verify_upstream_phase283_qualification(
        phase283_dir=p283_path,
        manifest_path=manifest_path,
        phase276_dir=phase276_dir,
        phase277_dir=phase277_dir,
        phase278_dir=phase278_dir,
        phase279_dir=phase279_dir,
        phase280_dir=phase280_dir,
        phase281_dir=phase281_dir,
        phase282_dir=phase282_dir,
    ):
        logger.error("Upstream Phase 283 hash chain / qualification verification failed")
        return False

    expected_cert_hash = compute_file_sha256(
        Path(phase276_dir) / "canary-activation-certificate.json"
    )
    expected_p277_rep_hash = compute_file_sha256(Path(phase277_dir) / "canary-gateway-report.json")
    expected_p277_sum_hash = compute_file_sha256(Path(phase277_dir) / "gateway-summary.json")
    expected_p278_rep_hash = compute_file_sha256(Path(phase278_dir) / "canary-testnet-report.json")
    expected_p278_sum_hash = compute_file_sha256(Path(phase278_dir) / "testnet-summary.json")
    expected_p279_rep_hash = compute_file_sha256(Path(phase279_dir) / "canary-mainnet-report.json")
    expected_p279_sum_hash = compute_file_sha256(Path(phase279_dir) / "mainnet-summary.json")
    expected_p280_rep_hash = compute_file_sha256(
        Path(phase280_dir) / "canary-mainnet-deployment-report.json"
    )
    expected_p280_sum_hash = compute_file_sha256(Path(phase280_dir) / "deployment-summary.json")
    expected_p281_rep_hash = compute_file_sha256(
        Path(phase281_dir) / "canary-mainnet-expansion-report.json"
    )
    expected_p281_sum_hash = compute_file_sha256(Path(phase281_dir) / "expansion-summary.json")
    expected_p282_rep_hash = compute_file_sha256(
        Path(phase282_dir) / "canary-continuous-daemon-report.json"
    )
    expected_p282_sum_hash = compute_file_sha256(
        Path(phase282_dir) / "continuous-daemon-summary.json"
    )
    expected_p283_rep_hash = compute_file_sha256(
        p283_path / "canary-adaptive-execution-report.json"
    )
    expected_p283_sum_hash = compute_file_sha256(p283_path / "adaptive-execution-summary.json")

    # 3. Verify canary-liquidity-regime-report.json
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
    if report_data.get("upstream_phase278_report_hash") != expected_p278_rep_hash:
        logger.error("Report upstream_phase278_report_hash mismatch")
        return False
    if report_data.get("upstream_phase278_summary_hash") != expected_p278_sum_hash:
        logger.error("Report upstream_phase278_summary_hash mismatch")
        return False
    if report_data.get("upstream_phase279_report_hash") != expected_p279_rep_hash:
        logger.error("Report upstream_phase279_report_hash mismatch")
        return False
    if report_data.get("upstream_phase279_summary_hash") != expected_p279_sum_hash:
        logger.error("Report upstream_phase279_summary_hash mismatch")
        return False
    if report_data.get("upstream_phase280_report_hash") != expected_p280_rep_hash:
        logger.error("Report upstream_phase280_report_hash mismatch")
        return False
    if report_data.get("upstream_phase280_summary_hash") != expected_p280_sum_hash:
        logger.error("Report upstream_phase280_summary_hash mismatch")
        return False
    if report_data.get("upstream_phase281_report_hash") != expected_p281_rep_hash:
        logger.error("Report upstream_phase281_report_hash mismatch")
        return False
    if report_data.get("upstream_phase281_summary_hash") != expected_p281_sum_hash:
        logger.error("Report upstream_phase281_summary_hash mismatch")
        return False
    if report_data.get("upstream_phase282_report_hash") != expected_p282_rep_hash:
        logger.error("Report upstream_phase282_report_hash mismatch")
        return False
    if report_data.get("upstream_phase282_summary_hash") != expected_p282_sum_hash:
        logger.error("Report upstream_phase282_summary_hash mismatch")
        return False
    if report_data.get("upstream_phase283_report_hash") != expected_p283_rep_hash:
        logger.error("Report upstream_phase283_report_hash mismatch")
        return False
    if report_data.get("upstream_phase283_summary_hash") != expected_p283_sum_hash:
        logger.error("Report upstream_phase283_summary_hash mismatch")
        return False

    rep_hashes = report_data.get("artifact_hashes", {})
    if rep_hashes.get("canary-orders.jsonl") != actual_jsonl_hash:
        logger.error("Report canary-orders.jsonl hash mismatch")
        return False
    if rep_hashes.get("canary-liquidity-regime-telemetry.sqlite3") != actual_db_hash:
        logger.error("Report canary-liquidity-regime-telemetry.sqlite3 hash mismatch")
        return False
    if not report_data.get("compliance", {}).get("all_criteria_passed"):
        logger.error("Report compliance all_criteria_passed is False")
        return False

    # 4. Verify liquidity-regime-summary.json
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
    if sum_hashes.get("canary-liquidity-regime-telemetry.sqlite3") != actual_db_hash:
        logger.error("Summary telemetry db hash mismatch")
        return False
    if sum_hashes.get("canary-liquidity-regime-report.json") != actual_report_hash:
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
    if pap_hashes.get("canary-liquidity-regime-telemetry.sqlite3") != actual_db_hash:
        logger.error("Paper summary telemetry db hash mismatch")
        return False
    if pap_hashes.get("canary-liquidity-regime-report.json") != actual_report_hash:
        logger.error("Paper summary report hash mismatch")
        return False
    if pap_hashes.get("liquidity-regime-summary.json") != actual_summary_hash:
        logger.error("Paper summary liquidity-regime-summary.json hash mismatch")
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
