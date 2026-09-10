from __future__ import annotations

import hashlib
from pathlib import Path

from houdocs.node.catalog import NodeTypeCatalog
from houdocs.node.models import (
    NodeDocSource,
    NodeDocumentRecord,
    NodeResolutionResult,
    NodeTypeDocument,
)
from houdocs.node.parameter_resolution import resolve_parameters
from houdocs.node.parser import node_type_lookup, strict_node_lookup
from houdocs.node.port_resolution import resolve_ports
from houdocs.node.related_resolution import resolve_related


def _node_document_priority(
    relative_path: str, node_doc: NodeDocSource, runtime_resolved: bool
) -> int:
    stem = Path(relative_path).stem.casefold()
    expected_name = node_doc.internal_name or ""
    if node_doc.namespace:
        expected_name = f"{node_doc.namespace}::{expected_name}"
    expected = expected_name.replace("::", "--").casefold()
    score = 1000 if runtime_resolved else 0
    if stem == expected:
        score += 100
    if node_doc.version_source == "explicit":
        score += 10
    elif node_doc.version_source == "filename":
        score += 5
    if stem.endswith("-"):
        score -= 20
    return score


def build_node_metadata(
    *,
    document_id: str,
    relative_path: str,
    node_doc: NodeDocSource,
    catalog: NodeTypeCatalog,
    overrides: dict[str, list[dict[str, object]]],
) -> NodeResolutionResult:
    context = node_doc.context or ""
    internal_name = node_doc.internal_name or ""
    lookup = strict_node_lookup(relative_path, node_doc)
    runtime = catalog.resolve(lookup) if lookup is not None else None
    if runtime is not None:
        context = lookup.context
        internal_name = runtime.internal_name
        canonical_name = runtime.canonical_name
    elif node_doc.context and node_doc.internal_name:
        lookup = node_type_lookup(node_doc)
        canonical_name = catalog.canonical_for(lookup)
    else:
        canonical_name = None
    if runtime is not None:
        category = runtime.category
        resolution_source = "houdini"
        node_reason = None
    elif canonical_name is not None:
        category = canonical_name.split("/", 1)[0]
        resolution_source = "bookish"
        node_reason = None
    else:
        category = None
        resolution_source = None
        node_reason = (
            "missing_context_or_internal"
            if not context or not internal_name
            else "unknown_context"
        )

    lookup_internal = lookup.internal_name if lookup is not None else internal_name
    node_type_id = hashlib.sha256(
        f"{document_id}|{context}|{lookup_internal}".encode("utf-8")
    ).hexdigest()[:32]
    node_type = NodeTypeDocument(
        node_type_id=node_type_id,
        document_id=document_id,
        context=context,
        namespace=node_doc.namespace,
        internal_name=internal_name,
        version=node_doc.version,
        category=category,
        canonical_name=canonical_name,
        priority=_node_document_priority(relative_path, node_doc, runtime is not None),
        resolution_source=resolution_source,
        unresolved_reason=node_reason,
    )

    (
        parameter_rows,
        parameter_docs,
        parameter_links,
        parameter_counts,
        parameter_unresolved,
    ) = resolve_parameters(
        node_type_id=node_type_id,
        relative_path=relative_path,
        canonical_name=canonical_name,
        documented=node_doc.parameters,
        runtime=runtime,
        overrides=overrides.get("parameters", []),
    )
    related_rows, related_counts, related_unresolved = resolve_related(
        node_type_id=node_type_id,
        relative_path=relative_path,
        canonical_name=canonical_name,
        related=node_doc.related,
        catalog=catalog,
        overrides=overrides.get("related", []),
    )
    ports = resolve_ports(
        node_type_id=node_type_id,
        runtime=runtime,
        inputs=node_doc.inputs,
        outputs=node_doc.outputs,
    )

    counts = {
        **parameter_counts,
        **related_counts,
        "node_type_total": 1,
        "node_type_resolved": 0 if node_reason else 1,
        "node_type_unresolved": 1 if node_reason else 0,
    }
    unresolved = {
        "node_types": []
        if node_reason is None
        else [
            {
                "document": relative_path,
                "context": context or None,
                "namespace": node_doc.namespace,
                "internal_name": internal_name or None,
                "version": node_doc.version,
                "reason": node_reason,
            }
        ],
        "parameters": parameter_unresolved,
        "related": related_unresolved,
    }
    return NodeResolutionResult(
        record=NodeDocumentRecord(
            node_type=node_type,
            parameters=tuple(parameter_rows),
            parameter_docs=tuple(parameter_docs),
            parameter_links=tuple(parameter_links),
            ports=tuple(ports),
            related=tuple(related_rows),
        ),
        counts=counts,
        unresolved=unresolved,
    )
