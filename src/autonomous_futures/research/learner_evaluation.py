from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .cached_evaluation import CachedEvaluationWindow, CachedEvaluationWindowSpec
from .learner_artifacts import LearnerArtifact


class LearnerEvaluationWindowSpec(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    time_start: datetime
    time_end: datetime

    @field_validator("time_start", "time_end")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("learner evaluation timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_time_range(self) -> LearnerEvaluationWindowSpec:
        if self.time_start >= self.time_end:
            raise ValueError("learner evaluation time_start must be before time_end")
        return self


@dataclass(frozen=True, slots=True)
class LearnerEvaluationWindow:
    spec: LearnerEvaluationWindowSpec
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
        object.__setattr__(self, "frame", cached_window.frame.copy(deep=True))

    def copy_frame(self) -> pd.DataFrame:
        """Return an isolated cached frame for learner callback code."""
        return self.frame.copy(deep=True)


class LearnerWindowEvaluation(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    rows_evaluated: int = Field(ge=1, strict=True)


class LearnerEvaluationRun(DomainModel):
    evaluation_version: Literal[1] = 1
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    evaluation_version_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    windows: tuple[LearnerWindowEvaluation, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    evaluated_at: datetime
    evaluation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("learner evaluation evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_windows(self) -> LearnerEvaluationRun:
        window_ids = tuple(window.window_id for window in self.windows)
        if len(set(window_ids)) != len(window_ids) or window_ids != tuple(sorted(window_ids)):
            raise ValueError("learner evaluation windows must be sorted and unique")
        return self


LearnerEvaluator = Callable[
    [LearnerArtifact, pd.DataFrame, LearnerEvaluationWindow], LearnerWindowEvaluation
]


def _is_safe_identifier(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def _evaluation_content_hash(run: LearnerEvaluationRun) -> str:
    payload = run.model_dump(mode="json", exclude={"evaluated_at", "evaluation_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def learner_evaluation_content_hash(run: LearnerEvaluationRun) -> str:
    """Return the canonical content hash used to verify a persisted evaluation run."""
    return _evaluation_content_hash(run)


@dataclass(frozen=True, slots=True)
class CachedOnlyLearnerEvaluatorAdapter:
    learner: LearnerArtifact
    evaluation_run_id: str
    evaluation_version: str
    evaluator: LearnerEvaluator

    def __post_init__(self) -> None:
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
    ) -> LearnerEvaluationRun:
        if not windows:
            raise DataQualityError("learner evaluation requires at least one window")

        results: list[LearnerWindowEvaluation] = []
        seen_window_ids: set[str] = set()
        for window in sorted(windows, key=lambda item: item.spec.window_id):
            spec = window.spec
            if spec.window_id in seen_window_ids:
                raise DataQualityError("learner evaluation window identities must be unique")
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
                result = self.evaluator(
                    self.learner,
                    isolated_window.copy_frame(),
                    isolated_window,
                )
            except ValidationError as exc:
                raise DataQualityError("invalid learner evaluation result: " + str(exc)) from None
            if (
                result.window_id != spec.window_id
                or result.learner_id != self.learner.learner_id
                or result.candidate_id != self.learner.candidate_id
                or result.symbol != spec.symbol
            ):
                raise DataQualityError(
                    "learner evaluator result window identity does not match input"
                )
            results.append(result)

        try:
            provisional = LearnerEvaluationRun(
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
            raise DataQualityError("invalid learner evaluation run: " + str(exc)) from None
        return provisional.model_copy(
            update={"evaluation_hash": _evaluation_content_hash(provisional)}
        )


def read_learner_evaluation_run(path: Path) -> LearnerEvaluationRun:
    """Read and verify one persisted cached-only learner evaluation run."""
    try:
        run = LearnerEvaluationRun.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FileNotFoundError(path) from exc
    except (ValidationError, ValueError) as exc:
        raise DataQualityError("invalid persisted learner evaluation run") from exc
    if _evaluation_content_hash(run) != run.evaluation_hash:
        raise DomainViolation(f"learner evaluation run hash mismatch: {path}")
    return run


def write_learner_evaluation_run(
    path: Path,
    run: LearnerEvaluationRun,
) -> LearnerEvaluationRun:
    """Persist one evaluation run with atomic write-once semantics."""
    if _evaluation_content_hash(run) != run.evaluation_hash:
        raise DomainViolation("learner evaluation run hash mismatch")
    if path.exists():
        existing = read_learner_evaluation_run(path)
        if existing != run:
            raise DomainViolation(f"learner evaluation run path is immutable: {path}")
        return existing

    payload = json.dumps(run.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    try:
        os.link(temporary_path, path)
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        existing = read_learner_evaluation_run(path)
        if existing != run:
            raise DomainViolation(f"learner evaluation run path is immutable: {path}") from None
        return existing
    finally:
        temporary_path.unlink(missing_ok=True)
    return read_learner_evaluation_run(path)


__all__ = [
    "CachedOnlyLearnerEvaluatorAdapter",
    "LearnerEvaluationRun",
    "LearnerEvaluationWindow",
    "LearnerEvaluationWindowSpec",
    "LearnerEvaluator",
    "LearnerWindowEvaluation",
    "learner_evaluation_content_hash",
    "read_learner_evaluation_run",
    "write_learner_evaluation_run",
]
