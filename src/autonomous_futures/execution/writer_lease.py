"""OS-held execution lease for participating writers; a PID file alone is never authority.

Use a shared account-level path across releases. This cannot fence a legacy writer
that does not participate; its exchange trading permission must be resolved separately.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from pathlib import Path
from typing import BinaryIO, Protocol, cast


class PosixLocks(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, descriptor: int, operation: int) -> None: ...


class ExecutionLease:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.descriptor: BinaryIO | None = None
        self.pid: int | None = None
        self.io_lock = asyncio.Lock()

    def acquire(self) -> None:
        if self.descriptor is not None:
            self.assert_held()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if self.path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
                os.fsync(stream.fileno())
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                locks = cast(PosixLocks, importlib.import_module("fcntl"))
                locks.flock(stream.fileno(), locks.LOCK_EX | locks.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError("Another execution writer holds the shared lease") from exc
        self.descriptor, self.pid = stream, os.getpid()

    def assert_held(self) -> None:
        if self.descriptor is None or self.descriptor.closed or self.pid != os.getpid():
            raise RuntimeError("Current process does not hold execution authority")
        opened = os.fstat(self.descriptor.fileno())
        current = self.path.stat()
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("Execution lock path was replaced; authority is invalid")

    def close(self) -> None:
        if self.descriptor is None:
            return
        self.assert_held()
        stream = self.descriptor
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            locks = cast(PosixLocks, importlib.import_module("fcntl"))
            locks.flock(stream.fileno(), locks.LOCK_UN)
        stream.close()
        self.descriptor, self.pid = None, None
