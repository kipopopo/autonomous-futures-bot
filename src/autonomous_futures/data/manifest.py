from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation


class DataFileManifest(DomainModel):
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: int = Field(ge=0)


class DatasetManifest(DomainModel):
    manifest_version: Literal[1] = 1
    symbols: tuple[str, ...] = Field(min_length=1)
    primary_interval: Literal["5m"] = "5m"
    context_interval: Literal["15m"] = "15m"
    dataset_interval: Literal["5m", "15m"] = "5m"
    time_start: datetime
    time_end: datetime
    source_files: tuple[DataFileManifest, ...] = Field(min_length=1)
    timezone: Literal["UTC"] = "UTC"
    timestamp_semantics: Literal["open_time"] = "open_time"
    feature_availability_policy: Literal["closed_bars_only"] = "closed_bars_only"
    code_version: str = Field(min_length=1)
    dependency_lock_hash: str = Field(min_length=1)
    created_at: datetime
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> DatasetManifest:
        for field_name in ("time_start", "time_end", "created_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.time_start >= self.time_end:
            raise ValueError("time_start must be before time_end")
        if len({file.relative_path for file in self.source_files}) != len(self.source_files):
            raise ValueError("source file paths must be unique")
        return self


def describe_data_file(path: Path, *, relative_path: str, rows: int) -> DataFileManifest:
    return DataFileManifest(
        relative_path=relative_path,
        sha256=sha256_file(path),
        rows=rows,
    )


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_content_hash(manifest: DatasetManifest) -> str:
    payload = manifest.model_dump(
        mode="json",
        exclude={"created_at", "manifest_hash"},
    )
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical_json).hexdigest()


def build_manifest(
    *,
    symbols: tuple[str, ...],
    source_files: tuple[DataFileManifest, ...],
    time_start: datetime,
    time_end: datetime,
    created_at: datetime,
    code_version: str,
    dependency_lock_hash: str,
    dataset_interval: Literal["5m", "15m"] = "5m",
) -> DatasetManifest:
    ordered_files = tuple(sorted(source_files, key=lambda item: item.relative_path))
    provisional = DatasetManifest(
        symbols=tuple(sorted(symbols)),
        source_files=ordered_files,
        dataset_interval=dataset_interval,
        time_start=time_start.astimezone(UTC),
        time_end=time_end.astimezone(UTC),
        created_at=created_at.astimezone(UTC),
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
        manifest_hash="0" * 64,
    )
    return provisional.model_copy(update={"manifest_hash": _manifest_content_hash(provisional)})


def read_manifest(path: Path) -> DatasetManifest:
    manifest = DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if _manifest_content_hash(manifest) != manifest.manifest_hash:
        raise DomainViolation(f"manifest hash mismatch: {path}")
    return manifest


def write_manifest(path: Path, manifest: DatasetManifest) -> DatasetManifest:
    if path.exists():
        existing = read_manifest(path)
        if existing != manifest:
            raise DomainViolation(f"manifest path is immutable: {path}")
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            manifest.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(payload, encoding="utf-8", newline="\n")
    temporary_path.replace(path)
    return manifest
