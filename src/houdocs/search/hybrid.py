from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from houdocs.db.connection import connect
from houdocs.errors import HouDocsError
from houdocs.search.dense import SQLiteVecIndex
from houdocs.search.embedding import EmbeddingProvider
from houdocs.search.lexical import SQLiteFtsIndex
from houdocs.search.models import SearchEntry, SearchHit
from houdocs.search.rrf import reciprocal_rank_fusion
from houdocs.search.store import ensure_search_schema


_SQLITE_IN_BATCH_SIZE = 500


@dataclass(frozen=True)
class _StoredEntry:
    entry_id: str
    namespace: str
    source_id: str
    content: str
    content_hash: str
    embedding_profile: str
    metadata: dict[str, object]


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
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.embeddings = embeddings
        self.rrf_k = rrf_k
        self.candidate_multiplier = candidate_multiplier
        self.candidate_min = candidate_min
        with self._connect() as connection:
            ensure_search_schema(connection)
        self.lexical = SQLiteFtsIndex(self._connect)
        self.dense = dense_index or SQLiteVecIndex(database)

    def _connect(self) -> sqlite3.Connection:
        return connect(self.database)

    def upsert(
        self,
        entries: Sequence[SearchEntry],
        *,
        embedding_progress: Callable[[int, float], None] | None = None,
    ) -> None:
        if not entries:
            return
        existing_profiles = self._profiles_for_entry_ids([entry.id for entry in entries])
        with self._connect() as connection:
            for entry in entries:
                metadata_json = json.dumps(entry.metadata, ensure_ascii=False, sort_keys=True)
                connection.execute("DELETE FROM search_fts WHERE entry_id = ?", (entry.id,))
                connection.execute(
                    """
                    INSERT INTO search_entries(
                        entry_id, namespace, source_id, content_hash, embedding_profile_id,
                        token_count, is_current, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET
                        namespace=excluded.namespace,
                        source_id=excluded.source_id,
                        content_hash=excluded.content_hash,
                        embedding_profile_id=excluded.embedding_profile_id,
                        token_count=excluded.token_count,
                        is_current=1,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        entry.id,
                        entry.namespace,
                        entry.source_id,
                        entry.content_hash,
                        entry.embedding_profile,
                        entry.token_count,
                        metadata_json,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO search_content(entry_id, content) VALUES (?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET content=excluded.content
                    """,
                    (entry.id, entry.content),
                )
                connection.execute(
                    "INSERT INTO search_fts(entry_id, namespace, content) VALUES (?, ?, ?)",
                    (entry.id, entry.namespace, entry.content),
                )
            connection.commit()

        moved: dict[str, list[str]] = {}
        for entry in entries:
            old_profile = existing_profiles.get(entry.id)
            if old_profile and old_profile != entry.embedding_profile:
                moved.setdefault(old_profile, []).append(entry.id)
        for profile, entry_ids in moved.items():
            self.dense.remove(profile, entry_ids)

        grouped: dict[str, list[SearchEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.embedding_profile, []).append(entry)
        for profile, group in grouped.items():
            vectors = self._ensure_vector_cache(
                profile,
                [self._stored_from_entry(entry) for entry in group],
                embedding_progress=embedding_progress,
            )
            self.dense.upsert(profile, group, vectors)

    def missing_embedding_count(self, entries: Sequence[SearchEntry]) -> int:
        grouped: dict[str, set[str]] = {}
        for entry in entries:
            grouped.setdefault(entry.embedding_profile, set()).add(entry.content_hash)
        missing = 0
        for profile, content_hashes in grouped.items():
            cached = self._cached_hashes(profile, sorted(content_hashes))
            missing += len(content_hashes - cached)
        return missing

    def entry_ids(self, namespace: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT entry_id FROM search_entries WHERE is_current = 1 AND namespace = ? ORDER BY entry_id",
                (namespace,),
            ).fetchall()
        return [str(row["entry_id"]) for row in rows]

    def entry_states(self, namespace: str) -> dict[str, tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT entry_id, content_hash, embedding_profile_id
                FROM search_entries
                WHERE is_current = 1 AND namespace = ?
                """,
                (namespace,),
            ).fetchall()
        return {
            str(row["entry_id"]): (
                str(row["content_hash"]),
                str(row["embedding_profile_id"]),
            )
            for row in rows
        }

    def remove(self, entry_ids: Sequence[str]) -> None:
        if not entry_ids:
            return
        profiles = self._profiles_for_entry_ids(entry_ids)
        grouped: dict[str, list[str]] = {}
        for entry_id, profile in profiles.items():
            grouped.setdefault(profile, []).append(entry_id)
        for profile, ids in grouped.items():
            try:
                self.dense.remove(profile, ids)
            except HouDocsError as exc:
                if exc.error.code != "dense_profile_missing":
                    raise
        with self._connect() as connection:
            for entry_id in entry_ids:
                connection.execute("DELETE FROM search_fts WHERE entry_id = ?", (entry_id,))
                connection.execute("DELETE FROM search_content WHERE entry_id = ?", (entry_id,))
                connection.execute("DELETE FROM search_entries WHERE entry_id = ?", (entry_id,))
            connection.commit()

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
        profile = self._profile_for(namespaces)
        if not profile:
            return []
        lexical = self.lexical.search(query, namespaces=namespaces, limit=candidate_limit)
        query_vectors = self.embeddings.encode([query], profile)
        if len(query_vectors) != 1:
            raise HouDocsError(
                "embedding_protocol_error",
                "Embedding provider returned the wrong query vector count.",
            )
        dense = self.dense.search(
            profile,
            query_vectors[0],
            namespaces=namespaces,
            top_k=candidate_limit,
        )
        scores = reciprocal_rank_fusion([dense, lexical], k=self.rrf_k)
        if not scores:
            return []
        dense_ranks = {entry_id: rank for rank, entry_id in enumerate(dense, start=1)}
        lexical_ranks = {entry_id: rank for rank, entry_id in enumerate(lexical, start=1)}
        by_id = self._load_entries(list(scores))
        ranked = sorted(
            (entry_id for entry_id in scores if entry_id in by_id),
            key=lambda entry_id: (-scores[entry_id], entry_id),
        )[:top_k]
        return [
            SearchHit(
                id=entry_id,
                namespace=by_id[entry_id].namespace,
                source_id=by_id[entry_id].source_id,
                score=scores[entry_id],
                metadata=by_id[entry_id].metadata,
                lexical_rank=lexical_ranks.get(entry_id),
                dense_rank=dense_ranks.get(entry_id),
            )
            for entry_id in ranked
        ]

    def _profile_for(self, namespaces: Sequence[str]) -> str:
        if not namespaces:
            return ""
        placeholders = ",".join("?" for _ in namespaces)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT embedding_profile_id FROM search_entries
                WHERE is_current = 1 AND namespace IN ({placeholders})
                ORDER BY embedding_profile_id LIMIT 1
                """,
                tuple(namespaces),
            ).fetchone()
        return str(row["embedding_profile_id"]) if row is not None else ""

    def _profiles_for_entry_ids(self, entry_ids: Sequence[str]) -> dict[str, str]:
        if not entry_ids:
            return {}
        found: dict[str, str] = {}
        for start in range(0, len(entry_ids), _SQLITE_IN_BATCH_SIZE):
            batch = entry_ids[start : start + _SQLITE_IN_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT entry_id, embedding_profile_id FROM search_entries WHERE entry_id IN ({placeholders})",
                    tuple(batch),
                ).fetchall()
            found.update(
                {str(row["entry_id"]): str(row["embedding_profile_id"]) for row in rows}
            )
        return found

    def _load_entries(self, entry_ids: Sequence[str]) -> dict[str, _StoredEntry]:
        if not entry_ids:
            return {}
        found: dict[str, _StoredEntry] = {}
        for start in range(0, len(entry_ids), _SQLITE_IN_BATCH_SIZE):
            batch = entry_ids[start : start + _SQLITE_IN_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT se.*, sc.content
                    FROM search_entries se JOIN search_content sc ON sc.entry_id = se.entry_id
                    WHERE se.is_current = 1 AND se.entry_id IN ({placeholders})
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

    def _ensure_vector_cache(
        self,
        profile: str,
        entries: Sequence[_StoredEntry],
        *,
        embedding_progress: Callable[[int, float], None] | None = None,
    ) -> dict[str, np.ndarray]:
        if not entries:
            return {}
        unique_hashes = list(dict.fromkeys(entry.content_hash for entry in entries))
        cached = self._vectors_for_hashes(profile, unique_hashes)
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
            with self._connect() as connection:
                for content_hash, vector in zip(missing_hashes, vectors):
                    normalized = np.asarray(vector, dtype=np.float32).reshape(-1)
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO embedding_cache(
                            embedding_profile_id, content_hash, dimensions, vector
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (profile, content_hash, len(normalized), normalized.tobytes()),
                    )
                    cached[content_hash] = normalized.copy()
                connection.commit()
            if embedding_progress is not None:
                embedding_progress(len(missing_hashes), elapsed)
        return cached

    def _cached_hashes(
        self,
        profile: str,
        content_hashes: Sequence[str],
    ) -> set[str]:
        if not content_hashes:
            return set()
        found: set[str] = set()
        for start in range(0, len(content_hashes), _SQLITE_IN_BATCH_SIZE):
            batch = content_hashes[start : start + _SQLITE_IN_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT content_hash FROM embedding_cache
                    WHERE embedding_profile_id = ? AND content_hash IN ({placeholders})
                    """,
                    (profile, *batch),
                ).fetchall()
            found.update(str(row["content_hash"]) for row in rows)
        return found

    def _vectors_for_hashes(
        self,
        profile: str,
        content_hashes: Sequence[str],
    ) -> dict[str, np.ndarray]:
        if not content_hashes:
            return {}
        found: dict[str, np.ndarray] = {}
        for start in range(0, len(content_hashes), _SQLITE_IN_BATCH_SIZE):
            batch = content_hashes[start : start + _SQLITE_IN_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT content_hash, dimensions, vector FROM embedding_cache
                    WHERE embedding_profile_id = ? AND content_hash IN ({placeholders})
                    """,
                    (profile, *batch),
                ).fetchall()
            for row in rows:
                vector = np.frombuffer(row["vector"], dtype=np.float32)
                if len(vector) != int(row["dimensions"]):
                    raise HouDocsError(
                        "embedding_cache_corrupt",
                        "Embedding cache dimensions do not match payload.",
                    )
                found[str(row["content_hash"])] = vector.copy()
        return found

    @staticmethod
    def _stored_from_entry(entry: SearchEntry) -> _StoredEntry:
        return _StoredEntry(
            entry_id=entry.id,
            namespace=entry.namespace,
            source_id=entry.source_id,
            content=entry.content,
            content_hash=entry.content_hash,
            embedding_profile=entry.embedding_profile,
            metadata=dict(entry.metadata),
        )

    @staticmethod
    def _row_to_stored(row: sqlite3.Row) -> _StoredEntry:
        return _StoredEntry(
            entry_id=str(row["entry_id"]),
            namespace=str(row["namespace"]),
            source_id=str(row["source_id"]),
            content=str(row["content"]),
            content_hash=str(row["content_hash"]),
            embedding_profile=str(row["embedding_profile_id"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
