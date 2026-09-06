from __future__ import annotations

import sqlite3
from pathlib import Path

from houdocs.db.connection import connect


_SEARCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_entries (
    entry_id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    source_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding_profile_id TEXT NOT NULL,
    token_count INTEGER,
    is_current INTEGER NOT NULL,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS search_entries_namespace_lookup
ON search_entries(namespace, is_current);

CREATE TABLE IF NOT EXISTS search_content (
    entry_id TEXT PRIMARY KEY REFERENCES search_entries(entry_id) ON DELETE CASCADE,
    content TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS document_search_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def ensure_search_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_SEARCH_SCHEMA)
    connection.commit()


class SearchStore:
    def __init__(self, database: Path) -> None:
        self.database = database
        with connect(database) as connection:
            ensure_search_schema(connection)

    def version(self) -> str | None:
        with connect(self.database) as connection:
            row = connection.execute(
                "SELECT value FROM document_search_state WHERE key = 'schema_version'"
            ).fetchone()
        return str(row["value"]) if row is not None else None

    def set_version(self, value: str) -> None:
        with connect(self.database) as connection:
            connection.execute(
                """
                INSERT INTO document_search_state(key, value) VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (value,),
            )
            connection.commit()
