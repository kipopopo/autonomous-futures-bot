"""Unit tests for Phase 304 calibration API endpoints and artifact evidence verification."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryCalibrationResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    load_verified_canary_calibration,
)


def _build_synthetic_phase304_artifacts(
    target_dir: Path,
    *,
    tamper_file: str | None = None,
    upstream_hash: str = "8ec3824da1946a3fc6fb70f2302a3b139f046385e76bf6050bf00fc58ae31f70",
    zero_drift: bool = True,
    drift_val: str = "0.00",
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite DB
    db_path = target_dir / "canary-calibration-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE calibration_telemetry (
            id INTEGER PRIMARY KEY,
            timestamp_ms INTEGER,
            symbol TEXT,
            regime TEXT,
            confidence REAL,
            gamma REAL,
            beta REAL,
            cushion_bps REAL,
            eta REAL,
            micro_chunk_usdt REAL,
            stability_index REAL,
            cash_usdt REAL,
            drift_usdt REAL
        )
        """
    )
    cur.execute(
        "INSERT INTO calibration_telemetry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            1000,
            "BTCUSDT",
            "CALM_BALANCED",
            0.90,
            0.05,
            12.0,
            2.5,
            0.00015,
            5.0,
            100.0,
            100.0,
            0.0,
        ),
    )
    conn.commit()
    conn.close()

    # 2. Events JSONL
    events_path = target_dir / "canary-calibration-events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event": "PARAMETER_CALIBRATED",
                "timestamp_ms": 1000,
                "symbol": "BTCUSDT",
                "regime": "CALM_BALANCED",
                "confidence": 0.90,
                "probabilities": {"CALM_BALANCED": 0.90},
                "damped_params": {
                    "risk_aversion_gamma": 0.05,
                    "hawkes_decay_beta": 12.0,
                    "reservation_cushion_bps": 2.5,
                    "temporary_impact_eta": 0.00015,
                    "micro_chunk_usdt": 5.0,
                    "tp_atr_multiplier": 2.0,
                    "sl_atr_multiplier": 1.2,
                },
                "raw_target": {
                    "risk_aversion_gamma": 0.05,
                    "hawkes_decay_beta": 12.0,
                    "reservation_cushion_bps": 2.5,
                    "temporary_impact_eta": 0.00015,
                    "micro_chunk_usdt": 5.0,
                    "tp_atr_multiplier": 2.0,
                    "sl_atr_multiplier": 1.2,
                },
                "stability_index": 100.0,
                "is_clamped": False,
                "solvency_drift": 0.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def sha256_file(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    sqlite_hash = sha256_file(db_path)
    events_hash = sha256_file(events_path)

    if tamper_file == "sqlite3":
        sqlite_hash = "f" * 64
    elif tamper_file == "events":
        events_hash = "f" * 64

    solvency = {
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
    }

    performance = {
        "total_calibrations": 1,
        "dominant_regime": "CALM_BALANCED",
        "average_stability_index": 100.0,
        "mean_adaptation_latency_ms": 0.35,
        "adaptation_sla_met": True,
        "regime_distribution": {"CALM_BALANCED": 1},
        "defense_lockouts_triggered": 0,
        "parameter_clamp_events": 0,
        "realized_sharpe_ratio": 1024.5,
        "calmar_ratio": 6800.0,
        "max_drawdown_pct": 0.0035,
        "win_rate_pct": 100.0,
        "profit_factor": 0.065,
    }

    phase_payload = {
        "phase": "phase_304",
        "upstream_root": upstream_hash,
        "sqlite_hash": sqlite_hash,
        "events_hash": events_hash,
        "solvency": solvency,
        "performance": performance,
    }
    phase_hash = hashlib.sha256(
        json.dumps(phase_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    merkle_combined = f"{upstream_hash}:{sqlite_hash}:{events_hash}:{phase_hash}"
    merkle_root = hashlib.sha256(merkle_combined.encode("utf-8")).hexdigest()

    summary_data = {
        "phase": "phase_304",
        "status": "CALIBRATION_VERIFIED",
        "verified": True,
        "paper_safe": True,
        "execution_authority": False,
        "timestamp_utc": "2026-09-23T11:45:00Z",
        "timestamp_ms": 1789450000000,
        "upstream_hash": upstream_hash,
        "phase_hash": phase_hash,
        "merkle_root": merkle_root,
        "artifact_hashes": {
            "sqlite3": sqlite_hash,
            "events_jsonl": events_hash,
        },
        "circuit_state": "NORMAL",
        "performance": performance,
        "shadow_states": {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "active_regime": "CALM_BALANCED",
                "regime_confidence": 0.90,
                "stability_index": 100.0,
                "total_calibrations": 1,
                "calibrated_params": {
                    "risk_aversion_gamma": 0.05,
                    "hawkes_decay_beta": 12.0,
                    "reservation_cushion_bps": 2.5,
                    "temporary_impact_eta": 0.00015,
                    "micro_chunk_usdt": 5.0,
                    "tp_atr_multiplier": 2.0,
                    "sl_atr_multiplier": 1.2,
                },
                "allocated_margin_usdt": 0.0,
                "unrealized_pnl_usdt": 0.0,
                "adaptation_latency_ms": 0.35,
            }
        },
        "solvency": solvency,
        "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "evolution_trace": [
            {
                "event": "PARAMETER_CALIBRATED",
                "timestamp_ms": 1000,
                "symbol": "BTCUSDT",
                "regime": "CALM_BALANCED",
                "confidence": 0.90,
                "probabilities": {"CALM_BALANCED": 0.90},
                "damped_params": {
                    "risk_aversion_gamma": 0.05,
                    "hawkes_decay_beta": 12.0,
                    "reservation_cushion_bps": 2.5,
                    "temporary_impact_eta": 0.00015,
                    "micro_chunk_usdt": 5.0,
                    "tp_atr_multiplier": 2.0,
                    "sl_atr_multiplier": 1.2,
                },
                "raw_target": {
                    "risk_aversion_gamma": 0.05,
                    "hawkes_decay_beta": 12.0,
                    "reservation_cushion_bps": 2.5,
                    "temporary_impact_eta": 0.00015,
                    "micro_chunk_usdt": 5.0,
                    "tp_atr_multiplier": 2.0,
                    "sl_atr_multiplier": 1.2,
                },
                "stability_index": 100.0,
                "is_clamped": False,
                "solvency_drift": 0.0,
            }
        ],
    }

    (target_dir / "calibration-summary.json").write_text(
        json.dumps(summary_data, indent=2), encoding="utf-8"
    )
    (target_dir / "canary-calibration-report.json").write_text(
        json.dumps(summary_data, indent=2), encoding="utf-8"
    )
    (target_dir / "paper-summary.json").write_text(
        json.dumps(
            {
                "phase": "phase_304",
                "status": "CALIBRATION_VERIFIED",
                "merkle_root": merkle_root,
                "upstream_root": upstream_hash,
                "zero_balance_drift": zero_drift,
                "execution_authority": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target_dir


def test_load_verified_canary_calibration_live() -> None:
    """Test loading live Phase 304 artifacts from default directory."""
    res = load_verified_canary_calibration()
    assert isinstance(res, CanaryCalibrationResponse)
    assert res.phase == "phase_304"
    assert res.status == "CALIBRATION_VERIFIED"
    assert res.verified is True
    assert res.paper_safe is True
    assert res.execution_authority is False
    assert res.solvency.zero_balance_drift_verified is True
    assert res.solvency.drift_usdt == 0.0
    assert "BTCUSDT" in res.shadow_states
    assert len(res.evolution_trace) > 0


def test_load_verified_canary_calibration_missing_dir(tmp_path: Path) -> None:
    """Test loading from nonexistent directory raises CanaryEvidenceNotFoundError."""
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_calibration(tmp_path / "nonexistent")


def test_load_verified_canary_calibration_tampered_hash(tmp_path: Path) -> None:
    """Test tampered artifact hash raises CanaryEvidenceIntegrityError."""
    target = tmp_path / "tampered"
    _build_synthetic_phase304_artifacts(target, tamper_file="sqlite3")
    with pytest.raises(CanaryEvidenceIntegrityError):
        load_verified_canary_calibration(target)


def test_load_verified_canary_calibration_upstream_mismatch(tmp_path: Path) -> None:
    """Test invalid upstream hash raises CanaryEvidenceIntegrityError."""
    target = tmp_path / "bad_upstream"
    _build_synthetic_phase304_artifacts(target, upstream_hash="bad" * 21 + "b")
    with pytest.raises(CanaryEvidenceIntegrityError):
        load_verified_canary_calibration(target)


def test_load_verified_canary_calibration_solvency_drift(tmp_path: Path) -> None:
    """Test nonzero solvency drift raises CanaryEvidenceIntegrityError."""
    target = tmp_path / "drift_breach"
    _build_synthetic_phase304_artifacts(target, zero_drift=False, drift_val="0.05")
    with pytest.raises(CanaryEvidenceIntegrityError):
        load_verified_canary_calibration(target)


def test_api_canary_calibration_200_ok() -> None:
    """Test FastAPI GET /api/v1/canary/calibration returns 200 OK with verified payload."""
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/v1/canary/calibration")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "CALIBRATION_VERIFIED"
    assert data["phase"] == "phase_304"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False
    assert data["solvency"]["zero_balance_drift_verified"] is True
    assert "BTCUSDT" in data["shadow_states"]


def test_api_canary_calibration_404_not_found(tmp_path: Path) -> None:
    """Test FastAPI GET /api/v1/canary/calibration returns 404 when evidence is missing."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)
    resp = client.get("/api/v1/canary/calibration")
    assert resp.status_code == 404
    assert "evidence unavailable" in resp.json()["detail"]


def test_api_canary_calibration_503_integrity_error(tmp_path: Path) -> None:
    """Test FastAPI GET /api/v1/canary/calibration returns 503 on corrupted artifacts."""
    bad_dir = tmp_path / "bad_dir"
    _build_synthetic_phase304_artifacts(bad_dir, tamper_file="sqlite3")
    app = create_app(canary_phase_dir=bad_dir)
    client = TestClient(app)
    resp = client.get("/api/v1/canary/calibration")
    assert resp.status_code == 503
    assert "integrity verification failed" in resp.json()["detail"]
