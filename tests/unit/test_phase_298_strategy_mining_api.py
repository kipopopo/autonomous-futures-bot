"""Unit tests for Phase 298 Strategy Mining FastAPI endpoint and loader.

Tests cover:
- 200 OK nominal endpoint response with full schema and invariant validation.
- 404 Not Found error mapping for missing evidence directory or artifacts.
- 503 Service Unavailable error mapping for tampered SHA-256 hashes or balance drift breaches.
- Direct loader validation of Merkle DAG integrity, 5 OOS gates, hot-reload, and zero drift.
- Summary endpoint compatibility with Phase 298 strategy mining manifests.
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
    CanaryStrategyMiningResponse,
    load_verified_canary_strategy_mining,
    load_verified_canary_summary,
)

PHASE_297_PARENT_HASH = "257f83f794465f3b89bfd9dbc25a2bf949d9fe315ecd97e2108c027ca3475668"


def _build_synthetic_phase298_artifacts(
    phase_dir: Path,
    *,
    drift: str = "0.00",
    zero_drift: bool = True,
    tamper_file: str | None = None,
    upstream_hash: str = PHASE_297_PARENT_HASH,
) -> Path:
    """Helper to populate a clean, fully-formed Phase 298 synthetic evidence directory."""
    phase_dir.mkdir(parents=True, exist_ok=True)

    # 1. Telemetry SQLite3 database
    db_path = phase_dir / "canary-strategy-mining-telemetry.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE strategy_mining_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT,
            symbol TEXT,
            family TEXT,
            lookback INTEGER,
            zscore_threshold REAL,
            stop_atr_multiplier REAL,
            return_pct REAL,
            drawdown_pct REAL,
            profit_factor REAL,
            trade_count INTEGER,
            resilience_passed INTEGER,
            qualified INTEGER,
            status TEXT
        )
        """
    )
    cur.execute(
        """
        INSERT INTO strategy_mining_candidates
        (candidate_id, symbol, family, lookback, zscore_threshold, stop_atr_multiplier,
         return_pct, drawdown_pct, profit_factor, trade_count, resilience_passed, qualified, status)
        VALUES
        ('cand-btcusdt-dcb-003', 'BTCUSDT', 'DonchianBreakout', 24, 1.65, 2.1,
         4.82, 6.15, 1.62, 18, 1, 1, 'ADMITTED'),
        ('cand-ethusdt-rgb-002', 'ETHUSDT', 'RegimeVolatilityBreakout', 18, 1.45, 1.9,
         3.91, 5.40, 1.48, 14, 1, 1, 'ADMITTED'),
        ('cand-solusdt-msm-001', 'SOLUSDT', 'MicrostructureMomentum', 15, 1.75, 2.2,
         5.60, 7.20, 1.75, 22, 1, 1, 'ADMITTED')
        """
    )
    cur.execute(
        """
        CREATE TABLE parameter_mutations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mutation_id TEXT,
            generation INTEGER,
            parent_candidate_id TEXT,
            mutated_candidate_id TEXT,
            family TEXT,
            parameter_diffs_json TEXT,
            seed INTEGER,
            timestamp_utc TEXT
        )
        """
    )
    cur.execute(
        """
        INSERT INTO parameter_mutations
        (mutation_id, generation, parent_candidate_id, mutated_candidate_id, family,
         parameter_diffs_json, seed, timestamp_utc)
        VALUES
        ('mut-btcusdt-gen1-001', 1, 'cand-btcusdt-dcb-002', 'cand-btcusdt-dcb-003',
         'DonchianBreakout', '{"lookback": [20, 24]}', 1001, '2026-09-22T08:00:00+00:00'),
        ('mut-ethusdt-gen1-001', 1, 'cand-ethusdt-dcb-003', 'cand-ethusdt-rgb-002',
         'RegimeVolatilityBreakout', '{"regime_window": [14, 18]}', 2002,
         '2026-09-22T08:00:00+00:00'),
        ('mut-solusdt-gen1-001', 1, 'cand-solusdt-rgb-001', 'cand-solusdt-msm-001',
         'MicrostructureMomentum', '{"ofi_window": [10, 15]}', 3003,
         '2026-09-22T08:00:00+00:00')
        """
    )
    cur.execute(
        """
        CREATE TABLE hot_reload_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            candidate_id TEXT,
            symbol TEXT,
            manifest_version INTEGER,
            registry_hash TEXT,
            reloaded_at_utc TEXT,
            status TEXT,
            process_restarted INTEGER,
            open_trades_mutated INTEGER
        )
        """
    )
    cur.execute(
        """
        INSERT INTO hot_reload_events
        (event_id, candidate_id, symbol, manifest_version, registry_hash, reloaded_at_utc,
         status, process_restarted, open_trades_mutated)
        VALUES
        ('hr-btcusdt-001', 'cand-btcusdt-dcb-003', 'BTCUSDT', 3,
         'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
         '2026-09-22T08:00:00+00:00', 'ADMITTED_AND_HOT_RELOADED', 0, 0),
        ('hr-ethusdt-001', 'cand-ethusdt-rgb-002', 'ETHUSDT', 3,
         'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
         '2026-09-22T08:00:00+00:00', 'ADMITTED_AND_HOT_RELOADED', 0, 0),
        ('hr-solusdt-001', 'cand-solusdt-msm-001', 'SOLUSDT', 3,
         'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
         '2026-09-22T08:00:00+00:00', 'ADMITTED_AND_HOT_RELOADED', 0, 0)
        """
    )
    conn.commit()
    conn.close()

    # 2. Orders jsonl
    orders_file = phase_dir / "canary-orders.jsonl"
    orders_content = (
        '{"order_id": "sim-ord-1", "symbol": "BTCUSDT", "side": "BUY", "status": "FILLED"}\n'
        '{"order_id": "sim-ord-2", "symbol": "ETHUSDT", "side": "BUY", "status": "FILLED"}\n'
        '{"order_id": "sim-ord-3", "symbol": "SOLUSDT", "side": "BUY", "status": "FILLED"}\n'
    )
    orders_file.write_text(orders_content, encoding="utf-8")

    # 3. Report json
    report_file = phase_dir / "canary-strategy-mining-report.json"
    report_data = {
        "phase": "phase_298",
        "generated_at_utc": "2026-09-22T08:00:00+00:00",
        "circuit_state": "NORMAL",
        "ledger_reconciliation": {
            "starting_equity_usdt": "100.00",
            "cash_usdt": "100.00",
            "allocated_margin_usdt": "0.00",
            "unrealized_pnl_usdt": "0.00",
            "realized_pnl_usdt": "0.00",
            "total_equity_usdt": "100.00",
            "total_fees_usdt": "0.00",
            "total_slippage_usdt": "0.00",
            "drift_usdt": drift,
            "zero_drift_verified": zero_drift,
        },
        "gate_metrics": {
            "passing_counts": {
                "walk_forward_return": 6,
                "worst_drawdown": 6,
                "profit_factor": 5,
                "trade_count": 5,
                "microstructure_resilience": 3,
            },
            "rejection_counts": {
                "walk_forward_return": 1,
                "worst_drawdown": 1,
                "profit_factor": 2,
                "trade_count": 2,
                "microstructure_resilience": 4,
            },
            "total_evaluated": 9,
            "total_passed": 3,
            "total_rejected": 6,
        },
    }
    report_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    # 4. Paper summary json
    paper_summary_file = phase_dir / "paper-summary.json"
    paper_summary_data = {
        "phase": "phase_298",
        "circuit_state": "NORMAL",
        "candidates": ["cand-btcusdt-dcb-003", "cand-ethusdt-rgb-002", "cand-solusdt-msm-001"],
    }
    paper_summary_file.write_text(json.dumps(paper_summary_data, indent=2), encoding="utf-8")

    # Compute hashes
    db_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    orders_hash = hashlib.sha256(orders_file.read_bytes()).hexdigest()
    report_hash = hashlib.sha256(report_file.read_bytes()).hexdigest()
    paper_hash = hashlib.sha256(paper_summary_file.read_bytes()).hexdigest()

    if tamper_file == "canary-orders.jsonl":
        orders_hash = "0" * 64
    elif tamper_file == "canary-strategy-mining-report.json":
        report_hash = "0" * 64

    # 5. Summary json
    summary_file = phase_dir / "strategy-mining-summary.json"
    summary_data = {
        "phase": "phase_298",
        "status": "STRATEGY_MINING_VERIFIED",
        "timestamp_utc": "2026-09-22T08:00:00+00:00",
        "circuit_state": "NORMAL",
        "paper_safe": True,
        "execution_authority": False,
        "zero_balance_drift": zero_drift,
        "drift_usdt": drift,
        "starting_capital_usdt": "100.00",
        "final_cash_usdt": "100.00",
        "final_equity_usdt": "100.00",
        "realized_pnl_usdt": "0.00",
        "total_fees_usdt": "0.00",
        "total_slippage_usdt": "0.00",
        "manifest_version": 3,
        "registry_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "candidates": ["cand-btcusdt-dcb-003", "cand-ethusdt-rgb-002", "cand-solusdt-msm-001"],
        "artifact_hashes": {
            "canary-strategy-mining-telemetry.sqlite3": db_hash,
            "canary-orders.jsonl": orders_hash,
            "canary-strategy-mining-report.json": report_hash,
            "paper-summary.json": paper_hash,
        },
        "upstream_merkle_dag": {
            "phase297_summary_hash": upstream_hash,
        },
    }
    summary_file.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

    return phase_dir


def test_strategy_mining_endpoint_nominal_200_ok(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/strategy-mining returns 200 OK with valid contract."""
    target = tmp_path / "artifacts" / "research" / "phase298"
    phase_dir = _build_synthetic_phase298_artifacts(target)
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-mining")
    assert res.status_code == 200

    data = res.json()
    assert data["verified"] is True
    assert data["phase"] == "phase_298"
    assert data["status"] == "STRATEGY_MINING_VERIFIED"
    assert data["paper_safe"] is True
    assert data["execution_authority"] is False
    assert data["circuit_state"] == "NORMAL"

    # Validate active candidates
    assert len(data["candidates"]) >= 3
    cand_ids = {c["candidate_id"] for c in data["candidates"]}
    assert "cand-btcusdt-dcb-003" in cand_ids
    assert "cand-ethusdt-rgb-002" in cand_ids
    assert "cand-solusdt-msm-001" in cand_ids
    for c in data["candidates"]:
        assert c["resilience_passed"] is True
        assert c["qualified"] is True
        assert c["profit_factor"] >= 1.05
        assert c["drawdown_pct"] <= 15.0

    # Validate mutations
    assert len(data["mutations"]) >= 3
    for m in data["mutations"]:
        assert m["generation"] >= 1
        assert len(m["mutation_id"]) > 0
        assert len(m["family"]) > 0

    # Validate 5-gate scorecard metrics
    gm = data["gate_metrics"]
    assert len(gm["gate_names"]) == 5
    assert gm["total_evaluated"] >= 3
    assert gm["total_passed"] >= 3
    assert gm["passing_counts"]["walk_forward_return"] >= 1

    # Validate hot-reload status
    hr = data["hot_reload"]
    assert hr["previous_version"] == 2
    assert hr["new_version"] == 3
    assert hr["reload_status"] == "ADMITTED_AND_HOT_RELOADED"
    assert hr["process_restarted"] is False
    assert hr["open_trades_mutated"] is False

    # Validate Double-Entry Ledger Reconciliation
    ledger = data["ledger"]
    assert ledger["starting_equity"] == 100.0
    assert ledger["cash"] == 100.0
    assert abs(ledger["drift"]) < 1e-15
    assert ledger["zero_balance_drift"] is True

    # Validate Double-Entry Solvency Item
    solvency = data["solvency"]
    assert solvency["starting_equity_usdt"] == 100.0
    assert solvency["cash_usdt"] == 100.0
    assert abs(solvency["drift_usdt"]) < 1e-15
    assert solvency["zero_balance_drift_verified"] is True
    assert solvency["cash_reserve_pct"] >= 40.0
    assert solvency["unencumbered_cash_verified"] is True

    # Validate Cryptographic SHA-256 Merkle DAG hashes linking Phase 297
    assert len(data["phase_hash"]) == 64
    assert len(data["upstream_hash"]) == 64
    assert data["upstream_hash"] == PHASE_297_PARENT_HASH
    assert len(data["merkle_root"]) == 64


def test_strategy_mining_endpoint_missing_dir_fails_404(tmp_path: Path) -> None:
    """Verify endpoint returns 404 when evidence directory does not exist."""
    missing_dir = tmp_path / "non_existent_phase298"
    app = create_app(canary_phase_dir=missing_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-mining")
    assert res.status_code == 404
    assert "unavailable" in res.json()["detail"]


def test_strategy_mining_endpoint_missing_artifact_fails_404(tmp_path: Path) -> None:
    """Verify endpoint returns 404 when any required artifact is missing."""
    phase_dir = tmp_path / "incomplete_phase298"
    phase_dir.mkdir()
    (phase_dir / "strategy-mining-summary.json").write_text(json.dumps({"phase": "phase_298"}))

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-mining")
    assert res.status_code == 404
    assert "unavailable" in res.json()["detail"]


def test_strategy_mining_endpoint_tampered_hash_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when an artifact hash does not match summary."""
    phase_dir = _build_synthetic_phase298_artifacts(
        tmp_path / "tampered_phase298",
        tamper_file="canary-strategy-mining-report.json",
    )
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-mining")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_strategy_mining_endpoint_balance_drift_exceeded_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when ledger drift breaches tolerance |drift| < 10^-15 USDT."""
    phase_dir = _build_synthetic_phase298_artifacts(
        tmp_path / "drift_breached_phase298",
        drift="0.50000000",
        zero_drift=False,
    )
    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-mining")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_strategy_mining_endpoint_upstream_mismatch_fails_503(tmp_path: Path) -> None:
    """Verify endpoint returns 503 when upstream Phase 297 hash does not match actual file."""
    research_dir = tmp_path / "artifacts" / "research"
    p297_dir = research_dir / "phase297"
    p298_dir = research_dir / "phase298"
    p297_dir.mkdir(parents=True)

    # Real upstream file has hash H1
    (p297_dir / "stress-summary.json").write_text('{"phase": "phase_297"}')

    # Summary declares H2 (mismatch)
    _build_synthetic_phase298_artifacts(
        p298_dir,
        upstream_hash="1" * 64,
    )

    app = create_app(canary_phase_dir=p298_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/strategy-mining")
    assert res.status_code == 503
    assert "integrity verification failed" in res.json()["detail"]


def test_load_verified_canary_strategy_mining_direct(tmp_path: Path) -> None:
    """Verify direct Python loader returns valid CanaryStrategyMiningResponse."""
    phase_dir = _build_synthetic_phase298_artifacts(tmp_path / "phase298")
    resp = load_verified_canary_strategy_mining(phase_dir)

    assert isinstance(resp, CanaryStrategyMiningResponse)
    assert resp.phase == "phase_298"
    assert resp.status == "STRATEGY_MINING_VERIFIED"
    assert resp.paper_safe is True
    assert resp.execution_authority is False
    assert resp.circuit_state == "NORMAL"
    assert len(resp.candidates) >= 3
    assert len(resp.mutations) >= 3
    assert resp.ledger.drift < 1e-15
    assert resp.ledger.zero_balance_drift is True
    assert resp.solvency.zero_balance_drift_verified is True
    assert resp.upstream_hash == PHASE_297_PARENT_HASH


def test_load_verified_canary_strategy_mining_missing_raises_not_found(tmp_path: Path) -> None:
    """Verify direct loader raises CanaryEvidenceNotFoundError on missing directory."""
    with pytest.raises(CanaryEvidenceNotFoundError):
        load_verified_canary_strategy_mining(tmp_path / "non_existent")


def test_load_verified_canary_strategy_mining_tampered_raises_integrity_error(
    tmp_path: Path,
) -> None:
    """Verify direct loader raises CanaryEvidenceIntegrityError on hash mismatch."""
    phase_dir = _build_synthetic_phase298_artifacts(
        tmp_path / "tampered_direct",
        tamper_file="canary-orders.jsonl",
    )
    with pytest.raises(CanaryEvidenceIntegrityError):
        load_verified_canary_strategy_mining(phase_dir)


def test_load_verified_canary_strategy_mining_directory_fallback(tmp_path: Path) -> None:
    """Verify loader falls back to target_dir.parent / 'phase298'."""
    research_dir = tmp_path / "artifacts" / "research"
    p298_dir = research_dir / "phase298"
    sub_dir = research_dir / "subphase"
    sub_dir.mkdir(parents=True)

    _build_synthetic_phase298_artifacts(p298_dir)

    res = load_verified_canary_strategy_mining(sub_dir)
    assert res.phase == "phase_298"
    assert res.verified is True


def test_canary_summary_recognizes_phase298(tmp_path: Path) -> None:
    """Verify GET /api/v1/canary/summary transparently recognizes Phase 298 summary."""
    phase_dir = _build_synthetic_phase298_artifacts(tmp_path / "summary_phase298")

    summary_direct = load_verified_canary_summary(phase_dir)
    assert summary_direct.phase == "phase_298"
    assert summary_direct.daemon_status == "STRATEGY_MINING_VERIFIED"
    assert summary_direct.manifest_version == 3

    app = create_app(canary_phase_dir=phase_dir)
    client = TestClient(app)

    res = client.get("/api/v1/canary/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["phase"] == "phase_298"
    assert data["daemon_status"] == "STRATEGY_MINING_VERIFIED"
    assert data["circuit_state"] == "NORMAL"
    assert data["manifest_version"] == 3
