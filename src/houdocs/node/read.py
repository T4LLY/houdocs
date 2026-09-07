from __future__ import annotations

from collections.abc import Callable

from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.node.repository import NodeRepository

TokenCounter = Callable[[str], int]
_DETAIL_KINDS = {"parameters", "inputs", "outputs"}


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


def _split_target(value: str) -> tuple[str, str | None, str | None]:
    parts = value.strip().split("/", 3)
    if len(parts) == 4 and parts[2].casefold() in _DETAIL_KINDS and parts[3]:
        return "/".join(parts[:2]), parts[2].casefold(), parts[3]
    return value.strip(), None, None


class NodeReader:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        repository: NodeRepository,
        token_counter: TokenCounter,
    ) -> None:
        self.documents = documents
        self.repository = repository
        self.token_counter = token_counter

    def read(self, target: str) -> dict[str, object]:
        node_type, detail_kind, detail_key = _split_target(target)
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

        parameter_docs = [
            raw for raw in metadata.get("parameter_docs", []) if isinstance(raw, dict)
        ]

        if detail_kind == "parameters" and detail_key is not None:
            return self._parameter_detail(
                node_type,
                detail_key,
                parameter_docs,
                links_by_doc,
                runtime_by_id,
            )
        if detail_kind in {"inputs", "outputs"} and detail_key is not None:
            direction = "input" if detail_kind == "inputs" else "output"
            return self._port_detail(node_type, detail_kind, detail_key, metadata, direction)

        parameters: list[dict[str, object]] = []
        for raw in parameter_docs:
            description = str(raw.get("description") or "")
            tokens = self.token_counter(description)
            runtime_items = self._resolved_runtime_items(raw, links_by_doc, runtime_by_id)
            if runtime_items:
                for runtime in runtime_items:
                    parm_id = str(runtime.get("parm_id") or "").strip()
                    parameter: dict[str, object] = {
                        "id": parm_id,
                        "label": raw.get("label"),
                        "tokens": tokens,
                    }
                    parm_type = _short_parameter_type(runtime.get("parm_type"))
                    if parm_type is not None:
                        parameter["type"] = parm_type
                    if bool(runtime.get("multiparm")):
                        parameter["multiparm"] = True
                    parameters.append(parameter)
                continue

            ordinal = raw.get("ordinal")
            if isinstance(ordinal, int):
                parameters.append(
                    {
                        "ordinal": ordinal,
                        "label": raw.get("label"),
                        "tokens": tokens,
                    }
                )

        def ports(direction: str) -> list[dict[str, object]]:
            values = self._ports(metadata, direction)
            return [
                {
                    "label": item.get("label"),
                    "tokens": self.token_counter(str(item.get("description") or "")),
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

    def _resolved_runtime_items(
        self,
        raw: dict[str, object],
        links_by_doc: dict[str, list[dict[str, object]]],
        runtime_by_id: dict[str, dict[str, object]],
    ) -> list[dict[str, object]]:
        links = sorted(
            links_by_doc.get(str(raw.get("doc_parameter_id")), []),
            key=lambda item: int(item.get("ordinal") or 0),
        )
        result: list[dict[str, object]] = []
        for link in links:
            runtime = runtime_by_id.get(str(link.get("parameter_id")))
            if not isinstance(runtime, dict) or not bool(runtime.get("runtime_present")):
                continue
            parm_id = str(runtime.get("parm_id") or "").strip()
            if parm_id:
                result.append(runtime)
        return result

    def _parameter_detail(
        self,
        node_type: str,
        key: str,
        parameter_docs: list[dict[str, object]],
        links_by_doc: dict[str, list[dict[str, object]]],
        runtime_by_id: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        unresolved_by_ordinal: dict[int, dict[str, object]] = {}
        for raw in parameter_docs:
            runtime_items = self._resolved_runtime_items(raw, links_by_doc, runtime_by_id)
            for runtime in runtime_items:
                if str(runtime.get("parm_id") or "") == key:
                    return {"description": str(raw.get("description") or "")}
            if not runtime_items:
                ordinal = raw.get("ordinal")
                if isinstance(ordinal, int):
                    unresolved_by_ordinal[ordinal] = raw

        try:
            ordinal_key = int(key)
        except ValueError:
            ordinal_key = None
        if ordinal_key is not None and ordinal_key in unresolved_by_ordinal:
            raw = unresolved_by_ordinal[ordinal_key]
            return {"description": str(raw.get("description") or "")}

        raise HouDocsError(
            "node_parameter_not_found",
            f"Node parameter documentation not found: {node_type}/parameters/{key}",
        )

    def _port_detail(
        self,
        node_type: str,
        detail_kind: str,
        key: str,
        metadata: dict[str, object],
        direction: str,
    ) -> dict[str, object]:
        try:
            index = int(key)
        except ValueError:
            index = -1
        values = self._ports(metadata, direction)
        if 0 <= index < len(values):
            return {"description": str(values[index].get("description") or "")}
        raise HouDocsError(
            "node_port_not_found",
            f"Node port documentation not found: {node_type}/{detail_kind}/{key}",
        )

    @staticmethod
    def _ports(metadata: dict[str, object], direction: str) -> list[dict[str, object]]:
        values = [
            item
            for item in metadata.get("ports", [])
            if isinstance(item, dict) and item.get("direction") == direction
        ]
        values.sort(key=lambda item: int(item.get("ordinal") or 0))
        return values
