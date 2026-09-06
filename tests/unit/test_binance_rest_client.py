"""Unit tests for Phase 261: Binance Futures Public REST Kline Client & Offline Fallback.

Tests verify:
- Strict unauthenticated invariant (credential rejection in constructor and headers).
- 100% offline testing with httpx.MockTransport (zero socket connections).
- Kline boundary calculation and developing bar exclusion.
- Parsing and canonical schema validation (geometry, positivity, intervals, gaps).
- Rate limit handling (HTTP 429 retry backoff, HTTP 418 immediate ban).
- Transient server error retries (5xx) and client error handling (4xx).
- Network and timeout retry handling.
- 3-tier fallback cascade (REST -> Parquet -> Deterministic Synthetic).
- Standalone helper functions and async context management.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

from autonomous_futures.feed.models import CanonicalBar
from autonomous_futures.feed.rest_client import (
    BinanceDataQualityError,
    BinanceHttpError,
    BinanceNetworkError,
    BinancePublicRestClient,
    BinanceRateLimitError,
    BinanceSecurityViolation,
    BinanceTimeoutError,
    calculate_closed_bar_boundary,
    fetch_binance_futures_klines,
    fetch_klines_with_fallback,
    fetch_warmup_bars_with_fallback,
    generate_deterministic_synthetic_bars,
    interval_to_milliseconds,
    load_parquet_warmup_bars,
    parse_raw_kline_to_canonical_bar,
    parse_raw_klines_to_canonical_bars,
    parse_raw_klines_to_canonical_df,
    validate_canonical_dataframe,
)


@pytest.fixture
def anyio_backend() -> str:
    """Configure anyio test runner to use standard asyncio backend."""
    return "asyncio"


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------


def make_mock_raw_kline(
    open_time_ms: int,
    interval_ms: int = 300_000,
    open_p: float = 85000.0,
    high_p: float = 85500.0,
    low_p: float = 84800.0,
    close_p: float = 85200.0,
    volume: float = 125.5,
) -> list[Any]:
    """Generate a valid 12-element raw Binance Futures kline array."""
    close_time_ms = open_time_ms + interval_ms - 1
    return [
        open_time_ms,
        f"{open_p:.2f}",
        f"{high_p:.2f}",
        f"{low_p:.2f}",
        f"{close_p:.2f}",
        f"{volume:.3f}",
        close_time_ms,
        "10692600.00000",
        1500,
        f"{volume * 0.5:.3f}",
        "5346300.00000",
        "0",
    ]


def make_mock_raw_klines_series(
    count: int = 100,
    end_time_ms: int = 1788706799999,
    interval_ms: int = 300_000,
    base_price: float = 85000.0,
) -> list[list[Any]]:
    """Generate a series of contiguous closed raw kline arrays ending at end_time_ms."""
    start_open_ms = end_time_ms - (count * interval_ms) + 1
    klines: list[list[Any]] = []
    for i in range(count):
        open_ms = start_open_ms + i * interval_ms
        p = base_price + (i % 20) * 10.0
        klines.append(
            make_mock_raw_kline(
                open_time_ms=open_ms,
                interval_ms=interval_ms,
                open_p=p,
                high_p=p + 50.0,
                low_p=p - 30.0,
                close_p=p + 20.0,
                volume=100.0 + i,
            )
        )
    return klines


# ---------------------------------------------------------------------------
# 1. Unauthenticated Security Invariants
# ---------------------------------------------------------------------------


def test_rest_client_forbids_credentials_in_init() -> None:
    """Prohibit any API keys, secrets, or tokens in constructor kwargs."""
    forbidden_attempts: list[dict[str, Any]] = [
        {"api_key": "test_key"},
        {"api_secret": "test_secret"},
        {"secret": "test_secret"},
        {"token": "test_token"},
        {"password": "test_password"},
        {"auth": ("user", "pass")},
        {"private_key": "test_pk"},
    ]
    for kwargs in forbidden_attempts:
        with pytest.raises((BinanceSecurityViolation, ValueError)):
            BinancePublicRestClient(**kwargs)


def test_rest_client_forbids_forbidden_headers_in_init() -> None:
    """Prohibit authentication headers such as X-MBX-APIKEY in constructor headers."""
    forbidden_headers = [
        {"X-MBX-APIKEY": "secret_key_value"},
        {"Authorization": "Bearer secret_token"},
        {"x-mbx-apikey": "lowercase_key"},
    ]
    for h in forbidden_headers:
        with pytest.raises((BinanceSecurityViolation, ValueError)):
            BinancePublicRestClient(headers=h)


def test_rest_client_forbids_sneaky_apikey_kwargs() -> None:
    """Sneaky 'ApiKey' and 'apikey' kwargs must raise BinanceSecurityViolation."""
    with pytest.raises((BinanceSecurityViolation, ValueError)):
        BinancePublicRestClient(ApiKey="sneaky_key")
    with pytest.raises((BinanceSecurityViolation, ValueError)):
        BinancePublicRestClient(apikey="sneaky_key")


def test_rest_client_forbids_sneaky_x_mbx_apikey_kwargs() -> None:
    """Underscore variant 'x_mbx_apikey' and 'privatekey' must be rejected."""
    with pytest.raises((BinanceSecurityViolation, ValueError)):
        BinancePublicRestClient(x_mbx_apikey="sneaky_key")
    with pytest.raises((BinanceSecurityViolation, ValueError)):
        BinancePublicRestClient(privatekey="sneaky_key")


def test_rest_client_forbids_sneaky_header_auth() -> None:
    """Header variations like X-API-KEY and ApiKey must be rejected."""
    with pytest.raises(BinanceSecurityViolation):
        BinancePublicRestClient(headers={"X-API-KEY": "secret"})
    with pytest.raises(BinanceSecurityViolation):
        BinancePublicRestClient(headers={"ApiKey": "secret"})


def test_rest_client_rejects_external_client_with_auth_header() -> None:
    """Passing an external httpx.AsyncClient with X-MBX-APIKEY must be rejected."""

    async def _run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        transport = httpx.MockTransport(handler)
        external_client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=transport,
            headers={"X-MBX-APIKEY": "leaked_secret"},
        )
        with pytest.raises(BinanceSecurityViolation):
            client = BinancePublicRestClient(client=external_client)
            await client.fetch_raw_klines("BTCUSDT", limit=1)

    asyncio.run(_run())


def test_rest_client_rejects_external_client_with_auth_tuple() -> None:
    """Passing an external httpx.AsyncClient with auth credentials must be rejected."""
    external_client = httpx.AsyncClient(
        base_url="https://fapi.binance.com",
        auth=("user", "password"),
    )
    with pytest.raises(BinanceSecurityViolation):
        BinancePublicRestClient(client=external_client)


def test_rest_client_audit_properties() -> None:
    """Verify audit properties confirm zero loaded credentials."""
    client = BinancePublicRestClient()
    assert client.is_unauthenticated is True
    assert client.api_keys_loaded == 0


@pytest.mark.anyio
async def test_fetch_klines_request_is_unauthenticated() -> None:
    """Verify outgoing HTTP request contains zero authentication headers or query parameters."""
    recorded_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        klines = make_mock_raw_klines_series(count=10)
        return httpx.Response(200, json=klines)

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(transport=transport) as client:
        await client.fetch_klines("BTCUSDT", limit=10)

    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert "x-mbx-apikey" not in req.headers
    assert "authorization" not in req.headers
    assert "signature" not in str(req.url)
    assert "timestamp" not in str(req.url)  # authenticated endpoints require timestamp/signature


# ---------------------------------------------------------------------------
# 2. Raw Kline Parsing & Canonical Validation
# ---------------------------------------------------------------------------


def test_parse_raw_klines_success_canonical() -> None:
    """Verify 100 raw klines parse into valid canonical DataFrame with UTC DatetimeIndex."""
    raw_data = make_mock_raw_klines_series(count=100)
    df = parse_raw_klines_to_canonical_df(raw_data, limit=100)

    assert len(df) == 100
    assert isinstance(df.index, pd.DatetimeIndex)
    assert str(df.index.tz) in ("UTC", "datetime.timezone.utc")
    assert df.index.name == "timestamp"
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert (df["high"] >= df["low"]).all()
    assert (df["volume"] >= 0).all()
    assert df.index.is_monotonic_increasing


def test_parse_raw_klines_relational_format() -> None:
    """Verify as_datetime_index=False returns RangeIndex with timestamp column."""
    raw_data = make_mock_raw_klines_series(count=10)
    df = parse_raw_klines_to_canonical_df(raw_data, limit=10, as_datetime_index=False)

    assert len(df) == 10
    assert "timestamp" in df.columns
    assert isinstance(df.index, pd.RangeIndex)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_parse_raw_klines_excludes_unclosed_bar() -> None:
    """Verify developing bar where close_time > now_ms is filtered when only_closed=True."""
    now_ms = 1788706700000  # In the middle of candle
    # 5 closed bars + 1 currently forming bar
    closed_bars = make_mock_raw_klines_series(count=5, end_time_ms=1788706499999)
    # Developing bar: open at 1788706500000, close at 1788706799999 (> now_ms)
    forming_bar = make_mock_raw_kline(open_time_ms=1788706500000)
    raw_payload = closed_bars + [forming_bar]

    df = parse_raw_klines_to_canonical_df(
        raw_payload,
        only_closed=True,
        current_time_ms=now_ms,
    )
    assert len(df) == 5
    # Ensure forming bar's timestamp is not present
    forming_ts = datetime.fromtimestamp(1788706500000 / 1000, tz=UTC)
    assert forming_ts not in df.index


def test_parse_raw_klines_rejects_empty() -> None:
    """Verify empty raw klines array raises BinanceDataQualityError."""
    with pytest.raises(BinanceDataQualityError, match="empty"):
        parse_raw_klines_to_canonical_df([])


def test_parse_raw_klines_rejects_short_row() -> None:
    """Verify row with < 7 elements raises BinanceDataQualityError."""
    short_rows = [[1788700000000, "85000.0", "85500.0"]]
    with pytest.raises(BinanceDataQualityError, match="row length"):
        parse_raw_klines_to_canonical_df(short_rows)


def test_parse_raw_klines_rejects_non_positive_price() -> None:
    """Verify non-positive price raises BinanceDataQualityError."""
    bad_row = make_mock_raw_kline(open_time_ms=1788700000000, open_p=-10.0)
    with pytest.raises(BinanceDataQualityError, match="strictly positive"):
        parse_raw_klines_to_canonical_df([bad_row])


def test_parse_raw_klines_rejects_non_finite_price() -> None:
    """Verify NaN / Inf price raises BinanceDataQualityError."""
    bad_row = [1788700000000, "NaN", "85500.0", "84800.0", "85200.0", "100.0", 1788700299999]
    with pytest.raises(BinanceDataQualityError, match="finite"):
        parse_raw_klines_to_canonical_df([bad_row])


def test_parse_raw_klines_rejects_negative_volume() -> None:
    """Verify negative volume raises BinanceDataQualityError."""
    bad_row = make_mock_raw_kline(open_time_ms=1788700000000, volume=-5.0)
    with pytest.raises(BinanceDataQualityError, match="Volume must be finite non-negative"):
        parse_raw_klines_to_canonical_df([bad_row])


def test_parse_raw_klines_rejects_geometric_violation() -> None:
    """Verify candle where high < low or high < open raises BinanceDataQualityError."""
    # high (84000) < low (84800)
    bad_row_high_low = make_mock_raw_kline(
        open_time_ms=1788700000000,
        open_p=85000.0,
        high_p=84000.0,
        low_p=84800.0,
        close_p=85000.0,
    )
    with pytest.raises(BinanceDataQualityError, match="geometry"):
        parse_raw_klines_to_canonical_df([bad_row_high_low])


def test_parse_raw_klines_detects_timestamp_gaps() -> None:
    """Verify missing 5m bar raises BinanceDataQualityError with 'timestamp gap'."""
    bar1 = make_mock_raw_kline(open_time_ms=1788700000000)
    # Missing 1788700300000 (10m leap to 1788700600000)
    bar2 = make_mock_raw_kline(open_time_ms=1788700600000)
    with pytest.raises(BinanceDataQualityError, match="timestamp gap"):
        parse_raw_klines_to_canonical_df([bar1, bar2])


def test_parse_raw_klines_detects_duplicate_timestamps() -> None:
    """Verify duplicate open_time bars raise BinanceDataQualityError with 'duplicate'."""
    bar1 = make_mock_raw_kline(open_time_ms=1788700000000)
    bar2 = make_mock_raw_kline(open_time_ms=1788700000000)
    with pytest.raises(BinanceDataQualityError, match="duplicate"):
        parse_raw_klines_to_canonical_df([bar1, bar2])


def test_parse_raw_klines_handles_astronomical_timestamp() -> None:
    """Astronomical epoch timestamp must raise BinanceDataQualityError, not raw OSError."""
    bad_row = make_mock_raw_kline(open_time_ms=10**20)
    with pytest.raises(BinanceDataQualityError):
        parse_raw_klines_to_canonical_df([bad_row], only_closed=False)


def test_validate_relational_geometry_error_message_accuracy() -> None:
    """In relational mode (as_datetime_index=False), error message must report the violating row."""
    ts = pd.date_range("2026-09-06 00:00:00", periods=5, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0] * 5,
            "high": [105.0, 105.0, 80.0, 105.0, 105.0],  # Row 2 high is 80.0 < low (90.0)
            "low": [90.0] * 5,
            "close": [102.0] * 5,
            "volume": [10.0] * 5,
        }
    )
    with pytest.raises(BinanceDataQualityError) as exc_info:
        validate_canonical_dataframe(df)

    msg = str(exc_info.value)
    assert "high (80.0)" in msg
    assert "low (90.0)" in msg
    assert "00:10:00" in msg or str(ts[2]) in msg


# ---------------------------------------------------------------------------
# 3. Client HTTP Methods & Query Boundary Logic
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_klines_success_100_bars() -> None:
    """Verify fetch_klines requests limit+5 and clamps output to requested 100 bars."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Check query parameters
        params = dict(request.url.params)
        assert params["symbol"] == "BTCUSDT"
        assert params["interval"] == "5m"
        assert params["limit"] == "105"  # 100 + 5
        assert "endTime" in params

        # Return 105 bars
        end_ms = int(params["endTime"])
        data = make_mock_raw_klines_series(count=105, end_time_ms=end_ms)
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(transport=transport) as client:
        df = await client.fetch_klines("BTCUSDT", limit=100)

    assert len(df) == 100
    validate_canonical_dataframe(df)


@pytest.mark.anyio
async def test_fetch_klines_explicit_end_time() -> None:
    """Verify explicit end_time parameter is respected in query."""
    explicit_end = 1788706799999
    captured_end_time: str | None = None

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_end_time
        captured_end_time = request.url.params.get("endTime")
        data = make_mock_raw_klines_series(count=10, end_time_ms=explicit_end)
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(transport=transport) as client:
        df = await client.fetch_klines("ETHUSDT", limit=10, endTime=explicit_end)

    assert captured_end_time == str(explicit_end)
    assert len(df) == 10


@pytest.mark.anyio
async def test_get_server_time_success() -> None:
    """Verify get_server_time retrieves exchange epoch ms."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/fapi/v1/time"
        return httpx.Response(200, json={"serverTime": 1788707000123})

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(transport=transport) as client:
        server_time = await client.get_server_time()

    assert server_time == 1788707000123


def test_calculate_closed_bar_boundary() -> None:
    """Verify closed bar boundary math: endTime = ((now_ms // 300_000) * 300_000) - 1."""
    # 1788707807920 // 300000 = 5962359
    # 5962359 * 300000 = 1788707700000
    # endTime = 1788707699999
    boundary = calculate_closed_bar_boundary(1788707807920, interval_ms=300_000)
    assert boundary == 1788707699999
    assert (boundary + 1) % 300_000 == 0


def test_interval_to_milliseconds() -> None:
    """Verify interval conversion to milliseconds."""
    assert interval_to_milliseconds("1m") == 60_000
    assert interval_to_milliseconds("5m") == 300_000
    assert interval_to_milliseconds("1h") == 3_600_000
    assert interval_to_milliseconds("1d") == 86_400_000
    with pytest.raises(ValueError):
        interval_to_milliseconds("invalid")


def test_input_validation_symbol_and_interval() -> None:
    """Verify client rejects malformed symbols or intervals before network transmission."""
    client = BinancePublicRestClient()
    with pytest.raises(ValueError, match="symbol"):
        asyncio.run(client.fetch_raw_klines("INVALID/SYMBOL"))
    with pytest.raises(ValueError, match="interval"):
        asyncio.run(client.fetch_raw_klines("BTCUSDT", interval="2m"))
    with pytest.raises(ValueError, match="Limit"):
        asyncio.run(client.fetch_raw_klines("BTCUSDT", limit=0))


def test_parse_raw_klines_excludes_in_progress_candle_at_exact_closing_ms() -> None:
    """At exact close_time_ms, candle is active and excluded when only_closed=True."""
    open_ms_1 = 1700000100000
    close_ms_1 = open_ms_1 + 299999
    row_1 = make_mock_raw_kline(open_time_ms=open_ms_1)

    open_ms_2 = open_ms_1 + 300000
    close_ms_2 = open_ms_2 + 299999
    row_2 = make_mock_raw_kline(open_time_ms=open_ms_2)

    boundary = calculate_closed_bar_boundary(close_ms_2, 300_000)
    assert boundary == close_ms_1

    df = parse_raw_klines_to_canonical_df(
        [row_1, row_2],
        only_closed=True,
        current_time_ms=close_ms_2,
    )
    assert len(df) == 1
    assert int(df.index[-1].timestamp() * 1000) == open_ms_1


def test_parse_raw_kline_to_canonical_bar_boundary_state() -> None:
    """Verify CanonicalBar.is_closed reflects strict close_time_ms < now_ms boundary."""
    open_ms = 1700000100000
    close_ms = open_ms + 299999
    row = make_mock_raw_kline(open_time_ms=open_ms)

    bar_active = parse_raw_kline_to_canonical_bar(row, symbol="BTCUSDT", current_time_ms=close_ms)
    assert bar_active.is_closed is False

    bar_closed = parse_raw_kline_to_canonical_bar(
        row, symbol="BTCUSDT", current_time_ms=close_ms + 1
    )
    assert bar_closed.is_closed is True


# ---------------------------------------------------------------------------
# 4. Error Handling & Retry Policies
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_klines_rate_limit_429_retry_success() -> None:
    """Verify HTTP 429 parses Retry-After, sleeps, retries, and succeeds."""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"}, text="Rate limit exceeded")
        data = make_mock_raw_klines_series(count=5)
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(
        transport=transport, max_retries=2, backoff_factor=0.01
    ) as client:
        df = await client.fetch_klines("BTCUSDT", limit=5)

    assert attempt_count == 2
    assert len(df) == 5


@pytest.mark.anyio
async def test_fetch_klines_rate_limit_429_exhausted() -> None:
    """Verify exhausting retries on HTTP 429 raises BinanceRateLimitError."""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        return httpx.Response(429, headers={"Retry-After": "0.01"}, text="Rate limit exceeded")

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(
        transport=transport, max_retries=1, backoff_factor=0.01
    ) as client:
        with pytest.raises(BinanceRateLimitError) as exc_info:
            await client.fetch_klines("BTCUSDT", limit=5)

    assert exc_info.value.status_code == 429
    assert attempt_count == 2  # initial attempt + 1 retry


@pytest.mark.anyio
async def test_fetch_klines_rate_limit_418_immediate_ban() -> None:
    """Verify HTTP 418 IP ban fails immediately without retrying."""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        return httpx.Response(418, text="IP has been banned until tomorrow")

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(
        transport=transport, max_retries=3, backoff_factor=0.01
    ) as client:
        with pytest.raises(BinanceRateLimitError) as exc_info:
            await client.fetch_klines("BTCUSDT", limit=5)

    assert exc_info.value.status_code == 418
    assert exc_info.value.is_ban is True
    assert attempt_count == 1  # No retries on 418


@pytest.mark.anyio
async def test_fetch_klines_server_error_5xx_retry() -> None:
    """Verify transient 500 error retries and succeeds."""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            return httpx.Response(500, text="Internal server error")
        data = make_mock_raw_klines_series(count=5)
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(
        transport=transport, max_retries=2, backoff_factor=0.01
    ) as client:
        df = await client.fetch_klines("BTCUSDT", limit=5)

    assert attempt_count == 2
    assert len(df) == 5


@pytest.mark.anyio
async def test_fetch_klines_server_error_5xx_exhausted() -> None:
    """Verify exhausting retries on 500 error raises BinanceHttpError."""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        return httpx.Response(502, text="Bad gateway")

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(
        transport=transport, max_retries=1, backoff_factor=0.01
    ) as client:
        with pytest.raises(BinanceHttpError) as exc_info:
            await client.fetch_klines("BTCUSDT", limit=5)

    assert exc_info.value.status_code == 502
    assert attempt_count == 2


@pytest.mark.anyio
async def test_fetch_klines_client_error_400_no_retry() -> None:
    """Verify 400 Client Error fails immediately without retrying."""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        return httpx.Response(400, text='{"code":-1121,"msg":"Invalid symbol"}')

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(
        transport=transport, max_retries=3, backoff_factor=0.01
    ) as client:
        with pytest.raises(BinanceHttpError) as exc_info:
            await client.fetch_klines("BTCUSDT", limit=5)

    assert exc_info.value.status_code == 400
    assert attempt_count == 1  # No retries on 400 client error


@pytest.mark.anyio
async def test_fetch_klines_timeout_retry_exhausted() -> None:
    """Verify TimeoutException retries and raises BinanceTimeoutError."""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(
        transport=transport, max_retries=1, backoff_factor=0.01
    ) as client:
        with pytest.raises(BinanceTimeoutError):
            await client.fetch_klines("BTCUSDT", limit=5)

    assert attempt_count == 2


@pytest.mark.anyio
async def test_fetch_klines_network_error_retry_exhausted() -> None:
    """Verify NetworkError retries and raises BinanceNetworkError."""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        raise httpx.ConnectError("Connection failed")

    transport = httpx.MockTransport(mock_handler)
    async with BinancePublicRestClient(
        transport=transport, max_retries=1, backoff_factor=0.01
    ) as client:
        with pytest.raises(BinanceNetworkError):
            await client.fetch_klines("BTCUSDT", limit=5)

    assert attempt_count == 2


# ---------------------------------------------------------------------------
# 5. Offline Fallback Cascade
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fallback_cascade_on_connect_error(tmp_path: Path) -> None:
    """Verify cascade to local Parquet when REST encounters ConnectError."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Simulated offline environment")

    transport = httpx.MockTransport(mock_handler)
    rest_client = BinancePublicRestClient(transport=transport, max_retries=0)

    # Use existing immutable-data Parquet for BTCUSDT
    df = await fetch_klines_with_fallback(
        "BTCUSDT",
        warmup_bars=100,
        rest_client=rest_client,
        history_dir=Path("research/immutable-data/5m/canonical"),
    )
    assert len(df) == 100
    validate_canonical_dataframe(df)


@pytest.mark.anyio
async def test_fallback_cascade_on_timeout() -> None:
    """Verify cascade to local Parquet when REST times out."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Simulated timeout")

    transport = httpx.MockTransport(mock_handler)
    rest_client = BinancePublicRestClient(transport=transport, max_retries=0)

    df = await fetch_klines_with_fallback(
        "ETHUSDT",
        warmup_bars=100,
        rest_client=rest_client,
        history_dir=Path("research/immutable-data/5m/canonical"),
    )
    assert len(df) == 100
    validate_canonical_dataframe(df)


@pytest.mark.anyio
async def test_fallback_cascade_synthetic_when_parquet_missing() -> None:
    """Verify cascade to Synthetic generator when Parquet is missing (e.g. DOGEUSDT)."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("No network")

    transport = httpx.MockTransport(mock_handler)
    rest_client = BinancePublicRestClient(transport=transport, max_retries=0)

    # DOGEUSDT does not exist in immutable-data
    df = await fetch_klines_with_fallback(
        "DOGEUSDT",
        warmup_bars=100,
        rest_client=rest_client,
        history_dir=Path("research/immutable-data/5m/canonical"),
    )
    assert len(df) == 100
    validate_canonical_dataframe(df)
    # Price should be near 0.150
    assert 0.10 < df["close"].iloc[-1] < 0.25


@pytest.mark.anyio
async def test_fallback_cascade_synthetic_when_parquet_incomplete(tmp_path: Path) -> None:
    """Verify cascade to Synthetic generator when Parquet has fewer than warmup_bars."""
    # Create incomplete parquet file with only 5 bars
    incomplete_file = tmp_path / "SOLUSDT-5m.parquet"
    synth_short = generate_deterministic_synthetic_bars(
        "SOLUSDT", bars_count=5, as_datetime_index=False
    )
    synth_short.to_parquet(incomplete_file)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Offline")

    transport = httpx.MockTransport(mock_handler)
    rest_client = BinancePublicRestClient(transport=transport, max_retries=0)

    df = await fetch_klines_with_fallback(
        "SOLUSDT",
        warmup_bars=100,
        rest_client=rest_client,
        history_dir=tmp_path,
    )
    assert len(df) == 100
    validate_canonical_dataframe(df)


@pytest.mark.anyio
async def test_explicit_offline_flag_bypasses_network() -> None:
    """Verify offline=True makes zero network calls and falls back cleanly."""
    network_called = False

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal network_called
        network_called = True
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(mock_handler)
    rest_client = BinancePublicRestClient(transport=transport)

    df = await fetch_klines_with_fallback(
        "BTCUSDT",
        warmup_bars=100,
        offline=True,
        rest_client=rest_client,
        history_dir=Path("research/immutable-data/5m/canonical"),
    )
    assert network_called is False
    assert len(df) == 100
    validate_canonical_dataframe(df)


def test_load_parquet_warmup_bars_direct() -> None:
    """Verify load_parquet_warmup_bars loads and validates bars directly."""
    df = load_parquet_warmup_bars(
        "BTCUSDT",
        warmup_bars=50,
        history_dir=Path("research/immutable-data/5m/canonical"),
    )
    assert df is not None
    assert len(df) == 50
    validate_canonical_dataframe(df)


@pytest.mark.anyio
async def test_fetch_warmup_bars_with_fallback_alias() -> None:
    """Verify fetch_warmup_bars_with_fallback operates identically as an alias."""
    df = await fetch_warmup_bars_with_fallback(
        "BTCUSDT",
        warmup_bars=50,
        offline=True,
        history_dir=Path("research/immutable-data/5m/canonical"),
    )
    assert len(df) == 50
    validate_canonical_dataframe(df)


# ---------------------------------------------------------------------------
# 6. Companion Domain Parsers & Helpers
# ---------------------------------------------------------------------------


def test_parse_raw_kline_to_canonical_bar() -> None:
    """Verify parse_raw_kline_to_canonical_bar converts array to CanonicalBar."""
    raw = make_mock_raw_kline(open_time_ms=1788700000000)
    bar = parse_raw_kline_to_canonical_bar(raw, symbol="BTCUSDT", interval="5m")

    assert isinstance(bar, CanonicalBar)
    assert bar.symbol == "BTCUSDT"
    assert bar.interval == "5m"
    assert bar.open == 85000.0
    assert bar.close == 85200.0
    assert bar.is_closed is True


def test_parse_raw_klines_to_canonical_bars() -> None:
    """Verify parse_raw_klines_to_canonical_bars returns list of CanonicalBars."""
    raw = make_mock_raw_klines_series(count=10)
    bars = parse_raw_klines_to_canonical_bars(raw, symbol="ETHUSDT", limit=5)

    assert len(bars) == 5
    assert all(isinstance(b, CanonicalBar) for b in bars)
    assert bars[-1].symbol == "ETHUSDT"


@pytest.mark.anyio
async def test_fetch_binance_futures_klines_standalone_helper() -> None:
    """Verify fetch_binance_futures_klines standalone async helper operates cleanly."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = make_mock_raw_klines_series(count=20)
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(mock_handler)
    df = await fetch_binance_futures_klines(
        "SOLUSDT",
        limit=20,
        transport=transport,
    )
    assert len(df) == 20
    validate_canonical_dataframe(df)


@pytest.mark.anyio
async def test_context_manager_lifecycle() -> None:
    """Verify async context manager initializes and closes internal httpx.AsyncClient."""
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=[]))
    client = BinancePublicRestClient(transport=transport)

    assert client._client is None
    async with client:
        assert client._client is not None
        assert not client._client.is_closed
    assert client._client is None
