from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..domain.errors import DomainViolation
from .backfill import BackfillPageStore, BackfillWindow, merge_kline_rows
from .builder import (
    INTERVAL_MS,
    RAW_KLINE_COLUMNS,
    build_kline_dataset,
)
from .checkpoint import complete_checkpoint, read_checkpoint, write_checkpoint
from .manifest import DatasetManifest, read_manifest, sha256_file
from .parquet import read_canonical_parquet


def _write_raw_csv(path: Path, rows: Sequence[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_KLINE_COLUMNS)
        writer.writeheader()
        for row in rows:
            if len(row) != len(RAW_KLINE_COLUMNS):
                raise DomainViolation("backfill row does not match Binance kline schema")
            writer.writerow(dict(zip(RAW_KLINE_COLUMNS, row, strict=True)))
    temporary_path.replace(path)


def _verify_manifest_files(output_dir: Path, manifest: DatasetManifest) -> None:
    for source_file in manifest.source_files:
        path = output_dir / source_file.relative_path
        if not path.exists():
            raise DomainViolation(f"manifest source file is missing: {path}")
        if sha256_file(path) != source_file.sha256:
            raise DomainViolation(f"manifest source file hash mismatch: {path}")


def finalize_resumable_backfill(
    checkpoint_path: Path,
    output_dir: Path,
    *,
    code_version: str,
    dependency_lock_hash: str,
    created_at: datetime,
    completed_at: datetime,
) -> DatasetManifest:
    """Persist and verify the final dataset before atomically completing the checkpoint."""
    checkpoint = read_checkpoint(checkpoint_path)
    if checkpoint.status == "complete":
        if checkpoint.manifest_relative_path is None:
            raise DomainViolation("completed checkpoint has no manifest binding")
        manifest_path = output_dir / checkpoint.manifest_relative_path
        manifest = read_manifest(manifest_path)
        _verify_manifest_files(output_dir, manifest)
        return manifest
    if checkpoint.next_start_ms != checkpoint.range_end_exclusive:
        raise DomainViolation("cannot finalize an unfinished backfill")

    page_store = BackfillPageStore.for_checkpoint(checkpoint_path)
    pages = tuple(
        page_store.read(
            BackfillWindow(window_start, window_end),
            interval_ms=INTERVAL_MS[checkpoint.interval],
        )
        for window_start, window_end in checkpoint.completed_windows
    )
    rows = merge_kline_rows(
        pages,
        start_ms=checkpoint.range_start_ms,
        end_ms_exclusive=checkpoint.range_end_exclusive,
        interval_ms=INTERVAL_MS[checkpoint.interval],
    )
    raw_path = output_dir / "raw" / f"{checkpoint.symbol}-{checkpoint.interval}-backfill.csv"
    _write_raw_csv(raw_path, rows)

    manifest = build_kline_dataset(
        raw_path,
        output_dir,
        symbol=checkpoint.symbol,
        interval=checkpoint.interval,
        code_version=code_version,
        dependency_lock_hash=dependency_lock_hash,
        created_at=created_at.astimezone(UTC),
    )
    artifact_path = output_dir / "canonical" / f"{checkpoint.symbol}-{checkpoint.interval}.parquet"
    manifest_path = (
        output_dir / "manifests" / f"{checkpoint.symbol}-{checkpoint.interval}.manifest.json"
    )
    read_canonical_parquet(
        artifact_path,
        interval=timedelta(milliseconds=INTERVAL_MS[checkpoint.interval]),
    )
    verified_manifest = read_manifest(manifest_path)
    _verify_manifest_files(output_dir, verified_manifest)
    if verified_manifest != manifest:
        raise DomainViolation("manifest changed during finalization")

    completed_checkpoint = complete_checkpoint(
        checkpoint,
        artifact_relative_path=f"canonical/{artifact_path.name}",
        manifest_relative_path=f"manifests/{manifest_path.name}",
        completed_at=completed_at,
    )
    write_checkpoint(checkpoint_path, completed_checkpoint)
    return verified_manifest


__all__ = ["finalize_resumable_backfill"]
