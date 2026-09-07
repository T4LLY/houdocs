from __future__ import annotations

from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.node.repository import NodeRepository


def _short_parameter_type(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.rsplit(".", 1)[-1]


def _related_target(item: dict[str, object]) -> str | None:
    target = str(item.get("canonical_target") or "").strip()
    if not target:
        return None
    if item.get("kind") == "node" and "/" in target:
        context, remainder = target.split("/", 1)
        return f"{context.lower()}/{remainder}"
    return target


class NodeReader:
    def __init__(self, *, documents: DocumentRepository, repository: NodeRepository) -> None:
        self.documents = documents
        self.repository = repository

    def read(self, node_type: str) -> dict[str, object]:
        record = self.repository.resolve(node_type)
        if record is None:
            raise HouDocsError(
                "node_document_not_found",
                f"Node documentation not found: {node_type}",
            )
        document_id, metadata = record
        self.documents.document(document_id)

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
            if not isinstance(raw, dict) or raw.get("unresolved_reason") is not None:
                continue
            links = sorted(
                links_by_doc.get(str(raw.get("doc_parameter_id")), []),
                key=lambda item: int(item.get("ordinal") or 0),
            )
            for link in links:
                runtime = runtime_by_id.get(str(link.get("parameter_id")))
                if not isinstance(runtime, dict) or not bool(runtime.get("runtime_present")):
                    continue
                parm_id = str(runtime.get("parm_id") or "").strip()
                if not parm_id:
                    continue
                parameter: dict[str, object] = {
                    "id": parm_id,
                    "label": raw.get("label"),
                    "description": raw.get("description") or "",
                }
                parm_type = _short_parameter_type(runtime.get("parm_type"))
                if parm_type is not None:
                    parameter["type"] = parm_type
                if bool(runtime.get("multiparm")):
                    parameter["multiparm"] = True
                parameters.append(parameter)

        def ports(direction: str) -> list[dict[str, object]]:
            values = [
                item for item in metadata.get("ports", [])
                if isinstance(item, dict) and item.get("direction") == direction
            ]
            values.sort(key=lambda item: int(item.get("ordinal") or 0))
            return [
                {
                    "label": item.get("label"),
                    "description": item.get("description") or "",
                }
                for item in values
            ]

        related = [
            target
            for item in metadata.get("related", [])
            if isinstance(item, dict)
            for target in [_related_target(item)]
            if target is not None
        ]

        result: dict[str, object] = {}
        inputs = ports("input")
        outputs = ports("output")
        if inputs:
            result["inputs"] = inputs
        if outputs:
            result["outputs"] = outputs
        if parameters:
            result["parameters"] = parameters
        if related:
            result["related"] = related
        return result
