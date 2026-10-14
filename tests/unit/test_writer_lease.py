import os
import subprocess
import sys
from pathlib import Path

import pytest

from autonomous_futures.execution.writer_lease import ExecutionLease


def test_real_os_lock_fences_second_process_and_releases_cleanly(tmp_path):
    path = tmp_path / "shared-execution.lock"
    lease = ExecutionLease(path)
    lease.acquire()
    lease.assert_held()
    code = """import sys
from pathlib import Path
from autonomous_futures.execution.writer_lease import ExecutionLease
lease = ExecutionLease(Path(sys.argv[1]))
try:
    lease.acquire()
except RuntimeError:
    raise SystemExit(3)
lease.close()
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    blocked = subprocess.run(
        [sys.executable, "-c", code, str(path)], env=environment, capture_output=True
    )
    assert blocked.returncode == 3
    lease.close()
    reopened = subprocess.run(
        [sys.executable, "-c", code, str(path)], env=environment, capture_output=True
    )
    assert reopened.returncode == 0
    assert path.exists()
    with pytest.raises(RuntimeError, match="authority"):
        lease.assert_held()
