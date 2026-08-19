"""Bounded read-only testnet account observation bound to lifecycle evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .domain.contracts import DomainModel
from .testnet_audit import TestnetLifecycleEvidence


class TestnetAccountObservationInput(DomainModel):
    asset_count: int = Field(ge=0, strict=True)
    nonzero_position_count: int = Field(ge=0, strict=True)


class TestnetObservation(DomainModel):
    observation_id: str = Field(pattern=r"^observation-testnet-[A-Za-z0-9._-]+$")
    observed_at: datetime
    audit_id: str
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["stable", "drift"]
    asset_count: int = Field(ge=0, strict=True)
    nonzero_position_count: int = Field(ge=0, strict=True)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    live_enabled: Literal[False] = False
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("testnet observation timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def hash_is_valid(self) -> TestnetObservation:
        if self.observation_hash != hash_testnet_observation(self):
            raise ValueError("testnet observation hash mismatch")
        return self


def hash_testnet_observation(observation: TestnetObservation) -> str:
    payload = observation.model_dump(mode="json", exclude={"observation_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def capture_testnet_observation(
    evidence: TestnetLifecycleEvidence,
    account: TestnetAccountObservationInput,
    *,
    observation_id: str,
    observed_at: datetime,
) -> TestnetObservation:
    reasons: list[str] = []
    if evidence.audit.status != "reconciled":
        reasons.append("audit_not_reconciled")
    if account.nonzero_position_count:
        reasons.append("nonzero_position_detected")
    observation = TestnetObservation.model_construct(
        observation_id=observation_id,
        observed_at=observed_at,
        audit_id=evidence.audit_id,
        audit_hash=evidence.evidence_hash,
        status="drift" if reasons else "stable",
        asset_count=account.asset_count,
        nonzero_position_count=account.nonzero_position_count,
        reason_codes=tuple(sorted(reasons)) if reasons else ("testnet_observation_stable",),
        paper_activation=False,
        execution_authority=False,
        live_enabled=False,
        observation_hash="0" * 64,
    )
    return TestnetObservation.model_validate(
        {
            **observation.model_dump(mode="python"),
            "observation_hash": hash_testnet_observation(observation),
        }
    )


class SqliteTestnetObservations:
    """Caller-owned write-once journal for bounded testnet observations."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS testnet_observations (
                sequence INTEGER PRIMARY KEY,
                observation_id TEXT NOT NULL UNIQUE,
                observed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'testnet_observations'"
        ).fetchone()
        return row is not None

    def append(self, observation: TestnetObservation) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM testnet_observations WHERE observation_id = ?",
                (observation.observation_id,),
            ).fetchone()
            if existing is not None:
                stored = TestnetObservation.model_validate_json(existing[0])
                if stored != observation:
                    raise ValueError("conflicting observation ID")
                return
            connection.execute(
                """
                INSERT INTO testnet_observations (
                    observation_id, observed_at, payload
                ) VALUES (?, ?, ?)
                """,
                (
                    observation.observation_id,
                    observation.observed_at.isoformat(),
                    observation.model_dump_json(),
                ),
            )

    def get(self, observation_id: str) -> TestnetObservation | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM testnet_observations WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        return None if row is None else TestnetObservation.model_validate_json(row[0])

    def read(self) -> tuple[TestnetObservation, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM testnet_observations ORDER BY sequence"
            ).fetchall()
        return tuple(TestnetObservation.model_validate_json(row[0]) for row in rows)
