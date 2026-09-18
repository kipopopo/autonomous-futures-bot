"""Unit tests for Phase 272: Continuous Canary Heartbeat Daemon & Real-Time Alert Dispatcher."""

from __future__ import annotations

import json
import sys
import unittest.mock as mock
from decimal import Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.canary_probe import (  # noqa: E402
    DEFAULT_CANARY_SYMBOLS,
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    ACCOUNTING_FINAL_CASH,
    ACCOUNTING_REALIZED_PNL,
    ACCOUNTING_STARTING_EQUITY,
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DOUBLE_ENTRY_MAX_DRIFT,
    AlertDispatcher,
    AlertEvent,
    AlertRingBuffer,
    AlertSeverity,
    CanaryHeartbeatDaemonConfig,
    CanaryHeartbeatDaemonRunner,
    CircuitBreakerManager,
    CircuitBreakerState,
    CircuitBreakerTransition,
    ConsoleAlertSink,
    JsonlAlertSink,
    SqliteCanaryHeartbeatTelemetryStore,
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
from scripts.run_phase_272_heartbeat_daemon import (  # noqa: E402
    build_arg_parser,
    format_summary_table,
)
from scripts.run_phase_272_heartbeat_daemon import (  # noqa: E402
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
def isolated_store(tmp_path: Path) -> SqliteCanaryHeartbeatTelemetryStore:
    """Provide clean isolated SQLite store in a temporary directory."""
    db_path = tmp_path / "test-canary-heartbeat-telemetry.sqlite3"
    return SqliteCanaryHeartbeatTelemetryStore(db_path)


class TestPhase272ManifestAndCandidateValidation:
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


class TestPhase272SqliteTelemetryStore:
    """Validate isolated SQLite store schemas, pragmas, operations, and aggregations."""

    def test_pragmas_and_schema_initialization(
        self, isolated_store: SqliteCanaryHeartbeatTelemetryStore
    ) -> None:
        cur = isolated_store._conn.cursor()
        cur.execute("PRAGMA journal_mode")
        row = cur.fetchone()
        assert row[0].upper() == "WAL"

        cur.execute("PRAGMA synchronous")
        row = cur.fetchone()
        assert row[0] == 1  # NORMAL

        cur.execute("PRAGMA foreign_keys")
        row = cur.fetchone()
        assert row[0] == 1

        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        expected_tables = {
            "connection_events",
            "heartbeat_samples",
            "clock_sync_samples",
            "latency_marks",
            "jitter_samples",
            "alert_events",
            "circuit_breaker_events",
            "accounting_ledger",
        }
        assert expected_tables.issubset(tables)

    def test_record_and_query_connection_events(
        self, isolated_store: SqliteCanaryHeartbeatTelemetryStore
    ) -> None:
        row_id = isolated_store.record_connection_event(
            event_type="ws_handshake_success",
            endpoint="wss://fstream.binance.com",
            duration_ms=45.2,
            success=True,
            details="Handshake OK",
        )
        assert row_id > 0
        events = isolated_store.get_connection_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "ws_handshake_success"
        assert events[0]["duration_ms"] == 45.2
        assert events[0]["success"] is True

    def test_record_and_query_heartbeat_samples(
        self, isolated_store: SqliteCanaryHeartbeatTelemetryStore
    ) -> None:
        rtts = [20.0, 30.0, 50.0, 100.0, 400.0]
        for seq, rtt in enumerate(rtts, 1):
            isolated_store.record_heartbeat(
                sequence_num=seq,
                ping_sent_ms=1000.0 * seq,
                pong_recv_ms=1000.0 * seq + rtt,
                rtt_ms=rtt,
            )
        stats = isolated_store.get_heartbeat_stats()
        assert stats["count"] == 5
        assert stats["min_rtt_ms"] == 20.0
        assert stats["max_rtt_ms"] == 400.0
        assert stats["mean_rtt_ms"] == 120.0
        assert stats["p50_rtt_ms"] == 50.0

    def test_record_and_query_clock_sync_samples(
        self, isolated_store: SqliteCanaryHeartbeatTelemetryStore
    ) -> None:
        isolated_store.record_clock_sync(
            client_time_ms=1000.0,
            server_time_ms=1015,
            drift_ms=15.0,
            rtt_ms=40.0,
            within_threshold=True,
        )
        stats = isolated_store.get_clock_sync_stats()
        assert stats["samples_count"] == 1
        assert stats["mean_drift_ms"] == 15.0
        assert stats["within_threshold"] is True

    def test_record_and_query_latency_and_jitter(
        self, isolated_store: SqliteCanaryHeartbeatTelemetryStore
    ) -> None:
        marks = [
            (
                "2026-09-18T10:00:00Z",
                "btcusdt@bookTicker",
                "BTCUSDT",
                "bookTicker",
                1000,
                1025.0,
                25.0,
            ),
            (
                "2026-09-18T10:00:01Z",
                "btcusdt@bookTicker",
                "BTCUSDT",
                "bookTicker",
                2000,
                2035.0,
                35.0,
            ),
        ]
        inserted = isolated_store.record_latency_marks_batch(marks)
        assert inserted == 2

        jitters = [
            ("2026-09-18T10:00:01Z", "BTCUSDT", "btcusdt@bookTicker", 1025.0, 2035.0, 1010.0, 10.0)
        ]
        isolated_store.record_jitter_samples_batch(jitters)

        telemetry = isolated_store.get_stream_telemetry(elapsed_seconds=2.0)
        assert telemetry["total_messages_received"] == 2
        assert "BTCUSDT" in telemetry["symbol_stats"]
        assert telemetry["symbol_stats"]["BTCUSDT"]["messages"] == 2

    def test_record_and_query_alert_events(
        self, isolated_store: SqliteCanaryHeartbeatTelemetryStore
    ) -> None:
        ev1 = AlertEvent(
            alert_id="alt-00001",
            timestamp_utc="2026-09-18T10:00:00Z",
            severity=AlertSeverity.INFO,
            component="stream_supervisor",
            event_type="connection_established",
            message="Connection OK",
            details={"foo": "bar"},
        )
        ev2 = AlertEvent(
            alert_id="alt-00002",
            timestamp_utc="2026-09-18T10:00:01Z",
            severity=AlertSeverity.WARNING,
            component="heartbeat_daemon",
            event_type="latency_spike",
            message="Latency spike",
            details={"rtt_ms": 350.0},
        )
        isolated_store.record_alert_event(ev1)
        isolated_store.record_alert_event(ev2)

        counts = isolated_store.get_alert_counts()
        assert counts["INFO"] == 1
        assert counts["WARNING"] == 1
        assert counts["CRITICAL"] == 0
        assert counts["EMERGENCY"] == 0

        recent = isolated_store.get_recent_alerts(limit=10)
        assert len(recent) == 2
        assert recent[0]["alert_id"] == "alt-00001"
        assert recent[1]["alert_id"] == "alt-00002"

    def test_record_and_query_circuit_breaker_events(
        self, isolated_store: SqliteCanaryHeartbeatTelemetryStore
    ) -> None:
        trans = CircuitBreakerTransition(
            timestamp_utc="2026-09-18T10:00:00Z",
            previous_state=CircuitBreakerState.NORMAL,
            new_state=CircuitBreakerState.TIER_1_SOFT_FREEZE,
            reason="Feed timeout",
            trigger_severity=AlertSeverity.CRITICAL,
        )
        row_id = isolated_store.record_circuit_breaker_transition(trans)
        assert row_id > 0
        events = isolated_store.get_circuit_breaker_events()
        assert len(events) == 1
        assert events[0]["new_state"] == "TIER_1_SOFT_FREEZE"
        assert events[0]["reason"] == "Feed timeout"

    def test_closed_store_guards(self, isolated_store: SqliteCanaryHeartbeatTelemetryStore) -> None:
        isolated_store.close()
        with pytest.raises(DomainViolation, match="Cannot operate on closed"):
            isolated_store.record_connection_event("test", "endpoint", 1.0, True)


class TestPhase272AlertRingBufferAndSinks:
    """Validate in-memory ring buffer capacity, JSONL persistence, and console alert sink."""

    def test_ring_buffer_capacity_and_fifo_eviction(self) -> None:
        buf = AlertRingBuffer(capacity=3)
        assert len(buf) == 0

        for i in range(5):
            alert = AlertEvent(
                alert_id=f"alt-{i:05d}",
                timestamp_utc="2026-09-18T10:00:00Z",
                severity=AlertSeverity.INFO,
                component="test",
                event_type="test_event",
                message=f"msg-{i}",
            )
            buf.append(alert)

        assert len(buf) == 3
        recent = buf.get_recent(limit=10)
        assert [a.message for a in recent] == ["msg-2", "msg-3", "msg-4"]

    def test_ring_buffer_severity_filtering_and_counts(self) -> None:
        buf = AlertRingBuffer(capacity=10)
        buf.append(
            AlertEvent(
                alert_id="alt-1",
                timestamp_utc="2026-09-18T10:00:00Z",
                severity=AlertSeverity.INFO,
                component="c",
                event_type="e",
                message="m1",
            )
        )
        buf.append(
            AlertEvent(
                alert_id="alt-2",
                timestamp_utc="2026-09-18T10:00:01Z",
                severity=AlertSeverity.WARNING,
                component="c",
                event_type="e",
                message="m2",
            )
        )
        buf.append(
            AlertEvent(
                alert_id="alt-3",
                timestamp_utc="2026-09-18T10:00:02Z",
                severity=AlertSeverity.CRITICAL,
                component="c",
                event_type="e",
                message="m3",
            )
        )
        buf.append(
            AlertEvent(
                alert_id="alt-4",
                timestamp_utc="2026-09-18T10:00:03Z",
                severity=AlertSeverity.EMERGENCY,
                component="c",
                event_type="e",
                message="m4",
            )
        )

        counts = buf.get_counts()
        assert counts["INFO"] == 1
        assert counts["WARNING"] == 1
        assert counts["CRITICAL"] == 1
        assert counts["EMERGENCY"] == 1

        crit_alerts = buf.get_by_severity(AlertSeverity.CRITICAL)
        assert len(crit_alerts) == 1
        assert crit_alerts[0].alert_id == "alt-3"

        buf.clear()
        assert len(buf) == 0

    def test_ring_buffer_invalid_capacity(self) -> None:
        with pytest.raises(DomainViolation, match="must be positive"):
            AlertRingBuffer(capacity=0)

    def test_jsonl_alert_sink_writes_and_flushes(self, tmp_path: Path) -> None:
        sink_path = tmp_path / "alerts.jsonl"
        sink = JsonlAlertSink(sink_path)

        ev = AlertEvent(
            alert_id="alt-00001",
            timestamp_utc="2026-09-18T10:00:00Z",
            severity=AlertSeverity.WARNING,
            component="stream",
            event_type="latency_spike",
            message="High latency",
            details={"rtt_ms": 320.0},
        )
        sink.append(ev)
        sink.flush()
        sink.close()

        with open(sink_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["alert_id"] == "alt-00001"
        assert parsed["severity"] == "WARNING"
        assert parsed["details"]["rtt_ms"] == 320.0

        with pytest.raises(DomainViolation, match="Cannot append alert to closed"):
            sink.append(ev)

    def test_console_alert_sink_emits(self) -> None:
        mock_logger = mock.MagicMock()
        sink = ConsoleAlertSink(mock_logger)

        for sev in AlertSeverity:
            ev = AlertEvent(
                alert_id=f"alt-{sev.value}",
                timestamp_utc="2026-09-18T10:00:00Z",
                severity=sev,
                component="comp",
                event_type="ev",
                message=f"test {sev.value}",
            )
            sink.emit(ev)

        assert mock_logger.info.called
        assert mock_logger.warning.called
        assert mock_logger.error.called
        assert mock_logger.critical.called


class TestPhase272CircuitBreakerManager:
    """Validate circuit breaker state machine, triggers, and fail-closed transitions."""

    def test_initial_state_is_normal(self) -> None:
        cb = CircuitBreakerManager()
        assert cb.current_state == CircuitBreakerState.NORMAL
        assert not cb.is_soft_frozen()
        assert not cb.is_hard_aborted()
        assert len(cb.transitions) == 0

    def test_critical_alert_triggers_soft_freeze(self) -> None:
        cb = CircuitBreakerManager()
        crit_alert = AlertEvent(
            alert_id="alt-001",
            timestamp_utc="2026-09-18T10:00:00Z",
            severity=AlertSeverity.CRITICAL,
            component="feed",
            event_type="feed_timeout",
            message="No data for >= 10s",
        )
        transition = cb.evaluate_alert(crit_alert)
        assert transition is not None
        assert cb.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert cb.is_soft_frozen()
        assert not cb.is_hard_aborted()
        assert transition.previous_state == CircuitBreakerState.NORMAL
        assert transition.new_state == CircuitBreakerState.TIER_1_SOFT_FREEZE

        # Repeated critical does not duplicate transition
        t2 = cb.evaluate_alert(crit_alert)
        assert t2 is None

    def test_emergency_alert_triggers_hard_abort(self) -> None:
        cb = CircuitBreakerManager()
        emrg_alert = AlertEvent(
            alert_id="alt-002",
            timestamp_utc="2026-09-18T10:00:00Z",
            severity=AlertSeverity.EMERGENCY,
            component="accounting",
            event_type="accounting_drift",
            message="Drift detected",
        )
        transition = cb.evaluate_alert(emrg_alert)
        assert transition is not None
        assert cb.current_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert cb.is_soft_frozen()
        assert cb.is_hard_aborted()
        assert transition.previous_state == CircuitBreakerState.NORMAL
        assert transition.new_state == CircuitBreakerState.TIER_2_HARD_ABORT


class TestPhase272AlertDispatcher:
    """Validate centralized AlertDispatcher coordination with ring buffer, sinks, and store."""

    def test_dispatcher_fans_out_to_all_sinks(
        self, tmp_path: Path, isolated_store: SqliteCanaryHeartbeatTelemetryStore
    ) -> None:
        jsonl_path = tmp_path / "alerts.jsonl"
        jsonl_sink = JsonlAlertSink(jsonl_path)
        ring_buf = AlertRingBuffer(capacity=10)
        cb = CircuitBreakerManager()
        dispatcher = AlertDispatcher(
            ring_buffer=ring_buf,
            jsonl_sink=jsonl_sink,
            console_sink=ConsoleAlertSink(),
            store=isolated_store,
            circuit_breaker=cb,
        )

        alert = dispatcher.dispatch(
            severity=AlertSeverity.INFO,
            component="daemon",
            event_type="tick",
            message="Normal heartbeat",
            details={"seq": 1},
        )
        assert alert.alert_id == "alt-00001"
        assert len(ring_buf) == 1
        assert isolated_store.get_alert_counts()["INFO"] == 1

        # Dispatch critical to check circuit breaker integration
        crit_alert = dispatcher.dispatch(
            severity=AlertSeverity.CRITICAL,
            component="clock",
            event_type="clock_drift_breach",
            message="Clock drift 1200ms",
        )
        assert crit_alert.alert_id == "alt-00002"
        assert cb.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        cb_events = isolated_store.get_circuit_breaker_events()
        assert len(cb_events) == 1
        assert cb_events[0]["new_state"] == "TIER_1_SOFT_FREEZE"

        jsonl_sink.close()


class TestPhase272AnomalySimulationFlags:
    """Validate CLI anomaly injection flags (--simulate-*) and triggered alerts."""

    def test_simulate_latency_spike(self, tmp_path: Path) -> None:
        cfg = CanaryHeartbeatDaemonConfig(
            output_dir=tmp_path,
            offline_replay=True,
            simulate_latency_spike=True,
            max_heartbeats=3,
            daemon_seconds=3.0,
        )
        runner = CanaryHeartbeatDaemonRunner(cfg)
        summary, db_path, jsonl_path, _, _, _ = runner.run()

        assert summary.alerts_summary["counts_by_severity"]["WARNING"] >= 1
        assert summary.circuit_breaker_state == "NORMAL"
        assert summary.compliance["all_criteria_passed"] is True

        with open(jsonl_path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        warn_lines = [entry for entry in lines if entry["severity"] == "WARNING"]
        assert any("latency_spike" in entry["event_type"] for entry in warn_lines)

    def test_simulate_feed_drop(self, tmp_path: Path) -> None:
        cfg = CanaryHeartbeatDaemonConfig(
            output_dir=tmp_path,
            offline_replay=True,
            simulate_feed_drop=True,
            max_heartbeats=3,
            daemon_seconds=3.0,
        )
        runner = CanaryHeartbeatDaemonRunner(cfg)
        summary, _, jsonl_path, _, _, _ = runner.run()

        assert summary.alerts_summary["counts_by_severity"]["CRITICAL"] >= 1
        assert summary.circuit_breaker_state == "TIER_1_SOFT_FREEZE"

        with open(jsonl_path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        crit_lines = [entry for entry in lines if entry["severity"] == "CRITICAL"]
        assert any("feed_timeout" in entry["event_type"] for entry in crit_lines)

    def test_simulate_clock_drift_breach(self, tmp_path: Path) -> None:
        cfg = CanaryHeartbeatDaemonConfig(
            output_dir=tmp_path,
            offline_replay=True,
            simulate_clock_drift_breach=True,
            max_heartbeats=3,
            daemon_seconds=3.0,
        )
        runner = CanaryHeartbeatDaemonRunner(cfg)
        summary, _, jsonl_path, _, _, _ = runner.run()

        assert summary.alerts_summary["counts_by_severity"]["CRITICAL"] >= 1
        assert summary.circuit_breaker_state == "TIER_1_SOFT_FREEZE"
        assert summary.compliance["clock_sync_compliant"] is False
        assert summary.compliance["all_criteria_passed"] is False

    def test_simulate_adverse_accounting_drift(self, tmp_path: Path) -> None:
        cfg = CanaryHeartbeatDaemonConfig(
            output_dir=tmp_path,
            offline_replay=True,
            simulate_adverse_drift=True,
            max_heartbeats=3,
            daemon_seconds=3.0,
        )
        runner = CanaryHeartbeatDaemonRunner(cfg)
        summary, _, jsonl_path, _, _, _ = runner.run()

        assert summary.alerts_summary["counts_by_severity"]["EMERGENCY"] >= 1
        assert summary.circuit_breaker_state == "TIER_2_HARD_ABORT"
        assert summary.compliance["zero_balance_drift"] is False
        assert summary.compliance["circuit_breaker_compliant"] is False
        assert summary.compliance["all_criteria_passed"] is False


class TestPhase272DoubleEntryAccountingAndGuardrails:
    """Validate exact zero-drift double-entry balance reconciliation and margin guardrails."""

    def test_zero_drift_nominal_reconciliation(self, tmp_path: Path) -> None:
        cfg = CanaryHeartbeatDaemonConfig(
            output_dir=tmp_path,
            offline_replay=True,
            max_heartbeats=2,
            daemon_seconds=2.0,
        )
        runner = CanaryHeartbeatDaemonRunner(cfg)
        summary, _, _, _, _, _ = runner.run()

        acct = summary.portfolio_accounting
        assert Decimal(acct["starting_equity_usdt"]) == ACCOUNTING_STARTING_EQUITY
        assert Decimal(acct["final_cash_usdt"]) == ACCOUNTING_FINAL_CASH
        assert Decimal(acct["realized_pnl_usdt"]) == ACCOUNTING_REALIZED_PNL
        assert acct["zero_balance_drift"] is True
        assert Decimal(acct["drift_usdt"]) < DOUBLE_ENTRY_MAX_DRIFT
        assert acct["max_observed_margin_utilization"] == "0"
        assert acct["min_observed_reserve_buffer"] == "1"
        assert acct["margin_guardrails_compliant"] is True
        assert acct["single_position_invariant"] is True


class TestPhase272StrictFailClosedSafetyInvariants:
    """Validate non-negotiable read-only fail-closed safety containment."""

    def test_orders_submitted_violation(self) -> None:
        with pytest.raises(RuntimeError, match="orders submitted"):
            verify_strict_fail_closed_invariants(orders_submitted=1)

    def test_execution_authority_violation(self) -> None:
        with pytest.raises(RuntimeError, match="execution_authority"):
            verify_strict_fail_closed_invariants(execution_authority=True)

    def test_exchange_access_violation(self) -> None:
        with pytest.raises(RuntimeError, match="exchange_access"):
            verify_strict_fail_closed_invariants(exchange_access=True)

    def test_authenticated_endpoints_violation(self) -> None:
        with pytest.raises(RuntimeError, match="authenticated_endpoints_accessed"):
            verify_strict_fail_closed_invariants(authenticated_endpoints_accessed=True)

    def test_binance_api_keys_loaded_violation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BINANCE_API_KEY", "test_mock_key_value")
        with pytest.raises(RuntimeError, match="api_keys_loaded"):
            verify_strict_fail_closed_invariants()


class TestPhase272ArtifactsAndDigests:
    """Validate artifact persistence, deterministic SHA-256 digests, and secret scanning."""

    def test_artifacts_generated_with_valid_hashes(self, tmp_path: Path) -> None:
        cfg = CanaryHeartbeatDaemonConfig(
            output_dir=tmp_path,
            offline_replay=True,
            max_heartbeats=5,
            daemon_seconds=5.0,
        )
        runner = CanaryHeartbeatDaemonRunner(cfg)
        (
            summary,
            db_path,
            alerts_path,
            report_path,
            hb_sum_path,
            paper_sum_path,
        ) = runner.run()

        # All 5 files exist
        assert db_path.is_file()
        assert alerts_path.is_file()
        assert report_path.is_file()
        assert hb_sum_path.is_file()
        assert paper_sum_path.is_file()

        # Check hashes
        db_hash = compute_file_sha256(db_path)
        jsonl_hash = compute_file_sha256(alerts_path)
        assert summary.artifact_hashes["canary-heartbeat-telemetry.sqlite3"] == db_hash
        assert summary.artifact_hashes["canary-alerts.jsonl"] == jsonl_hash

        # Assert zero secret scanning passes on all generated text/json/jsonl
        assert_zero_secrets(report_path.read_bytes(), "canary-daemon-report.json")
        assert_zero_secrets(hb_sum_path.read_bytes(), "heartbeat-summary.json")
        assert_zero_secrets(paper_sum_path.read_bytes(), "paper-summary.json")
        assert_zero_secrets(alerts_path.read_bytes(), "canary-alerts.jsonl")


class TestPhase272CLIRunnerAndFormatting:
    """Validate CLI arguments parsing, execution, and output formatting."""

    def test_cli_parser_defaults(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.daemon_seconds == 30.0
        assert args.max_heartbeats == 10
        assert args.heartbeat_interval == 3.0
        assert args.offline_replay is False
        assert args.simulate_latency_spike is False
        assert args.simulate_feed_drop is False
        assert args.simulate_clock_drift_breach is False
        assert args.simulate_adverse_drift is False

    def test_cli_format_summary_table(self, tmp_path: Path) -> None:
        cfg = CanaryHeartbeatDaemonConfig(
            output_dir=tmp_path,
            offline_replay=True,
            max_heartbeats=2,
            daemon_seconds=2.0,
        )
        runner = CanaryHeartbeatDaemonRunner(cfg)
        summary, _, _, _, _, _ = runner.run()
        table = format_summary_table(summary)
        assert "PHASE 272" in table
        assert "Circuit Breaker State:" in table
        assert "Multi-Tiered Alerting Dispatcher Summary:" in table
        assert "Exact Double-Entry Accounting" in table

    def test_cli_main_offline_success(self, tmp_path: Path) -> None:
        code = cli_main(
            [
                "--output-dir",
                str(tmp_path),
                "--offline-replay",
                "--max-heartbeats",
                "2",
                "--daemon-seconds",
                "2.0",
                "--json",
            ]
        )
        assert code == 0

    def test_cli_main_failure_on_clock_breach(self, tmp_path: Path) -> None:
        code = cli_main(
            [
                "--output-dir",
                str(tmp_path),
                "--offline-replay",
                "--simulate-clock-drift-breach",
                "--max-heartbeats",
                "2",
                "--daemon-seconds",
                "2.0",
            ]
        )
        assert code == 1


class TestPhase272ConfigValidation:
    """Validate configuration boundary rules and error handling."""

    def test_invalid_daemon_seconds(self) -> None:
        with pytest.raises(DomainViolation, match="daemon_seconds must be positive"):
            CanaryHeartbeatDaemonConfig(daemon_seconds=0.0)

    def test_negative_max_heartbeats(self) -> None:
        with pytest.raises(DomainViolation, match="max_heartbeats cannot be negative"):
            CanaryHeartbeatDaemonConfig(max_heartbeats=-1)

    def test_invalid_heartbeat_interval(self) -> None:
        with pytest.raises(DomainViolation, match="heartbeat_interval_seconds must be positive"):
            CanaryHeartbeatDaemonConfig(heartbeat_interval_seconds=0.0)
