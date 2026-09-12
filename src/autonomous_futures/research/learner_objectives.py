from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

import pandas as pd

from ..data.parquet import DataQualityError
from .learner_training import LearnerTrainingOutput


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataQualityError(f"invalid {field} value") from exc
    if not result.is_finite():
        raise DataQualityError(f"{field} value must be finite")
    return result


def fit_next_bar_direction(
    frames: Mapping[str, pd.DataFrame],
) -> LearnerTrainingOutput:
    """Fit a deterministic return-sign bucket model for ``close[t+1] > close[t]``."""
    if not frames:
        raise DataQualityError("next_bar_direction training requires frames")

    buckets: dict[str, dict[str, int]] = {
        "non_positive": {"down_or_flat": 0, "up": 0},
        "positive": {"down_or_flat": 0, "up": 0},
    }
    symbols = tuple(sorted(frames))
    observations = 0
    for symbol in symbols:
        frame = frames[symbol]
        if not isinstance(frame, pd.DataFrame):
            raise DataQualityError("next_bar_direction training frames must be DataFrames")
        missing = {"close", "returns"}.difference(frame.columns)
        if missing:
            raise DataQualityError(
                "next_bar_direction training frame is missing: " + ", ".join(sorted(missing))
            )
        if len(frame) < 2:
            continue
        for index in range(len(frame) - 1):
            raw_return = frame.iloc[index]["returns"]
            if raw_return is None or bool(pd.isna(raw_return)):
                continue
            feature = _decimal(raw_return, field="returns")
            current_close = _decimal(frame.iloc[index]["close"], field="close")
            next_close = _decimal(frame.iloc[index + 1]["close"], field="close")
            bucket = "positive" if feature > 0 else "non_positive"
            label = "up" if next_close > current_close else "down_or_flat"
            buckets[bucket][label] += 1
            observations += 1

    if observations == 0:
        raise DataQualityError("next_bar_direction training requires usable observations")

    payload = {
        "objective": "next_bar_direction",
        "target_definition": "close[t+1] > close[t]",
        "feature_ids": ["returns"],
        "feature_shift": 1,
        "model_family": "next_bar_direction_bucket",
        "learner_version": "next-bar-direction-v1",
        "symbols": list(symbols),
        "observations": observations,
        "buckets": buckets,
    }
    return LearnerTrainingOutput(
        model_artifact_ref="next-bar-direction.json",
        model_family="next_bar_direction_bucket",
        learner_version="next-bar-direction-v1",
        model_bytes=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    )


__all__ = ["fit_next_bar_direction"]
