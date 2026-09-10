from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from houdocs.db.connection import connect_readonly, connect_writable
from houdocs.errors import HouDocsError


_SQLITE_IN_BATCH_SIZE = 500


class EmbeddingCache:
    def __init__(self, database: Path) -> None:
        self.database = database

    def missing_count(self, profile: str, content_hashes: Sequence[str]) -> int:
        unique_hashes = set(content_hashes)
        if not unique_hashes:
            return 0
        return len(unique_hashes - self._cached_hashes(profile, sorted(unique_hashes)))

    def vectors(
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
            with connect_readonly(self.database) as connection:
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

    def store(
        self,
        profile: str,
        vectors_by_hash: Mapping[str, np.ndarray],
    ) -> dict[str, np.ndarray]:
        if not vectors_by_hash:
            return {}
        normalized: dict[str, np.ndarray] = {}
        with connect_writable(self.database) as connection:
            for content_hash, vector in vectors_by_hash.items():
                value = np.asarray(vector, dtype=np.float32).reshape(-1)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO embedding_cache(
                        embedding_profile_id, content_hash, dimensions, vector
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (profile, content_hash, len(value), value.tobytes()),
                )
                normalized[content_hash] = value.copy()
            connection.commit()
        return normalized

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
            with connect_readonly(self.database) as connection:
                rows = connection.execute(
                    f"""
                    SELECT content_hash FROM embedding_cache
                    WHERE embedding_profile_id = ? AND content_hash IN ({placeholders})
                    """,
                    (profile, *batch),
                ).fetchall()
            found.update(str(row["content_hash"]) for row in rows)
        return found
