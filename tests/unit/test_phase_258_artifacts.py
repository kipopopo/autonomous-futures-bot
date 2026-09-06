"""Validation test suite for Phase 258 live paper forward-testing artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path


def test_phase_258_summary_json_integrity() -> None:
    """Verify live-paper-summary.json schema, metrics, and safety invariants."""
    summary_path = Path("artifacts/research/phase258/live-paper-summary.json")
    assert summary_path.is_file(), f"Missing artifact: {summary_path}"

    with summary_path.open(encoding="utf-8") as f:
        data = json.load(f)

    # 1. Top-level metadata
    assert data["phase"] == "phase_258"
    assert data["milestone"] == "milestone_1"

    # 2. Run metadata
    run_meta = data["run_metadata"]
    assert run_meta["target_endpoint"] == "wss://fstream.binance.com"
    assert set(run_meta["symbols"]) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"}
    assert run_meta["duration_target_seconds"] == 600.0
    assert run_meta["duration_actual_seconds"] >= 600.0
    assert run_meta["host"]["hostname"] == "kipopopo"
    assert run_meta["host"]["operator"] == "afbot"
    assert run_meta["host"]["ip"] == "147.79.18.15"

    # 3. Network telemetry
    net = data["network_telemetry"]
    assert net["total_messages_received"] >= 100_000
    assert net["total_throughput_msgs_per_sec"] >= 100.0
    assert net["latency_ms"]["p50"] > 0.0
    assert net["latency_ms"]["p99"] > 0.0

    # 4. Shared portfolio margin and zero drift
    margin = data["shared_portfolio_margin"]
    assert Decimal(margin["starting_capital"]) == Decimal("100.00")
    assert Decimal(margin["final_cash"]) == Decimal("100.00")
    assert Decimal(margin["drift_amount"]) == Decimal("0.00")
    assert margin["zero_balance_drift"] is True

    # 5. Circuit breaker telemetry
    cb = data["circuit_breaker_telemetry"]
    assert cb["initial_state"] == "NORMAL"
    assert cb["final_state"] == "NORMAL"
    assert cb["evaluations_count"] >= 100_000

    # 6. Cohort health
    cohort = data["cohort_health"]
    assert cohort["cohort_status"] == "healthy"
    assert cohort["expected_candidate_count"] == 4
    assert cohort["reported_candidate_count"] == 4
    for _cand_id, cand_info in cohort["candidates"].items():
        assert cand_info["health_status"] == "healthy"
        assert cand_info["maturity_status"] == "maturing"
        assert len(cand_info["artifact_hash"]) == 64

    # 7. Strict safety invariants
    safety = data["safety_invariants"]
    assert safety["execution_authority"] is False
    assert safety["orders_submitted"] == 0
    assert safety["api_keys_loaded"] == 0
    assert safety["authenticated_endpoints_accessed"] is False
    assert safety["read_only_streams_only"] is True
    assert safety["promotion_state"] == "unpromoted"
    assert safety["live_trading_activation"] is False
    assert safety["zero_secret_leakage"] is True


def test_phase_258_sqlite_databases_integrity() -> None:
    """Verify SQLite databases exist, have valid schemas, and match SHA-256 hashes."""
    summary_path = Path("artifacts/research/phase258/live-paper-summary.json")
    with summary_path.open(encoding="utf-8") as f:
        summary_data = json.load(f)
    db_meta = summary_data["sqlite_persistence"]["databases"]

    # 1. paper-ledger.sqlite3
    ledger_path = Path("artifacts/research/phase258/paper-ledger.sqlite3")
    assert ledger_path.is_file()
    ledger_sha = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    assert ledger_sha == db_meta["paper_ledger"]["sha256"]
    with sqlite3.connect(ledger_path) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "paper_ledger_events" in tables

    # 2. paper-lifecycle.sqlite3
    lifecycle_path = Path("artifacts/research/phase258/paper-lifecycle.sqlite3")
    assert lifecycle_path.is_file()
    lifecycle_sha = hashlib.sha256(lifecycle_path.read_bytes()).hexdigest()
    assert lifecycle_sha == db_meta["paper_lifecycle"]["sha256"]
    with sqlite3.connect(lifecycle_path) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "paper_lifecycle_marks" in tables

    # 3. paper-observations.sqlite3
    obs_path = Path("artifacts/research/phase258/paper-observations.sqlite3")
    assert obs_path.is_file()
    obs_sha = hashlib.sha256(obs_path.read_bytes()).hexdigest()
    assert obs_sha == db_meta["paper_observations"]["sha256"]
    with sqlite3.connect(obs_path) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "paper_observations" in tables
