"""Unit tests for Phase 307 testnet bridge API endpoints and artifact evidence verification."""

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
    CanaryTestnetBridgeResponse,
    load_verified_canary_testnet_bridge,
)

UPSTREAM_PHASE306_ROOT = "818fd82458a8fb19420dd0179c8f78b0c273e5d2a71b1968b083d20f99e23dbe"


def _build_synthetic_phase307_artifacts(
    target_dir: Path,
    *,
    tamper_file: str | None = None,
    upstream_hash: str = UPSTREAM_PHASE306_ROOT,
    zero_drift: bool = True,
    drift_val: str = "0.00",
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite DB
    db_path = target_dir / "canary-testnet-bridge-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE testnet_bridge_status (
            bridge_id TEXT PRIMARY KEY,
            state TEXT,
            api_key_masked TEXT,
            clock_offset_ms INTEGER,
            listen_key TEXT,
            listen_key_active INTEGER,
            is_paper_safe INTEGER,
            execution_authority INTEGER,
            timestamp_ms INTEGER
        )
        """
    )
    cur.execute(
        "INSERT INTO testnet_bridge_status VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "bridge-01",
            "CONNECTED",
            "mock-****-7f89",
            12,
            "lk-test-001",
            1,
            1,
            0,
            1790233200000,
        ),
    )
    conn.commit()
    conn.close()

    # 2. Events JSONL
    events_path = target_dir / "canary-testnet-bridge-events.jsonl"
    with open(events_path, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "event_id": "evt-001",
                    "event_type": "ORDER_TRADE_UPDATE",
                    "listen_key": "lk-test-001",
                    "symbol": "BTCUSDT",
                    "order_id": "cli-btc-1001",
                    "order_status": "FILLED",
                    "balance_delta_usdt": 0.005,
                    "margin_delta_usdt": -5.0,
                    "timestamp_ms": 1790233200000,
                }
            )
            + "\n"
        )

    # Hashes of raw artifact files
    sqlite_bytes = db_path.read_bytes()
    events_bytes = events_path.read_bytes()
    sqlite_hash = hashlib.sha256(sqlite_bytes).hexdigest()
    events_hash = hashlib.sha256(events_bytes).hexdigest()

    # 3. Phase Hash & Merkle Root
    phase_hasher = hashlib.sha256()
    phase_hasher.update(b"phase_307_testnet_bridge_v1")
    phase_hasher.update(sqlite_hash.encode())
    phase_hasher.update(events_hash.encode())
    phase_hasher.update(drift_val.encode())
    phase_payload_hash = phase_hasher.hexdigest()

    merkle_combined = f"{upstream_hash}:{sqlite_hash}:{events_hash}:{phase_payload_hash}"
    merkle_root = hashlib.sha256(merkle_combined.encode("utf-8")).hexdigest()

    # 4. Summary JSON
    summary_path = target_dir / "testnet-bridge-summary.json"
    summary_data = {
        "phase": "phase_307",
        "verified": True,
        "status": "TESTNET_BRIDGE_VERIFIED",
        "circuit_state": "NORMAL",
        "timestamp_ms": 1790233200000,
        "timestamp_utc": "2026-09-24T07:00:00.000000+00:00",
        "paper_safe": True,
        "execution_authority": False,
        "bridge": {
            "connection_state": "CONNECTED",
            "api_key_masked": "mock-****-7f89",
            "is_mock_credentials": True,
            "clock_offset_ms": 12,
            "clock_skew_verified": True,
            "listen_key": "lk-test-001",
            "listen_key_active": True,
        },
        "performance": {
            "total_orders_dispatched": 1,
            "total_orders_filled": 1,
            "fill_rate_pct": 100.0,
            "mean_round_trip_ms": 18.5,
            "mean_filter_latency_us": 12.0,
            "mean_sign_latency_us": 25.0,
            "max_micro_notional_usdt": 5.0,
            "micro_cap_verified": True,
            "lot_size_filter_verified": True,
            "price_filter_verified": True,
            "min_notional_verified": True,
        },
        "exchange_filters": {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "step_size": 0.00001,
                "min_qty": 0.00001,
                "max_qty": 100.0,
                "tick_size": 0.1,
                "min_price": 1000.0,
                "max_price": 500000.0,
                "min_notional_usdt": 5.0,
                "max_micro_cap_usdt": 5.0,
            }
        },
        "dispatched_orders_trace": [
            {
                "order_id": "cli-btc-1001",
                "exchange_order_id": 900001001,
                "candidate_id": "cand-btcusdt-dcb-002",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "order_type": "LIMIT",
                "price": 95000.0,
                "qty": 0.00005,
                "notional_usdt": 4.75,
                "lifecycle": "FILLED",
                "tau_filter_us": 12.0,
                "tau_sign_us": 25.0,
                "tau_dispatch_ms": 18.5,
                "tau_rtt_ms": 18.537,
                "fill_price": 95000.0,
                "fill_qty": 0.00005,
                "fee_cost_usdt": 0.00095,
                "timestamp_ms": 1790233200000,
                "error_code": None,
            }
        ],
        "user_data_events_trace": [
            {
                "event_id": "evt-001",
                "event_type": "ORDER_TRADE_UPDATE",
                "listen_key": "lk-test-001",
                "symbol": "BTCUSDT",
                "order_id": "cli-btc-1001",
                "order_status": "FILLED",
                "balance_delta_usdt": 0.005,
                "margin_delta_usdt": -5.0,
                "timestamp_ms": 1790233200000,
            }
        ],
        "solvency": {
            "starting_equity_usdt": 100.0,
            "cash_usdt": 100.005,
            "allocated_margin_usdt": 0.0,
            "unrealized_pnl_usdt": 0.0,
            "realized_pnl_usdt": 0.005,
            "total_equity_usdt": 100.005,
            "total_fees_usdt": 0.00095,
            "total_slippage_usdt": 0.0,
            "drift_usdt": float(drift_val),
            "zero_balance_drift_verified": zero_drift,
            "tolerance_ceiling_usdt": 1e-15,
            "solvency_ratio_pct": 100.0,
            "cash_reserve_pct": 100.0,
            "unencumbered_cash_verified": True,
        },
        "upstream_hash": upstream_hash,
        "phase_hash": phase_payload_hash,
        "merkle_root": merkle_root,
        "artifact_hashes": {
            "sqlite3": sqlite_hash,
            "events_jsonl": events_hash,
        },
        "upstream_merkle_dag": {
            "phase_306": upstream_hash,
        },
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    # 5. Report JSON
    report_path = target_dir / "canary-testnet-bridge-report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    # Tampering for failure simulation
    if tamper_file == "sqlite":
        with open(db_path, "ab") as f:
            f.write(b"tampered")
    elif tamper_file == "events":
        with open(events_path, "a", encoding="utf-8") as f:
            f.write("tampered\n")
    elif tamper_file == "merkle":
        summary_data["merkle_root"] = "0" * 64
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)

    return target_dir


def test_load_verified_canary_testnet_bridge_success(tmp_path: Path) -> None:
    """Test loading and verifying valid Phase 307 artifacts."""
    _build_synthetic_phase307_artifacts(tmp_path)
    res = load_verified_canary_testnet_bridge(tmp_path)

    assert isinstance(res, CanaryTestnetBridgeResponse)
    assert res.verified
    assert res.phase == "phase_307"
    assert res.status == "TESTNET_BRIDGE_VERIFIED"
    assert res.paper_safe
    assert not res.execution_authority
    assert res.bridge.connection_state == "CONNECTED"
    assert res.bridge.clock_skew_verified
    assert res.solvency.zero_balance_drift_verified


def test_load_verified_canary_testnet_bridge_missing_evidence(tmp_path: Path) -> None:
    """Test missing required artifact file raises CanaryEvidenceNotFoundError."""
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_testnet_bridge(tmp_path)


def test_load_verified_canary_testnet_bridge_tamper_hash(tmp_path: Path) -> None:
    """Test tampered artifact file triggers hash mismatch CanaryEvidenceIntegrityError."""
    _build_synthetic_phase307_artifacts(tmp_path, tamper_file="sqlite")
    with pytest.raises(CanaryEvidenceIntegrityError, match="Artifact SHA-256 hash mismatch"):
        load_verified_canary_testnet_bridge(tmp_path)


def test_load_verified_canary_testnet_bridge_upstream_mismatch(tmp_path: Path) -> None:
    """Test mismatching upstream parent hash triggers CanaryEvidenceIntegrityError."""
    _build_synthetic_phase307_artifacts(tmp_path, upstream_hash="bad" * 16)
    with pytest.raises(CanaryEvidenceIntegrityError, match="Upstream hash mismatch"):
        load_verified_canary_testnet_bridge(tmp_path)


def test_load_verified_canary_testnet_bridge_merkle_mismatch(tmp_path: Path) -> None:
    """Test tampered Merkle root triggers CanaryEvidenceIntegrityError."""
    _build_synthetic_phase307_artifacts(tmp_path, tamper_file="merkle")
    with pytest.raises(CanaryEvidenceIntegrityError, match="Merkle root mismatch"):
        load_verified_canary_testnet_bridge(tmp_path)


def test_load_verified_canary_testnet_bridge_drift_breach(tmp_path: Path) -> None:
    """Test non-zero drift breaches double-entry tolerance."""
    _build_synthetic_phase307_artifacts(tmp_path, zero_drift=False, drift_val="0.05")
    with pytest.raises(CanaryEvidenceIntegrityError, match="Double-entry zero-drift"):
        load_verified_canary_testnet_bridge(tmp_path)


def test_api_canary_testnet_bridge_endpoint_success(tmp_path: Path) -> None:
    """Test GET /api/v1/canary/testnet-bridge returns 200 and schema."""
    _build_synthetic_phase307_artifacts(tmp_path)
    app = create_app(canary_phase_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/v1/canary/testnet-bridge")
    assert response.status_code == 200
    data = response.json()
    assert data["verified"] is True
    assert data["status"] == "TESTNET_BRIDGE_VERIFIED"
    assert data["bridge"]["connection_state"] == "CONNECTED"
    assert data["performance"]["total_orders_dispatched"] == 1


def test_api_canary_testnet_bridge_endpoint_not_found(tmp_path: Path) -> None:
    """Test GET /api/v1/canary/testnet-bridge returns 404 when artifacts missing."""
    empty_dir = tmp_path / "empty_phase"
    empty_dir.mkdir()
    app = create_app(canary_phase_dir=empty_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/testnet-bridge")
    assert response.status_code == 404
    assert "evidence unavailable" in response.json()["detail"]


def test_api_canary_testnet_bridge_endpoint_integrity_failure(tmp_path: Path) -> None:
    """Test GET /api/v1/canary/testnet-bridge returns 503 upon hash mismatch."""
    _build_synthetic_phase307_artifacts(tmp_path, tamper_file="sqlite")
    app = create_app(canary_phase_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/api/v1/canary/testnet-bridge")
    assert response.status_code == 503
    assert "integrity verification failed" in response.json()["detail"]
