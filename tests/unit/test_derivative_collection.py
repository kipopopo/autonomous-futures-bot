from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from autonomous_futures.data.backfill import BackfillWindow
from autonomous_futures.data.derivative_collection import collect_mark_price_artifact

START_MS = 1_754_524_800_000
END_MS = START_MS + 10 * 60_000


def test_collect_mark_price_artifact_persists_resumable_public_scope(tmp_path: Path) -> None:
    rows = (
        (
            START_MS,
            "100",
            "101",
            "99",
            "100.5",
            "10",
            START_MS + 299_999,
            "0",
            "0",
            "0",
            "0",
            "0",
        ),
        (
            START_MS + 300_000,
            "100.5",
            "102",
            "100",
            "101.5",
            "11",
            START_MS + 599_999,
            "0",
            "0",
            "0",
            "0",
            "0",
        ),
    )

    def fetch(window: BackfillWindow) -> tuple[tuple[object, ...], ...]:
        assert window == BackfillWindow(START_MS, END_MS)
        return rows

    manifest = collect_mark_price_artifact(
        fetch,
        artifact_path=tmp_path / "BTCUSDT-mark-5m.parquet",
        manifest_path=tmp_path / "BTCUSDT-mark-5m.json",
        artifact_ref="BTCUSDT-mark-5m.parquet",
        symbol="BTCUSDT",
        interval="5m",
        start_ms=START_MS,
        end_ms_exclusive=END_MS,
        now_ms=END_MS,
        created_at=datetime(2025, 8, 7, tzinfo=UTC),
        code_version="test",
        dependency_lock_hash="test-lock",
    )

    assert manifest.kind == "mark_price"
    assert manifest.rows == 2
    assert manifest.time_start == datetime.fromtimestamp(START_MS / 1000, UTC)
    assert manifest.time_end == datetime.fromtimestamp(END_MS / 1000, UTC)
    assert (tmp_path / "BTCUSDT-mark-5m.parquet").exists()
    assert (tmp_path / "BTCUSDT-mark-5m.json").exists()
