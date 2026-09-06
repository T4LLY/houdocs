from __future__ import annotations

from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.node.repository import NodeRepository


class NodeReader:
    def __init__(self, *, documents: DocumentRepository, repository: NodeRepository) -> None:
        self.documents = documents
        self.repository = repository
        self.document_reader = DocumentReader(documents)

    def read(self, node_type: str) -> dict[str, object]:
        record = self.repository.resolve(node_type)
        if record is None:
            raise HouDocsError(
                "node_document_not_found",
                f"Node documentation not found: {node_type}",
            )
        document_id, metadata = record
        document = self.documents.document(document_id)
        node = dict(metadata.get("node_type") or {})
        runtime_by_id = {
            str(item.get("parameter_id")): item
            for item in metadata.get("parameters", [])
            if isinstance(item, dict)
        }
        links_by_doc: dict[str, list[dict[str, object]]] = {}
        for raw in metadata.get("parameter_links", []):
            if isinstance(raw, dict):
                links_by_doc.setdefault(str(raw.get("doc_parameter_id")), []).append(raw)

        parameters: list[dict[str, object]] = []
        for raw in metadata.get("parameter_docs", []):
            if not isinstance(raw, dict):
                continue
            links = sorted(
                links_by_doc.get(str(raw.get("doc_parameter_id")), []),
                key=lambda item: int(item.get("ordinal") or 0),
            )
            runtime_parameters: list[dict[str, object]] = []
            for link in links:
                runtime = runtime_by_id.get(str(link.get("parameter_id")))
                if not isinstance(runtime, dict):
                    continue
                runtime_parameters.append(
                    {
                        "id": runtime.get("parm_id"),
                        "label": runtime.get("label"),
                        "folder_path": list(runtime.get("folder_path") or []),
                        "type": runtime.get("parm_type"),
                        "multiparm": bool(runtime.get("multiparm")),
                        "runtime_present": bool(runtime.get("runtime_present")),
                        "resolution_source": link.get("resolution_source"),
                    }
                )
            parameters.append(
                {
                    "id": runtime_parameters[0]["id"] if len(runtime_parameters) == 1 else None,
                    "ids": [item["id"] for item in runtime_parameters],
                    "label": raw.get("label"),
                    "group_path": list(raw.get("group_path") or []),
                    "description": raw.get("description") or "",
                    "explicit_ids": list(raw.get("explicit_ids") or []),
                    "resolved": bool(runtime_parameters) and raw.get("unresolved_reason") is None,
                    "unresolved_reason": raw.get("unresolved_reason"),
                    "runtime_parameters": runtime_parameters,
                }
            )

        def ports(direction: str) -> list[dict[str, object]]:
            values = [
                item for item in metadata.get("ports", [])
                if isinstance(item, dict) and item.get("direction") == direction
            ]
            values.sort(key=lambda item: int(item.get("ordinal") or 0))
            return [
                {
                    "index": item.get("ordinal"),
                    "label": item.get("label"),
                    "description": item.get("description") or "",
                }
                for item in values
            ]

        related = [
            {
                "kind": item.get("kind"),
                "target": item.get("target"),
                "label": item.get("label"),
                "canonical_target": item.get("canonical_target"),
                "resolved": bool(item.get("resolved")),
                "unresolved_reason": item.get("unresolved_reason"),
            }
            for item in metadata.get("related", [])
            if isinstance(item, dict)
        ]
        page = self.document_reader.page(document)
        return {
            "node_type": node.get("canonical_name") or node_type,
            "document": document.title,
            "relative_path": document.relative_path,
            "houdini_version": document.houdini_version,
            "context": node.get("context"),
            "namespace": node.get("namespace"),
            "internal_name": node.get("internal_name"),
            "version": node.get("version"),
            "category": node.get("category"),
            "inputs": ports("input"),
            "outputs": ports("output"),
            "parameters": parameters,
            "related": related,
            "text": page["text"],
        }
