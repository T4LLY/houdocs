from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from houdocs.db.connection import connect
from houdocs.errors import HouDocsError
from houdocs.search.models import SearchEntry


def _table_name(profile: str) -> str:
    digest = hashlib.sha256(profile.encode("utf-8")).hexdigest()[:16]
    return f"search_vec_{digest}"


def _serialize(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).reshape(-1).tobytes()


def load_sqlite_vec(connection: sqlite3.Connection) -> None:
    try:
        import sqlite_vec

        connection.enable_load_extension(True)
        try:
            sqlite_vec.load(connection)
        finally:
            connection.enable_load_extension(False)
    except Exception as exc:
        raise HouDocsError(
            "sqlite_vec_load_failed",
            "Unable to load sqlite-vec.",
            detail=str(exc),
        ) from exc


class SQLiteVecIndex:
    def __init__(self, database: Path) -> None:
        self.database = database

    def _connect(self) -> sqlite3.Connection:
        connection = connect(self.database)
        load_sqlite_vec(connection)
        return connection

    def upsert(
        self,
        profile: str,
        entries: Sequence[SearchEntry],
        vectors_by_hash: Mapping[str, np.ndarray],
    ) -> None:
        if not entries:
            return
        first = vectors_by_hash.get(entries[0].content_hash)
        if first is None:
            raise HouDocsError("embedding_missing", "Expected embedding vector is missing.")
        dimensions = int(np.asarray(first).size)
        table_name = self._ensure_profile(profile, dimensions)
        rows: list[tuple[object, ...]] = []
        for entry in entries:
            vector = vectors_by_hash.get(entry.content_hash)
            if vector is None:
                raise HouDocsError("embedding_missing", "Expected embedding vector is missing.")
            normalized = np.asarray(vector, dtype=np.float32).reshape(-1)
            if len(normalized) != dimensions:
                raise HouDocsError(
                    "embedding_dimension_mismatch",
                    f"Embedding dimensions changed within profile: {profile}",
                )
            rows.append((entry.id, _serialize(normalized), entry.namespace))

        with self._connect() as connection:
            connection.executemany(
                f'DELETE FROM "{table_name}" WHERE entry_id = ?',
                [(entry.id,) for entry in entries],
            )
            connection.executemany(
                f'INSERT INTO "{table_name}"(entry_id, embedding, namespace) VALUES (?, ?, ?)',
                rows,
            )
            connection.commit()

    def remove(self, profile: str, entry_ids: Sequence[str]) -> None:
        if not entry_ids:
            return
        table_name = self._table_for_profile(profile)
        with self._connect() as connection:
            connection.executemany(
                f'DELETE FROM "{table_name}" WHERE entry_id = ?',
                [(entry_id,) for entry_id in entry_ids],
            )
            connection.commit()

    def search(
        self,
        profile: str,
        query_vector: np.ndarray,
        *,
        namespaces: Sequence[str],
        top_k: int,
    ) -> list[str]:
        if top_k <= 0 or not namespaces:
            return []
        table_name = self._table_for_profile(profile)
        namespace_placeholders = ",".join("?" for _ in namespaces)
        sql = f"""
            SELECT entry_id, distance
            FROM "{table_name}"
            WHERE embedding MATCH ? AND k = ?
              AND namespace IN ({namespace_placeholders})
            ORDER BY distance
        """
        params: list[object] = [_serialize(query_vector), top_k, *namespaces]
        try:
            with self._connect() as connection:
                rows = connection.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as exc:
            raise HouDocsError(
                "dense_search_failed",
                "sqlite-vec dense search failed.",
                detail=str(exc),
            ) from exc
        return [str(row["entry_id"]) for row in rows]

    def _ensure_profile(self, profile: str, dimensions: int) -> str:
        table_name = _table_name(profile)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT dimensions, table_name FROM search_vector_profiles WHERE embedding_profile_id = ?",
                (profile,),
            ).fetchone()
            if row is not None:
                if int(row["dimensions"]) != dimensions:
                    raise HouDocsError(
                        "embedding_dimension_mismatch",
                        f"Embedding dimensions changed for profile: {profile}",
                    )
                return str(row["table_name"])
            connection.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS "{table_name}" USING vec0(
                    entry_id TEXT PRIMARY KEY,
                    embedding FLOAT[{dimensions}] distance_metric=cosine,
                    namespace TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO search_vector_profiles(embedding_profile_id, dimensions, table_name) VALUES (?, ?, ?)",
                (profile, dimensions, table_name),
            )
            connection.commit()
        return table_name

    def _table_for_profile(self, profile: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT table_name FROM search_vector_profiles WHERE embedding_profile_id = ?",
                (profile,),
            ).fetchone()
        if row is None:
            raise HouDocsError(
                "dense_profile_missing",
                f"sqlite-vec profile is not indexed: {profile}",
            )
        return str(row["table_name"])
