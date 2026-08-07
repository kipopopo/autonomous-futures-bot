from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from ..data.parquet import DataQualityError, canonicalize_bars
from .cached_evaluation import (
    CachedEvaluationRun,
    CachedEvaluationWindow,
    CachedOnlyEvaluatorAdapter,
)

_CONTEXT_COLUMNS = ("timestamp", "open", "high", "low", "close", "close_time")


def _require_utc_close_times(frame: pd.DataFrame) -> None:
    for value in frame["close_time"]:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise DataQualityError("context close_time must be timezone-aware UTC")


def _canonical_context(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(_CONTEXT_COLUMNS).difference(frame.columns))
    if missing:
        raise DataQualityError("context frame is missing columns: " + ", ".join(missing))
    _require_utc_close_times(frame)
    canonical = canonicalize_bars(frame, interval=timedelta(minutes=15))
    canonical["close_time"] = pd.to_datetime(canonical["close_time"], utc=True, errors="raise")
    expected_close_times = (
        pd.DatetimeIndex(canonical["timestamp"]) + timedelta(minutes=15) - timedelta(milliseconds=1)
    )
    if not canonical["close_time"].eq(expected_close_times).all():
        raise DataQualityError("context close_time does not match 15m candle boundaries")
    return canonical.loc[:, _CONTEXT_COLUMNS].copy(deep=True)


def materialize_causal_context(
    primary: pd.DataFrame,
    context: pd.DataFrame,
) -> pd.DataFrame:
    """Attach only closed 15m context values to a canonical 5m primary frame."""
    primary_canonical = canonicalize_bars(
        primary,
        interval=timedelta(minutes=5),
    )
    context_canonical = _canonical_context(context)

    context_for_merge = context_canonical.rename(
        columns={
            "timestamp": "context_timestamp",
            "open": "context_open",
            "high": "context_high",
            "low": "context_low",
            "close": "context_close",
            "close_time": "context_close_time",
        }
    )
    context_for_merge["context_available_at"] = context_for_merge["context_close_time"] + timedelta(
        milliseconds=1
    )
    context_for_merge = context_for_merge.sort_values("context_available_at", kind="mergesort")

    merged = pd.merge_asof(
        primary_canonical.sort_values("timestamp", kind="mergesort"),
        context_for_merge,
        left_on="timestamp",
        right_on="context_available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    return merged.reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class CausalCachedEvaluatorAdapter:
    """Materialize causal context before invoking the cached-only evaluator."""

    adapter: CachedOnlyEvaluatorAdapter

    def evaluate(
        self,
        windows: Sequence[CachedEvaluationWindow],
        *,
        context_frames: Mapping[str, pd.DataFrame],
        evaluated_at: datetime,
    ) -> CachedEvaluationRun:
        materialized_windows: list[CachedEvaluationWindow] = []
        for window in windows:
            window_id = window.spec.window_id
            if window_id not in context_frames:
                raise DataQualityError(f"missing context frame for window: {window_id}")
            causal_frame = materialize_causal_context(
                window.frame,
                context_frames[window_id],
            )
            materialized_windows.append(
                CachedEvaluationWindow(spec=window.spec, frame=causal_frame)
            )
        return self.adapter.evaluate(materialized_windows, evaluated_at=evaluated_at)


__all__ = [
    "CausalCachedEvaluatorAdapter",
    "materialize_causal_context",
]
