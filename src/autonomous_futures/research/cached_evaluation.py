from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import Field, ValidationError, field_validator, model_validator

from ..data.parquet import DataQualityError, canonicalize_bars
from ..data.verified_funding import VerifiedFundingSlice, load_verified_funding_slice
from ..domain.contracts import DomainModel
from .creator_artifacts import CreatorCandidateArtifact
from .qualification_artifacts import QualificationGateResult, QualificationMetric
from .trade_simulation import _funding_events_by_time


class CachedEvaluationWindowSpec(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    funding_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    time_start: datetime
    time_end: datetime
    timeframe: Literal["5m", "15m", "1h"] = "5m"

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


def _timeframe_to_timedelta(timeframe: str) -> timedelta:
    if timeframe == "5m":
        return timedelta(minutes=5)
    if timeframe == "15m":
        return timedelta(minutes=15)
    if timeframe == "1h":
        return timedelta(hours=1)
    return timedelta(minutes=5)


@dataclass(frozen=True, slots=True, init=False)
class CachedEvaluationWindow:
    spec: CachedEvaluationWindowSpec
    _frame: pd.DataFrame = field(repr=False)
    _funding_events: pd.DataFrame | None = field(repr=False)
    funding_slice: VerifiedFundingSlice | None = None

    def __init__(
        self,
        spec: CachedEvaluationWindowSpec,
        frame: pd.DataFrame,
        funding_events: pd.DataFrame | None = None,
        funding_slice: VerifiedFundingSlice | None = None,
    ) -> None:
        object.__setattr__(self, "spec", spec)
        object.__setattr__(self, "_frame", frame.copy(deep=True))
        object.__setattr__(
            self,
            "_funding_events",
            funding_events.copy(deep=True) if funding_events is not None else None,
        )
        object.__setattr__(self, "funding_slice", funding_slice)
        self.__post_init__()

    def __post_init__(self) -> None:
        required_columns = {"timestamp", "open", "high", "low", "close"}
        missing_columns = sorted(required_columns.difference(self._frame.columns))
        if missing_columns:
            raise DataQualityError(
                "cached evaluation frame is missing OHLC columns: " + ", ".join(missing_columns)
            )
        delta = _timeframe_to_timedelta(self.spec.timeframe)
        canonical = canonicalize_bars(self._frame, interval=delta)
        timestamps = pd.DatetimeIndex(canonical["timestamp"])
        expected_start = pd.Timestamp(self.spec.time_start)
        expected_end = pd.Timestamp(self.spec.time_end)
        if timestamps[0] != expected_start or timestamps[-1] + delta != expected_end:
            raise DataQualityError("cached evaluation frame must cover exactly the window range")
        if self.funding_slice is None and (
            (self._funding_events is None) != (self.spec.funding_artifact_hash is None)
        ):
            raise DataQualityError(
                "cached funding events and derivative manifest hash must be paired"
            )
        funding = self._funding_events
        if self.funding_slice is not None:
            if (
                self.spec.funding_artifact_hash != self.funding_slice.manifest_hash
                or self.spec.bundle_hash != self.funding_slice.bundle_hash
                or self.spec.dataset_registry_hash != self.funding_slice.dataset_registry_hash
                or self.spec.symbol != self.funding_slice.symbol
                or self.spec.time_start != self.funding_slice.time_start
                or self.spec.time_end != self.funding_slice.time_end
            ):
                raise DataQualityError("verified funding slice does not match cached window scope")
            verified_events = self.funding_slice.copy_events()
            if funding is not None:
                try:
                    pd.testing.assert_frame_equal(
                        funding.reset_index(drop=True),
                        verified_events,
                        check_dtype=False,
                        check_exact=True,
                    )
                except AssertionError as exc:
                    raise DataQualityError(
                        "cached funding events differ from verified slice"
                    ) from exc
            funding = verified_events
        if funding is not None:
            funding = funding.copy(deep=True)
            _funding_events_by_time(
                funding,
                symbol=self.spec.symbol,
                bar_timestamps=tuple(timestamp.to_pydatetime() for timestamp in timestamps),
                interval=delta,
            )
            object.__setattr__(self, "_funding_events", funding.copy(deep=True))
        object.__setattr__(self, "_frame", canonical.copy(deep=True))

    @property
    def frame(self) -> pd.DataFrame:
        """Expose only a copy so caller mutation cannot rewrite cached source rows."""
        return self._frame.copy(deep=True)

    @property
    def funding_events(self) -> pd.DataFrame | None:
        """Expose only a copy so caller mutation cannot rewrite derivative rows."""
        return self._funding_events.copy(deep=True) if self._funding_events is not None else None

    def copy_frame(self) -> pd.DataFrame:
        """Return an isolated frame; evaluator code cannot mutate the cached source frame."""
        return self._frame.copy(deep=True)

    def copy_funding_events(self) -> pd.DataFrame | None:
        """Return an isolated derivative-event frame, if its manifest is bound."""
        if self.funding_slice is not None:
            return self.funding_slice.copy_events()
        return self._funding_events.copy(deep=True) if self._funding_events is not None else None


def load_verified_cached_evaluation_window(
    *,
    window_id: str,
    symbol: str,
    bundle_hash: str,
    dataset_registry_hash: str,
    time_start: datetime,
    time_end: datetime,
    timeframe: Literal["5m", "15m", "1h"],
    frame: pd.DataFrame,
    artifact_root: Path,
    bundle_path: Path,
    registry_path: Path,
) -> CachedEvaluationWindow:
    """Build a cached window with its funding bytes verified against its exact catalog."""
    interval = _timeframe_to_timedelta(timeframe)
    canonical = canonicalize_bars(frame, interval=interval)
    bar_timestamps = tuple(
        timestamp.to_pydatetime() for timestamp in pd.DatetimeIndex(canonical["timestamp"])
    )
    funding_slice = load_verified_funding_slice(
        artifact_root=artifact_root,
        bundle_path=bundle_path,
        registry_path=registry_path,
        symbol=symbol,
        time_start=time_start,
        time_end=time_end,
        bar_timestamps=bar_timestamps,
        expected_bundle_hash=bundle_hash,
        expected_registry_hash=dataset_registry_hash,
    )
    spec = CachedEvaluationWindowSpec(
        window_id=window_id,
        symbol=symbol,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        funding_artifact_hash=funding_slice.manifest_hash,
        time_start=time_start,
        time_end=time_end,
        timeframe=timeframe,
    )
    return CachedEvaluationWindow(spec=spec, frame=canonical, funding_slice=funding_slice)


class CachedWindowEvaluation(DomainModel):
    window_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    symbol: str = Field(pattern=r"^[A-Z0-9]+$")
    funding_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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
    evaluation_version: Literal[1, 2] = 1
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
        funding_bound = all(window.funding_artifact_hash is not None for window in self.windows)
        if self.evaluation_version == 2 and not funding_bound:
            raise ValueError("version 2 cached evaluation requires funding-bound windows")
        if self.evaluation_version == 1 and any(
            window.funding_artifact_hash is not None for window in self.windows
        ):
            raise ValueError("version 1 cached evaluation cannot include funding bindings")
        return self


CachedEvaluator = Callable[
    [CreatorCandidateArtifact, pd.DataFrame, CachedEvaluationWindow], CachedWindowEvaluation
]


def _is_safe_identifier(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def _evaluation_content_hash(run: CachedEvaluationRun) -> str:
    payload = run.model_dump(mode="json", exclude={"evaluated_at", "evaluation_hash"})
    if run.evaluation_version == 1:
        for window in payload["windows"]:
            window.pop("funding_artifact_hash", None)
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
        funding_modes = {window.spec.funding_artifact_hash is not None for window in windows}
        if len(funding_modes) != 1:
            raise DataQualityError("cached evaluation cannot mix funding-bound and legacy windows")
        funding_bound = True in funding_modes
        for window in windows:
            if funding_bound:
                verified_slice = window.funding_slice
                if (
                    verified_slice is None
                    or verified_slice.manifest_hash != window.spec.funding_artifact_hash
                ):
                    raise DataQualityError(
                        "funding-bound cached evaluation requires a verified funding artifact slice"
                    )
            elif window.funding_events is not None or window.funding_slice is not None:
                raise DataQualityError("legacy cached evaluation cannot carry funding events")
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
            isolated_window = CachedEvaluationWindow(
                spec=spec,
                frame=window.copy_frame(),
                funding_events=window.copy_funding_events(),
                funding_slice=window.funding_slice,
            )
            result = self.evaluator(self.candidate, isolated_window.copy_frame(), isolated_window)
            if result.window_id != spec.window_id or result.symbol != spec.symbol:
                raise DataQualityError(
                    "cached evaluator result window identity does not match input"
                )
            if funding_bound:
                if result.funding_artifact_hash not in (None, spec.funding_artifact_hash):
                    raise DataQualityError(
                        "cached evaluator result funding binding does not match input"
                    )
                result = result.model_copy(
                    update={"funding_artifact_hash": spec.funding_artifact_hash}
                )
            elif result.funding_artifact_hash is not None:
                raise DataQualityError("legacy cached evaluation result cannot bind funding")
            results.append(result)
        try:
            provisional = CachedEvaluationRun(
                evaluation_version=2 if funding_bound else 1,
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
