"""Unit tests for Phase 306 auto-evolution API endpoints and artifact evidence verification."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryAutoEvolutionResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    load_verified_canary_auto_evolution,
)

UPSTREAM_PHASE305_ROOT = "0cbf6a93a5332789d5053f72e7e494b03b48ccd0ff7c62118bb339d5d905aa7c"


def _build_synthetic_phase306_artifacts(
    target_dir: Path,
    *,
    tamper_file: str | None = None,
    upstream_hash: str = UPSTREAM_PHASE305_ROOT,
    zero_drift: bool = True,
    drift_val: str = "0.00",
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite DB
    db_path = target_dir / "canary-evolution-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE autopsies (
            trade_id TEXT PRIMARY KEY,
            candidate_id TEXT,
            symbol TEXT,
            side TEXT,
            entry_price REAL,
            exit_price REAL,
            fill_qty REAL,
            entry_timing_error_bps REAL,
            hawkes_slip_drag_bps REAL,
            adverse_selection_bps REAL,
            realized_edge_bps REAL,
            gross_pnl_usdt REAL,
            fee_cost_usdt REAL,
            net_pnl_usdt REAL,
            cause TEXT,
            timestamp_ms INTEGER
        )
        """
    )
    cur.execute(
        "INSERT INTO autopsies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "tr-btc-001",
            "cand-btcusdt-dcb-002",
            "BTCUSDT",
            "BUY",
            95000.0,
            95250.0,
            0.0001,
            1.05,
            2.98,
            1.0,
            20.19,
            0.025,
            0.005,
            0.02,
            "ORGANIC_ALPHA",
            1710000000000,
        ),
    )
    conn.commit()
    conn.close()

    # 2. Events JSONL
    events_path = target_dir / "canary-evolution-events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event": "TRADE_AUTOPSY",
                "data": {
                    "trade_id": "tr-btc-001",
                    "candidate_id": "cand-btcusdt-dcb-002",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "entry_price": 95000.0,
                    "exit_price": 95250.0,
                    "fill_qty": 0.0001,
                    "entry_timing_error_bps": 1.05,
                    "hawkes_slip_drag_bps": 2.98,
                    "adverse_selection_bps": 1.0,
                    "realized_edge_bps": 20.19,
                    "gross_pnl_usdt": 0.025,
                    "fee_cost_usdt": 0.005,
                    "net_pnl_usdt": 0.02,
                    "cause": "ORGANIC_ALPHA",
                    "timestamp_ms": 1710000000000,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    if tamper_file == "sqlite":
        with open(db_path, "ab") as f:
            f.write(b"TAMPER")

    sqlite_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    events_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()

    if tamper_file == "sqlite_hash":
        sqlite_hash = "deadbeef" * 8

    # 3. Solvency & Performance
    solvency_dict = {
        "starting_equity_usdt": 100.0,
        "cash_balance_usdt": 100.02,
        "allocated_margin_usdt": 0.0,
        "unrealized_pnl_usdt": 0.0,
        "realized_pnl_usdt": 0.02,
        "total_equity_usdt": 100.02,
        "reserve_ratio": 1.0,
        "reserve_adequate": True,
        "drift_usdt": float(drift_val),
        "zero_drift_valid": zero_drift,
        "exposure_within_limit": True,
    }

    perf_dict = {
        "total_autopsies_conducted": 1,
        "autopsy_cause_distribution": {"ORGANIC_ALPHA": 1},
        "mean_entry_timing_error_bps": 1.05,
        "mean_hawkes_slip_drag_bps": 2.98,
        "mean_adverse_selection_bps": 1.0,
        "mean_realized_edge_bps": 20.19,
        "health_tier_distribution": {"ELITE": 1, "HEALTHY": 0, "DEGRADED": 0, "PROBATIONARY": 0},
        "staged_mutations_count": 0,
        "promoted_candidates_count": 0,
        "realized_sharpe_ratio": 3.85,
        "win_rate_pct": 100.0,
        "calmar_ratio": 12.0,
        "max_drawdown_pct": 0.0,
    }

    phase_payload = {
        "phase": "phase_306",
        "upstream_hash": upstream_hash,
        "perf": perf_dict,
        "solvency": solvency_dict,
    }
    phase_hash = hashlib.sha256(
        json.dumps(phase_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    merkle_combined = f"{upstream_hash}:{sqlite_hash}:{events_hash}:{phase_hash}"
    merkle_root = hashlib.sha256(merkle_combined.encode("utf-8")).hexdigest()

    if tamper_file == "merkle_root":
        merkle_root = "badroot" * 8

    summary_payload = {
        "phase": "phase_306",
        "status": "EVOLUTION_VERIFIED",
        "verified": True,
        "paper_safe": True,
        "execution_authority": False,
        "timestamp_utc": "2026-09-23T07:00:00+00:00",
        "timestamp_ms": 1790146800000,
        "upstream_merkle_dag": {"phase_305": upstream_hash},
        "upstream_hash": upstream_hash,
        "phase_hash": phase_hash,
        "merkle_root": merkle_root,
        "artifact_hashes": {
            "sqlite3": sqlite_hash,
            "events_jsonl": events_hash,
        },
        "circuit_state": "NORMAL",
        "performance": perf_dict,
        "solvency": solvency_dict,
        "candidates": ["cand-btcusdt-dcb-002"],
        "autopsies_trace": [
            {
                "trade_id": "tr-btc-001",
                "candidate_id": "cand-btcusdt-dcb-002",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "entry_price": 95000.0,
                "exit_price": 95250.0,
                "fill_qty": 0.0001,
                "entry_timing_error_bps": 1.05,
                "hawkes_slip_drag_bps": 2.98,
                "adverse_selection_bps": 1.0,
                "realized_edge_bps": 20.19,
                "gross_pnl_usdt": 0.025,
                "fee_cost_usdt": 0.005,
                "net_pnl_usdt": 0.02,
                "cause": "ORGANIC_ALPHA",
                "timestamp_ms": 1710000000000,
            }
        ],
        "health_evaluations": {
            "cand-btcusdt-dcb-002": {
                "candidate_id": "cand-btcusdt-dcb-002",
                "symbol": "BTCUSDT",
                "tier": "ELITE",
                "rolling_sharpe": 3.85,
                "win_rate_pct": 100.0,
                "max_drawdown_pct": 0.0,
                "hawkes_resilience_score": 90.0,
                "total_trades": 1,
                "consecutive_losses": 0,
                "needs_mutation": False,
            }
        },
        "mutations_trace": [],
        "shadow_evaluations": [],
    }

    summary_path = target_dir / "evolution-summary.json"
    summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    report_path = target_dir / "canary-evolution-report.json"
    report_path.write_text(
        json.dumps(
            {
                "phase": "phase_306",
                "title": "Phase 306 Auto-Evolution Report",
                "merkle_root": merkle_root,
                "upstream_hash": upstream_hash,
                "summary": summary_payload,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return target_dir


def test_load_verified_canary_auto_evolution_success(tmp_path: Path) -> None:
    """Test loading valid synthetic artifacts succeeds and returns typed response."""
    artifacts_dir = _build_synthetic_phase306_artifacts(tmp_path)
    res = load_verified_canary_auto_evolution(artifacts_dir)

    assert isinstance(res, CanaryAutoEvolutionResponse)
    assert res.verified is True
    assert res.phase == "phase_306"
    assert res.status == "EVOLUTION_VERIFIED"
    assert res.upstream_hash == UPSTREAM_PHASE305_ROOT
    assert len(res.autopsies_trace) == 1
    assert res.solvency.zero_balance_drift_verified is True


def test_load_verified_canary_auto_evolution_missing_evidence(tmp_path: Path) -> None:
    """Test missing artifacts raise CanaryEvidenceNotFoundError."""
    empty_dir = tmp_path / "empty_phase306"
    empty_dir.mkdir()

    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_auto_evolution(empty_dir)


def test_load_verified_canary_auto_evolution_tamper_hash(tmp_path: Path) -> None:
    """Test corrupted SQLite hash raises CanaryEvidenceIntegrityError."""
    artifacts_dir = _build_synthetic_phase306_artifacts(tmp_path, tamper_file="sqlite_hash")

    with pytest.raises(CanaryEvidenceIntegrityError, match="Artifact SHA-256 hash mismatch"):
        load_verified_canary_auto_evolution(artifacts_dir)


def test_load_verified_canary_auto_evolution_upstream_mismatch(tmp_path: Path) -> None:
    """Test upstream hash mismatch raises CanaryEvidenceIntegrityError."""
    artifacts_dir = _build_synthetic_phase306_artifacts(
        tmp_path, upstream_hash="invalid_upstream_root_hash"
    )

    with pytest.raises(CanaryEvidenceIntegrityError, match="Upstream hash mismatch"):
        load_verified_canary_auto_evolution(artifacts_dir)


def test_load_verified_canary_auto_evolution_merkle_mismatch(tmp_path: Path) -> None:
    """Test mismatched Merkle root raises CanaryEvidenceIntegrityError."""
    artifacts_dir = _build_synthetic_phase306_artifacts(tmp_path, tamper_file="merkle_root")

    with pytest.raises(CanaryEvidenceIntegrityError, match="Phase 306 Merkle root mismatch"):
        load_verified_canary_auto_evolution(artifacts_dir)


def test_load_verified_canary_auto_evolution_drift_breach(tmp_path: Path) -> None:
    """Test solvency balance drift breaching 1e-15 USDT raises CanaryEvidenceIntegrityError."""
    artifacts_dir = _build_synthetic_phase306_artifacts(
        tmp_path, zero_drift=False, drift_val="0.0001"
    )

    with pytest.raises(
        CanaryEvidenceIntegrityError, match="Double-entry zero-drift balance invariant breached"
    ):
        load_verified_canary_auto_evolution(artifacts_dir)


def test_api_canary_evolution_endpoint_success(tmp_path: Path) -> None:
    """Test FastAPI GET /api/v1/canary/evolution returns 200 with valid evidence."""
    artifacts_dir = _build_synthetic_phase306_artifacts(tmp_path)
    app = create_app(canary_phase_dir=artifacts_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/evolution")
    assert resp.status_code == 200
    data = resp.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_306"
    assert data["status"] == "EVOLUTION_VERIFIED"
    assert len(data["autopsies_trace"]) == 1


def test_api_canary_evolution_endpoint_not_found(tmp_path: Path) -> None:
    """Test FastAPI GET /api/v1/canary/evolution returns 404 when evidence is missing."""
    empty_dir = tmp_path / "empty_phase306"
    empty_dir.mkdir()
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/evolution")
    assert resp.status_code == 404
    assert "evidence unavailable" in resp.json()["detail"]


def test_api_canary_evolution_endpoint_integrity_failure(tmp_path: Path) -> None:
    """Test FastAPI GET /api/v1/canary/evolution returns 503 on cryptographic failure."""
    artifacts_dir = _build_synthetic_phase306_artifacts(tmp_path, tamper_file="merkle_root")
    app = create_app(canary_phase_dir=artifacts_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/evolution")
    assert resp.status_code == 503
    assert "integrity verification failed" in resp.json()["detail"]
