"""Unit tests for Phase 309 Production Launch API and Cryptographic Evidence Loader."""

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
    load_verified_canary_production_launch,
)

PHASE_308_PARENT_MERKLE_ROOT = "65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e"


def _build_synthetic_phase309_artifacts(
    target_dir: Path,
    upstream_hash: str = PHASE_308_PARENT_MERKLE_ROOT,
    tamper_file: str | None = None,
    tamper_merkle: bool = False,
    tamper_drift: bool = False,
) -> dict[str, Any]:
    """Helper to generate valid cryptographic Phase 309 artifacts for testing."""
    target_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = target_dir / "canary-production-telemetry.sqlite3"
    events_path = target_dir / "canary-production-events.jsonl"
    report_path = target_dir / "canary-production-report.json"
    execution_path = target_dir / "canary-production-execution.json"
    summary_path = target_dir / "production-summary.json"

    # SQLite3 database
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE production_trades (order_id TEXT, symbol TEXT)")
    cur.execute("INSERT INTO production_trades VALUES ('ord-01', 'BTCUSDT')")
    conn.commit()
    conn.close()

    # Events JSONL
    evt_record = {
        "event_id": "prod-evt-0001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 0.00006,
        "price": 95000.0,
        "notional_usdt": 5.70,
        "timestamp_ms": 1790200000000,
    }
    with open(events_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(evt_record) + "\n")

    # Execution JSON
    exec_record = {
        "phase": "phase_309",
        "total_dispatched": 1,
        "total_filled": 1,
        "total_cancelled": 0,
    }
    with open(execution_path, "w", encoding="utf-8") as f:
        json.dump(exec_record, f)

    # Hash computation
    if tamper_file == "sqlite":
        sqlite_bytes = sqlite_path.read_bytes() + b"tamper"
    else:
        sqlite_bytes = sqlite_path.read_bytes()
    sqlite_hash = hashlib.sha256(sqlite_bytes).hexdigest()

    events_bytes = events_path.read_bytes()
    events_hash = hashlib.sha256(events_bytes).hexdigest()

    exec_bytes = execution_path.read_bytes()
    exec_hash = hashlib.sha256(exec_bytes).hexdigest()

    drift_val = 0.05 if tamper_drift else 0.0

    solvency_dict = {
        "starting_equity": 100.0,
        "cash": 100.0,
        "allocated_margin": 0.0,
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "total_equity": 100.0,
        "total_fees": 0.0,
        "total_slippage": 0.0,
        "drift": drift_val,
        "zero_balance_drift": not tamper_drift,
        "solvency_ratio_pct": 100.0,
        "cash_reserve_pct": 100.0,
        "unencumbered_cash_verified": True,
    }

    confinement_dict = {
        "max_micro_order_notional_usdt": 5.0,
        "max_aggregate_exposure_usdt": 25.0,
        "min_cash_reserve_pct": 75.0,
        "intra_day_loss_ceiling_usdt": 3.0,
        "intra_day_loss_observed_usdt": 0.0,
    }

    order_dict = {
        "order_id": "ord-01",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "order_type": "LIMIT",
        "price": 95000.0,
        "quantity": 0.00006,
        "notional_usdt": 5.70,
        "status": "FILLED",
        "fill_price": 95000.0,
        "fee_usdt": 0.002,
        "realized_pnl_usdt": 0.0,
        "timestamp_ms": 1790200000000,
    }

    candidate_dict = {
        "symbol": "BTCUSDT",
        "current_price": 95000.0,
        "position_qty": 0.0,
        "entry_price": 0.0,
        "allocated_exposure_usdt": 0.0,
        "unrealized_pnl_usdt": 0.0,
        "realized_pnl_usdt": 0.0,
        "total_fees_usdt": 0.002,
        "trades_count": 1,
    }

    report_dict = {
        "phase": "phase_309",
        "status": "PRODUCTION_LAUNCH_VERIFIED",
        "timestamp_ms": 1790200000000,
        "candidates": [candidate_dict],
        "orders": [order_dict],
        "confinement": confinement_dict,
        "solvency": solvency_dict,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f)

    report_bytes = report_path.read_bytes()
    report_hash = hashlib.sha256(report_bytes).hexdigest()

    combined_payload = (
        f"phase_309:{upstream_hash}:{sqlite_hash}:{events_hash}:"
        f"{report_hash}:{exec_hash}:{drift_val}"
    )
    phase_hash = hashlib.sha256(combined_payload.encode()).hexdigest()

    if tamper_merkle:
        merkle_root = "bad" * 16
    else:
        merkle_root = hashlib.sha256(f"{upstream_hash}:{phase_hash}".encode()).hexdigest()

    summary_dict = {
        "phase": "phase_309",
        "verified": True,
        "status": "PRODUCTION_LAUNCH_VERIFIED",
        "timestamp_utc": "2026-09-23T08:00:00+00:00",
        "paper_safe": True,
        "execution_authority": False,
        "engine_state": "MICRO_CAPITAL_ACTIVE",
        "total_orders": 1,
        "total_trades": 1,
        "interlock_blocks_count": 0,
        "intra_day_loss_usdt": 0.0,
        "aggregate_exposure_usdt": 0.0,
        "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "solvency": solvency_dict,
        "upstream_hash": upstream_hash,
        "phase_hash": phase_hash,
        "merkle_root": merkle_root,
        "artifact_hashes": {
            "sqlite3": sqlite_hash,
            "events_jsonl": events_hash,
            "report_json": report_hash,
            "execution_json": exec_hash,
        },
        "upstream_merkle_dag": {"phase_308": upstream_hash},
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f)

    return summary_dict


def test_load_verified_canary_production_launch_real_artifacts() -> None:
    phase309_dir = Path("artifacts/research/phase309")
    if not phase309_dir.exists():
        pytest.skip("Phase 309 real artifacts directory not found")

    res = load_verified_canary_production_launch(phase309_dir)
    assert res.verified
    assert res.phase == "phase_309"
    assert res.status == "PRODUCTION_LAUNCH_VERIFIED"
    assert res.paper_safe
    assert not res.execution_authority
    assert res.engine_state == "MICRO_CAPITAL_ACTIVE"
    assert res.solvency.zero_balance_drift_verified
    assert abs(res.solvency.drift_usdt) < 1e-15
    assert res.merkle_root == "5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844"
    assert res.upstream_hash == PHASE_308_PARENT_MERKLE_ROOT
    assert len(res.candidate_allocations) == 3
    assert len(res.recent_orders) > 0


def test_load_verified_canary_production_launch_success(tmp_path: Path) -> None:
    _build_synthetic_phase309_artifacts(tmp_path)
    res = load_verified_canary_production_launch(tmp_path)

    assert res.verified
    assert res.phase == "phase_309"
    assert res.status == "PRODUCTION_LAUNCH_VERIFIED"
    assert res.paper_safe
    assert not res.execution_authority
    assert res.engine_state == "MICRO_CAPITAL_ACTIVE"
    assert res.solvency.zero_balance_drift_verified
    assert abs(res.solvency.drift_usdt) < 1e-15
    assert len(res.candidate_allocations) == 1
    assert len(res.recent_orders) == 1


def test_load_verified_canary_production_launch_missing_evidence(tmp_path: Path) -> None:
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_production_launch(tmp_path)


def test_load_verified_canary_production_launch_tamper_hash(tmp_path: Path) -> None:
    _build_synthetic_phase309_artifacts(tmp_path, tamper_file="sqlite")
    with pytest.raises(CanaryEvidenceIntegrityError, match="Artifact SHA-256 hash mismatch"):
        load_verified_canary_production_launch(tmp_path)


def test_load_verified_canary_production_launch_upstream_mismatch(tmp_path: Path) -> None:
    _build_synthetic_phase309_artifacts(tmp_path, upstream_hash="bad" * 16)
    with pytest.raises(CanaryEvidenceIntegrityError, match="Upstream hash mismatch"):
        load_verified_canary_production_launch(tmp_path)


def test_load_verified_canary_production_launch_merkle_mismatch(tmp_path: Path) -> None:
    _build_synthetic_phase309_artifacts(tmp_path, tamper_merkle=True)
    with pytest.raises(CanaryEvidenceIntegrityError, match="Phase 309 Merkle root mismatch"):
        load_verified_canary_production_launch(tmp_path)


def test_load_verified_canary_production_launch_drift_breach(tmp_path: Path) -> None:
    _build_synthetic_phase309_artifacts(tmp_path, tamper_drift=True)
    with pytest.raises(
        CanaryEvidenceIntegrityError, match="Double-entry zero-drift balance invariant breached"
    ):
        load_verified_canary_production_launch(tmp_path)


def test_api_canary_production_launch_endpoint_real_artifacts() -> None:
    phase309_dir = Path("artifacts/research/phase309")
    if not phase309_dir.exists():
        pytest.skip("Phase 309 real artifacts directory not found")

    app = create_app(canary_phase_dir=phase309_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/production-launch")
    assert response.status_code == 200
    data = response.json()
    assert data["verified"]
    assert data["phase"] == "phase_309"
    assert data["status"] == "PRODUCTION_LAUNCH_VERIFIED"
    assert data["engine_state"] == "MICRO_CAPITAL_ACTIVE"
    assert data["solvency"]["zero_balance_drift_verified"]
    assert data["merkle_root"] == "5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844"


def test_api_canary_production_launch_endpoint_synthetic_success(tmp_path: Path) -> None:
    _build_synthetic_phase309_artifacts(tmp_path)
    app = create_app(canary_phase_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/v1/canary/production-launch")
    assert response.status_code == 200
    data = response.json()
    assert data["verified"]
    assert data["phase"] == "phase_309"
    assert data["status"] == "PRODUCTION_LAUNCH_VERIFIED"
    assert data["engine_state"] == "MICRO_CAPITAL_ACTIVE"


def test_api_canary_production_launch_endpoint_not_found(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_phase"
    empty_dir.mkdir()
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/production-launch")
    assert response.status_code == 404
    assert response.json()["detail"] == "canary production launch evidence unavailable"


def test_api_canary_production_launch_endpoint_integrity_failure(tmp_path: Path) -> None:
    _build_synthetic_phase309_artifacts(tmp_path, tamper_merkle=True)
    app = create_app(canary_phase_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/v1/canary/production-launch")
    assert response.status_code == 503
    assert response.json()["detail"] == "canary production launch integrity verification failed"
