from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from .learner_artifacts import LearnerArtifact
from .learner_inputs import LearnerInputWindow

LearnerRunState = Literal["prepared"]


class LearnerRun(DomainModel):
    """Prepared learner-run provenance; it is not a completed training result."""

    run_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    learner_version: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    learner_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_window_ids: tuple[str, ...] = Field(min_length=1)
    input_symbols: tuple[str, ...] = Field(min_length=1)
    feature_ids: tuple[str, ...] = Field(min_length=1)
    training_window_start: datetime
    training_window_end: datetime
    status: LearnerRunState = "prepared"
    output_artifact_hash: None = None
    training_metrics: None = None
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    prepared_at: datetime
    run_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("training_window_start", "training_window_end", "prepared_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("learner run timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("input_window_ids")
    @classmethod
    def input_window_ids_are_sorted_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("learner input window IDs must be non-empty")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("learner input window IDs must be sorted and unique")
        return values

    @field_validator("input_symbols")
    @classmethod
    def input_symbols_are_sorted_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.upper() for value in values):
            raise ValueError("learner input symbols must be uppercase")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("learner input symbols must be sorted and unique")
        return values

    @field_validator("feature_ids")
    @classmethod
    def feature_ids_are_sorted_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("learner run feature IDs must be non-empty")
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("learner run feature IDs must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_training_window(self) -> LearnerRun:
        if self.training_window_end <= self.training_window_start:
            raise ValueError("learner run training_window_end must be after start")
        if self.status != "prepared":
            raise ValueError("learner runs must remain prepared until a separate training contract")
        return self


def _run_content_hash(run: LearnerRun) -> str:
    payload = run.model_dump(mode="json", exclude={"prepared_at", "run_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _is_safe_run_id(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def prepare_learner_run(
    *,
    learner: LearnerArtifact,
    windows: Sequence[LearnerInputWindow],
    run_id: str,
    prepared_at: datetime,
) -> LearnerRun:
    """Create deterministic prepared provenance from causal input windows only."""
    if not _is_safe_run_id(run_id):
        raise DataQualityError(
            "run_id must contain only letters, digits, dots, dashes, or underscores"
        )
    if not windows:
        raise DataQualityError("prepared learner run requires at least one input window")
    if prepared_at.tzinfo is None or prepared_at.utcoffset() != UTC.utcoffset(prepared_at):
        raise DataQualityError("prepared_at must be timezone-aware UTC")

    seen_ids: set[str] = set()
    first_spec = windows[0].spec
    for window in windows:
        spec = window.spec
        if spec.input_id in seen_ids:
            raise DataQualityError("learner input window IDs must be unique")
        seen_ids.add(spec.input_id)
        if spec.learner_id != learner.learner_id:
            raise DataQualityError("learner_id does not match learner artifact")
        if spec.learner_artifact_hash != learner.artifact_hash:
            raise DataQualityError("learner_artifact_hash does not match learner artifact")
        if spec.candidate_id != learner.candidate_id:
            raise DataQualityError("candidate_id does not match learner artifact")
        if spec.candidate_artifact_hash != learner.candidate_artifact_hash:
            raise DataQualityError("candidate_artifact_hash does not match learner artifact")
        if spec.bundle_hash != learner.bundle_hash:
            raise DataQualityError("bundle_hash does not match learner artifact")
        if spec.dataset_registry_hash != learner.dataset_registry_hash:
            raise DataQualityError("dataset_registry_hash does not match learner artifact")
        if spec.feature_ids != learner.feature_ids:
            raise DataQualityError("feature IDs do not match learner artifact")
        if (
            spec.primary_interval != learner.primary_interval
            or spec.context_interval != learner.context_interval
        ):
            raise DataQualityError("input intervals do not match learner artifact")
        if spec.context_feature_policy != "close_time_plus_1ms":
            raise DataQualityError("input context freshness policy is not causal")
        if spec.time_start != first_spec.time_start or spec.time_end != first_spec.time_end:
            raise DataQualityError("all learner inputs must use the same training window")

    input_symbols = tuple(sorted({window.spec.symbol for window in windows}))
    if input_symbols != learner.symbols:
        raise DataQualityError("learner input symbol coverage does not match learner universe")

    try:
        provisional = LearnerRun(
            run_id=run_id,
            learner_id=learner.learner_id,
            learner_run_id=learner.learner_run_id,
            learner_version=learner.learner_version,
            learner_artifact_hash=learner.artifact_hash,
            candidate_id=learner.candidate_id,
            candidate_artifact_hash=learner.candidate_artifact_hash,
            bundle_hash=learner.bundle_hash,
            dataset_registry_hash=learner.dataset_registry_hash,
            input_window_ids=tuple(sorted(seen_ids)),
            input_symbols=input_symbols,
            feature_ids=learner.feature_ids,
            training_window_start=first_spec.time_start,
            training_window_end=first_spec.time_end,
            prepared_at=prepared_at,
            run_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid prepared learner run: " + str(exc)) from None
    return provisional.model_copy(update={"run_hash": _run_content_hash(provisional)})


__all__ = ["LearnerRun", "LearnerRunState", "prepare_learner_run"]
