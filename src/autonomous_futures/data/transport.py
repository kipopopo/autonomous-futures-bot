from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError

from .backfill import MAX_BINANCE_KLINE_LIMIT
from .builder import KlineInterval
from .public_collector import public_get

if TYPE_CHECKING:
    from .backfill import BackfillWindow


class PublicTransportError(RuntimeError):
    """Classified failure from a public market-data transport."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class TransportTelemetrySnapshot:
    request_count: int
    success_count: int
    failure_count: int
    retryable_failure_count: int
    non_retryable_failure_count: int
    retry_after_observation_count: int
    status_code_counts: tuple[tuple[int, int], ...]
    total_latency_seconds: float
    max_latency_seconds: float

    @property
    def average_latency_seconds(self) -> float:
        if self.request_count == 0:
            return 0.0
        return self.total_latency_seconds / self.request_count


class TransportTelemetry:
    """In-memory transport counters containing metadata only, never payloads."""

    def __init__(self) -> None:
        self._request_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._retryable_failure_count = 0
        self._non_retryable_failure_count = 0
        self._retry_after_observation_count = 0
        self._status_code_counts: dict[int, int] = {}
        self._total_latency_seconds = 0.0
        self._max_latency_seconds = 0.0

    def observe(
        self,
        *,
        latency_seconds: float,
        success: bool,
        status_code: int | None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        if not math.isfinite(latency_seconds) or latency_seconds < 0:
            raise ValueError("latency_seconds must be finite and non-negative")
        if success and retryable:
            raise ValueError("successful requests cannot be retryable failures")
        self._request_count += 1
        self._success_count += int(success)
        self._failure_count += int(not success)
        if not success:
            if retryable:
                self._retryable_failure_count += 1
            else:
                self._non_retryable_failure_count += 1
        if retry_after_seconds is not None:
            self._retry_after_observation_count += 1
        if status_code is not None:
            self._status_code_counts[status_code] = self._status_code_counts.get(status_code, 0) + 1
        self._total_latency_seconds += latency_seconds
        self._max_latency_seconds = max(self._max_latency_seconds, latency_seconds)

    def snapshot(self) -> TransportTelemetrySnapshot:
        return TransportTelemetrySnapshot(
            request_count=self._request_count,
            success_count=self._success_count,
            failure_count=self._failure_count,
            retryable_failure_count=self._retryable_failure_count,
            non_retryable_failure_count=self._non_retryable_failure_count,
            retry_after_observation_count=self._retry_after_observation_count,
            status_code_counts=tuple(sorted(self._status_code_counts.items())),
            total_latency_seconds=self._total_latency_seconds,
            max_latency_seconds=self._max_latency_seconds,
        )


def _parse_retry_after(headers: object) -> float | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    raw_value = headers.get("Retry-After")
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except TypeError:
        return None
    except ValueError:
        return None
    return value if value >= 0 else None


def classify_public_transport_error(error: BaseException) -> PublicTransportError:
    if isinstance(error, PublicTransportError):
        return error
    if isinstance(error, HTTPError):
        status_code = error.code
        retryable = status_code in {418, 429} or 500 <= status_code <= 599
        return PublicTransportError(
            f"Binance public HTTP error {status_code}",
            status_code=status_code,
            retryable=retryable,
            retry_after_seconds=_parse_retry_after(error.headers),
        )
    if isinstance(error, (ConnectionError, TimeoutError, URLError)):
        return PublicTransportError(
            f"Binance public transport failure: {error}",
            retryable=True,
        )
    return PublicTransportError(
        f"Binance public transport failure: {error}",
        retryable=False,
    )


class BinancePublicKlineFetcher:
    """Unsigned adapter from a backfill window to Binance public klines."""

    def __init__(
        self,
        *,
        symbol: str,
        interval: KlineInterval,
        limit: int = MAX_BINANCE_KLINE_LIMIT,
        get_json: Callable[[str, dict[str, object]], object] = public_get,
        telemetry: TransportTelemetry | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not symbol:
            raise ValueError("symbol must not be empty")
        if not 1 <= limit <= MAX_BINANCE_KLINE_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_BINANCE_KLINE_LIMIT}")
        self.symbol = symbol
        self.interval = interval
        self.limit = limit
        self._get_json = get_json
        self.telemetry = telemetry or TransportTelemetry()
        self._clock = clock

    def __call__(self, window: BackfillWindow) -> tuple[tuple[object, ...], ...]:
        started_at = self._clock()
        try:
            payload = self._get_json(
                "/fapi/v1/klines",
                window.api_params(
                    symbol=self.symbol,
                    interval=self.interval,
                    limit=self.limit,
                ),
            )
        except PublicTransportError as exc:
            self.telemetry.observe(
                latency_seconds=self._clock() - started_at,
                success=False,
                status_code=exc.status_code,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
            )
            raise
        except (ConnectionError, HTTPError, TimeoutError, URLError) as exc:
            classified = classify_public_transport_error(exc)
            self.telemetry.observe(
                latency_seconds=self._clock() - started_at,
                success=False,
                status_code=classified.status_code,
                retryable=classified.retryable,
                retry_after_seconds=classified.retry_after_seconds,
            )
            raise classified from exc

        try:
            if not isinstance(payload, list):
                raise PublicTransportError(
                    "Binance kline response must be a list",
                    retryable=False,
                )
            rows: list[tuple[object, ...]] = []
            for row in payload:
                if not isinstance(row, (list, tuple)):
                    raise PublicTransportError(
                        "Binance kline response rows must be lists",
                        retryable=False,
                    )
                rows.append(tuple(row))
        except PublicTransportError as exc:
            self.telemetry.observe(
                latency_seconds=self._clock() - started_at,
                success=False,
                status_code=exc.status_code,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
            )
            raise
        self.telemetry.observe(
            latency_seconds=self._clock() - started_at,
            success=True,
            status_code=None,
        )
        return tuple(rows)


__all__ = [
    "BinancePublicKlineFetcher",
    "PublicTransportError",
    "TransportTelemetry",
    "TransportTelemetrySnapshot",
    "classify_public_transport_error",
]
