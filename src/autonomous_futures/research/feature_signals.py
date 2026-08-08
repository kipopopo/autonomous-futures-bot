from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from ..data.parquet import DataQualityError, canonicalize_bars
from .creator_artifacts import CreatorCandidateArtifact

_SUPPORTED_FEATURES = frozenset(
    {"returns", "ema_slope", "donchian_high", "donchian_low", "regime_trend"}
)
_REQUIRED_OHLC = ("open", "high", "low", "close")
_COMPARISON = re.compile(
    r"^(?P<feature>[a-z_][a-z0-9_]*)\s*"
    r"(?P<operator>>=|<=|==|>|<)\s*"
    r"(?P<value>-?(?:\d+(?:\.\d*)?|\.\d+))$"
)


def _parse_expression(
    expression: str,
) -> tuple[tuple[tuple[str, str, float], ...], tuple[str, ...]]:
    parts = re.split(r"\s+(and|or)\s+", expression.strip())
    if len(parts) % 2 == 0 or not parts:
        raise DataQualityError("signal expression must use bounded comparisons")
    clauses: list[tuple[str, str, float]] = []
    for clause in parts[::2]:
        match = _COMPARISON.fullmatch(clause)
        if match is None:
            raise DataQualityError("signal expression must use bounded comparisons")
        clauses.append(
            (
                match.group("feature"),
                match.group("operator"),
                float(match.group("value")),
            )
        )
    connectors = tuple(str(part) for part in parts[1::2])
    return tuple(clauses), connectors


def _finite_positive_series(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.isna().any() or not values.map(math.isfinite).all():
        raise DataQualityError(f"OHLC column is not finite: {column}")
    if (values <= 0).any():
        raise DataQualityError(f"OHLC column must be positive: {column}")
    return values.astype(float)


def _feature_series(
    name: str,
    *,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    lookback: int,
    shift: int,
) -> pd.Series:
    if name == "returns":
        raw = close.pct_change(fill_method=None)
    elif name == "ema_slope":
        ema = close.ewm(span=lookback, adjust=False, min_periods=lookback).mean()
        raw = ema.diff()
    elif name == "donchian_high":
        raw = high.rolling(window=lookback, min_periods=lookback).max()
    elif name == "donchian_low":
        raw = low.rolling(window=lookback, min_periods=lookback).min()
    else:
        ema = close.ewm(span=lookback, adjust=False, min_periods=lookback).mean()
        slope = ema.diff()
        raw = slope.gt(0).astype(float) - slope.lt(0).astype(float)
    return raw.shift(shift)


def _compare(values: pd.Series, operator: str, threshold: float) -> pd.Series:
    if operator == ">":
        result = values > threshold
    elif operator == ">=":
        result = values >= threshold
    elif operator == "<":
        result = values < threshold
    elif operator == "<=":
        result = values <= threshold
    else:
        result = values == threshold
    return result.fillna(False).astype(bool)


@dataclass(frozen=True, slots=True)
class CausalFeatureSignalEvaluator:
    """Compute a bounded feature set and fresh-state signals from cached OHLC bars."""

    def evaluate(self, candidate: CreatorCandidateArtifact, frame: pd.DataFrame) -> pd.DataFrame:
        missing = sorted(set(_REQUIRED_OHLC).difference(frame.columns))
        if missing:
            raise DataQualityError(
                "feature evaluator is missing OHLC columns: " + ", ".join(missing)
            )
        canonical = canonicalize_bars(frame, interval=timedelta(minutes=5))
        close = _finite_positive_series(canonical, "close")
        high = _finite_positive_series(canonical, "high")
        low = _finite_positive_series(canonical, "low")
        _finite_positive_series(canonical, "open")

        feature_refs = candidate.strategy.features
        feature_names = tuple(feature.name for feature in feature_refs)
        if len(set(feature_names)) != len(feature_names):
            raise DataQualityError("candidate features must be unique")
        if unsupported := sorted(set(feature_names).difference(_SUPPORTED_FEATURES)):
            raise DataQualityError("feature is not supported: " + ", ".join(unsupported))

        long_clauses, long_connectors = _parse_expression(candidate.strategy.entry.long)
        short_clauses, short_connectors = _parse_expression(candidate.strategy.entry.short)
        expression_features = tuple(sorted({clause[0] for clause in long_clauses + short_clauses}))
        undeclared = sorted(set(expression_features).difference(feature_names))
        if undeclared:
            raise DataQualityError("signal feature is not declared: " + ", ".join(undeclared))
        unsupported_expression = sorted(set(expression_features).difference(_SUPPORTED_FEATURES))
        if unsupported_expression:
            raise DataQualityError(
                "signal feature is not supported: " + ", ".join(unsupported_expression)
            )

        result = canonical.copy(deep=True)
        for feature_ref in feature_refs:
            result[feature_ref.name] = _feature_series(
                feature_ref.name,
                close=close,
                high=high,
                low=low,
                lookback=feature_ref.lookback,
                shift=feature_ref.shift,
            )

        long_condition = self._condition_series(result, long_clauses, long_connectors)
        short_condition = self._condition_series(result, short_clauses, short_connectors)
        if (long_condition & short_condition).any():
            raise DataQualityError("a candle cannot have both long and short conditions")
        long_entry = long_condition & ~long_condition.shift(1, fill_value=False)
        short_entry = short_condition & ~short_condition.shift(1, fill_value=False)
        signal = pd.Series(0, index=result.index, dtype="int8")
        signal.loc[long_entry] = 1
        signal.loc[short_entry] = -1
        result["long_condition"] = long_condition
        result["short_condition"] = short_condition
        result["long_entry"] = long_entry
        result["short_entry"] = short_entry
        result["signal"] = signal
        return result

    @staticmethod
    def _condition_series(
        frame: pd.DataFrame,
        clauses: tuple[tuple[str, str, float], ...],
        connectors: tuple[str, ...],
    ) -> pd.Series:
        condition = _compare(frame[clauses[0][0]], clauses[0][1], clauses[0][2])
        for connector, clause in zip(connectors, clauses[1:], strict=True):
            next_condition = _compare(frame[clause[0]], clause[1], clause[2])
            if connector == "and":
                condition = condition & next_condition
            else:
                condition = condition | next_condition
        return condition.astype(bool)


__all__ = ["CausalFeatureSignalEvaluator"]
