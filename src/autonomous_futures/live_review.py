"""Offline live activation review record; never activates live access."""

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


class LiveActivationReview(DomainModel):
    review_id: str = Field(pattern=r"^review-live-[A-Za-z0-9._-]+$")
    reviewed_by: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    reviewed_at: datetime
    expires_at: datetime
    decision: Literal["approve_live_design", "needs_attention", "reject"]
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    testnet_completion_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    legal_review_confirmed: bool
    venue_account_confirmed: bool
    capital_risk_confirmed: bool
    secret_manager_confirmed: bool
    kill_switch_confirmed: bool
    reconciliation_clean: bool
    symbol_approved: bool
    explicit_live_activation: bool
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    max_quote_notional: StrictPositiveDecimal
    max_daily_loss_quote: StrictPositiveDecimal
    state: Literal["reviewed_not_activated"] = "reviewed_not_activated"
    live_enabled: Literal[False] = False
    network_allowed: Literal[False] = False
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("reviewed_at", "expires_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("live review timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def review_is_valid(self) -> LiveActivationReview:
        if self.expires_at <= self.reviewed_at:
            raise ValueError("expires_at must be after reviewed_at")
        if self.review_hash != hash_live_activation_review(self):
            raise ValueError("live review hash mismatch")
        if self.decision == "approve_live_design":
            gates = (
                (self.legal_review_confirmed, "legal_review"),
                (self.venue_account_confirmed, "venue_account"),
                (self.capital_risk_confirmed, "capital_risk"),
                (self.secret_manager_confirmed, "secret_manager"),
                (self.kill_switch_confirmed, "kill_switch"),
                (self.reconciliation_clean, "reconciliation"),
                (self.symbol_approved, "symbol"),
                (self.explicit_live_activation, "explicit_activation"),
            )
            missing = tuple(name for confirmed, name in gates if not confirmed)
            if missing:
                raise ValueError(f"missing live gate: {','.join(missing)}")
        return self


def hash_live_activation_review(review: LiveActivationReview) -> str:
    payload = review.model_dump(mode="json", exclude={"review_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def create_live_activation_review(
    *,
    review_id: str,
    reviewed_by: str,
    reviewed_at: datetime,
    expires_at: datetime,
    decision: Literal["approve_live_design", "needs_attention", "reject"],
    candidate_id: str,
    candidate_artifact_hash: str,
    testnet_completion_hash: str,
    legal_review_confirmed: bool,
    venue_account_confirmed: bool,
    capital_risk_confirmed: bool,
    secret_manager_confirmed: bool,
    kill_switch_confirmed: bool,
    reconciliation_clean: bool,
    symbol_approved: bool,
    explicit_live_activation: bool,
    symbol: str,
    max_quote_notional: Decimal,
    max_daily_loss_quote: Decimal,
) -> LiveActivationReview:
    review = LiveActivationReview.model_construct(
        review_id=review_id,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        expires_at=expires_at,
        decision=decision,
        candidate_id=candidate_id,
        candidate_artifact_hash=candidate_artifact_hash,
        testnet_completion_hash=testnet_completion_hash,
        legal_review_confirmed=legal_review_confirmed,
        venue_account_confirmed=venue_account_confirmed,
        capital_risk_confirmed=capital_risk_confirmed,
        secret_manager_confirmed=secret_manager_confirmed,
        kill_switch_confirmed=kill_switch_confirmed,
        reconciliation_clean=reconciliation_clean,
        symbol_approved=symbol_approved,
        explicit_live_activation=explicit_live_activation,
        symbol=symbol,
        max_quote_notional=max_quote_notional,
        max_daily_loss_quote=max_daily_loss_quote,
        state="reviewed_not_activated",
        live_enabled=False,
        network_allowed=False,
        review_hash="0" * 64,
    )
    return LiveActivationReview.model_validate(
        {**review.model_dump(mode="python"), "review_hash": hash_live_activation_review(review)}
    )


class SqliteLiveActivationReviews:
    """Caller-owned write-once journal for offline live design reviews."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect_for_append(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_activation_reviews (
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
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'live_activation_reviews'"
        ).fetchone()
        return row is not None

    def append(self, review: LiveActivationReview) -> None:
        with self._connect_for_append() as connection:
            existing = connection.execute(
                "SELECT payload FROM live_activation_reviews WHERE review_id = ?",
                (review.review_id,),
            ).fetchone()
            if existing is not None:
                stored = LiveActivationReview.model_validate_json(existing[0])
                if stored != review:
                    raise ValueError("conflicting live review ID")
                return
            connection.execute(
                """
                INSERT INTO live_activation_reviews (
                    review_id, reviewed_at, payload
                ) VALUES (?, ?, ?)
                """,
                (review.review_id, review.reviewed_at.isoformat(), review.model_dump_json()),
            )

    def get(self, review_id: str) -> LiveActivationReview | None:
        if not self._path.exists():
            return None
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return None
            row = connection.execute(
                "SELECT payload FROM live_activation_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return None if row is None else LiveActivationReview.model_validate_json(row[0])

    def read(self) -> tuple[LiveActivationReview, ...]:
        if not self._path.exists():
            return ()
        with sqlite3.connect(self._path) as connection:
            if not self._has_table(connection):
                return ()
            rows = connection.execute(
                "SELECT payload FROM live_activation_reviews ORDER BY sequence"
            ).fetchall()
        return tuple(LiveActivationReview.model_validate_json(row[0]) for row in rows)
