"""Unit tests for Phase 295 Strategy Activation FastAPI endpoint and loader.

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
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    CanaryStrategyActivationResponse,
    load_verified_canary_strategy_activation,
)

PHASE_295_DIR = Path("artifacts/research/phase295")


def test_strategy_activation_endpoint_nominal_200_ok() -> None:
    """Verify GET /api/v1/canary/strategy-activation returns 200 OK with valid contract."""
    app = create_app(canary_phase_dir=PHASE_295_DIR)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-activation")
    assert res.status_code == 200

    data = res.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_295"
    assert data["status"] == "STRATEGY_ACTIVATION_VERIFIED"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False

    # Validate candidate scorecards
    assert len(data["candidates"]) == 3
    cand_map = {c["symbol"]: c for c in data["candidates"]}
    assert "BTCUSDT" in cand_map
    assert "ETHUSDT" in cand_map
    assert "SOLUSDT" in cand_map

    for _sym, cand in cand_map.items():
        assert cand["status"] == "PROMOTED"
        assert cand["qualified"] is True
        assert cand["average_return_pct"] >= 0.0
        assert cand["worst_drawdown_pct"] <= 15.0
        assert cand["profit_factor"] >= 1.05
        assert cand["trade_count"] >= 5
        assert cand["window_count"] >= 1

    # Validate double-entry ledger & zero drift
    ledger = data["ledger"]
    assert ledger["starting_equity"] == 100.0
    assert ledger["cash"] > 0.0
    assert abs(ledger["drift"]) < 1e-15
    assert ledger["zero_balance_drift"] is True

    # Validate fail-closed veto indicators
    vetoes = data["vetoes"]
    assert vetoes["hawkes_supercritical"] is False
    assert vetoes["gateway_heartbeat_stale"] is False
    assert vetoes["margin_headroom_breach"] is False

    # Validate SHA-256 Merkle DAG hashes
    assert len(data["phase_hash"]) == 64
    assert len(data["upstream_hash"]) == 64
    assert data["child_orders_count"] >= 3


def test_strategy_activation_endpoint_missing_dir_fails_404(tmp_path: Path) -> None:
    """Verify endpoint returns 404 when evidence directory does not exist."""
    missing_dir = tmp_path / "non_existent_phase295"
    app = create_app(canary_phase_dir=missing_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-activation")
    assert res.status_code == 404
    assert "unavailable" in res.json()["detail"]


def test_strategy_activation_endpoint_missing_summary_fails_404(tmp_path: Path) -> None:
    """Verify endpoint returns 404 when summary file is missing."""
    empty_dir = tmp_path / "empty_phase295"
    empty_dir.mkdir()
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-activation")
    assert res.status_code == 404
    assert "unavailable" in res.json()["detail"]


def test_strategy_activation_endpoint_tampered_hash_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when an artifact hash does not match summary."""
    phase_dir = tmp_path / "tampered_phase"
    phase_dir.mkdir()

    # Create dummy report
    report_file = phase_dir / "canary-strategy-activation-report.json"
    report_file.write_text(json.dumps({"drift_usdt": "0.0", "zero_balance_drift": True}))

    # Write summary with mismatched expected hash
    summary_file = phase_dir / "strategy-activation-summary.json"
    summary_data = {
        "phase": "phase_295",
        "status": "STRATEGY_ACTIVATION_VERIFIED",
        "artifact_hashes": {
            "canary-strategy-activation-report.json": "0" * 64,  # Intentionally corrupted hash
        },
    }
    summary_file.write_text(json.dumps(summary_data))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-activation")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_strategy_activation_endpoint_balance_drift_exceeded_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when ledger drift breaches absolute tolerance 10^-15 USDT."""
    phase_dir = tmp_path / "drift_breached_phase"
    phase_dir.mkdir()

    # Create report with excessive drift
    report_payload = {
        "phase": "phase_295",
        "starting_equity_usdt": "100.00",
        "final_cash_usdt": "99.50",
        "drift_usdt": "0.50000000",  # Serious drift breach
        "zero_balance_drift": False,
        "candidates": [],
    }
    report_bytes = json.dumps(report_payload).encode("utf-8")
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    (phase_dir / "canary-strategy-activation-report.json").write_bytes(report_bytes)

    summary_payload = {
        "phase": "phase_295",
        "status": "STRATEGY_ACTIVATION_VERIFIED",
        "drift_usdt": "0.50000000",
        "zero_balance_drift": False,
        "artifact_hashes": {
            "canary-strategy-activation-report.json": report_hash,
        },
    }
    (phase_dir / "strategy-activation-summary.json").write_text(json.dumps(summary_payload))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-activation")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_load_verified_canary_strategy_activation_direct() -> None:
    """Verify direct Python loader returns valid CanaryStrategyActivationResponse."""
    resp = load_verified_canary_strategy_activation(PHASE_295_DIR)
    assert isinstance(resp, CanaryStrategyActivationResponse)
    assert resp.phase == "phase_295"
    assert resp.status == "STRATEGY_ACTIVATION_VERIFIED"
    assert resp.paper_safe is True
    assert resp.execution_authority is False
    assert len(resp.candidates) == 3
    assert resp.ledger.drift < 1e-15
    assert resp.ledger.zero_balance_drift is True


def test_load_verified_canary_strategy_activation_default_path() -> None:
    """Verify direct loader defaults cleanly to artifacts/research/phase295."""
    resp = load_verified_canary_strategy_activation()
    assert isinstance(resp, CanaryStrategyActivationResponse)
    assert resp.phase == "phase_295"
    assert len(resp.candidates) == 3


def test_load_verified_canary_strategy_activation_missing_raises_not_found(tmp_path: Path) -> None:
    """Verify direct loader raises CanaryEvidenceNotFoundError on missing files."""
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_strategy_activation(tmp_path / "non_existent")


def test_load_verified_canary_strategy_activation_tampered_raises_integrity_error(
    tmp_path: Path,
) -> None:
    """Verify direct loader raises CanaryEvidenceIntegrityError on hash mismatch."""
    phase_dir = tmp_path / "tampered"
    phase_dir.mkdir()
    (phase_dir / "canary-strategy-activation-report.json").write_text("corrupted content")
    (phase_dir / "strategy-activation-summary.json").write_text(
        json.dumps(
            {
                "artifact_hashes": {
                    "canary-strategy-activation-report.json": "f" * 64,
                }
            }
        )
    )

    with pytest.raises(CanaryEvidenceIntegrityError):
        load_verified_canary_strategy_activation(phase_dir)
