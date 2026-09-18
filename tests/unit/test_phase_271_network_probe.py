"""Unit tests for Phase 271: Canary Public Network Telemetry Probe & Ingress Latency Profiler."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.canary_probe import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DEFAULT_CANARY_SYMBOLS,
    MAX_SERVER_TIME_DRIFT_MS,
    AccountingDriftError,
    CanaryNetworkProbeRunner,
    CanaryProbeConfig,
    CanaryProbeSummary,
    ClockSyncDriftError,
    SafetyInvariantViolation,
    SqliteCanaryNetworkTelemetryStore,
    compute_percentile,
    evaluate_server_time_sync,
    run_canary_network_probe,
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    EXPECTED_MANIFEST_V2_CANDIDATES,
    load_and_validate_canary_staging_manifest,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)
from autonomous_futures.paper.staging import (  # noqa: E402
    CanaryStagingManifest,
    assert_zero_secrets,
    compute_file_sha256,
)
from scripts.run_phase_271_network_probe import (  # noqa: E402  # noqa: E402
    build_arg_parser,
    format_summary_table,
)
from scripts.run_phase_271_network_probe import (  # noqa: E402
    main as cli_main,
)


@pytest.fixture
def valid_manifest() -> CanaryStagingManifest:
    """Load and return verified Phase 269 Canary Staging Manifest."""
    manifest, _ = load_and_validate_canary_staging_manifest(
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        registry_path=DEFAULT_CANDIDATE_REGISTRY_PATH,
    )
    return manifest


@pytest.fixture
def isolated_store(tmp_path: Path) -> SqliteCanaryNetworkTelemetryStore:
    """Provide clean isolated SQLite store in a temporary directory."""
    db_path = tmp_path / "test-canary-telemetry.sqlite3"
    return SqliteCanaryNetworkTelemetryStore(db_path)


class TestPhase271ManifestAndCandidateValidation:
    """Validate dynamic ingestion of Canary Staging Manifest and candidate provenance."""

    def test_load_and_validate_verified_manifest(
        self, valid_manifest: CanaryStagingManifest
    ) -> None:
        assert valid_manifest.manifest_version >= 2
        assert valid_manifest.registry_version >= 2
        assert valid_manifest.staging_promotion_state == "canary_staged"
        assert set(valid_manifest.candidates.keys()) == set(DEFAULT_CANARY_SYMBOLS)
        for sym, exp_id in EXPECTED_MANIFEST_V2_CANDIDATES.items():
            cand = valid_manifest.candidates[sym]
            assert cand.candidate_id == exp_id
            assert cand.staging_promotion_state == "canary_staged"
            assert len(cand.candidate_artifact_hash) == 64
            assert len(cand.qualification_hash) == 64
            assert cand.allocated_risk_limits.allocated_margin_usdt == Decimal("20.0000")

    def test_tampered_manifest_hash_rejection(self, tmp_path: Path) -> None:
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        raw["manifest_hash"] = "0" * 64
        tampered_file = tmp_path / "tampered-manifest.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(DomainViolation, match="integrity check failed"):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_tampered_signature_rejection(self, tmp_path: Path) -> None:
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        raw["cryptographic_signature"] = "f" * 64
        tampered_file = tmp_path / "tampered-sig.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(DomainViolation, match="integrity check failed"):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_missing_candidate_rejection(self, tmp_path: Path) -> None:
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        del raw["candidates"]["SOLUSDT"]
        tampered_file = tmp_path / "missing-cand.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(DomainViolation):
            load_and_validate_canary_staging_manifest(tampered_file)

    def test_manifest_promotion_state_rejection(self, tmp_path: Path) -> None:
        with open(DEFAULT_CANARY_STAGING_MANIFEST_PATH, "rb") as f:
            raw = json.loads(f.read())
        raw["staging_promotion_state"] = "rejected"
        tampered_file = tmp_path / "rejected-manifest.json"
        with open(tampered_file, "w") as f:
            json.dump(raw, f)

        with pytest.raises(DomainViolation):
            load_and_validate_canary_staging_manifest(tampered_file)


class TestPhase271SqliteTelemetryStore:
    """Validate isolated SQLite store schemas, pragmas, and metric aggregations."""

    def test_pragmas_and_schema_initialization(
        self, isolated_store: SqliteCanaryNetworkTelemetryStore
    ) -> None:
        cur = isolated_store._conn.cursor()
        cur.execute("PRAGMA journal_mode")
        row = cur.fetchone()
        assert row[0].upper() == "WAL"

        cur.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1

        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        assert "connection_events" in tables
        assert "heartbeat_samples" in tables
        assert "clock_sync_samples" in tables
        assert "latency_marks" in tables
        assert "jitter_samples" in tables
        assert "accounting_ledger" in tables

    def test_connection_event_crud(self, isolated_store: SqliteCanaryNetworkTelemetryStore) -> None:
        rowid = isolated_store.record_connection_event(
            event_type="ws_handshake_success",
            endpoint="wss://fstream.binance.com/stream",
            duration_ms=88.5,
            success=True,
            details="Handshake upgrade 101 OK",
        )
        assert rowid > 0
        events = isolated_store.get_connection_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "ws_handshake_success"
        assert events[0]["duration_ms"] == 88.5
        assert events[0]["success"] is True

    def test_heartbeat_samples_and_stats(
        self, isolated_store: SqliteCanaryNetworkTelemetryStore
    ) -> None:
        rtts = [45.0, 50.0, 55.0, 60.0, 65.0]
        for idx, rtt in enumerate(rtts, 1):
            isolated_store.record_heartbeat(
                sequence_num=idx,
                ping_sent_ms=1000.0 * idx,
                pong_recv_ms=(1000.0 * idx) + rtt,
                rtt_ms=rtt,
            )
        stats = isolated_store.get_heartbeat_stats()
        assert stats["count"] == 5
        assert stats["min_rtt_ms"] == 45.0
        assert stats["max_rtt_ms"] == 65.0
        assert stats["mean_rtt_ms"] == 55.0
        assert stats["p50_rtt_ms"] == 55.0

    def test_empty_heartbeat_stats(self, isolated_store: SqliteCanaryNetworkTelemetryStore) -> None:
        stats = isolated_store.get_heartbeat_stats()
        assert stats["count"] == 0
        assert stats["p50_rtt_ms"] == 0.0

    def test_clock_sync_samples_and_stats(
        self, isolated_store: SqliteCanaryNetworkTelemetryStore
    ) -> None:
        isolated_store.record_clock_sync(
            client_time_ms=1726000000000.0,
            server_time_ms=1726000000015,
            drift_ms=15.0,
            rtt_ms=40.0,
            within_threshold=True,
        )
        isolated_store.record_clock_sync(
            client_time_ms=1726000010000.0,
            server_time_ms=1726000010025,
            drift_ms=25.0,
            rtt_ms=42.0,
            within_threshold=True,
        )
        stats = isolated_store.get_clock_sync_stats()
        assert stats["samples_count"] == 2
        assert stats["mean_drift_ms"] == 20.0
        assert stats["max_drift_ms"] == 25.0
        assert stats["within_threshold"] is True

    def test_latency_marks_and_stream_telemetry(
        self, isolated_store: SqliteCanaryNetworkTelemetryStore
    ) -> None:
        for sym in DEFAULT_CANARY_SYMBOLS:
            for i in range(10):
                isolated_store.record_latency_mark(
                    stream=f"{sym.lower()}@bookTicker",
                    symbol=sym,
                    event_type="bookTicker",
                    event_time_ms=1726000000000 + i * 100,
                    local_recv_ms=1726000000050.0 + i * 100,
                    latency_ms=50.0 + i,
                )
                isolated_store.record_jitter(
                    symbol=sym,
                    stream=f"{sym.lower()}@bookTicker",
                    prev_recv_ms=1726000000050.0 + (i - 1) * 100,
                    curr_recv_ms=1726000000050.0 + i * 100,
                    interval_ms=100.0,
                    jitter_ms=2.0,
                )

        tel = isolated_store.get_stream_telemetry(elapsed_seconds=1.0)
        assert tel["total_messages_received"] == 30
        assert tel["messages_per_second"] == 30.0
        for sym in DEFAULT_CANARY_SYMBOLS:
            assert sym in tel["symbol_stats"]
            assert tel["symbol_stats"][sym]["messages"] == 10
            assert tel["symbol_stats"][sym]["p50_latency_ms"] >= 50.0

    def test_accounting_ledger_crud(
        self, isolated_store: SqliteCanaryNetworkTelemetryStore
    ) -> None:
        isolated_store.record_accounting_ledger(
            starting_equity=Decimal("100.00"),
            final_cash=Decimal("100.00"),
            realized_pnl=Decimal("0.00"),
            unrealized_pnl=Decimal("0.00"),
            final_equity=Decimal("100.00"),
            drift=Decimal("0.00"),
            zero_drift=True,
            margin_utilization_pct=0.0,
            reserve_buffer_pct=100.0,
            margin_compliant=True,
        )
        rec = isolated_store.get_accounting_record()
        assert rec is not None
        assert rec["starting_equity_usdt"] == "100.00"
        assert rec["final_cash_usdt"] == "100.00"
        assert rec["drift_usdt"] == "0.00"
        assert rec["zero_drift"] == 1
        assert rec["margin_compliant"] == 1

    def test_store_context_manager_close(self, tmp_path: Path) -> None:
        db_p = tmp_path / "ctx_test.sqlite3"
        with SqliteCanaryNetworkTelemetryStore(db_p) as st:
            st.record_connection_event("event_a", "endpoint_a", 10.0, True)
        with pytest.raises(sqlite3.ProgrammingError):
            st._conn.execute("SELECT 1")


class TestPhase271ServerClockSynchronization:
    """Validate Binance server time synchronization drift measurement and thresholding."""

    @pytest.mark.anyio
    async def test_nominal_server_time_sync(self) -> None:
        sample = await evaluate_server_time_sync(simulate_drift_ms=12.5)
        assert sample.drift_ms == 12.5
        assert sample.within_threshold is True
        assert abs(sample.drift_ms) <= MAX_SERVER_TIME_DRIFT_MS

    @pytest.mark.anyio
    async def test_drift_exceeding_threshold(self) -> None:
        sample = await evaluate_server_time_sync(simulate_drift_ms=1250.0)
        assert sample.drift_ms == 1250.0
        assert sample.within_threshold is False
        assert abs(sample.drift_ms) > MAX_SERVER_TIME_DRIFT_MS

    @pytest.mark.anyio
    async def test_mock_rest_transport_clock_sync(self) -> None:
        class MockTimeHandler(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                import time

                now_ms = int(time.time() * 1000.0)
                return httpx.Response(
                    200,
                    json={"serverTime": now_ms + 10},
                    request=request,
                )

        client = httpx.AsyncClient(transport=MockTimeHandler())
        sample = await evaluate_server_time_sync(client=client)
        assert sample.within_threshold is True
        await client.aclose()


class TestPhase271RunnerAndSafetyGuards:
    """Validate runner lifecycle, bounded execution, and fail-closed safety."""

    def test_fail_closed_invariants_verification(self) -> None:
        invariants = verify_strict_fail_closed_invariants(orders_submitted=0)
        assert invariants["execution_authority"] is False
        assert invariants["exchange_access"] is False
        assert invariants["orders"] == 0
        assert invariants["api_keys_loaded"] == 0
        assert invariants["zero_secret_leakage"] is True

    def test_fail_closed_rejects_non_zero_orders(self) -> None:
        with pytest.raises(SafetyInvariantViolation, match="orders submitted"):
            verify_strict_fail_closed_invariants(orders_submitted=1)

    def test_fail_closed_rejects_api_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BINANCE_API_KEY", "prohibited_secret_api_key")
        with pytest.raises(SafetyInvariantViolation, match="api_keys_loaded"):
            verify_strict_fail_closed_invariants(orders_submitted=0)

    def test_deterministic_offline_replay_execution(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "probe_output"
        summary, db_path, rep_path, net_path, paper_path = run_canary_network_probe(
            output_dir=out_dir,
            probe_seconds=2.0,
            max_heartbeats=5,
            offline_replay=True,
        )
        assert summary.phase == "phase_271"
        assert summary.execution_mode == "offline_replay"
        assert summary.duration_seconds >= 0.0
        assert (
            summary.staged_manifest_hash
            == "1b5ea30d08031d06b8f20b19469ef56d42e2b79d2e5d6c79b094dda83bf4f013"
        )
        assert set(summary.candidates.keys()) == set(DEFAULT_CANARY_SYMBOLS)
        assert summary.heartbeat_profile["count"] == 5
        assert summary.heartbeat_profile["min_rtt_ms"] > 0
        assert summary.clock_sync_profile["within_threshold"] is True
        assert summary.stream_telemetry["total_messages_received"] == 300
        assert summary.portfolio_accounting["zero_balance_drift"] is True
        assert summary.portfolio_accounting["drift_usdt"] == "0"
        assert summary.portfolio_accounting["starting_equity_usdt"] == "100.00"
        assert summary.portfolio_accounting["final_cash_usdt"] == "100.00"
        assert summary.compliance["all_criteria_passed"] is True

        assert db_path.is_file()
        assert rep_path.is_file()
        assert net_path.is_file()
        assert paper_path.is_file()

        # Check file hashes
        db_hash = compute_file_sha256(db_path)
        assert summary.artifact_hashes["canary-network-telemetry.sqlite3"] == db_hash

        # Assert zero secrets in all JSON artifacts
        for p in (rep_path, net_path, paper_path):
            with open(p, "rb") as f:
                content = f.read()
            assert_zero_secrets(content, str(p))

    def test_simulate_clock_drift_failure(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "drift_fail"
        with pytest.raises(ClockSyncDriftError, match="exceeds safety threshold"):
            run_canary_network_probe(
                output_dir=out_dir,
                offline_replay=True,
                simulate_clock_drift=True,
            )

    def test_simulate_accounting_drift_failure(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "acct_fail"
        with pytest.raises(AccountingDriftError, match="drift violation"):
            run_canary_network_probe(
                output_dir=out_dir,
                offline_replay=True,
                simulate_adverse_drift=True,
            )

    def test_clean_slate_isolation_across_runs(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "isolation"
        summary1, db_path, _, _, _ = run_canary_network_probe(
            output_dir=out_dir,
            max_heartbeats=2,
            offline_replay=True,
        )
        assert summary1.heartbeat_profile["count"] == 2

        summary2, _, _, _, _ = run_canary_network_probe(
            output_dir=out_dir,
            max_heartbeats=4,
            offline_replay=True,
        )
        assert summary2.heartbeat_profile["count"] == 4


class TestPhase271CLIRunner:
    """Validate CLI harness argument parsing and execution."""

    def test_cli_parser_defaults(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.manifest_path == DEFAULT_CANARY_STAGING_MANIFEST_PATH
        assert args.probe_seconds == 30.0
        assert args.max_heartbeats == 10
        assert args.offline_replay is False

    def test_cli_execution_offline_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out_dir = tmp_path / "cli_out"
        stdout_capture = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout_capture)

        code = cli_main(
            [
                "--output-dir",
                str(out_dir),
                "--probe-seconds",
                "1",
                "--max-heartbeats",
                "2",
                "--offline-replay",
                "--json",
            ]
        )
        assert code == 0
        output = stdout_capture.getvalue()
        payload = json.loads(output)
        assert payload["phase"] == "phase_271"
        assert payload["execution_mode"] == "offline_replay"
        assert payload["portfolio_accounting"]["zero_balance_drift"] is True

    def test_cli_table_formatting(self) -> None:
        summary = CanaryProbeSummary(
            phase="phase_271",
            description="Phase 271 Canary Public Network Telemetry Probe & Handshake Summary",
            timestamp_utc="2026-09-18T00:00:00+00:00",
            duration_seconds=1.5,
            execution_mode="offline_replay",
            staged_manifest_hash="1b5ea30d08031d06b8f20b19469ef56d42e2b79d2e5d6c79b094dda83bf4f013",
            manifest_version=2,
            registry_version=2,
            candidates={
                "BTCUSDT": {
                    "candidate_id": "cand-btcusdt-dcb-002",
                    "family": "donchian_channel_breakout",
                    "timeframe": "15m",
                    "staging_promotion_state": "canary_staged",
                    "allocated_margin_usdt": "20.0000",
                    "qualification_hash": "e4ac" * 16,
                    "artifact_hash": "91f4" * 16,
                }
            },
            connection_profile={
                "endpoint": "wss://fstream.binance.com/stream",
                "handshake_time_ms": 84.5,
                "status": "CLOSED",
                "reconnect_count": 0,
                "events_count": 3,
            },
            heartbeat_profile={
                "count": 2,
                "min_rtt_ms": 45.0,
                "mean_rtt_ms": 47.5,
                "p50_rtt_ms": 47.5,
                "p95_rtt_ms": 50.0,
                "p99_rtt_ms": 50.0,
                "max_rtt_ms": 50.0,
            },
            clock_sync_profile={
                "samples_count": 1,
                "mean_drift_ms": 14.2,
                "max_drift_ms": 14.2,
                "threshold_ms": 1000.0,
                "within_threshold": True,
            },
            stream_telemetry={
                "total_messages_received": 100,
                "messages_per_second": 50.0,
                "symbol_stats": {
                    "BTCUSDT": {
                        "messages": 100,
                        "book_ticker_count": 95,
                        "kline_count": 5,
                        "mean_latency_ms": 45.0,
                        "p50_latency_ms": 45.0,
                        "p95_latency_ms": 48.0,
                        "p99_latency_ms": 50.0,
                        "mean_interval_ms": 25.0,
                        "mean_jitter_ms": 2.5,
                    }
                },
            },
            portfolio_accounting={
                "starting_equity_usdt": "100.00",
                "final_cash_usdt": "100.00",
                "realized_pnl_usdt": "0.00",
                "unrealized_pnl_usdt": "0.00",
                "final_equity_usdt": "100.00",
                "drift_usdt": "0",
                "zero_balance_drift": True,
                "active_margin_commitment_usdt": "0.00",
                "max_observed_margin_utilization": "0",
                "min_observed_reserve_buffer": "1",
                "margin_guardrails_compliant": True,
                "single_position_invariant": True,
            },
            safety_invariants={
                "execution_authority": False,
                "exchange_access": False,
                "authenticated_endpoints_accessed": False,
                "orders": 0,
                "api_keys_loaded": 0,
                "zero_secret_leakage": True,
            },
            compliance={
                "zero_balance_drift": True,
                "margin_guardrails_compliant": True,
                "clock_sync_compliant": True,
                "read_only_safety_compliant": True,
                "all_criteria_passed": True,
            },
            artifact_hashes={
                "canary-network-telemetry.sqlite3": "abc123hash",
            },
        )
        table = format_summary_table(summary)
        assert "PHASE 271: CANARY PUBLIC NETWORK TELEMETRY PROBE & HANDSHAKE PROFILER" in table
        assert "Execution Mode:              OFFLINE_REPLAY" in table
        assert "Double-Entry Drift:        0 USDT (zero_drift=True)" in table


class TestPhase271AdditionalEdgeCases:
    """Validate boundary values, error branches, and edge conditions."""

    def test_compute_percentile_boundaries(self) -> None:
        assert compute_percentile([], 50.0) == 0.0
        assert compute_percentile([42.0], 0.0) == 42.0
        assert compute_percentile([42.0], 50.0) == 42.0
        assert compute_percentile([42.0], 100.0) == 42.0
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert compute_percentile(vals, 0.0) == 10.0
        assert compute_percentile(vals, 50.0) == 30.0
        assert compute_percentile(vals, 100.0) == 50.0

    @pytest.mark.anyio
    async def test_server_time_sync_invalid_payload(self) -> None:
        class MockBadTimeHandler(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json={"error": "no serverTime"}, request=request)

        client = httpx.AsyncClient(transport=MockBadTimeHandler())
        with pytest.raises(DomainViolation, match="Invalid response from Binance"):
            await evaluate_server_time_sync(client=client)
        await client.aclose()

    def test_build_combined_stream_url(self) -> None:
        cfg = CanaryProbeConfig(
            symbols=("BTCUSDT", "ETHUSDT"),
            streams=("bookTicker",),
            ws_url="wss://fstream.binance.com",
        )
        runner = CanaryNetworkProbeRunner(cfg)
        url = runner._build_combined_stream_url()
        assert (
            url == "wss://fstream.binance.com/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker"
        )

    def test_probe_network_fallback_on_network_error(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "fallback_test"
        cfg = CanaryProbeConfig(
            output_dir=out_dir,
            ws_url="wss://nonexistent.invalid.host.com",
            rest_url="https://nonexistent.invalid.host.com",
            probe_seconds=1.0,
            max_heartbeats=2,
            offline_replay=False,  # live attempt should catch network error and fallback gracefully
        )
        runner = CanaryNetworkProbeRunner(cfg)
        summary, db_path, rep_path, net_path, paper_path = runner.run()
        assert summary.execution_mode == "network_fallback"
        assert summary.portfolio_accounting["zero_balance_drift"] is True
        assert db_path.is_file()
        assert rep_path.is_file()

    def test_simulate_network_timeout_triggers_fallback(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "timeout_fallback_test"
        cfg = CanaryProbeConfig(
            output_dir=out_dir,
            probe_seconds=1.0,
            max_heartbeats=2,
            offline_replay=False,
            simulate_network_timeout=True,
        )
        runner = CanaryNetworkProbeRunner(cfg)
        summary, db_path, rep_path, net_path, paper_path = runner.run()
        assert summary.execution_mode == "network_fallback"
        assert summary.portfolio_accounting["zero_balance_drift"] is True
        assert db_path.is_file()

    def test_simulate_clock_drift_live_failure(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "live_drift_fail"
        cfg = CanaryProbeConfig(
            output_dir=out_dir,
            probe_seconds=1.0,
            max_heartbeats=2,
            offline_replay=False,
            simulate_clock_drift=True,
        )
        runner = CanaryNetworkProbeRunner(cfg)
        with pytest.raises(ClockSyncDriftError, match="exceeds safety threshold"):
            runner.run()

    def test_fail_closed_rejects_api_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BINANCE_API_SECRET", "prohibited_secret_key")
        with pytest.raises(SafetyInvariantViolation, match="api_keys_loaded"):
            verify_strict_fail_closed_invariants()

    def test_fail_closed_rejects_execution_authority(self) -> None:
        with pytest.raises(SafetyInvariantViolation, match="execution_authority"):
            verify_strict_fail_closed_invariants(execution_authority=True)

    def test_fail_closed_rejects_exchange_access(self) -> None:
        with pytest.raises(SafetyInvariantViolation, match="exchange_access"):
            verify_strict_fail_closed_invariants(exchange_access=True)

    def test_fail_closed_rejects_authenticated_endpoints(self) -> None:
        with pytest.raises(SafetyInvariantViolation, match="authenticated_endpoints_accessed"):
            verify_strict_fail_closed_invariants(authenticated_endpoints_accessed=True)

    def test_batch_persistence_in_sqlite(
        self, isolated_store: SqliteCanaryNetworkTelemetryStore
    ) -> None:
        marks = [
            (
                "2026-09-18T00:00:00Z",
                "btcusdt@bookTicker",
                "BTCUSDT",
                "bookTicker",
                1000 + i,
                1050.0 + i,
                50.0,
            )
            for i in range(25)
        ]
        count = isolated_store.record_latency_marks_batch(marks)
        assert count == 25
        tel = isolated_store.get_stream_telemetry(elapsed_seconds=1.0, symbols=("BTCUSDT",))
        assert tel["total_messages_received"] == 25
        assert tel["symbol_stats"]["BTCUSDT"]["messages"] == 25
        assert tel["symbol_stats"]["BTCUSDT"]["mean_latency_ms"] == 50.0

        jitters = [
            (
                "2026-09-18T00:00:00Z",
                "BTCUSDT",
                "btcusdt@bookTicker",
                1000.0 + i * 10,
                1010.0 + i * 10,
                10.0,
                1.0,
            )
            for i in range(10)
        ]
        j_count = isolated_store.record_jitter_batch(jitters)
        assert j_count == 10

    def test_idempotent_sqlite_close(self, tmp_path: Path) -> None:
        db_p = tmp_path / "idempotent_close.sqlite3"
        st = SqliteCanaryNetworkTelemetryStore(db_p)
        st.record_connection_event("test_ev", "endpoint", 5.0, True)
        st.close()
        # Second close must not raise
        st.close()
        assert st._closed is True
