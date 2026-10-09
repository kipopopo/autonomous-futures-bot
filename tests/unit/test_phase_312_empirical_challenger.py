"""Phase 312 Empirical Challenger Stress Test Suite.

Adversarially probes Milestone 1:
1. Candlestick data integrity across all 3 tiers (Live, Parquet fallback, Synthetic fallback):
   - Monotonic timestamps in Unix epoch seconds (not ms)
   - Price bounds: high >= low, high >= max(open, close), low <= min(open, close)
   - Non-negative volumes: volume >= 0
   - Positive prices: open > 0, high > 0, low > 0, close > 0
2. Complete simulated disconnection and network degradation.
3. Degraded & corrupted upstream payloads.
4. Boundary condition probing on query parameters.
5. In-memory 5s TTL cache invariants.
6. Local Parquet failure / corruption fallback to Tier 3 synthetic.
"""

from __future__ import annotations

import email.message
import io
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api import create_app


@pytest.fixture
def api_client(tmp_path: Path) -> TestClient:
    """Creates a TestClient isolated from active bundles."""
    app = create_app(
        bundle_path=tmp_path / "missing-bundle.json",
        registry_path=tmp_path / "missing-registry.json",
    )
    return TestClient(app)


def assert_candle_integrity(
    candles: list[dict[str, Any]], expected_count: int | None = None
) -> None:
    """Adversarially asserts all mathematical and logical invariants of candlestick bars."""
    assert len(candles) > 0, "Candles list must not be empty"
    if expected_count is not None:
        assert len(candles) == expected_count, (
            f"Expected {expected_count} candles, got {len(candles)}"
        )

    prev_ts = -1
    for idx, c in enumerate(candles):
        # 1. Required keys
        for key in ("timestamp", "open", "high", "low", "close", "volume"):
            assert key in c, f"Candle {idx} missing key '{key}'"

        ts = c["timestamp"]
        op = c["open"]
        hi = c["high"]
        lo = c["low"]
        cl = c["close"]
        vol = c["volume"]

        # 2. Timestamp format: Unix epoch seconds (not milliseconds)
        assert isinstance(ts, int), f"Candle {idx} timestamp must be int, got {type(ts)}"
        assert 1_000_000_000 < ts < 2_500_000_000, (
            f"Candle {idx} timestamp {ts} not in Unix seconds"
        )

        # 3. Monotonicity: strictly increasing
        if prev_ts != -1:
            assert ts > prev_ts, (
                f"Candle {idx} timestamp {ts} not strictly greater than previous {prev_ts}"
            )
        prev_ts = ts

        # 4. Price bounds
        assert hi >= lo, f"Candle {idx} high {hi} < low {lo}"
        assert hi >= op - 1e-6, f"Candle {idx} high {hi} < open {op}"
        assert hi >= cl - 1e-6, f"Candle {idx} high {hi} < close {cl}"
        assert lo <= op + 1e-6, f"Candle {idx} low {lo} > open {op}"
        assert lo <= cl + 1e-6, f"Candle {idx} low {lo} > close {cl}"

        # 5. Non-negativity and positive prices
        assert op > 0, f"Candle {idx} open must be > 0, got {op}"
        assert hi > 0, f"Candle {idx} high must be > 0, got {hi}"
        assert lo > 0, f"Candle {idx} low must be > 0, got {lo}"
        assert cl > 0, f"Candle {idx} close must be > 0, got {cl}"
        assert vol >= 0, f"Candle {idx} volume must be >= 0, got {vol}"


class TestAdversarialNetworkDisconnection:
    """Stress tests simulating network outages, timeouts, and HTTP errors."""

    @pytest.mark.parametrize(
        "exception_factory",
        [
            lambda: urllib.error.URLError("Network unreachable (Host down)"),
            lambda: TimeoutError("Socket connection timed out after 2500ms"),
            lambda: ConnectionResetError("Connection reset by peer"),
            lambda: urllib.error.HTTPError(
                "https://fapi.binance.com",
                429,
                "Too Many Requests",
                email.message.Message(),
                io.BytesIO(b"Rate limited"),
            ),
            lambda: urllib.error.HTTPError(
                "https://fapi.binance.com",
                418,
                "IP Banned",
                email.message.Message(),
                io.BytesIO(b"WAF ban"),
            ),
            lambda: urllib.error.HTTPError(
                "https://fapi.binance.com",
                500,
                "Internal Server Error",
                email.message.Message(),
                io.BytesIO(b"Error"),
            ),
            lambda: urllib.error.HTTPError(
                "https://fapi.binance.com",
                502,
                "Bad Gateway",
                email.message.Message(),
                io.BytesIO(b"Bad Gateway"),
            ),
            lambda: urllib.error.HTTPError(
                "https://fapi.binance.com",
                503,
                "Unavailable",
                email.message.Message(),
                io.BytesIO(b"Unavailable"),
            ),
        ],
        ids=[
            "URLError",
            "Timeout",
            "ConnectionReset",
            "HTTP_429",
            "HTTP_418",
            "HTTP_500",
            "HTTP_502",
            "HTTP_503",
        ],
    )
    def test_complete_disconnection_falls_back_cleanly(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        exception_factory: Callable[[], Exception],
    ) -> None:
        """Verifies that all network exceptions trigger automatic fallback without raising 500."""

        def mock_urlopen(*args: Any, **kwargs: Any) -> Any:
            raise exception_factory()

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        # Tier 2: SOLUSDT has local parquet
        res = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=40")
        assert res.status_code == 200
        data = res.json()
        assert data["symbol"] == "SOLUSDT"
        assert data["source"] in {"local_parquet_cache", "synthetic_fallback"}
        assert_candle_integrity(data["candles"], expected_count=40)

        # Tier 3: UNKNOWNUSDT has no local parquet -> must fall back to synthetic
        res_unknown = api_client.get(
            "/api/v1/market/klines?symbol=UNKNOWNUSDT&interval=15m&limit=30"
        )
        assert res_unknown.status_code == 200
        data_u = res_unknown.json()
        assert data_u["symbol"] == "UNKNOWNUSDT"
        assert data_u["source"] == "synthetic_fallback"
        assert_candle_integrity(data_u["candles"], expected_count=30)


class TestAdversarialUpstreamCorruption:
    """Stress tests simulating malformed, truncated, or hostile upstream payloads."""

    @pytest.mark.parametrize(
        "payload_bytes",
        [
            b"[]",  # Empty list
            b'{"code": -1121, "msg": "Invalid symbol."}',  # JSON object instead of array
            b"<!DOCTYPE html><html><body>502 Cloudflare Bad Gateway</body></html>",  # Raw HTML
            b"not even json",  # Corrupted bytes
            b"[[1700000000000, 100.0]]",  # Truncated row: missing high, low, close, volume
            b'[["1700000000000", "not_a_float", "100.0", "90.0", "95.0", "1000"]]',  # Non-float
            b"null",  # JSON null
        ],
        ids=[
            "empty_list",
            "json_dict_error",
            "html_error",
            "corrupt_bytes",
            "truncated_row",
            "non_float_price",
            "null_response",
        ],
    )
    def test_corrupted_upstream_payload_falls_back_gracefully(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        payload_bytes: bytes,
    ) -> None:
        """Verifies that invalid payloads never crash the API and trigger clean fallback."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = payload_bytes
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: mock_resp)

        res = api_client.get("/api/v1/market/klines?symbol=ETHUSDT&interval=1h&limit=25")
        assert res.status_code == 200
        data = res.json()
        assert data["symbol"] == "ETHUSDT"
        assert data["source"] in {"local_parquet_cache", "synthetic_fallback"}
        assert_candle_integrity(data["candles"], expected_count=25)


class TestAdversarialBoundaryConditions:
    """Stress tests probing parameter boundaries, intervals, and symbol normalizations."""

    def test_limit_boundary_minimum(self, api_client: TestClient) -> None:
        """limit=1 is the strict minimum valid boundary."""
        res = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=1")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1
        assert_candle_integrity(data["candles"], expected_count=1)

    def test_limit_boundary_maximum(
        self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """limit=1000 is the maximum valid boundary."""

        def mock_urlopen(*args: Any, **kwargs: Any) -> Any:
            raise urllib.error.URLError("Simulated offline")

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        res = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=1000")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1000
        assert_candle_integrity(data["candles"], expected_count=1000)

    @pytest.mark.parametrize("invalid_limit", [0, -1, -500, 1001, 5000, 999999])
    def test_limit_out_of_bounds_rejected(
        self, api_client: TestClient, invalid_limit: int
    ) -> None:
        """Out of bounds limit must fail closed with HTTP 422."""
        res = api_client.get(
            f"/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit={invalid_limit}"
        )
        assert res.status_code == 422

    @pytest.mark.parametrize(
        "valid_interval", ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]
    )
    def test_valid_intervals_accepted(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        valid_interval: str,
    ) -> None:
        """All supported intervals return 200 and conform to data invariants."""

        def mock_urlopen(*args: Any, **kwargs: Any) -> Any:
            raise urllib.error.URLError("Simulated offline")

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        res = api_client.get(
            f"/api/v1/market/klines?symbol=BTCUSDT&interval={valid_interval}&limit=10"
        )
        assert res.status_code == 200
        data = res.json()
        assert data["interval"] == valid_interval
        assert_candle_integrity(data["candles"], expected_count=10)

    @pytest.mark.parametrize(
        "invalid_interval", ["2m", "10m", "2h", "8h", "1w", "1M", "99m", ""]
    )
    def test_invalid_intervals_rejected(
        self, api_client: TestClient, invalid_interval: str
    ) -> None:
        """Unsupported intervals must return HTTP 422."""
        res = api_client.get(
            f"/api/v1/market/klines?symbol=BTCUSDT&interval={invalid_interval}"
        )
        assert res.status_code == 422

    def test_symbol_normalization_and_trimming(self, api_client: TestClient) -> None:
        """Symbols with lowercase and whitespace must be trimmed and upper-cased."""
        res = api_client.get(
            "/api/v1/market/klines?symbol=%20%20solusdt%20%20&interval=15m&limit=5"
        )
        assert res.status_code == 200
        data = res.json()
        assert data["symbol"] == "SOLUSDT"
        assert len(data["candles"]) == 5


class TestAdversarialCachingInvariants:
    """Stress tests on the 5-second TTL in-memory caching mechanism."""

    def test_cache_key_isolation_by_parameters(self, api_client: TestClient) -> None:
        """Verifies that different limits, intervals, or symbols do NOT collide in cache."""
        r_sol_10 = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=10")
        r_sol_20 = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=20")
        r_eth_10 = api_client.get("/api/v1/market/klines?symbol=ETHUSDT&interval=15m&limit=10")
        r_sol_1h = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=1h&limit=10")

        assert r_sol_10.status_code == 200
        assert r_sol_20.status_code == 200
        assert r_eth_10.status_code == 200
        assert r_sol_1h.status_code == 200

        assert r_sol_10.json()["count"] == 10
        assert r_sol_20.json()["count"] == 20
        assert r_eth_10.json()["symbol"] == "ETHUSDT"
        assert r_sol_1h.json()["interval"] == "1h"

    def test_cache_expiration_after_5_seconds(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulates time advance to verify cache refresh after 5.0 seconds."""
        current_time = [1700000000.0]

        def fake_time() -> float:
            return current_time[0]

        monkeypatch.setattr(time, "time", fake_time)

        # First call at t=0
        r1 = api_client.get("/api/v1/market/klines?symbol=TESTTTL&interval=15m&limit=10")
        assert r1.status_code == 200
        ts1 = r1.json()["timestamp_ms"]

        # Advance by 4.0 seconds -> must still be cached
        current_time[0] += 4.0
        r2 = api_client.get("/api/v1/market/klines?symbol=TESTTTL&interval=15m&limit=10")
        assert r2.status_code == 200
        assert r2.json()["timestamp_ms"] == ts1

        # Advance past 5.0 seconds (e.g. 5.2s) -> must invalidate and refresh
        current_time[0] += 1.2
        r3 = api_client.get("/api/v1/market/klines?symbol=TESTTTL&interval=15m&limit=10")
        assert r3.status_code == 200
        ts3 = r3.json()["timestamp_ms"]
        assert ts3 > ts1
        assert ts3 == int(current_time[0] * 1000)


class TestParquetCorruptionFallback:
    """Stress tests simulating corrupted local Parquet archives."""

    def test_corrupted_parquet_falls_through_to_synthetic(
        self,
        api_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If a local parquet file has missing columns or read failure, drop to synthetic."""

        def mock_urlopen(*args: Any, **kwargs: Any) -> Any:
            raise urllib.error.URLError("Network down")

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        def mock_read_parquet(*args: Any, **kwargs: Any) -> pd.DataFrame:
            return pd.DataFrame({"corrupted_col": [1, 2, 3]})

        monkeypatch.setattr(pd, "read_parquet", mock_read_parquet)

        res = api_client.get("/api/v1/market/klines?symbol=SOLUSDT&interval=15m&limit=15")
        assert res.status_code == 200
        data = res.json()
        assert data["source"] == "synthetic_fallback"
        assert_candle_integrity(data["candles"], expected_count=15)
