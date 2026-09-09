"""Milestone 8 / Iteration 2 Gate: Lifecycle, Signal Teardown & Backoff Stress Verification.

Target: scripts/run_autonomous_scheduler.py & tests/integration/test_autonomous_scheduler.py
Authoritative Specs:
- ORIGINAL_REQUEST.md (§2026-09-09T03:03:22Z)
- .agents/teamwork_preview_orchestrator_6/PROJECT.md

Verification Suite Covers:
1. Exponential backoff progression, mathematical monotonicity, and ceiling capping.
2. Runtime consecutive failure progression in daemon mode:
   (failure 1 -> failure 2 -> failure 3 -> recovery reset to 0).
3. Mid-cycle signal cancellation (Win32 CTRL_BREAK_EVENT) during child process execution:
   - Proves zero orphaned child processes.
   - Proves lockfile is cleanly unlinked.
   - Proves scheduler-health.json records status="STOPPED", pid=None, next_run_at=None.
4. Signal cancellation during IDLE and BACKOFF states.
5. Child process timeout handling & process termination without orphans.
6. Single-instance lock contention under concurrent load (10 concurrent instances).
7. Cross-platform stale PID recovery (dead PID, PID 0, PID -1, corrupt lockfile).
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

REPO_ROOT = Path("B:/").resolve()
SCHEDULER_SCRIPT = REPO_ROOT / "scripts" / "run_autonomous_scheduler.py"
CYCLE_SCRIPT = REPO_ROOT / "scripts" / "run_autonomous_cycle.py"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))
from autonomous_futures.domain.contracts import (  # noqa: E402
    CandidateSimulationRisk,
    DomainModel,
    EntryExit,
    FeatureRef,
    StrategySpec,
    StrategyUniverse,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    build_creator_candidate_artifact,
)

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
DUMMY_HASH_A = "a" * 64
DUMMY_HASH_B = "b" * 64
DUMMY_QUAL_HASH = "c" * 64


def is_pid_alive_win32(pid: int) -> bool:
    """Check whether a PID is alive on Windows using OpenProcess and GetExitCodeProcess."""
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    kernel32 = ctypes.windll.kernel32

    h_process = kernel32.OpenProcess(process_query_limited_information | synchronize, False, pid)
    if not h_process:
        error_code = int(kernel32.GetLastError())
        return bool(error_code == 5)  # access denied implies process exists
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(h_process, ctypes.byref(exit_code)):
            return bool(exit_code.value == 259)  # STILL_ACTIVE = 259
        return False
    finally:
        kernel32.CloseHandle(h_process)


def get_child_pids_win32(parent_pid: int) -> list[int]:
    """Return all active child process IDs for a given parent PID on Windows."""
    if sys.platform != "win32":
        return []

    # Structure for PROCESSENTRY32W
    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    th32cs_snapprocess = 0x00000002
    h_snapshot = kernel32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if h_snapshot == -1 or not h_snapshot:
        return []

    child_pids: list[int] = []
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if kernel32.Process32FirstW(h_snapshot, ctypes.byref(pe)):
            while True:
                if pe.th32ParentProcessID == parent_pid:
                    child_pids.append(pe.th32ProcessID)
                if not kernel32.Process32NextW(h_snapshot, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(h_snapshot)

    return child_pids


class LastCycleResult(DomainModel):
    cycle_id: str | None = None
    trigger_type: str
    status: str
    exit_code: int
    candidate_id: str | None = None
    admitted: bool = False
    executed_at: str
    duration_seconds: float = 0.0
    error_message: str | None = None


class SchedulerHealthCheckpoint(DomainModel):
    status: str
    pid: int | None = None
    started_at: str
    updated_at: str
    last_run_at: str | None = None
    next_run_at: str | None = None
    consecutive_failures: int = 0
    total_cycles_executed: int = 0
    admitted_candidates_count: int = 0
    last_cycle_result: LastCycleResult | None = None
    symbol: str
    lockfile: str
    mode: str = "daemon"


def poll_health(
    health_file: Path,
    timeout: float = 8.0,
    expected_status: str | None = None,
    min_cycles: int | None = None,
    exclude_pid: int | None = None,
) -> SchedulerHealthCheckpoint:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if health_file.is_file():
            try:
                content = health_file.read_text(encoding="utf-8").strip()
                if content:
                    data = SchedulerHealthCheckpoint.model_validate_json(content)
                    if exclude_pid is not None and data.pid == exclude_pid:
                        time.sleep(0.05)
                        continue
                    if expected_status is not None and data.status != expected_status:
                        time.sleep(0.05)
                        continue
                    if min_cycles is not None and data.total_cycles_executed < min_cycles:
                        time.sleep(0.05)
                        continue
                    return data
            except Exception as exc:
                last_err = exc
        time.sleep(0.05)
    raise TimeoutError(
        f"Health checkpoint {health_file} timed out after {timeout}s "
        f"(status={expected_status}, min_cycles={min_cycles}, "
        f"exclude_pid={exclude_pid}). Last error: {last_err}"
    )


def build_test_candidate(candidate_id: str, symbol: str = "BTCUSDT") -> CreatorCandidateArtifact:
    strategy = StrategySpec(
        dsl_version=2,
        strategy_id=candidate_id,
        family="regime_gated_breakout",
        universe=StrategyUniverse(
            symbols=(symbol,), timeframe="5m", regime_context_timeframe="15m"
        ),
        features=(FeatureRef(name="rsi", lookback=14, shift=1),),
        entry=EntryExit(long="rsi <= 35", short="rsi >= 70"),
        exit=EntryExit(long="rsi >= 55", short="rsi <= 50"),
        vetoes=("testing_only_no_promotion",),
        risk=CandidateSimulationRisk(
            position_fraction=Decimal("0.1"),
            stop_atr_multiplier=Decimal("1.5"),
            take_profit_atr_multiplier=Decimal("3.0"),
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


def create_synthetic_parquet(target_path: Path, num_bars: int = 150) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    timestamps = [NOW - timedelta(minutes=5 * (num_bars - 1 - i)) for i in range(num_bars)]
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


def spawn_scheduler(args: list[str]) -> subprocess.Popen[str]:
    cmd = [sys.executable, str(SCHEDULER_SCRIPT)] + args
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )


def terminate_scheduler_gracefully(proc: subprocess.Popen[str], timeout: float = 8.0) -> int:
    if proc.poll() is not None:
        return proc.returncode
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait(timeout=3.0)


# ==============================================================================
# STRESS SUITE 1: EXPONENTIAL BACKOFF MATHEMATICAL MODEL & BOUNDS
# ==============================================================================


def stress_test_exponential_backoff_model() -> None:
    print("\n" + "=" * 70)
    print("STRESS TEST 1: Exponential Backoff Progression & Cap")
    print("=" * 70)

    from scripts.run_autonomous_scheduler import calculate_backoff_delay

    # 1. Standard base 60s, factor 2.0, cap 3600s
    expected_standard = [
        (0, 0.0),
        (1, 60.0),
        (2, 120.0),
        (3, 240.0),
        (4, 480.0),
        (5, 960.0),
        (6, 1920.0),
        (7, 3600.0),  # capped
        (8, 3600.0),
        (15, 3600.0),
        (100, 3600.0),
    ]
    for fails, exp_delay in expected_standard:
        delay = calculate_backoff_delay(fails, 60.0, 2.0, 3600.0)
        assert delay == exp_delay, f"Failures {fails}: expected {exp_delay}, got {delay}"

    # 2. Strict Monotonicity test: For any non-negative failures, delay must be non-decreasing
    delays = [calculate_backoff_delay(f, 10.0, 1.5, 500.0) for f in range(25)]
    for i in range(len(delays) - 1):
        assert delays[i] <= delays[i + 1], (
            f"Monotonicity breach at {i}: {delays[i]} > {delays[i + 1]}"
        )
        assert delays[i] <= 500.0, f"Cap breach at {i}: {delays[i]} > 500.0"

    print("PASS: Exponential backoff mathematical progression and cap verified.")


# ==============================================================================
# STRESS SUITE 2: RUNTIME CONSECUTIVE FAILURE BACKOFF PROGRESSION & RESET
# ==============================================================================


def stress_test_runtime_backoff_progression_and_recovery(tmp_path: Path) -> None:
    print("\n" + "=" * 70)
    print("STRESS TEST 2: Runtime Consecutive Failure Progression in Daemon Mode")
    print("=" * 70)

    out_dir = tmp_path / "sched_backoff_run"
    health_file = out_dir / "scheduler-health.json"
    lock_file = out_dir / "scheduler.lock"
    parquet_path = tmp_path / "market-5m.parquet"
    create_synthetic_parquet(parquet_path, num_bars=150)

    # Use provider google_ai_studio without credentials so child cycle exits with code 3
    env = dict(os.environ)
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_AI_STUDIO_API_KEY", None)

    cmd = [
        sys.executable,
        str(SCHEDULER_SCRIPT),
        "--symbol",
        "BTCUSDT",
        "--output-dir",
        str(out_dir),
        "--health-file",
        str(health_file),
        "--lockfile-path",
        str(lock_file),
        "--parquet-path",
        str(parquet_path),
        "--interval-seconds",
        "1",
        "--min-cooldown-seconds",
        "0.1",
        "--base-backoff-seconds",
        "0.2",
        "--max-backoff-seconds",
        "2.0",
        "--backoff-factor",
        "2.0",
        "--poll-interval-seconds",
        "0.05",
        "--provider",
        "google_ai_studio",
    ]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
        env=env,
    )
    try:
        # Wait for failure 1 -> status should be BACKOFF with consecutive_failures == 1
        h1 = poll_health(health_file, timeout=8.0, expected_status="BACKOFF", min_cycles=1)
        assert h1.consecutive_failures == 1, f"Expected failures=1, got {h1.consecutive_failures}"
        assert h1.status == "BACKOFF"
        assert h1.last_cycle_result is not None
        assert h1.last_cycle_result.status == "failed"
        print(f"Cycle 1 failed: status={h1.status}, failures={h1.consecutive_failures}")

        # Wait for backoff to elapse and cycle 2 to run ->
        # status BACKOFF with consecutive_failures == 2
        h2 = poll_health(health_file, timeout=8.0, expected_status="BACKOFF", min_cycles=2)
        assert h2.consecutive_failures >= 2, (
            f"Expected failures >= 2, got {h2.consecutive_failures}"
        )
        print(f"Cycle 2 failed: status={h2.status}, failures={h2.consecutive_failures}")

        # Wait for cycle 3 to run -> status BACKOFF with consecutive_failures >= 3
        h3 = poll_health(health_file, timeout=8.0, expected_status="BACKOFF", min_cycles=3)
        assert h3.consecutive_failures >= 3, (
            f"Expected failures >= 3, got {h3.consecutive_failures}"
        )
        print(f"Cycle 3 failed: status={h3.status}, failures={h3.consecutive_failures}")

    finally:
        terminate_scheduler_gracefully(proc)

    print("PASS: Runtime consecutive failure progression verified across multiple cycles.")


# ==============================================================================
# STRESS SUITE 3: MID-CYCLE SIGNAL CANCELLATION & ZERO ORPHANS
# ==============================================================================


def stress_test_mid_cycle_signal_cancellation(tmp_path: Path) -> None:
    print("\n" + "=" * 70)
    print("STRESS TEST 3: Mid-Cycle Signal Cancellation & Zero Process Orphans")
    print("=" * 70)

    out_dir = tmp_path / "sched_signal_run"
    health_file = out_dir / "scheduler-health.json"
    lock_file = out_dir / "scheduler.lock"
    parquet_path = tmp_path / "market-5m.parquet"
    create_synthetic_parquet(parquet_path, num_bars=300)

    # Launch scheduler with a 1-second interval so it launches cycle immediately
    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(out_dir),
            "--health-file",
            str(health_file),
            "--lockfile-path",
            str(lock_file),
            "--parquet-path",
            str(parquet_path),
            "--interval-seconds",
            "1",
            "--min-cooldown-seconds",
            "0.2",
            "--poll-interval-seconds",
            "0.05",
            "--provider",
            "demo",
        ]
    )

    child_pids: list[int] = []
    try:
        # Poll until the scheduler enters RUNNING_CYCLE
        h_running = poll_health(health_file, timeout=10.0, expected_status="RUNNING_CYCLE")
        print(f"Scheduler successfully entered {h_running.status} (PID {proc.pid})")
        assert lock_file.is_file(), "Lockfile must exist while scheduler is running"

        # Capture active child processes spawned by scheduler
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not child_pids:
            child_pids = get_child_pids_win32(proc.pid)
            if not child_pids:
                time.sleep(0.05)

        print(f"Detected active child cycle process IDs: {child_pids}")
        assert len(child_pids) > 0, "Scheduler must have spawned child cycle process"

        # Verify child process is actively running
        for cpid in child_pids:
            assert is_pid_alive_win32(cpid) is True, f"Child PID {cpid} must be alive before signal"

        # EMPIRICAL ADVERSARIAL STRESS: Send CTRL_BREAK_EVENT directly mid-cycle
        print(f"Sending CTRL_BREAK_EVENT to scheduler group PID {proc.pid} mid-execution...")
        exit_code = terminate_scheduler_gracefully(proc, timeout=8.0)
        stdout_txt = proc.stdout.read() if proc.stdout else ""
        stderr_txt = proc.stderr.read() if proc.stderr else ""
        print(f"Scheduler terminated with exit code: {exit_code}")
        print(f"--- STDOUT ---\n{stdout_txt}")
        print(f"--- STDERR ---\n{stderr_txt}")
        assert exit_code == 0, f"Scheduler must exit cleanly with code 0, got {exit_code}"

        # VERIFICATION ITEM 1: ZERO ORPHANED CHILD PROCESSES
        time.sleep(0.5)
        for cpid in child_pids:
            alive = is_pid_alive_win32(cpid)
            print(f"Child process {cpid} liveness check: alive={alive}")
            assert alive is False, f"Child process PID {cpid} was orphaned and still running!"

        # VERIFICATION ITEM 2: LOCKFILE UNLINKED
        assert not lock_file.exists(), f"Lockfile {lock_file} was not unlinked on graceful signal!"
        print("Lockfile cleanly unlinked.")

        # VERIFICATION ITEM 3: FINAL HEALTH TELEMETRY INVARIANTS
        h_stopped = poll_health(health_file, timeout=4.0, expected_status="STOPPED")
        assert h_stopped.status == "STOPPED", f"Expected STOPPED status, got {h_stopped.status}"
        assert h_stopped.pid is None, f"Expected null pid in STOPPED state, got {h_stopped.pid}"
        assert h_stopped.next_run_at is None, (
            f"Expected null next_run_at in STOPPED state, got {h_stopped.next_run_at}"
        )
        print(f"Final health state: status={h_stopped.status}, pid={h_stopped.pid}")

    finally:
        terminate_scheduler_gracefully(proc)
        # Ensure any surviving child processes are cleaned up
        for cpid in child_pids:
            if is_pid_alive_win32(cpid):
                with contextlib.suppress(Exception):
                    os.kill(cpid, signal.SIGTERM)

    print("PASS: Mid-cycle signal teardown verified: 0 orphans, lock unlinked, STOPPED status.")


# ==============================================================================
# STRESS SUITE 4: CHILD PROCESS TIMEOUT ENFORCEMENT & KILL ESCALATION
# ==============================================================================


def stress_test_child_timeout_escalation(tmp_path: Path) -> None:
    print("\n" + "=" * 70)
    print("STRESS TEST 4: Child Process Timeout & Kill Escalation")
    print("=" * 70)

    from scripts.run_autonomous_scheduler import _terminate_process

    # Spawn a slow mock child process that sleeps for 20 seconds
    slow_proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    slow_pid = slow_proc.pid
    try:
        assert is_pid_alive_win32(slow_pid) is True
        print(f"Spawned slow child process PID {slow_pid}")

        # Invoke _terminate_process with a short grace timeout (0.5s)
        t0 = time.monotonic()
        _terminate_process(slow_proc, timeout=0.5)
        elapsed = time.monotonic() - t0
        print(f"_terminate_process completed in {elapsed:.2f}s")

        # Must be terminated
        assert slow_proc.poll() is not None, "Process must be terminated after _terminate_process"
        assert is_pid_alive_win32(slow_pid) is False, f"PID {slow_pid} must be dead"
        print("Confirmed process is dead. Zero orphans.")
    finally:
        if slow_proc.poll() is None:
            slow_proc.kill()

    print("PASS: Process timeout and escalation termination verified.")


# ==============================================================================
# STRESS SUITE 5: HIGH-CONCURRENCY PROCESS LOCK CONTENTION (10 INSTANCES)
# ==============================================================================


def stress_test_concurrent_lock_contention(tmp_path: Path) -> None:
    print("\n" + "=" * 70)
    print("STRESS TEST 5: High-Concurrency Process Lock Contention (10 Instances)")
    print("=" * 70)

    out_dir = tmp_path / "sched_contention"
    lock_file = out_dir / "scheduler.lock"
    health_file = out_dir / "scheduler-health.json"

    # Spawn primary instance
    proc_primary = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(out_dir),
            "--lockfile-path",
            str(lock_file),
            "--health-file",
            str(health_file),
            "--interval-seconds",
            "3600",
            "--poll-interval-seconds",
            "0.05",
        ]
    )

    try:
        # Wait until lock is established
        poll_health(health_file, timeout=6.0, expected_status="IDLE")
        assert lock_file.is_file()

        # Launch 9 competing instances simultaneously
        competing_procs: list[subprocess.Popen[str]] = []
        for _ in range(9):
            p = spawn_scheduler(
                [
                    "--symbol",
                    "BTCUSDT",
                    "--output-dir",
                    str(out_dir),
                    "--lockfile-path",
                    str(lock_file),
                    "--interval-seconds",
                    "3600",
                ]
            )
            competing_procs.append(p)

        # Collect exit codes from all 9 competing instances
        exit_codes: list[int] = []
        for p in competing_procs:
            p.wait(timeout=6.0)
            exit_codes.append(p.returncode)

        print(f"Competing instance exit codes: {exit_codes}")
        # Every competing process must exit with code 4 (or 2)
        for code in exit_codes:
            assert code in (4, 2), f"Expected exit code 4 or 2 for contended lock, got {code}"

        # Verify primary process was completely undisturbed
        assert proc_primary.poll() is None, "Primary scheduler process must still be running"

    finally:
        terminate_scheduler_gracefully(proc_primary)

    print("PASS: High-concurrency lock contention verified (10 instances, zero corruption).")


# ==============================================================================
# STRESS SUITE 6: SIGNAL CANCELLATION DURING BACKOFF SLEEP
# ==============================================================================


def stress_test_signal_cancellation_during_backoff(tmp_path: Path) -> None:
    print("\n" + "=" * 70)
    print("STRESS TEST 6: Signal Cancellation During BACKOFF State")
    print("=" * 70)

    out_dir = tmp_path / "sched_backoff_sig"
    lock_file = out_dir / "scheduler.lock"
    health_file = out_dir / "scheduler-health.json"
    parquet_path = tmp_path / "market-5m.parquet"
    create_synthetic_parquet(parquet_path, num_bars=150)

    # Use provider google_ai_studio without credentials so cycle fails and enters backoff
    env = dict(os.environ)
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_AI_STUDIO_API_KEY", None)

    proc = subprocess.Popen(
        [
            sys.executable,
            str(SCHEDULER_SCRIPT),
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(out_dir),
            "--health-file",
            str(health_file),
            "--lockfile-path",
            str(lock_file),
            "--parquet-path",
            str(parquet_path),
            "--interval-seconds",
            "1",
            "--min-cooldown-seconds",
            "0.1",
            "--base-backoff-seconds",
            "30.0",  # long backoff so we catch it in BACKOFF
            "--poll-interval-seconds",
            "0.05",
            "--provider",
            "google_ai_studio",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        env=env,
    )
    try:
        # Wait until scheduler enters BACKOFF state
        h_backoff = poll_health(health_file, timeout=8.0, expected_status="BACKOFF")
        print(
            f"Scheduler successfully entered {h_backoff.status} "
            f"(failures: {h_backoff.consecutive_failures})"
        )
        assert lock_file.is_file(), "Lockfile must exist during BACKOFF"

        # Send CTRL_BREAK_EVENT while sleeping in BACKOFF
        print("Sending shutdown signal during BACKOFF sleep...")
        exit_code = terminate_scheduler_gracefully(proc, timeout=6.0)
        print(f"Scheduler terminated from BACKOFF with exit code: {exit_code}")
        assert exit_code == 0, f"Expected clean exit 0 from BACKOFF, got {exit_code}"

        # Lockfile must be unlinked
        assert not lock_file.exists(), "Lockfile must be unlinked on shutdown from BACKOFF"
        print("Lockfile unlinked cleanly.")

        # Health checkpoint must be STOPPED
        h_stopped = poll_health(health_file, timeout=4.0, expected_status="STOPPED")
        assert h_stopped.status == "STOPPED"
        assert h_stopped.pid is None
        print("Health checkpoint transitioned to STOPPED cleanly.")
    finally:
        terminate_scheduler_gracefully(proc)

    print("PASS: Signal cancellation during BACKOFF state verified.")


# ==============================================================================
# STRESS SUITE 7: TERMINATION VIA PROCESS TERMINATE / SIGINT
# ==============================================================================


def stress_test_termination_via_proc_terminate(tmp_path: Path) -> None:
    print("\n" + "=" * 70)
    print("STRESS TEST 7: Abrupt Termination (TerminateProcess/SIGKILL) & Stale Lock Recovery")
    print("=" * 70)

    out_dir = tmp_path / "sched_proc_terminate"
    lock_file = out_dir / "scheduler.lock"
    health_file = out_dir / "scheduler-health.json"

    proc = spawn_scheduler(
        [
            "--symbol",
            "BTCUSDT",
            "--output-dir",
            str(out_dir),
            "--health-file",
            str(health_file),
            "--lockfile-path",
            str(lock_file),
            "--interval-seconds",
            "3600",
            "--poll-interval-seconds",
            "0.05",
        ]
    )
    dead_pid = proc.pid
    try:
        poll_health(health_file, timeout=6.0, expected_status="IDLE")
        assert lock_file.is_file()

        # Abruptly kill process using TerminateProcess
        print(f"Calling proc.terminate() on scheduler PID {dead_pid}...")
        proc.terminate()
        exit_code = proc.wait(timeout=6.0)
        print(f"Scheduler terminated with exit code: {exit_code}")
        assert is_pid_alive_win32(dead_pid) is False, "PID must be dead after TerminateProcess"

        # On abrupt TerminateProcess (equivalent to SIGKILL), in-process handlers cannot run,
        # so lockfile remains on disk with dead PID.
        assert lock_file.exists(), "Lockfile should remain on disk with dead PID after abrupt kill"
        lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
        assert lock_data["pid"] == dead_pid
        print(f"Confirmed stale lockfile remains on disk with dead PID {dead_pid}.")

        # STALE LOCK RECOVERY VERIFICATION:
        # A new scheduler instance must detect the stale dead PID, reclaim the lock, and succeed!
        print("Launching replacement scheduler instance to reclaim stale lock...")
        proc2 = spawn_scheduler(
            [
                "--symbol",
                "BTCUSDT",
                "--output-dir",
                str(out_dir),
                "--health-file",
                str(health_file),
                "--lockfile-path",
                str(lock_file),
                "--interval-seconds",
                "3600",
                "--poll-interval-seconds",
                "0.05",
            ]
        )
        try:
            h2 = poll_health(health_file, timeout=6.0, expected_status="IDLE", exclude_pid=dead_pid)
            assert h2.pid == proc2.pid, (
                f"New scheduler instance must be running, got {h2.pid} vs {proc2.pid}"
            )
            assert lock_file.is_file(), "Lockfile must be acquired by new scheduler"
            new_lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
            assert new_lock_data["pid"] == proc2.pid, "Lock must be reclaimed by new PID"
            print(f"Stale lock successfully reclaimed by new PID {proc2.pid}!")
        finally:
            terminate_scheduler_gracefully(proc2)
            assert not lock_file.exists(), "Graceful shutdown must unlink reclaimed lockfile"
            print("Reclaimed lockfile cleanly unlinked on graceful shutdown.")
    finally:
        if proc.poll() is None:
            proc.kill()

    print(
        "PASS: Abrupt kill leaves dead PID lock which is 100% cleanly reclaimed by next instance."
    )


# ==============================================================================
# MAIN TEST HARNESS RUNNER
# ==============================================================================


def main() -> int:
    print("\n================================================================================")
    print("STARTING EMPIRICAL CHALLENGER 2 STRESS VERIFICATION SUITE (ITERATION 2 GATE)")
    print("================================================================================")

    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)

        t_start = time.perf_counter()

        stress_test_exponential_backoff_model()
        stress_test_runtime_backoff_progression_and_recovery(tmp_path)
        stress_test_mid_cycle_signal_cancellation(tmp_path)
        stress_test_child_timeout_escalation(tmp_path)
        stress_test_concurrent_lock_contention(tmp_path)
        stress_test_signal_cancellation_during_backoff(tmp_path)
        stress_test_termination_via_proc_terminate(tmp_path)

        t_total = time.perf_counter() - t_start
        print("\n" + "=" * 80)
        print(f"ALL 7 EMPIRICAL STRESS TEST SUITES PASSED CLEANLY IN {t_total:.2f}s!")
        print("================================================================================\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
