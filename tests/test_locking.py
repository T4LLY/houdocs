from __future__ import annotations

from pathlib import Path

import pytest

from houdocs.locking import LockUnavailable, OperationLock


def test_operation_lock_is_exclusive_and_released_after_context(tmp_path: Path) -> None:
    path = tmp_path / "locks" / "operation.lock"

    with OperationLock(path):
        with pytest.raises(LockUnavailable):
            with OperationLock(path):
                pass

    with OperationLock(path):
        pass


def test_stale_lock_file_does_not_block_operation(tmp_path: Path) -> None:
    path = tmp_path / "operation.lock"
    path.write_text("stale", encoding="utf-8")

    with OperationLock(path):
        pass
