from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autonomous_futures.data.backfill import (
    BackfillError,
    RetryPolicy,
    backfill_klines,
    closed_end_exclusive,
    merge_kline_rows,
    plan_kline_windows,
    resumable_backfill_klines,
)
from autonomous_futures.data.checkpoint import read_checkpoint
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.data.transport import PublicTransportError


def test_planner_clamps_to_closed_end_and_splits_deterministic_windows() -> None:
    interval_ms = 300_000
    start_ms = 1_725_504_000_000
    requested_end_exclusive = start_ms + 7 * interval_ms
    now_ms = start_ms + 5 * interval_ms + 123

    end_exclusive = closed_end_exclusive(
        requested_end_exclusive,
        now_ms=now_ms,
        interval_ms=interval_ms,
    )
    windows = plan_kline_windows(
        start_ms,
        end_exclusive,
        interval_ms=interval_ms,
        page_limit=2,
    )

    assert end_exclusive == start_ms + 5 * interval_ms
    assert [(window.start_ms, window.end_ms_exclusive) for window in windows] == [
        (start_ms, start_ms + 2 * interval_ms),
        (start_ms + 2 * interval_ms, start_ms + 4 * interval_ms),
        (start_ms + 4 * interval_ms, start_ms + 5 * interval_ms),
    ]
    assert windows[0].api_params(symbol="BTCUSDT", interval="5m", limit=2) == {
        "symbol": "BTCUSDT",
        "interval": "5m",
        "startTime": start_ms,
        "endTime": start_ms + 2 * interval_ms - 1,
        "limit": 2,
    }


def test_backfill_retries_only_transient_failures_and_merges_in_order() -> None:
    interval_ms = 300_000
    start_ms = 1_725_504_000_000
    calls: list[int] = []
    delays: list[float] = []
    failures = [TimeoutError("timeout"), ConnectionError("reset")]

    def fetch_page(window) -> list[list[object]]:
        calls.append(window.start_ms)
        if failures:
            failure = failures.pop(0)
            raise failure
        return [
            [window.start_ms, "100"],
            [window.start_ms + interval_ms, "101"],
        ]

    result = backfill_klines(
        fetch_page,
        start_ms,
        start_ms + 4 * interval_ms,
        now_ms=start_ms + 5 * interval_ms,
        interval_ms=interval_ms,
        page_limit=2,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.25),
        sleep=delays.append,
    )

    assert calls == [start_ms, start_ms, start_ms, start_ms + 2 * interval_ms]
    assert delays == [0.25, 0.5]
    assert result.attempt_count == 4
    assert [row[0] for row in result.rows] == [
        start_ms,
        start_ms + interval_ms,
        start_ms + 2 * interval_ms,
        start_ms + 3 * interval_ms,
    ]


def test_backfill_does_not_retry_non_transient_errors() -> None:
    delays: list[float] = []

    def fetch_page(_window) -> list[list[object]]:
        raise ValueError("invalid response")

    with pytest.raises(ValueError, match="invalid response"):
        backfill_klines(
            fetch_page,
            0,
            300_000,
            now_ms=600_000,
            interval_ms=300_000,
            sleep=delays.append,
        )
    assert delays == []


def test_backfill_raises_after_bounded_transient_attempts() -> None:
    delays: list[float] = []

    def fetch_page(_window) -> list[list[object]]:
        raise TimeoutError("still unavailable")

    with pytest.raises(BackfillError, match="attempts"):
        backfill_klines(
            fetch_page,
            0,
            300_000,
            now_ms=600_000,
            interval_ms=300_000,
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.25),
            sleep=delays.append,
        )
    assert delays == [0.25, 0.5]


def test_backfill_honors_classified_transport_retry_after() -> None:
    delays: list[float] = []
    failures = [
        PublicTransportError(
            "rate limited",
            status_code=429,
            retryable=True,
            retry_after_seconds=3.5,
        )
    ]

    def fetch_page(window) -> list[list[object]]:
        if failures:
            raise failures.pop(0)
        return [[window.start_ms, "100"]]

    result = backfill_klines(
        fetch_page,
        0,
        300_000,
        now_ms=600_000,
        interval_ms=300_000,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.25),
        sleep=delays.append,
    )

    assert result.attempt_count == 2
    assert delays == [3.5]


def test_merge_deduplicates_identical_rows_and_rejects_conflicts_or_gaps() -> None:
    start_ms = 1_725_504_000_000
    interval_ms = 300_000
    pages = (
        ((start_ms, "100"), (start_ms + interval_ms, "101")),
        ((start_ms + interval_ms, "101"), (start_ms + 2 * interval_ms, "102")),
    )

    merged = merge_kline_rows(
        pages,
        start_ms=start_ms,
        end_ms_exclusive=start_ms + 3 * interval_ms,
        interval_ms=interval_ms,
    )
    assert [row[0] for row in merged] == [
        start_ms,
        start_ms + interval_ms,
        start_ms + 2 * interval_ms,
    ]

    with pytest.raises(DataQualityError, match="conflicting duplicate"):
        merge_kline_rows(
            (((start_ms, "100"),), ((start_ms, "999"),)),
            start_ms=start_ms,
            end_ms_exclusive=start_ms + interval_ms,
            interval_ms=interval_ms,
        )

    with pytest.raises(DataQualityError, match="gap"):
        merge_kline_rows(
            (((start_ms, "100"), (start_ms + 2 * interval_ms, "102")),),
            start_ms=start_ms,
            end_ms_exclusive=start_ms + 3 * interval_ms,
            interval_ms=interval_ms,
        )


def test_resumable_backfill_persists_completed_pages_and_resumes(tmp_path) -> None:
    interval_ms = 300_000
    start_ms = 1_725_504_000_000
    checkpoint_path = tmp_path / "BTCUSDT-5m.checkpoint.json"
    checkpoint_time = datetime(2026, 8, 7, tzinfo=UTC)
    first_run_calls: list[int] = []

    def interrupted_fetch(window) -> list[list[object]]:
        first_run_calls.append(window.start_ms)
        if len(first_run_calls) == 1:
            return [
                [window.start_ms, "100"],
                [window.start_ms + interval_ms, "101"],
            ]
        raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        resumable_backfill_klines(
            interrupted_fetch,
            checkpoint_path,
            job_id="BTCUSDT-5m-2023",
            symbol="BTCUSDT",
            interval="5m",
            start_ms=start_ms,
            requested_end_exclusive=start_ms + 4 * interval_ms,
            now_ms=start_ms + 5 * interval_ms,
            interval_ms=interval_ms,
            page_limit=2,
            checkpoint_clock=lambda: checkpoint_time,
        )

    saved = read_checkpoint(checkpoint_path)
    assert saved.next_start_ms == start_ms + 2 * interval_ms
    assert saved.completed_windows == ((start_ms, start_ms + 2 * interval_ms),)
    assert first_run_calls == [start_ms, start_ms + 2 * interval_ms]

    resumed_calls: list[int] = []

    def resumed_fetch(window) -> list[list[object]]:
        resumed_calls.append(window.start_ms)
        return [
            [window.start_ms, "102"],
            [window.start_ms + interval_ms, "103"],
        ]

    result = resumable_backfill_klines(
        resumed_fetch,
        checkpoint_path,
        job_id="BTCUSDT-5m-2023",
        symbol="BTCUSDT",
        interval="5m",
        start_ms=start_ms,
        requested_end_exclusive=start_ms + 4 * interval_ms,
        now_ms=start_ms + 5 * interval_ms,
        interval_ms=interval_ms,
        page_limit=2,
        checkpoint_clock=lambda: checkpoint_time,
    )

    assert resumed_calls == [start_ms + 2 * interval_ms]
    assert [row[0] for row in result.rows] == [
        start_ms,
        start_ms + interval_ms,
        start_ms + 2 * interval_ms,
        start_ms + 3 * interval_ms,
    ]
    completed = read_checkpoint(checkpoint_path)
    assert completed.next_start_ms == start_ms + 4 * interval_ms
    assert len(completed.completed_windows) == 2
