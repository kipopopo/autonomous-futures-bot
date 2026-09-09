"""Empirical Challenger 2 Fault Injection & Verification Suite.

Adversarially tests scripts/check_autonomous_pipeline_health.py across all
required failure modes, edge cases, and CLI options:
1. --help verification (all flags present)
2. Healthy baseline -> exit code 0
3. Stale paper daemon heartbeat (>120s) -> exit code 1
4. Stale scheduler heartbeat (>120s) -> exit code 1
5. Scheduler in BACKOFF status -> exit code 1
6. Missing health JSONs without allow-missing flag -> exit code 2
   (and verification that --allow-missing-scheduler permits missing scheduler -> exit code 0)
7. Corrupt SQLite DB -> exit code 2
8. Dirty recovery intent in paper_position_update_intent -> exit code 2
9. Tampered candidate_registry.json (hash mismatch) -> exit code 2
10. Dead PID with status RUNNING -> exit code 2
11. --json schema verification (all top-level and nested keys present)
12. --quiet concise status verification (HEALTHY, DEGRADED, CRITICAL)
13. --stale-threshold-seconds dynamic boundary shift verification
14. Read-only lock non-interference verification
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "scripts" / "check_autonomous_pipeline_health.py"

# Import domain helpers to generate authentic artifacts
sys.path.insert(0, str(REPO_ROOT / "src"))
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    CandidateManifestEntry,
    build_candidate_registry_manifest,
    write_candidate_registry,
)
from autonomous_futures.paper.sqlite_ledger import SqlitePaperLedger  # noqa: E402


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute the health CLI subprocess with given arguments."""
    cmd = [sys.executable, str(CLI_PATH), *args]
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def setup_base_environment(
    base_dir: Path,
    now: datetime,
) -> dict[str, Path]:
    """Create a fully populated, 100% HEALTHY baseline storage environment."""
    storage_dir = base_dir / "paper_live"
    storage_dir.mkdir(parents=True, exist_ok=True)
    now_iso = now.isoformat()

    # 1. Candidate artifact
    cand_dir = storage_dir / "artifacts" / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    candidate_file = cand_dir / "cand_01.json"
    candidate_content = {
        "candidate_id": "cand-01",
        "symbol": "BTCUSDT",
        "parameters": {"fast_period": 14, "slow_period": 30},
    }
    candidate_file.write_text(json.dumps(candidate_content, indent=2), encoding="utf-8")

    # 2. Candidate registry manifest
    manifest_entry = CandidateManifestEntry(
        candidate_id="cand-01",
        candidate_artifact_hash="a" * 64,
        artifact_path="artifacts/candidates/cand_01.json",
        qualification_hash="b" * 64,
        admitted_at=now_iso,
    )
    manifest = build_candidate_registry_manifest(
        symbols={"BTCUSDT": manifest_entry},
        updated_at=now,
        registry_version=1,
    )
    registry_file = storage_dir / "candidate_registry.json"
    write_candidate_registry(registry_file, manifest)

    # 3. Paper ledger DB
    ledger_db = storage_dir / "paper-ledger.sqlite3"
    ledger = SqlitePaperLedger(ledger_db)
    # Initialize schema
    conn = ledger._connect()
    conn.close()

    # 4. Paper lifecycle DB (optional but clean)
    lifecycle_db = storage_dir / "paper-lifecycle.sqlite3"
    life_conn = sqlite3.connect(lifecycle_db)
    life_conn.execute(
        "CREATE TABLE IF NOT EXISTS paper_lifecycle_marks (id INTEGER PRIMARY KEY, mark TEXT)"
    )
    life_conn.close()

    # 5. Paper daemon health JSON
    current_pid = os.getpid()
    daemon_file = storage_dir / "paper-daemon-health.json"
    daemon_payload = {
        "daemon_status": "RUNNING",
        "pid": current_pid,
        "uptime_seconds": 3600.0,
        "last_heartbeat_utc": now_iso,
        "circuit_breaker_status": "NORMAL",
        "symbols_monitored": ["BTCUSDT"],
        "active_positions_count": 0,
        "margin_utilization_pct": 12.5,
        "reserve_buffer_pct": 55.0,
        "zero_order_safety_invariants": {
            "orders_submitted": 0,
            "execution_authority": False,
            "live_trading_activation": False,
            "paper_activation": True,
            "zero_private_credentials": True,
        },
    }
    daemon_file.write_text(json.dumps(daemon_payload, indent=2), encoding="utf-8")

    # 6. Scheduler health JSON
    scheduler_file = storage_dir / "scheduler-health.json"
    scheduler_payload = {
        "status": "IDLE",
        "pid": current_pid,
        "updated_at": now_iso,
        "last_run_at": now_iso,
        "next_run_at": (now + timedelta(hours=1)).isoformat(),
        "consecutive_failures": 0,
        "total_cycles_executed": 3,
        "admitted_candidates_count": 1,
        "last_cycle_result": {
            "cycle_id": "cycle-001",
            "status": "COMPLETED",
            "exit_code": 0,
            "candidate_id": "cand-01",
            "admitted": True,
        },
    }
    scheduler_file.write_text(json.dumps(scheduler_payload, indent=2), encoding="utf-8")

    return {
        "storage_dir": storage_dir,
        "daemon_file": daemon_file,
        "scheduler_file": scheduler_file,
        "registry_file": registry_file,
        "ledger_db": ledger_db,
        "lifecycle_db": lifecycle_db,
    }


def test_cli_help() -> dict[str, Any]:
    """Test Task 0: --help displays cleanly and includes all required CLI flags."""
    res = run_cli(["--help"])
    assert res.returncode == 0, f"--help failed with code {res.returncode}"
    expected_flags = [
        "--help",
        "--storage-dir",
        "--scheduler-dir",
        "--stale-threshold-seconds",
        "--daemon-health-file",
        "--scheduler-health-file",
        "--registry-file",
        "--ledger-db",
        "--lifecycle-db",
        "--allow-missing-scheduler",
        "--now",
        "--json",
        "--quiet",
    ]
    for flag in expected_flags:
        assert flag in res.stdout, f"Missing flag {flag} in --help output"
    return {"passed": True, "exit_code": res.returncode, "checked_flags": len(expected_flags)}


def test_scenario_1_healthy() -> dict[str, Any]:
    """Fault Test 1: Healthy baseline -> exit code 0, status HEALTHY."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 0, f"Expected 0, got {res.returncode}:\n{res.stderr}\n{res.stdout}"
        data = json.loads(res.stdout)
        assert data["status"] == "HEALTHY"
        assert data["exit_code"] == 0
        assert data["summary"]["failures_count"] == 0
        assert data["summary"]["warnings_count"] == 0
        assert len(data["issues"]) == 0
    return {"passed": True, "exit_code": res.returncode, "status": data["status"]}


def test_scenario_2_stale_paper_daemon_heartbeat() -> dict[str, Any]:
    """Fault Test 2: Stale paper daemon heartbeat (>120s) -> exit code 1, status DEGRADED."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    stale_time = now - timedelta(seconds=150)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        daemon_payload = json.loads(env["daemon_file"].read_text(encoding="utf-8"))
        daemon_payload["last_heartbeat_utc"] = stale_time.isoformat()
        env["daemon_file"].write_text(json.dumps(daemon_payload), encoding="utf-8")

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 1, f"Expected 1, got {res.returncode}:\n{res.stderr}\n{res.stdout}"
        data = json.loads(res.stdout)
        assert data["status"] == "DEGRADED"
        assert data["exit_code"] == 1
        assert data["summary"]["warnings_count"] >= 1
        assert any("stale paper daemon heartbeat" in issue for issue in data["issues"])
    return {"passed": True, "exit_code": res.returncode, "status": data["status"]}


def test_scenario_3_stale_scheduler_heartbeat() -> dict[str, Any]:
    """Fault Test 3: Stale scheduler heartbeat (>120s) -> exit code 1, status DEGRADED."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    stale_time = now - timedelta(seconds=180)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        sched_payload = json.loads(env["scheduler_file"].read_text(encoding="utf-8"))
        sched_payload["updated_at"] = stale_time.isoformat()
        env["scheduler_file"].write_text(json.dumps(sched_payload), encoding="utf-8")

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 1, f"Expected 1, got {res.returncode}:\n{res.stderr}\n{res.stdout}"
        data = json.loads(res.stdout)
        assert data["status"] == "DEGRADED"
        assert data["exit_code"] == 1
        assert data["summary"]["warnings_count"] >= 1
        assert any("stale scheduler heartbeat" in issue for issue in data["issues"])
    return {"passed": True, "exit_code": res.returncode, "status": data["status"]}


def test_scenario_4_scheduler_backoff() -> dict[str, Any]:
    """Fault Test 4: Scheduler in BACKOFF status -> exit code 1, status DEGRADED."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        sched_payload = json.loads(env["scheduler_file"].read_text(encoding="utf-8"))
        sched_payload["status"] = "BACKOFF"
        env["scheduler_file"].write_text(json.dumps(sched_payload), encoding="utf-8")

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 1, f"Expected 1, got {res.returncode}:\n{res.stderr}\n{res.stdout}"
        data = json.loads(res.stdout)
        assert data["status"] == "DEGRADED"
        assert data["exit_code"] == 1
        assert any("BACKOFF" in issue for issue in data["issues"])
    return {"passed": True, "exit_code": res.returncode, "status": data["status"]}


def test_scenario_5_missing_health_jsons() -> dict[str, Any]:
    """Fault Test 5: Missing health JSONs without allow-missing flag -> exit code 2, status CRITICAL."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    # 5a: Missing paper-daemon-health.json
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        env["daemon_file"].unlink()
        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 2, f"Expected 2 for missing daemon, got {res.returncode}"
        data = json.loads(res.stdout)
        assert data["status"] == "CRITICAL"
        assert any("paper-daemon-health.json not found" in issue for issue in data["issues"])

    # 5b: Missing scheduler-health.json without --allow-missing-scheduler
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        env["scheduler_file"].unlink()
        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 2, f"Expected 2 for missing scheduler without flag, got {res.returncode}"
        data = json.loads(res.stdout)
        assert data["status"] == "CRITICAL"
        assert any("scheduler-health.json not found" in issue for issue in data["issues"])

    # 5c: Missing scheduler-health.json WITH --allow-missing-scheduler -> exit code 0
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        env["scheduler_file"].unlink()
        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--allow-missing-scheduler",
            "--json",
        ])
        assert res.returncode == 0, f"Expected 0 for missing scheduler with allow flag, got {res.returncode}"
        data = json.loads(res.stdout)
        assert data["status"] == "HEALTHY"

    return {"passed": True, "verified_subcases": ["5a_missing_daemon_crit", "5b_missing_sched_crit", "5c_allow_missing_sched_healthy"]}


def test_scenario_6_corrupt_sqlite_db() -> dict[str, Any]:
    """Fault Test 6: Corrupt SQLite DB -> exit code 2, status CRITICAL."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        # Write corrupted garbage bytes to ledger DB
        env["ledger_db"].write_bytes(b"NOT_A_VALID_SQLITE_DATABASE_CORRUPTED_FILE_DATA_BYTES")

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 2, f"Expected 2 for corrupt SQLite DB, got {res.returncode}"
        try:
            data = json.loads(res.stdout)
        except Exception as exc:
            raise AssertionError(
                f"CLI failed to emit valid JSON on corrupt SQLite DB: {exc}. "
                f"STDERR was: {res.stderr.strip()!r}"
            ) from exc
        assert data["status"] == "CRITICAL"
        assert any("sqlite_ledger" in issue for issue in data["issues"])
    return {"passed": True, "exit_code": res.returncode, "status": data["status"]}


def test_scenario_14_nondict_json_payload() -> dict[str, Any]:
    """Fault Test 14: Non-dict JSON payload ('[]') in health files -> must handle cleanly without crash."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        env["daemon_file"].write_text("[]", encoding="utf-8")
        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 2, f"Expected exit 2, got {res.returncode}"
        try:
            data = json.loads(res.stdout)
            assert data["status"] == "CRITICAL"
        except Exception as exc:
            raise AssertionError(
                f"CLI crashed on non-dict JSON payload instead of producing structured report: {exc}. "
                f"STDERR was: {res.stderr.strip()!r}"
            ) from exc
    return {"passed": True}


def test_scenario_15_null_fields_dashboard_formatting() -> dict[str, Any]:
    """Fault Test 15: Null optional fields (symbols_monitored, uptime_seconds) in console dashboard."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        daemon_payload = json.loads(env["daemon_file"].read_text(encoding="utf-8"))
        daemon_payload["symbols_monitored"] = None
        daemon_payload["uptime_seconds"] = None
        env["daemon_file"].write_text(json.dumps(daemon_payload), encoding="utf-8")

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
        ])
        if res.returncode != 0 or "Traceback" in res.stderr:
            raise AssertionError(
                f"Console dashboard formatting crashed on null fields with exit {res.returncode}: {res.stderr.strip()!r}"
            )
        assert "AUTONOMOUS FUTURES PIPELINE HEALTH DIAGNOSTICS REPORT" in res.stdout
    return {"passed": True}


def test_scenario_7_dirty_recovery_intent() -> dict[str, Any]:
    """Fault Test 7: Dirty recovery intent in paper_position_update_intent -> exit code 2, CRITICAL."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        conn = sqlite3.connect(env["ledger_db"])
        conn.execute(
            "INSERT INTO paper_position_update_intent (trade_id, intent) "
            "VALUES ('trade-fault-001', '{\"action\": \"emergency_stop\"}')"
        )
        conn.commit()
        conn.close()

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 2, f"Expected 2 for dirty recovery intent, got {res.returncode}"
        data = json.loads(res.stdout)
        assert data["status"] == "CRITICAL"
        assert any("dirty recovery intent detected" in issue for issue in data["issues"])
    return {"passed": True, "exit_code": res.returncode, "status": data["status"]}


def test_scenario_8_tampered_candidate_registry() -> dict[str, Any]:
    """Fault Test 8: Tampered candidate_registry.json (hash mismatch) -> exit code 2, CRITICAL."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        # Read raw json and tamper with candidate_id without updating registry_hash
        raw = env["registry_file"].read_text(encoding="utf-8")
        tampered = raw.replace("cand-01", "cand-MALICIOUS-TAMPERED-01")
        env["registry_file"].write_text(tampered, encoding="utf-8")

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 2, f"Expected 2 for tampered registry, got {res.returncode}"
        data = json.loads(res.stdout)
        assert data["status"] == "CRITICAL"
        assert any("candidate_registry" in issue and ("hash mismatch" in issue or "manifest verification failed" in issue) for issue in data["issues"])
    return {"passed": True, "exit_code": res.returncode, "status": data["status"]}


def test_scenario_9_dead_pid_with_running_status() -> dict[str, Any]:
    """Fault Test 9: Dead PID with status RUNNING -> exit code 2, status CRITICAL."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    dead_pid = 99999999

    # 9a: Paper daemon RUNNING with dead PID
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        daemon_payload = json.loads(env["daemon_file"].read_text(encoding="utf-8"))
        daemon_payload["daemon_status"] = "RUNNING"
        daemon_payload["pid"] = dead_pid
        env["daemon_file"].write_text(json.dumps(daemon_payload), encoding="utf-8")

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 2, f"Expected 2 for dead daemon PID, got {res.returncode}"
        data = json.loads(res.stdout)
        assert data["status"] == "CRITICAL"
        assert any("paper daemon status is RUNNING but PID 99999999 is dead" in issue for issue in data["issues"])

    # 9b: Scheduler RUNNING_CYCLE with dead PID
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        sched_payload = json.loads(env["scheduler_file"].read_text(encoding="utf-8"))
        sched_payload["status"] = "RUNNING_CYCLE"
        sched_payload["pid"] = dead_pid
        env["scheduler_file"].write_text(json.dumps(sched_payload), encoding="utf-8")

        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 2, f"Expected 2 for dead scheduler PID, got {res.returncode}"
        data = json.loads(res.stdout)
        assert data["status"] == "CRITICAL"
        assert any("scheduler status is RUNNING_CYCLE but PID 99999999 is dead" in issue for issue in data["issues"])

    return {"passed": True, "verified_subcases": ["9a_daemon_dead_pid", "9b_scheduler_dead_pid"]}


def test_scenario_10_json_schema_and_keys() -> dict[str, Any]:
    """Test Task 10: --json produces valid JSON schema with all expected keys."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 0
        data = json.loads(res.stdout)

        # Expected top-level keys
        top_keys = {
            "timestamp_utc",
            "status",
            "exit_code",
            "storage_dir",
            "stale_threshold_seconds",
            "summary",
            "components",
            "checks",
            "issues",
        }
        assert top_keys.issubset(set(data.keys())), f"Missing keys in {set(data.keys())}"

        # Summary keys
        summary_keys = {"total_checks", "passed_checks", "warnings_count", "failures_count"}
        assert summary_keys.issubset(set(data["summary"].keys()))

        # Component keys
        comp_keys = {"paper_daemon", "scheduler", "candidate_registry", "sqlite_ledger", "sqlite_lifecycle"}
        assert comp_keys.issubset(set(data["components"].keys()))

        # Checks schema
        for check in data["checks"]:
            assert "component" in check
            assert "check" in check
            assert "status" in check
            assert "message" in check
            assert check["status"] in ("PASS", "WARN", "FAIL")

    return {"passed": True, "total_checks": data["summary"]["total_checks"], "verified_keys": list(top_keys)}


def test_scenario_11_quiet_mode() -> dict[str, Any]:
    """Test Task 11: --quiet produces concise single-line status without decorative formatting."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)

        # 11a: Healthy
        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--quiet",
        ])
        assert res.returncode == 0
        assert res.stdout.startswith("HEALTHY:")
        assert "===" not in res.stdout
        assert "\n" not in res.stdout.strip()

        # 11b: Degraded (stale heartbeat)
        daemon_payload = json.loads(env["daemon_file"].read_text(encoding="utf-8"))
        daemon_payload["last_heartbeat_utc"] = (now - timedelta(seconds=200)).isoformat()
        env["daemon_file"].write_text(json.dumps(daemon_payload), encoding="utf-8")

        res_deg = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--quiet",
        ])
        assert res_deg.returncode == 1
        assert res_deg.stdout.startswith("DEGRADED:")
        assert "===" not in res_deg.stdout

        # 11c: Critical (corrupted registry)
        env["registry_file"].write_text("CORRUPTED_JSON", encoding="utf-8")
        res_crit = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--quiet",
        ])
        assert res_crit.returncode == 2
        assert res_crit.stdout.startswith("CRITICAL:")
        assert "===" not in res_crit.stdout

    return {
        "passed": True,
        "healthy_quiet": res.stdout.strip(),
        "degraded_quiet": res_deg.stdout.strip(),
        "critical_quiet": res_crit.stdout.strip(),
    }


def test_scenario_12_dynamic_stale_threshold() -> dict[str, Any]:
    """Test Task 12: --stale-threshold-seconds dynamically shifts boundary between HEALTHY and DEGRADED."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    # Heartbeat is 90 seconds old
    hb_time = now - timedelta(seconds=90)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)
        daemon_payload = json.loads(env["daemon_file"].read_text(encoding="utf-8"))
        daemon_payload["last_heartbeat_utc"] = hb_time.isoformat()
        env["daemon_file"].write_text(json.dumps(daemon_payload), encoding="utf-8")

        # Case A: threshold = 120s -> age 90s <= 120s -> HEALTHY (exit 0)
        res_healthy = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--stale-threshold-seconds", "120.0",
            "--json",
        ])
        assert res_healthy.returncode == 0, f"Expected 0 for 90s < 120s, got {res_healthy.returncode}"
        assert json.loads(res_healthy.stdout)["status"] == "HEALTHY"

        # Case B: threshold = 60s -> age 90s > 60s -> DEGRADED (exit 1)
        res_degraded = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--stale-threshold-seconds", "60.0",
            "--json",
        ])
        assert res_degraded.returncode == 1, f"Expected 1 for 90s > 60s, got {res_degraded.returncode}"
        assert json.loads(res_degraded.stdout)["status"] == "DEGRADED"

    return {
        "passed": True,
        "case_120s_exit": res_healthy.returncode,
        "case_60s_exit": res_degraded.returncode,
    }


def test_scenario_13_readonly_lock_non_interference() -> dict[str, Any]:
    """Test Task 13: Read-only lock non-interference and write prevention."""
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as td:
        env = setup_base_environment(Path(td), now)

        # Open an external concurrent shared read lock on paper-ledger.sqlite3
        external_conn = sqlite3.connect(env["ledger_db"], timeout=5.0)
        external_conn.execute("SELECT COUNT(*) FROM paper_ledger_events").fetchall()

        # Run health CLI while external read connection is open
        res = run_cli([
            "--storage-dir", str(env["storage_dir"]),
            "--now", now.isoformat(),
            "--json",
        ])
        assert res.returncode == 0, f"Concurrent read blocked! Exit code: {res.returncode}\n{res.stderr}"

        # Close external connection
        external_conn.close()

        # Check that no wal/journal files linger
        wal_file = env["ledger_db"].with_name(env["ledger_db"].name + "-wal")
        journal_file = env["ledger_db"].with_name(env["ledger_db"].name + "-journal")
        assert not wal_file.exists(), "Unexpected lingering WAL file"
        assert not journal_file.exists(), "Unexpected lingering journal file"

        # Verify connect_readonly enforces PRAGMA query_only = ON directly
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from check_autonomous_pipeline_health import connect_readonly
        ro_conn = connect_readonly(env["ledger_db"])
        try:
            write_blocked = False
            try:
                ro_conn.execute("CREATE TABLE attempt_write (id INTEGER)")
            except sqlite3.OperationalError as exc:
                write_blocked = True
                assert "readonly" in str(exc).lower() or "query_only" in str(exc).lower()
            assert write_blocked, "ReadOnly connection permitted write operation!"
        finally:
            ro_conn.close()

    return {"passed": True, "concurrent_read_exit": res.returncode, "write_prevented": True}


def main() -> int:
    """Run all empirical test suites."""
    print("=" * 80)
    print("EMPIRICAL CHALLENGER 2: HEALTH CLI FAULT INJECTION & VERIFICATION SUITE")
    print("=" * 80)

    tests = [
        ("Task 0: CLI --help and flag completeness", test_cli_help),
        ("Fault 1: Healthy baseline -> exit 0", test_scenario_1_healthy),
        ("Fault 2: Stale paper daemon heartbeat (>120s) -> exit 1", test_scenario_2_stale_paper_daemon_heartbeat),
        ("Fault 3: Stale scheduler heartbeat (>120s) -> exit 1", test_scenario_3_stale_scheduler_heartbeat),
        ("Fault 4: Scheduler in BACKOFF status -> exit 1", test_scenario_4_scheduler_backoff),
        ("Fault 5: Missing health JSONs without allow-missing -> exit 2 (and allow-missing -> exit 0)", test_scenario_5_missing_health_jsons),
        ("Fault 6: Corrupt SQLite DB -> exit 2", test_scenario_6_corrupt_sqlite_db),
        ("Fault 7: Dirty recovery intent in paper_position_update_intent -> exit 2", test_scenario_7_dirty_recovery_intent),
        ("Fault 8: Tampered candidate_registry.json (hash mismatch) -> exit 2", test_scenario_8_tampered_candidate_registry),
        ("Fault 9: Dead PID with status RUNNING -> exit 2", test_scenario_9_dead_pid_with_running_status),
        ("Task 10: --json schema completeness and structure", test_scenario_10_json_schema_and_keys),
        ("Task 11: --quiet concise single-line status formatting", test_scenario_11_quiet_mode),
        ("Task 12: --stale-threshold-seconds dynamic boundary shift", test_scenario_12_dynamic_stale_threshold),
        ("Task 13: Read-only lock non-interference & write prevention", test_scenario_13_readonly_lock_non_interference),
        ("Fault 14: Non-dict JSON payload resilience ('[]')", test_scenario_14_nondict_json_payload),
        ("Fault 15: Null fields console dashboard formatting resilience", test_scenario_15_null_fields_dashboard_formatting),
    ]

    results: dict[str, Any] = {}
    failed = False
    start_total = time.perf_counter()

    for name, fn in tests:
        t0 = time.perf_counter()
        try:
            outcome = fn()
            dur = time.perf_counter() - t0
            print(f"PASS: {name} ({dur:.3f}s)")
            results[name] = {"status": "PASS", "duration_seconds": dur, "details": outcome}
        except Exception as exc:
            dur = time.perf_counter() - t0
            print(f"FAIL: {name} ({dur:.3f}s)")
            print(f"      ERROR: {exc}")
            results[name] = {"status": "FAIL", "duration_seconds": dur, "error": str(exc)}
            failed = True

    total_dur = time.perf_counter() - start_total
    print("-" * 80)
    print(f"Total Execution Time: {total_dur:.2f}s")
    if failed:
        print("VERDICT: REQUEST_CHANGES (One or more fault scenarios failed)")
        return 1
    else:
        print("VERDICT: APPROVE (All 14 fault injection and CLI stress tests passed 100%)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
