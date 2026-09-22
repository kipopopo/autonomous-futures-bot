"""Unit tests for Phase 301 API endpoints and artifact evidence verification."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autonomous_futures.api.app import create_app
from autonomous_futures.api.canary import (
    CanaryBracketPositionsResponse,
    CanaryEvidenceIntegrityError,
    CanaryEvidenceNotFoundError,
    load_verified_canary_bracket_positions,
)


def _build_synthetic_phase301_artifacts(
    target_dir: Path,
    *,
    tamper_file: str | None = None,
    upstream_hash: str = "25c81437dc77630dd8a143aea2056a126c16d908573d69a79676bc223fbbd14c",
    zero_drift: bool = True,
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite DB
    db_path = target_dir / "canary-bracket-position-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE position_events (
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
        CREATE TABLE bracket_orders (
            bracket_id TEXT PRIMARY KEY,
            entry_order_id TEXT,
            symbol TEXT,
            bracket_type TEXT,
            side TEXT,
            status TEXT,
            trigger_price REAL,
            quantity REAL,
            notional_usdt REAL,
            fee_usdt REAL
        )
        """
    )
    cur.execute(
        "INSERT INTO position_events VALUES (?, ?, ?, ?, ?)",
        ("evt-001", "ACCOUNT_UPDATE", "BTCUSDT", "2026-09-22T17:30:00Z", "{}"),
    )
    cur.execute(
        "INSERT INTO bracket_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "brk-001",
            "entry-001",
            "BTCUSDT",
            "TAKE_PROFIT_LIMIT",
            "SELL",
            "ARMED",
            50750.0,
            0.0001,
            5.075,
            0.001,
        ),
    )
    conn.commit()
    conn.close()

    # 2. Events JSONL
    events_path = target_dir / "canary-bracket-events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "event_id": "evt-001",
                "event_type": "ACCOUNT_UPDATE",
                "timestamp_utc": "2026-09-22T17:30:00Z",
                "symbol": "BTCUSDT",
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Hashes
    db_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    events_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()

    if tamper_file == "telemetry_db":
        db_path.write_bytes(b"tampered db content")
    elif tamper_file == "events_jsonl":
        events_path.write_bytes(b"tampered events content")

    phase_hash = hashlib.sha256(
        f"phase_301:{upstream_hash}:{db_hash}:{events_hash}".encode()
    ).hexdigest()
    merkle_root = hashlib.sha256(f"{phase_hash}:{upstream_hash}".encode()).hexdigest()

    if tamper_file == "merkle_root":
        merkle_root = "0" * 64

    drift_val = 0.0 if zero_drift else 0.50

    # 3. Report JSON
    report_data = {
        "phase": "phase_301",
        "status": "BRACKET_POSITIONS_VERIFIED",
        "upstream_hash": upstream_hash,
        "phase_hash": phase_hash,
        "merkle_root": merkle_root,
        "solvency": {
            "starting_equity_usdt": 100.0,
            "cash_usdt": 96.6666,
            "allocated_margin_usdt": 3.3333,
            "unrealized_pnl_usdt": 0.0,
            "realized_pnl_usdt": 0.0,
            "total_equity_usdt": 100.0,
            "total_fees_usdt": 0.0,
            "total_slippage_usdt": 0.0,
            "drift_usdt": drift_val,
            "zero_balance_drift_verified": zero_drift,
            "tolerance_ceiling_usdt": 1e-15,
            "solvency_ratio_pct": 100.0,
            "cash_reserve_pct": 96.6666,
            "unencumbered_cash_verified": True,
        },
        "artifact_hashes": {
            "canary-bracket-position-telemetry.sqlite3": db_hash,
            "canary-bracket-events.jsonl": events_hash,
        },
    }
    report_path = target_dir / "canary-bracket-position-report.json"
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    # 4. Summary JSON
    summary_data = {
        "verified": True,
        "phase": "phase_301",
        "status": "BRACKET_POSITIONS_VERIFIED",
        "timestamp_ms": 1790098584000,
        "timestamp_utc": "2026-09-22T17:30:00Z",
        "paper_safe": True,
        "execution_authority": False,
        "circuit_state": "NORMAL",
        "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "active_positions": [
            {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "size": 0.0001,
                "entry_price": 50000.0,
                "mark_price": 50000.0,
                "notional_usdt": 5.0,
                "margin_allocated_usdt": 1.6666,
                "unrealized_pnl_usdt": 0.0,
                "realized_pnl_usdt": 0.0,
                "liquidation_price_usdt": 33833.33,
                "margin_ratio_pct": 3.0,
                "risk_state": "NORMAL",
                "brackets": [],
                "last_updated_utc": "2026-09-22T17:30:00Z",
            }
        ],
        "all_positions": [],
        "brackets": [
            {
                "bracket_id": "brk-001",
                "entry_order_id": "entry-001",
                "symbol": "BTCUSDT",
                "bracket_type": "TAKE_PROFIT_LIMIT",
                "side": "SELL",
                "status": "ARMED",
                "trigger_price": 50750.0,
                "limit_price": 50750.0,
                "quantity": 0.0001,
                "notional_usdt": 5.075,
                "ratchet_watermark": 50000.0,
                "callback_rate_pct": 0.008,
                "created_at_utc": "2026-09-22T17:30:00Z",
                "fee_usdt": 0.001,
            }
        ],
        "recent_events": [
            {
                "event_id": "evt-001",
                "event_type": "ACCOUNT_UPDATE",
                "symbol": "BTCUSDT",
                "timestamp_utc": "2026-09-22T17:30:00Z",
                "latency_ms": 0.05,
            }
        ],
        "ingress_status": {
            "listen_key_active": True,
            "heartbeat_age_ms": 10.0,
            "heartbeat_fresh": True,
            "total_events_ingested": 1,
        },
        "solvency": report_data["solvency"],
        "upstream_hash": upstream_hash,
        "phase_hash": phase_hash,
        "merkle_root": merkle_root,
        "artifact_hashes": {
            "canary-bracket-position-telemetry.sqlite3": db_hash,
            "canary-bracket-events.jsonl": events_hash,
            "canary-bracket-position-report.json": hashlib.sha256(
                report_path.read_bytes()
            ).hexdigest(),
        },
    }
    summary_path = target_dir / "bracket-position-summary.json"
    summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

    return target_dir


def test_loader_on_live_generated_phase301_artifacts() -> None:
    """Verify loader reads real generated Phase 301 artifacts correctly."""
    phase_dir = Path("artifacts/research/phase301")
    if not phase_dir.is_dir() or not (phase_dir / "bracket-position-summary.json").is_file():
        pytest.skip("Phase 301 research artifacts not yet generated")

    response = load_verified_canary_bracket_positions(phase_dir)
    assert isinstance(response, CanaryBracketPositionsResponse)
    assert response.verified is True
    assert response.phase == "phase_301"
    assert response.status == "BRACKET_POSITIONS_VERIFIED"
    assert response.paper_safe is True
    assert response.execution_authority is False
    assert response.solvency.zero_balance_drift_verified is True
    assert (
        response.upstream_hash == "25c81437dc77630dd8a143aea2056a126c16d908573d69a79676bc223fbbd14c"
    )
    assert len(response.candidates) == 3


def test_loader_missing_summary_raises_not_found(tmp_path: Path) -> None:
    """Verify loader raises CanaryEvidenceNotFoundError when directory is empty."""
    non_existent = tmp_path / "empty_phase301"
    with pytest.raises(
        CanaryEvidenceNotFoundError, match="Bracket position summary artifact missing"
    ):
        load_verified_canary_bracket_positions(non_existent)


def test_loader_missing_db_artifact_raises_not_found(tmp_path: Path) -> None:
    """Verify loader raises CanaryEvidenceNotFoundError when SQLite DB is missing."""
    phase_dir = _build_synthetic_phase301_artifacts(tmp_path / "phase301")
    (phase_dir / "canary-bracket-position-telemetry.sqlite3").unlink()

    with pytest.raises(
        CanaryEvidenceNotFoundError,
        match="Required bracket position telemetry artifact missing",
    ):
        load_verified_canary_bracket_positions(phase_dir)


def test_loader_tampered_artifact_hash_raises_integrity_error(
    tmp_path: Path,
) -> None:
    """Verify loader raises CanaryEvidenceIntegrityError when file hash differs from summary."""
    phase_dir = _build_synthetic_phase301_artifacts(
        tmp_path / "phase301", tamper_file="telemetry_db"
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="SHA-256 mismatch"):
        load_verified_canary_bracket_positions(phase_dir)


def test_loader_tampered_merkle_root_raises_integrity_error(
    tmp_path: Path,
) -> None:
    """Verify loader raises CanaryEvidenceIntegrityError when Merkle root is invalid."""
    phase_dir = _build_synthetic_phase301_artifacts(
        tmp_path / "phase301", tamper_file="merkle_root"
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="Merkle root mismatch"):
        load_verified_canary_bracket_positions(phase_dir)


def test_loader_upstream_hash_mismatch_raises_integrity_error(tmp_path: Path) -> None:
    """Verify loader raises error when parent DAG hash does not match Phase 300."""
    phase_dir = _build_synthetic_phase301_artifacts(
        tmp_path / "phase301", upstream_hash="bad_upstream_hash"
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="Upstream hash mismatch"):
        load_verified_canary_bracket_positions(phase_dir)


def test_loader_zero_drift_breach_raises_integrity_error(tmp_path: Path) -> None:
    """Verify loader raises CanaryEvidenceIntegrityError when drift exceeds tolerance."""
    phase_dir = _build_synthetic_phase301_artifacts(
        tmp_path / "phase301",
        zero_drift=False,
    )
    with pytest.raises(
        CanaryEvidenceIntegrityError,
        match="Double-entry zero-drift balance invariant breached",
    ):
        load_verified_canary_bracket_positions(phase_dir)


def test_api_endpoint_200_ok(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/bracket-positions returns 200 OK with valid artifacts."""
    phase_dir = _build_synthetic_phase301_artifacts(tmp_path / "phase301")
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/bracket-positions")
    assert res.status_code == 200
    data = res.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_301"
    assert data["status"] == "BRACKET_POSITIONS_VERIFIED"
    assert data["solvency"]["zero_balance_drift_verified"] is True
    assert len(data["brackets"]) == 1


def test_api_endpoint_404_when_missing(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/bracket-positions returns 404 when artifacts missing."""
    empty_dir = tmp_path / "empty_phase301"
    empty_dir.mkdir()
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/bracket-positions")
    assert res.status_code == 404


def test_api_endpoint_503_when_tampered(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/bracket-positions returns 503 when artifacts are tampered."""
    phase_dir = _build_synthetic_phase301_artifacts(
        tmp_path / "phase301", tamper_file="telemetry_db"
    )
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/bracket-positions")
    assert res.status_code == 503
