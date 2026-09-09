from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from itertools import groupby
from pathlib import Path

from houdocs.db.connection import connect_readonly, connect_writable
from houdocs.docs.models import Document, DocumentSection
from houdocs.errors import HouDocsError


_SECTION_SELECT = """
    d.id AS source_document_id,
    d.kind AS source_kind,
    s.id AS section_id,
    s.document_id AS section_document_id,
    s.ordinal AS section_ordinal,
    s.anchor AS section_anchor,
    s.heading AS section_heading,
    s.level AS section_level,
    s.token_count AS section_token_count,
    s.text AS section_text
"""


class DocumentRepository:
    def __init__(self, database: Path) -> None:
        self.database = database

    def _read(self) -> sqlite3.Connection:
        return connect_readonly(self.database)

    def _write(self) -> sqlite3.Connection:
        return connect_writable(self.database)

    def sections_for_document(self, document_id: str) -> list[DocumentSection]:
        with self._read() as connection:
            rows = connection.execute(
                f"""
                SELECT {_SECTION_SELECT}
                FROM documents AS d
                LEFT JOIN sections AS s ON s.document_id = d.id
                WHERE d.id = ?
                ORDER BY s.ordinal, s.id
                """,
                (document_id,),
            ).fetchall()
        if not rows:
            raise HouDocsError("document_not_found", f"Document not found: {document_id}")
        return _sections_from_joined_rows(rows)


    def documents_for_title(self, title: str) -> list[Document]:
        with self._read() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE title = ? COLLATE NOCASE ORDER BY path",
                (title.strip(),),
            ).fetchall()
        return [self._document(row) for row in rows]

    def section(self, section_id: str) -> DocumentSection:
        with self._read() as connection:
            rows = connection.execute(
                f"""
                WITH target AS (
                    SELECT document_id
                    FROM sections
                    WHERE id = ?
                )
                SELECT {_SECTION_SELECT}
                FROM target
                JOIN documents AS d ON d.id = target.document_id
                JOIN sections AS s ON s.document_id = d.id
                ORDER BY s.ordinal, s.id
                """,
                (section_id,),
            ).fetchall()
        for section in _sections_from_joined_rows(rows):
            if section.section_id == section_id:
                return section
        raise HouDocsError("document_section_not_found", f"Section not found: {section_id}")

    def sections_matching(self, document_id: str, section_name: str) -> list[DocumentSection]:
        key = section_name.casefold().strip().lstrip('#')
        sections = self.sections_for_document(document_id)
        matches = [
            section
            for section in sections
            if key
            in {
                str(section.anchor or "").casefold().strip().strip("/"),
                str(section.heading or "").casefold().strip().strip("/"),
                "/".join(section.heading_path).casefold().strip().strip("/"),
                "/".join(section.heading_path[1:]).casefold().strip().strip("/"),
            }
        ]
        return matches

    def all_sections(self) -> list[DocumentSection]:
        with self._read() as connection:
            rows = connection.execute(
                f"""
                SELECT {_SECTION_SELECT}
                FROM sections AS s
                JOIN documents AS d ON d.id = s.document_id
                ORDER BY d.path, s.ordinal, s.id
                """
            ).fetchall()
        return _sections_from_joined_rows(rows)

    def document(self, document_id: str) -> Document:
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            raise HouDocsError("document_not_found", f"Document not found: {document_id}")
        return self._document(row)

    def all_documents(self) -> list[Document]:
        with self._read() as connection:
            rows = connection.execute("SELECT * FROM documents ORDER BY path").fetchall()
        return [self._document(row) for row in rows]

    def insert_document(
        self,
        document: Document,
        sections: Sequence[DocumentSection],
    ) -> None:
        try:
            with self._write() as connection:
                connection.execute(
                    """
                    INSERT INTO documents(id, path, title, kind, houdini_version)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document.document_id,
                        document.relative_path,
                        document.title,
                        document.kind,
                        document.houdini_version,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO sections(
                        id, document_id, ordinal, anchor, heading, level, token_count, text
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            section.section_id,
                            section.document_id,
                            section.ordinal,
                            section.anchor,
                            section.heading,
                            section.heading_level,
                            section.token_count,
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

    @staticmethod
    def _document(row: sqlite3.Row) -> Document:
        return Document(
            document_id=str(row["id"]),
            title=str(row["title"]),
            relative_path=str(row["path"]),
            kind=str(row["kind"]),
            houdini_version=row["houdini_version"],
        )


def _sections_from_joined_rows(rows: Sequence[sqlite3.Row]) -> list[DocumentSection]:
    sections: list[DocumentSection] = []
    for _document_id, document_rows in groupby(
        rows, key=lambda row: str(row["source_document_id"])
    ):
        stack: list[str | None] = [None] * 6
        for row in document_rows:
            if row["section_id"] is None:
                continue
            heading = row["section_heading"]
            level = (
                int(row["section_level"])
                if row["section_level"] is not None
                else None
            )
            if level is not None and 1 <= level <= len(stack):
                stack[level - 1] = str(heading) if heading else None
                for index in range(level, len(stack)):
                    stack[index] = None
                heading_path = tuple(part for part in stack[:level] if part)
            else:
                heading_path = tuple(part for part in stack if part)
            text = str(row["section_text"])
            section_id = str(row["section_id"])
            document_id = str(row["section_document_id"])
            kind = str(row["source_kind"])
            sections.append(
                DocumentSection(
                    section_id=section_id,
                    document_id=document_id,
                    ordinal=int(row["section_ordinal"]),
                    anchor=row["section_anchor"],
                    heading=heading,
                    heading_path=heading_path,
                    heading_level=level,
                    kind=kind,
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    token_count=int(row["section_token_count"]),
                    text=text,
                )
            )
    return sections
