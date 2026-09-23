"""Unit tests for Phase 303 API endpoints and artifact evidence verification."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    CanaryOrchestratorResponse,
    load_verified_canary_orchestrator,
)


def _build_synthetic_phase303_artifacts(
    target_dir: Path,
    *,
    tamper_file: str | None = None,
    upstream_hash: str = "5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76",
    zero_drift: bool = True,
    drift_val: str = "0.00",
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite DB
    db_path = target_dir / "canary-orchestrator-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE orchestrator_events (
            event_id TEXT PRIMARY KEY,
            cycle_id TEXT,
            stage TEXT,
            symbol TEXT,
            timestamp_utc TEXT,
            payload_json TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO orchestrator_events VALUES (?, ?, ?, ?, ?, ?)",
        ("evt-001", "cyc-001", "STAGE_1_INGRESS_SLA", "BTCUSDT", "2026-09-23T02:43:00Z", "{}"),
    )
    conn.commit()
    conn.close()

    # 2. Events JSONL
    events_path = target_dir / "canary-orchestrator-events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event_id": "evt-001",
                "cycle_id": "cyc-001",
                "stage": "STAGE_1_INGRESS_SLA",
                "timestamp_utc": "2026-09-23T02:43:00Z",
                "symbol": "BTCUSDT",
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # 3. Report JSON
    report_path = target_dir / "canary-orchestrator-report.json"
    report_data = {
        "phase": "phase_303",
        "title": "Phase 303 Closed-Loop Orchestrator & Shadow Longevity Report",
        "timestamp_utc": "2026-09-23T02:43:00Z",
        "execution_authority": False,
        "paper_safe": True,
        "upstream_hash": upstream_hash,
        "merkle_root": "a" * 64,
    }
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    # Hashes
    sqlite_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    events_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()

    if tamper_file == "sqlite":
        sqlite_hash = "f" * 64
    elif tamper_file == "report":
        report_hash = "f" * 64

    # 4. Summary JSON
    summary_path = target_dir / "orchestrator-summary.json"
    summary_data = {
        "verified": True,
        "phase": "phase_303",
        "status": "ORCHESTRATOR_VERIFIED",
        "timestamp_ms": 1790131419749,
        "timestamp_utc": "2026-09-23T02:43:00Z",
        "paper_safe": True,
        "execution_authority": False,
        "circuit_state": "NORMAL",
        "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "performance": {
            "total_cycles": 1,
            "completed_cycles": 1,
            "defended_cycles": 0,
            "interlocked_cycles": 0,
            "stale_halted_cycles": 0,
            "realized_sharpe_ratio": 500.0,
            "calmar_ratio": 1000.0,
            "max_drawdown_pct": 0.001,
            "win_rate_pct": 100.0,
            "profit_factor": 1.0,
            "total_gross_pnl_usdt": 0.05,
            "total_fees_usdt": 0.001,
            "total_slippage_usdt": 0.001,
            "total_net_pnl_usdt": 0.048,
            "alpha_attribution_pnl_usdt": 0.05,
            "slippage_drag_pnl_usdt": 0.001,
            "fee_drag_pnl_usdt": 0.001,
        },
        "shadow_states": {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "active_positions_count": 0,
                "allocated_margin_usdt": 0.0,
                "unrealized_pnl_usdt": 0.0,
                "realized_pnl_usdt": 0.0,
                "total_cycles_count": 1,
                "last_vpin": 0.20,
                "last_hawkes_rho": 0.30,
                "last_action": "FILLED",
                "status": "NORMAL",
            }
        },
        "cycles": [],
        "solvency": {
            "starting_equity_usdt": 100.0,
            "cash_usdt": 100.0,
            "allocated_margin_usdt": 0.0,
            "unrealized_pnl_usdt": 0.0,
            "realized_pnl_usdt": 0.0,
            "total_equity_usdt": 100.0,
            "total_fees_usdt": 0.0,
            "total_slippage_usdt": 0.0,
            "drift_usdt": float(drift_val),
            "zero_balance_drift_verified": zero_drift,
            "tolerance_ceiling_usdt": 1e-15,
            "solvency_ratio_pct": 100.0,
            "cash_reserve_pct": 100.0,
            "unencumbered_cash_verified": True,
        },
        "ledger": {
            "starting_equity": 100.0,
            "cash": 100.0,
            "allocated_margin": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "drift": float(drift_val),
            "zero_balance_drift": zero_drift,
        },
        "upstream_hash": upstream_hash,
        "phase_hash": "b" * 64,
        "merkle_root": "c" * 64,
        "artifact_hashes": {
            "canary-orchestrator-telemetry.sqlite3": sqlite_hash,
            "canary-orchestrator-events.jsonl": events_hash,
            "canary-orchestrator-report.json": report_hash,
        },
    }
    summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

    return target_dir


# =====================================================================
# Evidence Verification Tests
# =====================================================================


def test_load_live_canary_orchestrator_evidence() -> None:
    """Verify loading real Phase 303 artifacts generated in artifacts/research/phase303."""
    response = load_verified_canary_orchestrator()

    assert isinstance(response, CanaryOrchestratorResponse)
    assert response.verified is True
    assert response.phase == "phase_303"
    assert response.status == "ORCHESTRATOR_VERIFIED"
    assert response.paper_safe is True
    assert response.execution_authority is False
    assert response.circuit_state == "NORMAL"
    assert response.candidates == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    # Check cryptographic root
    assert len(response.merkle_root) == 64
    assert response.upstream_hash == (
        "5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76"
    )

    # Check zero-drift solvency invariant
    assert response.solvency.zero_balance_drift_verified is True
    assert response.solvency.drift_usdt == 0.0
    assert response.ledger.zero_balance_drift is True

    # Check performance and cycles
    assert response.performance.total_cycles >= 3
    assert len(response.cycles) >= 3


def test_load_orchestrator_missing_dir(tmp_path: Path) -> None:
    """Verify CanaryEvidenceNotFoundError raised when directory does not exist."""
    non_existent = tmp_path / "non_existent_phase303"
    with pytest.raises(CanaryEvidenceNotFoundError, match="Orchestrator summary artifact missing"):
        load_verified_canary_orchestrator(non_existent)


def test_load_orchestrator_tampered_hash(tmp_path: Path) -> None:
    """Verify CanaryEvidenceIntegrityError raised when artifact hash mismatches."""
    target_dir = _build_synthetic_phase303_artifacts(tmp_path / "tampered", tamper_file="sqlite")
    with pytest.raises(CanaryEvidenceIntegrityError, match="SHA-256 mismatch"):
        load_verified_canary_orchestrator(target_dir)


def test_load_orchestrator_upstream_hash_mismatch(tmp_path: Path) -> None:
    """Verify CanaryEvidenceIntegrityError raised when Phase 302 root mismatch."""
    target_dir = _build_synthetic_phase303_artifacts(
        tmp_path / "bad_upstream",
        upstream_hash="0" * 64,
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="Upstream hash mismatch"):
        load_verified_canary_orchestrator(target_dir)


def test_load_orchestrator_solvency_drift_breach(tmp_path: Path) -> None:
    """Verify CanaryEvidenceIntegrityError raised when double-entry drift exceeds 1e-15."""
    target_dir = _build_synthetic_phase303_artifacts(
        tmp_path / "drift_breach",
        zero_drift=False,
        drift_val="0.05",
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="zero-drift balance invariant"):
        load_verified_canary_orchestrator(target_dir)


# =====================================================================
# FastAPI Endpoint Tests
# =====================================================================


def test_api_canary_orchestrator_endpoint_success() -> None:
    """Verify GET /api/v1/canary/orchestrator returns 200 with valid schema."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/canary/orchestrator")
    assert response.status_code == 200
    data = response.json()

    assert data["verified"] is True
    assert data["phase"] == "phase_303"
    assert data["status"] == "ORCHESTRATOR_VERIFIED"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False
    assert len(data["candidates"]) == 3
    assert "performance" in data
    assert "shadow_states" in data
    assert "cycles" in data
    assert "solvency" in data
    assert data["solvency"]["zero_balance_drift_verified"] is True


def test_api_canary_orchestrator_endpoint_404_on_missing(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/orchestrator returns 404 when evidence is missing."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir(parents=True)
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/orchestrator")
    assert response.status_code == 404
    assert "unavailable" in response.json()["detail"]


def test_api_canary_orchestrator_endpoint_503_on_integrity_error(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/orchestrator returns 503 when integrity is compromised."""
    tampered_dir = _build_synthetic_phase303_artifacts(
        tmp_path / "api_tampered", tamper_file="report"
    )
    app = create_app(canary_phase_dir=tampered_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/orchestrator")
    assert response.status_code == 503
    assert "integrity verification failed" in response.json()["detail"]
