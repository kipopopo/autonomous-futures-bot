from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Literal

from ..data.derivatives_artifacts import read_derivatives_artifact_manifest
from ..data.exchange_filters import read_exchange_filter_snapshot
from ..data.manifest import read_manifest, sha256_file
from ..data.registry import DatasetKind, DatasetRegistryEntry
from ..domain.contracts import DomainModel
from ..domain.errors import DomainViolation
from .catalog import VerifiedDatasetCatalog


class ArtifactIntegrityError(ValueError):
    """A registry artifact reference cannot be trusted by the read-only API."""


class ArtifactInspection(DomainModel):
    verified: Literal[True] = True
    kind: DatasetKind
    symbols: tuple[str, ...]
    interval: str | None
    artifact_ref: str
    manifest_hash: str
    artifact_sha256: str | None = None
    rows: int | None = None
    source_file_count: int
    schema_version: str


def _resolve_relative(root: Path, relative_ref: str) -> Path:
    reference = PurePosixPath(relative_ref)
    if reference.is_absolute() or ".." in reference.parts or "\\" in relative_ref:
        raise ArtifactIntegrityError("artifact reference must remain a relative POSIX path")
    root_resolved = root.resolve()
    candidate = (root_resolved.joinpath(*reference.parts)).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ArtifactIntegrityError("artifact reference escapes the configured root")
    return candidate


def _require_file(path: Path, *, reference: str) -> Path:
    if not path.is_file():
        raise ArtifactIntegrityError(f"artifact reference does not exist: {reference}")
    return path


def _verify_kline(root: Path, entry: DatasetRegistryEntry) -> ArtifactInspection:
    manifest_path = _require_file(
        _resolve_relative(root, entry.artifact_ref),
        reference=entry.artifact_ref,
    )
    manifest = read_manifest(manifest_path)
    if (
        manifest.manifest_hash != entry.content_hash
        or manifest.symbols != entry.symbols
        or manifest.dataset_interval != entry.interval
        or manifest.time_start != entry.time_start
        or manifest.time_end != entry.time_end
    ):
        raise ArtifactIntegrityError("kline manifest is not bound to the registry entry")

    dataset_root = manifest_path.parent.parent
    for source_file in manifest.source_files:
        source_path = _require_file(
            _resolve_relative(dataset_root, source_file.relative_path),
            reference=source_file.relative_path,
        )
        if sha256_file(source_path) != source_file.sha256:
            raise ArtifactIntegrityError(f"source file hash mismatch: {source_file.relative_path}")

    return ArtifactInspection(
        kind=entry.kind,
        symbols=entry.symbols,
        interval=entry.interval,
        artifact_ref=entry.artifact_ref,
        manifest_hash=manifest.manifest_hash,
        source_file_count=len(manifest.source_files),
        schema_version=f"dataset-manifest-v{manifest.manifest_version}",
    )


def _verify_derivative(root: Path, entry: DatasetRegistryEntry) -> ArtifactInspection:
    manifest_path = _require_file(
        _resolve_relative(root, entry.artifact_ref),
        reference=entry.artifact_ref,
    )
    manifest = read_derivatives_artifact_manifest(manifest_path)
    if (
        manifest.manifest_hash != entry.content_hash
        or manifest.symbol != entry.symbols[0]
        or manifest.interval != entry.interval
        or manifest.time_start != entry.time_start
        or manifest.time_end != entry.time_end
    ):
        raise ArtifactIntegrityError("derivatives manifest is not bound to the registry entry")

    artifact_path = _require_file(
        _resolve_relative(root, manifest.artifact_ref),
        reference=manifest.artifact_ref,
    )
    read_derivatives_artifact_manifest(manifest_path, artifact_path=artifact_path)
    return ArtifactInspection(
        kind=entry.kind,
        symbols=entry.symbols,
        interval=entry.interval,
        artifact_ref=entry.artifact_ref,
        manifest_hash=manifest.manifest_hash,
        artifact_sha256=manifest.artifact_sha256,
        rows=manifest.rows,
        source_file_count=1,
        schema_version=manifest.schema_version,
    )


def _verify_exchange_filters(root: Path, entry: DatasetRegistryEntry) -> ArtifactInspection:
    snapshot_path = _require_file(
        _resolve_relative(root, entry.artifact_ref),
        reference=entry.artifact_ref,
    )
    snapshot = read_exchange_filter_snapshot(snapshot_path)
    snapshot_symbols = tuple(item.symbol for item in snapshot.symbols)
    if snapshot.snapshot_hash != entry.content_hash or snapshot_symbols != entry.symbols:
        raise ArtifactIntegrityError("exchange filter snapshot is not bound to the registry entry")
    return ArtifactInspection(
        kind=entry.kind,
        symbols=entry.symbols,
        interval=None,
        artifact_ref=entry.artifact_ref,
        manifest_hash=snapshot.snapshot_hash,
        artifact_sha256=sha256_file(snapshot_path),
        source_file_count=1,
        schema_version=f"exchange-filter-snapshot-v{snapshot.snapshot_version}",
    )


def inspect_artifact_entry(root: Path, entry: DatasetRegistryEntry) -> ArtifactInspection:
    try:
        if entry.kind == "kline":
            return _verify_kline(root, entry)
        if entry.kind in {"funding_rate", "mark_price"}:
            return _verify_derivative(root, entry)
        return _verify_exchange_filters(root, entry)
    except ArtifactIntegrityError:
        raise
    except (OSError, ValueError, DomainViolation) as exc:
        raise ArtifactIntegrityError("artifact integrity verification failed") from exc


def inspect_dataset_artifacts(
    root: Path, catalog: VerifiedDatasetCatalog
) -> tuple[ArtifactInspection, ...]:
    return tuple(inspect_artifact_entry(root, entry) for entry in catalog.bundle.components)


__all__ = [
    "ArtifactInspection",
    "ArtifactIntegrityError",
    "inspect_artifact_entry",
    "inspect_dataset_artifacts",
]
