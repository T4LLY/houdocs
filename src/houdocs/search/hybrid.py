from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from houdocs.db.connection import connect_readonly, connect_writable
from houdocs.errors import HouDocsError
from houdocs.search.cache import EmbeddingCache
from houdocs.search.dense import SQLiteVecIndex
from houdocs.search.embedding import EmbeddingProvider
from houdocs.search.lexical import SQLiteFtsIndex
from houdocs.search.models import SearchEntry, SearchHit
from houdocs.search.rrf import reciprocal_rank_fusion


_SQLITE_IN_BATCH_SIZE = 500


@dataclass(frozen=True)
class _StoredEntry:
    entry_id: str
    namespace: str
    source_id: str
    token_count: int | None


class HybridSearchBackend:
    def __init__(
        self,
        *,
        database: Path,
        embeddings: EmbeddingProvider,
        rrf_k: int = 60,
        candidate_multiplier: int = 8,
        candidate_min: int = 32,
        dense_index: SQLiteVecIndex | None = None,
    ) -> None:
        self.database = database
        self.embeddings = embeddings
        self.rrf_k = rrf_k
        self.candidate_multiplier = candidate_multiplier
        self.candidate_min = candidate_min
        self.lexical = SQLiteFtsIndex(self._read)
        self.dense = dense_index or SQLiteVecIndex(database)
        self.embedding_cache = EmbeddingCache(database)

    def _read(self) -> sqlite3.Connection:
        return connect_readonly(self.database)

    def _write(self) -> sqlite3.Connection:
        return connect_writable(self.database)

    def upsert(
        self,
        entries: Sequence[SearchEntry],
        *,
        embedding_progress: Callable[[int, float], None] | None = None,
    ) -> None:
        if not entries:
            return
        grouped: dict[str, list[SearchEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.embedding_profile, []).append(entry)
        vectors_by_profile: dict[str, dict[str, np.ndarray]] = {}
        for profile, group in grouped.items():
            vectors_by_profile[profile] = self._vectors_for_entries(
                profile,
                group,
                embedding_progress=embedding_progress,
            )

        entry_ids = [entry.id for entry in entries]
        with self._write() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_profiles = self._profiles_for_entry_ids_in_connection(
                connection, entry_ids
            )
            fts_rowids = self._fts_rowids_for_entry_ids_in_connection(
                connection, entry_ids
            )
            moved: dict[str, list[str]] = {}
            for entry in entries:
                old_profile = existing_profiles.get(entry.id)
                if old_profile and old_profile != entry.embedding_profile:
                    moved.setdefault(old_profile, []).append(entry.id)

            if isinstance(self.dense, SQLiteVecIndex):
                for profile, group in grouped.items():
                    self.dense.upsert_in_transaction(
                        connection, profile, group, vectors_by_profile[profile]
                    )
                for profile, entry_ids in moved.items():
                    self.dense.remove_in_transaction(connection, profile, entry_ids)
            else:
                for profile, group in grouped.items():
                    self.dense.upsert(profile, group, vectors_by_profile[profile])
                for profile, entry_ids in moved.items():
                    self.dense.remove(profile, entry_ids)
            for entry in entries:
                existing_profile = existing_profiles.get(entry.id)
                fts_rowid = fts_rowids.get(entry.id)
                if existing_profile is not None:
                    if fts_rowid is None:
                        raise HouDocsError(
                            "docs_database_error",
                            f"Search entry is missing its FTS row mapping: {entry.id}",
                        )
                    connection.execute(
                        "DELETE FROM search_fts WHERE rowid = ?", (fts_rowid,)
                    )
                connection.execute(
                    """
                    INSERT INTO search_entries(
                        entry_id, namespace, source_id, embedding_profile_id, token_count
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET
                        namespace=excluded.namespace,
                        source_id=excluded.source_id,
                        embedding_profile_id=excluded.embedding_profile_id,
                        token_count=excluded.token_count
                    """,
                    (
                        entry.id,
                        entry.namespace,
                        entry.source_id,
                        entry.embedding_profile,
                        entry.token_count,
                    ),
                )
                connection.execute(
                    "INSERT INTO search_fts(entry_id, namespace, content) VALUES (?, ?, ?)",
                    (entry.id, entry.namespace, entry.content),
                )
                fts_rowid = connection.execute("SELECT last_insert_rowid()").fetchone()[
                    0
                ]
                connection.execute(
                    """
                    INSERT INTO search_fts_rows(entry_id, fts_rowid) VALUES (?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET fts_rowid=excluded.fts_rowid
                    """,
                    (entry.id, fts_rowid),
                )
            connection.commit()

    def missing_embedding_count(self, entries: Sequence[SearchEntry]) -> int:
        grouped: dict[str, set[str]] = {}
        for entry in entries:
            grouped.setdefault(entry.embedding_profile, set()).add(entry.content_hash)
        missing = 0
        for profile, content_hashes in grouped.items():
            missing += self.embedding_cache.missing_count(
                profile, sorted(content_hashes)
            )
        return missing

    def search(
        self,
        query: str,
        *,
        namespaces: Sequence[str],
        top_k: int = 10,
    ) -> list[SearchHit]:
        if not query.strip():
            raise HouDocsError("empty_query", "Search query must not be empty.")
        if top_k <= 0:
            return []
        candidate_limit = max(top_k * self.candidate_multiplier, self.candidate_min)
        profiles = self._profiles_for(namespaces)
        if not profiles:
            return []
        lexical = self.lexical.search(
            query, namespaces=namespaces, limit=candidate_limit
        )
        dense_rankings: list[list[str]] = []
        for profile in profiles:
            query_vectors = self.embeddings.encode([query], profile)
            if len(query_vectors) != 1:
                raise HouDocsError(
                    "embedding_protocol_error",
                    "Embedding provider returned the wrong query vector count.",
                )
            dense_rankings.append(
                self.dense.search(
                    profile,
                    query_vectors[0],
                    namespaces=namespaces,
                    top_k=candidate_limit,
                )
            )
        scores = reciprocal_rank_fusion([*dense_rankings, lexical], k=self.rrf_k)
        if not scores:
            return []
        by_id = self._load_entries(list(scores))
        ranked = sorted(
            (entry_id for entry_id in scores if entry_id in by_id),
            key=lambda entry_id: (-scores[entry_id], entry_id),
        )[:top_k]
        return [
            SearchHit(
                namespace=by_id[entry_id].namespace,
                source_id=by_id[entry_id].source_id,
                score=scores[entry_id],
                token_count=by_id[entry_id].token_count,
            )
            for entry_id in ranked
        ]

    def _profiles_for(self, namespaces: Sequence[str]) -> list[str]:
        if not namespaces:
            return []
        placeholders = ",".join("?" for _ in namespaces)
        with self._read() as connection:
            rows = connection.execute(
                f"""
                SELECT embedding_profile_id FROM search_entries
                WHERE namespace IN ({placeholders})
                GROUP BY embedding_profile_id
                ORDER BY embedding_profile_id
                """,
                tuple(namespaces),
            ).fetchall()
        return [str(row["embedding_profile_id"]) for row in rows]

    def _profiles_for_entry_ids_in_connection(
        self,
        connection: sqlite3.Connection,
        entry_ids: Sequence[str],
    ) -> dict[str, str]:
        if not entry_ids:
            return {}
        found: dict[str, str] = {}
        for start in range(0, len(entry_ids), _SQLITE_IN_BATCH_SIZE):
            batch = entry_ids[start : start + _SQLITE_IN_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                f"SELECT entry_id, embedding_profile_id FROM search_entries WHERE entry_id IN ({placeholders})",
                tuple(batch),
            ).fetchall()
            found.update(
                {str(row["entry_id"]): str(row["embedding_profile_id"]) for row in rows}
            )
        return found

    def _fts_rowids_for_entry_ids_in_connection(
        self,
        connection: sqlite3.Connection,
        entry_ids: Sequence[str],
    ) -> dict[str, int]:
        if not entry_ids:
            return {}
        found: dict[str, int] = {}
        for start in range(0, len(entry_ids), _SQLITE_IN_BATCH_SIZE):
            batch = entry_ids[start : start + _SQLITE_IN_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                f"SELECT entry_id, fts_rowid FROM search_fts_rows WHERE entry_id IN ({placeholders})",
                tuple(batch),
            ).fetchall()
            found.update({str(row["entry_id"]): int(row["fts_rowid"]) for row in rows})
        return found

    def _load_entries(self, entry_ids: Sequence[str]) -> dict[str, _StoredEntry]:
        if not entry_ids:
            return {}
        found: dict[str, _StoredEntry] = {}
        for start in range(0, len(entry_ids), _SQLITE_IN_BATCH_SIZE):
            batch = entry_ids[start : start + _SQLITE_IN_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            with self._read() as connection:
                rows = connection.execute(
                    f"""
                    SELECT entry_id, namespace, source_id, token_count
                    FROM search_entries
                    WHERE entry_id IN ({placeholders})
                    """,
                    tuple(batch),
                ).fetchall()
            found.update(
                {
                    entry.entry_id: entry
                    for entry in (self._row_to_stored(row) for row in rows)
                }
            )
        return found

    def _vectors_for_entries(
        self,
        profile: str,
        entries: Sequence[SearchEntry],
        *,
        embedding_progress: Callable[[int, float], None] | None = None,
    ) -> dict[str, np.ndarray]:
        if not entries:
            return {}
        unique_hashes = list(dict.fromkeys(entry.content_hash for entry in entries))
        cached = self.embedding_cache.vectors(profile, unique_hashes)
        missing_hashes = [item for item in unique_hashes if item not in cached]
        if missing_hashes:
            content_by_hash: dict[str, str] = {}
            for entry in entries:
                content_by_hash.setdefault(entry.content_hash, entry.content)
            started = time.perf_counter()
            vectors = self.embeddings.encode(
                [content_by_hash[content_hash] for content_hash in missing_hashes],
                profile,
            )
            elapsed = time.perf_counter() - started
            if len(vectors) != len(missing_hashes):
                raise HouDocsError(
                    "embedding_protocol_error",
                    "Embedding provider returned the wrong vector count.",
                )
            cached.update(
                self.embedding_cache.store(
                    profile, dict(zip(missing_hashes, vectors, strict=True))
                )
            )
            if embedding_progress is not None:
                embedding_progress(len(missing_hashes), elapsed)
        return cached

    @staticmethod
    def _row_to_stored(row: sqlite3.Row) -> _StoredEntry:
        return _StoredEntry(
            entry_id=str(row["entry_id"]),
            namespace=str(row["namespace"]),
            source_id=str(row["source_id"]),
            token_count=(
                int(row["token_count"]) if row["token_count"] is not None else None
            ),
        )
