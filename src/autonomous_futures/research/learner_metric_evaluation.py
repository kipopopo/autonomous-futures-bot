from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pandas as pd
from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .creator_artifacts import CreatorCandidateArtifact
from .learner_artifacts import LearnerArtifact
from .learner_evaluation import LearnerEvaluationWindow
from .performance_metrics import TradePerformanceMetrics, calculate_performance_metrics
from .trade_simulation import TradeSimulationResult


class LearnerMetricWindowEvaluation(DomainModel):
    """One learner evaluation window with validated net performance metrics."""

    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    rows_evaluated: int = Field(ge=1, strict=True)
    metrics: TradePerformanceMetrics


class LearnerMetricEvaluationRun(DomainModel):
    """Deterministic cached-only learner performance evidence; not qualification."""

    evaluation_version: Literal[1] = 1
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    evaluation_version_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    windows: tuple[LearnerMetricWindowEvaluation, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    evaluated_at: datetime
    evaluation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("learner metric evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_windows(self) -> LearnerMetricEvaluationRun:
        window_ids = tuple(window.window_id for window in self.windows)
        if len(set(window_ids)) != len(window_ids) or window_ids != tuple(sorted(window_ids)):
            raise ValueError("learner metric windows must be sorted and unique")
        return self


LearnerMetricSimulator = Callable[
    [LearnerArtifact, CreatorCandidateArtifact, pd.DataFrame, LearnerEvaluationWindow],
    TradeSimulationResult,
]


def _is_safe_identifier(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def _metric_evaluation_content_hash(run: LearnerMetricEvaluationRun) -> str:
    payload = run.model_dump(mode="json", exclude={"evaluated_at", "evaluation_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def learner_metric_evaluation_content_hash(run: LearnerMetricEvaluationRun) -> str:
    """Return the canonical content hash for a metric evaluation run."""
    return _metric_evaluation_content_hash(run)


@dataclass(frozen=True, slots=True)
class CachedOnlyLearnerMetricAdapter:
    """Convert explicit cached learner simulations into validated performance evidence."""

    learner: LearnerArtifact
    candidate: CreatorCandidateArtifact
    evaluation_run_id: str
    evaluation_version: str
    simulator: LearnerMetricSimulator

    def __post_init__(self) -> None:
        if (
            self.candidate.candidate_id != self.learner.candidate_id
            or self.candidate.artifact_hash != self.learner.candidate_artifact_hash
            or self.candidate.bundle_hash != self.learner.bundle_hash
            or self.candidate.dataset_registry_hash != self.learner.dataset_registry_hash
        ):
            raise DataQualityError("candidate does not match learner artifact binding")
        if not _is_safe_identifier(self.evaluation_run_id):
            raise DataQualityError(
                "evaluation_run_id must contain only letters, digits, dots, dashes, or underscores"
            )
        if not _is_safe_identifier(self.evaluation_version):
            raise DataQualityError(
                "evaluation_version must contain only letters, digits, dots, dashes, or underscores"
            )

    def evaluate(
        self,
        windows: Sequence[LearnerEvaluationWindow],
        *,
        evaluated_at: datetime,
    ) -> LearnerMetricEvaluationRun:
        if not windows:
            raise DataQualityError("learner metric evaluation requires at least one window")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() != UTC.utcoffset(evaluated_at):
            raise DataQualityError("evaluated_at must be timezone-aware UTC")

        results: list[LearnerMetricWindowEvaluation] = []
        seen_window_ids: set[str] = set()
        for window in sorted(windows, key=lambda item: item.spec.window_id):
            spec = window.spec
            if spec.window_id in seen_window_ids:
                raise DataQualityError("learner metric window identities must be unique")
            seen_window_ids.add(spec.window_id)
            if spec.learner_id != self.learner.learner_id:
                raise DataQualityError("learner_id does not match learner artifact")
            if spec.candidate_id != self.learner.candidate_id:
                raise DataQualityError("candidate_id does not match learner artifact")
            if spec.candidate_artifact_hash != self.learner.candidate_artifact_hash:
                raise DataQualityError("candidate_artifact_hash does not match learner artifact")
            if spec.bundle_hash != self.learner.bundle_hash:
                raise DataQualityError("bundle_hash does not match learner artifact")
            if spec.dataset_registry_hash != self.learner.dataset_registry_hash:
                raise DataQualityError("dataset_registry_hash does not match learner artifact")
            if spec.symbol not in self.learner.symbols:
                raise DataQualityError("symbol is not present in learner universe")

            isolated_window = LearnerEvaluationWindow(spec=spec, frame=window.copy_frame())
            try:
                simulation = TradeSimulationResult.model_validate(
                    self.simulator(
                        self.learner,
                        self.candidate,
                        isolated_window.copy_frame(),
                        isolated_window,
                    )
                )
            except DataQualityError:
                raise
            except (ValidationError, TypeError, ValueError) as exc:
                raise DataQualityError(
                    "invalid learner cached simulation result: " + str(exc)
                ) from None
            if simulation.symbol != spec.symbol:
                raise DataQualityError("learner simulation result symbol does not match input")
            metrics = calculate_performance_metrics(simulation)
            results.append(
                LearnerMetricWindowEvaluation(
                    window_id=spec.window_id,
                    learner_id=self.learner.learner_id,
                    candidate_id=self.learner.candidate_id,
                    symbol=spec.symbol,
                    rows_evaluated=len(isolated_window.frame),
                    metrics=metrics,
                )
            )

        try:
            provisional = LearnerMetricEvaluationRun(
                learner_id=self.learner.learner_id,
                learner_artifact_hash=self.learner.artifact_hash,
                candidate_id=self.learner.candidate_id,
                candidate_artifact_hash=self.learner.candidate_artifact_hash,
                bundle_hash=self.learner.bundle_hash,
                dataset_registry_hash=self.learner.dataset_registry_hash,
                evaluation_run_id=self.evaluation_run_id,
                evaluation_version_name=self.evaluation_version,
                windows=tuple(results),
                evaluated_at=evaluated_at,
                evaluation_hash="0" * 64,
            )
        except ValidationError as exc:
            raise DataQualityError("invalid learner metric evaluation run: " + str(exc)) from None
        return provisional.model_copy(
            update={"evaluation_hash": learner_metric_evaluation_content_hash(provisional)}
        )


def read_learner_metric_evaluation_run(path: Path) -> LearnerMetricEvaluationRun:
    """Read and verify one persisted cached-only learner metric evaluation run."""
    try:
        run = LearnerMetricEvaluationRun.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted learner metric evaluation run") from exc
    if learner_metric_evaluation_content_hash(run) != run.evaluation_hash:
        raise DomainViolation(f"learner metric evaluation run hash mismatch: {path}")
    return run


def write_learner_metric_evaluation_run(
    path: Path,
    run: LearnerMetricEvaluationRun,
) -> LearnerMetricEvaluationRun:
    """Persist one metric evaluation run with atomic write-once semantics."""
    if learner_metric_evaluation_content_hash(run) != run.evaluation_hash:
        raise DomainViolation("learner metric evaluation run hash mismatch")
    if path.exists():
        existing = read_learner_metric_evaluation_run(path)
        if existing != run:
            raise DomainViolation(f"learner metric evaluation run path is immutable: {path}")
        return existing

    payload = json.dumps(run.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8", newline="\n")
        os.link(temporary_path, path)
    except FileExistsError:
        existing = read_learner_metric_evaluation_run(path)
        if existing != run:
            raise DomainViolation(
                f"learner metric evaluation run path is immutable: {path}"
            ) from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_metric_evaluation_run(path)


__all__ = [
    "CachedOnlyLearnerMetricAdapter",
    "LearnerMetricEvaluationRun",
    "LearnerMetricSimulator",
    "LearnerMetricWindowEvaluation",
    "learner_metric_evaluation_content_hash",
    "read_learner_metric_evaluation_run",
    "write_learner_metric_evaluation_run",
]
