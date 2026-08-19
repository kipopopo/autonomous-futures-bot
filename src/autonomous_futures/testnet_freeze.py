"""Immutable human freeze review for bounded testnet lifecycle evidence."""

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
from .testnet_observation import TestnetObservation


class TestnetEvidenceReview(DomainModel):
    review_id: str = Field(pattern=r"^review-testnet-[A-Za-z0-9._-]+$")
    reviewer_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    reviewed_at: datetime
    decision: Literal["accept_testnet_observation", "needs_attention", "reject"]
    review_notes: str = Field(min_length=1, max_length=2000)
    audit_id: str
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_id: str
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit: TestnetLifecycleEvidence
    observation: TestnetObservation
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    live_enabled: Literal[False] = False

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("testnet review timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bindings_and_hash_are_valid(self) -> TestnetEvidenceReview:
        if self.audit_id != self.audit.audit_id or self.audit_hash != self.audit.evidence_hash:
            raise ValueError("testnet review audit binding mismatch")
        if self.observation_id != self.observation.observation_id:
            raise ValueError("testnet review observation binding mismatch")
        if self.observation_hash != self.observation.observation_hash:
            raise ValueError("testnet review observation hash mismatch")
        if self.review_hash != hash_testnet_evidence_review(self):
            raise ValueError("testnet review hash mismatch")
        if self.decision == "accept_testnet_observation" and (
            self.audit.audit.status != "reconciled"
            or self.observation.status != "stable"
            or self.observation.nonzero_position_count != 0
        ):
            raise ValueError("acceptance requires stable flat testnet observation")
        return self


def hash_testnet_evidence_review(review: TestnetEvidenceReview) -> str:
    payload = review.model_dump(mode="json", exclude={"review_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_testnet_evidence_review(
    audit: TestnetLifecycleEvidence,
    observation: TestnetObservation,
    *,
    review_id: str,
    reviewer_id: str,
    reviewed_at: datetime,
    decision: Literal["accept_testnet_observation", "needs_attention", "reject"],
    review_notes: str,
) -> TestnetEvidenceReview:
    review = TestnetEvidenceReview.model_construct(
        review_id=review_id,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        decision=decision,
        review_notes=review_notes,
        audit_id=audit.audit_id,
        audit_hash=audit.evidence_hash,
        observation_id=observation.observation_id,
        observation_hash=observation.observation_hash,
        audit=audit,
        observation=observation,
        review_hash="0" * 64,
        paper_activation=False,
        execution_authority=False,
        live_enabled=False,
    )
    return TestnetEvidenceReview.model_validate(
        {**review.model_dump(mode="python"), "review_hash": hash_testnet_evidence_review(review)}
    )


class SqliteTestnetEvidenceReviews:
    """Caller-owned write-once journal for testnet evidence freeze reviews."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS testnet_evidence_reviews (
                sequence INTEGER PRIMARY KEY,
                review_id TEXT NOT NULL UNIQUE,
                reviewed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'testnet_evidence_reviews'"
        ).fetchone()
        return row is not None

    def append(self, review: TestnetEvidenceReview) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM testnet_evidence_reviews WHERE review_id = ?",
                (review.review_id,),
            ).fetchone()
            if existing is not None:
                stored = TestnetEvidenceReview.model_validate_json(existing[0])
                if stored != review:
                    raise ValueError("conflicting testnet review ID")
                return
            connection.execute(
                """
                INSERT INTO testnet_evidence_reviews (
                    review_id, reviewed_at, payload
                ) VALUES (?, ?, ?)
                """,
                (review.review_id, review.reviewed_at.isoformat(), review.model_dump_json()),
            )

    def get(self, review_id: str) -> TestnetEvidenceReview | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM testnet_evidence_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return None if row is None else TestnetEvidenceReview.model_validate_json(row[0])

    def read(self) -> tuple[TestnetEvidenceReview, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM testnet_evidence_reviews ORDER BY sequence"
            ).fetchall()
        return tuple(TestnetEvidenceReview.model_validate_json(row[0]) for row in rows)
