from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

import pandas as pd
from pydantic import BaseModel

from ..domain.errors import DomainViolation


class DataQualityError(DomainViolation):
    """Raised when raw bars cannot satisfy the canonical data contract."""


class TimestampGap(BaseModel):
    previous: datetime
    expected_next: datetime
    actual_next: datetime


def _require_aware_timestamps(values: Iterable[object]) -> None:
    for value in values:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise DataQualityError("timestamps must be UTC-aware")


def find_timestamp_gaps(
    timestamps: Iterable[datetime], *, interval: timedelta
) -> tuple[TimestampGap, ...]:
    ordered = tuple(timestamps)
    gaps: list[TimestampGap] = []
    for previous, actual_next in zip(ordered, ordered[1:], strict=False):
        expected_next = previous + interval
        if actual_next != expected_next:
            gaps.append(
                TimestampGap(
                    previous=previous,
                    expected_next=expected_next,
                    actual_next=actual_next,
                )
            )
    return tuple(gaps)


def canonicalize_bars(
    frame: pd.DataFrame,
    *,
    interval: timedelta,
    timestamp_column: str = "timestamp",
) -> pd.DataFrame:
    if timestamp_column not in frame.columns:
        raise DataQualityError(f"missing timestamp column: {timestamp_column}")
    if frame.empty:
        raise DataQualityError("dataset must contain at least one row")

    _require_aware_timestamps(frame[timestamp_column].tolist())
    canonical = frame.copy()
    canonical[timestamp_column] = pd.to_datetime(
        canonical[timestamp_column], utc=True, errors="raise"
    )
    if canonical[timestamp_column].duplicated().any():
        raise DataQualityError("duplicate timestamps are not allowed")

    canonical = canonical.sort_values(timestamp_column, kind="mergesort").reset_index(drop=True)
    timestamps = tuple(canonical[timestamp_column].dt.to_pydatetime())
    gaps = find_timestamp_gaps(timestamps, interval=interval)
    if gaps:
        first_gap = gaps[0]
        raise DataQualityError(
            "timestamp gap: "
            f"expected {first_gap.expected_next.isoformat()} "
            f"but received {first_gap.actual_next.isoformat()}"
        )
    return canonical
