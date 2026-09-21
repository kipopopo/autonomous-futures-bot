"""Unit tests for Phase 297 Stress Fault Injection FastAPI endpoint and loader.

Tests cover:
- 200 OK nominal endpoint response with full schema and invariant validation.
- 404 Not Found error mapping for missing evidence directory or artifacts.
- 503 Service Unavailable error mapping for tampered SHA-256 hashes or balance drift breaches.
- Direct loader validation of Merkle DAG integrity, sub-ms breaker latencies, and zero drift.
- Summary endpoint compatibility with Phase 297 stress summary manifests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    CanaryStressFaultInjectionResponse,
    load_verified_canary_stress_fault_injection,
    load_verified_canary_summary,
)

PHASE_297_DIR = Path("artifacts/research/phase297")


def test_stress_fault_injection_endpoint_nominal_200_ok() -> None:
    """Verify GET /api/v1/canary/stress-fault-injection returns 200 OK with valid contract."""
    app = create_app(canary_phase_dir=PHASE_297_DIR)
    client = TestClient(app)

    res = client.get("/api/v1/canary/stress-fault-injection")
    assert res.status_code == 200

    data = res.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_297"
    assert data["status"] == "STRESS_FAULT_INJECTION_VERIFIED"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False
    assert data["circuit_state"] == "HALTED"

    # Validate 4 Calibrated Shock Vectors
    assert len(data["shock_vectors"]) >= 4
    vector_names = {v["name"] for v in data["shock_vectors"]}
    assert "Flash Crash Shock" in vector_names
    assert "Liquidity Evaporation & Wide Spread" in vector_names
    assert "Phantom Depth / Spoofing & Toxic Flow" in vector_names
    assert "Telemetry Degradation & Clock Skew" in vector_names

    # Validate Circuit Breaker Reaction Latencies (< 1 ms requirement)
    assert len(data["circuit_breaker_latencies"]) >= 1
    for cb in data["circuit_breaker_latencies"]:
        assert cb["sub_millisecond"] is True
        assert cb["detection_latency_us"] < 1000.0
        assert cb["tripped"] is True

    # Validate Auto-Flattening Audit Items
    assert len(data["auto_flattening_audits"]) >= 3
    for audit in data["auto_flattening_audits"]:
        assert audit["pre_flatten_equity_usdt"] == 100.0
        assert audit["capital_preserved_pct"] >= 93.0
        assert audit["execution_authority"] is False

    # Validate Capital Preservation Stats
    cap_stats = data["capital_preservation_stats"]
    assert cap_stats["pre_flatten_equity_usdt"] == 100.0
    assert cap_stats["post_flatten_cash_usdt"] >= 93.0
    assert cap_stats["capital_preserved_pct"] >= 93.0
    assert cap_stats["max_loss_budget_usdt"] == 7.00
    assert cap_stats["actual_loss_usdt"] <= 7.00
    assert cap_stats["loss_ceiling_breached"] is False
    assert cap_stats["circuit_state"] == "HALTED"

    # Validate Double-Entry Ledger Reconciliation
    ledger = data["ledger"]
    assert ledger["starting_equity"] == 100.0
    assert ledger["cash"] >= 93.0
    assert abs(ledger["drift"]) < 1e-15
    assert ledger["zero_balance_drift"] is True

    # Validate Double-Entry Solvency Item
    solvency = data["solvency"]
    assert solvency["starting_equity_usdt"] == 100.0
    assert solvency["cash_usdt"] >= 93.0
    assert abs(solvency["drift_usdt"]) < 1e-15
    assert solvency["zero_balance_drift_verified"] is True
    assert solvency["cash_reserve_pct"] >= 40.0
    assert solvency["unencumbered_cash_verified"] is True

    # Validate Cryptographic SHA-256 Merkle DAG hashes
    assert len(data["phase_hash"]) == 64
    assert len(data["upstream_hash"]) == 64
    assert len(data["merkle_root"]) == 64


def test_stress_fault_injection_endpoint_missing_dir_fails_404(tmp_path: Path) -> None:
    """Verify endpoint returns 404 when evidence directory does not exist."""
    missing_dir = tmp_path / "non_existent_phase297"
    app = create_app(canary_phase_dir=missing_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/stress-fault-injection")
    assert res.status_code == 404
    assert "unavailable" in res.json()["detail"]


def test_stress_fault_injection_endpoint_missing_artifact_fails_404(tmp_path: Path) -> None:
    """Verify endpoint returns 404 when any required artifact is missing."""
    phase_dir = tmp_path / "incomplete_phase297"
    phase_dir.mkdir()
    # Create only summary, but missing sqlite3, jsonl, etc.
    (phase_dir / "stress-summary.json").write_text(json.dumps({"phase": "phase_297"}))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/stress-fault-injection")
    assert res.status_code == 404
    assert "unavailable" in res.json()["detail"]


def test_stress_fault_injection_endpoint_tampered_hash_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when an artifact hash does not match summary."""
    phase_dir = tmp_path / "tampered_phase297"
    phase_dir.mkdir()

    (phase_dir / "canary-stress-telemetry.sqlite3").write_bytes(b"sqlite dummy")
    (phase_dir / "canary-orders.jsonl").write_text("{}\n")
    report_file = phase_dir / "canary-stress-report.json"
    report_file.write_text(json.dumps({"drift_usdt": "0.0", "zero_balance_drift": True}))
    (phase_dir / "paper-summary.json").write_text(json.dumps({}))

    summary_file = phase_dir / "stress-summary.json"
    summary_data = {
        "phase": "phase_297",
        "status": "STRESS_FAULT_INJECTION_VERIFIED",
        "artifact_hashes": {
            "canary-stress-report.json": "0" * 64,  # Corrupted hash
            "canary-stress-telemetry.sqlite3": hashlib.sha256(b"sqlite dummy").hexdigest(),
            "canary-orders.jsonl": hashlib.sha256(b"{}\n").hexdigest(),
            "paper-summary.json": hashlib.sha256(b"{}").hexdigest(),
        },
    }
    summary_file.write_text(json.dumps(summary_data))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/stress-fault-injection")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_stress_fault_injection_endpoint_balance_drift_exceeded_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when ledger drift breaches tolerance |drift| < 10^-15 USDT."""
    phase_dir = tmp_path / "drift_breached_phase297"
    phase_dir.mkdir()

    (phase_dir / "canary-stress-telemetry.sqlite3").write_bytes(b"dummy")
    (phase_dir / "canary-orders.jsonl").write_text("{}\n")
    (phase_dir / "paper-summary.json").write_text(json.dumps({}))

    report_payload = {
        "phase": "phase_297",
        "starting_equity_usdt": "100.00",
        "final_cash_usdt": "99.50",
        "drift_usdt": "0.50000000",
        "zero_balance_drift": False,
        "circuit_breaker_latencies": {},
        "fault_injection_stats": {},
        "order_execution_stats": {},
    }
    report_bytes = json.dumps(report_payload).encode("utf-8")
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    (phase_dir / "canary-stress-report.json").write_bytes(report_bytes)

    summary_payload = {
        "phase": "phase_297",
        "status": "STRESS_FAULT_INJECTION_VERIFIED",
        "drift_usdt": "0.50000000",
        "zero_balance_drift": False,
        "artifact_hashes": {
            "canary-stress-report.json": report_hash,
            "canary-stress-telemetry.sqlite3": hashlib.sha256(b"dummy").hexdigest(),
            "canary-orders.jsonl": hashlib.sha256(b"{}\n").hexdigest(),
            "paper-summary.json": hashlib.sha256(b"{}").hexdigest(),
        },
    }
    (phase_dir / "stress-summary.json").write_text(json.dumps(summary_payload))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/stress-fault-injection")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_load_verified_canary_stress_fault_injection_direct() -> None:
    """Verify direct Python loader returns valid CanaryStressFaultInjectionResponse."""
    resp = load_verified_canary_stress_fault_injection(PHASE_297_DIR)
    assert isinstance(resp, CanaryStressFaultInjectionResponse)
    assert resp.phase == "phase_297"
    assert resp.status == "STRESS_FAULT_INJECTION_VERIFIED"
    assert resp.paper_safe is True
    assert resp.execution_authority is False
    assert resp.circuit_state == "HALTED"
    assert len(resp.shock_vectors) >= 4
    assert resp.ledger.drift < 1e-15
    assert resp.ledger.zero_balance_drift is True
    assert resp.solvency.zero_balance_drift_verified is True


def test_load_verified_canary_stress_fault_injection_default_path() -> None:
    """Verify direct loader defaults cleanly to artifacts/research/phase297."""
    resp = load_verified_canary_stress_fault_injection()
    assert isinstance(resp, CanaryStressFaultInjectionResponse)
    assert resp.phase == "phase_297"
    assert resp.verified is True
    assert len(resp.shock_vectors) >= 4


def test_load_verified_canary_stress_fault_injection_missing_raises_not_found(
    tmp_path: Path,
) -> None:
    """Verify direct loader raises CanaryEvidenceNotFoundError on missing directory."""
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_stress_fault_injection(tmp_path / "non_existent")


def test_load_verified_canary_stress_fault_injection_tampered_raises_integrity_error(
    tmp_path: Path,
) -> None:
    """Verify direct loader raises CanaryEvidenceIntegrityError on hash mismatch."""
    phase_dir = tmp_path / "tampered"
    phase_dir.mkdir()
    (phase_dir / "canary-stress-telemetry.sqlite3").write_bytes(b"dummy")
    (phase_dir / "canary-orders.jsonl").write_text("{}\n")
    (phase_dir / "canary-stress-report.json").write_text("corrupted content")
    (phase_dir / "paper-summary.json").write_text("{}")
    (phase_dir / "stress-summary.json").write_text(
        json.dumps(
            {
                "artifact_hashes": {
                    "canary-stress-report.json": "f" * 64,
                }
            }
        )
    )

    with pytest.raises(CanaryEvidenceIntegrityError):
        load_verified_canary_stress_fault_injection(phase_dir)


def test_load_verified_canary_stress_fault_injection_directory_fallback(
    tmp_path: Path,
) -> None:
    """Verify loader falls back to target_dir.parent / 'phase297'."""
    artifacts_dir = tmp_path / "artifacts" / "research"
    p297_dir = artifacts_dir / "phase297"
    sub_dir = artifacts_dir / "subphase"
    p297_dir.mkdir(parents=True)
    sub_dir.mkdir(parents=True)

    (p297_dir / "canary-stress-telemetry.sqlite3").write_bytes(b"dummy")
    (p297_dir / "canary-orders.jsonl").write_text("{}\n")
    report_content = json.dumps({"drift_usdt": "0.0", "zero_balance_drift": True})
    (p297_dir / "canary-stress-report.json").write_text(report_content)
    (p297_dir / "paper-summary.json").write_text("{}")

    rep_hash = hashlib.sha256(report_content.encode("utf-8")).hexdigest()
    upstream_h = "aadff07fae3505f6f2b7f57519dc4d322a1d9d913d697be02354dea3b0c5c718"
    (p297_dir / "stress-summary.json").write_text(
        json.dumps(
            {
                "phase": "phase_297",
                "merkle_root": "a" * 64,
                "upstream_merkle_dag": {"phase296_summary_hash": upstream_h},
                "artifact_hashes": {
                    "canary-stress-report.json": rep_hash,
                },
            }
        )
    )

    res = load_verified_canary_stress_fault_injection(sub_dir)
    assert res.phase == "phase_297"
    assert res.verified is True


def test_canary_summary_recognizes_phase297() -> None:
    """Verify GET /api/v1/canary/summary transparently recognizes phase297 summary."""
    summary_direct = load_verified_canary_summary(PHASE_297_DIR)
    assert summary_direct.phase == "phase_297"

    app = create_app(canary_phase_dir=PHASE_297_DIR)
    client = TestClient(app)

    res = client.get("/api/v1/canary/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["phase"] == "phase_297"
    assert data["daemon_status"] == "STRESS_FAULT_INJECTION_VERIFIED"
    assert data["circuit_state"] == "HALTED"
