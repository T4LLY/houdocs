from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from houdocs.db.connection import connect_readonly, connect_writable
from houdocs.errors import HouDocsError
from houdocs.node.models import NodeDocumentRecord, ResolvedNodeDocument
from houdocs.node.serialization import decode_node_document, encode_node_document


class NodeRepository:
    def __init__(self, database: Path) -> None:
        self.database = database

    def replace_all(self, records: Sequence[NodeDocumentRecord]) -> None:
        try:
            with connect_writable(self.database) as connection:
                connection.execute("DELETE FROM node_documents")
                connection.executemany(
                    """
                    INSERT INTO node_documents(node_type, document_id, houdini_name, metadata_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (
                            record.node_type.node_type_id,
                            record.node_type.document_id,
                            record.node_type.canonical_name or record.node_type.internal_name,
                            encode_node_document(record),
                        )
                        for record in records
                    ],
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to write node documentation index: {self.database}",
                detail=str(exc),
            ) from exc

    def apply_parameter_overrides(self, overrides: Sequence[dict[str, object]]) -> int:
        """Apply saved assist mappings without re-indexing node documentation."""
        try:
            with connect_writable(self.database) as connection:
                seen: set[tuple[str, int]] = set()
                for override in overrides:
                    document, doc_ordinal, parm_ids = _parameter_override_fields(
                        override
                    )
                    key = (document, doc_ordinal)
                    if key in seen:
                        raise HouDocsError(
                            "node_assist_invalid",
                            f"Node assist report has duplicate parameter override: {document}#{doc_ordinal}",
                        )
                    seen.add(key)

                    rows = connection.execute(
                        """
                        SELECT node_documents.node_type, node_documents.metadata_json
                        FROM node_documents
                        JOIN documents ON documents.id = node_documents.document_id
                        WHERE documents.path = ?
                        """,
                        (document,),
                    ).fetchall()
                    if not rows:
                        raise HouDocsError(
                            "node_assist_target_missing",
                            f"Node assist override document is not indexed: {document}",
                        )

                    for row in rows:
                        payload = _metadata_for_override(row["metadata_json"], document)
                        _apply_parameter_override(
                            payload, document, doc_ordinal, parm_ids
                        )
                        connection.execute(
                            "UPDATE node_documents SET metadata_json = ? WHERE node_type = ?",
                            (
                                json.dumps(
                                    payload,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                    sort_keys=True,
                                ),
                                row["node_type"],
                            ),
                        )
                connection.commit()
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to update node documentation index: {self.database}",
                detail=str(exc),
            ) from exc
        return len(overrides)

    def resolve(self, node_type: str) -> ResolvedNodeDocument | None:
        key = node_type.strip()
        with connect_readonly(self.database) as connection:
            row = connection.execute(
                """
                SELECT document_id, metadata_json
                FROM node_documents
                WHERE lower(node_type) = lower(?)
                   OR lower(houdini_name) = lower(?)
                   OR lower(json_extract(metadata_json, '$.node_type.internal_name')) = lower(?)
                ORDER BY CAST(json_extract(metadata_json, '$.node_type.priority') AS INTEGER) DESC, node_type
                LIMIT 1
                """,
                (key, key, key),
            ).fetchone()
        if row is None:
            return None
        document_id = str(row["document_id"])
        record = decode_node_document(row["metadata_json"], node_type=node_type)
        if record.node_type.document_id != document_id:
            raise HouDocsError(
                "docs_database_error",
                f"Node metadata document ID does not match index row for: {node_type}",
            )
        return ResolvedNodeDocument(document_id=document_id, record=record)

    def count(self) -> int:
        with connect_readonly(self.database) as connection:
            row = connection.execute("SELECT COUNT(*) FROM node_documents").fetchone()
        return int(row[0])


def _parameter_override_fields(
    override: dict[str, object],
) -> tuple[str, int, list[str]]:
    document = override.get("document")
    ordinal = override.get("doc_ordinal")
    parm_ids = override.get("parm_ids")
    if (
        not isinstance(document, str)
        or not document
        or not isinstance(ordinal, int)
        or isinstance(ordinal, bool)
        or not isinstance(parm_ids, list)
        or not parm_ids
        or any(not isinstance(parm_id, str) or not parm_id for parm_id in parm_ids)
    ):
        raise HouDocsError(
            "node_assist_invalid", "Node assist parameter override is invalid."
        )
    if len(set(parm_ids)) != len(parm_ids):
        raise HouDocsError(
            "node_assist_invalid", "Node assist parameter override has duplicate IDs."
        )
    return document, ordinal, list(parm_ids)


def _metadata_for_override(value: object, document: str) -> dict[str, object]:
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise HouDocsError(
            "docs_database_error",
            f"Invalid node metadata JSON for assist override: {document}",
            detail=str(exc),
        ) from exc
    if not isinstance(payload, dict):
        raise HouDocsError(
            "docs_database_error",
            f"Invalid node metadata payload for assist override: {document}",
        )
    return payload


def _apply_parameter_override(
    payload: dict[str, object],
    document: str,
    doc_ordinal: int,
    parm_ids: list[str],
) -> None:
    parameter_docs = payload.get("parameter_docs")
    parameters = payload.get("parameters")
    parameter_links = payload.get("parameter_links")
    if (
        not isinstance(parameter_docs, list)
        or not isinstance(parameters, list)
        or not isinstance(parameter_links, list)
    ):
        raise HouDocsError(
            "docs_database_error",
            f"Invalid node metadata payload for assist override: {document}",
        )

    matching_docs = [
        item
        for item in parameter_docs
        if isinstance(item, dict) and item.get("ordinal") == doc_ordinal
    ]
    if len(matching_docs) != 1:
        raise HouDocsError(
            "node_assist_target_missing",
            f"Node assist override parameter is not indexed: {document}#{doc_ordinal}",
        )
    doc_parameter_id = matching_docs[0].get("doc_parameter_id")
    if not isinstance(doc_parameter_id, str) or not doc_parameter_id:
        raise HouDocsError(
            "docs_database_error",
            f"Invalid node metadata payload for assist override: {document}",
        )

    parameter_ids = {
        item.get("parm_id"): item.get("parameter_id")
        for item in parameters
        if isinstance(item, dict)
        and isinstance(item.get("parm_id"), str)
        and isinstance(item.get("parameter_id"), str)
    }
    missing = [parm_id for parm_id in parm_ids if parm_id not in parameter_ids]
    if missing:
        raise HouDocsError(
            "node_assist_target_missing",
            "Node assist override parameter IDs are not indexed: " + ", ".join(missing),
        )

    matching_docs[0]["unresolved_reason"] = None
    payload["parameter_links"] = [
        item
        for item in parameter_links
        if not (
            isinstance(item, dict) and item.get("doc_parameter_id") == doc_parameter_id
        )
    ] + [
        {
            "doc_parameter_id": doc_parameter_id,
            "parameter_id": parameter_ids[parm_id],
            "ordinal": ordinal,
            "resolution_source": "manual",
        }
        for ordinal, parm_id in enumerate(parm_ids)
    ]
