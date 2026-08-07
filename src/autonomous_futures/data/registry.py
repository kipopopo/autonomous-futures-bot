from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .parquet import DataQualityError

DatasetKind = Literal["kline", "funding_rate", "mark_price", "exchange_filters"]

_EXPECTED_ENDPOINTS: dict[str, str] = {
    "kline": "/fapi/v1/klines",
    "funding_rate": "/fapi/v1/fundingRate",
    "mark_price": "/fapi/v1/markPriceKlines",
    "exchange_filters": "/fapi/v1/exchangeInfo",
}


class DatasetRegistryEntry(DomainModel):
    kind: DatasetKind
    symbols: tuple[str, ...] = Field(min_length=1)
    interval: str | None = None
    time_start: datetime | None = None
    time_end: datetime | None = None
    observed_at: datetime
    schema_version: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_ref: str = Field(min_length=1)
    source: Literal["binance_public_rest"] = "binance_public_rest"
    endpoint_path: str = Field(min_length=1)
    provenance: tuple[str, ...] = Field(min_length=1)

    @field_validator("symbols")
    @classmethod
    def symbols_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(value)):
            raise ValueError("registry symbols must be sorted")
        if len(set(value)) != len(value):
            raise ValueError("registry symbols must be unique")
        if any(not item or item != item.upper() for item in value):
            raise ValueError("registry symbols must be uppercase")
        return value

    @field_validator("observed_at", "time_start", "time_end")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("registry timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("artifact_ref")
    @classmethod
    def artifact_ref_is_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("artifact_ref must be a relative path")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> DatasetRegistryEntry:
        if self.endpoint_path != _EXPECTED_ENDPOINTS[self.kind]:
            raise ValueError(f"endpoint_path does not match {self.kind}")
        if "unsigned" not in self.provenance:
            raise ValueError("provenance must include unsigned")
        if self.kind in {"kline", "mark_price"}:
            if self.interval not in {"5m", "15m"}:
                raise ValueError("interval must be 5m or 15m")
            if self.time_start is None or self.time_end is None:
                raise ValueError("time range is required for bar datasets")
        elif self.kind == "funding_rate":
            if self.interval is not None:
                raise ValueError("funding_rate interval must be null")
            if self.time_start is None or self.time_end is None:
                raise ValueError("time range is required for funding_rate")
        else:
            if (
                self.interval is not None
                or self.time_start is not None
                or self.time_end is not None
            ):
                raise ValueError("exchange_filters interval and time range must be null")
        if self.time_start is not None and self.time_end is not None:
            if self.time_start >= self.time_end:
                raise ValueError("time_start must be before time_end")
        return self


class DatasetRegistry(DomainModel):
    registry_version: Literal[1] = 1
    venue: Literal["BINANCE_USDS_M_FUTURES"] = "BINANCE_USDS_M_FUTURES"
    created_at: datetime
    entries: tuple[DatasetRegistryEntry, ...] = Field(min_length=1)
    registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_entries(self) -> DatasetRegistry:
        keys = tuple(_entry_identity(item) for item in self.entries)
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate registry entry identity")
        if keys != tuple(sorted(keys)):
            raise ValueError("registry entries must be sorted")
        return self


def _entry_identity(entry: DatasetRegistryEntry) -> tuple[object, ...]:
    return (
        entry.kind,
        entry.symbols,
        entry.interval or "",
        entry.time_start.isoformat() if entry.time_start is not None else "",
        entry.time_end.isoformat() if entry.time_end is not None else "",
    )


def _registry_content_hash(registry: DatasetRegistry) -> str:
    payload = registry.model_dump(mode="json", exclude={"created_at", "registry_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical).hexdigest()


def build_dataset_registry(
    entries: Sequence[DatasetRegistryEntry], *, created_at: datetime
) -> DatasetRegistry:
    ordered = tuple(sorted(entries, key=_entry_identity))
    try:
        provisional = DatasetRegistry(
            created_at=created_at.astimezone(UTC),
            entries=ordered,
            registry_hash="0" * 64,
        )
    except ValidationError as exc:
        if "duplicate registry entry identity" in str(exc):
            raise DataQualityError("duplicate registry entry identity") from None
        raise
    return provisional.model_copy(update={"registry_hash": _registry_content_hash(provisional)})


def read_dataset_registry(path: Path) -> DatasetRegistry:
    registry = DatasetRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    if _registry_content_hash(registry) != registry.registry_hash:
        raise DomainViolation(f"dataset registry hash mismatch: {path}")
    return registry


def write_dataset_registry(path: Path, registry: DatasetRegistry) -> DatasetRegistry:
    if path.exists():
        existing = read_dataset_registry(path)
        if existing != registry:
            raise DomainViolation(f"dataset registry path is immutable: {path}")
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(registry.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)
    return registry


def find_dataset_entry(
    registry: DatasetRegistry,
    *,
    kind: DatasetKind,
    symbols: tuple[str, ...],
    interval: str | None,
    time_start: datetime | None = None,
    time_end: datetime | None = None,
) -> DatasetRegistryEntry | None:
    canonical_symbols = tuple(sorted(symbols))
    canonical_start = time_start.astimezone(UTC) if time_start is not None else None
    canonical_end = time_end.astimezone(UTC) if time_end is not None else None
    for entry in registry.entries:
        if (
            entry.kind == kind
            and entry.symbols == canonical_symbols
            and entry.interval == interval
            and entry.time_start == canonical_start
            and entry.time_end == canonical_end
        ):
            return entry
    return None


__all__ = [
    "DatasetKind",
    "DatasetRegistry",
    "DatasetRegistryEntry",
    "build_dataset_registry",
    "find_dataset_entry",
    "read_dataset_registry",
    "write_dataset_registry",
]
