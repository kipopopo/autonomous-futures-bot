"""Unit tests for Phase 273: Canary Circuit Breaker Drill & Recovery State Machine."""

from __future__ import annotations

import concurrent.futures
import io
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.circuit_breaker_drill import (  # noqa: E402
    CanaryCircuitBreakerDrillConfig,
    CanaryCircuitBreakerDrillRunner,
    CanaryCircuitBreakerRecoveryStateMachine,
    CanaryIncidentRecord,
    CircuitBreakerState,
    CircuitBreakerTransition,
    IncidentTrackId,
    JsonlIncidentSink,
    SqliteCanaryIncidentTelemetryStore,
    TelemetryTick,
    verify_phase_273_hash_chain,
)
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    ACCOUNTING_FINAL_CASH,
    ACCOUNTING_REALIZED_PNL,
    ACCOUNTING_STARTING_EQUITY,
    CLOCK_DRIFT_CRITICAL_THRESHOLD_MS,
    DOUBLE_ENTRY_MAX_DRIFT,
    AlertSeverity,
)
from autonomous_futures.paper.staging import (  # noqa: E402
    assert_zero_secrets,
    compute_file_sha256,
)
from scripts.run_phase_273_circuit_breaker_drill import (  # noqa: E402
    build_arg_parser,
    execute_phase_273_runner,
    format_summary_table,
)
from scripts.run_phase_273_circuit_breaker_drill import (  # noqa: E402
    main as cli_main,
)


@pytest.fixture
def sm() -> CanaryCircuitBreakerRecoveryStateMachine:
    """Provide clean recovery state machine with hysteresis K=5."""
    return CanaryCircuitBreakerRecoveryStateMachine(recovery_hysteresis_ticks=5)


@pytest.fixture
def isolated_store(tmp_path: Path) -> SqliteCanaryIncidentTelemetryStore:
    """Provide clean isolated SQLite store in a temporary directory."""
    db_path = tmp_path / "test-canary-incident-telemetry.sqlite3"
    return SqliteCanaryIncidentTelemetryStore(db_path)


class TestPhase273RecoveryStateMachine:
    """Validate 3-state autonomous recovery state machine and hysteresis de-escalation."""

    def test_initial_state_is_normal(self, sm: CanaryCircuitBreakerRecoveryStateMachine) -> None:
        assert sm.current_state == CircuitBreakerState.NORMAL
        assert sm.is_normal()
        assert not sm.is_soft_frozen()
        assert not sm.is_hard_aborted()
        assert sm.consecutive_healthy_ticks == 0
        assert len(sm.transitions) == 0

    def test_nominal_healthy_ticks_stay_normal(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        tr1 = sm.process_tick(rtt_ms=25.0, drift_ms=10.0, jitter_ms=3.0)
        tr2 = sm.process_tick(rtt_ms=35.0, drift_ms=-12.0, jitter_ms=5.0)
        assert tr1 is None
        assert tr2 is None
        assert sm.current_state == CircuitBreakerState.NORMAL

    def test_transient_latency_spike_triggers_soft_freeze(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        tr = sm.process_tick(rtt_ms=350.0, drift_ms=10.0, jitter_ms=5.0)
        assert tr is not None
        assert tr.previous_state == CircuitBreakerState.NORMAL
        assert tr.new_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert tr.trigger_severity == AlertSeverity.CRITICAL
        assert sm.is_soft_frozen()
        assert not sm.is_hard_aborted()
        assert len(sm.transitions) == 1

    def test_clock_drift_breach_triggers_soft_freeze(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        tr = sm.process_tick(
            rtt_ms=50.0,
            drift_ms=CLOCK_DRIFT_CRITICAL_THRESHOLD_MS + 50.0,
            jitter_ms=5.0,
        )
        assert tr is not None
        assert tr.new_state == CircuitBreakerState.TIER_1_SOFT_FREEZE

    def test_hysteresis_autonomous_recovery_after_k_healthy_ticks(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        # Trip to soft freeze
        sm.process_tick(rtt_ms=400.0, drift_ms=10.0)
        assert sm.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE

        # Ingest 4 healthy ticks (sub-threshold, K=5)
        for i in range(1, 5):
            rec_tr = sm.process_tick(rtt_ms=25.0, drift_ms=10.0, jitter_ms=2.0)
            assert rec_tr is None
            assert sm.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
            assert sm.consecutive_healthy_ticks == i

        # 5th healthy tick triggers automated self-healing recovery
        final_tr = sm.process_tick(rtt_ms=25.0, drift_ms=10.0, jitter_ms=2.0)
        assert final_tr is not None
        assert final_tr.previous_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert final_tr.new_state == CircuitBreakerState.NORMAL
        assert final_tr.trigger_severity == AlertSeverity.INFO
        assert final_tr.consecutive_healthy_ticks == 5
        assert sm.current_state == CircuitBreakerState.NORMAL
        assert sm.consecutive_healthy_ticks == 0

    def test_unhealthy_tick_during_soft_freeze_resets_counter(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        sm.process_tick(rtt_ms=400.0, drift_ms=10.0)
        # 3 healthy ticks
        for _ in range(3):
            sm.process_tick(rtt_ms=25.0, drift_ms=10.0)
        assert sm.consecutive_healthy_ticks == 3

        # Unhealthy tick (latency spike) resets counter to 0
        sm.process_tick(rtt_ms=350.0, drift_ms=10.0)
        assert sm.consecutive_healthy_ticks == 0
        assert sm.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE

        # Needs full 5 healthy ticks again to recover
        for _ in range(4):
            sm.process_tick(rtt_ms=25.0, drift_ms=10.0)
        assert sm.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE

        rec_tr = sm.process_tick(rtt_ms=25.0, drift_ms=10.0)
        assert rec_tr is not None
        assert sm.current_state == CircuitBreakerState.NORMAL

    def test_escalate_outage_to_hard_abort(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        sm.process_tick(rtt_ms=400.0, drift_ms=10.0)
        esc_tr = sm.escalate_outage(reason="Feed silence > 10s")
        assert esc_tr.previous_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert esc_tr.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert esc_tr.trigger_severity == AlertSeverity.EMERGENCY
        assert sm.is_hard_aborted()

    def test_fail_closed_invariant_under_hard_abort(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        sm.trigger_catastrophic_abort(reason="Emergency halt")
        assert sm.is_hard_aborted()

        # Healthy ticks do not cause auto-recovery under hard abort
        for _ in range(10):
            res = sm.process_tick(rtt_ms=15.0, drift_ms=5.0, jitter_ms=1.0)
            assert res is None
            assert sm.is_hard_aborted()

    def test_catastrophic_drift_instantaneous_hard_abort(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        tr = sm.trigger_catastrophic_abort(reason="Catastrophic clock drift 5000ms")
        assert tr.previous_state == CircuitBreakerState.NORMAL
        assert tr.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert tr.trigger_severity == AlertSeverity.EMERGENCY
        # Verify no intermediate soft freeze
        states = [t.new_state for t in sm.transitions]
        assert CircuitBreakerState.TIER_1_SOFT_FREEZE not in states

    def test_manual_force_freeze(self, sm: CanaryCircuitBreakerRecoveryStateMachine) -> None:
        tr = sm.force_freeze(operator_id="operator-001", rationale="Manual freeze test")
        assert tr.previous_state == CircuitBreakerState.NORMAL
        assert tr.new_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert tr.is_manual_override is True
        assert tr.operator_id == "operator-001"
        assert sm.is_soft_frozen()

    def test_manual_force_abort(self, sm: CanaryCircuitBreakerRecoveryStateMachine) -> None:
        tr = sm.force_abort(operator_id="operator-001", rationale="Manual kill-switch")
        assert tr.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert tr.is_manual_override is True
        assert sm.is_hard_aborted()

    def test_manual_force_recover(self, sm: CanaryCircuitBreakerRecoveryStateMachine) -> None:
        sm.force_freeze(operator_id="operator-001")
        tr = sm.force_recover(operator_id="operator-001", rationale="Manual unfreeze")
        assert tr.previous_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert tr.new_state == CircuitBreakerState.NORMAL
        assert tr.is_manual_override is True
        assert sm.is_normal()

    def test_force_freeze_on_hard_abort_rejected(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        sm.force_abort(operator_id="operator-001")
        with pytest.raises(DomainViolation, match="Cannot force soft-freeze"):
            sm.force_freeze(operator_id="operator-001")

    def test_invalid_hysteresis_ticks_rejected(self) -> None:
        with pytest.raises(DomainViolation, match="must be positive"):
            CanaryCircuitBreakerRecoveryStateMachine(recovery_hysteresis_ticks=0)

    def test_state_machine_reset(self, sm: CanaryCircuitBreakerRecoveryStateMachine) -> None:
        sm.force_abort(operator_id="operator-001")
        assert sm.is_hard_aborted()
        sm.reset()
        assert sm.is_normal()
        assert len(sm.transitions) == 0

    def test_operator_manual_freeze_blocks_autonomous_recovery(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        tr = sm.force_freeze(operator_id="operator-001", rationale="Maintenance hold")
        assert sm.is_soft_frozen()
        assert sm.is_manual_freeze is True
        assert tr.is_manual_override is True

        # Ingest 10 healthy ticks (exceeding K=5)
        for _ in range(10):
            res = sm.process_tick(rtt_ms=25.0, drift_ms=10.0, jitter_ms=2.0)
            assert res is None
            assert sm.is_soft_frozen()
            assert sm.is_manual_freeze is True

        # Only manual recovery de-escalates manual freeze
        rec_tr = sm.force_recover(operator_id="operator-001", rationale="Maintenance finished")
        assert rec_tr.new_state == CircuitBreakerState.NORMAL
        assert sm.is_normal()
        assert sm.is_manual_freeze is False
        assert sm.recovery_duration_ms > 0

    def test_catastrophic_anomaly_escalates_from_manual_freeze(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        sm.force_freeze(operator_id="operator-001")
        assert sm.is_soft_frozen()
        assert sm.is_manual_freeze is True

        # Catastrophic clock drift occurs while manually frozen -> must fail-closed to HARD_ABORT
        cat_tr = sm.process_tick(rtt_ms=30.0, drift_ms=3000.0, is_catastrophic=True)
        assert cat_tr is not None
        assert cat_tr.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert sm.is_hard_aborted()
        assert sm.is_manual_freeze is False

    def test_negative_telemetry_marks_evaluated_unhealthy(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        assert sm.is_healthy_tick(rtt_ms=-1.0, drift_ms=10.0) is False
        assert sm.is_healthy_tick(rtt_ms=25.0, drift_ms=10.0, jitter_ms=-0.1) is False
        assert sm.is_healthy_tick(rtt_ms=25.0, drift_ms=10.0, jitter_ms=5.0) is True

    def test_threshold_validation_rejects_non_positive(self) -> None:
        with pytest.raises(DomainViolation, match="must be positive"):
            CanaryCircuitBreakerRecoveryStateMachine(latency_warning_threshold_ms=0.0)
        with pytest.raises(DomainViolation, match="must be positive"):
            CanaryCircuitBreakerRecoveryStateMachine(clock_drift_critical_threshold_ms=-50.0)
        with pytest.raises(DomainViolation, match="must be positive"):
            CanaryCircuitBreakerRecoveryStateMachine(jitter_threshold_ms=0.0)

    def test_escalate_outage_empty_transitions_guard(self) -> None:
        sm = CanaryCircuitBreakerRecoveryStateMachine()
        with sm._lock:
            sm._state = CircuitBreakerState.TIER_2_HARD_ABORT
        # No transitions recorded yet; escalate_outage should handle safely without IndexError
        tr = sm.escalate_outage(reason="Already aborted test")
        assert tr.new_state == CircuitBreakerState.TIER_2_HARD_ABORT


class TestPhase273SimulationTracks:
    """Validate execution of multi-scenario incident drills across defined tracks."""

    def test_track_1_transient_partition_and_auto_recovery(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track=IncidentTrackId.TRACK_1.value,
            recovery_hysteresis_ticks=5,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, db_path, jsonl_path, rep_path, cb_path, paper_path = runner.execute_drill()

        assert summary.phase == "phase_273"
        assert IncidentTrackId.TRACK_1.value in summary.tracks_executed
        t1_info = summary.tracks_summary[IncidentTrackId.TRACK_1.value]
        assert t1_info["status"] == "RESOLVED_AUTO_RECOVERY"
        assert t1_info["initial_state"] == CircuitBreakerState.NORMAL.value
        assert t1_info["final_state"] == CircuitBreakerState.NORMAL.value
        assert t1_info["recovery_duration_ms"] > 0
        assert summary.compliance["auto_recovery_verified"] is True
        assert summary.compliance["zero_balance_drift"] is True

    def test_track_2_sustained_outage_escalation(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track=IncidentTrackId.TRACK_2.value,
            max_reconnect_attempts=5,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()

        assert IncidentTrackId.TRACK_2.value in summary.tracks_executed
        t2_info = summary.tracks_summary[IncidentTrackId.TRACK_2.value]
        assert t2_info["status"] == "ESCALATED_HARD_ABORT"
        assert t2_info["final_state"] == CircuitBreakerState.TIER_2_HARD_ABORT.value
        assert t2_info["escalation_latency_ms"] > 0
        assert summary.compliance["outage_escalation_verified"] is True

    def test_track_3_catastrophic_drift_instantaneous_abort(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track=IncidentTrackId.TRACK_3.value,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()

        assert IncidentTrackId.TRACK_3.value in summary.tracks_executed
        t3_info = summary.tracks_summary[IncidentTrackId.TRACK_3.value]
        assert t3_info["status"] == "FAIL_CLOSED_HARD_ABORT"
        assert t3_info["final_state"] == CircuitBreakerState.TIER_2_HARD_ABORT.value
        assert t3_info["transitions_count"] == 1
        assert summary.compliance["catastrophic_abort_verified"] is True

    def test_track_4_operator_manual_intervention(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track=IncidentTrackId.TRACK_4.value,
            operator_id="operator-test-007",
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()

        assert IncidentTrackId.TRACK_4.value in summary.tracks_executed
        t4_info = summary.tracks_summary[IncidentTrackId.TRACK_4.value]
        assert t4_info["status"] == "OPERATOR_MANUAL_RESOLVED"
        assert t4_info["final_state"] == CircuitBreakerState.NORMAL.value
        assert summary.compliance["manual_override_verified"] is True

    def test_all_tracks_sequential_execution(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track="all",
            recovery_hysteresis_ticks=5,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, db_path, jsonl_path, rep_path, cb_path, paper_path = runner.execute_drill()

        assert len(summary.tracks_executed) == 4
        assert summary.compliance["all_criteria_passed"] is True
        assert summary.circuit_breaker_stats["total_transitions"] >= 7
        assert summary.circuit_breaker_stats["auto_recoveries_count"] == 1
        assert summary.circuit_breaker_stats["escalations_count"] == 1
        assert summary.circuit_breaker_stats["hard_aborts_count"] == 2
        assert summary.circuit_breaker_stats["manual_overrides_count"] == 2

    def test_track_2_terminal_state_in_paper_summary(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track=IncidentTrackId.TRACK_2.value,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        _, _, _, _, _, paper_path = runner.execute_drill()
        paper_data = json.loads(paper_path.read_text(encoding="utf-8"))
        assert paper_data["circuit_state"] == CircuitBreakerState.TIER_2_HARD_ABORT.value

    def test_track_3_terminal_state_in_paper_summary(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track=IncidentTrackId.TRACK_3.value,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        _, _, _, _, _, paper_path = runner.execute_drill()
        paper_data = json.loads(paper_path.read_text(encoding="utf-8"))
        assert paper_data["circuit_state"] == CircuitBreakerState.TIER_2_HARD_ABORT.value


class TestPhase273SqliteAndJsonlPersistence:
    """Validate isolated SQLite store and JSON lines audit streaming."""

    def test_sqlite_pragmas_and_schema_initialization(
        self, isolated_store: SqliteCanaryIncidentTelemetryStore
    ) -> None:
        cur = isolated_store._conn.cursor()
        cur.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0].upper() == "WAL"

        cur.execute("PRAGMA synchronous")
        assert cur.fetchone()[0] == 1  # NORMAL

        cur.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1

        tables = [
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        assert "incidents" in tables
        assert "circuit_breaker_events" in tables
        assert "telemetry_ticks" in tables
        assert "accounting_ledger" in tables
        assert "post_mortem_records" in tables

    def test_record_and_retrieve_incident(
        self, isolated_store: SqliteCanaryIncidentTelemetryStore
    ) -> None:
        inc = CanaryIncidentRecord(
            incident_id="inc-test-001",
            track_id="track_1",
            track_name="Test Drill",
            status="RESOLVED_AUTO_RECOVERY",
            root_cause="Transient test anomaly",
            start_time_utc="2026-09-18T10:00:00+00:00",
            end_time_utc="2026-09-18T10:00:05+00:00",
            duration_seconds=5.0,
            escalation_latency_ms=0.0,
            recovery_duration_ms=125.0,
            initial_state=CircuitBreakerState.NORMAL,
            final_state=CircuitBreakerState.NORMAL,
            transitions_count=2,
            details={"test_key": "test_val"},
        )
        rowid = isolated_store.record_incident(inc)
        assert rowid > 0

        incidents = isolated_store.get_incidents()
        assert len(incidents) == 1
        assert incidents[0]["incident_id"] == "inc-test-001"
        assert incidents[0]["status"] == "RESOLVED_AUTO_RECOVERY"

    def test_record_and_retrieve_cb_events(
        self, isolated_store: SqliteCanaryIncidentTelemetryStore
    ) -> None:
        tr = CircuitBreakerTransition(
            timestamp_utc="2026-09-18T10:00:01+00:00",
            previous_state=CircuitBreakerState.NORMAL,
            new_state=CircuitBreakerState.TIER_1_SOFT_FREEZE,
            reason="Test soft freeze",
            trigger_severity=AlertSeverity.CRITICAL,
            consecutive_healthy_ticks=0,
            is_manual_override=False,
        )
        isolated_store.record_circuit_breaker_transition("inc-test-001", "track_1", tr)
        events = isolated_store.get_circuit_breaker_events("inc-test-001")
        assert len(events) == 1
        assert events[0]["new_state"] == CircuitBreakerState.TIER_1_SOFT_FREEZE.value

    def test_record_and_retrieve_ticks(
        self, isolated_store: SqliteCanaryIncidentTelemetryStore
    ) -> None:
        tick = TelemetryTick(
            timestamp_utc="2026-09-18T10:00:01+00:00",
            sequence_num=1,
            rtt_ms=28.5,
            drift_ms=10.0,
            jitter_ms=4.0,
            is_healthy=True,
        )
        isolated_store.record_telemetry_tick("inc-test-001", "track_1", tick)
        ticks = isolated_store.get_telemetry_ticks("inc-test-001")
        assert len(ticks) == 1
        assert ticks[0]["rtt_ms"] == 28.5
        assert ticks[0]["is_healthy"] == 1

    def test_jsonl_incident_sink(self, tmp_path: Path) -> None:
        sink_path = tmp_path / "test-canary-incidents.jsonl"
        inc = CanaryIncidentRecord(
            incident_id="inc-jsonl-001",
            track_id="track_1",
            track_name="JSONL Test",
            status="RESOLVED",
            root_cause="Test",
            start_time_utc="2026-09-18T10:00:00+00:00",
            end_time_utc="2026-09-18T10:00:01+00:00",
            duration_seconds=1.0,
            escalation_latency_ms=0.0,
            recovery_duration_ms=50.0,
            initial_state=CircuitBreakerState.NORMAL,
            final_state=CircuitBreakerState.NORMAL,
            transitions_count=1,
        )
        with JsonlIncidentSink(sink_path) as sink:
            sink.append(inc)

        assert sink_path.exists()
        lines = sink_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["incident_id"] == "inc-jsonl-001"
        assert_zero_secrets(lines[0], "test-canary-incidents.jsonl")

    def test_sqlite_multithreaded_concurrent_writes(
        self, isolated_store: SqliteCanaryIncidentTelemetryStore
    ) -> None:
        def worker(worker_id: int) -> None:
            for i in range(10):
                inc_id = f"inc-worker-{worker_id}-{i}"
                isolated_store.record_incident(
                    CanaryIncidentRecord(
                        incident_id=inc_id,
                        track_id="track_concurrent",
                        track_name="Concurrent Test",
                        status="RESOLVED",
                        root_cause="Test",
                        start_time_utc="2026-09-18T10:00:00+00:00",
                        end_time_utc="2026-09-18T10:00:01+00:00",
                        duration_seconds=1.0,
                        escalation_latency_ms=0.0,
                        recovery_duration_ms=10.0,
                        initial_state=CircuitBreakerState.NORMAL,
                        final_state=CircuitBreakerState.NORMAL,
                        transitions_count=0,
                    )
                )
                isolated_store.record_telemetry_tick(
                    inc_id,
                    "track_concurrent",
                    TelemetryTick(
                        timestamp_utc="2026-09-18T10:00:00+00:00",
                        sequence_num=i,
                        rtt_ms=25.0,
                        drift_ms=10.0,
                        jitter_ms=2.0,
                        is_healthy=True,
                    ),
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, w) for w in range(5)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        incidents = isolated_store.get_incidents()
        assert len(incidents) == 50
        ticks = isolated_store.get_telemetry_ticks()
        assert len(ticks) == 50

    def test_jsonl_sink_multithreaded_concurrent_appends(self, tmp_path: Path) -> None:
        sink_path = tmp_path / "concurrent-canary-incidents.jsonl"
        sink = JsonlIncidentSink(sink_path)

        def worker(worker_id: int) -> None:
            for i in range(10):
                inc = CanaryIncidentRecord(
                    incident_id=f"inc-cjsonl-{worker_id}-{i}",
                    track_id="track_concurrent",
                    track_name="Concurrent JSONL",
                    status="RESOLVED",
                    root_cause="Test",
                    start_time_utc="2026-09-18T10:00:00+00:00",
                    end_time_utc="2026-09-18T10:00:01+00:00",
                    duration_seconds=1.0,
                    escalation_latency_ms=0.0,
                    recovery_duration_ms=10.0,
                    initial_state=CircuitBreakerState.NORMAL,
                    final_state=CircuitBreakerState.NORMAL,
                    transitions_count=0,
                )
                sink.append(inc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, w) for w in range(5)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        sink.close()
        lines = sink_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 50
        for line in lines:
            parsed = json.loads(line)
            assert "incident_id" in parsed


class TestPhase273AccountingAndSafetyInvariants:
    """Validate portfolio balance reconciliation and fail-closed safety invariants."""

    def test_exact_zero_balance_drift_calculation(self) -> None:
        starting_equity = ACCOUNTING_STARTING_EQUITY
        final_cash = ACCOUNTING_FINAL_CASH
        realized_pnl = ACCOUNTING_REALIZED_PNL
        drift = abs(final_cash - (starting_equity + realized_pnl))
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        assert drift == Decimal("0.00")

    def test_adverse_drift_detection_and_rejection(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track=IncidentTrackId.TRACK_1.value,
            simulate_adverse_drift=True,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()

        # Zero balance drift should fail when simulated adverse drift is injected
        assert summary.compliance["zero_balance_drift"] is False
        assert summary.compliance["all_criteria_passed"] is False

    def test_strict_read_only_safety_invariants(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track=IncidentTrackId.TRACK_1.value,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()

        assert summary.safety_invariants["execution_authority"] is False
        assert summary.safety_invariants["exchange_access"] is False
        assert summary.safety_invariants["orders"] == 0
        assert summary.safety_invariants["api_keys_loaded"] == 0
        assert summary.safety_invariants["zero_secret_leakage"] is True


class TestPhase273ReportsAndPackaging:
    """Validate artifact persistence, post-mortem content, and cryptographic hashing."""

    def test_all_reports_generated_with_valid_hashes(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(output_dir=tmp_path, target_track="all")
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, db_path, jsonl_path, rep_path, cb_path, paper_path = runner.execute_drill()

        # Verify all files exist
        assert db_path.exists()
        assert jsonl_path.exists()
        assert rep_path.exists()
        assert cb_path.exists()
        assert paper_path.exists()

        # Verify SHA-256 hashes match files on disk
        for fname, h in summary.artifact_hashes.items():
            fpath = tmp_path / fname
            if fpath.exists():
                computed = compute_file_sha256(fpath)
                assert computed == h

        # Verify post-mortem report schema
        rep_content = json.loads(rep_path.read_text(encoding="utf-8"))
        assert rep_content["phase"] == "phase_273"
        assert len(rep_content["incidents"]) == 4
        assert rep_content["compliance"]["all_criteria_passed"] is True

        # Verify circuit breaker summary schema
        cb_content = json.loads(cb_path.read_text(encoding="utf-8"))
        assert cb_content["recovery_hysteresis_k"] == 5
        assert len(cb_content["tracks_summary"]) == 4

        # Verify paper summary schema
        paper_content = json.loads(paper_path.read_text(encoding="utf-8"))
        assert paper_content["starting_capital_usdt"] == "100.00"
        assert paper_content["final_cash_usdt"] == "100.00"
        assert paper_content["drift_usdt"] == "0"
        assert paper_content["zero_balance_drift"] is True

    def test_circuit_breaker_summary_in_paper_summary_artifact_hashes(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(output_dir=tmp_path, target_track="1")
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        _, _, _, rep_path, cb_path, paper_path = runner.execute_drill()

        paper_data = json.loads(paper_path.read_text(encoding="utf-8"))
        assert "circuit-breaker-summary.json" in paper_data["artifact_hashes"]
        expected_hash = compute_file_sha256(cb_path)
        assert paper_data["artifact_hashes"]["circuit-breaker-summary.json"] == expected_hash


class TestPhase273CliRunner:
    """Validate CLI argument parsing, execution modes, and formatted summaries."""

    def test_cli_parser_defaults(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.track == "all"
        assert args.recovery_hysteresis_ticks == 5
        assert args.force_freeze is False
        assert args.force_abort is False
        assert args.force_recover is False
        assert args.operator_id == "operator-lead-001"
        assert args.json is False

    def test_cli_parser_custom_args(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(
            [
                "--track",
                "1",
                "--recovery-hysteresis-ticks",
                "7",
                "--force-freeze",
                "--operator-id",
                "operator-special",
                "--json",
            ]
        )
        assert args.track == "1"
        assert args.recovery_hysteresis_ticks == 7
        assert args.force_freeze is True
        assert args.operator_id == "operator-special"
        assert args.json is True

    def test_cli_main_execution(self, tmp_path: Path) -> None:
        ret = cli_main(["--output-dir", str(tmp_path), "--track", "1"])
        assert ret == 0

    def test_cli_main_json_output(self, tmp_path: Path, monkeypatch: Any) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        ret = cli_main(["--output-dir", str(tmp_path), "--track", "1", "--json"])
        assert ret == 0
        output = buf.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["phase"] == "phase_273"
        assert parsed["compliance"]["all_criteria_passed"] is True

    def test_format_summary_table(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(output_dir=tmp_path, target_track="1")
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()
        table_str = format_summary_table(summary)
        assert "PHASE 273: CANARY CIRCUIT BREAKER RECOVERY" in table_str
        assert "Circuit Breaker State Machine & Transition Statistics:" in table_str
        assert "Exact Double-Entry Accounting & Margin Guardrails:" in table_str

    def test_cli_force_abort_override_track(self, tmp_path: Path) -> None:
        ret = cli_main(
            ["--output-dir", str(tmp_path), "--force-abort", "--operator-id", "test-op-abort"]
        )
        assert ret == 0
        paper_path = tmp_path / "paper-summary.json"
        assert paper_path.exists()
        paper_data = json.loads(paper_path.read_text(encoding="utf-8"))
        assert paper_data["circuit_state"] == CircuitBreakerState.TIER_2_HARD_ABORT.value
        cb_summary = json.loads(
            (tmp_path / "circuit-breaker-summary.json").read_text(encoding="utf-8")
        )
        assert IncidentTrackId.CLI_OVERRIDE.value in cb_summary["tracks_summary"]
        assert cb_summary["circuit_breaker_stats"]["manual_overrides_count"] >= 1

    def test_cli_force_freeze_override_track(self, tmp_path: Path) -> None:
        ret = cli_main(
            ["--output-dir", str(tmp_path), "--force-freeze", "--operator-id", "test-op-freeze"]
        )
        assert ret == 0
        paper_path = tmp_path / "paper-summary.json"
        assert paper_path.exists()
        paper_data = json.loads(paper_path.read_text(encoding="utf-8"))
        assert paper_data["circuit_state"] == CircuitBreakerState.TIER_1_SOFT_FREEZE.value
        cb_summary = json.loads(
            (tmp_path / "circuit-breaker-summary.json").read_text(encoding="utf-8")
        )
        assert IncidentTrackId.CLI_OVERRIDE.value in cb_summary["tracks_summary"]
        assert cb_summary["circuit_breaker_stats"]["manual_overrides_count"] >= 1

    def test_cli_mutually_exclusive_force_flags(self) -> None:
        parser = build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--force-freeze", "--force-abort"])

    def test_cli_override_without_flags_runs_default_drill(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track="cli_override",
            operator_id="test-op-default",
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()
        assert "cli_override" in summary.tracks_executed
        override_info = summary.tracks_summary["cli_override"]
        assert override_info["status"] == "OPERATOR_MANUAL_RESOLVED"
        assert override_info["transitions_count"] == 2


class TestPhase273AdversarialHardening:
    """Adversarial stress tests for edge cases, non-finite telemetry, and illegal transitions."""

    def test_non_finite_telemetry_nan_triggers_catastrophic_abort(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        # Ingest NaN clock drift
        tr = sm.process_tick(rtt_ms=25.0, drift_ms=float("nan"), jitter_ms=2.0)
        assert tr is not None
        assert tr.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert tr.trigger_severity == AlertSeverity.EMERGENCY
        assert sm.is_hard_aborted()
        assert "non-finite telemetry" in tr.reason

    def test_non_finite_telemetry_inf_triggers_catastrophic_abort(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        tr = sm.process_tick(rtt_ms=float("inf"), drift_ms=10.0, jitter_ms=2.0)
        assert tr is not None
        assert tr.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert sm.is_hard_aborted()

    def test_is_healthy_tick_rejects_nan_and_inf(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        assert sm.is_healthy_tick(rtt_ms=float("nan"), drift_ms=10.0) is False
        assert sm.is_healthy_tick(rtt_ms=25.0, drift_ms=float("nan")) is False
        assert sm.is_healthy_tick(rtt_ms=25.0, drift_ms=10.0, jitter_ms=float("inf")) is False

    def test_force_recover_from_normal_raises_domain_violation(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        assert sm.is_normal()
        with pytest.raises(DomainViolation, match="already in NORMAL state"):
            sm.force_recover(operator_id="op-1")

    def test_escalate_outage_from_normal_raises_domain_violation(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        assert sm.is_normal()
        with pytest.raises(
            DomainViolation,
            match="Cannot escalate outage when circuit breaker is in NORMAL",
        ):
            sm.escalate_outage(reason="Invalid escalation")

    def test_duplicate_trigger_catastrophic_abort_deduplication(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        sm.trigger_catastrophic_abort(reason="First catastrophic abort")
        assert len(sm.transitions) == 1
        # Second call returns existing transition without appending duplicates
        tr2 = sm.trigger_catastrophic_abort(reason="Second catastrophic abort")
        assert tr2.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert len(sm.transitions) == 1

    def test_drill_config_validation_rejects_invalid_values(self) -> None:
        with pytest.raises(DomainViolation, match="Unknown incident drill track ID"):
            CanaryCircuitBreakerDrillConfig(target_track="invalid_track_name")
        with pytest.raises(DomainViolation, match="recovery_hysteresis_ticks must be positive"):
            CanaryCircuitBreakerDrillConfig(recovery_hysteresis_ticks=0)
        with pytest.raises(DomainViolation, match="max_reconnect_attempts must be positive"):
            CanaryCircuitBreakerDrillConfig(max_reconnect_attempts=-1)
        with pytest.raises(DomainViolation, match="grace_timeout_seconds must be positive"):
            CanaryCircuitBreakerDrillConfig(grace_timeout_seconds=0.0)
        with pytest.raises(DomainViolation, match="latency_warning_threshold_ms must be positive"):
            CanaryCircuitBreakerDrillConfig(latency_warning_threshold_ms=0.0)
        with pytest.raises(
            DomainViolation,
            match="clock_drift_critical_threshold_ms must be positive",
        ):
            CanaryCircuitBreakerDrillConfig(clock_drift_critical_threshold_ms=-10.0)
        with pytest.raises(DomainViolation, match="operator_id cannot be empty"):
            CanaryCircuitBreakerDrillConfig(operator_id="   ")

    def test_drill_config_validation_rejects_conflicting_force_flags(self) -> None:
        with pytest.raises(
            DomainViolation,
            match="Cannot specify multiple conflicting force override flags",
        ):
            CanaryCircuitBreakerDrillConfig(force_freeze=True, force_abort=True)

    def test_adverse_drift_propagates_faithfully_to_paper_summary(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(
            output_dir=tmp_path,
            target_track="track_1",
            simulate_adverse_drift=True,
        )
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, paper_path = runner.execute_drill()
        assert summary.compliance["zero_balance_drift"] is False
        assert summary.portfolio_accounting["final_cash_usdt"] == "99.95"
        assert summary.portfolio_accounting["drift_usdt"] == "0.05"

        paper_data = json.loads(paper_path.read_text(encoding="utf-8"))
        assert paper_data["final_cash_usdt"] == "99.95"
        assert paper_data["drift_usdt"] == "0.05"
        assert paper_data["zero_balance_drift"] is False

    def test_telemetry_tick_negative_sequence_num_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TelemetryTick(
                timestamp_utc="2026-09-18T10:00:00+00:00",
                sequence_num=-1,
                rtt_ms=25.0,
                drift_ms=10.0,
                jitter_ms=2.0,
                is_healthy=True,
            )

    def test_state_machine_initial_state_constructor(self) -> None:
        # Default is NORMAL
        sm_norm = CanaryCircuitBreakerRecoveryStateMachine()
        assert sm_norm.current_state == CircuitBreakerState.NORMAL
        assert sm_norm.is_normal()
        assert len(sm_norm.transitions) == 0

        # Direct initialization into TIER_1_SOFT_FREEZE
        sm_freeze = CanaryCircuitBreakerRecoveryStateMachine(
            initial_state=CircuitBreakerState.TIER_1_SOFT_FREEZE
        )
        assert sm_freeze.current_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert sm_freeze.is_soft_frozen()
        assert sm_freeze.is_manual_freeze is True
        assert len(sm_freeze.transitions) == 0

        # Direct initialization into TIER_2_HARD_ABORT
        sm_abort = CanaryCircuitBreakerRecoveryStateMachine(
            initial_state=CircuitBreakerState.TIER_2_HARD_ABORT
        )
        assert sm_abort.current_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert sm_abort.is_hard_aborted()
        assert len(sm_abort.transitions) == 0

        # Rejection of invalid initial_state
        with pytest.raises(
            DomainViolation, match="initial_state must be a CircuitBreakerState enum"
        ):
            CanaryCircuitBreakerRecoveryStateMachine(initial_state="INVALID_STATE")  # type: ignore

    def test_force_recover_from_hard_abort_raises_domain_violation(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        sm.force_abort(operator_id="op-1")
        assert sm.is_hard_aborted()
        with pytest.raises(
            DomainViolation,
            match="Cannot force recovery when system is in TIER_2_HARD_ABORT",
        ):
            sm.force_recover(operator_id="op-1")

    def test_force_abort_idempotency_does_not_duplicate_transitions(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        tr1 = sm.force_abort(operator_id="op-1", rationale="First abort")
        assert tr1.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert sm.is_hard_aborted()
        assert len(sm.transitions) == 1

        tr2 = sm.force_abort(operator_id="op-1", rationale="Second abort")
        assert tr2.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        assert len(sm.transitions) == 1

    def test_force_freeze_idempotency_when_already_manually_frozen(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        tr1 = sm.force_freeze(operator_id="op-1", rationale="First freeze")
        assert tr1.new_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert sm.is_soft_frozen()
        assert len(sm.transitions) == 1

        tr2 = sm.force_freeze(operator_id="op-1", rationale="Second freeze")
        assert tr2.new_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        assert len(sm.transitions) == 1

    def test_freeze_timestamp_perf_cleared_on_all_abort_paths(
        self, sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        # 1. escalate_outage cleans up _freeze_timestamp_perf
        sm.force_freeze(operator_id="op-1")
        assert sm._freeze_timestamp_perf is not None
        sm.escalate_outage(reason="escalate")
        assert sm._freeze_timestamp_perf is None
        assert sm.escalation_latency_ms > 0

        # 2. trigger_catastrophic_abort cleans up _freeze_timestamp_perf
        sm.reset()
        sm.force_freeze(operator_id="op-1")
        assert sm._freeze_timestamp_perf is not None
        sm.trigger_catastrophic_abort(reason="catastrophic")
        assert sm._freeze_timestamp_perf is None
        assert sm.escalation_latency_ms > 0

        # 3. process_tick catastrophic tick cleans up _freeze_timestamp_perf
        sm.reset()
        sm.force_freeze(operator_id="op-1")
        assert sm._freeze_timestamp_perf is not None
        sm.process_tick(rtt_ms=25.0, drift_ms=3000.0, is_catastrophic=True)
        assert sm._freeze_timestamp_perf is None
        assert sm.escalation_latency_ms > 0

        # 4. force_abort cleans up _freeze_timestamp_perf
        sm.reset()
        sm.force_freeze(operator_id="op-1")
        assert sm._freeze_timestamp_perf is not None
        sm.force_abort(operator_id="op-1")
        assert sm._freeze_timestamp_perf is None
        assert sm.escalation_latency_ms > 0

    def test_cli_track_chained_with_force_freeze_succeeds_without_crash(
        self, tmp_path: Path
    ) -> None:
        ret = execute_phase_273_runner(
            output_dir=tmp_path,
            track="track_2",
            force_freeze=True,
            operator_id="test-op-chain",
        )
        assert ret == 0
        summary_path = tmp_path / "circuit-breaker-summary.json"
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        assert "track_2" in summary_data["tracks_summary"]
        assert "cli_override" in summary_data["tracks_summary"]
        assert summary_data["tracks_summary"]["track_2"]["status"] == "ESCALATED_HARD_ABORT"
        assert summary_data["tracks_summary"]["cli_override"]["status"] == "OPERATOR_MANUAL_FREEZE"

    def test_verify_hash_chain_cli_and_function(self, tmp_path: Path) -> None:
        # Run drill with verify_hash_chain=True
        ret = execute_phase_273_runner(
            output_dir=tmp_path,
            track="all",
            verify_hash_chain=True,
        )
        assert ret == 0

        # Standalone verification function returns True
        assert verify_phase_273_hash_chain(output_dir=tmp_path) is True

        # Tampering with an artifact causes verification to fail
        report_path = tmp_path / "canary-incident-report.json"
        tampered = json.loads(report_path.read_text(encoding="utf-8"))
        tampered["phase"] = "phase_tampered"
        report_path.write_text(json.dumps(tampered), encoding="utf-8")
        assert verify_phase_273_hash_chain(output_dir=tmp_path) is False

    def test_paper_summary_included_in_summary_artifact_hashes(self, tmp_path: Path) -> None:
        cfg = CanaryCircuitBreakerDrillConfig(output_dir=tmp_path, target_track="1")
        runner = CanaryCircuitBreakerDrillRunner(cfg)
        summary, _, _, _, _, paper_path = runner.execute_drill()
        assert "paper-summary.json" in summary.artifact_hashes
        expected_hash = compute_file_sha256(paper_path)
        assert summary.artifact_hashes["paper-summary.json"] == expected_hash
