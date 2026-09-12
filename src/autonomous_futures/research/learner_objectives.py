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


def _parse_next_bar_direction_model(model_bytes: bytes) -> dict[str, dict[str, int]]:
    try:
        payload = json.loads(model_bytes.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataQualityError("next_bar_direction model is invalid") from exc
    if not isinstance(payload, dict):
        raise DataQualityError("next_bar_direction model is invalid")
    if (
        payload.get("objective") != "next_bar_direction"
        or payload.get("target_definition") != "close[t+1] > close[t]"
        or payload.get("feature_ids") != ["returns"]
        or payload.get("feature_shift") != 1
        or payload.get("model_family") != "next_bar_direction_bucket"
        or payload.get("learner_version") != "next-bar-direction-v1"
    ):
        raise DataQualityError("next_bar_direction model contract mismatch")
    observations = payload.get("observations")
    buckets = payload.get("buckets")
    if (
        isinstance(observations, bool)
        or not isinstance(observations, int)
        or observations <= 0
        or not isinstance(buckets, dict)
    ):
        raise DataQualityError("next_bar_direction model counts are invalid")
    parsed: dict[str, dict[str, int]] = {}
    for bucket_name in ("non_positive", "positive"):
        bucket = buckets.get(bucket_name)
        if not isinstance(bucket, dict):
            raise DataQualityError("next_bar_direction model buckets are invalid")
        counts: dict[str, int] = {}
        for label in ("down_or_flat", "up"):
            count = bucket.get(label)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise DataQualityError("next_bar_direction model counts are invalid")
            counts[label] = count
        parsed[bucket_name] = counts
    if sum(sum(counts.values()) for counts in parsed.values()) != observations:
        raise DataQualityError("next_bar_direction model observation count is invalid")
    return parsed


def next_bar_direction_signals(
    model_bytes: bytes,
    frame: pd.DataFrame,
) -> pd.Series:
    """Return deterministic direction signals from the causal return feature."""
    if not isinstance(frame, pd.DataFrame) or "returns" not in frame.columns:
        raise DataQualityError("next_bar_direction signals require returns")
    buckets = _parse_next_bar_direction_model(model_bytes)
    signals: list[int] = []
    for raw_return in frame["returns"]:
        if raw_return is None or bool(pd.isna(raw_return)):
            signals.append(0)
            continue
        feature = _decimal(raw_return, field="returns")
        bucket = buckets["positive" if feature > 0 else "non_positive"]
        if bucket["up"] > bucket["down_or_flat"]:
            signals.append(1)
        elif bucket["down_or_flat"] > bucket["up"]:
            signals.append(-1)
        else:
            signals.append(0)
    return pd.Series(signals, index=frame.index, dtype="int8")


__all__ = ["fit_next_bar_direction", "next_bar_direction_signals"]
