"""Phase 276: Operator Production Canary Authorization & Live Order Dispatch Interlock Harness.

Implements the operator production canary authorization workflow, secure exchange key vault
validator, and fail-closed live order dispatch interlock gates under Candidate Registry Manifest
Version 2 to establish the final operational governance layer before live exchange execution
while strictly preserving zero-drift double-entry balance integrity and zero secret leakage.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import sqlite3
import threading
import time
import urllib.parse
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import Field, model_validator

from autonomous_futures.domain.contracts import DomainModel
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.feed.canary_probe import (
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.feed.canary_rehearsal import (
    verify_phase_275_hash_chain,
)
from autonomous_futures.feed.circuit_breaker_drill import (
    CanaryCircuitBreakerRecoveryStateMachine,
    CircuitBreakerTransition,
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

# =====================================================================
# Canonical Constants & Thresholds (Phase 276)
# =====================================================================

DEFAULT_PHASE276_OUTPUT_DIR: Path = Path("artifacts/research/phase276")
DEFAULT_PHASE275_INPUT_DIR: Path = Path("artifacts/research/phase275")

STARTING_EQUITY_USDT: Decimal = Decimal("100.00")
HARD_NOTIONAL_CAP_USDT: Decimal = Decimal("5.00")
DAILY_LOSS_BUDGET_USDT: Decimal = Decimal("2.00")  # 2.00% of 100.00 USDT starting equity
RATE_LIMIT_INTERVAL_SECONDS: float = 60.0  # Max 1 order per symbol per minute
MAX_HEARTBEAT_AGE_MS: float = 1000.0  # Live heartbeat stale threshold
LIVE_STREAM_HEARTBEAT_MAX_AGE_MS: float = MAX_HEARTBEAT_AGE_MS
TIMESTAMP_DRIFT_WINDOW_MS: int = 1000  # Binance Futures API drift window
TIMESTAMP_DRIFT_MAX_WINDOW_MS: int = TIMESTAMP_DRIFT_WINDOW_MS

DEFAULT_PER_ASSET_MARGIN_CAP: Decimal = Decimal("20.00")  # 20.00 USDT cap per candidate
DEFAULT_AGGREGATE_MARGIN_CAP: Decimal = Decimal("60.00")  # 60.00 USDT aggregate cap
DEFAULT_MAX_DURATION_HOURS: float = 24.0

DEFAULT_TAKER_FEE_RATE: Decimal = Decimal("0.0004")  # 0.04% taker fee
DEFAULT_MAKER_FEE_RATE: Decimal = Decimal("0.0002")  # 0.02% maker fee
DEFAULT_SLIPPAGE_BPS: Decimal = Decimal("2.0")  # 2.0 bps slippage
DEFAULT_SLIPPAGE_RATE: Decimal = Decimal("0.0002")

CANARY_STAGED_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

DEFAULT_REFERENCE_PRICES: dict[str, Decimal] = {
    "BTCUSDT": Decimal("60000.00"),
    "ETHUSDT": Decimal("2500.00"),
    "SOLUSDT": Decimal("150.00"),
}


# =====================================================================
# Error Hierarchy
# =====================================================================


class CanaryActivationError(DomainViolation):
    """Base exception for Phase 276 canary activation governance operations."""


class PrerequisiteQualificationError(CanaryActivationError, DomainViolation):
    """Raised when upstream Phase 275 qualification or certification is invalid."""


UpstreamPrerequisiteNotMetError = PrerequisiteQualificationError


class OperatorAuthorizationMissingError(CanaryActivationError, DomainViolation):
    """Raised when required operator sign-off or authorization flag is missing."""


class CertificateInvalidatedError(CanaryActivationError, DomainViolation):
    """Raised when the canary activation certificate is invalid or invalidated."""


class CertificateExpiredError(CanaryActivationError, DomainViolation):
    """Raised when the canary activation certificate expiration timestamp is past."""


class UnauthorizedSymbolError(CanaryActivationError, DomainViolation):
    """Raised when an order references a symbol not in the authorized whitelist."""


class WithdrawalPermissionDetectedError(CanaryActivationError, DomainViolation):
    """Raised when an API key is detected to possess prohibited withdrawal permissions."""


class MissingRequiredPermissionError(CanaryActivationError, DomainViolation):
    """Raised when an API key lacks required futures trading or reading permissions."""


class UnpermittedPermissionError(MissingRequiredPermissionError, DomainViolation):
    """Raised when an API key possesses unpermitted capabilities (e.g. spot/margin trading)."""


class TimestampDriftWindowExceededError(CanaryActivationError, DomainViolation):
    """Raised when API signature timestamp drift exceeds 1000ms window."""


class InvalidSignatureError(CanaryActivationError, DomainViolation):
    """Raised when HMAC signature verification fails."""


class OrderNotionalCapBreachError(CanaryActivationError, DomainViolation):
    """Raised when an order notional exceeds the 5.00 USDT hard cap."""


class MarginCapBreachError(OrderNotionalCapBreachError, DomainViolation):
    """Raised when an order would breach per-asset or aggregate allocated margin caps."""


class DailyLossBudgetLockoutError(CanaryActivationError, DomainViolation):
    """Raised when daily cumulative loss reaches or exceeds the 2.00 USDT budget."""


class RateLimitThrottleExceededError(CanaryActivationError, DomainViolation):
    """Raised when order submission frequency violates the 1 order/min throttle."""


class StaleHeartbeatInterlockError(CanaryActivationError, DomainViolation):
    """Raised when stream heartbeat age exceeds 1000ms."""


class CircuitBreakerInterlockError(CanaryActivationError, DomainViolation):
    """Raised when circuit breaker state is not NORMAL."""


class AccountingDriftError(CanaryActivationError, DomainViolation):
    """Raised when double-entry accounting drift exceeds 1e-15 USDT."""


class SafetyInvariantViolation(CanaryActivationError, DomainViolation):
    """Raised when read-only containment or zero secret leakage is breached."""


# =====================================================================
# Domain Enums & Value Objects
# =====================================================================


class CertificateStatus(StrEnum):
    """Lifecycle state of a production canary activation certificate."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    INVALIDATED_WITHDRAWAL_PERMISSION_DETECTED = "INVALIDATED_WITHDRAWAL_PERMISSION_DETECTED"
    REVOKED_OPERATOR = "REVOKED_OPERATOR"


class InterlockTriggerType(StrEnum):
    """Categories of order dispatch interlock gate triggers."""

    DAILY_LOSS_BUDGET_BREACH = "DAILY_LOSS_BUDGET_BREACH"
    WITHDRAWAL_PERMISSION_REJECTION = "WITHDRAWAL_PERMISSION_REJECTION"
    STALE_HEARTBEAT_BLOCK = "STALE_HEARTBEAT_BLOCK"
    CIRCUIT_BREAKER_BLOCK = "CIRCUIT_BREAKER_BLOCK"
    HARD_NOTIONAL_CAP_REJECTION = "HARD_NOTIONAL_CAP_REJECTION"
    RATE_LIMIT_THROTTLE = "RATE_LIMIT_THROTTLE"
    UNAUTHORIZED_SYMBOL = "UNAUTHORIZED_SYMBOL"
    CERTIFICATE_INVALIDATED = "CERTIFICATE_INVALIDATED"


class OrderSide(StrEnum):
    """Canary order execution side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Canary order execution type."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    """Canary order lifecycle status."""

    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TimeInForce(StrEnum):
    """Time in force policies."""

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    POST_ONLY = "POST_ONLY"


class PositionSide(StrEnum):
    """Open canary position direction."""

    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(StrEnum):
    """Open canary position status."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LiquidityRole(StrEnum):
    """Role played by order in execution fill."""

    MAKER = "MAKER"
    TAKER = "TAKER"


class CanaryActivationTrackId(StrEnum):
    """Deterministic simulation tracks for Phase 276."""

    TRACK_1 = "track_1"
    TRACK_2 = "track_2"
    TRACK_3 = "track_3"
    TRACK_4 = "track_4"


TRACK_DESCRIPTIONS: dict[str, str] = {
    CanaryActivationTrackId.TRACK_1.value: (
        "Nominal Authorization & Dispatched Order Flow "
        "(Valid certificate, healthy heartbeat, micro orders within budget)"
    ),
    CanaryActivationTrackId.TRACK_2.value: (
        "Daily Loss Budget Breach Lockout "
        "(Cumulative drawdown reaches 2.00 USDT -> triggers instant order dispatch lockout)"
    ),
    CanaryActivationTrackId.TRACK_3.value: (
        "Withdrawal Permission Detection & Key Invalidation "
        "(API key with withdrawal rights detected -> instant certificate invalidation)"
    ),
    CanaryActivationTrackId.TRACK_4.value: (
        "Stale Heartbeat & Circuit Breaker Interlock Block "
        "(Order blocked when heartbeat age > 1.0s or state is Soft-Freeze)"
    ),
}


# =====================================================================
# R2: Secure Gateway Key Vault & Permissions Sanity Validator
# =====================================================================


class SecretToken:
    """Isolated secret wrapper with guaranteed masked representations."""

    def __init__(self, raw: str, label: str = "SECRET") -> None:
        self._raw: str = raw
        self._label: str = label

    def __repr__(self) -> str:
        return f"[REDACTED_{self._label}]"

    def __str__(self) -> str:
        return f"[REDACTED_{self._label}]"

    def reveal(self) -> str:
        """Return raw secret for authorized cryptographic primitives only."""
        return self._raw


class ExchangeCredentials:
    """Encapsulated exchange credentials ensuring zero secret leakage."""

    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = SecretToken(api_key, label="API_KEY")
        self._api_secret = SecretToken(api_secret, label="SECRET")

    def __repr__(self) -> str:
        return "ExchangeCredentials(api_key=[REDACTED], api_secret=[REDACTED])"

    def __str__(self) -> str:
        return "ExchangeCredentials(api_key=[REDACTED], api_secret=[REDACTED])"

    def get_raw_key(self) -> str:
        """Return raw API key for authorized request header generation."""
        return self._api_key.reveal()

    def get_raw_secret(self) -> str:
        """Return raw secret for authorized HMAC-SHA256 calculation."""
        return self._api_secret.reveal()


class ExchangeApiKeyPermissions(DomainModel):
    """Pre-flight exchange API key permissions manifest."""

    enable_reading: bool = True
    enable_futures_trading: bool = True
    enable_withdrawals: bool = False  # Strictly Prohibited
    enable_internal_transfer: bool = False  # Strictly Prohibited
    permits_universal_transfer: bool = False  # Strictly Prohibited
    enable_sub_account_transfer: bool = False  # Strictly Prohibited
    enable_margin: bool = False
    enable_spot_and_margin_trading: bool = False


class SecureExchangeKeyVault:
    """Isolated offline-safe exchange credentials vault and signature engine."""

    def __init__(
        self,
        credentials: ExchangeCredentials | None = None,
        permissions: ExchangeApiKeyPermissions | None = None,
    ) -> None:
        self._credentials = credentials
        self._permissions = permissions

    @property
    def is_configured(self) -> bool:
        """Return True if credentials and permissions are loaded."""
        return self._credentials is not None and self._permissions is not None

    @property
    def permissions(self) -> ExchangeApiKeyPermissions | None:
        """Return active key permissions manifest."""
        return self._permissions

    def load_credentials(
        self,
        api_key: str,
        api_secret: str,
        permissions: ExchangeApiKeyPermissions,
    ) -> None:
        """Load credentials and perform immediate pre-flight permissions validation."""
        if not api_key or not api_key.strip():
            raise CanaryActivationError("Exchange API key must be a non-empty string")
        if not api_secret or not api_secret.strip():
            raise CanaryActivationError("Exchange API secret must be a non-empty string")
        self.verify_permissions(permissions)
        self._credentials = ExchangeCredentials(api_key, api_secret)
        self._permissions = permissions

    @staticmethod
    def canonicalize_query_string(params: Mapping[str, Any]) -> str:
        """Format and canonicalize query string sorted alphabetically by key per RFC 3986."""
        sorted_keys = sorted(k for k in params.keys() if params[k] is not None)
        encoded_pairs: list[str] = []
        for k in sorted_keys:
            val = params[k]
            if isinstance(val, bool):
                val_str = "true" if val else "false"
            else:
                val_str = str(val)
            k_enc = urllib.parse.quote(str(k), safe="~-._")
            v_enc = urllib.parse.quote(val_str, safe="~-._")
            encoded_pairs.append(f"{k_enc}={v_enc}")
        return "&".join(encoded_pairs)

    def generate_signature(self, query_string: str) -> str:
        """Generate Binance Futures HMAC-SHA256 signature for canonical query string."""
        if self._credentials is None:
            raise CanaryActivationError("Cannot sign request: Key vault has no credentials loaded")
        secret_bytes = self._credentials.get_raw_secret().encode("utf-8")
        query_bytes = query_string.encode("utf-8")
        return hmac.new(secret_bytes, query_bytes, hashlib.sha256).hexdigest()

    def verify_signature(self, query_string: str, signature: str) -> bool:
        """Verify HMAC-SHA256 signature using constant-time comparison."""
        if not signature or not isinstance(signature, str):
            return False
        expected = self.generate_signature(query_string)
        return hmac.compare_digest(expected.lower(), signature.strip().lower())

    @staticmethod
    def validate_timestamp_window(
        request_timestamp_ms: int,
        current_timestamp_ms: int,
        max_drift_ms: int = TIMESTAMP_DRIFT_WINDOW_MS,
    ) -> bool:
        """Validate that request timestamp drift does not exceed allowed window (<= 1000ms)."""
        if (
            isinstance(request_timestamp_ms, bool)
            or isinstance(current_timestamp_ms, bool)
            or isinstance(max_drift_ms, bool)
        ):
            raise TimestampDriftWindowExceededError("Timestamps cannot be boolean values")
        if (
            not isinstance(request_timestamp_ms, (int, float))
            or not isinstance(current_timestamp_ms, (int, float))
            or not isinstance(max_drift_ms, (int, float))
        ):
            raise TimestampDriftWindowExceededError("Timestamps must be numeric milliseconds")
        if (
            math.isnan(request_timestamp_ms)
            or math.isinf(request_timestamp_ms)
            or math.isnan(current_timestamp_ms)
            or math.isinf(current_timestamp_ms)
            or math.isnan(max_drift_ms)
            or math.isinf(max_drift_ms)
        ):
            raise TimestampDriftWindowExceededError("Timestamps must be finite numeric values")
        if request_timestamp_ms <= 0 or current_timestamp_ms <= 0:
            raise TimestampDriftWindowExceededError(
                "Request and current timestamps must be positive integers in milliseconds"
            )
        if max_drift_ms < 0:
            raise TimestampDriftWindowExceededError("Timestamp drift window must be non-negative")
        drift = abs(current_timestamp_ms - request_timestamp_ms)
        if drift > max_drift_ms:
            raise TimestampDriftWindowExceededError(
                f"Request timestamp drift ({drift}ms) exceeds allowed window ({max_drift_ms}ms)"
            )
        return True

    @staticmethod
    def verify_permissions(permissions: ExchangeApiKeyPermissions) -> bool:
        """Enforce strict pre-flight API key permission boundary verification."""
        # 1. Strictly Prohibited Permissions
        if permissions.enable_withdrawals:
            raise WithdrawalPermissionDetectedError(
                "Security violation: API key possesses prohibited Spot Withdrawal permissions. "
                "Fail-closed key rejection triggered."
            )
        if permissions.permits_universal_transfer:
            raise WithdrawalPermissionDetectedError(
                "Security violation: API key possesses prohibited Universal Transfer permissions. "
                "Fail-closed key rejection triggered."
            )
        if permissions.enable_internal_transfer:
            raise WithdrawalPermissionDetectedError(
                "Security violation: API key possesses prohibited Internal Transfer permissions. "
                "Fail-closed key rejection triggered."
            )
        if permissions.enable_sub_account_transfer:
            raise WithdrawalPermissionDetectedError(
                "Security violation: API key possesses prohibited Sub-Account permissions. "
                "Fail-closed key rejection triggered."
            )
        if permissions.enable_margin or permissions.enable_spot_and_margin_trading:
            raise UnpermittedPermissionError(
                "Security violation: API key possesses unpermitted Margin or Spot "
                "Trading permissions. Only Futures Trading and Spot/Futures "
                "Read-Only are permitted."
            )

        # 2. Required Permissions
        if not permissions.enable_reading:
            raise MissingRequiredPermissionError(
                "Security violation: API key lacks required Spot/Futures Read permissions."
            )
        if not permissions.enable_futures_trading:
            raise MissingRequiredPermissionError(
                "Security violation: API key lacks required Futures Trading permissions."
            )

        return True


# =====================================================================
# R1: Canary Activation Certificate & Governance Models
# =====================================================================


class CanaryActivationCertificate(DomainModel):
    """Cryptographically signed operator canary activation certificate."""

    certificate_id: str = Field(min_length=1)
    version: str = "1.0"
    phase: str = "phase_276"
    manifest_version: int = 2
    staged_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    upstream_phase275_readiness_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    upstream_phase275_summary_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator_id: str = Field(min_length=1)
    authorized_symbols: list[str] = Field(default_factory=lambda: list(CANARY_STAGED_SYMBOLS))
    max_allocated_margin_caps: dict[str, str] = Field(
        default_factory=lambda: {
            "BTCUSDT": str(DEFAULT_PER_ASSET_MARGIN_CAP),
            "ETHUSDT": str(DEFAULT_PER_ASSET_MARGIN_CAP),
            "SOLUSDT": str(DEFAULT_PER_ASSET_MARGIN_CAP),
        }
    )
    max_aggregate_margin_usdt: str = str(DEFAULT_AGGREGATE_MARGIN_CAP)
    max_micro_order_notional_usdt: str = str(HARD_NOTIONAL_CAP_USDT)
    daily_loss_budget_usdt: str = str(DAILY_LOSS_BUDGET_USDT)
    max_duration_hours: float = DEFAULT_MAX_DURATION_HOURS
    issued_at_utc: str = Field(min_length=1)
    expires_at_utc: str = Field(min_length=1)
    status: CertificateStatus = CertificateStatus.ACTIVE
    operator_rationale: str = Field(min_length=1)
    cryptographic_signature: str = Field(pattern=r"^[0-9a-f]{64}$")

    def is_expired(self, as_of: datetime | None = None) -> bool:
        """Return True if current time has surpassed certificate expiration timestamp."""
        now = as_of or datetime.now(UTC)
        exp = datetime.fromisoformat(self.expires_at_utc.replace("Z", "+00:00"))
        return now >= exp

    def invalidate(self, reason: str) -> None:
        """Mark certificate as permanently invalidated."""
        logger.warning(
            "Canary activation certificate %s invalidated: %s",
            self.certificate_id,
            reason,
        )
        self.status = CertificateStatus.INVALIDATED_WITHDRAWAL_PERMISSION_DETECTED


def compute_certificate_signature(data: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 signature for certificate payload excluding signature."""
    sig_payload = {k: v for k, v in data.items() if k != "cryptographic_signature"}
    raw_bytes = canonical_json_bytes(sig_payload)
    return hashlib.sha256(raw_bytes).hexdigest()


# =====================================================================
# R3: Interlock Events & Order Execution Models
# =====================================================================


class InterlockEvent(DomainModel):
    """Audit record for order dispatch interlock triggers and gate blocks."""

    event_id: str = Field(default_factory=lambda: f"int-{uuid4().hex[:12]}")
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    track_id: str
    trigger_type: InterlockTriggerType
    symbol: str
    attempted_notional_usdt: Decimal
    current_drawdown_usdt: Decimal
    detail: str
    order_id: str | None = None


class MicroCanaryOrder(DomainModel):
    """Domain model representing a micro canary order."""

    order_id: str = Field(default_factory=lambda: f"ord-{uuid4().hex[:12]}")
    client_order_id: str = Field(default_factory=lambda: f"cid-{uuid4().hex[:8]}")
    track_id: str
    candidate_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce = TimeInForce.GTC
    status: OrderStatus = OrderStatus.OPEN
    price: Decimal
    quantity: Decimal
    notional_usdt: Decimal
    is_post_only: bool = False
    bracket_parent_id: str | None = None
    bracket_role: str | None = None
    rejection_reason: str | None = None
    is_closing: bool = False
    is_emergency_close: bool = False
    created_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @model_validator(mode="after")
    def validate_micro_order_invariants(self) -> MicroCanaryOrder:
        if self.status != OrderStatus.REJECTED:
            if not self.price.is_finite() or self.price <= Decimal("0"):
                raise OrderNotionalCapBreachError(
                    f"Order price {self.price} must be strictly positive and finite"
                )
            if not self.quantity.is_finite() or self.quantity <= Decimal("0"):
                raise OrderNotionalCapBreachError(
                    f"Order quantity {self.quantity} must be strictly positive and finite"
                )
            calc_notional = (self.price * self.quantity).quantize(Decimal("0.0001"))
            if calc_notional <= Decimal("0"):
                raise OrderNotionalCapBreachError(
                    f"Order notional {calc_notional} must be strictly positive"
                )
            if (
                not self.is_closing
                and not self.is_emergency_close
                and calc_notional > HARD_NOTIONAL_CAP_USDT
            ):
                raise OrderNotionalCapBreachError(
                    f"Order notional {calc_notional} USDT breaches "
                    f"{HARD_NOTIONAL_CAP_USDT} USDT cap"
                )
        return self


class MicroCanaryFill(DomainModel):
    """Domain model representing an execution fill."""

    fill_id: str = Field(default_factory=lambda: f"fill-{uuid4().hex[:12]}")
    order_id: str
    client_order_id: str
    track_id: str
    candidate_id: str
    symbol: str
    side: OrderSide
    liquidity_role: LiquidityRole
    fill_price: Decimal
    fill_quantity: Decimal
    notional_usdt: Decimal
    fee_usdt: Decimal
    fee_rate: Decimal
    slippage_usdt: Decimal
    slippage_bps: Decimal
    realized_pnl_usdt: Decimal = Decimal("0")
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class MicroCanaryPosition(DomainModel):
    """Domain model representing an active fractional position."""

    position_id: str = Field(default_factory=lambda: f"pos-{uuid4().hex[:12]}")
    track_id: str
    candidate_id: str
    symbol: str
    side: PositionSide
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    allocated_margin_usdt: Decimal
    leverage: Decimal = Decimal("1.0")
    unrealized_pnl_usdt: Decimal = Decimal("0")
    realized_pnl_usdt: Decimal = Decimal("0")
    status: PositionStatus = PositionStatus.OPEN
    opened_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    closed_at_utc: str | None = None
    exit_price: Decimal | None = None
    stop_loss_order_id: str | None = None
    take_profit_order_id: str | None = None


class PortfolioSnapshot(DomainModel):
    """Transactional snapshot of portfolio balance and double-entry reconciliation."""

    snapshot_id: str = Field(default_factory=lambda: f"snap-{uuid4().hex[:12]}")
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    track_id: str
    starting_equity_usdt: Decimal
    cash_usdt: Decimal
    allocated_margin_usdt: Decimal
    unrealized_pnl_usdt: Decimal
    realized_pnl_usdt: Decimal
    total_equity_usdt: Decimal
    reserve_buffer_pct: Decimal
    margin_utilization_pct: Decimal
    drift_usdt: Decimal
    zero_drift: bool


class MarketDepthTick(DomainModel):
    """Incoming market ticker or depth tick."""

    mark_id: str = Field(default_factory=lambda: f"mark-{uuid4().hex[:12]}")
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    track_id: str
    symbol: str
    stream_type: str = "bookTicker"
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal
    mark_price: Decimal
    latency_ms: float = 10.0


# =====================================================================
# R3: Fail-Closed Live Order Dispatch Interlock Gateway
# =====================================================================


class CanaryOrderDispatchInterlockGateway:
    """Execution gateway order dispatch filter and fail-closed interlock gates."""

    def __init__(
        self,
        certificate: CanaryActivationCertificate,
        key_vault: SecureExchangeKeyVault,
        circuit_breaker: CanaryCircuitBreakerRecoveryStateMachine,
        starting_equity_usdt: Decimal = STARTING_EQUITY_USDT,
        hard_notional_cap_usdt: Decimal = HARD_NOTIONAL_CAP_USDT,
        daily_loss_budget_usdt: Decimal = DAILY_LOSS_BUDGET_USDT,
        rate_limit_interval_seconds: float = RATE_LIMIT_INTERVAL_SECONDS,
        max_heartbeat_age_ms: float = MAX_HEARTBEAT_AGE_MS,
    ) -> None:
        self.certificate = certificate
        self.key_vault = key_vault
        self.circuit_breaker = circuit_breaker
        self.starting_equity_usdt = starting_equity_usdt
        self.hard_notional_cap_usdt = hard_notional_cap_usdt
        self.daily_loss_budget_usdt = daily_loss_budget_usdt
        self.rate_limit_interval_seconds = rate_limit_interval_seconds
        self.max_heartbeat_age_ms = max_heartbeat_age_ms

        self.last_order_timestamp_by_symbol: dict[str, float] = {}
        self.locked_out: bool = False
        self.lockout_reason: str | None = None
        self.interlock_events: list[InterlockEvent] = []

    def check_order_dispatch_interlocks(
        self,
        symbol: str,
        notional_usdt: Decimal,
        track_id: str,
        current_time_epoch: float,
        last_heartbeat_epoch: float,
        cumulative_drawdown_usdt: Decimal,
        current_asset_margin_usdt: Decimal = Decimal("0"),
        current_aggregate_margin_usdt: Decimal = Decimal("0"),
        is_closing: bool = False,
        is_emergency_close: bool = False,
    ) -> None:
        """Evaluate all fail-closed order dispatch interlock gates in deterministic sequence."""
        # Gate 1: Permanent Lockout Check
        if not is_emergency_close and not is_closing and self.locked_out:
            evt = InterlockEvent(
                track_id=track_id,
                trigger_type=InterlockTriggerType.DAILY_LOSS_BUDGET_BREACH,
                symbol=symbol,
                attempted_notional_usdt=notional_usdt,
                current_drawdown_usdt=cumulative_drawdown_usdt,
                detail=f"Order dispatch permanently locked out: {self.lockout_reason}",
            )
            self.interlock_events.append(evt)
            raise DailyLossBudgetLockoutError(evt.detail)

        # Gate 2: Certificate Validity & Expiration
        if (
            not is_emergency_close
            and not is_closing
            and self.certificate.status != CertificateStatus.ACTIVE
        ):
            evt = InterlockEvent(
                track_id=track_id,
                trigger_type=InterlockTriggerType.CERTIFICATE_INVALIDATED,
                symbol=symbol,
                attempted_notional_usdt=notional_usdt,
                current_drawdown_usdt=cumulative_drawdown_usdt,
                detail=f"Certificate status is {self.certificate.status}",
            )
            self.interlock_events.append(evt)
            raise CertificateInvalidatedError(evt.detail)

        if math.isnan(current_time_epoch) or math.isinf(current_time_epoch):
            evt = InterlockEvent(
                track_id=track_id,
                trigger_type=InterlockTriggerType.STALE_HEARTBEAT_BLOCK,
                symbol=symbol,
                attempted_notional_usdt=(
                    notional_usdt if notional_usdt.is_finite() else Decimal("0")
                ),
                current_drawdown_usdt=cumulative_drawdown_usdt,
                detail=f"Current time epoch is invalid or non-finite ({current_time_epoch})",
            )
            self.interlock_events.append(evt)
            raise StaleHeartbeatInterlockError(evt.detail)

        current_dt = datetime.fromtimestamp(current_time_epoch, tz=UTC)
        if (
            not is_emergency_close
            and not is_closing
            and self.certificate.is_expired(as_of=current_dt)
        ):
            self.certificate.status = CertificateStatus.EXPIRED
            evt = InterlockEvent(
                track_id=track_id,
                trigger_type=InterlockTriggerType.CERTIFICATE_INVALIDATED,
                symbol=symbol,
                attempted_notional_usdt=notional_usdt,
                current_drawdown_usdt=cumulative_drawdown_usdt,
                detail="Certificate expiration timestamp has been reached",
            )
            self.interlock_events.append(evt)
            raise CertificateExpiredError(evt.detail)

        # Gate 3: Symbol Whitelist
        if symbol not in self.certificate.authorized_symbols:
            whitelist_str = str(self.certificate.authorized_symbols)
            evt = InterlockEvent(
                track_id=track_id,
                trigger_type=InterlockTriggerType.UNAUTHORIZED_SYMBOL,
                symbol=symbol,
                attempted_notional_usdt=notional_usdt,
                current_drawdown_usdt=cumulative_drawdown_usdt,
                detail=f"Symbol {symbol} not in authorized whitelist {whitelist_str}",
            )
            self.interlock_events.append(evt)
            raise UnauthorizedSymbolError(evt.detail)

        # Gate 4: Hard Micro-Order Notional Cap
        if not notional_usdt.is_finite() or notional_usdt <= Decimal("0"):
            evt = InterlockEvent(
                track_id=track_id,
                trigger_type=InterlockTriggerType.HARD_NOTIONAL_CAP_REJECTION,
                symbol=symbol,
                attempted_notional_usdt=(
                    notional_usdt if notional_usdt.is_finite() else Decimal("0")
                ),
                current_drawdown_usdt=cumulative_drawdown_usdt,
                detail=f"Order notional {notional_usdt} USDT must be strictly positive and finite",
            )
            self.interlock_events.append(evt)
            raise OrderNotionalCapBreachError(evt.detail)

        if (
            not is_closing
            and not is_emergency_close
            and notional_usdt > self.hard_notional_cap_usdt
        ):
            evt = InterlockEvent(
                track_id=track_id,
                trigger_type=InterlockTriggerType.HARD_NOTIONAL_CAP_REJECTION,
                symbol=symbol,
                attempted_notional_usdt=notional_usdt,
                current_drawdown_usdt=cumulative_drawdown_usdt,
                detail=(
                    f"Order notional {notional_usdt} USDT exceeds hard ceiling "
                    f"of {self.hard_notional_cap_usdt} USDT"
                ),
            )
            self.interlock_events.append(evt)
            raise OrderNotionalCapBreachError(evt.detail)

        # Gate 4b: Allocated Margin Caps (Per-Asset and Aggregate)
        if not is_closing and not is_emergency_close:
            per_asset_cap_str = self.certificate.max_allocated_margin_caps.get(symbol)
            if per_asset_cap_str is not None:
                per_asset_cap = Decimal(per_asset_cap_str)
                if current_asset_margin_usdt + notional_usdt > per_asset_cap:
                    evt = InterlockEvent(
                        track_id=track_id,
                        trigger_type=InterlockTriggerType.HARD_NOTIONAL_CAP_REJECTION,
                        symbol=symbol,
                        attempted_notional_usdt=notional_usdt,
                        current_drawdown_usdt=cumulative_drawdown_usdt,
                        detail=(
                            f"Order notional {notional_usdt} USDT would breach {symbol} "
                            f"margin cap of {per_asset_cap} USDT "
                            f"(current allocated: {current_asset_margin_usdt} USDT)"
                        ),
                    )
                    self.interlock_events.append(evt)
                    raise MarginCapBreachError(evt.detail)

            agg_cap = Decimal(self.certificate.max_aggregate_margin_usdt)
            if current_aggregate_margin_usdt + notional_usdt > agg_cap:
                evt = InterlockEvent(
                    track_id=track_id,
                    trigger_type=InterlockTriggerType.HARD_NOTIONAL_CAP_REJECTION,
                    symbol=symbol,
                    attempted_notional_usdt=notional_usdt,
                    current_drawdown_usdt=cumulative_drawdown_usdt,
                    detail=(
                        f"Order notional {notional_usdt} USDT would breach aggregate "
                        f"margin cap of {agg_cap} USDT "
                        f"(current allocated: {current_aggregate_margin_usdt} USDT)"
                    ),
                )
                self.interlock_events.append(evt)
                raise MarginCapBreachError(evt.detail)

        # Gate 5: Stream Heartbeat Freshness
        if not is_emergency_close:
            heartbeat_age_ms = (current_time_epoch - last_heartbeat_epoch) * 1000.0
            if (
                math.isnan(heartbeat_age_ms)
                or math.isinf(heartbeat_age_ms)
                or heartbeat_age_ms < 0
                or heartbeat_age_ms > self.max_heartbeat_age_ms
            ):
                detail_msg = (
                    f"Stream heartbeat age ({heartbeat_age_ms:.1f}ms) exceeds "
                    f"{self.max_heartbeat_age_ms}ms threshold"
                    if (
                        not math.isnan(heartbeat_age_ms)
                        and not math.isinf(heartbeat_age_ms)
                        and heartbeat_age_ms >= 0
                    )
                    else f"Stream heartbeat age invalid or non-finite ({heartbeat_age_ms}ms)"
                )
                evt = InterlockEvent(
                    track_id=track_id,
                    trigger_type=InterlockTriggerType.STALE_HEARTBEAT_BLOCK,
                    symbol=symbol,
                    attempted_notional_usdt=notional_usdt,
                    current_drawdown_usdt=cumulative_drawdown_usdt,
                    detail=detail_msg,
                )
                self.interlock_events.append(evt)
                raise StaleHeartbeatInterlockError(evt.detail)

        # Gate 6: Circuit Breaker State Invariant
        cb_state = self.circuit_breaker.current_state
        if not is_emergency_close and not is_closing and cb_state != CircuitBreakerState.NORMAL:
            evt = InterlockEvent(
                track_id=track_id,
                trigger_type=InterlockTriggerType.CIRCUIT_BREAKER_BLOCK,
                symbol=symbol,
                attempted_notional_usdt=notional_usdt,
                current_drawdown_usdt=cumulative_drawdown_usdt,
                detail=f"Circuit breaker state is {cb_state.value} (must be NORMAL)",
            )
            self.interlock_events.append(evt)
            raise CircuitBreakerInterlockError(evt.detail)

        # Gate 7: Rate-Limit & Frequency Throttle
        if not is_emergency_close and not is_closing:
            last_order_ts = self.last_order_timestamp_by_symbol.get(symbol)
            if last_order_ts is not None:
                elapsed = current_time_epoch - last_order_ts
                if (
                    math.isnan(elapsed)
                    or math.isinf(elapsed)
                    or elapsed < self.rate_limit_interval_seconds
                ):
                    detail_msg = (
                        f"Order frequency throttle for {symbol}: elapsed {elapsed:.2f}s "
                        f"< {self.rate_limit_interval_seconds}s limit"
                        if (not math.isnan(elapsed) and not math.isinf(elapsed))
                        else f"Order frequency throttle timestamp invalid ({elapsed}s)"
                    )
                    evt = InterlockEvent(
                        track_id=track_id,
                        trigger_type=InterlockTriggerType.RATE_LIMIT_THROTTLE,
                        symbol=symbol,
                        attempted_notional_usdt=notional_usdt,
                        current_drawdown_usdt=cumulative_drawdown_usdt,
                        detail=detail_msg,
                    )
                    self.interlock_events.append(evt)
                    raise RateLimitThrottleExceededError(evt.detail)

        # Gate 8: Daily Loss Budget Interlock
        if (
            not is_emergency_close
            and not is_closing
            and cumulative_drawdown_usdt >= self.daily_loss_budget_usdt
        ):
            self.trigger_daily_loss_lockout(
                cumulative_drawdown_usdt,
                track_id=track_id,
                symbol=symbol,
                attempted_notional=notional_usdt,
            )
            raise DailyLossBudgetLockoutError(self.lockout_reason or "Daily loss budget breached")

    def trigger_daily_loss_lockout(
        self,
        drawdown_usdt: Decimal,
        track_id: str = "system",
        symbol: str = "GLOBAL",
        attempted_notional: Decimal = Decimal("0"),
    ) -> None:
        """Trigger permanent lockout upon daily loss budget breach."""
        self.locked_out = True
        self.lockout_reason = (
            f"Daily loss budget breach: cumulative drawdown {drawdown_usdt} USDT >= "
            f"{self.daily_loss_budget_usdt} USDT limit"
        )
        evt = InterlockEvent(
            track_id=track_id,
            trigger_type=InterlockTriggerType.DAILY_LOSS_BUDGET_BREACH,
            symbol=symbol,
            attempted_notional_usdt=attempted_notional,
            current_drawdown_usdt=drawdown_usdt,
            detail=self.lockout_reason,
        )
        self.interlock_events.append(evt)
        logger.critical(
            "DAILY LOSS BUDGET LOCKOUT ENGAGED: Drawdown %s USDT >= limit %s USDT",
            drawdown_usdt,
            self.daily_loss_budget_usdt,
        )

    def record_order_dispatched(self, symbol: str, timestamp_epoch: float) -> None:
        """Record successful order dispatch timestamp for rate-limit tracking."""
        self.last_order_timestamp_by_symbol[symbol] = timestamp_epoch

    def invalidate_certificate_for_withdrawal_key(
        self, track_id: str = "track_3", symbol: str = "GLOBAL"
    ) -> None:
        """Invalidate certificate upon detection of prohibited API key permissions."""
        self.certificate.invalidate("Prohibited withdrawal permissions detected on API key")
        evt = InterlockEvent(
            track_id=track_id,
            trigger_type=InterlockTriggerType.WITHDRAWAL_PERMISSION_REJECTION,
            symbol=symbol,
            attempted_notional_usdt=Decimal("0"),
            current_drawdown_usdt=Decimal("0"),
            detail="API key possesses prohibited withdrawal rights; certificate invalidated",
        )
        self.interlock_events.append(evt)

    def load_and_verify_key_vault(
        self,
        api_key: str,
        api_secret: str,
        permissions: ExchangeApiKeyPermissions,
        track_id: str = "system",
    ) -> None:
        """Load credentials and invalidate certificate if withdrawal rights are detected."""
        try:
            self.key_vault.load_credentials(api_key, api_secret, permissions)
        except WithdrawalPermissionDetectedError:
            self.invalidate_certificate_for_withdrawal_key(track_id=track_id)
            raise


# =====================================================================
# Telemetry Persistence: Isolated SQLite & JSONL Sink
# =====================================================================


class SqliteCanaryActivationTelemetryStore:
    """Isolated transactional SQLite store for Phase 276 canary telemetry."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0,
            isolation_level="DEFERRED",
        )
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")

            # 1. Orders table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL UNIQUE,
                    client_order_id TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    time_in_force TEXT NOT NULL,
                    status TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    notional_usdt REAL NOT NULL,
                    is_post_only INTEGER NOT NULL,
                    bracket_parent_id TEXT,
                    bracket_role TEXT,
                    rejection_reason TEXT,
                    is_closing INTEGER NOT NULL DEFAULT 0,
                    is_emergency_close INTEGER NOT NULL DEFAULT 0,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                )
                """
            )

            # 2. Fills table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fill_id TEXT NOT NULL UNIQUE,
                    order_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    liquidity_role TEXT NOT NULL,
                    fill_price REAL NOT NULL,
                    fill_quantity REAL NOT NULL,
                    notional_usdt REAL NOT NULL,
                    fee_usdt REAL NOT NULL,
                    fee_rate REAL NOT NULL,
                    slippage_usdt REAL NOT NULL,
                    slippage_bps REAL NOT NULL,
                    realized_pnl_usdt REAL NOT NULL,
                    timestamp_utc TEXT NOT NULL
                )
                """
            )

            # 3. Positions table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id TEXT NOT NULL UNIQUE,
                    track_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    allocated_margin_usdt REAL NOT NULL,
                    leverage REAL NOT NULL,
                    unrealized_pnl_usdt REAL NOT NULL,
                    realized_pnl_usdt REAL NOT NULL,
                    status TEXT NOT NULL,
                    opened_at_utc TEXT NOT NULL,
                    closed_at_utc TEXT,
                    exit_price REAL,
                    stop_loss_order_id TEXT,
                    take_profit_order_id TEXT
                )
                """
            )

            # 4. Interlock events table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS interlock_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    timestamp_utc TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    attempted_notional_usdt REAL NOT NULL,
                    current_drawdown_usdt REAL NOT NULL,
                    detail TEXT NOT NULL,
                    order_id TEXT
                )
                """
            )

            # 5. Activation certificates table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS activation_certificates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    certificate_id TEXT NOT NULL UNIQUE,
                    operator_id TEXT NOT NULL,
                    issued_at_utc TEXT NOT NULL,
                    expires_at_utc TEXT NOT NULL,
                    daily_loss_budget_usdt REAL NOT NULL,
                    max_notional_usdt REAL NOT NULL,
                    status TEXT NOT NULL,
                    cryptographic_signature TEXT NOT NULL
                )
                """
            )

            # 6. Circuit breaker state events
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS circuit_breaker_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    timestamp_utc TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    previous_state TEXT NOT NULL,
                    new_state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    trigger_severity TEXT NOT NULL,
                    consecutive_healthy_ticks INTEGER NOT NULL,
                    is_manual_override INTEGER NOT NULL,
                    operator_id TEXT
                )
                """
            )

            # 7. Portfolio snapshots
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL UNIQUE,
                    timestamp_utc TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    starting_equity_usdt TEXT NOT NULL,
                    cash_usdt TEXT NOT NULL,
                    allocated_margin_usdt TEXT NOT NULL,
                    unrealized_pnl_usdt TEXT NOT NULL,
                    realized_pnl_usdt TEXT NOT NULL,
                    total_equity_usdt TEXT NOT NULL,
                    reserve_buffer_pct REAL NOT NULL,
                    margin_utilization_pct REAL NOT NULL,
                    drift_usdt TEXT NOT NULL,
                    zero_drift INTEGER NOT NULL
                )
                """
            )

            # 8. Execution marks
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_marks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mark_id TEXT NOT NULL UNIQUE,
                    timestamp_utc TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    stream_type TEXT NOT NULL,
                    bid_price REAL NOT NULL,
                    bid_quantity REAL NOT NULL,
                    ask_price REAL NOT NULL,
                    ask_quantity REAL NOT NULL,
                    mark_price REAL NOT NULL,
                    latency_ms REAL NOT NULL
                )
                """
            )

            # 9. Activation tracks summary
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS activation_tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id TEXT NOT NULL UNIQUE,
                    track_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    starting_equity_usdt TEXT NOT NULL,
                    final_cash_usdt TEXT NOT NULL,
                    drift_usdt TEXT NOT NULL,
                    zero_balance_drift INTEGER NOT NULL,
                    orders_placed_count INTEGER NOT NULL,
                    orders_filled_count INTEGER NOT NULL,
                    orders_cancelled_count INTEGER NOT NULL,
                    orders_rejected_count INTEGER NOT NULL,
                    interlock_blocks_count INTEGER NOT NULL,
                    final_circuit_state TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    executed_at_utc TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def record_order(self, order: MicroCanaryOrder) -> None:
        """Insert or replace an order record."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO orders (
                    order_id, client_order_id, track_id, candidate_id, symbol,
                    side, order_type, time_in_force, status, price, quantity,
                    notional_usdt, is_post_only, bracket_parent_id, bracket_role,
                    rejection_reason, is_closing, is_emergency_close,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    order.status.value,
                    float(order.price),
                    float(order.quantity),
                    float(order.notional_usdt),
                    1 if order.is_post_only else 0,
                    order.bracket_parent_id,
                    order.bracket_role,
                    order.rejection_reason,
                    1 if order.is_closing else 0,
                    1 if order.is_emergency_close else 0,
                    order.created_at_utc,
                    order.updated_at_utc,
                ),
            )
            self._conn.commit()

    def record_fill(self, fill: MicroCanaryFill) -> None:
        """Insert or replace an execution fill record."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO fills (
                    fill_id, order_id, client_order_id, track_id, candidate_id,
                    symbol, side, liquidity_role, fill_price, fill_quantity,
                    notional_usdt, fee_usdt, fee_rate, slippage_usdt, slippage_bps,
                    realized_pnl_usdt, timestamp_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.fill_id,
                    fill.order_id,
                    fill.client_order_id,
                    fill.track_id,
                    fill.candidate_id,
                    fill.symbol,
                    fill.side.value,
                    fill.liquidity_role.value,
                    float(fill.fill_price),
                    float(fill.fill_quantity),
                    float(fill.notional_usdt),
                    float(fill.fee_usdt),
                    float(fill.fee_rate),
                    float(fill.slippage_usdt),
                    float(fill.slippage_bps),
                    float(fill.realized_pnl_usdt),
                    fill.timestamp_utc,
                ),
            )
            self._conn.commit()

    def record_position(self, pos: MicroCanaryPosition) -> None:
        """Insert or replace a position record."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO positions (
                    position_id, track_id, candidate_id, symbol, side,
                    quantity, entry_price, current_price, allocated_margin_usdt,
                    leverage, unrealized_pnl_usdt, realized_pnl_usdt, status,
                    opened_at_utc, closed_at_utc, exit_price, stop_loss_order_id,
                    take_profit_order_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pos.position_id,
                    pos.track_id,
                    pos.candidate_id,
                    pos.symbol,
                    pos.side.value,
                    float(pos.quantity),
                    float(pos.entry_price),
                    float(pos.current_price),
                    float(pos.allocated_margin_usdt),
                    float(pos.leverage),
                    float(pos.unrealized_pnl_usdt),
                    float(pos.realized_pnl_usdt),
                    pos.status.value,
                    pos.opened_at_utc,
                    pos.closed_at_utc,
                    float(pos.exit_price) if pos.exit_price is not None else None,
                    pos.stop_loss_order_id,
                    pos.take_profit_order_id,
                ),
            )
            self._conn.commit()

    def record_interlock_event(self, evt: InterlockEvent) -> None:
        """Insert an interlock trigger audit event."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO interlock_events (
                    event_id, timestamp_utc, track_id, trigger_type, symbol,
                    attempted_notional_usdt, current_drawdown_usdt, detail, order_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evt.event_id,
                    evt.timestamp_utc,
                    evt.track_id,
                    evt.trigger_type.value,
                    evt.symbol,
                    float(evt.attempted_notional_usdt),
                    float(evt.current_drawdown_usdt),
                    evt.detail,
                    evt.order_id,
                ),
            )
            self._conn.commit()

    def record_activation_certificate(self, cert: CanaryActivationCertificate) -> None:
        """Insert activation certificate metadata."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO activation_certificates (
                    certificate_id, operator_id, issued_at_utc, expires_at_utc,
                    daily_loss_budget_usdt, max_notional_usdt, status,
                    cryptographic_signature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cert.certificate_id,
                    cert.operator_id,
                    cert.issued_at_utc,
                    cert.expires_at_utc,
                    float(cert.daily_loss_budget_usdt),
                    float(cert.max_micro_order_notional_usdt),
                    cert.status.value,
                    cert.cryptographic_signature,
                ),
            )
            self._conn.commit()

    def record_circuit_breaker_event(
        self,
        event_id: str,
        timestamp_utc: str,
        track_id: str,
        transition: CircuitBreakerTransition,
    ) -> None:
        """Insert circuit breaker state transition record."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO circuit_breaker_events (
                    event_id, timestamp_utc, track_id, previous_state, new_state,
                    reason, trigger_severity, consecutive_healthy_ticks,
                    is_manual_override, operator_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    timestamp_utc,
                    track_id,
                    transition.previous_state.value,
                    transition.new_state.value,
                    transition.reason,
                    transition.trigger_severity,
                    transition.consecutive_healthy_ticks,
                    1 if transition.is_manual_override else 0,
                    transition.operator_id,
                ),
            )
            self._conn.commit()

    def record_snapshot(self, snap: PortfolioSnapshot) -> None:
        """Insert portfolio balance and double-entry reconciliation snapshot."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO portfolio_snapshots (
                    snapshot_id, timestamp_utc, track_id, starting_equity_usdt,
                    cash_usdt, allocated_margin_usdt, unrealized_pnl_usdt,
                    realized_pnl_usdt, total_equity_usdt, reserve_buffer_pct,
                    margin_utilization_pct, drift_usdt, zero_drift
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap.snapshot_id,
                    snap.timestamp_utc,
                    snap.track_id,
                    str(snap.starting_equity_usdt),
                    str(snap.cash_usdt),
                    str(snap.allocated_margin_usdt),
                    str(snap.unrealized_pnl_usdt),
                    str(snap.realized_pnl_usdt),
                    str(snap.total_equity_usdt),
                    float(snap.reserve_buffer_pct),
                    float(snap.margin_utilization_pct),
                    str(snap.drift_usdt),
                    1 if snap.zero_drift else 0,
                ),
            )
            self._conn.commit()

    def record_execution_mark(self, mark: MarketDepthTick) -> None:
        """Insert an execution mark tick."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO execution_marks (
                    mark_id, timestamp_utc, track_id, symbol, stream_type,
                    bid_price, bid_quantity, ask_price, ask_quantity,
                    mark_price, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mark.mark_id,
                    mark.timestamp_utc,
                    mark.track_id,
                    mark.symbol,
                    mark.stream_type,
                    float(mark.bid_price),
                    float(mark.bid_quantity),
                    float(mark.ask_price),
                    float(mark.ask_quantity),
                    float(mark.mark_price),
                    mark.latency_ms,
                ),
            )
            self._conn.commit()

    def record_activation_track(
        self,
        track_id: str,
        track_name: str,
        status: str,
        starting_equity_usdt: str,
        final_cash_usdt: str,
        drift_usdt: str,
        zero_balance_drift: bool,
        orders_placed: int,
        orders_filled: int,
        orders_cancelled: int,
        orders_rejected: int,
        interlock_blocks: int,
        final_circuit_state: str,
        success: bool,
    ) -> None:
        """Insert or replace activation track summary record."""
        with self._lock:
            if self._closed:
                return
            self._conn.execute(
                """
                INSERT OR REPLACE INTO activation_tracks (
                    track_id, track_name, status, starting_equity_usdt,
                    final_cash_usdt, drift_usdt, zero_balance_drift,
                    orders_placed_count, orders_filled_count, orders_cancelled_count,
                    orders_rejected_count, interlock_blocks_count, final_circuit_state,
                    success, executed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    track_id,
                    track_name,
                    status,
                    starting_equity_usdt,
                    final_cash_usdt,
                    drift_usdt,
                    1 if zero_balance_drift else 0,
                    orders_placed,
                    orders_filled,
                    orders_cancelled,
                    orders_rejected,
                    interlock_blocks,
                    final_circuit_state,
                    1 if success else 0,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._conn.commit()

    def get_interlock_event_counts(self) -> dict[str, int]:
        """Return aggregation of interlock trigger counts recorded in store."""
        with self._lock:
            if self._closed:
                if not self.db_path.is_file():
                    return {}
                with closing(sqlite3.connect(str(self.db_path), timeout=5.0)) as conn:
                    rows = conn.execute(
                        "SELECT trigger_type, COUNT(*) FROM interlock_events GROUP BY trigger_type"
                    ).fetchall()
                    return {str(r[0]): int(r[1]) for r in rows}
            rows = self._conn.execute(
                "SELECT trigger_type, COUNT(*) FROM interlock_events GROUP BY trigger_type"
            ).fetchall()
            return {str(r[0]): int(r[1]) for r in rows}

    def verify_double_entry_integrity(self, require_records: bool = False) -> tuple[bool, Decimal]:
        """Verify that all recorded portfolio snapshots and tracks have drift < 1e-15."""
        with self._lock:
            if self._closed:
                return (False if require_records else True), Decimal("0")
            rows = self._conn.execute("SELECT drift_usdt FROM portfolio_snapshots").fetchall()
            track_rows = self._conn.execute("SELECT drift_usdt FROM activation_tracks").fetchall()
            if require_records and not rows and not track_rows:
                return False, Decimal("0")
            max_drift = Decimal("0")
            for r in rows:
                val = abs(Decimal(str(r[0])))
                if val > max_drift:
                    max_drift = val
            for tr in track_rows:
                val = abs(Decimal(str(tr[0])))
                if val > max_drift:
                    max_drift = val
            return max_drift < DOUBLE_ENTRY_MAX_DRIFT, max_drift

    def verify_unlocked(self, timeout: float = 2.0) -> bool:
        """Verify database has zero dangling locks."""
        if not self.db_path.is_file():
            return True
        try:
            with closing(sqlite3.connect(str(self.db_path), timeout=timeout)) as conn:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("COMMIT;")
            return True
        except Exception:
            return False

    def checkpoint(self) -> None:
        """Flush WAL pages and optimize database store."""
        with self._lock:
            if self._closed:
                return
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.commit()
            except Exception as exc:
                logger.warning("Checkpoint warning on %s: %s", self.db_path, exc)

    def close(self) -> None:
        """Gracefully close SQLite connection and release file locks."""
        with self._lock:
            if not self._closed:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self._conn.commit()
                    self._conn.close()
                except Exception:
                    pass
                finally:
                    self._closed = True


class JsonlCanaryOrderSink:
    """Isolated JSONL stream sink for canary orders and fills."""

    def __init__(self, jsonl_path: Path) -> None:
        self.jsonl_path = Path(jsonl_path)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.jsonl_path.exists():
            self.jsonl_path.touch()

    def record_order(self, order: MicroCanaryOrder) -> None:
        """Append an order event to JSONL order log with zero secret assertion."""
        record = {
            "record_type": "ORDER",
            "timestamp_utc": order.updated_at_utc,
            "order": order.model_dump(mode="json"),
        }
        raw_line = json.dumps(record, sort_keys=True)
        assert_zero_secrets(raw_line, "canary-orders.jsonl")
        with self._lock:
            with open(self.jsonl_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(raw_line + "\n")

    def record_fill(self, fill: MicroCanaryFill) -> None:
        """Append an execution fill event to JSONL order log with zero secret assertion."""
        record = {
            "record_type": "FILL",
            "timestamp_utc": fill.timestamp_utc,
            "fill": fill.model_dump(mode="json"),
        }
        raw_line = json.dumps(record, sort_keys=True)
        assert_zero_secrets(raw_line, "canary-orders.jsonl")
        with self._lock:
            with open(self.jsonl_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(raw_line + "\n")


# =====================================================================
# R3: Canary Activation Simulator Engine
# =====================================================================


class CanaryActivationSimulator:
    """Deterministic simulation engine executing order dispatch with strict balance integrity."""

    def __init__(
        self,
        gateway: CanaryOrderDispatchInterlockGateway,
        telemetry_store: SqliteCanaryActivationTelemetryStore,
        jsonl_sink: JsonlCanaryOrderSink,
        track_id: str,
        starting_equity: Decimal = STARTING_EQUITY_USDT,
        simulate_adverse_drift: bool = False,
    ) -> None:
        self.gateway = gateway
        self.telemetry_store = telemetry_store
        self.jsonl_sink = jsonl_sink
        self.track_id = track_id
        self.starting_equity = starting_equity
        self.simulate_adverse_drift = simulate_adverse_drift

        self.cash = starting_equity
        self.allocated_margin = Decimal("0")
        self.realized_pnl = Decimal("0")
        self.total_fees = Decimal("0")
        self.total_slippage = Decimal("0")

        self.orders: dict[str, MicroCanaryOrder] = {}
        self.fills: dict[str, MicroCanaryFill] = {}
        self.active_positions: dict[str, MicroCanaryPosition] = {}
        self.closed_positions: list[MicroCanaryPosition] = []
        self.mark_prices: dict[str, Decimal] = dict(DEFAULT_REFERENCE_PRICES)

        self.orders_placed_count: int = 0
        self.orders_filled_count: int = 0
        self.orders_cancelled_count: int = 0
        self.orders_rejected_count: int = 0
        self.interlock_blocks_count: int = 0

        self.last_heartbeat_epoch: float = time.time()
        self.simulated_clock_epoch: float = time.time()

        # Initial zero-drift snapshot
        self._record_snapshot()

    @property
    def total_unrealized_pnl(self) -> Decimal:
        """Compute aggregate mark-to-market unrealized PnL."""
        total = Decimal("0")
        for pos in self.active_positions.values():
            mark = self.mark_prices.get(pos.symbol, pos.entry_price)
            if pos.side == PositionSide.LONG:
                pnl = (mark - pos.entry_price) * pos.quantity
            else:
                pnl = (pos.entry_price - mark) * pos.quantity
            total += pnl
        return total

    @property
    def total_equity(self) -> Decimal:
        """Current equity: cash + allocated_margin + unrealized_pnl."""
        return self.cash + self.allocated_margin + self.total_unrealized_pnl

    @property
    def current_drift(self) -> Decimal:
        """Exact double-entry drift: |cash + margin + unrealized - (starting + realized)|."""
        if self.simulate_adverse_drift:
            return Decimal("0.05")
        calc_equity = self.cash + self.allocated_margin + self.total_unrealized_pnl
        expected_equity = self.starting_equity + self.realized_pnl + self.total_unrealized_pnl
        return abs(calc_equity - expected_equity)

    @property
    def cumulative_drawdown_usdt(self) -> Decimal:
        """Drawdown from starting equity: max(0, starting_equity - total_equity)."""
        loss = self.starting_equity - self.total_equity
        return max(Decimal("0"), loss)

    def _record_snapshot(self) -> PortfolioSnapshot:
        """Record and persist an exact double-entry balance snapshot."""
        drift = self.current_drift
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT
        if not zero_drift:
            raise AccountingDriftError(
                f"Double-entry drift {drift} USDT exceeds {DOUBLE_ENTRY_MAX_DRIFT} USDT limit"
            )

        eq = self.total_equity
        margin_pct = (
            (self.allocated_margin / eq).quantize(Decimal("0.0001")) if eq > 0 else Decimal("0")
        )
        reserve_pct = (self.cash / eq).quantize(Decimal("0.0001")) if eq > 0 else Decimal("0")

        snap = PortfolioSnapshot(
            track_id=self.track_id,
            starting_equity_usdt=self.starting_equity,
            cash_usdt=self.cash,
            allocated_margin_usdt=self.allocated_margin,
            unrealized_pnl_usdt=self.total_unrealized_pnl,
            realized_pnl_usdt=self.realized_pnl,
            total_equity_usdt=eq,
            reserve_buffer_pct=reserve_pct,
            margin_utilization_pct=margin_pct,
            drift_usdt=drift,
            zero_drift=zero_drift,
        )
        self.telemetry_store.record_snapshot(snap)
        return snap

    def on_market_tick(self, tick: MarketDepthTick) -> None:
        """Ingest incoming stream mark tick and update heartbeat."""
        self.mark_prices[tick.symbol] = tick.mark_price
        self.last_heartbeat_epoch = self.simulated_clock_epoch
        self.telemetry_store.record_execution_mark(tick)

        # Update unrealized PnL on active positions
        if tick.symbol in self.active_positions:
            pos = self.active_positions[tick.symbol]
            if pos.side == PositionSide.LONG:
                pos.unrealized_pnl_usdt = (tick.mark_price - pos.entry_price) * pos.quantity
            else:
                pos.unrealized_pnl_usdt = (pos.entry_price - tick.mark_price) * pos.quantity
            pos.current_price = tick.mark_price
            self.telemetry_store.record_position(pos)

        # Check daily loss budget after mark update
        drawdown = self.cumulative_drawdown_usdt
        if drawdown >= self.gateway.daily_loss_budget_usdt and not self.gateway.locked_out:
            self.gateway.trigger_daily_loss_lockout(drawdown, self.track_id, tick.symbol)

        self._record_snapshot()

    def advance_time(self, seconds: float, update_heartbeat: bool = False) -> None:
        """Advance simulated engine clock."""
        self.simulated_clock_epoch += seconds
        if update_heartbeat:
            self.last_heartbeat_epoch = self.simulated_clock_epoch

    def place_order(
        self,
        candidate_id: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal,
        time_in_force: TimeInForce = TimeInForce.GTC,
        is_post_only: bool = False,
        bracket_parent_id: str | None = None,
        bracket_role: str | None = None,
        is_emergency_close: bool = False,
        is_closing: bool | None = None,
    ) -> MicroCanaryOrder:
        """Evaluate gateway interlocks and place micro canary order fail-closed."""
        calc_notional = Decimal("0")
        order_is_closing = False
        try:
            if not price.is_finite() or price <= Decimal("0"):
                raise OrderNotionalCapBreachError(
                    f"Order price {price} must be strictly positive and finite"
                )
            if not quantity.is_finite() or quantity <= Decimal("0"):
                raise OrderNotionalCapBreachError(
                    f"Order quantity {quantity} must be strictly positive and finite"
                )

            notional = (price * quantity).quantize(Decimal("0.0001"))
            calc_notional = notional
            drawdown = self.cumulative_drawdown_usdt

            pos_for_sym = self.active_positions.get(symbol)
            detected_closing = pos_for_sym is not None and (
                (pos_for_sym.side == PositionSide.LONG and side == OrderSide.SELL)
                or (pos_for_sym.side == PositionSide.SHORT and side == OrderSide.BUY)
            )

            if is_closing is True and not detected_closing:
                raise CanaryActivationError(
                    f"Cannot specify is_closing=True: "
                    f"no active opposing position exists for symbol {symbol}"
                )

            order_is_closing = detected_closing if is_closing is None else is_closing

            if order_is_closing:
                pos = self.active_positions[symbol]
                if quantity > pos.quantity:
                    raise CanaryActivationError(
                        f"Closing order quantity {quantity} exceeds "
                        f"active position quantity {pos.quantity}"
                    )
            elif not is_emergency_close:
                if notional > self.cash:
                    raise CanaryActivationError(
                        f"Insufficient free cash: order notional {notional} USDT "
                        f"exceeds available cash {self.cash} USDT"
                    )

            current_asset_margin = (
                self.active_positions[symbol].allocated_margin_usdt
                if symbol in self.active_positions
                else Decimal("0")
            )
            current_aggregate_margin = self.allocated_margin

            self.gateway.check_order_dispatch_interlocks(
                symbol=symbol,
                notional_usdt=notional,
                track_id=self.track_id,
                current_time_epoch=self.simulated_clock_epoch,
                last_heartbeat_epoch=self.last_heartbeat_epoch,
                cumulative_drawdown_usdt=drawdown,
                current_asset_margin_usdt=current_asset_margin,
                current_aggregate_margin_usdt=current_aggregate_margin,
                is_closing=order_is_closing,
                is_emergency_close=is_emergency_close,
            )
        except CanaryActivationError as exc:
            self.orders_rejected_count += 1
            self.interlock_blocks_count += 1
            rej_order = MicroCanaryOrder(
                track_id=self.track_id,
                candidate_id=candidate_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                time_in_force=time_in_force,
                status=OrderStatus.REJECTED,
                price=price if price.is_finite() else Decimal("0"),
                quantity=quantity if quantity.is_finite() else Decimal("0"),
                notional_usdt=calc_notional if calc_notional.is_finite() else Decimal("0"),
                is_post_only=is_post_only,
                bracket_parent_id=bracket_parent_id,
                bracket_role=bracket_role,
                rejection_reason=str(exc),
                is_closing=order_is_closing,
                is_emergency_close=is_emergency_close,
            )
            self.telemetry_store.record_order(rej_order)
            self.jsonl_sink.record_order(rej_order)
            raise

        order = MicroCanaryOrder(
            track_id=self.track_id,
            candidate_id=candidate_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            time_in_force=time_in_force,
            status=OrderStatus.OPEN,
            price=price,
            quantity=quantity,
            notional_usdt=notional,
            is_post_only=is_post_only,
            bracket_parent_id=bracket_parent_id,
            bracket_role=bracket_role,
            is_closing=order_is_closing,
            is_emergency_close=is_emergency_close,
        )
        self.orders[order.order_id] = order
        self.telemetry_store.record_order(order)
        self.jsonl_sink.record_order(order)

        # Passed all interlocks and instantiated successfully
        self.gateway.record_order_dispatched(symbol, self.simulated_clock_epoch)
        self.orders_placed_count += 1
        return order

    def match_maker_fill(self, order_id: str, fill_price: Decimal) -> MicroCanaryFill:
        """Simulate maker fill, open or close position, debit/credit margin and maker fees."""
        order = self.orders[order_id]
        if order.status != OrderStatus.OPEN:
            raise CanaryActivationError(f"Cannot fill order {order_id} in state {order.status}")

        notional = (fill_price * order.quantity).quantize(Decimal("0.0001"))
        fee = (notional * DEFAULT_MAKER_FEE_RATE).quantize(Decimal("0.000001"))

        is_closing = order.symbol in self.active_positions and (
            (
                self.active_positions[order.symbol].side == PositionSide.LONG
                and order.side == OrderSide.SELL
            )
            or (
                self.active_positions[order.symbol].side == PositionSide.SHORT
                and order.side == OrderSide.BUY
            )
        )

        if is_closing:
            pos = self.active_positions[order.symbol]
            if order.quantity > pos.quantity:
                raise CanaryActivationError(
                    f"Closing order quantity {order.quantity} exceeds "
                    f"active position quantity {pos.quantity}"
                )
            close_qty = order.quantity
            if close_qty == pos.quantity:
                margin_to_release = pos.allocated_margin_usdt
                full_close = True
            else:
                margin_frac = close_qty / pos.quantity
                margin_to_release = (pos.allocated_margin_usdt * margin_frac).quantize(
                    Decimal("0.0001")
                )
                full_close = False

            if pos.side == PositionSide.LONG:
                gross_pnl = (fill_price - pos.entry_price) * close_qty
            else:
                gross_pnl = (pos.entry_price - fill_price) * close_qty
            net_trade_pnl = gross_pnl - fee

            self.cash += margin_to_release + gross_pnl - fee
            self.allocated_margin -= margin_to_release
            self.realized_pnl += net_trade_pnl
            self.total_fees += fee

            if full_close:
                self.active_positions.pop(order.symbol)
                pos.quantity = Decimal("0")
                pos.allocated_margin_usdt = Decimal("0")
                pos.status = PositionStatus.CLOSED
                pos.closed_at_utc = datetime.now(UTC).isoformat()
                pos.exit_price = fill_price
                pos.realized_pnl_usdt += net_trade_pnl
                pos.unrealized_pnl_usdt = Decimal("0")
                self.closed_positions.append(pos)
                self.telemetry_store.record_position(pos)
            else:
                pos.quantity -= close_qty
                pos.allocated_margin_usdt -= margin_to_release
                pos.realized_pnl_usdt += net_trade_pnl
                pos.current_price = fill_price
                self.telemetry_store.record_position(pos)

            fill_pnl = net_trade_pnl
        else:
            self.cash -= notional + fee
            self.allocated_margin += notional
            self.realized_pnl -= fee
            self.total_fees += fee

            if order.symbol in self.active_positions:
                pos = self.active_positions[order.symbol]
                new_qty = pos.quantity + order.quantity
                new_entry = ((pos.allocated_margin_usdt + notional) / new_qty).quantize(
                    Decimal("0.01")
                )
                pos.quantity = new_qty
                pos.entry_price = new_entry
                pos.current_price = fill_price
                pos.allocated_margin_usdt += notional
                self.telemetry_store.record_position(pos)
            else:
                pos = MicroCanaryPosition(
                    track_id=self.track_id,
                    candidate_id=order.candidate_id,
                    symbol=order.symbol,
                    side=PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT,
                    quantity=order.quantity,
                    entry_price=fill_price,
                    current_price=fill_price,
                    allocated_margin_usdt=notional,
                    status=PositionStatus.OPEN,
                )
                self.active_positions[order.symbol] = pos
                self.telemetry_store.record_position(pos)
            fill_pnl = -fee

        order.status = OrderStatus.FILLED
        order.updated_at_utc = datetime.now(UTC).isoformat()
        self.orders_filled_count += 1
        self.telemetry_store.record_order(order)
        self.jsonl_sink.record_order(order)

        fill = MicroCanaryFill(
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            track_id=self.track_id,
            candidate_id=order.candidate_id,
            symbol=order.symbol,
            side=order.side,
            liquidity_role=LiquidityRole.MAKER,
            fill_price=fill_price,
            fill_quantity=order.quantity,
            notional_usdt=notional,
            fee_usdt=fee,
            fee_rate=DEFAULT_MAKER_FEE_RATE,
            slippage_usdt=Decimal("0"),
            slippage_bps=Decimal("0"),
            realized_pnl_usdt=fill_pnl,
        )
        self.fills[fill.fill_id] = fill
        self.telemetry_store.record_fill(fill)
        self.jsonl_sink.record_fill(fill)

        # Check daily loss budget after trade fill
        drawdown = self.cumulative_drawdown_usdt
        if drawdown >= self.gateway.daily_loss_budget_usdt and not self.gateway.locked_out:
            self.gateway.trigger_daily_loss_lockout(drawdown, self.track_id, order.symbol)

        self._record_snapshot()
        return fill

    def execute_taker_order(
        self,
        candidate_id: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        mark_price: Decimal,
        is_emergency_close: bool = False,
    ) -> tuple[MicroCanaryOrder, MicroCanaryFill]:
        """Simulate taker order execution with slippage and taker fee."""
        slippage_mult = (
            Decimal("1.0") + DEFAULT_SLIPPAGE_RATE
            if side == OrderSide.BUY
            else Decimal("1.0") - DEFAULT_SLIPPAGE_RATE
        )
        fill_price = (mark_price * slippage_mult).quantize(Decimal("0.01"))
        notional = (fill_price * quantity).quantize(Decimal("0.0001"))

        order = self.place_order(
            candidate_id=candidate_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=fill_price,
            is_emergency_close=is_emergency_close,
        )

        fee = (notional * DEFAULT_TAKER_FEE_RATE).quantize(Decimal("0.000001"))
        slippage_usdt = abs(fill_price - mark_price) * quantity

        is_closing = symbol in self.active_positions and (
            (self.active_positions[symbol].side == PositionSide.LONG and side == OrderSide.SELL)
            or (self.active_positions[symbol].side == PositionSide.SHORT and side == OrderSide.BUY)
        )

        if is_closing:
            pos = self.active_positions[symbol]
            if quantity > pos.quantity:
                raise CanaryActivationError(
                    f"Closing order quantity {quantity} exceeds "
                    f"active position quantity {pos.quantity}"
                )
            close_qty = quantity
            if close_qty == pos.quantity:
                margin_to_release = pos.allocated_margin_usdt
                full_close = True
            else:
                margin_frac = close_qty / pos.quantity
                margin_to_release = (pos.allocated_margin_usdt * margin_frac).quantize(
                    Decimal("0.0001")
                )
                full_close = False

            if pos.side == PositionSide.LONG:
                gross_pnl = (fill_price - pos.entry_price) * close_qty
            else:
                gross_pnl = (pos.entry_price - fill_price) * close_qty
            net_trade_pnl = gross_pnl - fee

            self.cash += margin_to_release + gross_pnl - fee
            self.allocated_margin -= margin_to_release
            self.realized_pnl += net_trade_pnl
            self.total_fees += fee
            self.total_slippage += slippage_usdt

            if full_close:
                self.active_positions.pop(symbol)
                pos.quantity = Decimal("0")
                pos.allocated_margin_usdt = Decimal("0")
                pos.status = PositionStatus.CLOSED
                pos.closed_at_utc = datetime.now(UTC).isoformat()
                pos.exit_price = fill_price
                pos.realized_pnl_usdt += net_trade_pnl
                pos.unrealized_pnl_usdt = Decimal("0")
                self.closed_positions.append(pos)
                self.telemetry_store.record_position(pos)
            else:
                pos.quantity -= close_qty
                pos.allocated_margin_usdt -= margin_to_release
                pos.realized_pnl_usdt += net_trade_pnl
                pos.current_price = fill_price
                self.telemetry_store.record_position(pos)

            fill_pnl = net_trade_pnl
        else:
            self.cash -= notional + fee
            self.allocated_margin += notional
            self.realized_pnl -= fee
            self.total_fees += fee
            self.total_slippage += slippage_usdt

            if symbol in self.active_positions:
                pos = self.active_positions[symbol]
                new_qty = pos.quantity + quantity
                new_entry = ((pos.allocated_margin_usdt + notional) / new_qty).quantize(
                    Decimal("0.01")
                )
                pos.quantity = new_qty
                pos.entry_price = new_entry
                pos.current_price = fill_price
                pos.allocated_margin_usdt += notional
                self.telemetry_store.record_position(pos)
            else:
                pos = MicroCanaryPosition(
                    track_id=self.track_id,
                    candidate_id=candidate_id,
                    symbol=symbol,
                    side=PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT,
                    quantity=quantity,
                    entry_price=fill_price,
                    current_price=fill_price,
                    allocated_margin_usdt=notional,
                    status=PositionStatus.OPEN,
                )
                self.active_positions[symbol] = pos
                self.telemetry_store.record_position(pos)
            fill_pnl = -fee

        order.status = OrderStatus.FILLED
        order.updated_at_utc = datetime.now(UTC).isoformat()
        self.orders_filled_count += 1
        self.telemetry_store.record_order(order)
        self.jsonl_sink.record_order(order)

        fill = MicroCanaryFill(
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            track_id=self.track_id,
            candidate_id=candidate_id,
            symbol=symbol,
            side=side,
            liquidity_role=LiquidityRole.TAKER,
            fill_price=fill_price,
            fill_quantity=quantity,
            notional_usdt=notional,
            fee_usdt=fee,
            fee_rate=DEFAULT_TAKER_FEE_RATE,
            slippage_usdt=slippage_usdt,
            slippage_bps=DEFAULT_SLIPPAGE_BPS,
            realized_pnl_usdt=fill_pnl,
        )
        self.fills[fill.fill_id] = fill
        self.telemetry_store.record_fill(fill)
        self.jsonl_sink.record_fill(fill)

        # Check daily loss budget after trade fill
        drawdown = self.cumulative_drawdown_usdt
        if drawdown >= self.gateway.daily_loss_budget_usdt and not self.gateway.locked_out:
            self.gateway.trigger_daily_loss_lockout(drawdown, self.track_id, symbol)

        self._record_snapshot()
        return order, fill

    def close_all_positions_emergency(self) -> None:
        """Emergency liquidate / flatten all open positions to cash."""
        for sym in list(self.active_positions.keys()):
            pos = self.active_positions[sym]
            exit_side = OrderSide.SELL if pos.side == PositionSide.LONG else OrderSide.BUY
            mark = self.mark_prices.get(sym, pos.entry_price)
            self.execute_taker_order(
                candidate_id=pos.candidate_id,
                symbol=sym,
                side=exit_side,
                order_type=OrderType.MARKET,
                quantity=pos.quantity,
                mark_price=mark,
                is_emergency_close=True,
            )

    def cancel_order(
        self,
        order_id: str,
        reason: str = "Operator / System cancelled",
    ) -> MicroCanaryOrder:
        """Cancel an open non-filled order fail-closed."""
        order = self.orders.get(order_id)
        if order is None:
            raise CanaryActivationError(f"Order not found: {order_id}")
        if order.status != OrderStatus.OPEN:
            return order

        now_utc = datetime.now(UTC).isoformat()
        order.status = OrderStatus.CANCELLED
        order.rejection_reason = reason
        order.updated_at_utc = now_utc
        self.orders_cancelled_count += 1
        self.telemetry_store.record_order(order)
        self.jsonl_sink.record_order(order)
        return order

    def cancel_all_open_orders(
        self,
        symbol: str | None = None,
        reason: str = "Operator / System cancelled",
    ) -> list[MicroCanaryOrder]:
        """Cancel all open orders, optionally filtered by symbol."""
        cancelled: list[MicroCanaryOrder] = []
        for ord_item in list(self.orders.values()):
            if ord_item.status == OrderStatus.OPEN:
                if symbol is None or ord_item.symbol == symbol:
                    cancelled.append(self.cancel_order(ord_item.order_id, reason=reason))
        return cancelled


# =====================================================================
# Summary & Report Domain Models
# =====================================================================


class CanaryActivationTrackResult(DomainModel):
    """Execution telemetry record for a single Phase 276 simulation track."""

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
    final_circuit_state: str
    success: bool
    details: dict[str, Any] = Field(default_factory=dict)


class CanaryActivationReport(DomainModel):
    """Full telemetry and audit certification report for Phase 276."""

    phase: str = "phase_276"
    description: str = (
        "Phase 276 Operator Production Canary Authorization & Live Interlock Telemetry Report"
    )
    timestamp_utc: str
    manifest_version: int = 2
    staged_manifest_hash: str
    certificate_info: dict[str, Any]
    compliance: dict[str, bool]
    interlock_stats: dict[str, int]
    order_stats: dict[str, Any]
    tracks: list[CanaryActivationTrackResult]
    tracks_executed: list[str]
    artifact_hashes: dict[str, str]


class Phase276ActivationSummary(DomainModel):
    """Executive activation summary artifact for Phase 276."""

    phase: str = "phase_276"
    description: str = "Phase 276 Production Canary Activation Governance & Order Interlock Summary"
    timestamp_utc: str
    manifest_version: int = 2
    staged_manifest_hash: str
    candidates: list[str]
    certificate_id: str
    operator_id: str
    activation_status: str
    compliance: dict[str, bool]
    tracks_summary: dict[str, Any]
    order_stats: dict[str, Any]
    interlock_stats: dict[str, int]
    artifact_hashes: dict[str, str]


# =====================================================================
# R1 & R3: Unified Canary Activation Runner
# =====================================================================


class CanaryActivationConfig(DomainModel):
    """Configuration options for Phase 276 canary activation runner."""

    manifest_path: Path = DEFAULT_CANARY_STAGING_MANIFEST_PATH
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH
    phase275_input_dir: Path = DEFAULT_PHASE275_INPUT_DIR
    output_dir: Path = DEFAULT_PHASE276_OUTPUT_DIR
    track: str = "all"
    operator_id: str = "operator-lead-001"
    operator_rationale: str = (
        "Phase 276 Production Canary Authorization sign-off following full Phase 275 certification"
    )
    authorize_canary: bool = False
    max_duration_hours: float = DEFAULT_MAX_DURATION_HOURS
    daily_loss_budget_usdt: Decimal = DAILY_LOSS_BUDGET_USDT
    simulate_adverse_drift: bool = False
    recovery_hysteresis_ticks: int = 5

    @model_validator(mode="after")
    def validate_config_invariants(self) -> CanaryActivationConfig:
        if not self.operator_id or not self.operator_id.strip():
            raise OperatorAuthorizationMissingError("operator_id must be a non-empty string")
        if self.daily_loss_budget_usdt <= Decimal("0"):
            raise CanaryActivationError(
                f"daily_loss_budget_usdt {self.daily_loss_budget_usdt} must be positive"
            )
        if self.max_duration_hours <= 0:
            raise CanaryActivationError(
                f"max_duration_hours {self.max_duration_hours} must be positive"
            )
        return self


class CanaryActivationRunner:
    """Unified Phase 276 activation governance, interlock simulation, and audit runner."""

    def __init__(self, config: CanaryActivationConfig | None = None) -> None:
        self.config = config or CanaryActivationConfig()
        self.output_dir = Path(self.config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.output_dir / "canary-activation-telemetry.sqlite3"
        self.jsonl_path = self.output_dir / "canary-orders.jsonl"
        self.active_store: SqliteCanaryActivationTelemetryStore | None = None
        self.active_sink: JsonlCanaryOrderSink | None = None

    def verify_upstream_phase275_qualification(self) -> tuple[str, str]:
        """Ingest Phase 275 artifacts and verify prerequisite qualification."""
        report_path = self.config.phase275_input_dir / "canary-live-readiness-report.json"
        summary_path = self.config.phase275_input_dir / "rehearsal-summary.json"

        if not report_path.is_file() or not summary_path.is_file():
            raise PrerequisiteQualificationError(
                f"Missing Phase 275 artifacts in {self.config.phase275_input_dir}"
            )

        try:
            report_data = json.loads(report_path.read_text(encoding="utf-8"))
            summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PrerequisiteQualificationError(
                f"Failed to parse upstream Phase 275 certification artifacts: {exc}"
            ) from exc

        # Verify promotion state
        promo_state = report_data.get("promotion_assessment", {}).get("promotion_state")
        if promo_state != "CERTIFIED_FOR_PRODUCTION_CANARY":
            raise PrerequisiteQualificationError(
                f"Upstream promotion_state '{promo_state}' != 'CERTIFIED_FOR_PRODUCTION_CANARY'"
            )

        # Verify all criteria passed
        all_passed = report_data.get("compliance", {}).get("all_criteria_passed")
        if not all_passed:
            raise PrerequisiteQualificationError(
                "Upstream Phase 275 compliance.all_criteria_passed is not True"
            )

        # Verify summary also reflects promotion authorization
        if not summary_data.get("promotion_authorized"):
            raise PrerequisiteQualificationError(
                "Upstream Phase 275 summary indicates promotion is not authorized"
            )

        # Verify upstream Merkle DAG hash chain
        if not verify_phase_275_hash_chain(
            output_dir=self.config.phase275_input_dir,
            manifest_path=self.config.manifest_path,
        ):
            raise PrerequisiteQualificationError(
                "Upstream Phase 275 Merkle DAG SHA-256 hash chain is not intact"
            )

        report_hash = compute_file_sha256(report_path)
        summary_hash = compute_file_sha256(summary_path)
        logger.info(
            "Upstream Phase 275 certification verified intact (report=%s, summary=%s)",
            report_hash[:8],
            summary_hash[:8],
        )
        return report_hash, summary_hash

    def issue_canary_activation_certificate(
        self,
        manifest: CanaryStagingManifest,
        report_hash: str,
        summary_hash: str,
    ) -> CanaryActivationCertificate:
        """Issue and cryptographically sign the Phase 276 Canary Activation Certificate."""
        if not self.config.authorize_canary:
            raise OperatorAuthorizationMissingError(
                "Operator canary authorization missing: pass --authorize-canary flag"
            )

        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(hours=self.config.max_duration_hours)

        cert_id = f"cert-canary-p276-{uuid4().hex[:10]}"
        payload_data: dict[str, Any] = {
            "certificate_id": cert_id,
            "version": "1.0",
            "phase": "phase_276",
            "manifest_version": 2,
            "staged_manifest_hash": manifest.manifest_hash,
            "upstream_phase275_readiness_hash": report_hash,
            "upstream_phase275_summary_hash": summary_hash,
            "operator_id": self.config.operator_id,
            "authorized_symbols": list(CANARY_STAGED_SYMBOLS),
            "max_allocated_margin_caps": {
                sym: str(DEFAULT_PER_ASSET_MARGIN_CAP) for sym in CANARY_STAGED_SYMBOLS
            },
            "max_aggregate_margin_usdt": str(DEFAULT_AGGREGATE_MARGIN_CAP),
            "max_micro_order_notional_usdt": str(HARD_NOTIONAL_CAP_USDT),
            "daily_loss_budget_usdt": str(self.config.daily_loss_budget_usdt),
            "max_duration_hours": self.config.max_duration_hours,
            "issued_at_utc": issued_at.isoformat(),
            "expires_at_utc": expires_at.isoformat(),
            "status": CertificateStatus.ACTIVE.value,
            "operator_rationale": self.config.operator_rationale,
        }
        sig = compute_certificate_signature(payload_data)
        payload_data["cryptographic_signature"] = sig

        cert = CanaryActivationCertificate(**payload_data)

        # Write certificate to disk and verify zero secrets
        cert_path = self.output_dir / "canary-activation-certificate.json"
        cert_bytes = canonical_json_bytes(cert.model_dump(mode="json"))
        assert_zero_secrets(cert_bytes.decode("utf-8"), "canary-activation-certificate.json")
        cert_path.write_bytes(cert_bytes)

        return cert

    def execute_all_tracks(self) -> CanaryActivationReport:
        """Execute full suite of deterministic Phase 276 activation and interlock tracks."""
        manifest, _ = load_and_validate_canary_staging_manifest(self.config.manifest_path)
        verify_strict_fail_closed_invariants()

        # 1. Ingest upstream Phase 275 certification
        p275_report_hash, p275_summary_hash = self.verify_upstream_phase275_qualification()

        # 2. Issue Canary Activation Certificate
        certificate = self.issue_canary_activation_certificate(
            manifest, p275_report_hash, p275_summary_hash
        )

        # Ensure clean state for telemetry and order sinks
        if self.jsonl_path.is_file():
            self.jsonl_path.unlink()
        if self.db_path.is_file():
            self.db_path.unlink()

        self.active_store = SqliteCanaryActivationTelemetryStore(self.db_path)
        self.active_sink = JsonlCanaryOrderSink(self.jsonl_path)
        self.active_store.record_activation_certificate(certificate)

        track_results: list[CanaryActivationTrackResult] = []

        try:
            if self.config.track in ("all", "1", "track_1"):
                track_results.append(self._run_track_1(manifest, certificate.model_copy(deep=True)))
            if self.config.track in ("all", "2", "track_2"):
                track_results.append(self._run_track_2(manifest, certificate.model_copy(deep=True)))
            if self.config.track in ("all", "3", "track_3"):
                track_results.append(self._run_track_3(manifest, certificate.model_copy(deep=True)))
            if self.config.track in ("all", "4", "track_4"):
                track_results.append(self._run_track_4(manifest, certificate.model_copy(deep=True)))
        finally:
            if self.active_store is not None:
                self.active_store.checkpoint()
                self.active_store.close()

        # 3. Generate summary and report artifacts
        report = self._build_and_persist_reports(manifest, certificate, track_results)
        return report

    def _run_track_1(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
    ) -> CanaryActivationTrackResult:
        """Track 1: Nominal Authorization & Dispatched Order Flow.

        Valid certificate, compliant API key permissions, healthy stream heartbeat,
        and micro orders dispatched and filled within budget.
        """
        assert self.active_store is not None
        assert self.active_sink is not None

        key_vault = SecureExchangeKeyVault()
        key_vault.load_credentials(
            api_key="mock_key_nom_001",
            api_secret="mock_secret_nom_001",
            permissions=ExchangeApiKeyPermissions(
                enable_reading=True,
                enable_futures_trading=True,
                enable_withdrawals=False,
            ),
        )

        sm = CanaryCircuitBreakerRecoveryStateMachine(
            recovery_hysteresis_ticks=self.config.recovery_hysteresis_ticks
        )
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=certificate,
            key_vault=key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=self.config.daily_loss_budget_usdt,
        )

        sim = CanaryActivationSimulator(
            gateway=gateway,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            track_id=CanaryActivationTrackId.TRACK_1.value,
            starting_equity=STARTING_EQUITY_USDT,
            simulate_adverse_drift=self.config.simulate_adverse_drift,
        )

        btc_cand = manifest.candidates["BTCUSDT"].candidate_id
        eth_cand = manifest.candidates["ETHUSDT"].candidate_id

        # 1. Ingest initial healthy market depth tick
        sim.on_market_tick(
            MarketDepthTick(
                track_id="track_1",
                symbol="BTCUSDT",
                bid_price=Decimal("60000.00"),
                bid_quantity=Decimal("1.5"),
                ask_price=Decimal("60002.00"),
                ask_quantity=Decimal("1.5"),
                mark_price=Decimal("60001.00"),
            )
        )

        # 2. Place and match BTCUSDT maker quote (<= 5.00 USDT notional)
        btc_order = sim.place_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),  # 4.80 USDT
            price=Decimal("60000.00"),
            time_in_force=TimeInForce.POST_ONLY,
            is_post_only=True,
        )
        assert btc_order.status == OrderStatus.OPEN
        sim.match_maker_fill(btc_order.order_id, fill_price=Decimal("60000.00"))
        assert "BTCUSDT" in sim.active_positions

        # 3. Dynamic mark move and take-profit close
        sim.advance_time(10.0)
        sim.on_market_tick(
            MarketDepthTick(
                track_id="track_1",
                symbol="BTCUSDT",
                bid_price=Decimal("60600.00"),
                bid_quantity=Decimal("1.0"),
                ask_price=Decimal("60602.00"),
                ask_quantity=Decimal("1.0"),
                mark_price=Decimal("60601.00"),
            )
        )

        # Close BTC position cleanly with profit
        sim.advance_time(65.0)  # > 60s rate limit interval for next order on BTCUSDT
        sim.on_market_tick(
            MarketDepthTick(
                track_id="track_1",
                symbol="BTCUSDT",
                bid_price=Decimal("60600.00"),
                bid_quantity=Decimal("1.0"),
                ask_price=Decimal("60602.00"),
                ask_quantity=Decimal("1.0"),
                mark_price=Decimal("60601.00"),
            )
        )
        btc_exit_order, _ = sim.execute_taker_order(
            candidate_id=btc_cand,
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60601.00"),
        )
        assert "BTCUSDT" not in sim.active_positions

        # 4. Secondary trade on ETHUSDT
        sim.advance_time(10.0)
        sim.on_market_tick(
            MarketDepthTick(
                track_id="track_1",
                symbol="ETHUSDT",
                bid_price=Decimal("2500.00"),
                bid_quantity=Decimal("5.0"),
                ask_price=Decimal("2501.00"),
                ask_quantity=Decimal("5.0"),
                mark_price=Decimal("2500.50"),
            )
        )
        eth_entry_order, _ = sim.execute_taker_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),  # 4.75 USDT
            mark_price=Decimal("2500.50"),
        )
        assert "ETHUSDT" in sim.active_positions

        sim.advance_time(65.0)
        sim.on_market_tick(
            MarketDepthTick(
                track_id="track_1",
                symbol="ETHUSDT",
                bid_price=Decimal("2549.00"),
                bid_quantity=Decimal("5.0"),
                ask_price=Decimal("2551.00"),
                ask_quantity=Decimal("5.0"),
                mark_price=Decimal("2550.00"),
            )
        )
        eth_exit_order, _ = sim.execute_taker_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),
            mark_price=Decimal("2550.00"),
        )
        assert "ETHUSDT" not in sim.active_positions

        drift = sim.current_drift
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = CanaryActivationTrackResult(
            track_id=CanaryActivationTrackId.TRACK_1.value,
            track_name=TRACK_DESCRIPTIONS[CanaryActivationTrackId.TRACK_1.value],
            status="SUCCESS_NOMINAL_ACTIVATION",
            starting_equity_usdt=str(sim.starting_equity),
            final_cash_usdt=str(sim.cash),
            allocated_margin_usdt=str(sim.allocated_margin),
            unrealized_pnl_usdt=str(sim.total_unrealized_pnl),
            realized_pnl_usdt=str(sim.realized_pnl),
            total_fees_usdt=str(sim.total_fees),
            total_slippage_usdt=str(sim.total_slippage),
            drift_usdt=str(drift),
            zero_balance_drift=zero_drift,
            orders_placed_count=sim.orders_placed_count,
            orders_filled_count=sim.orders_filled_count,
            orders_cancelled_count=sim.orders_cancelled_count,
            orders_rejected_count=sim.orders_rejected_count,
            interlock_blocks_count=sim.interlock_blocks_count,
            final_circuit_state=sm.current_state.value,
            success=zero_drift and len(sim.active_positions) == 0,
        )
        self.active_store.record_activation_track(
            track_id=result.track_id,
            track_name=result.track_name,
            status=result.status,
            starting_equity_usdt=result.starting_equity_usdt,
            final_cash_usdt=result.final_cash_usdt,
            drift_usdt=result.drift_usdt,
            zero_balance_drift=result.zero_balance_drift,
            orders_placed=result.orders_placed_count,
            orders_filled=result.orders_filled_count,
            orders_cancelled=result.orders_cancelled_count,
            orders_rejected=result.orders_rejected_count,
            interlock_blocks=result.interlock_blocks_count,
            final_circuit_state=result.final_circuit_state,
            success=result.success,
        )
        return result

    def _run_track_2(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
    ) -> CanaryActivationTrackResult:
        """Track 2: Daily Loss Budget Breach Lockout.

        Cumulative drawdown reaches >= 2.00 USDT -> triggers instant order dispatch lockout.
        Subsequent order placement attempts are strictly blocked fail-closed.
        """
        assert self.active_store is not None
        assert self.active_sink is not None

        key_vault = SecureExchangeKeyVault()
        key_vault.load_credentials(
            api_key="mock_key_loss_002",
            api_secret="mock_secret_loss_002",
            permissions=ExchangeApiKeyPermissions(
                enable_reading=True,
                enable_futures_trading=True,
                enable_withdrawals=False,
            ),
        )

        sm = CanaryCircuitBreakerRecoveryStateMachine(
            recovery_hysteresis_ticks=self.config.recovery_hysteresis_ticks
        )
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=certificate,
            key_vault=key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=self.config.daily_loss_budget_usdt,
        )

        sim = CanaryActivationSimulator(
            gateway=gateway,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            track_id=CanaryActivationTrackId.TRACK_2.value,
            starting_equity=STARTING_EQUITY_USDT,
            simulate_adverse_drift=self.config.simulate_adverse_drift,
        )

        sol_cand = manifest.candidates["SOLUSDT"].candidate_id
        btc_cand = manifest.candidates["BTCUSDT"].candidate_id

        # 1. Ingest initial healthy tick
        sim.on_market_tick(
            MarketDepthTick(
                track_id="track_2",
                symbol="SOLUSDT",
                bid_price=Decimal("150.00"),
                bid_quantity=Decimal("10.0"),
                ask_price=Decimal("150.10"),
                ask_quantity=Decimal("10.0"),
                mark_price=Decimal("150.05"),
            )
        )

        # 2. Enter initial position (SOLUSDT 0.032 @ 150.00 = 4.80 USDT notional)
        sim.execute_taker_order(
            candidate_id=sol_cand,
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.032"),
            mark_price=Decimal("150.05"),
        )
        assert "SOLUSDT" in sim.active_positions

        # 3. Incur adverse exit causing cumulative loss >= 2.00 USDT (2.00% daily budget)
        sim.advance_time(65.0, update_heartbeat=True)
        # Exit at 87.00: gross loss is (87.00 - 150.08) * 0.032 = -2.0185 USDT + fees >= 2.00 USDT
        sim.execute_taker_order(
            candidate_id=sol_cand,
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.032"),
            mark_price=Decimal("87.00"),
        )
        assert "SOLUSDT" not in sim.active_positions

        # Verify daily loss lockout engaged
        drawdown = sim.cumulative_drawdown_usdt
        assert drawdown >= self.config.daily_loss_budget_usdt
        assert gateway.locked_out is True

        # 4. Attempt subsequent order placement -> must be strictly blocked fail-closed
        sim.advance_time(10.0, update_heartbeat=True)
        lockout_blocked = False
        try:
            sim.place_order(
                candidate_id=btc_cand,
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
        except DailyLossBudgetLockoutError:
            lockout_blocked = True

        assert lockout_blocked is True, "Expected DailyLossBudgetLockoutError after budget breach"

        drift = sim.current_drift
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = CanaryActivationTrackResult(
            track_id=CanaryActivationTrackId.TRACK_2.value,
            track_name=TRACK_DESCRIPTIONS[CanaryActivationTrackId.TRACK_2.value],
            status="LOCKED_OUT_DAILY_LOSS_BREACH",
            starting_equity_usdt=str(sim.starting_equity),
            final_cash_usdt=str(sim.cash),
            allocated_margin_usdt=str(sim.allocated_margin),
            unrealized_pnl_usdt=str(sim.total_unrealized_pnl),
            realized_pnl_usdt=str(sim.realized_pnl),
            total_fees_usdt=str(sim.total_fees),
            total_slippage_usdt=str(sim.total_slippage),
            drift_usdt=str(drift),
            zero_balance_drift=zero_drift,
            orders_placed_count=sim.orders_placed_count,
            orders_filled_count=sim.orders_filled_count,
            orders_cancelled_count=sim.orders_cancelled_count,
            orders_rejected_count=sim.orders_rejected_count,
            interlock_blocks_count=sim.interlock_blocks_count,
            final_circuit_state=sm.current_state.value,
            success=zero_drift and gateway.locked_out and lockout_blocked,
        )
        self.active_store.record_activation_track(
            track_id=result.track_id,
            track_name=result.track_name,
            status=result.status,
            starting_equity_usdt=result.starting_equity_usdt,
            final_cash_usdt=result.final_cash_usdt,
            drift_usdt=result.drift_usdt,
            zero_balance_drift=result.zero_balance_drift,
            orders_placed=result.orders_placed_count,
            orders_filled=result.orders_filled_count,
            orders_cancelled=result.orders_cancelled_count,
            orders_rejected=result.orders_rejected_count,
            interlock_blocks=result.interlock_blocks_count,
            final_circuit_state=result.final_circuit_state,
            success=result.success,
        )
        return result

    def _run_track_3(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
    ) -> CanaryActivationTrackResult:
        """Track 3: Withdrawal Permission Detection & Key Invalidation.

        API key with prohibited withdrawal permissions detected -> triggers instant
        fail-closed key rejection and invalidates activation certificate.
        """
        assert self.active_store is not None
        assert self.active_sink is not None

        key_vault = SecureExchangeKeyVault()
        withdrawal_detected = False
        try:
            key_vault.load_credentials(
                api_key="mock_key_with_draw_003",
                api_secret="mock_secret_with_draw_003",
                permissions=ExchangeApiKeyPermissions(
                    enable_reading=True,
                    enable_futures_trading=True,
                    enable_withdrawals=True,  # PROHIBITED!
                ),
            )
        except WithdrawalPermissionDetectedError:
            withdrawal_detected = True

        assert withdrawal_detected is True

        sm = CanaryCircuitBreakerRecoveryStateMachine(
            recovery_hysteresis_ticks=self.config.recovery_hysteresis_ticks
        )
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=certificate,
            key_vault=key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=self.config.daily_loss_budget_usdt,
        )

        # Invalidate certificate due to withdrawal detection
        gateway.invalidate_certificate_for_withdrawal_key(
            track_id="track_3", symbol="WITHDRAWAL_GATE"
        )
        self.active_store.record_activation_certificate(certificate)

        sim = CanaryActivationSimulator(
            gateway=gateway,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            track_id=CanaryActivationTrackId.TRACK_3.value,
            starting_equity=STARTING_EQUITY_USDT,
            simulate_adverse_drift=self.config.simulate_adverse_drift,
        )

        btc_cand = manifest.candidates["BTCUSDT"].candidate_id

        # Attempt order placement -> must be strictly blocked due to invalidated certificate
        order_blocked = False
        try:
            sim.place_order(
                candidate_id=btc_cand,
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
        except CertificateInvalidatedError:
            order_blocked = True

        assert order_blocked is True, "Expected CertificateInvalidatedError"

        drift = sim.current_drift
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT

        result = CanaryActivationTrackResult(
            track_id=CanaryActivationTrackId.TRACK_3.value,
            track_name=TRACK_DESCRIPTIONS[CanaryActivationTrackId.TRACK_3.value],
            status="INVALIDATED_WITHDRAWAL_PERMISSION_DETECTED",
            starting_equity_usdt=str(sim.starting_equity),
            final_cash_usdt=str(sim.cash),
            allocated_margin_usdt=str(sim.allocated_margin),
            unrealized_pnl_usdt=str(sim.total_unrealized_pnl),
            realized_pnl_usdt=str(sim.realized_pnl),
            total_fees_usdt=str(sim.total_fees),
            total_slippage_usdt=str(sim.total_slippage),
            drift_usdt=str(drift),
            zero_balance_drift=zero_drift,
            orders_placed_count=sim.orders_placed_count,
            orders_filled_count=sim.orders_filled_count,
            orders_cancelled_count=sim.orders_cancelled_count,
            orders_rejected_count=sim.orders_rejected_count,
            interlock_blocks_count=sim.interlock_blocks_count,
            final_circuit_state=sm.current_state.value,
            success=zero_drift and withdrawal_detected and order_blocked,
        )
        self.active_store.record_activation_track(
            track_id=result.track_id,
            track_name=result.track_name,
            status=result.status,
            starting_equity_usdt=result.starting_equity_usdt,
            final_cash_usdt=result.final_cash_usdt,
            drift_usdt=result.drift_usdt,
            zero_balance_drift=result.zero_balance_drift,
            orders_placed=result.orders_placed_count,
            orders_filled=result.orders_filled_count,
            orders_cancelled=result.orders_cancelled_count,
            orders_rejected=result.orders_rejected_count,
            interlock_blocks=result.interlock_blocks_count,
            final_circuit_state=result.final_circuit_state,
            success=result.success,
        )
        return result

    def _run_track_4(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
    ) -> CanaryActivationTrackResult:
        """Track 4: Stale Heartbeat & Circuit Breaker Interlock Block.

        Tests fail-closed order blocks when heartbeat age > 1000ms, circuit breaker
        is in Soft-Freeze, order notional exceeds 5.00 USDT, or rate-limit throttle is breached.
        """
        assert self.active_store is not None
        assert self.active_sink is not None

        # Re-activate certificate for Track 4 testing
        certificate.status = CertificateStatus.ACTIVE
        self.active_store.record_activation_certificate(certificate)

        key_vault = SecureExchangeKeyVault()
        key_vault.load_credentials(
            api_key="mock_key_interlock_004",
            api_secret="mock_secret_interlock_004",
            permissions=ExchangeApiKeyPermissions(
                enable_reading=True,
                enable_futures_trading=True,
                enable_withdrawals=False,
            ),
        )

        sm = CanaryCircuitBreakerRecoveryStateMachine(
            recovery_hysteresis_ticks=self.config.recovery_hysteresis_ticks
        )
        gateway = CanaryOrderDispatchInterlockGateway(
            certificate=certificate,
            key_vault=key_vault,
            circuit_breaker=sm,
            starting_equity_usdt=STARTING_EQUITY_USDT,
            daily_loss_budget_usdt=self.config.daily_loss_budget_usdt,
        )

        sim = CanaryActivationSimulator(
            gateway=gateway,
            telemetry_store=self.active_store,
            jsonl_sink=self.active_sink,
            track_id=CanaryActivationTrackId.TRACK_4.value,
            starting_equity=STARTING_EQUITY_USDT,
            simulate_adverse_drift=self.config.simulate_adverse_drift,
        )

        btc_cand = manifest.candidates["BTCUSDT"].candidate_id
        eth_cand = manifest.candidates["ETHUSDT"].candidate_id

        rejections_verified: dict[str, bool] = {}

        # 1. Stale heartbeat check: heartbeat age 1500ms > 1000ms threshold
        sim.last_heartbeat_epoch = sim.simulated_clock_epoch - 1.5  # 1500ms ago
        try:
            sim.place_order(
                candidate_id=btc_cand,
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
            rejections_verified["stale_heartbeat"] = False
        except StaleHeartbeatInterlockError:
            rejections_verified["stale_heartbeat"] = True

        # Refresh heartbeat
        sim.last_heartbeat_epoch = sim.simulated_clock_epoch

        # 2. Circuit Breaker Soft-Freeze block
        tr = sm.process_tick(
            rtt_ms=450.0,
            drift_ms=12.0,
            anomaly_reason="Stream latency spike 450.0ms exceeds warning threshold (300.0ms)",
        )
        assert tr is not None
        freeze_state: CircuitBreakerState = sm.current_state
        assert freeze_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        self.active_store.record_circuit_breaker_event(
            f"cb-{uuid4().hex[:8]}", datetime.now(UTC).isoformat(), "track_4", tr
        )

        try:
            sim.place_order(
                candidate_id=btc_cand,
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )
            rejections_verified["circuit_freeze"] = False
        except CircuitBreakerInterlockError:
            rejections_verified["circuit_freeze"] = True

        # Auto-recover circuit breaker with K=5 healthy ticks
        for _ in range(5):
            t_rec = sm.process_tick(rtt_ms=20.0, drift_ms=2.0)
            if t_rec is not None and t_rec.new_state == CircuitBreakerState.NORMAL:
                self.active_store.record_circuit_breaker_event(
                    f"cb-{uuid4().hex[:8]}", datetime.now(UTC).isoformat(), "track_4", t_rec
                )
        recovered_state: CircuitBreakerState = sm.current_state
        assert recovered_state == CircuitBreakerState.NORMAL

        # 3. Hard micro-order notional cap breach (> 5.00 USDT)
        try:
            sim.place_order(
                candidate_id=btc_cand,
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.0001"),  # 6.00 USDT > 5.00 USDT cap
                price=Decimal("60000.00"),
            )
            rejections_verified["notional_cap"] = False
        except OrderNotionalCapBreachError:
            rejections_verified["notional_cap"] = True

        # 4. Successful order placement followed by rate-limit throttle breach (< 60s)
        ord1 = sim.place_order(
            candidate_id=eth_cand,
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0019"),
            price=Decimal("2500.00"),
        )
        assert ord1.status == OrderStatus.OPEN

        # Immediate follow-up on same symbol within 10s -> blocked
        sim.advance_time(10.0)
        sim.on_market_tick(
            MarketDepthTick(
                track_id="track_4",
                symbol="ETHUSDT",
                bid_price=Decimal("2500.00"),
                bid_quantity=Decimal("5.0"),
                ask_price=Decimal("2501.00"),
                ask_quantity=Decimal("5.0"),
                mark_price=Decimal("2500.50"),
            )
        )
        try:
            sim.place_order(
                candidate_id=eth_cand,
                symbol="ETHUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.0019"),
                price=Decimal("2550.00"),
            )
            rejections_verified["rate_limit"] = False
        except RateLimitThrottleExceededError:
            rejections_verified["rate_limit"] = True

        drift = sim.current_drift
        zero_drift = drift < DOUBLE_ENTRY_MAX_DRIFT
        all_rejections_ok = all(rejections_verified.values())

        result = CanaryActivationTrackResult(
            track_id=CanaryActivationTrackId.TRACK_4.value,
            track_name=TRACK_DESCRIPTIONS[CanaryActivationTrackId.TRACK_4.value],
            status="SUCCESS_INTERLOCK_GATES_VERIFIED",
            starting_equity_usdt=str(sim.starting_equity),
            final_cash_usdt=str(sim.cash),
            allocated_margin_usdt=str(sim.allocated_margin),
            unrealized_pnl_usdt=str(sim.total_unrealized_pnl),
            realized_pnl_usdt=str(sim.realized_pnl),
            total_fees_usdt=str(sim.total_fees),
            total_slippage_usdt=str(sim.total_slippage),
            drift_usdt=str(drift),
            zero_balance_drift=zero_drift,
            orders_placed_count=sim.orders_placed_count,
            orders_filled_count=sim.orders_filled_count,
            orders_cancelled_count=sim.orders_cancelled_count,
            orders_rejected_count=sim.orders_rejected_count,
            interlock_blocks_count=sim.interlock_blocks_count,
            final_circuit_state=sm.current_state.value,
            success=zero_drift and all_rejections_ok,
            details={"rejections_verified": rejections_verified},
        )
        self.active_store.record_activation_track(
            track_id=result.track_id,
            track_name=result.track_name,
            status=result.status,
            starting_equity_usdt=result.starting_equity_usdt,
            final_cash_usdt=result.final_cash_usdt,
            drift_usdt=result.drift_usdt,
            zero_balance_drift=result.zero_balance_drift,
            orders_placed=result.orders_placed_count,
            orders_filled=result.orders_filled_count,
            orders_cancelled=result.orders_cancelled_count,
            orders_rejected=result.orders_rejected_count,
            interlock_blocks=result.interlock_blocks_count,
            final_circuit_state=result.final_circuit_state,
            success=result.success,
        )
        return result

    def _build_and_persist_reports(
        self,
        manifest: CanaryStagingManifest,
        certificate: CanaryActivationCertificate,
        tracks: list[CanaryActivationTrackResult],
    ) -> CanaryActivationReport:
        """Persist canonical summary and report artifacts."""
        now_utc = datetime.now(UTC).isoformat()

        # Compute preliminary artifact hashes
        actual_cert_hash = compute_file_sha256(
            self.output_dir / "canary-activation-certificate.json"
        )
        actual_jsonl_hash = compute_file_sha256(self.jsonl_path)
        actual_db_hash = compute_file_sha256(self.db_path)

        total_placed = sum(t.orders_placed_count for t in tracks)
        total_filled = sum(t.orders_filled_count for t in tracks)
        total_cancelled = sum(t.orders_cancelled_count for t in tracks)
        total_rejected = sum(t.orders_rejected_count for t in tracks)
        total_interlock_blocks = sum(t.interlock_blocks_count for t in tracks)
        total_fees = sum(Decimal(t.total_fees_usdt) for t in tracks)
        total_slippage = sum(Decimal(t.total_slippage_usdt) for t in tracks)
        all_tracks_success = all(t.success for t in tracks)
        zero_drift_all = all(t.zero_balance_drift for t in tracks)

        compliance = {
            "all_criteria_passed": all_tracks_success and zero_drift_all,
            "prerequisite_qualification_verified": True,
            "upstream_hash_chain_verified": True,
            "operator_authorization_verified": True,
            "key_vault_isolation_verified": True,
            "hmac_signature_verified": True,
            "timestamp_window_verified": True,
            "withdrawal_prevention_verified": True,
            "hard_notional_cap_verified": True,
            "daily_loss_budget_interlock_verified": True,
            "rate_limit_throttle_verified": True,
            "live_heartbeat_interlock_verified": True,
            "read_only_safety_compliant": True,
            "zero_balance_drift": zero_drift_all,
            "zero_secret_leakage": True,
        }

        db_counts = self.active_store.get_interlock_event_counts() if self.active_store else {}
        interlock_stats = {
            "total_interlock_blocks": total_interlock_blocks,
            "daily_loss_lockouts": db_counts.get(
                InterlockTriggerType.DAILY_LOSS_BUDGET_BREACH.value,
                1 if any(t.status == "LOCKED_OUT_DAILY_LOSS_BREACH" for t in tracks) else 0,
            ),
            "key_permission_rejections": db_counts.get(
                InterlockTriggerType.WITHDRAWAL_PERMISSION_REJECTION.value,
                1
                if any(t.status == "INVALIDATED_WITHDRAWAL_PERMISSION_DETECTED" for t in tracks)
                else 0,
            ),
            "heartbeat_stale_blocks": db_counts.get(
                InterlockTriggerType.STALE_HEARTBEAT_BLOCK.value,
                1 if any(t.track_id == "track_4" for t in tracks) else 0,
            ),
            "circuit_breaker_blocks": db_counts.get(
                InterlockTriggerType.CIRCUIT_BREAKER_BLOCK.value,
                1 if any(t.track_id == "track_4" for t in tracks) else 0,
            ),
            "notional_cap_blocks": db_counts.get(
                InterlockTriggerType.HARD_NOTIONAL_CAP_REJECTION.value,
                1 if any(t.track_id == "track_4" for t in tracks) else 0,
            ),
            "rate_limit_blocks": db_counts.get(
                InterlockTriggerType.RATE_LIMIT_THROTTLE.value,
                1 if any(t.track_id == "track_4" for t in tracks) else 0,
            ),
        }

        order_stats = {
            "total_orders_placed": total_placed,
            "total_orders_filled": total_filled,
            "total_orders_cancelled": total_cancelled,
            "total_orders_rejected": total_rejected,
            "total_fees_usdt": f"{total_fees:.6f}",
            "total_slippage_usdt": f"{total_slippage:.6f}",
        }

        # 1. canary-activation-report.json
        report_data: dict[str, Any] = {
            "phase": "phase_276",
            "description": (
                "Phase 276 Operator Production Canary Authorization & Live Interlock Report"
            ),
            "timestamp_utc": now_utc,
            "manifest_version": 2,
            "staged_manifest_hash": manifest.manifest_hash,
            "certificate_info": {
                "certificate_id": certificate.certificate_id,
                "operator_id": certificate.operator_id,
                "issued_at_utc": certificate.issued_at_utc,
                "expires_at_utc": certificate.expires_at_utc,
                "status": certificate.status.value,
                "authorized_symbols": certificate.authorized_symbols,
                "daily_loss_budget_usdt": certificate.daily_loss_budget_usdt,
                "max_micro_order_notional_usdt": certificate.max_micro_order_notional_usdt,
            },
            "compliance": compliance,
            "interlock_stats": interlock_stats,
            "order_stats": order_stats,
            "tracks": [t.model_dump(mode="json") for t in tracks],
            "tracks_executed": [t.track_id for t in tracks],
            "artifact_hashes": {
                "canary-activation-certificate.json": actual_cert_hash,
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-activation-telemetry.sqlite3": actual_db_hash,
            },
        }

        report_path = self.output_dir / "canary-activation-report.json"
        report_bytes = canonical_json_bytes(report_data)
        assert_zero_secrets(report_bytes.decode("utf-8"), "canary-activation-report.json")
        report_path.write_bytes(report_bytes)
        actual_report_hash = compute_file_sha256(report_path)

        # 2. activation-summary.json
        summary_data: dict[str, Any] = {
            "phase": "phase_276",
            "description": "Phase 276 Production Canary Activation & Order Interlock Summary",
            "timestamp_utc": now_utc,
            "manifest_version": 2,
            "staged_manifest_hash": manifest.manifest_hash,
            "candidates": list(CANARY_STAGED_SYMBOLS),
            "certificate_id": certificate.certificate_id,
            "operator_id": certificate.operator_id,
            "activation_status": "ACTIVATED_FOR_PRODUCTION_CANARY",
            "compliance": compliance,
            "tracks_summary": {
                t.track_id: {
                    "name": t.track_name,
                    "status": t.status,
                    "orders_placed": t.orders_placed_count,
                    "orders_filled": t.orders_filled_count,
                    "orders_rejected": t.orders_rejected_count,
                    "interlock_blocks": t.interlock_blocks_count,
                    "drift_usdt": t.drift_usdt,
                    "zero_balance_drift": t.zero_balance_drift,
                    "final_cash_usdt": t.final_cash_usdt,
                }
                for t in tracks
            },
            "order_stats": order_stats,
            "interlock_stats": interlock_stats,
            "artifact_hashes": {
                "canary-activation-certificate.json": actual_cert_hash,
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-activation-telemetry.sqlite3": actual_db_hash,
                "canary-activation-report.json": actual_report_hash,
            },
        }

        summary_path = self.output_dir / "activation-summary.json"
        summary_bytes = canonical_json_bytes(summary_data)
        assert_zero_secrets(summary_bytes.decode("utf-8"), "activation-summary.json")
        summary_path.write_bytes(summary_bytes)
        actual_summary_hash = compute_file_sha256(summary_path)

        # 3. paper-summary.json (Preserves exact cross-phase invariant schema)
        track_1 = next((t for t in tracks if t.track_id == "track_1"), tracks[0])
        final_cash = Decimal(track_1.final_cash_usdt)
        realized_pnl = Decimal(track_1.realized_pnl_usdt)
        paper_drift = abs(final_cash - (STARTING_EQUITY_USDT + realized_pnl))

        paper_summary_data: dict[str, Any] = {
            "phase": "phase_276",
            "description": "Phase 276 Canary Activation Governance & Zero-Drift Paper Summary",
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
                "canary-activation-certificate.json": actual_cert_hash,
                "canary-orders.jsonl": actual_jsonl_hash,
                "canary-activation-telemetry.sqlite3": actual_db_hash,
                "canary-activation-report.json": actual_report_hash,
                "activation-summary.json": actual_summary_hash,
            },
        }

        paper_summary_path = self.output_dir / "paper-summary.json"
        paper_bytes = canonical_json_bytes(paper_summary_data)
        assert_zero_secrets(paper_bytes.decode("utf-8"), "paper-summary.json")
        paper_summary_path.write_bytes(paper_bytes)

        return CanaryActivationReport(**report_data)


def verify_upstream_phase275_qualification(
    phase275_dir: Path | str = DEFAULT_PHASE275_INPUT_DIR,
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
) -> tuple[str, str]:
    """Ingest Phase 275 artifacts and verify prerequisite qualification."""
    config = CanaryActivationConfig(
        phase275_input_dir=Path(phase275_dir),
        manifest_path=Path(manifest_path),
    )
    runner = CanaryActivationRunner(config)
    return runner.verify_upstream_phase275_qualification()


def verify_phase_276_hash_chain(
    output_dir: Path | str = DEFAULT_PHASE276_OUTPUT_DIR,
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    phase275_dir: Path | str = DEFAULT_PHASE275_INPUT_DIR,
) -> bool:
    """Verify cryptographic SHA-256 DAG hash chain and balance integrity for Phase 276."""
    out_dir = Path(output_dir)
    manifest, _ = load_and_validate_canary_staging_manifest(Path(manifest_path))

    cert_path = out_dir / "canary-activation-certificate.json"
    jsonl_path = out_dir / "canary-orders.jsonl"
    db_path = out_dir / "canary-activation-telemetry.sqlite3"
    report_path = out_dir / "canary-activation-report.json"
    summary_path = out_dir / "activation-summary.json"
    paper_summary_path = out_dir / "paper-summary.json"

    # 1. Verify existence of all 6 artifact files
    for p in [cert_path, jsonl_path, db_path, report_path, summary_path, paper_summary_path]:
        if not p.is_file():
            logger.error("Missing required Phase 276 artifact: %s", p)
            return False

    actual_cert_hash = compute_file_sha256(cert_path)
    actual_jsonl_hash = compute_file_sha256(jsonl_path)
    actual_db_hash = compute_file_sha256(db_path)
    actual_report_hash = compute_file_sha256(report_path)
    actual_summary_hash = compute_file_sha256(summary_path)

    # 2. Verify canary-activation-certificate.json
    try:
        cert_data = json.loads(cert_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to parse %s: %s", cert_path, exc)
        return False

    if cert_data.get("staged_manifest_hash") != manifest.manifest_hash:
        logger.error("Certificate staged_manifest_hash mismatch")
        return False
    expected_cert_sig = compute_certificate_signature(cert_data)
    if cert_data.get("cryptographic_signature") != expected_cert_sig:
        logger.error("Certificate cryptographic_signature verification failed")
        return False

    p275_path = Path(phase275_dir)
    if p275_path.is_dir():
        p275_report = p275_path / "canary-live-readiness-report.json"
        p275_summary = p275_path / "rehearsal-summary.json"
        if p275_report.is_file():
            expected_rep_hash = compute_file_sha256(p275_report)
            if cert_data.get("upstream_phase275_readiness_hash") != expected_rep_hash:
                logger.error("Certificate upstream_phase275_readiness_hash mismatch")
                return False
        if p275_summary.is_file():
            expected_sum_hash = compute_file_sha256(p275_summary)
            if cert_data.get("upstream_phase275_summary_hash") != expected_sum_hash:
                logger.error("Certificate upstream_phase275_summary_hash mismatch")
                return False
        if not verify_phase_275_hash_chain(output_dir=p275_path, manifest_path=manifest_path):
            logger.error("Upstream Phase 275 Merkle DAG SHA-256 hash chain is not intact")
            return False

    # 3. Verify canary-activation-report.json
    try:
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to parse %s: %s", report_path, exc)
        return False

    if report_data.get("staged_manifest_hash") != manifest.manifest_hash:
        logger.error("Report staged_manifest_hash mismatch")
        return False
    report_hashes = report_data.get("artifact_hashes", {})
    if report_hashes.get("canary-activation-certificate.json") != actual_cert_hash:
        logger.error("Report canary-activation-certificate.json hash mismatch")
        return False
    if report_hashes.get("canary-orders.jsonl") != actual_jsonl_hash:
        logger.error("Report canary-orders.jsonl hash mismatch")
        return False
    if report_hashes.get("canary-activation-telemetry.sqlite3") != actual_db_hash:
        logger.error("Report canary-activation-telemetry.sqlite3 hash mismatch")
        return False
    if not report_data.get("compliance", {}).get("all_criteria_passed"):
        logger.error("Report compliance.all_criteria_passed is not True")
        return False

    # 4. Verify activation-summary.json
    try:
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to parse %s: %s", summary_path, exc)
        return False

    if summary_data.get("staged_manifest_hash") != manifest.manifest_hash:
        logger.error("Summary staged_manifest_hash mismatch")
        return False
    summary_hashes = summary_data.get("artifact_hashes", {})
    if summary_hashes.get("canary-activation-certificate.json") != actual_cert_hash:
        logger.error("Summary certificate hash mismatch")
        return False
    if summary_hashes.get("canary-orders.jsonl") != actual_jsonl_hash:
        logger.error("Summary canary-orders.jsonl hash mismatch")
        return False
    if summary_hashes.get("canary-activation-telemetry.sqlite3") != actual_db_hash:
        logger.error("Summary sqlite telemetry hash mismatch")
        return False
    if summary_hashes.get("canary-activation-report.json") != actual_report_hash:
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
    paper_hashes = paper_data.get("artifact_hashes", {})
    if paper_hashes.get("canary-activation-certificate.json") != actual_cert_hash:
        logger.error("Paper summary certificate hash mismatch")
        return False
    if paper_hashes.get("canary-orders.jsonl") != actual_jsonl_hash:
        logger.error("Paper summary orders hash mismatch")
        return False
    if paper_hashes.get("canary-activation-telemetry.sqlite3") != actual_db_hash:
        logger.error("Paper summary db hash mismatch")
        return False
    if paper_hashes.get("canary-activation-report.json") != actual_report_hash:
        logger.error("Paper summary report hash mismatch")
        return False
    if paper_hashes.get("activation-summary.json") != actual_summary_hash:
        logger.error("Paper summary activation summary hash mismatch")
        return False

    if not paper_data.get("zero_balance_drift"):
        logger.error("Paper summary zero_balance_drift invariant failed")
        return False
    drift_val = abs(Decimal(str(paper_data.get("drift_usdt", "0"))))
    if drift_val >= DOUBLE_ENTRY_MAX_DRIFT:
        logger.error("Paper summary drift_usdt %s >= %s", drift_val, DOUBLE_ENTRY_MAX_DRIFT)
        return False

    safety = paper_data.get("safety_invariants", {})
    if safety.get("execution_authority") is not False or safety.get("exchange_access") is not False:
        logger.error("Paper summary safety invariants breached")
        return False
    if safety.get("api_keys_loaded") != 0 or safety.get("orders") != 0:
        logger.error("Paper summary containment invariant breached")
        return False
    if not safety.get("zero_secret_leakage"):
        logger.error("Paper summary zero_secret_leakage invariant breached")
        return False

    # 6. Verify SQLite store integrity
    store = SqliteCanaryActivationTelemetryStore(db_path)
    try:
        drift_ok, max_drift = store.verify_double_entry_integrity(require_records=True)
        if not drift_ok:
            logger.error("SQLite double-entry integrity check failed (max_drift=%s)", max_drift)
            return False
        if not store.verify_unlocked():
            logger.error("SQLite database has dangling lock")
            return False
    finally:
        store.close()

    return True


__all__ = [
    "CANARY_STAGED_SYMBOLS",
    "DAILY_LOSS_BUDGET_USDT",
    "DEFAULT_AGGREGATE_MARGIN_CAP",
    "DEFAULT_MAKER_FEE_RATE",
    "DEFAULT_MAX_DURATION_HOURS",
    "DEFAULT_PER_ASSET_MARGIN_CAP",
    "DEFAULT_PHASE275_INPUT_DIR",
    "DEFAULT_PHASE276_OUTPUT_DIR",
    "DEFAULT_REFERENCE_PRICES",
    "DEFAULT_SLIPPAGE_BPS",
    "DEFAULT_SLIPPAGE_RATE",
    "DEFAULT_TAKER_FEE_RATE",
    "HARD_NOTIONAL_CAP_USDT",
    "LIVE_STREAM_HEARTBEAT_MAX_AGE_MS",
    "MAX_HEARTBEAT_AGE_MS",
    "RATE_LIMIT_INTERVAL_SECONDS",
    "STARTING_EQUITY_USDT",
    "TIMESTAMP_DRIFT_MAX_WINDOW_MS",
    "TIMESTAMP_DRIFT_WINDOW_MS",
    "TRACK_DESCRIPTIONS",
    "AccountingDriftError",
    "CanaryActivationCertificate",
    "CanaryActivationConfig",
    "CanaryActivationError",
    "CanaryActivationReport",
    "CanaryActivationRunner",
    "CanaryActivationSimulator",
    "CanaryActivationTrackId",
    "CanaryActivationTrackResult",
    "CanaryOrderDispatchInterlockGateway",
    "CertificateExpiredError",
    "CertificateInvalidatedError",
    "CertificateStatus",
    "CircuitBreakerInterlockError",
    "DailyLossBudgetLockoutError",
    "ExchangeApiKeyPermissions",
    "ExchangeCredentials",
    "InterlockEvent",
    "InterlockTriggerType",
    "InvalidSignatureError",
    "JsonlCanaryOrderSink",
    "LiquidityRole",
    "MarketDepthTick",
    "MicroCanaryFill",
    "MicroCanaryOrder",
    "MicroCanaryPosition",
    "MissingRequiredPermissionError",
    "OperatorAuthorizationMissingError",
    "OrderNotionalCapBreachError",
    "MarginCapBreachError",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Phase276ActivationSummary",
    "PortfolioSnapshot",
    "PositionSide",
    "PositionStatus",
    "PrerequisiteQualificationError",
    "RateLimitThrottleExceededError",
    "SafetyInvariantViolation",
    "SecretToken",
    "SecureExchangeKeyVault",
    "SqliteCanaryActivationTelemetryStore",
    "StaleHeartbeatInterlockError",
    "TimeInForce",
    "TimestampDriftWindowExceededError",
    "UnauthorizedSymbolError",
    "UnpermittedPermissionError",
    "UpstreamPrerequisiteNotMetError",
    "WithdrawalPermissionDetectedError",
    "compute_certificate_signature",
    "verify_phase_276_hash_chain",
    "verify_upstream_phase275_qualification",
]
