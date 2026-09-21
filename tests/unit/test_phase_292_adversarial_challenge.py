"""Adversarial and stress verification tests for Phase 292 Live Public Market Ingress.

Authored by challenger_2 to empirically verify:
1. Packet latency & heartbeat freshness (<= 500 ms threshold assertions and stale packet flagging).
2. Clock skew telemetry (clock drift calculations, backward jumps, mock failure modes).
3. FastAPI /api/v1/canary/live-market route (200 valid, 404 missing, 503 tampered).
4. Accounting zero-drift invariant (|drift| < 1e-15 USDT, zero authority, paper safety).
5. Stream sequencer deduplication, gap tracking, and wire parser boundary defenses.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from autonomous_futures.api import create_app  # noqa: E402
from autonomous_futures.feed.client import (  # noqa: E402
    BinancePublicFeedClient,
    PublicMarketStreamSequencer,
)
from autonomous_futures.feed.models import parse_binance_depth5  # noqa: E402
from autonomous_futures.feed.telemetry import FeedTelemetryAccumulator  # noqa: E402
from scripts.run_phase_292_live_ingress import (  # noqa: E402
    MAX_GATEWAY_LATENCY_MS,
    run_phase_292_live_ingress,
)


def _api_request(app: FastAPI, method: str, path: str) -> httpx.Response:
    async def _send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path)

    return asyncio.run(_send())


# =====================================================================
# Focus 1: Packet Latency & Heartbeat Freshness (<= 500 ms Bound)
# =====================================================================


class TestPacketLatencyAndHeartbeatFreshness:
    """Stress tests for packet latency tracking and heartbeat age boundaries."""

    def test_heartbeat_freshness_within_500ms_boundary(self) -> None:
        """Verify that heartbeat age <= 500.0 ms is marked healthy."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))
        now_ms = time.time_ns() / 1_000_000.0

        # Case A: Received 10ms ago
        client.last_heartbeat_time_ms = now_ms - 10.0
        assert client.heartbeat_age_ms < 500.0
        assert client.is_heartbeat_healthy is True

        # Case B: Received 250ms ago
        client.last_heartbeat_time_ms = now_ms - 250.0
        assert client.heartbeat_age_ms < 500.0
        assert client.is_heartbeat_healthy is True

        # Case C: Received exactly 499.9ms ago
        client.last_heartbeat_time_ms = now_ms - 499.9
        assert client.is_heartbeat_healthy is True

    def test_heartbeat_stale_flagging_beyond_500ms_boundary(self) -> None:
        """Verify that heartbeat age > 500.0 ms is flagged as stale (unhealthy)."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))
        now_ms = time.time_ns() / 1_000_000.0

        # Case A: 501.0 ms ago (just over threshold)
        client.last_heartbeat_time_ms = now_ms - 501.0
        assert client.heartbeat_age_ms >= 500.0
        assert client.is_heartbeat_healthy is False

        # Case B: 1000.0 ms ago
        client.last_heartbeat_time_ms = now_ms - 1000.0
        assert client.is_heartbeat_healthy is False

        # Case C: 60,000.0 ms ago (dropped connection / silent feed)
        client.last_heartbeat_time_ms = now_ms - 60000.0
        assert client.is_heartbeat_healthy is False

    def test_heartbeat_age_uninitialized_state(self) -> None:
        """Verify initial state behavior before any messages arrive."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))
        assert client.last_heartbeat_time_ms == 0.0
        assert client.heartbeat_age_ms == 0.0
        assert client.is_heartbeat_healthy is True

    def test_latency_calculation_with_future_or_skewed_timestamps(self) -> None:
        """Adversarial test: packet timestamp is in the future relative to local clock."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))

        class MockWs:
            def __init__(self, messages: list[str]) -> None:
                self.messages = list(messages)

            async def recv(self) -> str:
                if not self.messages:
                    raise TimeoutError()
                return self.messages.pop(0)

        now_ms = int(time.time() * 1000)
        # Message with future event timestamp (10,000 ms into future)
        future_msg = json.dumps(
            {
                "stream": "btcusdt@aggTrade",
                "data": {
                    "e": "aggTrade",
                    "E": now_ms + 10000,
                    "s": "BTCUSDT",
                    "a": 1,
                    "p": "65000.00",
                    "q": "0.1",
                    "f": 1,
                    "l": 1,
                    "T": now_ms + 10000,
                    "m": False,
                },
            }
        )

        ws = MockWs([future_msg])
        # Consuming future timestamp should not result in negative latency (clamped to 0.0)
        asyncio.run(client.consume_stream(ws, duration_seconds=0.05))
        assert client.last_latency_ms == 0.0
        assert client.total_messages_received == 1

    def test_latency_calculation_with_stale_delayed_timestamps(self) -> None:
        """Adversarial test: packet timestamp arrived 2,500 ms after creation."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))

        class MockWs:
            def __init__(self, messages: list[str]) -> None:
                self.messages = list(messages)

            async def recv(self) -> str:
                if not self.messages:
                    raise TimeoutError()
                return self.messages.pop(0)

        now_ms = int(time.time() * 1000)
        delayed_msg = json.dumps(
            {
                "stream": "btcusdt@aggTrade",
                "data": {
                    "e": "aggTrade",
                    "E": now_ms - 2500,
                    "s": "BTCUSDT",
                    "a": 2,
                    "p": "65000.00",
                    "q": "0.1",
                    "f": 2,
                    "l": 2,
                    "T": now_ms - 2500,
                    "m": False,
                },
            }
        )

        ws = MockWs([delayed_msg])
        asyncio.run(client.consume_stream(ws, duration_seconds=0.05))
        # Latency should be roughly 2500ms
        assert client.last_latency_ms >= 2400.0
        assert client.last_latency_ms > MAX_GATEWAY_LATENCY_MS

    def test_telemetry_accumulator_percentiles_under_latency_spikes(self) -> None:
        """Stress-test FeedTelemetryAccumulator percentiles under extreme latency spikes."""
        acc = FeedTelemetryAccumulator(symbols=("BTCUSDT",))
        acc.start()

        base_time = 1726912800000.0
        # 95 nominal packets at 15ms latency
        for i in range(95):
            acc.record_message(
                "btcusdt@depth5@100ms", "BTCUSDT", int(base_time + i), base_time + i + 15.0
            )

        # 5 severe spike packets at 1200ms latency
        for i in range(95, 100):
            acc.record_message(
                "btcusdt@depth5@100ms", "BTCUSDT", int(base_time + i), base_time + i + 1200.0
            )

        acc.stop()
        snap = acc.snapshot()

        assert snap.total_messages == 100
        assert snap.latency_overall.min_ms == pytest.approx(15.0)
        assert snap.latency_overall.p50_ms == pytest.approx(15.0)
        assert snap.latency_overall.max_ms == pytest.approx(1200.0)
        assert snap.latency_overall.p99_ms == pytest.approx(1200.0)


# =====================================================================
# Focus 2: Clock Skew Telemetry & Drift Calculations
# =====================================================================


class TestClockSkewTelemetryAndDrift:
    """Stress tests for server clock synchronization, backward clock jumps, and mock failures."""

    def test_clock_skew_positive_drift(self) -> None:
        """Verify clock skew calculation when Binance server is 250ms ahead."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        # Fix local time and server time
        fixed_wall_ms = 1726912800000.0
        server_time_ms = int(fixed_wall_ms + 250)  # +250ms server ahead
        mock_resp.json = lambda: {"serverTime": server_time_ms}

        with (
            patch("time.time", return_value=fixed_wall_ms / 1000.0),
            patch("time.perf_counter", side_effect=[0.0, 0.02]),  # 20ms RTT
            patch("httpx.AsyncClient.get", return_value=mock_resp),
        ):
            skew = asyncio.run(client.sync_server_time())
            # Expected: server_ms - (t0_wall + RTT/2) = +250 - 10 = +240ms
            assert skew == pytest.approx(240.0, abs=1.0)
            assert client.clock_skew_ms == skew

    def test_clock_skew_negative_drift(self) -> None:
        """Verify clock skew calculation when Binance server is 300ms behind."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None

        fixed_wall_ms = 1726912800000.0
        server_time_ms = int(fixed_wall_ms - 300)  # -300ms server behind
        mock_resp.json = lambda: {"serverTime": server_time_ms}

        with (
            patch("time.time", return_value=fixed_wall_ms / 1000.0),
            patch("time.perf_counter", side_effect=[0.0, 0.01]),  # 10ms RTT
            patch("httpx.AsyncClient.get", return_value=mock_resp),
        ):
            skew = asyncio.run(client.sync_server_time())
            # Expected: server_ms - (t0_wall + RTT/2) = -300 - 5 = -305ms
            assert skew == pytest.approx(-305.0, abs=1.0)

    def test_clock_skew_backward_clock_jump_handling(self) -> None:
        """Verify clock skew handling if local wall clock experiences NTP backward step."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: {"serverTime": 1726912800000}

        # Local clock jumped backward to 1726912700000 (100 seconds prior)
        with (
            patch("time.time", return_value=1726912700.0),
            patch("time.perf_counter", side_effect=[100.0, 100.02]),  # strictly monotonic RTT
            patch("httpx.AsyncClient.get", return_value=mock_resp),
        ):
            skew = asyncio.run(client.sync_server_time())
            # Monotonic RTT prevents negative RTT; skew accurately measures disparity
            assert skew > 99000.0

    def test_fapi_v1_time_http_404_error(self) -> None:
        """Verify that HTTP 404 response raises HTTPStatusError."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))
        mock_resp = AsyncMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status = lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError("404 Not Found", request=AsyncMock(), response=mock_resp)
        )

        with (
            patch("httpx.AsyncClient.get", return_value=mock_resp),
            pytest.raises(httpx.HTTPStatusError),
        ):
            asyncio.run(client.sync_server_time())

    def test_fapi_v1_time_http_503_error(self) -> None:
        """Verify that HTTP 503 response raises HTTPStatusError."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))
        mock_resp = AsyncMock()
        mock_resp.status_code = 503
        mock_resp.raise_for_status = lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError(
                "503 Service Unavailable", request=AsyncMock(), response=mock_resp
            )
        )

        with (
            patch("httpx.AsyncClient.get", return_value=mock_resp),
            pytest.raises(httpx.HTTPStatusError),
        ):
            asyncio.run(client.sync_server_time())

    def test_fapi_v1_time_network_timeout(self) -> None:
        """Verify that network timeout raises TimeoutException."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))

        with (
            patch(
                "httpx.AsyncClient.get",
                side_effect=httpx.TimeoutException("Connection timed out"),
            ),
            pytest.raises(httpx.TimeoutException),
        ):
            asyncio.run(client.sync_server_time())

    def test_fapi_v1_time_malformed_json_responses(self) -> None:
        """Verify that malformed or unexpected responses raise ValueError."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))

        # Case 1: Array instead of dict
        mock_resp1 = AsyncMock()
        mock_resp1.status_code = 200
        mock_resp1.raise_for_status = lambda: None
        mock_resp1.json = lambda: [1726912800000]

        with (
            patch("httpx.AsyncClient.get", return_value=mock_resp1),
            pytest.raises(ValueError, match="Invalid response"),
        ):
            asyncio.run(client.sync_server_time())

        # Case 2: Missing serverTime key
        mock_resp2 = AsyncMock()
        mock_resp2.status_code = 200
        mock_resp2.raise_for_status = lambda: None
        mock_resp2.json = lambda: {"status": "ok"}

        with (
            patch("httpx.AsyncClient.get", return_value=mock_resp2),
            pytest.raises(ValueError, match="Invalid response"),
        ):
            asyncio.run(client.sync_server_time())

        # Case 3: Non-integer serverTime value
        mock_resp3 = AsyncMock()
        mock_resp3.status_code = 200
        mock_resp3.raise_for_status = lambda: None
        mock_resp3.json = lambda: {"serverTime": "invalid_number"}

        with (
            patch("httpx.AsyncClient.get", return_value=mock_resp3),
            pytest.raises(ValueError),
        ):
            asyncio.run(client.sync_server_time())


# =====================================================================
# Focus 3: FastAPI /api/v1/canary/live-market Route (200 / 404 / 503)
# =====================================================================


class TestFastAPILiveMarketEndpoint:
    """Stress tests for FastAPI /api/v1/canary/live-market endpoint."""

    def test_live_market_endpoint_200_valid_artifacts(self, tmp_path: Path) -> None:
        """Verify HTTP 200 and schema validity on fresh verified Phase 292 artifacts."""
        out_dir = tmp_path / "phase292_valid"
        run_phase_292_live_ingress(
            output_dir=out_dir,
            offline_replay=True,
            candidates=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        )

        app = create_app(canary_phase_dir=out_dir)
        res = _api_request(app, "GET", "/api/v1/canary/live-market")

        assert res.status_code == 200
        data = res.json()
        assert data["verified"] is True
        assert data["phase"] == "phase_292"
        assert data["paper_safe"] is True
        assert data["execution_authority"] is False
        assert set(data["candidates"]) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        assert len(data["orderbooks"]) == 3
        assert len(data["recent_trades"]) >= 3
        assert len(data["mark_prices"]) == 3
        assert data["gateway_health"]["is_healthy"] is True

    def test_live_market_endpoint_404_missing_directory(self, tmp_path: Path) -> None:
        """Verify HTTP 404 when target canary phase directory does not exist."""
        missing_dir = tmp_path / "does_not_exist"
        app = create_app(canary_phase_dir=missing_dir)

        res = _api_request(app, "GET", "/api/v1/canary/live-market")
        assert res.status_code == 404
        assert "unavailable" in res.json()["detail"]

    def test_live_market_endpoint_404_missing_sqlite_database(self, tmp_path: Path) -> None:
        """Verify HTTP 404 when summary exists but SQLite database is absent."""
        out_dir = tmp_path / "phase292_missing_db"
        run_phase_292_live_ingress(output_dir=out_dir, offline_replay=True)

        # Delete database
        db_file = out_dir / "canary-market-telemetry.sqlite3"
        db_file.unlink()

        app = create_app(canary_phase_dir=out_dir)
        res = _api_request(app, "GET", "/api/v1/canary/live-market")
        assert res.status_code == 404
        assert "unavailable" in res.json()["detail"]

    def test_live_market_endpoint_404_missing_report_json(self, tmp_path: Path) -> None:
        """Verify HTTP 404 when summary exists but referenced report JSON is missing."""
        out_dir = tmp_path / "phase292_missing_report"
        run_phase_292_live_ingress(output_dir=out_dir, offline_replay=True)

        report_file = out_dir / "canary-live-market-report.json"
        report_file.unlink()

        app = create_app(canary_phase_dir=out_dir)
        res = _api_request(app, "GET", "/api/v1/canary/live-market")
        assert res.status_code == 404

    def test_live_market_endpoint_503_tampered_sqlite_database(self, tmp_path: Path) -> None:
        """Verify HTTP 503 when SQLite telemetry database content is tampered with."""
        out_dir = tmp_path / "phase292_tampered_db"
        run_phase_292_live_ingress(output_dir=out_dir, offline_replay=True)

        db_file = out_dir / "canary-market-telemetry.sqlite3"
        # Modify single byte
        db_bytes = bytearray(db_file.read_bytes())
        db_bytes[-1] ^= 0xFF
        db_file.write_bytes(bytes(db_bytes))

        app = create_app(canary_phase_dir=out_dir)
        res = _api_request(app, "GET", "/api/v1/canary/live-market")
        assert res.status_code == 503
        assert "integrity verification failed" in res.json()["detail"]

    def test_live_market_endpoint_503_tampered_report_json(self, tmp_path: Path) -> None:
        """Verify HTTP 503 when canary report JSON content is tampered with."""
        out_dir = tmp_path / "phase292_tampered_report"
        run_phase_292_live_ingress(output_dir=out_dir, offline_replay=True)

        report_file = out_dir / "canary-live-market-report.json"
        content = report_file.read_text(encoding="utf-8")
        report_file.write_text(content + " ", encoding="utf-8")

        app = create_app(canary_phase_dir=out_dir)
        res = _api_request(app, "GET", "/api/v1/canary/live-market")
        assert res.status_code == 503
        assert "integrity verification failed" in res.json()["detail"]

    def test_live_market_endpoint_503_corrupt_summary_json(self, tmp_path: Path) -> None:
        """Verify HTTP 503 when summary JSON file syntax is corrupted."""
        out_dir = tmp_path / "phase292_corrupt_json"
        out_dir.mkdir()
        (out_dir / "live-market-summary.json").write_text(
            "{corrupt: json syntax...", encoding="utf-8"
        )

        app = create_app(canary_phase_dir=out_dir)
        res = _api_request(app, "GET", "/api/v1/canary/live-market")
        assert res.status_code == 503
        assert "integrity verification failed" in res.json()["detail"]


# =====================================================================
# Focus 4: Accounting Zero-Drift Invariant (|drift| < 1e-15 USDT)
# =====================================================================


class TestAccountingZeroDriftAndPaperSafeInvariants:
    """Stress tests verifying mathematical balance zero drift and paper-safe isolation."""

    def test_accounting_zero_drift_under_various_candidate_sets(self, tmp_path: Path) -> None:
        """Verify |drift| < 1e-15 USDT holds across various symbol configurations."""
        candidate_sets = [
            ["BTCUSDT"],
            ["BTCUSDT", "ETHUSDT"],
            ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        ]

        for idx, syms in enumerate(candidate_sets):
            out_dir = tmp_path / f"phase292_drift_{idx}"
            res = run_phase_292_live_ingress(
                output_dir=out_dir,
                offline_replay=True,
                candidates=syms,
            )

            assert res["status"] == "PASS"
            assert res["zero_balance_drift"] is True

            # Inspect report JSON
            report = json.loads((out_dir / "canary-live-market-report.json").read_text("utf-8"))
            starting = Decimal(report["balance_reconciliation"]["starting_capital_usdt"])
            final = Decimal(report["balance_reconciliation"]["final_cash_usdt"])
            drift = Decimal(report["balance_reconciliation"]["drift_usdt"])

            assert abs(drift) < Decimal("1e-15")
            assert starting == Decimal("100.00")
            assert final == Decimal("100.00")
            assert report["orders_submitted_count"] == 0
            assert report["execution_authority"] is False
            assert report["paper_safe"] is True

            # Inspect summary files
            live_sum = json.loads((out_dir / "live-market-summary.json").read_text("utf-8"))
            assert live_sum["zero_balance_drift"] is True
            assert Decimal(live_sum["drift_usdt"]) == Decimal("0.00")

            paper_sum = json.loads((out_dir / "paper-summary.json").read_text("utf-8"))
            assert paper_sum["zero_balance_drift"] is True
            assert Decimal(paper_sum["drift_usdt"]) == Decimal("0.00")
            assert paper_sum["orders_count"] == 0

    def test_strict_rejection_of_credentials(self) -> None:
        """Verify that client strictly rejects any credentials or auth parameters."""
        forbidden_params = [
            {"api_key": "dummy_key"},
            {"api_secret": "dummy_secret"},
            {"secret": "dummy"},
            {"token": "dummy_jwt"},
            {"password": "secret_pass"},
            {"auth": "bearer_token"},
            {"private_key": "pem_data"},
        ]

        for kw in forbidden_params:
            with pytest.raises(ValueError, match="strictly forbidden"):
                BinancePublicFeedClient(symbols=("BTCUSDT",), **kw)  # type: ignore[arg-type]

    def test_client_defaults_enforce_paper_safety(self) -> None:
        """Verify feed client default properties enforce zero authority."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))
        assert client.execution_authority is False
        assert client.paper_safe is True
        assert client.api_key is None
        assert client.api_secret is None
        assert client.get_connect_headers() == {}


# =====================================================================
# Focus 5: Wire Models & Stream Sequencer Boundary Defenses
# =====================================================================


class TestWireModelsAndStreamSequencerBoundaries:
    """Stress tests for wire frame parsing edge cases and stream sequencer deduplication."""

    def test_crossed_book_rejection(self) -> None:
        """Verify that crossed orderbook (bid > ask) is strictly rejected."""
        payload = {
            "s": "ETHUSDT",
            "u": 200,
            "b": [["3500.00", "1.0"]],
            "a": [["3499.00", "1.0"]],  # ask lower than bid
            "E": 1726912800000,
        }
        with pytest.raises(ValueError, match="crossed book detected"):
            parse_binance_depth5(payload)

    def test_locked_book_allowed(self) -> None:
        """Verify that locked orderbook (bid == ask) is permitted without crash."""
        payload = {
            "s": "ETHUSDT",
            "u": 201,
            "b": [["3500.00", "1.0"]],
            "a": [["3500.00", "1.0"]],  # locked book
            "E": 1726912800000,
        }
        snap = parse_binance_depth5(payload)
        assert snap.best_bid_price == Decimal("3500.00")
        assert snap.best_ask_price == Decimal("3500.00")
        assert snap.spread == Decimal("0.00")
        assert snap.spread_bps == Decimal("0.00")

    def test_sequencer_gap_and_duplicate_tracking(self) -> None:
        """Stress-test stream sequencer tracking under rapid sequence changes."""
        seq = PublicMarketStreamSequencer()

        # Step 1: First depth frame u=100
        is_dup, is_gap = seq.check_depth("BTCUSDT", u=100)
        assert (is_dup, is_gap) == (False, False)

        # Step 2: Duplicate frame u=100
        is_dup, is_gap = seq.check_depth("BTCUSDT", u=100)
        assert (is_dup, is_gap) == (True, False)

        # Step 3: Out of order frame u=95
        is_dup, is_gap = seq.check_depth("BTCUSDT", u=95)
        assert (is_dup, is_gap) == (True, False)

        # Step 4: Gap detected: u=110 with pu=105 (expected 100)
        is_dup, is_gap = seq.check_depth("BTCUSDT", u=110, pu=105)
        assert (is_dup, is_gap) == (False, True)
        assert seq.sequence_gap_count == 1
        assert seq.duplicate_count == 2

        # Step 5: Reset clears all counters
        seq.reset()
        assert seq.sequence_gap_count == 0
        assert seq.duplicate_count == 0

    def test_sequencer_cross_symbol_isolation(self) -> None:
        """Verify that sequence tracking for one symbol does not leak into another."""
        seq = PublicMarketStreamSequencer()

        # BTCUSDT at u=1000
        seq.check_depth("BTCUSDT", u=1000)
        # ETHUSDT at u=500 (lower than BTC, but should NOT be considered duplicate)
        is_dup, is_gap = seq.check_depth("ETHUSDT", u=500)
        assert is_dup is False
        assert is_gap is False

        # SOLUSDT at u=200
        is_dup, is_gap = seq.check_depth("SOLUSDT", u=200)
        assert is_dup is False
        assert is_gap is False

        # Duplicate check per symbol
        assert seq.check_depth("BTCUSDT", u=999)[0] is True
        assert seq.check_depth("ETHUSDT", u=499)[0] is True
        assert seq.check_depth("SOLUSDT", u=199)[0] is True

    def test_client_exponential_backoff_extreme_attempts(self) -> None:
        """Verify backoff behavior under extreme attempt values (negative, zero, very large)."""
        client = BinancePublicFeedClient(symbols=("BTCUSDT",))

        # Negative attempt -> clamped to 0.5s + jitter
        b_neg = client.compute_backoff_delay(attempt=-10, jitter=0.2)
        assert b_neg == pytest.approx(0.7)

        # Zero attempt -> 0.5s + jitter
        b_zero = client.compute_backoff_delay(attempt=0, jitter=0.2)
        assert b_zero == pytest.approx(0.7)

        # Huge attempt (100) -> capped at ceiling 8.0s + jitter
        b_huge = client.compute_backoff_delay(attempt=100, jitter=0.2)
        assert b_huge == pytest.approx(8.2)


class TestCLIRunnerAndSchemaIntegrity:
    """Stress tests for verification runner CLI flags and schema integrity."""

    def test_cli_runner_verify_only_flow(self, tmp_path: Path) -> None:
        """Verify that --verify-only returns 0 for valid phase and 1 for tampered phase."""
        from scripts.run_phase_292_live_ingress import main

        out_dir = tmp_path / "phase292_cli_verify"
        run_phase_292_live_ingress(output_dir=out_dir, offline_replay=True)

        # Valid verification
        code_valid = main(["--output-dir", str(out_dir), "--verify-only"])
        assert code_valid == 0

        # Tampered verification
        db_file = out_dir / "canary-market-telemetry.sqlite3"
        db_file.write_bytes(db_file.read_bytes() + b"\x01")
        code_tampered = main(["--output-dir", str(out_dir), "--verify-only"])
        assert code_tampered == 1
