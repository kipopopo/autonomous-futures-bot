"""Bounded testnet designation that remains explicitly non-activated."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .domain.contracts import DomainModel, StrictPositiveDecimal
from .testnet_freeze import TestnetEvidenceReview


class TestnetActivationDesignation(DomainModel):
    designation_id: str = Field(pattern=r"^designation-testnet-[A-Za-z0-9._-]+$")
    review_id: str
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    designated_by: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    designated_at: datetime
    expires_at: datetime
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    max_quote_notional: StrictPositiveDecimal
    max_open_positions: Literal[1] = 1
    state: Literal["designated_not_activated"] = "designated_not_activated"
    new_actions_allowed: Literal[False] = False
    live_enabled: Literal[False] = False
    designation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("designated_at", "expires_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("designation timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bindings_are_valid(self) -> TestnetActivationDesignation:
        if self.expires_at <= self.designated_at:
            raise ValueError("expires_at must be after designated_at")
        if self.designation_hash != hash_testnet_activation_designation(self):
            raise ValueError("designation hash mismatch")
        return self


def hash_testnet_activation_designation(designation: TestnetActivationDesignation) -> str:
    payload = designation.model_dump(mode="json", exclude={"designation_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_testnet_activation_designation(
    review: TestnetEvidenceReview,
    *,
    designation_id: str,
    designated_by: str,
    designated_at: datetime,
    expires_at: datetime,
    symbol: str,
    max_quote_notional: Decimal,
) -> TestnetActivationDesignation:
    if review.decision != "accept_testnet_observation":
        raise ValueError("activation designation requires accepted testnet evidence review")
    if review.audit.open_order.symbol != symbol or review.audit.close_order.symbol != symbol:
        raise ValueError("designation symbol does not match frozen lifecycle evidence")
    designation = TestnetActivationDesignation.model_construct(
        designation_id=designation_id,
        review_id=review.review_id,
        review_hash=review.review_hash,
        designated_by=designated_by,
        designated_at=designated_at,
        expires_at=expires_at,
        symbol=symbol,
        max_quote_notional=max_quote_notional,
        max_open_positions=1,
        state="designated_not_activated",
        new_actions_allowed=False,
        live_enabled=False,
        designation_hash="0" * 64,
    )
    return TestnetActivationDesignation.model_validate(
        {
            **designation.model_dump(mode="python"),
            "designation_hash": hash_testnet_activation_designation(designation),
        }
    )


class SqliteTestnetActivationDesignations:
    """Caller-owned write-once journal for non-activated designations."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS testnet_activation_designations (
                sequence INTEGER PRIMARY KEY,
                designation_id TEXT NOT NULL UNIQUE,
                designated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'testnet_activation_designations'"
        ).fetchone()
        return row is not None

    def append(self, designation: TestnetActivationDesignation) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM testnet_activation_designations WHERE designation_id = ?",
                (designation.designation_id,),
            ).fetchone()
            if existing is not None:
                stored = TestnetActivationDesignation.model_validate_json(existing[0])
                if stored != designation:
                    raise ValueError("conflicting designation ID")
                return
            connection.execute(
                """
                INSERT INTO testnet_activation_designations (
                    designation_id, designated_at, payload
                ) VALUES (?, ?, ?)
                """,
                (
                    designation.designation_id,
                    designation.designated_at.isoformat(),
                    designation.model_dump_json(),
                ),
            )

    def get(self, designation_id: str) -> TestnetActivationDesignation | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM testnet_activation_designations WHERE designation_id = ?",
                (designation_id,),
            ).fetchone()
        return None if row is None else TestnetActivationDesignation.model_validate_json(row[0])

    def read(self) -> tuple[TestnetActivationDesignation, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM testnet_activation_designations ORDER BY sequence"
            ).fetchall()
        return tuple(TestnetActivationDesignation.model_validate_json(row[0]) for row in rows)
