"""Immutable durable evidence for one bounded testnet lifecycle audit."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from .domain.contracts import DomainModel
from .testnet_lifecycle import TestnetLifecycleAudit, TestnetOrderRecord


class TestnetLifecycleEvidence(DomainModel):
    audit_id: str = Field(pattern=r"^audit-testnet-[A-Za-z0-9._-]+$")
    recorded_at: datetime
    open_order: TestnetOrderRecord
    close_order: TestnetOrderRecord
    pre_open_nonzero_positions: int = Field(ge=0, strict=True)
    post_close_nonzero_positions: int = Field(ge=0, strict=True)
    audit: TestnetLifecycleAudit
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    paper_activation: bool = False
    execution_authority: bool = False
    exchange_access: bool = True
    live_enabled: bool = False

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("testnet evidence timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bindings_are_consistent(self) -> TestnetLifecycleEvidence:
        if self.audit.open_order_id != self.open_order.order_id:
            raise ValueError("testnet evidence open order binding mismatch")
        if self.audit.close_order_id != self.close_order.order_id:
            raise ValueError("testnet evidence close order binding mismatch")
        if self.evidence_hash != hash_testnet_lifecycle_evidence(self):
            raise ValueError("testnet evidence hash mismatch")
        return self


def hash_testnet_lifecycle_evidence(evidence: TestnetLifecycleEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"evidence_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_testnet_lifecycle_evidence(
    open_order: TestnetOrderRecord,
    close_order: TestnetOrderRecord,
    *,
    pre_open_nonzero_positions: int,
    post_close_nonzero_positions: int,
    audit: TestnetLifecycleAudit,
    audit_id: str,
    recorded_at: datetime,
) -> TestnetLifecycleEvidence:
    evidence = TestnetLifecycleEvidence.model_construct(
        audit_id=audit_id,
        recorded_at=recorded_at,
        open_order=open_order,
        close_order=close_order,
        pre_open_nonzero_positions=pre_open_nonzero_positions,
        post_close_nonzero_positions=post_close_nonzero_positions,
        audit=audit,
        evidence_hash="0" * 64,
        paper_activation=False,
        execution_authority=False,
        exchange_access=True,
        live_enabled=False,
    )
    return TestnetLifecycleEvidence.model_validate(
        {
            **evidence.model_dump(mode="python"),
            "evidence_hash": hash_testnet_lifecycle_evidence(evidence),
        }
    )


class SqliteTestnetLifecycleEvidence:
    """Caller-owned append-only evidence journal with conflict-safe write-once IDs."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS testnet_lifecycle_evidence (
                sequence INTEGER PRIMARY KEY,
                audit_id TEXT NOT NULL UNIQUE,
                recorded_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'testnet_lifecycle_evidence'"
        ).fetchone()
        return row is not None

    def append(self, evidence: TestnetLifecycleEvidence) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM testnet_lifecycle_evidence WHERE audit_id = ?",
                (evidence.audit_id,),
            ).fetchone()
            if existing is not None:
                stored = TestnetLifecycleEvidence.model_validate_json(existing[0])
                if stored != evidence:
                    raise ValueError("conflicting audit ID")
                return
            connection.execute(
                """
                INSERT INTO testnet_lifecycle_evidence (
                    audit_id, recorded_at, payload
                ) VALUES (?, ?, ?)
                """,
                (
                    evidence.audit_id,
                    evidence.recorded_at.isoformat(),
                    evidence.model_dump_json(),
                ),
            )

    def get(self, audit_id: str) -> TestnetLifecycleEvidence | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM testnet_lifecycle_evidence WHERE audit_id = ?",
                (audit_id,),
            ).fetchone()
        return None if row is None else TestnetLifecycleEvidence.model_validate_json(row[0])

    def read(self) -> tuple[TestnetLifecycleEvidence, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM testnet_lifecycle_evidence ORDER BY sequence"
            ).fetchall()
        return tuple(TestnetLifecycleEvidence.model_validate_json(row[0]) for row in rows)
