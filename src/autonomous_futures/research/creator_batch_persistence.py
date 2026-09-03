"""Write-once persistence for bounded Creator batch trial outcomes."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_batch import CreatorBatchResult, CreatorBatchTrial


class CreatorBatchTrialEvidence(DomainModel):
    evidence_version: Literal[1] = 1
    trial: CreatorBatchTrial
    recorded_at: datetime
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("recorded_at must be timezone-aware UTC")
        return value.astimezone(UTC)


def _content_hash(evidence: CreatorBatchTrialEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"recorded_at", "evidence_hash"})
    if not evidence.trial.schema_diagnostics:
        # Preserve version-1 hashes for evidence written before diagnostics existed.
        payload["trial"].pop("schema_diagnostics", None)
    if not evidence.trial.provider_metadata:
        # Preserve version-1 hashes for evidence written before provider metadata existed.
        payload["trial"].pop("provider_metadata", None)
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_creator_batch_trial_evidence(
    trial: CreatorBatchTrial, *, recorded_at: datetime
) -> CreatorBatchTrialEvidence:
    provisional = CreatorBatchTrialEvidence(
        trial=trial,
        recorded_at=recorded_at,
        evidence_hash="0" * 64,
    )
    return provisional.model_copy(update={"evidence_hash": _content_hash(provisional)})


def read_creator_batch_trial_evidence(path: Path) -> CreatorBatchTrialEvidence:
    try:
        evidence = CreatorBatchTrialEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except ValueError as exc:
        raise DataQualityError("invalid persisted Creator batch trial evidence") from exc
    if _content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation(f"Creator batch trial evidence hash mismatch: {path}")
    return evidence


def write_creator_batch_trial_evidence(
    path: Path, evidence: CreatorBatchTrialEvidence
) -> CreatorBatchTrialEvidence:
    if _content_hash(evidence) != evidence.evidence_hash:
        raise DomainViolation("Creator batch trial evidence hash mismatch")
    if path.exists():
        existing = read_creator_batch_trial_evidence(path)
        if existing != evidence and existing.model_dump(mode="json") != evidence.model_dump(
            mode="json"
        ):
            raise DomainViolation(f"Creator batch trial evidence path is immutable: {path}")
        return existing
    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_creator_batch_trial_evidence(path)
        if existing != evidence and existing.model_dump(mode="json") != evidence.model_dump(
            mode="json"
        ):
            raise DomainViolation(
                f"Creator batch trial evidence path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_creator_batch_trial_evidence(path)


def persist_creator_batch_trials(
    result: CreatorBatchResult, *, root: Path, recorded_at: datetime
) -> tuple[CreatorBatchTrialEvidence, ...]:
    persisted: list[CreatorBatchTrialEvidence] = []
    for index, trial in enumerate(result.trials):
        evidence = build_creator_batch_trial_evidence(trial, recorded_at=recorded_at)
        path = root / f"trial-{index:04d}-{trial.research_run_id}.json"
        persisted.append(write_creator_batch_trial_evidence(path, evidence))
    return tuple(persisted)


__all__ = [
    "CreatorBatchTrialEvidence",
    "build_creator_batch_trial_evidence",
    "persist_creator_batch_trials",
    "read_creator_batch_trial_evidence",
    "write_creator_batch_trial_evidence",
]
