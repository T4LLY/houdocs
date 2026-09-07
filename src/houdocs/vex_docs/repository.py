from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from houdocs.db.connection import connect
from houdocs.db.schema import ensure_docs_schema
from houdocs.errors import HouDocsError
from houdocs.vex_docs.models import VexDocumentRecord


class VexRepository:
    def __init__(self, database: Path) -> None:
        self.database = database
        with connect(database) as connection:
            ensure_docs_schema(connection)

    def replace_all(self, records: Sequence[VexDocumentRecord]) -> None:
        try:
            with connect(self.database) as connection:
                connection.execute("DELETE FROM vex_documents")
                connection.executemany(
                    """
                    INSERT INTO vex_documents(
                        function_name, document_id, signatures_json, contexts_json,
                        group_name, tags_json, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.function_name,
                            item.document_id,
                            json.dumps(list(item.signatures), ensure_ascii=False, separators=(",", ":")),
                            json.dumps(list(item.contexts), ensure_ascii=False, separators=(",", ":")),
                            item.group_name,
                            json.dumps(list(item.tags), ensure_ascii=False, separators=(",", ":")),
                            item.status,
                            json.dumps(item.metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                        )
                        for item in records
                    ],
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to write VEX documentation index: {self.database}",
                detail=str(exc),
            ) from exc


    def get(self, function_name: str) -> VexDocumentRecord | None:
        with connect(self.database) as connection:
            row = connection.execute(
                "SELECT * FROM vex_documents WHERE lower(function_name) = lower(?)",
                (function_name.strip(),),
            ).fetchone()
        if row is None:
            return None
        return self._record(row)

    def all(self) -> list[VexDocumentRecord]:
        with connect(self.database) as connection:
            rows = connection.execute(
                "SELECT * FROM vex_documents ORDER BY function_name COLLATE NOCASE, function_name"
            ).fetchall()
        return [self._record(row) for row in rows]

    def count(self) -> int:
        with connect(self.database) as connection:
            row = connection.execute("SELECT COUNT(*) FROM vex_documents").fetchone()
        return int(row[0])

    @staticmethod
    def _record(row: sqlite3.Row) -> VexDocumentRecord:
        return VexDocumentRecord(
            function_name=str(row["function_name"]),
            document_id=str(row["document_id"]),
            signatures=tuple(json.loads(row["signatures_json"] or "[]")),
            contexts=tuple(json.loads(row["contexts_json"] or "[]")),
            group_name=row["group_name"],
            tags=tuple(json.loads(row["tags_json"] or "[]")),
            status=row["status"],
            metadata=dict(json.loads(row["metadata_json"] or "{}")),
        )
