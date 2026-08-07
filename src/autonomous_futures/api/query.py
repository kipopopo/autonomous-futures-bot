from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pandas as pd

from ..data.builder import KlineInterval
from ..data.derivatives_artifacts import read_funding_artifact, read_mark_price_artifact
from ..data.parquet import read_canonical_parquet
from ..data.registry import DatasetRegistryEntry
from .artifacts import ArtifactInspection, resolve_artifact_ref

QueryableDatasetKind = Literal["kline", "funding_rate", "mark_price"]
JSONScalar = str | int | float | bool | None
MAX_QUERY_ROWS = 1_000

_INTERVALS: dict[str, timedelta] = {"5m": timedelta(minutes=5), "15m": timedelta(minutes=15)}


class QueryError(ValueError):
    """A read-only dataset query cannot satisfy its contract."""


class QueryCoverageError(QueryError):
    """The requested half-open range is outside the persisted component."""


class QueryLimitError(QueryError):
    """The result exceeds the explicit hard row limit."""


class QueryDataIntegrityError(QueryError):
    """The verified artifact cannot be read as its declared canonical data."""


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise QueryCoverageError(f"{field} must be timezone-aware UTC")
    return value.astimezone(UTC)


def _interval_delta(interval: str | None) -> timedelta:
    if interval is None or interval not in _INTERVALS:
        raise QueryError("kline and mark_price queries require interval 5m or 15m")
    return _INTERVALS[interval]


def _kline_interval(interval: str | None) -> KlineInterval:
    if interval not in _INTERVALS:
        raise QueryError("kline and mark_price queries require interval 5m or 15m")
    return cast(KlineInterval, interval)


def _coverage(entry: DatasetRegistryEntry) -> tuple[datetime, datetime]:
    if entry.time_start is None or entry.time_end is None:
        raise QueryCoverageError("component does not declare a queryable time coverage")
    end = entry.time_end
    if entry.kind == "kline":
        end += _interval_delta(entry.interval)
    return entry.time_start, end


def _json_scalar(value: object) -> JSONScalar:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None or value.utcoffset() is None:
            raise QueryDataIntegrityError("dataset timestamp is not timezone-aware")
        return cast(str, value.tz_convert(UTC).isoformat().replace("+00:00", "Z"))
    if isinstance(value, datetime):
        return _json_scalar(pd.Timestamp(value))
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "item"):
        return _json_scalar(cast(object, value.item()))
    if isinstance(value, (str, int, float, bool)):
        return value
    raise QueryDataIntegrityError(f"unsupported dataset value type: {type(value).__name__}")


def _rows_to_json(frame: pd.DataFrame) -> tuple[dict[str, JSONScalar], ...]:
    return tuple(
        {str(column): _json_scalar(value) for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    )


def query_component_rows(
    artifact_root: Path,
    entry: DatasetRegistryEntry,
    inspection: ArtifactInspection,
    *,
    start: datetime,
    end: datetime,
    limit: int,
) -> tuple[dict[str, JSONScalar], ...]:
    if limit < 1 or limit > MAX_QUERY_ROWS:
        raise QueryLimitError(f"limit must be between 1 and {MAX_QUERY_ROWS}")
    if inspection.kind != entry.kind or inspection.data_ref is None:
        raise QueryDataIntegrityError("artifact inspection is not queryable for the component")

    query_start = _utc(start, field="start")
    query_end = _utc(end, field="end")
    if query_start >= query_end:
        raise QueryCoverageError("start must be before end")
    coverage_start, coverage_end = _coverage(entry)
    if query_start < coverage_start or query_end > coverage_end:
        raise QueryCoverageError("query range is outside component coverage")

    data_path = resolve_artifact_ref(artifact_root, inspection.data_ref)
    component_start, component_end = _coverage(entry)
    try:
        if entry.kind == "kline":
            frame = read_canonical_parquet(data_path, interval=_interval_delta(entry.interval))
            timestamp_column = "timestamp"
        elif entry.kind == "mark_price":
            frame = read_mark_price_artifact(
                data_path,
                symbol=entry.symbols[0],
                interval=_kline_interval(entry.interval),
                time_start=component_start,
                time_end=component_end,
            )
            timestamp_column = "timestamp"
        elif entry.kind == "funding_rate":
            frame = read_funding_artifact(
                data_path,
                symbol=entry.symbols[0],
                time_start=component_start,
                time_end=component_end,
            )
            timestamp_column = "funding_time"
        else:
            raise QueryError("exchange_filters is metadata-only and has no row query")
    except QueryError:
        raise
    except (OSError, ValueError) as exc:
        raise QueryDataIntegrityError("verified artifact could not be read") from exc

    timestamps = pd.to_datetime(frame[timestamp_column], utc=True, errors="raise")
    selected = frame.loc[
        (timestamps >= pd.Timestamp(query_start)) & (timestamps < pd.Timestamp(query_end))
    ]
    if len(selected) > limit:
        raise QueryLimitError("query result exceeds limit; narrow the requested range")
    return _rows_to_json(selected.reset_index(drop=True))


__all__ = [
    "JSONScalar",
    "MAX_QUERY_ROWS",
    "QueryCoverageError",
    "QueryDataIntegrityError",
    "QueryError",
    "QueryLimitError",
    "QueryableDatasetKind",
    "query_component_rows",
]
