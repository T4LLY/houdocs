from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from houdocs.db.connection import connect


def test_managed_connection_closes_after_context(tmp_path: Path) -> None:
    connection = connect(tmp_path / "managed.db")
    with connection as active:
        active.execute("CREATE TABLE example(value TEXT)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_managed_connection_rolls_back_and_closes_on_error(tmp_path: Path) -> None:
    database = tmp_path / "managed.db"
    connection = connect(database)
    with pytest.raises(RuntimeError, match="forced"):
        with connection as active:
            active.execute("CREATE TABLE example(value TEXT)")
            active.execute("INSERT INTO example(value) VALUES ('temporary')")
            raise RuntimeError("forced")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")

    reader = sqlite3.connect(database)
    try:
        table = reader.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='example'"
        ).fetchone()
        if table is not None:
            count = reader.execute("SELECT COUNT(*) FROM example").fetchone()[0]
            assert count == 0
    finally:
        reader.close()
