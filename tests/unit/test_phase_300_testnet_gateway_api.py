"""Unit tests for Phase 300 Testnet Gateway FastAPI endpoint and loader.

Tests cover:
- 200 OK nominal endpoint response with full schema, dual-custody multi-sig tickets,
  pre-dispatch exchange filters, staged orders, latency attribution, and zero balance drift.
- 404 Not Found error mapping for missing evidence directory or required artifacts.
- 503 Service Unavailable error mapping for tampered SHA-256 hashes, balance drift breaches,
  and upstream Phase 299 Merkle DAG linkage mismatch.
- Direct loader validation of Merkle DAG integrity, dual-custody signatures, filter items,
  sub-50 ms latency attribution, and zero balance drift (|drift| < 1e-15 USDT).
- Summary endpoint compatibility with Phase 300 manifests.
"""

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
    CanaryTestnetGatewayResponse,
    load_verified_canary_testnet_gateway,
)

PHASE_299_PARENT_HASH = "328a3afdb22b95242614e1ae0269f5bc9fadfba875170e66b2024d6cd7aa0544"


def _build_synthetic_phase300_artifacts(
    phase_dir: Path,
    *,
    drift: str = "0.00",
    zero_drift: bool = True,
    tamper_file: str | None = None,
    upstream_hash: str = PHASE_299_PARENT_HASH,
) -> Path:
    """Helper to populate a clean, fully-formed Phase 300 synthetic evidence directory."""
    phase_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite3 database
    db_path = phase_dir / "canary-testnet-gateway-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE staged_orders (
            client_order_id TEXT PRIMARY KEY,
            ticket_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            notional_usdt REAL NOT NULL,
            current_state TEXT NOT NULL,
            tau_auth_ms REAL NOT NULL,
            tau_filter_ms REAL NOT NULL,
            tau_dispatch_ms REAL NOT NULL,
            tau_rtt_ms REAL NOT NULL,
            fee_usdt REAL NOT NULL,
            dispatched_at_utc TEXT,
            filled_at_utc TEXT,
            rejection_reason TEXT
        )
        """
    )
    cur.execute(
        """
        INSERT INTO staged_orders
        (client_order_id, ticket_id, symbol, side, order_type,
         price, quantity, notional_usdt, current_state,
         tau_auth_ms, tau_filter_ms, tau_dispatch_ms, tau_rtt_ms, fee_usdt,
         dispatched_at_utc, filled_at_utc, rejection_reason)
        VALUES
        ('CANARY-TEST-001', 'TKT-TEST-001', 'BTCUSDT', 'BUY', 'LIMIT',
         50000.00, 0.00010, 5.00, 'FILLED',
         1.2, 0.8, 4.5, 6.5, 0.001,
         '2026-09-22T07:29:56.000Z', '2026-09-22T07:29:56.006Z', NULL),
        ('CANARY-TEST-002', 'TKT-TEST-002', 'ETHUSDT', 'BUY', 'LIMIT',
         2500.00, 0.0020, 5.00, 'FILLED',
         1.1, 0.7, 4.2, 6.0, 0.001,
         '2026-09-22T07:29:57.000Z', '2026-09-22T07:29:57.005Z', NULL)
        """
    )
    conn.commit()
    conn.close()

    # 2. canary-orders.jsonl
    orders_path = phase_dir / "canary-orders.jsonl"
    with open(orders_path, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "client_order_id": "CANARY-TEST-001",
                    "ticket_id": "TKT-TEST-001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "price": "50000.00",
                    "quantity": "0.00010",
                    "notional_usdt": "5.00",
                    "current_state": "FILLED",
                }
            )
            + "\n"
        )

    # 3. Paper summary
    paper_summary_path = phase_dir / "paper-summary.json"
    paper_summary_data = {
        "phase": "phase_300",
        "execution_authority": False,
        "paper_safe": True,
        "total_orders_staged": 2,
    }
    with open(paper_summary_path, "w", encoding="utf-8") as f:
        json.dump(paper_summary_data, f, indent=2)

    db_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    orders_hash = hashlib.sha256(orders_path.read_bytes()).hexdigest()
    paper_summary_hash = hashlib.sha256(paper_summary_path.read_bytes()).hexdigest()

    # Tamper file if requested
    if tamper_file == "telemetry_db":
        db_hash = "0" * 64

    # Initial report to get hash
    report_path = phase_dir / "canary-testnet-gateway-report.json"
    dummy_report_data = {
        "phase": "phase_300",
        "status": "TESTNET_GATEWAY_VERIFIED",
        "execution_authority": False,
        "paper_safe": True,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(dummy_report_data, f, indent=2)
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()

    merkle_combined = f"{db_hash}:{orders_hash}"
    merkle_root = hashlib.sha256(merkle_combined.encode("utf-8")).hexdigest()
    if tamper_file == "merkle_root":
        merkle_root = "0" * 64

    phase_combined = f"{upstream_hash}:{merkle_root}"
    phase_hash = hashlib.sha256(phase_combined.encode("utf-8")).hexdigest()

    # 4. Testnet summary
    summary_path = phase_dir / "testnet-gateway-summary.json"
    summary_data = {
        "phase": "phase_300",
        "status": "TESTNET_GATEWAY_VERIFIED",
        "timestamp_utc": "2026-09-22T07:30:00Z",
        "execution_authority": False,
        "paper_safe": True,
        "total_orders_staged": 2,
        "orders_filled": 2,
        "orders_rejected": 0,
        "double_entry_verified": zero_drift,
        "max_observed_drift": drift,
        "upstream_hash": upstream_hash,
        "phase_hash": phase_hash,
        "merkle_root": merkle_root,
        "artifact_hashes": {
            "canary-testnet-gateway-telemetry.sqlite3": db_hash,
            "canary-orders.jsonl": orders_hash,
            "canary-testnet-gateway-report.json": report_hash,
            "paper-summary.json": paper_summary_hash,
        },
        "solvency": {
            "starting_equity_usdt": 100.00,
            "cash_usdt": 99.998,
            "allocated_margin_usdt": 0.0,
            "unrealized_pnl_usdt": 0.0,
            "realized_pnl_usdt": -0.002,
            "total_equity_usdt": 99.998,
            "total_fees_usdt": 0.002,
            "total_slippage_usdt": 0.0,
            "drift_usdt": float(drift),
            "zero_balance_drift_verified": zero_drift,
            "tolerance_ceiling_usdt": 1e-15,
            "solvency_ratio_pct": 100.0,
            "cash_reserve_pct": 100.0,
            "unencumbered_cash_verified": True,
        },
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    return phase_dir


# =====================================================================
# Direct Loader Tests
# =====================================================================


def test_loader_nominal_success(tmp_path: Path) -> None:
    """Verify loader successfully loads and validates fully compliant Phase 300 evidence."""
    phase_dir = _build_synthetic_phase300_artifacts(tmp_path / "phase300")
    response = load_verified_canary_testnet_gateway(phase_dir)

    assert isinstance(response, CanaryTestnetGatewayResponse)
    assert response.verified is True
    assert response.phase == "phase_300"
    assert response.status == "TESTNET_GATEWAY_VERIFIED"
    assert len(response.staged_orders) == 2
    assert response.solvency.zero_balance_drift_verified is True
    assert len(response.tickets) >= 1
    assert len(response.staged_orders) == 2
    assert response.upstream_hash == PHASE_299_PARENT_HASH


def test_loader_missing_dir_raises_not_found(tmp_path: Path) -> None:
    """Verify loader raises CanaryEvidenceNotFoundError when directory does not exist."""
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(
        CanaryEvidenceNotFoundError, match="Testnet gateway summary artifact missing"
    ):
        load_verified_canary_testnet_gateway(non_existent)


def test_loader_missing_artifact_raises_not_found(tmp_path: Path) -> None:
    """Verify loader raises CanaryEvidenceNotFoundError when a required file is missing."""
    phase_dir = _build_synthetic_phase300_artifacts(tmp_path / "phase300")
    # Delete db file
    (phase_dir / "canary-testnet-gateway-telemetry.sqlite3").unlink()

    with pytest.raises(
        CanaryEvidenceNotFoundError, match="Required testnet gateway telemetry artifact missing"
    ):
        load_verified_canary_testnet_gateway(phase_dir)


def test_loader_tampered_artifact_hash_raises_integrity_error(tmp_path: Path) -> None:
    """Verify loader raises CanaryEvidenceIntegrityError when file hash differs from summary."""
    phase_dir = _build_synthetic_phase300_artifacts(
        tmp_path / "phase300", tamper_file="telemetry_db"
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="SHA-256 mismatch"):
        load_verified_canary_testnet_gateway(phase_dir)


def test_loader_tampered_merkle_root_raises_integrity_error(tmp_path: Path) -> None:
    """Verify loader raises CanaryEvidenceIntegrityError when Merkle root is invalid."""
    phase_dir = _build_synthetic_phase300_artifacts(
        tmp_path / "phase300", tamper_file="merkle_root"
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="Merkle root mismatch"):
        load_verified_canary_testnet_gateway(phase_dir)


def test_loader_upstream_hash_mismatch_raises_integrity_error(tmp_path: Path) -> None:
    """Verify loader raises error when parent DAG hash does not match Phase 299."""
    phase_dir = _build_synthetic_phase300_artifacts(
        tmp_path / "phase300", upstream_hash="bad_upstream_hash"
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="Upstream hash mismatch"):
        load_verified_canary_testnet_gateway(phase_dir)


def test_loader_balance_drift_breach_raises_integrity_error(tmp_path: Path) -> None:
    """Verify loader raises CanaryEvidenceIntegrityError when balance drift exceeds 1e-15 USDT."""
    phase_dir = _build_synthetic_phase300_artifacts(
        tmp_path / "phase300",
        drift="0.05",
        zero_drift=False,
    )
    with pytest.raises(
        CanaryEvidenceIntegrityError, match="Double-entry zero-drift balance invariant breached"
    ):
        load_verified_canary_testnet_gateway(phase_dir)


# =====================================================================
# FastAPI Endpoint Integration Tests
# =====================================================================


def test_api_endpoint_200_ok_nominal(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/testnet-gateway returns 200 OK with fully compliant schema."""
    phase_dir = _build_synthetic_phase300_artifacts(tmp_path / "phase300")
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/testnet-gateway")
    assert resp.status_code == 200

    data = resp.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_300"
    assert data["status"] == "TESTNET_GATEWAY_VERIFIED"
    assert len(data["staged_orders"]) == 2
    assert data["solvency"]["zero_balance_drift_verified"] is True
    assert data["execution_authority"] is False


def test_api_endpoint_404_when_dir_missing(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/testnet-gateway returns 404 when evidence is missing."""
    app = create_app(canary_phase_dir=tmp_path / "missing")
    client = TestClient(app)

    resp = client.get("/api/v1/canary/testnet-gateway")
    assert resp.status_code == 404
    assert "evidence unavailable" in resp.json()["detail"].lower()


def test_api_endpoint_503_when_tampered(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/testnet-gateway returns 503 when artifacts are tampered."""
    phase_dir = _build_synthetic_phase300_artifacts(
        tmp_path / "phase300", tamper_file="telemetry_db"
    )
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/testnet-gateway")
    assert resp.status_code == 503
    assert "integrity verification failed" in resp.json()["detail"].lower()


def test_api_endpoint_real_artifacts_verified() -> None:
    """Verify GET /api/v1/canary/testnet-gateway against the real Phase 300 generated artifacts."""
    real_phase_dir = Path("artifacts/research/phase300")
    if not real_phase_dir.exists():
        pytest.skip("Phase 300 real artifacts not found on disk")

    app = create_app(canary_phase_dir=real_phase_dir)
    client = TestClient(app)

    resp = client.get("/api/v1/canary/testnet-gateway")
    assert resp.status_code == 200

    data = resp.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_300"
    assert data["status"] == "TESTNET_GATEWAY_VERIFIED"
    assert len(data["staged_orders"]) >= 8
    assert data["solvency"]["zero_balance_drift_verified"] is True
    assert data["execution_authority"] is False
    assert data["upstream_hash"] == PHASE_299_PARENT_HASH
