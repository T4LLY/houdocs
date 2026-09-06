from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from houdocs.db.connection import connect
from houdocs.db.schema import ensure_docs_schema
from houdocs.errors import HouDocsError
from houdocs.python_docs.models import PythonDocumentRecord


class PythonRepository:
    def __init__(self, database: Path) -> None:
        self.database = database
        with connect(database) as connection:
            ensure_docs_schema(connection)

    def replace_all(self, records: Sequence[PythonDocumentRecord]) -> None:
        try:
            with connect(self.database) as connection:
                connection.execute("DELETE FROM python_documents")
                connection.executemany(
                    """
                    INSERT INTO python_documents(
                        symbol, document_id, parent_symbol, member_name, kind,
                        signatures_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.symbol,
                            item.document_id,
                            item.parent_symbol,
                            item.member_name,
                            item.kind,
                            json.dumps(list(item.signatures), ensure_ascii=False, separators=(",", ":")),
                            json.dumps(item.metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
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

    def count(self) -> int:
        with connect(self.database) as connection:
            row = connection.execute("SELECT COUNT(*) FROM python_documents").fetchone()
        return int(row[0])
