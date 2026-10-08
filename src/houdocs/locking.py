from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import BinaryIO


class LockUnavailable(RuntimeError):
    pass


class OperationLock:
    """Non-blocking OS-backed exclusive lock for one operation path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: BinaryIO | None = None

    def __enter__(self) -> OperationLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            _lock_nonblocking(handle)
        except OSError as exc:
            handle.close()
            raise LockUnavailable(str(self.path)) from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()


def _lock_nonblocking(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    # fcntl is POSIX-only; load it only after the Windows branch.
    fcntl = importlib.import_module("fcntl")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl = importlib.import_module("fcntl")
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
