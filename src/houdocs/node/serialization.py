from __future__ import annotations

import json

from houdocs.errors import HouDocsError
from houdocs.node.models import (
    NodeDocumentRecord,
    NodeParameter,
    NodeParameterDoc,
    NodeParameterLink,
    NodePort,
    NodeRelated,
    NodeTypeDocument,
)


def encode_node_document(record: NodeDocumentRecord) -> str:
    return json.dumps(
        _metadata_payload(record),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_node_document(value: object, *, node_type: str) -> NodeDocumentRecord:
    try:
        payload = json.loads(str(value or "{}"))
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

    try:
        node_type_payload = _object_field(payload, "node_type")
        return NodeDocumentRecord(
            node_type=NodeTypeDocument(
                node_type_id=_string_field(node_type_payload, "node_type_id"),
                document_id=_string_field(node_type_payload, "document_id"),
                context=_string_field(node_type_payload, "context"),
                namespace=_optional_string_field(node_type_payload, "namespace"),
                internal_name=_string_field(node_type_payload, "internal_name"),
                version=_optional_string_field(node_type_payload, "version"),
                category=_optional_string_field(node_type_payload, "category"),
                canonical_name=_optional_string_field(
                    node_type_payload, "canonical_name"
                ),
                priority=_int_field(node_type_payload, "priority"),
                resolution_source=_optional_string_field(
                    node_type_payload, "resolution_source"
                ),
                unresolved_reason=_optional_string_field(
                    node_type_payload, "unresolved_reason"
                ),
            ),
            parameters=tuple(
                NodeParameter(
                    parameter_id=_string_field(item, "parameter_id"),
                    node_type_id=_string_field(item, "node_type_id"),
                    ordinal=_int_field(item, "ordinal"),
                    parm_id=_string_field(item, "parm_id"),
                    label=_string_field(item, "label"),
                    folder_path=_string_tuple_field(item, "folder_path"),
                    parm_type=_optional_string_field(item, "parm_type"),
                    multiparm=_bool_field(item, "multiparm"),
                    runtime_present=_bool_field(item, "runtime_present"),
                )
                for item in _object_list_field(payload, "parameters")
            ),
            parameter_docs=tuple(
                NodeParameterDoc(
                    doc_parameter_id=_string_field(item, "doc_parameter_id"),
                    node_type_id=_string_field(item, "node_type_id"),
                    ordinal=_int_field(item, "ordinal"),
                    label=_string_field(item, "label"),
                    group_path=_string_tuple_field(item, "group_path"),
                    description=_string_field(item, "description"),
                    explicit_ids=_string_tuple_field(item, "explicit_ids"),
                    unresolved_reason=_optional_string_field(
                        item, "unresolved_reason"
                    ),
                )
                for item in _object_list_field(payload, "parameter_docs")
            ),
            parameter_links=tuple(
                NodeParameterLink(
                    doc_parameter_id=_string_field(item, "doc_parameter_id"),
                    parameter_id=_string_field(item, "parameter_id"),
                    ordinal=_int_field(item, "ordinal"),
                    resolution_source=_string_field(item, "resolution_source"),
                )
                for item in _object_list_field(payload, "parameter_links")
            ),
            ports=tuple(
                NodePort(
                    node_type_id=_string_field(item, "node_type_id"),
                    direction=_string_field(item, "direction"),
                    ordinal=_int_field(item, "ordinal"),
                    label=_string_field(item, "label"),
                    description=_string_field(item, "description"),
                )
                for item in _object_list_field(payload, "ports")
            ),
            related=tuple(
                NodeRelated(
                    node_type_id=_string_field(item, "node_type_id"),
                    ordinal=_int_field(item, "ordinal"),
                    kind=_string_field(item, "kind"),
                    target=_string_field(item, "target"),
                    label=_optional_string_field(item, "label"),
                    canonical_target=_optional_string_field(
                        item, "canonical_target"
                    ),
                    resolved=_bool_field(item, "resolved"),
                    unresolved_reason=_optional_string_field(
                        item, "unresolved_reason"
                    ),
                )
                for item in _object_list_field(payload, "related")
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HouDocsError(
            "docs_database_error",
            f"Invalid node metadata payload for: {node_type}",
            detail=str(exc),
        ) from exc


def _metadata_payload(record: NodeDocumentRecord) -> dict[str, object]:
    node_type = record.node_type
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
            for item in record.parameters
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
            for item in record.parameter_docs
        ],
        "parameter_links": [
            {
                "doc_parameter_id": item.doc_parameter_id,
                "parameter_id": item.parameter_id,
                "ordinal": item.ordinal,
                "resolution_source": item.resolution_source,
            }
            for item in record.parameter_links
        ],
        "ports": [
            {
                "node_type_id": item.node_type_id,
                "direction": item.direction,
                "ordinal": item.ordinal,
                "label": item.label,
                "description": item.description,
            }
            for item in record.ports
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
            for item in record.related
        ],
    }


def _object_field(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be an object")
    return value


def _object_list_field(
    payload: dict[str, object], key: str
) -> list[dict[str, object]]:
    value = payload[key]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TypeError(f"{key} must be an array of objects")
    return value


def _string_field(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _optional_string_field(payload: dict[str, object], key: str) -> str | None:
    value = payload[key]
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{key} must be a string or null")
    return value


def _int_field(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if type(value) is not int:
        raise TypeError(f"{key} must be an integer")
    return value


def _bool_field(payload: dict[str, object], key: str) -> bool:
    value = payload[key]
    if type(value) is not bool:
        raise TypeError(f"{key} must be a boolean")
    return value


def _string_tuple_field(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{key} must be an array of strings")
    return tuple(value)
