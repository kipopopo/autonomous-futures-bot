from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..domain.errors import DomainViolation
from .builder import KlineInterval
from .checkpoint import build_checkpoint, read_checkpoint, write_checkpoint
from .parquet import DataQualityError

MAX_BINANCE_KLINE_LIMIT = 1_500


class BackfillPlanningError(ValueError):
    """Raised when a historical backfill range cannot be planned safely."""


class BackfillError(RuntimeError):
    """Raised when a page cannot be fetched within the retry budget."""


@dataclass(frozen=True, slots=True)
class BackfillWindow:
    start_ms: int
    end_ms_exclusive: int

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise BackfillPlanningError("window start must not be negative")
        if self.end_ms_exclusive <= self.start_ms:
            raise BackfillPlanningError("window end must be after window start")

    def api_params(self, *, symbol: str, interval: str, limit: int) -> dict[str, object]:
        if not symbol:
            raise BackfillPlanningError("symbol must not be empty")
        if not interval:
            raise BackfillPlanningError("interval must not be empty")
        if not 1 <= limit <= MAX_BINANCE_KLINE_LIMIT:
            raise BackfillPlanningError(f"limit must be between 1 and {MAX_BINANCE_KLINE_LIMIT}")
        return {
            "symbol": symbol,
            "interval": interval,
            "startTime": self.start_ms,
            "endTime": self.end_ms_exclusive - 1,
            "limit": limit,
        }


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise BackfillPlanningError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0:
            raise BackfillPlanningError("base_delay_seconds must not be negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise BackfillPlanningError("max_delay_seconds must be at least base_delay_seconds")

    def delay_seconds(self, retry_number: int) -> float:
        if not 1 <= retry_number < self.max_attempts:
            raise BackfillPlanningError("retry_number must identify a permitted retry")
        exponential_delay = self.base_delay_seconds * float(2 ** (retry_number - 1))
        return min(self.max_delay_seconds, exponential_delay)


@dataclass(frozen=True, slots=True)
class BackfillResult:
    rows: tuple[tuple[object, ...], ...]
    windows: tuple[BackfillWindow, ...]
    attempt_count: int
    retry_delays: tuple[float, ...]


def _require_aligned(value_ms: int, interval_ms: int, *, field: str) -> None:
    if value_ms < 0:
        raise BackfillPlanningError(f"{field} must not be negative")
    if interval_ms <= 0:
        raise BackfillPlanningError("interval_ms must be positive")
    if value_ms % interval_ms != 0:
        raise BackfillPlanningError(f"{field} must align to interval_ms")


def closed_end_exclusive(
    requested_end_exclusive: int,
    *,
    now_ms: int,
    interval_ms: int,
) -> int:
    """Clamp a requested half-open end to the last fully closed candle boundary."""
    _require_aligned(requested_end_exclusive, interval_ms, field="requested_end_exclusive")
    if now_ms < 0:
        raise BackfillPlanningError("now_ms must not be negative")
    closed_boundary = (now_ms // interval_ms) * interval_ms
    return min(requested_end_exclusive, closed_boundary)


def plan_kline_windows(
    start_ms: int,
    end_ms_exclusive: int,
    *,
    interval_ms: int,
    page_limit: int = MAX_BINANCE_KLINE_LIMIT,
) -> tuple[BackfillWindow, ...]:
    """Create deterministic half-open windows for Binance kline pagination."""
    _require_aligned(start_ms, interval_ms, field="start_ms")
    _require_aligned(end_ms_exclusive, interval_ms, field="end_ms_exclusive")
    if end_ms_exclusive <= start_ms:
        raise BackfillPlanningError("end_ms_exclusive must be after start_ms")
    if not 1 <= page_limit <= MAX_BINANCE_KLINE_LIMIT:
        raise BackfillPlanningError(f"page_limit must be between 1 and {MAX_BINANCE_KLINE_LIMIT}")

    page_span_ms = interval_ms * page_limit
    windows: list[BackfillWindow] = []
    cursor = start_ms
    while cursor < end_ms_exclusive:
        window_end = min(cursor + page_span_ms, end_ms_exclusive)
        windows.append(BackfillWindow(cursor, window_end))
        cursor = window_end
    return tuple(windows)


def _row_open_time(row: Sequence[object]) -> int:
    if not row:
        raise DataQualityError("backfill row must contain an open timestamp")
    value = row[0]
    if isinstance(value, bool):
        raise DataQualityError("backfill open timestamp must be an integer")
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise DataQualityError(f"invalid backfill open timestamp: {value!r}") from exc


def merge_kline_rows(
    pages: Sequence[Sequence[Sequence[object]]],
    *,
    start_ms: int,
    end_ms_exclusive: int,
    interval_ms: int,
) -> tuple[tuple[object, ...], ...]:
    """Merge pages, deduplicate identical rows, and require a complete range."""
    _require_aligned(start_ms, interval_ms, field="start_ms")
    _require_aligned(end_ms_exclusive, interval_ms, field="end_ms_exclusive")
    if end_ms_exclusive <= start_ms:
        raise BackfillPlanningError("end_ms_exclusive must be after start_ms")

    by_open_time: dict[int, tuple[object, ...]] = {}
    for page in pages:
        for raw_row in page:
            row = tuple(raw_row)
            open_time = _row_open_time(row)
            if not start_ms <= open_time < end_ms_exclusive:
                raise DataQualityError("backfill row is outside the requested range")
            existing = by_open_time.get(open_time)
            if existing is not None and existing != row:
                raise DataQualityError(f"conflicting duplicate at {open_time}")
            by_open_time[open_time] = row

    expected = tuple(range(start_ms, end_ms_exclusive, interval_ms))
    actual = tuple(sorted(by_open_time))
    if actual != expected:
        raise DataQualityError(f"backfill gap: expected {len(expected)} rows, got {len(actual)}")
    return tuple(by_open_time[open_time] for open_time in expected)


def backfill_klines(
    fetch_page: Callable[[BackfillWindow], Sequence[Sequence[object]]],
    start_ms: int,
    requested_end_exclusive: int,
    *,
    now_ms: int,
    interval_ms: int,
    page_limit: int = MAX_BINANCE_KLINE_LIMIT,
    retry_policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_window_complete: Callable[[BackfillWindow], None] | None = None,
) -> BackfillResult:
    """Fetch planned pages with bounded transient retries and strict merge validation."""
    policy = retry_policy or RetryPolicy()
    end_exclusive = closed_end_exclusive(
        requested_end_exclusive,
        now_ms=now_ms,
        interval_ms=interval_ms,
    )
    windows = plan_kline_windows(
        start_ms,
        end_exclusive,
        interval_ms=interval_ms,
        page_limit=page_limit,
    )

    pages: list[tuple[tuple[object, ...], ...]] = []
    retry_delays: list[float] = []
    attempt_count = 0
    for window in windows:
        for attempt in range(1, policy.max_attempts + 1):
            attempt_count += 1
            try:
                page = fetch_page(window)
            except (ConnectionError, TimeoutError) as exc:
                if attempt == policy.max_attempts:
                    raise BackfillError(
                        f"backfill page failed after {attempt} attempts: {window}"
                    ) from exc
                delay = policy.delay_seconds(attempt)
                retry_delays.append(delay)
                sleep(delay)
                continue
            except Exception as exc:
                if not getattr(exc, "retryable", False):
                    raise
                if attempt == policy.max_attempts:
                    raise BackfillError(
                        f"backfill page failed after {attempt} attempts: {window}"
                    ) from exc
                retry_after = getattr(exc, "retry_after_seconds", None)
                if isinstance(retry_after, (int, float)):
                    delay = min(policy.max_delay_seconds, float(retry_after))
                else:
                    delay = policy.delay_seconds(attempt)
                retry_delays.append(delay)
                sleep(delay)
                continue
            pages.append(tuple(tuple(row) for row in page))
            if on_window_complete is not None:
                merge_kline_rows(
                    (pages[-1],),
                    start_ms=window.start_ms,
                    end_ms_exclusive=window.end_ms_exclusive,
                    interval_ms=interval_ms,
                )
                on_window_complete(window)
            break

    rows = merge_kline_rows(
        pages,
        start_ms=start_ms,
        end_ms_exclusive=end_exclusive,
        interval_ms=interval_ms,
    )
    return BackfillResult(
        rows=rows,
        windows=windows,
        attempt_count=attempt_count,
        retry_delays=tuple(retry_delays),
    )


def resumable_backfill_klines(
    fetch_page: Callable[[BackfillWindow], Sequence[Sequence[object]]],
    checkpoint_path: Path,
    *,
    job_id: str,
    symbol: str,
    interval: KlineInterval,
    start_ms: int,
    requested_end_exclusive: int,
    now_ms: int,
    interval_ms: int,
    page_limit: int = MAX_BINANCE_KLINE_LIMIT,
    retry_policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    checkpoint_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BackfillResult:
    """Resume page-by-page backfill from the last durable completed window."""
    end_exclusive = closed_end_exclusive(
        requested_end_exclusive,
        now_ms=now_ms,
        interval_ms=interval_ms,
    )
    all_windows = plan_kline_windows(
        start_ms,
        end_exclusive,
        interval_ms=interval_ms,
        page_limit=page_limit,
    )
    if checkpoint_path.exists():
        checkpoint = read_checkpoint(checkpoint_path)
        if (
            checkpoint.job_id,
            checkpoint.symbol,
            checkpoint.interval,
            checkpoint.range_start_ms,
            checkpoint.range_end_exclusive,
        ) != (job_id, symbol, interval, start_ms, end_exclusive):
            raise DomainViolation(f"checkpoint scope mismatch: {checkpoint_path}")
        expected_completed = tuple(
            (window.start_ms, window.end_ms_exclusive)
            for window in all_windows[: len(checkpoint.completed_windows)]
        )
        if checkpoint.completed_windows != expected_completed:
            raise DomainViolation(f"checkpoint page plan mismatch: {checkpoint_path}")
        resume_start_ms = checkpoint.next_start_ms
        completed_windows = checkpoint.completed_windows
    else:
        checkpoint = build_checkpoint(
            job_id=job_id,
            symbol=symbol,
            interval=interval,
            range_start_ms=start_ms,
            range_end_exclusive=end_exclusive,
            next_start_ms=start_ms,
            completed_windows=(),
            updated_at=checkpoint_clock(),
        )
        write_checkpoint(checkpoint_path, checkpoint)
        resume_start_ms = start_ms
        completed_windows = ()

    if resume_start_ms == end_exclusive:
        return BackfillResult(rows=(), windows=(), attempt_count=0, retry_delays=())

    def persist_completed_window(window: BackfillWindow) -> None:
        nonlocal completed_windows
        completed_windows = (*completed_windows, (window.start_ms, window.end_ms_exclusive))
        next_checkpoint = build_checkpoint(
            job_id=job_id,
            symbol=symbol,
            interval=interval,
            range_start_ms=start_ms,
            range_end_exclusive=end_exclusive,
            next_start_ms=window.end_ms_exclusive,
            completed_windows=completed_windows,
            updated_at=checkpoint_clock(),
        )
        write_checkpoint(checkpoint_path, next_checkpoint)

    return backfill_klines(
        fetch_page,
        resume_start_ms,
        end_exclusive,
        now_ms=now_ms,
        interval_ms=interval_ms,
        page_limit=page_limit,
        retry_policy=retry_policy,
        sleep=sleep,
        on_window_complete=persist_completed_window,
    )


__all__ = [
    "MAX_BINANCE_KLINE_LIMIT",
    "BackfillError",
    "BackfillPlanningError",
    "BackfillResult",
    "BackfillWindow",
    "RetryPolicy",
    "backfill_klines",
    "closed_end_exclusive",
    "merge_kline_rows",
    "plan_kline_windows",
    "resumable_backfill_klines",
]
