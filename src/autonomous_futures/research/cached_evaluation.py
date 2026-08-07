from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

import pandas as pd
from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError, canonicalize_bars
from ..domain.contracts import DomainModel
from .creator_artifacts import CreatorCandidateArtifact
from .qualification_artifacts import QualificationGateResult, QualificationMetric


class CachedEvaluationWindowSpec(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    time_start: datetime
    time_end: datetime

    @field_validator("time_start", "time_end")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("cached evaluation timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_time_range(self) -> CachedEvaluationWindowSpec:
        if self.time_start >= self.time_end:
            raise ValueError("cached evaluation time_start must be before time_end")
        return self


@dataclass(frozen=True, slots=True)
class CachedEvaluationWindow:
    spec: CachedEvaluationWindowSpec
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        required_columns = {"timestamp", "open", "high", "low", "close"}
        missing_columns = sorted(required_columns.difference(self.frame.columns))
        if missing_columns:
            raise DataQualityError(
                "cached evaluation frame is missing OHLC columns: " + ", ".join(missing_columns)
            )
        canonical = canonicalize_bars(self.frame, interval=timedelta(minutes=5))
        timestamps = pd.DatetimeIndex(canonical["timestamp"])
        expected_start = pd.Timestamp(self.spec.time_start)
        expected_end = pd.Timestamp(self.spec.time_end)
        if timestamps[0] != expected_start or timestamps[-1] + timedelta(minutes=5) != expected_end:
            raise DataQualityError("cached evaluation frame must cover exactly the window range")
        object.__setattr__(self, "frame", canonical.copy(deep=True))

    def copy_frame(self) -> pd.DataFrame:
        """Return an isolated frame; evaluator code cannot mutate the cached source frame."""
        return self.frame.copy(deep=True)


class CachedWindowEvaluation(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    metrics: tuple[QualificationMetric, ...] = Field(min_length=1)
    gates: tuple[QualificationGateResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_order(self) -> CachedWindowEvaluation:
        metric_ids = tuple(metric.metric_id for metric in self.metrics)
        if len(set(metric_ids)) != len(metric_ids) or metric_ids != tuple(sorted(metric_ids)):
            raise ValueError("cached window metrics must be sorted and unique")
        gate_ids = tuple(gate.gate_id for gate in self.gates)
        if len(set(gate_ids)) != len(gate_ids) or gate_ids != tuple(sorted(gate_ids)):
            raise ValueError("cached window gates must be sorted and unique")
        return self


class CachedEvaluationRun(DomainModel):
    evaluation_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    evaluator_version: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    windows: tuple[CachedWindowEvaluation, ...] = Field(min_length=1)
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False
    evaluated_at: datetime
    evaluation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("evaluated_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_windows(self) -> CachedEvaluationRun:
        window_ids = tuple(window.window_id for window in self.windows)
        if len(set(window_ids)) != len(window_ids) or window_ids != tuple(sorted(window_ids)):
            raise ValueError("cached evaluation windows must be sorted and unique")
        return self


CachedEvaluator = Callable[
    [CreatorCandidateArtifact, pd.DataFrame, CachedEvaluationWindow], CachedWindowEvaluation
]


def _is_safe_identifier(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def _evaluation_content_hash(run: CachedEvaluationRun) -> str:
    payload = run.model_dump(mode="json", exclude={"evaluated_at", "evaluation_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class CachedOnlyEvaluatorAdapter:
    candidate: CreatorCandidateArtifact
    evaluator_run_id: str
    evaluator_version: str
    evaluator: CachedEvaluator

    def __post_init__(self) -> None:
        if not _is_safe_identifier(self.evaluator_run_id):
            raise DataQualityError(
                "evaluator_run_id must contain only letters, digits, dots, dashes, or underscores"
            )
        if not _is_safe_identifier(self.evaluator_version):
            raise DataQualityError(
                "evaluator_version must contain only letters, digits, dots, dashes, or underscores"
            )

    def evaluate(
        self,
        windows: Sequence[CachedEvaluationWindow],
        *,
        evaluated_at: datetime,
    ) -> CachedEvaluationRun:
        if not windows:
            raise DataQualityError("cached evaluation requires at least one window")
        results: list[CachedWindowEvaluation] = []
        candidate_symbols = self.candidate.strategy.universe.symbols
        seen_window_ids: set[str] = set()
        for window in sorted(windows, key=lambda item: item.spec.window_id):
            spec = window.spec
            if spec.window_id in seen_window_ids:
                raise DataQualityError("cached evaluation window identities must be unique")
            seen_window_ids.add(spec.window_id)
            if spec.bundle_hash != self.candidate.bundle_hash:
                raise DataQualityError("cached evaluation bundle_hash does not match candidate")
            if spec.dataset_registry_hash != self.candidate.dataset_registry_hash:
                raise DataQualityError(
                    "cached evaluation dataset_registry_hash does not match candidate"
                )
            if spec.symbol not in candidate_symbols:
                raise DataQualityError(
                    "cached evaluation symbol is not present in candidate universe"
                )
            isolated_window = CachedEvaluationWindow(spec=spec, frame=window.copy_frame())
            result = self.evaluator(self.candidate, isolated_window.copy_frame(), isolated_window)
            if result.window_id != spec.window_id or result.symbol != spec.symbol:
                raise DataQualityError(
                    "cached evaluator result window identity does not match input"
                )
            results.append(result)
        try:
            provisional = CachedEvaluationRun(
                candidate_id=self.candidate.candidate_id,
                candidate_artifact_hash=self.candidate.artifact_hash,
                bundle_hash=self.candidate.bundle_hash,
                dataset_registry_hash=self.candidate.dataset_registry_hash,
                evaluator_run_id=self.evaluator_run_id,
                evaluator_version=self.evaluator_version,
                windows=tuple(results),
                evaluated_at=evaluated_at,
                evaluation_hash="0" * 64,
            )
        except ValidationError as exc:
            raise DataQualityError("invalid cached evaluation run: " + str(exc)) from None
        return provisional.model_copy(
            update={"evaluation_hash": _evaluation_content_hash(provisional)}
        )


__all__ = [
    "CachedEvaluationRun",
    "CachedEvaluationWindow",
    "CachedEvaluationWindowSpec",
    "CachedEvaluator",
    "CachedOnlyEvaluatorAdapter",
    "CachedWindowEvaluation",
]
