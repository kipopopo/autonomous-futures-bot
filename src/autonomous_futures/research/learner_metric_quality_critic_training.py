from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

import pandas as pd
from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact
from .learner_inputs import LearnerInputWindow
from .learner_metric_quality_critic import (
    LearnerMetricQualityCriticRequest,
    LearnerMetricQualityCritiqueEvidence,
    verify_learner_metric_quality_critic_binding,
)
from .learner_runs import LearnerRun
from .learner_training import LearnerTrainingOutput
from .learner_training_evidence import (
    LearnerTrainingEvidence,
    learner_training_evidence_content_hash,
    read_learner_training_evidence,
)
from .learner_training_pipeline import execute_learner_training_with_evidence


class LearnerMetricQualityCriticTrainingEvidence(DomainModel):
    """Immutable link between Critic evidence and one explicit training run."""

    evidence_version: Literal[1] = 1
    evidence_id: str = Field(pattern=r"^critic-training-evidence-[a-z0-9][a-z0-9-]{0,63}$")
    critic_evidence_id: str = Field(
        pattern=r"^learner-quality-critic-evidence-[a-z0-9][a-z0-9-]{0,63}$"
    )
    critic_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_evidence_id: str = Field(pattern=r"^training-evidence-[a-z0-9][a-z0-9-]{0,63}$")
    training_evidence_ref: str = Field(min_length=1)
    training_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_run_id: str = Field(pattern=r"^run-[a-z0-9][a-z0-9-]{0,63}$")
    prepared_run_ref: str = Field(min_length=1)
    prepared_run_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_learner_artifact_ref: str = Field(min_length=1)
    source_learner_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact_ref: str = Field(min_length=1)
    output_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_window_ids: tuple[str, ...] = Field(min_length=1)
    input_symbols: tuple[str, ...] = Field(min_length=1)
    feature_ids: tuple[str, ...] = Field(min_length=1)
    training_window_start: datetime
    training_window_end: datetime
    objective_id: Literal["next_bar_direction"]
    target_definition: Literal["close[t+1] > close[t]"] = "close[t+1] > close[t]"
    learner_version: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    model_family: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    status: Literal["completed"] = "completed"
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    promotion_state: Literal["unpromoted"] = "unpromoted"
    paper_activation: Literal[False] = False
    execution_authority: Literal[False] = False
    created_at: datetime
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "training_evidence_ref",
        "prepared_run_ref",
        "source_learner_artifact_ref",
        "output_artifact_ref",
    )
    @classmethod
    def refs_are_relative_posix(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or path == PurePosixPath(".")
            or ".." in path.parts
            or "\\" in value
        ):
            raise ValueError("Critic training references must be relative POSIX paths")
        return value

    @field_validator("input_window_ids", "input_symbols", "feature_ids")
    @classmethod
    def lists_are_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values) or values != tuple(sorted(set(values))):
            raise ValueError("Critic training lists must be sorted and unique")
        return values

    @field_validator("input_symbols")
    @classmethod
    def symbols_are_uppercase(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(value != value.upper() for value in values):
            raise ValueError("Critic training symbols must be uppercase")
        return values

    @field_validator("training_window_start", "training_window_end", "created_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("Critic training timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def window_is_valid(self) -> LearnerMetricQualityCriticTrainingEvidence:
        if self.training_window_end <= self.training_window_start:
            raise ValueError("Critic training window must end after it starts")
        return self


def learner_metric_quality_critic_training_evidence_content_hash(
    evidence: LearnerMetricQualityCriticTrainingEvidence,
) -> str:
    payload = evidence.model_dump(mode="json", exclude={"created_at", "evidence_hash"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _resolve_ref(root: Path, reference: str) -> Path:
    root_resolved = root.resolve()
    reference_path = PurePosixPath(reference)
    if (
        not reference
        or reference_path.is_absolute()
        or reference_path == PurePosixPath(".")
        or ".." in reference_path.parts
        or "\\" in reference
    ):
        raise DataQualityError("Critic training reference must be a relative POSIX path")
    path = (root_resolved / reference_path).resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError:
        raise DataQualityError("Critic training reference escapes its root") from None
    return path


def build_learner_metric_quality_critic_training_evidence(
    *,
    request: LearnerMetricQualityCriticRequest,
    critic_evidence: LearnerMetricQualityCritiqueEvidence,
    training_evidence: LearnerTrainingEvidence,
    objective_id: str,
    evidence_id: str,
    training_evidence_ref: str,
    created_at: datetime,
) -> LearnerMetricQualityCriticTrainingEvidence:
    verify_learner_metric_quality_critic_binding(request=request, evidence=critic_evidence)
    if critic_evidence.critique_decision != "revise":
        raise DataQualityError("only a revise Critic decision can authorize training research")
    if objective_id != "next_bar_direction":
        raise DataQualityError("unsupported learner training objective")
    if learner_training_evidence_content_hash(training_evidence) != training_evidence.evidence_hash:
        raise DomainViolation("learner training evidence hash mismatch")
    if (
        training_evidence.candidate_id != request.candidate_id
        or training_evidence.candidate_artifact_hash != request.candidate_artifact_hash
        or training_evidence.learner_id != request.learner_id
        or training_evidence.source_learner_artifact_hash != request.learner_artifact_hash
        or training_evidence.bundle_hash != request.bundle_hash
        or training_evidence.dataset_registry_hash != request.dataset_registry_hash
    ):
        raise DataQualityError("Critic training evidence binding is invalid")
    try:
        provisional = LearnerMetricQualityCriticTrainingEvidence(
            evidence_id=evidence_id,
            critic_evidence_id=critic_evidence.evidence_id,
            critic_evidence_hash=critic_evidence.evidence_hash,
            training_evidence_id=training_evidence.evidence_id,
            training_evidence_ref=training_evidence_ref,
            training_evidence_hash=training_evidence.evidence_hash,
            prepared_run_id=training_evidence.prepared_run_id,
            prepared_run_ref=training_evidence.prepared_run_ref,
            prepared_run_hash=training_evidence.prepared_run_hash,
            source_learner_artifact_ref=training_evidence.source_learner_artifact_ref,
            source_learner_artifact_hash=training_evidence.source_learner_artifact_hash,
            output_artifact_ref=training_evidence.output_artifact_ref,
            output_artifact_hash=training_evidence.output_artifact_hash,
            learner_id=training_evidence.learner_id,
            learner_run_id=training_evidence.learner_run_id,
            candidate_id=training_evidence.candidate_id,
            candidate_artifact_hash=training_evidence.candidate_artifact_hash,
            bundle_hash=training_evidence.bundle_hash,
            dataset_registry_hash=training_evidence.dataset_registry_hash,
            input_window_ids=training_evidence.input_window_ids,
            input_symbols=training_evidence.input_symbols,
            feature_ids=training_evidence.feature_ids,
            training_window_start=training_evidence.training_window_start,
            training_window_end=training_evidence.training_window_end,
            objective_id="next_bar_direction",
            learner_version=training_evidence.learner_version,
            model_family=training_evidence.model_family,
            created_at=created_at,
            evidence_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError("invalid Critic training evidence: " + str(exc)) from None
    return provisional.model_copy(
        update={
            "evidence_hash": learner_metric_quality_critic_training_evidence_content_hash(
                provisional
            )
        }
    )


def _verify_link(
    link: LearnerMetricQualityCriticTrainingEvidence,
    *,
    request: LearnerMetricQualityCriticRequest,
    critic_evidence: LearnerMetricQualityCritiqueEvidence,
    training_evidence: LearnerTrainingEvidence,
) -> None:
    verify_learner_metric_quality_critic_binding(request=request, evidence=critic_evidence)
    if learner_metric_quality_critic_training_evidence_content_hash(link) != link.evidence_hash:
        raise DomainViolation("Critic training evidence hash mismatch")
    if learner_training_evidence_content_hash(training_evidence) != training_evidence.evidence_hash:
        raise DomainViolation("learner training evidence hash mismatch")
    if (
        link.critic_evidence_id != critic_evidence.evidence_id
        or link.critic_evidence_hash != critic_evidence.evidence_hash
        or link.training_evidence_id != training_evidence.evidence_id
        or link.training_evidence_hash != training_evidence.evidence_hash
        or link.output_artifact_hash != training_evidence.output_artifact_hash
        or link.learner_id != request.learner_id
        or link.candidate_id != request.candidate_id
        or link.candidate_artifact_hash != request.candidate_artifact_hash
        or link.bundle_hash != request.bundle_hash
        or link.dataset_registry_hash != request.dataset_registry_hash
        or link.objective_id != "next_bar_direction"
    ):
        raise DomainViolation("Critic training evidence binding failed")


def read_learner_metric_quality_critic_training_evidence(
    path: Path,
    *,
    request: LearnerMetricQualityCriticRequest,
    critic_evidence: LearnerMetricQualityCritiqueEvidence,
    training_evidence_root: Path,
    run_root: Path,
    artifact_root: Path,
    model_root: Path,
    candidate: CreatorCandidateArtifact,
) -> LearnerMetricQualityCriticTrainingEvidence:
    try:
        link = LearnerMetricQualityCriticTrainingEvidence.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted Critic training evidence") from exc
    training = read_learner_training_evidence(
        _resolve_ref(training_evidence_root, link.training_evidence_ref),
        run_root=run_root,
        artifact_root=artifact_root,
        model_root=model_root,
        candidate=candidate,
    )
    _verify_link(
        link,
        request=request,
        critic_evidence=critic_evidence,
        training_evidence=training,
    )
    return link


def write_learner_metric_quality_critic_training_evidence(
    path: Path,
    evidence: LearnerMetricQualityCriticTrainingEvidence,
    *,
    request: LearnerMetricQualityCriticRequest,
    critic_evidence: LearnerMetricQualityCritiqueEvidence,
    training_evidence_root: Path,
    run_root: Path,
    artifact_root: Path,
    model_root: Path,
    candidate: CreatorCandidateArtifact,
) -> LearnerMetricQualityCriticTrainingEvidence:
    training = read_learner_training_evidence(
        _resolve_ref(training_evidence_root, evidence.training_evidence_ref),
        run_root=run_root,
        artifact_root=artifact_root,
        model_root=model_root,
        candidate=candidate,
    )
    _verify_link(
        evidence,
        request=request,
        critic_evidence=critic_evidence,
        training_evidence=training,
    )
    if path.exists():
        existing = read_learner_metric_quality_critic_training_evidence(
            path,
            request=request,
            critic_evidence=critic_evidence,
            training_evidence_root=training_evidence_root,
            run_root=run_root,
            artifact_root=artifact_root,
            model_root=model_root,
            candidate=candidate,
        )
        if existing != evidence:
            raise DomainViolation(f"Critic training evidence path is immutable: {path}")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_learner_metric_quality_critic_training_evidence(
            path,
            request=request,
            critic_evidence=critic_evidence,
            training_evidence_root=training_evidence_root,
            run_root=run_root,
            artifact_root=artifact_root,
            model_root=model_root,
            candidate=candidate,
        )
        if existing != evidence:
            raise DomainViolation(f"Critic training evidence path is immutable: {path}") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_metric_quality_critic_training_evidence(
        path,
        request=request,
        critic_evidence=critic_evidence,
        training_evidence_root=training_evidence_root,
        run_root=run_root,
        artifact_root=artifact_root,
        model_root=model_root,
        candidate=candidate,
    )


def execute_learner_metric_quality_critic_training_with_evidence(
    *,
    request: LearnerMetricQualityCriticRequest,
    critic_evidence: LearnerMetricQualityCritiqueEvidence,
    objective_id: str,
    prepared_run: LearnerRun,
    source_learner: LearnerArtifact,
    candidate: CreatorCandidateArtifact,
    windows: Sequence[LearnerInputWindow],
    trainer: Callable[
        [LearnerMetricQualityCritiqueEvidence, LearnerRun, dict[str, pd.DataFrame]],
        LearnerTrainingOutput,
    ],
    run_root: Path,
    prepared_run_ref: str,
    artifact_root: Path,
    source_learner_artifact_ref: str,
    output_artifact_ref: str,
    model_root: Path,
    training_evidence_root: Path,
    training_evidence_ref: str,
    link_evidence_path: Path,
    artifact_created_at: datetime,
    evidence_created_at: datetime,
) -> LearnerMetricQualityCriticTrainingEvidence:
    """Run one explicit objective trainer after exact Critic binding."""
    verify_learner_metric_quality_critic_binding(request=request, evidence=critic_evidence)
    if critic_evidence.critique_decision != "revise":
        raise DataQualityError("only a revise Critic decision can authorize training research")
    if objective_id != "next_bar_direction":
        raise DataQualityError("unsupported learner training objective")

    def bound_trainer(run: LearnerRun, frames: dict[str, pd.DataFrame]) -> LearnerTrainingOutput:
        return trainer(critic_evidence, run, frames)

    training_evidence = execute_learner_training_with_evidence(
        prepared_run=prepared_run,
        source_learner=source_learner,
        candidate=candidate,
        windows=windows,
        trainer=bound_trainer,
        run_root=run_root,
        prepared_run_ref=prepared_run_ref,
        artifact_root=artifact_root,
        source_learner_artifact_ref=source_learner_artifact_ref,
        output_artifact_ref=output_artifact_ref,
        model_root=model_root,
        evidence_root=training_evidence_root,
        evidence_ref=training_evidence_ref,
        artifact_created_at=artifact_created_at,
        evidence_created_at=evidence_created_at,
    )
    link = build_learner_metric_quality_critic_training_evidence(
        request=request,
        critic_evidence=critic_evidence,
        training_evidence=training_evidence,
        objective_id=objective_id,
        evidence_id=f"critic-training-evidence-{prepared_run.run_id.removeprefix('run-')}",
        training_evidence_ref=training_evidence_ref,
        created_at=evidence_created_at,
    )
    return write_learner_metric_quality_critic_training_evidence(
        link_evidence_path,
        link,
        request=request,
        critic_evidence=critic_evidence,
        training_evidence_root=training_evidence_root,
        run_root=run_root,
        artifact_root=artifact_root,
        model_root=model_root,
        candidate=candidate,
    )


__all__ = [
    "LearnerMetricQualityCriticTrainingEvidence",
    "build_learner_metric_quality_critic_training_evidence",
    "execute_learner_metric_quality_critic_training_with_evidence",
    "learner_metric_quality_critic_training_evidence_content_hash",
    "read_learner_metric_quality_critic_training_evidence",
    "write_learner_metric_quality_critic_training_evidence",
]
