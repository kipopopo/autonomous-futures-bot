"""Unit tests for Phase 259 empirical research and telemetry artifacts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

PHASE_259_ARTIFACTS_DIR = (
    Path(__file__).resolve().parents[2] / "artifacts" / "research" / "phase259"
)


def test_phase_259_artifacts_directory_exists() -> None:
    assert PHASE_259_ARTIFACTS_DIR.is_dir(), f"Missing {PHASE_259_ARTIFACTS_DIR}"


def test_phase_259_summary_json_integrity() -> None:
    summary_path = PHASE_259_ARTIFACTS_DIR / "live-paper-summary.json"
    assert summary_path.is_file(), f"Missing {summary_path}"
    data = json.loads(summary_path.read_text(encoding="utf-8"))

    margin = data["shared_portfolio_margin"]
    assert margin["starting_capital"] == "100.00"
    assert margin["final_cash"] == "100.00"
    assert margin["zero_balance_drift"] is True
    assert margin["drift_amount"] == "0.00"

    invariants = data["safety_invariants"]
    assert invariants["orders_submitted"] == 0
    assert invariants["execution_authority"] is False
    assert invariants["api_keys_loaded"] == 0
    assert invariants["read_only_streams_only"] is True
    assert invariants["promotion_state"] == "unpromoted"
    assert invariants["zero_secret_leakage"] is True

    run_meta = data["run_metadata"]
    assert set(run_meta["symbols"]) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"}
    assert run_meta["host"]["operator"] == "afbot"
    assert run_meta["host"]["ip"] == "147.79.18.15"


def test_phase_259_daemon_health_json_integrity() -> None:
    health_path = PHASE_259_ARTIFACTS_DIR / "paper-daemon-health.json"
    assert health_path.is_file(), f"Missing {health_path}"
    data = json.loads(health_path.read_text(encoding="utf-8"))

    assert data["daemon_status"] == "SHUTDOWN_CLEAN"
    assert data["starting_capital_usdt"] == "100.00"
    assert data["current_cash_usdt"] == "100.00"
    assert data["current_equity_usdt"] == "100.00"
    assert data["margin_utilization_pct"] <= 80.0
    assert data["reserve_buffer_pct"] >= 20.0
    assert data["circuit_breaker_status"] == "NORMAL"
    assert data["feed_messages_received"] >= 1000
    assert data["feed_reconnects_count"] == 0
    assert data["symbols_monitored"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]

    invariants = data["zero_order_safety_invariants"]
    assert invariants["orders_submitted"] == 0
    assert invariants["execution_authority"] is False
    assert invariants["live_trading_activation"] is False
    assert invariants["paper_activation"] is True
    assert invariants["promotion_state"] == "unpromoted"
    assert invariants["zero_private_credentials"] is True


def test_phase_259_sqlite_ledgers_integrity() -> None:
    ledger_db = PHASE_259_ARTIFACTS_DIR / "paper-ledger.sqlite3"
    lifecycle_db = PHASE_259_ARTIFACTS_DIR / "paper-lifecycle.sqlite3"
    obs_db = PHASE_259_ARTIFACTS_DIR / "paper-observations.sqlite3"

    for p in (ledger_db, lifecycle_db, obs_db):
        assert p.is_file(), f"Missing {p}"
        assert p.stat().st_size == 8192

    # Verify tables exist
    with sqlite3.connect(ledger_db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "paper_ledger_events" in tables

    with sqlite3.connect(lifecycle_db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "paper_lifecycle_marks" in tables

    with sqlite3.connect(obs_db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "paper_observations" in tables
