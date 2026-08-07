from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autonomous_futures.data.artifacts import finalize_resumable_backfill
from autonomous_futures.data.backfill import BackfillPageStore, resumable_backfill_klines
from autonomous_futures.data.checkpoint import read_checkpoint
from autonomous_futures.data.manifest import read_manifest
from autonomous_futures.data.parquet import read_canonical_parquet
from autonomous_futures.domain.errors import DomainViolation


def kline_row(open_time: int, index: int) -> list[object]:
    return [
        open_time,
        f"{100 + index}.00",
        f"{101 + index}.00",
        f"{99 + index}.00",
        f"{100.50 + index:.2f}",
        "12.345",
        open_time + 299_999,
        "1234.500",
        10 + index,
        "6.000",
        "600.000",
        "0",
    ]


def test_finalize_resumable_backfill_binds_artifact_manifest_before_completion(
    tmp_path: Path,
) -> None:
    start_ms = 1_725_504_000_000
    interval_ms = 300_000
    checkpoint_path = tmp_path / "BTCUSDT-5m.checkpoint.json"
    output_dir = tmp_path / "dataset"
    fixed_time = datetime(2026, 8, 7, tzinfo=UTC)

    def fetch_page(window) -> list[list[object]]:
        index = (window.start_ms - start_ms) // interval_ms
        return [kline_row(window.start_ms, index)]

    resumable_backfill_klines(
        fetch_page,
        checkpoint_path,
        job_id="BTCUSDT-5m-2023",
        symbol="BTCUSDT",
        interval="5m",
        start_ms=start_ms,
        requested_end_exclusive=start_ms + 2 * interval_ms,
        now_ms=start_ms + 3 * interval_ms,
        interval_ms=interval_ms,
        page_limit=1,
        checkpoint_clock=lambda: fixed_time,
    )
    assert read_checkpoint(checkpoint_path).status == "running"

    manifest = finalize_resumable_backfill(
        checkpoint_path,
        output_dir,
        code_version="test-code",
        dependency_lock_hash="sha256:lock",
        created_at=fixed_time,
        completed_at=fixed_time,
    )

    artifact_path = output_dir / "canonical" / "BTCUSDT-5m.parquet"
    manifest_path = output_dir / "manifests" / "BTCUSDT-5m.manifest.json"
    raw_path = output_dir / "raw" / "BTCUSDT-5m-backfill.csv"
    assert manifest.dataset_interval == "5m"
    assert artifact_path.exists()
    assert manifest_path.exists()
    assert raw_path.exists()
    assert read_manifest(manifest_path) == manifest
    assert len(read_canonical_parquet(artifact_path, interval=timedelta(minutes=5))) == 2

    completed = read_checkpoint(checkpoint_path)
    assert completed.status == "complete"
    assert completed.artifact_relative_path == "canonical/BTCUSDT-5m.parquet"
    assert completed.manifest_relative_path == "manifests/BTCUSDT-5m.manifest.json"

    assert (
        finalize_resumable_backfill(
            checkpoint_path,
            output_dir,
            code_version="test-code",
            dependency_lock_hash="sha256:lock",
            created_at=fixed_time,
            completed_at=fixed_time,
        )
        == manifest
    )


def test_finalizer_keeps_checkpoint_running_when_page_artifact_is_missing(tmp_path: Path) -> None:
    start_ms = 1_725_504_000_000
    interval_ms = 300_000
    checkpoint_path = tmp_path / "BTCUSDT-5m.checkpoint.json"
    fixed_time = datetime(2026, 8, 7, tzinfo=UTC)

    resumable_backfill_klines(
        lambda window: [kline_row(window.start_ms, 0)],
        checkpoint_path,
        job_id="BTCUSDT-5m-2023",
        symbol="BTCUSDT",
        interval="5m",
        start_ms=start_ms,
        requested_end_exclusive=start_ms + interval_ms,
        now_ms=start_ms + 2 * interval_ms,
        interval_ms=interval_ms,
        page_limit=1,
        checkpoint_clock=lambda: fixed_time,
    )
    page_path = BackfillPageStore.for_checkpoint(checkpoint_path).root / (
        f"{start_ms}-{start_ms + interval_ms}.json"
    )
    page_path.unlink()

    with pytest.raises(DomainViolation, match="missing persisted backfill page"):
        finalize_resumable_backfill(
            checkpoint_path,
            tmp_path / "dataset",
            code_version="test-code",
            dependency_lock_hash="sha256:lock",
            created_at=fixed_time,
            completed_at=fixed_time,
        )
    assert read_checkpoint(checkpoint_path).status == "running"
