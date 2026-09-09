from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from houdocs.db.connection import connect_readonly, connect_writable
from houdocs.db.schema import initialize_docs_database


def test_managed_writable_connection_closes_after_context(tmp_path: Path) -> None:
    connection = connect_writable(tmp_path / "managed.db")
    with connection as active:
        active.execute("CREATE TABLE example(value TEXT)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_managed_writable_connection_rolls_back_and_closes_on_error(
    tmp_path: Path,
) -> None:
    database = tmp_path / "managed.db"
    connection = connect_writable(database)
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


def test_readonly_connection_requires_an_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "missing" / "docs.db"

    with pytest.raises(sqlite3.OperationalError):
        connect_readonly(database)

    assert not database.exists()
    assert not database.parent.exists()


def test_readonly_connection_cannot_write_or_change_database_state(tmp_path: Path) -> None:
    database = tmp_path / "docs.db"
    with connect_writable(database) as connection:
        connection.execute("CREATE TABLE example(value TEXT)")
        connection.execute("INSERT INTO example(value) VALUES ('stored')")
        connection.commit()

    with connect_readonly(database) as connection:
        assert connection.execute("SELECT value FROM example").fetchone()[0] == "stored"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO example(value) VALUES ('mutated')")


def test_docs_database_initialization_owns_schema_and_wal(tmp_path: Path) -> None:
    database = tmp_path / "docs.db"

    initialize_docs_database(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert {"documents", "sections", "node_documents", "python_documents", "vex_documents"}.issubset(tables)
    assert journal_mode == "wal"


def test_repository_and_search_backend_construction_has_no_database_side_effect(
    tmp_path: Path,
) -> None:
    from houdocs.docs.repository import DocumentRepository
    from houdocs.node.repository import NodeRepository
    from houdocs.python_docs.repository import PythonRepository
    from houdocs.search.hybrid import HybridSearchBackend
    from houdocs.vex_docs.repository import VexRepository

    class NoopEmbeddings:
        def encode(self, texts, profile):
            raise AssertionError((texts, profile))

    docs_database = tmp_path / "docs.db"
    search_database = tmp_path / "search.db"

    DocumentRepository(docs_database)
    NodeRepository(docs_database)
    PythonRepository(docs_database)
    VexRepository(docs_database)
    HybridSearchBackend(database=search_database, embeddings=NoopEmbeddings())

    assert not docs_database.exists()
    assert not search_database.exists()
