"""Unit tests for Phase 296 Autonomous Lifecycle FastAPI endpoint and loader.

Tests cover:
- 200 OK nominal endpoint response with full schema and invariant validation.
- 404 Not Found error mapping for missing evidence artifacts.
- 503 Service Unavailable error mapping for tampered hashes or drift violations.
- Direct loader validation of Merkle DAG integrity and zero-drift balance ledger.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryAutonomousLifecycleResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    load_verified_canary_autonomous_lifecycle,
)

PHASE_296_DIR = Path("artifacts/research/phase296")


def test_autonomous_lifecycle_endpoint_nominal_200_ok() -> None:
    """Verify GET /api/v1/canary/autonomous-lifecycle returns 200 OK with valid contract."""
    app = create_app(canary_phase_dir=PHASE_296_DIR)
    client = TestClient(app)

    res = client.get("/api/v1/canary/autonomous-lifecycle")
    assert res.status_code == 200

    data = res.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_296"
    assert data["status"] == "AUTONOMOUS_LIFECYCLE_VERIFIED"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False
    assert data["daemon_status"] == "ACTIVE"
    assert data["circuit_state"] == "NORMAL"

    # Validate 5 Subsystem Health items
    assert len(data["components"]) == 5
    comp_names = {c["name"] for c in data["components"]}
    assert "Public Ingress Gateway" in comp_names
    assert "Hawkes Microstructure Streamer" in comp_names
    assert "Strategy Activation Engine" in comp_names
    assert "Passive Matching Simulator" in comp_names
    assert "Zero-Drift Ledger" in comp_names
    for comp in data["components"]:
        assert comp["status"] == "HEALTHY"

    # Validate Longevity metrics
    longevity = data["longevity"]
    assert longevity["total_sessions"] >= 1
    assert longevity["total_ticks_processed"] > 0
    assert longevity["memory_bounded"] is True
    assert longevity["ring_buffer_capacity"] == 1000

    # Validate Sessions list
    assert len(data["sessions"]) >= 1
    for session in data["sessions"]:
        assert "session_" in session["session_id"]
        assert session["zero_balance_drift"] is True
        assert abs(session["drift_usdt"]) < 1e-15

    # Validate Risk Circuit indicators
    risk = data["risk_circuits"]
    assert risk["circuit_state"] == "NORMAL"
    assert risk["hawkes_supercritical"] is False
    assert risk["gateway_heartbeat_stale"] is False
    assert risk["margin_headroom_breach"] is False
    assert risk["loss_ceiling_breached"] is False
    assert risk["cash_reserve_depleted"] is False
    assert risk["cash_reserve_pct"] >= 40.0

    # Validate Operational Switches (fail-closed boundaries)
    assert len(data["operational_switches"]) >= 5
    switches_map = {s["name"]: s for s in data["operational_switches"]}
    assert switches_map["paper_safe"]["enabled"] is True
    assert switches_map["execution_authority"]["enabled"] is False
    assert switches_map["hawkes_cutoff"]["enabled"] is True
    assert switches_map["heartbeat_freshness"]["enabled"] is True
    assert switches_map["aggregate_margin_cap"]["enabled"] is True

    # Validate Double-Entry Ledger & Zero Drift
    ledger = data["ledger"]
    assert ledger["starting_equity"] == 100.0
    assert ledger["cash"] > 0.0
    assert abs(ledger["drift"]) < 1e-15
    assert ledger["zero_balance_drift"] is True

    # Validate SHA-256 Merkle DAG hashes
    assert len(data["phase_hash"]) == 64
    assert len(data["upstream_hash"]) == 64
    expected_root = "1d6e6412f9c2a19dce2625fd3236ebdb9bd6c527959bb33875889a18ee51f005"
    assert data["upstream_hash"] == expected_root
    assert len(data["merkle_root"]) == 64


def test_autonomous_lifecycle_endpoint_missing_dir_fails_404(tmp_path: Path) -> None:
    """Verify endpoint returns 404 when evidence directory does not exist."""
    missing_dir = tmp_path / "non_existent_phase296"
    app = create_app(canary_phase_dir=missing_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/autonomous-lifecycle")
    assert res.status_code == 404
    assert "unavailable" in res.json()["detail"]


def test_autonomous_lifecycle_endpoint_missing_artifact_fails_404(tmp_path: Path) -> None:
    """Verify endpoint returns 404 when any required artifact is missing."""
    phase_dir = tmp_path / "incomplete_phase296"
    phase_dir.mkdir()
    # Create only summary, but missing sqlite3, jsonl, etc.
    (phase_dir / "lifecycle-summary.json").write_text(json.dumps({"phase": "phase_296"}))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/autonomous-lifecycle")
    assert res.status_code == 404
    assert "unavailable" in res.json()["detail"]


def test_autonomous_lifecycle_endpoint_tampered_hash_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when an artifact hash does not match summary."""
    phase_dir = tmp_path / "tampered_phase"
    phase_dir.mkdir()

    # Create all required artifacts
    (phase_dir / "canary-lifecycle-telemetry.sqlite3").write_bytes(b"sqlite dummy")
    (phase_dir / "canary-orders.jsonl").write_text("{}\n")
    report_file = phase_dir / "canary-lifecycle-report.json"
    report_file.write_text(json.dumps({"drift_usdt": "0.0", "zero_balance_drift": True}))
    (phase_dir / "paper-summary.json").write_text(json.dumps({}))

    # Write summary with mismatched expected hash
    summary_file = phase_dir / "lifecycle-summary.json"
    summary_data = {
        "phase": "phase_296",
        "status": "AUTONOMOUS_LIFECYCLE_VERIFIED",
        "artifact_hashes": {
            "canary-lifecycle-report.json": "0" * 64,  # Intentionally corrupted hash
            "canary-lifecycle-telemetry.sqlite3": hashlib.sha256(b"sqlite dummy").hexdigest(),
            "canary-orders.jsonl": hashlib.sha256(b"{}\n").hexdigest(),
            "paper-summary.json": hashlib.sha256(b"{}").hexdigest(),
        },
    }
    summary_file.write_text(json.dumps(summary_data))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/autonomous-lifecycle")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_autonomous_lifecycle_endpoint_balance_drift_exceeded_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when ledger drift breaches absolute tolerance 10^-15 USDT."""
    phase_dir = tmp_path / "drift_breached_phase"
    phase_dir.mkdir()

    # Create dummy artifacts
    (phase_dir / "canary-lifecycle-telemetry.sqlite3").write_bytes(b"dummy")
    (phase_dir / "canary-orders.jsonl").write_text("{}\n")
    (phase_dir / "paper-summary.json").write_text(json.dumps({}))

    # Create report with excessive drift
    report_payload = {
        "phase": "phase_296",
        "starting_equity_usdt": "100.00",
        "final_cash_usdt": "99.50",
        "drift_usdt": "0.50000000",  # Serious drift breach
        "zero_balance_drift": False,
        "longevity": {},
        "candidates": [],
    }
    report_bytes = json.dumps(report_payload).encode("utf-8")
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    (phase_dir / "canary-lifecycle-report.json").write_bytes(report_bytes)

    summary_payload = {
        "phase": "phase_296",
        "status": "AUTONOMOUS_LIFECYCLE_VERIFIED",
        "drift_usdt": "0.50000000",
        "zero_balance_drift": False,
        "artifact_hashes": {
            "canary-lifecycle-report.json": report_hash,
            "canary-lifecycle-telemetry.sqlite3": hashlib.sha256(b"dummy").hexdigest(),
            "canary-orders.jsonl": hashlib.sha256(b"{}\n").hexdigest(),
            "paper-summary.json": hashlib.sha256(b"{}").hexdigest(),
        },
    }
    (phase_dir / "lifecycle-summary.json").write_text(json.dumps(summary_payload))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/autonomous-lifecycle")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_load_verified_canary_autonomous_lifecycle_direct() -> None:
    """Verify direct Python loader returns valid CanaryAutonomousLifecycleResponse."""
    resp = load_verified_canary_autonomous_lifecycle(PHASE_296_DIR)
    assert isinstance(resp, CanaryAutonomousLifecycleResponse)
    assert resp.phase == "phase_296"
    assert resp.status == "AUTONOMOUS_LIFECYCLE_VERIFIED"
    assert resp.paper_safe is True
    assert resp.execution_authority is False
    assert len(resp.components) == 5
    assert resp.ledger.drift < 1e-15
    assert resp.ledger.zero_balance_drift is True


def test_load_verified_canary_autonomous_lifecycle_default_path() -> None:
    """Verify direct loader defaults cleanly to artifacts/research/phase296."""
    resp = load_verified_canary_autonomous_lifecycle()
    assert isinstance(resp, CanaryAutonomousLifecycleResponse)
    assert resp.phase == "phase_296"
    assert resp.verified is True
    assert len(resp.components) == 5


def test_load_verified_canary_autonomous_lifecycle_missing_raises_not_found(tmp_path: Path) -> None:
    """Verify direct loader raises CanaryEvidenceNotFoundError on missing directory."""
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_autonomous_lifecycle(tmp_path / "non_existent")


def test_load_verified_canary_autonomous_lifecycle_tampered_raises_integrity_error(
    tmp_path: Path,
) -> None:
    """Verify direct loader raises CanaryEvidenceIntegrityError on hash mismatch."""
    phase_dir = tmp_path / "tampered"
    phase_dir.mkdir()
    (phase_dir / "canary-lifecycle-telemetry.sqlite3").write_bytes(b"dummy")
    (phase_dir / "canary-orders.jsonl").write_text("{}\n")
    (phase_dir / "canary-lifecycle-report.json").write_text("corrupted content")
    (phase_dir / "paper-summary.json").write_text("{}")
    (phase_dir / "lifecycle-summary.json").write_text(
        json.dumps(
            {
                "artifact_hashes": {
                    "canary-lifecycle-report.json": "f" * 64,
                }
            }
        )
    )

    with pytest.raises(CanaryEvidenceIntegrityError):
        load_verified_canary_autonomous_lifecycle(phase_dir)


def test_load_verified_canary_autonomous_lifecycle_directory_fallback(
    tmp_path: Path,
) -> None:
    """Verify loader falls back to target_dir.parent / 'phase296'."""
    artifacts_dir = tmp_path / "artifacts" / "research"
    p296_dir = artifacts_dir / "phase296"
    sub_dir = artifacts_dir / "subphase"
    p296_dir.mkdir(parents=True)
    sub_dir.mkdir(parents=True)

    (p296_dir / "canary-lifecycle-telemetry.sqlite3").write_bytes(b"dummy")
    (p296_dir / "canary-orders.jsonl").write_text("{}\n")
    report_content = json.dumps({"drift_usdt": "0.0", "zero_balance_drift": True})
    (p296_dir / "canary-lifecycle-report.json").write_text(report_content)
    (p296_dir / "paper-summary.json").write_text("{}")

    import hashlib

    rep_hash = hashlib.sha256(report_content.encode("utf-8")).hexdigest()
    upstream_h = "1d6e6412f9c2a19dce2625fd3236ebdb9bd6c527959bb33875889a18ee51f005"
    (p296_dir / "lifecycle-summary.json").write_text(
        json.dumps(
            {
                "phase": "phase_296",
                "merkle_root": "a" * 64,
                "upstream_phase_hash": upstream_h,
                "artifact_hashes": {
                    "canary-lifecycle-report.json": rep_hash,
                },
            }
        )
    )

    res = load_verified_canary_autonomous_lifecycle(sub_dir)
    assert res.phase == "phase_296"
    assert res.verified is True
