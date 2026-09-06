from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from houdocs.db.connection import connect
from houdocs.db.schema import ensure_docs_schema
from houdocs.errors import HouDocsError
from houdocs.node.models import (
    NodeParameter,
    NodeParameterDoc,
    NodeParameterLink,
    NodePort,
    NodeRelated,
    NodeTypeDocument,
)

NodeRecord = tuple[
    NodeTypeDocument,
    Sequence[NodeParameter],
    Sequence[NodeParameterDoc],
    Sequence[NodeParameterLink],
    Sequence[NodePort],
    Sequence[NodeRelated],
]


class NodeRepository:
    def __init__(self, database: Path) -> None:
        self.database = database
        try:
            with connect(database) as connection:
                ensure_docs_schema(connection)
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to initialize node documentation index: {database}",
                detail=str(exc),
            ) from exc

    def replace_all(self, records: Sequence[NodeRecord]) -> None:
        try:
            with connect(self.database) as connection:
                connection.execute("DELETE FROM node_documents")
                connection.executemany(
                    """
                    INSERT INTO node_documents(node_type, document_id, houdini_name, metadata_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (
                            node_type.node_type_id,
                            node_type.document_id,
                            node_type.canonical_name or node_type.internal_name,
                            json.dumps(
                                _metadata_payload(
                                    node_type,
                                    parameters,
                                    parameter_docs,
                                    parameter_links,
                                    ports,
                                    related,
                                ),
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                        )
                        for node_type, parameters, parameter_docs, parameter_links, ports, related in records
                    ],
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Unable to write node documentation index: {self.database}",
                detail=str(exc),
            ) from exc

    def resolve(self, node_type: str) -> tuple[str, dict[str, object]] | None:
        key = node_type.strip()
        with connect(self.database) as connection:
            row = connection.execute(
                """
                SELECT document_id, metadata_json
                FROM node_documents
                WHERE lower(node_type) = lower(?) OR lower(houdini_name) = lower(?)
                ORDER BY CAST(json_extract(metadata_json, '$.node_type.priority') AS INTEGER) DESC, node_type
                LIMIT 1
                """,
                (key, key),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise HouDocsError(
                "docs_database_error",
                f"Invalid node metadata JSON for: {node_type}",
                detail=str(exc),
            ) from exc
        if not isinstance(payload, dict):
            raise HouDocsError(
                "docs_database_error",
                f"Invalid node metadata payload for: {node_type}",
            )
        return str(row["document_id"]), payload

    def count(self) -> int:
        with connect(self.database) as connection:
            row = connection.execute("SELECT COUNT(*) FROM node_documents").fetchone()
        return int(row[0])


def _metadata_payload(
    node_type: NodeTypeDocument,
    parameters: Sequence[NodeParameter],
    parameter_docs: Sequence[NodeParameterDoc],
    parameter_links: Sequence[NodeParameterLink],
    ports: Sequence[NodePort],
    related: Sequence[NodeRelated],
) -> dict[str, object]:
    return {
        "node_type": {
            "node_type_id": node_type.node_type_id,
            "document_id": node_type.document_id,
            "context": node_type.context,
            "namespace": node_type.namespace,
            "internal_name": node_type.internal_name,
            "version": node_type.version,
            "category": node_type.category,
            "canonical_name": node_type.canonical_name,
            "priority": node_type.priority,
            "resolution_source": node_type.resolution_source,
            "unresolved_reason": node_type.unresolved_reason,
        },
        "parameters": [
            {
                "parameter_id": item.parameter_id,
                "node_type_id": item.node_type_id,
                "ordinal": item.ordinal,
                "parm_id": item.parm_id,
                "label": item.label,
                "folder_path": list(item.folder_path),
                "parm_type": item.parm_type,
                "multiparm": item.multiparm,
                "runtime_present": item.runtime_present,
            }
            for item in parameters
        ],
        "parameter_docs": [
            {
                "doc_parameter_id": item.doc_parameter_id,
                "node_type_id": item.node_type_id,
                "ordinal": item.ordinal,
                "label": item.label,
                "group_path": list(item.group_path),
                "description": item.description,
                "explicit_ids": list(item.explicit_ids),
                "unresolved_reason": item.unresolved_reason,
            }
            for item in parameter_docs
        ],
        "parameter_links": [
            {
                "doc_parameter_id": item.doc_parameter_id,
                "parameter_id": item.parameter_id,
                "ordinal": item.ordinal,
                "resolution_source": item.resolution_source,
            }
            for item in parameter_links
        ],
        "ports": [
            {
                "node_type_id": item.node_type_id,
                "direction": item.direction,
                "ordinal": item.ordinal,
                "label": item.label,
                "description": item.description,
            }
            for item in ports
        ],
        "related": [
            {
                "node_type_id": item.node_type_id,
                "ordinal": item.ordinal,
                "kind": item.kind,
                "target": item.target,
                "label": item.label,
                "canonical_target": item.canonical_target,
                "resolved": item.resolved,
                "unresolved_reason": item.unresolved_reason,
            }
            for item in related
        ],
    }
