from __future__ import annotations

import sqlite3


_DOCS_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    houdini_version TEXT,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_title_lookup
ON documents(title);

CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    anchor TEXT,
    heading TEXT,
    level INTEGER,
    text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sections_document_lookup
ON sections(document_id, ordinal);
"""


def ensure_docs_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_DOCS_SCHEMA)
    connection.commit()
