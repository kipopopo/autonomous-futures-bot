from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.errors import DomainViolation
from autonomous_futures.domain.risk import ResumeEvidence
from autonomous_futures.paper.candidate_registry import (
    build_candidate_registry_manifest,
    write_candidate_registry,
)
from autonomous_futures.paper.resume_control import (
    PaperRecoveryPreflight,
    build_paper_resume_request,
    capture_paper_recovery_preflight,
    read_paper_resume_request,
    write_paper_resume_request,
)

START = datetime(2026, 9, 13, 6, 30, tzinfo=UTC)
REGISTRY_HASH = "a" * 64


def _evidence(**overrides: bool) -> ResumeEvidence:
    values = {
        "reconciled": True,
        "incident_resolved": True,
        "data_fresh": True,
        "risk_healthy": True,
        "operator_approved": True,
    }
    values.update(overrides)
    return ResumeEvidence(**values)


def _preflight(**overrides: object) -> PaperRecoveryPreflight:
    values: dict[str, object] = {
        "observed_at": START,
        "breaker_sidecar_state": "HALTED",
        "daemon_health_state": "HALTED",
        "daemon_status": "RUNNING",
        "heartbeat_fresh": True,
        "scheduler_status": "IDLE",
        "scheduler_heartbeat_fresh": True,
        "ledger_integrity": "ok",
        "ledger_opens": 166,
        "ledger_closes": 166,
        "dirty_intents": 0,
        "unmatched_opens": 0,
        "persisted_positions": 0,
        "active_positions": 0,
        "candidate_registry_hash": REGISTRY_HASH,
        "candidate_count": 0,
        "orders_submitted": 0,
        "execution_authority": False,
        "live_trading_activation": False,
        "zero_private_credentials": True,
    }
    values.update(overrides)
    return PaperRecoveryPreflight(**values)


def _request(**overrides: object):
    values: dict[str, object] = {
        "request_id": "paper-resume-20260913-0630",
        "evidence": _evidence(),
        "preflight": _preflight(),
        "created_at": START,
        "expires_at": START + timedelta(minutes=10),
    }
    values.update(overrides)
    return build_paper_resume_request(**values)


def test_prepare_resume_request_is_explicit_and_non_authoritative(tmp_path: Path) -> None:
    request = _request()
    path = tmp_path / "resume-request.json"

    persisted = write_paper_resume_request(path, request)
    loaded = read_paper_resume_request(path)

    assert persisted == request
    assert loaded == request
    assert request.status == "ready_for_operator_apply"
    assert request.control_scope == "paper_only"
    assert request.paper_activation is False
    assert request.execution_authority is False
    assert request.testnet_activation is False
    assert request.live_activation is False
    assert len(request.request_hash) == 64
    assert not (tmp_path / "paper-circuit-breaker-state.json").exists()
    assert write_paper_resume_request(path, request) == request


def test_prepare_rejects_incomplete_evidence_without_writing(tmp_path: Path) -> None:
    with pytest.raises(DataQualityError, match="evidence incomplete"):
        _request(evidence=_evidence(risk_healthy=False))

    assert not (tmp_path / "resume-request.json").exists()


def test_prepare_rejects_unsafe_current_preflight_without_writing() -> None:
    with pytest.raises(DataQualityError, match="dirty_intents"):
        _request(preflight=_preflight(dirty_intents=1))
    with pytest.raises(DataQualityError, match="active_positions"):
        _request(preflight=_preflight(active_positions=1))
    with pytest.raises(DataQualityError, match="candidate_count"):
        _request(preflight=_preflight(candidate_count=1))


def test_prepare_revalidates_semantic_model_copy_tampering() -> None:
    tampered_evidence = _evidence().model_copy(update={"operator_approved": False})
    tampered_preflight = _preflight().model_copy(update={"execution_authority": True})

    with pytest.raises(DataQualityError, match="evidence incomplete"):
        _request(evidence=tampered_evidence)
    with pytest.raises(DataQualityError, match="execution_authority_enabled"):
        _request(preflight=tampered_preflight)


def test_prepare_requires_a_fresh_preflight_snapshot() -> None:
    with pytest.raises(DataQualityError, match="preflight_stale"):
        _request(preflight=_preflight(observed_at=START - timedelta(minutes=3)))
    with pytest.raises(DataQualityError, match="preflight timestamp"):
        _request(preflight=_preflight(observed_at=START + timedelta(seconds=1)))


def test_capture_preflight_reads_storage_without_mutating_it(tmp_path: Path) -> None:
    storage = tmp_path / "paper_live"
    storage.mkdir()
    health = {
        "daemon_status": "RUNNING",
        "last_heartbeat_utc": START.isoformat(),
        "circuit_breaker_status": "HALTED",
        "active_positions_count": 0,
        "active_positions": {},
        "zero_order_safety_invariants": {
            "orders_submitted": 0,
            "execution_authority": False,
            "live_trading_activation": False,
            "zero_private_credentials": True,
        },
    }
    (storage / "paper-daemon-health.json").write_text(json.dumps(health), encoding="utf-8")
    (storage / "paper-circuit-breaker-state.json").write_text(
        json.dumps({"circuit_breaker_status": "HALTED"}), encoding="utf-8"
    )
    scheduler_dir = storage / "scheduler"
    scheduler_dir.mkdir()
    (scheduler_dir / "scheduler-health.json").write_text(
        json.dumps({"status": "IDLE", "updated_at": START.isoformat()}), encoding="utf-8"
    )
    registry = build_candidate_registry_manifest(updated_at=START)
    write_candidate_registry(storage / "candidate_registry.json", registry)

    ledger = storage / "paper-ledger.sqlite3"
    with sqlite3.connect(ledger) as connection:
        connection.executescript(
            """
            CREATE TABLE paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL
            );
            CREATE TABLE paper_position_state (
                trade_id TEXT PRIMARY KEY,
                state_version INTEGER NOT NULL,
                state_json TEXT NOT NULL
            );
            CREATE TABLE paper_position_update_intent (
                trade_id TEXT PRIMARY KEY,
                intent TEXT NOT NULL
            );
            """
        )
    before = ledger.read_bytes()

    snapshot = capture_paper_recovery_preflight(
        storage,
        observed_at=START + timedelta(seconds=30),
    )

    assert snapshot.breaker_sidecar_state == "HALTED"
    assert snapshot.daemon_health_state == "HALTED"
    assert snapshot.heartbeat_fresh is True
    assert snapshot.scheduler_heartbeat_fresh is True
    assert snapshot.ledger_integrity == "ok"
    assert snapshot.ledger_opens == 0
    assert snapshot.ledger_closes == 0
    assert snapshot.candidate_count == 0
    assert snapshot.zero_private_credentials is True
    assert ledger.read_bytes() == before


def test_capture_preflight_fails_without_storage_files(tmp_path: Path) -> None:
    storage = tmp_path / "missing-paper-live"

    with pytest.raises(DataQualityError, match="health"):
        capture_paper_recovery_preflight(storage, observed_at=START)

    assert not storage.exists()


def test_read_rejects_tampered_request(tmp_path: Path) -> None:
    path = tmp_path / "resume-request.json"
    write_paper_resume_request(path, _request())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evidence"]["operator_approved"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DomainViolation, match="resume request"):
        read_paper_resume_request(path)


def test_read_rejects_missing_and_malformed_request(tmp_path: Path) -> None:
    with pytest.raises(DomainViolation, match="resume request"):
        read_paper_resume_request(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(DomainViolation, match="resume request"):
        read_paper_resume_request(malformed)


def test_conflicting_request_id_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "resume-request.json"
    write_paper_resume_request(path, _request())

    conflicting = _request(expires_at=START + timedelta(minutes=11))
    with pytest.raises(DomainViolation, match="immutable"):
        write_paper_resume_request(path, conflicting)


def test_caller_hash_mismatch_fails_before_output(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "resume-request.json"
    invalid = _request().model_copy(update={"request_hash": "b" * 64})

    with pytest.raises(DomainViolation, match="hash"):
        write_paper_resume_request(path, invalid)

    assert not path.exists()
    assert not path.parent.exists()
