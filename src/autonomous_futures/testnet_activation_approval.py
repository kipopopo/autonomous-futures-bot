"""Explicit approval for exactly one bounded testnet lifecycle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .domain.contracts import DomainModel, StrictPositiveDecimal
from .testnet_activation import TestnetActivationDesignation


class TestnetActivationApproval(DomainModel):
    approval_id: str = Field(pattern=r"^approval-testnet-[A-Za-z0-9._-]+$")
    designation_id: str
    designation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    approved_at: datetime
    expires_at: datetime
    scope: Literal["one_open_and_reduce_only_close"]
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    max_quote_notional: StrictPositiveDecimal
    new_actions_allowed: Literal[True] = True
    live_enabled: Literal[False] = False
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("approved_at", "expires_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("approval timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bindings_are_valid(self) -> TestnetActivationApproval:
        if self.expires_at <= self.approved_at:
            raise ValueError("expires_at must be after approved_at")
        if self.approval_hash != hash_testnet_activation_approval(self):
            raise ValueError("approval hash mismatch")
        return self


def hash_testnet_activation_approval(approval: TestnetActivationApproval) -> str:
    payload = approval.model_dump(mode="json", exclude={"approval_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_testnet_activation_approval(
    designation: TestnetActivationDesignation,
    *,
    approval_id: str,
    approved_by: str,
    approved_at: datetime,
    expires_at: datetime,
) -> TestnetActivationApproval:
    if approved_at < designation.designated_at:
        raise ValueError("approved_at must be after designation time")
    if expires_at > designation.expires_at:
        raise ValueError("approval cannot exceed designation expiry")
    approval = TestnetActivationApproval.model_construct(
        approval_id=approval_id,
        designation_id=designation.designation_id,
        designation_hash=designation.designation_hash,
        approved_by=approved_by,
        approved_at=approved_at,
        expires_at=expires_at,
        scope="one_open_and_reduce_only_close",
        symbol=designation.symbol,
        max_quote_notional=designation.max_quote_notional,
        new_actions_allowed=True,
        live_enabled=False,
        approval_hash="0" * 64,
    )
    return TestnetActivationApproval.model_validate(
        {
            **approval.model_dump(mode="python"),
            "approval_hash": hash_testnet_activation_approval(approval),
        }
    )


class SqliteTestnetActivationApprovals:
    """Caller-owned write-once journal for explicit one-lifecycle approvals."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS testnet_activation_approvals (
                sequence INTEGER PRIMARY KEY,
                approval_id TEXT NOT NULL UNIQUE,
                approved_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'testnet_activation_approvals'"
        ).fetchone()
        return row is not None

    def append(self, approval: TestnetActivationApproval) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM testnet_activation_approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            if existing is not None:
                stored = TestnetActivationApproval.model_validate_json(existing[0])
                if stored != approval:
                    raise ValueError("conflicting activation approval ID")
                return
            connection.execute(
                """
                INSERT INTO testnet_activation_approvals (
                    approval_id, approved_at, payload
                ) VALUES (?, ?, ?)
                """,
                (
                    approval.approval_id,
                    approval.approved_at.isoformat(),
                    approval.model_dump_json(),
                ),
            )

    def get(self, approval_id: str) -> TestnetActivationApproval | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM testnet_activation_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return None if row is None else TestnetActivationApproval.model_validate_json(row[0])

    def read(self) -> tuple[TestnetActivationApproval, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM testnet_activation_approvals ORDER BY sequence"
            ).fetchall()
        return tuple(TestnetActivationApproval.model_validate_json(row[0]) for row in rows)
