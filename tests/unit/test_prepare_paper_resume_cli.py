from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from autonomous_futures.domain.risk import ResumeEvidence
from autonomous_futures.paper.candidate_registry import (
    build_candidate_registry_manifest,
    write_candidate_registry,
)
from autonomous_futures.paper.resume_control import PaperRecoveryPreflight

START = datetime(2026, 9, 13, 6, 30, tzinfo=UTC)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.prepare_paper_resume import main  # noqa: E402


def _write_inputs(tmp_path: Path, *, operator_approved: bool = True) -> tuple[Path, Path]:
    evidence_path = tmp_path / "evidence.json"
    preflight_path = tmp_path / "preflight.json"
    evidence_path.write_text(
        ResumeEvidence(
            reconciled=True,
            incident_resolved=True,
            data_fresh=True,
            risk_healthy=True,
            operator_approved=operator_approved,
        ).model_dump_json(),
        encoding="utf-8",
    )
    preflight_path.write_text(
        PaperRecoveryPreflight(
            observed_at=START,
            breaker_sidecar_state="HALTED",
            daemon_health_state="HALTED",
            daemon_status="RUNNING",
            heartbeat_fresh=True,
            scheduler_status="IDLE",
            scheduler_heartbeat_fresh=True,
            ledger_integrity="ok",
            ledger_opens=166,
            ledger_closes=166,
            dirty_intents=0,
            unmatched_opens=0,
            persisted_positions=0,
            active_positions=0,
            candidate_registry_hash="a" * 64,
            candidate_count=0,
            orders_submitted=0,
            execution_authority=False,
            live_trading_activation=False,
            zero_private_credentials=True,
        ).model_dump_json(),
        encoding="utf-8",
    )
    return evidence_path, preflight_path


def _argv(evidence_path: Path, preflight_path: Path, output_path: Path) -> list[str]:
    return [
        "--evidence-file",
        str(evidence_path),
        "--preflight-file",
        str(preflight_path),
        "--output",
        str(output_path),
        "--request-id",
        "paper-resume-20260913-0630",
        "--created-at",
        "2026-09-13T06:30:00Z",
        "--expires-at",
        "2026-09-13T06:40:00Z",
    ]


def test_cli_prepares_non_authoritative_request(tmp_path: Path, capsys) -> None:
    evidence_path, preflight_path = _write_inputs(tmp_path)
    output_path = tmp_path / "requests" / "resume-request.json"

    assert main(_argv(evidence_path, preflight_path, output_path)) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ready_for_operator_apply"
    assert result["paper_activation"] is False
    assert result["execution_authority"] is False
    assert result["testnet_activation"] is False
    assert result["live_activation"] is False
    assert output_path.is_file()
    assert not (tmp_path / "paper-circuit-breaker-state.json").exists()


def test_cli_blocks_invalid_evidence_without_output(tmp_path: Path, capsys) -> None:
    evidence_path, preflight_path = _write_inputs(tmp_path, operator_approved=False)
    output_path = tmp_path / "resume-request.json"

    assert main(_argv(evidence_path, preflight_path, output_path)) == 2

    result = json.loads(capsys.readouterr().out)
    assert result == {"reason": "invalid_input", "status": "blocked"}
    assert not output_path.exists()


def test_cli_captures_current_storage_read_only(tmp_path: Path, capsys) -> None:
    evidence_path, _ = _write_inputs(tmp_path)
    storage = tmp_path / "paper_live"
    storage.mkdir()
    health = {
        "daemon_status": "RUNNING",
        "last_heartbeat_utc": START.isoformat(),
        "circuit_breaker_status": "HALTED",
        "active_positions_count": 0,
        "active_positions": {},
        "zero_order_safety_invariants": {
            "orders_submitted": 0,
            "execution_authority": False,
            "live_trading_activation": False,
            "zero_private_credentials": True,
        },
    }
    (storage / "paper-daemon-health.json").write_text(json.dumps(health), encoding="utf-8")
    (storage / "paper-circuit-breaker-state.json").write_text(
        json.dumps({"circuit_breaker_status": "HALTED"}), encoding="utf-8"
    )
    scheduler_dir = storage / "scheduler"
    scheduler_dir.mkdir()
    (scheduler_dir / "scheduler-health.json").write_text(
        json.dumps({"status": "IDLE", "updated_at": START.isoformat()}), encoding="utf-8"
    )
    write_candidate_registry(
        storage / "candidate_registry.json",
        build_candidate_registry_manifest(updated_at=START),
    )
    ledger = storage / "paper-ledger.sqlite3"
    with sqlite3.connect(ledger) as connection:
        connection.executescript(
            """
            CREATE TABLE paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL
            );
            CREATE TABLE paper_position_state (
                trade_id TEXT PRIMARY KEY,
                state_version INTEGER NOT NULL,
                state_json TEXT NOT NULL
            );
            CREATE TABLE paper_position_update_intent (
                trade_id TEXT PRIMARY KEY,
                intent TEXT NOT NULL
            );
            """
        )
    before = ledger.read_bytes()
    output_path = tmp_path / "storage-resume-request.json"
    args = _argv(evidence_path, tmp_path / "unused-preflight.json", output_path)
    preflight_index = args.index("--preflight-file")
    del args[preflight_index : preflight_index + 2]
    args[preflight_index:preflight_index] = ["--storage-dir", str(storage)]

    assert main(args) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ready_for_operator_apply"
    assert output_path.is_file()
    assert ledger.read_bytes() == before
