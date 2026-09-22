"""Unit tests for Phase 299 Portfolio Rebalancing FastAPI endpoint and loader.

Tests cover:
- 200 OK nominal endpoint response with full schema, risk-parity allocation,
  and invariant validation.
- 404 Not Found error mapping for missing evidence directory or required artifacts.
- 503 Service Unavailable error mapping for tampered SHA-256 hashes, balance drift breaches,
  and upstream Phase 298 Merkle DAG linkage mismatch.
- Direct loader validation of Merkle DAG integrity, 3-asset allocation, cross-asset spillover,
  micro-order chunk caps (<= 5.00 USDT), and zero balance drift (|drift| < 1e-15 USDT).
- Summary endpoint compatibility with Phase 299 manifests (manifest_version=4).
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
    CanaryPortfolioRebalancingResponse,
    load_verified_canary_portfolio_rebalancing,
    load_verified_canary_summary,
)

PHASE_298_PARENT_HASH = "b2ea1dc7053aec1ecd6dd9845d776380093b925e056b891b64c8a454a62bf837"


def _build_synthetic_phase299_artifacts(
    phase_dir: Path,
    *,
    drift: str = "0.00",
    zero_drift: bool = True,
    tamper_file: str | None = None,
    upstream_hash: str = PHASE_298_PARENT_HASH,
) -> Path:
    """Helper to populate a clean, fully-formed Phase 299 synthetic evidence directory."""
    phase_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite3 database
    db_path = phase_dir / "canary-portfolio-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE asset_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            target_weight REAL,
            actual_weight REAL,
            target_notional_usdt REAL,
            actual_notional_usdt REAL,
            allocated_margin_usdt REAL,
            volatility_sigma REAL,
            jump_intensity_lambda REAL,
            drift_pct REAL,
            rebalance_required INTEGER,
            margin_ceiling_usdt REAL,
            ceiling_breached INTEGER
        )
        """
    )
    cur.execute(
        """
        INSERT INTO asset_allocations
        (symbol, target_weight, actual_weight, target_notional_usdt, actual_notional_usdt,
         allocated_margin_usdt, volatility_sigma, jump_intensity_lambda, drift_pct,
         rebalance_required, margin_ceiling_usdt, ceiling_breached)
        VALUES
        ('BTCUSDT', 0.45, 0.48, 27.00, 28.80, 14.40, 0.018, 0.22, 3.0, 1, 25.00, 0),
        ('ETHUSDT', 0.35, 0.34, 21.00, 20.40, 10.20, 0.024, 0.35, 1.0, 0, 25.00, 0),
        ('SOLUSDT', 0.20, 0.18, 12.00, 10.80, 5.40, 0.038, 0.58, 2.0, 0, 25.00, 0)
        """
    )

    cur.execute(
        """
        CREATE TABLE spillover_matrix (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            affected_symbol TEXT,
            trigger_symbol TEXT,
            cross_excitation_alpha REAL,
            decay_beta REAL,
            branching_ratio_gamma REAL,
            spillover_hazard INTEGER,
            deallocation_triggered INTEGER,
            freeze_dispatched INTEGER
        )
        """
    )
    cur.execute(
        """
        INSERT INTO spillover_matrix
        (affected_symbol, trigger_symbol, cross_excitation_alpha, decay_beta,
         branching_ratio_gamma, spillover_hazard, deallocation_triggered, freeze_dispatched)
        VALUES
        ('BTCUSDT', 'BTCUSDT', 0.25, 1.0, 0.25, 0, 0, 0),
        ('BTCUSDT', 'ETHUSDT', 0.12, 1.0, 0.12, 0, 0, 0),
        ('BTCUSDT', 'SOLUSDT', 0.08, 1.0, 0.08, 0, 0, 0),
        ('ETHUSDT', 'BTCUSDT', 0.18, 1.0, 0.18, 0, 0, 0),
        ('ETHUSDT', 'ETHUSDT', 0.28, 1.0, 0.28, 0, 0, 0),
        ('ETHUSDT', 'SOLUSDT', 0.11, 1.0, 0.11, 0, 0, 0),
        ('SOLUSDT', 'BTCUSDT', 0.18, 1.0, 0.18, 0, 0, 0),
        ('SOLUSDT', 'ETHUSDT', 0.14, 1.0, 0.14, 0, 0, 0),
        ('SOLUSDT', 'SOLUSDT', 0.32, 1.0, 0.32, 0, 0, 0)
        """
    )

    cur.execute(
        """
        CREATE TABLE micro_rebalance_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rebalance_id TEXT,
            timestamp_utc TEXT,
            symbol TEXT,
            side TEXT,
            target_drift_pct REAL,
            order_chunk_notional_usdt REAL,
            order_chunk_qty REAL,
            passive_price REAL,
            execution_status TEXT,
            fee_drag_usdt REAL,
            slippage_absorbed_usdt REAL,
            exchange_filters_compliant INTEGER
        )
        """
    )
    cur.execute(
        """
        INSERT INTO micro_rebalance_audits
        (rebalance_id, timestamp_utc, symbol, side, target_drift_pct,
         order_chunk_notional_usdt, order_chunk_qty, passive_price,
         execution_status, fee_drag_usdt, slippage_absorbed_usdt, exchange_filters_compliant)
        VALUES
        ('reb-299-001', '2026-09-22T08:00:00+00:00', 'BTCUSDT', 'SELL', 3.0, 1.80, 0.00003,
         60000.0, 'SIMULATED_FILLED', 0.00036, 0.0, 1),
        ('reb-299-002', '2026-09-22T08:00:01+00:00', 'SOLUSDT', 'BUY', 2.0, 1.20, 0.008,
         150.0, 'SIMULATED_FILLED', 0.00024, 0.0, 1)
        """
    )
    conn.commit()
    conn.close()

    # 2. Orders jsonl
    orders_file = phase_dir / "canary-orders.jsonl"
    line1 = (
        '{"order_id": "reb-chunk-1", "symbol": "BTCUSDT", "side": "SELL", '
        '"notional_usdt": 1.80, "status": "FILLED"}\n'
    )
    line2 = (
        '{"order_id": "reb-chunk-2", "symbol": "SOLUSDT", "side": "BUY", '
        '"notional_usdt": 1.20, "status": "FILLED"}\n'
    )
    orders_content = line1 + line2
    orders_file.write_text(orders_content, encoding="utf-8")

    # 3. Report json
    report_file = phase_dir / "canary-portfolio-report.json"
    report_data = {
        "phase": "phase_299",
        "generated_at_utc": "2026-09-22T08:00:00+00:00",
        "circuit_state": "NORMAL",
        "ledger_reconciliation": {
            "starting_equity_usdt": "100.00",
            "cash_usdt": "70.00",
            "allocated_margin_usdt": "30.00",
            "unrealized_pnl_usdt": "0.00",
            "realized_pnl_usdt": "0.00",
            "total_equity_usdt": "100.00",
            "total_fees_usdt": "0.00060",
            "total_slippage_usdt": "0.00",
            "drift_usdt": drift,
            "zero_drift_verified": zero_drift,
        },
        "optimization_metrics": {
            "aggregate_exposure_usdt": 60.00,
            "aggregate_exposure_cap_usdt": 60.00,
            "cash_reserve_usdt": 70.00,
            "cash_reserve_pct": 70.00,
            "cash_reserve_floor_pct": 40.00,
            "max_asset_margin_usdt": 14.40,
            "margin_ceiling_per_asset_usdt": 25.00,
            "spectral_radius_rho": 0.428571,
            "portfolio_volatility": 0.0215,
            "risk_parity_herfindahl_index": 0.338,
            "sharpe_ratio": 1.85,
            "optimization_status": "OPTIMAL",
        },
        "contagion_guard": {
            "guard_active": True,
            "max_spectral_radius_rho": 0.428571,
            "hazard_threshold_rho": 0.85,
            "hazard_detected": False,
            "source_hazard_assets": [],
            "throttled_recipient_assets": [],
            "capital_deallocated_usdt": 0.0,
            "order_dispatch_frozen": False,
            "action_taken": "MONITORING_NOMINAL",
        },
    }
    report_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    # 4. Paper summary json
    paper_summary_file = phase_dir / "paper-summary.json"
    paper_summary_data = {
        "phase": "phase_299",
        "circuit_state": "NORMAL",
        "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    }
    paper_summary_file.write_text(json.dumps(paper_summary_data, indent=2), encoding="utf-8")

    # Compute hashes
    db_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    orders_hash = hashlib.sha256(orders_file.read_bytes()).hexdigest()
    report_hash = hashlib.sha256(report_file.read_bytes()).hexdigest()
    paper_hash = hashlib.sha256(paper_summary_file.read_bytes()).hexdigest()

    if tamper_file == "canary-orders.jsonl":
        orders_hash = "0" * 64
    elif tamper_file == "canary-portfolio-report.json":
        report_hash = "0" * 64
    elif tamper_file == "canary-portfolio-telemetry.sqlite3":
        db_hash = "0" * 64

    # 5. Summary json
    summary_file = phase_dir / "portfolio-rebalancing-summary.json"
    summary_data = {
        "phase": "phase_299",
        "status": "PORTFOLIO_REBALANCING_VERIFIED",
        "timestamp_utc": "2026-09-22T08:00:00+00:00",
        "circuit_state": "NORMAL",
        "paper_safe": True,
        "execution_authority": False,
        "zero_balance_drift": zero_drift,
        "drift_usdt": drift,
        "starting_capital_usdt": "100.00",
        "final_cash_usdt": "70.00",
        "final_equity_usdt": "100.00",
        "realized_pnl_usdt": "0.00",
        "total_fees_usdt": "0.00060",
        "total_slippage_usdt": "0.00",
        "manifest_version": 4,
        "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "artifact_hashes": {
            "canary-portfolio-telemetry.sqlite3": db_hash,
            "canary-orders.jsonl": orders_hash,
            "canary-portfolio-report.json": report_hash,
            "paper-summary.json": paper_hash,
        },
        "upstream_merkle_dag": {
            "phase298_summary_hash": upstream_hash,
        },
    }
    summary_file.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

    return phase_dir


def test_canary_portfolio_rebalancing_nominal_200(tmp_path: Path) -> None:
    """Verifies that GET /api/v1/canary/portfolio-rebalancing returns 200 with verified state."""
    phase_dir = _build_synthetic_phase299_artifacts(tmp_path / "phase299")
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/portfolio-rebalancing")
    assert response.status_code == 200
    data = response.json()

    # Safety and confinement invariants
    assert data["verified"] is True
    assert data["phase"] == "phase_299"
    assert data["status"] == "PORTFOLIO_REBALANCING_VERIFIED"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False
    assert data["circuit_state"] == "NORMAL"

    # Allocations
    allocations = data["allocations"]
    assert len(allocations) == 3
    symbols = {a["symbol"] for a in allocations}
    assert symbols == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    for a in allocations:
        assert a["target_weight"] > 0
        assert a["volatility_sigma"] > 0
        assert a["jump_intensity_lambda"] >= 0
        assert a["allocated_margin_usdt"] <= a["margin_ceiling_usdt"]
        assert a["ceiling_breached"] is False

    # Optimization metrics
    metrics = data["optimization_metrics"]
    assert metrics["aggregate_exposure_usdt"] <= metrics["aggregate_exposure_cap_usdt"]
    assert metrics["cash_reserve_pct"] >= metrics["cash_reserve_floor_pct"]
    assert metrics["max_asset_margin_usdt"] <= metrics["margin_ceiling_per_asset_usdt"]
    assert metrics["optimization_status"] == "OPTIMAL"

    # Spillover matrix
    matrix = data["spillover_matrix"]
    assert len(matrix) == 9
    for item in matrix:
        assert item["cross_excitation_alpha"] >= 0
        assert item["decay_beta"] > 0
        assert item["branching_ratio_gamma"] >= 0

    # Contagion guard
    guard = data["contagion_guard"]
    assert guard["guard_active"] is True
    assert guard["hazard_detected"] is False
    assert guard["max_spectral_radius_rho"] < guard["hazard_threshold_rho"]

    # Micro-rebalance audits
    audits = data["rebalancing_audits"]
    assert len(audits) >= 1
    for audit in audits:
        assert audit["order_chunk_notional_usdt"] <= 5.00
        assert audit["execution_status"] == "SIMULATED_FILLED"
        assert audit["exchange_filters_compliant"] is True

    # Ledger & Solvency
    ledger = data["ledger"]
    solvency = data["solvency"]
    assert ledger["zero_balance_drift"] is True
    assert abs(ledger["drift"]) < 1e-15
    assert solvency["zero_balance_drift_verified"] is True
    assert solvency["unencumbered_cash_verified"] is True

    # Merkle DAG chaining
    assert data["upstream_hash"] == PHASE_298_PARENT_HASH
    assert len(data["phase_hash"]) == 64
    assert len(data["merkle_root"]) == 64


def test_canary_portfolio_rebalancing_404_missing_directory(tmp_path: Path) -> None:
    """Verifies that missing evidence directory returns 404 Not Found."""
    non_existent = tmp_path / "does_not_exist"
    app = create_app(canary_phase_dir=non_existent)
    client = TestClient(app)

    response = client.get("/api/v1/canary/portfolio-rebalancing")
    assert response.status_code == 404
    assert "unavailable" in response.json()["detail"].lower()


def test_canary_portfolio_rebalancing_404_missing_summary(tmp_path: Path) -> None:
    """Verifies that missing summary file returns 404 Not Found."""
    phase_dir = _build_synthetic_phase299_artifacts(tmp_path / "phase299")
    summary_file = phase_dir / "portfolio-rebalancing-summary.json"
    summary_file.unlink()

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/portfolio-rebalancing")
    assert response.status_code == 404


def test_canary_portfolio_rebalancing_404_missing_required_artifact(tmp_path: Path) -> None:
    """Verifies that missing required artifact (orders or db) returns 404."""
    phase_dir = _build_synthetic_phase299_artifacts(tmp_path / "phase299")
    orders_file = phase_dir / "canary-orders.jsonl"
    orders_file.unlink()

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/portfolio-rebalancing")
    assert response.status_code == 404


def test_canary_portfolio_rebalancing_503_tampered_hash(tmp_path: Path) -> None:
    """Verifies that SHA-256 hash mismatch triggers 503 Service Unavailable."""
    phase_dir = _build_synthetic_phase299_artifacts(
        tmp_path / "phase299",
        tamper_file="canary-orders.jsonl",
    )
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/portfolio-rebalancing")
    assert response.status_code == 503
    assert "integrity verification failed" in response.json()["detail"].lower()


def test_canary_portfolio_rebalancing_503_balance_drift_exceeded(tmp_path: Path) -> None:
    """Verifies that balance drift >= 1e-15 USDT triggers 503 Service Unavailable."""
    phase_dir = _build_synthetic_phase299_artifacts(
        tmp_path / "phase299",
        drift="0.000000000001",
        zero_drift=False,
    )
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/portfolio-rebalancing")
    assert response.status_code == 503


def test_canary_portfolio_rebalancing_503_upstream_merkle_dag_mismatch(tmp_path: Path) -> None:
    """Verifies that mismatch in upstream Phase 298 Merkle DAG hash triggers 503."""
    phase_dir = _build_synthetic_phase299_artifacts(
        tmp_path / "phase299",
        upstream_hash="deadbeef" * 8,
    )
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/portfolio-rebalancing")
    assert response.status_code == 503


def test_direct_loader_validation(tmp_path: Path) -> None:
    """Directly tests load_verified_canary_portfolio_rebalancing behavior and error types."""
    phase_dir = _build_synthetic_phase299_artifacts(tmp_path / "phase299")

    # Direct nominal call
    res = load_verified_canary_portfolio_rebalancing(phase_dir)
    assert isinstance(res, CanaryPortfolioRebalancingResponse)
    assert res.phase == "phase_299"
    assert res.status == "PORTFOLIO_REBALANCING_VERIFIED"
    assert len(res.allocations) == 3

    # Direct missing dir
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_portfolio_rebalancing(tmp_path / "nonexistent")

    # Direct drift failure
    bad_drift_dir = _build_synthetic_phase299_artifacts(
        tmp_path / "bad_drift",
        drift="1e-14",
    )
    with pytest.raises(CanaryEvidenceIntegrityError, match="strict tolerance"):
        load_verified_canary_portfolio_rebalancing(bad_drift_dir)


def test_canary_summary_endpoint_with_phase299(tmp_path: Path) -> None:
    """Verifies that GET /api/v1/canary/summary recognizes Phase 299 and manifest_version=4."""
    phase_dir = _build_synthetic_phase299_artifacts(tmp_path / "phase299")
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    response = client.get("/api/v1/canary/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["verified"] is True
    assert data["phase"] == "phase_299"
    assert data["daemon_status"] == "PORTFOLIO_REBALANCING_VERIFIED"
    assert data["manifest_version"] == 4
    assert "BTCUSDT" in data["candidates"]

    # Direct summary loader
    summary_resp = load_verified_canary_summary(phase_dir)
    assert summary_resp.phase == "phase_299"
    assert summary_resp.manifest_version == 4
