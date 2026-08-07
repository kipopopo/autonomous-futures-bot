from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .parquet import DataQualityError
from .registry import DatasetKind, DatasetRegistry, DatasetRegistryEntry


class DatasetBundle(DomainModel):
    bundle_version: Literal[1] = 1
    venue: Literal["BINANCE_USDS_M_FUTURES"] = "BINANCE_USDS_M_FUTURES"
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbols: tuple[str, ...] = Field(min_length=1)
    primary_interval: Literal["5m"] = "5m"
    context_interval: Literal["15m"] = "15m"
    context_feature_policy: Literal["close_time_plus_1ms"] = "close_time_plus_1ms"
    time_start: datetime
    time_end: datetime
    components: tuple[DatasetRegistryEntry, ...] = Field(min_length=1)
    created_at: datetime
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("symbols")
    @classmethod
    def symbols_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(value)):
            raise ValueError("bundle symbols must be sorted")
        if len(set(value)) != len(value):
            raise ValueError("bundle symbols must be unique")
        if any(not item or item != item.upper() for item in value):
            raise ValueError("bundle symbols must be uppercase")
        return value

    @field_validator("time_start", "time_end", "created_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("bundle timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("components")
    @classmethod
    def components_are_sorted(
        cls, value: tuple[DatasetRegistryEntry, ...]
    ) -> tuple[DatasetRegistryEntry, ...]:
        keys = tuple(_component_identity(item) for item in value)
        if keys != tuple(sorted(keys)):
            raise ValueError("bundle components must be sorted")
        if len(set(keys)) != len(keys):
            raise ValueError("bundle components must be unique")
        return value

    @model_validator(mode="after")
    def validate_bundle(self) -> DatasetBundle:
        if self.time_start >= self.time_end:
            raise ValueError("bundle time_start must be before time_end")
        _validate_component_set(
            self.components,
            symbols=self.symbols,
            time_start=self.time_start,
            time_end=self.time_end,
            primary_interval=self.primary_interval,
            context_interval=self.context_interval,
        )
        return self


def _component_identity(entry: DatasetRegistryEntry) -> tuple[object, ...]:
    return (
        entry.kind,
        entry.symbols,
        entry.interval or "",
        entry.time_start.isoformat() if entry.time_start is not None else "",
        entry.time_end.isoformat() if entry.time_end is not None else "",
        entry.content_hash,
    )


def context_bar_is_usable(context_open: datetime, *, primary_timestamp: datetime) -> bool:
    for value in (context_open, primary_timestamp):
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise DataQualityError("context timestamps must be timezone-aware UTC")
    available_at = context_open.astimezone(UTC) + timedelta(minutes=15)
    return primary_timestamp.astimezone(UTC) >= available_at


def _validate_component_set(
    components: Sequence[DatasetRegistryEntry],
    *,
    symbols: tuple[str, ...],
    time_start: datetime,
    time_end: datetime,
    primary_interval: Literal["5m"],
    context_interval: Literal["15m"],
) -> None:
    bar_end = time_end - timedelta(minutes=5)
    expected_count = len(symbols) * 4 + 1
    if len(components) != expected_count:
        raise ValueError(
            "bundle requires "
            f"{expected_count} components for symbol universe, got {len(components)}"
        )

    for symbol in symbols:
        primary_matches = [
            entry
            for entry in components
            if entry.kind == "kline"
            and entry.symbols == (symbol,)
            and entry.interval == primary_interval
            and entry.time_start == time_start
            and entry.time_end == bar_end
        ]
        if len(primary_matches) != 1:
            raise ValueError(f"missing or ambiguous 5m kline component for {symbol}")

        context_matches = [
            entry
            for entry in components
            if entry.kind == "kline"
            and entry.symbols == (symbol,)
            and entry.interval == context_interval
            and entry.time_start is not None
            and entry.time_end is not None
            and entry.time_start <= time_start
            and entry.time_end + timedelta(minutes=15) >= time_end
        ]
        if len(context_matches) != 1:
            raise ValueError(f"missing or ambiguous 15m context coverage for {symbol}")

        mark_matches = [
            entry
            for entry in components
            if entry.kind == "mark_price"
            and entry.symbols == (symbol,)
            and entry.interval == primary_interval
            and entry.time_start == time_start
            and entry.time_end == time_end
        ]
        if len(mark_matches) != 1:
            raise ValueError(f"missing or ambiguous mark_price component for {symbol}")

        funding_matches = [
            entry
            for entry in components
            if entry.kind == "funding_rate"
            and entry.symbols == (symbol,)
            and entry.interval is None
            and entry.time_start is not None
            and entry.time_end is not None
            and entry.time_start <= time_start
            and entry.time_end >= time_end
        ]
        if len(funding_matches) != 1:
            raise ValueError(f"missing or ambiguous funding_rate coverage for {symbol}")

    filter_matches = [
        entry
        for entry in components
        if entry.kind == "exchange_filters"
        and entry.symbols == symbols
        and entry.interval is None
        and entry.time_start is None
        and entry.time_end is None
    ]
    if len(filter_matches) != 1:
        raise ValueError("missing or ambiguous exchange_filters symbol universe")


def _bundle_content_hash(bundle: DatasetBundle) -> str:
    payload = bundle.model_dump(mode="json", exclude={"created_at", "bundle_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def _utc_range(time_start: datetime, time_end: datetime) -> tuple[datetime, datetime]:
    values = (time_start, time_end)
    if any(value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value) for value in values):
        raise DataQualityError("bundle time range must be timezone-aware UTC")
    start = time_start.astimezone(UTC)
    end = time_end.astimezone(UTC)
    if start >= end:
        raise DataQualityError("bundle time_start must be before time_end")
    return start, end


def build_dataset_bundle(
    registry: DatasetRegistry,
    *,
    symbols: Sequence[str],
    time_start: datetime,
    time_end: datetime,
    created_at: datetime,
    primary_interval: Literal["5m"] = "5m",
    context_interval: Literal["15m"] = "15m",
) -> DatasetBundle:
    canonical_symbols = tuple(sorted(symbols))
    if not canonical_symbols or any(
        not symbol or symbol != symbol.upper() for symbol in canonical_symbols
    ):
        raise DataQualityError("bundle symbols must be non-empty uppercase values")
    start, end = _utc_range(time_start, time_end)

    selected: list[DatasetRegistryEntry] = []
    bar_end = end - timedelta(minutes=5)
    for symbol in canonical_symbols:
        primary_matches = [
            entry
            for entry in registry.entries
            if entry.kind == "kline"
            and entry.symbols == (symbol,)
            and entry.interval == primary_interval
            and entry.time_start == start
            and entry.time_end == bar_end
        ]
        if len(primary_matches) != 1:
            raise DataQualityError(f"missing or ambiguous 5m kline component for {symbol}")
        selected.append(primary_matches[0])

        context_matches = [
            entry
            for entry in registry.entries
            if entry.kind == "kline"
            and entry.symbols == (symbol,)
            and entry.interval == context_interval
            and entry.time_start is not None
            and entry.time_end is not None
            and entry.time_start <= start
            and entry.time_end + timedelta(minutes=15) >= end
        ]
        if len(context_matches) != 1:
            raise DataQualityError(f"missing or ambiguous 15m context coverage for {symbol}")
        selected.append(context_matches[0])

        mark_matches = [
            entry
            for entry in registry.entries
            if entry.kind == "mark_price"
            and entry.symbols == (symbol,)
            and entry.interval == primary_interval
            and entry.time_start == start
            and entry.time_end == end
        ]
        if len(mark_matches) != 1:
            raise DataQualityError(f"missing or ambiguous mark_price component for {symbol}")
        selected.append(mark_matches[0])

        funding_matches = [
            entry
            for entry in registry.entries
            if entry.kind == "funding_rate"
            and entry.symbols == (symbol,)
            and entry.interval is None
            and entry.time_start is not None
            and entry.time_end is not None
            and entry.time_start <= start
            and entry.time_end >= end
        ]
        if len(funding_matches) != 1:
            raise DataQualityError(f"missing or ambiguous funding_rate coverage for {symbol}")
        selected.append(funding_matches[0])

    filter_matches = [
        entry
        for entry in registry.entries
        if entry.kind == "exchange_filters"
        and entry.symbols == canonical_symbols
        and entry.interval is None
        and entry.time_start is None
        and entry.time_end is None
    ]
    if len(filter_matches) != 1:
        raise DataQualityError("missing or ambiguous exchange_filters symbol universe")
    selected.append(filter_matches[0])

    components = tuple(sorted(selected, key=_component_identity))
    try:
        provisional = DatasetBundle(
            registry_hash=registry.registry_hash,
            symbols=canonical_symbols,
            primary_interval=primary_interval,
            context_interval=context_interval,
            time_start=start,
            time_end=end,
            components=components,
            created_at=created_at.astimezone(UTC),
            bundle_hash="0" * 64,
        )
    except ValidationError as exc:
        raise DataQualityError(str(exc)) from None
    return provisional.model_copy(update={"bundle_hash": _bundle_content_hash(provisional)})


def find_bundle_component(
    bundle: DatasetBundle,
    *,
    kind: DatasetKind,
    symbol: str | None = None,
    interval: str | None = None,
) -> DatasetRegistryEntry | None:
    requested_interval = interval
    if kind == "kline" and requested_interval is None:
        requested_interval = bundle.primary_interval
    for component in bundle.components:
        if component.kind != kind:
            continue
        if requested_interval is not None and component.interval != requested_interval:
            continue
        if kind == "exchange_filters":
            if symbol is None:
                return component
        elif symbol is not None and component.symbols == (symbol,):
            return component
    return None


def read_dataset_bundle(path: Path) -> DatasetBundle:
    bundle = DatasetBundle.model_validate_json(path.read_text(encoding="utf-8"))
    if _bundle_content_hash(bundle) != bundle.bundle_hash:
        raise DomainViolation(f"dataset bundle hash mismatch: {path}")
    return bundle


def write_dataset_bundle(path: Path, bundle: DatasetBundle) -> DatasetBundle:
    if path.exists():
        existing = read_dataset_bundle(path)
        if existing != bundle:
            raise DomainViolation(f"dataset bundle path is immutable: {path}")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)
    return bundle


__all__ = [
    "DatasetBundle",
    "build_dataset_bundle",
    "context_bar_is_usable",
    "find_bundle_component",
    "read_dataset_bundle",
    "write_dataset_bundle",
]
