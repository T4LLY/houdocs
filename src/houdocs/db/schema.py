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

CREATE TABLE IF NOT EXISTS node_documents (
    node_type TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    houdini_name TEXT,
    metadata_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS node_documents_document_lookup
ON node_documents(document_id);

CREATE INDEX IF NOT EXISTS node_documents_name_lookup
ON node_documents(houdini_name);

CREATE TABLE IF NOT EXISTS python_documents (
    symbol TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_symbol TEXT,
    member_name TEXT,
    kind TEXT NOT NULL,
    signatures_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS python_documents_document_lookup
ON python_documents(document_id);

CREATE TABLE IF NOT EXISTS vex_documents (
    function_name TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    signatures_json TEXT NOT NULL,
    contexts_json TEXT NOT NULL,
    group_name TEXT,
    tags_json TEXT NOT NULL,
    status TEXT,
    metadata_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS vex_documents_document_lookup
ON vex_documents(document_id);
"""


def ensure_docs_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_DOCS_SCHEMA)
    connection.commit()
