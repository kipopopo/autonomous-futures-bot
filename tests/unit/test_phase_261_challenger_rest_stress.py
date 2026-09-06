"""Phase 261: Adversarial Stress & Empirical Verification Test Suite for REST Kline Client.

Authored by challenger_m1_2 to empirically challenge:
1. Fallback cascade under connection drops (ConnectError, ReadTimeout, WriteTimeout, PoolTimeout).
2. Corrupted, truncated (<100 rows), missing columns, and empty Parquet handling.
3. Synthetic bar validity under validate_canonical_dataframe and canonicalize_bars.
4. Concurrent symbol fetching (BTC, ETH, SOL, DOGE) via asyncio.gather.
5. Resource cleanliness, session pooling, and zero ResourceWarnings.
"""

from __future__ import annotations

import asyncio
import tempfile
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

from autonomous_futures.data.quality import canonicalize_bars
from autonomous_futures.feed.rest_client import (
    BinancePublicRestClient,
    BinanceSecurityViolation,
    calculate_closed_bar_boundary,
    fetch_binance_futures_klines,
    fetch_klines_with_fallback,
    generate_deterministic_synthetic_bars,
    load_parquet_warmup_bars,
    validate_canonical_dataframe,
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _make_mock_klines(
    count: int = 105,
    interval_ms: int = 300_000,
    end_ms: int = 1_770_000_000_000,
    base_price: float = 100.0,
) -> list[list[Any]]:
    """Helper to generate valid raw Binance kline arrays."""
    klines: list[list[Any]] = []
    start_ms = end_ms - (count * interval_ms)
    for i in range(count):
        open_time = start_ms + i * interval_ms
        close_time = open_time + interval_ms - 1
        open_p = base_price + (i % 5) * 0.1
        close_p = open_p + 0.05
        high_p = max(open_p, close_p) + 0.5
        low_p = min(open_p, close_p) - 0.5
        vol = 1000.0 + i
        klines.append(
            [
                open_time,
                f"{open_p:.4f}",
                f"{high_p:.4f}",
                f"{low_p:.4f}",
                f"{close_p:.4f}",
                f"{vol:.2f}",
                close_time,
                "100000.0",
                50,
                "500.0",
                "50000.0",
                "0",
            ]
        )
    return klines


# ===========================================================================
# 1. Fallback Cascade & Network Error Drops
# ===========================================================================


@pytest.mark.anyio
@pytest.mark.parametrize(
    "network_error",
    [
        httpx.ConnectError("Connection refused by peer"),
        httpx.ReadTimeout("Read timeout after 5.0s"),
        httpx.WriteTimeout("Write timeout after 5.0s"),
        httpx.PoolTimeout("Connection pool timeout"),
        httpx.ConnectTimeout("Connect timeout after 5.0s"),
    ],
)
async def test_fallback_cascade_on_network_dropouts(network_error: Exception) -> None:
    """Challenge: Client must survive sudden network drops and cascade cleanly."""

    class DroppingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise network_error

    client = BinancePublicRestClient(transport=DroppingTransport(), max_retries=0)

    # BTCUSDT should cleanly cascade to local Parquet
    df_btc = await fetch_klines_with_fallback("BTCUSDT", rest_client=client)
    assert len(df_btc) == 100
    assert isinstance(df_btc.index, pd.DatetimeIndex)
    validate_canonical_dataframe(df_btc)

    # DOGEUSDT has no local Parquet; should cascade through Parquet to Synthetic
    df_doge = await fetch_klines_with_fallback("DOGEUSDT", rest_client=client)
    assert len(df_doge) == 100
    assert isinstance(df_doge.index, pd.DatetimeIndex)
    validate_canonical_dataframe(df_doge)


@pytest.mark.anyio
async def test_fallback_cascade_on_exhausted_500_and_429() -> None:
    """Challenge: Persistent HTTP 500 and 429 responses trigger offline fallback."""

    class ErrorTransport(httpx.AsyncBaseTransport):
        def __init__(self, status_code: int):
            self.status_code = status_code

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(self.status_code, text="Simulated Error", request=request)

    # HTTP 500
    client_500 = BinancePublicRestClient(
        transport=ErrorTransport(500), max_retries=1, backoff_factor=0.01
    )
    df_500 = await fetch_klines_with_fallback("ETHUSDT", rest_client=client_500)
    assert len(df_500) == 100
    validate_canonical_dataframe(df_500)

    # HTTP 429
    client_429 = BinancePublicRestClient(
        transport=ErrorTransport(429), max_retries=1, backoff_factor=0.01
    )
    df_429 = await fetch_klines_with_fallback("DOGEUSDT", rest_client=client_429)
    assert len(df_429) == 100
    validate_canonical_dataframe(df_429)


# ===========================================================================
# 2. Corrupted & Truncated Parquet Handling
# ===========================================================================


@pytest.mark.anyio
async def test_parquet_handling_truncated_sub_100_rows() -> None:
    """Challenge: Parquet with < 100 rows must be rejected and drop down to synthetic."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Create 85 rows (< 100 required)
        df_short = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=85, freq="5min", tz="UTC"),
                "open": [100.0] * 85,
                "high": [105.0] * 85,
                "low": [95.0] * 85,
                "close": [102.0] * 85,
                "volume": [500.0] * 85,
            }
        )
        df_short.to_parquet(tmp_path / "BTCUSDT-5m.parquet")

        # Direct loader should return None
        result = load_parquet_warmup_bars("BTCUSDT", warmup_bars=100, history_dir=tmp_path)
        assert result is None

        # Fallback cascade should drop down to deterministic synthetic
        df_cascade = await fetch_klines_with_fallback(
            "BTCUSDT", warmup_bars=100, history_dir=tmp_path, offline=True
        )
        assert len(df_cascade) == 100
        validate_canonical_dataframe(df_cascade)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "corrupt_mode",
    ["empty_zero_byte", "corrupt_magic_bytes", "missing_columns", "geometric_flaw"],
)
async def test_parquet_handling_adversarial_corruptions(corrupt_mode: str) -> None:
    """Challenge: Diverse Parquet corruptions must be rejected cleanly without unhandled errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        target_file = tmp_path / "ETHUSDT-5m.parquet"

        if corrupt_mode == "empty_zero_byte":
            target_file.write_bytes(b"")
        elif corrupt_mode == "corrupt_magic_bytes":
            target_file.write_bytes(b"PAR1_GARBAGE_PAYLOAD_NON_PARQUET_FOOTER_TEST_1234567890")
        elif corrupt_mode == "missing_columns":
            df_missing = pd.DataFrame(
                {
                    "timestamp": pd.date_range("2026-01-01", periods=120, freq="5min", tz="UTC"),
                    "close": [100.0] * 120,
                }
            )
            df_missing.to_parquet(target_file)
        elif corrupt_mode == "geometric_flaw":
            df_flaw = pd.DataFrame(
                {
                    "timestamp": pd.date_range("2026-01-01", periods=120, freq="5min", tz="UTC"),
                    "open": [100.0] * 120,
                    "high": [90.0] * 120,  # High < Low (Geometry error!)
                    "low": [95.0] * 120,
                    "close": [92.0] * 120,
                    "volume": [10.0] * 120,
                }
            )
            df_flaw.to_parquet(target_file)

        # Loader must return None
        loaded = load_parquet_warmup_bars("ETHUSDT", history_dir=tmp_path)
        assert loaded is None

        # Cascade must fall through to synthetic
        df = await fetch_klines_with_fallback(
            "ETHUSDT", warmup_bars=100, history_dir=tmp_path, offline=True
        )
        assert len(df) == 100
        validate_canonical_dataframe(df)


# ===========================================================================
# 3. Synthetic Bar Validity & Canonicalization Invariants
# ===========================================================================


@pytest.mark.parametrize("symbol", SYMBOLS)
@pytest.mark.parametrize("bar_count", [1, 5, 50, 100, 288, 1000])
def test_synthetic_bars_pass_validation_and_canonicalize(symbol: str, bar_count: int) -> None:
    """Challenge: Synthetic bars must pass validate_canonical_dataframe and canonicalize_bars."""
    # 1. DatetimeIndex format
    df_dt = generate_deterministic_synthetic_bars(
        symbol, bars_count=bar_count, as_datetime_index=True
    )
    assert len(df_dt) == bar_count
    validate_canonical_dataframe(df_dt)

    # 2. Relational format (with 'timestamp' column)
    df_rel = generate_deterministic_synthetic_bars(
        symbol, bars_count=bar_count, as_datetime_index=False
    )
    assert len(df_rel) == bar_count
    assert "timestamp" in df_rel.columns
    validate_canonical_dataframe(df_rel)

    # 3. canonicalize_bars validation
    canonical = canonicalize_bars(df_rel, interval=timedelta(minutes=5))
    assert len(canonical) == bar_count
    assert "timestamp" in canonical.columns

    # 4. canonicalize_bars from reset_index() of DatetimeIndex
    canonical_from_reset = canonicalize_bars(df_dt.reset_index(), interval=timedelta(minutes=5))
    assert len(canonical_from_reset) == bar_count


def test_synthetic_bars_doge_micro_precision() -> None:
    """Challenge: Micro-priced assets (DOGE at ~0.150) must not suffer float rounding collisions."""
    df_doge = generate_deterministic_synthetic_bars("DOGEUSDT", bars_count=500)
    for idx, row in df_doge.iterrows():
        open_val, high_val = row["open"], row["high"]
        low_val, close_val, vol_val = row["low"], row["close"], row["volume"]
        assert high_val >= low_val, f"High < Low at {idx}: {high_val} < {low_val}"
        assert high_val >= max(open_val, close_val), (
            f"High < max(O, C) at {idx}: {high_val} < {max(open_val, close_val)}"
        )
        assert low_val <= min(open_val, close_val), (
            f"Low > min(O, C) at {idx}: {low_val} > {min(open_val, close_val)}"
        )
        assert low_val > 0.0, f"Non-positive price at {idx}: {low_val}"
        assert vol_val >= 0.0, f"Negative volume at {idx}: {vol_val}"


def test_synthetic_bars_temporal_alignment_continuity() -> None:
    """Challenge: Timestamps must align to the preceding closed 5m boundary."""
    anchor_dt = datetime(2026, 9, 6, 15, 33, 42, tzinfo=UTC)
    df = generate_deterministic_synthetic_bars("BTCUSDT", bars_count=100, end_time=anchor_dt)

    # Anchor 15:33:42 belongs to 15:30-15:35 bar.
    # The last closed 5m bar open is 15:25:00 UTC.
    last_bar_ts = df.index[-1]
    expected_last = datetime(2026, 9, 6, 15, 25, 0, tzinfo=UTC)
    assert last_bar_ts == expected_last

    # Spacing between all consecutive bars must be exactly 300s
    diffs = df.index[1:] - df.index[:-1]
    assert (diffs == pd.Timedelta(minutes=5)).all()


# ===========================================================================
# 4. Concurrency, Session Pooling, and Resource Hygiene
# ===========================================================================


@pytest.mark.anyio
async def test_concurrent_fetching_across_all_symbols_with_gather() -> None:
    """Challenge: Simultaneous gather requests across all 4 symbols share session pool cleanly."""
    mock_klines = _make_mock_klines(count=105)

    class ConcurrencyMockTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.request_count = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.request_count += 1
            # Simulate slight asynchronous network scheduling jitter
            await asyncio.sleep(0.005)
            return httpx.Response(200, json=mock_klines, request=request)

    transport = ConcurrencyMockTransport()

    # Capture any ResourceWarnings as errors
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)

        async with BinancePublicRestClient(transport=transport) as client:
            tasks = [client.fetch_klines(sym, limit=100) for sym in SYMBOLS]
            results = await asyncio.gather(*tasks)

            assert len(results) == 4
            for _sym, df in zip(SYMBOLS, results, strict=True):
                assert len(df) == 100
                validate_canonical_dataframe(df)

        assert transport.request_count == 4


@pytest.mark.anyio
async def test_high_concurrency_stress_20_simultaneous_requests() -> None:
    """Challenge: Stress test 20 concurrent requests through shared client session."""
    mock_klines = _make_mock_klines(count=105)

    class LatencyTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.002)
            return httpx.Response(200, json=mock_klines, request=request)

    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)

        async with BinancePublicRestClient(transport=LatencyTransport()) as client:
            tasks = [client.fetch_klines(sym, limit=100) for sym in SYMBOLS * 5]
            results = await asyncio.gather(*tasks)
            assert len(results) == 20
            for df in results:
                assert len(df) == 100


@pytest.mark.anyio
async def test_concurrent_offline_fallback_cascade_gather() -> None:
    """Challenge: fetch_klines_with_fallback executed concurrently for all symbols."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)

        tasks = [fetch_klines_with_fallback(sym, offline=True) for sym in SYMBOLS]
        results = await asyncio.gather(*tasks)
        assert len(results) == 4
        for _sym, df in zip(SYMBOLS, results, strict=True):
            assert len(df) == 100
            validate_canonical_dataframe(df)


@pytest.mark.anyio
async def test_standalone_helper_clean_lifecycle_no_warnings() -> None:
    """Challenge: Standalone helper manages lifecycle with zero unclosed clients."""
    mock_klines = _make_mock_klines(count=105)

    class SimpleTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=mock_klines, request=request)

    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)

        tasks = [fetch_binance_futures_klines(sym, transport=SimpleTransport()) for sym in SYMBOLS]
        results = await asyncio.gather(*tasks)
        assert len(results) == 4


# ===========================================================================
# 5. Security & Boundary Defense-in-Depth
# ===========================================================================


@pytest.mark.parametrize(
    "forbidden_kwarg",
    [
        {"api_key": "injected_key"},
        {"API_SECRET": "injected_secret"},
        {"X-MBX-APIKEY": "injected_header"},
        {"Authorization": "Bearer token"},
        {"private_key": "secret"},
    ],
)
def test_adversarial_credential_injection_rejected(forbidden_kwarg: dict[str, Any]) -> None:
    """Challenge: Any attempt to supply credentials must raise BinanceSecurityViolation."""
    with pytest.raises(BinanceSecurityViolation):
        BinancePublicRestClient(**forbidden_kwarg)

    with pytest.raises(BinanceSecurityViolation):
        BinancePublicRestClient(headers=forbidden_kwarg)


def test_boundary_calculation_edge_cases() -> None:
    """Challenge: Closed bar boundary calculation must be mathematically invariant."""
    base_epoch = 1_700_000_100_000
    aligned_start = base_epoch - (base_epoch % 300_000)

    # Case 1: Exactly at bar start (0ms into bar) -> returns previous bar closing ms
    boundary_exact = calculate_closed_bar_boundary(aligned_start)
    expected = aligned_start - 1
    assert boundary_exact == expected

    # Case 2: 1ms before bar close -> still returns previous bar closing ms
    now_ms = aligned_start + 299_999
    boundary_late = calculate_closed_bar_boundary(now_ms)
    assert boundary_late == expected

    # Case 3: Negative timestamp rejected
    with pytest.raises(ValueError, match="non-negative"):
        calculate_closed_bar_boundary(-5)

    # Case 4: Non-positive interval rejected
    with pytest.raises(ValueError, match="strictly positive"):
        calculate_closed_bar_boundary(1_000_000, interval_ms=0)
