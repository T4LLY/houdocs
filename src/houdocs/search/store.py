from __future__ import annotations

import sqlite3
from pathlib import Path

from houdocs.db.connection import connect_writable

_SEARCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_entries (
    entry_id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    source_id TEXT NOT NULL,
    embedding_profile_id TEXT NOT NULL,
    token_count INTEGER
);
CREATE INDEX IF NOT EXISTS search_entries_namespace_lookup
ON search_entries(namespace);

CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    entry_id UNINDEXED,
    namespace UNINDEXED,
    content,
    tokenize = "unicode61 tokenchars '_:'"
);

CREATE TABLE IF NOT EXISTS search_fts_rows (
    entry_id TEXT PRIMARY KEY REFERENCES search_entries(entry_id) ON DELETE CASCADE,
    fts_rowid INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_cache (
    embedding_profile_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (embedding_profile_id, content_hash)
);

CREATE TABLE IF NOT EXISTS search_vector_profiles (
    embedding_profile_id TEXT PRIMARY KEY,
    dimensions INTEGER NOT NULL,
    table_name TEXT NOT NULL UNIQUE
);

"""


def _create_search_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_SEARCH_SCHEMA)
    connection.commit()


def initialize_search_database(path: Path) -> None:
    with connect_writable(path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        _create_search_schema(connection)
