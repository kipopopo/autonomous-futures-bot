from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import pandas as pd
from pydantic import Field, field_validator, model_validator

from ..data.parquet import DataQualityError, canonicalize_bars
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .causal_evaluation import materialize_causal_context
from .creator_artifacts import CreatorCandidateArtifact
from .feature_signals import materialize_causal_features
from .learner_artifacts import LearnerArtifact, verify_learner_artifact_binding

_CONTEXT_COLUMNS = (
    "context_timestamp",
    "context_open",
    "context_high",
    "context_low",
    "context_close",
    "context_close_time",
    "context_available_at",
)
_REQUIRED_OHLC = ("timestamp", "open", "high", "low", "close")


class LearnerInputWindowSpec(DomainModel):
    """Metadata contract for one causal learner input window."""

    input_id: str = Field(pattern=r"^input-[a-z0-9][a-z0-9-]{0,63}$")
    learner_id: str = Field(pattern=r"^learner-[a-z0-9][a-z0-9-]{0,63}$")
    learner_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_ids: tuple[str, ...] = Field(min_length=1)
    time_start: datetime
    time_end: datetime
    row_count: int = Field(gt=0, strict=True)
    primary_interval: Literal["5m"] = "5m"
    context_interval: Literal["15m"] = "15m"
    context_feature_policy: Literal["close_time_plus_1ms"] = "close_time_plus_1ms"
    data_source: Literal["cached_only"] = "cached_only"
    exchange_access: Literal[False] = False

    @field_validator("time_start", "time_end")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("learner input timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("feature_ids")
    @classmethod
    def feature_ids_are_sorted_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("learner input feature IDs must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_time_range(self) -> LearnerInputWindowSpec:
        if self.time_start >= self.time_end:
            raise ValueError("learner input time_start must be before time_end")
        return self


@dataclass(frozen=True, slots=True)
class LearnerInputWindow:
    spec: LearnerInputWindowSpec
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        missing = sorted(
            set(_REQUIRED_OHLC)
            .union(_CONTEXT_COLUMNS, self.spec.feature_ids)
            .difference(self.frame.columns)
        )
        if missing:
            raise DataQualityError("learner input frame is missing columns: " + ", ".join(missing))
        canonical = canonicalize_bars(self.frame, interval=timedelta(minutes=5))
        if len(canonical) != self.spec.row_count:
            raise DataQualityError("learner input row_count does not match frame")
        timestamps = pd.DatetimeIndex(canonical["timestamp"])
        if timestamps[0] != pd.Timestamp(self.spec.time_start) or timestamps[-1] + timedelta(
            minutes=5
        ) != pd.Timestamp(self.spec.time_end):
            raise DataQualityError("learner input frame does not cover exactly the window range")
        available_at = pd.to_datetime(canonical["context_available_at"], utc=True, errors="coerce")
        timestamp_series = pd.DatetimeIndex(canonical["timestamp"])
        if ((available_at.notna()) & (available_at > timestamp_series)).any():
            raise DataQualityError("learner input contains context before close boundary")
        object.__setattr__(self, "frame", canonical.copy(deep=True))

    def copy_frame(self) -> pd.DataFrame:
        """Return an isolated learner input frame."""
        return self.frame.copy(deep=True)


@dataclass(frozen=True, slots=True)
class LearnerInputMaterializer:
    learner: LearnerArtifact
    candidate: CreatorCandidateArtifact

    def materialize(
        self,
        *,
        primary: pd.DataFrame,
        context: pd.DataFrame,
        symbol: str,
        input_id: str,
    ) -> LearnerInputWindow:
        try:
            verify_learner_artifact_binding(self.learner, self.candidate)
        except DomainViolation:
            raise DataQualityError("learner candidate binding is invalid") from None
        if symbol not in self.learner.symbols:
            raise DataQualityError("symbol is not present in learner universe")

        candidate_feature_ids = tuple(
            sorted(feature.name for feature in self.candidate.strategy.features)
        )
        if candidate_feature_ids != self.learner.feature_ids:
            raise DataQualityError("learner feature IDs do not match candidate features")

        primary_canonical = canonicalize_bars(primary, interval=timedelta(minutes=5))
        context_canonical = canonicalize_bars(context, interval=timedelta(minutes=15))
        primary_window_end = pd.Timestamp(primary_canonical.iloc[-1]["timestamp"]) + timedelta(
            minutes=5
        )
        context_coverage_end = pd.Timestamp(context_canonical.iloc[-1]["timestamp"]) + timedelta(
            minutes=15
        )
        if context_coverage_end < primary_window_end:
            raise DataQualityError("context frame does not cover primary learner window")

        context_frame = materialize_causal_context(primary_canonical, context)
        if pd.isna(context_frame.iloc[-1]["context_available_at"]):
            raise DataQualityError("context frame does not cover primary learner window")
        input_frame = materialize_causal_features(self.candidate, context_frame)
        time_start = pd.Timestamp(input_frame.iloc[0]["timestamp"]).to_pydatetime()
        time_end = pd.Timestamp(input_frame.iloc[-1]["timestamp"]).to_pydatetime() + timedelta(
            minutes=5
        )
        spec = LearnerInputWindowSpec(
            input_id=input_id,
            learner_id=self.learner.learner_id,
            learner_artifact_hash=self.learner.artifact_hash,
            candidate_id=self.learner.candidate_id,
            candidate_artifact_hash=self.learner.candidate_artifact_hash,
            symbol=symbol,
            bundle_hash=self.learner.bundle_hash,
            dataset_registry_hash=self.learner.dataset_registry_hash,
            feature_ids=self.learner.feature_ids,
            time_start=time_start,
            time_end=time_end,
            row_count=len(input_frame),
        )
        return LearnerInputWindow(spec=spec, frame=input_frame)


__all__ = [
    "LearnerInputMaterializer",
    "LearnerInputWindow",
    "LearnerInputWindowSpec",
]
