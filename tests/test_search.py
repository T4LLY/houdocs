from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from houdocs.docs.models import Document, DocumentSection
from houdocs.docs.repository import DocumentRepository
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.index import SearchIndexer
from houdocs.search.models import SearchEntry
from houdocs.search.service import DocumentSearchService
from houdocs.search.store import SearchStore


class FakeEmbeddings:
    def encode(self, texts, profile):
        return np.asarray([[float(len(text)), 1.0] for text in texts], dtype=np.float32)


class FakeDense:
    def __init__(self) -> None:
        self.entries: list[str] = []

    def upsert(self, profile, entries, vectors_by_hash):
        self.entries = [entry.id for entry in entries]

    def remove(self, profile, entry_ids):
        self.entries = [entry for entry in self.entries if entry not in set(entry_ids)]

    def search(self, profile, query_vector, *, namespaces, top_k):
        return list(reversed(self.entries))[:top_k]


def _section(
    document_id: str, ordinal: int, heading: str, text: str
) -> DocumentSection:
    section_id = f"{document_id}#{ordinal}"
    return DocumentSection(
        section_id=section_id,
        document_id=document_id,
        ordinal=ordinal,
        anchor=heading.casefold(),
        heading=heading,
        heading_path=("Page", heading),
        heading_level=2,
        kind="concept",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        token_count=10,
        text=text,
        metadata={"kind": "concept", "heading_path": ["Page", heading]},
    )


def test_hybrid_search_keeps_rrf_and_search_contract_has_no_body(
    tmp_path: Path,
) -> None:
    docs = DocumentRepository(tmp_path / "docs.db")
    document = Document(
        document_id="doc",
        title="Page",
        relative_path="page.txt",
        kind="concept",
        houdini_version="22.0.429",
        content_hash="document-hash",
    )
    docs.replace_document(
        document,
        [
            _section("doc", 0, "Alpha", "alpha geometry"),
            _section("doc", 1, "Beta", "beta geometry"),
        ],
    )
    dense = FakeDense()
    backend = HybridSearchBackend(
        database=tmp_path / "search.db",
        embeddings=FakeEmbeddings(),
        dense_index=dense,
        rrf_k=60,
        candidate_multiplier=8,
        candidate_min=32,
    )
    result = SearchIndexer(
        documents=docs,
        backend=backend,
        store=SearchStore(tmp_path / "search.db"),
        embedding_profile="test-profile",
    ).index_all()

    assert result == {"entries": 2, "indexed": 2, "skipped": 0, "removed": 0}
    payload = DocumentSearchService(repository=docs, backend=backend).search("alpha")
    assert payload["query"] == "alpha"
    assert payload["hits"][0]["heading"] == "Alpha"
    assert "text" not in payload["hits"][0]
    assert set(payload["hits"][0]) == {
        "section_id",
        "score",
        "document",
        "heading",
        "heading_path",
        "kind",
        "relative_path",
        "anchor",
    }


def test_search_reuses_unchanged_entries_and_reindexes_profile_change(
    tmp_path: Path,
) -> None:
    docs = DocumentRepository(tmp_path / "docs.db")
    document = Document("doc", "Page", "page.txt", "concept", "22.0.429", "h")
    docs.replace_document(document, [_section("doc", 0, "Alpha", "alpha")])
    backend = HybridSearchBackend(
        database=tmp_path / "search.db",
        embeddings=FakeEmbeddings(),
        dense_index=FakeDense(),
    )
    store = SearchStore(tmp_path / "search.db")

    first = SearchIndexer(
        documents=docs, backend=backend, store=store, embedding_profile="p1"
    ).index_all()
    second = SearchIndexer(
        documents=docs, backend=backend, store=store, embedding_profile="p1"
    ).index_all()
    third = SearchIndexer(
        documents=docs, backend=backend, store=store, embedding_profile="p2"
    ).index_all()

    assert first["indexed"] == 1
    assert second == {"entries": 1, "indexed": 0, "skipped": 1, "removed": 0}
    assert third["indexed"] == 1


def test_search_fts_rows_track_entry_rowids_for_reindexing(tmp_path: Path) -> None:
    database = tmp_path / "search.db"
    backend = HybridSearchBackend(
        database=database,
        embeddings=FakeEmbeddings(),
        dense_index=FakeDense(),
    )
    entry = SearchEntry("entry", "docs", "source", "alpha", "hash", "p1", 1, {})

    backend.upsert([entry])
    backend.upsert([entry])

    with backend._connect() as connection:
        mapped = connection.execute(
            "SELECT fts_rowid FROM search_fts_rows WHERE entry_id = 'entry'"
        ).fetchone()
        rows = connection.execute(
            "SELECT COUNT(*) FROM search_fts WHERE entry_id = 'entry'"
        ).fetchone()
    assert mapped is not None
    assert rows[0] == 1


def test_search_index_reports_only_uncached_embedding_progress(tmp_path: Path) -> None:
    docs = DocumentRepository(tmp_path / "docs.db")
    document = Document("doc", "Page", "page.txt", "concept", "22.0.429", "h")
    docs.replace_document(
        document,
        [
            _section("doc", 0, "Alpha", "alpha"),
            _section("doc", 1, "Beta", "beta"),
        ],
    )
    backend = HybridSearchBackend(
        database=tmp_path / "search.db",
        embeddings=FakeEmbeddings(),
        dense_index=FakeDense(),
    )
    store = SearchStore(tmp_path / "search.db")
    first_progress: list[tuple[int, int, int, float]] = []
    second_progress: list[tuple[int, int, int, float]] = []

    indexer = SearchIndexer(
        documents=docs,
        backend=backend,
        store=store,
        embedding_profile="p1",
    )
    indexer.index_all(embedding_progress=lambda *values: first_progress.append(values))
    indexer.index_all(embedding_progress=lambda *values: second_progress.append(values))

    assert first_progress[0] == (0, 2, 0, 0.0)
    assert first_progress[-1][0:3] == (2, 2, 2)
    assert second_progress == [(0, 0, 0, 0.0)]


def test_search_index_embeds_changed_sections_per_document(tmp_path: Path) -> None:
    class RecordingEmbeddings:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def encode(self, texts, profile):
            del profile
            self.batch_sizes.append(len(texts))
            return np.asarray(
                [[float(len(text)), 1.0] for text in texts],
                dtype=np.float32,
            )

    docs = DocumentRepository(tmp_path / "docs.db")
    docs.replace_document(
        Document("doc-a", "A", "a.txt", "concept", "22.0.429", "ha"),
        [
            _section("doc-a", 0, "A1", "alpha one"),
            _section("doc-a", 1, "A2", "alpha two"),
        ],
    )
    docs.replace_document(
        Document("doc-b", "B", "b.txt", "concept", "22.0.429", "hb"),
        [
            _section("doc-b", 0, "B1", "beta one"),
            _section("doc-b", 1, "B2", "beta two"),
        ],
    )
    embeddings = RecordingEmbeddings()
    backend = HybridSearchBackend(
        database=tmp_path / "search.db",
        embeddings=embeddings,
        dense_index=FakeDense(),
    )

    SearchIndexer(
        documents=docs,
        backend=backend,
        store=SearchStore(tmp_path / "search.db"),
        embedding_profile="p1",
    ).index_all()

    assert embeddings.batch_sizes == [2, 2]


def test_large_entry_id_lookups_are_batched_for_sqlite_variable_limits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import houdocs.search.hybrid as hybrid_module
    from houdocs.db.connection import connect

    database = tmp_path / "search.db"
    backend = HybridSearchBackend(
        database=database,
        embeddings=FakeEmbeddings(),
        dense_index=FakeDense(),
    )
    entry_ids = [f"entry-{index}" for index in range(5)]
    with connect(database) as connection:
        for entry_id in entry_ids:
            connection.execute(
                """
                INSERT INTO search_entries(
                    entry_id, namespace, source_id, content_hash,
                    embedding_profile_id, token_count, is_current, metadata_json
                ) VALUES (?, 'docs', ?, ?, 'profile', 1, 1, '{}')
                """,
                (entry_id, entry_id, f"hash-{entry_id}"),
            )
            connection.execute(
                "INSERT INTO search_content(entry_id, content) VALUES (?, ?)",
                (entry_id, f"content-{entry_id}"),
            )
        connection.commit()

    monkeypatch.setattr(hybrid_module, "_SQLITE_IN_BATCH_SIZE", 2)
    original_connect = backend._connect
    parameter_counts: list[int] = []

    class GuardedConnection:
        def __init__(self):
            self.connection = original_connect()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return self.connection.__exit__(exc_type, exc, tb)

        def execute(self, sql, parameters=()):
            parameter_counts.append(len(parameters))
            if len(parameters) > 2:
                raise AssertionError("lookup exceeded the configured SQLite batch size")
            return self.connection.execute(sql, parameters)

    monkeypatch.setattr(backend, "_connect", lambda: GuardedConnection())

    profiles = backend._profiles_for_entry_ids(entry_ids)
    loaded = backend._load_entries(entry_ids)

    assert profiles == {entry_id: "profile" for entry_id in entry_ids}
    assert set(loaded) == set(entry_ids)
    assert parameter_counts == [2, 2, 1, 2, 2, 1]
