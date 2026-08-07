from __future__ import annotations

from email.message import Message
from urllib.error import HTTPError

import pytest

from autonomous_futures.data.backfill import BackfillWindow
from autonomous_futures.data.transport import (
    BinancePublicKlineFetcher,
    PublicTransportError,
    TransportTelemetry,
    classify_public_transport_error,
)


def test_public_fetcher_maps_window_to_unsigned_kline_request() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    start_ms = 1_725_504_000_000

    def get_json(path: str, params: dict[str, object]) -> object:
        calls.append((path, params))
        return [[start_ms, "100", "101", "99", "100.5"]]

    fetcher = BinancePublicKlineFetcher(
        symbol="BTCUSDT",
        interval="5m",
        limit=1,
        get_json=get_json,
    )
    rows = fetcher(BackfillWindow(start_ms, start_ms + 300_000))

    assert rows == ((start_ms, "100", "101", "99", "100.5"),)
    assert calls == [
        (
            "/fapi/v1/klines",
            {
                "symbol": "BTCUSDT",
                "interval": "5m",
                "startTime": start_ms,
                "endTime": start_ms + 299_999,
                "limit": 1,
            },
        )
    ]


def test_http_rate_limit_classification_honors_retry_after() -> None:
    headers = Message()
    headers["Retry-After"] = "3.5"
    error = HTTPError("https://fapi.binance.com", 429, "rate limit", headers, None)

    classified = classify_public_transport_error(error)

    assert classified.status_code == 429
    assert classified.retryable is True
    assert classified.retry_after_seconds == 3.5


def test_http_client_error_is_not_retryable() -> None:
    error = HTTPError("https://fapi.binance.com", 400, "bad request", None, None)

    classified = classify_public_transport_error(error)

    assert classified.status_code == 400
    assert classified.retryable is False
    assert classified.retry_after_seconds is None


def test_fetcher_rejects_malformed_public_payload() -> None:
    fetcher = BinancePublicKlineFetcher(
        symbol="BTCUSDT",
        interval="5m",
        get_json=lambda _path, _params: {"code": -1003},
    )

    with pytest.raises(PublicTransportError, match="list"):
        fetcher(BackfillWindow(1_725_504_000_000, 1_725_504_300_000))


def test_fetcher_records_success_latency_without_payload_metadata() -> None:
    clock_values = iter((10.0, 10.125))
    telemetry = TransportTelemetry()
    fetcher = BinancePublicKlineFetcher(
        symbol="BTCUSDT",
        interval="5m",
        get_json=lambda _path, _params: [[1_725_504_000_000, "100"]],
        telemetry=telemetry,
        clock=lambda: next(clock_values),
    )

    fetcher(BackfillWindow(1_725_504_000_000, 1_725_504_300_000))

    snapshot = telemetry.snapshot()
    assert snapshot.request_count == 1
    assert snapshot.success_count == 1
    assert snapshot.failure_count == 0
    assert snapshot.retryable_failure_count == 0
    assert snapshot.retry_after_observation_count == 0
    assert snapshot.total_latency_seconds == pytest.approx(0.125)
    assert snapshot.average_latency_seconds == pytest.approx(0.125)
    assert not hasattr(snapshot, "payload")


def test_fetcher_records_retryable_http_classification_and_retry_after() -> None:
    headers = Message()
    headers["Retry-After"] = "3.5"
    error = HTTPError("https://fapi.binance.com", 429, "rate limit", headers, None)
    clock_values = iter((20.0, 20.25))
    telemetry = TransportTelemetry()
    fetcher = BinancePublicKlineFetcher(
        symbol="BTCUSDT",
        interval="5m",
        get_json=lambda _path, _params: (_ for _ in ()).throw(error),
        telemetry=telemetry,
        clock=lambda: next(clock_values),
    )

    with pytest.raises(PublicTransportError):
        fetcher(BackfillWindow(1_725_504_000_000, 1_725_504_300_000))

    snapshot = telemetry.snapshot()
    assert snapshot.request_count == 1
    assert snapshot.success_count == 0
    assert snapshot.failure_count == 1
    assert snapshot.retryable_failure_count == 1
    assert snapshot.non_retryable_failure_count == 0
    assert snapshot.retry_after_observation_count == 1
    assert snapshot.status_code_counts == ((429, 1),)
    assert snapshot.total_latency_seconds == pytest.approx(0.25)
