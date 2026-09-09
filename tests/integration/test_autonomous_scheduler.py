"""Milestone 6: Comprehensive E2E Integration Test Suite for Autonomous Scheduler Daemon.

Target Component: scripts/run_autonomous_scheduler.py
Authoritative Specifications:
- ORIGINAL_REQUEST.md (Section 2026-09-09T03:03:22Z)
- .agents/teamwork_preview_orchestrator_6/PROJECT.md
- .agents/teamwork_preview_spec_miner_survey6_2/spec.md
- .agents/teamwork_preview_explorer_survey6_3/report.md

Covers Tiers 1-4:
1. CLI flag parsing, validation, and forbidden credential rejection (exit code 2).
2. Single-instance process lock: acquisition, concurrent second process rejection (exit code 4),
   and stale lockfile recovery.
3. Signal handling & graceful shutdown (unlinking lockfile, STOPPED health state, zero orphans).
4. Dual triggers: periodic interval trigger with fresh market data, early breach trigger with
   SQLite closed trades, and cooldown suppression (--min-cooldown-seconds).
5. Resilient exponential backoff on child failure/timeout, consecutive failures tracking,
   and reset on exit 0.
6. Deterministic telemetry output (scheduler-health.json) across all states.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pandas as pd
import pytest
from pydantic import Field

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    DomainModel,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    CandidateManifestEntry,
    build_candidate_registry_manifest,
    write_candidate_registry,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
    write_creator_candidate_artifact,
)

SCHEDULER_SCRIPT = _REPO_ROOT / "scripts" / "run_autonomous_scheduler.py"
CYCLE_SCRIPT = _REPO_ROOT / "scripts" / "run_autonomous_cycle.py"
CANONICAL_PARQUET = (
    _REPO_ROOT / "research" / "immutable-data" / "5m" / "canonical" / "BTCUSDT-5m.parquet"
)

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
DUMMY_HASH_A = "a" * 64
DUMMY_HASH_B = "b" * 64
DUMMY_QUAL_HASH = "c" * 64
SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)

# Skip guard for integration tests that invoke scripts/run_autonomous_scheduler.py
# when the implementation file is not yet present on disk during early milestone stages.
requires_scheduler = pytest.mark.skipif(
    not SCHEDULER_SCRIPT.is_file(),
    reason="scripts/run_autonomous_scheduler.py has not yet been delivered by Worker M7",
)


# ==============================================================================
# FORMAL PYDANTIC TELEMETRY & LOCK MODELS (FOR INDEPENDENT VERIFICATION)
# ==============================================================================


SchedulerStatus = Literal["IDLE", "RUNNING_CYCLE", "BACKOFF", "STOPPED"]
TriggerType = Literal["interval", "breach", "manual_once"]


class LastCycleResult(DomainModel):
    """Execution telemetry schema from the most recently executed autonomous cycle."""

    cycle_id: str | None = Field(default=None, description="Unique cycle execution identifier")
    trigger_type: TriggerType = Field(description="Cause of cycle trigger")
    status: str = Field(
        description="Result status string: completed_admitted, completed_rejected, failed, timeout"
    )
    exit_code: int = Field(description="Subprocess exit code (0, 2, 3, etc.)")
    candidate_id: str | None = Field(default=None, description="Admitted candidate ID if admitted")
    admitted: bool = Field(default=False, description="True if candidate achieved admission")
    executed_at: str = Field(description="ISO-8601 UTC timestamp of cycle start")
    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Elapsed execution duration in seconds"
    )
    error_message: str | None = Field(
        default=None, description="Sanitized failure diagnostic message"
    )


class SchedulerHealthCheckpoint(DomainModel):
    """Durable runtime telemetry schema matching scheduler-health.json."""

    status: SchedulerStatus = Field(description="Current daemon operational status")
    pid: int | None = Field(default=None, description="OS process ID of daemon; None when stopped")
    started_at: str = Field(description="ISO-8601 UTC timestamp when scheduler started")
    updated_at: str = Field(description="ISO-8601 UTC timestamp of latest update")
    last_run_at: str | None = Field(
        default=None, description="ISO-8601 UTC timestamp when last cycle started"
    )
    next_run_at: str | None = Field(
        default=None, description="ISO-8601 UTC timestamp for next scheduled cycle"
    )
    consecutive_failures: int = Field(default=0, ge=0, description="Count of consecutive failures")
    total_cycles_executed: int = Field(default=0, ge=0, description="Total cycle runs attempted")
    admitted_candidates_count: int = Field(default=0, ge=0, description="Total candidates admitted")
    last_cycle_result: LastCycleResult | None = Field(
        default=None, description="Result of most recent cycle"
    )
    symbol: str = Field(description="Target market symbol")
    lockfile: str = Field(description="Path to active process lockfile")
    mode: Literal["daemon", "once"] = Field(default="daemon", description="Execution mode")


class SchedulerLockPayload(DomainModel):
    """Schema for daemon process lockfile."""

    pid: int
    started_at: str
    hostname: str
    symbol: str
    command: str | None = None
    lock_version: int = 1


# ==============================================================================
# TEST FIXTURES & SYNTHETIC ENVIRONMENT HELPERS
# ==============================================================================


def calculate_expected_backoff(
    failures: int,
    base: float = 60.0,
    factor: float = 2.0,
    max_backoff: float = 3600.0,
) -> float:
    """Authoritative mathematical reference for exponential backoff delay."""
    if failures <= 0:
        return 0.0
    delay = base * (factor ** (failures - 1))
    return min(max_backoff, delay)


def is_pid_alive_reference(pid: int) -> bool:
    """Deterministic reference PID liveness checker without third-party dependencies."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        kernel32 = ctypes.windll.kernel32
        h_process = kernel32.OpenProcess(
            process_query_limited_information | synchronize, False, pid
        )
        if not h_process:
            error_code = kernel32.GetLastError()
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
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True


def _build_test_candidate(
    candidate_id: str,
    symbol: str = "BTCUSDT",
    stop_mult: str = "1.5",
    tp_mult: str = "3.0",
) -> CreatorCandidateArtifact:
    """Build a valid CreatorCandidateArtifact with ATR risk profile."""
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,),
            timeframe="5m",
            regime_context_timeframe="15m",
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 35", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 55", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal(stop_mult),
            take_profit_atr_multiplier=Decimal(tp_mult),
            trailing_atr_multiplier=Decimal("1.0"),
        ),
    )
    return build_creator_candidate_artifact(
        candidate_id=candidate_id,
        strategy=strategy,
        bundle_hash=DUMMY_HASH_A,
        dataset_registry_hash=DUMMY_HASH_B,
        creator_run_id=f"run-{candidate_id}",
        research_seed=42,
        created_at=NOW,
    )


def _init_test_ledger(
    db_path: Path,
    cand: CreatorCandidateArtifact,
    symbol: str = "BTCUSDT",
    failing_trades_count: int = 0,
    winning_trades_count: int = 0,
) -> None:
    """Initialize SQLite paper ledger schema and optionally insert trades."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                approval_id TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                slippage_cost TEXT,
                gross_pnl TEXT,
                net_pnl TEXT
            );
            """
        )
        seq = (
            int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM paper_ledger_events"
                ).fetchone()[0]
            )
            + 1
        )
        # Insert failing trades (negative net PnL)
        for i in range(failing_trades_count):
            trade_id = f"trade-fail-{i + 1:03d}"
            t_open = (NOW - timedelta(minutes=10 * (failing_trades_count - i))).isoformat()
            t_close = (NOW - timedelta(minutes=10 * (failing_trades_count - i) - 5)).isoformat()
            conn.execute(
                """
                INSERT INTO paper_ledger_events VALUES (
                    ?, 'open', ?, ?, ?, ?, 'LONG', '0.002', '50000.0',
                    ?, 'app-open', '0.05', NULL, '0.01', NULL, NULL
                );
                """,
                (seq, trade_id, cand.candidate_id, cand.artifact_hash, symbol, t_open),
            )
            seq += 1
            conn.execute(
                """
                INSERT INTO paper_ledger_events VALUES (
                    ?, 'close', ?, ?, ?, ?, 'LONG', '0.002', '45000.0',
                    ?, 'app-close', '0.05', '0.05', '0.01', '-10.0', '-10.1'
                );
                """,
                (seq, trade_id, cand.candidate_id, cand.artifact_hash, symbol, t_close),
            )
            seq += 1

        # Insert winning trades (positive net PnL)
        for i in range(winning_trades_count):
            trade_id = f"trade-win-{i + 1:03d}"
            t_open = (NOW - timedelta(minutes=10 * (winning_trades_count - i))).isoformat()
            t_close = (NOW - timedelta(minutes=10 * (winning_trades_count - i) - 5)).isoformat()
            conn.execute(
                """
                INSERT INTO paper_ledger_events VALUES (
                    ?, 'open', ?, ?, ?, ?, 'LONG', '0.002', '50000.0',
                    ?, 'app-open', '0.05', NULL, '0.01', NULL, NULL
                );
                """,
                (seq, trade_id, cand.candidate_id, cand.artifact_hash, symbol, t_open),
            )
            seq += 1
            conn.execute(
                """
                INSERT INTO paper_ledger_events VALUES (
                    ?, 'close', ?, ?, ?, ?, 'LONG', '0.002', '55000.0',
                    ?, 'app-close', '0.05', '0.05', '0.01', '10.0', '9.9'
                );
                """,
                (seq, trade_id, cand.candidate_id, cand.artifact_hash, symbol, t_close),
            )
            seq += 1


def _create_synthetic_parquet(
    target_path: Path,
    num_bars: int = 150,
    end_time: datetime | None = None,
) -> None:
    """Create a synthetic 5m Parquet file for testing."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    end = end_time or NOW
    timestamps = [end - timedelta(minutes=5 * (num_bars - 1 - i)) for i in range(num_bars)]
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [50000.0 + (i * 2.0) for i in range(num_bars)],
            "high": [50100.0 + (i * 2.0) for i in range(num_bars)],
            "low": [49900.0 + (i * 2.0) for i in range(num_bars)],
            "close": [50050.0 + (i * 2.0) for i in range(num_bars)],
            "volume": [10.0] * num_bars,
        }
    )
    df.to_parquet(target_path, index=False)


def poll_health_checkpoint(
    health_file: Path,
    timeout: float = 8.0,
    expected_status: str | None = None,
    min_cycles: int | None = None,
    proc: subprocess.Popen[str] | None = None,
) -> SchedulerHealthCheckpoint:
    """Poll scheduler-health.json handling Windows NTFS concurrent file locks."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            pass
        if health_file.is_file():
            try:
                content = health_file.read_text(encoding="utf-8")
                if content.strip():
                    data = SchedulerHealthCheckpoint.model_validate_json(content)
                    if expected_status is not None and data.status != expected_status:
                        time.sleep(0.03)
                        continue
                    if min_cycles is not None and data.total_cycles_executed < min_cycles:
                        time.sleep(0.03)
                        continue
                    return data
            except (OSError, ValueError, PermissionError) as err:
                last_err = err
        time.sleep(0.03)
    msg = (
        f"Health checkpoint {health_file} timed out after {timeout}s "
        f"(status={expected_status}, min_cycles={min_cycles}). Last error: {last_err}"
    )
    raise TimeoutError(msg)


def poll_lockfile(
    lockfile: Path,
    timeout: float = 8.0,
    exclude_pid: int | None = None,
    expected_pid: int | None = None,
) -> SchedulerLockPayload:
    """Poll scheduler.lock until valid JSON is parseable."""
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if lockfile.is_file():
            try:
                content = lockfile.read_text(encoding="utf-8")
                if content.strip():
                    payload = SchedulerLockPayload.model_validate_json(content)
                    if exclude_pid is not None and payload.pid == exclude_pid:
                        time.sleep(0.03)
                        continue
                    if expected_pid is not None and payload.pid != expected_pid:
                        time.sleep(0.03)
                        continue
                    return payload
            except (OSError, ValueError, PermissionError) as err:
                last_err = err
        time.sleep(0.03)
    raise TimeoutError(f"Timed out waiting for lockfile {lockfile}. Last err: {last_err}")


def spawn_scheduler(
    args: list[str],
    cwd: Path = _REPO_ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    """Spawn run_autonomous_scheduler.py in background with Windows process group support."""
    cmd = [sys.executable, str(SCHEDULER_SCRIPT)] + args
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
        env=env,
    )


def terminate_scheduler(
    proc: subprocess.Popen[str],
    timeout: float = 8.0,
) -> int:
    """Gracefully terminate scheduler daemon via CTRL_BREAK (Win32) or SIGINT (POSIX)."""
    if proc.poll() is not None:
        return proc.returncode
    try:
        if sys.platform == "win32":
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except ValueError, OSError:
                proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=3.0)


# ==============================================================================
# TIER 0: PURE UNIT TESTS (VALIDATING CONTRACTS & LOGIC INDEPENDENTLY)
# ==============================================================================


def test_scheduler_telemetry_schema_validation() -> None:
    """Validate SchedulerHealthCheckpoint strictly against payload specifications."""
    raw_payload = {
        "status": "IDLE",
        "pid": 12345,
        "started_at": "2026-09-09T03:00:00+00:00",
        "updated_at": "2026-09-09T03:05:00+00:00",
        "last_run_at": "2026-09-09T03:00:05+00:00",
        "next_run_at": "2026-09-09T04:00:05+00:00",
        "consecutive_failures": 0,
        "total_cycles_executed": 1,
        "admitted_candidates_count": 1,
        "last_cycle_result": {
            "cycle_id": "cycle-001",
            "trigger_type": "interval",
            "status": "completed_admitted",
            "exit_code": 0,
            "candidate_id": "cand-001",
            "admitted": True,
            "executed_at": "2026-09-09T03:00:05+00:00",
            "duration_seconds": 12.5,
            "error_message": None,
        },
        "symbol": "BTCUSDT",
        "lockfile": "artifacts/scheduler.lock",
        "mode": "daemon",
    }
    model = SchedulerHealthCheckpoint.model_validate(raw_payload)
    assert model.status == "IDLE"
    assert model.pid == 12345
    assert model.total_cycles_executed == 1
    assert model.admitted_candidates_count == 1
    assert model.last_cycle_result is not None
    assert model.last_cycle_result.admitted is True

    # Check that invalid status string is rejected
    invalid_payload = dict(raw_payload)
    invalid_payload["status"] = "INVALID_STATUS"
    with pytest.raises(ValueError):
        SchedulerHealthCheckpoint.model_validate(invalid_payload)


def test_scheduler_lock_payload_schema_validation() -> None:
    """Validate SchedulerLockPayload model serialization and deserialization."""
    payload = {
        "pid": 54321,
        "started_at": "2026-09-09T03:00:00+00:00",
        "hostname": "test-host",
        "symbol": "BTCUSDT",
        "command": "python scripts/run_autonomous_scheduler.py --symbol BTCUSDT",
        "lock_version": 1,
    }
    lock_model = SchedulerLockPayload.model_validate(payload)
    assert lock_model.pid == 54321
    assert lock_model.symbol == "BTCUSDT"
    assert lock_model.lock_version == 1

    # Verify JSON round-trip
    dumped = lock_model.model_dump_json()
    reconstructed = SchedulerLockPayload.model_validate_json(dumped)
    assert reconstructed.pid == lock_model.pid


def test_exponential_backoff_mathematical_progression() -> None:
    """Verify binary exponential backoff calculation: min(max, base * factor^(failures - 1))."""
    base = 60.0
    factor = 2.0
    max_b = 3600.0

    assert calculate_expected_backoff(0, base, factor, max_b) == 0.0
    assert calculate_expected_backoff(1, base, factor, max_b) == 60.0
    assert calculate_expected_backoff(2, base, factor, max_b) == 120.0
    assert calculate_expected_backoff(3, base, factor, max_b) == 240.0
    assert calculate_expected_backoff(4, base, factor, max_b) == 480.0
    assert calculate_expected_backoff(5, base, factor, max_b) == 960.0
    assert calculate_expected_backoff(6, base, factor, max_b) == 1920.0
    assert calculate_expected_backoff(7, base, factor, max_b) == 3600.0  # capped
    assert calculate_expected_backoff(8, base, factor, max_b) == 3600.0  # capped


def test_is_pid_alive_self_and_dead() -> None:
    """Verify cross-platform PID liveness helper detects active PID and dead PID."""
    # Self process must be alive
    current_pid = os.getpid()
    assert is_pid_alive_reference(current_pid) is True

    # PID 0 or negative must be dead
    assert is_pid_alive_reference(0) is False
    assert is_pid_alive_reference(-1) is False

    # High non-existent PID should be dead (999999)
    assert is_pid_alive_reference(999999) is False


# ==============================================================================
# TIER 1: CLI ARGUMENT PARSING, VALIDATION & CREDENTIAL SANITIZATION
# ==============================================================================


@requires_scheduler
def test_cli_help_displays_options_and_exits_0() -> None:
    """Verify that --help displays all required CLI options and exits with code 0."""
    result = subprocess.run(
        [sys.executable, str(SCHEDULER_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0
    stdout = result.stdout
    assert "--symbol" in stdout
    assert "--interval-seconds" in stdout
    assert "--min-cooldown-seconds" in stdout
    assert "--provider" in stdout
    assert "--model" in stdout
    assert "--once" in stdout
    assert "--lockfile-path" in stdout
    assert "--output-dir" in stdout


@requires_scheduler
def test_cli_missing_required_symbol_rejected_exit_code_2() -> None:
    """Verify that executing without --symbol is rejected with exit code 2."""
    result = subprocess.run(
        [sys.executable, str(SCHEDULER_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2
    assert "symbol" in result.stderr.lower()


@requires_scheduler
@pytest.mark.parametrize(
    "invalid_symbol",
    ["btcusdt", "BTC-USDT", "BTC/USDT", "ETH_USDT", "123-INVALID"],
)
def test_cli_invalid_symbol_format_rejected_exit_code_2(invalid_symbol: str) -> None:
    """Verify that invalid symbol formats (lowercase, hyphens, slashes) exit with code 2."""
    result = subprocess.run(
        [sys.executable, str(SCHEDULER_SCRIPT), "--symbol", invalid_symbol],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2
    assert "symbol" in result.stderr.lower()


@requires_scheduler
@pytest.mark.parametrize(
    "forbidden_flag",
    [
        "--api-key",
        "--api_key",
        "--key",
        "-k",
        "--token",
        "--google-api-key",
        "--gemini-api-key",
        "--google-ai-studio-api-key",
    ],
)
def test_cli_forbidden_credential_flags_rejected_exit_code_2(forbidden_flag: str) -> None:
    """Verify credential flags via CLI are rejected with exit code 2 and zero secrets leaked."""
    test_secret = "AIzaSyFakeSecretToken1234567890ABCDEF"
    result = subprocess.run(
        [
            sys.executable,
            str(SCHEDULER_SCRIPT),
            "--symbol",
            "BTCUSDT",
            forbidden_flag,
            test_secret,
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2
    # Verify that stderr contains sanitized error
    assert "forbidden" in result.stderr.lower() or "forbidden_cli_argument" in result.stderr
    # Verify strict zero credential leakage across stdout and stderr
    assert test_secret not in result.stdout
    assert test_secret not in result.stderr
    assert SECRET_PATTERN.search(result.stdout) is None
    assert SECRET_PATTERN.search(result.stderr) is None


@requires_scheduler
def test_cli_interval_less_than_cooldown_rejected_exit_code_2() -> None:
    """Verify validation: --interval-seconds cannot be less than --min-cooldown-seconds."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCHEDULER_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--interval-seconds",
            "60",
            "--min-cooldown-seconds",
            "300",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2
    assert "cooldown" in result.stderr.lower() or "interval" in result.stderr.lower()


@requires_scheduler
@pytest.mark.parametrize("invalid_interval", ["0", "-10", "-3600"])
def test_cli_invalid_interval_bounds_rejected_exit_code_2(invalid_interval: str) -> None:
    """Verify that non-positive intervals are rejected with exit code 2."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCHEDULER_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--interval-seconds",
            invalid_interval,
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2


@requires_scheduler
def test_cli_invalid_cooldown_bounds_rejected_exit_code_2() -> None:
    """Verify that negative cooldown is rejected with exit code 2."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCHEDULER_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--min-cooldown-seconds",
            "-5.0",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2


@requires_scheduler
def test_cli_invalid_backoff_bounds_rejected_exit_code_2() -> None:
    """Verify that max-backoff less than base-backoff is rejected with exit code 2."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCHEDULER_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--base-backoff-seconds",
            "100.0",
            "--max-backoff-seconds",
            "50.0",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2


@requires_scheduler
def test_cli_invalid_provider_choice_rejected_exit_code_2() -> None:
    """Verify that unsupported provider option exits with code 2."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCHEDULER_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--provider",
            "unsupported_provider_foo",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 2


# ==============================================================================
# TIER 2: SINGLE-INSTANCE PROCESS LOCK & STALE LOCKFILE RECOVERY
# ==============================================================================


@requires_scheduler
def test_single_instance_lock_acquisition_and_json_payload(tmp_path: Path) -> None:
    """Verify scheduler acquires lockfile and writes JSON payload with PID, symbol, hostname."""
    output_dir = tmp_path / "scheduler_out"
    lockfile_path = output_dir / "scheduler.lock"

    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--lockfile-path",
            str(lockfile_path),
            "--interval-seconds",
            "3600",
            "--poll-interval-seconds",
            "0.1",
        ]
    )
    try:
        lock_payload = poll_lockfile(lockfile_path, timeout=6.0)
        assert lock_payload.pid == proc.pid
        assert lock_payload.symbol == "BTCUSDT"
        assert len(lock_payload.hostname) > 0
        assert lock_payload.lock_version == 1
    finally:
        terminate_scheduler(proc)


@requires_scheduler
def test_concurrent_second_process_rejected_exit_code_4(tmp_path: Path) -> None:
    """Verify that a second concurrent scheduler instance is rejected with exit code 4."""
    output_dir = tmp_path / "scheduler_out"
    lockfile_path = output_dir / "scheduler.lock"

    # Start instance 1
    proc1 = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--lockfile-path",
            str(lockfile_path),
            "--interval-seconds",
            "3600",
            "--poll-interval-seconds",
            "0.1",
        ]
    )
    try:
        # Wait until proc1 acquires lock
        lock_payload = poll_lockfile(lockfile_path, timeout=6.0, expected_pid=proc1.pid)
        assert lock_payload.pid == proc1.pid

        # Attempt to start instance 2 with the same lockfile
        result2 = subprocess.run(
            [
                sys.executable,
                str(SCHEDULER_SCRIPT),
                "--symbol",
                "BTCUSDT",
                "--output-dir",
                str(output_dir),
                "--lockfile-path",
                str(lockfile_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        # Process 2 must exit with code 4 (or 2) indicating lock acquisition contention
        assert result2.returncode in (4, 2)
        assert "lock" in result2.stderr.lower() or "lock_acquisition_failed" in result2.stderr

        # Verify proc1 was not disturbed and lockfile remains intact with proc1's PID
        assert proc1.poll() is None
        current_lock = SchedulerLockPayload.model_validate_json(
            lockfile_path.read_text(encoding="utf-8")
        )
        assert current_lock.pid == proc1.pid
    finally:
        terminate_scheduler(proc1)


@requires_scheduler
def test_stale_lockfile_recovery_dead_pid(tmp_path: Path) -> None:
    """Verify that a pre-existing lockfile belonging to a dead PID is reclaimed cleanly."""
    output_dir = tmp_path / "scheduler_out"
    output_dir.mkdir(parents=True, exist_ok=True)
    lockfile_path = output_dir / "scheduler.lock"

    # Write a stale lockfile with a PID that does not exist
    dead_pid = 999998
    stale_payload = {
        "pid": dead_pid,
        "started_at": (NOW - timedelta(hours=2)).isoformat(),
        "hostname": "ghost-host",
        "symbol": "BTCUSDT",
        "command": "python scripts/run_autonomous_scheduler.py",
        "lock_version": 1,
    }
    lockfile_path.write_text(json.dumps(stale_payload), encoding="utf-8")

    # Start scheduler
    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--lockfile-path",
            str(lockfile_path),
            "--interval-seconds",
            "3600",
            "--poll-interval-seconds",
            "0.1",
        ]
    )
    try:
        # Scheduler must reclaim the lock and overwrite with its own active PID
        lock_payload = poll_lockfile(
            lockfile_path, timeout=8.0, exclude_pid=dead_pid, expected_pid=proc.pid
        )
        assert lock_payload.pid == proc.pid
        assert lock_payload.pid != dead_pid
    finally:
        terminate_scheduler(proc)


@requires_scheduler
@pytest.mark.parametrize("non_positive_pid", [0, -1])
def test_stale_lockfile_recovery_non_positive_pid(tmp_path: Path, non_positive_pid: int) -> None:
    """Verify that a lockfile containing a non-positive PID (0 or -1) is cleanly reclaimed."""
    output_dir = tmp_path / f"scheduler_out_pid_{non_positive_pid}"
    output_dir.mkdir(parents=True, exist_ok=True)
    lockfile_path = output_dir / "scheduler.lock"

    stale_payload = {
        "pid": non_positive_pid,
        "started_at": (NOW - timedelta(hours=2)).isoformat(),
        "hostname": "ghost-host",
        "symbol": "BTCUSDT",
        "command": "python scripts/run_autonomous_scheduler.py",
        "lock_version": 1,
    }
    lockfile_path.write_text(json.dumps(stale_payload), encoding="utf-8")

    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--lockfile-path",
            str(lockfile_path),
            "--interval-seconds",
            "3600",
            "--poll-interval-seconds",
            "0.1",
        ]
    )
    try:
        lock_payload = poll_lockfile(
            lockfile_path,
            timeout=8.0,
            exclude_pid=non_positive_pid,
            expected_pid=proc.pid,
        )
        assert lock_payload.pid == proc.pid
        assert lock_payload.pid > 0
    finally:
        terminate_scheduler(proc)


@requires_scheduler
def test_corrupt_lockfile_older_than_grace_period_reclaimed(tmp_path: Path) -> None:
    """Verify unparseable lockfile older than 10 seconds grace period is reclaimed."""
    output_dir = tmp_path / "scheduler_out"
    output_dir.mkdir(parents=True, exist_ok=True)
    lockfile_path = output_dir / "scheduler.lock"

    # Write corrupt lockfile
    lockfile_path.write_text("CORRUPTED_JSON_DATA_!@#$%", encoding="utf-8")
    # Backdate mtime to 60 seconds ago (> 10s grace period)
    old_time = time.time() - 60.0
    os.utime(lockfile_path, (old_time, old_time))

    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--lockfile-path",
            str(lockfile_path),
            "--interval-seconds",
            "3600",
            "--poll-interval-seconds",
            "0.1",
        ]
    )
    try:
        lock_payload = poll_lockfile(lockfile_path, timeout=6.0)
        assert lock_payload.pid == proc.pid
    finally:
        terminate_scheduler(proc)


# ==============================================================================
# TIER 3: SIGNAL HANDLING & GRACEFUL SHUTDOWN
# ==============================================================================


@requires_scheduler
def test_graceful_shutdown_unlinks_lockfile_and_emits_stopped(tmp_path: Path) -> None:
    """Verify that SIGINT/SIGTERM cleanly shuts down daemon, unlinks lock, and sets STOPPED."""
    output_dir = tmp_path / "scheduler_out"
    lockfile_path = output_dir / "scheduler.lock"
    health_file = output_dir / "scheduler-health.json"

    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--lockfile-path",
            str(lockfile_path),
            "--health-file",
            str(health_file),
            "--interval-seconds",
            "3600",
            "--poll-interval-seconds",
            "0.1",
        ]
    )
    try:
        # Wait until IDLE health checkpoint is written
        health = poll_health_checkpoint(health_file, timeout=6.0, expected_status="IDLE", proc=proc)
        assert health.status == "IDLE"
        assert lockfile_path.is_file()

        # Send graceful shutdown signal
        exit_code = terminate_scheduler(proc, timeout=6.0)
        assert exit_code == 0

        # Verify lockfile has been cleanly unlinked
        assert not lockfile_path.exists()

        # Verify final health telemetry reflects STOPPED status with null PID
        stopped_health = poll_health_checkpoint(health_file, timeout=4.0, expected_status="STOPPED")
        assert stopped_health.status == "STOPPED"
        assert stopped_health.pid is None
        assert stopped_health.next_run_at is None
    finally:
        terminate_scheduler(proc)


# ==============================================================================
# TIER 4: DUAL TRIGGERS (INTERVAL & LEDGER BREACH) & COOLDOWN GUARD
# ==============================================================================


@requires_scheduler
def test_interval_trigger_fires_when_fresh_market_data_present(tmp_path: Path) -> None:
    """Verify interval trigger executes cycle when interval expires and fresh 5m data is present."""
    output_dir = tmp_path / "scheduler_out"
    parquet_path = tmp_path / "market-5m.parquet"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    registry_path = tmp_path / "candidate_registry.json"
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    health_file = output_dir / "scheduler-health.json"

    # Prepare fixtures
    _create_synthetic_parquet(parquet_path, num_bars=120)
    cand = _build_test_candidate("cand-initial-01")
    cand_file = candidates_dir / f"{cand.candidate_id}.json"
    write_creator_candidate_artifact(cand_file, cand)
    _init_test_ledger(ledger_path, cand, failing_trades_count=0)

    # Initial manifest
    entry = CandidateManifestEntry(
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=str(cand_file),
        qualification_hash=DUMMY_QUAL_HASH,
        admitted_at=NOW.isoformat(),
    )
    manifest = build_candidate_registry_manifest(symbols={"BTCUSDT": entry})
    write_candidate_registry(registry_path, manifest)

    # Start scheduler with 1-second interval, 0.2-second cooldown, demo provider
    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--health-file",
            str(health_file),
            "--parquet-path",
            str(parquet_path),
            "--ledger-db",
            str(ledger_path),
            "--candidate-registry-path",
            str(registry_path),
            "--interval-seconds",
            "1",
            "--min-cooldown-seconds",
            "0.2",
            "--poll-interval-seconds",
            "0.1",
            "--provider",
            "demo",
        ]
    )
    try:
        # Wait for at least 1 cycle to execute and transition back to IDLE
        health = poll_health_checkpoint(
            health_file, timeout=12.0, expected_status="IDLE", min_cycles=1, proc=proc
        )
        assert health.total_cycles_executed >= 1
        assert health.last_cycle_result is not None
        assert health.last_cycle_result.trigger_type == "interval"
    finally:
        terminate_scheduler(proc)


@requires_scheduler
def test_interval_trigger_postponed_when_data_not_fresh(tmp_path: Path) -> None:
    """Verify that scheduler postpones interval cycle if Parquet market data has not updated."""
    output_dir = tmp_path / "scheduler_out"
    parquet_path = tmp_path / "market-5m.parquet"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    health_file = output_dir / "scheduler-health.json"

    _create_synthetic_parquet(parquet_path, num_bars=120)
    cand = _build_test_candidate("cand-fresh-test")
    _init_test_ledger(ledger_path, cand)

    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--health-file",
            str(health_file),
            "--parquet-path",
            str(parquet_path),
            "--ledger-db",
            str(ledger_path),
            "--interval-seconds",
            "1",
            "--min-cooldown-seconds",
            "0.2",
            "--poll-interval-seconds",
            "0.1",
            "--provider",
            "demo",
        ]
    )
    try:
        # First cycle runs on initial fresh data
        h1 = poll_health_checkpoint(
            health_file, timeout=10.0, expected_status="IDLE", min_cycles=1, proc=proc
        )
        cycles_after_run1 = h1.total_cycles_executed

        # Sleep for 1.5 seconds WITHOUT updating parquet file (mtime unchanged)
        time.sleep(1.5)

        # Check telemetry: total_cycles_executed must NOT increment because data is not fresh
        h2 = poll_health_checkpoint(health_file, timeout=4.0, proc=proc)
        assert h2.total_cycles_executed == cycles_after_run1
    finally:
        terminate_scheduler(proc)


@requires_scheduler
def test_ledger_breach_trigger_fires_ahead_of_schedule(tmp_path: Path) -> None:
    """Verify closed trades breaching qualification policy trigger cycle early before interval."""
    output_dir = tmp_path / "scheduler_out"
    parquet_path = tmp_path / "market-5m.parquet"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    registry_path = tmp_path / "candidate_registry.json"
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    health_file = output_dir / "scheduler-health.json"

    _create_synthetic_parquet(parquet_path, num_bars=120)
    cand = _build_test_candidate("cand-breach-target")
    cand_file = candidates_dir / f"{cand.candidate_id}.json"
    write_creator_candidate_artifact(cand_file, cand)

    # Initialize ledger with zero trades
    _init_test_ledger(ledger_path, cand, failing_trades_count=0)

    # Register candidate in manifest
    entry = CandidateManifestEntry(
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=str(cand_file),
        qualification_hash=DUMMY_QUAL_HASH,
        admitted_at=NOW.isoformat(),
    )
    manifest = build_candidate_registry_manifest(symbols={"BTCUSDT": entry})
    write_candidate_registry(registry_path, manifest)

    # Start scheduler with 3600s interval, fast breach check (0.2s), low cooldown (0.2s)
    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--health-file",
            str(health_file),
            "--parquet-path",
            str(parquet_path),
            "--ledger-db",
            str(ledger_path),
            "--candidate-registry-path",
            str(registry_path),
            "--interval-seconds",
            "3600",
            "--min-cooldown-seconds",
            "0.2",
            "--poll-interval-seconds",
            "0.1",
            "--check-breach-interval-seconds",
            "0.2",
            "--provider",
            "demo",
        ]
    )
    try:
        # Wait until scheduler is IDLE
        poll_health_checkpoint(health_file, timeout=6.0, expected_status="IDLE", proc=proc)

        # Inject 5 failing closed trades into ledger (net loss, 0% win rate -> breaches policy)
        _init_test_ledger(ledger_path, cand, failing_trades_count=5)

        # Scheduler must detect the breach and fire cycle ahead of 3600s interval
        health = poll_health_checkpoint(health_file, timeout=12.0, min_cycles=1, proc=proc)
        assert health.total_cycles_executed >= 1
        assert health.last_cycle_result is not None
        assert health.last_cycle_result.trigger_type == "breach"
    finally:
        terminate_scheduler(proc)


@requires_scheduler
def test_ledger_zero_trades_does_not_trigger_breach(tmp_path: Path) -> None:
    """Verify that newly admitted candidate with 0 trades does NOT trigger an early breach cycle."""
    output_dir = tmp_path / "scheduler_out"
    parquet_path = tmp_path / "market-5m.parquet"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    health_file = output_dir / "scheduler-health.json"

    _create_synthetic_parquet(parquet_path, num_bars=120)
    cand = _build_test_candidate("cand-zero-trades")
    # 0 trades inserted
    _init_test_ledger(ledger_path, cand, failing_trades_count=0)

    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--health-file",
            str(health_file),
            "--parquet-path",
            str(parquet_path),
            "--ledger-db",
            str(ledger_path),
            "--interval-seconds",
            "3600",
            "--min-cooldown-seconds",
            "0.2",
            "--poll-interval-seconds",
            "0.1",
            "--check-breach-interval-seconds",
            "0.2",
            "--provider",
            "demo",
        ]
    )
    try:
        poll_health_checkpoint(health_file, timeout=6.0, expected_status="IDLE", proc=proc)
        # Sleep 1 second; verify cycle is NOT launched
        time.sleep(1.0)
        h = poll_health_checkpoint(health_file, timeout=2.0, proc=proc)
        assert h.total_cycles_executed == 0
        assert h.status == "IDLE"
    finally:
        terminate_scheduler(proc)


@requires_scheduler
def test_cooldown_guard_suppresses_rapid_fire_triggers(tmp_path: Path) -> None:
    """Verify that --min-cooldown-seconds suppresses early triggers during cooldown period."""
    output_dir = tmp_path / "scheduler_out"
    parquet_path = tmp_path / "market-5m.parquet"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    registry_path = tmp_path / "candidate_registry.json"
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    health_file = output_dir / "scheduler-health.json"

    _create_synthetic_parquet(parquet_path, num_bars=120)
    cand = _build_test_candidate("cand-cooldown-target")
    cand_file = candidates_dir / f"{cand.candidate_id}.json"
    write_creator_candidate_artifact(cand_file, cand)
    _init_test_ledger(ledger_path, cand, failing_trades_count=5)

    entry = CandidateManifestEntry(
        candidate_id=cand.candidate_id,
        candidate_artifact_hash=cand.artifact_hash,
        artifact_path=str(cand_file),
        qualification_hash=DUMMY_QUAL_HASH,
        admitted_at=NOW.isoformat(),
    )
    manifest = build_candidate_registry_manifest(symbols={"BTCUSDT": entry})
    write_candidate_registry(registry_path, manifest)

    # Set cooldown to 3.0 seconds
    cooldown_secs = 3.0
    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--health-file",
            str(health_file),
            "--parquet-path",
            str(parquet_path),
            "--ledger-db",
            str(ledger_path),
            "--candidate-registry-path",
            str(registry_path),
            "--interval-seconds",
            "3600",
            "--min-cooldown-seconds",
            str(cooldown_secs),
            "--poll-interval-seconds",
            "0.1",
            "--check-breach-interval-seconds",
            "0.1",
            "--provider",
            "demo",
        ]
    )
    try:
        # Cycle 1 triggers due to initial breach
        h1 = poll_health_checkpoint(
            health_file, timeout=12.0, expected_status="IDLE", min_cycles=1, proc=proc
        )
        assert h1.total_cycles_executed == 1

        # Immediately inject 5 more losing trades during the active 3s cooldown window
        _init_test_ledger(ledger_path, cand, failing_trades_count=10)

        # Sleep for 1.0s (less than 3.0s cooldown)
        time.sleep(1.0)

        # Confirm that cycle count remains 1 (suppressed by cooldown)
        h_suppressed = poll_health_checkpoint(health_file, timeout=2.0, proc=proc)
        assert h_suppressed.total_cycles_executed == 1
    finally:
        terminate_scheduler(proc)


# ==============================================================================
# TIER 5: EXPONENTIAL BACKOFF & ERROR RECOVERY
# ==============================================================================


@requires_scheduler
def test_exponential_backoff_on_child_failure_increments_consecutive_failures(
    tmp_path: Path,
) -> None:
    """Verify child failure transitions daemon to BACKOFF and increments failure counter."""
    output_dir = tmp_path / "scheduler_out"
    parquet_path = tmp_path / "non_existent_data.parquet"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    health_file = output_dir / "scheduler-health.json"

    # Start scheduler pointing to missing Parquet file so child cycle runner fails
    base_backoff = 2.0
    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--health-file",
            str(health_file),
            "--parquet-path",
            str(parquet_path),
            "--ledger-db",
            str(ledger_path),
            "--interval-seconds",
            "3600",
            "--base-backoff-seconds",
            str(base_backoff),
            "--max-backoff-seconds",
            "10.0",
            "--poll-interval-seconds",
            "0.1",
            "--provider",
            "demo",
            "--once",
        ]
    )
    try:
        # When run in --once mode with failure, exit code is preserved from child (non-zero)
        exit_code = proc.wait(timeout=10.0)
        assert exit_code != 0

        # Telemetry should reflect the failure and consecutive_failures == 1
        health = poll_health_checkpoint(health_file, timeout=4.0)
        assert health.consecutive_failures >= 1
        assert health.last_cycle_result is not None
        assert health.last_cycle_result.exit_code != 0
    finally:
        terminate_scheduler(proc)


@requires_scheduler
def test_backoff_resets_to_zero_on_successful_cycle(tmp_path: Path) -> None:
    """Verify that consecutive_failures resets to 0 when subsequent cycle completes exit code 0."""
    output_dir = tmp_path / "scheduler_out"
    parquet_path = tmp_path / "market-5m.parquet"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    health_file = output_dir / "scheduler-health.json"

    _create_synthetic_parquet(parquet_path, num_bars=120)
    cand = _build_test_candidate("cand-reset-test")
    _init_test_ledger(ledger_path, cand)

    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--health-file",
            str(health_file),
            "--parquet-path",
            str(parquet_path),
            "--ledger-db",
            str(ledger_path),
            "--interval-seconds",
            "1",
            "--min-cooldown-seconds",
            "0.2",
            "--poll-interval-seconds",
            "0.1",
            "--provider",
            "demo",
        ]
    )
    try:
        health = poll_health_checkpoint(
            health_file, timeout=12.0, expected_status="IDLE", min_cycles=1, proc=proc
        )
        # On exit code 0, consecutive_failures must be 0
        assert health.consecutive_failures == 0
        assert health.status == "IDLE"
    finally:
        terminate_scheduler(proc)


# ==============================================================================
# TIER 6: TELEMETRY INVARIANTS, ONCE MODE & CANDIDATE ADMISSION
# ==============================================================================


@requires_scheduler
def test_single_pass_once_mode_execution(tmp_path: Path) -> None:
    """Verify that --once runs a single evaluation pass, unlinks lockfile, and exits cleanly."""
    output_dir = tmp_path / "scheduler_out"
    parquet_path = tmp_path / "market-5m.parquet"
    ledger_path = tmp_path / "paper-ledger.sqlite3"
    health_file = output_dir / "scheduler-health.json"
    lockfile_path = output_dir / "scheduler.lock"

    _create_synthetic_parquet(parquet_path, num_bars=120)
    cand = _build_test_candidate("cand-once-test")
    _init_test_ledger(ledger_path, cand)

    result = subprocess.run(
        [
            sys.executable,
            str(SCHEDULER_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(output_dir),
            "--health-file",
            str(health_file),
            "--lockfile-path",
            str(lockfile_path),
            "--parquet-path",
            str(parquet_path),
            "--ledger-db",
            str(ledger_path),
            "--provider",
            "demo",
            "--once",
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    # Exits 0 on clean single-shot completion
    assert result.returncode == 0

    # Lockfile must be unlinked
    assert not lockfile_path.exists()

    # Health telemetry reflects mode == "once"
    health = poll_health_checkpoint(health_file, timeout=4.0)
    assert health.mode == "once"
    assert health.total_cycles_executed == 1
    assert health.symbol == "BTCUSDT"
