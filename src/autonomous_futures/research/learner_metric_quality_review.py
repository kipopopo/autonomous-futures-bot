from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact
from .learner_metric_evaluation import (
    LearnerMetricEvaluationRun,
    LearnerMetricWindowEvaluation,
)
from .learner_metric_review_input import load_verified_learner_metric_review_input


class LearnerMetricQualityReviewMetric(DomainModel):
    """One finite observation returned by a caller-supplied metric reviewer."""

    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")
    value: Decimal

    @field_validator("value")
    @classmethod
    def value_is_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("metric quality review value must be finite")
        return value


class LearnerMetricQualityReviewWindowResult(DomainModel):
    """Observed-only quality-review output for one metric evaluation window."""

    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    metrics: tuple[LearnerMetricQualityReviewMetric, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def metrics_are_sorted_and_unique(self) -> LearnerMetricQualityReviewWindowResult:
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(set(metric_ids)) != len(metric_ids) or metric_ids != tuple(sorted(metric_ids)):
            raise ValueError("metric quality review metrics must be sorted and unique")
        return self


class LearnerMetricQualityReviewEvidence(DomainModel):
    """Observed-only review evidence bound to one persisted metric evaluation run."""

    review_version: Literal[1] = 1
    review_id: str = Field(pattern=r"^metric-quality-review-[a-z0-9][a-z0-9-]{0,63}$")
    metric_evaluation_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    metric_evaluation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_version_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    windows: tuple[LearnerMetricQualityReviewWindowResult, ...] = Field(min_length=1)
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
            raise ValueError("metric quality review reviewed_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def windows_are_sorted_and_unique(self) -> LearnerMetricQualityReviewEvidence:
        window_ids = tuple(window.window_id for window in self.windows)
        if len(set(window_ids)) != len(window_ids) or window_ids != tuple(sorted(window_ids)):
            raise ValueError("metric quality review windows must be sorted and unique")
        return self


def learner_metric_quality_review_content_hash(
    evidence: LearnerMetricQualityReviewEvidence,
) -> str:
    """Return the canonical hash excluding audit time and the hash field."""
    payload = evidence.model_dump(mode="json", exclude={"reviewed_at", "review_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


LearnerMetricQualityReviewer = Callable[
    [LearnerMetricEvaluationRun, LearnerMetricWindowEvaluation],
    LearnerMetricQualityReviewWindowResult,
]


def _is_safe_identifier(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def execute_learner_metric_quality_review(
    path: Path,
    *,
    learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    review_id: str,
    review_version: str,
    reviewer: LearnerMetricQualityReviewer,
    reviewed_at: datetime,
) -> LearnerMetricQualityReviewEvidence:
    """Build observed-only review evidence from verified persisted metric input."""
    if not _is_safe_identifier(review_id) or not _is_safe_identifier(review_version):
        raise DataQualityError("metric quality review identifiers must be safe")
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() != UTC.utcoffset(reviewed_at):
        raise DataQualityError("metric quality review reviewed_at must be timezone-aware UTC")

    run = load_verified_learner_metric_review_input(
        path,
        learner=learner,
        candidate=candidate,
    )
    results: list[LearnerMetricQualityReviewWindowResult] = []
    for source_window in run.windows:
        try:
            result = LearnerMetricQualityReviewWindowResult.model_validate(
                reviewer(
                    run.model_copy(deep=True),
                    source_window.model_copy(deep=True),
                )
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise DataQualityError("invalid quality review result: " + str(exc)) from None
        if result.window_id != source_window.window_id or result.symbol != source_window.symbol:
            raise DataQualityError("quality review result window identity is invalid")
        results.append(result)

    try:
        provisional = LearnerMetricQualityReviewEvidence(
            review_id=review_id,
            metric_evaluation_run_id=run.evaluation_run_id,
            metric_evaluation_hash=run.evaluation_hash,
            learner_id=run.learner_id,
            learner_artifact_hash=run.learner_artifact_hash,
            candidate_id=run.candidate_id,
            candidate_artifact_hash=run.candidate_artifact_hash,
            bundle_hash=run.bundle_hash,
            dataset_registry_hash=run.dataset_registry_hash,
            review_version_name=review_version,
            windows=tuple(results),
            reviewed_at=reviewed_at,
            review_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid metric quality review evidence: " + str(exc)) from None
    return provisional.model_copy(
        update={"review_hash": learner_metric_quality_review_content_hash(provisional)}
    )


def read_learner_metric_quality_review_evidence(
    path: Path,
) -> LearnerMetricQualityReviewEvidence:
    """Read and verify one persisted observed-only metric quality review."""
    try:
        evidence = LearnerMetricQualityReviewEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted learner metric quality review evidence") from exc
    if learner_metric_quality_review_content_hash(evidence) != evidence.review_hash:
        raise DomainViolation(f"learner metric quality review evidence hash mismatch: {path}")
    return evidence


def write_learner_metric_quality_review_evidence(
    path: Path,
    evidence: LearnerMetricQualityReviewEvidence,
) -> LearnerMetricQualityReviewEvidence:
    """Persist observed-only review evidence atomically and write-once."""
    if learner_metric_quality_review_content_hash(evidence) != evidence.review_hash:
        raise DomainViolation("learner metric quality review evidence hash mismatch")
    if path.exists():
        existing = read_learner_metric_quality_review_evidence(path)
        if existing != evidence:
            raise DomainViolation(
                f"learner metric quality review evidence path is immutable: {path}"
            )
        return existing

    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_learner_metric_quality_review_evidence(path)
        if existing != evidence:
            raise DomainViolation(
                f"learner metric quality review evidence path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_metric_quality_review_evidence(path)


__all__ = [
    "LearnerMetricQualityReviewer",
    "LearnerMetricQualityReviewEvidence",
    "LearnerMetricQualityReviewMetric",
    "LearnerMetricQualityReviewWindowResult",
    "execute_learner_metric_quality_review",
    "learner_metric_quality_review_content_hash",
    "read_learner_metric_quality_review_evidence",
    "write_learner_metric_quality_review_evidence",
]
