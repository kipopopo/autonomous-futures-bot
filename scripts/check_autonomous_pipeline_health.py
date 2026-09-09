"""Unified Autonomous Pipeline Health Diagnostics CLI.

Inspects runtime health files, process liveness, SQLite database integrity,
and candidate registry manifests across the autonomous trading pipeline.

Authoritative Specification:
- ORIGINAL_REQUEST.md (Section 2026-09-09T04:57:45Z §R2)
- .agents/teamwork_preview_spec_miner_survey7_2/spec.md
- .agents/teamwork_preview_explorer_survey7_3/report.md
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

# Ensure src/ is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.domain.contracts import DomainModel  # noqa: E402
from autonomous_futures.paper.candidate_registry import read_candidate_registry  # noqa: E402
from autonomous_futures.paper.sqlite_ledger import validate_position_state  # noqa: E402


def is_pid_alive(pid: int) -> bool:
    """Determine if a process with the specified PID is currently running.

    Compatible with Windows and POSIX systems without external dependencies.
    """
    if pid <= 0:
        return False

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            synchronize = 0x00100000
            kernel32 = ctypes.windll.kernel32

            h_process = kernel32.OpenProcess(
                process_query_limited_information | synchronize, False, pid
            )
            if not h_process:
                error_code = int(kernel32.GetLastError())
                error_access_denied = 5
                return bool(error_code == error_access_denied)

            try:
                exit_code = wintypes.DWORD()
                if kernel32.GetExitCodeProcess(h_process, ctypes.byref(exit_code)):
                    still_active = 259
                    return bool(exit_code.value == still_active)
                return False
            finally:
                kernel32.CloseHandle(h_process)
        except Exception:
            try:
                os.kill(pid, 0)
                return True
            except OSError as exc:
                if getattr(exc, "winerror", None) == 87:
                    return False
                if getattr(exc, "winerror", None) == 5:
                    return True
                if exc.errno == errno.ESRCH:
                    return False
                if exc.errno == errno.EPERM:
                    return True
                return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return False
            if exc.errno == errno.EPERM:
                return True
            return False


def compute_heartbeat_age_seconds(timestamp_str: str, now: datetime | None = None) -> float:
    """Calculate elapsed seconds since last reported UTC heartbeat.

    Handles ISO-8601 formatting, UTC timezone conversion, and minor clock drift
    clamping (-5.0s to 0.0s clamped to 0.0s).
    """
    current = now or datetime.now(UTC)
    clean_str = timestamp_str.replace("Z", "+00:00")
    try:
        heartbeat_dt = datetime.fromisoformat(clean_str)
    except ValueError, TypeError:
        return float("inf")

    if heartbeat_dt.tzinfo is None:
        heartbeat_dt = heartbeat_dt.replace(tzinfo=UTC)
    else:
        heartbeat_dt = heartbeat_dt.astimezone(UTC)

    elapsed = (current - heartbeat_dt).total_seconds()
    if -5.0 <= elapsed < 0.0:
        return 0.0
    return elapsed


def format_uptime(seconds: float | None) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds is None or seconds < 0:
        return "0s"
    total_secs = int(seconds)
    hours, remainder = divmod(total_secs, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a non-blocking read-only SQLite connection.

    Uses URI mode (?mode=ro), PRAGMA query_only = ON, and PRAGMA busy_timeout = 1000.
    """
    if not db_path.is_file():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    uri_path = db_path.resolve().as_posix()
    uri = f"file:{uri_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=1.0)
    conn.execute("PRAGMA query_only = ON;")
    conn.execute("PRAGMA busy_timeout = 1000;")
    return conn


class CheckItem(DomainModel):
    """Individual health check verification outcome."""

    component: str = Field(
        description=(
            "Component identifier (paper_daemon, scheduler, candidate_registry, "
            "sqlite_ledger, sqlite_lifecycle)"
        )
    )
    check: str = Field(description="Name of the specific check")
    status: Literal["PASS", "WARN", "FAIL"] = Field(description="Status of check result")
    message: str = Field(description="Diagnostic message or detail")


class HealthSummary(DomainModel):
    """Aggregate check count summary."""

    total_checks: int = Field(ge=0, description="Total number of checks executed")
    passed_checks: int = Field(ge=0, description="Total passing checks")
    warnings_count: int = Field(ge=0, description="Total warnings / degraded checks")
    failures_count: int = Field(ge=0, description="Total critical / failing checks")


class PipelineHealthReport(DomainModel):
    """Complete structured machine-readable pipeline health diagnostics report."""

    timestamp_utc: str = Field(description="ISO-8601 UTC timestamp of inspection")
    status: Literal["HEALTHY", "DEGRADED", "CRITICAL"] = Field(
        description="Overall pipeline status"
    )
    exit_code: int = Field(
        ge=0, le=2, description="Process exit code: 0=HEALTHY, 1=DEGRADED, 2=CRITICAL"
    )
    storage_dir: str = Field(description="Resolved storage directory inspected")
    stale_threshold_seconds: float = Field(gt=0, description="Stale threshold in seconds applied")
    summary: HealthSummary = Field(description="Summary count metrics")
    components: dict[str, Any] = Field(description="Per-component telemetry data and metrics")
    checks: list[CheckItem] = Field(description="Chronological check outcomes")
    issues: list[str] = Field(description="List of detected warnings and failures")


def check_paper_daemon(
    daemon_file: Path,
    now: datetime,
    stale_threshold_seconds: float,
) -> tuple[dict[str, Any] | None, list[CheckItem]]:
    """Evaluate paper daemon telemetry (paper-daemon-health.json)."""
    checks: list[CheckItem] = []
    comp = "paper_daemon"

    if not daemon_file.is_file():
        checks.append(
            CheckItem(
                component=comp,
                check="file_exists",
                status="FAIL",
                message=f"paper-daemon-health.json not found at {daemon_file}",
            )
        )
        return None, checks

    try:
        raw_text = daemon_file.read_text(encoding="utf-8")
        data: Any = json.loads(raw_text)
    except Exception as exc:
        checks.append(
            CheckItem(
                component=comp,
                check="json_syntax",
                status="FAIL",
                message=f"corrupted or invalid JSON in {daemon_file}: {exc}",
            )
        )
        return None, checks

    if not isinstance(data, dict):
        checks.append(
            CheckItem(
                component=comp,
                check="json_schema",
                status="FAIL",
                message=f"expected JSON object in {daemon_file}, got {type(data).__name__}",
            )
        )
        return None, checks

    checks.append(
        CheckItem(
            component=comp,
            check="file_exists",
            status="PASS",
            message=f"paper-daemon-health.json present at {daemon_file}",
        )
    )

    # 1. Daemon status & PID liveness
    daemon_status = str(data.get("daemon_status", "UNKNOWN")).upper()
    pid = data.get("pid")
    if isinstance(pid, int):
        alive = is_pid_alive(pid)
        if daemon_status == "RUNNING":
            if not alive:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="process_liveness",
                        status="FAIL",
                        message=f"paper daemon status is RUNNING but PID {pid} is dead",
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="process_liveness",
                        status="PASS",
                        message=f"paper daemon process is alive (PID: {pid})",
                    )
                )
        elif daemon_status in ("STOPPED", "SHUTDOWN_CLEAN"):
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="WARN",
                    message=f"paper daemon is inactive ({daemon_status})",
                )
            )
        elif daemon_status == "HALTED":
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="FAIL",
                    message="paper daemon is HALTED",
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="PASS",
                    message=f"paper daemon status is {daemon_status} (PID: {pid}, alive: {alive})",
                )
            )
    else:
        if daemon_status in ("STOPPED", "SHUTDOWN_CLEAN"):
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="WARN",
                    message=f"paper daemon is inactive ({daemon_status}, PID: null)",
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="FAIL",
                    message=f"paper daemon missing valid PID in status {daemon_status}",
                )
            )

    # 2. Heartbeat freshness
    heartbeat_str = data.get("last_heartbeat_utc")
    if isinstance(heartbeat_str, str) and heartbeat_str.strip():
        age = compute_heartbeat_age_seconds(heartbeat_str, now)
        data["heartbeat_age_seconds"] = round(age, 2)
        if age < -5.0:
            checks.append(
                CheckItem(
                    component=comp,
                    check="heartbeat_freshness",
                    status="WARN",
                    message=(
                        f"significant clock skew detected: "
                        f"heartbeat is in the future by {-age:.1f}s"
                    ),
                )
            )
        elif age > stale_threshold_seconds:
            checks.append(
                CheckItem(
                    component=comp,
                    check="heartbeat_freshness",
                    status="WARN",
                    message=(
                        f"stale paper daemon heartbeat: age {age:.1f}s > "
                        f"threshold {stale_threshold_seconds:.1f}s"
                    ),
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="heartbeat_freshness",
                    status="PASS",
                    message=(
                        f"heartbeat is fresh (age: {age:.1f}s <= {stale_threshold_seconds:.1f}s)"
                    ),
                )
            )
    else:
        checks.append(
            CheckItem(
                component=comp,
                check="heartbeat_freshness",
                status="FAIL",
                message="missing or invalid last_heartbeat_utc in paper-daemon-health.json",
            )
        )

    # 3. Circuit breaker
    cb_status = str(data.get("circuit_breaker_status", "NORMAL")).upper()
    if cb_status == "HALTED":
        checks.append(
            CheckItem(
                component=comp,
                check="circuit_breaker",
                status="FAIL",
                message="circuit breaker is HALTED (emergency stop active)",
            )
        )
    elif cb_status == "THROTTLED":
        checks.append(
            CheckItem(
                component=comp,
                check="circuit_breaker",
                status="WARN",
                message="circuit breaker is THROTTLED",
            )
        )
    else:
        checks.append(
            CheckItem(
                component=comp,
                check="circuit_breaker",
                status="PASS",
                message=f"circuit breaker is {cb_status}",
            )
        )

    # 4. Zero-order safety invariants
    invariants = data.get("zero_order_safety_invariants")
    if isinstance(invariants, dict):
        violations: list[str] = []
        if invariants.get("orders_submitted") != 0:
            violations.append(f"orders_submitted={invariants.get('orders_submitted')} (expected 0)")
        if invariants.get("execution_authority") is not False:
            violations.append("execution_authority is True (expected False)")
        if invariants.get("live_trading_activation") is not False:
            violations.append("live_trading_activation is True (expected False)")
        if invariants.get("paper_activation") is not True:
            violations.append("paper_activation is not True (expected True)")
        if invariants.get("zero_private_credentials") is not True:
            violations.append("zero_private_credentials is not True (expected True)")

        if violations:
            checks.append(
                CheckItem(
                    component=comp,
                    check="zero_order_safety_invariants",
                    status="FAIL",
                    message=f"safety invariant violations: {', '.join(violations)}",
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="zero_order_safety_invariants",
                    status="PASS",
                    message="zero-order safety invariants verified",
                )
            )
    else:
        checks.append(
            CheckItem(
                component=comp,
                check="zero_order_safety_invariants",
                status="FAIL",
                message="missing zero_order_safety_invariants in paper daemon health",
            )
        )

    # 5. Margin utilization and reserve buffer
    margin_util = data.get("margin_utilization_pct")
    reserve_buf = data.get("reserve_buffer_pct")
    if isinstance(margin_util, (int, float)) and margin_util > 80.0:
        checks.append(
            CheckItem(
                component=comp,
                check="margin_utilization",
                status="WARN",
                message=f"high margin utilization: {margin_util:.2f}% > 80.0%",
            )
        )
    if isinstance(reserve_buf, (int, float)) and reserve_buf < 20.0:
        checks.append(
            CheckItem(
                component=comp,
                check="reserve_buffer",
                status="WARN",
                message=f"low reserve buffer: {reserve_buf:.2f}% < 20.0%",
            )
        )

    return data, checks


def check_scheduler(
    scheduler_file: Path,
    now: datetime,
    stale_threshold_seconds: float,
    allow_missing: bool,
) -> tuple[dict[str, Any] | None, list[CheckItem]]:
    """Evaluate autonomous scheduler telemetry (scheduler-health.json)."""
    checks: list[CheckItem] = []
    comp = "scheduler"

    if not scheduler_file.is_file():
        if allow_missing:
            checks.append(
                CheckItem(
                    component=comp,
                    check="file_exists",
                    status="PASS",
                    message=(
                        "scheduler-health.json not found (skipped per --allow-missing-scheduler)"
                    ),
                )
            )
            return {"status": "SKIPPED", "message": "missing allowed"}, checks

        checks.append(
            CheckItem(
                component=comp,
                check="file_exists",
                status="FAIL",
                message=f"scheduler-health.json not found at {scheduler_file}",
            )
        )
        return None, checks

    try:
        raw_text = scheduler_file.read_text(encoding="utf-8")
        data: Any = json.loads(raw_text)
    except Exception as exc:
        checks.append(
            CheckItem(
                component=comp,
                check="json_syntax",
                status="FAIL",
                message=f"corrupted or invalid JSON in {scheduler_file}: {exc}",
            )
        )
        return None, checks

    if not isinstance(data, dict):
        checks.append(
            CheckItem(
                component=comp,
                check="json_schema",
                status="FAIL",
                message=f"expected JSON object in {scheduler_file}, got {type(data).__name__}",
            )
        )
        return None, checks

    checks.append(
        CheckItem(
            component=comp,
            check="file_exists",
            status="PASS",
            message=f"scheduler-health.json present at {scheduler_file}",
        )
    )

    # 1. Scheduler status and PID
    status = str(data.get("status", "UNKNOWN")).upper()
    pid = data.get("pid")
    if isinstance(pid, int):
        alive = is_pid_alive(pid)
        if status in ("IDLE", "RUNNING_CYCLE"):
            if not alive:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="process_liveness",
                        status="FAIL",
                        message=f"scheduler status is {status} but PID {pid} is dead",
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="process_liveness",
                        status="PASS",
                        message=f"scheduler process is alive (PID: {pid}, status: {status})",
                    )
                )
        elif status == "BACKOFF":
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="WARN",
                    message="scheduler is in BACKOFF mode",
                )
            )
        elif status == "STOPPED":
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="WARN",
                    message="scheduler daemon is stopped cleanly",
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="PASS",
                    message=f"scheduler status: {status} (PID: {pid})",
                )
            )
    else:
        if status == "STOPPED":
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="WARN",
                    message="scheduler daemon is stopped cleanly (PID: null)",
                )
            )
        elif status == "BACKOFF":
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="WARN",
                    message="scheduler is in BACKOFF mode (PID: null)",
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="process_liveness",
                    status="FAIL",
                    message=f"scheduler reported active status {status} but PID is null",
                )
            )

    # 2. Update freshness
    updated_at_str = data.get("updated_at")
    if isinstance(updated_at_str, str) and updated_at_str.strip():
        age = compute_heartbeat_age_seconds(updated_at_str, now)
        data["heartbeat_age_seconds"] = round(age, 2)
        if age < -5.0:
            checks.append(
                CheckItem(
                    component=comp,
                    check="heartbeat_freshness",
                    status="WARN",
                    message=(
                        f"significant clock skew detected: "
                        f"scheduler update is in the future by {-age:.1f}s"
                    ),
                )
            )
        elif age > stale_threshold_seconds:
            checks.append(
                CheckItem(
                    component=comp,
                    check="heartbeat_freshness",
                    status="WARN",
                    message=(
                        f"stale scheduler heartbeat: age {age:.1f}s > "
                        f"threshold {stale_threshold_seconds:.1f}s"
                    ),
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="heartbeat_freshness",
                    status="PASS",
                    message=(
                        f"scheduler update is fresh "
                        f"(age: {age:.1f}s <= {stale_threshold_seconds:.1f}s)"
                    ),
                )
            )
    else:
        checks.append(
            CheckItem(
                component=comp,
                check="heartbeat_freshness",
                status="FAIL",
                message="missing or invalid updated_at in scheduler-health.json",
            )
        )

    # 3. Consecutive failures
    consecutive_failures = data.get("consecutive_failures", 0)
    if isinstance(consecutive_failures, int) and consecutive_failures >= 3:
        checks.append(
            CheckItem(
                component=comp,
                check="failure_rate",
                status="WARN",
                message=f"scheduler has {consecutive_failures} consecutive cycle failures",
            )
        )
    else:
        checks.append(
            CheckItem(
                component=comp,
                check="failure_rate",
                status="PASS",
                message=f"consecutive failures: {consecutive_failures}",
            )
        )

    return data, checks


def check_candidate_registry(
    registry_file: Path,
    storage_dir: Path,
) -> tuple[dict[str, Any] | None, list[CheckItem]]:
    """Validate candidate registry manifest and canonical cryptographic hash."""
    checks: list[CheckItem] = []
    comp = "candidate_registry"

    if not registry_file.is_file():
        checks.append(
            CheckItem(
                component=comp,
                check="file_exists",
                status="FAIL",
                message=f"candidate_registry.json not found at {registry_file}",
            )
        )
        return None, checks

    try:
        manifest = read_candidate_registry(registry_file, verify_hash=True)
    except Exception as exc:
        checks.append(
            CheckItem(
                component=comp,
                check="manifest_hash_integrity",
                status="FAIL",
                message=f"candidate registry manifest verification failed: {exc}",
            )
        )
        return None, checks

    checks.append(
        CheckItem(
            component=comp,
            check="file_exists",
            status="PASS",
            message=f"candidate_registry.json present at {registry_file}",
        )
    )
    checks.append(
        CheckItem(
            component=comp,
            check="manifest_hash_integrity",
            status="PASS",
            message=f"manifest hash verified: {manifest.registry_hash[:16]}...",
        )
    )

    manifest_data: dict[str, Any] = manifest.model_dump(mode="json")

    # Check reachability of candidate artifacts
    for symbol, entry in manifest.symbols.items():
        art_path_str = entry.artifact_path
        candidate_search_paths = [
            storage_dir.parent / art_path_str,
            storage_dir / art_path_str,
            _REPO_ROOT / art_path_str,
            Path(art_path_str),
        ]
        found = any(p.is_file() for p in candidate_search_paths)
        if not found:
            checks.append(
                CheckItem(
                    component=comp,
                    check="artifact_reachability",
                    status="FAIL",
                    message=f"candidate artifact missing for symbol {symbol}: {art_path_str}",
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="artifact_reachability",
                    status="PASS",
                    message=f"candidate artifact verified for {symbol}: {entry.candidate_id}",
                )
            )

    return manifest_data, checks


def check_sqlite_ledger(
    ledger_db_file: Path,
    daemon_active_positions_count: int | None,
) -> tuple[dict[str, Any] | None, list[CheckItem]]:
    """Verify SQLite ledger integrity, dirty recovery intents, and trade event parity."""
    checks: list[CheckItem] = []
    comp = "sqlite_ledger"

    if not ledger_db_file.is_file():
        checks.append(
            CheckItem(
                component=comp,
                check="file_exists",
                status="FAIL",
                message=f"paper-ledger.sqlite3 not found at {ledger_db_file}",
            )
        )
        return None, checks

    checks.append(
        CheckItem(
            component=comp,
            check="file_exists",
            status="PASS",
            message=f"paper-ledger.sqlite3 present at {ledger_db_file}",
        )
    )

    try:
        conn = connect_readonly(ledger_db_file)
    except Exception as exc:
        checks.append(
            CheckItem(
                component=comp,
                check="database_connection",
                status="FAIL",
                message=f"failed to open read-only connection to ledger: {exc}",
            )
        )
        return None, checks

    ledger_summary: dict[str, Any] = {"path": str(ledger_db_file)}

    try:
        # 1. PRAGMA integrity_check
        cursor = conn.execute("PRAGMA integrity_check;")
        integrity_rows = cursor.fetchall()
        if integrity_rows != [("ok",)]:
            checks.append(
                CheckItem(
                    component=comp,
                    check="integrity_check",
                    status="FAIL",
                    message=f"SQLite integrity check failed: {integrity_rows}",
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="integrity_check",
                    status="PASS",
                    message="SQLite integrity check: ok",
                )
            )
            ledger_summary["integrity"] = "ok"

        # 2. Check paper_position_update_intent for dirty intents
        intent_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_position_update_intent'"
        ).fetchone()
        if intent_table is not None:
            dirty_rows = conn.execute(
                "SELECT trade_id, intent FROM paper_position_update_intent ORDER BY trade_id"
            ).fetchall()
            dirty_count = len(dirty_rows)
            ledger_summary["dirty_intents_count"] = dirty_count
            if dirty_count > 0:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="dirty_recovery_intents",
                        status="FAIL",
                        message=(
                            f"dirty recovery intent detected: {dirty_count} "
                            f"uncommitted intent(s): {dirty_rows}"
                        ),
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="dirty_recovery_intents",
                        status="PASS",
                        message="zero dirty recovery intents in ledger",
                    )
                )
        else:
            ledger_summary["dirty_intents_count"] = 0
            checks.append(
                CheckItem(
                    component=comp,
                    check="dirty_recovery_intents",
                    status="PASS",
                    message="paper_position_update_intent table clean / not present",
                )
            )

        # 3. Trade event anomalies
        events_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_ledger_events'"
        ).fetchone()
        unmatched_open_ids: set[str] = set()
        if events_table is not None:
            total_events = conn.execute("SELECT COUNT(*) FROM paper_ledger_events").fetchone()[0]
            opens_count = conn.execute(
                "SELECT COUNT(*) FROM paper_ledger_events WHERE event = 'open'"
            ).fetchone()[0]
            closes_count = conn.execute(
                "SELECT COUNT(*) FROM paper_ledger_events WHERE event = 'close'"
            ).fetchone()[0]
            ledger_summary["total_events"] = total_events
            ledger_summary["opens_count"] = opens_count
            ledger_summary["closes_count"] = closes_count

            # Duplicate opens
            dup_opens = conn.execute(
                "SELECT trade_id, COUNT(*) FROM paper_ledger_events WHERE event = 'open' "
                "GROUP BY trade_id HAVING COUNT(*) > 1"
            ).fetchall()
            if dup_opens:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="duplicate_open_events",
                        status="FAIL",
                        message=(
                            f"duplicate open events detected for trades: "
                            f"{[r[0] for r in dup_opens]}"
                        ),
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="duplicate_open_events",
                        status="PASS",
                        message="zero duplicate open events",
                    )
                )

            # Duplicate closes
            dup_closes = conn.execute(
                "SELECT trade_id, COUNT(*) FROM paper_ledger_events WHERE event = 'close' "
                "GROUP BY trade_id HAVING COUNT(*) > 1"
            ).fetchall()
            if dup_closes:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="duplicate_close_events",
                        status="FAIL",
                        message=(
                            f"duplicate close events detected for trades: "
                            f"{[r[0] for r in dup_closes]}"
                        ),
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="duplicate_close_events",
                        status="PASS",
                        message="zero duplicate close events",
                    )
                )

            # Orphan closes
            orphan_closes = conn.execute(
                "SELECT trade_id FROM paper_ledger_events WHERE event = 'close' "
                "AND trade_id NOT IN ("
                "SELECT trade_id FROM paper_ledger_events WHERE event = 'open')"
            ).fetchall()
            if orphan_closes:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="orphan_close_events",
                        status="FAIL",
                        message=(
                            f"orphan close events without matching open: "
                            f"{[r[0] for r in orphan_closes]}"
                        ),
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="orphan_close_events",
                        status="PASS",
                        message="zero orphan close events",
                    )
                )

            # Unmatched opens
            unmatched_rows = conn.execute(
                "SELECT trade_id FROM paper_ledger_events WHERE event = 'open' "
                "AND trade_id NOT IN ("
                "SELECT trade_id FROM paper_ledger_events WHERE event = 'close')"
            ).fetchall()
            unmatched_open_ids = {r[0] for r in unmatched_rows}
            ledger_summary["unmatched_opens_count"] = len(unmatched_open_ids)
            ledger_summary["unmatched_open_ids"] = sorted(unmatched_open_ids)

        # 4. Position state parity
        pos_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_position_state'"
        ).fetchone()
        if pos_table is not None:
            state_rows = conn.execute(
                "SELECT trade_id, state_version, state_json "
                "FROM paper_position_state ORDER BY trade_id"
            ).fetchall()
            persisted_state_ids = {r[0] for r in state_rows}
            ledger_summary["persisted_positions_count"] = len(persisted_state_ids)

            if unmatched_open_ids != persisted_state_ids:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="position_state_parity",
                        status="FAIL",
                        message=(
                            f"position state parity mismatch: unmatched opens "
                            f"({len(unmatched_open_ids)}) != persisted states "
                            f"({len(persisted_state_ids)}). "
                            f"Unmatched: {sorted(unmatched_open_ids)}, "
                            f"Persisted: {sorted(persisted_state_ids)}"
                        ),
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="position_state_parity",
                        status="PASS",
                        message=(
                            f"position state parity match "
                            f"({len(persisted_state_ids)} active positions)"
                        ),
                    )
                )

            # Validate each state schema
            schema_errors: list[str] = []
            for t_id, s_ver, s_json in state_rows:
                try:
                    payload = json.loads(s_json)
                    validate_position_state(payload, sql_trade_id=t_id, sql_state_version=s_ver)
                except Exception as exc:
                    schema_errors.append(f"trade {t_id}: {exc}")

            if schema_errors:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="position_state_schema",
                        status="FAIL",
                        message=f"invalid position state schema: {'; '.join(schema_errors)}",
                    )
                )
            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="position_state_schema",
                        status="PASS",
                        message="all persisted position states validated cleanly",
                    )
                )

        # 5. Parity with daemon active positions count
        if daemon_active_positions_count is not None and events_table is not None:
            if daemon_active_positions_count != len(unmatched_open_ids):
                checks.append(
                    CheckItem(
                        component=comp,
                        check="daemon_position_parity",
                        status="WARN",
                        message=(
                            f"active position count mismatch: daemon reports "
                            f"{daemon_active_positions_count}, "
                            f"ledger has {len(unmatched_open_ids)} unmatched opens"
                        ),
                    )
                )

            else:
                checks.append(
                    CheckItem(
                        component=comp,
                        check="daemon_position_parity",
                        status="PASS",
                        message=(
                            f"daemon active positions ({daemon_active_positions_count}) "
                            f"matches ledger open positions"
                        ),
                    )
                )
    except Exception as exc:
        checks.append(
            CheckItem(
                component=comp,
                check="integrity_check",
                status="FAIL",
                message=f"SQLite query or integrity failure: {exc}",
            )
        )
    finally:
        conn.close()

    return ledger_summary, checks


def check_sqlite_lifecycle(
    lifecycle_db_file: Path,
) -> tuple[dict[str, Any] | None, list[CheckItem]]:
    """Verify SQLite lifecycle database integrity and recorded telemetry marks."""
    checks: list[CheckItem] = []
    comp = "sqlite_lifecycle"

    if not lifecycle_db_file.is_file():
        checks.append(
            CheckItem(
                component=comp,
                check="file_exists",
                status="PASS",
                message="paper-lifecycle.sqlite3 not initialized (optional)",
            )
        )
        return {"status": "NOT_INITIALIZED"}, checks

    try:
        conn = connect_readonly(lifecycle_db_file)
    except Exception as exc:
        checks.append(
            CheckItem(
                component=comp,
                check="database_connection",
                status="FAIL",
                message=f"failed to open read-only connection to lifecycle db: {exc}",
            )
        )
        return None, checks

    summary: dict[str, Any] = {"path": str(lifecycle_db_file)}
    try:
        cursor = conn.execute("PRAGMA integrity_check;")
        rows = cursor.fetchall()
        if rows != [("ok",)]:
            checks.append(
                CheckItem(
                    component=comp,
                    check="integrity_check",
                    status="FAIL",
                    message=f"lifecycle SQLite integrity check failed: {rows}",
                )
            )
        else:
            checks.append(
                CheckItem(
                    component=comp,
                    check="integrity_check",
                    status="PASS",
                    message="lifecycle SQLite integrity check: ok",
                )
            )
            summary["integrity"] = "ok"

        table_row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_lifecycle_marks'"
        ).fetchone()
        if table_row is not None:
            marks_count = conn.execute("SELECT COUNT(*) FROM paper_lifecycle_marks").fetchone()[0]
            summary["marks_count"] = marks_count
            checks.append(
                CheckItem(
                    component=comp,
                    check="marks_recorded",
                    status="PASS",
                    message=f"{marks_count} telemetry mark(s) recorded in paper_lifecycle_marks",
                )
            )
        else:
            summary["marks_count"] = 0
            checks.append(
                CheckItem(
                    component=comp,
                    check="marks_recorded",
                    status="PASS",
                    message="paper_lifecycle_marks table clean / not initialized",
                )
            )
    except Exception as exc:
        checks.append(
            CheckItem(
                component=comp,
                check="integrity_check",
                status="FAIL",
                message=f"SQLite query or integrity failure: {exc}",
            )
        )
    finally:
        conn.close()

    return summary, checks


def format_console_dashboard(report: PipelineHealthReport) -> str:
    """Format an informative human-readable ASCII console dashboard."""
    lines: list[str] = []
    border = "=" * 80
    sub_border = "-" * 80

    lines.append(border)
    lines.append("          AUTONOMOUS FUTURES PIPELINE HEALTH DIAGNOSTICS REPORT          ")
    lines.append(border)
    lines.append(f"Timestamp (UTC):    {report.timestamp_utc}")
    lines.append(f"Storage Directory:  {report.storage_dir}")
    lines.append(f"Stale Threshold:    {report.stale_threshold_seconds:.1f}s")
    lines.append(f"Overall Status:     [ {report.status} ]  (Exit Code: {report.exit_code})")
    lines.append(border)
    lines.append("")

    # Live Paper Daemon
    daemon_data = report.components.get("paper_daemon")
    daemon_checks = [c for c in report.checks if c.component == "paper_daemon"]
    daemon_status = (
        "CRITICAL"
        if any(c.status == "FAIL" for c in daemon_checks)
        else "DEGRADED"
        if any(c.status == "WARN" for c in daemon_checks)
        else "HEALTHY"
    )
    lines.append(f"[+] LIVE PAPER DAEMON: {daemon_status}")
    if daemon_data and daemon_data.get("daemon_status"):
        pid = daemon_data.get("pid")
        alive = is_pid_alive(pid) if isinstance(pid, int) else False
        uptime_val = daemon_data.get("uptime_seconds")
        uptime_sec = float(uptime_val) if isinstance(uptime_val, (int, float)) else 0.0
        uptime = format_uptime(uptime_sec)
        lines.append(
            f"    Status:               {daemon_data.get('daemon_status')} "
            f"(PID: {pid}, Alive: {alive})"
        )
        lines.append(f"    Uptime:               {uptime}")
        lines.append(
            f"    Last Heartbeat:       {daemon_data.get('last_heartbeat_utc')} "
            f"(Age: {daemon_data.get('heartbeat_age_seconds', 'N/A')}s)"
        )
        syms_val = daemon_data.get("symbols_monitored")
        syms = (
            ", ".join(str(s) for s in syms_val)
            if isinstance(syms_val, list) and syms_val
            else "None"
        )
        lines.append(f"    Monitored Symbols:    {syms}")
        lines.append(
            f"    Active Positions:     {daemon_data.get('active_positions_count', 0)} "
            f"(Margin Util: {daemon_data.get('margin_utilization_pct', 0.0)}%, "
            f"Reserve: {daemon_data.get('reserve_buffer_pct', 0.0)}%)"
        )
        lines.append(f"    Circuit Breaker:      {daemon_data.get('circuit_breaker_status')}")
    else:
        for c in daemon_checks:
            lines.append(f"    [{c.status}] {c.message}")
    lines.append("")

    # Autonomous Scheduler
    sched_data = report.components.get("scheduler")
    sched_checks = [c for c in report.checks if c.component == "scheduler"]
    sched_status = (
        "CRITICAL"
        if any(c.status == "FAIL" for c in sched_checks)
        else "DEGRADED"
        if any(c.status == "WARN" for c in sched_checks)
        else "HEALTHY"
    )
    lines.append(f"[+] AUTONOMOUS SCHEDULER: {sched_status}")
    if sched_data and sched_data.get("status") and sched_data.get("status") != "SKIPPED":
        pid = sched_data.get("pid")
        alive = is_pid_alive(pid) if isinstance(pid, int) else False
        lines.append(
            f"    Status:               {sched_data.get('status')} (PID: {pid}, Alive: {alive})"
        )
        lines.append(
            f"    Last Update:          {sched_data.get('updated_at')} "
            f"(Age: {sched_data.get('heartbeat_age_seconds', 'N/A')}s)"
        )
        last_res = sched_data.get("last_cycle_result") or {}
        last_cycle_summary = (
            f"{last_res.get('status', 'none')}, exit {last_res.get('exit_code', 'N/A')}"
            if last_res
            else "none"
        )
        lines.append(
            f"    Last Run:             {sched_data.get('last_run_at', 'None')} "
            f"({last_cycle_summary})"
        )
        lines.append(f"    Next Run:             {sched_data.get('next_run_at', 'None')}")
        lines.append(
            f"    Cycles / Admitted:    {sched_data.get('total_cycles_executed', 0)} executed / "
            f"{sched_data.get('admitted_candidates_count', 0)} admitted "
            f"({sched_data.get('consecutive_failures', 0)} consecutive failures)"
        )
    else:
        for c in sched_checks:
            lines.append(f"    [{c.status}] {c.message}")
    lines.append("")

    # Candidate Registry
    reg_data = report.components.get("candidate_registry")
    reg_checks = [c for c in report.checks if c.component == "candidate_registry"]
    reg_status = (
        "CRITICAL"
        if any(c.status == "FAIL" for c in reg_checks)
        else "DEGRADED"
        if any(c.status == "WARN" for c in reg_checks)
        else "HEALTHY"
    )
    lines.append(f"[+] CANDIDATE REGISTRY: {reg_status}")
    if reg_data and "registry_version" in reg_data:
        lines.append(
            f"    Manifest Version:     {reg_data.get('registry_version')} "
            f"(Updated: {reg_data.get('updated_at')})"
        )
        reg_hash = str(reg_data.get("registry_hash", ""))
        lines.append(f"    Cryptographic Hash:   {reg_hash[:24]}... (VALID)")
        sym_entries = [
            f"{s} ({e.get('candidate_id', 'N/A')})" for s, e in reg_data.get("symbols", {}).items()
        ]
        lines.append(f"    Registered Symbols:   {', '.join(sym_entries) or 'None'}")
    else:
        for c in reg_checks:
            lines.append(f"    [{c.status}] {c.message}")
    lines.append("")

    # SQLite Paper Ledger
    ledger_data = report.components.get("sqlite_ledger")
    ledger_checks = [c for c in report.checks if c.component == "sqlite_ledger"]
    ledger_status = (
        "CRITICAL"
        if any(c.status == "FAIL" for c in ledger_checks)
        else "DEGRADED"
        if any(c.status == "WARN" for c in ledger_checks)
        else "HEALTHY"
    )
    lines.append(f"[+] SQLITE PAPER LEDGER: {ledger_status}")
    if ledger_data and "path" in ledger_data:
        lines.append(f"    Path:                 {ledger_data.get('path')}")
        lines.append(f"    Integrity Check:      {ledger_data.get('integrity', 'N/A')}")
        dirty_cnt = ledger_data.get("dirty_intents_count", 0)
        dirty_desc = "0 (CLEAN)" if dirty_cnt == 0 else f"{dirty_cnt} (DIRTY)"
        lines.append(f"    Dirty Intents:        {dirty_desc}")
        lines.append(
            f"    Trade Events:         {ledger_data.get('total_events', 0)} total "
            f"({ledger_data.get('opens_count', 0)} opens, "
            f"{ledger_data.get('closes_count', 0)} closes)"
        )
        lines.append(
            f"    Active Open Trades:   "
            f"{ledger_data.get('unmatched_opens_count', 0)} unmatched open"
        )
        lines.append(
            f"    Position States:      "
            f"{ledger_data.get('persisted_positions_count', 0)} persisted state"
        )
    else:
        for c in ledger_checks:
            lines.append(f"    [{c.status}] {c.message}")
    lines.append("")

    # SQLite Paper Lifecycle
    life_data = report.components.get("sqlite_lifecycle")
    life_checks = [c for c in report.checks if c.component == "sqlite_lifecycle"]
    life_status = (
        "CRITICAL"
        if any(c.status == "FAIL" for c in life_checks)
        else "DEGRADED"
        if any(c.status == "WARN" for c in life_checks)
        else "HEALTHY"
    )
    lines.append(f"[+] SQLITE PAPER LIFECYCLE: {life_status}")
    if life_data and "path" in life_data:
        lines.append(f"    Path:                 {life_data.get('path')}")
        lines.append(f"    Integrity Check:      {life_data.get('integrity', 'N/A')}")
        lines.append(f"    Telemetry Marks:      {life_data.get('marks_count', 0)} recorded")
    else:
        for c in life_checks:
            lines.append(f"    [{c.status}] {c.message}")
    lines.append("")

    lines.append(sub_border)
    lines.append(
        f"Summary: {report.summary.passed_checks} checks passed, "
        f"{report.summary.warnings_count} warnings, "
        f"{report.summary.failures_count} failures."
    )
    if report.issues:
        lines.append("Issues Detected:")
        for issue in report.issues:
            lines.append(f"  * {issue}")
    lines.append(border)

    return "\n".join(lines)


def format_quiet_summary(report: PipelineHealthReport) -> str:
    """Format a single-line minimal status summary."""
    if report.status == "HEALTHY":
        return (
            f"HEALTHY: All {report.summary.total_checks} checks passed "
            f"(heartbeats fresh, DB integrity ok, 0 dirty intents)"
        )
    if report.status == "DEGRADED":
        primary_issue = (
            report.issues[0] if report.issues else "heartbeat stale or scheduler backoff"
        )
        return f"DEGRADED: {primary_issue}"
    primary_failure = (
        report.issues[0] if report.issues else "missing files, db corruption, or dirty intents"
    )
    return f"CRITICAL: {primary_failure}"


def build_pipeline_health_report(
    *,
    storage_dir: Path,
    scheduler_dir: Path | None = None,
    stale_threshold_seconds: float = 120.0,
    daemon_health_file: Path | None = None,
    scheduler_health_file: Path | None = None,
    registry_file: Path | None = None,
    ledger_db: Path | None = None,
    lifecycle_db: Path | None = None,
    allow_missing_scheduler: bool = False,
    now: datetime | None = None,
) -> PipelineHealthReport:
    """Execute all health diagnostics and compile a unified PipelineHealthReport."""
    current_time = now or datetime.now(UTC)

    # 1. Path resolutions
    daemon_path = daemon_health_file or (storage_dir / "paper-daemon-health.json")
    registry_path = registry_file or (storage_dir / "candidate_registry.json")
    ledger_path = ledger_db or (storage_dir / "paper-ledger.sqlite3")
    lifecycle_path = lifecycle_db or (storage_dir / "paper-lifecycle.sqlite3")

    if scheduler_health_file:
        sched_path = scheduler_health_file
    elif scheduler_dir:
        sched_path = scheduler_dir / "scheduler-health.json"
    else:
        candidate1 = storage_dir / "scheduler" / "scheduler-health.json"
        candidate2 = storage_dir / "scheduler-health.json"
        if candidate1.is_file():
            sched_path = candidate1
        elif candidate2.is_file():
            sched_path = candidate2
        else:
            sched_path = candidate1

    all_checks: list[CheckItem] = []
    components: dict[str, Any] = {}

    # Check Paper Daemon
    daemon_data, daemon_checks = check_paper_daemon(
        daemon_path, current_time, stale_threshold_seconds
    )
    all_checks.extend(daemon_checks)
    components["paper_daemon"] = daemon_data

    daemon_active_count: int | None = None
    if daemon_data and isinstance(daemon_data.get("active_positions_count"), int):
        daemon_active_count = daemon_data["active_positions_count"]

    # Check Scheduler
    sched_data, sched_checks = check_scheduler(
        sched_path, current_time, stale_threshold_seconds, allow_missing_scheduler
    )
    all_checks.extend(sched_checks)
    components["scheduler"] = sched_data

    # Check Candidate Registry
    reg_data, reg_checks = check_candidate_registry(registry_path, storage_dir)
    all_checks.extend(reg_checks)
    components["candidate_registry"] = reg_data

    # Check SQLite Ledger
    ledger_data, ledger_checks = check_sqlite_ledger(ledger_path, daemon_active_count)
    all_checks.extend(ledger_checks)
    components["sqlite_ledger"] = ledger_data

    # Check SQLite Lifecycle
    life_data, life_checks = check_sqlite_lifecycle(lifecycle_path)
    all_checks.extend(life_checks)
    components["sqlite_lifecycle"] = life_data

    # Evaluate summary counts
    failures = [c for c in all_checks if c.status == "FAIL"]
    warnings = [c for c in all_checks if c.status == "WARN"]
    passed = [c for c in all_checks if c.status == "PASS"]

    if failures:
        overall_status: Literal["HEALTHY", "DEGRADED", "CRITICAL"] = "CRITICAL"
        exit_code = 2
    elif warnings:
        overall_status = "DEGRADED"
        exit_code = 1
    else:
        overall_status = "HEALTHY"
        exit_code = 0

    issues = [
        f"[{c.status}] {c.component}.{c.check}: {c.message}"
        for c in all_checks
        if c.status in ("WARN", "FAIL")
    ]

    summary = HealthSummary(
        total_checks=len(all_checks),
        passed_checks=len(passed),
        warnings_count=len(warnings),
        failures_count=len(failures),
    )

    return PipelineHealthReport(
        timestamp_utc=current_time.isoformat(),
        status=overall_status,
        exit_code=exit_code,
        storage_dir=str(storage_dir),
        stale_threshold_seconds=stale_threshold_seconds,
        summary=summary,
        components=components,
        checks=all_checks,
        issues=issues,
    )


def create_argument_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser for the health CLI."""
    parser = argparse.ArgumentParser(
        description="Unified Autonomous Pipeline Health Diagnostics CLI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path("artifacts/paper_live"),
        help="Base storage directory for paper runtime artifacts.",
    )
    parser.add_argument(
        "--scheduler-dir",
        type=Path,
        default=None,
        help=(
            "Directory for autonomous scheduler artifacts "
            "(defaults to <storage-dir>/scheduler or <storage-dir>)."
        ),
    )
    parser.add_argument(
        "--stale-threshold-seconds",
        type=float,
        default=120.0,
        help="Maximum allowable heartbeat age in seconds before declaring STALE.",
    )
    parser.add_argument(
        "--daemon-health-file",
        type=Path,
        default=None,
        help="Explicit path to paper-daemon-health.json.",
    )
    parser.add_argument(
        "--scheduler-health-file",
        type=Path,
        default=None,
        help="Explicit path to scheduler-health.json.",
    )
    parser.add_argument(
        "--registry-file",
        type=Path,
        default=None,
        help="Explicit path to candidate_registry.json.",
    )
    parser.add_argument(
        "--ledger-db",
        type=Path,
        default=None,
        help="Explicit path to paper-ledger.sqlite3.",
    )
    parser.add_argument(
        "--lifecycle-db",
        type=Path,
        default=None,
        help="Explicit path to paper-lifecycle.sqlite3.",
    )
    parser.add_argument(
        "--allow-missing-scheduler",
        action="store_true",
        default=False,
        help=(
            "Do not fail if scheduler-health.json is absent "
            "(useful during paper-only testing or bootstrapping)."
        ),
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="Override current UTC timestamp (ISO-8601) for deterministic offline testing.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON output to stdout.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Emit minimal single-line status summary.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for pipeline health diagnostics."""
    parser = create_argument_parser()
    args = parser.parse_args(argv)

    now_dt: datetime | None = None
    if args.now:
        try:
            now_clean = args.now.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(now_clean)
            now_dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except Exception as exc:
            sys.stderr.write(f"Error parsing --now timestamp: {exc}\n")
            return 2

    try:
        report = build_pipeline_health_report(
            storage_dir=args.storage_dir,
            scheduler_dir=args.scheduler_dir,
            stale_threshold_seconds=args.stale_threshold_seconds,
            daemon_health_file=args.daemon_health_file,
            scheduler_health_file=args.scheduler_health_file,
            registry_file=args.registry_file,
            ledger_db=args.ledger_db,
            lifecycle_db=args.lifecycle_db,
            allow_missing_scheduler=args.allow_missing_scheduler,
            now=now_dt,
        )
    except Exception as exc:
        sys.stderr.write(f"Unexpected error executing health probe: {exc}\n")
        return 2

    if args.json:
        sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    elif args.quiet:
        sys.stdout.write(format_quiet_summary(report) + "\n")
    else:
        sys.stdout.write(format_console_dashboard(report) + "\n")

    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
