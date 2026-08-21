"""Final live-order review record; never enables order transport."""

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
from .live_activation import LiveActivationToken
from .live_evidence import LiveReadOnlyEvidence


class LiveOrderActivationReview(DomainModel):
    review_id: str = Field(pattern=r"^review-order-live-[A-Za-z0-9._-]+$")
    reviewed_at: datetime
    expires_at: datetime
    reviewed_by: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    decision: Literal["approve_one_live_lifecycle", "reject"]
    token_id: str
    token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_id: str
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    max_quote_notional_pct: StrictPositiveDecimal
    max_capital_at_risk_pct: StrictPositiveDecimal
    max_daily_loss_pct: StrictPositiveDecimal
    max_leverage: StrictPositiveDecimal
    max_open_positions: int = Field(gt=0, strict=True)
    state: Literal["reviewed_not_enabled"] = "reviewed_not_enabled"
    live_order_enabled: Literal[False] = False
    network_allowed: Literal[False] = False
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("reviewed_at", "expires_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("order review timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def review_is_valid(self) -> LiveOrderActivationReview:
        if self.expires_at <= self.reviewed_at:
            raise ValueError("order review expiry must be after review time")
        if self.review_hash != hash_live_order_activation_review(self):
            raise ValueError("order review hash mismatch")
        return self


def hash_live_order_activation_review(review: LiveOrderActivationReview) -> str:
    payload = review.model_dump(mode="json", exclude={"review_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_live_order_activation_review(
    token: LiveActivationToken,
    evidence: LiveReadOnlyEvidence,
    *,
    review_id: str,
    reviewed_at: datetime,
    expires_at: datetime,
    reviewed_by: str,
    decision: Literal["approve_one_live_lifecycle", "reject"],
) -> LiveOrderActivationReview:
    if evidence.token_id != token.token_id or evidence.token_hash != token.token_hash:
        raise ValueError("read-only evidence token binding drift")
    if evidence.status != "reconciled" or evidence.nonzero_position_count != 0:
        raise ValueError("evidence is not reconciled and flat")
    if expires_at > token.expires_at:
        raise ValueError("order review expiry exceeds token expiry")
    review = LiveOrderActivationReview.model_construct(
        review_id=review_id,
        reviewed_at=reviewed_at,
        expires_at=expires_at,
        reviewed_by=reviewed_by,
        decision=decision,
        token_id=token.token_id,
        token_hash=token.token_hash,
        evidence_id=evidence.evidence_id,
        evidence_hash=evidence.evidence_hash,
        symbol=token.symbol,
        max_quote_notional_pct=token.max_quote_notional_pct,
        max_capital_at_risk_pct=token.max_capital_at_risk_pct,
        max_daily_loss_pct=token.max_daily_loss_pct,
        max_leverage=Decimal("1"),
        max_open_positions=1,
        state="reviewed_not_enabled",
        live_order_enabled=False,
        network_allowed=False,
        review_hash="0" * 64,
    )
    return LiveOrderActivationReview.model_validate(
        {
            **review.model_dump(mode="python"),
            "review_hash": hash_live_order_activation_review(review),
        }
    )


class SqliteLiveOrderActivationReviews:
    """Caller-owned write-once journal for final live-order reviews."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_order_activation_reviews (
                sequence INTEGER PRIMARY KEY,
                review_id TEXT NOT NULL UNIQUE,
                reviewed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection

    def append(self, review: LiveOrderActivationReview) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM live_order_activation_reviews WHERE review_id = ?",
                (review.review_id,),
            ).fetchone()
            if existing is not None:
                stored = LiveOrderActivationReview.model_validate_json(existing[0])
                if stored != review:
                    raise ValueError("conflicting live order review ID")
                return
            connection.execute(
                """
                INSERT INTO live_order_activation_reviews (
                    review_id, reviewed_at, payload
                ) VALUES (?, ?, ?)
                """,
                (review.review_id, review.reviewed_at.isoformat(), review.model_dump_json()),
            )

    def get(self, review_id: str) -> LiveOrderActivationReview | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            row = connection.execute(
                "SELECT payload FROM live_order_activation_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return None if row is None else LiveOrderActivationReview.model_validate_json(row[0])
