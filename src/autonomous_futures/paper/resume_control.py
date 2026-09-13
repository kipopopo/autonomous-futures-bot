"""Fail-closed preparation of operator-approved paper resume evidence."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from ..domain.risk import ResumeEvidence

MAX_PREFLIGHT_AGE = timedelta(minutes=2)
MAX_REQUEST_LIFETIME = timedelta(minutes=15)
BreakerState = Literal["NORMAL", "THROTTLED", "HALTED", "EMERGENCY_FLAT"]
_BREAKER_STATES: tuple[BreakerState, ...] = (
    "NORMAL",
    "THROTTLED",
    "HALTED",
    "EMERGENCY_FLAT",
)


class PaperRecoveryPreflight(DomainModel):
    """Read-only state snapshot that must be safe before paper resume preparation."""

    observed_at: datetime
    breaker_sidecar_state: BreakerState
    daemon_health_state: BreakerState
    daemon_status: str = Field(min_length=1)
    heartbeat_fresh: bool
    scheduler_status: str = Field(min_length=1)
    scheduler_heartbeat_fresh: bool
    ledger_integrity: Literal["ok", "failed", "unknown"]
    ledger_opens: int = Field(ge=0, strict=True)
    ledger_closes: int = Field(ge=0, strict=True)
    dirty_intents: int = Field(ge=0, strict=True)
    unmatched_opens: int = Field(ge=0, strict=True)
    persisted_positions: int = Field(ge=0, strict=True)
    active_positions: int = Field(ge=0, strict=True)
    candidate_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_count: int = Field(ge=0, strict=True)
    orders_submitted: int = Field(ge=0, strict=True)
    execution_authority: bool
    live_trading_activation: bool
    zero_private_credentials: bool

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at must be timezone-aware UTC")
        return value.astimezone(UTC)


class PaperResumeRequest(DomainModel):
    """Immutable approval evidence; it never applies or executes the resume."""

    request_version: Literal[1] = 1
    request_id: str = Field(pattern=r"^paper-resume-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    evidence: ResumeEvidence
    preflight: PaperRecoveryPreflight
    created_at: datetime
    expires_at: datetime
    status: Literal["ready_for_operator_apply"] = "ready_for_operator_apply"
    control_scope: Literal["paper_only"] = "paper_only"
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    testnet_activation: Literal[False] = False
    live_activation: Literal[False] = False
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at", "expires_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("resume request timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_request_contract(self) -> PaperResumeRequest:
        if self.expires_at <= self.created_at:
            raise ValueError("resume request expiry must be after creation")
        if self.expires_at - self.created_at > MAX_REQUEST_LIFETIME:
            raise ValueError("resume request lifetime is too long")
        if not self.evidence.can_resume:
            raise ValueError("resume evidence incomplete")
        blockers = _preflight_blockers(self.preflight)
        if blockers:
            raise ValueError("resume preflight blocked: " + ", ".join(blockers))
        preflight_age = self.created_at - self.preflight.observed_at
        if preflight_age < timedelta(0):
            raise ValueError("resume preflight timestamp is in the future")
        if preflight_age > MAX_PREFLIGHT_AGE:
            raise ValueError("resume preflight_stale")
        return self


def _preflight_blockers(preflight: PaperRecoveryPreflight) -> tuple[str, ...]:
    blockers: list[str] = []
    if preflight.breaker_sidecar_state != "HALTED":
        blockers.append("breaker_sidecar_not_halted")
    if preflight.daemon_health_state != "HALTED":
        blockers.append("daemon_health_not_halted")
    if preflight.daemon_status != "RUNNING":
        blockers.append("daemon_not_running")
    if not preflight.heartbeat_fresh:
        blockers.append("daemon_heartbeat_stale")
    if preflight.scheduler_status != "IDLE":
        blockers.append("scheduler_not_idle")
    if not preflight.scheduler_heartbeat_fresh:
        blockers.append("scheduler_heartbeat_stale")
    if preflight.ledger_integrity != "ok":
        blockers.append("ledger_integrity_not_ok")
    if preflight.ledger_opens != preflight.ledger_closes:
        blockers.append("ledger_open_close_mismatch")
    if preflight.dirty_intents:
        blockers.append("dirty_intents")
    if preflight.unmatched_opens:
        blockers.append("unmatched_opens")
    if preflight.persisted_positions:
        blockers.append("persisted_positions")
    if preflight.active_positions:
        blockers.append("active_positions")
    if preflight.candidate_count:
        blockers.append("candidate_count")
    if preflight.orders_submitted:
        blockers.append("orders_submitted")
    if preflight.execution_authority:
        blockers.append("execution_authority_enabled")
    if preflight.live_trading_activation:
        blockers.append("live_trading_enabled")
    if not preflight.zero_private_credentials:
        blockers.append("private_credentials_detected")
    return tuple(blockers)


def paper_resume_request_content_hash(request: PaperResumeRequest) -> str:
    """Return the canonical hash over all request fields except its self-hash."""
    payload = request.model_dump(mode="json", exclude={"request_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


def _read_json_object(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DataQualityError(f"paper recovery {label} is unavailable") from exc
    if not isinstance(payload, dict):
        raise DataQualityError(f"paper recovery {label} must be a JSON object")
    return payload


def _required_text(payload: Mapping[str, object], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DataQualityError(f"paper recovery {label} is missing {key}")
    return value


def _required_breaker_state(payload: Mapping[str, object], *, label: str) -> BreakerState:
    value = _required_text(payload, "circuit_breaker_status", label=label)
    if value not in _BREAKER_STATES:
        raise DataQualityError(f"paper recovery {label} has invalid circuit_breaker_status")
    return value


def _required_int(payload: Mapping[str, object], key: str, *, label: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DataQualityError(f"paper recovery {label} has invalid {key}")
    return value


def _required_bool(payload: Mapping[str, object], key: str, *, label: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise DataQualityError(f"paper recovery {label} has invalid {key}")
    return value


def _parse_utc_text(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataQualityError(f"paper recovery {label} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise DataQualityError(f"paper recovery {label} timestamp must be UTC")
    return parsed.astimezone(UTC)


def _is_fresh_timestamp(value: str, *, observed_at: datetime, label: str) -> bool:
    parsed = _parse_utc_text(value, label=label)
    age = observed_at - parsed
    return timedelta(0) <= age <= MAX_PREFLIGHT_AGE


def _read_ledger_recovery_counts(path: Path) -> tuple[int, int, int, int, int]:
    if not path.is_file():
        raise DataQualityError("paper recovery ledger is unavailable")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    except (sqlite3.Error, OSError) as exc:
        raise DataQualityError("paper recovery ledger cannot open read-only") from exc
    try:
        connection.execute("PRAGMA query_only = ON;")
        connection.execute("PRAGMA busy_timeout = 1000;")
        if connection.execute("PRAGMA query_only;").fetchone() != (1,):
            raise DataQualityError("paper recovery ledger is not query-only")
        if connection.execute("PRAGMA integrity_check;").fetchall() != [("ok",)]:
            raise DataQualityError("paper recovery ledger integrity is not ok")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        required_tables = {
            "paper_ledger_events",
            "paper_position_state",
            "paper_position_update_intent",
        }
        if not required_tables.issubset(tables):
            raise DataQualityError("paper recovery ledger schema is incomplete")
        opens = int(
            connection.execute(
                "SELECT COUNT(*) FROM paper_ledger_events WHERE event = 'open'"
            ).fetchone()[0]
        )
        closes = int(
            connection.execute(
                "SELECT COUNT(*) FROM paper_ledger_events WHERE event = 'close'"
            ).fetchone()[0]
        )
        dirty_intents = int(
            connection.execute("SELECT COUNT(*) FROM paper_position_update_intent").fetchone()[0]
        )
        unmatched_opens = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM paper_ledger_events AS opened
                LEFT JOIN paper_ledger_events AS closed
                    ON closed.trade_id = opened.trade_id AND closed.event = 'close'
                WHERE opened.event = 'open' AND closed.sequence IS NULL
                """
            ).fetchone()[0]
        )
        persisted_positions = int(
            connection.execute("SELECT COUNT(*) FROM paper_position_state").fetchone()[0]
        )
        return opens, closes, dirty_intents, unmatched_opens, persisted_positions
    except DataQualityError:
        raise
    except sqlite3.Error as exc:
        raise DataQualityError("paper recovery ledger read failed") from exc
    finally:
        connection.close()


def capture_paper_recovery_preflight(
    storage_dir: Path,
    *,
    observed_at: datetime | None = None,
) -> PaperRecoveryPreflight:
    """Capture current paper state read-only for a later explicit resume review."""
    current_time = observed_at or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() != UTC.utcoffset(current_time):
        raise DataQualityError("paper recovery observed_at must be timezone-aware UTC")
    current_time = current_time.astimezone(UTC)

    health = _read_json_object(storage_dir / "paper-daemon-health.json", label="health")
    sidecar = _read_json_object(
        storage_dir / "paper-circuit-breaker-state.json", label="breaker sidecar"
    )
    scheduler_path = storage_dir / "scheduler" / "scheduler-health.json"
    if not scheduler_path.is_file():
        scheduler_path = storage_dir / "scheduler-health.json"
    scheduler = _read_json_object(scheduler_path, label="scheduler health")

    active_positions = health.get("active_positions")
    if not isinstance(active_positions, dict):
        raise DataQualityError("paper recovery health is missing active_positions")
    active_positions_count = _required_int(health, "active_positions_count", label="health")
    if active_positions_count != len(active_positions):
        raise DataQualityError("paper recovery active position count mismatch")

    safety = health.get("zero_order_safety_invariants")
    if not isinstance(safety, dict):
        raise DataQualityError("paper recovery health is missing safety invariants")

    from .candidate_registry import read_candidate_registry

    try:
        candidate_registry = read_candidate_registry(storage_dir / "candidate_registry.json")
    except (OSError, DomainViolation) as exc:
        raise DataQualityError("paper recovery candidate registry is unavailable") from exc

    opens, closes, dirty, unmatched, persisted = _read_ledger_recovery_counts(
        storage_dir / "paper-ledger.sqlite3"
    )
    try:
        return PaperRecoveryPreflight(
            observed_at=current_time,
            breaker_sidecar_state=_required_breaker_state(sidecar, label="breaker sidecar"),
            daemon_health_state=_required_breaker_state(health, label="health"),
            daemon_status=_required_text(health, "daemon_status", label="health"),
            heartbeat_fresh=_is_fresh_timestamp(
                _required_text(health, "last_heartbeat_utc", label="health"),
                observed_at=current_time,
                label="daemon heartbeat",
            ),
            scheduler_status=_required_text(scheduler, "status", label="scheduler health"),
            scheduler_heartbeat_fresh=_is_fresh_timestamp(
                _required_text(scheduler, "updated_at", label="scheduler health"),
                observed_at=current_time,
                label="scheduler heartbeat",
            ),
            ledger_integrity="ok",
            ledger_opens=opens,
            ledger_closes=closes,
            dirty_intents=dirty,
            unmatched_opens=unmatched,
            persisted_positions=persisted,
            active_positions=active_positions_count,
            candidate_registry_hash=candidate_registry.registry_hash,
            candidate_count=len(candidate_registry.symbols),
            orders_submitted=_required_int(safety, "orders_submitted", label="safety invariants"),
            execution_authority=_required_bool(
                safety, "execution_authority", label="safety invariants"
            ),
            live_trading_activation=_required_bool(
                safety, "live_trading_activation", label="safety invariants"
            ),
            zero_private_credentials=_required_bool(
                safety, "zero_private_credentials", label="safety invariants"
            ),
        )
    except ValidationError as exc:
        raise DataQualityError("invalid paper recovery preflight state") from exc


def build_paper_resume_request(
    *,
    request_id: str,
    evidence: ResumeEvidence,
    preflight: PaperRecoveryPreflight,
    created_at: datetime,
    expires_at: datetime,
) -> PaperResumeRequest:
    """Validate explicit evidence and build a non-authoritative resume request."""
    try:
        verified_evidence = ResumeEvidence.model_validate(evidence.model_dump())
        verified_preflight = PaperRecoveryPreflight.model_validate(preflight.model_dump())
    except ValidationError as exc:
        raise DataQualityError("invalid paper resume input") from exc

    if not verified_evidence.can_resume:
        raise DataQualityError("resume evidence incomplete")
    blockers = _preflight_blockers(verified_preflight)
    if blockers:
        raise DataQualityError("paper resume preflight blocked: " + ", ".join(blockers))
    if created_at.tzinfo is None or created_at.utcoffset() != UTC.utcoffset(created_at):
        raise DataQualityError("resume request created_at must be timezone-aware UTC")
    created_at_utc = created_at.astimezone(UTC)
    preflight_age = created_at_utc - verified_preflight.observed_at
    if preflight_age < timedelta(0):
        raise DataQualityError("resume preflight timestamp is in the future")
    if preflight_age > MAX_PREFLIGHT_AGE:
        raise DataQualityError("paper resume preflight_stale")

    try:
        provisional = PaperResumeRequest(
            request_id=request_id,
            evidence=verified_evidence,
            preflight=verified_preflight,
            created_at=created_at,
            expires_at=expires_at,
            request_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid paper resume request") from exc
    return provisional.model_copy(
        update={"request_hash": paper_resume_request_content_hash(provisional)}
    )


def read_paper_resume_request(path: Path) -> PaperResumeRequest:
    """Read and verify one persisted resume request without changing state."""
    try:
        request = PaperResumeRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        raise DomainViolation("invalid paper resume request") from exc
    if paper_resume_request_content_hash(request) != request.request_hash:
        raise DomainViolation("paper resume request hash mismatch")
    return request


def write_paper_resume_request(path: Path, request: PaperResumeRequest) -> PaperResumeRequest:
    """Write one request atomically and immutably, with no runtime apply step."""
    if paper_resume_request_content_hash(request) != request.request_hash:
        raise DomainViolation("paper resume request hash mismatch before write")
    if path.exists():
        existing = read_paper_resume_request(path)
        if existing != request:
            raise DomainViolation("paper resume request path is immutable")
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    descriptor_open = True
    try:
        payload = json.dumps(request.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor_open = False
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError:
            existing = read_paper_resume_request(path)
            if existing != request:
                raise DomainViolation("paper resume request path is immutable") from None
            return existing
        return read_paper_resume_request(path)
    finally:
        if descriptor_open:
            os.close(file_descriptor)
        Path(temporary_name).unlink(missing_ok=True)


__all__ = [
    "MAX_PREFLIGHT_AGE",
    "MAX_REQUEST_LIFETIME",
    "BreakerState",
    "PaperRecoveryPreflight",
    "PaperResumeRequest",
    "build_paper_resume_request",
    "capture_paper_recovery_preflight",
    "paper_resume_request_content_hash",
    "read_paper_resume_request",
    "write_paper_resume_request",
]
