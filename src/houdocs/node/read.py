from __future__ import annotations

from collections.abc import Callable, Sequence

from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.node.models import (
    NodeDocumentRecord,
    NodeParameter,
    NodeParameterDoc,
    NodeParameterLink,
    NodePort,
    NodeRelated,
)
from houdocs.node.repository import NodeRepository

TokenCounter = Callable[[str], int]
_DETAIL_KINDS = {"parameters", "inputs", "outputs"}


def _short_parameter_type(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    return text.rsplit(".", 1)[-1]


def _related_target(item: NodeRelated) -> str | None:
    target = (item.canonical_target or "").strip()
    if not target:
        return None
    if item.kind == "node" and "/" in target:
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
        resolved = self.repository.resolve(node_type)
        if resolved is None:
            raise HouDocsError(
                "node_document_not_found",
                f"Node documentation not found: {node_type}",
            )
        self.documents.document(resolved.document_id)
        record = resolved.record

        runtime_parameters = sorted(
            (item for item in record.parameters if item.runtime_present),
            key=lambda item: (item.ordinal, item.parm_id),
        )
        runtime_by_id = {item.parameter_id: item for item in record.parameters}
        links_by_doc: dict[str, list[NodeParameterLink]] = {}
        for link in record.parameter_links:
            links_by_doc.setdefault(link.doc_parameter_id, []).append(link)

        descriptions_by_parameter = self._runtime_parameter_descriptions(
            record.parameter_docs,
            links_by_doc,
            runtime_by_id,
        )

        if detail_kind == "parameters" and detail_key is not None:
            return self._parameter_detail(
                node_type,
                detail_key,
                runtime_parameters,
                record.parameter_docs,
                links_by_doc,
                runtime_by_id,
                descriptions_by_parameter,
            )
        if detail_kind in {"inputs", "outputs"} and detail_key is not None:
            direction = "input" if detail_kind == "inputs" else "output"
            return self._port_detail(
                node_type,
                detail_kind,
                detail_key,
                record,
                direction,
            )

        parameters: list[dict[str, object]] = []
        for runtime in runtime_parameters:
            parm_id = runtime.parm_id.strip()
            if not parm_id:
                continue
            description = descriptions_by_parameter.get(runtime.parameter_id, "")
            parameter: dict[str, object] = {
                "id": parm_id,
                "label": runtime.label,
                "tokens": self.token_counter(description),
            }
            parm_type = _short_parameter_type(runtime.parm_type)
            if parm_type is not None:
                parameter["type"] = parm_type
            if runtime.multiparm:
                parameter["multiparm"] = True
            parameters.append(parameter)

        for documented in record.parameter_docs:
            if self._resolved_runtime_items(documented, links_by_doc, runtime_by_id):
                continue
            parameters.append(
                {
                    "ordinal": documented.ordinal,
                    "label": documented.label,
                    "tokens": self.token_counter(documented.description),
                }
            )

        def ports(direction: str) -> list[dict[str, object]]:
            values = self._ports(record, direction)
            return [
                {
                    "label": item.label,
                    "tokens": self.token_counter(item.description),
                }
                for item in values
            ]

        related = [
            target
            for item in record.related
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

    def _runtime_parameter_descriptions(
        self,
        parameter_docs: Sequence[NodeParameterDoc],
        links_by_doc: dict[str, list[NodeParameterLink]],
        runtime_by_id: dict[str, NodeParameter],
    ) -> dict[str, str]:
        descriptions: dict[str, list[str]] = {}
        for documented in sorted(parameter_docs, key=lambda item: item.ordinal):
            for runtime in self._resolved_runtime_items(
                documented, links_by_doc, runtime_by_id
            ):
                values = descriptions.setdefault(runtime.parameter_id, [])
                if documented.description and documented.description not in values:
                    values.append(documented.description)
        return {key: "\n\n".join(values) for key, values in descriptions.items()}

    def _resolved_runtime_items(
        self,
        documented: NodeParameterDoc,
        links_by_doc: dict[str, list[NodeParameterLink]],
        runtime_by_id: dict[str, NodeParameter],
    ) -> list[NodeParameter]:
        links = sorted(
            links_by_doc.get(documented.doc_parameter_id, []),
            key=lambda item: item.ordinal,
        )
        result: list[NodeParameter] = []
        for link in links:
            runtime = runtime_by_id.get(link.parameter_id)
            if runtime is None or not runtime.runtime_present:
                continue
            if runtime.parm_id.strip():
                result.append(runtime)
        return result

    def _parameter_detail(
        self,
        node_type: str,
        key: str,
        runtime_parameters: Sequence[NodeParameter],
        parameter_docs: Sequence[NodeParameterDoc],
        links_by_doc: dict[str, list[NodeParameterLink]],
        runtime_by_id: dict[str, NodeParameter],
        descriptions_by_parameter: dict[str, str],
    ) -> dict[str, object]:
        for runtime in runtime_parameters:
            if runtime.parm_id == key:
                return {
                    "description": descriptions_by_parameter.get(
                        runtime.parameter_id, ""
                    )
                }

        unresolved_by_ordinal: dict[int, NodeParameterDoc] = {}
        for documented in parameter_docs:
            runtime_items = self._resolved_runtime_items(
                documented, links_by_doc, runtime_by_id
            )
            if not runtime_items:
                unresolved_by_ordinal[documented.ordinal] = documented

        try:
            ordinal_key = int(key)
        except ValueError:
            ordinal_key = None
        if ordinal_key is not None and ordinal_key in unresolved_by_ordinal:
            return {"description": unresolved_by_ordinal[ordinal_key].description}

        raise HouDocsError(
            "node_parameter_not_found",
            f"Node parameter documentation not found: {node_type}/parameters/{key}",
        )

    def _port_detail(
        self,
        node_type: str,
        detail_kind: str,
        key: str,
        record: NodeDocumentRecord,
        direction: str,
    ) -> dict[str, object]:
        try:
            index = int(key)
        except ValueError:
            index = -1
        values = self._ports(record, direction)
        if 0 <= index < len(values):
            return {"description": values[index].description}
        raise HouDocsError(
            "node_port_not_found",
            f"Node port documentation not found: {node_type}/{detail_kind}/{key}",
        )

    @staticmethod
    def _ports(record: NodeDocumentRecord, direction: str) -> list[NodePort]:
        values = [item for item in record.ports if item.direction == direction]
        values.sort(key=lambda item: item.ordinal)
        return values
