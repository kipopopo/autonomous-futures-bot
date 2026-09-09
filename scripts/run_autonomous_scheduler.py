"""Autonomous Scheduling & Trigger Daemon.

Periodically evaluates paper trading ledger feedback, orchestrates the bounded
autonomous cycle (scripts/run_autonomous_cycle.py), and hot-publishes qualified
candidate strategies with non-overlapping process locks, failure backoff,
and durable health observability.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import errno
import json
import logging
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

# Ensure src/ is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.domain.contracts import DomainModel  # noqa: E402
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
    read_candidate_registry,
)
from autonomous_futures.paper.feedback_extractor import (  # noqa: E402
    PaperQualificationPolicy,
    extract_paper_feedback,
)

try:
    import pyarrow.parquet as pq

    _PYARROW_AVAILABLE = True
except ImportError:
    _PYARROW_AVAILABLE = False

logger = logging.getLogger("autonomous_futures.scheduler")

_SECRET_PATTERN = re.compile(
    r"(?i)(AIza[0-9A-Za-z\-_]{20,}|ya29\.[0-9A-Za-z\-_]+|bearer\s+[A-Za-z0-9\-._~+/]+=*)"
)


def _sanitize_string(text: str | None) -> str | None:
    """Mask credentials and sensitive authorization tokens in strings."""
    if text is None:
        return None
    return _SECRET_PATTERN.sub("[REDACTED]", text)


FORBIDDEN_CREDENTIAL_FLAGS = (
    "--api-key",
    "--api_key",
    "--key",
    "-key",
    "--apikey",
    "--google-api-key",
    "--google_api_key",
    "--gemini-api-key",
    "--gemini_api_key",
    "--google-ai-studio-api-key",
    "--token",
    "--api-token",
    "-k",
)


def _check_forbidden_credential_flags(argv: Sequence[str]) -> bool:
    """Inspect raw CLI arguments for forbidden credential flags."""
    for arg in argv:
        prefix = arg.lower().split("=")[0].strip()
        if prefix in FORBIDDEN_CREDENTIAL_FLAGS:
            return True
    return False


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


def get_effective_pid() -> int:
    """Return the effective PID for single-instance locking and health reporting.

    On Windows, when launched via a virtual environment launcher shim
    (e.g., .venv\\Scripts\\python.exe), sys.executable launches an intermediate wrapper
    whose PID is returned by subprocess.Popen to callers (such as test runners).
    The actual interpreter running this script is a child of that wrapper.
    If our direct parent (os.getppid()) is this virtualenv launcher executable, we report
    the parent's PID so external supervisors can match the lock/health PID to child handles.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            ppid = os.getppid()
            if ppid > 0:
                h = ctypes.windll.kernel32.OpenProcess(0x1000, False, ppid)
                if h:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                            h, 0, buf, ctypes.byref(size)
                        ):
                            parent_exe = buf.value
                            if parent_exe:
                                is_same = False
                                try:
                                    is_same = os.path.samefile(parent_exe, sys.executable)
                                except Exception:
                                    pass
                                if is_same or (
                                    Path(parent_exe).name.lower() in ("python.exe", "pythonw.exe")
                                    and "\\.venv\\scripts" in parent_exe.lower()
                                ):
                                    return ppid
                    finally:
                        ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            pass
    return os.getpid()


class LockAcquisitionError(RuntimeError):
    """Raised when the single instance execution lock cannot be acquired."""


class SingleInstanceLock:
    """Cross-platform, file-based execution lock with stale PID detection."""

    def __init__(self, lock_path: Path, symbol: str = "") -> None:
        self.lock_path = lock_path.resolve()
        self.symbol = symbol
        self._acquired = False
        self._acquired_pid: int | None = None
        atexit.register(self.release)

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        effective_pid = get_effective_pid()

        for _attempt in range(2):
            try:
                fd = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_RDWR,
                    0o644,
                )
                metadata = {
                    "pid": effective_pid,
                    "started_at": datetime.now(UTC).isoformat(),
                    "hostname": socket.gethostname(),
                    "symbol": self.symbol,
                    "command": " ".join(sys.argv),
                    "lock_version": 1,
                }
                payload = (json.dumps(metadata, indent=2) + "\n").encode("utf-8")
                os.write(fd, payload)
                os.close(fd)
                self._acquired = True
                self._acquired_pid = effective_pid
                logger.info(
                    "Acquired single-instance execution lock at %s (PID %d)",
                    self.lock_path,
                    effective_pid,
                )
                return
            except FileExistsError:
                stale_pid, is_corrupt = self._inspect_existing_lock()
                if is_corrupt:
                    logger.warning(
                        "Found unparseable or corrupt lockfile at %s older than grace period. "
                        "Reclaiming lock.",
                        self.lock_path,
                    )
                    with contextlib.suppress(OSError):
                        self.lock_path.unlink()
                    continue

                if stale_pid is not None and not is_pid_alive(stale_pid):
                    logger.warning(
                        "Detected stale lockfile from dead PID %d at %s. Reclaiming lock.",
                        stale_pid,
                        self.lock_path,
                    )
                    with contextlib.suppress(OSError):
                        self.lock_path.unlink()
                    continue

                # Process is actively running
                err_payload = {
                    "error_code": "lock_acquisition_failed",
                    "message": "Another autonomous scheduler is actively running on this host.",
                    "active_pid": stale_pid,
                    "lockfile": str(self.lock_path),
                }
                print(json.dumps(err_payload, indent=2), file=sys.stderr)
                raise LockAcquisitionError(
                    f"Execution lock already held at {self.lock_path} by active PID {stale_pid}."
                ) from None

        raise LockAcquisitionError(
            f"Failed to acquire execution lock at {self.lock_path} after reclaiming stale lock."
        )

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            stale_pid, _ = self._inspect_existing_lock()
            if stale_pid in (self._acquired_pid, os.getpid(), os.getppid()):
                with contextlib.suppress(OSError):
                    self.lock_path.unlink()
                logger.info("Released single-instance execution lock at %s", self.lock_path)
        except Exception as exc:
            logger.warning("Error releasing lock at %s: %s", self.lock_path, exc)
        finally:
            self._acquired = False

    def _inspect_existing_lock(self) -> tuple[int | None, bool]:
        if not self.lock_path.exists():
            return None, True
        try:
            raw = self.lock_path.read_text(encoding="utf-8").strip()
            if not raw:
                mtime = os.path.getmtime(self.lock_path)
                return (None, True) if (time.time() - mtime) > 10.0 else (None, False)
            if raw.startswith("{"):
                data = json.loads(raw)
                pid = int(data.get("pid", -1))
                return pid, False
            pid = int(raw)
            return pid, False
        except Exception:
            mtime = os.path.getmtime(self.lock_path)
            return (None, True) if (time.time() - mtime) > 10.0 else (None, False)

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.release()


# Telemetry Schema

SchedulerStatus = Literal["IDLE", "RUNNING_CYCLE", "BACKOFF", "STOPPED"]
TriggerType = Literal["interval", "breach", "manual_once"]


class LastCycleResult(DomainModel):
    """Execution telemetry schema from the most recently executed autonomous cycle."""

    cycle_id: str | None = Field(default=None, description="Unique cycle execution identifier")
    trigger_type: TriggerType = Field(description="Cause of cycle trigger")
    status: str = Field(
        description=(
            "Result status string: completed_admitted, completed_rejected, "
            "completed_unadmitted, stopped, failed, timeout"
        )
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
    pid: int | None = Field(
        default=None, description="OS process ID of the daemon; null when stopped"
    )
    started_at: str = Field(description="ISO-8601 UTC timestamp when scheduler started")
    updated_at: str = Field(description="ISO-8601 UTC timestamp of latest telemetry update")
    last_run_at: str | None = Field(
        default=None, description="ISO-8601 UTC timestamp when last cycle started"
    )
    next_run_at: str | None = Field(
        default=None, description="ISO-8601 UTC timestamp for next scheduled cycle"
    )
    consecutive_failures: int = Field(
        default=0, ge=0, description="Count of consecutive cycle failures"
    )
    total_cycles_executed: int = Field(default=0, ge=0, description="Total cycle runs attempted")
    admitted_candidates_count: int = Field(
        default=0, ge=0, description="Total candidates admitted into paper pool"
    )
    last_cycle_result: LastCycleResult | None = Field(
        default=None, description="Result of most recent cycle"
    )
    symbol: str = Field(description="Target market symbol")
    lockfile: str = Field(description="Absolute or relative path to active process lockfile")
    mode: Literal["daemon", "once"] = Field(default="daemon", description="Execution mode")


def emit_scheduler_health(output_path: Path, payload: SchedulerHealthCheckpoint) -> None:
    """Atomically persist scheduler-health.json with Windows retry handling."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.model_dump_json(indent=2)
    temp_path = output_path.with_name(f".{output_path.name}.{os.getpid()}_{time.time_ns()}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(data + "\n")
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(10):
            try:
                temp_path.replace(output_path)
                break
            except PermissionError, OSError:
                if attempt < 9:
                    time.sleep(0.015)
                else:
                    raise
    finally:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()


def calculate_backoff_delay(
    consecutive_failures: int,
    base_backoff_seconds: float,
    backoff_factor: float,
    max_backoff_seconds: float,
) -> float:
    """Calculate binary exponential backoff delay: min(max, base * factor^(failures - 1))."""
    if consecutive_failures <= 0:
        return 0.0
    exponent = consecutive_failures - 1
    delay = base_backoff_seconds * (backoff_factor**exponent)
    return min(max_backoff_seconds, delay)


class MarketDataFreshnessMonitor:
    """Monitors canonical 5m Parquet data freshness."""

    def __init__(self, parquet_path: Path) -> None:
        self.parquet_path = parquet_path
        self.last_evaluated_mtime: float = 0.0
        self.last_evaluated_bar_time: datetime | None = None

    def check_freshness(self) -> tuple[bool, str]:
        """Check if fresh market data is available since last evaluated cycle."""
        if not self.parquet_path.is_file():
            return False, "parquet_file_not_found"

        try:
            stat = os.stat(self.parquet_path)
        except OSError:
            return False, "parquet_stat_error"

        current_mtime = stat.st_mtime

        # Initial run: file exists and has data
        if self.last_evaluated_mtime == 0.0:
            return (stat.st_size > 0), (
                "initial_fresh_data" if stat.st_size > 0 else "parquet_file_empty"
            )

        # Check mtime
        if current_mtime <= self.last_evaluated_mtime:
            return False, "mtime_unchanged"

        # Check PyArrow last row group timestamp if available
        if _PYARROW_AVAILABLE:
            try:
                pf = pq.ParquetFile(self.parquet_path)
                if pf.num_row_groups > 0:
                    last_rg = pf.read_row_group(pf.num_row_groups - 1, columns=["timestamp"])
                    last_ts = last_rg.column("timestamp")[-1].as_py()
                    if isinstance(last_ts, datetime):
                        last_ts_utc = last_ts if last_ts.tzinfo else last_ts.replace(tzinfo=UTC)
                        if (
                            self.last_evaluated_bar_time
                            and last_ts_utc <= self.last_evaluated_bar_time
                        ):
                            return False, "bar_timestamp_unchanged"
            except Exception as exc:
                logger.debug("PyArrow check failed, falling back to mtime (%s)", exc)

        return True, "fresh_bars_detected"

    def mark_evaluated(self) -> None:
        """Update freshness watermark after successful cycle launch/completion."""
        if self.parquet_path.is_file():
            try:
                self.last_evaluated_mtime = os.stat(self.parquet_path).st_mtime
            except OSError:
                pass

            if _PYARROW_AVAILABLE:
                try:
                    pf = pq.ParquetFile(self.parquet_path)
                    if pf.num_row_groups > 0:
                        last_rg = pf.read_row_group(pf.num_row_groups - 1, columns=["timestamp"])
                        last_ts = last_rg.column("timestamp")[-1].as_py()
                        if isinstance(last_ts, datetime):
                            self.last_evaluated_bar_time = (
                                last_ts if last_ts.tzinfo else last_ts.replace(tzinfo=UTC)
                            )
                except Exception:
                    pass


def check_new_closed_trades(
    ledger_db_path: Path,
    symbol: str,
    last_evaluated_seq: int,
) -> tuple[bool, int, int]:
    """Probe paper-ledger.sqlite3 for new closed trades."""
    if not ledger_db_path.is_file():
        return False, last_evaluated_seq, 0
    uri = f"file:{ledger_db_path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
            conn.execute("PRAGMA query_only = ON;")
            conn.execute("PRAGMA busy_timeout = 1000;")
            cur = conn.execute(
                "SELECT MAX(sequence), COUNT(*) FROM paper_ledger_events "
                "WHERE event = 'close' AND symbol = ?",
                (symbol,),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return False, last_evaluated_seq, 0
            max_seq = int(row[0])
            count = int(row[1])
            has_new = max_seq > last_evaluated_seq
            return has_new, max_seq, count
    except sqlite3.Error as exc:
        logger.debug("SQLite closed trade probe error: %s", exc)
        return False, last_evaluated_seq, 0


def evaluate_ledger_breach(
    *,
    ledger_db: Path,
    lifecycle_db: Path | None,
    symbol: str,
    candidate_id: str | None,
    candidate_path: Path | None,
    candidate_registry_path: Path | None,
    policy: PaperQualificationPolicy,
    bundle_hash: str | None,
    dataset_registry_hash: str | None,
    closed_trades_count: int,
) -> bool:
    """Evaluate closed trades for performance breach.

    Returns True ONLY if closed_trades_count > 0 and at least one
    performance gate (PnL, profit factor, win rate, drawdown) fails.
    """
    if closed_trades_count <= 0:
        return False

    active_candidate_id = candidate_id
    active_candidate_path = candidate_path
    if candidate_registry_path and candidate_registry_path.is_file():
        try:
            manifest = read_candidate_registry(candidate_registry_path, verify_hash=False)
            if symbol in manifest.symbols:
                entry = manifest.symbols[symbol]
                if not active_candidate_id:
                    active_candidate_id = entry.candidate_id
                if (
                    not active_candidate_path
                    and entry.artifact_path
                    and Path(entry.artifact_path).is_file()
                ):
                    active_candidate_path = Path(entry.artifact_path).resolve()
        except Exception as exc:
            logger.debug("Could not read candidate registry: %s", exc)

    if not active_candidate_path and active_candidate_id:
        search_dirs: list[Path] = [
            ledger_db.parent / "candidates",
            ledger_db.parent,
            Path("artifacts/research/phase252/candidates"),
            Path("artifacts/research/phase249/candidates"),
        ]
        for sdir in search_dirs:
            if sdir.is_dir():
                cf = sdir / f"{active_candidate_id}.json"
                if cf.is_file():
                    active_candidate_path = cf.resolve()
                    break

    try:
        feedback = extract_paper_feedback(
            ledger_path=ledger_db,
            lifecycle_path=lifecycle_db,
            symbol=symbol,
            candidate_id=active_candidate_id,
            candidate_artifact_path=active_candidate_path,
            policy=policy,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
        )
    except Exception as exc:
        logger.warning("Error evaluating paper feedback: %s", exc)
        return False

    if feedback is None:
        return False

    # A genuine performance breach requires failure of at least one performance gate
    # (i.e. not solely the sample size threshold paper_trades_min)
    return any(g.gate_id != "paper_trades_min" for g in feedback.failed_gates)


def _terminate_process(proc: subprocess.Popen[str], timeout: float = 5.0) -> None:
    """Safely terminate child process with escalation from terminate to kill."""
    if proc.poll() is not None:
        return
    logger.info("Sending terminate signal to child process PID %d...", proc.pid)
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning(
            "Child process PID %d did not terminate gracefully; sending kill...",
            proc.pid,
        )
        try:
            proc.kill()
            proc.wait(timeout=2.0)
        except Exception as exc:
            logger.warning("Error killing child process PID %d: %s", proc.pid, exc)
    except Exception as exc:
        logger.warning("Error terminating child process PID %d: %s", proc.pid, exc)


class AutonomousSchedulerDaemon:
    """Coordinates periodic and breach-triggered autonomous strategy revision cycles."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.symbol: str = args.symbol
        self.output_dir: Path = Path(args.output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.health_path: Path = (
            Path(args.health_file).resolve()
            if args.health_file
            else self.output_dir / "scheduler-health.json"
        )

        self.lock_path: Path = (
            Path(args.lockfile_path).resolve()
            if args.lockfile_path
            else self.output_dir / "scheduler.lock"
        )

        ledger_p = Path(args.ledger_db).resolve()
        self.ledger_db: Path = ledger_p / "paper-ledger.sqlite3" if ledger_p.is_dir() else ledger_p

        if args.lifecycle_db:
            lifecycle_p = Path(args.lifecycle_db).resolve()
            self.lifecycle_db: Path | None = (
                lifecycle_p / "paper-lifecycle.sqlite3" if lifecycle_p.is_dir() else lifecycle_p
            )
        elif (self.ledger_db.parent / "paper-lifecycle.sqlite3").is_file():
            self.lifecycle_db = self.ledger_db.parent / "paper-lifecycle.sqlite3"
        else:
            self.lifecycle_db = None

        if args.parquet_path:
            self.parquet_path: Path = Path(args.parquet_path).resolve()
        else:
            self.parquet_path = Path(
                f"research/immutable-data/5m/canonical/{self.symbol}-5m.parquet"
            ).resolve()

        if args.candidate_registry_path:
            self.candidate_registry_path: Path = Path(args.candidate_registry_path).resolve()
        elif self.ledger_db.parent.is_dir():
            self.candidate_registry_path = (
                self.ledger_db.parent / "candidate_registry.json"
            ).resolve()
        else:
            self.candidate_registry_path = DEFAULT_CANDIDATE_REGISTRY_PATH.resolve()

        self.interval_seconds: float = float(args.interval_seconds)
        self.min_cooldown_seconds: float = float(args.min_cooldown_seconds)
        self.base_backoff_seconds: float = float(args.base_backoff_seconds)
        self.max_backoff_seconds: float = float(args.max_backoff_seconds)
        self.backoff_factor: float = float(args.backoff_factor)
        self.cycle_timeout_seconds: float = float(args.cycle_timeout_seconds)
        self.poll_interval_seconds: float = float(args.poll_interval_seconds)
        self.check_breach_interval_seconds: float = float(args.check_breach_interval_seconds)
        self.mode: Literal["daemon", "once"] = "once" if args.once else "daemon"

        self.policy = PaperQualificationPolicy(
            policy_id=args.policy_id,
            paper_net_pnl_min=args.paper_net_pnl_min,
            paper_profit_factor_min=args.paper_profit_factor_min,
            paper_win_rate_min=args.paper_win_rate_min,
            paper_drawdown_max=args.paper_drawdown_max,
            paper_trades_min=args.paper_trades_min,
        )

        self.freshness_monitor = MarketDataFreshnessMonitor(self.parquet_path)
        self.lock = SingleInstanceLock(self.lock_path, symbol=self.symbol)

        # State tracking
        self.started_at: datetime = datetime.now(UTC)
        self.status: SchedulerStatus = "IDLE"
        self.consecutive_failures: int = 0
        self.total_cycles_executed: int = 0
        self.admitted_candidates_count: int = 0
        self.last_run_at: str | None = None
        self.next_run_at: datetime | None = None
        self.cooldown_until: datetime | None = None
        self.backoff_until: datetime | None = None
        self.last_cycle_result: LastCycleResult | None = None

        self.last_evaluated_seq: int = 0
        self.pending_breach: bool = False
        self.last_breach_check_time: float = 0.0

        self.stop_event = threading.Event()
        self.active_process: subprocess.Popen[str] | None = None
        self._win_handler_ref: Any = None

    def _setup_signal_handlers(self) -> None:
        def _signal_handler(signame: str) -> None:
            logger.info("Received signal %s; triggering graceful shutdown...", signame)
            self.stop_event.set()
            if self.active_process is not None:
                _terminate_process(self.active_process, timeout=5.0)

        def _make_handler(sig_num: int) -> Any:
            def _handler(signum: int, frame: Any) -> None:
                _signal_handler(str(sig_num))

            return _handler

        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(ValueError, AttributeError):
                    signal.signal(sig, _make_handler(sig))
        else:
            for sig in (signal.SIGINT, getattr(signal, "SIGBREAK", signal.SIGINT)):
                with contextlib.suppress(ValueError, AttributeError):
                    signal.signal(sig, _make_handler(sig))

            try:
                import ctypes
                from ctypes import wintypes

                phandler_routine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

                def _win_handler(ctrl_type: int) -> bool:
                    _signal_handler(f"WIN_CTRL_{ctrl_type}")
                    return True

                self._win_handler_ref = phandler_routine(_win_handler)
                ctypes.windll.kernel32.SetConsoleCtrlHandler(self._win_handler_ref, True)
            except Exception as exc:
                logger.debug("Could not register Win32 console control handler: %s", exc)

    def emit_health(self) -> None:
        now_iso = datetime.now(UTC).isoformat()
        next_run_iso = self.next_run_at.isoformat() if self.next_run_at is not None else None
        current_pid = get_effective_pid() if self.status != "STOPPED" else None

        checkpoint = SchedulerHealthCheckpoint(
            status=self.status,
            pid=current_pid,
            started_at=self.started_at.isoformat(),
            updated_at=now_iso,
            last_run_at=self.last_run_at,
            next_run_at=next_run_iso,
            consecutive_failures=self.consecutive_failures,
            total_cycles_executed=self.total_cycles_executed,
            admitted_candidates_count=self.admitted_candidates_count,
            last_cycle_result=self.last_cycle_result,
            symbol=self.symbol,
            lockfile=str(self.lock_path),
            mode=self.mode,
        )
        emit_scheduler_health(self.health_path, checkpoint)

    def _execute_cycle(self, trigger_type: TriggerType) -> int:
        now = datetime.now(UTC)
        self.last_run_at = now.isoformat()
        self.status = "RUNNING_CYCLE"
        self.emit_health()

        cycle_id = f"cycle-{self.symbol.lower()}-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
        cycle_output_dir = self.output_dir / "cycles" / cycle_id
        cycle_output_dir.mkdir(parents=True, exist_ok=True)

        cycle_script = Path(__file__).resolve().parent / "run_autonomous_cycle.py"

        # 1. Resolve candidate ID and candidate artifact path
        resolved_cid: str | None = getattr(self.args, "candidate_id", None)
        resolved_cpath: Path | None = (
            Path(self.args.candidate_path).resolve()
            if getattr(self.args, "candidate_path", None)
            else None
        )

        # Check candidate registry if not explicitly provided
        if self.candidate_registry_path and self.candidate_registry_path.is_file():
            try:
                manifest = read_candidate_registry(self.candidate_registry_path, verify_hash=False)
                if self.symbol in manifest.symbols:
                    entry = manifest.symbols[self.symbol]
                    if resolved_cid is None:
                        resolved_cid = entry.candidate_id
                    if (
                        resolved_cpath is None
                        and entry.artifact_path
                        and Path(entry.artifact_path).is_file()
                    ):
                        resolved_cpath = Path(entry.artifact_path).resolve()
            except Exception as exc:
                logger.debug("Could not resolve candidate from registry: %s", exc)

        # Check paper ledger DB for candidate if still missing
        if resolved_cid is None and self.ledger_db and self.ledger_db.is_file():
            try:
                with sqlite3.connect(self.ledger_db) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT candidate_id, candidate_artifact_hash FROM paper_ledger_events "
                        "WHERE symbol = ? ORDER BY sequence DESC LIMIT 1;",
                        (self.symbol,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        cursor.execute(
                            "SELECT candidate_id, candidate_artifact_hash FROM paper_ledger_events "
                            "ORDER BY sequence DESC LIMIT 1;"
                        )
                        row = cursor.fetchone()
                    if row:
                        resolved_cid = str(row[0])
            except Exception as exc:
                logger.debug("Could not query candidate from ledger DB: %s", exc)

        # Search known candidate directories if resolved_cpath is still missing
        search_dirs: list[Path] = [
            self.output_dir.parent / "candidates",
            self.output_dir / "candidates",
            self.ledger_db.parent / "candidates" if self.ledger_db else Path("."),
            _REPO_ROOT / "artifacts" / "research" / "phase252" / "candidates",
            _REPO_ROOT / "artifacts" / "research" / "phase249" / "candidates",
        ]

        if resolved_cpath is None and resolved_cid:
            for sdir in search_dirs:
                if sdir.is_dir():
                    cand_file = sdir / f"{resolved_cid}.json"
                    if cand_file.is_file():
                        resolved_cpath = cand_file.resolve()
                        break

        if resolved_cpath is None:
            # Fallback: search for any candidate JSON matching symbol in known search dirs
            for sdir in search_dirs:
                if sdir.is_dir():
                    for jf in sdir.glob("*.json"):
                        try:
                            c_data = json.loads(jf.read_text(encoding="utf-8"))
                            symbols = (
                                c_data.get("strategy", {}).get("universe", {}).get("symbols", [])
                            )
                            if self.symbol in symbols:
                                resolved_cpath = jf.resolve()
                                if resolved_cid is None:
                                    resolved_cid = c_data.get("candidate_id")
                                break
                        except Exception:
                            continue
                if resolved_cpath is not None:
                    break

        # Extract paper feedback if ledger DB is present
        extracted_feedback = None
        feedback_file: Path | None = None
        if self.ledger_db and self.ledger_db.is_file():
            try:
                extracted_feedback = extract_paper_feedback(
                    ledger_path=self.ledger_db,
                    lifecycle_path=self.lifecycle_db
                    if self.lifecycle_db and self.lifecycle_db.is_file()
                    else None,
                    symbol=self.symbol,
                    candidate_id=resolved_cid,
                    candidate_artifact_path=resolved_cpath,
                    policy=self.policy,
                    bundle_hash=getattr(self.args, "bundle_hash", None),
                    dataset_registry_hash=getattr(self.args, "dataset_registry_hash", None),
                )
                if extracted_feedback is not None:
                    feedback_file = cycle_output_dir / "paper-feedback.json"
                    feedback_file.write_text(
                        extracted_feedback.model_dump_json(indent=2) + "\n",
                        encoding="utf-8",
                    )
            except Exception as exc:
                logger.debug("Could not extract paper feedback: %s", exc)

        cmd: list[str] = [
            sys.executable,
            str(cycle_script),
            "--symbol",
            self.symbol,
            "--output-dir",
            str(cycle_output_dir),
            "--cycle-id",
            cycle_id,
            "--provider",
            self.args.provider,
            "--model",
            self.args.model,
            "--temperature",
            str(self.args.temperature),
        ]

        if feedback_file is not None and feedback_file.is_file():
            cmd.extend(["--feedback-path", str(feedback_file)])
        elif self.ledger_db.exists():
            cmd.extend(["--ledger-db", str(self.ledger_db)])

        if self.lifecycle_db and self.lifecycle_db.exists():
            cmd.extend(["--lifecycle-db", str(self.lifecycle_db)])
        if self.parquet_path.exists():
            cmd.extend(["--parquet-path", str(self.parquet_path)])
        if self.candidate_registry_path:
            cmd.extend(["--candidate-registry-path", str(self.candidate_registry_path)])
        if resolved_cid:
            cmd.extend(["--candidate-id", str(resolved_cid)])
        if resolved_cpath and resolved_cpath.is_file():
            cmd.extend(["--candidate-path", str(resolved_cpath)])
        if getattr(self.args, "require_flat", False):
            cmd.append("--require-flat")
        if getattr(self.args, "bundle_hash", None):
            cmd.extend(["--bundle-hash", str(self.args.bundle_hash)])
        if getattr(self.args, "dataset_registry_hash", None):
            cmd.extend(["--dataset-registry-hash", str(self.args.dataset_registry_hash)])

        # Forward policy options with dynamic slice adaptation for short evaluation datasets
        windows_count = self.args.windows_count
        bars_per_window = self.args.bars_per_window
        min_trades = self.args.min_trades

        if self.parquet_path.exists() and _PYARROW_AVAILABLE:
            try:
                parquet_meta = pq.ParquetFile(str(self.parquet_path)).metadata
                total_rows = parquet_meta.num_rows
                if total_rows > 0 and total_rows < windows_count * bars_per_window:
                    bars_per_window = max(20, min(total_rows, 288))
                    windows_count = max(1, min(windows_count, total_rows // bars_per_window))
                    logger.info(
                        "Adapted cycle evaluation parameters to available parquet rows (%d): "
                        "windows_count=%d, bars_per_window=%d",
                        total_rows,
                        windows_count,
                        bars_per_window,
                    )
            except Exception as exc:
                logger.debug("Failed checking parquet row count: %s", exc)

        cmd.extend(
            [
                "--windows-count",
                str(windows_count),
                "--bars-per-window",
                str(bars_per_window),
                "--min-profit-factor",
                str(self.args.min_profit_factor),
                "--max-drawdown-pct",
                str(self.args.max_drawdown_pct),
                "--min-average-return-pct",
                str(self.args.min_average_return_pct),
                "--min-trades",
                str(min_trades),
                "--min-windows",
                str(self.args.min_windows),
                "--policy-id",
                str(self.args.policy_id),
                "--paper-net-pnl-min",
                str(self.args.paper_net_pnl_min),
                "--paper-profit-factor-min",
                str(self.args.paper_profit_factor_min),
                "--paper-win-rate-min",
                str(self.args.paper_win_rate_min),
                "--paper-drawdown-max",
                str(self.args.paper_drawdown_max),
                "--paper-trades-min",
                str(self.args.paper_trades_min),
            ]
        )

        logger.info(
            "Launching autonomous cycle %s for %s (trigger: %s)",
            cycle_id,
            self.symbol,
            trigger_type,
        )
        start_monotonic = time.monotonic()
        timed_out = False

        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creation_flags,
        )
        self.active_process = proc

        deadline = start_monotonic + self.cycle_timeout_seconds
        last_tick = time.monotonic()

        try:
            while proc.poll() is None:
                if self.stop_event.is_set():
                    logger.info(
                        "Stop event detected; terminating child cycle PID %d",
                        proc.pid,
                    )
                    _terminate_process(proc, timeout=5.0)
                    break

                now_mono = time.monotonic()
                if now_mono >= deadline:
                    logger.warning(
                        "Child cycle process PID %d exceeded timeout of %.1fs; killing.",
                        proc.pid,
                        self.cycle_timeout_seconds,
                    )
                    timed_out = True
                    _terminate_process(proc, timeout=5.0)
                    break

                if now_mono - last_tick >= self.poll_interval_seconds:
                    self.emit_health()
                    last_tick = now_mono

                time.sleep(0.05)

            stdout, stderr = proc.communicate()
        finally:
            self.active_process = None

        elapsed_seconds = round(time.monotonic() - start_monotonic, 2)
        self.total_cycles_executed += 1

        error_msg: str | None = None
        if timed_out:
            exit_code = 124
            status = "timeout"
            error_msg = f"Cycle exceeded timeout of {self.cycle_timeout_seconds}s"
        elif self.stop_event.is_set():
            exit_code = proc.returncode if proc.returncode is not None else 1
            status = "stopped"
            error_msg = "Daemon shutdown during cycle execution"
        else:
            exit_code = proc.returncode

        admitted = False
        candidate_id: str | None = None

        if exit_code == 0:
            result_file = cycle_output_dir / "autonomous-cycle-result.json"
            audit_file = cycle_output_dir / "cycle-audit.json"
            for _ in range(5):
                if result_file.is_file() or audit_file.is_file():
                    break
                time.sleep(0.05)

            if result_file.is_file():
                try:
                    result_data = json.loads(result_file.read_text(encoding="utf-8"))
                    status = result_data.get("cycle_status", "completed")
                    candidate_id = result_data.get("candidate_id")
                    admitted = (
                        result_data.get("admission_decision") == "admitted"
                        or result_data.get("cycle_status") == "completed_admitted"
                    )
                except Exception as exc:
                    logger.warning("Could not parse cycle result file: %s", exc)
                    status = "completed"
            elif audit_file.is_file():
                try:
                    audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
                    status = audit_data.get("cycle_status", "completed")
                    lineage = audit_data.get("lineage", {})
                    candidate_id = lineage.get("candidate_id")
                    admitted = lineage.get("admission_decision") == "admitted"
                except Exception as exc:
                    logger.warning("Could not parse cycle audit file: %s", exc)
                    status = "completed"
            else:
                status = "completed"

            if admitted:
                self.admitted_candidates_count += 1

            self.consecutive_failures = 0
            self.backoff_until = None
            self.status = "IDLE"
            self.freshness_monitor.mark_evaluated()
        else:
            if not timed_out and not self.stop_event.is_set():
                status = "failed"
                raw_err = stderr.strip() or stdout.strip()
                if raw_err:
                    try:
                        err_json = json.loads(raw_err)
                        error_msg = err_json.get("message", raw_err[:200])
                    except Exception:
                        error_msg = raw_err[:200]
                else:
                    error_msg = f"Process exited with code {exit_code}"

            self.consecutive_failures += 1
            backoff_delay = calculate_backoff_delay(
                self.consecutive_failures,
                self.base_backoff_seconds,
                self.backoff_factor,
                self.max_backoff_seconds,
            )
            self.backoff_until = datetime.now(UTC) + timedelta(seconds=backoff_delay)
            self.status = "BACKOFF"
            logger.warning(
                "Cycle failed (exit %d); entering backoff for %.1fs (failure #%d)",
                exit_code,
                backoff_delay,
                self.consecutive_failures,
            )

        completed_now = datetime.now(UTC)
        self.cooldown_until = completed_now + timedelta(seconds=self.min_cooldown_seconds)

        if self.status == "BACKOFF" and self.backoff_until:
            self.next_run_at = max(self.backoff_until, self.cooldown_until)
        else:
            interval_run = completed_now + timedelta(seconds=self.interval_seconds)
            self.next_run_at = max(interval_run, self.cooldown_until)

        self.last_cycle_result = LastCycleResult(
            cycle_id=cycle_id,
            trigger_type=trigger_type,
            status=status,
            exit_code=exit_code,
            candidate_id=candidate_id,
            admitted=admitted,
            executed_at=now.isoformat(),
            duration_seconds=elapsed_seconds,
            error_message=_sanitize_string(error_msg),
        )

        self.emit_health()
        return exit_code

    def _is_status(self, target: SchedulerStatus) -> bool:
        return self.status == target

    def run(self) -> int:
        self._setup_signal_handlers()

        with self.lock:
            logger.info("Autonomous scheduler started for %s", self.symbol)

            # In --once mode, execute single pass immediately and terminate
            if self.mode == "once":
                self.status = "IDLE"
                self.emit_health()
                exit_code = self._execute_cycle("manual_once")
                self.status = "STOPPED"
                self.next_run_at = None
                self.emit_health()
                return exit_code

            # Daemon mode initialization
            self.status = "IDLE"
            self.next_run_at = self.started_at + timedelta(seconds=self.interval_seconds)
            self.emit_health()

            effective_breach_interval = min(
                self.poll_interval_seconds, self.check_breach_interval_seconds
            )

            while not self.stop_event.is_set():
                now = datetime.now(UTC)
                mono_now = time.monotonic()

                # Check backoff expiry
                if self._is_status("BACKOFF") and self.backoff_until:
                    if now >= self.backoff_until:
                        logger.info("Backoff period elapsed; returning to IDLE state.")
                        self.status = "IDLE"
                        self.backoff_until = None
                        self.emit_health()

                # Fast SQLite closed trades probe
                if self._is_status("IDLE") and (
                    (mono_now - self.last_breach_check_time) >= effective_breach_interval
                ):
                    self.last_breach_check_time = mono_now
                    has_new, max_seq, count = check_new_closed_trades(
                        self.ledger_db, self.symbol, self.last_evaluated_seq
                    )
                    if has_new:
                        is_breached = evaluate_ledger_breach(
                            ledger_db=self.ledger_db,
                            lifecycle_db=self.lifecycle_db,
                            symbol=self.symbol,
                            candidate_id=getattr(self.args, "candidate_id", None),
                            candidate_path=getattr(self.args, "candidate_path", None),
                            candidate_registry_path=self.candidate_registry_path,
                            policy=self.policy,
                            bundle_hash=getattr(self.args, "bundle_hash", None),
                            dataset_registry_hash=getattr(self.args, "dataset_registry_hash", None),
                            closed_trades_count=count,
                        )
                        if is_breached:
                            logger.info(
                                "Detected qualification policy breach on %s (sequence %d)",
                                self.symbol,
                                max_seq,
                            )
                            self.pending_breach = True
                        self.last_evaluated_seq = max_seq

                # Evaluate triggers if not in cooldown or backoff
                in_cooldown = self.cooldown_until is not None and now < self.cooldown_until
                in_backoff = (
                    self._is_status("BACKOFF")
                    and self.backoff_until is not None
                    and now < self.backoff_until
                )

                if not in_cooldown and not in_backoff and self._is_status("IDLE"):
                    # Breach trigger has priority
                    if self.pending_breach:
                        logger.info(
                            "Firing early evaluation cycle due to ledger breach on %s",
                            self.symbol,
                        )
                        self.pending_breach = False
                        self._execute_cycle("breach")
                        continue

                    # Scheduled interval trigger
                    if self.next_run_at is not None and now >= self.next_run_at:
                        is_fresh, reason = self.freshness_monitor.check_freshness()
                        if is_fresh:
                            logger.info(
                                "Firing scheduled interval cycle for %s (fresh data: %s)",
                                self.symbol,
                                reason,
                            )
                            self._execute_cycle("interval")
                            continue
                        else:
                            logger.debug(
                                "Postponing interval cycle for %s; market data not fresh (%s)",
                                self.symbol,
                                reason,
                            )

                self.emit_health()

                sleep_end = time.monotonic() + self.poll_interval_seconds
                while time.monotonic() < sleep_end and not self.stop_event.is_set():
                    time.sleep(0.05)

            self.status = "STOPPED"
            self.next_run_at = None
            self.emit_health()
            logger.info("Autonomous scheduler stopped cleanly.")
            return 0


def _validate_symbol(value: str) -> str:
    raw = value.strip()
    if not re.match(r"^[A-Z0-9]+$", raw):
        raise argparse.ArgumentTypeError(
            f"Invalid symbol '{value}'. Must be uppercase alphanumeric (e.g. 'BTCUSDT')."
        )
    return raw


def _validate_positive_int(value: str) -> int:
    try:
        ival = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid integer: '{value}'") from exc
    if ival <= 0:
        raise argparse.ArgumentTypeError(f"Must be greater than 0: {ival}")
    return ival


def _validate_non_negative_float(value: str) -> float:
    try:
        fval = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid float: '{value}'") from exc
    if fval < 0.0:
        raise argparse.ArgumentTypeError(f"Must be non-negative: {fval}")
    return fval


def _validate_positive_float(value: str) -> float:
    try:
        fval = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid float: '{value}'") from exc
    if fval <= 0.0:
        raise argparse.ArgumentTypeError(f"Must be greater than 0: {fval}")
    return fval


def _validate_temperature(value: str) -> float:
    try:
        fval = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid temperature: '{value}'") from exc
    if not (0.0 <= fval <= 2.0):
        raise argparse.ArgumentTypeError(f"Temperature must be between 0.0 and 2.0: {fval}")
    return fval


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for autonomous scheduler daemon."""
    parser = argparse.ArgumentParser(
        description="Autonomous Scheduling & Trigger Daemon for paper futures trading."
    )
    # Required target symbol
    parser.add_argument(
        "--symbol",
        type=_validate_symbol,
        required=True,
        help="Target market symbol (e.g. BTCUSDT).",
    )
    # Timing and intervals
    parser.add_argument(
        "--interval-seconds",
        type=_validate_positive_int,
        default=3600,
        help="Scheduled evaluation period in seconds (default: 3600).",
    )
    parser.add_argument(
        "--min-cooldown-seconds",
        type=_validate_non_negative_float,
        default=300.0,
        help="Minimum elapsed seconds between consecutive cycles (default: 300.0).",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=_validate_positive_float,
        default=5.0,
        help="Event loop sleep granularity in seconds (default: 5.0).",
    )
    parser.add_argument(
        "--check-breach-interval-seconds",
        type=_validate_positive_float,
        default=30.0,
        help="Periodic SQLite ledger breach inspection frequency (default: 30.0).",
    )
    # Backoff and timeout
    parser.add_argument(
        "--base-backoff-seconds",
        type=_validate_positive_float,
        default=60.0,
        help="Base exponential backoff delay in seconds (default: 60.0).",
    )
    parser.add_argument(
        "--max-backoff-seconds",
        type=_validate_positive_float,
        default=3600.0,
        help="Maximum backoff ceiling in seconds (default: 3600.0).",
    )
    parser.add_argument(
        "--backoff-factor",
        type=_validate_positive_float,
        default=2.0,
        help="Exponential backoff multiplier (default: 2.0).",
    )
    parser.add_argument(
        "--cycle-timeout-seconds",
        type=_validate_positive_float,
        default=600.0,
        help="Child cycle process timeout in seconds (default: 600.0).",
    )
    # Provider options
    parser.add_argument(
        "--provider",
        choices=["demo", "google_ai_studio"],
        default="demo",
        help="Strategy proposal transport provider (default: demo).",
    )
    parser.add_argument(
        "--model",
        choices=["gemma-4-31b-it", "gemma-4-26b-a4b-it"],
        default="gemma-4-31b-it",
        help="Gemma model ID for google_ai_studio provider.",
    )
    parser.add_argument(
        "--temperature",
        type=_validate_temperature,
        default=0.2,
        help="LLM sampling temperature between 0.0 and 2.0 (default: 0.2).",
    )
    # Execution mode
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run single evaluation pass and exit immediately.",
    )
    # Storage and paths
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/paper_live/scheduler"),
        help="Output directory for logs, health telemetry, and locks.",
    )
    parser.add_argument(
        "--health-file",
        type=Path,
        default=None,
        help="Explicit path for scheduler-health.json.",
    )
    parser.add_argument(
        "--lockfile-path",
        type=Path,
        default=None,
        help="Explicit path for single-instance scheduler.lock.",
    )
    parser.add_argument(
        "--ledger-db",
        type=Path,
        default=Path("artifacts/paper_live/paper-ledger.sqlite3"),
        help="Path to paper ledger SQLite database.",
    )
    parser.add_argument(
        "--lifecycle-db",
        type=Path,
        default=None,
        help="Optional path to paper lifecycle SQLite database.",
    )
    parser.add_argument(
        "--parquet-path",
        type=Path,
        default=None,
        help="Canonical 5m Parquet data path.",
    )
    parser.add_argument(
        "--candidate-registry-path",
        type=Path,
        default=None,
        help="Explicit path to candidate_registry.json manifest.",
    )
    # Logging
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level verbosity.",
    )

    # Forwarded cycle policy parameters
    parser.add_argument("--windows-count", type=int, default=3)
    parser.add_argument("--bars-per-window", type=int, default=288)
    parser.add_argument("--min-profit-factor", type=Decimal, default=Decimal("1.05"))
    parser.add_argument("--max-drawdown-pct", type=Decimal, default=Decimal("15.0"))
    parser.add_argument("--min-average-return-pct", type=Decimal, default=Decimal("0.0"))
    parser.add_argument("--min-trades", type=int, default=5)
    parser.add_argument("--min-windows", type=int, default=1)
    parser.add_argument("--policy-id", type=str, default="policy-autonomous-cycle-v1")
    parser.add_argument("--paper-net-pnl-min", type=Decimal, default=Decimal("0.00"))
    parser.add_argument("--paper-profit-factor-min", type=Decimal, default=Decimal("1.05"))
    parser.add_argument("--paper-win-rate-min", type=Decimal, default=Decimal("45.00"))
    parser.add_argument("--paper-drawdown-max", type=Decimal, default=Decimal("15.00"))
    parser.add_argument("--paper-trades-min", type=int, default=5)
    parser.add_argument("--require-flat", action="store_true", default=False)
    parser.add_argument("--bundle-hash", type=str, default=None)
    parser.add_argument("--dataset-registry-hash", type=str, default=None)
    parser.add_argument("--candidate-id", type=str, default=None)
    parser.add_argument("--candidate-path", type=Path, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI runner entry point for autonomous scheduler daemon."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if _check_forbidden_credential_flags(raw_argv):
        print(
            json.dumps(
                {
                    "error_code": "forbidden_cli_argument",
                    "message": (
                        "Passing API keys or credentials via CLI flags is forbidden. "
                        "Set GOOGLE_API_KEY, GEMINI_API_KEY, or GOOGLE_AI_STUDIO_API_KEY "
                        "in your environment or repository .env file."
                    ),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = int(exc.code) if exc.code is not None and isinstance(exc.code, int) else 2
        return 2 if code != 0 else 0

    if args.interval_seconds < args.min_cooldown_seconds:
        print(
            json.dumps(
                {
                    "error_code": "invalid_arguments",
                    "message": (
                        f"--interval-seconds ({args.interval_seconds}) must be greater "
                        f"than or equal to --min-cooldown-seconds ({args.min_cooldown_seconds})."
                    ),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    if args.max_backoff_seconds < args.base_backoff_seconds:
        print(
            json.dumps(
                {
                    "error_code": "invalid_arguments",
                    "message": (
                        f"--max-backoff-seconds ({args.max_backoff_seconds}) cannot be "
                        f"less than --base-backoff-seconds ({args.base_backoff_seconds})."
                    ),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        daemon = AutonomousSchedulerDaemon(args)
        return daemon.run()
    except LockAcquisitionError:
        return 4
    except Exception as exc:
        logger.exception("Fatal internal daemon error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
