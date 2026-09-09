from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from houdocs.db.connection import connect_readonly, connect_writable
from houdocs.errors import HouDocsError
from houdocs.python_docs.models import PythonDocumentRecord


class PythonRepository:
    def __init__(self, database: Path) -> None:
        self.database = database

    def insert_all(self, records: Sequence[PythonDocumentRecord]) -> None:
        try:
            with connect_writable(self.database) as connection:
                connection.executemany(
                    """
                    INSERT INTO python_documents(
                        symbol, document_id, parent_symbol, member_name, kind,
                        signatures_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.symbol,
                            item.document_id,
                            item.parent_symbol,
                            item.member_name,
                            item.kind,
                            json.dumps(
                                list(item.signatures),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        )
                        for item in records
                    ],
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to write Python/HOM documentation index: {self.database}",
                detail=str(exc),
            ) from exc

    def get(self, symbol: str) -> PythonDocumentRecord | None:
        with connect_readonly(self.database) as connection:
            row = connection.execute(
                "SELECT * FROM python_documents WHERE lower(symbol) = lower(?)",
                (symbol.strip(),),
            ).fetchone()
        if row is None:
            return None
        return self._record(row)

    def all(self) -> list[PythonDocumentRecord]:
        with connect_readonly(self.database) as connection:
            rows = connection.execute(
                "SELECT * FROM python_documents ORDER BY symbol COLLATE NOCASE, symbol"
            ).fetchall()
        return [self._record(row) for row in rows]

    @staticmethod
    def _record(row: sqlite3.Row) -> PythonDocumentRecord:
        return PythonDocumentRecord(
            symbol=str(row["symbol"]),
            document_id=str(row["document_id"]),
            parent_symbol=row["parent_symbol"],
            member_name=row["member_name"],
            kind=str(row["kind"]),
            signatures=tuple(json.loads(row["signatures_json"] or "[]")),
        )
