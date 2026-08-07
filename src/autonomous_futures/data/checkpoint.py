from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .builder import INTERVAL_MS, KlineInterval


class BackfillCheckpoint(DomainModel):
    checkpoint_version: Literal[1] = 1
    status: Literal["running", "complete"] = "running"
    job_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    interval: KlineInterval
    range_start_ms: int = Field(ge=0)
    range_end_exclusive: int = Field(gt=0)
    next_start_ms: int = Field(ge=0)
    completed_windows: tuple[tuple[int, int], ...]
    updated_at: datetime
    completed_at: datetime | None = None
    artifact_relative_path: str | None = None
    manifest_relative_path: str | None = None
    checkpoint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_progress(self) -> BackfillCheckpoint:
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        if self.completed_at is not None and (
            self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None
        ):
            raise ValueError("completed_at must be timezone-aware")
        completion_fields = (
            self.completed_at,
            self.artifact_relative_path,
            self.manifest_relative_path,
        )
        if self.status == "complete":
            if any(value is None for value in completion_fields):
                raise ValueError("complete checkpoint requires completion metadata")
            if self.next_start_ms != self.range_end_exclusive:
                raise ValueError("complete checkpoint must cover the full range")
        elif any(value is not None for value in completion_fields):
            raise ValueError("running checkpoint cannot contain completion metadata")
        interval_ms = INTERVAL_MS[self.interval]
        for value, field in (
            (self.range_start_ms, "range_start_ms"),
            (self.range_end_exclusive, "range_end_exclusive"),
            (self.next_start_ms, "next_start_ms"),
        ):
            if value % interval_ms != 0:
                raise ValueError(f"{field} must align to interval")
        if self.range_end_exclusive <= self.range_start_ms:
            raise ValueError("range_end_exclusive must be after range_start_ms")
        if not self.range_start_ms <= self.next_start_ms <= self.range_end_exclusive:
            raise ValueError("next_start_ms must stay within the requested range")

        expected_start = self.range_start_ms
        for window_start, window_end in self.completed_windows:
            if window_start != expected_start:
                raise ValueError("completed windows must be contiguous")
            if window_end <= window_start or window_end > self.range_end_exclusive:
                raise ValueError("completed window bounds are invalid")
            if window_start % interval_ms or window_end % interval_ms:
                raise ValueError("completed window bounds must align to interval")
            expected_start = window_end
        if expected_start != self.next_start_ms:
            raise ValueError("next_start_ms must equal the end of completed windows")
        return self


def _checkpoint_content_hash(checkpoint: BackfillCheckpoint) -> str:
    payload = checkpoint.model_dump(mode="json", exclude={"checkpoint_hash"})
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical_json).hexdigest()


def build_checkpoint(
    *,
    job_id: str,
    symbol: str,
    interval: KlineInterval,
    range_start_ms: int,
    range_end_exclusive: int,
    next_start_ms: int,
    completed_windows: tuple[tuple[int, int], ...],
    updated_at: datetime,
    status: Literal["running", "complete"] = "running",
    completed_at: datetime | None = None,
    artifact_relative_path: str | None = None,
    manifest_relative_path: str | None = None,
) -> BackfillCheckpoint:
    provisional = BackfillCheckpoint(
        job_id=job_id,
        status=status,
        symbol=symbol,
        interval=interval,
        range_start_ms=range_start_ms,
        range_end_exclusive=range_end_exclusive,
        next_start_ms=next_start_ms,
        completed_windows=completed_windows,
        updated_at=updated_at.astimezone(UTC),
        completed_at=completed_at.astimezone(UTC) if completed_at is not None else None,
        artifact_relative_path=artifact_relative_path,
        manifest_relative_path=manifest_relative_path,
        checkpoint_hash="0" * 64,
    )
    return provisional.model_copy(update={"checkpoint_hash": _checkpoint_content_hash(provisional)})


def complete_checkpoint(
    checkpoint: BackfillCheckpoint,
    *,
    artifact_relative_path: str,
    manifest_relative_path: str,
    completed_at: datetime,
) -> BackfillCheckpoint:
    if checkpoint.status == "complete":
        if (
            checkpoint.artifact_relative_path != artifact_relative_path
            or checkpoint.manifest_relative_path != manifest_relative_path
        ):
            raise DomainViolation("completed checkpoint artifact binding is immutable")
        return checkpoint
    if checkpoint.next_start_ms != checkpoint.range_end_exclusive:
        raise DomainViolation("cannot complete an unfinished checkpoint")
    return build_checkpoint(
        job_id=checkpoint.job_id,
        symbol=checkpoint.symbol,
        interval=checkpoint.interval,
        range_start_ms=checkpoint.range_start_ms,
        range_end_exclusive=checkpoint.range_end_exclusive,
        next_start_ms=checkpoint.next_start_ms,
        completed_windows=checkpoint.completed_windows,
        updated_at=completed_at,
        status="complete",
        completed_at=completed_at,
        artifact_relative_path=artifact_relative_path,
        manifest_relative_path=manifest_relative_path,
    )


def read_checkpoint(path: Path) -> BackfillCheckpoint:
    checkpoint = BackfillCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))
    if _checkpoint_content_hash(checkpoint) != checkpoint.checkpoint_hash:
        raise DomainViolation(f"checkpoint hash mismatch: {path}")
    return checkpoint


def _same_scope(left: BackfillCheckpoint, right: BackfillCheckpoint) -> bool:
    return (
        left.job_id,
        left.symbol,
        left.interval,
        left.range_start_ms,
        left.range_end_exclusive,
    ) == (
        right.job_id,
        right.symbol,
        right.interval,
        right.range_start_ms,
        right.range_end_exclusive,
    )


def write_checkpoint(path: Path, checkpoint: BackfillCheckpoint) -> BackfillCheckpoint:
    if path.exists():
        existing = read_checkpoint(path)
        if existing.status == "complete":
            if existing != checkpoint:
                raise DomainViolation(f"completed checkpoint is immutable: {path}")
            return existing
        if not _same_scope(existing, checkpoint):
            raise DomainViolation(f"checkpoint scope mismatch: {path}")
        if checkpoint.next_start_ms < existing.next_start_ms:
            raise DomainViolation(f"checkpoint progress would regress: {path}")
        if checkpoint.next_start_ms == existing.next_start_ms:
            if checkpoint.completed_windows != existing.completed_windows:
                raise DomainViolation(f"checkpoint progress conflicts: {path}")
            if checkpoint.status == "running":
                return existing
        if (
            checkpoint.completed_windows[: len(existing.completed_windows)]
            != existing.completed_windows
        ):
            raise DomainViolation(f"checkpoint progress is not append-only: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            checkpoint.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)
    return checkpoint


__all__ = [
    "BackfillCheckpoint",
    "build_checkpoint",
    "complete_checkpoint",
    "read_checkpoint",
    "write_checkpoint",
]
