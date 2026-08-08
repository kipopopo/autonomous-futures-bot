from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .cached_evaluation import CachedEvaluationWindow, CachedEvaluationWindowSpec
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact, verify_learner_artifact_binding
from .learner_training_evidence import (
    LearnerTrainingEvidence,
    learner_training_evidence_content_hash,
)


class LearnerQualityReviewWindowSpec(DomainModel):
    """Metadata for one explicit, cached-only holdout review window."""

    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    split: Literal["holdout"] = "holdout"
    time_start: datetime
    time_end: datetime

    @field_validator("time_start", "time_end")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("quality review timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_time_range(self) -> LearnerQualityReviewWindowSpec:
        if self.time_start >= self.time_end:
            raise ValueError("quality review time_start must be before time_end")
        return self


@dataclass(frozen=True, slots=True)
class LearnerQualityReviewWindow:
    """An isolated 5m cached frame supplied to one holdout reviewer."""

    spec: LearnerQualityReviewWindowSpec
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        cached_spec = CachedEvaluationWindowSpec(
            window_id=self.spec.window_id,
            symbol=self.spec.symbol,
            bundle_hash=self.spec.bundle_hash,
            dataset_registry_hash=self.spec.dataset_registry_hash,
            time_start=self.spec.time_start,
            time_end=self.spec.time_end,
        )
        cached_window = CachedEvaluationWindow(spec=cached_spec, frame=self.frame)
        object.__setattr__(self, "frame", cached_window.copy_frame())

    def copy_frame(self) -> pd.DataFrame:
        """Return a deep copy so reviewer code cannot mutate the source window."""
        return self.frame.copy(deep=True)


class LearnerQualityReviewMetric(DomainModel):
    """A finite metric reported by the caller-supplied holdout reviewer."""

    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    value: Decimal

    @field_validator("value")
    @classmethod
    def metric_value_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("quality review metric value must be finite")
        return value


class LearnerQualityReviewWindowResult(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    rows_evaluated: int = Field(ge=1, strict=True)
    metrics: tuple[LearnerQualityReviewMetric, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_metrics(self) -> LearnerQualityReviewWindowResult:
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(set(metric_ids)) != len(metric_ids) or metric_ids != tuple(sorted(metric_ids)):
            raise ValueError("quality review metrics must be sorted and unique")
        return self


class LearnerQualityReviewEvidence(DomainModel):
    """Immutable observation record; it does not make a qualification decision."""

    review_version: Literal[1] = 1
    review_id: str = Field(pattern=r"^quality-review-[a-z0-9][a-z0-9-]{0,63}$")
    training_evidence_id: str = Field(pattern=r"^training-evidence-[a-z0-9][a-z0-9-]{0,63}$")
    training_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    review_version_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    split: Literal["holdout"] = "holdout"
    windows: tuple[LearnerQualityReviewWindowResult, ...] = Field(min_length=1)
    status: Literal["completed"] = "completed"
    review_conclusion: Literal["observed_only"] = "observed_only"
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    reviewed_at: datetime
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("quality review reviewed_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_windows(self) -> LearnerQualityReviewEvidence:
        window_ids = tuple(window.window_id for window in self.windows)
        if len(set(window_ids)) != len(window_ids) or window_ids != tuple(sorted(window_ids)):
            raise ValueError("quality review windows must be sorted and unique")
        return self


def learner_quality_review_content_hash(evidence: LearnerQualityReviewEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"reviewed_at", "review_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


LearnerQualityReviewer = Callable[
    [LearnerArtifact, pd.DataFrame, LearnerQualityReviewWindow], LearnerQualityReviewWindowResult
]


def _is_safe_identifier(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def _verify_binding(
    *,
    training_evidence: LearnerTrainingEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> None:
    if learner_training_evidence_content_hash(training_evidence) != training_evidence.evidence_hash:
        raise DataQualityError("training evidence hash is invalid")
    try:
        verify_learner_artifact_binding(output_artifact, candidate)
    except DomainViolation as exc:
        raise DataQualityError("quality review output artifact binding is invalid") from exc
    if (
        training_evidence.output_artifact_hash != output_artifact.artifact_hash
        or training_evidence.learner_id != output_artifact.learner_id
        or training_evidence.learner_run_id != output_artifact.learner_run_id
        or training_evidence.candidate_id != output_artifact.candidate_id
        or training_evidence.candidate_artifact_hash != output_artifact.candidate_artifact_hash
        or training_evidence.bundle_hash != output_artifact.bundle_hash
        or training_evidence.dataset_registry_hash != output_artifact.dataset_registry_hash
    ):
        raise DataQualityError("quality review training evidence binding is invalid")


def execute_learner_quality_review(
    *,
    training_evidence: LearnerTrainingEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    windows: Sequence[LearnerQualityReviewWindow],
    review_run_id: str,
    review_version: str,
    reviewer: LearnerQualityReviewer,
    reviewed_at: datetime,
) -> LearnerQualityReviewEvidence:
    """Run an explicit cached-only holdout reviewer and build observation evidence."""
    _verify_binding(
        training_evidence=training_evidence,
        output_artifact=output_artifact,
        candidate=candidate,
    )
    if not _is_safe_identifier(review_run_id) or not _is_safe_identifier(review_version):
        raise DataQualityError("quality review identifiers must be safe")
    if not windows:
        raise DataQualityError("quality review requires at least one holdout window")

    results: list[LearnerQualityReviewWindowResult] = []
    seen_window_ids: set[str] = set()
    for window in sorted(windows, key=lambda item: item.spec.window_id):
        spec = window.spec
        if spec.window_id in seen_window_ids:
            raise DataQualityError("quality review window identities must be unique")
        seen_window_ids.add(spec.window_id)
        if (
            spec.bundle_hash != output_artifact.bundle_hash
            or spec.dataset_registry_hash != output_artifact.dataset_registry_hash
            or spec.symbol not in output_artifact.symbols
            or spec.split != "holdout"
        ):
            raise DataQualityError("quality review window binding is invalid")
        if spec.time_start < training_evidence.training_window_end:
            raise DataQualityError("quality review holdout window overlaps training window")
        isolated_window = LearnerQualityReviewWindow(spec=spec, frame=window.copy_frame())
        try:
            result = LearnerQualityReviewWindowResult.model_validate(
                reviewer(output_artifact, isolated_window.copy_frame(), isolated_window)
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise DataQualityError("invalid quality review result: " + str(exc)) from None
        if (
            result.window_id != spec.window_id
            or result.symbol != spec.symbol
            or result.rows_evaluated != len(isolated_window.frame)
        ):
            raise DataQualityError("quality review result window identity or row count is invalid")
        results.append(result)

    try:
        provisional = LearnerQualityReviewEvidence(
            review_id=f"quality-review-{review_run_id}",
            training_evidence_id=training_evidence.evidence_id,
            training_evidence_hash=training_evidence.evidence_hash,
            output_artifact_hash=output_artifact.artifact_hash,
            learner_id=output_artifact.learner_id,
            learner_run_id=output_artifact.learner_run_id,
            candidate_id=output_artifact.candidate_id,
            candidate_artifact_hash=output_artifact.candidate_artifact_hash,
            bundle_hash=output_artifact.bundle_hash,
            dataset_registry_hash=output_artifact.dataset_registry_hash,
            review_run_id=review_run_id,
            review_version_name=review_version,
            windows=tuple(results),
            reviewed_at=reviewed_at,
            review_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid learner quality review evidence: " + str(exc)) from None
    return provisional.model_copy(
        update={"review_hash": learner_quality_review_content_hash(provisional)}
    )


def _read_evidence(path: Path) -> LearnerQualityReviewEvidence:
    try:
        evidence = LearnerQualityReviewEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        raise DomainViolation("quality review evidence hash or shape is invalid") from exc
    if learner_quality_review_content_hash(evidence) != evidence.review_hash:
        raise DomainViolation("quality review evidence hash mismatch")
    return evidence


def _verify_persisted(
    evidence: LearnerQualityReviewEvidence,
    *,
    training_evidence: LearnerTrainingEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> None:
    _verify_binding(
        training_evidence=training_evidence,
        output_artifact=output_artifact,
        candidate=candidate,
    )
    if (
        evidence.training_evidence_id != training_evidence.evidence_id
        or evidence.training_evidence_hash != training_evidence.evidence_hash
        or evidence.output_artifact_hash != output_artifact.artifact_hash
        or evidence.learner_id != output_artifact.learner_id
        or evidence.learner_run_id != output_artifact.learner_run_id
        or evidence.candidate_id != output_artifact.candidate_id
        or evidence.candidate_artifact_hash != output_artifact.candidate_artifact_hash
        or evidence.bundle_hash != output_artifact.bundle_hash
        or evidence.dataset_registry_hash != output_artifact.dataset_registry_hash
    ):
        raise DomainViolation("quality review evidence binding is invalid")


def read_learner_quality_review_evidence(
    path: Path,
    *,
    training_evidence: LearnerTrainingEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> LearnerQualityReviewEvidence:
    evidence = _read_evidence(path)
    _verify_persisted(
        evidence,
        training_evidence=training_evidence,
        output_artifact=output_artifact,
        candidate=candidate,
    )
    return evidence


def write_learner_quality_review_evidence(
    path: Path,
    evidence: LearnerQualityReviewEvidence,
    *,
    training_evidence: LearnerTrainingEvidence,
    output_artifact: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
) -> LearnerQualityReviewEvidence:
    if path.exists():
        existing = read_learner_quality_review_evidence(
            path,
            training_evidence=training_evidence,
            output_artifact=output_artifact,
            candidate=candidate,
        )
        if existing != evidence:
            raise DomainViolation(f"quality review evidence path is immutable: {path}") from None
        return existing

    if learner_quality_review_content_hash(evidence) != evidence.review_hash:
        raise DomainViolation("quality review evidence hash mismatch")
    _verify_persisted(
        evidence,
        training_evidence=training_evidence,
        output_artifact=output_artifact,
        candidate=candidate,
    )
    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    try:
        os.link(temporary_path, path)
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        existing = read_learner_quality_review_evidence(
            path,
            training_evidence=training_evidence,
            output_artifact=output_artifact,
            candidate=candidate,
        )
        if existing != evidence:
            raise DomainViolation(f"quality review evidence path is immutable: {path}") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_quality_review_evidence(
        path,
        training_evidence=training_evidence,
        output_artifact=output_artifact,
        candidate=candidate,
    )


__all__ = [
    "LearnerQualityReviewEvidence",
    "LearnerQualityReviewMetric",
    "LearnerQualityReviewWindow",
    "LearnerQualityReviewWindowResult",
    "LearnerQualityReviewWindowSpec",
    "LearnerQualityReviewer",
    "execute_learner_quality_review",
    "learner_quality_review_content_hash",
    "read_learner_quality_review_evidence",
    "write_learner_quality_review_evidence",
]
