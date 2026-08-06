from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from autonomous_futures.data.checkpoint import (
    build_checkpoint,
    read_checkpoint,
    write_checkpoint,
)
from autonomous_futures.domain.errors import DomainViolation


def checkpoint(*, next_start_ms: int, completed_windows: tuple[tuple[int, int], ...]):
    start_ms = 1_725_504_000_000
    return build_checkpoint(
        job_id="BTCUSDT-5m-2023",
        symbol="BTCUSDT",
        interval="5m",
        range_start_ms=start_ms,
        range_end_exclusive=start_ms + 4 * 300_000,
        next_start_ms=next_start_ms,
        completed_windows=completed_windows,
        updated_at=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
    )


def test_checkpoint_round_trip_is_hash_verified_and_idempotent(tmp_path) -> None:
    start_ms = 1_725_504_000_000
    path = tmp_path / "BTCUSDT-5m.checkpoint.json"
    state = checkpoint(
        next_start_ms=start_ms + 2 * 300_000,
        completed_windows=((start_ms, start_ms + 2 * 300_000),),
    )

    write_checkpoint(path, state)
    assert read_checkpoint(path) == state
    assert write_checkpoint(path, state) == state

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at"] = "2026-08-06T02:00:00Z"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DomainViolation, match="hash mismatch"):
        read_checkpoint(path)


def test_checkpoint_allows_forward_progress_but_rejects_regression(tmp_path) -> None:
    start_ms = 1_725_504_000_000
    path = tmp_path / "BTCUSDT-5m.checkpoint.json"
    first = checkpoint(
        next_start_ms=start_ms + 2 * 300_000,
        completed_windows=((start_ms, start_ms + 2 * 300_000),),
    )
    advanced = build_checkpoint(
        job_id=first.job_id,
        symbol=first.symbol,
        interval=first.interval,
        range_start_ms=first.range_start_ms,
        range_end_exclusive=first.range_end_exclusive,
        next_start_ms=start_ms + 4 * 300_000,
        completed_windows=(
            (start_ms, start_ms + 2 * 300_000),
            (start_ms + 2 * 300_000, start_ms + 4 * 300_000),
        ),
        updated_at=first.updated_at + timedelta(minutes=1),
    )

    write_checkpoint(path, first)
    write_checkpoint(path, advanced)
    assert read_checkpoint(path) == advanced

    with pytest.raises(DomainViolation, match="regress"):
        write_checkpoint(path, first)
