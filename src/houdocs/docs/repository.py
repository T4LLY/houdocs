from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from houdocs.db.connection import connect
from houdocs.db.schema import ensure_docs_schema
from houdocs.docs.models import Document, DocumentSection
from houdocs.errors import HouDocsError


class DocumentRepository:
    def __init__(self, database: Path) -> None:
        self.database = database
        try:
            with self._connect() as connection:
                ensure_docs_schema(connection)
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to initialize documentation database: {database}",
                detail=str(exc),
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        return connect(self.database)

    def document_for_path(self, relative_path: str) -> Document | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE path = ?",
                (relative_path,),
            ).fetchone()
        return self._document(row) if row else None

    def section_ids_for_document(self, document_id: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM sections WHERE document_id = ? ORDER BY ordinal, id",
                (document_id,),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def sections_for_document(self, document_id: str) -> list[DocumentSection]:
        document = self.document(document_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sections WHERE document_id = ? ORDER BY ordinal, id",
                (document_id,),
            ).fetchall()
        return _sections_from_rows(rows, document.kind, document.relative_path)

    def document(self, document_id: str) -> Document:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            raise HouDocsError("document_not_found", f"Document not found: {document_id}")
        return self._document(row)

    def all_documents(self) -> list[Document]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM documents ORDER BY path").fetchall()
        return [self._document(row) for row in rows]

    def replace_document(
        self,
        document: Document,
        sections: Sequence[DocumentSection],
    ) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO documents(id, path, title, kind, houdini_version, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        path=excluded.path,
                        title=excluded.title,
                        kind=excluded.kind,
                        houdini_version=excluded.houdini_version,
                        content_hash=excluded.content_hash
                    """,
                    (
                        document.document_id,
                        document.relative_path,
                        document.title,
                        document.kind,
                        document.houdini_version,
                        document.content_hash,
                    ),
                )
                connection.execute(
                    "DELETE FROM sections WHERE document_id = ?",
                    (document.document_id,),
                )
                connection.executemany(
                    """
                    INSERT INTO sections(id, document_id, ordinal, anchor, heading, level, text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            section.section_id,
                            section.document_id,
                            section.ordinal,
                            section.anchor,
                            section.heading,
                            section.heading_level,
                            section.text,
                        )
                        for section in sections
                    ],
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to write documentation database: {self.database}",
                detail=str(exc),
            ) from exc

    def delete_document(self, document_id: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
                connection.commit()
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to update documentation database: {self.database}",
                detail=str(exc),
            ) from exc

    @staticmethod
    def _document(row: sqlite3.Row) -> Document:
        return Document(
            document_id=str(row["id"]),
            title=str(row["title"]),
            relative_path=str(row["path"]),
            kind=str(row["kind"]),
            houdini_version=row["houdini_version"],
            content_hash=str(row["content_hash"]),
        )


def _sections_from_rows(
    rows: Sequence[sqlite3.Row],
    kind: str,
    relative_path: str,
) -> list[DocumentSection]:
    stack: list[str | None] = [None] * 6
    sections: list[DocumentSection] = []
    for row in rows:
        heading = row["heading"]
        level = int(row["level"]) if row["level"] is not None else None
        if level is not None and 1 <= level <= len(stack):
            stack[level - 1] = str(heading) if heading else None
            for index in range(level, len(stack)):
                stack[index] = None
            heading_path = tuple(part for part in stack[:level] if part)
        else:
            heading_path = tuple(part for part in stack if part)
        text = str(row["text"])
        section_id = str(row["id"])
        document_id = str(row["document_id"])
        metadata = {
            "kind": kind,
            "document_id": document_id,
            "relative_path": relative_path,
            "ordinal": int(row["ordinal"]),
            "anchor": row["anchor"],
            "heading": heading,
            "heading_path": list(heading_path),
            "heading_level": level,
        }
        sections.append(
            DocumentSection(
                section_id=section_id,
                document_id=document_id,
                ordinal=int(row["ordinal"]),
                anchor=row["anchor"],
                heading=heading,
                heading_path=heading_path,
                heading_level=level,
                kind=kind,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                token_count=_estimate_tokens(text),
                text=text,
                metadata=metadata,
            )
        )
    return sections


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text.encode("utf-8")) + 2) // 3)
