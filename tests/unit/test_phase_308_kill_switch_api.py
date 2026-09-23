"""Unit tests for Phase 308 Kill-Switch API and Cryptographic Evidence Loader."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    load_verified_canary_kill_switch,
)

PHASE_307_PARENT_MERKLE_ROOT = "4eb405de6cdc48e26fddaa4a2ed8bd91ef9e0843a4b71cfd0cb643a15e7ceb16"


def _build_synthetic_phase308_artifacts(
    target_dir: Path,
    upstream_hash: str = PHASE_307_PARENT_MERKLE_ROOT,
    tamper_file: str | None = None,
    tamper_merkle: bool = False,
    tamper_drift: bool = False,
) -> dict[str, Any]:
    """Helper to generate valid cryptographic Phase 308 artifacts for testing."""
    target_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = target_dir / "canary-kill-switch-telemetry.sqlite3"
    events_path = target_dir / "canary-kill-switch-events.jsonl"
    report_path = target_dir / "canary-kill-switch-report.json"
    summary_path = target_dir / "kill-switch-summary.json"

    # SQLite3 database
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE kill_switch_events (event_id TEXT, reason TEXT)")
    cur.execute("INSERT INTO kill_switch_events VALUES ('ks-01', 'Test reason')")
    conn.commit()
    conn.close()

    # Events JSONL
    evt_record = {
        "event_id": "ks-evt-0001",
        "tier": "LEVEL_3_PANIC",
        "previous_state": "ARMED_NORMAL",
        "new_state": "LEVEL_3_HARDWARE_PANIC",
        "reason": "Test panic",
        "trigger_source": "OS_SIGNAL",
        "positions_flattened_count": 2,
        "orders_cancelled_count": 3,
        "memory_wiped": True,
        "timestamp_ms": 1790150000000,
    }
    with open(events_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(evt_record) + "\n")

    # Hash computation
    if tamper_file == "sqlite":
        sqlite_bytes = sqlite_path.read_bytes() + b"tamper"
    else:
        sqlite_bytes = sqlite_path.read_bytes()
    sqlite_hash = hashlib.sha256(sqlite_bytes).hexdigest()

    events_bytes = events_path.read_bytes()
    events_hash = hashlib.sha256(events_bytes).hexdigest()

    drift_val = 0.05 if tamper_drift else 0.0

    combined_payload = f"phase_308:{upstream_hash}:{sqlite_hash}:{events_hash}:{drift_val}"
    phase_hash = hashlib.sha256(combined_payload.encode()).hexdigest()

    if tamper_merkle:
        merkle_root = "bad" * 16
    else:
        merkle_root = hashlib.sha256(f"{upstream_hash}:{phase_hash}".encode()).hexdigest()

    solvency_dict = {
        "starting_equity": 100.0,
        "cash": 100.0,
        "allocated_margin": 0.0,
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "total_equity": 100.0,
        "drift": drift_val,
        "zero_balance_drift": not tamper_drift,
        "cash_reserve_pct": 100.0,
        "unencumbered_cash_verified": True,
    }

    report_dict = {
        "phase": "phase_308",
        "status": "KILL_SWITCH_VERIFIED",
        "timestamp_ms": 1790150000000,
        "signers": [
            {
                "signer_id": "signer-1",
                "public_key": "p1",
                "role": "CRO",
                "is_active": True,
                "last_nonce": 1,
            }
        ],
        "proposals": [
            {
                "proposal_id": "prop-1",
                "action_type": "RESET",
                "target": "ks",
                "parameters": {},
                "required_quorum": 2,
                "votes_cast": 2,
                "is_executed": True,
            }
        ],
        "events_trace": [evt_record],
        "solvency": solvency_dict,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f)

    summary_dict = {
        "phase": "phase_308",
        "verified": True,
        "status": "KILL_SWITCH_VERIFIED",
        "timestamp_ms": 1790150000000,
        "paper_safe": True,
        "execution_authority": False,
        "kill_switch_state": "LEVEL_3_HARDWARE_PANIC",
        "memory_wiped": True,
        "active_signers_count": 1,
        "required_quorum": 2,
        "proposals_evaluated": 1,
        "proposals_executed": 1,
        "total_kill_events": 1,
        "emergency_flattened_positions": 2,
        "cancelled_orders_count": 3,
        "solvency": solvency_dict,
        "upstream_hash": upstream_hash,
        "phase_hash": phase_hash,
        "merkle_root": merkle_root,
        "artifact_hashes": {
            "sqlite3": sqlite_hash,
            "events_jsonl": events_hash,
        },
        "upstream_merkle_dag": {"phase_307": upstream_hash},
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f)

    return summary_dict


def test_load_verified_canary_kill_switch_success(tmp_path: Path) -> None:
    _build_synthetic_phase308_artifacts(tmp_path)
    res = load_verified_canary_kill_switch(tmp_path)

    assert res.verified
    assert res.phase == "phase_308"
    assert res.status == "KILL_SWITCH_VERIFIED"
    assert res.paper_safe
    assert not res.execution_authority
    assert res.kill_switch_state == "LEVEL_3_HARDWARE_PANIC"
    assert res.memory_wiped
    assert res.solvency.zero_balance_drift_verified


def test_load_verified_canary_kill_switch_missing_evidence(tmp_path: Path) -> None:
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_kill_switch(tmp_path)


def test_load_verified_canary_kill_switch_tamper_hash(tmp_path: Path) -> None:
    _build_synthetic_phase308_artifacts(tmp_path, tamper_file="sqlite")
    with pytest.raises(CanaryEvidenceIntegrityError, match="Artifact SHA-256 hash mismatch"):
        load_verified_canary_kill_switch(tmp_path)


def test_load_verified_canary_kill_switch_upstream_mismatch(tmp_path: Path) -> None:
    _build_synthetic_phase308_artifacts(tmp_path, upstream_hash="bad" * 16)
    with pytest.raises(CanaryEvidenceIntegrityError, match="Upstream hash mismatch"):
        load_verified_canary_kill_switch(tmp_path)


def test_load_verified_canary_kill_switch_merkle_mismatch(tmp_path: Path) -> None:
    _build_synthetic_phase308_artifacts(tmp_path, tamper_merkle=True)
    with pytest.raises(CanaryEvidenceIntegrityError, match="Phase 308 Merkle root mismatch"):
        load_verified_canary_kill_switch(tmp_path)


def test_load_verified_canary_kill_switch_drift_breach(tmp_path: Path) -> None:
    _build_synthetic_phase308_artifacts(tmp_path, tamper_drift=True)
    with pytest.raises(
        CanaryEvidenceIntegrityError, match="Double-entry zero-drift balance invariant breached"
    ):
        load_verified_canary_kill_switch(tmp_path)


def test_api_canary_kill_switch_endpoint_success(tmp_path: Path) -> None:
    _build_synthetic_phase308_artifacts(tmp_path)
    app = create_app(canary_phase_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/v1/canary/kill-switch")
    assert response.status_code == 200
    data = response.json()
    assert data["verified"]
    assert data["phase"] == "phase_308"
    assert data["status"] == "KILL_SWITCH_VERIFIED"
    assert data["memory_wiped"]


def test_api_canary_kill_switch_endpoint_not_found(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_phase"
    empty_dir.mkdir()
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/kill-switch")
    assert response.status_code == 404
    assert response.json()["detail"] == "canary kill switch evidence unavailable"


def test_api_canary_kill_switch_endpoint_integrity_failure(tmp_path: Path) -> None:
    _build_synthetic_phase308_artifacts(tmp_path, tamper_merkle=True)
    app = create_app(canary_phase_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/v1/canary/kill-switch")
    assert response.status_code == 503
    assert response.json()["detail"] == "canary kill switch integrity verification failed"
