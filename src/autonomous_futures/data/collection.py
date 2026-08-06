from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .builder import KlineInterval, build_kline_dataset, read_kline_csv
from .manifest import DatasetManifest
from .parquet import DataQualityError


class DatasetCollectionManifest(DomainModel):
    manifest_version: Literal[1] = 1
    dataset_interval: KlineInterval
    symbols: tuple[str, ...] = Field(min_length=1)
    datasets: tuple[DatasetManifest, ...] = Field(min_length=1)
    code_version: str = Field(min_length=1)
    dependency_lock_hash: str = Field(min_length=1)
    created_at: datetime
    collection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_children(self) -> DatasetCollectionManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        child_symbols = tuple(dataset.symbols[0] for dataset in self.datasets)
        if child_symbols != self.symbols:
            raise ValueError("child datasets must match sorted collection symbols")
        if any(dataset.dataset_interval != self.dataset_interval for dataset in self.datasets):
            raise ValueError("child dataset intervals must match collection interval")
        if len({dataset.time_start for dataset in self.datasets}) != 1:
            raise ValueError("child dataset start times must align")
        if len({dataset.time_end for dataset in self.datasets}) != 1:
            raise ValueError("child dataset end times must align")
        return self


def _collection_content_hash(manifest: DatasetCollectionManifest) -> str:
    payload = manifest.model_dump(
        mode="json",
        exclude={"created_at", "collection_hash"},
    )
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(canonical_json).hexdigest()


def build_collection_manifest(
    *,
    datasets: tuple[DatasetManifest, ...],
    code_version: str,
    dependency_lock_hash: str,
    created_at: datetime,
) -> DatasetCollectionManifest:
    ordered = tuple(sorted(datasets, key=lambda dataset: dataset.symbols[0]))
    if not ordered:
        raise DataQualityError("collection must contain at least one dataset")
    provisional = DatasetCollectionManifest(
        dataset_interval=ordered[0].dataset_interval,
        symbols=tuple(dataset.symbols[0] for dataset in ordered),
        datasets=ordered,
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
        created_at=created_at.astimezone(UTC),
        collection_hash="0" * 64,
    )
    return provisional.model_copy(update={"collection_hash": _collection_content_hash(provisional)})


def read_collection_manifest(path: Path) -> DatasetCollectionManifest:
    manifest = DatasetCollectionManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if _collection_content_hash(manifest) != manifest.collection_hash:
        raise DomainViolation(f"collection manifest hash mismatch: {path}")
    return manifest


def write_collection_manifest(
    path: Path,
    manifest: DatasetCollectionManifest,
) -> DatasetCollectionManifest:
    if path.exists():
        existing = read_collection_manifest(path)
        if existing != manifest:
            raise DomainViolation(f"collection manifest path is immutable: {path}")
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


def build_kline_collection(
    source_paths: Mapping[str, Path],
    output_dir: Path,
    *,
    interval: KlineInterval,
    code_version: str,
    dependency_lock_hash: str,
    created_at: datetime,
) -> DatasetCollectionManifest:
    symbols = tuple(sorted(source_paths))
    if not symbols:
        raise DataQualityError("collection requires at least one source symbol")

    # Preflight every source before the first write to avoid partial collections.
    for symbol in symbols:
        read_kline_csv(source_paths[symbol], symbol=symbol, interval=interval)

    datasets = tuple(
        build_kline_dataset(
            source_paths[symbol],
            output_dir,
            symbol=symbol,
            interval=interval,
            code_version=code_version,
            dependency_lock_hash=dependency_lock_hash,
            created_at=created_at,
        )
        for symbol in symbols
    )
    manifest = build_collection_manifest(
        datasets=datasets,
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
        created_at=created_at,
    )
    return write_collection_manifest(
        output_dir / "manifests" / f"collection-{interval}.manifest.json",
        manifest,
    )


__all__ = [
    "DatasetCollectionManifest",
    "build_collection_manifest",
    "build_kline_collection",
    "read_collection_manifest",
    "write_collection_manifest",
]
