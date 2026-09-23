"""Unit tests for Phase 305 ensemble API endpoints and artifact evidence verification."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryEnsembleResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    load_verified_canary_ensemble,
)

UPSTREAM_PHASE304_ROOT = "07ffc13325eeffaadd0fb2e2cc60fe15269943f0bfca55fd613289c02a4fb80b"


def _build_synthetic_phase305_artifacts(
    target_dir: Path,
    *,
    tamper_file: str | None = None,
    upstream_hash: str = UPSTREAM_PHASE304_ROOT,
    zero_drift: bool = True,
    drift_val: str = "0.00",
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite DB
    db_path = target_dir / "canary-ensemble-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE ensemble_decisions (
            id INTEGER PRIMARY KEY,
            timestamp_ms INTEGER,
            symbol TEXT,
            regime TEXT,
            micro_weight REAL,
            short_weight REAL,
            medium_weight REAL,
            raw_direction REAL,
            conflict_detected INTEGER,
            conflict_penalty REAL,
            effective_direction REAL,
            effective_conviction REAL,
            target_action TEXT,
            target_micro_chunk_usdt REAL,
            ensemble_state TEXT,
            cash_usdt REAL,
            drift_usdt REAL
        )
        """
    )
    cur.execute(
        "INSERT INTO ensemble_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            1000,
            "BTCUSDT",
            "CALM_BALANCED",
            0.35,
            0.35,
            0.30,
            0.60,
            0,
            1.0,
            0.60,
            0.75,
            "BUY",
            3.50,
            "ENSEMBLE_ACTIVE",
            96.50,
            0.0,
        ),
    )
    conn.commit()
    conn.close()

    # 2. Events JSONL
    events_path = target_dir / "canary-ensemble-events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event": "ENSEMBLE_DECISION_GENERATED",
                "timestamp_ms": 1000,
                "symbol": "BTCUSDT",
                "regime": "CALM_BALANCED",
                "decision": {
                    "symbol": "BTCUSDT",
                    "timestamp_ms": 1000,
                    "regime": "CALM_BALANCED",
                    "weights": {
                        "micro_weight": 0.35,
                        "short_weight": 0.35,
                        "medium_weight": 0.30,
                        "weights_sum": 1.0,
                        "regime": "CALM_BALANCED",
                        "regime_confidence": 0.95,
                    },
                    "signals": {},
                    "raw_blended_direction": 0.60,
                    "raw_blended_conviction": 0.75,
                    "conflict_detected": False,
                    "conflict_penalty": 1.0,
                    "effective_direction": 0.60,
                    "effective_conviction": 0.75,
                    "target_action": "BUY",
                    "target_micro_chunk_usdt": 3.50,
                    "ensemble_state": "ENSEMBLE_ACTIVE",
                    "notes": "",
                },
                "cash_usdt": 96.50,
                "drift_usdt": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # 3. Compute Hashes
    sqlite_bytes = db_path.read_bytes()
    events_bytes = events_path.read_bytes()
    sqlite_hash = hashlib.sha256(sqlite_bytes).hexdigest()
    events_hash = hashlib.sha256(events_bytes).hexdigest()

    solvency_dict = {
        "starting_equity_usdt": 100.0,
        "cash_usdt": 96.50,
        "allocated_margin_usdt": 3.50,
        "unrealized_pnl_usdt": 0.0,
        "realized_pnl_usdt": 0.0,
        "total_equity_usdt": 100.0,
        "total_fees_usdt": 0.0,
        "total_slippage_usdt": 0.0,
        "drift_usdt": float(drift_val),
        "zero_balance_drift_verified": zero_drift,
        "tolerance_ceiling_usdt": 1e-15,
        "solvency_ratio_pct": 100.0,
        "cash_reserve_pct": 96.50,
        "unencumbered_cash_verified": True,
    }

    perf_dict = {
        "total_decisions": 1,
        "conflict_count": 0,
        "conflict_ratio_pct": 0.0,
        "average_effective_conviction": 0.75,
        "mean_horizon_weights": {"micro": 0.35, "short": 0.35, "medium": 0.30},
        "regime_distribution": {"CALM_BALANCED": 1},
        "defense_lockouts_triggered": 0,
        "realized_sharpe_ratio": 1100.0,
        "calmar_ratio": 7000.0,
        "max_drawdown_pct": 0.002,
        "win_rate_pct": 100.0,
        "profit_factor": 20.0,
    }

    phase_payload = {
        "phase": "phase_305",
        "upstream_hash": upstream_hash,
        "perf": perf_dict,
        "solvency": solvency_dict,
    }
    phase_hash = hashlib.sha256(
        json.dumps(phase_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    merkle_combined = f"{upstream_hash}:{sqlite_hash}:{events_hash}:{phase_hash}"
    merkle_root = hashlib.sha256(merkle_combined.encode("utf-8")).hexdigest()

    summary_data = {
        "phase": "phase_305",
        "status": "ENSEMBLE_VERIFIED",
        "verified": True,
        "paper_safe": True,
        "execution_authority": False,
        "timestamp_utc": "2026-09-23T12:00:00+00:00",
        "timestamp_ms": 1790136000000,
        "upstream_hash": upstream_hash,
        "phase_hash": phase_hash,
        "merkle_root": merkle_root,
        "artifact_hashes": {
            "sqlite3": sqlite_hash,
            "events_jsonl": events_hash,
        },
        "circuit_state": "NORMAL",
        "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "performance": perf_dict,
        "shadow_states": {},
        "decisions_trace": [],
        "solvency": solvency_dict,
    }

    summary_path = target_dir / "ensemble-summary.json"
    summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

    report_path = target_dir / "canary-ensemble-report.json"
    report_path.write_text(
        json.dumps({"phase": "phase_305", "summary": summary_data}, indent=2),
        encoding="utf-8",
    )

    if tamper_file == "sqlite":
        db_path.write_bytes(db_path.read_bytes() + b"corrupt")
    elif tamper_file == "events":
        events_path.write_text("corrupted", encoding="utf-8")
    elif tamper_file == "summary_json":
        summary_path.write_text("{corrupt", encoding="utf-8")
    elif tamper_file == "merkle_root":
        summary_data["merkle_root"] = "0" * 64
        summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

    return target_dir


def test_load_verified_canary_ensemble_success(tmp_path: Path) -> None:
    """Verify loading synthetic artifacts succeeds and returns typed response."""
    artifacts_dir = _build_synthetic_phase305_artifacts(tmp_path)
    res = load_verified_canary_ensemble(artifacts_dir)
    assert isinstance(res, CanaryEnsembleResponse)
    assert res.verified is True
    assert res.phase == "phase_305"
    assert res.status == "ENSEMBLE_VERIFIED"
    assert res.paper_safe is True
    assert res.execution_authority is False
    assert res.solvency.drift_usdt < 1e-15


def test_load_verified_canary_ensemble_missing_dir(tmp_path: Path) -> None:
    """Verify missing directory raises CanaryEvidenceNotFoundError."""
    missing_dir = tmp_path / "nonexistent"
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_ensemble(missing_dir)


def test_load_verified_canary_ensemble_hash_tamper(tmp_path: Path) -> None:
    """Verify tampered SQLite fails integrity check."""
    artifacts_dir = _build_synthetic_phase305_artifacts(tmp_path, tamper_file="sqlite")
    with pytest.raises(CanaryEvidenceIntegrityError, match="hash mismatch"):
        load_verified_canary_ensemble(artifacts_dir)


def test_load_verified_canary_ensemble_merkle_tamper(tmp_path: Path) -> None:
    """Verify altered Merkle root fails integrity check."""
    artifacts_dir = _build_synthetic_phase305_artifacts(tmp_path, tamper_file="merkle_root")
    with pytest.raises(CanaryEvidenceIntegrityError, match="Merkle root mismatch"):
        load_verified_canary_ensemble(artifacts_dir)


def test_load_verified_canary_ensemble_drift_breach(tmp_path: Path) -> None:
    """Verify drift exceeding 1e-15 fails integrity check."""
    artifacts_dir = _build_synthetic_phase305_artifacts(
        tmp_path, zero_drift=False, drift_val="0.05"
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="zero-drift balance invariant"):
        load_verified_canary_ensemble(artifacts_dir)


def test_canary_ensemble_api_endpoint(tmp_path: Path) -> None:
    """Verify FastAPI GET /api/v1/canary/ensemble endpoint."""
    artifacts_dir = _build_synthetic_phase305_artifacts(tmp_path)
    app = create_app(canary_phase_dir=artifacts_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/ensemble")
    assert resp.status_code == 200
    data = resp.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_305"
    assert data["status"] == "ENSEMBLE_VERIFIED"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False
    assert data["solvency"]["zero_balance_drift_verified"] is True


def test_canary_ensemble_api_endpoint_404(tmp_path: Path) -> None:
    """Verify 404 when evidence is missing."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/ensemble")
    assert resp.status_code == 404
    assert "unavailable" in resp.json()["detail"]


def test_canary_ensemble_api_endpoint_503(tmp_path: Path) -> None:
    """Verify 503 when integrity is compromised."""
    artifacts_dir = _build_synthetic_phase305_artifacts(tmp_path, tamper_file="sqlite")
    app = create_app(canary_phase_dir=artifacts_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/ensemble")
    assert resp.status_code == 503
    assert "verification failed" in resp.json()["detail"]
