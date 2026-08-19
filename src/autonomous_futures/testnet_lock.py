"""Hard post-freeze lock for new testnet actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator

from .domain.contracts import DomainModel
from .testnet_freeze import TestnetEvidenceReview


class TestnetExecutionLock(DomainModel):
    lock_id: str = Field(pattern=r"^lock-testnet-[A-Za-z0-9._-]+$")
    review_id: str
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locked_at: datetime
    new_actions_allowed: Literal[False] = False
    live_enabled: Literal[False] = False
    reason_codes: tuple[str, ...] = ("testnet_evidence_frozen",)

    @field_validator("locked_at")
    @classmethod
    def locked_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("testnet lock timestamp must be timezone-aware UTC")
        return value.astimezone(UTC)


def freeze_testnet_evidence(
    review: TestnetEvidenceReview,
    *,
    locked_at: datetime,
) -> TestnetExecutionLock:
    if review.decision != "accept_testnet_observation":
        raise ValueError("only accepted testnet observation evidence can be frozen")
    return TestnetExecutionLock(
        lock_id=f"lock-testnet-{review.review_id.removeprefix('review-testnet-')}",
        review_id=review.review_id,
        review_hash=review.review_hash,
        locked_at=locked_at,
    )


def require_testnet_action_unlocked(
    lock: TestnetExecutionLock,
    *,
    action: str,
) -> None:
    del action
    if not lock.new_actions_allowed:
        raise ValueError("new testnet actions blocked by frozen testnet evidence")
