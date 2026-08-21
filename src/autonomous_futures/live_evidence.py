"""Durable, aggregate-only evidence for one live read-only account GET."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .domain.contracts import DomainModel
from .live_activation import LiveActivationToken


class LiveReadOnlyEvidence(DomainModel):
    evidence_id: str = Field(pattern=r"^evidence-live-[A-Za-z0-9._-]+$")
    observed_at: datetime
    token_id: str
    token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    endpoint: Literal["/fapi/v3/account"] = "/fapi/v3/account"
    asset_count: int = Field(ge=0, strict=True)
    nonzero_position_count: int = Field(ge=0, strict=True)
    status: Literal["reconciled", "drift"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    network_request_count: int = Field(ge=0, strict=True)
    live_enabled: Literal[False] = False
    order_capability: Literal[False] = False
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("live evidence timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def evidence_is_valid(self) -> LiveReadOnlyEvidence:
        if self.evidence_hash != hash_live_readonly_evidence(self):
            raise ValueError("live evidence hash mismatch")
        if self.status == "reconciled" and self.nonzero_position_count != 0:
            raise ValueError("reconciled live evidence must have flat positions")
        if self.network_request_count != 1:
            raise ValueError("live evidence must contain exactly one request")
        return self


def hash_live_readonly_evidence(evidence: LiveReadOnlyEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"evidence_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def capture_live_readonly_evidence(
    token: LiveActivationToken,
    *,
    evidence_id: str,
    observed_at: datetime,
    asset_count: int,
    nonzero_position_count: int,
    status: Literal["reconciled", "drift"],
    reason_codes: tuple[str, ...],
    network_request_count: int,
) -> LiveReadOnlyEvidence:
    if network_request_count != 1:
        raise ValueError("live read-only evidence requires exactly one request")
    evidence = LiveReadOnlyEvidence.model_construct(
        evidence_id=evidence_id,
        observed_at=observed_at,
        token_id=token.token_id,
        token_hash=token.token_hash,
        endpoint="/fapi/v3/account",
        asset_count=asset_count,
        nonzero_position_count=nonzero_position_count,
        status=status,
        reason_codes=reason_codes,
        network_request_count=network_request_count,
        live_enabled=False,
        order_capability=False,
        evidence_hash="0" * 64,
    )
    return LiveReadOnlyEvidence.model_validate(
        {
            **evidence.model_dump(mode="python"),
            "evidence_hash": hash_live_readonly_evidence(evidence),
        }
    )


class SqliteLiveReadOnlyEvidence:
    """Caller-owned write-once journal for live read-only aggregates."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_readonly_evidence (
                sequence INTEGER PRIMARY KEY,
                evidence_id TEXT NOT NULL UNIQUE,
                observed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'live_readonly_evidence'"
        ).fetchone()
        return row is not None

    def append(self, evidence: LiveReadOnlyEvidence) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM live_readonly_evidence WHERE evidence_id = ?",
                (evidence.evidence_id,),
            ).fetchone()
            if existing is not None:
                stored = LiveReadOnlyEvidence.model_validate_json(existing[0])
                if stored != evidence:
                    raise ValueError("conflicting live evidence ID")
                return
            connection.execute(
                """
                INSERT INTO live_readonly_evidence (
                    evidence_id, observed_at, payload
                ) VALUES (?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.observed_at.isoformat(),
                    evidence.model_dump_json(),
                ),
            )

    def get(self, evidence_id: str) -> LiveReadOnlyEvidence | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM live_readonly_evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        return None if row is None else LiveReadOnlyEvidence.model_validate_json(row[0])

    def read(self) -> tuple[LiveReadOnlyEvidence, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM live_readonly_evidence ORDER BY sequence"
            ).fetchall()
        return tuple(LiveReadOnlyEvidence.model_validate_json(row[0]) for row in rows)
