from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence


def _fts_query(query: str) -> str:
    terms = re.findall(r"[\w:]+", query, flags=re.UNICODE)
    if not terms:
        return '"' + query.replace('"', '""') + '"'
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


class SQLiteFtsIndex:
    def __init__(self, connection_factory) -> None:
        self._connection_factory = connection_factory

    def search(
        self,
        query: str,
        *,
        namespaces: Sequence[str],
        limit: int,
    ) -> list[str]:
        if not query.strip() or not namespaces or limit <= 0:
            return []
        placeholders = ",".join("?" for _ in namespaces)
        sql = f"""
            SELECT search_fts.entry_id, bm25(search_fts) AS score
            FROM search_fts
            JOIN search_entries se ON se.entry_id = search_fts.entry_id
            WHERE search_fts MATCH ?
              AND search_fts.namespace IN ({placeholders})
              AND se.is_current = 1
            ORDER BY score ASC
            LIMIT ?
        """
        params: list[object] = [_fts_query(query), *namespaces, limit]
        try:
            with self._connection_factory() as connection:
                rows = connection.execute(sql, tuple(params)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [str(row["entry_id"]) for row in rows]
