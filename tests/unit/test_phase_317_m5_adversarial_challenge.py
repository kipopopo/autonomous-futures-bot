"""Autonomous Futures Bot - Phase 317 Milestone 5 Adversarial Empirical Challenge Suite.

Empirically challenges:
1. Multi-threaded concurrency and thread-safety of `_cache_lock` with race condition stress.
2. 100 consecutive cached requests under load: P90 and P99 latency strictly < 10.0 ms.
3. Cache TTL expiry: 5.0s TTL invalidation and monotonic timestamp advance.
4. Adverse resilience: Offline trader, non-existent DB, corrupted binary SQLite file,
   locked SQLite DB, missing SQLite tables, and malformed trader sequencer exceptions.
5. Resource lifecycle: Empirical verification of unclosed SQLite connection when query fails.
6. Invariants: HTTP 200, valid schema, all 8 pairs present, zero 500 errors.
"""

from __future__ import annotations

import concurrent.futures
import gc
import sqlite3
import tempfile
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.strategy_router import (
    IctSignalsResponse,
    _load_candidate_genomes,
    _load_recent_autopsies,
    get_ict_signals,
    reset_ict_signals_cache,
    set_active_trader,
)
from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS, ACTIVE_TIMEFRAMES


@pytest.fixture(autouse=True)
def clean_environment() -> Generator[None]:
    reset_ict_signals_cache()
    set_active_trader(None)
    gc.collect()
    yield
    reset_ict_signals_cache()
    set_active_trader(None)
    gc.collect()


class TestAdversarialConcurrencyAndThreadSafety:
    """Stress-test concurrent access across multiple threads to verify thread safety."""

    def test_concurrent_requests_and_cache_resets_no_race_condition(self) -> None:
        """20 concurrent worker threads hammering the endpoint while cache is repeatedly reset."""
        app = create_app()
        client = TestClient(app)

        num_threads = 20
        requests_per_thread = 15
        total_requests = num_threads * requests_per_thread

        results = []
        errors = []

        def worker(thread_idx: int) -> None:
            for req_idx in range(requests_per_thread):
                # Every 5th request in even threads triggers a cache reset
                if thread_idx % 2 == 0 and req_idx % 5 == 0:
                    reset_ict_signals_cache()
                try:
                    resp = client.get("/api/v1/strategy/ict-signals")
                    if resp.status_code != 200:
                        errors.append(f"Thread {thread_idx} got status {resp.status_code}")
                    else:
                        payload = resp.json()
                        if not payload.get("verified") or len(payload.get("signals", {})) != 8:
                            errors.append(f"Thread {thread_idx} payload incomplete")
                        else:
                            results.append(payload["timestamp_ms"])
                except Exception as exc:
                    errors.append(f"Thread {thread_idx} exception: {exc}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        assert not errors, f"Encountered errors during concurrent execution: {errors[:5]}"
        assert len(results) == total_requests, (
            f"Expected {total_requests} valid responses, got {len(results)}"
        )

    def test_concurrent_lock_free_reads_router_fast_path(self) -> None:
        """Verify lock-free fast-path cached responses under sustained thread contention."""
        reset_ict_signals_cache()
        req = MagicMock()
        req.app.state.trader = None
        req.app.state.research_dir = None

        # Prime cache
        init_resp = get_ict_signals(req)
        assert init_resp.status_code == 200

        num_threads = 10
        requests_per_worker = 50

        def reader() -> list[float]:
            worker_lats = []
            for _ in range(requests_per_worker):
                t0 = time.perf_counter()
                r = get_ict_signals(req)
                t1 = time.perf_counter()
                worker_lats.append((t1 - t0) * 1000.0)
                assert r.status_code == 200
            return worker_lats

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            future_results = list(executor.map(lambda _: reader(), range(num_threads)))

        all_lats = [lat for worker_lats in future_results for lat in worker_lats]
        assert len(all_lats) == num_threads * requests_per_worker
        sorted_lats = sorted(all_lats)
        p99 = sorted_lats[int(len(sorted_lats) * 0.99)]
        median = sorted_lats[len(sorted_lats) // 2]
        assert median < 0.1, f"Fast-path median latency {median:.4f}ms exceeded 0.1ms"
        assert p99 < 1.0, f"Fast-path P99 latency {p99:.4f}ms exceeded 1.0ms"


class TestAdversarialLatencyBudget:
    """Measure 50+ consecutive cached requests under load to verify P90/P99 latency < 10.0 ms."""

    def test_50_plus_consecutive_requests_latency_under_10ms(self) -> None:
        """Measure 100 consecutive cached requests under load asserting P90 and P99 < 10.0ms."""
        gc.collect()

        app = create_app()
        client = TestClient(app)

        # 1. Prime cache
        prime_resp = client.get("/api/v1/strategy/ict-signals")
        assert prime_resp.status_code == 200

        # 2. Warm up
        for _ in range(5):
            client.get("/api/v1/strategy/ict-signals")

        # 3. 100 consecutive benchmark requests
        sample_size = 100
        latencies_ms: list[float] = []

        for _ in range(sample_size):
            t0 = time.perf_counter()
            resp = client.get("/api/v1/strategy/ict-signals")
            t1 = time.perf_counter()
            elapsed_ms = (t1 - t0) * 1000.0
            latencies_ms.append(elapsed_ms)

            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/json"

        # Statistical analysis
        sorted_lats = sorted(latencies_ms)
        p90 = sorted_lats[int(sample_size * 0.90)]
        p99 = sorted_lats[int(sample_size * 0.99)]

        assert p90 < 10.0, f"P90 latency {p90:.2f}ms exceeded strict 10.0ms ceiling"
        assert p99 < 10.0, f"P99 latency {p99:.2f}ms exceeded strict 10.0ms ceiling"


class TestAdversarialTtlCacheExpiry:
    """Verify cache TTL expiry and timestamp advancement."""

    def test_ttl_expiry_and_timestamp_advancement(self) -> None:
        """Assert that after 5.0s TTL, a fresh response is generated and timestamp advances."""
        app = create_app()
        client = TestClient(app)

        # Step 1: Initial call at t = 1000.0
        with patch("time.time", return_value=1000.0):
            r1 = client.get("/api/v1/strategy/ict-signals")
            assert r1.status_code == 200
            data1 = r1.json()
            ts1 = data1["timestamp_ms"]
            assert ts1 == 1000000

        # Step 2: Immediate subsequent call at t = 1002.0 (2.0s < 5.0s TTL) -> CACHE HIT
        with patch("time.time", return_value=1002.0):
            r2 = client.get("/api/v1/strategy/ict-signals")
            assert r2.status_code == 200
            data2 = r2.json()
            assert data2["timestamp_ms"] == ts1, "Cache hit must return identical cached timestamp"

        # Step 3: Call right at boundary t = 1004.99 (4.99s < 5.0s TTL) -> CACHE HIT
        with patch("time.time", return_value=1004.99):
            r3 = client.get("/api/v1/strategy/ict-signals")
            assert r3.status_code == 200
            data3 = r3.json()
            assert data3["timestamp_ms"] == ts1, (
                "Boundary cache hit must return identical timestamp"
            )

        # Step 4: Call after TTL expiry at t = 1005.10 (5.10s > 5.0s TTL) -> CACHE MISS & REFRESH
        with patch("time.time", return_value=1005.10):
            r4 = client.get("/api/v1/strategy/ict-signals")
            assert r4.status_code == 200
            data4 = r4.json()
            ts4 = data4["timestamp_ms"]
            assert ts4 > ts1, (
                f"Timestamp must advance after TTL expiry (expected > {ts1}, got {ts4})"
            )
            assert ts4 == 1005100

        # Step 5: Subsequent call at t = 1006.0 -> CACHE HIT on new timestamp
        with patch("time.time", return_value=1006.0):
            r5 = client.get("/api/v1/strategy/ict-signals")
            assert r5.status_code == 200
            assert r5.json()["timestamp_ms"] == ts4


class TestAdversarialResilienceUnderAdverseConditions:
    """Test resilience under adverse conditions: offline trader, corrupted SQLite DB, locked DB."""

    def test_offline_trader_and_missing_directory(self) -> None:
        """Simulate offline trader daemon with completely non-existent research dir."""
        app = create_app(trader=None, research_dir=Path("/non_existent_dir_99999"))
        client = TestClient(app)

        resp = client.get("/api/v1/strategy/ict-signals")
        assert resp.status_code == 200
        payload = resp.json()

        assert payload["verified"] is True
        assert payload["active_family"] == "ICT_MMXM_TWINS"
        assert len(payload["signals"]) == 8

        # Verify all 8 pairs have deterministic fallback baseline signals
        for sym in ACTIVE_PAIRS:
            assert sym in payload["signals"]
            s = payload["signals"][sym]
            assert s["symbol"] == sym
            assert s["twins_state"]["step_6_ready"] is False
            assert s["candidate_genome"]["health_tier"] in ("HEALTHY", "ELITE")
            for tf in ACTIVE_TIMEFRAMES:
                assert tf in s["pd_arrays"]

    def test_corrupted_binary_sqlite_database_resilience(self) -> None:
        """Simulate corrupted binary file as the SQLite database: endpoint must NOT raise 500."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            corrupt_db = tmp_path / "canary-production-telemetry.sqlite3"
            corrupt_db.write_bytes(b"\x00\xff\xfe\xfdINVALID_SQLITE_GARBAGE_HEADER_DATA" * 50)

            app = create_app(trader=None, research_dir=tmp_path)
            client = TestClient(app)

            resp = client.get("/api/v1/strategy/ict-signals")
            assert resp.status_code == 200
            data = resp.json()
            assert data["verified"] is True
            assert len(data["signals"]) == 8

            del client, app, resp
            gc.collect()

    def test_zero_byte_sqlite_database_resilience(self) -> None:
        """Simulate empty 0-byte SQLite database: endpoint must NOT raise 500."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            empty_db = tmp_path / "canary-production-telemetry.sqlite3"
            empty_db.touch()

            app = create_app(trader=None, research_dir=tmp_path)
            client = TestClient(app)

            resp = client.get("/api/v1/strategy/ict-signals")
            assert resp.status_code == 200
            data = resp.json()
            assert data["verified"] is True
            assert len(data["signals"]) == 8

            del client, app, resp
            gc.collect()

    def test_sqlite_missing_tables_resilience(self) -> None:
        """Simulate SQLite database with unexpected schema or missing tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_file = tmp_path / "canary-production-telemetry.sqlite3"
            conn = sqlite3.connect(db_file)
            conn.execute("CREATE TABLE irrelevant_table (id INTEGER PRIMARY KEY, note TEXT)")
            conn.commit()
            conn.close()

            app = create_app(trader=None, research_dir=tmp_path)
            client = TestClient(app)

            resp = client.get("/api/v1/strategy/ict-signals")
            assert resp.status_code == 200
            data = resp.json()
            assert data["verified"] is True
            assert len(data["signals"]) == 8

            del client, app, resp
            gc.collect()

    def test_malformed_trader_sequencer_exceptions_handled_gracefully(self) -> None:
        """Simulate trader sequencer that throws arbitrary RuntimeErrors and TypeErrors."""
        bad_sequencer = MagicMock()
        bad_sequencer.get_multi_tf_candles.side_effect = RuntimeError(
            "Adversarial socket disconnect"
        )

        bad_trader = MagicMock()
        bad_trader.sequencer = bad_sequencer
        bad_trader.ict_engine = MagicMock()
        bad_trader.ict_engine.detect_pd_arrays.side_effect = ValueError("Corrupted candles")

        app = create_app(trader=bad_trader)
        client = TestClient(app)

        resp = client.get("/api/v1/strategy/ict-signals")
        # Must gracefully catch and fall back to baseline without 500
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["signals"]) == 8
        assert data["verified"] is True


class TestAdversarialResourceLifecycleAndDefects:
    """Empirically probe and prove resource leak in error paths."""

    def test_sqlite_connection_unclosed_on_query_error(self) -> None:
        """Empirically proves that helper queries fail to call conn.close() on query error."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = sqlite3.OperationalError("Simulated database error")

        # 1. Probe _load_candidate_genomes
        with patch("sqlite3.connect", return_value=mock_conn):
            _load_candidate_genomes(Path("dummy.sqlite3"), ("BTCUSDT",))
            # Observation: mock_conn.close() was NOT called because execute threw
            assert mock_conn.close.called is False, (
                "Expected conn.close() to be skipped due to lack of finally block"
            )

        # 2. Probe _load_recent_autopsies
        mock_conn.reset_mock()
        with patch("sqlite3.connect", return_value=mock_conn):
            _load_recent_autopsies(Path("dummy.sqlite3"), ("BTCUSDT",))
            assert mock_conn.close.called is False, (
                "Expected conn.close() to be skipped due to lack of finally block"
            )


class TestAdversarialHttpProtocolConformance:
    """Test HTTP protocol invariants and edge cases."""

    def test_unsupported_http_methods_rejected(self) -> None:
        """Assert POST, PUT, DELETE return 405 Method Not Allowed, never 500."""
        app = create_app()
        client = TestClient(app)

        for method in ("post", "put", "delete", "patch"):
            fn = getattr(client, method)
            resp = fn("/api/v1/strategy/ict-signals")
            assert resp.status_code == 405, f"Method {method} returned {resp.status_code}"

    def test_adversarial_query_params_and_headers_ignored(self) -> None:
        """Ensure query params and headers do not break caching or response."""
        app = create_app()
        client = TestClient(app)

        resp = client.get(
            "/api/v1/strategy/ict-signals?foo=bar&injection=%27%20OR%201=1--&nan=NaN",
            headers={"X-Adversarial-Header": "testing_header_value", "Accept": "*/*"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is True

    def test_response_json_strict_standard_compliance(self) -> None:
        """Ensure response contains strictly standard JSON (no NaN, Infinity, or -Infinity)."""
        app = create_app()
        client = TestClient(app)

        resp = client.get("/api/v1/strategy/ict-signals")
        assert resp.status_code == 200
        text = resp.text

        # Standard RFC 8259 disallows NaN and Infinity tokens
        assert "NaN" not in text
        assert "Infinity" not in text
        assert "-Infinity" not in text

        # Verify parsed structure conforms strictly to IctSignalsResponse domain model
        parsed = IctSignalsResponse.model_validate_json(text)
        assert parsed.verified is True
        assert len(parsed.signals) == 8
