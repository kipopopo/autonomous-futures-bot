"""Offline one-shot live activation token; never enables network access."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .domain.contracts import DomainModel, StrictPositiveDecimal
from .live_review import LiveActivationReview


class LiveActivationToken(DomainModel):
    token_id: str = Field(pattern=r"^token-live-[A-Za-z0-9._-]+$")
    review_id: str = Field(pattern=r"^review-live-[A-Za-z0-9._-]+$")
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    issued_at: datetime
    expires_at: datetime
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    max_quote_notional_pct: StrictPositiveDecimal
    max_capital_at_risk_pct: StrictPositiveDecimal
    max_daily_loss_pct: StrictPositiveDecimal
    remaining_uses: int = Field(ge=0, le=1, strict=True)
    state: Literal["issued_not_enabled"] = "issued_not_enabled"
    live_enabled: Literal[False] = False
    network_allowed: Literal[False] = False
    token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("issued_at", "expires_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("live token timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def token_is_valid(self) -> LiveActivationToken:
        if self.expires_at <= self.issued_at:
            raise ValueError("token expiry must be after issuance")
        if self.token_hash != hash_live_activation_token(self):
            raise ValueError("live token hash mismatch")
        return self


def hash_live_activation_token(token: LiveActivationToken) -> str:
    payload = token.model_dump(mode="json", exclude={"token_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def issue_live_activation_token(
    review: LiveActivationReview,
    *,
    token_id: str,
    issued_at: datetime,
    expires_at: datetime,
) -> LiveActivationToken:
    if review.decision != "approve_live_design":
        raise ValueError("live review is not approved")
    if review.state != "reviewed_not_activated":
        raise ValueError("live review state is not eligible")
    if expires_at > review.expires_at:
        raise ValueError("token expiry exceeds live review expiry")
    token = LiveActivationToken.model_construct(
        token_id=token_id,
        review_id=review.review_id,
        review_hash=review.review_hash,
        issued_at=issued_at,
        expires_at=expires_at,
        symbol=review.symbol,
        max_quote_notional_pct=review.max_quote_notional_pct,
        max_capital_at_risk_pct=review.max_capital_at_risk_pct,
        max_daily_loss_pct=review.max_daily_loss_pct,
        remaining_uses=1,
        state="issued_not_enabled",
        live_enabled=False,
        network_allowed=False,
        token_hash="0" * 64,
    )
    return LiveActivationToken.model_validate(
        {**token.model_dump(mode="python"), "token_hash": hash_live_activation_token(token)}
    )


class SqliteLiveActivationTokens:
    """Caller-owned write-once journal for offline live activation tokens."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_activation_tokens (
                sequence INTEGER PRIMARY KEY,
                token_id TEXT NOT NULL UNIQUE,
                issued_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _has_table(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'live_activation_tokens'"
        ).fetchone()
        return row is not None

    def append(self, token: LiveActivationToken) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM live_activation_tokens WHERE token_id = ?",
                (token.token_id,),
            ).fetchone()
            if existing is not None:
                stored = LiveActivationToken.model_validate_json(existing[0])
                if stored != token:
                    raise ValueError("conflicting live token ID")
                return
            connection.execute(
                """
                INSERT INTO live_activation_tokens (
                    token_id, issued_at, payload
                ) VALUES (?, ?, ?)
                """,
                (token.token_id, token.issued_at.isoformat(), token.model_dump_json()),
            )

    def get(self, token_id: str) -> LiveActivationToken | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM live_activation_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
        return None if row is None else LiveActivationToken.model_validate_json(row[0])

    def read(self) -> tuple[LiveActivationToken, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM live_activation_tokens ORDER BY sequence"
            ).fetchall()
        return tuple(LiveActivationToken.model_validate_json(row[0]) for row in rows)
