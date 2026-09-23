"""Unit tests for Phase 302 API endpoints and artifact evidence verification."""

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
    CanaryExecutionGuardResponse,
    load_verified_canary_execution_guard,
)


def _build_synthetic_phase302_artifacts(
    target_dir: Path,
    *,
    tamper_file: str | None = None,
    upstream_hash: str = "64f0c31a6763924339d1737f7ff94923b4eba22f71bb703295a045bb5e16da7a",
    zero_drift: bool = True,
    drift_val: str = "0.00",
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite DB
    db_path = target_dir / "canary-execution-guard-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE execution_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT,
            symbol TEXT,
            timestamp_utc TEXT,
            payload_json TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE shaded_quotes (
            quote_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            unshaded_price REAL,
            shaded_price REAL,
            reservation_price REAL,
            shading_bps REAL,
            action TEXT,
            reason TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO execution_events VALUES (?, ?, ?, ?, ?)",
        ("evt-001", "QUOTE_PULLED", "BTCUSDT", "2026-09-23T01:17:00Z", "{}"),
    )
    cur.execute(
        "INSERT INTO shaded_quotes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "quote-001",
            "BTCUSDT",
            "BUY",
            50150.0,
            50150.0,
            50149.99,
            30.0,
            "PULLED_DEFENSE",
            "Toxic flow runaway defense",
        ),
    )
    conn.commit()
    conn.close()

    # 2. Events JSONL
    events_path = target_dir / "canary-execution-events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event_id": "evt-001",
                "event_type": "QUOTE_PULLED",
                "timestamp_utc": "2026-09-23T01:17:00Z",
                "symbol": "BTCUSDT",
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # 3. Report JSON
    report_path = target_dir / "canary-execution-guard-report.json"
    report_dict = {
        "phase": "phase_302",
        "status": "EXECUTION_GUARD_VERIFIED",
        "upstream_hash": upstream_hash,
        "merkle_root": "5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76",
    }
    report_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")

    # 4. Paper summary JSON
    paper_path = target_dir / "paper-summary.json"
    paper_path.write_text(json.dumps({"phase": "phase_302", "paper_safe": True}), encoding="utf-8")

    # Compute hashes
    db_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    events_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    paper_hash = hashlib.sha256(paper_path.read_bytes()).hexdigest()

    if tamper_file == "db":
        db_hash = "a" * 64
    elif tamper_file == "events":
        events_hash = "b" * 64

    # 5. Summary JSON
    summary_dict = {
        "phase": "phase_302",
        "status": "EXECUTION_GUARD_VERIFIED",
        "timestamp_ms": 1790126252809,
        "timestamp_utc": "2026-09-23T01:17:32.809634+00:00",
        "paper_safe": True,
        "execution_authority": False,
        "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "circuit_state": "NORMAL",
        "toxicity_metrics": [
            {
                "symbol": "BTCUSDT",
                "vpin": 1.0,
                "kyles_lambda": 0.00001,
                "hawkes_spectral_radius": 0.4,
                "risk_state": "TOXIC_RUNAWAY",
                "shading_offset_bps": 25.0,
                "quotes_pulled": True,
            }
        ],
        "shaded_quotes": [
            {
                "quote_id": "quote-001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "unshaded_price": 50150.0,
                "shaded_price": 50150.0,
                "reservation_price": 50149.99,
                "shading_bps": 30.0,
                "action": "PULLED_DEFENSE",
                "reason": "Toxic flow runaway defense",
            }
        ],
        "slippage_decompositions": [
            {
                "order_id": "child-ord-001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "intended_price": 50150.0,
                "fill_price": 50155.0,
                "total_slippage_bps": 1.0,
                "delay_slippage_bps": 0.2,
                "temporary_impact_bps": 0.0,
                "permanent_impact_bps": 0.0,
                "queue_degradation_bps": 0.8,
                "is_maker": True,
                "within_tolerance": True,
            }
        ],
        "child_orders": [
            {
                "order_id": "child-ord-001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "intended_price": 50150.0,
                "executed_price": 50155.0,
                "quantity": 0.0001,
                "notional_usdt": 5.0,
                "fee_usdt": 0.002,
                "slippage_usdt": 0.0005,
                "status": "FILLED",
            }
        ],
        "ledger": {
            "starting_equity": 100.0,
            "cash": 98.5,
            "allocated_margin": 1.5,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "drift": float(drift_val),
            "zero_balance_drift": zero_drift,
        },
        "solvency": {
            "starting_equity_usdt": 100.0,
            "cash_usdt": 98.5,
            "allocated_margin_usdt": 1.5,
            "unrealized_pnl_usdt": 0.0,
            "realized_pnl_usdt": 0.0,
            "total_equity_usdt": 100.0,
            "total_fees_usdt": 0.002,
            "total_slippage_usdt": 0.0005,
            "drift_usdt": float(drift_val),
            "zero_balance_drift_verified": zero_drift,
            "tolerance_ceiling_usdt": 1e-15,
            "solvency_ratio_pct": 100.0,
            "cash_reserve_pct": 98.5,
            "unencumbered_cash_verified": True,
        },
        "upstream_hash": upstream_hash,
        "phase_hash": "a" * 64,
        "merkle_root": (
            "0" * 64
            if tamper_file == "merkle_root"
            else "5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76"
        ),
        "artifact_hashes": {
            "canary-execution-guard-telemetry.sqlite3": db_hash,
            "canary-execution-events.jsonl": events_hash,
            "canary-execution-guard-report.json": report_hash,
            "paper-summary.json": paper_hash,
        },
    }

    summary_path = target_dir / "execution-guard-summary.json"
    summary_path.write_text(json.dumps(summary_dict, indent=2), encoding="utf-8")
    return target_dir


# =====================================================================
# Loader Tests
# =====================================================================


def test_load_verified_canary_execution_guard_live() -> None:
    """Verify loading from the real generated Phase 302 artifact directory."""
    resp = load_verified_canary_execution_guard()
    assert isinstance(resp, CanaryExecutionGuardResponse)
    assert resp.phase == "phase_302"
    assert resp.status == "EXECUTION_GUARD_VERIFIED"
    assert resp.paper_safe is True
    assert resp.execution_authority is False
    assert resp.circuit_state == "NORMAL"
    assert resp.solvency.zero_balance_drift_verified is True
    assert resp.solvency.drift_usdt == 0.0
    assert resp.solvency.unencumbered_cash_verified is True
    assert resp.upstream_hash == "64f0c31a6763924339d1737f7ff94923b4eba22f71bb703295a045bb5e16da7a"
    assert len(resp.toxicity_metrics) > 0
    assert len(resp.shaded_quotes) > 0
    assert len(resp.slippage_decompositions) > 0
    assert len(resp.child_orders) > 0


def test_load_verified_canary_execution_guard_missing_summary(tmp_path: Path) -> None:
    """Verify CanaryEvidenceNotFoundError when summary artifact does not exist."""
    with pytest.raises(CanaryEvidenceNotFoundError, match="Execution guard summary artifact"):
        load_verified_canary_execution_guard(tmp_path)


def test_load_verified_canary_execution_guard_missing_db(tmp_path: Path) -> None:
    """Verify CanaryEvidenceNotFoundError when SQLite telemetry artifact is missing."""
    summary_path = tmp_path / "execution-guard-summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    with pytest.raises(CanaryEvidenceNotFoundError, match="telemetry artifact missing"):
        load_verified_canary_execution_guard(tmp_path)


def test_load_verified_canary_execution_guard_tampered_hash(tmp_path: Path) -> None:
    """Verify CanaryEvidenceIntegrityError when artifact hash fails SHA-256 validation."""
    _build_synthetic_phase302_artifacts(tmp_path, tamper_file="db")
    with pytest.raises(CanaryEvidenceIntegrityError, match="SHA-256 mismatch"):
        load_verified_canary_execution_guard(tmp_path)


def test_load_verified_canary_execution_guard_upstream_mismatch(tmp_path: Path) -> None:
    """Verify CanaryEvidenceIntegrityError when upstream Phase 301 hash does not match."""
    _build_synthetic_phase302_artifacts(tmp_path, upstream_hash="c" * 64)
    with pytest.raises(CanaryEvidenceIntegrityError, match="Upstream hash mismatch"):
        load_verified_canary_execution_guard(tmp_path)


def test_load_verified_canary_execution_guard_merkle_root_invalid(tmp_path: Path) -> None:
    """Verify CanaryEvidenceIntegrityError when Merkle root is invalid."""
    _build_synthetic_phase302_artifacts(tmp_path, tamper_file="merkle_root")
    with pytest.raises(CanaryEvidenceIntegrityError, match="Merkle root mismatch"):
        load_verified_canary_execution_guard(tmp_path)


def test_load_verified_canary_execution_guard_drift_breach(tmp_path: Path) -> None:
    """Verify CanaryEvidenceIntegrityError when double-entry drift exceeds 1e-15 USDT."""
    _build_synthetic_phase302_artifacts(
        tmp_path,
        zero_drift=False,
        drift_val="0.001",
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="zero-drift balance invariant breached"):
        load_verified_canary_execution_guard(tmp_path)


# =====================================================================
# FastAPI Endpoint Tests
# =====================================================================


def test_api_endpoint_200() -> None:
    """Verify GET /api/v1/canary/execution-guard returns 200 with valid schema."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/canary/execution-guard")
    assert response.status_code == 200
    data = response.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_302"
    assert data["status"] == "EXECUTION_GUARD_VERIFIED"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False
    assert data["solvency"]["zero_balance_drift_verified"] is True
    assert (
        data["upstream_hash"] == "64f0c31a6763924339d1737f7ff94923b4eba22f71bb703295a045bb5e16da7a"
    )


def test_api_endpoint_404(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/execution-guard returns 404 when evidence missing."""
    empty_dir = tmp_path / "empty_phase"
    empty_dir.mkdir()
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/execution-guard")
    assert response.status_code == 404
    assert "unavailable" in response.json()["detail"]


def test_api_endpoint_503(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/execution-guard returns 503 when integrity compromised."""
    _build_synthetic_phase302_artifacts(tmp_path, tamper_file="db")
    app = create_app(canary_phase_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/v1/canary/execution-guard")
    assert response.status_code == 503
    assert "verification failed" in response.json()["detail"]
