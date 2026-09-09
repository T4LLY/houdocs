from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from houdocs.db.schema import initialize_docs_database
from houdocs.docs.models import Document, DocumentSection
from houdocs.docs.repository import DocumentRepository
from houdocs.search.dense import SQLiteVecIndex
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.index import SearchIndexer
from houdocs.search.models import SearchEntry, SearchHit
from houdocs.search.store import initialize_search_database
from houdocs.search.service import DocumentSearchService


def _docs(database: Path) -> DocumentRepository:
    initialize_docs_database(database)
    return DocumentRepository(database)


def _backend(**kwargs) -> HybridSearchBackend:
    initialize_search_database(kwargs["database"])
    return HybridSearchBackend(**kwargs)


def _test_token_count(text: str) -> int:
    return len(text.encode("utf-8"))


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


class TransactionalDense(SQLiteVecIndex):
    """SQLite-backed test double that participates in the caller transaction."""

    def upsert_in_transaction(self, connection, profile, entries, vectors_by_hash):
        del vectors_by_hash
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS test_dense_vectors (
                embedding_profile_id TEXT NOT NULL,
                entry_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                PRIMARY KEY (embedding_profile_id, entry_id)
            )
            """
        )
        connection.executemany(
            "DELETE FROM test_dense_vectors WHERE embedding_profile_id = ? AND entry_id = ?",
            [(profile, entry.id) for entry in entries],
        )
        connection.executemany(
            "INSERT INTO test_dense_vectors(embedding_profile_id, entry_id, namespace) VALUES (?, ?, ?)",
            [(profile, entry.id, entry.namespace) for entry in entries],
        )

    def remove_in_transaction(self, connection, profile, entry_ids):
        connection.executemany(
            "DELETE FROM test_dense_vectors WHERE embedding_profile_id = ? AND entry_id = ?",
            [(profile, entry_id) for entry_id in entry_ids],
        )


class FailingConnection:
    def __init__(self, connection, *, sql_fragment: str, message: str) -> None:
        self.connection = connection
        self.sql_fragment = sql_fragment
        self.message = message

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.connection.__exit__(exc_type, exc, tb)

    def execute(self, sql, parameters=()):
        if self.sql_fragment in sql:
            raise sqlite3.OperationalError(self.message)
        return self.connection.execute(sql, parameters)

    def __getattr__(self, name):
        return getattr(self.connection, name)


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
    )


def test_search_schema_keeps_only_live_index_state(tmp_path: Path) -> None:
    database = tmp_path / "search.db"
    initialize_search_database(database)
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        entry_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(search_entries)")
        }

    assert "search_content" not in tables
    assert "content_hash" not in entry_columns
    assert "metadata_json" not in entry_columns


def test_hybrid_search_keeps_rrf_and_search_contract_has_no_body(
    tmp_path: Path,
) -> None:
    docs = _docs(tmp_path / "docs.db")
    document = Document(
        document_id="doc",
        title="Page",
        relative_path="page.txt",
        kind="concept",
        houdini_version="22.0.429",
    )
    docs.insert_document(
        document,
        [
            _section("doc", 0, "Alpha", "alpha geometry"),
            _section("doc", 1, "Beta", "beta geometry"),
        ],
    )
    dense = FakeDense()
    backend = _backend(
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
        embedding_profile="test-profile",
        token_counter=_test_token_count,
    ).index_all()

    assert result == {"entries": 2}
    payload = DocumentSearchService(repository=docs, backend=backend).search("alpha")
    assert set(payload) == {"hits"}
    assert payload["hits"][0]["path"] == ["Page", "Alpha"]
    assert "text" not in payload["hits"][0]
    assert set(payload["hits"][0]) == {"path", "kind", "score", "tokens"}
    assert payload["hits"][0]["tokens"] == 10


def test_search_indexer_indexes_all_entries_each_run(
    tmp_path: Path,
) -> None:
    docs = _docs(tmp_path / "docs.db")
    document = Document("doc", "Page", "page.txt", "concept", "22.0.429")
    docs.insert_document(document, [_section("doc", 0, "Alpha", "alpha")])
    dense = FakeDense()
    backend = _backend(
        database=tmp_path / "search.db",
        embeddings=FakeEmbeddings(),
        dense_index=dense,
    )

    first = SearchIndexer(
        documents=docs,
        backend=backend,
        embedding_profile="p1",
        token_counter=_test_token_count,
    ).index_all()
    second = SearchIndexer(
        documents=docs,
        backend=backend,
        embedding_profile="p1",
        token_counter=_test_token_count,
    ).index_all()

    assert first == {"entries": 1}
    assert second == {"entries": 1}
    assert dense.entries == ["document:doc#0"]


def test_search_retries_entries_after_embedding_failure(tmp_path: Path) -> None:
    class FailingEmbeddings:
        def encode(self, texts, profile):
            del texts, profile
            raise RuntimeError("embedding service unavailable")

    docs = _docs(tmp_path / "docs.db")
    docs.insert_document(
        Document("doc", "Page", "page.txt", "concept", "22.0.429"),
        [_section("doc", 0, "Alpha", "alpha")],
    )
    database = tmp_path / "search.db"
    failed_backend = _backend(
        database=database,
        embeddings=FailingEmbeddings(),
        dense_index=FakeDense(),
    )

    with pytest.raises(RuntimeError, match="embedding service unavailable"):
        SearchIndexer(
            documents=docs,
            backend=failed_backend,
            embedding_profile="p1",
            token_counter=_test_token_count,
        ).index_all()

    with failed_backend._read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM search_entries").fetchone()[0] == 0

    dense = FakeDense()
    retry = SearchIndexer(
        documents=docs,
        backend=_backend(
            database=database,
            embeddings=FakeEmbeddings(),
            dense_index=dense,
        ),
        embedding_profile="p1",
        token_counter=_test_token_count,
    ).index_all()

    assert retry == {"entries": 1}
    assert dense.entries == ["document:doc#0"]


def test_search_fts_rows_track_entry_rowids_for_repeated_upserts(tmp_path: Path) -> None:
    database = tmp_path / "search.db"
    backend = _backend(
        database=database,
        embeddings=FakeEmbeddings(),
        dense_index=FakeDense(),
    )
    entry = SearchEntry("entry", "docs", "source", "alpha", "hash", "p1", 1)

    backend.upsert([entry])
    backend.upsert([entry])

    with backend._read() as connection:
        mapped = connection.execute(
            "SELECT fts_rowid FROM search_fts_rows WHERE entry_id = 'entry'"
        ).fetchone()
        rows = connection.execute(
            "SELECT COUNT(*) FROM search_fts WHERE entry_id = 'entry'"
        ).fetchone()
    assert mapped is not None
    assert rows[0] == 1


def test_search_upsert_rolls_back_vectors_when_entry_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "search.db"
    backend = _backend(
        database=database,
        embeddings=FakeEmbeddings(),
        dense_index=TransactionalDense(database),
    )
    original_connect = backend._write

    monkeypatch.setattr(
        backend,
        "_write",
        lambda: FailingConnection(
            original_connect(),
            sql_fragment="INSERT INTO search_entries",
            message="forced entry write failure",
        ),
    )

    with pytest.raises(sqlite3.OperationalError, match="forced entry write failure"):
        backend.upsert(
            [SearchEntry("entry", "docs", "source", "alpha", "hash", "p1", 1)]
        )

    with original_connect() as connection:
        dense_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'test_dense_vectors'"
        ).fetchone()
        entries = connection.execute("SELECT * FROM search_entries").fetchall()
    assert dense_table is None
    assert entries == []


def test_search_profile_move_rolls_back_dense_and_entry_state_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "search.db"
    backend = _backend(
        database=database,
        embeddings=FakeEmbeddings(),
        dense_index=TransactionalDense(database),
    )
    backend.upsert(
        [SearchEntry("entry", "docs", "source", "alpha", "hash", "p1", 1)]
    )
    original_connect = backend._write

    monkeypatch.setattr(
        backend,
        "_write",
        lambda: FailingConnection(
            original_connect(),
            sql_fragment="INSERT INTO search_entries",
            message="forced entry write failure",
        ),
    )

    with pytest.raises(sqlite3.OperationalError, match="forced entry write failure"):
        backend.upsert(
            [
                SearchEntry(
                    "entry", "docs", "source", "alpha", "hash", "p2", 1
                )
            ]
        )

    with original_connect() as connection:
        dense_rows = connection.execute(
            "SELECT embedding_profile_id, entry_id FROM test_dense_vectors ORDER BY embedding_profile_id"
        ).fetchall()
        stored = connection.execute(
            "SELECT embedding_profile_id FROM search_entries WHERE entry_id = 'entry'"
        ).fetchone()
        cached_p2 = connection.execute(
            "SELECT COUNT(*) FROM embedding_cache WHERE embedding_profile_id = 'p2' AND content_hash = 'hash'"
        ).fetchone()[0]

    assert [(row["embedding_profile_id"], row["entry_id"]) for row in dense_rows] == [
        ("p1", "entry")
    ]
    assert stored["embedding_profile_id"] == "p1"
    assert cached_p2 == 1


def test_search_skips_stale_hits_without_aborting_current_results(
    tmp_path: Path,
) -> None:
    class StaleBackend:
        def search(self, query, *, namespaces, top_k):
            del query, namespaces, top_k
            return [
                SearchHit("document", "missing", 1.0, token_count=5),
                SearchHit("document", "doc#0", 0.5, token_count=10),
            ]

    docs = _docs(tmp_path / "docs.db")
    docs.insert_document(
        Document("doc", "Page", "page.txt", "concept", "22.0.429"),
        [_section("doc", 0, "Alpha", "alpha")],
    )

    result = DocumentSearchService(repository=docs, backend=StaleBackend()).search(
        "alpha"
    )

    assert [hit["path"] for hit in result["hits"]] == [["Page", "Alpha"]]


def test_search_index_reuses_embedding_for_duplicate_content_hashes(
    tmp_path: Path,
) -> None:
    class RecordingEmbeddings:
        def __init__(self) -> None:
            self.text_batches: list[list[str]] = []

        def encode(self, texts, profile):
            del profile
            batch = list(texts)
            self.text_batches.append(batch)
            return np.asarray(
                [[float(len(text)), 1.0] for text in batch],
                dtype=np.float32,
            )

    docs = _docs(tmp_path / "docs.db")
    docs.insert_document(
        Document("doc-a", "A", "a.txt", "concept", "22.0.429"),
        [_section("doc-a", 0, "A", "shared content")],
    )
    docs.insert_document(
        Document("doc-b", "B", "b.txt", "concept", "22.0.429"),
        [_section("doc-b", 0, "B", "shared content")],
    )
    embeddings = RecordingEmbeddings()
    backend = _backend(
        database=tmp_path / "search.db",
        embeddings=embeddings,
        dense_index=FakeDense(),
    )
    progress: list[tuple[int, int, int, float]] = []

    SearchIndexer(
        documents=docs,
        backend=backend,
        embedding_profile="p1",
        token_counter=_test_token_count,
    ).index_all(embedding_progress=lambda *values: progress.append(values))

    assert embeddings.text_batches == [["shared content"]]
    assert progress[0] == (0, 1, 0, 0.0)
    assert progress[-1][0:3] == (1, 1, 1)


def test_search_index_embeds_entries_per_document(tmp_path: Path) -> None:
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

    docs = _docs(tmp_path / "docs.db")
    docs.insert_document(
        Document("doc-a", "A", "a.txt", "concept", "22.0.429"),
        [
            _section("doc-a", 0, "A1", "alpha one"),
            _section("doc-a", 1, "A2", "alpha two"),
        ],
    )
    docs.insert_document(
        Document("doc-b", "B", "b.txt", "concept", "22.0.429"),
        [
            _section("doc-b", 0, "B1", "beta one"),
            _section("doc-b", 1, "B2", "beta two"),
        ],
    )
    embeddings = RecordingEmbeddings()
    backend = _backend(
        database=tmp_path / "search.db",
        embeddings=embeddings,
        dense_index=FakeDense(),
    )

    SearchIndexer(
        documents=docs,
        backend=backend,
        embedding_profile="p1",
        token_counter=_test_token_count,
    ).index_all()

    assert embeddings.batch_sizes == [2, 2]


def test_large_entry_id_lookups_are_batched_for_sqlite_variable_limits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import houdocs.search.hybrid as hybrid_module
    from houdocs.db.connection import connect_writable

    database = tmp_path / "search.db"
    backend = _backend(
        database=database,
        embeddings=FakeEmbeddings(),
        dense_index=FakeDense(),
    )
    entry_ids = [f"entry-{index}" for index in range(5)]
    with connect_writable(database) as connection:
        for entry_id in entry_ids:
            connection.execute(
                """
                INSERT INTO search_entries(
                    entry_id, namespace, source_id, embedding_profile_id, token_count
                ) VALUES (?, 'docs', ?, 'profile', 1)
                """,
                (entry_id, entry_id),
            )
        connection.commit()

    monkeypatch.setattr(hybrid_module, "_SQLITE_IN_BATCH_SIZE", 2)
    original_connect = backend._read
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

    monkeypatch.setattr(backend, "_read", lambda: GuardedConnection())

    with backend._read() as connection:
        profiles = backend._profiles_for_entry_ids_in_connection(connection, entry_ids)
    loaded = backend._load_entries(entry_ids)

    assert profiles == {entry_id: "profile" for entry_id in entry_ids}
    assert set(loaded) == set(entry_ids)
    assert parameter_counts == [2, 2, 1, 2, 2, 1]


def test_search_index_separates_domains_and_indexes_hom_symbols(tmp_path: Path) -> None:
    from houdocs.python_docs.models import PythonDocumentRecord
    from houdocs.python_docs.repository import PythonRepository
    from houdocs.vex_docs.models import VexDocumentRecord
    from houdocs.vex_docs.repository import VexRepository

    database = tmp_path / "docs.db"
    docs = _docs(database)
    docs.insert_document(
        Document("concept", "Overview", "overview.txt", "concept", "22.0.429"),
        [_section("concept", 0, "Overview", "general documentation")],
    )
    node_section = _section("node", 0, "Copy to Points", "copy geometry to points")
    node_section = DocumentSection(
        **{**node_section.__dict__, "kind": "node-doc"}
    )
    docs.insert_document(
        Document(
            "node",
            "Copy to Points",
            "nodes/sop/copytopoints.txt",
            "node-doc",
            "22.0.429",
        ),
        [node_section],
    )
    hom_text = (
        "hou.Node\n\n::`setInput(self, input_index, node)`:\n    Connect another node."
    )
    hom_section = _section("hom", 0, "hou.Node", hom_text)
    hom_section = DocumentSection(**{**hom_section.__dict__, "kind": "hom"})
    docs.insert_document(
        Document("hom", "hou.Node", "hom/hou/Node.txt", "hom", "22.0.429"),
        [hom_section],
    )
    vex_section = _section(
        "vex", 0, "xyzdist", "xyzdist finds the nearest surface point"
    )
    vex_section = DocumentSection(**{**vex_section.__dict__, "kind": "vex"})
    docs.insert_document(
        Document(
            "vex", "xyzdist", "vex/functions/xyzdist.txt", "vex", "22.0.429"
        ),
        [vex_section],
    )

    hom = PythonRepository(database)
    hom.insert_all(
        [
            PythonDocumentRecord("hou.Node", "hom", "hou", "Node", "class", ()),
            PythonDocumentRecord(
                "hou.Node.setInput",
                "hom",
                "hou.Node",
                "setInput",
                "method",
                ("setInput(self, input_index, node)",),
            ),
            PythonDocumentRecord(
                "hou.Node.missing",
                "hom",
                "hou.Node",
                "missing",
                "method",
                ("missing()",),
            ),
        ]
    )
    vex = VexRepository(database)
    vex.insert_all(
        [
            VexDocumentRecord(
                "xyzdist",
                "vex",
                ("float xyzdist(int geometry, vector origin)",),
                ("sop",),
                "geometry",
                (),
                None,
            )
        ]
    )

    backend = _backend(
        database=tmp_path / "search.db",
        embeddings=FakeEmbeddings(),
        dense_index=FakeDense(),
    )
    result = SearchIndexer(
        documents=docs,
        python_documents=hom,
        vex_documents=vex,
        backend=backend,
        embedding_profile="p1",
        token_counter=_test_token_count,
    ).index_all()

    assert result["entries"] == 5
    with backend._read() as connection:
        entry_rows = connection.execute(
            "SELECT namespace, entry_id FROM search_entries ORDER BY namespace, entry_id"
        ).fetchall()
        hom_member = connection.execute(
            "SELECT content FROM search_fts WHERE entry_id = ?",
            ("hom:hou.Node.setInput",),
        ).fetchone()
        token_rows = connection.execute(
            "SELECT entry_id, token_count FROM search_entries ORDER BY entry_id"
        ).fetchall()
    by_namespace: dict[str, list[str]] = {}
    for row in entry_rows:
        by_namespace.setdefault(str(row["namespace"]), []).append(str(row["entry_id"]))
    assert by_namespace == {
        "document": ["document:concept#0"],
        "hom": ["hom:hou.Node", "hom:hou.Node.setInput"],
        "node": ["node:node#0"],
        "vex": ["vex:xyzdist"],
    }
    assert hom_member is not None
    assert "hou.Node.setInput" in hom_member["content"]
    assert "Connect another node." in hom_member["content"]
    token_counts = {str(row["entry_id"]): int(row["token_count"]) for row in token_rows}
    assert token_counts["document:concept#0"] == 10
    assert token_counts["node:node#0"] == 10
    assert token_counts["hom:hou.Node"] == _test_token_count(hom_text)
    assert token_counts["hom:hou.Node.setInput"] == _test_token_count(
        "setInput(self, input_index, node)\n    Connect another node."
    )
    assert token_counts["vex:xyzdist"] == _test_token_count(vex_section.text)


def test_search_output_collapses_document_heading_metadata_to_path(
    tmp_path: Path,
) -> None:
    docs = _docs(tmp_path / "docs.db")
    section = DocumentSection(
        section_id="doc#0",
        document_id="doc",
        ordinal=0,
        anchor="inputs",
        heading="Inputs",
        heading_path=("Copy to Points", "Inputs"),
        heading_level=2,
        kind="node-doc",
        content_hash="hash",
        token_count=10,
        text="inputs",
    )
    docs.insert_document(
        Document(
            "doc",
            "Copy to Points",
            "nodes/sop/copytopoints.txt",
            "node-doc",
            "22.0.429",
        ),
        [section],
    )

    class OneHitBackend:
        def search(self, query, *, namespaces, top_k):
            del query, namespaces, top_k
            return [SearchHit("node", "doc#0", 1.0, token_count=12)]

    result = DocumentSearchService(repository=docs, backend=OneHitBackend()).search(
        "copy to points"
    )

    assert result == {
        "hits": [
            {
                "path": ["Copy to Points", "Inputs"],
                "kind": "node-doc",
                "score": 10000.0,
                "tokens": 12,
            }
        ]
    }


def test_search_output_uses_symbol_and_function_paths(tmp_path: Path) -> None:
    from houdocs.python_docs.models import PythonDocumentRecord
    from houdocs.python_docs.repository import PythonRepository
    from houdocs.vex_docs.models import VexDocumentRecord
    from houdocs.vex_docs.repository import VexRepository

    database = tmp_path / "docs.db"
    docs = _docs(database)
    docs.insert_document(
        Document("hom-doc", "hou.Node", "hom/hou/Node.txt", "hom", "22.0.429"),
        [],
    )
    docs.insert_document(
        Document(
            "vex-doc", "xyzdist", "vex/functions/xyzdist.txt", "vex", "22.0.429"
        ),
        [],
    )
    hom = PythonRepository(database)
    hom.insert_all(
        [
            PythonDocumentRecord(
                "hou.Node.setInput",
                "hom-doc",
                "hou.Node",
                "setInput",
                "method",
                ("setInput(self, input_index, node)",),
            )
        ]
    )
    vex = VexRepository(database)
    vex.insert_all(
        [
            VexDocumentRecord(
                "xyzdist",
                "vex-doc",
                ("float xyzdist(int geometry, vector origin)",),
                ("sop",),
                "geometry",
                (),
                None,
            )
        ]
    )

    class SpecializedBackend:
        def __init__(self, hit: SearchHit) -> None:
            self.hit = hit

        def search(self, query, *, namespaces, top_k):
            del query, namespaces, top_k
            return [self.hit]

    hom_result = DocumentSearchService(
        repository=docs,
        python_repository=hom,
        vex_repository=vex,
        backend=SpecializedBackend(
            SearchHit(
                "hom",
                "hou.Node.setInput",
                1.0,
                token_count=13,
            )
        ),
    ).search("connect node input")
    vex_result = DocumentSearchService(
        repository=docs,
        python_repository=hom,
        vex_repository=vex,
        backend=SpecializedBackend(
            SearchHit("vex", "xyzdist", 1.0, token_count=14)
        ),
    ).search("nearest surface")

    assert hom_result["hits"][0]["path"] == ["hou.Node", "setInput"]
    assert hom_result["hits"][0]["kind"] == "hom"
    assert hom_result["hits"][0]["tokens"] == 13
    assert vex_result["hits"][0]["path"] == ["xyzdist"]
    assert vex_result["hits"][0]["kind"] == "vex"
    assert vex_result["hits"][0]["tokens"] == 14


def test_existing_search_entry_without_fts_mapping_fails_closed(tmp_path: Path) -> None:
    from houdocs.db.connection import connect_writable
    from houdocs.errors import HouDocsError

    database = tmp_path / "search.db"
    backend = _backend(
        database=database,
        embeddings=FakeEmbeddings(),
        dense_index=FakeDense(),
    )
    entry = SearchEntry("entry", "docs", "source", "alpha", "hash", "p1", 1)
    backend.upsert([entry])

    with connect_writable(database) as connection:
        connection.execute("DELETE FROM search_fts_rows WHERE entry_id = ?", ("entry",))
        connection.commit()

    with pytest.raises(HouDocsError, match="missing its FTS row mapping") as exc_info:
        backend.upsert([entry])
    assert exc_info.value.error.code == "docs_database_error"


def test_fts_operational_error_propagates(tmp_path: Path) -> None:
    import houdocs.search.lexical as lexical_module

    def _make_conn():
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        return conn

    index = lexical_module.SQLiteFtsIndex(_make_conn)

    with pytest.raises(sqlite3.OperationalError):
        index.search("test", namespaces=["docs"], limit=10)


def test_search_domain_selects_one_namespace_or_all_domains(tmp_path: Path) -> None:
    from houdocs.python_docs.repository import PythonRepository
    from houdocs.search.domain import ALL_SEARCH_NAMESPACES, SearchDomain
    from houdocs.vex_docs.repository import VexRepository

    class RecordingBackend:
        def __init__(self) -> None:
            self.namespaces: list[str] = []

        def search(self, query, *, namespaces, top_k):
            del query, top_k
            self.namespaces = list(namespaces)
            return []

    docs = _docs(tmp_path / "docs.db")
    backend = RecordingBackend()
    service = DocumentSearchService(
        repository=docs,
        python_repository=PythonRepository(docs.database),
        vex_repository=VexRepository(docs.database),
        backend=backend,
    )

    service.search("node input", domain=SearchDomain.HOM)
    assert backend.namespaces == ["hom"]

    service.search("node input")
    assert backend.namespaces == list(ALL_SEARCH_NAMESPACES)
